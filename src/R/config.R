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
  invalid <- gage_ids[!grepl("^([0-9]{8}|[0-9]{10}|[0-9]{12})$", gage_ids)]

  if (length(invalid) > 0) {
    message(
      "[WARNING] USGS gage IDs are expected to contain 8, 10, or 12 digits. ",
      "The following ID(s) do not match that format and may fail during ",
      "NWIS/hydrofabric lookup: ",
      paste(invalid, collapse = ", ")
    )
  }
}

normalize_gage_domain <- function(value) {
  if (is.null(value)) {
    return(NULL)
  }
  if (length(value) != 1 || is.logical(value) || is.na(value)) {
    stop(
      "general$gages$domain must be one of: conus, hi, ak, prvi"
    )
  }

  domain <- tolower(trimws(as.character(value)))
  aliases <- c(pr = "prvi", vi = "prvi")
  if (domain %in% names(aliases)) {
    domain <- unname(aliases[[domain]])
  }

  allowed <- c("conus", "hi", "ak", "prvi")
  if (!nzchar(domain) || !(domain %in% allowed)) {
    stop(sprintf(
      paste0(
        "Invalid general$gages$domain '%s'. ",
        "Supported domains: %s"
      ),
      value,
      toString(allowed)
    ))
  }

  domain
}

normalize_hydrofabric_version <- function(value) {
  version <- as.character(value)
  if (length(version) != 1 || is.na(version) || !identical(version, "2.2")) {
    stop(sprintf(
      paste0(
        "Unsupported subsetting$hydrofabric$version '%s'. ",
        "NextGenSandbox supports Hydrofabric 2.2 only."
      ),
      toString(version)
    ))
  }
  version
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

is_simple_gage_selector <- function(value) {
  is.character(value) && is.null(names(value))
}

normalize_simple_gage_selector <- function(value, project_ids, field_name) {
  if (is.null(value) || identical(tolower(as.character(value)[1]), "all")) {
    return(project_ids)
  }

  if (!is_simple_gage_selector(value)) {
    stop(sprintf(
      "%s must be 'all', a gage ID string, or a list of gage IDs. Full option/file/gpkg selectors are only supported under general$gages.",
      field_name
    ))
  }

  selected <- as.character(value)
  missing <- setdiff(selected, project_ids)
  if (length(missing) > 0) {
    stop(sprintf(
      "%s contains gages outside general$gages: %s",
      field_name,
      paste(missing, collapse = ", ")
    ))
  }

  selected
}
