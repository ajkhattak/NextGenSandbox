# @author Lauren Bolotin
# @email lauren.bolotin@noaa.gov
# @date  Aug 25, 2025

# ########################### Slope ########################
# Function computes aspect from a DEM to replace the hydrofabric aspect values

aspect_function <- function(div_infile) {
  
  dem_output_dir <- "dem"
  
  div <- read_sf(div_infile, 'divides')

  dem <- rast(glue("{dem_output_dir}/dem_corr.tif"))
  aspect <- wbt_aspect(dem, glue("{dem_output_dir}/aspect.tif"))
  aspect <- rast(glue("{dem_output_dir}/aspect.tif"))
  div <- align_sf_to_raster_crs(div, aspect, "hydrofabric divide polygons")

  aspect_cat <- zonal::execute_zonal(data = aspect,
                                    geom = div,
                                    ID = "divide_id",
                                    fun = circular_mean)
  
  for (i in seq_len(nrow(aspect_cat))) {
    x <- aspect_cat$fun.aspect[i]

    if (is.nan(x) || x == "" || x == "[]") {
      message("Replacing empty aspect with default value")
      aspect_cat$fun.aspect[i] <- 360 # facing north = 360 or 0
    }
  }


  return(aspect_cat)
  
}


