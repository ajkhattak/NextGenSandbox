import json

from ngen.config.realization import NgenRealization


def test_ngen_cal_preserves_per_formulation_nexus_output_setting():
    realization = NgenRealization(
        **{
            "global": {
                "formulations": [],
                "forcing": {
                    "file_pattern": ".*{{id}}.*.csv",
                    "path": ".",
                },
            },
            "time": {
                "start_time": "2020-01-01 00:00:00",
                "end_time": "2020-01-02 00:00:00",
                "output_interval": 3600,
            },
            "per_formulation_nexus_files": True,
        }
    )

    serialized = json.loads(
        realization.json(by_alias=True, exclude_none=True)
    )

    assert serialized["per_formulation_nexus_files"] is True
