import os
import sys

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator


@register_model("SNOW17")
class SNOW17ConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

        self.variants = self.ctx.model_registry.get("SNOW17")
        
    def _write_input_files(self, member_id, tag):
        
        for variant_cfg in self.variants:

            config_dir = variant_cfg.config_dir
            basefile = variant_cfg.basefile

            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")

            param_basefile = os.path.join(
                self.ctx.sandbox_dir,
                "configs/basefiles/snow17_params_cat.txt"
            )

            if not os.path.exists(basefile_path):
                raise FileNotFoundError(f"Missing Snow17 basefile: {basefile_path}")

            #with open(basefile_path, "r") as f:
            #    self.pet_template = yaml.safe_load(f) or {}

            self.write_snow17_input_files(config_dir, basefile_path, param_basefile,
                                          member_id=member_id, tag=tag)


    def write_snow17_input_files(self, config_dir, basefile_path, param_basefile,
                                 member_id=1, tag="cfg"):

        # ensemble logic
        if self.ctx.ensemble_enabled and "SNOW17" in (self.ctx.ensemble_models or "").upper():
            pass
        elif member_id == 1:
            tag = "cfg"
        else:
            return

        snow17_dir = os.path.join(self.output_dir, config_dir)
        self.create_directory(snow17_dir)
        

        # Read all lines from the base template
        with open(basefile_path, "r") as infile:
            lines = infile.readlines()

        with open(param_basefile, "r") as infile_param:
            lines_param = infile_param.readlines()

        for catID in self.static_data.catids:
            cat_name = f"cat-{catID}"
            fname_snow17 = f"snow17_{tag}_{cat_name}.namelist.input"
            fname_snow17_param = f"snow17_params_{tag}_{cat_name}.txt"

            snow17_file = os.path.join(snow17_dir, fname_snow17)
            snow17_param_file = os.path.join(snow17_dir, fname_snow17_param)

            with open(snow17_file, "w") as outfile:
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
                    elif line.strip().startswith("snow17_param_file"):
                        outfile.write(f'snow17_param_file   = "{snow17_param_file}"\n')
                    else:
                        outfile.write(line)

            area = self.static_data.gdf["divide_area"][cat_name]
            centroid_y = str(self.static_data.gdf["geometry"][cat_name].centroid.y)
            elevation_mean = self.static_data.gdf["elevation_mean"][cat_name]

            # write param files
            with open(snow17_param_file, "w") as outfile_param:
                for line in lines_param:

                    if line.strip().startswith("!"):
                        outfile_param.write(line)
                        continue

                    # Replace parameters
                    if line.strip().startswith("hru_id"):
                        outfile_param.write(f"hru_id {cat_name}\n")
                    elif line.strip().startswith("hru_area"):
                        outfile_param.write(f"hru_area {area}\n")
                    elif line.strip().startswith("latitude"):
                        outfile_param.write(f"latitude {centroid_y}\n")
                    elif line.strip().startswith("elev"):
                        outfile_param.write(f"elev {elevation_mean}\n")
                    else:
                        outfile_param.write(line)
