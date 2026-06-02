############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
# Date    : July 16, 2024
############################################################################################

import os
import sys
import subprocess
import argparse
from pathlib import Path
import sandbox
import platform


from src.python import forcing, driver, runner
from src.python.context import SandboxContext

sandbox_dir = Path(sandbox.__file__).resolve().parent
sys.path.insert(0, str(sandbox_dir))


def check_required_env_vars():

    required_vars = [
        "SANDBOX_DIR",
        "SANDBOX_BUILD_DIR",
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


formulations_supported = [
    "NOM,CFE,T-ROUTE",
    "PET,CFE,T-ROUTE",
    "NOM,PET,CFE,T-ROUTE",
    "NOM,TOPMODEL,T-ROUTE",
    "PET,TOPMODEL,T-ROUTE",
    "NOM,CASAM,T-ROUTE",
    "PET,CASAM,T-ROUTE",
    "NOM,CFE,SMP,SFT,T-ROUTE",
    "NOM,PET,TOPMODEL,T-ROUTE",
    "NOM,CASAM,SMP,SFT,T-ROUTE",
    "SNOW17,PET,CFE-S,T-ROUTE",
    "SNOW17,PET,CFE-X,T-ROUTE",
    "SNOW17,PET,TOPMODEL,T-ROUTE",
    "LSTM,T-ROUTE",
    "SNOW17,PET,SACSMA,T-ROUTE",
    "DHBV,T-ROUTE",
]


def Sandbox(args, sandbox_config, calib_config, rscript, dryrun=False):
    
    if (args.subset):
        print ("Generating geopackages...")

        subprocess.run(
            [
                str(rscript),
                str(sandbox_dir / "src/R/main.R"),
                str(sandbox_config),
                str(sandbox_dir),
            ],
            check=True,
        )
        print ("DONE \u2713")

    if (args.forc):
        print ("Generating forcing data...")
        process_forcing = forcing.ForcingProcessor(sandbox_dir, sandbox_config)
        status          = process_forcing.download_forcing()

        if (status):
            sys.exit("Failed during downloading forcing data step...")
        else:
            print ("DONE \u2713")

    mode = "conf" if args.conf else "run"

    ctx = SandboxContext(
        sandbox_dir=Path(sandbox_dir),
        sandbox_config_path=sandbox_config,
        formulations_supported=formulations_supported,
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
            print ("DONE \u2713")
    
    if (args.run):
        print ("Calling Runner...")

        status = runner.Runner(ctx).run()
        #status  = _runner.run()

        if (status):
            sys.exit("Failed during ngen-cal execution...")
        else:
            print ("DONE \u2713")
    
    print ("**********************************")
    

def main():

    parser = argparse.ArgumentParser(description="NextGen SandboxHub workflow")
    parser.add_argument("--subset", action='store_true',    help="Subset basin")
    parser.add_argument("--forc",   action='store_true',    help="Download forcing data")
    parser.add_argument("--conf",   action='store_true',    help="Generate config files")
    parser.add_argument("--run",    action='store_true',    help="Run NextGen simulations")
    parser.add_argument("-i",       dest="sandbox_infile",  type=str, required=False, metavar="FILE", help="sandbox config file")
    parser.add_argument("-j",       dest="calib_infile",    type=str, required=False, metavar="FILE", help="caliberation config file")

    parser.add_argument("--dryrun", action="store_true",         help="caliberation config file")
    parser.add_argument("--formulations", action="store_true", help="List supported formulations and exit")
    
    args = parser.parse_args()

    if args.formulations:
        print("Formulations supported:\n")
        print("\n".join(formulations_supported))
        print(
            "\n[INFO]: Formulations that omit T-ROUTE are allowed "
            "(e.g., NOM, CFE-S). All formulation components must be "
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


    if (len(sys.argv) < 2):
        print ("No arguments are provide")
        sys.exit(0)

    sandbox_build_dir, rscript = configure_runtime_environment()

    # check if expected Python virtual env exists and activated
    check_sandbox_venv(sandbox_build_dir)

    Sandbox(args, sandbox_config, calib_config, rscript, args.dryrun)
