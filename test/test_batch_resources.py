import tempfile
import unittest
from pathlib import Path

from tools.batch.run_sandbox_resources_parallel import (
    duplicate_gages,
    load_status,
    pending_gages,
    save_status,
    set_gage_status,
    subset_domain_warning,
)


class TestParallelResourceBatch(unittest.TestCase):
    def test_duplicate_gages_are_reported_once_in_sorted_order(self):
        self.assertEqual(
            duplicate_gages(
                ["03366500", "01109403", "03366500", "01109403", "02299950"]
            ),
            ["01109403", "03366500"],
        )

    def test_unique_gages_are_accepted(self):
        self.assertEqual(
            duplicate_gages(["01109403", "02299950", "03366500"]),
            [],
        )

    def test_large_local_subset_without_domain_warns(self):
        config = {
            "general": {"gages": {"option": "ids"}},
            "subsetting": {"hydrofabric": {"gpkg_path": "/data/conus.gpkg"}},
        }

        warning = subset_domain_warning(config, "subset", 170)

        self.assertIsNotNone(warning)
        self.assertIn("all 170 selected gages", warning)

    def test_configured_subset_domain_does_not_warn(self):
        config = {
            "general": {"domain": "conus", "gages": {"option": "ids"}},
            "subsetting": {"hydrofabric": {"gpkg_path": "/data/conus.gpkg"}},
        }

        self.assertIsNone(subset_domain_warning(config, "subset", 170))

    def test_forcing_batch_does_not_use_subset_domain_warning(self):
        config = {
            "general": {"gages": {"option": "ids"}},
            "subsetting": {"hydrofabric": {"gpkg_path": "/data/conus.gpkg"}},
        }

        self.assertIsNone(subset_domain_warning(config, "forc", 170))

    def test_resume_skips_only_successful_gages_for_selected_step(self):
        status = {"version": 1, "subset": {}, "forcing": {}}
        set_gage_status(status, "subset", "01109403", "success")
        set_gage_status(status, "subset", "02299950", "failed")
        set_gage_status(status, "forc", "02299950", "success")

        pending, completed = pending_gages(
            status,
            "subset",
            ["01109403", "02299950", "03366500"],
            resume=True,
        )

        self.assertEqual(completed, ["01109403"])
        self.assertEqual(pending, ["02299950", "03366500"])

    def test_status_file_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sandbox_status.json"
            status = load_status(path)
            set_gage_status(status, "forc", "01109403", "success")
            save_status(path, status)

            loaded = load_status(path)

        self.assertEqual(loaded["forcing"]["01109403"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
