from __future__ import annotations

import itertools

from ngen.cal import hookimpl
from ngen.cal.meta import JobMeta
from ngen.cal.model import ModelExec
from pathlib import Path

# NOTE: global variable that is set in `NgenSaveOutput.ngen_cal_model_iteration_finish`
_workdir: Path | None = None


def save_output(sim_dir: Path, output_suffix: str):
    runoff_pattern = "cat-*.csv"
    lateral_pattern = "nex-*.csv"
    terminal_pattern = "tnx-*.csv"
    coastal_pattern = "cnx-*.csv"
    routing_output_stream = "troute_output_*"
    routing_csv_output = "flowveldepth_*.csv"
    ngen_json = "realization*.json"

    out_dir = sim_dir / f"output_{output_suffix}"
    Path.mkdir(out_dir, exist_ok=True)

    globs = [
        sim_dir.glob(runoff_pattern),
        sim_dir.glob(lateral_pattern),
        sim_dir.glob(terminal_pattern),
        sim_dir.glob(coastal_pattern),
        sim_dir.glob(routing_output_stream),
        sim_dir.glob(routing_csv_output),
        sim_dir.glob(ngen_json),
    ]
    for f in itertools.chain(*globs):
        f.rename(out_dir / f.name)

def clean_output(sim_dir: Path):
    runoff_pattern = "cat-*.csv"
    lateral_pattern = "nex-*.csv"
    terminal_pattern = "tnx-*.csv"
    coastal_pattern = "cnx-*.csv"
    routing_output_stream = "troute_output_*"
    routing_csv_output = "flowveldepth_*.csv"
    ngen_json = "realization*.json"

    globs = [
        sim_dir.glob(runoff_pattern),
        sim_dir.glob(lateral_pattern),
        sim_dir.glob(terminal_pattern),
        sim_dir.glob(coastal_pattern),
        sim_dir.glob(routing_output_stream),
        sim_dir.glob(routing_csv_output),
        sim_dir.glob(ngen_json),
    ]

    for f in itertools.chain(*globs):
        f.unlink()



class SaveData:
    def __init__(self):
        self.output_retention = "best"

    @hookimpl
    def ngen_cal_model_configure(self, config: ModelExec) -> None:
        settings = config.plugin_settings.get("output_retention", {})
        self.output_retention = settings.get("mode", "best")
        if self.output_retention not in {"best", "all"}:
            raise ValueError("output_retention.mode must be one of: best, all")
        path = config.workdir
        global _workdir
        # HACK: fix this in future
        _workdir = path

    @hookimpl
    def ngen_cal_model_iteration_finish(self, iteration: int, info: JobMeta) -> None:
        """
        After each iteration, copy the old outputs for possible future
        evaluation and inspection.
        """
        path = info.workdir
        if self.output_retention == "all":
            save_output(path, str(iteration))
            return

        if not (path / "best_params.txt").exists():
            save_output(path, str(iteration))
            return

        if self._is_best_iteration(path, iteration):
            save_output(path, "best")
        else:
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
