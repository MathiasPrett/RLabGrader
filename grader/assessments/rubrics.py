"""Pautas de corrección como datos. Se leen del Excel si existe la hoja; si no, valores por defecto."""
from dataclasses import dataclass

import openpyxl

from .. import config


@dataclass
class Level:
    score: float          # fracción del puntaje de la pregunta (0..1)
    description: str
    note: str = ""


@dataclass
class Rubric:
    name: str
    levels: list[Level]
    general_note: str = ""

    def as_text(self) -> str:
        lines = [f"- {l.score}: {l.description}" + (f" (Nota: {l.note})" if l.note else "") for l in self.levels]
        if self.general_note:
            lines.append(f"Nota general: {self.general_note}")
        return "\n".join(lines)


DEFAULTS = {
    "Pauta Bonos": Rubric("Pauta Bonos", [
        Level(0, "Respuesta y código incorrectos, código no relacionado con la pregunta o que no funciona",
              "Incluso si la respuesta es correcta, si no hay código no colocar puntaje. Colocar como comentario eso"),
        Level(0.5, "Código que funciona, pero presenta errores en el cálculo",
              "Por ejemplo, sabían qué código usar pero leyeron mal el enunciado"),
        Level(0.7, "Código correcto, pero respuesta final incorrecta"),
        Level(1, "Código y respuesta correctos"),
    ]),
    "Pauta Taller (tentativa)": Rubric("Pauta Taller (tentativa)", [
        Level(0, "Respuesta y código incorrectos, código no relacionado con la pregunta o que no funciona"),
        Level(0.5, "Código que funciona, pero presenta errores en el cálculo",
              "Si seleccionaron o escribieron la respuesta correcta colocar la mitad del puntaje. "
              "Colocar como comentario que falta el código"),
        Level(0.7, "Código correcto, pero respuesta final incorrecta"),
        Level(1, "Código y respuesta correctos"),
    ], "Dependiendo del error pueden variar el puntaje según su criterio, pero en general considerar la pauta"),
}


def load_rubric(sheet: str, path=config.ROSTER_XLSX) -> Rubric:
    """Lee una hoja tipo 'Pauta Bonos': columnas Puntaje(desc), valor, Notas."""
    try:
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[sheet]
    except (KeyError, FileNotFoundError):
        return DEFAULTS[sheet]
    levels, general = [], ""
    for row in ws.iter_rows(min_row=2, values_only=True):
        desc, val, note = (list(row) + [None, None, None])[:3]
        if isinstance(val, (int, float)) and desc:
            levels.append(Level(float(val), str(desc).strip(" :"), str(note or "").strip()))
        else:  # fila "Nota:" en cualquier columna, con el texto a su derecha
            cells = [str(x).strip() for x in row if x]
            if len(cells) >= 2 and cells[0].lower().startswith("nota"):
                general = cells[1]
    return Rubric(sheet, sorted(levels, key=lambda l: l.score), general) if levels else DEFAULTS[sheet]
