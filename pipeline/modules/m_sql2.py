"""m_sql2.py — Módulo SQL (parte 2, task 4-c) del dataset AI-ku_programming.

15 ejemplos COMPLEMENTARIOS a m_sql.py: mismos mecanismos avanzados de SQL
(SQLite) pero en dominios de negocio distintos (aerolíneas, gimnasio,
suscripciones SaaS, farmacia, eventos) y con ángulos que la parte 1 no tocaba.

Cobertura: CTE recursiva de rutas de vuelo con tarifa mínima, anti-join con
NOT EXISTS (pacientes sin tomas en el período), upsert ON CONFLICT idempotente
(debugging de carga diaria que acumula en re-ejecución), transacción con
rollback por condición de negocio + trigger de auditoría (RAISE ABORT vs
ROLLBACK explícito), EXPLAIN QUERY PLAN con índice que elimina SCAN
(bug=SCAN, fix=SEARCH con expect_stdout_contains), LEFT JOIN degradado a
INNER por WHERE sobre columna derecha, NULL en NOT IN que vacía resultados
(vs NOT EXISTS), fan-out m:n en facturación por equipos con prorrateo,
dedupe con ROW_NUMBER + DELETE (y UNIQUE índice preventivo), migración en dos
fases de columna NOT NULL con backfill y reconstrucción, lag/lead para
sesiones de usuario (gaps and islands), cohortes de retención mensual con
CTEs, reescritura de subconsulta correlacionada a window function con prueba
de equivalencia EXCEPT, migración de esquema legado (dedupe + cuarentena de
huérfanos + reconstrucción con FK/CHECK) y auditoría de integridad con FK
huérfanas (incluida la trampa de PRAGMA foreign_key_check sobre tablas sin
FK declaradas).

Verificación: acción "sql" del harness — setup = pares [msg, block] con el
DDL del mensaje user (msg 1), ejecución sobre SQLite :memory: y comprobación
con expect_stdout_contains / expect_stdout_not_contains. Consultas con
ORDER BY determinista. En los debugging hay paso de bug (msg=1, block de la
consulta rota, expect_stdout_not_contains del resultado correcto) y paso de
fix (msg=-1). Ningún bloque verificado lanza error SQL (el harness invalida
el paso si hay error): las demos con excepción viven en transcripts realistas
de mensajes tool.

Distribución: 5 implementation, 6 debugging, 2 optimization, 2 migration.
Dificultad: 1 medium, 7 hard, 5 very_hard, 2 extreme. recovery=True en 6.
"""

from schema import E

EXAMPLES = [
    # ---------------------------------------------------------------- I1 (very_hard)
    E(
        language="sql", domain="databases", subdomain="flight_route_planner",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Somos el equipo de pricing de una aerolínea low-cost. El buscador necesita, desde Madrid (MAD), el itinerario MÁS BARATO a cada aeropuerto alcanzable con nuestra red: si hay empate de tarifa gana el de menos escalas y, a igualdad total, el camino alfabéticamente menor. La red tiene vuelos de VUELTA (LIS→MAD, FAO→MAD), así que la consulta no puede colgarse ni revisitar aeropuertos. Red cargada:\n"
                     "```sql\n"
                     "CREATE TABLE flights (\n"
                     "  flight_no TEXT PRIMARY KEY,\n"
                     "  origin TEXT NOT NULL,\n"
                     "  destination TEXT NOT NULL,\n"
                     "  fare INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO flights VALUES\n"
                     " ('IB6211','MAD','LIS',85),('TP1033','LIS','OPO',42),\n"
                     " ('IB3450','MAD','OPO',160),('TP2231','LIS','FAO',55),\n"
                     " ('TP1177','FAO','OPO',38),('FR8812','MAD','FAO',70),\n"
                     " ('IB6212','LIS','MAD',85),('FR8813','FAO','MAD',66);\n"
                     "```\n"
                     "Entrega UNA consulta SQLite que devuelva destino, tarifa total, escalas y ruta, ordenada por destino."),
            ("assistant", "Estructura en dos capas: (1) CTE recursiva walk que enumera todos los CAMINOS SIMPLES desde MAD acumulando tarifa, escalas y el camino como texto '/MAD/LIS/...'; la terminación se garantiza podando con instr: solo extendemos hacia destinos que NO estén ya en el camino, comparando con delimitadores a ambos lados ('/LIS/') para que '/LIS/' no matchee dentro de otro código como '/LISBOA/' si existiera; (2) sobre walk, ROW_NUMBER particionado por aeropuerto ordenado por tarifa, escalas y camino, y nos quedamos con rn = 1. Antes de resolver mido cuántos caminos genera la red para acotar el coste."),
            ("tool", "sqlite> WITH RECURSIVE walk(airport, total_fare, legs, path) AS (SELECT 'MAD', 0, 0, '/MAD' UNION ALL SELECT f.destination, w.total_fare + f.fare, w.legs + 1, w.path || '/' || f.destination FROM walk w JOIN flights f ON f.origin = w.airport WHERE instr(w.path || '/', '/' || f.destination || '/') = 0) SELECT COUNT(*) FROM walk;\n"
                     "7\n"
                     "sqlite> -- 7 itinerarios simples; los tramos de vuelta IB6212/FR8813 (LIS->MAD, FAO->MAD)\n"
                     "sqlite> -- se podan porque MAD ya aparece en el camino: la recursión termina siempre"),
            ("assistant", "Siete itinerarios simples (el ciclo vía LIS→MAD y FAO→MAD queda podado). Consulta final:\n"
                     "```sql\n"
                     "WITH RECURSIVE walk(airport, total_fare, legs, path) AS (\n"
                     "  SELECT 'MAD', 0, 0, '/MAD'\n"
                     "  UNION ALL\n"
                     "  SELECT f.destination, w.total_fare + f.fare, w.legs + 1,\n"
                     "         w.path || '/' || f.destination\n"
                     "  FROM walk w\n"
                     "  JOIN flights f ON f.origin = w.airport\n"
                     "  WHERE instr(w.path || '/', '/' || f.destination || '/') = 0\n"
                     "),\n"
                     "best AS (\n"
                     "  SELECT airport, total_fare, legs, path,\n"
                     "         ROW_NUMBER() OVER (PARTITION BY airport\n"
                     "                            ORDER BY total_fare, legs, path) AS rn\n"
                     "  FROM walk\n"
                     ")\n"
                     "SELECT airport, total_fare, legs, SUBSTR(path, 2) AS ruta\n"
                     "FROM best\n"
                     "WHERE rn = 1 AND airport <> 'MAD'\n"
                     "ORDER BY airport;\n"
                     "```\n"
                     "Traza: a OPO se llega directo por 160, vía LIS por 127 y vía FAO por 70+38 = 108 → gana MAD/FAO/OPO con 2 escalas... ojo, 1 escala técnica; el campo legs cuenta ARISTAS (2 vuelos). La poda con instr es O(longitud del camino) por fila; en redes con cientos de aeropuertos conviene añadir además una cota de precio (WHERE w.total_fare + f.fare < 500) o de escalas (w.legs < 4) para no enumerar caminos absurdos, y para producción real un Dijkstra externo. El ORDER BY total_fare, legs, path hace el desempate reproducible; SUBSTR(path, 2) solo quita la barra inicial."),
        ],
        verify=[
            {"name": "rutas_tarifa_minima", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["FAO|70|1|MAD/FAO", "LIS|85|1|MAD/LIS",
                                        "OPO|108|2|MAD/FAO/OPO"],
             "expect_stdout_not_contains": ["MAD|0|0"]},
        ],
        tags=["sql", "recursive-cte", "graph", "routes", "airlines"],
    ),
    # ---------------------------------------------------------------- I2 (medium)
    E(
        language="sql", domain="databases", subdomain="anti_join_inactive_patients",
        difficulty="medium", task_type="implementation",
        messages=[
            ("user", "Farmacia con varias sucursales: el servicio de adherencia terapéutica necesita la lista de pacientes que NO han recogido medicación en junio de 2024, con la fecha de su última recogida histórica (puede ser NULL si nunca han recogido). Tablas:\n"
                     "```sql\n"
                     "CREATE TABLE patients (\n"
                     "  patient_id INTEGER PRIMARY KEY,\n"
                     "  full_name TEXT NOT NULL,\n"
                     "  phone TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE fillings (\n"
                     "  filling_id INTEGER PRIMARY KEY,\n"
                     "  patient_id INTEGER NOT NULL,\n"
                     "  drug TEXT NOT NULL,\n"
                     "  filled_on TEXT NOT NULL\n"
                     ");\n"
                     "INSERT INTO patients VALUES (1,'Lucia Marin','600-111'),(2,'Pablo Serrano','600-222'),(3,'Elena Prats','600-333'),(4,'Marc Vidal','600-444');\n"
                     "INSERT INTO fillings VALUES (1,1,'metformina','2024-06-03'),(2,2,'atorvastatina','2024-05-12'),(3,2,'omeprazol','2024-04-28'),(4,3,'levotiroxina','2024-06-11');\n"
                     "```\n"
                     "Devuelve patient_id, nombre, teléfono y última recogida, ordenado por patient_id."),
            ("assistant", "Es un anti-join: pacientes para los que NO existe ninguna recogida en [2024-06-01, 2024-07-01). Uso NOT EXISTS con rango semiabierto (>= inicio AND < fin), que es seguro con fechas TEXT ISO y no depende de si la columna tuviera hora. La última recogida la resuelvo con una subconsulta escalar correlacionada por paciente; para Marc (sin recogidas) devolverá NULL y el harness lo imprime como celda vacía. Primero fijo los hechos con una sonda."),
            ("tool", "sqlite> SELECT patient_id, COUNT(*) AS tomas FROM fillings GROUP BY patient_id ORDER BY patient_id;\n"
                     "1|1\n"
                     "2|2\n"
                     "3|1\n"
                     "sqlite> SELECT COUNT(*) FROM fillings WHERE filled_on >= '2024-06-01' AND filled_on < '2024-07-01';\n"
                     "2\n"
                     "sqlite> -- junio tiene 2 tomas (pacientes 1 y 3); los pacientes 2 y 4 no pasaron por farmacia"),
            ("assistant", "Consulta final:\n"
                     "```sql\n"
                     "SELECT p.patient_id, p.full_name, p.phone,\n"
                     "       (SELECT MAX(f.filled_on) FROM fillings f\n"
                     "         WHERE f.patient_id = p.patient_id) AS last_pickup\n"
                     "FROM patients p\n"
                     "WHERE NOT EXISTS (\n"
                     "  SELECT 1 FROM fillings f\n"
                     "  WHERE f.patient_id = p.patient_id\n"
                     "    AND f.filled_on >= '2024-06-01'\n"
                     "    AND f.filled_on <  '2024-07-01'\n"
                     ")\n"
                     "ORDER BY p.patient_id;\n"
                     "```\n"
                     "Dos alternativas equivalentes y sus matices: LEFT JOIN ... IS NULL (JOIN por paciente y rango de junio, filtrar IS NULL) es igual de correcta pero duplica la lógica del rango; NOT IN (subconsulta de pacientes con recogida en junio) la verás más adelante en este dataset y tiene una trampa grave con NULLs — NO la uses contra columnas anulables. NOT EXISTS es la forma canónica: no multiplica filas, usa índices por (patient_id, filled_on) y su semántica es inmune a NULL. En el resultado, la fila de Marc termina con celda vacía: el NULL de last_pickup es correcto y el informe debe tratarlo como «sin historial», no como error."),
        ],
        verify=[
            {"name": "anti_join_adherencia", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2|Pablo Serrano|600-222|2024-05-12",
                                        "4|Marc Vidal|600-444|"],
             "expect_stdout_not_contains": ["1|Lucia Marin|600-111",
                                            "3|Elena Prats|600-333"]},
        ],
        tags=["sql", "anti-join", "not-exists", "pharmacy", "cohortes"],
    ),
    # ---------------------------------------------------------------- D1 (hard)
    E(
        language="sql", domain="databases", subdomain="upsert_idempotency_debug",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "La carga nocturna de estados de vuelo falló a medias anoche y Operations reenvió el fichero del feed COMPLETO. Ahora el dashboard muestra retrasos imposibles (un vuelo con 110 minutos de retraso cuando el feed dice 30). Esquema y feed:\n"
                     "```sql\n"
                     "CREATE TABLE flight_status (\n"
                     "  flight_no TEXT NOT NULL,\n"
                     "  status_date TEXT NOT NULL,\n"
                     "  delay_min INTEGER NOT NULL DEFAULT 0,\n"
                     "  status TEXT NOT NULL DEFAULT 'on_time',\n"
                     "  updated_seq INTEGER NOT NULL DEFAULT 0,\n"
                     "  PRIMARY KEY (flight_no, status_date)\n"
                     ");\n"
                     "CREATE TABLE status_feed (\n"
                     "  seq INTEGER PRIMARY KEY,\n"
                     "  flight_no TEXT NOT NULL,\n"
                     "  status_date TEXT NOT NULL,\n"
                     "  delay_min INTEGER NOT NULL,\n"
                     "  status TEXT NOT NULL\n"
                     ");\n"
                     "INSERT INTO status_feed VALUES (1,'IB6211','2024-06-10',25,'delayed'),(2,'FR8812','2024-06-10',0,'on_time'),(3,'IB3450','2024-06-10',40,'delayed'),(4,'IB6211','2024-06-10',30,'delayed');\n"
                     "```\n"
                     "```sql\n"
                     "INSERT INTO flight_status (flight_no, status_date, delay_min, status, updated_seq)\n"
                     "SELECT flight_no, status_date, delay_min, status, seq AS updated_seq FROM status_feed WHERE seq > 0\n"
                     "ON CONFLICT (flight_no, status_date) DO UPDATE SET\n"
                     "  delay_min = flight_status.delay_min + excluded.delay_min,\n"
                     "  status = excluded.status,\n"
                     "  updated_seq = excluded.updated_seq;\n"
                     "INSERT INTO flight_status (flight_no, status_date, delay_min, status, updated_seq)\n"
                     "SELECT flight_no, status_date, delay_min, status, seq AS updated_seq FROM status_feed WHERE seq > 0\n"
                     "ON CONFLICT (flight_no, status_date) DO UPDATE SET\n"
                     "  delay_min = flight_status.delay_min + excluded.delay_min,\n"
                     "  status = excluded.status,\n"
                     "  updated_seq = excluded.updated_seq;\n"
                     "SELECT flight_no, delay_min, status, updated_seq FROM flight_status ORDER BY flight_no;\n"
                     "```\n"
                     "El segundo INSERT simula el reenvío del mismo fichero. Esperado tras carga + reenvío: IB6211 con 30 (la línea más reciente del feed manda), no 110."),
            ("assistant", "Síntoma: retrasos inflados exactamente tras el reenvío. Hipótesis 1: el feed trae el vuelo duplicado con datos contradictorios. Hipótesis 2: la carga no es idempotente — el ON CONFLICT ACUMULA (delay_min = delay_min + excluded.delay_min), así que cada re-ejecución vuelve a sumar las mismas líneas. El acumular era razonable si el feed fuese incremental (deltas), pero el feed es un SNAPSHOT por seq: la línea con seq mayor sustituye a la anterior. Sonda: mirar el feed por vuelo."),
            ("tool", "sqlite> SELECT flight_no, seq, delay_min, status FROM status_feed ORDER BY flight_no, seq;\n"
                     "FR8812|2|0|on_time\n"
                     "IB3450|3|40|delayed\n"
                     "IB6211|1|25|delayed\n"
                     "IB6211|4|30|delayed\n"
                     "sqlite> SELECT COUNT(*) FROM status_feed;\n"
                     "4\n"
                     "sqlite> -- IB6211 tiene DOS líneas (seq 1 y 4): es un log ordenado por seq, no un delta\n"
                     "sqlite> -- reenviar el fichero tras un error es operación normal: la carga debe tolerarlo"),
            ("assistant", "La sonda refuta la hipótesis 1 (las dos líneas de IB6211 son legítimas: 25 min reportado en seq 1 y 30 min confirmado en seq 4) y confirma la 2: el DO UPDATE suma, de modo que la primera pasada deja IB6211 en 25+30 = 55 y el reenvío lo deja en 55+25+30 = 110. Causa raíz: confundir feed incremental (acumularía) con feed snapshot-versionado (sustituye). La idempotencia se consigue con un guard de versión en la propia cláusula ON CONFLICT: el SELECT del INSERT proyecta seq AS updated_seq (excluded expone las columnas DEL DESTINO, no las del origen), y solo aplicamos la línea si excluded.updated_seq es estrictamente mayor que la última aplicada. Corrección (misma carga + reenvío, resultado estable):\n"
                     "```sql\n"
                     "INSERT INTO flight_status (flight_no, status_date, delay_min, status, updated_seq)\n"
                     "SELECT flight_no, status_date, delay_min, status, seq AS updated_seq FROM status_feed WHERE seq > 0\n"
                     "ON CONFLICT (flight_no, status_date) DO UPDATE SET\n"
                     "  delay_min = excluded.delay_min,\n"
                     "  status = excluded.status,\n"
                     "  updated_seq = excluded.updated_seq\n"
                     "WHERE excluded.updated_seq > flight_status.updated_seq;\n"
                     "INSERT INTO flight_status (flight_no, status_date, delay_min, status, updated_seq)\n"
                     "SELECT flight_no, status_date, delay_min, status, seq AS updated_seq FROM status_feed WHERE seq > 0\n"
                     "ON CONFLICT (flight_no, status_date) DO UPDATE SET\n"
                     "  delay_min = excluded.delay_min,\n"
                     "  status = excluded.status,\n"
                     "  updated_seq = excluded.updated_seq\n"
                     "WHERE excluded.updated_seq > flight_status.updated_seq;\n"
                     "SELECT flight_no, delay_min, status, updated_seq FROM flight_status ORDER BY flight_no;\n"
                     "```\n"
                     "Traza: en la primera pasada seq 1 inserta (25) y seq 4 sustituye (30); en el reenvío todos los guard fallan (1 > 4, 3 > 3, 4 > 4 son falsos) y la tabla no se mueve: N reenvíos dejan el mismo estado. Nota de parsing: con INSERT ... SELECT el ON CONFLICT exige WHERE en el SELECT para desambiguar; y si el negocio pidiera «acumular solo los deltas nuevos», el guard correcto sería sobre un marcador de líneas procesadas, nunca sumar a ciegas el snapshot entero."),
        ],
        verify=[
            {"name": "bug_reenvio_acumula", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["IB3450|80|delayed|3", "IB6211|110|delayed|4"],
             "expect_stdout_not_contains": ["IB6211|30|delayed|4"]},
            {"name": "fix_guard_por_seq", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["FR8812|0|on_time|2", "IB3450|40|delayed|3",
                                        "IB6211|30|delayed|4"],
             "expect_stdout_not_contains": ["IB3450|80", "IB6211|110"]},
        ],
        tags=["sql", "upsert", "on-conflict", "idempotency", "debugging", "airlines"],
    ),
    # ---------------------------------------------------------------- I3 (very_hard)
    E(
        language="sql", domain="databases", subdomain="sessionization_lag_lead",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Producto de analítica SaaS: necesitamos RECONSTRUIR SESIONES a partir del event stream. Definición de negocio: dos eventos del mismo usuario pertenecen a la misma sesión si están separados por MENOS O IGUAL de 30 minutos (1800 s); una pausa mayor abre sesión nueva. Con eso, entrega por sesión: usuario, nº de sesión (empezando en 1 por usuario), inicio, fin, nº de eventos y duración en minutos. Eventos del 10 de junio:\n"
                     "```sql\n"
                     "CREATE TABLE events (\n"
                     "  event_id INTEGER PRIMARY KEY,\n"
                     "  user_id TEXT NOT NULL,\n"
                     "  occurred_at TEXT NOT NULL,\n"
                     "  action TEXT NOT NULL\n"
                     ");\n"
                     "INSERT INTO events VALUES\n"
                     " (1,'u1','2024-06-10 08:00:00','login'),\n"
                     " (2,'u1','2024-06-10 08:30:00','checkout'),\n"
                     " (3,'u1','2024-06-10 09:05:00','login'),\n"
                     " (4,'u1','2024-06-10 09:20:00','search'),\n"
                     " (5,'u2','2024-06-10 10:00:00','login'),\n"
                     " (6,'u2','2024-06-10 12:30:00','login');\n"
                     "```\n"
                     "Casos límite que debe cubrir: la pausa de EXACTAMENTE 30 min (evento 2) sigue siendo la misma sesión, y los eventos sueltos de u2 forman sesiones de 1 evento y 0 minutos."),
            ("assistant", "Patrón gaps and islands en dos saltos: (1) con LAG obtengo el instante del evento anterior DEL MISMO USUARIO (PARTITION BY user_id es obligatorio: sin él, el LAG cruzaría usuarios y fusionaría sesiones ajenas) y marco new_session = 1 cuando la diferencia supera 1800 s o no hay evento previo; (2) la suma acumulada de new_session (SUM OVER con ROWS UNBOUNDED PRECEDING) genera el identificador de isla session_no, estable mientras la brecha no se supere. La aritmética temporal la hago con strftime('%s', ...) que devuelve SEGUNDOS enteros: con julianday el mismo cálculo produce floats con error de redondeo y la comparación <= 1800 se rompe justo en el caso límite de los 30 minutos. Sonda del límite:"),
            ("tool", "sqlite> SELECT strftime('%s', '2024-06-10 08:30:00') - strftime('%s', '2024-06-10 08:00:00') AS gap_s;\n"
                     "1800\n"
                     "sqlite> -- 1800 s = 30 min exactos: con <= sigue siendo la MISMA sesion\n"
                     "sqlite> SELECT julianday('2024-06-10 08:30:00') - julianday('2024-06-10 08:00:00');\n"
                     "0.0208333333333333\n"
                     "sqlite> -- en dias: 0.0208333... * 86400 = 1800.0000000002 en algunos calculos: cuidado"),
            ("assistant", "Consulta final:\n"
                     "```sql\n"
                     "WITH gaps AS (\n"
                     "  SELECT user_id, occurred_at, action,\n"
                     "         CASE\n"
                     "           WHEN (strftime('%s', occurred_at)\n"
                     "                 - strftime('%s', LAG(occurred_at) OVER (\n"
                     "                     PARTITION BY user_id ORDER BY occurred_at))) <= 1800\n"
                     "           THEN 0 ELSE 1\n"
                     "         END AS new_session\n"
                     "  FROM events\n"
                     "),\n"
                     "flagged AS (\n"
                     "  SELECT user_id, occurred_at, action, new_session,\n"
                     "         SUM(new_session) OVER (\n"
                     "           PARTITION BY user_id ORDER BY occurred_at\n"
                     "           ROWS UNBOUNDED PRECEDING) AS session_no\n"
                     "  FROM gaps\n"
                     ")\n"
                     "SELECT user_id, session_no,\n"
                     "       MIN(occurred_at) AS session_start,\n"
                     "       MAX(occurred_at) AS session_end,\n"
                     "       COUNT(*) AS eventos,\n"
                     "       (strftime('%s', MAX(occurred_at)) - strftime('%s', MIN(occurred_at))) / 60 AS duracion_min\n"
                     "FROM flagged\n"
                     "GROUP BY user_id, session_no\n"
                     "ORDER BY user_id, session_no;\n"
                     "```\n"
                     "Traza u1: e1 abre sesión 1 (LAG NULL → rama ELSE = 1); e2 está a 1800 s exactos → misma sesión (el requisito dice ≤); e3 está a 2100 s → abre la 2; e4 a 900 s se queda en la 2. u2: cada evento aislado es su propia isla (1|10:00 y 2|12:30, 0 minutos). Variante equivalente con LEAD: marcar cierre de sesión cuando el SIGUIENTE evento dista > 1800 y luego numerar hacia atrás — útil cuando el origen del corte se define por el final. Rendimiento: un índice (user_id, occurred_at) convierte el window sort en scan ordenado; sin él, SQLite ordena el dataset entero dos veces (una por LAG, otra por SUM)."),
        ],
        verify=[
            {"name": "sesiones_gaps_islands", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": [
                 "u1|1|2024-06-10 08:00:00|2024-06-10 08:30:00|2|30",
                 "u1|2|2024-06-10 09:05:00|2024-06-10 09:20:00|2|15",
                 "u2|1|2024-06-10 10:00:00|2024-06-10 10:00:00|1|0",
                 "u2|2|2024-06-10 12:30:00|2024-06-10 12:30:00|1|0"]},
        ],
        tags=["sql", "window-functions", "lag-lead", "gaps-islands", "sessions", "saas"],
    ),
    # ---------------------------------------------------------------- I5 (hard)
    E(
        language="sql", domain="databases", subdomain="monthly_cohort_retention",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Cadena de gimnasios: dirección quiere la MATRIZ DE RETENCIÓN por cohorte de alta. Cohorte = mes de alta del socio (joined_month). Para cada cohorte: tamaño, socios activos (con algún check-in) en el mes de alta (m0), al mes siguiente (m1) y al segundo (m2), y los porcentajes de retención m1 y m2 como enteros (redondeo por truncado). Datos de abril y mayo:\n"
                     "```sql\n"
                     "CREATE TABLE members (\n"
                     "  member_id INTEGER PRIMARY KEY,\n"
                     "  full_name TEXT NOT NULL,\n"
                     "  joined_month TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE checkins (\n"
                     "  checkin_id INTEGER PRIMARY KEY,\n"
                     "  member_id INTEGER NOT NULL,\n"
                     "  day TEXT NOT NULL\n"
                     ");\n"
                     "INSERT INTO members VALUES (1,'Lucia Marin','2024-04'),(2,'Pablo Serrano','2024-04'),(3,'Elena Prats','2024-04'),(4,'Marc Vidal','2024-05'),(5,'Nuria Camps','2024-05');\n"
                     "INSERT INTO checkins VALUES (1,1,'2024-04-08'),(2,1,'2024-05-06'),(3,1,'2024-06-03'),(4,2,'2024-04-15'),(5,3,'2024-04-20'),(6,3,'2024-06-10'),(7,4,'2024-05-02'),(8,4,'2024-05-30'),(9,5,'2024-05-11'),(10,5,'2024-06-14');\n"
                     "```\n"
                     "Ojo: Marc hizo DOS check-ins en mayo y cuentan como UN socio activo. Ordena por cohorte."),
            ("assistant", "Peligro principal: los check-ins son eventos, no socios — hay que DEDUPLICAR el par (socio, mes de actividad) ANTES de agregar, o Marc inflará su cohorte. Estructura: activity con DISTINCT produce las parejas socio/mes activo; offsets calcula el desfase en meses restando (año, mes) convertido a enteros, fórmula (año_act - año_alta)*12 + (mes_act - mes_alta) que no se rompe al cambiar de año; sizes fija el denominador con TODOS los socios dados de alta (activos o no); el SELECT final pivota m0/m1/m2 con SUM(CASE) y los porcentajes salen de la división ENTERA de SQLite (100*1/3 = 33) — el truncado es exactamente lo pedido; si quisieras redondeo, ROUND devuelve float y la salida cambiaría de formato. Sonda que justifica el DISTINCT:"),
            ("tool", "sqlite> SELECT member_id, COUNT(*) AS checkins FROM checkins GROUP BY member_id ORDER BY member_id;\n"
                     "1|3\n"
                     "2|1\n"
                     "3|2\n"
                     "4|2\n"
                     "5|2\n"
                     "sqlite> SELECT COUNT(*) FROM checkins WHERE member_id = 4 AND day LIKE '2024-05%';\n"
                     "2\n"
                     "sqlite> -- marc hizo 2 checkins en mayo: sin DISTINCT la cohorte 2024-05 contaria 3 en m0"),
            ("assistant", "Consulta final:\n"
                     "```sql\n"
                     "WITH activity AS (\n"
                     "  SELECT DISTINCT c.member_id, m.joined_month, substr(c.day, 1, 7) AS active_month\n"
                     "  FROM checkins c\n"
                     "  JOIN members m ON m.member_id = c.member_id\n"
                     "),\n"
                     "offsets AS (\n"
                     "  SELECT member_id, joined_month, active_month,\n"
                     "         (CAST(substr(active_month, 1, 4) AS INTEGER)\n"
                     "        - CAST(substr(joined_month, 1, 4) AS INTEGER)) * 12\n"
                     "       + (CAST(substr(active_month, 6, 2) AS INTEGER)\n"
                     "        - CAST(substr(joined_month, 6, 2) AS INTEGER)) AS month_offset\n"
                     "  FROM activity\n"
                     "),\n"
                     "sizes AS (\n"
                     "  SELECT joined_month, COUNT(*) AS cohort_size\n"
                     "  FROM members GROUP BY joined_month\n"
                     ")\n"
                     "SELECT o.joined_month, s.cohort_size,\n"
                     "       SUM(CASE WHEN o.month_offset = 0 THEN 1 ELSE 0 END) AS m0,\n"
                     "       SUM(CASE WHEN o.month_offset = 1 THEN 1 ELSE 0 END) AS m1,\n"
                     "       SUM(CASE WHEN o.month_offset = 2 THEN 1 ELSE 0 END) AS m2,\n"
                     "       100 * SUM(CASE WHEN o.month_offset = 1 THEN 1 ELSE 0 END) / s.cohort_size AS pct_m1,\n"
                     "       100 * SUM(CASE WHEN o.month_offset = 2 THEN 1 ELSE 0 END) / s.cohort_size AS pct_m2\n"
                     "FROM offsets o\n"
                     "JOIN sizes s ON s.joined_month = o.joined_month\n"
                     "GROUP BY o.joined_month, s.cohort_size\n"
                     "ORDER BY o.joined_month;\n"
                     "```\n"
                     "Verificación cruzada: cohorte 2024-04 (Lucia, Pablo, Elena): m0 = 3 (los tres vinieron en abril), m1 = 1 (solo Lucia en mayo) → 33%, m2 = 2 (Lucia y Elena en junio) → 66%. Cohorte 2024-05: m0 = 2, m1 = 1 (Nuria) → 50%, m2 = 0 → 0%. Dos decisiones de diseño a documentar: el denominador usa la tabla members (cohortes honestas aunque nadie vuelva) y un socio que se da de baja y vuelve aparece activo en ambos meses — si el negocio exige «activo continuo», la definición cambia y con ella el SQL."),
        ],
        verify=[
            {"name": "matriz_retencion", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2024-04|3|3|1|2|33|66", "2024-05|2|2|1|0|50|0"]},
        ],
        tags=["sql", "cohorts", "retention", "cte", "gym", "analytics"],
    ),
    # ---------------------------------------------------------------- O1 (very_hard)
    E(
        language="sql", domain="databases", subdomain="explain_plan_index",
        difficulty="very_hard", task_type="optimization",
        messages=[
            ("user", "El panel de operaciones de la aerolínea tiene una consulta que consulta retrasos por origen y fecha y se ha vuelto lenta según crece flight_legs. El plan de la consulta actual está en el segundo bloque. Demuestra con EXPLAIN QUERY PLAN que el problema es un barrido completo, crea el índice adecuado y demuestra que el plan pasa a búsqueda por índice SIN ordenación temporal. Datos:\n"
                     "```sql\n"
                     "CREATE TABLE flight_legs (\n"
                     "  leg_id INTEGER PRIMARY KEY,\n"
                     "  flight_no TEXT NOT NULL,\n"
                     "  origin TEXT NOT NULL,\n"
                     "  destination TEXT NOT NULL,\n"
                     "  status_date TEXT NOT NULL,\n"
                     "  delay_min INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO flight_legs VALUES\n"
                     " (1,'IB6211','MAD','LIS','2024-06-10',25),(2,'IB3450','MAD','OPO','2024-06-10',40),\n"
                     " (3,'FR8812','MAD','FAO','2024-06-10',0),(4,'UX1151','MAD','AGP','2024-06-10',15),\n"
                     " (5,'IB6211','MAD','LIS','2024-06-09',10),(6,'VY7001','BCN','IBZ','2024-06-10',5),\n"
                     " (7,'IB6211','MAD','LIS','2024-06-11',0),(8,'FR8812','MAD','FAO','2024-06-11',20),\n"
                     " (9,'IB3450','MAD','OPO','2024-06-11',60),(10,'VY7002','IBZ','BCN','2024-06-10',0);\n"
                     "```\n"
                     "```sql\n"
                     "EXPLAIN QUERY PLAN\n"
                     "SELECT destination, delay_min FROM flight_legs\n"
                     "WHERE origin = 'MAD' AND status_date = '2024-06-10'\n"
                     "ORDER BY delay_min;\n"
                     "```\n"
                     "Consulta objetivo: SELECT destination, delay_min FROM flight_legs WHERE origin = 'MAD' AND status_date = '2024-06-10' ORDER BY delay_min;"),
            ("assistant", "Diagnóstico esperado y cómo leerlo: el plan actual dice «SCAN flight_legs» (lee TODAS las filas y filtra después) y añade «USE TEMP B-TREE FOR ORDER BY» (ordena en memoria el resultado). Es O(N log N) por consulta con N creciendo cada día. El índice correcto debe servir el predicado de IGUALDAD (origin, status_date) como prefijo y el ORDER BY delay_min como siguiente columna — así el plan usa el índice en orden y el resultado ya sale ordenado sin temp b-tree. Si además incluyo destination como cuarta columna, la consulta no toca la tabla: índice CUBRIENTE (covering). Primero documentamos el plan malo desde el sandbox:"),
            ("tool", "sqlite> EXPLAIN QUERY PLAN SELECT destination, delay_min FROM flight_legs WHERE origin = 'MAD' AND status_date = '2024-06-10' ORDER BY delay_min;\n"
                     "3|0|216|SCAN flight_legs\n"
                     "14|0|0|USE TEMP B-TREE FOR ORDER BY\n"
                     "sqlite> -- SCAN = barrido completo + TEMP B-TREE = ordenacion extra: dos costes evitables\n"
                     "sqlite> -- un indice (origin) solo NO bastaria: status_date quedaria fuera del seek y el\n"
                     "sqlite> -- ORDER BY seguiria necesitando ordenacion"),
            ("assistant", "Índice compuesto pensado para ESTA consulta: igualdad (origin, status_date), orden (delay_min) y cobertura (destination). Tras crearlo, el mismo EXPLAIN debe decir SEARCH ... USING COVERING INDEX y desaparecer el temp b-tree:\n"
                     "```sql\n"
                     "CREATE INDEX idx_legs_origin_date\n"
                     "  ON flight_legs(origin, status_date, delay_min, destination);\n"
                     "EXPLAIN QUERY PLAN\n"
                     "SELECT destination, delay_min FROM flight_legs\n"
                     "WHERE origin = 'MAD' AND status_date = '2024-06-10'\n"
                     "ORDER BY delay_min;\n"
                     "SELECT destination, delay_min FROM flight_legs\n"
                     "WHERE origin = 'MAD' AND status_date = '2024-06-10'\n"
                     "ORDER BY delay_min;\n"
                     "```\n"
                     "Lectura del plan nuevo: «SEARCH flight_legs USING COVERING INDEX idx_legs_origin_date (origin=? AND status_date=?)» — busca por el prefijo de igualdad, recorre las entradas ya ordenadas por delay_min (columna 3 del índice) y no visita la tabla porque destination (columna 4) viaja en el índice; sin USE TEMP B-TREE. Reglas de composición: columnas de igualdad primero (en cualquier orden entre sí), columna de orden después, y al final las que solo se leen — si mezclas el ORDER BY antes de una columna de igualdad, el índice no puede servir el orden y vuelve el b-tree. Mantenimiento: cada índice cuesta en INSERT/UPDATE y espacio; índices que nadie busca se detectan con estadísticas de uso del motor, no por intuición."),
        ],
        verify=[
            {"name": "bug_plan_con_scan", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["SCAN flight_legs", "USE TEMP B-TREE FOR ORDER BY"]},
            {"name": "fix_plan_con_search", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["SEARCH flight_legs USING COVERING INDEX idx_legs_origin_date",
                                        "FAO|0", "AGP|15", "LIS|25", "OPO|40"],
             "expect_stdout_not_contains": ["SCAN", "USE TEMP B-TREE"]},
        ],
        tags=["sql", "explain-query-plan", "index", "covering-index", "optimization", "airlines"],
    ),
    # ---------------------------------------------------------------- O2 (extreme)
    E(
        language="sql", domain="databases", subdomain="cumulative_rewrite_equivalence",
        difficulty="extreme", task_type="optimization",
        messages=[
            ("user", "El área de datos del gimnasio reporta el ACUMULADO de asistencias por día del mes con esta consulta, y a medida que crece el histórico se vuelve lenta (la subconsulta escalar relee la tabla por cada día). Necesito la versión rápida con window functions y PRUEBA DE EQUIVALENCIA formal entre ambas (cero divergencias), porque el informe se consume en contabilidad y no admitimos discrepancias:\n"
                     "```sql\n"
                     "CREATE TABLE trainers (\n"
                     "  trainer_id INTEGER PRIMARY KEY,\n"
                     "  name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE sessions (\n"
                     "  session_id INTEGER PRIMARY KEY,\n"
                     "  trainer_id INTEGER NOT NULL REFERENCES trainers(trainer_id),\n"
                     "  day TEXT NOT NULL,\n"
                     "  attendees INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO trainers VALUES (1,'Mireia Roca'),(2,'Joan Petit'),(3,'Pau Vidal');\n"
                     "INSERT INTO sessions VALUES (1,1,'2024-06-03',25),(2,2,'2024-06-03',20),(3,1,'2024-06-04',30),(4,3,'2024-06-05',10),(5,2,'2024-06-05',15);\n"
                     "```\n"
                     "```sql\n"
                     "SELECT s.day,\n"
                     "       (SELECT SUM(attendees) FROM sessions s2 WHERE s2.day <= s.day) AS acumulado\n"
                     "FROM (SELECT DISTINCT day FROM sessions) s\n"
                     "ORDER BY s.day;\n"
                     "```\n"
                     "Esa es la versión lenta de referencia (correcta, pero O(días × filas))."),
            ("assistant", "Coste de la referencia: por cada día distinto ejecuta una subconsulta que relee y suma TODAS las sesiones hasta ese día — O(D·N) con N filas; el plan la marca como CORRELATED SCALAR SUBQUERY y dentro vuelve a escanear sessions. Reescritura: primero agrego el total por día (GROUP BY, una pasada), y sobre esa CTE pequeña aplico SUM() OVER (ORDER BY day ROWS UNBOUNDED PRECEDING), que es una pasada más: O(N + D). Detalle fino: la ventana DEBE ir sobre los totales diarios, no sobre las filas crudas — si sumas acumulado sobre sessions sin agregar, los días con varias clases acumulan clase a clase y el informe ya no cuadra. Equivalencia: en lugar de comparar a ojo, ejecuto ambas y las resto con EXCEPT en LOS DOS SENTIDOS; cero filas divergentes = misma función, no misma casualidad. Sonda del plan lento:"),
            ("tool", "sqlite> EXPLAIN QUERY PLAN SELECT s.day, (SELECT SUM(attendees) FROM sessions s2 WHERE s2.day <= s.day) AS acumulado FROM (SELECT DISTINCT day FROM sessions) s ORDER BY s.day;\n"
                     "2|0|0|SCAN s\n"
                     "4|0|0|LIST SUBQUERY\n"
                     "9|0|0|SCAN sessions\n"
                     "sqlite> -- la subconsulta escalar re-escanea sessions POR CADA dia distinto: O(D*N)\n"
                     "sqlite> SELECT COUNT(*) AS dias FROM (SELECT DISTINCT day FROM sessions);\n"
                     "3\n"),
            ("assistant", "Versión rápida + prueba de equivalencia bidireccional:\n"
                     "```sql\n"
                     "WITH daily AS (\n"
                     "  SELECT day, SUM(attendees) AS attendees\n"
                     "  FROM sessions\n"
                     "  GROUP BY day\n"
                     ")\n"
                     "SELECT day,\n"
                     "       SUM(attendees) OVER (ORDER BY day ROWS UNBOUNDED PRECEDING) AS acumulado\n"
                     "FROM daily\n"
                     "ORDER BY day;\n"
                     "WITH slow AS (\n"
                     "  SELECT s.day,\n"
                     "         (SELECT SUM(attendees) FROM sessions s2 WHERE s2.day <= s.day) AS acumulado\n"
                     "  FROM (SELECT DISTINCT day FROM sessions) s\n"
                     "),\n"
                     "fast AS (\n"
                     "  SELECT day, SUM(attendees) OVER (ORDER BY day ROWS UNBOUNDED PRECEDING) AS acumulado\n"
                     "  FROM (SELECT day, SUM(attendees) AS attendees FROM sessions GROUP BY day)\n"
                     ")\n"
                     "SELECT COUNT(*) AS divergencias\n"
                     "FROM (SELECT day, acumulado FROM slow\n"
                     "      EXCEPT\n"
                     "      SELECT day, acumulado FROM fast);\n"
                     "```\n"
                     "Resultado: 45, 75, 100 el mismo día que la referencia (03: 25+20; 04: +30; 05: +25) y divergencias = 0. Notas de frontera: (1) EXCEPT compara CONJUNTOS — si dos días pudieran repetir pareja (day, acumulado), la prueba se debilitaría; el patrón robusto es EXCEPT sobre la tupla completa con claves únicas, o FULL OUTER JOIN por day comparando valores (en SQLite, LEFT+UNION por ambos lados); (2) ROWS UNBOUNDED PRECEDING es deliberado: con el frame por defecto (RANGE), un empate de day duplicaría valores en la ventana — aquí day es clave única de la CTE y no ocurre, pero la disciplina de frames de la parte 1 aplica igual; (3) si el informe necesita el acumulado REINICIADO por mes, se añade PARTITION BY strftime('%Y-%m', day) a la ventana — el coste no cambia."),
        ],
        verify=[
            {"name": "fast_y_equivalencia", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2024-06-03|45", "2024-06-04|75", "2024-06-05|100"]},
        ],
        tags=["sql", "window-functions", "correlated-subquery", "equivalence", "optimization", "gym"],
    ),
    # ---------------------------------------------------------------- M1 (very_hard)
    E(
        language="sql", domain="databases", subdomain="migration_notnull_two_phase",
        difficulty="very_hard", task_type="migration",
        messages=[
            ("user", "SaaS de suscripciones: el producto ha añadido el ciclo de facturación y necesitamos la columna billing_cycle como NOT NULL con dominio controlado ('monthly' | 'annual'), SIN ventana de parada. Contrato de migración en dos fases: fase 1, añadir la columna con DEFAULT (metadato instantáneo, no reescribe filas) y rellenar por política: price_cents >= 12000 → 'annual'; fase 2, reconstruir la tabla para imponer NOT NULL + CHECK sin default (la base de referencia deja de tolerar nulos ni ciclos inventados). Estado actual:\n"
                     "```sql\n"
                     "CREATE TABLE subscriptions (\n"
                     "  subscription_id INTEGER PRIMARY KEY,\n"
                     "  customer_email TEXT NOT NULL,\n"
                     "  plan TEXT NOT NULL,\n"
                     "  price_cents INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO subscriptions VALUES\n"
                     " (1,'ana@x.io','pro',15000),(2,'beto@x.io','basic',2900),\n"
                     " (3,'carla@x.io','pro',9900),(4,'dario@x.io','team',18000);\n"
                     "```\n"
                     "Entrega el script completo de ambas fases con verificación (PRAGMA table_info) y el resumen final por ciclo."),
            ("assistant", "Por qué dos fases: ALTER TABLE ADD COLUMN con DEFAULT es O(1) en SQLite (no toca filas existentes; el default se resuelve al leer), así que despliega en segundos aunque la tabla tenga millones de filas — fase 1 compatible con código viejo. El backfill por política es reversible y auditable. La fase 2 es la cara cara: SQLite no permite ALTERar restricciones, así que la vía canónica es reconstruir (tabla nueva con el DDL objetivo, INSERT ... SELECT, DROP, RENAME) dentro de la misma sesión transaccional. El CHECK lo declaro CON NOMBRE (chk_billing_cycle) para que los errores futuros digan qué regla falló. Transcript de control de la fase 1 y del rechazo post-migración:"),
            ("tool", "sqlite> ALTER TABLE subscriptions ADD COLUMN billing_cycle TEXT NOT NULL DEFAULT 'monthly';\n"
                     "sqlite> SELECT subscription_id, price_cents, billing_cycle FROM subscriptions ORDER BY subscription_id;\n"
                     "1|15000|monthly\n"
                     "2|2900|monthly\n"
                     "3|9900|monthly\n"
                     "4|18000|monthly\n"
                     "sqlite> INSERT INTO subscriptions (subscription_id, customer_email, plan, price_cents, billing_cycle) VALUES (5,'eve@x.io','basic',1900,'weekly');\n"
                     "Runtime error: CHECK constraint failed: chk_billing_cycle (19)\n"
                     "sqlite> -- tras la fase 2 el CHECK rechaza ciclos invalidos; en fase 1 el valor entraria sin control"),
            ("assistant", "Script completo:\n"
                     "```sql\n"
                     "ALTER TABLE subscriptions ADD COLUMN billing_cycle TEXT NOT NULL DEFAULT 'monthly';\n"
                     "SELECT billing_cycle, COUNT(*) AS n FROM subscriptions GROUP BY billing_cycle;\n"
                     "UPDATE subscriptions SET billing_cycle = 'annual' WHERE price_cents >= 12000;\n"
                     "CREATE TABLE subscriptions_new (\n"
                     "  subscription_id INTEGER PRIMARY KEY,\n"
                     "  customer_email TEXT NOT NULL,\n"
                     "  plan TEXT NOT NULL,\n"
                     "  price_cents INTEGER NOT NULL CHECK (price_cents >= 0),\n"
                     "  billing_cycle TEXT NOT NULL\n"
                     "    CONSTRAINT chk_billing_cycle CHECK (billing_cycle IN ('monthly','annual'))\n"
                     ");\n"
                     "INSERT INTO subscriptions_new\n"
                     "SELECT subscription_id, customer_email, plan, price_cents, billing_cycle FROM subscriptions;\n"
                     "DROP TABLE subscriptions;\n"
                     "ALTER TABLE subscriptions_new RENAME TO subscriptions;\n"
                     "PRAGMA table_info(subscriptions);\n"
                     "SELECT billing_cycle, COUNT(*) AS n, MIN(price_cents) AS min_price, MAX(price_cents) AS max_price\n"
                     "FROM subscriptions GROUP BY billing_cycle ORDER BY billing_cycle;\n"
                     "```\n"
                     "Lectura: la primera agregación muestra monthly|4 (el default cubre la fase 1 sin romper lectores); el UPDATE rellena 2 filas por política; la tabla final reporta billing_cycle con notnull=1 y sin default (celda dflt_value vacía: NOT NULL SIN red de seguridad, como pide el contrato). Resumen final: annual|2 (15000–18000) y monthly|2 (2900–9900). Checklist de la fase 2 que NO hay que saltarse: recrear índices y vistas que apuntaban a la tabla vieja (aquí no había, pero anótalo), ejecutar PRAGMA foreign_key_check si la tabla es padre/hija, y desplegar el cambio de esquema ANTES de que el código nuevo exija la columna — si el despliegue va al revés, la fase 1 te salva pero la fase 2 rompe lectores viejos que hagan SELECT * y esperen orden de columnas."),
        ],
        verify=[
            {"name": "migracion_dos_fases", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["monthly|4", "annual|2|15000|18000",
                                        "monthly|2|2900|9900",
                                        "4|billing_cycle|TEXT|1||0"]},
        ],
        tags=["sql", "migration", "alter-table", "not-null", "backfill", "table-rebuild", "saas"],
    ),
    # ---------------------------------------------------------------- M2 (extreme)
    E(
        language="sql", domain="databases", subdomain="schema_rebuild_legacy",
        difficulty="extreme", task_type="migration",
        messages=[
            ("user", "La farmacia hereda una tabla de stock creada \"a pelo\" hace años: sin clave foránea al catálogo (relación solo por nombre), sin UNIQUE por lote y con basura acumulada. Necesito la migración completa a un esquema saneado: (1) auditar duplicados de (drug_name, batch_no) y filas huérfanas respecto al catálogo; (2) deduplicar conservando el stock_id MENOR; (3) las huérfanas NO se borran: van a una tabla de cuarentena; (4) reconstruir pharmacy_stock con FK a drug_catalog, CHECK qty > 0 y UNIQUE (drug_id, batch_no), mapeando nombre→drug_id; (5) verificar con PRAGMA foreign_key_check + integrity_check y listar el estado final. Datos de partida:\n"
                     "```sql\n"
                     "CREATE TABLE drug_catalog (\n"
                     "  drug_id INTEGER PRIMARY KEY,\n"
                     "  drug_name TEXT NOT NULL UNIQUE\n"
                     ");\n"
                     "CREATE TABLE pharmacy_stock (\n"
                     "  stock_id INTEGER PRIMARY KEY,\n"
                     "  drug_name TEXT NOT NULL,\n"
                     "  batch_no TEXT NOT NULL,\n"
                     "  qty INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO drug_catalog VALUES (1,'Ibuprofeno'),(2,'Amoxicilina'),(3,'Metformina');\n"
                     "INSERT INTO pharmacy_stock VALUES (1,'Ibuprofeno','L-2024-01',120),(2,'Amoxicilina','A-2024-07',40),(3,'Ibuprofeno','L-2024-01',60),(4,'Metformina','M-2024-03',90),(5,'Amoxicilina','A-2024-07',25),(6,'Omeprazol','O-2024-02',30);\n"
                     "```\n"
                     "Espera 3 filas finales en stock y 1 en cuarentena."),
            ("assistant", "Orden de operaciones deliberado: auditar ANTES de tocar (los informes de auditoría deben emitirse sobre el estado original), deduplicar ANTES de reconstruir (si no, la UNIQUE del DDL nuevo revienta el INSERT ... SELECT), y separar el residuo en cuarentena en lugar de borrarlo (en farmacia ningún dato desaparece sin traza). La reconstrucción usa el patrón canónico de SQLite: tabla nueva con el DDL objetivo, INSERT ... SELECT con el mapeo por JOIN, DROP de la vieja y RENAME. Los PRAGMA finales cierran la migración con evidencia. Sonda previa:"),
            ("tool", "sqlite> SELECT drug_name, batch_no, COUNT(*) AS copias, GROUP_CONCAT(stock_id) AS ids FROM pharmacy_stock GROUP BY drug_name, batch_no HAVING COUNT(*) > 1 ORDER BY drug_name;\n"
                     "Amoxicilina|A-2024-07|2|2,5\n"
                     "Ibuprofeno|L-2024-01|2|1,3\n"
                     "sqlite> SELECT COUNT(*) AS huerfanas FROM pharmacy_stock s LEFT JOIN drug_catalog d ON d.drug_name = s.drug_name WHERE d.drug_id IS NULL;\n"
                     "1\n"
                     "sqlite> -- 2 pares duplicados y 1 huerfano (Omeprazol no esta en el catalogo): la migracion\n"
                     "sqlite> -- debe tratar los tres problemas ANTES de imponer UNIQUE y FK"),
            ("assistant", "Script completo de migración:\n"
                     "```sql\n"
                     "SELECT drug_name, batch_no, COUNT(*) AS copias\n"
                     "FROM pharmacy_stock\n"
                     "GROUP BY drug_name, batch_no\n"
                     "HAVING COUNT(*) > 1\n"
                     "ORDER BY drug_name;\n"
                     "SELECT s.stock_id, s.drug_name, s.batch_no, s.qty\n"
                     "FROM pharmacy_stock s\n"
                     "LEFT JOIN drug_catalog d ON d.drug_name = s.drug_name\n"
                     "WHERE d.drug_id IS NULL\n"
                     "ORDER BY s.stock_id;\n"
                     "DELETE FROM pharmacy_stock\n"
                     "WHERE stock_id NOT IN (SELECT MIN(stock_id) FROM pharmacy_stock GROUP BY drug_name, batch_no);\n"
                     "CREATE TABLE stock_quarantine (\n"
                     "  stock_id INTEGER PRIMARY KEY,\n"
                     "  drug_name TEXT NOT NULL,\n"
                     "  batch_no TEXT NOT NULL,\n"
                     "  qty INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO stock_quarantine\n"
                     "SELECT s.stock_id, s.drug_name, s.batch_no, s.qty\n"
                     "FROM pharmacy_stock s\n"
                     "LEFT JOIN drug_catalog d ON d.drug_name = s.drug_name\n"
                     "WHERE d.drug_id IS NULL;\n"
                     "CREATE TABLE pharmacy_stock_new (\n"
                     "  stock_id INTEGER PRIMARY KEY,\n"
                     "  drug_id INTEGER NOT NULL REFERENCES drug_catalog(drug_id),\n"
                     "  batch_no TEXT NOT NULL,\n"
                     "  qty INTEGER NOT NULL CHECK (qty > 0),\n"
                     "  UNIQUE (drug_id, batch_no)\n"
                     ");\n"
                     "INSERT INTO pharmacy_stock_new\n"
                     "SELECT s.stock_id, d.drug_id, s.batch_no, s.qty\n"
                     "FROM pharmacy_stock s\n"
                     "JOIN drug_catalog d ON d.drug_name = s.drug_name;\n"
                     "DROP TABLE pharmacy_stock;\n"
                     "ALTER TABLE pharmacy_stock_new RENAME TO pharmacy_stock;\n"
                     "PRAGMA foreign_key_check;\n"
                     "PRAGMA integrity_check;\n"
                     "SELECT s.stock_id, s.drug_id, s.batch_no, s.qty\n"
                     "FROM pharmacy_stock s\n"
                     "ORDER BY s.stock_id;\n"
                     "SELECT stock_id, drug_name FROM stock_quarantine ORDER BY stock_id;\n"
                     "```\n"
                     "Lectura: los duplicados eran (1,3) y (2,5) — el DELETE conservó 1 y 2 (MIN de cada grupo); Omeprazol (id 6) quedó en cuarentena, no en el limbo; la tabla nueva solo acepta lo que mapea al catálogo, por eso el INNER JOIN del INSERT actúa de filtro y la FK declara el contrato que antes era un acuerdo implícito por nombre. Los PRAGMA devuelven cero filas y «ok»: sin violaciones y con integridad estructural. Advertencias de operación: (1) el NOT IN del DELETE es seguro SOLO porque stock_id es PK y nunca NULL — con una columna anulable sería la trampa del NOT IN con NULL; (2) el cambio de clave natural (drug_name → drug_id) es un cambio de CONTRATO: cualquier consulta vieja que filtrara por drug_name ahora debe cruzar con el catálogo, y eso se versiona en el código, no en la BD."),
        ],
        verify=[
            {"name": "migracion_legado_saneada", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["Ibuprofeno|L-2024-01|2", "Amoxicilina|A-2024-07|2",
                                        "6|Omeprazol|O-2024-02|30", "1|1|L-2024-01|120",
                                        "2|2|A-2024-07|40", "4|3|M-2024-03|90",
                                        "(0 filas)", "ok"]},
        ],
        tags=["sql", "migration", "table-rebuild", "foreign-keys", "data-quality", "pharmacy"],
    ),
    # ---------------------------------------------------------------- D6 (hard)
    E(
        language="sql", domain="databases", subdomain="left_join_status_filter",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "El informe mensual del gimnasio «socios con clases asistidas» debe incluir a TODOS los socios (0 clases si no asistieron), pero desde que se añadió el filtro de asistencia desaparecen dos socios. Esquema, datos y consulta problemática:\n"
                     "```sql\n"
                     "CREATE TABLE members (\n"
                     "  member_id INTEGER PRIMARY KEY,\n"
                     "  name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE class_bookings (\n"
                     "  booking_id INTEGER PRIMARY KEY,\n"
                     "  member_id INTEGER NOT NULL REFERENCES members(member_id),\n"
                     "  class_name TEXT NOT NULL,\n"
                     "  duration_min INTEGER NOT NULL,\n"
                     "  status TEXT NOT NULL CHECK (status IN ('attended','no_show','cancelled'))\n"
                     ");\n"
                     "INSERT INTO members VALUES (1,'Ana Torres'),(2,'Bruno Diaz'),(3,'Carla Nunez'),(4,'Diana Soto');\n"
                     "INSERT INTO class_bookings VALUES (101,1,'yoga',60,'attended'),(102,2,'yoga',60,'no_show'),(103,3,'pilates',45,'attended');\n"
                     "```\n"
                     "```sql\n"
                     "SELECT m.name, COUNT(b.booking_id) AS clases, COALESCE(SUM(b.duration_min), 0) AS minutos\n"
                     "FROM members m\n"
                     "LEFT JOIN class_bookings b ON b.member_id = m.member_id\n"
                     "WHERE b.status = 'attended'\n"
                     "GROUP BY m.member_id, m.name\n"
                     "ORDER BY m.name;\n"
                     "```\n"
                     "Esperado: Ana 1|60, Bruno 0|0, Carla 1|45 y Diana 0|0. Obtenido: solo Ana y Carla."),
            ("assistant", "Síntoma: Bruno (solo no_show) y Diana (sin reservas) desaparecen. Hipótesis 1: el GROUP BY pierde grupos cuyos agregados son nulos. Hipótesis 2: el LEFT JOIN está bien escrito pero el WHERE sobre la columna DERECHA convierte el outer join en inner — la fila extendida de Diana lleva b.status NULL, NULL = 'attended' es UNKNOWN y el WHERE la descarta; Bruno tiene filas pero ninguna attended, así que también cae. Experimento discriminante: ejecutar el LEFT JOIN en crudo, sin WHERE ni agregación, y mirar qué filas llegan al filtro."),
            ("tool", "sqlite> SELECT m.name, b.booking_id, b.status, b.duration_min FROM members m LEFT JOIN class_bookings b ON b.member_id = m.member_id ORDER BY m.name, b.booking_id;\n"
                     "Ana Torres|101|attended|60\n"
                     "Bruno Diaz|102|no_show|60\n"
                     "Carla Nunez|103|attended|45\n"
                     "Diana Soto|||\n"
                     "sqlite> -- la fila de Diana SI existe tras el JOIN (b.status NULL): el WHERE la esta matando"),
            ("assistant", "El experimento refuta la hipótesis 1 (Diana tiene fila tras el JOIN; un GROUP BY no descarta grupos, el WHERE actúa ANTES del GROUP BY) y confirma la 2: el predicado sobre la tabla derecha pertenece a la lógica del JOIN y debe vivir en el ON. Corrección:\n"
                     "```sql\n"
                     "SELECT m.name, COUNT(b.booking_id) AS clases, COALESCE(SUM(b.duration_min), 0) AS minutos\n"
                     "FROM members m\n"
                     "LEFT JOIN class_bookings b\n"
                     "       ON b.member_id = m.member_id AND b.status = 'attended'\n"
                     "GROUP BY m.member_id, m.name\n"
                     "ORDER BY m.name;\n"
                     "```\n"
                     "Nueva ejecución: Ana Torres|1|60, Bruno Diaz|0|0, Carla Nunez|1|45, Diana Soto|0|0. Nota: COUNT(b.booking_id) cuenta no nulos (para Diana 0, no 1) y el COALESCE cubre la suma. Regla mnemotécnica: filtro de la izquierda → WHERE; filtro de la derecha → ON. La variante WHERE (b.status = 'attended' OR b.booking_id IS NULL) también produce lo correcto, pero reparte la misma condición en dos sitios y se rompe en silencio con el próximo refactor; y ojo con «arreglarlo» cambiando el LEFT JOIN por JOIN: entonces Diana desaparecería «correctamente» y el informe seguiría mal según el requisito de negocio."),
        ],
        verify=[
            {"name": "bug_socios_perdidos", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["Ana Torres|1|60", "Carla Nunez|1|45"],
             "expect_stdout_not_contains": ["Bruno Diaz|0|0", "Diana Soto|0|0"]},
            {"name": "fix_predicado_en_on", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["Ana Torres|1|60", "Bruno Diaz|0|0",
                                        "Carla Nunez|1|45", "Diana Soto|0|0"]},
        ],
        tags=["sql", "left-join", "where-predicate", "debugging", "gym"],
    ),
    # ---------------------------------------------------------------- D7 (hard)
    E(
        language="sql", domain="databases", subdomain="not_in_null_trap",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "La pantalla de seguridad de la farmacia lista los pacientes SIN alergia registrada a penicilina (candidatos a prescripción estándar). Desde que urgencias empezó a registrar alergias de pacientes anónimos, la pantalla devuelve CERO pacientes, lo cual es claramente falso. Esquema, datos y consulta rota:\n"
                     "```sql\n"
                     "CREATE TABLE patients (\n"
                     "  patient_id INTEGER PRIMARY KEY,\n"
                     "  full_name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE patient_allergies (\n"
                     "  allergy_id INTEGER PRIMARY KEY,\n"
                     "  patient_id INTEGER,\n"
                     "  allergen TEXT NOT NULL\n"
                     ");\n"
                     "INSERT INTO patients VALUES (1,'Lucia Ortega'),(2,'Pablo Reyes'),(3,'Nerea Campos'),(4,'Iker Blanco');\n"
                     "INSERT INTO patient_allergies VALUES (1,1,'penicilina'),(2,3,'penicilina'),(3,NULL,'penicilina');\n"
                     "```\n"
                     "```sql\n"
                     "SELECT COUNT(*) AS pacientes FROM patients;\n"
                     "SELECT patient_id, full_name\n"
                     "FROM patients\n"
                     "WHERE patient_id NOT IN (\n"
                     "  SELECT patient_id FROM patient_allergies WHERE allergen = 'penicilina'\n"
                     ")\n"
                     "ORDER BY patient_id;\n"
                     "```\n"
                     "La fila (3, NULL, 'penicilina') es una alergia de paciente anónimo (walk-in sin ficha aún). Esperado: los pacientes 2 y 4."),
            ("assistant", "Síntoma: el NOT IN devuelve cero filas desde que existe un registro con patient_id NULL. Hipótesis 1: los datos están bien y en realidad todos los pacientes son alérgicos. Hipótesis 2: semántica trivalente — x NOT IN (lista) se despliega como x <> v1 AND x <> v2 AND ...; con un NULL en la lista, cada comparación x <> NULL es UNKNOWN, el AND nunca llega a TRUE y el predicado filtra TODAS las filas. Experimento: ver la tabla de alergias y evaluar NOT IN con y sin NULL a mano."),
            ("tool", "sqlite> SELECT allergy_id, patient_id, allergen FROM patient_allergies ORDER BY allergy_id;\n"
                     "1|1|penicilina\n"
                     "2|3|penicilina\n"
                     "3||penicilina\n"
                     "sqlite> SELECT 2 NOT IN (1, 3) AS sin_null, 2 NOT IN (1, NULL) AS con_null;\n"
                     "1|\n"
                     "sqlite> -- sin_null=1 y con_null sale VACIO (UNKNOWN): basta un NULL en la lista para\n"
                     "sqlite> -- que NINGUN valor sea «NOT IN»: el informe se vacia en silencio"),
            ("assistant", "Refutada la hipótesis 1 (Pablo e Iker no tienen alergia registrada) y confirmada la 2: la lista del NOT IN contiene {1, 3, NULL} y por lógica trivalente el predicado es UNKNOWN para todo el mundo. Causa raíz: NOT IN sobre una subconsulta de columna ANULABLE. Corrección canónica: NOT EXISTS, que no despliega la lista — comprueba existencia por fila correlacionada y es inmune a NULL por construcción:\n"
                     "```sql\n"
                     "SELECT p.patient_id, p.full_name\n"
                     "FROM patients p\n"
                     "WHERE NOT EXISTS (\n"
                     "  SELECT 1 FROM patient_allergies a\n"
                     "  WHERE a.patient_id = p.patient_id\n"
                     "    AND a.allergen = 'penicilina'\n"
                     ")\n"
                     "ORDER BY p.patient_id;\n"
                     "```\n"
                     "Alternativa mínima (si el ORM te obliga a NOT IN): excluir los nulos en la subconsulta — funciona aquí, pero el día que alguien añada una columna anulable nueva o cambie el filtro, la trampa vuelve; el anti-join con NOT EXISTS no depende de la calidad de los datos:\n"
                     "```sql\n"
                     "SELECT patient_id, full_name\n"
                     "FROM patients\n"
                     "WHERE patient_id NOT IN (\n"
                     "  SELECT patient_id FROM patient_allergies\n"
                     "  WHERE patient_id IS NOT NULL AND allergen = 'penicilina'\n"
                     ")\n"
                     "ORDER BY patient_id;\n"
                     "```\n"
                     "Ambas devuelven 2|Pablo Reyes y 4|Iker Blanco. Nota de rendimiento: NOT EXISTS y NOT IN sin nulos suelen compilar a planes equivalentes en SQLite (anti-join); la diferencia aquí es de CORRECTNESS, no de velocidad. Y el arreglo estructural de fondo es de esquema: patient_id debería ser NOT NULL REFERENCES patients — la columna anulable fue la decisión que armó la trampa."),
        ],
        verify=[
            {"name": "bug_not_in_vacia", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["4", "(0 filas)"],
             "expect_stdout_not_contains": ["2|Pablo Reyes", "4|Iker Blanco"]},
            {"name": "fix_not_exists", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2|Pablo Reyes", "4|Iker Blanco"],
             "expect_stdout_not_contains": ["1|Lucia Ortega", "3|Nerea Campos"]},
            {"name": "fix_alternativa_not_in", "action": "sql", "lang": "sql", "msg": -1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2|Pablo Reyes", "4|Iker Blanco"],
             "expect_stdout_not_contains": ["1|Lucia Ortega", "3|Nerea Campos"]},
        ],
        tags=["sql", "not-in", "null-semantics", "not-exists", "debugging", "pharmacy"],
    ),
    # ---------------------------------------------------------------- D8 (hard)
    E(
        language="sql", domain="databases", subdomain="team_alloc_fanout",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "Facturación de una plataforma SaaS: el informe cobra a cada equipo las llamadas API de los proyectos en que participa, y el contrato dice que un proyecto COMPARTIDO se PRORRATEA a partes iguales entre sus equipos. La consulta actual factura de más: la suma del informe (2800) no cuadra con lo medido (1800). Esquema y consulta rota:\n"
                     "```sql\n"
                     "CREATE TABLE teams (\n"
                     "  team_id INTEGER PRIMARY KEY,\n"
                     "  team_name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE projects (\n"
                     "  project_id INTEGER PRIMARY KEY,\n"
                     "  name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE team_projects (\n"
                     "  project_id INTEGER NOT NULL REFERENCES projects(project_id),\n"
                     "  team_id INTEGER NOT NULL REFERENCES teams(team_id),\n"
                     "  PRIMARY KEY (project_id, team_id)\n"
                     ");\n"
                     "CREATE TABLE usage_records (\n"
                     "  usage_id INTEGER PRIMARY KEY,\n"
                     "  project_id INTEGER NOT NULL REFERENCES projects(project_id),\n"
                     "  api_calls INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO teams VALUES (1,'alpha'),(2,'beta'),(3,'gamma');\n"
                     "INSERT INTO projects VALUES (10,'atlas'),(20,'bolt'),(30,'comet');\n"
                     "INSERT INTO team_projects VALUES (10,1),(10,2),(20,1),(30,2);\n"
                     "INSERT INTO usage_records VALUES (1,10,1000),(2,20,300),(3,30,500);\n"
                     "```\n"
                     "```sql\n"
                     "SELECT t.team_name, SUM(u.api_calls) AS llamadas\n"
                     "FROM usage_records u\n"
                     "JOIN team_projects tp ON tp.project_id = u.project_id\n"
                     "JOIN teams t ON t.team_id = tp.team_id\n"
                     "GROUP BY t.team_id, t.team_name\n"
                     "ORDER BY t.team_name;\n"
                     "SELECT SUM(api_calls) AS medido FROM usage_records;\n"
                     "```\n"
                     "Salida: alpha|1300, beta|1500 y medido 1800. Esperado con prorrateo: alpha|800, beta|1000, gamma|0 y total 1800."),
            ("assistant", "Síntoma: 2800 facturado vs 1800 medido — sobran exactamente 1000, las llamadas de atlas, el proyecto con DOS equipos. Hipótesis 1: filas duplicadas en usage_records. Hipótesis 2: fan-out del m:n — el JOIN atraviesa team_projects y multiplica cada línea de consumo por el nº de equipos del proyecto; SUM agrega filas, no proyectos, así que atlas cobra 1000 a alpha Y 1000 a beta. Sondas:"),
            ("tool", "sqlite> SELECT usage_id, COUNT(*) AS n FROM usage_records GROUP BY usage_id;\n"
                     "1|1\n"
                     "2|1\n"
                     "3|1\n"
                     "sqlite> -- hipotesis 1 refutada: sin duplicados en usage_records\n"
                     "sqlite> SELECT u.usage_id, u.project_id, u.api_calls, COUNT(tp.team_id) AS equipos FROM usage_records u LEFT JOIN team_projects tp ON tp.project_id = u.project_id GROUP BY u.usage_id ORDER BY u.usage_id;\n"
                     "1|10|1000|2\n"
                     "2|20|300|1\n"
                     "3|30|500|1\n"
                     "sqlite> -- atlas lo comparten alpha y beta: en el JOIN su consumo sale DOS veces"),
            ("assistant", "Confirmado el fan-out m:n. Causa raíz: agregar sobre el producto cartesiano consumo×equipos en lugar de asignar el consumo. Corrección: el prorrateo se calcula DIVIDIENDO cada línea por el nº de equipos del proyecto (subconsulta correlacionada sobre team_projects), y el informe se construye desde teams con LEFT JOIN para que gamma salga con 0 — un equipo sin consumo también se factura (cuota cero, fila presente):\n"
                     "```sql\n"
                     "WITH alloc AS (\n"
                     "  SELECT tp.team_id,\n"
                     "         u.api_calls / (SELECT COUNT(*) FROM team_projects tp2\n"
                     "                        WHERE tp2.project_id = u.project_id) AS llamadas_asignadas\n"
                     "  FROM usage_records u\n"
                     "  JOIN team_projects tp ON tp.project_id = u.project_id\n"
                     ")\n"
                     "SELECT t.team_name, COALESCE(SUM(a.llamadas_asignadas), 0) AS llamadas\n"
                     "FROM teams t\n"
                     "LEFT JOIN alloc a ON a.team_id = t.team_id\n"
                     "GROUP BY t.team_id, t.team_name\n"
                     "ORDER BY t.team_name;\n"
                     "SELECT SUM(api_calls) AS medido FROM usage_records;\n"
                     "```\n"
                     "alpha: 1000/2 + 300/1 = 800; beta: 1000/2 + 500/1 = 1000; gamma: 0. La suma del informe (1800) ya cuadra con lo medido: el prorrateo conserva el total, el fan-out lo inflaba. Dos avisos de frontera: (1) la división ENTRE ENTEROS de SQLite trunca (1000/2 = 500 aquí es exacto por diseño de los datos; con importes no divisibles decide y documenta la política: CAST a REAL y redondeo, o ajuste de céntimos residuales al primer equipo); (2) si el negocio un día pide «coste por proyecto» EN LUGAR de por equipo, no reutilices esta consulta: el prorrateo es una DECISIÓN de negocio con su propio informe, no un accidente del JOIN."),
        ],
        verify=[
            {"name": "bug_fanout_factura", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["alpha|1300", "beta|1500", "1800"],
             "expect_stdout_not_contains": ["alpha|800"]},
            {"name": "fix_prorrateo", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["alpha|800", "beta|1000", "gamma|0", "1800"],
             "expect_stdout_not_contains": ["alpha|1300", "beta|1500"]},
        ],
        tags=["sql", "many-to-many", "fan-out", "proration", "debugging", "saas"],
    ),
    # ---------------------------------------------------------------- D9 (hard)
    E(
        language="sql", domain="databases", subdomain="duplicate_registration_purge",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "Eventos: el doble submit del formulario ha creado registros duplicados de inscripción y el sistema de check-in da prioridad por ORDEN DE REGISTRO (el más temprano gana). El becario aplicó un borrado con ROW_NUMBER y ahora el check-in de Ana sale mal. Esquema, datos y el borrado que se aplicó:\n"
                     "```sql\n"
                     "CREATE TABLE registrations (\n"
                     "  registration_id INTEGER PRIMARY KEY,\n"
                     "  event_id INTEGER NOT NULL,\n"
                     "  attendee_email TEXT NOT NULL,\n"
                     "  registered_at TEXT NOT NULL\n"
                     ");\n"
                     "INSERT INTO registrations VALUES\n"
                     " (1,1,'ana@x.io','2024-05-01 10:00'),(2,1,'bruno@x.io','2024-05-01 11:00'),\n"
                     " (3,1,'ana@x.io','2024-05-02 09:00'),(4,1,'ana@x.io','2024-05-01 10:00'),\n"
                     " (5,2,'clara@x.io','2024-05-03 12:00'),(6,2,'clara@x.io','2024-05-04 08:00');\n"
                     "```\n"
                     "```sql\n"
                     "WITH d AS (\n"
                     "  SELECT registration_id,\n"
                     "         ROW_NUMBER() OVER (\n"
                     "           PARTITION BY event_id, attendee_email\n"
                     "           ORDER BY registered_at DESC, registration_id DESC) AS rn\n"
                     "  FROM registrations\n"
                     ")\n"
                     "DELETE FROM registrations WHERE registration_id IN (SELECT registration_id FROM d WHERE rn > 1);\n"
                     "SELECT registration_id, attendee_email, registered_at FROM registrations ORDER BY registration_id;\n"
                     "```\n"
                     "Regla de negocio: por cada (event_id, attendee_email) debe quedar SOLO la inscripción MÁS ANTIGUA; a igualdad de instante, el registration_id MENOR. El borrado del becario conserva lo contrario."),
            ("assistant", "Análisis del borrado aplicado: ROW_NUMBER con ORDER BY registered_at DESC, registration_id DESC numera de MÁS RECIENTE a más antiguo, y el DELETE conserva rn = 1... que es la más RECIENTE de cada grupo. Además del error de dirección, en el grupo de Ana hay un empate exacto (ids 1 y 4 con el mismo instante) que sin desempate explícito sería arbitrario — aquí el DESC de registration_id lo resuelve, pero hacia el lado contrario del negocio. Sonda: qué grupos hay y quién debería sobrevivir."),
            ("tool", "sqlite> SELECT event_id, attendee_email, COUNT(*) AS copias FROM registrations GROUP BY event_id, attendee_email HAVING COUNT(*) > 1 ORDER BY event_id, attendee_email;\n"
                     "1|ana@x.io|3\n"
                     "2|clara@x.io|2\n"
                     "sqlite> SELECT registration_id, attendee_email, registered_at FROM registrations WHERE event_id = 1 ORDER BY registered_at, registration_id;\n"
                     "1|ana@x.io|2024-05-01 10:00\n"
                     "4|ana@x.io|2024-05-01 10:00\n"
                     "3|ana@x.io|2024-05-02 09:00\n"
                     "2|bruno@x.io|2024-05-01 11:00\n"
                     "sqlite> -- para ana la superviviente correcta es la id 1 (la mas antigua; 1 y 4 empatan y gana el id menor)"),
            ("assistant", "El borrado aplicado conserva las supervivientes equivocadas: para ana deja la id 3 (2024-05-02, la más reciente) y elimina la id 1, que es la que el check-in debe honrar. Causa raíz: dirección del ORDER BY invertida respecto a la regla de negocio. Corrección (sobre el estado ORIGINAL de la tabla — cada verificación reconstruye el escenario desde el DDL): ASC en ambas claves y desempate explícito; después, índice UNIQUE preventivo para que el doble submit no vuelva a ocurrir:\n"
                     "```sql\n"
                     "WITH d AS (\n"
                     "  SELECT registration_id,\n"
                     "         ROW_NUMBER() OVER (\n"
                     "           PARTITION BY event_id, attendee_email\n"
                     "           ORDER BY registered_at, registration_id) AS rn\n"
                     "  FROM registrations\n"
                     ")\n"
                     "DELETE FROM registrations WHERE registration_id IN (SELECT registration_id FROM d WHERE rn > 1);\n"
                     "CREATE UNIQUE INDEX uq_registration ON registrations(event_id, attendee_email);\n"
                     "SELECT registration_id, attendee_email, registered_at FROM registrations ORDER BY registration_id;\n"
                     "SELECT event_id, COUNT(*) AS inscritos_unicos FROM registrations GROUP BY event_id ORDER BY event_id;\n"
                     "```\n"
                     "Resultado: sobreviven 1, 2 y 5 (para ana la 1; para clara la 5) y el índice UNIQUE convierte el próximo intento de doble inscripción en un error de restricción, no en datos corruptos. Lecciones: (1) en un DELETE con ventana, el sentido del ORDER BY ES la semántica — revísalo contra la regla de negocio escrita, no contra «parece razonable»; (2) el empate nunca lo dejes al plan de ejecución: fija el desempate en la propia ventana; (3) patrón idempotente para cargas futuras: INSERT ... ON CONFLICT (event_id, attendee_email) DO NOTHING con el índice ya desplegado, así la dedupe deja de ser una tarea nocturna."),
        ],
        verify=[
            {"name": "bug_superviviente_reciente", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["3|ana@x.io|2024-05-02 09:00", "6|clara@x.io|2024-05-04 08:00"],
             "expect_stdout_not_contains": ["1|ana@x.io|2024-05-01 10:00"]},
            {"name": "fix_superviviente_antigua", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["1|ana@x.io|2024-05-01 10:00", "2|bruno@x.io|2024-05-01 11:00",
                                        "5|clara@x.io|2024-05-03 12:00"],
             "expect_stdout_not_contains": ["2024-05-02 09:00", "2024-05-04 08:00"]},
        ],
        tags=["sql", "row-number", "dedupe", "delete", "unique-index", "events"],
    ),
    # ---------------------------------------------------------------- D10 (hard)
    E(
        language="sql", domain="databases", subdomain="orphan_fk_audit",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "Contabilidad del gimnasio detecta descuadre: la suma de TODAS las facturas (49500 céntimos) no coincide con lo que suma el informe de facturación por socio. Sospechan de facturas «fantasma» tras una purga RGPD de socios. Esquema legacy (sin FK declaradas — así se creó), datos y el informe conflictivo:\n"
                     "```sql\n"
                     "CREATE TABLE members (\n"
                     "  member_id INTEGER PRIMARY KEY,\n"
                     "  full_name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE invoices (\n"
                     "  invoice_id INTEGER PRIMARY KEY,\n"
                     "  member_id INTEGER NOT NULL,\n"
                     "  amount_cents INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO members VALUES (1,'Roser Vila'),(2,'Toni Abril'),(4,'Sara Llop');\n"
                     "INSERT INTO invoices VALUES (1,1,9000),(2,1,9000),(3,3,7000),(4,2,12000),(5,4,6000),(6,5,5000),(7,3,1500);\n"
                     "```\n"
                     "```sql\n"
                     "SELECT i.member_id, COUNT(*) AS facturas, SUM(i.amount_cents) AS total_cents\n"
                     "FROM invoices i\n"
                     "JOIN members m ON m.member_id = i.member_id\n"
                     "GROUP BY i.member_id\n"
                     "ORDER BY i.member_id;\n"
                     "SELECT COUNT(*) AS facturas, SUM(amount_cents) AS total_cents FROM invoices;\n"
                     "```\n"
                     "El informe suma 36000 pero facturado hay 49500: la diferencia debe estar en facturas de socios inexistentes."),
            ("assistant", "Síntoma: el informe (por socio) deja fuera 13500 céntimos. Hipótesis 1: facturas duplicadas que el GROUP BY colapsa. Hipótesis 2: facturas que apuntan a member_id inexistentes — el INNER JOIN las descarta en silencio. Sonda barata primero: recuento de duplicados por factura; después, el LEFT JOIN invertido que EXHIBE las huérfanas en vez de esconderlas. Y una comprobación que suele engañar: PRAGMA foreign_key_check — porque SOLO examina claves ajenas DECLARADAS, y esta tabla legacy no declara ninguna: el pragma devolverá vacío aunque los datos estén rotos."),
            ("tool", "sqlite> SELECT invoice_id, COUNT(*) AS n FROM invoices GROUP BY invoice_id HAVING COUNT(*) > 1;\n"
                     "sqlite> -- hipotesis 1 refutada: ninguna factura duplicada\n"
                     "sqlite> SELECT COUNT(*) AS huerfanas FROM invoices i LEFT JOIN members m ON m.member_id = i.member_id WHERE m.member_id IS NULL;\n"
                     "3\n"
                     "sqlite> PRAGMA foreign_key_check;\n"
                     "sqlite> -- cero filas: los ids 3 y 5 fueron purgados y la tabla NO declara FK, asi que\n"
                     "sqlite> -- foreign_key_check no tiene nada que mirar: el pragma NO es auditoria de datos"),
            ("assistant", "Confirmadas 3 facturas huérfanas (member_id 3 y 5, socios purgados). El INNER JOIN del informe no «falla»: hace exactamente lo que dice — y eso lo hace peligroso para conciliar. Suite de auditoría + remediación: cuantificar el descuadre, listar huérfanas, criarlas a una tabla de cuarentena (en contabilidad no se borra sin traza), retirarlas del activo y re-cuadrar:\n"
                     "```sql\n"
                     "SELECT (SELECT SUM(amount_cents) FROM invoices) AS facturado,\n"
                     "       (SELECT SUM(i.amount_cents) FROM invoices i JOIN members m ON m.member_id = i.member_id) AS conciliado;\n"
                     "SELECT i.invoice_id, i.member_id, i.amount_cents\n"
                     "FROM invoices i\n"
                     "LEFT JOIN members m ON m.member_id = i.member_id\n"
                     "WHERE m.member_id IS NULL\n"
                     "ORDER BY i.invoice_id;\n"
                     "PRAGMA foreign_key_check;\n"
                     "CREATE TABLE orphan_invoices AS\n"
                     "SELECT invoice_id, member_id, amount_cents\n"
                     "FROM invoices\n"
                     "WHERE member_id NOT IN (SELECT member_id FROM members);\n"
                     "DELETE FROM invoices\n"
                     "WHERE member_id NOT IN (SELECT member_id FROM members);\n"
                     "SELECT (SELECT SUM(amount_cents) FROM invoices) AS facturado,\n"
                     "       (SELECT SUM(i.amount_cents) FROM invoices i JOIN members m ON m.member_id = i.member_id) AS conciliado;\n"
                     "SELECT COUNT(*) AS en_cuarentena FROM orphan_invoices;\n"
                     "```\n"
                     "Lectura: antes del saneo facturado=49500 contra conciliado=36000; las huérfanas son las facturas 3, 6 y 7; el PRAGMA vuelve a dar vacío (recuerda: sin FK declarada no audita nada); tras la remediación 36000|36000 y 3 filas en cuarentena para su tratamiento contable. El NOT IN del DELETE es seguro aquí porque members.member_id es PK (nunca NULL) — con una columna anulable sería la trampa del NOT IN con NULL. Cierre estructural: la migración que convierta invoices a una tabla con member_id INTEGER NOT NULL REFERENCES members(member_id) convierte esta clase de corrupción en error de escritura inmediato; hasta entonces, esta suite debe correr programada, no a demanda."),
        ],
        verify=[
            {"name": "bug_informe_descuadra", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["1|2|18000", "7|49500"],
             "expect_stdout_not_contains": ["3|3|7000", "6|5|5000", "7|3|1500"]},
            {"name": "fix_auditoria_cuarentena", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["49500|36000", "3|3|7000", "6|5|5000", "7|3|1500",
                                        "(0 filas)", "36000|36000"]},
        ],
        tags=["sql", "integrity", "orphan-rows", "foreign-keys", "data-quality", "gym"],
    ),
]
