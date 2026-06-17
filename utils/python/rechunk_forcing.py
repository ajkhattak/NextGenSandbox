from __future__ import annotations

"""Rechunk NextGen NetCDF forcing files for faster ngen reads.

Acknowledgement: this utility is adapted from Austin Raney (Lynker) forcing
rechunking approach.
"""

import argparse
from pathlib import Path

import numpy as np
import xarray as xr


def compute_chunk_size(catchments: int, timesteps: int) -> tuple[int, int]:
    """Return chunk sizes tuned for catchment-by-time forcing variables."""
    if catchments < 1:
        raise ValueError("catchments must be >= 1")
    if timesteps < 1:
        raise ValueError("timesteps must be >= 1")

    # Default HDF5 chunk cache is commonly 16 MiB (2^24). With eight forcing
    # variables and 8-byte doubles, 2^18 values per variable is a conservative
    # target chunk budget.
    max_values_power = 18
    max_catchment_power = 14

    catchment_power = min(
        int(np.ceil(np.log2(catchments))),
        max_catchment_power,
    )
    catchment_chunk = min(2**catchment_power, catchments)
    time_chunk = min(2**max_values_power // catchment_chunk, timesteps)

    return catchment_chunk, time_chunk


def _clean_encoding(encoding: dict[str, object]) -> dict[str, object]:
    cleaned = dict(encoding)
    for key in ("source", "szip", "zstd", "bzip2", "blosc", "coordinates"):
        cleaned.pop(key, None)
    cleaned["zlib"] = True
    return cleaned


def _forcing_encodings(
    dataset: xr.Dataset,
    catchment_chunk: int,
    time_chunk: int,
) -> dict[str, dict[str, object]]:
    encodings = {
        name: _clean_encoding(variable.encoding)
        for name, variable in dataset.variables.items()
        if name in ("time", "Time")
    }

    for name in dataset.variables:
        if name in ("time", "Time", "ids", "catchment-id"):
            continue

        variable = dataset[name]
        if "catchment-id" not in variable.dims or "time" not in variable.dims:
            continue

        chunks = []
        for dimension in variable.dims:
            if dimension == "catchment-id":
                chunks.append(catchment_chunk)
            elif dimension == "time":
                chunks.append(time_chunk)
            else:
                chunks.append(dataset.sizes[dimension])
        encodings[name] = {"chunksizes": tuple(chunks)}

    return encodings


def rechunk_forcing(
    infile: Path,
    output_path: Path | None = None,
    force: bool = False,
) -> Path:
    """Write a rechunked copy of *infile* and return its path."""
    infile = infile.expanduser().resolve()
    if not infile.exists():
        raise FileNotFoundError(f"Forcing file does not exist: {infile}")
    if infile.suffix != ".nc":
        raise ValueError(f"Expected a NetCDF .nc file: {infile}")

    if output_path is None:
        output_path = infile.parent / f"{infile.stem}_rechunked.nc"
    else:
        output_path = output_path.expanduser().resolve()

    if output_path == infile:
        raise ValueError("Output path must be different from input path")

    if output_path.exists():
        if not force and output_path.stat().st_mtime >= infile.stat().st_mtime:
            return output_path
        output_path.unlink()

    with xr.open_dataset(infile) as dataset:
        required_dimensions = {"catchment-id", "time"}
        missing = required_dimensions.difference(dataset.sizes)
        if missing:
            raise ValueError(
                f"Forcing file {infile} is missing dimension(s): "
                f"{', '.join(sorted(missing))}"
            )

        if "Time" in dataset:
            dataset = dataset.assign_coords(
                time=(["time"], dataset.Time.isel({"catchment-id": 0}).values)
            )

        catchment_chunk, time_chunk = compute_chunk_size(
            dataset.sizes["catchment-id"],
            dataset.sizes["time"],
        )
        encodings = _forcing_encodings(dataset, catchment_chunk, time_chunk)
        dataset.to_netcdf(output_path, encoding=encodings)

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rechunk a NextGen NetCDF forcing file."
    )
    parser.add_argument(
        "-i",
        "--infile",
        required=True,
        type=Path,
        help="Path to the forcing NetCDF file.",
    )
    parser.add_argument(
        "-o",
        "--outfile",
        type=Path,
        help="Optional output path. Defaults to '<input>_rechunked.nc'.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the rechunked file even when it is current.",
    )
    args = parser.parse_args()

    output_path = rechunk_forcing(args.infile, args.outfile, args.force)
    print(output_path)


if __name__ == "__main__":
    main()
