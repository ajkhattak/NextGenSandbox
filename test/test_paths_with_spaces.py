from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.python.configuration import ConfigurationGenerator
from src.python.forcing import ForcingProcessor
from src.python.runner import Runner


class TestPathsWithSpaces(unittest.TestCase):
    def test_configuration_cleanup_removes_only_requested_directory(self):
        with tempfile.TemporaryDirectory(prefix="sandbox path ") as tmp:
            root = Path(tmp)
            target = root / "model configs"
            sibling = root / "model"
            target.mkdir()
            sibling.mkdir()
            (target / "old.txt").touch()
            (sibling / "keep.txt").touch()

            static_data = SimpleNamespace(gdf=None, catids=[])
            generator = ConfigurationGenerator(static_data)
            generator.create_directory(target)

            self.assertTrue(target.is_dir())
            self.assertEqual(list(target.iterdir()), [])
            self.assertTrue((sibling / "keep.txt").is_file())

    def test_control_run_preserves_paths_as_single_arguments(self):
        with tempfile.TemporaryDirectory(prefix="sandbox path ") as tmp:
            root = Path(tmp)
            gpkg_file = (
                root
                / "input resources"
                / "hydrofabric"
                / "gage_12345678.gpkg"
            )
            output_dir = root / "run outputs" / "12345678"
            realization = (
                output_dir
                / "configs"
                / "control"
                / "realization_test.json"
            )
            gpkg_file.parent.mkdir(parents=True)
            realization.parent.mkdir(parents=True)
            gpkg_file.touch()
            realization.touch()

            ctx = SimpleNamespace(
                gage_ids=["12345678"],
                gpkg_dirs=[gpkg_file],
                output_dirs=[output_dir],
                forcing_files=[root / "forcing files" / "forcing.nc"],
                ngen_dir=root / "ngen build",
                sandbox_dir=root / "sandbox source",
                sandbox_config={"simulation": {"partitioning": {}}},
                simulation_time={
                    "start_time": "2010-01-01 00:00:00",
                    "end_time": "2010-01-02 00:00:00",
                },
                dryrun=False,
            )
            runner = Runner(ctx)
            runner.mpirun_exists = False

            with patch(
                "src.python.runner.helper.prepare_basin_partitioning",
                return_value=(None, 1),
            ), patch("src.python.runner.os.chdir"), patch(
                "src.python.runner.os.getcwd",
                return_value=str(output_dir),
            ), patch(
                "src.python.runner.subprocess.run",
                return_value=SimpleNamespace(returncode=0),
            ) as run, patch.object(
                runner,
                "validate_configuration_profile",
            ):
                runner.run_ngen_without_calibration()

            command = run.call_args.args[0]
            self.assertIsInstance(command, list)
            self.assertEqual(command[0], str(root / "ngen build/cmake_build/ngen"))
            self.assertEqual(command[1], str(gpkg_file))
            self.assertEqual(command[3], str(gpkg_file))
            self.assertEqual(command[5], str(realization))
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_forcing_run_preserves_paths_as_single_arguments(self):
        with tempfile.TemporaryDirectory(prefix="sandbox path ") as tmp:
            root = Path(tmp)
            resource = root / "input resources" / "gage_12345678.gpkg"
            resource.parent.mkdir(parents=True)
            resource.touch()

            forcing_python = root / "forcing env" / "bin" / "python"
            forcing_python.parent.mkdir(parents=True)
            forcing_python.touch()
            forcing_config = root / "generated configs" / "forcing input.yaml"

            processor = object.__new__(ForcingProcessor)
            processor.sandbox_dir = root / "sandbox source"
            processor.forcing_venv_dir = root / "forcing env"
            processor.forcing_dir = str(root / "forcing output" / "<gage_id>")
            processor.forcing_format = ".csv"
            processor.write_forcing_input_files = lambda forcing_dir: forcing_config

            with patch("src.python.forcing.os.chdir"), patch(
                "src.python.forcing.has_gpkg_file",
                return_value=True,
            ), patch(
                "src.python.forcing.find_gpkg_file",
                return_value=resource,
            ), patch(
                "src.python.forcing.resource_id",
                return_value="12345678",
            ), patch(
                "src.python.forcing.subprocess.run",
                return_value=SimpleNamespace(returncode=0),
            ) as run:
                failed = processor.forcing_generate_catchment(resource)

            self.assertFalse(failed)
            command = run.call_args.args[0]
            self.assertEqual(command[0], str(forcing_python))
            self.assertEqual(
                command[1],
                str(
                    root
                    / "sandbox source"
                    / "extern"
                    / "CIROH_DL_NextGen"
                    / "forcing_prep"
                    / "generate.py"
                ),
            )
            self.assertEqual(command[2], str(forcing_config))
            self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
