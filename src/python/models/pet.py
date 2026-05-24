import os
import geopandas as gpd
import json
import pandas as pd
import yaml

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator


@register_model("PET")
class PETConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

        self.variants = self.ctx.model_registry.get("PET")

    def _write_input_files(self, member_id, tag):

        for variant_cfg in self.variants:

            config_dir = variant_cfg.config_dir
            basefile = variant_cfg.basefile

            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")

            if not os.path.exists(basefile_path):
                raise FileNotFoundError(f"Missing PET basefile: {basefile_path}")

            with open(basefile_path, "r") as f:
                self.pet_template = yaml.safe_load(f) or {}

            self.write_pet_input_files(config_dir, member_id=member_id, tag=tag)


    def write_pet_input_files(self, config_dir, member_id=1, tag="cfg"):

        # ensemble logic
        if self.ctx.ensemble_enabled and "PET" in (self.ctx.ensemble_models or "").upper():
            pass
        elif member_id == 1:
            tag = "cfg"
        else:
            return
        
        pet_dir = os.path.join(self.output_dir, config_dir)
        self.create_directory(pet_dir,member_id)


        for catID in self.static_data.catids:
            cat_name = "cat-" + str(catID)

            centroid_x = str(self.static_data.gdf["geometry"][cat_name].centroid.x)
            centroid_y = str(self.static_data.gdf["geometry"][cat_name].centroid.y)
            elevation_mean = self.static_data.gdf["elevation_mean"][cat_name]

            veg_type = int(self.static_data.gdf.loc[cat_name]["IVGTYP"])

            if self.ctx.ensemble_enabled or "IVGTYP_nlcd" in self.static_data.gdf.columns:
                veg_type_nlcd = json.loads(self.static_data.gdf.loc[cat_name]['IVGTYP_nlcd'])
                veg_type_nlcd = pd.DataFrame(veg_type_nlcd, columns=['v', 'frequency'])
                
                if len(veg_type_nlcd["frequency"]) == 1:
                    veg_type      = veg_type_nlcd['v'][0]
                else:
                    veg_type      = veg_type_nlcd['v'][member_id - 1]

            # Dynamcis variables
            veg_height = max(self.static_data.vegetation_height[veg_type], 0.5)

            # taken from evapotranpiration repo (see include/PETPenmanMonteithMethod.h)
            zero_plane_displacement_height_m   = 2.0 / 3.0 * veg_height 
            momentum_transfer_roughness_length = 0.1845 * zero_plane_displacement_height_m
            heat_transfer_roughness_length_m   = 0.1 * momentum_transfer_roughness_length

            # Dynamic variables — names must match YAML keys
            dynamic_values = {
                "vegetation_height_m": veg_height,
                "zero_plane_displacement_height_m": zero_plane_displacement_height_m,
                "momentum_transfer_roughness_length": momentum_transfer_roughness_length,
                "heat_transfer_roughness_length_m": heat_transfer_roughness_length_m,
                "latitude_degrees": centroid_y,
                "longitude_degrees": centroid_x,
                "site_elevation_m": elevation_mean
            }
            

            # build param list generically from the basefile
            pet_params = []
            for key in self.pet_template:
                value = self.pet_template[key]
                if value is None:
                    # update nulls from dynamic_values
                    if key not in dynamic_values:
                        raise ValueError(f"Basefile has a key '{key}' set to null but no dynamic value is computed")
                    value = dynamic_values[key]
                pet_params.append(f"{key}={value}")

            # write PET file
            fname_pet = f"pet_{tag}_{cat_name}.txt"
            pet_file = os.path.join(pet_dir, fname_pet)
            with open(pet_file, "w") as f:
                f.write("\n".join(pet_params) + "\n")
