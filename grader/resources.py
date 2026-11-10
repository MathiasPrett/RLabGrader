"""Recursos por evaluación: bases de datos, solución oficial y notas (data/evaluaciones/<id>/)."""
import re
from pathlib import Path

import openpyxl
import requests

from . import config

DATA_EXT = {".csv", ".txt", ".tsv", ".xlsx", ".xls", ".dat"}
SOLUTION = "solucion.R"
NOTES = "notas.md"


def folder(assignment_id) -> Path:
    p = config.EVAL_DIR / str(assignment_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_files(assignment_id) -> list[Path]:
    return sorted(p for p in folder(assignment_id).iterdir() if p.suffix.lower() in DATA_EXT)


def read_text(assignment_id, name) -> str:
    p = folder(assignment_id) / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write_text(assignment_id, name, text):
    (folder(assignment_id) / name).write_text(text or "", encoding="utf-8")


def save_upload(assignment_id, filename, content: bytes) -> str:
    name = Path(filename).name
    if Path(name).suffix.lower() not in DATA_EXT:
        raise ValueError(f"Extensión no permitida: {name}")
    (folder(assignment_id) / name).write_bytes(content)
    return name


def canvas_file_ids(html_texts) -> set[int]:
    ids = set()
    for h in html_texts:
        ids.update(int(m) for m in re.findall(r"/files/(\d+)", h or ""))
    return ids


def _file_meta(client, fid):
    from . import store
    key = f"file:{fid}"
    meta = store.cache_get(key)
    if meta is None:
        m = client.get(f"{client.c}/files/{fid}")
        meta = {"name": Path(m.get("display_name") or m.get("filename")).name, "url": m.get("url")}
        store.cache_set(key, meta)
    return meta


def linked_names(client, html_texts) -> list[str]:
    """Nombres de los archivos de datos enlazados en estos textos (en orden de aparición)."""
    names = []
    for h in html_texts:
        for fid in dict.fromkeys(int(m) for m in re.findall(r"/files/(\d+)", h or "")):
            n = _file_meta(client, fid)["name"]
            if Path(n).suffix.lower() in DATA_EXT and n not in names:
                names.append(n)
    return names


def files_for(client, assignment_id, context_htmls) -> list[Path]:
    """BD del contexto que vio el alumno; si el contexto no enlaza archivos, todas las de la carpeta.
    Orden: .csv primero (es el que se usa si el alumno hizo file.choose())."""
    names = linked_names(client, context_htmls) if context_htmls else []
    paths = [folder(assignment_id) / n for n in names if (folder(assignment_id) / n).exists()]
    paths = paths or data_files(assignment_id)
    return sorted(paths, key=lambda p: (p.suffix.lower() != ".csv", names.index(p.name) if p.name in names else 99))


def download_linked(client, assignment_id, html_texts) -> list[str]:
    """Descarga a la carpeta los archivos de datos enlazados en el enunciado del quiz."""
    got = []
    for fid in canvas_file_ids(html_texts):
        meta = _file_meta(client, fid)
        name = meta["name"]
        if Path(name).suffix.lower() not in DATA_EXT:
            continue
        dest = folder(assignment_id) / name
        if not dest.exists():
            r = requests.get(meta["url"], timeout=60)
            r.raise_for_status()
            dest.write_bytes(r.content)
        got.append(name)
    return got


def schema_preview(path: Path, n=6) -> str:
    """Primeras filas de la BD (para dar contexto a la IA sin enviarla completa)."""
    if path.suffix.lower() in {".xlsx", ".xls"}:
        try:
            ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
            rows = [", ".join("" if c is None else str(c) for c in r)
                    for r in ws.iter_rows(max_row=n, values_only=True)]
            return f"{path.name} (Excel, {ws.max_row} filas):\n" + "\n".join(rows)
        except Exception as e:  # noqa: BLE001
            return f"{path.name}: no se pudo leer ({e})"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return f"{path.name} ({len(lines)} líneas):\n" + "\n".join(lines[:n])
