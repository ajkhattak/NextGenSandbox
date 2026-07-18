from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import yaml

from src.python.configuration import ConfigurationCalib
from src.python.model_instances import build_model_instances


def make_context(calib_config_path, instances_by_model):
    return SimpleNamespace(
        calib_config_path=calib_config_path,
        formulation=",".join(instances_by_model),
        formulation_models=list(instances_by_model),
        get_model_instances=lambda model: instances_by_model.get(model, []),
    )


class TestCalibrationConfig(unittest.TestCase):
    def test_official_cfe_x_instance_gets_cfe_x_calib_params_file(self):
        registry = build_model_instances(
            "CFE,T-ROUTE",
            {
                "CFE": [
                    {
                        "name": "cfe-x",
                        "basefile": "config_cfe-x.yaml",
                        "repo_name": "cfe",
                        "calib_params_block": "cfex_params",
                    }
                ]
            },
        )

        instance = registry["CFE"][0]

        self.assertEqual(instance.calib_params_block, "cfex_params")
        self.assertEqual(instance.calib_params_file, "cfe-x.yaml")

    def test_rejects_inconsistent_official_cfe_variant(self):
        with self.assertRaisesRegex(
            ValueError,
            "official CFE variant",
        ):
            build_model_instances(
                "CFE,T-ROUTE",
                {
                    "CFE": [
                        {
                            "name": "cfe-x",
                            "basefile": "config_cfe-s.yaml",
                            "repo_name": "cfe",
                            "calib_params_block": "cfes_params",
                        }
                    ]
                },
            )

    def test_allows_custom_settings_within_official_cfe_family(self):
        registry = build_model_instances(
            "CFE,T-ROUTE",
            {
                "CFE": [
                    {
                        "name": "cfe-x",
                        "basefile": "config_cfe-x_custom.yaml",
                        "repo_name": "cfe",
                        "calib_params_block": "cfex_params_custom",
                        "calib_params_file": "cfe-x-custom.yaml",
                    }
                ]
            },
        )

        instance = registry["CFE"][0]

        self.assertEqual(instance.basefile, "config_cfe-x_custom.yaml")
        self.assertEqual(instance.calib_params_block, "cfex_params_custom")
        self.assertEqual(instance.calib_params_file, "cfe-x-custom.yaml")

    def test_rejects_mixed_family_markers_in_official_cfe_variant(self):
        with self.assertRaisesRegex(
            ValueError,
            "different variant family",
        ):
            build_model_instances(
                "CFE,T-ROUTE",
                {
                    "CFE": [
                        {
                            "name": "cfe-x",
                            "basefile": "config_cfe-x_and_cfe-s.yaml",
                            "repo_name": "cfe",
                            "calib_params_block": "cfex_params",
                        }
                    ]
                },
            )

    def test_allows_custom_cfe_variant_fields(self):
        registry = build_model_instances(
            "CFE,T-ROUTE",
            {
                "CFE": [
                    {
                        "name": "cfe-custom",
                        "basefile": "config_cfe-s.yaml",
                        "repo_name": "cfe",
                        "calib_params_block": "custom_cfe_params",
                        "calib_params_file": "custom-cfe.yaml",
                    }
                ]
            },
        )

        instance = registry["CFE"][0]

        self.assertEqual(instance.name, "cfe-custom")
        self.assertEqual(instance.calib_params_block, "custom_cfe_params")
        self.assertEqual(instance.calib_params_file, "custom-cfe.yaml")

    def test_dds_strategy_does_not_include_pso_parameters(self):
        strategy = ConfigurationCalib.build_strategy_config(
            {
                "type": "estimation",
                "algorithm": "dds",
                "parameters": {
                    "particles": 20,
                    "pool": 2,
                },
            }
        )

        self.assertEqual(strategy["algorithm"], "dds")
        self.assertNotIn("parameters", strategy)

    def test_pso_strategy_includes_pso_parameters(self):
        strategy = ConfigurationCalib.build_strategy_config(
            {
                "type": "estimation",
                "algorithm": "pso",
                "parameters": {
                    "particles": 20,
                    "pool": 2,
                },
            }
        )

        self.assertEqual(
            strategy["parameters"],
            {
                "particles": 20,
                "pool": 2,
            },
        )

    def test_log10_parameter_values_are_loaded_in_physical_units(self):
        param = ConfigurationCalib.normalize_calibration_parameter(
            "cfes_params",
            {
                "name": "Cgw",
                "min": 1.0e-5,
                "max": 1.0e-2,
                "init": 1.0e-3,
                "scale": "log10",
            },
        )

        self.assertEqual(param["scale"], "log10")
        self.assertAlmostEqual(param["min"], -5.0)
        self.assertAlmostEqual(param["max"], -2.0)
        self.assertAlmostEqual(param["init"], -3.0)

    def test_log10_parameter_values_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "positive physical value"):
            ConfigurationCalib.normalize_calibration_parameter(
                "cfes_params",
                {
                    "name": "Cgw",
                    "min": 0.0,
                    "max": 1.0e-2,
                    "init": 1.0e-3,
                    "scale": "log10",
                },
            )

    def test_log10_parameter_init_must_be_within_bounds(self):
        with self.assertRaisesRegex(ValueError, "init outside min/max"):
            ConfigurationCalib.normalize_calibration_parameter(
                "cfes_params",
                {
                    "name": "Cgw",
                    "min": 1.0e-5,
                    "max": 1.0e-2,
                    "init": 1.0e-1,
                    "scale": "log10",
                },
            )

    def test_loads_parameter_blocks_from_calibration_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            params_dir = root / "calibration"
            params_dir.mkdir()

            calib_config = root / "calib_config.yaml"
            calib_config.write_text(
                yaml.safe_dump(
                    {
                        "general": {
                            "strategy": {
                                "type": "estimation",
                                "algorithm": "dds",
                            }
                        },
                        "calibration": {
                            "params_dir": "calibration",
                        },
                        "model": {
                            "eval_params": {
                                "objective": "kling_gupta",
                                "target": "min",
                            }
                        },
                    },
                    sort_keys=False,
                )
            )
            (params_dir / "cfe-s.yaml").write_text(
                yaml.safe_dump(
                    {
                        "cfes_params": [
                            {
                                "name": "refkdt",
                                "min": 0.001,
                                "max": 8.0,
                                "init": 3.0,
                            }
                        ]
                    },
                    sort_keys=False,
                )
            )

            config = ConfigurationCalib.__new__(ConfigurationCalib)
            config.ctx = make_context(
                calib_config,
                {
                    "CFE": [
                        SimpleNamespace(
                            model="CFE",
                            name="cfe-s",
                            calib_params_block="cfes_params",
                            calibration_model_name="CFE",
                        )
                    ]
                },
            )

            loaded = config.load_calib_config()

            self.assertEqual(loaded["cfes_params"][0]["name"], "refkdt")
            self.assertNotIn("snow17_params", loaded)

    def test_ignores_parameter_files_not_used_by_formulation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            params_dir = root / "calibration"
            params_dir.mkdir()

            calib_config = root / "calib_config.yaml"
            calib_config.write_text(
                yaml.safe_dump(
                    {
                        "calibration": {
                            "params_dir": "calibration",
                        },
                    },
                    sort_keys=False,
                )
            )
            (params_dir / "cfe-s.yaml").write_text(
                yaml.safe_dump({"cfes_params": []}, sort_keys=False)
            )
            (params_dir / "snow17.yaml").write_text(
                yaml.safe_dump(["not", "a", "mapping"], sort_keys=False)
            )

            config = ConfigurationCalib.__new__(ConfigurationCalib)
            config.ctx = make_context(
                calib_config,
                {
                    "CFE": [
                        SimpleNamespace(
                            model="CFE",
                            name="cfe-s",
                            calib_params_block="cfes_params",
                            calibration_model_name="CFE",
                        )
                    ]
                },
            )

            loaded = config.load_calib_config()

            self.assertEqual(loaded["cfes_params"], [])

    def test_uses_instance_name_when_calib_params_file_is_not_set(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            params_dir = root / "calibration"
            params_dir.mkdir()

            calib_config = root / "calib_config.yaml"
            calib_config.write_text(
                yaml.safe_dump(
                    {
                        "calibration": {
                            "params_dir": "calibration",
                        },
                    },
                    sort_keys=False,
                )
            )
            (params_dir / "cfe-x.yaml").write_text(
                yaml.safe_dump({"cfex_params": []}, sort_keys=False)
            )

            config = ConfigurationCalib.__new__(ConfigurationCalib)
            config.ctx = make_context(
                calib_config,
                {
                    "CFE": [
                        SimpleNamespace(
                            model="CFE",
                            name="cfe-x",
                            calib_params_block="cfex_params",
                            calib_params_file="",
                            calibration_model_name="CFE",
                        )
                    ]
                },
            )

            loaded = config.load_calib_config()

            self.assertEqual(loaded["cfex_params"], [])

    def test_rejects_top_level_parameter_blocks_in_calib_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            params_dir = root / "calibration"
            params_dir.mkdir()

            calib_config = root / "calib_config.yaml"
            calib_config.write_text(
                yaml.safe_dump(
                    {
                        "calibration": {
                            "params_dir": "calibration",
                        },
                        "cfes_params": [],
                    },
                    sort_keys=False,
                )
            )
            (params_dir / "cfe-s.yaml").write_text(
                yaml.safe_dump({"cfes_params": []}, sort_keys=False)
            )

            config = ConfigurationCalib.__new__(ConfigurationCalib)
            config.ctx = make_context(
                calib_config,
                {
                    "CFE": [
                        SimpleNamespace(
                            model="CFE",
                            name="cfe-s",
                            calib_params_block="cfes_params",
                            calibration_model_name="CFE",
                        )
                    ]
                },
            )

            with self.assertRaisesRegex(
                ValueError,
                "must be defined in files under calibration.params_dir",
            ):
                config.load_calib_config()

    def test_requires_calibration_params_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calib_config = root / "calib_config.yaml"
            calib_config.write_text(
                yaml.safe_dump(
                    {
                        "general": {
                            "strategy": {
                                "type": "estimation",
                                "algorithm": "dds",
                            }
                        },
                        "calibration": {},
                    },
                    sort_keys=False,
                )
            )

            config = ConfigurationCalib.__new__(ConfigurationCalib)
            config.ctx = make_context(
                calib_config,
                {
                    "CFE": [
                        SimpleNamespace(
                            model="CFE",
                            name="cfe-s",
                            calib_params_block="cfes_params",
                            calibration_model_name="CFE",
                        )
                    ]
                },
            )

            with self.assertRaisesRegex(ValueError, "calibration.params_dir"):
                config.load_calib_config()


if __name__ == "__main__":
    unittest.main()
