# Sandbox Launcher

The Sandbox Launcher runs many gage/formulation experiments from one shared
set of base configuration files. It is intended for larger calibration and
validation campaigns where each gage/formulation run may need to resume across
multiple scheduler submissions.

The launcher supports:

- SLURM execution for HPC systems
- local multiprocessing for small tests
- per-gage/per-formulation config generation
- automatic calibration restart selection
- validation after calibration iterations are complete
- status checks across all configured experiments

## Files

| File | Purpose |
|---|---|
| `launcher_config.yaml` | Preferred one-window launcher setup: project paths, templates, experiments, gages, and assignments. |
| `models_gages_map.yaml` | Advanced/direct mapping format; optional when using `launcher_config.yaml` experiments and assignments. |
| `basefiles/sandbox_config_base.yaml` | Base Sandbox config copied and customized per gage/formulation. |
| `basefiles/calib_config_base.yaml` | Base calibration config copied per gage/formulation. |
| `sandbox_launcher.py` | Main launcher CLI. |
| `submit_launcher.sh` | Entry script for SLURM or local execution. |
| `submit_gage.slurm` | SLURM worker script for one gage/formulation run. |
| `check_status.sh` | Convenience wrapper for launcher status. |

## Setup

1. Copy or edit `launcher_config.yaml`.
2. Edit `basefiles/sandbox_config_base.yaml`.
3. Edit `basefiles/calib_config_base.yaml`.
4. Define experiments and assignments in `launcher_config.yaml`.
5. On SLURM systems, edit account, partition, time, memory, and module loads in
   `submit_launcher.sh` and `submit_gage.slurm`.

The base Sandbox config must use the current major-release schema:

```yaml
general:
  input_dir: "/path/to/reusable/resources"
  output_dir: "/path/to/run/outputs"
  resource_layout: gage
  gages:
    option: ids
    ids: []

forcings:
  gages: all

simulation:
  gages: []
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
  outputs:
    metadata:
      enabled: true
      index_dir: metadata
      run_file: run_metadata.yml
```

The launcher fills `general.gages.ids`, `simulation.gages`,
`general.output_dir`, `formulation.models`, and optional
`formulation.model_instances` for each generated config.
The `simulation.outputs.metadata` block is required because the launcher uses
`<output_dir>/<formulation>/metadata/run_<gage_id>.yml` for status checks and
resubmission after wallclock timeouts.

## One-Window Launcher Config

The preferred setup is to define experiments, gages, and assignments in
`launcher_config.yaml`:

```yaml
project:
  input_dir: "/path/to/inputs"
  output_dir: "/path/to/outputs"
  resource_layout: gage

templates:
  sandbox_config: basefiles/sandbox_config_base.yaml
  calib_config: basefiles/calib_config_base.yaml

experiments:
  pet_cfe_x:
    models: "PET, CFE, T-route"
    model_instances:
      CFE:
        - name: cfe-x
          basefile: "config_cfe-x.yaml"
          repo_name: "cfe"
          calib_params_block: "cfex_params"

gages:
  option: file
  file:
    path: "/path/to/gages.csv"
    id_column: gage_id
    group_column: group_name

assignment:
  default:
    - all

  groups:
    snowy:
      - snow17_sacsma
      - nom_cfe_s

    arid:
      - pet_topmodel
```

`assignment.default: [all]` means run every experiment over every gage.
Otherwise, list specific experiment names.

When `gages.file.group_column` is configured, group-specific assignments can
override the default. A gage may belong to more than one group either by
appearing in multiple CSV rows or by using comma, semicolon, or pipe-separated
group names in one cell.

```csv
gage_id,group_name
01109403,snowy
01109403,benchmark
02299950,arid
08070500,non-snowy|benchmark
```

If a gage belongs to multiple configured groups, the launcher merges the
experiment lists and removes duplicates while preserving order. If a gage's
group is not configured under `assignment.groups`, the gage falls back to
`assignment.default`.

## Direct Mapping Format

For advanced use, `models_gages_map.yaml` can still define a fully resolved
mapping. The launcher uses this file only when `launcher_config.yaml` does not
define `experiments`, `gages`, and `assignment`.

## Check

Run a read-only configuration check before submitting jobs:

```bash
python tools/launcher/sandbox_launcher.py check --config tools/launcher/launcher_config.yaml
```

or, from a copied launcher directory:

```bash
python sandbox_launcher.py check --config launcher_config.yaml
```

## Dry Run

Preview planned work without writing configs or submitting jobs:

```bash
python tools/launcher/sandbox_launcher.py run --backend local --dryrun
```

## Run

Local mode:

```bash
bash tools/launcher/submit_launcher.sh
```

SLURM mode:

```bash
sbatch tools/launcher/submit_launcher.sh
```

The entry script detects whether it is running inside SLURM and selects the
backend automatically.

## Status

```bash
bash tools/launcher/check_status.sh
```

or:

```bash
python tools/launcher/sandbox_launcher.py status --config tools/launcher/launcher_config.yaml
```

## Notes

- The launcher assumes hydrofabric and forcing resources already exist.
- `SANDBOX_ENV` must point to the Sandbox Python environment.
- Generated configs are written under `<output_dir>/<formulation_name>/configs`.
- Status uses each run's `metadata/run_<gage_id>.yml`, `best_params.txt`, and
  validation files under `output_sim_obs`.
