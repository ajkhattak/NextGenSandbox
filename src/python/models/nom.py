import os
import sys
import yaml
import subprocess
import pandas as pd
import json

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator

@register_model("NOM")
class NOMConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

        self.variants = self.ctx.model_registry.get("NOM")
        
    def _write_input_files(self, member_id, tag):
        for variant_cfg in self.variants:
            
            config_dir = variant_cfg.config_dir
            basefile = variant_cfg.basefile
            
            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")
            
            
            if not os.path.exists(basefile_path):
                raise FileNotFoundError(f"Missing NOM basefile: {basefile_path}")
            
            #with open(basefile_path, "r") as f:
            #    self.pet_template = yaml.safe_load(f) or {}
            
            self.write_nom_input_files(config_dir, basefile_path, member_id=member_id, tag=tag)

    def write_nom_input_files(self, config_dir, basefile_path, member_id=1, tag="cfg"):

        if self.ctx.ensemble_enabled and "NOM" in self.ctx.ensemble_models:
            pass
        elif member_id == 1:
            tag = "cfg"
        else:
            return

        nom_dir = os.path.join(self.output_dir, config_dir)
        self.create_directory(nom_dir, member_id)
        
        # copy NOM params dir 
        str_sub ="cp -r "+ self.static_data.soil_params_NWM_dir + " %s"%nom_dir
        out=subprocess.call(str_sub,shell=True)
        
        #nom_basefile = os.path.join(self.ctx.sandbox_dir, "configs/basefiles/config_noahowp.input")

        
        # Read infile line by line
        with open(basefile_path, 'r') as infile:
            lines = infile.readlines()

        start_time = pd.Timestamp(self.ctx.simulation_time['start_time']).strftime("%Y%m%d%H%M")
        end_time   = pd.Timestamp(self.ctx.simulation_time['end_time']).strftime("%Y%m%d%H%M")

        flat_domain = 0.0 if lines[2].split("=")[1].strip().lower() == "true" else 1.0

        lines = lines[3:] # skipping the first 3 lines

        for catID in self.static_data.catids:
            cat_name = 'cat-' + str(catID)
            fname_nom = f'noahowp_{tag}_{cat_name}.input'
            
            centroid_x = str(self.static_data.gdf['geometry'][cat_name].centroid.x)
            centroid_y = str(self.static_data.gdf['geometry'][cat_name].centroid.y)
            soil_type  = str(self.static_data.gdf.loc[cat_name]['ISLTYP'])
            veg_type   = str(self.static_data.gdf.loc[cat_name]['IVGTYP'])
            
            if self.ctx.ensemble_enabled or "IVGTYP_nlcd" in self.static_data.gdf.columns:
                veg_type_nlcd = json.loads(self.static_data.gdf.loc[cat_name]['IVGTYP_nlcd'])
                veg_type_nlcd = pd.DataFrame(veg_type_nlcd, columns=['v', 'frequency'])

                if len(veg_type_nlcd["frequency"]) == 1:
                    veg_type      = veg_type_nlcd['v'][0]
                else:
                    veg_type      = veg_type_nlcd['v'][member_id - 1]


            nom_file = os.path.join(nom_dir, fname_nom)
            aspect = str(self.static_data.gdf.loc[cat_name]['aspect_mean'] * flat_domain)

            terrain_slope = str(self.static_data.gdf.loc[cat_name]['terrain_slope']*flat_domain)

            with open(nom_file, 'w') as file:
                for line in lines:
                    if line.strip().startswith('startdate'):
                        file.write(f'  startdate      = \"{start_time}\"  \n')
                    elif line.strip().startswith('enddate'):
                        file.write(f'  enddate      = \"{end_time}\"  \n')
                    elif line.strip().startswith('forcing_filename'):
                        file.write(f'  forcing_filename   = \"{self.ctx.forcing_dir}\"  \n')
                    elif line.strip().startswith('output_filename'):
                        file.write(f'  output_filename   = \"output-{cat_name}.csv\"  \n')
                    elif line.strip().startswith('parameter_dir'):
                        file.write(f'  parameter_dir      = \"{os.path.join(nom_dir, "parameters")}\" \n')
                    elif line.strip().startswith('lat'):
                        file.write(f'  lat      = {centroid_y} \n')
                    elif line.strip().startswith('lon'):
                        file.write(f'  lon      = {centroid_x} \n')
                    elif line.strip().startswith('terrain_slope'):
                        file.write(f'  terrain_slope      = {terrain_slope} \n')
                    elif line.strip().startswith('azimuth'):
                        file.write(f'  azimuth       = {aspect} \n')
                    elif line.strip().startswith('isltyp'):
                        file.write(f'  isltyp           = {soil_type} \n')
                    elif line.strip().startswith('vegtyp'):
                        file.write(f'  vegtyp        = {veg_type} \n')
                    else:
                        file.write(line)

