import subprocess
import os, sys
import json
import time
import yaml
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import glob
import numpy as np
import geopandas as gpd
import yaml
import argparse
import getpass
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# ===========================  Inputs ==========================================
base_dir = "/Users/ahmadjankhattak/Core/projects/synthetic_2026"
num_workers = 2  # number of basins running in parallel
#===============================================================================

# DON'T NEED TO MODIFY ANYTHING THING BELOW THIS LINE

sandbox_config_file = f"{base_dir}/launcher/basefiles/sandbox_config_base.yaml"
calib_config_file   = f"{base_dir}/launcher/basefiles/calib_config_base.yaml"
map_config_file     = f"{base_dir}/launcher/models_gages_map.yaml"



# ==============================================================================
# Load configuration files
# ==============================================================================
with open(sandbox_config_file, "r") as f:
    base_sandbox_cfg = yaml.safe_load(f)

output_dir = Path(base_sandbox_cfg["general"]["output_dir"])
input_dir  = Path(base_sandbox_cfg["general"]["input_dir"])


with open(map_config_file) as f:
    map_cfg = yaml.safe_load(f)

formulations = map_cfg["formulations"]
mapping      = map_cfg["mapping"]


# ====================== Moels & Gages Mapper  ======================

def get_models_for_gage(gage_id):
    """
    Return all models for a given gage as a flat list.
    """
    gage_formulations = mapping[gage_id]
    models = []
    for fg in gage_formulations:
        models.extend(formulations[fg])

    return models


def model_name_to_dir(model_name):
    """
    Convert model string to a safe directory name (remove T-route, commas, etc.).
    """
    name = model_name.replace("T-route", "")
    name = name.replace(",", "")
    name = name.strip()
    name = name.replace(" ", "_")
    return name.lower()

# ==================================== ==========================================

# === Generate config per gage ===
def generate_config_files_for_gage(model_name, model_dir, gage_id, exp_config_dir, exp_info_dir):
    """Create sandbox + calibration configs for a single model + single gage."""

    # === Read base YAML once ===
    with open(sandbox_config_file, "r") as f:
        sandbox_config = yaml.safe_load(f)

    with open(calib_config_file, "r") as f:
        calib_config = yaml.safe_load(f)

    sandbox_cfg = sandbox_config.copy()

    sandbox_cfg["general"]["output_dir"]    = str(output_dir / model_dir)
    sandbox_cfg["formulation"]["models"]    = model_name
    sandbox_cfg["simulation"]["gage_ids_input"]   = [gage_id]

    # Create directories
    (exp_config_dir / gage_id).mkdir(parents=True, exist_ok=True)
    exp_info_dir.mkdir(parents=True, exist_ok=True)

    sandbox_main  = exp_config_dir / gage_id / f"sandbox_config_{gage_id}.yaml"
    sandbox_val   = exp_config_dir / gage_id / f"sandbox_config_{gage_id}_validation.yaml"
    calib_main    = exp_config_dir / gage_id / f"calib_config_{gage_id}.yaml"
    calib_restart = exp_config_dir / gage_id / f"calib_config_{gage_id}_restart.yaml"

    # Write sandbox main
    with open(sandbox_main, "w") as f:
        yaml.dump(sandbox_cfg, f, default_flow_style=False, sort_keys=False)

    # Write sandbox validation
    sandbox_val_cfg = sandbox_cfg.copy()
    sandbox_val_cfg["simulation"]["task_type"] = "validation"
    with open(sandbox_val, "w") as f:
        yaml.dump(sandbox_val_cfg, f, default_flow_style=False, sort_keys=False)

    # Write calib main
    with open(calib_main, "w") as f:
        yaml.dump(calib_config, f, default_flow_style=False, sort_keys=False)

    # Write calib restart
    calib_restart_cfg = calib_config.copy()
    calib_restart_cfg["general"]["restart"] = True
    with open(calib_restart, "w") as f:
        yaml.dump(calib_restart_cfg, f, default_flow_style=False, sort_keys=False)
    
    # Run sandbox -conf to generate exp_info.yml
    subprocess.run(["sandbox", "--conf", "-i", sandbox_main, "-j", calib_main])
    

def get_max_iter(exp_config_dir, gage_id):
    """
    Read the calibration config to determine the total number of iterations.
    """
    f = exp_config_dir / gage_id / f"calib_config_{gage_id}.yaml"

    if not f.exists():
        return 0

    with open(f, "r") as fp:
        cfg = yaml.safe_load(fp)

    return cfg["general"]["iterations"]


def get_current_iteration(exp_info_dir, gage_id, status=False):

    info_file = exp_info_dir / f"info_{gage_id}.yml"

    if not info_file.exists():
        return 0, -999

    with open(info_file, 'r') as file:
        d = yaml.safe_load(file)

    iter_file = glob.glob(str(Path(d["output_dir"]) / "*_worker" / "best_params.txt"))

    if not iter_file:
        if not status:
            print(f"INFO: [{gage_id}] No best_params.txt found — assuming iteration 0")
        return 0, -999

    iter_params = pd.read_csv(iter_file[0], header=None)
    current_iter = int(iter_params.values[0].item())
    obj_value = round(float(iter_params.values[2].item()),3)

    return current_iter, obj_value


def get_num_cpus(exp_info_dir, gage_id):
    """
    Extract num_cpus from the info file generated during sandbox -conf.
    """
    info_file = exp_info_dir / f"info_{gage_id}.yml"

    if not info_file.exists():
        return 1

    with open(info_file, "r") as file:
        d = yaml.safe_load(file)

    return int(d["num_cpus"])


def check_validation_exists(exp_info_dir, gage_id, status=False):
    """
    Return True if validation output already exists for this gage.
    """

    info_file = exp_info_dir / f"info_{gage_id}.yml"

    if not info_file.exists():
        return False  # Validation doesn't exist

    with open(info_file, "r") as f:
        d = yaml.safe_load(f)

    # Validation output lives in output_sim_obs/
    validation_file = glob.glob(
        str(Path(d["output_dir"]) / "*_worker" / "output_sim_obs" / "sim_obs_validation.csv")
    )

    if validation_file:
        if not status:
            print(f"INFO: [{gage_id}] Validation output found — skipping validation run.")
        return True

    return False

# ====================== SLURM Submission ======================

def run_experiment(model_name, model_dir, gage_id, job_name, exp_config_dir,
                   exp_info_dir, current_iter, delay_seconds,
                   use_slurm):
    """
    Submit the calibration/validation or restart job.
    """

    sandbox_main  = exp_config_dir / gage_id / f"sandbox_config_{gage_id}.yaml"
    sandbox_val   = exp_config_dir / gage_id / f"sandbox_config_{gage_id}_validation.yaml"

    calib_main    = exp_config_dir / gage_id / f"calib_config_{gage_id}.yaml"
    calib_restart = exp_config_dir / gage_id / f"calib_config_{gage_id}_restart.yaml"

    calib_file    = calib_main if current_iter == 0 else calib_restart

    max_iter      = get_max_iter(exp_config_dir, gage_id)
    sb_cfg_file   = str(sandbox_main) if current_iter < max_iter else str(sandbox_val)

    # # Skip submission if validation already exists — job is fully complete
    if check_validation_exists(exp_info_dir, gage_id):
        return

    time.sleep(delay_seconds)

    if use_slurm:
        num_cpus = get_num_cpus(exp_info_dir, gage_id)

        cmd = [
            "sbatch",
            f"--cpus-per-task={num_cpus}",
            f"--ntasks-per-node={num_cpus}",
            f"--job-name={job_name}",
            "--export=ALL,"
            f"SANDBOX_FILE={sb_cfg_file},"
            f"CALIB_FILE={calib_file},"
            f"START_DELAY={delay_seconds}",
            "launcher/submit_gage.slurm"
        ]

        print(f"[{gage_id}] Submitting: {' '.join(cmd)}")
        subprocess.run(cmd)
    else:
        # ===== LOCAL EXECUTION =====
        cmd = [
            "sandbox",
            "--run",
            "-i", str(sb_cfg_file),
            "-j", str(calib_file)
        ]

        print(f"[{gage_id}] Running locally: {' '.join(cmd)}")
        subprocess.run(cmd)

def local_worker(args):
    """
    Wrapper for local parallel execution.
    """
    (model_name, model_dir, gage_id, job_name,
     exp_config_dir, exp_info_dir,
     current_iter, delay_seconds) = args

    run_experiment(model_name, model_dir, gage_id, job_name,
                   exp_config_dir, exp_info_dir,
                   current_iter, delay_seconds,
                   use_slurm=False)

# ====================== Check Experiments Status ======================
def check_status():
    """
    Print calibration/validation runs status for all gages and all models.
    """

    print("\n============================ STATUS REPORT ==============================")
    #print ("Sumamry:")
    #print (f"Total Gages: {len(mapping.keys())}")
    # Table header
    header = f"{'Gage':<12} {'Formulation':<30} {'Calib (cur|max|obj_val)':<18} {'Validation':<4}"
    print(header)
    print("-" * len(header))
    for gage_id in mapping.keys():
        models_for_gage = get_models_for_gage(gage_id)

        for model_name in models_for_gage:
            model_dir      = model_name_to_dir(model_name)
            exp_info_dir   = output_dir / model_dir / base_sandbox_cfg["sandbox_launcher"]["exp_info_dir"]
            exp_config_dir = output_dir / model_dir / "configs"

            current_iter, obj_value = get_current_iteration(exp_info_dir, gage_id, status=True)
            max_iter     = get_max_iter(exp_config_dir, gage_id)

            validation_exists = check_validation_exists(exp_info_dir, gage_id, status=True)
            valid_flag = "YES" if validation_exists else "NO"
            print(f"{gage_id:<12} {model_name:<30} {f'{current_iter} | {max_iter} | {obj_value}':<25} {valid_flag:<4}")

    print("-" * len(header))
    print("======================== STATUS REPORT COMPLETE =========================")

# For requeue-ing launcher via slrum
def launcher_exit(incomplete_exists):
    # Get wallclock in minutes; must be set in the submit_launcher.slurm
    wallclock_min_str = os.getenv("LAUNCHER_WALLCLOCK_MIN")
    if wallclock_min_str is None:
        raise RuntimeError("Environment variable LAUNCHER_WALLCLOCK_MIN must be set, \
        in the submit_launcher.slurm, before calling launcher_exit.")

    wallclock_min = int(wallclock_min_str)
    buffer = 30 # seconds
    max_runtime_sec = wallclock_min * 60 - buffer

    if incomplete_exists:
        print("[INFO] Incomplete gages/models detected — requesting SLURM requeue.")
        time.sleep(max_runtime_sec)
        sys.exit(99)
    else:
        print("[INFO] All work complete — exiting normally.")
        sys.exit(0)

def is_experiment_complete(gage_id, model_dir):
    """
    Check if a given model/gage experiment has already completed.
    Returns True if current iteration >= max iteration AND validation exists.
    """

    exp_info_dir   = output_dir / model_dir / base_sandbox_cfg["sandbox_launcher"]["exp_info_dir"]
    exp_config_dir = output_dir / model_dir / "configs"

    # Get current and max iterations
    current_iter, _ = get_current_iteration(exp_info_dir, gage_id, status=True)
    max_iter     = get_max_iter(exp_config_dir, gage_id)

    # Check if validation exists
    validation_exists = check_validation_exists(exp_info_dir, gage_id, status=True)

    # Consider experiment complete if all iterations are done AND validation exists
    if current_iter >= max_iter and validation_exists:
        return True
    else:
        return False


def get_running_slurm_jobs():
    """
    Returns a set of job names currently running or pending for the given user.
    """
    user = getpass.getuser()

    cmd = ["squeue", "-u", user, "-h", "-o", "%j", "-t", "R,PD"]
    try:
        output = subprocess.check_output(cmd, text=True)
        job_names = set(line.strip() for line in output.splitlines() if line.strip())
        return job_names
    except subprocess.CalledProcessError as e:
        print("Error fetching Slurm jobs:", e)
        return set()


# ==============================================================================
# Main function loops over all models x all gages
# ==============================================================================
def runner(use_slurm):

    incomplete_exists = False

    # Get all currently running/pending Slurm job names
    running_jobs = get_running_slurm_jobs() if use_slurm else set()

    local_jobs = []
    
    for gage_id in mapping.keys():

        print(f"----------------------------------------------")
        print(f"---------  Processing Gage: {gage_id} ---------")

        models_for_gage = get_models_for_gage(gage_id)

        for m_idx, model_name in enumerate(models_for_gage):

            print(f"\n--- Model {m_idx+1}/{len(models_for_gage)} | {model_name} ---")

            model_dir = model_name_to_dir(model_name)
            job_name = f"{model_dir}_{gage_id}"

            # Skip if job is already complete
            if is_experiment_complete(gage_id, model_dir):
                print(f"[{gage_id}] Experiment '{job_name}' already completed. Skipping...")
                continue

            # Skip if job is already running/pending
            if job_name in running_jobs:
                print(f"[{gage_id}] Job '{job_name}' is already running or pending. Skipping...")
                continue

            exp_info_dir   = output_dir / model_dir / base_sandbox_cfg["sandbox_launcher"]["exp_info_dir"]
            exp_config_dir = output_dir / model_dir / "configs"

            current_iter, _ = get_current_iteration(exp_info_dir, gage_id)
            max_iter        = get_max_iter(exp_config_dir, gage_id)

            if current_iter == 0:
                print(f"[{gage_id}] Setup step (iteration 0) — generating configs...")
                generate_config_files_for_gage(model_name, model_dir, gage_id, exp_config_dir, exp_info_dir)

            # if made it to this point, the experiment needs to be checked for resubmission
            incomplete_exists = True

            # to avoid race for reading .nc forcing file. 5 seconds per mode, adjust as needed
            delay_seconds = m_idx * 5

            if use_slurm:
                run_experiment(model_name, model_dir, gage_id, job_name,
                               exp_config_dir, exp_info_dir,
                               current_iter, delay_seconds,
                               use_slurm=True)
            else:
                local_jobs.append((model_name, model_dir, gage_id, job_name,
                                   exp_config_dir, exp_info_dir,
                                   current_iter, delay_seconds
                                   ))

        print(f"\n--- Finished Model: {model_name} ---\n")


    if not use_slurm and local_jobs:

        max_workers = min(num_workers, multiprocessing.cpu_count())
        print(f"\n[INFO] Running locally with up to {max_workers} parallel workers\n")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(local_worker, job)
                       for job in local_jobs]

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"[ERROR] Local job failed: {e}")
                
    print("\n=== Launcher Finished ===\n")


    # Exit with special code: 99 = request SLURM requeue
    if use_slurm:
        launcher_exit(incomplete_exists)
    else:
        print("[INFO] Local execution finished.")
        sys.exit(0)

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "mode",
        choices=["run", "status"],
        help="Run experiments or show status."
    )

    parser.add_argument(
        "--backend",
        choices=["slurm", "local"],
        default="slurm",
        help="Execution backend (default: slurm)."
    )

    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    print(f"\n=== Sandbox Launcher Started @ {datetime.now()} ===")

    if args.mode == "status":
        check_status()
    else:
        use_slurm = args.backend == "slurm"
        runner(use_slurm)

