############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ajkhattak@gmail.com
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
from datetime import datetime, timezone

from src.python import helper
from src.python import generate
from src.python.resource_paths import find_gpkg_file

class Driver:
    def __init__(self, ctx):
        self.ctx = ctx

    def generate_catchment_files(self, dirs):
        ctx = self.ctx

        gpkg_id = dirs[0]
        i_dir = dirs[1]
        o_dir = dirs[2]
        f_dir = dirs[3]

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

        gpkg_dir = find_gpkg_file(i_dir)
        gpkg_name = gpkg_dir.name

        # get num of cores for the basin
        gpkg_file = gpkg_dir
        partitioning = ctx.sandbox_config.get("simulation", {}).get("partitioning", {})
        num_cpus = helper.prepare_basin_partitioning(ctx.sandbox_dir, gpkg_file,
                                                     partitioning,
                                                     create_par_file=False)
        if ctx.verbosity >= 1:
            print("-- ", gpkg_name, end="")

        gpkg_dir = os.path.join(i_dir, gpkg_dir)
        
        if ctx.metadata_enabled:
            self.write_simulation_metadata(
                gpkg_id=gpkg_id,
                num_cpus=num_cpus,
                input_dir=i_dir,
                output_dir=o_dir,
            )

        original_task_type = ctx.task_type
        original_simulation_time = ctx.simulation_time
        try:
            for specification in self.configuration_specs(o_dir):
                ctx.task_type = specification["task_type"]
                ctx.simulation_time = specification["simulation_time"]
                config_dir = specification["config_dir"]
                config_dir.mkdir(parents=True, exist_ok=True)

                gen = generate.Generate(
                    ctx=self.ctx,
                    gage_id=gpkg_id,
                    gpkg_file=gpkg_dir,
                    forcing_dir=f_dir,
                    output_dir=o_dir,
                    config_dir=config_dir,
                )
                gen.run()

                helper.write_configuration_manifest(
                    config_dir,
                    task_type=specification["task_type"],
                    validation_name=specification.get("validation_name"),
                    gage_id=gpkg_id,
                    formulation_models=ctx.formulation_models,
                    simulation_time=specification["simulation_time"],
                    hydrofabric=gpkg_dir,
                    forcing=f_dir,
                )
        finally:
            ctx.task_type = original_task_type
            ctx.simulation_time = original_simulation_time

        failed = False
        if not failed:
            basin_ids.append(gpkg_id)
            x = gpd.read_file(gpkg_dir, layer="divides")
            num_cats.append(len(x["divide_id"]))

        if ctx.verbosity >= 1:
            result = "Passed" if not failed else "Failed"
            print(self.colors.GREEN + "  %s " % result + self.colors.END)

        return basin_ids, num_cats

    def configuration_specs(self, output_dir):
        ctx = self.ctx
        specifications = []

        if ctx.task_type != "validation":
            specifications.append(
                {
                    "config_dir": helper.configuration_dir(
                        output_dir,
                        ctx.task_type,
                    ),
                    "task_type": ctx.task_type,
                    "simulation_time": ctx.simulation_time,
                }
            )

        if "validation" in ctx.simulation_tasks:
            multiple_validations = len(ctx.validation_periods) > 1
            for period in ctx.validation_periods:
                name = period.get("name", "validation")
                specifications.append(
                    {
                        "config_dir": helper.configuration_dir(
                            output_dir,
                            "validation",
                            validation_name=name,
                            multiple_validations=multiple_validations,
                        ),
                        "task_type": "validation",
                        "validation_name": name,
                        "simulation_time": period["simulation_time"],
                    }
                )

        return specifications

    def write_simulation_metadata(self, gpkg_id, num_cpus, input_dir, output_dir):
        ctx = self.ctx
        metadata = {
            "gage_id": gpkg_id,
            "num_cpus": num_cpus,
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "cwd": os.getcwd(),
            "task_type": ctx.task_type,
            "formulation": ctx.formulation,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "sandbox_config": str(ctx.sandbox_config_path),
        }

        metadata_file = output_dir / ctx.metadata_file
        with metadata_file.open("w") as file:
            yaml.safe_dump(metadata, file, default_flow_style=False, sort_keys=False)

        if ctx.metadata_index_dir:
            index_dir = output_dir.parent / ctx.metadata_index_dir
            index_dir.mkdir(parents=True, exist_ok=True)
            index_metadata_file = index_dir / f"run_{gpkg_id}.yml"
            with index_metadata_file.open("w") as file:
                yaml.safe_dump(metadata, file, default_flow_style=False, sort_keys=False)


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

        tuple_list = list(zip(
            ctx.gage_ids,
            ctx.gpkg_dirs,
            ctx.output_dirs,
            ctx.forcing_files,
            strict=True,
        ))

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
