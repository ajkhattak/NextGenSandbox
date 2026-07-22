#!/usr/bin/env bash
set -euo pipefail

require_command() {
  local cmd="$1"
  local hint="$2"

  if ! command -v "$cmd" >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: '$cmd' was not found in PATH.

$hint
EOF
    exit 127
  fi
}

on_error() {
  local status="$?"
  cat >&2 <<EOF

Subset environment setup failed.

Common causes on HPC systems:
  - conda is provided by a module that is not loaded in this shell
  - the home-directory conda cache is full or over quota
  - a previous failed conda/mamba solve left partial packages in ~/.conda/pkgs

This script sets conda package and environment caches under:
  $SANDBOX_BUILD_DIR/rvenv/conda_pkgs
  $SANDBOX_BUILD_DIR/rvenv/conda_envs

If the error mentions ~/.conda/pkgs or "Disk quota exceeded", clean the user's
home conda cache or set SANDBOX_BUILD_DIR to a project/scratch location with
enough space, then rerun:
  ./bootstrap.sh --subset
EOF
  exit "$status"
}

trap on_error ERR

require_command conda "Load the conda module first, for example: module load conda"

if [ -z "${SANDBOX_BUILD_DIR:-}" ] || [ -z "${SANDBOX_DIR:-}" ]; then
  cat >&2 <<'EOF'
ERROR: SANDBOX_DIR and SANDBOX_BUILD_DIR must be set before building subset dependencies.

Run:
  ./bootstrap.sh --env --verbose

Then reload the environment if needed and rerun:
  ./bootstrap.sh --subset
EOF
  exit 2
fi

export CONDA_NO_PLUGINS=true
#export CONDA_SOLVER=classic # required for macOS
#CONDA_SOLVER=libmamba # already the mamba default
export CONDARC="${SANDBOX_CONDARC:-$SANDBOX_BUILD_DIR/condarc}"

mkdir -p "$(dirname "$CONDARC")"
touch "$CONDARC"
mkdir -p "${SANDBOX_BUILD_DIR}/rvenv/conda_envs"
mkdir -p "${SANDBOX_BUILD_DIR}/rvenv/conda_pkgs"

export CONDA_ENVS_PATH="${SANDBOX_BUILD_DIR}/rvenv/conda_envs"
export CONDA_PKGS_DIRS="${SANDBOX_BUILD_DIR}/rvenv/conda_pkgs"
export MAMBA_ROOT_PREFIX="${SANDBOX_BUILD_DIR}/rvenv/mamba_root"

eval "$(conda shell.bash hook)"

conda config --file "$CONDARC" --remove-key channels >/dev/null 2>&1 || true
conda config --file "$CONDARC" --remove-key envs_dirs >/dev/null 2>&1 || true
conda config --file "$CONDARC" --remove-key pkgs_dirs >/dev/null 2>&1 || true
conda config --file "$CONDARC" --append channels conda-forge
conda config --file "$CONDARC" --append channels defaults
conda config --file "$CONDARC" --set channel_priority strict
conda config --file "$CONDARC" --set env_prompt '({name})'
conda config --file "$CONDARC" --set safety_checks disabled
conda config --file "$CONDARC" --append envs_dirs "${SANDBOX_BUILD_DIR}/rvenv/conda_envs"
conda config --file "$CONDARC" --append pkgs_dirs "${SANDBOX_BUILD_DIR}/rvenv/conda_pkgs"

echo "Subset conda envs : ${CONDA_ENVS_PATH}"
echo "Subset conda pkgs : ${CONDA_PKGS_DIRS}"
echo "Subset condarc    : ${CONDARC}"

if [ ! -d "${SANDBOX_BUILD_DIR}/rvenv/mamba" ]; then
  conda create -y -p "${SANDBOX_BUILD_DIR}/rvenv/mamba" -c conda-forge mamba
fi

eval "$("${SANDBOX_BUILD_DIR}/rvenv/mamba/bin/mamba" shell hook --shell bash)"
set +u; mamba activate "${SANDBOX_BUILD_DIR}/rvenv/mamba"; set -u

if [ ! -d "${SANDBOX_BUILD_DIR}/rvenv/venv_subset" ]; then
  # Use lockfile if available (fast), otherwise solve from YAML (slow, first time)
  if [ -f "${SANDBOX_DIR}/utils/venv/venv_subset.lock" ]; then
    echo "Using lockfile — skipping solver"
    conda create -y -p "${SANDBOX_BUILD_DIR}/rvenv/venv_subset" \
      --file "${SANDBOX_DIR}/utils/venv/venv_subset.lock"
  else
    echo "No lockfile found — solving from YAML (this will be slow once)"
    mamba env create -y -p "${SANDBOX_BUILD_DIR}/rvenv/venv_subset" \
      -f "${SANDBOX_DIR}/utils/venv/venv_subset.yaml"
    # Save lockfile for next time
    conda list -p "${SANDBOX_BUILD_DIR}/rvenv/venv_subset" --explicit \
      > "${SANDBOX_DIR}/utils/venv/venv_subset.lock"
  fi
fi

set +u; mamba activate "${SANDBOX_BUILD_DIR}/rvenv/venv_subset"; set -u

Rscript "${SANDBOX_DIR}/src/R/install_load_libs.R" --install
echo "Environment setup complete."
