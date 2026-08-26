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

    def test_discovery_recurses_into_directories_matched_by_quoted_glob(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = []
            for gage_id in ("08070500", "09112500"):
                directory = root / gage_id / "hydrofabric"
                directory.mkdir(parents=True)
                gpkg = directory / f"gage_{gage_id}.gpkg"
                write_divides(gpkg, [("cat-1", 1.0)])
                expected.append(gpkg.resolve())

            discovered = checker.discover_gpkg_files(
                [str(root / "*" / "hydrofabric")]
            )

        self.assertEqual(discovered, sorted(expected))

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

    def test_cleaned_hydrofabric_removes_flagged_divide_and_related_rows(self):
        import geopandas as gpd
        from shapely.geometry import LineString, Point, box

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "gage_08070500.gpkg"
            output = Path(tmp) / "cleaned" / source.name
            divides = gpd.GeoDataFrame(
                {
                    "divide_id": ["cat-in", "cat-out"],
                    "id": ["wb-in", "wb-out"],
                    "toid": ["nex-in", "nex-out"],
                    "areasqkm": [1.0, 1.0],
                    "tot_drainage_areasqkm": [1.0, 1.0],
                },
                geometry=[box(-80.0, 35.0, -79.99, 35.01), box(-79.97, 35.0, -79.96, 35.01)],
                crs="EPSG:4326",
            )
            flowpaths = gpd.GeoDataFrame(
                {
                    "id": ["wb-in", "wb-out"],
                    "toid": ["nex-shared", "nex-shared"],
                    "divide_id": ["cat-in", "cat-out"],
                    "areasqkm": [1.0, 1.0],
                    "tot_drainage_areasqkm": [1.0, 1.0],
                    "poi_id": ["", "77968"],
                },
                geometry=[
                    LineString([(-79.999, 35.001), (-79.991, 35.009)]),
                    LineString([(-79.969, 35.001), (-79.961, 35.009)]),
                ],
                crs="EPSG:4326",
            )
            nexus = gpd.GeoDataFrame(
                {"id": ["nex-shared"], "toid": [None], "poi_id": ["77968"]},
                geometry=[Point(-79.985, 35.009)],
                crs="EPSG:4326",
            )
            divides.to_file(source, layer="divides", driver="GPKG")
            flowpaths.to_file(source, layer="flowpaths", driver="GPKG")
            nexus.to_file(source, layer="nexus", driver="GPKG")
            with sqlite3.connect(source) as connection:
                pd.DataFrame(
                    {"divide_id": ["cat-in", "cat-out"], "value": [1.0, 2.0]}
                ).to_sql("divide-attributes", connection, index=False)
                pd.DataFrame(
                    {
                        "link": ["wb-in", "wb-out"],
                        "id": ["wb-in", "wb-out"],
                        "gage": ["", "08070500"],
                        "gage_nex_id": ["", "nex-shared"],
                    }
                ).to_sql("flowpath-attributes", connection, index=False)
                pd.DataFrame(
                    {
                        "id": ["wb-in", "wb-out"],
                        "toid": ["nex-shared", "nex-shared"],
                        "divide_id": ["cat-in", "cat-out"],
                        "hf_id": [123.0, 456.0],
                        "poi_id": ["77968", "77968"],
                        "tot_drainage_areasqkm": [1.0, 1.0],
                    }
                ).to_sql("network", connection, index=False)

            boundary = gpd.GeoDataFrame(
                geometry=[box(-80.005, 34.995, -79.985, 35.015)],
                crs="EPSG:4326",
            )
            divide_audit = checker.identify_divides_outside_boundary(
                source,
                boundary,
                outside_fraction_pct=50.0,
                minimum_outside_area_sqkm=0.01,
            ).set_index("divide_id")
            checker.write_cleaned_hydrofabric(
                source,
                output,
                divide_audit.index[divide_audit["delete"]],
                gage_id="08070500",
                nldi_comid=123,
            )

            with sqlite3.connect(output) as connection:
                remaining_divides = pd.read_sql_query(
                    "SELECT divide_id FROM divides", connection
                )["divide_id"].tolist()
                remaining_flowpaths = pd.read_sql_query(
                    "SELECT id, poi_id FROM flowpaths", connection
                ).set_index("id")
                remaining_attributes = pd.read_sql_query(
                    'SELECT divide_id FROM "divide-attributes"', connection
                )["divide_id"].tolist()
                remaining_network = pd.read_sql_query(
                    "SELECT id FROM network", connection
                )["id"].tolist()
                reassigned = pd.read_sql_query(
                    'SELECT id, gage, gage_nex_id FROM "flowpath-attributes"',
                    connection,
                ).set_index("id")

        self.assertFalse(divide_audit.loc["cat-in", "delete"])
        self.assertTrue(divide_audit.loc["cat-out", "delete"])
        self.assertEqual(remaining_divides, ["cat-in"])
        self.assertEqual(remaining_flowpaths.index.tolist(), ["wb-in"])
        self.assertEqual(remaining_flowpaths.loc["wb-in", "poi_id"], "77968")
        self.assertEqual(remaining_attributes, ["cat-in"])
        self.assertEqual(remaining_network, ["wb-in"])
        self.assertEqual(reassigned.loc["wb-in", "gage"], "08070500")
        self.assertEqual(reassigned.loc["wb-in", "gage_nex_id"], "nex-shared")

    def test_comparison_applies_three_way_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [
                Path(tmp) / f"gage_{gage_id}.gpkg"
                for gage_id in ("08070500", "09112500", "02146700", "02053500")
            ]
            for path, area in zip(paths, (102.0, 115.0, 142.5, 120.0)):
                write_divides(path, [("cat-1", area)])
            usgs = pd.DataFrame(
                {
                    "gage_id": ["08070500", "09112500", "02146700", "02053500"],
                    "station_name": ["Clean", "Offset", "Mismatch", "Topology"],
                    "usgs_area_sqmi": [
                        100.0 / checker.SQUARE_MILES_TO_SQUARE_KM
                    ] * 4,
                    "usgs_area_sqkm": [100.0] * 4,
                }
            )
            nldi = pd.DataFrame(
                {
                    "gage_id": ["08070500", "09112500", "02146700", "02053500"],
                    "nldi_area_sqkm": [102.0, 115.0, 142.5, 100.0],
                    "nldi_error": [""] * 4,
                }
            )

            with (
                patch.object(checker, "fetch_usgs_drainage_areas", return_value=usgs),
                patch.object(checker, "fetch_nldi_basin_areas", return_value=nldi),
            ):
                result = checker.compare_basin_areas(
                    paths,
                    threshold_pct=20.0,
                    clean_threshold_pct=10.0,
                    hf_nldi_threshold_pct=5.0,
                ).set_index("gage_id")

        self.assertEqual(result.loc["08070500", "status"], "CLEAN_PASS")
        self.assertEqual(
            result.loc["09112500", "status"],
            "ACCEPTABLE_OUTLET_OFFSET",
        )
        self.assertEqual(
            result.loc["02146700", "status"],
            "OBSERVATION_DOMAIN_MISMATCH",
        )
        self.assertEqual(
            result.loc["02053500", "status"],
            "SUBSETTER_OR_TOPOLOGY_FAILURE",
        )

    def test_visualization_cli_options(self):
        args = checker._parser().parse_args(
            [
                "gage_08070500.gpkg",
                "--figure-dir",
                "figures",
                "--figure-format",
                "pdf",
                "--clean-threshold-pct",
                "8",
                "--hf-nldi-threshold-pct",
                "3",
            ]
        )

        self.assertEqual(args.figure_dir, Path("figures"))
        self.assertEqual(args.figure_format, "pdf")
        self.assertEqual(args.clean_threshold_pct, 8.0)
        self.assertEqual(args.hf_nldi_threshold_pct, 3.0)

    def test_main_writes_only_passing_gage_ids_to_additional_csv(self):
        comparison = pd.DataFrame(
            {
                "gage_id": ["09112500", "08070500", "02053500"],
                "status": [
                    "OBSERVATION_DOMAIN_MISMATCH",
                    "CLEAN_PASS",
                    "ACCEPTABLE_OUTLET_OFFSET",
                ],
                "hydrofabric_area_sqkm": [130.0, 100.0, 100.0],
                "nldi_area_sqkm": [130.0, 100.0, 115.0],
                "usgs_area_sqkm": [100.0, 100.0, 100.0],
                "hf_nldi_difference_pct": [0.0, 0.0, -13.0],
                "nldi_nwis_difference_pct": [30.0, 0.0, 15.0],
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
        self.assertEqual(
            passed.to_dict("records"),
            [{"gage_id": "02053500"}, {"gage_id": "08070500"}],
        )

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
                    "nldi_area_sqkm": 1.02,
                    "usgs_area_sqkm": 1.1,
                    "difference_pct": -9.0909,
                    "hf_nldi_difference_pct": -1.9608,
                    "nldi_nwis_difference_pct": -7.2727,
                    "threshold_pct": 10.0,
                    "clean_threshold_pct": 5.0,
                    "hf_nldi_threshold_pct": 3.0,
                    "status": "ACCEPTABLE_OUTLET_OFFSET",
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
                    "status": ["CLEAN_PASS", "OBSERVATION_DOMAIN_MISMATCH"],
                    "threshold_pct": [20.0, 20.0],
                    "clean_threshold_pct": [10.0, 10.0],
                    "hf_nldi_threshold_pct": [5.0, 5.0],
                    "gpkg_file": [str(pass_gpkg), str(fail_gpkg)],
                    "hydrofabric_area_sqkm": [100.0, 130.0],
                    "nldi_area_sqkm": [100.0, 130.0],
                    "usgs_area_sqkm": [100.0, 100.0],
                    "difference_pct": [0.0, 30.0],
                    "hf_nldi_difference_pct": [0.0, 0.0],
                    "nldi_nwis_difference_pct": [0.0, 30.0],
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
