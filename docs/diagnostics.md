# Diagnostics And Common Issues

This page collects common setup and workflow issues without crowding the main
installation guide. Start with:

```bash
source ./sandbox_profile.sh
./bootstrap.sh --check
```

`--check` is read-only. It reports what is configured, what exists on disk, and
which Python/R/build components are available.

## Bootstrap Check Status

- `[SET]` means a path or variable is configured. It does not mean the
  component has been built.
- `[OK]` means the item exists or the import/check succeeded.
- `[WARN]` means the item may be valid for your current stage, but later steps
  may require it.
- `[MISSING]` means the item is not available and should be fixed before using
  the related workflow step.

When output is written directly to an interactive terminal, these status labels
are colored for readability. Redirected output remains plain text. Set
`NO_COLOR=1` to disable terminal colors. The check ends with a deduplicated
`Recommended Next Steps` list based on the issues it detected.

## Environment Profile Is Not Loaded

Symptom from `./bootstrap.sh --check`:

```text
[WARN] No Sandbox environment profile is loaded
```

Create the installation-specific profile once, then source it in every new
terminal:

```bash
cp configs/sandbox_profile.sh sandbox_profile.sh
source ./sandbox_profile.sh
```

Do not add the internal `scripts/bootstrap/sandbox_env.sh` file directly to a
shell startup file. Customize and reuse the profile instead.

Installations created by an older release may already contain a line that
sources `scripts/bootstrap/sandbox_env.sh` in `.bashrc`, `.bash_profile`, or
`.zshrc`. Remove that line once the profile workflow is in use; current
versions do not modify shell startup files.

## Wrong Python Environment

Symptom:

```text
ModuleNotFoundError: No module named 'sandbox'
```

or:

```text
/bin/sh: sandbox: command not found
```

Likely cause: the Sandbox Python environment is not active, or `$SANDBOX_ENV/bin`
is not on `PATH`. This can happen during the smoke test because the test script
launches the `sandbox` command internally.

Check:

```bash
which sandbox
python -c "import sandbox; print(sandbox.__file__)"
```

Expected: both should point under `$SANDBOX_ENV` or the Sandbox repository.

Fix:

```bash
source ./sandbox_profile.sh
```

## Missing Subsetting R Packages

Symptom from `./bootstrap.sh --check`:

```text
[MISSING] subset R package 'hfsubsetR'
[MISSING] subset R package 'zonal'
```

The `sandbox --subset` workflow requires the R subsetting packages to already
be installed. It checks dependencies during a run but does not compile/install
missing packages at that time.

Fix:

```bash
./bootstrap.sh --subset
```

On macOS, if conda-based R packages are difficult to resolve, install through
system R or RStudio:

```bash
Rscript "$SANDBOX_DIR/src/R/install_load_libs.R" --install
```

Then rerun:

```bash
./bootstrap.sh --check
```

### RANN compilation fails while installing hfsubsetR

A failure containing `DBL_MAX was not declared` while compiling CRAN `RANN`
prevents the dependent `hydroloom`, `nhdplusTools`, and `hfsubsetR` packages
from installing. Current Sandbox environments install the Conda `r-rann`
binary and avoid that source compilation. Update the repository and rerun:

```bash
./bootstrap.sh --subset
```

An existing subset environment is updated in place when `RANN` is missing; it
does not need to be deleted and rebuilt.

## Subset Build Cannot Find Conda Or Hits Home Quota

Symptoms from `./bootstrap.sh --subset`:

```text
./scripts/bootstrap/build_venv_subset.sh: line 9: conda: command not found
```

or:

```text
Disk quota exceeded
~/.conda/pkgs
*.conda extraction failed
```

On many HPC systems, conda is only available after loading a module. Load the
site's conda module in the same shell before running the subset build:

```bash
module load conda
./bootstrap.sh --subset
```

The subset build is intended to keep conda environments and package caches under
`$SANDBOX_BUILD_DIR/rvenv`, for example:

```text
$SANDBOX_BUILD_DIR/rvenv/conda_envs
$SANDBOX_BUILD_DIR/rvenv/conda_pkgs
```

If mamba still reports paths under `~/.conda/pkgs`, the user's home conda cache
may contain partial downloads from an earlier failed install or may be over
quota. Clean the home conda cache, or set `SANDBOX_BUILD_DIR` to a project or
scratch filesystem with enough space, then rerun:

```bash
./bootstrap.sh --subset
```

## ngen Or Model Build Missing

Symptoms:

```text
[WARN] ngen executable not found
[MISSING] nwm_routing import (t-route)
```

Fix after activating the Sandbox environment:

```bash
./bootstrap.sh --ngen --models --troute
./bootstrap.sh --check
```

If only one component is missing, run the matching flag, such as
`./bootstrap.sh --troute`.

## Linux C++ Runtime Or Compiler Mismatch

Symptoms while linking or starting ngen may include:

```text
version `GLIBCXX_3.4.30' not found
version `CXXABI_1.3.15' not found
```

This means compiled Conda libraries require a newer C++ runtime than the one
selected from the HPC compiler modules. Current conda-forge Python and NumPy
builds cannot be solved against the older GCC 11 runtime. On Linux,
`sandbox_profile.sh` prepends `$SANDBOX_ENV/lib` to `LD_LIBRARY_PATH` and
`LIBRARY_PATH`, and prepends the Sandbox `libstdc++.so.6` to `LD_PRELOAD`.
This lets direct ngen and `mpirun` commands find the Sandbox Python and C++
libraries while retaining the compiler, MPI, NetCDF, and UDUNITS paths
supplied by the loaded modules.

Confirm the runtime and other shared dependencies with:

```bash
./bootstrap.sh --check
```

If a failed environment build used the short-lived GCC 11-pinned environment
definition, update the repository, remove the incomplete environment, and
rebuild it:

```bash
sandbox_env_path="$SANDBOX_ENV"
conda deactivate
conda env remove -p "$sandbox_env_path"
./bootstrap.sh --sandbox
source ./sandbox_profile.sh
./bootstrap.sh --check
```

Do not override `PATH`, `LD_LIBRARY_PATH`, or `LD_PRELOAD` in a shell startup
file. Source the installation-specific `sandbox_profile.sh` instead, so these
settings apply only to the current Sandbox shell and launcher jobs that source
the same profile.

### Testing ngen directly on Slurm

Sandbox gives spawned ngen processes a scoped C++ runtime. It also launches an
MPI-enabled ngen through `mpirun` inside a Slurm allocation, including basins
that use only one process. This avoids OpenMPI treating the process as a direct
`srun` launch when the site OpenMPI module lacks Slurm PMI support.

A manual ngen command bypasses the Sandbox process setup. After sourcing the
installation's profile, run it through `mpirun`:

```bash
source ./sandbox_profile.sh
mpirun -np 1 "$NGEN_DIR/cmake_build/ngen" <ngen-arguments>
```

For a one-off test in a shell that has not sourced the profile, use:

```bash
env \
  LD_LIBRARY_PATH="$SANDBOX_ENV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  LD_PRELOAD="$SANDBOX_ENV/lib/libstdc++.so.6${LD_PRELOAD:+:$LD_PRELOAD}" \
  mpirun -np 1 "$NGEN_DIR/cmake_build/ngen" <ngen-arguments>
```

If a partition file is part of the generated Sandbox command, include it as
the final ngen argument. Do not launch an MPI-enabled ngen executable directly
from an interactive Slurm allocation.

## MPI Compiler Variables Are Not Set

`./bootstrap.sh --check` reports the C, C++, and Fortran compilers used behind
the loaded MPI wrappers. Before building ngen and its models, select those
wrappers explicitly:

```bash
export CC="$(command -v mpicc)"
export CXX="$(command -v mpicxx)"
export FC="$(command -v mpifort)"
export F90="$FC"
./bootstrap.sh --check
```

For routine HPC builds, prefer GCC with an OpenMPI and NetCDF stack built using
the same GCC version. Keep optional Intel builds in a separate
`SANDBOX_BUILD_DIR`. Do not set `FC=gfortran` while `CC` and `CXX` use
Intel-backed MPI wrappers; that mixes compiler runtimes within one build.

If the check says the existing ngen CMake compilers use a different compiler
family, rebuild the compiled components with
`./bootstrap.sh --ngen --models --troute --clean`. Preserve any `LIBRARY_PATH`
set by the loaded compiler and NetCDF modules because t-route uses it while
linking native extensions. Do not replace it with `LD_LIBRARY_PATH`.

### Intel compilers with OpenMPI

Older t-route setup files assume that any Intel compiler is paired with Intel
MPI and try to link `libmpifort`. OpenMPI does not provide that Intel MPI
library. NextGenSandbox detects an Intel Fortran compiler behind an OpenMPI
wrapper and adjusts the t-route wheel build to use OpenMPI's `libmpi` plus the
Intel compiler runtime libraries. This is a temporary compatibility adjustment
that can be removed after t-route detects the MPI implementation upstream.

If the t-route wheel still fails, retain the first linker error printed above
`Failed building wheel for troute.network`; the final `CalledProcessError` only
reports that the link command failed. Confirm the active wrappers with:

```bash
mpicc --showme:command
mpifort --showme:command
mpifort --showme:link
```

All three commands must describe the compiler and OpenMPI installation loaded
by the active Sandbox profile.

### Compiler terminated by a kill signal

A compiler process terminated by `kill signal` commonly indicates that the
build exceeded available memory. The profile defaults to two concurrent CMake
build processes. Reduce it to one on a memory-constrained node:

```bash
export SANDBOX_BUILD_JOBS=1
./bootstrap.sh --ngen --models
```

Increase `SANDBOX_BUILD_JOBS` only when the build node has enough memory. This
setting controls ngen and model compilation; the t-route build remains serial.

## Git Submodules Not Initialized

Symptom:

```text
[MISSING] Not initialized: ... extern/<name>
```

Fix:

```bash
git submodule update --init --recursive
```

Then rerun the relevant build step and `./bootstrap.sh --check`.

## Subsetting Failed For A Gage

Failed subsetting work is written to:

```text
<input_dir>/failed_gages/<gage_id>/subsetting_error.txt
```

Common causes:

- the gage ID is not valid or not present in the selected hydrofabric
- `subsetting.hydrofabric.gpkg_path` points to the wrong hydrofabric version
- DEM-derived attributes were requested but the DEM path is invalid
- R subsetting packages are missing

If `subsetting.hydrofabric.compute_divide_attributes: FALSE`, the workflow
should only subset geopackages and should not create DEM output.

If a large local-hydrofabric batch pauses during gage metadata lookup, set the
common domain explicitly under `general`, for example:

```yaml
general:
  domain: conus
  gages:
    option: ids
    ids: ["01308000", "03366500"]
```

Without this field, Sandbox queries USGS metadata to infer the domain for each
gage. Use separate batches when gages span multiple domains.

## Forcing Download Or Network Failure

Symptoms:

```text
Forcing generation failed before post-processing.
```

or missing NetCDF forcing files after `sandbox --forc`.

Common causes:

- remote forcing data service is unavailable
- network access is blocked on the login/compute node
- requested time period is outside available forcing data
- forcing output directory does not match `general.resource_layout`

Check the per-step terminal output and verify the expected forcing directory
from [directory_layout.md](./directory_layout.md).

## Smoke Test Expectations

Run the smoke test from the active Sandbox environment:

```bash
python test/sandbox_test.py --all --gpkg <path/to/conus_nextgen.gpkg>
```

Expected final message:

```text
SUCCESS: NextGenSandbox smoke test completed. Installation and the core workflow are ready.
```

If this fails, run the individual steps to isolate the problem:

```bash
python test/sandbox_test.py --subset --gpkg <path/to/conus_nextgen.gpkg>
python test/sandbox_test.py --forc   --gpkg <path/to/conus_nextgen.gpkg>
python test/sandbox_test.py --conf   --gpkg <path/to/conus_nextgen.gpkg>
python test/sandbox_test.py --run    --gpkg <path/to/conus_nextgen.gpkg>
```

## Dry Run

After `sandbox --conf` has generated run files, use dry-run mode to validate
the execution setup without launching ngen or ngen-cal:

```bash
sandbox --dryrun -i configs/my_sandbox_config.yaml
```

`--dryrun` is standalone. Do not combine it with `--run`.
