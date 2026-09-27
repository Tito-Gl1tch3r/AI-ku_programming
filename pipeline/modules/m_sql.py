"""m_sql.py — Módulo SQL (parte 1, task 3-a) del dataset AI-ku_programming.

30 ejemplos profundos de SQL (SQLite) en español, identificadores en inglés.
Cobertura: diseño de esquema y restricciones (FK/CHECK/UNIQUE), joins complejos
(anti-join, self-join), CTEs recursivas (organigrama, rutas con ciclos), window
functions (RANK/ROW_NUMBER/LAG, frames, sumas móviles), upsert ON CONFLICT,
transacciones y triggers de auditoría, índices con EXPLAIN QUERY PLAN (SCAN →
SEARCH), debugging clásico de SQL (NULL=NULL, LEFT JOIN degradado por WHERE,
GROUP BY incompleto, COUNT(*) vs COUNT(col), fan-out m:n, frames RANGE vs ROWS,
ancla recursiva, upsert acumulativo, greatest-per-group) y analítica (cohortes,
retención, LTV, cesta de la compra, outliers, keyset pagination, refactor con
equivalencia EXCEPT, reconstrucción de tabla).

Verificación: acción "sql" del harness — setup = pares [msg, block] con el DDL
del mensaje user (msg 1 = primer mensaje user, -1 = último), ejecución sobre
SQLite :memory: y comprobación de la salida con expect_stdout_contains /
expect_stdout_not_contains. Todas las consultas con ORDER BY determinista; en
los ejemplos de debugging hay un paso extra que ejecuta la consulta rota y
comprueba que NO produce el resultado correcto.

Distribución: 10 implementation, 9 debugging, 5 optimization, 3 analysis,
2 refactoring, 1 migration. Dificultad: 3 medium, 16 hard, 7 very_hard, 4 extreme.
"""

from schema import E

EXAMPLES = [
    # ---------------------------------------------------------------- I1 (medium)
    E(
        language="sql", domain="databases", subdomain="schema_design",
        difficulty="medium", task_type="implementation",
        messages=[
            ("user", "Tenemos que formalizar la gestión de citas del policlínico. Estas tablas ya existen en producción:\n"
                     "```sql\n"
                     "CREATE TABLE medicos (\n"
                     "  id INTEGER PRIMARY KEY,\n"
                     "  dni TEXT NOT NULL UNIQUE,\n"
                     "  nombre TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE pacientes (\n"
                     "  id INTEGER PRIMARY KEY,\n"
                     "  dni TEXT NOT NULL UNIQUE,\n"
                     "  nombre TEXT NOT NULL,\n"
                     "  fecha_nacimiento TEXT NOT NULL\n"
                     ");\n"
                     "INSERT INTO medicos VALUES (1, '44441111M', 'Dra. Soler'), (2, '55552222P', 'Dr. Ibanez');\n"
                     "INSERT INTO pacientes VALUES (1, '11112222A', 'Lucia Ramos', '1990-05-14'), (2, '22223333B', 'Pablo Orta', '1985-11-02');\n"
                     "```\n"
                     "Necesito la tabla de citas con estas reglas de negocio: (1) un médico no puede tener dos citas ACTIVAS a la misma hora —las canceladas no ocupan hueco—; (2) la duración debe ser estrictamente positiva; (3) el estado solo admite 'programada', 'atendida' o 'cancelada'; (4) si se elimina un paciente, sus citas deben eliminarse en cascada; (5) no debe poder eliminarse un médico que tenga citas. Entrega el DDL y demuestra con PRAGMA que el esquema queda íntegro y sin violaciones de claves ajenas."),
            ("assistant", "Regla por restricción: (1) exige un índice único PARCIAL —un UNIQUE de tabla no puede condicionarse por el estado, y las canceladas deben quedar fuera—; (2) CHECK duracion_min > 0; (3) CHECK de dominio con IN; (4) ON DELETE CASCADE en citas→pacientes; (5) ON DELETE RESTRICT en citas→médicos (SQLite impide borrar el padre mientras existan hijas). Voy a aplicar un DDL provisional y a probar el caso límite: un hueco ocupado por una cita CANCELADA debe seguir siendo asignable."),
            ("tool", "sqlite> CREATE TABLE citas (id INTEGER PRIMARY KEY, medico_id INTEGER NOT NULL REFERENCES medicos(id), paciente_id INTEGER NOT NULL REFERENCES pacientes(id), fecha_hora TEXT NOT NULL, duracion_min INTEGER NOT NULL, estado TEXT NOT NULL DEFAULT 'programada');\n"
                     "sqlite> CREATE UNIQUE INDEX uq_citas_slot_medico ON citas(medico_id, fecha_hora) WHERE estado <> 'cancelada';\n"
                     "sqlite> INSERT INTO citas VALUES (99, 1, 2, '2024-06-03 09:00', 30, 'programada');\n"
                     "Runtime error: UNIQUE constraint failed: index 'uq_citas_slot_medico' (19)\n"
                     "sqlite> INSERT INTO citas VALUES (99, 1, 2, '2024-06-03 09:00', 30, 'cancelada');\n"
                     "sqlite> DELETE FROM citas WHERE id = 99;\n"
                     "sqlite> -- la cancelada se admitió en el mismo hueco: el índice parcial la ignora"),
            ("assistant", "La sonda confirma la semántica del índice parcial: rechaza la cita activa duplicada y admite la cancelada en el mismo hueco. DDL definitivo con todas las reglas, carga de humo y verificación:\n"
                     "```sql\n"
                     "CREATE TABLE citas (\n"
                     "  id INTEGER PRIMARY KEY,\n"
                     "  medico_id INTEGER NOT NULL REFERENCES medicos(id) ON DELETE RESTRICT,\n"
                     "  paciente_id INTEGER NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,\n"
                     "  fecha_hora TEXT NOT NULL,\n"
                     "  duracion_min INTEGER NOT NULL CHECK (duracion_min > 0),\n"
                     "  estado TEXT NOT NULL DEFAULT 'programada'\n"
                     "    CHECK (estado IN ('programada','atendida','cancelada'))\n"
                     ");\n"
                     "CREATE UNIQUE INDEX uq_citas_slot_medico ON citas(medico_id, fecha_hora)\n"
                     "  WHERE estado <> 'cancelada';\n"
                     "INSERT INTO citas VALUES (1, 1, 1, '2024-06-03 09:00', 30, 'programada');\n"
                     "INSERT INTO citas VALUES (2, 1, 2, '2024-06-03 09:30', 30, 'programada');\n"
                     "INSERT INTO citas VALUES (3, 2, 1, '2024-06-03 09:00', 20, 'cancelada');\n"
                     "PRAGMA integrity_check;\n"
                     "PRAGMA foreign_key_check;\n"
                     "SELECT m.nombre, p.nombre, c.fecha_hora, c.estado\n"
                     "FROM citas c\n"
                     "JOIN medicos m ON m.id = c.medico_id\n"
                     "JOIN pacientes p ON p.id = c.paciente_id\n"
                     "ORDER BY c.fecha_hora, m.nombre, p.nombre;\n"
                     "```\n"
                     "Notas: la fila 3 colisiona en hueco con la fila 1 pero está cancelada, así que el índice parcial la admite. Si alguien ejecutara DELETE FROM medicos WHERE id = 1, SQLite respondería «FOREIGN KEY constraint failed» por el RESTRICT; en cambio, borrar a un paciente arrastraría sus citas por el CASCADE. Los PRAGMA deben devolver «ok» y cero filas; cualquier otra cosa indicaría un esquema mal cosido."),
        ],
        verify=[
            {"name": "ddl_integro_y_datos", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["ok", "(0 filas)",
                                        "Dr. Ibanez|Lucia Ramos|2024-06-03 09:00|cancelada",
                                        "Dra. Soler|Pablo Orta|2024-06-03 09:30|programada"]},
        ],
        tags=["sql", "ddl", "constraints", "schema-design", "partial-index"],
    ),
    # ---------------------------------------------------------------- I2 (hard)
    E(
        language="sql", domain="databases", subdomain="topn_ties",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "El informe de dirección pide el top-2 de productos por categoría según unidades vendidas. La consulta actual usa GROUP BY con MAX y dos problemas: el producto que acompaña al MAX es arbitrario cuando hay empates, y los empates se pierden (si dos productos comparten el segundo puesto, deben salir LOS DOS). Datos de ventas del mes:\n"
                     "```sql\n"
                     "CREATE TABLE product_sales (\n"
                     "  sale_id INTEGER PRIMARY KEY,\n"
                     "  category TEXT NOT NULL,\n"
                     "  product TEXT NOT NULL,\n"
                     "  units INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO product_sales VALUES (1,'audio','auriculares',120),(2,'audio','altavoz',95),(3,'audio','soundbar',95),(4,'video','monitor',80),(5,'video','proyector',80),(6,'video','webcam',50);\n"
                     "```\n"
                     "Entrega la consulta correcta, reproducible y con empates incluidos, y justifica RANK frente a ROW_NUMBER."),
            ("assistant", "Requisito matizado: «top-2» con empates = puestos 1 y 2 SEGÚN RANK, no dos filas. Con RANK los empatados comparten puesto y el siguiente salta (1,2,2), así que rk <= 2 puede devolver 3 filas en audio; en video los dos productos con 80 comparten el puesto 1 y webcam (puesto 3) queda fuera. ROW_NUMBER numeraría 1,2,3 sin empates y cortaría de forma arbitraria (dependiendo del criterio de desempate). Antes de escribir la solución verifico el comportamiento de la consulta actual para documentar el síntoma."),
            ("tool", "sqlite> SELECT category, product, MAX(units) FROM product_sales GROUP BY category;\n"
                     "audio|auriculares|120\n"
                     "video|monitor|80\n"
                     "sqlite> -- en 'video' proyector también tiene 80: la fila mostrada es arbitraria\n"
                     "sqlite> -- y el empate completo no aparece en ninguna forma"),
            ("assistant", "Confirmado: el GROUP BY mezcla agregación con columnas sueltas y ni identifica la fila ganadora ni conserva los empates. Solución: subconsulta con RANK particionado por categoría, filtro rk <= 2, y ORDER BY total (categoría, puesto, producto) para reproducibilidad:\n"
                     "```sql\n"
                     "SELECT category, product, units, rk\n"
                     "FROM (\n"
                     "  SELECT category, product, units,\n"
                     "         RANK() OVER (PARTITION BY category ORDER BY units DESC) AS rk\n"
                     "  FROM product_sales\n"
                     ") t\n"
                     "WHERE rk <= 2\n"
                     "ORDER BY category, rk, product;\n"
                     "```\n"
                     "Como contraste, dejo también la versión con ROW_NUMBER y desempate alfabético: es determinista, pero CORTA empates en lugar de incluirlos — útil cuando el requisito es «exactamente n filas», no aquí.\n"
                     "```sql\n"
                     "SELECT category, product, units, rn\n"
                     "FROM (\n"
                     "  SELECT category, product, units,\n"
                     "         ROW_NUMBER() OVER (PARTITION BY category ORDER BY units DESC, product) AS rn\n"
                     "  FROM product_sales\n"
                     ") t\n"
                     "WHERE rn <= 2\n"
                     "ORDER BY category, rn, product;\n"
                     "```"),
        ],
        verify=[
            {"name": "rank_con_empates", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["audio|auriculares|120|1", "audio|altavoz|95|2",
                                        "audio|soundbar|95|2", "video|monitor|80|1",
                                        "video|proyector|80|1"],
             "expect_stdout_not_contains": ["video|webcam"]},
            {"name": "rownumber_corta_empates", "action": "sql", "lang": "sql", "msg": -1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["audio|auriculares|120|1", "video|proyector|80|2"],
             "expect_stdout_not_contains": ["soundbar"]},
        ],
        tags=["sql", "window-functions", "ranking", "ties"],
    ),
    # ---------------------------------------------------------------- I3 (hard)
    E(
        language="sql", domain="databases", subdomain="upsert_conciliation",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Conciliación de saldos: cada noche llega un lote de apuntes y hay que aplicarlo sobre el libro mayor de forma idempotente. Reglas: si la cuenta ya existe, los céntimos del apunte se SUMAN al saldo y la versión pasa a la entrante SOLO si esta es estrictamente mayor (los reenvíos con versión vieja se ignoran); si no existe, se crea. El lote puede traer varias líneas de la misma cuenta. Esquema y lote de esta noche:\n"
                     "```sql\n"
                     "CREATE TABLE ledger_balances (\n"
                     "  account_number TEXT PRIMARY KEY,\n"
                     "  cents INTEGER NOT NULL DEFAULT 0,\n"
                     "  version INTEGER NOT NULL DEFAULT 0\n"
                     ");\n"
                     "INSERT INTO ledger_balances VALUES ('ACC-100', 10000, 3), ('ACC-200', 500, 1);\n"
                     "CREATE TABLE incoming_batch (\n"
                     "  line_no INTEGER PRIMARY KEY,\n"
                     "  account_number TEXT NOT NULL,\n"
                     "  cents INTEGER NOT NULL,\n"
                     "  version INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO incoming_batch VALUES (1,'ACC-100',2500,4),(2,'ACC-200',300,2),(3,'ACC-100',-300,2),(4,'ACC-300',1200,1),(5,'ACC-100',750,4);\n"
                     "```\n"
                     "Escribe el INSERT con ON CONFLICT que aplique el lote completo en una sola sentencia."),
            ("assistant", "Piezas clave del upsert: la cláusula ON CONFLICT (account_number) DO UPDATE permite leer el valor previo con el nombre de la tabla y el entrante con excluded; el guard WHERE excluded.version > ledger_balances.version hace que las líneas 3 (v2) y 5 (v4, ya aplicada por la línea 1) no toquen nada; y la suma acumulada se expresa como cents = ledger_balances.cents + excluded.cents. Las líneas del lote se aplican en orden de escaneo (line_no, que es el rowid), así que la v4 entra antes de que llegue el reenvío v2. Antes de tocar nada, fijo el estado previo como testigo."),
            ("tool", "sqlite> SELECT account_number, cents, version FROM ledger_balances ORDER BY account_number;\n"
                     "ACC-100|10000|3\n"
                     "ACC-200|500|1\n"
                     "sqlite> -- testigo previo: ACC-100 10000/v3, ACC-200 500/v1"),
            ("assistant", "Sentencia única de aplicación y comprobación final:\n"
                     "```sql\n"
                     "INSERT INTO ledger_balances (account_number, cents, version)\n"
                     "SELECT account_number, cents, version FROM incoming_batch WHERE line_no > 0\n"
                     "ON CONFLICT (account_number) DO UPDATE SET\n"
                     "  cents = ledger_balances.cents + excluded.cents,\n"
                     "  version = excluded.version\n"
                     "WHERE excluded.version > ledger_balances.version;\n"
                     "SELECT account_number, cents, version FROM ledger_balances ORDER BY account_number;\n"
                     "```\n"
                     "Traza esperada: línea 1 crea conflicto y suma (10000+2500, v4); línea 2 suma (500+300, v2); línea 3 falla el guard (2 > 4 falso) y no hace nada; línea 4 inserta ACC-300; línea 5 falla el guard (4 > 4 falso). Nota de parsing: cuando el INSERT toma valores de un SELECT, la cláusula ON CONFLICT exige que el SELECT lleve WHERE (aquí line_no > 0) para desambiguar. Variantes útiles: ON CONFLICT DO NOTHING para marcar líneas ya procesadas, y RETURNING para obtener las filas afectadas en el mismo viaje."),
        ],
        verify=[
            {"name": "upsert_guard_version", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["ACC-100|12500|4", "ACC-200|800|2", "ACC-300|1200|1"],
             "expect_stdout_not_contains": ["ACC-100|13250"]},
        ],
        tags=["sql", "upsert", "on-conflict", "idempotency"],
    ),
    # ---------------------------------------------------------------- I4 (extreme)
    E(
        language="sql", domain="databases", subdomain="recursive_routes",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", "Planificador de rutas de la flota: la red de tramos es un grafo dirigido CON ciclos y necesito, desde el hub, el mejor itinerario a cada estación alcanzable (menos minutos; a igualdad, menos saltos) junto con el camino completo. La consulta no puede colgarse aunque existan ciclos. Red actual:\n"
                     "```sql\n"
                     "CREATE TABLE legs (\n"
                     "  leg_id INTEGER PRIMARY KEY,\n"
                     "  origin TEXT NOT NULL,\n"
                     "  destination TEXT NOT NULL,\n"
                     "  minutes INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO legs VALUES (1,'HUB-CENTRO','NORTE-1',3),(2,'NORTE-1','NORTE-2',4),(3,'HUB-CENTRO','NORTE-2',9),(4,'NORTE-2','ESTE-1',2),(5,'ESTE-1','HUB-CENTRO',1),(6,'NORTE-1','ESTE-1',8),(7,'ESTE-1','NORTE-1',5);\n"
                     "```\n"
                     "Entrega una única consulta SQLite que devuelva destino, minutos, saltos y ruta."),
            ("assistant", "Diseño en dos fases dentro de una misma consulta: (1) una CTE recursiva walk que enumera TODOS los caminos simples desde el hub, acumulando minutos, saltos y el camino como texto '/HUB-CENTRO/NORTE-1/...'; la poda de ciclos se hace comprobando, antes de extender a un destino, que 'destino' no aparezca ya en el camino — con delimitadores a ambos lados ('/NORTE-1/') para que '/NORTE-1/' no haga match con '/NORTE-12/'; (2) sobre walk, ROW_NUMBER particionado por estación ordenado por minutos, saltos y camino, y me quedo con rn = 1. Primero mido cuántos caminos simples genera esta red para acotar el coste."),
            ("tool", "sqlite> WITH RECURSIVE walk(station, total_min, hops, path) AS (SELECT 'HUB-CENTRO', 0, 0, '/HUB-CENTRO' UNION ALL SELECT l.destination, w.total_min + l.minutes, w.hops + 1, w.path || '/' || l.destination FROM walk w JOIN legs l ON l.origin = w.station WHERE instr(w.path || '/', '/' || l.destination || '/') = 0) SELECT COUNT(*) FROM walk;\n"
                     "8\n"
                     "sqlite> -- 8 caminos simples: la poda por instr acota la recursión y garantiza terminación"),
            ("assistant", "Ocho caminos simples (el ciclo ESTE-1→HUB-CENTRO y el tramo de vuelta ESTE-1→NORTE-1 se podan por repetición de estación en el camino). Consulta final:\n"
                     "```sql\n"
                     "WITH RECURSIVE walk(station, total_min, hops, path) AS (\n"
                     "  SELECT 'HUB-CENTRO', 0, 0, '/HUB-CENTRO'\n"
                     "  UNION ALL\n"
                     "  SELECT l.destination, w.total_min + l.minutes, w.hops + 1,\n"
                     "         w.path || '/' || l.destination\n"
                     "  FROM walk w\n"
                     "  JOIN legs l ON l.origin = w.station\n"
                     "  WHERE instr(w.path || '/', '/' || l.destination || '/') = 0\n"
                     "),\n"
                     "best AS (\n"
                     "  SELECT station, total_min, hops, path,\n"
                     "         ROW_NUMBER() OVER (PARTITION BY station\n"
                     "                            ORDER BY total_min, hops, path) AS rn\n"
                     "  FROM walk\n"
                     ")\n"
                     "SELECT station AS destino, total_min AS minutos, hops AS saltos,\n"
                     "       SUBSTR(path, 2) AS ruta\n"
                     "FROM best\n"
                     "WHERE rn = 1 AND station <> 'HUB-CENTRO'\n"
                     "ORDER BY station;\n"
                     "```\n"
                     "Verificación semántica: a NORTE-2 se llega directo en 9 o vía NORTE-1 en 3+4=7 → gana 7; a ESTE-1, vía NORTE-1 directo son 3+8=11 y vía NORTE-1→NORTE-2 son 3+4+2=9 → gana 9 con 3 saltos. El ORDER BY total_min, hops, path rompe empates de forma reproducible; SUBSTR(path, 2) solo elimina la barra inicial. En grafos densos este patrón explora caminos simples exponenciales: para producción real se añadiría una cota de profundidad (w.hops < N) o Dijkstra externo, pero para redes de decenas de nodos la CTE es correcta y auditables."),
        ],
        verify=[
            {"name": "rutas_minimas", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["ESTE-1|9|3|HUB-CENTRO/NORTE-1/NORTE-2/ESTE-1",
                                        "NORTE-1|3|1|HUB-CENTRO/NORTE-1",
                                        "NORTE-2|7|2|HUB-CENTRO/NORTE-1/NORTE-2"],
             "expect_stdout_not_contains": ["NORTE-2|9", "ESTE-1|11"]},
        ],
        tags=["sql", "recursive-cte", "graph", "shortest-path"],
    ),
    # ---------------------------------------------------------------- I5 (very_hard)
    E(
        language="sql", domain="databases", subdomain="hierarchy_subtree",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Del organigrama del hospital necesito un informe jerárquico completo: para cada empleado, su nivel (la dirección general es nivel 0), el camino jerárquico legible desde la raíz, el número de informes directos y el tamaño de su subárbol (descendientes totales, sin contarse a sí mismo). Tabla:\n"
                     "```sql\n"
                     "CREATE TABLE staff (\n"
                     "  id INTEGER PRIMARY KEY,\n"
                     "  name TEXT NOT NULL,\n"
                     "  role TEXT NOT NULL,\n"
                     "  manager_id INTEGER REFERENCES staff(id)\n"
                     ");\n"
                     "INSERT INTO staff VALUES (1,'Adriana Costa','directora general',NULL),(2,'Bruno Diaz','jefe urgencias',1),(3,'Carla Medina','jefa farmacia',1),(4,'Diego Ruiz','medico',2),(5,'Elena Paz','medica',2),(6,'Fabio Lugo','farmaceutico',3),(7,'Gina Rios','enfermera',2);\n"
                     "```\n"
                     "Una sola consulta, orden determinista."),
            ("assistant", "Dos recursiones distintas con propósitos distintos: tree (ancla manager_id IS NULL) construye nivel y camino bajando desde la raíz; lineage enumera pares (raíz, miembro) partiendo de CADA nodo como raíz propia, de modo que contar lineage por root me da el subárbol completo (por eso resto 1 para excluir al propio nodo). Los informes directos son un recuento plano sobre manager_id. Verifico primero la forma cruda de la tabla."),
            ("tool", "sqlite> SELECT id, name, manager_id FROM staff ORDER BY id;\n"
                     "1|Adriana Costa|\n"
                     "2|Bruno Diaz|1\n"
                     "3|Carla Medina|1\n"
                     "4|Diego Ruiz|2\n"
                     "5|Elena Paz|2\n"
                     "6|Fabio Lugo|3\n"
                     "7|Gina Rios|2\n"
                     "sqlite> -- un único raíz (manager NULL), árbol de 3 niveles"),
            ("assistant", "Consulta final:\n"
                     "```sql\n"
                     "WITH RECURSIVE tree(id, name, level, path) AS (\n"
                     "  SELECT id, name, 0, name FROM staff WHERE manager_id IS NULL\n"
                     "  UNION ALL\n"
                     "  SELECT s.id, s.name, t.level + 1, t.path || ' > ' || s.name\n"
                     "  FROM staff s JOIN tree t ON s.manager_id = t.id\n"
                     "),\n"
                     "lineage(root, member_id) AS (\n"
                     "  SELECT id, id FROM staff\n"
                     "  UNION ALL\n"
                     "  SELECT lin.root, s.id\n"
                     "  FROM lineage lin JOIN staff s ON s.manager_id = lin.member_id\n"
                     ")\n"
                     "SELECT t.level AS nivel, t.path AS jerarquia, t.name AS persona,\n"
                     "       (SELECT COUNT(*) FROM staff s WHERE s.manager_id = t.id) AS informes_directos,\n"
                     "       (SELECT COUNT(*) FROM lineage lin WHERE lin.root = t.id) - 1 AS tamano_subarbol\n"
                     "FROM tree t\n"
                     "ORDER BY t.level, t.name;\n"
                     "```\n"
                     "Puntos sutiles: lineage usa UNION ALL (no hay ciclos — manager_id forma un árbol y cada recursión estrictamente desciende); si la tabla pudiera contener ciclos habría que podar con un camino acumulado como en el planificador de rutas. Las subconsultas correlacionadas sobre CTEs son legales en SQLite y aquí el coste es trivial. Sanity check: la raíz debe dar informes_directos = 2 y tamano_subarbol = 6 (toda la plantilla menos ella)."),
        ],
        verify=[
            {"name": "organigrama_completo", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["0|Adriana Costa|Adriana Costa|2|6",
                                        "1|Adriana Costa > Bruno Diaz|Bruno Diaz|3|3",
                                        "1|Adriana Costa > Carla Medina|Carla Medina|1|1",
                                        "2|Adriana Costa > Bruno Diaz > Gina Rios|Gina Rios|0|0",
                                        "2|Adriana Costa > Carla Medina > Fabio Lugo|Fabio Lugo|0|0"]},
        ],
        tags=["sql", "recursive-cte", "hierarchy", "subtree"],
    ),
    # ---------------------------------------------------------------- I6 (hard)
    E(
        language="sql", domain="databases", subdomain="moving_windows_iot",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Telemetría de cámaras frigoríficas: por cada sensor necesito, en UNA sola pasada y sin subconsultas por fila, (1) la media móvil de las últimas 3 lecturas (la actual y las dos anteriores), (2) el delta respecto a la lectura anterior del MISMO sensor y (3) una marca 'pico' cuando ese delta sea ≥ 5.0 grados. Tabla:\n"
                     "```sql\n"
                     "CREATE TABLE readings (\n"
                     "  read_id INTEGER PRIMARY KEY,\n"
                     "  sensor_id INTEGER NOT NULL,\n"
                     "  taken_at TEXT NOT NULL,\n"
                     "  temp REAL NOT NULL\n"
                     ");\n"
                     "INSERT INTO readings VALUES (1,10,'2024-05-01 10:00',21.0),(2,10,'2024-05-01 10:05',22.0),(3,10,'2024-05-01 10:10',30.0),(4,10,'2024-05-01 10:15',23.0),(5,20,'2024-05-01 10:00',18.5),(6,20,'2024-05-01 10:05',18.5),(7,20,'2024-05-01 10:10',19.0),(8,20,'2024-05-01 10:15',27.5);\n"
                     "```\n"
                     "Salida: sensor, instante, temperatura, media móvil (1 decimal), delta (1 decimal) y alerta."),
            ("assistant", "Tres ventanas sobre la misma partición (sensor) y el mismo orden (taken_at): AVG con frame ROWS BETWEEN 2 PRECEDING AND CURRENT ROW para la media móvil —ROWS, no RANGE, para que el frame cuente FILAS y no valores empatados—; LAG(temp) para el delta; y el CASE reutiliza el mismo LAG. La primera lectura de cada sensor tiene LAG nulo → delta nulo → alerta vacía por el ELSE. Confirmo los datos crudos antes de escribir la ventana."),
            ("tool", "sqlite> SELECT sensor_id, taken_at, temp FROM readings ORDER BY sensor_id, taken_at;\n"
                     "10|2024-05-01 10:00|21.0\n"
                     "10|2024-05-01 10:05|22.0\n"
                     "10|2024-05-01 10:10|30.0\n"
                     "10|2024-05-01 10:15|23.0\n"
                     "20|2024-05-01 10:00|18.5\n"
                     "20|2024-05-01 10:05|18.5\n"
                     "20|2024-05-01 10:10|19.0\n"
                     "20|2024-05-01 10:15|27.5"),
            ("assistant", "Consulta final:\n"
                     "```sql\n"
                     "SELECT sensor_id, taken_at, temp,\n"
                     "       ROUND(AVG(temp) OVER (PARTITION BY sensor_id ORDER BY taken_at\n"
                     "                             ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1) AS media_3,\n"
                     "       ROUND(temp - LAG(temp) OVER (PARTITION BY sensor_id ORDER BY taken_at), 1) AS delta,\n"
                     "       CASE WHEN temp - LAG(temp) OVER (PARTITION BY sensor_id ORDER BY taken_at) >= 5.0\n"
                     "            THEN 'pico' ELSE '' END AS alerta\n"
                     "FROM readings\n"
                     "ORDER BY sensor_id, taken_at;\n"
                     "```\n"
                     "Sanity check sobre el sensor 10: en 10:10 la media móvil es (21+22+30)/3 = 24.3 y el delta 30.0-22.0 = 8.0 → 'pico'; en 10:15 la ventana desliza a (22+30+23)/3 = 25.0 con delta -7.0. En el sensor 20 el salto final es 27.5-19.0 = 8.5 → 'pico'. Detalles que suelen morder: si hubiera DOS lecturas con el mismo taken_at, el ORDER BY de la ventana sería ambiguo y habría que desempatar por read_id; y usar RANGE (por defecto) con valores repetidos cambiaría el frame de 3 filas a «3 valores distintos», dando medias distintas — lo veremos como bug más adelante."),
        ],
        verify=[
            {"name": "ventanas_iot", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["10|2024-05-01 10:10|30.0|24.3|8.0|pico",
                                        "10|2024-05-01 10:15|23.0|25.0|-7.0|",
                                        "20|2024-05-01 10:15|27.5|21.7|8.5|pico",
                                        "10|2024-05-01 10:00|21.0|21.0||"]},
        ],
        tags=["sql", "window-functions", "moving-average", "lag", "iot"],
    ),
    # ---------------------------------------------------------------- I7 (hard)
    E(
        language="sql", domain="databases", subdomain="anti_join_availability",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Biblioteca municipal, dos consultas del panel: (a) socios SIN ningún préstamo activo (returned_on IS NULL); (b) libros que NUNCA se han prestado. Quiero anti-joins con NOT EXISTS y, como control, la versión equivalente con LEFT JOIN ... IS NULL; explícame también por qué NOT IN es la peor opción aquí. Esquema y datos:\n"
                     "```sql\n"
                     "CREATE TABLE members (\n"
                     "  member_id INTEGER PRIMARY KEY,\n"
                     "  name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE books (\n"
                     "  book_id INTEGER PRIMARY KEY,\n"
                     "  title TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE loans (\n"
                     "  loan_id INTEGER PRIMARY KEY,\n"
                     "  book_id INTEGER NOT NULL REFERENCES books(book_id),\n"
                     "  member_id INTEGER NOT NULL REFERENCES members(member_id),\n"
                     "  returned_on TEXT\n"
                     ");\n"
                     "INSERT INTO members VALUES (1,'Ana Fuentes'),(2,'Marcos Vera'),(3,'Sofia Canal'),(4,'Ivan Pena');\n"
                     "INSERT INTO books VALUES (1,'Cien anos de soledad'),(2,'Rayuela'),(3,'La casa de los espiritus'),(4,'Ficciones');\n"
                     "INSERT INTO loans VALUES (1,1,1,NULL),(2,1,2,'2024-02-10'),(3,2,3,NULL),(4,2,1,'2024-03-05');\n"
                     "```\n"
                     "Orden determinista en ambas consultas."),
            ("assistant", "Préstamos activos: loan 1 (Ana, libro 1) y loan 3 (Sofia, libro 2). Por tanto (a) debe devolver Marcos Vera e Ivan Pena, y (b) los libros 3 y 4 ('La casa de los espiritus' y 'Ficciones'), pues los libros 1 y 2 sí tienen historial. El anti-join con NOT EXISTS es semi-join: por cada fila externa basta UNA prueba de existencia, corta al primer match y no depende del número de préstamos. El LEFT JOIN ... IS NULL es equivalente aquí, pero si la tabla interna puede repetir la clave hay que pensar en duplicados. NOT IN con subconsulta tiene DOS problemas: semántico (si la subconsulta devuelve un único NULL, el NOT IN completo devuelve vacío por la lógica trivalente) y de rendimiento (materializa la lista completa). Compruebo el estado crudo de loans."),
            ("tool", "sqlite> SELECT loan_id, book_id, member_id, returned_on FROM loans ORDER BY loan_id;\n"
                     "1|1|1|\n"
                     "2|1|2|2024-02-10\n"
                     "3|2|3|\n"
                     "4|2|1|2024-03-05\n"
                     "sqlite> -- activos: loans 1 y 3 (returned_on NULL)"),
            ("assistant", "Consultas principales (NOT EXISTS) y control (LEFT JOIN), ambas deterministas:\n"
                     "```sql\n"
                     "SELECT m.member_id, m.name\n"
                     "FROM members m\n"
                     "WHERE NOT EXISTS (\n"
                     "  SELECT 1 FROM loans l\n"
                     "  WHERE l.member_id = m.member_id AND l.returned_on IS NULL\n"
                     ")\n"
                     "ORDER BY m.member_id;\n"
                     "SELECT b.book_id, b.title\n"
                     "FROM books b\n"
                     "WHERE NOT EXISTS (SELECT 1 FROM loans l WHERE l.book_id = b.book_id)\n"
                     "ORDER BY b.book_id;\n"
                     "```\n"
                     "```sql\n"
                     "SELECT m.member_id, m.name\n"
                     "FROM members m\n"
                     "LEFT JOIN loans l ON l.member_id = m.member_id AND l.returned_on IS NULL\n"
                     "WHERE l.loan_id IS NULL\n"
                     "ORDER BY m.member_id;\n"
                     "SELECT b.book_id, b.title\n"
                     "FROM books b\n"
                     "LEFT JOIN loans l ON l.book_id = b.book_id\n"
                     "WHERE l.loan_id IS NULL\n"
                     "ORDER BY b.book_id;\n"
                     "```\n"
                     "Fíjate en el control de (a): la condición returned_on IS NULL va dentro del ON, no en el WHERE — moverla al WHERE degradaría el LEFT JOIN a INNER y cambiaría el resultado (es exactamente el bug que depuraremos en otro ejemplo). Con NOT IN, además del riesgo NULL, un índice sobre loans(member_id) acelera EXISTS pero no salva la semántica; si algún día una carga defectuosa inserta un préstamo con member_id NULL, la consulta con NOT IN devolvería CERO socios en silencio."),
        ],
        verify=[
            {"name": "not_exists_antijoin", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2|Marcos Vera", "4|Ivan Pena",
                                        "3|La casa de los espiritus", "4|Ficciones"],
             "expect_stdout_not_contains": ["1|Ana Fuentes", "3|Sofia Canal",
                                            "1|Cien anos de soledad", "2|Rayuela"]},
            {"name": "leftjoin_control", "action": "sql", "lang": "sql", "msg": -1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2|Marcos Vera", "4|Ivan Pena",
                                        "3|La casa de los espiritus", "4|Ficciones"],
             "expect_stdout_not_contains": ["1|Ana Fuentes", "3|Sofia Canal"]},
        ],
        tags=["sql", "anti-join", "not-exists", "left-join"],
    ),
    # ---------------------------------------------------------------- I8 (very_hard)
    E(
        language="sql", domain="databases", subdomain="transactions_audit",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Núcleo bancario mínimo: transferencias atómicas entre cuentas con dos garantías. (1) Ninguna cuenta puede quedar en negativo — el intento debe abortar SIN dejar cambios a medias. (2) Cada variación de saldo queda auditada (cuenta, saldo anterior, saldo posterior). Tengo el DDL con los triggers ya definidos:\n"
                     "```sql\n"
                     "CREATE TABLE accounts (\n"
                     "  account_id INTEGER PRIMARY KEY,\n"
                     "  owner TEXT NOT NULL,\n"
                     "  balance_cents INTEGER NOT NULL CHECK (balance_cents >= 0)\n"
                     ");\n"
                     "CREATE TABLE audit_transfers (\n"
                     "  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                     "  account_id INTEGER NOT NULL,\n"
                     "  balance_before INTEGER NOT NULL,\n"
                     "  balance_after INTEGER NOT NULL\n"
                     ");\n"
                     "CREATE TRIGGER trg_no_overdraft BEFORE UPDATE ON accounts WHEN NEW.balance_cents < 0 BEGIN SELECT RAISE(ABORT, 'saldo insuficiente'); END;\n"
                     "CREATE TRIGGER trg_account_audit AFTER UPDATE ON accounts BEGIN INSERT INTO audit_transfers (account_id, balance_before, balance_after) VALUES (OLD.account_id, OLD.balance_cents, NEW.balance_cents); END;\n"
                     "```\n"
                     "Ejecuta la transferencia de 12000 céntimos de la cuenta 1 a la 2: carga inicial, débito, crédito, commit y verificación de saldos y auditoría. Explícame también qué pasa si el débito viola el guard con transacción explícita."),
            ("assistant", "El CHECK (balance_cents >= 0) es la última línea de defensa, pero el trigger BEFORE UPDATE con RAISE(ABORT) aborta la UPDATE en el momento exacto y devuelve el error a la aplicación; el AFTER UPDATE audita solo actualizaciones que SÍ ocurrieron (RAISE en el BEFORE impide que el AFTER llegue a dispararse). La atomicidad de negocio no la dan los triggers sino la transacción: BEGIN → débito → crédito → COMMIT; si el débito aborta a mitad, hay que hacer ROLLBACK explícito porque SQLite NO deshace automáticamente lo ya hecho dentro de la transacción — solo aborta la sentencia. Lo demuestro con un intento de sobregiro y luego ejecuto la transferencia real."),
            ("tool", "sqlite> BEGIN IMMEDIATE;\n"
                     "sqlite> INSERT INTO accounts (account_id, owner, balance_cents) VALUES (1,'Cuenta Origen', 50000), (2,'Cuenta Destino', 20000);\n"
                     "sqlite> UPDATE accounts SET balance_cents = balance_cents - 80000 WHERE account_id = 1;\n"
                     "Runtime error: saldo insuficiente (19)\n"
                     "sqlite> ROLLBACK;\n"
                     "sqlite> SELECT account_id, balance_cents FROM accounts ORDER BY account_id;\n"
                     "sqlite> -- tabla vacía: el ROLLBACK deshizo también la carga; sin él, la carga habría quedado a medias"),
            ("assistant", "El experimento muestra el punto clave: el error abortó la UPDATE, pero la INSERT previa seguía viva dentro de la transacción hasta el ROLLBACK. Transferencia real, atómica y auditada:\n"
                     "```sql\n"
                     "BEGIN;\n"
                     "INSERT INTO accounts (account_id, owner, balance_cents) VALUES (1,'Cuenta Origen', 50000), (2,'Cuenta Destino', 20000);\n"
                     "UPDATE accounts SET balance_cents = balance_cents - 12000 WHERE account_id = 1;\n"
                     "UPDATE accounts SET balance_cents = balance_cents + 12000 WHERE account_id = 2;\n"
                     "COMMIT;\n"
                     "SELECT account_id, owner, balance_cents FROM accounts ORDER BY account_id;\n"
                     "SELECT audit_id, account_id, balance_before, balance_after FROM audit_transfers ORDER BY audit_id;\n"
                     "```\n"
                     "Verificación: saldos 38000 y 32000 (la suma se conserva: 70000 antes y después), y dos filas de auditoría en el orden de ejecución. Añadidos de producción: usar BEGIN IMMEDIATE para tomar el bloqueo de escritura antes de leer (evita SQLITE_BUSY en el upgrade), y nunca confiar en CHECK sin trigger si el mensaje de error debe ser de negocio. En SQLite solo hay escritor simultáneo (modo journal por defecto), así que la serialización la da el motor; la atomicidad la da TU transacción."),
        ],
        verify=[
            {"name": "transferencia_atomica", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["1|Cuenta Origen|38000", "2|Cuenta Destino|32000",
                                        "1|1|50000|38000", "2|2|20000|32000"]},
        ],
        tags=["sql", "transactions", "triggers", "audit", "banking"],
    ),
    # ---------------------------------------------------------------- I9 (extreme)
    E(
        language="sql", domain="databases", subdomain="cohort_retention",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", "Analítica de e-commerce: matriz de retención por cohortes de primera compra. Para cada cohorte (mes de la primera compra) y cada offset de 0 a 2 meses: clientes activos ese mes relativo, tamaño de la cohorte y retención en % (entero, redondeado). Los clientes con varios pedidos en el mismo mes cuentan UNA vez. Pedidos del trimestre:\n"
                     "```sql\n"
                     "CREATE TABLE orders (\n"
                     "  order_id INTEGER PRIMARY KEY,\n"
                     "  customer_id INTEGER NOT NULL,\n"
                     "  purchased_on TEXT NOT NULL,\n"
                     "  amount_cents INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO orders VALUES (101,1,'2024-01-05',2000),(102,2,'2024-01-19',3500),(103,1,'2024-02-08',1500),(104,3,'2024-02-14',4000),(105,1,'2024-03-02',2500),(106,4,'2024-02-27',1200),(107,5,'2024-03-09',5000),(108,2,'2024-03-15',3000),(109,3,'2024-03-21',900),(110,1,'2024-04-10',1800);\n"
                     "```\n"
                     "Una sola consulta; sin funciones de fecha frágiles al cambiar de año."),
            ("assistant", "El truco clave es pasar de fechas a UN ÍNDICE DE MES absoluto: year*12 + month. Con eso el offset es una resta de enteros y no hay bordes de año que gestionar (strftime('%m') solo no sirve: '2024-01' - '2023-12' no es 1). Capas: activity calcula el índice; first_purchase toma MIN por cliente; cohorts une y calcula month_offset; sizes cuenta clientes únicos por cohorte; y el SELECT final agrega con COUNT(DISTINCT customer_id) sobre (cohorte, offset) previamente deduplicado. Verifico primero el mapeo de fechas a índices."),
            ("tool", "sqlite> SELECT customer_id, purchased_on, CAST(strftime('%Y', purchased_on) AS INTEGER)*12 + CAST(strftime('%m', purchased_on) AS INTEGER) AS m_idx FROM orders ORDER BY customer_id, purchased_on;\n"
                     "1|2024-01-05|24289\n"
                     "1|2024-02-08|24290\n"
                     "1|2024-03-02|24291\n"
                     "1|2024-04-10|24292\n"
                     "2|2024-01-19|24289\n"
                     "2|2024-03-15|24291\n"
                     "3|2024-02-14|24290\n"
                     "3|2024-03-21|24291\n"
                     "4|2024-02-27|24290\n"
                     "5|2024-03-09|24291\n"
                     "sqlite> -- 24289 = 2024*12+1 (enero 2024); offsets = resta de índices"),
            ("assistant", "Consulta final:\n"
                     "```sql\n"
                     "WITH activity AS (\n"
                     "  SELECT customer_id,\n"
                     "         CAST(strftime('%Y', purchased_on) AS INTEGER) * 12\n"
                     "             + CAST(strftime('%m', purchased_on) AS INTEGER) AS m_idx\n"
                     "  FROM orders\n"
                     "),\n"
                     "first_purchase AS (\n"
                     "  SELECT customer_id, MIN(m_idx) AS first_m FROM activity GROUP BY customer_id\n"
                     "),\n"
                     "cohorts AS (\n"
                     "  SELECT a.customer_id, f.first_m, a.m_idx - f.first_m AS month_offset\n"
                     "  FROM activity a JOIN first_purchase f ON f.customer_id = a.customer_id\n"
                     "),\n"
                     "sizes AS (\n"
                     "  SELECT first_m, COUNT(DISTINCT customer_id) AS n FROM cohorts GROUP BY first_m\n"
                     "),\n"
                     "offsets(offs) AS (\n"
                     "  SELECT 0 UNION ALL SELECT offs + 1 FROM offsets WHERE offs < 2\n"
                     ")\n"
                     "SELECT printf('%04d-%02d', g.first_m / 12, g.first_m % 12) AS cohorte,\n"
                     "       o.offs AS mes,\n"
                     "       COUNT(DISTINCT c.customer_id) AS activos,\n"
                     "       s.n AS tamano,\n"
                     "       CAST(ROUND(100.0 * COUNT(DISTINCT c.customer_id) / s.n) AS INTEGER) AS retencion\n"
                     "FROM (SELECT DISTINCT first_m FROM cohorts) g\n"
                     "CROSS JOIN offsets o\n"
                     "JOIN sizes s ON s.first_m = g.first_m\n"
                     "LEFT JOIN (SELECT DISTINCT first_m, customer_id, month_offset FROM cohorts) c\n"
                     "       ON c.first_m = g.first_m AND c.month_offset = o.offs\n"
                     "GROUP BY g.first_m, o.offs\n"
                     "ORDER BY g.first_m, o.offs;\n"
                     "```\n"
                     "Lectura de la matriz: cohortes 2024-01 y 2024-02 (2 clientes cada una), 2024-03 (1). La fila 2024-01 | mes 2 vale 100% porque ambos clientes del enero volvieron en marzo; el pedido 110 de abril queda fuera porque la rejilla de offsets llega solo hasta 2 (ventana de 90 días). Dos decisiones de diseño que suelen olvidarse: (1) la rejilla cohorte × offset se genera con CROSS JOIN contra una CTE recursiva de offsets y se conecta con LEFT JOIN — sin ella, los meses SIN actividad no producirían fila y la matriz tendría huecos (se perderían 2024-02|mes 2 o 2024-03|mes 1); el COUNT(DISTINCT customer_id) sobre el LEFT JOIN vacío da 0 y el 0% sale explícito; (2) la deduplicación previa es imprescindible: el cliente 1 tiene dos pedidos en enero y sin ella inflaría activos y retención."),
        ],
        verify=[
            {"name": "matriz_retencion", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2024-01|0|2|2|100", "2024-01|1|1|2|50",
                                        "2024-01|2|2|2|100", "2024-02|0|2|2|100",
                                        "2024-02|1|1|2|50", "2024-02|2|0|2|0",
                                        "2024-03|0|1|1|100", "2024-03|1|0|1|0"],
             "expect_stdout_not_contains": ["2024-01|3"]},
        ],
        tags=["sql", "cohorts", "retention", "date-arithmetic", "analytics"],
    ),
    # ---------------------------------------------------------------- I10 (hard)
    E(
        language="sql", domain="databases", subdomain="gap_filling",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Telemetría de inversores solares: el panel necesita una rejilla HORARIA completa (todas las horas × todos los inversores) aunque el sensor no haya reportado; para los huecos, el valor efectivo es la ÚLTIMA lectura anterior conocida (forward fill) y la fila debe marcarse 'hueco'. Datos del 10 de junio:\n"
                     "```sql\n"
                     "CREATE TABLE sensor_readings (\n"
                     "  reading_id INTEGER PRIMARY KEY,\n"
                     "  sensor_code TEXT NOT NULL,\n"
                     "  bucket TEXT NOT NULL,\n"
                     "  watts INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO sensor_readings VALUES (1,'INV-A','2024-06-10 08:00',4200),(2,'INV-A','2024-06-10 09:00',4350),(3,'INV-A','2024-06-10 11:00',4100),(4,'INV-A','2024-06-10 12:00',3900),(5,'INV-B','2024-06-10 08:00',3800),(6,'INV-B','2024-06-10 10:00',3600),(7,'INV-B','2024-06-10 11:00',3700);\n"
                     "```\n"
                     "INV-A no reporta a las 10:00; INV-B falla a las 09:00 y a las 12:00. Devuelve bucket, sensor, watts crudo, watts efectivo y estado."),
            ("assistant", "Tres piezas: (1) una CTE recursiva hrs genera el calendario de horas 08:00–12:00 con datetime('+1 hour') formateado de vuelta a 'YYYY-MM-DD HH:MM' para que el formato coincida EXACTAMENTE con los buckets almacenados (datetime a secas añade ':00' de segundos y el JOIN fallaría en silencio); (2) CROSS JOIN con los sensores distintos y LEFT JOIN de lecturas construye la rejilla con huecos; (3) para el forward fill, una subconsulta correlacionada toma la última lectura anterior del mismo sensor (ORDER BY bucket DESC LIMIT 1), con COALESCE por si el hueco fuera la primera hora. Verifico el calendario generado."),
            ("tool", "sqlite> WITH RECURSIVE hrs(bucket) AS (SELECT '2024-06-10 08:00' UNION ALL SELECT strftime('%Y-%m-%d %H:%M', datetime(bucket, '+1 hour')) FROM hrs WHERE bucket < '2024-06-10 12:00') SELECT * FROM hrs;\n"
                     "2024-06-10 08:00\n"
                     "2024-06-10 09:00\n"
                     "2024-06-10 10:00\n"
                     "2024-06-10 11:00\n"
                     "2024-06-10 12:00\n"
                     "sqlite> -- 5 horas; sin el strftime el tercer valor sería '2024-06-10 10:00:00'"),
            ("assistant", "Consulta final:\n"
                     "```sql\n"
                     "WITH RECURSIVE hrs(bucket) AS (\n"
                     "  SELECT '2024-06-10 08:00'\n"
                     "  UNION ALL\n"
                     "  SELECT strftime('%Y-%m-%d %H:%M', datetime(bucket, '+1 hour'))\n"
                     "  FROM hrs WHERE bucket < '2024-06-10 12:00'\n"
                     ")\n"
                     "SELECT h.bucket, s.sensor_code, r.watts,\n"
                     "       COALESCE(r.watts, (\n"
                     "         SELECT r2.watts FROM sensor_readings r2\n"
                     "         WHERE r2.sensor_code = s.sensor_code AND r2.bucket < h.bucket\n"
                     "         ORDER BY r2.bucket DESC LIMIT 1\n"
                     "       )) AS watts_efectivo,\n"
                     "       CASE WHEN r.watts IS NULL THEN 'hueco' ELSE 'ok' END AS estado\n"
                     "FROM hrs h\n"
                     "CROSS JOIN (SELECT DISTINCT sensor_code FROM sensor_readings) s\n"
                     "LEFT JOIN sensor_readings r ON r.sensor_code = s.sensor_code AND r.bucket = h.bucket\n"
                     "ORDER BY h.bucket, s.sensor_code;\n"
                     "```\n"
                     "Traza de los tres huecos: INV-B a las 09:00 hereda 3800 (su lectura de 08:00); INV-A a las 10:00 hereda 4350 (la de 09:00 — no la de 08:00, el ORDER BY DESC con LIMIT 1 garantiza la más reciente); INV-B a las 12:00 hereda 3700. El estado se calcula sobre el valor CRUDO, no sobre el efectivo, para que el dashboard pueda distinguir medición real de valor arrastrado. Para rangos largos, la subconsulta correlacionada convierte índices por (sensor_code, bucket); sin ese índice el forward fill es O(huecos × lecturas)."),
        ],
        verify=[
            {"name": "rejilla_con_relleno", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["2024-06-10 09:00|INV-B||3800|hueco",
                                        "2024-06-10 10:00|INV-A||4350|hueco",
                                        "2024-06-10 12:00|INV-B||3700|hueco",
                                        "2024-06-10 10:00|INV-B|3600|3600|ok"],
             "expect_stdout_not_contains": ["|0|hueco"]},
        ],
        tags=["sql", "gap-filling", "recursive-cte", "time-series", "iot"],
    ),
    # ---------------------------------------------------------------- D1 (hard)
    E(
        language="sql", domain="databases", subdomain="null_join_debug",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "La conciliación automática del banco marca un movimiento sin pareja, pero la línea correspondiente SÍ está en el extracto. Script de carga y consulta de cruce:\n"
                     "```sql\n"
                     "CREATE TABLE movs (\n"
                     "  mov_id INTEGER PRIMARY KEY,\n"
                     "  concept TEXT NOT NULL,\n"
                     "  ref TEXT\n"
                     ");\n"
                     "CREATE TABLE stmt_lines (\n"
                     "  line_id INTEGER PRIMARY KEY,\n"
                     "  ref TEXT,\n"
                     "  amount_cents INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO movs VALUES (1,'nomina','TRX-2024-001'),(2,'recibo luz','TRX-2024-002'),(3,'ingreso efectivo',NULL);\n"
                     "INSERT INTO stmt_lines VALUES (1,'TRX-2024-001',215000),(2,'TRX-2024-002',6420),(3,NULL,9000);\n"
                     "```\n"
                     "```sql\n"
                     "SELECT m.mov_id, m.concept, s.line_id, s.amount_cents\n"
                     "FROM movs m JOIN stmt_lines s ON s.ref = m.ref\n"
                     "ORDER BY m.mov_id;\n"
                     "```\n"
                     "La referencia NULL es el convenio del banco para operaciones en ventanilla: ambas partes la dejan a NULL y DEBEN cruzar entre sí."),
            ("assistant", "Síntoma: el movimiento 3 ('ingreso efectivo') no encuentra su pareja aunque stmt_lines tiene una línea con importe 9000 sin referencia. Hipótesis 1: las referencias a NULL no son realmente NULL (espacios, cadena vacía o tipo distinto tras la carga). Hipótesis 2: son NULL legítimos y el problema es semántico — el operador = nunca da TRUE cuando un operando es NULL (lógica trivalente), así que un JOIN por una columna anulable descarta esas filas en silencio. Experimento discriminante: clasificar cada referencia con IS NULL y typeof, y evaluar NULL = NULL explícitamente."),
            ("tool", "sqlite> SELECT mov_id, ref, typeof(ref), ref IS NULL AS es_null FROM movs ORDER BY mov_id;\n"
                     "1|TRX-2024-001|text|0\n"
                     "2|TRX-2024-002|text|0\n"
                     "3|ingreso efectivo|null|1\n"
                     "sqlite> SELECT NULL = NULL AS eq, NULL IS NULL AS is_op;\n"
                     "|1\n"
                     "sqlite> SELECT COUNT(*) FROM stmt_lines WHERE ref IS NULL;\n"
                     "1\n"
                     "sqlite> -- NULL = NULL evalúa a NULL (fila impresa vacía), no a 1: la igualdad SQL no cruza nulos"),
            ("assistant", "Refutada la hipótesis 1: typeof devuelve 'null' real, no texto vacío. Causa raíz (hipótesis 2): en SQL, NULL = NULL evalúa a UNKNOWN y el JOIN solo conserva filas con TRUE; por eso el cruce pierde exactamente las operaciones de ventanilla, y lo hace EN SILENCIO — el conteo total baja pero nadie lanza error. Corrección: SQLite ofrece el operador IS, equivalente a IS NOT DISTINCT FROM del estándar: TRUE si ambos son NULL o si ambos son iguales no nulos. Corrección aplicada:\n"
                     "```sql\n"
                     "SELECT m.mov_id, m.concept, s.line_id, s.amount_cents\n"
                     "FROM movs m JOIN stmt_lines s ON s.ref IS m.ref\n"
                     "ORDER BY m.mov_id;\n"
                     "```\n"
                     "Nueva ejecución: 3 filas, incluida 3|ingreso efectivo|3|9000. Dos advertencias de operación: (1) IS iguala TODOS los NULL entre sí — si en un mes hubiera dos operaciones de ventanilla, cruzarían entre sí en cruz múltiple; el convenio correcto sería cruzar además por importe o sustituir NULL por un token generado ('CASH-0001') en carga; (2) en otros motores, usa IS NOT DISTINCT FROM (PostgreSQL) o predicaos con COALESCE cuidadoso. Nunca «arregles» esto con WHERE ref IS NOT NULL: escondería el caso en vez de cruzarlo."),
        ],
        verify=[
            {"name": "bug_null_no_cruza", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["1|nomina|1|215000", "2|recibo luz|2|6420"],
             "expect_stdout_not_contains": ["3|ingreso efectivo|3|9000"]},
            {"name": "fix_is_null_safe", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["3|ingreso efectivo|3|9000", "1|nomina|1|215000"]},
        ],
        tags=["sql", "null-semantics", "joins", "debugging", "reconciliation"],
    ),
    # ---------------------------------------------------------------- D2 (hard)
    E(
        language="sql", domain="databases", subdomain="left_join_degradation",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "El informe «clientes con su facturación pagada» debe incluir a los clientes SIN pedidos con 0, pero desde que añadimos el filtro de estado desaparecen dos clientes. Esquema, datos y consulta problemática:\n"
                     "```sql\n"
                     "CREATE TABLE customers (\n"
                     "  customer_id INTEGER PRIMARY KEY,\n"
                     "  name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE orders (\n"
                     "  order_id INTEGER PRIMARY KEY,\n"
                     "  customer_id INTEGER NOT NULL REFERENCES customers(customer_id),\n"
                     "  status TEXT NOT NULL CHECK (status IN ('paid','pending','refunded')),\n"
                     "  total_cents INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO customers VALUES (1,'Ana Fuentes'),(2,'Bruno Silva'),(3,'Carla Duarte'),(4,'Diana Reyes');\n"
                     "INSERT INTO orders VALUES (100,1,'paid',12500),(101,1,'pending',3000),(102,2,'paid',45000),(103,2,'refunded',12000),(104,3,'pending',9900);\n"
                     "```\n"
                     "```sql\n"
                     "SELECT c.name, COUNT(o.order_id) AS pedidos, COALESCE(SUM(o.total_cents), 0) AS pagado\n"
                     "FROM customers c\n"
                     "LEFT JOIN orders o ON o.customer_id = c.customer_id\n"
                     "WHERE o.status = 'paid'\n"
                     "GROUP BY c.customer_id, c.name\n"
                     "ORDER BY c.name;\n"
                     "```\n"
                     "Esperado: Ana 1/12500, Bruno 1/45000, Carla 0/0 y Diana 0/0. Obtenido: solo Ana y Bruno."),
            ("assistant", "Síntoma: desaparecen Carla (solo pedidos pending) y Diana (sin pedidos). Hipótesis 1: el GROUP BY pierde grupos con agregados nulos. Hipótesis 2: el LEFT JOIN está bien pero el WHERE de la tabla derecha elimina las filas extendidas con NULL antes de agrupar — cada fila de Diana sale del LEFT JOIN con o.status NULL, y NULL = 'paid' es UNKNOWN, así que el WHERE la descarta: el LEFT JOIN queda degradado a INNER JOIN. Experimento: ejecutar el LEFT JOIN en crudo, sin WHERE ni agregación, y mirar qué filas llegan al filtro."),
            ("tool", "sqlite> SELECT c.name, o.order_id, o.status, o.total_cents\n"
                     "   ...> FROM customers c LEFT JOIN orders o ON o.customer_id = c.customer_id\n"
                     "   ...> ORDER BY c.name, o.order_id;\n"
                     "Ana Fuentes|100|paid|12500\n"
                     "Ana Fuentes|101|pending|3000\n"
                     "Bruno Silva|102|paid|45000\n"
                     "Bruno Silva|103|refunded|12000\n"
                     "Carla Duarte|104|pending|9900\n"
                     "Diana Reyes|||\n"
                     "sqlite> -- la fila de Diana SÍ existe tras el JOIN (order_id NULL): el WHERE la está matando"),
            ("assistant", "El experimento refuta la hipótesis 1 y confirma la 2: Diana llega al WHERE con o.status NULL y es descartada; Carla sobrevive al JOIN pero sus únicos pedidos son pending, así que también cae. Causa raíz: un predicado sobre columnas de la tabla DERECHA en el WHERE convierte cualquier LEFT JOIN en INNER JOIN, porque las filas extendidas tienen NULL en esas columnas y NULL = cualquiercosa es UNKNOWN. Corrección: el filtro pertenece a la lógica del JOIN, luego va en el ON:\n"
                     "```sql\n"
                     "SELECT c.name, COUNT(o.order_id) AS pedidos, COALESCE(SUM(o.total_cents), 0) AS pagado\n"
                     "FROM customers c\n"
                     "LEFT JOIN orders o\n"
                     "       ON o.customer_id = c.customer_id AND o.status = 'paid'\n"
                     "GROUP BY c.customer_id, c.name\n"
                     "ORDER BY c.name;\n"
                     "```\n"
                     "Nueva ejecución: Ana Fuentes|1|12500, Bruno Silva|1|45000, Carla Duarte|0|0, Diana Reyes|0|0. Observa que para Bruno el resultado no cambia (su único paid era 45000 y el refunded ya quedaba fuera por el ON). Regla mnemotécnica: condiciones de la tabla izquierda → WHERE; condiciones de la tabla derecha → ON. La variante WHERE (o.status = 'paid' OR o.order_id IS NULL) también funciona, pero duplica la lógica y es frágil ante refactorizaciones."),
        ],
        verify=[
            {"name": "bug_clientes_perdidos", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["Ana Fuentes|1|12500", "Bruno Silva|1|45000"],
             "expect_stdout_not_contains": ["Carla Duarte|0|0", "Diana Reyes|0|0"]},
            {"name": "fix_on_predicate", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["Ana Fuentes|1|12500", "Bruno Silva|1|45000",
                                        "Carla Duarte|0|0", "Diana Reyes|0|0"]},
        ],
        tags=["sql", "left-join", "where-predicate", "debugging"],
    ),
    # ---------------------------------------------------------------- D3 (hard)
    E(
        language="sql", domain="databases", subdomain="group_by_incomplete",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "El dashboard logístico de bultos por sucursal y mes muestra totales imposibles: enero sale inflado y febrero y marzo no existen. Tabla y consulta del dashboard:\n"
                     "```sql\n"
                     "CREATE TABLE shipments (\n"
                     "  ship_id INTEGER PRIMARY KEY,\n"
                     "  branch TEXT NOT NULL,\n"
                     "  month TEXT NOT NULL,\n"
                     "  boxes INTEGER NOT NULL\n"
                     ");\n"
                     "INSERT INTO shipments VALUES (1,'norte','2024-01',1500),(2,'norte','2024-02',1900),(3,'sur','2024-01',900),(4,'sur','2024-02',1100),(5,'sur','2024-03',700);\n"
                     "```\n"
                     "```sql\n"
                     "SELECT branch, SUM(boxes) AS bultos\n"
                     "FROM shipments\n"
                     "GROUP BY branch\n"
                     "ORDER BY branch;\n"
                     "```\n"
                     "Lo que devuelve: norte|3400 y sur|2700. Lo que debe devolver: cinco filas, una por sucursal y mes."),
            ("assistant", "Síntoma: dos filas cuando deberían ser cinco, y sumas que mezclan meses (norte 1500+1900 = 3400). Hipótesis 1: hay filas duplicadas en la tabla que inflan la suma. Experimento: contar líneas reales por (branch, month); si cada clave aparece una sola vez, la tabla está limpia y el defecto está en la consulta. Hipótesis 2 (alternativa): algún month está mal cargado. La misma sonda descarta ambas."),
            ("tool", "sqlite> SELECT branch, month, COUNT(*) AS lineas, SUM(boxes) AS bultos\n"
                     "   ...> FROM shipments GROUP BY branch, month ORDER BY branch, month;\n"
                     "norte|2024-01|1|1500\n"
                     "norte|2024-02|1|1900\n"
                     "sur|2024-01|1|900\n"
                     "sur|2024-02|1|1100\n"
                     "sur|2024-03|1|700\n"
                     "sqlite> -- 5 claves, 1 línea cada una: sin duplicados y con los meses bien cargados"),
            ("assistant", "La sonda refuta la hipótesis de datos: a nivel (branch, month) todo está correcto — de hecho esta misma consulta devuelve EXACTAMENTE lo que pide el informe. Causa raíz: la clave de agrupación del dashboard está incompleta; GROUP BY branch colapsa los meses dentro de cada sucursal y la suma se convierte en «bultos del trimestre por sucursal». Es el bug silencioso clásico: la consulta no falla, devuelve números plausibles y mal. Corrección: añadir month a la clave y al SELECT, ordenando por la clave completa:\n"
                     "```sql\n"
                     "SELECT branch, month, SUM(boxes) AS bultos\n"
                     "FROM shipments\n"
                     "GROUP BY branch, month\n"
                     "ORDER BY branch, month;\n"
                     "```\n"
                     "Nueva ejecución: cinco filas (norte|2024-01|1500 … sur|2024-03|700). Dos lecciones de blindaje: (1) en SQLite el modo estricto no te salva aquí, pero sí lo hará probar SIEMPRE el nº de filas esperado junto al valor; (2) si el motor lo soporta, activar ONLY_FULL_GROUP_BY (MySQL) evita además columnas sueltas no agrupadas; SQLite las tolera y devuelve valores arbitrarios — otro teléfono roto que veremos en otro ejemplo."),
        ],
        verify=[
            {"name": "bug_grupos_colapsados", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["norte|3400", "sur|2700"],
             "expect_stdout_not_contains": ["norte|2024-02|1900", "sur|2024-03|700"]},
            {"name": "fix_clave_completa", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["norte|2024-01|1500", "norte|2024-02|1900",
                                        "sur|2024-03|700"]},
        ],
        tags=["sql", "group-by", "aggregation", "debugging"],
    ),
    # ---------------------------------------------------------------- D4 (medium)
    E(
        language="sql", domain="databases", subdomain="count_nulls",
        difficulty="medium", task_type="debugging",
        messages=[
            ("user", "El informe de laboratorio dice que el paciente 2 tiene CERO pruebas cuando tiene tres (todas pendientes de resultado). Consulta del informe:\n"
                     "```sql\n"
                     "CREATE TABLE lab_tests (\n"
                     "  test_id INTEGER PRIMARY KEY,\n"
                     "  patient_id INTEGER NOT NULL,\n"
                     "  profile TEXT NOT NULL,\n"
                     "  result_value REAL\n"
                     ");\n"
                     "INSERT INTO lab_tests VALUES (101,1,'hemograma',7.2),(102,1,'glucosa',95.0),(103,1,'colesterol',180.0),(201,2,'hemograma',NULL),(202,2,'glucosa',NULL),(203,2,'perfil hepatico',NULL),(301,3,'hemograma',6.9),(302,3,'glucosa',NULL);\n"
                     "```\n"
                     "```sql\n"
                     "SELECT patient_id, COUNT(result_value) AS pruebas\n"
                     "FROM lab_tests\n"
                     "GROUP BY patient_id\n"
                     "ORDER BY patient_id;\n"
                     "```\n"
                     "Devuelve 1|3, 2|0, 3|1. Lo correcto es el nº TOTAL de pruebas por paciente, incluidas las pendientes."),
            ("assistant", "Síntoma: el paciente 2 aparece con 0 y el 3 con 1 — ambos infrarreportados. Hipótesis: COUNT(expr) cuenta filas donde expr NO es NULL, y result_value es precisamente lo que está pendiente; la métrica pedida es filas, no valores. Experimento barato y contundente: poner COUNT(*) y COUNT(result_value) lado a lado por paciente y ver la divergencia exacta."),
            ("tool", "sqlite> SELECT patient_id, COUNT(*) AS total, COUNT(result_value) AS con_resultado\n"
                     "   ...> FROM lab_tests GROUP BY patient_id ORDER BY patient_id;\n"
                     "1|3|3\n"
                     "2|3|0\n"
                     "3|2|1\n"
                     "sqlite> -- COUNT(*) cuenta filas; COUNT(col) salta los NULL de esa columna"),
            ("assistant", "El experimento confirma la hipótesis: el patient 2 tiene 3 filas y 0 valores; el 3, 2 filas y 1 valor. Causa raíz: semántica de COUNT con expresión — COUNT(result_value) es «pruebas CON resultado», una métrica legítima pero distinta de la pedida. Corrección: COUNT(*) para «pruebas totales»; y ya que estamos, dejo ambas métricas con nombres inequívocos para que el informe pueda mostrar las dos:\n"
                     "```sql\n"
                     "SELECT patient_id,\n"
                     "       COUNT(*) AS pruebas,\n"
                     "       COUNT(result_value) AS con_resultado,\n"
                     "       COUNT(*) - COUNT(result_value) AS pendientes\n"
                     "FROM lab_tests\n"
                     "GROUP BY patient_id\n"
                     "ORDER BY patient_id;\n"
                     "```\n"
                     "Nueva ejecución: 1|3|3|0, 2|3|0|3, 3|2|1|1. Ficha rápida de variantes para no volver a caer: COUNT(*) filas del grupo; COUNT(col) filas con col no nula; COUNT(DISTINCT col) valores distintos no nulos; y en SQLite 3.30+, COUNT(*) FILTER (WHERE cond) para métricas condicionales sin CASE."),
        ],
        verify=[
            {"name": "bug_subconteo", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["1|3", "2|0", "3|1"],
             "expect_stdout_not_contains": ["2|3", "3|2"]},
            {"name": "fix_count_star", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["1|3|3|0", "2|3|0|3", "3|2|1|1"]},
        ],
        tags=["sql", "count", "null", "aggregation", "debugging"],
    ),
    # ---------------------------------------------------------------- D5 (hard)
    E(
        language="sql", domain="databases", subdomain="fanout_aggregates",
        difficulty="hard", task_type="debugging", recovery=True,
        messages=[
            ("user", "Finanzas detecta que la recaudación por préstamos de la biblioteca sale por encima del total cobrado en caja. La consulta pasa por la tabla de autores porque el informe del próximo trimestre filtrará por autor:\n"
                     "```sql\n"
                     "CREATE TABLE loans (\n"
                     "  loan_id INTEGER PRIMARY KEY,\n"
                     "  book_id INTEGER NOT NULL,\n"
                     "  fee_cents INTEGER NOT NULL\n"
                     ");\n"
                     "CREATE TABLE authors (\n"
                     "  author_id INTEGER PRIMARY KEY,\n"
                     "  name TEXT NOT NULL\n"
                     ");\n"
                     "CREATE TABLE book_authors (\n"
                     "  book_id INTEGER NOT NULL,\n"
                     "  author_id INTEGER NOT NULL,\n"
                     "  PRIMARY KEY (book_id, author_id)\n"
                     ");\n"
                     "INSERT INTO authors VALUES (1,'G. Garcia Marquez'),(2,'A. Carbonell'),(3,'J. Cortazar');\n"
                     "INSERT INTO book_authors VALUES (1,1),(1,2),(2,3),(3,1);\n"
                     "INSERT INTO loans VALUES (1,1,12000),(2,2,8000),(3,3,6000);\n"
                     "```\n"
                     "```sql\n"
                     "SELECT COUNT(*) AS prestamos, SUM(l.fee_cents) AS ingresos\n"
                     "FROM loans l\n"
                     "JOIN book_authors ba ON ba.book_id = l.book_id;\n"
                     "```\n"
                     "Devuelve 4|38000, pero la caja cobró 3 préstamos y 26000 céntimos."),
            ("assistant", "Síntoma: +1 préstamo y +12000 céntimos sobre la realidad — exactamente la tarifa del préstamo del libro 1. Hipótesis 1: hay un préstamo duplicado en loans. Experimento: contar filas por loan_id. Hipótesis 2: el fan-out del join m:n — el libro 1 tiene DOS autores y cada préstamo se multiplica por autor en el JOIN. La segunda sonda lo demuestra: listar (loan_id, author_id) tras el join."),
            ("tool", "sqlite> SELECT loan_id, COUNT(*) AS n FROM loans GROUP BY loan_id;\n"
                     "1|1\n"
                     "2|1\n"
                     "3|1\n"
                     "sqlite> -- hipótesis 1 refutada: no hay duplicados en loans\n"
                     "sqlite> SELECT l.loan_id, ba.author_id, l.fee_cents FROM loans l JOIN book_authors ba ON ba.book_id = l.book_id ORDER BY l.loan_id, ba.author_id;\n"
                     "1|1|12000\n"
                     "1|2|12000\n"
                     "2|3|8000\n"
                     "3|1|6000\n"
                     "sqlite> -- el préstamo 1 aparece DOS veces (autores 1 y 2): fan-out m:n confirmado"),
            ("assistant", "Causa raíz: un JOIN contra la tabla puente book_authors multiplica cada préstamo por su nº de autores; SUM y COUNT(*) agregan filas, no entidades, así que el libro con dos autores paga doble. La consulta era «correcta» para el futuro filtro por autor (ahí el reparto por autor es legítimo), pero el TOTAL debe medir préstamos, no pares (préstamo, autor). Corrección: deduplicar la entidad préstamo antes de agregar — con DISTINCT sobre la clave natural del dinero (loan_id, fee_cents), o equivalentemente filtrando con EXISTS sin multiplicar:\n"
                     "```sql\n"
                     "SELECT COUNT(*) AS prestamos, SUM(fee_cents) AS ingresos\n"
                     "FROM (\n"
                     "  SELECT DISTINCT l.loan_id, l.fee_cents\n"
                     "  FROM loans l\n"
                     "  JOIN book_authors ba ON ba.book_id = l.book_id\n"
                     ") t;\n"
                     "```\n"
                     "Nueva ejecución: 3|26000, cuadrado con caja. Nota de diseño: DISTINCT aquí es seguro SOLO porque (loan_id, fee_cents) identifica la fila monetaria; si la tarifa pudiera diferir por fila duplicada, el patrón correcto es agregar los autores primero (subconsulta GROUP BY book_id) o usar EXISTS, que comprueba existencia sin multiplicar filas. Y para el informe por autor, el reparto 12000/2 = 6000 por autor es una DECISIÓN de negocio: documéntala; no la decida el JOIN por accidente."),
        ],
        verify=[
            {"name": "bug_fanout", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["4|38000"],
             "expect_stdout_not_contains": ["3|26000"]},
            {"name": "fix_dedup_antes_agregar", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["3|26000"],
             "expect_stdout_not_contains": ["38000"]},
        ],
        tags=["sql", "many-to-many", "fan-out", "debugging", "aggregation"],
    ),
]
