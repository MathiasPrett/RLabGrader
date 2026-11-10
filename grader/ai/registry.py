"""Crea el proveedor según AI_PROVIDER. Para agregar uno: implementar AIProvider y añadirlo aquí."""
from .. import config
from .providers.base import AIProvider, AIProviderError


def _groq():
    from .providers.groq import GroqProvider
    return GroqProvider(config.GROQ_API_KEY, config.GROQ_MODEL)


PROVIDERS = {"groq": _groq}


def make_provider(name: str = config.AI_PROVIDER) -> AIProvider:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise AIProviderError(f"Proveedor de IA desconocido: {name}. Opciones: {list(PROVIDERS)}") from None
