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
    OBSERVATION_PLUGIN = (
        "ngen_cal_plugins.read_obs_plugin.ReadObservedData"
    )
    NGEN_CAL_OBJECTIVES = {
        "custom",
        "kling_gupta",
        "nnse",
        "single_peak",
        "volume",
    }
    OBSERVATION_OBJECTIVES = {
        "kge": "ngen_cal_plugins.objectives.kge_multi_variable",
        "nse": "ngen_cal_plugins.objectives.nse_multi_variable",
        "nnse": "ngen_cal_plugins.objectives.nnse_multi_variable",
    }
    CALIB_CONFIG_RESERVED_KEYS = {
        "general",
        "calibration",
        "model",
        "strategy",
    }

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

    @staticmethod
    def _calibration_filename_stems(value):
        hyphenated = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        underscored = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        stems = [hyphenated]
        if underscored != hyphenated:
            stems.append(underscored)
        return stems

    @classmethod
    def _calibration_filenames(cls, value):
        return [
            f"{stem}.yaml"
            for stem in cls._calibration_filename_stems(value)
            if stem
        ]

    @staticmethod
    def _block_name_stem(value):
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    def _required_calib_params_blocks(self):
        required = []
        for model in self.ctx.formulation_models:
            for instance in self.ctx.get_model_instances(model):
                if (
                    instance.calib_params_block
                    and instance.calib_params_block not in required
                ):
                    required.append(instance.calib_params_block)
        return required

    def _candidate_calib_param_files(self, params_dir, required_blocks):
        candidates = []

        for model in self.ctx.formulation_models:
            for instance in self.ctx.get_model_instances(model):
                block = instance.calib_params_block
                if not block or block not in required_blocks:
                    continue

                names = []
                if getattr(instance, "calib_params_file", ""):
                    names.append(instance.calib_params_file)
                names.extend(self._calibration_filenames(instance.name))
                names.extend(self._calibration_filenames(instance.model))
                names.extend(
                    self._calibration_filenames(instance.calibration_model_name)
                )
                names.append(
                    f"{self._block_name_stem(block.removesuffix('_params'))}.yaml"
                )

                for name in names:
                    if not name:
                        continue
                    path = params_dir / name
                    if path.exists() and path not in candidates:
                        candidates.append(path)

        return candidates

    @staticmethod
    def build_strategy_config(base_strategy):
        algorithm = base_strategy.get("algorithm", "dds")
        strategy = {
            "type": base_strategy.get("type", "estimation"),
            "algorithm": algorithm,
        }

        if algorithm.lower() == "pso" and "parameters" in base_strategy:
            strategy["parameters"] = base_strategy["parameters"]

        return strategy

    @classmethod
    def normalize_calibration_parameter_blocks(cls, param_blocks):
        return {
            block_name: cls.normalize_calibration_parameters(
                block_name,
                params,
            )
            for block_name, params in param_blocks.items()
        }

    @classmethod
    def normalize_calibration_parameters(cls, block_name, params):
        if not isinstance(params, list):
            return params

        return [
            cls.normalize_calibration_parameter(block_name, param)
            for param in params
        ]

    @staticmethod
    def normalize_calibration_parameter(block_name, param):
        if not isinstance(param, dict):
            return param

        scale = str(param.get("scale", "linear")).lower()
        if scale not in {"linear", "log10"}:
            raise ValueError(
                f"Calibration parameter '{param.get('name', '<unknown>')}' "
                f"in block '{block_name}' has unsupported scale '{scale}'. "
                "Supported values are: linear, log10."
            )

        normalized = dict(param)
        if "scale" in normalized:
            normalized["scale"] = scale

        if scale != "log10":
            return normalized

        normalized["scale"] = scale

        for field in ("min", "max", "init"):
            if field not in normalized:
                raise ValueError(
                    f"Calibration parameter '{param.get('name', '<unknown>')}' "
                    f"in block '{block_name}' is missing required field '{field}'."
                )
            value = float(normalized[field])
            if value <= 0.0:
                raise ValueError(
                    f"Calibration parameter '{param.get('name', '<unknown>')}' "
                    f"in block '{block_name}' uses scale: log10, so '{field}' "
                    f"must be a positive physical value. Provided: {value}"
                )
            normalized[field] = math.log10(value)

        if normalized["min"] > normalized["max"]:
            raise ValueError(
                f"Calibration parameter '{param.get('name', '<unknown>')}' "
                f"in block '{block_name}' has min greater than max after "
                "log10 conversion."
            )
        if not normalized["min"] <= normalized["init"] <= normalized["max"]:
            raise ValueError(
                f"Calibration parameter '{param.get('name', '<unknown>')}' "
                f"in block '{block_name}' has init outside min/max after "
                "log10 conversion."
            )

        return normalized

    def load_calib_config(self):
        with open(self.ctx.calib_config_path, "r") as file:
            base_file = yaml.safe_load(file) or {}

        if not isinstance(base_file, dict):
            raise ValueError(
                f"Calibration config must be a YAML mapping: {self.ctx.calib_config_path}"
            )
        extra_top_level_keys = {
            key: value
            for key, value in base_file.items()
            if key not in self.CALIB_CONFIG_RESERVED_KEYS
        }
        if extra_top_level_keys:
            keys = ", ".join(sorted(extra_top_level_keys))
            raise ValueError(
                "Calibration parameter blocks must be defined in files under "
                "calibration.params_dir, not directly in calib_config.yaml. "
                f"Move top-level block(s) to configs/calibration/*.yaml: {keys}"
            )

        param_blocks = {}
        calibration = base_file.get("calibration", {}) or {}
        if not isinstance(calibration, dict):
            raise ValueError("calibration block in calib_config.yaml must be a mapping")

        params_dir = calibration.get("params_dir")
        if not params_dir:
            raise ValueError(
                "calibration.params_dir must be provided in calib_config.yaml. "
                "Each model's calibration parameters must live in a YAML file "
                "under that directory."
            )

        required_blocks = self._required_calib_params_blocks()

        params_dir = Path(params_dir)
        if not params_dir.is_absolute():
            params_dir = Path(self.ctx.calib_config_path).resolve().parent / params_dir

        if not params_dir.is_dir():
            raise FileNotFoundError(
                f"Calibration parameter directory does not exist: {params_dir}"
            )

        for params_file in self._candidate_calib_param_files(
            params_dir,
            required_blocks,
        ):
            with open(params_file, "r") as file:
                file_blocks = yaml.safe_load(file) or {}

            if not isinstance(file_blocks, dict):
                raise ValueError(
                    f"Calibration parameter file must be a YAML mapping: {params_file}"
                )

            for key, value in file_blocks.items():
                if key in self.CALIB_CONFIG_RESERVED_KEYS:
                    raise ValueError(
                        f"Reserved key '{key}' is not allowed in calibration "
                        f"parameter file: {params_file}"
                    )
                if key in param_blocks:
                    raise ValueError(
                        f"Duplicate calibration parameter block '{key}' found "
                        f"in {params_file}"
                    )
                param_blocks[key] = value

        missing_blocks = [
            block for block in required_blocks
            if block not in param_blocks
        ]
        if missing_blocks:
            raise ValueError(
                "Calibration parameter block(s) were not found for the "
                "active formulation: "
                f"{', '.join(missing_blocks)}. Check "
                "configs/calib_config.yaml calibration.params_dir and the "
                "model files under configs/calibration/."
            )
        
        param_blocks = self.normalize_calibration_parameter_blocks(param_blocks)
        base_file.update(param_blocks)
        return base_file

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

    def configure_observations(self, model_config, gage_id):
        observation_settings = {}
        for name, files_by_gage in self.ctx.observation_files.items():
            if gage_id not in files_by_gage:
                raise KeyError(
                    f"No validated {name} observation file found for gage "
                    f"{gage_id}"
                )

            settings = dict(files_by_gage[gage_id])
            settings["path"] = str(settings["path"])
            simulated = settings.get("simulated")
            if simulated:
                settings["simulated_units"] = self.ctx.divide_output_variables[
                    simulated
                ]["units"]
            observation_settings[name] = settings

        if not observation_settings:
            plugins = model_config.get("plugins") or []
            model_config["plugins"] = [
                plugin
                for plugin in plugins
                if plugin != self.OBSERVATION_PLUGIN
            ]

            plugin_settings = model_config.get("plugin_settings")
            if isinstance(plugin_settings, dict):
                plugin_settings.pop("read_obs_data", None)
            return

        objective_key = (
            "val_params"
            if getattr(self, "ngen_cal_type", None) == "validation"
            else "eval_params"
        )
        objective_params = model_config.setdefault(objective_key, {})
        observation_objective = getattr(
            self.ctx,
            "observation_objective",
            None,
        )
        if observation_objective:
            objective_name = observation_objective.strip().lower()
            if objective_name in self.OBSERVATION_OBJECTIVES:
                objective = self.OBSERVATION_OBJECTIVES[objective_name]
            elif "." in observation_objective:
                objective = observation_objective.strip()
            else:
                supported = ", ".join(sorted(self.OBSERVATION_OBJECTIVES))
                raise ValueError(
                    f"Unsupported observations.objective "
                    f"'{observation_objective}'. Supported objectives: "
                    f"{supported}, or a custom objective import path"
                )
            objective_params["objective"] = objective
            objective_params["target"] = "min"

        variables = set(observation_settings)
        uses_streamflow_default = variables == {"streamflow"}
        objective = objective_params.get("objective")
        uses_custom_objective = (
            isinstance(objective, str)
            and objective not in self.NGEN_CAL_OBJECTIVES
        )
        if not uses_streamflow_default and not uses_custom_objective:
            names = ", ".join(observation_settings)
            raise ValueError(
                "Built-in ngen-cal objectives are only valid when streamflow is "
                "the sole local observation type. "
                f"Configured observation types: {names}. "
                "Set model.eval_params.objective in configs/calib_config.yaml to "
                "the import path of a custom objective function, typically defined "
                "in the plugins package."
            )


        plugins = list(model_config.get("plugins") or [])
        if self.OBSERVATION_PLUGIN not in plugins:
            plugins.append(self.OBSERVATION_PLUGIN)
        model_config["plugins"] = plugins
        model_config.setdefault("plugin_settings", {})[
            "read_obs_data"
        ] = observation_settings

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

        base_file = self.load_calib_config()

        base_strategy = base_file.get("general", {}).get("strategy", {})
        strategy = self.build_strategy_config(base_strategy)

        df_new = {
            "general": {
                "strategy": strategy,
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
        for model in self.ctx.formulation_models:
            for instance in self.ctx.get_model_instances(model):
                name = instance.calib_params_block
                if not name:
                    continue

                param_values = base_file.get(name)
                if param_values is None:
                    raise ValueError(
                        f"Calibration parameter block '{name}' was not found. "
                        "Check configs/calib_config.yaml calibration.params_dir "
                        "and the model files under configs/calibration/."
                    )

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

        for model in self.ctx.formulation_models:
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
        output_retention = (
            self.ctx.calibration_output_retention
            if self.ngen_cal_type in {"calibration", "restart"}
            else "all"
        )
        df_new["model"].setdefault("plugin_settings", {})[
            "output_retention"
        ] = {
            "mode": output_retention,
        }
        self.configure_observations(
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
