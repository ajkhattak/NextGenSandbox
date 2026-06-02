from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ModelInstance:

    model: str
    name: str
    repo_name: str
    calib_params_name: str
    basefile: Optional[str] = None
    config_dir: Optional[Path] = None
    outputs_dir: Optional[Path] = None
    exe_dir: Optional[Path] = None

    def is_instance(self):
        return self.name.lower() != self.model.lower()


DEFAULT_MODEL_INSTANCES = {

    "PET": [

        ModelInstance(
            model="PET",
            name="pet",
            basefile="config_pet.yaml",
            repo_name="evapotranspiration",
            calib_params_name=""
        )

    ],


    "CFE": [

        ModelInstance(
            model="CFE",
            name="cfe-s",
            basefile="config_cfe-s.yaml",
            repo_name="cfe",
            calib_params_name="cfes_params"
        )

    ],

    "NOM": [

        ModelInstance(
            model="NOM",
            name="noahowp",
            basefile="config_noahowp.input",
            repo_name="noah-owp-modular",
            calib_params_name="noahowp_params"
        )

    ],

    "TOPMODEL": [

        ModelInstance(
            model="TOPMODEL",
            name="topmodel",
            repo_name="topmodel",
            calib_params_name="topmodel_params"
        )

    ],

    "SFT": [

        ModelInstance(
            model="SFT",
            name="sft",
            repo_name="SoilFreezeThaw",
            calib_params_name=""
        )

    ],

    "SMP": [

        ModelInstance(
            model="SMP",
            name="smp",
            repo_name="SoilMoistureProfiles",
            calib_params_name=""
        )

    ],
    
    "SNOW17": [

        ModelInstance(
            model="Snow17",
            name="snow17",
            basefile="config_snow17.namelist.input",
            repo_name="snow17",
            calib_params_name="snow17_params"
            
        )

    ],

    "SACSMA": [

        ModelInstance(
            model="SacSMA",
            name="sacsma",
            basefile="config_sacsma.namelist.input",
            repo_name="sac-sma",
            calib_params_name="sacsma_params"
        )

    ],


    "CASAM": [

        ModelInstance(
            model="CASAM",
            name="casam",
            basefile="config_casam.yaml",
            repo_name="CASAM",
            calib_params_name="casam_params"
        )

    ],
    
    "LSTM": [

        ModelInstance(
            model="LSTM",
            name="lstm",
            repo_name="lstm",
            basefile="config_lstm.yaml",
            calib_params_name=""
        )

    ],

    "DHBV": [

        ModelInstance(
            model="DHBV",
            name="dhbv",
            repo_name="dhbv",
            basefile="config_dhbv.yaml",
            calib_params_name=""
        )

    ],

    "T-ROUTE": [

        ModelInstance(
            model="T-ROUTE",
            name="t-route",
            basefile="config_troute.yaml",
            repo_name="t-route",
            calib_params_name=""
        )

    ],

    "SLOTH": [

        ModelInstance(
            model="sloth",
            name="sloth",
            basefile="",
            repo_name="sloth",
            calib_params_name=""
        )

    ],

}


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

    registry["SLOTH"] = DEFAULT_MODEL_INSTANCES["SLOTH"]

    model_instances = model_instances or {}

    models = [m.strip().upper() for m in formulation.split(",")]

    for model in models:

        # User-provided instances
        if model in model_instances:

            instances = []

            for item in model_instances[model]:

                instance = ModelInstance(
                    model=model,
                    name=item["name"],
                    basefile=item.get("basefile"),
                    repo_name=item.get("repo_name"),
                    calib_params_name=item.get("calib_params_name")
                )

                instances.append(instance)

            registry[model] = instances
        
        # Default instances
        elif model in DEFAULT_MODEL_INSTANCES:

            registry[model] = DEFAULT_MODEL_INSTANCES[model]

        # Generic fallback
        else:

            registry[model] = [

                ModelInstance(
                    model=model,
                    name=model.lower()
                )

            ]

    return registry
