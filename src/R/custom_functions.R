############################### SET PATHS ######################################
# STEP #2. Load custom .R files
################################################################################

current_file <- function() {
  frames <- sys.frames()

  for (frame in rev(frames)) {
    if (!is.null(frame$ofile)) {
      return(normalizePath(frame$ofile))
    }
  }

  stop("Unable to determine path to custom_functions.R.")
}

subset_r_dir <- dirname(current_file())

source(file.path(subset_r_dir, "twi_width.R"))
source(file.path(subset_r_dir, "helper.R"))
source(file.path(subset_r_dir, "giuh.R"))
source(file.path(subset_r_dir, "nash_cascade.R"))
source(file.path(subset_r_dir, "veg_type.R"))
source(file.path(subset_r_dir, "driver.R"))
source(file.path(subset_r_dir, "slope.R"))
source(file.path(subset_r_dir, "aspect.R"))
source(file.path(subset_r_dir, "dem.R"))

# List all functions - give access to these function to each worker
functions_lst = c("RunDriver", "add_model_attributes", "dem_function", "twi_function", 
                  "width_function", "twi_pre_computed_function", "giuh_function", 
                  "Nash_Cascade_Runoff", "get_nash_params", "fun_crop_lower", 
                  "fun_crop_upper", "clean_move_dem_dir", "slope_function", "aspect_function",
                  "GetDEM")
