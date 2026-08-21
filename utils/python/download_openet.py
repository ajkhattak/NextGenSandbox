from __future__ import annotations

"""Download OpenET evapotranspiration for a NextGen hydrofabric."""

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import mapping
from shapely.ops import unary_union


OPENET_API_URL = "https://openet-api.org"
SUPPORTED_GAGE_ID_LENGTHS = (8, 10, 12)
SUPPORTED_FORMATS = {"csv", "parquet"}
SUPPORTED_INTERVALS = {"daily", "monthly"}


@dataclass(frozen=True)
class OpenETOptions:
    gpkg: Path
    start: date
    end: date
    output_dir: Path
    gage_id: str
    basin_aggregate: bool = False
    divide_scale: bool = False
    interval: str = "daily"
    model: str = "Ensemble"
    reference_et: str = "gridMET"
    units: str = "mm"
    reducer: str = "mean"
    version: float = 2.1
    output_format: str = "parquet"
    max_polygons_per_request: int = 100
    keep_raw: bool = False

    def validate(self) -> None:
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        if not self.basin_aggregate and not self.divide_scale:
            raise ValueError(
                "Enable at least one output: --basin-aggregate or --divide-scale"
            )
        if self.interval not in SUPPORTED_INTERVALS:
            raise ValueError(
                f"interval must be one of: {', '.join(sorted(SUPPORTED_INTERVALS))}"
            )
        if self.output_format not in SUPPORTED_FORMATS:
            raise ValueError(
                "output_format must be one of: "
                f"{', '.join(sorted(SUPPORTED_FORMATS))}"
            )
        if self.max_polygons_per_request < 1:
            raise ValueError("max_polygons_per_request must be >= 1")
        earliest = (
            date(2016, 1, 1)
            if self.interval == "daily"
            else date(2000, 1, 1)
        )
        if self.start < earliest:
            raise ValueError(
                f"OpenET {self.interval} ET is available starting {earliest}"
            )


class OpenETClient:
    """Small client for the OpenET endpoints used by this utility."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = OPENET_API_URL,
        timeout: int = 600,
        session: requests.Session | None = None,
    ):
        if not api_key.strip():
            raise ValueError(
                "OpenET API key is empty. Set the OPENET_API_KEY environment variable."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {
            "Authorization": api_key,
            "accept": "application/json",
        }

    def polygon_timeseries(self, payload: dict[str, Any]) -> Any:
        return self._post_json("/raster/timeseries/polygon", payload)

    def multipolygon_timeseries(self, payload: dict[str, Any]) -> Any:
        return self._post_json("/raster/timeseries/multipolygon", payload)

    def upload_geojson(self, path: Path) -> str:
        with path.open("rb") as stream:
            response = self.session.post(
                f"{self.base_url}/account/upload",
                headers=self.headers,
                files={"file": (path.name, stream, "application/geo+json")},
                timeout=self.timeout,
            )
        payload = self._decode_response(response, "/account/upload")
        asset_id = _find_asset_id(payload)
        if asset_id is None:
            raise RuntimeError(
                "OpenET upload succeeded but its response did not contain an "
                f"asset_id: {payload!r}"
            )
        return asset_id

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> Any:
        response = self.session.post(
            f"{self.base_url}{endpoint}",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        return self._decode_response(response, endpoint)

    @staticmethod
    def _decode_response(response: requests.Response, endpoint: str) -> Any:
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            detail = response.text.strip()
            if len(detail) > 1000:
                detail = f"{detail[:1000]}..."
            raise RuntimeError(
                f"OpenET request to {endpoint} failed with HTTP "
                f"{response.status_code}: {detail or exc}"
            ) from exc
        try:
            return response.json()
        except requests.JSONDecodeError as exc:
            raise RuntimeError(
                f"OpenET request to {endpoint} returned invalid JSON"
            ) from exc


def infer_gage_id(gpkg: Path) -> str:
    numeric_tokens = re.findall(r"\d+", gpkg.stem)
    valid = [
        token for token in numeric_tokens if len(token) in SUPPORTED_GAGE_ID_LENGTHS
    ]
    if len(numeric_tokens) != 1 or len(valid) != 1:
        lengths = ", ".join(str(value) for value in SUPPORTED_GAGE_ID_LENGTHS)
        raise ValueError(
            f"Cannot infer a gage ID from '{gpkg.name}'. Provide --gage-id, "
            f"or use a filename containing exactly one {lengths}-digit ID."
        )
    return valid[0]


def load_divides(gpkg: Path) -> gpd.GeoDataFrame:
    gpkg = gpkg.expanduser().resolve()
    if not gpkg.is_file():
        raise FileNotFoundError(f"Geopackage does not exist: {gpkg}")
    try:
        divides = gpd.read_file(gpkg, layer="divides")
    except Exception as exc:
        raise ValueError(
            f"Could not read the 'divides' layer from {gpkg}: {exc}"
        ) from exc
    if "divide_id" not in divides.columns:
        raise ValueError(f"The 'divides' layer in {gpkg} has no divide_id column")
    if divides.crs is None:
        raise ValueError(f"The 'divides' layer in {gpkg} has no CRS")

    divides = divides[["divide_id", "geometry"]].copy()
    divides["divide_id"] = divides["divide_id"].astype(str)
    if divides["divide_id"].duplicated().any():
        duplicates = sorted(divides.loc[divides["divide_id"].duplicated(), "divide_id"])
        raise ValueError(
            f"Duplicate divide_id values in {gpkg}: {', '.join(duplicates)}"
        )
    invalid = divides.geometry.isna() | divides.geometry.is_empty
    if invalid.any():
        ids = divides.loc[invalid, "divide_id"].tolist()
        raise ValueError(f"Missing or empty divide geometries: {', '.join(ids)}")
    if (~divides.geometry.is_valid).any():
        ids = divides.loc[~divides.geometry.is_valid, "divide_id"].tolist()
        raise ValueError(f"Invalid divide geometries: {', '.join(ids)}")

    divides = divides.to_crs("EPSG:4326")
    non_polygon = ~divides.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if non_polygon.any():
        ids = divides.loc[non_polygon, "divide_id"].tolist()
        raise ValueError(f"Non-polygon divide geometries: {', '.join(ids)}")
    return divides


def _base_request(options: OpenETOptions, start: date, end: date) -> dict[str, Any]:
    return {
        "date_range": [start.isoformat(), end.isoformat()],
        "interval": options.interval,
        "model": options.model,
        "variable": "ET",
        "reference_et": options.reference_et,
        "reducer": options.reducer,
        "units": options.units,
        "version": options.version,
        "overpass": False,
    }


def _date_chunks(start: date, end: date, interval: str) -> list[tuple[date, date]]:
    # The OpenET multipolygon endpoint currently supports at most 366 daily
    # timesteps. Monthly requests are small enough to submit as one range.
    if interval == "monthly":
        return [(start, end)]
    chunks = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=365), end)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


def _find_asset_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("asset_id", "assetId"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _find_asset_id(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_asset_id(value)
            if found:
                return found
    elif isinstance(payload, str) and payload.startswith("projects/"):
        return payload
    return None


def _records(payload: Any, *, identifier: str | None = None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        if all(isinstance(item, dict) for item in payload):
            return [dict(item) for item in payload]
        raise ValueError("OpenET response list contains non-record values")
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            if key in payload:
                return _records(payload[key], identifier=identifier)

        nested_records = []
        for key, value in payload.items():
            if not isinstance(value, list) or not all(
                isinstance(item, dict) for item in value
            ):
                continue
            for item in value:
                record = dict(item)
                if identifier and identifier not in record:
                    record[identifier] = key
                nested_records.append(record)
        if nested_records:
            return nested_records

        if payload and all(_looks_like_date(key) for key in payload):
            return [{"time": key, "et": value} for key, value in payload.items()]
    raise ValueError(f"Unsupported OpenET response structure: {type(payload).__name__}")


def _looks_like_date(value: Any) -> bool:
    try:
        pd.Timestamp(value)
        return True
    except (TypeError, ValueError):
        return False


def _find_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str:
    lowered = {str(column).lower(): str(column) for column in frame.columns}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    for column in frame.columns:
        suffix = str(column).lower().rsplit(".", 1)[-1]
        if suffix in {name.lower() for name in names}:
            return str(column)
    raise ValueError(
        f"OpenET response is missing one of columns {names}; found: "
        f"{', '.join(str(column) for column in frame.columns)}"
    )


def _normalize_timeseries(
    payloads: list[Any],
    *,
    identifier: str | None = None,
) -> pd.DataFrame:
    records = []
    for payload in payloads:
        records.extend(_records(payload, identifier=identifier))
    if not records:
        raise ValueError("OpenET returned no ET records")

    frame = pd.json_normalize(records)
    time_column = _find_column(frame, ("time", "date", "value_time"))
    value_column = _find_column(frame, ("et", "value"))
    rename = {time_column: "value_time", value_column: "value"}
    if identifier:
        id_column = _find_column(frame, (identifier,))
        rename[id_column] = identifier
    keep = [time_column, value_column]
    if identifier:
        keep.append(id_column)
    frame = frame[keep].rename(columns=rename)
    frame["value_time"] = (
        pd.to_datetime(frame["value_time"], utc=True).dt.tz_localize(None)
    )
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    if identifier:
        frame[identifier] = frame[identifier].astype(str)
    return frame.sort_values(["value_time"] + ([identifier] if identifier else []))


def _write_frame(frame: pd.DataFrame, path: Path, output_format: str) -> Path:
    path = path.with_suffix(f".{output_format}")
    if output_format == "csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path, index=False)
    return path


def _write_raw(payloads: list[Any], path: Path) -> None:
    path.write_text(json.dumps(payloads, indent=2), encoding="utf-8")


def download_openet(
    options: OpenETOptions,
    client: OpenETClient,
) -> dict[str, Path]:
    options.validate()
    divides = load_divides(options.gpkg)
    options.output_dir.mkdir(parents=True, exist_ok=True)
    chunks = _date_chunks(options.start, options.end, options.interval)
    outputs: dict[str, Path] = {}
    raw_payloads: dict[str, list[Any]] = {}

    if options.basin_aggregate:
        basin_geometry = unary_union(divides.geometry.tolist())
        payloads = []
        for start, end in chunks:
            request = _base_request(options, start, end)
            request.update({"geojson": mapping(basin_geometry), "file_format": "JSON"})
            payloads.append(client.polygon_timeseries(request))
        lumped = _normalize_timeseries(payloads)
        if lumped["value_time"].duplicated().any():
            raise ValueError("OpenET returned duplicate lumped ET timestamps")
        outputs["lumped"] = _write_frame(
            lumped,
            options.output_dir
            / f"openet_{options.gage_id}_lumped_{options.interval}",
            options.output_format,
        )
        raw_payloads["lumped"] = payloads

    if options.divide_scale:
        payloads = []
        expected_ids = set(divides["divide_id"])
        for offset in range(0, len(divides), options.max_polygons_per_request):
            batch = divides.iloc[offset : offset + options.max_polygons_per_request]
            with tempfile.TemporaryDirectory(prefix="sandbox_openet_") as temp_dir:
                upload_path = Path(temp_dir) / "divides.geojson"
                upload_path.write_text(batch.to_json(), encoding="utf-8")
                asset_id = client.upload_geojson(upload_path)
            for start, end in chunks:
                request = _base_request(options, start, end)
                request.update(
                    {
                        "asset_id": asset_id,
                        "attributes": ["divide_id"],
                    }
                )
                payloads.append(client.multipolygon_timeseries(request))

        long_frame = _normalize_timeseries(payloads, identifier="divide_id")
        returned_ids = set(long_frame["divide_id"])
        missing = sorted(expected_ids - returned_ids)
        unexpected = sorted(returned_ids - expected_ids)
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"missing divide IDs: {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected divide IDs: {', '.join(unexpected)}")
            raise ValueError("OpenET divide response mismatch; " + "; ".join(details))
        if long_frame[["value_time", "divide_id"]].duplicated().any():
            raise ValueError("OpenET returned duplicate time/divide ET records")
        distributed = (
            long_frame.pivot(index="value_time", columns="divide_id", values="value")
            .sort_index()
            .reset_index()
        )
        distributed.columns.name = None
        outputs["distributed"] = _write_frame(
            distributed,
            options.output_dir
            / f"openet_{options.gage_id}_distributed_{options.interval}",
            options.output_format,
        )
        raw_payloads["distributed"] = payloads

    if options.keep_raw:
        for name, payloads in raw_payloads.items():
            _write_raw(
                payloads,
                options.output_dir / f"openet_{options.gage_id}_{name}_response.json",
            )

    metadata = {
        "source": "OpenET API",
        "api_url": client.base_url,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "gpkg": str(options.gpkg.expanduser().resolve()),
        "options": {
            key: str(value) if isinstance(value, (Path, date)) else value
            for key, value in asdict(options).items()
        },
        "outputs": {name: str(path) for name, path in outputs.items()},
        "observation_units": f"{options.units}/d"
        if options.interval == "daily"
        else f"{options.units}/month",
    }
    metadata_path = options.output_dir / f"openet_{options.gage_id}_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    outputs["metadata"] = metadata_path
    return outputs


def _parse_date(value: str) -> date:
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"Invalid date: {value}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download OpenET ET for a NextGen geopackage. Set OPENET_API_KEY "
            "before running."
        )
    )
    parser.add_argument("--gpkg", required=True, type=Path)
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--gage-id",
        help="Gage ID used in output filenames; inferred from the geopackage name.",
    )
    parser.add_argument(
        "--basin-aggregate",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Write one lumped, basin-mean ET time series.",
    )
    parser.add_argument(
        "--divide-scale",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Write ET for every hydrofabric divide.",
    )
    parser.add_argument(
        "--interval", choices=sorted(SUPPORTED_INTERVALS), default="daily"
    )
    parser.add_argument("--model", default="Ensemble")
    parser.add_argument("--reference-et", default="gridMET")
    parser.add_argument("--reducer", default="mean")
    parser.add_argument("--version", type=float, default=2.1)
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["csv", "parquet"],
        default="parquet",
    )
    parser.add_argument("--max-polygons-per-request", type=int, default=100)
    parser.add_argument("--keep-raw", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    gpkg = args.gpkg.expanduser().resolve()
    gage_id = args.gage_id or infer_gage_id(gpkg)
    options = OpenETOptions(
        gpkg=gpkg,
        start=args.start,
        end=args.end,
        output_dir=args.output_dir.expanduser().resolve(),
        gage_id=gage_id,
        basin_aggregate=args.basin_aggregate,
        divide_scale=args.divide_scale,
        interval=args.interval,
        model=args.model,
        reference_et=args.reference_et,
        reducer=args.reducer,
        version=args.version,
        output_format=args.output_format,
        max_polygons_per_request=args.max_polygons_per_request,
        keep_raw=args.keep_raw,
    )
    api_key = os.environ.get("OPENET_API_KEY", "")
    client = OpenETClient(api_key)
    outputs = download_openet(options, client)
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
