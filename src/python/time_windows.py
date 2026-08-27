from __future__ import annotations

from pathlib import Path

import pandas as pd


NGEN_TIMESTEP = pd.Timedelta(hours=1)


def normalize_simulation_tasks(simulation_config):
    """Validate public simulation tasks and return tasks plus the run mode."""
    if not isinstance(simulation_config, dict):
        raise TypeError("simulation must be a YAML dictionary/object")
    if "task_type" in simulation_config:
        raise ValueError(
            "simulation.task_type is no longer supported; use simulation.tasks"
        )

    tasks = simulation_config.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(
            "simulation.tasks must be one of: [control], [calibration], "
            "[validation], [restart], or [calibration, validation]"
        )

    normalized = tuple(str(task).strip().lower() for task in tasks)
    task_modes = {
        ("control",): "control",
        ("calibration",): "calibration",
        ("validation",): "validation",
        ("restart",): "restart",
        ("calibration", "validation"): "calibvalid",
    }
    if normalized not in task_modes:
        raise ValueError(
            "simulation.tasks must be one of: [control], [calibration], "
            "[validation], [restart], or [calibration, validation]"
        )
    return normalized, task_modes[normalized]


def normalize_forcing_time_config(time_config):
    if not isinstance(time_config, dict):
        raise TypeError("forcings.time must be a YAML dictionary/object")

    legacy_keys = {"start_time", "end_time"}.intersection(time_config)
    if legacy_keys:
        raise ValueError(
            "forcings.time uses start/end now; replace start_time/end_time "
            "with start/end"
        )

    missing = [
        key for key in ("start", "end")
        if key not in time_config
    ]
    if missing:
        raise ValueError(
            f"forcings.time missing required field(s): {', '.join(missing)}"
        )

    start = parse_timestamp(time_config["start"], "forcings.time.start")
    end = parse_timestamp(time_config["end"], "forcings.time.end")

    normalized = {
        "start_time": format_timestamp(start),
        "end_time": format_timestamp(end),
    }
    validate_time_window("forcings.time", normalized)
    return normalized


def normalize_simulation_time_config(dsim, task_type, config_dir=None):
    time_config = dsim["time"]
    if not isinstance(time_config, dict):
        raise TypeError("simulation.time must be a YAML dictionary/object")
    if "timestep" in time_config:
        raise ValueError(
            "simulation.time.timestep is not supported. "
            "Sandbox assumes hourly ngen model timesteps."
        )

    if task_type == "control":
        if "control" not in time_config:
            raise ValueError(
                "simulation.time.control is required for simulation.tasks: "
                "[control]"
            )
        dsim["simulation_time"] = resolve_time_period(
            time_config["control"],
            "simulation.time.control",
        )["simulation_time"]
        return

    if task_type in ["calibration", "calibvalid", "restart"]:
        if "calibration" not in time_config:
            task_label = (
                "[calibration, validation]"
                if task_type == "calibvalid"
                else f"[{task_type}]"
            )
            raise ValueError(
                "simulation.time.calibration is required for simulation.tasks: "
                f"{task_label}"
            )

        calibration = resolve_time_period(
            time_config["calibration"],
            "simulation.time.calibration",
            allow_selected_years=True,
        )
        dsim["calibration_time"] = calibration["simulation_time"]
        dsim["calib_eval_time"] = calibration["evaluation_time"]
        dsim["calib_eval_selection"] = calibration.get("evaluation_selection")

        if task_type == "calibvalid":
            validations = resolve_validation_periods(time_config, config_dir=config_dir)
            validation = validations[0]
            dsim["validation_periods"] = validations
            dsim["validation_time"] = validation["simulation_time"]
            dsim["valid_eval_time"] = validation["evaluation_time"]

        return

    if task_type == "validation":
        validations = resolve_validation_periods(time_config, config_dir=config_dir)
        validation = validations[0]
        dsim["validation_periods"] = validations
        dsim["validation_time"] = validation["simulation_time"]
        dsim["valid_eval_time"] = validation["evaluation_time"]


def resolve_validation_periods(time_config, config_dir=None):
    validations = time_config.get("validations")
    if validations is None:
        raise ValueError("simulation.time.validations is required")
    if not isinstance(validations, list) or not validations:
        raise ValueError("simulation.time.validations must be a non-empty list")

    periods = []
    for index, period in enumerate(validations):
        periods.extend(
            resolve_validation_period(
                period,
                f"simulation.time.validations[{index}]",
                config_dir=config_dir,
            )
        )
    return periods


def resolve_validation_period(period, name, config_dir=None):
    if not isinstance(period, dict):
        raise TypeError(f"{name} must be a YAML dictionary/object")

    source = str(period.get("source", "manual")).lower()
    if source == "manual":
        return [resolve_time_period(period, name)]
    if source == "file":
        return resolve_validation_file_periods(period, name, config_dir=config_dir)

    raise ValueError(f"{name}.source must be one of: manual, file")


def resolve_validation_file_periods(period, name, config_dir=None):
    if "start" in period:
        raise ValueError(f"{name}.start is not used when source: file")
    if "end" in period:
        raise ValueError(f"{name}.end is not used when source: file")
    if "evaluation" not in period:
        raise ValueError(f"{name}.evaluation is required when source: file")
    if "spinup" not in period:
        raise ValueError(f"{name}.spinup is required when source: file")

    file_value = period.get("file")
    if not isinstance(file_value, str) or not file_value.strip():
        raise ValueError(f"{name}.file must be a non-empty path")

    csv_file = Path(file_value).expanduser()
    if not csv_file.is_absolute() and config_dir is not None:
        csv_file = Path(config_dir) / csv_file
    if not csv_file.exists():
        raise FileNotFoundError(f"{name}.file does not exist: {csv_file}")

    year_column = period.get("year_column", "year")
    task_column = period.get("task_column", "task_type")
    select_value = str(period.get("select", "valid")).strip()
    year_type = str(period.get("year_type", "calendar_year")).lower()

    if year_type not in {"calendar_year", "water_year"}:
        raise ValueError(f"{name}.year_type must be one of: calendar_year, water_year")

    table = pd.read_csv(csv_file, dtype={year_column: str, task_column: str})
    missing_columns = [
        column for column in (year_column, task_column)
        if column not in table.columns
    ]
    if missing_columns:
        raise ValueError(
            f"{name}.file missing required column(s): "
            f"{', '.join(missing_columns)}"
        )

    selected = table[
        table[task_column].astype(str).str.strip().str.lower()
        == select_value.lower()
    ]
    if selected.empty:
        raise ValueError(
            f"{name}.file has no rows where {task_column} == {select_value!r}"
        )

    periods = []
    base_name = period.get("name", name.rsplit(".", 1)[-1])
    for row_index, row in selected.iterrows():
        year_text = str(row[year_column]).strip()
        try:
            year = int(year_text)
        except ValueError as exc:
            raise ValueError(
                f"{name}.file row {row_index} has invalid year: {year_text!r}"
            ) from exc

        start = start_for_year(year, year_type)
        generated = {
            "name": f"{base_name}_{year_label(year, year_type)}",
            "start": start,
            "spinup": period["spinup"],
            "evaluation": period["evaluation"],
        }
        resolved = resolve_time_period(generated, f"{name}[{year_label(year, year_type)}]")
        resolved["source"] = "file"
        resolved["year"] = year
        resolved["year_type"] = year_type
        periods.append(resolved)

    return periods


def start_for_year(year, year_type):
    if year_type == "water_year":
        return pd.Timestamp(year=year - 1, month=10, day=1)
    return pd.Timestamp(year=year, month=1, day=1)


def year_label(year, year_type):
    prefix = "wy" if year_type == "water_year" else "cy"
    return f"{prefix}{year}"


def resolve_time_period(period, name, allow_selected_years=False):
    if not isinstance(period, dict):
        raise TypeError(f"{name} must be a YAML dictionary/object")

    if "start" not in period:
        raise ValueError(f"{name}.start is required")
    if "spinup" not in period:
        raise ValueError(f"{name}.spinup is required")
    if "end" not in period and "evaluation" not in period:
        raise ValueError(f"{name} must define either evaluation or end")

    start = parse_timestamp(period["start"], f"{name}.start")
    spinup = parse_duration(period["spinup"], f"{name}.spinup")
    eval_start = start + spinup
    evaluation_selection = None
    evaluation = period.get("evaluation")

    if isinstance(evaluation, dict):
        if not allow_selected_years:
            raise TypeError(f"{name}.evaluation must be a duration string")
        if "end" not in period or period["end"] is None:
            raise ValueError(
                f"{name}.end is required when evaluation selects years"
            )
        evaluation_selection = normalize_year_selection(
            evaluation,
            f"{name}.evaluation",
        )

    if "end" in period and period["end"] is not None:
        end = parse_timestamp(period["end"], f"{name}.end")
    else:
        evaluation_duration = parse_duration(
            evaluation,
            f"{name}.evaluation",
        )
        end = eval_start + evaluation_duration - NGEN_TIMESTEP

    simulation_time = {
        "start_time": format_timestamp(start),
        "end_time": format_timestamp(end),
    }
    evaluation_time = {
        "start_time": format_timestamp(eval_start),
        "end_time": format_timestamp(end),
    }

    validate_time_subset(
        f"{name}.simulation",
        simulation_time,
        f"{name}.evaluation",
        evaluation_time,
    )

    resolved = {
        "name": period.get("name", name.rsplit(".", 1)[-1]),
        "simulation_time": simulation_time,
        "evaluation_time": evaluation_time,
    }
    if evaluation_selection is not None:
        validate_year_selection(
            evaluation_selection,
            eval_start,
            end,
            f"{name}.evaluation",
        )
        resolved["evaluation_selection"] = evaluation_selection
    return resolved


def normalize_year_selection(selection, name):
    unknown = sorted(set(selection) - {"years", "year_type"})
    if unknown:
        raise ValueError(
            f"{name} contains unsupported field(s): {', '.join(unknown)}"
        )

    years_value = selection.get("years")
    if not isinstance(years_value, list) or not years_value:
        raise ValueError(f"{name}.years must be a non-empty list")

    years = []
    for value in years_value:
        if isinstance(value, bool):
            raise TypeError(f"{name}.years values must be integer years")
        try:
            year = int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"{name}.years values must be integer years"
            ) from exc
        if isinstance(value, float) and not value.is_integer():
            raise TypeError(f"{name}.years values must be integer years")
        if year < 1:
            raise ValueError(f"{name}.years values must be positive")
        years.append(year)

    if len(set(years)) != len(years):
        raise ValueError(f"{name}.years must not contain duplicates")

    year_type = str(selection.get("year_type", "calendar_year")).lower()
    if year_type not in {"calendar_year", "water_year"}:
        raise ValueError(
            f"{name}.year_type must be one of: calendar_year, water_year"
        )

    return {
        "years": sorted(years),
        "year_type": year_type,
    }


def validate_year_selection(selection, eval_start, eval_end, name):
    outside = []
    for year in selection["years"]:
        year_start = start_for_year(year, selection["year_type"])
        next_start = start_for_year(year + 1, selection["year_type"])
        year_end = next_start - NGEN_TIMESTEP
        if year_start < eval_start or year_end > eval_end:
            outside.append(year)

    if outside:
        raise ValueError(
            f"{name}.years must be complete years within the post-spinup "
            f"calibration evaluation interval; outside years: "
            f"{', '.join(str(year) for year in outside)}"
        )


def parse_timestamp(value, name):
    try:
        timestamp = pd.Timestamp(value)
    except Exception as exc:
        raise ValueError(f"{name} has invalid timestamp value: {value}") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{name} has invalid timestamp value: {value}")
    return timestamp


def parse_duration(value, name):
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
        return pd.Timedelta(hours=value)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty duration string")

    parts = value.strip().split()
    if len(parts) != 2:
        raise ValueError(
            f"{name} must use '<number> <unit>', for example '12 months'"
        )

    amount_text, unit_text = parts
    try:
        amount = float(amount_text)
    except ValueError as exc:
        raise ValueError(f"{name} has invalid duration amount: {amount_text}") from exc

    if amount < 0:
        raise ValueError(f"{name} must be non-negative")
    if not amount.is_integer():
        raise ValueError(f"{name} duration amount must be an integer")

    amount = int(amount)
    unit = unit_text.lower()

    if unit in {"hour", "hours", "hr", "hrs", "h"}:
        return pd.Timedelta(hours=amount)
    if unit in {"day", "days", "d"}:
        return pd.Timedelta(days=amount)
    if unit in {"week", "weeks", "wk", "wks", "w"}:
        return pd.Timedelta(weeks=amount)
    if unit in {"month", "months"}:
        return pd.DateOffset(months=amount)
    if unit in {"year", "years", "y"}:
        return pd.DateOffset(years=amount)

    raise ValueError(
        f"{name} has unsupported duration unit '{unit_text}'. Supported "
        "units: hours, days, weeks, months, years"
    )


def validate_time_window(name, window):
    missing = [
        key for key in ("start_time", "end_time")
        if key not in window
    ]
    if missing:
        raise ValueError(
            f"{name} missing required field(s): {', '.join(missing)}"
        )

    start_time = parse_timestamp(window["start_time"], f"{name}.start_time")
    end_time = parse_timestamp(window["end_time"], f"{name}.end_time")

    if start_time > end_time:
        raise ValueError(
            f"{name}.start_time must be less than or equal to "
            f"{name}.end_time ({window['start_time']} > {window['end_time']})."
        )

    return start_time, end_time


def validate_time_subset(parent_name, parent_window, child_name, child_window):
    parent_start, parent_end = validate_time_window(parent_name, parent_window)
    child_start, child_end = validate_time_window(child_name, child_window)

    if child_start < parent_start or child_end > parent_end:
        raise ValueError(
            f"{child_name} must be within {parent_name}. "
            f"{child_name}: {child_start} to {child_end}; "
            f"{parent_name}: {parent_start} to {parent_end}."
        )


def format_timestamp(timestamp):
    return pd.Timestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
