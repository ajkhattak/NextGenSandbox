"""
Taken from ngen-cal (ngen benchmarking)
Courtesy of Austin & Nels
"""

from __future__ import annotations

import typing

from ngen.cal import hookimpl
from hydrotools.metrics.metrics import (
    coefficient_of_persistence,
    kling_gupta_efficiency,
    mean_error,
    mean_squared_error,
    nash_sutcliffe_efficiency,
    root_mean_squared_error,
    volumetric_efficiency,
)
import numpy as np
import pandas as pd
from pathlib import Path

from .streamflow_metrics import (
    DIAGNOSTIC_METRIC_NAMES,
    StreamflowMetricSettings,
    compute_streamflow_diagnostics,
)

#from download_nwm_streamflow import

if typing.TYPE_CHECKING:
    from datetime import datetime
    from ngen.cal.meta import JobMeta
    from ngen.cal.model import ModelExec
    from hypy.nexus import Nexus

class ComputeMetrics:
    def __init__(self) -> None:
        self.sim: pd.Series | None = None
        self.obs: pd.Series | None = None
        self.first_iteration: bool = True
        self.save_obs_nwm: bool = True
        self.eval_range: tuple[datetime, datetime] | None = None
        self.out_file: Path = Path("metrics.parquet")
        self.metric_settings = StreamflowMetricSettings()

    def ngen_cal_model_configure(self, config: ModelExec) -> None:
        plugin_settings = getattr(config, "plugin_settings", {}) or {}
        self.metric_settings = StreamflowMetricSettings.from_mapping(
            plugin_settings.get("compute_metrics")
        )

        validation_params = getattr(config, "val_params", None)
        if validation_params is not None:
            self.eval_range = validation_params.evaluation_interval()
            return

        evaluation_params = getattr(config, "eval_params", None)
        self.eval_range = (
            evaluation_params._eval_range
            if evaluation_params is not None
            else None
        )

    @hookimpl(wrapper=True)
    def ngen_cal_model_observations(
        self,
        nexus: Nexus,
        start_time: datetime,
        end_time: datetime,
        simulation_interval: pd.Timedelta,
    ) -> typing.Generator[None, pd.Series, pd.Series]:
        # In short, all registered `ngen_cal_model_observations` hooks run
        # before `yield` and the results are sent as the result to `yield`
        # NOTE: DO NOT MODIFY `obs`
        obs = yield
        if self.first_iteration and obs is None:
           self.first_iteration = False
           return None
        assert isinstance(obs, pd.Series), f"expected pd.Series, got {type(obs)!r}"
        self.obs = obs
        return obs

    @hookimpl(wrapper=True)
    def ngen_cal_model_output(
        self, nexus: Nexus
    ) -> typing.Generator[None, pd.Series, pd.Series]:
        # In short, all registered `ngen_cal_model_output` hooks run
        # before `yield` and the results are sent as the result to `yield`
        # NOTE: DO NOT MODIFY `sim`
        sim = yield
        if self.first_iteration and sim is None:
           self.first_iteration = False
           return None
        assert isinstance(sim, pd.Series), f"expected pd.Series, got {type(sim)!r}"
        self.sim = sim
        return sim

    @hookimpl
    def ngen_cal_model_iteration_finish(self, iteration: int, info: JobMeta) -> None:
        if self.sim is None:
            return None
        assert self.sim is not None, "make sure `ngen_cal_model_output` was called"
        assert (
            self.obs is not None
        ), "make sure `ngen_cal_model_observations` was called"

        #out_dir: Path = info.workdir/"model_outputs" - ajk 
        #out_dir.mkdir(exist_ok=True) - ajk

        # index: hourly datetime
        # columns: `obs_flow` and `sim_flow`; units m^3/s
        funcs = {
            "mean_absolute_error": mean_error,
            "mean_squared_error": mean_squared_error,
            "root_mean_squared_error": root_mean_squared_error,
            "volumetric_efficiency": volumetric_efficiency,
            "nash_sutcliffe_efficiency": nash_sutcliffe_efficiency,
            "coefficient_of_persistence": coefficient_of_persistence,
            "coefficient_of_extrapolation": _coefficient_of_extrapolation,
            "kling_gupta_efficiency": kling_gupta_efficiency,
        }
        metric_names = (*funcs.keys(), *DIAGNOSTIC_METRIC_NAMES)

        def failure_all_nan():
            return pd.Series(
                data=[np.nan for _ in metric_names],
                index=metric_names,
                dtype=float,
            )

        if self.sim.empty or self.obs.empty:
            print(
                f"{'SIM' if self.sim.empty else 'OBS'} DATAFRAME IS EMPTY. SETTING ALL METRICS TO NP.NAN"
            )
            metrics = failure_all_nan()
            self.update_metrics(info, metrics, iteration)
            return

        sim = self._select_streamflow(self.sim)
        obs = self._select_streamflow(self.obs)
        if sim is None or obs is None:
            metrics = failure_all_nan()
            self.update_metrics(info, metrics, iteration)
            return

        df = pd.concat(
            [sim.rename("sim_flow"), obs.rename("obs_flow")],
            axis=1,
            join="inner",
        ).sort_index()

        if df.empty:
            print("MERGED DATAFRAME IS EMPTY. SETTING ALL METRICS TO NP.NAN")
            metrics = failure_all_nan()
            self.update_metrics(info, metrics, iteration)
            return

        if self.eval_range:
            df = df.loc[self.eval_range[0]:self.eval_range[1]]
        df = df.dropna(subset=["obs_flow", "sim_flow"])
        df = df[
            np.isfinite(df["obs_flow"].to_numpy())
            & np.isfinite(df["sim_flow"].to_numpy())
        ]
        if df.empty:
            print(
                "NO VALID PAIRED VALUES IN EVALUATION RANGE. "
                "SETTING ALL METRICS TO NP.NAN"
            )
            metrics = failure_all_nan()
            self.update_metrics(info, metrics, iteration)
            return

        metrics = pd.Series(index=funcs.keys(), dtype=float)
        for f in funcs.keys():
            try:
                metrics[f] = funcs[f](df["obs_flow"], df["sim_flow"])
            except Exception as e:
                metrics[f] = np.nan
                print(
                    f"FAILED TO COMPUTE METRIC {f}. Setting metric value to np.nan for iteration {iteration}. Metric raised {e}"
                )

        diagnostics = compute_streamflow_diagnostics(
            df["obs_flow"],
            df["sim_flow"],
            self.metric_settings,
        )
        metrics = pd.concat([metrics, diagnostics])

        self.update_metrics(info, metrics, iteration)

        #model_file = f"sim_obs_{iteration}.parquet" - ajk
        #df.to_parquet(out_dir/model_file) - ajk

    @staticmethod
    def _select_streamflow(series: pd.Series) -> pd.Series | None:
        if not isinstance(series.index, pd.MultiIndex):
            return series
        if "variable" not in series.index.names:
            return None
        variables = series.index.get_level_values("variable")
        if "streamflow" not in variables:
            return None
        return series.xs("streamflow", level="variable")

    def update_metrics(self, info, metrics, iteration):
        #out_dir: Path = info.workdir/"model_outputs" - ajk
        out_dir: Path = info.workdir #/"metrics"
        out_dir.mkdir(exist_ok=True)
        metric_file: Path = out_dir / self.out_file

        if metric_file.exists():
            metric_df = pd.read_parquet(metric_file)
            metric_df = metric_df.reindex(
                metric_df.index.union(metrics.index, sort=False)
            )
        else:
            metric_df = pd.DataFrame(index=metrics.index)

        metric_df[iteration] = metrics

        metric_df.to_parquet(metric_file)


def _coefficient_of_extrapolation(observed, simulated) -> float:
    """Score against linear extrapolation from the two preceding observations."""
    obs = np.asarray(observed, dtype=float)
    sim = np.asarray(simulated, dtype=float)
    if len(obs) < 3 or len(obs) != len(sim):
        return np.nan

    baseline = obs[1:-1] + (obs[1:-1] - obs[:-2])
    denominator = float(np.sum((obs[2:] - baseline) ** 2))
    if denominator == 0:
        return np.nan
    error = float(np.sum((obs[2:] - sim[2:]) ** 2))
    return 1.0 - error / denominator
