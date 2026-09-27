# Esquema del dataset — AI-ku_programming

Un único Parquet (`data/AI-ku_programming.parquet`), un único esquema homogéneo
para los 290 ejemplos. Compresión zstd.

## Columnas

| Columna | Tipo Arrow | Descripción |
|---|---|---|
| `id` | string | Identificador estable `aiku-prog-NNNNN` (orden determinista por lenguaje/dominio/módulo). |
| `split` | string | `train` (92 %), `val` (5 %), `test` (3 %). Asignación determinista por hash del id. |
| `language` | string | Lenguaje principal: `python`, `sql`, `bash`, `powershell`, `javascript`, `c`, `cpp`, `php`, `java`, `html`, `css`, `ssh`. |
| `stack` | list[string] | Todos los lenguajes/entornos implicados (Stack V2). Un solo lenguaje → `[language]`. |
| `domain` | string | `web`, `systems`, `backend`, `databases`, `data`, `scripting_automation`, `security`, `tooling`, `agentic`, `scientific`, `architecture`. |
| `subdomain` | string | Subdominio en snake_case (p. ej. `concurrencia`, `window_functions`, `migracion_sin_downtime`). |
| `difficulty` | string | `medium` (4,1 %), `hard` (49,3 %), `very_hard` (35,9 %), `extreme` (10,7 %). |
| `task_type` | string | `implementation`, `debugging`, `refactoring`, `optimization`, `code_review`, `architecture`, `testing`, `migration`, `analysis`, `integration`, `scripting`, `automation`, `documentation`, `research`, `maintenance`. |
| `messages` | list[struct{role, content}] | Conversación completa. Roles: `system` (prompt de método de trabajo de AI-ku), `user` (enunciado/contexto), `assistant` (razonamiento + código + verificación), `tool` (salidas realistas de comandos/compiladores/tests). El último mensaje siempre es `assistant`. |
| `verification` | struct | Resultado del harness: `executed` (bool), `steps` (lista de {name, passed, executed, detail}), `summary`, `harness` (versión). |
| `provenance` | struct | `origin=original`, `method=authored + executed-verification harness`, `sources=[]`, `license=MIT`, `created`, `pipeline`. |
| `tags` | list[string] | Etiquetas temáticas. Convenciones: `error-recovery` (muestra estrategia fallida + adaptación), `stack-v2` (≥2 tecnologías), `verified-executed` / `verified-static`. |

## Convenciones de contenido

- Idioma: **español** en los mensajes; identificadores de código en inglés estándar.
- El sistema prompt (compartido) fija el método de trabajo de AI-ku: comprender →
  inferir requisitos → planificar → implementar → ejecutar → depurar con método →
  verificar antes de afirmar.
- Los ejemplos de debugging presentan ≥1 hipótesis fallida con experimento antes de
  la causa raíz (método, no adivinanza).
- Los mensajes `tool` son reconstrucciones realistas de ejecuciones; el harness
  re-comprueba las afirmaciones verificables.

## Verificación por lenguaje (harness)

| Lenguaje | Acciones | Resultado |
|---|---|---|
| Python | ejecución, unittest, salidas, carreras con `repeat` | ejecutado |
| C / C++ | compilación (gcc 14), ejecución, ASan, timeout como fallo | ejecutado |
| JavaScript | node: ejecución de lógica pura, `--check` | ejecutado |
| Bash | `bash -n`, ejecución con fixtures y expectativas | ejecutado |
| SQL | SQLite :memory:: DDL, consultas, EXPLAIN QUERY PLAN, triggers, transacciones | ejecutado |
| HTML | DOCTYPE + `node --check` de scripts en línea | ejecutado |
| PHP / Java / PowerShell | pasos registrados | **no ejecutado** (sin toolchain), marcado en metadata |

## Ejemplo (recortado)

```json
{
  "id": "aiku-prog-00123",
  "split": "train",
  "language": "python",
  "stack": ["python", "sql"],
  "domain": "backend",
  "subdomain": "concurrencia",
  "difficulty": "very_hard",
  "task_type": "debugging",
  "messages": [
    {"role": "system", "content": "Eres AI-ku, un ingeniero de software senior…"},
    {"role": "user", "content": "Este servicio agrega eventos con 8 hilos… ```python … ```"},
    {"role": "assistant", "content": "Síntoma: … Hipótesis: …"},
    {"role": "tool", "content": "$ python servicio.py\n52716\n…"},
    {"role": "assistant", "content": "Causa raíz: … Corrección: ```python … ```"}
  ],
  "verification": {
    "executed": true,
    "steps": [
      {"name": "bug_reproduce", "passed": true, "executed": true,
       "detail": "fallo observado como se esperaba (exit 1)"},
      {"name": "fix_correcto", "passed": true, "executed": true,
       "detail": "OK en 3 ejecución(ones)"}
    ],
    "summary": "2/2 comprobaciones superadas",
    "harness": "aiku-verify 1.0"
  },
  "provenance": {"origin": "original", "method": "authored + executed-verification harness",
                 "sources": [], "license": "MIT", "created": "2026-09-28",
                 "pipeline": "AI-ku Programming Pipeline v2.0"},
  "tags": ["threading", "race-condition", "locks", "error-recovery",
           "verified-executed", "stack-v2"]
}
```
