import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
from shapely.geometry import Point

from src.python.models.nom import NOMConfigurationGenerator


class TestNOMConfigurationGenerator(unittest.TestCase):
    def test_forcing_filename_uses_resolved_netcdf_file(self):
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            forcing_file = tmp_dir / "gage_01234567_2010_to_2021_corrected.nc"
            forcing_file.touch()

            soil_params = tmp_dir / "parameters"
            soil_params.mkdir()
            (soil_params / "GENPARM.TBL").write_text("")

            output_dir = tmp_dir / "output"

            ctx = SimpleNamespace(
                sandbox_dir=repo_root,
                ensemble_enabled=False,
                ensemble_models=[],
                simulation_time={
                    "start_time": "2010-01-01 00:00:00",
                    "end_time": "2017-09-30 23:00:00",
                },
                forcing_format=".nc",
                model_registry={
                    "NOM": [
                        SimpleNamespace(
                            config_dir="configs/nom",
                            basefile="config_noahowp.input",
                        )
                    ]
                },
            )

            gdf = gpd.GeoDataFrame(
                {
                    "ISLTYP": [1],
                    "IVGTYP": [7],
                    "aspect_mean": [180.0],
                    "terrain_slope": [0.12],
                    "geometry": [Point(-77.0, 39.0)],
                },
                index=["cat-1"],
                crs="EPSG:4326",
            )
            static_data = SimpleNamespace(
                gdf=gdf,
                catids=[1],
                soil_params_NWM_dir=str(soil_params),
            )

            generator = NOMConfigurationGenerator(ctx, static_data, output_dir)
            generator.forcing_file = str(forcing_file)
            generator.write_input_files(member_id=1, tag="cfg")

            nom_file = output_dir / "configs" / "nom" / "noahowp_cfg_cat-1.input"
            contents = nom_file.read_text()

            self.assertIn(f'forcing_filename   = "{forcing_file}"', contents)
            self.assertNotIn("{*}", contents)

    def test_csv_forcing_uses_resolved_directory(self):
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            forcing_dir = tmp_dir / "forcing_csv"
            forcing_dir.mkdir()

            soil_params = tmp_dir / "parameters"
            soil_params.mkdir()
            (soil_params / "GENPARM.TBL").write_text("")

            output_dir = tmp_dir / "output"

            ctx = SimpleNamespace(
                sandbox_dir=repo_root,
                ensemble_enabled=False,
                ensemble_models=[],
                simulation_time={
                    "start_time": "2010-01-01 00:00:00",
                    "end_time": "2017-09-30 23:00:00",
                },
                forcing_format=".csv",
                model_registry={
                    "NOM": [
                        SimpleNamespace(
                            config_dir="configs/nom",
                            basefile="config_noahowp.input",
                        )
                    ]
                },
            )

            gdf = gpd.GeoDataFrame(
                {
                    "ISLTYP": [1],
                    "IVGTYP": [7],
                    "aspect_mean": [180.0],
                    "terrain_slope": [0.12],
                    "geometry": [Point(-77.0, 39.0)],
                },
                index=["cat-1"],
                crs="EPSG:4326",
            )
            static_data = SimpleNamespace(
                gdf=gdf,
                catids=[1],
                soil_params_NWM_dir=str(soil_params),
            )

            generator = NOMConfigurationGenerator(ctx, static_data, output_dir)
            generator.forcing_file = str(forcing_dir)
            generator.write_input_files(member_id=1, tag="cfg")

            nom_file = output_dir / "configs" / "nom" / "noahowp_cfg_cat-1.input"
            contents = nom_file.read_text()

            self.assertIn(f'forcing_filename   = "{forcing_dir}"', contents)


if __name__ == "__main__":
    unittest.main()
