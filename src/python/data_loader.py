############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
# Date    : May 22, 2026
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


class SandboxData:

    def __init__(self, ctx,
                 gpkg_file
                 ):

        #self.ctx = ctx
        self.gpkg_file = gpkg_file
                         
        self.soil_params_NWM_dir = os.path.join(ctx.ngen_dir,
                                                "extern/noah-owp-modular/noah-owp-modular/parameters")

        self.gdf, self.catids = self.read_gpkg_file(ctx)

        self.soil_class_NWM, self.vegetation_height = self.get_soil_class_NWM()

        self.save_ensemble_weights(ctx)
        
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

    def read_gpkg_file(self, ctx):
        #ctx = self.ctx
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

        if ctx.verbosity >= 3:
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
        
        if ctx.schema_type == 'dangermond':
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

    def save_ensemble_weights(self, ctx, file_format="csv"):

        if not ctx.ensemble_enabled:
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
