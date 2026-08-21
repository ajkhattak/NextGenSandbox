import unittest

import numpy as np
import pandas as pd

from ngen_cal_plugins.objectives import (
    NONFINITE_METRIC_LOSS,
    composite_objective,
    configure_composite_objective,
    configure_objective_evaluation,
    kge_multi_variable,
)


class TestObjectives(unittest.TestCase):
    def test_kge_multi_variable_penalizes_constant_simulated_streamflow(self):
        index = pd.date_range("2011-10-01", periods=4, freq="h")
        observed = pd.Series([1.0, 2.0, 3.0, 4.0], index=index)
        simulated = pd.Series([0.0, 0.0, 0.0, 0.0], index=index)

        loss = kge_multi_variable(observed, simulated)

        self.assertTrue(np.isfinite(loss))
        self.assertEqual(loss, NONFINITE_METRIC_LOSS)

    def test_kge_uses_only_selected_water_years(self):
        index = pd.to_datetime(
            [
                "2010-10-01",
                "2011-09-30",
                "2011-10-01",
                "2012-09-30",
                "2013-10-01",
                "2014-09-30",
            ]
        )
        observed = pd.Series([1.0, 2.0, 10.0, 20.0, 3.0, 4.0], index=index)
        simulated = pd.Series(
            [1.0, 2.0, 1000.0, 2000.0, 3.0, 4.0],
            index=index,
        )

        configure_objective_evaluation(
            {"years": [2011, 2014], "year_type": "water_year"}
        )
        try:
            loss = kge_multi_variable(observed, simulated)
        finally:
            configure_objective_evaluation(None)

        self.assertAlmostEqual(loss, 0.0)

    def test_selected_years_require_aligned_values(self):
        index = pd.date_range("2011-10-01", periods=4, freq="h")
        observed = pd.Series([1.0, 2.0, 3.0, 4.0], index=index)
        simulated = observed.copy()

        configure_objective_evaluation(
            {"years": [2011], "year_type": "water_year"}
        )
        try:
            with self.assertRaisesRegex(ValueError, "selected water_year"):
                kge_multi_variable(observed, simulated)
        finally:
            configure_objective_evaluation(None)

    def test_selected_years_are_combined_before_objective_calculation(self):
        index = pd.to_datetime(
            [
                "2010-10-01", "2011-01-01", "2011-04-01", "2011-09-30",
                "2011-10-01", "2012-01-01", "2012-04-01", "2012-09-30",
            ]
        )
        observed = pd.Series([1.0, 2.0, 3.0, 4.0] * 2, index=index)
        simulated = observed.copy()
        simulated.loc[simulated.index >= "2011-10-01"] *= 2.0

        configure_composite_objective({"q10_skill": 1.0})
        configure_objective_evaluation(
            {"years": [2011, 2012], "year_type": "water_year"}
        )
        try:
            loss = composite_objective(observed, simulated)
        finally:
            configure_objective_evaluation(None)

        obs_q10 = np.quantile(observed, 0.9)
        sim_q10 = np.quantile(simulated, 0.9)
        self.assertAlmostEqual(loss, abs(sim_q10 - obs_q10) / obs_q10)

    def test_objective_evaluation_rejects_aggregation(self):
        with self.assertRaisesRegex(ValueError, "unsupported field.*aggregation"):
            configure_objective_evaluation(
                {
                    "years": [2011],
                    "year_type": "water_year",
                    "aggregation": "pooled",
                }
            )

    def test_q10_and_q90_skill_use_flow_exceedance_quantiles(self):
        index = pd.date_range("2011-10-01", periods=10, freq="h")
        observed = pd.Series(np.arange(1.0, 11.0), index=index)
        simulated = pd.Series(
            [1.0, 1.5, 2.5, 4.0, 5.0, 7.0, 8.0, 9.0, 12.0, 20.0],
            index=index,
        )

        for metric, exceedance in (
            ("q10_skill", 0.10),
            ("q90_skill", 0.90),
        ):
            with self.subTest(metric=metric):
                configure_composite_objective({metric: 1.0})
                loss = composite_objective(observed, simulated)
                obs_flow = np.quantile(observed, 1.0 - exceedance)
                sim_flow = np.quantile(simulated, 1.0 - exceedance)
                expected = abs(sim_flow - obs_flow) / obs_flow
                self.assertAlmostEqual(loss, expected)

    def test_compound_kge_q10_q90_uses_weighted_l2_loss(self):
        index = pd.date_range("2011-10-01", periods=10, freq="h")
        observed = pd.Series(np.arange(1.0, 11.0), index=index)
        simulated = observed * 2.0

        configure_composite_objective(
            {"kge": 0.4, "q10_skill": 0.3, "q90_skill": 0.3}
        )
        loss = composite_objective(observed, simulated)

        # Scaling by two gives KGE loss sqrt(2) and unit relative error at
        # both flow-exceedance points.
        self.assertAlmostEqual(loss, np.sqrt(0.5))


if __name__ == "__main__":
    unittest.main()
