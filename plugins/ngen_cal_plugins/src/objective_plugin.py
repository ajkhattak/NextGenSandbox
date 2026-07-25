from __future__ import annotations

from ngen.cal import hookimpl

from ngen_cal_plugins.objectives import configure_composite_objective


class ConfigureObjective:
    """Configure the weighted objective before ngen-cal starts evaluating it."""

    @hookimpl
    def ngen_cal_model_configure(self, config) -> None:
        settings = config.plugin_settings.get("composite_objective")
        if settings is None:
            return
        if not isinstance(settings, dict):
            raise TypeError(
                "model.plugin_settings.composite_objective must be a mapping"
            )
        metrics = settings.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            raise ValueError(
                "model.plugin_settings.composite_objective.metrics must be "
                "a non-empty mapping"
            )
        configure_composite_objective(metrics)
