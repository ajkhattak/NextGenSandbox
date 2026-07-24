# Run a NextGenSandbox Project

This guide begins after NextGenSandbox is installed and the smoke test in
[install.md](./install.md) has passed. It walks through one project from
resource preparation to model execution, then introduces parallel resource
preparation and Sandbox Launcher.

Configuration field definitions are intentionally kept in
[configuration.md](./configuration.md). Resource path structures are documented
in [directory_layout.md](./directory_layout.md).

## Before Starting

From the NextGenSandbox repository, activate the Sandbox Python environment:

```bash
conda activate "$SANDBOX_ENV"
```

or:

```bash
source "$SANDBOX_ENV/bin/activate"
```

Confirm that the installation is ready:

```bash
./bootstrap.sh --check
```

The `sandbox` command, ngen executable, required model libraries, t-route, and
the resource preparation environments should be available before continuing.

## Workflow Overview

Resource preparation commands are optional when suitable files already exist.
Configuration generation and model execution are separate so generated files
can be inspected before a run.

| Stage | Command | When to run it |
|---|---|---|
| Prepare hydrofabric | `sandbox --subset` | Run when gage-specific geopackages do not already exist. |
| Prepare forcing | `sandbox --forc` | Run when forcing must be downloaded, prepared, or rechunked by Sandbox. |
| Generate model files | `sandbox --conf` | Run after hydrofabric and forcing resources are available. |
| Inspect execution | `sandbox --dryrun` | Recommended after configuration generation and before a real run. |
| Execute models | `sandbox --run` | Run after generated configurations have been reviewed. |

All commands use the same project `sandbox_config.yaml`. Calibration and
validation commands may also use a project-specific `calib_config.yaml`.

## Step 1: Create Project Configuration

Start from the distributed samples:

```bash
cp configs/sandbox_config.yaml configs/my_project.yaml
cp configs/calib_config.yaml configs/my_project_calibration.yaml
```

The calibration copy is needed only when you want project-specific changes to
the search strategy, objective, plugins, or parameter-file location.

Review the following project decisions in `my_project.yaml`:

1. Choose reusable resource and generated output directories.
2. Choose one resource layout for the project.
3. Define the complete project gage set.
4. Configure the hydrofabric source or existing geopackages.
5. Configure the forcing period and source.
6. Select the formulation and any custom model instances.
7. Select the simulation task, time periods, outputs, and partitioning.
8. Add local observations only when the run uses them.

Use [configuration.md](./configuration.md) as the field reference. For
calibration or validation, also review [calibration.md](./calibration.md) and
the relevant files under `configs/calibration/`.

## Step 2: Prepare Reusable Resources

### Prepare the hydrofabric

Each selected gage needs a geopackage before configuration generation.

If gage-specific geopackages do not exist, download the source hydrofabric for
your domain. CONUS hydrofabric files are available from
[Lynker Spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F).
Set `subsetting.hydrofabric.gpkg_path`, then run:

```bash
sandbox --subset -i configs/my_project.yaml
```

Expected result:

```text
NextGenSandbox subset step completed successfully.
```

One `gage_<gage_id>.gpkg` should be present for each selected gage under the
configured resource layout.

If the gage-specific geopackages already exist, use
`general.gages.option: gpkg` or place the files under the configured resource
layout. Skip `sandbox --subset`.

See [configuration.md](./configuration.md#subsetting) for settings and
[directory_layout.md](./directory_layout.md) for expected paths.

### Prepare forcing

If Sandbox should download or prepare forcing for the selected gages, run:

```bash
sandbox --forc -i configs/my_project.yaml
```

Expected result:

```text
NextGenSandbox forcing step completed successfully.
```

If forcing files already exist outside the project resource directory, set
`forcings.forcing_dir` to the file, directory, or `<gage_id>` path pattern and
skip the download step.

See [forcing.md](./forcing.md) for external forcing, multi-gage path patterns,
and NetCDF rechunking.

## Step 3: Generate Model Configuration

For a control simulation:

```bash
sandbox --conf -i configs/my_project.yaml
```

For calibration or validation with a project-specific calibration file:

```bash
sandbox --conf \
  -i configs/my_project.yaml \
  -j configs/my_project_calibration.yaml
```

Expected result:

```text
NextGenSandbox configuration step completed successfully.
```

Generated files are written under each selected gage's output directory. The
`configs/` directory includes the realization, routing configuration, model
configuration files, and ngen-cal configuration when required.

Inspect these files before execution, especially after changing a model
basefile, model instance, objective function, or simulation period.

## Step 4: Inspect the Run Command

Dry run initializes the run context and prints the ngen or ngen-cal command
without executing it:

```bash
sandbox --dryrun -i configs/my_project.yaml
```

For a project-specific calibration configuration:

```bash
sandbox --dryrun \
  -i configs/my_project.yaml \
  -j configs/my_project_calibration.yaml
```

`--dryrun` is a standalone mode. Do not combine it with `--run`, `--conf`,
`--subset`, or `--forc`.

Use the output to verify:

- selected gage and geopackage
- forcing path
- generated realization
- partition file and process count
- ngen or ngen-cal executable
- working and output directories

## Step 5: Run the Simulation

For a control simulation:

```bash
sandbox --run -i configs/my_project.yaml
```

For calibration or validation with a project-specific calibration file:

```bash
sandbox --run \
  -i configs/my_project.yaml \
  -j configs/my_project_calibration.yaml
```

Expected result:

```text
NextGenSandbox run step completed successfully.
```

For calibration and validation tasks, `run_index.yml` maps the configured
period names to their timestamped ngen-cal worker directories. Optional
`simulation_metadata.yml` records the gage, formulation, task, input path,
output path, and source configuration files.

See [directory_layout.md](./directory_layout.md) for the generated directory
structure and [calibration.md](./calibration.md) for calibration output
retention.

## Run One Gage

Use `--gage` to run one member of the configured project gage set without
editing the YAML file:

```bash
sandbox --conf --gage 01308000 -i configs/my_project.yaml
sandbox --run  --gage 01308000 -i configs/my_project.yaml
```

This is useful for diagnosing one failed gage before rerunning a larger
experiment. The supplied ID must belong to `general.gages`.

## Parallel Hydrofabric or Forcing Preparation

Subsetting and forcing preparation consist of independent serial commands per
gage. The batch helper runs several of those commands concurrently without
using Python multiprocessing inside Sandbox:

```bash
tools/batch/run_sandbox_resources_parallel.sh \
  --step forc \
  --config configs/my_project.yaml \
  --jobs 2
```

Use `--step subset` for hydrofabric preparation. The helper reads the project
gage set and the corresponding step filter directly from the YAML file.

On Slurm, `--jobs` controls concurrent gages and must not exceed
`SLURM_CPUS_PER_TASK` unless `--allow-oversubscribe` is explicitly supplied.
It may be set lower than the allocated CPUs to reduce memory, filesystem I/O,
or remote-data pressure. When more gages are selected than concurrent jobs,
the remaining gages wait and run in later batches.

The helper writes per-gage logs and these summary files under its log directory:

- `selected_gages.txt`
- `success_gages.txt`
- `failed_gages.txt`

The shell script contains an editable Slurm header. It can also be run directly
from a local Linux or macOS terminal.

## Scale with Sandbox Launcher

After one project configuration succeeds normally, use Sandbox Launcher to
apply configuration templates across many gages and formulations or to manage
long calibration jobs.

Launcher uses the same `sandbox_config.yaml` and `calib_config.yaml` concepts,
adds experiment assignments, creates per-gage/per-model run directories, and
runs locally or submits jobs through Slurm.

See the [Sandbox Launcher guide](../tools/launcher/README.md).

## When a Step Fails

Run the read-only installation check first:

```bash
./bootstrap.sh --check
```

Then see [diagnostics.md](./diagnostics.md) for environment, subsetting,
forcing, model-build, dry-run, and smoke-test issues. Failed subsetting work
also records a gage-specific error file under the configured resource root.
