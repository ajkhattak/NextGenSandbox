import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.python import helper
from src.python.driver import Driver


class TestConfigurationManifest(unittest.TestCase):
    def _values(self, root, **overrides):
        values = {
            "task_type": "calibration",
            "gage_id": "02299950",
            "formulation_models": ["NOM", "CFE", "T-ROUTE"],
            "simulation_time": {
                "start_time": "2013-10-01 00:00:00",
                "end_time": "2016-09-30 23:00:00",
            },
            "hydrofabric": root / "custom_02299950.gpkg",
            "forcing": root / "forcing_02299950.nc",
        }
        values.update(overrides)
        return values

    def test_manifest_accepts_matching_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            values = self._values(root)
            helper.write_configuration_manifest(root, **values)

            manifest = helper.validate_configuration_manifest(root, **values)

            self.assertEqual(
                manifest,
                root / "configuration_manifest.yml",
            )

    def test_manifest_rejects_validation_configuration_for_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = self._values(
                root,
                task_type="validation",
                validation_name="validation",
                simulation_time={
                    "start_time": "2000-10-01 00:00:00",
                    "end_time": "2023-09-30 23:00:00",
                },
            )
            helper.write_configuration_manifest(root, **generated)

            with self.assertRaisesRegex(
                ValueError,
                "Generated configurations do not match",
            ):
                helper.validate_configuration_manifest(
                    root,
                    **self._values(root),
                )

    def test_missing_manifest_instructs_user_to_generate_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaisesRegex(FileNotFoundError, "sandbox --conf"):
                helper.validate_configuration_manifest(
                    root,
                    **self._values(root),
                )

    def test_single_validation_uses_validation_directory_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "02299950"
            period = {
                "name": "water year 2011",
                "simulation_time": {
                    "start_time": "2010-10-01 00:00:00",
                    "end_time": "2012-09-30 23:00:00",
                },
                "evaluation_time": {
                    "start_time": "2011-10-01 00:00:00",
                    "end_time": "2012-09-30 23:00:00",
                },
            }
            ctx = SimpleNamespace(
                simulation_tasks=("validation",),
                task_type="validation",
                simulation_time=period["simulation_time"],
                validation_periods=[period],
            )

            specifications = Driver(ctx).configuration_specs(output_dir)

            self.assertEqual(len(specifications), 1)
            self.assertEqual(specifications[0]["task_type"], "validation")
            self.assertEqual(
                specifications[0]["config_dir"],
                output_dir / "configs" / "validation",
            )

    def test_multiple_validations_use_named_directories(self):
        output_dir = Path("gage_output")
        periods = [
            {
                "name": name,
                "simulation_time": {
                    "start_time": f"{year}-01-01 00:00:00",
                    "end_time": f"{year}-12-31 23:00:00",
                },
            }
            for name, year in [("dry year", 2011), ("wet year", 2012)]
        ]
        ctx = SimpleNamespace(
            simulation_tasks=("validation",),
            task_type="validation",
            simulation_time=periods[0]["simulation_time"],
            validation_periods=periods,
        )

        specifications = Driver(ctx).configuration_specs(output_dir)

        self.assertEqual(
            [specification["config_dir"] for specification in specifications],
            [
                output_dir / "configs" / "validation" / "dry_year",
                output_dir / "configs" / "validation" / "wet_year",
            ],
        )

    def test_task_configuration_directories_share_one_configs_tree(self):
        output_dir = Path("gage_output")

        self.assertEqual(
            helper.configuration_dir(output_dir, "calibration"),
            output_dir / "configs" / "calibration",
        )
        self.assertEqual(
            helper.configuration_dir(output_dir, "control"),
            output_dir / "configs" / "control",
        )
        self.assertEqual(
            helper.configuration_dir(output_dir, "restart"),
            output_dir / "configs" / "restart",
        )


if __name__ == "__main__":
    unittest.main()
