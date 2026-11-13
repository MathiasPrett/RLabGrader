"""Lógica de la app: carga una evaluación, arma la vista por alumno, ejecuta R/IA y envía notas."""
import threading
from dataclasses import dataclass, field

from . import config, overrides, r_runner, resources, roster, store
from .ai import AIAdvisor, CaseInput, ItemCase
from .assessments import AssessmentType, Item, Question, detect_type, get_type
from .canvas_client import CanvasClient


@dataclass
class Evaluation:
    assignment: dict
    quiz_id: int
    questions: list[Question]
    atype: AssessmentType
    subs: dict[int, dict]            # user_id -> submission (assignment API)
    qsubs: dict[int, dict]           # user_id -> quiz submission
    items: dict[int, list[Item]] = field(default_factory=dict)

    @property
    def id(self):
        return self.assignment["id"]


class Service:
    def __init__(self):
        self.client = CanvasClient()
        self.advisor = AIAdvisor()
        self._students = None
        self._evals: dict[int, Evaluation] = {}
        self._lock = threading.Lock()

    # ---------- catálogos ----------
    def students(self, refresh=False):
        key = f"students:{config.COURSE_ID}"
        if self._students is None or refresh:
            self._students = None if refresh else store.cache_get_fresh(key, 12 * 3600)
        if self._students is None:
            self._students = [{k: s.get(k) for k in ("id", "name", "sortable_name", "enrollments")}
                              for s in self.client.students()]
            store.cache_set(key, self._students)
        return self._students

    def assessments(self):
        """Solo BonoXX y Taller N (los del laboratorio)."""
        out = []
        for a in self.client.quiz_assignments():
            t = detect_type(a["name"])
            if t:
                out.append({"id": a["id"], "name": a["name"], "quiz_id": a["quiz_id"], "type": t,
                            "due_at": a.get("due_at")})
        out.sort(key=lambda a: (a["type"], a["name"].lower()))
        return out

    @staticmethod
    def groups():
        return roster.groups(roster.read_excel())

    # ---------- carga ----------
    def load(self, assignment_id, type_key=None, refresh=False) -> Evaluation:
        if refresh:
            self.students(refresh=True)
        with self._lock:
            ev = self._evals.get(assignment_id)
            if ev and not refresh and (type_key is None or ev.atype.key == type_key):
                return ev
            a = self.client.assignment(assignment_id)
            qid = a["quiz_id"]
            raw = self.client.quiz_questions(qid)
            gpts = self.client.quiz_group_points(qid, [q.get("quiz_group_id") for q in raw])
            questions = [Question.from_canvas(q, i, gpts) for i, q in enumerate(raw)]
            atype = get_type(type_key or detect_type(a["name"]) or "bono")
            qsubs = {q["user_id"]: q for q in self.client.quiz_submissions(qid)}
            ev = Evaluation(a, qid, questions, atype, {}, qsubs)  # subs se llenan por grupo
            try:  # bases de datos enlazadas en los enunciados → carpeta local
                resources.download_linked(self.client, assignment_id, [q.html for q in questions])
            except Exception:  # noqa: BLE001 — no bloquea la carga
                pass
            self._evals[assignment_id] = ev
            return ev

    def ensure_subs(self, ev: Evaluation, user_ids, refresh=False):
        need = [u for u in user_ids if u and (refresh or u not in ev.subs)]
        if need:
            got = {s["user_id"]: s for s in self.client.submissions_for(ev.id, need)}
            for u in need:
                ev.subs[u] = got.get(u, {"workflow_state": "unsubmitted"})
                ev.items.pop(u, None)

    def sub_data(self, ev, user_id):
        sub = ev.subs.get(user_id) or {}
        hist = sub.get("submission_history") or []
        last = max(hist, key=lambda h: h.get("attempt") or 0) if hist else sub
        return last.get("submission_data") or []

    def items_for(self, ev: Evaluation, user_id) -> list[Item]:
        if user_id not in ev.items:
            items = ev.atype.build_items(ev.questions, self.sub_data(ev, user_id))
            ov = overrides.load(ev.id)
            if items and not items[0].code_text.strip() and (ext := overrides.external_code(ov, user_id)):
                for it in items:  # parche local: código recibido en otro buzón (no está en Canvas)
                    it.code_text, it.code_source = ext, "buzón"
            ev.items[user_id] = items
        return ev.items[user_id]

    def pauta_text(self, ev) -> str:
        extra = overrides.load(ev.id).get("pauta_extra", "")
        base = ev.atype.rubric.as_text()
        return f"{base}\n\nEXCEPCIÓN PARA ESTA EVALUACIÓN (tiene prioridad sobre la pauta):\n{extra}" if extra else base

    def contexts(self, ev, user_id):
        return ev.atype.contexts_for(ev.questions, self.sub_data(ev, user_id))

    def data_files(self, ev, user_id):
        """BD del contexto que le tocó al alumno."""
        return resources.files_for(self.client, ev.id, [q.html for q in self.contexts(ev, user_id)])

    def code_of(self, ev, user_id) -> str:
        items = self.items_for(ev, user_id)
        return items[0].code_text if items else ""

    @staticmethod
    def status(sub, local_sent=None):
        """Según Canvas: 'graded' = corregida (todas las preguntas con puntaje).
        local_sent (parche 'estado_local'): set de alumnos corregidos desde la app; Canvas pudo
        autocorregir la entrega, así que solo cuenta lo revisado por un humano."""
        if not sub or sub.get("workflow_state") == "unsubmitted":
            return "sin_entrega"
        if local_sent is not None:
            human = (sub.get("grader_id") or 0) > 0 or sub.get("user_id") in local_sent
            return "revisado" if human and sub.get("workflow_state") == "graded" else "pendiente"
        if sub.get("workflow_state") == "graded":
            return "revisado"
        return "pendiente"

    def _local_sent(self, ev):
        if not overrides.load(ev.id).get("estado_local"):
            return None
        return {u for u, g in store.graded_by_app(ev.id).items() if not g["dry_run"]}

    # ---------- vistas ----------
    def roster_view(self, ev: Evaluation, group):
        entries = roster.load_group(self.students(), group)
        self.ensure_subs(ev, [e.user_id for e in entries])
        sent = store.graded_by_app(ev.id)
        local = self._local_sent(ev)
        out = []
        for e in entries:
            sub = ev.subs.get(e.user_id) if e.user_id else None
            out.append({
                "name": e.name, "user_id": e.user_id, "section": e.section, "day": e.day, "group": e.group, "match": e.match,
                "warnings": e.warnings, "status": self.status(sub, local) if e.user_id else "no_encontrado",
                "score": sub.get("score") if sub else None,
                "app": sent.get(e.user_id),
            })
        return out

    def student_view(self, ev: Evaluation, user_id):
        self.ensure_subs(ev, [user_id])
        sub = ev.subs.get(user_id) or {}
        data = self.sub_data(ev, user_id)
        return {
            "user_id": user_id, "status": self.status(sub, self._local_sent(ev)), "score": sub.get("score"),
            "points_possible": ev.assignment.get("points_possible"),
            "submitted_at": sub.get("submitted_at"), "late": sub.get("late"),
            "comments": [{"author": c.get("author_name"), "text": c.get("comment"), "at": c.get("created_at")}
                         for c in sub.get("submission_comments") or []],
            "context": ev.atype.context_text(ev.questions, data),
            "files": [p.name for p in self.data_files(ev, user_id)] if data else [],
            "base_points": ev.atype.base_points(ev.questions, data),
            "code": self.code_of(ev, user_id),
            "code_source": (self.items_for(ev, user_id) or [None])[0].code_source
            if self.items_for(ev, user_id) else "canvas",
            "items": [i.to_dict() for i in self.items_for(ev, user_id)],
            "speedgrader": f"{config.CANVAS_URL}/courses/{config.COURSE_ID}/gradebook/speed_grader"
                           f"?assignment_id={ev.id}&student_id={user_id}",
        }

    def eval_info(self, ev: Evaluation):
        rid = ev.id
        return {
            "id": rid, "name": ev.assignment["name"], "type": ev.atype.key,
            "points_possible": ev.assignment.get("points_possible"),
            "rubric": [{"score": l.score, "description": l.description, "note": l.note}
                       for l in ev.atype.rubric.levels],
            "rubric_note": ev.atype.rubric.general_note,
            "pauta_extra": overrides.load(rid).get("pauta_extra", ""),
            "files": [p.name for p in resources.data_files(rid)],
            "solution": resources.read_text(rid, resources.SOLUTION),
            "notes": resources.read_text(rid, resources.NOTES),
            "ai": f"{config.AI_PROVIDER} · {config.GROQ_MODEL}",
        }

    # ---------- R ----------
    def run_r(self, ev, user_id, use_cache=True):
        """Ejecuta el código completo del alumno con la BD de su contexto."""
        return r_runner.run(self.code_of(ev, user_id), self.data_files(ev, user_id), use_cache).to_dict()

    def run_solution(self, ev, use_cache=True):
        sol = resources.read_text(ev.id, resources.SOLUTION)
        return r_runner.run(sol, resources.data_files(ev.id), use_cache).to_dict() if sol.strip() else None

    # ---------- IA ----------
    def suggest(self, ev, user_id, use_cache=True):
        items = self.items_for(ev, user_id)
        if not items:
            raise ValueError("El alumno no tiene preguntas respondidas")
        code = self.code_of(ev, user_id)
        r = self.run_r(ev, user_id) if code.strip() else None
        sol = self.run_solution(ev)
        ejec = None
        if r:
            ejec = ("Terminó sin errores." if r["ok"] else "Terminó con ERROR." if not r["timed_out"]
                    else "Excedió el tiempo límite.")
            if r["changes"]:
                ejec += "\nAjustes automáticos hechos por el sistema (no son del alumno): " + "; ".join(r["changes"])
            if r.get("plots"):
                ejec += f"\nSe generaron {len(r['plots'])} gráfico(s) (no puedes verlos)."
            ejec += f"\nSalida:\n{r['stdout'][-6000:]}\nErrores:\n{r['stderr'][-1500:]}"
        case = CaseInput(
            tipo=ev.atype.key,
            contexto=ev.atype.context_text(ev.questions, self.sub_data(ev, user_id)),
            pauta=self.pauta_text(ev), codigo=code, ejecucion_r=ejec,
            bd_muestra="\n\n".join(resources.schema_preview(p) for p in self.data_files(ev, user_id)),
            items=[ItemCase(
                n=i.n, pregunta=i.answer_q.text, respuesta_correcta=i.answer_q.correct,
                respuesta_alumno=i.answer_text, canvas_marca_correcta=i.canvas_correct, puntos=i.points,
                opciones=list(i.answer_q.options.values()), fragmento_lineas=i.fragment_lines,
                fragmento_origen=i.fragment_source) for i in items],
            solucion_oficial=resources.read_text(ev.id, resources.SOLUTION),
            solucion_output=(sol or {}).get("stdout", "")[-2000:],
            notas_ayudante=resources.read_text(ev.id, resources.NOTES),
        )
        return self.advisor.suggest(case, use_cache).model_dump()

    # ---------- escritura ----------
    def grade(self, ev, user_id, fractions: list[float], comment: str, dry_run: bool = True):
        items = self.items_for(ev, user_id)
        if len(fractions) != len(items):
            raise ValueError("Cantidad de puntajes no coincide con las preguntas")
        qs = ev.qsubs.get(user_id)
        if not qs:
            raise ValueError("El alumno no tiene quiz submission")
        scores = {}
        for item, f in zip(items, fractions):
            if not 0 <= f <= 1:
                raise ValueError("El puntaje debe estar entre 0 y 1")
            scores.update(ev.atype.score_targets(item, f))
        result = {"scores": self.client.set_question_scores(ev.quiz_id, qs["id"], qs["attempt"], scores, dry_run)}
        if comment.strip():
            result["comment"] = self.client.add_comment(ev.id, user_id, comment.strip(), dry_run)
        store.log_grade(ev.id, user_id, scores, comment, dry_run, result)
        state = None
        if not dry_run:  # releer para confirmar lo que quedó en Canvas
            self.ensure_subs(ev, [user_id], refresh=True)
            state = (ev.subs.get(user_id) or {}).get("workflow_state")
            if state != "graded":
                raise ValueError(f"Canvas guardó los puntajes pero la entrega quedó en estado '{state}' "
                                 "(no 'graded'). Revísala en SpeedGrader.")
        return {"dry_run": dry_run, "scores": scores, "state": state,
                "new_score": (ev.subs.get(user_id) or {}).get("score")}
