# NextGenSandbox

NextGenSandbox is a workflow tool for setting up, running, calibrating, and evaluating [NextGen/ngen](https://github.com/NOAA-OWP/ngen) hydrologic modeling experiments. It brings together common setup steps such as hydrofabric subsetting, forcing preparation, model configuration, calibration, validation, and large-scale job launching so users can move from basin resources to repeatable simulations with less manual wiring.

## Start Here

For a new machine or first-time setup, follow the [install guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/install.md). The guide includes a Quick Path, detailed installation steps, and a smoke test to verify the core workflow. For common setup issues, see the [diagnostics guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/diagnostics.md).

## Configuration

NextGenSandbox configuration defines the resources, models, and run behavior
for a project. This includes project directory layout, hydrofabric subsetting,
forcing preparation, local observations, model formulations and variants,
simulation or calibration task types, output retention, and calibration search
settings.

Start with the [configuration guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/configuration.md) for the main field reference. The [directory layout guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/directory_layout.md) explains how reusable resources and generated outputs are organized.

Detailed guides are also available for [model configuration](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/model_configuration.md), [calibration settings](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/calibration.md), and [observations/objectives](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/observations.md).

## Project Workflows

After installation, use the [project workflow guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/workflow.md) to set up a custom single-basin project, run `sandbox --subset`, `sandbox --forc`, `sandbox --conf`, and `sandbox --run`, and then scale larger experiments with the [Sandbox Launcher](https://github.com/ajkhattak/NextGenSandbox/tree/main/tools/launcher).

## Models And Formulations

To see the current model formulations supported by NextGenSandbox, run:

```bash
sandbox --formulations
```

See the [formulations guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/formulations.md) for model combinations, variants, and setup notes.
