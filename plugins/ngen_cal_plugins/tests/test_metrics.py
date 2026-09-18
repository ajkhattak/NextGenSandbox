from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

import pandas as pd

from ngen_cal_plugins.metrics import (
    ComputeMetrics,
    _coefficient_of_extrapolation,
)


class TestComputeMetricsConfiguration(unittest.TestCase):
    def test_uses_calibration_evaluation_range(self):
        calibration_range = ("calibration-start", "calibration-stop")
        config = SimpleNamespace(
            eval_params=SimpleNamespace(_eval_range=calibration_range),
            val_params=None,
        )

        plugin = ComputeMetrics()
        plugin.ngen_cal_model_configure(config)

        self.assertEqual(plugin.eval_range, calibration_range)

    def test_validation_range_takes_precedence(self):
        calibration_range = ("calibration-start", "calibration-stop")
        validation_range = ("validation-start", "validation-stop")
        config = SimpleNamespace(
            eval_params=SimpleNamespace(_eval_range=calibration_range),
            val_params=SimpleNamespace(
                evaluation_interval=lambda: validation_range,
            ),
        )

        plugin = ComputeMetrics()
        plugin.ngen_cal_model_configure(config)

        self.assertEqual(plugin.eval_range, validation_range)

    def test_supports_missing_evaluation_parameters(self):
        plugin = ComputeMetrics()
        plugin.ngen_cal_model_configure(SimpleNamespace())

        self.assertIsNone(plugin.eval_range)

    def test_validation_metrics_exclude_spinup_values(self):
        times = pd.date_range("2020-01-01", periods=5, freq="D")
        plugin = ComputeMetrics()
        plugin.ngen_cal_model_configure(
            SimpleNamespace(
                eval_params=SimpleNamespace(_eval_range=None),
                val_params=SimpleNamespace(
                    evaluation_interval=lambda: (times[1], times[-1]),
                ),
            )
        )
        plugin.obs = pd.Series(
            [100.0, 1.0, 2.0, 4.0, 3.0],
            index=times,
            name="obs_flow",
        )
        plugin.sim = pd.Series(
            [0.0, 1.0, 2.0, 4.0, 3.0],
            index=times,
            name="sim_flow",
        )
        plugin.update_metrics = Mock()

        plugin.ngen_cal_model_iteration_finish(
            iteration="validation",
            info=SimpleNamespace(),
        )

        metrics = plugin.update_metrics.call_args.args[1]
        self.assertEqual(metrics["mean_absolute_error"], 0.0)
        self.assertEqual(metrics["number_of_pairs"], 4.0)

    def test_mean_absolute_error(self):
        times = pd.date_range("2020-01-01", periods=2, freq="D")
        plugin = ComputeMetrics()
        plugin.obs = pd.Series([1.0, 3.0], index=times)
        plugin.sim = pd.Series([0.0, 4.0], index=times)
        plugin.update_metrics = Mock()

        plugin.ngen_cal_model_iteration_finish(
            iteration=0,
            info=SimpleNamespace(),
        )

        metrics = plugin.update_metrics.call_args.args[1]
        self.assertEqual(metrics["mean_absolute_error"], 1.0)

    def test_extrapolation_uses_only_prior_observations(self):
        observed = pd.Series([1.0, 2.0, 4.0, 7.0])
        perfect = observed.copy()
        linear_baseline = pd.Series([1.0, 2.0, 3.0, 6.0])

        self.assertEqual(
            _coefficient_of_extrapolation(observed, perfect),
            1.0,
        )
        self.assertEqual(
            _coefficient_of_extrapolation(observed, linear_baseline),
            0.0,
        )

    def test_existing_metrics_file_expands_for_new_metric_schema(self):
        plugin = ComputeMetrics()
        with TemporaryDirectory() as directory:
            workdir = Path(directory)
            pd.DataFrame({0: [1.0]}, index=["legacy_metric"]).to_parquet(
                workdir / "metrics.parquet"
            )

            plugin.update_metrics(
                SimpleNamespace(workdir=workdir),
                pd.Series({"new_metric": 2.0}),
                iteration=1,
            )

            stored = pd.read_parquet(workdir / "metrics.parquet")
            self.assertEqual(
                list(stored.index), ["legacy_metric", "new_metric"]
            )
            self.assertEqual(stored.loc["legacy_metric", 0], 1.0)
            self.assertEqual(stored.loc["new_metric", 1], 2.0)


if __name__ == "__main__":
    unittest.main()
