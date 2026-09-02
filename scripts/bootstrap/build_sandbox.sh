###############################################################
# Author : Ahmad Jan Khattak [ajkhattak@gmail.com | September 10, 2024]
# Contributor : Sifan A. Koriche [sakoriche@ua.edu | December 18, 2024]

# Clone NextGenSandbox repository
# git clone https://github.com/ajkhattak/NextGenSandbox && cd NextGenSandbox
# Called by: ./bootstrap.sh --sandbox
# install mamba if not already there: conda install -n base -c conda-forge mamba

###############################################################

###### Config #######
BUILD_SANDBOX=${BUILD:-ON}

# Validate environment
for var in \
    SANDBOX_DIR \
    SANDBOX_BUILD_DIR \
    SANDBOX_DATA_DIR \
    NGEN_DIR \
    SANDBOX_ENV \
    FORCING_ENV
do
    eval "value=\${$var}"

    if [ -z "$value" ]; then
        echo "ERROR: Missing environment variable: $var"
	echo "Run: ./bootstrap.sh --env and follow the steps to set environment variables." >&2
        return 1
    fi

done

SANDBOX_CONDARC="${SANDBOX_CONDARC:-$SANDBOX_BUILD_DIR/condarc}"
export SANDBOX_CONDARC

mkdir -p "$SANDBOX_BUILD_DIR"
mkdir -p "$SANDBOX_DATA_DIR"
touch "$SANDBOX_CONDARC"
export CONDARC="$SANDBOX_CONDARC"

echo "Sandbox dir       : $SANDBOX_DIR"
echo "Sandbox build dir : $SANDBOX_BUILD_DIR"
echo "Sandbox data dir  : $SANDBOX_DATA_DIR"
echo "Sandbox condarc   : $SANDBOX_CONDARC"
echo "Sandbox VENV      : $SANDBOX_ENV"
echo "Forcing VENV      : $FORCING_ENV"


############################################
# NEEDED WHEN HOME DIR HAS LIMITED STORAGE QUOTA (HPC SETTINGS)
############################################
export SCRATCH_BASE="$SANDBOX_BUILD_DIR"
mkdir -p "$SCRATCH_BASE/tmp" "$SCRATCH_BASE/pip_cache"

export TMPDIR="$SCRATCH_BASE/tmp"
export TEMP="$SCRATCH_BASE/tmp"
export TMP="$SCRATCH_BASE/tmp"
export PIP_CACHE_DIR="$SCRATCH_BASE/pip_cache"

#####################################################
print_build_status()
{
    local status="$1"
    local message="$2"
    printf "  [%s] %s\n" "$status" "$message"
}

summarize_sandbox_build()
{
    local sandbox_python="$SANDBOX_ENV/bin/python"
    local sandbox_command="$SANDBOX_ENV/bin/sandbox"
    local launcher_command="$SANDBOX_ENV/bin/sandbox-launcher"
    local forcing_python="$FORCING_ENV/bin/python"
    local failed=0

    echo ""
    echo "Sandbox build summary"
    echo "====================="

    if [ -x "$sandbox_python" ]; then
        print_build_status "OK" "Sandbox Python: $sandbox_python"
    else
        print_build_status "MISSING" "Sandbox Python: $sandbox_python"
        failed=1
    fi

    if [ -x "$sandbox_command" ]; then
        print_build_status "OK" "sandbox command: $sandbox_command"
    else
        print_build_status "MISSING" "sandbox command: $sandbox_command"
        failed=1
    fi

    if [ -x "$launcher_command" ]; then
        print_build_status "OK" "sandbox-launcher command: $launcher_command"
    else
        print_build_status "MISSING" "sandbox-launcher command: $launcher_command"
        failed=1
    fi

    if [ -x "$forcing_python" ]; then
        print_build_status "OK" "Forcing Python environment: $FORCING_ENV"
    else
        print_build_status "MISSING" "Forcing Python environment: $FORCING_ENV"
        failed=1
    fi

    echo ""

    if [ "$failed" -ne 0 ]; then
        echo "Sandbox build finished, but one or more expected environments were not found."
        echo "Run ./bootstrap.sh --check for a fuller diagnostic report."
        return 1
    fi

    echo "Sandbox build completed successfully."
    echo ""
    echo "Created environments:"
    echo "  Sandbox CLI : $SANDBOX_ENV"
    echo "  Forcing     : $FORCING_ENV"
}

#####################################################
build_sandbox()
{
    SANDBOX_ENV_FILE="$SANDBOX_DIR/scripts/bootstrap/venv/venv_sandbox.yaml"

    if [ ! -f "$SANDBOX_ENV_FILE" ]; then
        echo "ERROR: Sandbox environment definition not found: $SANDBOX_ENV_FILE" >&2
        return 1
    fi

    echo "Sandbox environment definition: $SANDBOX_ENV_FILE"

    # FIND PYTHON >= 3.11
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" &>/dev/null; then
                PYTHON_CMD="$cmd"
                break
            fi
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        echo "ErrorMsg: Python >= 3.11 is required and not found in PATH."
        return 1
    fi

    PY_VERSION=$("$PYTHON_CMD" -c "import sys; print(sys.version.split()[0])")
    echo "Using Python: $PYTHON_CMD ($PY_VERSION)"


    # -------------------------------
    # USE CONDA / MAMBA
    # -------------------------------
    if command -v conda &>/dev/null; then

        source "$(conda info --base)/etc/profile.d/conda.sh"

	# Prefer mamba if available
        if command -v mamba &>/dev/null; then
            SOLVER="mamba"
        else
            SOLVER="conda"
        fi

	echo "Using solver: $SOLVER"

	############################################
        # SANDBOX ENV
        ############################################
	if [ ! -d "$SANDBOX_ENV" ]; then
            echo "Creating sandbox environment at $SANDBOX_ENV"
            "$SOLVER" env create -y -p "$SANDBOX_ENV" -f "$SANDBOX_ENV_FILE"
        else
            echo "Updating sandbox environment at $SANDBOX_ENV"
            "$SOLVER" env update -p "$SANDBOX_ENV" -f "$SANDBOX_ENV_FILE"
        fi

	conda activate "$SANDBOX_ENV"

	# To remove conda env long prefix 
	conda config --env --set env_prompt '({name})'

	#python -m pip install --upgrade pip --no-cache-dir
	#pip install "setuptools>=64.0,<69.0" wheel
        #conda install -y -c conda-forge numba==0.63 llvmlite
	#conda install -y -c conda-forge pycares=4.11.0 # need for ngen-cal
    else
        # -------------------------------
        # FALLBACK TO VIRTUALENV
        # -------------------------------
	echo "Conda not found -- building sandbox virtual python environment ($SANDBOX_ENV)"
        mkdir -p "$SANDBOX_ENV"
        $PYTHON_CMD -m venv "$SANDBOX_ENV"
        source "$SANDBOX_ENV/bin/activate"
	"$SANDBOX_ENV/bin/python" -m pip install --upgrade pip --no-cache-dir
	"$SANDBOX_ENV/bin/python" -m pip install \
	    "setuptools>=64.0,<69.0" wheel

    fi

    SANDBOX_PYTHON="$SANDBOX_ENV/bin/python"
    if [ ! -x "$SANDBOX_PYTHON" ]; then
        echo "ERROR: Sandbox Python was not created: $SANDBOX_PYTHON" >&2
        return 1
    fi

    "$SANDBOX_PYTHON" -m pip install -e '.[test]'

    # Install the dependency versions pinned by the NextGenSandbox repository.
    git submodule update --init --recursive

    "$SANDBOX_PYTHON" -m pip install 'extern/ngen-cal/python/ngen_cal[netcdf,pso]'
    "$SANDBOX_PYTHON" -m pip install extern/ngen-cal/python/ngen_conf
    "$SANDBOX_PYTHON" -m pip install -e ./plugins/ngen_cal_plugins
    "$SANDBOX_PYTHON" -m pip install -e ./extern/lstm
    "$SANDBOX_PYTHON" -m pip install -e ./extern/dhbv2
    "$SANDBOX_PYTHON" -m pip install 'aiohttp<3.14'
 
    echo "Sandbox Python Environment Created ($SANDBOX_ENV)"
    
    if command -v conda &>/dev/null; then
        conda deactivate
    else
        deactivate
    fi

    ############################################
    # FORCING
    ############################################
    echo "Creating virtual python environment for forcing downloader ($FORCING_ENV)"

    if command -v conda >/dev/null 2>&1; then
	source "$(conda info --base)/etc/profile.d/conda.sh"

	# Prefer mamba if available
        if command -v mamba &>/dev/null; then
            SOLVER="mamba"
        else
            SOLVER="conda"
        fi

	echo "Using solver: $SOLVER"

	if [ ! -d "$FORCING_ENV" ]; then
            echo "Creating forcing environment at $FORCING_ENV"
	    $SOLVER env create -y -p "$FORCING_ENV" \
	        -f "$SANDBOX_DIR/scripts/bootstrap/venv/venv_forcing.yaml"
	else
            echo "Updating forcing environment at $FORCING_ENV"
	    $SOLVER env update -p "$FORCING_ENV" \
	        -f "$SANDBOX_DIR/scripts/bootstrap/venv/venv_forcing.yaml"
	fi

    else
	echo "Conda not found -- building forcing virtual python environment ($FORCING_ENV)"

	mkdir -p "$FORCING_ENV"

	$PYTHON_CMD -m venv "$FORCING_ENV"
	source "$FORCING_ENV/bin/activate"
	"$FORCING_ENV/bin/python" -m pip install --upgrade pip --no-cache-dir
	"$FORCING_ENV/bin/python" -m pip install \
	    -r "$SANDBOX_DIR/scripts/bootstrap/venv/requirements_forcing.txt"

	deactivate
    fi

    summarize_sandbox_build
}


############################################
# ENTRY POINT
############################################
if [[ "$BUILD_SANDBOX" == "ON" ]]; then
    echo "=== Building NextGen Sandbox ==="
    build_sandbox
else
    echo "BUILD=OFF — skipping"
fi
