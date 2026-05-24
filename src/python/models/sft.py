import os
import sys
import pandas as pd

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator


@register_model("SFT")
class SFTConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

    def _write_input_files(self, member_id, tag):
        self.write_sft_input_files(member_id=member_id, tag=tag)

    def write_sft_input_files(self, member_id=1, tag="cfg"):

        # ensemble logic
        if self.ctx.ensemble_enabled and "SFT" in (self.ctx.ensemble_models or "").upper():
            pass
        elif member_id == 1:
            tag = "cfg"
        else:
            return

        sft_dir = os.path.join(self.ctx.output_dir, "configs", "sft")
        self.create_directory(sft_dir)

        if self.ctx.surface_water_partitioning_scheme not in ["Schaake", "Xinanjiang"]:
            sys.exit("Runoff scheme should be: Schaake or Xinanjiang")

        ncells = 4  # 19
        soil_z = "0.1,0.15,0.18,0.23,0.29,0.36,0.44,0.55,0.69,0.86,1.07,1.34,1.66,2.07,2.58,3.22,4.01,5.0,6.0"
        soil_z = "0.1,0.5,1.0,2.0"
        delimiter = ","
        nsteps_yr = 365 * 24

        for catID in self.ctx.catids:
            cat_name = "cat-" + str(catID)

            MAAT = [str(285.0)] * ncells
            MAAT = delimiter.join(MAAT)

            soil_id = self.ctx.gdf["ISLTYP"][cat_name]

            sft_params = [
                "verbosity=none",
                "soil_moisture_bmi=1",
                "end_time=1.0[d]",
                "dt=1.0[h]",
                f'soil_params.smcmax={self.ctx.gdf["soil_smcmax"][cat_name]}[m/m]',
                f'soil_params.b={self.ctx.gdf["soil_b"][cat_name]}[]',
                f'soil_params.satpsi={self.ctx.gdf["soil_satpsi"][cat_name]}[m]',
                f'soil_params.quartz={self.ctx.soil_class_NWM["QTZ"][soil_id]}[]',
                f'ice_fraction_scheme={self.ctx.surface_water_partitioning_scheme}',
                f'soil_z={soil_z}[m]',
                f'soil_temperature={MAAT}[K]'
            ]

            fname_sft = f"sft_{tag}_{cat_name}.txt"
            sft_file = os.path.join(sft_dir, fname_sft)

            with open(sft_file, "w") as f:
                f.writelines("\n".join(sft_params))
