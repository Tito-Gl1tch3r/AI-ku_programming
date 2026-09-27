"""
m_php_java.py — Módulo PHP 8.x / Java 17-21 del dataset AI-ku_programming (Stack V2).

36 ejemplos (18 PHP + 18 Java) de backend real:
  * PHP: PDO con prepared statements y transacciones, API REST con códigos HTTP
    correctos (400/404/405/422), sesiones seguras (regeneración de ID, cookies
    httponly/samesite), OOP (interfaces, traits, PSR-4 con Composer, DI),
    debugging de coerciones (== suelto, array_search falsy, notices de PHP 8,
    headers already sent), rendimiento (N+1, caché idempotente, keyset).
  * Java: Streams/Collectors, Optional bien usado, ExecutorService con shutdown
    correcto, ConcurrentHashMap + LongAdder, CompletableFuture con timeout y
    composición, HttpClient contra servidor local, Files.walk, records + sealed
    + pattern matching, contrato equals/hashCode, excepciones suprimidas,
    autoboxing, comparadores consistentes.

Distribución: 14 implementation, 10 debugging, 4 code_review, 4 refactoring,
2 testing, 1 optimization, 1 architecture. Dificultad: 2 medium, 16 hard,
18 very_hard. Nota de verificación honesta: los pasos syntax (php -l) y
compile_run (javac/java) quedan NO EJECUTADO en el entorno de construcción
(no hay toolchain); los pasos sql sí se ejecutan de verdad contra SQLite.
"""

from schema import E

EXAMPLES = [
    # ==================================================================
    # PHP (18)
    # ==================================================================

    # PHP 1 — PDO: prepared statements + transaccion atomica de transferencias
    E(
        language="php",
        domain="backend",
        subdomain="pdo_transacciones",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r'''Necesitamos endurecer el servicio de transferencias del panel de pagos (PHP 8.2, PDO sobre MySQL). El código actual es este:

```php
<?php
function transferir(PDO $pdo, int $origen, int $destino, float $importe): bool {
    $pdo->exec("UPDATE cuentas SET saldo = saldo - {$importe} WHERE id = {$origen}");
    $pdo->exec("UPDATE cuentas SET saldo = saldo + {$importe} WHERE id = {$destino}");
    return true;
}
```

Problemas observados en producción: un error a mitad de proceso dejaba el dinero descontado sin abonar, y auditoría marcó las consultas por interpolación de valores. Requisitos: atomicidad (todo o nada), saldo nunca negativo, importes en céntimos (enteros) y que una cuenta destino inexistente no «pierda» el dinero. Implementa la clase TransferService y justifica cada decisión.'''),
            ("assistant", r'''Decisiones de diseño, una por requisito:

1. **Atomicidad**: `beginTransaction()` + `commit()`/`rollBack()`. Si el abono falla, el débito no puede sobrevivir.
2. **Saldo nunca negativo**: `CHECK (saldo_cents >= 0)` en la BD como última línea de defensa, más comprobación previa bajo `SELECT ... FOR UPDATE` para que dos transferencias concurrentes no lean el mismo saldo (lost update).
3. **Importes en céntimos (int)**: en coma flotante `0.1 + 0.2 !== 0.3`; con dinero no se negocia.
4. **Prepared statements**: los valores nunca se interpolan; cada identificador e importe viaja como parámetro.
5. **rowCount()**: un UPDATE sobre cuenta inexistente afecta a 0 filas; sin ese chequeo, el débito se aplica y el abono «desaparece».

```php
<?php
declare(strict_types=1);

final class TransferService
{
    public function __construct(private PDO $pdo) {}

    /** @throws DomainException datos invalidos | RuntimeException fallo de BD */
    public function transfer(int $fromId, int $toId, int $amountCents): void
    {
        if ($fromId === $toId) {
            throw new DomainException('origen y destino coinciden');
        }
        if ($amountCents <= 0) {
            throw new DomainException('importe invalido');
        }

        $this->pdo->beginTransaction();
        try {
            $lock = $this->pdo->prepare('SELECT saldo_cents FROM cuentas WHERE id = ? FOR UPDATE');
            $lock->execute([$fromId]);
            $saldo = $lock->fetchColumn();
            if ($saldo === false) {
                throw new DomainException('cuenta origen inexistente');
            }
            if ((int) $saldo < $amountCents) {
                throw new DomainException('saldo insuficiente');
            }

            $debit = $this->pdo->prepare('UPDATE cuentas SET saldo_cents = saldo_cents - ? WHERE id = ?');
            $debit->execute([$amountCents, $fromId]);
            if ($debit->rowCount() !== 1) {
                throw new RuntimeException('debito no aplicado');
            }

            $credit = $this->pdo->prepare('UPDATE cuentas SET saldo_cents = saldo_cents + ? WHERE id = ?');
            $credit->execute([$amountCents, $toId]);
            if ($credit->rowCount() !== 1) {
                throw new DomainException('cuenta destino inexistente');
            }

            $this->pdo->commit();
        } catch (Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
    }
}
```

Notas: `FOR UPDATE` es sintaxis de MySQL/PostgreSQL para bloquear la fila leída; SQLite no lo soporta y en ese motor basta el aislamiento del archivo para el caso de prueba. Cómo comprobarlo: `php -l src/TransferService.php` debe devolver «No syntax errors detected», y la semántica transaccional se verifica con la misma secuencia SQL que ejecuta el servicio (arriba está reproducida para el harness):

```sql
CREATE TABLE cuentas (
  id INTEGER PRIMARY KEY,
  titular TEXT NOT NULL,
  saldo_cents INTEGER NOT NULL DEFAULT 0 CHECK (saldo_cents >= 0)
);
INSERT INTO cuentas (id, titular, saldo_cents) VALUES (1, 'acme_ltd', 100000), (2, 'beta_srl', 25000);
BEGIN;
UPDATE cuentas SET saldo_cents = saldo_cents - 15000 WHERE id = 1;
UPDATE cuentas SET saldo_cents = saldo_cents + 15000 WHERE id = 2;
COMMIT;
SELECT id, titular, printf('%.2f', saldo_cents / 100.0) AS saldo FROM cuentas ORDER BY id;
```

Si el débito violara el CHECK (sobregiro), la sentencia falla, el catch hace rollBack() y ninguna operación queda aplicada: ese es el invariante que pide el negocio.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
            {"name": "sql_transaccion_atomica", "action": "sql", "lang": "sql", "msg": -1, "block": 1,
             "expect_stdout_contains": ["1|acme_ltd|850.00", "2|beta_srl|400.00"]},
        ],
        tags=["php", "pdo", "prepared-statements", "transacciones", "dinero"],
        stack=["php", "sql"],
        recovery=False,
    ),

    # PHP 2 — API REST: json_response, codigos HTTP y validacion 422
    E(
        language="php",
        domain="security",
        subdomain="api_rest_validacion",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r'''Endpoint del panel logístico: POST /api/ordenes. El controlador actual falla de formas distintas según el cliente y a veces escupe avisos de PHP dentro del JSON:

```php
<?php
$data = json_decode(file_get_contents('php://input'));
if ($data->cantidad > 0) {   // aviso si falta el campo, y "9" pasa como numero
    echo json_encode(['ok' => true]);
}
```

Requisitos del equipo de integraciones: respuestas JSON consistentes (siempre objeto con error o datos), 400 para JSON malformado, 405 para métodos no permitidos, 422 con detalle de validación, 201 al crear, y nunca filtrar avisos/trazas en el cuerpo. sku con formato ABC-1234, cantidad entero 1..1000, idempotency_key cadena de 16 a 64 caracteres.'''),
            ("assistant", r'''Principio: un único punto de salida `json_response(int $status, array $payload)` que fija código, cabeceras y corta la ejecución; la validación es estricta (JSON ya tipa los valores, así que exigimos `is_int`, no coerciones).

```php
<?php
declare(strict_types=1);

function json_response(int $status, array $payload): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    exit;
}

function validate_order(array $in): array
{
    $errors = [];
    $sku = $in['sku'] ?? null;
    if (!is_string($sku) || preg_match('/^[A-Z]{3}-[0-9]{4}$/', $sku) !== 1) {
        $errors['sku'] = 'formato esperado ABC-1234';
    }
    $qty = $in['cantidad'] ?? null;
    if (!is_int($qty) || $qty < 1 || $qty > 1000) {
        $errors['cantidad'] = 'entero entre 1 y 1000';
    }
    $key = $in['idempotency_key'] ?? null;
    if (!is_string($key) || mb_strlen($key) < 16 || mb_strlen($key) > 64) {
        $errors['idempotency_key'] = 'cadena de 16 a 64 caracteres';
    }
    return $errors;
}

$method = $_SERVER['REQUEST_METHOD'] ?? '';
if ($method !== 'POST') {
    header('Allow: POST');
    json_response(405, ['error' => 'metodo no permitido']);
}

$raw = file_get_contents('php://input');
try {
    $body = json_decode($raw !== false ? $raw : '', true, 512, JSON_THROW_ON_ERROR);
} catch (JsonException) {
    json_response(400, ['error' => 'json malformado']);
}
if (!is_array($body)) {
    json_response(400, ['error' => 'el cuerpo debe ser un objeto json']);
}

$errors = validate_order($body);
if ($errors !== []) {
    json_response(422, ['error' => 'validacion fallida', 'details' => $errors]);
}

json_response(201, ['status' => 'aceptada', 'sku' => $body['sku']]);
```

Decisiones que conviene poder defender en revisión:

- 400 vs 422: 400 es «no entiendo tu sintaxis» (JSON roto); 422 es «entiendo, pero no cumple el contrato». Agrupar todos los errores de validación en `details` evita el ping-pong de un error por petición.
- `catch (JsonException)` sin variable: no usamos la excepción, solo el tipo.
- `is_int($qty)`: con JSON, `"2"` y `2.5` llegan como string/float; aceptar coerciones aquí es la puerta a pedidos de 2.5 unidades.
- Además del controlador, en el bootstrap: `set_exception_handler(fn () => json_response(500, ['error' => 'error interno']))` tras registrar la traza en el log — el cliente nunca ve trazas.
- `display_errors=0` y `log_errors=1` en producción; con `display_errors=1` cualquier aviso contamina el JSON (el bug original).

Cómo comprobarlo (curl y códigos esperados):

```bash
# contrato de la API, cada codigo con su causa:
curl -i -X GET  http://localhost/api/ordenes                # 405 + cabecera Allow: POST
curl -i -X POST http://localhost/api/ordenes -d '{mal'      # 400 json malformado
curl -i -X POST http://localhost/api/ordenes -d '{"sku":"X","cantidad":1,"idempotency_key":"corta"}'                  # 422 con details
curl -i -X POST http://localhost/api/ordenes -d '{"sku":"ABC-1234","cantidad":2,"idempotency_key":"0123456789abcdef"}' # 201
```'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "api-rest", "validacion", "codigos-http", "json"],
        stack=["php"],
        recovery=False,
    ),

    # PHP 3 — Sesiones seguras: fijacion de sesion, cookies y rehash
    E(
        language="php",
        domain="security",
        subdomain="sesion_fijacion",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r'''El informe del pentest del panel administrativo marca dos hallazgos: fijación de sesión (el ID de sesión no cambia al autenticar) y cookies de sesión sin flags. Código actual:

```php
<?php
session_start();
if ($_POST['user'] === 'admin' && $_POST['pass'] === 'clave-del-demo') {
    $_SESSION['user'] = $_POST['user'];
}
```

Nos piden: cookies con httponly/samesite (secure en producción), regeneración del ID al elevar privilegios, verificación con password_hash/password_verify sin filtrar usuarios existentes por tiempo de respuesta, y expiración por inactividad. PHP 8.2.'''),
            ("assistant", r'''Tres piezas: configuración de cookie ANTES de `session_start()`, login que regenera el ID justo cuando sube el privilegio, y un guardián de sesión con expiración y rotación periódica.

```php
<?php
declare(strict_types=1);

session_set_cookie_params([
    'lifetime' => 0,
    'path' => '/',
    'domain' => '',
    'secure' => true,      // solo via HTTPS en produccion
    'httponly' => true,    // inaccesible desde JavaScript
    'samesite' => 'Lax',   // mitiga CSRF basico en navegadores modernos
]);
session_start();

function login(PDO $pdo, string $user, string $pass): bool
{
    $stmt = $pdo->prepare('SELECT id, password_hash FROM usuarios WHERE nombre = ?');
    $stmt->execute([$user]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!is_array($row)) {
        static $dummy = null;
        $dummy ??= password_hash('usuario-fantasma', PASSWORD_BCRYPT);
        password_verify($pass, $dummy);          // mismo coste CPU: no se filtra por timing
        return false;
    }
    if (!password_verify($pass, (string) $row['password_hash'])) {
        return false;
    }
    if (password_needs_rehash((string) $row['password_hash'], PASSWORD_DEFAULT)) {
        $up = $pdo->prepare('UPDATE usuarios SET password_hash = ? WHERE id = ?');
        $up->execute([password_hash($pass, PASSWORD_DEFAULT), (int) $row['id']]);
    }

    session_regenerate_id(true);                 // nuevo ID; el antiguo se invalida en el servidor
    $_SESSION['uid'] = (int) $row['id'];
    $_SESSION['last_seen'] = time();
    $_SESSION['last_regen'] = time();
    return true;
}

function require_login(): void
{
    if (empty($_SESSION['uid'])) {
        header('Location: /login.php', true, 302);
        exit;
    }
    $ahora = time();
    if ($ahora - (int) ($_SESSION['last_seen'] ?? 0) > 900) {      // 15 min inactivo
        $_SESSION = [];
        session_destroy();
        header('Location: /login.php?motivo=caducada', true, 302);
        exit;
    }
    if ($ahora - (int) ($_SESSION['last_regen'] ?? 0) > 300) {    // rotar ID cada 5 min
        session_regenerate_id(true);
        $_SESSION['last_regen'] = $ahora;
    }
    $_SESSION['last_seen'] = $ahora;
}
```

Por qué cada pieza:

- **Fijación de sesión**: el atacante consigue que la víctima use un ID conocido (enlace, XSS persistente, red compartida); si al autenticar no se regenera, el ID pre-autenticación ya es válido post-autenticación. `session_regenerate_id(true)` debe ejecutarse EXACTAMENTE al elevar privilegios, no en cualquier página.
- **Hash señuela**: si el usuario no existe, verificar contra un bcrypt real cuesta lo mismo que el camino feliz; sin eso, el tiempo de respuesta delata cuentas existentes (enumeración de usuarios).
- **password_needs_rehash**: cuando el algoritmo por defecto del servidor suba de versión, la migración ocurre en el siguiente login correcto, sin reset masivo.
- **Rotación periódica (5 min)**: acorta la ventana si el ID se filtró sin regenerar.
- `$_SESSION = []` antes de `session_destroy()` y cookie de sesión sin `Expires` (lifetime 0): muere al cerrar el navegador.

Cómo comprobarlo: con `curl -i` sobre el formulario, el `Set-Cookie: PHPSESSID=...` de la respuesta al login debe ser DISTINTO del recibido al pedir el formulario, y llevar `HttpOnly; SameSite=Lax; Secure`.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "sesiones", "session-fixation", "password-hash", "cookies"],
        stack=["php"],
        recovery=False,
    ),

    # PHP 4 — OOP: interfaces, trait, PSR-4 con Composer y DI minima
    E(
        language="php",
        domain="architecture",
        subdomain="psr4_di",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r'''El panel de facturación creció como una red de `require '../../.../Cosa.php'` frágiles y `new StripeGateway()` clavados en quince sitios, imposible de probar sin red. Se pide: autoload PSR-4 con Composer, interfaz PaymentGateway, un trait de auditoría reutilizable, servicio de checkout con inyección de dependencias y un contenedor mínimo de factorías. PHP 8.2, sin frameworks.'''),
            ("assistant", r'''Estructura objetivo: `src/` con una clase por fichero (aquí van juntas para leerlas de un vistazo), `composer dump-autoload`, y en el front controller un solo `require vendor/autoload.php`.

```php
<?php
declare(strict_types=1);

namespace Acme\Billing;

interface PaymentGateway
{
    public function charge(int $amountCents, string $reference): string;
}

trait AuditTrail
{
    /** @var list<string> */
    private array $audit = [];

    protected function audit(string $event): void
    {
        $this->audit[] = $event;
    }

    /** @return list<string> */
    public function auditTrail(): array
    {
        return $this->audit;
    }
}

final class SandboxGateway implements PaymentGateway
{
    use AuditTrail;

    public function charge(int $amountCents, string $reference): string
    {
        $this->audit("charge {$reference} {$amountCents}");
        return 'sbx_' . substr(hash('sha256', $reference . '|' . $amountCents), 0, 12);
    }
}

final class CheckoutService
{
    public function __construct(private PaymentGateway $gateway) {}

    public function checkout(string $reference, int $amountCents): string
    {
        if ($amountCents <= 0) {
            throw new InvalidArgumentException('importe invalido');
        }
        return $this->gateway->charge($amountCents, $reference);
    }
}

final class Container
{
    /** @var array<string, callable> */
    private array $factories = [];
    /** @var array<string, object> */
    private array $instances = [];

    public function set(string $id, callable $factory): void
    {
        $this->factories[$id] = $factory;
    }

    public function get(string $id): object
    {
        if (!isset($this->instances[$id])) {
            $this->instances[$id] = ($this->factories[$id])($this);
        }
        return $this->instances[$id];
    }
}

// Cableado unico en el front controller:
$c = new Container();
$c->set(PaymentGateway::class, fn () => new SandboxGateway());
$c->set(CheckoutService::class, fn (Container $c) => new CheckoutService($c->get(PaymentGateway::class)));

$checkout = $c->get(CheckoutService::class);
var_dump($checkout->checkout('ORD-2024-0042', 2500));
var_dump($c->get(PaymentGateway::class)->auditTrail());
```

Y el `composer.json` que alimenta el autoloader:

```json
{
    "autoload": {
        "psr-4": {
            "Acme\\Billing\\": "src/"
        }
    },
    "require": {
        "php": ">=8.1"
    }
}
```

Cómo funciona PSR-4 y por qué elimina los require: el prefijo `Acme\\Billing\\` se mapea a `src/`; `Acme\Billing\CheckoutService` se busca en `src/CheckoutService.php` (una clase por fichero, nombre exacto). Tras `composer dump-autoload`, `require vendor/autoload.php` en el punto de entrada basta. En pruebas: `$c->set(PaymentGateway::class, fn () => new FakeGatewayQueDevuelveError())` y el CheckoutService se prueba sin red — esa es la diferencia entre inyección y `new` clavado.

Interfaz vs trait: la interfaz define el CONTRATO (qué puede hacer el consumidor sin saber quién lo implementa); el trait reutiliza IMPLEMENTACIÓN horizontal (la auditoría) sin forzar una jerarquía de herencia. Un trait no sustituye a la interfaz: SandboxGateway firma el contrato Y recibe el comportamiento común por composición vertical de código.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "oop", "psr-4", "composer", "inyeccion-dependencias", "traits"],
        stack=["php"],
        recovery=False,
    ),

    # PHP 5 — Cache de archivo idempotente (anti-stampede con flock)
    E(
        language="php",
        domain="backend",
        subdomain="cache_archivo",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r'''El dashboard del CRM ejecuta un informe que tarda 2.5 s en MySQL y lo recalcula en cada petición; con 40 usuarios en hora punta el servidor se funde. Restricciones: sin Redis ni APCu en este despliegue (hosting compartido), y NO puede pasar que una ráfaga de peticiones simultáneas dispare el mismo informe N veces (stampede). PHP 8.2. Implementa una cache de archivo con `remember()` idempotente.'''),
            ("assistant", r'''La clave del requisito anti-stampede: antes de computar, tomar un lock exclusivo sobre el fichero de la clave; quien gana el lock RELEE la cache (por si alguien ya computó) y solo el ganador ejecuta el cálculo. Los perdedores esperan el lock y releen el resultado ya fresco.

```php
<?php
declare(strict_types=1);

final class FileCache
{
    public function __construct(private string $dir, private int $ttlSeconds = 300)
    {
        if (!is_dir($dir) && !mkdir($dir, 0770, true) && !is_dir($dir)) {
            throw new RuntimeException('no se pudo crear el directorio de cache');
        }
    }

    private function path(string $key): string
    {
        // la clave puede venir de parametros de usuario: nunca al nombre del fichero directo
        return $this->dir . '/' . hash('sha256', $key) . '.cache';
    }

    /** @return array{0: bool, 1: mixed} [hubo_hit, valor] */
    public function get(string $key): array
    {
        $raw = @file_get_contents($this->path($key));
        if ($raw === false) {
            return [false, null];
        }
        $entry = unserialize($raw, ['allowed_classes' => false]);
        if (!is_array($entry) || !isset($entry['expires_at'], $entry['value'])) {
            return [false, null];
        }
        if ($entry['expires_at'] < time()) {
            return [false, null];
        }
        return [true, $entry['value']];
    }

    public function set(string $key, mixed $value): void
    {
        file_put_contents(
            $this->path($key),
            serialize(['expires_at' => time() + $this->ttlSeconds, 'value' => $value]),
            LOCK_EX
        );
    }

    /** Idempotente bajo concurrencia: el informe se computa una sola vez por ventana TTL. */
    public function remember(string $key, callable $compute): mixed
    {
        [$hit, $value] = $this->get($key);
        if ($hit) {
            return $value;
        }
        $fh = fopen($this->path($key) . '.lock', 'c');
        if ($fh === false || !flock($fh, LOCK_EX)) {
            if (is_resource($fh)) {
                fclose($fh);
            }
            return $compute();                       // degradacion elegante sin lock
        }
        try {
            [$hit, $value] = $this->get($key);       // doble lectura: otro pudo computar ya
            if ($hit) {
                return $value;
            }
            $value = $compute();
            $this->set($key, $value);
            return $value;
        } finally {
            flock($fh, LOCK_UN);
            fclose($fh);
        }
    }
}

// Uso en el dashboard:
// $cache = new FileCache(sys_get_temp_dir() . '/crm-cache', 600);
// $informe = $cache->remember('informe-ventas:2024-05', fn () => $informes->ventasMensuales('2024-05'));
```

Decisiones defendibles:

- La clave se hashea a nombre de fichero: parámetros de usuario jamás tocan el filesystem directamente (traversal).
- `unserialize(..., ['allowed_classes' => false])`: deserializar datos que otros puedan escribir sin esa opción es RCE clásico. Para valores que no sean escalables, mejor JSON.
- La doble lectura dentro del lock es la que da la idempotencia: el segundo request de la ráfaga no re-computa, encuentra el valor escrito por el primero.
- `time()` para TTL está bien aquí; para testear la caducidad sin dormir, inyecta un reloj (`fn (): int => ...`) en el constructor.
- Si el lock falla (filesystem raro), degradamos a computar: peor rendimiento, nunca incorrectitud.

Cómo comprobarlo: `php -l` sobre el fichero; y en entorno con PHP-CLI, dos procesos paralelos (`php informe.php & php informe.php &`) contra un `$compute` que loguea: el log debe mostrar UNA ejecución y DOS lecturas de cache.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "cache", "flock", "idempotencia", "rendimiento"],
        stack=["php"],
        recovery=True,
    ),

    # PHP 6 — Export CSV streaming con generadores (sin OOM)
    E(
        language="php",
        domain="backend",
        subdomain="export_csv_generadores",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r'''La exportación de pedidos a CSV del panel B2B tira el proceso: `fetchAll()` de 2 millones de filas consume 1.8 GB y PHP alcanza memory_limit. Código actual:

```php
<?php
$rows = $pdo->query('SELECT id, cliente_id, total_cents, creado_en FROM pedidos')->fetchAll(PDO::FETCH_ASSOC);
$out = fopen('php://output', 'w');
fputcsv($out, ['id', 'cliente_id', 'total_eur', 'creado_en']);
foreach ($rows as $r) {
    fputcsv($out, [$r['id'], $r['cliente_id'], number_format($r['total_cents'] / 100, 2, '.', ''), $r['creado_en']]);
}
```

Se pide streaming con memoria acotada, sin depender de un `LIMIT/OFFSET` que se degrada, y con cabeceras HTTP correctas para descarga.'''),
            ("assistant", r'''Dos ideas combinadas: un GENERADOR que recorre la tabla por keyset (`WHERE id > :ultimo ORDER BY id LIMIT n`) manteniendo en memoria solo un chunk, y `fputcsv` escribiendo directo a `php://output` mientras el buffer va al cliente.

```php
<?php
declare(strict_types=1);

/** Recorre pedidos por keyset: memoria O(chunk), coste O(total) sin degradacion. */
function iter_pedidos(PDO $pdo, int $chunk = 5000): Generator
{
    $chunk = max(100, min($chunk, 50000));
    $stmt = $pdo->prepare(
        'SELECT id, cliente_id, total_cents, creado_en
           FROM pedidos
          WHERE id > ?
          ORDER BY id
          LIMIT ' . $chunk              // entero ya acotado por el clamp de arriba
    );
    $lastId = 0;
    while (true) {
        $stmt->execute([$lastId]);
        $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
        if ($rows === []) {
            return;
        }
        foreach ($rows as $row) {
            yield $row;
        }
        $lastId = (int) $row['id'];      // $row sigue en scope tras el foreach
        $stmt->closeCursor();
    }
}

function stream_csv(PDO $pdo): void
{
    while (ob_get_level() > 0) {
        ob_end_flush();                  // no buffers entre PHP y el cliente: streaming real
    }
    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename="pedidos.csv"');
    header('X-Accel-Buffering: no');     // desactiva buffering del proxy si hay nginx

    $out = fopen('php://output', 'w');
    if ($out === false) {
        throw new RuntimeException('salida no disponible');
    }
    fputcsv($out, ['id', 'cliente_id', 'total_eur', 'creado_en']);
    foreach (iter_pedidos($pdo) as $p) {
        fputcsv($out, [
            $p['id'],
            $p['cliente_id'],
            number_format(((int) $p['total_cents']) / 100, 2, '.', ''),
            $p['creado_en'],
        ]);
    }
    fclose($out);
}
```

Puntos de ingeniería:

- **Por qué keyset y no OFFSET**: `LIMIT 5000 OFFSET 1900000` obliga al motor a recorrer y DESCARTAR 1.9 M de filas en cada página; el coste crece linealmente con la profundidad. `WHERE id > :ultimo` usa el índice PK y cuesta lo mismo en la página 1 que en la 400.
- **Por qué generador y no fetch() incremental en el mismo loop**: el generador separa el recorrido del formato; se reutiliza para JSON-Lines, para migraciones, o para contar sin materializar. Además `yield` empuja fila a fila sin acumular.
- **LIMIT interpolado pero seguro**: LIMIT no acepta placeholder en muchos drivers; el valor es un entero acotado por `min/max` antes de llegar a la cadena. Ese es el único literal permitido.
- En PHP ≥ 8.4 conviene pasar `escape: ''` explícito en fputcsv para el modo RFC 4180 (el escape propietario está en vías de deprecación); en 8.1–8.3 el comportamiento por defecto es estable.
- Si el proceso muere a mitad, el cliente recibe CSV truncado: para exportaciones críticas, escribir a fichero temporal + servir al completar, o soportar reanudación por `Range`.

Cómo comprobarlo: `php -l`; y con una tabla de prueba, `php export.php | wc -l` debe dar filas+1 (cabecera) con `memory_get_peak_usage()` constante al crecer el tamaño de la tabla.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "generadores", "streaming", "csv", "paginacion-keyset"],
        stack=["php"],
        recovery=False,
    ),

    # PHP 7 — Pipeline de middlewares sin framework
    E(
        language="php",
        domain="architecture",
        subdomain="pipeline_middlewares",
        difficulty="medium",
        task_type="architecture",
        messages=[
            ("user", r'''Nuestro backend sin framework repite en cada controlador: comprobar token, loguear petición, medir tiempos. Se propone un pipeline de middlewares componibles. Restricciones: sin dependencias externas (ni PSR-15 completo), tipos estrictos, y el middleware de auth debe poder cortocircuitar la petición con 401 sin tocar el handler. Muestra cómo se compone y en qué orden se ejecuta.'''),
            ("assistant", r'''Un pipeline es un plegado a la derecha: partimos del handler final y envolvemos con cada middleware en orden inverso, así el PRIMERO de la lista es el más externo (el que ve la petición antes).

```php
<?php
declare(strict_types=1);

final class Pipeline
{
    /** @param list<callable(callable): callable> $middlewares */
    public function __construct(private array $middlewares) {}

    /** @return array{0: int, 1: array<string, mixed>, 2: array<string, mixed>} */
    public function handle(array $request, callable $handler): array
    {
        $next = array_reduce(
            array_reverse($this->middlewares),
            fn (callable $inner, callable $mw): callable => $mw($inner),
            fn (array $req): array => $handler($req)
        );
        return $next($request);
    }
}

function logging_middleware(callable $next): callable
{
    return function (array $req) use ($next): array {
        [$status, $body, $ctx] = $next($req);
        error_log(sprintf('%s %s -> %d', $req['method'] ?? 'GET', $req['path'] ?? '/', $status));
        return [$status, $body, $ctx];
    };
}

function auth_middleware(callable $next): callable
{
    return function (array $req) use ($next): array {
        $token = $req['headers']['authorization'] ?? '';
        if (!str_starts_with($token, 'Bearer ')) {
            return [401, ['error' => 'token ausente'], []];   // cortocircuito: no llama a $next
        }
        return $next([...$req, 'user_id' => extraer_uid($token)]);
    };
}

function extraer_uid(string $token): int
{
    return 42;   // en real: verificar firma JWT/HMAC contra el secreto del servidor
}

$handler = fn (array $req): array => [200, ['hola' => $req['user_id'] ?? 'anon'], []];
$pipeline = new Pipeline([logging_middleware(...), auth_middleware(...)]);

print_r($pipeline->handle(['method' => 'GET', 'path' => '/panel', 'headers' => ['authorization' => 'Bearer xyz']], $handler));
print_r($pipeline->handle(['method' => 'GET', 'path' => '/panel', 'headers' => []], $handler));
```

Puntos clave:

- `logging_middleware(...)` es la sintaxis de callable de primera clase (PHP 8.1): pasa la función como valor sin crear closures manuales.
- Orden de ejecución con `[logging, auth]`: logging → auth → handler. Si quisieras loguear TAMBIÉN los 401 de auth, logging debe ser el más externo — y lo es. El orden de la lista es una decisión de arquitectura, no un detalle.
- El contrato `[status, body, ctx]` es la versión minimalista de una Response; si el proyecto crece, es el momento natural de adoptar PSR-7/PSR-15 en vez de inventar más.
- El cortocircuito es simplemente «devolver sin llamar a $next»: cero magia, trivial de testear.
- Para medir tiempos añade un `timer_middleware` que capture `hrtime()` antes y después de `$next($req)`; colócalo el primero (externo) para que incluya auth y handler.

Cómo comprobarlo: `php -l`; ejecutando el script de demo, la primera petición imprime 200 con `user_id=42` y la segunda un 401, y el error_log recibe las dos líneas con sus códigos.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "middlewares", "arquitectura", "pipeline", "psr-15"],
        stack=["php"],
        recovery=False,
    ),

    # PHP 8 — Debugging: N+1 de consultas en el panel de reporting
    E(
        language="php",
        domain="backend",
        subdomain="n_plus_one",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", r'''El panel de reporting tarda ~9 s y el DBA dice que no es problema de servidor. Código del endpoint de facturación por cliente:

```php
<?php
$clientes = $pdo->query('SELECT id, nombre FROM clientes')->fetchAll(PDO::FETCH_ASSOC);
$total = 0.0;
foreach ($clientes as $c) {
    $st = $pdo->prepare('SELECT COALESCE(SUM(total_cents), 0) FROM pedidos WHERE cliente_id = ?');
    $st->execute([$c['id']]);
    $c['facturado'] = ((int) $st->fetchColumn()) / 100;
    $total += $c['facturado'];
}
```

Hay índice en pedidos.cliente_id (lo verificamos), así que mi primera intuición era de índices y no encaja. El log de consultas de una petición está en la consola.'''),
            ("tool", r'''Transcripción de referencia del log de la aplicación (una petición al endpoint):

```
[2024-05-12 09:14:02] app.INFO: SQL "SELECT id, nombre FROM clientes" dur=2.1ms
[2024-05-12 09:14:02] app.INFO: SQL "SELECT COALESCE(SUM(total_cents), 0) FROM pedidos WHERE cliente_id = ?" dur=1.8ms
[2024-05-12 09:14:02] app.INFO: SQL "SELECT COALESCE(SUM(total_cents), 0) FROM pedidos WHERE cliente_id = ?" dur=1.6ms
[2024-05-12 09:14:02] app.INFO: SQL "SELECT COALESCE(SUM(total_cents), 0) FROM pedidos WHERE cliente_id = ?" dur=2.0ms
… (la misma consulta se repite 4.000 veces; 4.001 consultas en total, 9.1 s acumulados)
```'''),
            ("assistant", r'''Método: síntoma → hipótesis → experimento → causa raíz.

- **Hipótesis 1 (falta un índice)**: descartada con evidencia. El índice existe y cada consulta individual tarda ~2 ms — si fuera un problema de índices, cada consulta sería lenta, no habría 4.001 consultas rápidas.
- **Experimento**: contar consultas por petición en el log. Resultado: exactamente `1 + N` donde N = número de clientes (4.000). La latencia total ≈ N × latencia individual. Ese patrón 1+N tiene nombre: N+1 (o «consulta por fila»).
- **Causa raíz**: el bucle delega la agregación a la aplicación; la BD puede hacerla en una sola pasada con JOIN + GROUP BY. Además el código original usa INNER implícito por cómo consume los clientes: hay que decidir explícitamente si los clientes sin pedidos aparecen (LEFT JOIN) o no (INNER JOIN). En reporting, omitir silenciosamente filas es un bug sutil.

Corrección:

```php
<?php
declare(strict_types=1);

$sql = 'SELECT c.id, c.nombre,
               COALESCE(SUM(p.total_cents), 0) AS facturado_cents
          FROM clientes c
          LEFT JOIN pedidos p ON p.cliente_id = c.id
         GROUP BY c.id, c.nombre';
$filas = $pdo->query($sql)->fetchAll(PDO::FETCH_ASSOC);

$total = array_sum(array_column($filas, 'facturado_cents')) / 100;
foreach ($filas as &$c) {
    $c['facturado'] = number_format(((int) $c['facturado_cents']) / 100, 2, '.', '');
}
unset($c);   // soltar la referencia del foreach por &, error clasico olvidarla
```

De 4.001 consultas a 1; la latencia pasa de ~9 s a decenas de ms. Verificación de la semántica de la agregación (la misma consulta contra SQLite en el harness, con clientes sin pedidos incluidos):

```sql
CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL);
CREATE TABLE pedidos (
  id INTEGER PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id),
  total_cents INTEGER NOT NULL
);
CREATE INDEX idx_pedidos_cliente ON pedidos(cliente_id);
INSERT INTO clientes (id, nombre) VALUES (1, 'acme'), (2, 'beta'), (3, 'gamma'), (4, 'delta');
INSERT INTO pedidos (cliente_id, total_cents) VALUES
  (1, 120000), (1, 80000), (2, 45000), (2, 15000), (2, 30000);
SELECT c.nombre, printf('%.2f', COALESCE(SUM(p.total_cents), 0) / 100.0) AS facturado
  FROM clientes c
  LEFT JOIN pedidos p ON p.cliente_id = c.id
 GROUP BY c.id, c.nombre
 ORDER BY c.id;
SELECT printf('%.2f', SUM(total_cents) / 100.0) AS total_global FROM pedidos;
```

Comprobación adicional en un entorno con PHP: `php -l` sobre el fichero corregido, y re-contar consultas en el log tras el fix: debe ser exactamente 1. Si el informe necesitara filtros por fechas, el JOIN con la condición en `ON` (no en `WHERE`) preserva los clientes sin pedidos del rango.

Cómo prevenir la recaída: alerta de APM sobre `queries_per_request > umbral` y revisión de código con esa regla como checklist obligatoria en endpoints de reporting.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
            {"name": "sql_agregacion_una_consulta", "action": "sql", "lang": "sql", "msg": -1, "block": 1,
             "expect_stdout_contains": ["acme|2000.00", "beta|900.00", "gamma|0.00", "delta|0.00", "2900.00"]},
        ],
        tags=["php", "n-plus-1", "sql", "rendimiento", "reporting"],
        stack=["php", "sql"],
        recovery=True,
    ),

    # PHP 9 — Debugging: array_search falsy 0 e in_array sin strict
    E(
        language="php",
        domain="backend",
        subdomain="comparaciones_sueltas",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r'''Bug doble en la configuración de canales de notificación del CRM y no logro aislarlo:

1) Cuando el usuario elige el primer canal de la lista («sms»), el sistema aplica SIEMPRE el canal por defecto («email»).
2) Seguridad reportó que valores raros como "2e0" pasan la whitelist de IDs de canal.

Código implicado:

```php
<?php
$canales = ['sms', 'email', 'push'];
$pos = array_search($_GET['canal'] ?? '', $canales);
if ($pos) {                       // suponemos que "no encontrado" es lo unico falsy
    $canalElegido = $canales[$pos];
} else {
    $canalElegido = 'email';      // por defecto
}

$permitidos = ['2', '5', '9'];    // IDs de canal autorizados para esta cuenta
$idCanal = $_GET['canal_id'] ?? '';
if (in_array($idCanal, $permitidos)) {
    enviarACanal((int) $idCanal);
}
```'''),
            ("tool", r'''Transcripción de referencia (PHP 8.2 CLI), los tres experimentos mínimos:

```
$ php -r "var_dump(array_search('sms', ['sms', 'email', 'push']));"
int(0)
$ php -r "var_dump((bool) 0, (bool) 'email');"
bool(false)
bool(true)
$ php -r "var_dump(in_array('2e0', ['2', '5', '9']));"
bool(true)
$ php -r "var_dump(in_array('2e0', ['2', '5', '9'], true));"
bool(false)
```'''),
            ("assistant", r'''Dos defectos INDEPENDIENTES; conviene no mezclarlos:

**Defecto 1 — posición 0 confundida con «no encontrado».** `array_search` devuelve la posición o `false`. La posición 0 es falsy, así que `if ($pos)` la trata como «no encontrado» y cae al default. Nota el experimento: devuelve `int(0)` y `(bool) 0` es `false`. La regla PHP: funciones que devuelven `false` como centinela se comparan SIEMPRE con `=== false`. Primera corrección parcial que probé y descarté a medias: añadir `true` como tercer argumento — eso arregla el tipo pero NO el falsy: `array_search('sms', ..., true)` sigue devolviendo `0`. La corrección completa es de identidad, no de strictness.

**Defecto 2 — coerción numérica en `in_array` sin strict.** Con comparación suelta, `'2e0' == '2'` es TRUE porque ambas son cadenas numéricas válidas (notación científica): el whitelist salta con un valor que nunca fue «2». Con `true` como tercer argumento, la comparación es por cadena exacta y el bypass desaparece. Aun mejor para lookups por ID: un array asociativo con las claves como claves — las claves de array no sufren coerción del valor buscado.

Corrección:

```php
<?php
declare(strict_types=1);

const CANALES = ['sms', 'email', 'push'];

function resuelve_canal(?string $preferido): string
{
    if ($preferido === null || $preferido === '') {
        return 'email';
    }
    $pos = array_search($preferido, CANALES, true);
    return $pos === false ? 'email' : CANALES[$pos];   // identidad: 0 es un resultado valido
}

const CANALES_ID = ['2' => 'sms', '5' => 'email', '9' => 'push'];

function canal_autorizado(string $id): ?string
{
    return CANALES_ID[$id] ?? null;    // lookup exacto por clave; '2e0' no existe como clave
}
```

Cómo comprobarlo (php -r en un entorno con PHP):

```
php -r "var_dump(array_search('sms', ['sms','email','push'], true) === 0);"   // bool(true)
php -r "var_dump(in_array('2e0', ['2','5','9'], true));"                      // bool(false)
php -r '$m = ["2"=>"sms"]; var_dump($m["2e0"] ?? null);'                      // NULL
```

Lección general: en PHP, todo `array_search`/`strpos`/`fetchColumn` comparado con `if ($x)` hereda este bug el día que el resultado legítimo es 0. El validador estático (PHPStan nivel ≥ 6 con strict-rules) lo señala de forma automática.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "comparacion-estricta", "array-search", "in-array", "coercion"],
        stack=["php"],
        recovery=True,
    ),

    # PHP 10 — Debugging: magic hashes con == y migracion de md5 a password_hash
    E(
        language="php",
        domain="security",
        subdomain="migracion_hashes",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", r'''Sistema de 2011 en producción: la columna `users.password` guarda `md5($pass)` sin salt. El equipo reporta algo insólito: «ciertas contraseñas alternativas inician sesión igual», y seguridad teme una fuga de la tabla. El login:

```php
<?php
function check_login(string $user, string $pass): bool {
    $row = db_one("SELECT id, password FROM users WHERE username = '" . $user . "'"); // SQLi conocida, otro ticket
    return md5($pass) == $row['password'];
}
```

Se nos pide: arreglar el login «universal» y de paso migrar a un KDF moderno sin resetear a todos los usuarios. PHP 8.2.'''),
            ("tool", r'''Transcripción de referencia (PHP 8.2 CLI), reprodución mínima del fenómeno:

```
$ php -r "var_dump(md5('240610708'));"
string(32) "0e462097431906509019562988736854"
$ php -r "var_dump(md5('QNKCDZO'));"
string(32) "0e830400451993494058024219903391"
$ php -r "var_dump(md5('240610708') == md5('QNKCDZO'));"
bool(true)
$ php -r "var_dump(md5('240610708') === md5('QNKCDZO'));"
bool(false)
$ php -r "var_dump('0e462' == '0e830');"
bool(true)
```'''),
            ("assistant", r'''Método, con dos hipótesis competidoras:

- **Hipótesis 1: colisión real de md5.** Implicaría que `md5($a) === md5($b)` con $a ≠ $b. El experimento 4 la refuta: con comparación estricta, esos dos textos NO colisionan. md5 completo de textos arbitrarios no produce colisiones triviales.
- **Hipótesis 2: el comparador.** Los hashes hexadecimales pueden empezar por `0e…`, que PHP interpreta como notación científica cuando compara con `==` DOS cadenas numéricas: `0e462097431906509019562988736854` vale `0 × 10^462…` = 0, y lo mismo el otro. Cero == cero. Son los «magic hashes»: existen entradas cuyo md5 adopta esa forma (el experimento 5 lo demuestra sin necesitar el par completo). Confirmado: el bug es del COMPARADOR, no del hash.

Corrección en dos frentes: comparador seguro YA y migración de algoritmo en el login correcto (rehash-on-login: solo ahí disponemos de la contraseña en claro).

```php
<?php
declare(strict_types=1);

function check_login(PDO $pdo, string $user, string $pass): bool
{
    $stmt = $pdo->prepare('SELECT id, password FROM users WHERE username = ?');
    $stmt->execute([$user]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!is_array($row)) {
        static $dummy = null;
        $dummy ??= password_hash('usuario-fantasma', PASSWORD_BCRYPT);
        password_verify($pass, $dummy);        // coste uniforme: no se enumeran usuarios
        return false;
    }
    $stored = (string) $row['password'];

    if (str_starts_with($stored, '$2y$') || str_starts_with($stored, '$argon2')) {
        return password_verify($pass, $stored);   // hash_equals dentro; tiempo constante
    }

    $okLegacy = $stored !== '' && hash_equals($stored, md5($pass));
    if ($okLegacy) {
        $up = $pdo->prepare('UPDATE users SET password = ? WHERE id = ?');
        $up->execute([password_hash($pass, PASSWORD_BCRYPT), (int) $row['id']]);
    }
    return $okLegacy;
}
```

Decisiones y notas:

- `hash_equals()` en vez de `===`: comparación en tiempo constante, inmune a timing attacks sobre la comparación de cadenas (aunque md5 sea rápido, la fuga lateral gratis no se regala).
- `str_starts_with($stored, '$2y$')`: distinguir formatos por prefijo hace la migración reversible y permite coexistencia; `password_needs_rehash()` sería la variante canónica si todo ya estuviera en password_hash().
- La migración es «perezosa»: cada usuario se rehashea a su primer login correcto. Ventana residual: usuarios inactivos quedan en md5 — plan paralelo: expirar sesiones y forzar reset a los que no entren en 90 días, y borrar md5s restantes con un trabajo por lotes.
- md5 sigue siendo inaceptable como KDF (velocidad); esto es un puente, no el destino.
- El SQLi del SELECT se marca para otro ticket, pero no dormimos con prepared statements pendientes.

Cómo comprobarlo: `php -l`; en un entorno con PHP: los `php -r` de arriba deben seguir mostrando `==` en true (es la demostración del lenguaje) y `password_verify` con pares magic-hash debe dar false; y un test de integración que inserte un usuario md5 y haga login dos veces debe ver la columna cambiar de formato md5 a `$2y$…` tras el primer login.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "password-hash", "magic-hash", "migracion", "timing-attack"],
        stack=["php"],
        recovery=True,
    ),

    # PHP 11 — Debugging: notices de PHP 8, null coercion y contratos de entrada
    E(
        language="php",
        domain="backend",
        subdomain="notices_php8",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r'''Tras migrar a PHP 8.2, el endpoint de tarifas devuelve 500 intermitente y el error log se llena. El código:

```php
<?php
function precio_con_descuento(array $articulo): float {
    $base = $articulo['precio'];
    $dto  = $articulo['descuento_pct'] / 100;
    return round($base - $base * $dto, 2);
}

// punto de entrada (varias rutas llaman a la funcion):
$a = $_GET;
echo precio_con_descuento($a);
```

Llamadas típicas: `?precio=19.90` (sin descuento_pct) y `?precio=abc`. Mi primera teoría fue que el CLI y el FPM tienen versiones distintas de PHP, pero el equipo dice que no.'''),
            ("tool", r'''Transcripción de referencia del error log (FPM) tras dos llamadas:

```
[12-May-2024 09:41:02 Europe/Madrid] PHP Warning:  Undefined array key "descuento_pct" in /var/www/html/src/Precios.php on line 4
[12-May-2024 09:41:02 Europe/Madrid] PHP Fatal error:  Uncaught TypeError: Unsupported operand types: null / int in /var/www/html/src/Precios.php:4
Stack trace:
#0 /var/www/html/src/Precios.php(11): precio_con_descuento(Array)
#1 {main}
  thrown in /var/www/html/src/Precios.php on line 4
[12-May-2024 09:41:09 Europe/Madrid] PHP Warning:  A non-numeric value encountered in /var/www/html/src/Precios.php on line 5
```

Y en CLI, para comparar entornos:

```
$ php -v
PHP 8.2.6 (cli)
$ php-fpm82 -v | head -1
PHP 8.2.6 (fpm-fcgi)
```'''),
            ("assistant", r'''Cadena causal, línea a línea:

1. `$articulo['precio']` con clave ausente → `null` + Warning (PHP 8 cambió el texto del notice, no la semántica).
2. `$articulo['descuento_pct'] / 100` con la clave ausente → `null / 100`. En PHP 7 eso era warning + resultado 0; en PHP 8, `null / int` es un **TypeError fatal** («Unsupported operand types»). Eso explica el 500 intermitente: solo cuando falta el campo.
3. `?precio=abc` → 'abc' - 'abc'*0.0 → «A non-numeric value encountered»: el warning de coerción que en 7 pasaba desapercibido y en 8 sigue siendo warning pero con `null` de por medio acabó en el caso 2.

La teoría de «versiones distintas» se descarta con el experimento del log: CLI y FPM reportan 8.2.6 idénticos. La causa real es el cambio de semántica del motor sobre un CONTRATO DE ENTRADA que nunca existió: la función aceptaba cualquier array y confiaba en coerciones.

Primera idea (descartada): parchear con `$articulo['descuento_pct'] ?? 0`. Enmascara el problema real — `?precio=abc` seguiría produciendo precio 0.00 y se cobraría gratis. El bug de fondo es que la entrada no se valida.

Corrección: validar en la frontera, tipar el dominio:

```php
<?php
declare(strict_types=1);

/** @return array{precio: float, descuento_pct: float} */
function normaliza_articulo(array $in): array
{
    $precio = filter_var($in['precio'] ?? null, FILTER_VALIDATE_FLOAT);
    if ($precio === false || $precio < 0) {
        throw new InvalidArgumentException('precio invalido');
    }
    $dto = filter_var($in['descuento_pct'] ?? 0, FILTER_VALIDATE_FLOAT);
    if ($dto === false || $dto < 0 || $dto > 100) {
        throw new InvalidArgumentException('descuento invalido');
    }
    return ['precio' => $precio, 'descuento_pct' => $dto];
}

function precio_con_descuento(float $precio, float $descuentoPct): float
{
    return round($precio - $precio * $descuentoPct / 100, 2);
}

// punto de entrada:
try {
    $a = normaliza_articulo($_GET);
    echo precio_con_descuento($a['precio'], $a['descuento_pct']);
} catch (InvalidArgumentException $e) {
    http_response_code(422);
    echo json_encode(['error' => $e->getMessage()]);
}
```

Detalles que importan:

- `filter_var(..., FILTER_VALIDATE_FLOAT)` devuelve `float|false`: con `$precio === false` (identidad) distinguimos 0.0 válido de inválido — un `!$precio` aquí sería otro bug de falsy.
- Con `strict_types=1`, `precio_con_descuento(float, float)` ya no acepta '19.90' colándose: la validación es la ÚNICA puerta de coerción.
- `?? 0` ahora es correcto porque va DESPUÉS de validar el tipo: ausencia de descuento es semántica legítima; descuento no numérico es error 422.
- No silenciar con `@` ni `error_reporting(0)`: los warnings eran el síntoma que localizó el bug.

Cómo comprobarlo: `php -l`; en CLI con PHP: llamar con `?precio=abc` debe dar 422 con JSON (sin fatals en el log) y con `?precio=19.90&descuento_pct=10` debe imprimir 17.91.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "php8", "notices", "typeerror", "validacion-entrada"],
        stack=["php"],
        recovery=True,
    ),

    # PHP 12 — Debugging: headers already sent y redirect sin exit
    E(
        language="php",
        domain="web",
        subdomain="headers_ya_enviados",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r'''El guard del panel no redirige: a veces aparece el warning de cabeceras, a veces la página del panel se pinta DEBAJO del formulario de login, y en una máquina concreta (la del becario, con otro editor) falla SIEMPRE. Ficheros:

```php
<?php // config.php
echo "<!-- build 2024-05-01 -->\n";   // diagnostico que dejo un companero
session_start();
```

```php
<?php // index.php
require 'config.php';
if (!isset($_SESSION['uid'])) {
    header('Location: /login.php');
}
echo '<h1>Panel</h1>';
```'''),
            ("tool", r'''Transcripción de referencia del error log y del comportamiento HTTP:

```
PHP Warning:  Cannot modify header information - headers already sent by
(output started at /var/www/html/config.php:2) in /var/www/html/index.php on line 4
```

```
$ curl -i http://localhost/index.php
HTTP/1.1 200 OK
Content-Type: text/html; charset=UTF-8

<!-- build 2024-05-01 -->
<h1>Panel</h1>
```'''),
            ("assistant", r'''El protocolo HTTP manda: TODAS las cabeceras van antes del primer byte del cuerpo. En PHP, el primer byte de salida (echo, espacio o salto de línea fuera de `<?php … ?>`, o el BOM de un fichero guardado como UTF-8 con BOM) «cierra» la zona de cabeceras; todo `header()` posterior lanza el warning y se descarta.

Aquí hay DOS defectos encadenados:

1. **`echo` en config.php** (línea 2, como dice el propio warning: output started at config.php:2) incluido antes del `header()`. Sin esa línea, el redirect «funcionaría» — y seguiría teniendo el defecto 2.
2. **`header('Location: …')` sin `exit`**: PHP sigue ejecutando y RENDERIZA el panel en el cuerpo de la respuesta del guard. Hoy el daño es cosmético; mañana, con contenido sensible en vez de un `<h1>`, es una fuga real: el redirect es una cabecera, no un cortafuegos.

La pista del «solo en la máquina del becario» apunta al defecto clásico restante: su editor guarda con BOM (3 bytes EF BB BF antes de `<?php`), que cuenta como salida aunque no se vea.

Corrección:

```php
<?php // config.php
declare(strict_types=1);
session_start([
    'cookie_httponly' => true,
    'cookie_samesite' => 'Lax',
]);
```

```php
<?php // index.php
require __DIR__ . '/config.php';
if (!isset($_SESSION['uid'])) {
    header('Location: /login.php', true, 302);
    exit;                        // tras Location, exit SIEMPRE
}
echo '<h1>Panel</h1>';
```

Reglas que se derivan:

- Nada de salida antes de cabeceras: ni diagnóstico temporal, ni espacios tras `?>` (de hecho, omite el `?>` final en ficheros PHP puros), ni UTF-8 con BOM.
- `exit` inmediato tras `header('Location: …')`; el segundo parámetro `true` (reemplazar) y el `302` explícito dejan el intent claro.
- `ob_start()` como cinturón de seguridad en el front controller puede esconder el warning, pero NO arregla el diseño; no lo uses para «parchear» esto.
- En APIs JSON el mismo bug se manifiesta como «Warning: headers already sent» mezclado con el JSON del cliente.

Cómo comprobarlo: `php -l` en ambos ficheros; y `curl -i http://localhost/index.php` debe devolver `HTTP/1.1 302 Found` con `Location: /login.php` y cuerpo vacío — no un 200 con HTML.'''),
        ],
        verify=[
            {"name": "sintaxis_config_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
            {"name": "sintaxis_index_php", "action": "syntax", "lang": "php", "msg": -1, "block": 1},
        ],
        tags=["php", "headers", "http", "redirect", "sesiones"],
        stack=["php"],
        recovery=True,
    ),

    # PHP 13 — Code review: webhook de pasarela de pago
    E(
        language="php",
        domain="security",
        subdomain="webhook_pagos",
        difficulty="very_hard",
        task_type="code_review",
        messages=[
            ("user", r'''PR a revisar: receptor del webhook de la pasarela de pago (producción, dinero real). Código propuesto:

```php
<?php
// POST /webhooks/pagos
$payload = json_decode(file_get_contents('php://input'), true);
if ($_SERVER['HTTP_X_SIGNATURE'] === hash('sha256', $payload['monto'] . SECRET)) {
    $pedido = db_one("SELECT * FROM pedidos WHERE ref = '" . $payload['ref'] . "'");
    if ($pedido) {
        db_exec("UPDATE pedidos SET estado = 'pagado' WHERE ref = '" . $payload['ref'] . "'");
        db_exec("INSERT INTO pagos (ref, monto, tarjeta) VALUES ('" . $payload['ref'] . "', " . $payload['monto'] . ", '" . $payload['tarjeta'] . "')");
    }
}
http_response_code(200);
echo 'ok';
```

Marca qué es bug real y qué es preferencia; el equipo suele discutir por estilo y quiero que esta revisión sea accionable.'''),
            ("assistant", r'''Revisión ordenada por severidad. Todo lo que sigue es BUG, no preferencia:

1. **[CRÍTICO] Firma verificada con `==` y sobre un subconjunto del mensaje.** Dos problemas sumados: comparación no constante en tiempo (hash_equals) y la firma cubre solo `monto`, así que un atacante con una firma válida de un monto puede reutilizarla cambiando `ref` (replay). Corrección: HMAC sobre el cuerpo CRUDO (`hash_hmac('sha256', $raw, $secret)`) verificado con `hash_equals`. La pasarela firma el mensaje completo por algo.
2. **[CRÍTICO] SQL por interpolación con `ref` y `tarjeta` del exterior.** Inyección directa sobre tabla de pagos. Prepared statements, sin excepciones.
3. **[GRAVE] Guarda el número completo de tarjeta en nuestra BD.** Ámbito PCI DSS: almacenar PAN exige controles que no tenemos; la pasarela ya tokeniza. Se guarda token + últimos 4 dígitos, y el campo desaparece de esta tabla.
4. **[GRAVE] Sin idempotencia.** La pasarela REINTENTA los webhooks. El UPDATE es inocuo, pero el INSERT duplica filas de pago (doble contabilidad). Clave de evento (`event_id`) con UNIQUE: si el insert choca, es un reintento → responder 200 y no re-aplicar.
5. **[MEDIO] Responde 200 SIEMPRE, incluso con firma inválida.** La pasarela interpreta el 200 como «entregado» y deja de reintentar: un fallo transitorio nuestro pierde el evento para siempre. Contrato correcto: 401 firma inválida (la pasarela reintenta), 422 payload incoherente, 500 fallo nuestro con backoff, 200 solo cuando se aplicó o era duplicado.
6. **[MEDIO] No valida el monto contra el pedido.** Un webhook legítimo con `monto` manipulado en tránsito (o un test de la pasarela mal apuntado) marcaría pagado un pedido de 500€ con un pago de 0,01€. Comparar montos en la transacción.

Preferencias (NO bloquear el PR): usar PSR-12/nombres de variables; inyectar el logger en vez del global; tipar el helper `db_one`. Estilo, no defectos.

Corrección:

```php
<?php
declare(strict_types=1);

/** @return array{0: int, 1: array<string, mixed>} */
function handle_webhook(PDO $pdo, string $raw, string $signature): array
{
    if (!hash_equals(hash_hmac('sha256', $raw, WEBHOOK_SECRET), $signature)) {
        return [401, ['error' => 'firma invalida']];
    }
    try {
        $data = json_decode($raw, true, 16, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        return [400, ['error' => 'json malformado']];
    }
    $ref    = (string) ($data['ref'] ?? '');
    $monto  = (int) ($data['monto_cents'] ?? 0);
    $evento = (string) ($data['event_id'] ?? '');
    if ($ref === '' || $monto <= 0 || $evento === '') {
        return [422, ['error' => 'payload incompleto']];
    }

    $sel = $pdo->prepare('SELECT estado, monto_cents FROM pedidos WHERE ref = ?');
    $sel->execute([$ref]);
    $pedido = $sel->fetch(PDO::FETCH_ASSOC);
    if (!is_array($pedido)) {
        return [404, ['error' => 'pedido inexistente']];
    }
    if ((int) $pedido['monto_cents'] !== $monto) {
        return [422, ['error' => 'importe no coincide']];
    }

    $pdo->beginTransaction();
    try {
        try {
            $pdo->prepare('INSERT INTO eventos_pasarela (event_id, ref) VALUES (?, ?)')
                ->execute([$evento, $ref]);          // UNIQUE(event_id): arbitra reintentos
        } catch (PDOException) {
            $pdo->rollBack();
            return [200, ['status' => 'duplicado']]; // reintento de la pasarela: ya aplicado
        }
        if ($pedido['estado'] !== 'pagado') {
            $pdo->prepare("UPDATE pedidos SET estado = 'pagado' WHERE ref = ?")
                ->execute([$ref]);
        }
        $pdo->commit();
    } catch (Throwable) {
        $pdo->rollBack();
        return [500, ['error' => 'procesamiento fallido']];  // la pasarela reintenta con backoff
    }
    return [200, ['status' => 'aplicado']];
}
```

Notas de diseño: la validación de existencia/monto va FUERA de la transacción (lecturas), y dentro solo el par insert-evento/update-estado, que es lo que exige atomicidad. `catch (PDOException)` del insert funciona porque el bootstrap fija `PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION` y `event_id` es la única columna UNIQUE de esa tabla; si añadiera más, convendría inspeccionar `errorInfo()[1]`. WEBHOOK_SECRET viene del entorno y rota por dos ventanas cuando toque. El `tarjeta` del payload se ignora: de eso se encarga el token de la pasarela.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "webhook", "hmac", "idempotencia", "pci-dss", "code-review"],
        stack=["php"],
        recovery=False,
    ),

    # PHP 14 — Code review: repositorio de busquedas (LIKE, ORDER BY, singleton)
    E(
        language="php",
        domain="databases",
        subdomain="repositorio_busquedas",
        difficulty="hard",
        task_type="code_review",
        messages=[
            ("user", r'''Revisión del PR del buscador del catálogo. Código:

```php
<?php
class ArticuloRepo {
    private $db;
    public static $instancia;
    public function __construct($db) { $this->db = $db; }
    public static function get(): self {
        return self::$instancia ??= new self(DB::getInstance());
    }
    public function buscar($filtro, $orden) {
        return $this->db->query("SELECT * FROM articulos WHERE nombre LIKE '%$filtro%' ORDER BY $orden")->fetchAll();
    }
    public function todos() {
        return $this->db->query('SELECT * FROM articulos')->fetchAll();
    }
}
```

El autor dice que «funciona» y que lo del ORDER BY se arregla escapando comillas. Necesito la revisión separando lo que bloquea el PR.'''),
            ("assistant", r'''Hay un malentendido que desbloquea todo: **el ORDER BY no se arregla escapando**. Los identificadores (columnas) no son valores: no admiten placeholder en prepared statements ni escapado fiable. La solución canónica es una whitelist: el usuario elige una CLAVE, el mapa decide la SQL.

Lo que BLOQUEA el PR:

1. **[BUG] Inyección por `$filtro` en el LIKE.** `'%$filtro%'` permite romper la comilla y también inyectar comodines (`%` y `_`) a voluntad — una búsqueda de «%» escanea la tabla. Corrección: placeholder + escapado de comodines con `ESCAPE`.
2. **[BUG] Inyección por `$orden`.** Un `orden` tipo `precio;DROP TABLE x--` o `(SELECT 1)` viaja literal a la consulta. Corrección: mapa `clave => expresión SQL` declarada en el código.
3. **[BUG] `SELECT *` + `fetchAll()` sin límite.** Con 2M de artículos materializa todo y un cliente puede pedir ordenados los 2M. Columnas explícitas + `LIMIT` acotado (y paginación).
4. **[BUG] `SELECT *` acopla el contrato de la API al esquema físico**: añadir una columna con datos sensibles la expone sin tocar código.

Lo que es PREFERENCIA (sugerir, no bloquear): `final` y tipos en la firma (el `$db` sin tipo y `private $db` sin declaración son estilo aquí, no bug); el singleton `get()` sí lo discutiría como deuda de testeabilidad, pero es ortogonal a este PR.

Corrección:

```php
<?php
declare(strict_types=1);

final class ArticuloRepository
{
    /** claves publicas -> expresion ORDER BY declarada, jamas del usuario */
    private const ORDEN_VALIDO = [
        'nombre'     => 'nombre ASC, id ASC',
        'nombre_inv' => 'nombre DESC, id DESC',
        'precio'     => 'precio ASC, id ASC',
        'precio_inv' => 'precio DESC, id DESC',
    ];

    public function __construct(private PDO $pdo) {}

    /** @return list<array{id: int, nombre: string, precio: float}> */
    public function buscar(string $termino, string $orden): array
    {
        $sqlOrden = self::ORDEN_VALIDO[$orden] ?? 'id ASC';
        $stmt = $this->pdo->prepare(
            "SELECT id, nombre, precio
               FROM articulos
              WHERE nombre LIKE :term ESCAPE '\\'
              ORDER BY $sqlOrden
              LIMIT 200"
        );
        $term = '%' . strtr($termino, ['\\' => '\\\\', '%' => '\\%', '_' => '\\_']) . '%';
        $stmt->execute(['term' => $term]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }
}
```

Verificación de la semántica de LIKE con escape y del ORDER whitelisteado (ejecutable contra SQLite en el harness):

```sql
CREATE TABLE articulos (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, precio NUMERIC NOT NULL);
INSERT INTO articulos (nombre, precio) VALUES
  ('teclado mecanico', 49.90), ('monitor 24 pulgadas', 199.00), ('cable HDMI', 9.50),
  ('teclado memoria', 39.00), ('100% algodon', 5.00);
-- busqueda con comodines del usuario neutralizados:
SELECT id, nombre, printf('%.2f', precio) FROM articulos WHERE nombre LIKE '%teclado%' ORDER BY precio ASC, id ASC;
-- un termino que CONTIENE '%' literal solo casa con el % escapado:
SELECT id, nombre FROM articulos WHERE nombre LIKE '%100\%%' ESCAPE '\' ORDER BY id;
```'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
            {"name": "sql_like_escape_whitelist", "action": "sql", "lang": "sql", "msg": -1, "block": 1,
             "expect_stdout_contains": ["4|teclado memoria|39.00", "1|teclado mecanico|49.90", "5|100% algodon"]},
        ],
        tags=["php", "sql-injection", "like-escape", "order-by-whitelist", "code-review"],
        stack=["php", "sql"],
        recovery=False,
    ),

    # PHP 15 — Refactoring: validacion duplicada en dos controladores
    E(
        language="php",
        domain="backend",
        subdomain="refactor_validacion",
        difficulty="hard",
        task_type="refactoring",
        messages=[
            ("user", r'''Refactor solicitado del módulo de pedidos (PHP 8.2): dos controladores — crear pedido y reservar stock — repiten la misma validación con ligeras divergencias que ya causaron tickets. Fragmento real (el segundo controlador repite esto 60 líneas después con «cantidad» validada de otra forma):

```php
<?php
// ControladorA (crear pedido)
if (!isset($_POST['sku']) || !preg_match('/^[A-Z]{3}-[0-9]{4}$/', $_POST['sku'])) {
    http_response_code(422);
    echo json_encode(['error' => 'sku invalido']);
    exit;
}
if (!isset($_POST['cantidad']) || !ctype_digit($_POST['cantidad']) || $_POST['cantidad'] < 1 || $_POST['cantidad'] > 1000) {
    http_response_code(422);
    echo json_encode(['error' => 'cantidad invalida']);
    exit;
}
// ... logica de alta

// ControladorB (reservar stock): mismo sku, pero cantidad con is_numeric
// (por eso '2.5' pasa aqui y no en A: ticket #4521)
```

Condición dura: el contrato HTTP no puede cambiar NI UN BYTE (hay scripts de integración parseando el cuerpo exacto: un solo error por vez, claves `error`, códigos 422).'''),
            ("assistant", r'''Método de refactor seguro, en este orden:

1. **Tabla de caracterización** (qué produce hoy el código): sku `X` → 422 `{"error":"sku invalido"}`; sku `ABC-1234` + cantidad `'0'` → 422 `{"error":"cantidad invalida"}`; cantidad `'1e3'` → 422 (ctype_digit falla); cantidad `'2.5'` → en A 422, en B PASA (la divergencia que causa el ticket); cantidad `'10'` → continúa.
2. Extraer la validación a un único punto con el contrato EXACTO de la tabla.
3. Re-ejecutar la tabla contra el refactor: misma salida byte a byte. Solo entonces unificar el caso `'2.5'` — y aquí sí hay decisión de producto: la regla correcta es rechazar decimales (unidades enteras), igual que A; el cambio se comunica aparte, no escondido en un refactor.

```php
<?php
declare(strict_types=1);

final class OrderInput
{
    private function __construct(
        public readonly string $sku,
        public readonly int $cantidad,
    ) {}

    /** Devuelve el DTO validado o la lista de mensajes de error (contrato 1-error-por-vez). */
    public static function fromArray(array $in): self|array
    {
        $errors = [];
        $sku = $in['sku'] ?? '';
        if (!is_string($sku) || preg_match('/^[A-Z]{3}-[0-9]{4}$/', $sku) !== 1) {
            $errors[] = 'sku invalido';
        }
        $cantidad = $in['cantidad'] ?? null;
        if (!is_string($cantidad) || !ctype_digit($cantidad)
            || (int) $cantidad < 1 || (int) $cantidad > 1000) {
            $errors[] = 'cantidad invalida';
        }
        return $errors === [] ? new self($sku, (int) $cantidad) : $errors;
    }
}

// ControladorA (y B, con su logica propia tras validar):
$input = OrderInput::fromArray($_POST);
if (is_array($input)) {
    http_response_code(422);
    echo json_encode(['error' => $input[0]]);   // mismo cuerpo que hoy: UN mensaje, clave 'error'
    exit;
}
// $input->sku / $input->cantidad: tipos garantizados, sin re-validar
```

Dos golpes que recibí (y corregí) durante el propio refactor — por si alguien repite el ejercicio:

- Primera versión devolvía `{'errors': [...]}` (plural, lista): rompía el script de facturación que parsea `error`. Lo detectó la re-ejecución de la tabla de caracterización ANTES de hacer merge. La lección: el refactor solo mueve código; cambiar contrato es otro cambio, visible en otro PR.
- Segunda versión validaba con `is_int($cantidad)`: en POST form-encoded todo llega como string, así que `'10'` era rechazado. Por eso el filtro mantiene `is_string + ctype_digit`: acepta la representación del formulario, no tipos que nunca llegarán.

`readonly` en las propiedades: el DTO es inmutable tras validar — ningún controlador puede «ajustar» la cantidad a posteriori sin pasar por la validación otra vez.

Cómo comprobarlo: `php -l`; y la tabla de caracterización como script de humo (curl por cada fila comparando status y cuerpo exacto) debe pasar idéntica antes y después.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
        ],
        tags=["php", "refactoring", "validacion", "dto", "contrato-http"],
        stack=["php"],
        recovery=True,
    ),

    # PHP 16 — Refactoring: singleton global a inyeccion de dependencias
    E(
        language="php",
        domain="architecture",
        subdomain="singleton_a_di",
        difficulty="very_hard",
        task_type="refactoring",
        messages=[
            ("user", r'''Migración pedida por el equipo de calidad: eliminar el acceso global `DB::getInstance()` de los repositorios para poder probar contra SQLite en memoria. Estado actual (hay 23 llamadas a DB::getInstance() repartidas en 9 ficheros):

```php
<?php
final class DB {
    private static ?PDO $pdo = null;
    public static function getInstance(): PDO {
        if (self::$pdo === null) {
            self::$pdo = new PDO(getenv('DB_DSN'), null, null, [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            ]);
        }
        return self::$pdo;
    }
}

final class PedidosRepo {
    public function porCliente(int $id): array {
        return DB::getInstance()
            ->query('SELECT id, cliente_id, total_cents FROM pedidos WHERE cliente_id = ' . $id)
            ->fetchAll(PDO::FETCH_ASSOC);
    }
}
```

Propón la migración sin big-bang: el despliegue no puede pararse y los tests deben poder ejecutarse en paralelo.'''),
            ("assistant", r'''El singleton tiene aquí tres costes concretos: dependencia oculta (la firma de `porCliente` no dice que habla con MySQL), pruebas serializables (un global de PHP es por-proceso: dos tests paralelos se pisan), y acoplamiento al bootstrap (cambiar DSN exige tocar la clase DB). El plan de migración en fases:

**Fase 1 — introducir inyección sin romper a nadie.** El repositorio acepta PDO por constructor; el facade estático se mantiene UNA RELEASE delegando en la instancia inyectada (para los 14 puntos de llamada que todavía no migraron):

```php
<?php
declare(strict_types=1);

final class PedidosRepository
{
    public function __construct(private PDO $pdo) {}

    /** @return list<array{id: int, cliente_id: int, total_cents: int}> */
    public function porCliente(int $clienteId): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT id, cliente_id, total_cents FROM pedidos WHERE cliente_id = ? ORDER BY id'
        );
        $stmt->execute([$clienteId]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }
}

/** Facade de transicion: deprecated desde el dia 1, se borra en la release siguiente. */
final class PedidosRepo
{
    private static ?PedidosRepository $instancia = null;

    public static function conPDO(PDO $pdo): void
    {
        self::$instancia = new PedidosRepository($pdo);
    }

    /** @deprecated usar inyeccion; se elimina en la release 24.7 */
    public function porCliente(int $id): array
    {
        if (self::$instancia === null) {
            self::$instancia = new PedidosRepository(DB::getInstance()); // camino legacy
        }
        return self::$instancia->porCliente($id);
    }
}
```

**Fase 2 — el front controller resuelve UNA vez** (ahí vive la «única instancia», que era lo único valioso del singleton):

```php
$pdo = new PDO(getenv('DB_DSN'), null, null, [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_EMULATE_PREPARES => false,
]);
PedidosRepo::conPDO($pdo);
// ... y cada controlador nuevo recibe su repositorio ya construido
```

**Fase 3 — tests en paralelo contra SQLite en memoria** (cada test su propia instancia, cero estado compartido):

```php
<?php
declare(strict_types=1);

$pdo = new PDO('sqlite::memory:');
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->exec('CREATE TABLE pedidos (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL, total_cents INTEGER NOT NULL)');
$pdo->exec('INSERT INTO pedidos (cliente_id, total_cents) VALUES (7, 1000), (7, 2500), (8, 900)');

$repo = new PedidosRepository($pdo);
assert(count($repo->porCliente(7)) === 2);
assert($repo->porCliente(9) === []);
echo "humo ok\n";
```

Notas honestas sobre el camino:

- El facade de transición mantiene un estado estático (es su trabajo); la diferencia con el singleton original es que AHORA el estado lo alimenta el bootstrap y los tests pueden no alimentarlo nunca.
- De paso, el `WHERE cliente_id = ' . $id` del original se convierte en placeholder: al tocar la línea por la inyección, la SQLi latente no sobrevive la revisión.
- `assert()` para humo rápido requiere zend.assertions=1 en dev; en CI mejor expectativas explícitas o PHPUnit.
- Cómo comprobarlo: `php -l` en los tres ficheros; la suite contra sqlite::memory: corre en paralelo (procesos distintos, bases distintas) y la llamada deprecated emite E_DEPRECATED en los logs, que es la lista de trabajo para la fase final de borrado.'''),
        ],
        verify=[
            {"name": "sintaxis_repositorio", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
            {"name": "sintaxis_hum_sqlite", "action": "syntax", "lang": "php", "msg": -1, "block": 1},
        ],
        tags=["php", "refactoring", "singleton", "inyeccion-dependencias", "testabilidad"],
        stack=["php"],
        recovery=False,
    ),

    # PHP 17 — Testing: repositorio PDO contra sqlite::memory: (sin MySQL en CI)
    E(
        language="php",
        domain="backend",
        subdomain="pruebas_repositorio",
        difficulty="very_hard",
        task_type="testing",
        messages=[
            ("user", r'''CI sin MySQL disponible y el equipo decide «probar» el PedidosRepository con mocks que repiten el SQL — es decir, tests que prueban el mock. Propón cómo probar el repositorio REAL con comportamiento real (inserción, UNIQUE, rollback) sin servicios externos, en un solo fichero ejecutable. PHP 8.2 + PDO. El repositorio por testear:

```php
<?php
final class PedidosRepository {
    public function __construct(private PDO $pdo) {}
    public function crear(int $clienteId, int $totalCents, string $ref): int {
        $st = $this->pdo->prepare('INSERT INTO pedidos (cliente_id, total_cents, ref) VALUES (?, ?, ?)');
        $st->execute([$clienteId, $totalCents, $ref]);
        return (int) $this->pdo->lastInsertId();
    }
    public function porCliente(int $clienteId): array {
        $st = $this->pdo->prepare('SELECT id, total_cents FROM pedidos WHERE cliente_id = ? ORDER BY id');
        $st->execute([$clienteId]);
        return $st->fetchAll(PDO::FETCH_ASSOC);
    }
}
```'''),
            ("assistant", r'''La pieza clave: PDO tiene driver SQLite incluido (`sqlite::memory:`), así que el repositorio REAL corre contra una base real, en memoria, por-test, determinista y en milisegundos. Un DDL mínimo compartido crea el mundo; cada caso decide qué sembrar. Sin framework: un runner mínimo con códigos de salida sirve de señal a CI.

```php
<?php
declare(strict_types=1);

final class PedidosRepository
{
    public function __construct(private PDO $pdo) {}

    public function crear(int $clienteId, int $totalCents, string $ref): int
    {
        $st = $this->pdo->prepare('INSERT INTO pedidos (cliente_id, total_cents, ref) VALUES (?, ?, ?)');
        $st->execute([$clienteId, $totalCents, $ref]);
        return (int) $this->pdo->lastInsertId();
    }

    /** @return list<array{id: int, total_cents: int}> */
    public function porCliente(int $clienteId): array
    {
        $st = $this->pdo->prepare('SELECT id, total_cents FROM pedidos WHERE cliente_id = ? ORDER BY id');
        $st->execute([$clienteId]);
        return $st->fetchAll(PDO::FETCH_ASSOC);
    }
}

function nuevoPDO(): PDO
{
    $pdo = new PDO('sqlite::memory:');
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('CREATE TABLE pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        total_cents INTEGER NOT NULL,
        ref TEXT NOT NULL UNIQUE
    )');
    return $pdo;
}

$fallos = 0;
function check(bool $cond, string $nombre, int &$fallos): void
{
    echo ($cond ? 'PASS ' : 'FAIL ') . $nombre . PHP_EOL;
    if (!$cond) {
        $fallos++;
    }
}

// 1: creacion y lectura redonda
$pdo = nuevoPDO();
$repo = new PedidosRepository($pdo);
$id = $repo->crear(7, 1200, 'A-1');
check($id > 0, 'crear devuelve id', $fallos);
$rows = $repo->porCliente(7);
check(count($rows) === 1 && (int) $rows[0]['total_cents'] === 1200, 'lectura redonda', $fallos);

// 2: UNIQUE(ref) se traduce en excepcion, no en silencio
try {
    $repo->crear(8, 900, 'A-1');
    check(false, 'ref duplicada lanza', $fallos);
} catch (PDOException) {
    check(true, 'ref duplicada lanza', $fallos);
}

// 3: rollback revierte lo escrito (el repositorio no debe ocultar transacciones)
$pdo->beginTransaction();
$repo->crear(9, 500, 'A-2');
$pdo->rollBack();
check($repo->porCliente(9) === [], 'rollback deja tabla limpia', $fallos);

// 4: dos clientes no se contaminan
$repo->crear(10, 777, 'B-1');
check(count($repo->porCliente(7)) === 1 && count($repo->porCliente(10)) === 1, 'aislamiento por cliente', $fallos);

exit($fallos === 0 ? 0 : 1);
```

Por qué esto es mejor que mockear PDO:

- Los mocks replican el SQL a mano: prueban que llamas al método que tú mismo definiste. Aquí se prueban el SQL REAL, las restricciones REALES (UNIQUE) y la semántica transaccional real.
- Casos elegidos con intención: redondez (1-2), contrato de errores (2), límites de transacción (3) y aislamiento de consultas (4). Con JUnit/PHPUnit serían dataProviders; el patrón (fixture mínima + assertion + cleanup implícito por base nueva) es idéntico.
- Diferencias SQLite/MySQL a documentar en el propio test: `AUTOINCREMENT` vs `AUTO_INCREMENT`, tipado dinámico de SQLite y `ON CONFLICT` — lo que el test cubre debe ser SQL portátil.

La misma lógica de consulta, verificada de verdad contra SQLite (harness):

```sql
CREATE TABLE pedidos (id INTEGER PRIMARY KEY, cliente_id INTEGER NOT NULL, total_cents INTEGER NOT NULL, ref TEXT NOT NULL UNIQUE);
INSERT INTO pedidos (cliente_id, total_cents, ref) VALUES (7, 1200, 'A-1'), (7, 2500, 'A-2'), (8, 900, 'B-1');
SELECT cliente_id, total_cents FROM pedidos WHERE cliente_id = 7 ORDER BY id;
SELECT printf('%d pedidos del cliente 9', COUNT(*)) FROM pedidos WHERE cliente_id = 9;
```

Cómo comprobarlo: `php -l`; ejecutando el fichero en un entorno con PHP la salida esperada es 5 líneas PASS y `exit 0`.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
            {"name": "sql_consulta_repositorio", "action": "sql", "lang": "sql", "msg": -1, "block": 1,
             "expect_stdout_contains": ["7|1200", "7|2500", "0 pedidos del cliente 9"]},
        ],
        tags=["php", "testing", "pdo", "sqlite", "rollback"],
        stack=["php", "sql"],
        recovery=False,
    ),

    # PHP 18 — Optimization: paginacion keyset frente a OFFSET
    E(
        language="php",
        domain="databases",
        subdomain="paginacion_keyset",
        difficulty="very_hard",
        task_type="optimization",
        messages=[
            ("user", r'''El listado de eventos del panel (1M de filas) se llena de timeouts cuando el usuario salta a páginas profundas: «página 9000 de 10000». Código actual:

```php
<?php
$pagina = max(1, (int) ($_GET['pagina'] ?? 1));
$porPagina = 50;
$stmt = $pdo->prepare('SELECT id, categoria, creado FROM eventos ORDER BY id LIMIT ? OFFSET ?');
$stmt->execute([$porPagina, ($pagina - 1) * $porPagina]);
```

El equipo propone «subir el índice», pero el ORDER BY id ya recorre la PK. ¿Qué falta? Propón la solución y demuestra que los resultados coinciden.'''),
            ("assistant", r'''El diagnóstico ya está casi en tu frase: `ORDER BY id` SÍ usa la PK, pero `OFFSET 449950` obliga al motor a RECORRER y DESCARTAR 449.950 filas antes de devolver las 50 de la ventana. El coste del OFFSET crece con la profundidad; subir memoria o índices no lo arregla porque el trabajo inútil es estructural.

La alternativa es paginación keyset (cursor): en lugar de «fila 449.950», la siguiente página se define como «id mayor que el último visto». Coste constante en cualquier profundidad, y de regalo las páginas son ESTABLES ante inserciones concurrentes (con OFFSET, una inserción al principio desplaza todo y el usuario ve duplicados).

```php
<?php
declare(strict_types=1);

/** @return array{data: list<array<string, mixed>>, next_cursor: int|null} */
function pagina_eventos(PDO $pdo, int $despuesDeId, int $limite = 50): array
{
    $limite = max(1, min($limite, 200));        // acotado ANTES de construir la SQL
    $stmt = $pdo->prepare(
        'SELECT id, categoria, creado
           FROM eventos
          WHERE id > :cursor
          ORDER BY id
          LIMIT ' . $limite                     // LIMIT no admite placeholder en este driver
    );
    $stmt->execute(['cursor' => $despuesDeId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    $next = $rows === [] ? null : (int) $rows[array_key_last($rows)]['id'];
    return ['data' => $rows, 'next_cursor' => $next];
}

// el cliente pagina con el cursor devuelto; primera llamada: pagina_eventos($pdo, 0)
```

Cambios de contrato que hay que defender ante producto:

- Se pierde «salta a la página 9000» y se gana «siguiente/anterior». Para saltos arbitrarios quedan las opciones caras: índice descendente + cursor por el final, o un buscador. La UX de scroll infinito encaja nativamente con cursores.
- El cursor es el último `id`; si el listado se ordenara por otra columna (fecha), el cursor compuesto `(fecha, id)` con tie-breaker por id es obligatorio: sin el id, dos filas con la misma fecha parten el cursor y se pierden/duplican filas.

Demostración de equivalencia (harness, 1000 filas; la página profunda 20ª de 50):

```sql
CREATE TABLE eventos (id INTEGER PRIMARY KEY, categoria TEXT NOT NULL, creado TEXT NOT NULL);
CREATE INDEX idx_eventos_cat ON eventos(categoria, id);
WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 1000)
INSERT INTO eventos (id, categoria, creado)
SELECT n,
       CASE WHEN n % 3 = 0 THEN 'pago' WHEN n % 3 = 1 THEN 'alta' ELSE 'baja' END,
       printf('2024-05-01 %02d:%02d:%02d', (n / 3600) % 24, (n / 60) % 60, n % 60)
  FROM seq;
SELECT COUNT(*) FROM eventos;
-- pagina profunda por OFFSET (recorre y descarta 995 filas):
SELECT id, categoria FROM eventos ORDER BY id LIMIT 5 OFFSET 995;
-- keyset: arranca en el ultimo id visto, coste constante:
SELECT id, categoria FROM eventos WHERE id > 995 ORDER BY id LIMIT 5;
```

Ambas consultas devuelven exactamente las mismas 5 filas (996..1000) — esa es la equivalencia que exige la migración — pero la segunda empieza a leer por el índice en el punto pedido. En MySQL con 1M de filas la diferencia es de segundos a milisegundos, y el plan de ejecución (`EXPLAIN`) deja de mostrar `Using where; Using index` con rangos gigantes.

Cómo comprobarlo: `php -l`; y en MySQL real, `EXPLAIN` de ambas variantes + comparación de tiempos en página 9000 antes/después.'''),
        ],
        verify=[
            {"name": "sintaxis_php", "action": "syntax", "lang": "php", "msg": -1, "block": 0},
            {"name": "sql_keyset_equivalente", "action": "sql", "lang": "sql", "msg": -1, "block": 1,
             "expect_stdout_contains": ["996|pago", "997|alta", "998|baja", "999|pago", "1000|alta"]},
        ],
        tags=["php", "paginacion", "keyset", "optimizacion", "sql"],
        stack=["php", "sql"],
        recovery=False,
    ),

    # ==================================================================
    # Java (18)
    # ==================================================================

    # Java 1 — Streams y Collectors: agregaciones de reporting deterministas
    E(
        language="java",
        domain="backend",
        subdomain="streams_agregaciones",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r'''Reporting de ventas en Java 21 (servicio batch, sin BD en este paso): a partir de una lista de ventas necesitamos (1) total facturado por vendedor, (2) el sku de mayor importe-alfabético por vendedor, (3) la lista de vendedores únicos ordenada como cadena, y (4) el resumen global (nº ventas y venta máxima). Los importes van en céntimos (int). Necesito un programa autocontenido cuyo resultado sea determinista entre ejecuciones (nada de orden de HashMap en la salida) y con los Collectors bien elegidos. Además: el equipo tuvo un `IllegalStateException: Duplicate key` la semana pasada usando toMap — explica por qué y cómo se evita.'''),
            ("assistant", r'''Programa completo, determinista: los mapas que se imprimen usan `TreeMap` como contenedor (orden estable), y `toMap` lleva SIEMPRE función de fusión:

```java
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.stream.Collectors;

public class Main {

    record Venta(String vendedor, String sku, int centavos) {}

    public static void main(String[] args) {
        List<Venta> ventas = List.of(
            new Venta("ana",  "A-100", 120_00),
            new Venta("luis", "B-220",  80_50),
            new Venta("ana",  "A-101",  45_25),
            new Venta("luis", "B-221", 210_00),
            new Venta("ana",  "A-100",  30_00),
            new Venta("mara", "C-300",  99_99));

        // (1) total por vendedor: groupingBy + down-stream summingInt
        Map<String, Integer> totales = ventas.stream().collect(
            Collectors.groupingBy(Venta::vendedor, TreeMap::new,
                                  Collectors.summingInt(Venta::centavos)));

        // (2) sku mayor por vendedor: toMap CON merge (hay claves repetidas)
        Map<String, String> skuMayor = ventas.stream().collect(
            Collectors.toMap(Venta::vendedor, Venta::sku,
                             (a, b) -> a.compareTo(b) >= 0 ? a : b, TreeMap::new));

        // (3) vendedores unicos ordenados, unidos en una cadena
        String vendedores = ventas.stream()
            .map(Venta::vendedor).distinct().sorted()
            .collect(Collectors.joining(", ", "[", "]"));

        // (4) resumen global
        var resumen = ventas.stream().collect(Collectors.summarizingInt(Venta::centavos));

        System.out.println("totales=" + totales);
        System.out.println("skuMayor=" + skuMayor);
        System.out.println("vendedores=" + vendedores);
        System.out.println("global=" + resumen.getCount() + " ventas, max=" + resumen.getMax());
    }
}
```

Sobre el `IllegalStateException: Duplicate key` de la semana pasada: `Collectors.toMap(clave, valor)` SIN tercer argumento lanza esa excepción en cuanto dos elementos comparten clave — es un contrato deliberado para que no pierdas datos por accidente. En nuestro caso `ana` aparece 3 veces: sin merge, el programa moriría. La regla del equipo debería ser: `toMap` sin merge solo cuando la unicidad de la clave está garantizada por el dominio (y anotado en un comentario); en cualquier otro caso, merge explícito (`(a, b) -> a`, o el que corresponda a la semántica de negocio) o `groupingBy` con un down-stream.

Cómo se comprueba (javac + java Main — en entornos sin toolchain queda como receta):

```
javac Main.java && java Main
totales={ana=19525, luis=29050, mara=9999}
skuMayor={ana=A-101, luis=B-221, mara=C-300}
vendedores=[ana, luis, mara]
global=6 ventas, max=21000
```

Comprobaciones mentales que hice antes de darlo por bueno: totales — ana 12000+4525+3000 = 19525; luis 8050+21000 = 29050; mara 9999. skuMayor — para ana, A-101 > A-100 lexicográficamente, y el merge conserva el mayor; max global 21000 (venta B-221 de luis). El `TreeMap::new` en ambos mapas es lo que congela el orden de impresión: con HashMap el programa sería correcto pero la salida podría variar entre JVMs, y un reporting determinista facilita los diffs de snapshots en CI.'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": [
                 "totales={ana=19525, luis=29050, mara=9999}",
                 "skuMayor={ana=A-101, luis=B-221, mara=C-300}",
                 "vendedores=[ana, luis, mara]",
                 "global=6 ventas, max=21000"]},
        ],
        tags=["java", "streams", "collectors", "tomap", "determinismo"],
        stack=["java"],
        recovery=False,
    ),

    # Java 2 — Optional bien usado: retorno, no campo
    E(
        language="java",
        domain="backend",
        subdomain="optional_retorno",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r'''Revisando el repositorio de clientes vimos Optional mal usado por todos lados: campos `Optional<Cliente> cliente` en entidades, parámetros `Optional<Long> id`, `Optional<List<Venta>>` para búsquedas, y llamadas con `.get()` desnudo. Nos pidieron una versión de referencia con las convenciones CORRECTAS de Optional (Java 21): dónde sí, dónde no, y composición con map/flatMap/orElseThrow. Programa autocontenido que lo demuestre con un repositorio en memoria.'''),
            ("assistant", r'''Reglas que fija este ejemplo (y el porqué):

1. Optional SOLO como TIPO DE RETORNO de métodos que «quizá no encuentran»: comunica la ausencia en la firma, sin javadoc.
2. NUNCA como campo ni parámetro: en campos rompe serialización/equals y no aporta nada que null ya hiciera; en parámetros multiplica sobrecargas — para «opcional» hay sobrecarga o builder.
3. NUNCA `Optional<List<...>>`: una lista vacía YA es la ausencia idiomática de resultados.
4. `.get()` sin `isPresent()` está vetado en revisión; usar `orElse`, `orElseGet` (cómputo perezoso) u `orElseThrow` (fallo de dominio explícito).

```java
import java.util.Map;
import java.util.Optional;

public class Main {

    record Cliente(long id, String email, boolean vip) {}

    static final class ClienteNoEncontrado extends RuntimeException {
        ClienteNoEncontrado(long id) { super("cliente " + id + " inexistente"); }
    }

    static final class ClienteRepository {
        private final Map<Long, Cliente> data;

        ClienteRepository(Map<Long, Cliente> data) { this.data = Map.copyOf(data); }

        Optional<Cliente> findById(long id) {
            return Optional.ofNullable(data.get(id));
        }

        /** Composicion: cada paso opera sobre el valor si existe. */
        Optional<String> emailNormalizado(long id) {
            return findById(id)
                    .map(Cliente::email)
                    .map(String::trim)
                    .map(String::toLowerCase);
        }

        /** El llamador exige la existencia: el fallo es de dominio, no un null. */
        Cliente requireById(long id) {
            return findById(id).orElseThrow(() -> new ClienteNoEncontrado(id));
        }
    }

    public static void main(String[] args) {
        ClienteRepository repo = new ClienteRepository(Map.of(
            1L, new Cliente(1, "  Ana@Acme.COM ", true),
            2L, new Cliente(2, "luis@acme.io", false)));

        System.out.println(repo.emailNormalizado(1).orElse("sin-email"));
        System.out.println(repo.emailNormalizado(99).orElse("sin-email"));
        try {
            repo.requireById(99);
        } catch (ClienteNoEncontrado e) {
            System.out.println("error: " + e.getMessage());
        }
        System.out.println("vip1=" + repo.findById(1).map(Cliente::vip).orElse(false));
    }
}
```

Puntos finos que suelen preguntarse en revisión: `orElse(...)` evalúa su argumento SIEMPRE (constantes o valores ya calculados); `orElseGet(() -> ...)` evalúa perezosamente (cómputos caros); `ofNullable` en la frontera con APIs que devuelven null, y NUNCA `Optional.of(null)` (NPE inmediata). La cadena `map` de `emailNormalizado` es la razón de ser del tipo: cada transformación expresa «si hay valor» sin un solo if.

Verificación esperada al compilar y ejecutar:

```
javac Main.java && java Main
ana@acme.com
sin-email
error: cliente 99 inexistente
vip1=true
```

Nota de portabilidad: `Map.of` no admite claves o valores null — para datos que puedan traer nulls usa HashMap construido a mano o Map.ofEntries con cuidado; el repositorio aquí copia inmutable (`Map.copyOf`) para asegurar que nadie lo muta por detrás.'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": [
                 "ana@acme.com", "sin-email", "error: cliente 99 inexistente", "vip1=true"]},
        ],
        tags=["java", "optional", "api-design", "records"],
        stack=["java"],
        recovery=False,
    ),

    # Java 3 — ExecutorService: shutdown correcto (graceful -> force)
    E(
        language="java",
        domain="backend",
        subdomain="executor_shutdown",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r'''Procesador por lotes del backoffice (Java 21): 12 tareas I/O simuladas, pool de 4 hilos. Requisitos del SRE: al terminar el lote el pool se cierra GRACEFULMENTE (acepta terminar las tareas en curso pero no acepta nuevas), con ruta de fuerza bruta por timeout (shutdownNow) y recolección ordenada de resultados. El equipo tuvo un servicio que «no terminaba nunca» porque nadie llamaba a shutdown — el código debe ser inmune a ese olvido. Programa autocontenido y determinista.'''),
            ("assistant", r'''El patrón canónico de ciclo de vida, con las dos etapas de apagado y el porqué de cada paso:

```java
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

public class Main {

    static String job(int id) {
        try {
            Thread.sleep(10 + (id % 4) * 10L);   // carga simulada, determinista por id
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();  // restaurar el flag: cortesia minima
            return "job-" + id + ":interrumpido";
        }
        return "job-" + id + ":ok";
    }

    public static void main(String[] args) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(4);
        List<Future<String>> futures = new ArrayList<>();
        try {
            for (int i = 1; i <= 12; i++) {
                final int id = i;
                futures.add(pool.submit(() -> job(id)));
            }
        } finally {
            pool.shutdown();                     // 1) no acepta tareas nuevas
            if (!pool.awaitTermination(5, TimeUnit.SECONDS)) {
                List<Runnable> pendientes = pool.shutdownNow();   // 2) interrumpe en curso
                System.out.println("pendientes al cortar: " + pendientes.size());
            }
        }
        for (Future<String> f : futures) {
            System.out.println(f.get());         // ya resueltas tras awaitTermination
        }
    }
}
```

Decisiones que el SRE exigirá poder defender:

- `shutdown()` antes que `shutdownNow()`: el primero drena (termina lo en curso, rechaza lo nuevo); el segundo interrumpe hilos. Forzar antes de esperar es cómo se pierden trabajos a medias.
- `awaitTermination` con timeout DA la señal para escalar a fuerza bruta; sin ese `if`, el `shutdownNow` nunca ocurre o ocurre siempre.
- `Thread.currentThread().interrupt()` en el catch: al tragarte la InterruptedException con solo return, el flag de interrupción desaparece y los marcos superiores no pueden reaccionar. Restaurar es obligación del que captura.
- ¿Por qué no `try-with-resources` con el pool? Desde Java 19 `ExecutorService` implementa `AutoCloseable` y `close()` hace shutdown+await INDEFINIDO — cómodo, pero sin ruta de timeout ni de fuerza bruta. Para un lote SRE, el patrón explícito de arriba da control fino; para scripts triviales, `try (pool) { ... }` es válido.
- Los resultados se leen DESPUÉS del apagado con `f.get()`: en ese punto cada Future está resuelto y `get()` no bloquea; el orden de impresión es el de envío (determinista), no el de finalización.

Verificación esperada (javac + java Main):

```
javac Main.java && java Main
job-1:ok
job-2:ok
...
job-12:ok
```

12 líneas `job-N:ok`, ninguna «interrumpido» (el timeout de 5 s sobra con estos sleeps — y eso en sí es una aserción: si un día una tarea cuelga, la línea «pendientes al cortar» aparece en el log y el lote no se queda colgado).'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": ["job-1:ok", "job-12:ok"],
             "expect_stdout_not_contains": ["interrumpido", "pendientes"]},
        ],
        tags=["java", "executorservice", "shutdown", "concurrencia"],
        stack=["java"],
        recovery=False,
    ),

    # Java 4 — ConcurrentHashMap + LongAdder: agregador de metricas sin locks globales
    E(
        language="java",
        domain="backend",
        subdomain="concurrenthashmap_metricas",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r'''Agregador de métricas en memoria (Java 21) para el gateway: 8 hilos de negocio incrementan contadores por tipo de evento; un hilo de reporting lee totales. La versión actual usa `HashMap` con `synchronized` en cada método y el throughput se desploma; además hubo incrementos perdidos antes de meter el synchronized. Necesito la versión con `ConcurrentHashMap` + `LongAdder`, sin locks globales, y que el hilo de reporting nunca vea estados imposibles. Programa autocontenido con 1000 eventos repartidos en 8 hilos y salida determinista.'''),
            ("assistant", r'''Tres piezas y su porqué:

1. `ConcurrentHashMap.computeIfAbsent(clave, k -> new LongAdder())`: crea-y-asigna atómico POR CLAVE. Es la versión concurrente del patrón `if (!map.containsKey(k)) map.put(k, new ...)` que en HashMap requiere lock global para no crear dos contadores.
2. `LongAdder` en vez de `AtomicLong`: divide el contador en celdas y solo las suma al leer; con escritura concurrente intensa y lecturas ocasionales (exactamente nuestro patrón métricas) gana por poco contention. `increment()` no devuelve el valor nuevo — si necesitas el valor por incremento, AtomicLong.
3. Nada de `synchronized` alrededor: el map está fragmentado internamente; lockear el objeto sería volver al cuello de botella.

```java
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.LongAdder;

public class Main {

    public static void main(String[] args) throws Exception {
        final int hilos = 8, eventos = 1000;
        Map<String, LongAdder> porTipo = new ConcurrentHashMap<>();
        LongAdder total = new LongAdder();

        ExecutorService pool = Executors.newFixedThreadPool(hilos);
        try {
            for (int t = 0; t < hilos; t++) {
                final int desde = t * eventos / hilos;
                final int hasta = (t + 1) * eventos / hilos;
                pool.submit(() -> {
                    for (int i = desde; i < hasta; i++) {
                        porTipo.computeIfAbsent("tipo-" + (i % 5), k -> new LongAdder()).increment();
                        total.increment();
                    }
                });
            }
        } finally {
            pool.shutdown();
            if (!pool.awaitTermination(10, TimeUnit.SECONDS)) {
                pool.shutdownNow();
            }
        }

        // snapshot ordenado para reporting (el mapa sigue vivo: se copia, no se recorre "en vivo" para informes)
        Map<String, Long> snapshot = new TreeMap<>();
        porTipo.forEach((k, v) -> snapshot.put(k, v.sum()));
        System.out.println("total=" + total.sum());
        System.out.println("porTipo=" + snapshot);
    }
}
```

Sobre «estados imposibles»: cada contador individual es exacto (LongAdder garantiza sum() consistente tras quiescencia); lo que NO se promete es un snapshot transversal atómico entre contadores — para reporting de dashboards eso basta; si un informe exigiera consistencia transversal total, la solución es un swap de referencias (publicar un mapa inmutable nuevo por ventana) o externalizar la agregación. Declararlo explícitamente es parte del diseño.

Por qué el HashMap+synchronized perdía incrementos ANTES del synchronized: la secuencia get-modify-put no es atómica; dos hilos leían el mismo valor y uno pisaba al otro. ConcurrentHashMap resuelve eso por micro-bloqueo por bucket, y el bug desaparece sin lock global.

Verificación esperada (javac + java Main):

```
javac Main.java && java Main
total=1000
porTipo={tipo-0=200, tipo-1=200, tipo-2=200, tipo-3=200, tipo-4=200}
```

Los 1000 eventos se reparten en rangos contiguos de 125 por hilo; 125 es múltiplo de 5, así que cada tipo recibe exactamente 200 incrementos — si un incremento se perdiera, el total o un tipo no daría 200 y la salida lo delataría: el propio programa es su test de carrera.'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": ["total=1000", "tipo-0=200", "tipo-2=200", "tipo-4=200"]},
        ],
        tags=["java", "concurrenthashmap", "longadder", "concurrencia", "metricas"],
        stack=["java"],
        recovery=False,
    ),

    # Java 5 — CompletableFuture: composicion, timeout y degradacion
    E(
        language="java",
        domain="backend",
        subdomain="completablefuture_timeout",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r'''Orquestador de fichas de producto (Java 21): la ficha combina el servicio de precios y el de stock. Reglas: si precios tarda >100 ms se sirve el valor de caché («precios-cache»); si stock falla, la ficha se publica igual con «stock-indispuesto». Primera versión del compañero: llamaba a `join()` dentro de tareas del MISMO pool y se bloqueaba; y usaba `get()` sin timeout. Necesito la versión con CompletableFuture: composición sin bloquear hilos del pool, timeout por tarea y fallback por fallo, con executor dedicado y apagado correcto. Simulaciones deterministas, salida fija.'''),
            ("assistant", r'''Reconstrucción con las tres garantías: (1) ningún `join()` dentro de tareas del pool — la composición encadena callbacks, no bloquea hilos; (2) `completeOnTimeout` aporta el valor de cache si la tarea no llega; (3) `exceptionally` degrada el fallo de stock. El pool es propio y se apaga en finally.

```java
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class Main {

    static final ExecutorService pool = Executors.newFixedThreadPool(4);

    static CompletableFuture<String> servicio(String nombre, long millis, String respuesta) {
        return CompletableFuture.supplyAsync(() -> {
            try {
                Thread.sleep(millis);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new CompletionException(e);
            }
            return respuesta;
        }, pool);
    }

    static CompletableFuture<String> stockQueFalla() {
        return CompletableFuture.supplyAsync(() -> {
            throw new IllegalStateException("fallo del servicio de stock");
        }, pool).exceptionally(e -> "stock-indispuesto");
    }

    public static void main(String[] args) {
        try {
            // Escenario 1: ambos a tiempo
            CompletableFuture<String> p1 = servicio("precios", 20, "precios-v1");
            CompletableFuture<String> s1 = servicio("stock", 30, "stock-v1");
            System.out.println(p1.thenCombine(s1, (p, s) -> "ficha[" + p + "+" + s + "]").join());

            // Escenario 2: precios tarda 500 ms -> el timeout de 100 ms aporta la cache
            CompletableFuture<String> p2 = servicio("precios", 500, "precios-v1")
                    .completeOnTimeout("precios-cache", 100);
            CompletableFuture<String> s2 = servicio("stock", 30, "stock-v1");
            System.out.println(p2.thenCombine(s2, (p, s) -> "ficha[" + p + "+" + s + "]").join());

            // Escenario 3: stock falla -> degradacion controlada
            CompletableFuture<String> p3 = servicio("precios", 20, "precios-v1");
            System.out.println(p3.thenCombine(stockQueFalla(),
                    (p, s) -> "ficha[" + p + "+" + s + "]").join());
        } finally {
            pool.shutdown();
        }
    }
}
```

Notas de diseño que responden al incidente del compañero:

- `join()` en el HILO PRINCIPAL está bien (es el punto de sincronización final); `join()` DENTRO de una tarea del pool puede agotar todos los hilos esperando a tareas que nunca arrancan (thread starvation). La composición correcta usa thenCombine/thenCompose y solo bloquea al final, fuera del pool.
- `completeOnTimeout(valor, timeout)` vs `orTimeout(timeout)`: el primero sustituye el resultado por un default (degradación); el segundo completa excepcionalmente (fallo duro). Elegimos por escenario: cache para precios, excepción-fallback para stock.
- La tarea «lenta» del escenario 2 sigue corriendo tras el timeout: el timeout completa el FUTURO, no mata la tarea. Con servicios reales, el cancel verdadero es un efecto del cliente HTTP; aquí el pool la deja terminar y el JVM sale sin colgarse.
- `exceptionally` captura el fallo y entrega un valor: el error se maneja donde importa y el tipo del futuro sigue siendo String.
- Alternativa moderna: `CompletableFuture.completedFuture` para caminos cortocircuitados y virtual threads (Java 21) si el orquestador crece; el patrón de composición no cambia.

Verificación esperada (javac + java Main):

```
javac Main.java && java Main
ficha[precios-v1+stock-v1]
ficha[precios-cache+stock-v1]
ficha[precios-v1+stock-indispuesto]
```

Los tres escenarios ejercitan camino feliz, timeout y fallo: si mañana alguien mete un join() dentro del pool, el escenario 2 se cuelga y el test (timeout externo de CI) lo detecta.'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": [
                 "ficha[precios-v1+stock-v1]",
                 "ficha[precios-cache+stock-v1]",
                 "ficha[precios-v1+stock-indispuesto]"]},
        ],
        tags=["java", "completablefuture", "timeout", "concurrencia", "fallback"],
        stack=["java"],
        recovery=True,
    ),

    # Java 6 — java.net.http.HttpClient contra servidor local (smoke test autocontenido)
    E(
        language="java",
        domain="web",
        subdomain="httpclient_local",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r'''Smoke test autocontenido (Java 21, sin dependencias) para la API de órdenes: levanta un servidor HTTP mínimo en localhost con `com.sun.net.httpserver`, y con `java.net.http.HttpClient` comprueba: GET /health → 200 con `{"status":"ok"}`; POST /ordenes con sku → 201; POST /ordenes sin sku → 422; método no permitido → 405. Al terminar, el servidor debe detenerse SIEMPRE (también si una aserción falla). Puerto efímero para no chocar con CI.'''),
            ("assistant", r'''Servidor y cliente en el mismo proceso: el servidor escucha en un puerto efímero (puerto 0), el test lee el puerto real de `server.getAddress()` y el `finally` garantiza el stop.

```java
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.Executors;

public class Main {

    static void responderJson(com.sun.net.httpserver.HttpExchange ex, int status, String json)
            throws IOException {
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(status, body.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(body);
        }
    }

    public static void main(String[] args) throws IOException, InterruptedException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/health", ex -> responderJson(ex, 200, "{\"status\":\"ok\"}"));
        server.createContext("/ordenes", ex -> {
            if (!"POST".equals(ex.getRequestMethod())) {
                ex.getResponseHeaders().set("Allow", "POST");
                ex.sendResponseHeaders(405, -1);          // -1: sin cuerpo
                return;
            }
            String req = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            if (req.contains("\"sku\"")) {
                responderJson(ex, 201, "{\"aceptada\":true}");
            } else {
                responderJson(ex, 422, "{\"error\":\"sku ausente\"}");
            }
        });
        server.setExecutor(Executors.newFixedThreadPool(2));
        server.start();

        HttpClient client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .build();
        try {
            int port = server.getAddress().getPort();
            HttpResponse<String> health = client.send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/health")).GET().build(),
                HttpResponse.BodyHandlers.ofString());
            System.out.println("health=" + health.statusCode() + " " + health.body());

            HttpResponse<String> orden = client.send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/ordenes"))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString("{\"sku\":\"A-100\",\"cantidad\":2}"))
                    .build(),
                HttpResponse.BodyHandlers.ofString());
            System.out.println("orden=" + orden.statusCode() + " " + orden.body());

            HttpResponse<String> mala = client.send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/ordenes"))
                    .POST(HttpRequest.BodyPublishers.ofString("{}"))
                    .build(),
                HttpResponse.BodyHandlers.ofString());
            System.out.println("mala=" + mala.statusCode() + " " + mala.body());
        } finally {
            server.stop(0);
            System.out.println("servidor detenido");
        }
    }
}
```

Puntos que el test fija y por qué:

- `new InetSocketAddress("127.0.0.1", 0)`: el SO asigna puerto libre — en CI con ejecución paralela evita `BindException`. El cliente nunca escribe el puerto a mano: lo lee del server.
- `sendResponseHeaders(405, -1)`: la convención de la librería para respuestas SIN cuerpo (cualquier length < 0). Con 0 sería cuerpo vacío con chunked.
- El cliente lleva `connectTimeout`: sin él, un puerto cerrado cuelga el test hasta el timeout global de CI, con peor diagnóstico.
- `finally { server.stop(0) }`: aunque una comparación lance, el puerto se libera. `stop(0)` corta en seco; con tareas en vuelo usar `stop(delay)`.
- El manejo de JSON es contains a propósito (el test no debe depender de una librería): lo que se verifica es el CONTRATO HTTP (status + cuerpo), no el parser.

Verificación esperada (javac + java Main):

```
javac Main.java && java Main
health=200 {"status":"ok"}
orden=201 {"aceptada":true}
mala=422 {"error":"sku ausente"}
servidor detenido
```

Nota de módulo: `com.sun.net.httpserver` vive en el módulo JDK `jdk.httpserver`, presente en cualquier JDK estándar — no requiere flags ni dependencias.'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": [
                 "health=200 {\"status\":\"ok\"}",
                 "orden=201 {\"aceptada\":true}",
                 "mala=422 {\"error\":\"sku ausente\"}",
                 "servidor detenido"]},
        ],
        tags=["java", "httpclient", "httpserver", "smoke-test", "json"],
        stack=["java"],
        recovery=False,
    ),

    # Java 7 — Records + sealed + pattern matching para eventos de orden
    E(
        language="java",
        domain="architecture",
        subdomain="sealed_eventos",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r'''El procesador de eventos de órdenes del ERP (Java 21) usa `String tipo` + if/else con casts; cada evento nuevo se olvida en una rama y el compilador no puede ayudar. Piden la versión con jerarquía sellada: eventos Creada (ordenId, sku, cantidad), Pagada (ordenId, monto BigDecimal) y Cancelada (ordenId, motivo); un método que produzca la descripción con switch sobre patrones, deconstrucción de records y guardas (`when`), exhaustivo SIN default (para que añadir un evento futuro rompa la compilación en todos los switch). Programa autocontenido.'''),
            ("assistant", r'''Los tres mecanismos y qué compran:

- `sealed interface EventoOrden permits Creada, Pagada, Cancelada`: el conjunto de subtipos es CERRADO y conocido por el compilador.
- `record` para cada evento: datos inmutables + accessors + equals/hashCode sin cerillas.
- `switch` con patrones + `when`: deconstruye el record y filtra; sin cláusula `default`, el compilador OBLIGA a cubrir cada subtipo — el «evento nuevo olvidado» deja de existir.

```java
import java.math.BigDecimal;
import java.util.List;

public class Main {

    sealed interface EventoOrden permits Creada, Pagada, Cancelada {}
    record Creada(long ordenId, String sku, int cantidad) implements EventoOrden {}
    record Pagada(long ordenId, BigDecimal monto) implements EventoOrden {}
    record Cancelada(long ordenId, String motivo) implements EventoOrden {}

    static String procesar(EventoOrden e) {
        return switch (e) {
            case Creada(long id, String sku, int qty) when qty > 0 ->
                "orden " + id + " creada: " + sku + " x" + qty;
            case Creada c ->
                "orden " + c.ordenId() + " rechazada: cantidad no positiva";
            case Pagada(long id, BigDecimal monto) ->
                "orden " + id + " pagada: " + monto.toPlainString();
            case Cancelada(long id, String motivo) ->
                "orden " + id + " cancelada: " + motivo;
        };
    }

    public static void main(String[] args) {
        List<EventoOrden> eventos = List.of(
            new Creada(1001, "A-100", 2),
            new Creada(1002, "B-220", 0),
            new Pagada(1001, new BigDecimal("149.90")),
            new Cancelada(1002, "sin stock"));
        eventos.stream().map(Main::procesar).forEach(System.out::println);
    }
}
```

Decisiones finas:

- Orden de casos: la variante con guarda (`when qty > 0`) va PRIMERO; el `case Creada c` posterior atrapa el resto (cantidad <= 0). Si se invirtieran, el segundo caso sería inalcanzable y el compilador lo marca como error.
- `case Creada c` en vez de deconstrucción cuando los campos no se usan: legibilidad; la deconstrucción `Pagada(long id, BigDecimal monto)` solo se usa cuando los componentes importan.
- `BigDecimal` para dinero y `toPlainString()` para no heredar notación científica del `toString()` en montos grandes.
- El switch es una EXPRESIÓN: cada rama produce el String; sin `default`, la exhaustividad es verificada por el compilador gracias al `sealed`. Añadir mañana `record Devuelta(...)` produce errores de compilación en CADA switch no actualizado — esa es la propiedad que se compró.

Verificación esperada (javac + java Main):

```
javac Main.java && java Main
orden 1001 creada: A-100 x2
orden 1002 rechazada: cantidad no positiva
orden 1001 pagada: 149.90
orden 1002 cancelada: sin stock
```

Nota de versión: records y pattern matching para switch son definitivos desde Java 21 (JEP 440/441); en Java 17 el switch con patrones era preview y no debe usarse en producción sin `--enable-preview`.'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": [
                 "orden 1001 creada: A-100 x2",
                 "orden 1002 rechazada: cantidad no positiva",
                 "orden 1001 pagada: 149.90",
                 "orden 1002 cancelada: sin stock"]},
        ],
        tags=["java", "sealed", "records", "pattern-matching", "java21"],
        stack=["java"],
        recovery=False,
    ),

    # Java 8 — Files.walk con try-with-resources y ruta segura
    E(
        language="java",
        domain="backend",
        subdomain="files_walk_seguro",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r'''Carga de inventario (Java 21): recorrer un directorio de volúmenes CSV, contar ficheros y sumar la columna `stock` de cada uno. Requisitos de seguridad del equipo de plataforma: ninguna lectura fuera del directorio base (aunque nos pasen rutas relativas con `..`), el stream de `Files.walk` debe cerrarse SIEMPRE (es lazy y contiene un descriptor de fichero), y las líneas en blanco no deben romper el parseo. Programa autocontenido que cree su propio árbol temporal de prueba y demuestre el bloqueo de rutas externas.'''),
            ("assistant", r'''Dos cuidados dominan el ejemplo: el ciclo de vida del Stream (try-with-resources: `Files.walk` abre un DirectoryStream perezoso; sin close, fuga de file descriptors) y la validación de rutas (resolve + normalize + startsWith, el patrón que anula el `../`).

```java
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Stream;

public class Main {

    /** Suma la columna stock de un CSV relativo al directorio base. */
    static long sumaCsv(Path base, Path relativo) throws IOException {
        Path objetivo = base.resolve(relativo).normalize();
        if (!objetivo.startsWith(base)) {
            throw new IOException("ruta fuera del directorio base: " + relativo);
        }
        try (Stream<String> lineas = Files.lines(objetivo)) {
            return lineas.skip(1)                      // cabecera
                    .filter(l -> !l.isBlank())
                    .mapToLong(l -> Long.parseLong(l.split(",")[1]))
                    .sum();
        }
    }

    public static void main(String[] args) throws Exception {
        Path base = Files.createTempDirectory("inventario");
        Files.write(base.resolve("tornilleria.csv"), List.of("sku,stock", "T-1,10", "T-2,25"));
        Files.createDirectories(base.resolve("anexos"));
        Files.write(base.resolve("anexos/herrajes.csv"),
                List.of("sku,stock", "H-1,7", "H-2,3", "", "H-3,5"));

        try (Stream<Path> arbol = Files.walk(base)) {  // SIEMPRE con recursos: stream lazy
            long ficheros = arbol.filter(p -> Files.isRegularFile(p) && p.toString().endsWith(".csv"))
                    .count();
            System.out.println("ficheros csv=" + ficheros);
        }

        long total = sumaCsv(base, Path.of("tornilleria.csv"))
                   + sumaCsv(base, Path.of("anexos/herrajes.csv"));
        System.out.println("stock total=" + total);

        try {
            sumaCsv(base, Path.of("../fuera.csv"));    // intento de traversal
        } catch (IOException e) {
            System.out.println("bloqueada: " + e.getMessage());
        }
    }
}
```

Detalles de seguridad y robustez que se piden en revisión:

- `base.resolve(relativo).normalize()` y luego `startsWith(base)`: `../fuera.csv` normaliza a un path hermano del base y queda fuera → IOException. `normalize()` es OBLIGATORIO: sin él, `startsWith` compara componentes literales y `base/../x` empieza «por» base solo en apariencia. Ojo también con el caso límite del propio base (`base` vs `baseSecundaria`: startsWith compara por componentes, no por prefijo de caracteres — justamente por eso es el método correcto).
- `Files.lines` y `Files.walk` son streams CON recursos subyacentes: el try-with-resources no es opcional. `Files.walk` por defecto NO sigue enlaces simbólicos, lo que evita bucles con symlinks.
- `isBlank()` absorbe la línea vacía del CSV real; `skip(1)` asume cabecera — con CSV de proveedores sin cabecera, ese skip es un bug y se detecta en el primer volumen.
- `createTempDirectory` para el demo: el test no toca rutas del repo ni dependen de una fixture externa.

Verificación esperada (javac + java Main):

```
javac Main.java && java Main
ficheros csv=2
stock total=50
bloqueada: ruta fuera del directorio base: ../fuera.csv
```

Cálculos: tornilleria 10+25 = 35; herrajes 7+3+5 = 15 (la línea en blanco se filtra); total 50. Si el bloqueo de traversal no saltara, la salida faltaría y el test de plataforma fallaría.'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": ["ficheros csv=2", "stock total=50", "bloqueada: ruta fuera"]},
        ],
        tags=["java", "nio", "files", "path-traversal", "try-with-resources"],
        stack=["java"],
        recovery=False,
    ),

    # Java 9 — Testing: servicio de descuentos con reloj inyectado (sin framework)
    E(
        language="java",
        domain="backend",
        subdomain="pruebas_reloj_inyectado",
        difficulty="hard",
        task_type="testing",
        messages=[
            ("user", r'''El servicio de descuentos del checkout (Java 21) tiene una regla de campaña que depende de la FECHA («10% en enero») y otra de fidelidad («15% para vip, no acumulable con campaña: gana la mayor»). Los tests actuales fallan cada febrero porque la lógica lee `LocalDate.now()` internamente. Restricciones del build: sin JUnit/Mockito disponibles en este módulo. Diseña las pruebas como programa autocontenido determinista y explica la decisión de diseño que elimina la dependencia del reloj.'''),
            ("assistant", r'''La decisión de diseño ANTES del test: la dependencia temporal es una dependencia como cualquier otra — se INYECTA. Una interfaz funcional `Reloj` (o `Supplier<LocalDate>`) sustituye a `LocalDate.now()` y convierte «febrero rompe los tests» en «el tiempo es un parámetro del test».

```java
import java.time.LocalDate;

public class Main {

    interface Reloj {
        LocalDate hoy();
    }

    static final class DescuentoService {
        private final Reloj reloj;

        DescuentoService(Reloj reloj) { this.reloj = reloj; }

        /** 10% en campanas de enero; 15% para vip; no acumulables: gana el mayor. */
        int descuento(int precioCentavos, boolean vip) {
            if (precioCentavos <= 0) {
                throw new IllegalArgumentException("precio invalido");
            }
            int pct = 0;
            if (reloj.hoy().getMonthValue() == 1) {
                pct = 10;
            }
            if (vip && pct < 15) {
                pct = 15;
            }
            return precioCentavos * pct / 100;
        }
    }

    static int fallos = 0;

    static void check(boolean cond, String nombre) {
        System.out.println((cond ? "PASS " : "FAIL ") + nombre);
        if (!cond) {
            fallos++;
        }
    }

    public static void main(String[] args) {
        Reloj enero = () -> LocalDate.of(2024, 1, 15);
        Reloj marzo = () -> LocalDate.of(2024, 3, 15);
        DescuentoService enEnero = new DescuentoService(enero);
        DescuentoService enMarzo = new DescuentoService(marzo);

        check(enEnero.descuento(10_000, false) == 1_000, "campana enero 10%");
        check(enMarzo.descuento(10_000, false) == 0, "sin campana 0%");
        check(enMarzo.descuento(10_000, true) == 1_500, "vip 15% fuera de campana");
        check(enEnero.descuento(10_000, true) == 1_500, "vip no acumula con campana");
        try {
            enMarzo.descuento(0, false);
            check(false, "precio 0 lanza");
        } catch (IllegalArgumentException e) {
            check(true, "precio 0 lanza");
        }

        System.out.println("fallos=" + fallos);
        if (fallos > 0) {
            System.exit(1);
        }
    }
}
```

Lo que cada caso fija (y por qué existe):

- «campana enero 10%» y «sin campana 0%»: la regla temporal en SUS dos lados, con fechas fijas — determinista cualquier día del año.
- «vip no acumula»: el caso que el requisito marca explícitamente (gana el mayor). Sin ese caso, un refactor bien intencionado puede sumar 10+15.
- «precio 0 lanza»: el contrato de errores es parte del API, no un detalle.
- `System.exit(1)` con fallos > 0: el código de salida es la señal de CI; sin framework, el runner son 15 líneas.

Extensión natural: con JUnit serían `@ParameterizedTest` con fechas como parámetros; si la producción puede usar `java.time.Clock`, inyecta `Clock` directamente (tiene `instant()`/`fixed(...)`) y la interfaz propia solo hace falta cuando se quiere desacoplar del tipo JDK. Lo que NO se hace: `LocalDate.now()` dentro del servicio — cada prueba del pasado lo demuestra.

Verificación esperada (javac + java Main):

```
javac Main.java && java Main
PASS campana enero 10%
PASS sin campana 0%
PASS vip 15% fuera de campana
PASS vip no acumula con campana
PASS precio 0 lanza
fallos=0
```

y código de salida 0 (en CI, distinto de 0 marca el job en rojo).'''),
        ],
        verify=[
            {"name": "compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": ["PASS campana enero 10%", "PASS vip no acumula con campana", "fallos=0"],
             "expect_stdout_not_contains": ["FAIL"]},
        ],
        tags=["java", "testing", "inyeccion-dependencias", "determinismo"],
        stack=["java"],
        recovery=False,
    ),

    # Java 10 — Debugging: contrato equals/hashCode roto (HashSet que «no encuentra»)
    E(
        language="java",
        domain="backend",
        subdomain="equals_hashcode",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", r'''Bug del sprint en el módulo de etiquetas del CRM: un HashSet contiene un elemento pero `contains()` dice que no. El código (reducido, reproduce el fenómeno):

```java
import java.util.HashSet;
import java.util.Set;

public class Main {
    static final class Etiqueta {
        final String nombre;
        Etiqueta(String nombre) { this.nombre = nombre; }

        @Override public boolean equals(Object o) {
            return o instanceof Etiqueta e && e.nombre.equals(nombre);
        }
        // hashCode: no lo sobreescribimos porque "equals ya es correcto"
    }

    public static void main(String[] args) {
        Set<Etiqueta> activas = new HashSet<>();
        activas.add(new Etiqueta(" Urgente ".trim()));
        System.out.println(activas.contains(new Etiqueta("Urgente")));  // esperabamos true
    }
}
```

Mi primera impresión fue que el `.trim()` no hacía lo que creíamos, pero no encaja del todo.'''),
            ("tool", r'''Transcripción de referencia (JDK 21), la reproducción y el experimento que descarta la primera hipótesis:

```
$ javac Main.java && java Main
false
$ jshell -q
jshell> " Urgente ".trim().equals("Urgente")
$1 ==> true
jshell> var a = new Main.Etiqueta("Urgente"); var b = new Main.Etiqueta("Urgente");
jshell> a.equals(b)
$2 ==> true
jshell> System.identityHashCode(a) + " / " + System.identityHashCode(b)
$3 ==> "1735600054 / 216856739"
```'''),
            ("assistant", r'''Tu primera hipótesis muere con evidencia: `trim().equals(...)` da true — el problema no es el contenido del string.

**Hipótesis 2 (la buena): equals está bien, hashCode no existe.** El HashSet funciona por buckets: primero llama a `hashCode()` para decidir EN QUÉ cubeta buscar, y solo dentro de esa cubeta usa `equals()`. Sin override, `Etiqueta` hereda `Object.hashCode()` — el identity hash —, así que dos instancias «iguales» caen en cubetas distintas y `equals` jamás llega a ejecutarse. El experimento 3 lo hace visible: identity hashcodes distintos.

El CONTRATO (Object.hashCode): si `a.equals(b)` entonces `a.hashCode() == b.hashCode()`. Lo contrario no se exige (colisiones legales). Romper la primera mitad rompe silenciosamente HashMap, HashSet, Hashtable y LinkedHashMap: el código compila, los tests «pasan» si comparas con la misma instancia, y falla solo con instancias nuevas — el peor tipo de bug.

Corrección recomendada: para clases de VALOR, record — el compilador genera equals/hashCode consistentes:

```java
import java.util.HashSet;
import java.util.Set;

public class Main {

    record Etiqueta(String nombre) {
        Etiqueta {
            nombre = nombre.trim();   // constructor compacto: normaliza al crear
        }
    }

    public static void main(String[] args) {
        Set<Etiqueta> activas = new HashSet<>();
        activas.add(new Etiqueta(" Urgente "));
        System.out.println("contiene=" + activas.contains(new Etiqueta("Urgente")));
        System.out.println("unicas=" + activas.size());
    }
}
```

Si la clase no puede ser record (herencia, campos mutables), el override manual es `@Override public int hashCode() { return Objects.hash(nombre); }` — nunca `nombre.hashCode()` a pelo con más campos de los que equals compara, y jamás un hashCode «creativo» que use solo algunos de los campos de equals.

Dos reglas que este bug deja grabadas:

- **Inmutabilidad en claves de colecciones**: si un campo que participa en hashCode se muta DESPUÉS de insertar, el elemento queda en la cubeta equivocada: `contains` falso para siempre. Records inmutables eliminan esa clase de error.
- Añadir el campo al equals sin tocar el hashCode (o al revés) es el mismo bug con otro traje: los dos métodos se mantienen SIEMPRE juntos, y un test como el de arriba (inserta instancia nueva, busca otra instancia nueva) lo fija.

Verificación esperada (javac + java Main):

```
javac Main.java && java Main
contiene=true
unicas=1
```'''),
        ],
        verify=[
            {"name": "bug_reproducido", "action": "compile_run", "lang": "java", "msg": 1, "block": 0,
             "filename": "Main.java", "expect_stdout_contains": ["false"]},
            {"name": "fix_compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": ["contiene=true", "unicas=1"],
             "expect_stdout_not_contains": ["false"]},
        ],
        tags=["java", "equals", "hashcode", "hashset", "records"],
        stack=["java"],
        recovery=True,
    ),

    # Java 11 — Debugging: ConcurrentModificationException (fail-fast, no concurrencia)
    E(
        language="java",
        domain="backend",
        subdomain="concurrent_modification",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r'''La limpieza de inventario agotado del ERP lanza `ConcurrentModificationException` en producción. Lo curioso: es un hilo, un solo flujo, ni un Executor en el módulo. Código:

```java
import java.util.ArrayList;
import java.util.List;

public class Main {
    record Articulo(String sku, int stock) {}

    public static void main(String[] args) {
        List<Articulo> inventario = new ArrayList<>(List.of(
            new Articulo("A-1", 0),
            new Articulo("B-2", 5),
            new Articulo("C-3", 0)));
        for (Articulo a : inventario) {
            if (a.stock() == 0) {
                inventario.remove(a);   // dar de baja lo agotado
            }
        }
        System.out.println(inventario.size());
    }
}
```'''),
            ("tool", r'''Transcripción de referencia (JDK 21):

```
$ javac Main.java && java Main
Exception in thread "main" java.util.ConcurrentModificationException
        at java.base/java.util.ArrayList$Itr.checkForComodification(ArrayList.java:1096)
        at java.base/java.util.ArrayList$Itr.next(ArrayList.java:1050)
        at Main.main(Main.java:12)
```'''),
            ("assistant", r'''Primera hipótesis (la que sugiere el nombre): condición de carrera. Descartada con el propio código: un hilo, ningún pool. La CME aquí NO es concurrencia: es el mecanismo **fail-fast** del iterador.

Mecanismo: el ArrayList lleva un contador `modCount` de modificaciones estructurales. El iterador lo fotografía al crearse y lo re-verifica en cada `next()`. Nuestro for-each usa ese iterador; `inventario.remove(a)` (fuera del iterador) incrementa modCount, y el siguiente `next()` detecta la divergencia y lanza CME. Es una detección a-best-effort de un bug de diseño, no una protección.

Nota siniestra que vale saber: el for-each sobre ArrayList que elimina el PENÚLTIMO elemento a veces NO lanza (el `hasNext` compara cursor==size y da falso justo después del remove) — el mismo código puede «funcionar» durante meses y explotar cuando la lista cambia de tamaño. Nunca confíes en que pasar los tests prueba que el patrón es correcto.

Corrección (tres variantes legítimas, de simple a específica):

```java
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

public class Main {
    record Articulo(String sku, int stock) {}

    public static void main(String[] args) {
        List<Articulo> inventario = new ArrayList<>(List.of(
            new Articulo("A-1", 0),
            new Articulo("B-2", 5),
            new Articulo("C-3", 0)));

        // Variante A: removeIf (la idiomática desde Java 8)
        inventario.removeIf(a -> a.stock() == 0);

        // Variante B (si necesitas logica por elemento): iterador y SU remove
        // Iterator<Articulo> it = inventario.iterator();
        // while (it.hasNext()) {
        //     if (it.next().stock() == 0) {
        //         it.remove();            // remove DEL iterador: actualiza modCount honestamente
        //     }
        // }

        System.out.println("quedan=" + inventario.size());
        System.out.println(inventario.get(0).sku());
    }
}
```

Y dos trampas relacionadas que conviene tener en el radar del equipo:

- `list.remove(int)` vs `list.remove(Object)`: con `List<Integer>`, `remove(1)` borra el ÍNDICE 1, no el valor 1. Con genéricos de referencia el compilador te avisa; con boxing y casts manuales, no.
- Si la colección se comparte entre hilos (no es este caso): removeIf no arregla carreras; ahí toca CopyOnWriteArrayList o locking real, y aceptar su coste de copia.

Verificación esperada:

```
# codigo original: crash con CME (exit != 0) — es la reproducion del bug
$ javac Main.java && java Main    # ConcurrentModificationException
# codigo corregido:
$ javac Main.java && java Main
quedan=1
B-2
```'''),
        ],
        verify=[
            {"name": "bug_reproducido_cme", "action": "compile_run", "lang": "java", "msg": 1, "block": 0,
             "filename": "Main.java", "expect_fail": True},
            {"name": "fix_compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": ["quedan=1", "B-2"]},
        ],
        tags=["java", "concurrentmodificationexception", "fail-fast", "colecciones"],
        stack=["java"],
        recovery=True,
    ),

    # Java 12 — Debugging: autoboxing y la cache de Integer (== sobre wrappers)
    E(
        language="java",
        domain="backend",
        subdomain="autoboxing_cache",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r'''El cache de sesiones del gateway guarda `Map<Integer, String>`; para ids pequeños funciona, para ids altos devuelve «miss» aunque la entrada exista. El código escanea las claves a mano:

```java
import java.util.HashMap;
import java.util.Map;

public class Main {
    public static void main(String[] args) {
        Map<Integer, String> cache = new HashMap<>();
        for (int i = 100; i <= 130; i++) {
            cache.put(i, "sesion-" + i);
        }
        Integer buscado = 128;
        for (Integer clave : cache.keySet()) {
            if (clave == buscado) {          // comparacion de referencias
                System.out.println("hit " + cache.get(clave));
                return;
            }
        }
        System.out.println("miss");
    }
}
```

En pruebas con id 100 y 105 funciona; en producción (ids > 127) no. No encuentro el patrón.'''),
            ("tool", r'''Transcripción de referencia (JDK 21), reprodución y aislamiento del fenómeno:

```
$ javac Main.java && java Main
miss
$ jshell -q
jshell> Integer a = 100, b = 100;
jshell> Integer c = 1000, d = 1000;
jshell> System.out.println((a == b) + " " + (c == d))
true false
jshell> var cache = new HashMap<Integer, String>();
jshell> cache.put(128, "sesion-128");
jshell> cache.size() + " / " + cache.get(128)
$1 ==> "1 / sesion-128"
```'''),
            ("assistant", r'''El experimento 3 es el que descarta la hipótesis obvia («el HashMap pierde entradas»): `size()==1` y `get(128)` devuelven la sesión — el mapa está bien. El bug es la línea `clave == buscado`.

**Causa raíz — la cache de boxing.** El autoboxing de `int` a `Integer` NO crea siempre un objeto nuevo: para valores entre -128 y 127 (extensible con `-XX:AutoBoxCacheMax`), el JVM reutiliza instancias de una cache. Consecuencia: `a == b` con 100 es true POR ACCIDENTE (misma instancia cacheada); con 1000, instancias distintas → false. `==` sobre wrappers compara REFERENCIAS, y la cache hace que el bug sea intermitente exactamente en el rango de pruebas — el peor escenario posible para detectarlo.

El experimento 4 muestra que `cache.get(128)` FUNCIONA: HashMap internamente usa `equals()` (y el hashCode de Integer). Es decir, la solución es no escanear a mano:

```java
import java.util.HashMap;
import java.util.Map;

public class Main {
    public static void main(String[] args) {
        Map<Integer, String> cache = new HashMap<>();
        for (int i = 100; i <= 130; i++) {
            cache.put(i, "sesion-" + i);      // boxing int->Integer al insertar
        }
        Integer buscado = 128;

        String sesion = cache.get(buscado);   // get() usa equals(): correcto siempre
        System.out.println(sesion != null ? "hit " + sesion : "miss");
        System.out.println("contains=" + cache.containsKey(128));
        System.out.println("equals=" + buscado.equals(Integer.valueOf(128)));
    }
}
```

Si el escaneo fuera imprescindible (no lo es aquí), la comparación correcta entre wrappers es `clave.equals(buscado)` o `clave.intValue() == buscado.intValue()` — y si mezclas wrappers y primitivos en una expresión, cuidado con el DESBOXING: el clásico `cond ? boxedLong : primitiveLong` desboxe el boxed y lanza NPE si es null.

Reglas que salen del incidente:

- `==` con wrappers: vetado en revisión, sin excepciones «porque con ids pequeños va bien».
- `Integer` cache: es JLS §5.1.7 (garantizado para -128..127); fuera de ahí, comportamiento dependiente de flags — nunca construir lógica sobre ello.
- Dónde SÍ aparece `==` legítimo: enums, comparación de referencia intencionada, o después de un `unbox` explícito.

Verificación esperada:

```
# codigo original: imprime "miss" (bug, exit 0 — por eso no lo pillaba nadie)
$ java Main
miss
# codigo corregido:
$ java Main
hit sesion-128
contains=true
equals=true
```'''),
        ],
        verify=[
            {"name": "bug_reproducido", "action": "compile_run", "lang": "java", "msg": 1, "block": 0,
             "filename": "Main.java", "expect_stdout_contains": ["miss"]},
            {"name": "fix_compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": ["hit sesion-128", "contains=true", "equals=true"],
             "expect_stdout_not_contains": ["miss"]},
        ],
        tags=["java", "autoboxing", "integer-cache", "equals", "debugging"],
        stack=["java"],
        recovery=True,
    ),

    # Java 13 — Debugging: excepciones suprimidas y el anti-patron finally-return
    E(
        language="java",
        domain="backend",
        subdomain="excepciones_suprimidas",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", r'''El importador de facturas reporta errores imposibles de diagnosticar: cuando falla el cierre del canal, el mensaje que llega a soporte es «cierre fallido» y SE PIERDE el error real de lectura; a veces el error desaparece por completo. Código simplificado (la clase Canal simula recursos reales que pueden fallar al leer y al cerrar):

```java
import java.io.IOException;

public class Main {

    static class Canal implements AutoCloseable {
        private final String nombre;
        private final boolean fallarLectura;
        Canal(String nombre, boolean fallarLectura) {
            this.nombre = nombre;
            this.fallarLectura = fallarLectura;
        }
        String leer() throws IOException {
            if (fallarLectura) {
                throw new IOException("lectura fallida en " + nombre);
            }
            return "dato";
        }
        @Override public void close() throws IOException {
            throw new IOException("cierre fallido en " + nombre);
        }
    }

    static String procesar() {
        try {
            Canal c = new Canal("entrada", true);
            try {
                return c.leer();
            } finally {
                c.close();     // "aseguramos" el cierre a mano
            }
        } catch (IOException e) {
            return "error: " + e.getMessage();
        }
    }

    public static void main(String[] args) {
        System.out.println(procesar());
    }
}
```'''),
            ("tool", r'''Transcripción de referencia (JDK 21):

```
$ javac Main.java && java Main
error: cierre fallido en entrada
```

El mensaje REAL era «lectura fallida en entrada» (la lectura sí falló primero) — no aparece por ningún lado. En los logs del importador hay cientos de «cierre fallido» sin causa primaria.'''),
            ("assistant", r'''Causa raíz: cuando el cuerpo (`c.leer()`) lanza Y el `close()` del finally lanza, la segunda excepción REEMPLAZA a la primera en un try manual. La primera ni se loguea ni se encadena: desaparece. Es exactamente el escenario para el que existe try-with-resources: el compilador genera el cierre, y si el cuerpo y el cierre fallan a la vez, la excepción del CUERPO es la primaria y la del cierre se adjunta como SUPRIMIDA (`getSuppressed()`).

Corrección:

```java
import java.io.IOException;

public class Main {

    static class Canal implements AutoCloseable {
        private final String nombre;
        private final boolean fallarLectura;

        Canal(String nombre, boolean fallarLectura) {
            this.nombre = nombre;
            this.fallarLectura = fallarLectura;
        }

        String leer() throws IOException {
            if (fallarLectura) {
                throw new IOException("lectura fallida en " + nombre);
            }
            return "dato";
        }

        @Override public void close() throws IOException {
            throw new IOException("cierre fallido en " + nombre);
        }
    }

    static String procesar() {
        try (Canal c = new Canal("entrada", true)) {   // el close lo orquesta el lenguaje
            return c.leer();
        } catch (IOException e) {
            StringBuilder sb = new StringBuilder("error: " + e.getMessage());
            for (Throwable s : e.getSuppressed()) {
                sb.append(" | suprimido: ").append(s.getMessage());
            }
            return sb.toString();
        }
    }

    /** Demo del anti-patron hermano: finally con return traga TODO. */
    @SuppressWarnings("finally")
    static int antiPatron() {
        try {
            throw new IllegalStateException("fallo grave");
        } finally {
            return 42;    // el return del finally descarta la excepcion: nunca llega al llamador
        }
    }

    public static void main(String[] args) {
        System.out.println(procesar());
        System.out.println("antiPatron=" + antiPatron());
    }
}
```

Lo que fija el ejemplo:

- **Orden de cierre**: try-with-resources cierra en orden INVERSO de declaración y ANTES del catch — por eso la primaria es la del cuerpo y no la del cierre. Tu hipótesis inicial («el orden de los cierres no afecta al resultado») era la contraria: el orden afecta exactamente a esto.
- **Nunca `return` (ni `throw`) en finally**: sustituye el resultado normal o anormal del bloque; en este caso el `IllegalStateException` «fallo grave» se evapora y el método devuelve 42. javac lo avisa (finally no completa normalmente) pero no lo prohibe — la revisión de código sí.
- Los recursos null en try-with-resources están permitidos (se omiten del cierre); si el constructor lanza, el recurso ni se crea — el lenguaje maneja los bordes que el finally manual hace mal.
- Regla práctica para soporte: si un log dice «cierre fallido» sin causa primaria, busca un try/finally manual cerca.

Verificación esperada:

```
# codigo original: solo la excepcion del close — la primaria se perdio
$ java Main
error: cierre fallido en entrada
# codigo corregido: primaria + suprimida, y el anti-patron documentado
$ java Main
error: lectura fallida en entrada | suprimido: cierre fallido en entrada
antiPatron=42
```'''),
        ],
        verify=[
            {"name": "bug_reproducido", "action": "compile_run", "lang": "java", "msg": 1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": ["cierre fallido en entrada"],
             "expect_stdout_not_contains": ["lectura fallida"]},
            {"name": "fix_compila_y_ejecuta", "action": "compile_run", "lang": "java", "msg": -1, "block": 0,
             "filename": "Main.java",
             "expect_stdout_contains": [
                 "error: lectura fallida en entrada | suprimido: cierre fallido en entrada",
                 "antiPatron=42"]},
        ],
        tags=["java", "try-with-resources", "suppressed-exceptions", "finally", "debugging"],
        stack=["java"],
        recovery=True,
    ),
# __APPEND_7__
]
