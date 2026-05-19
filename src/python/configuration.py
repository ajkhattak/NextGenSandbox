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

try:
    from src.python import schema
except:
    import schema

os_name = platform.system()

from src.python.registry import MODELS_REGISTRY

def _load_formulations():
    # Import formulation modules here so they register themselves
    import src.python.models.lstm
    import src.python.models.nom
    import src.python.models.cfe
    import src.python.models.topmodel
    import src.python.models.pet
    import src.python.models.sacsma
    import src.python.models.casam
    import src.python.models.snow17
    import src.python.models.troute
    import src.python.models.sft
    import src.python.models.smp
    import src.python.models.dhbv

def get_config_generator(formulation, **kwargs):
    ctx = ConfigurationContext(formulation=formulation, **kwargs)

    _load_formulations()
    keys = [k.strip().upper() for k in formulation.replace(",", "+").split("+")]
    generators = []
    for key in keys:
        if key not in MODELS_REGISTRY:
            raise ValueError(f"Unknown model in the formulation: {key}")
        # creates an instance using class context MODELS_REGISTRY["NOM"] => NOMConfigurationGenerator
        generators.append(MODELS_REGISTRY[key](ctx))

    if len(generators) == 1:
        return generators[0]

    return CompositeConfigurationGenerator(generators)

class ConfigurationContext:

    def __init__(self, sandbox_dir, gpkg_file, forcing_dir, output_dir,
                 ngen_dir, formulation, model_variants, simulation_time,
                 verbosity, ngen_cal_type, schema_type = None,
                 ensemble_enabled = False,
                 ensemble_models  = None):

        self.sandbox_dir        = sandbox_dir
        self.gpkg_file          = gpkg_file
        self.forcing_dir        = forcing_dir
        self.output_dir         = output_dir
        self.ngen_dir           = ngen_dir
        self.formulation        = formulation
        self.model_variants     = model_variants
        self.simulation_time    = simulation_time
        self.verbosity          = verbosity
        self.ngen_cal_type      = ngen_cal_type
        self.schema_type        = schema_type
        self.ensemble_enabled   = ensemble_enabled
        self.ensemble_size = len([m.strip() for m in ensemble_models.split(",")]) if self.ensemble_enabled else 1
        self.ensemble_models    = ensemble_models

        self.soil_params_NWM_dir = os.path.join(self.ngen_dir,"extern/noah-owp-modular/noah-owp-modular/parameters")

        self.gdf, self.catids = self.read_gpkg_file()

        self.soil_class_NWM, self.vegetation_height = self.get_soil_class_NWM()

        self.save_ensemble_weights()
        
    def get_soil_class_NWM(self):
        nom_soil_file = os.path.join(self.soil_params_NWM_dir, "SOILPARM.TBL")
        header = ['index', 'BB', 'DRYSMC', 'F11', 'MAXSMC', 'REFSMC', 'SATPSI', 'SATDK', 'SATDW',
                  'WLTSMC', 'QTZ', 'BVIC', 'AXAJ', 'BXAJ', 'XXAJ', 'BDVIC', 'BBVIC', 'GDVIC', 'ISLTYP']
        df = pd.read_table(nom_soil_file, delimiter=',', index_col=0, skiprows=3, nrows=19, names=header)

        nom_veg_file = os.path.join(self.soil_params_NWM_dir, "MPTABLE.TBL")
        with open(nom_veg_file, 'r') as f:
            lines = f.readlines()

        # Extract HVT values
        for line in lines:
            if line.strip().startswith("HVT"):
                hvt_line = line.split('=')[1]   # Remove 'HVT =' or 'HVT   ='
                hvt_values = [float(x.strip().rstrip(',')) for x in hvt_line.strip().split(',') if x.strip()]
                HVT = {i: val for i, val in enumerate(hvt_values, start=1)}
                break

        return df, HVT

    def read_gpkg_file(self):
        try:
            gdf_soil = gpd.read_file(self.gpkg_file, layer='divide-attributes')
        except:
            try:
                gdf_soil = gpd.read_file(self.gpkg_file, layer='model_attributes')
            except:
                print("layer 'divide-attributes or model_attributes does not exist!'")
                sys.exit(1)

        gdf_soil.set_index("divide_id", inplace=True)
        gdf_div = gpd.read_file(self.gpkg_file, layer='divides')
        gdf_div = gdf_div.to_crs("EPSG:4326")
        gdf_div.set_index("divide_id", inplace=True)

        layers = fiona.listlayers(self.gpkg_file)
        flowpath_layer = [layer for layer in layers if 'flowpath' in layer][0]

        if self.verbosity >= 3:
            print("Geopackage layers: ", layers, "\n")

        params = schema.get_schema_model_attributes(gdf_soil)

        gdf_soil['soil_b']           = gdf_soil[params['soil_b']].fillna(16)
        gdf_soil['soil_dksat']       = gdf_soil[params['soil_dksat']].fillna(0.00000338)
        gdf_soil['soil_psisat']      = gdf_soil[params['soil_psisat']].fillna(0.355)
        gdf_soil['soil_smcmax']      = gdf_soil[params['soil_smcmax']].fillna(0.439)
        gdf_soil['soil_smcwlt']      = gdf_soil[params['soil_smcwlt']].fillna(0.066)
        gdf_soil['gw_Zmax']          = gdf_soil[params['gw_Zmax']].fillna(0.01)
        gdf_soil['gw_Coeff']         = gdf_soil[params['gw_Coeff']].fillna(1.8e-05)
        gdf_soil['gw_Expon']         = gdf_soil[params['gw_Expon']].fillna(6.0)
        gdf_soil['slope_1km']        = gdf_soil[params['slope_1km']].fillna(1.0)
        gdf_soil['ISLTYP']           = gdf_soil[params['ISLTYP']].fillna(1).astype(int)
        gdf_soil['IVGTYP']           = gdf_soil[params['IVGTYP']].fillna(1).astype(int)
        gdf_soil['gw_Zmax']          = gdf_soil['gw_Zmax'] / 1000.0
        gdf_soil['gw_Coeff']         = gdf_soil['gw_Coeff'] * 3600 / (7.337700 * 1000 * 1000)
        gdf_soil['elevation_mean']   = gdf_soil[params['elevation_mean']].fillna(4) / 100. # convert cm to m
        gdf_soil['slope_mean']       = gdf_soil[params['slope_mean']].fillna(0.0)
        gdf_soil['aspect_mean']      = gdf_soil[params['aspect_mean']].fillna(0.0)
        gdf_soil['impervious_mean']  = gdf_soil[params['impervious_mean']].fillna(0.0) / 100. # convert percent to fraction
        gdf_soil['terrain_slope']    = gdf_soil[params['terrain_slope']].fillna(0.0)
        gdf_soil['divide_area']      = gdf_div["areasqkm"].fillna(1.0)
        gdf_soil['flowpath_length']  = gdf_div["lengthkm"].fillna(1.0)
        
        if self.schema_type == 'dangermond':
            gdf_soil['elevation_mean'] = gdf_soil['elevation_mean'] / 100.0

        if 'refkdt' in gdf_soil:
            gdf_soil['soil_refkdt'] = gdf_soil[params['soil_refkdt']].fillna(3.0)
        else:
            gdf_soil['soil_refkdt'] = 3.0

        gdf = gpd.GeoDataFrame(data={'geometry': gdf_div['geometry'].values}, index=gdf_soil.index)
        gdf['soil_b']          = gdf_soil['soil_b'].copy()
        gdf['soil_satdk']      = gdf_soil['soil_dksat'].copy()
        gdf['soil_satpsi']     = gdf_soil['soil_psisat'].copy()
        gdf['soil_slop']       = gdf_soil['slope_1km'].copy()
        gdf['soil_smcmax']     = gdf_soil['soil_smcmax'].copy()
        gdf['soil_wltsmc']     = gdf_soil['soil_smcwlt'].copy()
        gdf['soil_refkdt']     = gdf_soil['soil_refkdt'].copy()
        gdf['max_gw_storage']  = gdf_soil['gw_Zmax'].copy()
        gdf['Cgw']             = gdf_soil['gw_Coeff'].copy()
        gdf['gw_expon']        = gdf_soil['gw_Expon'].copy()
        gdf['ISLTYP']          = gdf_soil['ISLTYP'].copy()
        gdf['IVGTYP']          = gdf_soil['IVGTYP'].copy()
        gdf['elevation_mean']  = gdf_soil['elevation_mean'].copy()
        gdf['slope_mean']      = gdf_soil['slope_mean'].copy()
        gdf['aspect_mean']     = gdf_soil['aspect_mean'].copy()
        gdf['impervious_mean'] = gdf_soil['impervious_mean'].copy()

        mask = gdf['soil_b'].gt(0.0)
        min_value = gdf['soil_b'][mask].min()
        mask = gdf['soil_b'].le(0.0)
        gdf.loc[mask, 'soil_b'] = min_value

        mask = gdf['elevation_mean'].le(0.0)
        gdf.loc[mask, 'elevation_mean'] = 1.0

        if "TOPMODEL" in self.formulation:
            gdf['twi'] = gdf_soil[params['twi']]
            gdf['width_dist'] = gdf_soil[params['width_dist']]


        gdf['giuh'] = gdf_soil[params['giuh']]
        gdf['N_nash_surface'] = gdf_soil[params['N_nash_surface']]
        gdf['K_nash_surface'] = gdf_soil[params['K_nash_surface']]

        gdf['terrain_slope'] = gdf_soil[params['terrain_slope']]

        gdf['divide_area'] = gdf_soil['divide_area']
        gdf['flowpath_length'] = gdf_soil['flowpath_length']

        if "IVGTYP_nlcd" in params and params["IVGTYP_nlcd"] in gdf_soil.columns:
            gdf["IVGTYP_nlcd"] = gdf_soil[params["IVGTYP_nlcd"]]
         

        df_cats = gpd.read_file(self.gpkg_file, layer='divides')
        catids = [int(re.findall('[0-9]+', s)[0]) for s in df_cats['divide_id']]

        return gdf, catids

    def save_ensemble_weights(self, file_format="csv"):

        if not self.ensemble_enabled:
            return

        rows = []

        for catID in self.catids:
            cat_name = 'cat-' + str(catID)
            
            veg_type_nlcd = json.loads(self.gdf.loc[cat_name]['IVGTYP_nlcd'])
            df = pd.DataFrame(veg_type_nlcd, columns=['v', 'frequency'])
            frequencies = df['frequency'].tolist()

            if len(frequencies) !=  self.ensemble_size:
                frequencies.append(0)

            rows.append([cat_name] + frequencies)

        columns = ['divide_id'] + [f'weight_{i+1}' for i in range(self.ensemble_size)]
       
        out_df = pd.DataFrame(rows, columns=columns)

        # Save file
        out_path = os.path.join(self.output_dir, "configs", "ensemble_weights")

        if file_format == "csv":
            out_df.to_csv(f"{out_path}.csv", index=False)
        elif file_format == "parquet":
            out_df.to_parquet(f"{out_path}.parquet", index=False)
        else:
            raise ValueError("file_format must be one of ['csv', 'parquet']")

    def get_flowpath_attributes(self,
                                full_schema=False,
                                gage_id=False):

        layers = fiona.listlayers(self.gpkg_file)
        flowpath_layer = [layer for layer in layers if 'flowpath' in layer and not 'flowpaths' in layer][0]
        gdf_fp_attr = gpd.read_file(self.gpkg_file, layer=flowpath_layer)
        params = schema.get_schema_flowpath_attributes(gdf_fp_attr, for_gage_id=gage_id)

        if full_schema:
            return params
        elif gage_id:
            gage_id = params['gages']
            waterbody_id = params['key']
            gdf_fp_cols = gdf_fp_attr[[waterbody_id, gage_id]]
            basin_gage = gdf_fp_cols[gdf_fp_cols[gage_id].notna()]
            basin_gage_id = basin_gage[waterbody_id].tolist()
            return basin_gage_id

# ----------------------------
# Base Generator
# ----------------------------
class ConfigurationGenerator:
    def __init__(self, context: ConfigurationContext):
        self.ctx = context

        # convenience
        self.gdf = context.gdf
        self.catids = context.catids

        # shared derived fields
        self.soil_params_NWM_dir = os.path.join(
            self.ctx.ngen_dir,
            "extern/noah-owp-modular/noah-owp-modular/parameters"
        )

    def __getattr__(self, name):
        if name in [
            "output_dir", "sandbox_dir", "gpkg_file",
            "forcing_dir", "ngen_dir", "formulation",
            "simulation_time", "verbosity", "ngen_cal_type",
            "schema_type", "ensemble_enabled", "ensemble_size",
            "ensemble_models", "gdf", "catids"
        ]:
            raise AttributeError(
                f"Access '{name}' directly is not allowed. Use 'self.ctx.{name}' instead."
            )
        raise AttributeError(name)
    
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
    def __init__(self, gpkg_file, output_dir, ngen_dir, sandbox_dir, realization_file_par,
                 troute_output_file, ngen_cal_basefile, ngen_cal_type, formulation, model_variants,
                 restart_dir, simulation_time, evaluation_time, num_proc,
                 ensemble_enabled, ensemble_models,
                 ensemble_calib_params_groups):
        
        self.gpkg_file          = gpkg_file
        self.output_dir         = output_dir
        self.ngen_dir           = ngen_dir
        self.sandbox_dir        = sandbox_dir
        self.simulation_time    = simulation_time
        self.evaluation_time    = evaluation_time
        self.formulation        = formulation
        self.model_variants     = model_variants
        self.ngen_cal_type      = ngen_cal_type
        self.num_proc           = num_proc
        self.ngen_cal_basefile  = ngen_cal_basefile
        self.troute_output_file = troute_output_file
        self.restart_dir        = restart_dir
        self.ensemble_enabled   = ensemble_enabled
        self.ensemble_size      = len([m.strip() for m in ensemble_models.split(",")]) if self.ensemble_enabled else 1
        self.ensemble_models    = ensemble_models
        self.realization_file_par = realization_file_par
        self.ensemble_calib_params_groups = ensemble_calib_params_groups
        
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
            params_state_dir = self.restart_dir

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

    def write_calib_input_files(self):
        
        conf_dir = os.path.join(self.output_dir, "configs")
        realization_file =  sorted(
            glob.glob(os.path.join(conf_dir, "realization_*.json"))
            )

        if (self.ensemble_enabled):
            assert len(realization_file) == self.ensemble_size
        else:
            assert len(realization_file) == 1

        if not os.path.exists(self.ngen_cal_basefile):
            sys.exit(f"Sample calib yaml file does not exist, provided is {self.ngen_cal_basefile}")

        gpkg_name = os.path.basename(self.gpkg_file).split(".")[0]
        gage_id = self.get_flowpath_attributes()

        with open(self.ngen_cal_basefile, 'r') as file:
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

        model_param_map = {
            "TOPMODEL": "topmodel_params",
            "NOM":      "noahowp_params",
            "SNOW17":   "snow17_params",
            "SAC-SMA":  "sacsma_params",
            "CASAM":    "casam_params"
        }

        if "CFE" in self.formulation:
            default_variants = [
                {
                    "name": "cfe-s"
                }
            ]

            cfe_variants = (
                self.model_variants.get("CFE")
                if self.model_variants
                else None
            )

            if not cfe_variants:
                cfe_variants = default_variants
        
            for variant_cfg in cfe_variants:

                variant_name = variant_cfg["name"]

                if variant_name == "cfe-s":
                    model_param_map["CFE"] = "cfes_params"
                elif variant_name == "cfe-x":
                    model_param_map["CFE"] = "cfex_params"
            
        # Add calibratable parameter blocks
        for model in self.formulation.split(","):
            model = model.strip()
            if model not in model_param_map:
                continue
            name = model_param_map[model]
            param_values = base_file.get(name, [])

            if (self.ensemble_enabled
                and self.ensemble_calib_params_groups.get(model) == "local"):
                new_params = []

                for i in range(self.ensemble_size):
                    for p in param_values:
                        new_param = dict(p)                            # create a deep copy to avoid reference issues
                        new_param["name"] = f"{p['name']}_tile_{i+1}"
                        new_params.append(new_param)

                df_new[name] = new_params

            else:
                df_new[name] = param_values

        df_new["model"] = {
            "type": "ngen",
            "binary": os.path.join(self.ngen_dir, "cmake_build/ngen"),
            "realization": realization_file[0],
            "hydrofabric": self.gpkg_file.as_posix(),
            "routing_output": self.troute_output_file,
            "strategy": base_file.get("strategy", "uniform"),
            "eval_feature": gpkg_name.split("_")[1]
        }

        if self.ensemble_enabled:
            df_new["model"]["binary"] = os.path.join(self.sandbox_dir, "src/python/landcover_tiling.py")

            cmd = (
                f"--hydrofabric {self.gpkg_file.as_posix()} "
                f"--realization {realization_file[0]} "
                f"--routing {conf_dir}/troute_config.yaml"
            )
            
            if self.num_proc > 1:
                cmd += f" --partition {self.num_proc}"

            if self.ngen_cal_type == "validation":
                 cmd += f" --task_type {self.ngen_cal_type}"

            df_new["model"]["args"]  = cmd

        
        if self.num_proc > 1 and self.ensemble_size == 1:
            df_new["model"]["parallel"] = self.num_proc
            df_new["model"]["partitions"] = self.realization_file_par

        gage_id = self.get_flowpath_attributes()


        df_new["model"]["params"] = {}

        for model in self.formulation.split(","):
            model = model.strip()
            for key, name in model_param_map.items():
                if key in model:
                    if key in ["CFE-S", "CFE-X"]:
                        key = "CFE"
                    if key == "NOM":
                        key = "NoahOWP"
                    if key == "SNOW17":
                        key = "Snow17"
                    if key == "SAC-SMA":
                        key = "SacSMA"
                    if key == "CASAM":
                        key = "LGAR"
                    param_values = base_file.get(name, [])

                    # store final params
                    df_new["model"]["params"][key] = df_new[f"{name}"] #tiled_params


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

        df_new["model"]["plugins"] = base_file.get("model", "").get("plugins", "")
        # see if user have provided local observed data
        obs_data_flag = base_file.get('model', {}).get('plugin_settings', {}).get('read_obs_data', None)

        if obs_data_flag:
            obs_dir = base_file['model']['plugin_settings']['read_obs_data']['obs_data_path']
            obs_file = glob.glob(f'{obs_dir}/{gpkg_name}*.csv')[0]
            df_new.setdefault("model", {}).setdefault("plugin_settings", {})["read_obs_data"] = {
                "obs_data_path": obs_file
            }
             

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

        with open(os.path.join(conf_dir, config_fname), 'w') as file:
            yaml.dump(df_new, file, default_flow_style=False, sort_keys=False)


