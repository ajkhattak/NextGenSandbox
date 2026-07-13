import tempfile
import unittest
from pathlib import Path

from src.python.resource_paths import (
    find_gpkg_file,
    forcing_dir_for_resource,
    forcing_dir_for_gpkg,
    has_gage_placeholder,
    has_gpkg_file,
    render_gage_path,
)


class TestResourcePaths(unittest.TestCase):
    def test_has_gpkg_file_ignores_non_basin_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            observation_dir = Path(tmp) / "streamflow"
            observation_dir.mkdir()

            self.assertFalse(has_gpkg_file(observation_dir))

    def test_prefers_hydrofabric_and_falls_back_to_legacy_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            basin_dir = Path(tmp) / "12345678"
            legacy_dir = basin_dir / "data"
            legacy_dir.mkdir(parents=True)
            legacy_gpkg = legacy_dir / "gage_12345678.gpkg"
            legacy_gpkg.touch()

            self.assertTrue(has_gpkg_file(basin_dir))
            self.assertEqual(find_gpkg_file(basin_dir), legacy_gpkg)
            self.assertEqual(
                forcing_dir_for_gpkg(legacy_gpkg, 2016, 2021),
                basin_dir / "forcing" / "2016_to_2021",
            )

            hydrofabric_dir = basin_dir / "hydrofabric"
            hydrofabric_dir.mkdir()
            hydrofabric_gpkg = hydrofabric_dir / "gage_12345678.gpkg"
            hydrofabric_gpkg.touch()

            self.assertEqual(find_gpkg_file(basin_dir), hydrofabric_gpkg)
            self.assertEqual(
                forcing_dir_for_gpkg(hydrofabric_gpkg, 2016, 2021),
                basin_dir / "forcing" / "2016_to_2021",
            )

    def test_resource_layout_forcing_directory(self):
        self.assertEqual(
            forcing_dir_for_resource(
                "/tmp/inputs",
                "12345678",
                2016,
                2021,
                resource_layout="resource",
            ),
            Path("/tmp/inputs/forcing/12345678/2016_to_2021"),
        )

    def test_resource_layout_forcing_directory_placeholder(self):
        self.assertEqual(
            forcing_dir_for_resource(
                "/tmp/inputs",
                "<gage_id>",
                2016,
                2021,
                resource_layout="resource",
            ),
            Path("/tmp/inputs/forcing/<gage_id>/2016_to_2021"),
        )

    def test_render_gage_path_supports_preferred_placeholder(self):
        self.assertTrue(has_gage_placeholder("/tmp/forcing/<gage_id>.nc"))
        self.assertEqual(
            render_gage_path("/tmp/forcing/<gage_id>.nc", "12345678"),
            Path("/tmp/forcing/12345678.nc"),
        )

    def test_render_gage_path_supports_format_placeholder(self):
        self.assertTrue(has_gage_placeholder("/tmp/forcing/{gage_id}.nc"))
        self.assertEqual(
            render_gage_path("/tmp/forcing/{gage_id}.nc", "12345678"),
            Path("/tmp/forcing/12345678.nc"),
        )


if __name__ == "__main__":
    unittest.main()
