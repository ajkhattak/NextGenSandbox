import os
import sys
import glob
import yaml
from pathlib import Path
import subprocess
import xarray as xr
import pandas as pd

from src.python.forcing_files import (
    prepare_rechunked_forcing_file,
    select_netcdf_forcing_file,
    select_source_netcdf_forcing_file,
)
from src.python.gages import load_general_gages, resolve_step_gages
from src.python.resource_paths import (
    find_gpkg_file,
    forcing_dir_for_resource,
    has_gpkg_file,
    resource_hydrofabric_dir,
    resource_id,
)


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
        self.dsim             = self.config['formulation']
        self.verbosity        = self.dsim.get('verbosity', 0)
        self.dforcing         = self.config['forcings']
        self.forcing_time     = self.dforcing["time"]
        self.forcing_format   = self.dforcing.get('format', '.nc')
        self.selected_gages   = resolve_step_gages(
            project_gages=self.project_gages,
            step_value=self.dforcing.get("gages"),
            field_name="forcings.gages",
        )
        self.rechunk_forcing  = self.dforcing.get("rechunk", True)

        self.forcing_venv_dir = Path(os.environ.get("FORCING_ENV"))

        start_yr = pd.Timestamp(self.forcing_time['start_time']).year
        end_yr   = pd.Timestamp(self.forcing_time['end_time']).year + 1

        if self.resource_layout == "resource":
            forcing_dir = os.path.join(
                self.input_dir,
                "forcing",
                "{*}",
                f"{start_yr}_to_{end_yr}",
            )
        else:
            forcing_dir = os.path.join(
                self.input_dir,
                "{*}",
                f"forcing/{start_yr}_to_{end_yr}",
            )
        self.forcing_dir = self.dforcing.get("forcing_dir", forcing_dir)

    def download_forcing(self):
        if not os.path.exists(self.config_file):
            sys.exit("Sample forcing yaml file does not exist, provided is " + self.config_file)

        failed = False

        for gpkg in self.gpkg_dirs:
            print (f"Processing gage: {gpkg}")
            result = self.forcing_generate_catchment(gpkg)
            if result:
                failed = True

        return failed


    def forcing_generate_catchment(self, resource):
        resource = Path(resource)
        work_dir = resource.parent if resource.is_file() else resource
        os.chdir(work_dir)

        if not has_gpkg_file(resource):
            return

        self.current_resource = resource
        self.gpkg_file = str(find_gpkg_file(resource))

        fdir = self.forcing_dir
        if "{*}" in self.forcing_dir:
            fdir = Path(self.forcing_dir.replace("{*}", resource_id(resource)))

        forcing_config = self.write_forcing_input_files(forcing_dir=fdir)

        run_cmd = f'python {self.sandbox_dir}/extern/CIROH_DL_NextGen/forcing_prep/generate.py {forcing_config}'

        venv_bin = os.path.join(self.forcing_venv_dir, 'bin')

        if not os.path.exists(venv_bin):
            msg = f"Python venv for forcing does not exist. Provided {self.forcing_venv_dir}"
            sys.exit(msg)

        env = os.environ.copy()
        env['PATH'] = f"{venv_bin}:{env['PATH']}"
        result = subprocess.call(run_cmd, shell=True, env=env)

        if self.forcing_format == ".nc":
            print("Correcting forcing data ...")
            self.forcing_data_correction(fdir)
            forcing_file = select_netcdf_forcing_file(fdir, prefer_corrected=True)
            prepare_rechunked_forcing_file(
                forcing_file,
                sandbox_dir=self.sandbox_dir,
                enabled=self.rechunk_forcing,
            )

    def load_gage_ids(self):
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

        # ---------- filter directories ----------
        selected_dirs = [gage_dir_map[g] for g in selected_ids if g in gage_dir_map]

        if not selected_dirs:
            raise ValueError(f"No matching gage directories found for: {selected_ids}")

        print("Selected gage directories:", selected_dirs)

        return selected_dirs

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
        d["out_dir"] = str(
            forcing_dir_for_resource(
                self.input_dir,
                self.current_resource,
                start_yr,
                end_yr,
                self.resource_layout,
            ).parent
        )

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
