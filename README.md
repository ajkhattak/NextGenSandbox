# NextGenSandbox

NextGenSandbox is a workflow tool for setting up, running, calibrating, and evaluating [NextGen/ngen](https://github.com/NOAA-OWP/ngen) hydrologic modeling experiments. It brings together common setup steps such as hydrofabric subsetting, forcing preparation, model configuration, calibration, validation, and large-scale job launching so users can move from basin resources to repeatable simulations with less manual wiring.

### Schematic 
A conceptual workflow diagram of NextGenSandbox is available [here](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/schematic.md)

### Getting Started with NextGen Sandbox

Detailed instructions for building, configuring, and running NextGenSandbox for calibration and validation experiments are available in the [install guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/install.md)

### Configuration

Guidance for setting up `sandbox_config.yaml`, `calib_config.yaml`, formulations, model instances, and task types is available in the [configuration guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/configuration.md).

The default basin-first directory structure, including how `input_dir` and `output_dir` are used, is described in the [directory layout guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/directory_layout.md).

For ML-based formulations, the configuration guide also documents how to stage trained LSTM and dHBV data under `$SANDBOX_DATA_DIR` and configure the model basefiles.

### Currently Supported Formulations:
For the most up-to-date list of supported formulations, run `sandbox --formulations`. A complete list is also available in the [formulations guide](https://github.com/ajkhattak/NextGenSandbox/blob/main/doc/formulations.md)

### Sandbox Launcher
The sandbox launcher enables a single command to automatically run multiple hydrologic formulations across many gages, manage calibration, restarts, validation, and submit all jobs efficiently on HPC systems. For more details see [launcher](https://github.com/ajkhattak/NextGenSandbox/tree/main/tools/launcher)
