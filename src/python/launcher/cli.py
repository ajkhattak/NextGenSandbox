from __future__ import annotations

import argparse
import csv
import copy
import getpass
import json
import multiprocessing
import os
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

LAUNCHER_PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_CONFIG_DIR = REPO_ROOT / "configs" / "launcher"
CAMPAIGN_STATUS_ORDER = (
    "COMPLETED",
    "RUNNING",
    "QUEUED",
    "WILL_BE_REQUEUED",
    "NOT_SUBMITTED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "FAILED",
    "CANCELLED",
)
STATUS_FILTERS = {
    "completed": "COMPLETED",
    "running": "RUNNING",
    "queued": "QUEUED",
    "will_be_requeued": "WILL_BE_REQUEUED",
    "not_submitted": "NOT_SUBMITTED",
    "timeout": "TIMEOUT",
    "out_of_memory": "OUT_OF_MEMORY",
    "failed": "FAILED",
    "cancelled": "CANCELLED",
}
DETAILED_STATUS_ORDER = {
    state: index
    for index, state in enumerate(
        (
            "RUNNING",
            "COMPLETED",
            "FAILED",
            "NOT_SUBMITTED",
            "QUEUED",
            "WILL_BE_REQUEUED",
            "TIMEOUT",
            "OUT_OF_MEMORY",
            "CANCELLED",
            "UNKNOWN",
        )
    )
}
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.python.calibration_config import absolutize_optimizer_settings_file
from src.python.forcing_files import (
    resolve_netcdf_forcing_pattern,
    select_netcdf_forcing_file,
    select_prepared_forcing_file,
)
from src.python.observations import ObservationLoader
from src.python.resource_paths import (
    forcing_dir_for_resource,
    find_gpkg_file,
    has_gage_placeholder,
    render_gage_path,
    resource_hydrofabric_dir,
    resource_id,
)
from src.python.time_windows import (
    NGEN_TIMESTEP,
    format_timestamp,
    normalize_forcing_time_config,
    normalize_simulation_tasks,
    parse_duration,
    parse_timestamp,
    resolve_time_period,
    start_for_year,
)


@dataclass(frozen=True)
class CalibrationScenario:
    name: str | None
    calibration: dict[str, Any]
    selected_years: tuple[int, ...] = ()

    @property
    def display_name(self) -> str:
        return self.name or "default"


@dataclass(frozen=True)
class LauncherContext:
    launcher_dir: Path
    launcher_config_file: Path
    campaign_name: str
    sandbox_cfg: dict[str, Any]
    map_cfg: dict[str, Any]
    output_dir: Path
    input_dir: Path
    metadata_index_dir_name: str
    stages: tuple[str, ...]
    local: dict[str, Any]
    selection_summary: dict[str, int]
    calibration_scenarios: dict[str, tuple[CalibrationScenario, ...]]
    scenario_execution_mode: str
    scenario_order: tuple[str, ...]
    slurm: dict[str, Any]

    @property
    def log_dir(self) -> Path:
        return self.output_dir / "logs"


@dataclass(frozen=True)
class ExperimentProgress:
    configured: bool
    current_iteration: int | None = None
    completed_iterations: int | None = None
    objective_value: float | None = None
    checkpoint_file: Path | None = None
    algorithm: str | None = None

    @property
    def started(self) -> bool:
        return self.current_iteration is not None

    @property
    def checkpoint_available(self) -> bool:
        return self.checkpoint_file is not None


@dataclass(frozen=True)
class ActiveSlurmJob:
    job_id: str
    name: str
    num_tasks: int
    state: str
    num_cpus: int | None = None


@dataclass(frozen=True)
class SlurmJobHistory:
    job_id: str
    name: str
    state: str
    exit_code: str


@dataclass(frozen=True)
class ExperimentRun:
    config_file: Path | None
    slurm_job_id: str | None = None


@dataclass(frozen=True)
class CampaignStatus:
    gage_id: str
    formulation: str
    scenario: str
    state: str
    current_iteration: int | None
    max_iterations: int
    objective_value: float | None
    validation: str
    average_iteration_seconds: float | None
    estimated_remaining_seconds: float | None
    slurm_job_id: str | None = None


@dataclass(frozen=True)
class LauncherRunUnit:
    gage_id: str
    formulation_name: str
    formulation_spec: dict[str, Any]
    scenario: CalibrationScenario


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return data


def resolve_path(base_dir: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path


def default_config_file() -> Path:
    return LAUNCHER_CONFIG_DIR / "launcher_config.yaml"


def worker_script_path(ctx: LauncherContext) -> Path:
    return ctx.output_dir / "launcher" / f"{ctx.campaign_name}_worker.slurm"


def as_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise TypeError(f"{field_name} must be a string or list")


def unique_ordered(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def load_launcher_stages(sandbox_cfg: dict[str, Any]) -> tuple[str, ...]:
    simulation = sandbox_cfg.get("simulation") or {}
    normalized, _ = normalize_simulation_tasks(simulation)
    supported = {
        ("calibration",),
        ("validation",),
        ("calibration", "validation"),
    }
    if normalized not in supported:
        raise ValueError(
            "simulation.tasks must be one of: [calibration], [validation], "
            "or [calibration, validation]"
        )
    return normalized


def split_group_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [
        item.strip()
        for item in re.split(r"[,;|]", str(value))
        if item.strip()
    ]


def load_launcher_gages(
    sandbox_cfg: dict[str, Any],
    launcher_dir: Path,
) -> dict[str, list[str]]:
    general = sandbox_cfg.get("general")
    if not isinstance(general, dict):
        raise ValueError("launcher_config.yaml must define a general block")

    gages_cfg = general.get("gages")
    if not isinstance(gages_cfg, dict):
        raise ValueError("launcher_config.yaml must define general.gages")

    option = str(gages_cfg.get("option", "")).lower()
    if option == "ids":
        gage_ids = unique_ordered(
            [
                gage.strip()
                for gage in as_list(gages_cfg.get("ids"), "general.gages.ids")
                if gage.strip()
            ]
        )
        return {gage: [] for gage in gage_ids}

    if option != "file":
        raise ValueError("general.gages.option must be one of: ids, file")

    file_cfg = gages_cfg.get("file") or {}
    if not isinstance(file_cfg, dict):
        raise TypeError("general.gages.file must be a mapping")
    path_value = file_cfg.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("general.gages.file.path must be provided")
    path = resolve_path(launcher_dir, path_value)
    id_column = file_cfg.get("id_column") or file_cfg.get("column", "gage_id")
    group_column = file_cfg.get("group_column")

    if not path.exists():
        raise FileNotFoundError(f"general.gages.file.path not found: {path}")

    gage_groups: dict[str, list[str]] = {}
    with path.open(newline="") as file:
        reader = csv.DictReader(file)
        if id_column not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain gage ID column '{id_column}'")
        if group_column and group_column not in (reader.fieldnames or []):
            raise ValueError(f"{path} must contain group column '{group_column}'")

        for row in reader:
            gage_id = str(row[id_column]).strip()
            if not gage_id:
                continue
            groups = split_group_value(row.get(group_column)) if group_column else []
            existing = gage_groups.setdefault(gage_id, [])
            existing.extend(groups)

    return {gage: unique_ordered(groups) for gage, groups in gage_groups.items()}


def resolve_simulation_gages(
    sandbox_cfg: dict[str, Any],
    gage_groups: dict[str, list[str]],
) -> dict[str, list[str]]:
    selected = (sandbox_cfg.get("simulation") or {}).get("gages", "all")
    if isinstance(selected, str) and selected.strip().lower() == "all":
        return gage_groups
    if isinstance(selected, (list, tuple, set)):
        selected_ids = unique_ordered([str(item).strip() for item in selected])
    elif isinstance(selected, str):
        selected_ids = [selected.strip()]
    else:
        raise TypeError(
            "simulation.gages must be all, a gage ID string, or a list of IDs"
        )
    unknown = sorted(set(selected_ids) - set(gage_groups))
    if unknown:
        raise ValueError(
            "simulation.gages contains gages outside general.gages: "
            + ", ".join(unknown)
        )
    return {gage_id: gage_groups[gage_id] for gage_id in selected_ids}


def resolve_formulation_gages(
    formulation_name: str,
    formulation: dict[str, Any],
    gage_groups: dict[str, list[str]],
) -> list[str]:
    field_name = f"formulations.{formulation_name}.selection"
    selection = formulation.get("selection")

    if isinstance(selection, str):
        if selection.strip().lower() != "all":
            raise ValueError(f"{field_name} must be 'all' or a mapping")
        return list(gage_groups)

    if not isinstance(selection, dict):
        raise ValueError(f"{field_name} is required and must be 'all' or a mapping")

    unknown_fields = sorted(set(selection) - {"groups", "ids"})
    if unknown_fields:
        raise ValueError(
            f"{field_name} contains unsupported field(s): "
            f"{', '.join(unknown_fields)}"
        )

    selected_groups = unique_ordered(
        [
            group.strip()
            for group in as_list(selection.get("groups"), f"{field_name}.groups")
            if group.strip()
        ]
    )
    selected_ids = unique_ordered(
        [
            gage.strip()
            for gage in as_list(selection.get("ids"), f"{field_name}.ids")
            if gage.strip()
        ]
    )
    if not selected_groups and not selected_ids:
        raise ValueError(f"{field_name} must contain groups and/or ids")

    unknown_ids = sorted(set(selected_ids) - set(gage_groups))
    if unknown_ids:
        raise ValueError(
            f"{field_name}.ids contains gages outside the selected "
            "general/simulation gages: "
            f"{', '.join(unknown_ids)}"
        )

    known_groups = {
        group
        for groups in gage_groups.values()
        for group in groups
    }
    unknown_groups = sorted(set(selected_groups) - known_groups)
    if unknown_groups:
        raise ValueError(
            f"{field_name}.groups references unknown gage group(s): "
            f"{', '.join(unknown_groups)}"
        )

    selected_id_set = set(selected_ids)
    selected_group_set = set(selected_groups)
    resolved = [
        gage_id
        for gage_id, groups in gage_groups.items()
        if gage_id in selected_id_set or selected_group_set.intersection(groups)
    ]
    if not resolved:
        raise ValueError(f"{field_name} resolves to zero project gages")
    return resolved


def build_map_from_formulations(
    sandbox_cfg: dict[str, Any],
    launcher_dir: Path,
) -> tuple[dict[str, Any], dict[str, int]]:
    configured_formulations = sandbox_cfg.get("formulations")
    if not isinstance(configured_formulations, dict) or not configured_formulations:
        raise ValueError("launcher_config.yaml must define a non-empty formulations block")

    gage_groups = load_launcher_gages(sandbox_cfg, launcher_dir)
    if not gage_groups:
        raise ValueError("No gages were resolved from general.gages")
    gage_groups = resolve_simulation_gages(sandbox_cfg, gage_groups)
    if not gage_groups:
        raise ValueError("simulation.gages resolves to zero general.gages")

    mapping: dict[str, list[str]] = {gage_id: [] for gage_id in gage_groups}
    formulations: dict[str, dict[str, Any]] = {}
    summary: dict[str, int] = {}

    for formulation_name, formulation in configured_formulations.items():
        if not isinstance(formulation, dict):
            raise TypeError(f"formulations.{formulation_name} must be a mapping")
        if not formulation.get("models"):
            raise ValueError(f"formulations.{formulation_name}.models must be provided")

        selected_gages = resolve_formulation_gages(
            formulation_name,
            formulation,
            gage_groups,
        )
        summary[formulation_name] = len(selected_gages)
        formulations[formulation_name] = {
            key: copy.deepcopy(value)
            for key, value in formulation.items()
            if key != "selection"
        }
        for gage_id in selected_gages:
            mapping[gage_id].append(formulation_name)

    unassigned = [gage_id for gage_id, selected in mapping.items() if not selected]
    if unassigned:
        raise ValueError(
            "The selected general/simulation gages are not assigned to any "
            "formulation: "
            f"{', '.join(unassigned)}"
        )

    return {
        "formulations": formulations,
        "mapping": mapping,
    }, summary


def resolve_project_paths(
    sandbox_cfg: dict[str, Any],
    launcher_dir: Path,
) -> None:
    general = sandbox_cfg.get("general") or {}
    for field_name in ("input_dir", "output_dir"):
        value = general.get(field_name)
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError(f"general.{field_name} must be a non-empty path")
        general[field_name] = str(resolve_path(launcher_dir, value).resolve())


def absolutize_launcher_resource_paths(
    sandbox_cfg: dict[str, Any],
    launcher_dir: Path,
) -> None:
    forcings = sandbox_cfg.get("forcings") or {}
    forcing_dir = forcings.get("forcing_dir")
    if forcing_dir and not Path(str(forcing_dir)).expanduser().is_absolute():
        forcings["forcing_dir"] = str(resolve_path(launcher_dir, forcing_dir))

    observations = sandbox_cfg.get("observations") or {}
    for settings in observations.values():
        if not isinstance(settings, dict):
            continue
        path = settings.get("path")
        if path and not Path(str(path)).expanduser().is_absolute():
            settings["path"] = str(resolve_path(launcher_dir, path))


def enable_launcher_metadata(sandbox_cfg: dict[str, Any]) -> None:
    """Enable the metadata required to resume and monitor launcher jobs."""
    simulation = sandbox_cfg.setdefault("simulation", {})
    outputs = simulation.setdefault("outputs", {})
    if not isinstance(outputs, dict):
        raise TypeError("simulation.outputs must be a mapping")
    metadata = outputs.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise TypeError("simulation.outputs.metadata must be a mapping")
    metadata["enabled"] = True
    metadata.setdefault("index_dir", "metadata")
    metadata.setdefault("file", "simulation_metadata.yml")


def _complete_evaluation_years(
    reference: dict[str, Any],
    year_type: str,
) -> list[int]:
    resolved = resolve_time_period(
        reference,
        "regime_calibration.reference",
    )
    evaluation = resolved["evaluation_time"]
    eval_start = parse_timestamp(
        evaluation["start_time"],
        "regime_calibration.reference evaluation start",
    )
    eval_end = parse_timestamp(
        evaluation["end_time"],
        "regime_calibration.reference evaluation end",
    )

    years = []
    for year in range(eval_start.year - 1, eval_end.year + 2):
        year_start = start_for_year(year, year_type)
        year_end = start_for_year(year + 1, year_type) - NGEN_TIMESTEP
        if year_start >= eval_start and year_end <= eval_end:
            years.append(year)

    if not years:
        raise ValueError(
            "regime_calibration.reference has no complete post-spinup "
            f"{year_type.replace('_', ' ')}s available for calibration"
        )
    return years


def _load_regime_years(
    source_file: Path,
    year_column: str,
    regime_column: str,
) -> dict[int, str]:
    if not source_file.is_file():
        raise FileNotFoundError(f"Regime source file not found: {source_file}")

    rows: dict[int, str] = {}
    with source_file.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames or []
        missing = [
            column
            for column in (year_column, regime_column)
            if column not in fields
        ]
        if missing:
            raise ValueError(
                f"Regime source file {source_file} is missing column(s): "
                f"{', '.join(missing)}"
            )

        for line_number, row in enumerate(reader, start=2):
            year_text = str(row.get(year_column, "")).strip()
            regime = str(row.get(regime_column, "")).strip()
            if not year_text and not regime:
                continue
            try:
                year = int(year_text)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid year {year_text!r} in {source_file} line "
                    f"{line_number}"
                ) from exc
            if not regime:
                raise ValueError(
                    f"Missing regime in {source_file} line {line_number}"
                )
            if year in rows:
                raise ValueError(
                    f"Duplicate year {year} in regime source file {source_file}"
                )
            rows[year] = regime
    return rows


def resolve_regime_scenarios(
    regime_config: dict[str, Any],
    gage_id: str,
    launcher_dir: Path,
    *,
    require_gage_placeholder: bool = False,
) -> tuple[CalibrationScenario, ...]:
    if not isinstance(regime_config, dict):
        raise TypeError("regime_calibration must be a YAML dictionary/object")

    reference = regime_config.get("reference")
    source = regime_config.get("source")
    selection = regime_config.get("selection")
    if not isinstance(reference, dict):
        raise TypeError(
            "regime_calibration.reference must be a YAML dictionary/object"
        )
    if not isinstance(source, dict):
        raise TypeError(
            "regime_calibration.source must be a YAML dictionary/object"
        )
    if not isinstance(selection, dict):
        raise TypeError(
            "regime_calibration.selection must be a YAML dictionary/object"
        )

    unknown_reference = sorted(
        set(reference) - {"start", "end", "spinup", "year_type"}
    )
    if unknown_reference:
        raise ValueError(
            "regime_calibration.reference contains unsupported field(s): "
            f"{', '.join(unknown_reference)}"
        )
    for field in ("start", "end", "spinup"):
        if field not in reference:
            raise ValueError(f"regime_calibration.reference.{field} is required")

    year_type = str(reference.get("year_type", "water_year")).strip().lower()
    if year_type not in {"water_year", "calendar_year"}:
        raise ValueError(
            "regime_calibration.reference.year_type must be one of: "
            "water_year, calendar_year"
        )

    source_pattern = source.get("file")
    if not isinstance(source_pattern, str) or not source_pattern.strip():
        raise ValueError("regime_calibration.source.file must be a non-empty path")
    if require_gage_placeholder and "<gage_id>" not in source_pattern:
        raise ValueError(
            "regime_calibration.source.file must contain <gage_id> when the "
            "launcher includes multiple gages"
        )
    source_file = resolve_path(
        launcher_dir,
        source_pattern.replace("<gage_id>", gage_id),
    )
    year_column = str(source.get("year_column", "Water_Year")).strip()
    regime_column = str(source.get("regime_column", "Regime")).strip()

    order = str(selection.get("order", "earliest")).strip().lower()
    if order != "earliest":
        raise ValueError(
            "regime_calibration.selection.order currently supports only: earliest"
        )
    max_years = selection.get("max_years", 5)
    if isinstance(max_years, bool) or not isinstance(max_years, int) or max_years < 1:
        raise ValueError(
            "regime_calibration.selection.max_years must be a positive integer"
        )
    regimes = selection.get("regimes")
    if not isinstance(regimes, dict) or not regimes:
        raise ValueError(
            "regime_calibration.selection.regimes must be a non-empty mapping"
        )
    if "ref" in regimes:
        raise ValueError(
            "'ref' is reserved for the reference calibration scenario"
        )

    normalized_regimes: dict[str, str] = {}
    source_labels: dict[str, str] = {}
    for scenario_name, source_label in regimes.items():
        safe_name = model_name_to_dir(str(scenario_name))
        if not safe_name or safe_name != str(scenario_name).strip().lower():
            raise ValueError(
                "regime_calibration.selection.regimes keys must use lowercase "
                "letters, numbers, periods, underscores, or hyphens"
            )
        if safe_name == "ref":
            raise ValueError(
                "'ref' is reserved for the reference calibration scenario"
            )
        if safe_name in normalized_regimes:
            raise ValueError(f"Duplicate regime scenario name: {safe_name}")
        label = str(source_label).strip()
        if not label:
            raise ValueError(
                f"Regime scenario '{safe_name}' must map to a non-empty CSV label"
            )
        folded_label = label.casefold()
        if folded_label in source_labels:
            raise ValueError(
                f"Regime CSV label {label!r} is assigned to more than one scenario"
            )
        normalized_regimes[safe_name] = folded_label
        source_labels[folded_label] = safe_name

    reference_period = {
        "start": reference["start"],
        "end": reference["end"],
        "spinup": reference["spinup"],
    }
    eligible_years = _complete_evaluation_years(reference_period, year_type)
    rows = _load_regime_years(source_file, year_column, regime_column)
    missing_years = [year for year in eligible_years if year not in rows]
    if missing_years:
        raise ValueError(
            f"Regime source file {source_file} is missing eligible year(s): "
            f"{', '.join(str(year) for year in missing_years)}"
        )
    unknown_labels = sorted(
        {
            rows[year]
            for year in eligible_years
            if rows[year].casefold() not in source_labels
        }
    )
    if unknown_labels:
        raise ValueError(
            f"Regime source file {source_file} contains unconfigured label(s) "
            f"within the reference period: {', '.join(unknown_labels)}"
        )
    spinup = parse_duration(
        reference["spinup"],
        "regime_calibration.reference.spinup",
    )

    reference_start = parse_timestamp(
        reference["start"],
        "regime_calibration.reference.start",
    )
    reference_end = parse_timestamp(
        reference["end"],
        "regime_calibration.reference.end",
    )
    scenarios = [
        CalibrationScenario(
            name="ref",
            calibration={
                "start": format_timestamp(reference_start),
                "end": format_timestamp(reference_end),
                "spinup": reference["spinup"],
            },
        )
    ]

    for scenario_name, label in normalized_regimes.items():
        selected = [
            year
            for year in eligible_years
            if rows[year].casefold() == label
        ][:max_years]
        if not selected:
            raise ValueError(
                f"Regime scenario '{scenario_name}' has no matching complete "
                f"{year_type.replace('_', ' ')}s for gage {gage_id} in "
                f"{source_file}"
            )

        first_year_start = start_for_year(selected[0], year_type)
        simulation_start = first_year_start - spinup
        simulation_end = (
            start_for_year(selected[-1] + 1, year_type) - NGEN_TIMESTEP
        )
        calibration = {
            "start": format_timestamp(simulation_start),
            "end": format_timestamp(simulation_end),
            "spinup": reference["spinup"],
            "evaluation": {
                "years": selected,
                "year_type": year_type,
            },
        }
        resolve_time_period(
            calibration,
            f"regime_calibration.{scenario_name}",
            allow_selected_years=True,
        )
        scenarios.append(
            CalibrationScenario(
                name=str(scenario_name),
                calibration=calibration,
                selected_years=tuple(selected),
            )
        )

    return tuple(scenarios)


def resolve_calibration_scenarios(
    launcher_settings: dict[str, Any],
    map_cfg: dict[str, Any],
    sandbox_cfg: dict[str, Any],
    launcher_dir: Path,
) -> dict[str, tuple[CalibrationScenario, ...]]:
    gage_ids = list(map_cfg["mapping"])
    regime_config = launcher_settings.get("regime_calibration")
    if regime_config is None:
        calibration = (
            sandbox_cfg.get("simulation", {})
            .get("time", {})
            .get("calibration")
        )
        if not isinstance(calibration, dict):
            raise ValueError(
                "simulation.time must define calibration"
            )
        scenario = CalibrationScenario(
            name=None,
            calibration=copy.deepcopy(calibration),
        )
        return {gage_id: (scenario,) for gage_id in gage_ids}

    return {
        gage_id: resolve_regime_scenarios(
            regime_config,
            gage_id,
            launcher_dir,
            require_gage_placeholder=len(gage_ids) > 1,
        )
        for gage_id in gage_ids
    }


def resolve_scenario_execution(
    launcher_settings: dict[str, Any],
    calibration_scenarios: dict[str, tuple[CalibrationScenario, ...]],
) -> tuple[str, tuple[str, ...]]:
    regime_config = launcher_settings.get("regime_calibration")
    if regime_config is None:
        return "parallel", ("default",)

    execution = regime_config.get("execution") or {}
    if not isinstance(execution, dict):
        raise TypeError(
            "regime_calibration.execution must be a YAML dictionary/object"
        )
    unknown = sorted(set(execution) - {"mode", "order"})
    if unknown:
        raise ValueError(
            "regime_calibration.execution contains unsupported field(s): "
            f"{', '.join(unknown)}"
        )

    mode = str(execution.get("mode", "priority")).strip().lower()
    if mode not in {"priority", "parallel"}:
        raise ValueError(
            "regime_calibration.execution.mode must be one of: "
            "priority, parallel"
        )

    first_scenarios = next(iter(calibration_scenarios.values()))
    available = tuple(scenario.display_name for scenario in first_scenarios)
    configured_order = execution.get("order", list(available))
    if not isinstance(configured_order, list) or not configured_order:
        raise TypeError(
            "regime_calibration.execution.order must be a non-empty YAML list"
        )
    order = tuple(str(name).strip().lower() for name in configured_order)
    if any(not name for name in order) or len(order) != len(set(order)):
        raise ValueError(
            "regime_calibration.execution.order must contain unique, "
            "non-empty scenario names"
        )
    missing = sorted(set(available) - set(order))
    unknown_names = sorted(set(order) - set(available))
    if missing or unknown_names:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown_names:
            details.append(f"unknown: {', '.join(unknown_names)}")
        raise ValueError(
            "regime_calibration.execution.order must list every configured "
            f"scenario exactly once ({'; '.join(details)})"
        )
    return mode, order


def load_context(config_file: Path) -> LauncherContext:
    config_file = config_file.expanduser()
    if not config_file.is_absolute():
        config_file = Path.cwd() / config_file
    if not config_file.exists():
        fallback = default_config_file()
        if config_file.name == "launcher_config.yaml" and fallback.exists():
            config_file = fallback
        else:
            raise FileNotFoundError(f"Launcher config file not found: {config_file}")

    config_file = config_file.resolve()
    launcher_dir = config_file.parent
    launcher_cfg = load_yaml(config_file)

    legacy_fields = [
        field_name
        for field_name in (
            "project",
            "sandbox",
            "experiments",
            "stages",
            "local",
            "slurm",
            "regime_calibration",
            "mapping_config",
            "templates",
            "sandbox_config",
            "gages",
            "assignment",
            "submit_script",
            "execution",
        )
        if field_name in launcher_cfg
    ]
    if legacy_fields:
        raise ValueError(
            "Unsupported legacy launcher field(s): "
            f"{', '.join(legacy_fields)}. Keep Sandbox settings at the top "
            "level, use formulations for model assignments, and put "
            "launcher-only settings under launcher."
        )

    supported_blocks = {
        "general",
        "subsetting",
        "forcings",
        "observations",
        "calibration",
        "simulation",
        "formulations",
        "launcher",
    }
    unsupported_blocks = sorted(set(launcher_cfg) - supported_blocks)
    if unsupported_blocks:
        raise ValueError(
            "Unsupported launcher configuration block(s): "
            f"{', '.join(unsupported_blocks)}. Use normal Sandbox blocks, "
            "formulations, and launcher."
        )

    launcher_settings = launcher_cfg.get("launcher")
    if not isinstance(launcher_settings, dict):
        raise ValueError("launcher_config.yaml must define a launcher block")

    sandbox_cfg = {
        key: copy.deepcopy(value)
        for key, value in launcher_cfg.items()
        if key not in {"formulations", "launcher"}
    }
    if not sandbox_cfg:
        raise ValueError("launcher_config.yaml must include Sandbox configuration blocks")
    if "formulation" in sandbox_cfg:
        raise ValueError(
            "Launcher configs use formulations, not formulation. Move the "
            "model definition into formulations.<name>."
        )
    stages = load_launcher_stages(sandbox_cfg)

    local = launcher_settings.get("local") or {}
    if not isinstance(local, dict):
        raise TypeError("launcher.local must be a YAML dictionary/object")
    local = copy.deepcopy(local)
    local.setdefault("max_workers", 2)
    local.setdefault("startup_delay_seconds", 5)

    resolve_project_paths(sandbox_cfg, launcher_dir)
    absolutize_launcher_resource_paths(sandbox_cfg, launcher_dir)
    enable_launcher_metadata(sandbox_cfg)
    absolutize_optimizer_settings_file(
        sandbox_cfg,
        config_file,
    )
    validate_sandbox_config(sandbox_cfg)

    formulation_config = copy.deepcopy(sandbox_cfg)
    formulation_config["formulations"] = copy.deepcopy(
        launcher_cfg.get("formulations")
    )
    map_cfg, selection_summary = build_map_from_formulations(
        formulation_config,
        launcher_dir,
    )

    output_dir = Path(sandbox_cfg["general"]["output_dir"]).expanduser()
    input_dir = Path(sandbox_cfg["general"]["input_dir"]).expanduser()
    metadata = (
        sandbox_cfg.get("simulation", {})
        .get("outputs", {})
        .get("metadata", {})
    )
    metadata_index_dir_name = metadata.get("index_dir", "metadata")
    calibration_scenarios = resolve_calibration_scenarios(
        launcher_settings,
        map_cfg,
        sandbox_cfg,
        launcher_dir,
    )
    scenario_execution_mode, scenario_order = resolve_scenario_execution(
        launcher_settings,
        calibration_scenarios,
    )
    slurm_value = launcher_settings.get("slurm")
    if slurm_value is None:
        slurm = {}
    elif not isinstance(slurm_value, dict):
        raise TypeError("slurm must be a YAML dictionary/object")
    else:
        slurm = copy.deepcopy(slurm_value)
        slurm.setdefault("startup_delay_seconds", 5)

    campaign_name = model_name_to_dir(
        launcher_settings.get("campaign_name") or config_file.stem
    )
    if not campaign_name:
        raise ValueError(
            "launcher.campaign_name or the launcher config filename must "
            "contain a usable name"
        )

    return LauncherContext(
        launcher_dir=launcher_dir,
        launcher_config_file=config_file,
        campaign_name=campaign_name,
        sandbox_cfg=sandbox_cfg,
        map_cfg=map_cfg,
        output_dir=output_dir,
        input_dir=input_dir,
        metadata_index_dir_name=metadata_index_dir_name,
        stages=stages,
        local=local,
        selection_summary=selection_summary,
        calibration_scenarios=calibration_scenarios,
        scenario_execution_mode=scenario_execution_mode,
        scenario_order=scenario_order,
        slurm=slurm,
    )


def validate_sandbox_config(config: dict[str, Any]) -> None:
    general = config.get("general") or {}
    simulation = config.get("simulation") or {}
    forcings = config.get("forcings") or {}

    if "layout" in general:
        raise ValueError("general.layout is no longer supported; use general.resource_layout")
    if "gage_ids_input" in simulation:
        raise ValueError("simulation.gage_ids_input is no longer supported; use simulation.gages")
    if "select" in forcings:
        raise ValueError("forcings.select is no longer supported; use forcings.gages")
    if "sandbox_launcher" in config:
        raise ValueError(
            "sandbox_launcher is no longer supported; use "
            "simulation.outputs.metadata"
        )
    if "input_dir" not in general or "output_dir" not in general:
        raise ValueError(
            "Project paths are missing. Define general.input_dir and "
            "general.output_dir in launcher_config.yaml."
        )
    metadata = simulation.get("outputs", {}).get("metadata", {})
    if not metadata.get("enabled"):
        raise ValueError(
            "Launcher requires simulation.outputs.metadata.enabled: true "
            "in the generated Sandbox configuration"
        )
    if not metadata.get("index_dir"):
        raise ValueError("Launcher requires simulation.outputs.metadata.index_dir")


def validate_mapping_config(map_cfg: dict[str, Any]) -> None:
    formulations = map_cfg.get("formulations")
    mapping = map_cfg.get("mapping")
    if not isinstance(formulations, dict) or not formulations:
        raise ValueError("Resolved launcher formulations must be a non-empty mapping")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("Resolved launcher gage assignments must be a non-empty mapping")

    groups = map_cfg.get("groups", {}) or {}
    for name, spec in formulations.items():
        if not isinstance(spec, dict):
            raise ValueError(f"formulations.{name} must be a mapping")
        if not spec.get("models"):
            raise ValueError(f"formulations.{name}.models must be provided")

    known = set(formulations) | set(groups)
    for gage_id, entries in mapping.items():
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"mapping.{gage_id} must be a non-empty list")
        missing = [entry for entry in entries if entry not in known]
        if missing:
            raise ValueError(
                f"mapping.{gage_id} references unknown formulation/group(s): "
                f"{', '.join(missing)}"
            )

    for group_name, entries in groups.items():
        missing = [entry for entry in entries if entry not in formulations]
        if missing:
            raise ValueError(
                f"groups.{group_name} references unknown formulation(s): "
                f"{', '.join(missing)}"
            )


def validate_context(ctx: LauncherContext) -> None:
    unknown_local = sorted(
        set(ctx.local) - {"max_workers", "startup_delay_seconds"}
    )
    if unknown_local:
        raise ValueError(
            f"local contains unsupported field(s): {', '.join(unknown_local)}"
        )
    max_workers = ctx.local.get("max_workers")
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or max_workers < 1
    ):
        raise ValueError("local.max_workers must be a positive integer")
    local_delay = ctx.local.get("startup_delay_seconds")
    if (
        isinstance(local_delay, bool)
        or not isinstance(local_delay, int)
        or local_delay < 0
    ):
        raise ValueError(
            "local.startup_delay_seconds must be a non-negative integer"
        )
    validate_slurm_config(ctx.slurm)
    validate_sandbox_config(ctx.sandbox_cfg)
    validate_mapping_config(ctx.map_cfg)
    validate_project_paths(ctx)


def validate_project_paths(ctx: LauncherContext) -> None:
    if not ctx.input_dir.exists():
        raise FileNotFoundError(
            "general.input_dir does not exist: "
            f"{ctx.input_dir}. Update general.input_dir in "
            f"{ctx.launcher_config_file}."
        )
    if not ctx.input_dir.is_dir():
        raise NotADirectoryError(
            f"general.input_dir is not a directory: {ctx.input_dir}"
        )

    if ctx.output_dir.exists():
        if not ctx.output_dir.is_dir():
            raise NotADirectoryError(
                f"general.output_dir is not a directory: {ctx.output_dir}"
            )
        return

    existing_parent = ctx.output_dir.parent
    while (
        not existing_parent.exists()
        and existing_parent != existing_parent.parent
    ):
        existing_parent = existing_parent.parent
    if not existing_parent.is_dir() or not os.access(existing_parent, os.W_OK):
        raise PermissionError(
            "general.output_dir cannot be created: "
            f"{ctx.output_dir}. The nearest existing parent is not writable: "
            f"{existing_parent}. Update general.output_dir in "
            f"{ctx.launcher_config_file}."
        )


def resolve_launcher_hydrofabric(ctx: LauncherContext, gage_id: str) -> Path:
    resource_layout = ctx.sandbox_cfg["general"].get(
        "resource_layout",
        "gage",
    )
    if resource_layout == "gage":
        return find_gpkg_file(ctx.input_dir / gage_id)

    candidates = [
        path
        for path in sorted(resource_hydrofabric_dir(ctx.input_dir).glob("*.gpkg"))
        if resource_id(path) == gage_id
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No geopackage found for gage {gage_id} under "
            f"{resource_hydrofabric_dir(ctx.input_dir)}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple geopackages found for gage {gage_id}: "
            f"{', '.join(str(path) for path in candidates)}"
        )
    return candidates[0]


def resolve_launcher_forcing(
    ctx: LauncherContext,
    gage_id: str,
) -> Path:
    forcings = ctx.sandbox_cfg.get("forcings") or {}
    forcing_time = normalize_forcing_time_config(forcings.get("time"))
    start_year = parse_timestamp(
        forcing_time["start_time"],
        "forcings.time.start",
    ).year
    end_year = parse_timestamp(
        forcing_time["end_time"],
        "forcings.time.end",
    ).year + 1
    resource_layout = ctx.sandbox_cfg["general"].get(
        "resource_layout",
        "gage",
    )

    configured_path = forcings.get("forcing_dir")
    if configured_path:
        if not has_gage_placeholder(configured_path) and len(ctx.map_cfg["mapping"]) > 1:
            raise ValueError(
                "forcings.forcing_dir must contain <gage_id> for a "
                "multi-gage launcher campaign"
            )
        forcing_path = (
            render_gage_path(configured_path, gage_id)
            if has_gage_placeholder(configured_path)
            else Path(configured_path)
        )
    else:
        resource = (
            ctx.input_dir / gage_id
            if resource_layout == "gage"
            else Path(gage_id)
        )
        forcing_path = forcing_dir_for_resource(
            ctx.input_dir,
            resource,
            start_year,
            end_year,
            resource_layout,
        )

    forcing_format = str(forcings.get("format", ".nc")).lower()
    if forcing_format == ".csv":
        if not forcing_path.is_dir():
            raise FileNotFoundError(
                f"CSV forcing directory does not exist: {forcing_path}"
            )
        return forcing_path

    rechunk_enabled = bool(forcings.get("rechunk", True))
    forcing_path = resolve_netcdf_forcing_pattern(
        forcing_path,
        rechunk_enabled=rechunk_enabled,
    )
    if not forcing_path.exists():
        raise FileNotFoundError(
            f"Forcing directory or file does not exist: {forcing_path}"
        )
    if forcing_path.is_dir():
        forcing_file = select_netcdf_forcing_file(
            forcing_path,
            use_corrected=bool(forcings.get("use_corrected", True)),
        )
    elif forcing_path.suffix.lower() == ".nc":
        forcing_file = forcing_path
    else:
        raise ValueError(
            f"NetCDF forcing path must resolve to a .nc file: {forcing_path}"
        )
    return select_prepared_forcing_file(
        forcing_file,
        rechunk_enabled=rechunk_enabled,
    )


def validate_launcher_resources(
    ctx: LauncherContext,
    *,
    verbose: bool = False,
) -> None:
    errors = []
    resolved = []
    for gage_id in ctx.map_cfg["mapping"]:
        try:
            hydrofabric = resolve_launcher_hydrofabric(ctx, gage_id)
        except (
            FileNotFoundError,
            NotADirectoryError,
            TypeError,
            ValueError,
        ) as error:
            hydrofabric = None
            errors.append(f"{gage_id} hydrofabric: {error}")

        try:
            forcing = resolve_launcher_forcing(ctx, gage_id)
        except (
            FileNotFoundError,
            NotADirectoryError,
            TypeError,
            ValueError,
        ) as error:
            forcing = None
            errors.append(f"{gage_id} forcing: {error}")

        resolved.append((gage_id, hydrofabric, forcing))

    observations = ctx.sandbox_cfg.get("observations") or {}
    if observations:
        try:
            ObservationLoader(
                observations=observations,
                config_dir=ctx.launcher_dir,
            ).validate(list(ctx.map_cfg["mapping"]))
        except (FileNotFoundError, TypeError, ValueError) as error:
            errors.append(f"observations: {error}")

    if verbose:
        print("\nResource preflight")
        print("------------------")
        for gage_id, hydrofabric, forcing in resolved:
            print(f"{gage_id} | hydrofabric: {hydrofabric or 'MISSING'}")
            print(f"{gage_id} | forcing    : {forcing or 'MISSING'}")
        if observations:
            status = "valid" if not any(
                error.startswith("observations:") for error in errors
            ) else "INVALID"
            print(f"observations | {status}")

    if errors:
        details = "\n".join(f"  - {error}" for error in errors)
        raise FileNotFoundError(
            "Launcher resource preflight failed:\n" + details
        )


def validate_slurm_config(slurm: dict[str, Any]) -> None:
    if not slurm:
        return

    unknown_slurm = sorted(
        set(slurm)
        - {
            "account",
            "partition",
            "mpi_tasks",
            "max_active_jobs",
            "max_total_mpi_tasks",
            "max_total_allocated_cpus",
            "startup_delay_seconds",
            "modules",
            "environment",
            "coordinator",
            "calibration",
            "validation",
        }
    )
    if unknown_slurm:
        raise ValueError(
            f"slurm contains unsupported field(s): {', '.join(unknown_slurm)}"
        )
    if "mpi_tasks" in slurm and slurm["mpi_tasks"] != "auto":
        raise ValueError("slurm.mpi_tasks must be: auto")

    modules = slurm.get("modules", [])
    if not isinstance(modules, list) or any(
        not isinstance(module, str) or not module.strip()
        for module in modules
    ):
        raise ValueError("slurm.modules must be a list of non-empty module names")

    environment = slurm.get("environment", {})
    if not isinstance(environment, dict):
        raise ValueError("slurm.environment must be a mapping of names to values")
    reserved_environment = {
        "SANDBOX_ENV",
        "SANDBOX_FILE",
        "SANDBOX_STAGE",
        "START_DELAY",
    }
    for name, value in environment.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*",
            name,
        ):
            raise ValueError(
                f"Invalid environment variable name in slurm.environment: {name!r}"
            )
        if name in reserved_environment:
            raise ValueError(
                f"slurm.environment cannot override launcher variable {name}"
            )
        if value is None or isinstance(value, (dict, list)):
            raise ValueError(
                f"slurm.environment.{name} must be a scalar value"
            )
    for field_name in (
        "max_active_jobs",
        "max_total_mpi_tasks",
        "max_total_allocated_cpus",
    ):
        value = slurm.get(field_name)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(f"slurm.{field_name} must be a positive integer")
    slurm_delay = slurm.get("startup_delay_seconds")
    if (
        isinstance(slurm_delay, bool)
        or not isinstance(slurm_delay, int)
        or slurm_delay < 0
    ):
        raise ValueError(
            "slurm.startup_delay_seconds must be a non-negative integer"
        )

    coordinator_value = slurm.get("coordinator")
    if coordinator_value is None:
        coordinator = {}
    elif not isinstance(coordinator_value, dict):
        raise TypeError("slurm.coordinator must be a YAML dictionary/object")
    else:
        coordinator = coordinator_value
    unknown_coordinator = sorted(set(coordinator) - {"time", "memory"})
    if unknown_coordinator:
        raise ValueError(
            "slurm.coordinator contains unsupported field(s): "
            f"{', '.join(unknown_coordinator)}"
        )
    for field_name, default in (("time", "00:10:00"), ("memory", "2G")):
        value = coordinator.get(field_name, default)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"slurm.coordinator.{field_name} must be a non-empty string"
            )

    for stage in ("calibration", "validation"):
        settings = slurm.get(stage)
        if not isinstance(settings, dict):
            raise ValueError(
                f"slurm.{stage} must be provided as a mapping with explicit "
                "time and memory settings"
            )
        unknown_settings = sorted(set(settings) - {"time", "memory"})
        if unknown_settings:
            raise ValueError(
                f"slurm.{stage} contains unsupported field(s): "
                f"{', '.join(unknown_settings)}"
            )
        for field_name in ("time", "memory"):
            value = settings.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"slurm.{stage}.{field_name} must be provided"
                )


def slurm_settings_for_stage(
    slurm: dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    if stage not in {"calibration", "validation"}:
        raise ValueError(f"Unsupported launcher stage: {stage}")

    settings = {
        key: slurm[key]
        for key in ("account", "partition", "mpi_tasks")
        if key in slurm
    }
    settings.update(slurm[stage])
    return settings


def model_name_to_dir(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return safe.strip("_").lower()


def get_formulations_for_gage(ctx: LauncherContext, gage_id: str) -> list[tuple[str, dict[str, Any]]]:
    formulations = ctx.map_cfg["formulations"]
    groups = ctx.map_cfg.get("groups", {}) or {}
    entries = ctx.map_cfg["mapping"][gage_id]

    names: list[str] = []
    for entry in entries:
        if entry in groups:
            names.extend(groups[entry])
        else:
            names.append(entry)

    return [(name, formulations[name]) for name in names]


def get_calibration_scenarios(
    ctx: LauncherContext,
    gage_id: str,
) -> tuple[CalibrationScenario, ...]:
    return ctx.calibration_scenarios[gage_id]


def launcher_run_units(ctx: LauncherContext) -> list[LauncherRunUnit]:
    units = [
        LauncherRunUnit(
            gage_id=gage_id,
            formulation_name=formulation_name,
            formulation_spec=formulation_spec,
            scenario=scenario,
        )
        for gage_id in ctx.map_cfg["mapping"]
        for formulation_name, formulation_spec in get_formulations_for_gage(
            ctx,
            gage_id,
        )
        for scenario in get_calibration_scenarios(ctx, gage_id)
    ]
    if getattr(ctx, "scenario_execution_mode", "parallel") != "priority":
        return units

    scenario_order = getattr(ctx, "scenario_order", ())
    priority = {name: index for index, name in enumerate(scenario_order)}
    return sorted(
        units,
        key=lambda unit: priority.get(
            unit.scenario.display_name,
            len(priority),
        ),
    )


def experiment_output_dir(
    ctx: LauncherContext,
    model_dir: str,
    scenario_name: str | None = None,
) -> Path:
    model_output_dir = ctx.output_dir / model_dir
    if scenario_name:
        model_output_dir = model_output_dir / scenario_name
    return model_output_dir


def experiment_dirs(
    ctx: LauncherContext,
    model_dir: str,
    scenario_name: str | None = None,
) -> tuple[Path, Path]:
    model_output_dir = experiment_output_dir(ctx, model_dir, scenario_name)
    return model_output_dir / "configs", model_output_dir / ctx.metadata_index_dir_name


def generated_config_paths(exp_config_dir: Path, gage_id: str) -> dict[str, Path]:
    gage_dir = exp_config_dir / gage_id
    return {
        "sandbox_main": gage_dir / f"sandbox_config_{gage_id}.yaml",
        "sandbox_restart": gage_dir / f"sandbox_config_{gage_id}_restart.yaml",
        "sandbox_pso_warm_start": (
            gage_dir / f"sandbox_config_{gage_id}_pso_warm_start.yaml"
        ),
        "pso_warm_start_settings": (
            gage_dir / f"pso_settings_{gage_id}_warm_start.yaml"
        ),
        "sandbox_validation": gage_dir / f"sandbox_config_{gage_id}_validation.yaml",
    }


def generate_config_files_for_gage(
    ctx: LauncherContext,
    formulation_name: str,
    formulation_spec: dict[str, Any],
    model_dir: str,
    gage_id: str,
    exp_config_dir: Path,
    metadata_index_dir: Path,
    *,
    scenario: CalibrationScenario | None = None,
    dryrun: bool = False,
) -> None:
    sandbox_cfg = copy.deepcopy(ctx.sandbox_cfg)
    scenario_name = scenario.name if scenario else None
    output_dir = experiment_output_dir(ctx, model_dir, scenario_name)

    general = sandbox_cfg.setdefault("general", {})
    general["output_dir"] = str(output_dir)
    general["gages"] = {
        "option": "ids",
        "ids": [gage_id],
    }
    sandbox_cfg.pop("formulation", None)
    sandbox_cfg["formulations"] = {
        formulation_name: copy.deepcopy(formulation_spec)
    }
    simulation = sandbox_cfg.setdefault("simulation", {})
    simulation["gages"] = [gage_id]
    simulation["tasks"] = ["calibration"]
    simulation["label"] = formulation_name
    if scenario is not None:
        simulation.setdefault("time", {})["calibration"] = (
            copy.deepcopy(scenario.calibration)
        )
    paths = generated_config_paths(exp_config_dir, gage_id)

    if dryrun:
        print(
            f"[DRYRUN] Would generate configs for {gage_id} / "
            f"{formulation_name} / {scenario.display_name if scenario else 'default'}: "
            f"{paths['sandbox_main']}"
        )
        return

    paths["sandbox_main"].parent.mkdir(parents=True, exist_ok=True)
    metadata_index_dir.mkdir(parents=True, exist_ok=True)

    with paths["sandbox_main"].open("w") as file:
        yaml.safe_dump(sandbox_cfg, file, default_flow_style=False, sort_keys=False)

    sandbox_restart_cfg = copy.deepcopy(sandbox_cfg)
    sandbox_restart_cfg["simulation"]["tasks"] = ["restart"]
    simulation_label = sandbox_cfg["simulation"].get("label")
    output_name = (
        f"{gage_id}_{simulation_label}"
        if simulation_label
        else gage_id
    )
    sandbox_restart_cfg["simulation"]["restart_dir"] = str(
        output_dir / output_name
    )
    with paths["sandbox_restart"].open("w") as file:
        yaml.safe_dump(
            sandbox_restart_cfg,
            file,
            default_flow_style=False,
            sort_keys=False,
        )

    sandbox_val_cfg = copy.deepcopy(sandbox_cfg)
    sandbox_val_cfg["simulation"]["tasks"] = ["validation"]
    with paths["sandbox_validation"].open("w") as file:
        yaml.safe_dump(sandbox_val_cfg, file, default_flow_style=False, sort_keys=False)

    subprocess.run(
        [
            "sandbox",
            "--conf",
            "-i",
            str(paths["sandbox_main"]),
        ],
        check=True,
    )


def get_max_iter(exp_config_dir: Path, gage_id: str) -> int:
    sandbox_file = generated_config_paths(exp_config_dir, gage_id)["sandbox_main"]
    if not sandbox_file.exists():
        return 0
    cfg = load_yaml(sandbox_file)
    return int(cfg["calibration"]["optimizer"]["iterations"])


def read_metadata_index_file(metadata_index_dir: Path, gage_id: str) -> dict[str, Any] | None:
    metadata_file = metadata_index_dir / f"run_{gage_id}.yml"
    if not metadata_file.exists():
        return None
    return load_yaml(metadata_file)


def parse_best_params(path: Path) -> tuple[int, float]:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError(f"Expected at least 3 lines in {path}")

    def value(line: str) -> str:
        return line.split("=", 1)[1].strip() if "=" in line else line.strip()

    return int(float(value(lines[0]))), round(float(value(lines[2])), 3)


def calibration_algorithm(metadata: dict[str, Any]) -> str | None:
    sandbox_config = metadata.get("sandbox_config")
    if not sandbox_config:
        return None

    config_path = Path(sandbox_config)
    if not config_path.is_file():
        return None

    config = load_yaml(config_path)
    algorithm = (
        (config.get("calibration") or {})
        .get("optimizer", {})
        .get("algorithm")
    )
    return str(algorithm).lower() if algorithm else None


def pso_best_params_files(output_dir: Path) -> list[Path]:
    candidates = [output_dir / "pso_global_best" / "best_params.txt"]
    candidates.extend(
        worker_dir / "pso_global_best" / "best_params.txt"
        for worker_dir in sorted(output_dir.glob("*_worker"))
    )
    return [path for path in candidates if path.is_file()]


def pso_completed_generations(output_dir: Path, current_iteration: int) -> int:
    progress_file = output_dir / "pso_progress.json"
    if not progress_file.is_file():
        return current_iteration + 1

    progress = json.loads(progress_file.read_text())
    completed = progress.get("completed_generations")
    if isinstance(completed, bool) or not isinstance(completed, int) or completed < 0:
        raise ValueError(
            f"Invalid completed_generations in PSO progress file: {progress_file}"
        )
    return completed


def get_experiment_progress(
    metadata_index_dir: Path,
    gage_id: str,
    *,
    status: bool = False,
) -> ExperimentProgress:
    metadata = read_metadata_index_file(metadata_index_dir, gage_id)
    if metadata is None:
        return ExperimentProgress(configured=False)

    output_dir = Path(metadata["output_dir"])
    algorithm = calibration_algorithm(metadata)
    pso_files = pso_best_params_files(output_dir)
    if algorithm == "pso" or (algorithm is None and pso_files):
        algorithm = "pso"
        best_param_files = pso_files
    else:
        best_param_files = list(output_dir.glob("*_worker/best_params.txt"))

    best_param_files = sorted(
        best_param_files,
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not best_param_files:
        if not status:
            print(f"INFO: [{gage_id}] Calibration has not started.")
        return ExperimentProgress(configured=True, algorithm=algorithm)

    best_params = best_param_files[0]
    current_iteration, objective_value = parse_best_params(best_params)
    state_files = sorted(
        best_params.parent.glob("*_parameter_df_state.parquet"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    checkpoint_file = state_files[0] if state_files else None
    completed_iterations = (
        pso_completed_generations(output_dir, current_iteration)
        if algorithm == "pso"
        else current_iteration
    )

    return ExperimentProgress(
        configured=True,
        current_iteration=current_iteration,
        completed_iterations=completed_iterations,
        objective_value=objective_value,
        checkpoint_file=checkpoint_file,
        algorithm=algorithm,
    )


def get_num_cpus(metadata_index_dir: Path, gage_id: str) -> int:
    metadata = read_metadata_index_file(metadata_index_dir, gage_id)
    if metadata is None:
        return 1
    return int(metadata.get("num_cpus", 1))


def prepare_pso_warm_start_config(
    paths: dict[str, Path],
    checkpoint_file: Path,
) -> Path:
    sandbox_config = load_yaml(paths["sandbox_main"])
    calibration = sandbox_config.get("calibration") or {}
    optimizer = calibration.get("optimizer") or {}
    if str(optimizer.get("algorithm", "")).strip().lower() != "pso":
        raise ValueError(
            "Cannot prepare a PSO warm start from a non-PSO sandbox config: "
            f"{paths['sandbox_main']}"
        )

    settings_value = optimizer.get("settings_file")
    if settings_value:
        settings_file = Path(settings_value).expanduser()
        if not settings_file.is_absolute():
            settings_file = (
                paths["sandbox_main"].resolve().parent / settings_file
            ).resolve()
    else:
        settings_file = REPO_ROOT / "configs" / "optimizers" / "pso.yaml"

    settings = load_yaml(settings_file)
    initialization = settings.setdefault("initialization", {})
    if not isinstance(initialization, dict):
        raise TypeError(
            f"PSO initialization must be a mapping in {settings_file}"
        )
    initialization["best_path"] = str(checkpoint_file.resolve())

    warm_settings_file = paths["pso_warm_start_settings"]
    warm_settings_file.parent.mkdir(parents=True, exist_ok=True)
    with warm_settings_file.open("w") as file:
        yaml.safe_dump(settings, file, default_flow_style=False, sort_keys=False)

    optimizer["settings_file"] = str(warm_settings_file.resolve())
    simulation = sandbox_config.setdefault("simulation", {})
    simulation["tasks"] = ["calibration"]
    simulation.pop("restart_dir", None)

    warm_config_file = paths["sandbox_pso_warm_start"]
    with warm_config_file.open("w") as file:
        yaml.safe_dump(
            sandbox_config,
            file,
            default_flow_style=False,
            sort_keys=False,
        )

    print(
        "INFO: Starting a new PSO swarm from the previous global-best "
        f"parameters in {checkpoint_file}."
    )
    return warm_config_file


def check_validation_exists(metadata_index_dir: Path, gage_id: str, *, status: bool = False) -> bool:
    metadata = read_metadata_index_file(metadata_index_dir, gage_id)
    if metadata is None:
        return False

    output_dir = Path(metadata["output_dir"])
    validation_files = list(output_dir.glob("*_worker/output_sim_obs/sim_obs_validation.*"))
    if validation_files:
        if not status:
            print(f"INFO: [{gage_id}] Validation output found; skipping validation run.")
        return True
    return False


def build_slurm_submit_command(
    worker_script: Path,
    sandbox_file: Path,
    job_name: str,
    num_mpi_tasks: int,
    delay_seconds: int,
    stage: str,
    slurm: dict[str, Any] | None = None,
    log_dir: Path | None = None,
    work_dir: Path | None = None,
) -> list[str]:
    command = [
        "sbatch",
        "--parsable",
        "--cpus-per-task=1",
        f"--ntasks-per-node={num_mpi_tasks}",
        f"--job-name={job_name}",
    ]
    slurm = slurm or {}
    option_names = {
        "account": "account",
        "partition": "partition",
        "time": "time",
        "memory": "mem",
    }
    for config_name, option_name in option_names.items():
        value = slurm.get(config_name)
        if value is not None and str(value).strip():
            command.append(f"--{option_name}={value}")
    if log_dir is not None:
        command.extend(
            [
                f"--output={log_dir}/%x_%j.out",
                f"--error={log_dir}/%x_%j.err",
            ]
        )
    if work_dir is not None:
        command.append(f"--chdir={work_dir}")
    command.extend(
        [
            "--export=ALL,"
            f"SANDBOX_FILE={sandbox_file},"
            f"SANDBOX_STAGE={stage},"
            f"START_DELAY={delay_seconds}",
            str(worker_script),
        ]
    )
    return command


def render_slurm_worker_script(slurm: dict[str, Any]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "",
        "set -euo pipefail",
        "",
        'echo "Allocated MPI tasks: ${SLURM_NTASKS:-1}"',
        'echo "CPUs per task: ${SLURM_CPUS_PER_TASK:-1}"',
    ]

    modules = slurm.get("modules", [])
    if modules:
        lines.extend(
            [
                "",
                "if ! command -v module >/dev/null 2>&1; then",
                '    echo "ERROR: The module command is unavailable in this Slurm job."',
                "    exit 1",
                "fi",
            ]
        )
        lines.extend(
            f"module load {shlex.quote(module)}"
            for module in modules
        )

    environment = slurm.get("environment", {})
    if environment:
        lines.append("")
        for name, value in environment.items():
            if isinstance(value, bool):
                value = str(value).lower()
            lines.append(f"export {name}={shlex.quote(str(value))}")

    lines.extend(
        [
            "",
            "unset PYTHONPATH",
            'if [ -z "${SANDBOX_ENV:-}" ]; then',
            '    echo "ERROR: SANDBOX_ENV is not set. Run ./bootstrap.sh --env and reload your shell before submitting."',
            "    exit 1",
            "fi",
            "",
            'SANDBOX_PYTHON="$SANDBOX_ENV/bin/python"',
            'SANDBOX_COMMAND="$SANDBOX_ENV/bin/sandbox"',
            'if [ ! -x "$SANDBOX_PYTHON" ] || [ ! -x "$SANDBOX_COMMAND" ]; then',
            '    echo "ERROR: The Sandbox environment is incomplete: $SANDBOX_ENV"',
            '    echo "Run ./bootstrap.sh --sandbox to build it."',
            "    exit 1",
            "fi",
            'export PATH="$SANDBOX_ENV/bin:$PATH"',
            "",
            'if [ -z "${SANDBOX_FILE:-}" ]; then',
            '    echo "ERROR: SANDBOX_FILE must be exported by the launcher."',
            "    exit 1",
            "fi",
            'if [ "${SANDBOX_STAGE:-}" != "calibration" ] && [ "${SANDBOX_STAGE:-}" != "validation" ]; then',
            '    echo "ERROR: SANDBOX_STAGE must be calibration or validation."',
            "    exit 1",
            "fi",
            "",
            'echo "Python executable: $SANDBOX_PYTHON"',
            'echo "SANDBOX_FILE = $SANDBOX_FILE"',
            'echo "SANDBOX_STAGE = $SANDBOX_STAGE"',
            "",
            'if [ -n "${START_DELAY:-}" ] && [ "$START_DELAY" -gt 0 ]; then',
            '    echo "Applying startup delay: ${START_DELAY}s"',
            '    sleep "$START_DELAY"',
            "fi",
            "",
            'if [ "$SANDBOX_STAGE" = "validation" ]; then',
            '    echo "Generating validation configuration files..."',
            '    "$SANDBOX_COMMAND" --conf -i "$SANDBOX_FILE"',
            "fi",
            '"$SANDBOX_COMMAND" --run -i "$SANDBOX_FILE"',
        ]
    )
    return "\n".join(lines) + "\n"


def write_slurm_worker_script(ctx: LauncherContext) -> Path:
    path = worker_script_path(ctx)
    content = render_slurm_worker_script(ctx.slurm)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != content:
        path.write_text(content)
    path.chmod(0o700)
    return path


def build_launcher_submit_command(
    ctx: LauncherContext,
    dependency_job_ids: tuple[str, ...] = (),
) -> list[str]:
    coordinator = ctx.slurm.get("coordinator") or {}
    coordinator_time = coordinator.get("time", "00:10:00")
    coordinator_memory = coordinator.get("memory", "2G")
    command = [
        "sbatch",
        "--parsable",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=1",
        f"--time={coordinator_time}",
        f"--mem={coordinator_memory}",
        f"--job-name={ctx.campaign_name}_launcher",
        f"--output={ctx.log_dir}/%x_%j.out",
        f"--error={ctx.log_dir}/%x_%j.err",
        f"--chdir={ctx.output_dir}",
    ]
    for name in ("account", "partition"):
        value = ctx.slurm.get(name)
        if value is not None and str(value).strip():
            command.append(f"--{name}={value}")
    if dependency_job_ids:
        command.append(
            "--dependency="
            + "?".join(
                f"afterany:{job_id}" for job_id in dependency_job_ids
            )
        )
    command.extend(
        [
            f"--export=ALL,LAUNCHER_CONFIG={ctx.launcher_config_file}",
            str(LAUNCHER_PACKAGE_DIR / "submit_launcher.sh"),
        ]
    )
    return command


def parse_sbatch_job_id(output: str) -> str:
    text = output.strip()
    if not text:
        raise RuntimeError("Slurm submission did not return a job ID")

    last_line = text.splitlines()[-1].strip()
    if last_line.startswith("Submitted batch job "):
        last_line = last_line.removeprefix("Submitted batch job ").strip()
    job_id = last_line.split(";", 1)[0]
    if not job_id.isdigit():
        raise RuntimeError(
            f"Unable to parse Slurm job ID from sbatch output: {text!r}"
        )
    return job_id


def submission_history_path(ctx: LauncherContext) -> Path:
    return (
        ctx.output_dir
        / "launcher"
        / f"{ctx.campaign_name}_submitted_jobs.jsonl"
    )


def record_slurm_submission(
    ctx: LauncherContext,
    *,
    job_id: str,
    job_name: str,
    stage: str,
) -> None:
    path = submission_history_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "job_id": job_id,
        "job_name": job_name,
        "stage": stage,
        "submitted_at": datetime.now().astimezone().isoformat(),
    }
    with path.open("a") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")


def submit_launcher(
    ctx: LauncherContext,
    dependency_job_ids: tuple[str, ...] = (),
) -> str:
    if not ctx.slurm:
        raise ValueError(
            "Slurm submission requires a slurm block in the launcher configuration"
        )
    slurm_limits(ctx.slurm)
    try:
        ctx.output_dir.mkdir(parents=True, exist_ok=True)
        ctx.log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RuntimeError(
            f"Unable to create general.output_dir {ctx.output_dir}: {error}"
        ) from error
    worker_script = write_slurm_worker_script(ctx)
    print(f"Generated Slurm worker script: {worker_script}")
    command = build_launcher_submit_command(ctx, dependency_job_ids)
    if dependency_job_ids:
        print(
            "Scheduling launcher follow-up after worker job(s): "
            f"{', '.join(dependency_job_ids)}"
        )
    else:
        print(f"Submitting launcher campaign '{ctx.campaign_name}'...")
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "The sbatch command was not found. Submit Slurm campaigns from "
            "an HPC login node with Slurm available."
        ) from error
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or str(error)).strip()
        raise RuntimeError(f"Slurm launcher submission failed: {details}") from error
    message = result.stdout.strip()
    if message:
        print(message)
    job_id = parse_sbatch_job_id(result.stdout)
    print(f"Launcher coordinator job ID: {job_id}")
    print(f"Launcher logs: {ctx.log_dir}")
    return job_id


def select_experiment_config(
    paths: dict[str, Path],
    progress: ExperimentProgress,
    max_iter: int,
    stages: tuple[str, ...],
    *,
    validation_exists: bool = False,
) -> Path | None:
    calibration_requested = "calibration" in stages
    validation_requested = "validation" in stages

    if not progress.started:
        if not calibration_requested:
            raise RuntimeError(
                "Validation was requested, but calibration has not started. "
                "Run the launcher with simulation.tasks: [calibration] or "
                "simulation.tasks: [calibration, validation] first."
            )
        return paths["sandbox_main"]

    if not progress.checkpoint_available:
        raise RuntimeError(
            "Calibration progress was found, but its worker directory has no "
            "*_parameter_df_state.parquet checkpoint. The launcher cannot "
            "restart or validate this experiment safely."
        )

    completed_iterations = (
        progress.completed_iterations
        if progress.completed_iterations is not None
        else progress.current_iteration
    )
    if completed_iterations < max_iter:
        if not calibration_requested:
            raise RuntimeError(
                "Validation was requested, but calibration is incomplete "
                f"({completed_iterations}/{max_iter} iterations). Run or "
                "resume calibration first."
            )
        if progress.algorithm == "pso":
            return prepare_pso_warm_start_config(
                paths,
                progress.checkpoint_file,
            )
        return paths["sandbox_restart"]

    if validation_requested and not validation_exists:
        return paths["sandbox_validation"]
    return None


def run_experiment(
    ctx: LauncherContext,
    model_dir: str,
    gage_id: str,
    job_name: str,
    exp_config_dir: Path,
    metadata_index_dir: Path,
    progress: ExperimentProgress,
    delay_seconds: int,
    *,
    use_slurm: bool,
    dryrun: bool = False,
) -> ExperimentRun:
    paths = generated_config_paths(exp_config_dir, gage_id)
    max_iter = get_max_iter(exp_config_dir, gage_id)
    if max_iter == 0 and not progress.configured:
        max_iter = 1
    validation_exists = (
        "validation" in ctx.stages
        and check_validation_exists(metadata_index_dir, gage_id)
    )
    sandbox_file = select_experiment_config(
        paths,
        progress,
        max_iter,
        ctx.stages,
        validation_exists=validation_exists,
    )
    if sandbox_file is None:
        return ExperimentRun(None)
    stage = (
        "validation"
        if sandbox_file == paths["sandbox_validation"]
        else "calibration"
    )

    if use_slurm:
        num_mpi_tasks = get_num_cpus(metadata_index_dir, gage_id)
        cmd = build_slurm_submit_command(
            worker_script_path(ctx),
            sandbox_file,
            job_name,
            num_mpi_tasks,
            delay_seconds,
            stage,
            slurm_settings_for_stage(ctx.slurm, stage),
            log_dir=ctx.log_dir,
            work_dir=ctx.output_dir,
        )
        if dryrun:
            print(f"[DRYRUN] [{gage_id}] Would submit: {' '.join(cmd)}")
        else:
            print(f"[{gage_id}] Submitting: {' '.join(cmd)}")
    else:
        cmd = [
            "sandbox",
            "--run",
            "-i",
            str(sandbox_file),
        ]
        if dryrun:
            if stage == "validation":
                print(
                    f"[DRYRUN] [{gage_id}] Would generate validation "
                    f"configs: sandbox --conf -i {sandbox_file}"
                )
            print(f"[DRYRUN] [{gage_id}] Would run locally: {' '.join(cmd)}")

    if dryrun:
        return ExperimentRun(sandbox_file)

    if not use_slurm:
        time.sleep(delay_seconds)
        if stage == "validation":
            print(
                f"[{gage_id}] Generating validation configs: "
                f"sandbox --conf -i {sandbox_file}"
            )
            subprocess.run(
                ["sandbox", "--conf", "-i", str(sandbox_file)],
                check=True,
            )
        print(f"[{gage_id}] Running locally: {' '.join(cmd)}")
    if use_slurm:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        message = result.stdout.strip()
        if message:
            print(message)
        job_id = parse_sbatch_job_id(result.stdout)
        record_slurm_submission(
            ctx,
            job_id=job_id,
            job_name=job_name,
            stage=stage,
        )
        return ExperimentRun(
            sandbox_file,
            job_id,
        )

    subprocess.run(cmd, check=True)
    return ExperimentRun(sandbox_file)


def local_worker(args: tuple[Any, ...]) -> None:
    (
        ctx,
        model_dir,
        gage_id,
        job_name,
        exp_config_dir,
        metadata_index_dir,
        progress,
        delay_seconds,
        dryrun,
    ) = args
    if dryrun:
        run_experiment(
            ctx,
            model_dir,
            gage_id,
            job_name,
            exp_config_dir,
            metadata_index_dir,
            progress,
            delay_seconds,
            use_slurm=False,
            dryrun=True,
        )
        return

    paths = generated_config_paths(exp_config_dir, gage_id)
    current_progress = progress
    current_delay = delay_seconds

    while True:
        run_result = run_experiment(
            ctx,
            model_dir,
            gage_id,
            job_name,
            exp_config_dir,
            metadata_index_dir,
            current_progress,
            current_delay,
            use_slurm=False,
        )
        current_delay = 0

        selected_config = run_result.config_file
        if selected_config is None:
            return

        if selected_config == paths["sandbox_validation"]:
            if not check_validation_exists(
                metadata_index_dir,
                gage_id,
                status=True,
            ):
                raise RuntimeError(
                    f"Validation command completed for gage {gage_id}, but "
                    "no sim_obs_validation output was found. Review the "
                    "validation worker output before rerunning the launcher."
                )
            return

        next_progress = get_experiment_progress(
            metadata_index_dir,
            gage_id,
            status=True,
        )
        previous_state = (
            current_progress.current_iteration,
            current_progress.completed_iterations,
            current_progress.objective_value,
            current_progress.checkpoint_file,
        )
        next_state = (
            next_progress.current_iteration,
            next_progress.completed_iterations,
            next_progress.objective_value,
            next_progress.checkpoint_file,
        )
        if not next_progress.started or next_state == previous_state:
            raise RuntimeError(
                f"Calibration command completed for gage {gage_id}, but "
                "calibration progress did not advance. Review the calibration "
                "worker output before rerunning the launcher."
            )
        current_progress = next_progress


def calibration_is_complete(
    progress: ExperimentProgress,
    max_iterations: int,
) -> bool:
    if not progress.started:
        return False
    completed = (
        progress.completed_iterations
        if progress.completed_iterations is not None
        else progress.current_iteration
    )
    return completed is not None and completed >= max_iterations


def worker_start_time(worker_dir: Path) -> float | None:
    match = re.match(r"^(\d{12})_.*_worker$", worker_dir.name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M").timestamp()
    except ValueError:
        return None


def objective_log_evaluations(path: Path) -> int:
    evaluations = 0
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return 0
    for line in lines:
        fields = line.split(",", 1)
        if len(fields) != 2:
            continue
        try:
            int(fields[0].strip())
            float(fields[1].strip())
        except ValueError:
            continue
        evaluations += 1
    return evaluations


def estimate_calibration_timing(
    output_dir: Path,
    progress: ExperimentProgress,
    max_iterations: int,
) -> tuple[float | None, float | None]:
    if not progress.started:
        return None, None

    elapsed_seconds = 0.0
    completed_samples = 0
    if progress.algorithm == "pso":
        progress_file = output_dir / "pso_progress.json"
        worker_starts = [
            start
            for worker_dir in output_dir.glob("*_worker")
            if (start := worker_start_time(worker_dir)) is not None
        ]
        if progress_file.is_file() and worker_starts:
            try:
                pso_progress = json.loads(progress_file.read_text())
                progress_mtime = progress_file.stat().st_mtime
            except (OSError, json.JSONDecodeError):
                pso_progress = {}
                progress_mtime = 0.0
            completed = pso_progress.get("completed_generations", 0)
            if (
                isinstance(completed, int)
                and not isinstance(completed, bool)
                and completed > 0
            ):
                elapsed_seconds = max(
                    0.0,
                    progress_mtime - min(worker_starts),
                )
                completed_samples = completed
    else:
        for objective_log in output_dir.glob("*_worker/objective_log.txt"):
            start = worker_start_time(objective_log.parent)
            if start is None:
                continue
            evaluations = objective_log_evaluations(objective_log)
            try:
                elapsed = max(0.0, objective_log.stat().st_mtime - start)
            except OSError:
                continue
            if evaluations == 0 or elapsed == 0:
                continue
            elapsed_seconds += elapsed
            completed_samples += evaluations

    if completed_samples == 0 or elapsed_seconds == 0:
        return None, None

    average_seconds = elapsed_seconds / completed_samples
    completed_iterations = (
        progress.completed_iterations
        if progress.completed_iterations is not None
        else progress.current_iteration
    )
    remaining_iterations = max(
        0,
        max_iterations - (completed_iterations or 0),
    )
    return average_seconds, average_seconds * remaining_iterations


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total_seconds = max(0, int(round(seconds)))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_estimated_minutes(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    minutes = max(0, int(seconds / 60.0 + 0.5))
    return f"{minutes} min"


def detailed_status_sort_key(
    status: CampaignStatus,
) -> tuple[int, str, str, str]:
    return (
        DETAILED_STATUS_ORDER.get(status.state, len(DETAILED_STATUS_ORDER)),
        status.gage_id,
        status.formulation,
        status.scenario,
    )


def submitted_worker_jobs(
    ctx: LauncherContext,
    expected_names: set[str],
) -> dict[str, str]:
    """Return submitted Slurm worker job IDs mapped to experiment names."""
    jobs: dict[str, str] = {}
    history_path = submission_history_path(ctx)
    if history_path.is_file():
        try:
            lines = history_path.read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            job_id = str(record.get("job_id", "")).strip()
            job_name = str(record.get("job_name", "")).strip()
            if job_id.isdigit() and job_name in expected_names:
                jobs[job_id] = job_name

    # Recover campaigns submitted before the history file was introduced from
    # their persistent Slurm output/error filenames.
    log_dir = getattr(ctx, "log_dir", ctx.output_dir / "logs")
    if log_dir.is_dir():
        for path in log_dir.iterdir():
            match = re.match(r"^(.+)_(\d+)\.(?:out|err)$", path.name)
            if match is None:
                continue
            job_name, job_id = match.groups()
            if job_name in expected_names:
                jobs[job_id] = job_name
    return jobs


def normalize_slurm_state(state: str) -> str:
    return state.strip().upper().split()[0].rstrip("+")


def get_slurm_job_history(
    jobs_by_id: dict[str, str],
) -> dict[str, SlurmJobHistory]:
    """Return the latest accounting record for each submitted experiment."""
    if not jobs_by_id:
        return {}

    latest: dict[str, SlurmJobHistory] = {}
    job_ids = sorted(jobs_by_id, key=int)
    for start in range(0, len(job_ids), 500):
        chunk = job_ids[start : start + 500]
        cmd = [
            "sacct",
            "-X",
            "-n",
            "-P",
            "-j",
            ",".join(chunk),
            "-o",
            "JobIDRaw,State%30,ExitCode",
        ]
        try:
            output = subprocess.check_output(cmd, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise RuntimeError(
                "Unable to query completed Slurm jobs with sacct."
            ) from error

        for line in output.splitlines():
            if not line.strip():
                continue
            fields = line.split("|", 2)
            if len(fields) != 3:
                continue
            job_id, state, exit_code = (field.strip() for field in fields)
            job_name = jobs_by_id.get(job_id)
            if job_name is None:
                continue
            record = SlurmJobHistory(
                job_id=job_id,
                name=job_name,
                state=normalize_slurm_state(state),
                exit_code=exit_code,
            )
            previous = latest.get(job_name)
            if previous is None or int(job_id) > int(previous.job_id):
                latest[job_name] = record
    return latest


def terminal_campaign_state(
    progress: ExperimentProgress,
    history: SlurmJobHistory | None,
) -> str:
    if history is None:
        return "WILL_BE_REQUEUED" if progress.started else "NOT_SUBMITTED"

    state = history.state
    if state == "TIMEOUT":
        return "TIMEOUT"
    if state in {"OUT_OF_MEMORY", "OUT_OF_ME", "OOM"}:
        return "OUT_OF_MEMORY"
    if state == "CANCELLED":
        return "CANCELLED"
    if state == "COMPLETED":
        return "WILL_BE_REQUEUED"
    if state in {"PENDING", "CONFIGURING", "REQUEUED", "RESIZING"}:
        return "QUEUED"
    if state in {"RUNNING", "COMPLETING", "SUSPENDED"}:
        return "RUNNING"
    if state in {
        "BOOT_FAIL",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "PREEMPTED",
        "REVOKED",
        "SPECIAL_EXIT",
    }:
        return "FAILED"
    return "FAILED"


def collect_campaign_status(
    ctx: LauncherContext,
) -> tuple[list[CampaignStatus], str | None]:
    scheduler_error = None
    active_by_name: dict[str, ActiveSlurmJob] = {}
    history_by_name: dict[str, SlurmJobHistory] = {}
    if ctx.slurm:
        try:
            expected_names = expected_slurm_job_names(ctx)
            for job in get_active_slurm_jobs():
                if job.name not in expected_names:
                    continue
                existing = active_by_name.get(job.name)
                if existing is None or job.state == "RUNNING":
                    active_by_name[job.name] = job
            submitted_jobs = submitted_worker_jobs(ctx, expected_names)
            history_by_name = get_slurm_job_history(submitted_jobs)
        except RuntimeError as error:
            scheduler_error = str(error)
    else:
        scheduler_error = "Slurm is not configured for this campaign."

    statuses = []
    for gage_id in ctx.map_cfg["mapping"]:
        for formulation_name, _ in get_formulations_for_gage(ctx, gage_id):
            model_dir = model_name_to_dir(formulation_name)
            for scenario in get_calibration_scenarios(ctx, gage_id):
                exp_config_dir, metadata_index_dir = experiment_dirs(
                    ctx,
                    model_dir,
                    scenario.name,
                )
                progress = get_experiment_progress(
                    metadata_index_dir,
                    gage_id,
                    status=True,
                )
                max_iter = get_max_iter(exp_config_dir, gage_id)
                metadata = read_metadata_index_file(
                    metadata_index_dir,
                    gage_id,
                )
                if metadata is not None and metadata.get("output_dir"):
                    average_seconds, remaining_seconds = (
                        estimate_calibration_timing(
                            Path(metadata["output_dir"]),
                            progress,
                            max_iter,
                        )
                    )
                else:
                    average_seconds, remaining_seconds = None, None
                calibration_complete = calibration_is_complete(
                    progress,
                    max_iter,
                )
                if "validation" in ctx.stages:
                    validation_exists = check_validation_exists(
                        metadata_index_dir,
                        gage_id,
                        status=True,
                    )
                    validation = "YES" if validation_exists else "NO"
                    finished = calibration_complete and validation_exists
                else:
                    validation = "NOT REQUESTED"
                    finished = calibration_complete

                scenario_suffix = f"_{scenario.name}" if scenario.name else ""
                job_name = f"{model_dir}{scenario_suffix}_{gage_id}"
                active_job = active_by_name.get(job_name)
                history = history_by_name.get(job_name)
                if finished:
                    state = "COMPLETED"
                elif active_job is not None and active_job.state == "PENDING":
                    state = "QUEUED"
                elif active_job is not None:
                    state = "RUNNING"
                elif scheduler_error is not None:
                    state = "UNKNOWN"
                else:
                    state = terminal_campaign_state(
                        progress,
                        history,
                    )

                current_iteration = (
                    progress.completed_iterations
                    if progress.completed_iterations is not None
                    else progress.current_iteration
                )
                statuses.append(
                    CampaignStatus(
                        gage_id=gage_id,
                        formulation=formulation_name,
                        scenario=scenario.display_name,
                        state=state,
                        current_iteration=current_iteration,
                        max_iterations=max_iter,
                        objective_value=progress.objective_value,
                        validation=validation,
                        average_iteration_seconds=average_seconds,
                        estimated_remaining_seconds=remaining_seconds,
                        slurm_job_id=(
                            active_job.job_id
                            if active_job is not None
                            else history.job_id if history is not None else None
                        ),
                    )
                )
    return statuses, scheduler_error


def print_status_filter(
    statuses: list[CampaignStatus],
    state: str,
) -> None:
    matches = [status for status in statuses if status.state == state]
    title = f"{state.replace('_', ' ').title()} Experiments"
    print(f"\n{title}")
    print("=" * len(title))
    if not matches:
        print(f"No experiments currently have status {state}.")
        return

    header = (
        f"{'Job ID':<14} {'Gage':<14} {'Formulation':<24} "
        f"{'Scenario':<14}"
    )
    print(header)
    print("-" * len(header))
    for status in matches:
        print(
            f"{(status.slurm_job_id or '-'):<14} "
            f"{status.gage_id:<14} {status.formulation:<24} "
            f"{status.scenario:<14}"
        )


def check_status(
    ctx: LauncherContext,
    *,
    detailed: bool = False,
    state_filter: str | None = None,
) -> None:
    statuses, scheduler_error = collect_campaign_status(ctx)
    if state_filter is not None:
        print_status_filter(statuses, state_filter)
        if scheduler_error is not None:
            print(f"Scheduler status unavailable: {scheduler_error}")
        return

    counts = {
        state: sum(status.state == state for status in statuses)
        for state in (*CAMPAIGN_STATUS_ORDER, "UNKNOWN")
    }

    print("\nCampaign Status Summary")
    print("========================")
    print(f"{'TOTAL':<18} | {len(statuses)}")
    for state in CAMPAIGN_STATUS_ORDER:
        print(f"{state:<18} | {counts[state]}")
    if counts["UNKNOWN"]:
        print(f"{'UNKNOWN':<18} | {counts['UNKNOWN']}")
    print("========================")
    if scheduler_error is not None:
        print(f"Scheduler status    : unavailable ({scheduler_error})")
    elif getattr(ctx, "slurm", {}):
        coordinator_name = f"{ctx.campaign_name}_launcher"
        try:
            coordinator_jobs = [
                job
                for job in get_active_slurm_jobs()
                if job.name == coordinator_name
            ]
        except RuntimeError as error:
            print(f"Coordinator status  : unavailable ({error})")
        else:
            if coordinator_jobs:
                description = ", ".join(
                    f"{job.job_id} {job.state}"
                    for job in sorted(
                        coordinator_jobs,
                        key=lambda job: int(job.job_id),
                    )
                )
                print(f"Coordinator status  : {description}")
            elif any(status.state != "COMPLETED" for status in statuses):
                print(
                    "Coordinator status  : MISSING while campaign work "
                    "remains"
                )

    if not detailed:
        return

    print("\nDetailed Experiment Status")
    print("==========================")
    header = (
        f"{'Gage':<12} {'Formulation':<24} {'Scenario':<12} "
        f"{'State':<20} {'Calib (cur|max|obj)':<24} "
        f"{'Est. avg/iter':<14} {'Est. remaining':<15} {'Validation':<14}"
    )
    print(header)
    print("-" * len(header))
    for status in sorted(statuses, key=detailed_status_sort_key):
        current_iter = (
            str(status.current_iteration)
            if status.current_iteration is not None
            else "-"
        )
        obj_value = (
            str(status.objective_value)
            if status.objective_value is not None
            else "-"
        )
        calibration = (
            f"{current_iter} | {status.max_iterations} | {obj_value}"
        )
        average_time = format_estimated_minutes(
            status.average_iteration_seconds
        )
        if status.state in {"FAILED", "OUT_OF_MEMORY", "CANCELLED"}:
            remaining_time = "-"
        elif (
            status.current_iteration is not None
            and status.current_iteration >= status.max_iterations
        ):
            remaining_time = "DONE"
        elif status.estimated_remaining_seconds is not None:
            remaining_time = format_estimated_minutes(
                status.estimated_remaining_seconds
            )
        else:
            remaining_time = "-"
        print(
            f"{status.gage_id:<12} {status.formulation:<24} "
            f"{status.scenario:<12} {status.state:<20} "
            f"{calibration:<24} {average_time:<14} "
            f"{remaining_time:<15} {status.validation:<14}"
        )
    print("-" * len(header))


def is_experiment_complete(
    ctx: LauncherContext,
    gage_id: str,
    model_dir: str,
    scenario_name: str | None = None,
) -> bool:
    exp_config_dir, metadata_index_dir = experiment_dirs(
        ctx,
        model_dir,
        scenario_name,
    )
    progress = get_experiment_progress(metadata_index_dir, gage_id, status=True)
    max_iter = get_max_iter(exp_config_dir, gage_id)
    calibration_complete = calibration_is_complete(progress, max_iter)
    if not calibration_complete:
        return False
    if "validation" not in ctx.stages:
        return True
    return check_validation_exists(
        metadata_index_dir,
        gage_id,
        status=True,
    )


def get_active_slurm_jobs() -> list[ActiveSlurmJob]:
    # NumTasks represents MPI ranks. NumCPUs represents the scheduler's CPU
    # request, which can be larger when a job requests substantial memory.
    user = getpass.getuser()
    cmd = [
        "squeue",
        "-u",
        user,
        "-h",
        "-O",
        "JobID:20,Name:200,NumTasks:12,NumCPUs:12,State:30",
    ]
    try:
        output = subprocess.check_output(cmd, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "Unable to query active Slurm jobs with squeue; refusing to "
            "submit because launcher limits cannot be enforced."
        ) from error

    jobs = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            job_id, name, num_tasks, num_cpus, state = line.split(maxsplit=4)
            jobs.append(
                ActiveSlurmJob(
                    job_id.strip(),
                    name.strip(),
                    int(num_tasks.strip()),
                    state.strip().upper(),
                    int(num_cpus.strip()),
                )
            )
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                f"Unexpected squeue output while enforcing Slurm limits: {line!r}"
            ) from error
    return jobs


def expected_slurm_job_names(ctx: LauncherContext) -> set[str]:
    names = set()
    for gage_id in ctx.map_cfg["mapping"]:
        for formulation_name, _ in get_formulations_for_gage(ctx, gage_id):
            model_dir = model_name_to_dir(formulation_name)
            for scenario in get_calibration_scenarios(ctx, gage_id):
                scenario_suffix = f"_{scenario.name}" if scenario.name else ""
                names.add(f"{model_dir}{scenario_suffix}_{gage_id}")
    return names


def slurm_limits(slurm: dict[str, Any]) -> tuple[int, int, int]:
    max_active_jobs = slurm.get("max_active_jobs")
    if max_active_jobs is None:
        raise ValueError(
            "Slurm execution requires slurm.max_active_jobs in "
            "launcher_config.yaml to prevent unbounded job submission."
        )
    max_total_mpi_tasks = slurm.get("max_total_mpi_tasks")
    if max_total_mpi_tasks is None:
        raise ValueError(
            "Slurm execution requires slurm.max_total_mpi_tasks in "
            "launcher_config.yaml to cap aggregate MPI ranks."
        )
    max_total_allocated_cpus = slurm.get("max_total_allocated_cpus")
    if max_total_allocated_cpus is None:
        raise ValueError(
            "Slurm execution requires slurm.max_total_allocated_cpus in "
            "launcher_config.yaml to cap scheduler-allocated CPUs."
        )
    return (
        int(max_active_jobs),
        int(max_total_mpi_tasks),
        int(max_total_allocated_cpus),
    )


def slurm_limit_reason(
    *,
    active_jobs: int,
    active_mpi_tasks: int,
    active_allocated_cpus: int,
    requested_mpi_tasks: int,
    requested_allocated_cpus: int,
    max_active_jobs: int,
    max_total_mpi_tasks: int,
    max_total_allocated_cpus: int,
) -> str | None:
    if active_jobs >= max_active_jobs:
        return f"active-job limit reached ({active_jobs}/{max_active_jobs})"
    if requested_mpi_tasks > max_total_mpi_tasks:
        raise ValueError(
            f"A run requires {requested_mpi_tasks} MPI tasks, which exceeds "
            "slurm.max_total_mpi_tasks="
            f"{max_total_mpi_tasks}. Increase the limit or "
            "reduce simulation.partitioning."
        )
    if active_mpi_tasks + requested_mpi_tasks > max_total_mpi_tasks:
        return (
            "MPI-task limit reached "
            f"({active_mpi_tasks}+{requested_mpi_tasks}>"
            f"{max_total_mpi_tasks})"
        )
    if requested_allocated_cpus > max_total_allocated_cpus:
        raise ValueError(
            f"A run requires {requested_allocated_cpus} allocated CPUs, "
            "which exceeds slurm.max_total_allocated_cpus="
            f"{max_total_allocated_cpus}. Increase the limit or reduce the "
            "run's MPI tasks or memory request."
        )
    if (
        active_allocated_cpus + requested_allocated_cpus
        > max_total_allocated_cpus
    ):
        return (
            "allocated-CPU limit reached "
            f"({active_allocated_cpus}+{requested_allocated_cpus}>"
            f"{max_total_allocated_cpus})"
        )
    return None


def startup_delay_seconds(
    run_index: int,
    interval_seconds: int,
    *,
    cycle_size: int | None = None,
) -> int:
    """Return a deterministic startup delay for a scheduled run."""
    position = run_index if cycle_size is None else run_index % cycle_size
    return position * interval_seconds


def runner(ctx: LauncherContext, *, use_slurm: bool, dryrun: bool = False) -> None:
    incomplete_exists = False
    local_jobs: list[tuple[Any, ...]] = []
    active_job_names: set[str] = set()
    dependency_job_ids: set[str] = set()
    active_job_count = 0
    active_mpi_tasks = 0
    active_allocated_cpus = 0
    max_active_jobs = 0
    max_total_mpi_tasks = 0
    max_total_allocated_cpus = 0
    scheduled_run_index = 0

    if use_slurm:
        if not dryrun:
            ctx.log_dir.mkdir(parents=True, exist_ok=True)
            write_slurm_worker_script(ctx)
        (
            max_active_jobs,
            max_total_mpi_tasks,
            max_total_allocated_cpus,
        ) = slurm_limits(ctx.slurm)
        if not dryrun:
            expected_names = expected_slurm_job_names(ctx)
            campaign_jobs = [
                job
                for job in get_active_slurm_jobs()
                if job.name in expected_names
            ]
            active_job_names = {job.name for job in campaign_jobs}
            dependency_job_ids = {job.job_id for job in campaign_jobs}
            active_job_count = len(campaign_jobs)
            active_mpi_tasks = sum(job.num_tasks for job in campaign_jobs)
            active_allocated_cpus = sum(
                job.num_cpus if job.num_cpus is not None else job.num_tasks
                for job in campaign_jobs
            )
        print(
            "[INFO] Slurm launcher capacity: "
            f"jobs={active_job_count}/{max_active_jobs}, "
            f"MPI tasks={active_mpi_tasks}/{max_total_mpi_tasks}, "
            "allocated CPUs="
            f"{active_allocated_cpus}/{max_total_allocated_cpus}"
        )

    for unit in launcher_run_units(ctx):
        gage_id = unit.gage_id
        formulation_name = unit.formulation_name
        formulation_spec = unit.formulation_spec
        scenario = unit.scenario
        model_dir = model_name_to_dir(formulation_name)
        scenario_suffix = f"_{scenario.name}" if scenario.name else ""
        job_name = f"{model_dir}{scenario_suffix}_{gage_id}"
        exp_config_dir, metadata_index_dir = experiment_dirs(
            ctx,
            model_dir,
            scenario.name,
        )

        print("----------------------------------------------")
        print(f"---------  Processing Gage: {gage_id} ---------")
        print(
            f"--- Formulation: {formulation_name} | "
            f"Scenario: {scenario.display_name} ---"
        )

        if is_experiment_complete(
            ctx,
            gage_id,
            model_dir,
            scenario.name,
        ):
            print(
                f"[{gage_id}] Experiment '{job_name}' already "
                "completed. Skipping."
            )
            continue

        if job_name in active_job_names:
            print(
                f"[{gage_id}] Job '{job_name}' is already running "
                "or pending. Skipping."
            )
            incomplete_exists = True
            continue

        progress = get_experiment_progress(metadata_index_dir, gage_id)
        if not progress.configured:
            if "calibration" not in ctx.stages:
                raise RuntimeError(
                    f"Validation was requested for gage {gage_id}, "
                    f"experiment '{job_name}', but no configured "
                    "calibration run was found. Run calibration first."
                )
            print(
                f"[{gage_id}] Setup step for "
                f"{scenario.display_name}; generating configs."
            )
            generate_config_files_for_gage(
                ctx,
                formulation_name,
                formulation_spec,
                model_dir,
                gage_id,
                exp_config_dir,
                metadata_index_dir,
                scenario=scenario,
                dryrun=dryrun,
            )
            if not dryrun:
                progress = get_experiment_progress(
                    metadata_index_dir,
                    gage_id,
                )

        incomplete_exists = True

        if use_slurm:
            requested_mpi_tasks = get_num_cpus(
                metadata_index_dir,
                gage_id,
            )
            limit_reason = slurm_limit_reason(
                active_jobs=active_job_count,
                active_mpi_tasks=active_mpi_tasks,
                active_allocated_cpus=active_allocated_cpus,
                requested_mpi_tasks=requested_mpi_tasks,
                requested_allocated_cpus=requested_mpi_tasks,
                max_active_jobs=max_active_jobs,
                max_total_mpi_tasks=max_total_mpi_tasks,
                max_total_allocated_cpus=max_total_allocated_cpus,
            )
            if limit_reason:
                print(
                    f"[{gage_id}] Deferring '{job_name}': "
                    f"{limit_reason}."
                )
                continue
            delay_seconds = startup_delay_seconds(
                scheduled_run_index,
                ctx.slurm["startup_delay_seconds"],
            )
            run_result = run_experiment(
                ctx,
                model_dir,
                gage_id,
                job_name,
                exp_config_dir,
                metadata_index_dir,
                progress,
                delay_seconds,
                use_slurm=True,
                dryrun=dryrun,
            )
            if run_result.slurm_job_id is not None:
                dependency_job_ids.add(run_result.slurm_job_id)
            active_job_names.add(job_name)
            active_job_count += 1
            active_mpi_tasks += requested_mpi_tasks
            submitted_allocated_cpus = requested_mpi_tasks
            if run_result.slurm_job_id is not None:
                try:
                    submitted_job = next(
                        (
                            job
                            for job in get_active_slurm_jobs()
                            if job.job_id == run_result.slurm_job_id
                        ),
                        None,
                    )
                except RuntimeError:
                    submitted_job = None
                if submitted_job is not None:
                    submitted_allocated_cpus = (
                        submitted_job.num_cpus
                        if submitted_job.num_cpus is not None
                        else submitted_job.num_tasks
                    )
            active_allocated_cpus += submitted_allocated_cpus
            if active_allocated_cpus > max_total_allocated_cpus:
                print(
                    "[WARNING] Slurm increased the submitted job's CPU "
                    "request to satisfy its memory request. Campaign "
                    "allocated CPUs are now "
                    f"{active_allocated_cpus}/{max_total_allocated_cpus}; "
                    "no additional jobs will be admitted until capacity "
                    "returns below the limit."
                )
            scheduled_run_index += 1
        elif dryrun:
            delay_seconds = startup_delay_seconds(
                scheduled_run_index,
                ctx.local["startup_delay_seconds"],
                cycle_size=ctx.local["max_workers"],
            )
            run_experiment(
                ctx,
                model_dir,
                gage_id,
                job_name,
                exp_config_dir,
                metadata_index_dir,
                progress,
                delay_seconds,
                use_slurm=False,
                dryrun=True,
            )
            scheduled_run_index += 1
        else:
            delay_seconds = startup_delay_seconds(
                scheduled_run_index,
                ctx.local["startup_delay_seconds"],
                cycle_size=ctx.local["max_workers"],
            )
            local_jobs.append(
                (
                    ctx,
                    model_dir,
                    gage_id,
                    job_name,
                    exp_config_dir,
                    metadata_index_dir,
                    progress,
                    delay_seconds,
                    dryrun,
                )
            )
            scheduled_run_index += 1

    if not use_slurm and local_jobs:
        max_workers = min(ctx.local["max_workers"], multiprocessing.cpu_count())
        print(f"\n[INFO] Running locally with up to {max_workers} parallel workers\n")
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(local_worker, job) for job in local_jobs]
            for future in as_completed(futures):
                future.result()

    print("\n=== Launcher Finished ===\n")

    if use_slurm and not dryrun:
        if incomplete_exists:
            if not dependency_job_ids:
                raise RuntimeError(
                    "Launcher work remains incomplete, but no active or newly "
                    "submitted worker job IDs are available for a follow-up "
                    "dependency. Review the launcher output and Slurm limits."
                )
            submit_launcher(
                ctx,
                tuple(sorted(dependency_job_ids, key=int)),
            )
        else:
            print("[INFO] All launcher work is complete.")


def print_check_report(ctx: LauncherContext) -> None:
    validate_context(ctx)
    print("Launcher Check")
    print("==============")
    print(f"Launcher config : {ctx.launcher_config_file}")
    print(f"Campaign name   : {ctx.campaign_name}")
    print("Sandbox settings: top-level blocks in the launcher configuration")
    print("Formulations    : resolved from the formulations block")
    print(f"Worker script   : {worker_script_path(ctx)} (generated for Slurm runs)")
    print(f"Input dir       : {ctx.input_dir}")
    print(f"Output dir      : {ctx.output_dir}")
    print(f"Slurm logs      : {ctx.log_dir}")
    print(f"Tasks           : {', '.join(ctx.stages)}")
    print(
        "Scenario order  : "
        f"{ctx.scenario_execution_mode} "
        f"({', '.join(ctx.scenario_order)})"
    )
    print(f"Local workers   : {ctx.local['max_workers']}")
    print(f"Local delay     : {ctx.local['startup_delay_seconds']} sec")
    print(f"Mapped gages    : {len(ctx.map_cfg['mapping'])}")
    print(f"Formulations    : {len(ctx.map_cfg['formulations'])}")
    if ctx.slurm:
        common_slurm = {
            key: value
            for key, value in ctx.slurm.items()
            if key not in {
                "calibration",
                "validation",
                "modules",
                "environment",
            }
        }
        print("Slurm settings  : " + ", ".join(
            f"{key}={value}" for key, value in common_slurm.items()
        ))
        modules = ctx.slurm.get("modules", [])
        environment = ctx.slurm.get("environment", {})
        print(
            "Slurm modules   : "
            + (", ".join(modules) if modules else "none")
        )
        print(
            "Slurm environment: "
            + (
                ", ".join(f"{name}={value}" for name, value in environment.items())
                if environment
                else "none"
            )
        )
        for stage in ("calibration", "validation"):
            settings = ctx.slurm[stage]
            print(
                f"Slurm {stage:<11}: time={settings['time']}, "
                f"memory={settings['memory']}"
            )
    if ctx.selection_summary:
        print("\nResolved formulation selection")
        print("-------------------------------")
        for formulation_name, gage_count in ctx.selection_summary.items():
            print(f"{formulation_name}: {gage_count} gage(s)")
    print("\nResolved calibration plan")
    print("-------------------------")
    for gage_id in ctx.map_cfg["mapping"]:
        formulations = get_formulations_for_gage(ctx, gage_id)
        model_dir = model_name_to_dir(formulations[0][0])
        for scenario in get_calibration_scenarios(ctx, gage_id):
            resolved_period = resolve_time_period(
                scenario.calibration,
                f"launcher plan {gage_id}.{scenario.display_name}",
                allow_selected_years=True,
            )
            simulation_time = resolved_period["simulation_time"]
            _, metadata_index_dir = experiment_dirs(
                ctx,
                model_dir,
                scenario.name,
            )
            metadata_file = metadata_index_dir / f"run_{gage_id}.yml"
            tasks = (
                str(get_num_cpus(metadata_index_dir, gage_id))
                if metadata_file.is_file()
                else "pending config"
            )
            years = (
                ",".join(str(year) for year in scenario.selected_years)
                if scenario.selected_years
                else "all post-spinup values"
            )
            print(
                f"{gage_id} | {scenario.display_name} | "
                f"{simulation_time['start_time']} to "
                f"{simulation_time['end_time']} | "
                f"years: {years} | MPI tasks: {tasks} | "
                f"formulations: {len(formulations)}"
            )
    validate_launcher_resources(ctx, verbose=True)
    print("Launcher configuration and required resources look valid.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or inspect Sandbox Launcher jobs.")
    parser.add_argument(
        "mode",
        choices=["run", "submit", "dryrun", "status", "check"],
        help=(
            "Run locally, submit to Slurm, preview execution, show status, "
            "or validate launcher inputs."
        ),
    )
    parser.add_argument(
        "--backend",
        choices=["slurm", "local"],
        default="slurm",
        help="Execution backend for run and dryrun modes.",
    )
    parser.add_argument(
        "--config",
        default="launcher_config.yaml",
        help=(
            "Path to any launcher YAML configuration file. Defaults to the "
            "repository example."
        ),
    )
    status_view = parser.add_mutually_exclusive_group()
    status_view.add_argument(
        "--summary",
        dest="status_view",
        action="store_const",
        const="summary",
        help="Print campaign status totals (the default status view).",
    )
    status_view.add_argument(
        "--detailed",
        dest="status_view",
        action="store_const",
        const="detailed",
        help="Print campaign totals and one line per resolved experiment.",
    )
    for view_name, state in STATUS_FILTERS.items():
        status_view.add_argument(
            f"--{view_name.replace('_', '-')}",
            dest="status_view",
            action="store_const",
            const=view_name,
            help=(
                f"Print only {state.lower().replace('_', ' ')} jobs and "
                "their gage IDs."
            ),
        )
    parser.set_defaults(status_view="summary")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ctx = load_context(Path(args.config))
    print(f"\n=== Sandbox Launcher Started @ {datetime.now()} ===")

    if args.mode == "check":
        print_check_report(ctx)
        return

    validate_context(ctx)
    if args.mode == "status":
        check_status(
            ctx,
            detailed=args.status_view == "detailed",
            state_filter=STATUS_FILTERS.get(args.status_view),
        )
        return
    validate_launcher_resources(ctx)
    if args.mode == "submit":
        submit_launcher(ctx)
        return

    runner(
        ctx,
        use_slurm=args.backend == "slurm",
        dryrun=args.mode == "dryrun",
    )


if __name__ == "__main__":
    main()
