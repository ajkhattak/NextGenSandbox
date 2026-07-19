import unittest

import numpy as np
import pandas as pd

from ngen_cal_plugins.objectives import (
    NONFINITE_METRIC_LOSS,
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


if __name__ == "__main__":
    unittest.main()
