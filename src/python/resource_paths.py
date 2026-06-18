from __future__ import annotations

from pathlib import Path


HYDROFABRIC_DIR = "hydrofabric"
FORCING_DIR = "forcing"
LEGACY_DATA_DIR = "data"


def find_gpkg_file(basin_dir: str | Path) -> Path:
    """Return the single geopackage for a basin resource directory."""
    basin_dir = Path(basin_dir)
    hydrofabric_candidates = sorted((basin_dir / HYDROFABRIC_DIR).glob("*.gpkg"))
    legacy_candidates = sorted((basin_dir / LEGACY_DATA_DIR).glob("*.gpkg"))
    candidates = hydrofabric_candidates or legacy_candidates

    if not candidates:
        raise FileNotFoundError(
            f"No geopackage found in {basin_dir / HYDROFABRIC_DIR} "
            f"or {basin_dir / LEGACY_DATA_DIR}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple geopackages found for {basin_dir}: "
            f"{', '.join(str(path) for path in candidates)}"
        )
    return candidates[0]


def has_gpkg_file(basin_dir: str | Path) -> bool:
    basin_dir = Path(basin_dir)
    for dirname in (HYDROFABRIC_DIR, LEGACY_DATA_DIR):
        if any((basin_dir / dirname).glob("*.gpkg")):
            return True
    return False


def forcing_dir_for_basin(
    basin_dir: str | Path,
    start_year: int,
    end_year: int,
) -> Path:
    return Path(basin_dir) / FORCING_DIR / f"{start_year}_to_{end_year}"


def forcing_dir_for_gpkg(
    gpkg_file: str | Path,
    start_year: int,
    end_year: int,
) -> Path:
    gpkg_file = Path(gpkg_file)
    if gpkg_file.parent.name in {HYDROFABRIC_DIR, LEGACY_DATA_DIR}:
        basin_dir = gpkg_file.parent.parent
    else:
        basin_dir = gpkg_file.parent
    return forcing_dir_for_basin(basin_dir, start_year, end_year)
