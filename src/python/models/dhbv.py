import os
import sys
import yaml
import pandas as pd
import requests

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator


@register_model("dHBV")
class dHBVConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

        self.instances = self.ctx.model_registry.get("DHBV")

    def _write_input_files(self, member_id, tag):
        for variant_cfg in self.instances:

            config_dir = variant_cfg.config_dir
            basefile = variant_cfg.basefile

            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")

            if not os.path.exists(basefile_path):
                raise FileNotFoundError(f"Missing dHBV basefile: {basefile_path}")

            #with open(basefile_path, "r") as f:
            #    self.pet_template = yaml.safe_load(f) or {}

            self.write_dhbv_input_files(config_dir, basefile_path, member_id=member_id, tag=tag)

            

    def write_dhbv_input_files(self, config_dir, basefile_path, member_id=1, tag="cfg"):

        if self.ctx.ensemble_enabled and "dHBV" in self.ctx.ensemble_models:
            pass
        elif (member_id == 1):
            tag = "cfg"
        else:
            return
        
        dhbv_dir = os.path.join(self.output_dir, config_dir)
        self.create_directory(dhbv_dir)

        with open(basefile_path, "r") as f:
            base_file = yaml.safe_load(f)
        
        model_dir = os.path.normpath(
            os.path.join(
                self.ctx.sandbox_dir,
                "extern",
                "dhbv2",
                base_file.get("model_dir"),
            )
        )

        attributes_file = os.path.join(self.ctx.sandbox_dir,"extern/dhbv2", base_file.get("attributes_file"))
        df_attr_div     = pd.read_parquet(attributes_file)
        df_attr_div     = df_attr_div.set_index("divide_id")
        
        static_attributes_cfg = base_file.get("static_attributes", {})
        static_attrs_parquet_mapping = static_attributes_cfg.get("training", {})

        for catID in self.static_data.catids:
            cat_name = f"cat-{catID}"
            
            fname_dhbv = f'dhbv_{tag}_{cat_name}.yaml'
            dhbv_file = os.path.join(dhbv_dir, fname_dhbv)
            
            if cat_name not in df_attr_div.index:
                raise KeyError(f"{cat_name} not found in attributes parquet")

            config = {
                "model_dir": model_dir,
                "catchment_id": cat_name,
                "catchment_name": cat_name,
                "verbose": 0,
                "time_step": "1 hour",
                "dtype": "float32"
            }

            # Add training attributes
            for dhbv_name, parquet_col in static_attrs_parquet_mapping.items():
                
                if dhbv_name == "catchsize":
                    config[dhbv_name] = float(self.static_data.gdf.loc[cat_name, "divide_area"])
                elif dhbv_name == "lengthkm":
                    config[dhbv_name] = float(self.static_data.gdf.loc[cat_name, "flowpath_length"])
                else:
                    config[dhbv_name] = float(df_attr_div.loc[cat_name][parquet_col])


            with open(dhbv_file, "w") as f:
                yaml.dump(config, f, sort_keys=False)

