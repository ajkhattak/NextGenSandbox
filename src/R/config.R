# Helpers for reading and validating the subset workflow configuration.

get_param <- function(input, param, default_value) {
  tryCatch({
    value <- eval(parse(text = paste("input$", param, sep = "")))

    if (is.null(value)) default_value else value
  }, error = function(e) {
    default_value
  })
}

warn_invalid_gage_ids <- function(gage_ids) {
  gage_ids <- as.character(gage_ids)
  invalid <- gage_ids[!grepl("^[0-9]{8}$", gage_ids)]

  if (length(invalid) > 0) {
    message(
      "[WARNING] USGS gage IDs are expected to be exactly 8 digits. ",
      "The following ID(s) do not match that format and may fail during ",
      "NWIS/hydrofabric lookup: ",
      paste(invalid, collapse = ", ")
    )
  }
}

validate_positive_integer <- function(value, field_name) {
  if (is.null(value) || length(value) != 1 || is.logical(value)) {
    stop(sprintf(
      "Invalid input: '%s' must be a whole number greater than or equal to 1.",
      field_name
    ))
  }

  if (is.character(value)) {
    value <- trimws(value)

    if (!nzchar(value)) {
      stop(sprintf(
        "Invalid input: '%s' was provided but is empty. It must be a whole number greater than or equal to 1.",
        field_name
      ))
    }
  }

  numeric_value <- suppressWarnings(as.numeric(value))

  if (
    is.na(numeric_value) ||
    !is.finite(numeric_value) ||
    numeric_value < 1 ||
    numeric_value != floor(numeric_value)
  ) {
    stop(sprintf(
      "Invalid input: '%s' must be a whole number greater than or equal to 1. Provided value: %s",
      field_name,
      value
    ))
  }

  as.integer(numeric_value)
}
