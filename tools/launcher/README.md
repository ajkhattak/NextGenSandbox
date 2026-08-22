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

The launcher always needs **two configuration files**, including for one
gage, one formulation, and one calibration window:

| File | Defines |
|---|---|
| `launcher_config.yaml` | The campaign: project paths, gages, experiments, assignments, execution settings, and optional regime calibration. |
| `basefiles/sandbox_config_base.yaml` | The reusable Sandbox settings copied into every generated run: forcing, observations, optimizer, objective, simulation time, partitioning, and output settings. |

`launcher_config.yaml` points to the base file through
`templates.sandbox_config`. It does not replace the base Sandbox config, and
the base config cannot replace the launcher config.

### Where Project Paths Belong

Define the paths once in `launcher_config.yaml`:

```yaml
project:
  input_dir: "/path/to/project/inputs"
  output_dir: "/path/to/project/outputs"
  resource_layout: gage
```

You do **not** need to repeat `input_dir`, `output_dir`, or `resource_layout`
in `sandbox_config_base.yaml`. The launcher injects these values into every
generated Sandbox config. If they are present in both files, values under
`launcher_config.yaml: project` take precedence.

The launcher also injects the current gage, output directory, formulation,
model instances, and calibration scenario. These fields do not need empty
placeholders in the base file.

## Required Files

| File | Purpose |
|---|---|
| `launcher_config.yaml` | Main launcher configuration; always required. |
| `basefiles/sandbox_config_base.yaml` | Template for generated per-run Sandbox configs; always required. |
| `sandbox_launcher.py` | Launcher command-line program. |
| `submit_gage.slurm` | Slurm worker template used for each submitted run. |
| `submit_launcher.sh` | Optional wrapper that selects local or Slurm execution. |
| `check_status.sh` | Convenience wrapper for campaign status. |
| `models_gages_map.yaml` | Optional advanced mapping format; not needed for the recommended setup. |

## Before You Start

Confirm that:

1. NextGenSandbox is installed and `./bootstrap.sh --check` succeeds.
2. A normal `sandbox --conf` and `sandbox --run` succeeds for at least one of
   the intended gages and formulations.
3. Hydrofabric, forcing, observations, and any trained model data already
   exist. The launcher does not download or subset resources.
4. `SANDBOX_ENV` is available in the shell.
5. For Slurm, `submit_gage.slurm` contains the correct modules and site
   settings.

## Minimal Setup

This example runs one formulation over two gages using one calibration
window. Even this small case requires both launcher configuration files.

### 1. Configure the Campaign

Edit `tools/launcher/launcher_config.yaml`:

```yaml
project:
  input_dir: "/path/to/project/inputs"
  output_dir: "/path/to/project/outputs"
  resource_layout: gage

templates:
  sandbox_config: basefiles/sandbox_config_base.yaml

submit_script: submit_gage.slurm

execution:
  num_workers: 2
  startup_delay_seconds: 5

experiments:
  pet_cfe_s:
    models: "PET, CFE, T-route"

gages:
  option: ids
  ids:
    - "02299950"
    - "08070500"

assignment:
  default:
    - pet_cfe_s
```

This means: run the `pet_cfe_s` experiment for both listed gages. Use
`assignment.default: [all]` to assign every experiment to every gage.

### 2. Configure the Sandbox Template

Edit the file selected by `templates.sandbox_config`. The launcher supplies
the project paths, gages, and formulation, so this file begins with settings
that are shared by every generated run:

```yaml
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
```

Keep `simulation.outputs.metadata.enabled: true`. The launcher uses each
`metadata/run_<gage_id>.yml` file to detect progress, select restart behavior,
request MPI tasks, and find validation output.

### 3. Check the Campaign

Run the read-only preflight check:

```bash
python tools/launcher/sandbox_launcher.py check \
  --config tools/launcher/launcher_config.yaml
```

Expected result:

- resolved launcher and Sandbox template paths;
- input and output directories;
- gage and experiment counts;
- assignment summary;
- calibration scenarios and selected years; and
- `Launcher configuration looks valid.`

`check` does not generate configs, create output directories, run Sandbox, or
submit jobs.

### 4. Preview the Work

Preview local execution:

```bash
python tools/launcher/sandbox_launcher.py dryrun \
  --backend local \
  --config tools/launcher/launcher_config.yaml
```

Preview Slurm submissions:

```bash
python tools/launcher/sandbox_launcher.py dryrun \
  --backend slurm \
  --config tools/launcher/launcher_config.yaml
```

Expected result: one `Would generate configs` and one `Would run locally` or
`Would submit` message for each resolved gage/experiment/scenario. `dryrun`
does not write files, create output directories, execute Sandbox, or submit
jobs.

### 5. Run the Campaign

For local execution:

```bash
python tools/launcher/sandbox_launcher.py run \
  --backend local \
  --config tools/launcher/launcher_config.yaml
```

For Slurm execution from a login node:

```bash
python tools/launcher/sandbox_launcher.py run \
  --backend slurm \
  --config tools/launcher/launcher_config.yaml
```

Local mode runs at most `execution.num_workers` experiments concurrently.
Slurm mode generates each run config and submits `submit_gage.slurm` once per
gage/experiment/scenario. Configure the Slurm worker before using this mode.

The optional entry script selects the backend automatically:

```bash
# Local
bash tools/launcher/submit_launcher.sh

# Slurm launcher job
sbatch tools/launcher/submit_launcher.sh
```

Set `LAUNCHER_CONFIG` when the launcher config is not the default file:

```bash
LAUNCHER_CONFIG=/path/to/launcher_config.yaml \
  bash tools/launcher/submit_launcher.sh
```

### 6. Check Status

```bash
python tools/launcher/sandbox_launcher.py status \
  --config tools/launcher/launcher_config.yaml
```

or:

```bash
bash tools/launcher/check_status.sh
```

Status reports calibration progress and whether validation output exists for
each resolved run. It reads existing metadata and output files; it does not
start work.

## Generated Layout

For a normal calibration campaign:

```text
<project.output_dir>/
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
experiment that uses them:

```yaml
experiments:
  pet_cfe_s:
    models: "PET, CFE, T-route"

  pet_cfe_x:
    models: "PET, CFE, T-route"
    model_instances:
      CFE:
        - name: cfe-x
          basefile: "config_cfe-x.yaml"
          repo_name: "cfe"
          calib_params_block: cfex_params
```

For grouped campaigns, load gages and group names from CSV:

```yaml
gages:
  option: file
  file:
    path: "/path/to/gages.csv"
    id_column: gage_id
    group_column: group_name

assignment:
  default:
    - pet_cfe_s
  groups:
    snowy:
      - snow17_sacsma
    arid:
      - pet_topmodel
```

```csv
gage_id,group_name
01109403,snowy
01109403,benchmark
02299950,arid
08070500,non-snowy|benchmark
```

A gage may belong to multiple groups through repeated rows or comma-,
semicolon-, or pipe-separated group names. The launcher merges matching
experiment assignments and removes duplicates. If none of a gage's groups
appear under `assignment.groups`, `assignment.default` is used.

## Regime Calibration

Regime calibration expands every assigned gage/experiment pair into three
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

## Slurm Resources

The launcher reads generated partition metadata and requests one MPI task per
resolved NextGen partition. Basin size may therefore produce a different task
count for every submitted job.

Optional settings in `launcher_config.yaml` override matching defaults in
`submit_gage.slurm`:

```yaml
slurm:
  account: project_account
  partition: shared
  time: "12:00:00"
  memory: "8G"
  mpi_tasks: auto
```

`mpi_tasks` currently accepts only `auto`; CPUs per MPI task remain `1`.
Site-specific module commands still belong in `submit_gage.slurm`.

## Advanced Direct Mapping

`models_gages_map.yaml` can provide an already-resolved `formulations` and
`mapping` structure. The launcher uses it only when `launcher_config.yaml`
does not contain all three recommended blocks: `experiments`, `gages`, and
`assignment`.

The launcher config is still required in direct-mapping mode because it
selects project paths, the base Sandbox template, execution settings, and the
mapping file.
