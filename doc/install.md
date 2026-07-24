# Install and Verify NextGenSandbox

This guide explains how to install NextGenSandbox and verify that its core
workflow runs on a new machine.

- Use the [Quick Path](#quick-path) for the shortest first-time setup.
- Use the [Detailed Installation](#detailed-installation) sections for
  platform-specific guidance and expected results.
- See [diagnostics.md](./diagnostics.md) when a check or build step fails.

After installation, the next step is to understand and customize the project
configuration.

## Before You Begin

The complete NextGenSandbox build is intended for Linux, HPC systems, and
macOS. It uses a Unix-like shell and requires:

- Git
- Bash
- Python 3.11 or newer
- internet access while downloading packages and source repositories
- a C, C++, and Fortran build toolchain
- CMake, MPI, and NetCDF development libraries for building ngen and its models

HPC users may need to load site-provided compiler, MPI, NetCDF, CMake, Python,
or conda modules. See [setup_hpc.sh](../utils/setup_hpc.sh) for an example; the
exact module names vary by system.

Build environments, compiled software, and package caches are stored under
`$SANDBOX_BUILD_DIR`. On an HPC system, choose a project or scratch filesystem
with sufficient quota instead of a small home directory.

## Quick Path

Run these commands from a terminal. Platform-specific handling is required only
for the R subsetting dependencies.

### 1. Clone and configure

```bash
git clone https://github.com/ajkhattak/NextGenSandbox.git
cd NextGenSandbox
./bootstrap.sh --env --verbose
```

Open a new terminal or reload your shell, return to the repository, and check
the initial configuration:

```bash
./bootstrap.sh --check
```

At this stage, configured paths and shell setup should be reported. Warnings
about environments, ngen, models, or t-route are expected because they have not
been built yet.

### 2. Build and activate the Python environment

```bash
./bootstrap.sh --sandbox
```

Activate the environment using the method available on your system:

```bash
conda activate "$SANDBOX_ENV"
```

or:

```bash
source "$SANDBOX_ENV/bin/activate"
```

The shell prompt should indicate the Sandbox environment is active, and
`which sandbox` should point inside `$SANDBOX_ENV`. When the environment is not
active, `./bootstrap.sh --check` also reports the appropriate activation
command.

### 3. Install subsetting dependencies

On Linux or an HPC system with conda:

```bash
module load conda  # only when conda is provided as a module
./bootstrap.sh --subset
```

On macOS with a system R installation:

```bash
Rscript "$SANDBOX_DIR/src/R/install_load_libs.R" --install
```

### 4. Build ngen, models, and t-route

Keep the Sandbox Python environment active, then run:

```bash
./bootstrap.sh --ngen --models --troute
./bootstrap.sh --check
```

The final check should find the `ngen` executable, the Sandbox and forcing
Python environments, key Python imports, required R packages, and initialized
submodules.

### 5. Run the smoke test

Download a CONUS hydrofabric geopackage from
[Lynker Spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F),
then run:

```bash
python test/sandbox_test.py --all --gpkg <path/to/conus_nextgen.gpkg>
```

Expected final message:

```text
SUCCESS: NextGenSandbox smoke test completed. Installation and the core workflow are ready.
```

## Detailed Installation

### Step 1: Clone the repository

```bash
git clone https://github.com/ajkhattak/NextGenSandbox.git
cd NextGenSandbox
```

All remaining commands in this guide should be run from the repository root
unless stated otherwise.

### Step 2: Configure Sandbox paths

Configure the repository, build, data, and environment paths:

```bash
./bootstrap.sh --env --verbose
```

On first-time setup, open a new terminal or reload the shell setup before
continuing. Return to the repository and run:

```bash
./bootstrap.sh --check
```

`--check` is read-only: it does not install packages or create directories. It
reports the current installation state, so missing components are normal until
their corresponding build step has run. Follow the recommendations printed at
the end of the check.

Additional details about the generated paths are available in the
[environment validation guide](../utils/venv/validation.md#step-13-validation).

### Step 3: Build the Python environments

```bash
./bootstrap.sh --sandbox
```

This creates:

- the Sandbox Python environment at `$SANDBOX_ENV`
- the forcing Python environment at `$FORCING_ENV`
- the `sandbox` command in `$SANDBOX_ENV/bin`

Activate the Sandbox environment before building ngen or running workflow
commands.

With conda:

```bash
conda activate "$SANDBOX_ENV"
```

With a standard Python virtual environment:

```bash
source "$SANDBOX_ENV/bin/activate"
```

Verify the active command:

```bash
which sandbox
```

Expected: the reported path is inside `$SANDBOX_ENV`.

### Step 4: Install hydrofabric subsetting dependencies

This step installs the R packages and WhiteboxTools binary used by
`sandbox --subset`. These dependencies let NextGenSandbox extract
gage-specific geopackages from a larger hydrofabric.

This installation step only prepares the subsetting dependencies. It does not
subset hydrofabric resources for a project.

#### Linux and HPC systems

The managed subset environment requires conda. If conda is provided through an
environment module, load it in the same shell:

```bash
module load conda
./bootstrap.sh --subset
```

The environment and package caches are created under
`$SANDBOX_BUILD_DIR/rvenv`. If the build reports `~/.conda/pkgs`,
`Disk quota exceeded`, or package-extraction errors, see the
[subset build diagnostics](./diagnostics.md#subset-build-cannot-find-conda-or-hits-home-quota).

#### macOS

Install R from a trusted distribution. RStudio is optional. Some source
packages may also require the Xcode Command Line Tools and a compatible Fortran
compiler.

Install the required R packages using the system R installation:

```bash
Rscript "$SANDBOX_DIR/src/R/install_load_libs.R" --install
```

Do not use `./bootstrap.sh --subset` on Apple Silicon when its conda package set
cannot resolve the required R packages.

To install through RStudio instead, open
`src/R/install_load_libs.R` and click **Source**, or run:

```r
Sys.setenv(SANDBOX_R_DEPS_MODE = "install")
source(file.path(Sys.getenv("SANDBOX_DIR"), "src/R/install_load_libs.R"))
```

During a later `sandbox --subset` run, NextGenSandbox checks that the required R
packages are available. It does not install or compile missing packages while
processing gages.

#### Verify the subset environment

```bash
./bootstrap.sh --check
```

Expected:

- Linux/HPC: the managed subset `Rscript` and required R packages are found.
- macOS: the required packages are found in the system R installation.

The required package check includes `sf`, `terra`, `hfsubsetR`, and `zonal`.

### Step 5: Build ngen, models, and t-route

Confirm that the Sandbox Python environment is active, then build all three
components in their required order:

```bash
./bootstrap.sh --ngen --models --troute
```

The components may also be built separately:

```bash
./bootstrap.sh --ngen
./bootstrap.sh --models
./bootstrap.sh --troute
```

For an example HPC module setup, see [setup_hpc.sh](../utils/setup_hpc.sh).

### Step 6: Run the final installation check

```bash
./bootstrap.sh --check
```

Confirm that the check finds:

- Sandbox and forcing Python environments
- the `sandbox` command
- the `ngen` executable
- key Python package imports, including t-route
- required R packages
- initialized git submodules

If a required item is missing, follow the recommendation printed by the check
or see [diagnostics.md](./diagnostics.md).

### Step 7: Run the workflow smoke test

The smoke test verifies more than package installation. It exercises
hydrofabric subsetting, forcing preparation, configuration generation, and a
short ngen simulation.

Download a CONUS hydrofabric geopackage from
[Lynker Spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F),
then run the test from the active Sandbox environment:

```bash
python test/sandbox_test.py --all --gpkg <path/to/conus_nextgen.gpkg>
```

Expected final message:

```text
SUCCESS: NextGenSandbox smoke test completed. Installation and the core workflow are ready.
```

The installation is ready when both the final `--check` and smoke test pass.

## Next: Configure a Project

Continue to [configuration.md](./configuration.md) to understand the project
paths, resources, models, time periods, outputs, and calibration settings before
running a custom project.

If installation failed, use [diagnostics.md](./diagnostics.md). Contributors
can find the optional repository test suites in [testing.md](./testing.md).
