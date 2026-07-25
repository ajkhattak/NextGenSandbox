# Configure NextGenSandbox

This guide is the reference for the configuration files read by
NextGenSandbox. It introduces their structure, explains what each setting
controls, and points to focused guides for advanced examples.

## Configuration Files

NextGenSandbox provides two project configuration samples:

| File | Purpose |
|---|---|
| `configs/sandbox_config.yaml` | Minimal starter configuration for a typical project. |
| `configs/sandbox_config_reference.yaml` | Complete, correctly indented reference with optional fields and alternative input methods ready to uncomment. |

Two supporting directories provide model defaults:

| Location | Purpose |
|---|---|
| `configs/calibration/*.yaml` | Calibratable parameter names, bounds, initial values, and scales for supported models. |
| `configs/optimizers/*.yaml` | Algorithm-specific tuning settings, such as PSO swarm coefficients. |
| `configs/basefiles/*` | Model configuration templates used to generate run-specific model files. |

The supporting files work without modification for their default model
instances. Edit them only when you need different parameter ranges, initial
conditions, model switches, static attributes, or trained-model paths.

For a custom project, make a project-specific copy of the relevant top-level
configuration file rather than repeatedly changing the distributed sample.

## First Look at `sandbox_config.yaml`

Start with
[configs/sandbox_config.yaml](https://github.com/ajkhattak/NextGenSandbox/blob/main/configs/sandbox_config.yaml).
When you need another gage source, observation layout, optimizer, model
instance, or task type, copy the prepared structure from
[configs/sandbox_config_reference.yaml](https://github.com/ajkhattak/NextGenSandbox/blob/main/configs/sandbox_config_reference.yaml).
Both files use the same seven top-level sections:

```yaml
general:
  # Project directories, resource layout, and complete gage list

subsetting:
  # Hydrofabric and optional DEM/vegetation preparation

forcings:
  # Forcing source, period, format, and selected gages

observations:
  # Optional local streamflow, ET, SWE, or other observations

calibration:
  # Optimizer, iteration count, random seed, and objective function

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
| `sandbox --conf` | Generate model and realization files. | `general`, `forcings`, `observations`, `calibration`, `formulation`, `simulation` |
| `sandbox --dryrun` | Show the prepared run without executing it. | `general`, `forcings`, `observations`, `calibration`, `formulation`, `simulation` |
| `sandbox --run` | Execute the configured simulation or calibration. | `general`, `forcings`, `observations`, `calibration`, `formulation`, `simulation` |

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

If geopackages already exist, configure `general.gages.option: gpkg`; project
execution can then skip hydrofabric subsetting.

### `forcings`

The `forcings` block controls forcing download, discovery, format, period, and
optional NetCDF rechunking.

| Field | Meaning |
|---|---|
| `format` | Forcing format: `.nc` or `.csv`. |
| `use_corrected` | Use the corrected NetCDF forcing file during configuration and model runs. Recommended; default: `true`. |
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

For NetCDF downloaded with `sandbox --forc`, Sandbox preserves the original and
writes a sibling file named `*_corrected.nc`. The correction fills missing
values along the time dimension, replaces invalid radiation and air-temperature
values through interpolation, and sets the precipitation units metadata to
`mm/hr`. With `use_corrected: true`, later configuration and run steps
select this corrected file. Setting it to `false` selects the original NetCDF
file; it does not prevent the forcing step from creating the corrected copy.

Using the corrected file is recommended. The downloaded raw NetCDF may not
declare `mm/hr` as the precipitation units. Without that metadata, ngen cannot
convert precipitation when a model expects units other than `mm/hr`. The raw
file may therefore work only when the model already expects `mm/hr`.

When both correction and rechunking are used, the file selected by ngen is
typically named `*_corrected_rechunked.nc`.

Every simulation period must fall within the configured forcing period. See
[forcing.md](./forcing.md) for correction details, external forcing examples,
and rechunking behavior.

### `observations`

The optional `observations` block provides local data to ngen-cal plugins.
Multiple variables, such as streamflow and ET, may be configured together.

| Field | Meaning |
|---|---|
| `<variable>.layout` | Observation layout: `point` or `distributed`. |
| `<variable>.path` | CSV or Parquet path. Supports `<gage_id>` and `<variable>` placeholders. |
| `<variable>.time_column` | Timestamp column. |
| `<variable>.value_column` | Value column for point or long-format distributed data. |
| `<variable>.id_column` | Divide ID column for long-format distributed data. |
| `<variable>.units` | Observation units. Required for local observations. |
| `<variable>.simulated` | Divide output variable corresponding to the observation. |

If the block is empty, ngen-cal uses its default streamflow observation
behavior. Local streamflow must use `m3/s` or `m3/sec`. Multi-variable
calibration uses the objective selected under `calibration.objective`.

See [observations.md](./observations.md) for supported file layouts, spatial
aggregation, units, time alignment, and simulation-observation output.

### `calibration`

The `calibration` block controls the parameter search and objective used for
calibration and validation. It is separate from `simulation.time.calibration`,
which defines the calibration time window.

```yaml
calibration:
  optimizer:
    algorithm: dds
    iterations: 400
    random_seed: 444
  objective:
    function: kge
```

| Field | Meaning |
|---|---|
| `optimizer.algorithm` | Search algorithm: `dds` or `pso`. |
| `optimizer.iterations` | Number of DDS iterations or PSO generations. Must be greater than zero. |
| `optimizer.random_seed` | Integer random seed used for reproducibility. |
| `optimizer.settings_file` | PSO settings YAML. Used only with `algorithm: pso`; a relative path is resolved from the project config directory. |
| `objective.function` | One metric (`kge`, `nse`, or `nnse`), a weighted metric mapping, or a custom Python import path. |

To emphasize several aspects of streamflow behavior, construct a weighted
objective:

```yaml
calibration:
  objective:
    function:
      kge: 0.5
      log_kge: 0.3
      fdc: 0.2
```

Available components are `kge`, `nse`, `nnse`, `log_kge`, and `fdc`.
`log_kge` and `fdc` apply only to streamflow. The FDC component evaluates both
high-flow exceedances `(0.01, 0.05, 0.10)` and low-flow exceedances
`(0.70, 0.90, 0.95)`.

Sandbox objectives are losses minimized internally. For PSO, keep
swarm-specific values outside the project config:

```yaml
calibration:
  optimizer:
    algorithm: pso
    iterations: 40
    random_seed: 444
    settings_file: "optimizers/pso.yaml"
  objective:
    function: kge
```

See [calibration.md](./calibration.md) for DDS, PSO settings, custom objectives,
and model parameter files.

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
| `label` | Label appended to each gage ID when naming its simulation output directory. For example, `pet_cfe` produces `<gage_id>_pet_cfe`. |
| `time.control` | Time period for a control run. |
| `time.calibration` | Time period used for calibration. |
| `time.validations` | One or more validation period definitions. |
| `restart_dir` | Restart source path. Supports `<gage_id>`. |
| `outputs.divide_variables` | BMI variables written to divide CSV files. Each variable requires units. |
| `outputs.calibration.retention` | Calibration output retention: `best` or `all`. |
| `outputs.metadata.enabled` | Write run metadata during configuration generation. |
| `outputs.metadata.file` | Metadata filename inside each gage output directory. Default: `simulation_metadata.yml`. |
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

## Generated ngen-cal Configuration

For calibration and validation tasks, Sandbox translates the project settings
into `configs/ngen-cal_calib_config.yaml` or
`configs/ngen-cal_valid_config.yaml` under the gage output directory. These
files record resolved paths, active parameter blocks, plugins, observations,
and objective settings. They are run artifacts for inspection and
reproducibility, not additional user configuration files.

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

## Reference Guides

| Topic | Guide |
|---|---|
| Resource and output directory structures | [directory_layout.md](./directory_layout.md) |
| Forcing files and rechunking | [forcing.md](./forcing.md) |
| Supported formulations | [formulations.md](./formulations.md) |
| Model instances and basefiles | [model_configuration.md](./model_configuration.md) |
| Observations and objective functions | [observations.md](./observations.md) |
| Calibration, DDS, PSO, and parameter files | [calibration.md](./calibration.md) |
| Common errors | [diagnostics.md](./diagnostics.md) |

## Next: Run a Project

Continue to [workflow.md](./workflow.md) to prepare reusable resources,
generate model configuration files, inspect the execution command, and run the
configured simulation or calibration.
