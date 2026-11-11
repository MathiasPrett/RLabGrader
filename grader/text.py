"""Utilidades para pasar HTML de Canvas a texto plano."""
import html
import re


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    # fórmulas de Canvas (imágenes) → $LaTeX$
    s = re.sub(r'<img[^>]*data-equation-content="([^"]*)"[^>]*>', lambda m: f" ${html.unescape(m.group(1))}$ ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|pre|h\d)>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def compact(s: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(s)).strip()
