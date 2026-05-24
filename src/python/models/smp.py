import os
from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator


@register_model("SMP")
class SMPConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

    def _write_input_files(self, member_id, tag):
        self.write_smp_input_files(member_id=member_id, tag=tag)

    def write_smp_input_files(self, cfe_coupled, casam_coupled=False, member_id=1, tag="cfg"):

        # ensemble logic
        if self.ctx.ensemble_enabled and "SMP" in (self.ctx.ensemble_models or "").upper():
            pass
        elif member_id == 1:
            tag = "cfg"
        else:
            return

        smp_dir = os.path.join(self.ctx.output_dir, "configs", "smp")
        self.create_directory(smp_dir)

        soil_z = "0.1,0.5,1.0,2.0"

        for catID in self.ctx.catids:
            cat_name = "cat-" + str(catID)
            soil_id = self.ctx.gdf["ISLTYP"][cat_name]

            smp_params = [
                "verbosity=none",
                f'soil_params.smcmax={self.ctx.gdf["soil_smcmax"][cat_name]}[m/m]',
                f'soil_params.b={self.ctx.gdf["soil_b"][cat_name]}[]',
                f'soil_params.satpsi={self.ctx.gdf["soil_satpsi"][cat_name]}[m]',
                f'soil_z={soil_z}[m]',
                "soil_moisture_fraction_depth=1.0[m]"
            ]

            if cfe_coupled:
                smp_params += [
                    "soil_storage_model=conceptual",
                    "soil_storage_depth=2.0"
                ]
            elif casam_coupled:
                smp_params += [
                    "soil_storage_model=layered",
                    "soil_moisture_profile_option=constant",
                    "soil_depth_layers=2.0",
                    "water_table_depth=10[m]"
                ]

            fname_smp = f"smp_{tag}_{cat_name}.txt"
            smp_file = os.path.join(smp_dir, fname_smp)

            with open(smp_file, "w") as f:
                f.writelines("\n".join(smp_params))
