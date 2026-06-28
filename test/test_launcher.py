import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
