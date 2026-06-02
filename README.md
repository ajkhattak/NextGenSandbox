# Next-Generation Framework Sandbox Hub (NextGenSandboxHub)
The Next-Generation Water Resources Modeling Framework ([NextGen](https://github.com/NOAA-OWP/ngen)), developed by the NOAA's Office of Water Prediction is a language- and model-agnostic framework, which allows to run a mosaic of surface and subsurface models in a single basin comprised of 10s-100s sub-catchments. 

### Schematic 
A conceptual workflow diagram of the NextGenSandboxHub is available [here](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/doc/schematic.md)

### Getting Started with NextGen Sandbox

Detailed instructions for building, configuring, and running NextGenSandboxHub for calibration and validation experiments are available in the [INSTALL guide](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/INSTALL.md) 

### Configuration

Guidance for setting up `sandbox_config.yaml`, `calib_config.yaml`, formulations, model instances, and task types is available in the [configuration guide](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/doc/configuration.md).

### Currently Supported Formulations:
For the most up-to-date list of supported formulations, run `sandbox --formulations`. A complete list is also available in the [FORMULATIONS](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/FORMULATIONS.md)

### Sandbox Launcher
The sandbox launcher enables a single command to automatically run multiple hydrologic formulations across many gages, manage calibration, restarts, validation, and submit all jobs efficiently on HPC systems. For more details see [launcher](https://github.com/ajkhattak/NextGenSandboxHub/tree/main/tools/launcher)
