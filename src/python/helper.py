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

def create_clean_dirs(output_dir,
                      task_type,
                      clean = ["none"]):
    
    if (clean == ["all"]):
        subdirs  = os.listdir(output_dir)
        for d in subdirs:
            if (d != "data"):
                try:
                    shutil.rmtree(d)
                except:
                    os.remove(d)
    elif (clean == ["existing"]):
        subdirs  = os.listdir(output_dir)
        for d in subdirs:
            if (d in ["configs", "outputs"]):
                try:
                    shutil.rmtree(d)
                except:
                    os.remove(d)
    elif (len(clean) >= 1 and clean != ["none"]):
        subdirs  = os.listdir(output_dir)
        for d in subdirs:
            if (d in clean):
                try:
                    shutil.rmtree(d)
                except:
                    os.remove(d)

   
    subdirs  = os.listdir(output_dir)

    for d in subdirs:
        if (d in ["configs", "outputs"]):
            try:
                shutil.rmtree(d)
            except:
                os.remove(d)

    os.mkdir("configs")
    if task_type == 'control':
        os.makedirs("outputs/div")
        os.makedirs("outputs/troute")
        #os.makedirs("outputs/troute_parq")
    
    if (os.path.isdir("dem")):
        shutil.rmtree("dem")


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
