from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def select_netcdf_forcing_file(
    forcing_dir: str | Path,
    *,
    prefer_corrected: bool = True,
) -> Path:
    forcing_dir = Path(forcing_dir)

    if prefer_corrected:
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
