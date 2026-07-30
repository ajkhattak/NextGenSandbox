############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ajkhattak@gmail.com
# Date    : July 5, 2024
############################################################################################

import os
import sys
import pandas as pd
import geopandas as gpd
import numpy as np
import subprocess
import glob
import yaml
import platform
import json
from pathlib import Path
import shutil
import re
from datetime import datetime, timezone
from src.python import configuration
from src.python import helper
from src.python.resource_paths import find_gpkg_file, render_gage_path

class Runner:
    def __init__(self, ctx):
        self.ctx = ctx
        self.os_name         = platform.system()

        # Check whether `mpirun` exists on the system; if exists, then it assumes that ngen was built with MPI=ON
        self.mpirun_exists = shutil.which("mpirun") is not None


    def run(self):

        if "LSTM" in self.ctx.formulation:
            print("Running LSTM in NextGen ...")
            self.run_ngen_without_calibration()
            return

        if self.ctx.task_type in ['calibration', 'validation', 'calibvalid', 'restart']:
            print(f'Running NextGen with task_type {self.ctx.task_type}')

            tuple_list = list(zip(
                self.ctx.gage_ids,
                self.ctx.gpkg_dirs,
                self.ctx.output_dirs,
                self.ctx.forcing_files,
                strict=True,
            ))
            #for gage in self.ctx.gage_ids:
            #    self.run_ngen_with_calibration(gage)
            for tpl in tuple_list:
                self.run_ngen_with_calibration(tpl)
        else:
            print("Running NextGen without calibration ...")
            self.run_ngen_without_calibration()



    def run_ngen_without_calibration(self):
        ngen_exe = os.path.join(self.ctx.ngen_dir, "cmake_build/ngen")

        resources = zip(
            self.ctx.gage_ids,
            self.ctx.gpkg_dirs,
            self.ctx.output_dirs,
            strict=True,
        )
        for gage_id, gpkg_resource, o_dir in resources:

            if not os.path.isdir(o_dir):
                raise FileNotFoundError(f"directory {o_dir} does not exist, this dir is created at the config generation step")

            os.chdir(o_dir)

            print("cwd: ", os.getcwd())
            print("input_resource: ", gpkg_resource)
            print("output_dir: ", o_dir)

            gpkg_file = find_gpkg_file(gpkg_resource)

            realization = glob.glob(str(o_dir / "configs" / "realization_*.json"))

            if len(realization) != 1:
                raise RuntimeError(
                    f"Expected exactly one realization file in {o_dir / 'configs'}, "
                    f"found {len(realization)}: {realization}"
                )
            realization = realization[0]

            # defaults to serial run no-mpi mode
            run_cmd = f'{ngen_exe} {gpkg_file} all {gpkg_file} all {realization}'

            partitioning = self.ctx.sandbox_config.get("simulation", {}).get("partitioning", {})
            file_par, num_cpus = helper.prepare_basin_partitioning(self.ctx.sandbox_dir, gpkg_file,
                                                                   partitioning)

            self.file_par = os.path.join(o_dir, file_par) if file_par else None
            self.num_procs = int(num_cpus)

            if self.mpirun_exists and self.num_procs > 1:
                # Use MPI only when the partitioning request needs multiple processes.

                run_cmd = (
                    f"mpirun -np {self.num_procs} "
                    f"{ngen_exe} {gpkg_file} all {gpkg_file} all {realization}"
                    f" {self.file_par}"
                )

            if self.os_name == "Darwin":
                run_cmd = f'PYTHONEXECUTABLE=$(which python) {run_cmd}'

            if not self.ctx.dryrun:
                print(f"Running basin {gage_id} on cores {self.num_procs} ********", flush=True)
                print(f"Run command: {run_cmd}", flush=True)
                result = subprocess.run(run_cmd, shell=True)
                if result.returncode != 0:
                    raise RuntimeError(
                        f"NextGen run failed for gage {gage_id} with exit code "
                        f"{result.returncode}."
                    )
            else:
                print(f"Dry run command: {run_cmd}")


    def run_ngen_with_calibration(self, dirs):
        id = dirs[0]
        i_dir = dirs[1]
        o_dir = dirs[2]

        if not os.path.isdir(o_dir):
            raise FileNotFoundError(f"directory {o_dir} does not exist, this dir is created at the config generation step")

        os.chdir(o_dir)

        print("cwd: ", os.getcwd())
        print("input_dir: ", i_dir)
        print("output_dir: ", o_dir)

        gpkg_file = find_gpkg_file(i_dir)
        gpkg_name = gpkg_file.stem

        partitioning = self.ctx.sandbox_config.get("simulation", {}).get("partitioning", {})
        file_par, num_cpus = helper.prepare_basin_partitioning(self.ctx.sandbox_dir, gpkg_file,
                                                               partitioning)

        self.file_par = os.path.join(o_dir, file_par) if file_par else None

        self.num_procs = int(num_cpus)

        self.validate_configs(o_dir)

        print(f"Running basin {id} on cores {self.num_procs} ********", flush=True)

        if self.ctx.task_type in ['calibration', 'calibvalid', 'restart']:
            mode = 'calibration' if self.ctx.task_type == 'calibvalid' else self.ctx.task_type
            self.run_ngen_experiment(mode, gpkg_file, o_dir, self.file_par, id)

            if self.ctx.dryrun and self.ctx.task_type == 'calibvalid':
                print(
                    "Dry run: skipping validation because calibration state "
                    "was not generated."
                )
                return

        if self.ctx.task_type in ['validation', 'calibvalid']:
            for validation_period in self.validation_periods():
                self.run_ngen_experiment(
                    'validation',
                    gpkg_file,
                    o_dir,
                    self.file_par,
                    id,
                    validation_period=validation_period,
                )


    def run_ngen_experiment(
        self,
        mode,
        gpkg_file,
        o_dir,
        file_par,
        id,
        validation_period=None,
    ):
        """
        ngen_cal_type (mode): 'calibration', 'restart', or 'validation'
        """

        if mode in ['calibration', 'restart']:
            sim_time = self.ctx.simulation_time
            eval_time = self.ctx.calib_eval_time
            start_time = pd.Timestamp(sim_time['start_time']).strftime("%Y%m%d%H%M")
            restart_dir = str(render_gage_path(self.ctx.restart_dir, id))
            ngen_cal_type = mode

        elif mode == 'validation':
            validation_period = validation_period or self.validation_periods()[0]
            sim_time = validation_period["simulation_time"]
            eval_time = validation_period["evaluation_time"]
            start_time = pd.Timestamp(sim_time['start_time']).strftime("%Y%m%d%H%M")
            restart_dir = self.ctx.restart_dir
            ngen_cal_type = 'validation'

        else:
            raise ValueError(f"Unsupported mode (ngen_cal_type): {mode}")

        troute_output_file = os.path.join(f"./troute_output_{start_time}.nc")


        ConfigGen = configuration.ConfigurationCalib(
            ctx = self.ctx,
            gpkg_file            = gpkg_file,
            output_dir           = o_dir,
            realization_file_par = file_par,
            troute_output_file   = troute_output_file,
            simulation_time      = sim_time,
            evaluation_time      = eval_time,
            num_procs            = self.num_procs,
            ngen_cal_type        = ngen_cal_type
        )

        ConfigGen.write_calib_input_files()

        validation_name = None
        if mode == "validation":
            validation_name = validation_period.get("name", "validation")
            config_file = self.copy_named_validation_config(validation_name)
        elif mode in ["calibration", "restart"]:
            config_file = Path("configs/ngen-cal_calib_config.yaml")
        else:
            raise ValueError(f"Unsupported mode (ngen_cal_type): {mode}")

        # Run command
        if mode in ['calibration', 'restart']:
            run_command = f"{sys.executable} -m ngen.cal {config_file}"

        elif mode == 'validation':
            run_command = (
                f"{sys.executable} {self.ctx.sandbox_dir}/src/python/validation.py "
                f"-config {config_file}"
            )

            if self.ctx.ensemble_enabled:
                run_command += " -routing configs/troute_config.yaml"

        before_workers = self.worker_dirs(o_dir)
        if not self.ctx.dryrun:
            result = subprocess.run(run_command, shell=True)
            after_workers = self.worker_dirs(o_dir)
            self.write_run_index(
                output_dir=o_dir,
                gage_id=id,
                mode=mode,
                name=validation_name or mode,
                config_file=config_file,
                command=run_command,
                simulation_time=sim_time,
                evaluation_time=eval_time,
                worker_dirs=after_workers - before_workers,
                returncode=result.returncode,
                status="completed" if result.returncode == 0 else "failed",
            )
            if result.returncode != 0:
                raise RuntimeError(f"{mode.capitalize()} step failed...")
        else:
            print(f"Dry run command: {run_command}")
            self.write_run_index(
                output_dir=o_dir,
                gage_id=id,
                mode=mode,
                name=validation_name or mode,
                config_file=config_file,
                command=run_command,
                simulation_time=sim_time,
                evaluation_time=eval_time,
                worker_dirs=[],
                returncode=None,
                status="dryrun",
            )

    def validation_periods(self):
        periods = getattr(self.ctx, "validation_periods", None)
        if periods:
            return periods
        return [
            {
                "name": "validation",
                "simulation_time": self.ctx.validation_time,
                "evaluation_time": self.ctx.valid_eval_time,
            }
        ]

    def copy_named_validation_config(self, validation_name):
        config_dir = Path("configs")
        source = config_dir / "ngen-cal_valid_config.yaml"
        safe_name = self.safe_filename(validation_name)
        target = config_dir / f"ngen-cal_valid_config_{safe_name}.yaml"
        shutil.copy2(source, target)
        return target

    @staticmethod
    def safe_filename(value):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
        return safe.strip("._") or "validation"

    @staticmethod
    def worker_dirs(output_dir):
        return {
            path.resolve()
            for path in Path(output_dir).glob("*_worker")
            if path.is_dir()
        }

    def write_run_index(
        self,
        output_dir,
        gage_id,
        mode,
        name,
        config_file,
        command,
        simulation_time,
        evaluation_time,
        worker_dirs,
        returncode,
        status,
    ):
        index_file = Path(output_dir) / "run_index.yml"
        if index_file.exists():
            index = yaml.safe_load(index_file.read_text()) or {}
        else:
            index = {}

        runs = index.setdefault("runs", [])
        runs.append(
            {
                "gage_id": str(gage_id),
                "task_type": mode,
                "name": str(name),
                "status": status,
                "returncode": returncode,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "config_file": str(config_file),
                "worker_dirs": [
                    str(path)
                    for path in sorted(worker_dirs)
                ],
                "simulation_time": simulation_time,
                "evaluation_time": evaluation_time,
                "command": command,
            }
        )

        with index_file.open("w") as file:
            yaml.safe_dump(index, file, default_flow_style=False, sort_keys=False)

    def validate_configs(self, output_dir):
            
        for model_name, instances in self.ctx.model_registry.items():
            
            if model_name in {"T-ROUTE"} or model_name == "SLOTH":
                continue

            for instance in instances:

                model_dir = Path(output_dir) / "configs" / instance.name
                
                if (not model_dir.exists()):
                    raise FileNotFoundError(model_dir)
