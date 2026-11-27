"""Proveedor Groq (API compatible con OpenAI)."""
import re
import time

from groq import Groq

from .base import AIProvider, AIProviderError

MAX_OUTPUT_TOKENS = 2500  # la respuesta (incluye el razonamiento del modelo); cuenta para el límite por minuto
MAX_WAIT = 75             # segundos que se espera, como máximo, si Groq pide esperar por su límite


class GroqProvider(AIProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str):
        super().__init__(model)
        if not api_key or api_key.startswith("pega_aqui"):
            raise AIProviderError("Falta la API key de Groq: configúrala en ⚙ Configuración (arriba a la derecha)")
        # los reintentos por límite de uso los maneja complete_json (respetando lo que pide Groq)
        self.client = Groq(api_key=api_key, max_retries=0, timeout=150)

    def complete_json(self, system, user):
        waited, timeouts, bad_json = 0.0, 0, 0
        while True:
            try:
                r = self.client.chat.completions.create(
                    model=self.model, temperature=0.1, max_completion_tokens=MAX_OUTPUT_TOKENS,
                    response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                return r.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "timed out" in msg.lower() or type(e).__name__ in ("APITimeoutError", "APIConnectionError"):
                    timeouts += 1
                    if timeouts <= 1:  # Groq se demoró o se cortó la conexión: un reintento
                        continue
                    raise AIProviderError("Groq no respondió a tiempo (dos intentos). Prueba de nuevo en un momento.") from e
                if "Failed to generate JSON" in msg or "json_validate_failed" in msg:
                    bad_json += 1
                    if bad_json <= 2:  # el modelo produjo un JSON inválido: se vuelve a pedir
                        continue
                    raise AIProviderError("Groq no logró generar una respuesta válida. Prueba de nuevo.") from e
                if "413" in msg or "Request too large" in msg:
                    raise AIProviderError("El caso es demasiado grande para el límite por minuto de tu cuenta de "
                                          "Groq. Intenta de nuevo; si persiste, acorta el código editado.") from e
                m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", msg)
                if "429" in msg and m:
                    wait = int(m.group(1) or 0) * 60 + float(m.group(2)) + 1
                    if waited + wait <= MAX_WAIT:  # límite por minuto: esperar lo que pide Groq y reintentar
                        time.sleep(wait)
                        waited += wait
                        continue
                    raise AIProviderError(f"Se alcanzó el límite de uso de Groq; intenta en {round(wait)} s.") from e
                raise AIProviderError(f"Groq: {e}") from e
