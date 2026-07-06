# Project Workflow Guide

This guide starts after NextGenSandbox is installed and the smoke test in
[install.md](./install.md) has passed. It explains how to move from a working
installation to a custom project, first for one basin or a small set of basins,
then for larger launcher-managed experiments.

## Start With Configuration

Before running a custom project, review [configuration.md](./configuration.md).
That guide explains the main configuration files:

- `configs/sandbox_config.yaml`: workflow paths, hydrofabric subsetting,
  forcings, observations, formulation, model instances, and simulation settings.
- `configs/calib_config.yaml`: calibration strategy, objective functions,
  plugins, and calibration parameter files.
- `configs/calibration/*.yaml`: model-specific calibration parameter blocks.

For project directory choices, also review
[directory_layout.md](./directory_layout.md). It explains the supported
`general.resource_layout` values and how reusable resources differ from
generated run artifacts.

## Single-Basin Project

For a first custom project, start with one basin or a small set of gages. This
keeps debugging simple and confirms that the selected hydrofabric, forcing,
formulation, and calibration settings work before scaling up.

1. Copy or edit `configs/sandbox_config.yaml`.
2. Set `general.input_dir`, `general.output_dir`, and `general.resource_layout`.
3. Configure `general.gages` with the full project gage set.
4. Configure `subsetting` with the source hydrofabric and, if needed, a
   step-specific gage filter.
5. Configure `forcings` for the simulation period and forcing source.
6. Configure `formulation` and any `model_instances`.
7. Configure `simulation` for the task type, time periods, output settings,
   and partitioning.
8. For calibration runs, review `configs/calib_config.yaml` and the relevant
   files under `configs/calibration/`.

### Subset Hydrofabric

Before running `sandbox --subset`, download the source hydrofabric for the
domain of interest from
[lynker-spatial](https://www.lynker-spatial.com/data?path=hydrofabric%2Fv2.2%2F).
For example, for CONUS workflows, configure `subsetting.hydrofabric.gpkg_path`
to point to the downloaded `conus_nextgen.gpkg` or equivalent hydrofabric file.

`general.gages` defines the full project gage set. The `subsetting.gages`
field is an optional filter on that set, so a project can subset all configured
gages or just a smaller list for one run.

```yaml
general:
  gages:
    option: ids
    ids: ["01308000", "03366500"]

subsetting:
  hydrofabric:
    version: "2.2"
    gpkg_path: "/path/to/conus_nextgen.gpkg"
  gages: ["01308000"]
```

Step-level gage filters under `subsetting`, `forcings`, and `simulation` may be
`all`, one gage ID, or a list of IDs. CSV and geopackage selection should be
configured under `general.gages`.

Run:

```bash
sandbox --subset -i configs/my_sandbox_config.yaml
```

If subsetting succeeds, a basin geopackage is written for each selected gage.
With the default `general.resource_layout: gage`, geopackages are written under:

```text
<input_dir>/<gage_id>/hydrofabric/gage_<gage_id>.gpkg
```

With `general.resource_layout: resource`, geopackages are written under:

```text
<input_dir>/hydrofabric/gage_<gage_id>.gpkg
```

On systems where the R dependencies are managed outside the command line,
such as RStudio workflows, you can run the subsetting R entry point directly
after setting `infile_config` in `src/R/main.R`.

### Run The Workflow

Run the workflow one step at a time:

```bash
sandbox --subset -i configs/my_sandbox_config.yaml
sandbox --forc   -i configs/my_sandbox_config.yaml
sandbox --conf   -i configs/my_sandbox_config.yaml -j configs/calib_config.yaml
sandbox --run    -i configs/my_sandbox_config.yaml -j configs/calib_config.yaml
```

The step-by-step order makes failures easier to diagnose:

- `sandbox --subset` creates basin geopackages from a larger hydrofabric.
- `sandbox --forc` prepares forcing data for the selected gages and period.
- `sandbox --conf` generates model configuration and realization files.
- `sandbox --run` executes ngen or ngen-cal for the configured task.

Expected outputs:

| Step | Success Indicator |
| --- | --- |
| `sandbox --subset` | `NextGenSandbox subset step completed successfully.` and `gage_<gage_id>.gpkg` files under the configured resource layout. |
| `sandbox --forc` | `NextGenSandbox forcing step completed successfully.` and forcing NetCDF files under the configured forcing resource directory. |
| `sandbox --conf` | `NextGenSandbox configuration step completed successfully.` and generated files under `<output_dir>/<gage_id>*/configs/`. |
| `sandbox --run` | `NextGenSandbox run step completed successfully.` plus ngen/ngen-cal output files in the run directory. |

To check the generated run command without executing ngen or ngen-cal, use:

```bash
sandbox --dryrun -i configs/my_sandbox_config.yaml -j configs/calib_config.yaml
```

`sandbox --dryrun` validates the run setup and prints the command that would be
executed. It is a standalone workflow mode, so do not combine it with
`--run`, `--conf`, `--subset`, or `--forc`.

If a step fails, see [diagnostics.md](./diagnostics.md) for common setup and
workflow issues.

### Parallel Subset Or Forcing Batches

For subsetting and forcing preparation, you can run several independent serial
Sandbox commands in parallel without using Python multiprocessing. The batch
helper reads the selected gages directly from the Sandbox configuration. For
example, if `general.gages` lists three gages and `forcings.gages: all`, all
three forcing jobs are included. If `forcings.gages` lists only one or two of
them, only that subset is included.

For a local machine or macOS terminal, run the helper directly and choose a
small number of jobs:

```bash
tools/batch/run_sandbox_resources_parallel.sh \
  --step forc \
  --config configs/sandbox_config1.yaml \
  --jobs 2
```

For HPC, submit the same helper through Slurm. `--jobs` controls how many
gages run at the same time, not the total number of selected gages. The total
selected gage count can be larger than the CPU count because the helper runs
gages in batches. `--jobs` can be equal to `SLURM_CPUS_PER_TASK`, such as
`--jobs "$SLURM_CPUS_PER_TASK"`, or lower if memory, filesystem I/O, or remote
data access should be throttled. The helper rejects `--jobs` values larger
than `SLURM_CPUS_PER_TASK` unless `--allow-oversubscribe` is set, so it will
not run more simultaneous gages than allocated CPUs. The helper script contains
an editable Slurm header template.

The helper launches each basin with `sandbox --gage <gage_id>`. You can also
use `sandbox --gage` directly when debugging one basin without editing the
configuration file.

For subsetting, change `--step forc` to `--step subset`. The wrapper writes
per-gage logs plus `selected_gages.txt`, `success_gages.txt`, and
`failed_gages.txt` under the log directory.

## Scale With Sandbox Launcher

After one normal Sandbox configuration works, use the Sandbox Launcher to scale
the same workflow across many gages, formulations, or long calibration jobs.
The launcher builds on the same `sandbox_config.yaml` and `calib_config.yaml`
concepts, then creates per-gage/per-model run directories and submits jobs
through SLURM or local execution.

See the [Sandbox Launcher guide](../tools/launcher/README.md).
