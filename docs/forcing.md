# Forcing Data

NextGenSandbox prepares forcing data through the bundled
`extern/CIROH_DL_NextGen` submodule. Users should not clone or configure a
separate forcing repository for the Sandbox workflow.

The forcing step is:

```bash
sandbox --forc -i configs/sandbox_config.yaml
```

This step reads the `general.gages` project gage set, applies any
`forcings.gages` filter, and calls:

```text
extern/CIROH_DL_NextGen/forcing_prep/generate.py
```

for each selected gage. The generated forcing files are written to the
directory implied by `general.resource_layout`, unless `forcings.forcing_dir`
is provided.

## NetCDF forcing correction

After downloading NetCDF forcing, `sandbox --forc` preserves the downloaded
file and writes a corrected sibling named:

```text
<original_name>_corrected.nc
```

The correction step:

- sets the `APCP_surface` precipitation units metadata to `mm/hr`
- fills missing values in forcing variables using nearest-neighbor
  interpolation along time
- treats negative `DLWRF_surface` and `DSWRF_surface` radiation as missing and
  fills them using linear interpolation along time
- treats `TMP_2maboveground` values below 200 K as missing and fills them using
  linear interpolation along time

The original NetCDF file is not modified.

Control which file later configuration and run steps select with:

```yaml
forcings:
  format: ".nc"
  use_corrected: true
```

`use_corrected` defaults to `true`. Set it to `false` to use the original
NetCDF file. This setting controls file selection; the `--forc` step still
creates the corrected copy.

> **Important:** Using corrected forcing is recommended. The downloaded raw
> NetCDF may not declare `mm/hr` as the precipitation units. Without that
> metadata, ngen cannot convert precipitation for a model that expects
> different units. The raw file may therefore be usable only when the model
> already expects precipitation in `mm/hr`.

## NetCDF forcing rechunking

Sandbox can rechunk NetCDF forcing files before configuration generation. This
creates a sibling `*_rechunked.nc` file and points ngen to that file. The
original forcing file is left unchanged. Existing rechunked files are reused
when they are newer than the source forcing file.

```yaml
forcings:
  format: ".nc"
  use_corrected: true
  time:
    start: "2015-10-01"
    end: "2022-09-30 23:00:00"
  rechunk: true
```

With both correction and rechunking enabled, the selected file is typically:

```text
<original_name>_corrected_rechunked.nc
```

Date-only values default to `00:00:00`.

To download or prepare forcing for a subset of the project gages, set
`forcings.gages` to `all`, one gage ID, or a list of gage IDs. The full project
gage set is defined once under `general.gages`.

The standalone utility is:

```bash
python utils/python/rechunk_forcing.py -i /path/to/forcing.nc
```

Acknowledgement: the rechunking utility is adapted from Austin Raney's
approach for improving ngen forcing-read performance.

## External NetCDF forcing

For a one-gage run, `forcings.forcing_dir` may point directly to a single
NetCDF forcing file instead of a directory:

```yaml
forcings:
  format: ".nc"
  forcing_dir: "/path/to/gage_50147800_forcing.nc"
```

This is useful when a user already has one basin-specific forcing file and does
not want to place it in the default Sandbox forcing directory layout.

This mode is only valid when exactly one gage is configured for the run. If
multiple gages are selected and `forcing_dir` points to one `.nc` file, the
workflow raises an error. For multiple gages, use the default layout-derived
forcing directories or a path pattern with `<gage_id>`.

For multiple gages with forcing outside `general.input_dir`, use `<gage_id>` as
the gage placeholder. The placeholder can resolve to a directory containing one
NetCDF file:

```yaml
forcings:
  format: ".nc"
  forcing_dir: "/path/to/forcing_custom/<gage_id>"
```

or directly to one NetCDF file per gage:

```yaml
forcings:
  format: ".nc"
  forcing_dir: "/path/to/forcing_custom/<gage_id>.nc"
```

For gage `50147800`, these examples resolve to
`/path/to/forcing_custom/50147800` and
`/path/to/forcing_custom/50147800.nc`, respectively.

If `rechunk: true`, the workflow writes a sibling file named
`*_rechunked.nc`, so the forcing file's parent directory must be writable. Set
`rechunk: false` if the source forcing directory is read-only.
