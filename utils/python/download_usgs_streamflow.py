import glob
import re
import shutil
from pathlib import Path
import pandas as pd
from hydrotools.nwis_client.iv import IVDataService
import os, sys


# ============================================================
# STEP 2: Get gage IDs from local input directories
# ============================================================

def get_gage_ids(input_pattern):
    gage_ids = []

    for gpkg_path in glob.glob(input_pattern):
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


#cf_per_hr_to_m3_per_hr = 0.028316847


def fetch_and_save_hourly_usgs_data(service,
                                    gage_id,
                                    start,
                                    end,
                                    cf_per_hr_to_m3_per_hr=0.028316847,
                                    output_dir=".",
                                    aggregate=True
                                    ):
    """
    Fetches 15-min USGS streamflow data for a given gage ID, filters to hourly values,
    converts units, and saves to CSV.

    Parameters:
        service:          USGS data service client (e.g., from dataretrieval or ulmo)
        gage_id:          str, USGS site ID (e.g., '10011500')
        start:            str or datetime, start date (e.g., '2015-10-01 00:00:00')
        end:              str or datetime, end date (e.g., '2015-11-01 00:00:00')
        cf_per_hr_to_m3_per_hr: float, conversion factor from ft³/hr to m³/hr
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
            return

        # Parse datetime and convert units
        observations_data['value_time'] = pd.to_datetime(observations_data['value_time'])
        observations_data['value'] = observations_data['value'] * cf_per_hr_to_m3_per_hr

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

    except Exception as e:
        print(f"[ERROR] Failed to fetch/process data for gage {gage_id}: {e}")


# ============================================================
# STEP 4: Loop over all discovered gages
# ============================================================
def get_usgs_data_driver(input_pattern, output_dir,
                         start, end, gages_lst, aggregate=True):
    """
    get USGS gages IDs from a local directory and download hourly streamflow data for each.

    Parameters
    ----------
    input_pattern : str
        Glob pattern for gage_*.gpkg files.
    output_dir : str
        Output directory for CSV files.
    start, end : str
        Date range for download.
    gages_lst : list[str], optional
        User-provided list of gage IDs. If None or empty, gages will be obtained from input_pattern.
    aggregate : bool, optional
        If True, resample to hourly mean. If False, keep top-of-hour values.
    """
    os.makedirs(Path(output_dir), exist_ok=True)
    service  = IVDataService(value_time_label="value_time")

    if gages_lst and len(gages_lst) > 0:
        gage_ids = gages_lst
        print(f"[INFO] Using {len(gage_ids)} user-provided gage IDs.")
    else:
        gage_ids = get_gage_ids(input_pattern)
        print(f"[INFO] Discovered {len(gage_ids)} gage IDs from input directory.")

    for gage_id in gage_ids:
        fetch_and_save_hourly_usgs_data(
            service=service,
            gage_id=gage_id,
            start=start,
            end=end,
            output_dir=output_dir,
            aggregate=aggregate
        )

    print("All gages processed successfully.")


# ============================================================
if __name__ == "__main__":
    input_pattern = "/Users/ahmadjankhattak/Core/projects/nwm_bm_sims/input_20250902/*/data/*.gpkg"
    output_dir    = "/Users/ahmadjankhattak/Core/projects/nwm_bm_sims/usgs_obs_streamflow_agg"
    start = "2015-10-01 00:00:00"
    end   = "2022-09-30 23:00:00"

    aggregate = True
    gages_lst = []     # e.g. ['10011500', '08070500']

    get_usgs_data_driver(
        input_pattern=input_pattern,
        output_dir=output_dir,
        start=start,
        end=end,
        gages_lst=gages_lst,
        aggregate=aggregate
    )
