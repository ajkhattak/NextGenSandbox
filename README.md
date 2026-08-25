# NextGenSandbox

NextGenSandbox is a workflow tool for setting up, running, calibrating, and
evaluating [NextGen/ngen](https://github.com/NOAA-OWP/ngen) hydrologic modeling
experiments. It brings hydrofabric subsetting, forcing preparation, model
configuration, calibration, validation, and large-scale job launching into one
repeatable workflow.

## Documentation

Read the complete
[NextGenSandbox documentation](https://ajkhattak.github.io/NextGenSandbox/).

## Getting Started

First-time users should follow these guides in order:

1. **[Install and verify NextGenSandbox](docs/install.md)**

   Build the environments, ngen, models, and t-route, then confirm the
   installation with the workflow smoke test.

2. **[Configure a project](docs/configuration.md)**

   Understand the single project `sandbox_config.yaml`, model defaults, and
   the settings that control resources, simulations, and calibration.

3. **[Run a project](docs/workflow.md)**

   Prepare hydrofabric and forcing resources, generate model files, inspect the
   command with dry run, and execute the simulation or calibration.

4. **[Scale with Sandbox Launcher](docs/launcher.md)** *(optional)*

   Apply working configuration templates across many gages and formulations,
   run locally, or submit jobs through Slurm.

Each guide ends with the next step in this sequence. Complete the smoke test
before configuring a custom project, and validate one normal project before
scaling it with Launcher.

## Reference Guides

Use these guides when the main sequence directs you to a specific topic:

| Topic | Guide |
|---|---|
| Directory organization | [Directory layout](docs/directory_layout.md) |
| Forcing files and rechunking | [Forcing data](docs/forcing.md) |
| Supported model combinations | [Formulations](docs/formulations.md) |
| Model instances and basefiles | [Model configuration](docs/model_configuration.md) |
| Calibration, DDS, and PSO | [Calibration](docs/calibration.md) |
| Local observations and objectives | [Observations](docs/observations.md) |
| Common setup and workflow errors | [Diagnostics](docs/diagnostics.md) |
| Contributor test suites | [Testing](docs/testing.md) |

## Supported Formulations

After installation, list the currently registered formulation components with:

```bash
sandbox --formulations
```

See the [formulations guide](docs/formulations.md) for supported combinations,
model variants, and setup notes.
