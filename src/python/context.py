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

from src.python import helper
from src.python.forcing_files import (
    prepare_rechunked_forcing_file,
    select_netcdf_forcing_file,
)
from src.python.formulations_registry import (
    get_supported_formulations,
    is_registered_formulation,
    with_default_routing,
)
from src.python.gages import load_general_gages, resolve_step_gages
from src.python.model_instances import build_model_instances
from src.python.observations import ObservationLoader
from src.python.resource_paths import (
    HYDROFABRIC_DIR,
    forcing_dir_for_resource,
    has_gage_placeholder,
    has_gpkg_file,
    render_gage_path,
    resource_hydrofabric_dir,
    resource_id,
)
from src.python.time_windows import (
    normalize_forcing_time_config,
    normalize_simulation_time_config,
)

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
        self.validate_observations()
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
        name = resource_id(gpkg_dir)
        if self.sim_name_suffix:
            return f"{name}_{self.sim_name_suffix}"
        return name

    def load_config(self):

        with open(self.sandbox_config_path, "r") as file:
            self.sandbox_config = yaml.safe_load(file)

        self.input_dir = self.sandbox_config["general"].get("input_dir")

        self.output_dir = Path(self.sandbox_config["general"].get("output_dir"))

        self.resource_layout = self.sandbox_config["general"].get(
            "resource_layout",
            "gage",
        )
        if self.resource_layout not in {"gage", "resource"}:
            raise ValueError("general.resource_layout must be one of: gage, resource")

        self.project_gages = load_general_gages(self.sandbox_config)

        self.load_formulation_config()

        self.load_forcing_config()

        self.load_simulation_config()

        self.load_observations_config()


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

        self.forcing_time = normalize_forcing_time_config(dforcing["time"])

        self.forcing_format = dforcing.get("format", ".nc")

        forcing_start_yr = pd.Timestamp(self.forcing_time["start_time"]).year

        forcing_end_yr = pd.Timestamp(self.forcing_time["end_time"]).year + 1
        self.forcing_year_dir = f"{forcing_start_yr}_to_{forcing_end_yr}"

        forcing_dir = str(
            forcing_dir_for_resource(
                self.input_dir,
                "<gage_id>",
                forcing_start_yr,
                forcing_end_yr,
                self.resource_layout,
            )
        )

        self.forcing_dir_is_configured = "forcing_dir" in dforcing
        self.forcing_dir = dforcing.get("forcing_dir", forcing_dir)

        self.domain = dforcing.get("domain", "conus")

        self.is_corrected_forcing = dforcing.get("is_corrected_forcing", True)

        self.is_netcdf_forcing = (self.forcing_format != ".csv")

        self.rechunk_forcing = dforcing.get("rechunk", True)

    def load_observations_config(self):
        observations = self.sandbox_config.get("observations", {}) or {}

        if not isinstance(observations, dict):
            raise TypeError("observations must be a mapping of observation names")

        self.observation_objective = observations.get("objective")
        if self.observation_objective is not None and (
            not isinstance(self.observation_objective, str)
            or not self.observation_objective.strip()
        ):
            raise ValueError("observations.objective must be a non-empty string")

        self.observations = {
            name: config
            for name, config in observations.items()
            if name != "objective"
        }

    @staticmethod
    def validate_time_window(name, window):
        if not isinstance(window, dict):
            raise ValueError(f"{name} missing or invalid.")

        missing = [
            key for key in ("start_time", "end_time")
            if key not in window
        ]
        if missing:
            raise ValueError(
                f"{name} missing required field(s): {', '.join(missing)}"
            )

        try:
            start_time = pd.Timestamp(window["start_time"])
            end_time = pd.Timestamp(window["end_time"])
        except Exception as exc:
            raise ValueError(
                f"{name} has invalid start_time/end_time values."
            ) from exc

        if pd.isna(start_time) or pd.isna(end_time):
            raise ValueError(f"{name} has invalid start_time/end_time values.")

        if start_time > end_time:
            raise ValueError(
                f"{name}.start_time must be less than or equal to "
                f"{name}.end_time ({window['start_time']} > "
                f"{window['end_time']})."
            )

        return start_time, end_time

    @classmethod
    def validate_time_subset(
        cls,
        parent_name,
        parent_window,
        child_name,
        child_window,
    ):
        parent_start, parent_end = cls.validate_time_window(
            parent_name,
            parent_window,
        )
        child_start, child_end = cls.validate_time_window(
            child_name,
            child_window,
        )

        if child_start < parent_start or child_end > parent_end:
            raise ValueError(
                f"{child_name} must be within {parent_name}. "
                f"{child_name}: {child_start} to {child_end}; "
                f"{parent_name}: {parent_start} to {parent_end}."
            )

    def validate_observations(self):
        missing_outputs = {
            config["simulated"]
            for config in self.observations.values()
            if isinstance(config, dict)
            and config.get("simulated")
            and config["simulated"] not in self.divide_output_variables
        }
        if missing_outputs:
            raise ValueError(
                "Observation simulated variables must also be listed in "
                "simulation.outputs.divide_variables: "
                f"{', '.join(sorted(missing_outputs))}"
            )

        loader = ObservationLoader(
            observations=self.observations,
            config_dir=Path(self.sandbox_config_path).resolve().parent,
        )
        self.observation_files = loader.validate(self.gage_ids)
        self.observation_units = loader.units


    def load_simulation_config(self):
        # Simulation block
        dsim = self.sandbox_config["simulation"]

        self.task_type = (dsim.get("task_type", "control").lower())

        if "LSTM" in self.formulation:
            print("INFO: LSTM formulation -- setting task_type to control")
            self.task_type = "control"

        self.gage_ids = resolve_step_gages(
            project_gages=self.project_gages,
            step_value=dsim.get("gages"),
            field_name="simulation.gages",
        )

        self.sim_name_suffix = dsim.get("sim_name_suffix") or None

        outputs = dsim.get("outputs", {}) or {}
        if not isinstance(outputs, dict):
            raise TypeError("simulation.outputs must be a mapping")

        calibration_outputs = outputs.get("calibration", {}) or {}
        if not isinstance(calibration_outputs, dict):
            raise TypeError("simulation.outputs.calibration must be a mapping")

        self.calibration_output_retention = str(
            calibration_outputs.get("retention", "best")
        ).lower()
        if self.calibration_output_retention not in {"best", "all"}:
            raise ValueError(
                "simulation.outputs.calibration.retention must be one of: "
                "best, all"
            )

        self.divide_output_variables = outputs.get("divide_variables", {}) or {}
        if not isinstance(self.divide_output_variables, dict) or not all(
            isinstance(variable, str)
            and variable.strip()
            and isinstance(settings, dict)
            and isinstance(settings.get("units"), str)
            and settings["units"].strip()
            for variable, settings in self.divide_output_variables.items()
        ):
            raise ValueError(
                "simulation.outputs.divide_variables must be a mapping of "
                "output variable names to settings containing non-empty units"
            )

        if "sandbox_launcher" in self.sandbox_config:
            raise ValueError(
                "sandbox_launcher is no longer supported. Use "
                "simulation.outputs.metadata instead."
            )

        metadata_outputs = outputs.get("metadata", {}) or {}
        if not isinstance(metadata_outputs, dict):
            raise TypeError("simulation.outputs.metadata must be a mapping")

        self.metadata_enabled = bool(metadata_outputs.get("enabled", False))
        self.metadata_index_dir = metadata_outputs.get("index_dir")
        self.metadata_run_file = metadata_outputs.get("run_file", "run_metadata.yml")

        if self.metadata_enabled:
            if not isinstance(self.metadata_run_file, str) or not self.metadata_run_file.strip():
                raise ValueError(
                    "simulation.outputs.metadata.run_file must be a non-empty string"
                )
            if self.metadata_index_dir is not None and (
                not isinstance(self.metadata_index_dir, str)
                or not self.metadata_index_dir.strip()
            ):
                raise ValueError(
                    "simulation.outputs.metadata.index_dir must be a non-empty string "
                    "when provided"
                )

        if "time" in dsim:
            config_dir = None
            if getattr(self, "sandbox_config_path", None):
                config_dir = Path(self.sandbox_config_path).resolve().parent
            normalize_simulation_time_config(
                dsim,
                self.task_type,
                config_dir=config_dir,
            )

        if self.task_type in ["calibration", "calibvalid", "restart"]:

            if "calib_eval_time" not in dsim or not isinstance(dsim["calib_eval_time"], dict):
                raise ValueError("calib_eval_time missing or invalid.")

            self.validate_time_subset(
                "calibration_time",
                dsim.get("calibration_time"),
                "calib_eval_time",
                dsim["calib_eval_time"],
            )

            self.simulation_time = dsim["calibration_time"]
            self.calib_eval_time  = dsim["calib_eval_time"]

            if self.task_type == "calibvalid":
                self.load_validation_periods(dsim)

        elif self.task_type == "validation":
            self.load_validation_periods(dsim)
            self.simulation_time = self.validation_time

        elif self.task_type == "control":

            self.validate_time_window(
                "task_type CONTROL: simulation_time",
                dsim.get("simulation_time"),
            )

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

    def load_validation_periods(self, dsim):
        validation_periods = dsim.get("validation_periods")
        if validation_periods is None:
            if "valid_eval_time" not in dsim or not isinstance(dsim["valid_eval_time"], dict):
                raise ValueError("valid_eval_time missing or invalid.")
            self.validate_time_subset(
                "validation_time",
                dsim.get("validation_time"),
                "valid_eval_time",
                dsim["valid_eval_time"],
            )
            validation_periods = [
                {
                    "name": "validation",
                    "simulation_time": dsim.get("validation_time"),
                    "evaluation_time": dsim["valid_eval_time"],
                }
            ]

        if not isinstance(validation_periods, list) or not validation_periods:
            raise ValueError("validation_periods must be a non-empty list")

        for index, period in enumerate(validation_periods):
            if not isinstance(period, dict):
                raise ValueError(f"validation_periods[{index}] must be a mapping")
            if "simulation_time" not in period or "evaluation_time" not in period:
                raise ValueError(
                    f"validation_periods[{index}] must include simulation_time "
                    "and evaluation_time"
                )
            self.validate_time_subset(
                f"validation_periods[{index}].simulation_time",
                period["simulation_time"],
                f"validation_periods[{index}].evaluation_time",
                period["evaluation_time"],
            )

        self.validation_periods = validation_periods
        first_validation = validation_periods[0]
        self.validation_time = first_validation["simulation_time"]
        self.valid_eval_time = first_validation["evaluation_time"]

    @staticmethod
    def parse_formulation_models(formulation):
        return [
            model.strip()
            for model in formulation.split(",")
            if model.strip()
        ]

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

            if any(
                model in self.parse_formulation_models(self.formulation)
                for model in ["CFE-S", "CFE-X"]
            ):
                message += (
                    "\n[INFO]: Use CFE as the formulation component. "
                    "To use CFE-X, set formulation.model_instances.CFE in the configuration file."
                )

            raise ValueError(message)

        self.formulation = with_default_routing(self.formulation)
        self.formulation_models = self.parse_formulation_models(self.formulation)

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


    def load_gpkg_dirs(self):
        if self.resource_layout == "resource":
            self.gpkg_dirs = sorted(resource_hydrofabric_dir(self.input_dir).glob("*.gpkg"))
        else:
            # Get all subdirectories inside input_dir
            all_dirs = glob.glob(os.path.join(self.input_dir, '*/'), recursive=True)

            # Filter directories that have a hydrofabric/geopackage resource.
            self.gpkg_dirs = [
                Path(g) for g in all_dirs
                if has_gpkg_file(g)
            ]

        gage_ids = self.gage_ids or []  # Default to empty list [] if None

        # If it's a single string, convert to list
        if isinstance(gage_ids, str):
            gage_ids = [gage_ids]
        elif not isinstance(gage_ids, list):
            raise TypeError(f"gage_ids must be a string, list, or None, but got {type(self.gage_ids).__name__}")


        if gage_ids:
            resources_by_gage = {}
            duplicate_gages = set()
            expected_gages = set(gage_ids)

            for resource in self.gpkg_dirs:
                gage_id = self._resource_gage_id(resource)
                if gage_id not in expected_gages:
                    continue
                if gage_id in resources_by_gage:
                    duplicate_gages.add(gage_id)
                resources_by_gage[gage_id] = resource

            if duplicate_gages:
                raise ValueError(
                    "Multiple geopackage resources found for gage(s): "
                    f"{', '.join(sorted(duplicate_gages))}"
                )

            missing_gages = [
                gage_id for gage_id in gage_ids
                if gage_id not in resources_by_gage
            ]
            if missing_gages:
                raise FileNotFoundError(self._missing_gpkg_message(missing_gages))

            self.gpkg_dirs = [resources_by_gage[gage_id] for gage_id in gage_ids]

        if not self.gpkg_dirs:
            raise FileNotFoundError(self._missing_gpkg_message(gage_ids))

    def _resource_gage_id(self, resource):
        if self.resource_layout == "resource":
            return resource_id(resource)
        return resource_id(Path(resource))

    def _missing_gpkg_message(self, gage_ids):
        input_dir = Path(self.input_dir)
        gage_text = ", ".join(gage_ids) if gage_ids else "all configured gages"

        if self.resource_layout == "resource":
            expected = input_dir / HYDROFABRIC_DIR
            message = (
                f"Geopackage file(s) missing for gage(s) {gage_text}. "
                f"With general.resource_layout: resource, expected files under "
                f"{expected}/, for example {expected / 'gage_<gage_id>.gpkg'}."
            )
            alternate = [
                input_dir / gid / HYDROFABRIC_DIR / f"gage_{gid}.gpkg"
                for gid in gage_ids
            ]
            if any(path.exists() for path in alternate):
                message += (
                    " Matching geopackages were found in the gage-layout "
                    "location. Set general.resource_layout: gage or move the "
                    "geopackages to the resource-layout hydrofabric directory."
                )
            return message

        examples = [
            input_dir / "<gage_id>" / HYDROFABRIC_DIR / "gage_<gage_id>.gpkg",
            input_dir / "<gage_id>" / "data" / "gage_<gage_id>.gpkg",
        ]
        message = (
            f"Geopackage file(s) missing for gage(s) {gage_text}. "
            f"With general.resource_layout: gage, expected files under "
            f"{examples[0]} or {examples[1]}."
        )
        resource_dir = resource_hydrofabric_dir(input_dir)
        if any((resource_dir / f"gage_{gid}.gpkg").exists() for gid in gage_ids):
            message += (
                " Matching geopackages were found in the resource-layout "
                "location. Set general.resource_layout: resource or move the "
                "geopackages under per-gage directories."
            )
        return message


    def prepare_forcing_files(self):
        self.forcing_files = []

        if self.forcing_format == ".nc":

            if has_gage_placeholder(self.forcing_dir):
                for g in self.gpkg_dirs:
                    forcing_dir_local = self.forcing_dir
                    forcing_path = render_gage_path(
                        forcing_dir_local,
                        resource_id(g),
                    )
                    forcing_file = self._resolve_netcdf_forcing_file(g, forcing_path)

                    self.forcing_files.append(str(forcing_file))
            else:
                forcing_file = self._resolve_single_netcdf_forcing_file()
                self.forcing_files.append(str(forcing_file))
        else:
            if has_gage_placeholder(self.forcing_dir):
                for g in self.gpkg_dirs:
                    forcing_dir_local = self.forcing_dir
                    fdir = render_gage_path(forcing_dir_local, resource_id(g))
                    fdir = self._resolve_forcing_dir(g, fdir)

                    if not fdir.exists():
                        raise ValueError(f"Forcing directory {fdir} does not exist.")
                    if not fdir.is_dir():
                        raise ValueError("forcing format is .csv, so '{fdir}' should point to a directory and not file.")

                    self.forcing_files.append(fdir)

    def _resolve_forcing_dir(self, basin_dir, forcing_dir):
        forcing_dir = Path(forcing_dir)
        if forcing_dir.exists() or self.forcing_dir_is_configured:
            return forcing_dir

        legacy_dir = Path(basin_dir) / "data" / "forcing" / self.forcing_year_dir
        if legacy_dir.exists():
            return legacy_dir
        return forcing_dir

    def _resolve_netcdf_forcing_file(self, resource, forcing_path):
        forcing_path = self._resolve_forcing_dir(resource, forcing_path)

        if not forcing_path.exists():
            raise ValueError(
                f"Forcing directory or file '{forcing_path}' does not exist."
            )

        if forcing_path.is_dir():
            forcing_file = select_netcdf_forcing_file(
                forcing_path,
                prefer_corrected=self.is_corrected_forcing,
            )
        else:
            if forcing_path.suffix != ".nc":
                raise ValueError(
                    "forcings.forcing_dir resolved to a file, but NetCDF forcing "
                    f"requires a .nc file: {forcing_path}"
                )
            forcing_file = forcing_path

        return prepare_rechunked_forcing_file(
            forcing_file,
            sandbox_dir=self.sandbox_dir,
            enabled=self.rechunk_forcing,
        )

    def _resolve_single_netcdf_forcing_file(self):
        forcing_path = Path(self.forcing_dir)

        if not forcing_path.exists():
            raise ValueError(f"Forcing directory or file {forcing_path} does not exist.")

        if forcing_path.is_dir():
            forcing_file = select_netcdf_forcing_file(
                forcing_path,
                prefer_corrected=self.is_corrected_forcing,
            )
        else:
            if len(self.gpkg_dirs) != 1:
                raise ValueError(
                    "forcings.forcing_dir points to a single NetCDF file, "
                    f"but {len(self.gpkg_dirs)} gages are configured. "
                    "A single forcing file is only supported for one-gage runs. "
                    "For multiple gages, use a forcing directory pattern with "
                    "<gage_id> or the default layout-derived forcing directories."
                )
            if forcing_path.suffix != ".nc":
                raise ValueError(
                    "forcings.forcing_dir points to a file, but NetCDF forcing "
                    f"requires a .nc file: {forcing_path}"
                )
            forcing_file = forcing_path

        return prepare_rechunked_forcing_file(
            forcing_file,
            sandbox_dir=self.sandbox_dir,
            enabled=self.rechunk_forcing,
        )

    def process_clean_input_param(self, clean):
        clean_lst = []
        if isinstance(clean, str):
            clean_lst = [clean]
        elif isinstance(clean, list):
            clean_lst.extend(clean)
        return clean_lst
