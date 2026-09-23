import unittest
from pathlib import Path

from src.python.context import SandboxContext


class TestContextOutputDirs(unittest.TestCase):
    def test_output_layout_includes_formulation(self):
        context = object.__new__(SandboxContext)
        context.formulation_name = "NOM CFE-S"
        context.project_output_dir = Path("/tmp/outputs")
        context.simulation_scenario = None

        context.apply_output_layout()

        self.assertEqual(context.output_dir, Path("/tmp/outputs/nom_cfe-s"))

    def test_output_layout_places_scenario_after_formulation(self):
        context = object.__new__(SandboxContext)
        context.formulation_name = "nom_cfe_s"
        context.project_output_dir = Path("/tmp/outputs")
        context.simulation_scenario = "dry"

        context.apply_output_layout()

        self.assertEqual(
            context.output_dir,
            Path("/tmp/outputs/nom_cfe_s/dry"),
        )

    def test_output_layout_rejects_unsafe_formulation_name(self):
        context = object.__new__(SandboxContext)
        context.formulation_name = ".."
        context.project_output_dir = Path("/tmp/outputs")
        context.simulation_scenario = None

        with self.assertRaisesRegex(ValueError, "usable output directory"):
            context.apply_output_layout()

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
