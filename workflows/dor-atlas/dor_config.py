import functools
import os
import pathlib

import pydantic
import pydantic_settings


class DORConfig(pydantic_settings.BaseSettings):
    """Configuration class for the DOR Atlas workflow."""

    scratch_env: str = pydantic.Field(
        default_factory=lambda: os.environ.get("SCRATCH", "")
    )
    parent_data_dir: str = pydantic.Field(
        default="/global/cfs/projectdirs/m4746/Datasets/Ocean-CDR-Atlas-v0/DOR-Efficiency-Map"
    )
    data_archive_dir: str = pydantic.Field(
        default="/global/cfs/projectdirs/m4746/Projects/Ocean-CDR-Atlas-v0/data/archive"
    )

    store_1_path: str = pydantic.Field(
        default=f"{os.environ.get('SCRATCH', '')}/test/store1b.zarr"
    )
    store_2_path: str = pydantic.Field(
        default=f"{os.environ.get('SCRATCH', '')}/test/store2.zarr"
    )

    cumulative_fg_co2_percent_store_path: str = pydantic.Field(
        default=f"{os.environ.get('SCRATCH', '')}/test/cumulative_FG_CO2_percent.zarr"
    )

    class Config:
        env_prefix = "OCEAN_CDR_"
        case_sensitive = False

    @functools.cached_property
    def scratch_dir(self) -> pathlib.Path:
        """Get the DOR scratch directory and ensure it exists."""
        scratch = pathlib.Path(self.scratch_env) / "dor"
        scratch.mkdir(parents=True, exist_ok=True)
        return scratch

    @functools.cached_property
    def dask_log_dir(self) -> pathlib.Path:
        """Get the Dask logs directory and ensure it exists."""
        dask_log_directory = pathlib.Path(self.scratch_env) / "dask" / "logs"
        dask_log_directory.mkdir(parents=True, exist_ok=True)
        return dask_log_directory

    @functools.cached_property
    def dask_local_dir(self) -> pathlib.Path:
        """Get the Dask local directory and ensure it exists."""
        dask_local_directory = pathlib.Path(self.scratch_env) / "dask" / "local-dir"
        dask_local_directory.mkdir(parents=True, exist_ok=True)
        return dask_local_directory

    @functools.cached_property
    def compressed_data_dir(self) -> pathlib.Path:
        """Get the compressed data directory and ensure it exists."""
        out_dir = pathlib.Path(self.parent_data_dir) / "research-grade-compressed"
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    @functools.cached_property
    def data_archive_dir_path(self) -> pathlib.Path:
        """Get the data archive directory path."""
        return pathlib.Path(self.data_archive_dir)
