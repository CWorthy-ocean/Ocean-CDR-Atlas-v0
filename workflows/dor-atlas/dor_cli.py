import pathlib
import sys
import traceback

# Import our modules
import research_data
import typer
import vis_pyramid
from dask.diagnostics.progress import ProgressBar
from rich.console import Console
from rich.table import Table

pbar = ProgressBar()
pbar.register()

# Create app with unified CLI for both modules
app = typer.Typer(
    help="CDR Atlas Data Processing Tool: Process and build visualization data"
)

# Set up Rich console for nice formatting
console = Console()

try:
    from dor_config import DORConfig

    config = DORConfig()

except ImportError:
    typer.echo(
        "Error: Missing data_config module. Please ensure it's in your PYTHONPATH."
    )
    sys.exit(1)

# Add the subcommands from both modules
app.add_typer(
    research_data.app, name="research-data", help="Process research-grade data"
)
app.add_typer(vis_pyramid.app, name="vis", help="Generate visualization pyramids")


def setup_directories():
    """Setup and return required directories"""
    scratch = config.scratch_dir
    joblib_cache_dir = scratch / "joblib"
    joblib_cache_dir.mkdir(parents=True, exist_ok=True)

    return {
        "scratch": scratch,
        "joblib_cache_dir": joblib_cache_dir,
        "dask_log_dir": config.dask_log_dir,
        "dask_local_dir": config.dask_local_dir,
        "compressed_data_dir": config.compressed_data_dir,
        "data_archive_dir": config.data_archive_dir_path,
        "store_1_path": config.store_1_path,
        "store_2_path": config.store_2_path,
        "cumulative_fg_co2_percent_store_path": config.cumulative_fg_co2_percent_store_path,
    }


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
            if not exists and "store" not in name:
                all_dirs_exist = False

            table.add_row(
                name,
                str(path),
                "[green]✓ Exists[/green]" if exists else "[red]✗ Missing[/red]",
            )

        console.print(table)

        # Check for required modules
        modules = ["atlas", "pop_tools", "variables", "ndpyramid"]
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
