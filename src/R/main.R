# @author Ahmad Jan Khattak
# @email ahmad.jan.khattak@noaa.gov
# @author Lauren Bolotin
# @email lauren.bolotin@noaa.gov
# @date  December 22, 2023

# The script downloads geopackge(s) given USGS gauge id(s) (also can read gpkg from the disk)
# Computes TWI, GIUH, Nash cascade parameters, and extracts model attributes from source,
# source could either be hydrofabric S3 endpoint or local sync hydrofabric (preferred for speed)

# INPUT  : yaml file (see below)
# OUTPUT : a geopackage with all model parameters, which is used for generating config and realization files

######################## REQUIRED INPUT #######################################
# Key steps are highlight as:
# STEP #1: Setup (REQUIRED) (main.R)
# Workflow steps
#   STEP #2:  Download geopackage (if needed)
#   STEP #3:  Add model attributes to the geopackage
#   STEP #4:  Compute TWI and width function
#   STEP #5:  Compute GIUH
#   STEP #6:  Compute Nash cascade parameters (N and K) for surface runoff
#   STEP #7:  Compute terrain slope from the DEM
#   STEP #8a: Compute NLCD landcover
#   STEP #8b: Compute aspect from the DEM
#   STEP #9:  Append GIUH, TWI, width function, Nash cascade parameters, slope, 
#   aspect, and vegetation type to divide_attributes layer


# STEP 8a REQUIRED - download NLCD data for the domain of interest and set the path to the NLCD data
# Links to recent NLCD data for each domain:
# - CONUS (2021): https://www.mrlc.gov/downloads/sciweb1/shared/mrlc/data-bundles/Annual_NLCD_LndCov_2021_CU_C1V1.zip
# - Puerto Rico (2001): https://www.mrlc.gov/downloads/sciweb1/shared/mrlc/data-bundles/PR_landcover_wimperv_10-28-08_se5.zip
# - Hawaii (2001): https://www.mrlc.gov/downloads/sciweb1/shared/mrlc/data-bundles/HI_landcover_wimperv_9-30-08_se5.zip
# - Alaska (2011): https://www.mrlc.gov/downloads/sciweb1/shared/mrlc/data-bundles/NLCD_2016_Land_Cover_AK_20200724.zip


################################################################################
library(yaml)
args <- commandArgs(trailingOnly = TRUE)
Sys.setenv("AWS_NO_SIGN_REQUEST" = "YES")


################################ SETUP #########################################
# STEP: Workflow setup
# - Set sandbox_config.yaml file under $SANDBOX_DIR/configs directory
# - Set sandbox_dir and infile_config explicitly when running in RStudio (see below)

Setup <-function() {

  if (length(args) == 2) {
    infile_config <- args[1]
    sandbox_dir   <<- args[2]
    print (paste0("Config file provided: ", infile_config))
  } else if (length(args) > 2) {
    stop("Usage: RScript main.R input.yaml sandbox_dir")
  } else {
    # Set paths explicitly when running in RStudio
    sandbox_dir   <<- "<path/to/sandboxhub>" 
    infile_config <-  "<path/to/sandbox_config.yaml>"
  }

  if (!file.exists(infile_config)) {
    print(paste0("input config file does not exist, provided: ", infile_config))
    print ("Note: if running from RStudio, make sure sandbox_dir & infile_config are set propely (see src/R/main.R).")
    stop()
  }

  inputs = yaml.load_file(infile_config)

  output_dir    <<- inputs$general$input_dir
  hf_version    <<- inputs$subsetting$hydrofabric$version
  hf_gpkg_path  <<- inputs$subsetting$hydrofabric$gpkg_path
  
  if (is.null(hf_gpkg_path) || trimws(hf_gpkg_path) == "" || !file.exists(hf_gpkg_path)) {
    stop("Invalid input: 'subsetting$hydrofabric$gpkg_path' is missing, empty, or does not exist.")
  }

  suppressMessages(source(paste0(sandbox_dir, "/src/R/install_load_libs.R")))
  source(glue("{sandbox_dir}/src/R/custom_functions.R"))
  
  compute_divide_attributes <<- get_param(inputs, "subsetting$hydrofabric$compute_divide_attributes", TRUE)
  
  # Newer DEM, better for oCONUS and other previously problematic basins
  dem_input_file <<- get_param(inputs, "subsetting$dem$input_file", NULL)
  
  if (is.null(dem_input_file)) {
    dem_input_file <<- "s3://lynker-spatial/gridded/3DEP/USGS_seamless_DEM_13.vrt"
  } else if (trimws(dem_input_file) == "") {
    stop("Invalid input: 'subsetting$dem$input_file' was provided but is empty. 
         Either remove it to use the default DEMor provide a valid DEM file.")
  }

  dem_output_dir  <<- get_param(inputs, "subsetting$dem$output_dir", "")
  dem_aggregate_factor <<- get_param(inputs, "subsetting$dem$aggregate_factor", 3)
  
  # NLCD vegetation data parameters
  veg_calc_enabled      <<- get_param(inputs, "subsetting$vegetation$enabled", FALSE)
  veg_nlcd_path         <<- get_param(inputs, "subsetting$vegetation$nlcd_path", FALSE)
  veg_method            <<- get_param(inputs, "subsetting$vegetation$classification_method", "majority")
  
  option <- get_param(inputs, "subsetting$gages$option", NULL)
  
  if (is.null(option)) stop("subsetting$gages$option must be defined. OPTIONS: ids | file | gpkg")
  
  allowed <- c("ids", "file", "gpkg")
  
  if (!(option %in% allowed)) {
    stop(glue("Invalid option '{option}'. Must be one of: {toString(allowed)}"))
  }
  
  option_use_ids <<- option_use_file <<- option_use_gpkg <<- FALSE
  
  if (option == "ids") {
    gage_ids <<- get_param(inputs, "subsetting$gages$ids", NULL)
    if (is.null(gage_ids)) stop("ids must be provided when option = 'ids'")
    option_use_ids <<- TRUE
  }
  
  if (option == "file") {
    gage_file   <<- get_param(inputs, "subsetting$gages$file$path", NULL)
    column_name <<- get_param(inputs, "subsetting$gages$file$column", "")
    option_use_file <<- TRUE
  }
  
  if (option == "gpkg") {
    gpkg_dir  <<- get_param(inputs, "subsetting$gages$gpkg$dir", NULL)
    pattern   <<- get_param(inputs, "subsetting$gages$gpkg$pattern", "gage_")
    selected_gpkgs  <<- get_param(inputs, "subsetting$gages$gpkg$select", NULL)
    option_use_gpkg <<- TRUE
  }
  
  if (!file.exists(output_dir)) {
    print(glue("Output directory does not exist, provided: {output_dir}"))
    return(1)
  }
  
  setwd(output_dir)
  wbt_wd(getwd())
  
  failed_dir <- file.path(output_dir, "basins_failed")
  
  if (dir.exists(failed_dir)) {
    unlink(failed_dir, recursive = TRUE, force = TRUE)
  }
  
  dir.create(failed_dir, recursive = TRUE)
  
  return(0)
}

# call setup function to read parameters from config file
tryCatch({
  Setup() 
}, error = function(e) {
  message("Setup failed: ", e$message)
  stop()
})

print ("SETUP DONE!")


################################ OPTIONS #######################################

start_time <- Sys.time()
if (option_use_ids == TRUE || option_use_file == TRUE) {
  ################################ EXAMPLE 1 ###################################
  # For this example either provide a gage ID or a file to read gage IDs from
  # Modify this part according your settings
  
  if (option_use_file == TRUE) {
    d = read.csv(gage_file,colClasses = c("character")) 
    gage_ids <- d[[column_name]]
      gage_ids <- zeroPad(gage_ids, 8)

  }
  
  stopifnot( length(gage_ids) > 0)

  DriverGivenGageIDs(gage_id = gage_ids, 
                    output_dir = output_dir,
                    dem_output_dir = dem_output_dir,
                    dem_input_file = dem_input_file,
                    veg_calc_enabled  = veg_calc_enabled,
                    veg_nlcd_path     = veg_nlcd_path, 
                    veg_method        = veg_method,
                    compute_divide_attributes = compute_divide_attributes,
                    dem_aggregate_factor = dem_aggregate_factor
                    )
  
  
} else if (option_use_gpkg == TRUE) {
  
  gage_files = list.files(gpkg_dir, full.names = TRUE, pattern = pattern)

  if (dir.exists(gpkg_dir)) {
    gage_files <- list.files(gpkg_dir, full.names = TRUE, pattern = pattern)

  } else if (file.exists(gpkg_dir)) {
    # gpkg_dir is actually a file
    gage_files <- gpkg_dir
  } else {
    stop("gpkg_dir does not exist")
  }

 if (!is.null(selected_gpkgs)) {
   # collapse multiple selections into a regex OR
   pattern <- paste(selected_gpkgs, collapse = "|")
   matches <- grep(pattern, gage_files, value = TRUE)
  
   if (length(matches) == 0) {
     stop(glue(
       "None of the selected gage files were found.\n",
       "Selected: {toString(selected_gpkgs)}\n",
       "Available: {toString(basename(gage_files))}"
     ))
   }
   
   gage_files <- matches

 }
 
 print (glue("GPKG FILES : {gage_files}"))

  DriverGivenGPKG(gage_files = gage_files, 
                  gpkg_dir   = gpkg_dir, 
                  output_dir = output_dir,
                  dem_output_dir = dem_output_dir,
                  dem_input_file = dem_input_file,
                  veg_calc_enabled  = veg_calc_enabled,
                  veg_nlcd_path     = veg_nlcd_path, 
                  veg_method        = veg_method,
                  compute_divide_attributes = compute_divide_attributes,
                  dem_aggregate_factor = dem_aggregate_factor
                  )
}


end_time <- Sys.time()
time_taken <- as.numeric(end_time - start_time, units = "secs")
print (paste0("Total Time Taken = ", time_taken))

# check for failed basins
basins_failed <- glue("{output_dir}/basins_failed")

if (dir.exists(basins_failed)) {
  files <- list.files(basins_failed, full.names = TRUE)
  subdirs <- files[dir.exists(files)]
  if (length(subdirs) > 0) {
    subdir_names <- basename(subdirs)
    print("List of Basins failed..")
    print(subdir_names)
  }
  else {
    print ("All Basins Passed!!!")
  }
} 


################################### DONE #######################################
