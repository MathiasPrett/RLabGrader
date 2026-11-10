"""Cliente mínimo de la API de Canvas (Quizzes clásicos)."""
import logging

import requests

from . import config

log = logging.getLogger(__name__)


class CanvasError(RuntimeError):
    pass


class CanvasClient:
    def __init__(self, base=config.CANVAS_URL, token=config.CANVAS_TOKEN, course_id=config.COURSE_ID):
        if not token:
            raise CanvasError("Falta CANVAS_TOKEN en .env (ver README)")
        if not course_id:
            raise CanvasError("Falta COURSE_ID en .env (ver README)")
        self.base = base
        self.course_id = course_id
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    # ---------- bajo nivel ----------
    def _url(self, path):
        return path if path.startswith("http") else f"{self.base}/api/v1{path}"

    def _check(self, r):
        if not r.ok:
            raise CanvasError(f"{r.request.method} {r.url} -> {r.status_code}: {r.text[:300]}")
        return r

    def get(self, path, params=None):
        return self._check(self.s.get(self._url(path), params=params, timeout=30)).json()

    def get_all(self, path, params=None):
        """GET siguiendo la paginación (header Link rel=next)."""
        url, params = self._url(path), {**(params or {}), "per_page": 100}
        items = []
        while url:
            r = self._check(self.s.get(url, params=params, timeout=30))
            data = r.json()
            items.extend(data if isinstance(data, list) else data.get("quiz_submissions", []))
            url, params = r.links.get("next", {}).get("url"), None
        return items

    def put(self, path, json_body):
        if config.DRY_RUN:
            log.warning("DRY_RUN PUT %s %s", path, json_body)
            return {"dry_run": True, "path": path, "body": json_body}
        return self._check(self.s.put(self._url(path), json=json_body, timeout=30)).json()

    # ---------- lectura ----------
    @property
    def c(self):
        return f"/courses/{self.course_id}"

    def quiz_assignments(self, search=None):
        params = {"search_term": search} if search else {}
        return [a for a in self.get_all(f"{self.c}/assignments", params) if a.get("quiz_id")]

    def assignment(self, assignment_id):
        return self.get(f"{self.c}/assignments/{assignment_id}")

    def quiz(self, quiz_id):
        return self.get(f"{self.c}/quizzes/{quiz_id}")

    def quiz_questions(self, quiz_id):
        return self.get_all(f"{self.c}/quizzes/{quiz_id}/questions")

    def quiz_group_points(self, quiz_id, group_ids):
        """{group_id: puntaje por pregunta del grupo}."""
        out = {}
        for g in {g for g in group_ids if g}:
            out[g] = self.get(f"{self.c}/quizzes/{quiz_id}/groups/{g}").get("question_points")
        return out

    def submissions(self, assignment_id):
        return self.get_all(
            f"{self.c}/assignments/{assignment_id}/submissions",
            {"include[]": ["submission_history", "user", "submission_comments"]},
        )

    def submission(self, assignment_id, user_id):
        return self.get(
            f"{self.c}/assignments/{assignment_id}/submissions/{user_id}",
            {"include[]": ["submission_history", "user", "submission_comments"]},
        )

    def submissions_for(self, assignment_id, user_ids):
        """Entregas solo de ciertos alumnos (mucho más rápido que todo el curso)."""
        out, ids = [], list(user_ids)
        for i in range(0, len(ids), 50):
            out += self.get_all(f"{self.c}/students/submissions", {
                "student_ids[]": ids[i:i + 50], "assignment_ids[]": assignment_id,
                "include[]": ["submission_history", "submission_comments"]})
        return out

    def quiz_submissions(self, quiz_id):
        return self.get_all(f"{self.c}/quizzes/{quiz_id}/submissions")

    def students(self):
        return self.get_all(
            f"{self.c}/users", {"enrollment_type[]": "student", "include[]": ["enrollments"]}
        )

    # ---------- escritura ----------
    def set_question_scores(self, quiz_id, quiz_submission_id, attempt, scores):
        """scores: {question_id: puntaje}. Solo cambia esas preguntas."""
        body = {"quiz_submissions": [{
            "attempt": attempt,
            "questions": {str(q): {"score": s} for q, s in scores.items()},
        }]}
        return self.put(f"{self.c}/quizzes/{quiz_id}/submissions/{quiz_submission_id}", body)

    def add_comment(self, assignment_id, user_id, text):
        body = {"comment": {"text_comment": text}}
        return self.put(f"{self.c}/assignments/{assignment_id}/submissions/{user_id}", body)
