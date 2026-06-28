from __future__ import annotations

import argparse
import csv
import copy
import getpass
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


@dataclass(frozen=True)
class LauncherContext:
    launcher_dir: Path
    launcher_config_file: Path
    sandbox_config_file: Path
    calib_config_file: Path
    map_config_file: Path | None
    submit_script: Path
    base_sandbox_cfg: dict[str, Any]
    base_calib_cfg: dict[str, Any]
    map_cfg: dict[str, Any]
    output_dir: Path
    input_dir: Path
    exp_info_dir_name: str
    num_workers: int
    startup_delay_seconds: int
    assignment_summary: dict[str, dict[str, int]]


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
    calib_config_file = resolve_path(
        launcher_dir,
        templates.get(
            "calib_config",
            launcher_cfg.get("calib_config", "basefiles/calib_config_base.yaml"),
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
    base_calib_cfg = load_yaml(calib_config_file)

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
    exp_info_dir_name = (
        base_sandbox_cfg.get("sandbox_launcher", {}).get("exp_info_dir", "info")
    )

    return LauncherContext(
        launcher_dir=launcher_dir,
        launcher_config_file=config_file,
        sandbox_config_file=sandbox_config_file,
        calib_config_file=calib_config_file,
        map_config_file=map_config_file,
        submit_script=submit_script,
        base_sandbox_cfg=base_sandbox_cfg,
        base_calib_cfg=base_calib_cfg,
        map_cfg=map_cfg,
        output_dir=output_dir,
        input_dir=input_dir,
        exp_info_dir_name=exp_info_dir_name,
        num_workers=int(execution.get("num_workers", launcher_cfg.get("num_workers", 2))),
        startup_delay_seconds=int(
            execution.get(
                "startup_delay_seconds",
                launcher_cfg.get("startup_delay_seconds", 5),
            )
        ),
        assignment_summary=assignment_summary,
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
    if "input_dir" not in general or "output_dir" not in general:
        raise ValueError("Base sandbox config must define general.input_dir and general.output_dir")
    if "models" not in (config.get("formulation") or {}):
        raise ValueError("Base sandbox config must define formulation.models")
    if "gages" not in simulation:
        raise ValueError("Base sandbox config must define simulation.gages")


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
    required_files = [ctx.sandbox_config_file, ctx.calib_config_file]
    if ctx.map_config_file is not None:
        required_files.append(ctx.map_config_file)

    for path in required_files:
        if not path.exists():
            raise FileNotFoundError(f"Required launcher file not found: {path}")
    if not ctx.submit_script.exists():
        raise FileNotFoundError(f"SLURM submit script not found: {ctx.submit_script}")
    if ctx.num_workers < 1:
        raise ValueError("num_workers must be greater than or equal to 1")
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


def experiment_dirs(ctx: LauncherContext, model_dir: str) -> tuple[Path, Path]:
    model_output_dir = ctx.output_dir / model_dir
    return model_output_dir / "configs", model_output_dir / ctx.exp_info_dir_name


def generated_config_paths(exp_config_dir: Path, gage_id: str) -> dict[str, Path]:
    gage_dir = exp_config_dir / gage_id
    return {
        "sandbox_main": gage_dir / f"sandbox_config_{gage_id}.yaml",
        "sandbox_validation": gage_dir / f"sandbox_config_{gage_id}_validation.yaml",
        "calib_main": gage_dir / f"calib_config_{gage_id}.yaml",
        "calib_restart": gage_dir / f"calib_config_{gage_id}_restart.yaml",
    }


def generate_config_files_for_gage(
    ctx: LauncherContext,
    formulation_name: str,
    formulation_spec: dict[str, Any],
    model_dir: str,
    gage_id: str,
    exp_config_dir: Path,
    exp_info_dir: Path,
    *,
    dryrun: bool = False,
) -> None:
    sandbox_cfg = copy.deepcopy(ctx.base_sandbox_cfg)
    calib_cfg = copy.deepcopy(ctx.base_calib_cfg)

    sandbox_cfg["general"]["output_dir"] = str(ctx.output_dir / model_dir)
    sandbox_cfg["general"]["gages"] = {
        "option": "ids",
        "ids": [gage_id],
    }
    sandbox_cfg["formulation"]["models"] = formulation_spec["models"]
    if "model_instances" in formulation_spec:
        sandbox_cfg["formulation"]["model_instances"] = copy.deepcopy(
            formulation_spec["model_instances"]
        )
    else:
        sandbox_cfg["formulation"].pop("model_instances", None)
    sandbox_cfg["simulation"]["gages"] = [gage_id]

    paths = generated_config_paths(exp_config_dir, gage_id)

    if dryrun:
        print(
            f"[DRYRUN] Would generate configs for {gage_id} / {formulation_name}: "
            f"{paths['sandbox_main']}"
        )
        return

    paths["sandbox_main"].parent.mkdir(parents=True, exist_ok=True)
    exp_info_dir.mkdir(parents=True, exist_ok=True)

    with paths["sandbox_main"].open("w") as file:
        yaml.safe_dump(sandbox_cfg, file, default_flow_style=False, sort_keys=False)

    sandbox_val_cfg = copy.deepcopy(sandbox_cfg)
    sandbox_val_cfg["simulation"]["task_type"] = "validation"
    with paths["sandbox_validation"].open("w") as file:
        yaml.safe_dump(sandbox_val_cfg, file, default_flow_style=False, sort_keys=False)

    with paths["calib_main"].open("w") as file:
        yaml.safe_dump(calib_cfg, file, default_flow_style=False, sort_keys=False)

    calib_restart_cfg = copy.deepcopy(calib_cfg)
    calib_restart_cfg.setdefault("general", {})["restart"] = True
    with paths["calib_restart"].open("w") as file:
        yaml.safe_dump(calib_restart_cfg, file, default_flow_style=False, sort_keys=False)

    subprocess.run(
        [
            "sandbox",
            "--conf",
            "-i",
            str(paths["sandbox_main"]),
            "-j",
            str(paths["calib_main"]),
        ],
        check=True,
    )


def get_max_iter(exp_config_dir: Path, gage_id: str) -> int:
    calib_file = generated_config_paths(exp_config_dir, gage_id)["calib_main"]
    if not calib_file.exists():
        return 0
    cfg = load_yaml(calib_file)
    return int(cfg["general"]["iterations"])


def read_info_file(exp_info_dir: Path, gage_id: str) -> dict[str, Any] | None:
    info_file = exp_info_dir / f"info_{gage_id}.yml"
    if not info_file.exists():
        return None
    return load_yaml(info_file)


def parse_best_params(path: Path) -> tuple[int, float]:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError(f"Expected at least 3 lines in {path}")

    def value(line: str) -> str:
        return line.split("=", 1)[1].strip() if "=" in line else line.strip()

    return int(float(value(lines[0]))), round(float(value(lines[2])), 3)


def get_current_iteration(exp_info_dir: Path, gage_id: str, *, status: bool = False) -> tuple[int, float]:
    info = read_info_file(exp_info_dir, gage_id)
    if info is None:
        return 0, -999.0

    best_param_files = sorted(
        Path(info["output_dir"]).glob("*_worker/best_params.txt"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not best_param_files:
        if not status:
            print(f"INFO: [{gage_id}] No best_params.txt found; assuming iteration 0")
        return 0, -999.0

    return parse_best_params(best_param_files[0])


def get_num_cpus(exp_info_dir: Path, gage_id: str) -> int:
    info = read_info_file(exp_info_dir, gage_id)
    if info is None:
        return 1
    return int(info.get("num_cpus", 1))


def check_validation_exists(exp_info_dir: Path, gage_id: str, *, status: bool = False) -> bool:
    info = read_info_file(exp_info_dir, gage_id)
    if info is None:
        return False

    output_dir = Path(info["output_dir"])
    validation_files = list(output_dir.glob("*_worker/output_sim_obs/sim_obs_validation.*"))
    if validation_files:
        if not status:
            print(f"INFO: [{gage_id}] Validation output found; skipping validation run.")
        return True
    return False


def run_experiment(
    ctx: LauncherContext,
    model_dir: str,
    gage_id: str,
    job_name: str,
    exp_config_dir: Path,
    exp_info_dir: Path,
    current_iter: int,
    delay_seconds: int,
    *,
    use_slurm: bool,
    dryrun: bool = False,
) -> None:
    paths = generated_config_paths(exp_config_dir, gage_id)
    calib_file = paths["calib_main"] if current_iter == 0 else paths["calib_restart"]
    max_iter = get_max_iter(exp_config_dir, gage_id)
    if max_iter == 0 and current_iter == 0:
        max_iter = 1
    sandbox_file = paths["sandbox_main"] if current_iter < max_iter else paths["sandbox_validation"]

    if check_validation_exists(exp_info_dir, gage_id):
        return

    if use_slurm:
        num_cpus = get_num_cpus(exp_info_dir, gage_id)
        cmd = [
            "sbatch",
            f"--cpus-per-task={num_cpus}",
            f"--ntasks-per-node={num_cpus}",
            f"--job-name={job_name}",
            "--export=ALL,"
            f"SANDBOX_FILE={sandbox_file},"
            f"CALIB_FILE={calib_file},"
            f"START_DELAY={delay_seconds}",
            str(ctx.submit_script),
        ]
        print(f"[{gage_id}] Submitting: {' '.join(cmd)}")
    else:
        cmd = [
            "sandbox",
            "--run",
            "-i",
            str(sandbox_file),
            "-j",
            str(calib_file),
        ]
        print(f"[{gage_id}] Running locally: {' '.join(cmd)}")

    if dryrun:
        return

    time.sleep(delay_seconds)
    subprocess.run(cmd, check=True)


def local_worker(args: tuple[Any, ...]) -> None:
    (
        ctx,
        model_dir,
        gage_id,
        job_name,
        exp_config_dir,
        exp_info_dir,
        current_iter,
        delay_seconds,
        dryrun,
    ) = args
    run_experiment(
        ctx,
        model_dir,
        gage_id,
        job_name,
        exp_config_dir,
        exp_info_dir,
        current_iter,
        delay_seconds,
        use_slurm=False,
        dryrun=dryrun,
    )


def check_status(ctx: LauncherContext) -> None:
    print("\n============================ STATUS REPORT ==============================")
    header = f"{'Gage':<12} {'Formulation':<24} {'Calib (cur|max|obj)':<24} {'Validation':<10}"
    print(header)
    print("-" * len(header))

    for gage_id in ctx.map_cfg["mapping"]:
        for formulation_name, _ in get_formulations_for_gage(ctx, gage_id):
            model_dir = model_name_to_dir(formulation_name)
            exp_config_dir, exp_info_dir = experiment_dirs(ctx, model_dir)
            current_iter, obj_value = get_current_iteration(exp_info_dir, gage_id, status=True)
            max_iter = get_max_iter(exp_config_dir, gage_id)
            validation_exists = check_validation_exists(exp_info_dir, gage_id, status=True)
            valid_flag = "YES" if validation_exists else "NO"
            status_text = f"{current_iter} | {max_iter} | {obj_value}"
            print(f"{gage_id:<12} {formulation_name:<24} {status_text:<24} {valid_flag:<10}")

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


def is_experiment_complete(ctx: LauncherContext, gage_id: str, model_dir: str) -> bool:
    exp_config_dir, exp_info_dir = experiment_dirs(ctx, model_dir)
    current_iter, _ = get_current_iteration(exp_info_dir, gage_id, status=True)
    max_iter = get_max_iter(exp_config_dir, gage_id)
    validation_exists = check_validation_exists(exp_info_dir, gage_id, status=True)
    return current_iter >= max_iter and validation_exists


def get_running_slurm_jobs() -> set[str]:
    user = getpass.getuser()
    cmd = ["squeue", "-u", user, "-h", "-o", "%j", "-t", "R,PD"]
    try:
        output = subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as error:
        print("Error fetching Slurm jobs:", error)
        return set()
    return {line.strip() for line in output.splitlines() if line.strip()}


def runner(ctx: LauncherContext, *, use_slurm: bool, dryrun: bool = False) -> None:
    incomplete_exists = False
    running_jobs = get_running_slurm_jobs() if use_slurm and not dryrun else set()
    local_jobs: list[tuple[Any, ...]] = []

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
            job_name = f"{model_dir}_{gage_id}"
            exp_config_dir, exp_info_dir = experiment_dirs(ctx, model_dir)

            if is_experiment_complete(ctx, gage_id, model_dir):
                print(f"[{gage_id}] Experiment '{job_name}' already completed. Skipping.")
                continue

            if job_name in running_jobs:
                print(f"[{gage_id}] Job '{job_name}' is already running or pending. Skipping.")
                continue

            current_iter, _ = get_current_iteration(exp_info_dir, gage_id)
            if current_iter == 0:
                print(f"[{gage_id}] Setup step; generating configs.")
                generate_config_files_for_gage(
                    ctx,
                    formulation_name,
                    formulation_spec,
                    model_dir,
                    gage_id,
                    exp_config_dir,
                    exp_info_dir,
                    dryrun=dryrun,
                )

            incomplete_exists = True
            delay_seconds = index * ctx.startup_delay_seconds

            if use_slurm:
                run_experiment(
                    ctx,
                    model_dir,
                    gage_id,
                    job_name,
                    exp_config_dir,
                    exp_info_dir,
                    current_iter,
                    delay_seconds,
                    use_slurm=True,
                    dryrun=dryrun,
                )
            elif dryrun:
                run_experiment(
                    ctx,
                    model_dir,
                    gage_id,
                    job_name,
                    exp_config_dir,
                    exp_info_dir,
                    current_iter,
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
                        exp_info_dir,
                        current_iter,
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
    print(f"Calib config    : {ctx.calib_config_file}")
    print(f"Mapping config  : {ctx.map_config_file or 'resolved from launcher_config.yaml'}")
    print(f"Submit script   : {ctx.submit_script}")
    print(f"Input dir       : {ctx.input_dir}")
    print(f"Output dir      : {ctx.output_dir}")
    print(f"Num workers     : {ctx.num_workers}")
    print(f"Mapped gages    : {len(ctx.map_cfg['mapping'])}")
    print(f"Formulations    : {len(ctx.map_cfg['formulations'])}")
    if ctx.assignment_summary:
        print("\nResolved assignment summary")
        print("---------------------------")
        for group, counts in ctx.assignment_summary.items():
            print(
                f"{group}: {counts['gages']} gage(s) x "
                f"{counts['experiments']} experiment(s)"
            )
    print("Launcher configuration looks valid.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or inspect Sandbox Launcher jobs.")
    parser.add_argument(
        "mode",
        choices=["run", "status", "check"],
        help="Run experiments, show status, or validate launcher inputs.",
    )
    parser.add_argument(
        "--backend",
        choices=["slurm", "local"],
        default="slurm",
        help="Execution backend for run mode.",
    )
    parser.add_argument(
        "--config",
        default="launcher_config.yaml",
        help="Path to launcher_config.yaml. Defaults to tools/launcher/launcher_config.yaml.",
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Print planned work without writing configs or submitting jobs.",
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

    runner(ctx, use_slurm=args.backend == "slurm", dryrun=args.dryrun)


if __name__ == "__main__":
    main()
