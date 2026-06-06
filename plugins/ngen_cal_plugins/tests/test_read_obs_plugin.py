from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

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
                    "name": "streamflow",
                    "layout": "point",
                    "path": str(path),
                    "time_column": "value_time",
                    "value_column": "value",
                    "units": units,
                }
            }
        )

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


if __name__ == "__main__":
    unittest.main()
