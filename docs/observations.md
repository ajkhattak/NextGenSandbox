# Observations And Objectives

This guide explains the optional `observations` block in
`configs/sandbox_config.yaml` and how local observation data are passed to
ngen-cal plugins and objective functions.

## Observation Block

The optional `observations` block configures one or more local CSV or Parquet
datasets for the selected simulation gages. During configuration generation,
the sandbox resolves file paths and validates the file schema without loading
the observation values. When local streamflow observations are not configured,
ngen-cal uses its built-in provider to download streamflow observations from
USGS.

```yaml
observations:
  objective: kge

  streamflow:
    layout: point
    path: "/path/to/observations/gage_<gage_id>_streamflow.parquet"
    time_column: value_time
    value_column: value
    units: "m3/sec"

  ET:
    layout: distributed
    path: "/path/to/observations/gage_<gage_id>_ET.parquet"
    time_column: value_time
    units: "m/d"
    simulated: ACTUAL_ET
```

Multiple observation types, such as streamflow and ET, may be loaded together.
`path` supports `<gage_id>` and `<variable>` placeholders.

## Layouts

`layout: point` describes one value per timestamp. This is the usual streamflow
case: a time column and a value column, optionally filtered by gage ID if the
file contains multiple gages.

`layout: distributed` describes one value per timestamp and sub-basin.
Distributed CSV or Parquet files may use either layout:

- Wide format: one time column and one column per sub-basin.
- Long format: provide `id_column` and `value_column` to identify the
  sub-basin and observed value columns.

Distributed observations are converted to basin-area-weighted series using
`areasqkm` from the basin geopackage.

## Objective Functions

When `observations.objective` is provided, the sandbox replaces the objective
from `configs/calib_config.yaml` with the corresponding bundled
multi-variable objective. Supported values are `kge`, `nse`, and `nnse`.
These objectives are minimized. A custom objective may also be provided using
its Python import path.

```yaml
observations:
  objective: nnse
```

When one observation type is configured, ngen-cal receives an ordinary
datetime-indexed series. When multiple observation types are configured, the
local observation plugin returns one series indexed by `value_time` and
`variable`.

The default ngen-cal objective may only be used when streamflow is the sole
configured observation type. A custom objective function import path is
required for multiple observation variables or for a single non-streamflow
variable.

The bundled multi-variable objectives compute the selected efficiency metric
independently for each variable and minimize the L2 norm of their losses. For a
metric value `E`, each variable contributes `(1 - E)^2` to the combined
objective.

For multiple observation variables, both observed and simulated series must
contain a MultiIndex level named `variable`. The objective aligns each variable
independently before computing the metric, allowing variables with different
frequencies to be evaluated safely. Ordinary Series are also supported for a
single observation variable.

## Simulated Variables

The optional `simulated` value identifies which generated simulation output
corresponds to the observation variable. Its units are defined once under
`simulation.outputs.divide_variables`. `units` describes the observed values,
while the output variable's `units` describes the raw model output before
temporal aggregation.

```yaml
simulation:
  outputs:
    divide_variables:
      ACTUAL_ET:
        units: "m/h"
      POTENTIAL_ET:
        units: "m/h"
      INFILTRATION:
        units: "m/h"
```

When `divide_variables` is non-empty, catchment output is enabled automatically
and each requested BMI variable is written to every `cat-<divide_id>.csv`
file. Units are required for every requested output variable. They are recorded
for observation matching and are not passed to ngen.

The observation plugin reads the simulated column from `cat-<divide_id>.csv`
files in the current ngen-cal worker directory using `Time` as the timestamp
column. It computes a basin-area-weighted series and resamples it to the
observed variable frequency. ET is summed when resampled; SWE is averaged.
After resampling, supported simulated units are converted to the observation
units. For example, hourly simulated ET in `m/h` may be summed and converted
for comparison with daily observed ET in `mm/d`.

## Units And Time Alignment

Streamflow observation units must be `m3/s` or `m3/sec`. The workflow accepts
either label.

`units` is required for every observation type and every
`simulation.outputs.divide_variables` entry. The observation plugin currently
converts depth units between `m`, `mm`, `m/h`, `mm/h`, `m/d`, and `mm/d`.
Unsupported or temporally incompatible unit combinations raise an error.

The plugin trims all configured observation datasets to their common time
window before combining them. The common start is the latest dataset start,
and the common end is the earliest dataset end, limited by the requested
calibration period. Datasets retain their native frequencies; the plugin does
not resample or interpolate observed values.

## Simulation-Observation Output

With calibration output retention set to `best`, the
save-simulation-observation plugin keeps two files:

- `output_sim_obs/sim_obs_0.parquet` preserves the first iteration.
- `output_sim_obs/sim_obs_best.parquet` is overwritten whenever ngen-cal
  identifies a new best iteration.

Each file has a MultiIndex named `value_time` and `variable`, with `sim_flow`
and `obs_flow` columns. It preserves each variable's native timestamps, so
unmatched timestamps remain null. Load one variable and retain only aligned
pairs with:

```python
data = pd.read_parquet("output_sim_obs/sim_obs_best.parquet")
et_pairs = data.xs("ET", level="variable").dropna()
```

With `retention: all`, divide-level outputs are stored under
`output_<iteration>`, and simulation-observation outputs are stored as
`output_sim_obs/sim_obs_<iteration>.parquet`. This can require substantial
storage for long or highly distributed calibrations.
