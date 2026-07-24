# Configure NextGenSandbox

This guide is the reference for the configuration files read by
NextGenSandbox. It introduces their structure, explains what each setting
controls, and points to focused guides for advanced examples.

Use [workflow.md](./workflow.md) when you are ready to prepare resources,
generate model files, and run a project.

## Configuration Files

NextGenSandbox uses two main YAML files:

| File | Purpose |
|---|---|
| `configs/sandbox_config.yaml` | Defines project paths, gages, reusable resources, observations, formulation, simulation periods, and outputs. |
| `configs/calib_config.yaml` | Defines ngen-cal search behavior, objective settings, plugins, and the location of model calibration parameters. |

Two supporting directories provide model defaults:

| Location | Purpose |
|---|---|
| `configs/calibration/*.yaml` | Calibratable parameter names, bounds, initial values, and scales for supported models. |
| `configs/basefiles/*` | Model configuration templates used to generate run-specific model files. |

The supporting files work without modification for their default model
instances. Edit them only when you need different parameter ranges, initial
conditions, model switches, static attributes, or trained-model paths.

For a custom project, make a project-specific copy of the relevant top-level
configuration file rather than repeatedly changing the distributed sample.

## First Look at `sandbox_config.yaml`

Open [configs/sandbox_config.yaml](../configs/sandbox_config.yaml) while reading
this guide. It is a YAML file organized into six named top-level sections:

```yaml
general:
  # Project directories, resource layout, and complete gage list

subsetting:
  # Hydrofabric and optional DEM/vegetation preparation

forcings:
  # Forcing source, period, format, and selected gages

observations:
  # Optional local streamflow, ET, SWE, or other observations

formulation:
  # Models and model-instance customization

simulation:
  # Task, time periods, outputs, and processor settings
```

This guide calls each top-level section a **block**. For example, `general` is
a block. A setting inside a block is a **field**. For example, `input_dir` is a
field in the `general` block and may be referred to as `general.input_dir`.

YAML indentation defines which fields belong to a block. Use spaces rather than
tabs and preserve the indentation shown in the distributed sample.

## Which Settings Each Command Uses

NextGenSandbox runs in stages. Each command reads the sections relevant to that
stage; it does not use every setting in the file.

| Command | Purpose | Sections read from `sandbox_config.yaml` |
|---|---|---|
| `sandbox --subset` | Create gage-specific hydrofabric files. | `general`, `subsetting` |
| `sandbox --forc` | Download or prepare forcing data. | `general`, `forcings` |
| `sandbox --conf` | Generate model and realization files. | `general`, `forcings`, `observations`, `formulation`, `simulation` |
| `sandbox --dryrun` | Show the prepared run without executing it. | `general`, `forcings`, `observations`, `formulation`, `simulation` |
| `sandbox --run` | Execute the configured simulation or calibration. | `general`, `forcings`, `observations`, `formulation`, `simulation` |

`configs/calib_config.yaml` is used when generating or running calibration and
validation tasks. Pass another file with `-j`; otherwise the distributed
`configs/calib_config.yaml` is used.

## Sandbox Configuration Reference

### `general`

The `general` block defines project-wide paths, resource organization, and the
full set of gages available to workflow steps.

| Field | Meaning |
|---|---|
| `input_dir` | Root directory for reusable resources, including hydrofabric and forcing files. |
| `output_dir` | Root directory for generated configurations, realizations, simulation outputs, and calibration artifacts. |
| `resource_layout` | Resource organization. Options: `gage` or `resource`. Use one layout consistently within a project. |
| `gages.option` | How the project gage set is defined. Options: `ids`, `file`, or `gpkg`. |
| `gages.ids` | Gage ID list used with `option: ids`. Quote IDs so leading zeros are preserved. |
| `gages.file.path` | CSV file used with `option: file`. |
| `gages.file.column` | CSV column containing gage IDs. |
| `gages.gpkg.dir` | Existing geopackage directory or individual geopackage used with `option: gpkg`. If omitted, Sandbox searches `input_dir` using `resource_layout`. |
| `gages.gpkg.pattern` | Filename pattern used to discover geopackages. |
| `gages.gpkg.select` | Optional subset selected from the discovered geopackages. |

`general.gages` is the authoritative project gage set. The `gages` fields under
`subsetting`, `forcings`, and `simulation` only filter that set for an
individual workflow stage. A step filter accepts:

- `all`
- one quoted gage ID
- a list of quoted gage IDs

CSV and geopackage discovery belong only under `general.gages`.

See [directory_layout.md](./directory_layout.md) for the paths produced by the
`gage` and `resource` layouts.

### `subsetting`

The `subsetting` block controls `sandbox --subset`. It selects gage-specific
geopackages from a source hydrofabric and can optionally calculate DEM-derived
and vegetation attributes.

| Field | Meaning |
|---|---|
| `hydrofabric.version` | Source hydrofabric version, such as `"2.2"`. |
| `hydrofabric.gpkg_path` | Source hydrofabric geopackage. Its version must match `hydrofabric.version`. |
| `hydrofabric.compute_divide_attributes` | Compute divide attributes locally. Set to `FALSE` when the source geopackage already contains the required attributes. |
| `dem.input_file` | Optional DEM file or VRT. When omitted and divide attributes are requested, Sandbox uses its default DEM source. |
| `dem.output_dir` | Retained DEM output location. Use `dem` for the project resource layout or an explicit path; use null/empty to remove temporary DEM files. |
| `dem.aggregate_factor` | Integer greater than or equal to 1 used to coarsen DEM resolution. |
| `vegetation.enabled` | Enable vegetation attribute calculation. |
| `vegetation.nlcd_path` | NLCD raster used when vegetation calculation is enabled. |
| `vegetation.classification_method` | Vegetation classification method: `majority` or `fraction`. |
| `gages` | Optional filter on `general.gages`. |

If geopackages already exist, configure `general.gages.option: gpkg` and skip
the subsetting command. See [workflow.md](./workflow.md#prepare-the-hydrofabric).

### `forcings`

The `forcings` block controls forcing download, discovery, format, period, and
optional NetCDF rechunking.

| Field | Meaning |
|---|---|
| `format` | Forcing format: `.nc` or `.csv`. |
| `rechunk` | Create or reuse a rechunked NetCDF file for faster ngen reads. |
| `time.start` | First forcing timestamp. A date without a time defaults to `00:00:00`. |
| `time.end` | Last forcing timestamp. A date without a time defaults to `00:00:00`. |
| `domain` | Forcing domain, such as `conus`, `HI`, `PR`, or `AK`. |
| `gages` | Optional filter on `general.gages`. |
| `forcing_dir` | Optional external forcing directory, path pattern, or single NetCDF file. |

When `forcing_dir` is omitted, Sandbox derives the location from `input_dir`
and `resource_layout`. For one selected gage, `forcing_dir` may point directly
to one `.nc` file. For multiple gages outside the project resource tree, use
the `<gage_id>` placeholder in the directory or filename.

Every simulation period must fall within the configured forcing period. See
[forcing.md](./forcing.md) for external forcing examples and rechunking
behavior.

### `observations`

The optional `observations` block provides local data to ngen-cal plugins.
Multiple variables, such as streamflow and ET, may be configured together.

| Field | Meaning |
|---|---|
| `objective` | Bundled objective shortcut (`kge`, `nse`, or `nnse`) or a custom import path. |
| `<variable>.layout` | Observation layout: `point` or `distributed`. |
| `<variable>.path` | CSV or Parquet path. Supports `<gage_id>` and `<variable>` placeholders. |
| `<variable>.time_column` | Timestamp column. |
| `<variable>.value_column` | Value column for point or long-format distributed data. |
| `<variable>.id_column` | Divide ID column for long-format distributed data. |
| `<variable>.units` | Observation units. Required for local observations. |
| `<variable>.simulated` | Divide output variable corresponding to the observation. |

If the block is empty, ngen-cal uses its default streamflow observation
behavior. Local streamflow must use `m3/s` or `m3/sec`. Multi-variable
calibration requires a compatible custom objective.

See [observations.md](./observations.md) for supported file layouts, spatial
aggregation, units, time alignment, and simulation-observation output.

### `formulation`

The `formulation` block selects model components and optional custom model
instances.

| Field | Meaning |
|---|---|
| `models` | Comma-separated supported components, such as `"PET, CFE, T-ROUTE"`. |
| `clean` | Cleanup policy for existing generated configuration and realization files. |
| `verbosity` | Model/configuration verbosity. Use `0` unless debugging. |
| `model_instances` | Optional overrides or additional instances for a model family. |
| `ensemble.enabled` | Enable ensemble/member configuration generation. |
| `ensemble.calib_params_groups` | Parameter scope for ensemble members, such as `local` or `global`. |

List the registered formulation components with:

```bash
sandbox --formulations
```

Use `CFE` as the formulation component. Select CFE-S, CFE-X, or a custom CFE
variant through `model_instances`.

See [model_configuration.md](./model_configuration.md) for instance fields,
variant validation, basefiles, shared libraries, LSTM, and dHBV.

### `simulation`

The `simulation` block defines the task, selected gages, time windows,
partitioning, and output behavior.

| Field | Meaning |
|---|---|
| `task_type` | Workflow task: `control`, `calibration`, `validation`, `calibvalid`, or `restart`. |
| `gages` | Optional filter on `general.gages`. |
| `sim_name_suffix` | Suffix appended to each gage ID when naming its run directory. |
| `time.control` | Time period for a control run. |
| `time.calibration` | Time period used for calibration. |
| `time.validations` | One or more validation period definitions. |
| `restart_dir` | Restart source path. Supports `<gage_id>`. |
| `outputs.divide_variables` | BMI variables written to divide CSV files. Each variable requires units. |
| `outputs.calibration.retention` | Calibration output retention: `best` or `all`. |
| `outputs.metadata.enabled` | Write run metadata during configuration generation. |
| `outputs.metadata.run_file` | Metadata filename inside each gage output directory. |
| `outputs.metadata.index_dir` | Optional metadata index used by Sandbox Launcher. |
| `partitioning.mode` | ngen execution mode: `serial` or `parallel`. |
| `partitioning.max_nexus_per_proc` | Maximum nexus count assigned to one process in parallel mode. |
| `partitioning.max_procs` | Maximum number of ngen processes. |

#### Time periods

Control, calibration, and manually defined validation periods use the same
fields:

| Field | Meaning |
|---|---|
| `name` | Validation name used in generated files and `run_index.yml`. |
| `start` | Simulation start. A date without a time defaults to `00:00:00`. |
| `spinup` | Duration before model evaluation, such as `12 months`, `30 days`, or `0 h`. Use `month` or `months`, not `m`, for months. |
| `evaluation` | Model evaluation duration after spinup. |
| `end` | Optional inclusive simulation end. When provided, it overrides `evaluation`. |

Example:

```yaml
simulation:
  task_type: calibvalid
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
```

Sandbox assumes hourly model timesteps when converting durations to inclusive
end timestamps.

Required periods depend on `task_type`:

| Task | Required settings |
|---|---|
| `control` | `time.control` |
| `calibration` | `time.calibration` |
| `validation` | One or more `time.validations` entries |
| `calibvalid` | `time.calibration` and one or more `time.validations` entries |
| `restart` | `time.calibration` and `restart_dir` |

#### Validation periods from a CSV file

A validation entry may create several validation windows from one CSV:

```yaml
validations:
  - name: water_year_split
    source: file
    file: "/path/to/year_tasks.csv"
    year_type: water_year
    year_column: year
    task_column: task_type
    select: valid
    spinup: "12 months"
    evaluation: "1 year"
```

The CSV contains one row per year:

```csv
year,task_type
2011,valid
2012,calib
2013,valid
```

`year_type` may be `water_year` or `calendar_year`. For water year 2011, the
simulation begins on October 1, 2010. Sandbox selects rows whose task value
matches `select` and creates one named validation run per selected year.

During calibration or validation, `sandbox --run` writes `run_index.yml` under
the gage output directory. It maps each named calibration or validation to its
timestamped ngen-cal worker directory.

## Calibration Configuration Reference

`configs/calib_config.yaml` is the base ngen-cal configuration. Sandbox fills
run-specific paths and parameter blocks, adds observation plugin settings when
needed, and writes a generated `ngen-cal_calib_config.yaml` under the run
configuration directory.

### `general`

| Field | Meaning |
|---|---|
| `strategy.type` | ngen-cal strategy type, normally `estimation`. |
| `strategy.algorithm` | Search algorithm, such as `dds` or `pso`. |
| `strategy.parameters` | Algorithm-specific options. Used by PSO; normally omitted for DDS. |
| `log` | Enable ngen-cal logging. |
| `start_iteration` | First calibration iteration. |
| `iterations` | Number of DDS iterations or PSO generations. |
| `random_seed` | Random seed for reproducibility. |
| `workdir` | ngen-cal working directory. Usually left as `./`. |

### `calibration`

| Field | Meaning |
|---|---|
| `params_dir` | Directory containing model calibration parameter files. A relative path is resolved from the directory containing `calib_config.yaml`. |

### `model`

| Field | Meaning |
|---|---|
| `type` | Model type passed to ngen-cal, normally `ngen`. |
| `binary` | Placeholder filled with the ngen executable path. |
| `realization` | Placeholder filled with the generated realization path. |
| `hydrofabric` | Placeholder filled with the selected geopackage. |
| `eval_feature` | Placeholder filled with the target evaluation feature. |
| `strategy` | ngen-cal parameter strategy, commonly `uniform`. |
| `params` | Placeholder filled from the active model calibration files. |
| `eval_params.objective` | Objective function name or import path. |
| `eval_params.target` | Optimization direction, normally `min`. |
| `plugins` | ngen-cal plugin classes to load. |
| `plugin_settings` | Optional plugin settings. Sandbox adds local observation settings when required. |

Keep the `<*>` placeholders in the base file; Sandbox replaces them for each
gage and run.

Detailed DDS, PSO, plugin, retention, and parameter-file behavior is documented
in [calibration.md](./calibration.md).

## Supporting Model Defaults

### Calibration parameter files

Files under `configs/calibration/` define parameter names, physical bounds,
initial values, and optional scales. For `scale: log10`, keep `min`, `max`, and
`init` in physical model units; Sandbox converts them internally for ngen-cal.

Each model instance identifies its parameter block and parameter file. Models
without calibratable parameters do not require a file.

See [calibration.md](./calibration.md#model-calibration-parameter-files).

### Model basefiles

Files under `configs/basefiles/` are templates for generated model
configuration files. Edit them when a run needs different model initialization
values, switches, static attributes, or trained-model locations.

See [model_configuration.md](./model_configuration.md#model-basefiles).

## Related Guides

| Topic | Guide |
|---|---|
| Installation and verification | [install.md](./install.md) |
| Running a project | [workflow.md](./workflow.md) |
| Resource and output directory structures | [directory_layout.md](./directory_layout.md) |
| Forcing files and rechunking | [forcing.md](./forcing.md) |
| Supported formulations | [formulations.md](./formulations.md) |
| Model instances and basefiles | [model_configuration.md](./model_configuration.md) |
| Observations and objective functions | [observations.md](./observations.md) |
| Calibration, DDS, PSO, and parameter files | [calibration.md](./calibration.md) |
| Common errors | [diagnostics.md](./diagnostics.md) |
