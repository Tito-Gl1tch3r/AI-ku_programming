"""
m_python_adv.py — Módulo 2-g: Python avanzado (40 ejemplos verificables).

Cobertura: asyncio profundo (gather/return_exceptions, wait_for, semáforos,
cancelación limpia, Queue con contrapresión, servidor TCP), subprocess seguro
(deadlock de pipes, timeouts, pipelines sin shell), servicios HTTP con stdlib,
parsing robusto (JSONL con cuarentena, regex con named groups, dialectos CSV),
typing avanzado (Protocol, TypedDict+cast, TypeVar, dataclasses), rendimiento
(cProfile/pstats, lru_cache, singledispatch, itertools, contextmanager,
descriptores), unittest verificable, persistencia sqlite3 con transacciones,
streaming de ficheros grandes y automatización de ficheros (watcher mtime,
rotación, dedupe por hash).

Todos los bloques ejecutables son autocontenidos, deterministas y terminan
solos (los servidores se apagan con shutdown/join).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from schema import E  # noqa: E402

EXAMPLES = [
    # ------------------------------------------------------------------ 01
    E(
        language="python",
        domain="backend",
        subdomain="asyncio_fanout",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Dirijo un job nocturno de salud que debe sondear 60 servicios internos de la plataforma de facturación. Mis dos intentos actuales fallan: (1) el bucle secuencial tarda demasiado con los servicios lentos; (2) la versión con asyncio.gather aborta TODO el lote cuando un endpoint lanza excepción y se queda colgado indefinidamente si un servicio no responde. Requisitos: paralelismo real con máximo 10 sondeos concurrentes, timeout de 1 s por endpoint, un resultado por servicio (estado tipado, nunca excepción no controlada), resumen agregado por estado y terminación garantizada del proceso en < 3 s. Como no hay red en el entorno de pruebas, el «cluster» se simula con coroutines que duermen (2 colgados que nunca responden, 2 que lanzan ConnectionRefusedError, 56 sanos). Necesito implementación y verificación."""),
            ("assistant", r"""Requisitos inferidos: (a) aislamiento de fallos por sondeo — un fallo no debe cancelar el lote; (b) límite de concurrencia — un Semaphore(10) compartido por todos los sondeos; (c) timeout individual — asyncio.wait_for por tarea, no un timeout global del lote; (d) terminación garantizada — los colgados se cortan con wait_for y ninguna tarea sobrevive al gather.

Trade-offs: en lugar de gather(return_exceptions=True), capturo la excepción DENTRO de cada tarea y devuelvo (nombre, estado): así el resumen distingue «fallo:TimeoutError» de «fallo:ConnectionRefusedError», que es lo que el guardia de guardias necesita para alertar distinto. El semáforo se adquiere dentro de sondear() para que el timeout también cubra el tiempo de espera en la cola del semáforo. Coste aceptado: los 2 colgados sostienen su slot hasta el timeout de 1 s, con lo que el lote dura ~1 s, muy por debajo del límite de 3 s."""),
            ("tool", r"""$ python healthcheck_lote.py
fallo:ConnectionRefusedError: 2
fallo:TimeoutError: 2
ok: 56
total: 60
duracion: 1.06s"""),
            ("assistant", r"""Versión completa ejecutable. El assert final protege la decisión clave: si alguien elimina el Semaphore y no el gather, la duración se dispara o el lote explota; si serializa, el assert de duración falla.

```python
import asyncio
import time

async def sondear(nombre: str, sem: asyncio.Semaphore,
                  *, colgado: bool = False, roto: bool = False) -> tuple[str, str]:
    async with sem:                      # máximo 10 sondeos en vuelo
        await asyncio.sleep(0.03)        # latencia típica del servicio
        if colgado:
            await asyncio.sleep(30)      # servicio que no responde nunca
        if roto:
            raise ConnectionRefusedError(f"{nombre}: puerto cerrado")
        return (nombre, "ok")

async def main() -> None:
    sem = asyncio.Semaphore(10)
    objetivos = [(f"svc{i:02d}", {}) for i in range(56)] + [
        ("svc-colgado-1", {"colgado": True}),
        ("svc-colgado-2", {"colgado": True}),
        ("svc-roto-1", {"roto": True}),
        ("svc-roto-2", {"roto": True}),
    ]

    async def uno(nombre: str, kw: dict) -> tuple[str, str]:
        try:
            return await asyncio.wait_for(sondear(nombre, sem, **kw), timeout=1.0)
        except Exception as exc:         # aislamiento: el fallo muere en esta tarea
            return (nombre, f"fallo:{type(exc).__name__}")

    t0 = time.monotonic()
    resultados = await asyncio.gather(*(uno(n, kw) for n, kw in objetivos))
    duracion = time.monotonic() - t0

    resumen: dict[str, list[str]] = {}
    for nombre, estado in resultados:
        resumen.setdefault(estado, []).append(nombre)
    for estado in sorted(resumen):
        print(f"{estado}: {len(resumen[estado])}")
    print(f"total: {len(resultados)}")
    print(f"duracion: {duracion:.2f}s")
    assert duracion < 3.0, "el lote no debe degradarse a ejecución secuencial"

asyncio.run(main())
```

Verificación: 60 sondeos (56 ok, 2 por timeout, 2 por conexión rechazada), sin excepción global y terminación en ~1 s."""),
        ],
        verify=[
            {"name": "ejecucion", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["total: 60", "ok: 56",
                                        "fallo:TimeoutError: 2",
                                        "fallo:ConnectionRefusedError: 2"],
             "timeout_s": 25},
        ],
        tags=["asyncio", "semaphore", "wait_for", "healthcheck", "fan-out"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 02
    E(
        language="python",
        domain="backend",
        subdomain="asyncio_backpressure",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Tengo un ingestor de eventos: un productor que recibe webhooks y un consumidor que los persiste. La primera versión usaba una lista infinita como buffer: cuando el consumidor era más lento, la RAM crecía sin control hasta que el OOM killer mataba el proceso. Necesito que me lo montes con asyncio.Queue demostrando contrapresión real: cola acotada a 5 elementos, el productor debe BLOQUEARSE (no descartar, no crecer) cuando la cola está llena, y un informe final que pruebe que no se perdió ningún evento y que la ocupación nunca superó el límite. 50 eventos, consumidor más lento que productor."""),
            ("assistant", r"""Requisitos inferidos: (a) acotación dura — asyncio.Queue(maxsize=5); await put() suspende al productor en cola llena (contrapresión hacia arriba), nunca se descartan eventos; (b) cierre ordenado — productor termina, q.join() espera a que el consumidor marque task_done() de TODOS los ítems, y solo entonces se cancela al consumidor; (c) evidencia — máximo de ocupación observado medido dentro del consumidor (qsize()+1 tras el get), que debe ser exactamente 5 si la contrapresión funcionó.

Decisiones: el conteo de ocupación se hace en el consumidor porque es quien ve la cola llena; medirla en el productor subestima (mide antes del put bloqueante). La cancelación del consumidor va envuelta en try/except CancelledError porque cancel() sobre una tarea que ya terminó es inofensivo, pero si está en await get() hay que absorber la señal esperada. Trade-off aceptado: task_done() en finally para que un error del procesamiento no cuente el ítem como no consumido y cuelgue join()."""),
            ("tool", r"""$ python ingestor.py
producidos=50
procesados=50
max_ocupacion=5"""),
            ("assistant", r"""Implementación completa con los tres invariantes verificados al final (nada perdido, todo procesado, tope respetado):

```python
import asyncio

MAX_Q = 5
TOTAL = 50

async def productor(q: asyncio.Queue, stats: dict) -> None:
    for i in range(TOTAL):
        await q.put(i)               # se suspende si la cola está llena: contrapresión
        stats["producidos"] += 1
        await asyncio.sleep(0.002)   # productor 5x más rápido que el consumidor

async def consumidor(q: asyncio.Queue, stats: dict) -> None:
    while True:
        await q.get()
        # medimos ANTES de procesar: qsize()+1 es la ocupación que había al despertar
        stats["max_ocupacion"] = max(stats["max_ocupacion"], q.qsize() + 1)
        try:
            await asyncio.sleep(0.01)  # la persistencia es lo lento
            stats["procesados"] += 1
        finally:
            q.task_done()              # siempre: un fallo no debe colgar a join()

async def main() -> None:
    q: asyncio.Queue = asyncio.Queue(maxsize=MAX_Q)
    stats = {"producidos": 0, "procesados": 0, "max_ocupacion": 0}
    consumidor_t = asyncio.create_task(consumidor(q, stats))
    productor_t = asyncio.create_task(productor(q, stats))
    await productor_t
    await q.join()                   # todos los ítems procesados y marcados
    consumidor_t.cancel()            # el bucle infinito solo acaba con cancel()
    try:
        await consumidor_t
    except asyncio.CancelledError:
        pass                         # cancelación esperada y limpia

    print(f"producidos={stats['producidos']}")
    print(f"procesados={stats['procesados']}")
    print(f"max_ocupacion={stats['max_ocupacion']}")
    assert stats["producidos"] == TOTAL, "el productor no pudo producir todo"
    assert stats["procesados"] == TOTAL, "se perdieron eventos: contrapresión rota"
    assert stats["max_ocupacion"] == MAX_Q, "la cola nunca alcanzó el tope: no hubo contrapresión"

asyncio.run(main())
```

Verificación: producidos=procesados=50 (cero pérdidas) y ocupación máxima exactamente 5 (el tope se alcanzó y se respetó)."""),
        ],
        verify=[
            {"name": "contrapresion", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["producidos=50", "procesados=50", "max_ocupacion=5"],
             "timeout_s": 15},
        ],
        tags=["asyncio", "queue", "backpressure", "ingest"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 03
    E(
        language="python",
        domain="backend",
        subdomain="asyncio_concurrency_limit",
        difficulty="hard",
        task_type="optimization",
        messages=[
            ("user", r"""Nuestro reindexador lanza 50 tareas asíncronas contra una base de datos simulada y el DBA nos ha sancionado: las 50 conexiones «en vuelo» saturan el pool. Quiero que demuestres el problema y la solución medible: (1) mide el pico de concurrencia real de 50 tareas sin límite; (2) aplícale un Semaphore(5) y vuelve a medir; (3) deja evidencia impresa de que el pico baja de 50 a 5 SIN perder throughput (las 50 tareas siguen completándose). El trabajo simulado es un sleep de 20 ms."""),
            ("assistant", r"""Requisitos inferidos: medición del pico de concurrencia concurrentes-en-vuelo, no del número de tareas lanzadas. La medición correcta es registrar len(en_curso) justo después de ENTRAR en la zona crítica, dentro de un set compartido con add/discard en finally.

Dos decisiones que importan: (1) el contador se actualiza dentro de la coroutine antes del primer await visible — asyncio es single-threaded y cooperativo, así que el add y la lectura del pico son atómicos sin candados (en threading esto NO sería cierto); (2) el semáforo envuelve SOLO el trabajo contra la BD, no la construcción de resultados, para no sostener el slot durante el procesamiento puro. Trade-off: con semáforo el lote tarda ~10 veces más (50 tareas / 5 slots × 20 ms), pero cada tarea sigue completando: throughput conservado, presión acotada."""),
            ("tool", r"""$ python reindexador.py
sin_limite: n=50 pico=50
sem_5: n=50 pico=5"""),
            ("assistant", r"""Implementación con ambas mediciones en el mismo proceso, para que la comparación sea honesta:

```python
import asyncio

TOTAL = 50

async def trabajo(i: int, en_curso: set[int], stats: dict) -> int:
    en_curso.add(i)
    stats["pico"] = max(stats["pico"], len(en_curso))   # medición en el punto de máxima presión
    try:
        await asyncio.sleep(0.02)      # la «consulta» contra la BD simulada
        return i * 2
    finally:
        en_curso.discard(i)

async def lote(sem: asyncio.Semaphore | None) -> dict:
    en_curso: set[int] = set()
    stats = {"pico": 0, "n": 0}

    async def uno(i: int) -> int:
        if sem is None:
            return await trabajo(i, en_curso, stats)
        async with sem:                # el slot se libera ANTES del procesamiento posterior
            return await trabajo(i, en_curso, stats)

    resultados = await asyncio.gather(*(uno(i) for i in range(TOTAL)))
    stats["n"] = len(resultados)
    return stats

async def main() -> None:
    sin_limite = await lote(None)
    print(f"sin_limite: n={sin_limite['n']} pico={sin_limite['pico']}")
    con_limite = await lote(asyncio.Semaphore(5))
    print(f"sem_5: n={con_limite['n']} pico={con_limite['pico']}")
    assert sin_limite["pico"] == TOTAL, "sin límite deben solaparse las 50"
    assert con_limite["pico"] == 5, "el semáforo debe acotar el pico a 5"
    assert con_limite["n"] == TOTAL, "acotar no debe perder tareas"

asyncio.run(main())
```

Verificación: mismo número de resultados (n=50) en ambos regímenes, pero el pico de concurrencia cae de 50 a 5. Es la evidencia que pide el DBA: throughput intacto, presión acotada."""),
        ],
        verify=[
            {"name": "medicion_pico", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["sin_limite: n=50 pico=50", "sem_5: n=50 pico=5"],
             "timeout_s": 15},
        ],
        tags=["asyncio", "semaphore", "concurrency", "optimization"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 04
    E(
        language="python",
        domain="backend",
        subdomain="asyncio_cancellation",
        difficulty="extreme",
        task_type="debugging",
        messages=[
            ("user", r"""Tengo un worker que procesa una lista de fuentes con checkpoint incremental. Al apagar el servicio (SIGTERM -> task.cancel()) el worker «no se entera» y sigue trabajando: en producción hemos visto datos procesados DESPUÉS del apagado y checkpoints incoherentes. Este es mi worker actual, donde puse un «except BaseException: continue» para que nada lo detenga:

```python
import asyncio

class Trabajador:
    def __init__(self) -> None:
        self.procesados: list[int] = []
        self.checkpoint: int = -1

    def guardar_estado(self) -> None:
        pass  # en producción persiste el checkpoint a disco

    async def bucle(self, fuentes: list[int]) -> None:
        for i, fuente in enumerate(fuentes):
            try:
                await asyncio.sleep(0.02)      # simula la E/S por elemento
                self.procesados.append(fuente)
                self.checkpoint = i
            except BaseException:              # «por si acaso»: traga la cancelación
                self.guardar_estado()
                continue

async def main() -> None:
    t = Trabajador()
    tarea = asyncio.create_task(t.bucle(list(range(30))))
    await asyncio.sleep(0.12)                  # apagado ordenado a los 120 ms
    tarea.cancel()
    await asyncio.sleep(0.20)                  # tiempo para morir con dignidad
    n_antes = len(t.procesados)
    await asyncio.sleep(0.10)
    siguio = len(t.procesados) > n_antes or not tarea.done()
    print(f"procesados={len(t.procesados)}")
    print(f"trabajo_tras_cancel={'si' if siguio else 'no'}")
    if siguio:
        raise SystemExit(1)                    # el supervisor detecta el apagado sucio

asyncio.run(main())
```

Reproduce el bug, explica la causa raíz y corrige con el patrón de cancelación limpia (checkpoint + re-raise).""",
            ),
            ("assistant", r"""Síntoma verificado: tras cancel() el bucle sigue procesando elementos. Causa raíz: except BaseException atrapa asyncio.CancelledError (que es BaseException, NO Exception, desde Python 3.8) y el continue convierte la petición de cancelación en un «no» silencioso. La tarea queda zombie: sigue consumiendo CPU y datos después del apagado.

Requisitos del patrón correcto: (1) capturar SOLO asyncio.CancelledError en el punto de espera; (2) persistir el checkpoint (progreso coherente: checkpoint == índice del último elemento completado); (3) re-lanzar con raise — la cancelación es una petición, no un error; quien la recibe debe obedecerla y propagarla. Trade-off: cualquier otra excepción (Exception) se propaga sin tocar, para no enmascarar fallos reales del worker."""),
            ("tool", r"""$ python worker_roto.py
procesados=30
trabajo_tras_cancel=si
$ echo $?
1"""),
            ("assistant", r"""Fijate en la evidencia del run roto: 30 procesados (¡todos!, pese al cancel a los 120 ms) y trabajo_tras_cancel=si. Corrección con el patrón canónico checkpoint-then-reraise:

```python
import asyncio

class Trabajador:
    def __init__(self) -> None:
        self.procesados: list[int] = []
        self.checkpoint: int = -1

    def guardar_estado(self) -> None:
        pass  # en producción persiste el checkpoint a disco

    async def bucle(self, fuentes: list[int]) -> None:
        for i, fuente in enumerate(fuentes):
            try:
                await asyncio.sleep(0.02)
                self.procesados.append(fuente)
                self.checkpoint = i
            except asyncio.CancelledError:
                self.guardar_estado()   # persistir el progreso coherente
                raise                   # obedecer y propagar la cancelación

async def main() -> None:
    t = Trabajador()
    tarea = asyncio.create_task(t.bucle(list(range(30))))
    await asyncio.sleep(0.12)           # apagado ordenado a los 120 ms
    tarea.cancel()
    await asyncio.sleep(0.20)
    n_antes = len(t.procesados)
    await asyncio.sleep(0.10)
    siguio = len(t.procesados) > n_antes or not tarea.done()
    invariante = t.checkpoint == len(t.procesados) - 1
    print(f"procesados={len(t.procesados)}")
    print(f"trabajo_tras_cancel={'si' if siguio else 'no'}")
    print(f"invariante_checkpoint={'ok' if invariante else 'roto'}")
    if not siguio and invariante:
        print("apagado_limpio=True")

asyncio.run(main())
```

Verificación: el worker se detiene en el elemento en curso (el número exacto varía con el scheduling, pero es < 30 y determinista el INVARIANTE: checkpoint == len(procesados)-1), trabajo_tras_cancel=no y apagado_limpio=True. La regla para el equipo: en asyncio solo se silencia CancelledError para hacer trabajo síncrono mínimo (flush, checkpoint) y SIEMPRE con re-raise."""),
        ],
        verify=[
            {"name": "bug_apagado_sucio", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_fail": True, "timeout_s": 15},
            {"name": "apagado_limpio", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["trabajo_tras_cancel=no",
                                        "invariante_checkpoint=ok",
                                        "apagado_limpio=True"],
             "timeout_s": 15},
        ],
        tags=["asyncio", "cancellation", "graceful-shutdown", "cancellederror"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 05
    E(
        language="python",
        domain="backend",
        subdomain="asyncio_tcp_server",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Necesito un servicio interno de utilidades por TCP para el equipo de soporte: protocolo de líneas, comandos PING (responde PONG), SUM n1 n2 ... (responde OK <suma>, o ERR bad_args si algo no es entero) y QUIT (responde BYE y cierra). Restricción dura del entorno de pruebas: servidor y cliente en el MISMO proceso, el servidor arranca, SIRVE y se APAGA solo — el programa debe terminar siempre y sin hilos huérfanos. Puerto efímero, nunca uno fijo."""),
            ("assistant", r"""Requisitos inferidos: (a) puerto 0 -> el SO asigna uno efímero y lo leo de server.sockets[0].getsockname(); (b) un solo cliente de prueba que ejercita los tres comandos y el caso de error; (c) cierre ordenado en cadena: cliente cierra -> readline devuelve b"" -> handler cierra writer -> server.close() + await server.wait_closed() -> asyncio.run termina. (d) El readline del handler lleva wait_for(2.0) para que un cliente mudo no deje conexiones colgadas (el sandbox castigaría el proceso eterno).

Trade-offs: protocolo línea-a-línea con StreamReader.readline (delimita sin parsear a mano); errores de dominio se responden como ERR y no como excepciones — el protocolo NO es el lugar para stacktraces. Timeout por lectura, no por conexión: una sesión larga pero activa es legítima."""),
            ("tool", r"""$ python util_tcp.py
listening=127.0.0.1:43921
PONG
OK 42
ERR bad_args
BYE"""),
            ("assistant", r"""Implementación autocontenida (servidor + cliente + apagado):

```python
import asyncio

async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            linea = await asyncio.wait_for(reader.readline(), timeout=2.0)
            if not linea:                # el cliente cerró: EOF
                break
            cmd = linea.decode().strip()
            if cmd == "QUIT":
                writer.write(b"BYE\n")
                await writer.drain()
                break
            if cmd.startswith("SUM "):
                try:
                    total = sum(int(p) for p in cmd.split()[1:])
                    writer.write(f"OK {total}\n".encode())
                except ValueError:
                    writer.write(b"ERR bad_args\n")
            elif cmd == "PING":
                writer.write(b"PONG\n")
            else:
                writer.write(b"ERR unknown\n")
            await writer.drain()
    except asyncio.TimeoutError:
        pass                             # cliente mudo: se corta la sesión
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, asyncio.CancelledError):
            pass

async def main() -> None:
    server = await asyncio.start_server(handle, "127.0.0.1", 0)   # puerto efímero
    port = server.sockets[0].getsockname()[1]
    print(f"listening=127.0.0.1:{port}")

    async def cliente() -> list[str]:
        r, w = await asyncio.open_connection("127.0.0.1", port)
        respuestas: list[str] = []
        for cmd in (b"PING\n", b"SUM 2 40\n", b"SUM x\n", b"QUIT\n"):
            w.write(cmd)
            await w.drain()
            respuestas.append((await r.readline()).decode().strip())
        w.close()
        try:
            await w.wait_closed()
        except ConnectionError:
            pass
        return respuestas

    try:
        respuestas = await asyncio.wait_for(cliente(), timeout=5.0)
    finally:
        server.close()                   # el servidor SIEMPRE se apaga
        await server.wait_closed()
    for r in respuestas:
        print(r)

asyncio.run(main())
```

Verificación: los cuatro comandos producen PONG, OK 42, ERR bad_args y BYE; el proceso termina solo porque no queda ni el servidor abierto ni tareas pendientes."""),
        ],
        verify=[
            {"name": "servidor_tcp", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["PONG", "OK 42", "ERR bad_args", "BYE"],
             "timeout_s": 15},
        ],
        tags=["asyncio", "tcp", "stream", "server", "protocol"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 06
    E(
        language="python",
        domain="backend",
        subdomain="asyncio_blocking_trap",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Migré una utilidad a asyncio y su timeout «no funciona»: puse wait_for(..., timeout=0.1) alrededor de una función heredada deriva(valor) que internamente hace time.sleep(0.5) (simula una librería bloqueante que no puedo tocar), y el proceso sigue tardando 0,5 s en soltarse en vez de 0,1 s. Aquí está el reproductor:

```python
import asyncio
import time

async def derivar(valor: int) -> int:
    time.sleep(0.5)          # función heredada bloqueante, no puedo modificarla
    return valor * 2

async def main() -> None:
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(derivar(21), timeout=0.1)
    except asyncio.TimeoutError:
        pass
    dt = time.monotonic() - t0
    respetado = dt < 0.3
    print(f"timeout_respetado={'si' if respetado else 'no'}")
    print(f"latencia={dt:.2f}")

asyncio.run(main())
```

Explica por qué wait_for no puede cortar esto y da una corrección que respete el timeout de 0,1 s sin reescribir la función heredada."""),
            ("assistant", r"""Causa raíz: wait_for cancela la TAREA, pero una cancelación solo se entrega en un punto de espera (un await real). time.sleep(0.5) es una llamada bloqueante que congela el HILO del event loop: no hay loop ejecutándose durante esos 500 ms, así que el callback del timeout queda encolado y solo se despacha cuando el sleep por fin devuelve. Resultado: el «timeout» dispara a los 500 ms, no a los 100. Regla general: cualquier llamada síncrona bloqueante dentro de una coroutine rompe las garantías de latencia de TODO el loop, no solo de su tarea.

Requisitos de la corrección: no tocar la función heredada; mantener el timeout de 0,1 s; y ser honestos con el coste — moviendo el trabajo a un hilo del executor, el event loop recupera el control y la cancelación del lado asyncio es inmediata, aunque el hilo sigue calculando (la cancelación de un hilo es cooperativa: ese cómputo se desperdicia, no se interrumpe)."""),
            ("tool", r"""$ python timeout_roto.py
timeout_respetado=no
latencia=0.50"""),
            ("assistant", r"""Corrección: descargar la función bloqueante al executor con loop.run_in_executor. El await del futuro SÍ es un punto de cancelación, así que wait_for expira puntual:

```python
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="legacy")

def derivar_bloqueante(valor: int) -> int:
    time.sleep(0.5)          # función heredada, sin modificar
    return valor * 2

async def derivar(valor: int) -> int:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, derivar_bloqueante, valor)

async def main() -> None:
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(derivar(21), timeout=0.1)
    except asyncio.TimeoutError:
        pass
    dt = time.monotonic() - t0
    print(f"timeout_respetado={'si' if dt < 0.3 else 'no'}")
    print("cancelacion_hilo=cooperativa")   # el hilo sigue calculando: se desperdicia, no se interrumpe
    executor.shutdown(wait=False)

asyncio.run(main())
```

Verificación: timeout_respetado=si (expira ~0,1 s). La alternativa a largo plazo es reescribir deriva como coroutine real con awaits, donde la cancelación sí aborta el trabajo a medias; mientras tanto, executor + wait_for es el patrón correcto para envolver código bloqueante heredado."""),
        ],
        verify=[
            {"name": "bug_timeout_no_respetado", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_not_contains": ["timeout_respetado=si"],
             "timeout_s": 15},
            {"name": "fix_timeout_respetado", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["timeout_respetado=si"],
             "timeout_s": 15},
        ],
        tags=["asyncio", "wait_for", "blocking", "executor", "timeout"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 07
    E(
        language="python",
        domain="tooling",
        subdomain="subprocess_timeouts",
        difficulty="medium",
        task_type="implementation",
        messages=[
            ("user", r"""Para la CLI de nuestro producto necesito un helper ejecutar(codigo, timeout) que lance un intérprete hijo con subprocess.run: si el comando termina, devuelve (True, stdout); si excede el timeout, debe MATARLO y devolver (False, ""). Caso de prueba: un comando rápido que imprime «listo» y otro que duerme 30 s con timeout de 2 s. Sin hilos, sin librerías externas, y el programa completo debe terminar en < 5 s."""),
            ("assistant", r"""Requisitos inferidos: captura de stdout (capture_output=True, text=True) y garantía de que el hijo colgado no sobrevive a la llamada. subprocess.run(timeout=...) ya integra el kill: al expirar lanza TimeoutExpired y mata al hijo antes de propagar; no hay que hacer kill() a mano (sería doble gestión). Trade-offs: run() con timeout no ofrece salida parcial (si te interesara lo impreso antes del colgado, sería Popen + communicate(timeout) leyendo lo que haya en la excepción); para un gate de CI, abortar sin salida parcial es lo correcto y más simple."""),
            ("tool", r"""$ python gate_subprocess.py
rapido_ok=True out=listo
colgado_terminado=si"""),
            ("assistant", r"""Implementación con ambos casos y autoverificación:

```python
import subprocess
import sys

COLGADO = "import time; time.sleep(30)"
RAPIDO = "print('listo')"

def ejecutar(codigo: str, timeout: float) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            [sys.executable, "-c", codigo],
            capture_output=True, text=True, timeout=timeout,
        )
        return True, p.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, ""     # run() ya mató al hijo al expirar

def main() -> None:
    ok, out = ejecutar(RAPIDO, 5)
    print(f"rapido_ok={ok} out={out}")
    vivo, _ = ejecutar(COLGADO, 2)
    print(f"colgado_terminado={'si' if not vivo else 'no'}")
    assert ok and out == "listo", "el comando rápido debe completarse"
    assert not vivo, "el comando colgado debe ser terminado por el timeout"

main()
```

Verificación: rapido_ok=True out=listo y colgado_terminado=si; el proceso completo tarda ~2 s (el colgado muere en el segundo 2, no en el 30)."""),
        ],
        verify=[
            {"name": "gate_subprocess", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["rapido_ok=True out=listo", "colgado_terminado=si"],
             "timeout_s": 15},
        ],
        tags=["subprocess", "timeout", "cli", "process-management"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 09
    E(
        language="python",
        domain="systems",
        subdomain="process_pipeline",
        difficulty="hard",
        task_type="refactoring",
        messages=[
            ("user", r"""Heredé un informe de ventas que procesa CSV con un one-liner de shell incrustado en Python: grep para quitar comentarios, cut para el campo importe y una suma en Python. Los datos reales tienen campos entre comillas con comas («Doe, Jane») y el informe suma MAL: las filas con comillas se descartan en silencio. Además el fichero nuevo se llama ventas;final.csv y temo que el shell haga cosas raras. Dame la versión refactorizada: sin shell=True, encadenando procesos con Popen cuando el pipeline Unix aporte, y usando el módulo csv donde el shell no llega. Fixtures: ventas.csv y ventas;final.csv."""),
            ("assistant", r"""Diagnóstico: cut no entiende CSV — parte por TODAS las comas, incluidas las de dentro de comillas — y el except ValueError: pass del heredado convierte ese error de parseo en PÉRDIDA DE DATOS silenciosa. Además shell=True con interpolación de nombres de fichero es un agujero de inyección (un nombre con comilla simple rompe el quoting).

Plan de refactor: (1) la única etapa que Unix hace mejor que Python aquí es el prefiltrado de comentarios -> subprocess.Popen(["grep", "-v", "^#"]) sin shell, stdin conectado al fichero y stdout=PIPE; (2) el parseo CSV pasa al módulo csv, que respeta el dialecto con comillas; (3) códigos de retorno verificados explícitamente (grep devuelve 1 cuando no hay líneas, que aquí no es error; lo demás sí lo es). Trade-off: mantenemos el proceso grep para no reescribir un prefiltrado que ya funciona, pero el contenido estructurado se parsea en Python: cada dato en la herramienta que lo respeta."""),
            ("tool", r"""$ python informe_roto.py
ventas.csv: suma_importes=200
ventas;final.csv: suma_importes=60
# suma real: 700 y 300 — dos filas entre comillas perdidas por fichero"""),
            ("assistant", r"""Versión refactorizada (los números demuestran la recuperación: 700 y 300 frente a 200 y 60 del heredado):

```python
import csv
import subprocess
from pathlib import Path

def suma_importes_validos(ruta: Path) -> tuple[int, int]:
    fh = ruta.open("r", encoding="utf-8")
    try:
        # etapa Unix: prefiltrado de comentarios, SIN shell (sin inyección posible)
        proceso = subprocess.Popen(
            ["grep", "-v", "^#"], stdin=fh, stdout=subprocess.PIPE, text=True,
        )
    finally:
        fh.close()               # el hijo conserva su duplicado del descriptor
    try:
        filas = 0
        total = 0
        lector = csv.reader(proceso.stdout)     # csv SÍ respeta comillas y comas embebidas
        cabecera = next(lector)
        col = cabecera.index("importe")
        for fila in lector:
            total += int(fila[col])
            filas += 1
    finally:
        proceso.stdout.close()
        # grep devuelve 1 si no sale ninguna línea: no es error en este pipeline
        if proceso.wait() not in (0, 1):
            raise RuntimeError(f"etapa grep falló con código {proceso.returncode}")
    return filas, total

def main() -> None:
    for nombre in ("ventas.csv", "ventas;final.csv"):
        filas, total = suma_importes_validos(Path(nombre))
        print(f"{nombre}: filas={filas} suma_importes={total}")
    assert suma_importes_validos(Path("ventas.csv")) == (4, 700)
    assert suma_importes_validos(Path("ventas;final.csv")) == (3, 300)
    print("sin_perdida_silenciosa=True")

main()
```

Verificación: filas=4 suma_importes=700 y filas=3 suma_importes=300 — cada fila contada y sumada; el assert bloquea cualquier regresión que vuelva a descartar filas en silencio. Lecciones del refactor: lista de args en Popen (no shell), códigos de retorno como contrato, y parseo estructurado con csv en cuanto hay comillas."""),
        ],
        verify=[
            {"name": "informe_refactorizado", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "fixtures": [
                 {"name": "ventas.csv",
                  "content": "# export v2\nfecha,cliente,importe\n2024-01-05,\"Doe, Jane\",200\n2024-01-06,John Smith,150\n# generado por el ETL legacy\n2024-01-07,\"Ñuñoa, Ltda.\",300\n2024-01-08,ACME,50\n"},
                 {"name": "ventas;final.csv",
                  "content": "# export v2;region=norte\nfecha,cliente,importe\n2024-02-01,\"López, Ana\",90\n2024-02-02,Taller Ruiz,60\n2024-02-03,\"Cía. de Suministros, S.L.\",150\n"},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["ventas.csv: filas=4 suma_importes=700",
                                        "ventas;final.csv: filas=3 suma_importes=300",
                                        "sin_perdida_silenciosa=True"],
             "timeout_s": 15},
        ],
        tags=["subprocess", "popen", "pipeline", "csv", "refactoring"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 10
    E(
        language="python",
        domain="backend",
        subdomain="http_server_stdlib",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Para el smoke-test del despliegue necesito un patrón autocontenible con SOLO stdlib: un servidor HTTP (http.server) que arranque en hilo daemon sobre un puerto EFÍMERO, exponga GET /saludo?nombre=X -> 200 {"hola": X}, POST /eco -> 201 {"recibido": <cuerpo>}, y 404 para lo demás; un cliente urllib que ejerza los tres casos; y apagado ordenado (shutdown + server_close + join). El proceso entero debe terminar solo, sin hilos colgados, y las aserciones de status deben quedar impresas."""),
            ("assistant", r"""Requisitos inferidos: (a) ThreadingHTTPServer + puerto 0, leyendo el puerto real de server_address[1] — fijar puerto es receta para colisiones en CI; (b) hilo daemon con serve_forever y apagado EXPLÍCITO en finally: shutdown() despierta el bucle del servidor, server_close() libera el socket y join(timeout) garantiza que el hilo muere antes de imprimir el resultado; (c) Content-Length explícito en cada respuesta (http.client moderno lo exige para leer el cuerpo fiablemente); (d) HTTPError para el 404 se captura como dato, no como crash. Trade-off: para pruebas de producto reales conviene además log_message silenciado — el log por petición de http.server ensucia la salida del smoke test."""),
            ("tool", r"""$ python smoke_http.py
get_status=200 get={'hola': 'ada'}
post_status=201 eco={'x': 1, 'y': [2, 3]}
status_404=404
apagado_ordenado=True"""),
            ("assistant", r"""Implementación completa del patrón «arranca, sirve, se apaga»:

```python
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Api(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:   # smoke test limpio: sin log por petición
        pass

    def _json(self, codigo: int, cuerpo: dict) -> None:
        data = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.startswith("/saludo"):
            nombre = self.path.split("nombre=")[-1] or "mundo"
            self._json(200, {"hola": nombre})
        else:
            self._json(404, {"error": "no encontrado"})

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/eco":
            self._json(201, {"recibido": cuerpo})
        else:
            self._json(404, {"error": "no encontrado"})

def main() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Api)     # puerto efímero
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    port = srv.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/saludo?nombre=ada", timeout=5) as r:
            get_status, get_body = r.status, json.loads(r.read())
        peticion = urllib.request.Request(
            f"http://127.0.0.1:{port}/eco",
            data=json.dumps({"x": 1, "y": [2, 3]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(peticion, timeout=5) as r:
            post_status, post_body = r.status, json.loads(r.read())
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nada", timeout=5)
            status_404 = 200
        except urllib.error.HTTPError as e:
            status_404 = e.code
    finally:
        srv.shutdown()               # despierta y detiene serve_forever
        srv.server_close()           # libera el socket de escucha
        hilo.join(timeout=5)         # el hilo muere antes de seguir
    print(f"get_status={get_status} get={get_body}")
    print(f"post_status={post_status} eco={post_body['recibido']}")
    print(f"status_404={status_404}")
    print(f"apagado_ordenado={not hilo.is_alive()}")
    assert get_status == 200 and post_status == 201 and status_404 == 404

main()
```

Verificación: los tres status correctos, hilo terminado (apagado_ordenado=True) y proceso que finaliza solo. Este es el esqueleto que usamos en todos los smoke tests del producto."""),
        ],
        verify=[
            {"name": "smoke_http", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["get_status=200", "post_status=201",
                                        "status_404=404", "apagado_ordenado=True"],
             "timeout_s": 15},
        ],
        tags=["http-server", "urllib", "stdlib", "smoke-test", "threading"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 11
    E(
        language="python",
        domain="backend",
        subdomain="http_server_testing",
        difficulty="hard",
        task_type="testing",
        messages=[
            ("user", r"""Quiero los tests de integración del mini-API del smoke test, en un único fichero ejecutable con unittest: servidor ThreadingHTTPServer que se levanta UNA vez para toda la suite (setUpClass/tearDownClass), puerto efímero, y cuatro casos: GET /suma?a=2&b=40 -> 200/42, GET /suma?a=x&b=1 -> 400, GET /estado -> 200/ok=True, ruta desconocida -> 404. Que la suite termine en OK y el servidor quede cerrado después."""),
            ("assistant", r"""Decisiones: el servidor vive en setUpClass (una instancia por suite, no por test: arranque caro, suite rápida) con tearDownClass que hace shutdown + server_close + join — así el proceso no se cuelga ni deja sockets abiertos; cada test habla con el servidor REAL por urllib (integración de verdad, no mock); el 400 se elige como caso de error de dominio para verificar que el handler distingue error de cliente de error de ruta. Los errores HTTP se convierten a (codigo, cuerpo) en un helper para que los tests aserten sobre datos y no sobre control de excepciones."""),
            ("tool", r"""$ python test_api_integracion.py
test_estado ... ok
test_parametros_invalidos ... ok
test_ruta_desconocida ... ok
test_suma ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.003s

OK"""),
            ("assistant", r"""Suite completa en un solo bloque ejecutable:

```python
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Api(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _json(self, codigo: int, cuerpo: dict) -> None:
        data = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.startswith("/suma"):
            try:
                params = dict(p.split("=") for p in self.path.split("?", 1)[-1].split("&"))
                self._json(200, {"resultado": int(params["a"]) + int(params["b"])})
            except (KeyError, ValueError):
                self._json(400, {"error": "parametros invalidos"})
        elif self.path == "/estado":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "no encontrado"})

class TestApiIntegracion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Api)
        cls.hilo = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.hilo.start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.hilo.join(timeout=5)

    def _get(self, ruta: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.base + ruta, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_suma(self) -> None:
        codigo, cuerpo = self._get("/suma?a=2&b=40")
        self.assertEqual(codigo, 200)
        self.assertEqual(cuerpo["resultado"], 42)

    def test_parametros_invalidos(self) -> None:
        codigo, cuerpo = self._get("/suma?a=x&b=1")
        self.assertEqual(codigo, 400)
        self.assertIn("error", cuerpo)

    def test_estado(self) -> None:
        codigo, cuerpo = self._get("/estado")
        self.assertEqual((codigo, cuerpo["ok"]), (200, True))

    def test_ruta_desconocida(self) -> None:
        codigo, _ = self._get("/nada")
        self.assertEqual(codigo, 404)

if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Verificación: Ran 4 tests con OK; tearDownClass garantiza que el servidor se apaga aunque un test falle."""),
        ],
        verify=[
            {"name": "suite_integracion", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["Ran 4 tests", "OK"],
             "timeout_s": 20},
        ],
        tags=["unittest", "http-server", "integration-testing", "setupclass"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 12
    E(
        language="python",
        domain="data",
        subdomain="jsonl_quarantine",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""El ETL del CRM me deja un JSONL que viene sucio: líneas que no son JSON, JSON válido que no es objeto (arrays), objetos sin claves obligatorias (id/tipo) y compras con importe no numérico. Necesito un procesador de cuarentena en dos capas: capa sintáctica (json.loads) y capa de esquema (tipo + tipos de campo), que escriba los válidos a validos.jsonl y los rechazados a cuarentena.jsonl con {linea, motivo, crudo} — con el número de línea original para poder reclamar datos. Al final: conteos validas/cuarentena. Fixture: eventos.jsonl (9 líneas, 5 válidas, 4 a cuarentena)."""),
            ("assistant", r"""Requisitos inferidos: dos motivos distinguishables (json_invalido:<detalle> para la capa sintáctica; no_es_objeto / campos_obligatorios / importe_invalido para la de esquema) y procesamiento streaming línea a línea (un JSONL real es grande; nada de leerlo entero). Dos decisiones finas: (1) isinstance(True, int) es True en Python — el importe booleano pasaría un chequeo isinstance(x, (int, float)) ingenuo, así que excluyo bool explícitamente; (2) las líneas vacías se omiten sin cuarentena (ruido de exportador, no dato corrompido). Trade-off: la cuarentena guarda el crudo completo — es lo que permite reprocesar; si el crudo fuera sensible, ahí habría que aplicar máscaras antes."""),
            ("tool", r"""$ python cuarentena.py
validas=5
cuarentena=4
$ head -3 cuarentena.jsonl
{"linea": 3, "motivo": "json_invalido:Expecting value", "crudo": "no es json"}
{"linea": 6, "motivo": "no_es_objeto", "crudo": "[]"}
{"linea": 7, "motivo": "importe_invalido", "crudo": "{\"id\": 4, \"tipo\": \"compra\"}"}"""),
            ("assistant", r"""Procesador completo con validación en dos capas:

```python
import json
from pathlib import Path

ENTRADA = Path("eventos.jsonl")
SALIDA = Path("validos.jsonl")
CUARENTENA = Path("cuarentena.jsonl")

def validar(linea: str) -> tuple[dict | None, str | None]:
    # capa 1: sintaxis
    try:
        obj = json.loads(linea)
    except json.JSONDecodeError as e:
        return None, f"json_invalido:{e.msg}"
    # capa 2: esquema
    if not isinstance(obj, dict):
        return None, "no_es_objeto"
    if "id" not in obj or "tipo" not in obj:
        return None, "campos_obligatorios"
    if obj.get("tipo") == "compra":
        importe = obj.get("importe")
        if not isinstance(importe, (int, float)) or isinstance(importe, bool):
            return None, "importe_invalido"
    return obj, None

def procesar() -> tuple[int, int]:
    validas = cuarentena = 0
    with (ENTRADA.open(encoding="utf-8") as fin,
          SALIDA.open("w", encoding="utf-8") as fok,
          CUARENTENA.open("w", encoding="utf-8") as fq):
        for nlinea, cruda in enumerate(fin, 1):
            linea = cruda.strip()
            if not linea:
                continue
            registro, motivo = validar(linea)
            if registro is None:
                cuarentena += 1
                fq.write(json.dumps({"linea": nlinea, "motivo": motivo,
                                     "crudo": linea}, ensure_ascii=False) + "\n")
            else:
                validas += 1
                fok.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return validas, cuarentena

v, c = procesar()
print(f"validas={v}")
print(f"cuarentena={c}")
assert (v, c) == (5, 4), "los conteos deben coincidir con el análisis del fixture"
```

Verificación con el fixture de 9 líneas: validas=5, cuarentena=4 (1 no-JSON, 1 array, 1 compra sin importe numérico, 1 importe string), y cuarentena.jsonl conserva línea original + motivo + crudo para reproceso."""),
        ],
        verify=[
            {"name": "cuarentena_jsonl", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "fixtures": [
                 {"name": "eventos.jsonl",
                  "content": "{\"id\": 1, \"tipo\": \"login\", \"ok\": true}\n"
                             "{\"id\": 2, \"tipo\": \"compra\", \"importe\": 10.5}\n"
                             "no es json\n"
                             "{\"id\": 3, \"tipo\": \"login\", \"ok\": false}\n"
                             "{\"id\": 3, \"tipo\": \"login\", \"ok\": true}\n"
                             "[]\n"
                             "{\"id\": 4, \"tipo\": \"compra\"}\n"
                             "{\"id\": 5, \"tipo\": \"logout\"}\n"
                             "{\"id\": 6, \"tipo\": \"compra\", \"importe\": \"7\"}\n"},
             ],
             "expect_stdout_contains": ["validas=5", "cuarentena=4"],
             "timeout_s": 15},
        ],
        tags=["jsonl", "quarantine", "data-quality", "etl", "validation"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 13
    E(
        language="python",
        domain="data",
        subdomain="log_regex_parsing",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Necesito analizar los logs del backend con un formato propio: FECHA_ISO NIVEL MODULO MENSAJE... latency_ms=N. Quiero un parser con regex de named groups (ts, nivel, modulo, mensaje, latencia), que cuente: líneas parseadas vs no parseadas (el log tiene líneas corruptas que NO deben tumbar el análisis), distribución por nivel y latencia máxima por módulo. Solo re, collections y pathlib. Fixture: app.log (10 líneas, 1 corrupta)."""),
            ("assistant", r"""Decisiones: (1) el patrón es deliberadamente ESTRICTO (anclado con ^...$, niveles en enumeración exacta, latency_ms=\d+ al final): las líneas corruptas NO matchean y caen al contador no_parseadas — un regex laxo «parsearía» basura con campos vacíos; (2) named groups en lugar de grupos numerados: el agregador lee por nombre y sobrevive a reordenar el patrón; (3) mensaje con .*? perezoso anclado a \s+latency_ms= para que el propio mensaje pueda contener espacios y claves clave=valor sin tragarse la latencia. Trade-off: niveles como alternación fija (INFO|WARN|ERROR|DEBUG|TRACE) — si el log crece con un nivel nuevo, aparece en no_parseadas y el monitor lo avisará, que es exactamente el comportamiento que queremos."""),
            ("tool", r"""$ python analiza_log.py
parseadas=9 no_parseadas=1
niveles=DEBUG:1,ERROR:2,INFO:4,TRACE:1,WARN:1
lat_max=api:812,auth:12,db:2001"""),
            ("assistant", r"""Parser y agregador:

```python
import re
from collections import Counter
from pathlib import Path

PATRON = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+"
    r"(?P<nivel>INFO|WARN|ERROR|DEBUG|TRACE)\s+"
    r"(?P<modulo>\S+)\s+"
    r"(?P<mensaje>.*?)\s+latency_ms=(?P<latencia>\d+)$"
)

def analizar(ruta: Path) -> tuple[int, int, Counter, dict[str, int]]:
    parseadas = no_parseadas = 0
    niveles: Counter = Counter()
    lat_max: dict[str, int] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        m = PATRON.match(linea)
        if m is None:
            no_parseadas += 1          # corrupta: se cuenta, no se tumba el análisis
            continue
        parseadas += 1
        niveles[m["nivel"]] += 1
        lat = int(m["latencia"])
        mod = m["modulo"]
        lat_max[mod] = max(lat_max.get(mod, 0), lat)
    return parseadas, no_parseadas, niveles, lat_max

def main() -> None:
    p, np_, niveles, lat_max = analizar(Path("app.log"))
    print(f"parseadas={p} no_parseadas={np_}")
    print("niveles=" + ",".join(f"{k}:{v}" for k, v in sorted(niveles.items())))
    print("lat_max=" + ",".join(f"{k}:{v}" for k, v in sorted(lat_max.items())))
    assert (p, np_) == (9, 1)
    assert lat_max["db"] == 2001 and lat_max["api"] == 812

main()
```

Verificación: 9/10 líneas parseadas, la corrupta contada pero sin romper nada; distribución por nivel y picos de latencia por módulo correctos (db:2001 marca la consulta con timeout, api:812 el endpoint lento)."""),
        ],
        verify=[
            {"name": "analisis_logs", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "fixtures": [
                 {"name": "app.log",
                  "content": "2024-03-01T08:00:12Z INFO  auth     login user=ada latency_ms=12\n"
                             "2024-03-01T08:00:15Z WARN  api      slow endpoint=/v1/users latency_ms=812\n"
                             "2024-03-01T08:00:16Z ERROR db       timeout query=SELECT latency_ms=2001\n"
                             "2024-03-01T08:00:20Z INFO  auth     login user=grace latency_ms=9\n"
                             "linea corrupta sin formato\n"
                             "2024-03-01T08:00:22Z DEBUG auth     token refresh user=ada latency_ms=3\n"
                             "2024-03-01T08:00:30Z INFO  api      GET endpoint=/v1/users latency_ms=95\n"
                             "2024-03-01T08:00:31Z TRACE api      ping latency_ms=1\n"
                             "2024-03-01T08:00:33Z ERROR api      boom endpoint=/v1/orders latency_ms=44\n"
                             "2024-03-01T08:00:40Z INFO  db       checkpoint latency_ms=45\n"},
             ],
             "expect_stdout_contains": ["parseadas=9 no_parseadas=1",
                                        "niveles=DEBUG:1,ERROR:2,INFO:4,TRACE:1,WARN:1",
                                        "lat_max=api:812,auth:12,db:2001"],
             "timeout_s": 15},
        ],
        tags=["regex", "named-groups", "logs", "parsing", "observability"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 14
    E(
        language="python",
        domain="data",
        subdomain="csv_dialects",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Un proveedor me manda ventas_semicolon.csv con delimitador «;» y campos entre comillas que contienen «;» y «,». Mi loader usa csv.reader con el dialecto por defecto (coma) y explota al tomar el campo importe. Arregla el loader detectando el dialecto con csv.Sniffer, demuestra por qué fallaba el parseo por defecto y verifica: filas de datos=3, total importes=1575. Fixture: ventas_semicolon.csv. Este es el loader roto:

```python
import csv

with open("ventas_semicolon.csv", newline="", encoding="utf-8") as fh:
    filas = list(csv.reader(fh))
try:
    total = sum(int(f[2]) for f in filas[1:])
    print(f"total={total}")
except (IndexError, ValueError) as e:
    print(f"parse_roto={type(e).__name__}")
    raise SystemExit(2)
```
""",
            ),
            ("assistant", r"""Causa raíz: csv.reader(…) por defecto asume delimiter=','. Con un CSV de «;», CADA línea entera es un único campo; f[2] lanza IndexError en cuanto se sale de la fila. No es un CSV corrupto: es un dialecto que el lector desconoce. La corrección robusta cuando el dialecto llega «de fuera» es snifarlo de una muestra: csv.Sniffer().sniff(muestra, delimiters=",;\t|") infiere delimitador y quotechar de la estructura de las primeras líneas (acota el conjunto de delimitadores candidatos para que el sniffing no confunda). Trade-off: Sniffer necesita una muestra representativa (con al menos una fila de datos con separadores); si el proveedor manda un dialecto exótico nuevo, el error pasa a ser claro y temprano, no un importe sumado mal."""),
            ("tool", r"""$ python loader_roto.py
parse_roto=IndexError
$ echo $?
2"""),
            ("assistant", r"""Loader corregido con sniffing y verificación de invariantes:

```python
import csv

RUTA = "ventas_semicolon.csv"

def cargar(ruta: str) -> tuple[int, int]:
    with open(ruta, newline="", encoding="utf-8") as fh:
        muestra = fh.read(4096)
        fh.seek(0)
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
        filas = list(csv.reader(fh, dialecto))
    cabecera, datos = filas[0], filas[1:]
    assert cabecera == ["id", "cliente", "importe"], "cabecera inesperada: dialecto mal detectado"
    total = sum(int(f[2]) for f in datos)
    return len(datos), total

def main() -> None:
    filas, total = cargar(RUTA)
    print(f"delimiter=;")
    print(f"filas={filas}")
    print(f"total={total}")
    assert (filas, total) == (3, 1575), "el dialecto detectado debe reconstruir los 3 importes"

main()
```

Verificación: filas=3 y total=1575 (1200 + 300 + 75), con el campo «Ferretería ""El Tornillo""» reconstruido correctamente gracias al quotechar detectado. Regla para el equipo: entrada de terceros -> sniffea el dialecto y valida la cabecera antes de confiar en columnas por posición."""),
        ],
        verify=[
            {"name": "bug_dialecto", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 2,
             "fixtures": [
                 {"name": "ventas_semicolon.csv",
                  "content": "id;cliente;importe\n"
                             "1;\"Pérez, S.L.\";1200\n"
                             "2;ACME;300\n"
                             "3;\"Ferretería \"\"El Tornillo\"\"\";75\n"},
             ],
             "expect_stdout_contains": ["parse_roto=IndexError"],
             "timeout_s": 15},
            {"name": "fix_sniffer", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "fixtures": [
                 {"name": "ventas_semicolon.csv",
                  "content": "id;cliente;importe\n"
                             "1;\"Pérez, S.L.\";1200\n"
                             "2;ACME;300\n"
                             "3;\"Ferretería \"\"El Tornillo\"\"\";75\n"},
             ],
             "expect_stdout_contains": ["filas=3", "total=1575"],
             "timeout_s": 15},
        ],
        tags=["csv", "sniffer", "dialect", "debugging", "data-ingestion"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 15
    E(
        language="python",
        domain="data",
        subdomain="event_streaming_analysis",
        difficulty="hard",
        task_type="analysis",
        messages=[
            ("user", r"""Tengo un log de eventos de 20 000 líneas (formato «id tipo usuario») que crece cada día, y el script actual lo carga con readlines() antes de contar: la RAM se dispara. Analiza el patrón de uso: distribución de eventos por tipo y top-3 de usuarios más activos, PERO con una pipeline de generadores (leer perezoso -> filtrar -> contar) que nunca materialice el fichero completo en memoria. Genera el fichero determinista con random.seed(42) y 20 000 eventos sobre 5 tipos y 50 usuarios."""),
            ("assistant", r"""Requisitos inferidos: (a) la memoria debe ser proporcional al NÚMERO DE CLAVES (5 tipos, 50 usuarios), no al número de líneas — eso es lo que la pipeline de generadores compra; (b) determinismo total para poder verificar: random.seed(42) en la generación y Counter con conteo por acumulación (most_common desempata por orden de inserción: con el mismo fichero, el top-3 es estable). Decisiones: el fichero se genera UNA vez y se procesa streaming con un generador que parsea cada línea al vuelo; el agregado es un solo pase O(n) con dos Counters. Trade-off: un solo pase impide métricas que requieran ver el flujo dos veces (p. ej. percentiles exactos por usuario); si hicieran falta, segunda pasada sobre el fichero, nunca acumulación en RAM."""),
            ("tool", r"""$ python analiza_eventos.py
eventos=20000
tipos=compra:4002,login:3981,logout:4035,ping:3972,query:4010
top_usuarios=u013:429,u041:424,u009:423"""),
            ("assistant", r"""Pipeline de generadores completa (los números exactos del top salen de la semilla, lo verificable es la estructura y el total):

```python
import random
from collections import Counter

RUTA = "eventos_grandes.log"
TIPOS = ["login", "compra", "logout", "query", "ping"]

def generar(ruta: str, n: int) -> None:
    rng = random.Random(42)
    with open(ruta, "w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(f"{i} {rng.choice(TIPOS)} u{rng.randrange(50):03d}\n")

def leer(ruta: str):                      # generador: nunca carga el fichero
    with open(ruta, encoding="utf-8") as fh:
        for linea in fh:
            partes = linea.split()
            if len(partes) == 3:
                yield partes[1], partes[2]   # (tipo, usuario)

def agregar(pares) -> tuple[Counter, Counter]:
    por_tipo: Counter = Counter()
    por_usuario: Counter = Counter()
    for tipo, usuario in pares:          # un solo pase O(n), memoria O(claves)
        por_tipo[tipo] += 1
        por_usuario[usuario] += 1
    return por_tipo, por_usuario

def main() -> None:
    generar(RUTA, 20_000)
    por_tipo, por_usuario = agregar(leer(RUTA))
    print(f"eventos={sum(por_tipo.values())}")
    print("tipos=" + ",".join(f"{t}:{c}" for t, c in sorted(por_tipo.items())))
    print("top_usuarios=" + ",".join(f"{u}:{c}" for u, c in por_usuario.most_common(3)))
    assert sum(por_tipo.values()) == 20_000
    assert len(por_tipo) == 5 and len(por_usuario) <= 50

main()
```

Verificación: eventos=20000 sin materializar la lista de líneas — el generador `leer` mantiene el bucle en streaming y los Counter solo guardan 55 claves. La misma pipeline escala a ficheros de gigas cambiando solo la fuente."""),
        ],
        verify=[
            {"name": "analisis_streaming", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["eventos=20000", "tipos=compra:"],
             "timeout_s": 20},
        ],
        tags=["generators", "streaming", "counter", "analysis", "memory"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 16
    E(
        language="python",
        domain="backend",
        subdomain="typing_boundaries",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Nuestro servicio arranca con una configuración JSON y crashea en producción con KeyError reintentos en lo profundo del arranque, muy lejos del load. Sospecho de un cast(Config, json.loads(...)) que «lava» el dict sin validar nada. Reproduce el crash, explica por qué el cast es una mentira al type checker y da la corrección: validación en la FRONTERA que devuelva un Config de verdad, con defaults para claves opcionales y rechazo con ValueError de tipos incorrectos. Este es el código culpable:

```python
import json
from typing import TypedDict, cast

class Config(TypedDict):
    host: str
    puerto: int
    reintentos: int

def arrancar(cfg: Config) -> str:
    return f"conectando a {cfg['host']}:{cfg['puerto']} reintentos={cfg['reintentos']}"

CRUDO = '{"host": "db.interno", "puerto": 5432}'   # falta «reintentos»

def principal() -> None:
    cfg = cast(Config, json.loads(CRUDO))   # el cast NO valida: miente al type checker
    print(arrancar(cfg))

principal()
```
""",
            ),
            ("assistant", r"""Causa raíz: cast() es una aserción HACIA el type checker, no una operación en runtime — no comprueba NADA. dict.get('reintentos') estaba ausente y el KeyError estalló tres capas más abajo, en el peor lugar posible (durante el arranque, con traceback sin contexto del fichero de config). Principio: los datos EXTERNOS (JSON, env, HTTP) son unknown hasta que una frontera los valida; después de la frontera, los tipos son verdad.

Requisitos de la corrección: (1) validar_config(crudo, defaults) fusiona defaults con lo crudo, verifica claves obligatorias y TIPOS (con el matiz isinstance(x, bool) excluido cuando esperamos int, porque True es int para isinstance); (2) errores como ValueError con mensaje accionable EN la frontera; (3) solo tras validar, cast(Config, ...) que ya es honesto."""),
            ("tool", r"""$ python config_rota.py
Traceback (most recent call last):
  ...
KeyError: 'reintentos'
$ echo $?
1"""),
            ("assistant", r"""Corrección con la frontera validadora:

```python
import json
from typing import TypedDict, cast

class Config(TypedDict):
    host: str
    puerto: int
    reintentos: int

OBLIGATORIAS = ("host", "puerto", "reintentos")

def validar_config(crudo: str, defaults: dict | None = None) -> Config:
    datos = json.loads(crudo)
    if not isinstance(datos, dict):
        raise ValueError("la configuración debe ser un objeto JSON")
    completos = {**(defaults or {}), **datos}
    faltan = [k for k in OBLIGATORIAS if k not in completos]
    if faltan:
        raise ValueError(f"faltan claves obligatorias: {faltan}")
    if not isinstance(completos["host"], str) or not completos["host"]:
        raise ValueError("host debe ser cadena no vacía")
    p = completos["puerto"]
    if not isinstance(p, int) or isinstance(p, bool) or not (1 <= p <= 65535):
        raise ValueError("puerto inválido (entero 1-65535)")
    r = completos["reintentos"]
    if not isinstance(r, int) or isinstance(r, bool) or r < 0:
        raise ValueError("reintentos inválido (entero >= 0)")
    return cast(Config, completos)      # cast HONESTO: la forma acaba de validarse

def arrancar(cfg: Config) -> str:
    return f"conectando a {cfg['host']}:{cfg['puerto']} reintentos={cfg['reintentos']}"

def main() -> None:
    cfg = validar_config('{"host": "db.interno", "puerto": 5432}',
                         defaults={"reintentos": 3})
    print(arrancar(cfg))
    try:
        validar_config('{"host": "db.interno", "puerto": "5432", "reintentos": 3}')
    except ValueError:
        print("config_mala_rechazada=True")

main()
```

Verificación: el arranque imprime conectando a db.interno:5432 reintentos=3 (el default llenó el hueco) y una config con puerto «5432» como string muere en la frontera con ValueError, no tres capas más abajo. Regla: TypedDict describe la forma, la frontera la garantiza, el cast después de validar es documentación, no mentira."""),
        ],
        verify=[
            {"name": "bug_keyerror_frontera", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_fail": True, "timeout_s": 15},
            {"name": "fix_validacion_frontera", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["conectando a db.interno:5432 reintentos=3",
                                        "config_mala_rechazada=True"],
             "timeout_s": 15},
        ],
        tags=["typeddict", "cast", "boundary-validation", "configuration"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 18
]
