# Configuration Guide

This guide is the field reference for the main NextGenSandbox configuration
files. It focuses on what each setting means and links to focused guides for
details.

The workflow uses two core configuration files:

- `configs/sandbox_config.yaml`: workflow paths, resource preparation,
  observations, formulation, model instances, and simulation settings.
- `configs/calib_config.yaml`: ngen-cal search strategy, objective function,
  plugins, and calibration parameter linkage.

Two supporting configuration areas provide default values. Users usually leave
them unchanged at first, but can modify them when they need to customize model
initial values or calibration parameter ranges:

- `configs/calibration/*.yaml`: calibratable parameter ranges for each model.
- `configs/basefiles/*`: model basefiles, or model configuration templates,
  used to generate model-specific input files.

If you are setting up your first custom project, read this guide together with
[workflow.md](./workflow.md).

## Related Guides

| Topic | Guide |
|---|---|
| Installation and smoke test | [install.md](./install.md) |
| Single-basin and launcher workflows | [workflow.md](./workflow.md) |
| Project directory layouts | [directory_layout.md](./directory_layout.md) |
| Supported formulations | [formulations.md](./formulations.md) |
| Observation files and custom objectives | [observations.md](./observations.md) |
| Formulations, model instances, and basefiles | [model_configuration.md](./model_configuration.md) |
| Calibration search and parameter files | [calibration.md](./calibration.md) |

## Command Requirements

Different commands use different parts of `sandbox_config.yaml`.

| Command | Required config blocks |
|---|---|
| `sandbox --subset -i <config>` | `general`, `subsetting` |
| `sandbox --forc -i <config>` | `general`, `forcings` |
| `sandbox --conf -i <config> -j <calib_config>` | `general`, `forcings`, `formulation`, `simulation` |
| `sandbox --run -i <config> -j <calib_config>` | `general`, `forcings`, `formulation`, `simulation` |

## `sandbox_config.yaml`

### `general`

Defines the project resource and output locations.

| Field | Meaning |
|---|---|
| `input_dir` | Reusable resource directory. Hydrofabric, forcing, and related inputs are stored here. |
| `output_dir` | Generated run artifact directory. Config files, realization files, model outputs, and calibration outputs are written here. |
| `layout` | Project-level resource layout. Options: `basin` or `flat`. |

See [directory_layout.md](./directory_layout.md) for the exact path structure
for both layouts.

### `subsetting`

Controls hydrofabric basin subsetting, optional DEM-derived attributes,
optional vegetation attributes, and selected gages. This block is used by
`sandbox --subset`.

| Field | Meaning |
|---|---|
| `hydrofabric.version` | Hydrofabric version, such as `"2.2"`. |
| `hydrofabric.gpkg_path` | Source hydrofabric geopackage used for subsetting. |
| `hydrofabric.compute_divide_attributes` | Whether to compute divide attributes locally. If the source hydrofabric already includes required attributes, set to `FALSE`. |
| `dem.output_dir` | DEM output location. `dem` keeps DEM files under the project layout; empty/null removes temporary DEM files. |
| `dem.input_file` | Optional local DEM file or VRT. If omitted and attributes are computed, the default DEM source is used. |
| `dem.aggregate_factor` | Positive integer aggregation factor for coarsening DEM resolution. |
| `vegetation.enabled` | Whether to compute vegetation attributes. |
| `vegetation.nlcd_path` | Path to NLCD raster used for vegetation classification. |
| `vegetation.classification_method` | Vegetation classification method, such as `majority` or `fraction`. |
| `gages.option` | Gage selection mode. Options: `ids`, `file`, or `gpkg`. |
| `gages.ids` | List of gage IDs when `option: ids`. |
| `gages.file.path` | CSV path when `option: file`. |
| `gages.file.column` | Column containing gage IDs when `option: file`. |
| `gages.gpkg.dir` | Directory or file path for existing geopackages when `option: gpkg`. |
| `gages.gpkg.pattern` | Filename pattern used when selecting existing geopackages. |
| `gages.gpkg.select` | Selected gages/geopackages from `gages.gpkg.dir`. |

See [workflow.md](./workflow.md#subset-hydrofabric) for the project-level
subsetting workflow.

### `forcings`

Controls forcing time range, format, domain, and optional rechunking.

| Field | Meaning |
|---|---|
| `format` | Forcing file format. Common values: `.nc` or `.csv`. |
| `rechunk` | Whether to write/use rechunked NetCDF forcing for faster ngen reads. |
| `time.start_time` | First forcing timestamp to prepare. |
| `time.end_time` | Last forcing timestamp to prepare. |
| `domain` | Forcing domain, such as `conus`, `HI`, `PR`, or `AK`. |
| `select` | Gage selection for forcing download. Can be one ID, a list, CSV input, or `all`. |
| `forcing_dir` | Optional explicit forcing directory. If omitted, the workflow derives the path from `general.layout`. |

Simulation time windows must fall within the forcing time range. See
[forcing.md](./forcing.md) for forcing-specific notes.

### `observations`

Optional local observations used by calibration plugins and custom objective
functions.

| Field | Meaning |
|---|---|
| `objective` | Optional objective shortcut or import path. Supported bundled shortcuts: `kge`, `nse`, `nnse`. |
| `<variable>.layout` | Observation layout. Options: `point` or `distributed`. |
| `<variable>.path` | CSV or Parquet observation path. Supports `{gage_id}` and `{variable}` placeholders. |
| `<variable>.time_column` | Timestamp column name. |
| `<variable>.value_column` | Value column name for point or long-format distributed data. |
| `<variable>.id_column` | Sub-basin ID column for long-format distributed data. |
| `<variable>.units` | Observation units. Required for local observations. |
| `<variable>.simulated` | Simulation output variable corresponding to the observation variable. |

See [observations.md](./observations.md) for file layouts, units, simulated
variables, and multi-variable objectives.

### `formulation`

Controls the selected model formulation and model-specific instances.

| Field | Meaning |
|---|---|
| `models` | Comma-separated model components, such as `"PET,CFE,T-ROUTE"`. |
| `clean` | Config/output cleanup policy for generated files. |
| `verbosity` | Logging verbosity. Use `0` unless debugging. |
| `model_instances` | Optional per-model instance customization. |
| `ensemble.enabled` | Enables ensemble/member generation. |
| `ensemble.calib_params_groups` | Scope of calibratable parameters for ensemble/member workflows, such as `local` or `global`. |

See [model_configuration.md](./model_configuration.md) for formulation rules,
model instances, CFE variants, basefiles, LSTM, and dHBV.

### `simulation`

Controls task type, gages, time windows, output retention, and partitioning.

| Field | Meaning |
|---|---|
| `task_type` | Workflow task. Options: `control`, `calibration`, `validation`, `calibvalid`, `restart`. |
| `gage_ids_input` | Gage IDs to run. Can be one ID, a list, or a CSV path depending on workflow. |
| `sim_name_suffix` | Suffix appended to the gage ID to name the run directory. |
| `simulation_time` | Time window for `control` runs. |
| `calibration_time` | Full calibration period, including spinup. |
| `calib_eval_time` | Evaluation period within `calibration_time`. |
| `validation_time` | Full validation period, including spinup. |
| `valid_eval_time` | Evaluation period within `validation_time`. |
| `restart_dir` | Restart source directory for `restart` runs. Supports `{*}` placeholders. |
| `outputs.divide_variables` | BMI variables written to `cat-<divide_id>.csv` files, with required units. |
| `outputs.calibration.retention` | Calibration output retention. Options: `best` or `all`. |
| `partitioning.mode` | Execution mode. Options: `serial` or `parallel`. |
| `partitioning.max_nexus_per_proc` | Maximum nexus count per processor in parallel mode. |
| `partitioning.max_procs` | Maximum number of processors to use. |

Required time fields depend on `task_type`.

| `task_type` | Required time/config fields |
|---|---|
| `control` | `simulation_time` |
| `calibration` | `calibration_time`, `calib_eval_time` |
| `validation` | `validation_time`, `valid_eval_time` |
| `calibvalid` | `calibration_time`, `calib_eval_time`, `validation_time`, `valid_eval_time` |
| `restart` | `calibration_time`, `calib_eval_time`, `restart_dir` |

## `calib_config.yaml`

`configs/calib_config.yaml` controls ngen-cal behavior. The sandbox reads this
file, fills run-specific paths, adds plugin settings when needed, and writes a
run-local `ngen-cal_calib_config.yaml`.

### `general`

| Field | Meaning |
|---|---|
| `strategy.type` | ngen-cal strategy type, usually `estimation`. |
| `strategy.algorithm` | Search algorithm, such as `dds` or `pso`. |
| `strategy.parameters` | Optional algorithm-specific settings. |
| `log` | Enables ngen-cal logging. |
| `start_iteration` | First calibration iteration. |
| `iterations` | Number of calibration iterations or generations. |
| `random_seed` | Random seed for reproducibility. |
| `workdir` | ngen-cal working directory. Usually left as `./`. |

### `calibration`

| Field | Meaning |
|---|---|
| `params_dir` | Directory under `configs/` containing model calibration parameter files. Default: `calibration`. |

### `model`

| Field | Meaning |
|---|---|
| `type` | Model type passed to ngen-cal, usually `ngen`. |
| `binary` | Filled by the sandbox with the ngen executable path. |
| `realization` | Filled by the sandbox with the realization file. |
| `hydrofabric` | Filled by the sandbox with the basin geopackage. |
| `eval_feature` | Filled by the sandbox with the target evaluation feature. |
| `strategy` | ngen-cal parameter strategy, commonly `uniform`. |
| `params` | Filled by the sandbox from model calibration parameter blocks. |
| `eval_params.objective` | Objective function name or import path. |
| `eval_params.target` | Optimization target, usually `min`. |
| `plugins` | ngen-cal plugin classes to load. |
| `plugin_settings` | Optional plugin settings. Often written by the sandbox for local observations. |

See [calibration.md](./calibration.md) for PSO settings, calibration parameter
files, and calibration output retention.

## Supporting Files

### `configs/calibration/*.yaml`

These files define calibratable parameter names, ranges, initial values, and
optional scaling for each model. Users can adjust them to change the
calibration search space. See [calibration.md](./calibration.md#model-calibration-parameter-files).

### `configs/basefiles/*`

These model basefiles are templates used to generate model-specific input files
during `sandbox --conf`. Users can adjust them to change model initialization
values, model switches, static attribute files, or trained-model paths. See
[model_configuration.md](./model_configuration.md#model-basefiles).

## Troubleshooting

| Problem | What to check |
|---|---|
| Unsupported formulation | Run `sandbox --formulations`; use `CFE`, not `CFE-S` or `CFE-X`, in `formulation.models`. |
| Missing geopackage | Check the path expected by `general.layout`; see [directory_layout.md](./directory_layout.md). |
| Missing forcing file | Check the forcing directory derived from `forcings.time`, or set `forcings.forcing_dir`. |
| Missing shared library | Confirm the model was built under `$NGEN_DIR/extern/<repo_name>`, or set `library_file` in `model_instances`. |
| Calibration parameter block not found | Make sure `calib_params_block` exists in `configs/calibration/*.yaml`. |
| LSTM or dHBV trained data missing | Check the model basefile and data paths; see [model_configuration.md](./model_configuration.md). |
