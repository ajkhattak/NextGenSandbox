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
    @staticmethod
    def _extract_flat_domain(lines):
        """Return the terrain multiplier and remove the Sandbox-only directive."""
        values = []
        config_lines = []

        for line_number, line in enumerate(lines, start=1):
            setting = line.split("!", maxsplit=1)[0].strip()
            key, separator, value = setting.partition("=")

            if separator and key.strip().lower() == "flat_domain":
                value = value.strip().lower()
                if value not in {"true", "false"}:
                    raise ValueError(
                        "NOM basefile flat_domain must be either true or false "
                        f"(line {line_number}), provided: {value!r}"
                    )
                values.append(value)
                continue

            config_lines.append(line)

        if not values:
            raise ValueError("NOM basefile must define flat_domain = true or false")
        if len(values) > 1:
            raise ValueError("NOM basefile defines flat_domain more than once")

        terrain_multiplier = 0.0 if values[0] == "true" else 1.0
        return terrain_multiplier, config_lines

    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

        self.instances = self.ctx.model_registry.get("NOM")
        
    def _write_input_files(self, member_id, tag):
        for variant_cfg in self.instances:
            
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

        terrain_multiplier, lines = self._extract_flat_domain(lines)

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
            aspect = str(
                self.static_data.gdf.loc[cat_name]["aspect_mean"]
                * terrain_multiplier
            )

            terrain_slope = str(
                self.static_data.gdf.loc[cat_name]["terrain_slope"]
                * terrain_multiplier
            )

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
