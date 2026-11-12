"""Modelo genérico de evaluación: contexto + preguntas de respuesta + código + pauta.

Un tipo de evaluación (bono, taller, ...) decide cómo agrupar las respuestas de un
alumno en "ítems a corregir", cómo ubicar el código de cada ítem y a qué pregunta
se escribe el puntaje.
"""
import re
from dataclasses import asdict, dataclass, field

from ..text import compact, html_to_text
from .rubrics import Rubric

CONTEXT_TYPES = {"text_only_question"}
CODE_TYPES = {"essay_question"}
NON_ANSWER_TYPES = CONTEXT_TYPES | CODE_TYPES | {"file_upload_question"}
BASE_RE = re.compile(r"punto\s+base", re.I)  # pregunta regalo, no se corrige


@dataclass
class Question:
    id: int
    type: str
    html: str
    text: str
    points: float             # puntaje real (el del grupo si viene de un grupo)
    group_id: int | None
    position: int
    correct: str              # descripción legible de la respuesta correcta
    options: dict[int, str]   # selección múltiple: id → texto
    keys: list[dict] = field(default_factory=list)  # respuestas con peso 100 (clave actual)

    @classmethod
    def from_canvas(cls, q, idx, group_points: dict | None = None):
        gid = q.get("quiz_group_id")
        pts = (group_points or {}).get(gid, q.get("points_possible")) if gid else q.get("points_possible")
        opts = {a["id"]: compact(a.get("html") or a.get("text") or "") for a in q.get("answers") or []
                if q["question_type"] in ("multiple_choice_question", "true_false_question",
                                          "multiple_answers_question", "multiple_dropdowns_question")}
        return cls(id=q["id"], type=q["question_type"], html=q.get("question_text") or "",
                   text=html_to_text(q.get("question_text")), points=float(pts or 0),
                   group_id=gid, position=q.get("position") or idx,
                   correct=describe_correct(q), options=opts,
                   keys=[{k: a.get(k) for k in ("id", "numerical_answer_type", "exact", "margin", "start", "end",
                                                "approximate", "precision", "text")}
                         for a in q.get("answers") or [] if (a.get("weight") or 0) >= 100])

    @property
    def is_base(self):
        return bool(BASE_RE.search(self.text)) and self.type not in NON_ANSWER_TYPES

    def student_answer(self, d: dict) -> str:
        """Texto de lo que respondió el alumno (traduce answer_id en selección múltiple)."""
        if self.options:
            aid = d.get("answer_id")
            if aid is None and str(d.get("text") or "").isdigit():
                aid = int(d["text"])
            if aid is not None:
                return self.options.get(int(aid), f"(opción {aid})")
        return html_to_text(d.get("text"))


def parse_number(text) -> float | None:
    """Número escrito por el alumno: '0.4458', '0,4458' (coma decimal), '20,254.5', '61,590', '35%'."""
    t = re.sub(r"[\s$]", "", str(text or ""))
    pct = t.endswith("%")
    t = t.rstrip("%")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:
        # miles solo si es del tipo 61,590 o 1,234,567 (y no empieza en 0); si no, coma decimal
        t = t.replace(",", "") if re.fullmatch(r"[1-9]\d{0,2}(,\d{3})+", t) else t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return v / 100 if pct else v


def check_answer(q: "Question", d: dict) -> bool | None:
    """¿La respuesta coincide con la clave ACTUAL de la pregunta? None si no se puede saber."""
    if not q.keys:
        return None
    if q.type == "numerical_question":
        v = parse_number(d.get("text"))
        if v is None:
            return False if str(d.get("text") or "").strip() else None
        for k in q.keys:
            t = k.get("numerical_answer_type") or "exact_answer"
            if t == "exact_answer" and k.get("exact") is not None:
                if abs(v - float(k["exact"])) <= float(k.get("margin") or 0) + 1e-9:
                    return True
            elif t == "range_answer" and k.get("start") is not None:
                if float(k["start"]) - 1e-9 <= v <= float(k["end"]) + 1e-9:
                    return True
            elif t == "precision_answer" and k.get("approximate") is not None:
                p = int(k.get("precision") or 0)
                if p and float(f"{v:.{p}g}") == float(f"{float(k['approximate']):.{p}g}"):
                    return True
        return False
    if q.type in ("multiple_choice_question", "true_false_question"):
        aid = d.get("answer_id")
        if aid is None and str(d.get("text") or "").isdigit():
            aid = int(d["text"])
        return None if aid is None else int(aid) in {k["id"] for k in q.keys}
    return None


def describe_correct(q) -> str:
    out = []
    for a in q.get("answers") or []:
        if (a.get("weight") or 0) < 100:
            continue
        t = a.get("numerical_answer_type")
        if t == "exact_answer":
            out.append(f"{a.get('exact')} (± {a.get('margin') or 0})")
        elif t == "range_answer":
            out.append(f"entre {a.get('start')} y {a.get('end')}")
        elif t == "precision_answer":
            out.append(f"{a.get('approximate')} (precisión {a.get('precision')})")
        else:
            out.append(compact(a.get("html") or a.get("text") or ""))
    return " | ".join(x for x in out if x)


@dataclass
class Item:
    """Una unidad a corregir: una respuesta del alumno + dónde está su código."""
    n: int
    label: str
    answer_q: Question
    answer_text: str
    canvas_correct: bool | None   # según la clave ACTUAL de la pregunta (recalculado)
    canvas_points: float
    code_q: Question | None
    code_text: str
    fragment_lines: list[list[int]] = field(default_factory=list)  # [[ini, fin], ...] 1-based
    fragment_source: str = "todo"  # todo | comentarios | ia | no detectado
    code_source: str = "canvas"     # canvas | buzón (parche local)
    code_in_submission: bool = True  # False si la entrega no incluye la pregunta de código
    canvas_flag: bool | None = None  # marca guardada por Canvas al entregar (puede quedar obsoleta)

    @property
    def points(self):
        return self.answer_q.points

    def fragment(self) -> str:
        if not self.fragment_lines:
            return self.code_text
        lines = self.code_text.splitlines()
        return "\n".join("\n".join(lines[a - 1:b]) for a, b in self.fragment_lines)

    def to_dict(self):
        d = asdict(self)
        d["points"] = self.points
        return d


def answered(submission_data):
    return {int(d["question_id"]): d for d in submission_data or []}


def parse_correct(v):
    return {"true": True, "false": False}.get(str(v).lower())


@dataclass
class AssessmentType:
    key: str
    title: str
    rubric: Rubric
    segment_code: bool = False  # True: el código de todas las preguntas viene junto

    # ---- clasificación de preguntas ----
    @staticmethod
    def classify(questions: list[Question]):
        ctx = [q for q in questions if q.type in CONTEXT_TYPES]
        code = [q for q in questions if q.type in CODE_TYPES]
        ans = [q for q in questions if q.type not in NON_ANSWER_TYPES]
        return ctx, code, ans

    def contexts_for(self, questions, submission_data=None) -> list[Question]:
        """Contexto que vio el alumno (si hay contextos sorteados, solo el suyo)."""
        ctx, _, _ = self.classify(questions)
        if submission_data:
            ids = {int(d["question_id"]) for d in submission_data}
            mine = [q for q in ctx if q.id in ids]
            grouped = any(q.group_id for q in ctx)
            if mine or grouped:
                return mine
        return ctx

    def context_text(self, questions, submission_data=None) -> str:
        return "\n\n".join(q.text for q in self.contexts_for(questions, submission_data))

    def base_points(self, questions, submission_data) -> float:
        data = answered(submission_data)
        return sum(float(data[q.id].get("points") or 0) for q in questions if q.is_base and q.id in data)

    # ---- por alumno ----
    def build_items(self, questions: list[Question], submission_data: list[dict]) -> list[Item]:
        """Ítems en el orden en que el alumno vio las preguntas (orden de submission_data)."""
        by_id = {q.id: q for q in questions}
        _, code, _ = self.classify(questions)
        data = answered(submission_data)
        code_q = next((q for q in code if q.id in data), code[0] if code else None)
        code_text = html_to_text(data.get(code_q.id, {}).get("text")) if code_q else ""
        items = []
        for d in submission_data or []:
            q = by_id.get(int(d["question_id"]))
            if not q or q.type in NON_ANSWER_TYPES or q.is_base:
                continue
            n = len(items) + 1
            items.append(Item(
                n=n, label=f"P{n}", answer_q=q,
                answer_text=q.student_answer(d) or "(sin respuesta)",
                canvas_correct=(lambda c: parse_correct(d.get("correct")) if c is None else c)(check_answer(q, d)),
                canvas_flag=parse_correct(d.get("correct")),
                canvas_points=float(d.get("points") or 0),
                code_q=code_q, code_text=code_text,
                code_in_submission=bool(code_q and code_q.id in data)))
        if self.segment_code and items:
            from .segment import segment
            found = segment(code_text, len(items))
            for it in items:
                if it.n in found:
                    it.fragment_lines, it.fragment_source = found[it.n], "comentarios"
                else:
                    it.fragment_source = "no detectado"
        return items

    def score_targets(self, item: Item, fraction: float) -> dict[int, float]:
        """Qué preguntas modificar en Canvas y con cuántos puntos (pauta = fracción del puntaje).

        La pregunta de código (ensayo) se marca explícitamente con 0: si queda sin puntaje,
        Canvas deja la entrega en 'pending_review' y no la considera corregida.
        """
        out = {item.answer_q.id: round(fraction * item.points, 4)}
        if item.code_q and item.code_in_submission:
            out[item.code_q.id] = 0.0
        return out
