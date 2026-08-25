import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.python.launcher import cli as launcher


class TestLauncherSelection(unittest.TestCase):
    @staticmethod
    def _write_launcher_metadata(
        metadata_index_dir: Path,
        gage_id: str,
        output_dir: Path,
    ) -> None:
        metadata_index_dir.mkdir(parents=True, exist_ok=True)
        (metadata_index_dir / f"run_{gage_id}.yml").write_text(
            yaml.safe_dump({"output_dir": str(output_dir)})
        )

    def test_experiment_selections_merge_for_repeated_gage_groups(self):
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
                "project": {
                    "gages": {
                        "option": "file",
                        "file": {
                            "path": str(csv_path),
                            "id_column": "gage_id",
                            "group_column": "group_name",
                        },
                    }
                },
                "experiments": {
                    "pet_cfe_s": {
                        "models": "PET, CFE, T-route",
                        "selection": {"groups": ["snowy"]},
                    },
                    "pet_cfe_x": {
                        "models": "PET, CFE, T-route",
                        "selection": {"groups": ["benchmark"]},
                    },
                    "pet_topmodel": {
                        "models": "PET, TopModel, T-route",
                        "selection": {"groups": ["arid"]},
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
            self.assertEqual(summary["pet_cfe_s"], 1)
            self.assertEqual(summary["pet_cfe_x"], 1)
            self.assertNotIn(
                "selection",
                map_config["formulations"]["pet_cfe_s"],
            )

    def test_experiment_selection_combines_groups_and_ids(self):
        gage_groups = {
            "01109403": ["snowy"],
            "02299950": ["arid"],
            "03366500": ["humid"],
        }

        selected = launcher.resolve_experiment_gages(
            "pet_cfe",
            {
                "models": "PET, CFE, T-route",
                "selection": {
                    "groups": ["snowy"],
                    "ids": ["03366500"],
                },
            },
            gage_groups,
        )

        self.assertEqual(selected, ["01109403", "03366500"])

    def test_experiment_selection_is_required(self):
        with self.assertRaisesRegex(ValueError, "selection.*required"):
            launcher.resolve_experiment_gages(
                "pet_cfe",
                {"models": "PET, CFE, T-route"},
                {"01109403": []},
            )

    def test_experiment_selection_rejects_unknown_ids(self):
        with self.assertRaisesRegex(ValueError, "outside project.gages"):
            launcher.resolve_experiment_gages(
                "pet_cfe",
                {
                    "models": "PET, CFE, T-route",
                    "selection": {"ids": ["99999999"]},
                },
                {"01109403": []},
            )

    def test_experiment_selection_rejects_unknown_groups(self):
        with self.assertRaisesRegex(ValueError, "unknown project gage group"):
            launcher.resolve_experiment_gages(
                "pet_cfe",
                {
                    "models": "PET, CFE, T-route",
                    "selection": {"groups": ["snowy"]},
                },
                {"01109403": ["arid"]},
            )

    def test_project_gages_must_all_receive_an_experiment(self):
        config = {
            "project": {
                "gages": {
                    "option": "ids",
                    "ids": ["01109403", "02299950"],
                }
            },
            "experiments": {
                "pet_cfe": {
                    "models": "PET, CFE, T-route",
                    "selection": {"ids": ["01109403"]},
                }
            },
        }

        with self.assertRaisesRegex(ValueError, "not selected.*02299950"):
            launcher.build_map_from_launcher_config(
                config,
                Path("/tmp"),
            )

    def test_dryrun_is_a_standalone_launcher_mode(self):
        with patch.object(
            sys,
            "argv",
            ["sandbox_launcher.py", "dryrun", "--backend", "local"],
        ):
            args = launcher.parse_args()

        self.assertEqual(args.mode, "dryrun")
        self.assertEqual(args.backend, "local")
        self.assertFalse(hasattr(args, "dryrun"))

    def test_submit_is_a_standalone_launcher_mode(self):
        with patch.object(
            sys,
            "argv",
            ["sandbox-launcher", "submit", "--config", "launcher_pso.yaml"],
        ):
            args = launcher.parse_args()

        self.assertEqual(args.mode, "submit")
        self.assertEqual(args.config, "launcher_pso.yaml")

    def test_status_defaults_to_summary_view(self):
        with patch.object(
            sys,
            "argv",
            ["sandbox-launcher", "status", "--config", "launcher.yaml"],
        ):
            args = launcher.parse_args()

        self.assertEqual(args.status_view, "summary")

    def test_status_accepts_detailed_view(self):
        with patch.object(
            sys,
            "argv",
            [
                "sandbox-launcher",
                "status",
                "--detailed",
                "--config",
                "launcher.yaml",
            ],
        ):
            args = launcher.parse_args()

        self.assertEqual(args.status_view, "detailed")

    def test_status_accepts_explicit_summary(self):
        with patch.object(
            sys,
            "argv",
            [
                "sandbox-launcher",
                "status",
                "--summary",
                "--config",
                "launcher.yaml",
            ],
        ):
            args = launcher.parse_args()

        self.assertEqual(args.status_view, "summary")

    def test_launcher_stages_are_explicit(self):
        self.assertEqual(
            launcher.load_launcher_stages(
                {"stages": ["calibration", "validation"]}
            ),
            ("calibration", "validation"),
        )

    def test_launcher_rejects_missing_stages(self):
        with self.assertRaisesRegex(ValueError, "explicitly define stages"):
            launcher.load_launcher_stages({})

    def test_launcher_rejects_validation_before_calibration(self):
        with self.assertRaisesRegex(ValueError, "stages must be one of"):
            launcher.load_launcher_stages(
                {"stages": ["validation", "calibration"]}
            )

    def test_dryrun_mode_previews_without_running(self):
        context = object()
        args = SimpleNamespace(
            mode="dryrun",
            backend="local",
            config="launcher_config.yaml",
        )
        with (
            patch.object(launcher, "parse_args", return_value=args),
            patch.object(launcher, "load_context", return_value=context),
            patch.object(launcher, "validate_context") as validate,
            patch.object(
                launcher,
                "validate_launcher_resources",
            ) as validate_resources,
            patch.object(launcher, "runner") as run,
        ):
            launcher.main()

        validate.assert_called_once_with(context)
        validate_resources.assert_called_once_with(context)
        run.assert_called_once_with(
            context,
            use_slurm=False,
            dryrun=True,
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
            launcher.validate_sandbox_config(config)

    def test_launcher_does_not_require_injected_placeholders(self):
        config = {
            "general": {
                "input_dir": "/tmp/inputs",
                "output_dir": "/tmp/outputs",
            },
            "forcings": {"gages": "all"},
            "simulation": {
                "outputs": {
                    "metadata": {
                        "enabled": True,
                        "index_dir": "metadata",
                    }
                },
            },
        }

        launcher.validate_sandbox_config(config)

    def test_launcher_loads_sandbox_settings_from_same_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / "launcher_dds.yaml"
            config_file.write_text(
                yaml.safe_dump(
                    {
                        "project": {
                            "input_dir": "inputs",
                            "output_dir": "outputs",
                            "resource_layout": "gage",
                            "gages": {
                                "option": "ids",
                                "ids": ["01109403"],
                            },
                        },
                        "sandbox": {
                            "forcings": {"gages": "all"},
                            "calibration": {
                                "optimizer": {
                                    "algorithm": "dds",
                                    "iterations": 25,
                                },
                                "objective": {"function": "kge"},
                            },
                            "simulation": {
                                "time": {
                                    "calibration": {
                                        "start": "2015-10-01",
                                        "spinup": "12 months",
                                        "evaluation": "2 years",
                                    }
                                },
                                "outputs": {
                                    "metadata": {
                                        "enabled": True,
                                        "index_dir": "metadata",
                                    }
                                },
                            },
                        },
                        "stages": ["calibration", "validation"],
                        "experiments": {
                            "pet_cfe": {
                                "models": "PET, CFE, T-route",
                                "selection": "all",
                            }
                        },
                    }
                )
            )

            context = launcher.load_context(config_file)

            self.assertEqual(
                context.sandbox_cfg["general"]["input_dir"],
                str((root / "inputs").resolve()),
            )
            self.assertEqual(
                context.sandbox_cfg["calibration"]["optimizer"]["iterations"],
                25,
            )
            self.assertEqual(context.campaign_name, "launcher_dds")
            self.assertEqual(
                context.log_dir,
                (root / "outputs").resolve() / "logs",
            )

    def test_project_path_validation_reports_missing_input_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = SimpleNamespace(
                input_dir=root / "missing-inputs",
                output_dir=root / "outputs",
                launcher_config_file=root / "launcher.yaml",
            )

            with self.assertRaisesRegex(
                FileNotFoundError,
                "project.input_dir does not exist",
            ):
                launcher.validate_project_paths(context)

    def test_launcher_resource_preflight_resolves_gage_forcing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gage_id = "08070500"
            hydrofabric = root / "inputs" / gage_id / "hydrofabric"
            forcing = root / "inputs" / gage_id / "forcing" / "2000_to_2024"
            hydrofabric.mkdir(parents=True)
            forcing.mkdir(parents=True)
            (hydrofabric / f"gage_{gage_id}.gpkg").touch()
            forcing_file = forcing / f"gage_{gage_id}_corrected.nc"
            forcing_file.touch()
            context = SimpleNamespace(
                input_dir=root / "inputs",
                launcher_dir=root,
                map_cfg={"mapping": {gage_id: ["pet_cfe"]}},
                sandbox_cfg={
                    "general": {"resource_layout": "gage"},
                    "forcings": {
                        "format": ".nc",
                        "time": {
                            "start": "2000-10-01",
                            "end": "2023-09-30 23:00:00",
                        },
                        "use_corrected": True,
                        "rechunk": False,
                    },
                    "observations": {},
                },
            )

            launcher.validate_launcher_resources(context)
            self.assertEqual(
                launcher.resolve_launcher_forcing(context, gage_id),
                forcing_file,
            )

    def test_launcher_resource_preflight_reports_mismatched_gage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual_gage = "08070500"
            requested_gage = "08075400"
            hydrofabric = root / "inputs" / actual_gage / "hydrofabric"
            forcing = (
                root
                / "inputs"
                / actual_gage
                / "forcing"
                / "2000_to_2024"
            )
            hydrofabric.mkdir(parents=True)
            forcing.mkdir(parents=True)
            (hydrofabric / f"gage_{actual_gage}.gpkg").touch()
            (forcing / f"gage_{actual_gage}_corrected.nc").touch()
            context = SimpleNamespace(
                input_dir=root / "inputs",
                launcher_dir=root,
                map_cfg={"mapping": {requested_gage: ["pet_cfe"]}},
                sandbox_cfg={
                    "general": {"resource_layout": "gage"},
                    "forcings": {
                        "format": ".nc",
                        "time": {
                            "start": "2000-10-01",
                            "end": "2023-09-30 23:00:00",
                        },
                        "use_corrected": True,
                        "rechunk": False,
                    },
                    "observations": {},
                },
            )

            with self.assertRaisesRegex(
                FileNotFoundError,
                "08075400.*2000_to_2024",
            ):
                launcher.validate_launcher_resources(context)

    def test_project_path_validation_rejects_unwritable_output_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            input_dir.mkdir()
            context = SimpleNamespace(
                input_dir=input_dir,
                output_dir=root / "missing" / "outputs",
                launcher_config_file=root / "launcher.yaml",
            )

            with patch.object(launcher.os, "access", return_value=False):
                with self.assertRaisesRegex(
                    PermissionError,
                    "project.output_dir cannot be created",
                ):
                    launcher.validate_project_paths(context)

    def test_launcher_requires_inline_sandbox_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "launcher_config.yaml"
            config_file.write_text("project: {}\n")

            with self.assertRaisesRegex(ValueError, "non-empty sandbox mapping"):
                launcher.load_context(config_file)

    def test_launcher_rejects_external_sandbox_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "launcher_config.yaml"
            config_file.write_text(
                "templates:\n  sandbox_config: sandbox_config.yaml\n"
            )

            with self.assertRaisesRegex(ValueError, "no longer supported"):
                launcher.load_context(config_file)

    def test_launcher_rejects_top_level_gages_and_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "launcher_config.yaml"
            config_file.write_text("gages: {}\nassignment: {}\n")

            with self.assertRaisesRegex(ValueError, "project.gages"):
                launcher.load_context(config_file)

    def test_generated_configs_use_only_sandbox_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = SimpleNamespace(
                sandbox_cfg={
                    "general": {
                        "input_dir": "/tmp/inputs",
                        "output_dir": "/tmp/outputs",
                    },
                    "calibration": {
                        "optimizer": {
                            "algorithm": "dds",
                            "iterations": 25,
                        },
                        "objective": {"function": "kge"},
                    },
                    "simulation": {
                        "time": {},
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
                {
                    "sandbox_main",
                    "sandbox_restart",
                    "sandbox_pso_warm_start",
                    "pso_warm_start_settings",
                    "sandbox_validation",
                },
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

    def test_regime_configs_use_scenario_output_and_calibration_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = SimpleNamespace(
                sandbox_cfg={
                    "general": {
                        "input_dir": "/tmp/inputs",
                        "output_dir": "/tmp/outputs",
                        "gages": {"option": "ids", "ids": []},
                    },
                    "calibration": {
                        "optimizer": {"algorithm": "dds", "iterations": 25},
                        "objective": {"function": "kge"},
                    },
                    "formulation": {"models": ""},
                    "simulation": {
                        "task_type": "calibvalid",
                        "label": "old_label",
                        "gages": [],
                        "time": {"calibration": {}},
                    },
                },
                output_dir=root / "outputs",
                metadata_index_dir_name="metadata",
            )
            scenario = launcher.CalibrationScenario(
                name="dry",
                calibration={
                    "start": "2016-10-01 00:00:00",
                    "end": "2023-09-30 23:00:00",
                    "spinup": "12 months",
                    "evaluation": {
                        "years": [2018, 2020, 2021, 2022, 2023],
                        "year_type": "water_year",
                    },
                },
                selected_years=(2018, 2020, 2021, 2022, 2023),
            )
            config_dir, metadata_dir = launcher.experiment_dirs(
                ctx,
                "pet_cfe",
                scenario.name,
            )

            with patch.object(launcher.subprocess, "run"):
                launcher.generate_config_files_for_gage(
                    ctx,
                    "pet_cfe",
                    {"models": "PET, CFE, T-ROUTE"},
                    "pet_cfe",
                    "01109403",
                    config_dir,
                    metadata_dir,
                    scenario=scenario,
                )

            paths = launcher.generated_config_paths(config_dir, "01109403")
            generated = yaml.safe_load(paths["sandbox_main"].read_text())
            self.assertEqual(
                generated["general"]["output_dir"],
                str(root / "outputs" / "pet_cfe" / "dry"),
            )
            self.assertEqual(
                generated["simulation"]["time"]["calibration"],
                scenario.calibration,
            )
            self.assertNotIn("label", generated["simulation"])
            restart = yaml.safe_load(paths["sandbox_restart"].read_text())
            self.assertEqual(
                restart["simulation"]["restart_dir"],
                str(root / "outputs" / "pet_cfe" / "dry" / "01109403"),
            )

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

    def test_slurm_command_requests_one_cpu_per_mpi_task(self):
        command = launcher.build_slurm_submit_command(
            Path("/tmp/submit_gage.slurm"),
            Path("/tmp/sandbox_config.yaml"),
            "pet_cfe_01109403",
            num_mpi_tasks=4,
            delay_seconds=10,
            stage="calibration",
        )

        self.assertIn("--ntasks-per-node=4", command)
        self.assertIn("--cpus-per-task=1", command)
        self.assertIn("--parsable", command)
        self.assertNotIn("--cpus-per-task=4", command)
        self.assertIn("SANDBOX_STAGE=calibration", command[-2])

    def test_slurm_command_applies_launcher_resource_overrides(self):
        command = launcher.build_slurm_submit_command(
            Path("/tmp/submit_gage.slurm"),
            Path("/tmp/sandbox_config.yaml"),
            "pet_cfe_wet_01109403",
            num_mpi_tasks=4,
            delay_seconds=10,
            stage="validation",
            slurm={
                "account": "project123",
                "partition": "shared",
                "time": "12:00:00",
                "memory": "8G",
                "mpi_tasks": "auto",
            },
        )

        self.assertIn("--account=project123", command)
        self.assertIn("--partition=shared", command)
        self.assertIn("--time=12:00:00", command)
        self.assertIn("--mem=8G", command)
        self.assertIn("SANDBOX_STAGE=validation", command[-2])

    def test_slurm_command_routes_worker_logs_to_output_directory(self):
        command = launcher.build_slurm_submit_command(
            Path("/tmp/submit_gage.slurm"),
            Path("/tmp/sandbox_config.yaml"),
            "pet_cfe_01109403",
            num_mpi_tasks=4,
            delay_seconds=0,
            stage="calibration",
            log_dir=Path("/project/outputs/logs"),
            work_dir=Path("/project/outputs"),
        )

        self.assertIn(
            "--output=/project/outputs/logs/%x_%j.out",
            command,
        )
        self.assertIn(
            "--error=/project/outputs/logs/%x_%j.err",
            command,
        )
        self.assertIn("--chdir=/project/outputs", command)

    def test_launcher_submit_command_uses_config_and_output_paths(self):
        context = SimpleNamespace(
            campaign_name="launcher_pso",
            launcher_config_file=Path("/project/launcher_pso.yaml"),
            output_dir=Path("/project/outputs/pso"),
            log_dir=Path("/project/outputs/pso/logs"),
            slurm={"account": "project123", "partition": "shared"},
        )

        command = launcher.build_launcher_submit_command(context)

        self.assertIn("--job-name=launcher_pso_launcher", command)
        self.assertIn("--parsable", command)
        self.assertIn(
            "--output=/project/outputs/pso/logs/%x_%j.out",
            command,
        )
        self.assertIn("--chdir=/project/outputs/pso", command)
        self.assertIn("--account=project123", command)
        self.assertIn("--partition=shared", command)
        self.assertIn(
            "--export=ALL,LAUNCHER_CONFIG=/project/launcher_pso.yaml",
            command,
        )
        self.assertEqual(
            Path(command[-1]),
            launcher.LAUNCHER_PACKAGE_DIR / "submit_launcher.sh",
        )

    def test_launcher_followup_waits_for_worker_jobs(self):
        context = SimpleNamespace(
            campaign_name="launcher_pso",
            launcher_config_file=Path("/project/launcher_pso.yaml"),
            output_dir=Path("/project/outputs/pso"),
            log_dir=Path("/project/outputs/pso/logs"),
            slurm={"account": "project123", "partition": "shared"},
        )

        command = launcher.build_launcher_submit_command(
            context,
            ("123", "456"),
        )

        self.assertIn(
            "--dependency=afterany:123?afterany:456",
            command,
        )

    def test_launcher_default_files_use_config_and_package_directories(self):
        self.assertEqual(
            launcher.default_config_file(),
            launcher.LAUNCHER_CONFIG_DIR / "launcher_config.yaml",
        )
        self.assertTrue(
            (launcher.LAUNCHER_PACKAGE_DIR / "submit_launcher.sh").is_file()
        )
        coordinator = (
            launcher.LAUNCHER_PACKAGE_DIR / "submit_launcher.sh"
        ).read_text()
        self.assertNotIn("scontrol requeue", coordinator)
        self.assertNotIn("LAUNCHER_WALLCLOCK", coordinator)

    def test_worker_script_contains_configured_modules_and_environment(self):
        script = launcher.render_slurm_worker_script(
            {
                "modules": ["openmpi/4.1.6", "netcdf-fortran/4.6.1"],
                "environment": {
                    "OMP_NUM_THREADS": "1",
                    "MODEL_MODE": "test value",
                },
            }
        )

        self.assertIn("module load openmpi/4.1.6", script)
        self.assertIn("module load netcdf-fortran/4.6.1", script)
        self.assertIn("export OMP_NUM_THREADS=1", script)
        self.assertIn("export MODEL_MODE='test value'", script)
        self.assertIn('"$SANDBOX_COMMAND" --run -i "$SANDBOX_FILE"', script)

    def test_slurm_rejects_reserved_environment_variable(self):
        with self.assertRaisesRegex(ValueError, "cannot override"):
            launcher.validate_slurm_config(
                {
                    "modules": [],
                    "environment": {"SANDBOX_FILE": "/tmp/config.yaml"},
                    "startup_delay_seconds": 0,
                    "calibration": {"time": "01:00:00", "memory": "8G"},
                    "validation": {"time": "01:00:00", "memory": "8G"},
                }
            )

    def test_submit_mode_creates_output_logs_and_submits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = SimpleNamespace(
                campaign_name="launcher_dds",
                launcher_config_file=root / "launcher_dds.yaml",
                output_dir=root / "outputs" / "dds",
                log_dir=root / "outputs" / "dds" / "logs",
                slurm={
                    "max_active_jobs": 2,
                    "max_total_mpi_tasks": 8,
                },
            )
            completed = SimpleNamespace(stdout="123\n")

            with patch.object(
                launcher.subprocess,
                "run",
                return_value=completed,
            ) as run:
                job_id = launcher.submit_launcher(context)

            self.assertTrue(context.log_dir.is_dir())
            worker_script = launcher.worker_script_path(context)
            self.assertTrue(worker_script.is_file())
            self.assertTrue(worker_script.stat().st_mode & 0o100)
            run.assert_called_once()
            self.assertTrue(run.call_args.kwargs["check"])
            self.assertEqual(job_id, "123")

    def test_submit_mode_requires_slurm_settings(self):
        context = SimpleNamespace(slurm={})

        with self.assertRaisesRegex(ValueError, "requires a slurm block"):
            launcher.submit_launcher(context)

    def test_slurm_uses_stage_specific_resources(self):
        slurm = {
            "account": "project123",
            "calibration": {"time": "04:00:00", "memory": "8G"},
            "validation": {"time": "12:00:00", "memory": "64G"},
        }

        self.assertEqual(
            launcher.slurm_settings_for_stage(slurm, "calibration"),
            {
                "account": "project123",
                "time": "04:00:00",
                "memory": "8G",
            },
        )
        self.assertEqual(
            launcher.slurm_settings_for_stage(slurm, "validation"),
            {
                "account": "project123",
                "time": "12:00:00",
                "memory": "64G",
            },
        )

    def test_slurm_requires_resources_for_both_stages(self):
        with self.assertRaisesRegex(ValueError, "slurm.validation"):
            launcher.validate_slurm_config(
                {
                    "max_active_jobs": 2,
                    "max_total_mpi_tasks": 8,
                    "startup_delay_seconds": 5,
                    "calibration": {
                        "time": "04:00:00",
                        "memory": "8G",
                    },
                }
            )

    def test_slurm_execution_requires_active_job_limit(self):
        with self.assertRaisesRegex(ValueError, "max_active_jobs"):
            launcher.slurm_limits({})

    def test_slurm_execution_requires_mpi_task_limit(self):
        with self.assertRaisesRegex(ValueError, "max_total_mpi_tasks"):
            launcher.slurm_limits({"max_active_jobs": 4})

    def test_active_slurm_jobs_include_requested_cpus(self):
        with patch.object(
            launcher.subprocess,
            "check_output",
            return_value=(
                "101|pet_cfe_01109403|4|RUNNING\n"
                "102|pet_cfe_08070500|12|PENDING\n"
            ),
        ):
            jobs = launcher.get_active_slurm_jobs()

        self.assertEqual(
            jobs,
            [
                launcher.ActiveSlurmJob(
                    "101", "pet_cfe_01109403", 4, "RUNNING"
                ),
                launcher.ActiveSlurmJob(
                    "102", "pet_cfe_08070500", 12, "PENDING"
                ),
            ],
        )

    def test_slurm_history_reports_latest_terminal_state_per_experiment(self):
        submitted = {
            "101": "pet_cfe_01109403",
            "102": "pet_cfe_01109403",
            "103": "pet_cfe_08070500",
        }
        with patch.object(
            launcher.subprocess,
            "check_output",
            return_value=(
                "101|TIMEOUT|0:0\n"
                "102|OUT_OF_MEMORY|0:125\n"
                "103|CANCELLED by 1234|0:15\n"
            ),
        ):
            history = launcher.get_slurm_job_history(submitted)

        self.assertEqual(
            history["pet_cfe_01109403"].state,
            "OUT_OF_MEMORY",
        )
        self.assertEqual(
            history["pet_cfe_08070500"].state,
            "CANCELLED",
        )

    def test_terminal_campaign_states_are_distinct(self):
        progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=4,
        )
        states = {
            state: launcher.terminal_campaign_state(
                progress,
                launcher.SlurmJobHistory("101", "job", state, "0:1"),
            )
            for state in (
                "TIMEOUT",
                "OUT_OF_MEMORY",
                "FAILED",
                "CANCELLED",
            )
        }

        self.assertEqual(
            states,
            {
                "TIMEOUT": "TIMEOUT",
                "OUT_OF_MEMORY": "OUT_OF_MEMORY",
                "FAILED": "FAILED",
                "CANCELLED": "CANCELLED",
            },
        )
        self.assertEqual(
            launcher.terminal_campaign_state(progress, None),
            "WILL_BE_REQUEUED",
        )
        self.assertEqual(
            launcher.terminal_campaign_state(
                launcher.ExperimentProgress(configured=True),
                None,
            ),
            "NOT_SUBMITTED",
        )

    def test_status_summary_prints_lifecycle_and_failure_categories(self):
        statuses = [
            launcher.CampaignStatus(
                gage_id="01109403",
                formulation="pet_cfe",
                scenario="default",
                state="OUT_OF_MEMORY",
                current_iteration=3,
                max_iterations=40,
                objective_value=0.5,
                validation="NO",
                average_iteration_seconds=None,
                estimated_remaining_seconds=None,
            )
        ]
        output = StringIO()
        with (
            patch.object(
                launcher,
                "collect_campaign_status",
                return_value=(statuses, None),
            ),
            redirect_stdout(output),
        ):
            launcher.check_status(SimpleNamespace(), detailed=False)

        report = output.getvalue()
        labels = [
            "TOTAL",
            "COMPLETED",
            "RUNNING",
            "QUEUED",
            "WILL_BE_REQUEUED",
            "NOT_SUBMITTED",
            "TIMEOUT",
            "OUT_OF_MEMORY",
            "FAILED",
            "CANCELLED",
        ]
        positions = [report.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("OUT_OF_MEMORY      | 1", report)

    def test_parse_sbatch_job_id_supports_parsable_cluster_output(self):
        self.assertEqual(
            launcher.parse_sbatch_job_id("12345;anvil\n"),
            "12345",
        )

    def test_campaign_status_distinguishes_running_and_queued(self):
        gages = ("01109403", "08070500")
        context = SimpleNamespace(
            campaign_name="test_campaign",
            output_dir=Path("/tmp/outputs"),
            metadata_index_dir_name="metadata",
            stages=("calibration",),
            slurm={"max_active_jobs": 2},
            map_cfg={
                "mapping": {gage_id: ["pet_cfe"] for gage_id in gages},
                "formulations": {"pet_cfe": {"models": "PET,CFE"}},
                "groups": {},
            },
            calibration_scenarios={
                gage_id: (
                    launcher.CalibrationScenario(
                        name=None,
                        calibration={},
                    ),
                )
                for gage_id in gages
            },
        )

        with (
            patch.object(
                launcher,
                "get_active_slurm_jobs",
                return_value=[
                    launcher.ActiveSlurmJob(
                        "101", "pet_cfe_01109403", 4, "RUNNING"
                    ),
                    launcher.ActiveSlurmJob(
                        "102", "pet_cfe_08070500", 4, "PENDING"
                    ),
                ],
            ),
            patch.object(
                launcher,
                "get_experiment_progress",
                return_value=launcher.ExperimentProgress(configured=True),
            ),
            patch.object(launcher, "get_max_iter", return_value=40),
        ):
            statuses, scheduler_error = launcher.collect_campaign_status(
                context
            )

        self.assertIsNone(scheduler_error)
        self.assertEqual(
            [status.state for status in statuses],
            ["RUNNING", "QUEUED"],
        )

    def test_calibration_timing_estimates_remaining_iterations(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            worker = output_dir / "202608250100_ngen_test_worker"
            worker.mkdir()
            objective_log = worker / "objective_log.txt"
            objective_log.write_text("0, 0.8\n1, 0.6\n2, 0.5\n")
            start = launcher.datetime.strptime(
                "202608250100",
                "%Y%m%d%H%M",
            ).timestamp()
            os.utime(objective_log, (start + 180, start + 180))

            average, remaining = launcher.estimate_calibration_timing(
                output_dir,
                launcher.ExperimentProgress(
                    configured=True,
                    current_iteration=2,
                    completed_iterations=2,
                    algorithm="dds",
                ),
                max_iterations=5,
            )

        self.assertEqual(average, 60.0)
        self.assertEqual(remaining, 180.0)
        self.assertEqual(launcher.format_duration(remaining), "3m 0s")

    def test_slurm_runner_schedules_followup_after_active_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gage_id = "01109403"
            context = SimpleNamespace(
                campaign_name="regime",
                output_dir=root / "outputs",
                log_dir=root / "outputs" / "logs",
                metadata_index_dir_name="metadata",
                stages=("calibration", "validation"),
                slurm={
                    "max_active_jobs": 4,
                    "max_total_mpi_tasks": 16,
                    "startup_delay_seconds": 0,
                },
                map_cfg={
                    "mapping": {gage_id: ["pet_cfe"]},
                    "formulations": {"pet_cfe": {"models": "PET,CFE"}},
                    "groups": {},
                },
                calibration_scenarios={
                    gage_id: (
                        launcher.CalibrationScenario(
                            name=None,
                            calibration={},
                        ),
                    )
                },
            )

            with (
                patch.object(launcher, "write_slurm_worker_script"),
                patch.object(
                    launcher,
                    "get_active_slurm_jobs",
                    return_value=[
                        launcher.ActiveSlurmJob(
                            "123",
                            "pet_cfe_01109403",
                            4,
                            "RUNNING",
                        )
                    ],
                ),
                patch.object(
                    launcher,
                    "is_experiment_complete",
                    return_value=False,
                ),
                patch.object(launcher, "submit_launcher") as submit,
            ):
                launcher.runner(context, use_slurm=True)

            submit.assert_called_once_with(context, ("123",))

    def test_slurm_job_limit_defers_submission(self):
        reason = launcher.slurm_limit_reason(
            active_jobs=4,
            active_mpi_tasks=20,
            requested_mpi_tasks=2,
            max_active_jobs=4,
            max_total_mpi_tasks=32,
        )

        self.assertIn("active-job limit", reason)

    def test_slurm_mpi_task_limit_defers_submission(self):
        reason = launcher.slurm_limit_reason(
            active_jobs=2,
            active_mpi_tasks=30,
            requested_mpi_tasks=4,
            max_active_jobs=4,
            max_total_mpi_tasks=32,
        )

        self.assertIn("MPI-task limit", reason)

    def test_single_run_cannot_exceed_slurm_mpi_task_limit(self):
        with self.assertRaisesRegex(ValueError, "requires 40 MPI tasks"):
            launcher.slurm_limit_reason(
                active_jobs=0,
                active_mpi_tasks=0,
                requested_mpi_tasks=40,
                max_active_jobs=4,
                max_total_mpi_tasks=32,
            )

    def test_slurm_startup_delay_uses_global_run_sequence(self):
        self.assertEqual(
            [
                launcher.startup_delay_seconds(index, 5)
                for index in range(4)
            ],
            [0, 5, 10, 15],
        )

    def test_local_startup_delay_cycles_across_worker_slots(self):
        self.assertEqual(
            [
                launcher.startup_delay_seconds(index, 5, cycle_size=2)
                for index in range(6)
            ],
            [0, 5, 0, 5, 0, 5],
        )

    def test_regime_scenarios_select_earliest_five_complete_water_years(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "08070500_regimes.csv"
            source.write_text(
                "Water_Year,Regime\n"
                "2015,Wet\n"
                "2016,Wet\n"
                "2017,Wet\n"
                "2018,Dry\n"
                "2019,Wet\n"
                "2020,Dry\n"
                "2021,Dry\n"
                "2022,Dry\n"
                "2023,Dry\n"
                "2024,Wet\n"
            )
            config = {
                "reference": {
                    "start": "2013-10-01 00:00:00",
                    "end": "2024-09-30 23:00:00",
                    "spinup": "12 months",
                    "year_type": "water_year",
                },
                "source": {
                    "file": "<gage_id>_regimes.csv",
                    "year_column": "Water_Year",
                    "regime_column": "Regime",
                },
                "selection": {
                    "max_years": 5,
                    "order": "earliest",
                    "regimes": {"wet": "Wet", "dry": "Dry"},
                },
            }

            scenarios = launcher.resolve_regime_scenarios(
                config,
                "08070500",
                root,
            )
            by_name = {scenario.name: scenario for scenario in scenarios}

            self.assertEqual(set(by_name), {"ref", "wet", "dry"})
            self.assertNotIn("evaluation", by_name["ref"].calibration)
            self.assertEqual(
                by_name["wet"].selected_years,
                (2015, 2016, 2017, 2019, 2024),
            )
            self.assertEqual(
                by_name["dry"].selected_years,
                (2018, 2020, 2021, 2022, 2023),
            )
            self.assertEqual(
                by_name["dry"].calibration["start"],
                "2016-10-01 00:00:00",
            )
            self.assertEqual(
                by_name["dry"].calibration["end"],
                "2023-09-30 23:00:00",
            )

    def test_regime_scenario_uses_fewer_years_when_five_are_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "regimes.csv").write_text(
                "year,regime\n2019,Wet\n2020,Dry\n2021,Wet\n"
            )
            config = {
                "reference": {
                    "start": "2017-10-01",
                    "end": "2021-09-30 23:00:00",
                    "spinup": "12 months",
                    "year_type": "water_year",
                },
                "source": {
                    "file": "regimes.csv",
                    "year_column": "year",
                    "regime_column": "regime",
                },
                "selection": {
                    "max_years": 5,
                    "regimes": {"wet": "Wet", "dry": "Dry"},
                },
            }

            scenarios = launcher.resolve_regime_scenarios(
                config,
                "01109403",
                root,
            )
            by_name = {scenario.name: scenario for scenario in scenarios}
            self.assertEqual(by_name["wet"].selected_years, (2019, 2021))
            self.assertEqual(by_name["dry"].selected_years, (2020,))

    def test_regime_config_requires_per_gage_path_for_multiple_gages(self):
        config = {
            "reference": {
                "start": "2013-10-01",
                "end": "2024-09-30 23:00:00",
                "spinup": "12 months",
            },
            "source": {"file": "regimes.csv"},
            "selection": {"regimes": {"wet": "Wet", "dry": "Dry"}},
        }
        with self.assertRaisesRegex(ValueError, "must contain <gage_id>"):
            launcher.resolve_regime_scenarios(
                config,
                "01109403",
                Path("/tmp"),
                require_gage_placeholder=True,
            )

    def test_unconfigured_experiment_has_no_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            progress = launcher.get_experiment_progress(
                Path(tmp) / "metadata",
                "01109403",
            )

            self.assertFalse(progress.configured)
            self.assertFalse(progress.started)
            self.assertIsNone(progress.current_iteration)

    def test_configured_experiment_is_distinct_from_started_iteration_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_dir = root / "metadata"
            output_dir = root / "output"
            output_dir.mkdir()
            self._write_launcher_metadata(
                metadata_dir,
                "01109403",
                output_dir,
            )

            configured = launcher.get_experiment_progress(
                metadata_dir,
                "01109403",
                status=True,
            )
            self.assertTrue(configured.configured)
            self.assertFalse(configured.started)

            worker_dir = output_dir / "202607180225_ngen_test_worker"
            worker_dir.mkdir()
            (worker_dir / "best_params.txt").write_text("0\n0\n0.75\n")
            checkpoint = (
                worker_dir
                / "ngen_cal_nex-1_parameter_df_state.parquet"
            )
            checkpoint.touch()

            started = launcher.get_experiment_progress(
                metadata_dir,
                "01109403",
                status=True,
            )
            self.assertTrue(started.configured)
            self.assertTrue(started.started)
            self.assertEqual(started.current_iteration, 0)
            self.assertEqual(started.completed_iterations, 0)
            self.assertEqual(started.objective_value, 0.75)
            self.assertEqual(started.checkpoint_file, checkpoint)

    def test_iteration_zero_checkpoint_selects_restart_config(self):
        paths = {
            "sandbox_main": Path("/tmp/main.yaml"),
            "sandbox_restart": Path("/tmp/restart.yaml"),
            "sandbox_validation": Path("/tmp/validation.yaml"),
        }
        progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=0,
            objective_value=0.75,
            checkpoint_file=Path("/tmp/state_parameter_df_state.parquet"),
        )

        self.assertEqual(
            launcher.select_experiment_config(
                paths,
                progress,
                max_iter=100,
                stages=("calibration",),
            ),
            paths["sandbox_restart"],
        )

    def test_completed_calibration_only_experiment_has_no_next_config(self):
        paths = {
            "sandbox_main": Path("/tmp/main.yaml"),
            "sandbox_restart": Path("/tmp/restart.yaml"),
            "sandbox_validation": Path("/tmp/validation.yaml"),
        }
        progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=100,
            completed_iterations=100,
            checkpoint_file=Path("/tmp/state.parquet"),
        )

        self.assertIsNone(
            launcher.select_experiment_config(
                paths,
                progress,
                max_iter=100,
                stages=("calibration",),
            )
        )

    def test_validation_only_requires_completed_calibration(self):
        paths = {
            "sandbox_main": Path("/tmp/main.yaml"),
            "sandbox_restart": Path("/tmp/restart.yaml"),
            "sandbox_validation": Path("/tmp/validation.yaml"),
        }
        progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=25,
            completed_iterations=25,
            checkpoint_file=Path("/tmp/state.parquet"),
        )

        with self.assertRaisesRegex(RuntimeError, "calibration is incomplete"):
            launcher.select_experiment_config(
                paths,
                progress,
                max_iter=100,
                stages=("validation",),
            )

    def test_started_experiment_without_checkpoint_is_rejected(self):
        paths = {
            "sandbox_main": Path("/tmp/main.yaml"),
            "sandbox_restart": Path("/tmp/restart.yaml"),
            "sandbox_validation": Path("/tmp/validation.yaml"),
        }
        progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=0,
            objective_value=0.75,
        )

        with self.assertRaisesRegex(RuntimeError, "has no.*checkpoint"):
            launcher.select_experiment_config(
                paths,
                progress,
                max_iter=100,
                stages=("calibration",),
            )

    def test_pso_progress_uses_global_best_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_dir = root / "metadata"
            output_dir = root / "output"
            output_dir.mkdir()
            sandbox_config = root / "sandbox_config.yaml"
            sandbox_config.write_text(
                yaml.safe_dump(
                    {
                        "calibration": {
                            "optimizer": {
                                "algorithm": "pso",
                            }
                        }
                    }
                )
            )
            metadata_dir.mkdir()
            (metadata_dir / "run_01109403.yml").write_text(
                yaml.safe_dump(
                    {
                        "output_dir": str(output_dir),
                        "sandbox_config": str(sandbox_config),
                    }
                )
            )

            particle_dir = output_dir / "202607180225_ngen_particle_worker"
            particle_dir.mkdir()
            (particle_dir / "best_params.txt").write_text("39\n39\n9.0\n")
            (particle_dir / "particle_parameter_df_state.parquet").touch()

            global_best_dir = output_dir / "pso_global_best"
            global_best_dir.mkdir()
            (global_best_dir / "best_params.txt").write_text("12\n12\n0.25\n")
            global_checkpoint = (
                global_best_dir
                / "global_parameter_df_state.parquet"
            )
            global_checkpoint.touch()
            (output_dir / "pso_progress.json").write_text(
                '{"completed_generations": 40}'
            )

            progress = launcher.get_experiment_progress(
                metadata_dir,
                "01109403",
                status=True,
            )

            self.assertEqual(progress.algorithm, "pso")
            self.assertEqual(progress.current_iteration, 12)
            self.assertEqual(progress.completed_iterations, 40)
            self.assertEqual(progress.objective_value, 0.25)
            self.assertEqual(progress.checkpoint_file, global_checkpoint)

            paths = {
                "sandbox_main": Path("/tmp/main.yaml"),
                "sandbox_restart": Path("/tmp/restart.yaml"),
                "sandbox_validation": Path("/tmp/validation.yaml"),
            }
            self.assertEqual(
                launcher.select_experiment_config(
                    paths,
                    progress,
                    max_iter=40,
                    stages=("calibration", "validation"),
                ),
                paths["sandbox_validation"],
            )

    def test_incomplete_pso_warm_starts_from_global_best(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = launcher.generated_config_paths(root / "configs", "01109403")
            paths["sandbox_main"].parent.mkdir(parents=True)

            source_settings = root / "pso.yaml"
            source_settings.write_text(
                yaml.safe_dump(
                    {
                        "particles": 8,
                        "initialization": {
                            "nearby_fraction": 0.25,
                            "noise_fraction": 0.1,
                        },
                    },
                    sort_keys=False,
                )
            )
            paths["sandbox_main"].write_text(
                yaml.safe_dump(
                    {
                        "calibration": {
                            "optimizer": {
                                "algorithm": "pso",
                                "iterations": 40,
                                "settings_file": str(source_settings),
                            }
                        },
                        "simulation": {
                            "task_type": "calibration",
                        },
                    },
                    sort_keys=False,
                )
            )

            checkpoint = (
                root
                / "output"
                / "pso_global_best"
                / "state_parameter_df_state.parquet"
            )
            checkpoint.parent.mkdir(parents=True)
            checkpoint.touch()
            (checkpoint.parent / "best_params.txt").write_text("9\n9\n0.25\n")
            progress = launcher.ExperimentProgress(
                configured=True,
                current_iteration=9,
                completed_iterations=10,
                objective_value=0.25,
                checkpoint_file=checkpoint,
                algorithm="pso",
            )

            selected = launcher.select_experiment_config(
                paths,
                progress,
                max_iter=40,
                stages=("calibration",),
            )

            self.assertEqual(selected, paths["sandbox_pso_warm_start"])
            warm_config = yaml.safe_load(selected.read_text())
            self.assertEqual(
                warm_config["simulation"]["task_type"],
                "calibration",
            )
            self.assertEqual(
                warm_config["calibration"]["optimizer"]["iterations"],
                40,
            )
            self.assertEqual(
                warm_config["calibration"]["optimizer"]["settings_file"],
                str(paths["pso_warm_start_settings"].resolve()),
            )
            warm_settings = yaml.safe_load(
                paths["pso_warm_start_settings"].read_text()
            )
            self.assertEqual(
                warm_settings["initialization"]["best_path"],
                str(checkpoint.resolve()),
            )
            self.assertNotIn(
                "best_path",
                yaml.safe_load(source_settings.read_text())["initialization"],
            )

    def test_local_worker_runs_calibration_then_validation(self):
        main_config = Path("/tmp/sandbox_main.yaml")
        validation_config = Path("/tmp/sandbox_validation.yaml")
        initial_progress = launcher.ExperimentProgress(configured=True)
        completed_progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=10,
            completed_iterations=10,
            objective_value=0.25,
            checkpoint_file=Path("/tmp/state.parquet"),
        )
        args = (
            object(),
            "pet_cfe",
            "01109403",
            "pet_cfe_01109403",
            Path("/tmp/configs"),
            Path("/tmp/metadata"),
            initial_progress,
            5,
            False,
        )

        with (
            patch.object(
                launcher,
                "generated_config_paths",
                return_value={
                    "sandbox_main": main_config,
                    "sandbox_validation": validation_config,
                },
            ),
            patch.object(
                launcher,
                "run_experiment",
                side_effect=[
                    launcher.ExperimentRun(main_config),
                    launcher.ExperimentRun(validation_config),
                ],
            ) as run,
            patch.object(
                launcher,
                "get_experiment_progress",
                return_value=completed_progress,
            ),
            patch.object(
                launcher,
                "check_validation_exists",
                return_value=True,
            ),
        ):
            launcher.local_worker(args)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[7], 5)
        self.assertEqual(run.call_args_list[1].args[6], completed_progress)
        self.assertEqual(run.call_args_list[1].args[7], 0)

    def test_local_validation_generates_configs_before_run(self):
        validation_config = Path("/tmp/sandbox_validation.yaml")
        paths = {
            "sandbox_main": Path("/tmp/sandbox_main.yaml"),
            "sandbox_restart": Path("/tmp/sandbox_restart.yaml"),
            "sandbox_validation": validation_config,
        }
        progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=10,
            completed_iterations=10,
            checkpoint_file=Path("/tmp/state.parquet"),
        )

        with (
            patch.object(
                launcher,
                "check_validation_exists",
                return_value=False,
            ),
            patch.object(
                launcher,
                "generated_config_paths",
                return_value=paths,
            ),
            patch.object(launcher, "get_max_iter", return_value=10),
            patch.object(launcher.time, "sleep"),
            patch.object(launcher.subprocess, "run") as run,
        ):
            selected = launcher.run_experiment(
                SimpleNamespace(stages=("calibration", "validation")),
                "pet_cfe",
                "01109403",
                "pet_cfe_01109403",
                Path("/tmp/configs"),
                Path("/tmp/metadata"),
                progress,
                0,
                use_slurm=False,
            )

        self.assertEqual(selected.config_file, validation_config)
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["sandbox", "--conf", "-i", str(validation_config)],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["sandbox", "--run", "-i", str(validation_config)],
        )

    def test_slurm_run_returns_submitted_worker_job_id(self):
        main_config = Path("/tmp/sandbox_main.yaml")
        paths = {
            "sandbox_main": main_config,
            "sandbox_restart": Path("/tmp/sandbox_restart.yaml"),
            "sandbox_validation": Path("/tmp/sandbox_validation.yaml"),
        }
        context = SimpleNamespace(
            stages=("calibration",),
            slurm={
                "calibration": {"time": "24:00:00", "memory": "8G"},
            },
            log_dir=Path("/tmp/logs"),
            output_dir=Path("/tmp/outputs"),
            campaign_name="test",
        )

        with (
            patch.object(
                launcher,
                "generated_config_paths",
                return_value=paths,
            ),
            patch.object(launcher, "get_max_iter", return_value=10),
            patch.object(launcher, "get_num_cpus", return_value=4),
            patch.object(
                launcher.subprocess,
                "run",
                return_value=SimpleNamespace(stdout="456;anvil\n"),
            ),
            patch.object(launcher, "record_slurm_submission") as record,
        ):
            result = launcher.run_experiment(
                context,
                "pet_cfe",
                "01109403",
                "pet_cfe_01109403",
                Path("/tmp/configs"),
                Path("/tmp/metadata"),
                launcher.ExperimentProgress(configured=True),
                0,
                use_slurm=True,
            )

        self.assertEqual(result.config_file, main_config)
        self.assertEqual(result.slurm_job_id, "456")
        record.assert_called_once_with(
            context,
            job_id="456",
            job_name="pet_cfe_01109403",
            stage="calibration",
        )

    def test_local_worker_rejects_missing_validation_output(self):
        validation_config = Path("/tmp/sandbox_validation.yaml")
        progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=10,
            completed_iterations=10,
            checkpoint_file=Path("/tmp/state.parquet"),
        )
        args = (
            object(),
            "pet_cfe",
            "01109403",
            "pet_cfe_01109403",
            Path("/tmp/configs"),
            Path("/tmp/metadata"),
            progress,
            0,
            False,
        )

        with (
            patch.object(
                launcher,
                "generated_config_paths",
                return_value={"sandbox_validation": validation_config},
            ),
            patch.object(
                launcher,
                "run_experiment",
                return_value=launcher.ExperimentRun(validation_config),
            ),
            patch.object(
                launcher,
                "check_validation_exists",
                return_value=False,
            ),
            self.assertRaisesRegex(RuntimeError, "no sim_obs_validation"),
        ):
            launcher.local_worker(args)

    def test_local_worker_rejects_stalled_calibration(self):
        restart_config = Path("/tmp/sandbox_restart.yaml")
        progress = launcher.ExperimentProgress(
            configured=True,
            current_iteration=5,
            completed_iterations=5,
            objective_value=0.5,
            checkpoint_file=Path("/tmp/state.parquet"),
        )
        args = (
            object(),
            "pet_cfe",
            "01109403",
            "pet_cfe_01109403",
            Path("/tmp/configs"),
            Path("/tmp/metadata"),
            progress,
            0,
            False,
        )

        with (
            patch.object(
                launcher,
                "generated_config_paths",
                return_value={
                    "sandbox_validation": Path("/tmp/validation.yaml"),
                },
            ),
            patch.object(
                launcher,
                "run_experiment",
                return_value=launcher.ExperimentRun(restart_config),
            ),
            patch.object(
                launcher,
                "get_experiment_progress",
                return_value=progress,
            ),
            self.assertRaisesRegex(RuntimeError, "did not advance"),
        ):
            launcher.local_worker(args)


if __name__ == "__main__":
    unittest.main()
