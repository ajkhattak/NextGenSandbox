from __future__ import annotations

from pathlib import Path


HYDROFABRIC_DIR = "hydrofabric"
FORCING_DIR = "forcing"
LEGACY_DATA_DIR = "data"
GAGE_ID_PLACEHOLDER = "<gage_id>"


def find_gpkg_file(basin_dir: str | Path) -> Path:
    """Return the single geopackage for a basin resource directory."""
    basin_dir = Path(basin_dir)
    if basin_dir.is_file() and basin_dir.suffix == ".gpkg":
        return basin_dir

    hydrofabric_candidates = sorted((basin_dir / HYDROFABRIC_DIR).glob("*.gpkg"))
    legacy_candidates = sorted((basin_dir / LEGACY_DATA_DIR).glob("*.gpkg"))
    flat_candidates = sorted(basin_dir.glob("*.gpkg"))
    candidates = hydrofabric_candidates or legacy_candidates or flat_candidates

    if not candidates:
        raise FileNotFoundError(
            f"No geopackage found in {basin_dir / HYDROFABRIC_DIR} "
            f"or {basin_dir / LEGACY_DATA_DIR} or {basin_dir}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple geopackages found for {basin_dir}: "
            f"{', '.join(str(path) for path in candidates)}"
        )
    return candidates[0]


def has_gpkg_file(basin_dir: str | Path) -> bool:
    basin_dir = Path(basin_dir)
    if basin_dir.is_file() and basin_dir.suffix == ".gpkg":
        return True
    if any(basin_dir.glob("*.gpkg")):
        return True
    for dirname in (HYDROFABRIC_DIR, LEGACY_DATA_DIR):
        if any((basin_dir / dirname).glob("*.gpkg")):
            return True
    return False


def resource_hydrofabric_dir(input_dir: str | Path) -> Path:
    return Path(input_dir) / HYDROFABRIC_DIR


def forcing_dir_for_basin(
    basin_dir: str | Path,
    start_year: int,
    end_year: int,
) -> Path:
    return Path(basin_dir) / FORCING_DIR / f"{start_year}_to_{end_year}"


def forcing_dir_for_resource(
    input_dir: str | Path,
    resource: str | Path,
    start_year: int,
    end_year: int,
    resource_layout: str = "gage",
) -> Path:
    """Return the default forcing directory for the configured resource layout."""
    input_dir = Path(input_dir)
    resource = Path(resource)
    if str(resource) == GAGE_ID_PLACEHOLDER:
        if resource_layout == "resource":
            return (
                input_dir
                / FORCING_DIR
                / GAGE_ID_PLACEHOLDER
                / f"{start_year}_to_{end_year}"
            )
        return (
            input_dir
            / GAGE_ID_PLACEHOLDER
            / FORCING_DIR
            / f"{start_year}_to_{end_year}"
        )

    if resource_layout == "resource":
        return input_dir / FORCING_DIR / resource_id(resource) / f"{start_year}_to_{end_year}"

    if resource.is_file() and resource.suffix == ".gpkg":
        return input_dir / resource_id(resource) / FORCING_DIR / f"{start_year}_to_{end_year}"

    return forcing_dir_for_basin(resource, start_year, end_year)


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


def resource_id(resource: str | Path) -> str:
    """Return the basin/resource identifier for a gpkg file or basin directory."""
    resource = Path(resource)
    if resource.suffix == ".gpkg":
        name = resource.stem
        if name.startswith("gage_"):
            return name.removeprefix("gage_")
        if name.startswith("Gage_"):
            return name.removeprefix("Gage_")
        return name
    return resource.name


def has_gage_placeholder(path_template: str | Path) -> bool:
    template = str(path_template)
    return any(
        placeholder in template
        for placeholder in (GAGE_ID_PLACEHOLDER, "{gage_id}", "{*}")
    )


def render_gage_path(path_template: str | Path, gage_id: str) -> Path:
    """Render a path template with the selected gage/resource identifier."""
    rendered = (
        str(path_template)
        .replace(GAGE_ID_PLACEHOLDER, gage_id)
        .replace("{gage_id}", gage_id)
        .replace("{*}", gage_id)
    )
    return Path(rendered)
