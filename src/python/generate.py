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
from src.python.data_loader import SandboxData
from src.python.models_registry import load_model_registry
from src.python.configuration import CompositeConfigurationGenerator

class Generate:
    def __init__(self, ctx, gpkg_file, forcing_dir, output_dir):
        self.ctx = ctx
        self.gpkg_file = gpkg_file
        self.forcing_dir = forcing_dir
        self.output_dir = output_dir

            
    def run(self):

        self.validate()

        # Ensemble loop (or single run)
        for member_id in range(1, self.ctx.ensemble_size + 1):
            self._generate_member(member_id if self.ctx.ensemble_enabled else 1)
        
    def _generate_member(self, member_id):


        ConfigGen = self.get_config_generator(
            ctx=self.ctx,
            gpkg_file=self.gpkg_file,
            forcing_dir=self.forcing_dir,
            output_dir=self.output_dir
        )

        tag = f"cfg_tile-{member_id}" if self.ctx.ensemble_enabled else "cfg"
        ConfigGen.write_input_files(member_id, tag)


        RealGen = realization.RealizationGenerator(
            ctx=self.ctx,
            forcing_dir        = self.forcing_dir,
            output_dir         = self.output_dir,
            ensemble_member_id = member_id
        )

        RealGen.write_realization_file()

    
    def get_config_generator(self, ctx,
                             gpkg_file,
                             forcing_dir,
                             output_dir):

        models_registry = load_model_registry()
        formulation = ctx.formulation
        keys = [k.strip().upper() for k in formulation.replace(",", "+").split("+")]
    
        static_data = SandboxData(ctx, gpkg_file)
    
    
        generators = []
        
        for key in keys:
            if key not in models_registry:
                supported = ", ".join(sorted(models_registry))
                raise ValueError(
                    f"Unknown model in formulation: {key}. "
                    f"Registered models are: {supported}"
                )

            # creates an instance using class context MODELS_REGISTRY["NOM"] => NOMConfigurationGenerator
            generators.append(models_registry[key](ctx, static_data, output_dir))

        if len(generators) == 1:
            return generators[0]

        return CompositeConfigurationGenerator(generators)


    def validate(self):
        if not Path(self.gpkg_file).exists():
            raise FileNotFoundError(self.gpkg_file)

        if not Path(self.forcing_dir).exists():
            raise FileNotFoundError(self.forcing_dir)
