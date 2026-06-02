# ----------------------------
# Formulation Registry
# ----------------------------

FORMULATIONS_REGISTRY = {}


def normalize_formulation(formulation):
    if isinstance(formulation, str):
        models = formulation.split(",")
    else:
        models = formulation

    return ",".join(
        model.strip().upper().replace(" ", "")
        for model in models
        if model and model.strip()
    )


def register_formulation(formulation):
    formulation = normalize_formulation(formulation)
    FORMULATIONS_REGISTRY[formulation] = tuple(formulation.split(","))
    return formulation


def load_formulations_registry():
    return FORMULATIONS_REGISTRY


def get_supported_formulations():
    return list(FORMULATIONS_REGISTRY)


def with_default_routing(formulation):
    formulation = normalize_formulation(formulation)
    models = formulation.split(",")

    if "T-ROUTE" not in models:
        models.append("T-ROUTE")

    return ",".join(models)


def is_registered_formulation(formulation):
    return with_default_routing(formulation) in FORMULATIONS_REGISTRY


register_formulation("NOM,CFE,T-ROUTE")
register_formulation("PET,CFE,T-ROUTE")
register_formulation("NOM,PET,CFE,T-ROUTE")
register_formulation("NOM,TOPMODEL,T-ROUTE")
register_formulation("PET,TOPMODEL,T-ROUTE")
register_formulation("NOM,CASAM,T-ROUTE")
register_formulation("PET,CASAM,T-ROUTE")
register_formulation("NOM,CFE,SMP,SFT,T-ROUTE")
register_formulation("NOM,PET,TOPMODEL,T-ROUTE")
register_formulation("NOM,CASAM,SMP,SFT,T-ROUTE")
register_formulation("SNOW17,PET,CFE,T-ROUTE")
register_formulation("SNOW17,PET,TOPMODEL,T-ROUTE")
register_formulation("LSTM,T-ROUTE")
register_formulation("SNOW17,PET,SACSMA,T-ROUTE")
register_formulation("DHBV,T-ROUTE")
