import os
import sys
import yaml
import json
import pandas as pd
import numpy as np

from src.python.registry import register_model
from src.python.configuration import ConfigurationGenerator

@register_model("CFE")
class CFEConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx):
        super().__init__(ctx)

        default_variant = [
            {
                "name": "cfe-s",
                "basefile": "config_cfe-s.yaml"
            }
        ]

        self.variants = (
            self.ctx.model_variants.get("CFE")
            if getattr(self.ctx, "model_variants", None)
            else None
        )

        if not self.variants:
            self.variants = default_variant

            
    def _write_input_files(self, member_id, tag):
        for variant_cfg in self.variants:
            name = variant_cfg["name"]
            basefile = variant_cfg["basefile"]

            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")

            if not os.path.exists(basefile_path):
                raise FileNotFoundError(f"Missing CFE basefile: {basefile_path}")

            with open(basefile_path, "r") as f:
                self.cfe_template = yaml.safe_load(f) or {}

            self.write_cfe_input_files(name, member_id=member_id, tag=tag)

        

    def write_cfe_input_files(self, name, member_id=1, tag="cfg"):

        if self.ctx.ensemble_enabled and "CFE" in self.ctx.ensemble_models:
            pass
        elif (member_id == 1):
            tag = "cfg"
        else:
            return
        
        cfe_dir = os.path.join(self.ctx.output_dir, f"configs/{name}")
        self.create_directory(cfe_dir, member_id)

        
        for catID in self.ctx.catids:

            cat_name = f"cat-{catID}"
            fname_cfe = f"cfe_{tag}_{cat_name}.txt"
            cfe_file = os.path.join(cfe_dir, fname_cfe)

            dynamic_values = self._build_dynamic_values(cat_name, member_id)
                
            cfe_params = []

            for key in self.cfe_template:
                value = self.cfe_template[key]

                if key in ["spatial"]:          # Skip, meta keys (not model params)
                    continue

                if key in ["sft_coupled", "ice_content_threshold"] and "SFT" not in self.ctx.formulation:
                    continue

                if key in ["N_nash_surface", "K_nash_surface", "nash_storage_surface"
                           ] and self.cfe_template["surface_runoff_scheme"] == "GIUH":
                    continue

                if key in ["giuh_ordinates"] and self.cfe_template["surface_runoff_scheme"] == "NASH_CASCADE":
                    continue
                
                if value is None:
                    if key not in dynamic_values:
                        raise ValueError(
                            f"CFE basefile has key '{key}' set to null "
                            f"but no dynamic value was computed."
                        )
                    value = dynamic_values[key]

                if isinstance(value, list):
                    value = ",".join(str(v) for v in value)

                cfe_params.append(f"{key}={value}")

            with open(cfe_file, "w") as f:
                f.write("\n".join(cfe_params) + "\n")
                

    def _build_dynamic_values(self, cat_name, member_id):

        gdf = self.ctx.gdf
        
        dynamic = {
            "soil_params.b": 1.1 if gdf["soil_b"][cat_name] == 1.0 else gdf["soil_b"][cat_name],

            "soil_params.satdk": gdf["soil_satdk"][cat_name],

            "soil_params.satpsi": gdf["soil_satpsi"][cat_name],

            "soil_params.slop": gdf["soil_slop"][cat_name],

            "soil_params.smcmax": gdf["soil_smcmax"][cat_name],

            "soil_params.wltsmc": gdf["soil_wltsmc"][cat_name],

            "refkdt": gdf["soil_refkdt"][cat_name],

            "max_gw_storage": gdf["max_gw_storage"][cat_name],

            "Cgw": gdf["Cgw"][cat_name],

            "expon": gdf["gw_expon"][cat_name],

        }

        surface_runoff_scheme = self.cfe_template["surface_runoff_scheme"]

        dynamic["surface_runoff_scheme"] = surface_runoff_scheme

        if surface_runoff_scheme in ["GIUH", 1]:
            
            giuh_cat = json.loads(gdf["giuh"][cat_name])
            giuh_cat = pd.DataFrame(giuh_cat, columns=["v", "frequency"])

            dynamic["giuh_ordinates"] = list(np.array(giuh_cat["frequency"]))

        elif surface_runoff_scheme in ["NASH_CASCADE", 2]:

            N = int(gdf["N_nash_surface"][cat_name])

            dynamic.update({
                "N_nash_surface": N,
                "K_nash_surface": gdf["K_nash_surface"][cat_name],
                "nash_storage_surface": [0.0] * N
            })

        # Surface partitioning logic
        if self.cfe_template["surface_water_partitioning_scheme"].lower() == "xinanjiang":
            soil_id = gdf["ISLTYP"][cat_name]

            dynamic.update({
                "surface_water_partitioning_scheme": "Xinanjiang",
                "a_Xinanjiang_inflection_point_parameter":
                self.ctx.soil_class_NWM["AXAJ"][soil_id],
                "b_Xinanjiang_shape_parameter":
                self.ctx.soil_class_NWM["BXAJ"][soil_id],
                "x_Xinanjiang_shape_parameter":
                self.ctx.soil_class_NWM["XXAJ"][soil_id],
                "urban_decimal_fraction":
                gdf["impervious_mean"][cat_name],
            })
        #else:
        #    dynamic["surface_water_partitioning_scheme"] = "Schaake"


        # Spatial parameters override uniform values
        spatial_params = self.cfe_template.get("spatial", [])

        for param in spatial_params:
            dynamic[param], roughness_factor = self._apply_spatial_parameter(param, cat_name, member_id)
            dynamic["K_nash_surface"] = dynamic["K_nash_surface"] * roughness_factor

        # SFT logic
        if "SFT" in self.ctx.formulation:
            dynamic.update({
                "sft_coupled": True
            })

        return dynamic

    def _apply_spatial_parameter(self, param, cat_name, member_id):

        gdf = self.ctx.gdf
        
        if param == "refkdt":

            if "IVGTYP_nlcd" not in gdf.columns:
                raise ValueError("IVGTYP_nlcd column missing for spatial refkdt")

            veg_type_nlcd = json.loads(gdf.loc[cat_name]['IVGTYP_nlcd'])
            veg_type_nlcd = pd.DataFrame(veg_type_nlcd, columns=['v', 'frequency'])
            #veg_type = veg_type_nlcd['v'][member_id - 1]
            if len(veg_type_nlcd["frequency"]) == 1:
                veg_type      = veg_type_nlcd['v'][0]
            else:
                veg_type      = veg_type_nlcd['v'][member_id - 1]

            refkdt_file = os.path.join(self.ctx.sandbox_dir , "configs/calib", "cfe_refkdt.yaml")

            with open(refkdt_file, 'r') as file:
                refkdt_data = yaml.safe_load(file)

            classes = refkdt_data['refkdt']['classes']

            class_veg = next(
                (item for item in classes if item['usgs_id'] == veg_type),
                None
            )

            if class_veg is None:
                raise ValueError(f"No refkdt class found for vegetation {veg_type}")

            return class_veg["init"], class_veg["runoff_resistance_factor"]

        # -------------------------------------------------
        # Future spatial parameters go here
        # -------------------------------------------------

        else:
            raise ValueError(f"Spatial logic not implemented for parameter '{param}'")
        
