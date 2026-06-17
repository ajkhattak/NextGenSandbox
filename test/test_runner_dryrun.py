from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.python.runner import Runner


class TestRunnerDryRun(unittest.TestCase):
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
            ), patch.object(runner, "run_ngen_experiment") as run_experiment:
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
