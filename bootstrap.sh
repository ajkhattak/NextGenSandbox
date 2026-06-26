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

# Parse args
for arg in "$@"; do
    case $arg in
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
    printf "  [OK]      %s\n" "$1"
}

status_set() {
    printf "  [SET]     %s\n" "$1"
}

status_warn() {
    printf "  [WARN]    %s\n" "$1"
}

status_fail() {
    printf "  [MISSING] %s\n" "$1"
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
    fi
}

check_python_import() {
    local python_bin="$1"
    local module="$2"
    local label="$3"

    if [ ! -x "$python_bin" ]; then
        status_fail "$label: sandbox Python not found"
        return
    fi

    if "$python_bin" -c "import $module" >/dev/null 2>&1; then
        status_ok "$label"
    else
        status_fail "$label"
    fi
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
    local target_file=""
    local source_line=""

    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    sandbox_dir="${SANDBOX_DIR:-$script_dir}"
    sandbox_build_dir="${SANDBOX_BUILD_DIR:-$sandbox_dir/build}"
    sandbox_data_dir="${SANDBOX_DATA_DIR:-$sandbox_dir/data}"
    sandbox_condarc="${SANDBOX_CONDARC:-$sandbox_build_dir/condarc}"
    ngen_dir="${NGEN_DIR:-$sandbox_build_dir/ngen}"
    sandbox_env="${SANDBOX_ENV:-$sandbox_build_dir/venv/sandbox}"
    forcing_env="${FORCING_ENV:-$sandbox_build_dir/venv/forcing}"
    subset_env="$sandbox_build_dir/rvenv/venv_subset"

    echo ""
    echo "Bootstrap Check"
    echo "==============="
    echo "This check is read-only; it does not install packages or create directories."
    echo ""

    echo "Configured Paths"
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
    fi

    for var in SANDBOX_DIR SANDBOX_BUILD_DIR SANDBOX_DATA_DIR SANDBOX_ENV FORCING_ENV NGEN_DIR; do
        if [ -n "${!var:-}" ]; then
            status_ok "$var is set: ${!var}"
        else
            status_warn "$var is not set in the current shell"
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
    else
        status_fail "Sandbox Python env not found: $sandbox_env"
        echo "           Run: ./bootstrap.sh --sandbox"
    fi
    if [ -x "$sandbox_env/bin/sandbox" ]; then
        status_ok "sandbox command: $sandbox_env/bin/sandbox"
    else
        status_fail "sandbox command not found in sandbox env"
    fi
    if [ -x "$forcing_env/bin/python" ]; then
        status_ok "Forcing Python: $forcing_env/bin/python"
    else
        status_fail "Forcing Python env not found: $forcing_env"
        echo "           Run: ./bootstrap.sh --sandbox"
    fi
    if [ -x "$subset_env/bin/Rscript" ]; then
        status_ok "Subset Rscript: $subset_env/bin/Rscript"
    else
        status_warn "Subset R env not found: $subset_env"
        echo "           Run: ./bootstrap.sh --subset"
    fi
    echo ""

    echo "Python Packages"
    check_python_import "$sandbox_env/bin/python" "ngen.cal" "ngen.cal import"
    check_python_import "$sandbox_env/bin/python" "ngen.config" "ngen.config import"
    check_python_import "$sandbox_env/bin/python" "nwm_routing" "nwm_routing import (t-route)"
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
    echo ""

    echo "Build Artifacts"
    if [ -x "$ngen_dir/cmake_build/ngen" ]; then
        status_ok "ngen executable: $ngen_dir/cmake_build/ngen"
    else
        status_warn "ngen executable not found: $ngen_dir/cmake_build/ngen"
        echo "           Run: ./bootstrap.sh --ngen"
    fi
    if [ -d "$ngen_dir/extern" ]; then
        status_ok "ngen extern directory: $ngen_dir/extern"
    else
        status_warn "ngen extern directory not found yet"
    fi
    echo ""

    echo "Submodules"
    if git -C "$sandbox_dir" submodule status >/dev/null 2>&1; then
        git -C "$sandbox_dir" submodule status | while read -r line; do
            case "$line" in
                -*)
                    status_fail "Not initialized: $line"
                    ;;
                +*)
                    status_warn "Different commit than index: $line"
                    ;;
                *)
                    status_ok "$line"
                    ;;
            esac
        done
    else
        status_warn "Unable to read git submodule status"
    fi
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

if [ "$BUILD_NGEN" = "ON" ]; then
    source ./utils/build_models.sh NGEN=ON CLEAN=$BUILD_CLEAN
fi

if [ "$BUILD_MODELS" = "ON" ]; then
    source ./utils/build_models.sh MODELS=ON CLEAN=$BUILD_CLEAN
fi

if [ "$BUILD_TROUTE" = "ON" ]; then
    source ./utils/build_models.sh TROUTE=ON
fi
