# NextGenSandbox

NextGenSandbox is a workflow tool for setting up, running, calibrating, and evaluating [NextGen/ngen](https://github.com/NOAA-OWP/ngen) hydrologic modeling experiments. It brings together common setup steps such as hydrofabric subsetting, forcing preparation, model configuration, calibration, validation, and large-scale job launching so users can move from basin resources to repeatable simulations with less manual wiring.

## Start Here

For a new machine or first-time setup, follow the [install guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/install.md). The guide includes a Quick Path, a detailed step-by-step setup, and a smoke test to verify the core workflow.

## Configuration

Guidance for setting up `sandbox_config.yaml`, `calib_config.yaml`, formulations, model instances, and task types is available in the [configuration guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/configuration.md).

The default basin-first directory structure, including how `input_dir` and `output_dir` are used, is described in the [directory layout guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/directory_layout.md).

For ML-based formulations, the configuration guide also documents how to stage trained LSTM and dHBV data under `$SANDBOX_DATA_DIR` and configure the model basefiles.

## Supported Formulations

For the most up-to-date list of supported formulations, run:

```bash
sandbox --formulations
```

A complete list is also available in the [formulations guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/formulations.md).

## Scaling Runs

After a single Sandbox configuration works, the [Sandbox Launcher](https://github.com/ajkhattak/NextGenSandbox/tree/main/tools/launcher) can run many gage/model experiments, manage calibration restarts, and submit jobs on HPC systems.
