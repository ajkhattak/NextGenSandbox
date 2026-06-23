# @author Lauren Bolotin
# @email lauren.bolotin@noaa.gov
# @date  July 16, 2025

# ########################### Slope ########################
# Function computes slope from a DEM to replace the hydrofabric slope values
# DEFAULT UNITS = "degrees"

slope_function <- function(div_infile) {
  
  dem_output_dir <- "dem"
  
  div <- read_sf(div_infile, 'divides')
  
  # This was already run in twi_width.R
  # wbt_slope(dem = glue("{dem_output_dir}/dem_corr.tif"), output = glue("{dem_output_dir}/slope.tif"),
  #           verbose_mode = FALSE)
  slope <- rast(glue("{dem_output_dir}/slope.tif"))
  div <- align_sf_to_raster_crs(div, slope, "hydrofabric divide polygons")
  
  slope_cat <- zonal::execute_zonal(data = slope,
                                    geom = div,
                                    ID = "divide_id",
                                    fun = "mean")

  for (i in seq_len(nrow(slope_cat))) {
    x <- slope_cat$mean.slope[i]

    if (is.nan(x) || x == "" || x == "[]") {
      message("Replacing empty GIUH with default distribution")
      slope_cat$mean.slope[i] <- 10.0
      }
  }
  
  return(slope_cat)
}

