# RLabGrader

Corrector asistido para **bonos** y **talleres** de laboratorios de R en **Canvas** (Quizzes clásicos).
Pensado para ayudantes: reemplaza el ir y venir de SpeedGrader por una pantalla donde ves a **tus**
alumnos, su respuesta, su código R ejecutado y, si lo pides, una **primera opinión de una IA**.

> **La IA nunca pone notas.** Solo sugiere. Tú revisas, decides y confirmas cada corrección.
> Lee el [Descargo de responsabilidad](#descargo-de-responsabilidad) antes de usarla.

---

## Qué hace

- **Tus alumnos, sin buscarlos**: eliges la evaluación, el día y tu grupo (desde la planilla de
  coordinación de ayudantes) y aparecen separados en *pendientes*, *ya revisados*, *sin entrega* y
  *no encontrados*.
- **Todo en una pantalla**: el contexto y la pregunta que le tocó a cada alumno (con versiones
  sorteadas), su respuesta (✔/✘ según Canvas), la respuesta correcta, las alternativas y su código R.
- **▶ Ejecutar R**: corre el código del alumno en tu computador con la base de datos correcta
  (se descarga sola desde el enunciado). Muestra la salida, los errores línea por línea y los
  gráficos. Corrige solo los problemas típicos que no son culpa del alumno (rutas `C:/Users/...`,
  `file.choose()`, copias de la consola, títulos sin `#`, base de datos guardada con otro nombre
  como `bd` o `datos`, paquetes usados sin `library()`) y te dice qué ajustó. Si el alumno usa un
  paquete que no tienes instalado, lo instala solo desde CRAN en `data/Rlib` (sin tocar tu R).
- **Talleres**: separa el código de cada pregunta usando los títulos que puso el alumno
  (`#1`, `Pregunta 2:`, `#P3`…); si no hay, la IA propone dónde está. Cada pregunta tiene su puntaje
  (p. ej. 1 o 1.5) y la pauta se aplica como fracción de ese puntaje.
- **✨ Sugerencia IA** (opcional, con botón): puntaje según la pauta, razón y comentario sugerido.
  **No se envía el nombre ni el ID del alumno** a la IA.
- **Confirmar y subir**: escribe el puntaje y el comentario en Canvas, solo cuando tú lo confirmas.
- **Modo prueba** (`DRY_RUN=1`, por defecto): no envía nada a Canvas.
- Atajos de teclado: `j`/`k` alumno siguiente/anterior · `Tab` pregunta siguiente (talleres) ·
  `0` `5` `7` `1` puntaje · `r` ejecutar R · `i` pedir IA · `c` armar comentario · `Ctrl+Enter` confirmar.

---

## Instalación paso a paso

Necesitas 4 cosas: **uv** (para correr el programa), **R**, un **token de Canvas** y (opcional) una
**API key de Groq** para la IA. Todo es gratis. Además necesitas la **planilla de coordinación de
ayudantes** (el Excel con los alumnos y grupos).

**Resumen rápido** (si ya tienes todo):

1. Copia `.env.example` como `.env` y completa `CANVAS_TOKEN` y `COURSE_ID`.
2. Copia el Excel de coordinación de ayudantes en la carpeta **`planilla/`**.
3. Ejecuta `uv run main.py`. Se abre el navegador en <http://localhost:8765>.

### 1. Instalar uv

[uv](https://docs.astral.sh/uv/) es un programa que instala Python y todo lo que RLabGrader
necesita, sin que tengas que configurar nada. Solo hay que instalarlo una vez.

Abre una **terminal** (en Windows: busca "PowerShell" en el menú Inicio; en Mac: "Terminal";
en Linux: "Terminal") y copia y pega el comando de tu sistema:

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Mac o Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Cierra la terminal y ábrela de nuevo. Comprueba que quedó instalado escribiendo `uv --version`:
debería mostrar un número de versión.

### 2. Instalar R

Si ya usas R o RStudio, ya lo tienes. Si no, descárgalo de <https://cran.r-project.org/> e instálalo.

Luego abre R (o RStudio) y ejecuta una vez esta línea para instalar los paquetes más comunes
(si un alumno usa otro, RLabGrader lo instala solo la primera vez que lo necesite):
```r
install.packages(c("readxl", "rio", "dplyr"))
```

### 3. Descargar RLabGrader

- **Con git:** `git clone https://github.com/MathiasPrett/RLabGrader.git`
- **Sin git:** en la página del repositorio, botón verde **Code → Download ZIP**, y descomprímelo.

En la terminal, entra a la carpeta (ajusta la ruta a donde la dejaste):
```bash
cd RLabGrader
```

### 4. Obtener el token de Canvas

El token es una "contraseña" personal que permite a RLabGrader leer y escribir en Canvas **con tus
mismos permisos** (debes ser ayudante/profesor del curso).

1. Entra a Canvas en el navegador.
2. Haz clic en tu foto o en **Cuenta** (barra izquierda) → **Configuración**.
3. Baja hasta **Integraciones aprobadas** y presiona **+ Nuevo token de acceso**.
4. En "Propósito" escribe algo como `RLabGrader` y pon una **fecha de expiración** (recomendado:
   el fin del semestre).
5. Presiona **Generar token** y **copia el token** que aparece. Canvas lo muestra **una sola vez**.

Si lo pierdes o crees que alguien lo vio, vuelve a esa página y elimínalo; luego crea otro.

### 5. Obtener la API key de Groq (opcional, para la IA)

1. Entra a <https://console.groq.com> y crea una cuenta (puedes usar Google o GitHub).
2. En el menú, ve a **API Keys** y presiona **Create API Key**.
3. Ponle un nombre (ej. `RLabGrader`) y **copia la clave** (empieza con `gsk_`). Se muestra una sola vez.

Sin esta clave la app funciona igual; solo el botón de IA mostrará un aviso.
La cuenta gratuita de Groq tiene límites de uso: si se alcanzan, la IA puede tardar o fallar un rato.

### 6. Configurar el archivo `.env`

En la carpeta de RLabGrader hay un archivo llamado `.env.example`. Haz una copia con el nombre
**`.env`** (exactamente así, con el punto al inicio) y ábrela con cualquier editor de texto
(Bloc de notas, TextEdit, VS Code…). Completa:

| Variable | Qué poner |
|---|---|
| `CANVAS_URL` | La dirección de tu Canvas, ej. `https://cursos.canvas.uc.cl` |
| `CANVAS_TOKEN` | El token del paso 4 |
| `COURSE_ID` | El número del curso: en Canvas, entra al curso y míralo en la URL (`.../courses/123456`) |
| `GROQ_API_KEY` | La clave del paso 5 (opcional) |
| `DRY_RUN` | `1` = modo prueba, no envía nada. `0` = envío real a Canvas |

> El archivo `.env` contiene tus claves: **no lo compartas** ni lo subas a internet.
> El repositorio ya está configurado para que git lo ignore.

### 7. Poner la planilla de alumnos en la carpeta `planilla/`

Copia el Excel de **coordinación de ayudantes** (el `.xlsx` con los alumnos y sus grupos) dentro de
la carpeta **`planilla/`** del proyecto. El nombre del archivo da igual: la app usa el `.xlsx` que
encuentre ahí (deja uno solo).

```
RLabGrader/
├── planilla/
│   └── CoordAyudantes.xlsx   ← aquí va el Excel con los estudiantes
├── .env                      ← tus claves (paso 6)
└── main.py
```

El Excel debe tener:

- Una hoja llamada **`Secciones M y J`** con las columnas `Sección`, `Student` (formato
  "Apellidos, Nombres", igual que en Canvas), `Section`, `DÍA` (`M` o `J`) y `Grupos`.
- (Opcional) Las hojas **`Pauta Bonos`** y **`Pauta Taller (tentativa)`** con las pautas.

Lo que pongas en `planilla/` **no se sube a git** (son datos de estudiantes).

### 8. Abrir la app

En la terminal, dentro de la carpeta de RLabGrader:
```bash
uv run main.py
```
La primera vez tarda un poco porque uv descarga Python y las dependencias. Luego se abre solo el
navegador en **<http://localhost:8765>** (si no, abre esa dirección a mano). En la terminal verás
avisos si falta algo por configurar (el `.env`, el token, la planilla…) y si estás en modo prueba
o envío real.

Para cerrarla, vuelve a la terminal y presiona `Ctrl + C`. Para usarla otro día, repite solo este paso.

Opciones: `uv run main.py --no-browser` no abre el navegador; para usar otro puerto agrega
`PORT=8000` en el `.env`.

---

## Uso recomendado

1. Deja `DRY_RUN=1` mientras te familiarizas: puedes hacer todo, pero nada llega a Canvas.
   Arriba a la derecha verás **MODO PRUEBA** (amarillo) o **ENVÍO REAL** (rojo).
2. Cuando quieras corregir de verdad, cambia a `DRY_RUN=0`, reinicia la app y **prueba con un solo
   alumno**. Revisa en SpeedGrader (cada alumno tiene un enlace) que la nota y el comentario quedaron bien.
3. En **Recursos** puedes subir otras bases de datos, pegar una solución de referencia y escribir
   notas con tus criterios para que la IA las considere.

Bonos y talleres se reconocen por el nombre de la tarea en Canvas: `BonoXX` (ej. `Bono03`) y
`Taller N` (ej. `Taller 1`).

---

## Parches locales (casos excepcionales)

Si una evaluación tuvo un problema puntual (por ejemplo, faltó la pregunta de código y los alumnos
lo entregaron en otro buzón), puedes crear `data/overrides/<ID de la tarea>.json` (solo en tu
computador, nunca se sube a git ni a Canvas):

```json
{
  "codigo_externo": "data/mi_buzon/submissions",
  "estado_local": true,
  "pauta_extra": "Regla excepcional que la IA y tú verán junto a la pauta."
}
```

- `codigo_externo`: carpeta con la descarga de entregas del buzón (Canvas → tarea → *Descargar
  entregas*); se cruza con cada alumno por su ID de Canvas en el nombre del archivo.
- `estado_local`: "ya revisado" solo si corregiste desde la app (útil si Canvas autocorrigió).
- `pauta_extra`: regla especial con prioridad sobre la pauta.

Si borras el archivo, la evaluación vuelve a funcionar como siempre.

## Privacidad y seguridad

- Las claves viven solo en tu `.env`, en tu computador.
- A la IA se envía el enunciado, la respuesta, el código, la salida de R y una muestra de la base
  de datos. **Nunca** el nombre ni el ID del alumno. Aun así, revisa que el uso de servicios de IA
  externos esté permitido por tu institución y curso.
- El código de los alumnos se ejecuta en una carpeta temporal, con tiempo y memoria limitados y
  **sin acceso a tus claves**. No es un aislamiento completo: no ejecutes código que te parezca
  malicioso.
- Las bases de datos, notas y caché quedan en `data/` y la planilla en `planilla/` (ambas
  ignoradas por git).

---

## Estructura

| Ruta | Qué contiene |
|---|---|
| `main.py` | Punto de entrada: `uv run main.py` |
| `planilla/` | **Aquí va el Excel de coordinación de ayudantes** (no se sube a git) |
| `data/` | Se crea sola: caché, bases de datos, paquetes R y parches locales (no se sube a git) |
| `grader/canvas_client.py` | Conexión con la API de Canvas |
| `grader/roster.py` | Cruce de la planilla de grupos con los alumnos de Canvas |
| `grader/assessments/` | Tipos de evaluación (bono, taller), pautas y separación del código por pregunta |
| `grader/ai/` | IA detrás de una fachada (`facade.py`); proveedores en `providers/` (hoy: Groq) |
| `grader/r_runner.py`, `grader/runner.R` | Preparación y ejecución tolerante del código R |
| `grader/service.py`, `grader/app.py` | Lógica y servidor web |
| `grader/static/`, `grader/templates/` | Interfaz |

Para agregar otro proveedor de IA: implementa `AIProvider.complete_json` en `grader/ai/providers/`
y regístralo en `grader/ai/registry.py`. Para otro tipo de evaluación: crea una clase en
`grader/assessments/` y regístrala en `grader/assessments/registry.py`.

---

## Descargo de responsabilidad

**Herramienta no oficial.** RLabGrader es un proyecto personal e independiente. No está afiliado,
respaldado ni mantenido por Instructure (Canvas), Groq, ninguna universidad ni ningún curso.
"Canvas" y "SpeedGrader" son marcas de sus respectivos dueños.

**Uso bajo tu propia responsabilidad.** El software se entrega "tal cual", sin garantías de ningún
tipo. El autor no se hace responsable de ningún daño, pérdida de datos, error en calificaciones,
filtración de información ni de cualquier mal uso que se haga de esta herramienta, incluido su uso
en contra de las normas de tu institución, curso o de las condiciones de uso de Canvas o Groq.
Cada persona que la usa es la única responsable de cumplir esas normas y de proteger sus claves y
los datos de los estudiantes.

**Corrección con IA: humano en el ciclo (*human in the loop*).** La IA entrega solo una **primera
opinión** no vinculante, que puede estar equivocada. Revisar, corregir y confirmar cada puntaje y
cada comentario es **responsabilidad exclusiva y obligatoria de la persona que corrige**. Ninguna
nota se publica sin una confirmación humana explícita, y quien confirma es responsable de ella.

---

## Licencia

[MIT](LICENSE). Puedes usar, copiar, modificar y distribuir este software libremente, manteniendo
el aviso de copyright. Se entrega "tal cual", sin garantías (ver también el descargo de
responsabilidad más arriba).
