"""Módulo insignia: sistemas en C — concurrencia, IPC, sockets, atomics, memoria.
Complementa el corpus de debugging C (ASan) con ingeniería de sistemas verificada."""
from schema import E

EXAMPLES = [
    # 1 ------------------------------------------------------------------ carrera hilo → mutex
    E(
        language="c", domain="systems", subdomain="concurrencia",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Este agregador lanza 8 hilos que contan eventos; el total debería ser 800000 pero sale menos y varía. Reproduce, diagnostica y corrige.\n"
                     "```c\n#define _GNU_SOURCE\n#include <pthread.h>\n#include <sched.h>\n#include <stdio.h>\n\n#define N 100000\nstatic long contador = 0;\n\nstatic void *trabajador(void *arg) {\n    (void)arg;\n    for (long i = 0; i < N; i++) {\n        if ((i & 63) == 0) sched_yield();\n        contador++;\n    }\n    return NULL;\n}\n\nint main(void) {\n    pthread_t h[8];\n    for (int i = 0; i < 8; i++) pthread_create(&h[i], NULL, trabajador, NULL);\n    for (int i = 0; i < 8; i++) pthread_join(h[i], NULL);\n    printf(\"total=%ld\\n\", contador);\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: total menor que 800000 y variable entre ejecuciones. Hipótesis: `contador++` compila a leer-modificar-escribir (load, add, store) NO atómico; dos hilos pueden leer el mismo valor y perder incrementos. Experimento: ejecutar varias veces y observar la variación."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra -pthread agregador.c -o agregador\n$ ./agregador\ntotal=738214\n$ ./agregador\ntotal=695108"),
            ("assistant", "Confirmado: 738214 y 695108 en dos corridas — actualizaciones perdidas. Causa raíz: carrera de datos sobre `contador` (dos hilos leen el mismo valor y ambos almacenan el incremento de ese mismo valor). Corrección: mutex que hace atómica la secuencia completa.\n"
                     "```c\n#define _GNU_SOURCE\n#include <pthread.h>\n#include <sched.h>\n#include <stdio.h>\n\n#define N 100000\nstatic long contador = 0;\nstatic pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;\n\nstatic void *trabajador(void *arg) {\n    (void)arg;\n    for (long i = 0; i < N; i++) {\n        if ((i & 63) == 0) sched_yield();\n        pthread_mutex_lock(&mutex);\n        contador++;\n        pthread_mutex_unlock(&mutex);\n    }\n    return NULL;\n}\n\nint main(void) {\n    pthread_t h[8];\n    for (int i = 0; i < 8; i++) pthread_create(&h[i], NULL, trabajador, NULL);\n    for (int i = 0; i < 8; i++) pthread_join(h[i], NULL);\n    printf(\"total=%ld\\n\", contador);\n    return 0;\n}\n```\nVerificación: repetidas corridas dan exactamente total=800000 (2 ejecuciones consecutivas en el tool siguiente)."),
            ("tool", "$ ./agregador\ntotal=800000\n$ ./agregador\ntotal=800000"),
            ("assistant", 'Verificado: dos corridas consecutivas del binario corregido dan exactamente total=800000; la carrera quedó eliminada y el coste del mutex es despreciable frente a la corrección.'),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "compile_run", "lang": "c", "msg": 1, "block": 0,
             "cargs": ["-pthread"], "expect_exit": 0, "expect_stdout_not_contains": ["total=800000"],
             "repeat": 2, "timeout_s": 20},
            {"name": "fix_exacto", "action": "compile_run", "lang": "c", "msg": 4, "block": 0,
             "cargs": ["-pthread"], "expect_exit": 0, "expect_stdout_contains": ["total=800000"],
             "repeat": 2, "timeout_s": 25},
        ],
        tags=["c", "pthread", "mutex", "race-condition"], stack=["c"], recovery=True,
    ),
    # 2 ------------------------------------------------------------------ productor/consumidor
    E(
        language="c", domain="systems", subdomain="concurrencia",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", "Implementa un productor/consumidor en C con cola circular limitada a 8 elementos: un productor envía los enteros 1..1000, un consumidor los suma. Debe ser libre de carreras y de espera activa, y terminar siempre."),
            ("assistant", "Plan: cola acotada protegida con mutex; DOS variables de condición (`no_llena`, `no_vacia`) para dormir a quien corresponda — sin espera activa; `while` (no `if`) tras cada `pthread_cond_wait` por despertares espurios; señal DENTRO del mutex para no perder despertares. Verificación: suma esperada 1..1000 = 500500.\n"
                     "```c\n#include <pthread.h>\n#include <stdio.h>\n\n#define CAP 8\n#define TOTAL 1000\n\nstatic int cola[CAP];\nstatic size_t n = 0;\nstatic pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;\nstatic pthread_cond_t no_llena = PTHREAD_COND_INITIALIZER;\nstatic pthread_cond_t no_vacia = PTHREAD_COND_INITIALIZER;\n\nstatic void *productor(void *arg) {\n    (void)arg;\n    for (int i = 1; i <= TOTAL; i++) {\n        pthread_mutex_lock(&m);\n        while (n == CAP) pthread_cond_wait(&no_llena, &m);\n        cola[n++] = i;\n        pthread_cond_signal(&no_vacia);\n        pthread_mutex_unlock(&m);\n    }\n    return NULL;\n}\n\nstatic void *consumidor(void *arg) {\n    (void)arg;\n    long suma = 0;\n    for (int i = 1; i <= TOTAL; i++) {\n        pthread_mutex_lock(&m);\n        while (n == 0) pthread_cond_wait(&no_vacia, &m);\n        suma += cola[--n];\n        pthread_cond_signal(&no_llena);\n        pthread_mutex_unlock(&m);\n    }\n    printf(\"suma=%ld\\n\", suma);\n    return NULL;\n}\n\nint main(void) {\n    pthread_t p, c;\n    pthread_create(&p, NULL, productor, NULL);\n    pthread_create(&c, NULL, consumidor, NULL);\n    pthread_join(p, NULL);\n    pthread_join(c, NULL);\n    return 0;\n}\n```\nVerificación: el consumidor imprime exactamente la suma 1..1000 = 500500 y el programa termina sin colgarse."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra -pthread prodcons.c -o prodcons\n$ ./prodcons\nsuma=500500\n$ ./prodcons\nsuma=500500"),
            ("assistant", 'Verificado: dos corridas consecutivas imprimen suma=500500 y el programa termina sin colgarse; el patrón while+condvar cubre despertares espurios y pérdida de señales.'),
        ],
        verify=[
            {"name": "prodcons", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "cargs": ["-pthread"], "expect_exit": 0, "expect_stdout_contains": ["suma=500500"],
             "repeat": 2, "timeout_s": 20},
        ],
        tags=["c", "pthread", "condvar", "productor-consumidor"], stack=["c"],
    ),
    # 3 ------------------------------------------------------------------ anillo SPSC atomics
    E(
        language="c", domain="systems", subdomain="concurrencia_sin_bloqueos",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", "Necesito un anillo SPSC (un productor, un consumidor) sin bloqueos en C11, capacidad 1024, para 200000 valores. Demuestra que la suma consumida coincide con la esperada y explica los memory order elegidos."),
            ("assistant", "Plan: `cabeza` lo escribe el productor y lo lee el consumidor; `cola` al revés. Cada índice se publica con `release` (garantiza que el dato del buffer es visible antes del índice) y se consume con `acquire`; la lectura de mi propio índice es `relaxed`. Operación con índices monótonos que envuelven módulo CAP sin ambigüedad (c − t nunca retrocede).\n"
                     "```c\n#define _GNU_SOURCE\n#include <pthread.h>\n#include <stdatomic.h>\n#include <stdio.h>\n\n#define CAP 1024\n#define TOTAL 200000\n\nstatic long buffer[CAP];\nstatic _Atomic size_t cabeza = 0;\nstatic _Atomic size_t base = 0;\nstatic _Atomic long suma_consumida = 0;\n\nstatic int push(long v) {\n    size_t c = atomic_load_explicit(&cabeza, memory_order_relaxed);\n    size_t b = atomic_load_explicit(&base, memory_order_acquire);\n    if (c - b == CAP) return 0;\n    buffer[c % CAP] = v;\n    atomic_store_explicit(&cabeza, c + 1, memory_order_release);\n    return 1;\n}\n\nstatic int pop(long *out) {\n    size_t b = atomic_load_explicit(&base, memory_order_relaxed);\n    size_t c = atomic_load_explicit(&cabeza, memory_order_acquire);\n    if (b == c) return 0;\n    *out = buffer[b % CAP];\n    atomic_store_explicit(&base, b + 1, memory_order_release);\n    return 1;\n}\n\nstatic void *prod(void *a) {\n    (void)a;\n    for (long i = 1; i <= TOTAL;) if (push(i)) i++;\n    return NULL;\n}\n\nstatic void *cons(void *a) {\n    (void)a;\n    long v;\n    for (;;) {\n        if (pop(&v)) {\n            atomic_fetch_add(&suma_consumida, v);\n            if (v == TOTAL) return NULL;\n        }\n    }\n}\n\nint main(void) {\n    pthread_t p, c;\n    pthread_create(&p, NULL, prod, NULL);\n    pthread_create(&c, NULL, cons, NULL);\n    pthread_join(p, NULL);\n    pthread_join(c, NULL);\n    long esperado = (long)TOTAL * (TOTAL + 1) / 2;\n    long obtenido = atomic_load(&suma_consumida);\n    printf(\"suma=%ld esperado=%ld ok=%d\\n\", obtenido, esperado, obtenido == esperado);\n    return 0;\n}\n```\nVerificación: la suma consumida coincide exactamente con 200000·200001/2."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra -pthread anillo.c -o anillo\n$ ./anillo\nsuma=20000100000 esperado=20000100000 ok=1"),
            ("assistant", 'Verificado: 200000 valores consumidos con suma exacta y sin bloqueos; los pares release/acquire garantizan que el dato es visible antes que el índice que lo anuncia.'),
        ],
        verify=[
            {"name": "anillo_spcc", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "cargs": ["-pthread"], "expect_exit": 0, "expect_stdout_contains": ["ok=1"],
             "timeout_s": 25},
        ],
        tags=["c", "atomics", "lock-free", "spsc", "memory-order"], stack=["c"],
    ),
    # 4 ------------------------------------------------------------------ poll echo server
    E(
        language="c", domain="systems", subdomain="sockets",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Escribe un servidor de eco TCP monoproceso con `poll()` (no forks, no hilos en el servidor) capaz de atender varias conexiones, y pruébalo con un cliente real dentro del mismo programa. Tras servir la sesión de prueba, debe terminar limpio."),
            ("assistant", "Plan: socket de escucha con `bind(0)` (puerto efímero) + `getsockname` para conocer el puerto real; hilo cliente que conecta, envía «hola-mundo» y comprueba el eco; el servidor usa `poll()` sobre escucha + conexiones activas, acepta y hace eco hasta que el cliente cierra; al terminar la prueba, cierre ordenado y mensaje final.\n"
                     "```c\n#define _GNU_SOURCE\n#include <arpa/inet.h>\n#include <netinet/in.h>\n#include <poll.h>\n#include <pthread.h>\n#include <stdio.h>\n#include <string.h>\n#include <sys/socket.h>\n#include <unistd.h>\n\nstatic int puerto_real = 0;\n\nstatic void *cliente(void *arg) {\n    (void)arg;\n    int fd = socket(AF_INET, SOCK_STREAM, 0);\n    struct sockaddr_in dir = {0};\n    dir.sin_family = AF_INET;\n    dir.sin_port = htons((uint16_t)puerto_real);\n    dir.sin_addr.s_addr = htonl(INADDR_LOOPBACK);\n    usleep(100000);\n    if (connect(fd, (struct sockaddr *)&dir, sizeof dir) != 0) {\n        perror(\"connect\");\n        return NULL;\n    }\n    const char *msg = \"hola-mundo\";\n    send(fd, msg, strlen(msg), 0);\n    char buf[128] = {0};\n    ssize_t n = recv(fd, buf, sizeof buf - 1, 0);\n    if (n > 0) printf(\"eco: %s\\n\", buf);\n    close(fd);\n    return NULL;\n}\n\nint main(void) {\n    int escucha = socket(AF_INET, SOCK_STREAM, 0);\n    int uno = 1;\n    setsockopt(escucha, SOL_SOCKET, SO_REUSEADDR, &uno, sizeof uno);\n    struct sockaddr_in dir = {0};\n    dir.sin_family = AF_INET;\n    dir.sin_port = htons(0);\n    dir.sin_addr.s_addr = htonl(INADDR_LOOPBACK);\n    bind(escucha, (struct sockaddr *)&dir, sizeof dir);\n    listen(escucha, 8);\n    socklen_t len = sizeof dir;\n    getsockname(escucha, (struct sockaddr *)&dir, &len);\n    puerto_real = ntohs(dir.sin_port);\n\n    pthread_t t;\n    pthread_create(&t, NULL, cliente, NULL);\n\n    struct pollfd pfd[16];\n    int nconn = 0;\n    pfd[0].fd = escucha;\n    pfd[0].events = POLLIN;\n    nconn = 1;\n    int sesiones = 0;\n    while (sesiones < 1) {\n        int listos = poll(pfd, (nfds_t)nconn, 3000);\n        if (listos <= 0) continue;\n        if (pfd[0].revents & POLLIN) {\n            int cli = accept(escucha, NULL, NULL);\n            if (nconn < 16) {\n                pfd[nconn].fd = cli;\n                pfd[nconn].events = POLLIN;\n                nconn++;\n            }\n        }\n        for (int i = 1; i < nconn; i++) {\n            if (pfd[i].revents & (POLLIN | POLLHUP)) {\n                char buf[256];\n                ssize_t n = recv(pfd[i].fd, buf, sizeof buf, 0);\n                if (n <= 0) {\n                    close(pfd[i].fd);\n                    pfd[i] = pfd[nconn - 1];\n                    nconn--;\n                    i--;\n                    sesiones++;\n                } else {\n                    send(pfd[i].fd, buf, (size_t)n, 0);\n                }\n            }\n        }\n    }\n    pthread_join(t, NULL);\n    close(escucha);\n    printf(\"servidor_fin\\n\");\n    return 0;\n}\n```\nVerificación: el cliente recibe exactamente el mensaje enviado (eco) y el servidor termina ordenado."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra -pthread eco_poll.c -o eco_poll\n$ ./eco_poll\neco: hola-mundo\nservidor_fin"),
            ("assistant", 'Verificado: el cliente recibe su eco y el servidor cierra en orden (servidor_fin); poll() atiende muchas conexiones en un solo hilo sin forks.'),
        ],
        verify=[
            {"name": "echo_poll", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "cargs": ["-pthread"], "expect_exit": 0,
             "expect_stdout_contains": ["eco: hola-mundo", "servidor_fin"], "timeout_s": 25},
        ],
        tags=["c", "poll", "sockets", "tcp", "io-multiplexing"], stack=["c"],
    ),
    # 5 ------------------------------------------------------------------ mmap copy
    E(
        language="c", domain="systems", subdomain="ficheros",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Implementa en C una copia de fichero con `mmap` (origen y destino mapeados) y verifica byte a byte que el destino es idéntico al origen. El fichero de prueba (1 MiB con patrón determinista) lo genera el propio programa."),
            ("assistant", "Plan: generar origen con patrón determinista (i·2654435761 mod 256); ftruncate para dar tamaño al destino; mapear ambos PROT_READ/PROT_WRITE MAP_SHARED; `memcpy` entre mapeos (el kernel hace la E/S por páginas bajo demanda); `msync`+`munmap`; comparación byte a byte con lectura ordinaria para NO verificar con el mismo mecanismo que la copia.\n"
                     "```c\n#define _GNU_SOURCE\n#include <fcntl.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <sys/mman.h>\n#include <sys/stat.h>\n#include <unistd.h>\n\n#define TAM (1024 * 1024)\n\nint main(void) {\n    const char *origen = \"origen.bin\";\n    const char *destino = \"destino.bin\";\n\n    int fo = open(origen, O_RDWR | O_CREAT | O_TRUNC, 0600);\n    if (fo < 0) return 1;\n    unsigned char patron = 0;\n    for (off_t i = 0; i < TAM; i++) {\n        patron = (unsigned char)((i * 2654435761u) & 0xff);\n        if (write(fo, &patron, 1) != 1) return 1;\n    }\n\n    int fd = open(destino, O_RDWR | O_CREAT | O_TRUNC, 0600);\n    if (fd < 0) return 1;\n    ftruncate(fd, TAM);\n\n    unsigned char *m_o = mmap(NULL, TAM, PROT_READ, MAP_SHARED, fo, 0);\n    unsigned char *m_d = mmap(NULL, TAM, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);\n    if (m_o == MAP_FAILED || m_d == MAP_FAILED) return 1;\n    memcpy(m_d, m_o, TAM);\n    msync(m_d, TAM, MS_SYNC);\n    munmap(m_d, TAM);\n    munmap(m_o, TAM);\n    close(fd);\n    close(fo);\n\n    int fc = open(origen, O_RDONLY);\n    int ff = open(destino, O_RDONLY);\n    static unsigned char b1[65536], b2[65536];\n    int identico = 1;\n    ssize_t r1, r2;\n    while ((r1 = read(fc, b1, sizeof b1)) > 0) {\n        r2 = read(ff, b2, sizeof b2);\n        if (r1 != r2 || memcmp(b1, b2, (size_t)r1) != 0) {\n            identico = 0;\n            break;\n        }\n    }\n    close(fc);\n    close(ff);\n    unlink(origen);\n    unlink(destino);\n    printf(\"identico=%d\\n\", identico);\n    return identico ? 0 : 1;\n}\n```\nVerificación: comparación byte a byte mediante read() ordinario (mecanismo distinto del mmap usado para copiar)."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra copia_mmap.c -o copia_mmap\n$ ./copia_mmap\nidentico=1"),
            ("assistant", 'Verificado: la comparación byte a byte con read() ordinario confirma la copia (identico=1), usando un mecanismo distinto del empleado para copiar.'),
        ],
        verify=[
            {"name": "mmap_copia", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["identico=1"], "timeout_s": 25},
        ],
        tags=["c", "mmap", "ficheros", "paginas"], stack=["c"],
    ),
    # 6 ------------------------------------------------------------------ fork+pipe bidireccional
    E(
        language="c", domain="systems", subdomain="ipc",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Implementa IPC bidireccional padre→hijo→padre con dos pipes: el padre envía la cadena «hola procesos», el hijo la convierte a mayúsculas y la devuelve; el padre imprime la respuesta. Sin esperas activas."),
            ("assistant", "Plan: `pipe(a)` padre→hijo y `pipe(b)` hijo→padre; cada proceso cierra los extremos que no usa (si no, el hijo nunca ve EOF y puede bloquearse); el hijo lee hasta EOF, transforma y responde; el padre escribe, cierra su extremo de escritura para señalizar fin, y lee la respuesta hasta EOF. read() bloqueante, cero polling.\n"
                     "```c\n#define _GNU_SOURCE\n#include <ctype.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <sys/wait.h>\n#include <unistd.h>\n\nint main(void) {\n    int a[2], b[2];\n    if (pipe(a) != 0 || pipe(b) != 0) return 1;\n\n    pid_t pid = fork();\n    if (pid < 0) return 1;\n    if (pid == 0) {\n        close(a[1]);\n        close(b[0]);\n        char buf[256];\n        ssize_t n;\n        size_t total = 0;\n        while ((n = read(a[0], buf + total, sizeof buf - 1 - total)) > 0) {\n            total += (size_t)n;\n            if (total >= sizeof buf - 1) break;\n        }\n        buf[total] = 0;\n        for (size_t i = 0; i < total; i++) buf[i] = (char)toupper((unsigned char)buf[i]);\n        write(b[1], buf, total);\n        close(a[0]);\n        close(b[1]);\n        _exit(0);\n    }\n    close(a[0]);\n    close(b[1]);\n    const char *msg = \"hola procesos\";\n    write(a[1], msg, strlen(msg));\n    close(a[1]);\n\n    char resp[256] = {0};\n    ssize_t n;\n    size_t total = 0;\n    while ((n = read(b[0], resp + total, sizeof resp - 1 - total)) > 0) {\n        total += (size_t)n;\n        if (total >= sizeof resp - 1) break;\n    }\n    close(b[0]);\n    waitpid(pid, NULL, 0);\n    printf(\"respuesta: %s\\n\", resp);\n    return strcmp(resp, \"HOLA PROCESOS\") == 0 ? 0 : 1;\n}\n```\nVerificación: la respuesta es exactamente la cadena en mayúsculas y el hijo queda reaped."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra ipc_pipes.c -o ipc_pipes\n$ ./ipc_pipes\nrespuesta: HOLA PROCESOS"),
            ("assistant", 'Verificado: el padre recibe exactamente «HOLA PROCESOS» y el hijo queda reaped; cerrar los extremos no usados es lo que permite que read() vea EOF.'),
        ],
        verify=[
            {"name": "ipc_pipes", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["respuesta: HOLA PROCESOS"], "timeout_s": 20},
        ],
        tags=["c", "fork", "pipe", "ipc"], stack=["c"],
    ),
    # 7 ------------------------------------------------------------------ reaper de hijos
    E(
        language="c", domain="systems", subdomain="procesos",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Lanzo 8 procesos hijos que terminan escalonadamente, pero mi código solo «recoge» uno y el resto quedan huérfanos/zombies hasta que el padre muere. Aquí está el bucle del padre:\n"
                     "```c\n#define _GNU_SOURCE\n#include <stdio.h>\n#include <sys/wait.h>\n#include <unistd.h>\n\nint main(void) {\n    for (int i = 0; i < 8; i++) {\n        pid_t pid = fork();\n        if (pid == 0) {\n            usleep(50000u * (unsigned)(i + 1));\n            _exit(0);\n        }\n    }\n    int reaped = 0;\n    if (waitpid(-1, NULL, 0) > 0) reaped = 1;   /* solo UNO */\n    printf(\"reaped=%d\\n\", reaped);\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: un solo hijo recogido; los demás quedan como zombies mientras el padre viva. Hipótesis: `waitpid` recoge EXACTAMENTE un hijo por llamada; hay que iterar hasta que no queden (ECHILD). Experimento: contar cuántos recoge el código actual frente a un bucle con `waitpid(-1, ..., 0)` hasta error ECHILD.\n"
                     "```c\n#define _GNU_SOURCE\n#include <errno.h>\n#include <stdio.h>\n#include <sys/wait.h>\n#include <unistd.h>\n\nint main(void) {\n    for (int i = 0; i < 8; i++) {\n        pid_t pid = fork();\n        if (pid == 0) {\n            usleep(50000u * (unsigned)(i + 1));\n            _exit(0);\n        }\n    }\n    int reaped = 0;\n    while (waitpid(-1, NULL, 0) > 0) reaped++;\n    if (errno != ECHILD) return 1;\n    printf(\"reaped=%d\\n\", reaped);\n    return reaped == 8 ? 0 : 1;\n}\n```\nVerificación: el bucle recoge los 8 (el último sale a los 400 ms) y detecta ECHILD al no quedar ninguno."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra reaper.c -o reaper\n$ ./reaper\nreaped=8\n$ ./reaper\nreaped=8"),
            ("assistant", 'Verificado: dos corridas consecutivas recogen los 8 hijos (reaped=8) y detectan ECHILD al agotarse; sin bucle, cada waitpid solo recoge uno.'),
        ],
        verify=[
            {"name": "bug_un_solo_hijo", "action": "compile_run", "lang": "c", "msg": 1, "block": 0,
             "expect_exit": 0, "expect_stdout_not_contains": ["reaped=8"], "timeout_s": 20},
            {"name": "fix_reaped_8", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["reaped=8"], "timeout_s": 25},
        ],
        tags=["c", "fork", "waitpid", "zombies"], stack=["c"], recovery=True,
    ),
    # 8 ------------------------------------------------------------------ flock exclusión
    E(
        language="c", domain="systems", subdomain="sincronizacion_procesos",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", "Cuatro procesos independientes (forks del mismo binario) incrementan un contador compartido en un fichero 1000 veces cada uno. Con la implementación actual el total no llega a 4000. Implementa la versión correcta con `flock` y demuestra ambos comportamientos."),
            ("assistant", "Plan: el bug — leer contador, ceder CPU, escribir+1 — deja una ventana enorme entre lectura y escritura: todos leen el mismo valor y pierden incrementos. La corrección: `flock(LOCK_EX)` (exclusivo, inter-proceso) alrededor de TODA la secuencia leer-modificar-escribir, con el fichero abierto en el propio proceso antes del flock. Demostración en un solo binario: modo `bug` y modo `fix` seleccionado por argv.\n"
                     "```c\n#define _GNU_SOURCE\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <fcntl.h>\n#include <sys/file.h>\n#include <sys/wait.h>\n#include <unistd.h>\n\nstatic int incrementar(const char *ruta, int con_flock) {\n    int fd = open(ruta, O_RDWR | O_CREAT, 0600);\n    if (fd < 0) return -1;\n    int valor = 0;\n    char buf[32] = {0};\n    if (con_flock && flock(fd, LOCK_EX) != 0) {\n        close(fd);\n        return -1;\n    }\n    ssize_t n = read(fd, buf, sizeof buf - 1);\n    if (n > 0) valor = atoi(buf);\n    if (!con_flock) usleep(0);\n    valor++;\n    lseek(fd, 0, SEEK_SET);\n    ftruncate(fd, 0);\n    dprintf(fd, \"%d\", valor);\n    if (con_flock) flock(fd, LOCK_UN);\n    close(fd);\n    return valor;\n}\n\nint main(int argc, char **argv) {\n    if (argc != 3) return 2;\n    int con_flock = strcmp(argv[2], \"fix\") == 0;\n    if (fork() == 0) {\n        for (int i = 0; i < 1000; i++) incrementar(argv[1], con_flock);\n        _exit(0);\n    }\n    if (fork() == 0) {\n        for (int i = 0; i < 1000; i++) incrementar(argv[1], con_flock);\n        _exit(0);\n    }\n    if (fork() == 0) {\n        for (int i = 0; i < 1000; i++) incrementar(argv[1], con_flock);\n        _exit(0);\n    }\n    if (fork() == 0) {\n        for (int i = 0; i < 1000; i++) incrementar(argv[1], con_flock);\n        _exit(0);\n    }\n    for (int i = 0; i < 4; i++) wait(NULL);\n    int fd = open(argv[1], O_RDONLY);\n    char buf[32] = {0};\n    read(fd, buf, sizeof buf - 1);\n    printf(\"total=%s\\n\", buf);\n    close(fd);\n    unlink(argv[1]);\n    return 0;\n}\n```\nVerificación: modo bug pierde actualizaciones (total < 4000); modo fix da exactamente 4000 en repetidas corridas."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra contador_flock.c -o contador\n$ ./contador cnt.bin bug\ntotal=1893\n$ ./contador cnt.bin fix\ntotal=4000\n$ ./contador cnt.bin fix\ntotal=4000"),
            ("assistant", 'Verificado: el modo bug pierde actualizaciones de forma repetible y el modo fix da total=4000 en corridas consecutivas; flock serializa la secuencia completa leer-escribir.'),
        ],
        verify=[
            {"name": "bug_pierde", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "args": ["cnt.bin", "bug"], "expect_exit": 0,
             "expect_stdout_not_contains": ["total=4000"], "repeat": 2, "timeout_s": 25},
            {"name": "fix_exacto", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "args": ["cnt2.bin", "fix"], "expect_exit": 0, "expect_stdout_contains": ["total=4000"],
             "repeat": 2, "timeout_s": 25},
        ],
        tags=["c", "flock", "procesos", "exclusion-mutua"], stack=["c"], recovery=True,
    ),
    # 9 ------------------------------------------------------------------ read parcial
    E(
        language="c", domain="systems", subdomain="io",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Este receptor debería recibir 200000 bytes por un pipe (el emisor los escribe todos) pero solo procesa 4096. Código del receptor:\n"
                     "```c\n#define _GNU_SOURCE\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <sys/wait.h>\n#include <unistd.h>\n\nint main(void) {\n    int pipefd[2];\n    if (pipe(pipefd) != 0) return 1;\n    pid_t pid = fork();\n    if (pid == 0) {\n        close(pipefd[0]);\n        static char datos[200000];\n        memset(datos, 7, sizeof datos);\n        size_t enviados = 0;\n        while (enviados < sizeof datos) {\n            ssize_t w = write(pipefd[1], datos + enviados, sizeof datos - enviados);\n            if (w <= 0) _exit(1);\n            enviados += (size_t)w;\n        }\n        close(pipefd[1]);\n        _exit(0);\n    }\n    close(pipefd[1]);\n    char buf[4096];\n    ssize_t n = read(pipefd[0], buf, sizeof buf);   /* UNA lectura */\n    close(pipefd[0]);\n    waitpid(pid, NULL, 0);\n    printf(\"recibidos=%zd\\n\", n);\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: 4096 recibidos en vez de 200000. Hipótesis: `read()` sobre un pipe devuelve CUANDO HAY DATOS DISPONIBLES, no cuando el búfer del llamador se llena: una única llamada devuelve lo que hubiera al instante (≤ tamaño del búfer). Es una lectura corta, no un error. Experimento: ya visible en el código — una sola `read` de 4096 nunca puede acumular 200000. Corrección: bucle hasta EOF (read devuelve 0 cuando el emisor cierra).\n"
                     "```c\n#define _GNU_SOURCE\n#include <stdio.h>\n#include <string.h>\n#include <sys/wait.h>\n#include <unistd.h>\n\nint main(void) {\n    int pipefd[2];\n    if (pipe(pipefd) != 0) return 1;\n    pid_t pid = fork();\n    if (pid == 0) {\n        close(pipefd[0]);\n        static char datos[200000];\n        memset(datos, 7, sizeof datos);\n        size_t enviados = 0;\n        while (enviados < sizeof datos) {\n            ssize_t w = write(pipefd[1], datos + enviados, sizeof datos - enviados);\n            if (w <= 0) _exit(1);\n            enviados += (size_t)w;\n        }\n        close(pipefd[1]);\n        _exit(0);\n    }\n    close(pipefd[1]);\n    size_t total = 0;\n    ssize_t n;\n    char buf[4096];\n    while ((n = read(pipefd[0], buf, sizeof buf)) > 0) {\n        total += (size_t)n;\n    }\n    close(pipefd[0]);\n    waitpid(pid, NULL, 0);\n    printf(\"recibidos=%zu\\n\", total);\n    return total == 200000 ? 0 : 1;\n}\n```\nVerificación: el bucle acumula exactamente los 200000 bytes enviados."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra receptor.c -o receptor\n$ ./receptor\nrecibidos=200000"),
            ("assistant", 'Verificado: el bucle acumula exactamente 200000 bytes; read() es corto por naturaleza — devuelve lo disponible en el instante, no lo pedido.'),
        ],
        verify=[
            {"name": "bug_una_lectura", "action": "compile_run", "lang": "c", "msg": 1, "block": 0,
             "expect_exit": 0, "expect_stdout_not_contains": ["recibidos=200000"], "timeout_s": 20},
            {"name": "fix_bucle", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["recibidos=200000"], "timeout_s": 20},
        ],
        tags=["c", "read", "pipe", "short-reads", "io"], stack=["c"], recovery=True,
    ),
    # 10 ----------------------------------------------------------------- endianness
    E(
        language="c", domain="systems", subdomain="serializacion",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Nuestro productor envía registros {id, monto} binarios a un servicio que decodifica con orden de red (big-endian). En x86 el servicio recibe valores absurdos. Este es el envío actual:\n"
                     "```c\n#define _GNU_SOURCE\n#include <arpa/inet.h>\n#include <stdio.h>\n#include <string.h>\n\nstruct registro {\n    unsigned int id;\n    unsigned int monto;\n};\n\nstatic unsigned int decodifica_u32_be(const unsigned char *b) {\n    return ((unsigned int)b[0] << 24) | ((unsigned int)b[1] << 16)\n         | ((unsigned int)b[2] << 8) | (unsigned int)b[3];\n}\n\nint main(void) {\n    struct registro r = {1000u, 250000u};\n    unsigned char trama[sizeof r];\n    memcpy(trama, &r, sizeof r);          /* ¿qué orden es esto? */\n    unsigned int id = decodifica_u32_be(trama);\n    unsigned int monto = decodifica_u32_be(trama + 4);\n    printf(\"id=%u monto=%u ok=%d\\n\", id, monto, id == 1000u && monto == 250000u);\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: el receptor big-endian ve valores absurdos. Hipótesis: `memcpy` de la estructura copia la representación DEL HOST; en x86 (little-endian) los bytes quedan al revés de lo que el decodificador big-endian espera. Experimento: decodificar la trama con orden de red aquí mismo — si da valores trocados, confirmado.\n"
                     "```c\n#define _GNU_SOURCE\n#include <arpa/inet.h>\n#include <stdio.h>\n\nstruct registro {\n    unsigned int id;\n    unsigned int monto;\n};\n\nstatic void codifica_u32_be(unsigned char *b, unsigned int v) {\n    unsigned int be = htonl(v);\n    b[0] = (unsigned char)(be & 0xff);\n    b[1] = (unsigned char)((be >> 8) & 0xff);\n    b[2] = (unsigned char)((be >> 16) & 0xff);\n    b[3] = (unsigned char)((be >> 24) & 0xff);\n}\n\nstatic unsigned int decodifica_u32_be(const unsigned char *b) {\n    return ((unsigned int)b[0] << 24) | ((unsigned int)b[1] << 16)\n         | ((unsigned int)b[2] << 8) | (unsigned int)b[3];\n}\n\nint main(void) {\n    struct registro r = {1000u, 250000u};\n    unsigned char trama[8];\n    codifica_u32_be(trama, r.id);\n    codifica_u32_be(trama + 4, r.monto);\n    unsigned int id = decodifica_u32_be(trama);\n    unsigned int monto = decodifica_u32_be(trama + 4);\n    printf(\"id=%u monto=%u ok=%d\\n\", id, monto, id == 1000u && monto == 250000u);\n    return (id == 1000u && monto == 250000u) ? 0 : 1;\n}\n```\nVerificación: codificar con htonl (o manual big-endian) y decodificar produce los valores originales; la regla: serializar CAMPO A CAMPO con orden explícito, jamás con la representación del host."),
            ("tool", "$ gcc -std=c11 -O2 -Wall -Wextra trama_be.c -o trama_be\n$ ./trama_be\nid=1000 monto=250000 ok=1"),
            ("assistant", 'Verificado: con codificación big-endian explícita los valores sobreviven el viaje (ok=1); serializar campo a campo es la única forma portable entre arquitecturas.'),
        ],
        verify=[
            {"name": "bug_host_endian", "action": "compile_run", "lang": "c", "msg": 1, "block": 0,
             "expect_exit": 0, "expect_stdout_not_contains": ["ok=1"], "timeout_s": 20},
            {"name": "fix_red", "action": "compile_run", "lang": "c", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["id=1000 monto=250000 ok=1"], "timeout_s": 20},
        ],
        tags=["c", "endianness", "serializacion", "redes"], stack=["c"], recovery=True,
    ),
]
