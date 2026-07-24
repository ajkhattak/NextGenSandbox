import tempfile
import unittest
from pathlib import Path

from src.python.forcing_files import (
    prepare_rechunked_forcing_file,
    select_netcdf_forcing_file,
    select_source_netcdf_forcing_file,
)


class TestForcingFiles(unittest.TestCase):
    def test_selects_corrected_or_source_netcdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing_dir = Path(tmp)
            source = forcing_dir / "gage_123_2010_to_2021.nc"
            corrected = forcing_dir / "gage_123_2010_to_2021_corrected.nc"
            rechunked = forcing_dir / "gage_123_2010_to_2021_corrected_rechunked.nc"
            source.touch()
            corrected.touch()
            rechunked.touch()

            self.assertEqual(
                select_netcdf_forcing_file(forcing_dir, use_corrected=True),
                corrected,
            )
            self.assertEqual(
                select_netcdf_forcing_file(forcing_dir, use_corrected=False),
                source,
            )
            self.assertEqual(select_source_netcdf_forcing_file(forcing_dir), source)

    def test_prepare_rechunked_reuses_current_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing_dir = Path(tmp)
            source = forcing_dir / "forcing_corrected.nc"
            rechunked = forcing_dir / "forcing_corrected_rechunked.nc"
            source.touch()
            rechunked.touch()

            result = prepare_rechunked_forcing_file(
                source,
                sandbox_dir=forcing_dir,
                enabled=True,
            )

            self.assertEqual(result, rechunked)


if __name__ == "__main__":
    unittest.main()
