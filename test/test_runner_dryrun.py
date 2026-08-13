import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.python.runner import Runner


class TestRunnerDryRun(unittest.TestCase):
    def test_linux_runtime_is_scoped_to_spawned_processes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox_env = Path(temp_dir) / "sandbox"
            runtime = sandbox_env / "lib" / "libstdc++.so.6"
            runtime.parent.mkdir(parents=True)
            runtime.touch()

            runner = Runner(SimpleNamespace())
            runner.os_name = "Linux"
            original_library_path = os.environ.get("LD_LIBRARY_PATH")
            original_preload = os.environ.get("LD_PRELOAD")
            with patch.dict(
                os.environ,
                {
                    "SANDBOX_ENV": str(sandbox_env),
                    "LD_LIBRARY_PATH": "/hpc/netcdf/lib:/hpc/gcc/lib",
                },
                clear=False,
            ):
                os.environ.pop("LD_PRELOAD", None)
                run_env = runner.subprocess_environment()

                self.assertEqual(
                    run_env["LD_LIBRARY_PATH"].split(os.pathsep),
                    [
                        str(runtime.parent),
                        "/hpc/netcdf/lib",
                        "/hpc/gcc/lib",
                    ],
                )
                self.assertEqual(run_env["LD_PRELOAD"], str(runtime))
                self.assertNotIn("LD_PRELOAD", os.environ)

            self.assertEqual(
                os.environ.get("LD_LIBRARY_PATH"),
                original_library_path,
            )
            self.assertEqual(os.environ.get("LD_PRELOAD"), original_preload)

    def test_calibration_run_rejects_mismatched_resource_counts(self):
        ctx = SimpleNamespace(
            formulation="CFE",
            task_type="calibration",
            gage_ids=["12345678", "87654321"],
            gpkg_dirs=[Path("gage_12345678.gpkg"), Path("gage_87654321.gpkg")],
            output_dirs=[Path("12345678"), Path("87654321")],
            forcing_files=[Path("forcing_12345678.nc")],
        )
        runner = Runner(ctx)

        with self.assertRaises(ValueError):
            runner.run()

    def test_control_run_uses_context_resolved_resource_layout_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gpkg_file = root / "inputs" / "hydrofabric" / "gage_12345678.gpkg"
            output_dir = root / "outputs" / "12345678"
            gpkg_file.parent.mkdir(parents=True)
            config_dir = output_dir / "configs" / "control"
            config_dir.mkdir(parents=True)
            gpkg_file.touch()
            (config_dir / "realization_test.json").touch()

            ctx = SimpleNamespace(
                gage_ids=["12345678"],
                gpkg_dirs=[gpkg_file],
                output_dirs=[output_dir],
                forcing_files=[root / "forcing.nc"],
                ngen_dir=root / "ngen",
                sandbox_dir=root,
                sandbox_config={"simulation": {"partitioning": {}}},
                simulation_time={
                    "start_time": "2010-01-01 00:00:00",
                    "end_time": "2010-01-02 00:00:00",
                },
                dryrun=True,
            )
            runner = Runner(ctx)

            with patch(
                "src.python.runner.helper.prepare_basin_partitioning",
                return_value=(None, 1),
            ) as prepare_partitioning, patch("src.python.runner.os.chdir"), patch(
                "src.python.runner.os.getcwd",
                return_value=str(output_dir),
            ), patch.object(
                runner,
                "validate_configuration_profile",
            ):
                runner.run_ngen_without_calibration()

            prepare_partitioning.assert_called_once_with(
                root,
                gpkg_file,
                {},
                config_dir=config_dir,
            )

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
                forcing_file=None,
            )


if __name__ == "__main__":
    unittest.main()
