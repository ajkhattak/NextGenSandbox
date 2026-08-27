# Sandbox Launcher

Sandbox Launcher expands one project configuration into independent Sandbox
runs across many gages, formulations, and optional calibration scenarios. Use
it after a normal single-gage `sandbox --conf` and `sandbox --run` succeeds.
The launcher prepares configuration files, resumes incomplete calibrations,
submits Slurm jobs when requested, and reports campaign progress. It does not
subset hydrofabric or download forcing data.

## One Configuration File

Launcher YAML uses the same top-level blocks as a normal Sandbox
configuration. This means an existing Sandbox configuration can be copied into
a launcher configuration and then extended with `formulations` and `launcher`.
There is no separate `project`, `sandbox`, `experiments`, or `stages` language.

| Block | Purpose |
| --- | --- |
| `general` | Project paths, resource layout, and the full gage universe. |
| `subsetting`, `forcings`, `observations`, `calibration` | Normal Sandbox settings copied into generated runs. |
| `formulations` | Named model formulations and their gage selections. |
| `simulation` | Campaign tasks, optional gage filter, time windows, and partitioning. |
| `launcher` | Local or Slurm scheduling and optional regime-calibration expansion. |

Copy the shipped example to a project directory and rename it as needed:

```bash
cp "$SANDBOX_DIR/configs/launcher/launcher_config.yaml" launcher_dds.yaml
```

Relative paths are resolved from the directory containing the launcher YAML.

## Minimal Campaign

```yaml
general:
  input_dir: "./inputs"
  output_dir: "./outputs/dds"
  resource_layout: gage
  gages:
    option: ids
    ids: ["02299950", "08070500"]

forcings:
  format: ".nc"
  use_corrected: true
  rechunk: true
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

simulation:
  tasks: [calibration, validation]
  gages: all
  time:
    calibration:
      start: "2015-10-01"
      spinup: "12 months"
      evaluation: "4 years"
    validations:
      - name: validation
        start: "2020-10-01"
        spinup: "12 months"
        evaluation: "1 year"
  partitioning:
    mode: parallel
    max_nexus_per_proc: 15
    max_procs: 5

launcher:
  campaign_name: dds_example
  local:
    max_workers: 2
    startup_delay_seconds: 5
```

`simulation.tasks` must be exactly one of:

```yaml
tasks: [calibration]
tasks: [validation]
tasks: [calibration, validation]
```

Restart is automatic, rather than a task to list. An incomplete DDS
calibration resumes from its checkpoint. An incomplete PSO calibration starts
a new swarm from its saved global-best parameters. Validation-only work
requires an available completed calibration state.

The launcher automatically enables `simulation.outputs.metadata`. Do not add
that block merely for the launcher unless a non-default metadata location is
needed.

## Gage and Formulation Selection

Selection happens in three clear steps:

1. `general.gages` defines every gage available to the campaign.
2. `simulation.gages` optionally narrows that set for this run.
3. Each `formulations.<name>.selection` assigns one or more remaining gages
   to that formulation.

Every selected gage must be assigned to at least one formulation. The launcher
errors rather than quietly omitting a gage.

Use `selection: all` for every campaign gage. For explicit gages or CSV
groups, use a selection mapping:

```yaml
general:
  gages:
    option: file
    file:
      path: "./gages.csv"
      column: gage_id
      group_column: group_name

simulation:
  gages: ["02299950", "08070500"]

formulations:
  nom_cfe_s:
    models: "NOM, CFE, T-ROUTE"
    selection:
      groups: [snowy]
      ids: ["08070500"]
```

`groups` and `ids` are combined. A gage may occur on several rows in the CSV
and therefore belong to several groups.

Each named entry under `formulations` is a normal formulation definition plus
the required `selection`. Keep `model_instances` as a wrapper: it is the same
shape used in normal Sandbox configuration files and supports multiple
instances for one model family.

## Check, Preview, and Run

Before submitting work, run the read-only check:

```bash
sandbox-launcher check --config launcher_dds.yaml
```

It validates the configuration, selected gages and formulations, hydrofabric,
forcing, observations, time windows, and launcher resources. It does not
create output directories, write generated configurations, run models, or
submit jobs.

Preview the resolved work without writing anything:

```bash
sandbox-launcher dryrun --backend local --config launcher_dds.yaml
sandbox-launcher dryrun --backend slurm --config launcher_dds.yaml
```

Run a small campaign locally:

```bash
sandbox-launcher run --backend local --config launcher_dds.yaml
```

`launcher.local.max_workers` limits simultaneous local experiments.
`launcher.local.startup_delay_seconds` staggers their starts.

Submit a Slurm campaign from a login node:

```bash
sandbox-launcher submit --config launcher_dds.yaml
```

The launcher writes its worker script, logs, generated configuration files,
and submission history below `general.output_dir`. It submits a lightweight
coordinator, which admits workers within the configured campaign limits and
schedules a successor after active workers finish. Do not submit generated
worker scripts manually.

## Slurm Settings

Add this to the `launcher` block when using Slurm:

```yaml
launcher:
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
```

Set `modules` to the same HPC modules used to build `ngen` and its model
libraries. `environment` is for literal environment values such as
`OMP_NUM_THREADS`; it does not run shell commands.

The three campaign limits protect different resources:

| Setting | Limits |
| --- | --- |
| `max_active_jobs` | Launcher workers running or pending in Slurm. |
| `max_total_mpi_tasks` | Sum of requested MPI ranks (`--ntasks`). |
| `max_total_allocated_cpus` | Sum of Slurm CPUs requested by jobs (`NumCPUs`). |

For standard Sandbox MPI execution each rank requests one CPU, so the last two
limits are often equal. Keep both because cluster configuration or a future
worker profile may allocate more CPUs than MPI tasks. Slurm can still leave a
submitted job pending because of its own priority, node, memory, and account
limits.

## Regime Calibration

An optional `launcher.regime_calibration` block expands every assigned
formulation/gage into reference, wet, and dry calibration scenarios. Reference
uses every post-spinup year; wet and dry select regime years from the supplied
CSV and create the smallest simulation window that includes the selected years
and spinup.

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
campaign capacity when an earlier scenario cannot fit its job limits.

## Status and Resume

Use the compact campaign report:

```bash
sandbox-launcher status --summary --config launcher_dds.yaml
```

Use one row per gage/formulation/scenario when diagnosing work:

```bash
sandbox-launcher status --detailed --config launcher_dds.yaml
```

Filter either view to one state:

```bash
sandbox-launcher status --running --config launcher_dds.yaml
sandbox-launcher status --out-of-memory --config launcher_dds.yaml
sandbox-launcher status --failed --config launcher_dds.yaml
sandbox-launcher status --cancelled --config launcher_dds.yaml
```

The summary distinguishes `COMPLETED`, `RUNNING`, `QUEUED`,
`WILL_BE_REQUEUED`, `NOT_SUBMITTED`, `TIMEOUT`, `OUT_OF_MEMORY`, `FAILED`, and
`CANCELLED`. The detailed view also reports calibration iteration progress and
estimated remaining calibration time when enough progress has been recorded.

Re-run `sandbox-launcher run` or `sandbox-launcher submit` with the same
configuration after a failure or wall-clock limit. Existing completed work is
left alone; incomplete calibrations use their available restart state.

## Generated Files

For one formulation and calibration scenario, launcher artifacts look like:

```text
<general.output_dir>/
  launcher/
    <campaign>_worker.slurm
    <campaign>_submitted_jobs.jsonl
  logs/
    <campaign>_launcher_<job_id>.out
    <worker_job_name>_<job_id>.out
  <formulation>/
    configs/
      <gage_id>/
        sandbox_config_<gage_id>.yaml
        sandbox_config_<gage_id>_restart.yaml
        sandbox_config_<gage_id>_validation.yaml
    metadata/
      run_<gage_id>.yml
    <gage_id>_<formulation>/
```

Regime scenarios add `ref`, `wet`, and `dry` below each formulation before
their `configs`, `metadata`, and model outputs.

## Migration From Earlier Launcher YAML

| Earlier block | New location |
| --- | --- |
| `project` | `general` |
| `sandbox.forcings`, `sandbox.observations`, `sandbox.calibration`, `sandbox.simulation` | Top-level Sandbox blocks |
| `experiments` | `formulations` |
| `stages` | `simulation.tasks` |
| `local`, `slurm`, `regime_calibration` | `launcher.local`, `launcher.slurm`, `launcher.regime_calibration` |

The older wrapper blocks are deliberately rejected, so a campaign cannot run
with an accidentally mixed configuration.
