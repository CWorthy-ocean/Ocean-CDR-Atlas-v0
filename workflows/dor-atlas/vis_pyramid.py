import os
import traceback
from typing import Optional

import cftime
import dask
import dask.array as dsa
import dask.config
import fsspec
import joblib
import loky
import ndpyramid
import numcodecs
import numpy as np
import typer
import xarray as xr
from dor_config import DORConfig
from rich.console import Console

# Set up console for nice formatting
console = Console()
config = DORConfig()


# Create a Typer app for this module
app = typer.Typer(help="Build visualization pyramids for CDR Atlas data")

# Initialize joblib memory cache
memory = None


def setup_memory(cache_dir):
    """Setup joblib memory cache"""
    global memory
    memory = joblib.Memory(cache_dir, verbose=0)
    return memory


def integrate_column_mol(
    var: xr.DataArray, depth_element: xr.DataArray, ssh: xr.DataArray
) -> xr.DataArray:
    """
    Integrate a variable over the vertical column and convert to mol/m².

    Parameters:
    -----------
    var : xr.DataArray
        Variable to integrate with units of mmol/m³
    depth_element : xr.DataArray
        Thickness of each layer with units of centimeters
    ssh : xr.DataArray
        Sea Surface Height with units of centimeters

    Returns:
    --------
    xr.DataArray
        Integrated variable with units of mol/m²
    """
    # convert depth_element and ssh from cm to m
    depth_m = depth_element * 0.01  # cm to m
    ssh_m = ssh * 0.01  # cm to m

    # integrate over depth
    a = (var * depth_m).sum(dim="z_t")  # mmol/m²
    b = var.isel(z_t=0).squeeze() * ssh_m  # mmol/m²

    # leave conversion from mmol/m² to mol/m² to the frontend
    result = a + b

    result.attrs.update(
        {
            "units": "mmol/m^2",
            "long_name": f"Column integrated {var.attrs.get('long_name', 'variable')}",
        }
    )

    return result


def reduction(ds: xr.Dataset, ssh: xr.DataArray) -> xr.Dataset:
    """Apply reduction operations to the dataset."""
    with xr.set_options(keep_attrs=True):
        dic_surf = ds.DIC.isel(z_t=0)
        ds.ALK.isel(z_t=0)
        dic_delta_surf = ds.DIC.isel(z_t=0) - ds.DIC_ALT_CO2.isel(z_t=0)

        pH_delta_surf = ds.PH - ds.PH_ALT_CO2
        pco2_delta_surf = ds.pCO2SURF - ds.pCO2SURF_ALT_CO2

        fg_co2_delta_surf = ds.FG_CO2 - ds.FG_ALT_CO2

        dic_column_integrated = integrate_column_mol(ds.DIC, ds["dz"], ssh)
        dic_delta_column_integrated = dic_column_integrated - integrate_column_mol(
            ds.DIC_ALT_CO2, ds["dz"], ssh
        )

    dso = (
        xr.Dataset(
            dict(
                FG_CO2_SURF=ds.FG_CO2,
                FG_CO2_DELTA_SURF=fg_co2_delta_surf,
                DIC_SURF=dic_surf,
                DIC_DELTA_SURF=dic_delta_surf,
                DIC_COLUMN_INTEGRATED=dic_column_integrated,
                DIC_DELTA_COLUMN_INTEGRATED=dic_delta_column_integrated,
                PH_SURF=ds.PH,
                PH_DELTA_SURF=pH_delta_surf,
                pCO2_DELTA_SURF=pco2_delta_surf,
                pCO2_SURF=ds.pCO2SURF,
            )
        )
    ).drop_vars(["TLONG", "TLAT"])
    dso.attrs["case"] = ds.title
    return dso


def concatenate_into_bands(ds: xr.Dataset) -> xr.Dataset:
    """Concatenate the dataset into bands."""
    bands_ds = xr.Dataset(coords=ds.coords)

    bands_ds["DIC_SURF"] = xr.concat(
        [ds["DIC_DELTA_SURF"], ds["DIC_SURF"]],
        dim=xr.DataArray(name="band", data=["delta", "experimental"], dims="band"),
    )
    bands_ds["DIC"] = xr.concat(
        [ds["DIC_DELTA_COLUMN_INTEGRATED"], ds["DIC_COLUMN_INTEGRATED"]],
        dim=xr.DataArray(name="band", data=["delta", "experimental"], dims="band"),
    )
    bands_ds["PH"] = xr.concat(
        [ds["PH_DELTA_SURF"], ds["PH_SURF"]],
        dim=xr.DataArray(name="band", data=["delta", "experimental"], dims="band"),
    )
    bands_ds["FG"] = xr.concat(
        [ds["FG_CO2_DELTA_SURF"], ds["FG_CO2_SURF"]],
        dim=xr.DataArray(name="band", data=["delta", "experimental"], dims="band"),
    )
    bands_ds["pCO2SURF"] = xr.concat(
        [ds["pCO2_DELTA_SURF"], ds["pCO2_SURF"]],
        dim=xr.DataArray(name="band", data=["delta", "experimental"], dims="band"),
    )

    return bands_ds.isel(z_t=0, missing_dims="warn")


def reshape_into_month_year(ds: xr.Dataset) -> xr.Dataset:
    """Reshape the dataset into month-year structure."""
    with dask.config.set(**{"array.slicing.split_large_chunks": False}):
        reshaped = (
            ds.assign_coords(
                month=xr.DataArray(
                    data=np.concatenate([np.arange(1, 13)] * 15), dims="elapsed_time"
                ).astype("int32"),
                year=xr.DataArray(
                    data=np.repeat(np.arange(1, 16), 12), dims="elapsed_time"
                ).astype("int32"),
            )
            .swap_dims(
                elapsed_time="month",
            )
            .set_index(
                monthyear=("month", "year"),
            )
            .unstack(
                "monthyear",
            )
        )

    to_drop_coords = set(reshaped.coords).difference(
        set(
            [
                "band",
                "elapsed_time",
                "injection_date",
                "month",
                "polygon_id",
                "year",
                "ULONG",
                "ULAT",
            ]
        )
    )
    reshaped["injection_date"] = reshaped.injection_date.dt.month.astype("float32")

    return reshaped.drop_vars(to_drop_coords)


def set_compression_encoding(ds: xr.Dataset) -> xr.Dataset:
    compressor = numcodecs.Zlib(level=1)

    for name, var in ds.variables.items():
        # avoid using NaN as a fill value, and avoid overflow errors in encoding
        if np.issubdtype(var.dtype, np.integer):
            ds[name].encoding = {"compressor": compressor, "_FillValue": 2_147_483_647}
        elif var.dtype == np.dtype("float32"):
            ds[name].encoding = {
                "compressor": compressor,
                "_FillValue": 9.969209968386869e36,
            }
        else:
            ds[name].encoding = {"compressor": compressor}

        ds[name].encoding.pop("preferred_chunks", None)

    return ds


def set_datatree_compression_encoding(dt: xr.DataTree) -> xr.DataTree:
    """Set compression encoding for the DataTree."""

    for node in dt.subtree:
        node.ds = set_compression_encoding(node.ds)

    return dt


def _create_template_store1() -> xr.Dataset:
    """Create a template for visualization store with empty data arrays."""
    store1b_chunks_encoding_per_variable = {
        "DOR_efficiency": {
            "chunks": {"polygon_id": 1, "injection_date": 1, "elapsed_time": 180}
        },  # polygon_id: 1 injection_date: 1 elapsed_time: 180
        "polygon_id": {"chunks": {"polygon_id": 690}},  # polygon_id: 1
        "injection_date": {"chunks": {"injection_date": 1}},  # injection_date: 1
        "elapsed_time": {"chunks": {"elapsed_time": 180}},  # elapsed_time: 180
    }
    sizes_all_dims = {
        "elapsed_time": 180,
        "polygon_id": 690,
        "injection_date": 4,
    }

    placeholder = xr.Dataset()
    placeholder["elapsed_time"] = xr.DataArray(
        np.arange(180), dims=["elapsed_time"], attrs={"units": "months"}
    ).astype("int32")
    placeholder["polygon_id"] = xr.DataArray(
        np.arange(690),
        dims=["polygon_id"],
        attrs={"long_name": "Polygon ID"},
    ).astype("int32")
    placeholder["injection_date"] = xr.DataArray(
        np.array([1, 4, 7, 10]),
        dims=["injection_date"],
        attrs={"long_name": "injection date", "units": "month of 1999"},
    ).astype("int32")

    var_chunks = store1b_chunks_encoding_per_variable["DOR_efficiency"]["chunks"]
    var_dims = list(var_chunks.keys())
    var_sizes = {d: s for d, s in sizes_all_dims.items() if d in var_dims}
    var_shape = tuple(var_sizes.values())
    ordered_var_dims = list(var_sizes.keys())

    placeholder["DOR_efficiency"] = xr.DataArray(
        dsa.empty(
            shape=var_shape,
            chunks=var_chunks,
            dtype="float32",
        ),
        dims=ordered_var_dims,
    )
    placeholder = (
        placeholder.pipe(set_compression_encoding)
        .chunk(polygon_id=-1, injection_date=1, elapsed_time=-1)
        .transpose("elapsed_time", "polygon_id", "injection_date")
    )

    return placeholder


def _create_template_store2(
    existing_oae_pyramid: xr.DataTree,
    variables: list[str],
    levels: int = 2,
) -> xr.DataTree:
    """Create a template for visualization store with empty data arrays."""
    plevels = {}
    for entry in range(levels):
        level = str(entry)
        ds = xr.Dataset()

        # Create dimension coordinates
        ds["band"] = xr.DataArray(["delta", "experimental"], dims=["band"])

        ds["polygon_id"] = xr.DataArray(np.arange(690), dims="polygon_id").astype(
            "int32"
        )

        ds["injection_date"] = xr.DataArray(
            [1, 4, 7, 10], dims="injection_date"
        ).astype("int32")

        ds["month"] = xr.DataArray(np.arange(1, 13), dims="month").astype("int32")

        ds["year"] = xr.DataArray(np.arange(1, 16), dims="year").astype("int32")

        # Copy spatial coordinates from existing pyramid
        ds["x"] = existing_oae_pyramid[level].ds["x"]
        ds["y"] = existing_oae_pyramid[level].ds["y"]

        # Create elapsed time coordinate
        ds["elapsed_time"] = xr.DataArray(
            existing_oae_pyramid[level].ds["elapsed_time"].data.compute(),
            dims=["month", "year"],
        ).astype("int32")

        ds = ds.set_coords(["elapsed_time"])

        # Create empty arrays for each variable
        for variable in variables:
            ds[variable] = xr.DataArray(
                dsa.empty(
                    shape=existing_oae_pyramid[level].ds["DIC"].shape,
                    chunks=existing_oae_pyramid[level].ds["DIC"].chunks,
                    dtype="float32",
                ),
                dims=existing_oae_pyramid[level].ds["DIC"].dims,
            )

        plevels[level] = ds.chunk(
            polygon_id=1, band=1, injection_date=1, month=1, year=-1, x=128, y=128
        )

        # Copy attributes from existing pyramid
        plevels[level].attrs = existing_oae_pyramid[level].ds.attrs

    # Create root node and final datatree
    root = xr.Dataset(attrs={})
    plevels["/"] = root
    template = xr.DataTree.from_dict(plevels)
    template.attrs = existing_oae_pyramid.attrs

    template = ndpyramid.utils.add_metadata_and_zarr_encoding(template, levels=levels)

    return template


def _create_template_cumulative_fg_co2_percent_store() -> xr.Dataset:
    """Create a template for cumulative FG CO2 percent store with empty data arrays."""
    chunks_encoding_per_variable = {
        "FG_CO2_percent_cumulative": {
            "chunks": {
                "polygon_id": 690,
                "injection_date": 1,
                "elapsed_time": 180,
                "dist2center": 3,
            }
        },
        "polygon_id": {"chunks": {"polygon_id": 690}},
        "injection_date": {"chunks": {"injection_date": 1}},
        "elapsed_time": {"chunks": {"elapsed_time": 180}},
        "dist2center": {"chunks": {"dist2center": 3}},
    }
    sizes_all_dims = {
        "elapsed_time": 180,
        "polygon_id": 690,
        "injection_date": 4,
        "dist2center": 3,
    }

    placeholder = xr.Dataset()
    placeholder["elapsed_time"] = xr.DataArray(
        np.arange(180), dims=["elapsed_time"], attrs={"units": "months"}
    ).astype("int32")
    placeholder["polygon_id"] = xr.DataArray(
        np.arange(690),
        dims=["polygon_id"],
        attrs={"long_name": "Polygon ID"},
    ).astype("int32")
    placeholder["injection_date"] = xr.DataArray(
        np.array([1, 4, 7, 10]),
        dims=["injection_date"],
        attrs={"long_name": "injection date", "units": "month of 1999"},
    ).astype("int32")

    placeholder["dist2center"] = xr.DataArray(
        [500000, 1000000, 2000000],
        dims=["dist2center"],
        attrs={
            "long_name": "Distance to center",
            "units": "m",
        },
    ).astype("int32")

    var_chunks = chunks_encoding_per_variable["FG_CO2_percent_cumulative"]["chunks"]
    var_dims = list(var_chunks.keys())
    var_sizes = {d: s for d, s in sizes_all_dims.items() if d in var_dims}
    var_shape = tuple(var_sizes.values())
    ordered_var_dims = list(var_sizes.keys())

    placeholder["cumulative_fg_co2_percent"] = xr.DataArray(
        dsa.empty(
            shape=var_shape,
            chunks=var_chunks,
            dtype="float32",
        ),
        dims=ordered_var_dims,
    )
    placeholder = (
        placeholder.pipe(set_compression_encoding)
        .chunk(polygon_id=-1, injection_date=1, elapsed_time=-1, dist2center=-1)
        .transpose("elapsed_time", "polygon_id", "injection_date", "dist2center")
    )
    placeholder.attrs["long_name"] = "Cumulative FG CO2 percent"
    placeholder.attrs["units"] = "percent"
    placeholder.attrs["description"] = (
        "Cumulative percent of CO2 uptake, within a time step and distance to center"
    )
    return placeholder


def print_template_dataset(ds: xr.Dataset) -> None:
    """Print the structure of the template dataset."""

    console.print(ds)
    console.print("\nTemplate dataset structure:")
    for var in ds.variables:
        console.print(f"  • {var}: {ds[var].encoding} ")
    console.print("\n")


def print_template_cumulative_fg_co2_percent_store(path: str) -> None:
    """Validate the template cumulative FG CO2 percent store structure."""

    console.print(f"Validating template structure:{path}...", style="blue")
    placeholder = xr.open_dataset(path, engine="zarr", chunks={})

    console.print("[bold cyan]Variables:[/bold cyan]")
    print_template_dataset(placeholder)

    placeholder.close()


def print_template_vis_store1(path: str) -> None:
    """Validate the template visualization store structure."""

    console.print(f"Validating template structure:{path}...", style="blue")
    placeholder = xr.open_dataset(path, engine="zarr", chunks={})

    console.print("[bold cyan]Variables:[/bold cyan]")
    print_template_dataset(placeholder)

    placeholder.close()


def print_template_vis_store2(path: str) -> None:
    """Validate the template visualization store structure."""

    console.print(f"Validating template structure:{path}...", style="blue")
    placeholder = xr.open_datatree(path, engine="zarr", chunks={})

    for level in ["0", "1"]:
        console.print(f"[bold cyan]Level {level} variables:[/bold cyan]")
        print_template_dataset(placeholder[level].ds)

    placeholder.close()


def generate_padded_ids(start: int, end: int) -> list[str]:
    """Generate zero-padded string IDs for a range of integers."""
    return [f"{i:03d}" for i in range(start, end)]


def generate_padded_months(months: list[int]) -> list[str]:
    """Generate zero-padded string months."""
    return [f"{month:02d}" for month in months]


def get_nc_glob_pattern(data_dir: str, polygon_id: str, injection_month: str) -> str:
    """Generate glob pattern for NetCDF files."""
    return f"{data_dir}/{polygon_id}/{injection_month}/*.nc"


def load_ssh_data(injection_month: str) -> xr.DataArray:
    """Load SSH data for a given injection month."""
    ssh_path = "/global/cfs/cdirs/m4746/Datasets/SMYLE-FOSI/ocn/proc/tseries/month_1/g.e22.GOMIPECOIAF_JRA-1p4-2018.TL319_g17.SMYLE.005.pop.h.SSH.030601-036812.nc"
    ds = xr.open_dataset(ssh_path, chunks={}, decode_timedelta=True)

    if int(injection_month) == 1:
        subset_slice = slice("0347-01", "0361-12")
    elif int(injection_month) == 4:
        subset_slice = slice("0347-04", "0362-03")
    elif int(injection_month) == 7:
        subset_slice = slice("0347-07", "0362-06")
    elif int(injection_month) == 10:
        subset_slice = slice("0347-10", "0362-09")
    else:
        raise ValueError(f"Invalid injection month: {injection_month}")
    ds = ds.sel(time=subset_slice)

    year = ds.time.dt.year
    month = ds.time.dt.month

    # Compute current year based on formula
    current_year = 1999 + year - int("0347")  # Equivalent to 1999 + year - 347

    # Create DataArray of datetime objects
    current_time = xr.DataArray(
        [
            cftime.datetime(y, m, 1, calendar="noleap", has_year_zero=True)
            for y, m in zip(current_year, month)
        ],
        dims="time",
        name="current_time",
    )

    injection_date_coord = xr.DataArray(
        data=[
            cftime.DatetimeNoLeap.strptime(
                f"1999-{injection_month}",
                "%Y-%m",
                calendar="noleap",
                has_year_zero=True,
            )
        ],
        dims=["injection_date"],
        attrs={"long_name": "injection date"},
    )

    ds = (
        ds.assign_coords(
            injection_date=injection_date_coord,
            elapsed_time=(current_time - injection_date_coord).squeeze(),
        )
        .drop_indexes("time")
        .swap_dims(time="elapsed_time")
        .drop_vars("time")
    )

    console.print(
        f"Loaded SSH data for injection month {ds.injection_date} \ntime_slice: {subset_slice}",
        style="blue",
    )

    return ds["SSH"]


def process_and_create_pyramid(
    polygon_id: str,
    injection_month: str,
    data_dir: str,
    store_path: str,
    weights_store: str,
    levels: int = 2,
) -> None:
    """Process data and create visualization pyramid."""
    try:
        path = get_nc_glob_pattern(data_dir, polygon_id, injection_month)
        console.print(f"Loading data from {path}", style="blue")

        with dask.config.set(
            pool=loky.ProcessPoolExecutor(max_workers=os.cpu_count() // 2, timeout=120)
        ):
            ds = xr.open_mfdataset(
                path,
                coords="minimal",
                combine="by_coords",
                data_vars="minimal",
                compat="override",
                decode_times=True,
                parallel=True,
                decode_timedelta=True,
            )
            ds = dask.optimize(ds)[0]

            console.print("Processing dataset through reduction pipeline", style="blue")
            ssh = load_ssh_data(injection_month)

            bands_ds = (
                ds.pipe(reduction, ssh)
                .pipe(concatenate_into_bands)
                .pipe(reshape_into_month_year)
            )

            console.print("Building visualization pyramid", style="blue")
            other_chunks = dict(
                month=1, year=-1, band=1, polygon_id=1, injection_date=1, x=128, y=128
            )

            if fsspec.get_mapper(weights_store).fs.exists(weights_store):
                console.print(
                    f"Using weights from {weights_store} for regridding", style="blue"
                )
                weights = xr.open_datatree(weights_store, engine="zarr", chunks={})

            else:
                console.print(
                    "No weights store provided or does not exist. "
                    "Weights will be generated on-the-fly.",
                    style="yellow",
                )
                weights = ndpyramid.regrid.generate_weights_pyramid(bands_ds, levels=2)
                weights.to_zarr(
                    weights_store, consolidated=True, zarr_format=2, mode="w"
                )

            pyramid = ndpyramid.pyramid_regrid(
                bands_ds,
                levels=levels,
                projection="web-mercator",
                parallel_weights=False,
                other_chunks=other_chunks,
                weights_pyramid=weights,
            )

            pyramid = dask.optimize(pyramid)[0]

            console.print(f"Saving pyramid to {store_path}", style="blue")
            pyramid.to_zarr(store_path, region="auto", mode="r+")

            return pyramid

    except Exception as exc:
        console.print(
            f"[bold red]Error processing polygon_id={polygon_id}, "
            f"injection_month={injection_month}: {traceback.format_exc()}[/bold red]"
        )
        raise exc


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Visualization pyramid tools for CDR Atlas."""
    if ctx.invoked_subcommand is None:
        console.print(
            "[yellow]No command specified. Use --help to see available commands.[/yellow]"
        )


@app.command()
def build_pyramid(
    output_store: str = typer.Option(
        config.store_2_path, help="Path to the output zarr store"
    ),
    weights_store: Optional[str] = typer.Option(
        f"{os.environ['SCRATCH']}/weights.zarr",
        "--weights-store",
        "-w",
        help="Path to the weights zarr store (optional)",
    ),
    polygon_ids: Optional[list[int]] = typer.Option(
        None, "--polygon-ids", "-p", help="Specific polygon IDs to process"
    ),
    polygon_range: Optional[list[int]] = typer.Option(
        None,
        "--polygon-range",
        "-pr",
        help="Range of polygon IDs to process (start, end)",
    ),
    injection_months: list[int] = typer.Option(
        [1, 4, 7, 10], "--injection-months", "-im", help="Injection months to process"
    ),
    input_dir: Optional[str] = typer.Option(
        None, "--input-dir", "-i", help="Directory containing processed NetCDF files"
    ),
    levels: int = typer.Option(
        2, "--levels", "-l", help="Number of pyramid levels to generate"
    ),
):
    """Build visualization pyramids for CDR Atlas data."""
    # Set up directories
    from dor_cli import setup_directories

    dirs = setup_directories()
    memory = setup_memory(dirs["joblib_cache_dir"])

    # Use provided input directory or default
    data_dir = input_dir if input_dir else dirs["compressed_data_dir"]

    console.print(
        f"Building visualization pyramids from data in: {data_dir}", style="blue"
    )
    console.print(f"Output zarr store: {output_store}", style="blue")

    try:
        # Determine which polygon IDs to process
        if polygon_ids:
            ids_to_process = polygon_ids
        elif polygon_range:
            start, end = polygon_range
            ids_to_process = list(range(start, end))
        else:
            ids_to_process = list(range(0, 690))

        padded_polygon_ids = [f"{polygon_id:03d}" for polygon_id in ids_to_process]
        padded_injection_months = generate_padded_months(injection_months)

        console.print(f"Processing {len(padded_polygon_ids)} polygon IDs", style="blue")
        console.print(
            f"Processing {len(padded_injection_months)} injection months", style="blue"
        )

        # Prepare all tasks
        tasks = []
        for polygon_id in padded_polygon_ids:
            for injection_month in padded_injection_months:
                tasks.append((polygon_id, injection_month))

        for polygon_id, injection_month in tasks:
            try:
                func = memory.cache(process_and_create_pyramid)
                func(
                    polygon_id=polygon_id,
                    injection_month=injection_month,
                    data_dir=data_dir,
                    store_path=output_store,
                    weights_store=weights_store,
                    levels=levels,
                )
                console.print(
                    f"Finished processing polygon_id={polygon_id}, injection_month={injection_month}",
                    style="green",
                )

            except Exception:
                console.print(
                    f"[bold red]Error processing {polygon_id}/{injection_month}: "
                    f"{traceback.format_exc()}[/bold red]"
                )

        console.print(
            "[bold green]Successfully built all visualization pyramids![/bold green]"
        )

    except Exception:
        console.print(
            f"[bold red]Error building visualization pyramids: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


@app.command()
def create_template_cumulative_fg_co2_percent_store(
    output_store: str = typer.Option(
        config.cumulative_fg_co2_percent_store_path,
        help="Output path for the template visualization store",
    ),
):
    """Create a template for the cumulative FG CO2 percent store."""
    try:
        console.print(
            "Creating template for cumulative FG CO2 percent store...", style="blue"
        )
        template = _create_template_cumulative_fg_co2_percent_store()

        template.to_zarr(
            output_store, compute=False, zarr_format=2, consolidated=True, mode="w"
        )

        print_template_cumulative_fg_co2_percent_store(output_store)

        console.print(f"Template saved to {output_store}", style="green")

    except Exception as _:
        console.print(
            f"[bold red]Error creating template visualization store: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


@app.command()
def create_template_store1(
    output_store: str = typer.Option(
        config.store_1_path,
        help="Output path for the template visualization store",
    ),
):
    """Create a template for the visualization store."""
    try:
        console.print("Creating template for store1...", style="blue")
        template = _create_template_store1()

        template.to_zarr(
            output_store, compute=False, zarr_format=2, consolidated=True, mode="w"
        )

        print_template_vis_store1(output_store)

        console.print(f"Template saved to {output_store}", style="green")

    except Exception as _:
        console.print(
            f"[bold red]Error creating template visualization store: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


@app.command()
def create_template_store2(
    output_store: str = typer.Option(
        config.store_2_path,
        help="Output path for the template visualization store",
    ),
    variables: list[str] = typer.Option(
        ["DIC", "DIC_SURF", "PH", "FG", "pCO2SURF"],
        "--variables",
        "-v",
        help="List of variables to include in the template",
    ),
    levels: int = typer.Option(
        2, "--levels", "-l", help="Number of zoom levels for the template pyramid"
    ),
):
    """Create a template for the visualization store."""
    try:
        console.print("Opening reference OAE pyramid...", style="blue")
        existing_oae_pyramid = xr.open_datatree(
            "s3://carbonplan-oae-efficiency/v2/store2.zarr/", engine="zarr", chunks={}
        )

        console.print(
            f"Creating template with variables: {', '.join(variables)}", style="blue"
        )
        template = _create_template_store2(
            existing_oae_pyramid=existing_oae_pyramid,
            variables=variables,
            levels=levels,
        )

        console.print(f"Created template with {len(template)} levels", style="green")
        console.print(template)

        console.print(f"Saving to {output_store}", style="blue")
        template.to_zarr(
            output_store, compute=False, zarr_format=2, consolidated=True, mode="w"
        )
        template.close()

        print_template_vis_store2(output_store)

        console.print(f"Template saved to {output_store}", style="green")
        console.print("Template validation complete", style="green")
        console.print("All done!", style="green")

    except Exception as _:
        console.print(
            f"[bold red]Error creating template visualization store: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
