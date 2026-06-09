LENGTH_FACTORS = {
    ("m", "m"): 1.0,
    ("m", "mm"): 1000.0,
    ("mm", "m"): 0.001,
    ("mm", "mm"): 1.0,
}


def unit_conversion_factor(
    source_units,
    target_units,
    temporal_aggregation=None,
):
    """Return the scale factor for supported simulated depth units."""
    source_length, source_time = _parse_units(source_units)
    target_length, target_time = _parse_units(target_units)

    if temporal_aggregation == "sum":
        if source_time is None or target_time is None:
            raise ValueError(
                "Summed simulated values require rate units such as "
                "'m/h' or 'mm/d'"
            )
        if (source_time, target_time) != ("h", "d"):
            raise ValueError(
                "Summed simulated values currently support only hourly-to-"
                "daily aggregation"
            )
        source_time = target_time
    elif temporal_aggregation == "mean":
        if source_time != target_time:
            raise ValueError(
                "Averaged simulated and observed units must use the same "
                "time basis"
            )
    elif source_time != target_time:
        raise ValueError(
            f"Cannot convert simulated units '{source_units}' to "
            f"observation units '{target_units}' without temporal aggregation"
        )

    return LENGTH_FACTORS[(source_length, target_length)]


def _parse_units(units):
    supported = {"m", "mm", "m/h", "mm/h", "m/d", "mm/d"}
    if units not in supported:
        raise ValueError(
            f"Unsupported units '{units}'. Supported units: "
            f"{', '.join(sorted(supported))}"
        )

    if "/" not in units:
        return units, None

    return tuple(units.split("/", maxsplit=1))
