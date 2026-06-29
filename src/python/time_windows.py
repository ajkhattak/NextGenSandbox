from __future__ import annotations

import pandas as pd


NGEN_TIMESTEP = pd.Timedelta(hours=1)


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


def normalize_simulation_time_config(dsim, task_type):
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
            raise ValueError("simulation.time.control is required for task_type control")
        dsim["simulation_time"] = resolve_time_period(
            time_config["control"],
            "simulation.time.control",
        )["simulation_time"]
        return

    if task_type in ["calibration", "calibvalid", "restart"]:
        if "calibration" not in time_config:
            raise ValueError(
                "simulation.time.calibration is required for task_type "
                f"{task_type}"
            )

        calibration = resolve_time_period(
            time_config["calibration"],
            "simulation.time.calibration",
        )
        dsim["calibration_time"] = calibration["simulation_time"]
        dsim["calib_eval_time"] = calibration["evaluation_time"]

        if task_type == "calibvalid":
            validations = resolve_validation_periods(time_config)
            if len(validations) > 1:
                raise NotImplementedError(
                    "Multiple simulation.time.validations entries are parsed but "
                    "the runner currently supports one validation window. Keep one "
                    "validation entry until cross-validation runner support is added."
                )
            validation = validations[0]
            dsim["validation_time"] = validation["simulation_time"]
            dsim["valid_eval_time"] = validation["evaluation_time"]

        return

    if task_type == "validation":
        validations = resolve_validation_periods(time_config)
        if len(validations) > 1:
            raise NotImplementedError(
                "Multiple simulation.time.validations entries are parsed but "
                "the runner currently supports one validation window. Keep one "
                "validation entry until cross-validation runner support is added."
            )
        validation = validations[0]
        dsim["validation_time"] = validation["simulation_time"]
        dsim["valid_eval_time"] = validation["evaluation_time"]


def resolve_validation_periods(time_config):
    validations = time_config.get("validations")
    if validations is None:
        raise ValueError("simulation.time.validations is required")
    if not isinstance(validations, list) or not validations:
        raise ValueError("simulation.time.validations must be a non-empty list")

    return [
        resolve_time_period(
            period,
            f"simulation.time.validations[{index}]",
        )
        for index, period in enumerate(validations)
    ]


def resolve_time_period(period, name):
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

    if "end" in period and period["end"] is not None:
        end = parse_timestamp(period["end"], f"{name}.end")
    else:
        evaluation = parse_duration(period["evaluation"], f"{name}.evaluation")
        end = eval_start + evaluation - NGEN_TIMESTEP

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

    return {
        "name": period.get("name", name.rsplit(".", 1)[-1]),
        "simulation_time": simulation_time,
        "evaluation_time": evaluation_time,
    }


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
