# Helpers for retrieving USGS gage metadata.

.strip_ansi <- function(text) {
  gsub(paste0(intToUtf8(27), "\\[[0-9;]*[[:alpha:]]"), "", text)
}

get_gage_state_code <- function(gage_id) {
  state_code <- tryCatch(
    get_gage_state_code_waterdata(gage_id),
    error = function(waterdata_error) {
      tryCatch(
        get_gage_state_code_nwis(gage_id),
        error = function(nwis_error) {
          stop(sprintf(
            paste0(
              "Failed to retrieve USGS gage metadata for gage ID '%s'. ",
              "USGS gage IDs are expected to contain 8, 10, or 12 digits. ",
              "Confirm the ID exists in USGS monitoring-location data and is correctly formatted. ",
              "Water Data API error: %s. ",
              "NWIS fallback error: %s"
            ),
            gage_id,
            .strip_ansi(conditionMessage(waterdata_error)),
            .strip_ansi(conditionMessage(nwis_error))
          ))
        }
      )
    }
  )

  if (is.null(state_code) || length(state_code) == 0 || is.na(state_code[1])) {
    stop(sprintf(
      paste0(
        "Failed to retrieve USGS gage metadata for gage ID '%s'. ",
        "USGS returned no state code. Confirm the ID exists and is correctly formatted."
      ),
      gage_id
    ))
  }

  as.character(state_code[1])
}

resolve_gage_domain <- function(gage_id, configured_domain = NULL) {
  if (!is.null(configured_domain)) {
    return(configured_domain)
  }

  state_code <- get_gage_state_code(gage_id)
  state <- stateCd$STUSAB[which(stateCd$STATE == state_code)]
  if (length(state) != 1 || is.na(state)) {
    stop(sprintf(
      "Unable to map USGS state code '%s' to a subsetting domain for gage '%s'.",
      state_code,
      gage_id
    ))
  }
  if (state %in% c("HI", "AK")) {
    return(tolower(state))
  }
  if (state %in% c("PR", "VI")) {
    return("prvi")
  }
  "conus"
}

get_gage_state_code_waterdata <- function(gage_id) {
  if (!exists(
    "read_waterdata_monitoring_location",
    where = asNamespace("dataRetrieval"),
    inherits = FALSE
  )) {
    stop("dataRetrieval::read_waterdata_monitoring_location() is not available.")
  }

  monitoring_location_id <- paste0("USGS-", gage_id)
  metadata <- suppressMessages(dataRetrieval::read_waterdata_monitoring_location(
    monitoring_location_id = monitoring_location_id,
    properties = c("monitoring_location_id", "state_code"),
    skipGeometry = TRUE
  ))

  if (nrow(metadata) == 0 || !"state_code" %in% names(metadata)) {
    stop(sprintf(
      "No state_code returned for monitoring location '%s'.",
      monitoring_location_id
    ))
  }

  metadata$state_code[1]
}

get_gage_state_code_nwis <- function(gage_id) {
  metadata <- suppressWarnings(
    suppressMessages(dataRetrieval::readNWISsite(gage_id))
  )

  if (nrow(metadata) == 0 || !"state_cd" %in% names(metadata)) {
    stop(sprintf(
      "No state_cd returned by readNWISsite() for gage ID '%s'.",
      gage_id
    ))
  }

  metadata$state_cd[1]
}
