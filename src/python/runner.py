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
    def __init__(self, sandbox_dir, config_workflow, config_calib, dryrun
                 ):
        self.os_name         = platform.system()
        self.sandbox_dir     = Path(sandbox_dir)
        self.config_workflow = config_workflow
        self.config_calib    = config_calib
        self.dryrun          = dryrun

        self.load_configuration()

        # Check whether `mpirun` exists on the system; if exists, then it assumes that ngen was built with MPI=ON
        self.mpirun_exists = shutil.which("mpirun") is not None


    def load_configuration(self):
        with open(self.config_workflow, 'r') as file:
            self.config = yaml.safe_load(file)

        self.input_dir    = self.config['general'].get('input_dir')
        self.output_dir   = Path(self.config['general'].get('output_dir'))

        dformul = self.config['formulation']
        self.ngen_dir     = Path(os.environ.get("NGEN_DIR"))
        self.formulation  = dformul['models'].upper()
        self.model_variants = dformul.get('model_variants', {})
        
        dsim = self.config['simulation']
        self.ngen_cal_type    = dsim.get('task_type', 'control')
        self.calibration_time = pd.NaT
        self.validation_time  = pd.NaT

        if self.ngen_cal_type in ['calibration', 'calibvalid', 'restart']:
            if "calibration_time" not in dsim or not isinstance(dsim["calibration_time"], dict):
                raise ValueError("calibration_time is not provided or is not a valid dictionary.")

            if "calib_eval_time" not in dsim or not isinstance(dsim["calib_eval_time"], dict):
                raise ValueError("calib_eval_time is not provided or is not a valid dictionary.")

            self.calibration_time = dsim["calibration_time"]
            self.calib_eval_time  = dsim["calib_eval_time"]

        if self.ngen_cal_type in ['validation', 'calibvalid']:
            if "calibration_time" not in dsim or not isinstance(dsim["calibration_time"], dict):
                raise ValueError("calibration_time is not provided or is not a valid dictionary.")

            if "calib_eval_time" not in dsim or not isinstance(dsim["calib_eval_time"], dict):
                raise ValueError("calib_eval_time is not provided or is not a valid dictionary.")
            
            self.validation_time = dsim["validation_time"]
            self.valid_eval_time = dsim["valid_eval_time"]

        self.restart_dir = "./"
        if self.ngen_cal_type == 'restart':
            self.restart_dir = dsim.get('restart_dir')
            if self.restart_dir is None:
                raise ValueError("ngen_cal_type is restart, however, restart_dir is None. It must be set to a valid directory.")
            if not self.restart_dir:
                raise FileNotFoundError(f"restart_dir does not exist, provided {self.restart_dir}.")

        # Get gages IDs
        self.gage_ids = self.load_gage_ids(dsim.get("gage_ids_input"))

        suffix = dsim.get('sim_name_suffix')
        if suffix and any(c.isspace() for c in suffix):
            raise ValueError("sim_name_suffix must not contain whitespace")
        self.sim_name_suffix = suffix

        densemble = dformul.get('ensemble') or None
        if (densemble):
            self.ensemble_enabled = bool(densemble.get('enabled'))
            
            if self.ensemble_enabled:
                self.ensemble_models  = self.formulation.replace("T-ROUTE", "").replace(" ,", ",").strip(", ").strip()
                self.ensemble_calib_params_groups = densemble.get('calib_params_groups')
            else:
                self.ensemble_models = []
                self.ensemble_calib_params_groups = {}

        else:
            self.ensemble_enabled = False
            self.ensemble_models  = []
            self.ensemble_calib_params_groups = {}



    def load_gage_ids(self, gage_ids_input):
        if gage_ids_input is None:
            raise TypeError("gage_ids_input must be a CSV path, a string ID, or a list of IDs")

        # Case 1: CSV file path
        if isinstance(gage_ids_input, str) and gage_ids_input.lower().endswith(".csv"):
            path = Path(gage_ids_input)

            if not path.is_file():
                raise FileNotFoundError(f"gage_ids file not found: {path}")

            df = pd.read_csv(path, dtype=str)

            if 'gage_id' not in df.columns:
                raise ValueError("CSV must contain a 'gage_id' column")

            return df['gage_id'].tolist()

        # Case 2: single gage ID as string
        if isinstance(gage_ids_input, str):
            return [gage_ids_input]

        # Case 3: list / tuple / set
        if isinstance(gage_ids_input, (list, tuple, set)):
            return [str(x) for x in gage_ids_input]

        raise TypeError("gage_ids_input must be a CSV path, a string ID, or a list of IDs")

    def run(self):

        if "LSTM" in self.formulation:
            print("Running LSTM in NextGen ...")
            self.run_ngen_without_calibration()
            return

        if self.ngen_cal_type in ['calibration', 'validation', 'calibvalid', 'restart']:
            print(f'Running NextGen with task_type {self.ngen_cal_type}')
            for gage in self.gage_ids:
                self.run_ngen_with_calibration(gage)
        else:
            print("Running NextGen without calibration ...")
            self.run_ngen_without_calibration()



    def run_ngen_without_calibration(self):
        ngen_exe = os.path.join(self.ngen_dir, "cmake_build/ngen")


        for id in self.gage_ids:

            o_dir = self.output_dir / id
            if self.sim_name_suffix:
                o_dir = self.output_dir / f"{id}_{self.sim_name_suffix}"

            i_dir = Path(self.input_dir) / id

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

            file_par, num_cpus = helper.prepare_basin_partitioning(self.sandbox_dir, gpkg_file,
                                                                   self.config["simulation"]['partitioning'])

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

            if not self.dryrun:
                print(f"Running basin {id} on cores {self.num_procs} ********", flush=True)
                print(f"Run command: {run_cmd}", flush=True)
                result = subprocess.call(run_cmd, shell=True)
            else:
                print("Dry run: no simulation executed.")


    def run_ngen_with_calibration(self, gage):
        id = gage

        o_dir = self.output_dir / id

        if self.sim_name_suffix:
            o_dir = self.output_dir / f"{id}_{self.sim_name_suffix}"

        i_dir = Path(self.input_dir) / id

        if not os.path.isdir(o_dir):
            raise FileNotFoundError(f"directory {o_dir} does not exist, this dir is created at the config generation step")

        os.chdir(o_dir)

        print("cwd: ", os.getcwd())
        print("input_dir: ", i_dir)
        print("output_dir: ", o_dir)

        gpkg_file = Path(glob.glob(str(i_dir / "data" / "*.gpkg"))[0])
        gpkg_name = gpkg_file.stem

        file_par, num_cpus = helper.prepare_basin_partitioning(self.sandbox_dir, gpkg_file,
                                                               self.config["simulation"]['partitioning'])

        self.file_par = os.path.join(o_dir, file_par) if file_par else None

        self.num_procs = int(num_cpus)

        print(f"Running basin {id} on cores {self.num_procs} ********", flush=True)

        if self.ngen_cal_type in ['calibration', 'calibvalid', 'restart']:
            mode = 'calibration' if self.ngen_cal_type == 'calibvalid' else self.ngen_cal_type
            self.run_ngen_experiment(mode, gpkg_file, o_dir, self.file_par, id)

        if self.ngen_cal_type in ['validation', 'calibvalid']:
            self.run_ngen_experiment('validation', gpkg_file, o_dir, self.file_par, id)


    def run_ngen_experiment(self, mode, gpkg_file, o_dir, file_par, id):
        """
        ngen_cal_type (mode): 'calibration', 'restart', or 'validation'
        """

        if mode in ['calibration', 'restart']:
            sim_time = self.calibration_time
            eval_time = self.calib_eval_time
            start_time = pd.Timestamp(sim_time['start_time']).strftime("%Y%m%d%H%M")
            restart_dir = self.restart_dir.replace("{*}", id)
            ngen_cal_type = mode

        elif mode == 'validation':
            sim_time = self.validation_time
            eval_time = self.valid_eval_time
            start_time = pd.Timestamp(sim_time['start_time']).strftime("%Y%m%d%H%M")
            restart_dir = self.restart_dir
            ngen_cal_type = 'validation'

        else:
            raise ValueError(f"Unsupported mode (ngen_cal_type): {mode}")

        troute_output_file = os.path.join(f"./troute_output_{start_time}.nc")


        ConfigGen = configuration.ConfigurationCalib(
            gpkg_file            = gpkg_file,
            output_dir           = o_dir,
            ngen_dir             = self.ngen_dir,
            sandbox_dir          = self.sandbox_dir,
            realization_file_par = file_par,
            troute_output_file   = troute_output_file,
            ngen_cal_type        = ngen_cal_type,
            formulation          = self.formulation,
            model_variants       = self.model_variants,
            simulation_time      = sim_time,
            evaluation_time      = eval_time,
            ngen_cal_basefile    = self.config_calib,
            restart_dir          = restart_dir,
            num_proc             = self.num_procs,
            ensemble_enabled     = self.ensemble_enabled,
            ensemble_models      = self.ensemble_models,
            ensemble_calib_params_groups = self.ensemble_calib_params_groups
        )

        ConfigGen.write_calib_input_files()


        # Run command
        if mode in ['calibration', 'restart']:
            run_command = f"{sys.executable} -m ngen.cal configs/ngen-cal_calib_config.yaml"

        elif mode == 'validation':
            run_command = (
                f"{sys.executable} {self.sandbox_dir}/src/python/validation.py "
                f"-config configs/ngen-cal_valid_config.yaml"
            )

            if self.ensemble_enabled:
                run_command += " -routing configs/troute_config.yaml"

        if not self.dryrun:
            result = subprocess.run(run_command, shell=True)
            if result.returncode != 0:
                raise RuntimeError(f"{mode.capitalize()} step failed...")
        else:
            print("Dry run: no simulation executed.")

            return
