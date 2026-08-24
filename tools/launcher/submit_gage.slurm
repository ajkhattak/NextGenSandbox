#!/bin/bash
set -euo pipefail

#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --time=00:04:00
#SBATCH --job-name=gage
#SBATCH --account=ohd
#SBATCH --error=log/gage_%j.err
#SBATCH --output=log/gage_%j.out
##SBATCH --partition=ursa
#SBATCH --mem=16G
##SBATCH --exclusive

##SBATCH --cpus-per-task=1

echo "Allocated MPI tasks: ${SLURM_NTASKS:-1}"
echo "CPUs per task: ${SLURM_CPUS_PER_TASK:-1}"
# === Load modules or activate your environment ===

module load openmpi/4.1.6
module load netcdf-fortran/4.6.1
module load cmake/3.30.2
module load sqlite
module load udunits

unset PYTHONPATH
if [ -z "${SANDBOX_ENV:-}" ]; then
    echo "ERROR: SANDBOX_ENV is not set. Run ./bootstrap.sh --env and reload your shell before submitting."
    exit 1
fi

SANDBOX_PYTHON="$SANDBOX_ENV/bin/python"
SANDBOX_COMMAND="$SANDBOX_ENV/bin/sandbox"
if [ ! -x "$SANDBOX_PYTHON" ] || [ ! -x "$SANDBOX_COMMAND" ]; then
    echo "ERROR: The Sandbox environment is incomplete: $SANDBOX_ENV"
    echo "Run ./bootstrap.sh --sandbox to build it."
    exit 1
fi
export PATH="$SANDBOX_ENV/bin:$PATH"

if [ -z "${SANDBOX_FILE:-}" ]; then
    echo "ERROR: SANDBOX_FILE must be exported by the launcher."
    exit 1
fi
if [[ "${SANDBOX_STAGE:-}" != "calibration" && "${SANDBOX_STAGE:-}" != "validation" ]]; then
    echo "ERROR: SANDBOX_STAGE must be calibration or validation."
    exit 1
fi

# Debug info
echo "Python executable: $SANDBOX_PYTHON"
"$SANDBOX_PYTHON" -c "import sqlite3; print('sqlite3 version:', sqlite3.sqlite_version)"

echo "Running gage simulation..."
echo "SANDBOX_FILE = $SANDBOX_FILE"
echo "SANDBOX_STAGE = $SANDBOX_STAGE"

# Delay start based on model index (passed from Python)
if [[ -n "${START_DELAY:-}" ]]; then
    echo "Applying model-index startup delay: ${START_DELAY}s"
    sleep "$START_DELAY"
fi
# === Run sandbox ===
if [ "$SANDBOX_STAGE" = "validation" ]; then
    echo "Generating validation configuration files..."
    "$SANDBOX_COMMAND" --conf -i "$SANDBOX_FILE"
fi
"$SANDBOX_COMMAND" --run -i "$SANDBOX_FILE"
