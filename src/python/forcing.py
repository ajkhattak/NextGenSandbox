import os
import sys
import glob
import shlex
import yaml
from pathlib import Path
import subprocess
import xarray as xr
import pandas as pd

from src.python.forcing_files import (
    prepare_rechunked_forcing_file,
    resolve_netcdf_forcing_pattern,
    select_netcdf_forcing_file,
    select_source_netcdf_forcing_file,
)
from src.python.gages import (
    load_general_gages,
    load_gpkg_resources,
    resolve_step_gages,
)
from src.python.resource_paths import (
    find_gpkg_file,
    has_gage_placeholder,
    has_gpkg_file,
    render_gage_path,
    resource_hydrofabric_dir,
    resource_id,
)
from src.python.time_windows import normalize_forcing_time_config


class ForcingProcessor:
    def __init__(self, sandbox_dir, config_file):
        self.sandbox_dir = Path(sandbox_dir)
        self.config_file = config_file
        self.load_config()

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.gpkg_dirs = self.load_gage_ids()
        
    def load_config(self):
        with open(self.config_file, 'r') as file:
            self.config = yaml.safe_load(file)

        self.input_dir        = self.config['general'].get('input_dir')
        self.output_dir       = Path(self.config['general'].get('output_dir'))
        self.resource_layout  = self.config["general"].get("resource_layout", "gage")
        if self.resource_layout not in {"gage", "resource"}:
            raise ValueError("general.resource_layout must be one of: gage, resource")
        self.project_gages    = load_general_gages(self.config)
        self.verbosity        = 0
        self.dforcing         = self.config['forcings']
        self.forcing_time     = normalize_forcing_time_config(self.dforcing["time"])
        self.forcing_format   = self.dforcing.get('format', '.nc')
        self.selected_gages   = resolve_step_gages(
            project_gages=self.project_gages,
            step_value=self.dforcing.get("gages"),
            field_name="forcings.gages",
        )
        self.rechunk_forcing  = self.dforcing.get("rechunk", True)

        start_yr = pd.Timestamp(self.forcing_time['start_time']).year
        end_yr   = pd.Timestamp(self.forcing_time['end_time']).year + 1

        if self.resource_layout == "resource":
            forcing_dir = os.path.join(
                self.input_dir,
                "forcing",
                "<gage_id>",
                f"{start_yr}_to_{end_yr}",
            )
        else:
            forcing_dir = os.path.join(
                self.input_dir,
                "<gage_id>",
                f"forcing/{start_yr}_to_{end_yr}",
            )
        self.forcing_dir = self.dforcing.get("forcing_dir", forcing_dir)
        self.external_netcdf_template = (
            Path(str(self.forcing_dir)).suffix.lower() == ".nc"
            or glob.has_magic(str(self.forcing_dir))
        )
        if self.external_netcdf_template and self.forcing_format != ".nc":
            raise ValueError(
                "A NetCDF forcings.forcing_dir filename template requires "
                "forcings.format: .nc"
            )
        if (
            self.external_netcdf_template
            and len(self.selected_gages) > 1
            and not has_gage_placeholder(self.forcing_dir)
        ):
            raise ValueError(
                "A custom NetCDF forcings.forcing_dir without <gage_id> is only "
                "supported for one gage."
            )

        forcing_env = os.environ.get("FORCING_ENV")
        self.forcing_venv_dir = Path(forcing_env) if forcing_env else None

    def download_forcing(self):
        if not os.path.exists(self.config_file):
            sys.exit("Sample forcing yaml file does not exist, provided is " + self.config_file)

        failed = False

        for gage_id, gpkg in zip(
            self.selected_gages,
            self.gpkg_dirs,
            strict=True,
        ):
            if self.external_netcdf_template:
                print(f"Preparing existing forcing for gage: {gage_id}")
                result = self.prepare_existing_forcing(gage_id)
            else:
                print(f"Processing gage: {gpkg}")
                result = self.forcing_generate_catchment(gpkg, gage_id=gage_id)
            if result:
                failed = True

        return failed

    def prepare_existing_forcing(self, gage_id):
        forcing_path = self.forcing_dir
        if has_gage_placeholder(forcing_path):
            forcing_path = render_gage_path(forcing_path, gage_id)

        forcing_file = resolve_netcdf_forcing_pattern(
            forcing_path,
            rechunk_enabled=self.rechunk_forcing,
        )
        if not forcing_file.is_file():
            raise FileNotFoundError(
                f"Custom NetCDF forcing file does not exist: {forcing_file}"
            )

        prepared_file = prepare_rechunked_forcing_file(
            forcing_file,
            sandbox_dir=self.sandbox_dir,
            enabled=self.rechunk_forcing,
        )
        print(f"Prepared forcing file: {prepared_file}")
        return False


    def forcing_generate_catchment(self, resource, gage_id=None):
        resource = Path(resource)
        gage_id = gage_id or self._resource_gage_id(resource)
        work_dir = resource.parent if resource.is_file() else resource
        os.chdir(work_dir)

        if not has_gpkg_file(resource):
            return False

        self.current_resource = resource
        self.gpkg_file = str(find_gpkg_file(resource))

        fdir = self.forcing_dir
        if has_gage_placeholder(self.forcing_dir):
            fdir = render_gage_path(self.forcing_dir, gage_id)

        forcing_config = self.write_forcing_input_files(forcing_dir=fdir)

        if self.forcing_venv_dir is None:
            sys.exit(
                "FORCING_ENV is not set. Build and load the Sandbox forcing "
                "environment before downloading forcing data."
            )

        venv_bin = self.forcing_venv_dir / "bin"
        forcing_python = venv_bin / "python"
        forcing_script = (
            self.sandbox_dir
            / "extern"
            / "CIROH_DL_NextGen"
            / "forcing_prep"
            / "generate.py"
        )
        run_cmd = [
            str(forcing_python),
            str(forcing_script),
            str(forcing_config),
        ]

        if not forcing_python.is_file():
            msg = (
                "Python executable for forcing does not exist. "
                f"Expected: {forcing_python}"
            )
            sys.exit(msg)

        env = os.environ.copy()
        env["PATH"] = f"{venv_bin}{os.pathsep}{env['PATH']}"
        result = subprocess.run(run_cmd, env=env)
        if result.returncode != 0:
            print(
                "Forcing generation failed before post-processing. "
                f"Command exited with status {result.returncode}: "
                f"{shlex.join(run_cmd)}"
            )
            return True

        if self.forcing_format == ".nc":
            print("Correcting forcing data ...")
            self.forcing_data_correction(fdir)
            forcing_file = select_netcdf_forcing_file(fdir, use_corrected=True)
            prepare_rechunked_forcing_file(
                forcing_file,
                sandbox_dir=self.sandbox_dir,
                enabled=self.rechunk_forcing,
            )

        return False

    def load_gage_ids(self):
        gages_config = getattr(self, "config", {}).get("general", {}).get(
            "gages",
            {},
        )
        if str(gages_config.get("option", "")).lower() == "gpkg":
            resources = load_gpkg_resources(
                self.config,
                selected_gages=self.selected_gages,
            )
            self._gpkg_gage_ids = {
                Path(resource): gage_id
                for gage_id, resource in resources.items()
            }
            selected_resources = list(resources.values())
            print("Selected geopackage resources:", selected_resources)
            return selected_resources

        self._gpkg_gage_ids = {}
        input_dir = Path(self.input_dir)
        if not input_dir.is_dir():
            raise FileNotFoundError(
                f"Input directory does not exist: {input_dir}. "
                "Run the subsetting step first or correct general.input_dir."
            )

        if self.resource_layout == "resource":
            hydrofabric_dir = resource_hydrofabric_dir(input_dir)
            gpkg_dirs = sorted(hydrofabric_dir.glob("*.gpkg"))
            expected_location = hydrofabric_dir / "*.gpkg"
        else:
            all_dirs = glob.glob(os.path.join(input_dir, '*/'), recursive=True)
            gpkg_dirs = [
                Path(g) for g in all_dirs
                if has_gpkg_file(g)
            ]
            expected_location = input_dir / "<gage_id>" / "hydrofabric" / "*.gpkg"

        if not gpkg_dirs:
            raise FileNotFoundError(
                f"No geopackages found for general.resource_layout='{self.resource_layout}'. "
                f"Expected files matching: {expected_location}"
            )

        # map gage_id -> directory
        gage_dir_map = {resource_id(d): d for d in gpkg_dirs}

        selected_ids = self.selected_gages

        missing_ids = [
            gage_id for gage_id in selected_ids
            if gage_id not in gage_dir_map
        ]
        if missing_ids:
            raise FileNotFoundError(
                "Geopackages are missing for requested gages: "
                f"{', '.join(missing_ids)}. "
                f"Expected files matching: {expected_location}"
            )

        selected_dirs = [gage_dir_map[gage_id] for gage_id in selected_ids]

        print("Selected gage directories:", selected_dirs)

        return selected_dirs

    def _resource_gage_id(self, resource):
        configured_id = getattr(self, "_gpkg_gage_ids", {}).get(Path(resource))
        if configured_id:
            return configured_id
        return resource_id(resource)

    def write_forcing_input_files(self, forcing_dir):

        forcing_basefile = os.path.join(self.sandbox_dir, "configs/basefiles/config_aorc.yaml")

        if not os.path.exists(forcing_basefile):
            sys.exit(f"Sample forcing yaml file does not exist, provided is {forcing_basefile}")

        with open(forcing_basefile, 'r') as file:
            d = yaml.safe_load(file)


        start_yr = pd.Timestamp(self.forcing_time['start_time']).year
        end_yr   = pd.Timestamp(self.forcing_time['end_time']).year

        if start_yr > end_yr:
            sys.exit(f"end_time ({end_yr})is less than the start_time ({start_yr}")

        if start_yr <= end_yr:
            end_yr = end_yr + 1

        d['gpkg'] = self.gpkg_file
        d["years"] = [start_yr, end_yr]
        d["out_dir"] = str(Path(forcing_dir).parent)

        out_dir = Path(d['out_dir']) / f'{start_yr}_to_{end_yr}'
        are_identical = out_dir.resolve() == Path(forcing_dir).resolve()

        if not are_identical:
            raise RuntimeError(f"Directory mismatch: out_dir={out_dir} is not the same as forcing_dir={forcing_dir}.")

        if not os.path.exists(d["out_dir"]):
            os.makedirs(d["out_dir"])

        if self.forcing_format == '.csv':
            d['netcdf'] = False

        with open(os.path.join(d["out_dir"], "config_forcing.yaml"), 'w') as file:
            yaml.dump(d, file, default_flow_style=False, sort_keys=False)

        return os.path.join(d["out_dir"], "config_forcing.yaml")


    def forcing_data_correction(self, fdir):
        nc_file = select_source_netcdf_forcing_file(fdir)
        if nc_file is None:
            return

        ds = xr.open_dataset(nc_file)
        ds['APCP_surface'].attrs['units'] = 'mm/hr'

        for name in ds.data_vars:
            if ds[name].isnull().any():
                if self.verbosity >= 2:
                    print(f"Missing data: NaNs found in {name}. Applying nearest neighbor")
                ds[name] = ds[name].interpolate_na(dim='time', method='nearest')
            elif self.verbosity >= 2:
                print(f"Looks good. No NaNs found in {name}.")

            # Fix negative radiation values
            if name in ['DLWRF_surface', 'DSWRF_surface']:
                neg_mask = ds[name] < 0

                if neg_mask.any():
                    if self.verbosity >= 2:
                        neg_count = int(neg_mask.sum())
                        print(f"{neg_count} negative values found in {name}. Applying linear interpolation.")

                    # set negatives to NaN
                    ds[name] = ds[name].where(~neg_mask)

                    # interpolate along time
                    ds[name] = ds[name].interpolate_na(dim='time', method='linear')

            # Fix <200K values in air Temperature
            if name in ['TMP_2maboveground']:
                neg_mask = ds[name] < 200

                if neg_mask.any():
                    if self.verbosity >= 2:
                        neg_count = int(neg_mask.sum())
                        print(f"{neg_count} negative values found in {name}. Applying linear interpolation.")

                    # set negatives to NaN
                    ds[name] = ds[name].where(~neg_mask)

                    # interpolate along time
                    ds[name] = ds[name].interpolate_na(dim='time', method='linear')

        path = Path(nc_file)
        new_file = Path(fdir) / (path.stem + "_corrected.nc")
        ds.to_netcdf(new_file)
