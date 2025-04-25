import joblib
import pathlib
import dask
import os
import xarray as xr
import pandas as pd
import numpy as np
import variables
import cftime
import concurrent.futures

from fastprogress.fastprogress import master_bar, progress_bar

scratch = pathlib.Path(os.environ["SCRATCH"]) / "dor"
joblib_cache_dir = scratch / "joblib"

joblib_cache_dir.mkdir(parents=True, exist_ok=True)

memory = joblib.Memory(joblib_cache_dir, verbose=0)


def save_to_netcdf(
    ds: xr.Dataset,
    out_filepath: str,
) -> None:
    ds.to_netcdf(out_filepath, format="NETCDF4")


def get_year_and_month(ds):
    value = ds.time_bound.isel(d2=0).data.item()
    year = value.year
    month = value.month
    return year, month


def set_coords(ds: xr.Dataset) -> xr.Dataset:
    return ds.set_coords(variables.COORDS)


def get_case_metadata(case: str, df: pd.DataFrame) -> pd.Series:
    case_metadata = df.loc[case]
    return case_metadata


def add_additional_coords(ds: xr.Dataset, case: str, case_metadata: pd.Series):
    polygon_master = int(case_metadata.polygon_master)
    if polygon_master < 0 or polygon_master > 689:
        raise ValueError(
            f"Polygon id must be in range [0, 690). Found polygon_id={polygon_master}"
        )

    # add as an integer coordinate
    polygon_id_coord = xr.DataArray(
        name="polygon_id",
        dims="polygon_id",
        data=[polygon_master],
        attrs={"long_name": "polygon ID"},
    )

    # injenction date
    injection_date_coord = xr.DataArray(
        data=[
            cftime.DatetimeNoLeap.strptime(
                case_metadata.start_date, "%Y-%m", calendar="noleap", has_year_zero=True
            )
        ],
        dims=["injection_date"],
        attrs={"long_name": "injection date"},
    )

    # add elapsed time coord
    year, month = get_year_and_month(ds)
    current_year = (
        1999 + int(year) - int("0347")
    )  # all simulations start in the same year
    current_time = cftime.datetime(
        year=current_year,
        month=int(month),
        day=1,
        calendar="noleap",
        has_year_zero=True,
    )
    # print(f'current_date: {current_time}')

    injection_date = injection_date_coord.data[0]

    elapsed_time = current_time - injection_date

    elapsed_time_coord = xr.DataArray(
        data=[elapsed_time],
        dims=["elapsed_time"],
    )

    renamed = ds.drop_indexes("time").rename_dims(time="elapsed_time")

    return renamed.assign_coords(
        polygon_id=polygon_id_coord,
        injection_date=injection_date_coord,
        elapsed_time=elapsed_time_coord,
    )


def expand_ensemble_dims(ds: xr.Dataset) -> xr.Dataset:
    """Add new dimensions across the ensemble"""

    copied = ds.copy()

    # all data variables should be ensemble variables
    for name in list(ds.data_vars):
        copied[name] = copied[name].expand_dims(["polygon_id", "injection_date"])

    # absolute time is a function of injection_date because of the different starting times
    copied["time"] = copied["time"].expand_dims(["injection_date"])
    copied["time_bound"] = copied["time_bound"].expand_dims(["injection_date"])

    return copied


def compute_anomalies(ds: xr.Dataset) -> xr.Dataset:
    """Subtract counterfactual from experimental values, and leave only these anomalies in the resulting dataset."""

    # do this manually instead of a loop over variable names because there are too many variable names that don't follow a consistent pattern

    def compute_anomaly_for_variable(ds, name, alt_name, new_name):
        ds[new_name] = ds[name] - ds[alt_name]
        ds[new_name].attrs = ds[name].attrs
        ds = ds.drop_vars([name, alt_name], errors="raise")
        return ds

    ds = compute_anomaly_for_variable(
        ds, name="DIC", alt_name="DIC_ALT_CO2", new_name="DIC_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="ALK", alt_name="ALK_ALT_CO2", new_name="ALK_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="FG_CO2", alt_name="FG_ALT_CO2", new_name="FG_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="PH", alt_name="PH_ALT_CO2", new_name="PH_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="CO2STAR", alt_name="CO2STAR_ALT_CO2", new_name="CO2STAR_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="CO3", alt_name="CO3_ALT_CO2", new_name="CO3_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="pH_3D", alt_name="pH_3D_ALT_CO2", new_name="pH_3D_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="DCO2STAR", alt_name="DCO2STAR_ALT_CO2", new_name="DCO2STAR_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="pCO2SURF", alt_name="pCO2SURF_ALT_CO2", new_name="pCO2SURF_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds, name="DpCO2", alt_name="DpCO2_ALT_CO2", new_name="DpCO2_ANOM"
    )
    ds = compute_anomaly_for_variable(
        ds,
        name="DIC_zint_100m",
        alt_name="DIC_ALT_CO2_zint_100m",
        new_name="DIC_ANOM_zint_100m",
    )
    ds = compute_anomaly_for_variable(
        ds,
        name="ALK_zint_100m",
        alt_name="ALK_ALT_CO2_zint_100m",
        new_name="ALK_ANOM_zint_100m",
    )
    ds = compute_anomaly_for_variable(
        ds,
        name="tend_zint_100m_DIC",
        alt_name="tend_zint_100m_DIC_ALT_CO2",
        new_name="tend_zint_100m_DIC_ANOM",
    )
    ds = compute_anomaly_for_variable(
        ds,
        name="tend_zint_100m_ALK",
        alt_name="tend_zint_100m_ALK_ALT_CO2",
        new_name="tend_zint_100m_ALK_ANOM",
    )
    ds = compute_anomaly_for_variable(
        ds, name="STF_ALK", alt_name="STF_ALK_ALT_CO2", new_name="STF_ALK_ANOM"
    )

    return ds


def set_encoding(ds: xr.Dataset) -> xr.Dataset:
    # ds = ds.drop_encoding()

    # merge encodings to include existing time encoding as well as previous compression encoding
    for name, var in ds.variables.items():
        # avoids some very irritating behaviour causing the netCDF files to be internally chunked
        if "original_shape" in ds[name].encoding:
            del ds[name].encoding["original_shape"]

        if np.issubdtype(
            var.dtype, np.floating
        ):  # don't try to compress things that aren't floats
            ds[name].encoding["zlib"] = True
            ds[name].encoding["complevel"] = 4

        if var.ndim == 6:
            _3D_CHUNKS = (1, 1, 1, 60, 384, 320)
            # ds[name] = ds[name].chunk(_3D_CHUNKS)
            ds[name].encoding["chunksizes"] = _3D_CHUNKS
        elif var.ndim == 5:
            _2D_CHUNKS = (1, 1, 1, 384, 320)
            # ds[name] = ds[name].chunk(_2D_CHUNKS)
            ds[name].encoding["chunksizes"] = _2D_CHUNKS

    return ds


def load_case_dataset(
    filepath: str | pathlib.Path,
    case: str,
    case_metadata: pd.Series,
) -> xr.Dataset:
    ds = (
        xr.open_dataset(filepath, engine="netcdf4", decode_timedelta=True)
        .pipe(set_coords)
        .pipe(add_additional_coords, case, case_metadata)
        .pipe(expand_ensemble_dims)
        # .pipe(compute_anomalies)
        .pipe(set_encoding)
    )
    return ds


def open_compress_and_save_file(
    filepath: str | pathlib.Path,
    out_path_prefix: str | pathlib.Path,
    case: str,
    case_metadata: pd.Series,
) -> None:
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
        pathlib.Path(out_path_prefix) / f"{padded_polygon_id}/{padded_injection_month}/"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_filepath = (
        out_dir
        / f"smyle.cdr-atlas-v0.glb-dor.{padded_polygon_id}-{padded_injection_year}-{padded_injection_month}.pop.h.{padded_year}-{padded_month}.nc"
    )
    save_to_netcdf(ds, out_filepath=out_filepath)
    print(f"""
🎉 Processing Complete! 🎉
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Polygon ID:       {padded_polygon_id}
💉 Injection Date:   {padded_injection_year}-{padded_injection_month}
📅 Processed Period: {padded_year}-{padded_month}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📁 Input File:
   {filepath}
📁 Output File:
   {out_filepath}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ File saved successfully!
    """)

    ds.close()
    del ds
    return out_filepath


@memory.cache
def glob_nc_files(base_path: str | pathlib.Path, case: str):
    base_path = pathlib.Path(base_path)
    print("Globbing files (this may take a while)...")
    pattern = base_path / case / "ocn" / "hist" / "*.pop.h.*.nc"
    nc_files = sorted(base_path.glob(str(pattern.relative_to(base_path))))

    return nc_files


@memory.cache
def _process_single_case_no_dask(
    *, case: str, case_metadata: pd.Series, out_path_prefix: str, data_dir_path: str
):
    nc_files = glob_nc_files(base_path=data_dir_path, case=case)
    results = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=dask.system.CPU_COUNT
    ) as executor:
        future_tasks = [
            executor.submit(
                open_compress_and_save_file, file, out_path_prefix, case, case_metadata
            )
            for file in nc_files
        ]
        gen = progress_bar(
            concurrent.futures.as_completed(future_tasks), total=len(nc_files)
        )
        for task in gen:
            results.append(task.result())
    return results


def process_cases(
    data_dir_path: str,
    out_path_prefix: str,
    done_cases: list[str],
    df: pd.DataFrame,
):
    mb = master_bar(done_cases)
    for case in mb:
        mb.main_bar.comment = f"Processing {case}"
        case_metadata = get_case_metadata(case, df)
        _process_single_case_no_dask(
            case=case,
            case_metadata=case_metadata,
            out_path_prefix=out_path_prefix,
            data_dir_path=data_dir_path,
        )
        mb.write(f"Finished processing case: {case}")
