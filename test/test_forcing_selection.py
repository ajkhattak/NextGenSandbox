import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

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

    def test_custom_gpkg_template_is_used_for_forcing_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "external"
            directory.mkdir()
            first = directory / "hf_v2_01308000_final.gpkg"
            second = directory / "hf_v2_03366500_final.gpkg"
            first.touch()
            second.touch()

            processor = object.__new__(ForcingProcessor)
            processor.config = {
                "general": {
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {
                            "dir": str(directory / "hf_v2_<gage_id>_*.gpkg"),
                        },
                    },
                }
            }
            processor.selected_gages = ["03366500", "01308000"]

            self.assertEqual(processor.load_gage_ids(), [second, first])
            self.assertEqual(processor._resource_gage_id(second), "03366500")

    def test_forcing_step_accepts_existing_netcdf_filename_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "sandbox.yaml"
            config = {
                "general": {
                    "input_dir": tmp,
                    "output_dir": str(Path(tmp) / "outputs"),
                    "gages": {
                        "option": "ids",
                        "ids": ["50147800"],
                    },
                },
                "formulation": {},
                "forcings": {
                    "time": {
                        "start": "2016-01-01",
                        "end": "2016-12-31 23:00:00",
                    },
                    "forcing_dir": str(Path(tmp) / "*<gage_id>*.nc"),
                },
            }
            with config_file.open("w") as stream:
                yaml.safe_dump(config, stream)

            processor = object.__new__(ForcingProcessor)
            processor.config_file = str(config_file)

            with patch.dict("os.environ", {}, clear=True):
                processor.load_config()

            self.assertTrue(processor.external_netcdf_template)
            self.assertIsNone(processor.forcing_venv_dir)

    def test_forcing_step_prepares_existing_custom_netcdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "vendor-gage_50147800-hourly.nc"
            rechunked = Path(tmp) / "vendor-gage_50147800-hourly_rechunked.nc"
            source.touch()
            rechunked.touch()
            os.utime(source, (100, 100))
            os.utime(rechunked, (200, 200))

            processor = object.__new__(ForcingProcessor)
            processor.forcing_dir = str(Path(tmp) / "*<gage_id>*.nc")
            processor.rechunk_forcing = True
            processor.sandbox_dir = Path(tmp)

            self.assertFalse(processor.prepare_existing_forcing("50147800"))


if __name__ == "__main__":
    unittest.main()
