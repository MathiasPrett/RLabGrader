"""Ejecuta código R de alumnos en una carpeta temporal, con timeout y límite de memoria."""
import base64
import hashlib
import re
import os
import sys
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config, store
from .assessments import segment

MAX_OUT = 8000
RUNNER_VERSION = 5  # subir al cambiar prepare() o runner.R: invalida la caché
MAX_PLOTS = 12
MEM_BYTES = 2 * 1024**3

# Literales de texto que parecen rutas a archivos de datos
_PATH_RE = re.compile(r"""(["'])([^"'\n]*?([^/\\"'\n]+\.(?:csv|txt|tsv|xlsx|xls|dat)))\1""", re.I)


@dataclass
class RResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool
    code_run: str
    changes: list[str]
    plots: list[str] = None  # PNG en base64 (data URI)

    def to_dict(self):
        return asdict(self)


_CONSOLE_CMD = re.compile(r"^\s*[>+] ?")
_CONSOLE_NOISE = re.compile(r"^\s*(\[\d+\]|R version|Copyright|Platform:|Type '|You are welcome|"
                            r"Natural language|R is free|R is a collaborative|'citation\(\)'|'help|'q\(\)')")
_IDENT = r"[A-Za-z][A-Za-z0-9._]*"
_KNOWN = {"T", "F", "TRUE", "FALSE", "NULL", "NA", "NaN", "Inf", "c", "data", "df", "letters", "LETTERS",
          "pi", "iris", "mtcars", "month.name"}
_READERS = {".csv": "read.csv", ".xlsx": "readxl::read_excel", ".xls": "readxl::read_excel"}


def _reader(name):
    ext = Path(name).suffix.lower()
    r = _READERS.get(ext, "read.table")
    return f'{r}("{name}"' + (", header = TRUE)" if r == "read.table" else ")")


def _strip_console(code, changes):
    """Si el alumno pegó la consola (líneas '> ...'), quedarse solo con los comandos."""
    lines = code.splitlines()
    cmd = [l for l in lines if l.lstrip().startswith(">")]
    nonempty = [l for l in lines if l.strip()]
    outputs = [l for l in lines if re.match(r"^\s*\[\d+\]", l)]
    if len(cmd) < 3 or not (outputs or len(cmd) >= 0.5 * len(nonempty)):
        return code
    keep = []
    for l in lines:
        st = l.lstrip()
        if st.startswith((">", "+")):
            keep.append(_CONSOLE_CMD.sub("", l, count=1))
        elif st.startswith("#") or segment.header_number(l):
            keep.append(l)
    changes.append(f"copia de consola: se extrajeron {len(cmd)} comandos y se descartó la salida")
    return "\n".join(keep)


def _strip_prompts(code, changes):
    """Líneas sueltas copiadas de la consola ('> x', '>' solo) dentro de código normal."""
    out, n = [], 0
    for l in code.splitlines():
        if re.match(r"^\s*>\s*$", l):
            n += 1
            continue
        if re.match(r"^\s*> ", l):
            n += 1
            l = re.sub(r"^\s*> ", "", l, count=1)
        out.append(l)
    if n:
        changes.append(f"quitado el prompt '>' de {n} línea(s)")
    return "\n".join(out)


def _comment_headers(code, changes):
    """Títulos sin '#' ('Pregunta 1:', '1.- código') rompen R: se comentan."""
    out, n = [], 0
    for l in code.splitlines():
        h = None if l.lstrip().startswith("#") else segment.header_number(l)
        if h and not h[1]:
            n += 1
            out.append(f"# [título] {l.strip() if not h[2] else l.strip()[:len(l.strip()) - len(h[2])].strip()}")
            if h[2]:
                out.append(h[2])
        elif not l.lstrip().startswith("#") and _CONSOLE_NOISE.match(l):
            n += 1
            out.append("# [salida] " + l)
        else:
            out.append(l)
    if n:
        changes.append(f"comentadas {n} línea(s) de títulos o texto sin '#'")
    return "\n".join(out)


def prepare(code: str, data_names: list[str]) -> tuple[str, list[str]]:
    """Adapta el código del alumno para que corra aquí, anotando cada ajuste en `changes`.

    data_names: archivos de datos del contexto del alumno; el primero es el principal.
    """
    changes = []
    lower = {n.lower(): n for n in data_names}
    code = _strip_console(code, changes)
    code = _strip_prompts(code, changes)
    code = _comment_headers(code, changes)

    def fix_path(m):
        q, full, base = m.group(1), m.group(2), m.group(3)
        target = lower.get(base.lower())
        note = ""
        if not target:  # archivo que no existe aquí: el de igual extensión, o el principal
            ext = Path(base).suffix.lower()
            target = next((n for n in data_names if Path(n).suffix.lower() == ext), None)
            note = " (supuesto)"
        if target and full != target:
            changes.append(f"ruta '{full}' → '{target}'{note}")
            return f"{q}{target}{q}"
        return m.group(0)

    code = _PATH_RE.sub(fix_path, code)
    if data_names and re.search(r"file\.choose\(\s*\)", code):
        code = re.sub(r"file\.choose\(\s*\)", "file.choose()", code)
        code = code.replace("file.choose()", f'"{data_names[0]}"')
        changes.append(f"file.choose() → '{data_names[0]}'")

    # Variables de datos usadas sin cargarlas (típico de importar con RStudio y no pegar esa línea)
    def assigned(var):
        return re.search(rf"(?<![\w.$]){re.escape(var)}\s*(<<?-|=(?!=))|->\s*{re.escape(var)}\b"
                         rf"|assign\(\s*[\"']{re.escape(var)}", code)

    preload = []
    by_stem = {Path(n).stem: n for n in data_names}
    for var, name in by_stem.items():  # mismo nombre que el archivo: Taller1, fish...
        if re.fullmatch(_IDENT, var) and re.search(rf"(?<![\w.$]){re.escape(var)}(?![\w.(])", code) \
                and not assigned(var):
            preload.append(f"{var} <- {_reader(name)}")
            changes.append(f"precargado: {preload[-1]}")
    if data_names:  # otros nombres usados como data frame sin definirlos
        used = list(re.findall(rf"(?<![\w.$`])({_IDENT})\s*(?:\$|\[)", code))           # Datos$x, bd[...]
        used += re.findall(rf"(?:<-|=)\s*({_IDENT})\s*(?:#.*)?$", code, re.M)           # datos <- Taller1
        used += re.findall(rf"\b(?:head|View|nrow|summary|str|names|attach)\(\s*({_IDENT})\s*\)", code)
        ticks = re.findall(r"`([^`\n]+)`", code)                                          # `Taller1.(1)`
        for var in dict.fromkeys(used + ticks):
            if var in by_stem or var in _KNOWN or assigned(var) or re.search(
                    rf"\bfunction\s*\(.*\b{re.escape(var)}\b", code):
                continue
            target = f"`{var}`" if var in ticks and not re.fullmatch(_IDENT, var) else var
            if var in ticks and not re.search(rf"`{re.escape(var)}`\s*(?:\$|\[|\)|$|\s)", code, re.M):
                continue
            preload.append(f"{target} <- {_reader(data_names[0])}")
            changes.append(f"precargado (supuesto): {preload[-1]}")

    out = list(preload)
    for line in code.splitlines():
        if re.match(r"\s*(setwd|install\.packages)\s*\(", line):
            changes.append(f"comentado: {line.strip()[:60]}")
            line = "# [desactivado] " + line
        out.append(line)
    return "\n".join(out), changes


RUNNER_R = Path(__file__).with_name("runner.R")
_LIBS = None


def _lib_paths() -> str:
    """Librerías de R del usuario (dplyr, rio...), que no se ven al aislar HOME."""
    global _LIBS
    if _LIBS is None:
        try:
            _LIBS = subprocess.run([_rscript(), "-e", 'cat(.libPaths(), sep=.Platform$path.sep)'], capture_output=True,
                                   text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            _LIBS = ""
    return _LIBS


def _limits():
    import resource  # solo Linux/macOS
    resource.setrlimit(resource.RLIMIT_AS, (MEM_BYTES, MEM_BYTES))


_SECRET = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|PASS|CREDENTIAL|AUTH", re.I)


def _env(home) -> dict:
    """Entorno para el código del alumno: sin ninguna variable que parezca una clave."""
    env = {k: v for k, v in os.environ.items() if not _SECRET.search(k)}
    env.update({"HOME": home, "USERPROFILE": home, "LANG": "C.UTF-8", "R_LIBS": _lib_paths()})
    return env


def _rscript() -> str:
    exe = shutil.which("Rscript")
    if not exe:
        raise RuntimeError("No se encontró Rscript. Instala R (ver README) y reinicia la app.")
    return exe


def _plots(tmp) -> list[str]:
    out = []
    for p in sorted(Path(tmp).glob("plot_*.png"))[:MAX_PLOTS]:
        if p.stat().st_size > 1500:  # descarta páginas en blanco
            out.append("data:image/png;base64," + base64.b64encode(p.read_bytes()).decode())
    return out


def run(code: str, data_files: list[Path], use_cache=True) -> RResult:
    names = [p.name for p in data_files]
    key = f"r{RUNNER_VERSION}:" + hashlib.sha256((code + "|" + ",".join(names)).encode()).hexdigest()
    if use_cache and (hit := store.cache_get(key)):
        return RResult(**hit)
    prepared, changes = prepare(code, names)
    with tempfile.TemporaryDirectory(prefix="rgrade_") as tmp:
        for p in data_files:
            shutil.copy(p, tmp)
        script = Path(tmp) / "alumno.R"
        # Ver resultados intermedios como en la consola de R (echo de cada expresión).
        script.write_text(prepared, encoding="utf-8")
        shutil.copy(RUNNER_R, Path(tmp) / "_run.R")  # ejecuta bloque a bloque y guarda gráficos
        try:
            p = subprocess.run([_rscript(), "--vanilla", "_run.R"], cwd=tmp, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=config.R_TIMEOUT,
                               preexec_fn=None if sys.platform == "win32" else _limits, env=_env(tmp))
            res = RResult(p.returncode == 0, p.stdout[-MAX_OUT:], p.stderr[-MAX_OUT:], p.returncode,
                          False, prepared, changes, _plots(tmp))
        except subprocess.TimeoutExpired as e:
            res = RResult(False, (e.stdout or b"").decode(errors="replace")[-MAX_OUT:] if isinstance(e.stdout, bytes) else (e.stdout or "")[-MAX_OUT:],
                          f"Tiempo límite ({config.R_TIMEOUT}s) excedido", None, True, prepared, changes,
                          _plots(tmp))
    store.cache_set(key, res.to_dict())
    return res
