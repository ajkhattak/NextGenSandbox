from __future__ import annotations

import itertools
import os
import shutil
import tempfile

import yaml

from ngen.cal import hookimpl
from ngen.cal.meta import JobMeta
from ngen.cal.model import ModelExec
from pathlib import Path

# NOTE: global variable that is set in `NgenSaveOutput.ngen_cal_model_iteration_finish`
_workdir: Path | None = None


def save_output(sim_dir: Path, output_suffix: str, local_output: Path | None = None):
    runoff_pattern = "cat-*.csv"
    lateral_pattern = "nex-*.csv"
    terminal_pattern = "tnx-*.csv"
    coastal_pattern = "cnx-*.csv"
    nexus_netcdf_pattern = "formulation_*_nexuses.nc"
    routing_output_stream = "troute_output_*"
    routing_csv_output = "flowveldepth_*.csv"
    ngen_json = "realization*.json"

    out_dir = sim_dir / f"output_{output_suffix}"
    Path.mkdir(out_dir, exist_ok=True)

    if local_output is not None:
        # Publish a complete file on shared storage before removing the local source.
        with tempfile.NamedTemporaryFile(dir=out_dir, prefix=".routing-", delete=False) as f:
            staged = Path(f.name)
        try:
            shutil.copy2(local_output, staged)
            staged.replace(out_dir / local_output.name)
        finally:
            staged.unlink(missing_ok=True)
        local_output.unlink()

    globs = [
        sim_dir.glob(runoff_pattern),
        sim_dir.glob(lateral_pattern),
        sim_dir.glob(terminal_pattern),
        sim_dir.glob(coastal_pattern),
        sim_dir.glob(nexus_netcdf_pattern),
        sim_dir.glob(routing_output_stream),
        sim_dir.glob(routing_csv_output),
        sim_dir.glob(ngen_json),
    ]
    for f in itertools.chain(*globs):
        if local_output is not None and f.name == local_output.name:
            continue
        f.rename(out_dir / f.name)

def clean_output(sim_dir: Path):
    runoff_pattern = "cat-*.csv"
    lateral_pattern = "nex-*.csv"
    terminal_pattern = "tnx-*.csv"
    coastal_pattern = "cnx-*.csv"
    nexus_netcdf_pattern = "formulation_*_nexuses.nc"
    routing_output_stream = "troute_output_*"
    routing_csv_output = "flowveldepth_*.csv"
    ngen_json = "realization*.json"

    globs = [
        sim_dir.glob(runoff_pattern),
        sim_dir.glob(lateral_pattern),
        sim_dir.glob(terminal_pattern),
        sim_dir.glob(coastal_pattern),
        sim_dir.glob(nexus_netcdf_pattern),
        sim_dir.glob(routing_output_stream),
        sim_dir.glob(routing_csv_output),
        sim_dir.glob(ngen_json),
    ]

    for f in itertools.chain(*globs):
        f.unlink()



class SaveData:
    def __init__(self):
        self.output_retention = "best"
        self.local_output: Path | None = None

    @hookimpl(tryfirst=True, optionalhook=True)
    def ngen_cal_model_prepare(self, config: ModelExec) -> None:
        self.local_output = None
        if not config.plugin_settings.get("local_routing_output", {}).get("enabled", False):
            return
        for key in ("SLURM_JOB_NUM_NODES", "SLURM_NNODES"):
            if int(os.environ.get(key, "1")) != 1:
                raise ValueError("Local routing output requires a single-node job")
        tmpdir = os.environ.get("TMPDIR")
        if not tmpdir or not Path(tmpdir).is_dir() or not os.access(tmpdir, os.W_OK):
            raise ValueError("Local routing output requires a writable TMPDIR")

        routing = config.ngen_realization.routing
        if routing is None:
            raise ValueError("Local routing output requires t-route")
        with Path(routing.config).open() as f:
            troute = yaml.safe_load(f)
        output = troute.get("output_parameters", {}).get("netcdf_output")
        if not isinstance(output, dict) or not output.get("output_path"):
            raise ValueError("Local routing output requires netcdf_output.output_path")

        local_dir = Path(tempfile.mkdtemp(prefix="troute_", dir=tmpdir)).resolve()
        self.local_output = local_dir / Path(output["output_path"]).name
        output["output_path"] = str(self.local_output)
        worker_config = Path(config.workdir) / "troute_local_config.yaml"
        with worker_config.open("w") as f:
            yaml.safe_dump(troute, f, sort_keys=False)
        routing.config = worker_config
        config.routing_output = self.local_output
        validation = config.plugin_settings.get("ngen_cal_troute_output")
        if validation is not None:
            validation["validation_routing_output"] = str(self.local_output)

    @hookimpl
    def ngen_cal_model_configure(self, config: ModelExec) -> None:
        if config.plugin_settings.get("local_routing_output", {}).get("enabled", False) and self.local_output is None:
            raise RuntimeError("Local routing output requires ngen-cal worker preparation support; rebuild ngen-cal")
        settings = config.plugin_settings.get("output_retention", {})
        self.output_retention = settings.get("mode", "best")
        if self.output_retention not in {"best", "all"}:
            raise ValueError("output_retention.mode must be one of: best, all")
        path = config.workdir
        global _workdir
        # HACK: fix this in future
        _workdir = path
        for nexus_output in path.glob("formulation_*_nexuses.nc"):
            nexus_output.unlink()

    @hookimpl
    def ngen_cal_model_iteration_finish(self, iteration: int, info: JobMeta) -> None:
        """
        After each iteration, copy the old outputs for possible future
        evaluation and inspection.
        """
        path = info.workdir
        if self.output_retention == "all" or iteration == "validation":
            save_output(path, str(iteration), self.local_output)
            return

        if not (path / "best_params.txt").exists():
            save_output(path, str(iteration), self.local_output)
            return

        if self._is_best_iteration(path, iteration):
            save_output(path, "best", self.local_output)
        else:
            if self.local_output is not None:
                self.local_output.unlink(missing_ok=True)
            clean_output(path)

    @staticmethod
    def _is_best_iteration(workdir: Path, iteration: int) -> bool:
        best_params = workdir / "best_params.txt"
        with best_params.open() as file:
            lines = file.readlines()

        if len(lines) < 2:
            raise ValueError(
                f"Invalid best parameters file; expected at least two lines: "
                f"{best_params}"
            )

        best_iteration = lines[1].strip()
        return best_iteration == str(iteration)
