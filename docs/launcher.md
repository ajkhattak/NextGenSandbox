# Sandbox Launcher

The Sandbox Launcher expands one reusable Sandbox configuration into many
gage, formulation, and calibration experiments. Use it after a normal
single-gage Sandbox run works and the required hydrofabric, forcing, and
observation resources are available.

The launcher can:

- run small campaigns locally;
- submit independent experiments to Slurm;
- generate a Sandbox config for every gage and experiment;
- resume incomplete DDS calibrations or warm-start PSO from its global best;
- run validation after calibration;
- expand a reference period into reference, wet, and dry calibrations; and
- report campaign status from run metadata.

## How Configuration Works

The launcher uses one self-contained YAML file. Its name and location are up
to the user; examples include `launcher_dds.yaml` and `launcher_pso.yaml`.
The file describes the campaign and contains the reusable Sandbox settings
copied into every generated run.

The main sections are:

| Section | Defines |
|---|---|
| `project` | Shared input and output locations, resource layout, and campaign gages. |
| `stages` | Explicitly selects calibration, validation, or both in that order. |
| `sandbox` | Forcing, observations, calibration, simulation time, partitioning, and output settings. |
| `experiments` | Formulations, optional model instances, and the gages selected for each experiment. |
| `local` and `slurm` | Backend concurrency, scheduling, and resource limits. |
| `regime_calibration` | Optional reference, wet, and dry calibration expansion. |

### Project Settings

Define the paths once under `project`:

```yaml
project:
  name: regime_dds
  input_dir: "/path/to/project/inputs"
  output_dir: "/path/to/project/outputs"
  resource_layout: gage
  gages:
    option: ids
    ids:
      - "02299950"
      - "08070500"
```

Paths may be absolute or relative. Relative paths are resolved from the
directory containing the launcher YAML, so a project-local configuration can
use `./inputs`, `./outputs`, and `./clusters/...` regardless of the directory
from which `sandbox-launcher` is invoked.

The launcher injects these values, plus the current gage, formulation, model
instances, and calibration scenario, into each generated Sandbox config.
They do not need placeholders under `sandbox`.

`project.name` is optional. When omitted, the launcher uses the configuration
filename without `.yaml` as the campaign name.

## Required Files

| File | Purpose |
|---|---|
| Project launcher YAML | Complete campaign and shared Sandbox configuration; always required. It may have any filename. |
| `models_gages_map.yaml` | Optional advanced mapping format; not needed for the recommended setup. |

The launcher program and its Slurm scripts remain managed by NextGenSandbox.
Users configure Slurm resources, modules, and environment variables in the
project launcher YAML instead of maintaining a separate submission script.

The repository layout separates those responsibilities:

```text
src/python/launcher/       installed launcher implementation
configs/launcher/          editable launcher YAML examples
docs/launcher.md           this user guide
```

## Before You Start

Confirm that:

1. NextGenSandbox is installed and `./bootstrap.sh --check` succeeds.
2. A normal `sandbox --conf` and `sandbox --run` succeeds for at least one of
   the intended gages and formulations.
3. Hydrofabric, forcing, observations, and any trained model data already
   exist. The launcher does not download or subset resources.
4. The installed `sandbox-launcher` command is available.
5. For Slurm, the `slurm.modules` list contains the modules required by the
   target HPC system.

Run `./bootstrap.sh --sandbox` again after updating NextGenSandbox so the
installed `sandbox-launcher` command matches the repository.

## Minimal Setup

This example runs one formulation over two gages using one calibration
window from one configuration file.

### 1. Configure the Campaign and Sandbox

Copy the example into the project and give it a descriptive name:

```bash
cp "$SANDBOX_DIR/configs/launcher/launcher_config.yaml" launcher_dds.yaml
```

Then edit `launcher_dds.yaml`:

```yaml
project:
  name: regime_dds
  input_dir: "/path/to/project/inputs"
  output_dir: "/path/to/project/outputs"
  resource_layout: gage
  gages:
    option: ids
    ids:
      - "02299950"
      - "08070500"

sandbox:
  forcings:
    format: ".nc"
    time:
      start: "2015-10-01"
      end: "2022-09-30 23:00:00"
    gages: all

  observations: {}

  calibration:
    optimizer:
      algorithm: dds
      iterations: 400
      random_seed: 444
    objective:
      function: kge

  simulation:
    time:
      calibration:
        start: "2015-10-01 00:00:00"
        spinup: "12 months"
        evaluation: "4 years"
      validations:
        - name: validation
          start: "2020-10-01 00:00:00"
          spinup: "12 months"
          evaluation: "1 year"
    partitioning:
      mode: parallel
      max_nexus_per_proc: 15
      max_procs: 3
    outputs:
      metadata:
        enabled: true
        index_dir: metadata
        file: simulation_metadata.yml

stages: [calibration, validation]

local:
  max_workers: 2
  startup_delay_seconds: 5

slurm:
  max_active_jobs: 10
  max_total_mpi_tasks: 64
  startup_delay_seconds: 5
  modules:
    - openmpi/4.1.6
    - netcdf-fortran/4.6.1
    - cmake/3.30.2
    - sqlite
    - udunits
  environment:
    OMP_NUM_THREADS: "1"
  calibration:
    time: "12:00:00"
    memory: "8G"
  validation:
    time: "12:00:00"
    memory: "64G"

experiments:
  pet_cfe_s:
    models: "PET, CFE, T-route"
    selection: all
```

This means: run the `pet_cfe_s` experiment for every gage listed under
`project.gages`, completing calibration and then validation.

The launcher requires an explicit stage selection:

```yaml
# Start or resume calibration, then stop.
stages: [calibration]

# Run validation from an already completed calibration.
stages: [validation]

# Start or resume calibration, then run validation.
stages: [calibration, validation]
```

Calibration selection includes restart behavior. An incomplete DDS run uses
its restart configuration. An incomplete PSO run starts a new swarm from the
saved global-best parameters. Validation-only execution fails with a clear
error when no completed calibration checkpoint is available.

The `local` block applies only to `--backend local`; the `slurm` block applies
only to `--backend slurm`. A local-only campaign may omit `slurm`. Local
settings default to two workers and a five-second startup delay when omitted.

Keep `simulation.outputs.metadata.enabled: true`. The launcher uses each
`metadata/run_<gage_id>.yml` file to detect progress, select restart behavior,
request MPI tasks, and find validation output.

### 2. Configure the Slurm Environment

Skip this step for local execution. Before using Slurm, replace the example
`slurm.modules` entries with the modules used when ngen and its model
libraries were built on the target HPC system. Put simple fixed environment
variables under `slurm.environment`. Environment values are exported as
literal values; shell expressions and arbitrary setup commands are not
evaluated.

The launcher generates one shared worker script under
`<project.output_dir>/launcher/<campaign>_worker.slurm`. All gage jobs in that
campaign reuse this script. Values such as `slurm.account` and
`slurm.partition`, together with the stage-specific `slurm.calibration` and
`slurm.validation` profiles, are passed to `sbatch` for each job. Both
profiles require explicit `time` and `memory` values.

### 3. Check the Campaign

Run the read-only preflight check:

```bash
sandbox-launcher check --config launcher_dds.yaml
```

Expected result:

- the resolved launcher configuration and inline Sandbox settings;
- input and output directories;
- gage and experiment counts;
- resolved gage count for each experiment;
- calibration scenarios and selected years;
- the resolved hydrofabric and forcing resource for every gage;
- observation file paths and required columns; and
- `Launcher configuration and required resources look valid.`

`check` does not generate configs, create output directories, run Sandbox, or
submit jobs. The same resource preflight runs automatically before `submit`,
`run`, and `dryrun`.

### 4. Preview the Work

Preview local execution:

```bash
sandbox-launcher dryrun --backend local --config launcher_dds.yaml
```

Preview Slurm submissions:

```bash
sandbox-launcher dryrun --backend slurm --config launcher_dds.yaml
```

Expected result: one `Would generate configs` and one `Would run locally` or
`Would submit` message for each resolved gage/experiment/scenario. `dryrun`
does not write files, create output directories, execute Sandbox, or submit
jobs. A Slurm preview starts from an empty launcher budget and does not query
the live queue.

### 5. Run the Campaign

For local execution:

```bash
sandbox-launcher run --backend local --config launcher_dds.yaml
```

Local mode runs at most `local.max_workers` experiments concurrently. Its
startup delay cycles across worker slots so each new group of local runs is
staggered without imposing progressively longer waits on a large campaign.
Each local worker continues through the experiment stages: it completes or
resumes calibration, reloads the resulting checkpoint, and then runs
validation. One launcher command therefore completes both stages when they
succeed.

For Slurm, submit the campaign from a login node:

```bash
sandbox-launcher submit --config launcher_dds.yaml
```

The command validates the configuration, creates
`<project.output_dir>/logs`, submits the coordinator with absolute paths, and
prints the resulting Slurm job ID. During each coordinator cycle, Slurm mode
generates missing configs and submits the generated worker script once per
admitted gage/experiment/scenario. It then submits a lightweight follow-up
coordinator with OR-separated `afterany` dependencies on the active worker
job IDs and exits. Slurm starts that follow-up when any admitted worker
terminates. The coordinator recognizes workers that remain running or pending,
fills the newly available campaign capacity, and schedules its next dependent
successor. Running or pending workers are not submitted again. Calibration,
restarts, and validation are separate Slurm submissions selected across
dependency-driven coordinator cycles.

Do not call `sbatch` directly for the normal workflow. The
`sandbox-launcher submit` command supplies the configuration, output log
paths, account, partition, and dependency settings needed by the coordinator.

### Multiple Campaign Configurations

Configuration filenames are unrestricted. Keep independent optimizer setups
in separate files and give each one a separate output directory:

```text
regime_calibration/
  launcher_dds.yaml
  launcher_pso.yaml
  outputs/
    dds/
    pso/
```

Submit them independently:

```bash
sandbox-launcher submit --config launcher_dds.yaml
sandbox-launcher submit --config launcher_pso.yaml
```

Separate output directories prevent calibration checkpoints, metadata, worker
directories, and logs from the two optimizers from being mixed.

### 6. Check Status

The default view prints a compact campaign summary:

```bash
sandbox-launcher status --summary --config launcher_dds.yaml
```

Omitting `--summary` produces the same compact view.

Example fields are total experiments, finished, running, queued, and
inactive/incomplete. An experiment is one resolved gage, formulation, and
calibration scenario; calibration restarts are not counted as additional
experiments.

Use the detailed view for one line per experiment:

```bash
sandbox-launcher status --detailed --config launcher_dds.yaml
```

The detailed view includes live scheduler state, calibration iteration and
objective progress, and validation status. `INACTIVE/INCOMPLETE` means that
the experiment is unfinished but has no running or pending Slurm worker. It
may be awaiting the next coordinator cycle or require investigation after a
worker failure. Status reads Slurm, existing metadata, and output files; it
does not start or submit work. If Slurm cannot be queried, unfinished
experiments are reported as `UNKNOWN` rather than guessed.

## Generated Layout

For a normal calibration campaign:

```text
<project.output_dir>/
  launcher/
    <campaign>_worker.slurm
  logs/
    <campaign>_launcher_<job_id>.out
    <campaign>_launcher_<job_id>.err
    <worker_job_name>_<job_id>.out
    <worker_job_name>_<job_id>.err
  <experiment>/
    configs/
      <gage_id>/
        sandbox_config_<gage_id>.yaml
        sandbox_config_<gage_id>_restart.yaml
        sandbox_config_<gage_id>_validation.yaml
    metadata/
      run_<gage_id>.yml
    <gage run output>/
```

For regime calibration, the scenario separates the generated files and run
outputs:

```text
<project.output_dir>/
  <experiment>/
    ref/
      configs/
      metadata/
    wet/
      configs/
      metadata/
    dry/
      configs/
      metadata/
```

## Multiple Experiments and Groups

Add experiments by name under `experiments`. Model variants belong with the
experiment that uses them. Every experiment must define `selection`:

```yaml
experiments:
  pet_cfe_s:
    models: "PET, CFE, T-route"
    selection: all

  pet_cfe_x:
    models: "PET, CFE, T-route"
    selection:
      groups:
        - snowy
        - benchmark
      ids:
        - "02299950"
    model_instances:
      CFE:
        - name: cfe-x
          basefile: "config_cfe-x.yaml"
          repo_name: "cfe"
          calib_params_block: cfex_params
```

`selection: all` uses every gage in `project.gages`. A selection mapping may
contain `groups`, `ids`, or both. When both are present, the launcher uses
their union and removes duplicates.

For grouped campaigns, load the project gages and group names from CSV:

```yaml
project:
  gages:
    option: file
    file:
      path: "/path/to/gages.csv"
      id_column: gage_id
      group_column: group_name

experiments:
  snow17_sacsma:
    models: "SNOW17, PET, SAC-SMA, T-route"
    selection:
      groups: [snowy]

  pet_topmodel:
    models: "PET, TopModel, T-route"
    selection:
      groups: [arid]
```

```csv
gage_id,group_name
01109403,snowy
01109403,benchmark
02299950,arid
08070500,non-snowy|benchmark
```

A gage may belong to multiple groups through repeated rows or comma-,
semicolon-, or pipe-separated group names. It receives every experiment whose
selection matches any of those groups.

The preflight check rejects unknown IDs or groups, an experiment matching no
gages, and project gages selected by no experiment. This keeps omitted work
from passing silently. To run an experiment everywhere, specify
`selection: all` explicitly.

## Regime Calibration

Regime calibration expands every selected gage/experiment pair into three
independent scenarios:

- `ref` evaluates all post-spinup values in the reference period;
- `wet` evaluates only selected wet years; and
- `dry` evaluates only selected dry years.

Add this block to `launcher_config.yaml`:

```yaml
regime_calibration:
  reference:
    start: "2013-10-01 00:00:00"
    end: "2024-09-30 23:00:00"
    spinup: "12 months"
    year_type: water_year

  source:
    file: "/path/to/clusters/<gage_id>_annual_signatures_clusters.csv"
    year_column: Water_Year
    regime_column: Regime

  selection:
    max_years: 5
    order: earliest
    regimes:
      wet: Wet
      dry: Dry
```

The CSV contains one row per year:

```csv
Water_Year,Regime
2015,Wet
2016,Wet
2017,Wet
2018,Dry
```

`<gage_id>` is replaced for each gage and is required in the source path for
a multi-gage campaign. Only complete post-spinup years inside the reference
window are eligible. The launcher selects up to `max_years` for each regime,
using all available matching years when fewer exist. A regime with no
eligible years is an error.

Wet and dry simulations begin one spinup period before the earliest selected
year and end after the latest selected year. Intermediate years are simulated
to keep the run continuous but do not contribute to the objective function.

## Local Resources

The launcher expands the campaign into run units. One run unit is one
gage/experiment/scenario combination. For example, ten gages assigned to two
experiments produce 20 run units; enabling reference, wet, and dry scenarios
expands that campaign to 60 run units.

| Setting | Meaning |
|---|---|
| `max_workers` | Maximum run units executed concurrently by the local backend. The effective value cannot exceed the machine's detected CPU count. |
| `startup_delay_seconds` | Delay interval distributed across local worker slots to stagger filesystem access. |

```yaml
local:
  max_workers: 2
  startup_delay_seconds: 5
```

With two workers and a five-second interval, queued runs receive delays in the
cycle `0, 5, 0, 5, ...`. This staggers each pair without making later runs
wait progressively longer.

## Slurm Resources

The launcher reads generated partition metadata and requests one MPI task per
resolved NextGen partition. Basin size may therefore produce a different task
count for every submitted job.

Each run unit is submitted as a separate worker job and requests one MPI task
per resolved NextGen partition. Launcher limits admit only a bounded set of
worker jobs, even when the cluster has enough resources to run the entire
campaign at once.

| Setting | Meaning |
|---|---|
| `max_active_jobs` | Required. Maximum number of this campaign's running plus pending worker jobs. |
| `max_total_mpi_tasks` | Required. Maximum aggregate MPI tasks requested by those jobs. Because workers use one CPU per task, this is also the campaign CPU budget. |
| `startup_delay_seconds` | Delay interval assigned across jobs admitted in one launcher cycle: `0`, one interval, two intervals, and so on. |
| `account` | Optional worker-job Slurm account override. |
| `partition` | Optional worker-job Slurm partition override. |
| `mpi_tasks` | Must be `auto` when present. Per-run tasks come from generated partition metadata. |
| `modules` | Module names loaded in order by the generated worker script. Use an empty list when modules are not needed. |
| `environment` | Optional fixed environment variables exported by the generated worker script. |
| `calibration.time` | Required calibration/restart worker wallclock. |
| `calibration.memory` | Required calibration/restart worker memory. |
| `validation.time` | Required validation worker wallclock. |
| `validation.memory` | Required validation worker memory. |

Configure worker resources and runtime dependencies together:

```yaml
slurm:
  max_active_jobs: 10
  max_total_mpi_tasks: 64
  startup_delay_seconds: 5
  account: project_account
  partition: shared
  mpi_tasks: auto
  modules:
    - openmpi/4.1.6
    - netcdf-fortran/4.6.1
    - cmake/3.30.2
    - sqlite
    - udunits
  environment:
    OMP_NUM_THREADS: "1"
  calibration:
    time: "06:00:00"
    memory: "8G"
  validation:
    time: "12:00:00"
    memory: "64G"
```

With these limits, no more than ten worker jobs and no more than 64 aggregate
MPI tasks can be running or pending from this campaign. Work that does not fit
is deferred until the next dependency-driven coordinator cycle. A single run
requiring more than `max_total_mpi_tasks` is rejected with an actionable error.

`startup_delay_seconds` staggers the jobs admitted during one launcher cycle.
For example, a five-second interval assigns delays of 0, 5, 10, and 15 seconds
to the first four submitted jobs. The delay occurs in the generated worker
script immediately before Sandbox starts.

`mpi_tasks` currently accepts only `auto`; CPUs per MPI task remain `1`.
Site-specific modules and fixed environment values belong in the `slurm`
block of the launcher configuration.
Restart and PSO warm-start jobs use the calibration profile. Before a
validation worker starts NextGen, it generates the validation-specific model
configs and configuration manifest from the completed calibration state.

## Advanced Direct Mapping

`models_gages_map.yaml` can provide an already-resolved `formulations` and
`mapping` structure. The launcher uses it only when `launcher_config.yaml`
does not contain an `experiments` block.

The launcher config is still required in direct-mapping mode because it
contains project paths, shared Sandbox settings, backend controls, and the
mapping-file location.
