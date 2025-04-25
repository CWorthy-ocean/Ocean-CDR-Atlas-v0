import concurrent.futures
import datetime
import os
import pathlib
import sys
import traceback
from typing import Optional

import cftime
import dask
import dask.array as dsa
import fsspec
import joblib
import loky
import ndpyramid
import numpy as np
import pandas as pd
import pop_tools
import typer
import xarray as xr
import zarr
from dask.diagnostics import ProgressBar
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
from rich.table import Table

import variables

try:
    from data_config import (
        get_compressed_data_dir,
        get_dask_local_dir,
        get_dask_log_dir,
        get_data_archive_dir,
        get_scratch_dir,
    )
except ImportError:
    typer.echo(
        "Error: Missing data_config module. Please ensure it's in your PYTHONPATH."
    )
    sys.exit(1)


pbar = ProgressBar()
pbar.register()
# Set up Rich console for nice formatting
console = Console()


app = typer.Typer(
    help="CDR Atlas Data Processing Tool: Process and compress ocean model output data"
)

# Append parent directory to path to import atlas
parent_dir = pathlib.Path.cwd().parent
sys.path.append(str(parent_dir))
try:
    import atlas
except ImportError:
    typer.echo("Error: Atlas module not found. Make sure it's in the parent directory.")
    sys.exit(1)


# Initialize directories
def setup_directories():
    """Setup and return required directories"""
    scratch = get_scratch_dir()
    joblib_cache_dir = scratch / "joblib"
    joblib_cache_dir.mkdir(parents=True, exist_ok=True)

    return {
        "scratch": scratch,
        "joblib_cache_dir": joblib_cache_dir,
        "dask_log_dir": get_dask_log_dir(),
        "dask_local_dir": get_dask_local_dir(),
        "compressed_data_dir": get_compressed_data_dir(),
        "data_archive_dir": get_data_archive_dir(),
    }


# Initialize joblib memory cache
memory = None


def setup_memory(cache_dir):
    """Setup joblib memory cache"""
    global memory
    memory = joblib.Memory(cache_dir, verbose=0)
    return memory


# Keep your existing functions but decorate the ones we'll use as commands
def get_cases_df(today=datetime.datetime.today().date()):
    """Get DataFrame of available cases from the atlas."""
    try:
        calc = atlas.global_irf_map(cdr_forcing="DOR", vintage="001")
        done_cases = calc.df.index.to_list()
        if "smyle.cdr-atlas-v0.control.001" in done_cases:
            done_cases.remove("smyle.cdr-atlas-v0.control.001")
        done_cases = sorted(done_cases)
        df = calc.df.loc[done_cases]
        return df
    except Exception as _:
        console.print(
            f"[bold red]Error getting cases: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


def set_coords(ds: xr.Dataset) -> xr.Dataset:
    """Set coordinates on the dataset."""
    return ds.set_coords(variables.COORDS)


def get_year_and_month(ds):
    """Extract year and month from dataset time coordinate."""
    value = ds.time.data.item()
    year = value.year
    month = value.month
    return year, month


def get_case_metadata(case: str, df: pd.DataFrame) -> pd.Series:
    """Get metadata for a specific case."""
    case_metadata = df.loc[case]
    return case_metadata


def save_to_netcdf(ds: xr.Dataset, out_filepath: str) -> None:
    """Save dataset to NetCDF file."""
    ds.to_netcdf(out_filepath, format="NETCDF4")


def open_gx1v7_dataset(path: str | pathlib.Path):
    """Open and preprocess a GX1V7 grid dataset."""

    def preprocess(ds):
        return ds.set_coords(["KMT", "TAREA"]).reset_coords(
            ["ULONG", "ULAT"], drop=True
        )

    grid = pop_tools.get_grid("POP_gx1v7")

    try:
        ds = xr.open_dataset(path, engine="netcdf4", decode_times=False)
        # Fix time
        tb_var = ds.time.attrs["bounds"]
        time_units = ds.time.units
        calendar = ds.time.calendar

        ds["time"] = cftime.num2date(
            ds[tb_var].mean("d2"),
            units=time_units,
            calendar=calendar,
        )
        ds.time.encoding.update(
            dict(
                calendar=calendar,
                units=time_units,
            )
        )

        # Add ∆t
        d2 = ds[tb_var].dims[-1]
        ds["time_delta"] = ds[tb_var].diff(d2).squeeze()
        ds = ds.set_coords("time_delta")
        ds.time_delta.attrs["long_name"] = "∆t"
        ds.time_delta.attrs["units"] = "days"

        # Replace coords to account for land-block elimination
        ds["TLONG"] = grid.TLONG
        ds["TLAT"] = grid.TLAT
        ds["KMT"] = ds.KMT.fillna(0)

        # Add area field
        ds["area_m2"] = ds.TAREA * 1e-4
        ds.area_m2.encoding = dict(**ds.TAREA.encoding)
        ds.area_m2.attrs = dict(**ds.TAREA.attrs)
        ds.area_m2.attrs["units"] = "m^2"

        return ds
    except Exception as _:
        console.print(
            f"[bold red]Error opening dataset {path}: {traceback.format_exc()}[/bold red]"
        )
        raise


def set_encoding(ds: xr.Dataset) -> xr.Dataset:
    """Set encoding for compression."""
    for name, var in ds.variables.items():
        # Avoid some very irritating behaviour causing the netCDF files to be internally chunked
        if "original_shape" in ds[name].encoding:
            del ds[name].encoding["original_shape"]

        if np.issubdtype(var.dtype, np.floating):
            # Only compress floats
            ds[name].encoding["zlib"] = True
            ds[name].encoding["complevel"] = 4

        if var.ndim == 6:
            _3D_CHUNKS = (1, 1, 1, 60, 384, 320)
            ds[name].encoding["chunksizes"] = _3D_CHUNKS
        elif var.ndim == 5:
            _2D_CHUNKS = (1, 1, 1, 384, 320)
            ds[name].encoding["chunksizes"] = _2D_CHUNKS

    return ds


def add_polygon_id_coord(ds: xr.Dataset, case_metadata: pd.Series):
    """Add polygon ID coordinate to dataset."""
    polygon_master = int(case_metadata.polygon_master)
    if polygon_master < 0 or polygon_master > 689:
        raise ValueError(
            f"Polygon id must be in range [0, 690). Found polygon_id={polygon_master}"
        )
    # Add as an integer coordinate
    polygon_id_coord = xr.DataArray(
        name="polygon_id",
        dims="polygon_id",
        data=[polygon_master],
        attrs={"long_name": "polygon ID"},
    ).astype("int32")
    return ds.assign_coords(polygon_id=polygon_id_coord)


def add_injection_date_coord(ds: xr.Dataset, case_metadata: pd.Series):
    """Add injection date coordinate to dataset."""
    injection_date_coord = xr.DataArray(
        data=[
            cftime.DatetimeNoLeap.strptime(
                case_metadata.start_date, "%Y-%m", calendar="noleap", has_year_zero=True
            )
        ],
        dims=["injection_date"],
        attrs={"long_name": "injection date"},
    )

    return ds.assign_coords(injection_date=injection_date_coord)


def expand_ensemble_dims(ds: xr.Dataset) -> xr.Dataset:
    """Add new dimensions across the ensemble."""
    copied = ds.copy()

    # All data variables should be ensemble variables
    for name in list(ds.data_vars):
        copied[name] = copied[name].expand_dims(["polygon_id", "injection_date"])

    # Absolute time is a function of injection_date because of the different starting times
    copied["time"] = copied["time"].expand_dims(["injection_date"])
    copied["time_bound"] = copied["time_bound"].expand_dims(["injection_date"])

    return copied


def add_elapsed_time_coord(ds: xr.Dataset):
    """Add elapsed time coordinate."""
    # Extract year and month
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
    return (
        ds.drop_indexes("time")
        .rename_dims(time="elapsed_time")
        .assign_coords(elapsed_time=current_time.data - ds.injection_date.data)
    )


def drop_unnecessary_time_coords(ds: xr.Dataset):
    """Drop unnecessary time coordinates."""
    return ds.reset_coords(["time", "time_bound", "time_delta"], drop=True)


def load_case_dataset(
    filepath: str | pathlib.Path,
    case: str,
    case_metadata: pd.Series,
) -> xr.Dataset:
    """Load and process a case dataset."""
    ds = (
        open_gx1v7_dataset(filepath)
        .pipe(set_coords)
        .pipe(add_polygon_id_coord, case_metadata)
        .pipe(add_injection_date_coord, case_metadata)
        .pipe(add_elapsed_time_coord)
        .pipe(expand_ensemble_dims)
    )
    return ds


def open_compress_and_save_file(
    filepath: str | pathlib.Path,
    out_path_prefix: str | pathlib.Path,
    case: str,
    case_metadata: pd.Series,
) -> pathlib.Path:
    """Open, compress, and save a single file."""
    try:
        ds = load_case_dataset(
            filepath=filepath,
            case=case,
            case_metadata=case_metadata,
        )

        polygon_id = ds.polygon_id.data.item()
        injection_month = ds.injection_date.dt.month.data.item()
        injection_year = ds.injection_date.dt.year.data.item()
        year, month = get_year_and_month(ds)

        # Pad the values with zeros
        padded_polygon_id = f"{polygon_id:03d}"
        padded_injection_month = f"{injection_month:02d}"
        padded_injection_year = f"{injection_year:04d}"
        padded_year = f"{year:04d}"
        padded_month = f"{month:02d}"

        out_dir = (
            pathlib.Path(out_path_prefix)
            / f"{padded_polygon_id}/{padded_injection_month}/"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        out_filepath = (
            out_dir
            / f"smyle.cdr-atlas-v0.glb-dor.{padded_polygon_id}-{padded_injection_year}-{padded_injection_month}.pop.h.{padded_year}-{padded_month}.nc"
        )

        save_to_netcdf(
            ds.pipe(drop_unnecessary_time_coords).pipe(set_encoding),
            out_filepath=out_filepath,
        )

        # Create success message
        # Only print success message if verbose flag is set
        # We'll add this option to our commands later

        ds.close()
        del ds
        return out_filepath

    except Exception as _:
        console.print(
            f"[bold red]Error processing file {filepath}: {traceback.format_exc()}[/bold red]"
        )
        raise


def glob_nc_files(base_path: str | pathlib.Path, case: str):
    """Find all NetCDF files for a case."""
    base_path = pathlib.Path(base_path)
    console.print("Globbing files (this may take a while)...", style="yellow")
    pattern = base_path / case / "ocn" / "hist" / "*.pop.h.*.nc"
    nc_files = sorted(base_path.glob(str(pattern.relative_to(base_path))))
    console.print(f"Found {len(nc_files)} files for case {case}", style="green")
    return nc_files


def process_single_case_with_dask(
    *, case: str, case_metadata: pd.Series, out_path_prefix: str, data_dir_path: str
):
    """Process a single case using dask for parallelization."""
    nc_files = glob_nc_files(base_path=data_dir_path, case=case)
    tasks = []
    for file in nc_files:
        tasks.append(
            dask.delayed(open_compress_and_save_file)(
                file, out_path_prefix, case, case_metadata
            )
        )
    results = dask.compute(*tasks, retries=4)
    return results


def process_single_case_no_dask(
    *,
    case: str,
    case_metadata: pd.Series,
    out_path_prefix: str,
    data_dir_path: str,
    max_workers: int = None,
    verbose: bool = False,
):
    """Process a single case using ProcessPoolExecutor."""
    nc_files = glob_nc_files(base_path=data_dir_path, case=case)
    results = []

    if not max_workers:
        max_workers = os.cpu_count()

    with loky.ProcessPoolExecutor(max_workers=max_workers, timeout=120) as executor:
        future_tasks = [
            executor.submit(
                open_compress_and_save_file, file, out_path_prefix, case, case_metadata
            )
            for file in nc_files
        ]

        for future in concurrent.futures.as_completed(future_tasks):
            try:
                result = future.result()
                results.append(result)
                # progress.update(task, advance=1)
                if verbose:
                    console.print(f"Processed: {result}", style="green")
            except Exception as _:
                console.print(
                    f"Error processing file: {traceback.format_exc()}", style="bold red"
                )

    return results


def integrate_column(var: xr.DataArray, depth_element: xr.DataArray) -> xr.DataArray:
    return (var * depth_element).sum(dim="z_t")


def reduction(ds):
    with xr.set_options(keep_attrs=True):
        dic_surf = ds.DIC.isel(z_t=0)
        ds.ALK.isel(z_t=0)
        dic_delta_surf = ds.DIC.isel(z_t=0) - ds.DIC_ALT_CO2.isel(z_t=0)

        pH_delta_surf = ds.PH - ds.PH_ALT_CO2
        pco2_delta_surf = ds.pCO2SURF - ds.pCO2SURF_ALT_CO2

        fg_co2_delta_surf = ds.FG_CO2 - ds.FG_ALT_CO2

        dic_column_integrated = integrate_column(ds.DIC, ds["dz"] * 1e-3)
        dic_delta_column_integrated = dic_column_integrated - integrate_column(
            ds.DIC_ALT_CO2, ds["dz"] * 1e-3
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
    """
    - DIC anomaly/full field (only at surface)
        - delta: `ds.DIC.isel(z_t=0) - ds.DIC_ALT_CO2.isel(z_t=0)`
        - experimental: `ds.DIC.isel(z_t=0)`
    - DIC (column integrated)
        - delta: `integrate_column(ds.DIC) - integrate_column(ds.DIC_ALT_CO2)`
        - experimental: `integrate_column(ds.DIC)`
    - pCO2 (only at surface)
        - delta: `ds.pCO2SURF - ds.pCO2SURF_ALT_CO2`
        - experimental: `ds.pCO2SURF`
    - Flux (only at surface)
        - delta: `ds.FG_CO2 - ds.FG_ALT_CO2`
        - experimental: `ds.FG_CO2`
    - Surface pH (only at surface)
        - delta: `ds.PH - ds.PH_ALT_CO2`
        - experimental: `ds.PH`

    """
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


def set_compression_encoding(dt: xr.DataTree) -> xr.DataTree:
    compressor = zarr.Zlib(level=1)

    for node in dt.subtree:
        for name, var in node.variables.items():
            # avoid using NaN as a fill value, and avoid overflow errors in encoding
            if np.issubdtype(var.dtype, np.integer):
                node[name].encoding = {
                    "compressor": compressor,
                    "_FillValue": 2_147_483_647,
                }
            elif var.dtype == np.dtype("float32"):
                node[name].encoding = {
                    "compressor": compressor,
                    "_FillValue": 9.969209968386869e36,
                }
            else:
                node[name].encoding = {"compressor": compressor}

            node[name].encoding.pop("preferred_chunks", None)

    return dt


def _create_template_store2(
    existing_oae_pyramid: xr.DataTree,
    variables: list[str],
    levels: int = 2,
) -> xr.DataTree:
    """Create a template for visualization store with empty data arrays.

    Parameters
    ----------
    existing_oae_pyramid : xr.DataTree
        Existing pyramid structure to use as a template
    variables : list[str]
        List of variables to include in the template
    levels : int, default=2
        Number of zoom levels for the template pyramid

    Returns
    -------
    xr.DataTree
        Template DataTree with the specified structure
    """

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


def validate_template_vis_store2(path: str) -> None:
    """Validate the template visualization store structure and encoding.

    Parameters
    ----------
    path : str
        Path to the template visualization store
    """
    placeholder = xr.open_datatree(path, engine="zarr", chunks={})

    for level in ["0", "1"]:
        console.print(f"[bold cyan]Level {level} variables:[/bold cyan]")
        for v in placeholder[level].ds.variables:
            console.print(f"  • {v}:", placeholder[level][v].encoding)
        console.print("\n")


def generate_padded_ids(start: int, end: int) -> list[str]:
    """Generate zero-padded string IDs for a range of integers.

    Parameters
    ----------
    start : int
        Starting ID (inclusive)
    end : int
        Ending ID (exclusive)

    Returns
    -------
    list[str]
        List of zero-padded IDs as strings
    """
    return [f"{i:03d}" for i in range(start, end)]


def generate_padded_months(months: list[int]) -> list[str]:
    """Generate zero-padded string months.

    Parameters
    ----------
    months : list[int]
        List of month numbers

    Returns
    -------
    list[str]
        List of zero-padded month strings
    """
    return [f"{month:02d}" for month in months]


def get_nc_glob_pattern(data_dir: str, polygon_id: str, injection_month: str) -> str:
    """Generate glob pattern for NetCDF files.

    Parameters
    ----------
    data_dir : str
        Base directory for data files
    polygon_id : str
        Padded polygon ID
    injection_month : str
        Padded injection month

    Returns
    -------
    str
        Glob pattern to use with xarray.open_mfdataset
    """
    return f"{data_dir}/{polygon_id}/{injection_month}/*.nc"


def process_and_create_pyramid(
    polygon_id: str,
    injection_month: str,
    data_dir: str,
    store_path: str,
    weights_store: str,
    levels: int = 2,
) -> None:
    """Process data and create visualization pyramid.

    Parameters
    ----------
    polygon_id : str
        Padded polygon ID
    injection_month : str
        Padded injection month
    data_dir : str
        Base directory for data files
    store_path : str
        Path to the zarr store
    levels : int, default=2
        Number of pyramid levels to generate
    weights_store : str
        Path to the weights zarr store (if available)
    """
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
            bands_ds = (
                ds.pipe(reduction)
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
            # console.print(f"The pyramid datatree: {pyramid}", style="blue")
            pyramid.to_zarr(store_path, region="auto", mode="r+")

            return pyramid

    except Exception as exc:
        console.print(
            f"[bold red]Error processing polygon_id={polygon_id}, "
            f"injection_month={injection_month}: {traceback.format_exc()}[/bold red]"
        )
        raise exc


@app.command()
def build_vis_pyramid(
    output_store: str = typer.Argument(..., help="Path to the output zarr store"),
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
    """Build visualization pyramids for CDR Atlas data.

    This command processes NetCDF files for specified polygon IDs and injection months,
    applies reduction operations, and builds multi-level visualization pyramids that
    are saved to a zarr store.
    """
    # Set up directories
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
                memory.cache(process_and_create_pyramid)(
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
def create_template_vis_pyramid(
    output_path: str = typer.Argument(
        ...,
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
    """Create a template for the visualization store.

    This command creates an empty template Zarr store with the structure needed
    for visualization data. The template includes all necessary dimensions and
    coordinates but contains empty data arrays that can be filled later.
    """
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

        console.print(f"Saving to {output_path}", style="blue")
        template.to_zarr(
            output_path, compute=False, zarr_format=2, consolidated=True, mode="w"
        )

        console.print("Validating template structure...", style="blue")
        validate_template_vis_store2(output_path)

        console.print(f"Template saved to {output_path}", style="green")
        console.print("Template validation complete", style="green")
        console.print("All done!", style="green")

    except Exception as _:
        console.print(
            f"[bold red]Error creating template visualization store: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


# Typer commands
@app.command()
def list_cases(
    polygon_filter: Optional[int] = typer.Option(
        None, "--polygon", "-p", help="Filter by polygon ID"
    ),
    limit: int = typer.Option(
        10, "--limit", "-l", help="Limit the number of cases to display"
    ),
):
    """List all available cases with their metadata."""
    console.print("Fetching available cases...", style="blue")

    try:
        df = get_cases_df()

        if polygon_filter is not None:
            df = df[df.polygon_master == polygon_filter]

        if df.empty:
            console.print("No cases found matching the criteria.", style="yellow")
            raise typer.Exit()

        # Limit the number of rows if needed
        if limit and len(df) > limit:
            df = df.head(limit)

        table = Table(title="Available Cases")

        table.add_column("Case", style="cyan", no_wrap=True)
        table.add_column("Polygon ID", style="magenta")

        for case, row in df.iterrows():
            table.add_row(
                case,
                str(row.polygon_master),
            )

        console.print(table)
        console.print(
            f"Displaying {len(df)} out of {len(get_cases_df())} total cases",
            style="blue",
        )

    except Exception as _:
        console.print(
            f"Error listing cases: {traceback.format_exc()}", style="bold red"
        )
        raise typer.Exit(1)


@app.command()
def process_case(
    case: str = typer.Argument(..., help="The case identifier to process"),
    output_dir: Optional[str] = typer.Option(
        None, "--output-dir", "-o", help="Output directory for processed files"
    ),
    data_dir: Optional[str] = typer.Option(
        None, "--data-dir", "-d", help="Directory containing input data files"
    ),
    workers: int = typer.Option(
        None, "--workers", "-w", help="Number of worker processes to use"
    ),
    use_dask: bool = typer.Option(
        False, "--use-dask", help="Use Dask instead of concurrent.futures"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """Process a single case, compressing and saving all associated files."""
    # Set up directories
    dirs = setup_directories()
    memory = setup_memory(dirs["joblib_cache_dir"])

    # Use provided paths or defaults
    out_path_prefix = output_dir if output_dir else dirs["compressed_data_dir"]
    data_dir_path = data_dir if data_dir else dirs["data_archive_dir"]

    console.print(f"Processing case: [bold cyan]{case}[/bold cyan]")
    console.print(f"Input directory: {data_dir_path}")
    console.print(f"Output directory: {out_path_prefix}")

    try:
        df = get_cases_df()
        if case not in df.index:
            console.print(
                f"[bold red]Error: Case '{case}' not found in available cases[/bold red]"
            )
            raise typer.Exit(1)

        case_metadata = get_case_metadata(case, df)

        # Process based on selected method
        if use_dask:
            console.print("Using Dask for parallel processing", style="blue")
            memory.cache(process_single_case_with_dask)(
                case=case,
                case_metadata=case_metadata,
                out_path_prefix=out_path_prefix,
                data_dir_path=data_dir_path,
            )
        else:
            memory.cache(process_single_case_no_dask)(
                case=case,
                case_metadata=case_metadata,
                out_path_prefix=out_path_prefix,
                data_dir_path=data_dir_path,
                max_workers=workers,
                verbose=verbose,
            )

        console.print(f"[bold green]Successfully processed case: {case}[/bold green]")

    except Exception as _:
        console.print(
            f"[bold red]Error processing case {case}: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


@app.command()
def process_all(
    output_dir: Optional[str] = typer.Option(
        None, "--output-dir", "-o", help="Output directory for processed files"
    ),
    data_dir: Optional[str] = typer.Option(
        None, "--data-dir", "-d", help="Directory containing input data files"
    ),
    polygon_filter: Optional[int] = typer.Option(
        None, "--polygon", "-p", help="Filter by polygon ID"
    ),
    max_cases: int = typer.Option(
        None, "--max-cases", help="Maximum number of cases to process"
    ),
    workers: int = typer.Option(
        None, "--workers", "-w", help="Number of worker processes to use"
    ),
    use_dask: bool = typer.Option(
        False, "--use-dask", help="Use Dask instead of concurrent.futures"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """Process all available cases or a filtered subset."""
    # Set up directories
    dirs = setup_directories()
    memory = setup_memory(dirs["joblib_cache_dir"])

    # Use provided paths or defaults
    out_path_prefix = output_dir if output_dir else dirs["compressed_data_dir"]
    data_dir_path = data_dir if data_dir else dirs["data_archive_dir"]

    console.print(f"Processing cases from: {data_dir_path}")
    console.print(f"Saving output to: {out_path_prefix}")

    try:
        df = get_cases_df()

        # Apply filters
        if polygon_filter is not None:
            df = df[df.polygon_master == polygon_filter]
            console.print(f"Filtered to cases with polygon ID: {polygon_filter}")

        if max_cases and len(df) > max_cases:
            df = df.head(max_cases)
            console.print(f"Limited to {max_cases} cases")

        if df.empty:
            console.print("No cases found matching the criteria.", style="yellow")
            raise typer.Exit()

        cases = df.index.to_list()
        console.print(f"Processing {len(cases)} cases")

        # Process each case
        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            main_task = progress.add_task("Processing all cases", total=len(cases))

            for case in cases:
                progress.update(main_task, description=f"Processing case: {case}")

                case_metadata = get_case_metadata(case, df)

                # Process based on selected method
                if use_dask:
                    memory.cache(process_single_case_with_dask)(
                        case=case,
                        case_metadata=case_metadata,
                        out_path_prefix=out_path_prefix,
                        data_dir_path=data_dir_path,
                    )
                else:
                    memory.cache(process_single_case_no_dask)(
                        case=case,
                        case_metadata=case_metadata,
                        out_path_prefix=out_path_prefix,
                        data_dir_path=data_dir_path,
                        max_workers=workers,
                        verbose=verbose,
                    )

                progress.update(main_task, advance=1)

        console.print("[bold green]Successfully processed all cases![/bold green]")

    except Exception as _:
        console.print(
            f"[bold red]Error processing cases: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


@app.command()
def setup_environment():
    """Setup and validate the processing environment."""
    try:
        dirs = setup_directories()

        # Check if all directories exist
        all_dirs_exist = True
        table = Table(title="Environment Setup")
        table.add_column("Directory", style="cyan")
        table.add_column("Path", style="yellow")
        table.add_column("Status", style="green")

        for name, path in dirs.items():
            exists = pathlib.Path(path).exists()
            if not exists:
                all_dirs_exist = False

            table.add_row(
                name,
                str(path),
                "[green]✓ Exists[/green]" if exists else "[red]✗ Missing[/red]",
            )

        console.print(table)

        # Check for required modules
        modules = ["atlas", "pop_tools", "variables"]
        missing_modules = []

        for module in modules:
            try:
                __import__(module)
            except ImportError:
                missing_modules.append(module)

        if missing_modules:
            console.print("[bold red]Missing required modules:[/bold red]")
            for module in missing_modules:
                console.print(f"  - {module}")
        else:
            console.print("[bold green]All required modules available[/bold green]")

        if all_dirs_exist and not missing_modules:
            console.print(
                "[bold green]Environment setup is complete and valid![/bold green]"
            )
        else:
            console.print(
                "[bold yellow]Environment setup incomplete. Please address the issues above.[/bold yellow]"
            )

    except Exception:
        console.print(
            f"[bold red]Error setting up environment: {traceback.format_exc()}[/bold red]"
        )
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
