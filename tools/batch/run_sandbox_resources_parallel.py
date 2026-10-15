#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.python.gages import load_general_gages, resolve_step_gages


STEP_BLOCK = {
    "subset": "subsetting",
    "forc": "forcings",
}

STATUS_BLOCK = {
    "subset": "subset",
    "forc": "forcing",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run independent Sandbox subset or forcing jobs in parallel, "
            "one serial sandbox command per gage."
        ),
        epilog=(
            "Examples:\n"
            "  Local/macOS terminal:\n"
            "    tools/batch/run_sandbox_resources_parallel.sh "
            "--step forc --config configs/sandbox_config1.yaml --jobs 2\n"
            "\n"
            "  Slurm submit script:\n"
            "    tools/batch/run_sandbox_resources_parallel.sh "
            "--step forc --config configs/sandbox_config1.yaml "
            "--jobs \"$SLURM_CPUS_PER_TASK\"\n"
            "\n"
            "Notes:\n"
            "  --jobs may be lower than SLURM_CPUS_PER_TASK to throttle "
            "memory, I/O, or remote-data pressure.\n"
            "  --jobs may not exceed SLURM_CPUS_PER_TASK unless "
            "--allow-oversubscribe is set.\n"
            "  Each worker calls sandbox --gage internally; use sandbox "
            "--gage directly to debug one basin."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--step",
        choices=sorted(STEP_BLOCK),
        required=True,
        help="Sandbox workflow step to run.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Sandbox config YAML file.",
    )
    parser.add_argument(
        "--jobs",
        required=True,
        type=int,
        help="Number of gages to run at the same time.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        help="Directory for per-gage logs and success/failure lists.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Skip gages already recorded as successful for this step in "
            "<general.input_dir>/sandbox_status.json."
        ),
    )
    parser.add_argument(
        "--allow-oversubscribe",
        action="store_true",
        help=(
            "Allow --jobs to exceed SLURM_CPUS_PER_TASK when running under "
            "Slurm. Use only when oversubscription is intentional."
        ),
    )
    return parser.parse_args()


def validate_slurm_allocation(jobs: int, allow_oversubscribe: bool) -> None:
    cpus_per_task = os.environ.get("SLURM_CPUS_PER_TASK")
    if not cpus_per_task:
        return

    try:
        allocated_cpus = int(cpus_per_task)
    except ValueError:
        return

    if jobs <= allocated_cpus or allow_oversubscribe:
        return

    raise ValueError(
        f"--jobs {jobs} would run more simultaneous gages than the "
        f"allocated SLURM_CPUS_PER_TASK={allocated_cpus}. "
        "Request more CPUs with #SBATCH --cpus-per-task, lower --jobs, "
        "or pass --allow-oversubscribe."
    )


def load_gages(config_path: Path, step: str) -> list[str]:
    with config_path.open("r") as file:
        config = yaml.safe_load(file)

    project_gages = load_general_gages(config)
    block_name = STEP_BLOCK[step]
    step_block = config.get(block_name) or {}
    return resolve_step_gages(
        project_gages=project_gages,
        step_value=step_block.get("gages"),
        field_name=f"{block_name}.gages",
    )


def duplicate_gages(gages: list[str]) -> list[str]:
    return sorted(gage_id for gage_id, count in Counter(gages).items() if count > 1)


def load_status(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "subset": {}, "forcing": {}}

    with path.open("r") as file:
        status = json.load(file)
    if not isinstance(status, dict):
        raise ValueError(f"Status file must contain a JSON object: {path}")

    status.setdefault("version", 1)
    status.setdefault("subset", {})
    status.setdefault("forcing", {})
    return status


def save_status(path: Path, status: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w") as file:
        json.dump(status, file, indent=2, sort_keys=True)
        file.write("\n")
    os.replace(temporary, path)


def set_gage_status(
    status: dict,
    step: str,
    gage_id: str,
    state: str,
    *,
    returncode: int | None = None,
) -> None:
    record = {
        "status": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if returncode is not None:
        record["returncode"] = returncode
    status[STATUS_BLOCK[step]][gage_id] = record


def pending_gages(
    status: dict,
    step: str,
    gages: list[str],
    resume: bool,
) -> tuple[list[str], list[str]]:
    if not resume:
        return list(gages), []

    step_status = status[STATUS_BLOCK[step]]
    completed = [
        gage_id
        for gage_id in gages
        if (step_status.get(gage_id) or {}).get("status") == "success"
    ]
    completed_set = set(completed)
    pending = [gage_id for gage_id in gages if gage_id not in completed_set]
    return pending, completed


def subset_domain_warning(config: dict, step: str, gage_count: int) -> str | None:
    """Warn when a local-hydrofabric batch will query USGS for every gage."""
    if step != "subset" or gage_count < 2:
        return None

    general = config.get("general") or {}
    hydrofabric = (config.get("subsetting") or {}).get("hydrofabric") or {}
    if general.get("domain") or not hydrofabric.get("gpkg_path"):
        return None

    return (
        "general.domain is not set. Sandbox will query USGS metadata "
        f"separately for all {gage_count} selected gages, which can make "
        "parallel subsetting very slow or appear stalled. Set general.domain "
        "to conus, hi, ak, or prvi when all selected gages share one domain."
    )


def run_one(step: str, config: Path, log_dir: Path, gage_id: str) -> tuple[str, int]:
    out_file = log_dir / f"{step}_{gage_id}.out"
    err_file = log_dir / f"{step}_{gage_id}.err"

    command = [
        "sandbox",
        f"--{step}",
        "-i",
        str(config),
        "--gage",
        gage_id,
    ]

    with out_file.open("w") as stdout, err_file.open("w") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr)

    return gage_id, result.returncode


def main() -> int:
    args = parse_args()

    if not args.config.is_file():
        print(f"--config must point to an existing file: {args.config}", file=sys.stderr)
        return 2
    if args.jobs < 1:
        print("--jobs must be a positive integer", file=sys.stderr)
        return 2
    try:
        validate_slurm_allocation(args.jobs, args.allow_oversubscribe)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not shutil.which("sandbox"):
        print(
            "sandbox command not found. Activate the Sandbox environment first.",
            file=sys.stderr,
        )
        return 2

    config = args.config.resolve()
    try:
        with config.open("r") as file:
            sandbox_config = yaml.safe_load(file)
        gages = load_gages(config, args.step)
    except Exception as exc:
        print(f"Failed to resolve gages from {config}: {exc}", file=sys.stderr)
        return 2

    if not gages:
        print(f"No gages selected for {args.step}", file=sys.stderr)
        return 2

    duplicates = duplicate_gages(gages)
    if duplicates:
        print(
            "Duplicate gage IDs cannot be run in parallel: "
            f"{', '.join(duplicates)}. Remove duplicate entries from the config.",
            file=sys.stderr,
        )
        return 2

    input_dir_value = (sandbox_config.get("general") or {}).get("input_dir")
    if not input_dir_value:
        print("general.input_dir must be provided", file=sys.stderr)
        return 2
    status_file = Path(input_dir_value).expanduser() / "sandbox_status.json"
    try:
        status = load_status(status_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Failed to read {status_file}: {exc}", file=sys.stderr)
        return 2

    run_gages, completed_gages = pending_gages(
        status,
        args.step,
        gages,
        args.resume,
    )

    log_dir = args.log_dir
    if log_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        log_dir = Path("logs") / f"{args.step}_{timestamp}"
    log_dir.mkdir(parents=True, exist_ok=True)

    success_file = log_dir / "success_gages.txt"
    failed_file = log_dir / "failed_gages.txt"
    selected_file = log_dir / "selected_gages.txt"

    success_file.write_text(
        "" if not completed_gages else "\n".join(completed_gages) + "\n"
    )
    failed_file.write_text("")
    selected_file.write_text("\n".join(gages) + "\n")

    total = len(gages)
    jobs = min(args.jobs, len(run_gages)) if run_gages else 0

    warning = subset_domain_warning(sandbox_config, args.step, total)
    if warning:
        print(f"WARNING: {warning}", file=sys.stderr)

    print(f"Selected             : {total}")
    print(f"Previously completed : {len(completed_gages)}")
    print(f"Remaining            : {len(run_gages)}")
    print(f"Config : {config}")
    print(f"Logs   : {log_dir}")
    print(f"Status : {status_file}")

    if not run_gages:
        print(f"All selected gages have completed the {args.step} step.")
        return 0

    print(
        f"Running sandbox --{args.step} with {jobs} parallel job(s)."
    )

    for gage_id in run_gages:
        set_gage_status(status, args.step, gage_id, "pending")
    try:
        save_status(status_file, status)
    except OSError as exc:
        print(f"Failed to write {status_file}: {exc}", file=sys.stderr)
        return 2

    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(run_one, args.step, config, log_dir, gage): gage
            for gage in run_gages
        }
        for future in concurrent.futures.as_completed(futures):
            gage = futures[future]
            try:
                gage_id, returncode = future.result()
            except Exception as exc:
                failed.append(gage)
                set_gage_status(status, args.step, gage, "failed")
                save_status(status_file, status)
                with failed_file.open("a") as file:
                    file.write(f"{gage}\n")
                print(f"FAIL  {args.step} {gage}: {exc}", file=sys.stderr)
                continue

            if returncode == 0:
                set_gage_status(status, args.step, gage_id, "success")
                save_status(status_file, status)
                with success_file.open("a") as file:
                    file.write(f"{gage_id}\n")
                print(f"DONE  {args.step} {gage_id}")
            else:
                failed.append(gage_id)
                set_gage_status(
                    status,
                    args.step,
                    gage_id,
                    "failed",
                    returncode=returncode,
                )
                save_status(status_file, status)
                with failed_file.open("a") as file:
                    file.write(f"{gage_id}\n")
                print(
                    f"FAIL  {args.step} {gage_id}; "
                    f"see {log_dir / f'{args.step}_{gage_id}.out'} and "
                    f"{log_dir / f'{args.step}_{gage_id}.err'}",
                    file=sys.stderr,
                )

    success_count = len(completed_gages) + len(run_gages) - len(failed)
    print("")
    print(f"Completed {args.step} batch.")
    print(f"  Success: {success_count}")
    print(f"  Failed : {len(failed)}")
    print(f"  Logs   : {log_dir}")

    if failed:
        print("Failed gages:")
        for gage in failed:
            print(gage)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
