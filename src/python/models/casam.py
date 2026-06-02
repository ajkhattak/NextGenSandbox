import os
import subprocess
import json
import numpy as np
import pandas as pd
import yaml

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator


@register_model("CASAM")
class CASAMConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

        self.instances = self.ctx.get_model_instances("CASAM")

        
    def _write_input_files(self, member_id, tag):

        for variant_cfg in self.instances:
            config_dir = variant_cfg.config_dir
            basefile = variant_cfg.basefile

            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")

            if not os.path.exists(basefile_path):
                raise FileNotFoundError(f"Missing CASAM basefile: {basefile_path}")

            with open(basefile_path, "r") as f:
                self.casam_template = yaml.safe_load(f) or {}

            self.write_casam_input_files(config_dir, basefile_path, member_id=member_id, tag=tag)
            
        

    def write_casam_input_files(self, config_dir, basefile_path, member_id=1, tag="cfg"):

        # ensemble logic
        if self.ctx.ensemble_enabled and "CASAM" in (self.ctx.ensemble_models or "").upper():
            pass
        elif member_id == 1:
            tag = "cfg"
        else:
            return

        casam_dir = os.path.join(self.output_dir, config_dir)
        self.create_directory(casam_dir)

        
        casam_params_file = os.path.join(
            self.ctx.ngen_dir,
            "extern/CASAM/CASAM/data/vG_params_stat_nom_ordered.dat"
        )

        # copy params file
        str_sub = f"cp -r {casam_params_file} {casam_dir}"
        subprocess.call(str_sub, shell=True)

        
        for catID in self.static_data.catids:

            cat_name = "cat-" + str(catID)
            fname_casam = f"casam_{tag}_{cat_name}.txt"
            casam_file = os.path.join(casam_dir, fname_casam)

            dynamic_values = self._build_dynamic_values(cat_name, member_id, casam_params_file)

            casam_params = []
            
            for key in self.casam_template:
                value = self.casam_template[key]
                
                if value is None:
                    if key not in dynamic_values:
                        raise ValueError(
                            f"CASAM basefile has key '{key}' set to null "
                            f"but no dynamic value was computed."
                        )
                    value = dynamic_values[key]

                if isinstance(value, list):
                    value = ",".join(str(v) for v in value)

                if isinstance(value, bool):
                    value = str(value).lower()

                casam_params.append(f"{key}={value}")

            with open(casam_file, "w") as f:
                f.write("\n".join(casam_params) + "\n")


    def _build_dynamic_values(self, cat_name, member_id, casam_params_file):

        gdf = self.static_data.gdf
        
        giuh_cat = json.loads(self.static_data.gdf["giuh"][cat_name])
        giuh_cat = pd.DataFrame(giuh_cat, columns=["v", "frequency"])
        
        giuh_ordinates = ",".join(str(x) for x in np.array(giuh_cat["frequency"]))
        
        any_nans = np.any(np.isnan(giuh_cat["frequency"]))
        if any_nans:
            giuh_ordinates = "1.0"
                    
        dynamic = {
            "soil_params_file" : casam_params_file,
            "layer_soil_type": gdf["ISLTYP"][cat_name],
            "giuh_ordinates": giuh_ordinates
        }


        # SFT coupling
        if "SFT" in self.ctx.formulation:
            dynamic.update({
                "sft_coupled": True,
                "soil_z": self.casam_template["soil_z"]
            })

        if self.ctx.task_type in ["calibration", "validation", "restart"]:
            dynamic.update({
                "calib_params": True
            })
        
        return dynamic
