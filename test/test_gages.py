import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.python.gages import (
    load_general_gages,
    load_gpkg_resources,
    resolve_step_gages,
)


class TestGageSelection(unittest.TestCase):
    def test_general_gages_from_ids(self):
        config = {
            "general": {
                "gages": {
                    "option": "ids",
                    "ids": ["01308000", "03366500"],
                }
            }
        }

        self.assertEqual(load_general_gages(config), ["01308000", "03366500"])

    def test_general_gages_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gages.csv"
            pd.DataFrame({"gage_id": ["01308000", "03366500"]}).to_csv(
                path, index=False
            )
            config = {
                "general": {
                    "gages": {
                        "option": "file",
                        "file": {
                            "path": str(path),
                            "column": "gage_id",
                        },
                    }
                }
            }

            self.assertEqual(load_general_gages(config), ["01308000", "03366500"])

    def test_general_gages_from_gpkg_select(self):
        with tempfile.TemporaryDirectory() as tmp:
            hydrofabric = Path(tmp) / "hydrofabric"
            hydrofabric.mkdir()
            (hydrofabric / "gage_01308000.gpkg").touch()
            (hydrofabric / "gage_03366500.gpkg").touch()
            config = {
                "general": {
                    "input_dir": tmp,
                    "resource_layout": "resource",
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {
                            "select": ["01308000", "03366500"],
                        },
                    },
                }
            }

            self.assertEqual(
                load_general_gages(config),
                ["01308000", "03366500"],
            )

    def test_general_gages_from_resource_layout_gpkg_default_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            hydrofabric = Path(tmp) / "hydrofabric"
            hydrofabric.mkdir()
            (hydrofabric / "gage_01308000.gpkg").touch()
            (hydrofabric / "gage_03366500.gpkg").touch()

            config = {
                "general": {
                    "input_dir": tmp,
                    "resource_layout": "resource",
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {},
                    },
                }
            }

            self.assertEqual(load_general_gages(config), ["01308000", "03366500"])

    def test_gpkg_discovery_preserves_supported_gage_id_lengths(self):
        with tempfile.TemporaryDirectory() as tmp:
            hydrofabric = Path(tmp) / "hydrofabric"
            hydrofabric.mkdir()
            expected = ["01308000", "1234567890", "123456789012"]
            for gage_id in expected:
                (hydrofabric / f"gage_{gage_id}.gpkg").touch()

            config = {
                "general": {
                    "input_dir": tmp,
                    "resource_layout": "resource",
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {},
                    },
                }
            }

            self.assertEqual(load_general_gages(config), expected)

    def test_gpkg_discovery_rejects_unsupported_gage_id_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            hydrofabric = Path(tmp) / "hydrofabric"
            hydrofabric.mkdir()
            (hydrofabric / "gage_011094030.gpkg").touch()

            config = {
                "general": {
                    "input_dir": tmp,
                    "resource_layout": "resource",
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {},
                    },
                }
            }

            with self.assertRaisesRegex(ValueError, "Gage IDs are never truncated"):
                load_general_gages(config)

    def test_gpkg_discovery_rejects_ambiguous_numeric_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            hydrofabric = Path(tmp) / "hydrofabric"
            hydrofabric.mkdir()
            (hydrofabric / "gage_01109403_v2.gpkg").touch()

            config = {
                "general": {
                    "input_dir": tmp,
                    "resource_layout": "resource",
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {},
                    },
                }
            }

            with self.assertRaisesRegex(ValueError, "exactly one numeric gage ID"):
                load_general_gages(config)

    def test_general_gages_from_gage_layout_gpkg_default_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            for gage_id in ["01308000", "03366500"]:
                hydrofabric = Path(tmp) / gage_id / "hydrofabric"
                hydrofabric.mkdir(parents=True)
                (hydrofabric / f"gage_{gage_id}.gpkg").touch()

            config = {
                "general": {
                    "input_dir": tmp,
                    "resource_layout": "gage",
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {},
                    },
                }
            }

            self.assertEqual(load_general_gages(config), ["01308000", "03366500"])

    def test_custom_gpkg_template_extracts_id_from_placeholder_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "external hydrofabrics"
            directory.mkdir()
            first = directory / "hf_v2_01308000_release_2026.gpkg"
            second = directory / "hf_v2_1234567890_release_2026.gpkg"
            first.touch()
            second.touch()

            config = {
                "general": {
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {
                            "dir": str(directory / "hf_v2_<gage_id>_*.gpkg"),
                        },
                    },
                }
            }

            self.assertEqual(
                load_gpkg_resources(config),
                {
                    "01308000": first,
                    "1234567890": second,
                },
            )

    def test_custom_gpkg_template_preserves_selected_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = directory / "custom_01308000_file.gpkg"
            second = directory / "custom_03366500_file.gpkg"
            first.touch()
            second.touch()

            config = {
                "general": {
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {
                            "dir": str(directory / "custom_<gage_id>_*.gpkg"),
                        },
                    },
                }
            }

            self.assertEqual(
                load_gpkg_resources(config, ["03366500", "01308000"]),
                {
                    "03366500": second,
                    "01308000": first,
                },
            )

    def test_custom_gpkg_template_rejects_duplicate_gage_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "custom_01308000_a.gpkg").touch()
            (directory / "custom_01308000_b.gpkg").touch()
            config = {
                "general": {
                    "gages": {
                        "option": "gpkg",
                        "gpkg": {
                            "dir": str(directory / "custom_<gage_id>_*.gpkg"),
                        },
                    },
                }
            }

            with self.assertRaisesRegex(ValueError, "Multiple geopackages"):
                load_gpkg_resources(config)

    def test_custom_gpkg_wildcard_requires_gage_placeholder(self):
        config = {
            "general": {
                "gages": {
                    "option": "gpkg",
                    "gpkg": {"dir": "/tmp/custom_*.gpkg"},
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "must include <gage_id>"):
            load_gpkg_resources(config)

    def test_gpkg_pattern_is_rejected(self):
        config = {
            "general": {
                "gages": {
                    "option": "gpkg",
                    "gpkg": {"pattern": "gage_"},
                },
            }
        }

        with self.assertRaisesRegex(ValueError, "pattern is no longer supported"):
            load_general_gages(config)

    def test_step_gages_default_to_project_gages(self):
        self.assertEqual(
            resolve_step_gages(
                project_gages=["01308000", "03366500"],
                step_value=None,
                field_name="simulation.gages",
            ),
            ["01308000", "03366500"],
        )

    def test_step_gages_must_be_subset_of_project_gages(self):
        with self.assertRaisesRegex(ValueError, "outside general.gages"):
            resolve_step_gages(
                project_gages=["01308000"],
                step_value=["03366500"],
                field_name="simulation.gages",
            )

    def test_step_gages_reject_csv_when_project_gages_are_configured(self):
        with self.assertRaisesRegex(ValueError, "does not support CSV"):
            resolve_step_gages(
                project_gages=["01308000"],
                step_value="gages.csv",
                field_name="simulation.gages",
            )

    def test_general_gages_are_required(self):
        with self.assertRaisesRegex(ValueError, "general.gages"):
            load_general_gages({"general": {}})


if __name__ == "__main__":
    unittest.main()
