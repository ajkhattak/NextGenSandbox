from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_general_gages(config: dict) -> list[str]:
    general_gages = (config.get("general") or {}).get("gages")
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
        gpkg_config = general_gages.get("gpkg") or {}
        selected = gpkg_config.get("select")
        if selected is not None:
            return _normalize_gage_list(selected, "general.gages.gpkg.select")
        return _gage_ids_from_gpkg_dir(
            gpkg_config.get("dir"),
            gpkg_config.get("pattern", "gage_"),
        )

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


def _gage_ids_from_gpkg_dir(directory, pattern: str) -> list[str]:
    if not directory:
        raise ValueError("general.gages.gpkg.dir must be provided")
    directory = Path(directory)
    if directory.is_file():
        files = [directory]
    elif directory.is_dir():
        files = sorted(directory.glob(f"*{pattern}*.gpkg"))
        if not files:
            files = sorted(directory.glob("*.gpkg"))
    else:
        raise FileNotFoundError(f"general.gages.gpkg.dir not found: {directory}")

    ids = []
    for path in files:
        stem = path.stem
        digits = "".join(ch for ch in stem if ch.isdigit())
        if digits:
            ids.append(digits[-8:] if len(digits) >= 8 else digits)
    if not ids:
        raise ValueError(f"No gage IDs could be inferred from {directory}")
    return ids


def _is_all(value) -> bool:
    return isinstance(value, str) and value.lower() == "all"
