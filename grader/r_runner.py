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

from . import config, r_packages, store
from .assessments import segment

MAX_OUT = 8000
RUNNER_VERSION = 6  # subir al cambiar prepare() o runner.R: invalida la caché
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
_NOT_DATA = {"x", "y", "n", "i", "j", "k", "p", "q"}  # nombres típicos de vectores o índices
_READERS = {".csv": "read.csv", ".xlsx": "readxl::read_excel", ".xls": "readxl::read_excel"}


_DATA_FUNCS = ("with|within|subset|attach|nrow|ncol|dim|head|tail|summary|str|names|colnames|View|"
               "filter|select|mutate|arrange|group_by|summarise|summarize|count|distinct|glimpse|"
               "transform|split|merge|droplevels|na\\.omit|complete\\.cases|sapply|lapply|apply|"
               "aggregate|tapply|by|boxplot|hist|plot")


def data_like_uses(code) -> list[str]:
    """Nombres usados como data frame: X$col, X[...], f(X, ...), X %>%, data = X, var <- X."""
    used = re.findall(rf"(?<![\w.$`])({_IDENT})\s*(?:\$|\[)", code)
    used += re.findall(rf"(?:<-|=)\s*({_IDENT})\s*(?:#.*)?$", code, re.M)
    used += re.findall(rf"\b(?:{_DATA_FUNCS})\(\s*({_IDENT})\s*[,)]", code)
    used += re.findall(rf"(?<![\w.$])({_IDENT})\s*%>%", code)
    used += re.findall(rf"\bdata\s*=\s*({_IDENT})\b", code)
    return list(dict.fromkeys(used))


def _assigned(code, var):
    v = re.escape(var)
    return re.search(rf"(?<![\w.$]){v}\s*(<<?-|=(?!=))|->\s*{v}\b|assign\(\s*[\"']{v}"
                     rf"|\bfor\s*\(\s*{v}\s+in\b|\bfunction\s*\([^)]*\b{v}\b", code)


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
        return _assigned(code, var)

    preload = []
    by_stem = {Path(n).stem: n for n in data_names}
    for var, name in by_stem.items():  # mismo nombre que el archivo: Taller1, fish...
        if re.fullmatch(_IDENT, var) and re.search(rf"(?<![\w.$]){re.escape(var)}(?![\w.(])", code) \
                and not assigned(var):
            preload.append(f"{var} <- {_reader(name)}")
            changes.append(f"precargado: {preload[-1]}")
    if data_names:  # otros nombres usados como data frame sin definirlos
        used = data_like_uses(code)
        ticks = re.findall(r"`([^`\n]+)`", code)                                          # `Taller1.(1)`
        for var in dict.fromkeys(used + ticks):
            if var in by_stem or var in _KNOWN or assigned(var) or var in _NOT_DATA:
                continue
            target = f"`{var}`" if var in ticks and not re.fullmatch(_IDENT, var) else var
            if var in ticks and not re.search(rf"`{re.escape(var)}`\s*(?:\$|\[|\)|$|\s)", code, re.M):
                continue
            preload.append(f"{target} <- {_reader(data_names[0])}")
            changes.append(f"precargado (supuesto): {preload[-1]}")

    libs = []
    for pkg in r_packages.inferred(code):
        libs.append(f"suppressPackageStartupMessages(library({pkg}))")
        changes.append(f"cargado el paquete {pkg} (usó sus funciones sin library())")
    out = libs + list(preload)
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
    libs = os.pathsep.join(x for x in (str(r_packages.RLIB), _lib_paths()) if x)
    env.update({"HOME": home, "USERPROFILE": home, "LANG": "C.UTF-8", "R_LIBS": libs})
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


_NOT_FOUND = re.compile(r"object '([^']+)' not found")


def _retry_vars(prepared, stderr, data_names) -> list[str]:
    """Variables que R no encontró y que el alumno nunca definió: probablemente su base de datos
    con otro nombre (bd, datos...). Se excluyen las usadas como valor de un argumento (mean = media)."""
    out = []
    for var in dict.fromkeys(_NOT_FOUND.findall(stderr)):
        if not re.fullmatch(_IDENT, var) or var in _KNOWN or var in _NOT_DATA or _assigned(prepared, var):
            continue
        if re.search(rf"\b(?!data\b)\w+\s*=\s*{re.escape(var)}\b(?!\s*\$)", prepared):
            continue
        out.append(var)
    return out if data_names else []


def _execute(prepared, data_files, rscript, env_home_files):
    with tempfile.TemporaryDirectory(prefix="rgrade_") as tmp:
        for p in data_files:
            shutil.copy(p, tmp)
        (Path(tmp) / "alumno.R").write_text(prepared, encoding="utf-8")
        shutil.copy(RUNNER_R, Path(tmp) / "_run.R")  # ejecuta bloque a bloque y guarda gráficos
        try:
            p = subprocess.run([rscript, "--vanilla", "_run.R"], cwd=tmp, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=config.R_TIMEOUT,
                               preexec_fn=None if sys.platform == "win32" else _limits, env=_env(tmp))
            return dict(ok=p.returncode == 0, stdout=p.stdout[-MAX_OUT:], stderr=p.stderr[-MAX_OUT:],
                        returncode=p.returncode, timed_out=False, plots=_plots(tmp))
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return dict(ok=False, stdout=out[-MAX_OUT:], stderr=f"Tiempo límite ({config.R_TIMEOUT}s) excedido",
                        returncode=None, timed_out=True, plots=_plots(tmp))


def run(code: str, data_files: list[Path], use_cache=True) -> RResult:
    names = [p.name for p in data_files]
    key = f"r{RUNNER_VERSION}:" + hashlib.sha256((code + "|" + ",".join(names)).encode()).hexdigest()
    if use_cache and (hit := store.cache_get(key)):
        return RResult(**hit)
    prepared, changes = prepare(code, names)
    rscript = _rscript()
    # Paquetes: instalar los que falten (en data/Rlib, desde CRAN)
    pkgs = list(dict.fromkeys(r_packages.explicit(code) + r_packages.inferred(code)))
    new, failed = r_packages.ensure(pkgs, rscript, _env(str(config.DATA_DIR)))
    changes += [f"instalado el paquete {p} (no estaba en este computador)" for p in new]
    changes += [f"no se pudo instalar el paquete {p}: sus errores NO son del alumno" for p in failed]
    r = _execute(prepared, data_files, rscript, None)
    # Reintento: base de datos guardada con otro nombre que el alumno no pegó
    extra = _retry_vars(prepared, r["stderr"], names)
    if extra:
        pre = [f"{v} <- {_reader(names[0])}" for v in extra]
        prepared = "\n".join(pre) + "\n" + prepared
        changes += [f"precargado (supuesto, R no encontraba '{v}'): {l}" for v, l in zip(extra, pre)]
        r = _execute(prepared, data_files, rscript, None)
    res = RResult(r["ok"], r["stdout"], r["stderr"], r["returncode"], r["timed_out"], prepared, changes,
                  r["plots"])
    store.cache_set(key, res.to_dict())
    return res
