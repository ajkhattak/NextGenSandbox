#!/usr/bin/env bash

set -euo pipefail


# ============================================================
# Internal Slurm coordinator submitted by `sandbox-launcher submit`.
# ============================================================

# -------------------------------
# SLURM DIRECTIVES (ignored locally)
# -------------------------------
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:10:00
#SBATCH --job-name=sandbox_launcher
#SBATCH --mem=2G


# ============================================================
# Detect execution environment
# ============================================================

if [ -z "${SLURM_JOB_ID:-}" ]; then
    echo "ERROR: This internal coordinator must be submitted by sandbox-launcher submit."
    echo "For local execution, use: sandbox-launcher run --backend local --config <file>"
    exit 1
fi
if [ -z "${LAUNCHER_CONFIG:-}" ]; then
    echo "ERROR: LAUNCHER_CONFIG was not provided by sandbox-launcher submit."
    exit 1
fi
RUN_ENV="slurm"
CONFIG_FILE="$LAUNCHER_CONFIG"

echo "==============================================="
echo " Sandbox Launcher Entry Script"
echo " Environment: $RUN_ENV"
echo " Host: $(hostname)"
echo " Time: $(date)"
echo " Launcher config: $CONFIG_FILE"
echo "==============================================="

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Launcher config file does not exist: $CONFIG_FILE"
    exit 1
fi

# ============================================================
# Configure Python Environment
# ============================================================

unset PYTHONPATH

if [ -z "${SANDBOX_ENV:-}" ]; then
    echo "ERROR: SANDBOX_ENV is not set. Run ./bootstrap.sh --env and reload your shell before launching."
    exit 1
fi

SANDBOX_PYTHON="$SANDBOX_ENV/bin/python"
SANDBOX_COMMAND="$SANDBOX_ENV/bin/sandbox"
SANDBOX_LAUNCHER="$SANDBOX_ENV/bin/sandbox-launcher"
if [ ! -x "$SANDBOX_PYTHON" ] || [ ! -x "$SANDBOX_COMMAND" ] || [ ! -x "$SANDBOX_LAUNCHER" ]; then
    echo "ERROR: The Sandbox environment is incomplete: $SANDBOX_ENV"
    echo "Expected executable files:"
    echo "  $SANDBOX_PYTHON"
    echo "  $SANDBOX_COMMAND"
    echo "  $SANDBOX_LAUNCHER"
    echo "Run ./bootstrap.sh --sandbox to build it."
    exit 1
fi

# Conda environments do not necessarily provide bin/activate. Using the
# environment executables directly works for both Conda and Python venv builds.
export PATH="$SANDBOX_ENV/bin:$PATH"

echo "Python executable: $SANDBOX_PYTHON"


# ============================================================
# Run Python Launcher
# ============================================================

echo "[submit_launcher] Running in SLURM mode"
"$SANDBOX_LAUNCHER" run --backend slurm --config "$CONFIG_FILE"

echo "[submit_launcher] Coordinator cycle completed"
