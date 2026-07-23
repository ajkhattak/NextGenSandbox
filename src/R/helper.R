# @author Ahmad Jan Khattak
# @email ajkhattak@gmail.com
# @author Lauren Bolotin
# @email lauren.bolotin@noaa.gov
# @date  February 05, 2024


#the condition [coverage_fraction > .1] excludes/drops all cell X that has fraction less than 10% in the divide Y
fun_crop_lower <- function(values, coverage_fraction) {
  data = (values * coverage_fraction)[coverage_fraction > 0.1]
  percentile_10 <- unname(quantile(data, probs = 0.15, na.rm = TRUE)) # unname function returns the quantile value only, and not the cut points
  data[data <= percentile_10] = percentile_10
}

fun_crop_upper <- function(values, coverage_fraction) {
  data = (values * coverage_fraction)[coverage_fraction > .1]
  percentile_90 <- unname(quantile(data, probs = 0.85, na.rm = TRUE))
  data[data >= percentile_90] = percentile_90
}

# Adapted from the distribution function at: https://github.com/mikejohnson51/zonal/blob/master/R/custom_function.R
corrected_distrib_func = function(value, coverage_fraction, breaks = 10, constrain = FALSE){


  if (length(value) <= 0 || all(is.na(value)) || all(is.nan(value))) {
    return("[]")
  }

  x1 = value*coverage_fraction
  x1 = x1[!is.na(x1)]
  
  if(constrain & length(breaks) > 1){
    
    breaks_tmp = c(breaks[1],breaks[2])
    
    ulimit = max(x1, na.rm = TRUE)
    
    if (ulimit < max(breaks, na.rm = TRUE)){
      ulimit = min(breaks[breaks >= ulimit])
    }
    
    breaks = breaks[breaks <= ulimit]
    
    if (length(breaks) == 1){
      breaks = breaks_tmp
    }
    
  }
  
  tmp = as.data.frame(table(cut(x1, breaks = breaks)))
  
  tmp$v = as.numeric(gsub("]", "", sub('.*,\\s*', '', tmp$Var1)))
  
  len <- length(tmp$Freq)
  len2 <- len - 1
  
  if (sum(tmp$Freq) == 0){
    tmp$Freq[1:len2] <- 0
    tmp$Freq[len] <- 1
  }  
  tmp$frequency = tmp$Freq / sum(tmp$Freq)
  
  
  if (sum(tmp$frequency) > 1.01 | sum(tmp$frequency) < 0.99){
    stop("No data in the distribution")
  }
  
  as.character(toJSON(tmp[,c("v", "frequency")]))
  
}

# get parameter function check if a param is provided otherwise a default value
get_param <- function(input, param, default_value) {

  tryCatch({
    value = eval(parse(text = paste("input$", param, sep = "")))
    
    if (is.null(value)) default_value else value
    }, error = function(e) {
      default_value
    })
}

align_sf_to_raster_crs <- function(geom, raster, label = "geometry") {
  geom_vect <- terra::vect(geom)

  if (terra::same.crs(raster, geom_vect)) {
    return(geom)
  }

  raster_crs <- terra::crs(raster)
  if (is.null(raster_crs) || !nzchar(raster_crs)) {
    warning(glue("Raster CRS is missing; cannot reproject {label}."))
    return(geom)
  }

  sf::st_transform(geom, crs = raster_crs)
}

reprojection_function <- function(outfile, epsg = 5070){
  # File paths
  gpkg_path <- outfile
  gpkg_temp <- tempfile(fileext = ".gpkg")
  # Get all layer names
  sf_layers <- st_layers(gpkg_path)
  
  # Track first write
  first <- TRUE
  
  for (layer in sf_layers$name) {
    # Read layer
    layer_data <- st_read(gpkg_path, layer = layer, quiet = TRUE)
    # Reproject only if it's an sf object
    if (inherits(layer_data, "sf")) {
      layer_data <- st_transform(layer_data, crs = 5070)
    }
    # Write to new GPKG
    st_write(
      layer_data,
      gpkg_temp,
      layer = layer,
      delete_dsn = first,
      append = !first,
      quiet = TRUE
    )
    first <- FALSE
  }
  
  # Replace original GPKG
  # file_delete(gpkg_path)
  # file_copy(gpkg_temp, gpkg_path)
  file.remove(gpkg_path)
  file.copy(gpkg_temp, gpkg_path, overwrite = TRUE)
}

circular_mean <- function (values, coverage_fraction) {

  # adopted from the 'zonal' package: https://github.com/mikejohnson51/zonal/blob/8d932f3d419489f90e7ab6c6afa085791324dc46/R/custom_function.R#L30
  #TODO: figure out how to integrate the existing function
  degrad = pi / 180

  sinr <- sum(sin(values * degrad), na.rm = TRUE)

  cosr <- sum(cos(values * degrad), na.rm = TRUE)

  val = atan2(sinr, cosr) * (1 / degrad)

  ifelse(val < 0, 180 + (val + 180), val)

}

clean_move_dem_dir <- function(id, output_dir, dem_output_dir) {
  
  dem_target <- glue("{dem_output_dir}/{id}")
  dem_source <- glue("{output_dir}/{id}/dem")
  
  if (is.null(dem_output_dir) || dem_output_dir == "") {
    
    message("DEM output directory is set to empty or null in the configuration file; deleting DEM.")
    if (dir.exists(dem_source)) {
      unlink(dem_source, recursive = TRUE)
    }
    
  } else if (dem_output_dir == "dem") {
    message("DEM output dir is 'dem' - no action taken")
    
  } else {
    
    # if dem_output_dir does not exist, then create it
    if (!dir.exists(dem_output_dir)) {
      dir.create(dem_output_dir, recursive = TRUE, showWarnings = FALSE)
      message(glue("Created dem_output_dir: {dem_output_dir}"))
    }
    
    # move DEM if it exists
    if (dir.exists(dem_source)) {
      
      if (dir.exists(dem_target)) {
        unlink(dem_target, recursive = TRUE)
      }
      
      dir.create(dirname(dem_target), recursive = TRUE, showWarnings = FALSE)
      file.rename(dem_source, dem_target)
      
      message(glue("Moved DEM to {dem_target}"))
      
    } else {
      message(glue("DEM source does not exist: {dem_source}"))
    }
    
  }
  
}
