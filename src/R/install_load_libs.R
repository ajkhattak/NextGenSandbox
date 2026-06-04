######################### INSTALL REQUIRED PACKAGES ############################
# STEP #1: The packages need to run Hydrofabric tools for subsetting basins
################################################################################
#install.packages("renv")
#renv::init()
os_type <- Sys.info()[["sysname"]]
message("Checking R package dependencies for NextGenSandbox subset workflow...")
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
  "whitebox", "Metrics", "dplyr", "glue", "raster",
  "jsonlite", "ggplot2", "pbapply", "yaml",
  "dataRetrieval", "exactextractr", "sf", "terra"
)

github_packages <- c(
  "owp-spatial/hfsubsetR",
  "mikejohnson51/zonal"
)

installed <- rownames(installed.packages())

for (pkg in cran_packages) {
  if (!pkg %in% installed) {
    message("Installing CRAN package: ", pkg)
    install.packages(pkg, dependencies = TRUE)
  } else {
    message("Found CRAN package: ", pkg)
  }
}

if (!requireNamespace("remotes", quietly = TRUE)) {
  message("Installing CRAN package: remotes")
  install.packages("remotes")
} else {
  message("Found CRAN package: remotes")
}

for (repo in github_packages) {
  pkg <- basename(repo)
  if (!requireNamespace(pkg, quietly = TRUE)) {
    message("Installing GitHub package: ", repo)
    remotes::install_github(repo, upgrade = "never", dependencies = TRUE, build_vignettes = FALSE, Ncpus = 4)
  } else {
    message("Found GitHub package: ", pkg)
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
   "rvenv/vevn_subset/lib/R/library/WBT/whitebox_tools"
   )

  if (file.exists(wbt_expected)) {

    Sys.setenv(WHITEBOX_EXE = wbt_expected)
    whitebox::wbt_init(exe_path = wbt_expected)
    message("Using existing WhiteboxTools: ", wbt_expected)
  } else {

    message("WhiteboxTools not found. Installing...")

    custom_lib <- file.path(
      sandbox_build_dir,
      "rvenv/vevn_subset/lib/R/library"
    )

    whitebox::install_whitebox(pkg_dir = custom_lib, force = TRUE)

    if (file.exists(wbt_expected)) {
     Sys.setenv(WHITEBOX_EXE = wbt_expected)
     whitebox::wbt_init(exe_path = wbt_expected)
     message("WhiteboxTools installed at: ", wbt_expected)
    } else {
     stop("WhiteboxTools installation failed!")
   }

 }
} else if (os_type == "Darwin") {
   if (!whitebox::check_whitebox_binary()) {
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
