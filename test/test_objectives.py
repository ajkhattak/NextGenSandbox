import unittest

import numpy as np
import pandas as pd

from ngen_cal_plugins.objectives import (
    NONFINITE_METRIC_LOSS,
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


if __name__ == "__main__":
    unittest.main()
