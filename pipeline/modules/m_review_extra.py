"""
m_review_extra.py — Tarea 4-e-bis del dataset AI-ku_programming (Stack V2).

8 ejemplos de code review y testing en español (identificadores en inglés):

  * CODE REVIEW (5): código realista 40-90 líneas con problemas sembrados; el
    assistant distingue explícitamente BUG demostrado por ejecución de
    preferencia estilística, prioriza por severidad y entrega fix.
    c(2) con ASan/LSan y trazas reales de gcc, javascript(1) con node,
    bash(1) con flock/pipefail, java(1) estático y honesto (sin afirmar
    ejecución).
  * TESTING (3): suites para funciones proporcionadas con casos límite:
    c con mini-framework de asserts (gcc -fsanitize=address), python con
    unittest.main(), javascript con mini-harness node + ronda TDD roja
    (expect_fail) y verde (expect_exit 0).

Verificación por ejecución real: gcc 14 + ASan/LSan, node v24, python 3.12.
Sin red, sin input(), determinista. recovery=True en los ejemplos donde se
demuestra recuperación tras una hipótesis fallida.
"""

from schema import E

EXAMPLES = [

    # =====================================================================
    # CR1 — c: parser de configuración con fuga de memoria y overflow (extreme)
    # =====================================================================
    E(
        language="c", domain="systems", subdomain="revision_parser_config",
        difficulty="extreme", task_type="code_review",
        messages=[
            ("user", r"""Revisión previa a fusión de `config_tool.c` v0.9, el cargador de configuración del servicio de pagos (lee pares `clave=valor`; se re-ejecuta en cada SIGHUP de reconfigura). QA reporta que la build de release muere de forma intermitente al cargar el DSN completo y `valgrind` nunca se termina de integrar en CI.

```c
#define _GNU_SOURCE
/* config_tool.c v0.9 — CLI que carga la config del servicio de pagos */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_ENTRIES 64
#define LINE_MAX    32

typedef struct { char *key; char *value; } Entry;

typedef struct {
    Entry entries[MAX_ENTRIES];
    int   count;
} Config;

static void config_set(Config *cfg, const char *key, const char *value) {
    for (int i = 0; i < cfg->count; i++) {
        if (strcmp(cfg->entries[i].key, key) == 0) {
            cfg->entries[i].value = strdup(value);   /* reemplazo de valor */
            return;
        }
    }
    cfg->entries[cfg->count].key = strdup(key);
    cfg->entries[cfg->count].value = strdup(value);
    cfg->count++;
}

static void config_load(Config *cfg, const char *text) {
    char line[LINE_MAX];
    long offset = 0;
    while (sscanf(text + offset, "%[^\n]", line) == 1) {
        offset += (long)strlen(line) + 1;
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        config_set(cfg, line, eq + 1);
    }
}

static void config_dump(const Config *cfg) {
    for (int i = 0; i < cfg->count; i++)
        printf("%s=%s\n", cfg->entries[i].key, cfg->entries[i].value);
}

int main(void) {
    Config cfg = {0};

    /* config base del servicio */
    config_load(&cfg,
        "host=localhost\n"
        "port=5432\n"
        "host=127.0.0.1\n"     /* misma clave tras cambio de DNS */
        "retries=3\n");
    config_dump(&cfg);

    /* config completa: QA anade la cadena de conexion larga */
    config_load(&cfg,
        "dsn=postgres://svc_user@10.0.0.9:5432/ventas?sslmode=require\n");
    config_dump(&cfg);
    return 0;
}
```

Encuentra los problemas reales, priorízalos por severidad y marca explícitamente cuáles son bugs demostrables y cuáles solo preferencias de estilo. Si puedes demostrarlo, demuéstralo."""),
            ("assistant", r"""Revisión priorizada por severidad. Cada hallazgo va marcado como **BUG** (comportamiento incorrecto demostrable) o **ESTILO** (no cambia el comportamiento), y distingo lo demostrado por ejecución de lo detectado por inspección.

**Recuperación de hipótesis:** mi primera lectura apuntaba al array `entries` de `config_set` como fuente del desbordamiento. La instrumentación con ASan/LSan del bloque inferior mostró dos evidencias distintas y me obligó a recalcular: el desbordamiento demostrable está en el `%[^\n]` **sin ancho** de `config_load`, y la fuga está en la sobrescritura de `value` en `config_set`. Reordeno en consecuencia.

**S1 — BUG crítico: desbordamiento de pila en `config_load` (demostrado por ejecución).** `char line[32]` con `sscanf(text + offset, "%[^\n]", line)`: la conversión `%[^\n]` no lleva ancho de campo, así que `sscanf` escribe la línea COMPLETA en el buffer. El DSN de QA mide 61 bytes: 61 bytes sobre un buffer de 32. Con `-fsanitize=address` el programa aborta con `WRITE of size 61` sobre `'line'` (traza real abajo); en mi entorno, la misma build sin sanitizer muere con SIGSEGV (`exit 139`) en el mismo punto — corromper la pila de un servicio que re-carga config por señal es inyectable en la práctica.

**S2 — BUG alto: fuga de memoria en cada sobrescritura (demostrado por ejecución).** En `config_set`, el reemplazo hace `cfg->entries[i].value = strdup(value)` sin `free` del valor anterior. La comprobación intermedia con LSan lo señala inequívocamente: `Direct leak of 10 byte(s) ... config_set` (el `"localhost"` original, huérfano). El servicio re-carga config en cada SIGHUP y cada clave repetida filtra su valor: crecimiento lineal con las reconfiguras, en un proceso de larga vida.

**S3 — BUG medio (inspección, no disparado en la traza): `config_set` no comprueba `MAX_ENTRIES`.** Con la 65.ª clave distinta escribe fuera de `entries[MAX_ENTRIES]`: desbordamiento del array contenedor, de la misma familia que S1. El repro usa 5 claves y no lo alcanza; lo corrijo en el parche aunque no esté en la traza, y lo etiqueto como hallazgo por inspección, no por ejecución.

**S4 — BUG bajo (inspección): una línea vacía aborta el parseo en silencio.** Ante `\n\n`, `sscanf` no matchea nada y devuelve 0; el `while (sscanf(...) == 1)` termina y el resto del fichero se ignora. Ningún config actual lo dispara, pero el contrato de "cargar el fichero" se rompe sin error.

**S5 — ESTILO (no bloqueante):** `LINE_MAX 32` mezcla "tamaño de línea" con "tamaño de clave", y `Entry`/`Config` sin tag de struct es cuestión de convención del repo. Arreglarlo no cambia el comportamiento; lo separo explícitamente de S1-S4 para que nadie bloquee la fusión por S5.

Repro determinista: copia literal del módulo con una única instrumentación — comprobación de fugas con LSan en mitad de ejecución (antes de tocar la línea larga) bajo `#ifdef __SANITIZE_ADDRESS__`:

```c
#define _GNU_SOURCE
/* repro_config.c — copia de config_tool.c v0.9 + comprobacion LSan intermedia.
 * Sin cambios semanticos respecto al modulo revisado. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __SANITIZE_ADDRESS__
#include <sanitizer/lsan_interface.h>
#endif

#define MAX_ENTRIES 64
#define LINE_MAX    32

typedef struct { char *key; char *value; } Entry;

typedef struct {
    Entry entries[MAX_ENTRIES];
    int   count;
} Config;

static void config_set(Config *cfg, const char *key, const char *value) {
    for (int i = 0; i < cfg->count; i++) {
        if (strcmp(cfg->entries[i].key, key) == 0) {
            cfg->entries[i].value = strdup(value);
            return;
        }
    }
    cfg->entries[cfg->count].key = strdup(key);
    cfg->entries[cfg->count].value = strdup(value);
    cfg->count++;
}

static void config_load(Config *cfg, const char *text) {
    char line[LINE_MAX];
    long offset = 0;
    while (sscanf(text + offset, "%[^\n]", line) == 1) {
        offset += (long)strlen(line) + 1;
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = '\0';
        config_set(cfg, line, eq + 1);
    }
}

int main(void) {
    Config cfg = {0};
    config_load(&cfg,
        "host=localhost\n"
        "port=5432\n"
        "host=127.0.0.1\n"
        "retries=3\n");
#ifdef __SANITIZE_ADDRESS__
    /* Solo bajo ASan: informa de fugas NO alcanzables sin abortar. */
    if (__lsan_do_recoverable_leak_check())
        fprintf(stderr, "[lsan] fuga confirmada antes de tocar la linea larga\n");
#endif
    config_load(&cfg,
        "dsn=postgres://svc_user@10.0.0.9:5432/ventas?sslmode=require\n");
    printf("config completa cargada: %d entradas\n", cfg.count);
    return 0;
}
```"""),
            ("tool", r"""$ gcc -g -o config_tool config_tool.c
$ ./config_tool
$ echo $?
139
$ gcc -fsanitize=address -g -o repro_config repro_config.c
$ ./repro_config

=================================================================
==21734==ERROR: LeakSanitizer: detected memory leaks

Direct leak of 10 byte(s) in 1 object(s) allocated from:
    #0 0x7fca85ef2d60 in strdup
    #1 0x55cad452e40a in config_set
    #2 0x55cad452e5a0 in config_load
    #3 0x55cad452e778 in main

SUMMARY: AddressSanitizer: 10 byte(s) leaked in 1 allocation(s).
[lsan] fuga confirmada antes de tocar la linea larga
=================================================================
==21734==ERROR: AddressSanitizer: stack-buffer-overflow on address 0x7fca83a000c0 at pc 0x7fca85e90c05
WRITE of size 61 at 0x7fca83a000c0 thread T0
    #0 0x7fca85e90c04 in scanf_common
    #1 0x7fca85ecb67f in __isoc99_vsscanf
    #2 0x7fca85ecf091 in __isoc99_sscanf
    #3 0x55cad452e5d0 in config_load
    #4 0x55cad452e8fc in main

Address 0x7fca83a000c0 is located in stack of thread T0 at offset 64 in frame
    #0 0x55cad452e481 in config_load
  This frame has 1 object(s):
    [32, 64) 'line' <== Memory access at offset 64 overflows this variable

SUMMARY: AddressSanitizer: stack-buffer-overflow in config_load
==21734==ABORTING
$ echo $?
1

(se omiten los frames del runtime y las lineas de shadow bytes de ambos informes)"""),
            ("assistant", r"""Causa raíz y parche.

**Causa raíz de S1:** `sscanf("%[^\n]")` sin ancho de campo nunca respeta el tamaño del buffer destino; el desbordamiento no depende del contenido "maligno", basta una línea de 32+ bytes — que QA ya genera con el DSN. **Causa raíz de S2:** el patrón "asignar sobre el puntero sin liberar el anterior" — un leak por cada clave repetida en cada re-carga.

Parche v1.0 (resuelve S1-S4; el parseo línea a línea con límite explícito sustituye al `sscanf` truncado, `config_set` libera el valor anterior y comprueba la capacidad, y una línea demasiado larga ahora es un error declarado, no un desbordamiento):

```c
#define _GNU_SOURCE
/* config_tool.c v1.0 — lectura de pares clave=valor (revision aplicada) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_ENTRIES 64
#define LINE_MAX    256

typedef struct { char *key; char *value; } Entry;

typedef struct {
    Entry entries[MAX_ENTRIES];
    int   count;
} Config;

static char *xstrndup(const char *src, size_t max) {
    size_t n = strnlen(src, max);
    char *copy = malloc(n + 1);
    if (!copy) return NULL;
    memcpy(copy, src, n);
    copy[n] = '\0';
    return copy;
}

static int config_set(Config *cfg, const char *key, const char *value) {
    for (int i = 0; i < cfg->count; i++) {
        if (strcmp(cfg->entries[i].key, key) == 0) {
            char *nuevo = xstrndup(value, LINE_MAX);
            if (!nuevo) return -1;
            free(cfg->entries[i].value);       /* S2: liberar el valor anterior */
            cfg->entries[i].value = nuevo;
            return 0;
        }
    }
    if (cfg->count >= MAX_ENTRIES) return -1;  /* S3: tabla llena -> error, no silencio */
    char *k = xstrndup(key, LINE_MAX), *v = xstrndup(value, LINE_MAX);
    if (!k || !v) { free(k); free(v); return -1; }
    cfg->entries[cfg->count].key = k;
    cfg->entries[cfg->count].value = v;
    cfg->count++;
    return 0;
}

/* S1: parseo acotado, una linea por iteracion, con longitud verificada. */
static int config_load(Config *cfg, const char *text) {
    const char *p = text;
    char line[LINE_MAX];
    while (*p) {
        const char *nl = strchr(p, '\n');
        size_t len = nl ? (size_t)(nl - p) : strlen(p);
        if (len >= sizeof line) return -1;     /* linea demasiado larga: error explicito */
        memcpy(line, p, len);
        line[len] = '\0';
        char *eq = strchr(line, '=');
        if (eq && eq != line) {                /* S4: sin '=' se ignora la linea; vacia tambien */
            *eq = '\0';
            if (config_set(cfg, line, eq + 1) != 0) return -1;
        }
        p += len;
        if (*p == '\n') p++;
    }
    return 0;
}

void config_free(Config *cfg) {
    for (int i = 0; i < cfg->count; i++) {
        free(cfg->entries[i].key);
        free(cfg->entries[i].value);
    }
    cfg->count = 0;
}

int main(void) {
    Config cfg = {0};
    if (config_load(&cfg,
            "host=localhost\n"
            "port=5432\n"
            "host=127.0.0.1\n"
            "retries=3\n"
            "dsn=postgres://svc_user@10.0.0.9:5432/ventas?sslmode=require\n") != 0) {
        fprintf(stderr, "config invalido\n");
        config_free(&cfg);
        return 1;
    }
    for (int i = 0; i < cfg.count; i++)
        printf("%s=%s\n", cfg.entries[i].key, cfg.entries[i].value);
    config_free(&cfg);                         /* S2: sin fugas al salir */
    printf("OK config cargado y liberado\n");
    return 0;
}
```

Dos notas de verificación: (1) la salida limpia con `exit 0` bajo `-fsanitize=address` no solo prueba S1/S3 — LSan corre al salir por defecto y convertiría cualquier fuga residual en `exit != 0`, así que un 0 también acredita S2; (2) la alternativa mínima `sscanf(..., "%31[^\n]", line)` habría acotado el desbordamiento, pero sigue truncando en silencio y mantiene el fallo de línea vacía de S4; prefiero el parseo explícito. S5 queda para un PR de estilo separado."""),
        ],
        verify=[
            {"name": "repro_fuga_y_overflow", "action": "compile_run", "lang": "c",
             "msg": 2, "block": 0, "cargs": ["-fsanitize=address", "-g"],
             "expect_fail": True,
             "expect_stdout_contains": ["LeakSanitizer", "stack-buffer-overflow"],
             "timeout_s": 20},
            {"name": "fix_limpio_bajo_asan", "action": "compile_run", "lang": "c",
             "msg": -1, "block": 0, "cargs": ["-fsanitize=address", "-g"],
             "expect_exit": 0, "expect_stdout_contains": ["OK config cargado y liberado"],
             "timeout_s": 20},
        ],
        tags=["code_review", "buffer_overflow", "memory_leak", "asan", "sscanf"],
        stack=["c", "gcc", "asan"],
        recovery=True,
    ),

    # =====================================================================
    # CR2 — c: CLI de despliegue con stdio roto alrededor de fork (hard)
    # =====================================================================
    E(
        language="c", domain="tooling", subdomain="revision_cli_logging_fork",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", r"""Revisión del CLI de despliegue `deploy_cli.c` v1.8. Síntomas en producción: el log de auditoría `deploy_cli.log` a veces tiene líneas repetidas y a veces faltan líneas (la auditoría de compliance nos exige una línea exacta por paso). No hay hilos en el proceso; sí hay `fork()` para los pasos de migración e invalidación de caché.

```c
/* deploy_cli.c v1.8 — CLI de despliegue: migraciones + invalidacion de cache.
 * Registro de auditoria: deploy_cli.log, una linea por paso. */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>

static FILE *g_log;

static void log_line(const char *msg) {
    fprintf(g_log, "%s\n", msg);
}

static int run_migrator(void) {
    pid_t pid = fork();
    if (pid == 0) {
        log_line("migrator: 12 esquemas aplicados");
        exit(0);                        /* el hijo termina por exit: vuelve SU copia */
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 1;
}

static int run_cache_flush(void) {
    pid_t pid = fork();
    if (pid == 0) {
        log_line("cache: invalidada por release 2.4.1");
        _exit(0);                       /* el hijo sale por _exit */
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 1;
}

int main(void) {
    g_log = fopen("deploy_cli.log", "w");
    if (!g_log) { perror("fopen"); return 2; }

    log_line("deploy: inicio, version=2.4.1");
    if (run_migrator() != 0) { log_line("deploy: migraciones fallidas"); return 1; }
    log_line("deploy: healthcheck 200 OK");
    if (run_cache_flush() != 0) { log_line("deploy: cache sin invalidar"); return 1; }
    log_line("deploy: fin correcto");
    return 0;
}
```

Necesito la causa raíz demostrada y el parche; el fichero de auditoría no admite "a veces"."""),
            ("assistant", r"""Revisión priorizada. Marco **BUG** lo demostrable por ejecución y **ESTILO** lo que no cambia el comportamiento.

**Recuperación de hipótesis:** partí sospechando de una carrera clásica de `fprintf` entre procesos (escrituras entrelazadas). Al verificarla encontré dos cosas que me hicieron corregir el diagnóstico: (1) en glibc, `fprintf` sí es thread-safe por llamada — el internal locking de `FILE*` hace que una llamada completa no se interleave; (2) la ejecución del repro muestra que la corrupción real del log nace del **buffering de stdio alrededor de `fork()`**, con dos manifestaciones opuestas y deterministas: duplicación y pérdida. La "carrera" está entre los buffers duplicados del padre y del hijo sobre la misma descripción de fichero, no dentro de `fprintf`.

**S1 — BUG alto: buffer heredado por el hijo que sale con `exit` → línea duplicada (demostrado).** `deploy_cli.log` es un fichero regular → stdio usa buffering completo (bloques de 4096). Al hacer `fork`, el hijo hereda una **copia** del buffer de `g_log` que aún contiene `"deploy: inicio..."` sin vaciar. El hijo del migrador escribe su línea y sale por `exit(0)` → vuelca SU copia: `"inicio"` + `"migrator..."`. El padre sigue con su copia y al final vuelca la suya: `"inicio"` otra vez. Resultado: la línea de inicio aparece **dos veces** (log real abajo). POSIX lo prevé: tras `fork`, el hijo que use los streams debe hacerlo después de un `fflush` del padre o vaciar con disciplina propia.

**S2 — BUG alto: `_exit` sin vaciar → línea perdida (demostrado).** El hijo del flush de caché sale con `_exit(0)`, que no ejecuta el vaciado de salida de `exit`. Su línea `"cache: invalidada..."` muere en el buffer copiado y **no aparece nunca** en el log (log real abajo). La auditoría pierde exactamente el paso que compliance exige registrar.

**S3 — BUG medio (inspección): sin `fclose` ni comprobación de errores de escritura.** En la salida normal, `return` de `main` → `exit()` vacía el stream y el síntoma no se ve; pero en cualquier salida anormal (un `return 1` del propio CLI tras "migraciones fallidas", un `_exit` futuro, o un error real de disco) el buffer final se pierde sin diagnóstico. Además `fprintf` devuelve `-1` en error y el código no lo comprueba: un log en un volumen lleno falla en silencio. La pérdida de S2 es la demostración ejecutada de esta familia; el resto se corrige por inspección.

**S4 — ESTILO (no bloqueante):** `g_log` global frente a pasar el `FILE*` por parámetro, y la falta de niveles/timestamp en `log_line`. No cambia el comportamiento observado; lo dejo fuera del parche mínimo.

Repro determinista (copia del módulo + autocomprobación: cada una de las 5 líneas esperadas debe aparecer exactamente una vez):

```c
/* repro_deploy.c — copia de deploy_cli.c v1.8 + autocomprobacion del log.
 * Sin cambios semanticos: reproduce duplicacion y perdida de forma fija. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>

static FILE *g_log;

static void log_line(const char *msg) {
    fprintf(g_log, "%s\n", msg);
}

static int run_migrator(void) {
    pid_t pid = fork();
    if (pid == 0) {
        log_line("migrator: 12 esquemas aplicados");
        exit(0);                        /* exit normal: vuelve SU copia del buffer */
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 1;
}

static int run_cache_flush(void) {
    pid_t pid = fork();
    if (pid == 0) {
        log_line("cache: invalidada por release 2.4.1");
        _exit(0);                       /* _exit: descarta SU copia del buffer */
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 1;
}

int main(void) {
    g_log = fopen("deploy_cli.log", "w");
    if (!g_log) { perror("fopen"); return 2; }

    log_line("deploy: inicio, version=2.4.1");
    if (run_migrator() != 0) { log_line("deploy: migraciones fallidas"); return 1; }
    log_line("deploy: healthcheck 200 OK");
    if (run_cache_flush() != 0) { log_line("deploy: cache sin invalidar"); return 1; }
    log_line("deploy: fin correcto");

    /* Instrumentacion de la autocomprobacion: fuerza el vuelco que el fclose
     * ausente haria en la salida normal. Sin esto, las lineas pendientes del
     * padre no llegarian al fichero antes de medir. */
    fflush(g_log);

    /* autocomprobacion: 5 lineas esperadas, exactamente una vez cada una */
    static const char *esperadas[5] = {
        "deploy: inicio, version=2.4.1",
        "migrator: 12 esquemas aplicados",
        "deploy: healthcheck 200 OK",
        "cache: invalidada por release 2.4.1",
        "deploy: fin correcto",
    };
    int contadas[5] = {0};
    char buf[256];
    FILE *check = fopen("deploy_cli.log", "r");
    if (!check) { perror("reapertura"); return 2; }
    while (fgets(buf, sizeof buf, check)) {
        buf[strcspn(buf, "\n")] = '\0';
        for (int i = 0; i < 5; i++)
            if (strcmp(buf, esperadas[i]) == 0) contadas[i]++;
    }
    fclose(check);
    int anomalies = 0;
    for (int i = 0; i < 5; i++)
        if (contadas[i] != 1) {
            printf("ANOMALIA: '%s' aparece %d veces (esperado 1)\n", esperadas[i], contadas[i]);
            anomalies++;
        }
    return anomalies == 0 ? 0 : 1;
}
```"""),
            ("tool", r"""$ gcc -g -o repro_deploy repro_deploy.c
$ ./repro_deploy
ANOMALIA: 'deploy: inicio, version=2.4.1' aparece 2 veces (esperado 1)
ANOMALIA: 'cache: invalidada por release 2.4.1' aparece 0 veces (esperado 1)
$ echo $?
1
$ cat deploy_cli.log
deploy: inicio, version=2.4.1
migrator: 12 esquemas aplicados
deploy: inicio, version=2.4.1
deploy: healthcheck 200 OK
deploy: fin correcto

(5 lineas: 'inicio' duplicada por el vuelco del buffer del hijo del migrador;
 'cache: invalidada...' desaparecida con el _exit del segundo hijo)"""),
            ("assistant", r"""Causa raíz y parche.

**Causa raíz única, dos manifestaciones:** el buffering completo de stdio no está coordinado con `fork`. El hijo hereda una copia del buffer pendiente; si el hijo sale por `exit` la vuelca (duplicado del contenido ya pendiente en el padre), si sale por `_exit` la descarta (pérdida de lo que el hijo escribió). El parche fija la disciplina: **buffer vacío antes de `fork`** y **vaciado explícito en el hijo antes de `_exit`**; además se comprueba `fprintf`/`fclose` (S3).

Parche v1.9 (mantiene la autocomprobación, ahora debe salir limpia):

```c
/* deploy_cli.c v1.9 — CLI de despliegue con log seguro ante fork (revision aplicada) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>

static FILE *g_log;

static void log_line(const char *msg) {
    if (fprintf(g_log, "%s\n", msg) < 0) {   /* S3: un fallo de escritura no es silencioso */
        perror("fprintf");
        exit(2);
    }
}

static void fork_checked(pid_t *out_pid) {
    fflush(g_log);                           /* S1/S2: buffer vacio ANTES de bifurcar */
    *out_pid = fork();
    if (*out_pid == -1) { perror("fork"); exit(2); }
}

static int run_migrator(void) {
    pid_t pid;
    fork_checked(&pid);
    if (pid == 0) {
        log_line("migrator: 12 esquemas aplicados");
        fflush(NULL);                        /* S2: vacia TODOS los streams abiertos */
        _exit(0);                            /* _exit legitimo: no re-ejecuta atexit del padre */
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 1;
}

static int run_cache_flush(void) {
    pid_t pid;
    fork_checked(&pid);
    if (pid == 0) {
        log_line("cache: invalidada por release 2.4.1");
        fflush(NULL);
        _exit(0);
    }
    int status = 0;
    waitpid(pid, &status, 0);
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 1;
}

int main(void) {
    g_log = fopen("deploy_cli.log", "w");
    if (!g_log) { perror("fopen"); return 2; }

    log_line("deploy: inicio, version=2.4.1");
    if (run_migrator() != 0) { log_line("deploy: migraciones fallidas"); return 1; }
    log_line("deploy: healthcheck 200 OK");
    if (run_cache_flush() != 0) { log_line("deploy: cache sin invalidar"); return 1; }
    log_line("deploy: fin correcto");
    if (fclose(g_log) != 0) {                /* S3: fclose es quien reporta errores de disco */
        perror("fclose");
        return 2;
    }

    /* autocomprobacion: 5 lineas esperadas, exactamente una vez cada una */
    static const char *esperadas[5] = {
        "deploy: inicio, version=2.4.1",
        "migrator: 12 esquemas aplicados",
        "deploy: healthcheck 200 OK",
        "cache: invalidada por release 2.4.1",
        "deploy: fin correcto",
    };
    int contadas[5] = {0};
    char buf[256];
    FILE *check = fopen("deploy_cli.log", "r");
    if (!check) { perror("reapertura"); return 2; }
    while (fgets(buf, sizeof buf, check)) {
        buf[strcspn(buf, "\n")] = '\0';
        for (int i = 0; i < 5; i++)
            if (strcmp(buf, esperadas[i]) == 0) contadas[i]++;
    }
    fclose(check);
    int anomalies = 0;
    for (int i = 0; i < 5; i++)
        if (contadas[i] != 1) {
            printf("ANOMALIA: '%s' aparece %d veces (esperado 1)\n", esperadas[i], contadas[i]);
            anomalies++;
        }
    if (anomalies == 0) printf("OK log integro: 5 lineas, sin duplicados ni perdidas\n");
    return anomalies == 0 ? 0 : 1;
}
```

Nota para el equipo: si el log pasara a ser compartido con otros procesos (no solo hijos de este), `fflush`-disciplina no basta y la respuesta correcta es `O_APPEND` + líneas `< PIPE_BUF` (atómicas en pipes; en ficheros regulares `O_APPEND` garantiza el offset, no la atomicidad del contenido), o migrar el audit log a un syslog condda un socket dedicado. Para el caso actual (padre e hijos del mismo proceso), el parche de arriba es completo."""),
        ],
        verify=[
            {"name": "repro_log_corrupto", "action": "compile_run", "lang": "c",
             "msg": 2, "block": 0, "expect_fail": True,
             "expect_stdout_contains": ["ANOMALIA", "aparece 2 veces"],
             "timeout_s": 20},
            {"name": "fix_log_integro", "action": "compile_run", "lang": "c",
             "msg": -1, "block": 0, "expect_exit": 0,
             "expect_stdout_contains": ["OK log integro"],
             "timeout_s": 20},
        ],
        tags=["code_review", "fork", "stdio", "posix", "audit_log"],
        stack=["c", "posix"],
        recovery=True,
    ),

    # =====================================================================
    # CR3 — javascript: cache TTL con fuga de memoria y carrera async (very_hard)
    # =====================================================================
    E(
        language="javascript", domain="backend", subdomain="revision_cache_ttl",
        difficulty="very_hard", task_type="code_review",
        messages=[
            ("user", r"""Revisión de `cache.js` v1.6, la caché TTL del catálogo (Node 24, un proceso por pod). Dos síntomas del on-call: (1) la memoria del pod crece sin llegar al límite declarado de 100 entradas — Prometheus dice rss creciente y el límite `maxEntries` parece decorativo; (2) en horas punta el backend de catálogo recibe el doble de peticiones por SKU caliente, como si dos clientes compitieran por la misma clave.

```js
'use strict';
// cache.js v1.6 — cache TTL para catalogo

class CacheTTL {
  constructor({ ttlMs = 5000, maxEntries = 100, now = () => Date.now() } = {}) {
    this.ttlMs = ttlMs;
    this.maxEntries = maxEntries;
    this._now = now;
    this._data = new Map();           // key -> { value, storedAt }
  }

  get(key) {
    const item = this._data.get(key);
    if (!item) return undefined;
    if (this._now() - item.storedAt > this.ttlMs) {
      this._data.delete(key);         // caducidad al leer
      return undefined;
    }
    return item.value;
  }

  set(key, value) {
    this._data.set(key, { value, storedAt: this._now() });
  }

  async getOrLoad(key, loader) {
    const cached = this.get(key);
    if (cached !== undefined) return cached;
    const value = await loader(key);  // carga desde el backend
    this.set(key, value);
    return value;
  }

  size() {
    return this._data.size;
  }
}

module.exports = { CacheTTL };
```

Encuentra los problemas reales, priorízalos, distingue bugs demostrables de preferencias de estilo y entrega el fix. El reloj es inyectable (`now`) para que la demo sea determinista."""),
            ("assistant", r"""Revisión priorizada. **BUG** = demostrable con un repro determinista; **ESTILO** = no cambia el comportamiento.

**Recuperación de hipótesis:** mi primera sospecha fue una fuga clásica por *timers*: TTL que cancela con `setTimeout` y nunca libera. El módulo no tiene ningún timer — el repro mostró que la fuga real es doble: la caducidad solo existe **al leer** y `maxEntries` **nunca se aplica**. Reformulo el análisis con las dos evidencias medidas (bloque inferior).

**S1 — BUG alto: fuga de memoria por caducidad perezosa + `maxEntries` sin aplicar (demostrado).** La única purga es la de `get()` sobre la clave leída: 500 entradas insertadas y caducadas, una sola lectura → `size() === 499`: las 499 que nadie vuelve a leer viven para siempre. Y `maxEntries = 100` no se consulta en ninguna parte: tras 500 inserciones, `size() === 500`. Dos promesas incumplidas del constructor en un mismo medidor: `PASS/FAIL` A1 y A2 del repro.

**S2 — BUG alto: carrera en `getOrLoad` → doble carga y escrituras fuera de orden (demostrado).** Entre el `get` (miss) y el `set` (tras el `await`) la corrutina cede el control: dos `getOrLoad` concurrentes sobre la misma clave entran ambos por el miss → `loader` se invoca **dos veces** (el "doble de peticiones por SKU caliente" del on-call). Y como el `set` ocurre cuando cada promesa resuelve, el orden real de escritura es el de resolución: en el repro, la carga lenta ("valor-1") resuelve la última y **sobrescribe** el valor fresco. Medido: `loads === 2`, valores distintos para cada llamante (FAIL B1/B2/B3).

**S3 — BUG menor (inspección): valores `undefined` no cacheables.** El centinela de "miss" es `cached !== undefined`; si algún loader produce `undefined`, la clave se recarga en cada acceso. Hoy ningún loader lo devuelve, pero el contrato no lo prohíbe. Lo arreglo con un mapa de entrada distinto de "presente" (basta no usar `undefined` como sentinela: compruebo `has`/`get` de la entrada).

**S4 — ESTILO (no bloqueante):** el constructor no valida `maxEntries >= 1` (el fix lo añade porque el fix depende de ese invariante, pero por sí mismo era solo robustez); mezclar `_data` plano con lógica de política en `get` dificulta probar la política; `5_000`/`1_000` con separadores está bien y no toco nada más de formato.

Repro determinista — reloj inyectado, sin temporizadores reales, con promesas resueltas a mano para fijar el orden:

```js
'use strict';
// repro_cache.js — copia de cache.js v1.6 + comprobaciones deterministas

class CacheTTL {
  constructor({ ttlMs = 5000, maxEntries = 100, now = () => Date.now() } = {}) {
    this.ttlMs = ttlMs;
    this.maxEntries = maxEntries;
    this._now = now;
    this._data = new Map();
  }

  get(key) {
    const item = this._data.get(key);
    if (!item) return undefined;
    if (this._now() - item.storedAt > this.ttlMs) {
      this._data.delete(key);
      return undefined;
    }
    return item.value;
  }

  set(key, value) {
    this._data.set(key, { value, storedAt: this._now() });
  }

  async getOrLoad(key, loader) {
    const cached = this.get(key);
    if (cached !== undefined) return cached;
    const value = await loader(key);
    this.set(key, value);
    return value;
  }

  size() {
    return this._data.size;
  }
}

(async () => {
  let t = 0;
  let failures = 0;
  const check = (name, ok) => { console.log((ok ? 'PASS' : 'FAIL') + ' ' + name); if (!ok) failures++; };

  // A: fuga de memoria (maxEntries sin aplicar + caducidad solo al leer)
  {
    const c = new CacheTTL({ ttlMs: 1000, maxEntries: 100, now: () => t });
    for (let i = 0; i < 500; i++) c.set('k' + i, { payload: 'x'.repeat(64) });
    t += 10000;
    c.get('k0');                       // purga unicamente la clave leida
    check('A1 maxEntries respetado tras 500 inserciones (size<=100)', c.size() <= 100);
    check('A2 entradas caducadas purgadas tras avanzar el reloj (size==0)', c.size() === 0);
  }

  // B: carrera en getOrLoad (doble carga + escritura fuera de orden)
  {
    const c = new CacheTTL({ ttlMs: 60000, maxEntries: 10, now: () => t });
    let loads = 0;
    let resolveSlow, resolveFast;
    const loader = () => {
      const n = ++loads;
      return new Promise((res) => {
        if (n === 1) resolveSlow = () => res('valor-' + n);
        else resolveFast = () => res('valor-' + n);
      });
    };
    const p1 = c.getOrLoad('sku-1', loader);
    const p2 = c.getOrLoad('sku-1', loader);
    resolveFast();                     // la segunda carga termina primero
    const v2 = await p2;               // 'valor-2'
    resolveSlow();                     // la primera termina despues y SOBREESCRIBE
    const v1 = await p1;               // 'valor-1'
    check('B1 backend cargado exactamente 1 vez bajo concurrencia', loads === 1);
    check('B2 ambos concurrentes obtienen el mismo valor', v1 === v2);
    check('B3 cache consistente con lo cargado', c.get('sku-1') === v2);
  }

  console.log(failures === 0 ? 'OK todos los invariantes' : 'FALLO invariantes rotos: ' + failures);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error('ERROR', e); process.exit(2); });
```"""),
            ("tool", r"""$ node --version
v24.21.0
$ node repro_cache.js
FAIL A1 maxEntries respetado tras 500 inserciones (size<=100)
FAIL A2 entradas caducadas purgadas tras avanzar el reloj (size==0)
FAIL B1 backend cargado exactamente 1 vez bajo concurrencia
FAIL B2 ambos concurrentes obtienen el mismo valor
FAIL B3 cache consistente con lo cargado
FALLO invariantes rotos: 5
$ echo $?
1"""),
            ("assistant", r"""Causa raíz y fix.

**Causa raíz de S1:** la política de expiración vivía solo en el path de lectura; el parámetro `maxEntries` se guardaba y nunca se leía. **Causa raíz de S2:** el hueco `await` entre miss y `set` sin memoización de la promesa en vuelo.

Fix v1.7: (a) purga activa de caducados en `set`/`size` — O(n) por operación con n≤100, despreciable; (b) expulsión FIFO cuando se alcanza `maxEntries` (el `Map` conserva orden de inserción; si el producto pide LRU, se toca la entrada en `get`); (c) deduplicación por clave con un mapa `_inflight`: el segundo `getOrLoad` devuelve la MISMA promesa, el backend se llama una vez y ambos llamantes reciben el mismo valor; el `finally` libera el vuelo también si el loader lanza; (d) S3: entrada de presencia explícita para tolerar valores `undefined`; (e) S4: validación de `maxEntries` en el constructor.

```js
'use strict';
// cache.js v1.7 — cache TTL para catalogo (revision aplicada)

class CacheTTL {
  constructor({ ttlMs = 5000, maxEntries = 100, now = () => Date.now() } = {}) {
    if (!Number.isInteger(maxEntries) || maxEntries < 1) {
      throw new TypeError('maxEntries debe ser >= 1');
    }
    this.ttlMs = ttlMs;
    this.maxEntries = maxEntries;
    this._now = now;
    this._data = new Map();       // key -> { value, storedAt }
    this._inflight = new Map();   // key -> Promise en vuelo (dedup de cargas)
  }

  get(key) {
    const item = this._data.get(key);
    if (!item) return undefined;
    if (this._now() - item.storedAt > this.ttlMs) {
      this._data.delete(key);
      return undefined;
    }
    return item.value;
  }

  set(key, value) {
    this._purgeExpired();
    if (!this._data.has(key)) this._evictWhileFull();
    this._data.set(key, { value, storedAt: this._now() });
  }

  async getOrLoad(key, loader) {
    const item = this._data.get(key);
    if (item && this._now() - item.storedAt <= this.ttlMs) return item.value;
    if (this._inflight.has(key)) return this._inflight.get(key);   // S2: dedup
    const flight = (async () => {
      try {
        const value = await loader(key);
        this.set(key, value);
        return value;
      } finally {
        this._inflight.delete(key);   // libera el vuelo tambien si loader lanza
      }
    })();
    this._inflight.set(key, flight);
    return flight;
  }

  size() {
    this._purgeExpired();
    return this._data.size;
  }

  _purgeExpired() {                 // S1a: caducidad activa, no solo al leer
    const t = this._now();
    for (const [k, item] of this._data) {
      if (t - item.storedAt > this.ttlMs) this._data.delete(k);
    }
  }

  _evictWhileFull() {               // S1b: maxEntries se aplica de verdad (FIFO)
    while (this._data.size >= this.maxEntries) {
      const oldest = this._data.keys().next().value;
      this._data.delete(oldest);
    }
  }
}

module.exports = { CacheTTL };

// --- verificacion determinista de los invariantes (mismo metodo que el repro) ---
(async () => {
  let t = 0;
  let failures = 0;
  const check = (name, ok) => { console.log((ok ? 'PASS' : 'FAIL') + ' ' + name); if (!ok) failures++; };

  {
    const c = new CacheTTL({ ttlMs: 1000, maxEntries: 100, now: () => t });
    for (let i = 0; i < 500; i++) c.set('k' + i, { payload: 'x'.repeat(64) });
    check('A1 maxEntries respetado tras 500 inserciones (size==100)', c.size() === 100);
    t += 10000;
    check('A2 entradas caducadas purgadas tras avanzar el reloj (size==0)', c.size() === 0);
    t -= 10000;
    c.set('a', 1);
    t += 2000;
    check('A3 get sobre clave caducada borra y devuelve undefined', c.get('a') === undefined && c.size() === 0);
  }

  {
    const c = new CacheTTL({ ttlMs: 60000, maxEntries: 10, now: () => t });
    let loads = 0;
    let resolver;
    const loader = () => {
      loads++;
      return new Promise((res) => { resolver = () => res('valor-' + loads); });
    };
    const p1 = c.getOrLoad('sku-1', loader);
    const p2 = c.getOrLoad('sku-1', loader);   // dedup: misma promesa en vuelo
    resolver();
    const v1 = await p1;
    const v2 = await p2;
    check('B1 backend cargado exactamente 1 vez bajo concurrencia', loads === 1);
    check('B2 ambos concurrentes obtienen el mismo valor', v1 === v2);
    check('B3 cache consistente con lo cargado', c.get('sku-1') === v2);
    let lanzo = false;
    await c.getOrLoad('sku-2', async () => { throw new Error('backend caido'); })
      .catch(() => { lanzo = true; });
    check('B4 si loader lanza, el vuelo se libera y el error propaga', lanzo && !c._inflight.has('sku-2'));
  }

  console.log(failures === 0 ? 'OK todos los invariantes' : 'FALLO invariantes rotos: ' + failures);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error('ERROR', e); process.exit(2); });
```

Nota operativa: con dedup, el segundo llamante hereda la latencia del primero en lugar de disparar una segunda carga; es exactamente el comportamiento que quiere el on-call para SKUs calientes. Si algún producto necesitara "carga más fresca aunque otra esté en vuelo", sería un cambio de contrato explícito, no un accidente de implementación."""),
        ],
        verify=[
            {"name": "repro_fuga_y_carrera", "action": "run", "lang": "js",
             "msg": 2, "block": 0, "expect_fail": True,
             "expect_stdout_contains": ["FAIL A1", "FAIL B1", "FALLO invariantes rotos: 5"],
             "timeout_s": 15},
            {"name": "fix_invariantes_verdes", "action": "run", "lang": "js",
             "msg": -1, "block": 0, "expect_exit": 0,
             "expect_stdout_contains": ["PASS A1", "PASS B1", "OK todos los invariantes"],
             "timeout_s": 15},
        ],
        tags=["code_review", "memory_leak", "race_condition", "async", "cache"],
        stack=["javascript", "node"],
        recovery=True,
    ),

    # =====================================================================
    # CR4 — bash: script de despliegue sin locking ni set -euo pipefail (hard)
    # =====================================================================
    E(
        language="bash", domain="scripting_automation", subdomain="revision_script_despliegue",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", r"""Revisión de `deploy.sh` v3.1 (se ejecuta desde CI y a veces a mano desde dos terminales del bastión). Incidentes recientes: (a) el estado `active` del servicio quedó con un número viejo tras dos despliegues casi simultáneos; (b) un artefacto con checksum fallido llegó a anunciarse como «DESPLIEGUE COMPLETADO».

```bash
#!/usr/bin/env bash
# deploy.sh v3.1 — despliegue del servicio (staging y produccion comparten host)

APP_DIR=/srv/app
RELEASES_DIR=/srv/releases
STATE_DIR=/srv/state

log() { echo "[deploy] $*"; }

publish_release() {
    local artifact=$1
    log "instalando artefacto $artifact"
    cp "$artifact" "$RELEASES_DIR/staging.bin" || log "aviso: cp fallo, se reusa el staging anterior"
    grep -q "checksum-ok" "$artifact.meta"
    log "checksum verificado"
    mkdir -p "$APP_DIR"
    cp "$RELEASES_DIR/staging.bin" "$APP_DIR/app.bin"

    # apunta el servicio a la nueva version (contador de releases activas)
    local current
    current=$(cat "$STATE_DIR/active")
    echo $((current + 1)) > "$STATE_DIR/active"

    log "DESPLIEGUE COMPLETADO"
}

case "${1:-}" in
    publish) publish_release "${2:?falta artefacto}" ;;
    *) echo "uso: deploy.sh publish <artefacto>" ; exit 64 ;;
esac
```

Quiero los bugs demostrados con un repro determinista y el parche. Los componentes reales (`cp`, `grep`) se sustituyen por dobles de prueba solo cuando hace falta para la demo."""),
            ("assistant", r"""Revisión priorizada. **BUG** = demostrado con repro determinista; **ESTILO** = no cambia el comportamiento.

**Recuperación de hipótesis:** mi primera propuesta de corrección para (a) fue un lock con `mkdir` (directorio-lock). La descarté al revisarla: si el proceso muere, el directorio queda huérfano y el despliegue siguiente se bloquea para siempre o requiere limpieza manual; sin una rutina de reaping, ese lock no es seguro ante fallos. La corrección que propongo usa `flock` con el descriptor de fichero del propio proceso, que el kernel libera al morir el proceso. Anoto la recuperación porque cambia el parche, no solo el estilo.

**S1 — BUG crítico: actualización de estado sin locking → actualización perdida (demostrado).** El patrón leer-modificar-escribir de `$STATE_DIR/active` no es atómico: dos despliegues concurrentes leen ambos el mismo valor y el segundo `echo` pisa al primero. Repro A (bloque inferior): dos instancias en paralelo sobre `active=0` dejan `active=1` en vez de `2`. Con `sleep 0.3` dentro de la ventana la demo es determinista, pero el fallo existe sin el `sleep`: es la ventana entre `cat` y `echo`.

**S2 — BUG alto: sin `set -euo pipefail` → fallo silenciado y éxito falso (demostrado).** Tres capas del mismo problema: (i) sin `set -e`, el `grep -q "checksum-ok" "$artifact.meta"` que falla NO aborta — el script sigue, imprime "checksum verificado" y termina anunciando «DESPLIEGUE COMPLETADO» (repro B: `rc=0` con meta inexistente); (ii) sin `pipefail`, un pipeline cuyo `grep` interno no encuentre nada devuelve el estado del último comando y pasa desapercibido; (iii) sin `set -u`, una variable mal tecleada se expande a vacío. El `cp ... || log "aviso"` es la misma enfermedad escrita a mano: el error se registra y el despliegue continúa con un binario viejo.

**S3 — BUG medio (inspección): la escritura de estado no es atómica frente a lectores.** Aunque se corrigiera S1 con lock entre despliegues, `echo > active` trunca y reescribe: un lector concurrente puede leer el fichero a medias. El parche escribe a temporal + `mv` (rename atómico) dentro de la sección crítica.

**S4 — ESTILO (no bloqueante):** comillas ya correctas en las expansiones (bien), pero `log` escribe a stdout cuando lo convencional en un script de despliegue es stderr o un logger; y el `case` podría validar `artifact` antes de tocar `$RELEASES_DIR`. No cambia el comportamiento demostrado; lo dejo fuera del parche mínimo.

Repro determinista (extrae las dos funciones del script tal cual y las ejercita):

```bash
#!/usr/bin/env bash
# repro_deploy_bugs.sh — demo determinista de S1 y S2 sobre extractos de deploy.sh v3.1
set -u
work=$(mktemp -d) || exit 2
trap 'rm -rf "$work"' EXIT
failures=0
check() { if [ "$1" = 0 ]; then echo "PASS $2"; else echo "FAIL $2"; failures=$((failures+1)); fi; }

# --- extracto literal de deploy.sh v3.1: contador de releases sin lock ---
bump_sin_lock() {
    local state=$1
    local current
    current=$(cat "$state/active")
    sleep 0.3                       # ventana: I/O del despliegue real
    echo $((current + 1)) > "$state/active"
}

# --- extracto literal: verificacion de checksum sin set -e ---
buggy_deploy() {
    local meta=$1
    grep -q "checksum-ok" "$meta"
    echo "[deploy] checksum verificado"
    echo "[deploy] DESPLIEGUE COMPLETADO"
}

# A: carrera — dos despliegues concurrentes sin flock
echo 0 > "$work/active"
bump_sin_lock "$work" & bump_sin_lock "$work" &
wait
check $([ "$(cat "$work/active")" = 2 ] && echo 0 || echo 1) \
      "A: dos despliegues concurrentes dejan active=2 (obtenido $(cat "$work/active"))"

# B: fallo silenciado — el script sigue y anuncia COMPLETADO
salida=$(buggy_deploy "$work/inexistente.meta" 2>/dev/null); rc=$?
check $([ "$rc" -ne 0 ] && echo 0 || echo 1) "B: deploy aborta con meta inexistente (rc=$rc)"
check $([[ "$salida" != *COMPLETADO* ]] && echo 0 || echo 1) "B: no se anuncia COMPLETADO tras fallo"

echo "$failures"
[ "$failures" = 0 ]
```"""),
            ("tool", r"""$ bash --version | head -1
GNU bash, version 5.2.15(1)-release (x86_64-pc-linux-gnu)
$ bash repro_deploy_bugs.sh
FAIL A: dos despliegues concurrentes dejan active=2 (obtenido 1)
FAIL B: deploy aborta con meta inexistente (rc=0)
FAIL B: no se anuncia COMPLETADO tras fallo
3
$ echo $?
1"""),
            ("assistant", r"""Causa raíz y parche.

**Causa raíz de S1:** la sección crítica (leer `active`, computar, escribir) corre sin exclusión mutua; el `sleep 0.3` del repro solo hace visible lo que en producción es la latencia de I/O entre ambas operaciones. **Causa raíz de S2:** el script no fija un modo de fallo: por defecto, bash continúa ante cualquier error y el estado de un pipeline es el del último comando.

Parche v3.2 con las tres piezas: `set -euo pipefail` arriba; `flock` sobre un descriptor abierto por el propio script para la sección crítica (lock liberado por el kernel al morir el proceso, sin huérfanos); escritura atómica del estado con temporal + `mv`. La autocomprobación incluye el matiz que casi nadie conoce: dentro de un contexto de condición (`if`, `||`, `&&`) `set -e` se ignora, así que el test B reactiva `set -e` dentro de la subshell de captura — fue exactamente el fallo de mi primera versión del propio test.

```bash
#!/usr/bin/env bash
# deploy.sh v3.2 — despliegue del servicio (revision aplicada) + autocomprobacion
set -euo pipefail

APP_DIR=/srv/app
RELEASES_DIR=/srv/releases
STATE_DIR=/srv/state

log() { echo "[deploy] $*" >&2; }

publish_release() {
    local artifact=$1
    log "instalando artefacto $artifact"
    cp "$artifact" "$RELEASES_DIR/staging.bin"          # S2: sin '|| aviso'; cp falla -> aborta
    grep -q "checksum-ok" "$artifact.meta"              # S2: con set -e un fallo aborta
    log "checksum verificado"
    mkdir -p "$APP_DIR"
    cp "$RELEASES_DIR/staging.bin" "$APP_DIR/app.bin"

    # S1/S3: seccion critica con flock y escritura atomica (temporal + mv)
    (
        flock 9
        local current
        current=$(cat "$STATE_DIR/active")
        sleep 0.3                       # I/O del despliegue real, dentro del lock
        echo $((current + 1)) > "$STATE_DIR/active.tmp"
        mv "$STATE_DIR/active.tmp" "$STATE_DIR/active"
    ) 9>"$STATE_DIR/.deploy.lock"

    log "DESPLIEGUE COMPLETADO"
}

# ---- autocomprobacion determinista (la misma metrica que el repro de v3.1) ----
work=$(mktemp -d) || exit 2
trap 'rm -rf "$work"' EXIT
failures=0
check() { if [ "$1" = 0 ]; then echo "PASS $2"; else echo "FAIL $2"; failures=$((failures+1)); fi; }

bump_con_flock() {
    local state=$1
    (
        flock 9
        local current
        current=$(cat "$state/active")
        sleep 0.3
        echo $((current + 1)) > "$state/active"
    ) 9>"$state/.deploy.lock"
}

fixed_deploy() {
    local meta=$1
    grep -q "checksum-ok" "$meta"
    echo "[deploy] checksum verificado"
    echo "[deploy] DESPLIEGUE COMPLETADO"
}

# A: carrera — dos despliegues concurrentes CON flock
echo 0 > "$work/active"
bump_con_flock "$work" & bump_con_flock "$work" &
wait
check $([ "$(cat "$work/active")" = 2 ] && echo 0 || echo 1) \
      "A: dos despliegues concurrentes dejan active=2 (obtenido $(cat "$work/active"))"

# B: fallo NO silenciado. Ojo: en un contexto de condicion set -e se ignora;
# reactivamos set -e dentro de la subshell de captura.
set +e
salida=$( set -e; fixed_deploy "$work/inexistente.meta" 2>/dev/null )
rc=$?
set -e
check $([ "$rc" -ne 0 ] && echo 0 || echo 1) "B: deploy aborta con meta inexistente (rc=$rc)"
check $([[ "$salida" != *COMPLETADO* ]] && echo 0 || echo 1) "B: no se anuncia COMPLETADO tras fallo"

# C: pipefail — un grep sin resultados en mitad de un pipeline no pasa desapercibido
set +e
printf 'alpha\nbeta\n' | grep -q 'gamma' | cat
rc=$?
set -e
check $([ "$rc" -ne 0 ] && echo 0 || echo 1) "C: pipefail detecta el grep fallido (rc=$rc)"

[ "$failures" = 0 ] && echo "OK invariante de despliegue restaurado"
```"""),
        ],
        verify=[
            {"name": "repro_carrera_y_falso_exito", "action": "run", "lang": "bash",
             "msg": 2, "block": 0, "expect_fail": True,
             "expect_stdout_contains": ["FAIL A", "COMPLETADO"],
             "timeout_s": 15},
            {"name": "fix_flock_y_pipefail", "action": "run", "lang": "bash",
             "msg": -1, "block": 0, "expect_exit": 0,
             "expect_stdout_contains": ["PASS A", "OK invariante de despliegue restaurado"],
             "timeout_s": 15},
        ],
        tags=["code_review", "locking", "flock", "pipefail", "deployment"],
        stack=["bash", "coreutils"],
        recovery=True,
    ),

    # =====================================================================
    # CR5 — java: recursos sin cerrar y equals/hashCode roto (hard, estático)
    # =====================================================================
    E(
        language="java", domain="backend", subdomain="revision_recursos_java",
        difficulty="hard", task_type="code_review",
        messages=[
            ("user", r"""Revisión previa a fusión de `ReportService.java` v3.2 (genera y cachea informes mensuales por tenant; se despliega en el servicio de facturación). No tengo entorno de ejecución de Java que puedas verificar desde aquí: quiero revisión estática rigurosa y que me digas QUÉ demostrarías y CÓMO, sin afirmar ejecuciones que no hayan pasado.

```java
// ReportService.java v3.2 — genera y cachea informes mensuales por tenant
package com.acme.reports;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

public class ReportService {

    /** Clave de informe: se usa como clave de HashMap (cache de generados). */
    public static final class ReportKey {
        private final String tenant;
        private final int year;
        private final int month;

        public ReportKey(String tenant, int year, int month) {
            this.tenant = tenant;
            this.year = year;
            this.month = month;
        }

        @Override
        public boolean equals(Object o) {
            if (!(o instanceof ReportKey)) return false;
            ReportKey other = (ReportKey) o;
            return tenant.equals(other.tenant) && year == other.year && month == other.month;
        }
        // hashCode: no hace falta, equals ya compara todos los campos
    }

    private final Map<ReportKey, File> generated = new HashMap<>();

    public File getOrGenerate(ReportKey key, String templatePath) throws Exception {
        File cached = generated.get(key);
        if (cached != null) return cached;

        BufferedReader template = new BufferedReader(
                new FileReader(templatePath, StandardCharsets.UTF_8));
        File out = new File("/var/reports/" + key.tenant + "-" + key.year + "-" + key.month + ".txt");
        PrintWriter writer = new PrintWriter(out, StandardCharsets.UTF_8);
        String line;
        while ((line = template.readLine()) != null) {
            writer.println(line.replace("{{tenant}}", key.tenant));
        }
        writer.close();
        generated.put(key, out);
        return out;
    }
}
```"""),
            ("assistant", r"""Revisión estática (sin ejecución verificada en este entorno, como pide el enunciado: no voy a afirmar salidas que no haya observado). Priorizo por severidad y marco **BUG** / **ESTILO**, indicando en cada caso el experimento que lo demostraría en tu máquina.

**R1 — BUG alto: `equals` sin `hashCode` rompe el contrato y la caché (razonamiento estático preciso).** El comentario "hashCode: no hace falta" es el bug. El contrato de `Object` exige que objetos `equals` tengan el mismo `hashCode`; `HashMap.get` primero localiza el bucket por `hashCode()` y solo después compara con `equals`. Dos `ReportKey` iguales creados por separado heredan `hashCode()` de identidad (basado en referencia): casi seguro caen en buckets distintos y `generated.get(key)` devuelve `null` aunque la clave equivalente esté cacheada. Consecuencias: la caché nunca acierta (regenera el informe en cada llamada, con I/O de disco por request), y cualquier `remove`/`containsKey` con una instancia nueva tampoco funciona. Experimento que lo demuestra (jshell o JUnit, yo no lo ejecuto aquí):

```java
var set = new java.util.HashSet<ReportService.ReportKey>();
var k1 = new ReportService.ReportKey("acme", 2025, 3);
var k2 = new ReportService.ReportKey("acme", 2025, 3);
System.out.println(k1.equals(k2));  // true
set.add(k1);
System.out.println(set.contains(k2)); // false con el bug; true con hashCode corregido
```

Si esas dos líneas no salen exactamente así, mi análisis está caído y lo retiro — es falsable y barato de comprobar.

**R2 — BUG alto: recursos sin cerrar y sin protección ante excepciones.** `BufferedReader template` se abre y nunca se cierra: cada llamada a `getOrGenerate` filtra un descriptor de fichero (el `FileReader` interno también). En un servicio que genera informes bajo demanda, el siguiente síntoma es `IOException: Too many open files` a las horas. Además, `writer.close()` solo se ejecuta en el camino feliz: si `readLine` lanza (plantilla borrada a mitad, problema de permisos), el `PrintWriter` queda abierto y el fichero de salida queda parcial en disco. En ambos casos el fix idiomático es try-with-resources, que cierra en orden inverso incluso con excepción. Experimento: generar 5.000 informes en un bucle sin cerrar y observar `lsof -p <pid>` crecer; con el fix, estable.

**R3 — BUG medio con ángulo de seguridad: ruta construida por concatenación.** `new File("/var/reports/" + key.tenant + ...)` no valida `tenant`: un tenant `"../../etc"` (si la entrada llega de un panel de administración o de un webhook) escribe fuera del directorio de informes (path traversal de escritura). Y con independencia de eso, no se crea `/var/reports` si no existe: en un host limpio, `PrintWriter` lanza `FileNotFoundException` en el primer arranque. Fix: validar el patrón del tenant, `Path.normalize()`/`resolve()` en lugar de concatenar, y `Files.createDirectories` antes de escribir.

**R4 — ESTILO / diseño no bloqueante:** `throws Exception` en la firma pierde toda la información de tipos (mejor `throws IOException`); `File` frente a `java.nio.file.Path` es preferencia moderna con comportamiento equivalente aquí; `PrintWriter.println` usa el separador de línea de la plataforma — para un fichero que consume otro sistema, prefiero fijar el salto explícitamente. Nada de esto cambia la corrección; lo separo de R1-R3.

Versión corregida v3.3 (R1-R3 resueltos; R4 incorporada donde no cuesta nada):

```java
// ReportService.java v3.3 — (revision aplicada)
package com.acme.reports;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Pattern;

public class ReportService {

    private static final Pattern TENANT_OK = Pattern.compile("[a-z0-9-]{1,64}");
    private static final Path REPORTS_DIR = Paths.get("/var/reports");

    /** Clave de informe: clave de HashMap, luego equals/hashCode deben cuadrar. */
    public static final class ReportKey {
        private final String tenant;
        private final int year;
        private final int month;

        public ReportKey(String tenant, int year, int month) {
            this.tenant = Objects.requireNonNull(tenant, "tenant");
            this.year = year;
            this.month = month;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof ReportKey)) return false;
            ReportKey other = (ReportKey) o;
            return tenant.equals(other.tenant) && year == other.year && month == other.month;
        }

        @Override
        public int hashCode() {
            return Objects.hash(tenant, year, month);   // R1: ahora coherente con equals
        }
    }

    private final Map<ReportKey, Path> generated = new HashMap<>();

    public Path getOrGenerate(ReportKey key, Path templatePath) throws IOException {
        Path cached = generated.get(key);
        if (cached != null) return cached;

        if (!TENANT_OK.matcher(key.tenant).matches()) {  // R3: sin traversal
            throw new IllegalArgumentException("tenant invalido: " + key.tenant);
        }
        Files.createDirectories(REPORTS_DIR);            // R3: host limpio no explota
        Path out = REPORTS_DIR.resolve(key.tenant + "-" + key.year + "-" + key.month + ".txt");

        // R2: try-with-resources cierra ambos recursos, en orden inverso, con excepcion
        try (BufferedReader template = Files.newBufferedReader(templatePath, StandardCharsets.UTF_8);
             BufferedWriter writer = Files.newBufferedWriter(out, StandardCharsets.UTF_8)) {
            String line;
            while ((line = template.readLine()) != null) {
                writer.write(line.replace("{{tenant}}", key.tenant));
                writer.write("\n");                      // R4: salto fijo, no el del SO
            }
        }
        generated.put(key, out);
        return out;
    }
}
```

Resumen para el PR: R1 es el silencioso más caro (rendimiento y corrección de la caché), R2 es el que tira el servicio por fd leakage, R3 cierra el traversal y el arranque limpio. Las dos líneas de jshell del punto R1 son el criterio de aceptación mínimo que pediría en la revisión antes de aprobar."""),
        ],
        tags=["code_review", "equals_hashcode", "try_with_resources", "path_traversal"],
        stack=["java"],
        recovery=False,
    ),

    # =====================================================================
    # T1 — c: suite con mini-framework de asserts para parse_duration_ms (hard)
    # =====================================================================
    E(
        language="c", domain="tooling", subdomain="tests_parse_duration",
        difficulty="hard", task_type="testing",
        messages=[
            ("user", r"""Te paso `parse_duration_ms`, la función del equipo de plataforma que convierte duraciones de la API (`"1h30m10s250ms"`) a milisegundos (`duration.c` v1.2, se usa en el CLI de tareas programadas). Necesito una suite de tests con casos límite y un mini-framework de asserts propio (sin dependencias), lista para compilar así:

`gcc -fsanitize=address -g -o test_duration test_duration.c`

El bloque debe imprimir `OK ...` solo si TODO pasa y salir con 0. Contrato actual de la función (v1.2):

```c
/* duration.c v1.2 — proporcionado por el equipo de plataforma.
 * parse_duration_ms: convierte una duracion tipo "1h30m10s250ms" a milisegundos.
 * Contrato:
 *   - Unidades validas, en este orden y sin repetirse: h, m, s, ms.
 *   - Cada componente requiere su cifra; sin espacios; sin signo (>= 0).
 *   - Sin unidad ("10") o unidad desconocida -> error.
 *   - Devuelve 0 en exito y escribe *out_ms; devuelve -1 ante cualquier error
 *     o desbordamiento de int64_t.
 */
#include <stdint.h>
#include <string.h>
#include <ctype.h>

int parse_duration_ms(const char *s, int64_t *out_ms) {
    if (s == NULL || *s == '\0') return -1;
    static const char *units[4] = { "h", "m", "s", "ms" };
    static const int64_t factor[4] = { 3600000, 60000, 1000, 1 };
    int64_t total = 0;
    int pos = 0, last_unit = -1;
    while (s[pos] != '\0') {
        if (!isdigit((unsigned char)s[pos])) return -1;
        int64_t value = 0;
        while (isdigit((unsigned char)s[pos])) {
            if (value > (INT64_MAX - (s[pos] - '0')) / 10) return -1; /* overflow cifra */
            value = value * 10 + (s[pos] - '0');
            pos++;
        }
        int u = -1;
        if (strncmp(s + pos, "ms", 2) == 0) { u = 3; pos += 2; }  /* 'ms' antes que 'm' */
        else for (int k = 0; k < 3; k++) {
            if (s[pos] == units[k][0]) { u = k; pos += 1; break; }
        }
        if (u == -1 || u <= last_unit) return -1;   /* unidad invalida o fuera de orden */
        if (value > INT64_MAX / factor[u]) return -1; /* overflow componente */
        int64_t term = value * factor[u];
        if (total > INT64_MAX - term) return -1;      /* overflow suma */
        total += term;
        last_unit = u;
    }
    if (last_unit == -1) return -1;
    if (out_ms) *out_ms = total;
    return 0;
}
```"""),
            ("assistant", r"""Diseño de la suite antes del código.

**Mini-framework:** macro `CHECK(cond)` que registra fichero/línea/expresión en stderr y cuenta fallos, más un helper específico `check_parse(input, rc_esperado, ms_esperado)` porque casi todos los casos comparten forma. Al final: `OK n comprobaciones, 0 fallos` + `exit 0` solo si no hubo fallos.

**Casos límite que elijo y por qué:**
1. Composición canónica completa y parcial (`"1h30m10s250ms"`, `"2h"`, `"59s"`) y la frontera inferior `0ms`/`1ms`.
2. **Límites de `int64_t`**: `9223372036854775807ms` (exactamente `INT64_MAX`) debe pasar; `+1` debe fallar; el overflow también aparece al multiplicar (`9223372036854776s` desborda el `value * factor`) y en la propia cifra (`"99999999999999999999h"`). Esto fija la política "error, no envolvimiento".
3. **El caso trampa `ms`**: una implementación que compare la unidad `"m"` antes que `"ms"` consumiría la `m` y parsearía el resto como basura; `"...250ms"`, `"1ms"` y `"0ms"` son el tripwire de esa regresión (existen porque la v1.1 la tenía).
4. Errores de formato: vacío, espacios, sin unidad, unidad sin cifra, unidad desconocida, mayúsculas, signo, orden `3s1h`, unidad repetida `1m30m`, basura final `250mss`, decimal `0.5s` (el caso real del incidente que motivó el contrato).
5. Robustez de la API: `out_ms == NULL` no debe romper (se usa en validación previa al cálculo).

Como compilamos con `-fsanitize=address`, la suite además acredita en la misma ejecución que no hay fugas ni accesos fuera de rango: un `exit 0` aquí es contrato completo, no solo "los asserts pasan".

```c
/* test_duration.c — suite de parse_duration_ms (duration.c v1.2, proporcionada).
 * Compilar: gcc -fsanitize=address -g -o test_duration test_duration.c
 * Sale 0 e imprime OK solo si todas las comprobaciones pasan. */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

/* ==== funcion proporcionada (copia literal, sin cambios) ==== */
int parse_duration_ms(const char *s, int64_t *out_ms) {
    if (s == NULL || *s == '\0') return -1;
    static const char *units[4] = { "h", "m", "s", "ms" };
    static const int64_t factor[4] = { 3600000, 60000, 1000, 1 };
    int64_t total = 0;
    int pos = 0, last_unit = -1;
    while (s[pos] != '\0') {
        if (!isdigit((unsigned char)s[pos])) return -1;
        int64_t value = 0;
        while (isdigit((unsigned char)s[pos])) {
            if (value > (INT64_MAX - (s[pos] - '0')) / 10) return -1;
            value = value * 10 + (s[pos] - '0');
            pos++;
        }
        int u = -1;
        if (strncmp(s + pos, "ms", 2) == 0) { u = 3; pos += 2; }
        else for (int k = 0; k < 3; k++) {
            if (s[pos] == units[k][0]) { u = k; pos += 1; break; }
        }
        if (u == -1 || u <= last_unit) return -1;
        if (value > INT64_MAX / factor[u]) return -1;
        int64_t term = value * factor[u];
        if (total > INT64_MAX - term) return -1;
        total += term;
        last_unit = u;
    }
    if (last_unit == -1) return -1;
    if (out_ms) *out_ms = total;
    return 0;
}

/* ==== mini-framework de asserts ==== */
static int g_checks = 0, g_failed = 0;
#define CHECK(cond) do { ++g_checks; if (!(cond)) { ++g_failed; \
    fprintf(stderr, "FALLO %s:%d: %s\n", __FILE__, __LINE__, #cond); } } while (0)

static void check_parse(const char *input, int expect_rc, int64_t expect_ms) {
    ++g_checks;
    int64_t got = -999;
    int rc = parse_duration_ms(input, &got);
    if (rc != expect_rc || (expect_rc == 0 && got != expect_ms)) {
        ++g_failed;
        fprintf(stderr, "FALLO parse(\"%s\"): rc=%d ms=%lld (esperado rc=%d ms=%lld)\n",
                input, rc, (long long)got, expect_rc, (long long)expect_ms);
    }
}

int main(void) {
    /* composicion canonica */
    check_parse("1h30m10s250ms", 0, 5410250LL);
    check_parse("2h", 0, 7200000LL);
    check_parse("90m", 0, 5400000LL);
    check_parse("59s", 0, 59000LL);
    check_parse("0ms", 0, 0LL);
    check_parse("1ms", 0, 1LL);

    /* limites de int64 */
    check_parse("9223372036854775807ms", 0, INT64_MAX);
    check_parse("9223372036854775808ms", -1, 0);   /* INT64_MAX + 1 */
    check_parse("9223372036854775s", 0, 9223372036854775000LL);
    check_parse("9223372036854776s", -1, 0);       /* desborda al multiplicar */
    check_parse("99999999999999999999h", -1, 0);   /* desborda la propia cifra */

    /* errores de formato */
    check_parse("", -1, 0);
    check_parse("   5s", -1, 0);
    check_parse("10", -1, 0);          /* falta unidad */
    check_parse("ms", -1, 0);          /* falta cifra */
    check_parse("5x", -1, 0);
    check_parse("5S", -1, 0);          /* unidades solo minusculas */
    check_parse("-5s", -1, 0);         /* sin signo */
    check_parse("3s1h", -1, 0);        /* orden h m s ms */
    check_parse("1m30m", -1, 0);       /* unidad repetida */
    check_parse("5s ", -1, 0);
    check_parse("1h30m10s250mss", -1, 0);

    /* caso del incidente: la API envia "0.5s" */
    check_parse("0.5s", -1, 0);

    /* out_ms NULL no rompe */
    CHECK(parse_duration_ms("7s", NULL) == 0);

    if (g_failed == 0) printf("OK %d comprobaciones, 0 fallos\n", g_checks);
    else printf("FALLOS: %d de %d comprobaciones\n", g_failed, g_checks);
    return g_failed == 0 ? 0 : 1;
}
```"""),
            ("tool", r"""$ gcc -fsanitize=address -g -o test_duration test_duration.c
$ ./test_duration
OK 24 comprobaciones, 0 fallos
$ echo $?
0
$ ./test_duration 2>/dev/null; echo "rc=$?"
OK 24 comprobaciones, 0 fallos
rc=0

(sin informes de LeakSanitizer al salir: la suite tambien acredita que la
 funcion proporcionada no fuga memoria en ningun camino probado)"""),
            ("assistant", r"""La suite está en verde contra v1.2 (salida real arriba: 24 comprobaciones, 0 fallos, `exit 0` bajo ASan). Tres notas de mantenimiento:

1. **Tripwire de unidades:** los casos `"1ms"`, `"0ms"` y `"...250ms"` existen porque la v1.1 comparaba `"m"` antes que `"ms"` y devolvía `-1` (o basura) en cualquier duración con milisegundos. Si alguien reintroduce ese orden de comparación, esta suite se pone roja en tres puntos con el mensaje exacto.
2. **Límites de `int64_t`:** los cuatro casos de desbordamiento fijan la política documentada ("devuelve -1, no envuelve"). Si la plataforma decide saturar en lugar de fallar, es un cambio de contrato: se actualizan estos tests primero, no el código.
3. **ASan como parte del criterio:** compilar la suite con `-fsanitize=address` convierte el `exit 0` en un doble veredicto (asserts + higiene de memoria). Si añadís más caminos a la función, la misma ejecución vigila fugas sin escribir nada extra.

Si el producto algún día acepta `"1h30m10s250ms "` con espacios finales o mayúsculas, el cambio de contrato empieza añadiendo los casos rojos aquí y después la implementación — en ese orden."""),
        ],
        verify=[
            {"name": "suite_c_verde_con_asan", "action": "compile_run", "lang": "c",
             "msg": 2, "block": 0, "cargs": ["-fsanitize=address", "-g"],
             "expect_exit": 0, "expect_stdout_contains": ["OK 24 comprobaciones, 0 fallos"],
             "timeout_s": 20},
        ],
        tags=["testing", "edge_cases", "assertions", "asan", "int64"],
        stack=["c", "gcc", "asan"],
        recovery=False,
    ),

    # =====================================================================
    # T2 — python: unittest para flatten_dict (hard)
    # =====================================================================
    E(
        language="python", domain="backend", subdomain="tests_flatten_dict",
        difficulty="hard", task_type="testing",
        messages=[
            ("user", r"""Esta es `flatten_dict` (utils/nested.py v2.0), que aplana la configuración anidada antes de enviarla a observabilidad. Escríbeme la suite unittest completa con casos límite, en un solo bloque ejecutable con `unittest.main()`. El contrato actual:

```python
# utils/nested.py v2.0 — proporcionada por el equipo de datos
def flatten_dict(mapping, sep="."):
    # Aplana un diccionario anidado: las claves se unen con `sep`.
    # Contrato (v2.0):
    #   - Los dict anidados se expanden; cualquier otro valor es hoja.
    #   - Un dict anidado vacio es una hoja (se conserva como {}).
    #   - sep debe ser un str no vacio; TypeError en otro caso.
    #   - Las claves deben ser str (TypeError si no); se unen sin escapar.
    if not isinstance(sep, str) or sep == "":
        raise TypeError("sep debe ser un str no vacio")
    out = {}

    def walk(prefix, obj):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError("las claves deben ser str")
            path = key if prefix is None else prefix + sep + key
            if isinstance(value, dict) and value:
                walk(path, value)
            else:
                out[path] = value

    if not isinstance(mapping, dict):
        raise TypeError("mapping debe ser un dict")
    walk(None, mapping)
    return out
```"""),
            ("assistant", r"""Suite diseñada por grupos: forma (vacío/plano/anidado), la decisión de diseño más discutida (dict vacío como hoja), valores falsy que NO deben perderse, validación de `sep` y de claves, comportamiento documentado con claves que contienen el separador, profundidad grande y no-mutación de la entrada. Doce tests, todos deterministas:

```python
# test_flatten_dict.py — suite de la funcion proporcionada (utils/nested.py v2.0)
import unittest


def flatten_dict(mapping, sep="."):
    # copia literal de la funcion proporcionada (sin cambios)
    if not isinstance(sep, str) or sep == "":
        raise TypeError("sep debe ser un str no vacio")
    out = {}

    def walk(prefix, obj):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError("las claves deben ser str")
            path = key if prefix is None else prefix + sep + key
            if isinstance(value, dict) and value:
                walk(path, value)
            else:
                out[path] = value

    if not isinstance(mapping, dict):
        raise TypeError("mapping debe ser un dict")
    walk(None, mapping)
    return out


class TestFlattenDict(unittest.TestCase):
    def test_vacio(self):
        self.assertEqual(flatten_dict({}), {})

    def test_plano(self):
        self.assertEqual(flatten_dict({"a": 1, "b": 2}), {"a": 1, "b": 2})

    def test_anidado(self):
        src = {"db": {"host": "localhost", "port": 5432, "creds": {"user": "svc"}}}
        self.assertEqual(
            flatten_dict(src),
            {"db.host": "localhost", "db.port": 5432, "db.creds.user": "svc"},
        )

    def test_dict_vacio_es_hoja(self):
        # decision de diseno fijada por el contrato v2.0: no se pierde la rama
        self.assertEqual(flatten_dict({"a": {}}), {"a": {}})
        self.assertEqual(flatten_dict({"a": {"b": {}}}), {"a.b": {}})

    def test_none_y_falsy_son_hojas(self):
        src = {"a": None, "b": {"c": 0}, "d": {"e": False}}
        self.assertEqual(flatten_dict(src), {"a": None, "b.c": 0, "d.e": False})

    def test_sep_personalizado(self):
        src = {"a": {"b": {"c": 1}}}
        self.assertEqual(flatten_dict(src, sep="/"), {"a/b/c": 1})

    def test_sep_invalido(self):
        for bad in ("", None, 3):
            with self.assertRaises(TypeError):
                flatten_dict({"a": 1}, sep=bad)

    def test_clave_no_str(self):
        with self.assertRaises(TypeError):
            flatten_dict({1: "x"})
        with self.assertRaises(TypeError):
            flatten_dict({"a": {(2, 3): "x"}})

    def test_clave_que_contiene_sep(self):
        # sin escapado, la clave literal "a.b" y la ruta a.b colisionan;
        # este test FIJA el comportamiento actual (el orden de recorrido
        # decide: la expansion anidada se recorre despues y sobrescribe)
        got = flatten_dict({"a.b": 1, "a": {"b": 2}})
        self.assertEqual(got, {"a.b": 2})

    def test_profundidad_grande(self):
        deep = {}
        node = deep
        for _ in range(200):
            node["n"] = {}
            node = node["n"]
        node["leaf"] = "x"
        flat = flatten_dict(deep)
        esperada = ".".join(["n"] * 200) + ".leaf"
        self.assertEqual(list(flat.keys()), [esperada])
        self.assertEqual(flat[esperada], "x")

    def test_entrada_no_dict(self):
        for bad in ([], "x", None, 5):
            with self.assertRaises(TypeError):
                flatten_dict(bad)

    def test_no_muta_entrada(self):
        src = {"a": {"b": 1}}
        flatten_dict(src)
        self.assertEqual(src, {"a": {"b": 1}})


if __name__ == "__main__":
    unittest.main()
```"""),
            ("tool", r"""$ python3 --version
Python 3.12.14
$ python3 test_flatten_dict.py
............
----------------------------------------------------------------------
Ran 12 tests in 0.002s

OK
$ echo $?
0"""),
            ("assistant", r"""12/12 en verde (salida real arriba). Lo que la suite fija y por qué:

- **`test_dict_vacio_es_hoja`** es el test que evita el bug clásico del "flatten que pierde ramas": sin la cláusula `and value`, `{"a": {}}` desaparecería del resultado y la configuración de un tenant sin overrides sería indistinguible de un tenant sin esa clave. Es decisión de contrato v2.0, no un accidente; si algún día se decide descartar ramas vacías, este test debe cambiar primero.
- **`test_none_y_falsy_son_hojas`** cubre el caso inverso: `0`, `False` y `None` son hojas legítimas y no se descartan.
- **`test_clave_que_contiene_sep`** documenta honestamente una ambigüedad del contrato (no hay escapado): el test no premia un comportamiento "bonito", congela el actual para que un cambio sea una decisión revisada.
- **`test_profundidad_grande`** (200 niveles) y **`test_no_muta_entrada`** protegen frente a dos regresiones típicas al optimizar: recursion explotando antes de tiempo y "optimizaciones" que reutilizan el dict de entrada.

La suite se ejecuta con `python3 test_flatten_dict.py` (sale por `unittest.main()` con el código de estado correcto para CI) o con `python3 -m unittest test_flatten_dict -v` en desarrollo."""),
        ],
        verify=[
            {"name": "suite_python_verde", "action": "run", "lang": "python",
             "msg": 2, "block": 0, "expect_exit": 0,
             "expect_stdout_contains": ["Ran 12 tests", "OK"],
             "expect_stdout_not_contains": ["FAILED"],
             "timeout_s": 15},
        ],
        tags=["testing", "unittest", "edge_cases", "contract"],
        stack=["python"],
        recovery=False,
    ),

    # =====================================================================
    # T3 — javascript: TDD rojo->verde con mini-harness node (very_hard)
    # =====================================================================
    E(
        language="javascript", domain="tooling", subdomain="tdd_roman_numerals",
        difficulty="very_hard", task_type="testing",
        messages=[
            ("user", r"""Necesito `toRoman(n)` y `fromRoman(s)` (números romanos 1..3999, forma canónica sustractiva) para el exportador de fechas del generador de prefacios legales. Quiero que lo hagas con TDD estricto y demostrado en dos pasos dentro de este entorno (node, sin dependencias):

1. Primero el test rojo: la lista completa de tests contra stubs, ejecutada y fallando.
2. Después el verde: implementación mínima que pase la MISMA lista de tests sin tocarlos.

Casos que exijo ver cubiertos: `toRoman(2024) === "MMXXIV"`, sustractivos (`IV`, `IX`), frontera `3999 === "MMMCMXCIX"`, `toRoman` lanza `RangeError` fuera de `[1, 3999]` o con no-enteros, `fromRoman` acepta minúsculas, rechaza formas no canónicas (`"IIII"`) y sustracciones inválidas (`"IL"`), rechaza vacío, e ida-y-vuelta para TODO el rango 1..3999."""),
            ("assistant", r"""TDD, ronda roja. La lista de tests está completa desde el primer momento (incluida la propiedad de ida-y-vuelta para los 3999 valores); los stubs lanzan `not implemented`. El mini-harness cuenta pasados/fallidos, imprime `FALLO <nombre>` por cada test rojo y sale con 1 si hay alguno — así el rojo es verificable, no narrativo.

```js
'use strict';
// roman.test.js — ronda ROJA (TDD): tests completos + stubs
// spec: toRoman(n) / fromRoman(s), enteros 1..3999, forma canonica sustractiva

function toRoman() { throw new Error('not implemented'); }
function fromRoman() { throw new Error('not implemented'); }

const TABLE = [[1000,'M'],[900,'CM'],[500,'D'],[400,'CD'],[100,'C'],[90,'XC'],
               [50,'L'],[40,'XL'],[10,'X'],[9,'IX'],[5,'V'],[4,'IV'],[1,'I']];

let passed = 0, failed = 0;
function check(name, fn) {
  try { if (fn()) { passed++; return; } } catch (e) { /* cuenta como fallo */ }
  failed++;
  console.log('FALLO ' + name);
}

check('toRoman(2024) === "MMXXIV"', () => toRoman(2024) === 'MMXXIV');
check('toRoman(4) es sustractivo', () => toRoman(4) === 'IV');
check('toRoman(3999) === "MMMCMXCIX"', () => toRoman(3999) === 'MMMCMXCIX');
check('toRoman(0) lanza RangeError', () => { try { toRoman(0); return false; } catch (e) { return e instanceof RangeError; } });
check('toRoman(1.5) lanza RangeError', () => { try { toRoman(1.5); return false; } catch (e) { return e instanceof RangeError; } });
check('fromRoman("mmxxiv") acepta minusculas', () => fromRoman('mmxxiv') === 2024);
check('fromRoman("IIII") rechaza (no canonica)', () => { try { fromRoman('IIII'); return false; } catch (e) { return e instanceof Error; } });
check('fromRoman("IL") rechaza (sustraccion invalida)', () => { try { fromRoman('IL'); return false; } catch (e) { return e instanceof Error; } });
check('fromRoman("") lanza Error', () => { try { fromRoman(''); return false; } catch (e) { return e instanceof Error; } });
check('ida y vuelta 1..3999', () => {
  for (let n = 1; n <= 3999; n++) if (fromRoman(toRoman(n)) !== n) return false;
  return true;
});

console.log(failed === 0 ? `OK ${passed}/${passed + failed} tests` : `FALLOS ${failed}/${passed + failed}`);
process.exit(failed === 0 ? 0 : 1);
```"""),
            ("tool", r"""$ node --version
v24.21.0
$ node roman.test.js
FALLO toRoman(2024) === "MMXXIV"
FALLO toRoman(4) es sustractivo
FALLO toRoman(3999) === "MMMCMXCIX"
FALLO toRoman(0) lanza RangeError
FALLO toRoman(1.5) lanza RangeError
FALLO fromRoman("mmxxiv") acepta minusculas
FALLO ida y vuelta 1..3999
FALLOS 7/10
$ echo $?
1

(rojo verificado: 7 tests fallan; los 3 'verdes por accidente' son los que
 solo exigen que fromRoman lance Error, y el stub ya lanza)"""),
            ("assistant", r"""Ronda verde: implementación mínima que hace pasar la MISMA lista sin tocarla. Dos decisiones: (a) `toRoman` por tabla sustractiva greedy (corta, obviamente correcta); (b) `fromRoman` parsea con signo y luego **valida la forma canónica** re-serializando: `toRoman(total) !== up` rechaza `IIII` y `IL` de una sola vez, sin enumerar reglas sustractivas. El bucle de ida-y-vuelta 1..3999 cierra la equivalencia para todo el dominio.

```js
'use strict';
// roman.test.js — ronda VERDE (TDD): misma lista de tests + implementacion
// spec: toRoman(n) / fromRoman(s), enteros 1..3999, forma canonica sustractiva

const TABLE = [[1000,'M'],[900,'CM'],[500,'D'],[400,'CD'],[100,'C'],[90,'XC'],
               [50,'L'],[40,'XL'],[10,'X'],[9,'IX'],[5,'V'],[4,'IV'],[1,'I']];

function toRoman(n) {
  if (!Number.isInteger(n) || n < 1 || n > 3999) throw new RangeError('n debe ser entero en [1, 3999]');
  let out = '';
  for (const [v, sym] of TABLE) { while (n >= v) { out += sym; n -= v; } }
  return out;
}

function fromRoman(s) {
  if (typeof s !== 'string' || s.length === 0) throw new Error('se requiere una cadena no vacia');
  const up = s.toUpperCase();
  const VAL = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };
  for (const ch of up) if (!(ch in VAL)) throw new Error('simbolo no romano: ' + ch);
  let total = 0;
  for (let i = 0; i < up.length; i++) {
    const v = VAL[up[i]];
    total += (i + 1 < up.length && VAL[up[i + 1]] > v) ? -v : v;
  }
  if (total < 1 || total > 3999 || toRoman(total) !== up) throw new Error('forma no canonica: ' + s);
  return total;
}

let passed = 0, failed = 0;
function check(name, fn) {
  try { if (fn()) { passed++; return; } } catch (e) { /* cuenta como fallo */ }
  failed++;
  console.log('FALLO ' + name);
}

check('toRoman(2024) === "MMXXIV"', () => toRoman(2024) === 'MMXXIV');
check('toRoman(4) es sustractivo', () => toRoman(4) === 'IV');
check('toRoman(3999) === "MMMCMXCIX"', () => toRoman(3999) === 'MMMCMXCIX');
check('toRoman(0) lanza RangeError', () => { try { toRoman(0); return false; } catch (e) { return e instanceof RangeError; } });
check('toRoman(1.5) lanza RangeError', () => { try { toRoman(1.5); return false; } catch (e) { return e instanceof RangeError; } });
check('fromRoman("mmxxiv") acepta minusculas', () => fromRoman('mmxxiv') === 2024);
check('fromRoman("IIII") rechaza (no canonica)', () => { try { fromRoman('IIII'); return false; } catch (e) { return e instanceof Error; } });
check('fromRoman("IL") rechaza (sustraccion invalida)', () => { try { fromRoman('IL'); return false; } catch (e) { return e instanceof Error; } });
check('fromRoman("") lanza Error', () => { try { fromRoman(''); return false; } catch (e) { return e instanceof Error; } });
check('ida y vuelta 1..3999', () => {
  for (let n = 1; n <= 3999; n++) if (fromRoman(toRoman(n)) !== n) return false;
  return true;
});

console.log(failed === 0 ? `OK ${passed}/${passed + failed} tests` : `FALLOS ${failed}/${passed + failed}`);
process.exit(failed === 0 ? 0 : 1);
```"""),
            ("tool", r"""$ node roman.test.js
OK 10/10 tests
$ echo $?
0"""),
            ("assistant", r"""Verde verificado: 10/10 con la misma lista de tests, `exit 0`. Balance del ciclo TDD:

- **El rojo fue informativo, no ceremonial:** fallaron 7/10 y los 3 que pasaron "por accidente" revelaron algo útil — los tests que solo exigen `Error` genérico no distinguen un stub de una implementación; por eso los casos de tipo (`RangeError`) exigen la clase exacta.
- **La validación canónica por re-serialización** (`toRoman(total) !== up`) salió de escribir los tests primero: rechazar `IIII`/`IL` con reglas sustractivas enumeradas es propenso a huecos; el invariante "fromRoman(x) debe re-serializar a x" los cubre todos y el bucle de ida-y-vuelta lo comprueba sobre los 3999 valores.
- **El harness es deliberadamente mínimo** (contadores, `console.log`, `process.exit`) para que los tests puedan correr en CI sin dependencias; si la lista crece, el siguiente paso natural es parametrizar `check` con casos y mantener el formato de salida.

Siguiente paso si lo pides en otro ciclo: refactor con la lista en verde (por ejemplo, memoizar la tabla `VAL` a nivel de módulo), sin tocar los tests."""),
        ],
        verify=[
            {"name": "tdd_rojo_con_stubs", "action": "run", "lang": "js",
             "msg": 2, "block": 0, "expect_fail": True,
             "expect_stdout_contains": ["FALLOS 7/10"],
             "timeout_s": 15},
            {"name": "tdd_verde_con_impl", "action": "run", "lang": "js",
             "msg": 4, "block": 0, "expect_exit": 0,
             "expect_stdout_contains": ["OK 10/10 tests"],
             "timeout_s": 15},
        ],
        tags=["testing", "tdd", "harness", "property_test"],
        stack=["javascript", "node"],
        recovery=True,
    ),
]
