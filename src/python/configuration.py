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
import shutil
import pandas as pd
import numpy as np
import yaml
import platform
import math
from pathlib import Path


os_name = platform.system()

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
            shutil.rmtree(dir_name)
        os.makedirs(dir_name, exist_ok=True)

    def instance_config_dir(self, instance):
        config_dir = getattr(self.static_data, "config_dir", None)
        if config_dir is not None:
            return Path(config_dir) / instance.name
        return Path(instance.config_dir)


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
    DEFAULT_PLUGINS = [
        "ngen_cal_plugins.objective_plugin.ConfigureObjective",
        "ngen_cal_plugins.save_divide_output_plugin.SaveData",
        "ngen_cal_plugins.save_sim_obs_plugin.SaveData",
        "ngen_cal_plugins.metrics.ComputeMetrics",
    ]

    def __init__(self,
                 ctx,
                 gpkg_file,
                 output_dir,
                 realization_file_par,
                 troute_output_file,
                 simulation_time,
                 evaluation_time,
                 num_procs,
                 ngen_cal_type,
                 gage_id,
                 state_dir=None,
                 config_dir=None,
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
        self.gage_id = str(gage_id)
        self.state_dir = Path(state_dir) if state_dir is not None else None
        self.config_dir = (
            Path(config_dir)
            if config_dir is not None
            else Path(output_dir) / "configs"
        )
        self.selected_state_file = None

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
    def build_strategy_config(algorithm, optimizer_settings=None):
        strategy = {
            "type": "estimation",
            "algorithm": algorithm,
        }

        if algorithm == "pso" and optimizer_settings:
            strategy["parameters"] = optimizer_settings

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

    def load_calibration_parameters(self):
        param_blocks = {}
        required_blocks = self._required_calib_params_blocks()
        params_dir = Path(self.ctx.sandbox_dir) / "configs" / "calibration"

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
                f"{', '.join(missing_blocks)}. Check the model files under "
                f"{params_dir}."
            )

        return self.normalize_calibration_parameter_blocks(param_blocks)

    def find_state_file(self):
        params_state_path = self._state_source_path()

        if not params_state_path.exists():
            raise FileNotFoundError(
                f"Calibration state source does not exist: {params_state_path}"
            )

        if params_state_path.is_file():
            return self._validate_state_file(params_state_path)

        run_index = params_state_path / "run_index.yml"
        if run_index.is_file():
            return self._state_file_from_run_index(params_state_path, run_index)

        return self._single_unindexed_state_file(params_state_path)

    def _state_source_path(self):
        if self.state_dir is not None:
            return self.state_dir
        if self.ngen_cal_type == "validation":
            return Path(self.output_dir)
        if self.ngen_cal_type == "restart":
            return Path(self.ctx.restart_dir)
        raise ValueError(f"Invalid task_type option: {self.ngen_cal_type}")

    @staticmethod
    def _validate_state_file(state_file):
        state_file = Path(state_file)
        if (
            not state_file.is_file()
            or not state_file.name.endswith("_parameter_df_state.parquet")
        ):
            raise ValueError(
                "Calibration state must be an existing "
                f"*_parameter_df_state.parquet file: {state_file}"
            )

        best_params = state_file.parent / "best_params.txt"
        if not best_params.is_file():
            raise FileNotFoundError(
                f"Calibration state is missing its matching best_params.txt: "
                f"{state_file}"
            )

        try:
            pd.read_parquet(state_file)
        except Exception as error:
            raise ValueError(
                f"Calibration checkpoint is corrupt or incomplete: {state_file}. "
                f"{type(error).__name__}: {error}. Restore a valid checkpoint "
                "or move the interrupted worker directory aside to restart "
                "that experiment from iteration 0."
            ) from error
        return state_file

    @classmethod
    def _complete_state_files(cls, directory):
        directory = Path(directory)
        return [
            state_file
            for state_file in sorted(
                directory.glob("*_parameter_df_state.parquet")
            )
            if (state_file.parent / "best_params.txt").is_file()
        ]

    @staticmethod
    def _resolve_index_path(root, value):
        path = Path(value)
        return path if path.is_absolute() else root / path

    @classmethod
    def _state_file_from_run_index(cls, root, run_index):
        index = yaml.safe_load(run_index.read_text()) or {}
        runs = index.get("runs")
        if not isinstance(runs, list):
            raise ValueError(
                f"Invalid run index: 'runs' must be a list in {run_index}"
            )

        completed_runs = [
            run
            for run in runs
            if isinstance(run, dict)
            and run.get("status") == "completed"
            and run.get("task_type") in {"calibration", "restart"}
        ]
        if not completed_runs:
            raise FileNotFoundError(
                f"No completed calibration or restart run is recorded in "
                f"{run_index}"
            )

        latest_run = completed_runs[-1]
        indexed_state = latest_run.get("state_file")
        if indexed_state:
            state_file = cls._resolve_index_path(root, indexed_state)
            return cls._validate_state_file(state_file)

        worker_dirs = latest_run.get("worker_dirs") or []
        if not isinstance(worker_dirs, list):
            raise ValueError(
                f"Invalid worker_dirs for the latest completed run in {run_index}"
            )

        worker_paths = [
            cls._resolve_index_path(root, worker_dir)
            for worker_dir in worker_dirs
        ]
        return cls.resolve_completed_run_state_file(
            root,
            worker_paths,
            prefer_pso=latest_run.get("algorithm") == "pso",
            run_name=latest_run.get("name", latest_run.get("task_type")),
            run_index=run_index,
        )

    @classmethod
    def resolve_completed_run_state_file(
        cls,
        root,
        worker_dirs,
        *,
        prefer_pso=False,
        run_name="calibration",
        run_index=None,
    ):
        root = Path(root)
        worker_dirs = [Path(worker_dir) for worker_dir in worker_dirs]
        worker_states = [
            state_file
            for worker_dir in worker_dirs
            for state_file in cls._complete_state_files(worker_dir)
        ]

        pso_dirs = [root / "pso_global_best"] + [
            worker_dir / "pso_global_best"
            for worker_dir in worker_dirs
        ]
        pso_states = [
            state_file
            for pso_dir in pso_dirs
            for state_file in cls._complete_state_files(pso_dir)
        ]
        worker_states = sorted(set(worker_states))
        pso_states = sorted(set(pso_states))

        if prefer_pso and len(pso_states) == 1:
            return pso_states[0]
        if len(worker_states) == 1:
            return worker_states[0]
        if len(pso_states) == 1:
            return pso_states[0]

        source = f" in {run_index}" if run_index else ""
        if not worker_states and not pso_states:
            raise FileNotFoundError(
                f"The latest completed run '{run_name}'{source} has no "
                "complete calibration state and best_params.txt pair."
            )

        candidates = worker_states + pso_states
        raise ValueError(
            f"The latest completed run '{run_name}'{source} has "
            f"{len(candidates)} possible calibration states. Refusing to "
            "choose one arbitrarily. Record state_file in run_index.yml or "
            "select the exact state file for restart."
        )

    @classmethod
    def _single_unindexed_state_file(cls, root):
        candidate_dirs = [
            root,
            root / "pso_global_best",
            *sorted(root.glob("*_worker")),
        ]
        candidate_dirs.extend(
            worker_dir / "pso_global_best"
            for worker_dir in sorted(root.glob("*_worker"))
        )
        candidates = [
            state_file
            for directory in candidate_dirs
            for state_file in cls._complete_state_files(directory)
        ]

        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise FileNotFoundError(
                f"No complete calibration state and best_params.txt pair found "
                f"under {root}"
            )

        raise ValueError(
            f"Found {len(candidates)} calibration states under {root}, but no "
            "run_index.yml identifies which completed run should be used. "
            "Restore the run index or explicitly select a state file."
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

        plugins = list(model_config.get("plugins") or [])
        if self.OBSERVATION_PLUGIN not in plugins:
            plugins.append(self.OBSERVATION_PLUGIN)
        model_config["plugins"] = plugins
        model_config.setdefault("plugin_settings", {})[
            "read_obs_data"
        ] = observation_settings

    def write_calib_input_files(self):
        
        conf_dir = self.config_dir
        realization_file =  sorted(
            glob.glob(str(conf_dir / "realization_*.json"))
            )

        if (self.ctx.ensemble_enabled):
            assert len(realization_file) == self.ctx.ensemble_size
        else:
            assert len(realization_file) == 1

        param_blocks = self.load_calibration_parameters()
        strategy = self.build_strategy_config(
            self.ctx.calibration_algorithm,
            self.ctx.optimizer_settings,
        )

        df_new = {
            "general": {
                "strategy": strategy,
                "log": True,
                "start_iteration": 0,
                "iterations": self.ctx.calibration_iterations,
                "random_seed": self.ctx.calibration_random_seed,
                "workdir": self.output_dir.as_posix(),
                "restart": False,
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

                param_values = param_blocks.get(name)
                if param_values is None:
                    raise ValueError(
                        f"Calibration parameter block '{name}' was not found. "
                        "Check the model files under configs/calibration/."
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
            "strategy": "uniform",
            "eval_feature": self.gage_id,
        }

        if self.ctx.ensemble_enabled:
            df_new["model"]["binary"] = (
                os.path.join(self.ctx.sandbox_dir,
                             "src/python/landcover_tiling.py")
                )

            cmd = (
                f"--hydrofabric {self.gpkg_file.as_posix()} "
                f"--realization {realization_file[0]} "
                f"--routing {conf_dir}/troute_config.yaml "
                f"--output-dir {self.output_dir}"
            )
            
            if self.num_procs > 1:
                cmd += f" --partition {self.num_procs}"

            df_new["model"]["args"]  = cmd

        
        if self.num_procs > 1 and self.ctx.ensemble_size == 1:
            df_new["model"]["parallel"] = self.num_procs
            df_new["model"]["partitions"] = self.realization_file_par

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
                'objective': self.ctx.calibration_objective,
                'target': "min",
            }

        # Validation
        if self.ngen_cal_type == "validation":
            df_new["model"]["val_params"] = {
                'sim_start': self.simulation_time['start_time'],
                'evaluation_start': self.evaluation_time['start_time'],
                'evaluation_stop': self.evaluation_time['end_time'],
                'objective': self.ctx.calibration_objective,
                'target': "min",
            }

            df_new["model"]["plugin_settings"] = {
                'ngen_cal_troute_output': {
                    'validation_routing_output': self.troute_output_file
                }
            }

        df_new["model"]["plugins"] = list(self.DEFAULT_PLUGINS)
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
        if self.ctx.calibration_objective_metrics:
            df_new["model"]["plugin_settings"]["composite_objective"] = {
                "metrics": self.ctx.calibration_objective_metrics,
            }
        evaluation_selection = getattr(
            self.ctx,
            "calib_eval_selection",
            None,
        )
        if (
            self.ngen_cal_type in {"calibration", "restart"}
            and evaluation_selection
        ):
            df_new["model"]["plugin_settings"]["objective_evaluation"] = (
                evaluation_selection
            )
        self.configure_observations(
            df_new["model"],
            self.gage_id,
        )
             

        if self.ngen_cal_type in ['restart', 'validation']:


            state_file = self.find_state_file()
            self.selected_state_file = Path(state_file)

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

        config_file = conf_dir / config_fname
        with config_file.open('w') as file:
            yaml.dump(df_new, file, default_flow_style=False, sort_keys=False)
        return config_file
