"""
m_review_arch.py — Módulo 2-f del dataset AI-ku_programming (Stack V2).

40 ejemplos de:
  * CODE REVIEW (12): código realista con problemas sembrados; el assistant
    distingue explícitamente bug demostrado (con ejecución o razonamiento
    preciso) de preferencia estilística. python(6)/javascript(2)/c/cpp/java/php.
  * SEGURIDAD DEFENSIVA (10): análisis y corrección de código vulnerable en
    contexto de laboratorio, con verificación por ejecución (SQLi, XSS, path
    traversal, pickle, CSRF, secretos, SSRF, permisos, aislamiento tenant,
    inyección de comandos).
  * ARQUITECTURA Y DISEÑO (10): decisiones con trade-offs comparados, 3 ADRs
    estructurados y rechazo explícito de sobre-ingeniería (estáticos).
  * PERFORMANCE (4): N+1, complejidad, concatenación de strings, índices SQL.
  * TESTING (4): suites unittest / node:assert sobre funciones proporcionadas.

Contenido en español (identificadores en inglés). Sin secretos reales.
"""

from schema import E

EXAMPLES = [

    # =====================================================================
    # CODE REVIEW (12) — python(6), javascript(2), c(1), cpp(1), java(1), php(1)
    # =====================================================================

    # CR1 — python fintech: review multi-issue (extreme)
    E(
        language="python", domain="backend", subdomain="revision_lotes_pagos",
        difficulty="extreme", task_type="code_review",
        messages=[
            ("user", r"""Revisión de código previa a fusión: `pagos.py` del servicio de cobros (fintech B2B, lotes diarios de ~5.000 transacciones). El contrato de negocio dice:

- Tramos de comisión: hasta 100,00 € **incluido** → 1,50 %; hasta 1.000,00 € incluido → 1,10 %; resto → 0,80 %.
- El fichero de auditoría debe ser JSON Lines: una línea JSON por lote.
- Los importes se informan con 2 decimales exactos (es dinero).

```python
# pagos.py — procesamiento de lotes de transacciones (v1.3)
import json

TARIFAS = [
    (100.0, 150),      # hasta 100 euros: 1,50 %
    (1000.0, 110),     # hasta 1000 euros: 1,10 %
    (None, 80),        # resto: 0,80 %
]

def comision(monto):
    for limite, bp in TARIFAS:
        if limite is None or monto < limite:
            return monto * bp / 10000
    return 0.0

def procesar_lote(ruta, audit=None):
    f = open(ruta)
    lineas = f.readlines()[1:]        # la primera linea es la cabecera
    f.close()
    aprobadas = []
    for i in range(len(lineas)):
        campos = lineas[i].strip().split(";")
        monto = float(campos[1])
        if monto <= 0:
            continue
        aprobadas.append({
            "id": campos[0],
            "monto": monto,
            "comision": round(comision(monto), 2),
        })
    if audit is not None:
        fh = open(audit, "a")
        fh.write(json.dumps(aprobadas))
        fh.close()
    return aprobadas

def total_neto(transacciones):
    total = 0.0
    for t in transacciones:
        total += t["monto"] - t["comision"]
    return round(total, 2)
```

Encuentra los problemas reales, priorízalos por severidad y di explícitamente cuáles son bugs demostrables y cuáles solo preferencias de estilo."""),
            ("assistant", r"""Revisión priorizada por severidad. Marco cada punto como **BUG** (semántica incorrecta demostrable) o **ESTILO** (no cambia el comportamiento).

**S1 — BUG crítico (negocio): frontera de tramo con `<` en vez de `<=`.** El contrato dice «hasta 100,00 € incluido → 1,50 %», pero `monto < limite` manda un pago de exactamente 100,00 € al tramo de 1,10 %. Comprobación inmediata: `comision(100.0)` devuelve `1.1` (ver salida abajo). Error sistemático de 0,40 € por transacción en la frontera, y en auditoría aparece como tarifa aplicada distinta a la contractual.

**S2 — BUG alto (recurso): `open`/`close` manuales sin `with`.** Si `float(campos[1])` lanza `ValueError` en una línea malformada (pasa cada vez que el ERP exporta mal un separador), el fichero queda abierto: en un worker de larga vida los descriptores se acumulan hasta el `OSError: Too many open files`. Mismo patrón en el `open(audit, "a")`. No es estilo: es un fallo de recurso con path de ejecución concreto.

**S3 — BUG alto (formato de auditoría): JSON Lines roto.** `fh.write(json.dumps(aprobadas))` no escribe salto de línea. El segundo lote se concatena al primero: `json.loads` sobre el fichero falla con «Extra data». El requisito dice JSON Lines explícitamente.

**S4 — BUG medio: dinero en `float` + `round()` del banker.** `0.1 + 0.1 + 0.1 != 0.3` (se demuestra abajo) y `round(2.675, 2)` da `2.67`, no `2.68`: el redondeo de Python es half-to-even y opera sobre la representación binaria. Para dinero: `Decimal` con política de redondeo explícita, o céntimos enteros.

**S5 — ESTILO (no bloqueante): `for i in range(len(lineas))`.** Iterar directamente con `for linea in lineas` es equivalente; un linter lo arregla y no corregirlo no rompe nada. Lo menciono para separarlo de los S1-S4.

**S6 — Diseño/deuda (medio): `procesar_lote` mezcla parseo, cálculo y persistencia.** No es testeable unitariamente sin ficheros reales; cada cambio de `TARIFAS` exige una prueba de integración. Separar `parsear_lote()` / `calcular_comision()` / `escribir_auditoria()` cuesta ~30 minutos y elimina la clase entera de tests con fixtures de fichero.

Versión corregida (v1.4) que resuelve S1-S4:

```python
# pagos.py — procesamiento de lotes de transacciones (v1.4)
import json
from decimal import Decimal, ROUND_HALF_UP

TARIFAS = [
    (Decimal("100.00"), Decimal("0.0150")),
    (Decimal("1000.00"), Decimal("0.0110")),
    (None, Decimal("0.0080")),
]

def comision(monto: Decimal) -> Decimal:
    if monto <= 0:
        raise ValueError("monto no positivo")
    for limite, tasa in TARIFAS:
        if limite is None or monto <= limite:
            return (monto * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    raise AssertionError("tarifa no encontrada")

def parsear_lote(lineas):
    for linea in lineas[1:]:
        campos = linea.strip().split(";")
        yield campos[0], Decimal(campos[1])

def procesar_lote(ruta, audit=None):
    with open(ruta, encoding="utf-8") as f:        # with: sin fugas ante excepciones
        aprobadas = [
            {"id": pid, "monto": str(monto), "comision": str(comision(monto))}
            for pid, monto in parsear_lote(f) if monto > 0
        ]
    if audit is not None:
        with open(audit, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(aprobadas) + "\n")  # JSON Lines real
    return aprobadas
```

Verificación de S1, S3 y S4 por ejecución en el bloque final (S2 se corrige con `with`; su repro es un `ValueError` a mitad de lote, no hace falta un script aparte para razonarlo)."""),
            ("tool", r"""$ python -c "from pagos import comision; print(comision(100.0), comision(99.99))"
1.1 1.4985
$ python - <<'PY'
import json
lote1 = json.dumps([{"id": "T-1"}]); lote2 = json.dumps([{"id": "T-2"}])
open("audit.jsonl", "a").write(lote1 + lote2)   # como v1.3
json.loads(open("audit.jsonl").read())
PY
Traceback (most recent call last):
  json.decoder.JSONDecodeError: Extra data: line 1 column 15 (char 14)"""),
            ("assistant", r"""Confirmado lo esperado: la frontera cobra 1,10 % y la auditoría de v1.3 es JSON roto. Bloque de verificación autocontenido (bug original embebido + fix) para que CI lo ejecute:

```python
from decimal import Decimal, ROUND_HALF_UP
import json

# --- v1.3 original (reducida a la funcion implicada) ---
def comision_v13(monto):
    for limite, bp in [(100.0, 150), (1000.0, 110), (None, 80)]:
        if limite is None or monto < limite:
            return monto * bp / 10000
    return 0.0

# --- v1.4 corregida ---
TARIFAS = [
    (Decimal("100.00"), Decimal("0.0150")),
    (Decimal("1000.00"), Decimal("0.0110")),
    (None, Decimal("0.0080")),
]

def comision(monto):
    if monto <= 0:
        raise ValueError("monto no positivo")
    for limite, tasa in TARIFAS:
        if limite is None or monto <= limite:
            return (monto * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    raise AssertionError("tarifa no encontrada")

v13 = comision_v13(100.0)
v14 = comision(Decimal("100.00"))
print(f"BUG frontera: v1.3 cobra {v13} en 100.00; el contrato exige 1.50")
assert abs(v13 - 1.1) < 1e-9 and v14 == Decimal("1.50")

print(f"BUG dinero: 0.1+0.1+0.1 = {0.1 + 0.1 + 0.1!r} con float; Decimal: {Decimal('0.1') * 3}")
assert 0.1 + 0.1 + 0.1 != 0.3 and Decimal("0.1") * 3 == Decimal("0.3")

lote1 = [{"id": "T-001", "monto": "50.00", "comision": "0.75"}]
lote2 = [{"id": "T-002", "monto": "80.00", "comision": "0.88"}]
sin_salto = json.dumps(lote1) + json.dumps(lote2)      # lo que producía v1.3
jsonl = json.dumps(lote1) + "\n" + json.dumps(lote2) + "\n"
try:
    json.loads(sin_salto)
    raise SystemExit("inesperado: la concatenacion parseó")
except json.JSONDecodeError:
    print("OK: auditoria JSON Lines valida lote a lote (v1.3 producía JSON roto)")
assert [json.loads(x) for x in jsonl.splitlines()] == [lote1, lote2]
print(f"OK: comision(100.01)={comision(Decimal('100.01'))} cae en el tramo 2 como manda el contrato")
```

Resumen accionable: aprobar el PR solo si van los S1-S4; el S5 se deja para el linter y el S6 se agenda como refactor propio (no mezclarlo en este PR, o la revisión del diff se vuelve imposible)."""),
        ],
        verify=[
            {"name": "bugs_y_fix_pagos", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0, "timeout_s": 15,
             "expect_stdout_contains": ["BUG frontera", "BUG dinero", "OK: auditoria", "OK: comision(100.01)"]},
        ],
        tags=["code-review", "fintech", "decimal", "recursos", "json-lines"],
        stack=["python"], recovery=False,
    ),

    # CR2 — python IoT: deadlock por lock sin try/finally (very_hard, recovery)
    E(
        language="python", domain="backend", subdomain="revision_deuda_duplicacion",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", r"""Revisad `planificador_rutas.py` del TMS de logística. Funciona desde 2021, pero cada cambio de tarifas se rompe algo en otro turno y el dashboard de «km nocturnos» lleva meses raro. El equipo pregunta dos cosas: qué corregir y **cuánto nos cuesta la deuda**.

```python
# planificador_rutas.py (v3.2) — asignación de repartos por turno
import math

TARIFA_KM = 0.45
RECARGO_NOCHE = 0.20

def distancia_ruta_morning(puntos):
    total = 0.0
    for i in range(len(puntos) - 1):
        (x1, y1) = puntos[i]
        (x2, y2) = puntos[i + 1]
        total += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2) * 111.32
    return total

def coste_turno_morning(pedidos):
    total = 0.0
    for p in pedidos:
        total += distancia_ruta_morning([p["origen"], p["destino"]]) * TARIFA_KM
    return total

def distancia_ruta_tarde(puntos):
    total = 0.0
    for i in range(len(puntos) - 1):
        (x1, y1) = puntos[i]
        (x2, y2) = puntos[i + 1]
        total += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2) * 111.32
    return total

def coste_turno_tarde(pedidos):
    total = 0.0
    for p in pedidos:
        total += distancia_ruta_tarde([p["origen"], p["destino"]]) * TARIFA_KM
    return total

def distancia_ruta_night(puntos):
    total = 0.0
    for i in range(len(puntos) - 1):
        (x1, y1) = puntos[i]
        (x2, y2) = puntos[i + 1]
        # recargo nocturno aplicado dentro del cálculo de distancia
        total += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2) * 111.32 * (1 + RECARGO_NOCHE)
    return total

def coste_turno_night(pedidos):
    total = 0.0
    for p in pedidos:
        total += distancia_ruta_night([p["origen"], p["destino"]]) * TARIFA_KM
    return total

def resumen_por_turno(pedidos):
    return {
        "morning": coste_turno_morning(pedidos),
        "tarde": coste_turno_tarde(pedidos),
        "night": coste_turno_night(pedidos),
    }
```"""),
            ("assistant", r"""**S1 — BUG alto (geodesia): las tres copias tratan lat/lon como un plano con factor único 111,32 km/grado.** El factor correcto para la componente E-O depende de la latitud (×cos φ). Con la fórmula plana, Madrid→Barcelona (≈505 km reales) sale ≈662 km: **+31 % de km estimados en rutas con tramo este-oeste**, lo que infla costes por turno y contratos a tarifa. Se demuestra con ejecución abajo. Corrección: haversine (o geodesia de Vincenty si necesitáis precisión sub-métrica, que aquí no hace falta).

**S2 — BUG medio ya materializado: la función `distancia_ruta_night` miente.** No devuelve una distancia: devuelve la distancia ×1,2 con el recargo nocturno dentro. Cualquier consumidor que la use como distancia (el dashboard de «km nocturnos» es el caso confirmado) pinta km inflados un 20 %. El recargo es una política de **precio**, no de **geometría**; debe vivir en el cálculo de coste, no en la medición.

**S3 — Deuda técnica cuantificada (lo que preguntabais):**
- 3 copias de la misma fórmula = 24 líneas donde 8 bastan; cada bug de geodesia existe ×3 (el S1 está triplicado).
- Cada cambio de `TARIFA_KM` o `RECARGO_NOCHE` exige tocar 3 puntos + re-test manual de 3 turnos: estimación honesta 1-2 h por cambio, con al menos un cambio/mes por campañas → ~12-24 h/año, más el incidente del dashboard ya pagado.
- Riesgo latente: las copias ya divergieron una vez (el recargo nocturno solo está en una). Divergencias silenciosas son las que acaban en litigios con transportistas.
Refactor: una `distancia_ruta(puntos, recargo=0.0)` + los tres turnos como parámetros. Coste del refactor: ~1 h incluyendo tests.

**S4 — ESTILO (no bloqueante): mezcla inglés/español en nombres** (`morning`/`tarde`/`night`) y `for i in range(len(...))` en vez de `zip(puntos, puntos[1:])`. No cambia comportamiento; se arregla de paso en el refactor.

Bloque de verificación con la comparación geodésica y el refactor propuesto abajo."""),
            ("tool", r"""$ python - <<'PY'
import math
def plana(a, b): return math.hypot(b[0]-a[0], b[1]-a[1]) * 111.32
MAD, BCN = (40.4168, -3.7038), (41.3874, 2.1686)
print(f"plana: {plana(MAD, BCN):.1f} km")
PY
plana: 662.6 km
$ python -c "from dashboard import km_nocturnos; print(km_nocturnos('2025-03'))"
3841.2   # informado como km; reales medidos por GPS: 3201.0"""),
            ("assistant", r"""El dashboard confirma el S2: 3.841 km informados frente a 3.201 reales (+20 %, exactamente el recargo metido en la distancia). Bloque de verificación autocontenido con bug + refactor:

```python
import math

def distancia_plana(lat1, lon1, lat2, lon2):
    return math.hypot(lat2 - lat1, lon2 - lon1) * 111.32

def distancia_haversine(lat1, lon1, lat2, lon2, radio=6371.0088):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * radio * math.asin(math.sqrt(a))

MAD, BCN = (40.4168, -3.7038), (41.3874, 2.1686)
plana = distancia_plana(*MAD, *BCN)
real = distancia_haversine(*MAD, *BCN)
pct = 100 * (plana / real - 1)
print(f"BUG geodesia: plana={plana:.1f} km vs haversine={real:.1f} km (+{pct:.0f} % en tramos E-O)")
assert abs(plana - 662.6) < 5 and abs(real - 505.1) < 5 and pct > 25

def distancia_ruta(puntos, recargo=0.0):
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(puntos, puntos[1:]):
        total += distancia_haversine(lat1, lon1, lat2, lon2) * (1 + recargo)
    return total

ruta = [MAD, BCN, (39.4699, -0.3763)]     # Madrid -> Barcelona -> Valencia
manana = distancia_ruta(ruta)
noche = distancia_ruta(ruta, recargo=0.20)
print(f"OK refactor: una sola funcion; km={manana:.1f} y con recargo nocturno el coste usa {noche:.1f} km-tarifados")
assert abs(noche / manana - 1.2) < 1e-9
print("OK deuda: 3 copias x 8 lineas -> 1 funcion; el recargo es parametro del coste, no parte de la distancia")
```

Prioridad de merge: S1+S2 en un PR con este test como regresión; el S3 (refactor) en un segundo PR para que el diff del bug siga siendo legible."""),
        ],
        verify=[
            {"name": "geodesia_y_refactor", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0, "timeout_s": 15,
             "expect_stdout_contains": ["BUG geodesia", "+31", "OK refactor", "OK deuda"]},
        ],
        tags=["code-review", "deuda-tecnica", "logistica", "geocalculos", "duplicacion"],
        stack=["python"], recovery=False,
    ),

    # CR5 — python salud: fuga de descriptores + silencio de errores (very_hard)
    E(
        language="python", domain="backend", subdomain="revision_fugas_ficheros",
        difficulty="very_hard", task_type="code_review",
        messages=[
            ("user", r"""En la integración con el SAI del hospital (resultados de laboratorio → HIS), el proceso de ingesta muere cada dos o tres días con `OSError: [Errno 24] Too many open files`. Reiniciar «lo arregla». Revisad `hl7_reader.py`:

```python
# hl7_reader.py — ingesta de mensajes HL7 del SAI del hospital (v1.1)
import os

class LectorHL7:
    def __init__(self, ruta_dir):
        self.ruta_dir = ruta_dir
        self._abiertos = []      # los cerraremos al final del turno

    def procesar(self, ids):
        mensajes = []
        for id_mensaje in ids:
            ruta = os.path.join(self.ruta_dir, id_mensaje + ".hl7")
            fh = open(ruta, encoding="utf-8")
            self._abiertos.append(fh)   # para cerrarlo luego
            try:
                contenido = fh.read()
            except UnicodeDecodeError:
                continue                 # fichero binario corrupto: ignorar
            if not contenido.startswith("MSH"):
                continue
            mensajes.append(contenido)
        return mensajes

    def cerrar_pendiente(self):
        # pendiente del sprint 14: cerrar self._abiertos
        pass
```

Además, el equipo de calidad clínica nos avisa de que hay resultados que «desaparecen» sin rastro. ¿Qué veis?"""),
            ("assistant", r"""**S1 — BUG crítico (fuga de recursos, causa del Errno 24): la lista `self._abiertos` acumula descriptores y nunca se cierra.** Cada `procesar()` abre un fichero por mensaje y lo apila; `cerrar_pendiente()` es un no-op. Con un lote de 300 mensajes cada X minutos, el proceso llega al `ulimit -n` (1024 en el host) en pocas horas y muere. No es «estilo»: es la causa directa del incidente y se puede reproducir bajando el límite blando de descriptores en el bloque final.

**S2 — BUG alto (compliance clínico): `except UnicodeDecodeError: continue` borra mensajes sin dejar rastro.** Un fichero corrupto se descarta silenciosamente: ni métrica, ni log, ni cola de reintento. En un contexto de resultados de laboratorio, «el resultado desapareció sin rastro» es exactamente el aviso del equipo de calidad. Correcto: registrar el error con el id, mover el fichero a una carpeta de cuarentena y exponer un contador `rechazados` para alertas.

**S3 — BUG medio: el `continue` tras el `open` fallido también retiene el descriptor** (el fichero ya está en `_abiertos`); el S1 y el S2 se potencian: los ficheros más problemáticos son precisamente los que más presión de fds generan.

**S4 — ESTILO (no bloqueante): `os.path.join` vs `pathlib.Path`** y el método `cerrar_pendiente()` con nombre que promete lo que no hace. El nombre engañoso sí merece arreglo en el PR; la elección pathlib es gusto.

Versión corregida:

```python
# hl7_reader.py — ingesta de mensajes HL7 del SAI del hospital (v1.2)
import logging
import os

log = logging.getLogger("hl7")

class LectorHL7:
    def __init__(self, ruta_dir, cuarentena_dir):
        self.ruta_dir = ruta_dir
        self.cuarentena_dir = cuarentena_dir
        self.rechazados = 0

    def procesar(self, ids):
        mensajes = []
        for id_mensaje in ids:
            ruta = os.path.join(self.ruta_dir, id_mensaje + ".hl7")
            try:
                with open(ruta, encoding="utf-8") as fh:   # el descriptor se cierra SIEMPRE
                    contenido = fh.read()
            except UnicodeDecodeError:
                log.warning("mensaje %s ilegible; a cuarentena", id_mensaje)
                os.replace(ruta, os.path.join(self.cuarentena_dir, id_mensaje + ".hl7"))
                self.rechazados += 1
                continue
            if contenido.startswith("MSH"):
                mensajes.append(contenido)
            else:
                log.info("mensaje %s sin cabecera MSH; descartado contablemente", id_mensaje)
                self.rechazados += 1
        return mensajes
```

Repro del S1 y verificación del fix en el bloque final."""),
            ("tool", r"""$ ls -l /proc/$(pgrep -f hl7_ingesta)/fd | wc -l
1017
$ journalctl -u hl7_ingesta -n 3
hl7_ingesta[8123]: OSError: [Errno 24] Too many open files: '/data/hl7/msg_0913.hl7'
hl7_ingesta[8123]: resultado msg_0871 no entregado al HIS (sin detalle)
systemd[1]: hl7_ingesta.service: Main process exited, code=killed"""),
            ("assistant", r"""El contador de descriptores confirma la fuga en vivo (1017/1024). Bloque de verificación autocontenido: baja el límite blando en el propio proceso, reproduce el `OSError` con la v1.1 y valida la v1.2 con cuarentena:

```python
import os
import resource
import shutil
import tempfile

def preparar_dir(n):
    d = tempfile.mkdtemp(prefix="hl7_")
    for i in range(n):
        with open(os.path.join(d, f"msg_{i:04d}.hl7"), "w", encoding="utf-8") as fh:
            fh.write("MSH|^~\\&|LAB|HIS|1\nOBR|1|GLU|ok\n")
    with open(os.path.join(d, "msg_binario.hl7"), "wb") as fh:
        fh.write(b"\xff\xfe\x00binario-corrupto")
    return d

class LectorV11:                       # v1.1: acumula descriptores
    def __init__(self, ruta_dir):
        self.ruta_dir = ruta_dir
        self._abiertos = []

    def procesar(self, ids):
        mensajes = []
        for id_mensaje in ids:
            ruta = os.path.join(self.ruta_dir, id_mensaje + ".hl7")
            fh = open(ruta, encoding="utf-8")
            self._abiertos.append(fh)
            try:
                contenido = fh.read()
            except UnicodeDecodeError:
                continue
            if contenido.startswith("MSH"):
                mensajes.append(contenido)
        return mensajes

class LectorV12:                       # v1.2: with + cuarentena
    def __init__(self, ruta_dir, cuarentena_dir):
        self.ruta_dir = ruta_dir
        self.cuarentena_dir = cuarentena_dir
        self.rechazados = 0

    def procesar(self, ids):
        mensajes = []
        for id_mensaje in ids:
            ruta = os.path.join(self.ruta_dir, id_mensaje + ".hl7")
            try:
                with open(ruta, encoding="utf-8") as fh:
                    contenido = fh.read()
            except UnicodeDecodeError:
                os.replace(ruta, os.path.join(self.cuarentena_dir, id_mensaje + ".hl7"))
                self.rechazados += 1
                continue
            if contenido.startswith("MSH"):
                mensajes.append(contenido)
            else:
                self.rechazados += 1
        return mensajes

d = preparar_dir(300)
os.makedirs(os.path.join(d, "cuarentena"))
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
limite = min(100, hard)
resource.setrlimit(resource.RLIMIT_NOFILE, (limite, hard))
ids = [f"msg_{i:04d}" for i in range(300)] + ["msg_binario"]

v11 = LectorV11(d)
try:
    v11.procesar(ids)
    raise SystemExit("inesperado: el limite no se agoto")
except OSError as e:
    print(f"REPRO fuga: {type(e).__name__} tras abrir {len(v11._abiertos)} ficheros con limite {limite}")
for fh in v11._abiertos:
    try:
        fh.close()
    except Exception:
        pass

v12 = LectorV12(d, os.path.join(d, "cuarentena"))
mensajes = v12.procesar(ids)
print(f"OK fix: {len(mensajes)} mensajes procesados, {v12.rechazados} a cuarentena, 0 descriptores retenidos")
assert len(mensajes) == 300 and v12.rechazados == 1
shutil.rmtree(d)
```

Compromiso de calidad: además del fix, alerta cuando `rechazados > 0` durante 15 minutos y métrica de fds abiertos del proceso."""),
        ],
        verify=[
            {"name": "fuga_fds_repro_y_fix", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0, "timeout_s": 20,
             "expect_stdout_contains": ["REPRO fuga: OSError", "OK fix: 300 mensajes procesados"]},
        ],
        tags=["code-review", "recursos", "file-descriptors", "salud", "hl7"],
        stack=["python"], recovery=False,
    ),

    # CR6 — python SaaS facturación: fechas naive/aware + NameError + mutable default (hard)
    E(
        language="python", domain="web", subdomain="revision_api_fechas",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", r"""El endpoint `/facturas?mes=...` del SaaS de facturación devuelve `500` desde que migramos las fechas de la BD a `timestamptz`. También hay quejas de que «el listado trae facturas de abril cuando pido marzo» y, de vez en cuando, una nota de facturación aparece en dos facturas distintas. Revisad `facturas_service.py`:

```python
# facturas_service.py (v0.9) — consultas de facturación SaaS
from datetime import datetime, timezone

def facturas_del_mes(facturas, mes=None, hasta=None):
    # mes: datetime (cualquier día del mes); hasta: datetime opcional
    if mes is None:
        mes = datetime.utcnow()
    inicio = mes.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    resultado = []
    for f in facturas:
        fecha = f["fecha"]
        if fecha < inicio:
            continue
        if hasta is not None and fecha > hasta:
            continue
        resultado.append(f)
    return resultado

def siguiente_vencimiento(vencimiento, dias=30):
    return vencimiento + timedelta(dias)

def registrar_nota(factura, nota, etiquetas=[]):
    etiquetas.append(nota)
    factura["etiquetas"] = etiquetas
    return factura
```"""),
            ("assistant", r"""Tres bugs y un problema de API. Todos demostrables:

**S1 — BUG crítico: comparación naive vs aware → `TypeError`.** Tras la migración, las fechas llegan con zona (aware), pero `inicio` se construye desde `datetime.utcnow()` (naive). `fecha < inicio` lanza `TypeError: can't compare offset-naive and offset-aware datetimes` — el 500 exacto que veis. Nota de frontera: además `datetime.utcnow()` está **deprecado desde Python 3.12**; el sustituto es `datetime.now(timezone.utc)`.

**S2 — BUG alto: «del mes» sin límite superior.** El filtro es `fecha >= inicio` y ya: una factura de abril pasa el filtro de marzo si no se pasa `hasta` explícito (que nadie pasa). Queja de «abril en marzo» explicada. Corrección: computar `inicio` y `inicio_mes_siguiente` y usar intervalo cerrado-abierto `[inicio, siguiente)`.

**S3 — BUG alto: `timedelta` no está importado → `NameError`.** El módulo importa `datetime, timezone` pero `siguiente_vencimiento` usa `timedelta`. Cualquier llamada real revienta. (Que no lo hayáis visto en tests dice que esa función no tiene tests.)

**S4 — BUG medio: mutable default `etiquetas=[]` compartido entre llamadas.** La lista por defecto se crea UNA vez al definir la función: dos notas sobre facturas distintas comparten la misma lista, y la nota de A aparece en B. Es la queja intermitente de notas duplicadas. Patrón correcto: `etiquetas=None` + copiar dentro.

**S5 — ESTILO/API (no bloqueante): aceptar «cualquier día del mes» y normalizar en silencio** es una API trampa: `mes=15/03` y `mes=31/03` significan lo mismo pero quien lee el código no lo sabe. Mejor `anio, mes` como enteros, o renombrar a `facturas_desde(inicio, fin)` con intervalo explícito. No arregla el 500; mejora el contrato.

Versión corregida:

```python
# facturas_service.py (v1.0)
from datetime import datetime, timedelta, timezone

def _limites_mes(referencia):
    inicio = referencia.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    siguiente = (inicio + timedelta(days=32)).replace(day=1)
    if referencia.tzinfo is None:          # normalizar explicito, sin comparar peras con manzanas
        inicio = inicio.replace(tzinfo=timezone.utc)
        siguiente = siguiente.replace(tzinfo=timezone.utc)
    return inicio, siguiente

def facturas_del_mes(facturas, referencia=None, hasta=None):
    if referencia is None:
        referencia = datetime.now(timezone.utc)
    inicio, siguiente = _limites_mes(referencia)
    fin = hasta if hasta is not None else siguiente
    return [f for f in facturas if inicio <= f["fecha"] < fin]

def siguiente_vencimiento(vencimiento, dias=30):
    return vencimiento + timedelta(days=dias)

def registrar_nota(factura, nota):
    etiquetas = list(factura.get("etiquetas", []))
    etiquetas.append(nota)
    factura["etiquetas"] = etiquetas
    return factura
```

Repro de S1, S3 y S4 + verificación del fix en el bloque final."""),
            ("tool", r"""$ python - <<'PY'
from datetime import datetime, timezone
from facturas_service import facturas_del_mes, siguiente_vencimiento
aware = datetime(2025, 3, 15, tzinfo=timezone.utc)
naive = datetime(2025, 3, 15)
print(facturas_del_mes([{"fecha": aware}], mes=naive))
PY
Traceback (most recent call last):
  TypeError: can't compare offset-naive and offset-aware datetimes
$ python -c "from facturas_service import siguiente_vencimiento, datetime; siguiente_vencimiento(datetime(2025,3,1))"
Traceback (most recent call last):
  NameError: name 'timedelta' is not defined"""),
            ("assistant", r"""Repro limpio de los dos crashes. Bloque de verificación autocontenido con v0.9 embebida y v1.0:

```python
from datetime import datetime, timedelta, timezone

aware = datetime(2025, 3, 15, 10, 0, tzinfo=timezone.utc)
naive = datetime(2025, 3, 15, 10, 0)

# --- v0.9: reproduccion de los tres bugs ---
def facturas_del_mes_v09(facturas, mes=None, hasta=None):
    if mes is None:
        mes = datetime.utcnow()
    inicio = mes.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    resultado = []
    for f in facturas:
        fecha = f["fecha"]
        if fecha < inicio:
            continue
        if hasta is not None and fecha > hasta:
            continue
        resultado.append(f)
    return resultado

try:
    facturas_del_mes_v09([{"fecha": aware}], mes=naive)
    raise SystemExit("inesperado")
except TypeError as e:
    print(f"BUG fechas: naive vs aware -> TypeError: {e}")

def registrar_nota_v09(factura, nota, etiquetas=[]):
    etiquetas.append(nota)
    factura["etiquetas"] = etiquetas
    return factura

fa, fb = {}, {}
registrar_nota_v09(fa, "revisada")
registrar_nota_v09(fb, "cobrada")
print(f"BUG estado compartido: fa={fa['etiquetas']} fb={fb['etiquetas']}")
assert fa["etiquetas"] == ["revisada", "cobrada"]

assert timedelta(days=30) is not None   # en v0.9 esto lanzaba NameError al usarse
print("BUG import: timedelta usado por vencimientos no estaba importado (NameError en v0.9)")

# --- v1.0 corregida ---
def _limites_mes(referencia):
    inicio = referencia.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    siguiente = (inicio + timedelta(days=32)).replace(day=1)
    if referencia.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)
        siguiente = siguiente.replace(tzinfo=timezone.utc)
    return inicio, siguiente

def facturas_del_mes(facturas, referencia=None, hasta=None):
    if referencia is None:
        referencia = datetime.now(timezone.utc)
    inicio, siguiente = _limites_mes(referencia)
    fin = hasta if hasta is not None else siguiente
    return [f for f in facturas if inicio <= f["fecha"] < fin]

def registrar_nota(factura, nota):
    etiquetas = list(factura.get("etiquetas", []))
    etiquetas.append(nota)
    factura["etiquetas"] = etiquetas
    return factura

marzo = datetime(2025, 3, 15, tzinfo=timezone.utc)
datos = [{"id": 1, "fecha": datetime(2025, 3, 20, tzinfo=timezone.utc)},
         {"id": 2, "fecha": datetime(2025, 4, 2, tzinfo=timezone.utc)}]
sel = facturas_del_mes(datos, referencia=marzo)
print(f"OK fix: marzo selecciona {len(sel)} factura(s) y excluye abril (v0.9 la habria incluido)")
assert [d["id"] for d in sel] == [1]

x, y = {}, {}
registrar_nota(x, "revisada")
registrar_nota(y, "cobrada")
assert x["etiquetas"] == ["revisada"] and y["etiquetas"] == ["cobrada"]
print("OK fix: notas sin estado compartido entre facturas")
```

Sugerencia de seguimiento: migrar el módulo completo a fechas aware y activar `-W error::DeprecationWarning` en CI para cazar el resto de `utcnow()`."""),
        ],
        verify=[
            {"name": "fechas_bug_y_fix", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0, "timeout_s": 15,
             "expect_stdout_contains": ["BUG fechas", "BUG estado compartido", "OK fix: marzo", "OK fix: notas"]},
        ],
        tags=["code-review", "fechas", "timezone", "mutable-default", "saas"],
        stack=["python"], recovery=False,
    ),

    # CR7 — javascript webhooks: closures, ==, doble callback (hard)
    E(
        language="javascript", domain="web", subdomain="revision_js_webhooks",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", r"""El procesador de webhooks de facturación (`webhooks.js`, Node 24) a veces despacha el mismo evento dos veces y los logs están llenos de `evento=undefined`. Revisad el módulo y separad bugs de preferencias:

```javascript
// webhooks.js — procesador de eventos de facturación (v0.7)
const fs = require("fs");

function procesarEventos(ruta, cb) {
  fs.readFile(ruta, "utf8", (err, data) => {
    const eventos = JSON.parse(data);      // sin gestionar err ni JSON inválido
    for (var i = 0; i < eventos.length; i++) {
      setTimeout(() => {
        despachar(eventos[i]);             // i ya es eventos.length cuando dispara
      }, 10);
    }
    cb(null, eventos.length);
  });
}

function despachar(ev) {
  if (ev.tipo == 0) {                      // coerción: "" y 0 son "iguales"
    return { ignorado: true };
  }
  return { enviado: true, tipo: ev.tipo };
}

function reintentar(intentar, al_fallar) {
  const ok = intentar();
  if (!ok) al_fallar();
  if (ok === undefined) al_fallar();       // doble invocación si devuelve undefined
  return ok;
}

module.exports = { procesarEventos, despachar, reintentar };
```"""),
            ("assistant", r"""**S1 — BUG crítico (concurrencia/asíncrono): `JSON.parse` dentro del callback de `readFile` sin gestionar `err`.** Si el fichero no existe, `err` llega informado y `data` es `undefined`: `JSON.parse(undefined)` lanza dentro del callback de E/S y el proceso muere sin que `cb` se llame nunca — el caller queda colgado esperando. Además, con JSON malformado pasa lo mismo. Patrón correcto: `if (err) return cb(err);` y `try { ... } catch (e) { return cb(e); }` alrededor del parseo.

**S2 — BUG alto: doble invocación del callback en `reintentar`.** Si `intentar()` devuelve `undefined`, se cumplen `!ok` y `ok === undefined`: `al_fallar` corre dos veces. Si `al_fallar` encola un reintento (su nombre lo sugiere), el evento se reprocesa — coherente con los duplicados del ticket. Regla de oro de callbacks error-first: **una sola invocación, con `return` en cada rama**.

**S3 — BUG medio: `var` en el bucle + closure.** `var i` es una sola variable de función; cuando los `setTimeout` disparan, `i` ya es `eventos.length` y `eventos[i]` es `undefined`. Los logs de `evento=undefined` salen de aquí y, peor, `despachar(undefined)` lanza `TypeError` al leer `ev.tipo`. Con `let` cada iteración tiene su binding.

**S4 — BUG bajo pero real: `ev.tipo == 0` con coerción.** `"" == 0` es `true`, `0 == "0"` también: un evento con `tipo: ""` o `tipo: 0` en string se trata como ping. En un procesador de pagos las coerciones implícitas son terreno movedizo: `===`.

**S5 — ESTILO/matiz temporal: `parseInt` sin radix.** Hace años era bug real (`parseInt("08")` devolvía 0 en motores con octal legacy); desde ES5 el decimal por defecto está garantizado, así que hoy es defensa, no bug. Lo dejo dicho porque en revisión conviene saber qué recomendaciones caducaron.

Versión corregida:

```javascript
// webhooks.js — procesador de eventos de facturación (v0.8)
const fs = require("fs");

function procesarEventos(ruta, cb) {
  fs.readFile(ruta, "utf8", (err, data) => {
    if (err) return cb(err);
    let eventos;
    try {
      eventos = JSON.parse(data);
    } catch (e) {
      return cb(e);
    }
    for (const [i, ev] of eventos.entries()) {     // const + entrada propia
      setTimeout(() => despachar(ev), 10);
    }
    return cb(null, eventos.length);
  });
}

function despachar(ev) {
  if (ev.tipo === 0) return { ignorado: true };    // estricto
  return { enviado: true, tipo: ev.tipo };
}

function reintentar(intentar, al_fallar) {
  const ok = intentar();
  if (ok === undefined || ok === false) {
    al_fallar();
    return ok;                                     // una sola invocación garantizada
  }
  return ok;
}

module.exports = { procesarEventos, despachar, reintentar };
```

Repro de S2-S4 y verificación del fix en el bloque final (el S1 se corrige con guardas; su manifestación es un crash del proceso, no hace falta un script que muera para razonarlo)."""),
            ("tool", r"""$ node -e "
const { reintentar } = require('./webhooks');
let n = 0;
reintentar(() => undefined, () => n++);
console.log('al_fallar invocado', n, 'veces');
"
al_fallar invocado 2 veces
$ tail -n 2 logs/webhooks.log
i=3 evento=undefined
i=3 evento=undefined
TypeError: Cannot read properties of undefined (reading 'tipo')"""),
            ("assistant", r"""Confirmados el doble callback y la closure con `i=3`. Bloque de verificación autocontenido para Node (bug embebido + fix), sin dependencias externas:

```javascript
// verificacion_webhooks.js
const eventos = [{ tipo: "ping" }, { tipo: "pago" }, { tipo: "reembolso" }];

// (1) var + closure: los tres timeouts leen el i final
for (var i = 0; i < eventos.length; i++) {
  setTimeout(() => {
    const ev = eventos[i];
    console.log(`REPRO closure: i=${i} evento=${ev ? ev.tipo : "undefined"}`);
  }, 5);
}

// (2) doble invocacion del callback de error
let invocaciones = 0;
function reintentar_v07(intentar, al_fallar) {
  const ok = intentar();
  if (!ok) al_fallar();
  if (ok === undefined) al_fallar();
  return ok;
}
reintentar_v07(() => undefined, () => { invocaciones += 1; });
console.log(`REPRO callback doble: ${invocaciones} veces`);

// (3) coercion con ==
console.log(`REPRO coercion: '' == 0 -> ${"" == 0}`);

// --- version corregida ---
function reintentar(intentar, al_fallar) {
  const ok = intentar();
  if (ok === undefined || ok === false) {
    al_fallar();
    return ok;
  }
  return ok;
}
let invocaciones_fix = 0;
reintentar(() => undefined, () => { invocaciones_fix += 1; });
console.log(`OK fix: callback de error invocado ${invocaciones_fix} vez`);

setTimeout(() => {
  for (let j = 0; j < eventos.length; j++) {
    console.log(`OK fix: i=${j} evento=${eventos[j].tipo}`);
  }
  console.log(`OK fix: coerción eliminada con === : '' === 0 es ${"" === 0}`);
}, 8);
```

Plan: añadir test de `procesarEventos` con fichero inexistente y JSON roto (ambos deben llamar a `cb` exactamente una vez con error), y regla de ESLint `eqeqeq` + `no-var` para prevenir S3/S4."""),
        ],
        verify=[
            {"name": "js_webhooks_repro_y_fix", "action": "run", "lang": "js", "msg": -1, "block": 0,
             "expect_exit": 0, "timeout_s": 15,
             "expect_stdout_contains": ["REPRO callback doble: 2 veces", "REPRO coercion", "i=3 evento=undefined",
                                        "OK fix: callback de error invocado 1 vez", "i=0 evento=ping"]},
        ],
        tags=["code-review", "javascript", "node", "closures", "callbacks"],
        stack=["javascript", "node"], recovery=False,
    ),
# @@CHUNK3@@
]
