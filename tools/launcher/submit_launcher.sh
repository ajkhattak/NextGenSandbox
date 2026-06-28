#!/bin/bash


# ============================================================
# Universal Sandbox Launcher Entry Script
# Works on:
#   - SLURM HPC (via sbatch)
#   - Local laptop (via bash)
# ============================================================

# -------------------------------
# SLURM DIRECTIVES (ignored locally)
# -------------------------------
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:05:00
#SBATCH --job-name=sandbox_launcher
#SBATCH --account=ohd
#SBATCH --error=log/launcher_%j.err
#SBATCH --output=log/launcher_%j.out
##SBATCH --partition=ursa
#SBATCH --mem=2G
#SBATCH --requeue
##SBATCH --exclusive


# ============================================================
# Detect execution environment
# ============================================================

if [ -n "$SLURM_JOB_ID" ]; then
    RUN_ENV="slurm"
else
    RUN_ENV="local"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${LAUNCHER_CONFIG:-$SCRIPT_DIR/launcher_config.yaml}"
mkdir -p "$SCRIPT_DIR/log"

echo "==============================================="
echo " Sandbox Launcher Entry Script"
echo " Environment: $RUN_ENV"
echo " Host: $(hostname)"
echo " Time: $(date)"
echo " Launcher config: $CONFIG_FILE"
echo "==============================================="

# ============================================================
# Activate Python Environment -- MODIFY ME
# ============================================================

# --- HPC environment ---
if [ "$RUN_ENV" = "slurm" ]; then
    unset PYTHONPATH
    if [ -z "$SANDBOX_ENV" ]; then
        echo "ERROR: SANDBOX_ENV is not set. Run ./bootstrap.sh --env and reload your shell before submitting."
        exit 1
    fi
    source "$SANDBOX_ENV/bin/activate"
else
    if [ -z "$SANDBOX_ENV" ]; then
        echo "ERROR: SANDBOX_ENV is not set. Run ./bootstrap.sh --env and reload your shell before submitting."
        exit 1
    fi
    source "$SANDBOX_ENV/bin/activate"
fi

echo "Python executable: $(which python)"


# ============================================================
# SLURM Wallclock Handling (HPC only) - MODIFY ME
# ============================================================

if [ "$RUN_ENV" = "slurm" ]; then

    # Set wallclock in seconds (MUST match SBATCH time above)
    SLURM_TIMELIMIT=$((5*60))

    if [ -z "$SLURM_TIMELIMIT" ]; then
        echo "ERROR: SLURM_TIMELIMIT is not set."
        exit 1
    fi

    export LAUNCHER_WALLCLOCK=$SLURM_TIMELIMIT
    export LAUNCHER_WALLCLOCK_MIN=$(( LAUNCHER_WALLCLOCK / 60 ))

    echo "Launcher wallclock (minutes): $LAUNCHER_WALLCLOCK_MIN"

fi


# ============================================================
# Run Python Launcher
# ============================================================

if [ "$RUN_ENV" = "slurm" ]; then
    echo "[submit_launcher] Running in SLURM mode"
    python "$SCRIPT_DIR/sandbox_launcher.py" run --backend slurm --config "$CONFIG_FILE"
else
    echo "[submit_launcher] Running in LOCAL mode"
    python "$SCRIPT_DIR/sandbox_launcher.py" run --backend local --config "$CONFIG_FILE"
fi

exit_code=$?

echo "[submit_launcher] Python exit code = $exit_code"


# ============================================================
# SLURM Requeue Handling
# 99 means: "requeue me, work still incomplete"
# ============================================================

if [ "$RUN_ENV" = "slurm" ]; then
    if [ $exit_code -eq 99 ]; then
        echo "[submit_launcher] Requeue requested — requeueing job"
        scontrol requeue $SLURM_JOB_ID
        exit 0
    fi
fi

echo "[submit_launcher] Completed"
exit $exit_code

# ----------------------------------------------------


# Debug info
#echo "LL Python executable: $(which python)"
#python -c "import numpy; print('LL NumPy version:', numpy.__version__)"
#python -c "import sqlite3; print('LL sqlite3 version:', sqlite3.sqlite_version)"
