# @author Ahmad Jan Khattak
# @email ajkhattak@gmail.com
# @date  February 05, 2024

# ########################### TWI ########################
# Function computes topographic wetness index (TWI) and generates files 
# needed for computing width function (see below)
ComputeTWI <- function(div_infile, distribution = 'quantiles', nclasses = 5) {
  
  dem_output_dir <- "dem"
  
  div <- read_sf(div_infile, 'divides')
  
  twi_file <- glue("{dem_output_dir}/twi.tif")
  
  if (file.exists(twi_file)) {
    message("dem/twi.tif file exists, so skipping generating twi..")
  } else {
    # @param out_type Output type; one of 'cells' (default), 'catchment area', and 'specific contributing area'.
    wbt_d8_flow_accumulation(input = glue("{dem_output_dir}/dem_corr.tif"), output = glue("{dem_output_dir}/sca.tif"),
                             out_type = 'specific contributing area', verbose_mode = FALSE)
  
  
   wbt_slope(dem = glue("{dem_output_dir}/dem_corr.tif"), output = glue("{dem_output_dir}/slope.tif"),
             verbose_mode = FALSE)

    wbt_wetness_index(sca = glue("{dem_output_dir}/sca.tif"), slope = glue("{dem_output_dir}/slope.tif"),
                      output = glue("{dem_output_dir}/twi.tif"), verbose_mode = FALSE)
  }
  
  twi = rast(glue("{dem_output_dir}/twi.tif"))
  div <- align_sf_to_raster_crs(div, twi, "hydrofabric divide polygons")
  
  twi[twi < 0] <- 0
  twi[twi > 50] <- 50
  
  if (distribution == 'quantiles') {
    twi_cat <- zonal::execute_zonal(data = twi,
                                    geom = div,
                                    ID = "divide_id",
                                    fun = zonal::equal_population_distribution,
                                    groups = nclasses)
    
  }
  else if (distribution == 'simple') {
     twi_cat <- zonal::execute_zonal(data = twi,
                                     geom = div,
                                     ID = "divide_id",
                                     fun = zonal::distribution,
                                     breaks = nclasses)
  }

  # Set default TWI to empty rows
  default_twi <- data.frame(
    v = seq(0, 15, length.out = nclasses),
    frequency = rep(1 / nclasses, nclasses)
  )


  for (i in seq_len(nrow(twi_cat))) {
    x <- twi_cat$fun.twi[i]

    if ( x == "" || x == "[]") {
      message("Replacing empty TWI with default distribution")
      twi_cat$fun.twi[i] <- as.character(toJSON(default_twi, auto_unbox = TRUE)) #default_twi_json
    }
  }
  
  return(twi_cat)
}


ComputeWidth <- function(div_infile) {
  
  dem_output_dir <- "dem"
  
  div <- read_sf(div_infile, 'divides')
  
  downslope_fp_length_file <- glue("{dem_output_dir}/downslope_fp_length.tif")
  
  if (file.exists(downslope_fp_length_file)) {
    message("dem/downslope_fp_length.tif file exists, so skipping generating flowpath length..")
  } else {
    wbt_d8_pointer(dem = glue("{dem_output_dir}/dem_corr.tif"),
                   output = glue("{dem_output_dir}/dem_d8.tif"))

    wbt_downslope_flowpath_length(d8_pntr = glue("{dem_output_dir}/dem_d8.tif"),
                                  output = glue("{dem_output_dir}/downslope_fp_length.tif"), watersheds=NULL)
    # note: watersheds=div never tested but maybe useful in some cases; default is NULL
  }
  
  flowpath_length <- rast(glue("{dem_output_dir}/downslope_fp_length.tif"))
  div <- align_sf_to_raster_crs(div, flowpath_length, "hydrofabric divide polygons")
  
  fp_min_ftn = zonal::execute_zonal(data = flowpath_length,
                             geom = div,
                             ID = "divide_id",
                             fun = fun_crop_lower)
  
  
  fp_max_ftn = zonal::execute_zonal(data = flowpath_length,
                             geom = div,
                             ID = "divide_id",
                             fun = fun_crop_upper)  
  
  # create a grid based on min values of sub-catchments, grid resolution consistent with downslope_flowpth_length
  rasterized_fp_min <- rasterize(fp_min_ftn, flowpath_length, field=fp_min_ftn$fun.downslope_fp_length)
  rasterized_fp_max <- rasterize(fp_max_ftn, flowpath_length, field=fp_max_ftn$fun.downslope_fp_length)
  
  # assign fp_length raster to rast_fp_temp 
  rast_fp_temp <- flowpath_length
  
  # assign NA to values (per catchment) less than the min and max
  rast_fp_temp[rast_fp_temp <= rasterized_fp_min] <- NA
  rast_fp_temp[rast_fp_temp >= rasterized_fp_max] <- NA
  
  # subtract adjusted-raster (created 15% and 85% quantiles) from minimun-catchment-value to get localized distance
  # of a point to the catchment outlet
  downslope_fp_distance_cat_outlet <- rast_fp_temp - rasterized_fp_min
  
  writeRaster(downslope_fp_distance_cat_outlet, glue("{dem_output_dir}/downslope_fp_distance_cat_outlet.tif"),
              overwrite=TRUE)
  
  # channel cumulative distribution of area with distance
  width_dist <- execute_zonal(data = downslope_fp_distance_cat_outlet,
                              geom = div,
                              ID = "divide_id",
                              fun = corrected_distrib_func,
                              breaks = c(0.0,0.1,500,1000,1500))
  
  # Set default width distribution to empty rows

  default_dist <- data.frame(
    v = c(0.1, 500, 1000, 1500),
    frequency = c(0, 1, 0, 0)
  )

  for (i in seq_len(nrow(width_dist))) {
    x <- width_dist$fun.downslope_fp_length[i]

    if ( x == "" || x == "[]") {
      #message("Replacing empty TWI with default distribution")
      width_dist$fun.downslope_fp_length[i] <- as.character(toJSON(default_dist, auto_unbox = TRUE))
    }
  }

  return(width_dist)
}
