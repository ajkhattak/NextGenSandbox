import unittest

import numpy as np
import pandas as pd

from ngen_cal_plugins.streamflow_metrics import (
    PEAK_METRIC_NAMES,
    StreamflowMetricSettings,
    compute_streamflow_diagnostics,
)


class TestStreamflowMetricSettings(unittest.TestCase):
    def test_rejects_unknown_setting(self):
        with self.assertRaisesRegex(ValueError, "unsupported field"):
            StreamflowMetricSettings.from_mapping({"unknown": 1})

    def test_rejects_invalid_peak_percentile(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            StreamflowMetricSettings.from_mapping({"peak_percentile": 101})


class TestStreamflowDiagnostics(unittest.TestCase):
    def test_perfect_simulation_has_expected_distribution_metrics(self):
        index = pd.date_range("2020-01-01", periods=8, freq="h")
        flow = pd.Series(
            [0.0, 0.0, 0.2, 1.0, 4.0, 1.0, 0.2, 0.0],
            index=index,
        )

        metrics = compute_streamflow_diagnostics(
            flow,
            flow.copy(),
            StreamflowMetricSettings(peak_metrics=False),
        )

        self.assertEqual(metrics["number_of_pairs"], 8.0)
        self.assertAlmostEqual(
            metrics["normalized_nash_sutcliffe_efficiency"], 1.0
        )
        self.assertAlmostEqual(metrics["kge_correlation"], 1.0)
        self.assertAlmostEqual(metrics["kge_variability_ratio"], 1.0)
        self.assertAlmostEqual(metrics["kge_mean_ratio"], 1.0)
        self.assertAlmostEqual(metrics["percent_bias"], 0.0)
        self.assertAlmostEqual(metrics["q10_relative_error_percent"], 0.0)
        self.assertAlmostEqual(metrics["q90_relative_error_percent"], 0.0)
        self.assertAlmostEqual(metrics["fdc_relative_rmse"], 0.0)
        self.assertAlmostEqual(metrics["nonzero_low_flow_log_mae"], 0.0)
        self.assertAlmostEqual(metrics["false_flow_percent"], 0.0)
        self.assertAlmostEqual(metrics["missed_flow_percent"], 0.0)
        for metric in PEAK_METRIC_NAMES:
            self.assertTrue(np.isnan(metrics[metric]))

    def test_peak_metrics_match_neuralhydrology_definitions(self):
        index = pd.date_range("2020-01-01", periods=420, freq="h")
        observed = pd.Series(0.0, index=index)
        simulated = pd.Series(0.0, index=index)
        observed.iloc[[120, 250, 370]] = [10.0, 20.0, 15.0]
        simulated.iloc[[123, 246, 370]] = [8.0, 24.0, 10.0]

        metrics = compute_streamflow_diagnostics(
            observed,
            simulated,
            StreamflowMetricSettings(),
        )

        self.assertAlmostEqual(metrics["mean_peak_timing"], 7.0 / 3.0)
        self.assertAlmostEqual(
            metrics["mean_absolute_percentage_peak_error"],
            77.77777777777779,
        )
        self.assertAlmostEqual(metrics["missed_peaks_percent"], 0.0)

    def test_missing_all_simulated_peaks_reports_one_hundred_percent(self):
        index = pd.date_range("2020-01-01", periods=420, freq="h")
        observed = pd.Series(0.0, index=index)
        simulated = pd.Series(0.0, index=index)
        observed.iloc[[120, 250, 370]] = [10.0, 20.0, 15.0]

        metrics = compute_streamflow_diagnostics(
            observed,
            simulated,
            StreamflowMetricSettings(),
        )

        self.assertAlmostEqual(metrics["missed_peaks_percent"], 100.0)

    def test_nonfinite_pairs_are_excluded(self):
        index = pd.date_range("2020-01-01", periods=5, freq="h")
        observed = pd.Series(
            [1.0, np.nan, 2.0, np.inf, 3.0],
            index=index,
        )
        simulated = pd.Series(
            [1.0, 2.0, np.nan, 4.0, 3.0],
            index=index,
        )

        metrics = compute_streamflow_diagnostics(
            observed,
            simulated,
            StreamflowMetricSettings(peak_metrics=False),
        )

        self.assertEqual(metrics["number_of_pairs"], 2.0)


if __name__ == "__main__":
    unittest.main()
