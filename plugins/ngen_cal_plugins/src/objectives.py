from __future__ import annotations

import json
import math
import os

import numpy as np
import pandas as pd
from hydrotools.metrics.metrics import (
    kling_gupta_efficiency,
    nash_sutcliffe_efficiency,
)

NONFINITE_METRIC_LOSS = 1000.0
LOW_FLOW_EPSILON = 1.0e-6
NONZERO_LOW_FLOW_EXCEEDANCE = 0.7
LOW_FLOW_EXCEEDANCES = (0.7, 0.9, 0.95)
HIGH_FLOW_EXCEEDANCES = (0.01, 0.05, 0.1)
FDC_EXCEEDANCES = HIGH_FLOW_EXCEEDANCES + LOW_FLOW_EXCEEDANCES
COMPOSITE_METRICS = {
    "kge",
    "nse",
    "nnse",
    "log_kge",
    "fdc",
    "nonzero_low_flow_log_mae",
}
STREAMFLOW_ONLY_METRICS = {
    "log_kge",
    "fdc",
    "nonzero_low_flow_log_mae",
}
COMPOSITE_OBJECTIVE_ENV = "NGEN_CAL_COMPOSITE_OBJECTIVE"
_composite_metric_weights: dict[str, float] | None = None


def kge_multi_variable(
    observed: pd.Series,
    simulated: pd.Series,
) -> float:
    """Return the L2 norm of KGE losses calculated per variable."""
    return _multi_variable_loss(
        observed,
        simulated,
        kling_gupta_efficiency,
        "KGE",
    )


def nse_multi_variable(
    observed: pd.Series,
    simulated: pd.Series,
) -> float:
    """Return the L2 norm of standard NSE losses calculated per variable."""
    return _multi_variable_loss(
        observed,
        simulated,
        nash_sutcliffe_efficiency,
        "NSE",
    )


def nnse_multi_variable(
    observed: pd.Series,
    simulated: pd.Series,
) -> float:
    """Return the L2 norm of normalized NSE losses calculated per variable."""

    def nnse(obs, sim):
        nse = nash_sutcliffe_efficiency(obs, sim)
        return 1.0 / (2.0 - nse)

    return _multi_variable_loss(
        observed,
        simulated,
        nnse,
        "NNSE",
    )


def configure_composite_objective(metric_weights: dict[str, float]) -> None:
    """Set the metric weights used by :func:`composite_objective`."""
    unknown = set(metric_weights) - COMPOSITE_METRICS
    if unknown:
        raise ValueError(
            "Unsupported composite objective metric(s): "
            + ", ".join(sorted(unknown))
        )
    if not metric_weights:
        raise ValueError("Composite objective metrics cannot be empty")
    validated = {}
    for name, raw_weight in metric_weights.items():
        if isinstance(raw_weight, bool):
            raise TypeError(
                f"Weight for composite metric '{name}' must be numeric"
            )
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"Weight for composite metric '{name}' must be numeric"
            ) from exc
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(
                f"Weight for composite metric '{name}' must be finite and "
                "greater than zero"
            )
        validated[name] = weight
    if not math.isclose(
        sum(validated.values()),
        1.0,
        rel_tol=1.0e-9,
        abs_tol=1.0e-9,
    ):
        raise ValueError(
            "Composite objective metric weights must sum to 1.0; "
            f"provided sum: {sum(validated.values()):.12g}"
        )

    global _composite_metric_weights
    _composite_metric_weights = validated
    # Spawned PSO workers import this module afresh. Environment inheritance
    # carries the same validated recipe into each worker process.
    os.environ[COMPOSITE_OBJECTIVE_ENV] = json.dumps(validated)


def composite_objective(
    observed: pd.Series,
    simulated: pd.Series,
) -> float:
    """Return a weighted L2 loss assembled from configured base metrics."""
    metric_weights = _configured_composite_metric_weights()

    observed_variables = _split_variables(observed, "observed")
    simulated_variables = _split_variables(simulated, "simulated")
    _require_matching_variables(observed_variables, simulated_variables)

    variable_losses = []
    for variable in sorted(observed_variables):
        pairs = _aligned_pairs(
            observed_variables[variable],
            simulated_variables[variable],
            variable,
        )
        weighted_losses = []
        for metric_name, weight in metric_weights.items():
            if metric_name in STREAMFLOW_ONLY_METRICS and variable != "streamflow":
                continue
            loss = _composite_metric_loss(metric_name, pairs, variable)
            weighted_losses.append((weight * loss) ** 2)

        if weighted_losses:
            variable_losses.append(sum(weighted_losses))

    if not variable_losses:
        raise ValueError(
            "The configured objective metrics do not apply to any available "
            "observation variable. log_kge, fdc, and "
            "nonzero_low_flow_log_mae require streamflow."
        )
    return float(np.sqrt(sum(variable_losses)))


def _configured_composite_metric_weights() -> dict[str, float]:
    if _composite_metric_weights is not None:
        return _composite_metric_weights

    encoded = os.environ.get(COMPOSITE_OBJECTIVE_ENV)
    if encoded:
        weights = json.loads(encoded)
        configure_composite_objective(weights)
        assert _composite_metric_weights is not None
        return _composite_metric_weights

    raise RuntimeError(
        "Composite objective was not configured. Ensure ConfigureObjective "
        "is loaded by ngen-cal."
    )


def _multi_variable_loss(observed, simulated, metric, metric_name):
    observed_variables = _split_variables(observed, "observed")
    simulated_variables = _split_variables(simulated, "simulated")
    _require_matching_variables(observed_variables, simulated_variables)

    squared_losses = []
    for variable in sorted(observed_variables):
        pairs = _aligned_pairs(
            observed_variables[variable],
            simulated_variables[variable],
            variable,
        )
        loss = _metric_loss(
            pairs["observed"],
            pairs["simulated"],
            metric,
            metric_name,
            variable,
        )
        squared_losses.append(loss ** 2)

    return float(np.sqrt(sum(squared_losses)))


def _composite_metric_loss(metric_name, pairs, variable):
    observed = pairs["observed"]
    simulated = pairs["simulated"]
    if metric_name == "kge":
        return _metric_loss(
            observed,
            simulated,
            kling_gupta_efficiency,
            "KGE",
            variable,
        )
    if metric_name == "nse":
        return _metric_loss(
            observed,
            simulated,
            nash_sutcliffe_efficiency,
            "NSE",
            variable,
        )
    if metric_name == "nnse":
        def nnse(obs, sim):
            nse = nash_sutcliffe_efficiency(obs, sim)
            return 1.0 / (2.0 - nse)

        return _metric_loss(
            observed,
            simulated,
            nnse,
            "NNSE",
            variable,
        )
    if metric_name == "log_kge":
        return _metric_loss(
            np.log10(observed.clip(lower=LOW_FLOW_EPSILON)),
            np.log10(simulated.clip(lower=LOW_FLOW_EPSILON)),
            kling_gupta_efficiency,
            "log10-KGE",
            variable,
        )
    if metric_name == "fdc":
        return _fdc_exceedance_loss(
            observed,
            simulated,
            FDC_EXCEEDANCES,
        )
    if metric_name == "nonzero_low_flow_log_mae":
        return _nonzero_low_flow_log_mae_loss(observed, simulated)
    raise ValueError(f"Unsupported composite objective metric: {metric_name}")


def _require_matching_variables(observed_variables, simulated_variables):
    if observed_variables.keys() == simulated_variables.keys():
        return
    missing_simulated = sorted(
        observed_variables.keys() - simulated_variables.keys()
    )
    missing_observed = sorted(
        simulated_variables.keys() - observed_variables.keys()
    )
    details = []
    if missing_simulated:
        details.append(
            f"missing simulated variables: {', '.join(missing_simulated)}"
        )
    if missing_observed:
        details.append(
            f"missing observed variables: {', '.join(missing_observed)}"
        )
    raise ValueError(
        "Observed and simulated variables do not match; "
        + "; ".join(details)
    )


def _aligned_pairs(observed, simulated, variable):
    pairs = pd.concat(
        [
            observed.rename("observed"),
            simulated.rename("simulated"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if pairs.empty:
        raise ValueError(
            f"No aligned observed and simulated values for {variable}"
        )
    return pairs


def _metric_loss(observed, simulated, metric, metric_name, variable):
    score = float(metric(observed, simulated))
    if not np.isfinite(score):
        print(
            f"WARNING: {metric_name} is not finite for {variable}; "
            f"using loss penalty {NONFINITE_METRIC_LOSS}. "
            f"pairs={len(observed)}, "
            f"observed_std={observed.std()}, "
            f"simulated_std={simulated.std()}, "
            f"observed_nan={observed.isna().sum()}, "
            f"simulated_nan={simulated.isna().sum()}"
        )
        return NONFINITE_METRIC_LOSS
    return abs(1.0 - score)


def _fdc_exceedance_loss(observed, simulated, exceedances):
    obs = observed.clip(lower=LOW_FLOW_EPSILON).to_numpy(dtype=float)
    sim = simulated.clip(lower=LOW_FLOW_EPSILON).to_numpy(dtype=float)
    quantiles = [1.0 - exceedance for exceedance in exceedances]
    obs_quantiles = np.quantile(obs, quantiles)
    sim_quantiles = np.quantile(sim, quantiles)
    relative_error = (sim_quantiles - obs_quantiles) / obs_quantiles
    return float(np.sqrt(np.mean(relative_error ** 2)))


def _nonzero_low_flow_log_mae_loss(observed, simulated):
    positive_observed = observed[observed > LOW_FLOW_EPSILON]
    if positive_observed.empty:
        raise ValueError(
            "nonzero_low_flow_log_mae requires at least one observed "
            f"streamflow value greater than {LOW_FLOW_EPSILON}"
        )

    low_flow_quantile = 1.0 - NONZERO_LOW_FLOW_EXCEEDANCE
    low_flow_threshold = float(
        np.quantile(positive_observed.to_numpy(dtype=float), low_flow_quantile)
    )
    low_flow_mask = (
        (observed > LOW_FLOW_EPSILON)
        & (observed <= low_flow_threshold)
    )
    if not low_flow_mask.any():
        raise ValueError(
            "nonzero_low_flow_log_mae found no nonzero observed low-flow "
            "streamflow values"
        )

    obs_log = np.log10(observed[low_flow_mask].clip(lower=LOW_FLOW_EPSILON))
    sim_log = np.log10(simulated[low_flow_mask].clip(lower=LOW_FLOW_EPSILON))
    log_error = (sim_log - obs_log).abs()
    return float(np.mean(log_error))


def _split_variables(series: pd.Series, label: str) -> dict[str, pd.Series]:
    if not isinstance(series, pd.Series):
        raise TypeError(f"{label} values must be a pandas Series")
    if not isinstance(series.index, pd.MultiIndex):
        return {"streamflow": series}
    if "variable" not in series.index.names:
        raise ValueError(
            f"{label} values must use a MultiIndex with a 'variable' level"
        )

    variables = set(series.index.get_level_values("variable"))
    if not variables:
        raise ValueError(f"{label} values contain no variables")
    return {
        variable: series.xs(variable, level="variable")
        for variable in variables
    }
