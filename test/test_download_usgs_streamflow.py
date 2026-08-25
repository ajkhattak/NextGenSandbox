import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load_downloader_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "utils/python/download_usgs_streamflow.py"
    )
    spec = importlib.util.spec_from_file_location(
        "download_usgs_streamflow",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


downloader = load_downloader_module()


class TestDownloadUsgsStreamflow(unittest.TestCase):
    def test_csv_gage_ids_preserve_leading_zeros_and_remove_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gages.csv"
            path.write_text(
                "gage_id,group_name\n"
                "01109403,humid\n"
                "08070500,dry\n"
                "01109403,benchmark\n"
            )

            self.assertEqual(
                downloader.get_gage_ids_from_csv(path),
                ["01109403", "08070500"],
            )

    def test_csv_requires_configured_id_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gages.csv"
            path.write_text("site_id\n01109403\n")

            with self.assertRaisesRegex(ValueError, "gage_id.*not found"):
                downloader.get_gage_ids_from_csv(path)

    def test_resolve_gage_ids_uses_direct_ids(self):
        args = argparse.Namespace(
            gages=["01109403", "08070500", "01109403"],
            gages_file=None,
            gpkg_pattern=None,
            id_column="gage_id",
        )

        self.assertEqual(
            downloader.resolve_gage_ids(args),
            ["01109403", "08070500"],
        )

    def test_driver_closes_http_service_after_downloads(self):
        class FakeService:
            def __init__(self, **settings):
                self.settings = settings
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.closed = True

        service = FakeService()
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch(
                    "download_usgs_streamflow.USGSIVDataService",
                    return_value=service,
                ) as service_factory,
                patch.object(
                    downloader,
                    "fetch_and_save_hourly_usgs_data",
                    return_value=True,
                ) as fetch,
            ):
                downloader.get_usgs_data_driver(
                    ["07335700"],
                    tmp,
                    "1998-10-01 00:00:00",
                    "2024-09-30 23:00:00",
                )

        service_factory.assert_called_once_with()
        fetch.assert_called_once()
        self.assertTrue(service.closed)

    def test_synchronous_service_parses_usgs_json(self):
        payload = {
            "value": {
                "timeSeries": [
                    {
                        "sourceInfo": {
                            "siteCode": [{"value": "07335700"}],
                        },
                        "variable": {"unit": {"unitCode": "ft3/s"}},
                        "values": [
                            {
                                "value": [
                                    {
                                        "dateTime": "2020-01-01T00:00:00Z",
                                        "value": "12.5",
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        }

        dataframe = downloader.USGSIVDataService._parse_response(payload)

        self.assertEqual(dataframe.loc[0, "usgs_site_code"], "07335700")
        self.assertEqual(dataframe.loc[0, "measurement_unit"], "ft3/s")
        self.assertEqual(dataframe.loc[0, "value"], 12.5)
        self.assertIsNone(dataframe.loc[0, "value_time"].tzinfo)


if __name__ == "__main__":
    unittest.main()
