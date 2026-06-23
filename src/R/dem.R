# @author Ahmad Jan Khattak
# @email ahmad.jan.khattak@noaa.gov
# @date  February 26, 2026


GetDEM <- function(div_infile,
                   dem_input_file,
                   buffer_m = 2000,
                   aggregate_factor = 3) {
  
  dem_corr_file <- glue("dem/dem_corr.tif")
  
  if (file.exists(dem_corr_file)) {
    message("dem/dem_corr.tif file exists, so skipping DEM processing...")
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
  gdal_utils("warp",
             source = dem_file,
             destination = dem_proj_file,
             options = c("-of", "GTiff", "-t_srs", "EPSG:5070", "-r", "bilinear"))
  cat(glue("\nDEM reprojected to EPSG:5070: {dem_proj_file}\n"))
  
  # ----------------------------
  # Breach depressions
  
  dem_corr_file <- file.path(dem_output_dir, "dem_corr.tif")
  wbt_breach_depressions(dem = dem_proj_file,
                         output = dem_corr_file)
  
  cat(glue("\nDepressions breached: {dem_corr_file}\n"))
  
  cat("=== DEM processing complete ===\n")
  
}
