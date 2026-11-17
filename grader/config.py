"""Configuración leída desde .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DEFAULT_CANVAS_URL = "https://cursos.canvas.uc.cl"
load_dotenv(ENV_FILE)


def _int(v):
    try:
        return int(v or 0)
    except ValueError:
        return 0


def _load_keys():
    """Claves que se pueden cambiar desde la app (⚙). reload() las vuelve a leer del .env."""
    global CANVAS_URL, CANVAS_TOKEN, COURSE_ID, AI_PROVIDER, GROQ_API_KEY, GROQ_MODEL
    CANVAS_URL = (os.environ.get("CANVAS_URL") or DEFAULT_CANVAS_URL).rstrip("/")
    CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "")
    COURSE_ID = _int(os.environ.get("COURSE_ID"))
    AI_PROVIDER = os.environ.get("AI_PROVIDER") or "groq"
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"


def reload():
    load_dotenv(ENV_FILE, override=True)
    _load_keys()


_load_keys()

PORT = int(os.environ.get("PORT") or 8765)

# Planilla de coordinación de ayudantes: el .xlsx dentro de planilla/
# (o la ruta indicada en ROSTER_XLSX, si se define).
ROSTER_DIR = ROOT / "planilla"


def _find_roster() -> Path:
    if os.environ.get("ROSTER_XLSX"):
        return ROOT / os.environ["ROSTER_XLSX"]
    found = sorted(p for p in ROSTER_DIR.glob("*.xlsx") if not p.name.startswith("~$"))
    return found[0] if found else ROSTER_DIR / "planilla.xlsx"


ROSTER_XLSX = _find_roster()
DATA_DIR = ROOT / "data"
EVAL_DIR = DATA_DIR / "evaluaciones"
DB_PATH = DATA_DIR / "grader.db"
R_TIMEOUT = int(os.environ.get("R_TIMEOUT", "20"))
