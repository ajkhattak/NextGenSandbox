"""Dependency-light streamflow diagnostics for calibration candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import signal


PEAK_METRIC_NAMES = (
    "mean_peak_timing",
    "mean_absolute_percentage_peak_error",
    "missed_peaks_percent",
)

DIAGNOSTIC_METRIC_NAMES = (
    "number_of_pairs",
    "normalized_nash_sutcliffe_efficiency",
    "kge_correlation",
    "kge_variability_ratio",
    "kge_mean_ratio",
    "percent_bias",
    "q10_relative_error_percent",
    "q90_relative_error_percent",
    "fdc_relative_rmse",
    "nonzero_low_flow_log_mae",
    "observed_zero_flow_percent",
    "simulated_zero_flow_percent",
    "false_flow_percent",
    "missed_flow_percent",
    *PEAK_METRIC_NAMES,
)

FDC_EXCEEDANCES = (0.01, 0.05, 0.10, 0.70, 0.90, 0.95)


@dataclass(frozen=True)
class StreamflowMetricSettings:
    """Runtime settings for inexpensive per-candidate diagnostics."""

    minimum_flow: float = 1.0e-6
    peak_metrics: bool = True
    peak_percentile: float = 80.0
    peak_window: int = 12
    peak_resolution: str = "1h"

    @classmethod
    def from_mapping(
        cls,
        settings: Mapping[str, object] | None,
    ) -> "StreamflowMetricSettings":
        settings = settings or {}
        unknown = sorted(
            set(settings)
            - {
                "minimum_flow",
                "peak_metrics",
                "peak_percentile",
                "peak_window",
                "peak_resolution",
            }
        )
        if unknown:
            raise ValueError(
                "compute_metrics contains unsupported field(s): "
                + ", ".join(unknown)
            )

        configured = cls(
            minimum_flow=float(settings.get("minimum_flow", cls.minimum_flow)),
            peak_metrics=bool(settings.get("peak_metrics", cls.peak_metrics)),
            peak_percentile=float(
                settings.get("peak_percentile", cls.peak_percentile)
            ),
            peak_window=int(settings.get("peak_window", cls.peak_window)),
            peak_resolution=str(
                settings.get("peak_resolution", cls.peak_resolution)
            ),
        )
        configured.validate()
        return configured

    def validate(self) -> None:
        if self.minimum_flow <= 0:
            raise ValueError("compute_metrics.minimum_flow must be positive")
        if not 0 <= self.peak_percentile <= 100:
            raise ValueError(
                "compute_metrics.peak_percentile must be between 0 and 100"
            )
        if self.peak_window < 1:
            raise ValueError("compute_metrics.peak_window must be at least 1")
        try:
            resolution = pd.to_timedelta(self.peak_resolution)
        except ValueError as exc:
            raise ValueError(
                "compute_metrics.peak_resolution must be a pandas duration"
            ) from exc
        if resolution <= pd.Timedelta(0):
            raise ValueError(
                "compute_metrics.peak_resolution must be positive"
            )


def compute_streamflow_diagnostics(
    observed: pd.Series,
    simulated: pd.Series,
    settings: StreamflowMetricSettings,
) -> pd.Series:
    """Compute scalar diagnostics from aligned, finite streamflow pairs."""
    paired = pd.concat(
        [observed.rename("observed"), simulated.rename("simulated")],
        axis=1,
        join="inner",
    ).dropna()
    paired = paired[
        np.isfinite(paired["observed"].to_numpy())
        & np.isfinite(paired["simulated"].to_numpy())
    ]
    result = {name: np.nan for name in DIAGNOSTIC_METRIC_NAMES}
    result["number_of_pairs"] = float(len(paired))
    if paired.empty:
        return pd.Series(result, dtype=float)

    obs = paired["observed"].to_numpy(dtype=float)
    sim = paired["simulated"].to_numpy(dtype=float)
    result.update(_distribution_metrics(obs, sim, settings.minimum_flow))

    if settings.peak_metrics:
        result.update(
            _peak_metrics(
                obs,
                sim,
                paired.index,
                percentile=settings.peak_percentile,
                window=settings.peak_window,
                resolution=settings.peak_resolution,
            )
        )
    return pd.Series(result, dtype=float)


def _distribution_metrics(
    observed: np.ndarray,
    simulated: np.ndarray,
    minimum_flow: float,
) -> dict[str, float]:
    observed_mean = float(np.mean(observed))
    simulated_mean = float(np.mean(simulated))
    observed_std = float(np.std(observed))
    simulated_std = float(np.std(simulated))

    denominator = float(np.sum((observed - observed_mean) ** 2))
    nse = (
        1.0 - float(np.sum((simulated - observed) ** 2)) / denominator
        if denominator > 0
        else np.nan
    )
    nnse = 1.0 / (2.0 - nse) if np.isfinite(nse) else np.nan

    correlation = (
        float(np.corrcoef(observed, simulated)[0, 1])
        if len(observed) > 1 and observed_std > 0 and simulated_std > 0
        else np.nan
    )
    variability_ratio = (
        simulated_std / observed_std if observed_std > 0 else np.nan
    )
    mean_ratio = simulated_mean / observed_mean if observed_mean != 0 else np.nan
    percent_bias = (
        100.0 * float(np.sum(simulated - observed)) / float(np.sum(observed))
        if np.sum(observed) != 0
        else np.nan
    )

    q10_error = _quantile_relative_error(
        observed,
        simulated,
        exceedance=0.10,
        minimum_flow=minimum_flow,
    )
    q90_error = _quantile_relative_error(
        observed,
        simulated,
        exceedance=0.90,
        minimum_flow=minimum_flow,
    )
    fdc_errors = [
        _quantile_relative_error(
            observed,
            simulated,
            exceedance=exceedance,
            minimum_flow=minimum_flow,
            as_percent=False,
        )
        for exceedance in FDC_EXCEEDANCES
    ]

    observed_nonzero = observed > minimum_flow
    simulated_nonzero = simulated > minimum_flow
    observed_zero = ~observed_nonzero
    simulated_zero = ~simulated_nonzero

    low_flow_log_mae = np.nan
    if observed_nonzero.any():
        threshold = float(np.quantile(observed[observed_nonzero], 0.30))
        low_flow = observed_nonzero & (observed <= threshold)
        if low_flow.any():
            low_flow_log_mae = float(
                np.mean(
                    np.abs(
                        np.log10(np.maximum(simulated[low_flow], minimum_flow))
                        - np.log10(observed[low_flow])
                    )
                )
            )

    return {
        "normalized_nash_sutcliffe_efficiency": nnse,
        "kge_correlation": correlation,
        "kge_variability_ratio": variability_ratio,
        "kge_mean_ratio": mean_ratio,
        "percent_bias": percent_bias,
        "q10_relative_error_percent": q10_error,
        "q90_relative_error_percent": q90_error,
        "fdc_relative_rmse": float(np.sqrt(np.mean(np.square(fdc_errors)))),
        "nonzero_low_flow_log_mae": low_flow_log_mae,
        "observed_zero_flow_percent": 100.0 * float(np.mean(observed_zero)),
        "simulated_zero_flow_percent": 100.0 * float(np.mean(simulated_zero)),
        "false_flow_percent": (
            100.0 * float(np.mean(simulated_nonzero[observed_zero]))
            if observed_zero.any()
            else np.nan
        ),
        "missed_flow_percent": (
            100.0 * float(np.mean(simulated_zero[observed_nonzero]))
            if observed_nonzero.any()
            else np.nan
        ),
    }


def _quantile_relative_error(
    observed: np.ndarray,
    simulated: np.ndarray,
    *,
    exceedance: float,
    minimum_flow: float,
    as_percent: bool = True,
) -> float:
    quantile = 1.0 - exceedance
    observed_flow = max(float(np.quantile(observed, quantile)), minimum_flow)
    simulated_flow = max(float(np.quantile(simulated, quantile)), minimum_flow)
    error = (simulated_flow - observed_flow) / observed_flow
    return 100.0 * error if as_percent else error


def _peak_metrics(
    observed: np.ndarray,
    simulated: np.ndarray,
    index: pd.Index,
    *,
    percentile: float,
    window: int,
    resolution: str,
) -> dict[str, float]:
    result = {name: np.nan for name in PEAK_METRIC_NAMES}
    if not isinstance(index, pd.DatetimeIndex) or len(observed) == 0:
        return result

    prominent_peaks, _ = signal.find_peaks(
        observed,
        distance=100,
        prominence=np.std(observed),
    )
    result["mean_peak_timing"] = _mean_peak_timing(
        prominent_peaks,
        simulated,
        index,
        window=window,
        resolution=resolution,
    )
    result["mean_absolute_percentage_peak_error"] = _peak_mape(
        prominent_peaks,
        observed,
        simulated,
    )
    result["missed_peaks_percent"] = 100.0 * _missed_peaks_fraction(
        observed,
        simulated,
        index,
        percentile=percentile,
        window=window,
        resolution=resolution,
    )
    return result


def _mean_peak_timing(
    peaks: np.ndarray,
    simulated: np.ndarray,
    index: pd.DatetimeIndex,
    *,
    window: int,
    resolution: str,
) -> float:
    timing_errors = []
    resolution_delta = pd.to_timedelta(resolution)
    for peak_index in peaks:
        if not _has_complete_window(
            index,
            peak_index,
            window=window,
            resolution=resolution,
        ):
            continue
        if (
            simulated[peak_index] > simulated[peak_index - 1]
            and simulated[peak_index] > simulated[peak_index + 1]
        ):
            simulated_peak_index = peak_index
        else:
            start = peak_index - window
            values = simulated[start:peak_index + window + 1]
            simulated_peak_index = start + int(np.argmax(values))
        timing_errors.append(
            abs((index[peak_index] - index[simulated_peak_index]) / resolution_delta)
        )
    return float(np.mean(timing_errors)) if timing_errors else np.nan


def _peak_mape(
    peaks: np.ndarray,
    observed: np.ndarray,
    simulated: np.ndarray,
) -> float:
    if len(peaks) == 0:
        return np.nan
    observed_peaks = observed[peaks]
    simulated_at_observed_peaks = simulated[peaks]
    return float(
        100.0
        * np.mean(
            np.abs(
                (simulated_at_observed_peaks - observed_peaks)
                / observed_peaks
            )
        )
    )


def _missed_peaks_fraction(
    observed: np.ndarray,
    simulated: np.ndarray,
    index: pd.DatetimeIndex,
    *,
    percentile: float,
    window: int,
    resolution: str,
) -> float:
    observed_peaks, _ = signal.find_peaks(
        observed,
        distance=30,
        height=np.percentile(observed, percentile),
    )
    simulated_peaks, _ = signal.find_peaks(
        simulated,
        distance=30,
        height=np.percentile(simulated, percentile),
    )
    if len(observed_peaks) == 0:
        return 0.0

    missed = 0
    for peak_index in observed_peaks:
        if not _has_complete_window(
            index,
            peak_index,
            window=window,
            resolution=resolution,
        ):
            continue
        if not np.any(np.abs(simulated_peaks - peak_index) <= window):
            missed += 1
    return float(missed / len(observed_peaks))


def _has_complete_window(
    index: pd.DatetimeIndex,
    center: int,
    *,
    window: int,
    resolution: str,
) -> bool:
    if center - window < 0 or center + window >= len(index):
        return False
    return (
        pd.date_range(
            index[center - window],
            index[center + window],
            freq=resolution,
        ).size
        == 2 * window + 1
    )
