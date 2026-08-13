# OpenET Data

NextGenSandbox includes a utility that downloads actual evapotranspiration
(ET) from the OpenET API for the `divides` in a NextGen geopackage. It can
produce either or both of these observation-ready datasets:

- **Lumped ET:** one basin-mean value per time step.
- **Distributed ET:** one value per hydrofabric divide and time step.

## Prerequisites

Create an API key from the
[OpenET account dashboard](https://account.etdata.org), then expose it only
through the environment:

```bash
export OPENET_API_KEY="<your-api-key>"
```

Do not put the key in a Sandbox configuration file or commit it to Git.

The utility reads the geopackage `divides` layer, validates `divide_id` and
polygon geometry, and reprojects the polygons to EPSG:4326 for OpenET.

## Download ET

Download both daily lumped and divide-scale ET:

```bash
python utils/python/download_openet.py \
  --gpkg /path/to/gage_01308000.gpkg \
  --start 2016-01-01 \
  --end 2020-12-31 \
  --output-dir "$SANDBOX_DATA_DIR/openet" \
  --basin-aggregate \
  --divide-scale
```

Use only `--basin-aggregate` for a lumped series or only `--divide-scale` for
sub-basin values. The gage ID is inferred from standard geopackage filenames;
use `--gage-id` when the filename does not contain exactly one supported USGS
gage ID.

Defaults are daily OpenET Ensemble ET, the gridMET reference ET source, mean
spatial reduction, millimeters, OpenET collection version 2.1, and Parquet
output. Use `--format csv` when CSV is preferred. Run the utility with
`--help` for all options. See the [OpenET API documentation](https://openet.gitbook.io/docs)
for model, data availability, and account details.

Divide requests are split into batches of 100 polygons and daily date ranges
of no more than 366 days to respect the standard OpenET limits. OpenET account
area, polygon, request, and response-size quotas still apply.

## Outputs

The utility writes:

```text
openet_<gage_id>_lumped_daily.parquet
openet_<gage_id>_distributed_daily.parquet
openet_<gage_id>_metadata.json
```

Lumped output has `value_time` and `value` columns. Distributed output uses
wide format with `value_time` followed by one column per `divide_id`. Both
formats can be read directly by the Sandbox observation loader.

For lumped ET:

```yaml
observations:
  ET:
    layout: lumped
    path: "/path/to/openet/*<gage_id>*lumped*.parquet"
    time_column: value_time
    value_column: value
    units: "mm/d"
    simulated: ACTUAL_ET
```

For divide-scale ET, change the path and layout:

```yaml
observations:
  ET:
    layout: distributed
    path: "/path/to/openet/*<gage_id>*distributed*.parquet"
    time_column: value_time
    units: "mm/d"
    simulated: ACTUAL_ET
```

OpenET daily ET values are depths accumulated over each day, so their Sandbox
observation units are `mm/d`. The metadata file records the request settings,
source geopackage, generated files, and generation time without storing the
API key.

## Availability And Quotas

OpenET currently provides daily ET beginning in 2016 and monthly ET beginning
in 2000. Recent data may be revised as source imagery and model inputs are
updated. API account quotas limit request count, area, and polygons per
request; large or complex hydrofabrics may need a higher OpenET account tier.
