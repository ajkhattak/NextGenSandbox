#!/usr/bin/env bash
# Slurm template:
# Uncomment and edit these lines if submitting this helper directly with sbatch,
# for example:
#   sbatch tools/batch/run_sandbox_resources_parallel.sh \
#     --step forc --config configs/sandbox_config1.yaml --jobs 4
#
# #SBATCH --job-name=sandbox_resources
# #SBATCH --time=06:00:00
# #SBATCH --cpus-per-task=4
# #SBATCH --mem=16G
# #SBATCH --output=logs/sandbox_resources_%j.out
# #SBATCH --error=logs/sandbox_resources_%j.err

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python "${SCRIPT_DIR}/run_sandbox_resources_parallel.py" "$@"
