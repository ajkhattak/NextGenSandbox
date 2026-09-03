from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import pandas as pd
import yaml

from src.python.calibration_config import load_calibration_settings
from src.python.configuration import ConfigurationCalib
from src.python.model_instances import build_model_instances


def make_parameter_context(sandbox_dir, instances_by_model):
    return SimpleNamespace(
        sandbox_dir=sandbox_dir,
        formulation=",".join(instances_by_model),
        formulation_models=list(instances_by_model),
        get_model_instances=lambda model: instances_by_model.get(model, []),
    )


class TestCalibrationConfig(unittest.TestCase):
    @staticmethod
    def _state_file(directory, name="ngen_cal_nex-1_parameter_df_state.parquet"):
        directory.mkdir(parents=True, exist_ok=True)
        state_file = directory / name
        pd.DataFrame({"0": [1.0]}, index=["parameter"]).to_parquet(state_file)
        (directory / "best_params.txt").write_text("1\n1\n0.5\n")
        return state_file

    @staticmethod
    def _state_config(root, ngen_cal_type="validation"):
        config = ConfigurationCalib.__new__(ConfigurationCalib)
        config.ngen_cal_type = ngen_cal_type
        config.output_dir = root
        config.state_dir = Path(root)
        config.ctx = SimpleNamespace(restart_dir=root)
        return config

    def test_state_selection_uses_latest_completed_indexed_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_worker = root / "20260101_ngen_old_worker"
            latest_worker = root / "20260201_ngen_latest_worker"
            failed_worker = root / "20260301_ngen_failed_worker"
            self._state_file(root, "stale_parameter_df_state.parquet")
            self._state_file(old_worker)
            latest_state = self._state_file(latest_worker)
            self._state_file(failed_worker)
            (root / "run_index.yml").write_text(
                yaml.safe_dump(
                    {
                        "runs": [
                            {
                                "task_type": "calibration",
                                "status": "completed",
                                "worker_dirs": [str(old_worker)],
                            },
                            {
                                "task_type": "calibration",
                                "status": "completed",
                                "worker_dirs": [str(latest_worker)],
                            },
                            {
                                "task_type": "calibration",
                                "status": "failed",
                                "worker_dirs": [str(failed_worker)],
                            },
                        ]
                    }
                )
            )

            config = self._state_config(root)

            self.assertEqual(config.find_state_file(), latest_state)

    def test_state_selection_uses_pso_global_best_for_indexed_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workers = []
            for particle in range(3):
                worker = root / f"20260101_ngen_particle_{particle}_worker"
                workers.append(worker)
                self._state_file(worker)
            global_best = self._state_file(root / "pso_global_best")
            (root / "run_index.yml").write_text(
                yaml.safe_dump(
                    {
                        "runs": [
                            {
                                "task_type": "calibration",
                                "status": "completed",
                                "worker_dirs": [
                                    str(worker)
                                    for worker in workers
                                ],
                            }
                        ]
                    }
                )
            )

            config = self._state_config(root)

            self.assertEqual(config.find_state_file(), global_best)

    def test_state_selection_does_not_fall_back_from_latest_completed_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_worker = root / "20260101_ngen_old_worker"
            missing_worker = root / "20260201_ngen_missing_worker"
            self._state_file(old_worker)
            missing_worker.mkdir()
            (root / "run_index.yml").write_text(
                yaml.safe_dump(
                    {
                        "runs": [
                            {
                                "task_type": "calibration",
                                "status": "completed",
                                "worker_dirs": [str(old_worker)],
                            },
                            {
                                "task_type": "calibration",
                                "status": "completed",
                                "worker_dirs": [str(missing_worker)],
                            },
                        ]
                    }
                )
            )

            config = self._state_config(root)

            with self.assertRaisesRegex(
                FileNotFoundError,
                "latest completed run",
            ):
                config.find_state_file()

    def test_state_selection_rejects_ambiguous_unindexed_states(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._state_file(root / "20260101_ngen_first_worker")
            self._state_file(root / "20260201_ngen_second_worker")
            config = self._state_config(root)

            with self.assertRaisesRegex(ValueError, "no run_index.yml"):
                config.find_state_file()

    def test_state_selection_accepts_explicit_state_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = self._state_file(Path(temp_dir) / "selected_worker")
            config = self._state_config(state_file, ngen_cal_type="restart")

            self.assertEqual(config.find_state_file(), state_file)

    def test_state_selection_requires_matching_best_params(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = (
                Path(temp_dir)
                / "ngen_cal_nex-1_parameter_df_state.parquet"
            )
            state_file.touch()
            config = self._state_config(state_file, ngen_cal_type="restart")

            with self.assertRaisesRegex(FileNotFoundError, "best_params.txt"):
                config.find_state_file()

    def test_state_selection_rejects_empty_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = (
                Path(temp_dir)
                / "ngen_cal_nex-1_parameter_df_state.parquet"
            )
            state_file.touch()
            (state_file.parent / "best_params.txt").write_text("11\n7\n0.5\n")
            config = self._state_config(state_file, ngen_cal_type="restart")

            with self.assertRaisesRegex(ValueError, "corrupt or incomplete"):
                config.find_state_file()

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
        with self.assertRaisesRegex(ValueError, "official CFE variant"):
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
        with self.assertRaisesRegex(ValueError, "different variant family"):
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

    def test_dds_strategy_does_not_include_pso_parameters(self):
        strategy = ConfigurationCalib.build_strategy_config(
            "dds",
            {"particles": 20, "pool": 2},
        )
        self.assertEqual(strategy["algorithm"], "dds")
        self.assertNotIn("parameters", strategy)

    def test_pso_strategy_includes_pso_parameters(self):
        strategy = ConfigurationCalib.build_strategy_config(
            "pso",
            {"particles": 20, "pool": 2},
        )
        self.assertEqual(
            strategy["parameters"],
            {"particles": 20, "pool": 2},
        )

    def test_composite_objective_configuration_plugin_is_loaded(self):
        self.assertIn(
            "ngen_cal_plugins.objective_plugin.ConfigureObjective",
            ConfigurationCalib.DEFAULT_PLUGINS,
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

    def test_loads_only_parameter_blocks_used_by_formulation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            params_dir = root / "configs" / "calibration"
            params_dir.mkdir(parents=True)
            (params_dir / "cfe-s.yaml").write_text(
                yaml.safe_dump({"cfes_params": [{"name": "refkdt"}]})
            )
            (params_dir / "snow17.yaml").write_text("- not\n- a\n- mapping\n")

            config = ConfigurationCalib.__new__(ConfigurationCalib)
            config.ctx = make_parameter_context(
                root,
                {
                    "CFE": [
                        SimpleNamespace(
                            model="CFE",
                            name="cfe-s",
                            calib_params_block="cfes_params",
                            calib_params_file="cfe-s.yaml",
                            calibration_model_name="CFE",
                        )
                    ]
                },
            )

            loaded = config.load_calibration_parameters()
            self.assertEqual(loaded["cfes_params"][0]["name"], "refkdt")
            self.assertNotIn("snow17_params", loaded)

    def test_uses_instance_name_when_calib_params_file_is_not_set(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            params_dir = root / "configs" / "calibration"
            params_dir.mkdir(parents=True)
            (params_dir / "cfe-x.yaml").write_text(
                yaml.safe_dump({"cfex_params": []})
            )

            config = ConfigurationCalib.__new__(ConfigurationCalib)
            config.ctx = make_parameter_context(
                root,
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
            self.assertEqual(
                config.load_calibration_parameters()["cfex_params"],
                [],
            )

    def test_loads_dds_settings_from_sandbox_config(self):
        settings = load_calibration_settings(
            {
                "calibration": {
                    "optimizer": {
                        "algorithm": "dds",
                        "iterations": 500,
                        "random_seed": 444,
                    },
                    "objective": {"function": "kge"},
                }
            },
            "/tmp/sandbox_config.yaml",
            "/tmp/sandbox",
        )
        self.assertEqual(settings.algorithm, "dds")
        self.assertEqual(settings.iterations, 500)
        self.assertEqual(
            settings.objective,
            "ngen_cal_plugins.objectives.kge_multi_variable",
        )
        self.assertEqual(settings.optimizer_settings, {})

    def test_builds_weighted_composite_objective(self):
        settings = load_calibration_settings(
            {
                "calibration": {
                    "optimizer": {"algorithm": "dds"},
                    "objective": {
                        "function": {
                            "kge": 0.5,
                            "q10_skill": 0.3,
                            "q90_skill": 0.2,
                        }
                    },
                }
            },
            "/tmp/sandbox_config.yaml",
            "/tmp/sandbox",
        )

        self.assertEqual(
            settings.objective,
            "ngen_cal_plugins.objectives.composite_objective",
        )
        self.assertEqual(
            settings.objective_metrics,
            {"kge": 0.5, "q10_skill": 0.3, "q90_skill": 0.2},
        )

    def test_rejects_unknown_composite_metric(self):
        with self.assertRaisesRegex(ValueError, "Unsupported.*metric"):
            load_calibration_settings(
                {
                    "calibration": {
                        "optimizer": {"algorithm": "dds"},
                        "objective": {
                            "function": {"rmse": 1.0},
                        },
                    }
                },
                "/tmp/sandbox_config.yaml",
                "/tmp/sandbox",
            )

    def test_rejects_nonpositive_composite_weight(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            load_calibration_settings(
                {
                    "calibration": {
                        "optimizer": {"algorithm": "dds"},
                        "objective": {
                            "function": {"kge": 0.0},
                        },
                    }
                },
                "/tmp/sandbox_config.yaml",
                "/tmp/sandbox",
            )

    def test_rejects_composite_weights_that_do_not_sum_to_one(self):
        with self.assertRaisesRegex(ValueError, "must sum to 1.0"):
            load_calibration_settings(
                {
                    "calibration": {
                        "optimizer": {"algorithm": "dds"},
                        "objective": {
                            "function": {
                                "kge": 0.5,
                                "log_kge": 0.3,
                                "fdc": 0.1,
                            },
                        },
                    }
                },
                "/tmp/sandbox_config.yaml",
                "/tmp/sandbox",
            )

    def test_loads_relative_pso_settings_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_file = root / "optimizers" / "pso.yaml"
            settings_file.parent.mkdir()
            settings_file.write_text("particles: 8\npool: 2\n")

            settings = load_calibration_settings(
                {
                    "calibration": {
                        "optimizer": {
                            "algorithm": "pso",
                            "iterations": 50,
                            "settings_file": "optimizers/pso.yaml",
                        },
                        "objective": {"function": "nnse"},
                    }
                },
                root / "sandbox_config.yaml",
                root,
            )
            self.assertEqual(settings.optimizer_settings["particles"], 8)
            self.assertEqual(
                settings.optimizer_settings_file,
                settings_file.resolve(),
            )

    def test_rejects_unknown_objective_alias(self):
        with self.assertRaisesRegex(ValueError, "custom objective import path"):
            load_calibration_settings(
                {
                    "calibration": {
                        "optimizer": {"algorithm": "dds"},
                        "objective": {"function": "not-a-metric"},
                    }
                },
                "/tmp/sandbox_config.yaml",
                "/tmp/sandbox",
            )

    def test_rejects_inline_optimizer_settings(self):
        with self.assertRaisesRegex(ValueError, "unsupported field.*parameters"):
            load_calibration_settings(
                {
                    "calibration": {
                        "optimizer": {
                            "algorithm": "pso",
                            "parameters": {"particles": 8},
                        },
                        "objective": {"function": "kge"},
                    }
                },
                "/tmp/sandbox_config.yaml",
                "/tmp/sandbox",
            )


if __name__ == "__main__":
    unittest.main()
