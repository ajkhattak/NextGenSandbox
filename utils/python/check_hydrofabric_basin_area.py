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
"""

from __future__ import annotations

import argparse
import glob
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
from pathlib import Path
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
SQUARE_MILES_TO_SQUARE_KM = 2.589988110336
SELECTED_STATUSES = {"CLEAN_PASS", "ACCEPTABLE_OUTLET_OFFSET"}


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
            matches = [Path(match) for match in glob.glob(value, recursive=True)]
            files.extend(candidate.resolve() for candidate in matches if candidate.is_file() and candidate.suffix.lower() == ".gpkg")
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

    result["status"] = "CLEAN_PASS"
    result.loc[outlet_offset, "status"] = "ACCEPTABLE_OUTLET_OFFSET"
    result.loc[domain_mismatch, "status"] = "OBSERVATION_DOMAIN_MISMATCH"
    result.loc[topology_failure, "status"] = "SUBSETTER_OR_TOPOLOGY_FAILURE"
    result.loc[missing_usgs, "status"] = "MISSING_USGS_AREA"
    result.loc[missing_nldi, "status"] = "MISSING_NLDI_AREA"
    result.loc[result["processing_error"].ne(""), "status"] = "ERROR"
    columns = [
        "gage_id", "station_name", "status", "threshold_pct",
        "clean_threshold_pct", "hf_nldi_threshold_pct", "gpkg_file",
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
    return boundary


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
        f"[{comparison_row['status']}]"
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
    timeout_seconds: int = 60,
) -> pd.DataFrame:
    """Generate one boundary-comparison figure per comparable GeoPackage."""
    figure_format = figure_format.lower()
    if figure_format not in {"pdf", "jpeg"}:
        raise ValueError("figure_format must be one of: pdf, jpeg")
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
        "ACCEPTABLE_OUTLET_OFFSET": 5,
        "CLEAN_PASS": 6,
    }
    ordered_indices = sorted(
        result.index,
        key=lambda index: (
            priority.get(str(result.at[index, "status"]), 4),
            str(result.at[index, "gage_id"]),
        ),
    )

    pdf = None
    consolidated_pdf = output_dir / "basin_boundary_comparisons.pdf"
    if figure_format == "pdf":
        from matplotlib.backends.backend_pdf import PdfPages

        pdf = PdfPages(consolidated_pdf)
    page_number = 0
    try:
        for index in ordered_indices:
            row = result.loc[index]
            if not row["gage_id"] or row["processing_error"]:
                continue
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
            except Exception as exc:
                result.at[index, "visualization_error"] = f"{type(exc).__name__}: {exc}"
                print(
                    f"WARNING: figure failed for {row['gage_id']}: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
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
        "--output-csv",
        type=Path,
        default=Path("basin_area_comparison.csv"),
        help="Output audit CSV (default: basin_area_comparison.csv)",
    )
    parser.add_argument(
        "--passed-csv",
        type=Path,
        help=(
            "Output CSV containing only passing gage IDs "
            "(default: passed_basin_ids.csv beside --output-csv)"
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        files = discover_gpkg_files(args.inputs)
        print(f"Found {len(files)} GeoPackage(s).", flush=True)
        result = compare_basin_areas(
            files,
            threshold_pct=args.threshold_pct,
            clean_threshold_pct=args.clean_threshold_pct,
            hf_nldi_threshold_pct=args.hf_nldi_threshold_pct,
            layer=args.layer,
            area_column=args.area_column,
            batch_size=args.batch_size,
            timeout_seconds=args.timeout_seconds,
            nldi_workers=args.nldi_workers,
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.figure_dir is not None:
        result = generate_boundary_figures(
            result,
            args.figure_dir,
            figure_format=args.figure_format,
            timeout_seconds=args.timeout_seconds,
        )

    args.output_csv = args.output_csv.expanduser().resolve()
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output_csv, index=False)

    passed_csv = (
        args.passed_csv.expanduser().resolve()
        if args.passed_csv is not None
        else args.output_csv.with_name("passed_basin_ids.csv")
    )
    passed_csv.parent.mkdir(parents=True, exist_ok=True)
    passed = (
        result.loc[result["status"].isin(SELECTED_STATUSES), ["gage_id"]]
        .drop_duplicates()
        .sort_values("gage_id")
        .reset_index(drop=True)
    )
    passed.to_csv(passed_csv, index=False)

    display_columns = [
        "gage_id", "status", "hydrofabric_area_sqkm", "nldi_area_sqkm",
        "usgs_area_sqkm", "hf_nldi_difference_pct",
        "nldi_nwis_difference_pct",
    ]
    with pd.option_context("display.max_rows", None, "display.width", 140):
        print(result[display_columns].to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"\nSaved: {args.output_csv}")
    print(f"Passed basin IDs ({len(passed)}): {passed_csv}")
    counts = result["status"].value_counts().to_dict()
    print("Status counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    if args.figure_dir is not None:
        saved_count = int(result["figure_file"].ne("").sum())
        error_count = int(result["visualization_error"].ne("").sum())
        print(f"Figures: saved={saved_count}, failed={error_count}, directory={args.figure_dir.resolve()}")
    else:
        error_count = 0
    return 0 if result["status"].isin(SELECTED_STATUSES).all() and error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
