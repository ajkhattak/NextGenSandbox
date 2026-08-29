import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.python.context import SandboxContext
from src.python.time_windows import normalize_forcing_time_config


class TestSimulationTimeWindows(unittest.TestCase):
    def test_rejects_retired_task_type_field(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["12345678"]
        context.sandbox_config = {
            "simulation": {
                "task_type": "control",
                "tasks": ["control"],
            }
        }

        with self.assertRaisesRegex(ValueError, "task_type is no longer supported"):
            context.load_simulation_config()

    def test_normalizes_forcing_time_schema(self):
        forcing_time = normalize_forcing_time_config(
            {
                "start": "2015-10-01",
                "end": "2022-09-30 23:00:00",
            }
        )

        self.assertEqual(
            forcing_time,
            {
                "start_time": "2015-10-01 00:00:00",
                "end_time": "2022-09-30 23:00:00",
            },
        )

    def test_forcing_time_rejects_legacy_keys(self):
        with self.assertRaisesRegex(ValueError, "start/end"):
            normalize_forcing_time_config(
                {
                    "start_time": "2015-10-01 00:00:00",
                    "end_time": "2022-09-30 23:00:00",
                }
            )

    def test_validate_formulation_sets_parsed_model_list(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = "PET,CFE"

        context.validate_formulation()

        self.assertEqual(context.formulation, "PET,CFE,T-ROUTE")
        self.assertEqual(context.formulation_models, ["PET", "CFE", "T-ROUTE"])

    def test_rejects_calibration_eval_time_outside_calibration_time(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "calibration_time": {
                    "start_time": "2010-01-01 00:00:00",
                    "end_time": "2010-09-30 23:00:00",
                },
                "calib_eval_time": {
                    "start_time": "2010-10-01 00:00:00",
                    "end_time": "2017-09-30 23:00:00",
                },
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "calib_eval_time must be within calibration_time",
        ):
            context.load_simulation_config()

    def test_accepts_calibration_eval_time_within_calibration_time(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "calibration_time": {
                    "start_time": "2010-01-01 00:00:00",
                    "end_time": "2017-09-30 23:00:00",
                },
                "calib_eval_time": {
                    "start_time": "2010-10-01 00:00:00",
                    "end_time": "2017-09-30 23:00:00",
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(context.calib_eval_time["start_time"], "2010-10-01 00:00:00")

    def test_rejects_reversed_time_window(self):
        with self.assertRaisesRegex(
            ValueError,
            "start_time must be less than or equal to",
        ):
            SandboxContext.validate_time_window(
                "calibration_time",
                {
                    "start_time": "2017-09-30 23:00:00",
                    "end_time": "2010-01-01 00:00:00",
                },
            )

    def test_rejects_validation_eval_time_outside_validation_time(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["validation"],
                "gages": "01109403",
                "validation_time": {
                    "start_time": "2018-01-01 00:00:00",
                    "end_time": "2018-09-30 23:00:00",
                },
                "valid_eval_time": {
                    "start_time": "2018-10-01 00:00:00",
                    "end_time": "2019-09-30 23:00:00",
                },
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "valid_eval_time must be within validation_time",
        ):
            context.load_simulation_config()

    def test_normalizes_calibration_time_schema(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2015-10-01 00:00:00",
                        "spinup": "12 months",
                        "evaluation": "4 years",
                    },
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(
            context.simulation_time,
            {
                "start_time": "2015-10-01 00:00:00",
                "end_time": "2020-09-30 23:00:00",
            },
        )
        self.assertEqual(
            context.calib_eval_time,
            {
                "start_time": "2016-10-01 00:00:00",
                "end_time": "2020-09-30 23:00:00",
            },
        )

    def test_time_schema_end_overrides_evaluation(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2015-10-01 00:00:00",
                        "spinup": "12 months",
                        "evaluation": "4 years",
                        "end": "2020-08-01 04:00:00",
                    },
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(context.simulation_time["end_time"], "2020-08-01 04:00:00")
        self.assertEqual(context.calib_eval_time["end_time"], "2020-08-01 04:00:00")

    def test_selects_noncontiguous_water_years_for_calibration_evaluation(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2009-10-01",
                        "spinup": "12 months",
                        "end": "2020-09-30 23:00:00",
                        "evaluation": {
                            "years": [2011, 2014, 2018, 2020],
                            "year_type": "water_year",
                        },
                    },
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(
            context.calib_eval_time,
            {
                "start_time": "2010-10-01 00:00:00",
                "end_time": "2020-09-30 23:00:00",
            },
        )
        self.assertEqual(
            context.calib_eval_selection,
            {
                "years": [2011, 2014, 2018, 2020],
                "year_type": "water_year",
            },
        )

    def test_rejects_selected_year_aggregation(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2009-10-01",
                        "spinup": "12 months",
                        "end": "2020-09-30 23:00:00",
                        "evaluation": {
                            "years": [2011],
                            "aggregation": "pooled",
                        },
                    },
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "unsupported field.*aggregation"):
            context.load_simulation_config()

    def test_selected_year_evaluation_requires_explicit_end(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2009-10-01",
                        "spinup": "12 months",
                        "evaluation": {
                            "years": [2011],
                            "year_type": "water_year",
                        },
                    },
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "end is required"):
            context.load_simulation_config()

    def test_rejects_selected_year_outside_post_spinup_interval(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2009-10-01",
                        "spinup": "12 months",
                        "end": "2020-09-30 23:00:00",
                        "evaluation": {
                            "years": [2010, 2011],
                            "year_type": "water_year",
                        },
                    },
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "outside years: 2010"):
            context.load_simulation_config()

    def test_date_only_timestamps_default_to_midnight(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2015-10-01",
                        "spinup": "12 months",
                        "end": "2020-09-30",
                    },
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(context.simulation_time["start_time"], "2015-10-01 00:00:00")
        self.assertEqual(context.simulation_time["end_time"], "2020-09-30 00:00:00")
        self.assertEqual(context.calib_eval_time["start_time"], "2016-10-01 00:00:00")

    def test_normalizes_combined_calibration_validation_time_schema(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration", "validation"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2015-10-01 00:00:00",
                        "spinup": "12 months",
                        "evaluation": "4 years",
                    },
                    "validations": [
                        {
                            "name": "validation",
                            "start": "2020-10-01 00:00:00",
                            "spinup": "12 months",
                            "evaluation": "1 year",
                        },
                    ],
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(
            context.simulation_tasks,
            ("calibration", "validation"),
        )
        self.assertEqual(context.task_type, "calibration")
        self.assertEqual(
            context.validation_time,
            {
                "start_time": "2020-10-01 00:00:00",
                "end_time": "2022-09-30 23:00:00",
            },
        )
        self.assertEqual(
            context.valid_eval_time,
            {
                "start_time": "2021-10-01 00:00:00",
                "end_time": "2022-09-30 23:00:00",
            },
        )

    def test_normalizes_multiple_validation_windows(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config_path = __file__
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration", "validation"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2015-10-01 00:00:00",
                        "spinup": "12 months",
                        "evaluation": "4 years",
                    },
                    "validations": [
                        {
                            "name": "wet",
                            "start": "2020-10-01 00:00:00",
                            "spinup": "12 months",
                            "evaluation": "1 year",
                        },
                        {
                            "name": "dry",
                            "start": "2010-10-01 00:00:00",
                            "spinup": "12 months",
                            "evaluation": "1 year",
                        },
                    ],
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(len(context.validation_periods), 2)
        self.assertEqual(context.validation_periods[0]["name"], "wet")
        self.assertEqual(context.validation_periods[1]["name"], "dry")
        self.assertEqual(
            context.validation_periods[0]["evaluation_time"]["start_time"],
            "2021-10-01 00:00:00",
        )

    def test_builds_validation_windows_from_water_year_file(self):
        with TemporaryDirectory() as tmp:
            csv_file = Path(tmp) / "year_tasks.csv"
            csv_file.write_text(
                "year,task_type\n"
                "2011,valid\n"
                "2012,calib\n"
                "2013,valid\n"
            )

            context = SandboxContext.__new__(SandboxContext)
            context.formulation = ""
            context.project_gages = ["01109403"]
            context.sandbox_config_path = str(Path(tmp) / "sandbox_config.yaml")
            context.sandbox_config = {
                "simulation": {
                    "tasks": ["validation"],
                    "gages": "01109403",
                    "time": {
                        "validations": [
                            {
                                "name": "water_year_split",
                                "source": "file",
                                "file": "year_tasks.csv",
                                "year_type": "water_year",
                                "task_column": "task_type",
                                "year_column": "year",
                                "select": "valid",
                                "spinup": "12 months",
                                "evaluation": "1 year",
                            },
                        ],
                    },
                }
            }

            context.load_simulation_config()

            self.assertEqual(
                [period["name"] for period in context.validation_periods],
                ["water_year_split_wy2011", "water_year_split_wy2013"],
            )
            self.assertEqual(
                context.validation_periods[0]["simulation_time"],
                {
                    "start_time": "2010-10-01 00:00:00",
                    "end_time": "2012-09-30 23:00:00",
                },
            )
            self.assertEqual(
                context.validation_periods[0]["evaluation_time"],
                {
                    "start_time": "2011-10-01 00:00:00",
                    "end_time": "2012-09-30 23:00:00",
                },
            )

    def test_time_schema_requires_yaml_dictionary(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": "2015-10-01",
            }
        }

        with self.assertRaisesRegex(TypeError, "YAML dictionary/object"):
            context.load_simulation_config()

    def test_time_schema_rejects_timestep_field(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "timestep": "1 hour",
                    "calibration": {
                        "start": "2015-10-01 00:00:00",
                        "spinup": "12 months",
                        "evaluation": "4 years",
                    },
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "timestep is not supported"):
            context.load_simulation_config()

    def test_rejects_invalid_duration_unit(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2015-10-01",
                        "spinup": "12 monthsss",
                        "evaluation": "4 years",
                    },
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "unsupported duration unit"):
            context.load_simulation_config()

    def test_accepts_unambiguous_duration_abbreviations(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2015-10-01",
                        "spinup": "365 d",
                        "evaluation": "4 y",
                    },
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(context.calib_eval_time["start_time"], "2016-09-30 00:00:00")
        self.assertEqual(context.calib_eval_time["end_time"], "2020-09-29 23:00:00")

    def test_rejects_month_abbreviations(self):
        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["01109403"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["calibration"],
                "gages": "01109403",
                "time": {
                    "calibration": {
                        "start": "2015-10-01",
                        "spinup": "12 mo",
                        "evaluation": "4 years",
                    },
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "unsupported duration unit"):
            context.load_simulation_config()


if __name__ == "__main__":
    unittest.main()
