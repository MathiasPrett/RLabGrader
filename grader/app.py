"""Servidor web local. Uso: uv run uvicorn grader.app:app --port 8000"""
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import resources
from .ai.providers.base import AIProviderError
from .canvas_client import CanvasError
from .service import Service

HERE = Path(__file__).parent
app = FastAPI(title="RLabGrader")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
_svc: Service | None = None


def svc() -> Service:
    global _svc
    if _svc is None:
        _svc = Service()
    return _svc


@app.exception_handler(CanvasError)
@app.exception_handler(AIProviderError)
@app.exception_handler(ValueError)
async def _err(_: Request, exc: Exception):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/")
def index():
    return FileResponse(HERE / "templates" / "index.html")


@app.get("/api/assessments")
def assessments():
    return svc().assessments()


@app.get("/api/groups")
def groups():
    return svc().groups()


@app.get("/api/eval/{aid}")
def load_eval(aid: int, day: str, group: str, type: str | None = None, refresh: bool = False):
    s = svc()
    ev = s.load(aid, type, refresh)
    return {"info": s.eval_info(ev), "students": s.roster_view(ev, day, group)}


@app.get("/api/eval/{aid}/student/{uid}")
def student(aid: int, uid: int):
    s = svc()
    return s.student_view(s.load(aid), uid)


class RunReq(BaseModel):
    fresh: bool = False


@app.post("/api/eval/{aid}/student/{uid}/run_r")
def run_r(aid: int, uid: int, body: RunReq):
    s = svc()
    return s.run_r(s.load(aid), uid, not body.fresh)


@app.post("/api/eval/{aid}/student/{uid}/suggest")
def suggest(aid: int, uid: int, body: RunReq):
    s = svc()
    return s.suggest(s.load(aid), uid, not body.fresh)


class GradeReq(BaseModel):
    fractions: list[float]
    comment: str = ""


@app.post("/api/eval/{aid}/student/{uid}/grade")
def grade(aid: int, uid: int, body: GradeReq):
    s = svc()
    return s.grade(s.load(aid), uid, body.fractions, body.comment)


class TextReq(BaseModel):
    solution: str | None = None
    notes: str | None = None


@app.post("/api/eval/{aid}/resources")
def save_resources(aid: int, body: TextReq):
    if body.solution is not None:
        resources.write_text(aid, resources.SOLUTION, body.solution)
    if body.notes is not None:
        resources.write_text(aid, resources.NOTES, body.notes)
    return {"ok": True}


@app.post("/api/eval/{aid}/files")
async def upload(aid: int, file: UploadFile = File(...)):
    try:
        name = resources.save_upload(aid, file.filename, await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"files": [p.name for p in resources.data_files(aid)], "saved": name}


@app.post("/api/eval/{aid}/run_solution")
def run_solution(aid: int):
    s = svc()
    return s.run_solution(s.load(aid), use_cache=False) or {"error": "No hay solución guardada"}
