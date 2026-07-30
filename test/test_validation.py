from datetime import datetime
import unittest

import pandas as pd

from src.python.validation import _evaluate_validation_objective


class TestValidationObjective(unittest.TestCase):
    def test_objective_excludes_spinup_period(self):
        index = pd.to_datetime(
            [
                "2020-01-01 00:00:00",
                "2020-01-02 00:00:00",
                "2020-01-03 00:00:00",
            ]
        )
        simulated = pd.Series([100.0, 1.0, 1.0], index=index, name="sim_flow")
        observed = pd.Series([100.0, 1.0, 1.0], index=index, name="obs_flow")

        score = _evaluate_validation_objective(
            simulated,
            observed,
            lambda obs, sim: float(obs.sum()),
            (
                datetime(2020, 1, 2),
                datetime(2020, 1, 3),
            ),
        )

        self.assertEqual(score, 2.0)


if __name__ == "__main__":
    unittest.main()
