from __future__ import annotations

import typing
import itertools

from ngen.cal import hookimpl
from hypy.nexus import Nexus
import pandas as pd
import numpy as np
from pathlib import Path
import glob
from hydrotools.metrics.metrics import kling_gupta_efficiency

if typing.TYPE_CHECKING:
    from datetime import datetime
    from ngen.cal.model import ModelExec

ds_sim_test = pd.Series
ds_obs_test = pd.Series
_workdir: Path | None = None

class Proxy:
    def __init__(self, obj):
        self._proxy_obj = obj
        self._proxy_obj_sim = obj

    def set_proxy(self, obj):
        self._proxy_obj = obj

    def set_proxy_sim(self, obj):
        self._proxy_obj_sim = obj

    def __getattribute__(self, name: str):
        if name not in ("_proxy_obj", "set_proxy", "_proxy_obj_sim", "set_proxy_sim"):
            return getattr(super().__getattribute__("_proxy_obj"), name)
        return super().__getattribute__(name)

    def __repr__(self):
        return repr(super().__getattribute__("_proxy_obj"))

    def __hash__(self):
        return hash(super().__getattribute__("_proxy_obj"))


class WellPlugin:
    def __init__(self):
        self.proxy = Proxy(pd.Series())
        self.ft3_to_m3 = 0.0283168
        self.obs_data_path = None
        self.cat_names     = None
        #self.col_names     = None
        self.units = None
        self.window = 1
        self.save_obs_nwm = True

    @hookimpl
    def ngen_cal_model_configure(self, config: ModelExec) -> None:
        path = config.workdir
        global _workdir
        # HACK: fix this in future
        _workdir = path

        self.obs_data_path = config.plugin_settings["ngen_cal_read_obs_data"]["obs_data_path"]
        self.units = config.plugin_settings["ngen_cal_read_obs_data"]["units"]
        self.window = int(config.plugin_settings["ngen_cal_read_obs_data"]["window"])

        start = self.obs_kwargs["start_time"]
        end = self.obs_kwargs["end_time"]


        ds = self._read_observations(self, self.obs_data_path, start, end, self.window)

        self.proxy.set_proxy(ds)


    @staticmethod
    def _read_observations(self,
        filename: str, start_time: datetime, end_time: datetime, window: int
    ) -> pd.Series:
        # read file

        try:
            df = pd.read_csv(filename)
        except:
            df = pd.read_parquet(filename)

        tname = 'value_date'
        names = [name for name in df.columns if 'cat-' in name or tname in name]

        names = [name for name in names if 'cat-30' not in name and 'cat-73'  not in name]
        #names = [name for name in names if 'cat-30' not in name]

        df = df[names]

        self.cat_names = [n.split('_')[-1] for n in names if 'cat' in n]

        if (df.index.name == tname):
            df.columns = self.cat_names
            df[tname] = pd.to_datetime(df.index.tz_localize(None))
            df.set_index(tname, inplace=True)
            df.update(df.cumsum())
        else:
            df.columns = [df.columns[0]] + self.cat_names
            df[tname] = pd.to_datetime(df[tname])
            df.set_index(tname, inplace=True)

        #if self.units == "m/hr":
        #    df["value"] =  df["value"]

        df = df.loc[start_time:end_time]

        # get total hours to ensure the length of observed data is consistent with the leght of simulated data
        total_hours = (end_time - start_time).total_seconds() / 3600.0 

        length = int(total_hours / window) + 1 # +1 includes the first hour

        assert length > 0
        df = df.head(length)
        ds = df.stack()
        ds.rename("obs_flow", inplace=True)

        #global ds_obs_test
        #ds_obs_test = ds
        #self.col_names = names
        #self.cat_names = [name.split('_')[-1] for name in names if 'cat' in name]

        return ds

    @hookimpl
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

        # `ngen_cal_model_observations` must have already called, so call again and set proxy
        if not self.proxy.empty:
            assert self.obs_data_path is not None, "invariant"

            ds = self._read_observations(self,
                                         self.obs_data_path,
                                         start_time,
                                         end_time,
                                         self.window
                                         )

            self.proxy.set_proxy(ds)

        return self.proxy

    @hookimpl(wrapper=True)
    def ngen_cal_model_output(
        self, id: str | None
    ) -> typing.Generator[None, pd.Series, pd.Series]:
        sim = yield

        if sim is None:
            return None
        global _workdir

        cat_pattern = "cat-*.csv"
        cat_files = _workdir.glob(cat_pattern)

        cat_files  = [file.as_posix() for file in cat_files]
        calib_cats = [file for file in cat_files if Path(file).stem in self.cat_names]

        df_sim = []
        tname = 'value_date'

        for file in calib_cats:
            df = pd.read_csv(file, usecols=['Time','SOIL_TO_GW_FLUX', 'DEEP_GW_TO_CHANNEL_FLUX'], index_col=False)
            df['SOIL_TO_GW_FLUX'] = df['SOIL_TO_GW_FLUX'] - df['DEEP_GW_TO_CHANNEL_FLUX']
            df.drop(columns=['DEEP_GW_TO_CHANNEL_FLUX'], inplace=True)
            df.rename(columns={'Time' : tname, 'SOIL_TO_GW_FLUX': Path(file).stem}, inplace=True)
            df[tname] = pd.to_datetime(df[tname])
            df.set_index(tname, inplace=True)
            df.update(df.cumsum())
            df_sim.append(df)

        df_sim = pd.concat(df_sim, axis=1)
        ds = df_sim.stack()
        ds.rename("sim_flow", inplace=True)
        #pd.set_option('display.float_format', '{:.10f}'.format)

        self.proxy.set_proxy_sim(ds)

        return ds

    @hookimpl
    def ngen_cal_model_iteration_finish(self, iteration: int, info: JobMeta) -> None:

        sim = self.proxy._proxy_obj_sim
        obs = self.proxy._proxy_obj
        if sim is None:
            return None
        assert (
            sim is not None
        ), "make sure `ngen_cal_model_output` was called"
        assert obs is not None, "make sure `ngen_cal_model_observations` was called"

        # index: hourly datetime
        # columns: `obs_flow` and `sim_flow`; units m^3/s
        #df = pd.merge(self.sim, self.obs, left_index=True, right_index=True)

        if self.save_obs_nwm:
            #self.save_obs_nwm = False  # will revisit this later
            df = pd.merge(sim, obs, left_index=True, right_index=True)
        else:
            df = pd.DataFrame(sim)

        df = df.unstack()

        df.reset_index(names="time", inplace=True)
        #df.to_parquet(f"sim_obs_{iteration}.parquet")

        path = info.workdir

        out_dir = path / f"output_sim_obs"
        if (not out_dir.is_dir()):
            Path.mkdir(out_dir)
        df.to_csv(f"{out_dir}/sim_obs_{iteration}.csv")

    @hookimpl
    def ngen_cal_finish(exception: Exception | None) -> None:

        if exception is None:
            print("validation: not saving obs/sim output")
            return
        global _workdir

        assert _workdir is not None, "invariant"

        if (len(ds_sim_test.index) == len(ds_obs_test.index)):
            df = pd.merge(ds_sim_test, ds_obs_test, left_index=True, right_index=True)
        else:
            df = pd.DataFrame(ds_sim_test)

        df = df.unstack()

        df.rename(columns = {"value_time" : "time"}, inplace=True)

        df.reset_index(names="time", inplace=True)

        path = _workdir
        out_dir = path / f"output_sim_obs"
        if (not out_dir.is_dir()):
            Path.mkdir(out_dir)
        df.to_csv(f"{out_dir}/sim_obs_validation.csv")


def kling_gupta_well(df_observed, df_simulated):

    cats = df_observed.index.levels[1] # get all cat-ids

    kge = 0.0

    count = 0
    for cat in cats:

        if ( not (df_observed[:,cat] == 0.0).all() and not (df_simulated[:,cat] == 0.0).all()):
            kge = kge + kling_gupta_efficiency(df_observed[:,cat], df_simulated[:,cat])
            count = count + 1

    if (count == 0):
        kge = 1000.0
    else:
        kge = 1 - kge/count

    return kge
