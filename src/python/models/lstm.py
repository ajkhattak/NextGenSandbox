import os
import sys
import yaml
import pandas as pd
from pathlib import Path

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

        for instance in self.instances:

            config_dir = instance.config_dir
            basefile = instance.basefile

            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")

            if not os.path.exists(basefile_path):
                raise FileNotFoundError(f"Missing LSTM basefile: {basefile_path}")

            #with open(basefile_path, "r") as f:
            #    self.lstm_template = yaml.safe_load(f) or {}

            self.write_lstm_input_files(config_dir, basefile_path, member_id=member_id, tag=tag)

    def resolve_train_cfg_path(self, train_cfg_file):
        train_path = Path(train_cfg_file).expanduser()
        if train_path.is_absolute():
            return train_path

        sandbox_data_dir = Path(os.environ["SANDBOX_DATA"])
        candidates = [
            sandbox_data_dir / "lstm" / train_path,
            self.ctx.sandbox_dir / train_path,
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return candidates[0]

    def resolve_attributes_path(self, attributes_file):
        attr_path = Path(attributes_file).expanduser()
        if attr_path.is_absolute():
            return attr_path

        sandbox_data_dir = Path(os.environ["SANDBOX_DATA"])
        candidates = [
            sandbox_data_dir / "lstm" / attr_path,
            self.ctx.sandbox_dir / attr_path,
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return candidates[0]

    def prepare_training_config(self, train_path: Path, lstm_dir: Path):
        with train_path.open("r") as f:
            train_cfg = yaml.safe_load(f)

        run_dir = train_path.parent.resolve()
        train_cfg["run_dir"] = str(run_dir)

        scaler_file = run_dir / "train_data" / "train_data_scaler.yml"
        if not scaler_file.exists():
            raise FileNotFoundError(
                f"Missing LSTM scaler file: {scaler_file}"
            )

        epochs = train_cfg.get("epochs")
        if epochs is not None:
            trained_model_file = run_dir / f"model_epoch{str(epochs).zfill(3)}.pt"
            if not trained_model_file.exists():
                raise FileNotFoundError(
                    f"Missing LSTM weights file: {trained_model_file}"
                )

        patched_train_cfg = lstm_dir / f"{train_path.stem}_patched.yml"
        with patched_train_cfg.open("w") as f:
            yaml.dump(train_cfg, f, sort_keys=False)

        return train_cfg, patched_train_cfg


    def write_lstm_input_files(self, config_dir, basefile_path, member_id=1, tag="cfg"):

        if self.ctx.ensemble_enabled and "LSTM" in self.ctx.ensemble_models:
            pass
        elif (member_id == 1):
            tag = "cfg"
        else:
            return

        lstm_dir = Path(self.output_dir) / config_dir
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

        for i, (train_f, attr_f) in enumerate(zip(train_cfg_files, attributes_files), start=1):

            train_path = self.resolve_train_cfg_path(train_f).resolve()

            attr_path = self.resolve_attributes_path(attr_f).resolve()

            if not train_path.exists():
                raise FileNotFoundError(f"Missing LSTM training config file: {train_path}")

            train_cfg, patched_train_cfg = self.prepare_training_config(
                train_path=train_path,
                lstm_dir=lstm_dir
            )

            static_attrs_training = train_cfg.get("static_attributes", [])

            # Load attributes parquet
            if not attr_path.exists():
                raise FileNotFoundError(f"Missing attributes file: {attr_path}")

            df = pd.read_parquet(attr_path).set_index("divide_id")

            config_ensemble.append({
                "train_cfg_path": str(patched_train_cfg),
                "static_attrs_parquet": df,
                "static_attrs_training": static_attrs_training
            })


        gpkg_name = os.path.basename(self.static_data.gpkg_file).split(".")[0]
        gage_id = gpkg_name.split("_")[1]
        

        for catID in self.static_data.catids:
            cat_name = f"cat-{catID}"
            
            fname_lstm = f'lstm_{tag}_{cat_name}.yaml'
            lstm_file = lstm_dir / fname_lstm

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

            with lstm_file.open("w") as f:
                yaml.dump(config, f, sort_keys=False)
