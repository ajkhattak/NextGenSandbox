#----------------------- DOWNLOAD GEOPACKAGE ----------------------------------#
# STEP #3: provide USGS gauge id or your own geopackage (single or multiple)
#------------------------------------------------------------------------------#

HYDROFABRIC_DIR <- "hydrofabric"

hydrofabric_path <- function(cat_dir, gpkg_name) {
  file.path(cat_dir, HYDROFABRIC_DIR, gpkg_name)
}

subsetting_work_dir <- function(id, config) {
  if (identical(config$resource_layout, "resource")) {
    return(file.path(config$input_dir, paste0(".", id, "_subset_work")))
  }

  file.path(config$input_dir, id)
}

subset_gpkg_path <- function(id, config, gpkg_name = glue("gage_{id}.gpkg")) {
  if (identical(config$resource_layout, "resource")) {
    return(file.path(config$input_dir, HYDROFABRIC_DIR, gpkg_name))
  }

  hydrofabric_path(file.path(config$input_dir, id), gpkg_name)
}

clean_subset_work_dir <- function(id, cat_dir, config) {
  if (!config$hydrofabric$compute_divide_attributes) {
    return()
  }

  if (identical(config$resource_layout, "gage")) {
    clean_move_dem_dir(
      id = id,
      output_dir = config$input_dir,
      dem_output_dir = config$dem$output_dir
    )
    return()
  }

  dem_source <- file.path(cat_dir, "dem")

  if (is.null(config$dem$output_dir) || config$dem$output_dir == "") {
    if (dir.exists(dem_source)) {
      unlink(dem_source, recursive = TRUE, force = TRUE)
    }
  } else if (dir.exists(dem_source)) {
    dem_target <- if (config$dem$output_dir == "dem") {
      file.path(config$input_dir, "dem", id)
    } else {
      file.path(config$dem$output_dir, id)
    }

    if (dir.exists(dem_target)) {
      unlink(dem_target, recursive = TRUE, force = TRUE)
    }
    dir.create(dirname(dem_target), recursive = TRUE, showWarnings = FALSE)
    file.rename(dem_source, dem_target)
  }
}

strip_ansi <- function(text) {
  gsub(paste0(intToUtf8(27), "\\[[0-9;]*[[:alpha:]]"), "", text)
}

write_subset_failure <- function(id, cat_dir, error) {
  error_message <- strip_ansi(conditionMessage(error))
  error_call <- conditionCall(error)
  error_file <- file.path(cat_dir, "subsetting_error.txt")

  details <- c(
    glue("Gage/resource: {id}"),
    glue("Working directory: {cat_dir}"),
    glue("Error: {error_message}")
  )

  if (!is.null(error_call)) {
    details <- c(
      details,
      glue("Call: {strip_ansi(paste(deparse(error_call), collapse = ' '))}")
    )
  }

  writeLines(details, error_file)

  cat(glue("[ERROR] Gage/resource {id} failed during subsetting.\n"))
  cat(glue("[ERROR] {error_message}\n"))
  cat(glue("[ERROR] Details written to: {error_file}\n"))
}


############################ DRIVER_GIVEN_GAGE_ID ##############################
# main script that loops over all the gage IDs and computes giuh/twi etc.
DriverGivenGageIDs <- function(gage_ids, config)
  {
  
  print ("DRIVER GIVEN GAGE ID")
  
  lapply(X = gage_ids, FUN = ProcessCatchmentID, config = config)

  setwd(config$input_dir)

}

#-----------------------------------------------------------------------------#
# Function called by pblapply for parallel processing by each worker/node
# for each catchment id
# it calls run_driver for each gage id and computes giuh/twi etc.

ProcessCatchmentID <- function(id, config) {

  print ("PROCESS CATCHMENT ID FUNCTION")

  cat_dir = subsetting_work_dir(id, config)
  gpkg_file = subset_gpkg_path(id, config)
  dir.create(cat_dir, recursive = TRUE, showWarnings = FALSE)
  dir.create(dirname(gpkg_file), recursive = TRUE, showWarnings = FALSE)
  setwd(cat_dir)
  wbt_wd(getwd())

  # DEM and related files are only needed when derived divide attributes are computed.
  if (config$hydrofabric$compute_divide_attributes) {
    dir.create("dem", recursive = TRUE, showWarnings = FALSE)
  }
  dir.create(HYDROFABRIC_DIR, recursive = TRUE, showWarnings = FALSE)

  failed <- TRUE

  tryCatch({
    cat ("Processing catchment: ", id, "\n")
    RunDriver(gage_id = id,
              gpkg_file = gpkg_file,
              config = config
              )

    failed <- FALSE
  }, error = function(e) {
    failed <- TRUE
    write_subset_failure(id, cat_dir, e)
  })

  # move (or delete) dem output directory out of the main output directory

  clean_subset_work_dir(id, cat_dir, config)

  if (failed) {
    cat ("Gage/resource failed:", id, "\n")
    if (identical(config$resource_layout, "resource") && file.exists(gpkg_file)) {
      unlink(gpkg_file, force = TRUE)
    }
    failed_dir <- subsetting_failure_dir(config$input_dir)
    cat_failed_dir = file.path(failed_dir, id)

    if (file.exists(cat_failed_dir) ) {
      unlink(cat_failed_dir, recursive = TRUE)
    }

    dir.create(failed_dir, recursive = TRUE, showWarnings = FALSE)
    file.rename(cat_dir, cat_failed_dir)

  }
  else {
    cat ("Gage/resource passed:", id, "\n")
    if (identical(config$resource_layout, "resource") && dir.exists(cat_dir)) {
      unlink(cat_dir, recursive = TRUE, force = TRUE)
    }
  }

}

############################ DRIVER_GIVEN_GPKG #################################
# main script that loops over all the geopackages and computes giuh/twi etc.
DriverGivenGPKG <- function(gage_files, config)
  {

  print ("DRIVER GIVEN GEOPACKAGE FUNCTION")

  stopifnot(length(gage_files) >= 1)

  cats_failed <- lapply(X = gage_files, FUN = ProcessGPKG, config = config)
  setwd(config$input_dir)

  return(cats_failed)
}

ProcessGPKG <- function(gfile, config) {

  print ("PROCESS GPKG FUNCTION")

  # vector containing IDs of failed (for some reason) basins
  cats_failed <- numeric(0)

  id <- subsetting_gpkg_id(gfile)

  gpkg_file = subset_gpkg_path(id, config, basename(gfile))
  cat_dir = subsetting_work_dir(id, config)
  dir.create(cat_dir, recursive = TRUE, showWarnings = FALSE)

  setwd(cat_dir)
  wbt_wd(getwd())

  # DEM and related files are only needed when derived divide attributes are computed.
  if (config$hydrofabric$compute_divide_attributes) {
    dir.create("dem", recursive = TRUE, showWarnings = FALSE)
  }
  dir.create(HYDROFABRIC_DIR, recursive = TRUE, showWarnings = FALSE)

  failed <- TRUE

  tryCatch({
    cat ("Processing catchment: ", id, "\n")

    dir.create(dirname(gpkg_file), recursive = TRUE, showWarnings = FALSE)
    file.copy(gfile, gpkg_file, overwrite = TRUE)

    RunDriver(gpkg_file = gpkg_file,
              config = config
              )

    failed <- FALSE

    }, error = function(e) {
      failed <- TRUE
      write_subset_failure(id, cat_dir, e)
    })

  # move (or delete) dem output directory out of the main output directory
  clean_subset_work_dir(id, cat_dir, config)

  if (failed) {
    cat ("Gage/resource failed:", id, "\n")
    if (identical(config$resource_layout, "resource") && file.exists(gpkg_file)) {
      unlink(gpkg_file, force = TRUE)
    }
    failed_dir <- subsetting_failure_dir(config$input_dir)
    cat_failed_dir = file.path(failed_dir, id)

    if (file.exists(cat_failed_dir) ) {
      unlink(cat_failed_dir, recursive = TRUE)
    }

    dir.create(failed_dir, recursive = TRUE, showWarnings = FALSE)
    file.rename(cat_dir, cat_failed_dir)

  }
  else {
    cat ("Gage/resource passed:", id, "\n")
    if (identical(config$resource_layout, "resource") && dir.exists(cat_dir)) {
      unlink(cat_dir, recursive = TRUE, force = TRUE)
    }
  }
  
  return(cats_failed)

}

############################# RUN_DRIVER ######################################
# main runner function
RunDriver <- function(gage_id = NULL, 
                      gpkg_file = NULL,
                      config
                      ) {

  print ("RUN DRIVER FUNCTION")

  if (is.null(gage_id) && is.null(gpkg_file)) {
    stop("RunDriver requires either 'gage_id' or 'gpkg_file'.")
  }

  outfile <- gpkg_file
  if (!is.null(gage_id)) {
    start.time <- Sys.time()
    if (is.null(outfile)) {
      outfile <- hydrofabric_path(getwd(), glue("gage_{gage_id}.gpkg"))
    }

    # Get domain info for this gage
    state_code <- get_gage_state_code(gage_id)
    state <- stateCd$STUSAB[which(stateCd$STATE == state_code)]
      if (state %in% c("HI", "AK")) {
        domain <- tolower(state)
      } else if (state %in% c("PR", "VI")) {
        domain <- "prvi"
      } else {
        domain <- "conus"
      }
    
    # If the gpkg exists, use that for subsetting
    layers = c("divides", "flowpaths", "network", "nexus",
               "flowpath-attributes","divide-attributes")
    
    if (config$hydrofabric$version == "2.2") {
      if (file.exists(config$hydrofabric$gpkg_path)) {
        print('USING LOCAL GPKG FILE FOR SUBSETTING')
        hf_gpkg <- config$hydrofabric$gpkg_path
      } else {
        print('USING REMOTE GPKG FILE FOR SUBSETTING')
        hf_gpkg = NULL
      }

      if (domain != "conus") { # If the gage is in oCONUS, query using flowpath id

        flowpath_id <- sf::read_sf(hf_gpkg, query = glue::glue(
          "SELECT hf_id FROM hydrolocations WHERE hl_reference || '-' || hl_link = 'Gages-{gage_id}'"
        ))$hf_id

        hfsubsetR::get_subset(comid = flowpath_id,
                              outfile = outfile,
                              gpkg = hf_gpkg,
                              hf_version = config$hydrofabric$version,
                              lyrs = layers,
                              type = 'nextgen',
                              overwrite = TRUE)
      } else { # If the gage is in CONUS, query using hl_uri
        hfsubsetR::get_subset(hl_uri = glue("gages-{gage_id}"),
                              outfile = outfile,
                              gpkg = hf_gpkg,
                              hf_version = config$hydrofabric$version,
                              lyrs = layers,
                              type = 'nextgen',
                              overwrite = TRUE)
      }
    } else if (config$hydrofabric$version == "2.1.1") {
      
      hfsubsetR::get_subset(nldi_feature = list(featureSource="nwissite", featureID=glue("USGS-{gage_id}")),
                            outfile = outfile, 
                            hf_version = config$hydrofabric$version,
                            domain = "conus",
                            lyrs = layers,
                            overwrite = TRUE)
      }
    
    time.taken <- as.numeric(Sys.time() - start.time, units = "secs") #end.time - start.time
    print (paste0("Time (geopackage) = ", time.taken))

  }

  # check if the divide-attributes layer has the same number of rows as the divides layer
  if (config$hydrofabric$compute_divide_attributes) {

    check_divs <- sf::st_read(outfile, layer = "divides", quiet = TRUE)
    check_attrs <- suppressWarnings(
      sf::st_read(outfile, layer = "divide-attributes", quiet = TRUE)
    )

    id_col <- "divide_id"

    missing_in_attrs <- setdiff(check_divs[[id_col]], check_attrs[[id_col]])

    missing_in_divs <- setdiff(check_attrs[[id_col]], check_divs[[id_col]])

    if (length(missing_in_attrs) > 0 || length(missing_in_divs) > 0) {
      stop(glue(
        "Mismatched rows detected between divides and divide-attributes. ",
        "divides rows: {nrow(check_divs)}; divide-attributes rows: {nrow(check_attrs)}. ",
        "IDs in divides but not in divide-attributes: {toString(missing_in_attrs)}. ",
        "IDs in divide-attributes but not in divides: {toString(missing_in_divs)}."
      ))
    }

  } else {
    print(glue("compute_divide_attributes is FALSE... returning"))
    return()
  }

  ## Stop if .gpkg does not exist

  if (!file.exists(outfile)) {
    stop(glue("Geopackage file does not exist: {outfile}"))
    }

  ############################### GET DEM ##################################
  
  start.time <- Sys.time()
  
  GetDEM(
    div_infile = outfile,
    config$dem$input_file,
    buffer_m = 2000,
    aggregate_factor = config$dem$aggregate_factor
  )

  time.taken <- as.numeric(Sys.time() - start.time, units = "secs") #end.time - start.time
  print (paste0("Time (dem func) = ", time.taken))

  ############################### GENERATE TWI ##################################
  # Note: The default distribution = 'quantiles'
  
  print("STEP: Computing TWI and Width function .................")
  start.time <- Sys.time()
  
  twi <- ComputeTWI(div_infile = outfile,
                    distribution = 'simple', 
                    nclasses = 30)

  width_dist <- ComputeWidth(div_infile = outfile)

  twi_dat_values = data.frame(ID = twi$divide_id, twi = twi$fun.twi,
                              width_dist = width_dist$fun.downslope_fp_length)

  # write TWI and width function layers to the geopackage
  names(twi_dat_values)
  colnames(twi_dat_values) <- c('divide_id', 'twi', 'width_dist')
  names(twi_dat_values)

  time.taken <- as.numeric(Sys.time() - start.time, units = "secs")
  print (paste0("Time (twi func) = ", time.taken))
  
  ############################### GENERATE GIUH ################################
  # There are many "model" options to specify the velocity.
  # Here we are using a simple approach: constant velocity as a function of upstream drainage area.
  
  print("STEP: Computing GIUH.................")
  start.time <- Sys.time()
  vel_channel     <- 1.0  # meter/second
  vel_overland    <- 0.1  # Fred: 0.1
  vel_gully       <- 0.2 # meter per second
  gully_threshold <- 30.0 # m (longest , closer to 10-30 m, Refs) 

  giuh_compute <- ComputeGIUH(div_infile = outfile, 
                              vel_channel, 
                              vel_overland, 
                              vel_gully, 
                              gully_threshold)
  
  # write GIUH layer to the geopackage
  giuh_dat_values = data.frame(ID = giuh_compute$divide_id, giuh = giuh_compute$fun.giuh_minute)
  colnames(giuh_dat_values) <- c('divide_id', 'giuh')

  time.taken <- as.numeric(Sys.time() - start.time, units = "secs")
  print (paste0("Time (giuh ftn) = ", time.taken))

  #######################. COMPUTE NASH CASCADE PARAMS ###########################

  print("STEP: Computing Nash Cascade parameters .............")
  start.time <- Sys.time()
  nash_params_surface <- GetNashParams(giuh_dat_values, calib_n_k = FALSE)

  time.taken <- as.numeric(Sys.time() - start.time, units = "secs") #end.time - start.time
  print (paste0("Time (nash func) = ", time.taken))

  ####################### CALCULATE VEGETATION TYPE ############################
  # Calculate vegetation type from NLCD data if enabled
  divides_with_veg <- NULL
  if (config$vegetation$enabled && file.exists(config$vegetation$nlcd_path)) {
    print("STEP: Computing vegetation type from NLCD data .................")
    start.time <- Sys.time()

    # Calculate vegetation type
    divides_with_veg <- ComputeVegTypeNLCD(
      outfile,
      config$vegetation$nlcd_path,
      config$vegetation$method,
      nclasses = 2
    )

    time.taken <- as.numeric(Sys.time() - start.time, units = "secs")
    print (paste0("Time (vegetation calc) = ", time.taken))
  } else if (config$vegetation$enabled) {
    print("WARNING: Vegetation calculation requested but NLCD data path not provided or file does not exist")
  }

  #######################. COMPUTE TERRAIN SLOPE ###########################
  # Take slope from the slope grid calculated in the TWI function
  print("STEP: Computing SLOPE .................")
  slope <-  slope_function(div_infile = outfile)

  #######################. COMPUTE ASPECT ###########################
  # Compute aspect from the DEM 
  print("STEP: Computing ASPECT .................")
  aspect <-  aspect_function(div_infile = outfile)

  ####################### WRITE MODEL ATTRIBUTE FILE ###########################
  # Append GIUH, TWI, width function, slope, and Nash cascade N and K parameters
  # to model attributes layers
  
  d_attr <- suppressWarnings(
    sf::read_sf(outfile, "divide-attributes")
  )

  d_attr$giuh <- giuh_dat_values$giuh             # append GIUH column to the model attributes layer
  d_attr$twi  <- twi_dat_values$twi               # append TWI column to the model attributes layer
  d_attr$width_dist <- twi_dat_values$width_dist  # append width distribution column to the model attributes layer

  d_attr$N_nash_surface <- nash_params_surface$N_nash

  d_attr$K_nash_surface <- nash_params_surface$K_nash
  d_attr$terrain_slope <- slope$mean.slope
  d_attr$terrain_aspect <- aspect$fun.aspect

  # Fix attribute naming issues (specific to PR hydrofabric)
  if ("mode.bexp_Time=_soil_layers_stag=1" %in% names(d_attr)) {
    d_attr <- dplyr::rename(d_attr, `mode.bexp_soil_layers_stag.1` = `mode.bexp_Time=_soil_layers_stag=1`)
  }

  if ("mean.refkdt_Time=" %in% names(d_attr)) {
    d_attr <- dplyr::rename(d_attr, `mean.refkdt` = `mean.refkdt_Time=`)
  }

  # Add vegetation type if calculated
  if (!is.null(divides_with_veg)) {
    d_attr$IVGTYP_nlcd <- divides_with_veg$IVGTYP_nlcd
  }

  if (config$hydrofabric$version == "2.2") {
    sf::st_write(d_attr, outfile,layer = "divide-attributes", append = FALSE, overwrite = TRUE)
  } else if (config$hydrofabric$version == "2.1.1") {
    sf::st_write(d_attr, outfile,layer = "model-attributes", append = FALSE)  
  }
  # Reproject to ensure all .gpkgs end up in Albers projection (EPSG:5070)
  reprojection_function(outfile)
}
