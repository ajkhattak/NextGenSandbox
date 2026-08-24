import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
