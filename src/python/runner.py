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
import shlex
from pathlib import Path
import shutil
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

    def subprocess_environment(self) -> dict[str, str]:
        """Return an isolated environment for ngen and ngen-cal processes."""
        run_env = os.environ.copy()

        if self.os_name == "Linux":
            sandbox_env = Path(os.environ.get("SANDBOX_ENV", sys.prefix))
            library_dir = sandbox_env / "lib"
            cxx_runtime = library_dir / "libstdc++.so.6"
            if cxx_runtime.is_file():
                run_env["LD_LIBRARY_PATH"] = self._prepend_environment_path(
                    str(library_dir),
                    run_env.get("LD_LIBRARY_PATH"),
                )
                run_env["LD_PRELOAD"] = self._prepend_environment_path(
                    str(cxx_runtime),
                    run_env.get("LD_PRELOAD"),
                )

        if self.os_name == "Darwin":
            run_env["PYTHONEXECUTABLE"] = (
                shutil.which("python") or sys.executable
            )

        return run_env

    @staticmethod
    def _prepend_environment_path(
        value: str,
        existing: str | None,
    ) -> str:
        entries = [entry for entry in (existing or "").split(os.pathsep) if entry]
        entries = [entry for entry in entries if entry != value]
        return os.pathsep.join([value, *entries])


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
            self.ctx.forcing_files,
            strict=True,
        )
        for gage_id, gpkg_resource, o_dir, forcing_file in resources:

            if not os.path.isdir(o_dir):
                raise FileNotFoundError(f"directory {o_dir} does not exist, this dir is created at the config generation step")

            os.chdir(o_dir)

            print("cwd: ", os.getcwd())
            print("input_resource: ", gpkg_resource)
            print("output_dir: ", o_dir)

            gpkg_file = find_gpkg_file(gpkg_resource)
            config_dir = helper.configuration_dir(o_dir, "control")

            self.validate_configuration_profile(
                config_dir=config_dir,
                task_type="control",
                gage_id=gage_id,
                simulation_time=self.ctx.simulation_time,
                gpkg_file=gpkg_file,
                forcing_file=forcing_file,
            )

            realization = glob.glob(str(config_dir / "realization_*.json"))

            if len(realization) != 1:
                raise RuntimeError(
                    f"Expected exactly one realization file in {config_dir}, "
                    f"found {len(realization)}: {realization}"
                )
            realization = realization[0]

            # defaults to serial run no-mpi mode
            run_cmd = [
                str(ngen_exe),
                str(gpkg_file),
                "all",
                str(gpkg_file),
                "all",
                str(realization),
            ]

            partitioning = self.ctx.sandbox_config.get("simulation", {}).get("partitioning", {})
            file_par, num_cpus = helper.prepare_basin_partitioning(self.ctx.sandbox_dir, gpkg_file,
                                                                   partitioning,
                                                                   config_dir=config_dir)

            self.file_par = file_par
            self.num_procs = int(num_cpus)

            if self.mpirun_exists and self.num_procs > 1:
                # Use MPI only when the partitioning request needs multiple processes.

                run_cmd = [
                    "mpirun",
                    "-np",
                    str(self.num_procs),
                    str(ngen_exe),
                    str(gpkg_file),
                    "all",
                    str(gpkg_file),
                    "all",
                    str(realization),
                    str(self.file_par),
                ]

            run_env = self.subprocess_environment()
            command_text = shlex.join(run_cmd)
            if self.os_name == "Darwin":
                command_text = (
                    "PYTHONEXECUTABLE="
                    f"{shlex.quote(run_env['PYTHONEXECUTABLE'])} "
                    f"{command_text}"
                )

            if not self.ctx.dryrun:
                print(f"Running basin {gage_id} on cores {self.num_procs} ********", flush=True)
                print(f"Run command: {command_text}", flush=True)
                result = subprocess.run(run_cmd, env=run_env)
                if result.returncode != 0:
                    raise RuntimeError(
                        f"NextGen run failed for gage {gage_id} with exit code "
                        f"{result.returncode}."
                    )
            else:
                print(f"Dry run command: {command_text}")


    def run_ngen_with_calibration(self, dirs):
        id = dirs[0]
        i_dir = dirs[1]
        o_dir = dirs[2]
        forcing_file = dirs[3]

        if not os.path.isdir(o_dir):
            raise FileNotFoundError(f"directory {o_dir} does not exist, this dir is created at the config generation step")

        os.chdir(o_dir)

        print("cwd: ", os.getcwd())
        print("input_dir: ", i_dir)
        print("output_dir: ", o_dir)

        gpkg_file = find_gpkg_file(i_dir)
        gpkg_name = gpkg_file.stem
        partition_task = (
            "calibration"
            if self.ctx.task_type == "calibvalid"
            else self.ctx.task_type
        )
        partition_config_dir = helper.configuration_dir(
            o_dir,
            partition_task,
        )

        partitioning = self.ctx.sandbox_config.get("simulation", {}).get("partitioning", {})
        file_par, num_cpus = helper.prepare_basin_partitioning(self.ctx.sandbox_dir, gpkg_file,
                                                               partitioning,
                                                               config_dir=partition_config_dir)

        self.file_par = file_par

        self.num_procs = int(num_cpus)

        if self.ctx.task_type in ['calibration', 'calibvalid', 'restart']:
            mode = 'calibration' if self.ctx.task_type == 'calibvalid' else self.ctx.task_type
            self.run_ngen_experiment(
                mode,
                gpkg_file,
                o_dir,
                self.file_par,
                id,
                forcing_file=forcing_file,
            )

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
                    forcing_file=forcing_file,
                    validation_period=validation_period,
                )


    def run_ngen_experiment(
        self,
        mode,
        gpkg_file,
        o_dir,
        file_par,
        id,
        forcing_file,
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

        if mode == "validation":
            validation_name = validation_period.get("name", "validation")
            config_dir = helper.configuration_dir(
                o_dir,
                "validation",
                validation_name=validation_name,
                multiple_validations=(len(self.validation_periods()) > 1),
            )
        else:
            validation_name = None
            config_dir = helper.configuration_dir(o_dir, ngen_cal_type)

        self.validate_configuration_profile(
            config_dir=config_dir,
            task_type=ngen_cal_type,
            validation_name=validation_name,
            gage_id=id,
            simulation_time=sim_time,
            gpkg_file=gpkg_file,
            forcing_file=forcing_file,
        )

        print(
            f"Running {mode} for gage {id} on cores "
            f"{self.num_procs} ********",
            flush=True,
        )

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
            ngen_cal_type        = ngen_cal_type,
            gage_id              = id,
            state_dir            = restart_dir if mode == "restart" else o_dir,
            config_dir           = config_dir,
        )

        config_file = ConfigGen.write_calib_input_files()

        if mode not in {"validation", "calibration", "restart"}:
            raise ValueError(f"Unsupported mode (ngen_cal_type): {mode}")

        # Run command
        if mode in ['calibration', 'restart']:
            run_command = [
                sys.executable,
                "-m",
                "ngen.cal",
                str(config_file),
            ]

        elif mode == 'validation':
            run_command = [
                sys.executable,
                str(Path(self.ctx.sandbox_dir) / "src/python/validation.py"),
                "-config",
                str(config_file),
            ]

            if self.ctx.ensemble_enabled:
                run_command.extend(
                    [
                        "-routing",
                        str(config_dir / "troute_config.yaml"),
                    ]
                )

        command_text = shlex.join(run_command)
        before_workers = self.worker_dirs(o_dir)
        if not self.ctx.dryrun:
            result = subprocess.run(
                run_command,
                env=self.subprocess_environment(),
            )
            after_workers = self.worker_dirs(o_dir)
            new_workers = after_workers - before_workers
            state_file = None
            state_error = None
            if result.returncode == 0 and mode in {"calibration", "restart"}:
                try:
                    if mode == "restart" and not new_workers:
                        if ConfigGen.selected_state_file is None:
                            raise FileNotFoundError(
                                "Restart did not retain its selected state file."
                            )
                        state_file = configuration.ConfigurationCalib._validate_state_file(
                            ConfigGen.selected_state_file
                        )
                    else:
                        state_file = (
                            configuration.ConfigurationCalib
                            .resolve_completed_run_state_file(
                                o_dir,
                                new_workers,
                                prefer_pso=(
                                    self.ctx.calibration_algorithm == "pso"
                                ),
                                run_name=validation_name or mode,
                            )
                        )
                except (FileNotFoundError, ValueError) as error:
                    state_error = error

            self.write_run_index(
                output_dir=o_dir,
                gage_id=id,
                mode=mode,
                name=validation_name or mode,
                config_file=config_file,
                command=command_text,
                simulation_time=sim_time,
                evaluation_time=eval_time,
                worker_dirs=new_workers,
                returncode=result.returncode,
                status=(
                    "completed"
                    if result.returncode == 0 and state_error is None
                    else "failed"
                ),
                algorithm=(
                    self.ctx.calibration_algorithm
                    if mode in {"calibration", "restart"}
                    else None
                ),
                state_file=state_file,
            )
            if result.returncode != 0:
                raise RuntimeError(f"{mode.capitalize()} step failed...")
            if state_error is not None:
                raise RuntimeError(
                    f"{mode.capitalize()} completed, but its calibration "
                    f"state could not be identified: {state_error}"
                ) from state_error
        else:
            print(f"Dry run command: {command_text}")
            self.write_run_index(
                output_dir=o_dir,
                gage_id=id,
                mode=mode,
                name=validation_name or mode,
                config_file=config_file,
                command=command_text,
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

    @staticmethod
    def safe_filename(value):
        return helper.safe_path_name(value)

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
        algorithm=None,
        state_file=None,
    ):
        index_file = Path(output_dir) / "run_index.yml"
        if index_file.exists():
            index = yaml.safe_load(index_file.read_text()) or {}
        else:
            index = {}

        runs = index.setdefault("runs", [])
        run = {
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
        if algorithm is not None:
            run["algorithm"] = algorithm
        if state_file is not None:
            run["state_file"] = str(state_file)
        runs.append(run)

        with index_file.open("w") as file:
            yaml.safe_dump(index, file, default_flow_style=False, sort_keys=False)

    def validate_configuration_profile(
        self,
        *,
        config_dir,
        task_type,
        gage_id,
        simulation_time,
        gpkg_file,
        forcing_file,
        validation_name=None,
    ):
        helper.validate_configuration_manifest(
            config_dir,
            task_type=task_type,
            validation_name=validation_name,
            gage_id=gage_id,
            formulation_models=self.ctx.formulation_models,
            simulation_time=simulation_time,
            hydrofabric=gpkg_file,
            forcing=forcing_file,
        )
        self.validate_configs(config_dir)

    def validate_configs(self, config_dir):
        config_dir = Path(config_dir)
            
        for model_name, instances in self.ctx.model_registry.items():
            
            if model_name in {"T-ROUTE"} or model_name == "SLOTH":
                continue

            for instance in instances:

                model_dir = config_dir / instance.name
                
                if (not model_dir.exists()):
                    raise FileNotFoundError(model_dir)

        realization_files = sorted(config_dir.glob("realization_*.json"))
        expected_realizations = (
            self.ctx.ensemble_size if self.ctx.ensemble_enabled else 1
        )
        if len(realization_files) != expected_realizations:
            raise RuntimeError(
                f"Expected {expected_realizations} realization file(s) in "
                f"{config_dir}, found {len(realization_files)}: "
                f"{realization_files}"
            )

        if "T-ROUTE" in self.ctx.formulation_models:
            troute_config = config_dir / "troute_config.yaml"
            if not troute_config.is_file():
                raise FileNotFoundError(troute_config)
