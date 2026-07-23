############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ajkhattak@gmail.com
# Date    : December 11, 2025
############################################################################################
# sandbox unit test

import os, sys
import subprocess
import yaml
import argparse
from pathlib import Path
import sandbox
import shutil

def run_step(label, command):
    print("-------------------------------------")
    print(label)
    subprocess.run(command, shell=True, check=True)

def print_success(message):
    print("-------------------------------------")
    print(message)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--gpkg",  dest="conus_gpkg",  type=str, required=True, metavar="CONUS_GPKG", help="conus .gpkg file")
        parser.add_argument("--subset", action='store_true', help="Subset basin (generate .gpkg files)")
        parser.add_argument("--forc",   action='store_true', help="Download forcing data")
        parser.add_argument("--conf",   action='store_true', help="Generate config files")
        parser.add_argument("--run",    action='store_true', help="Run NextGen simulations")
        parser.add_argument("--all",    action='store_true', help="Run all: subset, forc, conf, run")
        parser.add_argument("--clean",  action='store_true', help="Run all: subset, forc, conf, run")
        args = parser.parse_args()
    except SystemExit:
        sys.exit(0)

    sandbox_test_dir = Path(__file__).resolve().parent

    sandbox_config   = sandbox_test_dir / "configs" / "sandbox_config.yaml"
    original_config = sandbox_config.read_text()

    try:
        d = yaml.safe_load(original_config)

        # modify values
        d["general"]["input_dir"] = str(sandbox_test_dir / "input")
        d["general"]["output_dir"] = str(sandbox_test_dir / "output")
        d["subsetting"]["hydrofabric"]["gpkg_path"] = str(Path(args.conus_gpkg).resolve())

        with open(sandbox_config, "w") as f:
            yaml.safe_dump(d, f, sort_keys=False)

        # test sandbox -conf
        if args.subset:
            run_step("Running subset step", f"sandbox --subset -i {sandbox_config}")
            print_success("SUCCESS: subset smoke-test step completed.")
        elif args.forc:
            run_step("Running forcing step", f"sandbox --forc -i {sandbox_config}")
            print_success("SUCCESS: forcing smoke-test step completed.")
        elif args.conf:
            run_step("Running config generation step", f"sandbox --conf -i {sandbox_config}")
            print_success("SUCCESS: configuration smoke-test step completed.")
        elif args.run:
            run_step("Running test simulation", f"sandbox --run -i {sandbox_config}")
            print_success("SUCCESS: run smoke-test step completed.")

        elif args.all:
            run_step("Running subset step", f"sandbox --subset -i {sandbox_config}")
            run_step("Running forcing step", f"sandbox --forc -i {sandbox_config}")
            run_step("Running config generation step", f"sandbox --conf -i {sandbox_config}")
            run_step("Running test simulation", f"sandbox --run -i {sandbox_config}")
            print_success(
                "SUCCESS: NextGenSandbox smoke test completed. "
                "Installation and the core workflow are ready."
            )

        elif args.clean:
            output_dir = sandbox_test_dir / "output"

            if output_dir.exists():
                print(f"Deleting: {output_dir}")
                shutil.rmtree(output_dir)
                print_success("SUCCESS: smoke-test output directory removed.")
            else:
                print(f"Directory does not exist: {output_dir}")
    finally:
        sandbox_config.write_text(original_config)
