"""Parches locales por evaluación (data/overrides/<assignment_id>.json, ignorado por git).

Sirven para casos excepcionales sin tocar Canvas, por ejemplo un bono al que le faltó la
pregunta de código y cuyo código se recibió en otro buzón. Campos posibles:

  "codigo_externo": carpeta con la descarga de entregas del buzón (archivos nombre_IDCANVAS_...)
  "pauta_extra":    texto que se agrega a la pauta (lo ven la IA y el ayudante)
  "estado_local":   true → "ya revisado" solo si se corrigió desde la app o por un humano en Canvas
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from . import config
from .text import html_to_text

DIR = config.DATA_DIR / "overrides"
_ID = re.compile(r"_(?:LATE_)?(\d+)_")
_CODE_EXT = {".r", ".txt", ".html", ".htm"}


def load(assignment_id) -> dict:
    p = DIR / f"{assignment_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@lru_cache(maxsize=8)
def _mailbox(folder: str, mtime: float) -> dict[int, str]:
    """{user_id: código} desde una descarga de entregas de Canvas."""
    out: dict[int, list[str]] = {}
    for f in sorted(Path(folder).rglob("*")):
        m = _ID.search(f.name)
        if not f.is_file() or not m or f.suffix.lower() not in _CODE_EXT:
            continue
        raw = f.read_text(encoding="utf-8", errors="replace")
        if f.suffix.lower() in (".html", ".htm"):
            body = re.search(r"<div[^>]*>(.*)</div>", raw, re.S)  # el texto entregado
            raw = html_to_text(body.group(1) if body else raw)
        out.setdefault(int(m.group(1)), []).append(raw.strip())
    return {u: "\n\n".join(x for x in v if x) for u, v in out.items()}


def external_code(ov: dict, user_id) -> str:
    folder = ov.get("codigo_externo")
    if not folder:
        return ""
    p = Path(folder) if Path(folder).is_absolute() else config.ROOT / folder
    if not p.exists():
        return ""
    return _mailbox(str(p), p.stat().st_mtime).get(int(user_id), "")
