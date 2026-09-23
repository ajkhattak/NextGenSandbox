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

Every installation uses a local environment profile copied from
[`configs/sandbox_profile.sh`](https://github.com/ajkhattak/NextGenSandbox/blob/main/configs/sandbox_profile.sh).
Its defaults support a normal local installation. HPC users customize the same
profile to load site-provided compiler, MPI, NetCDF, CMake, Python, or conda
modules. The profile configures only the current shell, never edits shell
startup files, and can also be used by Sandbox Launcher jobs.

Build environments, compiled software, and package caches are stored under
`$SANDBOX_BUILD_DIR`. On an HPC system, choose a project or scratch filesystem
with sufficient quota instead of a small home directory. Compiled components
use `SANDBOX_BUILD_JOBS=2` by default; increase it only when the build node has
enough memory for additional concurrent compiler processes.

For routine HPC installations, the recommended build stack is GCC with an
OpenMPI module built using that GCC version. Load NetCDF and other compiled
libraries from the same compiler family. Intel builds are supported as a
separate, optional profile and should use MPI and libraries built with the
Intel compiler.

## Quick Path

Run these commands from Bash or zsh. HPC users should first identify a matched
compiler, MPI, NetCDF, CMake, Python, and conda module stack for their site.

### 1. Clone and load the environment profile

```bash
git clone https://github.com/ajkhattak/NextGenSandbox.git
cd NextGenSandbox
cp configs/sandbox_profile.sh sandbox_profile.sh
```

The copied file is ignored by Git. Its defaults are suitable for a local
installation. On HPC systems, edit its module commands and set
`SANDBOX_BUILD_DIR` to project or scratch storage before continuing.

Load the profile and inspect the initial configuration:

```bash
source ./sandbox_profile.sh
./bootstrap.sh --check
```

The profile must be sourced in each new terminal. At this stage, configured
paths should be reported. Warnings about environments, ngen, models, or t-route
are expected because they have not been built yet.

### 2. Build and activate the Python environment

```bash
./bootstrap.sh --sandbox
source ./sandbox_profile.sh
```

On Linux, the profile prepends `$SANDBOX_ENV/lib` to the current shell's
runtime library path. This lets directly launched ngen processes find the
Sandbox Python and C++ libraries while retaining the MPI, NetCDF, and compiler
paths supplied by the loaded modules. No shell-startup-file changes are
required.

Sourcing the profile again activates either the Conda environment or Python
virtual environment created by the build. The shell prompt should indicate the
Sandbox environment is active, and
`which sandbox` should point inside `$SANDBOX_ENV`. When the environment is not
active, `./bootstrap.sh --check` also reports the appropriate activation
command.

### 3. Install subsetting dependencies

On Linux or an HPC system, ensure the profile loads conda, then run:

```bash
./bootstrap.sh --subset
```

On macOS with a system R installation:

```bash
Rscript "$SANDBOX_DIR/src/R/install_load_libs.R" --install
```

### 4. Build ngen, models, and t-route

Keep the Sandbox profile loaded. It uses explicit compiler variables when
configured and otherwise selects the available MPI compiler wrappers. When
`nf-config` is available, it also derives `NETCDF_ROOT`. Run:

```bash
./bootstrap.sh --check
```

The check reports the compilers behind the MPI wrappers and warns if an
existing ngen build was configured with a different compiler family.

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

### Step 2: Configure the environment profile

Copy the profile template into the repository root:

```bash
cp configs/sandbox_profile.sh sandbox_profile.sh
```

The root-level copy is ignored by Git and becomes the installation-specific
configuration. Local users can keep its defaults. HPC users should edit it to:

- load a consistent compiler, MPI, NetCDF, CMake, and conda module stack;
- set compiler-specific build storage through `SANDBOX_BUILD_DIR`;
- set `SANDBOX_BUILD_JOBS` to the desired build parallelism, normally `2`;
- set `NETCDF_ROOT` or other site-specific library paths when they cannot be
  detected.

#### Choose one HPC toolchain

GCC with a matching OpenMPI installation is the recommended production setup
because it is widely available across HPC systems. A typical profile uses:

```bash
module load gcc/<version>
module load openmpi/<version-built-with-gcc>
module load netcdf-fortran/<version-built-with-gcc>
export SANDBOX_BUILD_DIR="$SANDBOX_REPO/build/gcc"
```

An Intel build should use a separate profile and build directory:

```bash
module load intel/<version>
module load openmpi/<version-built-with-intel>
module load netcdf-fortran/<version-built-with-intel>
export SANDBOX_BUILD_DIR="$SANDBOX_REPO/build/intel"
```

In both profiles, let `sandbox_profile.sh` select `mpicc`, `mpicxx`, and
`mpifort`. Do not set `FC=gfortran` inside an otherwise Intel-based profile;
that creates a mixed compiler build and loads both GNU and Intel Fortran
runtimes.

Load the profile and run the initial check:

```bash
source ./sandbox_profile.sh
./bootstrap.sh --check
```

`--check` is read-only: it does not install packages or create directories. It
reports the current installation state, so missing components are normal until
their corresponding build step has run. Follow the recommendations printed at
the end of the check.

The profile must be sourced once in each new terminal. It does not edit
`.bashrc`, `.bash_profile`, or `.zshrc`.

### Step 3: Build the Python environments

```bash
./bootstrap.sh --sandbox
source ./sandbox_profile.sh
```

This creates:

- the Sandbox Python environment at `$SANDBOX_ENV`
- the forcing Python environment at `$FORCING_ENV`
- the `sandbox` command in `$SANDBOX_ENV/bin`

The first command creates the environments. Sourcing the profile again detects
and activates the newly created Conda environment or Python virtual
environment.

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
environment module, configure that module in `sandbox_profile.sh`, source the
profile, and run:

```bash
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

Set a distinct `SANDBOX_BUILD_DIR` in each profile, such as `build/gcc` or
`build/intel`, so compiled libraries from different toolchains never mix. Do
not reuse an existing build directory after changing the compiler or MPI
implementation.

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
