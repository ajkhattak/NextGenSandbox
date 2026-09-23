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

A launcher configuration with one named formulation can be used directly with
`sandbox`; the launcher-only `selection` field is ignored. Multiple named
formulations require `sandbox-launcher`.

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

`general.gages.file.column` is the gage ID column for both `sandbox` and
`sandbox-launcher`; launcher configurations use the normal Sandbox schema.
`group_column` is optional and is used only for launcher assignments.

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

For a DDS restart, the launcher estimates walltime from completed iterations,
adds a 50% margin and a 10-minute startup buffer, and requests at least 15
minutes without exceeding `slurm.calibration.time`. If timing history is not
available, it uses the configured calibration walltime. Validation remains a
separate job and uses `slurm.validation.time` and memory.

The launcher automatically enables `simulation.outputs.metadata`; add that
block only when a non-default metadata location is needed.

Other `simulation.outputs` settings are shared with normal Sandbox projects.
For example, set
`simulation.outputs.per_formulation_nexus_files: true` to replace per-nexus
CSV output with one NetCDF file per formulation. Sandbox also configures
t-route to read that file. The selected ngen build must support NetCDF.

## Launcher Settings

The `launcher` block contains campaign-specific settings only.

```yaml
launcher:
  campaign_name: dds_example

  # Optional override for the currently loaded SANDBOX_PROFILE.
  environment_script: "./sandbox_profile.sh"

  local:
    max_workers: 2
    startup_delay_seconds: 5

  slurm:
    account: project_account
    partition: shared
    max_active_jobs: 10
    max_total_mpi_tasks: 64
    max_total_allocated_cpus: 128
    max_failed_attempts: 2
    startup_delay_seconds: 5
    coordinator:
      mode: persistent
      poll_interval_seconds: 300
      renew_before_seconds: 600
      time: "1-00:00:00"
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
| `max_failed_attempts` | Hard failures allowed after the last successful worker before automatic retries stop. Defaults to `2`; timeouts and preemptions do not count. |

Source the installation profile before invoking `sandbox-launcher`:

```bash
source /path/to/NextGenSandbox/sandbox_profile.sh
```

The launcher reuses the loaded `SANDBOX_PROFILE` automatically for local
Sandbox child commands,
the Slurm coordinator, and every Slurm worker. Set
`launcher.environment_script` only to override it; relative paths are resolved
from the launcher YAML.

This keeps the interactive session and every launcher process on the same
compiler/MPI stack and build directory. Do not also configure
`launcher.slurm.modules`; the launcher rejects that ambiguity.
`slurm.environment` remains available for literal values such as
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

The Slurm command creates a persistent, lightweight coordinator. It polls the
campaign every `poll_interval_seconds`, admits workers within the configured
limits, and fills capacity as workers finish. The coordinator does not run
ngen. It holds one CPU while active and relies on the partition's default
memory allocation unless optional `coordinator.memory` is provided.

Before its wallclock expires, the coordinator submits one successor dependent
on itself. This moves dependency scheduling from every worker wave to an
infrequent coordinator renewal. A campaign lock prevents overlapping
coordinators from submitting duplicate work. Do not submit generated worker
scripts manually.

Coordinator health is written atomically to:

```text
<output_dir>/launcher/<campaign_name>_coordinator_state.yaml
```

`sandbox-launcher status` reports its last heartbeat and next poll time. If a
campaign is intentionally stopped, cancel the coordinator before cancelling
workers so it cannot refill the released capacity.

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

To forget previous Slurm failures, cancellations, and retry counts before
submitting incomplete work again, reset the campaign history:

```bash
sandbox-launcher submit --reset --config launcher_dds.yaml
```

Reset refuses to run while a worker or coordinator for the campaign is active.
It archives the submission history and coordinator heartbeat below
`<output_dir>/launcher/archive/`, but preserves logs, generated configurations,
checkpoints, and model outputs. Completed experiments therefore remain
complete, while failed or cancelled experiments become eligible for another
submission.

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
    <gage_id>/
```

Regime campaigns add `ref`, `wet`, and `dry` below each formulation before
their generated configurations, metadata, and model outputs. The launcher does
not automatically append the formulation name to each gage directory. When an
explicit `simulation.label` is provided, it is appended instead; for example,
`label: dds` produces `<gage_id>_dds`. An omitted or empty label produces only
`<gage_id>`.
