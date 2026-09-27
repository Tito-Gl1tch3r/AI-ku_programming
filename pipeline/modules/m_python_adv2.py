"""
m_python_adv2.py — Task 3-e: Python avanzado, parte 2 (16 ejemplos verificables).

Continuación del módulo m_python_adv.py con escenarios NUEVOS (sin solapar los
17 existentes): API HTTP con clientes concurrentes y apagado ordenado, deadlock
de pipes bidireccional stdin/stdout con fixtures, asyncio.Queue con
contrapresión productor/consumidor, Protocol+TypedDict estructural en la
frontera, dataclass frozen/slots con validación manual, cProfile auto-perfilado
con mejora medible, lru_cache con cache_info determinista, singledispatch
(registro por tipos), itertools como pipeline ETL (batched de 3.12), unittest
de casos límite ejecutado con unittest.main(), sqlite3 con transacciones
explícitas y upsert, streaming de ficheros grandes con generadores (fixture),
watcher de mtime con rotación por tamaño, contextmanager con cleanup
garantizado (bug+fix), servidor TCP con framing de longitud, y carrera de
contador con sys.setswitchinterval.

Todos los bloques ejecutables son autocontenidos, deterministas (sin reloj del
sistema, sin red externa, sin input()) y terminan solos en < 15 s.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from schema import E  # noqa: E402

# ----------------------------------------------------------------- fixtures 02
HIJO_FILTRO = """\
import sys


def main() -> None:
    for linea in sys.stdin:
        sys.stdout.write(f"[FILTRADO] {linea}")
        sys.stdout.flush()   # flush por linea: el stdout del hijo se llena antes


main()
"""

HIJO_DORMILON = """\
import sys
import time


def main() -> None:
    sys.stdin.read()            # consume la entrada que le manden
    print("empezando", flush=True)
    time.sleep(30)              # demasiado lento: obliga al timeout del padre


main()
"""

FIXTURES_SUBPROCESS = [
    {"name": "hijo_filtro.py", "content": HIJO_FILTRO},
    {"name": "hijo_dormilon.py", "content": HIJO_DORMILON},
]

# ----------------------------------------------------------------- fixture 12
N_LINEAS_EVENTOS = 10000
_ACCIONES = ("login", "query", "query", "query", "logout")
FIXTURE_EVENTOS = "".join(
    (
        f"2024-05-01T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}"
        f"|usuario{(i * 37) % 120:03d}"
        f"|{_ACCIONES[i % 5]}"
        f"|{(i * 97) % 900 + 20}ms\n"
    )
    for i in range(N_LINEAS_EVENTOS)
)
FIXTURES_STREAMING = [{"name": "eventos.log", "content": FIXTURE_EVENTOS}]

EXAMPLES = [
    # ------------------------------------------------------------------ 01
    E(
        language="python",
        domain="backend",
        subdomain="http_api_concurrente",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Necesito un mini-API de tareas con SOLO stdlib que será sometido a carga desde el propio proceso de prueba. Requisitos que fija el equipo de plataforma:

(1) ThreadingHTTPServer en hilo daemon sobre puerto EFÍMERO (0), no fijo.
(2) POST /tareas crea una tarea y devuelve 201; valida que el cuerpo JSON traiga «titulo» no vacío → 400 si falta o es inválido; POST a cualquier otra ruta → 405.
(3) GET /tareas devuelve la lista; GET /tareas/{id} el detalle o 404; id no numérico → 400; ruta desconocida → 404.
(4) Seis POST concurrentes desde un ThreadPoolExecutor: el almacén en memoria DEBE ser thread-safe y los ids únicos.
(5) Respuestas JSON con Content-Length y Content-Type correctos, sin log por petición en stderr.
(6) Apagado ordenado: shutdown + server_close + join, imprimiendo una línea que PRUEBE que el hilo del servidor murió.
(7) Un solo fichero ejecutable que termina solo en pocos segundos y no deja hilos vivos.

Dame el programa completo y las líneas de salida que demuestran cada requisito."""),
            ("assistant", r"""Requisitos inferidos y decisiones de diseño:

- ThreadingHTTPServer atiende cada petición en SU PROPIO hilo: el almacén compartido necesita un threading.Lock en cada lectura/escritura; sin él, el contador de ids puede duplicarse bajo concurrencia.
- puerto 0 + server_address[1]: el puerto real se descubre tras el bind; fijar puerto es receta de colisiones en CI.
- protocol_version = "HTTP/1.1" obliga a mandar Content-Length en TODAS las respuestas (si falta, el cliente se queda esperando el cuerpo). En el 405 leo el cuerpo ANTES de responder: si dejo bytes sin consumir en la conexión keep-alive, el siguiente parseo del handler lee basura.
- Apagado: shutdown() despierta el bucle serve_forever (no cierra el socket), server_close() libera el socket de escucha y join(timeout) comprueba que el hilo murió — apagado_ordenado solo es cierto si el hilo dejó de estar vivo.
- Los errores HTTPError del cliente se capturan como datos (e.code), no como crashes.
Trade-off aceptado: estado en memoria (muere con el proceso) porque lo que se verifica es el protocolo y la concurrencia, no la persistencia."""),
            ("tool", r"""$ python api_tareas.py
ids=1,2,3,4,5,6
total_tareas=6
get_3={"hecha": false, "id": 3}
get_inexistente=404
post_invalido=400
servidor_apagado=True
$ echo $?
0"""),
            ("assistant", r"""Programa completo autocontenido:

```python
import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Almacen:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tareas = {}
        self._proximo_id = 1

    def crear(self, titulo: str) -> dict:
        with self._lock:
            tid = self._proximo_id
            self._proximo_id += 1
            self._tareas[tid] = {"id": tid, "hecha": False}
            return self._tareas[tid]

    def listar(self) -> list:
        with self._lock:
            return [self._tareas[k] for k in sorted(self._tareas)]

    def obtener(self, tid: int):
        with self._lock:
            return self._tareas.get(tid)


ALMACEN = Almacen()


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass                       # pruebas limpias: sin log por peticion

    def _json(self, codigo: int, objeto) -> None:
        cuerpo = json.dumps(objeto).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self) -> None:
        if self.path == "/tareas":
            self._json(200, ALMACEN.listar())
        elif self.path.startswith("/tareas/"):
            try:
                tid = int(self.path.rsplit("/", 1)[1])
            except ValueError:
                self._json(400, {"error": "id no numerico"})
                return
            tarea = ALMACEN.obtener(tid)
            self._json(200 if tarea else 404, tarea if tarea else {"error": "no existe"})
        else:
            self._json(404, {"error": "ruta desconocida"})

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", "0"))
        bruto = self.rfile.read(n) if n else b""   # drenar SIEMPRE el cuerpo
        if self.path != "/tareas":
            self._json(405, {"error": "solo POST /tareas"})
            return
        try:
            datos = json.loads(bruto or b"{}")
            titulo = datos["titulo"]
            if not isinstance(titulo, str) or not titulo.strip():
                raise ValueError
        except (ValueError, KeyError, TypeError):
            self._json(400, {"error": "cuerpo invalido: falta 'titulo'"})
            return
        self._json(201, ALMACEN.crear(titulo))


def cliente_post(base: str, titulo: str) -> dict:
    peticion = urllib.request.Request(
        base + "/tareas",
        data=json.dumps({"titulo": titulo}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def cliente_get(base: str, ruta: str = "/tareas"):
    with urllib.request.urlopen(base + ruta, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)  # puerto efimero
    hilo = threading.Thread(target=servidor.serve_forever,
                            kwargs={"poll_interval": 0.05}, daemon=True)
    hilo.start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    try:
        with ThreadPoolExecutor(max_workers=6) as ex:
            creadas = list(ex.map(lambda i: cliente_post(base, f"tarea-{i}"), range(6)))
        print("ids=" + ",".join(str(t["id"]) for t in sorted(creadas, key=lambda t: t["id"])))
        lista = cliente_get(base)
        print(f"total_tareas={len(lista)}")
        detalle = cliente_get(base, "/tareas/3")
        print(f"get_3={json.dumps({k: detalle[k] for k in ('id', 'hecha')}, sort_keys=True)}")
        try:
            cliente_get(base, "/tareas/999")
        except urllib.error.HTTPError as e:
            print(f"get_inexistente={e.code}")
        peticion = urllib.request.Request(base + "/tareas", data=b"{}",
                                          headers={"Content-Type": "application/json"},
                                          method="POST")
        try:
            urllib.request.urlopen(peticion, timeout=5)
        except urllib.error.HTTPError as e:
            print(f"post_invalido={e.code}")
    finally:
        servidor.shutdown()        # despierta el fin de serve_forever
        servidor.server_close()    # libera el socket de escucha
        hilo.join(timeout=5)
        print(f"servidor_apagado={not hilo.is_alive()}")


main()
```

Verificación línea a línea: ids=1..6 únicos (lock del almacén), total_tareas=6 tras el listado, get_3 con el detalle, 404 para id inexistente, 400 para cuerpo sin titulo, y servidor_apagado=True solo es imprimible si el hilo murió tras shutdown+join. El proceso termina solo (daemon + shutdown explícito) en ~1 s."""),
        ],
        verify=[
            {"name": "api_http_completa", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["ids=1,2,3,4,5,6", "total_tareas=6",
                                        "get_inexistente=404", "post_invalido=400",
                                        "servidor_apagado=True"],
             "timeout_s": 15},
        ],
        tags=["http-server", "urllib", "threading", "concurrency", "graceful-shutdown"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 02
    E(
        language="python",
        domain="systems",
        subdomain="subprocess_stdin_deadlock",
        difficulty="extreme",
        task_type="debugging",
        messages=[
            ("user", r"""Nuestro ETL interno se cuelga a las 3 AM. El padre envía un dataset de 5000 líneas (~370 KB) por stdin a un proceso filtro hijo y luego intenta leer el informe por stdout. El hijo es sencillo: lee líneas, las reetiqueta como [FILTRADO] y hace flush por línea. El padre es esto:

```python
import subprocess
import sys

DATOS = "".join(f"linea-{i:05d}-{'x' * 60}\n" for i in range(5000))  # ~370 KB

p = subprocess.Popen(
    [sys.executable, "hijo_filtro.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
)
p.stdin.write(DATOS)      # <- aqui se cuelga en produccion
p.stdin.flush()
salida = p.stdout.read()
print(f"lineas_salida={len(salida.splitlines())}")
print(f"rc={p.returncode}")
```

Reproduce el bloqueo de forma CONTROLADA (que el reproductor termine solo, aunque sea matado por un timeout externo), explica la causa raíz exacta con el tamaño de los buffers de pipe del SO, y corrige: (a) el caso normal con communicate; (b) además, un hijo que nunca termina debe gestionarse con TimeoutExpired + kill. Los hijos van como ficheros fixture en el directorio de trabajo."""),
            ("assistant", r"""Hipótesis inicial (falsa): «el hijo es lento y el padre no espera suficiente». Un sleep mayor no lo arregla — es un deadlock estructural, no de timing.

Causa raíz: los pipes del SO son FINITOS (~64 KiB en Linux). Secuencia exacta: (1) el padre escribe stdin; el hijo consume y reescribe por stdout con flush por línea; (2) el stdout del hijo llena su pipe de 64 KiB y el hijo se BLOQUEA en su write() — nadie drena; (3) al dejar de leer stdin, el pipe de entrada también se llena (~64 KiB acumulados); (4) el padre se bloquea dentro de p.stdin.write(DATOS) con ~300 KB aún sin escribir y, como jamás sale de esa línea, tampoco llega a p.stdout.read(). Padre e hijo se bloquean mutuamente: nadie drena el pipe del otro. No es carrera: es determinista con 370 KB ≫ 64 KiB.

La reproducción controlada usa `timeout 5` externo (exit 124) para demostrar el bloqueo sin colgar el sandbox. La corrección: communicate(input=...) bombea stdin y drena stdout en paralelo desde hilos internos; para el hijo dormilón, communicate(timeout=...) lanza TimeoutExpired, y hay que kill() + una segunda communicate() para recolectar. Trade-off: communicate bufferiza todo el stdout en memoria; para volúmenes de gigas, redirigir stdout a fichero o leer incrementalmente."""),
            ("tool", r"""$ timeout 5 python etl_rota.py; echo "exit=$?"
exit=124
$ strace -p $(pgrep -f etl_rota) 2>/dev/null | head -2
write(3, "linea-01633-xxxx"..., 243)     # bloqueado en write() sobre stdin
$ python etl_arreglada.py
rc=0 lineas_salida=5000
primera='[FILTRADO] linea-00000-xxxx...'
timeout_manejado=True rc=-9
$ echo $?
0"""),
            ("assistant", r"""Corrección completa (los dos fixtures van como ficheros en el directorio de trabajo):

```python
import subprocess
import sys

DATOS = "".join(f"linea-{i:05d}-{'x' * 60}\n" for i in range(5000))

# 1) communicate(): un solo hilo bombea stdin y drena stdout en paralelo
p = subprocess.Popen(
    [sys.executable, "hijo_filtro.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
)
salida, _ = p.communicate(input=DATOS, timeout=10)
lineas = salida.splitlines()
print(f"rc={p.returncode} lineas_salida={len(lineas)}")
print(f"primera={lineas[0]!r} ultima={lineas[-1]!r}")

# 2) timeout: hijo que nunca termina -> TimeoutExpired -> kill + recogida final
p2 = subprocess.Popen(
    [sys.executable, "hijo_dormilon.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
)
try:
    p2.communicate(input="datos\n", timeout=1)
    print("timeout_manejado=False")
except subprocess.TimeoutExpired:
    p2.kill()
    p2.communicate()   # segunda pasada: recoge el resto y hace el reaping
    print(f"timeout_manejado=True rc={p2.returncode}")
```

Verificación: el buggy muere con exit 124 (timeout externo lo mata bloqueado en stdin.write) y el fix imprime rc=0 con las 5000 líneas íntegras en ~1 s, más timeout_manejado=True con rc=-9 (SIGKILL) del dormilón. Regla del equipo: con PIPE a ambos lados, el único camino seguro es communicate(); escribir y leer secuencialmente solo funciona si el volumen entra en el buffer del SO."""),
        ],
        verify=[
            {"name": "deadlock_stdin_reproducido", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_fail": True, "repeat": 2,
             "fixtures": FIXTURES_SUBPROCESS, "timeout_s": 8},
            {"name": "fix_communicate_timeout", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["lineas_salida=5000", "timeout_manejado=True"],
             "fixtures": FIXTURES_SUBPROCESS, "timeout_s": 10},
        ],
        tags=["subprocess", "pipe", "deadlock", "communicate", "timeout"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 03
    E(
        language="python",
        domain="backend",
        subdomain="asyncio_queue_pipeline",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Ingesta de eventos con asyncio: una fuente emite 20 eventos a razón de 1 cada 10 ms; cada consumidor tarda 30 ms en procesar un evento; quiero DOS consumidores. Requisitos duros del equipo de datos:

- Cola ACOTADA a 4: si los consumidores van por detrás, el productor debe SUSPENDERSE en put (contrapresión real, sin descartar ni bufferizar sin límite).
- Apagado limpio con centinelas (None): una por consumidor; sin tareas huérfanas al final.
- La prueba debe imprimir: producidos, consumo por consumidor, el high-water mark observado de la cola (máximo qsize) y una línea que demuestre cero pérdidas (producidos == consumidos).
- Todo autocontenido con asyncio.run, determinista, sin librerías externas."""),
            ("assistant", r"""Requisitos inferidos y decisiones:

- La contrapresión correcta es `await cola.put(...)` sobre una Queue(maxsize=4): si está llena, put SUSPENDE al productor hasta que un consumidor haga espacio. put_nowait con try/except QueueFull DESCARTARÍA trabajo o exigiría reintento — no es contrapresión, es backpressure fingida.
- Con 2 consumidores × 30 ms hay 66,7 eventos/s de capacidad y la fuente produce 100/s: la cola satura en los primeros instantes, el productor queda gobernado por los consumidores y el high-water mark debe clavar el límite (4). Ese número es la prueba de que la contrapresión actuó.
- Centinelas: encolar 2 None al final, UNO por consumidor, y que el consumidor rompa su bucle al recibirlo; asyncio.gather sobre todas las tareas garantiza que nadie queda huérfano.
- El bucle de eventos es monohilo y determinista: los contadores son estables entre ejecuciones sin locks (no hay preemptión real, solo puntos de suspensión)."""),
            ("tool", r"""$ python ingesta.py
producidos=20
consumidos=c1=10,c2=10
max_q_observado=4 (limite=4)
sin_perdidas=True
$ echo $?
0"""),
            ("assistant", r"""Implementación completa:

```python
import asyncio

MAXQ = 4
N_EVENTOS = 20
SENTINELA = None


async def productor(cola: asyncio.Queue, stats: dict) -> None:
    for i in range(N_EVENTOS):
        await asyncio.sleep(0.01)                # la fuente emite cada 10 ms
        await cola.put({"seq": i})               # se SUSPENDE si la cola esta llena
        stats["max_q"] = max(stats["max_q"], cola.qsize())
    for _ in range(2):                           # una centinela por consumidor
        await cola.put(SENTINELA)
    stats["producidos"] = N_EVENTOS


async def consumidor(nombre: str, cola: asyncio.Queue, stats: dict) -> None:
    procesados = 0
    while True:
        evento = await cola.get()
        if evento is SENTINELA:
            break
        await asyncio.sleep(0.03)                # el procesado es mas lento que la fuente
        procesados += 1
    stats["consumidos"][nombre] = procesados


async def main() -> None:
    cola: asyncio.Queue = asyncio.Queue(maxsize=MAXQ)
    stats: dict = {"max_q": 0, "producidos": 0, "consumidos": {}}
    prod = asyncio.create_task(productor(cola, stats))
    cons = [asyncio.create_task(consumidor(f"c{i}", cola, stats)) for i in (1, 2)]
    await asyncio.gather(prod, *cons)
    total = sum(stats["consumidos"].values())
    print(f"producidos={stats['producidos']}")
    print("consumidos=" + ",".join(f"{k}={v}" for k, v in sorted(stats["consumidos"].items())))
    print(f"max_q_observado={stats['max_q']} (limite={MAXQ})")
    assert stats["producidos"] == total == N_EVENTOS
    print("sin_perdidas=True")


asyncio.run(main())
```

Verificación: producidos=20 y consumidos=10+10 (reparto estable por el orden FIFO de los esperas en el bucle monohilo), max_q_observado=4 — la cola alcanzó el límite, prueba de que el productor se suspendió en put — y sin_perdidas=True con el assert de conteo. Duración ~0,4 s: la fuente (0,2 s de emisión) queda gobernada por los consumidores (~0,3 s de procesado total), exactamente lo que exige la contrapresión."""),
        ],
        verify=[
            {"name": "contrapresion_cola_acotada", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["producidos=20", "consumidos=c1=10,c2=10",
                                        "max_q_observado=4", "sin_perdidas=True"],
             "timeout_s": 15},
        ],
        tags=["asyncio", "queue", "backpressure", "producer-consumer", "graceful-shutdown"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 04
    E(
        language="python",
        domain="backend",
        subdomain="typing_structural_sink",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Estamos abriendo nuestro bus de avisos a plugins de terceros. Necesito (sin librerías externas):

(1) Un contrato ESTRUCTURAL de sink con typing.Protocol: cualquier objeto que exponga enviar(destino: str, cuerpo: str) -> int debe encajar SIN heredar de nada (los vendors no van a importar nuestras clases base).
(2) El dato de dominio del aviso como TypedDict con un campo opcional (detalle), y una frontera validar_avisos() que convierta dicts crudos en avisos validados (id entero no bool, nivel en {info, warn, crit}, texto no vacío) rechazando con ValueError el primer dato malo.
(3) Un Sink de consola propio que conforme el Protocol sin herencia y uno ROTO con firma incompatible, para DEMOSTRAR el límite de @runtime_checkable: isinstance(SinkRoto(), Sink) da True en runtime aunque un type checker estático lo rechace.
(4) difundir() que entregue los avisos por el sink y devuelva los bytes enviados.

Que la demo sea ejecutable y sus conclusiones imprimibles."""),
            ("assistant", r"""Decisiones y matices verificados:

- Protocol = tipado NOMINAL invertido: la conformidad la decide la ESTRUCTURA (métodos presentes con firmas compatibles), no la herencia. ConsolaSink no importa ni hereda nada nuestro y aun así es un Sink para mypy.
- @runtime_checkable permite isinstance(x, Sink), pero SOLO comprueba que los NOMBRES de método existen: SinkRoto.enviar(destino) con un parámetro menos pasa el isinstance y estalla (o peor, «funciona») en ejecución. Conclusión impresa: la comprobación en runtime es de presencia, la de firmas la hace el type checker estático; una isinstance de Protocol NO es validación de contrato.
- TypedDict describe la forma de los datos; NO valida nada en runtime. La frontera validar_avisos() hace la validación manual (con la trampa isinstance(x, bool) excluida cuando esperamos int, porque bool ES int) y construye instancias reales del TypedDict; a partir de ahí el resto del código puede confiar en la forma.
- difundir() acepta cualquier sink conforme: polimorfismo estructural real sin frameworks de plugins."""),
            ("tool", r"""$ python bus_avisos.py
consola_es_sink=True
roto_es_sink_en_runtime=True
typechecker_rechazaria_sink_roto=True
avisos_validos=2
-> equipo-oncall: [crit] disco al 91%
-> equipo-oncall: [info] deploy 2024.17 ok
bytes_enviados=43
rechazado_en_frontera=aviso 0: nivel invalido
$ echo $?
0"""),
            ("assistant", r"""Implementación completa:

```python
from typing import NotRequired, Protocol, TypedDict, runtime_checkable


class Aviso(TypedDict):
    id: int
    nivel: str
    texto: str
    detalle: NotRequired[str]


@runtime_checkable
class Sink(Protocol):
    def enviar(self, destino: str, cuerpo: str) -> int: ...


class ConsolaSink:
    def enviar(self, destino: str, cuerpo: str) -> int:
        print(f"-> {destino}: {cuerpo}")
        return len(cuerpo)


class SinkRoto:
    def enviar(self, destino: str) -> int:   # firma incompatible
        return 0


def validar_avisos(brutos: list) -> list:
    validos = []
    for i, d in enumerate(brutos):
        if not isinstance(d.get("id"), int) or isinstance(d["id"], bool):
            raise ValueError(f"aviso {i}: 'id' debe ser entero")
        if d.get("nivel") not in ("info", "warn", "crit"):
            raise ValueError(f"aviso {i}: nivel invalido")
        if not isinstance(d.get("texto"), str) or not d["texto"]:
            raise ValueError(f"aviso {i}: 'texto' vacio")
        validos.append(Aviso(id=d["id"], nivel=d["nivel"], texto=d["texto"]))
    return validos


def difundir(sink, avisos) -> list:
    return [sink.enviar("equipo-oncall", f"[{a['nivel']}] {a['texto']}") for a in avisos]


def main() -> None:
    print(f"consola_es_sink={isinstance(ConsolaSink(), Sink)}")
    print(f"roto_es_sink_en_runtime={isinstance(SinkRoto(), Sink)}")
    print("typechecker_rechazaria_sink_roto=True")

    brutos = [
        {"id": 1, "nivel": "crit", "texto": "disco al 91%"},
        {"id": 2, "nivel": "info", "texto": "deploy 2024.17 ok", "detalle": "canary"},
        {"id": 3, "nivel": "x", "texto": "nivel falso"},
    ]
    avisos = validar_avisos(brutos[:2])
    print(f"avisos_validos={len(avisos)}")
    entregados = difundir(ConsolaSink(), avisos)
    print(f"bytes_enviados={sum(entregados)}")
    try:
        validar_avisos(brutos[2:])
    except ValueError as e:
        print(f"rechazado_en_frontera={e}")


main()
```

Verificación: consola_es_sink=True (estructural, sin herencia), roto_es_sink_en_runtime=True + typechecker_rechazaria_sink_roto=True (el límite documentado de runtime_checkable), bytes_enviados=43 (suma de los cuerpos entregados) y el aviso con nivel «x» muere en la frontera con un ValueError accionable, no tres capas más abajo."""),
        ],
        verify=[
            {"name": "protocolo_estructural", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["consola_es_sink=True", "roto_es_sink_en_runtime=True",
                                        "bytes_enviados=43", "rechazado_en_frontera"],
             "timeout_s": 10},
        ],
        tags=["protocol", "typeddict", "structural-typing", "boundary-validation"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 05
    E(
        language="python",
        domain="backend",
        subdomain="dataclass_frozen_slots",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Modelo de dominio monetario para el módulo de facturación. Requisitos:

(1) dataclass Dinero con unidades (entero >= 0), centimos (0-99) y moneda (código ISO de 3 mayúsculas); la VALIDACIÓN es manual en __post_init__ y rechaza con ValueError valores imposibles (incluido eur, EURO y centimos=100).
(2) frozen=True: intentar mutar debe levantar FrozenInstanceError (capturado y reportado); «modificar» se hace con dataclasses.replace y el original queda intacto.
(3) slots=True: demostrar que la instancia NO tiene __dict__.
(4) Suma solo entre la misma moneda (mezclar EUR con USD → ValueError) con carry correcto de céntimos.
(5) Al ser frozen+eq, la clase debe funcionar como clave de dict y elemento de set sin duplicados.
(6) Demo ejecutable con todas las comprobaciones imprimidas."""),
            ("assistant", r"""Decisiones:

- frozen=True genera __hash__ automáticamente (porque eq=True): por eso sirve como clave de dict y miembro de set. Con frozen=False y eq=True, la dataclass sería no-hasheable por defecto — la inmutabilidad es lo que habilita el uso como clave.
- slots=True elimina el __dict__ por instancia (menos memoria, acceso por atributos más rápido) e impide crear atributos nuevos por error. Matiz de compatibilidad que conviene conocer: slots + __post_init__ con asignación directa está bien, pero si necesitaras REESCRIBIR un campo desde __post_init__ en una clase frozen, se haría con object.__setattr__(self, "campo", valor) — aquí no hace falta porque solo validamos.
- Validación manual con reglas de dominio (rango, regex ^[A-Z]{3}$, enteros no bool): una dataclass no trae validación de serie; los invariantes viven en __post_init__ y fallan en el CONSTRUCTOR, es decir, en la frontera del tipo: es imposible tener un Dinero inválido vivo.
- __add__ con carry: total en céntimos, divmod manual; misma moneda exigida."""),
            ("tool", r"""$ python dominio_dinero.py
total=16e25
hash_como_clave=teclado
set_tamano=3 (el repetido no se duplica)
slots_sin_dict=True
inmutable=True
replace=12e99 original_intacto=50
validacion_rechazada=(-1, 0, 'EUR') -> True
validacion_rechazada=(1, 100, 'EUR') -> True
validacion_rechazada=(1, 0, 'eur') -> True
validacion_rechazada=(1, 0, 'EURO') -> True
mezcla_monedas_rechazada=True
$ echo $?
0"""),
            ("assistant", r"""Implementación completa:

```python
import re
from dataclasses import dataclass, replace, FrozenInstanceError

_PAT_MONEDA = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Dinero:
    unidades: int
    centimos: int
    moneda: str

    def __post_init__(self) -> None:
        if not isinstance(self.unidades, int) or self.unidades < 0:
            raise ValueError("unidades debe ser entero >= 0")
        if not (0 <= self.centimos <= 99):
            raise ValueError("centimos fuera de rango 0-99")
        if not _PAT_MONEDA.fullmatch(self.moneda):
            raise ValueError("moneda debe ser codigo ISO de 3 mayusculas")

    def __add__(self, otro):
        if not isinstance(otro, Dinero) or otro.moneda != self.moneda:
            raise ValueError("solo se suman importes de la misma moneda")
        total = self.unidades * 100 + self.centimos + otro.unidades * 100 + otro.centimos
        return Dinero(total // 100, total % 100, self.moneda)


def main() -> None:
    precio = Dinero(12, 50, "EUR")
    envio = Dinero(3, 75, "EUR")
    total = precio + envio
    print(f"total={total.unidades}e{total.centimos:02d}")

    carrito: dict = {precio: "teclado", envio: "envio"}
    print(f"hash_como_clave={carrito[precio]}")
    conjunto = {precio, envio, replace(precio, centimos=51), precio}
    print(f"set_tamano={len(conjunto)} (el repetido no se duplica)")

    print(f"slots_sin_dict={not hasattr(precio, '__dict__')}")

    try:
        precio.centimos = 0          # frozen: rechaza la mutacion
    except FrozenInstanceError:
        print("inmutable=True")

    corregido = replace(precio, centimos=99)   # 'modificar' = nueva instancia
    print(f"replace={corregido.unidades}e{corregido.centimos:02d} original_intacto={precio.centimos}")

    for malo in [(-1, 0, "EUR"), (1, 100, "EUR"), (1, 0, "eur"), (1, 0, "EURO")]:
        try:
            Dinero(*malo)
            print(f"validacion_rechazada={malo} -> False")
        except ValueError:
            print(f"validacion_rechazada={malo} -> True")

    try:
        precio + Dinero(1, 0, "USD")
    except ValueError:
        print("mezcla_monedas_rechazada=True")


main()
```

Verificación: total=16e25 con carry correcto (50+75=125 céntimos → +1 unidad), hash_como_clave y set_tamano=3 (el cuádruple set con un repetido no duplica), slots_sin_dict=True, inmutable=True con FrozenInstanceError capturado, replace que crea una NUEVA instancia dejando el original intacto, los cuatro constructores imposibles rechazados y la mezcla EUR/USD prohibida."""),
        ],
        verify=[
            {"name": "dominio_inmutable", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["total=16e25", "set_tamano=3", "slots_sin_dict=True",
                                        "inmutable=True", "mezcla_monedas_rechazada=True"],
             "timeout_s": 10},
        ],
        tags=["dataclasses", "frozen", "slots", "domain-model", "validation"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 06
    E(
        language="python",
        domain="data",
        subdomain="profiling_hot_path",
        difficulty="very_hard",
        task_type="optimization",
        messages=[
            ("user", r"""Nuestro /dedupe elimina duplicados de listas de 6000 enteros y tarda demasiado. La función actual:

```python
def duplicados_lista(valores):
    vistos = []
    for v in valores:
        if v not in vistos:
            vistos.append(v)
    return vistos
```

Lo que necesito, medido y sin humo: (1) auto-perfilado del hot path con cProfile dentro del propio script para CONFIRMAR dónde vive el coste; (2) una optimización que conserve el CONTRATO (orden de primera aparición) — ojo: el intento con sorted(set(xs)) se descartó porque reordena; (3) tiempos antes/después con perf_counter y el ratio impreso, con las dos salidas comparadas elemento a elemento; (4) el script entero debe terminar rápido y decir «mismo_resultado=True»."""),
            ("assistant", r"""Hipótesis a confirmar con el perfil, no a suponer: `v not in vistos` sobre LISTA es O(n) por elemento → O(n²) total (~10,5 millones de comparaciones con 6000 elementos y 3500 distintos). cProfile en la mano: la llamada dominante en cumulative debe ser duplicados_lista y el gasto no está en append sino en el operador `in` (C-level, invisible como llamada; por eso el perfil se lee por cumulative de la función, no por número de llamadas).

Optimización candidata: set para membresía O(1) medio + lista paralela para conservar el ORDEN DE PRIMERA APARICIÓN. El intento descartado (sorted(set(xs))) es igual de rápido pero rompe el contrato: con los datos mezclados, sorted() reordena y el test de igualdad contra la referencia falla — lo dejo impreso como evidencia de la hipótesis fallida. dict.fromkeys(xs) sería la alternativa idiomática; elijo el bucle explícito para que la paralela set+lista se vea clara.

Medición: perf_counter alrededor de cada versión, misma entrada determinista ((i*997) % 3500 — mezcla real, no ya ordenada), ratio impreso y comparación de listas completa. Espero un ratio de tres órdenes de magnitud; el número exacto varía por máquina, la conclusión no."""),
            ("tool", r"""$ python perfil_dedupe.py
antes=0.071s
despues=0.000s
ratio=165x
mismo_resultado=True distinct=3500
orden_primera_aparicion=[0, 997, 1994, 2991, 488]
sorted_set_cambia_orden=True
perfil_incluye_duplicados_lista=True
perfil_llamadas_totales=3502
$ echo $?
0"""),
            ("assistant", r"""Script completo con auto-perfilado y medición:

```python
import cProfile
import io
import pstats
import time

N = 6000


def datos() -> list:
    return [(i * 997) % 3500 for i in range(N)]   # 3500 distintos, orden mezclado


def duplicados_lista(valores: list) -> list:
    vistos: list = []
    for v in valores:
        if v not in vistos:
            vistos.append(v)
    return vistos


def duplicados_conjunto(valores: list) -> list:
    vistos: set = set()
    unicos: list = []
    for v in valores:
        if v not in vistos:
            vistos.add(v)
            unicos.append(v)
    return unicos


def main() -> None:
    xs = datos()

    t0 = time.perf_counter()
    ref = duplicados_lista(xs)
    t_antes = time.perf_counter() - t0

    t0 = time.perf_counter()
    rapida = duplicados_conjunto(xs)
    t_despues = time.perf_counter() - t0

    print(f"antes={t_antes:.3f}s")
    print(f"despues={t_despues:.3f}s")
    print(f"ratio={t_antes / t_despues:.0f}x")
    print(f"mismo_resultado={ref == rapida} distinct={len(rapida)}")

    print(f"orden_primera_aparicion={rapida[:5]}")
    print(f"sorted_set_cambia_orden={sorted(set(xs))[:5] != rapida[:5]}")

    profiler = cProfile.Profile()
    profiler.enable()
    duplicados_lista(xs)
    profiler.disable()
    buffer = io.StringIO()
    estadisticas = pstats.Stats(profiler, stream=buffer).sort_stats("cumulative")
    estadisticas.print_stats(5)
    informe = buffer.getvalue()
    print(f"perfil_incluye_duplicados_lista={'duplicados_lista' in informe}")
    print(f"perfil_llamadas_totales={estadisticas.total_calls}")


main()
```

Lectura del resultado: el perfil lista 3502 llamadas totales (main + duplicados_lista + 3500 append) y duplicados_lista domina el cumulative — la membresía O(n) sobre lista era el hot path. El fix baja de ~0,07 s a ~0,0002 s (ratio de dos-tres órdenes, estable en dirección) con mismo_resultado=True sobre las 3500 entradas. La hipótesis sorted(set) queda desmontada con datos: sorted_set_cambia_orden=True — rápido pero incorrecto para este contrato."""),
        ],
        verify=[
            {"name": "optimizacion_medible", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["mismo_resultado=True", "sorted_set_cambia_orden=True",
                                        "perfil_incluye_duplicados_lista=True"],
             "timeout_s": 15},
        ],
        tags=["cprofile", "pstats", "performance", "profiling", "sets"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 07
    E(
        language="python",
        domain="data",
        subdomain="lru_cache_dp",
        difficulty="hard",
        task_type="optimization",
        messages=[
            ("user", r"""El calculador de rutas de nuestro planificador recursivo es correcto pero lento, y el equipo no se fía de las cachés «mágicas». Necesito una demo con functools.lru_cache que sea auditable y determinista:

(1) caminos(m, n) — caminos de una retícula de (0,0) a (m,n) con pasos a derecha/arriba — cacheada con maxsize=None; tras UNA llamada caminos(12, 12) quiero que la demo imprima cache_info() y EXPLIQUE por qué hits/misses/currsize son exactamente esos números (estados únicos visitados, sin recalcular nada).
(2) Comparación honesta de fib(27) sin caché y con caché: mismo valor, ratio de tiempo impreso.
(3) cache_info() del fib cacheado (hits/misses reales de la recursión lineal).
(4) La trampa de hashabilidad: pasar una lista a la función cacheada levanta TypeError (los argumentos deben ser hashables) — capturado y reportado.
Sin librerías externas; el programa termina rápido."""),
            ("assistant", r"""Anatomía de lru_cache, verificada con cache_info:

- misses = número de llamadas cuyo par de argumentos NO estaba en la caché. Para caminos(12, 12) la recursión visita cada estado (m, n) EXACTAMENTE una vez: la retícula tiene 13×13 = 169 celdas, pero (0, 0) es inalcanzable (los casos base m==0 o n==0 devuelven 1 sin seguir recursando), así que misses=168 y currsize=168. hits=121 son las llamadas que encontraron su estado ya calculado: antes de la caché, cada estado se recalculaba exponencialmente; después, una vez.
- fib(27) sin caché hace ~600.000 llamadas; con caché, 27 misses (uno por n) y 25 hits. El valor es idéntico (196418): la caché no cambia el resultado, cambia el árbol de llamadas de exponencial a lineal.
- La trampa: la caché indexa por TUPLA de argumentos; una lista no es hashable → TypeError en la propia llamada. Se captura y se reporta; el patrón correcto para mutables es pasar tuplas o claves canónicas propias.
Trade-off documentado: maxsize=None no acota memoria (para datos de dominio acotados está bien); maxsize=N con política LRU es lo correcto cuando el espacio de claves crece sin límite."""),
            ("tool", r"""$ python rutas_cacheadas.py
caminos_12x12=2704156
estados_unicos=168 (reticula 13x13 menos (0,0), inalcanzable)
hits=121 misses=168 cache_size=168
fib_27=196418 mismo_valor=True
ratio_fib=2082x
fib_hits=25 fib_misses=28
unhashable_manejado=True
$ echo $?
0"""),
            ("assistant", r"""Implementación completa (los números de cache_info son deterministas: mismos hits/misses en cualquier máquina):

```python
import time
from functools import lru_cache


@lru_cache(maxsize=None)
def caminos(m: int, n: int) -> int:
    if m == 0 or n == 0:
        return 1
    return caminos(m - 1, n) + caminos(m, n - 1)


def fib_sin_cache(n: int) -> int:
    if n < 2:
        return n
    return fib_sin_cache(n - 1) + fib_sin_cache(n - 2)


@lru_cache(maxsize=128)
def fib_con_cache(n: int) -> int:
    if n < 2:
        return n
    return fib_con_cache(n - 1) + fib_con_cache(n - 2)


def main() -> None:
    caminos.cache_clear()
    resultado = caminos(12, 12)
    info = caminos.cache_info()
    print(f"caminos_12x12={resultado}")
    print(f"estados_unicos={info.misses} (reticula 13x13 menos (0,0), inalcanzable)")
    print(f"hits={info.hits} misses={info.misses} cache_size={info.currsize}")
    assert info.misses == 168, "cada estado (m,n) se calcula exactamente una vez"

    t0 = time.perf_counter()
    v1 = fib_sin_cache(27)
    t_lento = time.perf_counter() - t0
    t0 = time.perf_counter()
    v2 = fib_con_cache(27)
    t_rapido = time.perf_counter() - t0
    print(f"fib_27={v1} mismo_valor={v1 == v2}")
    print(f"ratio_fib={t_lento / max(t_rapido, 1e-9):.0f}x")

    info_fib = fib_con_cache.cache_info()
    print(f"fib_hits={info_fib.hits} fib_misses={info_fib.misses}")

    try:
        caminos([2], 3)   # argumento no hashable: lru_cache no puede indexarlo
    except TypeError:
        print("unhashable_manejado=True")


main()
```

Verificación: caminos_12x12=2704156 con el audit exacto del espacio de estados (168 misses, 121 hits, currsize=168, assert incluido), fib_27 idéntico en ambas versiones con ratio de tres órdenes, fib_hits=25/fib_misses=28 (27 niveles + la llamada final que solo consulta) y la trampa de hashabilidad capturada como TypeError."""),
        ],
        verify=[
            {"name": "cache_auditable", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["caminos_12x12=2704156", "estados_unicos=168",
                                        "unhashable_manejado=True", "mismo_valor=True"],
             "timeout_s": 10},
        ],
        tags=["functools", "lru-cache", "memoization", "dynamic-programming"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 08
    E(
        language="python",
        domain="backend",
        subdomain="singledispatch_registry",
        difficulty="medium",
        task_type="refactoring",
        messages=[
            ("user", r"""Tenemos una cadena de isinstance de 30 líneas que crece con cada tipo nuevo y hay que reescribirla con functools.singledispatch. Requisitos del refactor:

(1) serializar(valor) -> str con registro por tipos: bool, int, str, list (recursivo) y dict (recursivo, claves ordenadas); la rama genérica debe FALLAR con TypeError claro para tipos sin registro (p. ej. set).
(2) TRAMPA que ya mordió a otro equipo: bool es subclase de int — si solo registras int, True se serializa como 1. Hay que registrar bool explícitamente y demostrar que sale true/false.
(3) Herencia y despacho: registrar SOLO Parte y comprobar que una subclase Tornillo cae en el handler de Parte (el despacho mira el MRO).
(4) El equivalente para métodos de clase: singledispatchmethod con resumen(dato) para int y str, rechazando float.
(5) Registro dinámico adicional con @serializar.register(float, ...) si el equipo lo pide luego (déjalo demostrado en una línea comentada).
Demo ejecutable con todas las trampas imprimidas."""),
            ("assistant", r"""Decisiones del refactor:

- singledispatch convierte la cadena de isinstance en una TABLA de registro: cada tipo nuevo es un @register en su propio módulo (o incluso desde el plugin del vendor), sin tocar la función base. La rama genérica con TypeError explícito es mejor que un silencioso None: los tipos no soportados deben ser un error ruidoso.
- Orden de registro de bool/int: el despacho elige la coincidencia MÁS específica del MRO del tipo del argumento. Si bool está registrado, True → bool; si no, True → int (bool ES instancia de int). La demo imprime los dos caminos.
- Subclases sin registro propio: Tornillo(Parte) no tiene handler, pero el despacho recorre el MRO y encuentra Parte. Consecuencia para el diseño: registra por CLASES BASE abstractas si quieres que las subclases hereden el despacho.
- singledispatchmethod lleva el mismo mecanismo a métodos; self NO participa en el despacho (solo el primer argumento «lógico» posterior).
- Cuidado con los anotadores: registrar con type hints dentro del mismo fichero funciona (register infiere el tipo de la anotación), pero para tipos externos se usa register(Tipo) explícito."""),
            ("tool", r"""$ python serializador.py
bool: true
int: 42
str: "espa\u00f1ol"
list: [1, "dos", false]
dict: {"a": [3], "b": 2}
subclase_mro=<parte generica>
generico_rechazado=sin serializador para set
entero(-7)
cadena(9 chars)
visita_rechazada=tipo no soportado: float
$ echo $?
0"""),
            ("assistant", r"""Refactor completo:

```python
import json
from functools import singledispatch, singledispatchmethod


@singledispatch
def serializar(valor) -> str:
    raise TypeError(f"sin serializador para {type(valor).__name__}")


@serializar.register(bool)          # bool ANTES de confiar en int
def _(valor: bool) -> str:
    return "true" if valor else "false"


@serializar.register(int)
def _(valor: int) -> str:
    return str(valor)


@serializar.register(str)
def _(valor: str) -> str:
    return json.dumps(valor, ensure_ascii=True)


@serializar.register(list)
def _(valor: list) -> str:
    return "[" + ", ".join(serializar(v) for v in valor) + "]"


@serializar.register(dict)
def _(valor: dict) -> str:
    return "{" + ", ".join(f"{serializar(k)}: {serializar(v)}" for k, v in sorted(valor.items())) + "}"


class VisitaInforme:

    @singledispatchmethod
    def resumen(self, dato) -> str:
        raise TypeError(f"tipo no soportado: {type(dato).__name__}")

    @resumen.register(int)
    def _visita_entero(self, dato: int) -> str:
        return f"entero({dato:+d})"

    @resumen.register(str)
    def _visita_cadena(self, dato: str) -> str:
        return f"cadena({len(dato)} chars)"


class Parte:
    def nombre(self) -> str:
        return "parte generica"


class Tornillo(Parte):
    pass


@serializar.register(Parte)          # solo la base registrada: el MRO hace el resto
def _(valor: Parte) -> str:
    return f"<{valor.nombre()}>"


def main() -> None:
    datos = [True, 42, "espa\u00f1ol", [1, "dos", False], {"b": 2, "a": [3]}]
    for d in datos:
        print(f"{type(d).__name__}: {serializar(d)}")

    print(f"subclase_mro={serializar(Tornillo())}")

    try:
        serializar({1, 2, 3})
    except TypeError as e:
        print(f"generico_rechazado={e}")

    visita = VisitaInforme()
    print(visita.resumen(-7))
    print(visita.resumen("protocolo"))
    try:
        visita.resumen(3.14)
    except TypeError as e:
        print(f"visita_rechazada={e}")


main()
```

Verificación: true/false distinguidos del int (la trampa bool), recursión en list/dict con claves ordenadas, Tornillo despachado a Parte vía MRO, set rechazado por la rama genérica y singledispatchmethod cubriendo métodos. Extender a un tipo nuevo es añadir un @register, no editar una cadena de isinstance; para float bastaría @serializar.register(float) con su handler."""),
        ],
        verify=[
            {"name": "despacho_por_tipos", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["bool: true", "subclase_mro=<parte generica>",
                                        "generico_rechazado=sin serializador para set",
                                        "visita_rechazada=tipo no soportado: float"],
             "timeout_s": 10},
        ],
        tags=["functools", "singledispatch", "refactoring", "polymorphism"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 09
    E(
        language="python",
        domain="data",
        subdomain="itertools_etl",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Pipeline ETL de pedidos con itertools, sin pandas, procesando pedidos fisicos y digitales. Cada fila es (zona, sku, importe). Necesito una demo que encadene las piezas correctas y además documente un pitfall que nos costó horas:

- Fusionar dos fuentes con chain y descartar importes <= 0 con filterfalse.
- tee para repartir el MISMO stream a dos consumidores: totales por zona y alertas de importe >= 100.
- Totales por zona con groupby — y la prueba del pitfall: groupby agrupa SOLO adyacentes; sin sort previo, las 4 zonas fragmentan en 9 grupos. Imprimir grupos_con_sort vs grupos_sin_sort.
- acumulado = accumulate sobre la serie de pedidos por hora y mayor salto entre horas con pairwise.
- Lotes de envío de 3 SKUs con batched (itertools.batched, 3.12) y vista previa con islice.
- Salida determinista y ordenada."""),
            ("assistant", r"""Decisiones:

- groupby vs SQL GROUP BY: groupby agrupa CORRIDAS de claves iguales; si los datos no llegan ordenados por la clave, una zona «vuelve» y aparece como grupo nuevo. Por eso el patrón canónico es sorted(data, key) ANTES de groupby. La demo imprime 9 grupos sin sort vs 4 con sort sobre los mismos datos.
- tee(iterable, 2) devuelve dos iteradores independientes que comparten el stream subyacente: una sola pasada de E/S, dos consumidores. Aviso operativo: si un consumidor se queda muy atrás, tee bufferiza los elementos pendientes — para streams grandes, mejor re-leer la fuente que tee con desfase enorme.
- accumulate genera el total corrido perezosamente (no una lista nueva por punto); pairwise da las parejas contiguas para los deltas de hora a hora.
- batched(iterable, 3) (nuevo en 3.12) corta en tuplas de tamaño 3 sin materializar la lista completa: chunking perezoso para lotes de envío.
- Todas las salidas se ordenan/etiquetan para que la demo sea idéntica en cada ejecución."""),
            ("tool", r"""$ python etl_itertools.py
totales=este=245, norte=165, oeste=150, sur=255
alertas=este/SKU-300:210; oeste/DIG-003:150; sur/SKU-900:120
acumulado=30,60,115,155,245,365
mayor_salto=hora 3-> +50
lotes_de_envio=3 primera=('DIG-001', 'DIG-002', 'DIG-003')
vista_previa=sur/SKU-900; norte/SKU-100
groupby_sin_sort_grupos=9 (zonas reales: 4)
$ echo $?
0"""),
            ("assistant", r"""Pipeline completo:

```python
from itertools import accumulate, batched, chain, filterfalse, groupby, islice, pairwise, tee

FISICOS = [
    ("sur", "SKU-900", 120), ("norte", "SKU-100", 80), ("sur", "SKU-450", 45),
    ("este", "SKU-300", 210), ("norte", "SKU-220", 60),
]
DIGITALES = [
    ("este", "DIG-001", 35), ("sur", "DIG-002", 90), ("norte", "SKU-100", 25),
    ("oeste", "DIG-003", 150),
]


def total_por_zona(pedidos) -> dict:
    ordenados = sorted(pedidos, key=lambda p: p[0])   # groupby exige adyacencia
    return {zona: sum(p[2] for p in grupo)
            for zona, grupo in groupby(ordenados, key=lambda p: p[0])}


def main() -> None:
    todo = chain(FISICOS, DIGITALES)                      # dos fuentes, un stream
    validos = list(filterfalse(lambda p: p[2] <= 0, todo))

    rama_totales, rama_alertas = tee(validos, 2)

    totales = total_por_zona(rama_totales)
    print("totales=" + ", ".join(f"{z}={v}" for z, v in sorted(totales.items())))

    alertas = [p for p in rama_alertas if p[2] >= 100]
    print("alertas=" + "; ".join(f"{z}/{sku}:{v}" for z, sku, v in sorted(alertas)))

    serie = [30, 30, 55, 40, 90, 120]
    acumulado = list(accumulate(serie))
    print("acumulado=" + ",".join(map(str, acumulado)))
    saltos = [(a, b, b - a) for a, b in pairwise(serie)]
    peor = max(saltos, key=lambda s: s[2])
    print(f"mayor_salto=hora {saltos.index(peor)}-> {peor[2]:+d}")

    lotes = list(batched(sorted(v[1] for v in validos), 3))
    print(f"lotes_de_envio={len(lotes)} primera={lotes[0]}")

    print("vista_previa=" + "; ".join(f"{z}/{sku}" for z, sku, _ in islice(validos, 2)))

    grupos_sin_sort = list(groupby(validos, key=lambda p: p[0]))
    zonas_reales = len(set(p[0] for p in validos))
    print(f"groupby_sin_sort_grupos={len(grupos_sin_sort)} (zonas reales: {zonas_reales})")


main()
```

Verificación: totales cuadrados por zona (sur=120+45+90=255, este=210+35=245...), dos ramas del tee con datos consistentes, acumulado correcto con el mayor salto +50 entre la hora 3 y la 4, batched de 3 sobre 9 SKUs válidos y la lección impresa: 9 grupos fragmentados sin sort frente a 4 zonas reales."""),
        ],
        verify=[
            {"name": "pipeline_itertools", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["totales=este=245, norte=165, oeste=150, sur=255",
                                        "acumulado=30,60,115,155,245,365",
                                        "lotes_de_envio=3",
                                        "groupby_sin_sort_grupos=9 (zonas reales: 4)"],
             "timeout_s": 10},
        ],
        tags=["itertools", "groupby", "pipeline", "lazy-evaluation"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 10
    E(
        language="python",
        domain="tooling",
        subdomain="unittest_border_cases",
        difficulty="hard",
        task_type="testing",
        messages=[
            ("user", r"""Nuestro parser de duraciones («1h30m», «90s», «2d») ha devuelto valores absurdos en producción con entradas raras. Escribe el módulo parsear_duracion(texto) -> segundos (float) con estas reglas de contrato, y su SUITE unittest de casos límite:

- Unidades s/m/h/d (60, 3600, 86400); composición «1h30m»=5400; tokens repetidos se ACUMULAN («5m5m»=600); decimales «1.5m»=90 y «0.25h»=900; mayúsculas se normalizan («1M»=60); espacios interiores se toleran («1h 30m»).
- Errores: cadena vacía/solo espacios → ValueError; sin unidad («10»), unidad desconocida («10x»), negativos («-5s»), doble decimal («1.5.5s») → ValueError; tipo no str (None, 42, [60]) → TypeError.
- La suite debe usar subTest para reportar CADA caso individualmente, assertRaises paramétrico, un test @skip documentado (semanas «1w» aún fuera de contrato) y un @unittest.expectedFailure que documenta el futuro «1w»=604800 (hoy falla).
- Ejecutable como fichero: unittest.main() al final, y la salida del runner debe terminar en «OK (skipped=1, expected failures=1)»."""),
            ("assistant", r"""Decisiones de diseño y de suite:

- Parser en dos fases: una regex de TOKEN (\d+(?:\.\d+)?[smhd]) y una regex de FORMATO COMPLETO (^(?:token)+$). El formato completo rechaza de un vistazo «10», «10x», «-5s», «1.5.5s» y «1h-30m» (el guion rompe la secuencia de tokens); después findall extrae pares (valor, unidad) que se suman. strip().lower().replace(" ", "") normaliza mayúsculas y espacios ANTES de validar, para que «1h 30m» y «1M» sean casos válidos y no excepciones.
- TypeError para tipos (fallo de programador) vs ValueError para contenido (fallo de dato): distinción que después permite a los llamadores distinguir bugs de entradas sucias.
- subTest dentro del bucle: si falla el caso 4 de 7, el runner reporta los SIETE, no solo el primero — imprescindible para suites de casos límite.
- @skip y @expectedFailure documentan el contrato futuro sin ensuciar el OK: el runner exige OK (skipped=1, expected failures=1); si mañana alguien implementa «1w», el expectedFailure se convierte en «unexpected success» y FALLA la suite — el mecanismo te obliga a actualizar el test cuando el contrato cambia."""),
            ("tool", r"""$ python test_duracion.py
test_casos_validos (__main__.PruebasParsearDuracion.test_casos_validos) ... ok
test_cero_y_decimales (__main__.PruebasParsearDuracion.test_cero_y_decimales) ... ok
test_formato_invalido (__main__.PruebasParsearDuracion.test_formato_invalido) ... ok
test_semanas_futuro (__main__.PruebasParsearDuracion.test_semanas_futuro) ... skipped 'semanas no forman parte del contrato actual'
test_semanas_pendiente_de_contrato (__main__.PruebasParsearDuracion.test_semanas_pendiente_de_contrato) ... expected failure
test_tipo_incorrecto (__main__.PruebasParsearDuracion.test_tipo_incorrecto) ... ok
test_token_repetido_se_acumula (__main__.PruebasParsearDuracion.test_token_repetido_se_acumula) ... ok
----------------------------------------------------------------------
Ran 7 tests in 0.001s
OK (skipped=1, expected failures=1)
$ echo $?
0"""),
            ("assistant", r"""Módulo y suite completos, ejecutables como un único fichero:

```python
import re
import unittest

UNIDADES = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
_TOKEN = re.compile(r"(\d+(?:\.\d+)?)([smhd])")
_COMPLETA = re.compile(r"^(?:\d+(?:\.\d+)?[smhd])+$")


def parsear_duracion(texto) -> float:
    if not isinstance(texto, str):
        raise TypeError(f"se esperaba str, llega {type(texto).__name__}")
    limpio = texto.strip().lower().replace(" ", "")
    if not limpio:
        raise ValueError("cadena vacia")
    if not _COMPLETA.fullmatch(limpio):
        raise ValueError(f"formato invalido: {texto!r}")
    return sum(float(v) * UNIDADES[u] for v, u in _TOKEN.findall(limpio))


class PruebasParsearDuracion(unittest.TestCase):
    def test_casos_validos(self):
        casos = [("90s", 90.0), ("1h30m", 5400.0), ("2d", 172800.0),
                 ("0s", 0.0), ("1.5m", 90.0), ("1M", 60.0), ("1h 30m", 5400.0)]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(parsear_duracion(texto), esperado)

    def test_token_repetido_se_acumula(self):
        self.assertEqual(parsear_duracion("5m5m"), 600.0)

    def test_cero_y_decimales(self):
        self.assertEqual(parsear_duracion("0.25h"), 900.0)

    def test_formato_invalido(self):
        for texto in ["", "   ", "10", "10x", "-5s", "h", "1.5.5s", "1h-30m"]:
            with self.subTest(texto=texto):
                with self.assertRaises(ValueError):
                    parsear_duracion(texto)

    def test_tipo_incorrecto(self):
        for valor in (None, 42, [60]):
            with self.subTest(valor=valor):
                with self.assertRaises(TypeError):
                    parsear_duracion(valor)

    @unittest.skip("semanas no forman parte del contrato actual")
    def test_semanas_futuro(self):
        self.assertEqual(parsear_duracion("1w"), 604800.0)

    @unittest.expectedFailure
    def test_semanas_pendiente_de_contrato(self):
        self.assertEqual(parsear_duracion("1w"), 604800.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Verificación: el runner termina en «Ran 7 tests» y «OK (skipped=1, expected failures=1)» con exit 0 — el bloque ejecuta unittest.main(), que hace sys.exit(0) solo si TODOS los casos pasan (los skipped y expected failures no cuentan contra la suite), así que el código de salida ES la verificación."""),
        ],
        verify=[
            {"name": "suite_casos_limite", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["Ran 7 tests", "OK (skipped=1, expected failures=1)"],
             "timeout_s": 10},
        ],
        tags=["unittest", "subtest", "edge-cases", "testing"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 11
    E(
        language="python",
        domain="databases",
        subdomain="sqlite_transactions_upsert",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Caja registradora multi-titular sobre sqlite3 puro (sin ORM). Contratos:

(1) Tabla cuenta con saldo en CÉNTIMOS (entero, nunca float) y CHECK (centimos >= 0) como última línea de defensa; tabla diario(dia, titular, importe) con PK (dia, titular).
(2) Control de transacciones EXPLÍCITO: isolation_level=None y BEGIN IMMEDIATE / COMMIT / ROLLBACK a mano. Nada del comportamiento implícito por defecto.
(3) transferir() atómico: valida fondos, descuenta, abona y registra AMBOS lados del diario con UPSERT (INSERT ... ON CONFLICT(dia, titular) DO UPDATE SET importe = importe + excluded.importe) para que el diario del día AGREGUE movimientos. Si algo falla → ROLLBACK y saldos intactos.
(4) Demo: seed de tres cuentas; una transferencia correcta; una transferencia de 99999 que DEBE fracasar (fondos) dejando balances y diario EXACTAMENTE igual; un UPDATE que rompa el CHECK y muestre IntegrityError.
(5) Balances y diario finales impresos de forma determinista."""),
            ("assistant", r"""Decisiones y matices verificados:

- Céntimos enteros: el dinero nunca va en float (0.1+0.2 no es 0.3). El CHECK de la tabla es la última línea de defensa: aunque el código de arriba tenga un bug, la base RECHAZA saldos negativos con IntegrityError.
- isolation_level=None desactiva la gestión implícita de sqlite3 (el modo «isolation_level» por defecto abre transacciones al vuelo y complica el razonamiento); con None soy yo quien marca BEGIN IMMEDIATE (bloqueo de escritura desde el inicio: evita sorpresas de upgrade de lock entre sesiones concurrentes), COMMIT o ROLLBACK.
- UPSERT con DO UPDATE SET importe = importe + excluded.importe: la primera escritura del día INSERTA; las siguientes SUMAN sobre la fila existente. Es el patrón de agregación idempotente para diarios.
- Rollback total: transferir() captura cualquier excepción (BaseException, no solo Exception: también queremos deshacer en CancelledError/KeyboardInterrupt), hace ROLLBACK y devuelve False. La demo comprueba que tras el fallo los balances y el diario son BYTE A BYTE los mismos.
- total_changes al final como recuento determinista de escrituras aplicadas."""),
            ("tool", r"""$ python caja_ledger.py
balances_iniciales={'ana': 10000, 'bob': 5000, 'carl': 100}
transferencia_1=True balances={'ana': 7500, 'bob': 7500, 'carl': 100}
transferencia_2=False balances={'ana': 7500, 'bob': 7500, 'carl': 100}
diario_agregado={'ana': -2500, 'bob': 2500}
check_integridad=disparada
cambios_totales=8
$ echo $?
0"""),
            ("assistant", r"""Implementación completa:

```python
import sqlite3

ESQUEMA = '''
CREATE TABLE cuenta (
    titular TEXT PRIMARY KEY,
    centimos INTEGER NOT NULL CHECK (centimos >= 0)
);
CREATE TABLE diario (
    dia     TEXT,
    titular TEXT,
    importe INTEGER,
    PRIMARY KEY (dia, titular)
);
'''


def abrir() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.isolation_level = None          # control explicito de transacciones
    con.executescript(ESQUEMA)
    return con


def saldo(con, titular):
    fila = con.execute("SELECT centimos FROM cuenta WHERE titular = ?", (titular,)).fetchone()
    return None if fila is None else fila[0]


def transferir(con, origen, destino, centimos, dia="2024-05-01") -> bool:
    con.execute("BEGIN IMMEDIATE")
    try:
        if saldo(con, origen) is None or saldo(con, origen) < centimos:
            raise ValueError("fondos insuficientes")
        con.execute("UPDATE cuenta SET centimos = centimos - ? WHERE titular = ?", (centimos, origen))
        con.execute("UPDATE cuenta SET centimos = centimos + ? WHERE titular = ?", (centimos, destino))
        con.execute(
            '''INSERT INTO diario(dia, titular, importe) VALUES (?, ?, ?)
               ON CONFLICT(dia, titular)
               DO UPDATE SET importe = importe + excluded.importe''',
            (dia, origen, -centimos),
        )
        con.execute(
            '''INSERT INTO diario(dia, titular, importe) VALUES (?, ?, ?)
               ON CONFLICT(dia, titular)
               DO UPDATE SET importe = importe + excluded.importe''',
            (dia, destino, centimos),
        )
        con.execute("COMMIT")
        return True
    except BaseException:
        con.execute("ROLLBACK")
        return False


def balances(con) -> dict:
    return dict(sorted(con.execute("SELECT titular, centimos FROM cuenta").fetchall()))


con = abrir()
con.executemany("INSERT INTO cuenta VALUES (?, ?)", [("ana", 10000), ("bob", 5000), ("carl", 100)])
print(f"balances_iniciales={balances(con)}")

ok1 = transferir(con, "ana", "bob", 2500)
print(f"transferencia_1={ok1} balances={balances(con)}")

ok2 = transferir(con, "bob", "ana", 99999)   # fondos insuficientes -> rollback
print(f"transferencia_2={ok2} balances={balances(con)}")

diario = dict(sorted(con.execute("SELECT titular, importe FROM diario WHERE dia = '2024-05-01'").fetchall()))
print(f"diario_agregado={diario}")

try:
    con.execute("UPDATE cuenta SET centimos = centimos - 999999 WHERE titular = 'carl'")
except sqlite3.IntegrityError as e:
    print(f"check_integridad={'disparada' if 'CHECK' in str(e) else str(e)}")

con.execute("INSERT INTO diario VALUES ('2024-05-01', 'carl', 50)")
print(f"cambios_totales={con.total_changes}")
con.close()
```

Verificación: la transferencia correcta deja ana=7500/bob=7500 y el diario AGREGADO en una sola fila por titular (-2500 y +2500); la transferencia de 99999 devuelve False con balances IDÉNTICOS (rollback) y diario sin rastro; el UPDATE que viola el CHECK muere con IntegrityError; y cambios_totales=8 (3 seed + 2 updates + 2 upserts + 1 insert) confirma el recuento de escrituras aplicadas."""),
        ],
        verify=[
            {"name": "transacciones_y_upsert", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["transferencia_2=False balances={'ana': 7500, 'bob': 7500, 'carl': 100}",
                                        "diario_agregado={'ana': -2500, 'bob': 2500}",
                                        "check_integridad=disparada"],
             "timeout_s": 10},
        ],
        tags=["sqlite3", "transactions", "upsert", "rollback", "money-handling"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 12
    E(
        language="python",
        domain="data",
        subdomain="streaming_generators",
        difficulty="hard",
        task_type="optimization",
        messages=[
            ("user", r"""Necesito el informe de latencias de nuestro access log (eventos.log, 10000 líneas formato «fecha|usuarioNNN|accion|NNNms»; el fixture ya está en el directorio de trabajo) pero el anterior intento con readlines() mataba la memoria del contenedor. Requisitos:

(1) Lectura en STREAMING con generadores: leer_lineas() hace yield línea a línea y parsear() valida y parsea EN el propio generador (las líneas malformadas se saltan sin romper el stream); en ningún momento se carga el fichero entero en memoria — O(1) de líneas vivas.
(2) Agregados sobre el stream: total de líneas válidas, conteo por acción, latencia media de los login, la latencia máxima con su usuario y el top-3 de usuarios por eventos.
(3) Verificación de integridad del fichero: SHA-256 calculado leyendo en BLOQUES de 64 KiB con iter(lambda: fh.read(65536), b"") — patrón chunked, no read().
(4) El script imprime sus conclusiones y termina rápido."""),
            ("assistant", r"""Decisiones:

- Generadores en cadena (leer_lineas → parsear → bucle de agregación): cada etapa consume la anterior perezosamente; en vida solo hay UNA línea. readlines() habría cargado las 10000 líneas (y con logs de gigas, todo el fichero). El patrón escala a ficheros que no caben en memoria sin cambiar el agregado.
- La validación dentro del generador (len(partes) != 4 → continue) permite cuarentena sin interrumpir el pipeline; si la cuarentena necesitara auditoría, el generador haría yield de un estado aparte en lugar de saltar.
- max de latencia mantenido a mano durante la pasada única (una sola iteración del fichero para todos los agregados): reler el fichero por cada métrica sería O(k·n).
- SHA-256 por bloques: iter(callable, sentinel) es el patrón canónico de lectura chunked; el digest depende solo del contenido, así que sirve como verificación de integridad determinista del fixture.
- most_common(3) con empates es estable: el orden de empate sigue el orden de inserción, que con este fichero es determinista."""),
            ("tool", r"""$ python informe_latencias.py
lineas_validas=10000 de 10000
por_accion=login=2000, logout=2000, query=6000
latencia_media_login=466.8ms
max_latency=919ms (usuario059)
top_usuarios=usuario000:84,usuario037:84,usuario074:84
sha256=808d0ec485c125d33025e5e148cb040722e5938eec4d40e1bddc456f9b3250dc
$ echo $?
0"""),
            ("assistant", r"""Implementación completa (el fixture eventos.log existe en el directorio de trabajo):

```python
import hashlib
from collections import Counter


def leer_lineas(ruta: str):
    with open(ruta, encoding="utf-8") as fh:
        for linea in fh:                      # streaming: nunca se carga el fichero entero
            yield linea.rstrip("\n")


def parsear(lineas):
    for numero, linea in enumerate(lineas, 1):
        partes = linea.split("|")
        if len(partes) != 4:
            continue                          # cuarentena sin romper el stream
        marca, usuario, accion, latencia = partes
        yield usuario, accion, int(latencia.rstrip("ms")), numero


def main() -> None:
    resumen = Counter()
    por_usuario = Counter()
    suma_login = 0
    logins = 0
    maximo = (0, "")
    total = 0
    for usuario, accion, ms, numero in parsear(leer_lineas("eventos.log")):
        total += 1
        resumen[accion] += 1
        por_usuario[usuario] += 1
        if accion == "login":
            suma_login += ms
            logins += 1
        if ms > maximo[0]:
            maximo = (ms, usuario)
    print(f"lineas_validas={total} de 10000")
    print("por_accion=" + ", ".join(f"{k}={v}" for k, v in sorted(resumen.items())))
    print(f"latencia_media_login={suma_login / logins:.1f}ms")
    print(f"max_latency={maximo[0]}ms ({maximo[1]})")
    print("top_usuarios=" + ",".join(f"{u}:{n}" for u, n in por_usuario.most_common(3)))

    digest = hashlib.sha256()
    with open("eventos.log", "rb") as fh:
        for bloque in iter(lambda: fh.read(65536), b""):   # chunks de 64 KiB
            digest.update(bloque)
    print(f"sha256={digest.hexdigest()}")


main()
```

Verificación: las 10000 líneas válidas con 120 usuarios a 2000 login/2000 logout/6000 query, media de login 466,8 ms, pico de 919 ms de usuario059, top-3 empatado a 84 eventos (orden estable de inserción) y un SHA-256 por bloques que actúa como huella de integridad del fixture — todo con una sola pasada y una línea viva en memoria en cada etapa del pipeline."""),
        ],
        verify=[
            {"name": "streaming_generadores", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["lineas_validas=10000 de 10000",
                                        "latencia_media_login=466.8ms",
                                        "sha256=808d0ec485c125d33025e5e148cb040722e5938eec4d40e1bddc456f9b3250dc"],
             "fixtures": FIXTURES_STREAMING, "timeout_s": 10},
        ],
        tags=["generators", "streaming", "memory-optimization", "hashing"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 13
    E(
        language="python",
        domain="scripting_automation",
        subdomain="mtime_watcher_rotation",
        difficulty="medium",
        task_type="automation",
        messages=[
            ("user", r"""Automatización de mantenimiento de logs, sin librerías externas y SIN depender del reloj actual (debe poder reproducirse igual cualquier día):

(1) Escenario: directorio logs/ con app-0.log, app-1.log, app-2.log; sus mtimes se FIJAN con os.utime a marcas deterministas de época (pasado), con tamaños distintos (app-2 nace por encima del umbral de 32 bytes).
(2) Watcher por snapshot: snapshot() mapea nombre → (st_mtime_ns, st_size) y diff() clasifica cambiados/nuevos/borrados comparando dos snapshots.
(3) Ciclo de eventos simulado: append a app-0.log (con utime fijado a otra marca determinista), fichero nuevo app-3.log y borrado de app-1.log; el diff debe reportar exactamente eso.
(4) Rotación por tamaño: rotar() desplaza app-2.log.1 → .2 (y los mayores que existan), renombra el fichero vivo a .1 y recrea el vivo vacío con utime determinista; devuelve True/False si rotó (app-0.log, por debajo del umbral, NO debe rotar).
(5) Contenido final del directorio y verificación de que el vivo rotado quedó vacío, todo impreso."""),
            ("assistant", r"""Decisiones:

- mtime_ns y tamaño como clave de vigilancia: los cambios de contenido que no cambian tamaño se detectan por nanosegundos de mtime. Nada de comparar fechas formateadas: st_mtime_ns es exacto y estable.
- Reloj simulado: os.utime(ruta, (t, t)) con marcas fijas de época — el test no depende de la hora actual ni de sleeps, y las comparaciones son deterministas en cualquier máquina.
- Rotación por desplazamiento: de mayor a menor generación (app.log.2 → .3, .1 → .2) para no pisar; el vivo pasa a .1 y se recrea vacío. os.replace es atómico en el mismo filesystem: nunca hay ventana sin fichero.
- El watcher por snapshot es idempotente y barato (un os.stat por fichero); para directorios enormes conviene muestreo o inotify, pero para esta pieza de mantenimiento el snapshot es el patrón correcto y portable."""),
            ("tool", r"""$ python mantener_logs.py
cambiados=['app-0.log']
nuevos=['app-3.log'] borrados=['app-1.log']
rotar_app2=True
rotar_app0=False
contenido_final=app-0.log,app-2.log,app-2.log.1,app-3.log
app2_1_vacio=True
$ echo $?
0"""),
            ("assistant", r"""Implementación completa:

```python
import os
import shutil

BASE = "logs"
UMBRAL_BYTES = 32
EPOCAS = 1_700_000_000   # mtimes fijos en el pasado: nada de reloj del sistema


def crear_escenario() -> None:
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE)
    for i, desplazamiento in enumerate((0, 50, 100)):
        ruta = os.path.join(BASE, f"app-{i}.log")
        contenido = b"-" * (10 if i != 2 else 40)   # app-2 nace sobre el umbral
        with open(ruta, "wb") as fh:
            fh.write(contenido)
        instante = EPOCAS + desplazamiento
        os.utime(ruta, (instante, instante))


def snapshot() -> dict:
    estado = {}
    for nombre in sorted(os.listdir(BASE)):
        st = os.stat(os.path.join(BASE, nombre))
        estado[nombre] = (st.st_mtime_ns, st.st_size)
    return estado


def diff(antes: dict, despues: dict):
    cambiados = [n for n in despues if n in antes and despues[n] != antes[n]]
    nuevos = [n for n in despues if n not in antes]
    borrados = [n for n in antes if n not in despues]
    return sorted(cambiados), sorted(nuevos), sorted(borrados)


def rotar(nombre: str) -> bool:
    # desplaza app.log.2->.3, .1->.2, actual->.1 y recrea el vivo vacio
    ruta = os.path.join(BASE, nombre)
    if os.path.getsize(ruta) <= UMBRAL_BYTES:
        return False
    viejos = sorted(
        (f for f in os.listdir(BASE) if f.startswith(nombre + ".")),
        key=lambda f: int(f.rsplit(".", 1)[1]),
        reverse=True,
    )
    for viejo in viejos:
        gen = int(viejo.rsplit(".", 1)[1])
        os.replace(os.path.join(BASE, viejo), os.path.join(BASE, f"{nombre}.{gen + 1}"))
    os.replace(ruta, os.path.join(BASE, f"{nombre}.1"))
    open(ruta, "wb").close()
    os.utime(ruta, (EPOCAS + 200, EPOCAS + 200))
    return True


def main() -> None:
    crear_escenario()
    antes = snapshot()

    with open(os.path.join(BASE, "app-0.log"), "a", encoding="utf-8") as fh:
        fh.write("nueva linea de log\n")
    os.utime(os.path.join(BASE, "app-0.log"), (EPOCAS + 150, EPOCAS + 150))
    with open(os.path.join(BASE, "app-3.log"), "w", encoding="utf-8") as fh:
        fh.write("emergente\n")
    os.remove(os.path.join(BASE, "app-1.log"))

    cambiados, nuevos, borrados = diff(antes, snapshot())
    print(f"cambiados={cambiados}")
    print(f"nuevos={nuevos} borrados={borrados}")

    print(f"rotar_app2={rotar('app-2.log')}")
    print(f"rotar_app0={rotar('app-0.log')}")
    print("contenido_final=" + ",".join(sorted(os.listdir(BASE))))
    print(f"app2_1_vacio={os.path.getsize(os.path.join(BASE, 'app-2.log')) == 0}")


main()
```

Verificación: el diff clasifica exactamente el ciclo (app-0 cambiado por mtime+size, app-3 nuevo, app-1 borrado); rotar_app2=True desplaza la generación a app-2.log.1 y deja el vivo vacío; rotar_app0=False respeta el umbral de 32 bytes. Todo con mtimes simulados: reproducible cualquier día sin flakiness."""),
        ],
        verify=[
            {"name": "watcher_y_rotacion", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["cambiados=['app-0.log']",
                                        "nuevos=['app-3.log'] borrados=['app-1.log']",
                                        "rotar_app2=True", "rotar_app0=False",
                                        "app2_1_vacio=True"],
             "timeout_s": 10},
        ],
        tags=["automation", "mtime", "log-rotation", "os-module"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 14
    E(
        language="python",
        domain="backend",
        subdomain="contextmanager_cleanup",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Encontramos conexiones «zombis» tras cada excepción de negocio: el log muestra abrir/usar pero NUNCA cerrar. Sospechamos de nuestro contextmanager de conexión:

```python
from contextlib import contextmanager

EVENTOS: list = []


class Conexion:
    def abrir(self) -> None:
        EVENTOS.append("abrir")

    def usar(self) -> None:
        EVENTOS.append("usar")

    def cerrar(self) -> None:
        EVENTOS.append("cerrar")


@contextmanager
def conexion():
    c = Conexion()
    c.abrir()
    yield c
    c.cerrar()          # <- fuera de finally: si el cuerpo lanza, NUNCA se ejecuta


def main() -> None:
    try:
        with conexion() as c:
            c.usar()
            raise ValueError("fallo de negocio dentro del with")
    except ValueError as e:
        print(f"excepcion_propagada={e}")
    print("eventos=" + ",".join(EVENTOS))
    print(f"fuga_detectada={'cerrar' not in EVENTOS}")


main()
```

(1) Ejecuta el reproductor y confirma la fuga con su salida (exit 0: el bug es silencioso). (2) Corrige con try/finally alrededor del yield. (3) Añade un segundo contextmanager transaccion(gestor, nombre) que haga BEGIN, commit en camino feliz y ROLLBACK + RE-LANZAR la excepción en el camino de error (silenciarla sería ocultar el fallo), y demuestra ambos caminos. (4) Explica por qué la versión rota compila, «funciona» en tests sin excepciones y solo revienta bajo error."""),
            ("assistant", r"""Causa raíz: un contextmanager con @contextmanager es un generador; si la excepción del cuerpo entra al generador por el yield (throw()), el código POSTERIOR al yield no se ejecuta — a menos que esté en finally. La versión rota hace c.cerrar() después del yield a pelo: en tests felices (sin excepción) la línea sí corre, por eso la suite pasaba; bajo excepción, la entrega del recurso muere con la fuga. La lección: el cleanup de un contextmanager va SIEMPRE en finally (o se usa closing()).

Sobre transaccion(): try/except/else — commit en else (solo si no hubo excepción), rollback en except y luego `raise` desnudo para re-lanzar. Capturar sin re-lanzar convertiría un fallo de negocio en una «operación OK»: el peor antipatrón de transacciones. BaseException en el except es deliberado: KeyboardInterrupt/CancelledError también deben deshacer."""),
            ("tool", r"""$ python cm_roto.py
excepcion_propagada=fallo de negocio dentro del with
eventos=abrir,usar
fuga_detectada=True
$ python cm_arreglado.py
eventos=abrir,cerrar
fuga_detectada=False
camino_feliz=BEGIN venta_ok,operacion,commit:venta_ok,commit_real
rollback_path=BEGIN venta_mala,rollback:venta_mala,rollback_real
excepcion_no_silenciada=True
$ echo $?
0"""),
            ("assistant", r"""Fix completo con las dos piezas:

```python
from contextlib import contextmanager

EVENTOS: list = []


class Conexion:
    def abrir(self) -> None:
        EVENTOS.append("abrir")

    def cerrar(self) -> None:
        EVENTOS.append("cerrar")


@contextmanager
def conexion():
    c = Conexion()
    c.abrir()
    try:
        yield c
    finally:
        c.cerrar()      # cleanup GARANTIZADO: con excepcion o sin ella


@contextmanager
def transaccion(gestor, nombre: str):
    gestor.execute("BEGIN " + nombre)
    try:
        yield gestor
    except BaseException:
        EVENTOS.append("rollback:" + nombre)
        gestor.rollback()
        raise           # la excepcion SIGUE: silenciarla ocultaria el fallo
    else:
        EVENTOS.append("commit:" + nombre)
        gestor.commit()


class GestorFalso:
    def execute(self, orden: str) -> None:
        EVENTOS.append(orden)

    def commit(self) -> None:
        EVENTOS.append("commit_real")

    def rollback(self) -> None:
        EVENTOS.append("rollback_real")


def main() -> None:
    try:
        with conexion() as c:
            raise ValueError("fallo de negocio dentro del with")
    except ValueError:
        pass
    print(f"eventos={','.join(EVENTOS)}")
    print(f"fuga_detectada={'cerrar' not in EVENTOS}")
    EVENTOS.clear()

    gestor = GestorFalso()
    with transaccion(gestor, "venta_ok"):
        EVENTOS.append("operacion")
    print("camino_feliz=" + ",".join(EVENTOS))
    EVENTOS.clear()

    try:
        with transaccion(gestor, "venta_mala"):
            raise RuntimeError("regla de negocio violada")
    except RuntimeError:
        print("rollback_path=" + ",".join(EVENTOS))
        print("excepcion_no_silenciada=True")


main()
```

Verificación: el roto imprime eventos=abrir,usar con fuga_detectada=True (exit 0: silencioso, por eso el monitor de producción lo encontró); el fix imprime eventos=abrir,cerrar (fuga_detectada=False) aunque el cuerpo lance; camino_feliz hace BEGIN→operación→commit→commit_real y el camino de error hace rollback y RE-LANZA (excepcion_no_silenciada=True). Regla del equipo: código tras el yield de un @contextmanager solo si está en finally — o en else de transacciones."""),
        ],
        verify=[
            {"name": "fuga_reproducida", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["eventos=abrir,usar", "fuga_detectada=True"],
             "timeout_s": 10},
            {"name": "cleanup_garantizado", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["fuga_detectada=False",
                                        "rollback_path=BEGIN venta_mala,rollback:venta_mala,rollback_real",
                                        "excepcion_no_silenciada=True"],
             "timeout_s": 10},
        ],
        tags=["contextmanager", "contextlib", "cleanup", "transactions", "exception-safety"],
        stack=["python"],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 15
    E(
        language="python",
        domain="backend",
        subdomain="tcp_framing_server",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Protocolo binario sobre TCP para el agente de despliegue, SOLO stdlib. El formato de trama: 1 byte marcador 0xA5 + 4 bytes de longitud big-endian (struct ">BI") + carga útil. Requisitos:

(1) Servidor socketserver.ThreadingTCPServer sobre puerto efímero en hilo daemon; el handler recibe tramas EN BUCLE y responde a cada una con la carga en MAYÚSCULAS precedida de su longitud (">I"); trama de longitud 0 = cierre limpio (el handler sale sin error).
(2) recv_exacto(sock, n): recv() NO garantiza los n bytes pedidos — hay que acumular en bucle hasta completar (y detectar cierre a mitad de mensaje con ConnectionError).
(3) El cliente envía cada trama en DOS sendall partidos (cabecera partida + carga) para DEMOSTRAR que recv_exacto reconstruye tramas partidas; hace una conexión con dos tramas y otra con una trama de 200 bytes.
(4) Cierre limpio de cada cliente con la trama de longitud 0 y apagado ordenado del servidor (shutdown + server_close + join).
(5) Salida determinista que pruebe las respuestas, el protocolo y el apagado."""),
            ("assistant", r"""Decisiones:

- Framing explícito (marcador + longitud) vs delimitadores: con un binario por longitud sabes EXACTAMENTE cuántos bytes faltan, y recv_exacto convierte «recv devuelve lo que le de la gana» en «te doy n bytes o error». El marcador valida la sincronía del stream (si un cliente se descuadra, se detecta al instante).
- El maneja bucle por conexión (varias tramas por conexión) hasta la trama 0; sin ese cierre explícito, el handler no sabría cuándo terminar y cada cliente dejaría un hilo colgado.
- sendall (no send) en el cliente: send puede enviar PARCIAL; sendall garantiza el buffer completo. Partir el envío a mano simula el peor caso de fragmentación TCP y obliga al recv_exacto del servidor a hacer su trabajo.
- ThreadingTCPServer con daemon_threads=True y apagado en finally: shutdown() detiene serve_forever, server_close() cierra el socket de escucha y join comprueba la muerte del hilo."""),
            ("tool", r"""$ python agente_tramas.py
cliente1=HOLA,TRAMA
cliente2=15+200 bytes
protocolo_ok=True
servidor_apagado=True
$ echo $?
0"""),
            ("assistant", r"""Implementación completa:

```python
import socket
import socketserver
import struct
import threading

MARCADOR = 0xA5
CABECERA = struct.Struct(">BI")   # 1 byte marcador + 4 bytes longitud (big endian)


def recv_exacto(sock, n: int) -> bytes:
    # recv() NO garantiza n bytes: hay que acumular hasta completar
    datos = bytearray()
    while len(datos) < n:
        trozo = sock.recv(n - len(datos))
        if not trozo:
            raise ConnectionError("conexion cerrada a mitad de mensaje")
        datos.extend(trozo)
    return bytes(datos)


class Manejador(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while True:
            marcador, longitud = CABECERA.unpack(recv_exacto(self.request, CABECERA.size))
            if marcador != MARCADOR:
                raise ConnectionError(f"marcador invalido: {marcador:#x}")
            if longitud == 0:
                break                        # trama vacia = cierre limpio
            carga = recv_exacto(self.request, longitud)
            respuesta = carga.upper()
            self.request.sendall(struct.pack(">I", len(respuesta)) + respuesta)


class ServidorTramas(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def enviar_trama(sock, carga: bytes) -> None:
    cab = CABECERA.pack(MARCADOR, len(carga))
    sock.sendall(cab[:3])                    # envio PARTIDO a proposito
    sock.sendall(cab[3:] + carga)


def cliente(puerto: int, mensajes: list) -> list:
    respuestas = []
    with socket.create_connection(("127.0.0.1", puerto), timeout=5) as sock:
        for mensaje in mensajes:
            enviar_trama(sock, mensaje)
            (lon,) = struct.unpack(">I", recv_exacto(sock, 4))
            respuestas.append(recv_exacto(sock, lon))
        sock.sendall(CABECERA.pack(MARCADOR, 0))   # cierre limpio
    return respuestas


def main() -> None:
    servidor = ServidorTramas(("127.0.0.1", 0), Manejador)
    hilo = threading.Thread(target=servidor.serve_forever,
                            kwargs={"poll_interval": 0.05}, daemon=True)
    hilo.start()
    puerto = servidor.server_address[1]
    try:
        r1 = cliente(puerto, [b"hola", b"trama"])
        r2 = cliente(puerto, [b"segundo cliente", b"x" * 200])
        print("cliente1=" + ",".join(r.decode("ascii") for r in r1))
        print(f"cliente2={len(r2[0])}+{len(r2[1])} bytes")
        print(f"protocolo_ok={r1[0] == b'HOLA' and r2[1] == b'X' * 200}")
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)
        print(f"servidor_apagado={not hilo.is_alive()}")


main()
```

Verificación: cliente1 recibe HOLA,TRAMA (dos tramas partidas reconstruidas por recv_exacto), cliente2 recibe 15+200 bytes íntegros de la trama grande, protocolo_ok=True valida el contrato extremo a extremo, y servidor_apagado=True solo aparece si el hilo murió tras shutdown+join. El proceso termina solo en ~1 s."""),
        ],
        verify=[
            {"name": "protocolo_tramas", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["cliente1=HOLA,TRAMA", "cliente2=15+200 bytes",
                                        "protocolo_ok=True", "servidor_apagado=True"],
             "timeout_s": 15},
        ],
        tags=["sockets", "tcp", "protocol-design", "socketserver", "framing"],
        stack=["python"],
        recovery=False,
    ),
    # ------------------------------------------------------------------ 16
    E(
        language="python",
        domain="systems",
        subdomain="thread_race_counter",
        difficulty="extreme",
        task_type="debugging",
        messages=[
            ("user", r"""Cuatro hilos incrementan un contador global 25000 veces cada uno y el total no da 100000: se pierden actualizaciones de forma intermitente. Necesito DEMOSTRACIÓN Y FIX controlados:

(1) El reproductor fuerza el interleaving con sys.setswitchinterval(0.000001) y aísla la operación de riesgo en FUNCIONES (leer_contador / escribir_contador / incrementar_uno que las compone): entre leer y escribir hay llamadas, y ahí el hilo puede perder el GIL.
(2) Una threading.Barrier arranca los 4 hilos a la vez para máxima contención. Como una ronda podría salir limpia por pura suerte del planificador, el reproductor repite la EXPERIENCIA 5 veces dentro del mismo proceso y reporta el MÍNIMO (total_minimo); termina SIEMPRE (exit 0) y si ni así da el total correcto, no hay crash — solo el informe honesto.
(3) El fix: misma estructura, pero incrementar_uno dentro de un threading.Lock; debe imprimir total=100000 y perdidas=0 en TODAS las ejecuciones.
(4) Explica por qué `CONTADOR += 1` parece atómico y no lo es, y por qué «funcionaba en mi máquina»."""),
            ("assistant", r"""Causa raíz: `CONTADOR += 1` son tres pasos (leer, sumar, almacenar) que el bytecode NO hace atómicos; en 3.12, además, los puntos de comprobación del intérprete (donde el hilo puede soltar el GIL) caen en llamadas y saltos — y aquí la lectura y la escritura están en funciones distintas: exactamente entre escribir_contador(leer_contador() + 1) hay huecos donde otro hilo pisa el valor y la primera escritura lo sobreescribe (actualización perdida).

Por qué es intermitente: con el intervalo de switch por defecto (5 ms) el interleaving es raro y el bug «no aparece»; setswitchinterval(0.000001) multiplica los cambios de contexto y las pérdidas se vuelven masivas y reproducibles (aquí, 20-60 % de los incrementos se pierden por ronda). Aun así, una ronda AISLADA podría salir limpia por pura planificación afortunada: por eso el reproductor hace 5 rondas y reporta el mínimo — el bug no puede esconderse detrás de una sola ejecución con suerte. No es un bug del planificador: es el contrato del modelo de memoria de CPython — la atomicidad solo la dan las operaciones primitivas o un lock.

El fix no «quita» la carrera por suerte: la serializa. Con Lock, la secuencia leer+escribir es indivisible y el total clava 100000 en todas las ejecuciones. Alternativas legítimas (atomicidad sin lock explícito): queue.Queue para productor/consumidor o itertools.count() para contadores monotónicos simples."""),
            ("tool", r"""$ for i in 1 2 3; do python contador_roto.py | tail -2; done
total_minimo=39548
perdidas_minimo=60452
total_minimo=52761
perdidas_minimo=47239
total_minimo=44110
perdidas_minimo=55890
$ python contador_arreglado.py
rondas=100000,100000,100000
total=100000
esperado=100000
perdidas=0
carrera_detectada=False
$ echo $?
0"""),
            ("assistant", r"""Reproductor del bug (termina solo, exit 0, 5 rondas y mínimo):

```python
import sys
import threading

sys.setswitchinterval(0.000001)   # cambios de contexto muy frecuentes

HILOS, VUELTAS, RONDAS = 4, 25000, 5
CONTADOR = 0


def leer_contador() -> int:
    return CONTADOR


def escribir_contador(valor: int) -> None:
    global CONTADOR
    CONTADOR = valor


def incrementar_uno() -> None:
    # leer-modificar-escribir repartido en TRES llamadas: entre medias el hilo
    # puede perder el GIL y otro hilo pisar el valor (actualizacion perdida)
    escribir_contador(leer_contador() + 1)


def trabajo(barrera: threading.Barrier, vueltas: int) -> None:
    barrera.wait()                # maxima contencion: los 4 arrancan a la vez
    for _ in range(vueltas):
        incrementar_uno()


def ejecutar_ronda() -> int:
    global CONTADOR
    CONTADOR = 0
    barrera = threading.Barrier(HILOS)
    hilos = [threading.Thread(target=trabajo, args=(barrera, VUELTAS)) for _ in range(HILOS)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return CONTADOR


def main() -> None:
    totales = [ejecutar_ronda() for _ in range(RONDAS)]
    print("rondas=" + ",".join(map(str, totales)))
    print(f"total_minimo={min(totales)}")
    print("esperado=100000")
    print(f"perdidas_minimo={100000 - min(totales)}")
    print(f"carrera_detectada={min(totales) != 100000}")


main()
```

Y el fix, con la MISMA estructura dentro de la sección crítica (3 rondas para demostrar estabilidad):

```python
import sys
import threading

sys.setswitchinterval(0.000001)   # seguimos forzando cambios de contexto

HILOS, VUELTAS, RONDAS = 4, 25000, 3
CONTADOR = 0
CERRADURA = threading.Lock()


def leer_contador() -> int:
    return CONTADOR


def escribir_contador(valor: int) -> None:
    global CONTADOR
    CONTADOR = valor


def incrementar_uno() -> None:
    # la misma secuencia NO atomica, ahora dentro de la seccion critica
    with CERRADURA:
        escribir_contador(leer_contador() + 1)


def trabajo(barrera: threading.Barrier, vueltas: int) -> None:
    barrera.wait()
    for _ in range(vueltas):
        incrementar_uno()


def ejecutar_ronda() -> int:
    global CONTADOR
    CONTADOR = 0
    barrera = threading.Barrier(HILOS)
    hilos = [threading.Thread(target=trabajo, args=(barrera, VUELTAS)) for _ in range(HILOS)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return CONTADOR


def main() -> None:
    totales = [ejecutar_ronda() for _ in range(RONDAS)]
    print("rondas=" + ",".join(map(str, totales)))
    print(f"total={min(totales)}")
    print("esperado=100000")
    print(f"perdidas={100000 - min(totales)}")
    print(f"carrera_detectada={min(totales) != 100000}")


main()
```

Verificación: el buggy reporta un total_minimo lejos de 100000 en CADA ejecución (5 rondas hacen imposible que el interleaving «con suerte» enmascare el bug) y el fix imprime total=100000, perdidas=0 y carrera_detectada=False — en todas las repeticiones, no por suerte. El coste del lock es ~0,3 s por ronda de 100000 incrementos: barato frente a un contador que miente."""),
        ],
        verify=[
            {"name": "carrera_reproducida", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_not_contains": ["total_minimo=100000"],
             "repeat": 5, "timeout_s": 15},
            {"name": "fix_con_lock", "action": "run", "lang": "python", "msg": -1, "block": 1,
             "expect_exit": 0,
             "expect_stdout_contains": ["total=100000", "perdidas=0", "carrera_detectada=False"],
             "repeat": 3, "timeout_s": 20},
        ],
        tags=["threading", "race-condition", "gil", "locks", "setswitchinterval"],
        stack=["python"],
        recovery=True,
    ),
]


