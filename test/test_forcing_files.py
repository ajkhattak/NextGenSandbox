import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from src.python.forcing_files import (
    netcdf_forcing_time_bounds,
    prepare_rechunked_forcing_file,
    resolve_netcdf_forcing_pattern,
    select_prepared_forcing_file,
    select_netcdf_forcing_file,
    select_source_netcdf_forcing_file,
)


class TestForcingFiles(unittest.TestCase):
    def test_reads_one_dimensional_netcdf_time_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing = Path(tmp) / "forcing.nc"
            times = pd.date_range("2015-01-01", periods=3, freq="h")
            xr.Dataset(coords={"time": times}).to_netcdf(forcing)

            start, end = netcdf_forcing_time_bounds(forcing)

            self.assertEqual(start, pd.Timestamp("2015-01-01 00:00:00"))
            self.assertEqual(end, pd.Timestamp("2015-01-01 02:00:00"))

    def test_reads_catchment_repeated_netcdf_time_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing = Path(tmp) / "forcing.nc"
            times = pd.date_range("2015-01-01", periods=3, freq="h")
            values = np.tile(times.values, (2, 1))
            xr.Dataset(
                {"Time": (("catchment-id", "time"), values)},
            ).to_netcdf(forcing)

            start, end = netcdf_forcing_time_bounds(forcing)

            self.assertEqual(start, pd.Timestamp("2015-01-01 00:00:00"))
            self.assertEqual(end, pd.Timestamp("2015-01-01 02:00:00"))

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

    def test_select_prepared_forcing_requires_rechunked_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "forcing.nc"
            source.touch()

            with self.assertRaisesRegex(FileNotFoundError, "sandbox --forc"):
                select_prepared_forcing_file(
                    source,
                    rechunk_enabled=True,
                )

    def test_select_prepared_forcing_rejects_stale_rechunked_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "forcing.nc"
            rechunked = Path(tmp) / "forcing_rechunked.nc"
            source.touch()
            rechunked.touch()
            os.utime(rechunked, (100, 100))
            os.utime(source, (200, 200))

            with self.assertRaisesRegex(ValueError, "sandbox --forc"):
                select_prepared_forcing_file(
                    source,
                    rechunk_enabled=True,
                )

    def test_custom_pattern_rejects_source_corrected_and_rechunked_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing_dir = Path(tmp)
            source = forcing_dir / "aorc-gage_50147800-source.nc"
            corrected = forcing_dir / "aorc-gage_50147800-source_corrected.nc"
            rechunked = (
                forcing_dir / "aorc-gage_50147800-source_corrected_rechunked.nc"
            )
            source.touch()
            corrected.touch()
            rechunked.touch()

            pattern = forcing_dir / "*50147800*.nc"

            with self.assertRaisesRegex(ValueError, "must match exactly one"):
                resolve_netcdf_forcing_pattern(pattern)

    def test_custom_pattern_accepts_single_external_file_without_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            forcing = Path(tmp) / "vendor-product-50147800-hourly.nc"
            forcing.touch()

            self.assertEqual(
                resolve_netcdf_forcing_pattern(
                    Path(tmp) / "*50147800*.nc",
                ),
                forcing,
            )

    def test_custom_pattern_accepts_rechunked_file_when_base_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            rechunked = Path(tmp) / "gage_50147800_corrected_rechunked.nc"
            rechunked.touch()

            self.assertEqual(
                resolve_netcdf_forcing_pattern(
                    Path(tmp) / "*50147800*.nc",
                ),
                rechunked,
            )

    def test_custom_pattern_accepts_base_and_rechunked_sibling_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "gage_50147800_corrected.nc"
            rechunked = Path(tmp) / "gage_50147800_corrected_rechunked.nc"
            base.touch()
            rechunked.touch()

            self.assertEqual(
                resolve_netcdf_forcing_pattern(
                    Path(tmp) / "*50147800*.nc",
                    rechunk_enabled=True,
                ),
                base,
            )

    def test_custom_pattern_rejects_base_and_rechunked_sibling_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "gage_50147800_corrected.nc"
            rechunked = Path(tmp) / "gage_50147800_corrected_rechunked.nc"
            base.touch()
            rechunked.touch()

            with self.assertRaisesRegex(ValueError, "must match exactly one"):
                resolve_netcdf_forcing_pattern(
                    Path(tmp) / "*50147800*.nc",
                    rechunk_enabled=False,
                )

    def test_custom_pattern_rejects_unrelated_matches_when_rechunk_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "gage_50147800.nc"
            corrected = Path(tmp) / "gage_50147800_corrected.nc"
            rechunked = Path(tmp) / "gage_50147800_corrected_rechunked.nc"
            source.touch()
            corrected.touch()
            rechunked.touch()

            with self.assertRaisesRegex(ValueError, "must match exactly one"):
                resolve_netcdf_forcing_pattern(
                    Path(tmp) / "*50147800*.nc",
                    rechunk_enabled=True,
                )

    def test_custom_pattern_rejects_multiple_files_for_one_gage(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "forcing-50147800-a.nc"
            second = Path(tmp) / "forcing-50147800-b.nc"
            first.touch()
            second.touch()

            with self.assertRaisesRegex(ValueError, "Multiple NetCDF forcing"):
                resolve_netcdf_forcing_pattern(
                    Path(tmp) / "*50147800*.nc",
                )


if __name__ == "__main__":
    unittest.main()
