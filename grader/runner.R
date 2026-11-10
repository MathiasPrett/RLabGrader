# Ejecuta alumno.R bloque por bloque: un error (incluso de sintaxis) no detiene el resto.
# La salida imita la consola de R; los errores van en línea y además se resumen en stderr.
png("plot_%03d.png", width = 900, height = 620, res = 110)
View <- function(...) invisible(NULL)        # sin pantalla
file.choose <- function(...) stop("file.choose() no disponible")
.src <- readLines("alumno.R", warn = FALSE, encoding = "UTF-8")
.buf <- character(0); .start <- 1L; .errs <- character(0)
.echo <- function(lines) cat(paste0(c("> ", rep("+ ", length(lines) - 1)), lines), sep = "\n")
.err <- function(msg, line) {
  m <- sprintf("Error (línea %d): %s", line, msg)
  cat(m, "\n", sep = ""); .errs <<- c(.errs, m)
}
for (.i in seq_along(.src)) {
  if (!length(.buf)) .start <- .i
  .buf <- c(.buf, .src[.i])
  .p <- tryCatch(parse(text = .buf, keep.source = FALSE), error = function(e) e)
  if (inherits(.p, "error")) {
    if (grepl("unexpected end of input|INCOMPLETE_STRING", conditionMessage(.p)) && .i < length(.src)) next
    .echo(.buf)
    .err(paste("sintaxis:", sub("^<text>:", "", conditionMessage(.p))), .start)
    .buf <- character(0); next
  }
  .echo(.buf); .buf <- character(0)
  for (.e in .p) {
    .r <- withCallingHandlers(
      tryCatch(withVisible(eval(.e, globalenv())), error = function(e) { .err(conditionMessage(e), .start); NULL }),
      warning = function(w) { cat("Warning: ", conditionMessage(w), "\n", sep = ""); invokeRestart("muffleWarning") })
    if (!is.null(.r) && .r$visible) tryCatch(print(.r$value), error = function(e) .err(conditionMessage(e), .start))
  }
}
graphics.off()
if (length(.errs)) { message(paste(.errs, collapse = "\n")); quit(status = 1, save = "no") }
quit(status = 0, save = "no")
