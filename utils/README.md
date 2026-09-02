# NextGenSandbox Utilities

This directory contains user-facing data utilities and internal scripts used by
`bootstrap.sh`. Most installation and build scripts here are implementation
details of the bootstrap workflow and do not need to be run directly.

## Check and Correct Hydrofabric Areas

`check_hydrofabric_basin_area.sh` is the primary user-facing shell utility. It
compares each subset GeoPackage with NLDI and documented USGS drainage areas,
removes safely identifiable divides outside the NLDI boundary, and separates
accepted and rejected GeoPackages.

Run it from the repository root:

```bash
bash utils/check_hydrofabric_basin_area.sh \
  --input /path/to/source/geopackages \
  --output-dir /path/to/basin_area_check
```

`--input` identifies the source GeoPackage, directory searched recursively, or
quoted glob. `--output-dir` identifies where every generated result will be
written and defaults to `basin_area_check` when omitted.

The output directory contains:

- `basin_area_comparison.csv`: complete area and classification audit.
- `selected_gages.csv`: accepted gages using `STAID`, `STANAME`, and
  `DRAIN_SQKM` columns.
- `removed_divides.csv`: divides removed during correction.
- `rejected_gages.csv`: rejected gages and cleanup errors.
- `cleaned_hydrofabric/`: corrected, accepted GeoPackages suitable for Sandbox
  workflows.
- `rejected_hydrofabric/`: successfully processed but rejected GeoPackages.
- `figures/basin_boundary_comparisons.pdf`: attention-focused comparison
  report.

Source GeoPackages are never modified. To intentionally replace existing files
under `cleaned_hydrofabric/`, run:

```bash
bash utils/check_hydrofabric_basin_area.sh \
  --input /path/to/source/geopackages \
  --output-dir /path/to/basin_area_check \
  --overwrite-cleaned-gpkg
```

See the [hydrofabric verification section](../docs/workflow.md#prepare-the-hydrofabric)
for classifications, thresholds, and cleanup behavior. Run
`bash utils/check_hydrofabric_basin_area.sh --help` for the wrapper defaults.

## Optional Data Utilities

The scripts under `utils/python/` support optional data preparation tasks such
as downloading USGS streamflow or OpenET data and rechunking forcing files.
These are independent utilities rather than required installation steps. Run a
script with `--help` to see its inputs and options.

## Environment Helpers

`sandbox_env.sh` is sourced by users, Slurm jobs, and `bootstrap.sh` to expose
the configured Sandbox paths. `setup_hpc.sh` and `setup_ec2.sh` are optional
platform setup templates that users may adapt for their systems.

Bootstrap implementation scripts and environment definitions live under
[`scripts/bootstrap/`](../scripts/bootstrap/). Use the documented
`./bootstrap.sh` options instead of invoking those internal scripts directly.
