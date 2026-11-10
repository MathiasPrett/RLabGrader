"""Fachada de IA: la app solo usa AIAdvisor.suggest(). La IA recomienda; nunca decide.

Un caso tiene N ítems (bono: 1 pregunta; taller: varias) que comparten el mismo código.
"""
import hashlib
import json
from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, ValidationError, field_validator

from .. import store
from .providers.base import AIProvider, AIProviderError
from .registry import make_provider


class ItemSuggestion(BaseModel):
    n: int
    puntaje: float                      # fracción de la pauta (0..1)
    nivel: str = ""
    confianza: str = "media"            # alta | media | baja
    respuesta_correcta: bool | None = None
    codigo_funciona: bool | None = None
    codigo_correcto: bool | None = None
    razon: str = ""
    comentario_sugerido: str = ""
    observaciones_codigo: str = ""
    lineas: list[list[int]] | None = None  # dónde está el código de esta pregunta

    @field_validator("puntaje")
    @classmethod
    def _rango(cls, v):
        return min(1.0, max(0.0, float(v)))

    @field_validator("lineas", mode="before")
    @classmethod
    def _lineas(cls, v):
        if not v:
            return None
        if isinstance(v[0], (int, float)):  # [ini, fin] → [[ini, fin]]
            v = [v]
        return [[int(a), int(b)] for a, b in (x[:2] for x in v if len(x) >= 2)]


class Suggestion(BaseModel):
    items: list[ItemSuggestion]
    comentario_general: str = ""


@dataclass
class ItemCase:
    n: int
    pregunta: str
    respuesta_correcta: str
    respuesta_alumno: str
    canvas_marca_correcta: bool | None
    puntos: float
    opciones: list[str] = field(default_factory=list)
    fragmento_lineas: list[list[int]] = field(default_factory=list)
    fragmento_origen: str = "todo"


@dataclass
class CaseInput:
    """Todo lo que la IA ve de un caso. Sin nombre ni ID del alumno."""
    tipo: str                 # bono | taller
    contexto: str
    pauta: str
    codigo: str
    ejecucion_r: str | None
    bd_muestra: str
    items: list[ItemCase]
    solucion_oficial: str = ""
    solucion_output: str = ""
    notas_ayudante: str = ""


SYSTEM = """Eres un asistente de un ayudante que corrige controles de un laboratorio de
Probabilidad y Estadística en R ("bonos" con una pregunta y "talleres" con varias). Tu rol es
SOLO recomendar: el ayudante decide la nota.

Reglas:
- Aplica la pauta entregada a CADA pregunta por separado. El puntaje es la fracción de la pauta (0..1);
  el sistema la multiplica por los puntos de la pregunta.
- Canvas ya comparó la respuesta con la correcta (con margen); usa ese dato.
- Hay muchas formas válidas de resolver con R (table, prop.table, subset, dplyr, sum/length, etc.).
  No penalices un método distinto si es correcto.
- Si se entrega la ejecución del código, úsala para juzgar si funciona y qué obtiene. Los ajustes
  automáticos (rutas, file.choose, precarga de la base) los hizo el sistema: NO son errores del alumno.
- En talleres todo el código viene en un solo campo. Ubica qué líneas responden cada pregunta
  (el número de pregunta es el orden en que el alumno las vio: P1, P2...). Que el código esté
  desordenado o sin títulos no es, por sí solo, motivo de descuento.
- Si una pregunta no tiene código asociado, aplica lo que dice la pauta para ese caso.
- En preguntas sobre un gráfico no puedes ver la imagen: juzga si el código construye el gráfico
  pedido (tipo de gráfico, variables, filtro de datos correcto).
- Si el código obtiene el valor correcto pero la respuesta ingresada difiere (redondeo, tipeo,
  porcentaje en vez de proporción), dilo explícitamente.
- Comentarios para el alumno: breves (1-2 frases), en español, respetuosos y concretos.
  Si la pregunta tiene puntaje completo pueden ir vacíos.

Responde SOLO un objeto JSON:
{"items": [{"n": 1, "puntaje": <uno de los niveles de la pauta>, "nivel": "<texto del nivel>",
  "confianza": "alta|media|baja", "respuesta_correcta": bool, "codigo_funciona": bool|null,
  "codigo_correcto": bool|null, "razon": "<para el ayudante>", "comentario_sugerido": "<para el alumno>",
  "observaciones_codigo": "<texto>", "lineas": [[ini, fin], ...] }, ...],
 "comentario_general": "<comentario breve opcional para el alumno>"}
Incluye exactamente un elemento por cada pregunta."""


def numbered(code: str) -> str:
    return "\n".join(f"{i:>3}| {l}" for i, l in enumerate(code.splitlines(), start=1))


def build_prompt(c: CaseInput) -> str:
    marca = {True: "CORRECTA", False: "INCORRECTA", None: "sin evaluar"}
    parts = [
        f"## Tipo: {c.tipo} ({len(c.items)} pregunta(s))",
        f"## Pauta\n{c.pauta}",
        f"## Contexto del enunciado\n{c.contexto or '(no hay)'}",
    ]
    for it in c.items:
        p = [f"## Pregunta P{it.n} (vale {it.puntos} pts)\n{it.pregunta}"]
        if it.opciones:
            p.append("Alternativas:\n" + "\n".join(f"- {o}" for o in it.opciones))
        p.append(f"Respuesta correcta (Canvas): {it.respuesta_correcta or '(desconocida)'}")
        p.append(f"Respuesta del alumno: {it.respuesta_alumno}  → Canvas: {marca[it.canvas_marca_correcta]}")
        if it.fragmento_origen == "comentarios":
            p.append(f"El alumno tituló su código para esta pregunta en las líneas {it.fragmento_lineas}.")
        parts.append("\n".join(p))
    parts += [
        f"## Código R del alumno (con número de línea)\n```\n{numbered(c.codigo) if c.codigo.strip() else '(vacío: no entregó código)'}\n```",
        f"## Ejecución del código completo\n{c.ejecucion_r or '(no se ejecutó)'}",
        f"## Muestra de la base de datos\n{c.bd_muestra or '(no hay)'}",
    ]
    if c.solucion_oficial:
        parts.append(f"## Una solución de referencia (no es la única válida)\n```r\n{c.solucion_oficial}\n```"
                     + (f"\nSalida:\n{c.solucion_output}" if c.solucion_output else ""))
    if c.notas_ayudante:
        parts.append(f"## Notas del ayudante para esta evaluación\n{c.notas_ayudante}")
    return "\n\n".join(parts)


class AIAdvisor:
    def __init__(self, provider: AIProvider | None = None):
        self._provider = provider

    @property
    def provider(self) -> AIProvider:
        if self._provider is None:
            self._provider = make_provider()
        return self._provider

    def suggest(self, case: CaseInput, use_cache=True) -> Suggestion:
        prompt = build_prompt(case)
        p = self.provider
        key = "ai2:" + hashlib.sha256(f"{p.name}|{p.model}|{SYSTEM}|{prompt}".encode()).hexdigest()
        if use_cache and (hit := store.cache_get(key)):
            return Suggestion(**hit)
        want = {it.n for it in case.items}
        last_err = None
        for _ in range(2):  # un reintento si el JSON viene malo o incompleto
            raw = p.complete_json(SYSTEM, prompt)
            try:
                s = Suggestion(**json.loads(raw))
                got = {i.n for i in s.items}
                if not want <= got:
                    raise ValueError(f"faltan preguntas {sorted(want - got)}")
                s.items = sorted((i for i in s.items if i.n in want), key=lambda i: i.n)
                store.cache_set(key, s.model_dump())
                return s
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as e:
                last_err = e
        raise AIProviderError(f"Respuesta inválida de la IA: {last_err}")


__all__ = ["AIAdvisor", "CaseInput", "ItemCase", "Suggestion", "ItemSuggestion", "asdict"]
