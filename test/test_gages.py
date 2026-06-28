import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.python.gages import load_general_gages, resolve_step_gages


class TestGageSelection(unittest.TestCase):
    def test_general_gages_from_ids(self):
        config = {
            "general": {
                "gages": {
                    "option": "ids",
                    "ids": ["01308000", "03366500"],
                }
            }
        }

        self.assertEqual(load_general_gages(config), ["01308000", "03366500"])

    def test_general_gages_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gages.csv"
            pd.DataFrame({"gage_id": ["01308000", "03366500"]}).to_csv(
                path, index=False
            )
            config = {
                "general": {
                    "gages": {
                        "option": "file",
                        "file": {
                            "path": str(path),
                            "column": "gage_id",
                        },
                    }
                }
            }

            self.assertEqual(load_general_gages(config), ["01308000", "03366500"])

    def test_general_gages_from_gpkg_select(self):
        config = {
            "general": {
                "gages": {
                    "option": "gpkg",
                    "gpkg": {
                        "select": ["01308000", "03366500"],
                    },
                }
            }
        }

        self.assertEqual(load_general_gages(config), ["01308000", "03366500"])

    def test_step_gages_default_to_project_gages(self):
        self.assertEqual(
            resolve_step_gages(
                project_gages=["01308000", "03366500"],
                step_value=None,
                field_name="simulation.gages",
            ),
            ["01308000", "03366500"],
        )

    def test_step_gages_must_be_subset_of_project_gages(self):
        with self.assertRaisesRegex(ValueError, "outside general.gages"):
            resolve_step_gages(
                project_gages=["01308000"],
                step_value=["03366500"],
                field_name="simulation.gages",
            )

    def test_step_gages_reject_csv_when_project_gages_are_configured(self):
        with self.assertRaisesRegex(ValueError, "does not support CSV"):
            resolve_step_gages(
                project_gages=["01308000"],
                step_value="gages.csv",
                field_name="simulation.gages",
            )

    def test_general_gages_are_required(self):
        with self.assertRaisesRegex(ValueError, "general.gages"):
            load_general_gages({"general": {}})


if __name__ == "__main__":
    unittest.main()
