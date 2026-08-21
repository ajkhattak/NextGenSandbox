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
  streamflow:
    layout: point
    path: "/path/to/observations/streamflow/*<gage_id>*.parquet"
    time_column: value_time
    value_column: value
    units: "m3/sec"

  ET:
    layout: lumped
    path: "/path/to/observations/ET/*<gage_id>*.parquet"
    time_column: value_time
    value_column: value
    units: "m/d"
    simulated: ACTUAL_ET
```

Multiple observation types, such as streamflow and ET, may be loaded together.
`path` supports `<gage_id>` and `<variable>` placeholders. Ordinary `*`
wildcards may be used around them to accommodate arbitrary filename prefixes
and suffixes. A wildcard path must include `<gage_id>` and must match exactly
one file for each observation variable and gage.

Observation timestamps are interpreted in UTC. Timezone-aware values are
converted to UTC, then stored without timezone metadata to match NextGen and
ngen-cal simulation timestamps. Timezone-naive values are treated as UTC.

## Layouts

`layout: point` describes one value per timestamp at a location. This is the
usual streamflow case: a time column and a value column.

`layout: lumped` describes one value per timestamp that has already been
aggregated over the basin, such as basin-average daily ET. It requires
`value_column` and does not compare columns with hydrofabric divide IDs or
perform additional area weighting.

`layout: distributed` describes one value per timestamp and sub-basin.
Distributed CSV or Parquet files may use either layout:

- Wide format: one time column and one column per sub-basin.
- Long format: provide `id_column` and `value_column` to identify the
  sub-basin and observed value columns.

Distributed observations are converted to basin-area-weighted series using
`areasqkm` from the basin geopackage.

## Objective Functions

Configure the calibration objective under `calibration.objective.function`.
Use `kge`, `nse`, or `nnse` for a single metric, or provide a metric-to-weight
mapping to construct a composite objective. Sandbox minimizes the resulting
objective value.

```yaml
calibration:
  objective:
    function:
      kge: 0.5
      q10_skill: 0.3
      q90_skill: 0.2
```

When one observation type is configured, ngen-cal receives an ordinary
datetime-indexed series. When multiple observation types are configured, the
local observation plugin returns one series indexed by `value_time` and
`variable`.

The bundled multi-variable objectives compute efficiency metrics independently
for each variable and minimize the L2 norm of their losses. `log_kge`, `fdc`,
`q10_skill`, `q90_skill`, and `nonzero_low_flow_log_mae` are
streamflow-specific; `kge`, `nse`, and `nnse` apply to every variable. Q10 is
the flow exceeded 10% of the time, and Q90 is exceeded 90% of the time. The
FDC component uses default exceedances for
both high flows `(0.01, 0.05, 0.10)` and low flows `(0.70, 0.90, 0.95)`.
`nonzero_low_flow_log_mae` evaluates mean absolute log10 error only where observed
streamflow is greater than `1e-6` and below the 30th percentile of positive
observed streamflow.

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
