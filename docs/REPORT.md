# Informe final — AI-ku_programming v2.0

Fecha: 2026-09-28 · Pipeline: AI-ku Programming Pipeline v2.0 · Harness: aiku-verify 1.0

## 1. Número total de ejemplos

**290** (todos con esquema homogéneo en un único Parquet).

## 2. Número aproximado de tokens

**~355.545** (método: caracteres/4 sobre el contenido de los mensajes, incluidos system y tool).

## 3. Distribución por lenguaje

| Lenguaje | Ejemplos | % |
|---|---|---|
| python | 97 | 33.4 % |
| sql | 33 | 11.4 % |
| bash | 31 | 10.7 % |
| powershell | 22 | 7.6 % |
| javascript | 21 | 7.2 % |
| c | 20 | 6.9 % |
| php | 19 | 6.6 % |
| cpp | 15 | 5.2 % |
| java | 14 | 4.8 % |
| html | 9 | 3.1 % |
| ssh | 5 | 1.7 % |
| css | 4 | 1.4 % |

## 4. Distribución por dominio

| Dominio | Ejemplos |
|---|---|
| backend | 61 |
| systems | 46 |
| databases | 36 |
| scripting_automation | 33 |
| web | 30 |
| security | 19 |
| data | 18 |
| architecture | 16 |
| tooling | 15 |
| agentic | 8 |
| scientific | 8 |

## 5. Distribución por dificultad

| Dificultad | Ejemplos | % |
|---|---|---|
| hard | 143 | 49.3 % |
| very_hard | 104 | 35.9 % |
| extreme | 31 | 10.7 % |
| medium | 12 | 4.1 % |

**hard + very_hard + extreme = 95.9 %** del corpus, como exige el brief (difícil → muy difícil → extremo).

## 6. Porcentaje de ejemplos con ejecución

**78,28 %** verificados por ejecución real (Python, C/C++ con ASan, JavaScript/node,
Bash, SQL/SQLite, HTML). El 21,72 % restante (PHP, Java, PowerShell, CSS) no tiene
toolchain en el entorno de construcción y está marcado honestamente como
`executed=false` / tag `verified-static` — nunca se afirma que «funciona» sin haberlo
comprobado.

## 7. Porcentaje con testing

**21,0 %** (task_type=testing o verificación mediante baterías de tests /
mini-harnesses de asserts dentro del propio ejemplo).

## 8. Porcentaje con debugging

**31,7 %** (task_type=debugging o tag debugging), todos con el flujo
síntoma → hipótesis → experimento → causa raíz → corrección → verificación.

## 9. Porcentaje con tool calling

**80,3 %** de los ejemplos incluyen mensajes `role=tool` con salidas de comandos,
compiladores, tests o consultas (ingeniería con herramientas, no sólo código).

## 10. Porcentaje de tareas agénticas

**2,8 %** (domain=agentic: ciclos OBSERVE→PLAN→ACT→VERIFY→ADAPT de largo horizonte
con tool calling multi-paso). Adicionalmente, el patrón observar→verificar aparece
transversalmente en todo el corpus.

## 11. Porcentaje multidisciplinar

**16,6 %** combinan ≥2 tecnologías en su stack (p. ej. bash+python+sql+html,
javascript+html, sql+bash, python+sql). Tag `stack-v2`.

## 12. Porcentaje con recuperación tras error

**39,7 %** llevan el tag `error-recovery`: muestran explícitamente una primera
estrategia/hipótesis que falla y el cambio de estrategia con información nueva
(«un retry sin información nueva no es recovery, es repetición»).

## 13. Duplicados eliminados

**0 en el conjunto final.** Durante la construcción se eliminaron además
**35 registros** inválidos o no verificables: 6 con lógica interna rota detectada
por el harness, 9 con casos-límite mal especificados en Bash, y ajustes intermedios
de los módulos insignia. La deduplicación exacta y aproximada (similitud ≥0,92)
confirma: **0 duplicados residuales, 0 pares repetitivos**.

## 14. Principales fuentes

- **Autoría original** para este dataset (provenance `origin=original`): 21 módulos
  temáticos escritos como escenarios de ingeniería real, sin copia de código de
  terceros.
- **Ejecución real** como fuente de verdad: gcc 14 + AddressSanitizer, CPython 3.12,
  node 24, SQLite, bash 5.2 — los bugs sembrados se verifican reproducibles y las
  correcciones se verifican efectivas.
- No se usaron repositorios de terceros ni benchmarks públicos (evita contaminación
  y problemas de licencia).

## 15. Limitaciones

1. **Escala**: 290 ejemplos — profundidad verificada antes que volumen; el pipeline
   escala añadiendo módulos con la misma barrera de calidad.
2. **21,7 % no ejecutado**: PHP (sin binario), Java (solo JRE, sin javac), PowerShell
   (sin pwsh) y CSS (sin navegador) quedaron sin ejecución real.
3. **Salidas `tool`**: reconstrucciones realistas; las afirmaciones verificables
   están re-comprobadas por el harness, pero no todas las salidas son byte a byte
   de una ejecución capturada.
4. **SSH**: los ejemplos SSH no ejecutan conexiones remotas (honesto); cubren
   configuración, diagnóstico y mecanismos con partes locales verificables.
5. **Un solo idioma** de instrucciones (español): puede requerir extensión multilingüe
   según el despliegue de AI-ku.

## 16. Riesgos de contaminación

- **Bajo por diseño**: contenido original, sin benchmark público conocido copiado ni
  problemas de eval filtrados.
- Residual: los patrones canónicos (productor/consumidor, erase-remove, magic hashes,
  N+1…) coinciden con idioms públicos por naturaleza — el riesgo de memorización
  evaluativa es bajo pero no nulo.
- Los datos de prueba (logs, DDL, fixtures) son sintéticos y deterministas.

## 17. Calidad estimada del conjunto

- **Verificación**: 414/414 pasos de verificación superados; re-verificación sin
  caché del 15 % con **0 divergencias** (determinismo reproducible).
- **Dificultad**: 95,9 % hard o superior.
- **Integridad**: 0 duplicados, 0 registros inválidos, 0 secretos, 0 trivialidades
  detectadas por el QC.
- **Estimación**: conjunto **de alta calidad para especialización** (debugging con
  método, verificación ejecutable, Stack V2, agéntic), con la reserva honesta de que
  PHP/Java/PowerShell/CSS no pasaron por ejecución real en este entorno.

## Anexo: distribución por task_type y split

| task_type | Ejemplos | | split | Ejemplos |
|---|---|---|---|---|
| implementation | 102 | train | 266 |
| debugging | 92 | val | 15 |
| code_review | 22 | test | 9 |
| testing | 17 | | |
| optimization | 17 | | |
| architecture | 11 | | |
| analysis | 10 | | |
| refactoring | 8 | | |
| automation | 5 | | |
| migration | 4 | | |
| scripting | 1 | | |
| documentation | 1 | | |

## Checksum

SHA-256 de `data/AI-ku_programming.parquet`:
`294c7e58a62b351c11f85463cb586cedce1df6f529b32808d2c21c92f64d9516`
(505635 bytes, compresión zstd)
