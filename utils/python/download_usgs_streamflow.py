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
from pathlib import Path
from typing import Any

import pandas as pd
import requests


class USGSIVDataService:
    """Synchronous client for the USGS instantaneous-values JSON service."""

    URL = "https://nwis.waterservices.usgs.gov/nwis/iv/"

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self._owns_session = session is None

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
            print(
                f"[INFO] Gage {gage_id}: hourly obs rows={total_count}, "
                f"missing={missing_count}"
            )

            if missing_count > 0:
                missing_times = hourly[hourly.isna()].index
                print(
                    f"[WARNING] Gage {gage_id}: missing hourly observations "
                    f"from {missing_times.min()} to {missing_times.max()}"
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

    failed_gages = []
    with USGSIVDataService() as service:
        for gage_id in gage_ids:
            success = fetch_and_save_hourly_usgs_data(
                service=service,
                gage_id=gage_id,
                start=start,
                end=end,
                output_dir=output_dir,
                aggregate=aggregate
            )
            if not success:
                failed_gages.append(gage_id)

    if failed_gages:
        raise RuntimeError(
            "USGS streamflow download failed for gage(s): "
            + ", ".join(failed_gages)
        )

    print("All gages processed successfully.", flush=True)


# ============================================================
if __name__ == "__main__":
    args = parse_args()
    get_usgs_data_driver(
        gage_ids=resolve_gage_ids(args),
        output_dir=args.output_dir,
        start=args.start,
        end=args.end,
        aggregate=args.aggregate,
    )
