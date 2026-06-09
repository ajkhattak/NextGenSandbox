from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional


@dataclass
class ModelInstance:

    model: str
    name: str
    repo_name: str = ""
    calib_params_block: str = ""
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
            ngen_cal_model_name="NoahOWP"
        )

    ],

    "TOPMODEL": [

        ModelInstance(
            model="TOPMODEL",
            name="topmodel",
            repo_name="topmodel",
            calib_params_block="topmodel_params",
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


def _clone_instance(instance: ModelInstance) -> ModelInstance:
    return replace(instance)


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
    if "ngen_cal_model_name" in item:
        base.ngen_cal_model_name = item["ngen_cal_model_name"]
    if "basefile" in item:
        base.basefile = item["basefile"]
    if "library_file" in item:
        base.library_file = item["library_file"]

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
