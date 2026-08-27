from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.python.configuration import ConfigurationCalib
from src.python.observations import ObservationLoader


class TestObservationLoader(unittest.TestCase):
    def test_rejects_unknown_output_retention(self):
        from src.python.context import SandboxContext

        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["12345678"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["control"],
                "gages": "12345678",
                "outputs": {
                    "calibration": {
                        "retention": "sometimes",
                    }
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "retention"):
            context.load_simulation_config()

    def test_divide_output_variables_require_units(self):
        from src.python.context import SandboxContext

        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["12345678"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["control"],
                "gages": "12345678",
                "outputs": {
                    "divide_variables": {
                        "ACTUAL_ET": {},
                    }
                },
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "simulation.outputs.divide_variables",
        ):
            context.load_simulation_config()

    def test_loads_output_variable_units(self):
        from src.python.context import SandboxContext

        context = SandboxContext.__new__(SandboxContext)
        context.formulation = ""
        context.project_gages = ["12345678"]
        context.sandbox_config = {
            "simulation": {
                "tasks": ["control"],
                "gages": "12345678",
                "simulation_time": {
                    "start_time": "2020-01-01 00:00:00",
                    "end_time": "2020-01-02 00:00:00",
                },
                "outputs": {
                    "divide_variables": {
                        "ACTUAL_ET": {
                            "units": "m/h",
                        },
                    },
                },
            }
        }

        context.load_simulation_config()

        self.assertEqual(
            context.divide_output_variables,
            {"ACTUAL_ET": {"units": "m/h"}},
        )

    def test_simulated_observation_requires_requested_output_variable(self):
        from src.python.context import SandboxContext

        context = SandboxContext.__new__(SandboxContext)
        context.observations = {
            "ET": {
                "simulated": "ACTUAL_ET",
            }
        }
        context.divide_output_variables = {}

        with self.assertRaisesRegex(
            ValueError,
            "simulation.outputs.divide_variables",
        ):
            context.validate_observations()

    def test_loads_multiple_observation_types(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            pd.DataFrame(
                {
                    "value_time": pd.date_range("2020-01-01", periods=2, freq="h"),
                    "value": [10.0, 11.0],
                }
            ).to_parquet(root / "gage_12345678_streamflow.parquet", index=False)

            pd.DataFrame(
                {
                    "value_time": pd.date_range("2020-01-01", periods=2, freq="h"),
                    "cat-1": [1.0, 2.0],
                    "cat-2": [3.0, 4.0],
                }
            ).to_parquet(root / "openet-gage_12345678-daily.parquet", index=False)

            observations = {
                "streamflow": {
                    "layout": "point",
                    "path": str(root / "gage_<gage_id>_streamflow.parquet"),
                    "time_column": "value_time",
                    "value_column": "value",
                    "units": "m3/sec",
                },
                "ET": {
                    "layout": "distributed",
                    "path": str(root / "*<gage_id>*daily.parquet"),
                    "time_column": "value_time",
                    "units": "mm/h",
                },
            }

            loader = ObservationLoader(observations, root)
            loaded = loader.load(["12345678"])

            self.assertEqual(
                loader.units,
                {"streamflow": "m3/sec", "ET": "mm/h"},
            )

            streamflow = loaded["streamflow"]["12345678"]
            self.assertIsInstance(streamflow, pd.Series)
            self.assertEqual(streamflow.name, "streamflow")
            self.assertEqual(streamflow.tolist(), [10.0, 11.0])

            et = loaded["ET"]["12345678"]
            self.assertIsInstance(et, pd.DataFrame)
            self.assertEqual(et.columns.tolist(), ["cat-1", "cat-2"])
            self.assertEqual(et.loc[pd.Timestamp("2020-01-01 01:00:00"), "cat-2"], 4.0)

    def test_loads_wide_distributed_csv_from_wildcard_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "openet-12345678-daily.csv"
            pd.DataFrame(
                {
                    "value_time": ["2020-01-01", "2020-01-02"],
                    "cat-1": [1.0, 2.0],
                    "cat-2": [3.0, 4.0],
                }
            ).to_csv(path, index=False)

            observations = {
                "ET": {
                    "layout": "distributed",
                    "path": str(root / "*<gage_id>*.csv"),
                    "time_column": "value_time",
                    "units": "mm/d",
                }
            }

            loaded = ObservationLoader(observations, root).load(["12345678"])

            self.assertEqual(
                loaded["ET"]["12345678"].loc[
                    pd.Timestamp("2020-01-02"), "cat-2"
                ],
                4.0,
            )

    def test_rejects_ambiguous_observation_wildcard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for prefix in ("first", "second"):
                pd.DataFrame(
                    {"value_time": ["2020-01-01"], "cat-1": [1.0]}
                ).to_csv(root / f"{prefix}-12345678.csv", index=False)

            observations = {
                "ET": {
                    "layout": "distributed",
                    "path": str(root / "*<gage_id>*.csv"),
                    "time_column": "value_time",
                    "units": "mm/d",
                }
            }

            with self.assertRaisesRegex(ValueError, "Multiple observation files"):
                ObservationLoader(observations, root).validate(["12345678"])

    def test_loads_long_distributed_observations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "gage_12345678_SWE.parquet"

            pd.DataFrame(
                {
                    "time": [
                        "2020-01-01 00:00:00",
                        "2020-01-01 00:00:00",
                        "2020-01-01 01:00:00",
                        "2020-01-01 01:00:00",
                    ],
                    "divide_id": ["cat-1", "cat-2", "cat-1", "cat-2"],
                    "swe": [1.0, 2.0, 3.0, 4.0],
                }
            ).to_parquet(path, index=False)

            observations = {
                "SWE": {
                    "layout": "distributed",
                    "path": str(path),
                    "time_column": "time",
                    "id_column": "divide_id",
                    "value_column": "swe",
                    "units": "mm",
                }
            }

            loaded = ObservationLoader(observations, root).load(["12345678"])
            swe = loaded["SWE"]["12345678"]

            self.assertEqual(swe.columns.tolist(), ["cat-1", "cat-2"])
            self.assertEqual(swe.loc[pd.Timestamp("2020-01-01 01:00:00"), "cat-2"], 4.0)

    def test_requires_units(self):
        observations = {
            "streamflow": {
                "layout": "point",
                "path": "streamflow.parquet",
                "time_column": "value_time",
                "value_column": "value",
            }
        }

        with self.assertRaisesRegex(ValueError, "observations.streamflow.units"):
            ObservationLoader(observations, ".").load(["12345678"])

    def test_rejects_non_cubic_meters_per_second_streamflow_units(self):
        observations = {
            "streamflow": {
                "layout": "point",
                "path": "streamflow.parquet",
                "time_column": "value_time",
                "value_column": "value",
                "units": "cfs",
            }
        }

        with self.assertRaisesRegex(ValueError, "'m3/s' or 'm3/sec'"):
            ObservationLoader(observations, ".").validate(["12345678"])

    def test_loads_point_observations_from_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "gage_12345678_streamflow.csv"
            pd.DataFrame(
                {
                    "value_time": ["2020-01-01 00:00:00", "2020-01-01 01:00:00"],
                    "value": [10.0, 11.0],
                }
            ).to_csv(path, index=False)

            observations = {
                "streamflow": {
                    "layout": "point",
                    "path": str(path),
                    "time_column": "value_time",
                    "value_column": "value",
                    "units": "m3/s",
                }
            }

            loaded = ObservationLoader(observations, root).load(["12345678"])
            self.assertEqual(
                loaded["streamflow"]["12345678"].tolist(),
                [10.0, 11.0],
            )

    def test_loads_lumped_observations_without_divide_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "ET_gage-12345678_daily_average.csv"
            pd.DataFrame(
                {
                    "Time": [
                        "2020-01-01 00:00:00+00:00",
                        "2020-01-02 00:00:00+00:00",
                    ],
                    "values": [1.5, 2.5],
                }
            ).to_csv(path, index=False)

            observations = {
                "ET": {
                    "layout": "lumped",
                    "path": str(root / "*<gage_id>*.csv"),
                    "time_column": "Time",
                    "value_column": "values",
                    "units": "mm/d",
                }
            }

            loaded = ObservationLoader(observations, root).load(["12345678"])

            self.assertEqual(loaded["ET"]["12345678"].tolist(), [1.5, 2.5])
            self.assertEqual(loaded["ET"]["12345678"].name, "ET")
            self.assertIsNone(loaded["ET"]["12345678"].index.tz)

    def test_validates_without_loading_observation_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "gage_12345678_streamflow.parquet"
            pd.DataFrame(
                {
                    "value_time": ["2020-01-01 00:00:00"],
                    "value": [10.0],
                }
            ).to_parquet(path, index=False)

            observations = {
                "streamflow": {
                    "layout": "point",
                    "path": str(path),
                    "time_column": "value_time",
                    "value_column": "value",
                    "units": "m3/sec",
                }
            }
            loader = ObservationLoader(observations, root)

            with patch("pandas.read_parquet") as read_parquet:
                validated = loader.validate(["12345678"])

            read_parquet.assert_not_called()
            settings = validated["streamflow"]["12345678"]
            self.assertEqual(settings["path"], path.resolve())
            self.assertEqual(settings["units"], "m3/sec")

    def test_adds_validated_observation_plugin_settings(self):
        generator = ConfigurationCalib.__new__(ConfigurationCalib)
        generator.ctx = SimpleNamespace(
            observation_files={
                "streamflow": {
                    "12345678": {
                        "path": Path("/absolute/streamflow.csv"),
                        "layout": "point",
                        "time_column": "value_time",
                        "value_column": "value",
                        "id_column": None,
                        "units": "m3/sec",
                    }
                },
                "ET": {
                    "12345678": {
                        "path": Path("/absolute/ET.parquet"),
                        "layout": "distributed",
                        "time_column": "value_time",
                        "value_column": None,
                        "id_column": None,
                        "units": "mm/d",
                        "simulated": "ACTUAL_ET",
                    }
                },
            },
            divide_output_variables={"ACTUAL_ET": {"units": "m/h"}},
        )
        model_config = {
            "eval_params": {
                "objective": "ngen_cal_plugins.objectives.multi_variable"
            },
            "plugins": ["existing.Plugin"],
        }

        generator.configure_observations(model_config, "12345678")

        self.assertEqual(
            model_config["plugins"],
            [
                "existing.Plugin",
                generator.OBSERVATION_PLUGIN,
            ],
        )
        settings = model_config["plugin_settings"]["read_obs_data"]
        self.assertEqual(
            settings["streamflow"]["path"],
            "/absolute/streamflow.csv",
        )
        self.assertEqual(settings["ET"]["path"], "/absolute/ET.parquet")
        self.assertEqual(settings["ET"]["simulated_units"], "m/h")

    def test_adds_multiple_observation_types_to_plugin_settings(self):
        generator = ConfigurationCalib.__new__(ConfigurationCalib)
        generator.ctx = SimpleNamespace(
            observation_files={
                "streamflow": {
                    "12345678": {
                        "path": Path("/absolute/streamflow.csv"),
                        "layout": "point",
                        "time_column": "value_time",
                        "value_column": "value",
                        "id_column": None,
                        "units": "m3/sec",
                    }
                },
                "ET": {
                    "12345678": {
                        "path": Path("/absolute/ET.parquet"),
                        "layout": "distributed",
                        "time_column": "value_time",
                        "value_column": None,
                        "id_column": None,
                        "units": "mm/d",
                    }
                },
            }
        )
        model_config = {
            "eval_params": {"objective": "kling_gupta"},
            "plugins": [],
        }

        generator.configure_observations(model_config, "12345678")

        settings = model_config["plugin_settings"]["read_obs_data"]
        self.assertEqual(set(settings), {"streamflow", "ET"})

    def test_adds_single_streamflow_observation(self):
        generator = ConfigurationCalib.__new__(ConfigurationCalib)
        generator.ctx = SimpleNamespace(
            observation_files={
                "streamflow": {
                    "12345678": {
                        "path": Path("/absolute/streamflow.csv"),
                        "layout": "point",
                        "time_column": "value_time",
                        "value_column": "value",
                        "id_column": None,
                        "units": "m3/sec",
                    }
                },
            }
        )
        model_config = {
            "eval_params": {"objective": "kling_gupta"},
            "plugins": [],
        }

        generator.configure_observations(model_config, "12345678")

        self.assertIn(generator.OBSERVATION_PLUGIN, model_config["plugins"])

    def test_uses_ngen_cal_streamflow_when_local_observations_are_absent(self):
        generator = ConfigurationCalib.__new__(ConfigurationCalib)
        generator.ctx = SimpleNamespace(observation_files={})
        model_config = {
            "plugins": [
                "existing.Plugin",
                generator.OBSERVATION_PLUGIN,
            ],
            "plugin_settings": {
                "existing": {"enabled": True},
                "read_obs_data": {"path": "/stale/streamflow.csv"},
            },
        }

        generator.configure_observations(model_config, "12345678")

        self.assertEqual(model_config["plugins"], ["existing.Plugin"])
        self.assertEqual(
            model_config["plugin_settings"],
            {"existing": {"enabled": True}},
        )


if __name__ == "__main__":
    unittest.main()
