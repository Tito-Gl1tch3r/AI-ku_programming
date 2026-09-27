# AI-ku_programming

Dataset de programación avanzado (Stack V2) para **AI-ku V4X Thinker Max 35B**:
no enseña lenguajes aislados, enseña a **construir software** — leer un problema,
entender el entorno, inferir requisitos, planificar, programar, usar herramientas,
ejecutar, observar, depurar, adaptar y verificar.

**Un único dataset. Un único esquema. Un único Parquet.**

```text
data/AI-ku_programming.parquet   ← el producto final
```

| | |
|---|---|
| Ejemplos | 290 |
| Tokens aprox. | ~355.500 |
| Ejemplos con verificación **ejecutada** | 78,3 % (414/414 pasos superados) |
| Dificultad hard / very_hard / extreme | 95,9 % del corpus |
| Licencia | MIT |

---

## Filosofía

1. **Calidad > cantidad.** Cada ejemplo pasa un filtro previo: *¿esto realmente hace
   mejor ingeniero a AI-ku?* Si no, se descarta. No hay hello-world, ni variaciones
   mecánicas, ni ejercicios de sintaxis aislados.
2. **Ejecución + verificación > código que parece correcto.** El núcleo del dataset es
   un *harness* que compila, ejecuta y comprueba salidas reales. Lo que no pudo
   ejecutarse (PHP/Java sin toolchain, CSS sin navegador) está **marcado
   honestamente** como `executed=false` en la metadata — nunca se afirma «funciona»
   sin evidencia.
3. **Depurar con método.** Los ejemplos de debugging siguen siempre el flujo
   `síntoma → hipótesis → experimento → causa raíz → corrección → nueva ejecución →
   verificación`. Nada de «cambiar cosas hasta que funcione».
4. **Recuperación > repetición.** Los ejemplos marcados con el tag `error-recovery`
   (39,7 %) muestran una primera estrategia fallida y el cambio de hipótesis con
   información nueva.
5. **Stack V2.** La programación real rara vez ocurre en un solo lenguaje: 16,6 % de
   los ejemplos combinan ≥2 tecnologías (bash+python+sql+html, JS+WebSockets+HTML,
   SQL+bash, python+sql…).

## Lenguajes

Python · SQL · Bash · PowerShell · JavaScript · C · C++ · PHP · Java · HTML · CSS ·
SSH. JSON/YAML/TOML aparecen solo como formatos de configuración/serialización.

## Esquema

Todas las filas comparten esta estructura (detalle en [`docs/SCHEMA.md`](docs/SCHEMA.md)):

| Columna | Tipo | Contenido |
|---|---|---|
| `id` | string | `aiku-prog-NNNNN` |
| `split` | string | `train` (92 %) / `val` (5 %) / `test` (3 %) |
| `language` | string | lenguaje principal |
| `stack` | list[string] | lenguajes/entornos implicados |
| `domain` / `subdomain` | string | dominio y subdominio |
| `difficulty` | string | `medium` / `hard` / `very_hard` / `extreme` |
| `task_type` | string | implementation, debugging, optimization, code_review, architecture, testing, migration, … |
| `messages` | list[struct] | conversación `system`/`user`/`assistant`/`tool` |
| `verification` | struct | pasos de verificación ejecutados, resultado y detalle |
| `provenance` | struct | origen, método, licencia, pipeline |
| `tags` | list[string] | etiquetas temáticas (`error-recovery`, `stack-v2`, `verified-executed`…) |

## Metodología

1. **Autoría**: 21 módulos de contenido (`pipeline/modules/`), redactados como
   escenarios de ingeniería real con conversaciones multi-turno y salidas de
   herramientas (`role: tool`) realistas.
2. **Validación estática** (`validate_module.py`): vocabularios, roles, tamaño,
   marcadores de trivialidad y escaneo de secretos. Rechaza cualquier token o clave.
3. **Verificación ejecutable** (`verify.py`): cada ejemplo declara un *plan de
   verificación* que el harness ejecuta en sandboxes aislados:
   - Python (3.12, con numpy/pandas/scipy/sympy) — ejecución y tests reales;
   - C/C++ (gcc 14, `-fsanitize=address`) — compilación, ejecución, detección de UB;
   - JavaScript (node 24) — lógica pura y sintaxis;
   - Bash — `bash -n` + ejecución con fixtures;
   - SQL — SQLite en memoria (DDL, consultas, `EXPLAIN QUERY PLAN`, triggers,
     transacciones);
   - HTML — DOCTYPE + sintaxis de scripts en línea;
   - PHP/Java/PowerShell — pasos registrados como **no ejecutados** (sin toolchain).
   Un ejemplo se descarta si cualquier paso ejecutado falla. En la versión final:
   **290/290 superados**.
4. **Deduplicación**: exacta por contenido normalizado + aproximada
   (similitud ≥ 0,92 sobre el enunciado). 0 duplicados en el conjunto final.
5. **QC final** (`qc_final.py`): esquema Arrow, validación de los 290 registros,
   re-verificación sin caché de una muestra del 15 % (0 divergencias),
   distribuciones y checksum. Informe completo en [`docs/qc_report.json`](docs/qc_report.json).

## Fuentes y licencias

Todo el contenido es **original**, creado para este dataset (provenance
`origin=original`): escenarios, código, bugs sembrados y datos de prueba. No se
copia código de terceros. Licencia del dataset y del pipeline: **MIT**.

## Reproducción

```bash
cd pipeline
python3 validate_module.py modules/<módulo>.py   # validación estática
python3 verify.py <cache>.json --all             # verificación ejecutable
python3 build_parquet.py                         # Parquet + stats + checksum
python3 qc_final.py                              # QC final
```

## Limitaciones (transparencia)

- **Escala**: 290 ejemplos — una sesión de construcción única prioriza profundidad
  sobre volumen. El pipeline está diseñado para escalar añadiendo módulos; la
  barrera de calidad (verificación ejecutable) es la que limita el throughput,
  a propósito.
- **No ejecutado**: PHP, Java (solo JRE), PowerShell y CSS no tienen toolchain en el
  entorno de construcción; sus pasos quedan marcados `executed=false` (21,7 % del
  corpus) y su código no ha corrido aquí.
- **Salidas de herramientas**: los mensajes `tool` son reconstrucciones realistas de
  ejecuciones; las afirmaciones verificables del asistente están re-comprobadas por
  el harness.
- **Contaminación**: al ser contenido original no hay fugas de benchmarks conocidos,
  aunque los patrones canónicos (productor/consumidor, erase-remove…) coinciden con
  idioms públicos por naturaleza.
