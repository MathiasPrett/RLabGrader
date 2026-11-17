"""Punto de entrada de RLabGrader.

Uso:  uv run main.py               (abre el navegador solo)
      uv run main.py --no-browser
Abre la app en http://localhost:8765 (cambia el puerto con PORT en .env).
"""
import sys
import threading
import webbrowser

import uvicorn

from grader import config, settings


def check_setup():
    """Avisa en la terminal de lo que falta configurar, sin impedir que la app arranque."""
    problems = []
    st = settings.status()
    if not st["ready"]:
        problems.append("Faltan el token de Canvas y/o el número del curso: complétalos en la app (botón ⚙).")
    if not config.ROSTER_XLSX.exists():
        problems.append(f"Falta la planilla de ayudantes: copia el .xlsx en {config.ROSTER_DIR}")
    if not st["GROQ_API_KEY"]["set"]:
        problems.append("(Opcional) Sin API key de Groq: la sugerencia IA no funcionará (se configura en ⚙).")
    for p in problems:
        print(f"  ⚠  {p}")
    roster = config.ROSTER_XLSX
    if roster.is_relative_to(config.ROOT):
        roster = roster.relative_to(config.ROOT)
    print(f"  Planilla: {roster}")
    print("  Envío a Canvas: se controla con el interruptor de la app (parte encendido).")


def main():
    url = f"http://localhost:{config.PORT}"
    print(f"\nRLabGrader → {url}   (Ctrl+C para cerrar)\n")
    check_setup()
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    uvicorn.run("grader.app:app", host="127.0.0.1", port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
