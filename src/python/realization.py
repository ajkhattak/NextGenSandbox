############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
# Date    : September 28, 2023
############################################################################################

"""
The script generates realization files for a given model coupling option
 - inputs  : see main function for inputs (taken as arguments)
 - outputs : writes nextgen realization file for the basin
"""


import os
import sys
import glob
import json
import argparse
import shutil
import json
from pathlib import Path

from src.python.model_instances import build_model_instances

class RealizationGenerator:
    def __init__(self,
                 ctx,
                 forcing_dir,
                 output_dir,
                 ensemble_member_id,
                 ):
        self.ctx = ctx
        self.ngen_dir    = self.ctx.ngen_dir 
        self.forcing_dir = forcing_dir
        self.output_dir  = output_dir
        self.formulation = self.ctx.formulation
        self.simulation_time = self.ctx.simulation_time
        self.config_dir      = os.path.join(output_dir,"configs")
        self.forcing_format  = self.ctx.forcing_format
        self.verbosity       = self.ctx.verbosity
        self.ngen_cal_type   = self.ctx.task_type
        self.domain          = self.ctx.domain.lower()
        self.ensemble_enabled   = self.ctx.ensemble_enabled
        self.ensemble_size      = len([m.strip() for m in ensemble_models.split(",")]) if self.ensemble_enabled else 1
        self.ensemble_member_id = ensemble_member_id

        self.disable_divide_output = self.ctx.disable_divide_output

        if isinstance(self.ctx.ensemble_models, str):
            self.ensemble_models = self.ctx.ensemble_models.lower()
        elif isinstance(self.ctx.ensemble_models, (list, tuple, set)):
            self.ensemble_models = [m.lower() for m in self.ctx.ensemble_models]
        else:
            self.ensemble_models = []
        
        realization_name = self.formulation.replace(",","_").lower()

        # the same tag is used in the config files names
        self.tag = f"cfg_tile-{self.ensemble_member_id}" if self.ensemble_enabled else "cfg"

        self.realization_file = (
            Path(self.output_dir)
            / "configs"
            / (
                f"realization_{realization_name}_{self.tag}.json"
                if self.ensemble_enabled
                else f"realization_{realization_name}.json"
            )
        )

        if not os.path.exists(self.forcing_dir):
            sys.exit(f"Forcing directory does not exist: {self.forcing_dir}")

        self.model_registry = self.ctx.model_registry


    def write_realization_file(self):

        root = {
            "time": {
                "start_time": self.simulation_time["start_time"],
                "end_time": self.simulation_time["end_time"],
                "output_interval": 3600
            },
            "global": {
                "formulations": "to_be_filled_in",
                "forcing": {
                    "file_pattern": ".*{{id}}.*.csv",
                    "path": self.forcing_dir,
                    "provider": "CsvPerFeature"
                }
            }
        }
        
        if self.ngen_cal_type not in ['calibration', 'validation', 'calibvalid', 'restart']:
            root["output_root"] = os.path.join(self.output_dir, "outputs","div")

        if self.ensemble_enabled:
             root["output_root"] = os.path.join(self.output_dir, "output", f"output_{self.tag}")
             os.makedirs(root["output_root"], exist_ok=True)

        if self.forcing_format == ".nc":
            root["global"]["forcing"] = {
                "path": self.forcing_dir,
                "provider": "NetCDF"
            }


        if "t-route" in self.formulation.lower() and not self.ensemble_enabled:
            root["routing"] = {
                "t_route_config_file_with_path": os.path.join(self.config_dir, "troute_config.yaml")
            }

        global_block = {
            "name": "bmi_multi",
            "params": {
                "name": "bmi_multi",
                "model_type_name": "",
                "init_config": "",
                "allow_exceed_end_time": False,
                "fixed_time_step": False,
                "uses_forcing_file": False
            }
        }

        model_type_name = ""
        main_output_variable = ""
        modules = []

        model_type_name = self.formulation.replace(",","_")

        modules = []

        excluded = {"SACSMA", "LSTM", "DHBV"}  # don't add sloth

        if excluded.isdisjoint(self.model_registry):

            instance =  self.model_registry.get("SLOTH")[0]
            modules = [self.get_sloth_block(instance)]


        output_variables = []
        output_header_fields = []

        # NOM
        for instance in self.model_registry.get("NOM", []):
            modules.append(self.get_noah_owp_modular_block(instance))

        # PET
        for instance in self.model_registry.get("PET", []):
            modules.append(self.get_pet_block(instance, var_names_map=True))

        # SNOW17
        for instance in self.model_registry.get("SNOW17", []):
            modules.append(self.get_snow17_block(instance))

        # SAC-SMA
        for instance in self.model_registry.get("SACSMA", []):
            main_output_variable = "tci"
            output_variables = ["tci"]
            modules.append(self.get_sacsma_block(instance))

        # TOPMODEL
        for instance in self.model_registry.get("TOPMODEL", []):
            main_output_variable = "Qout"
            #output_variables = ["Qout"]
            modules.append(self.get_topmodel_block(instance))


        # CFE
        for instance in self.model_registry.get("CFE", []):
            main_output_variable = "Q_OUT"
            modules.append(self.get_cfe_block(instance))

        # CASAM
        for instance in self.model_registry.get("CASAM", []):
            main_output_variable = "total_discharge"
            output_variables = ["total_discharge"]
            modules.append(self.get_casam_block(instance))

        # SMP
        for instance in self.model_registry.get("SMP", []):
            modules.append(self.get_smp_block(instance))

        # SFT
        for instance in self.model_registry.get("SFT", []):
            modules.append(self.get_sft_block(instance))

        # LSTM
        for instance in self.model_registry.get("LSTM", []):
            main_output_variable = "land_surface_water__runoff_depth"
            output_variables = ["land_surface_water__runoff_depth"]
            modules.append(self.get_lstm_block(instance))


        # DHBV
        for instance in self.model_registry.get("DHBV", []):
            main_output_variable = "land_surface_water__runoff_volume_flux"
            modules.append(self.get_dhbv_block(instance))

        #output_header_fields = ["rain_rate", "q_out", "PET", "AET"]

        # disable catchment output, later move this to base realization file
        
        root["disable_catchment_output"] = True if self.disable_divide_output else False
        
        
        output_header_fields = ["Qout"]

        if (len(main_output_variable) == 0):
            str_msg = f"main_output_variable at the multi_bmi block level is empty, needs to be an output variable from the models."
            raise ValueError(str_msg)
        
        #assert len(output_variables) == len(output_header_fields)

        global_block["params"]["model_type_name"] = model_type_name
        global_block["params"]["main_output_variable"] = main_output_variable
        #global_block["params"]["output_variables"] = output_variables
        #global_block["params"]["output_header_fields"] = output_header_fields
        global_block["params"]["modules"] = modules

        root["global"]["formulations"] = [global_block]

        with open(self.realization_file, 'w') as outfile:
            json.dump(root, outfile, indent=4, separators=(", ", ": "), sort_keys=False)

    def configure_model_instances(self):

        if not hasattr(self, "model_registry"):
            return

        for model_name, instances in self.model_registry.items():

            if model_name in {"T-ROUTE"}:
                continue

            for instance in instances:

                instance.config_dir = Path(self.output_dir) / "configs"  / instance.name

                if not instance.config_dir.exists() and not model_name == "SLOTH":
                    print(
                        f"{model_name} config directory does not exist: "
                        f"{instance.config_dir}"
                    )
                    sys.exit(0)

                # Resolve executable/library directory
                if getattr(instance, "exe_dir", None):
                    exe_dir = Path(instance.exe_dir)
                else:
                    exe_dir = Path(self.ngen_dir) / "extern" / instance.repo_name

                if not exe_dir.exists():
                    instance.exe_dir = ""
                    continue

                # Search recursively for shared libraries
                pattern = "lib*.so" if sys.platform.startswith("linux") else "lib*.dylib"
                matches = list(exe_dir.rglob(pattern))

                if not matches:
                    instance.exe_dir = ""
                    continue

                # Prefer shortest / unversioned library
                matches = sorted(matches, key=lambda x: len(x.name))

                # Handle special cases
                if instance.repo_name in ['noah-owp-modular',"snow17"]:
                    if instance.repo_name == "noah-owp-modular":
                        preferred = [m for m in matches if "surfacebmi" in m.name]
                        if preferred:
                            matches = preferred
                    if instance.repo_name == "snow17":
                        preferred = [m for m in matches if "snow17" in m.name]
                        if preferred:
                            matches = preferred

                instance.exe_dir = str(matches[0])


    def get_pet_block(self, instance, var_names_map=False):

        tag = self.tag if (self.ensemble_enabled and "pet" in self.ensemble_models) else "cfg"

            
        block = {
            "name": "bmi_c",
            "params": {
                "name": "bmi_c",
                "model_type_name": "PET",
                "library_file": instance.exe_dir,
                "forcing_file": "",
                "init_config": os.path.join(self.config_dir, f'pet/pet_{tag}_{{{{id}}}}.txt'),
                "allow_exceed_end_time": "true",
                "main_output_variable": "water_potential_evaporation_flux",
                "registration_function": "register_bmi_pet",
                "uses_forcing_file": "false"
            }
        }
        
        # AORC forcing names
        if (self.domain == "conus" and var_names_map):
            block['params']['variables_names_map'] = {
                "PRCPNONC": "APCP_surface",
                "Q2": "SPFH_2maboveground",
                "SFCTMP": "TMP_2maboveground",
                "UU": "UGRD_10maboveground",
                "VV": "VGRD_10maboveground",
                "LWDN": "DLWRF_surface",
                "SOLDN": "DSWRF_surface",
                "SFCPRS": "PRES_surface"
            }
        elif (self.domain == "oconus" and var_names_map):
            block['params']['variables_names_map'] = {
                "PRCPNONC": "RAINRATE",
                "Q2": "Q2D",
                "SFCTMP": "T2D",
                "UU": "U2D",
                "VV": "V2D",
                "LWDN": "LWDOWN",
                "SOLDN": "SWDOWN",
                "SFCPRS": "PSFC"
            }
        elif (var_names_map):
              block['params']['variables_names_map'] = {
                  "PRCPNONC": "atmosphere_water__liquid_equivalent_precipitation_rate",
                  "Q2": "atmosphere_air_water~vapor__relative_saturation",
                  "SFCTMP": "land_surface_air__temperature",
                  "LWDN": "land_surface_radiation~incoming~longwave__energy_flux",
                  "SOLDN": "land_surface_radiation~incoming~shortwave__energy_flux",
                  "UU": "land_surface_wind__x_component_of_velocity",
                  "VV": "land_surface_wind__y_component_of_velocity",
                  "SFCPRS": "land_surface_air__pressure"
              }
        
        return block


    def get_noah_owp_modular_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "nom" in self.ensemble_models) else "cfg"

        block = {
            "name": "bmi_fortran",
            "params": {
                "name": "bmi_fortran",
                "model_type_name": "NoahOWP",
                "main_output_variable": "QINSUR",
                #"library_file": self.lib_files['noah-owp-modular'],
                "library_file": instance.exe_dir,
                "init_config": os.path.join(self.config_dir, f'noahowp/noahowp_{tag}_{{{{id}}}}.input'),
                "allow_exceed_end_time": True,
                "fixed_time_step": False,
                "uses_forcing_file": False,
                "variables_names_map": {
                    "PRCPNONC": "atmosphere_water__liquid_equivalent_precipitation_rate",
                    "Q2": "atmosphere_air_water~vapor__relative_saturation",
                    "SFCTMP": "land_surface_air__temperature",
                    "LWDN": "land_surface_radiation~incoming~longwave__energy_flux",
                    "SOLDN": "land_surface_radiation~incoming~shortwave__energy_flux",
                    "UU": "land_surface_wind__x_component_of_velocity",
                    "VV": "land_surface_wind__y_component_of_velocity",
                    "SFCPRS": "land_surface_air__pressure"
                }
            }
        }

        # AORC names (details at the end of file)
        if (self.domain == "conus"):
            block['params']['variables_names_map'] = {
                "PRCPNONC": "APCP_surface",
                "Q2": "SPFH_2maboveground",
                "SFCTMP": "TMP_2maboveground",
                "UU": "UGRD_10maboveground",
                "VV": "VGRD_10maboveground",
                "LWDN": "DLWRF_surface",
                "SOLDN": "DSWRF_surface",
                "SFCPRS": "PRES_surface"
            }

        return block

    def get_snow17_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "snow17" in self.ensemble_models) else "cfg"

        block = {
            "name": "bmi_fortran",
            "params": {
                "name": "bmi_fortran",
                "model_type_name": "Snow17",
                "main_output_variable": "raim",
                "library_file": instance.exe_dir,
                "init_config": os.path.join(self.config_dir, f'snow17/snow17_{tag}_{{{{id}}}}.namelist.input'),
                "allow_exceed_end_time": True,
                "fixed_time_step": False,
                "uses_forcing_file": False,
                "variables_names_map": {
                    "precip": "atmosphere_water__liquid_equivalent_precipitation_rate",
                    "tair": "land_surface_air__temperature"
                }
            }
        }

        # AORC names (details at the end of file)
        if (self.domain == "conus"):
            block['params']['variables_names_map'] = {
                "precip": "APCP_surface",
                "tair": "TMP_2maboveground"
            }

        return block

    def get_sacsma_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "sacsma" in self.ensemble_models) else "cfg"
            
        block = {
            "name": "bmi_fortran",
            "params": {
                "name": "bmi_fortran",
                "model_type_name": "SacSMA",
                "main_output_variable": "tci",
                "library_file": instance.exe_dir,
                "init_config": os.path.join(self.config_dir, f'sacsma/sacsma_{tag}_{{{{id}}}}.namelist.input'),
                "allow_exceed_end_time": True,
                "fixed_time_step": False,
                "uses_forcing_file": False,
                "variables_names_map": {
                    "precip": "atmosphere_water__liquid_equivalent_precipitation_rate",
                    "tair": "land_surface_air__temperature",
                    "pet" : "water_potential_evaporation_flux"
                }
            }
        }

        # AORC names (details at the end of file)
        if (self.domain == "conus"):
            block['params']['variables_names_map'] = {
                "precip": "APCP_surface",
                "tair": "TMP_2maboveground",
                "pet" : "water_potential_evaporation_flux"
            }

        if "SNOW17" in self.formulation:
            block["params"]["variables_names_map"]["precip"] = "raim"

        return block
    
    def get_cfe_block(self, instance, cfe_standalone=False):

        variant_name = instance.name
        
        tag = self.tag if (self.ensemble_enabled and "cfe" in self.ensemble_models) else "cfg"

        block = {
            "name": "bmi_c",
            "params": {
                "name": "bmi_c",
                "model_type_name": "CFE",
                "main_output_variable": "Q_OUT",
                "library_file": instance.exe_dir,
                "init_config": os.path.join(self.config_dir, f'{variant_name}/cfe_{tag}_{{{{id}}}}.txt'),
                "allow_exceed_end_time": True,
                "fixed_time_step": False,
                "uses_forcing_file": False,
                "variables_names_map": {
                    "atmosphere_water__liquid_equivalent_precipitation_rate": "APCP_surface",
                    "water_potential_evaporation_flux": "water_potential_evaporation_flux"
                },
                "registration_function": "register_bmi_cfe"
            }
        }
        
        if cfe_standalone:
            sub_map = {
                "ice_fraction_schaake": "ice_fraction_schaake",
                "ice_fraction_xinanjiang": "ice_fraction_xinanjiang",
                "soil_moisture_profile": "soil_moisture_profile"
            }
            block["params"]["variables_names_map"].update(sub_map)

        if "NOM" in self.formulation and not "PET" in self.formulation:
            block["params"]["variables_names_map"]["water_potential_evaporation_flux"] = "EVAPOTRANS"

        if "NOM" in self.formulation:
            block["params"]["variables_names_map"]["atmosphere_water__liquid_equivalent_precipitation_rate"] = "QINSUR"

        if self.domain == "oconus" and not "NOM" in self.formulation:
            block["params"]["variables_names_map"]["atmosphere_water__liquid_equivalent_precipitation_rate"] = "RAINRATE"

        if "SNOW17" in self.formulation:
            block["params"]["variables_names_map"]["atmosphere_water__liquid_equivalent_precipitation_rate"] = "raim"

        return block

    def get_topmodel_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "topmodel" in self.ensemble_models) else "cfg"

        block = {
            "name": "bmi_c",
            "params": {
                "name": "bmi_c",
                "model_type_name": "TOPMODEL",
                "main_output_variable": "Qout",
                "library_file": instance.exe_dir, #self.lib_files['topmodel'],
                "init_config": os.path.join(self.config_dir, f'topmodel/topmod_{tag}_{{{{id}}}}.run'),
                "allow_exceed_end_time": True,
                "fixed_time_step": False,
                "uses_forcing_file": False,
                "variables_names_map": {
                    "atmosphere_water__liquid_equivalent_precipitation_rate": "QINSUR",
                    "water_potential_evaporation_flux": "EVAPOTRANS"
                },
                "registration_function": "register_bmi_topmodel"
            }
        }

        if not "NOM" in self.formulation and "PET" in self.formulation:
            block["params"]["variables_names_map"]["water_potential_evaporation_flux"] = "water_potential_evaporation_flux"
            block["params"]["variables_names_map"]["atmosphere_water__liquid_equivalent_precipitation_rate"] = "APCP_surface"

        if "SNOW17" in self.formulation:
            block["params"]["variables_names_map"]["atmosphere_water__liquid_equivalent_precipitation_rate"] = "raim"
            block["params"]["variables_names_map"]["water_potential_evaporation_flux"] = "water_potential_evaporation_flux"
            
        return block

    def get_sft_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "sft" in self.ensemble_models) else "cfg"

        block = {
            "name": "bmi_c++",
            "params": {
                "name": "bmi_c++",
                "model_type_name": "SoilFreezeThaw",
                "main_output_variable": "num_cells",
                "library_file": self.lib_files['SoilFreezeThaw'],
                "init_config": os.path.join(self.config_dir, f'sft/sft_{tag}_{{{{id}}}}.txt'),
                "allow_exceed_end_time": True,
                "uses_forcing_file": False,
                "variables_names_map": {
                    "ground_temperature": "TGS"
                }
            }
        }
        return block

    def get_smp_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "smp" in self.ensemble_models) else "cfg"

        block = {
            "name": "bmi_c++",
            "params": {
                "name": "bmi_c++",
                "model_type_name": "SoilMoistureProfile",
                "main_output_variable": "soil_water_table",
                "library_file": self.lib_files['SoilMoistureProfiles'],
                "init_config": os.path.join(self.config_dir, f'smp/smp_{tag}_{{{{id}}}}.txt'),
                "allow_exceed_end_time": True,
                "uses_forcing_file": False,
                "variables_names_map": {
                    "soil_storage": "SOIL_STORAGE",
                    "soil_storage_change": "SOIL_STORAGE_CHANGE"
                }
            }
        }

        if "CFE" in self.formulation:
            name_map = {
                "soil_storage": "SOIL_STORAGE",
                "soil_storage_change": "SOIL_STORAGE_CHANGE"
            }
        elif "CASAM" in self.formulation:
            name_map = {
                "soil_storage": "sloth_soil_storage",
                "soil_storage_change": "sloth_soil_storage_change",
                "soil_moisture_wetting_fronts": "soil_moisture_wetting_fronts",
                "soil_depth_wetting_fronts": "soil_depth_wetting_fronts",
                "num_wetting_fronts": "soil_num_wetting_fronts"
            }
        else:
            print("coupled_models name should be nom_cfe_smp_sft or nom_casam_smp_sft, provided is ", self.coupled_models)
            quit()
        block["params"]["variables_names_map"] = name_map
        return block

    def get_casam_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "casam" in self.ensemble_models) else "cfg"

            
        #note the model_type_name should be LGAR as this name is currently supported by ngen-cal for calibration
        block = {
            "name": "bmi_c++",
            "params": {
                "name": "bmi_c++",
                "model_type_name": "LGAR",
                "main_output_variable": "precipitation_rate",
                "library_file": instance.exe_dir,
                "init_config": os.path.join(self.config_dir, f'casam/casam_{tag}_{{{{id}}}}.txt'),
                "allow_exceed_end_time": True,
                "uses_forcing_file": False,
                "variables_names_map": {
                    "precipitation_rate": "APCP_surface",
                    "potential_evapotranspiration_rate": "water_potential_evaporation_flux"
                }
            }
        }
        
        if "NOM" in self.formulation:
            block["params"]["variables_names_map"]["precipitation_rate"] = "QINSUR"
        if "PET" not in self.formulation:
            block["params"]["variables_names_map"]["potential_evapotranspiration_rate"] = "EVAPOTRANS"

        return block

    def get_sloth_block(self, instance):

        block = {
            "name": "bmi_c++",
            "params": {
                "name": "bmi_c++",
                "model_type_name": "SLOTH",
                "main_output_variable": "z",
                "library_file": instance.exe_dir,
                "init_config": '/dev/null',
                "allow_exceed_end_time": True,
                "fixed_time_step": False,
                "uses_forcing_file": False,
            }
        }
        params = {}
        if "CFE" in self.formulation and not "SFT" in self.formulation:
            params = {
                "ice_fraction_schaake(1,double,m,node)": 0.0,
                "ice_fraction_xinanjiang(1,double,1,node)": 0.0,
                "soil_moisture_profile(1,double,1,node)": 0.0
            }
        elif "CASAM" in self.formulation and not "SFT" in self.formulation:
            params = {
                "soil_temperature_profile(1,double,K,node)": 275.15
            }
        elif "SMP" in self.formulation and not "TOPMODEL" in self.formulation and not "CASAM" in self.formulation:
            params = {
                "soil_moisture_wetting_fronts(1,double,1,node)": 0.0,
                "soil_depth_wetting_fronts(1,double,1,node)": 0.0,
                "num_wetting_fronts(1,int,1,node)": 1.0,
                "Qb_topmodel(1,double,1,node)": 0.0,
                "Qv_topmodel(1,double,1,node)": 0.0,
                "global_deficit(1,double,1,node)": 0.0
            }
        elif "SMP" in self.formulation and "CASAM" in self.formulation:
            params = {
                "sloth_soil_storage(1,double,m,node)": 1.0E-10,
                "sloth_soil_storage_change(1,double,m,node)": 0.0,
                "Qb_topmodel(1,double,1,node)": 0.0,
                "Qv_topmodel(1,double,1,node)": 0.0,
                "global_deficit(1,double,1,node)": 0.0
            }
        elif "TOPMODEL" in self.formulation:
            params = {
                "tmp(1,double,1,node)": -999.9
            }
        elif "LSTM" in self.formulation:
            return block
        elif "DHBV" in self.formulation:
            return block
        else:
            msg = "SLoTH model not setup for this formulation yet: " + self.formulation
            sys.exit(msg)
        block["params"]["model_params"] = params

        return block

    def get_lstm_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "lstm" in self.ensemble_models) else "cfg"

        block = {
            "name": "bmi_python",
            "params": {
                "python_type": "lstm.bmi_lstm.bmi_LSTM",
                "model_type_name": "bmi_LSTM",
                "main_output_variable": "land_surface_water__runoff_depth",
                "allow_exceed_end_time": True,
                "fixed_time_step": False,
                "uses_forcing_file": False,
                "init_config": os.path.join(self.config_dir, f'lstm/lstm_{tag}_{{{{id}}}}.yaml'),
                "variables_names_map": {
                    "atmosphere_water__liquid_equivalent_precipitation_rate": "APCP_surface",
                    "land_surface_air__temperature": "TMP_2maboveground",
                    "atmosphere_air_water~vapor__relative_saturation": "SPFH_2maboveground",
                    "land_surface_radiation~incoming~longwave__energy_flux": "DLWRF_surface",
                    "land_surface_radiation~incoming~shortwave__energy_flux": "DSWRF_surface",
                    "land_surface_wind__x_component_of_velocity": "UGRD_10maboveground",
                    "land_surface_wind__y_component_of_velocity": "VGRD_10maboveground",
                    "land_surface_air__pressure": "PRES_surface"
                }
            }
        }

        return block


    def get_dhbv_block(self, instance):

        tag = self.tag if (self.ensemble_enabled and "lstm" in self.ensemble_models) else "cfg"

        block = {
            "name": "bmi_python",
            "params": {
                "python_type": "dhbv2.mts_bmi.MtsDeltaModelBmi",
                "model_type_name": "DeltaModelBmi",
                "main_output_variable": "land_surface_water__runoff_volume_flux",
                "allow_exceed_end_time": True,
                "fixed_time_step": False,
                "uses_forcing_file": False,
                "init_config": os.path.join(self.config_dir, f'dhbv/dhbv_{tag}_{{{{id}}}}.yaml'),
                "variables_names_map": {
                    "atmosphere_water__liquid_equivalent_precipitation_rate": "APCP_surface",
                    "land_surface_air__temperature": "TMP_2maboveground",
                    "atmosphere_air_water~vapor__relative_saturation": "SPFH_2maboveground",
                    "land_surface_radiation~incoming~longwave__energy_flux": "DLWRF_surface",
                    "land_surface_radiation~incoming~shortwave__energy_flux": "DSWRF_surface",
                    "land_surface_wind__x_component_of_velocity": "UGRD_10maboveground",
                    "land_surface_wind__y_component_of_velocity": "VGRD_10maboveground",
                    "land_surface_air__pressure": "PRES_surface",
                    "land_surface_water__runoff_volume_flux": "streamflow_cms"
                }
            }
        }

        return block
    
    def get_jinjabmi_unit_conversion_block(self):
        block_jinjabmi = {
            "name": "bmi_python",
            "params": {
                "model_type_name": "jinjabmi",
                "python_type": "jinjabmi.Jinja",
                "init_config": os.path.join(self.config_dir, "jinjabmi/baseline_support.yml"),
                "allow_exceed_end_time": True,
                "main_output_variable": "actual_ET_input",
                "uses_forcing_file": False,
                "variables_names_map": {
                    "actual_ET_input": "ACTUAL_ET",
                    "direct_runoff_input": "DIRECT_RUNOFF",
                    "giuh_runoff_input": "GIUH_RUNOFF",
                    "soil_storage_input": "SOIL_STORAGE",
                    "catchment_area_input": "sloth_catchment_area",
                    "deep_gw_to_channel_flux_input": "DEEP_GW_TO_CHANNEL_FLUX",
                    "soil_to_gw_flux_input": "SOIL_TO_GW_FLUX",
                    "giuh_runoff_input": "GIUH_RUNOFF"
                }
            }
        }

        block_unit_conversion = {
            "name": "bmi_c++",
            "params": {
                "model_type_name": "bmi_c++_sloth",
                "library_file": self.lib_files['sloth'],
                "init_config": "/dev/null",
                "allow_exceed_end_time": True,
                "main_output_variable": "nwm_ponded_depth",
                "uses_forcing_file": False,
                "model_params": {
                    "nwm_ponded_depth(1,double,mm,node,nwm_ponded_depth_output)": 0.0,
                    "ACTUAL_ET_mm(1,double,mm,node,ACTUAL_ET)": 0.0
                }
            }
        }

        return [block_jinjabmi, block_unit_conversion]

#############################################################################
# module for NOAH-OWP-Modular (NOM) block in the nextgen realization file 
# @param config_dir : input directory of the NOM config files
# @param model_exe : path to NOM executable
# Units and different forcing variables names and their mapping
# Nels script (AORC)         Jason Ducker script    NoahOWP BMI forcing vars names
# APCP_surface [kg/m2/sec]   <-> RAINRATE [mm/sec] <-> PRCPNONC [mm/sec]
# DLWRF_surface [W m-2]      <-> LWDOWN [W m-2]    <-> LWDN [W m-2]
# DSWRF_surface [W m-2]      <-> SWDOWN [W m-2]    <-> SOLDN [W m-2]
# TMP_2maboveground [K]      <-> T2D [K]           <-> SFCTMP
# UGRD_10maboveground [m/s]  <-> U2D [m s-1]       <-> UU [m/s]
# VGRD_10maboveground [m/s]  <-> V2D [m s-1]       <-> VV [m/s]
 # PRES_surface [Pa]         <-> PSFC [Pa]         <-> SFCPRS [Pa]
# SPFH_2maboveground [kg/kg] <-> Q2D [kg kg^-1]    <-> Q2 [kg/kg]
#############################################################################
