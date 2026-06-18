import os
import sys
import glob
import yaml
from pathlib import Path
import subprocess
import xarray as xr
import pandas as pd
import platform
import json
import time

from src.python.resource_paths import (
    find_gpkg_file,
    forcing_dir_for_gpkg,
    has_gpkg_file,
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
        self.dsim             = self.config['formulation']
        self.verbosity        = self.dsim.get('verbosity', 0)
        self.dforcing         = self.config['forcings']
        self.forcing_time     = self.dforcing["time"]
        self.forcing_format   = self.dforcing.get('format', '.nc')
        self.selected_gages   = self.dforcing.get('select', 'all')

        self.forcing_venv_dir = Path(os.environ.get("FORCING_ENV"))

        start_yr = pd.Timestamp(self.forcing_time['start_time']).year
        end_yr   = pd.Timestamp(self.forcing_time['end_time']).year + 1

        forcing_dir      = os.path.join(self.input_dir, "{*}", f'forcing/{start_yr}_to_{end_yr}')
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


    def forcing_generate_catchment(self, dir):
        os.chdir(dir)

        if not has_gpkg_file(dir):
            return

        self.gpkg_file = str(find_gpkg_file(dir))

        fdir = self.forcing_dir
        if "{*}" in self.forcing_dir:
            fdir = Path(self.forcing_dir.replace("{*}", Path(dir).name))

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

    def load_gage_ids(self):

        all_dirs = glob.glob(os.path.join(self.input_dir, '*/'), recursive=True)
        assert all_dirs, f"No directories found in the input directory {self.input_dir}."
        gpkg_dirs = [
            g for g in all_dirs
            if has_gpkg_file(g)
        ]

        # map gage_id -> directory
        gage_dir_map = {Path(d).name: d for d in gpkg_dirs}

        if self.selected_gages == "all":
            print ("Gages to be processed: ", gpkg_dirs)
            return gpkg_dirs

        if isinstance(self.selected_gages, str) and self.selected_gages.lower().endswith(".csv"):
            path = Path(self.selected_gages)

            if not path.is_file():
                raise FileNotFoundError(f"gage_ids file not found: {path}")

            df = pd.read_csv(path, dtype=str)

            if 'gage_id' not in df.columns:
                raise ValueError("CSV must contain a 'gage_id' column")

            selected_ids = df['gage_id'].tolist()

        elif isinstance(self.selected_gages, str):
            selected_ids = [self.selected_gages]

        elif isinstance(self.selected_gages, (list, tuple, set)):
            selected_ids = [str(x) for x in self.selected_gages]

        else:
            raise TypeError("forcing: 'select' must be a CSV path, a string ID, or a list of IDs")

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
        d["out_dir"] = str(forcing_dir_for_gpkg(self.gpkg_file, start_yr, end_yr).parent)

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
        nc_file = glob.glob(f"{fdir}/*.nc")
        if len(nc_file) != 1:
            print("Can't correct the forcing data, either file does not exist or more than one files exist. Files found: ", nc_file)
            return

        nc_file = [f for f in nc_file if not "_corrected" in f][0]
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
