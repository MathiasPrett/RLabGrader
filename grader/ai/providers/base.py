"""Interfaz que cualquier proveedor de IA debe cumplir."""
from abc import ABC, abstractmethod


class AIProviderError(RuntimeError):
    pass


class AIProvider(ABC):
    name: str = "base"

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def complete_json(self, system: str, user: str) -> str:
        """Devuelve el texto de la respuesta, que debe ser un objeto JSON."""
