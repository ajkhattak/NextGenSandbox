# Helpers for reporting subset workflow failures.

SUBSETTING_FAILURE_DIR <- "failed_gages"

subsetting_failure_dir <- function(output_dir) {
  file.path(output_dir, SUBSETTING_FAILURE_DIR)
}

subsetting_gpkg_id <- function(gpkg_file, gpkg_template = NULL) {
  if (!is.null(gpkg_template) && grepl("<gage_id>", gpkg_template, fixed = TRUE)) {
    marker <- "NEXTGENSANDBOXGAGEID"
    template_regex <- glob2rx(
      gsub("<gage_id>", marker, gpkg_template, fixed = TRUE)
    )
    template_regex <- sub(
      marker,
      "(?<![0-9])([0-9]{12}|[0-9]{10}|[0-9]{8})(?![0-9])",
      template_regex,
      fixed = TRUE
    )
    matched <- regmatches(
      gpkg_file,
      regexec(template_regex, gpkg_file, perl = TRUE)
    )[[1]]
    if (length(matched) == 2) {
      return(as.character(matched[2]))
    }
    stop(sprintf(
      "Geopackage does not match general$gages$gpkg$dir template: %s",
      gpkg_file
    ))
  }

  numeric_tokens <- regmatches(
    basename(gpkg_file),
    gregexpr("[0-9]+", basename(gpkg_file))
  )[[1]]
  valid_tokens <- numeric_tokens[nchar(numeric_tokens) %in% c(8, 10, 12)]
  if (length(numeric_tokens) != 1 || length(valid_tokens) != 1) {
    stop(sprintf(
      paste(
        "Cannot infer a USGS gage ID from geopackage '%s'.",
        "Its filename must contain exactly one numeric gage ID with 8, 10,",
        "or 12 digits, or general$gages$gpkg$dir must use <gage_id>."
      ),
      basename(gpkg_file)
    ))
  }

  as.character(valid_tokens[1])
}

subset_failure_dirs <- function(output_dir, gage_ids = NULL) {
  failed_gages <- subsetting_failure_dir(output_dir)

  if (!dir.exists(failed_gages)) {
    return(character(0))
  }

  files <- list.files(failed_gages, full.names = TRUE)
  subdirs <- files[dir.exists(files)]

  if (!is.null(gage_ids)) {
    gage_ids <- unique(as.character(gage_ids))
    subdirs <- subdirs[basename(subdirs) %in% gage_ids]
  }

  sort(subdirs)
}

clear_subset_failures <- function(output_dir, gage_ids) {
  failed_gages <- subsetting_failure_dir(output_dir)

  for (gage_id in unique(as.character(gage_ids))) {
    failure_dir <- file.path(failed_gages, gage_id)
    if (dir.exists(failure_dir)) {
      unlink(failure_dir, recursive = TRUE, force = TRUE)
    }
  }
}

report_failed_gages <- function(output_dir, gage_ids = NULL) {
  failed_gages <- subsetting_failure_dir(output_dir)
  subdirs <- subset_failure_dirs(output_dir, gage_ids)

  if (length(subdirs) == 0) {
    print("All Gages Passed!!!")
    return(invisible(FALSE))
  }

  subdir_names <- basename(subdirs)
  print("List of gages/resources failed..")
  print(subdir_names)

  for (subdir in subdirs) {
    gage_id <- basename(subdir)
    error_file <- file.path(subdir, "subsetting_error.txt")

    cat(glue("\n--- Subsetting failure details for gage/resource {gage_id} ---\n"))
    if (file.exists(error_file)) {
      cat(paste(readLines(error_file, warn = FALSE), collapse = "\n"))
      cat("\n")
    } else {
      cat(glue("No subsetting_error.txt file found in {subdir}\n"))
    }
  }

  message(
    glue(
      "Subsetting failed for {length(subdir_names)} gage/resource item(s): ",
      "{toString(subdir_names)}. See {failed_gages}/<gage_id>/",
      "subsetting_error.txt for details."
    )
  )
  quit(status = 3, save = "no")
}
