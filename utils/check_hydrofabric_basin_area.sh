#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<EOF
Usage:
  $0 --input <gpkg-file-directory-or-glob> [--output-dir <directory>]
     [extra Python options]

Required wrapper option:
  --input PATH
      Source GeoPackage, directory searched recursively, or quoted glob.

Optional wrapper option:
  --output-dir DIR
      Destination for all audits, corrected GeoPackages, rejected
      GeoPackages, and figures. Default: basin_area_check

Checks hydrofabric area against NLDI and NWIS, cleans NLDI-external divides,
and writes an attention-only PDF report. Original GeoPackages are unchanged.
The cleaned_hydrofabric directory contains accepted basins only and is safe
for downstream globbing. Rejected outputs are quarantined separately.
selected_gages.csv uses the shared calibration schema:
STAID, STANAME, DRAIN_SQKM.

Area-classification defaults:
  --hf-nldi-threshold-pct 5
  --clean-threshold-pct 10
  --threshold-pct 20
  --hf-nwis-fallback-threshold-pct 10
      If NLDI differs from NWIS by more than 20%, but hydrofabric and NWIS
      agree within 10%, accept the basin as HF_NWIS_AGREEMENT_NLDI_OUTLIER.

Cleanup defaults:
  --delete-outside-fraction-pct 50
      A partially overlapping divide is eligible when at least 50% is outside.
  --minimum-outside-area-sqkm 0.1
      Partially overlapping divides must also have at least 0.1 km² outside.
      Divides that are effectively 100% outside are always removed, including
      very small connector divides below 0.1 km².

Examples:
  $0 --input /path/to/inputs --output-dir basin_area_check
  $0 --input '/path/to/inputs/*/hydrofabric' --output-dir basin_area_check --nldi-workers 2
  $0 --input /path/to/inputs --output-dir basin_area_check --overwrite-cleaned-gpkg

Use --overwrite-cleaned-gpkg when rerunning into an output directory that
already contains cleaned GeoPackages. Additional options override the wrapper
defaults because they are passed last. Run the Python utility with --help for
the complete option list.
EOF
}

input_pattern=""
output_dir=basin_area_check
python_options=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input)
            if [[ $# -lt 2 || $2 == --* ]]; then
                echo "ERROR: --input requires a path, directory, or glob." >&2
                exit 2
            fi
            input_pattern=$2
            shift 2
            ;;
        --output-dir)
            if [[ $# -lt 2 || $2 == --* ]]; then
                echo "ERROR: --output-dir requires a directory." >&2
                exit 2
            fi
            output_dir=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            python_options+=("$@")
            break
            ;;
        *)
            python_options+=("$1")
            shift
            ;;
    esac
done

if [[ -z $input_pattern ]]; then
    echo "ERROR: --input is required." >&2
    usage >&2
    exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "${output_dir}"
output_dir=$(cd -- "${output_dir}" && pwd)

echo "Hydrofabric source : ${input_pattern}"
echo "Results directory  : ${output_dir}"

python -u "${script_dir}/python/check_hydrofabric_basin_area.py" \
    "${input_pattern}" \
    --hf-nldi-threshold-pct 5 \
    --clean-threshold-pct 10 \
    --threshold-pct 20 \
    --hf-nwis-fallback-threshold-pct 10 \
    --output-csv "${output_dir}/basin_area_comparison.csv" \
    --passed-csv "${output_dir}/selected_gages.csv" \
    --cleaned-gpkg-dir "${output_dir}/cleaned_hydrofabric" \
    --rejected-gpkg-dir "${output_dir}/rejected_hydrofabric" \
    --delete-outside-fraction-pct 50 \
    --minimum-outside-area-sqkm 0.1 \
    --nldi-workers 8 \
    --figure-dir "${output_dir}/figures" \
    --figure-format pdf \
    --figure-scope attention \
    "${python_options[@]}"
