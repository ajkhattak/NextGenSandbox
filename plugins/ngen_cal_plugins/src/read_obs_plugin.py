from __future__ import annotations

import typing
from pathlib import Path

from ngen.cal import hookimpl
from hypy.nexus import Nexus
import pandas as pd

from src.python.observations import ObservationLoader

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
        self.settings = None
        self.obs_kwargs = None

    @hookimpl
    def ngen_cal_model_configure(self, config: ModelExec) -> None:
        settings = config.plugin_settings.get("read_obs_data")
        if not isinstance(settings, dict):
            raise ValueError("Missing model.plugin_settings.read_obs_data")

        path = Path(settings.get("path", "")).expanduser()
        if not path.is_absolute():
            raise ValueError(f"read_obs_data.path must be absolute: {path}")

        self.settings = {
            "name": settings.get("name", "streamflow"),
            "layout": settings.get("layout", "point"),
            "path": str(path),
            "time_column": settings.get("time_column", "value_time"),
            "value_column": settings.get("value_column", "value"),
            "units": settings.get("units"),
        }

        if self.settings["layout"] != "point":
            raise ValueError(
                "ReadObservedData currently supports only layout: point"
            )
        if self.settings["units"] not in self.ACCEPTED_UNITS:
            raise ValueError(
                "Streamflow observation units must be 'm3/s' or 'm3/sec'"
            )

        if self.obs_kwargs is None:
            return

        ds = self._load_observations(
            self.obs_kwargs["start_time"],
            self.obs_kwargs["end_time"],
        )
        self.proxy.set_proxy(ds)

    def _load_observations(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> pd.Series:
        if self.settings is None:
            raise RuntimeError("ReadObservedData has not been configured")

        loader = ObservationLoader(observations={}, config_dir=Path.cwd())
        ds = loader.load_path(
            self.settings["name"],
            self.settings,
            self.settings["path"],
        )
        ds = ds.loc[start_time:end_time].copy()
        ds.rename("obs_flow", inplace=True)
        return ds

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
        if self.settings is not None:
            self.proxy.set_proxy(self._load_observations(start_time, end_time))

        return self.proxy
