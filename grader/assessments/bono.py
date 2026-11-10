"""Bono: una pregunta de respuesta (sorteada de un grupo) + una pregunta de código R."""
from .base import AssessmentType


class BonoType(AssessmentType):
    """El código completo corresponde a la única pregunta; el puntaje va en la pregunta de respuesta."""
