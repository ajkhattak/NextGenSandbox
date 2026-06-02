# ----------------------------
# Registry & Decorator
# src/python/models_registry.py
# ----------------------------
MODELS_REGISTRY = {}

def register_model(key):
    def decorator(cls):
        MODELS_REGISTRY[key.upper()] = cls
        return cls
    return decorator


def load_model_registry():
    import src.python.models.lstm
    import src.python.models.nom
    import src.python.models.cfe
    import src.python.models.topmodel
    import src.python.models.pet
    import src.python.models.sacsma
    import src.python.models.casam
    import src.python.models.snow17
    import src.python.models.troute
    import src.python.models.sft
    import src.python.models.smp
    import src.python.models.dhbv

    return MODELS_REGISTRY
