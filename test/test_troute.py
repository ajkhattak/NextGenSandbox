import unittest

import pandas as pd

from src.python.models.troute import TRouteConfigurationGenerator


class TestTRouteConfigurationGenerator(unittest.TestCase):
    def test_terminal_nexus_uses_explicit_gage_id(self):
        flowpaths = pd.DataFrame(
            {
                "gage": ["03366000", "02299950"],
                "gage_nex_id": ["nex-1", "nex-423186"],
            }
        )

        result = TRouteConfigurationGenerator._terminal_nexus_id(
            flowpaths,
            "02299950",
            "/tmp/usgs-gage_02299950-ngen.gpkg",
        )

        self.assertEqual(result, "nex-423186")

    def test_terminal_nexus_reports_missing_gage(self):
        flowpaths = pd.DataFrame(
            {
                "gage": ["03366000"],
                "gage_nex_id": ["nex-1"],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "No terminal nexus found for gage '02299950'",
        ):
            TRouteConfigurationGenerator._terminal_nexus_id(
                flowpaths,
                "02299950",
                "/tmp/custom.gpkg",
            )

    def test_terminal_nexus_rejects_ambiguous_matches(self):
        flowpaths = pd.DataFrame(
            {
                "gage": ["02299950", "02299950"],
                "gage_nex_id": ["nex-1", "nex-2"],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "Multiple terminal nexuses found for gage '02299950'",
        ):
            TRouteConfigurationGenerator._terminal_nexus_id(
                flowpaths,
                "02299950",
                "/tmp/custom.gpkg",
            )


if __name__ == "__main__":
    unittest.main()
