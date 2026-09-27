"""m_web_front2.py — Frontend avanzado, parte 2 (complementaria a m_web_front).

m_web_front.py cubre 9 páginas HTML completas. Este módulo cubre el resto del
territorio frontend con 15 ejemplos COMPLEMENTARIOS:

  * 8 de JavaScript con lógica PURA verificable por node v24 (sin DOM, sin red,
    sin reloj del sistema, deterministas): política de reintentos con
    AbortController, debounce/throttle con reloj inyectado, despachador de
    event delegation, validación de formularios composable, migraciones de
    localStorage con versionado, serialización de estado en URL con
    URLSearchParams, IA minimax con memo/poda y formateador de fechas relativas.
  * 4 de CSS avanzado (verify=[]): el asistente razona la elección técnica y
    explica CÓMO se comprobaría en navegador; nunca se inventa una ejecución.
  * 3 de debugging frontend (recovery=True): listeners duplicados, script
    antes del DOM y fuga de intervalos; el bug se reproduce y se corrige con
    bloques ejecutables en node (mini-mocks deterministas del DOM/timers).

POLÍTICA DE VERIFICACIÓN HONESTA (node v24 no tiene document/window):
  * Lógica pura -> action=run, lang=js, expect_stdout_contains sobre bloques
    ```javascript autocontenidos.
  * CSS -> verify=[]: sin verificación ejecutable; el texto declara qué se
    comprobaría a mano (DevTools, emulación de media/container queries).

Identificadores en inglés; prosa en español. Sin secretos, sin input(), sin red.
"""

from schema import E

EXAMPLES = [
    # ------------------------------------------------------------------ 1
    E(
        language="javascript",
        domain="web",
        subdomain="fetch_retry_abort_backoff",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Nuestro panel de métricas se queda colgado cuando el backend tiene un pico: el `fetch` espera sin límite y, cuando probamos a reintentar «a mano», a veces lanzamos tres peticiones seguidas que llegan todas y triplican la carga. Quiero una política de reintentos seria para el cliente, pero NO pegada al componente: reintentar solo lo que tiene sentido (5xx, 429, 408, fallo de red), respetar el `Retry-After` del servidor, backoff exponencial con tope y jitter para que todos los clientes no reintenten a la vez, y cancelarlo todo en cuanto el usuario cambie de sección (AbortController). El HTML me lo monta otro equipo; yo quiero la LÓGICA de decisión aislada y comprobable con Node, sin red. ¿Cómo la diseñas y cómo la pruebas?"""),
            ("assistant", r"""Antes de escribir código fijo las decisiones que la política debe tomar y en qué orden, porque el orden ES la especificación:

1. Si el `AbortSignal` saltó → `cancelled` (el usuario ya no está: nada de reintentos).
2. Si la respuesta es 2xx → `succeed` (aunque sea el intento N: un éxito nunca es «máximo de intentos»).
3. Si ya fui el intento `maxAttempts` → `giveup` (renunciar ES una decisión, no un olvido).
4. Clasificar: reintentables son fallo de red, 408, 425, 429 y 5xx. Un 404 o un 400 NO se reintentan jamás — reintentarlos es un ataque a tu propio backend.
5. Retardo: exponencial `base·2^(n-1)` con tope (`maxDelayMs`) y jitter multiplicativo ±20 % (un jitter aditivo fijo sincroniza menos de lo que la gente cree); si el servidor envió `Retry-After`, ese valor manda porque el servidor conoce su propia carga.

La función `decideRetry` es PURA: recibe el intento, el resultado y un generador de jitter inyectado. Sin red, sin reloj, sin DOM → testeable con Node tabla a tabla. El jitter usa un LCG con semilla fija: mismo input, mismo delay, siempre.

```javascript
"use strict";

// ── utilidades deterministas ────────────────────────────────────────────────
function makeJitter(seed) {
  let s = seed >>> 0 || 1;
  return function nextJitter() {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296; // [0, 1)
  };
}

const POLICY = {
  maxAttempts: 4,
  baseDelayMs: 200,
  maxDelayMs: 4000,
  jitterRatio: 0.2, // ±20 %
};

// ── decisión PURA: (intento, resultado) → {action, delayMs, reason} ─────────
function decideRetry(attempt, outcome, policy, jitter) {
  if (outcome.kind === "aborted") {
    return { action: "cancelled", delayMs: 0, reason: "AbortSignal disparado" };
  }
  if (outcome.kind === "http" && outcome.status >= 200 && outcome.status < 300) {
    return { action: "succeed", delayMs: 0, reason: "HTTP " + outcome.status };
  }
  if (attempt >= policy.maxAttempts) {
    return { action: "giveup", delayMs: 0, reason: "máximo de " + policy.maxAttempts + " intentos" };
  }
  const st = outcome.status;
  const retryable = outcome.kind === "network"
    || st === 408 || st === 425 || st === 429
    || (st >= 500 && st <= 599);
  if (!retryable) {
    return { action: "giveup", delayMs: 0, reason: "HTTP " + st + " no es reintentable" };
  }
  const exponential = policy.baseDelayMs * 2 ** (attempt - 1);
  const capped = Math.min(exponential, policy.maxDelayMs);
  const jittered = Math.round(capped * (1 + (jitter() * 2 - 1) * policy.jitterRatio));
  const hint = Number(outcome.retryAfterMs) || 0;
  if (hint > jittered) {
    return { action: "retry", delayMs: hint, reason: "respeta Retry-After del servidor" };
  }
  return { action: "retry", delayMs: jittered, reason: "backoff exponencial" };
}

// ── driver de simulación: sustituye a fetch, cero red ───────────────────────
function runScenario(name, outcomes, log) {
  const jitter = makeJitter(42);
  log("escenario: " + name);
  let attempt = 0;
  let t = 0;
  for (const outcome of outcomes) {
    attempt += 1;
    log("  t=" + String(t).padStart(4) + "ms  intento " + attempt + " → " + outcome.label);
    const d = decideRetry(attempt, outcome, POLICY, jitter);
    if (d.action === "retry") {
      log("    └─ " + d.reason + " → reintento en " + d.delayMs + "ms");
      t += d.delayMs;
    } else if (d.action === "succeed") {
      log("    └─ OK: " + d.reason + " → entrega la respuesta a la UI");
      return;
    } else {
      log("    └─ " + d.action.toUpperCase() + ": " + d.reason);
      return;
    }
  }
}

const line = [];
const log = (s) => line.push(s);

runScenario("pico de 503 sostenido", [
  { kind: "http", status: 503, label: "HTTP 503 (overloaded)" },
  { kind: "http", status: 503, label: "HTTP 503 (overloaded)" },
  { kind: "http", status: 503, label: "HTTP 503 (overloaded)" },
  { kind: "http", status: 503, label: "HTTP 503 (overloaded)" },
], log);

runScenario("429 con Retry-After y luego 200", [
  { kind: "http", status: 429, retryAfterMs: 1500, label: "HTTP 429 (Retry-After: 1.5s)" },
  { kind: "http", status: 200, label: "HTTP 200" },
], log);

runScenario("404 definitivo", [
  { kind: "http", status: 404, label: "HTTP 404" },
], log);

runScenario("el usuario navega a otra sección", [
  { kind: "http", status: 503, label: "HTTP 503 (overloaded)" },
  { kind: "aborted", label: "abort durante la espera" },
], log);

// ── autoverificación de las decisiones clave ────────────────────────────────
const j = makeJitter(7);
const checks = [
  decideRetry(4, { kind: "http", status: 503 }, POLICY, j).action === "giveup",
  decideRetry(1, { kind: "http", status: 404 }, POLICY, j).reason === "HTTP 404 no es reintentable",
  decideRetry(2, { kind: "http", status: 200 }, POLICY, j).action === "succeed",
  decideRetry(1, { kind: "aborted" }, POLICY, j).action === "cancelled",
  decideRetry(1, { kind: "http", status: 429, retryAfterMs: 9000 }, POLICY, j).delayMs === 9000,
];
console.log(line.join("\n"));
console.log("AUTOVERIFICACIÓN: " + checks.filter(Boolean).length + "/" + checks.length + " decisiones esperadas");
if (checks.some((c) => !c)) process.exit(1);
```"""),
            ("tool", r"""$ node politica_reintentos.mjs
escenario: pico de 503 sostenido
  t=   0ms  intento 1 → HTTP 503 (overloaded)
    └─ backoff exponencial → reintento en 180ms
  t= 180ms  intento 2 → HTTP 503 (overloaded)
    └─ backoff exponencial → reintento en 334ms
  t= 514ms  intento 3 → HTTP 503 (overloaded)
    └─ backoff exponencial → reintento en 825ms
  t=1339ms  intento 4 → HTTP 503 (overloaded)
    └─ GIVEUP: máximo de 4 intentos
escenario: 429 con Retry-After y luego 200
  t=   0ms  intento 1 → HTTP 429 (Retry-After: 1.5s)
    └─ respeta Retry-After del servidor → reintento en 1500ms
  t=1500ms  intento 2 → HTTP 200
    └─ OK: HTTP 200 → entrega la respuesta a la UI
escenario: 404 definitivo
  t=   0ms  intento 1 → HTTP 404
    └─ GIVEUP: HTTP 404 no es reintentable
escenario: el usuario navega a otra sección
  t=   0ms  intento 1 → HTTP 503 (overloaded)
    └─ backoff exponencial → reintento en 180ms
  t= 180ms  intento 2 → abort durante la espera
    └─ CANCELLED: AbortSignal disparado
AUTOVERIFICACIÓN: 5/5 decisiones esperadas
$ echo $?
0"""),
            ("assistant", r"""Lo que acaba de ejecutarse NO es pseudocódigo: es el bloque completo en Node, sin red y sin reloj real. Fíjate en tres pruebas que suelen faltar en las políticas «caseras»: un 200 en el intento 4 se entrega igualmente (`succeed` antes del check de máximo), un 404 se abandona al primer golpe y un `Retry-After: 9000` se respeta aunque el backoff diga otra cosa.

Para llevarlo al navegador, el componente solo necesita un bucle que traduzca `fetch` al vocabulario de `decideRetry`:

```javascript
async function loadWithRetries(url, { signal, policy = POLICY, seed = 42 } = {}) {
  const jitter = makeJitter(seed);
  for (let attempt = 1; ; attempt++) {
    const outcome = await attemptOnce(url, signal); // fetch + signal → {kind, status, retryAfterMs}
    const decision = decideRetry(attempt, outcome, policy, jitter);
    if (decision.action !== "retry") return outcome;  // succeed / giveup / cancelled
    await sleep(decision.delayMs, signal);            // rechaza en cuanto el signal salte
  }
}
```

Donde `attemptOnce` mapea `fetch`: `TypeError` de red → `kind:"network"`, y `Retry-After` (segundos o fecha HTTP) → `retryAfterMs`. Dos detalles que marcan la diferencia en producción: (1) la SEMILLA del jitter puede derivarse de la URL, así el test reproduce la secuencia exacta que viste en el log; (2) `sleep` debe rechazar con el `AbortError` del signal, no esperar el retardo completo — si no, la cancelación llega tarde aunque la decisión fuera correcta. Lo que NO he verificado aquí es la interacción con el navegador real (timeouts del `fetch`, streaming): eso se comprueba contra el backend de staging con una regla de(rate-limit) a propósito."""),
        ],
        tags=["javascript", "fetch", "abortcontroller", "retry", "backoff", "jitter"],
        stack=["javascript"],
        verify=[
            {"name": "logica_pura_node", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": [
                 "GIVEUP: máximo de 4 intentos",
                 "respeta Retry-After del servidor → reintento en 1500ms",
                 "HTTP 404 no es reintentable",
                 "CANCELLED: AbortSignal disparado",
                 "AUTOVERIFICACIÓN: 5/5 decisiones esperadas",
             ]},
        ],
    ),
    # ------------------------------------------------------------------ 2
    E(
        language="javascript",
        domain="web",
        subdomain="debounce_throttle_clock",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Tengo dos problemas opuestos y quiero resolverlos con las utilidades correctas, no a base de parchear. (1) En el editor, cada tecla dispara el autoguardado: quiero que espere a que el usuario «se pare a respirar» y guarde solo la última versión. (2) En el dashboard, el `resize` recalcula un layout caro: quiero que se ejecute como mucho una vez cada cierto intervalo, pero SIN perder el último valor (si el último evento ocurre dentro del intervalo, tiene que acabar aplicándose). Necesito `debounce` y `throttle` hechos a mano, que acepten cancelación, y sobre todo: tests que no tarden 5 segundos ni dependan del azar — he leído que lo suyo es inyectar el reloj, pero no veo cómo. ¿Me lo montas?"""),
            ("assistant", r"""Buen instinto con el reloj: si `debounce` llama a `setTimeout` global, tu test DORMIRÁ 300 ms y seguirá siendo frágil (el scheduler de CI puede retrasarse). La solución es invertir la dependencia: `debounce(fn, wait, clock)` y `throttle(fn, wait, clock, opts)` reciben un reloj con la superficie mínima que usan (`now`, `setTimeout`, `clearTimeout`). En producción pasa `window`-compatible; en tests, un reloj manual cuyo `advance(ms)` ejecuta las tareas vencidas en orden. Los tests avanzan el tiempo «instantáneamente» y son 100 % deterministas.

Decisiones de semántica que fijo antes del código: (1) debounce SOLO trailing edge (el autoguardado quiere el último valor; el leading edge dispararía un guardado con datos a medio escribir); (2) throttle leading + trailing (la primera invocación es inmediata — feedback instantáneo del resize — y el último evento dentro del intervalo se aplica al vencer el temporizador, que es justo lo que pedías); (3) `cancel()` explícito en ambos, porque «desmontar el componente» debe dejar cero temporizadores vivos.

```javascript
"use strict";

// ── reloj inyectable: nada de Date ni setTimeout reales → determinismo ──────
function createFakeClock() {
  let now = 0;
  let nextId = 1;
  const tasks = new Map(); // id → { at, fn }
  function runDue() {
    for (;;) {
      let best = null;
      for (const [id, task] of tasks) {
        if (task.at <= now && (best === null || task.at < best.task.at)) best = { id, task };
      }
      if (!best) return;
      tasks.delete(best.id);
      best.task.fn();
    }
  }
  return {
    now: () => now,
    setTimeout(fn, ms) { const id = nextId++; tasks.set(id, { at: now + ms, fn }); return id; },
    clearTimeout(id) { tasks.delete(id); },
    advance(ms) { now += ms; runDue(); },
  };
}

// ── debounce (trailing edge) con cancelación explícita ──────────────────────
function debounce(fn, wait, clock) {
  let timerId = null;
  function debounced(...args) {
    if (timerId !== null) clock.clearTimeout(timerId);
    timerId = clock.setTimeout(() => { timerId = null; fn(...args); }, wait);
  }
  debounced.cancel = () => { if (timerId !== null) { clock.clearTimeout(timerId); timerId = null; } };
  return debounced;
}

// ── throttle (leading + trailing) clásico ───────────────────────────────────
function throttle(fn, wait, clock, { leading = true, trailing = true } = {}) {
  let lastInvokeTime = null; // instante de la última invocación REAL
  let timerId = null;
  let savedArgs = null;
  function invoke(args) { lastInvokeTime = clock.now(); fn(...args); }
  function armTrailing() {
    const remaining = wait - (clock.now() - lastInvokeTime);
    timerId = clock.setTimeout(() => {
      timerId = null;
      if (savedArgs !== null) {
        const args = savedArgs;
        savedArgs = null;
        if (trailing) invoke(args); else lastInvokeTime = clock.now();
      }
    }, remaining);
  }
  return function throttled(...args) {
    const now = clock.now();
    if (lastInvokeTime === null) {
      if (leading) invoke(args);
      else { savedArgs = args; armTrailing(); }
      return;
    }
    const elapsed = now - lastInvokeTime;
    if (elapsed >= wait) {
      if (timerId !== null) { clock.clearTimeout(timerId); timerId = null; savedArgs = null; }
      invoke(args);
      return;
    }
    savedArgs = args;
    if (timerId === null) armTrailing();
  };
}

// ── escenario A: autoguardado de borrador con debounce de 100 ms ────────────
{
  const clock = createFakeClock();
  const saves = [];
  const save = (version) => saves.push({ at: clock.now(), version });
  const debouncedSave = debounce(save, 100, clock);

  const keystrokes = ["v1", "v2", "v3", "v4", "v5"];
  const times = [];
  for (const k of keystrokes) {
    clock.advance(40);
    times.push(clock.now());
    debouncedSave(k);
  }
  console.log("[debounce] teclas en t=" + times.join(",") + "ms (espera 100ms)");
  clock.advance(300); // tiempo suficiente para que venza el temporizador
  console.log("[debounce] guardado en t=" + saves[0].at + "ms con \"" + saves[0].version + "\"");

  // llega otra tecla, pero el componente se desmonta → cancel()
  clock.advance(40);
  debouncedSave("v6");
  debouncedSave.cancel();
  clock.advance(300);
  console.log("[debounce] guardados=" + saves.length + " de " + (keystrokes.length + 1) + " llamadas (cancel() evitó el segundo)");
}

// ── escenario B: recálculo de layout en resize con throttle de 80 ms ────────
{
  const clock = createFakeClock();
  const renders = [];
  const relayout = (w) => renders.push({ at: clock.now(), w });
  const throttledRelayout = throttle(relayout, 80, clock);

  const widths = [1280, 1266, 1240, 1225, 1210, 1180, 1152];
  const fired = [];
  for (const w of widths) {
    clock.advance(30);
    fired.push("t=" + clock.now());
    throttledRelayout(w);
  }
  console.log("[throttle] resize en " + fired.join(" ") + "ms (7 eventos, intervalo 80ms)");
  clock.advance(300); // deja vencer el trailing edge pendiente
  console.log("[throttle] render en t=" + renders.map((r) => r.at).join(", t="));
  console.log("[throttle] última anchura renderizada=" + renders[renders.length - 1].w + " (trailing siempre usa el ÚLTIMO valor)");
  console.log("[throttle] RENDERS=" + renders.length + " de " + widths.length + " eventos");
}
```"""),
            ("tool", r"""$ node debounce_throttle.test.mjs
[debounce] teclas en t=40,80,120,160,200ms (espera 100ms)
[debounce] guardado en t=500ms con "v5"
[debounce] guardados=1 de 6 llamadas (cancel() evitó el segundo)
[throttle] resize en t=30 t=60 t=90 t=120 t=150 t=180 t=210ms (7 eventos, intervalo 80ms)
[throttle] render en t=30, t=120, t=210, t=510
[throttle] última anchura renderizada=1152 (trailing siempre usa el ÚLTIMO valor)
[throttle] RENDERS=4 de 7 eventos
$ echo $?
0"""),
            ("assistant", r"""La salida merece lectura lenta, porque ahí se ve la semántica:

* Debounce: 6 llamadas, 1 guardado, y el log dice `t=500ms` aunque la última tecla fue en 200 — el reloj simulado avanza a saltos, así que el temporizador vencido se ejecuta en el siguiente `advance`. Es exactamente la misma abstracción que usa `vi.useFakeTimers()`. `cancel()` demuestra que desmontar el componente no deja guardados fantasma.
* Throttle: 7 eventos → 4 renders. El `t=30` es el leading edge (respuesta inmediata), los de `120/210` son trailing edges con los datos «de mitad de ráfaga» y el `t=510` aplica el ÚLTIMO valor (1152 px). Si tu `throttle` perdiera ese último evento — el bug clásico de las implementaciones con solo leading — el layout quedaría desincronizado con el ancho real.

Cómo lo comprobarías en el proyecto real: (1) en Node, este mismo fichero como test (cualquier runner vale; no usa APIs de Node más allá de `console`); (2) en el navegador, en la pestaña Performance verás que con throttle el recálculo de layout aparece como mucho una vez por intervalo aunque arrastres el divisor como un poseso; y (3) si algún día necesitas leading en el debounce (un botón «guardar ahora»), el cambio es añadir un flag que dispare en la PRIMERA llamada y suprima la última — la prueba con reloj inyectado ya está montada para ello."""),
        ],
        tags=["javascript", "debounce", "throttle", "reloj-inyectado", "determinismo", "rendering"],
        stack=["javascript"],
        verify=[
            {"name": "logica_pura_node", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": [
                 "[debounce] guardados=1 de 6 llamadas",
                 "[throttle] RENDERS=4 de 7 eventos",
                 "última anchura renderizada=1152",
             ]},
        ],
    ),
    # ------------------------------------------------------------------ 3
    E(
        language="javascript",
        domain="web",
        subdomain="event_delegation_dispatch",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Nuestra lista de tareas se re-renderiza entera cada vez que llega un dato del servidor, y hoy mismo hemos visto en el profiler que cada render vuelve a hacer `addEventListener` en cada botón: unos milisegundos que no tenemos y, temo, duplicados ocultos. Quiero pasar a event delegation con UN solo listener en el `<ul>`, pero bien hecho: la decisión de «qué acción es este clic» quiero tenerla en una función aparte que yo pueda testear sin navegador, porque la última vez que pusimos `data-*` a mano nos equivocamos con el burbujeo y un clic en el icono del botón no hacía nada. ¿Cómo separas el despacho del efecto?"""),
            ("assistant", r"""Vas a separar dos capas que casi siempre van mal acopladas:

1. **Despacho (puro)**: `resolveClick(target)` recorre ascendentes con la semántica de `closest()` y devuelve una ACCIÓN descrita con datos: `{kind:"todo:toggle", payload:"t3"}`, `{kind:"outside"}` o `{kind:"ignored", ...}`. No muta nada, no sabe qué es un `<li>`, solo lee atributos. Esa función es la que testearás en Node con un mini-DOM de objetos y enlaces `parent`.
2. **Efecto (impuro, mínimo)**: un único `ul.addEventListener("click", …)` que llama a `resolveClick(event.target)` y aplica la acción a través de un reducer. Los `<li>` regenerados no llevan listeners: es literalmente imposible que se dupliquen.

Detalles que hacen que la delegación sea «bien hecha» y no «un listener en el ul y a correr»: el `closest` debe buscar `data-action` en CUALQUIER ascendente (un `<svg>` dentro del botón burbujea al botón — tu bug de los iconos); un botón deshabilitado no se modela con el atributo HTML `disabled` (que ni dispara click en algunos casos ni burbujea igual) sino con `data-disabled` que el despachador respeta; y los clics fuera de toda zona con acción se convierten en una acción `outside` explícita (cerrar menús, quitar selección) en vez de ignorarse en silencio.

```javascript
"use strict";

// ── mini-DOM: solo lo que la delegación necesita (padres + atributos) ───────
function el(tag, attrs, children = []) {
  const node = { tag, attrs: attrs || {}, children };
  node.closest = function (match) {
    let n = this;
    while (n) { if (match(n)) return n; n = n.parent; }
    return null;
  };
  children.forEach((c) => { c.parent = node; });
  return node;
}
const hasDataAction = (n) => typeof n.attrs["data-action"] === "string";
const hasDataId = (n) => typeof n.attrs["data-id"] === "string";

// ── estado de la lista de tareas ────────────────────────────────────────────
let items = [
  { id: "t1", label: "Revisar PR #142", done: true },
  { id: "t2", label: "Actualizar dependencias", done: false },
  { id: "t3", label: "Responder soporte", done: false },
];

// ── despachador PURO: (target) → acción. No muta nada. ─────────────────────
// Es la función que ejecutaría el ÚNICO addEventListener del contenedor.
function resolveClick(target) {
  const actionable = target.closest(hasDataAction);
  if (!actionable) return { kind: "outside", payload: null };
  if (actionable.attrs["data-disabled"] === "true") {
    return { kind: "ignored", payload: actionable.attrs["data-action"] };
  }
  const row = actionable.closest(hasDataId);
  return { kind: actionable.attrs["data-action"], payload: row ? row.attrs["data-id"] : null };
}

// ── reducer puro: (estado, acción) → estado nuevo ───────────────────────────
function reduce(state, action) {
  switch (action.kind) {
    case "todo:toggle":
      return state.map((it) => (it.id === action.payload ? { ...it, done: !it.done } : it));
    case "todo:remove":
      return state.filter((it) => it.id !== action.payload);
    case "todo:clear-done":
      return state.filter((it) => !it.done);
    case "select":
      return state.map((it) => ({ ...it, selected: it.id === action.payload }));
    default:
      return state;
  }
}

// ── árbol: <ul data-delegation-root> con <li data-id> → <button data-action> ─
const icon = el("svg.icon", {});
const toggleBtn3 = el("button", { "data-action": "todo:toggle" }, [icon]);
const li3 = el("li", { "data-id": "t3" }, [toggleBtn3, el("span.text", {})]);

const removeBtn2 = el("button", { "data-action": "todo:remove", "data-disabled": "true" }, []);
const li2 = el("li", { "data-id": "t2" }, [removeBtn2, el("span.text", {})]);

const removeBtn1 = el("button", { "data-action": "todo:remove" }, []);
const li1 = el("li", { "data-id": "t1" }, [removeBtn1, el("span.text", {})]);

const clearDoneBtn = el("button", { "data-action": "todo:clear-done" }, []);
const footer = el("footer", {}, [clearDoneBtn]);

const tree = el("ul", { "data-delegation-root": "" }, [li1, li2, li3, footer]);

// ── clicks scripted (un solo listener real procesaría todos) ────────────────
const clicks = [
  ["svg.icon del toggle de t3", icon],
  ["span.text de t2 (sin botón)", li2.children[1]],
  ["botón remove de t1", removeBtn1],
  ["botón remove de t2 (deshabilitado)", removeBtn2],
  ["botón «limpiar completadas» del footer", clearDoneBtn],
];

let dispatched = 0, ignored = 0, outside = 0;
for (const [where, target] of clicks) {
  const action = resolveClick(target);
  if (action.kind === "ignored") { ignored += 1; console.log("click en " + where + " → IGNORADO (" + action.payload + " deshabilitado)"); continue; }
  if (action.kind === "outside") { outside += 1; console.log("click en " + where + " → outside: cerrar menú contextual (sin cambio de estado)"); continue; }
  dispatched += 1;
  items = reduce(items, action);
  console.log("click en " + where + " → " + action.kind + (action.payload ? " id=" + action.payload : "") + " → estado: "
    + items.map((i) => i.id + (i.done ? "[✓]" : "[ ]")).join(" "));
}

console.log("resumen: despachadas=" + dispatched + " ignoradas=" + ignored + " outside=" + outside);
console.log("listeners instalados en total: 1 (en <ul data-delegation-root>); los <li> se re-renderizan sin re-bind");
```"""),
            ("tool", r"""$ node delegacion.test.mjs
click en svg.icon del toggle de t3 → todo:toggle id=t3 → estado: t1[✓] t2[ ] t3[✓]
click en span.text de t2 (sin botón) → outside: cerrar menú contextual (sin cambio de estado)
click en botón remove de t1 → todo:remove id=t1 → estado: t2[ ] t3[✓]
click en botón remove de t2 (deshabilitado) → IGNORADO (todo:remove deshabilitado)
click en botón «limpiar completadas» del footer → todo:clear-done → estado: t2[ ]
resumen: despachadas=3 ignoradas=1 outside=1
listeners instalados en total: 1 (en <ul data-delegation-root>); los <li> se re-renderizan sin re-bind
$ echo $?
0"""),
            ("assistant", r"""La primera línea resuelve tu bug de los iconos: el clic cae en el `<svg>` y `closest` asciende hasta el botón con `data-action` — la acción es del botón, no del icono. Y la cuarta muestra por qué el despachador decide sobre `data-disabled`: la política («este botón hoy no funciona») vive en un sitio testeable, no esparcida entre `disabled`, clases y CSS.

En el navegador, la capa impura queda en tres líneas y ya no depende del re-render:

```javascript
list.addEventListener("click", (event) => {
  const action = resolveClick(event.target);
  if (action.kind !== "outside" && action.kind !== "ignored") {
    items = reduce(items, action);
    renderList(items);
  }
});
```

Dos refinamientos para cuando lo lleves a producción: (1) para teclado, escucha también `keydown` en el mismo contenedor y mapea `Enter`/`Space` sobre `event.target` — la accesibilidad sale gratis porque la acción es la misma; (2) si los re-renders son frecuentes, combina esto con un `AbortController` por ciclo de vida del widget: `addEventListener(…, { signal })` y un solo `abort()` al desmontar. Deja de medir «milisegundos de re-bind»: con delegación el coste de registrar listeners es O(1) con independencia de cuántas filas renderices."""),
        ],
        tags=["javascript", "event-delegation", "closest", "reducer", "dom", "testabilidad"],
        stack=["javascript"],
        verify=[
            {"name": "logica_pura_node", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": [
                 "todo:toggle id=t3 → estado: t1[✓] t2[ ] t3[✓]",
                 "IGNORADO (todo:remove deshabilitado)",
                 "resumen: despachadas=3 ignoradas=1 outside=1",
                 "listeners instalados en total: 1",
             ]},
        ],
    ),
    # ------------------------------------------------------------------ 4
    E(
        language="javascript",
        domain="web",
        subdomain="form_validation_composable",
        difficulty="medium",
        task_type="implementation",
        messages=[
            ("user", r"""El formulario de alta ha crecido a base de `if`s: ahora mismo `validarAlta()` mide longitudes, mira el email con un indexOf, y encima hay un campo de teléfono que solo es obligatorio cuando en «preferencia de contacto» se elige teléfono (y otro `@usuario@instancia` si se elige Mastodon). Cada validación nueva rompe otra vieja. Quiero reglas pequeñas e independientes que se COMBINEN, con los errores agregados por campo (no «el primer error y ya»), y todo en funciones puras que pueda testear con Node para dejar de probar a mano el formulario entero en cada deploy."""),
            ("assistant", r"""El problema de `validarAlta()` es que mezcla TRES conceptos: la regla (una función pequeña), la política de composición (¿todas? ¿condicional?) y el agregado (errores por campo). Los separo:

* **Regla**: `(valor, formulario) → string | null`. Recibe el formulario entero porque algunas reglas comparan campos (`sameAs`) y otras dependen de otros (`when`).
* **Combinadores**: `all(...reglas)` ejecuta todas y agrega (nunca corta en el primer fallo: el usuario merece la lista completa); `when(condición, regla)` activa una regla solo si la condición del formulario se cumple.
* **Esquema**: mapa `campo → regla combinada`; el validador genérico lo recorre y devuelve `{ ok, errors }`. Añadir un campo es añadir una línea.

Dos convenciones que evitan el ruido clásico: las reglas de formato (`pattern`, `minLength`) IGNORAN el valor vacío — «obligatorio» ya lo comunica `required`, y duplicar el error en dos frases confunde; y el email se valida con una regex pragmática de forma (`algo@algo.tld`), no con el monstruo RFC-5322: la prueba real del email es el correo de confirmación, la regex solo elimina erratas.

```javascript
"use strict";

// ── reglas atómicas: (valor, formulario) → string | null ────────────────────
const V = {
  required: (msg = "campo obligatorio") => (v) =>
    (v === undefined || v === null || String(v).trim() === "" ? msg : null),
  minLength: (n) => (v) =>
    (v != null && v !== "" && v.length < n ? "mínimo " + n + " caracteres" : null),
  pattern: (re, msg) => (v) =>
    (v != null && v !== "" && !re.test(v) ? msg : null),
  sameAs: (field) => (v, form) =>
    (v !== form[field] ? "las contraseñas no coinciden" : null),
};

// ── combinadores: componen reglas sin acoplarlas ────────────────────────────
const all = (...rules) => (v, form) => rules.map((r) => r(v, form)).filter(Boolean);
const when = (cond, rule) => (v, form) => (cond(form) ? [].concat(rule(v, form)).filter(Boolean) : []);

// ── esquema del formulario de alta ──────────────────────────────────────────
const schema = {
  email: all(
    V.required(),
    V.pattern(/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/, "email no válido"),
  ),
  password: all(
    V.required(),
    V.minLength(10),
    V.pattern(/[0-9]/, "debe incluir un dígito"),
    V.pattern(/[A-Z]/, "debe incluir una mayúscula"),
  ),
  confirm: all(V.required(), V.sameAs("password")),
  contactPref: all(V.required()),
  phone: when(
    (form) => form.contactPref === "phone",
    V.required("teléfono obligatorio si el contacto es por teléfono"),
  ),
  handle: when(
    (form) => form.contactPref === "mastodon",
    V.pattern(/^@[A-Za-z0-9_]+@[A-Za-z0-9.\-]+$/, "formato @usuario@instancia"),
  ),
};

// ── validador genérico: (esquema, valores) → { ok, errors } ─────────────────
function validate(schema, values) {
  const errors = {};
  for (const [field, rules] of Object.entries(schema)) {
    const errs = rules(values[field], values);
    if (errs.length) errors[field] = errs;
  }
  return { ok: Object.keys(errors).length === 0, errors };
}

function show(label, values) {
  const { ok, errors } = validate(schema, values);
  const fields = Object.keys(schema);
  const summary = fields.map((f) => f + "=" + (errors[f] ? errors[f].length + " error(es)" : "ok")).join(" ");
  console.log("envío " + label + " → " + (ok ? "SUBMIT_OK" : summary));
  for (const [f, errs] of Object.entries(errors)) {
    console.log("  · " + f + ": " + errs.join(" | "));
  }
  return ok;
}

// A) todo vacío (primer envío accidental)
const a = show("A (vacío)", {
  email: "", password: "", confirm: "", contactPref: "", phone: "", handle: "",
});

// B) email mal, contraseña débil, confirmación desigual, handle de Mastodon mal
const b = show("B (con fallos)", {
  email: "ana@cafe",
  password: "wiki",
  confirm: "wikis",
  contactPref: "mastodon",
  phone: "",
  handle: "@ana",
});

// C) correcto; contacto por teléfono condiciona el campo phone
const c = show("C (correcto)", {
  email: "ana@example.com",
  password: "CorrectHorse1",
  confirm: "CorrectHorse1",
  contactPref: "phone",
  phone: "+34 600 123 456",
  handle: "",
});

// D) correcto; contacto por Mastodon y el campo phone NO se exige (when)
const d = show("D (correcto, sin teléfono)", {
  email: "luis@example.com",
  password: "StapleTone9",
  confirm: "StapleTone9",
  contactPref: "mastodon",
  phone: "",
  handle: "@luis@hachyderm.io",
});

const checks = [a === false, b === false, c === true, d === true];
console.log("AUTOVERIFICACIÓN: " + checks.filter(Boolean).length + "/4 envíos con el resultado esperado");
if (checks.some((x) => !x)) process.exit(1);
```"""),
            ("tool", r"""$ node validacion_alta.test.mjs
envío A (vacío) → email=1 error(es) password=1 error(es) confirm=1 error(es) contactPref=1 error(es) phone=ok handle=ok
  · email: campo obligatorio
  · password: campo obligatorio
  · confirm: campo obligatorio
  · contactPref: campo obligatorio
envío B (con fallos) → email=1 error(es) password=3 error(es) confirm=1 error(es) contactPref=ok phone=ok handle=1 error(es)
  · email: email no válido
  · password: mínimo 10 caracteres | debe incluir un dígito | debe incluir una mayúscula
  · confirm: las contraseñas no coinciden
  · handle: formato @usuario@instancia
envío C (correcto) → SUBMIT_OK
envío D (correcto, sin teléfono) → SUBMIT_OK
AUTOVERIFICACIÓN: 4/4 envíos con el resultado esperado
$ echo $?
0"""),
            ("assistant", r"""Los cuatro envíos cubren la matriz que antes probabas a mano: vacío, inválido, válido con regla condicional activa y válido con regla condicional DORMIDA — ese cuarto caso es el que más bugs silenciosos esconde (si `when` estuviera mal, D pediría teléfono sin motivo y C pasaría sin él). El envío B además demuestra el agregado: la contraseña acumula sus tres razones en una sola línea.

Para conectarlo a la UI sin perder la pureza: el `submit` llama a `validate(schema, valoresDelFormulario)` y pinta `errors`; si quieres validación «al salir del campo», llama al validador por campo (`schema.email(valor, valores)`) en el evento `blur` — misma fuente de verdad, cero duplicación con el HTML. Y no tires la capa nativa: pon `required`, `type="email"`, `minlength` y `pattern` en el markup también; el validador JS da los MENSAJES agregados y la capa nativa protege al usuario si el JS tarda o falla. Lo que no he comprobado aquí es el comportamiento con lectores de pantalla de los mensajes dinámicos (`aria-describedby`/`aria-live`): eso se audita aparte."""),
        ],
        tags=["javascript", "validacion", "composicion", "formularios", "funciones-puras"],
        stack=["javascript"],
        verify=[
            {"name": "logica_pura_node", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": [
                 "password: mínimo 10 caracteres | debe incluir un dígito | debe incluir una mayúscula",
                 "confirm: las contraseñas no coinciden",
                 "handle: formato @usuario@instancia",
                 "AUTOVERIFICACIÓN: 4/4 envíos con el resultado esperado",
             ]},
        ],
    ),
    # ------------------------------------------------------------------ 5
    E(
        language="javascript",
        domain="web",
        subdomain="localstorage_schema_migrations",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Guardamos las preferencias y el estado de la app en `localStorage` bajo una clave fija, y ese documento ha cambiado tres veces desde el año pasado: metimos el tema dentro de `prefs`, convertimos la lista de archivos recientes de strings a objetos con fecha, y añadimos el idioma. Resultado: hay usuarios con datos v1, con datos v2, con datos v3, uno que me dice que la app «se le resetea» (sospecho JSON corrupto a medio escribir) y otro que la abrió con un build de pruebas que escribía un formato MÁS NUEVO que el de producción. Quiero versionado de esquema con migraciones y una carga que no reviente NUNCA, pero la lógica aislada del navegador para poder testearla."""),
            ("assistant", r"""Trataré `localStorage` como lo que es: un almacén clave→string SIN esquema. El esquema lo pone tu documento, y las versiones son un contrato explícito. Diseño:

* Cada migración es una función pura `v(n-1) → v(n)` en un mapa `MIGRATIONS`. Encadenar es recorrer `while (version < target)`. Las migraciones pueden AÑADIR y también RETIRAR campos: la función devuelve el documento nuevo completo (no un parche), así ninguna clave vieja queda zombi.
* `loadSafe(raw)` nunca lanza: JSON roto, raíz no-objeto, versión futura (¡tu caso del build de pruebas!) o migración ausente devuelven `{ok:false, reason}` con una causa legible. La versión futura NO se toca: migrarla «hacia abajo» destruiría datos que el otro build sabe leer.
* La tienda (`createStore`) añade la capa impura: respaldo `.bak` de la última copia buena conocida. Si la clave principal está corrupta, se recupera del respaldo y se re-migra; si también está mal, se recrea el documento por defecto y se deja constancia.

```javascript
"use strict";

// ── almacenamiento inyectable con la MISMA superficie que localStorage ──────
function createMemoryStorage(seedEntries = {}) {
  const map = new Map(Object.entries(seedEntries));
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    keys: () => [...map.keys()],
  };
}

// ── evolución del esquema del documento ─────────────────────────────────────
// v1: { schemaVersion, userName, theme, recent: string[] }
// v2: theme se mete en prefs { theme, density }
// v3: recent (strings) → recentFiles ({path, openedAt})
// v4: prefs.lang se añade
const CURRENT_VERSION = 4;
const MIGRATIONS = {
  1: (d) => {
    const { theme, ...rest } = d;
    return { ...rest, prefs: { theme: theme || "light", density: "comfortable" } };
  },
  2: (d) => {
    const { recent, ...rest } = d;
    return { ...rest, recentFiles: (recent || []).map((p) => ({ path: p, openedAt: 0 })) };
  },
  3: (d) => ({ ...d, prefs: { ...d.prefs, lang: "es" } }),
};

function defaultDoc(version) {
  return {
    schemaVersion: version,
    userName: "",
    prefs: { theme: "light", density: "comfortable", lang: "es" },
    recentFiles: [],
  };
}

// ── loadSafe/migrate: núcleo PURO, sin tocar el storage ─────────────────────
function migrate(rawDoc, target, migrations = MIGRATIONS) {
  let version = Number.isInteger(rawDoc.schemaVersion) ? rawDoc.schemaVersion : 1;
  let doc = { ...rawDoc };
  const steps = [];
  while (version < target) {
    const step = migrations[version];
    if (!step) return { ok: false, reason: "falta la migración " + version + "→" + (version + 1), steps };
    let next;
    try {
      next = step(doc);
    } catch (err) {
      return { ok: false, reason: "migración " + version + "→" + (version + 1) + " lanzó: " + err.message, steps };
    }
    if (typeof next !== "object" || next === null) {
      return { ok: false, reason: "la migración " + version + "→" + (version + 1) + " no devolvió documento", steps };
    }
    doc = next; // reemplazo íntegro: las migraciones también pueden RETIRAR campos
    version += 1;
    steps.push(version);
  }
  doc.schemaVersion = target;
  return { ok: true, doc, steps };
}

function loadSafe(raw, target = CURRENT_VERSION) {
  if (raw === null) return { ok: true, doc: defaultDoc(target), steps: [], note: "sin datos → documento nuevo" };
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    return { ok: false, reason: "JSON corrupto (" + err.message.split(" at ")[0].trim() + ")", steps: [] };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { ok: false, reason: "el documento no es un objeto", steps: [] };
  }
  if (Number.isInteger(parsed.schemaVersion) && parsed.schemaVersion > target) {
    return { ok: false, reason: "versión futura " + parsed.schemaVersion + " (este build soporta ≤ " + target + ")", steps: [] };
  }
  return migrate(parsed, target);
}

// ── tienda: usa loadSafe y mantiene una copia de respaldo ───────────────────
function createStore(storage, key = "app:doc") {
  const bakKey = key + ".bak";
  function save(doc) {
    const prev = storage.getItem(key);
    if (prev !== null) storage.setItem(bakKey, prev); // última copia buena conocida
    const stamped = { ...doc, schemaVersion: CURRENT_VERSION };
    storage.setItem(key, JSON.stringify(stamped));
  }
  function load() {
    const primary = loadSafe(storage.getItem(key));
    if (primary.ok) return { ...primary, viaBackup: false };
    const backup = loadSafe(storage.getItem(bakKey));
    if (backup.ok) return { ...backup, viaBackup: true, primaryReason: primary.reason };
    return { ok: true, doc: defaultDoc(CURRENT_VERSION), steps: [], recreated: true, primaryReason: primary.reason };
  }
  return { save, load, storage };
}

// caso 1: documento legítimo de hace meses, aún en v1
{
  const st = createMemoryStorage({ "app:doc": JSON.stringify({ schemaVersion: 1, userName: "ana", theme: "dark", recent: ["a.txt", "b.txt"] }) });
  const r = createStore(st).load();
  console.log("caso 1 · doc v1 legítimo → " + (r.ok ? "ok" : "FALLO") + " pasos=" + r.steps.length + " (1→" + CURRENT_VERSION + ")");
  console.log("  resultado: " + JSON.stringify(r.doc));
}

// caso 2: la clave principal se corrompe; hay backup en v3
{
  const st = createMemoryStorage({ "app:doc": '{"schemaVersion":3,"userName":"ana",', "app:doc.bak": JSON.stringify({ schemaVersion: 3, userName: "ana", prefs: { theme: "light", density: "comfortable" }, recentFiles: [{ path: "a.txt", openedAt: 0 }] }) });
  const r = createStore(st).load();
  console.log("caso 2 · JSON corrupto + backup v3 → viaBackup=" + r.viaBackup + " motivo primario: " + r.primaryReason);
  console.log("  resultado: " + JSON.stringify(r.doc));
}

// caso 3: el documento lo escribió un build futuro (v9)
{
  const r = loadSafe(JSON.stringify({ schemaVersion: 9, prefs: {} }));
  console.log("caso 3 · versión futura → " + (r.ok ? "ok" : "rechazado: " + r.reason));
}

// caso 4: basura no-JSON y no-objeto
{
  const r1 = loadSafe("¿qué es esto?");
  const r2 = loadSafe("[1, 2, 3]");
  console.log("caso 4 · basura → r1=" + (r1.ok ? "ok" : r1.reason) + " | r2=" + (r2.ok ? "ok" : r2.reason));
}

// caso 5: ciclo completo save→load con la tienda (idempotente tras migrar)
{
  const st = createMemoryStorage({ "app:doc": JSON.stringify({ schemaVersion: 1, userName: "ana", theme: "dark", recent: ["a.txt"] }) });
  const store = createStore(st);
  const loaded = store.load();
  store.save(loaded.doc);          // re-graba ya en v4
  const again = store.load();
  console.log("caso 5 · re-grabado → pasos de migración la 2ª vez: " + again.steps.length + " (0 = estable)");
  const checks = [
    loaded.steps.length === 3,
    again.steps.length === 0,
    JSON.stringify(loaded.doc) === JSON.stringify(again.doc),
  ];
  console.log("AUTOVERIFICACIÓN: " + checks.filter(Boolean).length + "/3 propiedades esperadas");
  if (checks.some((c) => !c)) process.exit(1);
}
```"""),
            ("tool", r"""$ node migraciones_storage.test.mjs
caso 1 · doc v1 legítimo → ok pasos=3 (1→4)
  resultado: {"schemaVersion":4,"userName":"ana","prefs":{"theme":"dark","density":"comfortable","lang":"es"},"recentFiles":[{"path":"a.txt","openedAt":0},{"path":"b.txt","openedAt":0}]}
caso 2 · JSON corrupto + backup v3 → viaBackup=true motivo primario: JSON corrupto (Expected double-quoted property name in JSON)
  resultado: {"schemaVersion":4,"userName":"ana","prefs":{"theme":"light","density":"comfortable","lang":"es"},"recentFiles":[{"path":"a.txt","openedAt":0}]}
caso 3 · versión futura → rechazado: versión futura 9 (este build soporta ≤ 4)
caso 4 · basura → r1=JSON corrupto (Unexpected token '¿', "¿qué es esto?" is not valid JSON) | r2=el documento no es un objeto
caso 5 · re-grabado → pasos de migración la 2ª vez: 0 (0 = estable)
AUTOVERIFICACIÓN: 3/3 propiedades esperadas
$ echo $?
0"""),
            ("assistant", r"""Tus cinco usuarios del mundo real están en la salida: el v1 migra 1→4 en tres pasos y conserva tema oscuro y recientes; el del JSON corrupto se recupera del `.bak` (v3) y sube a v4 sin darse cuenta; el del build futuro ve un rechazo EXPLÍCITO en lugar de una app que pisa sus datos; el de basura no-JSOn y el de array reciben causas distintas (te servirá en los tickets); y el caso 5 demuestra la propiedad más importante — tras el primer save, cargar es gratis: cero migraciones, documento estable. Sin esa idempotencia, cada arranque re-migraría y un bug de migración se multiplicaría.

Sobre tu sospecha del «JSON a medio escribir»: `localStorage` es transaccional por clave en la práctica (o está el valor viejo o el nuevo), pero no lo es TU secuencia de dos claves — por eso el `.bak` se escribe ANTES que el principal, y por eso el caso 2 existe. Si el documento crece, considera `structuredClone` y `navigator.storage` / IndexedDB; el núcleo `migrate`/`loadSafe` no cambia ni una línea, porque no saben nada del transporte. Lo que queda por validar fuera de este entorno es la interacción real: cuota superada (`QuotaExceededError` al hacer `setItem`) y pestañas múltiples escribiendo a la vez — para eso, un `storage` event listener y re-carga perezosa."""),
        ],
        tags=["javascript", "localstorage", "migraciones", "versionado-esquema", "persistencia", "resilencia"],
        stack=["javascript"],
        verify=[
            {"name": "logica_pura_node", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": [
                 "pasos=3 (1→4)",
                 "viaBackup=true",
                 "rechazado: versión futura 9",
                 "la 2ª vez: 0 (0 = estable)",
                 "AUTOVERIFICACIÓN: 3/3 propiedades esperadas",
             ]},
        ],
    ),
    # ------------------------------------------------------------------ 6
    E(
        language="javascript",
        domain="web",
        subdomain="url_state_serialization",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""El catálogo tiene que sobrevivir al F5 y a compartir enlaces por chat: búsqueda, etiquetas, página, tamaño de página, orden y vista (grid/lista) deben vivir en la query string. Pero lo que tenemos ahora se construye a base de concatenar strings y es un desastre: un `&` en la búsqueda rompe todo, hay parámetros que vienen manipulados (`page=abc`, `sort=DROP TABLE`), y al paginar perdemos el `utm_source` del boletín. Quiero `encodeState`/`decodeState` con `URLSearchParams`, valores por defecto, acotación de lo que llega por URL, ida-y-vuelta garantizada y un parcheo que PRESERVE los parámetros que no son nuestros. Lógica pura, testeable con Node."""),
            ("assistant", r"""La URL es un contrato público: cualquiera la edita. Por eso el diseño tiene dos direcciones asimétricas:

* `encodeState` solo acepta estado NORMALIZADO y emite una query CANÓNICA: omite lo que equivale al default (menos ruido, URLs comparables), repite `tag=` por cada etiqueta (arrays en el estándar de query strings) y escapa todo `URLSearchParams` (incluidos `&`, `=`, espacios y Unicode).
* `decodeState` asume HOSTILIDAD: cada campo se valida contra su catálogo (`sort` ∈ lista blanca, `per` ∈ {10,25,50}), los números se acotan (`page` ∈ [1,500]), los arrays se recortan y lo no reconocido vuelve al default CON UN AVISO — el aviso es lo que te permite distinguir «el usuario pegó basura» de «hay un bug».
* `withState(search, patch)` parchea el estado SIN tocar claves ajenas (`utm_source`, `gclid`…): borra solo las claves conocidas, recalcula y añade. Es la función que usarás en el enlace de «página 2».

```javascript
"use strict";

// ── contrato del estado de la vista de catálogo ─────────────────────────────
const DEFAULTS = { q: "", tags: [], page: 1, perPage: 25, sort: "relevancia", view: "grid" };
const SORTS = ["relevancia", "precio-asc", "precio-desc", "nuevo"];
const PER_PAGE = [10, 25, 50];
const KNOWN_KEYS = ["q", "tag", "page", "per", "sort", "view"];

// ── encode: estado NORMALIZADO → query string canónica ──────────────────────
function encodeState(state) {
  const sp = new URLSearchParams();
  if (state.q) sp.set("q", state.q);
  for (const t of state.tags) sp.append("tag", t);
  if (state.page !== DEFAULTS.page) sp.set("page", String(state.page));
  if (state.perPage !== DEFAULTS.perPage) sp.set("per", String(state.perPage));
  if (state.sort !== DEFAULTS.sort) sp.set("sort", state.sort);
  if (state.view !== DEFAULTS.view) sp.set("view", state.view);
  return sp.toString();
}

// ── decode: query string (incluso hostil) → estado normalizado + avisos ─────
function decodeState(search) {
  const sp = new URLSearchParams(search);
  const warnings = [];
  const out = { ...DEFAULTS, tags: [] };

  const q = sp.get("q");
  if (q !== null) {
    out.q = q.slice(0, 80);
    if (q.length > 80) warnings.push("q recortada a 80 caracteres");
  }

  const tags = sp.getAll("tag").filter((t) => t.length > 0);
  if (tags.length > 5) { warnings.push("máximo 5 etiquetas: se descartan el resto"); }
  out.tags = tags.slice(0, 5);

  const page = sp.get("page");
  if (page !== null) {
    const n = Number(page);
    if (Number.isInteger(n) && n >= 1) {
      out.page = Math.min(n, 500);
      if (n > 500) warnings.push("page limitada a 500");
    } else { out.page = 1; warnings.push("page no numérica → 1"); }
  }

  const per = sp.get("per");
  if (per !== null) {
    const n = Number(per);
    if (PER_PAGE.includes(n)) out.perPage = n;
    else warnings.push("per fuera de catálogo → 25");
  }

  const sort = sp.get("sort");
  if (sort !== null) {
    if (SORTS.includes(sort)) out.sort = sort;
    else warnings.push("sort desconocido → 'relevancia'");
  }

  const view = sp.get("view");
  if (view === "grid" || view === "list") out.view = view;
  else if (view !== null) warnings.push("view inválida → 'grid'");

  return { state: out, warnings };
}

// ── patch que PRESERVA parámetros ajenos (utm, campaña, sesión) ─────────────
function withState(search, patch) {
  const sp = new URLSearchParams(search);
  for (const k of KNOWN_KEYS) sp.delete(k);
  const merged = { ...decodeState(search).state, ...patch };
  for (const [k, v] of new URLSearchParams(encodeState(merged))) sp.append(k, v);
  return "?" + sp.toString();
}

// ── 1) ida y vuelta sobre estados normalizados ──────────────────────────────
const samples = [
  { q: "", tags: [], page: 1, perPage: 25, sort: "relevancia", view: "grid" },
  { q: "café ñandú", tags: ["mouse", "teclado"], page: 1, perPage: 25, sort: "relevancia", view: "grid" },
  { q: "", tags: [], page: 7, perPage: 50, sort: "precio-asc", view: "list" },
  { q: "mochila impermeable 30l", tags: [], page: 2, perPage: 10, sort: "nuevo", view: "grid" },
  { q: "a & b = c?", tags: ["oferta"], page: 1, perPage: 25, sort: "relevancia", view: "list" },
  { q: "", tags: ["a", "b", "c"], page: 1, perPage: 25, sort: "relevancia", view: "grid" },
];
let ok = 0;
for (const s of samples) {
  const back = decodeState(encodeState(s)).state;
  const same = JSON.stringify(back) === JSON.stringify(s);
  if (same) ok += 1;
  else console.log("  FALLA roundtrip: " + encodeState(s) + " → " + JSON.stringify(back));
}
console.log("roundtrip encode→decode: " + ok + "/" + samples.length + " estados");
console.log("ejemplo: encode(café ñandú + 2 tags) → \"" + encodeState(samples[1]) + "\"");

// ── 2) query hostil pegada por otra parte de la app ─────────────────────────
const hostile = "?page=abc&per=99&sort=DROP+TABLE&view=panoramica&tag=&q=<script>alert(1)</script>";
const h = decodeState(hostile);
console.log("hostil → page=" + h.state.page + " per=" + h.state.perPage + " sort=" + h.state.sort + " view=" + h.state.view + " q queda LITERAL: " + JSON.stringify(h.state.q));
console.log("avisos: " + h.warnings.length + " → " + h.warnings.join(" · "));

// ── 3) paginación sin perder el utm_source ──────────────────────────────────
const link = withState("?utm_source=boletin&page=3", { page: 4 });
console.log("link paginado: " + link);
console.log("AUTOVERIFICACIÓN: utm preservado=" + link.includes("utm_source=boletin") + ", page=4=" + link.includes("page=4"));
if (!link.includes("utm_source=boletin") || !link.includes("page=4")) process.exit(1);
```"""),
            ("tool", r"""$ node url_state.test.mjs
roundtrip encode→decode: 6/6 estados
ejemplo: encode(café ñandú + 2 tags) → "q=caf%C3%A9+%C3%B1and%C3%BA&tag=mouse&tag=teclado"
hostil → page=1 per=25 sort=relevancia view=grid q queda LITERAL: "<script>alert(1)</script>"
avisos: 4 → page no numérica → 1 · per fuera de catálogo → 25 · sort desconocido → 'relevancia' · view inválida → 'grid'
link paginado: ?utm_source=boletin&page=4
AUTOVERIFICACIÓN: utm preservado=true, page=4=true
$ echo $?
0"""),
            ("assistant", r"""Tres puntos de la salida que valen por el ejemplo entero. Primero, el roundtrip 6/6 incluye los dos asesinos clásicos: `café ñandú` (que demuestra el escape Unicode correcto — `+` para espacio, `%C3%B1` para la ñ) y `a & b = c?` (que con concatenación de strings habría destrozado la query). Segundo, la query hostil se normaliza a defaults con avisos, y fíjate en el matiz de seguridad: `q` conserva el valor LITERAL `<script>alert(1)</script>` — correcto, porque la capa URL no decide si escapar HTML; lo inseguro sería construir HTML con ella sin escapar (el escape va en la capa de render, contexto por contexto). Tercero, el `utm_source` sobrevive al parcheo porque `withState` solo borra las claves que son suyas.

Integración: `history.replaceState(null, "", location.pathname + "?" + encodeState(state))` en cada cambio (replaceState, no pushState: paginar no debe llenar el historial), y `decodeState(location.search)` al arrancar. Queda sin verificar aquí lo específico de navegador: el evento `popstate` al navegar con atrás y el redondeo visual del paginador cuando `page=500`."""),
        ],
        tags=["javascript", "urlsearchparams", "estado-url", "roundtrip", "validacion-entrada"],
        stack=["javascript"],
        verify=[
            {"name": "logica_pura_node", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": [
                 "roundtrip encode→decode: 6/6 estados",
                 "q queda LITERAL",
                 "avisos: 4",
                 "?utm_source=boletin&page=4",
             ]},
        ],
    ),
    # ------------------------------------------------------------------ 7
    E(
        language="javascript",
        domain="web",
        subdomain="minimax_game_ai",
        difficulty="extreme",
        task_type="implementation",
        messages=[
            ("user", r"""Estoy montando el tres en raya del menú de espera de nuestra app de kiosco y necesito que la máquina sea IMBATIBLE y determinista (dos partidas con los mismos movimientos deben ser idénticas: la pantalla es la misma para todos los clientes). «Jugar bien» no me vale como especificación: quiero minimax de verdad, con prueba de que no pierde contra varias políticas de rival, y quiero ENTENDER los números: cuánto cuesta el árbol completo, cuánto ahorra la memoización y cuánto la poda alfa-beta. Todo en funciones puras sin DOM para poder ejecutarlo en Node como parte del CI."""),
            ("assistant", r"""Tres en raya es el laboratorio perfecto del juego de suma cero: árbol pequeño pero con TODAS las ideas de los motores serios. El diseño:

* **Puntuación con preferencia temporal**: `+10−depth` si gano, `−(10−depth)` si pierdo, 0 empate. El `−depth` hace que ganar cuanto antes puntúe más: sin él, la IA «duda» y acepta ganancias en jugada 7 teniendo mate en 3.
* **Memoización**: los mismos tableros llegan por caminos distintos (transposiciones); la clave es `tablero+jugador`. AQUÍ está la trampa del ejemplo: la clave no puede ser `board.join("")` a secas, porque las celdas vacías desaparecen y `X...OOX..` colisiona con `XOOX.....` — un tablero NO igual cached con valor ajeno envenena la búsqueda. La clave rellena los huecos con `"."`.
* **Poda alfa-beta** aparte, solo para MEDIR: memoización y poda guardan valores distintos (exacto vs cotas) y mezclarlas sin flags de exactitud es el error típico; aquí comparamos nodos, no las mezclamos.
* **Desempate determinista**: se recorre 0..8 y solo se sustituye con `>` estricto → primer mejor movimiento en orden de lectura. Misma partida, misma respuesta, siempre.

```javascript
"use strict";

// ── tablero: array de 9 con "", "X" u "O"; índices 0..8 en orden de lectura ─
const LINES = [
  [0, 1, 2], [3, 4, 5], [6, 7, 8],   // filas
  [0, 3, 6], [1, 4, 7], [2, 5, 8],   // columnas
  [0, 4, 8], [2, 4, 6],              // diagonales
];
const winnerOf = (b) => {
  for (const [a, c, d] of LINES) if (b[a] && b[a] === b[c] && b[a] === b[d]) return b[a];
  return null;
};
const isFull = (b) => b.every(Boolean);
const other = (p) => (p === "X" ? "O" : "X");

// ── minimax exacto con memo: devuelve {score, nodes} ────────────────────────
// score desde el punto de vista de `me`: +10-depth (gana antes es mejor),
// 0 empate, -(10-depth) pierde. depth = fichas sobre el tablero.
// OJO: la clave de memo rellena las celdas vacías con "." — con join("") a secas,
// "X...OOX.." y "XOOX...." colisionarían y envenenarían la caché.
function minimax(board, player, me, depth, cache, stats) {
  const key = board.map((c) => c || ".").join("") + player;
  const hit = cache.get(key);
  if (hit !== undefined) { stats.hits += 1; return { score: hit, nodes: 0 }; }
  stats.misses += 1;
  const w = winnerOf(board);
  if (w !== null) {
    const score = w === me ? 10 - depth : depth - 10;
    cache.set(key, score);
    return { score, nodes: 1 };
  }
  if (isFull(board)) { cache.set(key, 0); return { score: 0, nodes: 1 }; }
  let best = player === me ? -Infinity : Infinity;
  let nodes = 1;
  for (let i = 0; i < 9; i++) {
    if (board[i]) continue;
    board[i] = player;
    const r = minimax(board, other(player), me, depth + 1, cache, stats);
    board[i] = "";
    nodes += r.nodes;
    if (player === me ? r.score > best : r.score < best) best = r.score;
  }
  cache.set(key, best);
  return { score: best, nodes };
}

// jugada de la IA: maximiza el score del hijo; desempate determinista 0..8
function bestMove(board, player) {
  const me = player;
  const cache = new Map();
  const stats = { hits: 0, misses: 0 };
  const pieces = board.filter(Boolean).length;
  let bestIdx = -1, bestScore = -Infinity;
  for (let i = 0; i < 9; i++) {
    if (board[i]) continue;
    board[i] = player;
    const r = minimax(board, other(player), me, pieces + 1, cache, stats);
    board[i] = "";
    if (r.score > bestScore) { bestScore = r.score; bestIdx = i; }
  }
  return { index: bestIdx, score: bestScore, stats };
}

// ── batería táctica ─────────────────────────────────────────────────────────
const show = (b) => b.map((c) => c || "·").join(" ");
const posBlock = ["X", "X", "", "", "O", "", "", "", ""]; // X amenaza 0-1-2
const m1 = bestMove(posBlock, "O");
console.log("bloqueo  : " + show(posBlock) + " → juega " + m1.index + " (valor " + m1.score + ")");
const posWin = ["X", "", "", "", "O", "O", "X", "", ""]; // O cierra 3-4-5
const m2 = bestMove(posWin, "O");
console.log("victoria : " + show(posWin) + " → juega " + m2.index + " (valor " + m2.score + ")");
const posEarly = ["", "", "", "", "X", "", "", "", ""]; // X abrió en el centro
const m3 = bestMove(posEarly, "O");
console.log("apertura : " + show(posEarly) + " → juega " + m3.index + " (valor " + m3.score + ")");

// ── barrido adversarial: tres políticas fijas de X contra la IA (O) ─────────
function makeSeededRandom(seed) {
  let s = seed >>> 0 || 1;
  return () => { s = (s * 1103515245 + 12345) >>> 0; return s / 4294967296; };
}
const POLICIES = {
  "centro-primero": (b, rnd) => b[4] === "" ? 4 : b.findIndex((c) => c === ""),
  "esquinas-primero": (b, rnd) => { for (const i of [0, 2, 6, 8, 4, 1, 3, 5, 7]) if (b[i] === "") return i; return -1; },
  "aleatorio(seed 7)": (b, rnd) => { const free = b.map((c, i) => (c ? -1 : i)).filter((i) => i >= 0); return free[Math.floor(rnd() * free.length)]; },
};
function playGame(policyName) {
  const b = Array(9).fill("");
  const rnd = makeSeededRandom(7);
  let moves = 0;
  for (;;) {
    // mueve X según la política
    const xi = POLICIES[policyName](b, rnd);
    if (xi === undefined || xi < 0) return { result: "empate", moves };
    b[xi] = "X"; moves += 1;
    if (winnerOf(b) === "X") return { result: "derrota", moves };
    if (isFull(b)) return { result: "empate", moves };
    // mueve O con la IA
    const { index } = bestMove(b, "O");
    b[index] = "O"; moves += 1;
    if (winnerOf(b) === "O") return { result: "victoria", moves };
    if (isFull(b)) return { result: "empate", moves };
  }
}
const tally = { victoria: 0, empate: 0, derrota: 0 };
for (const name of Object.keys(POLICIES)) {
  const g = playGame(name);
  tally[g.result] += 1;
  console.log("vs " + name.padEnd(18) + " → " + g.result + " en " + g.moves + " jugadas");
}
console.log("barrido: " + tally.victoria + " victorias, " + tally.empate + " empates, " + tally.derrota + " derrotas");

// ── coste de búsqueda desde el tablero vacío (3 estrategias) ────────────────
function countPlain(board, player) {
  if (winnerOf(board) !== null || isFull(board)) return 1;
  let nodes = 1;
  for (let i = 0; i < 9; i++) {
    if (board[i]) continue;
    board[i] = player;
    nodes += countPlain(board, other(player));
    board[i] = "";
  }
  return nodes;
}

function abSearch(board, player, me, depth, alpha, beta) {
  const w = winnerOf(board);
  if (w !== null) return { score: w === me ? 10 - depth : depth - 10, nodes: 1 };
  if (isFull(board)) return { score: 0, nodes: 1 };
  let nodes = 1;
  let a = alpha, bta = beta;
  let best = player === me ? -Infinity : Infinity;
  for (let i = 0; i < 9; i++) {
    if (board[i]) continue;
    board[i] = player;
    const r = abSearch(board, other(player), me, depth + 1, a, bta);
    board[i] = "";
    nodes += r.nodes;
    if (player === me) { best = Math.max(best, r.score); a = Math.max(a, best); }
    else { best = Math.min(best, r.score); bta = Math.min(bta, best); }
    if (a >= bta) break; // el rival ya tiene una opción mejor: no seguimos
  }
  return { score: best, nodes };
}

const empty = Array(9).fill("");
const plainNodes = countPlain(empty, "O");
const withMemo = bestMove(empty, "O");
const withAB = abSearch(empty, "O", "O", 0, -Infinity, Infinity);
console.log("nodos desde tablero vacío → árbol completo: " + plainNodes
  + " | con memo: " + withMemo.stats.misses
  + " | con poda alfa-beta: " + withAB.nodes);
console.log("valor del tablero vacío para O → memo=" + withMemo.score + " alfa-beta=" + withAB.score + " (deben coincidir)");

const checks = [
  m1.index === 2 && m1.score === 0,
  m2.index === 3 && m2.score === 5, // victoria inmediata = 10 - 5 fichas
  tally.derrota === 0,
  withMemo.score === withAB.score,
];
console.log("AUTOVERIFICACIÓN: " + checks.filter(Boolean).length + "/4 propiedades esperadas");
if (checks.some((c) => !c)) process.exit(1);
```"""),
            ("tool", r"""$ node minimax_ia.test.mjs
bloqueo  : X X · · O · · · · → juega 2 (valor 0)
victoria : X · · · O O X · · → juega 3 (valor 5)
apertura : · · · · X · · · · → juega 0 (valor 0)
vs centro-primero     → victoria en 8 jugadas
vs esquinas-primero   → victoria en 6 jugadas
vs aleatorio(seed 7)  → empate en 9 jugadas
barrido: 2 victorias, 1 empates, 0 derrotas
nodos desde tablero vacío → árbol completo: 549946 | con memo: 5477 | con poda alfa-beta: 20866
valor del tablero vacío para O → memo=0 alfa-beta=0 (deben coincidir)
AUTOVERIFICACIÓN: 4/4 propiedades esperadas
$ echo $?
0"""),
            ("assistant", r"""Lectura de los números, que era lo que pedías: el árbol completo desde vacío son 549.946 nodos; con memoización se expanden 5.477 posiciones ÚNICAS (≈100× menos: el 3 en raya está lleno de transposiciones); con poda alfa-beta, 20.866 — aquí la poda es peor que la memo porque el árbol es pequeño, pero en juegos donde las transposiciones son raras y el factor de ramificación grande (ajedrez), la relación se invierte. Por eso no se eligen «a ciegas»: se mide, como acabamos de hacer. Y la prueba de imbatibilidad es el barrido: 2 victorias y 1 empate contra las tres políticas, 0 derrotas — el empate contra el aleatorio es azar del rival afortunado, no debilidad de la IA (el valor del tablero vacío para O es 0: con juego perfecto de ambos, tablas).

Dos anclas tácticas confirman la corrección fina: en `X X · · O · · · ·` la IA NO se lanza a atacar, bloquea (valor 0: tablas garantizadas) y en `X · · · O O X · ·` cierra la línea 3-4-5 con valor `10−5=5` (la aritmética del depth en acción: ganar en cuanto antes vale más). Para tu kiosco te falta solo la capa de E/S (dibujar el tablero, esperar el toque), y un detalle práctico: como `bestMove` es determinista y barato (5.477 nodos ≈ milisegundos), puedes calcular la jugada en el momento sin tabla precalculada; si algún día portas el mismo motor a un juego con árbol grande, entonces sí: tabla de transposición persistente y límite de profundidad con quiescencia. Lo no verificado aquí: el render táctil del kiosco y qué pasa si el cliente pulsa dos celdas a la vez — eso es capa UI."""),
        ],
        tags=["javascript", "minimax", "alfa-beta", "memoizacion", "ia-juegos", "determinismo"],
        stack=["javascript"],
        verify=[
            {"name": "logica_pura_node", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 15,
             "expect_stdout_contains": [
                 "bloqueo  : X X · · O · · · · → juega 2 (valor 0)",
                 "victoria : X · · · O O X · · → juega 3 (valor 5)",
                 "barrido: 2 victorias, 1 empates, 0 derrotas",
                 "árbol completo: 549946 | con memo: 5477 | con poda alfa-beta: 20866",
                 "AUTOVERIFICACIÓN: 4/4 propiedades esperadas",
             ]},
        ],
    ),
    # ------------------------------------------------------------------ 8
    E(
        language="javascript",
        domain="web",
        subdomain="relative_date_formatting",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""El feed muestra sellos de tiempo tipo «hace 5 minutos» y hoy usamos una librería de 40 KB para eso. La quiero fuera. Pero al revisar el código descubrí que cada quien se inventaba sus umbrales: un sitio decía «hace 1 hora» a los 50 minutos y otro «hace 45 minutos» a los 55. Necesito un formateador de fechas relativas en español, sin librerías, con reglas EXPLÍCITAS y documentadas (pasado y futuro: «hace…» / «en…»), que acepte epoch ms (nosotros decimos «ahora», no lo consulta al reloj), y de paso un mini-parser de entradas tipo `+90m`, `-2h`, `3d` y fechas ISO de calendario para los filtro del feed. Todo puro y testeable con Node."""),
            ("assistant", r"""Lo que falla en tu equipo es el CONTRATO, no el código: «hace 1 hora» a los 50 minutos y «hace 45 minutos» a los 55 es imposible si los umbrales no están escritos. Así que el formateador lleva la tabla de convenciones COMO ESPECIFICACIÓN en el propio fichero (es la tabla que usan las librerías de referencia: 45 s, 90 s, 45 min, 90 min, 22 h, 36 h, 25 d, 45 d, 320 d, 548 d) y los test la fijan:

* Redondeo honesto: a 44:59 le decimos «hace 45 minutos» (44,98 redondea a 45) y el segundo 2700 exacto ya es «hace una hora». La frontera es exacta y testeada — ese tipo de caso es justo el que hace discutir a dos partes del código.
* Unidades de calendario con valor definido: mes = 2.629.746 s (mes gregoriano medio, 30,436875 días) y año = 31.556.952 s. Nada de «30 días siempre»: en 4 años el acumulado se desvía 1,2 días y los sellos «hace N meses» dejan de cuadrar con el calendario.
* Tensión como parámetro: el formateador recibe la DIFERENCIA en segundos; la capa superior `formatAt(nowMs, targetMs)` divide epoch ms explícitos. Ninguna función mira el reloj del sistema → determinismo total.
* El parser acepta `±N[smdwy]`, fecha ISO de calendario (interpretada 00:00 UTC, se dice en el resultado) e ISO con hora UTC; lo demás es error con la entrada impresa.

```javascript
"use strict";

// ── convenciones explícitas (segundos); nada de hora del sistema ────────────
const MIN = 60;
const HOUR = 3600;
const DAY = 86400;
const MONTH = 2629746;      // 30.436875 días (mes gregoriano medio)
const YEAR = 31556952;      // año gregoriano medio

// Umbral/valor que produce cada tramo (convención tipo moment/humanize):
//  <45s  → "unos segundos"          <90s   → "un minuto"
//  <45m  → "N minutos"             <90m   → "una hora"
//  <22h  → "N horas"               <36h   → "un día"
//  <25d  → "N días"                <45d   → "un mes"
//  <320d → "N meses"               <548d  → "un año"
//  ≥548d → "N años"
function relativeFormat(deltaSeconds) {
  if (!Number.isFinite(deltaSeconds)) return { phrase: "—", tense: "invalido" };
  const past = deltaSeconds < 0;
  const s = Math.abs(Math.round(deltaSeconds));
  let text;
  if (s < 45) text = "unos segundos";
  else if (s < 90) text = "un minuto";
  else if (s < 45 * MIN) text = Math.round(s / MIN) + " minutos";
  else if (s < 90 * MIN) text = "una hora";
  else if (s < 22 * HOUR) text = Math.round(s / HOUR) + " horas";
  else if (s < 36 * HOUR) text = "un día";
  else if (s < 25 * DAY) text = Math.round(s / DAY) + " días";
  else if (s < 45 * DAY) text = "un mes";
  else if (s < 320 * DAY) text = Math.round(s / MONTH) + " meses";
  else if (s < 548 * DAY) text = "un año";
  else text = Math.round(s / YEAR) + " años";
  return { phrase: (past ? "hace " : "en ") + text, tense: past ? "pasado" : "futuro" };
}

// API de capa superior: epoch ms explícitos (el llamador aporta "ahora")
function formatAt(nowMs, targetMs) {
  return relativeFormat(Math.round((targetMs - nowMs) / 1000)).phrase;
}

// ── parser minimalista de entradas temporales ───────────────────────────────
const UNIT_MS = { s: 1000, m: 60000, h: 3600000, d: 86400000, w: 604800000, y: 31556952000 };
function parseWhen(input, nowMs) {
  const rel = /^([+-]?\d+)\s*([smhdwy])$/i.exec(input.trim());
  if (rel) {
    const n = Number(rel[1]);
    const mult = UNIT_MS[rel[2].toLowerCase()];
    return { ok: true, at: nowMs + n * mult, kind: "relativa (" + input.trim() + ")" };
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(input)) {
    return { ok: true, at: Date.parse(input + "T00:00:00Z"), kind: "fecha ISO (00:00 UTC)" };
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(input)) {
    return { ok: true, at: Date.parse(input), kind: "ISO con hora UTC" };
  }
  return { ok: false, reason: "formato no reconocido: " + input };
}

// ── tabla de casos (NOW fijo, determinista) ─────────────────────────────────
const NOW = Date.parse("2025-06-15T10:00:00Z");
const cases = [
  [-30, "hace unos segundos"],
  [-61, "hace un minuto"],
  [-2699, "hace 45 minutos"],   // 44:59 redondea a «45 minutos»
  [-2700, "hace una hora"],     // frontera exacta de 45 min
  [-5399, "hace una hora"],
  [-7200, "hace 2 horas"],
  [-3 * DAY, "hace 3 días"],
  [40 * DAY, "en un mes"],
  [-100 * DAY, "hace 3 meses"],
  [-400 * DAY, "hace un año"],
  [700 * DAY, "en 2 años"],
];
let okFmt = 0;
for (const [delta, expected] of cases) {
  const got = relativeFormat(delta).phrase;
  if (got === expected) okFmt += 1;
  else console.log("  FALLA: Δ=" + delta + "s → " + got + " (esperado \"" + expected + "\")");
  console.log("Δ " + String(delta).padStart(8) + "s → \"" + got + "\"");
}
console.log("formateo: " + okFmt + "/" + cases.length + " casos con la frase esperada");

// ── ida y vuelta parser → formateador ───────────────────────────────────────
const inputs = ["+30s", "-90m", "+45m", "-3h", "+2d", "-1w", "+40d", "-2y"];
const expectedRound = [
  "en unos segundos", "hace 2 horas", "en una hora", "hace 3 horas",
  "en 2 días", "hace 7 días", "en un mes", "hace 2 años",
];
let okRound = 0;
inputs.forEach((input, i) => {
  const p = parseWhen(input, NOW);
  const got = formatAt(NOW, p.at);
  if (got === expectedRound[i]) okRound += 1;
  else console.log("  FALLA roundtrip: " + input + " → " + got + " (esperado \"" + expectedRound[i] + "\")");
});
console.log("roundtrip parser→formateador: " + okRound + "/" + inputs.length);
console.log("muestra: parseWhen(\"-90m\") → at=" + parseWhen("-90m", NOW).at + " → \"" + formatAt(NOW, parseWhen("-90m", NOW).at) + "\"");

const bad = parseWhen("ayer", NOW);
console.log("entrada inválida → " + (bad.ok ? "ACEPTADA (mal)" : bad.reason));

const checks = [okFmt === cases.length, okRound === inputs.length, bad.ok === false];
console.log("AUTOVERIFICACIÓN: " + checks.filter(Boolean).length + "/3 bloques correctos");
if (checks.some((c) => !c)) process.exit(1);
```"""),
            ("tool", r"""$ node fechas_relativas.test.mjs
Δ      -30s → "hace unos segundos"
Δ      -61s → "hace un minuto"
Δ    -2699s → "hace 45 minutos"
Δ    -2700s → "hace una hora"
Δ    -5399s → "hace una hora"
Δ    -7200s → "hace 2 horas"
Δ  -259200s → "hace 3 días"
Δ   3456000s → "en un mes"
Δ  -8640000s → "hace 3 meses"
Δ -34560000s → "hace un año"
Δ  60480000s → "en 2 años"
formateo: 11/11 casos con la frase esperada
roundtrip parser→formateador: 8/8
muestra: parseWhen("-90m") → at=1749976200000 → "hace 2 horas"
entrada inválida → formato no reconocido: ayer
AUTOVERIFICACIÓN: 3/3 bloques correctos
$ echo $?
0"""),
            ("assistant", r"""El caso que sorprende siempre es el de la muestra: `-90m` («hace hora y media») se imprime «hace 2 horas». No es un bug: 5.400 s cae FUERA del tramo `<90 min` y, dentro del tramo de horas, 1,5 redondea a 2. Ese redondeo es el mismo que hacen las librerías de referencia, y la lección de ingeniería es que el comportamiento de la FRONTERA debe estar en los tests (aquí: -2699 y -2700, juntos), no en el folklore del equipo. Si prefirieras «hace 1 hora» para 90 minutos exactos, el cambio es un umbral — y el test que hoy pasa te avisará.

Para integrarlo: en el feed, guarda los epoch ms del evento en el `dataset` y actualiza los sellos con UN intervalo compartido (60 s basta; no uno por elemento — ese es otro clásico que infla timers) usando `formatAt(Date.now(), stamp)`. El `Date.now()` aquí es legítimo porque ocurre en el navegador en tiempo real; las funciones PURAS siguen sin ver el reloj, que es lo que permite esta batería determinista. Y dos límites declarados: los meses/años usan unidades MEDIAS (no calendario real), suficiente para sellos de feed; y el parser no acepta horas locales ni zonas tipo `+02:00` — cuando hagas falta, se añade como tercer patrón ISO con `Date.parse` y su propio test."""),
        ],
        tags=["javascript", "fechas-relativas", "i18n", "parser", "sin-dependencias"],
        stack=["javascript"],
        verify=[
            {"name": "logica_pura_node", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": [
                 "Δ    -2700s → \"hace una hora\"",
                 "formateo: 11/11 casos con la frase esperada",
                 "roundtrip parser→formateador: 8/8",
                 "formato no reconocido: ayer",
                 "AUTOVERIFICACIÓN: 3/3 bloques correctos",
             ]},
        ],
    ),
    # ------------------------------------------------------------------ 9
    E(
        language="css",
        domain="web",
        subdomain="grid_dashboard_areas",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Nuestro panel de operaciones (marca arriba, filtros a la izquierda, franja de KPIs, gráfico grande y tabla abajo) hoy se maqueta con tres media queries que ya nadie se atreve a tocar, y el problema es que el panel se INCUSTA en iframes de anchos imprevisibles (portales de clientes), donde el viewport da igual: lo que manda es el ancho del iframe. Quiero el mismo comportamiento responsive sin una sola media query, con CSS Grid, y me han dicho que use «grid areas». Cuando lo intento, o el sidebar no baja abajo en estrecho o los KPIs se salen de pantalla en un iframe de 300px."""),
            ("assistant", r"""Antes del código, la verdad incómoda que te evita semanas de frustración: `grid-template-areas` NO se reorganiza solo. Su topología es estática; cambiarla exige una query (media o container). Lo que SÍ es intrínsecamente responsive es el NÚMERO DE PISTAS que `repeat(auto-fit, minmax(...))` genera según el ancho disponible. La técnica honesta combina ambas: áreas nombradas para el esqueleto estable (marca/cuerpo/pie) y auto-fit para las zonas que deben reorganizarse de verdad. Dos trucos finos que resuelven tus dos bugs:

* `minmax(min(100%, 320px), 1fr)` — el `min(100%, …)` evita el desbordamiento clásico por debajo de 320px (con `minmax(320px, 1fr)` a secas, una pista de 320px no cabe en un contenedor de 300 y aparece scroll horizontal).
* `container-type: inline-size` en el host del iframe-side: si el panel se incrusta, el contenedor relevante es el panel, no el viewport; con container queries puedes añadir topología extra POR CONTENEDOR sin tocar las media queries que ya no existen.

```css
/* ── Panel de operaciones: responsive intrínseco, cero @media ─────────────
   topología estable por áreas (esqueleto) + nº de pistas por auto-fit
   (la parte que sí se reorganiza sola según el ancho del CONTENEDOR). */

.panel {
  --gap: clamp(10px, 1.6vw, 22px);
  display: grid;
  grid-template-areas:
    "topbar"
    "cuerpo"
    "pie";
  grid-template-rows: auto 1fr auto;
  gap: var(--gap);
  container-type: inline-size;   /* el panel es su propio punto de referencia */
}

.marca { grid-area: topbar; }
.pie   { grid-area: pie; }

/* ¿1 pista o 2? Lo decide el ancho: si caben dos columnas de 320px hay
   rail + contenido; si no, filtros encima y contenido debajo. Sin @media. */
.cuerpo {
  grid-area: cuerpo;
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
  align-items: start;
}

.filtros {
  background: var(--superficie, #fff);
  border: 1px solid var(--borde, #dbe2ea);
  border-radius: 12px;
  padding: clamp(12px, 2vw, 20px);
}

/* Dentro del contenido: KPIs que van de 1 a N columnas solos, y el
   gráfico/tabla siempre a lo ancho de su zona (1 / -1). */
.contenido {
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
}
.grafico, .tabla { grid-column: 1 / -1; }

.card {
  background: var(--superficie, #fff);
  border: 1px solid var(--borde, #dbe2ea);
  border-radius: 12px;
  padding: clamp(12px, 2vw, 20px);
}

/* Opcional, cuando el panel se incrusta en anchos MUY estrechos: topología
   extra POR CONTENEDOR (no media query; mira el panel, no el viewport). */
@container (max-width: 480px) {
  .filtros { display: none; } /* en tarjeta de 300px, solo lo esencial */
}
```

Estructura HTML que espera este CSS: `.panel > header.marca + div.cuerpo > (aside.filtros + div.contenido > (3× .card.kpi + .card.grafico + .card.tabla)) + footer.pie`. Los KPIs se auto-colocan; el gráfico y la tabla ocupan fila completa con `1 / -1`."""),
            ("user", r"""Vale, pero hay algo que no me cuadra: si el panel se abre a 700px veo filtros y contenido en dos columnas, y a 600px se apilan. ¿Eso es predecible? Y en el iframe de 300px de verdad, ¿el `.contenido` también se reorganiza o solo el `.cuerpo`?"""),
            ("assistant", r"""Es predecible al milímetro, y conviene saber calcularlo: en `.cuerpo` la condición de «2 pistas» es que quepan 2×320px más el gap: con `clamp()` el gap vale ~10-22px, así que el corte está en torno a 650-662px de ancho DE PANEL. A 700px → 2 pistas (filtros | contenido); a 600px → 1 pista y se apilan. Ese corte lo puedes mover ajustando el `320px` (es el único número mágico y está documentado en el comentario). En `.contenido` pasa lo propio con 220px: tres KPIs caben en paralelo cuando el ancho del CONTENIDO (no del viewport) supera ~3×220+2×gap; si el panel total es de 700px con rail, el contenido tiene ~370px → un KPI por fila. Cada grid mira SU ancho disponible, que es justo lo que las media queries no podían darte.

Cómo se comprueba esto en navegador (te lo dejo protocolado, porque el CSS no se «ejecuta» en un test): (1) DevTools → inspecciona `.cuerpo` con el badge de Grid activado: verás las pistas cambiar de 2 a 1 mientras arrastras el borde del panel, con el corte exacto marcado por el overlay; (2) para el iframe, no redimensiones la ventana: redimensiona el `.panel` (o usa el modo responsive de DevTools fijando el ancho del iframe a 300px) y verifica que no hay scroll horizontal — si lo hay, te olvidaste de un `min(100%, …)`; (3) en la pestaña Layout del inspector aparecen los contenedores `container-type` y las `@container` activas, así confirmas que el corte de 480px dispara por ancho de panel y no por ancho de ventana; (4) y una pasada con el DOM en inglés/es y textos largos: `auto-fit` reparte el espacio SOBRANTE, pero un KPI con una palabra irrompible larguísima necesita `min-width: 0` o `overflow-wrap: anywhere` — el fallo típico que ningún test estático ve."""),
        ],
        tags=["css", "grid", "grid-areas", "auto-fit", "container-queries", "layout"],
        stack=["html", "css"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 10
    E(
        language="css",
        domain="web",
        subdomain="css_has_form_states",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""El formulario de alta tiene estados que hoy pintamos con JavaScript: cuando un campo es inválido, añaden una clase `.is-error` al contenedor y muestran el mensajito; cuando marcas un checkbox de una fila, otra función le pone `.row-selected` a la fila; y el botón de envío se apaga con JS. El resultado es que cada CAMBIO nuevo de diseño toca ese JS y siempre se les olvida un caso (acaban de descubrir que si el navegador autorellena, ninguna clase se aplica). Me han dicho que con `:has()` se puede, pero lo intento y no veo cómo llegar del input a la fila o al botón de enviar."""),
            ("assistant", r"""`:has()` es el selector que CSS esperaba treinta años: un ascendente condicional («el elemento que CONTIENE lo que yo diga»). Tu tres casos son exactamente su territory: del `input` hacia ARRIBA (contenedor, fila, formulario). Antes de escribirlo, dos decisiones técnicas que marcan la diferencia:

1. `:user-invalid` en lugar de `:invalid`. Con `:invalid`, el formulario NACE rojo (los campos están vacíos = inválidos antes de que el usuario haga nada). `:user-invalid` solo pinta tras interacción — y su hermano `:user-valid` limpia el error en cuanto se corrige. Es la diferencia entre «el formulario grita» y «el formulario responde».
2. No deshabilites el submit con CSS. Mantén el botón activo y muestra un resumen de errores: un botón muerto sin explicación es la queja nº1 de usabilidad de formularios. CSS pinta el estado; la política la pones tú.

```css
/* ── Estados de formulario con :has() — cero clases inyectadas por JS ── */

.campo {
  border: 1px solid var(--borde, #cbd5e1);
  border-radius: 10px;
  padding: 10px 12px;
  transition: border-color .15s, box-shadow .15s;
}

/* Campo inválido DESPUÉS de que el usuario lo tocó → borde y mensaje */
.campo:has(input:user-invalid, textarea:user-invalid) {
  border-color: var(--mal, #dc2626);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--mal, #dc2626) 18%, transparent);
}
.campo .error { display: none; }
.campo:has(input:user-invalid) .error { display: block; }

/* Etiqueta flotante: el label sube cuando hay contenido (autorelleno
   incluido: :autofill también funciona dentro de :has()) */
.campo { position: relative; }
.campo label {
  position: absolute; inset-inline-start: 12px; top: 10px;
  transition: top .12s, font-size .12s; pointer-events: none;
}
.campo:has(input:focus), .campo:has(input:not(:placeholder-shown)) {
  /* el input necesita placeholder=" " para que :placeholder-shown compare */
}
.campo:has(input:focus) label,
.campo:has(input:not(:placeholder-shown)) label { top: -7px; font-size: .68rem; }

/* Fila de tabla seleccionada: la fila reacciona a SU checkbox */
tbody tr:has(input[type="checkbox"]:checked) {
  background: var(--sel, #eef4ff);
}
tbody tr:has(input[type="checkbox"]:focus-visible) {
  outline: 2px solid var(--acento, #2563eb); outline-offset: -2px;
}

/* Fieldset entero iluminado mientras cualquier control interno tiene foco */
fieldset:has(:focus-visible) { border-color: var(--acento, #2563eb); }

/* Select vacío obligatorio: tono apagado hasta elegir (el truco clásico
   :invalid, ahora también sobre el contenedor) */
.campo:has(select:required:invalid) { color: var(--apagado, #64748b); }

/* Resumen de errores del formulario: visible mientras exista algún inválido */
.form-estado { display: none; }
form:has(:user-invalid) .form-estado { display: block; }

/* Progresivo: los estilos solo se aplican donde :has() existe;
   en el resto, el formulario sigue siendo usable con los estados nativos. */
@supports not selector(:has(*)) {
  .form-estado { display: block; } /* sin :has(), el resumen siempre visible */
}
```"""),
            ("user", r"""Tiene muy buena pinta, pero tengo dudas de soporte y de comportamiento: ¿esto funciona en todos los navegadores que atendemos? Y más importante: si el usuario autorellena con el gestor de contraseñas, ¿el label flotante y el borde verde se enteran? Y una cosa más: el mensajito de error que mostramos por CSS, ¿lo leen los lectores de pantalla o me estoy montando un problema de accesibilidad?"""),
            ("assistant", r""":has() está soportado en todos los navegadores actuales (Chrome/Edge 105+, Safari 15.4+, Firefox 121+; diciembre de 2023). El bloque `@supports not selector(:has(*))` es tu red: donde no exista, no se rompe nada — los estados nativos (`:invalid`, el `required` del navegador) siguen operando y el resumen se muestra siempre, que es la degradación correcta. Nada de JS de compatibilidad.

Autorelleno: sí, se entera — y es EL argumento frente a las clases inyectadas. El autorelleno dispara los mismos estados de validez y `:placeholder-shown`/`:autofill` se evalúan en el render, no en eventos: un contenedor `:has(input:not(:placeholder-shown))` reacciona al valor haya llegado como tecleo, pegado o por el gestor. Con clases JS, en cambio, el autorelleno no dispara `input` en algunos gestores — el bug que ya te pasó.

Accesibilidad, aquí conviene precisión quirúrgica: el borde rojo y el `display:block` del mensaje son PRESENTACIÓN, y los lectores de pantalla no anuncian cambios de CSS. Lo correcto no es renunciar a `:has()`, es no cargarlo de lo que no le toca: (1) el `<span class="error">` debe estar referenciado con `aria-describedby` desde el input (se anuncia al enfocar el campo, que es cuando importa); (2) `aria-live="polite"` en el resumen del formulario para que los errores agregados se anuncien tras el submit; (3) `aria-invalid="true"` — eso sí lo pone JS, pero UNA vez al validar, no gestionando clases por campo. Es decir: `:has()` elimina el 90 % del JS de estados, y el 10 % que queda (atributos ARIA semánticos) es justo el que CSS no puede poner. Cómo se comprueba: navega el formulario SOLO con Tab y VoiceOver/NVDA activo — cada campo inválido enfocado debe anunciar su mensaje; y en DevTools, fuerza `:user-invalid` desde el panel Force element state para ver el estado sin escribir. El flujo de autorelleno se prueba de verdad con el gestor de contraseñas del sistema, no con DevTools."""),
        ],
        tags=["css", "has", "user-invalid", "formularios", "accesibilidad", "progresivo"],
        stack=["html", "css"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 11
    E(
        language="css",
        domain="web",
        subdomain="performant_animations",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""El diseñador pasó unos mockups animados y el implemento quedó a tirones: la entrada de tarjetas anima `height` y `margin` (cada frame recalcula layout), el badge de «nuevo» late con `width`, y el panel de filtros se despliega animando `max-height` (ese salto final cuando el contenido es más corto que el máximo es horrible). En móvil es donde más se nota. Quiero las mismas animaciones pero que vayan fluidas, con entrada escalonada de tarjetas (stagger), y que las personas con «reducir movimiento» activado no reciban la coreografía."""),
            ("assistant", r"""El diagnóstico antes del código: el navegador por frame hace Layout → Paint → Composite, y solo hay dos propiedades cuyo cambio salta DIRECTAMENTE al composite sin invalidar layout ni pintura: `transform` (y sus propiedades individuales modernas `translate`, `rotate`, `scale`) y `opacity`. Todo lo que anima `height`, `margin`, `width` o `top` re-calcula el layout de todo el subárbol por frame — de ahí los tirones. Reescribo tus tres casos:

* Entrada de tarjetas: `opacity` + `translate` con retardo escalonado vía `--i` (índice inline), en lugar de animar altura.
* Badge latiendo: `scale` + `opacity`, no `width`.
* Panel desplegable: aquí hay que ser honesto — NO existe forma de animar una altura real sin layout. Lo que se hace: el panel no colapsa su altura, se oculta con `opacity`+`translate`+`visibility` (sigue ocupando sitio en el flujo si el diseño lo permite) o se mide con JS una vez y se usa FLIP. La transición de `grid-template-rows: 0fr→1fr` que se pone de moda TAMBIÉN anima layout: es barata en subárboles pequeños, pero es layout; te la menciono para que elijas sabiendo lo que cuesta.

```css
/* ── Animaciones de compositor: solo transform/translate/scale + opacity ── */

/* Entrada escalonada: el retardo vive en --i (style="--i: 3" en el HTML);
   calc() lo convierte en 60ms por posición. Nada de JS por tarjeta. */
.tarjeta {
  opacity: 0;
  translate: 0 14px;
  animation: entrada .45s cubic-bezier(.2, .7, .2, 1) forwards;
  animation-delay: calc(var(--i, 0) * 60ms);
}
@keyframes entrada { to { opacity: 1; translate: 0 0; } }

/* Badge latiendo: escala y opacidad → compositor puro, costo O(1) */
.badge-nuevo {
  animation: latido 1.6s ease-in-out infinite;
}
@keyframes latido {
  50% { scale: 1.12; opacity: .85; }
}

/* Desplegable sin animar altura: presencia/ausencia con opacidad y
   micro-desplazamiento; visibility mantiene accesible el foco correcto. */
.desplegable {
  opacity: 0;
  translate: 0 -6px;
  visibility: hidden;
  transition: opacity .22s ease, translate .22s ease, visibility 0s .22s;
}
.abierto .desplegable {
  opacity: 1;
  translate: 0 0;
  visibility: visible;
  transition-delay: 0s;
}

/* will-change SOLO en el elemento que late de forma permanente:
   es una promesa de capa que cuesta memoria; ni «por si acaso» ni a todo. */
.badge-nuevo { will-change: transform, opacity; }

/* La coreografía no es opcional para quien pidió menos movimiento:
   sin saltos, sin latidos; el contenido aparece directamente. */
@media (prefers-reduced-motion: reduce) {
  .tarjeta { animation: none; opacity: 1; translate: none; }
  .badge-nuevo { animation: none; will-change: auto; }
  .desplegable { transition-duration: 0s; }
}
```"""),
            ("user", r"""Entiendo la regla de transform/opacity, pero el desplegable me deja una duda: si no anima la altura, el contenido de debajo «salta» de golpe al abrirse, ¿no? Y otra cosa: ¿cómo compruebo yo que de verdad ya no hay layout thrash, no me fío de «debería ir fluido»?"""),
            ("assistant", r"""Correcto el matiz: con el desplegable por opacidad, el contenido posterior aparece de golpe en su posición final al terminar — por eso en tu diseño concreto hay dos caminos honestos: (a) reservar el espacio (el panel vive en una celda de grid de altura fija; nada salta porque nada cambia de tamaño) o (b) asumir animación de layout pero ACOTADA: la técnica `grid-template-rows: 0fr → 1fr` en el panel — anima layout, sí, pero solo del subárbol del panel, con `overflow: hidden` en el hijo, y en un panel de filtros de unas decenas de elementos el coste por frame es despreciable incluso en móvil. La regla de senior no es «nunca layout»: es «layout animado solo en subárboles pequeños y medidos»; para un modal a pantalla completa que empuja a toda la página, ni hablar.

Cómo se comprueba que va fluido (y no «en mi máquina iba bien»): DevTools → ⋮ → More tools → **Rendering** → activa *Paint flashing* y *Layer borders*: durante la animación la pantalla NO debe pintarse de verde (paint = sospecha) y las tarjetas/badge deben tener su propia capa. Luego graba una traza en **Performance** mientras se dispara la entrada: en el flame chart cada frame debe mostrar Composite/Draw sin bloques morados (Layout) ni verdes pintados a lo bestia — si ves `Recalculate Style` + `Layout` por frame, algo sigue animando propiedades de layout. El *FPS meter* te da el número, pero la traza te da la CAUSA. Y para `prefers-reduced-motion`: se emula en Rendering → *Emulate CSS media feature prefers-reduced-motion*, aunque la prueba final es real (Windows: Configuración → Efectos visuales; macOS: Accesibilidad → Movimiento) porque la emulación no reproduce el caso límite de un transition heredado desde un `*` — que, si algún día lo pones, verás que destroza las transiciones de los componentes: por eso aquí se limita a los tres elementos coreografiados."""),
        ],
        tags=["css", "animaciones", "transform", "opacity", "prefers-reduced-motion", "rendimiento"],
        stack=["css"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 12
    E(
        language="css",
        domain="web",
        subdomain="dark_mode_container_queries",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Nuestro design system tiene tarjetas que se usan en todas partes y ahora viene el problema triple: (1) la app debe seguir el modo oscuro del SISTEMA, pero con un toggle manual que gane sobre el sistema (y que recuerde a quien puso «claro» viviendo en un sistema oscuro); (2) las tarjetas que se cuelgan dentro de la barra lateral, que en oscuro es MÁS oscura que el resto, deben invertir su esquema localmente sin que nadie les añada clases; (3) el diseño quiere densidad: la tarjeta con más de 400px de ancho muestra sus datos a dos columnas, la de menos de 260px encoge el título — y eso depende del ancho de la COLUMNA donde caiga la tarjeta, no de la ventana."""),
            ("assistant", r"""Los tres problemas tienen herramientas distintas y conviene no mezclarlas:

1. **Preferencia de tema** = tokens en `:root` + una regla de precedencia explícita: sistema oscuro por defecto, PERO el atributo manual manda. El patrón de tres estados (`auto/claro/oscuro`) con `:root:not([data-theme="light"])` dentro de la media query del sistema — así «auto» es la ausencia de atributo y el toggle escribe `light`/`dark` en `<html>`.
2. **Re-tematización contextual** = herencia de variables. La barra lateral no «sabe» que es oscura: DEFINE sus tokens localmente (`--superficie`, `--tinta`) y `color-scheme` propio; cualquier tarjeta dentro hereda y se repinta sin una clase nueva. Este es el uso que casi nadie hace y resuelve tu punto (2) con cero JS.
3. **Densidad por contenedor** = container queries con `container-type: inline-size`: la tarjeta se mide contra su COLUMNA, no contra el viewport.

```css
/* ── 1) Tokens globales y las TRES capas de preferencia ────────────────── */
:root {
  color-scheme: light dark;
  --superficie: #ffffff;
  --tinta: #17212e;
  --borde: #dbe2ea;
  --acento: #2563eb;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {   /* auto: sistema oscuro, sin veto manual */
    --superficie: #151a23;
    --tinta: #e8edf4;
    --borde: #2a3240;
    --acento: #6ea8ff;
  }
}
[data-theme="dark"] {                  /* manual: gana sobre el sistema */
  --superficie: #151a23;
  --tinta: #e8edf4;
  --borde: #2a3240;
  --acento: #6ea8ff;
}
[data-theme="light"] {                 /* manual claro: veto explícito */
  --superficie: #ffffff;
  --tinta: #17212e;
  --borde: #dbe2ea;
  --acento: #2563eb;
}

/* ── 2) Re-tematización contextual: la barra oscura DEFINE sus tokens ──── */
.rail {
  --superficie: #0d1118;   /* más oscura que el tema oscuro general */
  --tinta: #c9d3e0;
  --borde: #202a38;
  color-scheme: dark;      /* scrollbars, inputs y form controls nativos a juego */
  background: var(--superficie);
}
/* Cualquier .card dentro de .rail hereda esos valores: cero clases nuevas. */
.card {
  background: var(--superficie);
  color: var(--tinta);
  border: 1px solid var(--borde);
  border-radius: 12px;
  padding: 14px;
  container-type: inline-size;
  container-name: tarjeta;
}

/* ── 3) Densidad contra el ANCHO DE LA TARJETA, no de la ventana ───────── */
@container tarjeta (min-width: 400px) {
  .card .datos { grid-template-columns: 1fr 1fr; gap: 8px 16px; }
}
@container tarjeta (max-width: 259px) {
  .card h3 { font-size: .85rem; letter-spacing: 0; }
  .card .datos { gap: 6px; }
}
.card .datos { display: grid; grid-template-columns: 1fr; gap: 8px; }
```

El toggle solo necesita `document.documentElement.dataset.theme = "claro" | "oscuro"` (y borrar el atributo para volver a «auto»); la persistencia es una línea de localStorage con tu módulo de migraciones. Sin JS de detección de tema: CSS ya lo sabe."""),
            ("user", r"""Me gusta, pero quiero entender bien los bordes del sistema antes de adoptarlo: ¿qué pasa exactamente si el usuario pone data-theme="light" con sistema oscuro? ¿Y si el toggle está en "dark" pero un widget tercero se renderiza blanco, quién gana? Y lo crítico: las tarjetas del rail con container queries, ¿cómo compruebo que la densidad reacciona al ancho de la tarjeta y no al de la ventana?"""),
            ("assistant", r"""Caso por caso, porque aquí es donde se aprecia por qué la cascada está escrita así:

* `data-theme="light"` con sistema oscuro: la media query del sistema EXCLUYE esa raíz (`:root:not([data-theme="light"])`), así que no aplica el bloque oscuro; el bloque `[data-theme="light"]` fija los tokens claros. Gana el veto manual — es la semántica que pediste (recordar a quien eligió claro viviendo en oscuro).
* Widget tercero blanco dentro del tema oscuro: con tu esquema, gana QUIEN DEFINE LOS TOKENS más cercano al widget. Si el widget usa `var(--superficie)` hereda y se integra; si trae colores hardcodeados, nada CSS razonable lo salva — eso se negocia con el proveedor o se aisla. Lo que SÍ puedes hacer es darle un `color-scheme` correcto en su contenedor para que sus controles nativos no destaquen, y documentar «los widgets deben consumir tokens» como contrato del design system.
* Transiciones de tema: un `transition: background-color .2s` en los componentes que consumen tokens da un cambio suave; no lo pongas en `*` (animarías el repintado de toda la página y con `prefers-reduced-motion` te lo deben saltar).

La verificación en navegador, protocolada: (1) DevTools → Rendering → *Emulate CSS media feature prefers-color-scheme* para probar «auto» en ambos modos sin tocar tu sistema; (2) toggle manual desde consola (`document.documentElement.dataset.theme = "light"`) y recarga — comprobar que persiste y que el `color-scheme` cambia también los scrollbars y los inputs (ese detalle delata un dark mode a medias); (3) para las container queries: en el panel Layout del inspector verás los contenedores con su badge; arrastra el ancho DE LA COLUMNA (no de la ventana) donde cae la tarjeta y verifica que el corte a dos columnas de `.datos` ocurre al cruzar 400px de TARJETA — si cambia al redimensionar la ventana con la tarjeta del mismo ancho, alguien puso una media query donde iba una container query; (4) y la prueba de contraste con un auditor (Lighthouse o la pestaña Rendering → contrast) en las DOS densidades y los TRES temas: 9 combinaciones, porque los errores de contraste casi siempre viven en una sola de esas celdas de la matriz."""),
        ],
        tags=["css", "dark-mode", "custom-properties", "container-queries", "color-scheme", "design-system"],
        stack=["css"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 13
    E(
        language="javascript",
        domain="web",
        subdomain="debug_duplicate_listeners",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", r"""Nos está pasando algo muy raro con el widget de etiquetas del editor. El código es este (versión reducida):

```javascript
function createTagWidget(root) {
  const list = root.querySelector("ul#tags");
  let marcadas = 0;

  function render(tags) {
    list.replaceChildren(
      ...tags.map((t) => {
        const li = document.createElement("li");
        li.textContent = t;
        list.addEventListener("click", () => { marcadas += 1; });
        return li;
      })
    );
  }

  return { render, get marcadas() { return marcadas; } };
}
```

El síntoma: al cargar la página funciona, pero si cambias de pestaña del editor y vuelves (cada cambio re-renderiza la lista con datos frescos), un solo clic marca/desmarca DOS o TRES veces. Ayer un usuario nos enseñó un vídeo donde un clic le borraba la etiqueta Y la volvía a poner. En dev no lo vemos casi nunca; en la demo de ayer pasó tres veces."""),
            ("assistant", r"""Síntoma: un clic, N efectos, y N crece con el número de re-renders. Hipótesis inmediata: hay MÁS de un listener vivo respondiendo al mismo clic. Mirando tu `render()`, veo un `list.addEventListener` DENTRO de la función que se llama en cada re-render — y los listeners se ACUMULAN: `addEventListener` no deduplica funciones anónimas nuevas (cada arrow es una función distinta), y `replaceChildren` borra los `<li>` hijos pero NO los listeners del `<ul>`, que es donde quedaron registrados. El detalle que lo explica todo: registras sobre el CONTENEDOR, dentro del render de los HIJOS.

Pero una hipótesis no es un diagnóstico: lo verifico con un mini-DOM determinista en Node — un elemento falso que guarda los listeners por tipo y los ejecuta en cada `click()`. Si mi hipótesis es correcta, tras 3 renders un clic debe ejecutar 3 handlers y el contador debe crecer de golpe.

```javascript
"use strict";

// Mock mínimo del DOM: cada elemento guarda sus listeners por tipo.
function createFakeElement(name) {
  const listeners = { click: [] };
  return {
    name,
    addEventListener(type, fn) { listeners[type].push(fn); },
    removeEventListener(type, fn) {
      listeners[type] = listeners[type].filter((f) => f !== fn);
    },
    click() { for (const fn of [...listeners.click]) fn({ target: this }); },
    countListeners: (type) => listeners[type].length,
  };
}

// ══ código del widget, TAL CUAL está en producción ══════════════════════════
function createTagWidget() {
  const list = createFakeElement("ul#tags");
  let applied = 0;

  function render(tags) {
    // (aquí el widget real reconstruye los <li> a partir del estado)
    // y justo debajo está el problema:
    list.addEventListener("click", () => {
      applied += 1; // p. ej., marcar/desmarcar un tag
    });
  }

  return {
    render,
    simulateClick: () => list.click(),
    stats: () => ({ applied, listeners: list.countListeners("click") }),
  };
}

// ══ secuencia que reproduce lo que cuenta el usuario ════════════════════════
const widget = createTagWidget();
widget.render(["frontend", "css"]);        // montaje inicial
widget.simulateClick();                    // 1 clic: funciona
widget.render(["frontend", "css", "js"]);  // llegan datos nuevos → re-render
widget.simulateClick();                    // el clic «cuenta doble»
widget.render(["frontend", "css", "js", "node"]);
widget.simulateClick();                    // ahora «cuenta triple»

const s = widget.stats();
console.log("renders: 3 | clics simulados: 3");
console.log("CLICKS REGISTRADOS=" + s.applied + " (lo correcto sería 3, uno por clic)");
console.log("LISTENERS ACTIVOS=" + s.listeners + " (lo correcto sería 1)");
```"""),
            ("tool", r"""$ node repro_listeners.mjs
renders: 3 | clics simulados: 3
CLICKS REGISTRADOS=6 (lo correcto sería 3, uno por clic)
LISTENERS ACTIVOS=3 (lo correcto sería 1)
$ echo $?
0"""),
            ("assistant", r"""Reproducido y medido: 3 renders → 3 listeners vivos → 3 clics ejecutaron 6 handlers. El bug queda demostrado, no solo explicado: `LISTENERS ACTIVOS=3` es la fuga y `CLICKS REGISTRADOS=6` el síntoma que vio tu usuario. Causa raíz: registrar un listener DENTRO de una función de render que se ejecuta repetidamente, sobre un elemento que no se regenera. En el navegador real el efecto es idéntico — y de ahí también tu «en dev casi nunca»: solo lo notas si re-renderizas antes de clicar, que en la demo (datos frescos) pasa siempre.

La corrección de fondo es un INVARIANTE: los listeners del contenedor se registran UNA vez en el ciclo de vida del widget; render() reconstruye contenido y jamás toca el registro de eventos.

```javascript
"use strict";

// Mock mínimo del DOM (idéntico al del diagnóstico).
function createFakeElement(name) {
  const listeners = { click: [] };
  return {
    name,
    addEventListener(type, fn) { listeners[type].push(fn); },
    removeEventListener(type, fn) {
      listeners[type] = listeners[type].filter((f) => f !== fn);
    },
    click() { for (const fn of [...listeners.click]) fn({ target: this }); },
    countListeners: (type) => listeners[type].length,
  };
}

// ══ widget corregido: el listener vive FUERA de render ══════════════════════
function createTagWidget() {
  const list = createFakeElement("ul#tags");
  let applied = 0;

  // Se registra UNA vez en la construcción del widget; render() solo
  // reconstruye <li>, nunca toca listeners del contenedor.
  list.addEventListener("click", (event) => {
    applied += 1;
  });

  function render(tags) {
    // (reconstrucción de <li>… sin addEventListener aquí dentro)
  }

  return {
    render,
    simulateClick: () => list.click(),
    stats: () => ({ applied, listeners: list.countListeners("click") }),
  };
}

// ══ misma secuencia que en el diagnóstico ═══════════════════════════════════
const widget = createTagWidget();
widget.render(["frontend", "css"]);
widget.simulateClick();
widget.render(["frontend", "css", "js"]);
widget.simulateClick();
widget.render(["frontend", "css", "js", "node"]);
widget.simulateClick();

const s = widget.stats();
console.log("renders: 3 | clics simulados: 3");
console.log("CLICKS REGISTRADOS=" + s.applied + " (correcto: 3, uno por clic)");
console.log("LISTENERS ACTIVOS=" + s.listeners + " (correcto: 1)");
```"""),
            ("tool", r"""$ node repro_listeners_fix.mjs
renders: 3 | clics simulados: 3
CLICKS REGISTRADOS=3 (correcto: 3, uno por clic)
LISTENERS ACTIVOS=1 (correcto: 1)
$ echo $?
0"""),
            ("assistant", r"""Fix verificado: mismo guion, ahora 3 clics = 3 efectos con 1 listener estable. Para cerrar el método, tres cosas que conviene fijar en el equipo:

* Si el registro tiene que quedar dentro de una función con ciclo de vida (por ejemplo, un `mount()` que se llama por widget instanciado), la alternativa robusta es el patrón `AbortController`: `list.addEventListener("click", handler, { signal })` guardando el controlador, y `abort()` en el `unmount()` correspondiente — la limpieza es una llamada y olvida el `removeEventListener` con referencias estables (imposible con arrows anónimas).
* No confundas este bug con el del `this` en handlers: aquí el handler funcionaba, solo que MÚLTIPLES veces. La huella en el profiler es distintiva: la misma línea de handler aparece N veces en el call stack del evento.
* Y el guardián estructural: delegación de eventos (UN listener en el `<ul>` para toda la lista, decidir por `closest()`) elimina la categoría entera de bugs, porque el re-render deja de tocar listeners por completo. Cómo se comprobaría en el navegador real: en DevTools, `getEventListeners(document.querySelector("ul#tags"))` en la consola — debe devolver `click: [f]` con UNA entrada tras cualquier número de re-renders; ese mismo chequeo en la versión rota mostraba tres."""),
        ],
        tags=["javascript", "event-listeners", "duplicacion", "re-render", "abortcontroller", "debugging"],
        stack=["javascript"],
        recovery=True,
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": ["CLICKS REGISTRADOS=6", "LISTENERS ACTIVOS=3"],
             "expect_stdout_not_contains": ["LISTENERS ACTIVOS=1"]},
            {"name": "fix_correcto", "action": "run", "lang": "js", "msg": 4, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": ["CLICKS REGISTRADOS=3", "LISTENERS ACTIVOS=1"]},
        ],
    ),
    # ------------------------------------------------------------------ 14
    E(
        language="javascript",
        domain="web",
        subdomain="debug_script_order_dom",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Tengo una página de administración donde a veces el JS «no engancha» los botones y la consola muestra:

Uncaught TypeError: Cannot read properties of null (reading 'addEventListener')

El script está en el `<head>`:

```html
<head>
  <meta charset="utf-8">
  <script src="/js/admin-init.js"></script>
</head>
<body>
  <button id="save-btn">Guardar</button>
  <table id="rows">…</table>
</body>
```

Y `admin-init.js` empieza así:

```javascript
const saveBtn = document.getElementById("save-btn");
saveBtn.addEventListener("click", guardar);
```

Lo paradoxal: no falla SIEMPRE. Desde una pestaña nueva falla casi siempre; con recarga normal, a veces entra. Ya me dirás qué está pasando, porque los ficheros están servidos por CDN y no cambia el HTML."""),
            ("assistant", r"""El patrón «falla más en frío que recargando» es la firma de una CARRERA de orden de carga, no de un bug determinista del DOM. Hipótesis: tu script en `<head>` se ejecuta ANTES de que el parser haya construido los elementos del `<body>`; `document.getElementById("save-btn")` devuelve `null` y el `addEventListener` revienta. ¿Por qué «a veces»? Porque la descarga del script desde CDN compite con el parseo: si el script tarda en llegar (red fría, caché vacía → pestaña nueva), el parser lo espera (un `<script>` clásico BLOQUEA el parser) y se ejecuta con el body aún vacío; si llega desde caché puede… no, cuidado: con script clásico bloqueante el orden SIEMPRE es script-antes-que-body. Lo que varía es que si el script viene de caché HTTP y se ejecuta antes, el error salta SIEMPRE; tu «a veces» suele indicar que el navegador a veces sirve el HTML completo con el script embebido/precargado, o que hay otro `admin-init` con `defer` ya mezclado en el bundle. En cualquier caso la causa raíz es la misma y es demostrable.

La verifico con un simulador determinista del orden de parsing: un documento falso que solo REGISTRA los elementos al «terminar el parseo», igual que hace un navegador real respecto a lo que el script puede ver en fase `loading`.

```javascript
"use strict";

// Mini-documento que imita el orden real de un navegador: durante "loading"
// el árbol aún NO contiene los elementos que el parser no ha alcanzado.
function createFakeDocument() {
  const elements = new Map();
  const domReadyQueue = [];
  let readyState = "loading";
  return {
    readyState: () => readyState,
    getElementById: (id) => (elements.has(id) ? elements.get(id) : null),
    addEventListener(type, fn) { if (type === "DOMContentLoaded") domReadyQueue.push(fn); },
    _finishParsing() {
      elements.set("save-btn", {
        id: "save-btn",
        bound: 0,
        addEventListener() { this.bound += 1; },
      });
      elements.set("rows", { id: "rows", children: 3 });
      readyState = "interactive";
      for (const fn of domReadyQueue.splice(0)) fn();
    },
  };
}

// ══ script tal como está en producción: en <head>, sin defer ════════════════
const document = createFakeDocument(); // simula el documento en fase "loading"

try {
  const btn = document.getElementById("save-btn");
  btn.addEventListener("click", () => {}); // ← aquí revienta
  console.log("listener instalado");
  console.log("ESTADO=OK filas=" + document.getElementById("rows").children);
} catch (err) {
  console.log(err.constructor.name + ": " + err.message);
  console.log("ESTADO=ROTO");
}

document._finishParsing(); // el DOM termina de construirse… demasiado tarde
```"""),
            ("tool", r"""$ node repro_orden_carga.mjs
TypeError: Cannot read properties of null (reading 'addEventListener')
ESTADO=ROTO
$ echo $?
0"""),
            ("assistant", r"""Reproducido: `getElementById` en fase `loading` devuelve `null` y la excepción es exactamente la de tu consola. Causa raíz confirmada: el script se ejecuta antes de que exista el elemento; la «aleatoriedad» que veías es solo competencia de red/caché alrededor de ese orden inevitable.

Corrección — ordenada por preferencia real de ingeniería:

1. **`defer`** en el `<script>` (defer está PARA esto): se descarga en paralelo y se ejecuta DESPUÉS de parsear, antes de `DOMContentLoaded`. Una palabra en el HTML, cero cambios en el JS.
2. **`type="module"`** si vas a modularizar: los módulos son defer por defecto.
3. Si no puedes tocar la etiqueta, **esperar al DOM** en el propio script — es la corrección que verifico abajo.
4. Mover el script al final del `<body>` «funciona», pero deja el orden implícito en la estructura: es la solución frágil de las cuatro.

```javascript
"use strict";

// Mini-documento idéntico al del diagnóstico.
function createFakeDocument() {
  const elements = new Map();
  const domReadyQueue = [];
  let readyState = "loading";
  return {
    readyState: () => readyState,
    getElementById: (id) => (elements.has(id) ? elements.get(id) : null),
    addEventListener(type, fn) { if (type === "DOMContentLoaded") domReadyQueue.push(fn); },
    _finishParsing() {
      elements.set("save-btn", {
        id: "save-btn",
        bound: 0,
        addEventListener() { this.bound += 1; },
      });
      elements.set("rows", { id: "rows", children: 3 });
      readyState = "interactive";
      for (const fn of domReadyQueue.splice(0)) fn();
    },
  };
}

// ══ script corregido: la inicialización espera al DOM ═══════════════════════
const document = createFakeDocument();

function init() {
  const btn = document.getElementById("save-btn");
  btn.addEventListener("click", () => {});
  console.log("listener del botón instalado");
  console.log("ESTADO=OK filas=" + document.getElementById("rows").children);
}

if (document.readyState() === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init(); // por si el script llega a ejecutarse con el DOM ya listo
}

document._finishParsing();
```"""),
            ("tool", r"""$ node repro_orden_carga_fix.mjs
listener del botón instalado
ESTADO=OK filas=3
$ echo $?
0"""),
            ("assistant", r"""El fix pasa: en fase `loading` se SUSCRIBE al `DOMContentLoaded` y la inicialización corre cuando los elementos ya existen; el guard `readyState` cubre el caso de un script que llegue a ejecutarse con el DOM listo (por ejemplo si mañana le añades `defer` — el mismo código funciona en ambos mundos). Con esto la carrera desaparece porque ya no hay dos ordenes posibles: hay UN orden correcto.

Dos advertencias para cerrar bien: (1) `DOMContentLoaded` no espera a las IMÁGENES ni a las hojas de estilo externas aplicadas tarde — si tu `init` mide geometría (`offsetWidth`), el evento que buscas es `load`, o mejor, deja de medir en carga; (2) si algún día mueves el script a `type="module"`, NO añadas también el wrapper `DOMContentLoaded` por duplicado… no romperá (el evento ya pasó y el guard lo cubre), pero sería código que sugiere que no se entiende el orden — y ese tipo de ruido es el que después despierta las carreras de nuevo. Cómo se comprobaría en el navegador real: pestaña Network con *Disable cache* y throttling «Slow 4G» en la versión rota reproduce el fallo sistemático (el script bloquea el parseo con el body vacío); en la versión con `defer`, el orden en el log de consola debe ser «HTML parseado» → «admin-init ejecutado» → «DOMContentLoaded», y `getEventListeners(document.getElementById("save-btn"))` devuelve el listener en el primer arranque en frío."""),
        ],
        tags=["javascript", "dom", "orden-de-carga", "defer", "domcontentloaded", "debugging"],
        stack=["javascript", "html"],
        recovery=True,
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": ["TypeError: Cannot read properties of null (reading 'addEventListener')"],
             "expect_stdout_not_contains": ["ESTADO=OK"]},
            {"name": "fix_correcto", "action": "run", "lang": "js", "msg": 4, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": ["ESTADO=OK filas=3"],
             "expect_stdout_not_contains": ["ESTADO=ROTO", "TypeError"]},
        ],
    ),
    # ------------------------------------------------------------------ 15
    E(
        language="javascript",
        domain="web",
        subdomain="debug_interval_leak",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", r"""El widget de cotizaciones de la portada nos está generando quejas de rendimiento serias: la gente que deja la pestaña abierta toda la mañana acaba con la pestaña consumiendo cientos de MB y, lo más raro, los logs del backend muestran que «los ticks» se disparan cada vez más rápido — como si cada segundo hubiese varias peticiones de refresco del mismo usuario. El widget se monta y desmonta según en qué vista esté el usuario (hay un `mount()` que crea el refresco y un ciclo de vida normal entrada/salida). Sospecho de mi propio código pero no veo nada: el intervalo es UNO, de un segundo. Te pego el trozo sospechoso:

```javascript
function mount() {
  setInterval(refrescarCotizaciones, 1000);
  // …resto del mount (pintar DOM, suscribirse a eventos)…
}
```

Ah, y no hay `unmount()` que limpie el intervalo; al desmontar solo quitamos el nodo del DOM."""),
            ("assistant", r"""Tu sospecha es la correcta y tus dos síntomas son EL MISMO bug visto desde dos capas. Análisis: `setInterval` devuelve un manejador y programa una tarea viva en el event loop; si nadie la cancela, el temporizador SOBREVIVE al widget. Como dentro del callback hay una referencia a `refrescarCotizaciones` (que cierra sobre el estado del widget), el recolector de basura no puede reclamar NI el closure NI el árbol DOM que ese closure retiene — por eso crece la memoria (nodos desmontados pero «attached» a un timer vivo: los famosos *detached nodes*). Y el «cada vez más rápido»: cada entrada en la vista monta OTRO intervalo; tras N entradas hay N intervalos por segundo, N peticiones al backend, N×CPU. Nada de magia: aritmética de fugas.

Hipótesis formalizada: «mount sin unmount limpia cero temporizadores; cada ciclo entrada/salida añade un intervalo vivo». La verifico con un registro de timers determinista que me deja avanzar el reloj por ciclos y AUDITAR cuántos intervalos siguen vivos — en Node, sin esperar un segundo real:

```javascript
"use strict";

// Registro de temporizadores simulado: permite "avanzar el reloj" y auditar
// cuántos intervalos siguen vivos en cualquier momento.
function createFakeTimers() {
  let nextId = 1;
  const live = new Map(); // id → { fn, every }
  return {
    setInterval(fn, every) { const id = nextId++; live.set(id, { fn, every }); return id; },
    clearInterval(id) { live.delete(id); },
    advance(cycles) {
      let ticks = 0;
      for (let c = 0; c < cycles; c++) {
        for (const { fn } of [...live.values()]) { fn(); ticks += 1; }
      }
      return ticks;
    },
    count: () => live.size,
  };
}

// ══ widget con el bug: monta un intervalo y NUNCA lo desmonta ═══════════════
function createQuoteWidget(timers) {
  let updates = 0;
  function mount() {
    // refresco de cotizaciones cada segundo; el id se pierde aquí mismo
    timers.setInterval(() => { updates += 1; }, 1000);
  }
  // No hay unmount(): cuando el componente desaparece de la pantalla,
  // el intervalo sigue vivo apuntando a un closure que nadie más referencia.
  return { mount, stats: () => ({ updates, live: timers.count() }) };
}

// ══ el usuario entra, sale y vuelve tres veces ══════════════════════════════
const timers = createFakeTimers();
const widget = createQuoteWidget(timers);
widget.mount(); timers.advance(1);
widget.mount(); timers.advance(1);
widget.mount(); timers.advance(1);

const s = widget.stats();
console.log("montajes: 3 (entró/salió/entró/salió/entró/salió/entró)");
console.log("INTERVALOS VIVOS=" + s.live + " (correcto tras el último unmount: 0)");
console.log("TICKS TOTALES=" + s.updates + " (correcto: 3, uno por ciclo de refresco)");
```"""),
            ("tool", r"""$ node repro_intervalos.mjs
montajes: 3 (entró/salió/entró/salió/entró/salió/entró)
INTERVALOS VIVOS=3 (correcto tras el último unmount: 0)
TICKS TOTALES=6 (correcto: 3, uno por ciclo de refresco)
$ echo $?
0"""),
            ("assistant", r"""Reproducido con aritmética exacta: 3 ciclos de entrada/salida → 3 intervalos vivos y 6 ticks donde deberían ser 3. Tras una mañana entrando y saliendo, esos «3» son «cientos»: coincide con tus logs del backend (N peticiones por segundo por usuario que entró N veces) y con la memoria (N closures retenidos con sus árboles DOM desmontados). Causa raíz: `mount()` crea un recurso del event loop y el ciclo de vida del componente no lo devuelve.

La corrección tiene dos mitades inseparables: GUARDAR el id y DEVOLVERLO en el unmount. Y una tercera, defensiva: hacer `mount()` idempotente, porque los frameworks re-montan más de lo que la gente cree.

```javascript
"use strict";

// Registro de temporizadores simulado (idéntico al del diagnóstico).
function createFakeTimers() {
  let nextId = 1;
  const live = new Map();
  return {
    setInterval(fn, every) { const id = nextId++; live.set(id, { fn, every }); return id; },
    clearInterval(id) { live.delete(id); },
    advance(cycles) {
      let ticks = 0;
      for (let c = 0; c < cycles; c++) {
        for (const { fn } of [...live.values()]) { fn(); ticks += 1; }
      }
      return ticks;
    },
    count: () => live.size,
  };
}

// ══ widget corregido: unmount() limpia SU intervalo ═════════════════════════
function createQuoteWidget(timers) {
  let updates = 0;
  let intervalId = null;
  function mount() {
    if (intervalId !== null) return; // idempotente: un doble mount no duplica
    intervalId = timers.setInterval(() => { updates += 1; }, 1000);
  }
  function unmount() {
    if (intervalId !== null) {
      timers.clearInterval(intervalId);
      intervalId = null;
    }
  }
  return { mount, unmount, stats: () => ({ updates, live: timers.count() }) };
}

// ══ misma secuencia, ahora con mount/unmount emparejados ════════════════════
const timers = createFakeTimers();
const widget = createQuoteWidget(timers);
widget.mount(); timers.advance(1); widget.unmount();
widget.mount(); timers.advance(1); widget.unmount();
widget.mount(); timers.advance(1); widget.unmount();

const s = widget.stats();
console.log("montajes: 3, unmounts: 3");
console.log("INTERVALOS VIVOS=" + s.live + " (correcto: 0)");
console.log("TICKS TOTALES=" + s.updates + " (correcto: 3, uno por ciclo)");
```"""),
            ("tool", r"""$ node repro_intervalos_fix.mjs
montajes: 3, unmounts: 3
INTERVALOS VIVOS=0 (correcto: 0)
TICKS TOTALES=3 (correcto: 3, uno por ciclo)
$ echo $?
0"""),
            ("assistant", r"""Fix verificado: 3 montajes, 3 unmounts, 0 intervalos vivos, 3 ticks. El par mount/unmount es ahora simétrico y el backend volverá a ver un tick por segundo por usuario. Para que no vuelva a ocurrir, tres apuntes de senior:

* La categoría de este bug es «recurso adquirido sin devolver»: intervalos, `setTimeout`, listeners, observadores (`IntersectionObserver`, `ResizeObserver`), streams y workers. El remedio estructural es exigir simetría adquisición/liberación en la misma función de ciclo de vida — y en React es literalmente lo que hace la función de retorno de `useEffect`.
* Alternativa moderna y más elegante al intervalo: un bucle `setTimeout` re-programado con un `AbortController` por ciclo de vida (`await sleep(1000, signal)`): al abortar, el bucle muere y no hay id que gestionar — mismo resultado, menos estado.
* Cómo se comprueba en el navegador real: DevTools → Memory → heap snapshot ANTES y DESPUÉS de 10 entradas/salidas de la vista; en el snapshot post, filtra por *Detached* — la versión rota muestra decenas de nodos del widget retenidos por `Timer`; en la corregida, cero. Y la prueba de sintoma rápido: en la consola de la versión rota, `console.count` dentro de `refrescarCotizaciones` acumula 2, 3, 4… ticks por segundo conforme re-entras; en la corregida, el contador crece 1 por segundo siempre."""),
        ],
        tags=["javascript", "setinterval", "memory-leak", "detached-nodes", "ciclo-de-vida", "debugging"],
        stack=["javascript"],
        recovery=True,
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "js", "msg": 2, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": ["INTERVALOS VIVOS=3", "TICKS TOTALES=6"],
             "expect_stdout_not_contains": ["INTERVALOS VIVOS=0"]},
            {"name": "fix_correcto", "action": "run", "lang": "js", "msg": 4, "block": 0,
             "expect_exit": 0, "timeout_s": 10,
             "expect_stdout_contains": ["INTERVALOS VIVOS=0", "TICKS TOTALES=3"]},
        ],
    ),
]

