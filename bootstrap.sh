#!/usr/bin/env bash
#USAGE: ./bootstrap.sh --check --env --sandbox --subset --ngen --models --troute

set -e
#set -x

RUN_CHECK=OFF
SETUP_ENV=OFF
BUILD_SANDBOX=OFF
BUILD_SUBSET=OFF
BUILD_NGEN=OFF
BUILD_MODELS=OFF
BUILD_TROUTE=OFF
BUILD_CLEAN=false

COLOR_RESET=""
COLOR_GREEN=""
COLOR_YELLOW=""
COLOR_RED=""
COLOR_CYAN=""
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
    COLOR_RESET=$'\033[0m'
    COLOR_GREEN=$'\033[32m'
    COLOR_YELLOW=$'\033[33m'
    COLOR_RED=$'\033[31m'
    COLOR_CYAN=$'\033[36m'
fi

RECOMMENDED_NEXT_STEPS=()

usage() {
    cat <<'EOF'
Usage:
  ./bootstrap.sh [OPTIONS]

Common first-time sequence:
  ./bootstrap.sh --env --verbose
  ./bootstrap.sh --check
  ./bootstrap.sh --sandbox
  ./bootstrap.sh --subset
  ./bootstrap.sh --ngen --models --troute
  ./bootstrap.sh --check

Options:
  --check     Read-only diagnostic check
  --env       Configure Sandbox environment variables
  --sandbox   Build Sandbox Python and forcing environments
  --subset    Build/install R subsetting dependencies
  --ngen      Build ngen
  --models    Build model libraries
  --troute    Build/install t-route
  --clean     Clean build artifacts where supported
  --verbose   Print verbose environment setup output
  -h, --help  Show this help message
EOF
}

# Parse args
for arg in "$@"; do
    case $arg in
      -h|--help) usage; exit 0 ;;
      --check)   RUN_CHECK=ON ;;
      --env)     SETUP_ENV=ON ;;
      --sandbox) BUILD_SANDBOX=ON ;;
      --subset)  BUILD_SUBSET=ON ;;
      --ngen)    BUILD_NGEN=ON ;;
      --models)  BUILD_MODELS=ON ;;
      --troute)  BUILD_TROUTE=ON ;;
      --clean)   BUILD_CLEAN=true ;;
      --verbose) VERBOSE=ON;;
      *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

echo "========================================="
echo "Configuration:"
echo "  CHECK    : $RUN_CHECK"
echo "  ENV      : $SETUP_ENV"
echo "  SANDBOX  : $BUILD_SANDBOX"
echo "  SUBSET   : $BUILD_SUBSET"
echo "  NGEN     : $BUILD_NGEN"
echo "  MODELS   : $BUILD_MODELS"
echo "  TROUTE   : $BUILD_TROUTE"
echo "========================================="

status_ok() {
    printf "  %b%-9s%b %s\n" "$COLOR_GREEN" "[OK]" "$COLOR_RESET" "$1"
}

status_set() {
    printf "  %b%-9s%b %s\n" "$COLOR_CYAN" "[SET]" "$COLOR_RESET" "$1"
}

status_warn() {
    printf "  %b%-9s%b %s\n" "$COLOR_YELLOW" "[WARN]" "$COLOR_RESET" "$1"
}

status_fail() {
    printf "  %b%-9s%b %s\n" "$COLOR_RED" "[MISSING]" "$COLOR_RESET" "$1"
}

add_recommendation() {
    local recommendation="$1"
    local existing

    for existing in "${RECOMMENDED_NEXT_STEPS[@]}"; do
        if [ "$existing" = "$recommendation" ]; then
            return
        fi
    done
    RECOMMENDED_NEXT_STEPS+=("$recommendation")
}

recommendation_priority() {
    case "$1" in
        *"Install Python >= 3.11"*) echo 5 ;;
        *"--env"*) echo 10 ;;
        *"--sandbox"*) echo 20 ;;
        *"conda activate"*|*"bin/activate"*) echo 25 ;;
        *"--subset"*|*"Install R packages"*) echo 30 ;;
        *"--ngen"*) echo 40 ;;
        *"--models"*) echo 50 ;;
        *"--troute"*) echo 60 ;;
        *"submodule"*) echo 70 ;;
        *) echo 80 ;;
    esac
}

print_recommended_next_steps() {
    local index=1
    local recommendation
    local recommendation_order
    local priority

    echo "Recommended Next Steps"
    echo "======================"
    if [ "${#RECOMMENDED_NEXT_STEPS[@]}" -eq 0 ]; then
        status_ok "No action required."
        return
    fi

    for priority in 5 10 20 25 30 40 50 60 70 80; do
        for recommendation in "${RECOMMENDED_NEXT_STEPS[@]}"; do
            recommendation_order="$(recommendation_priority "$recommendation")"
            if [ "$recommendation_order" -eq "$priority" ]; then
                printf "  %d. %s\n" "$index" "$recommendation"
                index=$((index + 1))
            fi
        done
    done
}

check_command() {
    local cmd="$1"
    local label="$2"

    if command -v "$cmd" >/dev/null 2>&1; then
        status_ok "$label: $(command -v "$cmd")"
        return 0
    fi

    status_fail "$label: command '$cmd' not found"
    return 1
}

check_dir() {
    local path="$1"
    local label="$2"

    if [ -d "$path" ]; then
        if [ -w "$path" ]; then
            status_ok "$label: $path"
        else
            status_warn "$label exists but is not writable: $path"
        fi
    else
        status_fail "$label does not exist yet: $path"
    fi
}

check_file() {
    local path="$1"
    local label="$2"

    if [ -f "$path" ]; then
        status_ok "$label: $path"
    else
        status_fail "$label not found: $path"
    fi
}

show_path_value() {
    local var="$1"
    local value="$2"

    if [ -n "${!var:-}" ]; then
        status_set "$var: $value"
    else
        status_warn "$var is not set in the current shell; using default: $value"
    fi
}

check_expected_dir() {
    local path="$1"
    local label="$2"
    local setup_hint="$3"

    if [ -d "$path" ]; then
        if [ -w "$path" ]; then
            status_ok "$label exists: $path"
        else
            status_warn "$label exists but is not writable: $path"
        fi
    else
        status_warn "$label does not exist yet: $path"
        if [ -n "$setup_hint" ]; then
            echo "           Run: $setup_hint"
            add_recommendation "Run: $setup_hint"
        fi
    fi
}

check_python_version() {
    local py_cmd=""

    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
                py_cmd="$cmd"
                break
            fi
        fi
    done

    if [ -n "$py_cmd" ]; then
        status_ok "Python >= 3.11: $($py_cmd -c 'import sys; print(sys.executable, sys.version.split()[0])')"
    else
        status_fail "Python >= 3.11 not found in PATH"
        add_recommendation "Install Python >= 3.11, then rerun: ./bootstrap.sh --check"
    fi
}

check_python_import() {
    local python_bin="$1"
    local module="$2"
    local label="$3"
    local setup_hint="${4:-./bootstrap.sh --sandbox}"

    if [ ! -x "$python_bin" ]; then
        status_fail "$label: sandbox Python not found"
        add_recommendation "Run: ./bootstrap.sh --sandbox"
        return
    fi

    if "$python_bin" -c "import $module" >/dev/null 2>&1; then
        status_ok "$label"
    else
        status_fail "$label"
        add_recommendation "Run: $setup_hint"
    fi
}

check_aiohttp_version() {
    local python_bin="$1"
    local result
    local status

    if [ ! -x "$python_bin" ]; then
        status_fail "aiohttp version: sandbox Python not found"
        add_recommendation "Run: ./bootstrap.sh --sandbox"
        return
    fi

    set +e
    result=$("$python_bin" - <<'PY'
import importlib.metadata as md
import sys

try:
    version = md.version("aiohttp")
except md.PackageNotFoundError:
    print("MISSING aiohttp not installed")
    sys.exit(1)

major, minor, *_ = version.split(".")
if (int(major), int(minor)) >= (3, 14):
    print(f"WARN aiohttp {version}; expected <3.14 for hydrotools NWIS cache compatibility")
    sys.exit(2)

print(f"OK aiohttp {version}")
PY
)
    status="$?"
    set -e

    case "$status" in
        0) status_ok "${result#OK }" ;;
        2)
            status_warn "${result#WARN }"
            add_recommendation "Run: ./bootstrap.sh --sandbox"
            ;;
        *)
            status_fail "${result#MISSING }"
            add_recommendation "Run: ./bootstrap.sh --sandbox"
            ;;
    esac
}

check_r_package() {
    local rscript_bin="$1"
    local package="$2"
    local label="${3:-R}"

    if [ ! -x "$rscript_bin" ]; then
        return
    fi

    if "$rscript_bin" -e "quit(status = ifelse(requireNamespace('$package', quietly = TRUE), 0, 1))" >/dev/null 2>&1; then
        status_ok "$label package '$package'"
    else
        status_fail "$label package '$package'"
        R_PACKAGE_CHECK_FAILED=1
    fi
}

run_check() {
    local script_dir
    local sandbox_dir
    local sandbox_build_dir
    local sandbox_data_dir
    local sandbox_condarc
    local ngen_dir
    local sandbox_env
    local forcing_env
    local subset_env
    local active_env=""
    local expected_env=""
    local activate_command=""
    local os_name
    local target_file=""
    local source_line=""
    local R_PACKAGE_CHECK_FAILED=0

    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    sandbox_dir="${SANDBOX_DIR:-$script_dir}"
    sandbox_build_dir="${SANDBOX_BUILD_DIR:-$sandbox_dir/build}"
    sandbox_data_dir="${SANDBOX_DATA_DIR:-$sandbox_dir/data}"
    sandbox_condarc="${SANDBOX_CONDARC:-$sandbox_build_dir/condarc}"
    ngen_dir="${NGEN_DIR:-$sandbox_build_dir/ngen}"
    sandbox_env="${SANDBOX_ENV:-$sandbox_build_dir/venv/sandbox}"
    forcing_env="${FORCING_ENV:-$sandbox_build_dir/venv/forcing}"
    subset_env="$sandbox_build_dir/rvenv/venv_subset"
    os_name="$(uname -s)"

    echo ""
    echo "Bootstrap Check"
    echo "==============="
    echo "This check is read-only; it does not install packages or create directories."
    echo ""

    echo "Configured Paths"
    if [ "$sandbox_dir" != "$script_dir" ]; then
        status_warn "SANDBOX_DIR points to a different repository: $sandbox_dir"
        echo "           Current repository: $script_dir"
        add_recommendation "Update Sandbox paths: ./bootstrap.sh --env --verbose"
    fi
    show_path_value "SANDBOX_DIR" "$sandbox_dir"
    show_path_value "SANDBOX_BUILD_DIR" "$sandbox_build_dir"
    show_path_value "SANDBOX_DATA_DIR" "$sandbox_data_dir"
    show_path_value "SANDBOX_CONDARC" "$sandbox_condarc"
    show_path_value "NGEN_DIR" "$ngen_dir"
    echo "           [SET] means the path is configured, not that the component is built."
    echo ""

    echo "Path Availability"
    check_dir "$sandbox_dir" "SANDBOX_DIR"
    check_expected_dir "$sandbox_build_dir" "SANDBOX_BUILD_DIR" "./bootstrap.sh --env --verbose"
    check_expected_dir "$sandbox_data_dir" "SANDBOX_DATA_DIR" "./bootstrap.sh --env --verbose"
    if [ -f "$sandbox_condarc" ]; then
        status_ok "SANDBOX_CONDARC exists: $sandbox_condarc"
    else
        status_warn "SANDBOX_CONDARC does not exist yet: $sandbox_condarc"
        echo "           Run: ./bootstrap.sh --env --verbose"
    fi
    check_expected_dir "$ngen_dir" "NGEN_DIR build root" "./bootstrap.sh --ngen"
    echo ""

    echo "Shell Setup"
    if [[ "$SHELL" == *zsh ]]; then
        target_file="$HOME/.zshrc"
    elif [[ "$SHELL" == *bash ]]; then
        if [ -f "$HOME/.bash_profile" ]; then
            target_file="$HOME/.bash_profile"
        else
            target_file="$HOME/.bashrc"
        fi
    fi

    source_line="[ -f \"$sandbox_dir/utils/sandbox_env.sh\" ] && source \"$sandbox_dir/utils/sandbox_env.sh\""
    if [ -n "$target_file" ] && grep -Fxq "$source_line" "$target_file" 2>/dev/null; then
        status_ok "Sandbox environment is registered in $target_file"
    else
        status_warn "Sandbox environment is not registered in the detected shell startup file"
        echo "           Run: ./bootstrap.sh --env --verbose"
        add_recommendation "Run: ./bootstrap.sh --env --verbose"
    fi

    for var in SANDBOX_DIR SANDBOX_BUILD_DIR SANDBOX_DATA_DIR SANDBOX_ENV FORCING_ENV NGEN_DIR; do
        if [ -n "${!var:-}" ]; then
            status_ok "$var is set: ${!var}"
        else
            status_warn "$var is not set in the current shell"
            add_recommendation "Run: ./bootstrap.sh --env --verbose"
        fi
    done
    echo ""

    echo "System Tools"
    check_command git "git"
    check_python_version
    if command -v conda >/dev/null 2>&1; then
        status_ok "conda: $(command -v conda)"
    else
        status_warn "conda not found; Python venv fallback can build the sandbox env, but --subset requires conda"
    fi
    if command -v mamba >/dev/null 2>&1; then
        status_ok "mamba: $(command -v mamba)"
    else
        status_warn "mamba not found; conda will be used where possible"
    fi
    if command -v Rscript >/dev/null 2>&1; then
        status_ok "Rscript: $(command -v Rscript)"
    else
        status_warn "Rscript not found in PATH; this is OK if using the subset conda env"
    fi
    echo ""

    echo "Sandbox Environments"
    if [ -x "$sandbox_env/bin/python" ]; then
        status_ok "Sandbox Python: $sandbox_env/bin/python"

        expected_env="$(cd "$sandbox_env" && pwd -P)"
        if [ -n "${VIRTUAL_ENV:-}" ]; then
            if [ -d "$VIRTUAL_ENV" ]; then
                active_env="$(cd "$VIRTUAL_ENV" && pwd -P)"
            else
                active_env="$VIRTUAL_ENV"
            fi
        elif [ -n "${CONDA_PREFIX:-}" ]; then
            if [ -d "$CONDA_PREFIX" ]; then
                active_env="$(cd "$CONDA_PREFIX" && pwd -P)"
            else
                active_env="$CONDA_PREFIX"
            fi
        fi

        if [ "$active_env" = "$expected_env" ]; then
            status_ok "Sandbox environment is active"
        else
            status_warn "Sandbox environment is not active"
            echo "           Expected: $expected_env"
            echo "           Current : ${active_env:-<none>}"
            if [ -d "$sandbox_env/conda-meta" ]; then
                activate_command="conda activate \"$sandbox_env\""
            else
                activate_command="source \"$sandbox_env/bin/activate\""
            fi
            echo "           Run: $activate_command"
            add_recommendation "Run: $activate_command"
        fi

    else
        status_fail "Sandbox Python env not found: $sandbox_env"
        echo "           Run: ./bootstrap.sh --sandbox"
        add_recommendation "Run: ./bootstrap.sh --sandbox"
    fi
    if [ -x "$sandbox_env/bin/sandbox" ]; then
        status_ok "sandbox command: $sandbox_env/bin/sandbox"
    else
        status_fail "sandbox command not found in sandbox env"
        add_recommendation "Run: ./bootstrap.sh --sandbox"
    fi
    if [ -x "$forcing_env/bin/python" ]; then
        status_ok "Forcing Python: $forcing_env/bin/python"
    else
        status_fail "Forcing Python env not found: $forcing_env"
        echo "           Run: ./bootstrap.sh --sandbox"
        add_recommendation "Run: ./bootstrap.sh --sandbox"
    fi
    if [ -x "$subset_env/bin/Rscript" ]; then
        status_ok "Subset Rscript: $subset_env/bin/Rscript"
    elif command -v Rscript >/dev/null 2>&1; then
        status_warn "Subset conda R env not found: $subset_env"
        echo "           System Rscript is available and will be checked below."
        if [ "$os_name" = "Darwin" ]; then
            echo "           On macOS, prefer installing subset R packages with:"
            echo "             Rscript \$SANDBOX_DIR/src/R/install_load_libs.R --install"
        else
            echo "           On HPC/Linux, run ./bootstrap.sh --subset if you want the managed subset R env."
            echo "           A loaded R module is OK only if the same module is loaded for sandbox --subset."
        fi
    else
        status_warn "Subset R env not found: $subset_env"
        if [ "$os_name" = "Darwin" ]; then
            echo "           Install R, then run:"
            echo "             Rscript \$SANDBOX_DIR/src/R/install_load_libs.R --install"
            add_recommendation "Install R packages: Rscript \$SANDBOX_DIR/src/R/install_load_libs.R --install"
        else
            echo "           Run: ./bootstrap.sh --subset"
            add_recommendation "Run: ./bootstrap.sh --subset"
        fi
    fi
    echo ""

    echo "Python Packages"
    check_python_import "$sandbox_env/bin/python" "ngen.cal" "ngen.cal import"
    check_python_import "$sandbox_env/bin/python" "ngen.config" "ngen.config import"
    check_python_import "$sandbox_env/bin/python" "ngen_cal_plugins" "ngen_cal_plugins import"
    check_python_import "$sandbox_env/bin/python" "nwm_routing" "nwm_routing import (t-route)" "./bootstrap.sh --troute"
    check_python_import "$sandbox_env/bin/python" "pytest" "pytest import"
    check_aiohttp_version "$sandbox_env/bin/python"
    echo ""

    echo "R Packages"
    if [ -x "$subset_env/bin/Rscript" ]; then
        check_r_package "$subset_env/bin/Rscript" "sf" "subset R"
        check_r_package "$subset_env/bin/Rscript" "terra" "subset R"
        check_r_package "$subset_env/bin/Rscript" "hfsubsetR" "subset R"
        check_r_package "$subset_env/bin/Rscript" "zonal" "subset R"
    elif command -v Rscript >/dev/null 2>&1; then
        check_r_package "$(command -v Rscript)" "sf" "system R"
        check_r_package "$(command -v Rscript)" "terra" "system R"
        check_r_package "$(command -v Rscript)" "hfsubsetR" "system R"
        check_r_package "$(command -v Rscript)" "zonal" "system R"
    else
        status_warn "No Rscript available for package checks"
    fi
    if [ "$R_PACKAGE_CHECK_FAILED" -ne 0 ]; then
        if [ "$os_name" = "Darwin" ]; then
            add_recommendation "Install R packages: Rscript \$SANDBOX_DIR/src/R/install_load_libs.R --install"
        else
            add_recommendation "Run: ./bootstrap.sh --subset"
        fi
    fi
    echo ""

    echo "Build Artifacts"
    if [ -x "$ngen_dir/cmake_build/ngen" ]; then
        status_ok "ngen executable: $ngen_dir/cmake_build/ngen"
        if [ "$os_name" = "Linux" ] && [ -f "$sandbox_env/lib/libstdc++.so.6" ]; then
            local runtime_library_path
            local runtime_preload
            local linkage_output
            runtime_library_path="$sandbox_env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            runtime_preload="$sandbox_env/lib/libstdc++.so.6${LD_PRELOAD:+:$LD_PRELOAD}"
            linkage_output="$(
                LD_LIBRARY_PATH="$runtime_library_path" \
                LD_PRELOAD="$runtime_preload" \
                ldd "$ngen_dir/cmake_build/ngen" 2>&1 || true
            )"
            if grep -q "not found" <<< "$linkage_output"; then
                status_fail "ngen has unresolved shared-library dependencies"
                grep "not found" <<< "$linkage_output" | sed 's/^/           /'
                add_recommendation "Load the compiler, MPI, NetCDF, and UDUNITS modules used to build ngen"
            else
                status_ok "ngen shared-library dependencies resolve with the Sandbox runtime"
            fi
        fi
    else
        status_warn "ngen executable not found: $ngen_dir/cmake_build/ngen"
        echo "           Run: ./bootstrap.sh --ngen"
        add_recommendation "Run: ./bootstrap.sh --ngen"
    fi
    if [ -d "$ngen_dir/extern" ]; then
        status_ok "ngen extern directory: $ngen_dir/extern"
    else
        status_warn "ngen extern directory not found yet"
    fi
    echo ""

    echo "Submodules"
    if git -C "$sandbox_dir" submodule status >/dev/null 2>&1; then
        while read -r line; do
            case "$line" in
                -*)
                    status_fail "Not initialized: $line"
                    add_recommendation "Initialize submodules: git submodule update --init --recursive"
                    ;;
                +*)
                    status_warn "Different commit than index: $line"
                    add_recommendation "Review submodule state: git submodule status"
                    ;;
                *)
                    status_ok "$line"
                    ;;
            esac
        done < <(git -C "$sandbox_dir" submodule status)
    else
        status_warn "Unable to read git submodule status"
        add_recommendation "Review repository and submodule paths: git submodule status"
    fi
    echo ""
    print_recommended_next_steps
    echo ""
}

if [ "$RUN_CHECK" = "ON" ]; then
    run_check
fi


# Run steps
if [ "$SETUP_ENV" = "ON" ]; then
    source ./utils/sandbox_env.sh VERBOSE=$VERBOSE
fi

# Run steps
if [ "$BUILD_SANDBOX" = "ON" ]; then
    source ./utils/build_sandbox.sh
fi

if [ "$BUILD_SUBSET" = "ON" ]; then
    ./utils/build_venv_subset.sh
fi

if [ "$BUILD_NGEN" = "ON" ] || [ "$BUILD_MODELS" = "ON" ] || [ "$BUILD_TROUTE" = "ON" ]; then
    bash ./utils/build_models.sh \
        NGEN="$BUILD_NGEN" \
        MODELS="$BUILD_MODELS" \
        TROUTE="$BUILD_TROUTE" \
        CLEAN="$BUILD_CLEAN"
fi
