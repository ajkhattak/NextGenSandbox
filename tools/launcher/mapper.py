from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml


DEFAULT_FORMULATIONS = {
    "pet_cfe_s": {
        "models": "PET, CFE, T-route",
        "model_instances": {
            "CFE": [
                {
                    "name": "cfe-s",
                    "basefile": "config_cfe-s.yaml",
                    "repo_name": "cfe",
                    "calib_params_block": "cfes_params",
                }
            ]
        },
    },
    "pet_cfe_x": {
        "models": "PET, CFE, T-route",
        "model_instances": {
            "CFE": [
                {
                    "name": "cfe-x",
                    "basefile": "config_cfe-x.yaml",
                    "repo_name": "cfe",
                    "calib_params_block": "cfex_params",
                }
            ]
        },
    },
    "pet_topmodel": {
        "models": "PET, TopModel, T-route",
    },
    "nom_cfe_s": {
        "models": "NOM, CFE, T-route",
        "model_instances": {
            "CFE": [
                {
                    "name": "cfe-s",
                    "basefile": "config_cfe-s.yaml",
                    "repo_name": "cfe",
                    "calib_params_block": "cfes_params",
                }
            ]
        },
    },
    "nom_cfe_x": {
        "models": "NOM, CFE, T-route",
        "model_instances": {
            "CFE": [
                {
                    "name": "cfe-x",
                    "basefile": "config_cfe-x.yaml",
                    "repo_name": "cfe",
                    "calib_params_block": "cfex_params",
                }
            ]
        },
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a launcher model-gage mapping YAML file."
    )
    parser.add_argument("gages_file", help="CSV file containing gage IDs.")
    parser.add_argument(
        "--column",
        default="gage_id",
        help="CSV column containing gage IDs. Default: gage_id.",
    )
    parser.add_argument(
        "--default-formulations",
        nargs="+",
        default=["pet_cfe_s"],
        help="Default formulation names assigned to each gage.",
    )
    parser.add_argument(
        "--output",
        default="models_gages_map.yaml",
        help="Output YAML file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gages_file = Path(args.gages_file)
    df = pd.read_csv(gages_file, dtype={args.column: str})

    if args.column not in df.columns:
        raise ValueError(f"{gages_file} must contain column '{args.column}'")

    unknown = sorted(set(args.default_formulations) - set(DEFAULT_FORMULATIONS))
    if unknown:
        raise ValueError(f"Unknown default formulation(s): {', '.join(unknown)}")

    gages = df[args.column].dropna().astype(str).tolist()
    mapping = {gage: list(args.default_formulations) for gage in gages}

    cfg = {
        "formulations": DEFAULT_FORMULATIONS,
        "groups": {},
        "mapping": mapping,
    }

    with Path(args.output).open("w") as file:
        yaml.safe_dump(cfg, file, sort_keys=False)

    print(f"Generated launcher mapping file: {args.output}")


if __name__ == "__main__":
    main()
