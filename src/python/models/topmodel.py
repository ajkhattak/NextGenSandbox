import os
import json
import pandas as pd
import numpy as np

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator

# NOTE: Use ctx attributes (not self.<attr>)

@register_model("TOPMODEL")
class TopmodelConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

        self.instances = self.ctx.model_registry.get("TOPMODEL")

    def _write_input_files(self, member_id, tag):
        for variant_cfg in self.instances:

            config_dir = variant_cfg.config_dir
            basefile = variant_cfg.basefile

            basefile_path = os.path.join(self.ctx.sandbox_dir, f"configs/basefiles/{basefile}")

            #if not os.path.exists(basefile_path):
            #    raise FileNotFoundError(f"Missing TOPMODEL basefile: {basefile_path}")
            
            #with open(basefile_path, "r") as f:
            #    self.pet_template = yaml.safe_load(f) or {}

            self.write_topmodel_input_files(config_dir, basefile_path, member_id=member_id, tag=tag)


    def write_topmodel_input_files(self, config_dir, basefile_path, member_id=1, tag="cfg"):

        if self.ctx.ensemble_enabled and "topmodel" in (self.ctx.ensemble_models or "").lower():
            pass
        elif member_id == 1:
            tag = "cfg"
        else:
            return

        topmodel_dir = os.path.join(self.output_dir, config_dir)
        self.create_directory(topmodel_dir)

        for catID in self.static_data.catids:
            cat_name = 'cat-' + str(catID)

            topmod = [
                "0",
                f'{cat_name}',
                f"./forcing/{cat_name}.csv",
                f'{topmodel_dir}/subcat_{tag}_{cat_name}.dat',
                f'{topmodel_dir}/params_{tag}_{cat_name}.dat',
                f'{topmodel_dir}/topmod_{tag}_{cat_name}.out',
                f'{topmodel_dir}/hyd_{cat_name}.out'
            ]

            fname_tm = f'topmod_{tag}_{cat_name}.run'
            tm_file = os.path.join(topmodel_dir, fname_tm)
            with open(tm_file, "w") as f:
                f.writelines('\n'.join(topmod))

            params = [
                f'Extracted study basin: {cat_name}',
                "0.032  5.0  50.  3600.0  3600.0  0.05  0.0000328  0.002  0  1.0  0.02  0.1"
            ]

            fname_tm = f'params_{tag}_{cat_name}.dat'
            tm_file = os.path.join(topmodel_dir, fname_tm)
            with open(tm_file, "w") as f:
                f.writelines('\n'.join(params))

            twi_cat = json.loads(self.static_data.gdf['twi'][cat_name])
            twi_cat = pd.DataFrame(twi_cat, columns=['v', 'frequency'])
            twi_cat = twi_cat.sort_values(by=['v'], ascending=False)

            width_f = json.loads(self.static_data.gdf['width_dist'][cat_name])
            df_width_f = pd.DataFrame(width_f, columns=['v', 'frequency'])
            v_cumm = np.cumsum(df_width_f['frequency'])

            nclasses_twi = len(twi_cat['frequency'].values)
            nclasses_width_function = len(df_width_f['frequency'].values)

            subcat = [
                "1 1 1",
                f'Extracted study basin: {cat_name}',
                f'{nclasses_twi} 1',
                'replace_with_twi',
                f'{nclasses_width_function}',
                'add_width_function',
                '$mapfile.dat'
            ]

            twi_str = ''
            for freq, value in zip(twi_cat['frequency'].values, twi_cat['v'].values):
                twi_str += f"{freq:.6f} {value:.6f}\n"

            subcat[3] = twi_str.strip()

            widthf_str = ''
            for freq, value in zip(v_cumm.values, df_width_f['v'].values):
                widthf_str += f"{freq:.6f} {value:.6f} "

            subcat[5] = widthf_str.strip()

            fname_tm = f'subcat_{tag}_{cat_name}.dat'
            tm_file = os.path.join(topmodel_dir, fname_tm)
            with open(tm_file, "w") as f:
                f.writelines('\n'.join(subcat))
