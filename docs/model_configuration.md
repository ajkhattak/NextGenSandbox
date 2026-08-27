# Model Configuration

This guide explains formulation selection, model instances, model basefiles,
and special setup for ML-based models.

## Formulations

The `formulations.<name>.models` value lists the model components used by a
run. A regular Sandbox configuration contains one named formulation.

```yaml
formulations:
  nom_cfe:
    models: "NOM,CFE,T-ROUTE"
```

Run this command to list supported formulations:

```bash
sandbox --formulations
```

`T-ROUTE` may be omitted from a supported formulation; the workflow appends it
automatically. All other model components must match a registered formulation
exactly.

See [formulations.md](./formulations.md) for the supported formulation list.

## Model Instances

`models` selects model components. `model_instances` customizes the configured
instance used for a component.

For example, use `CFE` in `models`, then select the CFE-X, CFE with
Xinanjiang scheme, instance through `model_instances`:

```yaml
formulations:
  nom_cfe_x:
    models: "NOM,CFE,T-ROUTE"

    model_instances:
      CFE:
        - name: cfe-x
          basefile: "config_cfe-x.yaml"
          repo_name: "cfe"
          calib_params_block: "cfex_params"
```

Do not put `CFE-S` or `CFE-X` in `models`. `CFE` defaults to the
`cfe-s`/Schaake instance. Use `formulations.<name>.model_instances.CFE` to
select another configured instance such as `cfe-x`.

Official variant names are validated by family. For example, `cfe-s` fields
must contain CFE-S markers such as `cfe-s`/`cfes`, while `cfe-x` fields must
contain CFE-X markers such as `cfe-x`/`cfex`. Custom files and parameter blocks
are allowed within the same family:

```yaml
formulations:
  nom_cfe_x:
    models: "NOM,CFE,T-ROUTE"
    model_instances:
      CFE:
        - name: cfe-x
          basefile: "config_cfe-x_custom.yaml"
          calib_params_block: "cfex_params_custom"
          calib_params_file: "cfe-x-custom.yaml"
```

Mixed family markers are rejected. For example, `name: cfe-x` cannot use
`config_cfe-s.yaml` or `cfes_params`. Custom variant names, such as
`cfe-custom`, may use their own basefile, parameter block, and parameter file.

## Model Instance Fields

| Field | Meaning |
|---|---|
| `name` | Instance name and config subdirectory name, for example `cfe-x`. |
| `basefile` | Base configuration template under `configs/basefiles`. |
| `repo_name` | Model repository name under `$NGEN_DIR/extern`. |
| `calib_params_block` | Calibration parameter block name loaded from `configs/calibration/*.yaml`. |
| `calib_params_file` | Optional calibration parameter file under `configs/calibration/`. If omitted, the workflow tries the instance name, model name, and block name. |
| `ngen_cal_model_name` | Optional model name expected by `ngen-cal` if different from the sandbox model key. |
| `library_file` | Optional full path to a model shared library. If omitted, the workflow searches under `$NGEN_DIR/extern/<repo_name>`. |

The parent key, such as `CFE`, is the sandbox model component. The `name` field
is the configured instance of that component.

## Model Basefiles

Model basefiles live under:

```text
configs/basefiles/
```

These files are model initialization/configuration templates. The sandbox reads
them during `sandbox --conf`, applies dynamic values from the selected basin
and simulation settings, and writes generated model config files into each run
directory.

Users may edit these files when they need to change model initialization
values, trained-model paths, static attributes, or model-specific switches. For
example:

- `config_cfe-s.yaml` and `config_cfe-x.yaml` define CFE initialization values.
- `config_noahowp.input` defines Noah-OWP-Modular initialization settings.
- `config_lstm.yaml` points to LSTM trained data and attributes.
- `config_dhbv.yaml` points to dHBV trained data.

The name `basefiles` is kept for compatibility with the current code and
examples. Conceptually, these are model configuration templates; a future
rename to something like `configs/model_templates/` would be clearer but would
require a coordinated code and documentation update.

## Running LSTM

LSTM requires external trained-model weights in addition to the normal sandbox
configuration. These weights/models are not built by the sandbox workflow
itself; the user must place them in a readable location and point
`config_lstm.yaml` at them.

Recommended layout:

```text
$SANDBOX_DATA_DIR/lstm/
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

Using `$SANDBOX_DATA_DIR/lstm` keeps trained models separate from the LSTM
source code under `SANDBOX_DIR/extern/lstm`.

To run LSTM, configure these fields in `configs/basefiles/config_lstm.yaml`:

```yaml
train_cfg_file: $SANDBOX_DATA_DIR/lstm/trained_neuralhydrology_models/<training-run>/config.yml
attributes_file: /path/to/attributes.parquet
```

For LSTM ensembles, both values may be lists; see the examples in
`configs/basefiles/config_lstm.yaml`.

The workflow automatically updates `run_dir` so it matches the directory
containing each referenced training `config.yml`. Users do not need to edit
`run_dir` manually.

Before running `sandbox --conf` or `sandbox --run`, check that:

1. `train_cfg_file` exists
2. `attributes_file` exists
3. the training run directory contains `train_data/train_data_scaler.yml`
4. the training run directory contains the required `model_epoch*.pt` files

You may keep the trained data anywhere on disk and use absolute paths, as long
as `train_cfg_file` and `attributes_file` point to valid locations.

## Running dHBV

dHBV requires external trained-model weights in addition to the normal sandbox
configuration. These weights/models are not built by the sandbox workflow
itself; the user must place them in a readable location and point
`config_dhbv.yaml` at them.

Recommended layout:

```text
$SANDBOX_DATA_DIR/dhbv2/
  dhbv_2_mts/
    model/
      dhbv_2_mts/
        config.yaml
        dhbv_attrs.parquet
        ...
```

Using `$SANDBOX_DATA_DIR/dhbv2` keeps trained models separate from the dHBV
source code under `SANDBOX_DIR/extern/dhbv2`.

To run dHBV, set `model_dir` in `configs/basefiles/config_dhbv.yaml`:

```yaml
model_dir: dhbv_2_mts/model/dhbv_2_mts
```

Relative `model_dir` values are resolved under `$SANDBOX_DATA_DIR/dhbv2/`.
Absolute paths are also supported.

`attributes_file` is optional. If omitted, the workflow defaults to:

```text
<model_dir>/dhbv_attrs.parquet
```

Set `attributes_file` only if your attribute parquet lives outside the model
directory.

## Examples

### PET + Default CFE

```yaml
formulations:
  pet_cfe:
    models: "PET,CFE,T-ROUTE"
```

### NOM + CFE-X

```yaml
formulations:
  nom_cfe_x:
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
formulations:
  snow_pet_sacsma:
    models: "SNOW17,PET,SACSMA,T-ROUTE"
```

### CASAM

```yaml
formulations:
  nom_casam:
    models: "NOM,CASAM,T-ROUTE"
```
