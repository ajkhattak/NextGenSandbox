# @author Ahmad Jan Khattak
# @email ajkhattak@gmail.com
# @date  February 26, 2026


ValidateCorrectedDEM <- function(dem_proj_file,
                                 dem_corr_file,
                                 validation_action = c("stop", "warn"),
                                 min_valid_ratio = 0.99,
                                 max_elevation_expansion_m = 100) {

  validation_action <- match.arg(validation_action)

  if (!file.exists(dem_proj_file)) {
    stop(glue("Cannot validate corrected DEM; projected DEM does not exist: {dem_proj_file}"))
  }
  if (!file.exists(dem_corr_file)) {
    stop(glue("Cannot validate corrected DEM; corrected DEM does not exist: {dem_corr_file}"))
  }

  dem_proj_check <- rast(dem_proj_file)
  dem_corr_check <- rast(dem_corr_file)

  same_geometry <- compareGeom(
    dem_proj_check,
    dem_corr_check,
    crs = TRUE,
    ext = TRUE,
    rowcol = TRUE,
    res = TRUE,
    stopOnError = FALSE
  )

  projected_valid <- global(!is.na(dem_proj_check), "sum", na.rm = TRUE)[1, 1]
  corrected_valid <- global(!is.na(dem_corr_check), "sum", na.rm = TRUE)[1, 1]
  valid_ratio <- corrected_valid / projected_valid

  projected_range <- global(dem_proj_check, c("min", "max"), na.rm = TRUE)
  corrected_range <- global(dem_corr_check, c("min", "max"), na.rm = TRUE)

  projected_min <- projected_range[1, "min"]
  projected_max <- projected_range[1, "max"]
  corrected_min <- corrected_range[1, "min"]
  corrected_max <- corrected_range[1, "max"]

  cat(glue(
    "\nCorrected DEM validation:\n",
    "  same geometry: {same_geometry}\n",
    "  projected valid cells: {format(projected_valid, scientific = FALSE)}\n",
    "  corrected valid cells: {format(corrected_valid, scientific = FALSE)}\n",
    "  corrected/projected valid ratio: {round(valid_ratio, 6)}\n",
    "  projected elevation range: {projected_min} to {projected_max}\n",
    "  corrected elevation range: {corrected_min} to {corrected_max}\n\n"
  ))

  problems <- character()

  if (!same_geometry) {
    problems <- c(problems, "projected and corrected DEM geometries differ")
  }
  if (!is.finite(projected_valid) || projected_valid <= 0) {
    problems <- c(problems, "projected DEM has no valid cells")
  }
  if (!is.finite(corrected_valid) || corrected_valid <= 0) {
    problems <- c(problems, "corrected DEM has no valid cells")
  }
  if (!is.finite(valid_ratio) || valid_ratio < min_valid_ratio) {
    problems <- c(
      problems,
      glue(
        "corrected DEM retained only {round(100 * valid_ratio, 4)}% of projected DEM valid cells ",
        "(required: at least {100 * min_valid_ratio}%)"
      )
    )
  }
  if (!all(is.finite(c(projected_min, projected_max, corrected_min, corrected_max)))) {
    problems <- c(problems, "DEM elevation statistics contain non-finite values")
  }
  if (
    is.finite(corrected_min) &&
    corrected_min < projected_min - max_elevation_expansion_m
  ) {
    problems <- c(
      problems,
      glue(
        "corrected minimum ({corrected_min}) is more than ",
        "{max_elevation_expansion_m} m below the projected minimum ({projected_min})"
      )
    )
  }
  if (
    is.finite(corrected_max) &&
    corrected_max > projected_max + max_elevation_expansion_m
  ) {
    problems <- c(
      problems,
      glue(
        "corrected maximum ({corrected_max}) is more than ",
        "{max_elevation_expansion_m} m above the projected maximum ({projected_max})"
      )
    )
  }

  if (length(problems) > 0) {
    msg <- paste(
      "Corrected DEM validation failed:",
      paste0(" - ", problems, collapse = "\n"),
      "Downstream TWI, GIUH, width, slope, and Nash calculations may be invalid.",
      sep = "\n"
    )

    if (validation_action == "stop") {
      stop(msg, call. = FALSE)
    } else {
      warning(msg, call. = FALSE)
    }
  } else {
    cat("Corrected DEM validation passed.\n")
  }

  invisible(length(problems) == 0)
}


GetDEM <- function(div_infile,
                   dem_input_file,
                   buffer_m = 2000,
                   aggregate_factor = 3,
                   dem_validation_action = c("stop", "warn"),
                   min_corrected_valid_ratio = 0.99,
                   max_corrected_elevation_expansion_m = 1) {

  dem_validation_action <- match.arg(dem_validation_action)

  dem_corr_file <- glue("dem/dem_corr.tif")

  if (file.exists(dem_corr_file)) {
    message("dem/dem_corr.tif file exists; validating it before skipping DEM processing...")
    ValidateCorrectedDEM(
      dem_proj_file = file.path("dem", "dem_proj.tif"),
      dem_corr_file = dem_corr_file,
      validation_action = dem_validation_action,
      min_valid_ratio = min_corrected_valid_ratio,
      max_elevation_expansion_m = max_corrected_elevation_expansion_m
    )
    return()
  }

  cat("=== Starting DEM processing ===\n")
  cat(glue("DEM input file1: {dem_input_file}\n"))

  terra_tempdir <- Sys.getenv("SANDBOX_TERRA_TMPDIR", unset = tempdir())
  if (!dir.exists(terra_tempdir)) {
    warning(glue("SANDBOX_TERRA_TMPDIR does not exist: {terra_tempdir}. Using R tempdir() instead."))
    terra_tempdir <- tempdir()
  }
  terraOptions(tempdir = terra_tempdir)

  # ----------------------------
  # Load DEM safely
  dem_output_dir <- "dem"

  tryCatch({
    elev <- rast(dem_input_file)
    cat("\nDEM loaded successfully.\n")
  }, error = function(e) {
    stop(glue("Failed to load DEM: {dem_input_file}\nDetails: {e$message}"))
  })

  # ----------------------------
  # Read the geopackage
  div <- read_sf(div_infile, "divides")

  # ----------------------------
  # Buffer hydrofabric divide polygons to avoid DEM edge effects.

  div_bf <- tryCatch({
    st_buffer(div, dist = buffer_m)
  }, error = function(e) {
    cat("Failed to create DEM buffer; cropping to hydrofabric divide polygons instead.\n")
    div
  })

  cat(glue("Buffered hydrofabric divide polygons by {buffer_m} meters.\n"))
  flush.console()

  div_bf_vect <- vect(div_bf)
  if (!same.crs(elev, div_bf_vect)) {
    div_bf_vect <- project(div_bf_vect, crs(elev))
    cat("\nReprojected buffered hydrofabric divide polygons to DEM CRS.\n")
  }

  # ----------------------------
  # Crop DEM to buffered hydrofabric divide polygons

  tryCatch({
    dem <- crop(elev, div_bf_vect, snap = "out")
    cat("\nDEM cropped to buffered hydrofabric divide polygons.\n")
  }, error = function(e) {
    warning("Buffer crop failed; cropping to hydrofabric divide polygons only.")
    div_vect <- vect(div)
    if (!same.crs(elev, div_vect)) {
      div_vect <- project(div_vect, crs(elev))
    }
    dem <- crop(elev, div_vect, snap = "out")
  })

  # ----------------------------
  # Convert units if VRT is in cm
  if (grepl("USGS_seamless_DEM_13.vrt", dem_input_file)) {
    dem <- dem * 0.01  # cm to m
    #dem <- as.float(dem)  # ensures FLT4S - note CONUS scale TWI/GIUHs etc. were produced using as.float(dem)
    cat("Converted DEM units from cm to m.\n")
  }

  # ----------------------------
  # Aggregate to coarser resolution

  if (aggregate_factor > 1) {
    cat(glue("Aggregating DEM by factor {aggregate_factor}...\n"))
    elev_file <- file.path(dem_output_dir, "dem_coarse.tif")

    dem <- aggregate(dem,
                     fact = aggregate_factor,
                     fun = "mean",
                     filename = elev_file,
                     overwrite = TRUE)
    cat("Aggregation complete.\n")
  }

  # ----------------------------
  # Remove negative values

  dem[dem < 0] <- 0

  # ----------------------------
  # Write DEM to disk

  dem_file <- file.path(dem_output_dir, "dem.tif")
  writeRaster(dem, dem_file, datatype = "FLT4S", overwrite = TRUE)
  cat(glue("DEM written to {dem_file}\n"))

  # ----------------------------
  # Reproject DEM using gdalwarp

  dem_proj_file <- file.path(dem_output_dir, "dem_proj.tif")
  gdal_threads <- Sys.getenv("SANDBOX_GDAL_THREADS", unset = "2")
  gdal_cache_mb <- Sys.getenv("SANDBOX_GDAL_CACHE_MB", unset = "512")

  warp_start <- Sys.time()
  gdal_utils("warp",
             source = dem_file,
             destination = dem_proj_file,
             options = c(
               "-of", "GTiff",
               "-t_srs", "EPSG:5070",
               "-r", "bilinear",
               "-multi",
               "-wo", glue("NUM_THREADS={gdal_threads}"),
               "-wm", gdal_cache_mb,
               "-co", "TILED=YES",
               "-co", "BLOCKXSIZE=256",
               "-co", "BLOCKYSIZE=256",
               "-co", "COMPRESS=DEFLATE",
               # Do not set a TIFF predictor here. WhiteboxTools 2.4 does not
               # correctly read floating-point GeoTIFFs written with either
               # PREDICTOR=2 or PREDICTOR=3.
               "-co", glue("NUM_THREADS={gdal_threads}"),
               "-co", "BIGTIFF=IF_SAFER"
             ),
             config_options = c(GDAL_CACHEMAX = gdal_cache_mb))
  warp_seconds <- as.numeric(difftime(Sys.time(), warp_start, units = "secs"))
  cat(glue(
    "\nDEM reprojected to EPSG:5070: {dem_proj_file} ",
    "({round(warp_seconds, 1)} seconds; {gdal_threads} GDAL threads)\n"
  ))

  # ----------------------------
  # Breach depressions

  dem_corr_file <- file.path(dem_output_dir, "dem_corr.tif")

  # OPTION # 1
  # Breach depressions while avoiding unrealistic trenching:
  # - Use a very small artificial slope of 0.000001 m per cell along flat breached paths
  #   so flow has a clear direction without accumulating large elevation drops.
  # - Fill single-cell pits before breaching to avoid carving long channels from tiny DEM artifacts.
  # - Avoid max_length/max_depth constraints here because they can make VPU-scale processing
  #   much slower; corrected DEM validation below catches unrealistic outputs.
  #

  wbt_breach_depressions(
    dem = dem_proj_file,
    output = dem_corr_file,
    fill_pits = TRUE,
    flat_increment = 0.000001,
    verbose_mode = TRUE
  )

  # OPTION # 2
  # Breach depressions with safety limits:
  # - Search for breach paths up to 25 cells long, i.e., about 25 x DEM cell size.
  # - Do not carve a breach deeper than 50 elevation units, normally meters.
  # - Apply a very small artificial slope of 0.001 m per cell along flat breached paths so flow has a clear direction.
  # - Fill single-cell pits before breaching to avoid carving long channels from tiny DEM artifacts.
  #

  #wbt_breach_depressions(
  #  dem = dem_proj_file,
  #  output = dem_corr_file,
  #  max_depth = 50,
  #  max_length = 25,
  #  flat_increment = 0.001,
  #  fill_pits = TRUE,
  #  verbose_mode = TRUE
  #)

  cat(glue("\nDepressions breached: {dem_corr_file}\n"))

  ValidateCorrectedDEM(
    dem_proj_file = dem_proj_file,
    dem_corr_file = dem_corr_file,
    validation_action = dem_validation_action,
    min_valid_ratio = min_corrected_valid_ratio,
    max_elevation_expansion_m = max_corrected_elevation_expansion_m
  )

  dem_corr <- rast(dem_corr_file)
  dem_corr[dem_corr < 0] <- 0
  writeRaster(dem_corr, dem_corr_file, datatype = "FLT4S", overwrite = TRUE)

  cat("=== DEM processing complete ===\n")

}
