import tempfile
import unittest
from pathlib import Path

from src.python.context import SandboxContext


class TestContextForcing(unittest.TestCase):
    def _context_for_netcdf_file(self, forcing_file, gpkg_count):
        ctx = object.__new__(SandboxContext)
        ctx.forcing_dir = str(forcing_file)
        ctx.gpkg_dirs = [Path(f"/tmp/gage_{i}") for i in range(gpkg_count)]
        ctx.sandbox_dir = Path.cwd()
        ctx.rechunk_forcing = False
        ctx.is_corrected_forcing = False
        return ctx

    def _context_for_pattern(self, forcing_dir):
        ctx = object.__new__(SandboxContext)
        ctx.forcing_dir = str(forcing_dir)
        ctx.gpkg_dirs = [Path("/tmp/gage_50147800.gpkg")]
        ctx.sandbox_dir = Path.cwd()
        ctx.rechunk_forcing = False
        ctx.is_corrected_forcing = False
        ctx.forcing_format = ".nc"
        ctx.forcing_dir_is_configured = True
        ctx.forcing_year_dir = "2016_to_2021"
        return ctx

    def test_single_netcdf_file_allowed_for_one_gage(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing_file = Path(tmp) / "gage_50147800.nc"
            forcing_file.touch()

            ctx = self._context_for_netcdf_file(forcing_file, gpkg_count=1)

            self.assertEqual(ctx._resolve_single_netcdf_forcing_file(), forcing_file)

    def test_single_netcdf_file_rejected_for_multiple_gages(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing_file = Path(tmp) / "forcing.nc"
            forcing_file.touch()

            ctx = self._context_for_netcdf_file(forcing_file, gpkg_count=2)

            with self.assertRaisesRegex(ValueError, "single NetCDF file"):
                ctx._resolve_single_netcdf_forcing_file()

    def test_pattern_netcdf_directory_per_gage_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing_dir = Path(tmp) / "forcing_custom" / "50147800"
            forcing_dir.mkdir(parents=True)
            forcing_file = forcing_dir / "forcing.nc"
            forcing_file.touch()

            ctx = self._context_for_pattern(
                Path(tmp) / "forcing_custom" / "<gage_id>"
            )

            ctx.prepare_forcing_files()

            self.assertEqual(ctx.forcing_files, [str(forcing_file)])

    def test_pattern_netcdf_file_per_gage_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing_file = Path(tmp) / "forcing_custom" / "50147800.nc"
            forcing_file.parent.mkdir()
            forcing_file.touch()

            ctx = self._context_for_pattern(
                Path(tmp) / "forcing_custom" / "<gage_id>.nc"
            )

            ctx.prepare_forcing_files()

            self.assertEqual(ctx.forcing_files, [str(forcing_file)])

    def test_pattern_netcdf_file_requires_nc_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing_file = Path(tmp) / "forcing_custom" / "50147800.txt"
            forcing_file.parent.mkdir()
            forcing_file.touch()

            ctx = self._context_for_pattern(
                Path(tmp) / "forcing_custom" / "<gage_id>.txt"
            )

            with self.assertRaisesRegex(ValueError, "requires a .nc file"):
                ctx.prepare_forcing_files()


if __name__ == "__main__":
    unittest.main()
