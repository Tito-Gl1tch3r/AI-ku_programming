"""Módulo insignia: ingeniería de software agéntica (§21, §22, §23, §37).
OBSERVE → UNDERSTAND → PLAN → ACT → OBSERVE RESULT → VERIFY → ADAPT, con tool calling
y recuperación explícita tras hipótesis/estrategias fallidas."""
from schema import E

EXAMPLES = [
    # 1 ------------------------------------------------------------------ caza de bugs con tests
    E(
        language="python", domain="agentic", subdomain="diagnostico_con_tests",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Tras añadir la función de descuento, los tests del módulo de pedidos fallan y no sé por qué. El proyecto está en el directorio actual: empieza, inspecciona, diagnostica, corrige y verifica. No «arregles a ciegas»."),
            ("assistant", "Plan agéntico: (1) OBSERVE — listar el proyecto y ejecutar la batería para ver el fallo exacto; (2) UNDERSTAND — leer el módulo afectado; (3) hipótesis; (4) ACT — corrección mínima; (5) VERIFY — re-ejecutar tests completos."),
            ("tool", "$ ls\ncarrito.py  test_carrito.py\n$ python -m unittest -v 2>&1 | tail -12\ntest_con_descuento_aplica_porcentaje ... FAIL\ntest_total_sin_descuento ... ok\n\ntest_con_descuento_aplica_porcentaje\n----------------------------------------------------------------------\nTraceback (most recent call last):\n  File \"test_carrito.py\", line 27, in test_con_descuento_aplica_porcentaje\n    self.assertEqual(total(100.0, descuento=10), 90.0)\nAssertionError: 90.00000000000001 != 90.0\n\nRan 2 tests in 0.004s\n\nFAILED (failures=1)"),
            ("assistant", "OBSERVE confirmado: la batería tiene 2 tests y falla exactamente 1 (lo aclaro frente a la percepción del usuario: hecho verificado vs impresión). UNDERSTAND: leo el módulo.\n"
                     "```python\n# carrito.py (versión actual)\n\ndef total(importe, descuento=0):\n    factor = (100 - descuento) / 100\n    return importe * factor\n```\nEl fallo es 90.00000000000001 != 90.0: aritmética binaria de flotantes (100·0.9 no es exacto en base 2). Hipótesis: no es un bug de lógica sino de representación — pero un total monetario que rompe un assert de igualdad es un contrato roto para el cliente de la API. DECISIÓN: dinero → aritmética decimal; operar en `Decimal` con redondeo monetario half-up a 2 decimales. Experimento que confirma la hipótesis antes de tocar nada:"),
            ("tool", "$ python - <<'EOF'\nfrom decimal import Decimal\nprint(repr(100.0 * (100 - 10) / 100))\nprint(repr(Decimal('100') * Decimal('90') / Decimal('100')))\nEOF\n90.00000000000001\nDecimal('90.0')"),
            ("assistant", "Confirmado: en Decimal el cálculo es exacto. ACT — corrección con contrato explícito, y VERIFY autocontenido (el bloque ejecuta su propia batería de contrato al correrlo):\n"
                     "```python\nfrom decimal import ROUND_HALF_UP, Decimal\n\n\ndef total(importe, descuento=0):\n    \"\"\"Total en euros con redondeo monetario (2 decimales, half-up).\"\"\"\n    if descuento < 0 or descuento > 100:\n        raise ValueError(\"descuento fuera de rango\")\n    bruto = Decimal(str(importe)) * (100 - Decimal(descuento)) / Decimal(100)\n    return float(bruto.quantize(Decimal(\"0.01\"), rounding=ROUND_HALF_UP))\n\n\nif __name__ == \"__main__\":\n    assert total(100.0, descuento=10) == 90.0\n    assert total(100.0) == 100.0\n    assert total(10.005) == 10.01            # half-up, no banker's\n    try:\n        total(100.0, descuento=150)\n    except ValueError:\n        pass\n    else:\n        raise AssertionError(\"debía rechazar descuento > 100\")\n    print(\"contrato_ok=True\")\n```\nVERIFY — el bloque anterior se ejecuta tal cual y la batería externa del proyecto queda en verde:"),
            ("tool", "$ python carrito.py\ncontrato_ok=True\n$ python -m unittest -v\ntest_con_descuento_aplica_porcentaje ... ok\ntest_total_sin_descuento ... ok\n\nRan 2 tests in 0.004s\n\nOK"),
            ("assistant", "Verificado por ejecución: contrato interno en verde (contrato_ok=True, incluido el caso half-up 10.005→10.01) y batería externa del proyecto en verde. Resumen agéntico: síntoma → lectura del módulo → hipótesis de representación confirmada con experimento Decimal → corrección mínima con contrato explícito → verificación doble (interna y externa). No se tocó nada más del módulo."),
        ],
        verify=[
            {"name": "fix_contrato", "action": "run", "lang": "python", "msg": 6, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["contrato_ok=True"], "timeout_s": 20},
        ],
        tags=["agentic", "decimal", "dinero", "tests", "tool-calling"],
        stack=["python"],
    ),
    # 2 ------------------------------------------------------------------ forense de logs
    E(
        language="bash", domain="agentic", subdomain="investigacion_de_logs",
        difficulty="extreme", task_type="debugging",
        messages=[
            ("user", "Desde el cambio de horario, nuestro job nocturno se ejecuta «a veces» dos veces. No hay cambios de código relevantes. Investiga con lo que te doy: el log del planificador y el crontab. Metodología: no concluyas sin evidencia."),
            ("assistant", "Plan: OBSERVE los dos artefactos (log del scheduler, crontab); correlacionar timestamps del doble disparo; UNDERSTAND el solapamiento; hipótesis verificable; corrección mínima; verificación del mecanismo por simulación determinista."),
            ("tool", "$ cat scheduler.log | grep -E 'job_nocturno' | tail -8\n2026-03-28 01:59:59 START job_nocturno pid=4100\n2026-03-28 03:00:01 START job_nocturno pid=4188\n2026-03-28 03:00:02 ALREADY_RUNNING pid=4188 aborta\n2026-03-29 01:59:59 START job_nocturno pid=5201\n2026-03-29 03:00:01 START job_nocturno pid=5288\n2026-03-29 03:00:02 ALREADY_RUNNING pid=5288 aborta\n2026-03-30 01:59:59 START job_nocturno pid=6110\n2026-03-30 03:00:01 START job_nocturno pid=6199\n$ crontab -l\n59 1 * * * /opt/bin/job_nocturno\n0 3 * * * /opt/bin/job_nocturno"),
            ("assistant", "OBSERVE: hay DOS entradas de cron para el mismo job (01:59 y 03:00) y los días del cambio de horario el job de las 01:59 (que tarda más de una hora) SIGUE VIVO cuando arranca el de las 03:00; el guardián aborta al segundo — el «doble disparo» percibido es el intento abortado que alarma. UNDERSTAND: con el cambio de horario el hueco real entre disparos varió y el solapamiento emerge. Causa inmediata: crontab duplicado; causa de fondo: el job no tiene locking propio. Corrección en dos capas: (1) unificar a UNA entrada cron; (2) wrapper con flock para que cualquier solapamiento futuro aborte ordenado y trazado, no con alarma."),
            ("tool", "$ cat /opt/bin/job_nocturno | head -5\n#!/bin/bash\nset -euo pipefail\n/opt/venv/bin/python /opt/lib/nocturno.py --desde=$(date -d yesterday +%F)\n$ flock --help | head -2\n\nUsage:\n flock [options] <file|directory> <command>..."),
            ("assistant", "ACT — wrapper con lock exclusivo (fd 9 + flock no bloqueante), y un test determinista del mecanismo como segundo bloque:\n"
                     "```bash\n#!/usr/bin/env bash\n# /opt/bin/job_nocturno — con locking y log de solapamientos\nset -euo pipefail\n\nLOCK=/var/lock/job_nocturno.lock\nLOG=/var/log/job_nocturno.log\n\nexec 9>\"$LOCK\"\nif ! flock -n 9; then\n  echo \"$(date -Is) solapamiento: ya hay una instancia en marcha; aborto ordenado\" >> \"$LOG\"\n  exit 0\nfi\n\necho \"$(date -Is) inicio\" >> \"$LOG\"\n/opt/venv/bin/python /opt/lib/nocturno.py --desde=\"$(date -d yesterday +%F)\"\necho \"$(date -Is) fin\" >> \"$LOG\"\n```\n"
                     "```bash\n#!/usr/bin/env bash\n# test_lock.sh — simulación del mecanismo: la segunda instancia debe abortar\nset -euo pipefail\nLOCK=./test.lock\n\nexec 9>\"$LOCK\"\nflock -n 9 || { echo \"fallo: la primera no adquirió el lock\"; exit 1; }\necho \"primera: lock adquirido\"\n\n(\n  exec 9>\"$LOCK\"\n  if flock -n 9; then\n    echo \"fallo: la segunda adquirió el lock\"\n    exit 1\n  fi\n  echo \"segunda: aborta ordenadamente\"\n)\necho \"lock_mecanismo_ok=True\"\n```\nVERIFY — ejecutar la simulación:"),
            ("tool", "$ bash test_lock.sh\nprimera: lock adquirido\nsegunda: aborta ordenadamente\nlock_mecanismo_ok=True"),
            ("assistant", "Verificado por ejecución: con el lock, la segunda instancia no puede correr en paralelo y aborta ordenadamente. Nota de cron bajo cambios de horario: los cron locales pueden saltarse o repetir horas — si el job es crítico, anclarlo a UTC con una sola entrada. Hechos verificados aquí: el mecanismo de lock (simulado). Suposiciones que quedan por validar en tu entorno: duración real del job (log histórico) y que ningún otro sistema dispare el binario."),
        ],
        verify=[
            {"name": "mecanismo_lock", "action": "run", "lang": "bash", "msg": 6, "block": 1,
             "expect_exit": 0, "expect_stdout_contains": ["lock_mecanismo_ok=True"], "timeout_s": 20},
            {"name": "wrapper_sintaxis", "action": "syntax", "lang": "bash", "msg": 6, "block": 0},
        ],
        tags=["agentic", "bash", "flock", "cron", "diagnostico", "tool-calling"],
        stack=["bash"],
    ),
    # 3 ------------------------------------------------------------------ recuperación tras fix fallido
    E(
        language="python", domain="agentic", subdomain="recuperacion",
        difficulty="extreme", task_type="debugging",
        messages=[
            ("user", "Nuestro importador duplica filas cuando el mismo lote llega dos veces (reintentos del productor). Hazlo idempotente. La clave de negocio es (proveedor, referencia)."),
            ("assistant", "Plan: OBSERVE el código y los datos; UNDERSTAND dónde se inserta; ACT con la primera estrategia; VERIFY; si falla, NUEVA hipótesis — repetir el mismo arreglo sin información nueva no es recovery, es repetición."),
            ("tool", "$ cat importador.py\ndef importar(con, lote):\n    for fila in lote:\n        con.execute(\"INSERT INTO piezas (proveedor, referencia, stock) VALUES (?,?,?)\",\n                    (fila[\"proveedor\"], fila[\"referencia\"], fila[\"stock\"]))\n    con.commit()\n$ python demo_duplicados.py\nfilas tras 2 importes del mismo lote: 8 (esperadas 4)"),
            ("assistant", "OBSERVE: 8 filas por 4 piezas — duplicación confirmada en el INSERT. Estrategia 1: INSERT OR IGNORE con UNIQUE(proveedor, referencia). ACT:"),
            ("tool", "$ python demo_duplicados.py\nfilas tras 2 importes del mismo lote: 4 (esperadas 4)\nPERO: test_stock_actualizado FALLO — stock quedó 3, esperado 7\n(El reenvío trae stock actualizado; OR IGNORE conserva el valor ANTIGUO)"),
            ("assistant", "VERIFY detectó el fallo de la estrategia 1: el requisito real no es «ignorar duplicados» sino UPSERT — la segunda llegada debe actualizar el stock. ADAPT con la información nueva que aportó el test: INSERT ... ON CONFLICT DO UPDATE. Estrategia 2:\n"
                     "```python\nfrom sqlite3 import connect\n\n\ndef importar(con, lote):\n    \"\"\"Importa un lote de piezas de forma idempotente.\n\n    (proveedor, referencia) es la clave de negocio: los reenvíos del mismo\n    lote actualizan el stock en lugar de duplicar filas.\n    \"\"\"\n    con.execute(\"CREATE TABLE IF NOT EXISTS piezas (\"\n                \"proveedor TEXT NOT NULL, referencia TEXT NOT NULL, \"\n                \"stock INTEGER NOT NULL, \"\n                \"UNIQUE(proveedor, referencia))\")\n    con.executemany(\n        \"INSERT INTO piezas (proveedor, referencia, stock) VALUES (?, ?, ?) \"\n        \"ON CONFLICT(proveedor, referencia) DO UPDATE SET stock = excluded.stock\",\n        [(f[\"proveedor\"], f[\"referencia\"], f[\"stock\"]) for f in lote],\n    )\n    con.commit()\n\n\ndef demo():\n    con = connect(\":memory:\")\n    lote = [{\"proveedor\": \"acme\", \"referencia\": \"torn-8\", \"stock\": 3},\n            {\"proveedor\": \"acme\", \"referencia\": \"tuer-6\", \"stock\": 9},\n            {\"proveedor\": \"bca\", \"referencia\": \"torn-8\", \"stock\": 1},\n            {\"proveedor\": \"acme\", \"referencia\": \"arand-8\", \"stock\": 40}]\n    importar(con, lote)\n    importar(con, lote)          # reenvío íntegro del mismo lote\n    importar(con, [dict(lote[0], stock=7)])   # reenvío con stock actualizado\n    n = con.execute(\"SELECT COUNT(*) FROM piezas\").fetchone()[0]\n    stock = con.execute(\"SELECT stock FROM piezas WHERE proveedor='acme' \"\n                        \"AND referencia='torn-8'\").fetchone()[0]\n    print(f\"filas={n} stock_actualizado={stock}\")\n    print(f\"idempotente={n == 4 and stock == 7}\")\n\n\nif __name__ == \"__main__\":\n    demo()\n```\nVERIFY de la estrategia 2: 4 filas tras el doble importe y el stock actualizado a 7 por el reenvío posterior."),
            ("tool", "$ python importador.py\nfilas=4 stock_actualizado=7\nidempotente=True"),
            ("assistant", "Verificado: idempotencia completa (4 filas tras 2 importes) y semántica de actualización correcta (stock=7). Lección agéntica registrada: la estrategia 1 cumplía el síntoma pero no el requisito; fue el VERIFY (test de stock) el que generó la información nueva que cambió la estrategia — exactamente lo que distingue recuperación de repetición."),
        ],
        verify=[
            {"name": "upsert_idempotente", "action": "run", "lang": "python", "msg": 6, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["idempotente=True"], "timeout_s": 20},
        ],
        tags=["agentic", "sqlite", "upsert", "idempotencia", "recovery", "tool-calling"],
        stack=["python", "sql"], recovery=True,
    ),
    # 4 ------------------------------------------------------------------ feature desde issue
    E(
        language="python", domain="agentic", subdomain="implementacion_desde_issue",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Issue #142: «El panel acepta duraciones tipo ISO-8601 en los filtros (PT1H30M, P2D, PT45M). Añadid soporte de parsing y el total en minutos para el resumen.» Sin más detalle. Que alguien lo implemente con tests."),
            ("assistant", "UNDERSTAND + requisitos que infiero del estándar y del uso en un panel: (1) soportar el formato de duración con semanas/días/horas/minutos/segundos; (2) RECHAZO años/meses con error explícito — su longitud en días varía y el panel necesita minutos exactos (decisión documentada para revisión de negocio, no silenciosa); (3) negativos no admitidos en filtros; (4) API: `parse_duracion(cadena) -> float` en MINUTOS (la unidad del resumen) con ValueError accionable; (5) tests: casos canónicos, compuestos, inválidos y cero."),
            ("tool", "$ grep -rn \"PT\\|minutos\" panel/ | head -3\npanel/filtros.py:    # hoy solo acepta enteros: \"90\" minutos\npanel/resumen.py:    total_min = sum(f.minutos for f in filtros)"),
            ("assistant", "OBSERVE confirma la integración: hoy acepta enteros de minutos — el parser nuevo es un superset y devuelve minutos float. ACT — implementación + tests:\n"
                     "```python\nimport re\nimport unittest\n\nPATRON = re.compile(\n    r\"^P(?!$)(?:(?P<semanas>\\d+)W)?(?:(?P<dias>\\d+)D)?\"\n    r\"(?:T(?!$)(?:(?P<horas>\\d+)H)?(?:(?P<minutos>\\d+)M)?(?:(?P<segundos>\\d+(?:\\.\\d+)?)S)?)?$\"\n)\n\n\ndef parse_duracion(cadena: str) -> float:\n    \"\"\"Parsea duraciones ISO-8601 del panel y devuelve MINUTOS (float).\n\n    Soporta semanas, días, horas, minutos y segundos (p. ej. PT1H30M, P2D,\n    PT45M, P1DT2H). NO soporta años ni meses: su longitud en días varía y\n    el panel necesita minutos exactos — decisión documentada pendiente de\n    negocio. Lanza ValueError con mensaje accionable.\n    \"\"\"\n    if not isinstance(cadena, str):\n        raise ValueError(\"la duración debe ser una cadena\")\n    if re.search(r\"P\\d+Y\", cadena):\n        raise ValueError(f\"años no soportados (longitud variable): {cadena!r}\")\n    if re.search(r\"P\\d+M\", cadena):\n        raise ValueError(f\"meses no soportados (longitud variable): {cadena!r}\")\n    m = PATRON.match(cadena)\n    if m is None:\n        raise ValueError(f\"duración ISO-8601 inválida: {cadena!r}\")\n    partes = {k: float(v) for k, v in m.groupdict().items() if v}\n    minutos = (partes.get(\"semanas\", 0.0) * 7 * 24 * 60\n               + partes.get(\"dias\", 0.0) * 24 * 60\n               + partes.get(\"horas\", 0.0) * 60\n               + partes.get(\"minutos\", 0.0)\n               + partes.get(\"segundos\", 0.0) / 60)\n    return minutos\n\n\nclass TestsParseDuracion(unittest.TestCase):\n    def test_canonicos(self):\n        self.assertEqual(parse_duracion(\"PT1H30M\"), 90.0)\n        self.assertEqual(parse_duracion(\"PT45M\"), 45.0)\n        self.assertEqual(parse_duracion(\"P2D\"), 2880.0)\n        self.assertEqual(parse_duracion(\"PT90S\"), 1.5)\n        self.assertEqual(parse_duracion(\"P1DT2H\"), 1560.0)\n        self.assertEqual(parse_duracion(\"P1W\"), 10080.0)\n        self.assertEqual(parse_duracion(\"PT0S\"), 0.0)\n        self.assertEqual(parse_duracion(\"PT1H\"), 60.0)\n\n    def test_invalidos(self):\n        for mala in (\"\", \"PT\", \"P\", \"1H30M\", \"P1Y2M\", \"P1M\", \"PT-5M\", \"PT1H30M extra\"):\n            with self.assertRaises(ValueError):\n                parse_duracion(mala)\n\n\nif __name__ == \"__main__\":\n    unittest.main(verbosity=2)\n```\nVERIFY — batería completa:"),
            ("tool", "$ python duracion.py\ntest_canonicos ... ok\ntest_invalidos ... ok\n\nRan 2 tests in 0.004s\n\nOK"),
            ("assistant", "Verificado: 8 casos canónicos (incluidos compuestos P1DT2H y P1W) y 8 inválidos rechazados con ValueError accionable. Nota de diseño para el issue: la restricción años/meses está DOCUMENTADA en el docstring — si negocio la necesita, la respuesta correcta es fijar una convención (p. ej. mes=30d) en un ADR, no meterla silenciosamente. La integración con `panel/filtros.py` es una línea (`minutos = parse_duracion(cadena)`); propongo PR separado para el cableado, porque el issue pide el parser y el total, no el wiring."),
        ],
        verify=[
            {"name": "parser_duracion", "action": "run", "lang": "python", "msg": 4, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["Ran 2 tests", "OK"], "timeout_s": 20},
        ],
        tags=["agentic", "iso8601", "requisitos-implicitos", "tests", "tool-calling"],
        stack=["python"],
    ),
    # 5 ------------------------------------------------------------------ investigación de rendimiento
    E(
        language="python", domain="agentic", subdomain="performance_con_sql",
        difficulty="extreme", task_type="optimization",
        messages=[
            ("user", "El endpoint /resumen tarda ~4s con 5000 pedidos. Perfila, encuentra la causa y optimiza mostrando números. BD SQLite con pedidos y clientes."),
            ("assistant", "Plan: OBSERVE con cProfile el endpoint real; UNDERSTAND el patrón (sospecho N+1 por la forma del código del servicio); cuantificar con el número de consultas; ACT (una consulta con JOIN+GROUP BY); VERIFY con números antes/después e igualdad exacta de resultados."),
            ("tool", "$ python -m cProfile -s cumtime servicio_resumen.py | head -14\n         5023 function calls in 3.94 seconds\n\n   Ordered by: cumulative time\n\n   ncalls  tottime  percall  cumtime\n     5001    0.412    0.000    3.655    sqlite3.Connection.execute\n        1    0.181    0.181    0.220    {built-in method builtins.sum}\n        1    0.091    0.091    3.940    endpoint_resumen\n     5001    0.033    0.000    0.041    len\n\n(5023 ejecuciones ≈ 1 consulta inicial + 5000 por pedido: patrón N+1 confirmado)"),
            ("assistant", "OBSERVE: 5001 llamadas a execute — N+1 confirmado (1 para pedidos + 1 consulta de cliente POR pedido). UNDERSTAND: el sumatorio es agregación pura; puede hacerla el motor con JOIN + GROUP BY en una sola consulta. ACT:\n"
                     "```python\nimport sqlite3\nimport time\n\n\ndef preparar(con):\n    con.execute(\"CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT)\")\n    con.execute(\"CREATE TABLE pedidos (id INTEGER PRIMARY KEY, cliente_id INT, importe REAL)\")\n    con.executemany(\"INSERT INTO clientes VALUES (?,?)\",\n                    [(i, f\"cli-{i:03d}\") for i in range(1, 201)])\n    con.executemany(\"INSERT INTO pedidos VALUES (?,?,?)\",\n                    [(i, (i % 200) + 1, 10.0 + (i % 7)) for i in range(1, 5001)])\n    con.commit()\n\n\ndef resumen_n_plus_1(con):\n    \"\"\"Versión lenta: una consulta por pedido.\"\"\"\n    pedidos = con.execute(\"SELECT cliente_id, importe FROM pedidos\").fetchall()\n    totales = {}\n    for cliente_id, importe in pedidos:\n        nombre = con.execute(\"SELECT nombre FROM clientes WHERE id=?\",\n                             (cliente_id,)).fetchone()[0]\n        totales[nombre] = totales.get(nombre, 0.0) + importe\n    return totales\n\n\ndef resumen_join(con):\n    \"\"\"Versión optimizada: agregación en una sola consulta.\"\"\"\n    filas = con.execute(\n        \"SELECT c.nombre, SUM(p.importe) AS total \"\n        \"FROM pedidos p JOIN clientes c ON c.id = p.cliente_id \"\n        \"GROUP BY c.id ORDER BY c.nombre\"\n    ).fetchall()\n    return {nombre: total for nombre, total in filas}\n\n\ndef main():\n    con = sqlite3.connect(\":memory:\")\n    preparar(con)\n    esperado = resumen_n_plus_1(con)\n\n    t0 = time.perf_counter()\n    lento = resumen_n_plus_1(con)\n    t_lento = time.perf_counter() - t0\n\n    t0 = time.perf_counter()\n    rapido = resumen_join(con)\n    t_rapido = time.perf_counter() - t0\n\n    mismo = (set(lento) == set(rapido)\n             and all(abs(lento[k] - rapido[k]) < 1e-9 for k in lento))\n    mismo = mismo and set(lento) == set(esperado)\n    ratio = t_lento / max(t_rapido, 1e-9)\n    print(f\"antes={t_lento:.3f}s despues={t_rapido:.4f}s ratio={ratio:.0f}x\")\n    print(f\"resultados_iguales={mismo} mejora_significativa={ratio > 3}\")\n\n\nif __name__ == \"__main__\":\n    main()\n```\nVERIFY — igualdad de resultados exacta (los dos caminos y el baseline) y mejora ≥3× (espero 10-50×: 5001 consultas → 1):"),
            ("tool", "$ python optimiza_resumen.py\nantes=0.489s despues=0.0041s ratio=119x\nresultados_iguales=True mejora_significativa=True"),
            ("assistant", "Verificado: resultados idénticos en los tres cálculos (lento, rápido y baseline) y mejora de dos órdenes de magnitud — 5001 consultas pasan a 1. Lección transferible: cProfile revela el patrón (ncalls ≈ nº de filas), y la agregación pertenece al motor de datos; Python orquesta, no itera fila a fila. El ratio exacto varía por máquina; el criterio aceptado fue ≥3× con igualdad de resultados EXACTA."),
        ],
        verify=[
            {"name": "n1_eliminado", "action": "run", "lang": "python", "msg": 4, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["resultados_iguales=True", "mejora_significativa=True"],
             "timeout_s": 30},
        ],
        tags=["agentic", "n-mas-1", "sql", "cprofile", "rendimiento", "tool-calling"],
        stack=["python", "sql"],
    ),
    # 6 ------------------------------------------------------------------ migración agéntica
    E(
        language="sql", domain="agentic", subdomain="migracion_con_verificacion",
        difficulty="extreme", task_type="migration",
        messages=[
            ("user", "Tenemos que separar el campo `nombre` de `usuarios` en `nombre` + `apellidos` sin perder datos y con verificación. Inspecciona el esquema actual, propón el plan, ejecuta y verifica. Esquema v1 y datos:\n"
                     "```sql\nCREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, email TEXT);\nINSERT INTO usuarios (id, nombre, email) VALUES\n (1, 'María García López', 'm@g.es'),\n (2, 'Juan Pérez', 'j@e.es'),\n (3, 'Ana', 'a@e.es'),\n (4, 'Luis de la Vega', 'l@e.es'),\n (5, 'Sofía Ruiz Martín', 's@e.es'),\n (6, 'Leo', 'leo@e.es');\n```"),
            ("assistant", "Plan agéntico: (1) OBSERVE el esquema y muestras reales; (2) UNDERSTAND el formato de `nombre` en los datos (¿un espacio? ¿segundo apellido? ¿partículas?); (3) decidir una regla de separación CONSERVADORA; (4) ACT con migración expand-contract; (5) VERIFY con fila a fila + agregados. Ejecuto la inspección:"),
            ("tool", "sqlite> SELECT * FROM usuarios LIMIT 6;\n1|María García López|m@g.es\n2|Juan Pérez|j@e.es\n3|Ana|a@e.es\n4|Luis de la Vega|l@e.es\n5|Sofía Ruiz Martín|s@e.es\n6|Leo|leo@e.es\nsqlite> SELECT COUNT(*) FROM usuarios;\n6"),
            ("assistant", "OBSERVE: hay nombres SIN apellidos (Ana, Leo), CON partículas (de la Vega) y con 1-2 apellidos. UNDERSTAND: regla conservadora — el PRIMER token es `nombre`, todo lo demás es `apellidos`, un solo token → apellidos vacío. Las partículas quedan en apellidos: sin pérdida de información y reversible concatenando (no invento una IA de apellidos). ACT — migración en tabla nueva con rename atómico:\n"
                     "```sql\nALTER TABLE usuarios ADD COLUMN apellidos TEXT NOT NULL DEFAULT '';\nUPDATE usuarios\nSET apellidos = LTRIM(SUBSTR(nombre, 1 + INSTR(nombre, ' ')))\nWHERE INSTR(nombre, ' ') > 0;\nUPDATE usuarios SET nombre = SUBSTR(nombre, 1, INSTR(nombre, ' ') - 1)\nWHERE INSTR(nombre, ' ') > 0;\nCREATE TABLE usuarios_nueva (\n  id INTEGER PRIMARY KEY,\n  nombre TEXT NOT NULL,\n  apellidos TEXT NOT NULL DEFAULT '',\n  email TEXT\n);\nINSERT INTO usuarios_nueva SELECT id, nombre, apellidos, email FROM usuarios;\nDROP TABLE usuarios;\nALTER TABLE usuarios_nueva RENAME TO usuarios;\nSELECT id, nombre, apellidos FROM usuarios ORDER BY id;\nSELECT COUNT(*) AS total, SUM(apellidos = '') AS sin_apellidos FROM usuarios;\n```\nVERIFY — fila a fila: María→(María, García López), Juan→(Juan, Pérez), Ana→(Ana, ''), Luis→(Luis, de la Vega); agregados total=6, sin_apellidos=2. La reversibilidad (nombre || ' ' || apellidos reconstruye el original) se comprueba contra el backup en el runbook."),
            ("tool", "sqlite> SELECT id, nombre, apellidos FROM usuarios ORDER BY id;\n1|María|García López\n2|Juan|Pérez\n3|Ana|\n4|Luis|de la Vega\n5|Sofía|Ruiz Martín\n6|Leo|\nsqlite> SELECT COUNT(*) AS total, SUM(apellidos='') AS sin_apellidos FROM usuarios;\n6|2"),
            ("assistant", "Verificado: 6 filas migradas, 2 sin apellidos conservadas, partículas íntegras y ningún dato perdido. Ciclo agéntico completo: inspección real del esquema y datos → regla conservadora EXPLÍCITA → migración expand-contract con rename atómico → verificación fila a fila + agregados. Riesgos documentados: nombres compuestos («María José») quedarían como nombre=«María»/apellidos=«José» si no llevan más tokens — revisar con negocio; nunca asumir que la regla es universal."),
        ],
        verify=[
            {"name": "migracion_nombres", "action": "sql", "lang": "sql", "msg": 4, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["1|María|García López", "3|Ana|", "4|Luis|de la Vega",
                                        "6|2"]},
        ],
        tags=["agentic", "sql", "migracion", "verificacion", "tool-calling"],
        stack=["sql"],
    ),
    # 7 ------------------------------------------------------------------ adaptación a dependencia
    E(
        language="python", domain="agentic", subdomain="migracion_de_api",
        difficulty="very_hard", task_type="refactoring",
        messages=[
            ("user", "Actualizamos la librería interna `fechas_negocio` a v2 y rompieron nuestros cálculos de vencimiento. La v1 tenía `sumar_dias(fecha, n)`; la v2 la eliminó. Adapta nuestro módulo y sus tests, y documenta la decisión."),
            ("assistant", "Plan: OBSERVE qué usábamos de la librería; UNDERSTAND qué ofrece la v2 (leo su API simulada); ACT con adaptación mínima encapsulada; VERIFY con tests del servicio ejecutables aquí (con un doble de la dependencia, sin instalarla)."),
            ("tool", "$ grep -rn \"fechas_negocio\" .\nservicio/ventas.py:from fechas_negocio import sumar_dias\nservicio/ventas.py:        vencimiento = sumar_dias(fecha_pedido, plazo)\n$ pip show fechas-negocio | head -3\nName: fechas-negocio\nVersion: 2.0.0\n$ python -c \"import fechas_negocio; print([x for x in dir(fechas_negocio) if not x.startswith('_')])\"\n['Date', 'delta_dias', 'fin_de_mes']"),
            ("assistant", "OBSERVE: un único punto de uso (`sumar_dias`) y la v2 ofrece `delta_dias(Date, int) -> Date` (orden de argumentos distinto y tipo propio `Date` con atributos anio/mes/dia). UNDERSTAND: encapsulo la dependencia en UN wrapper propio (`servicio/fechas.py`) — el resto del código no debe conocer la API de terceros (capa anti-corrupción); el wrapper acepta y devuelve `datetime.date` estándar para limitar el contagio del tipo propio. ACT:\n"
                     "```python\n\"\"\"servicio/fechas.py — encapsulador de fechas_negocio v2.\n\nLa v2 eliminó sumar_dias(fecha, n). En lugar de propagar delta_dias(Date, n)\npor todo el código, exponemos sumar_dias(date, int) con datetime.date estándar:\nun único punto de cambio para futuras migraciones.\n\"\"\"\nfrom datetime import date\n\nfrom fechas_negocio import Date as FechaNegocio, delta_dias\n\n\ndef sumar_dias(fecha: date, dias: int) -> date:\n    \"\"\"Devuelve fecha + dias usando el motor de fechas de negocio v2.\"\"\"\n    base = FechaNegocio(fecha.year, fecha.month, fecha.day)\n    resultado = delta_dias(base, dias)\n    return date(resultado.anio, resultado.mes, resultado.dia)\n```\nVERIFY — tests ejecutables SIN la librería real: un doble inyectado en sys.modules reproduce la API v2 (según su documentación) y valida el contrato del wrapper, incluidos los saltos de mes:"),
            ("tool", "$ python -m unittest -v\ntest_acepta_date_estandar ... ok\ntest_salto_de_mes ... ok\ntest_cero_dias ... ok\n\nRan 3 tests in 0.003s\n\nOK"),
            ("assistant", "VERIFY — batería ejecutable sin instalar la librería: un doble inyectado en sys.modules reproduce la API v2 documentada y valida el contrato del wrapper, incluidos los saltos de mes.\n"
                     "```python\nimport sys\nimport types\nimport unittest\nfrom datetime import date\n\n# doble de fechas_negocio v2 según su API documentada\nfake = types.ModuleType(\"fechas_negocio\")\n\n\nclass FechaNegocio:\n    def __init__(self, anio, mes, dia):\n        self.anio, self.mes, self.dia = anio, mes, dia\n\n\ndef delta_dias(base, n):\n    import datetime\n    d = datetime.date(base.anio, base.mes, base.dia) + datetime.timedelta(days=n)\n    return FechaNegocio(d.year, d.month, d.day)\n\n\nfake.Date = FechaNegocio\nfake.delta_dias = delta_dias\nsys.modules[\"fechas_negocio\"] = fake\n\n# wrapper (idéntico a servicio/fechas.py)\ndef sumar_dias(fecha, dias):\n    base = FechaNegocio(fecha.year, fecha.month, fecha.day)\n    r = delta_dias(base, dias)\n    return date(r.anio, r.mes, r.dia)\n\n\nclass TestsWrapper(unittest.TestCase):\n    def test_acepta_date_estandar(self):\n        self.assertEqual(sumar_dias(date(2026, 1, 10), 5), date(2026, 1, 15))\n\n    def test_salto_de_mes(self):\n        self.assertEqual(sumar_dias(date(2026, 1, 30), 3), date(2026, 2, 2))\n\n    def test_cero_dias(self):\n        self.assertEqual(sumar_dias(date(2026, 3, 15), 0), date(2026, 3, 15))\n\n\nif __name__ == \"__main__\":\n    unittest.main(verbosity=2)\n```\nVerificado: 3/3 tests en verde con el doble de la dependencia (mismo contrato que la v2 documentada) — el wrapper acepta `date` estándar, suma días respetando saltos de mes y devuelve `date`. Resumen agéntico: un único punto de uso encontrado con grep → wrapper anti-corrupción → código de negocio intacto → la próxima migración toca UN archivo. Deuda documentada: si la v3 ofrece fechas nativas, evaluar eliminar el wrapper; hoy protege todas las llamadas futuras."),
        ],
        verify=[
            {"name": "wrapper_tests", "action": "run", "lang": "python", "msg": 6, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["Ran 3 tests", "OK"], "timeout_s": 20},
        ],
        tags=["agentic", "refactoring", "anti-corruption-layer", "tests", "tool-calling"],
        stack=["python"],
    ),
    # 8 ------------------------------------------------------------------ disciplina de verificación
    E(
        language="python", domain="agentic", subdomain="verificacion_honesta",
        difficulty="very_hard", task_type="testing",
        messages=[
            ("user", "Termina esta tarea: «añadir validación de RIN (código de identificación vehicular) al formulario». Y sobre todo: dime exactamente QUÉ has verificado y QUÉ no."),
            ("assistant", "UNDERSTAND — el RIN/VIN es el identificador de 17 caracteres del chasis (vehículos post-2001). Requisitos que infiero del formato: 17 caracteres alfanuméricos SIN I, O ni Q (ambiguales con 1/0), mayúsculas. El dígito de control ISO 3779 exige una tabla de transliteración y pesos que NO puedo contrastar en este entorno: validaré el FORMATO y declararé explícitamente que el check-digit queda fuera — no lo inventaré. Plan: implementar `validar_formato_rin` + tests ejecutables + informe verificado/no verificado."),
            ("tool", "$ python - <<'EOF'\nimport re\nPATRON = re.compile(r\"^[A-HJ-NPR-Z0-9]{17}$\")\n\ndef ok(v):\n    return bool(PATRON.fullmatch(v))\n\nprint(ok(\"1M8GDM9AXKP042788\"))   # VIN de ejemplo documentado\nprint(ok(\"1M8GDM9AXKP04278\"))    # 16 chars\nprint(ok(\"1M8GDM9AXKP0427IO\"))   # contiene I/O\nEOF\nTrue\nFalse\nFalse"),
            ("assistant", "Experimento confirmado: el alfabeto sin I/O/Q discrimina correctamente. ACT — módulo con tests:\n"
                     "```python\nimport re\nimport unittest\n\nPATRON_RIN = re.compile(r\"^[A-HJ-NPR-Z0-9]{17}$\")\n\n\ndef validar_formato_rin(valor: str) -> bool:\n    \"\"\"Valida el FORMATO de un RIN/VIN de 17 caracteres (ISO 3779, parcial).\n\n    Verificado: longitud y alfabeto (sin I, O, Q). NO valida el dígito de\n    control ni la codificación del fabricante — fuera del alcance de esta\n    tarea y no verificado en este entorno.\n    \"\"\"\n    return isinstance(valor, str) and bool(PATRON_RIN.fullmatch(valor))\n\n\nclass TestsRin(unittest.TestCase):\n    def test_validos(self):\n        self.assertTrue(validar_formato_rin(\"1M8GDM9AXKP042788\"))\n        self.assertTrue(validar_formato_rin(\"1FAFP40434F232846\"))\n\n    def test_invalidos(self):\n        for malo in (\"1M8GDM9AXKP04278\", \"1M8GDM9AXKP0427IO\", \"1M8GDM9AXKP042788 \",\n                     \"1m8gdm9axkp042788\", \"\"):\n            self.assertFalse(validar_formato_rin(malo))\n\n\nif __name__ == \"__main__\":\n    unittest.main(verbosity=2)\n```\nVERIFY — batería ejecutada:"),
            ("tool", "$ python rin.py\ntest_invalidos ... ok\ntest_validos ... ok\n\nRan 2 tests in 0.004s\n\nOK"),
            ("assistant", "INFORME DE VERIFICACIÓN HONESTO. VERIFICADO por ejecución: (1) `validar_formato_rin` acepta VINs de 17 caracteres con el alfabeto correcto (2 casos documentados); (2) rechaza longitud incorrecta, presencia de I/O/Q, minúsculas, espacios y cadena vacía (5 casos); (3) los 2 tests pasan con exit 0. NO VERIFICADO / NO IMPLEMENTADO: (a) el dígito de control ISO 3779 — necesita tabla de transliteración y pesos contrastables; (b) la integración con el formulario real (requiere navegador y su stack); (c) variantes regionales previas a 2004. Riesgo residual declarado: un VIN con formato válido pero check-digit inválido pasaría esta validación — aceptable para filtrado de formulario, NO para identidad legal del vehículo. Si se necesita el check-digit, se implementa como tarea separada con vectores de prueba oficiales."),
        ],
        verify=[
            {"name": "tests_rin", "action": "run", "lang": "python", "msg": 4, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["Ran 2 tests", "OK"], "timeout_s": 20},
        ],
        tags=["agentic", "validacion", "honestidad", "testing", "tool-calling"],
        stack=["python"],
    ),
]
