#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 '<gpkg-file-directory-or-glob>' [output-directory] [extra options]" >&2
    exit 2
fi

input_pattern=$1
output_dir=${2:-basin_area_check}
if [[ $# -ge 2 ]]; then
    shift 2
else
    shift 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "${output_dir}"

python "${script_dir}/python/check_hydrofabric_basin_area.py" \
    "${input_pattern}" \
    --hf-nldi-threshold-pct 5 \
    --clean-threshold-pct 10 \
    --threshold-pct 20 \
    --output-csv "${output_dir}/basin_area_comparison.csv" \
    --passed-csv "${output_dir}/selected_gages.csv" \
    --cleaned-gpkg-dir "${output_dir}/cleaned_hydrofabric" \
    --delete-outside-fraction-pct 50 \
    --minimum-outside-area-sqkm 0.1 \
    --figure-dir "${output_dir}/figures" \
    --figure-format pdf \
    "$@"
