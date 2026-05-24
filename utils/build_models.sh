###############################################################
# Author      : Ahmad Jan Khattak [ahmad.jan.khattak@noaa.gov | September 10, 2024]
# Contributor : Sifan A. Koriche [sakoriche@ua.edu | December 18, 2024]

# NOTE : See utils/setup_hpc.sh to load the required modules and setup the env for building ngen and models

###############################################################
# Set build options below. Turn ON or OFF as needed.
# For first-time setup, build all components in the following order:
#   1. NGEN
#   2. MODELS
#   3. T-ROUTE


BUILD_NGEN=${NGEN:-OFF}
BUILD_MODELS=${MODELS:-OFF}
BUILD_TROUTE=${TROUTE:-OFF}
BUILD_CLEAN=${CLEAN:-false}

# -------------------------------
# Override from command-line arguments
# Example usage: ./build_models.sh NGEN=ON MODELS=OFF TROUTE=ON
# -------------------------------
for arg in "$@"; do
    key="${arg%%=*}"
    value="${arg#*=}"

    case "$key" in
        NGEN)   BUILD_NGEN="$value" ;;
        MODELS) BUILD_MODELS="$value" ;;
        TROUTE) BUILD_TROUTE="$value" ;;
        CLEAN)  BUILD_CLEAN="$value" ;;
        *) echo "Warning: unrecognized argument '$arg'" ;;
    esac
done


# -------------------------------
# Print the build flags
# -------------------------------
echo "BUILD_NGEN   = $BUILD_NGEN"
echo "BUILD_MODELS = $BUILD_MODELS"
echo "BUILD_TROUTE = $BUILD_TROUTE"

HF_VERSION=2.2     # provide hydrofabric version

###############################################################
# Check if current active venv matches the sandbox venv

# Determine current active environment
if [ -n "$VIRTUAL_ENV" ]; then
    CURRENT_ENV=$(realpath "$VIRTUAL_ENV" 2>/dev/null)
elif [ -n "$CONDA_PREFIX" ]; then
    CURRENT_ENV=$(realpath "$CONDA_PREFIX" 2>/dev/null)
else
    CURRENT_ENV=""
fi

if [ "$CURRENT_ENV" != "$SANDBOX_ENV" ]; then
    echo "Error: This script must be run inside the sandbox environment:"
    echo "Expected: $SANDBOX_ENV"
    echo "Current : ${CURRENT_ENV:-<none>}"
    exit 1
fi

###############################################################


###############################################################
# Helper: clone or update repo
clone_or_update() {
    local repo_url="$1"
    local dest_dir="$2"
    
    if [ -d "$dest_dir/.git" ]; then
        echo "Updating repo: $dest_dir"
        git -C "$dest_dir" pull --ff-only
    else
        echo "Cloning repo: $repo_url"
        git clone "$repo_url" "$dest_dir"
    fi
}

build_ngen()
{
    pushd $SANDBOX_BUILD_DIR

    if [ "$CLEAN" = true ]; then
	echo "Cleaning ngen repo"
	rm -rf ngen
    fi

    clone_or_update "https://github.com/NOAA-OWP/ngen" "ngen"

    cd ngen
    git submodule update --init --recursive

    export builddir="cmake_build"
    rm -rf ${builddir}
    cmake -DCMAKE_BUILD_TYPE=Release \
	  -DNGEN_WITH_BMI_FORTRAN=ON \
	  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
	  -DNGEN_WITH_NETCDF=ON \
	  -DNGEN_WITH_SQLITE=ON \
	  -DNGEN_WITH_ROUTING=ON \
	  -DNGEN_WITH_EXTERN_ALL=ON  \
	  -DNGEN_WITH_TESTS=ON \
          -DNGEN_QUIET=ON \
	  -DNGEN_WITH_MPI=ON \
	  -DNetCDF_ROOT=${NETCDF_ROOT}/lib \
	  -B ${builddir} \
	  -S .

    #make -j8 -C ${builddir}
    # run the following if ran into tests timeout issues
    cmake --build ${builddir} --target ngen -j8
    popd
}


build_troute()
{
    if [ ${HF_VERSION} == 2.2 ]; then
	pushd $NGEN_DIR/extern
	clone_or_update "https://github.com/shorvath-noaa/t-route" "t-route-hf2.2"

	cd t-route-hf2.2
	git checkout conus_timing_runs
	git pull
    else
	pushd $NGEN_DIR/extern/t-route
	git checkout master
	git pull
    fi

    ##hot patch nc config to nf config
    #sed -i 's/nc-config/nf-config/g' src/kernel/reservoir/makefile
    MAKEFILE_PATH="src/kernel/reservoir/makefile"
    
    # Only patch on Linux
    if [ "$(uname)" = "Linux" ]; then
	# Check if nf-config is available
	if command -v nf-config &>/dev/null; then
            NETCDF_FORTRAN_CONFIG="nf-config"
	else
            echo "Error: nf-config not found on Linux."
            exit 1
	fi

        echo "Patching $MAKEFILE_PATH to use $NETCDF_FORTRAN_CONFIG..."
        sed -i "s/nc-config/$NETCDF_FORTRAN_CONFIG/g" "$MAKEFILE_PATH"

    fi

    if [[ "$(uname)" == "Darwin" ]]; then
	NETCDF=$(brew --prefix netcdf-fortran)/include LIBRARY_PATH=$(brew --prefix gcc)/lib/gcc/current/:$(brew --prefix)/lib:$LIBRARY_PATH FC=$FC CC=$CC F90=$FC ./compiler.sh no-e
    else
	export NETCDF=${NETCDF_ROOT}/include
	./compiler.sh no-e
    fi

    popd
}



build_models() {

    set -e  # exit on error
    pushd "$NGEN_DIR" >/dev/null || return 1

    builddir="cmake_build"

    # Helper: build with cmake
    cmake_build() {
        local src="$1"
        local build="$2"
        shift 2

	if [ "$CLEAN" = true ]; then
            echo "Cleaning build directory: $build"
            rm -rf "$build"
        fi

	cmake -B "$build" -S "$src" "$@"
        cmake --build "$build" -j
	
    }


    # Model loop
    for model in noah-owp-modular cfe evapotranspiration SoilFreezeThaw SoilMoistureProfiles CASAM snow17 sac-sma; do
	echo "#-----------------------------------------------"
        echo "# Building model: $model"
	echo "#---------------------------------- -------------"
	
        case "$model" in

        noah-owp-modular)
            git submodule update --remote "extern/$model/$model"
            cmake_build "extern/$model" "extern/$model/$model/$builddir" \
                -DCMAKE_BUILD_TYPE=Release -DNGEN_IS_MAIN_PROJECT=ON
            ;;

        cfe|SoilFreezeThaw|SoilMoistureProfiles)
            git submodule update --remote "extern/$model/$model"
            cmake_build "extern/$model/$model" "extern/$model/$model/$builddir" \
                -DNGEN=ON -DCMAKE_BUILD_TYPE=Release
            ;;

        evapotranspiration)
            git submodule update --remote "extern/$model/$model"
            cmake_build "extern/$model/$model" "extern/$model/$model/$builddir" \
                -DCMAKE_BUILD_TYPE=Release
            ;;

        CASAM)
            clone_or_update "https://github.com/NOAA-OWP/LGAR-C" "extern/$model/$model"
            cmake_build "extern/$model/$model" "extern/$model/$model/$builddir" \
                -DNGEN=ON -DCMAKE_BUILD_TYPE=Release
            ;;

        snow17)
            clone_or_update "https://github.com/NOAA-OWP/snow17" "extern/$model/$model"
            cmake_build "extern/$model/$model" "extern/$model/$model/$builddir" \
                -DCMAKE_BUILD_TYPE=Release -DISO_C_FORTRAN_BMI_PATH=$NGEN_DIR/extern/iso_c_fortran_bmi
            ;;

        sac-sma)
            clone_or_update "https://github.com/NOAA-OWP/sac-sma" "extern/$model/$model"
            cp "extern/$model/$model/ngen_files/sacbmi.pc.in" \
               "extern/$model/$model/ngen_files/CMakeLists.txt" \
               "extern/$model" 2>/dev/null || true

            cmake_build "extern/$model" "extern/$model/$model/$builddir" \
                -DCMAKE_BUILD_TYPE=Release
            ;;

        *)
            echo "Unknown model: $model"
            ;;
        esac
    done

    popd >/dev/null || return 1
}

if [ "$BUILD_NGEN" == "ON" ]; then
    echo "Building ngen..."
    build_ngen
fi
if [ "$BUILD_MODELS" == "ON" ]; then
    echo "Building models..."
    build_models --clean
fi
if [ "$BUILD_TROUTE" == "ON" ]; then
    echo "Building troute..."
    build_troute
fi
