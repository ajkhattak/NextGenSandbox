import unittest

import numpy as np
import pandas as pd

from ngen_cal_plugins import objectives
from ngen_cal_plugins.objectives import (
    FDC_EXCEEDANCES,
    HIGH_FLOW_EXCEEDANCES,
    LOW_FLOW_EXCEEDANCES,
    NONZERO_LOW_FLOW_EXCEEDANCE,
    composite_objective,
    configure_composite_objective,
    kge_multi_variable,
    nnse_multi_variable,
    nse_multi_variable,
)


class TestKlingGuptaMultiVariable(unittest.TestCase):
    def create_series(self, streamflow, et):
        hourly = pd.date_range("2020-01-01", periods=len(streamflow), freq="h")
        daily = pd.date_range("2020-01-01", periods=len(et), freq="D")
        combined = pd.concat(
            {
                "streamflow": pd.Series(streamflow, index=hourly),
                "ET": pd.Series(et, index=daily),
            },
            names=["variable"],
        ).swaplevel().sort_index()
        combined.index.names = ["value_time", "variable"]
        return combined

    def test_perfect_variables_have_zero_loss(self):
        observed = self.create_series(
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0],
        )

        score = kge_multi_variable(observed, observed.copy())

        self.assertAlmostEqual(score, 0.0)

    def test_requires_matching_simulated_variables(self):
        observed = self.create_series(
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0],
        )
        simulated = observed.xs("streamflow", level="variable")

        with self.assertRaisesRegex(ValueError, "do not match"):
            kge_multi_variable(observed, simulated)

    def test_aligns_each_variable_independently(self):
        observed = self.create_series(
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0],
        )
        simulated = observed.copy()
        simulated = simulated.drop(
            (pd.Timestamp("2020-01-01 01:00:00"), "streamflow")
        )

        score = kge_multi_variable(observed, simulated)

        self.assertAlmostEqual(score, 0.0)

    def test_nse_perfect_variables_have_zero_loss(self):
        observed = self.create_series(
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0],
        )

        score = nse_multi_variable(observed, observed.copy())

        self.assertAlmostEqual(score, 0.0)

    def test_nnse_perfect_variables_have_zero_loss(self):
        observed = self.create_series(
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0],
        )

        score = nnse_multi_variable(observed, observed.copy())

        self.assertAlmostEqual(score, 0.0)

    def test_supports_single_variable_series(self):
        observed = pd.Series(
            [1.0, 2.0, 3.0, 4.0],
            index=pd.date_range("2020-01-01", periods=4, freq="h"),
        )

        score = kge_multi_variable(observed, observed.copy())

        self.assertAlmostEqual(score, 0.0)

    def test_composite_objective_perfect_streamflow_has_zero_loss(self):
        observed = pd.Series(
            [0.02, 0.03, 0.05, 0.2, 1.0, 3.0],
            index=pd.date_range("2020-01-01", periods=6, freq="h"),
        )
        configure_composite_objective(
            {"kge": 0.5, "log_kge": 0.3, "fdc": 0.2}
        )

        score = composite_objective(observed, observed.copy())

        self.assertAlmostEqual(score, 0.0)

    def test_et_only_series_is_not_treated_as_streamflow(self):
        times = pd.date_range("2020-01-01", periods=6, freq="D")
        et = pd.concat(
            {"ET": pd.Series([1.0, 2.0, 3.0, 2.0, 1.5, 1.0], index=times)},
            names=["variable"],
        ).swaplevel().sort_index()
        et.index.names = ["value_time", "variable"]
        configure_composite_objective({"fdc": 1.0})

        with self.assertRaisesRegex(ValueError, "require streamflow"):
            composite_objective(et, et.copy())

    def test_composite_fdc_uses_low_and_high_flow_exceedances(self):
        self.assertEqual(
            FDC_EXCEEDANCES,
            HIGH_FLOW_EXCEEDANCES + LOW_FLOW_EXCEEDANCES,
        )

    def test_composite_fdc_penalizes_changed_flow_distribution(self):
        observed = pd.Series(
            [0.02, 0.03, 0.05, 0.2, 1.0, 3.0],
            index=pd.date_range("2020-01-01", periods=6, freq="h"),
        )
        simulated = pd.Series(
            [1.0e-12, 1.0e-12, 0.05, 0.2, 0.6, 0.8],
            index=observed.index,
        )
        configure_composite_objective({"fdc": 1.0})

        score = composite_objective(observed, simulated)

        self.assertGreater(score, 0.1)

    def test_nonzero_low_flow_log_mae_ignores_zeros_and_high_flows(self):
        observed = pd.Series(
            [0.0, 0.02, 0.03, 0.05, 0.2, 1.0, 3.0],
            index=pd.date_range("2020-01-01", periods=7, freq="h"),
        )
        simulated = pd.Series(
            [5.0, 0.02, 0.03, 0.05, 5.0, 10.0, 30.0],
            index=observed.index,
        )
        configure_composite_objective({"nonzero_low_flow_log_mae": 1.0})

        score = composite_objective(observed, simulated)

        self.assertAlmostEqual(score, 0.0)

    def test_nonzero_low_flow_log_mae_penalizes_magnitude_error(self):
        observed = pd.Series(
            [0.0, 0.02, 0.03, 0.05, 0.2, 1.0, 3.0],
            index=pd.date_range("2020-01-01", periods=7, freq="h"),
        )
        simulated = pd.Series(
            [0.0, 0.2, 0.03, 0.5, 0.2, 1.0, 3.0],
            index=observed.index,
        )
        configure_composite_objective({"nonzero_low_flow_log_mae": 1.0})

        score = composite_objective(observed, simulated)

        low_flow_threshold = observed[observed > 1.0e-6].quantile(
            1.0 - NONZERO_LOW_FLOW_EXCEEDANCE
        )
        low_flow_mask = (
            (observed > 1.0e-6)
            & (observed <= low_flow_threshold)
        )
        expected = (
            np.log10(simulated[low_flow_mask])
            - np.log10(observed[low_flow_mask])
        ).abs().mean()
        self.assertAlmostEqual(score, expected)
        self.assertGreater(score, 0.0)

    def test_composite_recipe_is_available_to_fresh_worker_module(self):
        observed = pd.Series(
            [0.02, 0.03, 0.05, 0.2, 1.0, 3.0],
            index=pd.date_range("2020-01-01", periods=6, freq="h"),
        )
        configure_composite_objective({"kge": 1.0})
        objectives._composite_metric_weights = None

        score = composite_objective(observed, observed.copy())

        self.assertAlmostEqual(score, 0.0)

    def test_composite_weights_must_sum_to_one(self):
        with self.assertRaisesRegex(ValueError, "must sum to 1.0"):
            configure_composite_objective({"kge": 0.5, "fdc": 0.4})

    def test_composite_objective_skips_flow_metrics_for_et(self):
        observed = self.create_series(
            [0.02, 0.03, 0.05, 0.2, 1.0, 3.0],
            [2.0, 3.0, 4.0],
        )
        simulated = observed.copy()
        simulated.loc[
            simulated.index.get_level_values("variable") == "ET"
        ] *= 0.5
        configure_composite_objective(
            {"kge": 0.5, "log_kge": 0.3, "fdc": 0.2}
        )

        score = composite_objective(observed, simulated)

        self.assertGreater(score, 0.0)


if __name__ == "__main__":
    unittest.main()
