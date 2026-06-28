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

echo "Allocated CPUs: $SLURM_CPUS_PER_TASK"
# === Load modules or activate your environment ===

module load openmpi/4.1.6
module load netcdf-fortran/4.6.1
module load cmake/3.30.2
module load sqlite
module load udunits

#SANDBOX_PACKAGE_PATH=$(python -c "import sandbox, os; print(os.path.dirname(sandbox.__file__))")
#source "${SANDBOX_PACKAGE_PATH}/.venv/venv_sandbox_py3.11/bin/activate"
unset PYTHONPATH
if [ -z "$SANDBOX_ENV" ]; then
    echo "ERROR: SANDBOX_ENV is not set. Run ./bootstrap.sh --env and reload your shell before submitting."
    exit 1
fi
source "$SANDBOX_ENV/bin/activate"

if [ -z "${SANDBOX_FILE:-}" ] || [ -z "${CALIB_FILE:-}" ]; then
    echo "ERROR: SANDBOX_FILE and CALIB_FILE must be exported by the launcher."
    exit 1
fi

# Debug info
echo "Python executable: $(which python)"
python -c "import sqlite3; print('sqlite3 version:', sqlite3.sqlite_version)"

echo "Running gage simulation..."
echo "SANDBOX_FILE = $SANDBOX_FILE"
echo "CALIB_FILE   = $CALIB_FILE"

# Delay start based on model index (passed from Python)
if [[ -n "$START_DELAY" ]]; then
    echo "Applying model-index startup delay: ${START_DELAY}s"
    sleep $START_DELAY
fi
# === Run sandbox ===
sandbox --run -i "$SANDBOX_FILE" -j "$CALIB_FILE"
