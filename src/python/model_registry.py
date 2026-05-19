# model_registry.py
from src.python.model_instance import ModelInstance

 
DEFAULT_MODEL_VARIANTS = {

    "PET": [

        ModelInstance(
            model="PET",
            name="pet",
            basefile="config_pet.yaml",
            repo_name="evapotranspiration"
        )

    ],


    "CFE": [

        ModelInstance(
            model="CFE",
            name="cfe-s",
            basefile="config_cfe-s.yaml",
            repo_name="cfe"
        )

    ],

    "NOM": [

        ModelInstance(
            model="NOM",
            name="noahowp",
            basefile="config_noahowp.input",
            repo_name="noah-owp-modular"
        )

    ],

    "TOPMODEL": [

        ModelInstance(
            model="TOPMODEL",
            name="topmodel",
            repo_name="topmodel"
        )

    ],

    "SFT": [

        ModelInstance(
            model="SFT",
            name="sft",
            repo_name="SoilFreezeThaw"
        )

    ],

    "SMP": [

        ModelInstance(
            model="SMP",
            name="smp",
            repo_name="SoilMoistureProfiles"
        )

    ],
    
    "SNOW17": [

        ModelInstance(
            model="Snow17",
            name="snow17",
            repo_name="snow17"
        )

    ],

    "SACSMA": [

        ModelInstance(
            model="SacSMA",
            name="sacsma",
            basefile="config_sacsma.namelist.input",
            repo_name="sac-sma"
        )

    ],

    
    "LSTM": [

        ModelInstance(
            model="LSTM",
            name="lstm",
            repo_name="lstm"
        )

    ],

    "DHBV": [

        ModelInstance(
            model="DHBV",
            name="dhbv",
            repo_name="dhbv"
        )

    ],

    "T-ROUTE": [

        ModelInstance(
            model="T-ROUTE",
            name="t-route",
            basefile="config_troute.yaml",
            repo_name="t-route"
        )

    ],

    "SLOTH": [

        ModelInstance(
            model="sloth",
            name="sloth",
            basefile="",
            repo_name="sloth"
        )

    ],

}


def build_model_registry(formulation, model_variants=None):
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

    registry["SLOTH"] = DEFAULT_MODEL_VARIANTS["SLOTH"]

    model_variants = model_variants or {}

    models = [m.strip().upper() for m in formulation.split(",")]

    for model in models:

        # ==============================================================
        # User-provided variants
        # ==============================================================
        print ("E4 ", model)
        if model in model_variants:

            instances = []

            for item in model_variants[model]:

                instance = ModelInstance(
                    model=model,
                    name=item["name"],
                    basefile=item.get("basefile")
                )

                instances.append(instance)

            registry[model] = instances
        # ==============================================================
        # Default variants
        # ==============================================================

        elif model in DEFAULT_MODEL_VARIANTS:

            registry[model] = DEFAULT_MODEL_VARIANTS[model]

        # ==============================================================
        # Generic fallback
        # ==============================================================

        else:

            registry[model] = [

                ModelInstance(
                    model=model,
                    name=model.lower()
                )

            ]

    return registry
