from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.python.runner import Runner


class TestRunnerDryRun(unittest.TestCase):
    def test_control_run_uses_context_resolved_resource_layout_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gpkg_file = root / "inputs" / "hydrofabric" / "gage_12345678.gpkg"
            output_dir = root / "outputs" / "12345678"
            gpkg_file.parent.mkdir(parents=True)
            (output_dir / "configs").mkdir(parents=True)
            gpkg_file.touch()
            (output_dir / "configs" / "realization_test.json").touch()

            ctx = SimpleNamespace(
                gage_ids=["12345678"],
                gpkg_dirs=[gpkg_file],
                output_dirs=[output_dir],
                ngen_dir=root / "ngen",
                sandbox_dir=root,
                sandbox_config={"simulation": {"partitioning": {}}},
                dryrun=True,
            )
            runner = Runner(ctx)

            with patch(
                "src.python.runner.helper.prepare_basin_partitioning",
                return_value=(None, 1),
            ) as prepare_partitioning, patch("src.python.runner.os.chdir"), patch(
                "src.python.runner.os.getcwd",
                return_value=str(output_dir),
            ):
                runner.run_ngen_without_calibration()

            prepare_partitioning.assert_called_once_with(root, gpkg_file, {})

    def test_calibvalid_dryrun_skips_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            (input_dir / "data").mkdir(parents=True)
            output_dir.mkdir()
            (input_dir / "data" / "gage_12345678.gpkg").touch()

            ctx = SimpleNamespace(
                task_type="calibvalid",
                dryrun=True,
                sandbox_dir=root,
                sandbox_config={"simulation": {"partitioning": {}}},
                model_registry={},
            )
            runner = Runner(ctx)

            with patch(
                "src.python.runner.helper.prepare_basin_partitioning",
                return_value=(None, 1),
            ), patch.object(runner, "run_ngen_experiment") as run_experiment, patch(
                "src.python.runner.os.chdir"
            ):
                runner.run_ngen_with_calibration(
                    ("12345678", input_dir, output_dir, None)
                )

            run_experiment.assert_called_once_with(
                "calibration",
                input_dir / "data" / "gage_12345678.gpkg",
                output_dir,
                None,
                "12345678",
            )


if __name__ == "__main__":
    unittest.main()
