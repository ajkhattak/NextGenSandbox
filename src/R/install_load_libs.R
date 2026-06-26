######################### INSTALL REQUIRED PACKAGES ############################
# STEP #1: The packages need to run Hydrofabric tools for subsetting basins.
#
# Modes:
#   --install  Install missing dependencies, then load/check them.
#   --check    Only load/check dependencies. Do not install anything.
#
# Default is --install to preserve direct use from RStudio and bootstrap.
################################################################################
args <- commandArgs(trailingOnly = TRUE)
mode <- Sys.getenv("SANDBOX_R_DEPS_MODE", unset = "install")

if ("--check" %in% args) {
  mode <- "check"
} else if ("--install" %in% args) {
  mode <- "install"
}

if (!mode %in% c("install", "check")) {
  stop("Invalid dependency mode: ", mode, ". Use --install or --check.")
}

os_type <- Sys.info()[["sysname"]]
message("Checking R package dependencies for NextGenSandbox subset workflow...")
message("Dependency mode: ", mode)
message("R version: ", R.version.string)
message("Platform: ", os_type)

#custom_lib <- .libPaths()[1]

#dir.create(custom_lib, recursive = TRUE, showWarnings = FALSE)
#.libPaths(custom_lib)

options(repos = c(CRAN = "https://cloud.r-project.org"))

if (Sys.info()['sysname'] == "Windows") {
  options(download.file.method = "curl", download.file.extra="-k -L")
}

cran_packages <- c(
  "whitebox", "Metrics", "dplyr", "glue", "magrittr", "raster",
  "jsonlite", "ggplot2", "pbapply", "yaml",
  "dataRetrieval", "exactextractr", "sf", "terra", "santoku"
)

github_packages <- c(
  "owp-spatial/hfsubsetR",
  "mikejohnson51/zonal"
)

installed <- rownames(installed.packages())
missing_cran <- cran_packages[!cran_packages %in% installed]

install_r_package <- function(pkg) {
  if (pkg == "santoku") {
    message("Installing R package from R-universe: ", pkg)
    install.packages(
      pkg,
      repos = c(
        "https://hughjonesd.r-universe.dev",
        "https://cloud.r-project.org"
      ),
      dependencies = TRUE
    )
  } else {
    message("Installing CRAN package: ", pkg)
    install.packages(pkg, dependencies = TRUE)
  }
}

package_source_label <- function(pkg) {
  if (pkg == "santoku") {
    return("R-universe/installed")
  }

  "CRAN/installed"
}

if (mode == "install") {
  for (pkg in cran_packages) {
    if (!pkg %in% installed) {
      install_r_package(pkg)
    } else {
      message("Found ", package_source_label(pkg), " package: ", pkg)
    }
  }

  installed <- rownames(installed.packages())
  missing_cran <- cran_packages[!cran_packages %in% installed]
  if (length(missing_cran) > 0) {
    stop(
      "Failed to install required R package(s): ",
      paste(missing_cran, collapse = ", "),
      "\nInstall these packages in your R environment before running sandbox --subset."
    )
  }
} else {
  for (pkg in cran_packages) {
    if (pkg %in% installed) {
      message("Found ", package_source_label(pkg), " package: ", pkg)
    }
  }

  if (length(missing_cran) > 0) {
    stop(
      "Missing required R package(s): ",
      paste(missing_cran, collapse = ", "),
      "\nInstall subset dependencies before running sandbox --subset:\n",
      "  ./bootstrap.sh --subset\n",
      "or run/source src/R/install_load_libs.R --install in your R environment."
    )
  }
}

installed <- rownames(installed.packages())

if (mode == "install") {
  if (!requireNamespace("remotes", quietly = TRUE)) {
    message("Installing CRAN package: remotes")
    install.packages("remotes")
  } else {
    message("Found CRAN package: remotes")
  }
} else {
  if (!requireNamespace("remotes", quietly = TRUE)) {
    stop(
      "Missing required CRAN package: remotes\n",
      "Install subset dependencies before running sandbox --subset:\n",
      "  ./bootstrap.sh --subset\n",
      "or run/source src/R/install_load_libs.R --install in your R environment."
    )
  } else {
    message("Found CRAN package: remotes")
  }
}

for (repo in github_packages) {
  pkg <- basename(repo)
  if (!requireNamespace(pkg, quietly = TRUE)) {
    if (mode == "install") {
      message("Installing GitHub package: ", repo)
      remotes::install_github(
        repo,
        upgrade = "never",
        dependencies = c("Depends", "Imports", "LinkingTo"),
        build_vignettes = FALSE,
        Ncpus = 4
      )
    } else {
      stop(
        "Missing required GitHub package: ",
        pkg,
        " (",
        repo,
        ")\nInstall subset dependencies before running sandbox --subset:\n",
        "  ./bootstrap.sh --subset\n",
        "or run/source src/R/install_load_libs.R --install in your R environment."
      )
    }
  } else {
    message("Found GitHub package: ", pkg)
  }
}

missing_github <- vapply(
  basename(github_packages),
  function(pkg) !requireNamespace(pkg, quietly = TRUE),
  logical(1)
)

if (any(missing_github)) {
  stop(
    "Missing required GitHub package(s): ",
    paste(names(missing_github)[missing_github], collapse = ", "),
    "\nInstall subset dependencies before running sandbox --subset:\n",
    "  ./bootstrap.sh --subset\n",
    "or run/source src/R/install_load_libs.R --install in your R environment."
  )
}

prepare_whitebox <- function(exe_path) {
  whitebox_data_dir <- file.path(whitebox::wbt_data_dir(), "WBT")
  dir.create(whitebox_data_dir, recursive = TRUE, showWarnings = FALSE)

  Sys.setenv(
    WHITEBOX_EXE = exe_path,
    R_WHITEBOX_EXE_PATH = exe_path
  )

  initialized <- whitebox::wbt_init(exe_path = exe_path)
  if (!isTRUE(initialized) || !whitebox::check_whitebox_binary()) {
    stop("WhiteboxTools executable could not be initialized: ", exe_path)
  }
}

# WhiteboxTools install (still sets env dynamically)
if (os_type == "Linux") {
  sandbox_build_dir <- Sys.getenv("SANDBOX_BUILD_DIR")

  # Ensure it exists
  if (sandbox_build_dir == "" || is.na(sandbox_build_dir)) {
   stop("SANDBOX_BUILD_DIR environment variable is not set. Please export SANDBOX_BUILD_DIR before running this script.")
 }

 wbt_expected <- file.path(
   sandbox_build_dir,
   "rvenv/venv_subset/lib/R/library/WBT/whitebox_tools"
   )

  if (file.exists(wbt_expected)) {

    prepare_whitebox(wbt_expected)
    message("Using existing WhiteboxTools: ", wbt_expected)
  } else {

    if (mode == "check") {
      stop(
        "WhiteboxTools executable not found: ",
        wbt_expected,
        "\nInstall subset dependencies before running sandbox --subset:\n",
        "  ./bootstrap.sh --subset\n",
        "or run/source src/R/install_load_libs.R --install in your R environment."
      )
    }

    message("WhiteboxTools not found. Installing...")

    custom_lib <- file.path(
      sandbox_build_dir,
      "rvenv/venv_subset/lib/R/library"
    )

    whitebox::install_whitebox(pkg_dir = custom_lib, force = TRUE)

    if (file.exists(wbt_expected)) {
     prepare_whitebox(wbt_expected)
     message("WhiteboxTools installed at: ", wbt_expected)
    } else {
     stop("WhiteboxTools installation failed!")
   }

 }
} else if (os_type == "Darwin") {
   if (!whitebox::check_whitebox_binary()) {
    if (mode == "check") {
      stop(
        "WhiteboxTools executable not found for the whitebox R package.\n",
        "Install subset dependencies before running sandbox --subset:\n",
        "  ./bootstrap.sh --subset\n",
        "or run/source src/R/install_load_libs.R --install in your R environment."
      )
    }
    whitebox::install_whitebox()
    }
  }

#if (!whitebox::check_whitebox_binary()) {
#  whitebox::install_whitebox(pkg_dir = custom_lib, force = TRUE)
#  wbt_path <- list.files(custom_lib, pattern = "whitebox_tools$", recursive = TRUE, full.names = TRUE)
#  if (length(wbt_path) > 0) {
#    Sys.setenv(WHITEBOX_EXE = wbt_path[1])
#    whitebox::wbt_init(exe_path = Sys.getenv("WHITEBOX_EXE"))
#    message("WhiteboxTools executable set to: ", Sys.getenv("WHITEBOX_EXE"))
#  } else {
#    warning("Could not locate WhiteboxTools binary after install!")
#  }
#}


suppressPackageStartupMessages({
  library(zonal)
  library(whitebox)
  library(sf)
  library(terra)
  library(exactextractr)
  library(dplyr)
  library(magrittr)
  library(glue)
  library(raster)
  library(jsonlite)
  library(ggplot2)
  library(Metrics)
  library(pbapply)
  library(parallel)
  library(yaml)
  library(dataRetrieval)
})

message("R package dependency check complete.")

###########
# if(!requireNamespace("remotes", quietly=TRUE))
#   install.packages("remotes")
# 
# if(!requireNamespace("hfsubsetR", quietly=TRUE))
#   remotes::install_github("owp-spatial/hfsubsetR")
# 
# if(!requireNamespace("zonal", quietly=TRUE))
#   remotes::install_github("mikejohnson51/zonal")
# 
# if(!requireNamespace("whitebox", quietly=TRUE)) {
#   install.packages("whitebox")
#   whitebox::install_whitebox()
# }
# 
# if(!requireNamespace("Metrics", quietly=TRUE))
#   install.packages("Metrics")
# 
# if(!requireNamespace("dplyr", quietly=TRUE))
#    install.packages("dplyr")
# 
# 
# if(!requireNamespace("glue", quietly=TRUE)) {
#   install.packages("glue")
# }
#   
# 
# if(!requireNamespace("raster", quietly=TRUE))
#    install.packages("raster")
# 
# if(!requireNamespace("jsonlite", quietly=TRUE))
#    install.packages("jsonlite")
# 
# if(!requireNamespace("ggplot2", quietly=TRUE))
#    install.packages("ggplot2")
# 
# if(!requireNamespace("pbapply", quietly=TRUE))
#    install.packages("pbapply")
# 
# if(!requireNamespace("yaml", quietly=TRUE))
#    install.packages("yaml")
# 
# if(!requireNamespace("dataRetrieval", quietly=TRUE)) 
#    install.packages("dataRetrieval")
# 
# if(!requireNamespace("exactextractr", quietly=TRUE)) 
#   install.packages("exactextractr")
# 
# library(zonal)
# library(whitebox)
# library(sf)
# library(terra)
# library(exactextractr)
# library(dplyr)
# suppressPackageStartupMessages(library(glue))
# library(raster)
# suppressPackageStartupMessages(library(raster))
# library(jsonlite)
# library(ggplot2)
# library(Metrics)
# library(pbapply)
# library(parallel)
# library(yaml)
# library(dataRetrieval)
