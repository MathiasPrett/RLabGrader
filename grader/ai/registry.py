"""Crea el proveedor según AI_PROVIDER. Para agregar uno: implementar AIProvider y añadirlo aquí."""
from .. import config
from .providers.base import AIProvider, AIProviderError


def _groq():
    from .providers.groq import GroqProvider
    return GroqProvider(config.GROQ_API_KEY, config.GROQ_MODEL)


def _gemini():
    from .providers.gemini import GeminiProvider
    return GeminiProvider(config.GEMINI_API_KEY, config.GEMINI_MODEL, config.GEMINI_FALLBACK_MODELS)


PROVIDERS = {"groq": _groq, "gemini": _gemini}


def model_label() -> str:
    return {"groq": config.GROQ_MODEL, "gemini": config.GEMINI_MODEL}.get(config.AI_PROVIDER, "?")


def make_provider(name: str | None = None) -> AIProvider:
    name = name or config.AI_PROVIDER
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise AIProviderError(f"Proveedor de IA desconocido: {name}. Opciones: {list(PROVIDERS)}") from None
