# NextGenSandbox

NextGenSandbox is a workflow tool for setting up, running, calibrating, and
evaluating [NextGen/ngen](https://github.com/NOAA-OWP/ngen) hydrologic modeling
experiments. It brings hydrofabric subsetting, forcing preparation, model
configuration, calibration, validation, and large-scale job launching into one
repeatable workflow.

## Getting Started

First-time users should follow these guides in order:

1. **[Install and verify NextGenSandbox](install.md)**

   Build the environments, ngen, models, and t-route, then confirm the
   installation with the workflow smoke test.

2. **[Configure a project](configuration.md)**

   Understand the project and calibration configuration files, model defaults,
   and settings that control resources and simulations.

3. **[Run a project](workflow.md)**

   Prepare hydrofabric and forcing resources, generate model files, inspect the
   command with dry run, and execute the simulation or calibration.

4. **[Scale with Sandbox Launcher](https://github.com/ajkhattak/NextGenSandbox/tree/main/tools/launcher)** *(optional)*

   Apply working configuration templates across many gages and formulations,
   run locally, or submit jobs through Slurm.

## Reference Guides

Use the navigation menu or search to find focused guidance about directory
layouts, forcing data, formulations, model configuration, calibration,
observations, diagnostics, and testing.

## Source Repository

The source code, Markdown documentation, examples, and issue tracker are
available in the
[NextGenSandbox GitHub repository](https://github.com/ajkhattak/NextGenSandbox).
