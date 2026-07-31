from __future__ import annotations

import fnmatch
import glob
import os
import re
from pathlib import Path

import pandas as pd

from src.python.resource_paths import (
    HYDROFABRIC_DIR,
    find_gpkg_file,
    has_gpkg_file,
)

SUPPORTED_GAGE_ID_LENGTHS = (8, 10, 12)
GAGE_ID_PLACEHOLDER = "<gage_id>"


def load_general_gages(config: dict) -> list[str]:
    general = config.get("general") or {}
    general_gages = general.get("gages")
    if general_gages is None:
        raise ValueError("general.gages must be configured")
    if not isinstance(general_gages, dict):
        raise TypeError("general.gages must be a mapping with option: ids | file | gpkg")

    option = str(general_gages.get("option", "")).lower()
    if option == "ids":
        return _normalize_gage_list(general_gages.get("ids"), "general.gages.ids")
    if option == "file":
        file_config = general_gages.get("file") or {}
        return _load_gages_from_file(
            file_config.get("path"),
            file_config.get("column", "gage_id"),
            "general.gages.file",
        )
    if option == "gpkg":
        return list(load_gpkg_resources(config))

    raise ValueError("general.gages.option must be one of: ids, file, gpkg")


def resolve_step_gages(
    *,
    project_gages: list[str],
    step_value,
    field_name: str,
) -> list[str]:
    if step_value is None or _is_all(step_value):
        return list(project_gages)

    selected = _normalize_simple_step_gages(step_value, field_name)
    unknown = sorted(set(selected) - set(project_gages))
    if unknown:
        raise ValueError(
            f"{field_name} contains gages outside general.gages: "
            f"{', '.join(unknown)}"
        )
    return selected


def _normalize_simple_step_gages(value, field_name: str) -> list[str]:
    if isinstance(value, str):
        if value.lower() == "all":
            raise ValueError(f"{field_name}: use all only as a complete selector")
        if value.lower().endswith(".csv"):
            raise ValueError(
                f"{field_name} does not support CSV files. "
                "Use general.gages.option: file instead."
            )
        return [value]

    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]

    raise TypeError(f"{field_name} must be all, a gage ID string, or a list of IDs")


def _normalize_gage_list(value, field_name: str) -> list[str]:
    if value is None:
        raise ValueError(f"{field_name} must be provided")
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    raise TypeError(f"{field_name} must be a gage ID string or list of IDs")


def _load_gages_from_file(path, column: str, field_name: str) -> list[str]:
    if not path:
        raise ValueError(f"{field_name}.path must be provided")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{field_name}.path not found: {path}")

    df = pd.read_csv(path, dtype=str)
    if column not in df.columns:
        raise ValueError(f"{field_name} CSV must contain column '{column}'")
    return [str(value) for value in df[column].dropna().tolist()]


def load_gpkg_resources(
    config: dict,
    selected_gages: list[str] | None = None,
) -> dict[str, Path]:
    """Resolve option: gpkg into an ordered gage ID to file mapping."""
    general = config.get("general") or {}
    general_gages = general.get("gages") or {}
    if str(general_gages.get("option", "")).lower() != "gpkg":
        raise ValueError("load_gpkg_resources requires general.gages.option: gpkg")

    gpkg_config = general_gages.get("gpkg") or {}
    if "pattern" in gpkg_config:
        raise ValueError(
            "general.gages.gpkg.pattern is no longer supported. Put the "
            "filename pattern in general.gages.gpkg.dir and use <gage_id> "
            "for the gage ID, for example: /path/to/*_<gage_id>_*.gpkg"
        )

    path_spec = gpkg_config.get("dir")
    resource_layout = general.get("resource_layout", "gage")
    if path_spec:
        resources = _discover_gpkg_path_spec(path_spec, resource_layout)
    else:
        input_dir = general.get("input_dir")
        if not input_dir:
            raise ValueError(
                "general.input_dir must be provided when general.gages.gpkg.dir "
                "is omitted"
            )
        input_dir = Path(input_dir)
        directory = (
            input_dir / HYDROFABRIC_DIR
            if resource_layout == "resource"
            else input_dir
        )
        resources = _discover_gpkg_directory(directory, resource_layout)

    resources_by_gage: dict[str, Path] = {}
    duplicate_gages: dict[str, list[Path]] = {}
    for gage_id, path in resources:
        if gage_id in resources_by_gage:
            duplicate_gages.setdefault(
                gage_id,
                [resources_by_gage[gage_id]],
            ).append(path)
        else:
            resources_by_gage[gage_id] = path

    if duplicate_gages:
        details = "; ".join(
            f"{gage_id}: {', '.join(str(path) for path in paths)}"
            for gage_id, paths in sorted(duplicate_gages.items())
        )
        raise ValueError(f"Multiple geopackages resolved for the same gage: {details}")

    if not resources_by_gage:
        location = path_spec or directory
        message = f"No geopackage files found using {location}."
        if path_spec and GAGE_ID_PLACEHOLDER in str(path_spec):
            message += (
                " Characters outside <gage_id> are matched literally; for "
                "example, '_' and '-' are different. Adjust the surrounding "
                "characters or use * where either form should be accepted."
            )
        raise FileNotFoundError(message)

    requested = selected_gages
    if requested is None and gpkg_config.get("select") is not None:
        requested = _normalize_gage_list(
            gpkg_config.get("select"),
            "general.gages.gpkg.select",
        )

    if requested is None:
        return resources_by_gage

    missing = [gage_id for gage_id in requested if gage_id not in resources_by_gage]
    if missing:
        source = path_spec or directory
        raise FileNotFoundError(
            "Geopackages are missing for requested gages: "
            f"{', '.join(missing)}. Source: {source}"
        )

    return {gage_id: resources_by_gage[gage_id] for gage_id in requested}


def _discover_gpkg_path_spec(
    path_spec: str | Path,
    resource_layout: str,
) -> list[tuple[str, Path]]:
    expanded = os.path.expandvars(os.path.expanduser(str(path_spec)))
    placeholder_count = expanded.count(GAGE_ID_PLACEHOLDER)
    if placeholder_count > 1:
        raise ValueError(
            "general.gages.gpkg.dir may contain <gage_id> only once"
        )

    if placeholder_count == 1:
        if not expanded.lower().endswith(".gpkg"):
            raise ValueError(
                "A general.gages.gpkg.dir template containing <gage_id> must "
                "resolve to .gpkg files"
            )
        glob_pattern = expanded.replace(GAGE_ID_PLACEHOLDER, "*")
        candidates = [
            Path(path)
            for path in sorted(glob.glob(glob_pattern, recursive=True))
            if Path(path).is_file() and Path(path).suffix.lower() == ".gpkg"
        ]
        matcher = _gpkg_template_regex(expanded)
        resources = []
        for path in candidates:
            match = matcher.fullmatch(str(path))
            if match:
                resources.append((match.group("gage_id"), path))
        return resources

    path = Path(expanded)
    if path.is_file():
        if path.suffix.lower() != ".gpkg":
            raise ValueError(f"Geopackage file must end in .gpkg: {path}")
        return [(_gage_id_from_gpkg_filename(path), path)]
    if path.is_dir():
        return _discover_gpkg_directory(path, resource_layout)
    if glob.has_magic(expanded):
        raise ValueError(
            "A wildcard general.gages.gpkg.dir must include <gage_id> so "
            "Sandbox can reliably associate each file with its gage"
        )
    raise FileNotFoundError(f"general.gages.gpkg.dir not found: {path}")


def _discover_gpkg_directory(
    directory: Path,
    resource_layout: str,
) -> list[tuple[str, Path]]:
    if not directory.is_dir():
        raise FileNotFoundError(f"general.gages.gpkg.dir not found: {directory}")

    files = _discover_gpkg_files(directory, resource_layout)
    return [(_gage_id_from_gpkg_filename(path), path) for path in files]


def _gpkg_template_regex(path_template: str) -> re.Pattern[str]:
    marker = "__NEXTGEN_SANDBOX_GAGE_ID__"
    translated = fnmatch.translate(
        path_template.replace(GAGE_ID_PLACEHOLDER, marker)
    )
    supported = "|".join(
        rf"\d{{{length}}}" for length in sorted(SUPPORTED_GAGE_ID_LENGTHS, reverse=True)
    )
    capture = rf"(?P<gage_id>(?<!\d)(?:{supported})(?!\d))"
    return re.compile(translated.replace(marker, capture))

def _gage_id_from_gpkg_filename(path: Path) -> str:
    numeric_tokens = re.findall(r"\d+", path.stem)
    valid_tokens = [
        token
        for token in numeric_tokens
        if len(token) in SUPPORTED_GAGE_ID_LENGTHS
    ]

    if len(numeric_tokens) != 1 or len(valid_tokens) != 1:
        supported = ", ".join(str(length) for length in SUPPORTED_GAGE_ID_LENGTHS)
        raise ValueError(
            f"Cannot infer a USGS gage ID from geopackage '{path.name}'. "
            "Its filename must contain exactly one numeric gage ID with "
            f"{supported} digits. Gage IDs are never truncated."
        )

    return valid_tokens[0]


def _discover_gpkg_files(directory: Path, resource_layout: str) -> list[Path]:
    direct_files = sorted(directory.glob("*.gpkg"))
    if direct_files:
        return direct_files

    if resource_layout == "gage":
        return [
            find_gpkg_file(child)
            for child in sorted(directory.iterdir())
            if child.is_dir() and has_gpkg_file(child)
        ]

    return []


def _is_all(value) -> bool:
    return isinstance(value, str) and value.lower() == "all"
