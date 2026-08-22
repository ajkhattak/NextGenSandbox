from __future__ import annotations

import argparse
import csv
import copy
import getpass
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.python.calibration_config import absolutize_optimizer_settings_file
from src.python.time_windows import (
    NGEN_TIMESTEP,
    format_timestamp,
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
    sandbox_config_file: Path
    map_config_file: Path | None
    submit_script: Path
    base_sandbox_cfg: dict[str, Any]
    map_cfg: dict[str, Any]
    output_dir: Path
    input_dir: Path
    metadata_index_dir_name: str
    num_workers: int
    startup_delay_seconds: int
    assignment_summary: dict[str, dict[str, int]]
    calibration_scenarios: dict[str, tuple[CalibrationScenario, ...]]
    slurm: dict[str, Any]


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
    name: str
    num_cpus: int


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
    return Path(__file__).resolve().parent / "launcher_config.yaml"


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


def resolve_experiment_list(
    selected: Any,
    experiments: dict[str, Any],
    field_name: str,
) -> list[str]:
    names = as_list(selected, field_name)
    if not names:
        return []
    if "all" in names:
        if len(names) > 1:
            raise ValueError(f"{field_name} cannot mix 'all' with experiment names")
        return list(experiments)

    unknown = sorted(set(names) - set(experiments))
    if unknown:
        raise ValueError(
            f"{field_name} references unknown experiment(s): {', '.join(unknown)}"
        )
    return unique_ordered(names)


def load_launcher_gages(launcher_cfg: dict[str, Any], launcher_dir: Path) -> dict[str, list[str]]:
    gages_cfg = launcher_cfg.get("gages")
    if not isinstance(gages_cfg, dict):
        raise ValueError("launcher_config.yaml must define a gages block")

    option = str(gages_cfg.get("option", "")).lower()
    if option == "ids":
        return {gage: [] for gage in as_list(gages_cfg.get("ids"), "gages.ids")}

    if option != "file":
        raise ValueError("gages.option must be one of: ids, file")

    file_cfg = gages_cfg.get("file") or {}
    path = resolve_path(launcher_dir, file_cfg.get("path", ""))
    id_column = file_cfg.get("id_column") or file_cfg.get("column", "gage_id")
    group_column = file_cfg.get("group_column")

    if not path.exists():
        raise FileNotFoundError(f"gages.file.path not found: {path}")

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


def build_map_from_launcher_config(
    launcher_cfg: dict[str, Any],
    launcher_dir: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    experiments = launcher_cfg.get("experiments")
    if not isinstance(experiments, dict) or not experiments:
        raise ValueError("launcher_config.yaml must define a non-empty experiments block")

    assignment = launcher_cfg.get("assignment") or {}
    if not isinstance(assignment, dict):
        raise ValueError("assignment must be a mapping")

    gage_groups = load_launcher_gages(launcher_cfg, launcher_dir)
    if not gage_groups:
        raise ValueError("No gages were resolved from launcher_config.yaml")

    default_selection = assignment.get("default", ["all"])
    group_assignments = assignment.get("groups", {}) or {}
    if not isinstance(group_assignments, dict):
        raise ValueError("assignment.groups must be a mapping")

    resolved_group_assignments = {
        group: resolve_experiment_list(
            selected,
            experiments,
            f"assignment.groups.{group}",
        )
        for group, selected in group_assignments.items()
    }
    default_experiments = resolve_experiment_list(
        default_selection,
        experiments,
        "assignment.default",
    )

    mapping: dict[str, list[str]] = {}
    summary: dict[str, dict[str, int]] = {}

    for gage_id, groups in gage_groups.items():
        selected: list[str] = []
        matched_groups = [group for group in groups if group in resolved_group_assignments]

        if matched_groups:
            for group in matched_groups:
                selected.extend(resolved_group_assignments[group])
                group_summary = summary.setdefault(group, {"gages": 0, "experiments": 0})
                group_summary["gages"] += 1
                group_summary["experiments"] = len(resolved_group_assignments[group])
        else:
            selected.extend(default_experiments)
            fallback_group = groups[0] if groups else "default"
            summary.setdefault(fallback_group, {"gages": 0, "experiments": len(default_experiments)})
            summary[fallback_group]["gages"] += 1

        mapping[gage_id] = unique_ordered(selected)

    return {
        "formulations": experiments,
        "mapping": mapping,
    }, summary


def apply_project_overrides(base_sandbox_cfg: dict[str, Any], launcher_cfg: dict[str, Any]) -> dict[str, Any]:
    sandbox_cfg = copy.deepcopy(base_sandbox_cfg)
    project = launcher_cfg.get("project") or {}
    if not project:
        return sandbox_cfg

    general = sandbox_cfg.setdefault("general", {})
    for key in ("input_dir", "output_dir", "resource_layout"):
        if key in project:
            general[key] = project[key]
    return sandbox_cfg


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
    launcher_cfg: dict[str, Any],
    map_cfg: dict[str, Any],
    base_sandbox_cfg: dict[str, Any],
    launcher_dir: Path,
) -> dict[str, tuple[CalibrationScenario, ...]]:
    gage_ids = list(map_cfg["mapping"])
    regime_config = launcher_cfg.get("regime_calibration")
    if regime_config is None:
        calibration = (
            base_sandbox_cfg.get("simulation", {})
            .get("time", {})
            .get("calibration")
        )
        if not isinstance(calibration, dict):
            raise ValueError(
                "Base sandbox config must define simulation.time.calibration"
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

    launcher_dir = config_file.resolve().parent
    launcher_cfg = load_yaml(config_file)

    templates = launcher_cfg.get("templates", {}) or {}
    execution = launcher_cfg.get("execution", {}) or {}

    sandbox_config_file = resolve_path(
        launcher_dir,
        templates.get(
            "sandbox_config",
            launcher_cfg.get("sandbox_config", "basefiles/sandbox_config_base.yaml"),
        ),
    )
    submit_script = resolve_path(
        launcher_dir,
        launcher_cfg.get("submit_script", "submit_gage.slurm"),
    )

    base_sandbox_cfg = apply_project_overrides(
        load_yaml(sandbox_config_file),
        launcher_cfg,
    )
    absolutize_optimizer_settings_file(
        base_sandbox_cfg,
        sandbox_config_file,
    )

    if {"experiments", "gages", "assignment"}.issubset(launcher_cfg):
        map_config_file = None
        map_cfg, assignment_summary = build_map_from_launcher_config(
            launcher_cfg,
            launcher_dir,
        )
    else:
        map_config_file = resolve_path(
            launcher_dir,
            launcher_cfg.get("mapping_config", "models_gages_map.yaml"),
        )
        map_cfg = load_yaml(map_config_file)
        assignment_summary = {}

    output_dir = Path(base_sandbox_cfg["general"]["output_dir"]).expanduser()
    input_dir = Path(base_sandbox_cfg["general"]["input_dir"]).expanduser()
    metadata = (
        base_sandbox_cfg.get("simulation", {})
        .get("outputs", {})
        .get("metadata", {})
    )
    metadata_index_dir_name = metadata.get("index_dir", "metadata")
    calibration_scenarios = resolve_calibration_scenarios(
        launcher_cfg,
        map_cfg,
        base_sandbox_cfg,
        launcher_dir,
    )
    slurm = launcher_cfg.get("slurm") or {}
    if not isinstance(slurm, dict):
        raise TypeError("slurm must be a YAML dictionary/object")

    return LauncherContext(
        launcher_dir=launcher_dir,
        launcher_config_file=config_file,
        sandbox_config_file=sandbox_config_file,
        map_config_file=map_config_file,
        submit_script=submit_script,
        base_sandbox_cfg=base_sandbox_cfg,
        map_cfg=map_cfg,
        output_dir=output_dir,
        input_dir=input_dir,
        metadata_index_dir_name=metadata_index_dir_name,
        num_workers=int(execution.get("num_workers", launcher_cfg.get("num_workers", 2))),
        startup_delay_seconds=int(
            execution.get(
                "startup_delay_seconds",
                launcher_cfg.get("startup_delay_seconds", 5),
            )
        ),
        assignment_summary=assignment_summary,
        calibration_scenarios=calibration_scenarios,
        slurm=slurm,
    )


def validate_base_sandbox_config(config: dict[str, Any]) -> None:
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
            "Project paths are missing. Define project.input_dir and "
            "project.output_dir in launcher_config.yaml (recommended), or "
            "define general.input_dir and general.output_dir in the base "
            "Sandbox config."
        )
    metadata = simulation.get("outputs", {}).get("metadata", {})
    if not metadata.get("enabled"):
        raise ValueError(
            "Launcher requires simulation.outputs.metadata.enabled: true "
            "in the base sandbox config"
        )
    if not metadata.get("index_dir"):
        raise ValueError("Launcher requires simulation.outputs.metadata.index_dir")


def validate_mapping_config(map_cfg: dict[str, Any]) -> None:
    formulations = map_cfg.get("formulations")
    mapping = map_cfg.get("mapping")
    if not isinstance(formulations, dict) or not formulations:
        raise ValueError("models_gages_map.yaml must define a non-empty formulations mapping")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("models_gages_map.yaml must define a non-empty mapping block")

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
    required_files = [ctx.sandbox_config_file]
    if ctx.map_config_file is not None:
        required_files.append(ctx.map_config_file)

    for path in required_files:
        if not path.exists():
            raise FileNotFoundError(f"Required launcher file not found: {path}")
    if not ctx.submit_script.exists():
        raise FileNotFoundError(f"SLURM submit script not found: {ctx.submit_script}")
    if ctx.num_workers < 1:
        raise ValueError("num_workers must be greater than or equal to 1")
    unknown_slurm = sorted(
        set(ctx.slurm)
        - {
            "account",
            "partition",
            "time",
            "memory",
            "mpi_tasks",
            "max_active_jobs",
            "max_mpi_tasks",
        }
    )
    if unknown_slurm:
        raise ValueError(
            f"slurm contains unsupported field(s): {', '.join(unknown_slurm)}"
        )
    if "mpi_tasks" in ctx.slurm and ctx.slurm["mpi_tasks"] != "auto":
        raise ValueError("slurm.mpi_tasks must be: auto")
    for field_name in ("max_active_jobs", "max_mpi_tasks"):
        value = ctx.slurm.get(field_name)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(f"slurm.{field_name} must be a positive integer")
    validate_base_sandbox_config(ctx.base_sandbox_cfg)
    validate_mapping_config(ctx.map_cfg)


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
    sandbox_cfg = copy.deepcopy(ctx.base_sandbox_cfg)
    scenario_name = scenario.name if scenario else None
    output_dir = experiment_output_dir(ctx, model_dir, scenario_name)

    general = sandbox_cfg.setdefault("general", {})
    general["output_dir"] = str(output_dir)
    general["gages"] = {
        "option": "ids",
        "ids": [gage_id],
    }
    formulation = sandbox_cfg.setdefault("formulation", {})
    formulation["models"] = formulation_spec["models"]
    if "model_instances" in formulation_spec:
        formulation["model_instances"] = copy.deepcopy(
            formulation_spec["model_instances"]
        )
    else:
        formulation.pop("model_instances", None)
    simulation = sandbox_cfg.setdefault("simulation", {})
    simulation["gages"] = [gage_id]
    simulation["task_type"] = "calibration"
    if scenario is not None:
        simulation.setdefault("time", {})["calibration"] = (
            copy.deepcopy(scenario.calibration)
        )
    if scenario_name:
        simulation.pop("label", None)

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
    sandbox_restart_cfg["simulation"]["task_type"] = "restart"
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
    sandbox_val_cfg["simulation"]["task_type"] = "validation"
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
    simulation["task_type"] = "calibration"
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
    submit_script: Path,
    sandbox_file: Path,
    job_name: str,
    num_mpi_tasks: int,
    delay_seconds: int,
    slurm: dict[str, Any] | None = None,
) -> list[str]:
    command = [
        "sbatch",
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
    command.extend(
        [
            "--export=ALL,"
            f"SANDBOX_FILE={sandbox_file},"
            f"START_DELAY={delay_seconds}",
            str(submit_script),
        ]
    )
    return command


def select_experiment_config(
    paths: dict[str, Path],
    progress: ExperimentProgress,
    max_iter: int,
) -> Path:
    if not progress.started:
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
        if progress.algorithm == "pso":
            return prepare_pso_warm_start_config(
                paths,
                progress.checkpoint_file,
            )
        return paths["sandbox_restart"]

    return paths["sandbox_validation"]


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
) -> None:
    paths = generated_config_paths(exp_config_dir, gage_id)
    max_iter = get_max_iter(exp_config_dir, gage_id)
    if max_iter == 0 and not progress.configured:
        max_iter = 1
    sandbox_file = select_experiment_config(paths, progress, max_iter)

    if check_validation_exists(metadata_index_dir, gage_id):
        return

    if use_slurm:
        num_mpi_tasks = get_num_cpus(metadata_index_dir, gage_id)
        cmd = build_slurm_submit_command(
            ctx.submit_script,
            sandbox_file,
            job_name,
            num_mpi_tasks,
            delay_seconds,
            ctx.slurm,
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
            print(f"[DRYRUN] [{gage_id}] Would run locally: {' '.join(cmd)}")
        else:
            print(f"[{gage_id}] Running locally: {' '.join(cmd)}")

    if dryrun:
        return

    if not use_slurm:
        time.sleep(delay_seconds)
    subprocess.run(cmd, check=True)


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
        dryrun=dryrun,
    )


def check_status(ctx: LauncherContext) -> None:
    print("\n============================ STATUS REPORT ==============================")
    header = (
        f"{'Gage':<12} {'Formulation':<24} {'Scenario':<12} "
        f"{'Calib (cur|max|obj)':<24} {'Validation':<10}"
    )
    print(header)
    print("-" * len(header))

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
                validation_exists = check_validation_exists(
                    metadata_index_dir,
                    gage_id,
                    status=True,
                )
                valid_flag = "YES" if validation_exists else "NO"
                current_iter = (
                    str(progress.completed_iterations)
                    if progress.completed_iterations is not None
                    else "-"
                )
                obj_value = (
                    str(progress.objective_value)
                    if progress.objective_value is not None
                    else "-"
                )
                status_text = f"{current_iter} | {max_iter} | {obj_value}"
                print(
                    f"{gage_id:<12} {formulation_name:<24} "
                    f"{scenario.display_name:<12} {status_text:<24} "
                    f"{valid_flag:<10}"
                )

    print("-" * len(header))
    print("======================== STATUS REPORT COMPLETE =========================")


def launcher_exit(incomplete_exists: bool) -> None:
    wallclock_min_str = os.getenv("LAUNCHER_WALLCLOCK_MIN")
    if wallclock_min_str is None:
        raise RuntimeError(
            "LAUNCHER_WALLCLOCK_MIN must be set before SLURM requeue handling."
        )

    wallclock_min = int(wallclock_min_str)
    buffer_seconds = 30
    max_runtime_sec = max(0, wallclock_min * 60 - buffer_seconds)

    if incomplete_exists:
        print("[INFO] Incomplete gages/models detected; requesting SLURM requeue.")
        time.sleep(max_runtime_sec)
        sys.exit(99)

    print("[INFO] All work complete; exiting normally.")
    sys.exit(0)


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
    validation_exists = check_validation_exists(metadata_index_dir, gage_id, status=True)
    return (
        progress.started
        and (
            progress.completed_iterations
            if progress.completed_iterations is not None
            else progress.current_iteration
        ) >= max_iter
        and validation_exists
    )


def get_active_slurm_jobs() -> list[ActiveSlurmJob]:
    user = getpass.getuser()
    cmd = ["squeue", "-u", user, "-h", "-o", "%j|%C", "-t", "R,PD"]
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
            name, cpus = line.rsplit("|", 1)
            jobs.append(ActiveSlurmJob(name.strip(), int(cpus.strip())))
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


def slurm_limits(slurm: dict[str, Any]) -> tuple[int, int]:
    max_active_jobs = slurm.get("max_active_jobs")
    if max_active_jobs is None:
        raise ValueError(
            "Slurm execution requires slurm.max_active_jobs in "
            "launcher_config.yaml to prevent unbounded job submission."
        )
    max_mpi_tasks = slurm.get("max_mpi_tasks")
    if max_mpi_tasks is None:
        raise ValueError(
            "Slurm execution requires slurm.max_mpi_tasks in "
            "launcher_config.yaml to cap aggregate requested cores."
        )
    return int(max_active_jobs), int(max_mpi_tasks)


def slurm_limit_reason(
    *,
    active_jobs: int,
    active_mpi_tasks: int,
    requested_mpi_tasks: int,
    max_active_jobs: int,
    max_mpi_tasks: int,
) -> str | None:
    if active_jobs >= max_active_jobs:
        return f"active-job limit reached ({active_jobs}/{max_active_jobs})"
    if requested_mpi_tasks > max_mpi_tasks:
        raise ValueError(
            f"A run requires {requested_mpi_tasks} MPI tasks, which exceeds "
            f"slurm.max_mpi_tasks={max_mpi_tasks}. Increase the limit or "
            "reduce simulation.partitioning."
        )
    if active_mpi_tasks + requested_mpi_tasks > max_mpi_tasks:
        return (
            "MPI-task limit reached "
            f"({active_mpi_tasks}+{requested_mpi_tasks}>{max_mpi_tasks})"
        )
    return None


def runner(ctx: LauncherContext, *, use_slurm: bool, dryrun: bool = False) -> None:
    incomplete_exists = False
    local_jobs: list[tuple[Any, ...]] = []
    active_job_names: set[str] = set()
    active_job_count = 0
    active_mpi_tasks = 0
    max_active_jobs = 0
    max_mpi_tasks = 0

    if use_slurm:
        max_active_jobs, max_mpi_tasks = slurm_limits(ctx.slurm)
        if not dryrun:
            expected_names = expected_slurm_job_names(ctx)
            campaign_jobs = [
                job
                for job in get_active_slurm_jobs()
                if job.name in expected_names
            ]
            active_job_names = {job.name for job in campaign_jobs}
            active_job_count = len(campaign_jobs)
            active_mpi_tasks = sum(job.num_cpus for job in campaign_jobs)
        print(
            "[INFO] Slurm launcher capacity: "
            f"jobs={active_job_count}/{max_active_jobs}, "
            f"MPI tasks={active_mpi_tasks}/{max_mpi_tasks}"
        )

    for gage_id in ctx.map_cfg["mapping"]:
        print("----------------------------------------------")
        print(f"---------  Processing Gage: {gage_id} ---------")

        formulations_for_gage = get_formulations_for_gage(ctx, gage_id)
        for index, (formulation_name, formulation_spec) in enumerate(formulations_for_gage):
            print(
                f"\n--- Formulation {index + 1}/{len(formulations_for_gage)} | "
                f"{formulation_name} ---"
            )

            model_dir = model_name_to_dir(formulation_name)
            scenarios = get_calibration_scenarios(ctx, gage_id)
            for scenario_index, scenario in enumerate(scenarios):
                scenario_suffix = f"_{scenario.name}" if scenario.name else ""
                job_name = f"{model_dir}{scenario_suffix}_{gage_id}"
                exp_config_dir, metadata_index_dir = experiment_dirs(
                    ctx,
                    model_dir,
                    scenario.name,
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
                delay_index = index * len(scenarios) + scenario_index
                delay_seconds = delay_index * ctx.startup_delay_seconds

                if use_slurm:
                    requested_mpi_tasks = get_num_cpus(
                        metadata_index_dir,
                        gage_id,
                    )
                    limit_reason = slurm_limit_reason(
                        active_jobs=active_job_count,
                        active_mpi_tasks=active_mpi_tasks,
                        requested_mpi_tasks=requested_mpi_tasks,
                        max_active_jobs=max_active_jobs,
                        max_mpi_tasks=max_mpi_tasks,
                    )
                    if limit_reason:
                        print(
                            f"[{gage_id}] Deferring '{job_name}': "
                            f"{limit_reason}."
                        )
                        continue
                    run_experiment(
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
                    active_job_names.add(job_name)
                    active_job_count += 1
                    active_mpi_tasks += requested_mpi_tasks
                elif dryrun:
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
                else:
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

    if not use_slurm and local_jobs:
        max_workers = min(ctx.num_workers, multiprocessing.cpu_count())
        print(f"\n[INFO] Running locally with up to {max_workers} parallel workers\n")
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(local_worker, job) for job in local_jobs]
            for future in as_completed(futures):
                future.result()

    print("\n=== Launcher Finished ===\n")

    if use_slurm and not dryrun:
        launcher_exit(incomplete_exists)


def print_check_report(ctx: LauncherContext) -> None:
    validate_context(ctx)
    print("Launcher Check")
    print("==============")
    print(f"Launcher config : {ctx.launcher_config_file}")
    print(f"Sandbox config  : {ctx.sandbox_config_file}")
    print(f"Mapping config  : {ctx.map_config_file or 'resolved from launcher_config.yaml'}")
    print(f"Submit script   : {ctx.submit_script}")
    print(f"Input dir       : {ctx.input_dir}")
    print(f"Output dir      : {ctx.output_dir}")
    print(f"Num workers     : {ctx.num_workers}")
    print(f"Mapped gages    : {len(ctx.map_cfg['mapping'])}")
    print(f"Formulations    : {len(ctx.map_cfg['formulations'])}")
    if ctx.slurm:
        print("Slurm settings  : " + ", ".join(
            f"{key}={value}" for key, value in ctx.slurm.items()
        ))
    if ctx.assignment_summary:
        print("\nResolved assignment summary")
        print("---------------------------")
        for group, counts in ctx.assignment_summary.items():
            print(
                f"{group}: {counts['gages']} gage(s) x "
                f"{counts['experiments']} experiment(s)"
            )
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
                f"experiments: {len(formulations)}"
            )
    print("Launcher configuration looks valid.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or inspect Sandbox Launcher jobs.")
    parser.add_argument(
        "mode",
        choices=["run", "dryrun", "status", "check"],
        help=(
            "Run experiments, preview execution, show status, or validate "
            "launcher inputs."
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
        help="Path to launcher_config.yaml. Defaults to tools/launcher/launcher_config.yaml.",
    )
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
        check_status(ctx)
        return

    runner(
        ctx,
        use_slurm=args.backend == "slurm",
        dryrun=args.mode == "dryrun",
    )


if __name__ == "__main__":
    main()
