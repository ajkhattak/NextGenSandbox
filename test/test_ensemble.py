import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.python.context import SandboxContext
from src.python.data_loader import SandboxData
from src.python.realization import RealizationGenerator


class TestEnsembleConfiguration(unittest.TestCase):
    def load_formulation(self, formulation):
        context = object.__new__(SandboxContext)
        context.sandbox_config = {"formulation": formulation}
        with patch.dict(os.environ, {"NGEN_DIR": "/tmp/ngen"}):
            context.load_formulation_config()
        return context

    def test_loads_enabled_ensemble_from_formulation_block(self):
        context = self.load_formulation(
            {
                "models": "NOM, PET, CFE, T-ROUTE",
                "ensemble": {
                    "enabled": True,
                    "members": 2,
                    "calib_params_groups": {
                        "nom": "local",
                        "CFE": "global",
                    },
                },
            }
        )

        self.assertTrue(context.ensemble_enabled)
        self.assertEqual(context.ensemble_size, 2)
        self.assertEqual(context.ensemble_models, "NOM,PET,CFE")
        self.assertEqual(
            context.ensemble_calib_params_groups,
            {"NOM": "local", "CFE": "global"},
        )

    def test_enabled_ensemble_requires_member_count(self):
        with self.assertRaisesRegex(ValueError, "members"):
            self.load_formulation(
                {
                    "models": "PET, CFE, T-ROUTE",
                    "ensemble": {"enabled": True},
                }
            )

    def test_rejects_calibration_scope_for_model_outside_formulation(self):
        with self.assertRaisesRegex(ValueError, "not in formulation.models"):
            self.load_formulation(
                {
                    "models": "PET, CFE, T-ROUTE",
                    "ensemble": {
                        "enabled": True,
                        "members": 2,
                        "calib_params_groups": {"NOM": "local"},
                    },
                }
            )

    def test_realization_uses_context_member_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            forcing_file = root / "forcing.nc"
            forcing_file.touch()
            config_dir = root / "output" / "configs" / "calibration"
            config_dir.mkdir(parents=True)
            context = SimpleNamespace(
                ngen_dir=root / "ngen",
                formulation="PET,CFE,T-ROUTE",
                simulation_time={
                    "start_time": "2020-01-01 00:00:00",
                    "end_time": "2020-01-02 00:00:00",
                },
                forcing_format=".nc",
                verbosity=0,
                task_type="calibration",
                domain="conus",
                ensemble_enabled=True,
                ensemble_size=2,
                ensemble_models="PET,CFE",
                model_registry={},
            )

            generator = RealizationGenerator(
                context,
                forcing_file,
                root / "output",
                config_dir,
                ensemble_member_id=1,
            )

            self.assertEqual(generator.ensemble_size, 2)
            self.assertEqual(generator.tag, "cfg_tile-1")

    def test_writes_validated_ensemble_weights(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            loader = object.__new__(SandboxData)
            loader.output_dir = Path(temp_dir)
            loader.config_dir = Path(temp_dir) / "configs" / "calibration"
            loader.catids = [1, 2]
            loader.gdf = pd.DataFrame(
                {
                    "IVGTYP_nlcd": [
                        json.dumps(
                            [
                                {"v": 1, "frequency": 0.7},
                                {"v": 2, "frequency": 0.3},
                            ]
                        ),
                        json.dumps([{"v": 3, "frequency": 1.0}]),
                    ]
                },
                index=["cat-1", "cat-2"],
            )
            context = SimpleNamespace(
                ensemble_enabled=True,
                ensemble_size=2,
            )

            loader.save_ensemble_weights(context)

            weights = pd.read_csv(
                loader.config_dir / "ensemble_weights.csv"
            )
            self.assertEqual(
                list(weights.columns),
                ["divide_id", "weight_1", "weight_2"],
            )
            self.assertEqual(weights.loc[0, "weight_1"], 0.7)
            self.assertEqual(weights.loc[0, "weight_2"], 0.3)
            self.assertEqual(weights.loc[1, "weight_1"], 1.0)
            self.assertEqual(weights.loc[1, "weight_2"], 0.0)


if __name__ == "__main__":
    unittest.main()
