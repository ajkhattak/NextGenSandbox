# NextGenSandbox

NextGenSandbox is a workflow tool for setting up, running, calibrating, and evaluating [NextGen/ngen](https://github.com/NOAA-OWP/ngen) hydrologic modeling experiments. It brings together common setup steps such as hydrofabric subsetting, forcing preparation, model configuration, calibration, validation, and large-scale job launching so users can move from basin resources to repeatable simulations with less manual wiring.

## Start Here

For a new machine or first-time setup, follow the [install guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/install.md). The guide includes a Quick Path, detailed installation steps, and a smoke test to verify the core workflow.

## Configuration

Guidance for setting up `sandbox_config.yaml`, `calib_config.yaml`, formulations, model instances, and task types is available in the [configuration guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/configuration.md).

The default basin-first directory structure, including how `input_dir` and `output_dir` are used, is described in the [directory layout guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/directory_layout.md).

For ML-based formulations, the configuration guide also documents how to stage trained LSTM and dHBV data under `$SANDBOX_DATA_DIR` and configure the model basefiles.

## Project Workflows

After installation, use the [project workflow guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/workflow.md) to set up a custom single-basin project, run `sandbox --subset`, `sandbox --forc`, `sandbox --conf`, and `sandbox --run`, and then scale larger experiments with the [Sandbox Launcher](https://github.com/ajkhattak/NextGenSandbox/tree/main/tools/launcher).

## Supported Formulations

For the most up-to-date list of supported formulations, run:

```bash
sandbox --formulations
```

A complete list is also available in the [formulations guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/formulations.md).
