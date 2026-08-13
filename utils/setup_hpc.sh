#!/bin/bash
#
# Example HPC environment setup for building ngen/models needed for the Sandbox workflow.
# NOTE: 
# - You must adjust module names/versions to match your HPC system.
# - Set NETCDF_ROOT and BOOST_ROOT

# Optional: clear currently-loaded modules
module purge

##############################################
# NOAA URSA setup
# installed own python 3.11 using install_python.sh script
module load openmpi/4.1.6
module load netcdf-fortran/4.6.1
module load cmake/3.30.2
module load sqlite
module load udunits

# Use the wrappers from the loaded OpenMPI module. They invoke the compiler
# family with which that OpenMPI installation was built.
export CC="$(command -v mpicc)"
export CXX="$(command -v mpicxx)"
export FC="$(command -v mpifort)"
export F90="$FC"

# Modify this
export NETCDF_ROOT=/apps/spack-2024-12/linux-rocky9-x86_64/gcc-11.4.1/netcdf-fortran-4.6.1-rxwle72kj3anm4uess3ixiqg7ezgq4vk

# Preserve LIBRARY_PATH entries supplied by the compiler and NetCDF modules.
# t-route uses native extension link steps that rely on these paths. Do not
# replace LIBRARY_PATH with LD_LIBRARY_PATH; the latter may contain unrelated
# runtime libraries from other compiler stacks.

# Download boost using
# wget https://boostorg.jfrog.io/artifactory/main/release/1.88.0/source/boost_1_88_0.tar.gz
# tar -xzf boost_1_88_0.tar.gz
export BOOST_ROOT=/full/path/to/boost_1_88_0

# OR USE MPI Compilers explicitly
#export FC=`which gfortran`
#export F90=$FC
#export CC=`which mpicc`
#export CXX=`which mpicxx`

###############################################
### --- Compiler + MPI Stack --- ###
# Load a consistent compiler / MPI toolchain
#module load GCC/12.3.0
#module load OpenMPI/4.1.5

### --- Build & Utility Tools --- ###
#module load CMake/3.26.3
#module load Python/3.11.3

### --- Libraries --- ###
#module load Boost/1.82.0
#module load UDUNITS/2.2.28
#module load SQLite/3.42.0


### --- Optional: Fortran NetCDF --- ###
# These must match the same compiler / MPI version
#module load netcdf/4.9.0
#module load netcdf-fortran/4.6.0

### --- Compilers --- ###
# Set Fortran and C compilers explicitly
#export FC=$(which gfortran)
#export F90=$(which gfortran)
#export CC=$(which gcc)
#export CXX=$(which g++)



# OR TO BE MORE SPECIFIC -- you must adjust versions to match your HPC modules
#export CC=<path_to_gcc12.x.0>/gcc/12.x.0/bin/gcc
#export CXX=<path_to_gcc12.x.0>/g++/12.x.0/bin/g++
#export FC=<path_to_gcc12.x.0>/12.x.0/bin/gfortran
#export F90=<path_to_gcc12.x.0>/12.x.0/bin/gfortran

### --- NetCDF paths (optional) --- ###
# If your HPC has netcdf-fortran in a standard location you may not need this
# run: which nf-config to get the path
#export NETCDF_ROOT=<path_to_netcdf-fortran>/netcdf-fortran/4.6.0


echo "Environment configured for Sandbox Models build."

#############################################################################################

# If running on AWS EC2 instance, run setup_ec2.sh before bulding models to setup the EC2 instance

# Setup bash file (non-HPC env)
#  - Refer to the instructions here: (utils/setup_ec2.sh, line 23)
#  - For a quick reference: set the following environment variables in your bash file
#    export CC=/usr/local/opt/gcc@11/bin/gcc-11
#    export CXX=/usr/local/opt/gcc@11/bin/g++-11
#    export FC=/usr/local/opt/gcc@11/bin/gfortran-11
#    export F90=${FC}  # Alias for Fortran compiler
#    export CFORT=${FC}  # Alias for Fortran compiler
#    export NETCDF_ROOT=/usr/local/opt/netcdf-fortran
#    export PATH="/usr/local/opt/gcc@11/bin:$PATH"
