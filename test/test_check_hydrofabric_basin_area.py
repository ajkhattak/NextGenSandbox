import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


def load_checker_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "utils/python/check_hydrofabric_basin_area.py"
    )
    spec = importlib.util.spec_from_file_location(
        "check_hydrofabric_basin_area",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = load_checker_module()


def write_divides(path, rows):
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE divides (divide_id TEXT, areasqkm REAL)"
        )
        connection.executemany(
            "INSERT INTO divides VALUES (?, ?)",
            rows,
        )


class TestHydrofabricBasinArea(unittest.TestCase):
    def test_extract_gage_id_from_standard_and_fallback_names(self):
        self.assertEqual(
            checker.extract_gage_id("gage_08070500.gpkg"),
            "08070500",
        )
        self.assertEqual(
            checker.extract_gage_id("subset-for-09112500-final.gpkg"),
            "09112500",
        )

    def test_extract_gage_id_rejects_ambiguous_name(self):
        with self.assertRaisesRegex(ValueError, "multiple possible gage IDs"):
            checker.extract_gage_id("08070500_to_09112500.gpkg")

    def test_hydrofabric_area_sums_divides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gage_08070500.gpkg"
            write_divides(path, [("cat-1", 10.5), ("cat-2", 4.25)])

            area, count = checker.hydrofabric_area_sqkm(path)

        self.assertEqual(count, 2)
        self.assertAlmostEqual(area, 14.75)

    def test_duplicate_divides_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gage_08070500.gpkg"
            write_divides(path, [("cat-1", 10.0), ("cat-1", 4.0)])

            with self.assertRaisesRegex(ValueError, "duplicate divide_id"):
                checker.hydrofabric_area_sqkm(path)

    def test_comparison_applies_absolute_percent_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            passing = Path(tmp) / "gage_08070500.gpkg"
            failing = Path(tmp) / "gage_09112500.gpkg"
            write_divides(passing, [("cat-1", 110.0)])
            write_divides(failing, [("cat-2", 130.0)])
            usgs = pd.DataFrame(
                {
                    "gage_id": ["08070500", "09112500"],
                    "station_name": ["Passing site", "Failing site"],
                    "usgs_area_sqmi": [
                        100.0 / checker.SQUARE_MILES_TO_SQUARE_KM,
                        100.0 / checker.SQUARE_MILES_TO_SQUARE_KM,
                    ],
                    "usgs_area_sqkm": [100.0, 100.0],
                }
            )

            with patch.object(
                checker,
                "fetch_usgs_drainage_areas",
                return_value=usgs,
            ):
                result = checker.compare_basin_areas(
                    [passing, failing],
                    threshold_pct=20.0,
                ).set_index("gage_id")

        self.assertEqual(result.loc["08070500", "status"], "PASS")
        self.assertAlmostEqual(
            result.loc["08070500", "difference_pct"],
            10.0,
        )
        self.assertEqual(result.loc["09112500", "status"], "FAIL")
        self.assertAlmostEqual(
            result.loc["09112500", "difference_pct"],
            30.0,
        )


if __name__ == "__main__":
    unittest.main()
