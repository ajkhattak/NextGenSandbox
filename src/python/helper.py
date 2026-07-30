import os
import sys
import shutil
import importlib.util
import numpy as np
import subprocess
import geopandas as gpd
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
    config_dir = output_dir / "configs"

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


def prepare_basin_partitioning(sandbox_dir, gpkg_file, partitioning, create_par_file=True):

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

    fpar = os.path.join("configs", f"partitions_{num_cpus}.json")

    subprocess.run([
        sys.executable,
        f"{sandbox_dir}/utils/python/local_only_partitions.py",
        gpkg_file,
        str(num_cpus),
        os.path.join(os.getcwd(), "configs")
    ], check=True)

    return fpar, num_cpus
