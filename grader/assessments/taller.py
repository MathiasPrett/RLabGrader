"""Taller: varias preguntas (sorteadas por grupo) y un único campo con el código de todas."""
from dataclasses import dataclass

from .base import AssessmentType


@dataclass
class TallerType(AssessmentType):
    segment_code: bool = True
