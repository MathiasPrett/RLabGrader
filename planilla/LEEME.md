# Carpeta `planilla/`

Copia aquí la **planilla de coordinación de ayudantes** (un archivo `.xlsx`).
RLabGrader la detecta sola al iniciar; no hace falta configurar nada en `.env`.

Debe tener:

- Una hoja llamada **`Secciones M y J`** con las columnas (en este orden):
  `Sección`, `Student` (formato "Apellidos, Nombres", igual que en Canvas), `Section`,
  `DÍA` (`M` o `J`) y `Grupos`.
- (Opcional) Las hojas **`Pauta Bonos`** y **`Pauta Taller (tentativa)`** con las pautas.

Deja **un solo** `.xlsx` en esta carpeta (si hay varios, se usa el primero en orden alfabético).
Los archivos de esta carpeta **no se suben a git**: contienen datos de estudiantes.
