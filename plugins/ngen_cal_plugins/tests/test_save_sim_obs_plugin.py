from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import pandas as pd

from ngen_cal_plugins.save_sim_obs_plugin import SaveData


class TestSaveData(unittest.TestCase):
    def test_all_retention_saves_every_iteration(self):
        times = pd.date_range("2020-01-01", periods=2, freq="h")
        plugin = SaveData()
        plugin.output_retention = "all"
        plugin.obs = pd.Series([10.0, 11.0], index=times, name="obs_flow")

        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            info = SimpleNamespace(workdir=workdir)

            for iteration in range(2):
                plugin.sim = pd.Series(
                    [iteration, iteration + 1],
                    index=times,
                    name="sim_flow",
                )
                plugin.ngen_cal_model_iteration_finish(
                    iteration=iteration,
                    info=info,
                )

            self.assertEqual(
                sorted(path.name for path in (workdir / "output_sim_obs").glob("*")),
                ["sim_obs_0.parquet", "sim_obs_1.parquet"],
            )

    def test_save_hooks_capture_final_wrapped_results(self):
        observation_options = SaveData.ngen_cal_model_observations.__dict__[
            "ngen.cal_impl"
        ]
        output_options = SaveData.ngen_cal_model_output.__dict__[
            "ngen.cal_impl"
        ]

        self.assertTrue(observation_options["wrapper"])
        self.assertTrue(observation_options["tryfirst"])
        self.assertTrue(output_options["wrapper"])
        self.assertTrue(output_options["tryfirst"])

    def test_does_not_assign_streamflow_simulation_to_other_variables(self):
        times = pd.date_range("2020-01-01", periods=2, freq="h")
        observations = pd.concat(
            {
                "ET": pd.Series([1.0], index=times[:1]),
                "streamflow": pd.Series([10.0, 11.0], index=times),
            },
            names=["variable"],
        ).swaplevel().sort_index()
        observations.index.names = ["value_time", "variable"]
        observations.name = "obs_flow"

        plugin = SaveData()
        plugin.sim = pd.Series([20.0, 21.0], index=times, name="sim_flow")
        plugin.obs = observations

        with tempfile.TemporaryDirectory() as temp_dir:
            plugin.ngen_cal_model_iteration_finish(
                iteration=0,
                info=SimpleNamespace(workdir=Path(temp_dir)),
            )
            saved = pd.read_parquet(
                Path(temp_dir) / "output_sim_obs" / "sim_obs_0.parquet"
            )

        self.assertEqual(saved.index.names, ["value_time", "variable"])
        et = saved.xs("ET", level="variable")
        streamflow = saved.xs("streamflow", level="variable")
        self.assertTrue(et["sim_flow"].isna().all())
        self.assertEqual(streamflow["sim_flow"].tolist(), [20.0, 21.0])

    def test_preserves_aligned_multivariable_values(self):
        times = pd.date_range("2020-01-01", periods=2, freq="h")
        index = pd.MultiIndex.from_product(
            [times, ["ET", "streamflow"]],
            names=["value_time", "variable"],
        )

        plugin = SaveData()
        plugin.sim = pd.Series(range(4), index=index, name="sim_flow")
        plugin.obs = pd.Series(range(10, 14), index=index, name="obs_flow")

        with tempfile.TemporaryDirectory() as temp_dir:
            plugin.ngen_cal_model_iteration_finish(
                iteration=0,
                info=SimpleNamespace(workdir=Path(temp_dir)),
            )
            saved = pd.read_parquet(
                Path(temp_dir) / "output_sim_obs" / "sim_obs_0.parquet"
            )

        self.assertEqual(saved.index.names, ["value_time", "variable"])
        self.assertEqual(saved.columns.tolist(), ["sim_flow", "obs_flow"])
        self.assertFalse(saved.isna().any().any())

    def test_saves_first_iteration_and_overwrites_best_iteration(self):
        times = pd.date_range("2020-01-01", periods=2, freq="h")
        plugin = SaveData()
        plugin.obs = pd.Series([10.0, 11.0], index=times, name="obs_flow")

        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            info = SimpleNamespace(workdir=workdir)

            plugin.sim = pd.Series([1.0, 2.0], index=times, name="sim_flow")
            (workdir / "best_params.txt").write_text("0\n0\n1.0\n")
            plugin.ngen_cal_model_iteration_finish(iteration=0, info=info)

            plugin.sim = pd.Series([3.0, 4.0], index=times, name="sim_flow")
            (workdir / "best_params.txt").write_text("1\n1\n0.5\n")
            plugin.ngen_cal_model_iteration_finish(iteration=1, info=info)

            plugin.sim = pd.Series([5.0, 6.0], index=times, name="sim_flow")
            (workdir / "best_params.txt").write_text("2\n1\n0.5\n")
            plugin.ngen_cal_model_iteration_finish(iteration=2, info=info)

            out_dir = workdir / "output_sim_obs"
            first = pd.read_parquet(out_dir / "sim_obs_0.parquet")
            best = pd.read_parquet(out_dir / "sim_obs_best.parquet")

            self.assertEqual(
                sorted(path.name for path in out_dir.glob("*.parquet")),
                ["sim_obs_0.parquet", "sim_obs_best.parquet"],
            )

        self.assertEqual(first["sim_flow"].tolist(), [1.0, 2.0])
        self.assertEqual(best["sim_flow"].tolist(), [3.0, 4.0])


if __name__ == "__main__":
    unittest.main()
