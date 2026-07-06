# Install And Verify NextGenSandbox

This guide explains how to install NextGenSandbox and verify that the core
workflow runs on a new machine. Use the [Quick Path](#quick-path) for the
short setup sequence and smoke test. Use the
[Detailed Installation Steps](#detailed-installation-steps) when you want the
expanded explanation for each installation stage. After the smoke test passes,
continue with the [configuration guide](./configuration.md) and the
[project workflow guide](./workflow.md). If a check or build step fails, see
[diagnostics.md](./diagnostics.md).

## Quick Path

For a typical first-time setup, build the workflow and run the smoke test:

1. Clone the repository and enter it:
   `git clone https://github.com/ajkhattak/NextGenSandbox && cd NextGenSandbox`
2. `./bootstrap.sh --env --verbose`
3. Reload your shell or open a new terminal
4. `./bootstrap.sh --check`
   - Expected: `SANDBOX_DIR`, `SANDBOX_BUILD_DIR`, and shell setup are reported.
     Missing build artifacts are normal before later steps.
5. `./bootstrap.sh --sandbox`
6. `./bootstrap.sh --check`
   - Expected: Sandbox Python, forcing Python, and the `sandbox` command are
     found.
7. Activate the sandbox Python environment
8. `./bootstrap.sh --subset`
9. `./bootstrap.sh --check`
   - Expected: subset `Rscript` exists and required R packages are available.
10. `./bootstrap.sh --ngen --models --troute`
11. `./bootstrap.sh --check`
   - Expected: `ngen` executable exists, key Python imports pass, and submodules
     are initialized.
12. Download a CONUS geopackage from [lynker-spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F)
13. `python test/sandbox_test.py --all --gpkg <path/to/conus_nextgen.gpkg>`
   - Expected: `SUCCESS: NextGenSandbox smoke test completed. Installation and
     the core workflow are ready.`

After the smoke test passes, review [configuration.md](./configuration.md) to
understand the configuration files, then use [workflow.md](./workflow.md) to set
up a single-basin project and scale larger runs with the Sandbox Launcher.

## Detailed Installation Steps

### <ins> Step 1. Build Sandbox Workflow
  1.1 Clone the repository (if not already done):
     
     git clone https://github.com/ajkhattak/NextGenSandbox && cd NextGenSandbox
     
  1.2 Ensure conda or Python (>=3.11) is available: \
     - Local machine: check Python version. \
     - HPC system: load conda or a compatible Python module, e.g., Python ≥ 3.11.

  1.3 Set up sandbox environment variables

     ./bootstrap.sh --env --verbose
    

  Validate this step [here](https://github.com/ajkhattak/NextGenSandbox/blob/main/utils/venv/validation.md#step-13-validation).

  > **Important:** On first-time setup, open a new terminal (or reload your shell) before continuing.

  1.3.1 Check the bootstrap status:

     ./bootstrap.sh --check

This command is read-only. It reports configured paths, available system tools,
Sandbox/forcing/subset environments, key Python and R packages, ngen/t-route
availability, and git submodule status.
  Run it after each major setup step, or whenever a Sandbox command fails and
  the cause is not obvious. For common warnings and failures, see
  [diagnostics.md](./diagnostics.md).

  1.4 Build the Sandbox workflow:
     
     ./bootstrap.sh --sandbox
     
  Validate this step [here](https://github.com/ajkhattak/NextGenSandbox/blob/main/utils/venv/validation.md#step-14-validation).

### <ins> Step 2. Install Subsetting Dependencies
This step installs the R packages and WhiteboxTools binary used by the
hydrofabric basin-subsetting workflow. These dependencies are required before
running `sandbox --subset`, which extracts basin geopackages from a larger
hydrofabric file for the gage IDs listed in `sandbox_config.yaml`.

This step only installs and verifies the subsetting software stack; it does not
run basin subsetting for a project. After the installation smoke test passes,
see [workflow.md](./workflow.md#subset-hydrofabric) for the project-level
`sandbox --subset` workflow and expected geopackage output locations.

  #### Option #1: HPC machines (load conda module) or macOS
  Run the following command in a terminal:
  ```
  ./bootstrap.sh --subset
  ```
  #### Option #2: macOS
  Ensure R and Rtools are already installed before proceeding.
  ```
  Rscript $SANDBOX_DIR/src/R/install_load_libs.R --install
  ```
  #### Option #3: Using RStudio on macOS/Windows
   - Open `<path_to_sandbox_repo>/src/R/install_load_libs.R` in RStudio. Click Source to execute the script.
   - Alternatively, run the following command in the RStudio Console: `Sys.setenv(SANDBOX_R_DEPS_MODE = "install"); source("~/<path_to_sandbox_repo>/src/R/install_load_libs.R")`

  During `sandbox --subset`, the workflow checks that these R packages are
  already available. It does not install or compile missing R packages during a
  subsetting run.

If this step succeeds, the subset environment is ready. You can confirm with:

```bash
./bootstrap.sh --check
```

Expected: `Subset Rscript` is found and the subset R packages `sf`, `terra`,
`hfsubsetR`, and `zonal` are reported as available.

### <ins> Step 3. Activate Sandbox Environment
The sandbox setup step configures the required environment variables: `SANDBOX_DIR, SANDBOX_BUILD_DIR, SANDBOX_DATA_DIR, SANDBOX_ENV`, enabling easy navigation and environment activation. By default, build artifacts live under `$SANDBOX_DIR/build` and persistent model data live under `$SANDBOX_DATA_DIR`.
>**NOTE:** This environment must be activated before performing Step 4 and subsequent steps.

**Activate the virtual environment:**
 - If using Conda:
   ```
   conda activate $SANDBOX_ENV
   ```
 - If using a standard Python virtual environment:
   ```
   source $SANDBOX_ENV/bin/activate
   ```


### <ins> Step 4. Build NextGen And Required Models
> **Important:** Before continuing to later steps, you must install and build ngen and the required routing/models components.

> **Note:** Build ngen and the required models after Step 1 has created the sandbox environment and after that environment is activated.
Please activate the sandbox environment, then follow the instructions in the [build_models](https://github.com/ajkhattak/NextGenSandbox/blob/main/utils/build_models.sh) script to build ngen and models. For an example HPC setup, see [setup_hpc.sh](https://github.com/ajkhattak/NextGenSandbox/blob/main/utils/setup_hpc.sh). A typical build sequence is:
```
./bootstrap.sh --ngen
./bootstrap.sh --models
./bootstrap.sh --troute
```

You can also run the build steps separately as needed:
```
./bootstrap.sh [OPTIONS]
Options:
  --check    Check environment, tools, package imports, and build artifacts
  --ngen     Build ngen
  --models   Build models
  --troute   Build t-route
```

### <ins> Step 5. Verify Environment

Before moving on to configuration, confirm that the environment bootstrap succeeded:

- Run `./bootstrap.sh --check`
- Validate Step 1.3 with [utils/venv/validation.md](../utils/venv/validation.md#step-13-validation)
- Validate Step 1.4 with [utils/venv/validation.md](../utils/venv/validation.md#step-14-validation)

If any item is missing or unclear, check [diagnostics.md](./diagnostics.md)
before continuing.

### <ins> Step 6. Run Workflow Smoke Test

After the installation steps finish, run the smoke test to confirm that
subsetting, forcing preparation, configuration generation, and a short ngen run
all work together. Download a CONUS geopackage from
[lynker-spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F)
first.

```bash
python test/sandbox_test.py --all --gpkg <path/to/conus_nextgen.gpkg>
```

Run this from the active Sandbox Python environment. You can confirm with:

```bash
which sandbox
python -c "import sandbox; print(sandbox.__file__)"
```

Expected final message:

```text
SUCCESS: NextGenSandbox smoke test completed. Installation and the core workflow are ready.
```

When the smoke test completes successfully, continue with:

- [configuration.md](./configuration.md) to understand the configuration files
- [workflow.md](./workflow.md) to set up a single-basin project and scale larger runs
