"""Lógica de la app: carga una evaluación, arma la vista por alumno, ejecuta R/IA y envía notas."""
import threading
from dataclasses import dataclass, field, replace

from . import config, key_check, overrides, r_runner, resources, roster, store
from .ai import AIAdvisor, CaseInput, ItemCase
from .ai.registry import model_label
from .assessments import AssessmentType, Item, Question, detect_type, get_type
from .assessments.segment import segment
from .canvas_client import CanvasClient

BASE_POINT = 1.0  # escala chilena 1 a 7: el punto base es el 1 (talleres de 6 puntos + 1 base)


@dataclass
class Evaluation:
    assignment: dict
    quiz_id: int
    questions: list[Question]
    atype: AssessmentType
    subs: dict[int, dict]            # user_id -> submission (assignment API)
    qsubs: dict[int, dict]           # user_id -> quiz submission
    items: dict[int, list[Item]] = field(default_factory=dict)
    key_alerts: dict[int, dict] = field(default_factory=dict)  # claves de Canvas sospechosas
    stats: list[dict] | None = None  # por pregunta: respondidas / correctas (None = calculando)

    @property
    def id(self):
        return self.assignment["id"]


def compact_output(stdout: str, per_cmd: int = 6, max_chars: int = 3500) -> str:
    """Salida de R para la IA: cada comando con sus primeras líneas de resultado (no tablas enteras)."""
    out, shown, extra = [], 0, 0
    for line in stdout.splitlines():
        if line.startswith(("> ", "+ ", "Error")):
            if extra:
                out.append(f"   … ({extra} línea(s) más)")
            out.append(line[:200])
            shown = extra = 0
        elif shown < per_cmd:
            out.append(line[:200])
            shown += 1
        else:
            extra += 1
    if extra:
        out.append(f"   … ({extra} línea(s) más)")
    text = "\n".join(out)
    if len(text) > max_chars:  # aún muy larga: el comienzo y el final
        text = text[:max_chars // 2] + "\n   … (salida recortada) …\n" + text[-max_chars // 2:]
    return text


class Service:
    def __init__(self):
        self.client = CanvasClient()
        self.advisor = AIAdvisor()
        self._students = None
        self._evals: dict[int, Evaluation] = {}
        self._lock = threading.Lock()
        self._jobs: dict[int, dict] = {}  # sugerencia IA en lote, por evaluación

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
            if a.get("published") is False:  # sin publicar: no tiene entregas y Canvas no deja leerlas
                continue
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
            # en segundo plano: revisar si alguna clave de Canvas parece estar mal (no bloquea la carga)
            threading.Thread(target=self._scan_keys, args=(ev,), daemon=True).start()
            return ev

    def _scan_keys(self, ev: Evaluation):
        try:
            ids = [e.user_id for e in roster.match(roster.read_excel(), self.students()) if e.user_id]
            self.ensure_subs(ev, ids)
            datas = [self.sub_data(ev, u) for u in ids]
            ev.key_alerts = key_check.suspects(ev.questions, datas)
            ev.stats = key_check.question_stats(ev.questions, datas)
        except Exception:  # noqa: BLE001 — es solo un aviso; nunca debe romper la app
            ev.stats = []

    def stats_view(self, ev: Evaluation):
        if ev.stats is None:
            return {"ready": False}
        alerts = []
        for qid, a in ev.key_alerts.items():
            q = next((x for x in ev.questions if x.id == qid), None)
            alerts.append({"qid": qid, "text": key_check.short_text(q) if q else "",
                           "message": key_check.message(a), **a})
        return {"ready": True, "alerts": alerts, "questions": [
            dict(s, alert=s["qid"] in ev.key_alerts) for s in ev.stats]}

    # ---------- punto base ----------
    @staticmethod
    def base_missing(ev: Evaluation, data) -> bool:
        """True si la evaluación tiene "punto base" y el alumno no lo marcó (o no le dio puntos)."""
        if not data:
            return False
        base = [q for q in ev.questions if q.is_base]
        if not base:
            return False
        got = {int(d["question_id"]): float(d.get("points") or 0) for d in data}
        return all(got.get(q.id, 0) <= 0 for q in base)

    @staticmethod
    def base_value(ev: Evaluation) -> float:
        """Cuánto vale el punto base: el puntaje de su pregunta o, si quedó con 0 puntos en Canvas
        (pasó en algunas versiones del Taller 2), BASE_POINT (la nota mínima de la escala 1 a 7)."""
        return max([q.points for q in ev.questions if q.is_base] + [0]) or BASE_POINT

    def base_code_q(self, ev: Evaluation, user_id):
        """La pregunta de código donde se puede asignar el punto base que el alumno no marcó (o None)."""
        items = self.items_for(ev, user_id)
        it = items[0] if items else None
        return it.code_q if it and it.code_q and it.code_in_submission else None

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

    def edited_items(self, ev, user_id, code: str | None) -> list[Item]:
        """Ítems del alumno usando el código editado por el ayudante (solo local).
        En talleres se vuelven a ubicar los fragmentos por pregunta sobre el código editado."""
        items = self.items_for(ev, user_id)
        if code is None or not items:
            return items
        if len(code) > 200_000:
            raise ValueError("El código editado es demasiado largo")
        out = [replace(it, code_text=code, fragment_lines=[], fragment_source="todo") for it in items]
        if ev.atype.segment_code:
            found = segment(code, len(out))
            for it in out:
                it.fragment_lines, it.fragment_source = (found[it.n], "comentarios") if it.n in found \
                    else ([], "no detectado")
        return out

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
                "base_missing": self.base_missing(ev, self.sub_data(ev, e.user_id)) if e.user_id else False,
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
            "base_missing": self.base_missing(ev, data),
            "base_value": self.base_value(ev),
            "base_can_add": bool(self.base_missing(ev, data) and self.base_code_q(ev, user_id)),
            "code": self.code_of(ev, user_id),
            "code_source": (self.items_for(ev, user_id) or [None])[0].code_source
            if self.items_for(ev, user_id) else "canvas",
            "items": [dict(i.to_dict(), key_alert=(key_check.message(ev.key_alerts[i.answer_q.id])
                                                    if i.answer_q.id in ev.key_alerts else None))
                      for i in self.items_for(ev, user_id)],
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
            "ai": f"{config.AI_PROVIDER} · {model_label()}",
        }

    # ---------- R ----------
    def run_r(self, ev, user_id, use_cache=True, code: str | None = None):
        """Ejecuta el código completo del alumno con la BD de su contexto.
        code: versión editada por el ayudante (solo se ejecuta; no se guarda ni se envía)."""
        items = self.edited_items(ev, user_id, code)
        src = items[0].code_text if items else ""
        res = r_runner.run(src, self.data_files(ev, user_id), use_cache).to_dict()
        res["edited"] = code is not None
        if code is not None:  # fragmentos por pregunta del código editado (talleres)
            res["fragments"] = {it.n: {"lines": it.fragment_lines, "source": it.fragment_source} for it in items}
        return res

    def run_solution(self, ev, use_cache=True):
        sol = resources.read_text(ev.id, resources.SOLUTION)
        return r_runner.run(sol, resources.data_files(ev.id), use_cache).to_dict() if sol.strip() else None

    # ---------- IA ----------
    def suggest(self, ev, user_id, use_cache=True, code: str | None = None):
        """code: si el ayudante editó el código, la IA evalúa esa versión."""
        items = self.edited_items(ev, user_id, code)
        if not items:
            raise ValueError("El alumno no tiene preguntas respondidas")
        code = items[0].code_text
        r = self.run_r(ev, user_id, code=code if code != self.code_of(ev, user_id) else None) if code.strip() else None
        sol = self.run_solution(ev)
        ejec = None
        if r:
            ejec = ("Terminó sin errores." if r["ok"] else "Terminó con ERROR." if not r["timed_out"]
                    else "Excedió el tiempo límite.")
            if r.get("system_error"):
                ejec += ("\nATENCIÓN: la ejecución se interrumpió por una FALLA DEL COMPUTADOR, no del alumno ("
                         + r["system_error"] + "). Lo que no alcanzó a ejecutarse NO cuenta en su contra: "
                         "juzga esas líneas por su lógica y por la respuesta ingresada.")
            if r["changes"]:
                ejec += "\nAjustes automáticos hechos por el sistema (no son del alumno): " + "; ".join(r["changes"])
            if r.get("plots"):
                ejec += f"\nSe generaron {len(r['plots'])} gráfico(s) (no puedes verlos)."
            ejec += f"\nSalida (resumida):\n{compact_output(r['stdout'])}"
            errs = [l for l in r["stderr"].splitlines() if l.startswith(("Error", "Warning"))]
            if errs:
                ejec += "\nErrores:\n" + "\n".join(errs[:15])
        case = CaseInput(
            tipo=ev.atype.key,
            contexto=ev.atype.context_text(ev.questions, self.sub_data(ev, user_id)),
            pauta=self.pauta_text(ev), codigo=code, ejecucion_r=ejec,
            # una sola muestra: en talleres la misma base viene en .csv, .txt y .xlsx
            bd_muestra=next((resources.schema_preview(p, n=5) for p in self.data_files(ev, user_id)), ""),
            items=[ItemCase(
                n=i.n, pregunta=i.answer_q.text, respuesta_correcta=i.answer_q.correct,
                respuesta_alumno=i.answer_text, canvas_marca_correcta=i.canvas_correct, puntos=i.points,
                opciones=list(i.answer_q.options.values()), fragmento_lineas=i.fragment_lines,
                fragmento_origen=i.fragment_source,
                aviso_clave=key_check.message(ev.key_alerts[i.answer_q.id]) if i.answer_q.id in ev.key_alerts
                else "") for i in items],
            solucion_oficial=resources.read_text(ev.id, resources.SOLUTION),
            solucion_output=(sol or {}).get("stdout", "")[-2000:],
            notas_ayudante=resources.read_text(ev.id, resources.NOTES),
        )
        out = self.advisor.suggest(case, use_cache).model_dump()
        prov = self.advisor.provider
        if getattr(prov, "notice", ""):  # p. ej. el modelo de Gemini estaba saturado y respondió otro
            out["aviso"] = prov.notice
            prov.notice = ""
        return out

    # ---------- IA en lote ----------
    def start_batch(self, ev: Evaluation, group: str, only_pending: bool = True) -> dict:
        """Pide en segundo plano la sugerencia IA de todos los alumnos (pendientes) del grupo.
        Quedan en caché: al abrir al alumno, la sugerencia aparece al instante."""
        job = self._jobs.get(ev.id)
        if job and job["running"]:
            return self.batch_status(ev.id)
        rows = self.roster_view(ev, group)
        uids = [r["user_id"] for r in rows if r["user_id"] and r["status"] != "sin_entrega"
                and (r["status"] == "pendiente" or not only_pending)
                and self.items_for(ev, r["user_id"])]
        job = {"running": True, "cancel": False, "total": len(uids), "done": 0, "errors": [],
               "ready": [], "current": None, "group": group}
        self._jobs[ev.id] = job

        def work():
            for uid in uids:
                if job["cancel"]:
                    break
                job["current"] = uid
                try:
                    self.suggest(ev, uid)
                    job["ready"].append(uid)
                except Exception as e:  # noqa: BLE001 — se informa y se sigue con el siguiente
                    job["errors"].append({"user_id": uid, "error": str(e)[:200]})
                    if "límite de uso" in str(e) or "saturados" in str(e):
                        break  # sin cupo de IA: no tiene sentido seguir
                job["done"] += 1
            job["running"], job["current"] = False, None

        threading.Thread(target=work, daemon=True).start()
        return self.batch_status(ev.id)

    def batch_status(self, aid) -> dict:
        job = self._jobs.get(aid)
        if not job:
            return {"running": False, "total": 0, "done": 0, "ready": [], "errors": []}
        return {k: v for k, v in job.items() if k != "cancel"}

    def cancel_batch(self, aid):
        if aid in self._jobs:
            self._jobs[aid]["cancel"] = True
        return self.batch_status(aid)

    # ---------- escritura ----------
    def grade(self, ev, user_id, fractions: list[float], comment: str, dry_run: bool = True,
              item_comments: list[str] | None = None, add_base: bool = False):
        """item_comments: un comentario por pregunta (talleres); va en la pregunta de respuesta en Canvas.
        add_base: si el alumno no marcó el punto base, se le asigna en la pregunta de código."""
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
        if add_base:
            code_q = self.base_code_q(ev, user_id)
            if not self.base_missing(ev, self.sub_data(ev, user_id)):
                raise ValueError("El alumno ya tiene el punto base: no se agrega de nuevo")
            if not code_q:
                raise ValueError("La entrega no tiene pregunta de código donde asignar el punto base")
            scores[code_q.id] = round(self.base_value(ev), 4)
        q_comments = {it.answer_q.id: c.strip() for it, c in zip(items, item_comments or []) if c and c.strip()}
        result = {"scores": self.client.set_question_scores(ev.quiz_id, qs["id"], qs["attempt"], scores, dry_run,
                                                            q_comments)}
        if comment.strip():
            result["comment"] = self.client.add_comment(ev.id, user_id, comment.strip(), dry_run)
        full_comment = "\n".join([comment.strip()] + [f"[P{it.n}] {c}" for it in items
                                                        if (c := q_comments.get(it.answer_q.id))]).strip()
        store.log_grade(ev.id, user_id, scores, full_comment, dry_run, result)
        state = None
        if not dry_run:  # releer para confirmar lo que quedó en Canvas
            self.ensure_subs(ev, [user_id], refresh=True)
            state = (ev.subs.get(user_id) or {}).get("workflow_state")
            if state != "graded":
                raise ValueError(f"Canvas guardó los puntajes pero la entrega quedó en estado '{state}' "
                                 "(no 'graded'). Revísala en SpeedGrader.")
        return {"dry_run": dry_run, "scores": scores, "state": state,
                "new_score": (ev.subs.get(user_id) or {}).get("score")}
