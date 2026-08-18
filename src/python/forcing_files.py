from __future__ import annotations

import glob
import os
import shlex
import subprocess
import sys
import warnings
from pathlib import Path

import pandas as pd
import xarray as xr


def select_netcdf_forcing_file(
    forcing_dir: str | Path,
    *,
    use_corrected: bool = True,
) -> Path:
    forcing_dir = Path(forcing_dir)

    if use_corrected:
        files = sorted(forcing_dir.glob("*_corrected.nc"))
        expected = "*_corrected.nc"
    else:
        files = sorted(
            path
            for path in forcing_dir.glob("*.nc")
            if "_corrected" not in path.name and "_rechunked" not in path.name
        )
        expected = "*.nc excluding *_corrected.nc and *_rechunked.nc"

    if not files:
        raise FileNotFoundError(
            f"No NetCDF forcing file found in {forcing_dir}. Expected {expected}."
        )
    if len(files) > 1:
        raise ValueError(
            f"Multiple NetCDF forcing files found in {forcing_dir}: "
            f"{', '.join(path.name for path in files)}"
        )
    return files[0]


def resolve_netcdf_forcing_pattern(
    path_pattern: str | Path,
    *,
    rechunk_enabled: bool = False,
) -> Path:
    """Resolve a rendered external NetCDF pattern to exactly one file."""
    expanded = os.path.expandvars(os.path.expanduser(str(path_pattern)))
    if not glob.has_magic(expanded):
        return Path(expanded)

    if not expanded.lower().endswith(".nc"):
        raise ValueError(
            "A wildcard forcings.forcing_dir must resolve directly to .nc files"
        )

    files = [
        Path(path)
        for path in sorted(glob.glob(expanded, recursive=True))
        if Path(path).is_file() and Path(path).suffix.lower() == ".nc"
    ]

    if rechunk_enabled and len(files) > 1:
        base_files = [path for path in files if not path.stem.endswith("_rechunked")]
        if len(base_files) == 1:
            base_file = base_files[0]
            expected_rechunked = (
                base_file.parent / f"{base_file.stem}_rechunked.nc"
            )
            if set(files) == {base_file, expected_rechunked}:
                files = [base_file]

    if not files:
        raise FileNotFoundError(
            f"No NetCDF forcing file found using {expanded}. Characters outside "
            "<gage_id> are matched literally; adjust the surrounding characters "
            "or use * where different separators should be accepted."
        )
    if len(files) > 1:
        raise ValueError(
            f"Multiple NetCDF forcing files found using {expanded}: "
            f"{', '.join(str(path) for path in files)}. A custom forcing "
            "template must match exactly one file per gage; make the template "
            "more specific. When rechunk is enabled, only one base file and "
            "its exact Sandbox-generated _rechunked sibling are treated as "
            "one forcing resource."
        )
    return files[0]


def select_source_netcdf_forcing_file(forcing_dir: str | Path) -> Path | None:
    forcing_dir = Path(forcing_dir)
    files = sorted(
        path
        for path in forcing_dir.glob("*.nc")
        if "_corrected" not in path.name and "_rechunked" not in path.name
    )

    if len(files) == 1:
        return files[0]
    if not files:
        print(
            "Can't correct the forcing data, source NetCDF file does not exist. "
            f"Directory: {forcing_dir}"
        )
        return None

    print(
        "Can't correct the forcing data, more than one source NetCDF file "
        f"exists in {forcing_dir}. Files found: {files}"
    )
    return None


def prepare_rechunked_forcing_file(
    forcing_file: str | Path,
    *,
    sandbox_dir: str | Path,
    enabled: bool = True,
) -> Path:
    forcing_path = Path(forcing_file)
    if not enabled or forcing_path.suffix != ".nc":
        return forcing_path
    if forcing_path.stem.endswith("_rechunked"):
        return forcing_path

    rechunked_path = forcing_path.parent / f"{forcing_path.stem}_rechunked.nc"
    if (
        rechunked_path.exists()
        and rechunked_path.stat().st_mtime >= forcing_path.stat().st_mtime
    ):
        return rechunked_path

    chunk_py = Path(sandbox_dir) / "utils/python/rechunk_forcing.py"
    if not chunk_py.is_file():
        raise FileNotFoundError(f"Forcing rechunk utility not found: {chunk_py}")

    print(f"Rechunking forcing data: {forcing_path}")
    subprocess.run(
        [sys.executable, str(chunk_py), "-i", str(forcing_path)],
        check=True,
    )
    if not rechunked_path.exists():
        raise FileNotFoundError(
            f"Rechunked forcing file was not created: {rechunked_path}"
        )
    return rechunked_path


def select_prepared_forcing_file(
    forcing_file: str | Path,
    *,
    rechunk_enabled: bool = True,
) -> Path:
    """Select forcing prepared by the forcing step without modifying it."""
    forcing_path = Path(forcing_file)
    if not rechunk_enabled or forcing_path.suffix.lower() != ".nc":
        return forcing_path
    if forcing_path.stem.endswith("_rechunked"):
        return forcing_path

    rechunked_path = forcing_path.parent / f"{forcing_path.stem}_rechunked.nc"
    refresh_command = (
        'python "$SANDBOX_DIR/utils/python/rechunk_forcing.py" '
        f"-i {shlex.quote(str(forcing_path))} --force"
    )
    if not rechunked_path.exists():
        raise FileNotFoundError(
            f"Rechunked forcing file does not exist: {rechunked_path}. "
            "Run 'sandbox --forc -i <config>' before generating configurations "
            "or refresh only this existing forcing file with:\n"
            f"  {refresh_command}\n"
            "Alternatively, set forcings.rechunk: false."
        )
    if rechunked_path.stat().st_mtime < forcing_path.stat().st_mtime:
        warnings.warn(
            "The source forcing file has a newer modification time than its "
            f"rechunked sibling: {rechunked_path}. This can happen when files "
            "are copied or transferred in a different order, so Sandbox will "
            "continue using the existing rechunked file. If the source content "
            "was actually changed, refresh only this file with:\n"
            f"  {refresh_command}",
            UserWarning,
            stacklevel=2,
        )
    return rechunked_path


def netcdf_forcing_time_bounds(forcing_file: str | Path):
    """Read the first and last timestamps without loading the forcing array."""
    forcing_path = Path(forcing_file)
    with xr.open_dataset(forcing_path, decode_times=False) as dataset:
        time_name = next(
            (
                name
                for name in ("Time", "time")
                if name in dataset.variables
            ),
            None,
        )
        if time_name is None:
            raise ValueError(
                f"NetCDF forcing file has no Time or time variable: "
                f"{forcing_path}"
            )

        time_variable = dataset[time_name]
        if not time_variable.dims or time_variable.size == 0:
            raise ValueError(
                f"NetCDF forcing time variable is empty: {forcing_path}"
            )

        time_dimension = (
            "time" if "time" in time_variable.dims else time_variable.dims[-1]
        )
        indexers = {
            dimension: 0
            for dimension in time_variable.dims
            if dimension != time_dimension
        }
        indexers[time_dimension] = [0, -1]
        raw_bounds = time_variable.isel(indexers).values

        units = time_variable.attrs.get("units")
        if not units:
            raise ValueError(
                f"NetCDF forcing time variable has no units attribute: "
                f"{forcing_path}"
            )
        calendar = time_variable.attrs.get("calendar", "standard")
        decoded = xr.coding.times.decode_cf_datetime(
            raw_bounds,
            units,
            calendar,
        )

    return pd.Timestamp(decoded[0]), pd.Timestamp(decoded[-1])
