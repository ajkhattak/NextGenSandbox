# @author Ahmad Jan Khattak
# @email ajkhattak@gmail.com
# @author Lauren Bolotin
# @email lauren.bolotin@noaa.gov
# @date  December 22, 2023

# The script downloads geopackage(s) given USGS gauge id(s), or reads
# geopackages from disk. It can also compute derived divide attributes such as
# TWI, GIUH, Nash cascade parameters, terrain slope/aspect, and vegetation type.

library(yaml)
Sys.setenv("AWS_NO_SIGN_REQUEST" = "YES")

DEFAULT_DEM_INPUT_FILE <- "s3://lynker-spatial/gridded/3DEP/USGS_seamless_DEM_13.vrt"

load_subset_dependencies <- function(sandbox_dir) {
  # Subsetting runs should only check/load R dependencies. Installation happens
  # explicitly through src/R/install_load_libs.R --install or RStudio.
  Sys.setenv(SANDBOX_R_DEPS_MODE = "check")
  suppressMessages(source(file.path(sandbox_dir, "src/R/install_load_libs.R")))
}

source_subset_helpers <- function(sandbox_dir) {
  source(file.path(sandbox_dir, "src/R/config.R"))
  source(file.path(sandbox_dir, "src/R/failures.R"))
  source(file.path(sandbox_dir, "src/R/nwis.R"))
}

load_runtime_args <- function(args) {
  if (length(args) == 2) {
    runtime <- list(
      infile_config = args[1],
      sandbox_dir = args[2]
    )
    print(paste0("Config file provided: ", runtime$infile_config))
    return(runtime)
  }

  if (length(args) > 2) {
    stop("Usage: RScript main.R input.yaml sandbox_dir")
  }

  # RStudio/source() fallback. Prefer the active test config if present,
  # otherwise use the sample config.
  active_doc <- tryCatch(
    normalizePath(rstudioapi::getActiveDocumentContext()$path),
    error = function(e) ""
  )

  sandbox_dir <- if (nzchar(active_doc)) {
    normalizePath(file.path(dirname(active_doc), "../.."))
  } else {
    normalizePath(getwd())
  }

  list(
    infile_config = file.path(sandbox_dir, "configs/sandbox_config1.yaml"),
    sandbox_dir = sandbox_dir
  )
}

load_subset_config <- function(runtime) {
  if (!file.exists(runtime$infile_config)) {
    print(paste0("input config file does not exist, provided: ", runtime$infile_config))
    print("Note: if running from RStudio, make sure sandbox_dir & infile_config are set propely (see src/R/main.R).")
    stop(paste0("input config file does not exist, provided: ", runtime$infile_config))
  }

  inputs <- yaml.load_file(runtime$infile_config)

  general_gages <- get_param(inputs, "general$gages", NULL)
  subsetting_gages <- get_param(inputs, "subsetting$gages", NULL)
  resource_layout <- get_param(inputs, "general$resource_layout", "gage")
  subset_gages <- resolve_subset_gages(
    general_gages,
    subsetting_gages,
    input_dir = inputs$general$input_dir,
    resource_layout = resource_layout
  )

  list(
    sandbox_dir = runtime$sandbox_dir,
    infile_config = runtime$infile_config,
    input_dir = inputs$general$input_dir,
    resource_layout = resource_layout,
    hydrofabric = list(
      version = inputs$subsetting$hydrofabric$version,
      gpkg_path = inputs$subsetting$hydrofabric$gpkg_path,
      compute_divide_attributes = get_param(
        inputs,
        "subsetting$hydrofabric$compute_divide_attributes",
        TRUE
      )
    ),
    dem = list(
      input_file = get_param(inputs, "subsetting$dem$input_file", NULL),
      output_dir = get_param(inputs, "subsetting$dem$output_dir", ""),
      aggregate_factor = get_param(inputs, "subsetting$dem$aggregate_factor", 3)
    ),
    gages = list(
      option = subset_gages$option,
      ids = subset_gages$ids,
      file = list(
        path = subset_gages$file$path,
        column = subset_gages$file$column
      ),
      gpkg = list(
        dir = subset_gages$gpkg$dir,
        pattern = subset_gages$gpkg$pattern,
        select = subset_gages$gpkg$select
      )
    ),
    vegetation = list(
      enabled = get_param(inputs, "subsetting$vegetation$enabled", FALSE),
      nlcd_path = get_param(inputs, "subsetting$vegetation$nlcd_path", FALSE),
      method = get_param(inputs, "subsetting$vegetation$classification_method", "majority")
    )
  )
}

resolve_subset_gages <- function(general_gages, subset_gages, input_dir, resource_layout) {
  if (is.null(general_gages)) {
    stop("general$gages must be defined. Use subsetting$gages only as an optional filter: all, one ID, or a list of IDs.")
  }

  option <- general_gages$option
  if (is.null(option)) {
    stop("general$gages$option must be defined. OPTIONS: ids | file | gpkg")
  }

  full_gages <- list(
    option = option,
    ids = general_gages$ids,
    file = list(
      path = general_gages$file$path,
      column = ifelse(is.null(general_gages$file$column), "gage_id", general_gages$file$column)
    ),
    gpkg = list(
      dir = resolve_general_gpkg_dir(
        general_gages$gpkg$dir,
        input_dir,
        resource_layout
      ),
      pattern = ifelse(is.null(general_gages$gpkg$pattern), "gage_", general_gages$gpkg$pattern),
      select = general_gages$gpkg$select
    )
  )

  if (is.null(subset_gages)) {
    return(full_gages)
  }

  if (!is_simple_gage_selector(subset_gages)) {
    stop("When general$gages is configured, subsetting$gages may only be 'all', a gage ID string, or a list of IDs.")
  }

  if (option == "ids") {
    selected <- normalize_simple_gage_selector(
      subset_gages,
      as.character(full_gages$ids),
      "subsetting$gages"
    )
    full_gages$option <- "ids"
    full_gages$ids <- selected
    return(full_gages)
  }

  if (option == "file") {
    project_ids <- read.csv(full_gages$file$path, colClasses = c("character"))[[full_gages$file$column]]
    selected <- normalize_simple_gage_selector(
      subset_gages,
      as.character(project_ids),
      "subsetting$gages"
    )
    full_gages$option <- "ids"
    full_gages$ids <- selected
    return(full_gages)
  }

  if (option == "gpkg") {
    if (is.null(full_gages$gpkg$select)) {
      if (identical(tolower(as.character(subset_gages)[1]), "all")) {
        return(full_gages)
      }
      full_gages$gpkg$select <- as.character(subset_gages)
      return(full_gages)
    }

    selected <- normalize_simple_gage_selector(
      subset_gages,
      as.character(full_gages$gpkg$select),
      "subsetting$gages"
    )
    full_gages$gpkg$select <- selected
    return(full_gages)
  }

  stop(sprintf("Invalid option '%s'. general$gages$option must be one of: ids, file, gpkg", option))
}

resolve_general_gpkg_dir <- function(gpkg_dir, input_dir, resource_layout) {
  if (!is.null(gpkg_dir) && trimws(gpkg_dir) != "") {
    return(gpkg_dir)
  }

  if (is.null(input_dir) || trimws(input_dir) == "") {
    stop("general$input_dir must be defined when general$gages$gpkg$dir is omitted.")
  }

  if (identical(resource_layout, "resource")) {
    return(file.path(input_dir, "hydrofabric"))
  }

  input_dir
}

validate_subset_config <- function(config) {
  if (is.null(config$input_dir) || trimws(config$input_dir) == "") {
    stop("Invalid input: 'general$input_dir' is missing or empty.")
  }

  gpkg_path <- config$hydrofabric$gpkg_path
  if (is.null(gpkg_path) || trimws(gpkg_path) == "") {
    stop("Invalid input: 'subsetting$hydrofabric$gpkg_path' is missing or empty.")
  }
  if (!file.exists(gpkg_path)) {
    stop(sprintf(
      "Invalid input: 'subsetting$hydrofabric$gpkg_path' does not exist: %s",
      gpkg_path
    ))
  }

  dem_input_file <- config$dem$input_file
  if (is.null(dem_input_file)) {
    config$dem$input_file <- DEFAULT_DEM_INPUT_FILE
  } else if (trimws(dem_input_file) == "") {
    stop(paste(
      "Invalid input: 'subsetting$dem$input_file' was provided but is empty.",
      "",
      "Because 'subsetting$hydrofabric$compute_divide_attributes' defaults to TRUE,",
      "the workflow needs a DEM to compute derived divide attributes.",
      "",
      "Choose one:",
      "  - remove 'subsetting$dem$input_file' to use the default S3 DEM",
      "  - provide a valid DEM path or URL",
      "  - set 'subsetting$hydrofabric$compute_divide_attributes: FALSE' to only subset geopackages",
      sep = "\n"
    ))
  }

  config$dem$aggregate_factor <- validate_positive_integer(
    config$dem$aggregate_factor,
    "subsetting$dem$aggregate_factor"
  )

  option <- config$gages$option
  if (is.null(option)) {
    stop("subsetting$gages$option must be defined. OPTIONS: ids | file | gpkg")
  }

  allowed <- c("ids", "file", "gpkg")
  if (!(option %in% allowed)) {
    stop(sprintf("Invalid option '%s'. Must be one of: %s", option, toString(allowed)))
  }

  allowed_layouts <- c("gage", "resource")
  if (!(config$resource_layout %in% allowed_layouts)) {
    stop(sprintf(
      "Invalid option '%s'. general$resource_layout must be one of: %s",
      config$resource_layout,
      toString(allowed_layouts)
    ))
  }

  if (option == "ids") {
    if (is.null(config$gages$ids)) {
      stop("ids must be provided when option = 'ids'")
    }
    warn_invalid_gage_ids(config$gages$ids)
  }

  config
}

prepare_subset_run <- function(config) {
  dir.create(config$input_dir, recursive = TRUE, showWarnings = FALSE)

  setwd(config$input_dir)
  wbt_wd(getwd())

  failed_dir <- subsetting_failure_dir(config$input_dir)

  if (dir.exists(failed_dir)) {
    unlink(failed_dir, recursive = TRUE, force = TRUE)
  }
}

load_gage_ids_from_file <- function(config) {
  gages <- read.csv(config$gages$file$path, colClasses = c("character"))
  gage_ids <- zeroPad(gages[[config$gages$file$column]], 8)
  warn_invalid_gage_ids(gage_ids)
  gage_ids
}

load_gpkg_files <- function(config) {
  gpkg_dir <- config$gages$gpkg$dir
  pattern <- config$gages$gpkg$pattern
  selected_gpkgs <- config$gages$gpkg$select

  if (dir.exists(gpkg_dir)) {
    gage_files <- list.files(gpkg_dir, full.names = TRUE, pattern = pattern)
    if (length(gage_files) == 0 && identical(config$resource_layout, "gage")) {
      candidate_dirs <- list.dirs(gpkg_dir, recursive = FALSE, full.names = TRUE)
      gage_files <- unlist(lapply(candidate_dirs, function(candidate_dir) {
        candidate_files <- c(
          list.files(file.path(candidate_dir, "hydrofabric"), full.names = TRUE, pattern = pattern),
          list.files(file.path(candidate_dir, "data"), full.names = TRUE, pattern = pattern),
          list.files(candidate_dir, full.names = TRUE, pattern = pattern)
        )
        candidate_files[grepl("\\.gpkg$", candidate_files)]
      }))
    }
  } else if (file.exists(gpkg_dir)) {
    gage_files <- gpkg_dir
  } else {
    stop("gpkg_dir does not exist")
  }

  if (!is.null(selected_gpkgs)) {
    selected_pattern <- paste(selected_gpkgs, collapse = "|")
    matches <- grep(selected_pattern, gage_files, value = TRUE)

    if (length(matches) == 0) {
      stop(glue::glue(
        "None of the selected gage files were found.\n",
        "Selected: {toString(selected_gpkgs)}\n",
        "Available: {toString(basename(gage_files))}"
      ))
    }

    gage_files <- matches
  }

  gage_files
}

run_subset_workflow <- function(config) {
  start_time <- Sys.time()

  if (config$gages$option %in% c("ids", "file")) {
    gage_ids <- config$gages$ids
    if (config$gages$option == "file") {
      gage_ids <- load_gage_ids_from_file(config)
    }

    stopifnot(length(gage_ids) > 0)

    DriverGivenGageIDs(
      gage_ids = gage_ids,
      config = config
    )
  } else if (config$gages$option == "gpkg") {
    gage_files <- load_gpkg_files(config)
    print(glue::glue("GPKG FILES : {gage_files}"))

    DriverGivenGPKG(
      gage_files = gage_files,
      config = config
    )
  }

  end_time <- Sys.time()
  time_taken <- as.numeric(end_time - start_time, units = "secs")
  print(paste0("Total Time Taken = ", time_taken))

  report_failed_gages(config$input_dir)
}

main <- function(args = commandArgs(trailingOnly = TRUE)) {
  runtime <- load_runtime_args(args)
  source_subset_helpers(runtime$sandbox_dir)

  config <- load_subset_config(runtime)
  config <- validate_subset_config(config)

  load_subset_dependencies(config$sandbox_dir)
  source(file.path(config$sandbox_dir, "src/R/custom_functions.R"))

  prepare_subset_run(config)
  print("SETUP DONE!")

  run_subset_workflow(config)
}

tryCatch({
  main()
}, error = function(e) {
  message("Setup failed: ", e$message)
  quit(status = 2, save = "no")
})

################################### DONE #######################################
