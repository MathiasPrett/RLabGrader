// RLabGrader — interfaz. La IA solo sugiere; nada se envía sin "Confirmar".
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { evals: [], info: null, students: [], cur: -1, student: null, item: 0, fr: [], ai: null, rr: null };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || j.detail || r.statusText);
  return j;
}
const post = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });
async function busy(btn, fn) {
  btn.disabled = true;
  try { return await fn(); } catch (e) { alert(e.message); } finally { btn.disabled = false; }
}
const LS = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
             set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };
const fmt = (x) => (Math.round(x * 100) / 100).toString();
const hl = (code) => { try { return hljs.highlight(code, { language: "r" }).value; } catch { return esc(code); } };
const isTaller = () => S.student?.items.length > 1 || S.info?.type === "taller";

// ---------- inicio ----------
async function init() {
  const [evals, groups] = await Promise.all([api("/api/assessments"), api("/api/groups")]);
  S.evals = evals;
  const opt = (t, label) => {
    const xs = evals.filter((e) => e.type === t);
    return xs.length ? `<optgroup label="${label}">${xs.map((e) => `<option value="${e.id}">${esc(e.name.trim())}</option>`).join("")}</optgroup>` : "";
  };
  $("#sel-eval").innerHTML = opt("bono", "Bonos") + opt("taller", "Talleres");
  $("#sel-day").innerHTML = Object.keys(groups).map((d) => `<option>${d}</option>`).join("");
  const fillGroups = () => ($("#sel-group").innerHTML = groups[$("#sel-day").value].map((g) => `<option>${g}</option>`).join(""));
  $("#sel-day").onchange = fillGroups;
  for (const k of ["eval", "day"]) if (LS.get(k) && [...$("#sel-" + k).options].some((o) => o.value === LS.get(k))) $("#sel-" + k).value = LS.get(k);
  fillGroups();
  if (LS.get("group")) $("#sel-group").value = LS.get("group");
}

async function load(refresh = false) {
  const aid = $("#sel-eval").value, day = $("#sel-day").value, group = $("#sel-group").value;
  ["eval", "day", "group"].forEach((k) => LS.set(k, $("#sel-" + k).value));
  $("#list").innerHTML = '<p class="muted">Cargando desde Canvas…</p>';
  const r = await api(`/api/eval/${aid}?day=${encodeURIComponent(day)}&group=${encodeURIComponent(group)}&refresh=${refresh}`);
  S.info = r.info; S.students = r.students; S.cur = -1;
  $("#mode").textContent = r.info.dry_run ? "Modo prueba: no envía" : "Envío real a Canvas";
  $("#mode").className = r.info.dry_run ? "dry" : "live";
  $("#student").innerHTML = "";
  renderList();
  const first = S.students.findIndex((s) => s.status === "pendiente");
  select(first >= 0 ? first : S.students.findIndex((s) => s.status === "revisado"));
}

// ---------- lista ----------
const ORDER = { pendiente: "Pendientes", revisado: "Ya revisados", sin_entrega: "Sin entrega", no_encontrado: "No encontrados en Canvas" };
function renderList() {
  let html = "";
  for (const [st, title] of Object.entries(ORDER)) {
    const rows = S.students.map((s, i) => [s, i]).filter(([s]) => s.status === st);
    if (!rows.length) continue;
    html += `<h4>${title} <span class="n">${rows.length}</span></h4>`;
    for (const [s, i] of rows) {
      const app = s.app ? `<span class="badge" title="Enviado desde esta app">${s.app.dry_run ? "prueba" : "✓ app"}</span>` : "";
      const warn = s.warnings.length ? `<span class="warn" title="${esc(s.warnings.join("; "))}">⚠</span>` : "";
      const sc = s.score != null && st !== "sin_entrega" ? `<span class="badge">${fmt(s.score)}</span>` : "";
      html += `<div class="st ${i === S.cur ? "sel" : ""}" data-i="${i}"><span class="dot ${st}"></span>
        <span class="nm" title="${esc(s.name)}">${esc(s.name)}</span>${warn}${app}${sc}</div>`;
    }
  }
  $("#list").innerHTML = html || '<p class="muted">Sin alumnos.</p>';
  $("#list").querySelectorAll(".st").forEach((el) => (el.onclick = () => select(+el.dataset.i)));
  const done = S.students.filter((s) => s.status === "revisado" || s.app).length;
  const total = S.students.filter((s) => s.status !== "sin_entrega" && s.status !== "no_encontrado").length;
  $("#progress").innerHTML = `<b>${done}</b> de ${total} revisados`;
  $("#progress-bar").style.width = total ? `${(100 * done) / total}%` : "0";
  $("#meter").hidden = false;
}

// ---------- alumno ----------
async function select(i) {
  const s = S.students[i];
  if (!s) return;
  S.cur = i; S.item = 0; S.ai = null; S.rr = null; renderList();
  $("#list .st.sel")?.scrollIntoView({ block: "nearest" });
  $("#grade-msg").textContent = ""; $("#comment").value = ""; $("#custom").value = "";
  if (!s.user_id || s.status === "sin_entrega") {
    S.student = null; S.fr = [];
    $("#student").innerHTML = `<div class="card sheet-head"><h3>${esc(s.name)}</h3><p class="muted">${s.user_id ? "No respondió esta evaluación." : "No se encontró en Canvas."}</p>
      ${s.warnings.map((w) => `<div class="note warn small">⚠ ${esc(w)}</div>`).join("")}</div>`;
    renderGrade(); renderAI(); return;
  }
  $("#student").innerHTML = '<p class="muted">Cargando…</p>';
  const st = await api(`/api/eval/${S.info.id}/student/${s.user_id}`);
  if (S.students[S.cur] !== s) return;
  S.student = st;
  S.fr = st.items.map(() => null);
  renderStudent(); renderGrade(); renderAI();
  $("#center").scrollTop = 0;
}

function codeBlock(code, ranges = null, numbered = false) {
  const lines = code.split("\n");
  const want = (n) => !ranges || ranges.some(([a, b]) => n >= a && n <= b);
  let out = "", prev = 0;
  lines.forEach((l, k) => {
    const n = k + 1;
    if (!want(n)) return;
    if (ranges && prev && n !== prev + 1) out += '<span class="gap">⋯</span>\n';
    out += (numbered || ranges ? `<span class="ln">${n}</span>` : "") + hl(l) + "\n";
    prev = n;
  });
  return `<pre class="code"><code class="hljs">${out}</code></pre>`;
}

function fragmentOf(it) {
  const ai = S.ai?.items?.find((x) => x.n === it.n);
  if (it.fragment_source === "comentarios") return { lines: it.fragment_lines, src: "según los títulos del alumno" };
  if (ai?.lineas?.length) return { lines: ai.lineas, src: "ubicado por la IA (verifica)" };
  return null;
}

function renderStudent() {
  const s = S.students[S.cur], st = S.student;
  const taller = isTaller();
  const head = `<div class="card sheet-head"><div class="row" style="justify-content:space-between">
      <h3>${esc(s.name)}</h3><a class="small" href="${st.speedgrader}" target="_blank" rel="noopener">abrir en SpeedGrader ↗</a></div>
    <div class="grade muted">Nota actual en Canvas: <b>${st.score != null ? fmt(st.score) : "—"}</b> / ${st.points_possible} · ${st.status}${st.late ? ' · <span class="bad">atrasado</span>' : ""}</div>
    ${s.warnings.map((w) => `<div class="note warn small">⚠ ${esc(w)}</div>`).join("")}
    ${st.comments.map((c) => `<div class="note msg small"><b>${esc(c.author)}</b>: ${esc(c.text)}</div>`).join("")}
    <details class="ctx"><summary class="small">Contexto${st.files.length ? " · BD: " + st.files.map(esc).join(", ") : ""}</summary><pre>${esc(st.context)}</pre></details></div>`;

  const items = st.items.map((it, k) => {
    const mark = (it.canvas_correct === true ? '<span class="chip ok">✔ correcta</span>' : it.canvas_correct === false ? '<span class="chip bad">✘ incorrecta</span>' : "") +
      (it.canvas_flag != null && it.canvas_flag !== it.canvas_correct
        ? ` <span class="muted" title="Canvas guardó esta marca al momento de la entrega; después cambió la clave de la pregunta o se ajustó el puntaje. Aquí se compara con la clave actual.">(al entregar Canvas la marcó ${it.canvas_flag ? "✔" : "✘"})</span>` : "");
    const opts = Object.values(it.answer_q.options || {});
    const optHtml = opts.length ? `<ul class="opts">${opts.map((o) => `<li class="${o === it.answer_q.correct ? "right" : ""} ${o === it.answer_text ? "chosen" : ""}">${esc(o)}</li>`).join("")}</ul>` : "";
    const frag = fragmentOf(it);
    let codeHtml = "";
    const noCode = S.info.pauta_extra ? '<p class="muted">(no entregó código — ver excepción de esta evaluación)</p>' : '<p class="bad">(no entregó código)</p>';
    const srcTag = st.code_source === "buzón" ? '<div class="small buzon">📥 Código recibido en el buzón aparte (solo local, no está en Canvas)</div>' : "";
    if (!taller) codeHtml = st.code.trim() ? srcTag + codeBlock(st.code) : noCode;
    else if (frag) codeHtml = `<div class="small muted">Código de esta pregunta — ${frag.src}</div>${codeBlock(st.code, frag.lines)}`;
    else codeHtml = `<div class="small warn">No se identificó el código de esta pregunta (pide la sugerencia IA o revisa el código completo).</div>`;
    return `<div class="card item ${taller && k === S.item ? "active" : ""}" data-k="${k}">
      <div class="row qhead"><span class="qlabel">${taller ? `${esc(it.label)}<small>${fmt(it.points)} pts</small>` : "Pregunta"}</span>
        <span class="small">${mark} <span class="muted">(Canvas: ${fmt(it.canvas_points)})</span></span></div>
      <details ${it.answer_q.text.length < 450 ? "open" : ""}><summary class="small muted">Enunciado</summary><pre>${esc(it.answer_q.text)}</pre></details>
      ${optHtml}
      <div class="small answer">Respuesta: <b>${esc(it.answer_text)}</b>${opts.length ? "" : ` <span class="muted">· correcta: ${esc(it.answer_q.correct || "?")}</span>`}</div>
      ${codeHtml}
    </div>`;
  }).join("");

  const full = taller ? `<details class="card" ${st.items.some((it) => !fragmentOf(it)) ? "open" : ""}>
      <summary><b>Código completo</b> <span class="small muted">(${st.code.split("\n").length} líneas)</span></summary>
      ${st.code.trim() ? codeBlock(st.code, null, true) : '<p class="bad">(no entregó código)</p>'}</details>` : "";
  $("#student").innerHTML = head + (items || '<div class="card muted">Sin preguntas respondidas.</div>') + full + renderRun();
  if (taller) $("#student").querySelectorAll(".item").forEach((el) => (el.onclick = (e) => {
    if (e.target.closest("summary,a")) return;
    setItem(+el.dataset.k, false);
  }));
}

function renderRun() {
  const r = S.rr;
  if (!r) return "";
  if (r.error) return `<div class="card bad small">${esc(r.error)}</div>`;
  const nErr = (r.stderr.match(/^Error/gm) || []).length;
  const st = r.timed_out ? '<span class="bad">tiempo excedido</span>' : r.ok ? '<span class="ok">sin errores</span>' : `<span class="bad">${nErr || ""} error(es)</span>`;
  const ch = r.changes.length ? `<details class="small"><summary>${r.changes.length} ajuste(s) automático(s)</summary><ul>${r.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></details>` : "";
  const plots = (r.plots || []).map((p, k) => `<a href="${p}" target="_blank"><img src="${p}" alt="Gráfico ${k + 1}"></a>`).join("");
  return `<div class="card"><b>Ejecución en R</b> · ${st}${ch}
    <pre class="out">${esc(r.stdout)}${r.timed_out ? `<span class="err">\n${esc(r.stderr)}</span>` : ""}</pre>
    ${plots ? `<div class="plots">${plots}</div>` : ""}</div>`;
}

// ---------- puntaje ----------
function setItem(k, scroll = true) {
  if (!S.student || k < 0 || k >= S.student.items.length) return;
  S.item = k; $("#custom").value = "";
  document.querySelectorAll("#student .item").forEach((el) => el.classList.toggle("active", +el.dataset.k === k));
  if (scroll) document.querySelector(`#student .item[data-k="${k}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  renderGrade(); renderAI();
}
function total() {
  const st = S.student;
  return st ? st.items.reduce((a, it, k) => a + (S.fr[k] ?? 0) * it.points, 0) + (st.base_points || 0) : 0;
}
function renderGrade() {
  const st = S.student, lv = S.info?.rubric || [];
  const items = st?.items || [];
  const sug = S.ai?.items?.find((x) => x.n === items[S.item]?.n)?.puntaje;
  const tabs = items.length > 1 ? `<div class="tabs">${items.map((it, k) =>
    `<button data-k="${k}" class="${k === S.item ? "on" : ""}">${esc(it.label)}<br><small>${S.fr[k] == null ? "—" : fmt(S.fr[k] * it.points) + "/" + fmt(it.points)}</small></button>`).join("")}</div>` : "";
  const cur = S.fr[S.item];
  $("#levels").innerHTML = tabs + lv.map((l) => `<button data-v="${l.score}" class="lvl ${cur === l.score ? "on" : ""}" title="${esc(l.note)}">
      <b>${l.score}</b><span class="desc">${esc(l.description)}${sug === l.score ? '<span class="sug">IA sugiere</span>' : ""}</span></button>`).join("") +
    (S.info?.rubric_note ? `<div class="small muted">${esc(S.info.rubric_note)}</div>` : "") +
    (S.info?.pauta_extra ? `<details class="small excepcion" open><summary><b>Excepción de esta evaluación</b></summary><pre>${esc(S.info.pauta_extra)}</pre></details>` : "");
  $("#levels").querySelectorAll(".lvl").forEach((b) => (b.onclick = () => setScore(+b.dataset.v)));
  $("#levels").querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => setItem(+b.dataset.k)));
  const pp = S.info?.points_possible;
  $("#total").innerHTML = st && items.length ? `Total: <b>${fmt(total())}</b>${pp ? " / " + pp : ""}${st.base_points ? ` <span class="muted">(incluye punto base ${fmt(st.base_points)})</span>` : ""}${S.fr.some((f) => f == null) ? ' · <span class="warn">faltan preguntas</span>' : ""}` : "";
}
function setScore(v, advance = true) {
  if (!S.student?.items.length) return;
  S.fr[S.item] = v; $("#custom").value = "";
  if (advance && S.student.items.length > 1) {
    const next = S.fr.findIndex((f, k) => f == null && k > S.item);
    const any = S.fr.findIndex((f) => f == null);
    if (next >= 0 || any >= 0) return setItem(next >= 0 ? next : any);
  }
  renderGrade();
}

// ---------- IA ----------
function renderAI() {
  const a = S.ai;
  if (!a) { $("#ai").innerHTML = '<span class="muted small">La IA solo recomienda. Tú decides.</span>'; return; }
  if (a.error) { $("#ai").innerHTML = `<div class="bad small">${esc(a.error)}</div>`; return; }
  const items = S.student?.items || [];
  const it = items[S.item];
  const x = a.items.find((y) => y.n === it?.n);
  const yn = (v) => (v === true ? "sí" : v === false ? "no" : "?");
  const summary = items.length > 1 ? `<div class="aisum">${a.items.map((y) => {
    const k = items.findIndex((i) => i.n === y.n);
    return `<button data-k="${k}" class="${k === S.item ? "on" : ""}">P${y.n}: <b>${y.puntaje}</b></button>`; }).join("")}</div>` : "";
  $("#ai").innerHTML = summary + (x ? `<div class="ai-box"><div class="row"><span class="score">${x.puntaje}</span>
      <span class="small">${esc(x.nivel)}<br><span class="muted">confianza ${esc(x.confianza)}</span></span></div>
    <div class="small muted">Resp. correcta: ${yn(x.respuesta_correcta)} · código funciona: ${yn(x.codigo_funciona)} · código correcto: ${yn(x.codigo_correcto)}</div>
    <p class="small"><b>Razón:</b> ${esc(x.razon)}</p>
    ${x.observaciones_codigo ? `<p class="small"><b>Código:</b> ${esc(x.observaciones_codigo)}</p>` : ""}
    ${x.comentario_sugerido ? `<p class="small"><b>Comentario sugerido:</b> ${esc(x.comentario_sugerido)}</p>` : ""}
    <div class="row"><button id="btn-usescore">Usar ${x.puntaje}</button>${items.length > 1 ? '<button id="btn-useall">Usar todos los puntajes IA</button>' : ""}</div></div>` : "") +
    (a.comentario_general ? `<p class="small"><b>Comentario general sugerido:</b> ${esc(a.comentario_general)}</p>` : "");
  $("#ai").querySelectorAll(".aisum button").forEach((b) => (b.onclick = () => setItem(+b.dataset.k)));
  $("#btn-usescore")?.addEventListener("click", () => setScore(x.puntaje));
  $("#btn-useall")?.addEventListener("click", () => {
    items.forEach((i, k) => { const y = a.items.find((z) => z.n === i.n); if (y) S.fr[k] = y.puntaje; });
    renderGrade();
  });
}
function buildComment() {
  const a = S.ai, items = S.student?.items || [];
  if (!a?.items) return;
  const parts = [];
  items.forEach((it, k) => {
    const y = a.items.find((z) => z.n === it.n);
    const full = (S.fr[k] ?? y?.puntaje) === 1;
    if (y?.comentario_sugerido && !full) parts.push(items.length > 1 ? `${it.label}: ${y.comentario_sugerido}` : y.comentario_sugerido);
  });
  if (a.comentario_general) parts.push(a.comentario_general);
  $("#comment").value = parts.join("\n");
}

// ---------- acciones ----------
const uid = () => S.students[S.cur]?.user_id;
async function runR() {
  if (!S.student?.items.length) return;
  const who = uid();
  await busy($("#btn-run"), async () => {
    try { S.rr = await post(`/api/eval/${S.info.id}/student/${who}/run_r`); } catch (e) { S.rr = { error: e.message }; }
    if (uid() === who) renderStudent();
  });
}
async function askAI() {
  if (!S.student?.items.length) return;
  const who = uid();
  $("#ai").innerHTML = '<span class="muted small">Pensando… (ejecuta R y consulta la IA)</span>';
  await busy($("#btn-ai"), async () => {
    let a;
    try { a = await post(`/api/eval/${S.info.id}/student/${who}/suggest`); } catch (e) { a = { error: e.message }; }
    if (uid() !== who) return;
    S.ai = a;
    if (!S.rr) S.rr = await post(`/api/eval/${S.info.id}/student/${who}/run_r`).catch(() => null);
    renderStudent(); renderGrade(); renderAI();
  });
}
async function grade() {
  const st = S.student;
  if (!st?.items.length) return;
  const custom = $("#custom").value;
  if (custom !== "") S.fr[S.item] = +custom;
  if (S.fr.some((f) => f == null)) { renderGrade(); return alert("Falta elegir puntaje" + (st.items.length > 1 ? " en: " + st.items.filter((_, k) => S.fr[k] == null).map((i) => i.label).join(", ") : "")); }
  const s = S.students[S.cur], comment = $("#comment").value;
  const detail = st.items.map((it, k) => `${it.label}: ${S.fr[k]} × ${fmt(it.points)} = ${fmt(S.fr[k] * it.points)}`).join("\n");
  const msg = `${s.name}\n${detail}\nTotal: ${fmt(total())}${st.base_points ? " (con punto base)" : ""}\n\nComentario: ${comment || "(ninguno)"}\n\n${S.info.dry_run ? "MODO PRUEBA: no se enviará a Canvas." : "Se enviará a Canvas."}`;
  if (!confirm(msg)) return;
  await busy($("#btn-grade"), async () => {
    const r = await post(`/api/eval/${S.info.id}/student/${s.user_id}/grade`, { fractions: S.fr, comment });
    $("#grade-msg").innerHTML = r.dry_run ? '<span class="warn">Registrado en modo prueba (no enviado).</span>'
      : `<span class="ok">Enviado. Nota en Canvas: ${fmt(r.new_score)}</span>`;
    s.app = { dry_run: r.dry_run }; if (!r.dry_run) { s.status = "revisado"; s.score = r.new_score; }
    renderList();
    setTimeout(() => next(1, true), 700);
  });
}
function next(d, pendingOnly = false) {
  if (!S.students.length) return;
  let i = S.cur;
  for (let n = 0; n < S.students.length; n++) {
    i = (i + d + S.students.length) % S.students.length;
    const st = S.students[i].status;
    if (pendingOnly ? st === "pendiente" && !S.students[i].app : st !== "no_encontrado") return select(i);
  }
}

// ---------- recursos ----------
async function openRes() {
  if (!S.info) return alert("Primero carga una evaluación");
  $("#res-files").innerHTML = S.info.files.map((f) => `<li>${esc(f)}</li>`).join("") || "<li class='muted'>ninguna</li>";
  $("#res-solution").value = S.info.solution; $("#res-notes").value = S.info.notes;
  $("#res-out").classList.add("hidden");
  $("#dlg-res").showModal();
}
async function saveRes() {
  await post(`/api/eval/${S.info.id}/resources`, { solution: $("#res-solution").value, notes: $("#res-notes").value });
  S.info.solution = $("#res-solution").value; S.info.notes = $("#res-notes").value;
}

// ---------- eventos ----------
$("#btn-load").onclick = () => busy($("#btn-load"), () => load(false));
$("#btn-refresh").onclick = () => busy($("#btn-refresh"), () => load(true));
$("#btn-run").onclick = runR;
$("#btn-ai").onclick = askAI;
$("#btn-grade").onclick = grade;
$("#btn-comment").onclick = buildComment;
$("#custom").oninput = () => { const v = $("#custom").value; if (v !== "" && +v >= 0 && +v <= 1) { S.fr[S.item] = +v; renderGrade(); } };
$("#btn-res").onclick = openRes;
$("#res-close").onclick = () => $("#dlg-res").close();
$("#res-save").onclick = () => busy($("#res-save"), async () => { await saveRes(); $("#dlg-res").close(); });
$("#res-run").onclick = () => busy($("#res-run"), async () => {
  await saveRes();
  const r = await post(`/api/eval/${S.info.id}/run_solution`);
  $("#res-out").classList.remove("hidden");
  $("#res-out").textContent = r.error || (r.stdout + (r.stderr ? "\n" + r.stderr : ""));
});
$("#res-upload").onchange = (e) => busy($("#res-save"), async () => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch(`/api/eval/${S.info.id}/files`, { method: "POST", body: fd }).then((x) => x.json());
  if (r.detail) throw new Error(r.detail);
  S.info.files = r.files;
  $("#res-files").innerHTML = r.files.map((x) => `<li>${esc(x)}</li>`).join("");
});

document.addEventListener("keydown", (e) => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); grade(); return; }
  if (typing || $("#dlg-res").open || e.ctrlKey || e.metaKey || e.altKey) return;
  const map = { "0": 0, "5": 0.5, "7": 0.7, "1": 1 };
  if (e.key in map) setScore(map[e.key]);
  else if (e.key === "Tab" && S.student?.items.length > 1) { e.preventDefault(); setItem((S.item + (e.shiftKey ? -1 : 1) + S.student.items.length) % S.student.items.length); }
  else if (e.key === "j") next(1);
  else if (e.key === "k") next(-1);
  else if (e.key === "r") runR();
  else if (e.key === "i") askAI();
  else if (e.key === "c") buildComment();
});

init().catch((e) => ($("#list").innerHTML = `<p class="bad">${esc(e.message)}</p>`));
