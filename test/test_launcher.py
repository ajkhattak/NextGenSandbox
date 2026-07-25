import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml


def load_launcher_module():
    path = Path(__file__).resolve().parents[1] / "tools/launcher/sandbox_launcher.py"
    spec = importlib.util.spec_from_file_location("sandbox_launcher", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


launcher = load_launcher_module()


class TestLauncherAssignment(unittest.TestCase):
    def test_group_assignments_merge_for_repeated_gage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "gages.csv"
            csv_path.write_text(
                "gage_id,group_name\n"
                "01109403,snowy\n"
                "01109403,benchmark\n"
                "02299950,arid\n"
            )

            config = {
                "experiments": {
                    "pet_cfe_s": {"models": "PET, CFE, T-route"},
                    "pet_cfe_x": {"models": "PET, CFE, T-route"},
                    "pet_topmodel": {"models": "PET, TopModel, T-route"},
                },
                "gages": {
                    "option": "file",
                    "file": {
                        "path": str(csv_path),
                        "id_column": "gage_id",
                        "group_column": "group_name",
                    },
                },
                "assignment": {
                    "default": ["pet_cfe_s"],
                    "groups": {
                        "snowy": ["pet_cfe_s"],
                        "benchmark": ["pet_cfe_x"],
                        "arid": ["pet_topmodel"],
                    },
                },
            }

            map_config, summary = launcher.build_map_from_launcher_config(
                config,
                tmp_path,
            )

            self.assertEqual(
                map_config["mapping"]["01109403"],
                ["pet_cfe_s", "pet_cfe_x"],
            )
            self.assertEqual(
                map_config["mapping"]["02299950"],
                ["pet_topmodel"],
            )
            self.assertEqual(summary["snowy"]["gages"], 1)
            self.assertEqual(summary["benchmark"]["gages"], 1)

    def test_all_cannot_be_mixed_with_experiment_names(self):
        with self.assertRaisesRegex(ValueError, "cannot mix"):
            launcher.resolve_experiment_list(
                ["all", "pet_cfe_s"],
                {"pet_cfe_s": {"models": "PET, CFE, T-route"}},
                "assignment.default",
            )

    def test_launcher_requires_metadata_index(self):
        config = {
            "general": {
                "input_dir": "/tmp/inputs",
                "output_dir": "/tmp/outputs",
                "gages": {"option": "ids", "ids": []},
            },
            "forcings": {"gages": "all"},
            "formulation": {"models": "PET, CFE, T-route"},
            "simulation": {"gages": []},
        }

        with self.assertRaisesRegex(ValueError, "metadata.enabled"):
            launcher.validate_base_sandbox_config(config)

    def test_generated_configs_use_only_sandbox_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = SimpleNamespace(
                base_sandbox_cfg={
                    "general": {
                        "input_dir": "/tmp/inputs",
                        "output_dir": "/tmp/outputs",
                        "gages": {"option": "ids", "ids": []},
                    },
                    "calibration": {
                        "optimizer": {
                            "algorithm": "dds",
                            "iterations": 25,
                        },
                        "objective": {"function": "kge"},
                    },
                    "formulation": {"models": ""},
                    "simulation": {
                        "task_type": "calibvalid",
                        "gages": [],
                    },
                },
                output_dir=root / "outputs",
            )

            with patch.object(launcher.subprocess, "run") as run:
                launcher.generate_config_files_for_gage(
                    ctx,
                    "pet_cfe",
                    {"models": "PET, CFE, T-ROUTE"},
                    "pet_cfe",
                    "01109403",
                    root / "configs",
                    root / "metadata",
                )

            paths = launcher.generated_config_paths(
                root / "configs",
                "01109403",
            )
            self.assertEqual(
                set(paths),
                {"sandbox_main", "sandbox_restart", "sandbox_validation"},
            )
            restart = yaml.safe_load(paths["sandbox_restart"].read_text())
            self.assertEqual(
                restart["simulation"]["task_type"],
                "restart",
            )
            self.assertEqual(
                restart["simulation"]["restart_dir"],
                str(root / "outputs" / "pet_cfe" / "01109403"),
            )
            self.assertNotIn("-j", run.call_args.args[0])

    def test_max_iterations_comes_from_sandbox_calibration_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = launcher.generated_config_paths(root, "01109403")
            paths["sandbox_main"].parent.mkdir(parents=True)
            paths["sandbox_main"].write_text(
                yaml.safe_dump(
                    {
                        "calibration": {
                            "optimizer": {"iterations": 75},
                        }
                    }
                )
            )
            self.assertEqual(
                launcher.get_max_iter(root, "01109403"),
                75,
            )


if __name__ == "__main__":
    unittest.main()
