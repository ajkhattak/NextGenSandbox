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
sandbox --dryrun -i configs/my_sandbox_config.yaml -j configs/calib_config.yaml
```

`--dryrun` is standalone. Do not combine it with `--run`.
