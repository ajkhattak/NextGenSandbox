#!/usr/bin/env bash
set -euo pipefail

find_conda_exe() {
  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return
  fi

  if [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then
    printf "%s\n" "$CONDA_EXE"
    return
  fi

  cat >&2 <<'EOF'
ERROR: conda was not found in PATH, and CONDA_EXE is not set.

Load the conda module first, for example:
  module load conda

If a conda environment is already active, make sure CONDA_EXE is set:
  echo "$CONDA_EXE"
EOF
  exit 127
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

CONDA_EXE_PATH="$(find_conda_exe)"

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

eval "$("$CONDA_EXE_PATH" shell.bash hook)"

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

SUBSET_ENV="${SANDBOX_BUILD_DIR}/rvenv/venv_subset"
SUBSET_RSCRIPT="${SUBSET_ENV}/bin/Rscript"
CONDA_SUBDIR="$(conda info | awk -F: '/platform/{gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2; exit}')"
LOCKFILE="${SANDBOX_DIR}/utils/venv/venv_subset.${CONDA_SUBDIR}.lock"
LEGACY_LOCKFILE="${SANDBOX_DIR}/utils/venv/venv_subset.lock"

lockfile_matches_platform() {
  local lockfile="$1"
  grep -q "^# platform: ${CONDA_SUBDIR}$" "$lockfile"
}

if [ -d "$SUBSET_ENV" ] && [ ! -x "$SUBSET_RSCRIPT" ]; then
  cat >&2 <<EOF
ERROR: Existing subset environment is incomplete: $SUBSET_ENV

The directory exists, but Rscript was not found at:
  $SUBSET_RSCRIPT

This usually happens after a failed conda/mamba solve or a disk-quota
interruption. Remove the incomplete subset environment and rerun:

  conda env remove -p "$SUBSET_ENV"
  ./bootstrap.sh --subset

If conda cannot remove it, delete only this incomplete build artifact:
  rm -rf "$SUBSET_ENV"
EOF
  exit 3
fi

if [ ! -x "$SUBSET_RSCRIPT" ]; then
  # Use lockfile if available (fast), otherwise solve from YAML (slow, first time)
  if [ -f "$LOCKFILE" ]; then
    echo "Using lockfile for ${CONDA_SUBDIR} — skipping solver"
    conda create -y -p "$SUBSET_ENV" --file "$LOCKFILE"
  elif [ -f "$LEGACY_LOCKFILE" ] && lockfile_matches_platform "$LEGACY_LOCKFILE"; then
    echo "Using legacy lockfile for ${CONDA_SUBDIR} — skipping solver"
    conda create -y -p "$SUBSET_ENV" --file "$LEGACY_LOCKFILE"
  else
    echo "No lockfile found — solving from YAML (this will be slow once)"
    mamba env create -y -p "$SUBSET_ENV" \
      -f "${SANDBOX_DIR}/utils/venv/venv_subset.yaml"
    # Save lockfile for next time
    conda list -p "$SUBSET_ENV" --explicit > "$LOCKFILE"
  fi
fi

set +u; mamba activate "$SUBSET_ENV"; set -u

"$SUBSET_RSCRIPT" "${SANDBOX_DIR}/src/R/install_load_libs.R" --install
echo "Environment setup complete."
