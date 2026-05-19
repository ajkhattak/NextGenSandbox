import os
import sys
import yaml

from src.python.registry import register_model
from src.python.configuration import ConfigurationGenerator


@register_model("SACSMA")
class SACSMAGenerator(ConfigurationGenerator):
    def __init__(self, ctx):
        super().__init__(ctx)

        default_variant = [
            {
                "name": "sacsma",
                "basefile": "config_sacsma.namelist.input"
            }
        ]

        self.variants = (
            self.ctx.model_variants.get("SACSMA")
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
                raise FileNotFoundError(f"Missing SACSMA basefile: {basefile_path}")

            with open(basefile_path, "r") as f:
                self.cfe_template = yaml.safe_load(f) or {}


            self.write_sacsma_input_files(name, member_id=member_id, tag=tag)

    def write_sacsma_input_files(self, name, member_id=1, tag="cfg"):

        # ensemble logic
        if self.ctx.ensemble_enabled and "SACSMA" in (self.ctx.ensemble_models or "").upper():
            pass
        elif member_id == 1:
            tag = "cfg"
        else:
            return

        sacsma_dir = os.path.join(self.ctx.output_dir, f"configs/{name}")
        self.create_directory(sacsma_dir)

        sacsma_basefile = os.path.join(
            self.ctx.sandbox_dir,
            "configs/basefiles/config_sacsma.namelist.input"
        )

        sacsma_param_basefile = os.path.join(
            self.ctx.sandbox_dir,
            "configs/basefiles/sacsma_params_cat.HHWM8.txt"
        )

        if not os.path.exists(sacsma_basefile):
            sys.exit(f"Sample Sac-SMA config file does not exist: {sacsma_basefile}")

        # Read all lines from the base template
        with open(sacsma_basefile, "r") as infile:
            lines = infile.readlines()

        with open(sacsma_param_basefile, "r") as infile_param:
            lines_param = infile_param.readlines()

        for catID in self.ctx.catids:
            cat_name = f"cat-{catID}"
            fname_sacsma = f"sacsma_{tag}_{cat_name}.namelist.input"
            fname_sacsma_param = f"sacsma_params_{tag}_{cat_name}.txt"

            sacsma_file = os.path.join(sacsma_dir, fname_sacsma)
            sacsma_param_file = os.path.join(sacsma_dir, fname_sacsma_param)

            with open(sacsma_file, "w") as outfile:
                for line in lines:

                    if line.strip().startswith("!"):
                        outfile.write(line)
                        continue

                    # Replace parameters
                    if line.strip().startswith("main_id"):
                        outfile.write(f'main_id             = "{cat_name}"     ! basin label or gage id\n')
                    elif line.strip().startswith("forcing_root"):
                        outfile.write(f'forcing_root        = "{self.ctx.forcing_dir}"\n')
                    elif line.strip().startswith("output_root"):
                        outfile.write(f'output_root         = "{self.ctx.output_dir}/output"\n')
                    elif line.strip().startswith("sac_param_file"):
                        outfile.write(f'sac_param_file   = "{sacsma_param_file}"\n')
                    else:
                        outfile.write(line)

            area = self.ctx.gdf["divide_area"][cat_name]

            # write param files
            with open(sacsma_param_file, "w") as outfile_param:
                for line in lines_param:

                    if line.strip().startswith("!"):
                        outfile_param.write(line)
                        continue

                    # Replace parameters
                    if line.strip().startswith("hru_id"):
                        outfile_param.write(f"hru_id {cat_name}\n")
                    elif line.strip().startswith("hru_area"):
                        outfile_param.write(f"hru_area {area}\n")
                    else:
                        outfile_param.write(line)
