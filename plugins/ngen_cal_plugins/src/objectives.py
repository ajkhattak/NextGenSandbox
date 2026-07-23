from __future__ import annotations

import numpy as np
import pandas as pd
from hydrotools.metrics.metrics import (
    kling_gupta_efficiency,
    nash_sutcliffe_efficiency,
)

NONFINITE_METRIC_LOSS = 1000.0
LOW_FLOW_EPSILON = 1.0e-6
LOW_FLOW_QUANTILES = (0.7, 0.9, 0.95)
LOW_FLOW_EXCEEDANCES = (0.7, 0.9, 0.95)
HIGH_FLOW_EXCEEDANCES = (0.01, 0.05, 0.1)


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


def kge_low_flow(
    observed: pd.Series,
    simulated: pd.Series,
) -> float:
    """Return a KGE loss with extra pressure on log-flow and FDC low flows."""
    return _efficiency_low_flow_loss(
        observed,
        simulated,
        kling_gupta_efficiency,
        "KGE",
    )


def nse_low_flow(
    observed: pd.Series,
    simulated: pd.Series,
) -> float:
    """Return an NSE loss with extra pressure on log-flow and FDC low flows."""
    return _efficiency_low_flow_loss(
        observed,
        simulated,
        nash_sutcliffe_efficiency,
        "NSE",
    )


def kge_low_high_flow(
    observed: pd.Series,
    simulated: pd.Series,
) -> float:
    """Return a KGE loss balanced across full, low, and high-flow behavior."""
    observed_variables = _split_variables(observed, "observed")
    simulated_variables = _split_variables(simulated, "simulated")

    if observed_variables.keys() != simulated_variables.keys():
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

    squared_losses = []
    for variable in sorted(observed_variables):
        pairs = _aligned_pairs(
            observed_variables[variable],
            simulated_variables[variable],
            variable,
        )
        kge_loss = _metric_loss(
            pairs["observed"],
            pairs["simulated"],
            kling_gupta_efficiency,
            "KGE",
            variable,
        )
        if variable == "streamflow":
            log_kge_loss = _metric_loss(
                np.log10(pairs["observed"].clip(lower=LOW_FLOW_EPSILON)),
                np.log10(pairs["simulated"].clip(lower=LOW_FLOW_EPSILON)),
                kling_gupta_efficiency,
                "log10-KGE",
                variable,
            )
            low_flow_loss = _fdc_exceedance_loss(
                pairs["observed"],
                pairs["simulated"],
                LOW_FLOW_EXCEEDANCES,
            )
            high_flow_loss = _fdc_exceedance_loss(
                pairs["observed"],
                pairs["simulated"],
                HIGH_FLOW_EXCEEDANCES,
            )
            squared_losses.append(
                (0.4 * kge_loss) ** 2
                + (0.25 * log_kge_loss) ** 2
                + (0.2 * low_flow_loss) ** 2
                + (0.15 * high_flow_loss) ** 2
            )
        else:
            squared_losses.append(kge_loss ** 2)

    return float(np.sqrt(sum(squared_losses)))


def _efficiency_low_flow_loss(
    observed: pd.Series,
    simulated: pd.Series,
    metric,
    metric_name,
) -> float:
    observed_variables = _split_variables(observed, "observed")
    simulated_variables = _split_variables(simulated, "simulated")

    if observed_variables.keys() != simulated_variables.keys():
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

    squared_losses = []
    for variable in sorted(observed_variables):
        pairs = _aligned_pairs(
            observed_variables[variable],
            simulated_variables[variable],
            variable,
        )
        efficiency_loss = _metric_loss(
            pairs["observed"],
            pairs["simulated"],
            metric,
            metric_name,
            variable,
        )
        if variable == "streamflow":
            log_efficiency_loss = _metric_loss(
                np.log10(pairs["observed"].clip(lower=LOW_FLOW_EPSILON)),
                np.log10(pairs["simulated"].clip(lower=LOW_FLOW_EPSILON)),
                metric,
                f"log10-{metric_name}",
                variable,
            )
            fdc_loss = _low_flow_fdc_loss(
                pairs["observed"],
                pairs["simulated"],
            )
            squared_losses.append(
                (0.5 * efficiency_loss) ** 2
                + (0.3 * log_efficiency_loss) ** 2
                + (0.2 * fdc_loss) ** 2
            )
        else:
            squared_losses.append(efficiency_loss ** 2)

    return float(np.sqrt(sum(squared_losses)))


def _multi_variable_loss(observed, simulated, metric, metric_name):
    observed_variables = _split_variables(observed, "observed")
    simulated_variables = _split_variables(simulated, "simulated")

    if observed_variables.keys() != simulated_variables.keys():
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


def _low_flow_fdc_loss(observed, simulated):
    obs = observed.clip(lower=LOW_FLOW_EPSILON).to_numpy(dtype=float)
    sim = simulated.clip(lower=LOW_FLOW_EPSILON).to_numpy(dtype=float)
    obs_quantiles = np.quantile(obs, LOW_FLOW_QUANTILES)
    sim_quantiles = np.quantile(sim, LOW_FLOW_QUANTILES)
    relative_error = (sim_quantiles - obs_quantiles) / obs_quantiles
    return float(np.sqrt(np.mean(relative_error ** 2)))


def _fdc_exceedance_loss(observed, simulated, exceedances):
    obs = observed.clip(lower=LOW_FLOW_EPSILON).to_numpy(dtype=float)
    sim = simulated.clip(lower=LOW_FLOW_EPSILON).to_numpy(dtype=float)
    quantiles = [1.0 - exceedance for exceedance in exceedances]
    obs_quantiles = np.quantile(obs, quantiles)
    sim_quantiles = np.quantile(sim, quantiles)
    relative_error = (sim_quantiles - obs_quantiles) / obs_quantiles
    return float(np.sqrt(np.mean(relative_error ** 2)))


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
