# Configuration Guide

This guide explains how to configure NextGenSandboxHub runs. The workflow uses two main configuration files:

- `configs/sandbox_config.yaml`: workflow, inputs, formulation, model instances, and simulation settings.
- `configs/calib_config.yaml`: calibration strategy, parameter bounds, objectives, and plugins.

## Command Requirements

Different commands use different parts of `sandbox_config.yaml`.

| Command | Required config blocks |
|---|---|
| `sandbox --subset -i <config>` | `general`, `subsetting` |
| `sandbox --forc -i <config>` | `general`, `forcings` |
| `sandbox --conf -i <config> -j <calib_config>` | `general`, `forcings`, `formulation`, `simulation` |
| `sandbox --run -i <config> -j <calib_config>` | `general`, `forcings`, `formulation`, `simulation` |

## Core Blocks

### `general`

Defines where input data are read and outputs are written.

```yaml
general:
  input_dir: "<path_to_input_directory>"
  output_dir: "<path_to_output_directory>"
```

### `subsetting`

Controls hydrofabric subsetting, DEM processing, vegetation processing, and selected gages. This block is used by `sandbox --subset`.

### `forcings`

Controls forcing time range, format, domain, and optional forcing directory.

```yaml
forcings:
  format: ".nc"
  time:
    start_time: "2016-10-01 00:00:00"
    end_time: "2020-09-30 23:00:00"
  domain: "conus"
```

Simulation time windows must fall within the forcing time range.

## Formulations

The `formulation.models` value lists the model components used by a run.

```yaml
formulation:
  models: "NOM,CFE,T-ROUTE"
```

Run this command to list supported formulations:

```bash
sandbox --formulations
```

`T-ROUTE` may be omitted from a supported formulation; the workflow appends it automatically. All other model components must match a registered formulation exactly.

## Model Instances

`models` selects model components. `model_instances` customizes the configured instance used for a component.

For example, use `CFE` in `models`, then select the CFE-X (CFE with Xinanjiang scheme) instance through `model_instances`:

```yaml
formulation:
  models: "NOM,CFE,T-ROUTE"

  model_instances:
    CFE:
      - name: cfe-x
        basefile: "config_cfe-x.yaml"
        repo_name: "cfe"
        calib_params_block: "cfex_params"
```

Do not put `CFE-S` or `CFE-X` in `models`. `CFE` defaults to the `cfe-s`/Schaake instance. Use `model_instances.CFE` to select another configured instance such as `cfe-x`.

### Model Instance Fields

| Field | Meaning |
|---|---|
| `name` | Instance name and config subdirectory name, for example `cfe-x`. |
| `basefile` | Base configuration template under `configs/basefiles`. |
| `repo_name` | Model repository name under `$NGEN_DIR/extern`. |
| `calib_params_block` | Calibration parameter block name in `calib_config.yaml`. |
| `ngen_cal_model_name` | Optional model name expected by `ngen-cal` if different from the sandbox model key. |
| `library_file` | Optional full path to a model shared library. If omitted, the workflow searches under `$NGEN_DIR/extern/<repo_name>`. |

The parent key, such as `CFE`, is the sandbox model component. The `name` field is the configured instance of that component.

## Simulation Task Types

The `simulation.task_type` controls which time blocks are required.

| `task_type` | Required time/config fields |
|---|---|
| `control` | `simulation_time` |
| `calibration` | `calibration_time`, `calib_eval_time` |
| `validation` | `validation_time`, `valid_eval_time` |
| `calibvalid` | `calibration_time`, `calib_eval_time`, `validation_time`, `valid_eval_time` |
| `restart` | `calibration_time`, `calib_eval_time`, `restart_dir` |

Example:

```yaml
simulation:
  task_type: "calibvalid"
  gage_ids_input: "03366500"
  sim_name_suffix: "basecase"

  calibration_time:
    start_time: "2015-10-01 00:00:00"
    end_time: "2020-09-30 23:00:00"
  calib_eval_time:
    start_time: "2016-10-01 00:00:00"
    end_time: "2020-09-30 23:00:00"
  validation_time:
    start_time: "2020-10-01 00:00:00"
    end_time: "2022-09-30 23:00:00"
  valid_eval_time:
    start_time: "2021-10-01 00:00:00"
    end_time: "2022-09-30 23:00:00"
```

## Calibration Config Linkage

`calib_params_block` must match a block in `configs/calib_config.yaml`.

For example:

```yaml
formulation:
  model_instances:
    CFE:
      - name: cfe-x
        calib_params_block: "cfex_params"
```

must correspond to:

```yaml
cfex_params:
  - name: b
    min: 0.0
    max: 15
    init: 4.05
```

If a model has no calibratable parameters for a workflow, leave `calib_params_block` empty in its model instance.

## Examples

### PET + Default CFE

```yaml
formulation:
  models: "PET,CFE,T-ROUTE"
```

### NOM + CFE-X

```yaml
formulation:
  models: "NOM,CFE,T-ROUTE"
  model_instances:
    CFE:
      - name: cfe-x
        basefile: "config_cfe-x.yaml"
        repo_name: "cfe"
        calib_params_block: "cfex_params"
```

### SNOW17 + PET + SACSMA

```yaml
formulation:
  models: "SNOW17,PET,SACSMA,T-ROUTE"
```

### CASAM

```yaml
formulation:
  models: "NOM,CASAM,T-ROUTE"
```

## Running LSTM

LSTM requires external trained-model weights in addition to the normal sandbox configuration. These weights/models are not built by the sandbox workflow itself; the user must place them in a readable location and point `config_lstm.yaml` at them.

Recommended layout:

```text
$SANDBOX_DATA/lstm/
  trained_neuralhydrology_models/
    <training-run-1>/
      config.yml
      model_epoch*.pt
      train_data/
        train_data_scaler.yml
    <training-run-2>/
      config.yml
      model_epoch*.pt
      train_data/
        train_data_scaler.yml
```

Using `$SANDBOX_DATA/lstm` keeps trained models separate from the LSTM source code under `SANDBOX_DIR/extern/lstm`.

To run LSTM, the user must configure two things in `configs/basefiles/config_lstm.yaml`:

1. `train_cfg_file`
2. `attributes_file`

Example:

```yaml
train_cfg_file: /path/to/sandbox_data/lstm/trained_neuralhydrology_models/<training-run>/config.yml
attributes_file: /path/to/attributes.parquet
```

For LSTM ensembles, both values may be lists; see Example 2 in the `configs/basefiles/config_lstm.yaml`.

The workflow automatically updates `run_dir` so it matches the directory containing each referenced training `config.yml`. Users do not need to edit `run_dir` manually.

Before running `sandbox --conf` or `sandbox --run`, check that:

1. `train_cfg_file` exists
2. `attributes_file` exists
3. the training run directory contains `train_data/train_data_scaler.yml`
4. the training run directory contains the required `model_epoch*.pt` files

You may keep the trained data anywhere on disk and use absolute paths, as long as `train_cfg_file` and `attributes_file` point to valid locations.

## Running dHBV

dHBV requires external trained-model weights in addition to the normal sandbox configuration. These weights/models are not built by the sandbox workflow itself; the user must place them in a readable location and point `config_dhbv.yaml` at them.

Recommended layout:

```text
$SANDBOX_DATA/dhbv2/
  dhbv_2_mts/
    model/
      dhbv_2_mts/
        config.yaml
        dhbv_attrs.parquet
        ...
```

Using `$SANDBOX_DATA/dhbv2` keeps trained models separate from the dHBV source code under `SANDBOX_DIR/extern/dhbv2`.

To run dHBV, set `model_dir` in `configs/basefiles/config_dhbv.yaml`:

```yaml
model_dir: dhbv_2_mts/model/dhbv_2_mts
```

Relative `model_dir` values are resolved under `$SANDBOX_DATA/dhbv2/`. Absolute paths are also supported.

`attributes_file` is optional. If omitted, the workflow defaults to:

```text
<model_dir>/dhbv_attrs.parquet
```

Set `attributes_file` only if your attribute parquet lives outside the model directory.

## Troubleshooting

### Unsupported formulation

Run:

```bash
sandbox --formulations
```

Then make sure `formulation.models` matches one of the registered formulations. Use `CFE`, not `CFE-S` or `CFE-X`, in `models`.

### Missing geopackage

Check that each selected gage has a geopackage under:

```text
<input_dir>/<gage_id>/data/*.gpkg
```

### Missing forcing file

Check the forcing directory derived from `forcings.time`, or set `forcings.forcing_dir` explicitly.

### Missing shared library

Confirm the model has been built under `$NGEN_DIR/extern/<repo_name>`, or set `library_file` in the relevant `model_instances` entry.

### Calibration parameter block not found

Make sure `calib_params_block` matches a block name in `calib_config.yaml`.

### LSTM trained data missing

Check all of the following:

- `configs/basefiles/config_lstm.yaml` points to valid `train_cfg_file` and `attributes_file` paths
- the training run directory contains `train_data/train_data_scaler.yml`
- the trained weight files referenced by the run directory are present

### dHBV trained data missing

Check all of the following:

- `configs/basefiles/config_dhbv.yaml` points to a valid `model_dir`
- `model_dir` contains the trained dHBV bundle
- `dhbv_attrs.parquet` exists under `model_dir`, or `attributes_file` points to a valid parquet file
