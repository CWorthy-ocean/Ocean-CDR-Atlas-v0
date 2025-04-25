import concurrent.futures
import datetime
import os
import pathlib
import sys
import traceback
from typing import Optional

import cftime
import joblib
import loky
import numpy as np
import pandas as pd
import pop_tools
import typer
import variables
import xarray as xr
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
from rich.table import Table



# Set up console for nice formatting
console = Console()


# Append parent directory to path to import atlas
parent_dir = pathlib.Path.cwd().parent
sys.path.append(str(parent_dir))
try:
    import atlas
except ImportError:
    typer.echo("Error: Atlas module not found. Make sure it's in the parent directory.")
    sys.exit(1)

# Create a Typer app for this module
app = typer.Typer(help="Process and compress ocean model output data")

# Initialize joblib memory cache
memory = None


def setup_memory(cache_dir):
    """Setup joblib memory cache"""
    global memory
    memory = joblib.Memory(cache_dir, verbose=0)
    return memory


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


def get_case_metadata(case: str, df: pd.DataFrame) -> pd.Series | pd.DataFrame:
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
            out_filepath=str(out_filepath),
        )

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


def process_single_case_no_dask(
    *,
    case: str,
    case_metadata: pd.Series,
    out_path_prefix: str,
    data_dir_path: str,
    max_workers: int | None = None,
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
                if verbose:
                    console.print(f"Processed: {result}", style="green")
            except Exception as _:
                console.print(
                    f"Error processing file: {traceback.format_exc()}", style="bold red"
                )

    return results


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Research-grade data processing tools for CDR Atlas."""
    if ctx.invoked_subcommand is None:
        console.print(
            "[yellow]No command specified. Use --help to see available commands.[/yellow]"
        )


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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """Process a single case, compressing and saving all associated files."""
    # Set up directories
    from dor_cli import setup_directories, setup_environment

    setup_environment()

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

        func = memory.cache(process_single_case_no_dask)
        func(
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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """Process all available cases or a filtered subset."""
    # Set up directories
    from dor_cli import setup_directories, setup_environment

    setup_environment()

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

                func = memory.cache(process_single_case_no_dask)
                func(
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


if __name__ == "__main__":
    app()
