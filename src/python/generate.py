############################################################################################
# Author  : Ahmad Jan Khattak
# Contact : ahmad.jan.khattak@noaa.gov
# Date    : October 11, 2023 
############################################################################################

# driver of the script, generates configuration files and realization files by calling
# the respective scripts

import os
import sys
import subprocess
from pathlib import Path
import argparse
import json

from src.python import realization

from src.python.configuration import get_config_generator

class Generate:
    def __init__(self, sandbox_dir, gpkg_file, forcing_dir, ngen_dir,
                 sim_time, formulation, model_variants, output_dir,
                 forcing_format, ngen_cal_type, schema, domain,
                 disable_divide_output,
                 ensemble_enabled=False, ensemble_models = None
                 ):
        
        self.sandbox_dir = sandbox_dir
        self.gpkg_file   = gpkg_file
        self.forcing_dir = forcing_dir
        self.ngen_dir    = ngen_dir
        self.output_dir  = output_dir
        self.schema      = schema
        self.verbosity   = 1
        self.domain      = domain

        self.simulation_time = sim_time
        self.formulation     = formulation
        self.model_variants  = model_variants
        self.forcing_format  = forcing_format
        self.ngen_cal_type   = ngen_cal_type

        self.ensemble_enabled = ensemble_enabled
        self.ensemble_size    = len([m.strip() for m in ensemble_models.split(",")]) if self.ensemble_enabled else 1
        self.ensemble_models  = ensemble_models

        self.disable_divide_output     = disable_divide_output

        if not os.path.exists(self.gpkg_file):
            sys.exit(f'The gpkg file does not exist: ', self.gpkg_file)

        if not os.path.exists(self.forcing_dir):
            sys.exit(f'The forcing directory does not exist: ', self.forcing_dir)


        # Ensemble loop (or single run)
        for member_id in range(1, self.ensemble_size+1):
            self._generate_member(member_id if self.ensemble_enabled else 1)
            

    def _generate_member(self, member_id):


        ConfigGen = get_config_generator(
            sandbox_dir=self.sandbox_dir,
            gpkg_file=self.gpkg_file,
            forcing_dir=self.forcing_dir,
            output_dir=self.output_dir,
            ngen_dir=self.ngen_dir,
            formulation=self.formulation,
            model_variants=self.model_variants,
            simulation_time=self.simulation_time,
            verbosity=1,
            ngen_cal_type=self.ngen_cal_type,
            schema_type=self.schema,
            ensemble_enabled=self.ensemble_enabled,
            ensemble_models=self.ensemble_models
        )

        tag = f"cfg_tile-{member_id}" if self.ensemble_enabled else "cfg"
        ConfigGen.write_input_files(member_id, tag)


        """


        if "SMP" in self.formulation:
            
            if "CFE" in self.formulation:
                ConfigGen.write_smp_input_files(cfe_coupled=True, lasam_coupled=False,
                                                member_id=member_id, tag=tag)
            elif "LASAM" in self.formulation:
                ConfigGen.write_smp_input_files(cfe_coupled=False, lasam_coupled=True,
                                                member_id=member_id, tag=tag)
        """
        RealGen = realization.RealizationGenerator(
            ngen_dir           = self.ngen_dir,
            forcing_dir        = self.forcing_dir,
            output_dir         = self.output_dir,
            formulation        = self.formulation,
            model_variants=self.model_variants,
            simulation_time    = self.simulation_time,
            forcing_format     = self.forcing_format,
            ngen_cal_type      = self.ngen_cal_type,
            domain             = self.domain,
            ensemble_enabled   = self.ensemble_enabled,
            ensemble_member_id = member_id,
            ensemble_models    = self.ensemble_models,
            verbosity          = 1,
            disable_divide_output = self.disable_divide_output
        )

        RealGen.write_realization_file()
        
                
    class colors:
        BLUE = '\33[34m'
        BLACK = '\33[30m'
        RED = '\33[31m'
        CYAN = '\033[96m'
        GREEN = '\033[32m'
        WARNING = '\033[93m'
        FAIL = '\033[91m'
        ENDC = '\033[0m'
        BOLD = '\033[1m'
        UNDERLINE = '\033[4m'
