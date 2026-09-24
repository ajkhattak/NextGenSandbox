#!/usr/bin/env bash

# NextGenSandbox build and runtime profile.
# Copy this file, customize it when needed, and source it in Bash or zsh:
#   cp configs/sandbox_profile.sh sandbox_profile.sh
#   source ./sandbox_profile.sh

if [ -n "${BASH_VERSION:-}" ]; then
    if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
        echo "ERROR: Source this profile instead of executing it:"
        echo "  source ${BASH_SOURCE[0]}"
        exit 1
    fi
    PROFILE_SOURCE="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
    if [[ "${ZSH_EVAL_CONTEXT:-}" != *:file ]]; then
        echo "ERROR: Source this profile instead of executing it:"
        echo "  source $0"
        exit 1
    fi
    PROFILE_SOURCE="${(%):-%N}"
else
    echo "ERROR: NextGenSandbox profiles support Bash and zsh."
    return 1
fi

PROFILE_DIR="$(cd "$(dirname "$PROFILE_SOURCE")" && pwd -P)"
SANDBOX_PROFILE="$PROFILE_DIR/$(basename "$PROFILE_SOURCE")"

# Profiles kept in the repository root or its configs directory locate the
# checkout automatically. A profile stored elsewhere must set SANDBOX_REPO.
# SANDBOX_REPO="/path/to/NextGenSandbox"
if [ -f "$PROFILE_DIR/scripts/bootstrap/sandbox_env.sh" ]; then
    SANDBOX_REPO="$PROFILE_DIR"
elif [ -f "$PROFILE_DIR/../scripts/bootstrap/sandbox_env.sh" ]; then
    SANDBOX_REPO="$(cd "$PROFILE_DIR/.." && pwd -P)"
else
    SANDBOX_REPO="${SANDBOX_REPO:-}"
fi

if [ ! -f "$SANDBOX_REPO/scripts/bootstrap/sandbox_env.sh" ]; then
    echo "ERROR: NextGenSandbox was not found at: $SANDBOX_REPO"
    echo "Set SANDBOX_REPO in $SANDBOX_PROFILE to the repository path."
    return 1
fi

# Customize this section for the compiler/MPI stack on the current system.
# GCC with a GCC-built OpenMPI is the recommended HPC starting point. Load
# NetCDF and other compiled libraries built with the same compiler family.
# Keep every compiler-dependent build in its own directory.
#
# module --force purge
# module load gcc/<version>
# module load openmpi/<version-built-with-gcc>
# module load sqlite/3.35.5
# module load udunits/2.2.28
# module load cmake/3.20.0
# module load netcdf-fortran/<version-built-with-gcc>
# module load conda/2026.03
#
# export SANDBOX_BUILD_DIR="$SANDBOX_REPO/build/gcc"
# export SANDBOX_BUILD_JOBS=2
# export NETCDF_ROOT="$(nf-config --prefix)"
# export BOOST_ROOT="/path/to/boost"
#
# Intel builds are optional. Use a separate profile and build directory, and
# load Intel-built MPI, NetCDF, and supporting libraries consistently:
#   module load intel/<version>
#   module load openmpi/<version-built-with-intel>
#   export SANDBOX_BUILD_DIR="$SANDBOX_REPO/build/intel"

# Use the loaded MPI wrappers by default, replacing unrelated compiler values
# inherited from the parent shell.
if command -v mpicc >/dev/null 2>&1; then
    export CC="$(command -v mpicc)"
fi
if command -v mpicxx >/dev/null 2>&1; then
    export CXX="$(command -v mpicxx)"
elif command -v mpic++ >/dev/null 2>&1; then
    export CXX="$(command -v mpic++)"
fi
if command -v mpifort >/dev/null 2>&1; then
    export FC="$(command -v mpifort)"
elif command -v mpif90 >/dev/null 2>&1; then
    export FC="$(command -v mpif90)"
fi
if [ -n "${FC:-}" ]; then
    export F90="$FC"
    export F77="$FC"
fi
if [ -z "${NETCDF_ROOT:-}" ] && command -v nf-config >/dev/null 2>&1; then
    export NETCDF_ROOT="$(nf-config --prefix)"
fi

# Optional compiler overrides belong after the defaults above.
# export CC="/path/to/compiler"
# export CXX="/path/to/compiler"
# export FC="/path/to/compiler"
# export F90="$FC"
# export F77="$FC"

export SANDBOX_REPO
export SANDBOX_PROFILE
export SANDBOX_BUILD_DIR="${SANDBOX_BUILD_DIR:-$SANDBOX_REPO/build}"
export SANDBOX_BUILD_JOBS="${SANDBOX_BUILD_JOBS:-2}"
export SANDBOX_CONDARC="$SANDBOX_BUILD_DIR/condarc"

# Load repository paths for this shell/job only. Shell startup files are never
# modified.
source "$SANDBOX_REPO/scripts/bootstrap/sandbox_env.sh"

# Show the active Conda environment in the shell prompt by default. Set
# CONDA_CHANGEPS1=false before sourcing this profile to keep the prompt unchanged.
export CONDA_CHANGEPS1="${CONDA_CHANGEPS1:-true}"
# Display only the environment directory name for path-based environments.
export CONDA_ENV_PROMPT='({name}) '

if [ -x "$SANDBOX_ENV/bin/python" ]; then
    if [ -d "$SANDBOX_ENV/conda-meta" ]; then
        if command -v conda >/dev/null 2>&1; then
            CONDA_COMMAND="conda"
        elif [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then
            CONDA_COMMAND="$CONDA_EXE"
        else
            echo "ERROR: $SANDBOX_ENV is a Conda environment, but conda is unavailable."
            echo "Load or install conda, then source this profile again."
            return 1
        fi

        CONDA_BASE="$("$CONDA_COMMAND" info --base)"
        if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
            source "$CONDA_BASE/etc/profile.d/conda.sh"
        fi
        conda activate "$SANDBOX_ENV"
    elif [ -f "$SANDBOX_ENV/bin/activate" ]; then
        source "$SANDBOX_ENV/bin/activate"
    else
        echo "ERROR: Cannot activate the Sandbox environment: $SANDBOX_ENV"
        return 1
    fi
else
    echo "Sandbox environment has not been built for this profile."
    echo "  Run: $SANDBOX_REPO/bootstrap.sh --sandbox"
fi

# Linux executables built against the Sandbox Python environment need its
# shared libraries when launched directly or through mpirun. Retain the MPI,
# NetCDF, and compiler library paths supplied by the loaded modules.
if [ "$(uname -s)" = "Linux" ] && [ -d "$SANDBOX_ENV/lib" ]; then
    case ":${LD_LIBRARY_PATH:-}:" in
        *":$SANDBOX_ENV/lib:"*) ;;
        *) export LD_LIBRARY_PATH="$SANDBOX_ENV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
    esac

    if [ -f "$SANDBOX_ENV/lib/libstdc++.so.6" ]; then
        case ":${LIBRARY_PATH:-}:" in
            *":$SANDBOX_ENV/lib:"*) ;;
            *) export LIBRARY_PATH="$SANDBOX_ENV/lib${LIBRARY_PATH:+:$LIBRARY_PATH}" ;;
        esac

        case ":${LD_PRELOAD:-}:" in
            *":$SANDBOX_ENV/lib/libstdc++.so.6:"*) ;;
            *) export LD_PRELOAD="$SANDBOX_ENV/lib/libstdc++.so.6${LD_PRELOAD:+:$LD_PRELOAD}" ;;
        esac
    fi
fi

case ":$PATH:" in
    *":$SANDBOX_ENV/bin:"*) ;;
    *) export PATH="$SANDBOX_ENV/bin:$PATH" ;;
esac
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

echo "NextGenSandbox profile loaded."
echo "  Repository : $SANDBOX_DIR"
echo "  Build      : $SANDBOX_BUILD_DIR"
echo "  Build jobs : $SANDBOX_BUILD_JOBS"
echo "  Environment: $SANDBOX_ENV"
