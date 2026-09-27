"""
schema.py — Contrato único de esquema del dataset AI-ku_programming (Stack V2).

TODOS los ejemplos del dataset se construyen con la función E() de este módulo.
Un ejemplo es un diccionario con estas columnas (estructura global homogénea):

    id            -> asignado en build (aiku-prog-NNNNN)
    split         -> asignado en build (train/val/test)
    language      -> lenguaje principal (vocabulario LANGUAGES)
    stack         -> lista de lenguajes/entornos implicados (Stack V2)
    domain        -> dominio (vocabulario DOMAINS)
    subdomain     -> subdominio libre en snake_case
    difficulty    -> medium | hard | very_hard | extreme
    task_type     -> vocabulario TASK_TYPES
    messages      -> [{"role": ..., "content": ...}, ...]  (roles: system/user/assistant/tool)
    verification  -> rellenado por el harness de verificación (no por el autor)
    provenance    -> rellenado en build (no por el autor)
    tags          -> lista de strings en snake_case

USO
===

    from schema import E

    EJEMPLOS = [
        E(
            language="python",
            domain="backend",
            subdomain="concurrencia",
            difficulty="very_hard",
            task_type="debugging",
            messages=[
                ("user", "Enunciado con el código roto... ```python\\n...\\n```"),
                ("assistant", "Análisis del síntoma e hipótesis..."),
                ("tool", "$ python servicio.py\\n80037\\n"),     # salida realista de ejecución
                ("assistant", "Causa raíz y corrección...\\n```python\\n...\\n```"),
            ],
            verify=[
                {"name": "bug_reproduce", "action": "run", "lang": "python",
                 "msg": 1, "block": 0, "expect_fail": True, "repeat": 5, "timeout_s": 10},
                {"name": "fix_correcto", "action": "run", "lang": "python",
                 "msg": -1, "block": 0, "expect_exit": 0,
                 "expect_stdout_contains": ["800000"], "timeout_s": 15},
            ],
            tags=["threading", "race-condition", "locks"],
            stack=["python"],
            recovery=True,
        ),
        # ... más ejemplos
    ]

REGLAS DEL MENSAJE SYSTEM
=========================
Si el primer elemento de `messages` no es ("system", ...), se antepone
automáticamente SYSTEM_DEFAULT. Los índices de `verify` (campo `msg`) se
refieren a la lista FINAL de mensajes tras insertar el system (0 = system,
1 = primer mensaje de usuario, -1 = último mensaje).

PLAN DE VERIFICACIÓN (verify=[...])
===================================
Cada paso es un dict con claves:

    name                     (req) etiqueta corta del paso
    action                   (req) syntax | compile | run | compile_run | sql | html_check
    lang                     (req) python | c | cpp | bash | js | sql | php | java | html
    msg                      índice del mensaje (default -1)
    block                    índice del bloque cercado ``` dentro del mensaje (default 0)
    filename                 nombre de fichero para el bloque (java: debe coincidir con la clase)
    args                     argumentos del PROGRAMA (tras compilar, si aplica)
    cargs                    flags del COMPILADOR (solo c/cpp/java: -pthread, -fsanitize=address, -std=...)
    stdin                    stdin para la ejecución
    fixtures                 [{"name": "...", "content": "..."}] ficheros creados en el sandbox
    setup                    solo sql: pares [msg, block] con DDL a ejecutar antes
    expect_exit              código de salida esperado (default 0)
    expect_fail              True => se espera fallo (exit != 0, timeout o no compila)
    expect_compile_fail      True => se espera error de compilación (solo compile/compile_run)
    expect_stdout_contains   subcadenas que deben aparecer en stdout+stderr
    expect_stdout_not_contains  subcadenas que NO deben aparecer
    repeat                   ejecutar N veces (para carreras: expect_fail basta 1 fallo)
    timeout_s                por ejecución, max 30 (default 10)

ACCIONES
========
    syntax       comprobación de sintaxis (py_compile / bash -n / node --check / php -l)
    compile      solo compilar (c/cpp -> gcc/g++; java -> javac)
    run          ejecutar (python/bash/js/php). Para c/cpp/java usa compile_run
    compile_run  compilar + ejecutar (c/cpp/java)
    sql          ejecutar SQL en SQLite :memory: (setup DDL opcional); captura filas y planes
    html_check   DOCTYPE presente + sintaxis de <script> en línea con node --check

REGLAS DE AUTORÍA (OBLIGATORIAS)
================================
1. Contenido en ESPAÑOL (código y identificadores en inglés estándar).
2. Nada de ejercicios triviales, hello-world ni relleno. Si no hace mejor ingeniero, no lo incluyas.
3. Dificultad dominada por hard / very_hard / extreme.
4. Determinismo: si usas aleatoriedad, fija semillas; nada de hora del sistema, red externa ni hostname.
5. Los programas ejecutables deben ser AUTOCONTENIDOS en UN bloque (servidor+cliente => hilos/fork en el mismo programa; los servidores deben terminar solos).
6. Prohibido input() interactivo, APIs de pago, descargas, y secretos reales.
7. En debugging: verifica que el bug se reproduce (expect_fail / expect_compile_fail) Y que el fix pasa.
8. Marca recovery=True cuando el ejemplo demuestre explícitamente recuperación tras una hipótesis/estrategia fallida.
9. Los tool outputs que escribas deben ser realistas; el harness re-verifica las afirmaciones por su cuenta.
10. Nunca incluyas tokens, claves privadas ni credenciales (el validador lo rechaza).
"""

import re

# ---------------------------------------------------------------- vocabularios

LANGUAGES = {
    "python", "c", "cpp", "bash", "ssh", "html", "css",
    "javascript", "php", "java", "sql", "powershell",
}

DOMAINS = {
    "web", "systems", "backend", "databases", "data",
    "scripting_automation", "security", "tooling", "agentic",
    "scientific", "architecture",
}

TASK_TYPES = {
    "implementation", "debugging", "refactoring", "optimization",
    "code_review", "architecture", "testing", "migration",
    "analysis", "integration", "scripting", "automation",
    "documentation", "research", "maintenance",
}

DIFFICULTIES = {"medium", "hard", "very_hard", "extreme"}

ROLES = {"system", "user", "assistant", "tool"}

VERIFY_ACTIONS = {"syntax", "compile", "run", "compile_run", "sql", "html_check"}
VERIFY_LANGS = {"python", "c", "cpp", "bash", "js", "sql", "php", "java", "html"}

# ------------------------------------------------------------- system por defecto

SYSTEM_DEFAULT = (
    "Eres AI-ku, un ingeniero de software senior. Método de trabajo: "
    "(1) Comprende el problema y el entorno antes de escribir código; "
    "(2) haz explícitos los requisitos que infieras del objetivo; "
    "(3) planifica brevemente antes de actuar; "
    "(4) escribe código correcto, legible, seguro y mantenible; "
    "(5) ejecuta y observa la salida real; "
    "(6) si algo falla, aplica método: síntoma → hipótesis → experimento → causa raíz → corrección → nueva ejecución; "
    "(7) verifica con pruebas antes de afirmar que algo funciona; "
    "(8) nunca digas «funciona» sin evidencia. "
    "Distingue siempre hechos verificados de suposiciones."
)

# ------------------------------------------------------------------ utilidades

FENCE_RE = re.compile(r"```([A-Za-z0-9_+\-]*)[ \t]*\r?\n(.*?)```", re.S)

SECRET_PATTERNS = [
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

TRIVIAL_MARKERS = ["TODO:", "FIXME:", "LOREM", "PLACEHOLDER", "<tu código aquí>", "AQUÍ VA EL CÓDIGO"]


def blocks_of(content: str):
    """Extrae los bloques cercados ``` de un texto como lista (lenguaje, código)."""
    out = []
    for m in FENCE_RE.finditer(content or ""):
        out.append((m.group(1).lower(), m.group(2)))
    return out


# --------------------------------------------------------------------- E()

def E(*, language, domain, subdomain, difficulty, task_type, messages,
      tags=None, stack=None, verify=None, recovery=False, system=None):
    """Construye un registro de ejemplo con el esquema global homogéneo."""
    msgs = []
    for item in messages:
        role, content = item
        if role not in ROLES:
            raise ValueError(f"rol inválido: {role!r} (permitidos: {sorted(ROLES)})")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("contenido de mensaje vacío o no textual")
        msgs.append({"role": role, "content": content})
    if msgs[0]["role"] != "system":
        msgs.insert(0, {"role": "system", "content": system or SYSTEM_DEFAULT})

    return {
        "id": None,
        "split": None,
        "language": language,
        "stack": list(stack) if stack else [language],
        "domain": domain,
        "subdomain": subdomain,
        "difficulty": difficulty,
        "task_type": task_type,
        "messages": msgs,
        "verification": None,
        "provenance": None,
        "tags": list(tags) if tags else [],
        "_recovery": bool(recovery),
        "_verify_plan": list(verify) if verify else [],
        "_module": None,
        "_index": None,
    }


# ----------------------------------------------------------------- validación

def validate_record(rec):
    """Valida un registro. Devuelve (errores, avisos): listas de strings."""
    errors, warnings = [], []

    if rec.get("language") not in LANGUAGES:
        errors.append(f"language fuera de vocabulario: {rec.get('language')!r}")
    if rec.get("domain") not in DOMAINS:
        errors.append(f"domain fuera de vocabulario: {rec.get('domain')!r}")
    if rec.get("task_type") not in TASK_TYPES:
        errors.append(f"task_type fuera de vocabulario: {rec.get('task_type')!r}")
    if rec.get("difficulty") not in DIFFICULTIES:
        errors.append(f"difficulty fuera de vocabulario: {rec.get('difficulty')!r}")

    if not rec.get("subdomain") or not re.fullmatch(r"[a-z0-9_]+", rec["subdomain"]):
        errors.append(f"subdomain debe ser snake_case: {rec.get('subdomain')!r}")

    stack = rec.get("stack") or []
    if not stack or not all(isinstance(s, str) and s for s in stack):
        errors.append("stack debe ser lista de strings no vacía")

    tags = rec.get("tags") or []
    if not all(isinstance(t, str) and re.fullmatch(r"[a-z0-9_\-]+", t) for t in tags):
        errors.append("tags deben ser strings snake_case/kebab")

    msgs = rec.get("messages") or []
    if len(msgs) < 3:
        errors.append("mínimo 3 mensajes (system + user + assistant)")
    if msgs[0]["role"] != "system":
        errors.append("el primer mensaje debe ser system")
    roles = [m["role"] for m in msgs]
    if "user" not in roles:
        errors.append("falta mensaje user")
    if "assistant" not in roles:
        errors.append("falta mensaje assistant")
    if roles[-1] != "assistant":
        errors.append("el último mensaje debe ser assistant")
    for i, m in enumerate(msgs):
        if m["role"] not in ROLES:
            errors.append(f"mensaje {i}: rol inválido {m['role']!r}")

    total_chars = sum(len(m["content"]) for m in msgs)
    if total_chars < 500:
        warnings.append(f"contenido posiblemente superficial ({total_chars} chars)")
    if total_chars > 40000:
        warnings.append(f"contenido muy largo ({total_chars} chars)")

    joined = "\n".join(m["content"] for m in msgs)
    for label, pat in SECRET_PATTERNS:
        if pat.search(joined):
            errors.append(f"POSIBLE SECRETO detectado ({label}) — ejemplo rechazado")
    for marker in TRIVIAL_MARKERS:
        if marker in joined:
            errors.append(f"marcador de trivialidad presente: {marker!r}")

    # plan de verificación: comprobación estructural en seco
    for k, step in enumerate(rec.get("_verify_plan") or []):
        pfx = f"verify[{k}]"
        if not isinstance(step, dict):
            errors.append(f"{pfx}: debe ser dict")
            continue
        if not step.get("name"):
            errors.append(f"{pfx}: falta 'name'")
        action = step.get("action")
        lang = step.get("lang")
        if action not in VERIFY_ACTIONS:
            errors.append(f"{pfx}: action inválida {action!r}")
            continue
        if lang not in VERIFY_LANGS:
            errors.append(f"{pfx}: lang inválido {lang!r}")
            continue
        msg_idx = step.get("msg", -1)
        try:
            m = msgs[msg_idx]
        except (IndexError, TypeError):
            errors.append(f"{pfx}: msg {msg_idx} fuera de rango ({len(msgs)} mensajes)")
            continue
        blks = blocks_of(m["content"])
        blk_idx = step.get("block", 0)
        if blk_idx >= len(blks):
            errors.append(f"{pfx}: block {blk_idx} fuera de rango (msg {msg_idx} tiene {len(blks)} bloques)")
            continue
        blang, _ = blks[blk_idx]
        expected_labels = {"python": {"python", "py"}, "c": {"c"}, "cpp": {"cpp", "c++"},
                           "bash": {"bash", "sh", "shell"}, "js": {"js", "javascript"},
                           "sql": {"sql"}, "php": {"php"}, "java": {"java"},
                           "html": {"html"}}
        if blang and blang not in expected_labels.get(lang, set()):
            warnings.append(f"{pfx}: bloque etiquetado '{blang}' pero step lang='{lang}'")
        if lang == "java" and step.get("filename") is None:
            warnings.append(f"{pfx}: java sin 'filename' (se usará Main.java)")
        if action == "sql":
            for s in step.get("setup") or []:
                if not (isinstance(s, (list, tuple)) and len(s) == 2):
                    errors.append(f"{pfx}: setup debe ser pares [msg, block]")
                    break
        if step.get("timeout_s", 10) > 30:
            errors.append(f"{pfx}: timeout_s > 30 no permitido")

    return errors, warnings
