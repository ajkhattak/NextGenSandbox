# Diagnostics And Common Issues

This page collects common setup and workflow issues without crowding the main
installation guide. Start with:

```bash
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
source "$SANDBOX_ENV/bin/activate"
```

or, if using conda:

```bash
conda activate "$SANDBOX_ENV"
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

## Subset Build Cannot Find Conda Or Hits Home Quota

Symptoms from `./bootstrap.sh --subset`:

```text
./utils/build_venv_subset.sh: line 9: conda: command not found
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

Symptoms when starting ngen may include:

```text
version `GLIBCXX_3.4.30' not found
version `CXXABI_1.3.15' not found
```

This means compiled Conda libraries require a newer C++ runtime than the one
selected from the HPC compiler modules. Current conda-forge Python and NumPy
builds cannot be solved against the older GCC 11 runtime. Sandbox therefore
keeps the compiler, MPI, NetCDF, and UDUNITS module paths and applies Conda's
newer, backward-compatible C++ runtime only to ngen and ngen-cal child
processes.

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
conda activate "$SANDBOX_ENV"
./bootstrap.sh --check
```

Do not globally override `PATH`, `LD_LIBRARY_PATH`, or `LD_PRELOAD` in a shell
startup file. Sandbox scopes the required runtime paths to processes it starts,
so unrelated HPC applications retain their module environment.

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

If the check says the existing ngen CMake compilers use a different compiler
family, rebuild the compiled components with
`./bootstrap.sh --ngen --models --troute --clean`. Preserve any `LIBRARY_PATH`
set by the loaded compiler and NetCDF modules because t-route uses it while
linking native extensions. Do not replace it with `LD_LIBRARY_PATH`.

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
common domain explicitly under `general.gages`, for example:

```yaml
general:
  gages:
    option: ids
    domain: conus
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
