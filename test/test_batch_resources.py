import unittest

from tools.batch.run_sandbox_resources_parallel import duplicate_gages


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


if __name__ == "__main__":
    unittest.main()
