#!/usr/bin/env bash
# Submit with:
#   mkdir -p logs
#   sbatch tools/batch/run_sandbox_resources_parallel.sh
#
# Override defaults with:
#   sbatch tools/batch/run_sandbox_resources_parallel.sh \
#     --step subset --config configs/my_sandbox_config.yaml --jobs 3
#
# Run without Slurm, for example on macOS:
#   tools/batch/run_sandbox_resources_parallel.sh \
#     --step forc --config configs/sandbox_config1.yaml --jobs 2

#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=3
#SBATCH --time=02:00:00
#SBATCH --job-name=sandbox_resources
#SBATCH --error=logs/forcing_%j.err
#SBATCH --output=logs/forcing_%j.out
# Uncomment and set these if your HPC requires them:
##SBATCH --account=<account>
##SBATCH --partition=<partition>
#SBATCH --mem=64G
##SBATCH --exclusive

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${SANDBOX_ENV:-}" && -f "${SANDBOX_ENV}/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${SANDBOX_ENV}/bin/activate"
fi

if [[ $# -eq 0 ]]; then
  set -- \
    --step forc \
    --config configs/sandbox_config1.yaml \
    --jobs "${SLURM_CPUS_PER_TASK:-3}"
fi

exec python "${SCRIPT_DIR}/run_sandbox_resources_parallel.py" "$@"
