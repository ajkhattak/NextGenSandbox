import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from src.python.driver import Driver


class TestDriverMetadata(unittest.TestCase):
    def test_configuration_generation_rejects_mismatched_resource_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            ctx = SimpleNamespace(
                output_dir=output_dir,
                gage_ids=["12345678", "87654321"],
                gpkg_dirs=[Path("gage_12345678.gpkg"), Path("gage_87654321.gpkg")],
                output_dirs=[output_dir / "12345678", output_dir / "87654321"],
                forcing_files=[Path("forcing_12345678.nc")],
            )

            with self.assertRaises(ValueError):
                Driver(ctx).main()

    def test_simulation_metadata_does_not_write_index_without_index_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "01109403_pet_cfe"
            output_dir.mkdir()
            ctx = SimpleNamespace(
                metadata_file="simulation_metadata.yml",
                metadata_index_dir=None,
                task_type="calibration",
                formulation="PET,CFE,T-ROUTE",
                sandbox_config_path="sandbox.yaml",
            )

            Driver(ctx).write_simulation_metadata(
                gpkg_id="01109403",
                num_cpus=2,
                input_dir=Path(tmp) / "inputs" / "01109403",
                output_dir=output_dir,
            )

            metadata_file = output_dir / "simulation_metadata.yml"
            self.assertTrue(metadata_file.exists())
            self.assertFalse((Path(tmp) / "metadata").exists())

            metadata = yaml.safe_load(metadata_file.read_text())
            self.assertEqual(metadata["gage_id"], "01109403")
            self.assertEqual(metadata["num_cpus"], 2)
            self.assertNotIn("basin_id", metadata)
            self.assertNotIn("calib_config", metadata)

    def test_simulation_metadata_writes_index_when_index_dir_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "01109403_pet_cfe"
            output_dir.mkdir()
            ctx = SimpleNamespace(
                metadata_file="simulation_metadata.yml",
                metadata_index_dir="metadata",
                task_type="calibration",
                formulation="PET,CFE,T-ROUTE",
                sandbox_config_path="sandbox.yaml",
            )

            Driver(ctx).write_simulation_metadata(
                gpkg_id="01109403",
                num_cpus=2,
                input_dir=Path(tmp) / "inputs" / "01109403",
                output_dir=output_dir,
            )

            self.assertTrue((output_dir / "simulation_metadata.yml").exists())
            self.assertTrue((Path(tmp) / "metadata" / "run_01109403.yml").exists())


if __name__ == "__main__":
    unittest.main()
