# Directory Layout

NextGenSandbox supports two project-level resource layouts: `basin` and
`flat`. Set the layout once under `general.layout` in `sandbox_config.yaml`.
The default is `basin`.

```yaml
general:
  layout: basin  # OPTIONS: basin | flat
```

A project should use one layout consistently. The code supports both layouts,
but mixing styles within the same project makes later forcing, configuration,
and run steps harder to reason about.

## Basin Layout

The default `basin` layout is:

```text
<input_dir>/
  <gage_id>/
    hydrofabric/
      gage_<gage_id>.gpkg
    forcing/
      <start_year>_to_<end_year>/
        <forcing>.nc
        <forcing>_rechunked.nc
    dem/  # optional; retained when subsetting.dem.output_dir is "dem"

<output_dir>/
  <gage_id>_<run_name>/
    configs/
      realization_*.json
      ngen-cal_calib_config.yaml
      ngen-cal_valid_config.yaml
      troute_config.yaml
      <model_instance_name>/
        <model_config_files>
    output_*/
    output_sim_obs/
    pso_global_best/
```

## Flat Layout

The `flat` layout organizes reusable resources by resource type:

```text
<input_dir>/
  hydrofabric/
    gage_<gage_id>.gpkg
    gage_<another_gage_id>.gpkg
  forcing/
    <gage_id>/
      <start_year>_to_<end_year>/
        <forcing>.nc
        <forcing>_rechunked.nc
  dem/
    <gage_id>/  # optional; retained when subsetting.dem.output_dir is "dem"
      <dem_files>
    <another_gage_id>/
      <dem_files>
```

This is useful when users prefer to manage resources by data type first. The
gage ID remains distinguishable because each geopackage filename contains
`gage_<gage_id>`.

In this layout, `<input_dir>` is best understood as a reusable resource
directory. It contains data that can be shared across many formulations and
many runs for the same basin, such as hydrofabric geopackages and forcing
files.

`<output_dir>` is best understood as a run artifact directory. It contains
generated realization files, model configuration files, calibration files,
ngen outputs, validation outputs, and plugin outputs. These files usually
depend on the selected formulation, model instances, calibration settings, and
simulation period.

The `configs/` directory contains all generated configuration needed for a
specific run. This includes the ngen realization file, ngen-cal calibration or
validation files, routing configuration, and per-model configuration
directories for every model instance in the formulation. For example, a
formulation with `NoahOWP`, `CFE-X`, and `T-ROUTE` may generate:

```text
configs/
  realization_nom_cfe_t-route.json
  ngen-cal_calib_config.yaml
  troute_config.yaml
  noahowp/
    noahowp_cfg_cat-*.input
    parameters/
  cfe-x/
    cfe_cfg_cat-*.txt
```

## Why Basin First?

Sandbox follows a basin-first layout by default because several workflow steps
operate on one basin at a time:

```text
<gage_id>/hydrofabric/gage_<gage_id>.gpkg
<gage_id>/forcing/<start_year>_to_<end_year>/*.nc
```

Older Sandbox runs may have written geopackages under
`<gage_id>/data/gage_<gage_id>.gpkg` and forcing under
`<gage_id>/data/forcing/<start_year>_to_<end_year>`. The Python workflow can
still read legacy `data/*.gpkg` files during the transition.

The practical goal is that a user can download or prepare hydrofabric and
forcing once, then reuse those resources for many model formulations and
calibration experiments.

## Why `input_dir` And `output_dir`?

The names `input_dir` and `output_dir` are from the perspective of running
hydrologic formulations:

- `input_dir`: reusable hydrologic resources used by model runs
- `output_dir`: generated configuration files and model/run outputs

The names can feel context-dependent because each workflow step has its own
inputs and outputs. For example:

| Step | Consumes | Produces |
|---|---|---|
| `sandbox --subset` | gage IDs, source hydrofabric | basin geopackage |
| `sandbox --forc` | basin geopackage | forcing NetCDF or CSV |
| `sandbox --conf` | basin geopackage, forcing, config files | realization and model config files |
| `sandbox --run` | basin resources and generated configs | model and calibration outputs |

So a forcing file is an output of `sandbox --forc`, but it becomes a reusable
input/resource for `sandbox --conf` and `sandbox --run`.

## What Can Be Customized Today?

The default layout is convenient, but not every path is fixed.

Hydrofabric sources can be selected with:

```yaml
subsetting:
  gages:
    option: gpkg
    gpkg:
      dir: "/path/to/gpkgs"
      pattern: "gage_"
      select: ["50147800"]
```

Forcing can be pointed at an explicit directory or file:

```yaml
forcings:
  format: ".nc"
  forcing_dir: "/path/to/forcing/50147800/2016_to_2021"
```

or, for multiple basins:

```yaml
forcings:
  format: ".nc"
  forcing_dir: "/path/to/resources/{*}/forcing/2016_to_2021"
```

The `{*}` placeholder is replaced by each selected basin directory name.

Observation paths can use placeholders:

```yaml
observations:
  streamflow:
    path: "/path/to/streamflow/gage_{gage_id}_hourly_{variable}.csv"
```

## Common Alternatives

Some users prefer organizing by data type first:

```text
project/
  hydrofabric/
    50147800/
      gage_50147800.gpkg
  forcing/
    50147800/
      2016_to_2021/
        forcing.nc
  simulations/
    50147800_basecase/
```

This can work when the relevant config paths point Sandbox to those locations.
The current workflow is most automatic when basin resources follow the default
`input_dir/<gage_id>/hydrofabric` and `input_dir/<gage_id>/forcing` structure.
During the transition, the Python workflow can still read geopackages from
the older `input_dir/<gage_id>/data` structure and from flat
`input_dir/hydrofabric/gage_<gage_id>.gpkg` files.

## Recommended Mental Model

Think of the directories as:

```text
resources_dir = reusable basin resources
runs_dir      = generated run artifacts
```

Today, these correspond to:

```yaml
general:
  input_dir: "<resources_dir>"
  output_dir: "<runs_dir>"
```

Future refactors may add clearer aliases or more explicit path templates, but
the current layout is designed to protect reusable resources from generated
run artifacts. In practice, this means users can delete a run directory under
`output_dir` and rerun a formulation without deleting hydrofabric or forcing
files that may be expensive to regenerate.
