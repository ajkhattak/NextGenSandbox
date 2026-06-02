import os
import sys
import yaml
import pandas as pd

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator

@register_model("LSTM")
class LSTMConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

        self.instances = self.ctx.model_registry.get("LSTM")
        
    def _write_input_files(self, member_id, tag):
        for variant_cfg in self.instances:

            config_dir = variant_cfg.config_dir
            basefile = variant_cfg.basefile

            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")

            if not os.path.exists(basefile_path):
                raise FileNotFoundError(f"Missing LSTM basefile: {basefile_path}")

            #with open(basefile_path, "r") as f:
            #    self.pet_template = yaml.safe_load(f) or {}

            self.write_lstm_input_files(config_dir, basefile_path, member_id=member_id, tag=tag)


    def write_lstm_input_files(self, config_dir, basefile_path, member_id=1, tag="cfg"):

        if self.ctx.ensemble_enabled and "LSTM" in self.ctx.ensemble_models:
            pass
        elif (member_id == 1):
            tag = "cfg"
        else:
            return

        lstm_dir = os.path.join(self.output_dir, config_dir)
        self.create_directory(lstm_dir)

        with open(basefile_path, "r") as f:
            base_file = yaml.safe_load(f)

        train_cfg_files  = base_file.get("train_cfg_file", [])
        attributes_files = base_file.get("attributes_file", [])
        
        if isinstance(train_cfg_files, str):
            train_cfg_files = [train_cfg_files]
            
        if isinstance(attributes_files, str):
            attributes_files = [attributes_files]
            
        if len(train_cfg_files) != len(attributes_files):
            raise ValueError(
                "train_cfg_file and attributes_file must have the same length"
            )

        ## mappings
        static_attributes_cfg = base_file.get("static_attributes", {})
        static_attrs_parquet_mapping = static_attributes_cfg.get("training", {}) # mapping between training attrs and names in the parquet file
        static_attrs_bmi_mapping = static_attributes_cfg.get("bmi", {})
    
        config_ensemble = [] # lstm ensemble using different training weights

        for train_f, attr_f in zip(train_cfg_files, attributes_files):

            train_path = os.path.normpath(os.path.join(self.ctx.sandbox_dir, "extern", "lstm", train_f))

            attr_path = os.path.normpath(os.path.join(self.ctx.sandbox_dir, attr_f))

            if not os.path.exists(train_path):
                raise FileNotFoundError(f"Missing attributes file: {train_path}")

            # Load training config
            with open(train_path, "r") as f:
                train_cfg = yaml.safe_load(f)

            static_attrs_training = train_cfg.get("static_attributes", [])

            # Load attributes parquet
            if not os.path.exists(attr_path):
                raise FileNotFoundError(f"Missing attributes file: {attr_path}")

            df = pd.read_parquet(attr_path).set_index("divide_id")

            config_ensemble.append({
                "train_cfg_path": train_path,
                "static_attrs_parquet": df,
                "static_attrs_training": static_attrs_training
            })


        gpkg_name = os.path.basename(self.static_data.gpkg_file).split(".")[0]
        gage_id = gpkg_name.split("_")[1]
        

        for catID in self.static_data.catids:
            cat_name = f"cat-{catID}"
            
            fname_lstm = f'lstm_{tag}_{cat_name}.yaml'
            lstm_file = os.path.join(lstm_dir, fname_lstm)

            config = {
                "train_cfg_file": [c["train_cfg_path"] for c in config_ensemble],
                "basin_id": gage_id,
                "verbose": 0,
                "time_step": "1 hour",
                "initial_state": "zero",
                "static_attributes": {}
            }

            for member in config_ensemble:
                df = member["static_attrs_parquet"]
                attrs = member["static_attrs_training"]
            
                if cat_name not in df.index:
                    raise KeyError(f"{cat_name} not found in attributes parquet")
            
                for attr in attrs:
                    if attr not in static_attrs_parquet_mapping:
                        print(f"Warning: {attr} missing in mapping, skipping")
                        continue

                    parquet_col = static_attrs_parquet_mapping[attr]

                    if parquet_col not in df.columns:
                        raise ValueError(f"Missing column {parquet_col} in parquet")

                    config["static_attributes"][attr] = float(df.loc[cat_name][parquet_col])
                
            for bmi_name, parquet_col in static_attrs_bmi_mapping.items():
                found = False
                for member in config_ensemble:
                    df = member["static_attrs_parquet"]
                    if parquet_col in df.columns and cat_name in df.index:
                        config[bmi_name] = float(df.loc[cat_name][parquet_col])
                        found = True
                        break

                if not found:
                    raise ValueError(f"BMI column {parquet_col} not found in any attributes file")

            with open(lstm_file, "w") as f:
                yaml.dump(config, f, sort_keys=False)

