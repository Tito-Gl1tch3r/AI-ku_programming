"""Módulo insignia: C++ moderno — RAII, ownership, STL, variant/optional, concurrencia, C++20."""
from schema import E

EXAMPLES = [
    # 1 ------------------------------------------------------------------ RAII fuga
    E(
        language="cpp", domain="systems", subdomain="raii",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Este procesador de lotes reserva un buffer de auditoría y devuelve códigos de error; el sanitizador de fugas se queja en producción. Código:\n"
                     "```cpp\n#include <cstdio>\n#include <cstdlib>\n\nint procesa(int modo) {\n    char *traza = static_cast<char *>(std::malloc(1024));   /* buffer de auditoría */\n    if (traza == nullptr) return -1;\n    if (modo == 1) {\n        return 1;                       /* retorno temprano */\n    }\n    std::free(traza);\n    return 0;\n}\n\nint main() {\n    int rc = procesa(1);\n    std::printf(\"rc=%d\\n\", rc);\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: LeakSanitizer detecta fuga en la ruta de error. Causa raíz: gestión manual del recurso con múltiples puntos de salida — el `return 1` temprano se salta el `fclose`. Corrección RAII: encapsular el FILE* en un guard cuyo destructor cierra SIEMPRE, pase lo que pase (incluidas excepciones).\n"
                     "```cpp\n#include <cstdio>\n\nclass FileGuard {\npublic:\n    explicit FileGuard(const char *ruta, const char *modo)\n        : f_(std::fopen(ruta, modo)) {}\n    ~FileGuard() {\n        if (f_) {\n            std::fclose(f_);\n        }\n    }\n    FileGuard(const FileGuard &) = delete;\n    FileGuard &operator=(const FileGuard &) = delete;\n    bool ok() const { return f_ != nullptr; }\n    FILE *get() const { return f_; }\n\nprivate:\n    FILE *f_;\n};\n\nint procesa(const char *ruta) {\n    FileGuard audit(\"auditoria.log\", \"a\");\n    if (!audit.ok()) return -1;\n    std::fprintf(audit.get(), \"inicio %s\\n\", ruta);\n    if (ruta == nullptr || ruta[0] == 0) {\n        return 1;                       /* el destructor cierra igualmente */\n    }\n    std::fprintf(audit.get(), \"fin %s\\n\", ruta);\n    return 0;\n}\n\nint main() {\n    int rc = procesa(\"\");\n    std::printf(\"rc=%d\\n\", rc);\n    return 0;\n}\n```\nVerificación: con -fsanitize=address el original reporta fuga y sale con error; la versión RAII cierra el fichero en todos los caminos y termina limpio."),
            ("tool", "$ g++ -std=c++17 -O1 -g -fsanitize=address lote_roto.cpp -o lote_roto\n$ ./lote_roto\nrc=1\n=================================================================\n==ERROR: LeakSanitizer: detected memory leaks\n\nDirect leak of 336 byte(s) ... allocated by ... fopen\n$ g++ -std=c++17 -O1 -g -fsanitize=address lote_raii.cpp -o lote_raii\n$ ./lote_raii\nrc=1"),
            ("assistant", 'Verificado: el original sale con LeakSanitizer en rojo y la versión RAII termina limpia manteniendo rc=1; el destructor es el único responsable del cierre.'),
        ],
        verify=[
            {"name": "bug_fuga", "action": "compile_run", "lang": "cpp", "msg": 1, "block": 0,
             "cargs": ["-fsanitize=address", "-g"], "expect_fail": True, "timeout_s": 20},
            {"name": "fix_raii", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "cargs": ["-fsanitize=address", "-g"], "expect_exit": 0, "expect_stdout_contains": ["rc=1"],
             "timeout_s": 20},
        ],
        tags=["cpp", "raii", "leaks", "asan", "recursos"], stack=["cpp"], recovery=True,
    ),
    # 2 ------------------------------------------------------------------ thread sin join
    E(
        language="cpp", domain="systems", subdomain="concurrencia",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Este worker lanza un hilo para vaciar una cola y el programa muere con terminate justo al salir de main, aunque el hilo «termina rápido». ¿Qué está pasando?\n"
                     "```cpp\n#include <chrono>\n#include <cstdio>\n#include <thread>\n\nint main() {\n    std::thread limpiador([] {\n        std::this_thread::sleep_for(std::chrono::milliseconds(50));\n        std::puts(\"cola_vaciada\");\n    });\n    /* ¿falta algo? */\n    std::puts(\"main_fin\");\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: std::terminate al destruir el objeto thread. Causa raíz: si un `std::thread` es joinable cuando se destruye, el estándar ordena llamar a `std::terminate` — destruir no «mata» el hilo ni lo espera. Experimento: el abort ocurre SIEMPRE que main sale antes del join, no depende de la velocidad del hilo. Corrección: decidir la semántica — `join()` (esperarlo) o `detach()` (liberarlo) — y con C++20 `std::jthread` lo hace el destructor por ti.\n"
                     "```cpp\n#include <chrono>\n#include <cstdio>\n#include <thread>\n\nint main() {\n    std::jthread limpiador([] {\n        std::this_thread::sleep_for(std::chrono::milliseconds(50));\n        std::puts(\"cola_vaciada\");\n    });\n    std::puts(\"main_fin\");\n    return 0;\n}\n```\nVerificación: con jthread el destructor hace join automáticamente; el programa imprime main_fin, espera la cola y termina con exit 0 (el original aborta con SIGABRT)."),
            ("tool", "$ g++ -std=c++20 -O2 worker_roto.cpp -o worker_roto\n$ ./worker_roto\nmain_fin\nterminate called without an active exception\nAborted (core dumped)\n$ g++ -std=c++20 -O2 worker_jthread.cpp -o worker_jthread\n$ ./worker_jthread\nmain_fin\ncola_vaciada"),
            ("assistant", 'Verificado: el original aborta por terminate y la versión con jthread imprime main_fin y cola_vaciada con exit 0; la propiedad del hilo decide el cierre.'),
        ],
        verify=[
            {"name": "bug_terminate", "action": "compile_run", "lang": "cpp", "msg": 1, "block": 0,
             "cargs": ["-std=c++20"], "expect_fail": True, "timeout_s": 20},
            {"name": "fix_jthread", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "cargs": ["-std=c++20"], "expect_exit": 0,
             "expect_stdout_contains": ["main_fin", "cola_vaciada"], "timeout_s": 20},
        ],
        tags=["cpp", "threads", "jthread", "terminate", "lifetime"], stack=["cpp"], recovery=True,
    ),
    # 3 ------------------------------------------------------------------ erase en iteración
    E(
        language="cpp", domain="systems", subdomain="stl",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Quiero eliminar los negativos de un vector mientras lo recorro, pero el resultado deja negativos sin borrar. Código:\n"
                     "```cpp\n#include <cstdio>\n#include <vector>\n\nint main() {\n    std::vector<int> v{3, -1, 4, -1, -5, 9, -2, 6};\n    for (auto it = v.begin(); it != v.end(); ++it) {\n        if (*it < 0) {\n            v.erase(it);\n        }\n    }\n    for (int x : v) std::printf(\"%d \", x);\n    std::printf(\"\\n\");\n    bool ok = true;\n    for (int x : v) if (x < 0) ok = false;\n    std::printf(\"ok=%d\\n\", ok ? 1 : 0);\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: quedan negativos tras el borrado. Causa raíz: `erase(it)` INVALIDA `it` y devuelve el iterador al elemento siguiente; el `++it` del bucle se salta ese elemento (y seguir usando el iterador invalidado es UB). Corrección canónica: erase-remove (`std::remove_if` + `erase`), O(n) y sin bucles manuales.\n"
                     "```cpp\n#include <algorithm>\n#include <cstdio>\n#include <vector>\n\nint main() {\n    std::vector<int> v{3, -1, 4, -1, -5, 9, -2, 6};\n    v.erase(std::remove_if(v.begin(), v.end(),\n                           [](int x) { return x < 0; }),\n            v.end());\n    for (int x : v) std::printf(\"%d \", x);\n    std::printf(\"\\n\");\n    bool ok = true;\n    for (int x : v) if (x < 0) ok = false;\n    std::printf(\"ok=%d\\n\", ok ? 1 : 0);\n    return ok ? 0 : 1;\n}\n```\nVerificación: el resultado es 3 4 9 6 sin negativos (ok=1); patrón aplicable a cualquier filtrado de contenedor secuencial."),
            ("tool", "$ g++ -std=c++17 -O2 -Wall -Wextra filtrado_roto.cpp -o filtrado_roto\n$ ./filtrado_roto\n3 4 -5 9 6 \nok=0\n$ g++ -std=c++17 -O2 -Wall -Wextra filtrado_ok.cpp -o filtrado_ok\n$ ./filtrado_ok\n3 4 9 6 \nok=1"),
            ("assistant", 'Verificado: salida 3 4 9 6 con ok=1; erase-remove es O(n), no deja iteradores invalidados y no depende de la sutileza de erase.'),
        ],
        verify=[
            {"name": "bug_salta_elementos", "action": "compile_run", "lang": "cpp", "msg": 1, "block": 0,
             "expect_exit": 0, "expect_stdout_not_contains": ["ok=1"], "timeout_s": 20},
            {"name": "fix_erase_remove", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["3 4 9 6", "ok=1"], "timeout_s": 20},
        ],
        tags=["cpp", "stl", "erase-remove", "iteradores"], stack=["cpp"], recovery=True,
    ),
    # 4 ------------------------------------------------------------------ shared_ptr ciclo
    E(
        language="cpp", domain="systems", subdomain="ownership",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Este grafo de nodos con shared_ptr mutuos no destruye nunca los objetos: los destructores no aparecen. Código mínimo:\n"
                     "```cpp\n#include <cstdio>\n#include <memory>\n#include <string>\n\nstruct Nodo {\n    std::string nombre;\n    std::shared_ptr<Nodo> otro;\n    explicit Nodo(std::string n) : nombre(std::move(n)) {\n        std::printf(\"nace %s\\n\", nombre.c_str());\n    }\n    ~Nodo() {\n        std::printf(\"muere %s\\n\", nombre.c_str());\n    }\n};\n\nint main() {\n    auto a = std::make_shared<Nodo>(\"A\");\n    auto b = std::make_shared<Nodo>(\"B\");\n    a->otro = b;\n    b->otro = a;\n    std::printf(\"fin alcance\\n\");\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: los destructores nunca se ejecutan. Causa raíz: ciclo de shared_ptr — A mantiene a B y B mantiene a A; los conteos de referencia nunca llegan a 0 (fuga lógica, no detectable por LeakSanitizer como leak del montón porque los objetos aún están referenciados). Corrección: romper el ciclo con `std::weak_ptr` en la referencia de vuelta; el propietario único es la arista «padre→hijo».\n"
                     "```cpp\n#include <cstdio>\n#include <memory>\n#include <string>\n\nstruct Nodo {\n    std::string nombre;\n    std::weak_ptr<Nodo> otro;\n    explicit Nodo(std::string n) : nombre(std::move(n)) {\n        std::printf(\"nace %s\\n\", nombre.c_str());\n    }\n    ~Nodo() {\n        std::printf(\"muere %s\\n\", nombre.c_str());\n    }\n};\n\nint main() {\n    auto a = std::make_shared<Nodo>(\"A\");\n    auto b = std::make_shared<Nodo>(\"B\");\n    a->otro = b;\n    b->otro = a;\n    std::printf(\"fin alcance\\n\");\n    return 0;\n}\n```\nVerificación: al salir del alcance ambos destructores se ejecutan (muere A, muere B). Regla: shared_ptr para ownership, weak_ptr para relaciones de vuelta y cachés observadoras."),
            ("tool", "$ g++ -std=c++17 -O2 grafo_roto.cpp -o grafo_roto\n$ ./grafo_roto\nnace A\nnace B\nfin alcance\n(no hay 'muere')\n$ g++ -std=c++17 -O2 grafo_ok.cpp -o grafo_ok\n$ ./grafo_ok\nnace A\nnace B\nfin alcance\nmuere B\nmuere A"),
            ("assistant", 'Verificado: con weak_ptr ambos destructores se ejecutan al salir del alcance; el ciclo de shared_ptr es una fuga lógica invisible para LeakSanitizer.'),
        ],
        verify=[
            {"name": "bug_ciclo", "action": "compile_run", "lang": "cpp", "msg": 1, "block": 0,
             "expect_exit": 0, "expect_stdout_not_contains": ["muere"], "timeout_s": 20},
            {"name": "fix_weak_ptr", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["muere B", "muere A"], "timeout_s": 20},
        ],
        tags=["cpp", "shared-ptr", "weak-ptr", "ciclos", "ownership"], stack=["cpp"], recovery=True,
    ),
    # 5 ------------------------------------------------------------------ optional API
    E(
        language="cpp", domain="systems", subdomain="diseno_api",
        difficulty="hard", task_type="refactoring",
        messages=[
            ("user", "Esta API de búsqueda devuelve -1 como «no encontrado» y el código cliente ya ha confundido un id legítimo con el centinela. Rediseña la interfaz con C++17 para que el caso vacío sea imposible de ignorar, manteniendo la funcionalidad."),
            ("assistant", "Plan: reemplazar el centinela -1 por `std::optional<int>` — el tipo comunica en la FIRMA que puede no haber resultado, y el compilador obliga a decidir antes de desreferenciar. Mantengo el mismo algoritmo de búsqueda binaria y añado pruebas del caso vacío y de valores reales.\n"
                     "```cpp\n#include <algorithm>\n#include <cstdio>\n#include <optional>\n#include <vector>\n\nstatic std::optional<int> busca(const std::vector<int> &ordenado, int objetivo) {\n    auto it = std::lower_bound(ordenado.begin(), ordenado.end(), objetivo);\n    if (it != ordenado.end() && *it == objetivo) {\n        return static_cast<int>(it - ordenado.begin());\n    }\n    return std::nullopt;\n}\n\nint main() {\n    std::vector<int> datos{2, 4, 6, 8, 10};\n    auto r1 = busca(datos, 8);\n    auto r2 = busca(datos, 7);\n    bool ok = r1.has_value() && *r1 == 3 && !r2.has_value();\n    std::printf(\"indice=%d ausente=%d ok=%d\\n\",\n                r1.value_or(-1), !r2.has_value() ? 1 : 0, ok ? 1 : 0);\n    return ok ? 0 : 1;\n}\n```\nVerificación: la búsqueda del 8 da índice 3, la del 7 devuelve nullopt y el cliente no puede confundir «no encontrado» con un índice válido (los índices son ≥ 0, pero el tipo hace la decisión explícita y grep-able)."),
            ("tool", "$ g++ -std=c++17 -O2 -Wall -Wextra busca_optional.cpp -o busca_optional\n$ ./busca_optional\nindice=3 ausente=1 ok=1"),
            ("assistant", 'Verificado: índice 3 para el 8 y nullopt para el 7 (ok=1); el caso vacío ahora vive en el tipo y el compilador obliga a tratarlo.'),
        ],
        verify=[
            {"name": "optional_api", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["ok=1"], "timeout_s": 20},
        ],
        tags=["cpp", "optional", "api", "refactoring", "cpp17"], stack=["cpp"],
    ),
    # 6 ------------------------------------------------------------------ variant máquina
    E(
        language="cpp", domain="systems", subdomain="maquinas_de_estado",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", "Implementa una máquina de estados para un parser de órdenes con tres estados (Esperando, Acumulando, Ejecutando) usando `std::variant` + `std::visit` (sin herencia ni punteros). Eventos: `inicio`, `token(valor)`, `fin`. La suma de tokens acumulados debe imprimirse al ejecutar; demuéstralo con la secuencia inicio,7,8,fin → resultado 15."),
            ("assistant", "Plan: cada estado es un struct (datos que porta ese estado); la máquina completa es `std::variant<Esperando, Acumulando, Ejecutando>`; las transiciones viven en `std::visit` con overloads — el compilador garantiza exhaustividad (añadir un estado rompe la compilación si falta su rama, en lugar de fallar en runtime).\n"
                     "```cpp\n#include <cstdio>\n#include <string>\n#include <variant>\n#include <vector>\n\nstruct Inicio {};\nstruct Acumulando { long suma = 0; };\nstruct Ejecutando { long total = 0; };\n\nstruct EvInicio {};\nstruct EvToken { long valor; };\nstruct EvFin {};\nusing Evento = std::variant<EvInicio, EvToken, EvFin>;\nusing Estado = std::variant<Inicio, Acumulando, Ejecutando>;\n\ntemplate <class... Ts> struct overload : Ts... { using Ts::operator()...; };\ntemplate <class... Ts> overload(Ts...) -> overload<Ts...>;\n\nstatic Estado transiciona(const Estado &e, const Evento &ev) {\n    return std::visit(overload{\n        [](const Inicio &, const EvInicio &) -> Estado { return Acumulando{}; },\n        [](const Inicio &, const EvToken &) -> Estado { return Inicio{}; },\n        [](const Inicio &, const EvFin &) -> Estado { return Inicio{}; },\n        [](const Acumulando &a, const EvToken &t) -> Estado { return Acumulando{a.suma + t.valor}; },\n        [](const Acumulando &a, const EvFin &) -> Estado { return Ejecutando{a.suma}; },\n        [](const Acumulando &, const EvInicio &) -> Estado { return Acumulando{}; },\n        [](const Ejecutando &e, const EvInicio &) -> Estado { return Acumulando{}; },\n        [](const Ejecutando &ejec, const auto &) -> Estado { return ejec; }},\n        e, ev);\n}\n\nint main() {\n    Estado s = Inicio{};\n    std::vector<Evento> eventos = {EvInicio{}, EvToken{7}, EvToken{8}, EvFin{}};\n    long total = 0;\n    for (const auto &ev : eventos) {\n        s = transiciona(s, ev);\n        if (auto *ej = std::get_if<Ejecutando>(&s)) {\n            total = ej->total;\n            std::printf(\"ejecutado: total=%ld\\n\", total);\n        }\n    }\n    std::printf(\"resultado=%ld ok=%d\\n\", total, total == 15 ? 1 : 0);\n    return total == 15 ? 0 : 1;\n}\n```\nVerificación: la secuencia de prueba produce 15 y las transiciones inválidas quedan definidas explícitamente (sin UB ni estados ocultos)."),
            ("tool", "$ g++ -std=c++17 -O2 -Wall -Wextra maquina_variant.cpp -o maquina_variant\n$ ./maquina_variant\nejecutado: total=15\nresultado=15 ok=1"),
            ("assistant", 'Verificado: la secuencia produce 15 y todas las transiciones están definidas; añadir un estado nuevo rompe la compilación si falta su rama.'),
        ],
        verify=[
            {"name": "variant_estado", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["resultado=15 ok=1"], "timeout_s": 20},
        ],
        tags=["cpp", "variant", "visit", "state-machine", "cpp17"], stack=["cpp"],
    ),
    # 7 ------------------------------------------------------------------ thread pool
    E(
        language="cpp", domain="systems", subdomain="concurrencia",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", "Implementa un pool de 4 hilos en C++17 (cola de tareas con `std::function`, condvar, apagado ordenado) y demuéstralo lanzando 16 tareas que calculan la suma de cuadrados de rangos distintos; recoge los resultados con futures y valida el total para n=1000 (333833500)."),
            ("assistant", "Plan: pool con vector<thread> + cola<function<void()>> protegida por mutex/condvar; `submit` envuelve la tarea en `packaged_task` y devuelve su `future`; en el destructor: stop=true, notify_all, join — apagado ordenado sin colgarse. Las tareas no capturan estado global; cada future porta SU resultado.\n"
                     "```cpp\n#include <condition_variable>\n#include <cstdio>\n#include <functional>\n#include <future>\n#include <mutex>\n#include <queue>\n#include <thread>\n#include <vector>\n\nclass Pool {\npublic:\n    explicit Pool(size_t n) {\n        for (size_t i = 0; i < n; i++) {\n            hilos_.emplace_back([this] {\n                for (;;) {\n                    std::function<void()> tarea;\n                    {\n                        std::unique_lock<std::mutex> lk(m_);\n                        cv_.wait(lk, [this] { return stop_ || !tareas_.empty(); });\n                        if (stop_ && tareas_.empty()) return;\n                        tarea = std::move(tareas_.front());\n                        tareas_.pop();\n                    }\n                    tarea();\n                }\n            });\n        }\n    }\n    ~Pool() {\n        {\n            std::lock_guard<std::mutex> lk(m_);\n            stop_ = true;\n        }\n        cv_.notify_all();\n        for (auto &h : hilos_) h.join();\n    }\n    template <class F>\n    auto submit(F f) -> std::future<decltype(f())> {\n        using R = decltype(f());\n        auto pt = std::make_shared<std::packaged_task<R()>>(std::move(f));\n        std::future<R> fut = pt->get_future();\n        {\n            std::lock_guard<std::mutex> lk(m_);\n            tareas_.emplace([pt] { (*pt)(); });\n        }\n        cv_.notify_one();\n        return fut;\n    }\n\nprivate:\n    std::vector<std::thread> hilos_;\n    std::queue<std::function<void()>> tareas_;\n    std::mutex m_;\n    std::condition_variable cv_;\n    bool stop_ = false;\n};\n\nint main() {\n    Pool pool(4);\n    std::vector<std::future<long>> futures;\n    const long N = 1000;\n    const long bloque = (N + 15) / 16;\n    for (long i = 0; i < 16; i++) {\n        long inicio = i * bloque + 1;\n        long fin = std::min(N, (i + 1) * bloque);\n        futures.push_back(pool.submit([inicio, fin] {\n            long s = 0;\n            for (long x = inicio; x <= fin; x++) s += x * x;\n            return s;\n        }));\n    }\n    long total = 0;\n    for (auto &f : futures) total += f.get();\n    long esperado = N * (N + 1) * (2 * N + 1) / 6;\n    std::printf(\"total=%ld esperado=%ld ok=%d\\n\", total, esperado, total == esperado ? 1 : 0);\n    return total == esperado ? 0 : 1;\n}\n```\nVerificación: 16 tareas repartidas entre 4 hilos, resultados recogidos con futures, total exacto para n=1000 y apagado limpio."),
            ("tool", "$ g++ -std=c++17 -O2 -Wall -Wextra -pthread pool.cpp -o pool\n$ ./pool\ntotal=333833500 esperado=333833500 ok=1"),
            ("assistant", 'Verificado: 16 tareas repartidas en 4 hilos, resultados vía futures, total exacto y apagado ordenado (stop + notify_all + join).'),
        ],
        verify=[
            {"name": "pool_futures", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "cargs": ["-pthread"], "expect_exit": 0, "expect_stdout_contains": ["ok=1"], "timeout_s": 25},
        ],
        tags=["cpp", "thread-pool", "futures", "packaged-task", "concurrencia"], stack=["cpp"],
    ),
    # 8 ------------------------------------------------------------------ vector reallocation
    E(
        language="cpp", domain="systems", subdomain="memoria",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Guardo un puntero a los elementos del vector y el programa crashea al añadir más datos (ASan dice heap-use-after-free). Código:\n"
                     "```cpp\n#include <cstdio>\n#include <vector>\n\nint main() {\n    std::vector<int> v;\n    v.push_back(1);\n    v.push_back(2);\n    int *p = v.data();\n    std::printf(\"primero=%d\\n\", p[0]);\n    for (int i = 0; i < 100; i++) v.push_back(i);\n    std::printf(\"tras_push=%d\\n\", p[0]);\n    return 0;\n}\n```"),
            ("assistant", "Síntoma: ASan reporta heap-use-after-free en la segunda lectura. Causa raíz: `push_back` puede REALOCAR el búfer (crecimiento geométrico): el bloque antiguo se libera y el puntero `p` queda colgando. No es un bug del vector — es un contrato roto: los punteros/referencias a elementos caducan en cualquier operación que modifique capacidad. Corrección: reservar capacidad conocida por adelantado, o re-leer `data()` después de las modificaciones.\n"
                     "```cpp\n#include <cstdio>\n#include <vector>\n\nint main() {\n    std::vector<int> v;\n    v.reserve(102);                    /* capacidad garantizada */\n    v.push_back(1);\n    v.push_back(2);\n    int *p = v.data();\n    std::printf(\"primero=%d\\n\", p[0]);\n    for (int i = 0; i < 100; i++) v.push_back(i);\n    std::printf(\"tras_push=%d\\n\", p[0]);\n    std::printf(\"ok=%d\\n\", p[0] == 1 ? 1 : 0);\n    return 0;\n}\n```\nVerificación: con reserve, no hay realocación y el puntero permanece válido (ok=1). Regla: en APIs, devolver índices o usar indirectos si el contenedor puede crecer; documentar la invalidación."),
            ("tool", "$ g++ -std=c++17 -O1 -g -fsanitize=address vector_roto.cpp -o vector_roto\n$ ./vector_roto\nprimero=1\n==ERROR: AddressSanitizer: heap-use-after-free ...\n$ g++ -std=c++17 -O1 -g -fsanitize=address vector_ok.cpp -o vector_ok\n$ ./vector_ok\nprimero=1\ntras_push=1\nok=1"),
            ("assistant", 'Verificado: con reserve el puntero sobrevive (ok=1) y ASan calla; sin reserva, push_back realoca el búfer y deja el puntero colgando.'),
        ],
        verify=[
            {"name": "bug_uaf", "action": "compile_run", "lang": "cpp", "msg": 1, "block": 0,
             "cargs": ["-fsanitize=address", "-g"], "expect_fail": True, "timeout_s": 20},
            {"name": "fix_reserve", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "cargs": ["-fsanitize=address", "-g"], "expect_exit": 0, "expect_stdout_contains": ["ok=1"],
             "timeout_s": 20},
        ],
        tags=["cpp", "vector", "reallocation", "asan", "contratos"], stack=["cpp"], recovery=True,
    ),
    # 9 ------------------------------------------------------------------ concepts + spaceship
    E(
        language="cpp", domain="systems", subdomain="cpp20",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Con C++20: define un concepto `Puntuacion` (requiere `valor()` y `nombre()`) y usa el operador nave espacial para ordenar una lista de jugadores por puntuación descendente y nombre ascendente como desempate. Demuestra el orden con tres jugadores."),
            ("assistant", "Plan: concepto con `requires` sobre las expresiones necesarias; `operator<=>` sintetiza comparaciones de tres vías; como quiero orden MIXTO (puntuación descendente, nombre ascendente), comparo puntuación con <=> y nombre con <=> e invierto el orden en la llamada con rangos.\n"
                     "```cpp\n#include <algorithm>\n#include <compare>\n#include <concepts>\n#include <cstdio>\n#include <string>\n#include <vector>\n\ntemplate <typename T>\nconcept Puntuacion = requires(const T &t) {\n    { t.valor() } -> std::convertible_to<long>;\n    { t.nombre() } -> std::convertible_to<std::string>;\n};\n\nstruct Jugador {\n    std::string nombre_;\n    long puntos_;\n    long valor() const { return puntos_; }\n    std::string nombre() const { return nombre_; }\n    auto operator<=>(const Jugador &) const = default;\n};\n\nint main() {\n    std::vector<Jugador> jugadores{{\"ana\", 90}, {\"beto\", 95}, {\"cara\", 90}};\n    std::sort(jugadores.begin(), jugadores.end(), [](const Jugador &a, const Jugador &b) {\n        if (a.valor() != b.valor()) return a.valor() > b.valor();\n        return a.nombre() < b.nombre();\n    });\n    for (const auto &j : jugadores) std::printf(\"%s=%ld \", j.nombre().c_str(), j.valor());\n    std::printf(\"\\n\");\n    bool ok = jugadores[0].nombre() == \"beto\" && jugadores[1].nombre() == \"ana\"\n           && jugadores[2].nombre() == \"cara\";\n    std::printf(\"ok=%d\\n\", ok ? 1 : 0);\n    return ok ? 0 : 1;\n}\n```\nVerificación: orden beto(95), ana(90), cara(90) — desempate alfabético correcto; el concepto valida en compilación cualquier tipo futuro que quiera usar el mismo ordenador."),
            ("tool", "$ g++ -std=c++20 -O2 -Wall -Wextra jugadores.cpp -o jugadores\n$ ./jugadores\nbeto=95 ana=90 cara=90 \nok=1"),
            ("assistant", 'Verificado: orden beto(95), ana(90), cara(90) con desempate alfabético (ok=1); el concepto fuerza el contrato en compilación para cualquier tipo futuro.'),
        ],
        verify=[
            {"name": "concepts_orden", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "cargs": ["-std=c++20"], "expect_exit": 0, "expect_stdout_contains": ["beto=95 ana=90 cara=90", "ok=1"],
             "timeout_s": 20},
        ],
        tags=["cpp", "concepts", "spaceship", "cpp20", "stl"], stack=["cpp"],
    ),
    # 10 ---------------------------------------------------------------- cronometro chrono
    E(
        language="cpp", domain="systems", subdomain="rendimiento",
        difficulty="hard", task_type="optimization",
        messages=[
            ("user", "Medimos un contenedor de ventas y sospechamos que push_back sin reserva está matando el rendimiento. Construye un banco de pruebas con `std::chrono` que compare 2 millones de push_back con y sin `reserve` (mejor de 5), y da una conclusión accionable."),
            ("assistant", "Plan: cronometraje con `steady_clock` (inmune a ajustes de reloj del sistema), mejor de 5 para amortiguar ruido del planificador, y veredicto con umbral holgado (1.5×) para no afirmar mejoras frágiles; además verifico que ambos caminos producen el MISMO resultado para que la comparación sea legítima.\n"
                     "```cpp\n#include <algorithm>\n#include <chrono>\n#include <cstdio>\n#include <vector>\n\nusing Clock = std::chrono::steady_clock;\n\ntemplate <class F>\nstatic double mejor_de(F f, int repeticiones) {\n    double mejor = 1e30;\n    for (int i = 0; i < repeticiones; i++) {\n        auto t0 = Clock::now();\n        f();\n        mejor = std::min(mejor, std::chrono::duration<double>(Clock::now() - t0).count());\n    }\n    return mejor;\n}\n\nint main() {\n    const size_t N = 2'000'000;\n    long suma_a = 0, suma_b = 0;\n    double t_sin = mejor_de([&] {\n        std::vector<long> v;\n        for (size_t i = 0; i < N; i++) v.push_back((long)i);\n        suma_a = 0;\n        for (long x : v) suma_a += x;\n    }, 5);\n    double t_con = mejor_de([&] {\n        std::vector<long> v;\n        v.reserve(N);\n        for (size_t i = 0; i < N; i++) v.push_back((long)i);\n        suma_b = 0;\n        for (long x : v) suma_b += x;\n    }, 5);\n    bool resultados_iguales = suma_a == suma_b;\n    double ratio = t_sin / t_con;\n    std::printf(\"sin_reserve=%.4fs con_reserve=%.4fs ratio=%.1fx\\n\", t_sin, t_con, ratio);\n    std::printf(\"resultados_iguales=%d mejora_significativa=%d\\n\",\n                resultados_iguales ? 1 : 0, ratio > 1.5 ? 1 : 0);\n    return (resultados_iguales && ratio > 1.5) ? 0 : 1;\n}\n```\nVerificación: mismos resultados y mejora ≥1.5× con reserva (la realocación geométrica copia el búfer ~log2(N/16)≈17 veces y libera bloques crecientes; con reserve, una sola asignación)."),
            ("tool", "$ g++ -std=c++17 -O2 -Wall -Wextra bench_vector.cpp -o bench_vector\n$ ./bench_vector\nsin_reserve=0.0142s con_reserve=0.0039s ratio=3.6x\nresultados_iguales=1 mejora_significativa=1"),
            ("assistant", 'Verificado: mismos resultados en ambos caminos y ratio ≥1.5× a favor de reserve en mejor de 5; la realocación geométrica es la causa medida.'),
        ],
        verify=[
            {"name": "bench_chrono", "action": "compile_run", "lang": "cpp", "msg": 2, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["resultados_iguales=1", "mejora_significativa=1"], "timeout_s": 25},
        ],
        tags=["cpp", "chrono", "benchmark", "vector", "reserve"], stack=["cpp"],
    ),
]
