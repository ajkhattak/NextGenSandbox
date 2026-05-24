# ----------------------------
# Registry & Decorator
# ----------------------------
MODELS_REGISTRY = {}

def register_model(key):
    def decorator(cls):
        MODELS_REGISTRY[key.upper()] = cls
        return cls
    return decorator
