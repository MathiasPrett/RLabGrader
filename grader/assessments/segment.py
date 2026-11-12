"""Divide el código de un taller en bloques por pregunta usando los títulos que pone el alumno.

Reconoce títulos como:
  #1   # 2)   #P3   # Pregunta 4:   #pregunta_5   #Pregunta 1#   ####primera pregunta####
  Pregunta 1:   PREGUNTA 2   P3   1.- código   4. boxplot(...)     (sin '#': se comentan antes de ejecutar)
El número es el orden en que el alumno vio las preguntas (1..n).
"""
import re

ORDINALS = {"primera": 1, "primer": 1, "segunda": 2, "segundo": 2, "tercera": 3, "tercer": 3,
            "cuarta": 4, "cuarto": 4, "quinta": 5, "quinto": 5, "sexta": 6, "sexto": 6,
            "septima": 7, "séptima": 7, "octava": 8}
_WORD = r"(?:p(?:regunta|reg)?|[ií]tem|ejercicio|parte|q)"
_ORD = "|".join(sorted(ORDINALS, key=len, reverse=True))

# Con '#': flexible (el número puede ir seguido de texto)
_HASH = re.compile(rf"^\s*#+[\s#*=_\-]*(?:{_WORD}[\s._]*(?:n[°º]\s*)?)?(\d{{1,2}})(?!\d|[.,]\d)", re.I)
# Sin '#': palabra + número solos en la línea ("Pregunta 1:", "P2", "PREGUNTA 3")
_WORD_ONLY = re.compile(rf"^\s*{_WORD}[\s._]*(?:n[°º]\s*)?(\d{{1,2}})\s*[:.)\-–]*\s*$", re.I)
# Sin '#': "1.- código", "4. boxplot(...)", "5." , "2) ..."  (no "1 - pnorm(...)", que es R válido)
_NUM_PREFIX = re.compile(r"^\s*(\d{1,2})(?:\.-|\.(?![\d\w])|\))\s*(.*)$")
# Título al final de una línea de código: "x <- datos[...] # Pregunta 1", "mean(y)  #P2"
_TRAILING = re.compile(rf"^[^#]*\S[^#]*#+\s*{_WORD}[\s._]*(?:n[°º]\s*)?(\d{{1,2}})\s*[:.)\-–]*\s*$", re.I)
# Ordinales: "primera pregunta", "pregunta segunda" (con o sin '#')
_ORDINAL = re.compile(rf"^\s*#*[\s#*=_\-]*(?:({_ORD})[\s_]+pregunta|pregunta[\s_]+({_ORD}))", re.I)


def header_number(line: str, max_n: int = 20) -> tuple[int, bool, str] | None:
    """(número, es_comentario, código_que_sigue) si la línea es un título de pregunta."""
    m = _ORDINAL.match(line)
    if m:
        n = ORDINALS[(m.group(1) or m.group(2)).lower()]
        return (n, line.lstrip().startswith("#"), "") if n <= max_n else None
    m = _HASH.match(line)
    if m:
        n = int(m.group(1))
        return (n, True, "") if 1 <= n <= max_n else None
    if line.lstrip().startswith(">"):
        return None
    m = _TRAILING.match(line)
    if m:  # la línea es código válido: no hay que comentarla
        n = int(m.group(1))
        return (n, True, "") if 1 <= n <= max_n else None
    m = _WORD_ONLY.match(line)
    if m:
        n = int(m.group(1))
        return (n, False, "") if 1 <= n <= max_n else None
    m = _NUM_PREFIX.match(line)
    if m:
        n, rest = int(m.group(1)), m.group(2)
        return (n, False, rest) if 1 <= n <= max_n else None
    return None


def headers(code: str, n_items: int):
    out = []
    for i, line in enumerate(code.splitlines(), start=1):
        h = header_number(line, n_items)
        if h:
            out.append((i, h[0]))
    return out


def segment(code: str, n_items: int) -> dict[int, list[list[int]]]:
    """{n: [[ini, fin], ...]} con líneas 1-based. Solo incluye las preguntas encontradas."""
    total = len(code.splitlines())
    hs = headers(code, n_items)
    # Un número suelto no basta: exigir al menos 2 títulos distintos.
    if len({n for _, n in hs}) < 2:
        return {}
    # Si un número se repite seguido ("# 5" y luego "# 5 veces"), el bloque continúa.
    merged = [h for k, h in enumerate(hs) if k == 0 or hs[k - 1][1] != h[1]]
    blocks: dict[int, list[list[int]]] = {}
    for k, (line, n) in enumerate(merged):
        end = merged[k + 1][0] - 1 if k + 1 < len(merged) else total
        blocks.setdefault(n, []).append([line, end])
    return blocks
