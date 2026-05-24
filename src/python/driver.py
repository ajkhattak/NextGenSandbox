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
    def __init__(self, ctx):
        self.ctx = ctx

    def generate_catchment_files(self, dirs):
        ctx = self.ctx

        i_dir = dirs[0]
        o_dir = dirs[1]
        f_dir = dirs[2]

        o_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(o_dir)

        basin_ids = []
        num_cats = []

        if self.ctx.verbosity >= 2:
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
        num_cpus = helper.prepare_basin_partitioning(ctx.sandbox_dir, gpkg_file,
                                                     ctx.sandbox_config["simulation"]['partitioning'],
                                                     create_par_file=False)
        # this meta data is needed to resubmit jobs on HPC after wallclock time outs

        if ctx.sb_launcher:

            # write meta data to YAML for restarting
            sim_info = {
                "basin_id"   : gpkg_id,
                "num_cpus"  : num_cpus,
                "input_dir"  : str(i_dir),
                "output_dir" : str(o_dir),
                "cwd"        : os.getcwd()
            }

            os.makedirs(str(o_dir.parent / ctx.exp_info_dir) , exist_ok=True)

            # Write to YAML file
            sim_yaml_file = o_dir.parent / ctx.exp_info_dir / f"info_{gpkg_id}.yml"

            if not sim_yaml_file.exists():
                with open(sim_yaml_file, "w") as f:
                    yaml.dump(sim_info, f, default_flow_style=False)


        if ctx.verbosity >= 1:
            print("-- ", gpkg_name, end="")

        gpkg_dir = os.path.join(i_dir, gpkg_dir)
        
        helper.create_clean_dirs(output_dir=o_dir,
                                 task_type=ctx.task_type,
                                 clean=ctx.clean)

        # Call generate files
        gen = generate.Generate(ctx = self.ctx,
                                gpkg_file   = gpkg_dir,
                                forcing_dir = f_dir,
                                output_dir  = o_dir,
                                )

        gen.run()
        failed = False
        if not failed:
            basin_ids.append(gpkg_id)
            x = gpd.read_file(gpkg_dir, layer="divides")
            num_cats.append(len(x["divide_id"]))

        if ctx.verbosity >= 1:
            result = "Passed" if not failed else "Failed"
            print(self.colors.GREEN + "  %s " % result + self.colors.END)

        return basin_ids, num_cats


    def main(self):
        ctx = self.ctx
        
        basins_passed = os.path.join(ctx.output_dir, "basins_passed.csv")
        file_exists = os.path.exists(basins_passed)

        existing_gages = set()
        if ctx.gage_ids is None:
            if file_exists:
                os.remove(basins_passed)
        else:
            # Load existing gage_ids if file exists and is not empty

            if file_exists and os.path.getsize(basins_passed) > 0:
                with open(basins_passed, 'r', newline='') as file:
                    reader = csv.DictReader(file)
                    existing_gages = {row['gage_id'] for row in reader}

        basin_ids = []
        num_cats  = []

        tuple_list = list(zip(ctx.gpkg_dirs, ctx.output_dirs, ctx.forcing_files))

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


    

    def run(self):
        ctx = self.ctx

        if ctx.verbosity >= 2:
            print(ctx.simulation_time)

        start_time = time.time()

        if ctx.clean[0] == "all":
            check = input("\nDo you really want to delete all except \'data\' directory? you will lose all ngen output data: ")
            if check.lower() in ["y", "yes"]:
                print("Deleting all existing simulation data except \'data\' directory.")
            elif check.lower() in ["n", "no"]:
                sys.exit("Quiting...")

        ctx.output_dir.mkdir(parents=True, exist_ok=True)

        # Validate required directories
        if not ctx.sandbox_dir.exists():
            raise AssertionError("sandbox_dir does not exist")

        if not ctx.ngen_dir.exists():
            raise AssertionError("ngen_dir does not exist")


        # Validate repo structure

        required_path = ctx.sandbox_dir / "src/python"

        if not required_path.exists():
            sys.exit("check `sandbox_dir`, it should be parent of src/python")


        success_ncats = self.main()
        
        end_time = time.time()
        total_time = end_time - start_time

        print("================== SUMMARY ===============================")
        print("| Total time         = %s [sec], %s [min]" % (round(total_time, 4), round(total_time / 60., 4)))
        print("| Total no of basins = %s " % len(ctx.gpkg_dirs))
        print("| Succeeded          = %s " % success_ncats)
        print("| Failed             = %s " % (len(ctx.gpkg_dirs) - success_ncats))
        print("==========================================================")
