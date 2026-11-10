"""Registro de tipos de evaluación y reconocimiento por nombre."""
import re

from .bono import BonoType
from .rubrics import load_rubric
from .taller import TallerType

PATTERNS = {
    "bono": re.compile(r"^\s*bono\s*\d{2}\s*$", re.I),      # Bono03, Bono05...
    "taller": re.compile(r"^\s*taller\s*\d+\s*$", re.I),    # Taller 1, Taller 2...
}

_TYPES = {
    "bono": lambda: BonoType("bono", "Bono", load_rubric("Pauta Bonos")),
    "taller": lambda: TallerType("taller", "Taller", load_rubric("Pauta Taller (tentativa)")),
}


def list_types():
    return list(_TYPES)


def get_type(key):
    return _TYPES[key]()


def detect_type(name: str) -> str | None:
    """Tipo según el nombre de la tarea; None si no es un bono ni taller del laboratorio."""
    return next((k for k, p in PATTERNS.items() if p.match(name or "")), None)
