############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
# Date    : September 28, 2023
############################################################################################

import os
import sys
import argparse
import re
import copy
import glob
import json
import subprocess
import pandas as pd
import geopandas as gpd
import numpy as np
import fiona
import yaml
import platform
import math
from pathlib import Path


os_name = platform.system()
try:
    from src.python import schema
except:
    import schema

from src.python.data_loader import SandboxData


# ----------------------------
# Base Generator
# ----------------------------
class ConfigurationGenerator:
    def __init__(self, static_data: SandboxData):
        self.static_data = static_data

        # convenience
        self.gdf = static_data.gdf
        self.catids = static_data.catids
    
    def write_input_files(self, member_id=None, tag=None):
        """
        Public entry point called by driver.
        """
        self._write_input_files(member_id, tag)

    def _write_input_files(self, member_id, tag):
        """
        Must be overridden by subclasses.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _write_input_files()"
        )

    def create_directory(self, dir_name, member_id=1):
        if member_id == 1 and os.path.exists(dir_name):
            str_sub = "rm -rf " + dir_name
            out = subprocess.call(str_sub, shell=True)
        os.makedirs(dir_name, exist_ok=True)


class CompositeConfigurationGenerator(ConfigurationGenerator):

    def __init__(self, generators):
        self.generators = generators

    def write_input_files(self, member_id=None, tag=None):
        for gen in self.generators:
            gen.write_input_files(member_id, tag)


class ConfigurationCalib:
    STREAMFLOW_OBSERVATION_PLUGIN = (
        "ngen_cal_user_plugins.read_obs_plugin.ReadObservedData"
    )

    def __init__(self,
                 ctx,
                 gpkg_file,
                 output_dir,
                 realization_file_par,
                 troute_output_file,
                 simulation_time,
                 evaluation_time,
                 num_procs,
                 ngen_cal_type
                 ):
        self.ctx=ctx
        self.gpkg_file          = gpkg_file
        self.output_dir         = output_dir
        self.simulation_time    = simulation_time
        self.evaluation_time    = evaluation_time
        self.troute_output_file = troute_output_file
        self.realization_file_par = realization_file_par
        self.num_procs =  num_procs
        self.ngen_cal_type = ngen_cal_type

    def get_flowpath_attributes(self):

        layers = fiona.listlayers(self.gpkg_file)
        flowpath_layer = [layer for layer in layers if 'flowpath' in layer and not 'flowpaths' in layer][0]
        gdf_fp_attr = gpd.read_file(self.gpkg_file, layer=flowpath_layer)
        params = schema.get_schema_flowpath_attributes(gdf_fp_attr, for_gage_id=True)


        gage_id = params['gages']
        waterbody_id = params['key']
        gdf_fp_cols = gdf_fp_attr[[waterbody_id, gage_id]]
        basin_gage = gdf_fp_cols[gdf_fp_cols[gage_id].notna()]
        basin_gage_id = basin_gage[waterbody_id].tolist()

        return basin_gage_id

    def find_state_file(self):
        if self.ngen_cal_type == 'validation':
            params_state_dir = self.output_dir

        elif self.ngen_cal_type == 'restart':
            params_state_dir = self.ctx.restart_dir
        else:
            raise ValueError(f"Invalid task_type option: {self.ngen_cal_type}")

        params_state_path = Path(params_state_dir)

        if not params_state_path.exists():
            raise FileNotFoundError(f"Directory does not exist: {params_state_path}")

        # First pattern: directly inside directory
        files = glob.glob(str(params_state_path / "*_parameter_df_state.parquet"))
        if files:
            return files[0]

        # Second pattern: inside *_worker subdirectories
        files = glob.glob(str(params_state_path / "*_worker" / "*_parameter_df_state.parquet"))
        if files:
            return files[0]


        raise FileNotFoundError(
            f"No parameters state file found in {params_state_path} or its *_worker subdirectory"
        )

    def configure_streamflow_observations(self, model_config, gage_id):
        streamflow_files = self.ctx.observation_files.get("streamflow")
        if not streamflow_files:
            plugins = model_config.get("plugins") or []
            model_config["plugins"] = [
                plugin
                for plugin in plugins
                if plugin != self.STREAMFLOW_OBSERVATION_PLUGIN
            ]

            plugin_settings = model_config.get("plugin_settings")
            if isinstance(plugin_settings, dict):
                plugin_settings.pop("read_obs_data", None)
            return

        if gage_id not in streamflow_files:
            raise KeyError(
                f"No validated streamflow observation file found for gage {gage_id}"
            )

        plugins = list(model_config.get("plugins") or [])
        if self.STREAMFLOW_OBSERVATION_PLUGIN not in plugins:
            plugins.append(self.STREAMFLOW_OBSERVATION_PLUGIN)
        model_config["plugins"] = plugins

        settings = dict(streamflow_files[gage_id])
        settings["name"] = "streamflow"
        settings["path"] = str(settings["path"])
        model_config.setdefault("plugin_settings", {})["read_obs_data"] = settings

    def write_calib_input_files(self):
        
        conf_dir = os.path.join(self.output_dir, "configs")
        realization_file =  sorted(
            glob.glob(os.path.join(conf_dir, "realization_*.json"))
            )

        if (self.ctx.ensemble_enabled):
            assert len(realization_file) == self.ctx.ensemble_size
        else:
            assert len(realization_file) == 1

        if not os.path.exists(self.ctx.calib_config_path):
            sys.exit(f"Sample calib yaml file does not exist, provided is {self.ngen_cal_basefile}")

        gpkg_name = os.path.basename(self.gpkg_file).split(".")[0]
        gage_id = self.get_flowpath_attributes()

        with open(self.ctx.calib_config_path, 'r') as file:
            base_file = yaml.safe_load(file)

        df_new = {
            "general": {
                "strategy": {
                    "type": base_file.get("general").get("strategy").get("type", "estimation"),
                    "algorithm": base_file.get("general").get("strategy").get("algorithm", "dds")
                },
                "log": base_file.get("general").get("log", True),
                "start_iteration": base_file.get("general").get("start_iteration", 0),
                "iterations": base_file.get("general").get("iterations"),
                "random_seed": base_file.get("general").get("random_seed", 444.0),
                "workdir": self.output_dir.as_posix(),
                "restart": base_file.get("general").get("restart", False),
            }
        }

        if self.ngen_cal_type == "restart":
            df_new["general"]["restart"] = True

        # Add calibratable parameter blocks
        for model in self.ctx.formulation.split(","):
            model = model.strip()

            for instance in self.ctx.get_model_instances(model):
                name = instance.calib_params_block
                if not name:
                    continue

                param_values = base_file.get(name, [])

                if (self.ctx.ensemble_enabled
                    and self.ctx.ensemble_calib_params_groups.get(model) == "local"):
                    new_params = []

                    for i in range(self.ctx.ensemble_size):
                        for p in param_values:
                            new_param = dict(p)           # create a deep copy to avoid reference issues
                            new_param["name"] = f"{p['name']}_tile_{i+1}"
                            new_params.append(new_param)

                    df_new[name] = new_params

                else:
                    df_new[name] = param_values

        df_new["model"] = {
            "type": "ngen",
            "binary": os.path.join(self.ctx.ngen_dir, "cmake_build/ngen"),
            "realization": realization_file[0],
            "hydrofabric": self.gpkg_file.as_posix(),
            "routing_output": self.troute_output_file,
            "strategy": base_file.get("strategy", "uniform"),
            "eval_feature": gpkg_name.split("_")[1]
        }

        if self.ctx.ensemble_enabled:
            df_new["model"]["binary"] = (
                os.path.join(self.ctx.sandbox_dir,
                             "src/python/landcover_tiling.py")
                )

            cmd = (
                f"--hydrofabric {self.gpkg_file.as_posix()} "
                f"--realization {realization_file[0]} "
                f"--routing {conf_dir}/troute_config.yaml"
            )
            
            if self.num_procs > 1:
                cmd += f" --partition {self.num_procs}"

            if self.ngen_cal_type == "validation":
                 cmd += f" --task_type {self.ngen_cal_type}"

            df_new["model"]["args"]  = cmd

        
        if self.num_procs > 1 and self.ctx.ensemble_size == 1:
            df_new["model"]["parallel"] = self.num_procs
            df_new["model"]["partitions"] = self.realization_file_par

        gage_id = self.get_flowpath_attributes()


        df_new["model"]["params"] = {}

        for model in self.ctx.formulation.split(","):
            model = model.strip()
            for instance in self.ctx.get_model_instances(model):
                name = instance.calib_params_block
                if not name:
                    continue

                # store final params
                df_new["model"]["params"][instance.calibration_model_name] = df_new[f"{name}"] #tiled_params


        if self.ngen_cal_type in ["calibration", "restart"]:
            df_new["model"]["eval_params"] = {
                #'sim_start': self.simulation_time['start_time'],
                'evaluation_start': self.evaluation_time['start_time'],
                'evaluation_stop' : self.evaluation_time['end_time'],
                'objective': base_file.get("model").get("eval_params").get("objective", "kling_gupta"),
                'target'   : base_file.get("model").get("eval_params").get("target", "min"),
            }

        # Validation
        if self.ngen_cal_type == "validation":
            df_new["model"]["val_params"] = {
                'sim_start': self.simulation_time['start_time'],
                'evaluation_start': self.evaluation_time['start_time'],
                'evaluation_stop': self.evaluation_time['end_time'],
                'objective': "kling_gupta"
            }

            df_new["model"]["plugin_settings"] = {
                'ngen_cal_troute_output': {
                    'validation_routing_output': self.troute_output_file
                }
            }

        df_new["model"]["plugins"] = base_file.get("model", {}).get("plugins", [])
        self.configure_streamflow_observations(
            df_new["model"],
            gpkg_name.removeprefix("gage_"),
        )
             

        if self.ngen_cal_type in ['restart', 'validation']:


            state_file = self.find_state_file()

            df_parq = pd.read_parquet(state_file)
            df_params = pd.read_csv(Path(state_file).parent / "best_params.txt", header = None)

            best_itr = str(int(df_params.values[1]))

            best_params_set = df_parq[best_itr]
            calib_params = best_params_set.index.to_list()
            
            for block_name in df_new:
                if '_params' in block_name:    
                    for par in df_new[block_name]:
                        if par['name'] in calib_params:
                            par['init'] = float(best_params_set[par['name']]) #modify in place

                            
        if self.ngen_cal_type in ['calibration', 'restart']:
            config_fname = "ngen-cal_calib_config.yaml"
        elif self.ngen_cal_type == 'validation':
            config_fname = "ngen-cal_valid_config.yaml"
        else:
            raise ValueError(f"Unsupported ngen_cal_type: {self.ngen_cal_type}")

        with open(os.path.join(conf_dir, config_fname), 'w') as file:
            yaml.dump(df_new, file, default_flow_style=False, sort_keys=False)
