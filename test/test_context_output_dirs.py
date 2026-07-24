import unittest
from pathlib import Path

from src.python.context import SandboxContext


class TestContextOutputDirs(unittest.TestCase):
    def test_simulation_label_is_appended_to_gage_id(self):
        context = object.__new__(SandboxContext)
        context.simulation_label = "pet_cfe"

        self.assertEqual(
            context.output_dir_name(Path("/tmp/resources/01308000")),
            "01308000_pet_cfe",
        )

    def test_output_name_uses_only_gage_id_without_label(self):
        context = object.__new__(SandboxContext)
        context.simulation_label = None

        self.assertEqual(
            context.output_dir_name(Path("/tmp/resources/01308000")),
            "01308000",
        )


if __name__ == "__main__":
    unittest.main()
