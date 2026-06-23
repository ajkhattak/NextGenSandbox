# Helpers for reporting subset workflow failures.

report_failed_basins <- function(output_dir) {
  basins_failed <- file.path(output_dir, "basins_failed")

  if (!dir.exists(basins_failed)) {
    return(invisible(FALSE))
  }

  files <- list.files(basins_failed, full.names = TRUE)
  subdirs <- files[dir.exists(files)]

  if (length(subdirs) == 0) {
    print("All Basins Passed!!!")
    return(invisible(FALSE))
  }

  subdir_names <- basename(subdirs)
  print("List of Basins failed..")
  print(subdir_names)

  for (subdir in subdirs) {
    basin_id <- basename(subdir)
    error_file <- file.path(subdir, "subsetting_error.txt")

    cat(glue("\n--- Subsetting failure details for basin {basin_id} ---\n"))
    if (file.exists(error_file)) {
      cat(paste(readLines(error_file, warn = FALSE), collapse = "\n"))
      cat("\n")
    } else {
      cat(glue("No subsetting_error.txt file found in {subdir}\n"))
    }
  }

  message(
    glue(
      "Subsetting failed for {length(subdir_names)} basin(s): ",
      "{toString(subdir_names)}. See {basins_failed}/<gage_id>/",
      "subsetting_error.txt for details."
    )
  )
  quit(status = 3, save = "no")
}
