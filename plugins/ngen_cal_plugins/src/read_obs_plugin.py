from __future__ import annotations

import typing
from pathlib import Path
import sqlite3

from ngen.cal import hookimpl
from hypy.nexus import Nexus
import pandas as pd

from src.python.observations import ObservationLoader
from ngen_cal_plugins.units import unit_conversion_factor

if typing.TYPE_CHECKING:
    from datetime import datetime
    from ngen.cal.model import ModelExec

class Proxy:
    def __init__(self, obj):
        self._proxy_obj = obj

    def set_proxy(self, obj):
        self._proxy_obj = obj

    def __getattribute__(self, name: str):
        if name not in ("_proxy_obj", "set_proxy"):
            return getattr(super().__getattribute__("_proxy_obj"), name)
        return super().__getattribute__(name)

    def __repr__(self):
        return repr(super().__getattribute__("_proxy_obj"))

    def __hash__(self):
        return hash(super().__getattribute__("_proxy_obj"))


class ReadObservedData:
    ACCEPTED_UNITS = {"m3/s", "m3/sec"}

    def __init__(self):
        self.proxy = Proxy(pd.Series())
        self.settings = {}
        self.hydrofabric = None
        self.obs_kwargs = None
        self.observations = {}

    @hookimpl
    def ngen_cal_model_configure(self, config: ModelExec) -> None:
        settings = config.plugin_settings.get("read_obs_data")
        if not isinstance(settings, dict):
            raise ValueError("Missing model.plugin_settings.read_obs_data")

        self.settings = {
            name: self._validate_settings(name, variable_settings)
            for name, variable_settings in settings.items()
        }

        self.hydrofabric = getattr(config, "hydrofabric", None)

        if self.obs_kwargs is None:
            return

        ds = self._load_observations(
            self.obs_kwargs["start_time"],
            self.obs_kwargs["end_time"],
        )

        self.proxy.set_proxy(ds)

    def _validate_settings(self, name, settings):
        if not isinstance(settings, dict):
            raise ValueError(f"read_obs_data.{name} must be a mapping")

        path = Path(settings.get("path", "")).expanduser()
        if not path.is_absolute():
            raise ValueError(f"read_obs_data.{name}.path must be absolute: {path}")

        validated = {
            "layout": settings.get("layout", "point"),
            "path": str(path),
            "time_column": settings.get("time_column", "value_time"),
            "value_column": settings.get("value_column"),
            "id_column": settings.get("id_column"),
            "units": settings.get("units"),
            "simulated": settings.get("simulated"),
            "simulated_units": settings.get("simulated_units"),
        }
        if (
            not isinstance(validated["units"], str)
            or not validated["units"].strip()
        ):
            raise ValueError(
                f"read_obs_data.{name}.units must be a non-empty string"
            )
        if validated["simulated"] is not None and (
            not isinstance(validated["simulated"], str)
            or not validated["simulated"].strip()
        ):
            raise ValueError(
                f"read_obs_data.{name}.simulated must name a simulation "
                "output variable"
            )
        if validated["simulated"] is not None and (
            not isinstance(validated["simulated_units"], str)
            or not validated["simulated_units"].strip()
        ):
            raise ValueError(
                f"read_obs_data.{name}.simulated_units must be provided "
                "when simulated is configured"
            )
        if (
            name.lower() == "streamflow"
            and validated["units"] not in self.ACCEPTED_UNITS
        ):
            raise ValueError(
                "Streamflow observation units must be 'm3/s' or 'm3/sec'"
            )
        return validated

    def _load_observations(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> pd.Series:
        if not self.settings:
            raise RuntimeError("ReadObservedData has not been configured")

        loader = ObservationLoader(observations={}, config_dir=Path.cwd())
        observations = {}
        for name, settings in self.settings.items():
            data = loader.load_path(name, settings, settings["path"])
            if isinstance(data, pd.DataFrame):
                data = self._area_weighted_mean(name, data)
            observations[name] = data
        self.observations = observations

        empty = [name for name, data in observations.items() if data.empty]
        if empty:
            raise ValueError(
                "Observation datasets contain no values: "
                f"{', '.join(empty)}"
            )

        common_start = max(
            start_time,
            *(data.index.min() for data in observations.values()),
        )
        common_end = min(
            end_time,
            *(data.index.max() for data in observations.values()),
        )
        if common_start > common_end:
            raise ValueError(
                "Configured observation datasets do not share a common "
                "time range"
            )

        observations = {
            name: data.loc[common_start:common_end].copy()
            for name, data in observations.items()
        }
        empty = [name for name, data in observations.items() if data.empty]
        if empty:
            raise ValueError(
                "Observation datasets have no values in their common time "
                f"range: {', '.join(empty)}"
            )

        if len(observations) == 1:
            combined = next(iter(observations.values()))
        else:
            combined = pd.concat(observations, axis=1)
            combined.columns.name = "variable"
            combined = combined.stack().sort_index()
            combined.index.names = ["value_time", "variable"]

        combined.rename("obs_flow", inplace=True)

        return combined

    def _area_weighted_mean(self, name, dataframe):
        if self.hydrofabric is None:
            raise ValueError(
                f"A hydrofabric is required to area-weight distributed "
                f"{name} observations"
            )

        with sqlite3.connect(self.hydrofabric) as connection:
            rows = connection.execute(
                "SELECT divide_id, areasqkm FROM divides"
            ).fetchall()
        areas = pd.Series(
            {str(divide_id): area for divide_id, area in rows},
            dtype=float,
        )
        columns = dataframe.columns.intersection(areas.index)
        if columns.empty:
            raise ValueError(
                f"Distributed {name} observations do not match hydrofabric "
                "divide IDs"
            )

        values = dataframe[columns]
        weights = areas.loc[columns]
        available_weights = values.notna().mul(weights, axis=1).sum(axis=1)
        weighted_sum = values.mul(weights, axis=1).sum(axis=1, min_count=1)
        return weighted_sum.div(available_weights).rename(name)

    def _load_simulated_variable(self, name, settings):
        output_variable = settings.get("simulated")
        if not isinstance(output_variable, str):
            raise ValueError(
                f"read_obs_data.{name}.simulated must name a simulation "
                "output variable"
            )

        file_pattern = "cat-*.csv"
        files = sorted(Path.cwd().glob(file_pattern))
        if not files:
            raise FileNotFoundError(
                f"No simulated {name} files match "
                f"'{file_pattern}' in {Path.cwd()}"
            )

        time_column = "Time"
        value_column = output_variable
        values = {}
        for path in files:
            divide_id = path.stem
            dataframe = pd.read_csv(path)
            missing = [
                column
                for column in (
                    time_column,
                    value_column,
                )
                if column not in dataframe.columns
            ]
            if missing:
                raise ValueError(
                    f"Simulated {name} file {path} is missing columns: "
                    f"{', '.join(missing)}"
                )

            series = dataframe.set_index(time_column)[value_column]
            series.index = pd.to_datetime(series.index)
            values[divide_id] = series

        distributed = pd.DataFrame(values).sort_index()
        simulated = self._area_weighted_mean(name, distributed)

        observed = self.observations.get(name)
        frequency = None
        if observed is not None and len(observed.index) > 1:
            differences = observed.index.to_series().diff().dropna()
            if not differences.empty:
                frequency = differences.mode().iloc[0]
        temporal_aggregation = None
        if frequency and frequency > pd.Timedelta(hours=1):
            resampler = simulated.resample(frequency)
            # ET is an amount accumulated during each timestep, so sum it
            # across the observed interval. State variables such as SWE are
            # averaged when converting to a lower temporal resolution.
            if name.lower() == "et":
                simulated = resampler.sum()
                temporal_aggregation = "sum"
            elif name.lower() == "swe":
                simulated = resampler.mean()
                temporal_aggregation = "mean"
            else:
                raise ValueError(
                    f"Temporal aggregation is not configured for simulated "
                    f"{name} observations"
                )

        simulated *= unit_conversion_factor(
            settings["simulated_units"],
            settings["units"],
            temporal_aggregation,
        )
        return simulated.rename(name)

    @hookimpl(wrapper=True)
    def ngen_cal_model_output(self, nexus: Nexus):
        simulated_streamflow = yield
        if not isinstance(simulated_streamflow, pd.Series):
            return simulated_streamflow

        simulations = {}
        if "streamflow" in self.settings:
            simulations["streamflow"] = simulated_streamflow.rename(
                "streamflow"
            )

        for name, settings in self.settings.items():
            if name == "streamflow":
                continue
            simulations[name] = self._load_simulated_variable(name, settings)

        if len(simulations) == 1:
            return next(iter(simulations.values())).rename("sim_flow")

        combined = pd.concat(simulations, axis=1)
        combined.columns.name = "variable"
        combined = combined.stack().sort_index()
        combined.index.names = ["value_time", "variable"]
        return combined.rename("sim_flow")

    @hookimpl(tryfirst=True)
    def ngen_cal_model_observations(
        self,
        nexus: Nexus,
        start_time: datetime,
        end_time: datetime,
        simulation_interval: pd.Timedelta,
    ) -> pd.Series:
        self.obs_kwargs = {
            "nexus": nexus,
            "start_time": start_time,
            "end_time": end_time,
            "simulation_interval": simulation_interval,
        }

        # ngen-cal requests observations before it calls the model configure
        # hook. Return a proxy now; configure replaces its underlying Series.
        if self.settings:
            self.proxy.set_proxy(self._load_observations(start_time, end_time))

        return self.proxy
