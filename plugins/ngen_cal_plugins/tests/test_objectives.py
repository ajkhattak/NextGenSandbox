import unittest

import pandas as pd

from ngen_cal_plugins.objectives import (
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


if __name__ == "__main__":
    unittest.main()
