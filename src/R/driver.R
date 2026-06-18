#----------------------- DOWNLOAD GEOPACKAGE ----------------------------------#
# STEP #3: provide USGS gauge id or your own geopackage (single or multiple)
#------------------------------------------------------------------------------#

HYDROFABRIC_DIR <- "hydrofabric"

hydrofabric_path <- function(cat_dir, gpkg_name) {
  file.path(cat_dir, HYDROFABRIC_DIR, gpkg_name)
}


############################ DRIVER_GIVEN_GAGE_ID ##############################
# main script that loops over all the gage IDs and computes giuh/twi etc.
DriverGivenGageIDs <- function(gage_ids, 
                               output_dir,
                               dem_aggregate_factor,
                               dem_input_file = NULL,
                               dem_output_dir = "",
                               compute_divide_attributes = TRUE,
                               veg_calc_enabled = NULL,
                               veg_nlcd_path    = NULL, 
                               veg_method       = NULL
                               ) 
  {
  
  print ("DRIVER GIVEN GAGE ID")
  
  lapply(X = gage_ids, FUN = ProcessCatchmentID)

  setwd(output_dir)

}

#-----------------------------------------------------------------------------#
# Function called by pblapply for parallel processing by each worker/node
# for each catchment id
# it calls run_driver for each gage id and computes giuh/twi etc.

ProcessCatchmentID <- function(id) {

  print ("PROCESS CATCHMENT ID FUNCTION")

  cat_dir = glue("{output_dir}/{id}")
  dir.create(cat_dir, recursive = TRUE, showWarnings = FALSE)

  setwd(cat_dir)
  wbt_wd(getwd())

  # DEM and related files (such as projected/corrected DEMs, and specific contributing area rasters are stored here)
  dir.create("dem", recursive = TRUE, showWarnings = FALSE)
  dir.create(HYDROFABRIC_DIR, recursive = TRUE, showWarnings = FALSE)

  failed <- TRUE

  tryCatch({
    cat ("Processing catchment: ", id, "\n")
    RunDriver(gage_id = id,
              dem_input_file = dem_input_file,
              compute_divide_attributes = compute_divide_attributes,
              dem_aggregate_factor = dem_aggregate_factor,
              veg_calc_enabled = veg_calc_enabled,
              veg_nlcd_path    = veg_nlcd_path, 
              veg_method       = veg_method
              )

    failed <- FALSE
  }, error = function(e) {
    failed <- TRUE
  })

  # move (or delete) dem output directory out of the main output directory

  clean_move_dem_dir(id = id, output_dir = output_dir, dem_output_dir = dem_output_dir)

  if (failed) {
    cat ("Basin failed:", id, "\n")
    cat_failed_dir = glue("{output_dir}/basins_failed/{id}")

    if (file.exists(cat_failed_dir) ) {
      unlink(cat_failed_dir, recursive = TRUE)
    }

    file.rename(cat_dir, cat_failed_dir)

  }
  else {
    cat ("Basin Passed:", id, "\n")
  }

}

############################ DRIVER_GIVEN_GPKG #################################
# main script that loops over all the geopackages and computes giuh/twi etc.
DriverGivenGPKG <- function(gage_files, 
                            gpkg_dir, 
                            output_dir,
                            dem_aggregate_factor,
                            dem_output_dir,
                            dem_input_file = NULL,
                            compute_divide_attributes = TRUE,
                            veg_calc_enabled = NULL,
                            veg_nlcd_path    = NULL, 
                            veg_method       = NULL
                            ) 
  {

  print ("DRIVER GIVEN GEOPACKAGE FUNCTION")

  stopifnot(length(gage_files) >= 1)

  cats_failed <- lapply(X = gage_files, FUN = ProcessGPKG, failed_dir)
  setwd(output_dir)

  return(cats_failed)
}

ProcessGPKG <- function(gfile, failed_dir) {

  print ("PROCESS GPKG FUNCTION")

  # vector containing IDs of failed (for some reason) basins
  cats_failed <- numeric(0)

  id <- sub(".*_(.*?)\\..*", "\\1", basename(gfile))

  if (is.na(id)) {
     id <- 11111111
  }

  cat_dir = glue("{output_dir}/{id}")
  dir.create(cat_dir, recursive = TRUE, showWarnings = FALSE)

  setwd(cat_dir)
  wbt_wd(getwd())

  # DEM and related files (such as projected/corrected DEMs, and specific contributing 
  # area rasters are stored here)
  
  dir.create("dem", recursive = TRUE, showWarnings = FALSE)
  dir.create(HYDROFABRIC_DIR, recursive = TRUE, showWarnings = FALSE)
  file.copy(gfile, HYDROFABRIC_DIR)

  failed <- TRUE

  tryCatch({
    cat ("Processing catchment: ", id, "\n")

    gpkg_name = basename(gfile)

    local_gpkg_file = hydrofabric_path(cat_dir, gpkg_name)

    RunDriver(is_gpkg_provided = TRUE,
              loc_gpkg_file = local_gpkg_file,
              dem_input_file = dem_input_file,
              compute_divide_attributes = compute_divide_attributes,
              dem_aggregate_factor = dem_aggregate_factor,
              veg_calc_enabled = veg_calc_enabled,
              veg_nlcd_path    = veg_nlcd_path, 
              veg_method       = veg_method
              )

    failed <- FALSE

    }, error = function(e) {
      failed <- TRUE
    })

  # move (or delete) dem output directory out of the main output directory
  clean_move_dem_dir(id = id, output_dir = output_dir, dem_output_dir = dem_output_dir)

  if (failed) {
    cat ("Basin failed:", id, "\n")
    cat_failed_dir = glue("{output_dir}/basins_failed/{id}")

    if (file.exists(cat_failed_dir) ) {
      unlink(cat_failed_dir, recursive = TRUE)
    }

    file.rename(cat_dir, cat_failed_dir)

  }
  else {
    cat ("Basin Passed:", id, "\n")
  }
  
  return(cats_failed)

}

############################# RUN_DRIVER ######################################
# main runner function
RunDriver <- function(gage_id = NULL, 
                      is_gpkg_provided = FALSE, 
                      dem_input_file = NULL,
                      loc_gpkg_file = "",
                      compute_divide_attributes = TRUE,
                      dem_aggregate_factor = 3,
                      veg_calc_enabled = NULL,
                      veg_nlcd_path    = NULL, 
                      veg_method       = NULL
                      ) {

  print ("RUN DRIVER FUNCTION")

  outfile <- " "
  if(!is_gpkg_provided) {
    start.time <- Sys.time()
    outfile <- hydrofabric_path(getwd(), glue("gage_{gage_id}.gpkg"))

    # Get domain info for this gage
    gage_metadata <- suppressMessages(readNWISsite(gage_id)) |> 
      dplyr::select(state_cd)

    state_code <- gage_metadata$state_cd
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
    
    if (hf_version == "2.2") {
      if (file.exists(hf_gpkg_path)) {
        print('USING LOCAL GPKG FILE FOR SUBSETTING')
        hf_gpkg <- hf_gpkg_path
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
                              hf_version = hf_version,
                              lyrs = layers,
                              type = 'nextgen',
                              overwrite = TRUE)
      } else { # If the gage is in CONUS, query using hl_uri
        hfsubsetR::get_subset(hl_uri = glue("gages-{gage_id}"),
                              outfile = outfile,
                              gpkg = hf_gpkg,
                              hf_version = hf_version,
                              lyrs = layers,
                              type = 'nextgen',
                              overwrite = TRUE)
      }
    } else if (hf_version == "2.1.1") {
      
      hfsubsetR::get_subset(nldi_feature = list(featureSource="nwissite", featureID=glue("USGS-{gage_id}")),
                            outfile = outfile, 
                            hf_version = hf_version, 
                            domain = "conus",
                            lyrs = layers,
                            overwrite = TRUE)
      }
    
    time.taken <- as.numeric(Sys.time() - start.time, units = "secs") #end.time - start.time
    print (paste0("Time (geopackage) = ", time.taken))

  } else { 
    outfile <- loc_gpkg_file
  }

  # check if the divide-attributes layer has the same number of rows as the divides layer
  if (compute_divide_attributes) {

    check_divs  <- st_read(outfile, layer = 'divides')
    check_attrs <- st_read(outfile, layer = 'divide-attributes')

    id_col <- "divide_id"

    missing_in_attrs <- setdiff(check_divs[[id_col]], check_attrs[[id_col]])

    missing_in_divs <- setdiff(check_attrs[[id_col]], check_divs[[id_col]])

    if (length(missing_in_attrs) > 0 || length(missing_in_divs) > 0) {
      print("Mismatched rows detected:")
      print(glue("DIVIDES HAS {nrow(check_divs)} ROWS BUT DIVIDE-ATTRIBUTES HAS {nrow(check_attrs)}!!"))

      print(glue("IDs in divides but not in divide-attributes: {toString(missing_in_attrs)}"))
      print(glue("IDs in divide-attributes but not in divides: {toString(missing_in_divs)}"))
      stop()
    }

  } else {
    print(glue("compute_divide_attributes is FALSE... returning"))
    return()
  }

  ## Stop if .gpkg does not exist

  if (!file.exists(outfile)) {
    print(glue("FILE '{outfile}' DOES NOT EXIST!!"))
    stop()
    }

  ############################### GET DEM ##################################
  
  start.time <- Sys.time()
  
  GetDEM(div_infile = outfile, dem_input_file, buffer_m = 2000, 
           aggregate_factor = dem_aggregate_factor)

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
  if (veg_calc_enabled && file.exists(veg_nlcd_path)) {
    print("STEP: Computing vegetation type from NLCD data .................")
    start.time <- Sys.time()

    # Calculate vegetation type
    divides_with_veg <- ComputeVegTypeNLCD(outfile, veg_nlcd_path, veg_method, nclasses = 2)

    time.taken <- as.numeric(Sys.time() - start.time, units = "secs")
    print (paste0("Time (vegetation calc) = ", time.taken))
  } else if (veg_calc_enabled) {
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
  
  d_attr <- read_sf(outfile, 'divide-attributes')

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

  if (hf_version == "2.2") {
    sf::st_write(d_attr, outfile,layer = "divide-attributes", append = FALSE, overwrite = TRUE)
  } else if (hf_version == "2.1.1") {
    sf::st_write(d_attr, outfile,layer = "model-attributes", append = FALSE)  
  }
  # Reproject to ensure all .gpkgs end up in Albers projection (EPSG:5070)
  reprojection_function(outfile)
}
