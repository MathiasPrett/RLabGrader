"""Detecta claves de Canvas sospechosas: muchos alumnos llegan al mismo valor distinto a la clave.

Si al menos MIN_GROUP alumnos coinciden en un valor que no es la clave, y son más que los que coinciden
con la clave, lo más probable es que la clave esté mal (o que el enunciado sea ambiguo). Solo avisa:
la decisión es del ayudante.
"""
from .assessments.base import Question, check_answer, parse_number

MIN_GROUP = 3


def _tolerance(q: Question, value: float) -> float:
    margins = [float(k.get("margin") or 0) for k in q.keys if k.get("numerical_answer_type") == "exact_answer"]
    m = max(margins) if margins else 0
    return m if m > 0 else max(abs(value) * 0.002, 1e-6)


def suspects(questions: list[Question], all_submission_data: list[list[dict]]) -> dict[int, dict]:
    """{question_id: aviso} para las preguntas numéricas con una clave sospechosa."""
    by_id = {q.id: q for q in questions if q.type == "numerical_question" and q.keys}
    answers: dict[int, list[float]] = {}
    for data in all_submission_data:
        for d in data or []:
            q = by_id.get(int(d["question_id"]))
            v = parse_number(d.get("text")) if q else None
            if v is not None:
                answers.setdefault(q.id, []).append(v)
    out = {}
    for qid, vals in answers.items():
        q = by_id[qid]
        ok = [v for v in vals if check_answer(q, {"text": repr(v)})]
        wrong = sorted(v for v in vals if not check_answer(q, {"text": repr(v)}))
        best: list[float] = []
        for i, v in enumerate(wrong):  # el grupo más grande de respuestas incorrectas parecidas entre sí
            tol = _tolerance(q, v)
            group = [w for w in wrong[i:] if w - v <= 2 * tol]
            if len(group) > len(best):
                best = group
        if len(best) >= MIN_GROUP and len(best) > len(ok):
            center = sorted(best)[len(best) // 2]
            out[qid] = {"value": round(center, 6), "count": len(best), "correct": len(ok), "total": len(vals),
                        "key": q.correct}
    return out


def message(alert: dict) -> str:
    return (f"La clave de Canvas podría estar mal: {alert['count']} de {alert['total']} alumnos respondieron "
            f"≈ {alert['value']:g} y solo {alert['correct']} coinciden con la clave ({alert['key']}). "
            "Revisa antes de descontar.")


def short_text(q: Question, n: int = 170) -> str:
    """La parte que distingue a la pregunta (muchas comparten el mismo comienzo): la pregunta final."""
    t = " ".join(q.text.split())
    for sep in ("responda:", "Responda:", "Pregunta:", "pregunta:"):
        if sep in t:
            t = t.rsplit(sep, 1)[1].strip()
            break
    else:
        qs = [s for s in t.split("¿")[1:]]
        if qs:
            t = "¿" + qs[-1]
    return t if len(t) <= n else "…" + t[-n:]


def question_stats(questions: list[Question], all_submission_data: list[list[dict]]) -> list[dict]:
    """Por pregunta de respuesta: cuántos la respondieron y cuántos coinciden con la clave actual."""
    by_id = {q.id: q for q in questions if q.keys and q.type in ("numerical_question", "multiple_choice_question",
                                                                  "true_false_question") and not q.is_base}
    acc: dict[int, list[int]] = {}
    for data in all_submission_data:
        for d in data or []:
            q = by_id.get(int(d["question_id"]))
            if not q or not str(d.get("text") or "").strip():
                continue
            ok = check_answer(q, d)
            a = acc.setdefault(q.id, [0, 0])
            a[0] += 1
            a[1] += 1 if ok else 0
    order = {q.id: i for i, q in enumerate(questions)}
    return [{"qid": qid, "text": short_text(by_id[qid]), "answered": n, "correct": c,
             "pct": round(100 * c / n) if n else None}
            for qid, (n, c) in sorted(acc.items(), key=lambda kv: order.get(kv[0], 0))]
