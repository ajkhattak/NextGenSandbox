"""Download hourly USGS streamflow observations for NextGenSandbox.

Exactly one gage source is required:

1. Read IDs from a CSV file (extra columns are ignored)::

       python utils/python/download_usgs_streamflow.py \
         --gages-file /path/to/gages.csv \
         --id-column gage_id \
         --start "2015-10-01 00:00:00" \
         --end "2022-09-30 23:00:00" \
         --output-dir /path/to/observations/streamflow

2. Provide IDs directly::

       python utils/python/download_usgs_streamflow.py \
         --gages 01109403 08070500 \
         --start "2015-10-01 00:00:00" \
         --end "2022-09-30 23:00:00" \
         --output-dir /path/to/observations/streamflow

3. Discover IDs from gage_<gage_id>.gpkg filenames::

       python utils/python/download_usgs_streamflow.py \
         --gpkg-pattern "/path/to/inputs/*/hydrofabric/*.gpkg" \
         --start "2015-10-01 00:00:00" \
         --end "2022-09-30 23:00:00" \
         --output-dir /path/to/observations/streamflow

By default, instantaneous observations are averaged to hourly values. Add
``--no-aggregate`` to retain only observations recorded exactly on the hour.
Each output is named ``gage_<gage_id>_hourly_streamflow.csv`` and contains
``value_time`` and ``value`` columns, with streamflow in m3/s.
"""

from __future__ import annotations

import argparse
import glob
import html
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class USGSIVDataService:
    """Synchronous client for the USGS instantaneous-values JSON service."""

    URL = "https://nwis.waterservices.usgs.gov/nwis/iv/"

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self._owns_session = session is None
        if self._owns_session:
            retries = Retry(
                total=3,
                connect=3,
                read=2,
                status=3,
                backoff_factor=2,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods={"GET"},
                respect_retry_after_header=True,
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self._owns_session:
            self.session.close()

    def get(
        self,
        *,
        sites: str,
        startDT: str,
        endDT: str,
        parameterCd: str = "00060",
        siteStatus: str = "all",
    ) -> pd.DataFrame:
        start_time = self._parse_request_time(startDT, "startDT")
        end_time = self._parse_request_time(endDT, "endDT")
        if end_time < start_time:
            raise ValueError("USGS request endDT must not be before startDT")

        response = self.session.get(
            self.URL,
            params={
                "format": "json",
                "sites": str(sites),
                "startDT": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDT": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "parameterCd": parameterCd,
                "siteStatus": siteStatus,
            },
            headers={"Accept-Encoding": "gzip, compress"},
            timeout=(30, 900),
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            detail = html.unescape(
                re.sub(r"<[^>]+>", " ", getattr(response, "text", ""))
            )
            detail = " ".join(detail.split())[:600]
            message = (
                f"USGS IV request failed for gage {sites} from "
                f"{start_time:%Y-%m-%d %H:%M:%S UTC} to "
                f"{end_time:%Y-%m-%d %H:%M:%S UTC}"
            )
            if detail:
                message = f"{message}: {detail}"
            raise requests.HTTPError(message, response=response) from error
        return self._parse_response(response.json())

    @staticmethod
    def _parse_request_time(value: str, name: str) -> pd.Timestamp:
        """Return a UTC timestamp accepted by the USGS IV service."""
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"USGS request {name} is not a valid timestamp: {value!r}") from error

        if pd.isna(timestamp):
            raise ValueError(f"USGS request {name} is not a valid timestamp: {value!r}")
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC")

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> pd.DataFrame:
        rows = []
        time_series = payload.get("value", {}).get("timeSeries", [])
        for series_index, series in enumerate(time_series):
            source_info = series.get("sourceInfo", {})
            site_codes = source_info.get("siteCode", [])
            site_code = site_codes[0].get("value", "") if site_codes else ""
            unit = (
                series.get("variable", {})
                .get("unit", {})
                .get("unitCode", "")
            )
            for values_group in series.get("values", []):
                for observation in values_group.get("value", []):
                    rows.append(
                        {
                            "value_time": observation.get("dateTime"),
                            "value": observation.get("value"),
                            "usgs_site_code": site_code,
                            "measurement_unit": unit,
                            "series": series_index,
                        }
                    )

        columns = [
            "value_time",
            "value",
            "usgs_site_code",
            "measurement_unit",
            "series",
        ]
        if not rows:
            return pd.DataFrame(columns=columns)

        dataframe = pd.DataFrame(rows, columns=columns)
        dataframe["value_time"] = (
            pd.to_datetime(dataframe["value_time"], utc=True)
            .dt.tz_localize(None)
        )
        dataframe["value"] = pd.to_numeric(
            dataframe["value"],
            errors="coerce",
        )
        return dataframe.sort_values("value_time", ignore_index=True)


# ============================================================
# STEP 2: Get gage IDs from local input directories
# ============================================================

def get_gage_ids_from_gpkgs(gpkg_pattern: str) -> list[str]:
    gage_ids = []

    for gpkg_path in glob.glob(gpkg_pattern):
        gpkg_file = Path(gpkg_path)
        match = re.match(r"gage_(\w+)\.gpkg", gpkg_file.name)
        if match:
            gage_id = match.group(1)
            gage_ids.append(gage_id)
            print(f"[FOUND] Gage ID: {gage_id}")
        else:
            print(f"[SKIPPED] {gpkg_file.name} (filename format didn't match)")

    print(f"Total gages found: {len(gage_ids)}\n")
    return gage_ids


def get_gage_ids_from_csv(
    gages_file: str | Path,
    id_column: str = "gage_id",
) -> list[str]:
    """Read unique gage IDs from a CSV file while preserving leading zeros."""
    path = Path(gages_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Gage CSV file does not exist: {path}")

    dataframe = pd.read_csv(path, dtype=str)
    if id_column not in dataframe.columns:
        available = ", ".join(str(column) for column in dataframe.columns)
        raise ValueError(
            f"Gage CSV column '{id_column}' was not found in {path}. "
            f"Available columns: {available or '(none)'}"
        )

    values = dataframe[id_column]
    if values.isna().any():
        rows = [str(index + 2) for index in values[values.isna()].index]
        raise ValueError(
            f"Gage CSV column '{id_column}' contains empty values on line(s): "
            f"{', '.join(rows)}"
        )

    gage_ids = []
    seen = set()
    for value in values:
        gage_id = value.strip()
        if not gage_id:
            raise ValueError(
                f"Gage CSV column '{id_column}' contains a blank gage ID"
            )
        if gage_id not in seen:
            seen.add(gage_id)
            gage_ids.append(gage_id)

    if not gage_ids:
        raise ValueError(f"No gage IDs were found in {path}")

    print(f"[INFO] Read {len(gage_ids)} unique gage IDs from {path}.")
    return gage_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download USGS instantaneous streamflow observations and write "
            "one hourly CSV file per gage."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  # Read gages from a CSV file
  python utils/python/download_usgs_streamflow.py \\
    --gages-file gages.csv --id-column gage_id \\
    --start "2015-10-01 00:00:00" --end "2022-09-30 23:00:00" \\
    --output-dir observations/streamflow

  # Provide gages directly
  python utils/python/download_usgs_streamflow.py \\
    --gages 01109403 08070500 \\
    --start "2015-10-01 00:00:00" --end "2022-09-30 23:00:00" \\
    --output-dir observations/streamflow

  # Discover gages from geopackage filenames
  python utils/python/download_usgs_streamflow.py \\
    --gpkg-pattern "/path/to/inputs/*/hydrofabric/*.gpkg" \\
    --start "2015-10-01 00:00:00" --end "2022-09-30 23:00:00" \\
    --output-dir observations/streamflow
""",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--gages",
        nargs="+",
        metavar="GAGE_ID",
        help="One or more USGS gage IDs.",
    )
    source.add_argument(
        "--gages-file",
        type=Path,
        help="CSV file containing USGS gage IDs.",
    )
    source.add_argument(
        "--gpkg-pattern",
        help='Glob pattern for geopackages, such as "/path/*/hydrofabric/*.gpkg".',
    )
    parser.add_argument(
        "--id-column",
        default="gage_id",
        help="Gage ID column in --gages-file (default: gage_id).",
    )
    parser.add_argument("--start", required=True, help="Download start time.")
    parser.add_argument("--end", required=True, help="Download end time.")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for generated streamflow CSV files.",
    )
    parser.add_argument(
        "--no-aggregate",
        action="store_false",
        dest="aggregate",
        help="Keep top-of-hour values instead of hourly averages.",
    )
    parser.add_argument(
        "--audit-existing",
        action="store_true",
        help="Audit existing hourly CSV files without downloading them again.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        choices=(1, 2, 3),
        default=2,
        help="Concurrent gage downloads (default: 2; 1 runs serially).",
    )
    parser.add_argument(
        "--qc-start",
        help="First scored UTC hour; defaults to --start (exclude spin-up here).",
    )
    parser.add_argument(
        "--qc-end",
        help="Last scored UTC hour; a date alone includes its full day. Defaults to --end.",
    )
    parser.add_argument(
        "--min-hourly-coverage",
        type=float,
        default=0.95,
        help="Minimum fraction of scored hours available (default: 0.95).",
    )
    parser.add_argument(
        "--min-water-year-coverage",
        type=float,
        default=0.90,
        help="Minimum hourly coverage in every scored water year (default: 0.90).",
    )
    parser.add_argument(
        "--max-gap-hours",
        type=int,
        default=720,
        help="Maximum consecutive missing scored hours (default: 720, or 30 days).",
    )
    parser.add_argument(
        "--qc-summary",
        type=Path,
        help="QC CSV path; defaults to <output-dir>/hourly_streamflow_qc.csv.",
    )
    parser.set_defaults(aggregate=True)
    return parser.parse_args()


def resolve_gage_ids(args: argparse.Namespace) -> list[str]:
    if args.gages:
        return list(dict.fromkeys(str(gage_id).strip() for gage_id in args.gages))
    if args.gages_file:
        return get_gage_ids_from_csv(args.gages_file, args.id_column)

    gage_ids = get_gage_ids_from_gpkgs(args.gpkg_pattern)
    if not gage_ids:
        raise FileNotFoundError(
            f"No geopackages matched --gpkg-pattern: {args.gpkg_pattern}"
        )
    return gage_ids


def _qc_time(value: str, *, end: bool = False) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid QC timestamp: {value!r}") from exc
    if pd.isna(timestamp):
        raise ValueError(f"Invalid QC timestamp: {value!r}")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    if end and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value).strip()):
        timestamp += pd.Timedelta(hours=23)
    return timestamp


def audit_hourly_streamflow(
    path: Path,
    gage_id: str,
    qc_start: str,
    qc_end: str,
    min_hourly_coverage: float = 0.95,
    min_water_year_coverage: float = 0.90,
    max_gap_hours: int = 720,
) -> dict[str, object]:
    """Assess complete UTC hours in the scored interval, grouped by water year."""
    start = _qc_time(qc_start).ceil("h")
    end = _qc_time(qc_end, end=True).floor("h")
    if start > end:
        raise ValueError("QC end must be on or after QC start")
    if not 0 <= min_hourly_coverage <= 1 or not 0 <= min_water_year_coverage <= 1:
        raise ValueError("QC coverage thresholds must be between 0 and 1")
    if max_gap_hours < 0:
        raise ValueError("--max-gap-hours must be nonnegative")

    result: dict[str, object] = {
        "gage_id": gage_id,
        "qc_start": start.isoformat(),
        "qc_end": end.isoformat(),
        "file_exists": path.is_file(),
        "expected_hours": 0,
        "available_hours": 0,
        "overall_hourly_coverage": 0.0,
        "minimum_water_year_coverage": 0.0,
        "failed_water_years": "",
        "water_year_coverage": "",
        "longest_gap_hours": 0,
        "longest_gap_start": "",
        "longest_gap_end": "",
        "passes_hourly_qc": False,
        "exclusion_reasons": "",
    }
    if not path.is_file():
        result["exclusion_reasons"] = "missing_hourly_file"
        return result

    try:
        frame = pd.read_csv(path, usecols=["value_time", "value"])
    except (OSError, ValueError, pd.errors.ParserError):
        result["exclusion_reasons"] = "unreadable_hourly_file"
        return result
    times = pd.to_datetime(frame["value_time"], utc=True, errors="coerce")
    if times.isna().any():
        result["exclusion_reasons"] = "invalid_timestamps"
        return result
    times = times.dt.tz_localize(None)
    if times.duplicated().any():
        result["exclusion_reasons"] = "duplicate_timestamps"
        return result

    values = pd.to_numeric(frame["value"], errors="coerce")
    series = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(times))
    hours = pd.date_range(start, end, freq="h")
    available = np.isfinite(series.reindex(hours).to_numpy(dtype=float))
    expected = len(hours)
    total_coverage = float(available.mean())
    water_years = hours.year + (hours.month >= 10)
    yearly = pd.DataFrame({"water_year": water_years, "available": available})
    yearly_coverage = yearly.groupby("water_year", sort=True)["available"].mean()
    failed_years = yearly_coverage[yearly_coverage < min_water_year_coverage].index.tolist()

    missing_positions = np.flatnonzero(~available)
    if len(missing_positions):
        breaks = np.flatnonzero(np.diff(missing_positions) != 1) + 1
        runs = np.split(missing_positions, breaks)
        longest = max(runs, key=len)
        result["longest_gap_hours"] = len(longest)
        result["longest_gap_start"] = hours[longest[0]].isoformat()
        result["longest_gap_end"] = hours[longest[-1]].isoformat()

    reasons = []
    if total_coverage < min_hourly_coverage:
        reasons.append("overall_coverage")
    if failed_years:
        reasons.append("water_year_coverage")
    if result["longest_gap_hours"] > max_gap_hours:
        reasons.append("longest_gap")

    result.update(
        expected_hours=expected,
        available_hours=int(available.sum()),
        overall_hourly_coverage=total_coverage,
        minimum_water_year_coverage=float(yearly_coverage.min()),
        failed_water_years=";".join(map(str, failed_years)),
        water_year_coverage=";".join(
            f"{year}:{coverage:.4f}" for year, coverage in yearly_coverage.items()
        ),
        passes_hourly_qc=not reasons,
        exclusion_reasons=";".join(reasons),
    )
    return result


def fetch_and_save_hourly_usgs_data(service,
                                    gage_id,
                                    start,
                                    end,
                                    cfs_to_cms=0.028316847,
                                    output_dir=".",
                                    aggregate=True
                                    ) -> bool:
    """
    Fetches 15-min USGS streamflow data for a given gage ID, filters to hourly values,
    converts units, and saves to CSV.

    Parameters:
        service:          USGS data service client (e.g., from dataretrieval or ulmo)
        gage_id:          str, USGS site ID (e.g., '10011500')
        start:            str or datetime, start date (e.g., '2015-10-01 00:00:00')
        end:              str or datetime, end date (e.g., '2015-11-01 00:00:00')
        cfs_to_cms:       float, conversion factor from ft3/s to m3/s
        output_dir:       str, directory to save the CSV file in
    """
    try:
        # Fetch data
        observations_data = service.get(
            sites=gage_id,
            startDT=start,
            endDT=end
        )

        if observations_data.empty:
            print(f"[WARNING] No data returned for site {gage_id}")
            return False

        # Parse datetime and convert units
        observations_data['value_time'] = pd.to_datetime(observations_data['value_time'])
        observations_data['value'] = observations_data['value'] * cfs_to_cms

        if (aggregate):
            # Set datetime as index for resampling
            observations_data = observations_data.set_index('value_time')

            # Aggregate to hourly averages, label by end of hour (averaging period)
            hourly = (
                observations_data['value']
                .resample('1h', label='right', closed='left')
                .mean()
            )

            # Keep a complete hourly time axis so missing observation hours
            # remain explicit as NaN instead of being silently dropped. The
            # calibration/scoring plugin can then ignore paired sim/obs rows
            # where obs is NaN, while we still know how many observation hours
            # were unavailable.
            start_hour = pd.Timestamp(start).ceil('h')
            end_hour = pd.Timestamp(end).floor('h')
            full_hours = pd.date_range(start=start_hour, end=end_hour, freq='1h')

            hourly = hourly.reindex(full_hours)
            hourly.index.name = 'value_time'

            missing_count = int(hourly.isna().sum())
            total_count = int(hourly.shape[0])
            available_count = total_count - missing_count
            coverage_pct = (
                100.0 * available_count / total_count if total_count else 0.0
            )
            print(
                f"[INFO] Gage {gage_id}: hourly coverage={coverage_pct:.2f}% "
                f"({available_count}/{total_count} hours available; "
                f"{missing_count} missing)"
            )

            if missing_count > 0:
                missing_times = hourly[hourly.isna()].index
                missing_frame = pd.DataFrame({"missing_time": missing_times})
                missing_frame["gap_id"] = (
                    missing_frame["missing_time"]
                    .diff()
                    .ne(pd.Timedelta(hours=1))
                    .cumsum()
                )
                gaps = missing_frame.groupby("gap_id")["missing_time"].agg(
                    start="min",
                    end="max",
                    hours="size",
                )
                longest_gap = gaps.loc[gaps["hours"].idxmax()]
                longest_hours = int(longest_gap["hours"])
                longest_days = longest_hours / 24.0
                print(
                    f"[WARNING] Gage {gage_id}: missing observations occur "
                    f"in {len(gaps)} separate gap(s); earliest missing="
                    f"{missing_times.min()}, latest missing={missing_times.max()}; "
                    f"longest continuous gap={longest_hours} hours "
                    f"({longest_days:.1f} days), from {longest_gap['start']} "
                    f"to {longest_gap['end']}"
                )

            hourly_df = hourly.rename('value').reset_index()
        else:
            hourly_only = observations_data[
                (observations_data['value_time'].dt.minute == 0) &
                (observations_data['value_time'].dt.second == 0)
            ]

            # Select only value_time and value
            hourly_df = hourly_only[['value_time', 'value']].copy()


        # Save to file
        output_path = f"{output_dir}/gage_{gage_id}_hourly_streamflow.csv"
        hourly_df.to_csv(output_path, index=False)
        print(f"[INFO] Saved hourly data for gage {gage_id} to {output_path}")
        return True

    except Exception as e:
        print(f"[ERROR] Failed to fetch/process data for gage {gage_id}: {e}")
        return False


# ============================================================
# STEP 4: Loop over all discovered gages
# ============================================================
def get_usgs_data_driver(
    gage_ids: list[str],
    output_dir: str | Path,
    start: str,
    end: str,
    aggregate: bool = True,
    *,
    audit_existing: bool = False,
    qc_start: str | None = None,
    qc_end: str | None = None,
    min_hourly_coverage: float = 0.95,
    min_water_year_coverage: float = 0.90,
    max_gap_hours: int = 720,
    qc_summary: str | Path | None = None,
    workers: int = 2,
):
    """
    Download hourly streamflow data for each supplied USGS gage ID.

    Parameters
    ----------
    gage_ids : list[str]
        USGS gage IDs to download.
    output_dir : str
        Output directory for CSV files.
    start, end : str
        Date range for download.
    aggregate : bool, optional
        If True, resample to hourly mean. If False, keep top-of-hour values.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    if not gage_ids:
        raise ValueError("At least one gage ID must be provided")
    print(f"[INFO] Processing {len(gage_ids)} gage IDs.")

    qc_start = qc_start or start
    qc_end = qc_end or end
    # Validate settings even when no gage file is present.
    if _qc_time(qc_start).ceil("h") > _qc_time(qc_end, end=True).floor("h"):
        raise ValueError("QC end must be on or after QC start")
    if not 0 <= min_hourly_coverage <= 1 or not 0 <= min_water_year_coverage <= 1:
        raise ValueError("QC coverage thresholds must be between 0 and 1")
    if max_gap_hours < 0:
        raise ValueError("--max-gap-hours must be nonnegative")
    if workers not in (1, 2, 3):
        raise ValueError("--workers must be 1, 2, or 3")

    failed_gages = []
    qc_rows = []
    output_dir = Path(output_dir)
    def process_gage(gage_id: str) -> tuple[str, bool, dict[str, object]]:
        success = True
        if not audit_existing:
            with USGSIVDataService() as service:
                success = fetch_and_save_hourly_usgs_data(
                    service=service,
                    gage_id=gage_id,
                    start=start,
                    end=end,
                    output_dir=output_dir,
                    aggregate=aggregate,
                )
        qc = audit_hourly_streamflow(
            output_dir / f"gage_{gage_id}_hourly_streamflow.csv",
            gage_id,
            qc_start,
            qc_end,
            min_hourly_coverage,
            min_water_year_coverage,
            max_gap_hours,
        )
        if not success:
            qc["passes_hourly_qc"] = False
            qc["exclusion_reasons"] = "download_failed"
        return gage_id, success, qc

    def record_result(result: tuple[str, bool, dict[str, object]]) -> None:
        gage_id, success, qc = result
        if not success:
            failed_gages.append(gage_id)
        qc_rows.append(qc)
        status = "PASS" if qc["passes_hourly_qc"] else "FAIL"
        print(
            f"[QC {status}] Gage {gage_id}: "
            f"coverage={qc['overall_hourly_coverage']:.2%}, "
            f"minimum water-year coverage={qc['minimum_water_year_coverage']:.2%}, "
            f"longest scored gap={qc['longest_gap_hours']} hours; "
            f"reasons={qc['exclusion_reasons'] or 'none'}"
        )

    if audit_existing or workers == 1 or len(gage_ids) == 1:
        for gage_id in gage_ids:
            record_result(process_gage(gage_id))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for result in executor.map(process_gage, gage_ids):
                record_result(result)

    summary_path = Path(qc_summary) if qc_summary else output_dir / "hourly_streamflow_qc.csv"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(qc_rows).to_csv(summary_path, index=False)
    print(f"[INFO] Saved hourly QC for {len(qc_rows)} gages to {summary_path}")
    excluded_path = summary_path.with_name("excluded_hourly_gages.csv")
    excluded = pd.DataFrame(
        [
            {"STAID": row["gage_id"], "exclusion_reasons": row["exclusion_reasons"]}
            for row in qc_rows
            if not row["passes_hourly_qc"]
        ],
        columns=["STAID", "exclusion_reasons"],
    )
    excluded.to_csv(excluded_path, index=False)
    print(f"[INFO] Saved {len(excluded)} hourly QC exclusions to {excluded_path}")

    if failed_gages:
        raise RuntimeError(
            "USGS streamflow download failed for gage(s): "
            + ", ".join(failed_gages)
        )

    passed = sum(bool(row["passes_hourly_qc"]) for row in qc_rows)
    print(
        f"Hourly QC complete: {passed}/{len(qc_rows)} gages passed; "
        f"exclude the other {len(qc_rows) - passed} before calibration.",
        flush=True,
    )


# ============================================================
if __name__ == "__main__":
    args = parse_args()
    get_usgs_data_driver(
        gage_ids=resolve_gage_ids(args),
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
        aggregate=args.aggregate,
        audit_existing=args.audit_existing,
        qc_start=args.qc_start,
        qc_end=args.qc_end,
        min_hourly_coverage=args.min_hourly_coverage,
        min_water_year_coverage=args.min_water_year_coverage,
        max_gap_hours=args.max_gap_hours,
        qc_summary=args.qc_summary,
        workers=args.workers,
    )
