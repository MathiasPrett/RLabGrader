"""Proveedor Google Gemini (API REST generateContent, sin dependencias extra)."""
import re
import time

import requests

from .base import AIProvider, AIProviderError

API = "https://generativelanguage.googleapis.com/v1beta"
MAX_OUTPUT_TOKENS = 8192  # incluye el "pensamiento" del modelo
MAX_WAIT = 75             # segundos que se espera, como máximo, si Gemini pide esperar por su límite
RETRY_WAITS = (3, 8, 15)  # esperas entre reintentos si el modelo está saturado (503)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, fallbacks: list[str] | None = None):
        super().__init__(model)
        self.fallbacks = fallbacks or []
        self.last_model, self.notice = model, ""
        if not api_key or api_key.startswith("pega_aqui"):
            raise AIProviderError("Falta la API key de Gemini: configúrala en ⚙ Configuración (arriba a la derecha)")
        self.api_key = api_key

    def complete_json(self, system, user):
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": MAX_OUTPUT_TOKENS,
                                 "responseMimeType": "application/json"},
        }
        # Si el modelo está saturado (503/500), se reintenta y luego se prueba con modelos de respaldo
        chain = list(dict.fromkeys([self.model] + [m for m in self.fallbacks if m]))
        busy = []
        for model in chain:
            try:
                text = self._ask(model, body)
            except _Overloaded:
                busy.append(model)
                continue
            except _NoModel:
                if model == self.model:
                    raise AIProviderError(f"Gemini no tiene el modelo '{model}'. Elige otro en ⚙ Configuración.")
                continue  # un respaldo que tu clave no tiene: se salta
            self.last_model = model
            self.notice = (f"{self.model} estaba saturado en Google; respondió {model}."
                           if model != self.model else "")
            return text
        raise AIProviderError(f"Los servidores de Gemini están saturados en este momento ({', '.join(busy)}). "
                              "No es un problema de tu cuenta: intenta de nuevo en unos minutos.")

    def _ask(self, model, body):
        waited, tries = 0.0, 0
        while True:
            try:
                r = requests.post(f"{API}/models/{model}:generateContent", json=body, timeout=180,
                                  headers={"x-goog-api-key": self.api_key})
            except requests.Timeout:
                tries += 1
                if tries <= 1:
                    continue
                raise _Overloaded()
            except requests.RequestException as e:
                raise AIProviderError(f"No se pudo conectar con Gemini: {e}") from e
            if r.status_code == 429:  # límite de uso: esperar lo que pide Gemini y reintentar
                m = re.search(r'"retryDelay":\s*"([\d.]+)s"', r.text)
                wait = float(m.group(1)) + 1 if m else 20
                if waited + wait <= MAX_WAIT:
                    time.sleep(wait)
                    waited += wait
                    continue
                raise AIProviderError(f"Se alcanzó el límite de uso de Gemini; intenta en {round(wait)} s.")
            if r.status_code in (500, 502, 503, 504):  # saturado o caído un momento: esperar y reintentar
                tries += 1
                if tries <= len(RETRY_WAITS):
                    time.sleep(RETRY_WAITS[tries - 1])
                    continue
                raise _Overloaded()
            if r.status_code == 404:
                raise _NoModel()
            if r.status_code in (401, 403):
                raise AIProviderError("Gemini rechazó la API key (¿está bien copiada y habilitada?).")
            if not r.ok:
                raise AIProviderError(f"Gemini respondió {r.status_code}: {r.text[:200]}")
            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = (cand.get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if not text:
                why = cand.get("finishReason") or (data.get("promptFeedback") or {}).get("blockReason") or "?"
                raise AIProviderError(f"Gemini no devolvió respuesta (motivo: {why}).")
            return text


class _Overloaded(Exception):
    pass


class _NoModel(Exception):
    pass


def list_models(api_key: str) -> list[str]:
    """Modelos de la clave que sirven para generar texto (para elegir en ⚙)."""
    out, token = [], None
    for _ in range(5):
        r = requests.get(f"{API}/models", headers={"x-goog-api-key": api_key},
                         params={"pageSize": 200, **({"pageToken": token} if token else {})}, timeout=15)
        r.raise_for_status()
        d = r.json()
        out += [m["name"].removeprefix("models/") for m in d.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]
        token = d.get("nextPageToken")
        if not token:
            break
    return sorted(set(out))
