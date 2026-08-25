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

    def test_visualization_cli_options(self):
        args = checker._parser().parse_args(
            [
                "gage_08070500.gpkg",
                "--figure-dir",
                "figures",
                "--figure-format",
                "pdf",
            ]
        )

        self.assertEqual(args.figure_dir, Path("figures"))
        self.assertEqual(args.figure_format, "pdf")

    def test_main_writes_only_passing_gage_ids_to_additional_csv(self):
        comparison = pd.DataFrame(
            {
                "gage_id": ["09112500", "08070500", "08070500"],
                "status": ["FAIL", "PASS", "PASS"],
                "hydrofabric_area_sqkm": [130.0, 100.0, 100.0],
                "usgs_area_sqkm": [100.0, 100.0, 100.0],
                "difference_pct": [30.0, 0.0, 0.0],
                "threshold_pct": [20.0, 20.0, 20.0],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.csv"
            with (
                patch.object(checker, "discover_gpkg_files", return_value=[Path("gage_08070500.gpkg")]),
                patch.object(checker, "compare_basin_areas", return_value=comparison),
            ):
                exit_code = checker.main(
                    ["ignored", "--output-csv", str(audit)]
                )

            passed = pd.read_csv(
                Path(tmp) / "passed_basin_ids.csv",
                dtype={"gage_id": str},
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(passed.to_dict("records"), [{"gage_id": "08070500"}])

    def test_boundary_plot_is_written_without_network(self):
        import geopandas as gpd
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = Path(tmp) / "gage_08070500.gpkg"
            output = Path(tmp) / "figures" / "basin_boundary_08070500.pdf"
            divides = gpd.GeoDataFrame(
                {"divide_id": ["cat-1"], "areasqkm": [1.0]},
                geometry=[box(-95.5, 30.2, -95.4, 30.3)],
                crs="EPSG:4326",
            )
            divides.to_file(gpkg, layer="divides", driver="GPKG")
            boundary = gpd.GeoDataFrame(
                {"name": ["USGS basin"]},
                geometry=[box(-95.51, 30.19, -95.39, 30.31)],
                crs="EPSG:4326",
            )
            row = pd.Series(
                {
                    "gage_id": "08070500",
                    "station_name": "Test station",
                    "gpkg_file": str(gpkg),
                    "hydrofabric_area_sqkm": 1.0,
                    "usgs_area_sqkm": 1.1,
                    "difference_pct": -9.0909,
                    "threshold_pct": 10.0,
                    "status": "PASS",
                }
            )

            saved = checker.plot_basin_boundary_comparison(
                row,
                output,
                usgs_boundary=boundary,
            )

            self.assertEqual(saved, output.resolve())
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 0)

    def test_consolidated_pdf_orders_failed_basin_first(self):
        import geopandas as gpd
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as tmp:
            pass_gpkg = Path(tmp) / "gage_08070500.gpkg"
            fail_gpkg = Path(tmp) / "gage_09112500.gpkg"
            for path, offset in ((pass_gpkg, 0.0), (fail_gpkg, 0.2)):
                divides = gpd.GeoDataFrame(
                    {"divide_id": ["cat-1"], "areasqkm": [1.0]},
                    geometry=[box(-95.5 + offset, 30.2, -95.4 + offset, 30.3)],
                    crs="EPSG:4326",
                )
                divides.to_file(path, layer="divides", driver="GPKG")
            boundary = gpd.GeoDataFrame(
                {"name": ["USGS basin"]},
                geometry=[box(-95.51, 30.19, -95.39, 30.31)],
                crs="EPSG:4326",
            )
            comparison = pd.DataFrame(
                {
                    "gage_id": ["08070500", "09112500"],
                    "station_name": ["Passing", "Failing"],
                    "status": ["PASS", "FAIL"],
                    "threshold_pct": [20.0, 20.0],
                    "gpkg_file": [str(pass_gpkg), str(fail_gpkg)],
                    "hydrofabric_area_sqkm": [100.0, 130.0],
                    "usgs_area_sqkm": [100.0, 100.0],
                    "difference_pct": [0.0, 30.0],
                    "processing_error": ["", ""],
                }
            )

            with patch.object(
                checker,
                "fetch_usgs_basin_boundary",
                return_value=boundary,
            ):
                rendered = checker.generate_boundary_figures(
                    comparison,
                    Path(tmp) / "figures",
                    figure_format="pdf",
                ).set_index("gage_id")

            report = Path(rendered.loc["08070500", "figure_file"])
            self.assertTrue(report.exists())
            self.assertGreater(report.stat().st_size, 0)
            self.assertEqual(
                report,
                Path(rendered.loc["09112500", "figure_file"]),
            )
            self.assertEqual(rendered.loc["09112500", "figure_page"], 1)
            self.assertEqual(rendered.loc["08070500", "figure_page"], 2)


if __name__ == "__main__":
    unittest.main()
