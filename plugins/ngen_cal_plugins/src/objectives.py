from __future__ import annotations

import numpy as np
import pandas as pd
from hydrotools.metrics.metrics import (
    kling_gupta_efficiency,
    nash_sutcliffe_efficiency,
)


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
        pairs = pd.concat(
            [
                observed_variables[variable].rename("observed"),
                simulated_variables[variable].rename("simulated"),
            ],
            axis=1,
            join="inner",
        ).dropna()
        if pairs.empty:
            raise ValueError(
                f"No aligned observed and simulated values for {variable}"
            )

        score = float(metric(pairs["observed"], pairs["simulated"]))
        if not np.isfinite(score):
            raise ValueError(f"{metric_name} is not finite for {variable}")
        squared_losses.append((1.0 - score) ** 2)

    return float(np.sqrt(sum(squared_losses)))


def _split_variables(series: pd.Series, label: str) -> dict[str, pd.Series]:
    if not isinstance(series, pd.Series):
        raise TypeError(f"{label} values must be a pandas Series")
    if not isinstance(series.index, pd.MultiIndex):
        return {"observation": series}
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
