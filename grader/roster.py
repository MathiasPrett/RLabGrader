"""Lee los grupos del Excel de coordinación y los cruza con alumnos de Canvas."""
import difflib
import unicodedata
from dataclasses import dataclass, field

import openpyxl

from . import config

SHEET = "Secciones M y J"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(",", " ").replace("-", " ").split())


@dataclass
class RosterEntry:
    name: str           # "Apellidos, Nombres" tal como en el Excel
    section: str        # ej. EYP1113-8-28666
    day: str            # M / J
    group: str          # Grupo 1..7
    user_id: int | None = None
    canvas_name: str | None = None
    match: str = "none"  # exact | fuzzy | none
    warnings: list[str] = field(default_factory=list)


def read_excel(path=config.ROSTER_XLSX):
    if not path.exists():
        raise ValueError(f"No se encontró la planilla de ayudantes: copia el .xlsx en la carpeta "
                         f"'{config.ROSTER_DIR.name}/' ({config.ROSTER_DIR})")
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[SHEET]
    rows = ws.iter_rows(min_row=2, values_only=True)
    return [RosterEntry(name=r[1].strip(), section=r[2], day=r[3], group=r[4])
            for r in rows if r and r[1]]


def groups(entries):
    """{'M': ['Grupo 1', ...], 'J': [...]}"""
    out = {}
    for e in entries:
        out.setdefault(e.day, set()).add(e.group)
    return {d: sorted(g, key=lambda x: int(x.split()[-1])) for d, g in sorted(out.items())}


def _student_sections(student):
    return {e.get("sis_section_id") or "" for e in student.get("enrollments", [])} | {
        str(e.get("course_section_id")) for e in student.get("enrollments", [])}


def match(entries, students):
    """Asigna user_id de Canvas a cada entrada del Excel."""
    by_name = {}
    for s in students:
        by_name.setdefault(norm(s.get("sortable_name", "")), []).append(s)
    keys = list(by_name)
    for e in entries:
        k = norm(e.name)
        cands = by_name.get(k)
        if cands:
            e.match = "exact"
        else:
            close = difflib.get_close_matches(k, keys, n=1, cutoff=0.85)
            if close:
                cands, e.match = by_name[close[0]], "fuzzy"
                e.warnings.append(f"Nombre aproximado: '{by_name[close[0]][0]['sortable_name']}'")
        if not cands:
            e.warnings.append("No encontrado en Canvas")
            continue
        if len(cands) > 1:  # homónimos: desempatar por sección
            same = [s for s in cands if any(e.section in x for x in _student_sections(s))]
            cands = same or cands
            if len(cands) > 1:
                e.warnings.append("Varios alumnos con este nombre")
        e.user_id, e.canvas_name = cands[0]["id"], cands[0].get("sortable_name")
    return entries


def load_group(students, day, group, path=config.ROSTER_XLSX):
    entries = [e for e in read_excel(path) if e.day == day and e.group == group]
    return match(entries, students)
