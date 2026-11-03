import copy
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from ngen.cal._hookspec import ModelHooks
from ngen.cal._plugin_system import setup_scoped_plugin_manager
from ngen.cal.agent import Agent
from ngen.cal.ngen_hooks.ngen_output import TrouteOutput
from ngen_cal_plugins.save_divide_output_plugin import SaveData, save_output


class ModelStub(SimpleNamespace):
    def unwrap(self):
        return self

    def resolve_paths(self, path):
        pass


class ConfigStub(SimpleNamespace):
    def copy(self, deep=False):
        return copy.deepcopy(self)


@pytest.fixture
def model(tmp_path, monkeypatch):
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setenv("TMPDIR", str(local))
    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "1")
    monkeypatch.delenv("SLURM_NNODES", raising=False)
    routing = tmp_path / "troute.yaml"
    routing.write_text(yaml.safe_dump({
        "output_parameters": {"netcdf_output": {
            "output_path": "troute_output_test.nc", "output_interval": 3600,
        }},
        "compute_parameters": {"forcing_parameters": {
            "max_loop_size": 43200,
            "qlat_input_folder": "./",
            "qlat_input_file": "formulation_default_nexuses.nc",
        }},
    }))
    manager = setup_scoped_plugin_manager(ModelHooks, [SaveData])
    manager.register(TrouteOutput(Path("troute_output_test.nc")))
    return ConfigStub(model=ModelStub(
        type="ngen", workdir=tmp_path,
        ngen_realization=SimpleNamespace(routing=SimpleNamespace(config=routing)),
        routing_output=Path("troute_output_test.nc"),
        plugin_settings={
            "local_routing_output": {"enabled": True},
            "ngen_cal_troute_output": {"validation_routing_output": "old.nc"},
        },
        _plugin_manager=manager,
    ))


def retention(agent):
    return next(p for p in agent.model._plugin_manager.get_plugins() if isinstance(p, SaveData))


def reader(agent):
    return next(p for p in agent.model._plugin_manager.get_plugins() if isinstance(p, TrouteOutput))


def test_workers_and_restart_get_fresh_local_paths(model, tmp_path, monkeypatch):
    original_config = model.model.ngen_realization.routing.config
    original_text = original_config.read_text()
    first = Agent(model, tmp_path)
    second = first.duplicate()
    for agent in (first, second):
        output = agent.model.routing_output
        assert output.parent.parent == Path(os.environ["TMPDIR"])
        assert reader(agent)._output_file == output
        assert reader(agent)._settings.validation_routing_output == output
        assert retention(agent).local_output == output
        cfg_path = agent.model.ngen_realization.routing.config
        assert cfg_path.parent == agent.job.workdir
        cfg = yaml.safe_load(cfg_path.read_text())
        assert cfg["output_parameters"]["netcdf_output"]["output_path"] == str(output)
        assert cfg["output_parameters"]["netcdf_output"]["output_interval"] == 3600
        assert cfg["compute_parameters"]["forcing_parameters"]["max_loop_size"] == 43200
        assert cfg["compute_parameters"]["forcing_parameters"]["qlat_input_folder"] == "./"
        assert cfg["compute_parameters"]["forcing_parameters"]["qlat_input_file"] == "formulation_default_nexuses.nc"
    assert first.model.routing_output != second.model.routing_output
    assert original_config.read_text() == original_text

    new_local = tmp_path / "new-job-local"
    new_local.mkdir()
    monkeypatch.setenv("TMPDIR", str(new_local))
    old_output = first.model.routing_output
    first.model._plugin_manager.hook.ngen_cal_model_prepare(config=first.model)
    assert first.model.routing_output != old_output
    assert first.model.routing_output.parent.parent == new_local
    assert reader(first)._output_file == first.model.routing_output


def test_restart_agent_reuses_shared_worker_but_gets_new_local_path(model, tmp_path, monkeypatch):
    first = Agent(model, tmp_path)
    old_worker = first.job.workdir
    old_output = first.model.routing_output
    new_local = tmp_path / "restart-local"
    new_local.mkdir()
    monkeypatch.setenv("TMPDIR", str(new_local))

    restarted = Agent(first._model.copy(deep=True), tmp_path, restart=True)

    assert restarted.job.workdir == old_worker
    assert restarted.model.routing_output != old_output
    assert restarted.model.routing_output.parent.parent == new_local
    assert reader(restarted)._output_file == restarted.model.routing_output


@pytest.mark.parametrize("mode,iteration,best,suffix", [
    ("best", 2, 2, "best"), ("all", 2, 0, "2"),
    ("best", "validation", 0, "validation"),
])
def test_retention_copies_real_file(model, tmp_path, mode, iteration, best, suffix):
    agent = Agent(model, tmp_path)
    plugin = retention(agent)
    plugin.output_retention = mode
    (agent.job.workdir / "best_params.txt").write_text(f"2\n{best}\n0.5\n")
    plugin.local_output.write_bytes(b"routing result")
    plugin.ngen_cal_model_iteration_finish(iteration, agent.job)
    saved = agent.job.workdir / f"output_{suffix}" / plugin.local_output.name
    assert saved.read_bytes() == b"routing result"
    assert not saved.is_symlink()
    assert not plugin.local_output.exists()
    plugin.local_output.parent.rmdir()
    assert saved.read_bytes() == b"routing result"


def test_nonbest_output_is_discarded(model, tmp_path):
    agent = Agent(model, tmp_path)
    plugin = retention(agent)
    (agent.job.workdir / "best_params.txt").write_text("2\n0\n0.5\n")
    plugin.local_output.write_bytes(b"not best")
    plugin.ngen_cal_model_iteration_finish(2, agent.job)
    assert not plugin.local_output.exists()
    assert not (agent.job.workdir / "output_best").exists()


def test_failed_copy_preserves_source_and_previous_best(model, tmp_path):
    agent = Agent(model, tmp_path)
    source = retention(agent).local_output
    source.write_bytes(b"new")
    saved = agent.job.workdir / "output_best" / source.name
    saved.parent.mkdir()
    saved.write_bytes(b"old")
    with patch("ngen_cal_plugins.save_divide_output_plugin.shutil.copy2", side_effect=OSError("full")):
        with pytest.raises(OSError, match="full"):
            save_output(agent.job.workdir, "best", source)
    assert source.read_bytes() == b"new"
    assert saved.read_bytes() == b"old"
    assert not list(saved.parent.glob(".routing-*"))


def test_disabled_does_not_require_tmpdir(model, tmp_path, monkeypatch):
    model.model.plugin_settings.pop("local_routing_output")
    monkeypatch.delenv("TMPDIR")
    source_config = model.model.ngen_realization.routing.config
    agent = Agent(model, tmp_path)
    assert retention(agent).local_output is None
    assert agent.model.ngen_realization.routing.config == source_config
    assert agent.model.routing_output == Path("troute_output_test.nc")


def test_missing_tmpdir_fails(model, tmp_path, monkeypatch):
    monkeypatch.delenv("TMPDIR")
    with pytest.raises(ValueError, match="writable TMPDIR"):
        Agent(model, tmp_path)


def test_multinode_fails(model, tmp_path, monkeypatch):
    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "2")
    with pytest.raises(ValueError, match="single-node"):
        Agent(model, tmp_path)
