############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
# Date    : July 16, 2024
############################################################################################

import os
import sys
import subprocess
import argparse
import tempfile
import yaml
from pathlib import Path
import sandbox
import platform


from src.python import forcing, driver, runner
from src.python.context import SandboxContext
from src.python.formulations_registry import get_supported_formulations

sandbox_dir = Path(sandbox.__file__).resolve().parent
sys.path.insert(0, str(sandbox_dir))


def check_required_env_vars():

    required_vars = [
        "SANDBOX_DIR",
        "SANDBOX_BUILD_DIR",
        "SANDBOX_DATA_DIR",
        "NGEN_DIR",
        "SANDBOX_ENV",
        "FORCING_ENV",
    ]

    missing = [
        var
        for var in required_vars
        if not os.environ.get(var)
    ]

    if missing:

        print("")
        print("Error: Required sandbox environment variables are not defined:")
        print("")

        for var in missing:
            print(f"{var}")

        print("")
        print("Please source the sandbox environment before running:")
        print("")
        print("  source utils/sandbox_env.sh or ./boostrap.sh --env")
        print("")

        sys.exit(1)


def configure_runtime_environment():
    check_required_env_vars()

    sandbox_build_dir = Path(os.environ["SANDBOX_BUILD_DIR"])

    # Only configure R environment on HPC (Linux)
    if platform.system() == "Linux":
        venv_subset = sandbox_build_dir / "rvenv" / "venv_subset"
        rscript = venv_subset / "bin" / "Rscript"

        os.environ["R_LIBS_USER"] = str(venv_subset / "lib" / "R" / "library")
        os.environ["PROJ_LIB"] = str(venv_subset / "share" / "proj")
        os.environ["PATH"] = f"{venv_subset}/bin:" + os.environ.get("PATH", "")

    else:
        # macOS / local development
        rscript = Path("Rscript")  # assume system R

    return sandbox_build_dir, rscript


def check_sandbox_venv(sandbox_build_dir):
    SANDBOX_ENV = Path(os.environ.get("SANDBOX_ENV"))
    
    # Check if the virtual environment exists
    if not SANDBOX_ENV.exists():
        print(f"Error: NextGen virtual environment {SANDBOX_ENV} not found under directory: {sandbox_build_dir}/venv")
        sys.exit(1)

    # Detect active Python environment
    VENV_ACTIVE  = Path(sys.prefix)
    CONDA_ACTIVE = os.environ.get("CONDA_PREFIX")

    # Resolve paths to handle symlinks
    expected = SANDBOX_ENV.resolve()
    active   = VENV_ACTIVE.resolve()
    conda_active = Path(CONDA_ACTIVE).resolve() if CONDA_ACTIVE else None

    # Check if either venv or conda env matches
    if not (active.samefile(expected) or (conda_active and conda_active.samefile(expected))):
        print("Error: sandbox is not running in the expected Python virtual environment.")
        print(f"Expected: {SANDBOX_ENV}")
        print(f"Active sys.prefix: {VENV_ACTIVE}")
        if CONDA_ACTIVE:
            print(f"Active CONDA_PREFIX: {CONDA_ACTIVE}")
        sys.exit(1)


def Sandbox(args, sandbox_config, calib_config, rscript, dryrun=False):
    
    if (args.subset):
        print ("Generating geopackages...", flush=True)

        try:
            subprocess.run(
                [
                    str(rscript),
                    str(sandbox_dir / "src/R/main.R"),
                    str(sandbox_config),
                    str(sandbox_dir),
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            if exc.returncode == 2:
                sys.exit(
                    "Subsetting setup/configuration failed. "
                    "See the R error output above for the configuration issue."
                )
            if exc.returncode == 3:
                sys.exit(
                    "Subsetting failed for one or more gages/resources. "
                    "See the R error output above and "
                    "<input_dir>/failed_gages/<gage_id>/subsetting_error.txt "
                    "for gage/resource-specific details."
                )
            sys.exit(
                "Failed during geopackage generation/subsetting step. "
                f"R exited with status {exc.returncode}. "
                "See the R error output above for details."
            )
        print("NextGenSandbox subset step completed successfully.")

    if (args.forc):
        print ("Generating forcing data...")
        process_forcing = forcing.ForcingProcessor(sandbox_dir, sandbox_config)
        status          = process_forcing.download_forcing()

        if (status):
            sys.exit("Failed during downloading forcing data step...")
        else:
            print("NextGenSandbox forcing step completed successfully.")

    if not (args.conf or args.run):
        print ("**********************************")
        return

    mode = "conf" if args.conf else "run"

    ctx = SandboxContext(
        sandbox_dir=Path(sandbox_dir),
        sandbox_config_path=sandbox_config,
        calib_config_path=calib_config,
        dryrun=dryrun,
        mode=mode
    )

    ctx.initialize()
    
    if (args.conf):
        print ("Generating config files...")
        status = driver.Driver(ctx).run()

        if (status):
            sys.exit("Failed during generating config files step...")
        else:
            print("NextGenSandbox configuration step completed successfully.")
    
    if (args.run):
        print ("Running NextGen simulations...")

        status = runner.Runner(ctx).run()
        #status  = _runner.run()

        if (status):
            sys.exit("Failed during ngen-cal execution...")
        else:
            print("NextGenSandbox run step completed successfully.")
    
    print ("**********************************")
    

def write_gage_override_config(
    sandbox_config,
    gage_id,
    *,
    subset=False,
    forc=False,
    conf=False,
    run=False,
):
    with open(sandbox_config, "r") as file:
        config = yaml.safe_load(file)

    selected_steps = [
        name
        for name, enabled in {
            "subset": subset,
            "forc": forc,
            "conf": conf,
            "run": run,
        }.items()
        if enabled
    ]
    if len(selected_steps) != 1:
        raise ValueError("--gage can be used with exactly one workflow step")

    step = selected_steps[0]
    if step == "subset":
        config.setdefault("subsetting", {})["gages"] = gage_id
    elif step == "forc":
        config.setdefault("forcings", {})["gages"] = gage_id
    else:
        config.setdefault("simulation", {})["gages"] = gage_id

    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        prefix=f"sandbox_{step}_{gage_id}_",
        suffix=".yaml",
        delete=False,
    )
    with temp_file:
        yaml.safe_dump(config, temp_file, default_flow_style=False, sort_keys=False)

    temp_path = Path(temp_file.name)
    return temp_path, temp_path


def main():

    parser = argparse.ArgumentParser(description="NextGenSandbox workflow")
    parser.add_argument("--subset", action='store_true',    help="Subset basin")
    parser.add_argument("--forc",   action='store_true',    help="Download forcing data")
    parser.add_argument("--conf",   action='store_true',    help="Generate config files")
    parser.add_argument("--run",    action='store_true',    help="Run NextGen simulations")
    parser.add_argument("-i",       dest="sandbox_infile",  type=str, required=False, metavar="FILE", help="sandbox config file")
    parser.add_argument("-j",       dest="calib_infile",    type=str, required=False, metavar="FILE", help="caliberation config file")
    parser.add_argument("--gage",   dest="gage_id",         type=str, required=False, help="Run selected workflow step for one gage ID")

    parser.add_argument("--dryrun", action="store_true",         help="caliberation config file")
    parser.add_argument("--formulations", action="store_true", help="List supported formulations and exit")
    
    args = parser.parse_args()

    if args.formulations:
        print("Formulations supported:\n")
        print("\n".join(get_supported_formulations()))
        print(
            "\n[INFO]: Formulations that omit T-ROUTE are allowed "
            "(e.g., NOM, CFE). All formulation components must be "
            "specified exactly as supported."
        )
        sys.exit(0)


    if (args.sandbox_infile):
        if (os.path.exists(args.sandbox_infile)):
            sandbox_config = Path(args.sandbox_infile).resolve()
        else:
            print ("sandbox config file DOES NOT EXIST, provided: ", args.sandbox_infile)
            sys.exit(0)
    else:
        sandbox_config = f"{sandbox_dir}/configs/sandbox_config.yaml"

    if (args.calib_infile):
        if (os.path.exists(args.calib_infile)):
            calib_config = Path(args.calib_infile).resolve()
        else:
            print ("caliberation config file DOES NOT EXIST, provided: ", args.calib_infile)
            sys.exit(0)
    else:
        calib_config = f"{sandbox_dir}/configs/calib_config.yaml"

    temp_config = None
    if args.gage_id:
        sandbox_config, temp_config = write_gage_override_config(
            sandbox_config,
            args.gage_id,
            subset=args.subset,
            forc=args.forc,
            conf=args.conf,
            run=args.run,
        )

    if (len(sys.argv) < 2):
        print ("No arguments are provide")
        sys.exit(0)

    sandbox_build_dir, rscript = configure_runtime_environment()

    # check if expected Python virtual env exists and activated
    check_sandbox_venv(sandbox_build_dir)

    try:
        Sandbox(args, sandbox_config, calib_config, rscript, args.dryrun)
    finally:
        if temp_config:
            temp_config.unlink(missing_ok=True)
