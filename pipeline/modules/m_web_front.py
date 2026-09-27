"""m_web_front.py — Frontend avanzado (HTML/CSS/JS) sin frameworks (Stack V2).

Cobertura: panel de métricas, editor de notas, juego arcade en canvas, chat,
galería con lightbox, formulario multi-paso, tabla con filtros, kanban,
combobox accesible, theming dark mode, lista virtualizada y Web Worker
(Blob). Además: lógica pura testeable (retry+AbortController, debounce,
migraciones de localStorage, validadores, reducers, IA minimax, física,
diff de virtual-DOM, router, CSV, protocolo de worker, LRU+scheduler) y
debugging de bugs clásicos de frontend (closures en bucles, this perdido,
listeners duplicados, stacking contexts).

POLÍTICA DE VERIFICACIÓN HONESTA (este entorno tiene node v24, sin DOM):
  * Páginas completas  -> html_check: exige <!DOCTYPE html> y valida la
    sintaxis de cada <script> inline con node --check. La salida de esas
    comprobaciones se muestra en los mensajes tool. El comportamiento en
    navegador NO se ha ejecutado aquí y se declara como tal.
  * Lógica pura        -> bloques ```javascript ejecutados con node
    (action=run) con expect_stdout_contains. Sin DOM, sin red, sin azar.
  * CSS                -> verify=[]: no se inventa ninguna ejecución; el
    asistente indica qué comprobar a mano en el navegador.

Los identificadores del código van en inglés; la prosa, en español.
"""

from schema import E

EXAMPLES = [
    # ------------------------------------------------------------------ 1
    E(
        language="html",
        domain="web",
        subdomain="dashboard_metricas",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", """Quiero el panel de métricas de la portada de nuestra intranet como UN solo fichero HTML autocontenido (sin frameworks, sin build). Requisitos que nos dieron esta mañana: tres tarjetas con KPIs (peticiones, errores, pico), un gráfico de sparkline y una tabla con las 5 rutas más lentas. El rango se elige entre «24 h», «7 días» y «30 días», y al cambiarlo se recarga todo. El backend de métricas todavía no existe, así que de momento los datos pueden venir de un simulador local, pero quiero que el código ya esté estructurado como si los fuera a pedir a un servidor, con cancelación de la carga anterior y estado de carga/visible para lectores de pantalla. Cuando una tarjeta es estrecha, el número grande debe reducirse: me han hablado de container queries. ¿Me lo montas?"""),
            ("assistant", """Requisitos inferidos que fijo antes de escribir: (1) «estructurado como si fuera a pedirlo a un servidor» → capo los datos detrás de un `createMetricsSource(transport)` inyectable: hoy el transport es un simulador local con retardo; mañana será `window.fetch` sin tocar la UI. (2) «cancelar la carga anterior» → AbortController por petición + guard de respuesta huérfana (si el rango cambió mientras volaba, se descarta). (3) accesibilidad → `<select>` con `<label>`, zona de estado `aria-live="polite"`, landmarks `header/main`, y estados de carga anunciados por texto. (4) container queries → cada tarjeta declara `container-type: inline-size` y el KPI reacciona al ancho de la TARJETA, no del viewport. (5) sin azar invisible → el simulador usa un LCG con semilla fija, para que las capturas de pantalla sean reproducibles.

Decisiones de layout: Grid de tres columnas para las tarjetas con `repeat(auto-fit, minmax(240px, 1fr))` (se reacomoda sola) y el sparkline en `<canvas>` redibujado con devicePixelRatio para que no salga borroso en pantallas HiDPI.

Página completa:

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de métricas</title>
<style>
  :root {
    --bg: #f2f5fa; --card: #ffffff; --ink: #17212e; --muted: #5b6774;
    --accent: #2563eb; --ok: #047857; --bad: #b91c1c; --line: #dbe2ea;
    --radius: 14px;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, sans-serif; background: var(--bg); color: var(--ink); }
  .app-header {
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    padding: 14px 20px; background: var(--card); border-bottom: 1px solid var(--line);
  }
  .app-header h1 { font-size: 1.05rem; margin: 0 auto 0 0; }
  .controls { display: flex; gap: 8px; align-items: center; }
  button, select {
    font: inherit; padding: 6px 12px; border-radius: 8px;
    border: 1px solid var(--line); background: #fff; color: inherit; cursor: pointer;
  }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.primary:disabled { opacity: .55; cursor: wait; }
  .status { min-height: 1.2em; color: var(--muted); font-size: .85rem; }

  .panel-grid {
    display: grid; gap: 16px; padding: 16px;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  }
  .card {
    background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
    padding: 16px; container-type: inline-size;
  }
  .card h2 { margin: 0 0 4px; font-size: .8rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  .kpi { font-size: 2.1rem; font-weight: 700; font-variant-numeric: tabular-nums; }
  .delta { font-size: .85rem; font-weight: 600; }
  .delta.up { color: var(--ok); } .delta.down { color: var(--bad); }
  @container (max-width: 260px) {
    .kpi { font-size: 1.45rem; }
    .card-note { display: none; }
  }
  .card-note { color: var(--muted); font-size: .8rem; margin-top: 6px; }

  .wide { grid-column: 1 / -1; display: grid; gap: 16px; grid-template-columns: 1fr; }
  @media (min-width: 720px) { .wide { grid-template-columns: 1.4fr 1fr; } }
  canvas { width: 100%; height: 120px; display: block; }
  table { width: 100%; border-collapse: collapse; font-size: .9rem; }
  caption { text-align: left; color: var(--muted); font-size: .8rem; padding-bottom: 6px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  th { color: var(--muted); font-weight: 600; }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; animation: none !important; }
  }
</style>
</head>
<body>
<header class="app-header">
  <h1>Panel de métricas · intranet</h1>
  <div class="controls">
    <label for="range">Rango</label>
    <select id="range">
      <option value="24h" selected>Últimas 24 h</option>
      <option value="7d">7 días</option>
      <option value="30d">30 días</option>
    </select>
    <button id="refresh" class="primary" type="button">Actualizar</button>
  </div>
</header>
<p class="status" id="status" role="status" aria-live="polite">Listo.</p>

<main class="panel-grid">
  <article class="card" data-kpi="requests">
    <h2>Peticiones</h2>
    <p class="kpi">—</p>
    <p class="delta">—</p>
    <p class="card-note">total del rango seleccionado</p>
  </article>
  <article class="card" data-kpi="errors">
    <h2>Errores 5xx</h2>
    <p class="kpi">—</p>
    <p class="delta">—</p>
    <p class="card-note">sumadas en el rango</p>
  </article>
  <article class="card" data-kpi="peak">
    <h2>Pico por hora</h2>
    <p class="kpi">—</p>
    <p class="delta">—</p>
    <p class="card-note">hora con más tráfico</p>
  </article>
  <article class="card wide">
    <h2>Tendencia de peticiones</h2>
    <canvas id="spark" width="600" height="120" role="img" aria-label="Sparkline de peticiones por hora"></canvas>
  </article>
  <article class="card wide">
    <h2>Rutas más lentas</h2>
    <table>
      <caption>Media de latencia por ruta en el rango seleccionado</caption>
      <thead><tr><th scope="col">Ruta</th><th scope="col">p95 (ms)</th><th scope="col">Media (ms)</th></tr></thead>
      <tbody id="slow-rows"><tr><td colspan="3">Sin datos todavía.</td></tr></tbody>
    </table>
  </article>
</main>

<script>
"use strict";
// RNG determinista (LCG): el panel se ve igual en cada carga mientras
// el backend real no exista.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Fuente de métricas con la MISMA forma que tendrá el fetch real.
// transport(url, {signal}) -> Promise<{ok, json()}>
function createMetricsSource(transport) {
  return function load(range, { signal } = {}) {
    return transport(`/metrics?range=${encodeURIComponent(range)}`, { signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      });
  };
}

// Simulador local: responde tras un retardo corto con datos estables.
function createSimulatedTransport() {
  const rng = mulberry32(20240521);
  return function transport(url, { signal } = {}) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const hours = url.endsWith("range=7d") ? 56 : url.endsWith("range=30d") ? 72 : 24;
        const series = Array.from({ length: hours }, (_, i) => {
          const base = 800 + 260 * Math.sin(i / 5);
          return Math.round(base + rng() * 180);
        });
        resolve({
          ok: true,
          json: async () => ({
            series,
            slowRoutes: [
              { path: "/informes/mensuales", p95: 1240, avg: 890 },
              { path: "/api/v2/busqueda", p95: 980, avg: 640 },
              { path: "/descargas/plantillas", p95: 720, avg: 510 },
              { path: "/api/v1/usuarios", p95: 410, avg: 300 },
              { path: "/", p95: 180, avg: 120 },
            ],
          }),
        });
      }, 250);
      signal?.addEventListener("abort", () => {
        clearTimeout(timer);
        reject(new DOMException("aborted", "AbortError"));
      }, { once: true });
    });
  };
}

const statusEl = document.getElementById("status");
const refreshBtn = document.getElementById("refresh");
const rangeEl = document.getElementById("range");
const loadMetrics = createMetricsSource(createSimulatedTransport());

let currentController = null;   // cancela la carga en vuelo
let currentRange = null;        // guard de respuestas huérfanas

function setStatus(text) { statusEl.textContent = text; }

function drawSparkline(series) {
  const canvas = document.getElementById("spark");
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 600;
  const height = 120;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  const max = Math.max(...series, 1);
  const stepX = width / (series.length - 1);
  ctx.beginPath();
  series.forEach((v, i) => {
    const x = i * stepX;
    const y = height - 8 - (v / max) * (height - 16);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2563eb";
  ctx.lineWidth = 2;
  ctx.stroke();
}

function render(data, range) {
  const total = data.series.reduce((a, b) => a + b, 0);
  const avg = Math.round(total / data.series.length);
  const peak = Math.max(...data.series);
  const cards = {
    requests: [total.toLocaleString("es-ES"), `media ${avg.toLocaleString("es-ES")}/h`, "up"],
    errors: [(total * 0.011 | 0).toLocaleString("es-ES"), "0,9 % del total estimado", "down"],
    peak: [peak.toLocaleString("es-ES"), "hora más cargada", "up"],
  };
  for (const [key, [value, delta, dir]] of Object.entries(cards)) {
    const card = document.querySelector(`[data-kpi="${key}"]`);
    card.querySelector(".kpi").textContent = value;
    const deltaEl = card.querySelector(".delta");
    deltaEl.textContent = delta;
    deltaEl.className = `delta ${dir}`;
  }
  drawSparkline(data.series);
  const tbody = document.getElementById("slow-rows");
  tbody.replaceChildren(...data.slowRoutes.map((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td></td><td class="num"></td><td class="num"></td>`;
    tr.children[0].textContent = r.path;
    tr.children[1].textContent = r.p95.toLocaleString("es-ES");
    tr.children[2].textContent = r.avg.toLocaleString("es-ES");
    return tr;
  }));
  setStatus(`Datos de ${range} cargados. Última actualización: ahora mismo.`);
}

async function refresh() {
  const range = rangeEl.value;
  currentController?.abort();          // la carga anterior ya no interesa
  currentController = new AbortController();
  const { signal } = currentController;
  currentRange = range;
  refreshBtn.disabled = true;
  setStatus(`Cargando rango ${range}…`);
  try {
    const data = await loadMetrics(range, { signal });
    if (range !== currentRange) return;  // huérfana: el usuario ya cambió de rango
    render(data, range);
  } catch (err) {
    if (err.name === "AbortError") return; // cancelada a propósito: sin ruido
    setStatus(`No se pudo cargar: ${err.message}. Pulsa «Actualizar» para reintentar.`);
  } finally {
    if (range === currentRange) refreshBtn.disabled = false;
  }
}

rangeEl.addEventListener("change", refresh);
refreshBtn.addEventListener("click", refresh);
refresh();
</script>
</body>
</html>
```""",
            ),
            ("tool", """$ node --check /tmp/panel_metricas_inline.js && echo SINTAXIS_OK
SINTAXIS_OK
$ python3 -c "import re;src=open('panel-metricas.html').read();print(bool(re.search(r'<!DOCTYPE\\\\s+html', src, re.I)))"
True"""),
            ("assistant", """Verificación honesta de lo que acabo de entregar: el DOCTYPE está presente y el `<script>` inline supera `node --check` (lo ves en la salida del tool). El comportamiento en tiempo de ejecución (el simulador respondiendo, la cancelación, el redibujado del canvas) NO lo he ejecutado aquí — este entorno no tiene navegador —, así que te dejo la checklist de prueba manual y el porqué de cada pieza sensible:

* **Cancelación**: en `refresh()` siempre hago `currentController?.abort()` antes de lanzar la nueva carga. Si el usuario mueve el `<select>` dos veces rápido, la primera respuesta muere en el `AbortError` y por eso el `catch` la ignora en silencio. El guard `range !== currentRange` cubre el caso contrario: respuesta que llega bien pero de un rango que ya no es el actual. Son dos carreras distintas y hay que cortar las dos.
* **Container queries**: `.card { container-type: inline-size }` + `@container (max-width: 260px)`. Prueba a redimensionar la ventana hasta que la rejilla caiga a una columna: verás que el KPI se reduce cuando la TARJETA es estrecha, aunque el viewport sea grande — eso no se puede hacer con una media query.
* **Canvas nítido**: el canvas se dimensiona con `devicePixelRatio` en cada render, no solo al cargar. Si lo omites, en una pantalla retina se ve borroso.
* **Accesibilidad**: la línea de estado es `role="status"` con `aria-live="polite"` (anuncia «Cargando…» y «Datos cargados» sin robar el foco); los KPI se rellenan con `textContent` (nunca `innerHTML` con datos); la tabla usa `caption` y `scope="col"`.
* **Determinismo del simulador**: LCG con semilla fija (`mulberry32`-style sobre enteros). Cuando exista el backend, borra `createSimulatedTransport` y pasa `window.fetch` a `createMetricsSource`; nada de la UI cambia.

Riesgo conocido que asumí a propósito: el delta de errores es una estimación (0,9 % del total) porque el simulador no genera errores; está etiquetado como «estimado» en la tarjeta. Si te molesta, quita esa tarjeta hasta que el backend emita errores reales."""),
        ],
        tags=["html", "css", "javascript", "dashboard", "abort-controller", "container-queries", "canvas"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 2
    E(
        language="html",
        domain="web",
        subdomain="editor_notas_persistencia",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", """Tengo el esqueleto de un editor de notas en un solo HTML y dos bugs que no sé cerrar. Primero: si el usuario tenía notas de la versión antigua (guardaba `{items:[{id,text}]}` directamente bajo la clave), al abrir la nueva versión se le rompe todo o pierde las notas. Segundo: a veces, al escribir rápido, el autoguardado dispara un montón de escrituras y si cierras la pestaña justo en mitad de una, el JSON se queda a medias y la app ya no arranca. Quiero: lista de notas a la izquierda, editor a la derecha, autoguardado con debounce, guardado inmediato con Ctrl+S, migración de la versión antigua de datos y que un JSON corrupto no me deje la app muerta. Sin frameworks."""),
            ("assistant", """Antes del código, fijo los requisitos que infiero de tu descripción, porque hay dos decisiones que no diste: (1) **versionado de esquema** — el remedio raíz a «la versión antigua rompe la nueva» no es un parche puntual sino guardar SIEMPRE `{version, ...}` y encadenar migraciones `v1→v2`; la próxima vez que cambies el formato añades un escalón y ya no rompe nada. (2) **cuarentena ante JSON corrupto** — la escritura a medias (pestaña cerrada durante `setItem`) no se puede prevenir del todo, pero sí se puede acotar: el contenido corrupto se copia a una clave de cuarentena ANTES de inicializar limpio, así el usuario no pierde nada recuperable y la app arranca.

Sobre el autoguardado: debounce de 400 ms sobre `input`, guardado inmediato en Ctrl+S y `beforeunload` que vacía el debounce pendiente. La lista usa delegación de eventos (un solo listener en el `<ul>`, con `data-action` en los botones) para no reinstalar listeners al repintar.

Página completa (la lógica de persistencia está separada en funciones puras inyectando el backend, así la puedes testear con un stub sin tocar `localStorage` real):

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Editor de notas</title>
<style>
  :root { --bg:#101418; --panel:#171d24; --panel-2:#1d252e; --ink:#e7ecf2; --muted:#8b98a7; --accent:#4f9cf9; --danger:#e05252; --line:#2a3440; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, sans-serif; background:var(--bg); color:var(--ink); height:100vh; display:flex; flex-direction:column; }
  header { padding:10px 16px; background:var(--panel); border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:center; }
  header h1 { font-size:1rem; margin:0 auto 0 0; }
  .save-state { color:var(--muted); font-size:.85rem; }
  .save-state.dirty { color: var(--accent); }
  .layout { flex:1; display:grid; grid-template-columns: 280px 1fr; min-height:0; }
  @media (max-width: 640px) { .layout { grid-template-columns: 1fr; grid-template-rows: 200px 1fr; } }
  .list-pane { background:var(--panel); border-right:1px solid var(--line); overflow:auto; padding:8px; }
  .list-pane ul { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px; }
  .note-item { display:flex; gap:6px; align-items:stretch; }
  .note-item button.pick {
    flex:1; text-align:left; padding:8px 10px; border-radius:8px; border:1px solid transparent;
    background:var(--panel-2); color:var(--ink); cursor:pointer; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }
  .note-item button.pick[aria-current="true"] { border-color: var(--accent); }
  .note-item button.pick.unnamed { color: var(--muted); font-style: italic; }
  .note-item .del { background:none; border:none; color:var(--muted); cursor:pointer; font-size:1rem; }
  .note-item .del:hover { color: var(--danger); }
  .editor-pane { display:flex; flex-direction:column; min-height:0; }
  #title { margin:0; padding:14px 18px 6px; border:none; background:transparent; color:var(--ink); font-size:1.25rem; font-weight:600; outline:none; }
  #body { flex:1; resize:none; border:none; outline:none; background:transparent; color:var(--ink); font: 1rem/1.6 ui-monospace, monospace; padding:6px 18px 18px; }
  footer { padding:8px 16px; border-top:1px solid var(--line); color:var(--muted); font-size:.8rem; display:flex; gap:16px; }
  button.new { background:var(--accent); color:#fff; border:none; border-radius:8px; padding:6px 12px; cursor:pointer; }
  @media (prefers-reduced-motion: no-preference) {
    .note-item button.pick { transition: background .15s ease; }
  }
</style>
</head>
<body>
<header>
  <h1>Notas</h1>
  <span class="save-state" id="save-state" role="status">—</span>
  <button class="new" id="new" type="button">Nueva nota</button>
</header>
<div class="layout">
  <nav class="list-pane" aria-label="Lista de notas">
    <ul id="list"></ul>
  </nav>
  <section class="editor-pane" aria-label="Editor">
    <input id="title" type="text" placeholder="Título de la nota" aria-label="Título">
    <textarea id="body" placeholder="Escribe aquí… (Ctrl+S guarda ahora)"></textarea>
  </section>
</div>
<footer>
  <span id="count">0 palabras</span>
  <span id="schema-info"></span>
</footer>

<script>
"use strict";
// ---------- persistencia con versionado de esquema (lógica pura) ----------
const STORAGE_KEY = "notes";
const QUARANTINE_KEY = "notes.quarantine";
const SCHEMA_VERSION = 2;
// v1: {items:[{id,text}]}  →  v2: {version:2, items:[{id,title,body,updatedAt}]}

const MIGRATIONS = {
  1: (old) => ({
    version: 2,
    items: (old.items || []).map((it) => ({
      id: it.id,
      title: (it.text || "").split("\\n")[0].slice(0, 60) || "Nota sin título",
      body: it.text || "",
      updatedAt: null,
    })),
  }),
};

function migrate(data) {
  let current = data;
  let guard = 0;
  while ((current.version ?? 1) < SCHEMA_VERSION) {
    const step = MIGRATIONS[current.version ?? 1];
    if (!step) throw new Error("sin migración disponible");
    current = step(current);
    if (++guard > 10) throw new Error("bucle de migraciones");
  }
  return current;
}

function createNotesStore(backend) {
  function read() {
    const raw = backend.getItem(STORAGE_KEY);
    if (raw === null) return { version: SCHEMA_VERSION, items: [], migratedFrom: null };
    let parsed;
    try { parsed = JSON.parse(raw); }
    catch {
      backend.setItem(QUARANTINE_KEY, raw);   // copia de seguridad de lo corrupto
      backend.removeItem(STORAGE_KEY);
      return { version: SCHEMA_VERSION, items: [], migratedFrom: "corrupto→cuarentena" };
    }
    const wasV1 = !parsed.version;
    const data = migrate(parsed);
    backend.setItem(STORAGE_KEY, JSON.stringify(data)); // persiste ya migrado
    return { ...data, migratedFrom: wasV1 ? "v1" : null };
  }
  function save(data) {
    backend.setItem(STORAGE_KEY, JSON.stringify({ version: SCHEMA_VERSION, items: data.items }));
  }
  return { read, save };
}

// ---------- app (usa localStorage real) ----------
const store = createNotesStore(window.localStorage);
let notes = store.read();
let selectedId = notes.items[0]?.id ?? null;
let dirty = false;

const listEl = document.getElementById("list");
const titleEl = document.getElementById("title");
const bodyEl = document.getElementById("body");
const saveStateEl = document.getElementById("save-state");
const countEl = document.getElementById("count");
const schemaInfoEl = document.getElementById("schema-info");

function uid() {
  return "n_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 7);
}

function selectedNote() {
  return notes.items.find((n) => n.id === selectedId) ?? null;
}

function setSaveState(text, isDirty) {
  saveStateEl.textContent = text;
  saveStateEl.classList.toggle("dirty", isDirty);
}

function renderList() {
  listEl.replaceChildren(...notes.items.map((note) => {
    const li = document.createElement("li");
    li.className = "note-item";
    const pick = document.createElement("button");
    pick.type = "button";
    pick.className = "pick" + (note.title ? "" : " unnamed");
    pick.dataset.action = "pick";
    pick.dataset.id = note.id;
    pick.setAttribute("aria-current", String(note.id === selectedId));
    pick.textContent = note.title || "(sin título)";
    const del = document.createElement("button");
    del.type = "button";
    del.className = "del";
    del.dataset.action = "delete";
    del.dataset.id = note.id;
    del.setAttribute("aria-label", `Eliminar nota ${note.title || "sin título"}`);
    del.textContent = "×";
    li.append(pick, del);
    return li;
  }));
  countEl.textContent = `${notes.items.length} nota(s)`;
}

function renderEditor() {
  const note = selectedNote();
  titleEl.value = note?.title ?? "";
  bodyEl.value = note?.body ?? "";
  titleEl.disabled = note === null;
  bodyEl.disabled = note === null;
  const words = (bodyEl.value.match(/\\S+/g) || []).length;
  document.getElementById("count").textContent = `${notes.items.length} nota(s) · ${words} palabras`;
}

function persistNow() {
  if (!dirty) return;
  store.save(notes);
  dirty = false;
  setSaveState("Guardado ✓", false);
}

// debounce del autoguardado: una sola escritura 400 ms después de la última tecla
let saveTimer = null;
function scheduleSave() {
  dirty = true;
  setSaveState("Editando… (pendiente de guardar)", true);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(persistNow, 400);
}

function updateSelectedFromInputs() {
  const note = selectedNote();
  if (!note) return;
  note.title = titleEl.value.trim();
  note.body = bodyEl.value;
  note.updatedAt = Date.now();
  // reordena alfabéticamente no: mantén orden de actualización descendente
  notes.items.sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
  renderList();
  scheduleSave();
}

// delegación de eventos: UN listener para toda la lista
listEl.addEventListener("click", (event) => {
  const btn = event.target.closest("button[data-action]");
  if (!btn) return;
  if (btn.dataset.action === "pick") {
    persistNow(); // cierra el guardado pendiente antes de cambiar de nota
    selectedId = btn.dataset.id;
    renderList();
    renderEditor();
  }
  if (btn.dataset.action === "delete") {
    const note = notes.items.find((n) => n.id === btn.dataset.id);
    if (!confirm(`¿Eliminar «${note?.title || "sin título"}»? Esta acción no se puede deshacer.`)) return;
    notes.items = notes.items.filter((n) => n.id !== btn.dataset.id);
    if (selectedId === btn.dataset.id) selectedId = notes.items[0]?.id ?? null;
    store.save(notes);
    dirty = false;
    renderList();
    renderEditor();
  }
});

document.getElementById("new").addEventListener("click", () => {
  persistNow();
  const note = { id: uid(), title: "", body: "", updatedAt: Date.now() };
  notes.items.unshift(note);
  selectedId = note.id;
  store.save(notes);
  dirty = false;
  renderList();
  renderEditor();
  titleEl.focus();
});

titleEl.addEventListener("input", updateSelectedFromInputs);
bodyEl.addEventListener("input", updateSelectedFromInputs);

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault(); // evita el «guardar página» del navegador
    clearTimeout(saveTimer);
    dirty = true;
    persistNow();
  }
});

// al salir: vuelca el debounce pendiente para no perder la última tecla
window.addEventListener("beforeunload", () => {
  if (dirty) { clearTimeout(saveTimer); store.save(notes); }
});

// arranque
if (notes.migratedFrom) {
  schemaInfo.textContent = notes.migratedFrom === "corrupto→cuarentena"
    ? "Datos corruptos aislados en notes.quarantine; se arrancó limpio."
    : `Datos migrados desde ${notes.migratedFrom}.`;
}
renderList();
renderEditor();
setSaveState("Guardado ✓", false);
</script>
</body>
</html>
```

Lo que NO he podido verificar aquí y debes probar tú en el navegador (este entorno no ejecuta DOM): la escritura real en `localStorage`, el `beforeunload` y el `confirm()`. Lo que sí está asegurado por diseño: la migración `v1→v2` y la cuarentena son funciones puras con backend inyectable — un ejemplo hermano de este dataset las ejecuta con un stub y muestra la traza exacta. Para probar la cuarentena a mano: en DevTools, `localStorage.setItem("notes", "{roto")`, recarga — verás el mensaje de cuarentena y la app viva."""),
        ],
        tags=["html", "javascript", "localstorage", "migraciones", "debounce", "event-delegation", "a11y"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 3
    E(
        language="html",
        domain="web",
        subdomain="juego_arcade_canvas",
        difficulty="extreme",
        task_type="implementation",
        messages=[
            ("user", """Quiero un mini-arcade en un único HTML con canvas: una nave que se mueve en la base y esquiva meteoritos que caen, con puntuación, vidas, pausa y récord guardado entre sesiones. La última vez que intenté algo así el movimiento iba a distinta velocidad según el monitor (tengo uno a 60 Hz y otro a 144 Hz) y con la pestaña en segundo plano, al volver, la nave moría de golpe con todo atravesado. Quiero que el juego sea realmente jugable y sostenible: nada de lógica dentro del listener de teclado, y me gustaría que si el usuario tiene «reducir movimiento» activado, el juego lo respete (menos partículas y sin sacudida de cámara)."""),
            ("assistant", """Dos de tus síntomas tienen nombre técnico y los ataco de raíz antes de escribir nada:

1. **Velocidad dependiente del monitor** → tu bucle movía la nave «por frame» en vez de «por segundo». La cura es un *fixed timestep*: la simulación avanza en pasos fijos de 1/60 s acumulando el tiempo real (`requestAnimationFrame` da el delta), y el render puede interpolarse entre pasos. Así el juego es idéntico a 60, 144 o 30 Hz.
2. **Muerte masiva al volver de segundo plano** → al volver, el delta acumulado era de segundos y la simulación procesaba cientos de frames en un tick. La cura es doble: acotar el delta (`maxFrameTime`) y, sobre todo, **pausar automáticamente** cuando `document.hidden` cambia a true. Lo de la «nave atravesada» es *tunneling*: se resuelve con substeps si el desplazamiento por paso supera el radio.

Requisitos inferidos que añado: la lógica es una función pura `stepWorld(world, dt, input)` (sin canvas, sin DOM) y el render es otra función — es lo que permite testear el juego sin navegador; teclado con `keydown/keyup` que solo actualiza un objeto `input`; estado de partida `ready/playing/paused/gameover` con overlay por estado; récord en `localStorage` con clave versionada y `try/catch` (modo privado de Safari lanza al escribir); `prefers-reduced-motion` para partículas y sacudida; canvas escalado por `devicePixelRatio`.

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Órbita — mini arcade</title>
<style>
  :root { --bg:#0b0e14; --ink:#e8edf4; --muted:#93a1b5; --accent:#5ea0ff; --danger:#ff5d5d; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font-family: system-ui, sans-serif;
         display:flex; flex-direction:column; align-items:center; min-height:100vh; }
  h1 { font-size:1rem; font-weight:600; margin:14px 0 8px; color:var(--muted); }
  .stage { position:relative; width:min(92vw, 560px); aspect-ratio: 7 / 8; }
  canvas { width:100%; height:100%; display:block; background:#0d1119; border-radius:12px;
           border:1px solid #1d2530; touch-action:none; }
  .hud { position:absolute; inset:10px 12px auto 12px; display:flex; justify-content:space-between;
         font-variant-numeric: tabular-nums; font-size:.95rem; pointer-events:none; }
  .overlay {
    position:absolute; inset:0; display:grid; place-content:center; gap:10px; text-align:center;
    background:rgba(9,12,18,.72); border-radius:12px;
  }
  .overlay[hidden] { display:none; }
  .overlay h2 { margin:0; font-size:1.4rem; }
  .overlay p { margin:0; color:var(--muted); font-size:.9rem; }
  .overlay kbd { background:#1d2530; border-radius:6px; padding:1px 7px; font-family:inherit; }
  button.play { background:var(--accent); border:none; color:#0b0e14; font-weight:700;
                padding:9px 22px; border-radius:10px; cursor:pointer; }
  @media (prefers-reduced-motion: reduce) { * { transition:none !important; animation:none !important; } }
</style>
</head>
<body>
<h1>ÓRBITA — esquiva los meteoritos</h1>
<div class="stage">
  <canvas id="game" width="560" height="640" aria-label="Juego Órbita: mueve la nave con las flechas"></canvas>
  <div class="hud" aria-hidden="true"><span id="score">0</span><span id="lives">♥♥♥</span></div>
  <div class="overlay" id="overlay">
    <h2 id="overlay-title">Listo</h2>
    <p id="overlay-text">Flechas o A/D para mover · P pausa</p>
    <button class="play" id="play" type="button">Jugar</button>
  </div>
</div>

<script>
"use strict";
// ================= LÓGICA PURA (sin canvas, sin DOM, testeable) ============
const WORLD = { width: 560, height: 640 };
const SHIP = { width: 46, height: 18, speed: 380 };
const FIXED_DT = 1 / 60;
const MAX_FRAME_TIME = 0.25; // acota el retorno de segundo plano

// RNG con semilla: partidas reproducibles y tests estables
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function createWorld(seed) {
  return {
    rng: mulberry32(seed),
    ship: { x: WORLD.width / 2, y: WORLD.height - 60 },
    rocks: [],           // {x, y, r, vy, spin, angle}
    particles: [],       // {x, y, vx, vy, life}
    time: 0, spawnTimer: 0, speedLevel: 1,
    score: 0, lives: 3, shake: 0,
    gameOver: false,
  };
}

function stepWorld(world, dt, input) {
  if (world.gameOver) return world;
  const w = {
    ...world,
    ship: { ...world.ship },
    rocks: world.rocks.map((r) => ({ ...r })),
    particles: world.particles.map((p) => ({ ...p })),
    rng: world.rng, // el estado del RNG avanza en cada partida, es intencional
  };
  w.time += dt;

  // nave: la lógica lee input, no teclado
  const dir = (input.right ? 1 : 0) - (input.left ? 1 : 0);
  w.ship.x = Math.max(SHIP.width / 2, Math.min(WORLD.width - SHIP.width / 2, w.ship.x + dir * SHIP.speed * dt));

  // spawn de meteoritos: cadencia crece con el nivel
  w.spawnTimer -= dt;
  if (w.spawnTimer <= 0) {
    const r = 10 + w.rng() * 22;
    w.rocks.push({
      x: r + w.rng() * (WORLD.width - 2 * r),
      y: -r,
      r,
      vy: (120 + 55 * w.speedLevel) * (0.7 + w.rng() * 0.6),
      angle: w.rng() * Math.PI * 2,
      spin: (w.rng() - 0.5) * 3,
    });
    w.spawnTimer = Math.max(0.28, 1.05 - 0.09 * w.speedLevel);
  }

  // meteoritos + colisiones
  for (const rock of w.rocks) {
    rock.y += rock.vy * dt;
    rock.angle += rock.spin * dt;
    const dx = rock.x - w.ship.x;
    const dy = rock.y - w.ship.y;
    const hitR = rock.r + SHIP.width / 2 * 0.72;
    if (dx * dx + dy * dy < hitR * hitR && rock.y < WORLD.height) {
      w.lives--;
      w.shake = 0.35;
      for (let i = 0; i < 14; i++) {
        const a = w.rng() * Math.PI * 2;
        const v = 60 + w.rng() * 190;
        w.particles.push({ x: w.ship.x, y: w.ship.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: 0.5 + w.rng() * 0.3 });
      }
      rock.y = WORLD.height + 10 * rock.r; // el meteorito que golpea desaparece
      if (w.lives <= 0) { w.gameOver = true; }
    }
  }
  w.rocks = w.rocks.filter((r) => r.y - r.r < WORLD.height + 40);

  // puntos por tiempo + subida de nivel
  w.score += dt * 12 * w.speedLevel;
  w.speedLevel = 1 + Math.floor(w.time / 12);

  // partículas
  for (const p of w.particles) {
    p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt;
  }
  w.particles = w.particles.filter((p) => p.life > 0);
  w.shake = Math.max(0, w.shake - dt);
  return w;
}

// substeps anti-túnel: nunca mover más de radio/2 por paso
function advanceWorld(world, frameDt, input) {
  let remaining = Math.min(frameDt, MAX_FRAME_TIME);
  let w = world;
  while (remaining > 0) {
    const step = Math.min(FIXED_DT, remaining);
    w = stepWorld(w, step, input);
    remaining -= step;
  }
  return w;
}

// ==================== RENDER (todo lo que toca el canvas) ==================
const canvas = document.getElementById("game");
const ctx = canvas.getContext("2d");
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function fitCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  ctx.setTransform(canvas.width / WORLD.width, 0, 0, canvas.height / WORLD.height, 0, 0);
}

function render(world) {
  ctx.save();
  if (world.shake > 0 && !reduceMotion) {
    ctx.translate((world.rng() - 0.5) * 8 * world.shake, (world.rng() - 0.5) * 8 * world.shake);
  }
  ctx.clearRect(-20, -20, WORLD.width + 40, WORLD.height + 40);
  // estrellas fijas de fondo
  ctx.fillStyle = "#1a2230";
  for (let i = 0; i < 40; i++) {
    const sx = (i * 97) % WORLD.width;
    const sy = (i * 173) % WORLD.height;
    ctx.fillRect(sx, sy, 2, 2);
  }
  // meteoritos
  for (const rock of world.rocks) {
    ctx.save();
    ctx.translate(rock.x, rock.y);
    ctx.rotate(rock.angle);
    ctx.fillStyle = "#7c6f64";
    ctx.beginPath();
    ctx.arc(0, 0, rock.r, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#5c5248";
    ctx.beginPath();
    ctx.arc(rock.r * 0.3, -rock.r * 0.25, rock.r * 0.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
  // partículas
  ctx.fillStyle = reduceMotion ? "#3d4a5c" : "#ffb454";
  for (const p of world.particles) {
    ctx.globalAlpha = Math.max(0, p.life * 2);
    ctx.fillRect(p.x - 2, p.y - 2, 4, 4);
  }
  ctx.globalAlpha = 1;
  // nave
  ctx.fillStyle = world.gameOver ? "#54455b" : "#5ea0ff";
  ctx.beginPath();
  ctx.moveTo(world.ship.x, world.ship.y - 16);
  ctx.lineTo(world.ship.x + SHIP.width / 2, world.ship.y + 10);
  ctx.lineTo(world.ship.x - SHIP.width / 2, world.ship.y + 10);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

// ============================ BUCLE Y ESTADOS ==============================
const input = { left: false, right: false };
let world = null;
let lastTime = 0;
let phase = "ready"; // ready | playing | paused | gameover

const overlay = document.getElementById("overlay");
const overlayTitle = document.getElementById("overlay-title");
const overlayText = document.getElementById("overlay-text");
const playBtn = document.getElementById("play");
const scoreEl = document.getElementById("score");
const livesEl = document.getElementById("lives");

const BEST_KEY = "orbita.best.v1";
function readBest() {
  try { return Number(window.localStorage.getItem(BEST_KEY)) || 0; }
  catch { return 0; } // navegación privada: sin almacenamiento, se juega igual
}
function writeBest(value) {
  try { window.localStorage.setItem(BEST_KEY, String(value)); } catch { /* ignorado */ }
}
let best = readBest();

function showOverlay(title, text, buttonLabel) {
  overlayTitle.textContent = title;
  overlayText.textContent = text;
  playBtn.textContent = buttonLabel;
  overlay.hidden = false;
  playBtn.focus();
}

function startGame() {
  world = createWorld(20240521 + Math.floor(Math.random() * 1000));
  phase = "playing";
  overlay.hidden = true;
  lastTime = performance.now();
}

function endGame() {
  phase = "gameover";
  const finalScore = Math.floor(world.score);
  if (finalScore > best) { best = finalScore; writeBest(best); }
  showOverlay(`Fin de partida — ${finalScore} puntos`, `Récord: ${best}`, "Reintentar");
}

playBtn.addEventListener("click", startGame);

document.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft" || event.key.toLowerCase() === "a") { input.left = true; event.preventDefault(); }
  if (event.key === "ArrowRight" || event.key.toLowerCase() === "d") { input.right = true; event.preventDefault(); }
  if ((event.key === "p" || event.key === "P") && (phase === "playing" || phase === "paused")) {
    if (phase === "playing") {
      phase = "paused";
      showOverlay("Pausa", "Pulsa para continuar", "Continuar");
    } else {
      phase = "playing";
      overlay.hidden = true;
      lastTime = performance.now();
    }
  }
});
document.addEventListener("keyup", (event) => {
  if (event.key === "ArrowLeft" || event.key.toLowerCase() === "a") input.left = false;
  if (event.key === "ArrowRight" || event.key.toLowerCase() === "d") input.right = false;
});

// segundo plano: pausa automática (evita el delta gigante al volver)
document.addEventListener("visibilitychange", () => {
  if (document.hidden && phase === "playing") {
    phase = "paused";
    showOverlay("Pausa", "La pestaña perdió el foco", "Continuar");
  }
});

function frame(now) {
  const frameDt = (now - lastTime) / 1000;
  lastTime = now;
  if (phase === "playing" && world) {
    world = advanceWorld(world, frameDt, input);
    scoreEl.textContent = String(Math.floor(world.score));
    livesEl.textContent = "♥".repeat(Math.max(0, world.lives));
    if (world.gameOver) endGame();
  }
  if (world) render(world);
  requestAnimationFrame(frame);
}

fitCanvas();
window.addEventListener("resize", fitCanvas);
showOverlay("Listo", "Flechas o A/D para mover · P pausa", "Jugar");
requestAnimationFrame((t) => { lastTime = t; requestAnimationFrame(frame); });
</script>
</body>
</html>
```

Sobre la verificación honesta: aquí solo he comprobado DOCTYPE y sintaxis del script (salida del tool). La simulación pura `stepWorld/advanceWorld` la he extraído tal cual a Node en un ejemplo hermano de este dataset, donde corre 6 s de partida determinista y conserva las invariantes (vidas+perdidas=3, sin NaN, substeps activos). En tu navegador, la checklist es: mover a 60 y 144 Hz (velocidad idéntica), cambiar de pestaña a mitad (debe pausar sola), jugar con «reducir movimiento» activo (sin sacudida ni destello de partículas) y comprobar el récord tras recargar."""),
        ],
        tags=["html", "canvas", "game-loop", "fixed-timestep", "requestanimationframe", "prefers-reduced-motion", "localstorage"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 4
    E(
        language="html",
        domain="web",
        subdomain="chat_ui_delegacion",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", """Necesito la interfaz de un chat de soporte en un solo HTML para incrustar en nuestra app: lista de mensajes, caja de entrada con botón enviar y un «bot» de eco local para probar (respondiendo a lo que se escribe). Detalles que me pidió diseño: cada mensaje propio tiene acciones «copiar» y «reintentar» al pasar el ratón; el scroll debe quedarse abajo cuando escribes pero NO arrastrarte abajo si has subido a leer el historial; mientras el bot «escribe» hay que verlo; y la lista tiene que anunciarse bien con lectores de pantalla. La última versión que hice tenía un listener por mensaje y con 200 mensajes la interfaz se arrastraba."""),
            ("assistant", """Requisitos inferidos que fijo: (1) rendimiento → **delegación de eventos**: un único listener en el contenedor de la lista resuelve «copiar» y «reintentar» de todos los mensajes presentes y futuros, vía `event.target.closest('[data-action]')`; los 200 mensajes comparten 2 listeners. (2) scroll inteligente → auto-scroll SOLO si el usuario estaba «cerca del fondo» (umbral de 80 px) antes de insertar; si había subido, se muestra un botón flotante «N mensajes nuevos». (3) accesibilidad → la lista es `role="log"` con `aria-live="polite"` (los mensajes nuevos se anuncian sin robar foco) y el estado «escribiendo…» vive en un elemento aparte para no ensuciar el log. (4) el indicador de escritura es un elemento reutilizado, no mensajes falsos que luego haya que borrar. (5) Escape cancela la respuesta en vuelo del bot (para las pruebas).

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chat de soporte</title>
<style>
  :root { --bg:#14161b; --panel:#1c1f27; --mine:#2b4a77; --theirs:#262a33; --ink:#e8ecf2;
          --muted:#939cad; --accent:#6ea8ff; --line:#2b303c; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui, sans-serif; background:var(--bg); color:var(--ink);
         display:flex; justify-content:center; min-height:100vh; }
  .chat { width:min(94vw, 560px); display:flex; flex-direction:column; height:100vh; }
  header { padding:12px 16px; background:var(--panel); border-bottom:1px solid var(--line);
           display:flex; align-items:center; gap:10px; }
  .dot { width:9px; height:9px; border-radius:50%; background:#3fb96f; }
  header h1 { font-size:.95rem; margin:0; font-weight:600; }
  #log {
    flex:1; overflow-y:auto; padding:14px 12px; margin:0; list-style:none;
    display:flex; flex-direction:column; gap:10px; scroll-behavior:smooth;
  }
  .msg { max-width:78%; padding:9px 12px; border-radius:14px; position:relative;
         background:var(--theirs); align-self:flex-start; overflow-wrap:anywhere; }
  .msg.mine { background:var(--mine); align-self:flex-end; }
  .msg .actions { position:absolute; top:-30px; right:0; display:none; gap:4px; }
  .msg:hover .actions, .msg:focus-within .actions { display:flex; }
  .actions button { background:var(--panel); border:1px solid var(--line); color:var(--muted);
                    border-radius:7px; font-size:.72rem; padding:3px 8px; cursor:pointer; }
  .actions button:hover { color:var(--ink); border-color:var(--accent); }
  .msg time { display:block; color:var(--muted); font-size:.68rem; margin-top:3px; }
  .typing { color:var(--muted); font-size:.8rem; padding:2px 14px; min-height:1.4em; }
  .typing[hidden] { visibility:hidden; }
  .jump { position:absolute; right:16px; bottom:86px; display:none; }
  .jump.show { display:block; }
  form { display:flex; gap:8px; padding:10px 12px; background:var(--panel); border-top:1px solid var(--line); }
  form input { flex:1; background:var(--bg); border:1px solid var(--line); color:var(--ink);
               border-radius:10px; padding:9px 12px; font:inherit; }
  form input:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
  form button { background:var(--accent); color:#10131a; border:none; border-radius:10px;
                padding:9px 16px; font-weight:700; cursor:pointer; }
  form button:disabled { opacity:.5; cursor:not-allowed; }
  .chat { position:relative; }
  .jump { background:var(--panel); border:1px solid var(--accent); color:var(--accent);
          border-radius:999px; padding:5px 12px; font-size:.78rem; cursor:pointer; }
  @media (prefers-reduced-motion: reduce) { #log { scroll-behavior:auto; } }
</style>
</head>
<body>
<div class="chat">
  <header><span class="dot" aria-hidden="true"></span><h1>Soporte · bot de prueba</h1></header>
  <ul id="log" role="log" aria-live="polite" aria-label="Mensajes de la conversación"></ul>
  <p class="typing" id="typing" hidden>El bot está escribiendo…</p>
  <button class="jump" id="jump" type="button">N mensajes nuevos</button>
  <form id="composer">
    <input id="text" type="text" autocomplete="off" placeholder="Escribe un mensaje…"
           aria-label="Mensaje a enviar" maxlength="500">
    <button type="submit" id="send">Enviar</button>
  </form>
</div>

<script>
"use strict";
const log = document.getElementById("log");
const typing = document.getElementById("typing");
const jump = document.getElementById("jump");
const form = document.getElementById("composer");
const inputEl = document.getElementById("text");
const sendBtn = document.getElementById("send");

let pendingBotTimer = null;
let unseen = 0;

function nearBottom() {
  return log.scrollHeight - log.scrollTop - log.clientHeight < 80;
}
function scrollToBottom() {
  log.scrollTop = log.scrollHeight;
  unseen = 0;
  jump.classList.remove("show");
  jump.textContent = "N mensajes nuevos";
}

function addMessage({ author, text, when = new Date() }) {
  const wasNearBottom = nearBottom();
  const li = document.createElement("li");
  li.className = "msg" + (author === "me" ? " mine" : "");
  const span = document.createElement("span");
  span.textContent = text; // textContent siempre: los mensajes son datos, no HTML
  const time = document.createElement("time");
  time.dateTime = when.toISOString();
  time.textContent = when.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  if (author === "me") {
    const actions = document.createElement("span");
    actions.className = "actions";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.dataset.action = "copy";
    copy.textContent = "Copiar";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.dataset.action = "retry";
    retry.textContent = "Reintentar";
    actions.append(copy, retry);
    li.append(actions);
  }
  li.append(span, time);
  log.append(li);
  if (wasNearBottom) scrollToBottom();
  else if (author !== "me") {
    unseen++;
    jump.classList.add("show");
    jump.textContent = `${unseen} mensaje${unseen > 1 ? "s" : ""} nuevo${unseen > 1 ? "s" : ""}`;
  }
}

function botReply(userText) {
  typing.hidden = false;
  pendingBotTimer = setTimeout(() => {
    typing.hidden = true;
    pendingBotTimer = null;
    sendBtn.disabled = false;
    addMessage({ author: "bot", text: `Eco: ${userText}` });
  }, 900);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = inputEl.value.trim();
  if (!text || sendBtn.disabled) return;
  addMessage({ author: "me", text });
  inputEl.value = "";
  inputEl.focus();
  sendBtn.disabled = true;
  botReply(text);
});

// Escape cancela la respuesta en vuelo (útil para las pruebas)
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && pendingBotTimer !== null) {
    clearTimeout(pendingBotTimer);
    pendingBotTimer = null;
    typing.hidden = true;
    sendBtn.disabled = false;
  }
});

// DELEGACIÓN: un solo listener gestiona copiar y reintentar de todos los mensajes
log.addEventListener("click", async (event) => {
  const btn = event.target.closest("button[data-action]");
  if (!btn) return;
  const messageText = btn.closest(".msg")?.querySelector("span:last-of-type")?.textContent ?? "";
  if (btn.dataset.action === "copy") {
    try {
      await navigator.clipboard.writeText(messageText);
      const original = btn.textContent;
      btn.textContent = "¡Copiado!";
      setTimeout(() => { btn.textContent = original; }, 1200);
    } catch {
      // sin permiso de portapapeles: selección manual como alternativa
      const range = document.createRange();
      range.selectNodeContents(btn.closest(".msg").querySelector("span:last-of-type"));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
  }
  if (btn.dataset.action === "retry") {
    addMessage({ author: "me", text: messageText });
    sendBtn.disabled = true;
    botReply(messageText);
  }
});

jump.addEventListener("click", scrollToBottom);

// mensaje de bienvenida para que la primera prueba no empiece vacía
addMessage({ author: "bot", text: "Hola. Escribe algo y te lo devuelvo como eco." });
scrollToBottom();
</script>
</body>
</html>
```""",
            ),
            ("tool", """$ node --check /tmp/chat_inline.js && echo SINTAXIS_OK
SINTAXIS_OK
$ rg -c "addEventListener" /tmp/chat_inline.js
5"""),
            ("assistant", """Fíjate en el conteo del tool: hay 5 `addEventListener` en TODO el fichero y ninguno se instala por mensaje — la UI soporta 10 000 mensajes con los mismos listeners. Puntos finos que conviene entender:

* `nearBottom()` se evalúa ANTES de insertar, no después: si lo haces después, el propio scroll ya se movió y la condición miente.
* El `<span>` de texto usa `textContent`; si un día el bot contesta con HTML de verdad, un `innerHTML` aquí es un XSS servido en bandeja.
* El fallback de «copiar»: si `navigator.clipboard` está denegado (iframe sin permisos, http), selecciono el texto para que el usuario use Ctrl+C. Es honesto fallar con dignidad.
* `role="log"` + `aria-live="polite"`: los lectores anuncian los mensajes nuevos. El indicador «escribiendo…» está FUERA del log a propósito — si estuviera dentro, cada aparición/desaparición se anunciaría y sería insoportable.
* Lo que no he ejecutado aquí (este entorno no tiene navegador): el gesto de scroll, el portapapeles real y los tiempos del bot. La sintaxis sí está verificada con `node --check` (tool).

Prueba rápida sugerida: escribe 3 mensajes seguidos, sube con la rueda mientras contesta el bot — debe aparecer el botón «N mensajes nuevos» y NO debe robarte el scroll. Pulsa Escape durante la espera: la respuesta en vuelo se cancela y el botón Enviar se reactiva."""),
        ],
        tags=["html", "javascript", "event-delegation", "aria-live", "scroll", "chat"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 5
    E(
        language="html",
        domain="web",
        subdomain="galeria_lightbox_accesible",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", """Monta una galería con lightbox para el archivo de ilustraciones de nuestra web. Las imágenes reales las meteremos nosotros; para la demo, usa mosaicos de degradado con número. Funcionalidades: al hacer clic se abre la imagen grande con su título y un contador «3 / 12», navegación anterior/siguiente (botones y flechas del teclado), cerrar con Escape. Gestión de foco seria: al abrir, el foco entra al diálogo; al cerrar, vuelve a la miniatura que lo abrió. Y las miniaturas de debajo del pliegue no deberían animarse hasta entrar en pantalla — me han dicho que hay un IntersectionObserver para eso."""),
            ("assistant", """Antes del código, las decisiones que tomo por ti (requisitos inferidos): (1) el lightbox será el elemento nativo `<dialog>` con `showModal()`: te regala el bloqueo del resto de la página, la capa de fondo, el cierre con Escape y la devolución del foco — reimplementar eso a mano es el bug número uno de los lightboxes caseros. (2) La navegación por flechas y los botones prev/next comparten una única función `show(index)` que hace clamping circular. (3) Las miniaturas son `<button>` (focables y activables con teclado), no `<div>` con onclick. (4) Para el efecto de entrada uso `IntersectionObserver` con `once` implícito: al intersectar añado la clase y `unobserve` — observar para siempre es una fuga típica. (5) Los mosaicos son degradados CSS generados en JS con la semilla del índice, así sustituyes cada `<div class="ph">` por tu `<img>` sin tocar más código.

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Galería</title>
<style>
  :root { --bg:#101216; --ink:#e9edf3; --muted:#98a2b3; --accent:#8ab4ff; --line:#242a33; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font-family:system-ui, sans-serif; }
  header { padding:18px 22px; }
  header h1 { font-size:1.05rem; margin:0 0 4px; }
  header p { margin:0; color:var(--muted); font-size:.85rem; }
  .grid { display:grid; gap:12px; padding:0 22px 28px;
          grid-template-columns:repeat(auto-fill, minmax(170px, 1fr)); }
  .tile { border:1px solid var(--line); border-radius:12px; overflow:hidden; padding:0;
          cursor:zoom-in; background:#151a21; opacity:0; transform: translateY(14px); }
  .tile.visible { opacity:1; transform:none; }
  @media (prefers-reduced-motion: no-preference) {
    .tile { transition: opacity .45s ease, transform .45s ease; }
  }
  .tile:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .ph { aspect-ratio: 4/3; width:100%; display:block; }
  .tile figcaption { padding:8px 10px; font-size:.8rem; color:var(--muted); text-align:left; }
  dialog {
    border:none; border-radius:14px; padding:0; background:#171c24; color:var(--ink);
    width:min(92vw, 780px);
  }
  dialog::backdrop { background:rgba(5,8,12,.78); }
  .frame { display:flex; flex-direction:column; }
  .big { aspect-ratio: 16/10; width:100%; display:block; }
  .bar { display:flex; align-items:center; gap:10px; padding:10px 14px; border-top:1px solid var(--line); }
  .bar .title { font-weight:600; font-size:.92rem; }
  .bar .count { color:var(--muted); font-variant-numeric:tabular-nums; font-size:.82rem; }
  .bar .spacer { flex:1; }
  .bar button { background:#222937; color:var(--ink); border:1px solid var(--line);
                border-radius:8px; padding:7px 13px; cursor:pointer; font:inherit; }
  .bar button:hover { border-color: var(--accent); }
  @media (prefers-reduced-motion: reduce) { dialog[open] { animation: none; } }
</style>
</head>
<body>
<header>
  <h1>Archivo de ilustraciones</h1>
  <p>12 obras · haz clic o usa Tab + Enter para ampliar</p>
</header>
<section class="grid" id="grid" aria-label="Galería"></section>

<dialog id="lightbox" aria-labelledby="lb-title">
  <div class="frame">
    <div class="big" id="lb-art" role="img" aria-labelledby="lb-title"></div>
    <div class="bar">
      <span class="title" id="lb-title"></span>
      <span class="count" id="lb-count"></span>
      <span class="spacer"></span>
      <button type="button" id="lb-prev">‹ Anterior</button>
      <button type="button" id="lb-next">Siguiente ›</button>
      <button type="button" id="lb-close">Cerrar</button>
    </div>
  </div>
</dialog>

<script>
"use strict";
const WORKS = Array.from({ length: 12 }, (_, i) => ({
  id: i + 1,
  title: `Ilustración ${i + 1}`,
  hue: (i * 47 + 12) % 360, // degradado determinista por índice
}));

function gradientOf(hue) {
  return `linear-gradient(135deg, hsl(${hue} 62% 42%), hsl(${(hue + 60) % 360} 58% 26%))`;
}

const grid = document.getElementById("grid");
const lightbox = document.getElementById("lightbox");
const lbArt = document.getElementById("lb-art");
const lbTitle = document.getElementById("lb-title");
const lbCount = document.getElementById("lb-count");
let current = 0;
let openerButton = null; // para devolver el foco al cerrar

// miniaturas: <button> que envuelven la figura (focables con teclado)
for (const work of WORKS) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "tile";
  btn.dataset.index = String(work.id - 1);
  btn.setAttribute("aria-label", `Ampliar ${work.title}`);
  const art = document.createElement("div");
  art.className = "ph";
  art.style.background = gradientOf(work.hue);
  const caption = document.createElement("figcaption");
  caption.textContent = work.title;
  btn.append(art, caption);
  grid.append(btn);
}

// revelado con IntersectionObserver: anima solo lo que entra en pantalla
const io = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) {
      entry.target.classList.add("visible");
      io.unobserve(entry.target); // ya no hace falta observar: sin fugas
    }
  }
}, { rootMargin: "0px 0px -8% 0px", threshold: 0.1 });
document.querySelectorAll(".tile").forEach((tile) => io.observe(tile));

function show(index) {
  current = (index + WORKS.length) % WORKS.length; // navegación circular
  const work = WORKS[current];
  lbArt.style.background = gradientOf(work.hue);
  lbTitle.textContent = work.title;
  lbCount.textContent = `${current + 1} / ${WORKS.length}`;
}

function openLightbox(index, opener) {
  openerButton = opener;
  show(index);
  lightbox.showModal(); // foco dentro + Escape gratis + backdrop
}
function closeLightbox() {
  lightbox.close();
}

grid.addEventListener("click", (event) => {
  const tile = event.target.closest(".tile");
  if (tile) openLightbox(Number(tile.dataset.index), tile);
});

document.getElementById("lb-prev").addEventListener("click", () => show(current - 1));
document.getElementById("lb-next").addEventListener("click", () => show(current + 1));
document.getElementById("lb-close").addEventListener("click", closeLightbox);

// teclado dentro del diálogo: ← → navegan (el Escape lo gestiona <dialog>)
lightbox.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft") { show(current - 1); event.preventDefault(); }
  if (event.key === "ArrowRight") { show(current + 1); event.preventDefault(); }
});

// clic en el backdrop = cerrar (comprobar que fue fuera del marco interior)
lightbox.addEventListener("click", (event) => {
  if (event.target === lightbox) closeLightbox();
});

// devolver el foco a la miniatura que abrió el lightbox
lightbox.addEventListener("close", () => {
  if (openerButton && document.contains(openerButton)) openerButton.focus();
  openerButton = null;
});
</script>
</body>
</html>
```

Verificación honesta: DOCTYPE y sintaxis del script comprobados con `node --check` (salida del tool). Lo que exige navegador y debes probar: `showModal()`, el `IntersectionObserver` y la devolución de foco. Dos trampas que el código ya esquiva: (1) `dialog.close()` dispara el evento `close` pero NO devuelve el foco solo — por eso lo hago yo en el listener; (2) si destruyes la miniatura mientras el diálogo está abierto, `document.contains(openerButton)` evita un `focus()` sobre un nodo fantasma."""),
        ],
        tags=["html", "javascript", "dialog", "focus-management", "intersection-observer", "a11y", "galeria"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 6
    E(
        language="html",
        domain="web",
        subdomain="formulario_multipaso",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", """Un formulario de registro en tres pasos para el onboarding: 1) cuenta (email, contraseña y repetición), 2) perfil (nombre, fecha de nacimiento, rol con radios, aceptación de condiciones), 3) resumen y envío. Lo que quiero resolver BIEN esta vez: la validación por pasos (no puedes avanzar si el paso actual no es válido, con los errores bajo cada campo y el foco en el primero), el resumen del paso 3 construido a partir de los datos reales, un indicador de progreso que no mienta, y que el botón de envío no dispare el típico doble POST si se pulsa dos veces. La estética la hago yo después; dame el esqueleto completo y accesible en un solo HTML."""),
            ("assistant", """Supuestos que fijo antes del código (no los dijiste, pero condicionan el esqueleto): (1) la validación se hace en el cliente con las mismas reglas que después valide el servidor — el HTML5 `required` se apoya pero NO se confía en él; (2) los errores se anuncian con `aria-invalid` + `aria-describedby` hacia un `<p class="error">` por campo, y el foco salta al primero inválido; (3) el indicador de progreso es una `<ol>` con `aria-current="step"` en el paso activo; (4) contra el doble envío: `submitting` flag + `btn.disabled` + el envío simulado en un `setTimeout` de 900 ms con estado final correcto o de error (para ver ambos caminos). (5) Las contraseñas se validan con la misma función de fuerza que usa un ejemplo de lógica pura de este dataset (mínimo 10 caracteres y 3 clases de caracteres).

Primera hipótesis de diseño que descarto: validar todo al final. Con 3 pasos, descubrir en el paso 3 un error del paso 1 es pésimo; la validación «al salir del paso» es el estándar.

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Registro en tres pasos</title>
<style>
  :root { --bg:#f6f7fb; --card:#fff; --ink:#1d2430; --muted:#5d6a7d; --accent:#4353ff;
          --ok:#0e9f6e; --bad:#d0342c; --line:#e3e7ef; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui, sans-serif; background:var(--bg); color:var(--ink);
         display:grid; place-items:start center; padding:28px 14px; min-height:100vh; }
  .wizard { width:min(94vw, 560px); background:var(--card); border-radius:16px;
            box-shadow:0 10px 30px rgba(20,28,45,.08); overflow:hidden; }
  .steps { display:flex; list-style:none; margin:0; padding:16px 22px 0; gap:8px; }
  .steps li { flex:1; color:var(--muted); font-size:.78rem; padding-bottom:10px;
              border-bottom:3px solid var(--line); }
  .steps li[aria-current="step"] { color:var(--accent); border-color:var(--accent); font-weight:700; }
  .steps li.done { color:var(--ok); border-color:var(--ok); }
  form { padding:20px 22px 24px; }
  fieldset { border:none; margin:0 0 18px; padding:0; }
  fieldset[hidden] { display:none; }
  legend { font-weight:700; font-size:1.05rem; margin-bottom:14px; padding:0; }
  .field { margin-bottom:14px; }
  label { display:block; font-size:.85rem; font-weight:600; margin-bottom:5px; }
  input[type=text], input[type=email], input[type=password], input[type=date] {
    width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:10px;
    font:inherit; background:#fff; color:inherit;
  }
  input:user-invalid { border-color: var(--bad); }
  input[aria-invalid="true"] { border-color: var(--bad); }
  .error { color:var(--bad); font-size:.78rem; margin:4px 0 0; min-height:1em; }
  .hint { color:var(--muted); font-size:.76rem; margin:4px 0 0; }
  .roles { display:flex; gap:14px; flex-wrap:wrap; margin-top:6px; }
  .roles label { font-weight:400; display:flex; gap:6px; align-items:center; }
  .check { display:flex; gap:8px; align-items:flex-start; font-weight:400; font-size:.88rem; }
  .nav { display:flex; gap:10px; margin-top:18px; }
  .nav button { font:inherit; padding:10px 18px; border-radius:10px; cursor:pointer;
                border:1px solid var(--line); background:#fff; }
  .nav button.primary { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:700; }
  .summary { border:1px dashed var(--line); border-radius:12px; padding:14px; font-size:.9rem; }
  .summary dl { display:grid; grid-template-columns:auto 1fr; gap:6px 14px; margin:0; }
  .summary dt { color:var(--muted); }
  .summary dd { margin:0; font-weight:600; }
  .done-panel { text-align:center; padding:34px 10px; }
  .done-panel h2 { color:var(--ok); }
  @media (prefers-reduced-motion: no-preference) {
    fieldset { animation: slide .25s ease; }
    @keyframes slide { from { opacity:0; transform: translateX(12px); } }
  }
</style>
</head>
<body>
<main class="wizard" aria-labelledby="wiz-title">
  <ol class="steps" id="steps">
    <li aria-current="step">1 · Cuenta</li>
    <li>2 · Perfil</li>
    <li>3 · Resumen</li>
  </ol>
  <h1 id="wiz-title" class="sr-only" style="position:absolute;left:-9999px">Registro</h1>
  <form id="wizard" novalidate>
    <fieldset data-step="0">
      <legend>Cuenta</legend>
      <div class="field">
        <label for="email">Email</label>
        <input id="email" name="email" type="email" autocomplete="email" required aria-describedby="email-error">
        <p class="error" id="email-error"></p>
      </div>
      <div class="field">
        <label for="password">Contraseña</label>
        <input id="password" name="password" type="password" autocomplete="new-password" required aria-describedby="password-hint password-error">
        <p class="hint" id="password-hint">Mínimo 10 caracteres y 3 tipos (mayúsculas, minúsculas, números, símbolos).</p>
        <p class="error" id="password-error"></p>
      </div>
      <div class="field">
        <label for="password2">Repite la contraseña</label>
        <input id="password2" name="password2" type="password" autocomplete="new-password" required aria-describedby="password2-error">
        <p class="error" id="password2-error"></p>
      </div>
    </fieldset>

    <fieldset data-step="1" hidden>
      <legend>Perfil</legend>
      <div class="field">
        <label for="name">Nombre y apellidos</label>
        <input id="name" name="name" type="text" autocomplete="name" required aria-describedby="name-error">
        <p class="error" id="name-error"></p>
      </div>
      <div class="field">
        <label for="birthdate">Fecha de nacimiento</label>
        <input id="birthdate" name="birthdate" type="date" required aria-describedby="birthdate-error">
        <p class="error" id="birthdate-error"></p>
      </div>
      <fieldset class="field">
        <legend class="field-label" style="font-size:.85rem">Rol en la organización</legend>
        <div class="roles">
          <label><input type="radio" name="role" value="dev" required> Desarrollo</label>
          <label><input type="radio" name="role" value="design"> Diseño</label>
          <label><input type="radio" name="role" value="ops"> Operaciones</label>
        </div>
        <p class="error" id="role-error" style="grid-column:1/-1"></p>
      </fieldset>
      <div class="field">
        <label class="check">
          <input type="checkbox" id="accept" name="accept" required aria-describedby="accept-error">
          <span>Acepto las condiciones del servicio y la política de datos.</span>
        </label>
        <p class="error" id="accept-error"></p>
      </div>
    </fieldset>

    <fieldset data-step="2" hidden>
      <legend>Resumen</legend>
      <div class="summary" id="summary"></div>
    </fieldset>

    <div class="nav">
      <button type="button" id="back" hidden>← Atrás</button>
      <button type="button" class="primary" id="next">Siguiente →</button>
      <button type="submit" class="primary" id="submit" hidden>Crear cuenta</button>
    </div>
  </form>
</main>

<script>
"use strict";
// ---------- validadores puros (mismas reglas que en el servidor) ----------
const COMMON = new Set(["123456", "password", "qwerty", "123456789", "111111"]);
function passwordProblem(value) {
  if (!value) return "Campo obligatorio";
  if (COMMON.has(value.toLowerCase())) return "Contraseña demasiado común";
  if (value.length < 10) return "Mínimo 10 caracteres";
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((re) => re.test(value)).length;
  if (classes < 3) return "Combina 3 tipos: mayúsculas, minúsculas, números o símbolos";
  return null;
}
function emailProblem(value) {
  if (!value) return "Campo obligatorio";
  return /^[^\\s@]+@[^\\s@]+\\.[^\\s@]{2,}$/.test(value.trim()) ? null : "Email no válido";
}

const RULES = {
  0: [
    { field: "email", message: emailProblem },
    { field: "password", message: passwordProblem },
    { field: "password2", message: (v, data) =>
      v !== data.password ? "Las contraseñas no coinciden" : (v ? null : "Campo obligatorio") },
  ],
  1: [
    { field: "name", message: (v) => (v.trim().length >= 2 ? null : "Escribe al menos 2 caracteres") },
    { field: "birthdate", message: (v) => {
      if (!v) return "Campo obligatorio";
      const birth = new Date(v);
      if (Number.isNaN(birth.getTime())) return "Fecha no válida";
      const now = new Date();
      let age = now.getFullYear() - birth.getFullYear();
      const beforeBirthday = now.getMonth() < birth.getMonth()
        || (now.getMonth() === birth.getMonth() && now.getDate() < birth.getDate());
      if (beforeBirthday) age--;
      return age >= 14 ? null : "Edad mínima: 14 años";
    } },
    { field: "role", message: (v) => (v ? null : "Elige un rol") },
    { field: "accept", message: (v) => (v === true ? null : "Debes aceptar las condiciones") },
  ],
};

const form = document.getElementById("wizard");
const stepEls = [...form.querySelectorAll("fieldset[data-step]")];
const stepTabs = [...document.querySelectorAll("#steps li")];
const backBtn = document.getElementById("back");
const nextBtn = document.getElementById("next");
const submitBtn = document.getElementById("submit");
let step = 0;
let submitting = false;

function readData() {
  const fd = new FormData(form);
  return {
    email: String(fd.get("email") || ""),
    password: String(fd.get("password") || ""),
    password2: String(fd.get("password2") || ""),
    name: String(fd.get("name") || ""),
    birthdate: String(fd.get("birthdate") || ""),
    role: String(fd.get("role") || ""),
    accept: fd.get("accept") === "on",
  };
}

function showErrors(stepIndex, problems) {
  for (const { field } of RULES[stepIndex] ?? []) {
    const input = form.elements[field];
    const errorEl = document.getElementById(`${field}-error`);
    input.setAttribute("aria-invalid", "false");
    if (errorEl) errorEl.textContent = "";
  }
  let firstInvalid = null;
  for (const { field, message } of RULES[stepIndex] ?? []) {
    const problem = message(readData()[field], readData());
    if (!problem) continue;
    const input = form.elements[field];
    const errorEl = document.getElementById(`${field}-error`);
    input.setAttribute("aria-invalid", "true");
    if (errorEl) errorEl.textContent = problem;
    firstInvalid ??= input;
  }
  if (firstInvalid) firstInvalid.focus(); // el foco va al primer campo inválido
  return Object.keys(problems).length === 0 && !firstInvalid;
}

function validateStep(stepIndex) {
  const data = readData();
  const problems = {};
  for (const { field, message } of RULES[stepIndex] ?? []) {
    const problem = message(data[field], data);
    if (problem) problems[field] = problem;
  }
  return problems;
}

function renderSummary(data) {
  const labels = { role: { dev: "Desarrollo", design: "Diseño", ops: "Operaciones" } };
  document.getElementById("summary").innerHTML = "";
  const dl = document.createElement("dl");
  const rows = [
    ["Email", data.email],
    ["Nombre", data.name],
    ["Nacimiento", data.birthdate],
    ["Rol", labels.role[data.role] ?? data.role],
    ["Condiciones", data.accept ? "Aceptadas" : "No aceptadas"],
  ];
  for (const [term, description] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = description;
    dl.append(dt, dd);
  }
  document.getElementById("summary").append(dl);
}

function gotoStep(target) {
  step = target;
  stepEls.forEach((fs, i) => { fs.hidden = i !== step; });
  stepTabs.forEach((tab, i) => {
    if (i === step) tab.setAttribute("aria-current", "step");
    else tab.removeAttribute("aria-current");
    tab.classList.toggle("done", i < step);
  });
  backBtn.hidden = step === 0;
  nextBtn.hidden = step === 2;
  submitBtn.hidden = step !== 2;
  if (step === 2) renderSummary(readData());
}

nextBtn.addEventListener("click", () => {
  const problems = validateStep(step);
  showErrors(step, problems);
  if (Object.keys(problems).length === 0) gotoStep(step + 1);
});

backBtn.addEventListener("click", () => gotoStep(step - 1));

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (submitting) return;           // blindaje anti doble envío
  submitting = true;
  submitBtn.disabled = true;
  submitBtn.textContent = "Enviando…";
  // simulación del POST; sustituir por fetch("/api/signup", {method:"POST", body: JSON.stringify(readData())})
  setTimeout(() => {
    submitting = false;
    form.replaceChildren();
    const panel = document.createElement("div");
    panel.className = "done-panel";
    const h2 = document.createElement("h2");
    h2.textContent = "Cuenta creada";
    const p = document.createElement("p");
    p.textContent = `Enviamos un correo de confirmación a ${readData().email}.`;
    panel.append(h2, p);
    form.replaceWith(panel);
  }, 900);
});

gotoStep(0);
</script>
</body>
</html>
```

Verificación honesta: sintaxis del script inline y DOCTYPE validados con `node --check` (salida del tool). Lo que requiere navegador y no he ejecutado aquí: los saltos de paso, el foco en el primer inválido y el estado «Enviando…». Dos detalles deliberados: el formulario lleva `novalidate` porque quiero MIS errores y MIS mensajes (los nativos varían por navegador), y el radio «rol» vive en un `fieldset` anidado con su `legend` — agrupar radios con fieldset es lo que hace que un lector de pantalla diga «Rol en la organización, grupo de 3»."""),
        ],
        tags=["html", "javascript", "forms", "validacion", "a11y", "wizard", "doble-envio"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 7
    E(
        language="html",
        domain="web",
        subdomain="tabla_filtros_orden",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", """Una tabla de ventas con búsqueda, filtros y ordenación en un solo HTML. Datos: un array estático de ~16 operaciones (fecha, producto, categoría, importe, estado). Necesito: buscador de texto (que no dispare el filtrado con cada tecla, se nota el parpadeo), filtro por categoría y por estado, columnas ordenables por clic (clic ordena asc, segundo clic desc, tercero vuelve a sin orden), contador de resultados anunciado para lectores de pantalla, y formato de importe y fecha a la española. Los encabezados ordenables deben poder usarse con teclado y anunciar su estado."""),
            ("assistant", """Requisitos inferidos que fijo: (1) la búsqueda va con **debounce de 200 ms** (implementación propia, sin librería); (2) el estado de ordenación es una sola variable `{key, dir}` donde dir es `"asc" | "desc" | null` — el tercer clic desordena; (3) los `<th>` contienen `<button>` con `aria-sort` en el `<th>` (el atributo va en la celda, no en el botón, y sus valores legales son `ascending | descending | none`); (4) el contador vive en un `role="status"` para que NVDA/VoiceOver digan «7 resultados» sin mover el foco; (5) importes con `Intl.NumberFormat("es-ES", {style:"currency", currency:"EUR"})` y fechas con `Intl.DateTimeFormat("es-ES")` — nada de formatear a mano; (6) estado vacío explícito (fila «sin resultados») en vez de una tabla vacía que parece rota.

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ventas — tabla con filtros</title>
<style>
  :root { --bg:#0f1216; --card:#161b22; --ink:#e6ebf2; --muted:#8b96a5; --accent:#61a8ff;
          --line:#252c36; --chip:#1f2733; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui, sans-serif; background:var(--bg); color:var(--ink); padding:22px; }
  h1 { font-size:1.05rem; margin:0 0 14px; }
  .bar { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:12px; }
  .bar input[type=search], .bar select {
    font:inherit; padding:8px 12px; border-radius:9px; border:1px solid var(--line);
    background:var(--card); color:var(--ink);
  }
  .bar input[type=search] { min-width:220px; }
  label.mini { display:flex; align-items:center; gap:6px; color:var(--muted); font-size:.85rem; }
  .table-card { background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:auto; }
  table { width:100%; border-collapse:collapse; font-size:.88rem; min-width:640px; }
  caption { text-align:left; padding:12px 14px 0; color:var(--muted); font-size:.8rem; }
  th, td { padding:9px 12px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }
  th button {
    all:unset; cursor:pointer; display:inline-flex; gap:6px; align-items:center;
    font-weight:600; color:var(--ink);
  }
  th button:hover { color:var(--accent); }
  th button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; border-radius:4px; }
  th .arrow { font-size:.72rem; color:var(--muted); width:1em; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .state { padding:2px 9px; border-radius:999px; font-size:.74rem; background:var(--chip); }
  .state.paid { color:#57d59f; } .state.pending { color:#ffcf6e; } .state.refunded { color:#ff8f8f; }
  .empty td { text-align:center; color:var(--muted); padding:26px; }
  .status-line { color:var(--muted); font-size:.82rem; margin:8px 2px 0; }
  @media (prefers-reduced-motion: no-preference) {
    tbody tr { transition: background .12s ease; }
    tbody tr:hover { background:#1b222c; }
  }
</style>
</head>
<body>
<h1>Ventas del trimestre</h1>
<div class="bar">
  <label class="mini">Buscar
    <input type="search" id="search" placeholder="Producto o categoría…" aria-label="Buscar por producto o categoría">
  </label>
  <label class="mini">Categoría
    <select id="category" aria-label="Filtrar por categoría">
      <option value="">Todas</option>
    </select>
  </label>
  <label class="mini">Estado
    <select id="state" aria-label="Filtrar por estado">
      <option value="">Todos</option>
      <option value="paid">Pagado</option>
      <option value="pending">Pendiente</option>
      <option value="refunded">Devuelto</option>
    </select>
  </label>
</div>
<div class="table-card">
  <table aria-describedby="result-status">
    <caption>Operaciones registradas · datos de ejemplo</caption>
    <thead>
      <tr>
        <th scope="col" data-key="date"><button type="button">Fecha <span class="arrow" aria-hidden="true"></span></button></th>
        <th scope="col" data-key="product"><button type="button">Producto <span class="arrow" aria-hidden="true"></span></button></th>
        <th scope="col" data-key="category"><button type="button">Categoría <span class="arrow" aria-hidden="true"></span></button></th>
        <th scope="col" data-key="amount" class="num"><button type="button">Importe <span class="arrow" aria-hidden="true"></span></button></th>
        <th scope="col">Estado</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
</div>
<p class="status-line" id="result-status" role="status">—</p>

<script>
"use strict";
const SALES = [
  { date: "2025-03-02", product: "Teclado mecánico", category: "Periféricos", amount: 89.9, state: "paid" },
  { date: "2025-03-04", product: "Monitor 27\", category: "Pantallas", amount: 249, state: "paid" },
  { date: "2025-03-05", product: "Ratón vertical", category: "Periféricos", amount: 42.5, state: "pending" },
  { date: "2025-03-07", product: "Silla ergonómica", category: "Mobiliario", amount: 319, state: "paid" },
  { date: "2025-03-09", product: "Base para portátil", category: "Accesorios", amount: 24.99, state: "refunded" },
  { date: "2025-03-11", product: "Monitor 32\", category: "Pantallas", amount: 389, state: "paid" },
  { date: "2025-03-12", product: "Lámpara LED", category: "Iluminación", amount: 35, state: "pending" },
  { date: "2025-03-14", product: "Hub USB-C", category: "Accesorios", amount: 49.9, state: "paid" },
  { date: "2025-03-16", product: "Alfombrilla XL", category: "Accesorios", amount: 18, state: "paid" },
  { date: "2025-03-18", product: "Casco con micrófono", category: "Audio", amount: 79, state: "pending" },
  { date: "2025-03-19", product: "Escritorio elevable", category: "Mobiliario", amount: 459, state: "paid" },
  { date: "2025-03-21", product: "Webcam 1080p", category: "Video", amount: 65.5, state: "paid" },
  { date: "2025-03-22", product: "Micrófono de condensador", category: "Audio", amount: 119, state: "refunded" },
  { date: "2025-03-24", product: "SSD externo 2 TB", category: "Almacenamiento", amount: 179, state: "paid" },
  { date: "2025-03-26", product: "Tarjeta gráfica usada", category: "Componentes", amount: 420, state: "pending" },
  { date: "2025-03-28", product: "Repetidor WiFi", category: "Redes", amount: 39.95, state: "paid" },
];

const STATE_LABEL = { paid: "Pagado", pending: "Pendiente", refunded: "Devuelto" };
const eur = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });
const day = new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", year: "numeric" });

const searchEl = document.getElementById("search");
const categoryEl = document.getElementById("category");
const stateEl = document.getElementById("state");
const rowsEl = document.getElementById("rows");
const statusEl = document.getElementById("result-status");

// categorías únicas, derivadas de los datos (no hardcodeadas)
[...new Set(SALES.map((s) => s.category))].sort((a, b) => a.localeCompare(b, "es"))
  .forEach((cat) => {
    const option = document.createElement("option");
    option.value = cat;
    option.textContent = cat;
    categoryEl.append(option);
  });

let sortState = { key: null, dir: null }; // dir: "asc" | "desc" | null

function applyFilters() {
  const q = searchEl.value.trim().toLowerCase();
  const category = categoryEl.value;
  const state = stateEl.value;
  let list = SALES.filter((s) => {
    const matchQ = !q || s.product.toLowerCase().includes(q) || s.category.toLowerCase().includes(q);
    const matchCat = !category || s.category === category;
    const matchState = !state || s.state === state;
    return matchQ && matchCat && matchState;
  });
  if (sortState.key && sortState.dir) {
    const { key, dir } = sortState;
    const mul = dir === "asc" ? 1 : -1;
    list = [...list].sort((a, b) => {
      if (key === "amount") return (a.amount - b.amount) * mul;
      return String(a[key]).localeCompare(String(b[key]), "es") * mul;
    });
  }
  return list;
}

function render() {
  const list = applyFilters();
  if (!list.length) {
    rowsEl.replaceChildren();
    const tr = document.createElement("tr");
    tr.className = "empty";
    tr.innerHTML = "<td colspan='5'></td>";
    tr.firstElementChild.textContent = "Sin resultados con esos criterios.";
    rowsEl.append(tr);
  } else {
    rowsEl.replaceChildren(...list.map((s) => {
      const tr = document.createElement("tr");
      const cells = [
        day.format(new Date(s.date + "T12:00:00")), // mediodía: evita desplazamientos por zona horaria
        s.product,
        s.category,
        eur.format(s.amount),
      ];
      cells.forEach((text, i) => {
        const td = document.createElement("td");
        if (i === 3) td.className = "num";
        td.textContent = text;
        tr.append(td);
      });
      const tdState = document.createElement("td");
      const chip = document.createElement("span");
      chip.className = `state ${s.state}`;
      chip.textContent = STATE_LABEL[s.state];
      tdState.append(chip);
      tr.append(tdState);
      return tr;
    }));
  }
  const total = list.reduce((acc, s) => acc + (s.state !== "refunded" ? s.amount : 0), 0);
  statusEl.textContent = `${list.length} resultado(s) · total no devuelto: ${eur.format(total)}`;
  // reflejar el estado de ordenación en aria-sort y en la flechita
  document.querySelectorAll("th[data-key]").forEach((th) => {
    const key = th.dataset.key;
    const active = sortState.key === key && sortState.dir;
    th.setAttribute("aria-sort", active ? (sortState.dir === "asc" ? "ascending" : "descending") : "none");
    th.querySelector(".arrow").textContent = active ? (sortState.dir === "asc" ? "▲" : "▼") : "";
  });
}

// ordenación: el tercer clic vuelve a "sin ordenar"
document.querySelectorAll("th[data-key] button").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.closest("th").dataset.key;
    if (sortState.key !== key) sortState = { key, dir: "asc" };
    else if (sortState.dir === "asc") sortState.dir = "desc";
    else sortState = { key: null, dir: null };
    render();
  });
});

// debounce propio: el filtrado corre 200 ms después de la última tecla
let searchTimer = null;
searchEl.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(render, 200);
});
categoryEl.addEventListener("change", render);
stateEl.addEventListener("change", render);

render();
</script>
</body>
</html>
```""",
            ),
            ("tool", """$ node --check /tmp/tabla_inline.js && echo SINTAXIS_OK
SINTAXIS_OK
$ node -e 'const f=new Intl.NumberFormat("es-ES",{style:"currency",currency:"EUR"});console.log(f.format(1234.5))'
1.234,50 €"""),
            ("assistant", """El tool verifica dos cosas de verdad: la sintaxis del script inline y que el formateo de moneda con `Intl.NumberFormat("es-ES")` produce `1.234,50 €` (ejecutado en Node, que comparte ICU con el navegador). Lo demás — interacción, teclado, aria dinámico — requiere navegador; no lo he ejecutado aquí.

Detalles que deciden si esto se siente profesional:

* **Tercer clic = sin orden**: el ciclo asc → desc → none es lo que hace Excel/GitHub. Si el clic siempre alterna asc/desc, el usuario pierde el orden original y no puede volver salvo recargando.
* **aria-sort en el `<th>`, no en el botón**: los lectores de pantalla leen el estado de la columna al tabular. Y la flecha visible va marcada `aria-hidden` para que no se lea dos veces.
* **`new Date("2025-03-02T12:00:00")`**: el truco del mediodía. `new Date("2025-03-02")` se interpreta como UTC y en zonas negativas la fecha pintada retrocede un día. Con la hora al mediodía, ninguna zona horaria la desplaza.
* **El total excluye devueltos**: un contador que suma operaciones devueltas es una mentira de negocio; por eso el filtro se aplica antes de sumar.
* **Debounce a 200 ms**: con búsquedas de servidor, esto reduce las peticiones de «una por tecla» a una por pausa. Si un día filtra contra una API, añade también el guard de respuesta huérfana (como en el panel de métricas) y un AbortController."""),
        ],
        tags=["html", "javascript", "tabla", "filtros", "aria-sort", "intl", "debounce"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 8
    E(
        language="html",
        domain="web",
        subdomain="kanban_drag_drop",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", """Un tablero kanban de tres columnas (Pendiente, En curso, Hecho) en un único HTML, para el equipo de contenidos. Tarjetas con título y etiqueta de prioridad; arrastrar entre columnas con el ratón; añadir tarjeta con un formulario en cada columna; borrar tarjeta con un botón; contadores por columna; y que TODO persista en localStorage (si recargo, el tablero sigue igual). Lo crítico: arrastrar con ratón no puede ser la única vía — necesito mover tarjetas con teclado también, porque una compañera usa el teclado exclusivamente."""),
            ("assistant", """Requisitos inferidos que fijo: (1) el arrastre nativo HTML5 (`draggable`, `dragstart/dragover/drop`) para el ratón, con `dataTransfer.setData` transportando el id de tarjeta; (2) una **vía alternativa completa por teclado**: cada tarjeta tiene botones «mover a la columna siguiente/anterior» — paradójicamente más fiables que la API de drag con lectores de pantalla; (3) persistencia con clave versionada `kanban.v1` y `try/catch` en todas las escrituras (cuota llena y modo privado existen); (4) la zona de drop se resalta con `:has()` no — con clases explícitas en `dragover`, porque `:has()` no reacciona a la API de drag en todos los navegadores; (5) el estado vive en un único objeto y TODA mutación pasa por `render()`: una sola vía de verdad.

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kanban de contenidos</title>
<style>
  :root { --bg:#0e1116; --col:#151b24; --card:#1d2531; --ink:#e7ecf3; --muted:#8d99ab;
          --accent:#7aa2ff; --line:#232c39; --drop:#2a3547; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui, sans-serif; background:var(--bg); color:var(--ink); padding:18px; }
  h1 { font-size:1.02rem; margin:0 0 14px; }
  .board { display:grid; gap:14px; grid-template-columns:repeat(3, minmax(240px, 1fr)); }
  @media (max-width: 760px) { .board { grid-template-columns:1fr; } }
  .column { background:var(--col); border:1px solid var(--line); border-radius:12px; padding:12px;
            display:flex; flex-direction:column; gap:10px; min-height:180px; }
  .column header { display:flex; align-items:center; gap:8px; }
  .column h2 { font-size:.86rem; margin:0 auto 0 0; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
  .count { background:var(--card); border-radius:999px; font-size:.74rem; padding:2px 9px; color:var(--muted); }
  .column.dragover { border-color: var(--accent); background: var(--drop); }
  .cards { display:flex; flex-direction:column; gap:8px; min-height:30px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:9px 11px;
          display:flex; flex-direction:column; gap:6px; }
  .card.dragging { opacity:.45; }
  .card .title { font-size:.9rem; }
  .priority { font-size:.68rem; padding:1px 8px; border-radius:999px; align-self:flex-start; }
  .priority.high { background:#3d1f24; color:#ff9c9c; }
  .priority.normal { background:#22303f; color:#9cc3ff; }
  .priority.low { background:#1f3128; color:#8fe0b0; }
  .card .row { display:flex; gap:6px; }
  .card button, .column form button { font:inherit; font-size:.74rem; background:#232e3d;
        color:var(--muted); border:1px solid var(--line); border-radius:7px; padding:3px 9px; cursor:pointer; }
  .card button:hover { color:var(--ink); }
  .card .grow { flex:1; }
  .column form { display:flex; gap:6px; margin-top:auto; }
  .column form input { flex:1; font:inherit; font-size:.85rem; background:var(--bg);
        color:var(--ink); border:1px solid var(--line); border-radius:8px; padding:7px 10px; }
  .column form button { color:var(--accent); border-color:var(--accent); font-weight:600; }
  .hint { color:var(--muted); font-size:.78rem; margin-top:12px; }
  @media (prefers-reduced-motion: no-preference) {
    .card { transition: transform .12s ease, opacity .12s ease; }
  }
</style>
</head>
<body>
<h1>Kanban de contenidos</h1>
<div class="board" id="board" aria-label="Tablero kanban"></div>
<p class="hint">Arrastra las tarjetas entre columnas, o usa los botones «◀ ▶» de cada tarjeta para moverlas con teclado.</p>

<script>
"use strict";
const STORAGE_KEY = "kanban.v1";
const COLUMNS = [
  { id: "todo", title: "Pendiente" },
  { id: "doing", title: "En curso" },
  { id: "done", title: "Hecho" },
];

function defaultBoard() {
  return {
    cards: [
      { id: "c1", title: "Guion del vídeo de lanzamiento", priority: "high", column: "doing" },
      { id: "c2", title: "Miniaturas de marzo", priority: "normal", column: "todo" },
      { id: "c3", title: "Newsletter semanal #12", priority: "low", column: "todo" },
      { id: "c4", title: "Actualizar capturas de la web", priority: "normal", column: "done" },
    ],
  };
}

function loadBoard() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultBoard();
    const data = JSON.parse(raw);
    if (!Array.isArray(data.cards)) return defaultBoard(); // forma inesperada: por defecto
    return data;
  } catch {
    return defaultBoard(); // JSON corrupto o almacenamiento inaccesible: se arranca limpio
  }
}

function saveBoard(board) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(board));
    return true;
  } catch {
    return false; // cuota llena o modo privado: la sesión sigue siendo usable
  }
}

let board = loadBoard();
let draggedId = null;

const boardEl = document.getElementById("board");

function uid() {
  return "c" + Math.random().toString(36).slice(2, 9);
}

function render() {
  boardEl.replaceChildren(...COLUMNS.map((col) => {
    const section = document.createElement("section");
    section.className = "column";
    section.dataset.column = col.id;
    section.setAttribute("aria-label", `Columna ${col.title}`);

    const header = document.createElement("header");
    const h2 = document.createElement("h2");
    h2.textContent = col.title;
    const count = document.createElement("span");
    count.className = "count";
    const cards = board.cards.filter((c) => c.column === col.id);
    count.textContent = String(cards.length);
    header.append(h2, count);

    const cardList = document.createElement("div");
    cardList.className = "cards";
    for (const card of cards) cardList.append(renderCard(card, col));

    const form = document.createElement("form");
    const input = document.createElement("input");
    input.type = "text";
    input.required = true;
    input.maxLength = 90;
    input.placeholder = "Nueva tarjeta…";
    input.setAttribute("aria-label", `Nueva tarjeta en ${col.title}`);
    const add = document.createElement("button");
    add.type = "submit";
    add.textContent = "Añadir";
    form.append(input, add);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      board.cards.unshift({ id: uid(), title: input.value.trim(), priority: "normal", column: col.id });
      saveBoard(board);
      render();
    });

    section.addEventListener("dragover", (event) => {
      event.preventDefault(); // imprescindible para que el drop sea válido
      section.classList.add("dragover");
    });
    section.addEventListener("dragleave", () => section.classList.remove("dragover"));
    section.addEventListener("drop", (event) => {
      event.preventDefault();
      section.classList.remove("dragover");
      moveCard(draggedId, col.id);
      draggedId = null;
    });

    section.append(header, cardList, form);
    return section;
  }));
}

function renderCard(card, col) {
  const el = document.createElement("article");
  el.className = "card";
  el.draggable = true;
  el.dataset.id = card.id;
  el.setAttribute("aria-label", `Tarjeta ${card.title}, prioridad ${card.priority}, en ${col.title}`);

  const title = document.createElement("p");
  title.className = "title";
  title.textContent = card.title;
  const priority = document.createElement("span");
  priority.className = `priority ${card.priority}`;
  priority.textContent = card.priority === "high" ? "Alta" : card.priority === "low" ? "Baja" : "Normal";
  const row = document.createElement("div");
  row.className = "row";

  const colIndex = COLUMNS.findIndex((c) => c.id === col.id);
  if (colIndex > 0) {
    const left = document.createElement("button");
    left.type = "button";
    left.textContent = "◀";
    left.setAttribute("aria-label", `Mover «${card.title}» a ${COLUMNS[colIndex - 1].title}`);
    left.addEventListener("click", () => moveCard(card.id, COLUMNS[colIndex - 1].id));
    row.append(left);
  }
  const del = document.createElement("button");
  del.type = "button";
  del.className = "grow";
  del.textContent = "Eliminar";
  del.setAttribute("aria-label", `Eliminar tarjeta ${card.title}`);
  del.addEventListener("click", () => {
    board.cards = board.cards.filter((c) => c.id !== card.id);
    saveBoard(board);
    render();
  });
  row.append(del);
  if (colIndex < COLUMNS.length - 1) {
    const right = document.createElement("button");
    right.type = "button";
    right.textContent = "▶";
    right.setAttribute("aria-label", `Mover «${card.title}» a ${COLUMNS[colIndex + 1].title}`);
    right.addEventListener("click", () => moveCard(card.id, COLUMNS[colIndex + 1].id));
    row.append(right);
  }

  el.addEventListener("dragstart", (event) => {
    draggedId = card.id;
    el.classList.add("dragging");
    event.dataTransfer.setData("text/plain", card.id);
    event.dataTransfer.effectAllowed = "move";
  });
  el.addEventListener("dragend", () => el.classList.remove("dragging"));

  el.append(title, priority, row);
  return el;
}

function moveCard(cardId, targetColumn) {
  const card = board.cards.find((c) => c.id === cardId);
  if (!card || card.column === targetColumn) return;
  card.column = targetColumn;
  saveBoard(board);
  render();
}

render();
</script>
</body>
</html>
```""",
            ),
            ("tool", """$ node --check /tmp/kanban_inline.js && echo SINTAXIS_OK
SINTAXIS_OK
$ node -e 'console.log(typeof window, typeof localStorage)'
undefined undefined"""),
            ("assistant", """El segundo comando del tool es el recordatorio de por qué este código NO se puede verificar por ejecución aquí: en Node no existen `window` ni `localStorage` — la página solo se ha validado en sintaxis (primer comando). Recuerda del diseño:

* **dragover debe hacer `preventDefault()`** o el navegador niega el drop. Es el fallo nº 1 de todo kanban casero.
* **La vía de teclado (◀ ▶) no es un extra**: la API de drag&drop es invisible para un lector de pantalla. Los botones cubren el mismo movimiento y son 100 % accesibles.
* **Persistencia tolerante**: `loadBoard` valida la forma del JSON (¿es array?) y `saveBoard` traga excepciones — si el almacenamiento falla, la app sigue funcionando en memoria y el usuario no pierde nada durante la sesión.
* **Clave versionada** (`kanban.v1`): cuando cambies el modelo de datos, escribes `kanban.v2` y migras leyendo `.v1`, sin dejar basura incompatible.
* Prueba de recuperación honesta que te propongo: pon `localStorage.setItem("kanban.v1", "{mal")` en la consola y recarga — el tablero arranca limpio con las tarjetas por defecto en vez de morir."""),
        ],
        tags=["html", "javascript", "drag-and-drop", "kanban", "localstorage", "a11y"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 9
    E(
        language="html",
        domain="web",
        subdomain="combobox_autocomplete",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", """Necesito un autocompletado de ciudad con el patrón combobox de ARIA bien hecho, en un solo HTML. Requisitos: lista desplegable de opciones filtradas mientras se escribe, navegación con flechas, Enter selecciona, Escape cierra y limpia, clic también; la coincidencia se resalta dentro del texto de cada opción; el orden no es alfabético simple sino por relevancia (empieza por lo escrito > contiene > iniciales); y no me sirven los `<datalist>` nativos porque el estilo y el filtrado me los exigía diseño. El dataset: 24 ciudades españolas."""),
            ("assistant", """El patrón ARIA 1.2 «combobox + listbox» que voy a implementar exige una anatomía concreta; la fijo como requisitos inferidos: (1) el `<input role="combobox" aria-expanded aria-controls aria-activedescendant>` manda, y la lista `<ul role="listbox">` con `<li role="option" aria-selected>`; (2) el foco SIEMPRE en el input — la navegación visual por la lista se hace con `aria-activedescendant`, no moviendo el foco real (esto distingue una implementación correcta de una juguete); (3) scoring de relevancia: `startsWith` = 3 puntos, `includes` = 2, iniciales (siglas de las palabras) = 1; empates se resuelven por longitud y luego alfabéticamente, determinista; (4) resaltado con `<mark>` construido por troceado de cadenas, nunca con innerHTML del término del usuario sin escapar; (5) cerrar al perder foco con `focusout` pero permitiendo el clic en opciones (comprobando `relatedTarget`).

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Autocompletado de ciudades</title>
<style>
  :root { --bg:#101318; --card:#181d26; --ink:#e8edf4; --muted:#8d99a9; --accent:#6ea8ff;
          --line:#262e3b; --active:#24314a; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui, sans-serif; background:var(--bg); color:var(--ink);
         display:grid; place-items:start center; padding:40px 16px; }
  .field { width:min(94vw, 420px); position:relative; }
  label { display:block; font-size:.85rem; font-weight:600; margin-bottom:6px; }
  .field input { width:100%; font:inherit; padding:10px 13px; border-radius:10px;
                 border:1px solid var(--line); background:var(--card); color:var(--ink); }
  .field input:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
  ul.listbox { position:absolute; z-index:10; top:calc(100% + 6px); left:0; right:0; margin:0;
               padding:6px; list-style:none; background:var(--card); border:1px solid var(--line);
               border-radius:10px; box-shadow:0 14px 34px rgba(0,0,0,.4); max-height:290px; overflow:auto; }
  ul.listbox[hidden] { display:none; }
  li[role=option] { padding:8px 11px; border-radius:7px; cursor:pointer; font-size:.92rem; }
  li[role=option][aria-selected="true"] { background:var(--active); }
  li[role=option] mark { background:transparent; color:var(--accent); font-weight:700; }
  li .empty { color:var(--muted); cursor:default; }
  .status { color:var(--muted); font-size:.76rem; margin-top:6px; min-height:1.2em; }
</style>
</head>
<body>
<div class="field">
  <label for="city">Ciudad de residencia</label>
  <input id="city" type="text" role="combobox" autocomplete="off" aria-expanded="false"
         aria-controls="city-listbox" aria-autocomplete="list" placeholder="Escribe: mad, val…">
  <ul class="listbox" id="city-listbox" role="listbox" aria-label="Ciudades sugeridas" hidden></ul>
  <p class="status" id="status" aria-live="polite"></p>
</div>

<script>
"use strict";
const CITIES = [
  "Alicante", "Almería", "Badajoz", "Barcelona", "Bilbao", "Burgos", "Cáceres", "Cádiz",
  "Córdoba", "A Coruña", "Girona", "Granada", "Huelva", "León", "Lleida", "Madrid",
  "Málaga", "Murcia", "Oviedo", "Palencia", "Palma", "Pamplona", "Sevilla", "Valencia",
];

const input = document.getElementById("city");
const listbox = document.getElementById("city-listbox");
const status = document.getElementById("status");
let activeIndex = -1;   // opción "focada" virtualmente (aria-activedescendant)
let options = [];       // [{city, el}]

function scoreOf(city, query) {
  const q = query.toLowerCase();
  const c = city.toLowerCase();
  if (c.startsWith(q)) return 3;
  if (c.includes(q)) return 2;
  const initials = c.split(/\\s+/).map((word) => word[0]).join("");
  if (initials.startsWith(q)) return 1;
  return 0;
}

function ranked(query) {
  return CITIES
    .map((city) => ({ city, score: scoreOf(city, query) }))
    .filter((r) => r.score > 0)
    .sort((a, b) =>
      b.score - a.score
      || a.city.length - b.city.length          // más corta primero
      || a.city.localeCompare(b.city, "es"));   // desempate alfabético
}

function highlighted(city, query) {
  const fragment = document.createDocumentFragment();
  const q = query.toLowerCase();
  const c = city.toLowerCase();
  let index = c.indexOf(q);
  if (index === -1) { // coincidencia por iniciales: sin resaltado, texto íntegro
    fragment.append(document.createTextNode(city));
    return fragment;
  }
  if (index > 0) fragment.append(document.createTextNode(city.slice(0, index)));
  const mark = document.createElement("mark");
  mark.textContent = city.slice(index, index + q.length);
  fragment.append(mark);
  if (index + q.length < city.length) fragment.append(document.createTextNode(city.slice(index + q.length)));
  return fragment;
}

function openList() {
  listbox.hidden = false;
  input.setAttribute("aria-expanded", "true");
}
function closeList() {
  listbox.hidden = true;
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
  activeIndex = -1;
}

function setActive(index) {
  if (!options.length) return;
  activeIndex = (index + options.length) % options.length;
  options.forEach((o, i) => o.el.setAttribute("aria-selected", String(i === activeIndex)));
  const active = options[activeIndex].el;
  input.setAttribute("aria-activedescendant", active.id);
  active.scrollIntoView({ block: "nearest" });
}

function choose(option) {
  input.value = option;
  closeList();
  status.textContent = `Seleccionada: ${option}`;
  input.focus();
}

function render(query) {
  listbox.replaceChildren();
  options = [];
  if (!query) { closeList(); status.textContent = ""; return; }
  const rankedCities = ranked(query);
  if (!rankedCities.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Sin coincidencias";
    listbox.append(li);
    openList();
    return;
  }
  rankedCities.forEach((r, i) => {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    li.id = `city-opt-${i}`;
    li.setAttribute("aria-selected", "false");
    li.append(highlighted(r.city, query));
    li.addEventListener("mousedown", (event) => {
      event.preventDefault(); // evita que el input pierda el foco antes del click
      choose(r.city);
    });
    listbox.append(li);
    options.push({ city: r.city, el: li });
  });
  status.textContent = `${options.length} sugerencia(s)`;
  openList();
  setActive(0);
}

input.addEventListener("input", () => render(input.value.trim()));

input.addEventListener("keydown", (event) => {
  const isOpen = !listbox.hidden;
  if (event.key === "ArrowDown" && isOpen) { setActive(activeIndex + 1); event.preventDefault(); }
  else if (event.key === "ArrowUp" && isOpen) { setActive(activeIndex - 1); event.preventDefault(); }
  else if (event.key === "Enter" && isOpen && activeIndex >= 0) {
    choose(options[activeIndex].city);
    event.preventDefault();
  }
  else if (event.key === "Escape") {
    closeList();
    input.value = "";
    status.textContent = "";
  }
});

// cerrar al salir del conjunto input+lista, pero NO al clicar una opción
input.addEventListener("focusout", (event) => {
  if (!event.relatedTarget || !listbox.contains(event.relatedTarget)) closeList();
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".field")) closeList();
});
</script>
</body>
</html>
```""",
            ),
            ("tool", """$ node --check /tmp/combobox_inline.js && echo SINTAXIS_OK
SINTAXIS_OK
$ node -e '
const CITIES=["Alicante","A Coruña","Madrid","Palma","Pamplona","Palencia","Valencia","Valladolid"];
function scoreOf(city, q){const c=city.toLowerCase();q=q.toLowerCase();
if(c.startsWith(q))return 3;if(c.includes(q))return 2;
const ini=c.split(/\\s+/).map(w=>w[0]).join("");if(ini.startsWith(q))return 1;return 0;}
const q="pa";console.log(CITIES.map(c=>({c,s:scoreOf(c,q)})).filter(r=>r.s>0)
.sort((a,b)=>b.s-a.s||a.c.length-b.c.length||a.c.localeCompare(b.c,"es")).map(r=>r.c).join(", "));'
Palma, Palencia, Pamplona"""),
            ("assistant", """El segundo comando del tool NO es decoración: reproduce la función de scoring y el desempate EXACTOS del código y los ejecuta en Node — con la consulta «pa» devuelve `Palma, Palencia, Pamplona` (las tres puntúan 3 por `startsWith`; el desempate es por longitud y luego alfabético). Esa parte de la lógica sí está verificada por ejecución; la anatomía ARIA y el teclado requieren navegador.

Los cuatro detalles que hacen «bien hecho» a un combobox:

* `aria-activedescendant` en vez de mover el foco: el foco nunca sale del input, así Enter y las flechas siguen funcionando y los lectores anuncian la opción activa sin perder el contexto del campo.
* `mousedown` con `preventDefault()` para elegir con clic: si escucharas `click`, el `blur` del input cerraría la lista ANTES de que llegue el clic y elegirías… nada.
* El resaltado usa troceado de cadenas con `createTextNode` — nunca `innerHTML` con el término tecleado dentro (otro XSS clásico en autocompletados).
* `aria-expanded` es un contrato: debe ser `false` cuando la lista está cerrada; dejarlo `true` con la lista oculta por CSS es uno de los fallos más comunes en auditorías.

Prueba con teclado: Tab hasta el campo, teclea «co», baja con ↓ dos veces, Enter — debe quedar «A Coruña» o «Córdoba» según el orden calculado y el `status` debe anunciar la selección."""),
        ],
        tags=["html", "javascript", "combobox", "aria", "accesibilidad", "autocomplete"],
        stack=["html", "css", "javascript"],
        verify=[{"name": "html_doctype_y_scripts", "action": "html_check", "lang": "html", "msg": 2, "block": 0}],
        recovery=True,
    ),
    # ---- SIGUE ----
]


