from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional


@dataclass
class ModelInstance:

    model: str
    name: str
    repo_name: str = ""
    calib_params_block: str = ""
    calib_params_file: str = ""
    ngen_cal_model_name: Optional[str] = None
    basefile: Optional[str] = None
    config_dir: Optional[Path] = None
    outputs_dir: Optional[Path] = None
    library_file: Optional[Path] = None

    def is_instance(self):
        return self.name.lower() != self.model.lower()

    @property
    def calibration_model_name(self):
        return self.ngen_cal_model_name or self.model


DEFAULT_MODEL_INSTANCES = {

    "PET": [

        ModelInstance(
            model="PET",
            name="pet",
            basefile="config_pet.yaml",
            repo_name="evapotranspiration",
            calib_params_block=""
        )

    ],


    "CFE": [

        ModelInstance(
            model="CFE",
            name="cfe-s",
            basefile="config_cfe-s.yaml",
            repo_name="cfe",
            calib_params_block="cfes_params",
            calib_params_file="cfe-s.yaml",
            ngen_cal_model_name="CFE"
        )

    ],

    "NOM": [

        ModelInstance(
            model="NOM",
            name="noahowp",
            basefile="config_noahowp.input",
            repo_name="noah-owp-modular",
            calib_params_block="noahowp_params",
            calib_params_file="noahowp.yaml",
            ngen_cal_model_name="NoahOWP"
        )

    ],

    "TOPMODEL": [

        ModelInstance(
            model="TOPMODEL",
            name="topmodel",
            repo_name="topmodel",
            calib_params_block="topmodel_params",
            calib_params_file="topmodel.yaml",
            ngen_cal_model_name="TOPMODEL"
        )

    ],

    "SFT": [

        ModelInstance(
            model="SFT",
            name="sft",
            repo_name="SoilFreezeThaw",
            calib_params_block="",
            ngen_cal_model_name="SFT"
        )

    ],

    "SMP": [

        ModelInstance(
            model="SMP",
            name="smp",
            repo_name="SoilMoistureProfiles",
            calib_params_block="",
            ngen_cal_model_name="SMP"
        )

    ],

    "SNOW17": [

        ModelInstance(
            model="Snow17",
            name="snow17",
            basefile="config_snow17.namelist.input",
            repo_name="snow17",
            calib_params_block="snow17_params",
            calib_params_file="snow17.yaml",
            ngen_cal_model_name="Snow17"

        )

    ],

    "SACSMA": [

        ModelInstance(
            model="SacSMA",
            name="sacsma",
            basefile="config_sacsma.namelist.input",
            repo_name="sac-sma",
            calib_params_block="sacsma_params",
            calib_params_file="sac_sma.yaml",
            ngen_cal_model_name="SacSMA"
        )

    ],


    "CASAM": [

        ModelInstance(
            model="CASAM",
            name="casam",
            basefile="config_casam.yaml",
            repo_name="CASAM",
            calib_params_block="casam_params",
            calib_params_file="lgar.yaml",
            ngen_cal_model_name="LGAR"
        )

    ],

    "LSTM": [

        ModelInstance(
            model="LSTM",
            name="lstm",
            repo_name="lstm",
            basefile="config_lstm.yaml",
            calib_params_block=""
        )

    ],

    "DHBV": [

        ModelInstance(
            model="DHBV",
            name="dhbv",
            repo_name="dhbv",
            basefile="config_dhbv.yaml",
            calib_params_block=""
        )

    ],

    "T-ROUTE": [

        ModelInstance(
            model="T-ROUTE",
            name="t-route",
            basefile="config_troute.yaml",
            repo_name="t-route",
            calib_params_block=""
        )

    ],

    "SLOTH": [

        ModelInstance(
            model="sloth",
            name="sloth",
            basefile="",
            repo_name="sloth",
            calib_params_block=""
        )

    ],

}


OFFICIAL_MODEL_VARIANTS = {
    "CFE": {
        "cfe-s": {
            "defaults": {
                "basefile": "config_cfe-s.yaml",
                "repo_name": "cfe",
                "calib_params_block": "cfes_params",
                "calib_params_file": "cfe-s.yaml",
                "ngen_cal_model_name": "CFE",
            },
            "fields": {
                "basefile": {
                    "required": ("cfe-s", "cfe_s"),
                    "forbidden": ("cfe-x", "cfe_x"),
                },
                "calib_params_block": {
                    "required": ("cfes",),
                    "forbidden": ("cfex",),
                },
                "calib_params_file": {
                    "required": ("cfe-s", "cfe_s", "cfes"),
                    "forbidden": ("cfe-x", "cfe_x", "cfex"),
                },
            },
        },
        "cfe-x": {
            "defaults": {
                "basefile": "config_cfe-x.yaml",
                "repo_name": "cfe",
                "calib_params_block": "cfex_params",
                "calib_params_file": "cfe-x.yaml",
                "ngen_cal_model_name": "CFE",
            },
            "fields": {
                "basefile": {
                    "required": ("cfe-x", "cfe_x"),
                    "forbidden": ("cfe-s", "cfe_s"),
                },
                "calib_params_block": {
                    "required": ("cfex",),
                    "forbidden": ("cfes",),
                },
                "calib_params_file": {
                    "required": ("cfe-x", "cfe_x", "cfex"),
                    "forbidden": ("cfe-s", "cfe_s", "cfes"),
                },
            },
        },
    },
}


def _clone_instance(instance: ModelInstance) -> ModelInstance:
    return replace(instance)


def _contains_any_marker(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value.lower() for marker in markers)


def _apply_official_variant_defaults(instance: ModelInstance, model: str):
    variant = OFFICIAL_MODEL_VARIANTS.get(model.upper(), {}).get(
        instance.name.lower()
    )
    if not variant:
        return

    for field, expected in variant["defaults"].items():
        current = getattr(instance, field)
        if current in ("", None):
            setattr(instance, field, expected)

    for field, markers in variant["fields"].items():
        current = getattr(instance, field)
        if current in ("", None):
            continue

        current = str(current)
        if _contains_any_marker(current, markers["forbidden"]):
            raise ValueError(
                f"Model instance '{instance.name}' is an official {model} "
                f"variant, but {field}={current!r} contains a marker for "
                "a different variant family."
            )
        if not _contains_any_marker(current, markers["required"]):
            expected_markers = ", ".join(markers["required"])
            raise ValueError(
                f"Model instance '{instance.name}' is an official {model} "
                f"variant, so {field}={current!r} must contain one of: "
                f"{expected_markers}."
            )


def _merge_instance(
    default_instance: Optional[ModelInstance],
    model: str,
    item: dict
) -> ModelInstance:
    base = _clone_instance(default_instance) if default_instance else ModelInstance(
        model=model,
        name=item["name"],
    )

    if "name" in item:
        base.name = item["name"]
    if "repo_name" in item:
        base.repo_name = item["repo_name"]
    if "calib_params_block" in item:
        base.calib_params_block = item["calib_params_block"]
    if "calib_params_file" in item:
        base.calib_params_file = item["calib_params_file"]
    if "ngen_cal_model_name" in item:
        base.ngen_cal_model_name = item["ngen_cal_model_name"]
    if "basefile" in item:
        base.basefile = item["basefile"]
    if "library_file" in item:
        base.library_file = item["library_file"]

    _apply_official_variant_defaults(base, model)

    return base


def build_model_instances(formulation, model_instances=None):
    """
    Build canonical registry of model instances.

    Returns:
    {
        "CFE": [
            {
                "name": "cfe-s",
                "basefile": "config_cfe-s.yaml"
            }
        ],

        "TOPMODEL": [
            {
                "name": "topmodel"
            }
        ]
    }
    """

    registry = {}

    registry["SLOTH"] = [_clone_instance(instance) for instance in DEFAULT_MODEL_INSTANCES["SLOTH"]]

    model_instances = model_instances or {}

    models = [m.strip().upper() for m in formulation.split(",")]

    for model in models:

        # User-provided instances
        if model in model_instances:

            instances = []
            default_instances = {
                instance.name: instance
                for instance in DEFAULT_MODEL_INSTANCES.get(model, [])
            }

            for item in model_instances[model]:
                name = item["name"]
                instance = _merge_instance(
                    default_instances.get(name),
                    model=model,
                    item=item,
                )

                instances.append(instance)

            registry[model] = instances

        # Default instances
        elif model in DEFAULT_MODEL_INSTANCES:

            registry[model] = [
                _clone_instance(instance)
                for instance in DEFAULT_MODEL_INSTANCES[model]
            ]

        # Generic fallback
        else:

            registry[model] = [

                ModelInstance(
                    model=model,
                    name=model.lower()
                )

            ]

    return registry
