#!/usr/bin/env python3
"""Compare hydrofabric, NLDI, and NWIS basin drainage areas.

The hydrofabric area is the sum of ``areasqkm`` in the GeoPackage ``divides``
layer. The NLDI area is calculated from its network-derived basin boundary.
The documented USGS drainage area is ``drain_area_va`` from the NWIS site
service, reported in square miles and converted here to square kilometers.

Examples
--------
Check one GeoPackage with the default 5%/10%/20% classification thresholds::

    python check_hydrofabric_basin_area.py gage_08070500.gpkg

Check every GeoPackage below a directory with a 20 percent tolerance::

    python check_hydrofabric_basin_area.py /path/to/subsetters \
        --threshold-pct 20 --output-csv basin_area_comparison.csv

Create corrected copies by removing divides outside the NLDI boundary::

    python check_hydrofabric_basin_area.py /path/to/subsetters \
        --cleaned-gpkg-dir cleaned_hydrofabric \
        --delete-outside-fraction-pct 50 \
        --minimum-outside-area-sqkm 0.1

The minimum outside-area limit applies only to divides that straddle the NLDI
boundary. A divide that is effectively 100 percent outside is always removed,
even when it is smaller than the minimum. This avoids retaining tiny external
connector divides that would otherwise prevent a topology-consistent cleanup.
Use ``--overwrite-cleaned-gpkg`` when intentionally replacing prior outputs.
"""

from __future__ import annotations

import argparse
import glob
import re
import shutil
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
from pathlib import Path
from threading import Lock
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


NWIS_SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
NLDI_BASIN_URL = (
    "https://api.water.usgs.gov/nldi/linked-data/nwissite/"
    "USGS-{gage_id}/basin"
)
NLDI_FEATURE_URL = (
    "https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{gage_id}"
)
SQUARE_MILES_TO_SQUARE_KM = 2.589988110336
SELECTED_STATUSES = {
    "CLEAN_PASS",
    "ACCEPTABLE_OUTLET_OFFSET",
    "HF_NWIS_AGREEMENT_NLDI_OUTLIER",
}
_NLDI_BOUNDARY_CACHE: dict[tuple[str, bool], object] = {}
_NLDI_BOUNDARY_CACHE_LOCK = Lock()


def _classification(
    hf_nldi_absolute_difference_pct: float,
    nldi_nwis_absolute_difference_pct: float,
    hf_nwis_absolute_difference_pct: float,
    *,
    hf_nldi_threshold_pct: float,
    clean_threshold_pct: float,
    threshold_pct: float,
    hf_nwis_fallback_threshold_pct: float,
) -> str:
    """Classify one basin from its topology and observation-area differences."""
    if hf_nldi_absolute_difference_pct > hf_nldi_threshold_pct:
        if (
            nldi_nwis_absolute_difference_pct > threshold_pct
            and hf_nwis_absolute_difference_pct <= hf_nwis_fallback_threshold_pct
        ):
            return "HF_NWIS_AGREEMENT_NLDI_OUTLIER"
        return "SUBSETTER_OR_TOPOLOGY_FAILURE"
    if nldi_nwis_absolute_difference_pct > threshold_pct:
        return "OBSERVATION_DOMAIN_MISMATCH"
    if nldi_nwis_absolute_difference_pct > clean_threshold_pct:
        return "ACCEPTABLE_OUTLET_OFFSET"
    return "CLEAN_PASS"


def extract_gage_id(path: str | Path) -> str:
    """Extract a USGS gage ID from a GeoPackage filename."""
    stem = Path(path).stem
    preferred = re.search(r"(?:^|[_-])gage[_-]?(\d{8,15})(?:$|[_-])", stem, re.IGNORECASE)
    if preferred:
        return preferred.group(1)
    tokens = re.findall(r"(?<!\d)(\d{8,15})(?!\d)", stem)
    if len(tokens) == 1:
        return tokens[0]
    if not tokens:
        raise ValueError(
            f"cannot find an 8- to 15-digit gage ID in filename {Path(path).name!r}"
        )
    raise ValueError(
        f"filename {Path(path).name!r} contains multiple possible gage IDs: {tokens}"
    )


def discover_gpkg_files(inputs: Iterable[str]) -> list[Path]:
    """Resolve explicit files, directories, and shell-style glob expressions."""
    files: list[Path] = []
    for value in inputs:
        path = Path(value).expanduser()
        if path.is_file():
            if path.suffix.lower() != ".gpkg":
                raise ValueError(f"input file is not a GeoPackage: {path}")
            files.append(path.resolve())
        elif path.is_dir():
            files.extend(candidate.resolve() for candidate in path.rglob("*.gpkg"))
        else:
            matches = [Path(match) for match in glob.glob(str(path), recursive=True)]
            for match in matches:
                if match.is_file() and match.suffix.lower() == ".gpkg":
                    files.append(match.resolve())
                elif match.is_dir():
                    files.extend(
                        candidate.resolve() for candidate in match.rglob("*.gpkg")
                    )
    unique = sorted(set(files))
    if not unique:
        raise FileNotFoundError("no GeoPackage files matched the supplied input")
    return unique


def hydrofabric_area_sqkm(
    gpkg_file: str | Path,
    *,
    layer: str = "divides",
    area_column: str = "areasqkm",
) -> tuple[float, int]:
    """Return total subsetter area and number of divides."""
    path = Path(gpkg_file)
    quote = lambda identifier: '"' + str(identifier).replace('"', '""') + '"'
    with sqlite3.connect(path) as connection:
        available_layers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        if layer not in available_layers:
            raise KeyError(
                f"{path.name}: no {layer!r} layer; available tables include "
                f"{sorted(available_layers)}"
            )
        available_columns = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({quote(layer)})")
        }
        if area_column not in available_columns:
            raise KeyError(
                f"{path.name}: layer {layer!r} has no {area_column!r} column; "
                f"available columns: {sorted(available_columns)}"
            )
        requested_columns = [area_column]
        if "divide_id" in available_columns:
            requested_columns.insert(0, "divide_id")
        query = (
            "SELECT " + ", ".join(quote(column) for column in requested_columns)
            + " FROM " + quote(layer)
        )
        divides = pd.read_sql_query(query, connection)

    if divides.empty:
        raise ValueError(f"{path.name}: layer {layer!r} is empty")
    if "divide_id" in divides and divides["divide_id"].duplicated().any():
        duplicate_count = int(divides["divide_id"].duplicated(keep=False).sum())
        raise ValueError(f"{path.name}: {duplicate_count} rows have duplicate divide_id values")

    areas = pd.to_numeric(divides[area_column], errors="coerce")
    if areas.isna().any():
        raise ValueError(f"{path.name}: {int(areas.isna().sum())} divides have missing/non-numeric area")
    if (areas <= 0).any():
        raise ValueError(f"{path.name}: all divide areas must be positive")
    return float(areas.sum()), int(len(areas))


def _nwis_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {"User-Agent": "hydrofabric-basin-area-check/1.0 (USGS drainage-area QA)"}
    )
    return session


def _parse_nwis_rdb(text: str) -> pd.DataFrame:
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if len(lines) < 2:
        return pd.DataFrame()
    table = pd.read_csv(StringIO("\n".join(lines)), sep="\t", dtype="string")
    if not table.empty and table.iloc[0].astype(str).str.match(r"^\d+[a-z]$").mean() > 0.5:
        table = table.iloc[1:].reset_index(drop=True)
    return table


def fetch_usgs_drainage_areas(
    gage_ids: Iterable[str],
    *,
    batch_size: int = 50,
    timeout_seconds: int = 60,
) -> pd.DataFrame:
    """Fetch NWIS station name and drainage area for each requested gage."""
    ids = sorted(set(map(str, gage_ids)))
    session = _nwis_session()
    tables: list[pd.DataFrame] = []
    batch_count = max(1, (len(ids) + batch_size - 1) // batch_size)
    print(
        f"Fetching NWIS metadata for {len(ids)} gage(s) in {batch_count} batch(es)...",
        flush=True,
    )
    for start in range(0, len(ids), batch_size):
        batch = ids[start : start + batch_size]
        response = session.get(
            NWIS_SITE_URL,
            params={
                "format": "rdb",
                "sites": ",".join(batch),
                "siteOutput": "expanded",
                "siteStatus": "all",
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        table = _parse_nwis_rdb(response.text)
        if not table.empty:
            tables.append(table)
        batch_number = start // batch_size + 1
        print(f"NWIS metadata: batch {batch_number}/{batch_count}", flush=True)

    if not tables:
        return pd.DataFrame(columns=["gage_id", "station_name", "usgs_area_sqmi", "usgs_area_sqkm"])
    sites = pd.concat(tables, ignore_index=True)
    if "agency_cd" in sites:
        sites = sites.loc[sites["agency_cd"].astype("string").str.strip().eq("USGS")]
    required = {"site_no", "station_nm", "drain_area_va"}
    missing = sorted(required - set(sites))
    if missing:
        raise KeyError(f"NWIS response is missing columns: {missing}")
    sites = sites.rename(
        columns={
            "site_no": "gage_id",
            "station_nm": "station_name",
            "drain_area_va": "usgs_area_sqmi",
        }
    )
    sites["gage_id"] = sites["gage_id"].astype("string").str.strip()
    sites["usgs_area_sqmi"] = pd.to_numeric(sites["usgs_area_sqmi"], errors="coerce")
    sites["usgs_area_sqkm"] = sites["usgs_area_sqmi"] * SQUARE_MILES_TO_SQUARE_KM
    return sites[["gage_id", "station_name", "usgs_area_sqmi", "usgs_area_sqkm"]].drop_duplicates("gage_id")


def compare_basin_areas(
    gpkg_files: Iterable[str | Path],
    *,
    threshold_pct: float,
    clean_threshold_pct: float = 10.0,
    hf_nldi_threshold_pct: float = 5.0,
    hf_nwis_fallback_threshold_pct: float = 10.0,
    layer: str = "divides",
    area_column: str = "areasqkm",
    batch_size: int = 50,
    timeout_seconds: int = 60,
    nldi_workers: int = 4,
) -> pd.DataFrame:
    """Compare hydrofabric, NLDI, and NWIS areas and classify each basin."""
    thresholds = {
        "threshold_pct": threshold_pct,
        "clean_threshold_pct": clean_threshold_pct,
        "hf_nldi_threshold_pct": hf_nldi_threshold_pct,
        "hf_nwis_fallback_threshold_pct": hf_nwis_fallback_threshold_pct,
    }
    for name, value in thresholds.items():
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite non-negative number")
    if clean_threshold_pct > threshold_pct:
        raise ValueError("clean_threshold_pct cannot exceed threshold_pct")

    records = []
    for path_value in gpkg_files:
        path = Path(path_value).resolve()
        try:
            gage_id = extract_gage_id(path)
            hf_area, n_divides = hydrofabric_area_sqkm(
                path, layer=layer, area_column=area_column
            )
            records.append(
                {
                    "gage_id": gage_id,
                    "gpkg_file": str(path),
                    "n_divides": n_divides,
                    "hydrofabric_area_sqkm": hf_area,
                    "processing_error": "",
                }
            )
        except Exception as exc:
            records.append(
                {
                    "gage_id": "",
                    "gpkg_file": str(path),
                    "n_divides": np.nan,
                    "hydrofabric_area_sqkm": np.nan,
                    "processing_error": f"{type(exc).__name__}: {exc}",
                }
            )

    local = pd.DataFrame(records)
    duplicate_ids = local.loc[local["gage_id"].ne("") & local["gage_id"].duplicated(keep=False), "gage_id"]
    if not duplicate_ids.empty:
        raise ValueError(
            "multiple GeoPackages resolve to the same gage ID: "
            + ", ".join(sorted(duplicate_ids.unique()))
        )

    query_ids = local.loc[local["gage_id"].ne(""), "gage_id"].tolist()
    usgs = fetch_usgs_drainage_areas(
        query_ids, batch_size=batch_size, timeout_seconds=timeout_seconds
    )
    nldi = fetch_nldi_basin_areas(
        query_ids,
        timeout_seconds=timeout_seconds,
        workers=nldi_workers,
    )
    result = local.merge(usgs, on="gage_id", how="left", validate="one_to_one")
    result = result.merge(nldi, on="gage_id", how="left", validate="one_to_one")

    # Preserve the original hydrofabric-minus-NWIS columns for compatibility.
    result["difference_sqkm"] = result["hydrofabric_area_sqkm"] - result["usgs_area_sqkm"]
    result["difference_pct"] = 100.0 * result["difference_sqkm"] / result["usgs_area_sqkm"]
    result["absolute_difference_pct"] = result["difference_pct"].abs()

    result["hf_nldi_difference_sqkm"] = (
        result["hydrofabric_area_sqkm"] - result["nldi_area_sqkm"]
    )
    result["hf_nldi_difference_pct"] = (
        100.0 * result["hf_nldi_difference_sqkm"] / result["nldi_area_sqkm"]
    )
    result["hf_nldi_absolute_difference_pct"] = result[
        "hf_nldi_difference_pct"
    ].abs()
    result["nldi_nwis_difference_sqkm"] = (
        result["nldi_area_sqkm"] - result["usgs_area_sqkm"]
    )
    result["nldi_nwis_difference_pct"] = (
        100.0 * result["nldi_nwis_difference_sqkm"] / result["usgs_area_sqkm"]
    )
    result["nldi_nwis_absolute_difference_pct"] = result[
        "nldi_nwis_difference_pct"
    ].abs()

    result["threshold_pct"] = float(threshold_pct)
    result["clean_threshold_pct"] = float(clean_threshold_pct)
    result["hf_nldi_threshold_pct"] = float(hf_nldi_threshold_pct)
    result["hf_nwis_fallback_threshold_pct"] = float(
        hf_nwis_fallback_threshold_pct
    )
    result["lower_allowed_sqkm"] = result["usgs_area_sqkm"] * (1.0 - threshold_pct / 100.0)
    result["upper_allowed_sqkm"] = result["usgs_area_sqkm"] * (1.0 + threshold_pct / 100.0)

    missing_usgs = result["usgs_area_sqkm"].isna() & result["processing_error"].eq("")
    missing_nldi = (
        result["nldi_area_sqkm"].isna()
        & result["processing_error"].eq("")
        & ~missing_usgs
    )
    topology_failure = result["hf_nldi_absolute_difference_pct"].gt(
        hf_nldi_threshold_pct
    )
    outlet_offset = result["nldi_nwis_absolute_difference_pct"].gt(
        clean_threshold_pct
    )
    domain_mismatch = result["nldi_nwis_absolute_difference_pct"].gt(threshold_pct)
    nldi_outlier_fallback = (
        topology_failure
        & domain_mismatch
        & result["absolute_difference_pct"].le(hf_nwis_fallback_threshold_pct)
    )

    result["status"] = "CLEAN_PASS"
    result.loc[outlet_offset, "status"] = "ACCEPTABLE_OUTLET_OFFSET"
    result.loc[domain_mismatch, "status"] = "OBSERVATION_DOMAIN_MISMATCH"
    result.loc[topology_failure, "status"] = "SUBSETTER_OR_TOPOLOGY_FAILURE"
    result.loc[
        nldi_outlier_fallback, "status"
    ] = "HF_NWIS_AGREEMENT_NLDI_OUTLIER"
    result.loc[missing_usgs, "status"] = "MISSING_USGS_AREA"
    result.loc[missing_nldi, "status"] = "MISSING_NLDI_AREA"
    result.loc[result["processing_error"].ne(""), "status"] = "ERROR"
    columns = [
        "gage_id", "station_name", "status", "threshold_pct",
        "clean_threshold_pct", "hf_nldi_threshold_pct",
        "hf_nwis_fallback_threshold_pct", "gpkg_file",
        "n_divides", "hydrofabric_area_sqkm", "usgs_area_sqmi", "usgs_area_sqkm",
        "nldi_area_sqkm",
        "difference_sqkm", "difference_pct", "absolute_difference_pct",
        "hf_nldi_difference_sqkm", "hf_nldi_difference_pct",
        "hf_nldi_absolute_difference_pct", "nldi_nwis_difference_sqkm",
        "nldi_nwis_difference_pct", "nldi_nwis_absolute_difference_pct",
        "lower_allowed_sqkm", "upper_allowed_sqkm", "processing_error",
        "nldi_error",
    ]
    return result[columns].sort_values(["status", "gage_id", "gpkg_file"]).reset_index(drop=True)


def fetch_usgs_basin_boundary(
    gage_id: str,
    *,
    session: requests.Session | None = None,
    timeout_seconds: int = 60,
    simplified: bool = True,
):
    """Return the network-derived NLDI drainage basin as a GeoDataFrame."""
    import geopandas as gpd

    cache_key = (str(gage_id), bool(simplified))
    with _NLDI_BOUNDARY_CACHE_LOCK:
        cached = _NLDI_BOUNDARY_CACHE.get(cache_key)
        full_resolution = _NLDI_BOUNDARY_CACHE.get((str(gage_id), False))
    if cached is not None:
        return cached.copy()
    if simplified and full_resolution is not None:
        boundary = full_resolution.copy()
        boundary.geometry = boundary.geometry.simplify(
            0.0001,
            preserve_topology=True,
        )
        with _NLDI_BOUNDARY_CACHE_LOCK:
            _NLDI_BOUNDARY_CACHE[cache_key] = boundary
        return boundary.copy()

    session = session or _nwis_session()
    response = session.get(
        NLDI_BASIN_URL.format(gage_id=gage_id),
        params={"f": "json", "simplified": str(simplified).lower()},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features", [])
    if not features:
        raise ValueError(f"NLDI returned no basin boundary for USGS-{gage_id}")
    boundary = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    if boundary.empty or boundary.geometry.isna().all():
        raise ValueError(f"NLDI returned an empty basin boundary for USGS-{gage_id}")
    with _NLDI_BOUNDARY_CACHE_LOCK:
        _NLDI_BOUNDARY_CACHE[cache_key] = boundary
    return boundary.copy()


def fetch_nldi_feature(
    gage_id: str,
    *,
    session: requests.Session | None = None,
    timeout_seconds: int = 60,
) -> dict:
    """Return the NLDI feature properties for an NWIS gage."""
    session = session or _nwis_session()
    response = session.get(
        NLDI_FEATURE_URL.format(gage_id=gage_id),
        params={"f": "json"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    features = response.json().get("features", [])
    if len(features) != 1:
        raise ValueError(
            f"NLDI returned {len(features)} feature records for USGS-{gage_id}"
        )
    return features[0].get("properties", {})


def basin_boundary_area_sqkm(boundary) -> float:
    """Calculate geodesic area of an NLDI basin boundary in square kilometers."""
    from pyproj import Geod

    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:4326")
    boundary = boundary.to_crs("EPSG:4326")
    geod = Geod(ellps="WGS84")
    areas = [
        abs(geod.geometry_area_perimeter(geometry)[0])
        for geometry in boundary.geometry
        if geometry is not None and not geometry.is_empty
    ]
    if not areas:
        raise ValueError("NLDI basin boundary has no valid geometry")
    return float(sum(areas) / 1_000_000.0)


def fetch_nldi_basin_areas(
    gage_ids: Iterable[str],
    *,
    timeout_seconds: int = 60,
    workers: int = 4,
) -> pd.DataFrame:
    """Fetch full-resolution NLDI basins and calculate their geodesic areas."""
    ids = sorted(set(map(str, gage_ids)))
    if workers < 1:
        raise ValueError("NLDI workers must be at least 1")
    print(
        f"Fetching full-resolution NLDI basins for {len(ids)} gage(s) "
        f"with {workers} worker(s)...",
        flush=True,
    )

    def fetch_one(gage_id: str) -> dict:
        try:
            boundary = fetch_usgs_basin_boundary(
                gage_id,
                timeout_seconds=timeout_seconds,
                simplified=False,
            )
            return {
                "gage_id": gage_id,
                "nldi_area_sqkm": basin_boundary_area_sqkm(boundary),
                "nldi_error": "",
            }
        except Exception as exc:
            return {
                "gage_id": gage_id,
                "nldi_area_sqkm": np.nan,
                "nldi_error": f"{type(exc).__name__}: {exc}",
            }

    records = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_one, gage_id): gage_id for gage_id in ids}
        for completed, future in enumerate(as_completed(futures), start=1):
            records.append(future.result())
            if completed % 25 == 0 or completed == len(ids):
                print(f"Retrieved NLDI basins: {completed}/{len(ids)}", flush=True)
    return pd.DataFrame(
        records,
        columns=["gage_id", "nldi_area_sqkm", "nldi_error"],
    )


def identify_divides_outside_boundary(
    gpkg_file: str | Path,
    boundary,
    *,
    outside_fraction_pct: float = 50.0,
    minimum_outside_area_sqkm: float = 0.1,
) -> pd.DataFrame:
    """Measure divides outside NLDI and flag safe cleanup candidates.

    Partially intersecting divides must satisfy both configured thresholds.
    Effectively fully external divides bypass the minimum-area threshold so a
    tiny external connector cannot block deletion of the surrounding branch.
    """
    import geopandas as gpd

    if not 0.0 <= outside_fraction_pct <= 100.0:
        raise ValueError("outside_fraction_pct must be between 0 and 100")
    if minimum_outside_area_sqkm < 0 or not np.isfinite(minimum_outside_area_sqkm):
        raise ValueError("minimum_outside_area_sqkm must be finite and non-negative")

    divides = gpd.read_file(gpkg_file, layer="divides")
    if "divide_id" not in divides:
        raise KeyError(f"{Path(gpkg_file).name}: divides layer has no 'divide_id'")
    if divides["divide_id"].isna().any() or divides["divide_id"].duplicated().any():
        raise ValueError(f"{Path(gpkg_file).name}: divide_id values must be unique and non-null")
    if divides.crs is None:
        raise ValueError(f"{Path(gpkg_file).name}: divides layer has no CRS")
    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:4326")

    equal_area_crs = "EPSG:6933"
    divides_equal_area = divides.to_crs(equal_area_crs)
    boundary_equal_area = boundary.to_crs(equal_area_crs)
    boundary_union = (
        boundary_equal_area.geometry.union_all()
        if hasattr(boundary_equal_area.geometry, "union_all")
        else boundary_equal_area.geometry.unary_union
    )
    total_area_sqkm = divides_equal_area.geometry.area / 1_000_000.0
    outside_geometry = divides_equal_area.geometry.difference(boundary_union)
    outside_area_sqkm = outside_geometry.area / 1_000_000.0
    outside_fraction = 100.0 * outside_area_sqkm / total_area_sqkm
    fully_outside = outside_fraction.ge(99.999)
    flagged = outside_fraction.ge(outside_fraction_pct) & (
        outside_area_sqkm.ge(minimum_outside_area_sqkm) | fully_outside
    )
    relation = np.select(
        [outside_fraction.ge(99.999), outside_fraction.gt(0.001)],
        ["OUTSIDE", "PARTIAL"],
        default="INSIDE",
    )
    return pd.DataFrame(
        {
            "divide_id": divides["divide_id"].astype(str),
            "divide_area_sqkm": total_area_sqkm.to_numpy(),
            "outside_area_sqkm": outside_area_sqkm.to_numpy(),
            "outside_fraction_pct": outside_fraction.to_numpy(),
            "boundary_relation": relation,
            "delete": flagged.to_numpy(dtype=bool),
        }
    ).sort_values(
        ["delete", "outside_area_sqkm", "divide_id"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    escaped = table.replace('"', '""')
    return {
        row[1] for row in connection.execute(f'PRAGMA table_info("{escaped}")')
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone() is not None


def _drop_spatial_update_triggers(
    connection: sqlite3.Connection,
    tables: Iterable[str],
) -> list[tuple[str, str]]:
    table_names = tuple(tables)
    if not table_names:
        return []
    placeholders = ",".join("?" for _ in table_names)
    triggers = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
        f"AND tbl_name IN ({placeholders}) AND name LIKE 'rtree_%_update%'",
        table_names,
    ).fetchall()
    for name, _ in triggers:
        escaped = name.replace('"', '""')
        connection.execute(f'DROP TRIGGER "{escaped}"')
    return triggers


def _restore_triggers(
    connection: sqlite3.Connection,
    triggers: Iterable[tuple[str, str]],
) -> None:
    for _, sql in triggers:
        connection.execute(sql)


def _recalculate_accumulated_areas(connection: sqlite3.Connection) -> None:
    """Recalculate flowpath accumulated drainage areas after branch removal."""
    if not (_table_exists(connection, "flowpaths") and _table_exists(connection, "nexus")):
        return
    flowpaths = pd.read_sql_query(
        "SELECT id, toid, divide_id, areasqkm FROM flowpaths",
        connection,
    )
    nexus = pd.read_sql_query("SELECT id, toid FROM nexus", connection)
    if flowpaths.empty:
        return
    local_area = dict(
        zip(
            flowpaths["id"].astype(str),
            pd.to_numeric(flowpaths["areasqkm"], errors="coerce").fillna(0.0),
        )
    )
    nexus_downstream = dict(zip(nexus["id"].astype(str), nexus["toid"]))
    upstream: dict[str, list[str]] = {flowpath_id: [] for flowpath_id in local_area}
    for row in flowpaths.itertuples(index=False):
        downstream = nexus_downstream.get(str(row.toid))
        if pd.notna(downstream) and str(downstream) in upstream:
            upstream[str(downstream)].append(str(row.id))

    accumulated: dict[str, float] = {}
    visiting: set[str] = set()

    def total(flowpath_id: str) -> float:
        if flowpath_id in accumulated:
            return accumulated[flowpath_id]
        if flowpath_id in visiting:
            raise ValueError(f"cycle detected in flowpath network at {flowpath_id}")
        visiting.add(flowpath_id)
        value = float(local_area[flowpath_id]) + sum(
            total(upstream_id) for upstream_id in upstream[flowpath_id]
        )
        visiting.remove(flowpath_id)
        accumulated[flowpath_id] = value
        return value

    for flowpath_id in local_area:
        total(flowpath_id)

    updates = [(value, flowpath_id) for flowpath_id, value in accumulated.items()]
    spatial_update_triggers = _drop_spatial_update_triggers(
        connection, ("divides", "flowpaths")
    )
    try:
        if "tot_drainage_areasqkm" in _table_columns(connection, "flowpaths"):
            connection.executemany(
                "UPDATE flowpaths SET tot_drainage_areasqkm = ? WHERE id = ?",
                updates,
            )
        if _table_exists(connection, "network"):
            if "tot_drainage_areasqkm" in _table_columns(connection, "network"):
                connection.executemany(
                    'UPDATE network SET tot_drainage_areasqkm = ? WHERE id = ?',
                    updates,
                )
        if _table_exists(connection, "divides"):
            divide_updates = [
                (accumulated[str(row.id)], str(row.divide_id))
                for row in flowpaths.itertuples(index=False)
                if pd.notna(row.divide_id) and str(row.id) in accumulated
            ]
            if "tot_drainage_areasqkm" in _table_columns(connection, "divides"):
                connection.executemany(
                    "UPDATE divides SET tot_drainage_areasqkm = ? WHERE divide_id = ?",
                    divide_updates,
                )
    finally:
        _restore_triggers(connection, spatial_update_triggers)


def _migrate_removed_gage_associations(
    connection: sqlite3.Connection,
    *,
    gage_id: str | None,
    nldi_comid: int | None,
) -> list[str]:
    """Move a gage POI from a removed branch to its NLDI-indexed flowpath."""
    if not _table_exists(connection, "flowpaths"):
        return []
    flowpath_columns = _table_columns(connection, "flowpaths")
    if "poi_id" not in flowpath_columns:
        return []
    protected = connection.execute(
        "SELECT id, poi_id, toid FROM flowpaths WHERE id IN "
        "(SELECT id FROM remove_flowpaths) AND poi_id IS NOT NULL "
        "AND trim(poi_id) <> ''"
    ).fetchall()
    if not protected:
        return []
    if not gage_id or nldi_comid is None or not _table_exists(connection, "network"):
        raise ValueError(
            "outside branch contains a gage POI, but an NLDI COMID mapping "
            "is unavailable for safe reassignment"
        )

    migrations: list[tuple[str, str, str]] = []
    for removed_id, poi_id, removed_toid in protected:
        source_gage = ""
        source_nexus = removed_toid
        attribute_id_column = None
        if _table_exists(connection, "flowpath-attributes"):
            attribute_columns = _table_columns(connection, "flowpath-attributes")
            attribute_id_column = (
                "id" if "id" in attribute_columns else "link"
            )
            if attribute_id_column in attribute_columns and "gage" in attribute_columns:
                selected_columns = (
                    "gage, gage_nex_id"
                    if "gage_nex_id" in attribute_columns
                    else "gage"
                )
                source = connection.execute(
                    f'SELECT {selected_columns} FROM "flowpath-attributes" '
                    f'WHERE "{attribute_id_column}" = ? LIMIT 1',
                    (str(removed_id),),
                ).fetchone()
                source_gage = str(source[0]).strip() if source and source[0] else ""
                if source and len(source) > 1 and source[1]:
                    source_nexus = source[1]
        target_uri = f"gages-{gage_id}"
        mapped_to_target = False
        if "hl_uri" in _table_columns(connection, "network"):
            mapped_to_target = connection.execute(
                "SELECT 1 FROM network WHERE id = ? AND hl_uri = ? LIMIT 1",
                (str(removed_id), target_uri),
            ).fetchone() is not None
        is_target_gage = source_gage == str(gage_id) or mapped_to_target

        if not is_target_gage:
            triggers = _drop_spatial_update_triggers(connection, ("flowpaths",))
            try:
                connection.execute(
                    "UPDATE flowpaths SET poi_id = '' WHERE id = ?",
                    (str(removed_id),),
                )
            finally:
                _restore_triggers(connection, triggers)
            continue

        candidates = connection.execute(
            "SELECT DISTINCT n.id FROM network n JOIN flowpaths f ON n.id = f.id "
            "WHERE CAST(n.hf_id AS INTEGER) = ? "
            "AND n.id NOT IN (SELECT id FROM remove_flowpaths) AND f.toid = ?",
            (int(nldi_comid), removed_toid),
        ).fetchall()
        candidate_ids = sorted({str(row[0]) for row in candidates})
        if len(candidate_ids) != 1:
            raise ValueError(
                f"gage POI on {removed_id} maps to {len(candidate_ids)} retained "
                f"flowpaths for NLDI COMID {nldi_comid}: {candidate_ids}"
            )
        target_id = candidate_ids[0]
        existing_poi = connection.execute(
            "SELECT poi_id FROM flowpaths WHERE id = ?", (target_id,)
        ).fetchone()[0]
        if existing_poi is not None and str(existing_poi).strip() not in {"", str(poi_id)}:
            raise ValueError(
                f"NLDI-indexed flowpath {target_id} already has a different POI: "
                f"{existing_poi}"
            )
        migrations.append((str(removed_id), target_id, str(poi_id)))

        triggers = _drop_spatial_update_triggers(connection, ("flowpaths",))
        try:
            connection.execute(
                "UPDATE flowpaths SET poi_id = ? WHERE id = ?",
                (str(poi_id), target_id),
            )
            connection.execute(
                "UPDATE flowpaths SET poi_id = '' WHERE id = ?",
                (str(removed_id),),
            )
        finally:
            _restore_triggers(connection, triggers)

        if attribute_id_column is not None:
            columns = _table_columns(connection, "flowpath-attributes")
            if "gage" in columns:
                source_gage = source_gage or str(gage_id)
                if "gage_nex_id" in columns:
                    connection.execute(
                        f'UPDATE "flowpath-attributes" SET gage = ?, gage_nex_id = ? '
                        f'WHERE "{attribute_id_column}" = ?',
                        (source_gage, source_nexus, target_id),
                    )
                    connection.execute(
                        f'UPDATE "flowpath-attributes" SET gage = ?, gage_nex_id = ? '
                        f'WHERE "{attribute_id_column}" = ?',
                        ("", "", str(removed_id)),
                    )
                else:
                    connection.execute(
                        f'UPDATE "flowpath-attributes" SET gage = ? '
                        f'WHERE "{attribute_id_column}" = ?',
                        (source_gage, target_id),
                    )
    return [f"{removed_id}->{target_id}" for removed_id, target_id, _ in migrations]


def write_cleaned_hydrofabric(
    source_gpkg: str | Path,
    output_gpkg: str | Path,
    divide_ids: Iterable[str],
    *,
    overwrite: bool = False,
    gage_id: str | None = None,
    nldi_comid: int | None = None,
) -> dict:
    """Copy a hydrofabric and remove flagged divides and associated features."""
    source = Path(source_gpkg).expanduser().resolve()
    output = Path(output_gpkg).expanduser().resolve()
    removed_divides = sorted(set(map(str, divide_ids)))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise FileExistsError(f"cleaned GeoPackage already exists: {output}")
    shutil.copy2(source, output)
    if not removed_divides:
        return {
            "cleaned_gpkg_file": str(output),
            "removed_divide_count": 0,
            "removed_flowpath_count": 0,
            "gage_flowpath_migrations": "",
        }

    try:
        with sqlite3.connect(output) as connection:
            gage_migrations: list[str] = []
            connection.execute("CREATE TEMP TABLE remove_divides (divide_id TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO remove_divides VALUES (?)",
                [(divide_id,) for divide_id in removed_divides],
            )
            connection.execute("CREATE TEMP TABLE remove_flowpaths (id TEXT PRIMARY KEY)")
            if _table_exists(connection, "flowpaths"):
                connection.execute(
                    "INSERT OR IGNORE INTO remove_flowpaths "
                    "SELECT id FROM flowpaths WHERE divide_id IN "
                    "(SELECT divide_id FROM remove_divides)"
                )

                gage_migrations = _migrate_removed_gage_associations(
                    connection,
                    gage_id=gage_id,
                    nldi_comid=nldi_comid,
                )

                protected = []
                if "poi_id" in _table_columns(connection, "flowpaths"):
                    protected = connection.execute(
                        "SELECT id FROM flowpaths WHERE id IN "
                        "(SELECT id FROM remove_flowpaths) AND poi_id IS NOT NULL "
                        "AND trim(poi_id) <> ''"
                    ).fetchall()
                if protected:
                    raise ValueError(
                        "refusing to remove flowpath(s) containing a point of interest: "
                        + ", ".join(row[0] for row in protected)
                    )
                if _table_exists(connection, "flowpath-attributes"):
                    attribute_columns = _table_columns(
                        connection, "flowpath-attributes"
                    )
                    id_column = "id" if "id" in attribute_columns else "link"
                    if id_column in attribute_columns and "gage" in attribute_columns:
                        if gage_id:
                            protected = connection.execute(
                                f'SELECT "{id_column}" FROM "flowpath-attributes" '
                                f'WHERE "{id_column}" IN '
                                "(SELECT id FROM remove_flowpaths) AND trim(gage) = ?",
                                (str(gage_id),),
                            ).fetchall()
                        else:
                            protected = connection.execute(
                                f'SELECT "{id_column}" FROM "flowpath-attributes" '
                                f'WHERE "{id_column}" IN '
                                "(SELECT id FROM remove_flowpaths) AND gage IS NOT NULL "
                                "AND trim(gage) <> ?",
                                ("",),
                            ).fetchall()
                        if protected:
                            raise ValueError(
                                "refusing to remove calibrated gage flowpath(s): "
                                + ", ".join(row[0] for row in protected)
                            )

                severed = []
                if _table_exists(connection, "nexus"):
                    severed = connection.execute(
                        "SELECT DISTINCT retained.id, retained.toid, n.toid "
                        "FROM flowpaths retained JOIN nexus n ON retained.toid = n.id "
                        "WHERE retained.id NOT IN (SELECT id FROM remove_flowpaths) "
                        "AND n.toid IN (SELECT id FROM remove_flowpaths)"
                    ).fetchall()
                if severed:
                    raise ValueError(
                        "refusing cleanup because removal would sever retained downstream "
                        "connectivity at flowpath(s): "
                        + ", ".join(row[0] for row in severed)
                    )

            removed_flowpath_count = connection.execute(
                "SELECT count(*) FROM remove_flowpaths"
            ).fetchone()[0]
            if _table_exists(connection, "divide-attributes"):
                connection.execute(
                    'DELETE FROM "divide-attributes" WHERE divide_id IN '
                    "(SELECT divide_id FROM remove_divides)"
                )
            if _table_exists(connection, "flowpath-attributes"):
                columns = _table_columns(connection, "flowpath-attributes")
                identifiers = [column for column in ("id", "link") if column in columns]
                if identifiers:
                    condition = " OR ".join(
                        f'"{column}" IN (SELECT id FROM remove_flowpaths)'
                        for column in identifiers
                    )
                    connection.execute(
                        f'DELETE FROM "flowpath-attributes" WHERE {condition}'
                    )
            if _table_exists(connection, "network"):
                connection.execute(
                    "DELETE FROM network WHERE divide_id IN "
                    "(SELECT divide_id FROM remove_divides) OR id IN "
                    "(SELECT id FROM remove_flowpaths)"
                )
            if _table_exists(connection, "flowpaths"):
                connection.execute(
                    "DELETE FROM flowpaths WHERE id IN (SELECT id FROM remove_flowpaths)"
                )
            deleted_divide_count = connection.execute(
                "SELECT count(*) FROM divides WHERE divide_id IN "
                "(SELECT divide_id FROM remove_divides)"
            ).fetchone()[0]
            connection.execute(
                "DELETE FROM divides WHERE divide_id IN (SELECT divide_id FROM remove_divides)"
            )
            if deleted_divide_count != len(removed_divides):
                raise ValueError(
                    f"requested {len(removed_divides)} divide deletions but found "
                    f"{deleted_divide_count}"
                )
            _recalculate_accumulated_areas(connection)
            if _table_exists(connection, "nexus"):
                connection.execute(
                    "DELETE FROM nexus WHERE (poi_id IS NULL OR trim(poi_id) = '') "
                    "AND id NOT IN (SELECT toid FROM flowpaths WHERE toid IS NOT NULL) "
                    "AND (toid IS NULL OR toid NOT IN (SELECT id FROM flowpaths))"
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"GeoPackage integrity check failed: {integrity}")
        return {
            "cleaned_gpkg_file": str(output),
            "removed_divide_count": deleted_divide_count,
            "removed_flowpath_count": removed_flowpath_count,
            "gage_flowpath_migrations": ",".join(gage_migrations),
        }
    except Exception:
        output.unlink(missing_ok=True)
        raise


def generate_cleaned_hydrofabrics(
    result: pd.DataFrame,
    output_dir: str | Path,
    *,
    rejected_dir: str | Path | None = None,
    outside_fraction_pct: float = 50.0,
    minimum_outside_area_sqkm: float = 0.1,
    overwrite: bool = False,
    timeout_seconds: int = 60,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Write accepted and rejected GeoPackages to separate directories."""
    output_dir = Path(output_dir).expanduser().resolve()
    rejected_dir = (
        Path(rejected_dir).expanduser().resolve()
        if rejected_dir is not None
        else output_dir.parent / "rejected_hydrofabric"
    )
    if rejected_dir == output_dir:
        raise ValueError("rejected_dir must differ from the accepted output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    result = result.copy()
    result["cleaned_gpkg_file"] = ""
    result["removed_divide_count"] = 0
    result["removed_flowpath_count"] = 0
    result["removed_area_sqkm"] = 0.0
    result["corrected_hydrofabric_area_sqkm"] = np.nan
    result["corrected_hf_nldi_difference_pct"] = np.nan
    result["corrected_hf_nwis_difference_pct"] = np.nan
    result["cleaned_status"] = result["status"]
    result["removed_divide_ids"] = ""
    result["gage_flowpath_migrations"] = ""
    result["cleanup_error"] = ""
    result["output_disposition"] = "skipped"
    removed_records: list[dict] = []
    session = _nwis_session()
    total = len(result)
    print(
        f"Cleaning {total} hydrofabric GeoPackage(s) into {output_dir}...",
        flush=True,
    )

    for position, (index, row) in enumerate(result.iterrows(), start=1):
        gage_label = str(row["gage_id"] or Path(row["gpkg_file"]).name)
        started = time.perf_counter()
        print(f"Cleanup [{position}/{total}] {gage_label}: starting", flush=True)
        if not row["gage_id"] or row["processing_error"] or pd.isna(row["nldi_area_sqkm"]):
            print(
                f"Cleanup [{position}/{total}] {gage_label}: skipped "
                "because required basin information is unavailable",
                flush=True,
            )
            continue
        generated_gpkg: Path | None = None
        try:
            boundary = fetch_usgs_basin_boundary(
                str(row["gage_id"]),
                session=session,
                timeout_seconds=timeout_seconds,
                simplified=False,
            )
            divide_audit = identify_divides_outside_boundary(
                row["gpkg_file"],
                boundary,
                outside_fraction_pct=outside_fraction_pct,
                minimum_outside_area_sqkm=minimum_outside_area_sqkm,
            )
            flagged = divide_audit.loc[divide_audit["delete"]].copy()
            divide_ids = flagged["divide_id"].astype(str).tolist()
            nldi_comid = None
            if divide_ids:
                feature = fetch_nldi_feature(
                    str(row["gage_id"]),
                    session=session,
                    timeout_seconds=timeout_seconds,
                )
                if feature.get("comid") is not None:
                    nldi_comid = int(feature["comid"])
            output_gpkg = output_dir / Path(row["gpkg_file"]).name
            cleanup = write_cleaned_hydrofabric(
                row["gpkg_file"],
                output_gpkg,
                divide_ids,
                overwrite=overwrite,
                gage_id=str(row["gage_id"]),
                nldi_comid=nldi_comid,
            )
            generated_gpkg = Path(cleanup["cleaned_gpkg_file"])
            corrected_area, _ = hydrofabric_area_sqkm(output_gpkg)
            corrected_difference_pct = (
                100.0 * (corrected_area - row["nldi_area_sqkm"])
                / row["nldi_area_sqkm"]
            )
            corrected_hf_nwis_difference_pct = (
                100.0 * (corrected_area - row["usgs_area_sqkm"])
                / row["usgs_area_sqkm"]
            )
            cleaned_status = _classification(
                abs(corrected_difference_pct),
                row["nldi_nwis_absolute_difference_pct"],
                abs(corrected_hf_nwis_difference_pct),
                hf_nldi_threshold_pct=row["hf_nldi_threshold_pct"],
                clean_threshold_pct=row["clean_threshold_pct"],
                threshold_pct=row["threshold_pct"],
                hf_nwis_fallback_threshold_pct=row[
                    "hf_nwis_fallback_threshold_pct"
                ],
            )
            accepted = cleaned_status in SELECTED_STATUSES
            if accepted:
                stale_rejected = rejected_dir / generated_gpkg.name
                if stale_rejected.exists() and overwrite:
                    stale_rejected.unlink()
                final_gpkg = generated_gpkg
                disposition = "selected"
            else:
                final_gpkg = rejected_dir / generated_gpkg.name
                if final_gpkg.exists():
                    if not overwrite:
                        raise FileExistsError(
                            f"rejected GeoPackage already exists: {final_gpkg}"
                        )
                    final_gpkg.unlink()
                generated_gpkg.replace(final_gpkg)
                disposition = "rejected"
            cleanup["cleaned_gpkg_file"] = str(final_gpkg)
            generated_gpkg = final_gpkg
            result.at[index, "cleaned_gpkg_file"] = str(final_gpkg)
            result.at[index, "removed_divide_count"] = cleanup["removed_divide_count"]
            result.at[index, "removed_flowpath_count"] = cleanup["removed_flowpath_count"]
            result.at[index, "removed_area_sqkm"] = flagged["divide_area_sqkm"].sum()
            result.at[index, "corrected_hydrofabric_area_sqkm"] = corrected_area
            result.at[index, "corrected_hf_nldi_difference_pct"] = corrected_difference_pct
            result.at[index, "corrected_hf_nwis_difference_pct"] = (
                corrected_hf_nwis_difference_pct
            )
            result.at[index, "cleaned_status"] = cleaned_status
            result.at[index, "output_disposition"] = disposition
            result.at[index, "removed_divide_ids"] = ",".join(divide_ids)
            result.at[index, "gage_flowpath_migrations"] = cleanup[
                "gage_flowpath_migrations"
            ]
            for record in flagged.to_dict("records"):
                removed_records.append(
                    {
                        "gage_id": str(row["gage_id"]),
                        "source_gpkg_file": row["gpkg_file"],
                        "cleaned_gpkg_file": cleanup["cleaned_gpkg_file"],
                        **record,
                    }
                )
            elapsed = time.perf_counter() - started
            print(
                f"Cleanup [{position}/{total}] {gage_label}: removed "
                f"{len(divide_ids)} divide(s), {cleaned_status}, "
                f"{disposition}, {elapsed:.1f}s",
                flush=True,
            )
        except Exception as exc:
            if generated_gpkg is not None:
                generated_gpkg.unlink(missing_ok=True)
            result.at[index, "cleaned_status"] = "CLEANUP_ERROR"
            result.at[index, "output_disposition"] = "cleanup_error"
            result.at[index, "cleanup_error"] = f"{type(exc).__name__}: {exc}"
            print(
                f"WARNING: cleanup failed for {row['gage_id']}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    removed = pd.DataFrame(
        removed_records,
        columns=[
            "gage_id", "source_gpkg_file", "cleaned_gpkg_file", "divide_id",
            "divide_area_sqkm", "outside_area_sqkm", "outside_fraction_pct",
            "boundary_relation", "delete",
        ],
    )
    return result, removed


def plot_basin_boundary_comparison(
    comparison_row: pd.Series,
    output_file: str | Path | None = None,
    *,
    usgs_boundary=None,
    timeout_seconds: int = 60,
    pdf_pages=None,
) -> Path | None:
    """Plot a USGS NLDI basin boundary over hydrofabric spatial layers."""
    import matplotlib

    matplotlib.use("Agg")
    import geopandas as gpd
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    gage_id = str(comparison_row["gage_id"])
    gpkg_file = Path(comparison_row["gpkg_file"])
    boundary = (
        usgs_boundary
        if usgs_boundary is not None
        else fetch_usgs_basin_boundary(
            gage_id,
            timeout_seconds=timeout_seconds,
        )
    )
    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:4326")

    divides = gpd.read_file(gpkg_file, layer="divides").to_crs(boundary.crs)
    if divides.empty:
        raise ValueError(f"{gpkg_file.name}: divides layer is empty")

    optional_layers = {}
    with sqlite3.connect(gpkg_file) as connection:
        available = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
    for layer in ("flowpaths", "nexus"):
        if layer in available:
            frame = gpd.read_file(gpkg_file, layer=layer)
            if not frame.empty:
                optional_layers[layer] = frame.to_crs(boundary.crs)

    fig, ax = plt.subplots(figsize=(10, 8), constrained_layout=True)
    divides.plot(
        ax=ax,
        facecolor="#9ecae1",
        edgecolor="#2171b5",
        linewidth=0.7,
        alpha=0.38,
        zorder=1,
    )
    if "flowpaths" in optional_layers:
        optional_layers["flowpaths"].plot(
            ax=ax,
            color="#238b45",
            linewidth=0.55,
            alpha=0.85,
            zorder=2,
        )
    if "nexus" in optional_layers:
        optional_layers["nexus"].plot(
            ax=ax,
            color="#252525",
            markersize=4,
            alpha=0.75,
            zorder=3,
        )
    boundary.boundary.plot(
        ax=ax,
        color="#cb181d",
        linewidth=2.1,
        zorder=4,
    )
    removed_ids = {
        value for value in str(comparison_row.get("removed_divide_ids", "")).split(",")
        if value
    }
    if removed_ids and "divide_id" in divides:
        removed_divides = divides.loc[divides["divide_id"].astype(str).isin(removed_ids)]
        for divide_id, point in zip(
            removed_divides["divide_id"].astype(str),
            removed_divides.geometry.representative_point(),
        ):
            ax.text(
                point.x, point.y, divide_id,
                color="#7f0000", fontsize=7, ha="center", va="center",
                bbox={"facecolor": "white", "edgecolor": "#cb181d", "alpha": 0.75},
                zorder=6,
            )

    combined_bounds = np.vstack([divides.total_bounds, boundary.total_bounds])
    minx, miny = combined_bounds[:, :2].min(axis=0)
    maxx, maxy = combined_bounds[:, 2:].max(axis=0)
    margin_x = max((maxx - minx) * 0.08, 0.01)
    margin_y = max((maxy - miny) * 0.08, 0.01)
    ax.set_xlim(minx - margin_x, maxx + margin_x)
    ax.set_ylim(miny - margin_y, maxy + margin_y)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(linestyle=":", alpha=0.25)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    station = comparison_row.get("station_name")
    station = "" if pd.isna(station) else str(station)
    ax.set_title(
        f"USGS {gage_id} — {station}\n"
        "Hydrofabric and NLDI network-derived basin"
    )
    annotation = (
        f"Hydrofabric: {comparison_row['hydrofabric_area_sqkm']:.2f} km²\n"
        f"NLDI: {comparison_row['nldi_area_sqkm']:.2f} km²\n"
        f"NWIS documented: {comparison_row['usgs_area_sqkm']:.2f} km²\n"
        f"HF–NLDI: {comparison_row['hf_nldi_difference_pct']:+.2f}% "
        f"(±{comparison_row['hf_nldi_threshold_pct']:.1f}%)\n"
        f"NLDI–NWIS: {comparison_row['nldi_nwis_difference_pct']:+.2f}% "
        f"(clean ≤{comparison_row['clean_threshold_pct']:.1f}%, "
        f"maximum ≤{comparison_row['threshold_pct']:.1f}%)\n"
        f"HF–NWIS: {comparison_row['difference_pct']:+.2f}% "
        f"(fallback ≤{comparison_row.get('hf_nwis_fallback_threshold_pct', 10.0):.1f}%)\n"
        f"[{comparison_row['status']}]"
    )
    if comparison_row.get("cleaned_gpkg_file", ""):
        annotation += (
            f"\nRemoved divides: {int(comparison_row['removed_divide_count'])} "
            f"({comparison_row['removed_area_sqkm']:.2f} km²)\n"
            f"Corrected HF–NLDI: "
            f"{comparison_row['corrected_hf_nldi_difference_pct']:+.2f}% "
            f"| HF–NWIS: "
            f"{comparison_row['corrected_hf_nwis_difference_pct']:+.2f}% "
            f"[{comparison_row['cleaned_status']}]"
        )
    ax.text(
        0.015,
        0.015,
        annotation,
        transform=ax.transAxes,
        va="bottom",
        ha="left",
        fontsize=9,
        bbox={"facecolor": "white", "edgecolor": "#777777", "alpha": 0.9},
        zorder=5,
    )
    handles = [
        Patch(facecolor="#9ecae1", edgecolor="#2171b5", alpha=0.5, label="Hydrofabric divides"),
        Line2D(
            [0], [0], color="#cb181d", linewidth=2.1,
            label="NLDI network-derived basin",
        ),
    ]
    if "flowpaths" in optional_layers:
        handles.append(Line2D([0], [0], color="#238b45", linewidth=1.2, label="Hydrofabric flowpaths"))
    if "nexus" in optional_layers:
        handles.append(Line2D([0], [0], marker="o", color="none", markerfacecolor="#252525", markersize=5, label="Hydrofabric nexus"))
    ax.legend(handles=handles, loc="upper right", fontsize=9)

    if output_file is None and pdf_pages is None:
        raise ValueError("output_file or pdf_pages must be provided")
    output = None
    if output_file is not None:
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=300, bbox_inches="tight")
    if pdf_pages is not None:
        pdf_pages.savefig(fig, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return output.resolve() if output is not None else None


def generate_boundary_figures(
    result: pd.DataFrame,
    figure_dir: str | Path,
    *,
    figure_format: str = "jpeg",
    figure_scope: str = "all",
    timeout_seconds: int = 60,
) -> pd.DataFrame:
    """Generate one boundary-comparison figure per comparable GeoPackage."""
    figure_format = figure_format.lower()
    if figure_format not in {"pdf", "jpeg"}:
        raise ValueError("figure_format must be one of: pdf, jpeg")
    if figure_scope not in {"all", "attention"}:
        raise ValueError("figure_scope must be one of: all, attention")
    output_dir = Path(figure_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result = result.copy()
    result["figure_file"] = ""
    result["figure_page"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["visualization_error"] = ""
    session = _nwis_session()
    priority = {
        "SUBSETTER_OR_TOPOLOGY_FAILURE": 0,
        "OBSERVATION_DOMAIN_MISMATCH": 1,
        "ERROR": 2,
        "MISSING_USGS_AREA": 3,
        "MISSING_NLDI_AREA": 4,
        "HF_NWIS_AGREEMENT_NLDI_OUTLIER": 5,
        "ACCEPTABLE_OUTLET_OFFSET": 6,
        "CLEAN_PASS": 7,
    }
    ordered_indices = sorted(
        result.index,
        key=lambda index: (
            priority.get(str(result.at[index, "status"]), 4),
            str(result.at[index, "gage_id"]),
        ),
    )
    if figure_scope == "attention":
        ordered_indices = [
            index
            for index in ordered_indices
            if (
                str(result.at[index, "status"]) not in SELECTED_STATUSES
                or str(result.at[index, "status"])
                == "HF_NWIS_AGREEMENT_NLDI_OUTLIER"
                or (
                    "cleaned_status" in result
                    and str(result.at[index, "cleaned_status"])
                    not in SELECTED_STATUSES
                )
                or (
                    "removed_divide_count" in result
                    and int(result.at[index, "removed_divide_count"] or 0) > 0
                )
                or (
                    "cleanup_error" in result
                    and bool(result.at[index, "cleanup_error"])
                )
            )
        ]

    pdf = None
    consolidated_pdf = output_dir / "basin_boundary_comparisons.pdf"
    if figure_format == "pdf":
        from matplotlib.backends.backend_pdf import PdfPages

        pdf = PdfPages(consolidated_pdf)
    page_number = 0
    total = len(ordered_indices)
    print(
        f"Rendering {total} boundary comparison(s) as {figure_format}...",
        flush=True,
    )
    try:
        for position, index in enumerate(ordered_indices, start=1):
            row = result.loc[index]
            gage_label = str(row["gage_id"] or Path(row["gpkg_file"]).name)
            if not row["gage_id"] or row["processing_error"]:
                print(
                    f"Figure [{position}/{total}] {gage_label}: skipped",
                    flush=True,
                )
                continue
            print(
                f"Figure [{position}/{total}] {gage_label}: rendering",
                flush=True,
            )
            output = (
                None
                if figure_format == "pdf"
                else output_dir / f"basin_boundary_{row['gage_id']}.jpeg"
            )
            try:
                boundary = fetch_usgs_basin_boundary(
                    str(row["gage_id"]),
                    session=session,
                    timeout_seconds=timeout_seconds,
                )
                saved = plot_basin_boundary_comparison(
                    row,
                    output,
                    usgs_boundary=boundary,
                    timeout_seconds=timeout_seconds,
                    pdf_pages=pdf,
                )
                page_number += 1
                result.at[index, "figure_file"] = str(
                    consolidated_pdf.resolve() if pdf is not None else saved
                )
                result.at[index, "figure_page"] = page_number
                print(
                    f"Figure [{position}/{total}] {gage_label}: saved",
                    flush=True,
                )
            except Exception as exc:
                result.at[index, "visualization_error"] = f"{type(exc).__name__}: {exc}"
                print(
                    f"WARNING: figure failed for {row['gage_id']}: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if pdf is not None:
            pdf.close()
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare hydrofabric, NLDI network-derived, and NWIS documented "
            "drainage areas. Returns exit code 1 when any basin is not selected."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="GeoPackage file(s), directories (searched recursively), or glob expressions",
    )
    parser.add_argument(
        "--threshold-pct",
        type=float,
        default=20.0,
        help=(
            "Maximum allowed absolute NLDI-to-NWIS area difference "
            "(default: 20)"
        ),
    )
    parser.add_argument(
        "--clean-threshold-pct",
        type=float,
        default=10.0,
        help="Maximum NLDI-to-NWIS difference for CLEAN_PASS (default: 10)",
    )
    parser.add_argument(
        "--hf-nldi-threshold-pct",
        type=float,
        default=5.0,
        help=(
            "Maximum hydrofabric-to-NLDI difference before declaring a "
            "subsetter/topology failure (default: 5)"
        ),
    )
    parser.add_argument(
        "--hf-nwis-fallback-threshold-pct",
        type=float,
        default=10.0,
        help=(
            "Accept an NLDI outlier when hydrofabric and documented NWIS "
            "areas agree within this percentage and NLDI–NWIS exceeds "
            "--threshold-pct (default: 10)"
        ),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("basin_area_comparison.csv"),
        help="Output audit CSV (default: basin_area_comparison.csv)",
    )
    parser.add_argument(
        "--passed-csv",
        type=Path,
        help=(
            "Output selected-gage CSV with STAID, STANAME, and DRAIN_SQKM "
            "(default: selected_gages.csv beside --output-csv)"
        ),
    )
    parser.add_argument("--layer", default="divides", help="GeoPackage divides layer")
    parser.add_argument("--area-column", default="areasqkm", help="Per-divide area column in km²")
    parser.add_argument("--batch-size", type=int, default=50, help="Gages per NWIS request")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="NWIS and NLDI request timeout (default: 60)",
    )
    parser.add_argument(
        "--nldi-workers",
        type=int,
        default=4,
        help="Concurrent NLDI basin requests (default: 4)",
    )
    parser.add_argument(
        "--cleaned-gpkg-dir",
        type=Path,
        help=(
            "Optional downstream-safe directory containing only accepted "
            "GeoPackages after cleanup"
        ),
    )
    parser.add_argument(
        "--rejected-gpkg-dir",
        type=Path,
        help=(
            "Directory for successfully processed but rejected GeoPackages "
            "(default: rejected_hydrofabric beside --cleaned-gpkg-dir)"
        ),
    )
    parser.add_argument(
        "--delete-outside-fraction-pct",
        type=float,
        default=50.0,
        help="Delete a divide when at least this percentage lies outside NLDI (default: 50)",
    )
    parser.add_argument(
        "--minimum-outside-area-sqkm",
        type=float,
        default=0.1,
        help=(
            "Minimum outside area required to delete a boundary-straddling "
            "divide; fully external divides are always deleted (default: 0.1 km²)"
        ),
    )
    parser.add_argument(
        "--overwrite-cleaned-gpkg",
        action="store_true",
        help="Overwrite GeoPackages already present in --cleaned-gpkg-dir",
    )
    parser.add_argument(
        "--figure-dir",
        type=Path,
        help="Optional output directory for boundary-comparison figures/report",
    )
    parser.add_argument(
        "--figure-format",
        choices=("pdf", "jpeg"),
        default="jpeg",
        help=(
            "pdf writes one failure-first multi-page report; jpeg writes one "
            "image per gage (default: jpeg)"
        ),
    )
    parser.add_argument(
        "--figure-scope",
        choices=("all", "attention"),
        default="all",
        help=(
            "all plots every basin; attention plots only failures, cleanup "
            "errors, and basins with removed divides (default: all)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_started = time.perf_counter()
    try:
        print("Discovering GeoPackage inputs...", flush=True)
        files = discover_gpkg_files(args.inputs)
        print(f"Found {len(files)} GeoPackage(s).", flush=True)
        result = compare_basin_areas(
            files,
            threshold_pct=args.threshold_pct,
            clean_threshold_pct=args.clean_threshold_pct,
            hf_nldi_threshold_pct=args.hf_nldi_threshold_pct,
            hf_nwis_fallback_threshold_pct=args.hf_nwis_fallback_threshold_pct,
            layer=args.layer,
            area_column=args.area_column,
            batch_size=args.batch_size,
            timeout_seconds=args.timeout_seconds,
            nldi_workers=args.nldi_workers,
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    removed_divides = pd.DataFrame()
    if args.cleaned_gpkg_dir is not None:
        result, removed_divides = generate_cleaned_hydrofabrics(
            result,
            args.cleaned_gpkg_dir,
            rejected_dir=args.rejected_gpkg_dir,
            outside_fraction_pct=args.delete_outside_fraction_pct,
            minimum_outside_area_sqkm=args.minimum_outside_area_sqkm,
            overwrite=args.overwrite_cleaned_gpkg,
            timeout_seconds=args.timeout_seconds,
        )

    if args.figure_dir is not None:
        result = generate_boundary_figures(
            result,
            args.figure_dir,
            figure_format=args.figure_format,
            figure_scope=args.figure_scope,
            timeout_seconds=args.timeout_seconds,
        )

    args.output_csv = args.output_csv.expanduser().resolve()
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output_csv, index=False)

    if args.cleaned_gpkg_dir is not None:
        removed_divides_csv = args.output_csv.with_name("removed_divides.csv")
        removed_divides.to_csv(removed_divides_csv, index=False)
        rejected_csv = args.output_csv.with_name("rejected_gages.csv")
        rejected_columns = [
            "gage_id", "status", "cleaned_status", "output_disposition",
            "gpkg_file", "cleaned_gpkg_file", "cleanup_error",
        ]
        result.loc[
            ~result["cleaned_status"].isin(SELECTED_STATUSES), rejected_columns
        ].sort_values("gage_id").to_csv(rejected_csv, index=False)
    else:
        removed_divides_csv = None
        rejected_csv = None

    passed_csv = (
        args.passed_csv.expanduser().resolve()
        if args.passed_csv is not None
        else args.output_csv.with_name("selected_gages.csv")
    )
    passed_csv.parent.mkdir(parents=True, exist_ok=True)
    status_column = "cleaned_status" if args.cleaned_gpkg_dir is not None else "status"
    passed = (
        result.loc[
            result[status_column].isin(SELECTED_STATUSES),
            ["gage_id", "station_name", "usgs_area_sqkm"],
        ]
        .rename(
            columns={
                "gage_id": "STAID",
                "station_name": "STANAME",
                "usgs_area_sqkm": "DRAIN_SQKM",
            }
        )
        .drop_duplicates("STAID")
        .sort_values("STAID")
        .reset_index(drop=True)
    )
    passed["STAID"] = passed["STAID"].astype("string")
    passed.to_csv(passed_csv, index=False)

    display_columns = [
        "gage_id", "status", "hydrofabric_area_sqkm", "nldi_area_sqkm",
        "usgs_area_sqkm", "hf_nldi_difference_pct",
        "nldi_nwis_difference_pct",
        "difference_pct",
    ]
    if args.cleaned_gpkg_dir is not None:
        display_columns.extend(
            [
                "removed_divide_count", "corrected_hydrofabric_area_sqkm",
                "corrected_hf_nldi_difference_pct", "cleaned_status",
            ]
        )
    with pd.option_context("display.max_rows", None, "display.width", 140):
        print(result[display_columns].to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"\nSaved: {args.output_csv}")
    print(f"Selected gages ({len(passed)}): {passed_csv}")
    if removed_divides_csv is not None:
        print(f"Removed-divide audit ({len(removed_divides)}): {removed_divides_csv}")
        selected_gpkg_dir = args.cleaned_gpkg_dir.expanduser().resolve()
        rejected_gpkg_dir = (
            args.rejected_gpkg_dir.expanduser().resolve()
            if args.rejected_gpkg_dir is not None
            else selected_gpkg_dir.parent / "rejected_hydrofabric"
        )
        print(f"Rejected-gage audit: {rejected_csv}")
        print(f"Selected GeoPackages only: {selected_gpkg_dir}")
        print(f"Rejected GeoPackages: {rejected_gpkg_dir}")
    counts = result["status"].value_counts().to_dict()
    print("Status counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    if args.figure_dir is not None:
        saved_count = int(result["figure_file"].ne("").sum())
        error_count = int(result["visualization_error"].ne("").sum())
        print(f"Figures: saved={saved_count}, failed={error_count}, directory={args.figure_dir.resolve()}")
    else:
        error_count = 0
    cleanup_error_count = (
        int(result["cleanup_error"].ne("").sum())
        if args.cleaned_gpkg_dir is not None
        else 0
    )
    print(f"Total elapsed time: {time.perf_counter() - run_started:.1f}s", flush=True)
    return (
        0
        if result[status_column].isin(SELECTED_STATUSES).all()
        and error_count == 0
        and cleanup_error_count == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
