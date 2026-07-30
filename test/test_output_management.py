from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from sandbox import (
    validate_output_management_args,
    validate_output_management_task,
)
from src.python.helper import (
    prepare_configuration_output,
    replace_run_output,
)


class TestOutputManagement(unittest.TestCase):
    def test_configuration_preserves_existing_files_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "12345678"
            (output_dir / "configs").mkdir(parents=True)
            (output_dir / "configs" / "existing.yml").write_text("existing")
            (output_dir / "old_worker").mkdir()

            prepare_configuration_output(
                output_dir,
                "calibration",
                project_output_dir=Path(temp_dir),
            )

            self.assertTrue((output_dir / "configs" / "existing.yml").exists())
            self.assertTrue((output_dir / "old_worker").exists())

    def test_replace_existing_configuration_only_replaces_configs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "12345678"
            (output_dir / "configs").mkdir(parents=True)
            (output_dir / "configs" / "existing.yml").write_text("existing")
            (output_dir / "old_worker").mkdir()

            prepare_configuration_output(
                output_dir,
                "calibration",
                project_output_dir=Path(temp_dir),
                replace_existing=True,
            )

            self.assertTrue((output_dir / "configs").is_dir())
            self.assertFalse((output_dir / "configs" / "existing.yml").exists())
            self.assertTrue((output_dir / "old_worker").exists())

    def test_reset_output_recreates_selected_gage_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "12345678"
            (output_dir / "configs").mkdir(parents=True)
            (output_dir / "old_worker").mkdir()
            (output_dir / "result.txt").write_text("old")

            prepare_configuration_output(
                output_dir,
                "control",
                project_output_dir=Path(temp_dir),
                reset_output=True,
            )

            self.assertTrue((output_dir / "configs").is_dir())
            self.assertTrue((output_dir / "outputs" / "div").is_dir())
            self.assertTrue((output_dir / "outputs" / "troute").is_dir())
            self.assertFalse((output_dir / "old_worker").exists())
            self.assertFalse((output_dir / "result.txt").exists())

    def test_replace_run_preserves_configs_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "12345678"
            (output_dir / "configs").mkdir(parents=True)
            (output_dir / "configs" / "realization.json").write_text("{}")
            (output_dir / "simulation_metadata.yml").write_text("gage: 12345678")
            (output_dir / "old_worker").mkdir()
            (output_dir / "outputs").mkdir()
            (output_dir / "run_index.yml").write_text("runs: []")
            (output_dir / "params_parameter_df_state.parquet").touch()

            replace_run_output(
                output_dir,
                "calibration",
                project_output_dir=Path(temp_dir),
                metadata_file="simulation_metadata.yml",
            )

            self.assertTrue((output_dir / "configs" / "realization.json").exists())
            self.assertTrue((output_dir / "simulation_metadata.yml").exists())
            self.assertFalse((output_dir / "old_worker").exists())
            self.assertFalse((output_dir / "outputs").exists())
            self.assertFalse((output_dir / "run_index.yml").exists())
            self.assertFalse(
                (output_dir / "params_parameter_df_state.parquet").exists()
            )

    def test_control_run_replacement_recreates_output_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "12345678"
            (output_dir / "configs").mkdir(parents=True)
            (output_dir / "outputs" / "div").mkdir(parents=True)
            (output_dir / "outputs" / "div" / "old.csv").touch()

            replace_run_output(
                output_dir,
                "control",
                project_output_dir=Path(temp_dir),
            )

            self.assertTrue((output_dir / "outputs" / "div").is_dir())
            self.assertTrue((output_dir / "outputs" / "troute").is_dir())
            self.assertFalse((output_dir / "outputs" / "div" / "old.csv").exists())

    def test_refuses_to_reset_project_output_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "gage-specific"):
                prepare_configuration_output(
                    temp_dir,
                    "control",
                    project_output_dir=temp_dir,
                    reset_output=True,
                )

    def test_output_options_are_step_specific(self):
        valid_conf = SimpleNamespace(
            replace_existing=True,
            reset_output=False,
            conf=True,
            run=False,
            dryrun=False,
        )
        validate_output_management_args(valid_conf)

        invalid_reset = SimpleNamespace(
            replace_existing=False,
            reset_output=True,
            conf=False,
            run=True,
            dryrun=False,
        )
        with self.assertRaisesRegex(ValueError, "only be used with --conf"):
            validate_output_management_args(invalid_reset)

        conflicting = SimpleNamespace(
            replace_existing=True,
            reset_output=True,
            conf=True,
            run=False,
            dryrun=False,
        )
        with self.assertRaisesRegex(ValueError, "cannot be used together"):
            validate_output_management_args(conflicting)

    def test_state_dependent_tasks_reject_destructive_replacement(self):
        replace_run = SimpleNamespace(
            replace_existing=True,
            reset_output=False,
            conf=False,
            run=True,
            dryrun=False,
        )
        with self.assertRaisesRegex(ValueError, "existing calibration state"):
            validate_output_management_task(replace_run, "validation")

        reset_config = SimpleNamespace(
            replace_existing=False,
            reset_output=True,
            conf=True,
            run=False,
            dryrun=False,
        )
        with self.assertRaisesRegex(ValueError, "existing calibration state"):
            validate_output_management_task(reset_config, "restart")

        replace_configs = SimpleNamespace(
            replace_existing=True,
            reset_output=False,
            conf=True,
            run=False,
            dryrun=False,
        )
        validate_output_management_task(replace_configs, "validation")


if __name__ == "__main__":
    unittest.main()
