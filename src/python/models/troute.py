import os
import sys
import yaml
import geopandas as gpd
import pandas as pd

from src.python.models_registry import register_model
from src.python.configuration import ConfigurationGenerator

@register_model("T-ROUTE")
class TRouteConfigurationGenerator(ConfigurationGenerator):
    def __init__(self, ctx, static_data, output_dir):
        super().__init__(static_data)
        self.ctx = ctx
        self.static_data = static_data
        self.output_dir = output_dir

    def _write_input_files(self, member_id, tag):
        self.write_troute_input_files()


    def write_troute_input_files(self):

        troute_basefile = os.path.join(self.ctx.sandbox_dir, "configs/basefiles/config_troute.yaml")
        troute_dir = os.path.join(self.output_dir,"configs")
        gpkg_name = os.path.basename(self.static_data.gpkg_file).split(".")[0]

        if not os.path.exists(troute_basefile):
            sys.exit(f"Sample routing yaml file does not exist, provided is {troute_basefile}")

        with open(troute_basefile, 'r') as file:
            d = yaml.safe_load(file)

        # get the terminal nexus id
        gdf_net = gpd.read_file(self.static_data.gpkg_file, layer="flowpath-attributes")
        gpkg_id = gpkg_name.split("_")[1]
        mask    = gdf_net["gage"].str.contains(gpkg_id, na=False)

        terminal_nexus_id = gdf_net.loc[mask, "gage_nex_id"].iloc[0]
        
        d['network_topology_parameters']['supernetwork_parameters']['geo_file_path'] = self.static_data.gpkg_file
        d['network_topology_parameters']['waterbody_parameters']['level_pool']['level_pool_waterbody_parameter_file_path'] = self.static_data.gpkg_file
        d['network_topology_parameters']['supernetwork_parameters']['title_string'] = gpkg_name

        dt = 300
        params = self.static_data.get_flowpath_attributes(gage_id=self.static_data.gpkg_file, full_schema=True)

        columns = {
            'key': params['key'],
            'downstream': params['downstream'],
            'mainstem': params['mainstem'],
            'dx': params['dx'],
            'n': params['n'],
            'ncc': params['ncc'],
            's0': params['s0'],
            'bw': params['bw'],
            'waterbody': params['waterbody'],
            'gages': params['gages'],
            'tw': params['tw'],
            'twcc': params['twcc'],
            'musk': params['musk'],
            'musx': params['musx'],
            'cs': params['cs'],
            'alt': params['alt']
        }

        d['network_topology_parameters']['supernetwork_parameters']['columns'] = columns

        start_time = pd.Timestamp(self.ctx.simulation_time['start_time'])
        end_time = pd.Timestamp(self.ctx.simulation_time['end_time'])
        diff_time = (end_time - start_time).total_seconds()

        d['compute_parameters']['restart_parameters']['start_datetime'] = start_time.strftime("%Y-%m-%d_%H:%M:%S")

        if self.ctx.task_type in ['calibration', 'validation', 'calibvalid', 'restart']:
            d['compute_parameters']['forcing_parameters']['qlat_input_folder'] = "./"
        else:
            d['compute_parameters']['forcing_parameters']['qlat_input_folder'] = os.path.join(self.output_dir, "outputs/div")

        d['compute_parameters']['forcing_parameters']['qlat_file_pattern_filter'] = "nex-*"
        del d['compute_parameters']['forcing_parameters']['binary_nexus_file_folder']
        d['compute_parameters']['forcing_parameters']['nts'] = int(diff_time / dt)
        d['compute_parameters']['forcing_parameters']['max_loop_size'] = 10000000

        d['compute_parameters']['cpu_pool'] = 1

        if self.ctx.task_type in ['calibration', 'validation', 'calibvalid', 'restart']:
            stream_output = {
                "stream_output": {
                    "stream_output_directory": "./",
                    'stream_output_time': -1,
                    'stream_output_type': '.nc',
                    'stream_output_internal_frequency': 60
                }
            }
        else:
            stream_output = {
                "stream_output": {
                    'stream_output_directory': os.path.join(self.output_dir, "outputs/troute"),
                    'mask_output': os.path.join(troute_dir, "mask_output.yaml"),
                    'stream_output_time': -1,
                    'stream_output_type': '.nc',
                    'stream_output_internal_frequency': 60
                }
            }
            # write mask file for terminal nexus output only
            dnex = {
                "nex": [terminal_nexus_id.split("-")[1]]
                }
            with open(os.path.join(troute_dir, "mask_output.yaml"), 'w') as file:
                yaml.dump(dnex, file, default_flow_style=False, sort_keys=False)
             
        d['output_parameters'] = stream_output

        with open(os.path.join(troute_dir, "troute_config.yaml"), 'w') as file:
            yaml.dump(d, file, default_flow_style=False, sort_keys=False)
