"""Paquetes de R que usa el código del alumno: detectarlos, cargarlos e instalar los que falten.

Los alumnos suelen usar funciones de un paquete (import, %>%, read_excel...) sin pegar el
library(), porque en su RStudio ya estaba cargado. Aquí se infieren y se cargan.
Los que no estén instalados se instalan desde CRAN en data/Rlib (no toca el R del usuario).
"""
import re
import subprocess

from . import config, store

CRAN = "https://cloud.r-project.org"
RLIB = config.DATA_DIR / "Rlib"
_PKG = re.compile(r"^[A-Za-z][A-Za-z0-9.]*[A-Za-z0-9]$")
_BASE = {"base", "stats", "utils", "graphics", "grDevices", "methods", "datasets", "tools", "grid",
         "parallel", "splines", "stats4", "tcltk", "compiler"}

# función usada → paquete que la provee
FUNC_PKG = {
    "rio": ["import", "export", "convert", "import_list"],
    "readxl": ["read_excel", "read_xlsx", "read_xls", "excel_sheets"],
    "readr": ["read_csv", "read_csv2", "read_table", "read_table2", "read_delim", "read_tsv", "write_csv",
              "parse_number"],
    "dplyr": ["mutate", "summarise", "summarize", "group_by", "arrange", "rename", "left_join", "right_join",
              "inner_join", "full_join", "bind_rows", "bind_cols", "case_when", "pull", "n_distinct", "glimpse",
              "distinct", "slice_max", "slice_min", "across", "if_else", "transmute", "ungroup", "tibble"],
    "magrittr": ["%>%"],
    "ggplot2": ["ggplot", "aes", "geom_histogram", "geom_boxplot", "geom_point", "geom_bar", "geom_line",
                "geom_density", "geom_col", "facet_wrap", "ggtitle", "labs", "theme_minimal"],
    "data.table": ["fread", "fwrite", "data.table"],
    "janitor": ["clean_names", "tabyl"],
    "moments": ["skewness", "kurtosis"],
    "fitdistrplus": ["fitdist", "descdist"],
    "mvtnorm": ["pmvnorm", "dmvnorm", "rmvnorm", "qmvnorm", "pmvt"],
    "tidyr": ["pivot_longer", "pivot_wider", "drop_na", "replace_na"],
}
# dplyr también provee %>%, filter y select: si usa verbos de dplyr, basta con dplyr
_DPLYR_EXTRA = ["filter", "select", "count"]


def explicit(code: str) -> list[str]:
    """Paquetes que el alumno carga o usa con pkg::"""
    found = re.findall(r"\b(?:library|require|requireNamespace)\(\s*[\"']?([A-Za-z][\w.]*)[\"']?", code)
    found += re.findall(r"\b([A-Za-z][\w.]*)::", code)
    return [p for p in dict.fromkeys(found) if p not in _BASE]


def inferred(code: str) -> list[str]:
    """Paquetes cuyas funciones se usan sin library()."""
    loaded = set(explicit(code))
    out = []
    for pkg, funcs in FUNC_PKG.items():
        for f in funcs:
            pat = re.escape(f) if f.startswith("%") else rf"(?<![\w.$:]){re.escape(f)}\s*\("
            if re.search(pat, code):
                out.append(pkg)
                break
    if "magrittr" in out and any(re.search(rf"(?<![\w.$:]){f}\s*\(", code) for f in _DPLYR_EXTRA):
        out.append("dplyr")  # %>% con filter/select/count: es dplyr
    if "dplyr" in out or "dplyr" in loaded:
        out = [p for p in out if p != "magrittr"]  # dplyr ya trae %>%
    return [p for p in dict.fromkeys(out) if p not in loaded and not (p == "magrittr" and "dplyr" in loaded)]


def _rscript_out(rscript, expr, timeout, env):
    return subprocess.run([rscript, "--vanilla", "-e", expr], capture_output=True, text=True,
                          timeout=timeout, env=env)


_installed: set[str] | None = None


def installed(rscript, env, refresh=False) -> set[str]:
    global _installed
    if _installed is None or refresh:
        p = _rscript_out(rscript, 'cat(rownames(installed.packages()), sep="\\n")', 60, env)
        _installed = set(p.stdout.split())
    return _installed


def ensure(pkgs: list[str], rscript, env) -> tuple[list[str], list[str]]:
    """Instala desde CRAN los paquetes que falten. Devuelve (instalados_ahora, fallidos)."""
    have = installed(rscript, env)
    missing = [p for p in pkgs if _PKG.match(p) and p not in have and p not in _BASE]
    if not missing:
        return [], []
    failed_before = [p for p in missing if store.cache_get_fresh(f"rpkg_fail:{p}", 24 * 3600)]
    todo = [p for p in missing if p not in failed_before]
    if todo:
        RLIB.mkdir(parents=True, exist_ok=True)
        lib = str(RLIB).replace("\\", "/")
        expr = (f'install.packages(c({", ".join(repr(p) for p in todo)}), lib = "{lib}", '
                f'repos = "{CRAN}", quiet = TRUE)')
        try:
            _rscript_out(rscript, expr, 900, env)
        except subprocess.TimeoutExpired:
            pass
        have = installed(rscript, env, refresh=True)
    ok = [p for p in todo if p in have]
    failed = [p for p in missing if p not in have]
    for p in failed:
        store.cache_set(f"rpkg_fail:{p}", True)
    return ok, failed
