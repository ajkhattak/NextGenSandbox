# Getting Started with NextGen Sandbox: Build, Configure, and Run

Detailed instructions on how to install, configure, and get NextGenSandbox running.

## Quick Path

For a typical setup, the workflow is:

1. `./bootstrap.sh --env --verbose`
2. Reload your shell or open a new terminal
3. `./bootstrap.sh --check`
4. `./bootstrap.sh --sandbox`
5. `./bootstrap.sh --check`
6. Activate the sandbox Python environment
7. `./bootstrap.sh --subset`
8. `./bootstrap.sh --check`
9. `./bootstrap.sh --ngen --models --troute`
10. `./bootstrap.sh --check`
11. Review [configuration.md](./configuration.md) and update `configs/sandbox_config.yaml`
12. Run `sandbox --subset`, `sandbox --forc`, `sandbox --conf`, and `sandbox --run`

### <ins>  Step 1. Build Sandbox Workflow
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
  the cause is not obvious.

  1.4 Build the Sandbox workflow:
     
     ./bootstrap.sh --sandbox
     
  Validate this step [here](https://github.com/ajkhattak/NextGenSandbox/blob/main/utils/venv/validation.md#step-14-validation).

### <ins>  Step 2. Hydrofabric Installation
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

### <ins>  Sandbox Virtual Environment Activation
The sandbox setup step configures the required environment variables: `SANDBOX_DIR, SANDBOX_BUILD_DIR, SANDBOX_DATA_DIR, SANDBOX_ENV`, enabling easy navigation and environment activation. By default, build artifacts live under `$SANDBOX_DIR/build` and persistent model data live under `$SANDBOX_DATA_DIR`.
>**NOTE:** This environment must be activated before performing Step 3 and subsequent steps.

**Activate the virtual environment:**
 - If using Conda:
   ```
   conda activate $SANDBOX_ENV
   ```
 - If using a standard Python virtual environment:
   ```
   source $SANDBOX_ENV/bin/activate
   ```


### <ins> Step 3. Install NextGen (ngen) and Required Models
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

### <ins> Environment Verification

Before moving on to configuration, confirm that the environment bootstrap succeeded:

- Run `./bootstrap.sh --check`
- Validate Step 1.3 with [utils/venv/validation.md](../utils/venv/validation.md#step-13-validation)
- Validate Step 1.4 with [utils/venv/validation.md](../utils/venv/validation.md#step-14-validation)

### <ins> Step 4. Setup configuration file
Open the configuration file `$SANDBOX_DIR/configs/sandbox_config.yaml`

Review and update the blocks in [sandbox_config.yaml](../configs/sandbox_config.yaml) to match your local environment. The file already contains detailed inline instructions for each configuration block.

For formulation selection, `model_instances`, task types, and calibration config linkage, see the [configuration guide](./configuration.md).

### <ins> Step 5. Hydrofabric Subsetting
  - Dependency: Step 2 & Step 4
  - Download domain (CONUS or oCONUS) from [lynker-spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F), for instance, conus/conus_nextgen.gpkg
  - From command line run:
    ```
    sandbox --subset -i <sandbox_config_filename.yaml>
    ```
  - Using RStudio
      - open `<path_to_sandbox_repo>/src/R/main.R` in RStudio and source on main.R. Note Set file name `infile_config` [here](https://github.com/ajkhattak/NextGenSandbox/blob/main/src/R/main.R#L53)
    
    If everything goes well, a basin geopackage will be subsetted for each selected gage. With the default `general.layout: basin`, files are written under `<input_dir>/<gage_id>/hydrofabric/gage_<gage_id>.gpkg`. With `general.layout: flat`, files are written under `<input_dir>/hydrofabric/gage_<gage_id>.gpkg`.

### <ins> Step 6. Forcing Data Download
The workflow uses [CIROH_DL_NextGen](https://github.com/ajkhattak/CIROH_DL_NextGen) forcing_prep tool to download atmospheric forcing data. To download the forcing data run:
```
   sandbox --forc -i <sandbox_config_filename.yaml>
```

### <ins>  Step 7. Generate Configuration and Realization Files
If you have not already done so, review and update the sandbox config file [here](../configs/sandbox_config.yaml), particularly the `formulation` and `simulation` blocks, then run:
 ```
    sandbox --conf -i <sandbox_config_filename.yaml> -j <calib_config_filename.yaml>
 ```
### <ins> Step 8. Run Calibration/Validation Simulations
Run the following command — assuming you have already set up the sandbox configuration file [here](../configs/sandbox_config.yaml) and calibration configuration file [here](../configs/calib_config.yaml).
 ```
    sandbox --run -i <sandbox_config_filename.yaml> -j <calib_config_filename.yaml>
 ```

### <ins> Workflow Smoke Test

After the workflow is built, configured, and the required data are available, run the following end-to-end test. Download a CONUS geopackage from [lynker-spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F) first.

```
python test/sandbox_test.py --all --gpkg <path/to/conus_nextgen.gpkg>
```
