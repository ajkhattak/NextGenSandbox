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
| `resource_layout` | Project-level resource directory layout. Options: `gage` or `resource`. |
| `gages.option` | Project gage selection mode. Options: `ids`, `file`, or `gpkg`. |
| `gages.ids` | Full project gage list when `gages.option: ids`. |
| `gages.file.path` | CSV path when `gages.option: file`. |
| `gages.file.column` | CSV column containing gage IDs when `gages.option: file`. |
| `gages.gpkg.dir` | Optional directory or file path for existing geopackages when `gages.option: gpkg`. If omitted, the workflow discovers geopackages from `general.input_dir` using `general.resource_layout`. |
| `gages.gpkg.pattern` | Filename pattern used when discovering geopackages. |
| `gages.gpkg.select` | Optional selected geopackages from `gages.gpkg.dir`. |

See [directory_layout.md](./directory_layout.md) for the exact path structure
for both layouts.

`general.gages` defines the full project gage set. Step-specific gage settings
under `subsetting`, `forcings`, and `simulation` are filters on this project
set. They may be `all`, one gage ID, or a list of gage IDs. CSV and geopackage
selection belong at the `general.gages` level.

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
| `gages` | Optional subsetting filter. Use `all`, one gage ID, or a list of IDs from `general.gages`. |

See [workflow.md](./workflow.md#subset-hydrofabric) for the project-level
subsetting workflow.

### `forcings`

Controls forcing time range, format, domain, and optional rechunking.

| Field | Meaning |
|---|---|
| `format` | Forcing file format. Common values: `.nc` or `.csv`. |
| `rechunk` | Whether to write/use rechunked NetCDF forcing for faster ngen reads. |
| `time.start` | First forcing timestamp to prepare. Date-only values default to `00:00:00`. |
| `time.end` | Last forcing timestamp to prepare. Date-only values default to `00:00:00`. |
| `domain` | Forcing domain, such as `conus`, `HI`, `PR`, or `AK`. |
| `gages` | Optional forcing filter. Use `all`, one gage ID, or a list of IDs from `general.gages`. |
| `forcing_dir` | Optional explicit forcing directory or NetCDF file. If omitted, the workflow derives the path from `general.resource_layout`. For one-gage NetCDF runs, this may point directly to a single `.nc` file. For multi-gage external forcing, use `<gage_id>` as the gage placeholder, such as `/path/to/forcing/<gage_id>` or `/path/to/forcing/<gage_id>.nc`. |

Simulation time windows must fall within the forcing time range. See
[forcing.md](./forcing.md) for forcing-specific notes.

### `observations`

Optional local observations used by calibration plugins and custom objective
functions.

| Field | Meaning |
|---|---|
| `objective` | Optional objective shortcut or import path. Supported bundled shortcuts: `kge`, `nse`, `nnse`. |
| `<variable>.layout` | Observation layout. Options: `point` or `distributed`. |
| `<variable>.path` | CSV or Parquet observation path. Supports `<gage_id>` and `<variable>` placeholders. |
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
| `gages` | Optional simulation filter. Use `all`, one gage ID, or a list of IDs from `general.gages`. |
| `sim_name_suffix` | Suffix appended to the gage ID to name the run directory. |
| `time.control` | Period definition for `control` runs. |
| `time.calibration` | Calibration period definition. |
| `time.validations` | List of validation period definitions. Currently one validation entry is supported by the runner; the list shape prepares for cross-validation. |
| `restart_dir` | Restart source directory for `restart` runs. Supports `<gage_id>` placeholders. |
| `outputs.divide_variables` | BMI variables written to `cat-<divide_id>.csv` files, with required units. |
| `outputs.calibration.retention` | Calibration output retention. Options: `best` or `all`. |
| `outputs.metadata.enabled` | Write a metadata file inside each gage output directory. |
| `outputs.metadata.run_file` | Metadata file written inside each gage output directory, usually `run_metadata.yml`. |
| `outputs.metadata.index_dir` | Optional directory under each experiment output where indexed `run_<gage_id>.yml` metadata files are written. Required by Sandbox Launcher. |
| `partitioning.mode` | Execution mode. Options: `serial` or `parallel`. |
| `partitioning.max_nexus_per_proc` | Maximum nexus count per processor in parallel mode. |
| `partitioning.max_procs` | Maximum number of processors to use. |

Each period uses:

| Field | Meaning |
|---|---|
| `name` | Optional name, mainly useful for validation periods. |
| `start` | Simulation start timestamp. Date-only values default to `00:00:00`. |
| `spinup` | Spinup duration before the model evaluation period, such as `12 months`, `30 days`, `30 d`, or `0 h`. Months must be written as `month` or `months`. |
| `evaluation` | Model evaluation period after spinup. Ignored when `end` is provided. |
| `end` | Optional inclusive end timestamp. Date-only values default to `00:00:00`; include `HH:MM:SS` for odd/manual stop times. |

Example:

```yaml
simulation:
  task_type: calibvalid
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
        # end: "2022-08-01 04:00:00"
```

Sandbox derives the internal ngen-cal-style windows from this block. For
example, `start: 2015-10-01`, `spinup: 12 months`, and `evaluation: 4 years`
becomes a full simulation window ending `2020-09-30 23:00:00` and a model
evaluation window starting `2016-10-01 00:00:00`. Sandbox assumes hourly ngen
model timesteps when deriving inclusive end times from duration fields.

Required time fields depend on `task_type`.

| `task_type` | Required time/config fields |
|---|---|
| `control` | `time.control` |
| `calibration` | `time.calibration` |
| `validation` | one entry in `time.validations` |
| `calibvalid` | `time.calibration` and one entry in `time.validations` |
| `restart` | `time.calibration`, `restart_dir` |

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
| Missing geopackage | Check the path expected by `general.resource_layout`; see [directory_layout.md](./directory_layout.md). |
| Missing forcing file | Check the forcing directory derived from `forcings.time`, or set `forcings.forcing_dir`. |
| Missing shared library | Confirm the model was built under `$NGEN_DIR/extern/<repo_name>`, or set `library_file` in `model_instances`. |
| Calibration parameter block not found | Make sure `calib_params_block` exists in `configs/calibration/*.yaml`. |
| LSTM or dHBV trained data missing | Check the model basefile and data paths; see [model_configuration.md](./model_configuration.md). |
