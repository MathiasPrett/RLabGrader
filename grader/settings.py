"""Configuración de claves desde la app (⚙): lee, prueba y guarda en .env.

Precauciones:
- Nunca se devuelve una clave al navegador: solo si está configurada y sus últimos 4 caracteres.
- Cada valor se valida (sin saltos de línea ni espacios), así no se pueden colar otras variables.
- Se reescribe solo la línea de cada variable; el resto del .env (comentarios, otras variables) se conserva.
- El archivo queda legible solo por el usuario (permisos 600 en Linux/macOS).
"""
import os
import re
import tempfile

import requests

from . import config

PLACEHOLDER = "pega_aqui"

FIELDS = {
    "CANVAS_TOKEN": {"secret": True, "re": r"[A-Za-z0-9~_.\-]{20,300}",
                     "msg": "El token de Canvas debe ser una sola línea de letras y números (normalmente con un ~)."},
    "GROQ_API_KEY": {"secret": True, "re": r"[A-Za-z0-9_\-]{20,300}",
                     "msg": "La API key de Groq debe ser una sola línea (empieza con gsk_)."},
    "COURSE_ID": {"secret": False, "re": r"\d{1,12}",
                  "msg": "El número del curso son solo dígitos (lo ves en la URL: .../courses/123456)."},
    "CANVAS_URL": {"secret": False, "re": r"https://[A-Za-z0-9.\-]+(:\d{1,5})?",
                   "msg": "La dirección de Canvas debe ser del tipo https://cursos.canvas.uc.cl (sin / al final)."},
}


def _current(key) -> str:
    return {"CANVAS_TOKEN": config.CANVAS_TOKEN, "GROQ_API_KEY": config.GROQ_API_KEY,
            "COURSE_ID": str(config.COURSE_ID or ""), "CANVAS_URL": config.CANVAS_URL}[key]


def _is_set(key, value) -> bool:
    if not value or value.startswith(PLACEHOLDER):
        return False
    return not (key == "COURSE_ID" and value in ("0", "123456"))


def status() -> dict:
    out = {}
    for key, f in FIELDS.items():
        v = _current(key)
        ok = _is_set(key, v)
        out[key] = {"set": ok, "hint": (v[-4:] if f["secret"] else v) if ok else ""}
    out["CANVAS_URL"]["hint"] = config.CANVAS_URL  # siempre visible (tiene valor por defecto)
    out["env_exists"] = config.ENV_FILE.exists()
    out["ready"] = out["CANVAS_TOKEN"]["set"] and out["COURSE_ID"]["set"]
    return out


def clean(values: dict) -> dict:
    """Solo los campos conocidos y no vacíos, validados."""
    out = {}
    for key, raw in (values or {}).items():
        if key not in FIELDS or raw is None:
            continue
        v = str(raw).strip().rstrip("/") if key == "CANVAS_URL" else str(raw).strip()
        if not v:
            continue
        if not re.fullmatch(FIELDS[key]["re"], v):
            raise ValueError(FIELDS[key]["msg"])
        out[key] = v
    return out


def _merged(values: dict) -> dict:
    return {k: values.get(k) or _current(k) for k in FIELDS}


def test(values: dict) -> dict:
    """Prueba las claves (las nuevas o, si no vienen, las guardadas) sin guardar nada."""
    v = _merged(clean(values))
    res = {}
    if _is_set("CANVAS_TOKEN", v["CANVAS_TOKEN"]):
        h = {"Authorization": f"Bearer {v['CANVAS_TOKEN']}"}
        try:
            r = requests.get(f"{v['CANVAS_URL']}/api/v1/users/self", headers=h, timeout=15)
            if r.ok:
                msg = f"Conectado como {r.json().get('name', '?')}"
                if _is_set("COURSE_ID", v["COURSE_ID"]):
                    c = requests.get(f"{v['CANVAS_URL']}/api/v1/courses/{v['COURSE_ID']}", headers=h, timeout=15)
                    msg += f" · curso: {c.json().get('name', '?')}" if c.ok else " · ✗ no tienes acceso a ese curso"
                    res["canvas"] = {"ok": c.ok, "msg": msg}
                else:
                    res["canvas"] = {"ok": True, "msg": msg + " · falta el número del curso"}
            else:
                res["canvas"] = {"ok": False, "msg": "Canvas rechazó el token (¿expiró o está mal copiado?)"
                                 if r.status_code == 401 else f"Canvas respondió {r.status_code}"}
        except requests.RequestException:
            res["canvas"] = {"ok": False, "msg": "No se pudo conectar con esa dirección de Canvas"}
    else:
        res["canvas"] = {"ok": False, "msg": "Falta el token de Canvas"}
    if _is_set("GROQ_API_KEY", v["GROQ_API_KEY"]):
        try:
            r = requests.get("https://api.groq.com/openai/v1/models",
                             headers={"Authorization": f"Bearer {v['GROQ_API_KEY']}"}, timeout=15)
            res["groq"] = {"ok": r.ok, "msg": "La API key de Groq funciona" if r.ok else
                           "Groq rechazó la API key" if r.status_code == 401 else f"Groq respondió {r.status_code}"}
        except requests.RequestException:
            res["groq"] = {"ok": False, "msg": "No se pudo conectar con Groq"}
    else:
        res["groq"] = {"ok": False, "msg": "Sin API key de Groq: la sugerencia IA no funcionará (es opcional)"}
    return res


def _write_env(updates: dict):
    path = config.ENV_FILE
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        example = config.ROOT / ".env.example"
        lines = example.read_text(encoding="utf-8").splitlines() if example.exists() else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            done.add(m.group(1))
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    # escritura atómica: archivo temporal en la misma carpeta y luego reemplazo
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip("\n") + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save(values: dict) -> dict:
    updates = clean(values)
    if not updates:
        raise ValueError("No hay cambios que guardar")
    _write_env(updates)
    for k, v in updates.items():
        os.environ[k] = v
    config.reload()
    return status()
