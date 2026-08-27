# Sandbox Launcher

Sandbox Launcher expands one project configuration into independent Sandbox
runs across many gages, formulations, and optional calibration scenarios. Use
it after a normal single-gage `sandbox --conf` and `sandbox --run` succeeds.
It prepares per-gage configuration files, resumes incomplete calibrations,
submits Slurm jobs when requested, and reports campaign progress. It does not
subset hydrofabric or download forcing data.

## Start With a Sandbox Configuration

A launcher configuration uses the same normal Sandbox blocks and adds only a
`launcher` block. Its shared blocks use exactly the same schema and meanings
described in [Configure NextGenSandbox](configuration.md):

```text
general, subsetting, forcings, observations, calibration, simulation
```

Copy an existing Sandbox configuration or start from the shipped launcher
example:

```bash
cp "$SANDBOX_DIR/configs/launcher/launcher_config.yaml" launcher_dds.yaml
```

Keep `general.input_dir`, `general.output_dir`, forcing settings, observations,
calibration settings, and simulation time windows in this one file. There is
no second Sandbox configuration to maintain. Relative paths are resolved from
the launcher YAML's directory.

The launcher changes only these concepts:

| Normal Sandbox configuration | Launcher configuration |
| --- | --- |
| One named formulation defines one model setup. | Multiple named formulations define model setups and assign gages to each. |
| `simulation.tasks` selects work for one configuration. | The same `simulation.tasks` selection is distributed across the campaign. |
| One command runs one selected set of gages. | `launcher` controls local or Slurm campaign scheduling. |

The full ready-to-edit structure is in
[configs/launcher/launcher_config.yaml](https://github.com/ajkhattak/NextGenSandbox/blob/main/configs/launcher/launcher_config.yaml).

## Formulations

Each entry under `formulations` is a regular formulation definition plus a
required `selection`. Selection happens after `general.gages` establishes the
project gage set and `simulation.gages` optionally narrows it.

```yaml
formulations:
  nom_cfe_s:
    models: "NOM, CFE, T-ROUTE"
    verbosity: 0
    selection: all
    model_instances:
      CFE:
        - name: cfe-s
          basefile: "config_cfe-s.yaml"
          repo_name: cfe
          calib_params_block: cfes_params

  nom_cfe_x:
    models: "NOM, CFE, T-ROUTE"
    selection:
      groups: [snowy]
      ids: ["08070500"]
    model_instances:
      CFE:
        - name: cfe-x
          basefile: "config_cfe-x.yaml"
          repo_name: cfe
          calib_params_block: cfex_params
```

Use `selection: all` to assign every selected gage. A selection mapping can
use `ids`, CSV `groups`, or both. A gage may belong to multiple groups and may
therefore be assigned to multiple formulations. The launcher reports an error
if a selected gage has no formulation assignment.

When groups are needed, configure them in the shared `general.gages` block:

```yaml
general:
  gages:
    option: file
    file:
      path: "./gages.csv"
      column: gage_id
      group_column: group_name
```

Keep `model_instances` as a wrapper because it has the same form as a normal
Sandbox `formulations.<name>.model_instances` block and supports more than one
configured instance per model family.

## Tasks and Restart

Set launcher work explicitly with `simulation.tasks`:

```yaml
simulation:
  tasks: [calibration, validation]
```

Allowed choices are `[calibration]`, `[validation]`, and
`[calibration, validation]`. Restart is automatic: an incomplete DDS
calibration resumes from its checkpoint, while an incomplete PSO calibration
starts a new swarm from its saved global-best parameters. Validation-only work
requires a completed calibration state.

The launcher automatically enables `simulation.outputs.metadata`; add that
block only when a non-default metadata location is needed.

## Launcher Settings

The `launcher` block contains campaign-specific settings only.

```yaml
launcher:
  campaign_name: dds_example

  local:
    max_workers: 2
    startup_delay_seconds: 5

  slurm:
    account: project_account
    partition: shared
    max_active_jobs: 10
    max_total_mpi_tasks: 64
    max_total_allocated_cpus: 128
    startup_delay_seconds: 5
    coordinator:
      time: "00:10:00"
      memory: "2G"
    modules:
      - openmpi/4.1.6
      - netcdf-fortran/4.6.1
    environment:
      OMP_NUM_THREADS: "1"
    calibration:
      time: "12:00:00"
      memory: "8G"
    validation:
      time: "12:00:00"
      memory: "64G"
```

`local.max_workers` limits simultaneous local experiments. The Slurm limits
protect different resources:

| Setting | Limits |
| --- | --- |
| `max_active_jobs` | Launcher workers running or pending in Slurm. |
| `max_total_mpi_tasks` | Sum of requested MPI ranks (`--ntasks`). |
| `max_total_allocated_cpus` | Sum of Slurm CPUs requested by jobs. |

Set `modules` to the same HPC modules used to build `ngen` and model
libraries. `environment` sets literal environment values such as
`OMP_NUM_THREADS`; it does not run shell commands. Slurm can still leave a
submitted worker pending because of cluster priority, available nodes, memory,
or account limits.

## Regime Calibration

An optional `launcher.regime_calibration` block expands each assigned
formulation/gage into reference, wet, and dry calibration scenarios. Reference
uses every post-spinup year; wet and dry select regime years from the supplied
CSV and create the smallest simulation window that includes those years and
spinup.

```yaml
launcher:
  regime_calibration:
    execution:
      mode: priority
      order: [ref, wet, dry]
    reference:
      start: "2013-10-01 00:00:00"
      end: "2023-09-30 23:00:00"
      spinup: "12 months"
      year_type: water_year
    source:
      file: "./clusters/<gage_id>_annual_signatures_clusters.csv"
      year_column: Water_Year
      regime_column: Regime
    selection:
      max_years: 5
      order: earliest
      regimes:
        wet: Wet
        dry: Dry
```

`priority` admits scenarios in the listed order while still using remaining
campaign capacity when an earlier scenario cannot fit the configured limits.

## Run a Campaign

Check the configuration and resources first. This is read-only: it does not
create output directories, write generated configuration files, run models, or
submit jobs.

```bash
sandbox-launcher check --config launcher_dds.yaml
```

Preview resolved work without writing anything:

```bash
sandbox-launcher dryrun --backend local --config launcher_dds.yaml
sandbox-launcher dryrun --backend slurm --config launcher_dds.yaml
```

Run locally or submit from an HPC login node:

```bash
sandbox-launcher run --backend local --config launcher_dds.yaml
sandbox-launcher submit --config launcher_dds.yaml
```

The Slurm command creates a lightweight coordinator that admits workers within
the configured limits and schedules a successor after active workers finish.
Do not submit the generated worker scripts manually.

## Status and Output

Use the compact campaign report:

```bash
sandbox-launcher status --summary --config launcher_dds.yaml
```

Use one row per gage/formulation/scenario for diagnosis:

```bash
sandbox-launcher status --detailed --config launcher_dds.yaml
sandbox-launcher status --running --config launcher_dds.yaml
sandbox-launcher status --out-of-memory --config launcher_dds.yaml
```

The summary distinguishes `COMPLETED`, `RUNNING`, `QUEUED`,
`WILL_BE_REQUEUED`, `NOT_SUBMITTED`, `TIMEOUT`, `OUT_OF_MEMORY`, `FAILED`, and
`CANCELLED`. The detailed view also reports calibration iteration progress and
estimated remaining calibration time when enough progress is available.

Re-run `sandbox-launcher run` or `sandbox-launcher submit` with the same
configuration after a failure or wall-clock limit. Completed work is left
alone; incomplete calibrations use their available restart state.

Launcher artifacts are written below `general.output_dir`:

```text
<output_dir>/
  launcher/
    <campaign>_worker.slurm
    <campaign>_submitted_jobs.jsonl
  logs/
    <campaign>_launcher_<job_id>.out
    <worker_job_name>_<job_id>.out
  <formulation>/
    configs/
    metadata/
    <gage_id>_<formulation>/
```

Regime campaigns add `ref`, `wet`, and `dry` below each formulation before
their generated configurations, metadata, and model outputs.
