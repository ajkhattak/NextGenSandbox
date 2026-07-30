import tempfile
import unittest
from pathlib import Path

from src.python.forcing import ForcingProcessor


class TestForcingSelection(unittest.TestCase):
    @staticmethod
    def _processor(input_dir: Path, layout: str, selected_gages: list[str]):
        processor = object.__new__(ForcingProcessor)
        processor.input_dir = input_dir
        processor.resource_layout = layout
        processor.selected_gages = selected_gages
        return processor

    @staticmethod
    def _add_gpkg(input_dir: Path, layout: str, gage_id: str) -> Path:
        if layout == "resource":
            gpkg = input_dir / "hydrofabric" / f"gage_{gage_id}.gpkg"
            gpkg.parent.mkdir(parents=True, exist_ok=True)
            gpkg.touch()
            return gpkg

        basin_dir = input_dir / gage_id
        gpkg = basin_dir / "hydrofabric" / f"gage_{gage_id}.gpkg"
        gpkg.parent.mkdir(parents=True, exist_ok=True)
        gpkg.touch()
        return basin_dir

    def test_rejects_partial_gage_matches(self):
        for layout in ("gage", "resource"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as tmp:
                input_dir = Path(tmp)
                self._add_gpkg(input_dir, layout, "01109403")
                self._add_gpkg(input_dir, layout, "03366500")
                processor = self._processor(
                    input_dir,
                    layout,
                    ["01109403", "02299950", "03366500"],
                )

                with self.assertRaisesRegex(
                    FileNotFoundError,
                    "Geopackages are missing for requested gages: 02299950",
                ):
                    processor.load_gage_ids()

    def test_returns_every_requested_gage_in_requested_order(self):
        for layout in ("gage", "resource"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as tmp:
                input_dir = Path(tmp)
                first = self._add_gpkg(input_dir, layout, "03366500")
                second = self._add_gpkg(input_dir, layout, "01109403")
                processor = self._processor(
                    input_dir,
                    layout,
                    ["01109403", "03366500"],
                )

                self.assertEqual(processor.load_gage_ids(), [second, first])


if __name__ == "__main__":
    unittest.main()
