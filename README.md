# NextGenSandbox

NextGenSandbox is a workflow tool for setting up, running, calibrating, and
evaluating [NextGen/ngen](https://github.com/NOAA-OWP/ngen) hydrologic modeling
experiments. It brings hydrofabric subsetting, forcing preparation, model
configuration, calibration, validation, and large-scale job launching into one
repeatable workflow.

## Getting Started

First-time users should follow these guides in order:

1. **[Install and verify NextGenSandbox](doc/install.md)**

   Build the environments, ngen, models, and t-route, then confirm the
   installation with the workflow smoke test.

2. **[Configure a project](doc/configuration.md)**

   Understand `sandbox_config.yaml`, `calib_config.yaml`, model defaults, and
   the settings that control project resources and simulations.

3. **[Run a project](doc/workflow.md)**

   Prepare hydrofabric and forcing resources, generate model files, inspect the
   command with dry run, and execute the simulation or calibration.

4. **[Scale with Sandbox Launcher](tools/launcher/README.md)** *(optional)*

   Apply working configuration templates across many gages and formulations,
   run locally, or submit jobs through Slurm.

Each guide ends with the next step in this sequence. Complete the smoke test
before configuring a custom project, and validate one normal project before
scaling it with Launcher.

## Reference Guides

Use these guides when the main sequence directs you to a specific topic:

| Topic | Guide |
|---|---|
| Directory organization | [Directory layout](doc/directory_layout.md) |
| Forcing files and rechunking | [Forcing data](doc/forcing.md) |
| Supported model combinations | [Formulations](doc/formulations.md) |
| Model instances and basefiles | [Model configuration](doc/model_configuration.md) |
| Calibration, DDS, and PSO | [Calibration](doc/calibration.md) |
| Local observations and objectives | [Observations](doc/observations.md) |
| Common setup and workflow errors | [Diagnostics](doc/diagnostics.md) |
| Contributor test suites | [Testing](doc/testing.md) |

## Supported Formulations

After installation, list the currently registered formulation components with:

```bash
sandbox --formulations
```

See the [formulations guide](doc/formulations.md) for supported combinations,
model variants, and setup notes.
