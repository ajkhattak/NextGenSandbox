import os
import sys
import shutil
import importlib.util
import numpy as np
import subprocess
import geopandas as gpd
import re
import yaml
from datetime import datetime, timezone
from pathlib import Path

# called in driver.py
class colors:
    GREEN = '\033[92m'
    RED   = '\033[91m'
    END   = '\033[0m'


def ensure_troute_available(ngen_dir=None):
    if importlib.util.find_spec("nwm_routing") is not None:
        return

    candidates = []
    if ngen_dir:
        ngen_dir = Path(ngen_dir)
        for rel_path in ["extern/t-route-hf2.2", "extern/t-route"]:
            troute_dir = ngen_dir / rel_path
            if troute_dir.exists():
                candidates.append(troute_dir)

    location_hint = ""
    if candidates:
        joined = "\n".join(f"  - {path}" for path in candidates)
        location_hint = f"\nDetected t-route source directory:\n{joined}\n"

    sandbox_dir = os.environ.get("SANDBOX_DIR", "<sandbox repo>")

    raise ModuleNotFoundError(
        "T-ROUTE routing module `nwm_routing` is not available in the active sandbox environment.\n"
        "This can happen if the sandbox environment was deleted or rebuilt after T-ROUTE was built.\n"
        f"Active Python: {sys.executable}\n"
        f"SANDBOX_ENV: {os.environ.get('SANDBOX_ENV', '<not set>')}\n"
        f"{location_hint}"
        "Rebuild T-ROUTE in the active sandbox environment, for example:\n"
        f"  cd {sandbox_dir}\n"
        "  ./bootstrap.sh --troute\n"
    )

def remove_path(path):
    path = Path(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def validate_gage_output_directory(output_dir, project_output_dir):
    output_dir = Path(output_dir).resolve()
    project_output_dir = Path(project_output_dir).resolve()
    if output_dir == project_output_dir or project_output_dir not in output_dir.parents:
        raise ValueError(
            "Refusing to modify an output path that is not a gage-specific "
            f"directory under {project_output_dir}: {output_dir}"
        )
    return output_dir


def safe_path_name(value):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    return safe.strip("._") or "validation"


def configuration_dir(
    output_dir,
    task_type,
    validation_name=None,
    multiple_validations=False,
):
    task_type = str(task_type).lower()
    if task_type == "calibvalid":
        task_type = "calibration"
    if task_type == "validation":
        config_dir = Path(output_dir) / "configs" / "validation"
        if multiple_validations:
            config_dir /= safe_path_name(validation_name or "validation")
        return config_dir
    return Path(output_dir) / "configs" / task_type


def configuration_manifest_file(config_dir):
    return Path(config_dir) / "configuration_manifest.yml"


def _manifest_path(value):
    return str(Path(value).expanduser().resolve())


def configuration_manifest(
    *,
    task_type,
    gage_id,
    formulation_models,
    simulation_time,
    hydrofabric,
    forcing,
    validation_name=None,
):
    manifest = {
        "schema_version": 1,
        "task_type": str(task_type),
        "gage_id": str(gage_id),
        "formulation_models": list(formulation_models),
        "simulation_time": dict(simulation_time),
        "hydrofabric": _manifest_path(hydrofabric),
        "forcing": _manifest_path(forcing),
    }
    if validation_name is not None:
        manifest["validation_name"] = str(validation_name)
    return manifest


def write_configuration_manifest(config_dir, **values):
    manifest_file = configuration_manifest_file(config_dir)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest = configuration_manifest(**values)
    manifest["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    with manifest_file.open("w") as file:
        yaml.safe_dump(manifest, file, default_flow_style=False, sort_keys=False)
    return manifest_file


def validate_configuration_manifest(config_dir, **expected_values):
    manifest_file = configuration_manifest_file(config_dir)
    if not manifest_file.is_file():
        raise FileNotFoundError(
            f"Generated configuration manifest is missing: {manifest_file}. "
            "Run 'sandbox --conf -i <config>' for the current task before "
            "running NextGen."
        )

    generated = yaml.safe_load(manifest_file.read_text()) or {}
    expected = configuration_manifest(**expected_values)
    mismatches = []
    for key, current in expected.items():
        previous = generated.get(key)
        if previous != current:
            mismatches.append(
                f"  - {key}: generated={previous!r}, current={current!r}"
            )

    if mismatches:
        details = "\n".join(mismatches)
        raise ValueError(
            "Generated configurations do not match the current Sandbox run:\n"
            f"{details}\n"
            "Run 'sandbox --conf -i <config>' after changing task type, time "
            "windows, formulation, hydrofabric, or forcing."
        )
    return manifest_file


def prepare_validation_configuration_output(
    output_dir,
    validation_names,
    *,
    project_output_dir,
    replace_existing=False,
):
    output_dir = validate_gage_output_directory(output_dir, project_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    validation_root = output_dir / "configs" / "validation"
    if replace_existing and validation_root.exists():
        remove_path(validation_root)

    multiple_validations = len(validation_names) > 1
    for name in validation_names:
        config_dir = configuration_dir(
            output_dir,
            "validation",
            validation_name=name,
            multiple_validations=multiple_validations,
        )
        config_dir.mkdir(parents=True, exist_ok=True)


def prepare_configuration_output(
    output_dir,
    task_type,
    *,
    project_output_dir,
    replace_existing=False,
    reset_output=False,
):
    """Prepare one selected gage output directory for configuration generation."""
    output_dir = validate_gage_output_directory(output_dir, project_output_dir)

    if reset_output and output_dir.exists():
        remove_path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    config_dir = configuration_dir(output_dir, task_type)

    if replace_existing and config_dir.exists():
        remove_path(config_dir)

    config_dir.mkdir(parents=True, exist_ok=True)

    if task_type == "control":
        (output_dir / "outputs" / "div").mkdir(parents=True, exist_ok=True)
        (output_dir / "outputs" / "troute").mkdir(parents=True, exist_ok=True)


def replace_run_output(
    output_dir,
    task_type,
    *,
    project_output_dir,
    metadata_file=None,
):
    """Remove run artifacts while preserving generated configuration files."""
    output_dir = validate_gage_output_directory(output_dir, project_output_dir)
    if not output_dir.is_dir():
        raise FileNotFoundError(
            f"Gage output directory does not exist: {output_dir}. "
            "Run sandbox --conf first."
        )

    preserved_names = {"configs"}
    if metadata_file:
        preserved_names.add(str(metadata_file))

    for path in output_dir.iterdir():
        if path.name not in preserved_names:
            remove_path(path)

    if task_type == "control":
        (output_dir / "outputs" / "div").mkdir(parents=True, exist_ok=True)
        (output_dir / "outputs" / "troute").mkdir(parents=True, exist_ok=True)


def prepare_basin_partitioning(
    sandbox_dir,
    gpkg_file,
    partitioning,
    create_par_file=True,
    config_dir=None,
):

    nexus     = gpd.read_file(gpkg_file, layer='nexus')

    par_mode     = partitioning.get("mode", "serial").lower()
    max_nexus_per_proc = int(partitioning.get("max_nexus_per_proc", 20))
    max_procs = int(partitioning.get("max_procs", 1))

    if not par_mode in  ["serial", "parallel"]:
        raise RuntimeError(f"Partitioning mode OPTIONS: serial or parallel, provided {par_mode}")

    if par_mode == "serial":
        return None, 1

    if max_procs <= 1:
        raise RuntimeError(
            f"Parallel mode requires max_procs > 1, got {max_procs}"
        )

    num_cpus = min(max_procs, int(np.ceil(len(nexus) / max_nexus_per_proc)) )

    if not create_par_file:
        return num_cpus

    config_dir = Path(config_dir) if config_dir is not None else Path.cwd() / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    fpar = config_dir / f"partitions_{num_cpus}.json"

    subprocess.run([
        sys.executable,
        f"{sandbox_dir}/utils/python/local_only_partitions.py",
        gpkg_file,
        str(num_cpus),
        str(config_dir)
    ], check=True)

    return str(fpar), num_cpus
