from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd


MODULE_PATH = (
    Path(__file__).parents[1] / "utils" / "python" / "download_openet.py"
)
SPEC = importlib.util.spec_from_file_location("download_openet", MODULE_PATH)
openet = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = openet
SPEC.loader.exec_module(openet)


class FakeOpenETClient:
    base_url = "https://openet.example"

    def __init__(self):
        self.uploaded = {}
        self.polygon_requests = []
        self.multipolygon_requests = []

    def polygon_timeseries(self, payload):
        self.polygon_requests.append(payload)
        start, end = payload["date_range"]
        return [
            {"time": start, "et": 1.5},
            {"time": end, "et": 2.5},
        ]

    def upload_geojson(self, path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        asset_id = f"projects/test/assets/batch-{len(self.uploaded) + 1}"
        self.uploaded[asset_id] = [
            feature["properties"]["divide_id"]
            for feature in payload["features"]
        ]
        return asset_id

    def multipolygon_timeseries(self, payload):
        self.multipolygon_requests.append(payload)
        start, end = payload["date_range"]
        return [
            {"time": time, "et": float(index + 1), "divide_id": divide_id}
            for index, divide_id in enumerate(self.uploaded[payload["asset_id"]])
            for time in (start, end)
        ]


class TestOpenETDownloader(unittest.TestCase):
    def test_downloads_lumped_and_distributed_outputs(self):
        gpkg = Path(__file__).parent / "input/01308000/data/gage_01308000.gpkg"
        with tempfile.TemporaryDirectory() as temp_dir:
            options = openet.OpenETOptions(
                gpkg=gpkg,
                start=date(2016, 1, 1),
                end=date(2016, 1, 2),
                output_dir=Path(temp_dir),
                gage_id="01308000",
                basin_aggregate=True,
                divide_scale=True,
                output_format="csv",
                max_polygons_per_request=2,
            )
            client = FakeOpenETClient()

            outputs = openet.download_openet(options, client)

            self.assertEqual(set(outputs), {"lumped", "distributed", "metadata"})
            lumped = pd.read_csv(outputs["lumped"])
            distributed = pd.read_csv(outputs["distributed"])
            self.assertEqual(lumped.columns.tolist(), ["value_time", "value"])
            self.assertEqual(len(lumped), 2)
            self.assertEqual(
                set(distributed.columns) - {"value_time"},
                {"cat-109788", "cat-109789", "cat-109790"},
            )
            self.assertEqual(len(client.uploaded), 2)
            self.assertEqual(len(client.multipolygon_requests), 2)
            metadata = json.loads(outputs["metadata"].read_text(encoding="utf-8"))
            self.assertEqual(metadata["observation_units"], "mm/d")
            self.assertNotIn("api_key", json.dumps(metadata).lower())

    def test_daily_ranges_are_split_at_366_inclusive_days(self):
        chunks = openet._date_chunks(
            date(2016, 1, 1),
            date(2017, 1, 1),
            "daily",
        )

        self.assertEqual(
            chunks,
            [
                (date(2016, 1, 1), date(2016, 12, 31)),
                (date(2017, 1, 1), date(2017, 1, 1)),
            ],
        )

    def test_requires_at_least_one_spatial_output(self):
        options = openet.OpenETOptions(
            gpkg=Path("gage_01308000.gpkg"),
            start=date(2016, 1, 1),
            end=date(2016, 1, 2),
            output_dir=Path("output"),
            gage_id="01308000",
        )

        with self.assertRaisesRegex(ValueError, "Enable at least one output"):
            options.validate()

    def test_infers_supported_gage_id_from_filename(self):
        self.assertEqual(
            openet.infer_gage_id(Path("vendor-gage_01308000-final.gpkg")),
            "01308000",
        )

    def test_normalizes_nested_multipolygon_response(self):
        frame = openet._normalize_timeseries(
            [
                {
                    "cat-1": [{"time": "2016-01-01", "et": 1.0}],
                    "cat-2": [{"time": "2016-01-01", "et": 2.0}],
                }
            ],
            identifier="divide_id",
        )

        self.assertEqual(frame["divide_id"].tolist(), ["cat-1", "cat-2"])
        self.assertEqual(frame["value"].tolist(), [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
