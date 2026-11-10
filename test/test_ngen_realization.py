import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from ngen.config.realization import NgenRealization

from src.python.formulations_registry import is_registered_formulation
from src.python.model_instances import build_model_instances
from src.python.realization import RealizationGenerator


class TestSacSmaRealization(unittest.TestCase):
    def test_pet_sacsma_uses_precipitation_forcing_without_snow17(self):
        formulation = "PET,SACSMA,T-ROUTE"
        self.assertTrue(is_registered_formulation(formulation))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            forcing = root / "forcing.nc"
            forcing.touch()
            ctx = SimpleNamespace(
                ngen_dir=root / "ngen",
                formulation=formulation,
                simulation_time={
                    "start_time": "2020-01-01 00:00:00",
                    "end_time": "2020-01-02 00:00:00",
                },
                forcing_format=".nc",
                verbosity=0,
                task_type="calibration",
                domain="conus",
                ensemble_enabled=False,
                ensemble_size=1,
                ensemble_models="",
                divide_output_variables={},
                model_registry=build_model_instances(formulation),
            )
            generator = RealizationGenerator(ctx, str(forcing), root, root, 1)
            generator.write_realization_file()
            realization = json.loads(generator.realization_file.read_text())

        params = realization["global"]["formulations"][0]["params"]
        modules = [module["params"] for module in params["modules"]]
        self.assertEqual([module["model_type_name"] for module in modules], ["PET", "SacSMA"])
        self.assertEqual(modules[1]["variables_names_map"]["precip"], "APCP_surface")
        self.assertEqual(modules[1]["variables_names_map"]["pet"], modules[0]["main_output_variable"])
        self.assertEqual(params["main_output_variable"], "tci")
        self.assertIn("routing", realization)


def test_ngen_cal_preserves_per_formulation_nexus_output_setting():
    realization = NgenRealization(
        **{
            "global": {
                "formulations": [],
                "forcing": {
                    "file_pattern": ".*{{id}}.*.csv",
                    "path": ".",
                },
            },
            "time": {
                "start_time": "2020-01-01 00:00:00",
                "end_time": "2020-01-02 00:00:00",
                "output_interval": 3600,
            },
            "per_formulation_nexus_files": True,
        }
    )

    serialized = json.loads(
        realization.json(by_alias=True, exclude_none=True)
    )

    assert serialized["per_formulation_nexus_files"] is True
