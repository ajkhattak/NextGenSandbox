############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
# Date    : May 22, 2026
############################################################################################


from dataclasses import dataclass, field
from pathlib import Path

import os
import sys
import yaml
import pandas as pd
import glob
import subprocess

from src.python import helper
from src.python.formulations_registry import (
    get_supported_formulations,
    is_registered_formulation,
    with_default_routing,
)
from src.python.model_instances import build_model_instances

@dataclass
class SandboxContext:

    sandbox_dir: Path
    sandbox_config_path: str
    calib_config_path: str

    mode: str = "conf"
    
    # Optional runtime inputs
    dryrun: bool = False

    # Internal state
    sandbox_config: dict = field(default_factory=dict)
    model_registry: dict = field(default_factory=dict)

    def __post_init__(self):
        self.colors = helper.colors()
        self.sandbox_dir = Path(self.sandbox_dir)

    def initialize(self):
        self.load_config()
        self.validate_formulation()
        self.load_gpkg_dirs()
        self.build_instances()
        self.prepare_model_instances()
        self.prepare_forcing_files()
        self.resolve_output_dirs()

    def resolve_output_dirs(self):
        self.output_dirs = [
            self.output_dir / self.output_dir_name(gpkg_dir)
            for gpkg_dir in self.gpkg_dirs
        ]

    def output_dir_name(self, gpkg_dir):
        name = Path(gpkg_dir).name
        if self.sim_name_suffix:
            return f"{name}_{self.sim_name_suffix}"
        return name

    def load_config(self):

        with open(self.sandbox_config_path, "r") as file:
            self.sandbox_config = yaml.safe_load(file)

        self.input_dir = self.sandbox_config["general"].get("input_dir")

        self.output_dir = Path(self.sandbox_config["general"].get("output_dir"))

        self.load_formulation_config()

        self.load_forcing_config()

        self.load_simulation_config()
        
        self.load_launcher_config()
        

    def load_formulation_config(self):
        # Formulation block
        dformul = self.sandbox_config["formulation"]
        
        self.ngen_dir = Path(os.environ.get("NGEN_DIR"))
        
        self.formulation = (
            dformul["models"]
            .upper()
            .replace(" ", "")
        )
        
        self.model_instances = dformul.get("model_instances", {})
        
        self.clean = self.process_clean_input_param(dformul.get("clean", "none"))

        self.verbosity = dformul.get("verbosity", 0)
        
        self.schema_type = dformul.get("schema_type", "noaa-owp")

    def load_forcing_config(self):
        # Forcing block
        dforcing = self.sandbox_config["forcings"]

        self.forcing_time = dforcing["time"]

        self.forcing_format = dforcing.get("format", ".nc")

        forcing_start_yr = pd.Timestamp(self.forcing_time["start_time"]).year

        forcing_end_yr = pd.Timestamp(self.forcing_time["end_time"]).year + 1

        forcing_dir = os.path.join(
            self.input_dir,
            "{*}",
            f"data/forcing/{forcing_start_yr}_to_{forcing_end_yr}"
        )

        self.forcing_dir = dforcing.get("forcing_dir", forcing_dir)

        self.domain = dforcing.get("domain", "conus")

        self.is_corrected_forcing = dforcing.get("is_corrected_forcing", True)

        self.is_netcdf_forcing = (self.forcing_format != ".csv")


    def load_simulation_config(self):
        # Simulation block
        dsim = self.sandbox_config["simulation"]

        self.task_type = (dsim.get("task_type", "control").lower())

        if "LSTM" in self.formulation:
            print("INFO: LSTM formulation -- setting task_type to control")
            self.task_type = "control"

        self.gage_ids = self.load_gage_ids(dsim.get("gage_ids_input"))

        self.sim_name_suffix = dsim.get("sim_name_suffix") or None

        self.disable_divide_output = dsim.get("disable_divide_output", True)

        if self.task_type in ["calibration", "calibvalid", "restart"]:

            if "calibration_time" not in dsim or not isinstance(dsim["calibration_time"], dict):
                raise ValueError("calibration_time missing or invalid.")

            self.simulation_time = dsim["calibration_time"]
            self.calib_eval_time  = dsim["calib_eval_time"]

            if self.task_type == "calibvalid":
                if "validation_time" not in dsim or not isinstance(dsim["validation_time"], dict):
                    raise ValueError("validation_time missing or invalid.")

                self.validation_time = dsim["validation_time"]
                self.valid_eval_time = dsim["valid_eval_time"]
            
        elif self.task_type == "validation":

            if "validation_time" not in dsim or not isinstance(dsim["validation_time"], dict):
                raise ValueError("validation_time missing or invalid.")

            self.simulation_time = dsim["validation_time"]
            self.validation_time = dsim["validation_time"]
            self.valid_eval_time = dsim["valid_eval_time"]

        elif self.task_type == "control":
            
            if "simulation_time" not in dsim or not isinstance(dsim["simulation_time"], dict):
                raise ValueError("task_type CONTROL: simulation_time missing or invalid.")
            
            self.simulation_time = dsim["simulation_time"]

        else:
            raise ValueError("Invalid task_type provided: valid options are [control, calibration, validation, calibvalid, restart]")


        
        self.restart_dir = "./"
        if self.task_type == 'restart':
            self.restart_dir = dsim.get('restart_dir')
            if self.restart_dir is None:
                raise ValueError("task_type is restart, however, restart_dir is None. It must be set to a valid directory.")
            if not self.restart_dir:
                raise FileNotFoundError(f"restart_dir does not exist, provided {self.restart_dir}.")
            
        # Ensemble block
        densemble = dsim.get("ensemble") or None

        if densemble:
            self.ensemble_enabled = bool(densemble.get('enabled'))

            if self.ensemble_enabled:
                
                self.ensemble_models = (
                    self.formulation
                    .replace("T-ROUTE", "")
                    .replace(" ,", ",")
                    .strip(", ")
                    .strip()
                )

                self.ensemble_calib_params_groups = densemble.get('calib_params_groups')

            else:

                self.ensemble_size = 1
                self.ensemble_models = []

        else:

            self.ensemble_enabled = False
            self.ensemble_models = []

        self.ensemble_size    = len([m.strip() for m in self.ensemble_models.split(",")]) if self.ensemble_enabled else 1

    def load_launcher_config(self):
        # Sandbox launcher block
        dlauncher = self.sandbox_config.get("sandbox_launcher") or None

        if dlauncher:

            self.sb_launcher = dlauncher.get("exp_info", False)
            self.exp_info_dir = dlauncher.get("exp_info_dir") or None

            if self.exp_info_dir is None:
                raise ValueError("sandbox_launcher is True, but exp_info_dir not provided")
        else:
            self.sb_launcher = False

    def validate_formulation(self):
        if not is_registered_formulation(self.formulation):
            supported = "\n".join(
                f"  - {formulation}"
                for formulation in get_supported_formulations()
            )

            message = (
                f"\nUnsupported formulation: {self.formulation}\n"
                f"Supported formulations:\n{supported}\n"
                "[INFO]: Formulations that omit T-ROUTE are allowed, however, all other formulation components must be specified exactly as supported."
            )

            if any(model in self.formulation.split(",") for model in ["CFE-S", "CFE-X"]):
                message += (
                    "\n[INFO]: Use CFE as the formulation component. "
                    "To use CFE-X, set formulation.model_instances.CFE in the configuration file."
                )

            raise ValueError(message)

        self.formulation = with_default_routing(self.formulation)

    def build_instances(self):

        self.model_registry = build_model_instances(
            formulation=self.formulation,
            model_instances=self.model_instances
        )

    def get_model_instances(self, model_name):
        """
        Return all configured instances for a model.
        
        Example:
        get_model_instances("CFE")
        """
        
        return self.model_registry.get(model_name.upper(), [])

    def get_model_instance_names(self, model_name):
        return [
            instance.name
            for instance in self.get_model_instances(model_name)
        ]
    
    def prepare_model_instances(self):

        ML_MODELS = ["LSTM", "DHBV"]

        if not hasattr(self, "model_registry"):
            return

        for model_name, instances in self.model_registry.items():

            if model_name == "T-ROUTE":
                helper.ensure_troute_available(self.ngen_dir)
                continue

            for instance in instances:

                instance.config_dir = f"configs/{instance.name}" # full path is added in the model plugins

                if model_name in ML_MODELS:
                    continue

                # Resolve shared library path or search directory
                if getattr(instance, "library_file", None):
                    library_root = Path(instance.library_file)
                else:
                    library_root = Path(self.ngen_dir) / "extern" / instance.repo_name / instance.repo_name
                
                if model_name in ["SLOTH", "TOPMODEL"]:
                     library_root = Path(self.ngen_dir) / "extern" / instance.repo_name

                if not library_root.exists():
                    raise FileNotFoundError(
                        f"library path for {model_name} missing: {library_root}"
                    )


                # Search recursively for shared libraries
                pattern = "lib*.so" if sys.platform.startswith("linux") else "lib*.dylib"
                if library_root.is_file():
                    matches = [library_root]
                else:
                    matches = list(library_root.rglob(pattern))

                if not matches:
                    raise FileNotFoundError(f"shared library for {model_name} missing under {library_root}")


                # Prefer shortest / unversioned library
                matches = sorted(matches, key=lambda x: len(x.name))

                # Handle special cases
                if instance.repo_name in ['noah-owp-modular',"snow17"]:
                    if instance.repo_name == "noah-owp-modular":
                        preferred = [m for m in matches if "surfacebmi" in m.name]
                        if preferred:
                            matches = preferred
                    if instance.repo_name == "snow17":
                        preferred = [m for m in matches if "snow17" in m.name]
                        if preferred:
                            matches = preferred

                instance.library_file = str(matches[0])
                

    def load_gage_ids(self, gage_ids_input):

        if gage_ids_input is None:
            raise TypeError("gage_ids_input must be provided")

        if (isinstance(gage_ids_input, str)
            and gage_ids_input.lower().endswith(".csv")
            ):

            path = Path(gage_ids_input)

            if not path.is_file():
                raise FileNotFoundError(
                    f"gage_ids file not found: {path}"
                )

            df = pd.read_csv(path, dtype=str)

            if "gage_id" not in df.columns:
                raise ValueError("CSV must contain 'gage_id' column")

            return df["gage_id"].tolist()

        # Single ID
        if isinstance(gage_ids_input, str):
            return [gage_ids_input]

        # Multiple IDs
        if isinstance(gage_ids_input, (list, tuple, set)):
            return [str(x) for x in gage_ids_input]

        raise TypeError(
            "gage_ids_input must be a CSV "
            "path, string ID, or list"
        )

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

        if not self.gpkg_dirs:
            raise FileNotFoundError(f"Geopackage file(s) missing for gage(s) {gage_ids} in directory {self.input_dir}")


    def prepare_forcing_files(self):
        self.forcing_files = []

        if self.forcing_format == ".nc":

            if "{*}" in self.forcing_dir:
                for g in self.gpkg_dirs:
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

                    self.forcing_files.append(forcing_file)
            else:
                if not Path(self.forcing_dir).exists():
                    raise ValueError(f"Forcing directory {self.forcing_dir} does not exist.")

                if not Path(self.forcing_dir).is_dir():
                    forcing_file = self.forcing_dir
                else:
                    if self.is_corrected_forcing:
                        forcing_file = glob.glob(f"{self.forcing_dir}/*_corrected.nc")[0]
                    else:
                        nc_file = glob.glob(f"{self.forcing_dir}/*.nc")
                        forcing_file = [f for f in nc_file if not "_corrected" in f][0]

                self.forcing_files.append(forcing_file)
        else:
            if "{*}" in self.forcing_dir:
                for g in self.gpkg_dirs:
                    forcing_dir_local = self.forcing_dir
                    fdir = Path(forcing_dir_local.replace("{*}", Path(g).name))

                    if not fdir.exists():
                        raise ValueError(f"Forcing directory {fdir} does not exist.")
                    if not fdir.is_dir():
                        raise ValueError("forcing format is .csv, so '{fdir}' should point to a directory and not file.")

                    self.forcing_files.append(fdir)

    
    def process_clean_input_param(self, clean):
        clean_lst = []
        if isinstance(clean, str):
            clean_lst = [clean]
        elif isinstance(clean, list):
            clean_lst.extend(clean)
        return clean_lst
