############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
# Date    : October 11, 2023
############################################################################################


import os
import sys
import subprocess
import pandas as pd
import glob
import shutil
import re
import geopandas as gpd
import csv
import yaml
from functools import partial
import time
import argparse
import json
from pathlib import Path

from src.python import helper
from src.python import generate

class Driver:
    def __init__(self, sandbox_dir, infile, formulations_supported):
        self.colors = helper.colors()

        self.sandbox_dir  = Path(sandbox_dir)
        self.sandbox_config = infile
        self.formulations_supported = formulations_supported
        self.load_config()

    def load_config(self):
        with open(self.sandbox_config, 'r') as file:
            self.config = yaml.safe_load(file)

        self.input_dir    = self.config['general'].get('input_dir')
        self.output_dir   = Path(self.config['general'].get('output_dir'))
        
        dformul = self.config['formulation']
        self.ngen_dir       = Path(os.environ.get("NGEN_DIR"))
        self.formulation    = dformul['models'].upper().replace(" ","")
        self.model_variants = dformul.get('model_variants', {})
        self.clean          = self.process_clean_input_param(dformul.get('clean', "none"))
        self.verbosity      = dformul.get('verbosity', 0)
        self.schema_type    = dformul.get('schema_type', "noaa-owp")

        # Forcing block
        dforcing = self.config['forcings']

        self.forcing_time   = dforcing["time"]
        self.forcing_format = dforcing.get('format', '.nc')
        forcing_start_yr    = pd.Timestamp(self.forcing_time['start_time']).year
        forcing_end_yr      = pd.Timestamp(self.forcing_time['end_time']).year + 1
        forcing_dir         = os.path.join(self.input_dir, "{*}", f'data/forcing/{forcing_start_yr}_to_{forcing_end_yr}')
        self.forcing_dir    = dforcing.get("forcing_dir", forcing_dir)
        self.domain         = dforcing.get('domain', 'conus')
        self.is_corrected_forcing = dforcing.get('is_corrected_forcing', True)

        self.is_netcdf_forcing = True
        if self.forcing_format == '.csv':
            self.is_netcdf_forcing = False

        # Simulation block
        dsim = self.config['simulation']
        self.task_type = (dsim.get('task_type', 'control')).lower()

        if "LSTM" in self.formulation:
            print ("INFO: LSTM formulation -- setting task_type to control ")
            self.task_type = "control"

        # Get gages IDs
        self.gage_ids = self.load_gage_ids(dsim.get("gage_ids_input"))
        
        self.sim_name_suffix = dsim.get('sim_name_suffix') or None

        self.disable_divide_output = dsim.get('disable_divide_output',True)

        dlauncher = self.config.get('sandbox_launcher') or None

        if dlauncher:
            self.sb_launcher = dlauncher.get('exp_info', False)
            self.exp_info_dir = dlauncher.get('exp_info_dir') or None
            if self.exp_info_dir is None:
                raise ValueError("sandbox_launcher is True, but exp_info_dir not provided")
        else:
            self.sb_launcher = False

        if self.task_type == 'calibration' or self.task_type == 'calibvalid' or self.task_type == 'restart':
            if "calibration_time" not in dsim or not isinstance(dsim["calibration_time"], dict):
                raise ValueError("calibration_time is not provided or is not a valid dictionary.")
            
            self.simulation_time = dsim["calibration_time"]
        elif self.task_type == 'validation':
            if "validation_time" not in dsim or not isinstance(dsim["validation_time"], dict):
                raise ValueError("validation_time is not provided or is not a valid dictionary.")

            self.simulation_time = dsim["validation_time"]
        elif self.task_type == 'control':
            if "simulation_time" not in dsim or not isinstance(dsim["simulation_time"], dict):
                raise ValueError("task_type is CONTROL, but simulation_time is not provided or is not a valid dictionary.")
            
            self.simulation_time = dsim["simulation_time"]
        else:
            raise ValueError("Not a valid task_type provided: valid options are [control, calibration, validation, calibvalid, restart]")

        densemble = dsim.get('ensemble') or None

        if (densemble):
            self.ensemble_enabled = bool(densemble.get('enabled'))
            
            if self.ensemble_enabled:
                self.ensemble_models  = self.formulation.replace("T-ROUTE", "").replace(" ,", ",").strip(", ").strip() #densemble.get('models').upper()

                ensemble_calib_params_groups = densemble.get('calib_params_groups')
            else:
                self.ensemble_size = 1
                self.ensemble_models = []

        else:
            self.ensemble_enabled = False
            self.ensemble_models  = []

        # check if formulation is supported
        formulation_in_lower      = self.formulation.lower()

        # Check if T-ROUTE is present (case-insensitive)
        has_troute = "t-route" in formulation_in_lower

        formulation_test = formulation_in_lower if has_troute else f"{self.formulation},T-ROUTE"

        if not formulation_test.upper() in self.formulations_supported:
            raise ValueError(
                f"\nUnsupported formulation: {self.formulation} \n"
                f"Supported: {self.formulations_supported} \n"
                "[INFO]: Formulations that omit T-ROUTE are allowed, however, all other formulation components must be specified exactly as supported."
            )

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


    def process_clean_input_param(self, clean):
        clean_lst = []
        if isinstance(clean, str):
            clean_lst = [clean]
        elif isinstance(clean, list):
            clean_lst.extend(clean)
        return clean_lst

    def get_forcing_files(self, gpkg_dirs):
        forcing_files = []

        if self.forcing_format == ".nc":

            if "{*}" in self.forcing_dir:
                for g in gpkg_dirs:
                    forcing_dir_local = self.forcing_dir
                    fdir = Path(forcing_dir_local.replace("{*}", Path(g).name))

                    if not fdir.exists() or not fdir.is_dir():
                        raise ValueError(f"Forcing directory '{fdir}' does not exist.")
                    if self.is_corrected_forcing:
                        forcing_file = glob.glob(f"{fdir}/*_corrected.nc")[0]

                        chunk_py = os.path.join(self.sandbox_dir,"utils/python/rechunk_forcing.py")
                        # Rechunk forcing file if utility exists
                        if os.path.isfile(chunk_py):
                            subprocess.run(
                                [sys.executable, chunk_py, "-i", forcing_file],
                                check=True
                            )

                            rechunked_files = glob.glob(f"{fdir}/*_corrected_rechunked.nc")

                            if rechunked_files:
                                forcing_file = rechunked_files[0]

                    else:
                        nc_file = glob.glob(f"{fdir}/*.nc")
                        forcing_file = [f for f in nc_file if not "_corrected" in f][0]

                    forcing_files.append(forcing_file)
            else:
                if not Path(self.forcing_dir).exists():
                    raise ValueError("Forcing directory '{self.forcing_dir}' does not exist.")

                if not Path(self.forcing_dir).is_dir():
                    forcing_file = self.forcing_dir
                else:
                    if self.is_corrected_forcing:
                        forcing_file = glob.glob(f"{self.forcing_dir}/*_corrected.nc")[0]
                    else:
                        nc_file = glob.glob(f"{fdir}/*.nc")
                        forcing_file = [f for f in nc_file if not "_corrected" in f][0]

                forcing_files.append(forcing_file)
        else:
            if "{*}" in self.forcing_dir:
                for g in gpkg_dirs:
                    forcing_dir_local = self.forcing_dir
                    fdir = Path(forcing_dir_local.replace("{*}", Path(g).name))

                    if not fdir.exists():
                        raise ValueError("Forcing directory '{fdir}' does not exist.")
                    if not fdir.is_dir():
                        raise ValueError("forcing format is .csv, so '{fdir}' should point to a directory and not file.")

                    forcing_files.append(fdir)

        return forcing_files

    def generate_catchment_files(self, dirs):
        i_dir = dirs[0]
        o_dir = dirs[1]
        f_dir = dirs[2]

        o_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(o_dir)

        basin_ids = []
        num_cats = []

        if self.verbosity >= 2:
            print("***********************************")
            print("cwd: ", os.getcwd())
            print("input_dir: ", i_dir)
            print("output_dir: ", o_dir)
            print("forcing_dir: ", f_dir)

        gpkg_name = Path(glob.glob(str(i_dir / "data" / "*.gpkg"))[0]).name
        gpkg_dir = Path(glob.glob(str(i_dir / "data" / "*.gpkg"))[0])
        gpkg_id = i_dir.name

        # get num of cores for the basin
        gpkg_file = Path(glob.glob(str(i_dir / "data" / "*.gpkg"))[0])
        num_cpus = helper.prepare_basin_partitioning(self.sandbox_dir, gpkg_file,
                                                     self.config["simulation"]['partitioning'],
                                                     create_par_file=False)
        # this meta data is needed to resubmit jobs on HPC after wallclock time outs

        if self.sb_launcher:

            # write meta data to YAML for restarting
            sim_info = {
                "basin_id"   : gpkg_id,
                "num_cpus"  : num_cpus,
                "input_dir"  : str(i_dir),
                "output_dir" : str(o_dir),
                "cwd"        : os.getcwd()
            }

            os.makedirs(str(o_dir.parent / self.exp_info_dir) , exist_ok=True)

            # Write to YAML file
            sim_yaml_file = o_dir.parent / self.exp_info_dir / f"info_{gpkg_id}.yml"

            if not sim_yaml_file.exists():
                with open(sim_yaml_file, "w") as f:
                    yaml.dump(sim_info, f, default_flow_style=False)


        if self.verbosity >= 1:
            print("-- ", gpkg_name, end="")

        gpkg_dir = os.path.join(i_dir, gpkg_dir)
        
        helper.create_clean_dirs(output_dir=o_dir,
                                 task_type=self.task_type,
                                 clean=self.clean)

        # Call generate files
        driver_ = generate.Generate(sandbox_dir = self.sandbox_dir,
                                    gpkg_file   = gpkg_dir,
                                    forcing_dir = f_dir,
                                    ngen_dir    = self.ngen_dir,
                                    sim_time    = self.simulation_time,
                                    formulation = self.formulation,
                                    model_variants = self.model_variants,
                                    output_dir     = o_dir,
                                    forcing_format = self.forcing_format,
                                    ngen_cal_type  = self.task_type,
                                    schema = self.schema_type,
                                    domain = self.domain,
                                    disable_divide_output = self.disable_divide_output,
                                    ensemble_enabled = self.ensemble_enabled,
                                    ensemble_models  = self.ensemble_models
                                    )

        failed = False
        if not failed:
            basin_ids.append(gpkg_id)
            x = gpd.read_file(gpkg_dir, layer="divides")
            num_cats.append(len(x["divide_id"]))

        if self.verbosity >= 1:
            result = "Passed" if not failed else "Failed"
            print(self.colors.GREEN + "  %s " % result + self.colors.END)

        return basin_ids, num_cats


    def main(self):
        basins_passed = os.path.join(self.output_dir, "basins_passed.csv")
        file_exists = os.path.exists(basins_passed)

        existing_gages = set()
        if self.gage_ids is None:
            if file_exists:
                os.remove(basins_passed)
        else:
            # Load existing gage_ids if file exists and is not empty

            if file_exists and os.path.getsize(basins_passed) > 0:
                with open(basins_passed, 'r', newline='') as file:
                    reader = csv.DictReader(file)
                    existing_gages = {row['gage_id'] for row in reader}

        forcing_files = self.get_forcing_files(self.gpkg_dirs)

        basin_ids = []
        num_cats  = []

        tuple_list = list(zip(self.gpkg_dirs, self.output_dirs, forcing_files))

        results = []
        for tpl in tuple_list:
            result = self.generate_catchment_files(tpl)
            if result is not None:
                results.append(result)

        for result in results:
            basin_ids.extend(result[0])
            num_cats.extend(result[1])

        new_gages = [
            (gid, ncat) for gid, ncat in zip(basin_ids, num_cats)
            if gid not in existing_gages
        ]

        # Append or create a new file
        mode = 'a' if file_exists else 'w'
        with open(basins_passed, mode, newline='') as file:
            writer = csv.writer(file)
            # Write header if creating a new file OR if the existing file is empty
            if not file_exists or os.path.getsize(basins_passed) == 0:
                writer.writerow(['gage_id', 'num_divides'])
            writer.writerows(new_gages)

        # logging
        if new_gages:
            print(f"Added {len(new_gages)} new basin(s) to {basins_passed}")
        else:
            print("No new basins to add.")

        

        return len(num_cats)


    def load_gpkg_dirs(self):
        # Get all subdirectories inside input_dir
        all_dirs = glob.glob(os.path.join(self.input_dir, '*/'), recursive=True)

        # Filter directories that have a "data" folder that contains a .gpkg file
        self.gpkg_dirs = [
            Path(g) for g in all_dirs
            if os.path.exists(os.path.join(g, 'data')) and 
            glob.glob(os.path.join(g, 'data', '*.gpkg'))
        ]

        gage_ids = self.gage_ids or []  # Default to empty list [] if None

        # If it's a single string, convert to list
        if isinstance(gage_ids, str):
            gage_ids = [gage_ids]
        elif not isinstance(gage_ids, list):
            raise TypeError(f"gage_ids must be a string, list, or None, but got {type(self.gage_ids).__name__}")


        # If gage_id is provided, further filter based on gage_id presence in .gpkg filenames

        if gage_ids:
            self.gpkg_dirs = [
                g for g in self.gpkg_dirs
                if any(
                    any(gid in Path(f).stem for gid in gage_ids)
                    for f in glob.glob(os.path.join(g, 'data', '*.gpkg'))
                )
            ]

        assert self.gpkg_dirs, f"Geopackage file(s) missing for gage(s) {gage_ids} in directory {self.input_dir}"


    def run(self):
        start_time = time.time()

        if self.verbosity >= 2:
            print(self.simulation_time)

        if self.clean[0] == "all":
            check = input("\nDo you really want to delete all except \'data\' directory? you will lose all ngen output data: ")
            if check.lower() in ["y", "yes"]:
                print("Deleting all existing simulation data except \'data\' directory.")
            elif check.lower() in ["n", "no"]:
                sys.exit("Quiting...")

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
    
        assert os.path.exists(self.sandbox_dir)
        assert os.path.exists(self.ngen_dir)

        if not os.path.exists(os.path.join(self.sandbox_dir, "src/python")):
            sys.exit("check `sandbox_dir`, it should be the parent directory of `src/python` directory")

        self.load_gpkg_dirs()

        if self.sim_name_suffix:
            self.output_dirs = [self.output_dir / f"{Path(g).name}_{self.sim_name_suffix}" for g in self.gpkg_dirs]
        else:
            self.output_dirs = [self.output_dir / Path(g).name for g in self.gpkg_dirs]

        success_ncats = self.main()
        
        end_time = time.time()
        total_time = end_time - start_time

        print("================== SUMMARY ===============================")
        print("| Total time         = %s [sec], %s [min]" % (round(total_time, 4), round(total_time / 60., 4)))
        print("| Total no of basins = %s " % len(self.gpkg_dirs))
        print("| Succeeded          = %s " % success_ncats)
        print("| Failed             = %s " % (len(self.gpkg_dirs) - success_ncats))
        print("==========================================================")
