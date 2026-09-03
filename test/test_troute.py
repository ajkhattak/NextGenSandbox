import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import yaml

from src.python.models.troute import TRouteConfigurationGenerator


class TestTRouteConfigurationGenerator(unittest.TestCase):
    def test_all_tasks_mask_stream_output_to_terminal_flowpaths(self):
        network = pd.DataFrame(
            {
                "id": ["wb-423185", "wb-423184"],
                "hl_uri": ["gages-02299950", None],
                "toid": ["nex-423186", "nex-423186"],
            }
        )
        attributes = {
            "key": "id",
            "downstream": "toid",
            "mainstem": "mainstem",
            "dx": "Length_m",
            "n": "n",
            "ncc": "nCC",
            "s0": "So",
            "bw": "BtmWdth",
            "waterbody": "WaterbodyID",
            "gages": "gage",
            "tw": "TopWdth",
            "twcc": "TopWdthCC",
            "musk": "MusK",
            "musx": "MusX",
            "cs": "ChSlp",
            "alt": "alt",
        }

        for task_type in (
            "calibration",
            "validation",
            "restart",
            "control",
        ):
            with (
                self.subTest(task_type=task_type),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                config_dir = root / "configs"
                config_dir.mkdir()
                static_data = SimpleNamespace(
                    gdf=pd.DataFrame(),
                    catids=[],
                    config_dir=config_dir,
                    gpkg_file=str(root / "gage_02299950.gpkg"),
                    gage_id="02299950",
                    get_flowpath_attributes=lambda **kwargs: attributes,
                )
                context = SimpleNamespace(
                    sandbox_dir=Path(__file__).resolve().parents[1],
                    task_type=task_type,
                    simulation_time={
                        "start_time": "2015-10-01 00:00:00",
                        "end_time": "2015-10-02 00:00:00",
                    },
                )
                generator = TRouteConfigurationGenerator(
                    context,
                    static_data,
                    root / "output",
                )

                with patch(
                    "src.python.models.troute.gpd.read_file",
                    return_value=network,
                ):
                    generator.write_troute_input_files()

                mask_file = config_dir / "mask_output.yaml"
                troute_config = yaml.safe_load(
                    (config_dir / "troute_config.yaml").read_text()
                )
                stream_output = troute_config["output_parameters"]["stream_output"]

                self.assertEqual(
                    yaml.safe_load(mask_file.read_text()),
                    {"wb": [423185, 423184]},
                )
                self.assertEqual(stream_output["mask_output"], str(mask_file))
                expected_directory = (
                    "./"
                    if task_type != "control"
                    else str(root / "output" / "outputs" / "troute")
                )
                self.assertEqual(
                    stream_output["stream_output_directory"],
                    expected_directory,
                )

    def test_terminal_flowpath_mask_rejects_missing_contributors(self):
        network = pd.DataFrame(
            {
                "id": ["wb-1"],
                "toid": ["nex-2"],
            }
        )

        with self.assertRaisesRegex(ValueError, "No contributing flowpaths"):
            TRouteConfigurationGenerator._terminal_flowpath_ids(
                network,
                "nex-3",
                key_column="id",
                downstream_column="toid",
                gpkg_file="/tmp/gage.gpkg",
            )

    def test_terminal_nexus_uses_explicit_gage_id(self):
        network = pd.DataFrame(
            {
                "hl_uri": ["gages-03366000", "gages-02299950"],
                "toid": ["nex-1", "nex-423186"],
            }
        )

        result = TRouteConfigurationGenerator._terminal_nexus_id(
            network,
            "02299950",
            "/tmp/usgs-gage_02299950-ngen.gpkg",
        )

        self.assertEqual(result, "nex-423186")

    def test_terminal_nexus_reports_missing_gage(self):
        network = pd.DataFrame(
            {
                "hl_uri": ["gages-03366000"],
                "toid": ["nex-1"],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "No terminal nexus found for gage '02299950'",
        ):
            TRouteConfigurationGenerator._terminal_nexus_id(
                network,
                "02299950",
                "/tmp/custom.gpkg",
            )

    def test_terminal_nexus_uses_network_for_colocated_gages(self):
        flowpaths = pd.DataFrame(
            {
                "gage": ["02146315"],
                "gage_nex_id": ["nex-262234"],
            }
        )
        network = pd.DataFrame(
            {
                "hl_uri": ["gages-02146315", "gages-02146300"],
                "toid": ["nex-262234", "nex-262234"],
            }
        )

        result = TRouteConfigurationGenerator._terminal_nexus_id(
            network,
            "02146300",
            "/tmp/gage_02146300.gpkg",
            flowpath_attributes_loader=Mock(return_value=flowpaths),
        )

        self.assertEqual(result, "nex-262234")

    def test_terminal_nexus_falls_back_to_flowpath_attributes(self):
        network = pd.DataFrame(
            {
                "hl_uri": ["gages-03366000"],
                "toid": ["nex-1"],
            }
        )
        flowpaths = pd.DataFrame(
            {
                "gage": ["02299950"],
                "gage_nex_id": ["nex-423186"],
            }
        )

        flowpath_loader = Mock(return_value=flowpaths)
        result = TRouteConfigurationGenerator._terminal_nexus_id(
            network,
            "02299950",
            "/tmp/custom.gpkg",
            flowpath_attributes_loader=flowpath_loader,
        )

        self.assertEqual(result, "nex-423186")
        flowpath_loader.assert_called_once_with()

    def test_terminal_nexus_rejects_ambiguous_network_matches(self):
        network = pd.DataFrame(
            {
                "hl_uri": ["gages-02146300", "gages-02146300"],
                "toid": ["nex-1", "nex-2"],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "Multiple terminal nexuses found for gage '02146300'",
        ):
            TRouteConfigurationGenerator._terminal_nexus_id(
                network,
                "02146300",
                "/tmp/gage_02146300.gpkg",
            )

    def test_terminal_nexus_rejects_ambiguous_matches(self):
        network = pd.DataFrame(
            {
                "hl_uri": ["gages-03366000"],
                "toid": ["nex-3"],
            }
        )
        flowpaths = pd.DataFrame(
            {
                "gage": ["02299950", "02299950"],
                "gage_nex_id": ["nex-1", "nex-2"],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "Multiple terminal nexuses found for gage '02299950'",
        ):
            TRouteConfigurationGenerator._terminal_nexus_id(
                network,
                "02299950",
                "/tmp/custom.gpkg",
                flowpath_attributes=flowpaths,
            )


if __name__ == "__main__":
    unittest.main()
