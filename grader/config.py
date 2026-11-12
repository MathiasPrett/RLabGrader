"""Configuración leída desde .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CANVAS_URL = os.environ.get("CANVAS_URL", "https://cursos.canvas.uc.cl").rstrip("/")
CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "")
COURSE_ID = int(os.environ.get("COURSE_ID") or 0)  # obligatorio en .env

AI_PROVIDER = os.environ.get("AI_PROVIDER", "groq")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# Con DRY_RUN=1 las escrituras a Canvas solo se registran, no se envían.
DRY_RUN = os.environ.get("DRY_RUN", "1") not in ("0", "false", "False", "")

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
