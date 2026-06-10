from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from ngen_cal_plugins.read_obs_plugin import ReadObservedData


class TestReadObservedData(unittest.TestCase):
    def create_observations(self, root):
        path = root / "streamflow.parquet"
        pd.DataFrame(
            {
                "value_time": pd.date_range("2020-01-01", periods=3, freq="h"),
                "value": [10.0, 20.0, 30.0],
            }
        ).to_parquet(path, index=False)
        return path

    def create_csv_observations(self, root):
        path = root / "streamflow.csv"
        pd.DataFrame(
            {
                "value_time": pd.date_range("2020-01-01", periods=2, freq="h"),
                "value": [10.0, 20.0],
            }
        ).to_csv(path, index=False)
        return path

    def create_config(self, path, units="m3/sec"):
        return SimpleNamespace(
            plugin_settings={
                "read_obs_data": {
                    "streamflow": {
                        "layout": "point",
                        "path": str(path),
                        "time_column": "value_time",
                        "value_column": "value",
                        "units": units,
                    }
                }
            },
            hydrofabric=None,
        )

    def create_hydrofabric(self, root):
        path = root / "gage.gpkg"
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE divides (divide_id TEXT, areasqkm REAL)"
            )
            connection.executemany(
                "INSERT INTO divides VALUES (?, ?)",
                [("cat-1", 1.0), ("cat-2", 3.0)],
            )
        return path

    def test_loads_proxy_after_ngen_cal_configures_plugin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.create_observations(Path(temp_dir))
            plugin = ReadObservedData()

            observations = plugin.ngen_cal_model_observations(
                nexus=SimpleNamespace(),
                start_time=pd.Timestamp("2020-01-01 01:00:00"),
                end_time=pd.Timestamp("2020-01-01 02:00:00"),
                simulation_interval=pd.Timedelta(hours=1),
            )
            self.assertTrue(observations.empty)

            plugin.ngen_cal_model_configure(self.create_config(path))

            self.assertEqual(observations.name, "obs_flow")
            self.assertEqual(observations.tolist(), [20.0, 30.0])

    def test_rejects_non_m3_per_sec_units(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.create_observations(Path(temp_dir))
            plugin = ReadObservedData()

            with self.assertRaisesRegex(ValueError, "'m3/s' or 'm3/sec'"):
                plugin.ngen_cal_model_configure(
                    self.create_config(path, units="cfs")
                )

    def test_accepts_m3_per_s_units(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.create_observations(Path(temp_dir))
            plugin = ReadObservedData()

            plugin.ngen_cal_model_configure(
                self.create_config(path, units="m3/s")
            )

    def test_requires_simulated_units_for_simulated_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.create_observations(Path(temp_dir))
            config = self.create_config(path)
            config.plugin_settings["read_obs_data"]["ET"] = {
                "layout": "distributed",
                "path": str(path),
                "time_column": "value_time",
                "units": "m/d",
                "simulated": "ACTUAL_ET",
            }

            with self.assertRaisesRegex(
                ValueError,
                "read_obs_data.ET.simulated_units",
            ):
                ReadObservedData().ngen_cal_model_configure(config)

    def test_requires_absolute_path(self):
        plugin = ReadObservedData()
        config = self.create_config(Path("streamflow.parquet"))

        with self.assertRaisesRegex(ValueError, "must be absolute"):
            plugin.ngen_cal_model_configure(config)

    def test_loads_csv_observations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.create_csv_observations(Path(temp_dir))
            plugin = ReadObservedData()

            observations = plugin.ngen_cal_model_observations(
                nexus=SimpleNamespace(),
                start_time=pd.Timestamp("2020-01-01 00:00:00"),
                end_time=pd.Timestamp("2020-01-01 01:00:00"),
                simulation_interval=pd.Timedelta(hours=1),
            )
            plugin.ngen_cal_model_configure(self.create_config(path))

            self.assertEqual(observations.tolist(), [10.0, 20.0])

    def test_combines_streamflow_and_area_weighted_et(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            streamflow_path = root / "streamflow.parquet"
            pd.DataFrame(
                {
                    "value_time": pd.date_range(
                        "2020-01-01",
                        periods=25,
                        freq="h",
                    ),
                    "value": range(25),
                }
            ).to_parquet(streamflow_path, index=False)
            et_path = root / "ET.parquet"
            pd.DataFrame(
                {
                    "value_time": pd.date_range(
                        "2020-01-01",
                        periods=2,
                        freq="D",
                    ),
                    "cat-1": [1.0, 2.0],
                    "cat-2": [3.0, 4.0],
                }
            ).to_parquet(et_path, index=False)
            config = self.create_config(streamflow_path)
            config.hydrofabric = self.create_hydrofabric(root)
            config.plugin_settings["read_obs_data"]["ET"] = {
                "layout": "distributed",
                "path": str(et_path),
                "time_column": "value_time",
                "units": "mm/d",
            }
            plugin = ReadObservedData()

            observations = plugin.ngen_cal_model_observations(
                nexus=SimpleNamespace(),
                start_time=pd.Timestamp("2020-01-01 00:00:00"),
                end_time=pd.Timestamp("2020-01-02 00:00:00"),
                simulation_interval=pd.Timedelta(hours=1),
            )
            plugin.ngen_cal_model_configure(config)

            self.assertEqual(
                observations.index.names,
                ["value_time", "variable"],
            )
            self.assertEqual(
                observations.xs("ET", level="variable").tolist(),
                [2.5, 3.5],
            )
            self.assertEqual(
                observations.loc[pd.Timestamp("2020-01-01 00:00:00")].index.tolist(),
                ["ET", "streamflow"],
            )
            self.assertEqual(
                observations.xs("streamflow", level="variable").index.min(),
                pd.Timestamp("2020-01-01 00:00:00"),
            )
            self.assertEqual(
                observations.xs("streamflow", level="variable").index.max(),
                pd.Timestamp("2020-01-02 00:00:00"),
            )

    def test_combined_observations_use_common_time_range(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            streamflow_path = root / "streamflow.csv"
            pd.DataFrame(
                {
                    "value_time": pd.date_range(
                        "2019-12-31",
                        periods=73,
                        freq="h",
                    ),
                    "value": range(73),
                }
            ).to_csv(streamflow_path, index=False)
            et_path = root / "ET.parquet"
            pd.DataFrame(
                {
                    "value_time": pd.date_range(
                        "2020-01-01",
                        periods=2,
                        freq="D",
                    ),
                    "cat-1": [1.0, 2.0],
                    "cat-2": [3.0, 4.0],
                }
            ).to_parquet(et_path, index=False)
            config = self.create_config(streamflow_path)
            config.hydrofabric = self.create_hydrofabric(root)
            config.plugin_settings["read_obs_data"]["ET"] = {
                "layout": "distributed",
                "path": str(et_path),
                "time_column": "value_time",
                "units": "mm/d",
            }
            plugin = ReadObservedData()

            observations = plugin.ngen_cal_model_observations(
                nexus=SimpleNamespace(),
                start_time=pd.Timestamp("2019-12-31 00:00:00"),
                end_time=pd.Timestamp("2020-01-03 00:00:00"),
                simulation_interval=pd.Timedelta(hours=1),
            )
            plugin.ngen_cal_model_configure(config)

            self.assertEqual(
                observations.index.get_level_values("value_time").min(),
                pd.Timestamp("2020-01-01 00:00:00"),
            )
            self.assertEqual(
                observations.index.get_level_values("value_time").max(),
                pd.Timestamp("2020-01-02 00:00:00"),
            )

    def test_combines_streamflow_with_simulated_distributed_variable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hydrofabric = self.create_hydrofabric(root)
            times = pd.date_range("2020-01-01", periods=24, freq="h")
            pd.DataFrame(
                {"Time": times, "ET": [0.001] * 24}
            ).to_csv(root / "cat-1.csv", index=False)
            pd.DataFrame(
                {"Time": times, "ET": [0.003] * 24}
            ).to_csv(root / "cat-2.csv", index=False)

            plugin = ReadObservedData()
            plugin.hydrofabric = hydrofabric
            plugin.observations = {
                "ET": pd.Series(
                    [1.0, 2.0],
                    index=pd.date_range("2020-01-01", periods=2, freq="D"),
                )
            }
            plugin.settings = {
                "streamflow": {},
                "ET": {
                    "simulated": "ET",
                    "simulated_units": "m/h",
                    "units": "mm/d",
                },
            }
            streamflow = pd.Series(
                [10.0, 11.0],
                index=times[:2],
                name="sim_flow",
            )

            with patch(
                "ngen_cal_plugins.read_obs_plugin.Path.cwd",
                return_value=root,
            ):
                wrapper = plugin.ngen_cal_model_output(SimpleNamespace())
                next(wrapper)
                with self.assertRaises(StopIteration) as result:
                    wrapper.send(streamflow)
            combined = result.exception.value

            self.assertAlmostEqual(
                combined.xs("ET", level="variable").iloc[0],
                60.0,
            )
            self.assertEqual(
                combined.xs("streamflow", level="variable").tolist(),
                [10.0, 11.0],
            )

    def test_averages_hourly_swe_to_daily_observation_frequency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hydrofabric = self.create_hydrofabric(root)
            times = pd.date_range("2020-01-01", periods=24, freq="h")
            pd.DataFrame(
                {"Time": times, "SWE": [0.001] * 24}
            ).to_csv(root / "cat-1.csv", index=False)
            pd.DataFrame(
                {"Time": times, "SWE": [0.003] * 24}
            ).to_csv(root / "cat-2.csv", index=False)

            plugin = ReadObservedData()
            plugin.hydrofabric = hydrofabric
            plugin.observations = {
                "SWE": pd.Series(
                    [1.0, 2.0],
                    index=pd.date_range("2020-01-01", periods=2, freq="D"),
                )
            }
            plugin.settings = {
                "SWE": {
                    "simulated": "SWE",
                    "simulated_units": "m",
                    "units": "mm",
                }
            }

            with patch(
                "ngen_cal_plugins.read_obs_plugin.Path.cwd",
                return_value=root,
            ):
                simulated = plugin._load_simulated_variable(
                    "SWE",
                    plugin.settings["SWE"],
                )

            self.assertAlmostEqual(simulated.iloc[0], 2.5)


if __name__ == "__main__":
    unittest.main()
