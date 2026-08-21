from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import yaml


SUPPORTED_OPTIMIZERS = {"dds", "pso"}
OBJECTIVE_ALIASES = {
    "kge": "ngen_cal_plugins.objectives.kge_multi_variable",
    "nse": "ngen_cal_plugins.objectives.nse_multi_variable",
    "nnse": "ngen_cal_plugins.objectives.nnse_multi_variable",
}
COMPOSITE_OBJECTIVE = "ngen_cal_plugins.objectives.composite_objective"
COMPOSITE_METRICS = {
    "kge",
    "nse",
    "nnse",
    "log_kge",
    "fdc",
    "q10_skill",
    "q90_skill",
    "nonzero_low_flow_log_mae",
}


@dataclass(frozen=True)
class CalibrationSettings:
    algorithm: str
    iterations: int
    random_seed: int
    objective: str
    objective_metrics: dict[str, float]
    optimizer_settings: dict[str, Any]
    optimizer_settings_file: Path | None = None


def load_calibration_settings(
    sandbox_config: dict[str, Any],
    sandbox_config_path: str | Path,
    sandbox_dir: str | Path,
) -> CalibrationSettings:
    calibration = sandbox_config.get("calibration", {}) or {}
    if not isinstance(calibration, dict):
        raise TypeError("calibration must be a mapping")
    _reject_unknown_fields(
        calibration,
        {"optimizer", "objective"},
        "calibration",
    )

    optimizer = calibration.get("optimizer", {}) or {}
    if not isinstance(optimizer, dict):
        raise TypeError("calibration.optimizer must be a mapping")
    _reject_unknown_fields(
        optimizer,
        {"algorithm", "iterations", "random_seed", "settings_file"},
        "calibration.optimizer",
    )

    algorithm = str(optimizer.get("algorithm", "dds")).strip().lower()
    if algorithm not in SUPPORTED_OPTIMIZERS:
        supported = ", ".join(sorted(SUPPORTED_OPTIMIZERS))
        raise ValueError(
            f"calibration.optimizer.algorithm must be one of: {supported}"
        )

    iterations = _positive_integer(
        optimizer.get("iterations", 300),
        "calibration.optimizer.iterations",
    )
    random_seed = _integer(
        optimizer.get("random_seed", 444),
        "calibration.optimizer.random_seed",
    )

    objective_config = calibration.get("objective", {}) or {}
    if not isinstance(objective_config, dict):
        raise TypeError("calibration.objective must be a mapping")
    _reject_unknown_fields(
        objective_config,
        {"function"},
        "calibration.objective",
    )
    objective_spec = objective_config.get("function", "kge")
    objective_metrics = {}
    if isinstance(objective_spec, dict):
        objective_metrics = _objective_metric_weights(objective_spec)
        objective = COMPOSITE_OBJECTIVE
    elif not isinstance(objective_spec, str) or not objective_spec.strip():
        raise ValueError(
            "calibration.objective.function must be a non-empty string or "
            "a mapping of metric names to weights"
        )
    else:
        objective = objective_spec.strip()
        objective_key = objective.lower()
        if objective_key in OBJECTIVE_ALIASES:
            objective = OBJECTIVE_ALIASES[objective_key]
        elif "." not in objective:
            supported = ", ".join(sorted(OBJECTIVE_ALIASES))
            raise ValueError(
                "calibration.objective.function must be one of "
                f"{supported}, a metric-weight mapping, or a custom "
                "objective import path"
            )

    optimizer_settings = {}
    optimizer_settings_file = None
    settings_file = optimizer.get("settings_file")
    if algorithm == "pso":
        if settings_file is None:
            optimizer_settings_file = (
                Path(sandbox_dir) / "configs" / "optimizers" / "pso.yaml"
            )
        else:
            if not isinstance(settings_file, str) or not settings_file.strip():
                raise ValueError(
                    "calibration.optimizer.settings_file must be a non-empty path"
                )
            optimizer_settings_file = Path(settings_file).expanduser()
            if not optimizer_settings_file.is_absolute():
                optimizer_settings_file = (
                    Path(sandbox_config_path).resolve().parent
                    / optimizer_settings_file
                )
        optimizer_settings_file = optimizer_settings_file.resolve()
        if not optimizer_settings_file.is_file():
            raise FileNotFoundError(
                "PSO settings file does not exist: "
                f"{optimizer_settings_file}"
            )
        with optimizer_settings_file.open("r") as file:
            optimizer_settings = yaml.safe_load(file) or {}
        if not isinstance(optimizer_settings, dict):
            raise TypeError(
                "PSO settings file must contain a YAML mapping: "
                f"{optimizer_settings_file}"
            )
    elif settings_file is not None:
        raise ValueError(
            "calibration.optimizer.settings_file is only valid when "
            "calibration.optimizer.algorithm is pso"
        )

    return CalibrationSettings(
        algorithm=algorithm,
        iterations=iterations,
        random_seed=random_seed,
        objective=objective,
        objective_metrics=objective_metrics,
        optimizer_settings=optimizer_settings,
        optimizer_settings_file=optimizer_settings_file,
    )


def _objective_metric_weights(value: dict[Any, Any]) -> dict[str, float]:
    if not value:
        raise ValueError(
            "calibration.objective.function metric mapping cannot be empty"
        )

    weights = {}
    for raw_name, raw_weight in value.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(
                "calibration.objective.function metric names must be "
                "non-empty strings"
            )
        name = raw_name.strip().lower()
        if name not in COMPOSITE_METRICS:
            supported = ", ".join(sorted(COMPOSITE_METRICS))
            raise ValueError(
                "Unsupported calibration objective metric "
                f"'{raw_name}'. Supported metrics: {supported}"
            )
        if isinstance(raw_weight, bool):
            raise TypeError(
                f"Weight for calibration objective metric '{name}' must "
                "be a number"
            )
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"Weight for calibration objective metric '{name}' must "
                "be a number"
            ) from exc
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(
                f"Weight for calibration objective metric '{name}' must "
                "be finite and greater than zero"
            )
        weights[name] = weight

    if not math.isclose(
        sum(weights.values()),
        1.0,
        rel_tol=1.0e-9,
        abs_tol=1.0e-9,
    ):
        raise ValueError(
            "calibration.objective.function metric weights must sum to 1.0; "
            f"provided sum: {sum(weights.values()):.12g}"
        )
    return weights


def absolutize_optimizer_settings_file(
    sandbox_config: dict[str, Any],
    sandbox_config_path: str | Path,
) -> None:
    calibration = sandbox_config.get("calibration") or {}
    if not isinstance(calibration, dict):
        return
    optimizer = calibration.get("optimizer") or {}
    if not isinstance(optimizer, dict):
        return
    settings_file = optimizer.get("settings_file")
    if not settings_file:
        return

    path = Path(settings_file).expanduser()
    if not path.is_absolute():
        optimizer["settings_file"] = str(
            (Path(sandbox_config_path).resolve().parent / path).resolve()
        )


def _positive_integer(value: Any, field_name: str) -> int:
    result = _integer(value, field_name)
    if result < 1:
        raise ValueError(f"{field_name} must be greater than zero")
    return result


def _integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be an integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise TypeError(f"{field_name} must be an integer")
    return result


def _reject_unknown_fields(
    config: dict[str, Any],
    supported: set[str],
    field_name: str,
) -> None:
    unknown = sorted(set(config) - supported)
    if unknown:
        raise ValueError(
            f"{field_name} contains unsupported field(s): "
            f"{', '.join(unknown)}"
        )
