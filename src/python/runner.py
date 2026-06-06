############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
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
from src.python import configuration
from src.python import helper

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

            tuple_list = list(zip(self.ctx.gage_ids, self.ctx.gpkg_dirs, self.ctx.output_dirs, self.ctx.forcing_files))
            #for gage in self.ctx.gage_ids:
            #    self.run_ngen_with_calibration(gage)
            for tpl in tuple_list:
                self.run_ngen_with_calibration(tpl)
        else:
            print("Running NextGen without calibration ...")
            self.run_ngen_without_calibration()



    def run_ngen_without_calibration(self):
        ngen_exe = os.path.join(self.ctx.ngen_dir, "cmake_build/ngen")


        for id in self.ctx.gage_ids:

            o_dir = self.ctx.output_dir / id
            if self.ctx.sim_name_suffix:
                o_dir = self.ctx.output_dir / f"{id}_{self.ctx.sim_name_suffix}"

            i_dir = Path(self.ctx.input_dir) / id

            if not os.path.isdir(o_dir):
                raise FileNotFoundError(f"directory {o_dir} does not exist, this dir is created at the config generation step")

            os.chdir(o_dir)

            print("cwd: ", os.getcwd())
            print("input_dir: ", i_dir)
            print("output_dir: ", o_dir)

            gpkg_file = Path(glob.glob(str(i_dir / "data" / "*.gpkg"))[0])
            gpkg_name = gpkg_file.stem

            realization = glob.glob(str(o_dir / "configs" / "realization_*.json"))

            assert len(realization) == 1
            realization = realization[0]

            # defaults to serial run no-mpi mode
            run_cmd = f'{ngen_exe} {gpkg_file} all {gpkg_file} all {realization}'

            file_par, num_cpus = helper.prepare_basin_partitioning(self.ctx.sandbox_dir, gpkg_file,
                                                                   self.ctx.sandbox_config["simulation"]['partitioning'])

            self.file_par = os.path.join(o_dir, file_par) if file_par else None
            self.num_procs = int(num_cpus)

            if self.mpirun_exists:
                # mpirun exists so run with MPI

                run_cmd = (
                    f"mpirun -np {self.num_procs} "
                    f"{ngen_exe} {gpkg_file} all {gpkg_file} all {realization}"
                    f"{f' {self.file_par}' if self.num_procs > 1 else ''}"
                )

            if self.os_name == "Darwin":
                run_cmd = f'PYTHONEXECUTABLE=$(which python) {run_cmd}'

            if not self.ctx.dryrun:
                print(f"Running basin {id} on cores {self.num_procs} ********", flush=True)
                print(f"Run command: {run_cmd}", flush=True)
                result = subprocess.call(run_cmd, shell=True)
            else:
                print("Dry run: no simulation executed.")


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

        gpkg_file = Path(glob.glob(str(i_dir / "data" / "*.gpkg"))[0])
        gpkg_name = gpkg_file.stem

        file_par, num_cpus = helper.prepare_basin_partitioning(self.ctx.sandbox_dir, gpkg_file,
                                                               self.ctx.sandbox_config["simulation"]['partitioning'])

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
            self.run_ngen_experiment('validation', gpkg_file, o_dir, self.file_par, id)


    def run_ngen_experiment(self, mode, gpkg_file, o_dir, file_par, id):
        """
        ngen_cal_type (mode): 'calibration', 'restart', or 'validation'
        """

        if mode in ['calibration', 'restart']:
            sim_time = self.ctx.simulation_time
            eval_time = self.ctx.calib_eval_time
            start_time = pd.Timestamp(sim_time['start_time']).strftime("%Y%m%d%H%M")
            restart_dir = self.ctx.restart_dir.replace("{*}", id)
            ngen_cal_type = mode

        elif mode == 'validation':
            sim_time = self.ctx.validation_time
            eval_time = self.ctx.valid_eval_time
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


        # Run command
        if mode in ['calibration', 'restart']:
            run_command = f"{sys.executable} -m ngen.cal configs/ngen-cal_calib_config.yaml"

        elif mode == 'validation':
            run_command = (
                f"{sys.executable} {self.ctx.sandbox_dir}/src/python/validation.py "
                f"-config configs/ngen-cal_valid_config.yaml"
            )

            if self.ctx.ensemble_enabled:
                run_command += " -routing configs/troute_config.yaml"

        if not self.ctx.dryrun:
            result = subprocess.run(run_command, shell=True)
            if result.returncode != 0:
                raise RuntimeError(f"{mode.capitalize()} step failed...")
        else:
            print(f"Dry run command: {run_command}")

    def validate_configs(self, output_dir):
            
        for model_name, instances in self.ctx.model_registry.items():
            
            if model_name in {"T-ROUTE"} or model_name == "SLOTH":
                continue

            for instance in instances:

                model_dir = Path(output_dir) / "configs" / instance.name
                
                if (not model_dir.exists()):
                    raise FileNotFoundError(model_dir)
