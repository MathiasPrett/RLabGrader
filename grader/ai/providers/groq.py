"""Proveedor Groq (API compatible con OpenAI)."""
from groq import Groq

from .base import AIProvider, AIProviderError


class GroqProvider(AIProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str):
        super().__init__(model)
        if not api_key:
            raise AIProviderError("Falta GROQ_API_KEY en .env")
        self.client = Groq(api_key=api_key)

    def complete_json(self, system, user):
        try:
            r = self.client.chat.completions.create(
                model=self.model, temperature=0.1,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
        except Exception as e:  # noqa: BLE001 — se muestra al usuario tal cual
            raise AIProviderError(f"Groq: {e}") from e
        return r.choices[0].message.content or ""
