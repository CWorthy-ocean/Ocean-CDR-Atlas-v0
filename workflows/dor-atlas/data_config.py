import pathlib
import os


def get_scratch_dir():
    scratch = pathlib.Path(os.environ["SCRATCH"]) / "dor"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def get_dask_log_dir():
    dask_log_directory = pathlib.Path(os.environ["SCRATCH"]) / "dask" / "logs"
    dask_log_directory.mkdir(parents=True, exist_ok=True)
    return str(dask_log_directory)


def get_dask_local_dir():
    dask_local_directory = pathlib.Path(os.environ["SCRATCH"]) / "dask" / "local-dir"
    dask_local_directory.mkdir(parents=True, exist_ok=True)
    return str(dask_local_directory)


def get_compressed_data_dir(parent_dir):
    out_dir = pathlib.Path(parent_dir) / "compressed"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def get_data_archive_dir():
    return pathlib.Path(
        "/global/cfs/projectdirs/m4746/Projects/Ocean-CDR-Atlas-v0/data/archive"
    )
