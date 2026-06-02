# Getting Started with NextGen Sandbox: Build, Configure, and Run

Detailed instructions on how to install, configure, and get the NextGenSandboxHub running.

### <ins>  Step 1. Build Sandbox Workflow
  1.1 Clone the repository (if not already done):
     
     git clone https://github.com/ajkhattak/NextGenSandboxHub && cd NextGenSandboxHub
     
  1.2 Ensure conda or Python (>=3.11) is available: \
     - Local machine: check Python version. \
     - HPC system: load conda or a compatible Python module, e.g., Python ≥ 3.11.

  1.3 Set up sandbox environment variables

     ./bootstrap.sh --env --verbose
    

  Validate this step [here](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/utils/venv/validation.md#step-13-validation).

  > **Important:** On first-time setup, open a new terminal (or reload your shell) before continuing.

  1.4 Build the Sandbox workflow:
     
     ./bootstrap.sh --sandbox
     
  Validate this step [here](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/utils/venv/validation.md#step-14-validation).

### <ins>  Step 2. Hydrofabric Installation
  #### Option #1: HPC machines (load conda module) or macOS
  Run the following command in a terminal:
  ```
  ./bootstrap.sh --subset
  ```
  #### Option #2: macOS
  Ensure R and Rtools are already installed before proceeding.
  ```
  Rscript $SANDBOX_DIR/src/R/install_load_libs.R
  ```
  #### Option #3: Using RStudio on macOS/Windows
   - Open `<path_to_sandboxhub>/src/R/install_load_libs.R` in RStudio. Click Source to execute the script.
   - Alternatively, run the following command in the RStudio Console: `source("~/<path_to_sandboxhub>/src/R/install_load_libs.R")`

### <ins>  Sandbox Virtual Environment Activation
The sandbox setup step configures the required environment variables: `SANDBOX_DIR, SANDBOX_BUILD_DIR, SANDBOX_ENV`, enabling easy navigation and environment activation.
>**NOTE:** This environment must be activated before performing Step 3 and subsequent steps.

**Activate the virtual environment:**
 - If using Conda:
   ```
   conda activate $SANDBOX_ENV
   ```
 - If using a standard Python virtual environment:
   ```
   source $SANDBOX_ENV
   ```


### <ins> Step 3. Install NextGen (ngen) and Required Models
> **Important:** Before continuing to later steps, you must install and build ngen and the required routing/models components.

> **Note:** The sandbox workflow assumes that [ngen](https://github.com/NOAA-OWP/ngen) and models including [t-route](https://github.com/NOAA-OWP/t-route) have been built in the Python virtual environment created in Step 1.
Please activate the sandbox environment and follow the instructions in the [build_models](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/utils/build_models.sh) script to build ngen and models. For an example HPC setup, see [setup_hpc.sh](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/utils/setup_hpc.sh). After loading the required modules and setting up the environment variables, run the following command:
```
./bootstrap.sh [OPTIONS]
Options:
  --ngen     Build ngen
  --models   Build models
  --troute   Build t-route
```
### <ins>Verification Test
Run the following command to verify that everything has been set up successfully. Download conus geopackage file from [lynker-spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F).
```
   python test/sandbox_test.py --all --gpkg <path/to/conus_nextgen.gpkg>
```

### <ins> Step 4. Setup configuration file
Open the configuration file `$SANDBOX_DIR/configs/sandbox_config.yaml`

Review and update the blocks in [sandbox_config.yaml](../configs/sandbox_config.yaml) to match your local environment. The file already contains detailed inline instructions for each configuration block.

### <ins> Step 5. Hydrofabric Subsetting
  - Dependency: Step 2 & Step 4
  - Download domain (CONUS or oCONUS) from [lynker-spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F), for instance, conus/conus_nextgen.gpkg
  - From command line run:
    ```
    sandbox --subset -i <sandbox_config_filename.yaml>
    ```
  - Using RStudio
      - open `<path_to_sandboxhub>/src/R/main.R` in RStudio and source on main.R. Note Set file name `infile_config` [here](https://github.com/ajkhattak/NextGenSandboxHub/blob/main/src/R/main.R#L53) 
    
    If everything goes well, a basin geopackage will be subsetted and stored under `<input_dir>/<gage_id>/data/gage_<gage_id>.gpkg`

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
