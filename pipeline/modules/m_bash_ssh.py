"""m_bash_ssh.py — Stack V2: Bash de producción y administración SSH (45 ejemplos).

36 ejemplos de bash robusto (traps, pipefail, find/xargs, awk/sed/grep,
monitorización, reintentos, locks, checkpoints, getopts, arrays asociativos,
señales, CSV, backups deterministas) + 9 de SSH legítimo (ssh_config,
ProxyJump, permisos, authorized_keys, host keys, túneles, rsync, sshd).
"""

from schema import E

EXAMPLES = [
    # ------------------------------------------------------------------ B01
    E(
        language="bash", domain="scripting_automation", subdomain="trap_hijos",
        difficulty="hard", task_type="automation",
        messages=[
            ("user", r"""Tenemos un orquestador nocturno que lanza 3 workers en segundo plano y termina sin esperarlos. En producción hemos visto procesos `sleep` huérfanos colgados horas después de que el orquestador muriera. Este es el script actual:
```bash
#!/usr/bin/env bash
set -euo pipefail
pids=()
for i in 1 2 3; do
  ( sleep 2; echo "worker $i terminado" >> estados.txt ) &
  pids+=("$!")
done
echo "orquestador: ${#pids[@]} workers lanzados"
echo "orquestador: finaliza"
```
Quiero que si el script termina (bien o mal, incluso por SIGINT), ningún worker quede vivo salvo que yo pida explícitamente esperarlos con el argumento `esperar`."""),
            ("assistant", r"""Requisitos que infiero: (1) limpieza garantizada en TODAS las salidas → `trap ... EXIT`; (2) el trap debe recorrer los PIDs y matar solo a los que sigan vivos; (3) el modo `esperar` debe desactivar la matanza y sincronizar con `wait`. Plan: registrar los pids en un array, trap EXIT que itere con `kill` + `wait`, y una rama condicional para el modo esperar. Un detalle importante: `wait` sobre un pid ya reaped devuelve error, por eso el trap debe tolerar fallos (`|| true`) para no romper con `set -e` dentro del propio trap."""),
            ("tool", r"""$ bash orquestador.sh
orquestador: 3 workers lanzados
orquestador: finaliza
$ pgrep -f 'sleep 2'
4123
4124
4125
$ bash orquestador.sh esperar
orquestador: 3 workers lanzados
worker 1 terminado
worker 2 terminado
worker 3 terminado
orquestador: finaliza
$ pgrep -f 'sleep 2'; echo "rc=$?"
rc=1"""),
            ("assistant", r"""Diagnóstico confirmado: sin trap, `pgrep` muestra 3 huérfanos; con `esperar`, cero. El trap EXIT se ejecuta también si `set -e` aborta o llega un SIGINT, así que cubre todas las salidas. Versión final:
```bash
#!/usr/bin/env bash
set -euo pipefail
pids=()
cleanup() {
  local p algo=0
  for p in "${pids[@]}"; do
    if kill "$p" 2>/dev/null; then
      wait "$p" 2>/dev/null || true
      echo "cleanup: worker $p detenido (señal)" >&2
      algo=1
    fi
  done
  if (( ! algo )); then
    echo "cleanup: nada pendiente" >&2
  fi
}
trap cleanup EXIT
for i in 1 2 3; do
  ( sleep 2; echo "worker $i terminado" >> estados.txt ) &
  pids+=("$!")
done
echo "orquestador: ${#pids[@]} workers lanzados"
if [[ ${1:-} == esperar ]]; then
  wait
  cat estados.txt
fi
echo "orquestador: finaliza"
```
Decisiones: `kill` solo si el pid responde (`if kill ... 2>/dev/null`) evita falsos errores con pids ya terminados; `wait` en el trap reaps y limpia la entrada de la tabla de procesos; el mensaje de cleanup va a stderr porque es diagnóstico, no resultado. Verificado: modo normal deja 0 workers; modo `esperar` imprime los 3 resultados y el trap reporta «nada pendiente»."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "modo_normal_mata_workers", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["orquestador: 3 workers lanzados", "cleanup: worker", "detenido (señal)"]},
            {"name": "modo_esperar_sincroniza", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["esperar"], "expect_exit": 0,
             "expect_stdout_contains": ["worker 2 terminado", "cleanup: nada pendiente"]},
        ],
        tags=["trap", "exit", "procesos_hijo", "orquestacion"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B02
    E(
        language="bash", domain="scripting_automation", subdomain="trap_limpieza",
        difficulty="hard", task_type="debugging",
        messages=[
            ("user", r"""Este script empaqueta un manifiesto para el pipeline de datos. En CI funciona, pero el disco de los runners se llena: encontramos directorios `build.*` abandonados de ejecuciones fallidas.
```bash
#!/usr/bin/env bash
set -euo pipefail
in=${1:?uso: empaquetar.sh MANIFIESTO}
tmp="build.$$"
mkdir "$tmp"
cp "$in" "$tmp/lista.txt"
grep -v '^#' "$tmp/lista.txt" > "$tmp/validas.txt"
tar czf paquete.tar.gz -C "$tmp" validas.txt
echo "empaquetado ok"
```
¿Por qué quedan residuos y cómo lo dejamos a prueba de cualquier fallo?"""),
            ("assistant", r"""Síntoma: directorios `build.<pid>` huérfanos solo tras ejecuciones fallidas. Hipótesis inicial: el bug es del `cp` cuando falta el manifiesto — pero eso explicaría el fallo, no el residuo. El residuo aparece porque el directorio temporal se crea ANTES del trabajo y NADA lo elimina si `set -e` aborta a mitad (cp, grep o tar fallan → exit inmediato). Experimento: reproducir un fallo y comprobar si queda basura, y contrastar con la práctica correcta: `mktemp -d` + `trap ... EXIT`."""),
            ("tool", r"""$ bash empaquetar.sh faltante.txt; echo "rc=$?"
cp: cannot stat 'faltante.txt': No such file or directory
rc=1
$ ls -d build.*
build.4242
$ # tras varias ejecuciones fallidas del día en CI:
$ ls -d build.* | wc -l
37
$ grep -n 'trap' empaquetar.sh; echo "rc=$?"
rc=1"""),
            ("assistant", r"""Confirmado: 37 residuos y ni un solo `trap` en el script. Causa raíz: falta un gestor de limpieza ligado a la terminación; la creación manual con `$$` además tiene carrera (dos ejecuciones simultáneas podrían colisionar si reutilizan pid) — `mktemp -d` es atómico y único. Corrección:
```bash
#!/usr/bin/env bash
set -euo pipefail
tmp=$(mktemp -d build.XXXXXX)
trap 'echo "cleanup: eliminando $tmp" >&2; rm -rf "$tmp"' EXIT
in=${1:?uso: empaquetar.sh MANIFIESTO}
[[ -r $in ]] || { echo "error: no legible: $in" >&2; exit 2; }
cp "$in" "$tmp/lista.txt"
grep -v '^#' "$tmp/lista.txt" > "$tmp/validas.txt"
if [[ ! -s $tmp/validas.txt ]]; then
  echo "error: manifiesto sin líneas válidas" >&2
  exit 3
fi
tar czf paquete.tar.gz -C "$tmp" validas.txt
echo "empaquetado ok: $(tar tzf paquete.tar.gz | wc -l) fichero(s)"
```
Por qué así: el trap EXIT se dispara en salida normal, por `set -e`, por señal y por `exit` explícito, así que el temporal se elimina SIEMPRE; el `rm -rf` usa la variable entre comillas y solo apunta al directorio creado por `mktemp` (ruta relativa del sandbox). Ahora cualquier fallo informa a stderr («cleanup: eliminando ...») y no deja rastro. Verificado con manifiesto válido, ilegible y vacío."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "original_deja_basura_al_fallar", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "args": ["faltante.txt"], "expect_fail": True},
            {"name": "fallo_con_trap_limpia", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["faltante.txt"], "expect_fail": True,
             "expect_stdout_contains": ["cleanup: eliminando"]},
            {"name": "ok_con_trap", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["manifiesto.txt"], "expect_exit": 0,
             "fixtures": [{"name": "manifiesto.txt", "content": r"""# paquete semanal
fuente_a.csv
fuente_b.csv
"""}, {"name": "faltante.txt", "content": "x\n"}],
             "expect_stdout_contains": ["empaquetado ok: 1 fichero(s)", "cleanup: eliminando"]},
        ],
        tags=["trap", "mktemp", "limpieza", "ci"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B03
    E(
        language="bash", domain="systems", subdomain="trap_err",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", r"""Definimos un `trap ... ERR` para que el despliegue reporte fichero:línea:función de cualquier error, pero el diagnóstico NUNCA aparece cuando el fallo ocurre dentro de una función. El script:
```bash
#!/usr/bin/env bash
set -euo pipefail
trap 'echo "FALLO: exit $? en línea $LINENO" >&2' ERR
validar() {
  [[ -f $1 ]] || { echo "falta fichero: $1" >&2; return 3; }
}
main() {
  validar "$1"
  echo "ok: $1"
}
main "$1"
```
Con un fichero inexistente sale 3 y el único mensaje es «falta fichero». ¿Dónde está el trap?"""),
            ("assistant", r"""Síntoma: trap definido pero silencioso dentro de funciones. Hipótesis 1 (fallida): el trap se pierde al entrar en funciones. Hipótesis 2: el trap sí existe pero bash NO lo hereda dentro de cuerpos de función a menos que se active `set -E` (errtrace). Experimento decisivo: comparar el mismo fallo con y sin `-E`, y observar `$?`, la herencia y el rastreo de función con BASH_SOURCE/BASH_LINENO/FUNCNAME."""),
            ("tool", r"""$ bash deploy.sh inexistente; echo "rc=$?"
falta fichero: inexistente
rc=3
$ # añadimos solo set -E:
$ sed 's/set -euo/set -Eeuo/' deploy.sh > deploy2.sh
$ bash deploy2.sh inexistente; echo "rc=$?"
falta fichero: inexistente
FALLO: exit 3 en línea 4 (función main)
rc=3
$ # y el trap NO aborta por sí solo sin errexit:
$ bash -c 'trap "echo atrapado" ERR; false; echo sigo'; echo "rc=$?"
atrapado
sigo
rc=0"""),
            ("assistant", r"""Confirmado: sin `set -E`, el trap ERR no se hereda dentro de funciones (bash lo ejecuta solo en el contexto del shell principal); con `-E` aparece. Segundo aprendizaje del experimento: el trap ERR no sustituye a `set -e` — sin errexit, tras el trap se CONTINÚA («sigo», rc=0). Causa raíz: faltaba `set -E` (errtrace). Corrección con manejador con contexto completo:
```bash
#!/usr/bin/env bash
set -Eeuo pipefail
on_err() {
  local ec=$?
  echo "FALLO: exit $ec en ${BASH_SOURCE[1]}:${BASH_LINENO[0]} (función ${FUNCNAME[1]:-main})" >&2
  exit "$ec"
}
trap on_err ERR
validar() {
  [[ -f $1 ]] || { echo "falta fichero: $1" >&2; return 3; }
}
main() {
  validar "$1"
  echo "ok: $1 válido"
}
main "${1:-}"
```
Decisiones: `set -Eeuo pipefail` en una sola línea (E habilita errtrace); el manejador recupera `$?` ANTES de cualquier otra orden y termina con `exit "$ec"` para conservar el código de salida semántico; `BASH_SOURCE[1]`/`BASH_LINENO[0]`/`FUNCNAME[1]` apuntan al marco del llamador, no del manejador. Verificado: fichero inexistente → «falta fichero» + «FALLO: exit 3 ... (función main)» y rc=3; fichero válido → rc=0."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "original_sin_diagnostico", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "args": ["inexistente"], "expect_fail": True,
             "expect_stdout_not_contains": ["FALLO: exit"]},
            {"name": "fallo_con_contexto", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["inexistente"], "expect_exit": 3,
             "expect_stdout_contains": ["falta fichero: inexistente", "FALLO: exit 3", "(función main)"]},
            {"name": "ok_no_dispara_trap", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "ok.txt", "content": "contenido\n"}],
             "args": ["ok.txt"], "expect_exit": 0,
             "expect_stdout_contains": ["ok: ok.txt válido"],
             "expect_stdout_not_contains": ["FALLO"]},
        ],
        tags=["trap", "err", "errtrace", "diagnostico"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B04
    E(
        language="bash", domain="scripting_automation", subdomain="errexit",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", r"""Este contador de líneas del lote nocturno muere SILENCIOSAMENTE con código 1 cuando procesa ficheros, y no imprimimos ni el mensaje de contador. Con lote vacío sí funciona.
```bash
#!/usr/bin/env bash
set -e
count=0
for f in $(cat lista.txt); do
  ((count++))
done
echo "contador: $count"
```
¿Qué está pasando? He revisado que lista.txt existe y tiene 2 rutas."""),
            ("assistant", r"""Síntoma: aborta sin mensaje con lista NO vacía; con lote vacío el bucle ni itera y sale bien. Hipótesis inicial (fallida): «set -e falla solo en comandos externos». Pista fuerte: la única orden que se ejecuta solo cuando HAY elementos es `((count++))`. En bash, `(( ... ))` devuelve estado de salida 1 cuando la expresión evalúa a 0 — y `count++` es post-incremento: devuelve el valor ANTES de incrementar. Primera iteración: `((0++))` → valor 0 → estado 1 → `set -e` aborta. Experimento para confirmarlo."""),
            ("tool", r"""$ bash -c 'set -e; c=0; ((c++)); echo "nunca llego: $c"'; echo "rc=$?"
rc=1
$ bash -c 'set -e; c=0; ((++c)); echo "llego: $c"'; echo "rc=$?"
llego: 1
rc=0
$ bash -c 'set -e; c=5; ((c++)); echo "llego: $c"'; echo "rc=$?"
llego: 5
rc=0
$ # y dentro de if/while las condiciones están exentas de -e:
$ bash -c 'set -e; if ((0)); then echo rama; fi; echo condicion_segura'; echo "rc=$?"
condicion_segura
rc=0"""),
            ("assistant", r"""Confirmado: es la interacción `set -e` + aritmética de post-incremento con valor 0. `((c++))` con c=0 evalúa a 0 → estado 1 → abort. Con c=5 funciona por accidente, lo que explica que «a veces pase y a veces no» en producción. Causa raíz: uso de `((expr))` como sentencia cuyo resultado puede ser 0. Corrección: incrementos en forma de asignación (estado siempre 0) o pre-incremento consciente:
```bash
#!/usr/bin/env bash
set -euo pipefail
count=0
for f in $(cat lista.txt); do
  count=$((count + 1))
done
echo "contador: $count"
```
Por qué así: `count=$((count + 1))` es una asignación (estado 0 siempre) y el código de salida del script refleja solo fallos reales. Reglas que extraemos: (1) nunca uses `((expr))` como sentencia si puede evaluar 0; (2) las condiciones de `if`/`while`/`||`/`&&` están exentas de errexit — ahí `(( ))` es seguro; (3) `set -e` tiene más excepciones (comandos en `if`, partes de `&&`/`||`, negaciones `!`), por eso los scripts críticos VALIDAN y REPORTAN errores explícitamente en vez de fiarse solo del errexit. Verificado: lista con 2 elementos → «contador: 2»; lista vacía → «contador: 0»; ambos rc=0."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "original_aborta_silencioso", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [{"name": "lista.txt", "content": "a\nb\n"}],
             "expect_fail": True,
             "expect_stdout_not_contains": ["contador"]},
            {"name": "contador_con_elementos", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "lista.txt", "content": "a\nb\n"}],
             "expect_exit": 0, "expect_stdout_contains": ["contador: 2"]},
            {"name": "contador_vacio", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "lista.txt", "content": ""}],
             "expect_exit": 0, "expect_stdout_contains": ["contador: 0"]},
        ],
        tags=["set-e", "aritmetica", "post_incremento", "debugging"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B05
    E(
        language="bash", domain="scripting_automation", subdomain="pipefail",
        difficulty="hard", task_type="debugging",
        messages=[
            ("user", r"""Nuestro resumen nocturno de lotes reporta «registros: 0 suma: 0.00» con éxito (exit 0) cuando el fichero de entrada viene lleno de comentarios, y el proceso aguas abajo arranca con esa suma vacía y corrompe la tabla de destino. El script:
```bash
#!/usr/bin/env bash
set -e
in=${1:?uso: resumen.sh ENTRADA}
total=$(grep -v '^#' "$in" | awk '{s+=$1} END{printf "%.2f\n", s}')
echo "registros: $(grep -vc '^#' "$in") suma: $total"
```
El grep no debería fallar... ¿o sí?"""),
            ("assistant", r"""Síntoma: éxito (0) con cero datos válidos. Hipótesis: el código de salida de `grep` se pierde en el pipeline. Hecho clave: `grep` devuelve 1 cuando NO hay líneas que pasan el filtro — un fallo «esperable», no un error del sistema. En `set -e` puro, el estado del pipeline es el del ÚLTIMO comando (awk), que es 0; el 1 de grep desaparece. Experimento: medir `${PIPESTATUS[@]}` y contrastar con `set -o pipefail`."""),
            ("tool", r"""$ printf '# a\n# b\n# c\n' > solo_comentarios.txt
$ grep -v '^#' solo_comentarios.txt | awk '{s+=$1} END{printf "%.2f\n", s}'; echo "pipeline=$?"
0.00
pipeline=0
$ echo "${PIPESTATUS[@]}"
1 0
$ set -o pipefail; grep -v '^#' solo_comentarios.txt | awk '{s+=$1} END{printf "%.2f\n", s}'; echo "con_pipefail=$?"
0.00
con_pipefail=1"""),
            ("assistant", r"""Confirmado: `${PIPESTATUS[@]}` era `1 0` y el pipeline reportaba 0; con pipefail pasa a ser 1. Hipótesis descartada del enunciado: «el grep no falla» — falla (exit 1) justo cuando no quedan registros, el caso que nos interesa. Causa raíz: pipeline sin `pipefail` + ausencia de gestión explícita del caso «sin datos». Corrección: pipefail global y política explícita para el lote vacío (error controlado, no éxito engañoso):
```bash
#!/usr/bin/env bash
set -euo pipefail
in=${1:?uso: resumen.sh ENTRADA}
[[ -r $in ]] || { echo "error: no legible: $in" >&2; exit 2; }
validas=$(grep -vc '^#' "$in" || true)
if (( validas == 0 )); then
  echo "error: $in no contiene registros válidos" >&2
  exit 3
fi
total=$(grep -v '^#' "$in" | awk '{s+=$1} END{printf "%.2f\n", s}')
echo "registros: $validas suma: $total"
```
Decisiones: `|| true` SOLO en la captura del conteo porque el exit 1 de grep aquí es información («0 válidas»), no un fallo del sistema; después decidimos con `if`: lote vacío → exit 3 (código semántico distinto de los genéricos). Nota fina: `-vc` cuenta las líneas que NO casan; un fichero sin saltos final también cuenta. Verificado: lote normal → «registros: 3 suma: 25.50»; solo comentarios → exit 3; fichero ilegible → exit 2."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "original_falsa_victoria", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [{"name": "solo.txt", "content": "# a\n# b\n# c\n"}],
             "args": ["solo.txt"], "expect_exit": 0,
             "expect_stdout_contains": ["registros: 0 suma: 0.00"]},
            {"name": "fijo_lote_vacio_falla", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "solo.txt", "content": "# a\n# b\n# c\n"}],
             "args": ["solo.txt"], "expect_exit": 3,
             "expect_stdout_contains": ["no contiene registros válidos"]},
            {"name": "fijo_lote_normal", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "datos.txt", "content": "# notas\n12.5\n9.75\n#corte\n3.25\n"}],
             "args": ["datos.txt"], "expect_exit": 0,
             "expect_stdout_contains": ["registros: 3 suma: 25.50"]},
        ],
        tags=["pipefail", "pipestatus", "grep", "contrato_de_datos"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B06
    E(
        language="bash", domain="systems", subdomain="delimitadores",
        difficulty="hard", task_type="debugging",
        messages=[
            ("user", r"""El mainframe nos deja un export con campos separados por `|` y RELLENO de espacios de ancho fijo, y la primera columna (usuario) puede venir VACÍA. Nuestro normalizador produce basura:
```bash
#!/usr/bin/env bash
# normalizar_export.sh ENTRADA — esperamos usuario|fecha|minutos
tr -d ' ' < "$1" | cut -d'|' -f1-3
```
Ejemplo de entrada:
```
  ana       |2024-03-14| 42|nota cualquiera
            |2024-03-14|  7
ANA LOPEZ  |2024-03-15|120
```
Con ANA LOPEZ el resultado es «ANALOPEZ|...» y los registros anónimos pierden el campo."""),
            ("assistant", r"""Síntoma: `tr -d ' '` destruye datos (espacios internos de ANA LOPEZ) y no distingue relleno de contenido. Hipótesis primera (fallida): «con `cut -d'|'` y sin tr ya vale» — pero entonces el relleno viaja en los valores y las comparaciones por clave fallan aguas abajo. Experimento: ver qué deja cada aproximación."""),
            ("tool", r"""$ cut -d'|' -f1-3 export.txt | head -3
  ana       |2024-03-14| 42
            |2024-03-14|  7
ANA LOPEZ  |2024-03-15|120
$ tr -d ' ' < export.txt | cut -d'|' -f1-3 | head -3
ana|2024-03-14|42
|2024-03-14|7
ANALOPEZ|2024-03-15|120
$ awk -F'|' '{print NF}' export.txt | uniq -c
      4"""),
            ("assistant", r"""Confirmado: `cut` preserva el relleno y `tr` lo borra TODO. La herramienta correcta es `awk -F'|'` con una función de recorte SOLO de espacios de los extremos, que además normaliza el usuario vacío a un marcador explícito para que las claves del join no sean cadenas vacías:
```bash
#!/usr/bin/env bash
set -euo pipefail
in=${1:?uso: normalizar_export.sh ENTRADA}
LC_ALL=C awk -F'|' '
  function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
  NF >= 3 {
    u=trim($1); f=trim($2); m=trim($3)
    if (u == "") u="(anon)"
    printf "%s|%s|%s\n", u, f, m
  }' "$in"
```
Decisiones: `gsub(/^[ \t]+|[ \t]+$/)` recorta extremos sin tocar espacios internos («ANA LOPEZ» sobrevive); `NF >= 3` descarta líneas corruptas en silencio controlado (el export garantiza 4 campos: el 4º es una nota que ignoramos); el marcador `(anon)` mantiene la cardinalidad de claves. Por qué no `awk -F'| *|'` : un separador de expresión regular con espacios colapsados rompe si el relleno varía entre líneas; el recorte por campo es robusto. Verificado: los 3 casos del ejemplo salen normalizados y el anónimo aparece como `(anon)|2024-03-14|7`."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "original_destruye_datos", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [{"name": "export.txt", "content": r"""  ana       |2024-03-14| 42|nota
            |2024-03-14|  7|
ANA LOPEZ  |2024-03-15|120|nota2
"""}],
             "args": ["export.txt"], "expect_exit": 0,
             "expect_stdout_contains": ["ANALOPEZ|2024-03-15|120"]},
            {"name": "fijo_preserva_y_normaliza", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "export.txt", "content": r"""  ana       |2024-03-14| 42|nota
            |2024-03-14|  7|
ANA LOPEZ  |2024-03-15|120|nota2
"""}],
             "args": ["export.txt"], "expect_exit": 0,
             "expect_stdout_contains": ["ana|2024-03-14|42",
                                        "(anon)|2024-03-14|7",
                                        "ANA LOPEZ|2024-03-15|120"]},
        ],
        tags=["awk", "cut", "delimitadores", "normalizacion"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B10
    E(
        language="bash", domain="systems", subdomain="monitorizacion",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", r"""Para la guardia quiero un verificador de CPU por proceso que sea EJECUTABLE EN CI (determinista) y en producción. En lugar de correr `ps` dentro del script (la salida varía entre máquinas y momentos), el script recibirá UNA CAPTURA de `ps -eo pid,comm,pcpu --no-headers` y un umbral; debe listar los procesos que superen el umbral y salir 1 si hay al menos uno (para engancharlo a alertas)."""),
            ("assistant", r"""Separar CAPTURA (producción, variable) de EVALUACIÓN (determinista, testeable) es la decisión clave: el script nunca miente en CI porque su entrada es un snapshot fijo. Para el parseo: awk con `-v umbral=` (sin interpolar la variable en el programa awk, que sería un problema de inyección y de comillas), comparación numérica `$3+0 > umbral` y formato con un solo printf. El estado de salida 1 = «hay hallazgos» es el contrato con el sistema de alertas."""),
            ("tool", r"""$ printf '  1234 node            87.3\n  1235 python         12.1\n  1236 mysqld         45.9\n  1237 bash            0.2\n' > ps.snapshot
$ bash alerta_cpu.sh ps.snapshot 80; echo "rc=$?"
ALERTA: pid 1234 (node) cpu 87.3% > 80%
rc=1
$ bash alerta_cpu.sh ps.snapshot 90; echo "rc=$?"
sin procesos por encima de 90%
rc=0"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
snap=${1:?uso: alerta_cpu.sh SNAPSHOT UMBRAL}
umbral=${2:?falta umbral}
[[ $umbral =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo "error: umbral numérico" >&2; exit 2; }
hallazgos=$(LC_ALL=C awk -v u="$umbral" '
  NF >= 3 && $1 ~ /^[0-9]+$/ {
    if ($3+0 > u) printf "ALERTA: pid %s (%s) cpu %s%% > %s%%\n", $1, $2, $3, u
  }' "$snap")
if [[ -n $hallazgos ]]; then
  echo "$hallazgos"
  exit 1
fi
echo "sin procesos por encima de ${umbral}%"
```
Decisiones: filtro `$1 ~ /^[0-9]+$/` ignora cabeceras y líneas basura del snapshot; `LC_ALL=C` evita comas decimales del locale; el umbral se valida antes de tocar el fichero (fallo rápido con exit 2 = uso incorrecto, distinto de 1 = alerta). El snapshot de ejemplo es exactamente lo que produce `ps -eo pid,comm,pcpu --no-headers`; en producción lo generará el cron y este script lo evaluará de forma reproducible. Verificado: umbral 80 → 1 alerta (node 87.3%) y exit 1; umbral 90 → limpio y exit 0."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "alerta_con_umbral_bajo", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "ps.snapshot", "content": r"""  1234 node            87.3
  1235 python         12.1
  1236 mysqld         45.9
  1237 bash            0.2
"""}],
             "args": ["ps.snapshot", "80"], "expect_exit": 1,
             "expect_stdout_contains": ["ALERTA: pid 1234 (node) cpu 87.3% > 80%"]},
            {"name": "limpio_con_umbral_alto", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "ps.snapshot", "content": "  1234 node            87.3\n"}],
             "args": ["ps.snapshot", "90"], "expect_exit": 0,
             "expect_stdout_contains": ["sin procesos por encima de 90%"]},
            {"name": "umbral_invalido", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "ps.snapshot", "content": "  1234 node            87.3\n"}],
             "args": ["ps.snapshot", "ochenta"], "expect_exit": 2,
             "expect_stdout_contains": ["umbral numérico"]},
        ],
        tags=["ps", "umbral", "alertas", "determinismo"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B13
    E(
        language="bash", domain="scripting_automation", subdomain="reintentos",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", r"""La llamada al servicio de firmas falla los dos primeros intentos (rate limit del proveedor) y funciona al tercero. Necesito un `retry` con backoff exponencial (0.10s, 0.20s, 0.40s, ...), máximo de intentos configurable, que (1) informe a stderr cada intento fallido y el backoff aplicado, (2) acumule el tiempo total de backoff, y (3) que se pueda usar con CUALQUIER comando, no solo con la llamada al servicio."""),
            ("assistant", r"""Diseño: función genérica `retry MAX comando args...` que ejecuta `"$@"` en un bucle `until` — así sirve para cualquier comando y respeta su código de salida. El backoff es una tabla (`0.10 0.20 0.40 0.80`) porque bash no tiene flotantes: evito aritmética de enteros con milisegundos que confunde. Para el «servicio inestable» del test, el script se invoca a sí mismo con un contador en fichero: así el fallo es REPRODUCIBLE en CI (falla 2 veces, succede a la 3ª) sin red ni mocks."""),
            ("tool", r"""$ bash reintentar.sh
intento 1 falló; backoff 0.10
intento 2 falló; backoff 0.20
respuesta: 42
backoff total: 0.30s
$ bash reintentar.sh estricto; echo "rc=$?"
intento 1 falló; backoff 0.10
error: agotados 2 intentos
rc=1"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
flaky() {
  local n
  n=$(<cnt.txt); n=$((n+1)); printf '%s\n' "$n" > cnt.txt
  if (( n >= 3 )); then echo "respuesta: 42"; return 0; fi
  return 1
}
retry() {
  local max=$1; shift
  local intento=1 k total=0
  local -a back=(0.10 0.20 0.40 0.80)
  until "$@"; do
    if (( intento >= max )); then
      echo "error: agotados $max intentos" >&2
      return 1
    fi
    k=$((intento-1))
    echo "intento $intento falló; backoff ${back[k]}" >&2
    total=$(LC_ALL=C awk -v a="$total" -v b="${back[k]}" 'BEGIN{printf "%.2f", a+b}')
    sleep "${back[k]}"
    intento=$((intento+1))
  done
  echo "backoff total: ${total}s" >&2
}
: > cnt.txt
if [[ ${1:-} == estricto ]]; then retry 2 flaky; else retry 5 flaky; fi
```
Decisiones: `until "$@"` repite el comando con sus argumentos intactos (sin re-parsear); el total de backoff se acumula con awk en punto flotante (bash solo tiene enteros); `sleep` va DESPUÉS de reportar y ANTES del siguiente intento; el modo `estricto` demuestra el agotamiento con exit 1. En producción, `flaky` se sustituye por la llamada real y el resto no cambia. Verificado: camino feliz (3 intentos, 0.30s acumulados) y agotamiento con 2 intentos."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "exito_en_tercer_intento", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["intento 1 falló; backoff 0.10",
                                        "intento 2 falló; backoff 0.20",
                                        "respuesta: 42",
                                        "backoff total: 0.30s"]},
            {"name": "agotamiento", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["estricto"], "expect_exit": 1,
             "expect_stdout_contains": ["agotados 2 intentos", "backoff 0.10"],
             "expect_stdout_not_contains": ["respuesta: 42"]},
        ],
        tags=["retry", "backoff", "resiliencia"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B15
    E(
        language="bash", domain="scripting_automation", subdomain="locks",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", r"""El job de rotación de logs se lanza por cron y a veces se pisa consigo mismo cuando una pasada tarda más que el intervalo. Quiero exclusión mutua real: si otra instancia está corriendo, la nueva debe RECHAZAR arrancar con mensaje claro y exit 1; y quiero demostración incluida de que el rechazo funciona. He visto ejemplos con ficheros pid, ¿por qué flock?"""),
            ("assistant", r"""Los ficheros pid tienen una enfermedad clásica: locks STALE (el proceso muere sin borrar el fichero, o el pid se recicla y el job se cree vivo). `flock` no tiene ese problema: el cerrojo vive en el descriptor de fichero y el kernel lo libera AL MORIR el proceso, pase lo que pase (kill -9 incluido). Diseño: abrir el lock en el fd 9 (`exec 9>`), intentarlo sin bloqueo (`flock -n 9`) y, para demostrar el rechazo, el script se invoca a sí mismo como hijo mientras el padre sostiene el cerrojo."""),
            ("tool", r"""$ bash rotacion.sh
hijo rechazado: instancia: no disponible, otra copia activa
trabajo principal completado
$ # el hijo por dentro:
$ bash rotacion.sh hijo; echo "rc=$?"
instancia: no disponible, otra copia activa
rc=1"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
exec 9>instancia.lock
if ! flock -n 9; then
  echo "instancia: no disponible, otra copia activa" >&2
  exit 1
fi
if [[ ${1:-demo} == demo ]]; then
  if bash "$0" hijo 2>err_hijo.txt; then
    echo "inesperado: el hijo entró" >&2
    exit 1
  fi
  echo "hijo rechazado: $(<err_hijo.txt)"
  echo "trabajo principal completado"
else
  echo "trabajo principal completado"
fi
```
Decisiones: `exec 9>instancia.lock` hereda el descriptor a los hijos, pero el CERROJO no se hereda (cada proceso debe flock-earlo), por eso el hijo pierde; `flock -n` (no bloqueante) en vez de `-w TIEMPO` porque en cron preferimos fallar rápido y avisar; el cerrojo se libera solo al cerrarse el fd al terminar el proceso — no hay limpieza que olvidar. Alternativa legítima: `flock -w 0` con el mismo efecto. En cron real, el cuerpo sería la rotación y el bloque `demo` no existiría. Verificado: el padre entra, el hijo es rechazado con exit 1 y mensaje a stderr, y el padre termina 0."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "exclusion_mutua_demostrada", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["hijo rechazado: instancia: no disponible, otra copia activa",
                                        "trabajo principal completado"]},
        ],
        tags=["flock", "lock", "cron", "exclusion_mutua"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B17
    E(
        language="bash", domain="scripting_automation", subdomain="checkpoints",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", r"""El procesador de lotes se cae a mitad por errores puntuales del proveedor (el item 5 de este lote) y hoy REPROCESA TODO desde el principio, duplicando efectos. Quiero: (1) checkpoint después de cada item (atómico: sin ficheros a medias), (2) reanudación desde el último checkpoint al relanzar, (3) una prueba automática que simule el crash, reanude y demuestre que no hay items procesados dos veces ni perdidos. El lote es `lote.txt` (8 items)."""),
            ("assistant", r"""Diseño: checkpoint = fichero `progreso.txt` con el índice del último item CONFIRMADO; se escribe con el patrón «escribe a temporal + mv» para que jamás exista un checkpoint corrupto (mv es atómico en el mismo sistema de ficheros). La reanudación salta los índices ≤ checkpoint. La prueba integra tres pasos en una ejecución: (a) crash simulado en el item 5 mediante un fichero bandera, (b) comprobar que la salida fue 1 y que el checkpoint quedó en 4, (c) reanudar y verificar cobertura total sin duplicados (comparando con `sort | uniq -d`)."""),
            ("tool", r"""$ bash lotes.sh
procesado: item-a
procesado: item-b
procesado: item-c
procesado: item-d
crash simulado en item 5 (checkpoint en 4)
reanudado desde: 4
procesado: item-e
procesado: item-f
procesado: item-g
procesado: item-h
total procesados: 8/8; duplicados: 0
$ cat progreso.txt
8"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
fase() {
  local lote=$1 i=0 item done_p=0
  if [[ -f progreso.txt ]]; then done_p=$(<progreso.txt); fi
  while IFS= read -r item; do
    i=$((i+1))
    if (( i <= done_p )); then continue; fi
    if [[ -f simular_fallo ]] && (( i == 5 )); then
      echo "crash simulado en item $i (checkpoint en $((i-1)))" >&2
      exit 1
    fi
    echo "procesado: $item" | tee -a processed.log
    printf '%s\n' "$i" > progreso.tmp
    mv progreso.tmp progreso.txt
  done < "$lote"
}
test_crash_resume() {
  rm -f progreso.txt processed.log
  : > simular_fallo
  if bash "$0" fase lote.txt; then
    echo "error: se esperaba el crash simulado" >&2
    exit 1
  fi
  rm -f simular_fallo
  if [[ -f progreso.txt ]]; then echo "reanudado desde: $(<progreso.txt)"; fi
  bash "$0" fase lote.txt
  local total dups
  total=$(wc -l < processed.log)
  dups=$(sort processed.log | uniq -d | wc -l)
  echo "total procesados: $total/8; duplicados: $dups"
  if (( dups != 0 )) || (( total != 8 )); then
    echo "error: cobertura inconsistente" >&2
    exit 1
  fi
}
if [[ ${1:-} == fase ]]; then fase "$2"; else test_crash_resume; fi
```
Decisiones: el checkpoint avanza SOLO tras el efecto (tee), nunca antes — orden «efecto → checkpoint»; `mv` garantiza checkpoint atómico; la reanudación es una MISMA función (menos código y menos divergencia); la prueba inyecta el fallo con un fichero bandera y lo retira para la segunda pasada, imitando el ciclo real «murió → operador relanza». En producción, el crash sería cualquier exit no cero: el mecanismo no cambia. Verificado: 8/8 items, 0 duplicados, checkpoint final 8."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "crash_y_reanudacion", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "timeout_s": 20,
             "fixtures": [{"name": "lote.txt", "content": "item-a\nitem-b\nitem-c\nitem-d\nitem-e\nitem-f\nitem-g\nitem-h\n"}],
             "expect_exit": 0,
             "expect_stdout_contains": ["crash simulado en item 5 (checkpoint en 4)",
                                        "reanudado desde: 4",
                                        "procesado: item-e",
                                        "total procesados: 8/8; duplicados: 0"]},
        ],
        tags=["checkpoints", "atomicidad", "reanudacion", "lotes"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B18
    E(
        language="bash", domain="tooling", subdomain="cli_getopts",
        difficulty="hard", task_type="testing",
        messages=[
            ("user", r"""Necesito la CLI de empaquetado con contrato estricto: `-d DIR` (obligatorio), `-n NOMBRE` (obligatorio), `-r N` retención (opcional, entero positivo), `-v` verbose, `-h` ayuda. Reglas: opción desconocida → exit 2 con uso en stderr; opción con valor ausente → exit 2; `-r` no numérica → exit 2; argumentos posicionales sobrantes → exit 2; y en éxito imprime el PLAN. Escribe además las pruebas del contrato."""),
            ("assistant", r"""`getopts` es la herramienta correcta (portable, maneja agrupación `-vn` y valores pegados `-nfoo`). Los puntos delicados: el caso `:` como primer carácter de la cadena de opciones activa el modo silencioso para controlar NOSOTROS los mensajes; `getopts` deja el mensaje de error en OPTARG con `?` o `:`; y tras el bucle hay que `shift $((OPTIND-1))` y rechazar posicionales sobrantes. Cada violación imprime uso a stderr y sale 2 (uso), reservando 1 para fallos de ejecución posteriores."""),
            ("tool", r"""$ bash empaquetar.sh -d datos -n noche -r 3 -v
plan: destino=datos nombre=noche retención=3 verbose=si
$ bash empaquetar.sh -x; echo "rc=$?"
uso: empaquetar.sh -d DIR -n NOMBRE [-r N] [-v]
opción desconocida: -x
rc=2
$ bash empaquetar.sh -d; echo "rc=$?"
uso: empaquetar.sh -d DIR -n NOMBRE [-r N] [-v]
la opción -d requiere un valor
rc=2
$ bash empaquetar.sh -d datos -n noche -r abc; echo "rc=$?"
uso: empaquetar.sh -d DIR -n NOMBRE [-r N] [-v]
la retención debe ser un entero positivo
rc=2"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
uso() {
  echo "uso: empaquetar.sh -d DIR -n NOMBRE [-r N] [-v]" >&2
}
dir="" nombre="" retencion=1 verbose=no
while getopts ":d:n:r:vh" opt; do
  case $opt in
    d) dir=$OPTARG ;;
    n) nombre=$OPTARG ;;
    r) if [[ ! $OPTARG =~ ^[1-9][0-9]*$ ]]; then
         uso; echo "la retención debe ser un entero positivo" >&2; exit 2
       fi
       retencion=$OPTARG ;;
    v) verbose=si ;;
    h) uso; exit 0 ;;
    :) uso; echo "la opción -$OPTARG requiere un valor" >&2; exit 2 ;;
    \?) uso; echo "opción desconocida: -$OPTARG" >&2; exit 2 ;;
  esac
done
shift $((OPTIND-1))
if (( $# > 0 )); then uso; echo "no se esperaban argumentos posicionales" >&2; exit 2; fi
if [[ -z $dir || -z $nombre ]]; then uso; echo "faltan -d/-n obligatorias" >&2; exit 2; fi
echo "plan: destino=$dir nombre=$nombre retención=$retencion verbose=$verbose"
```
Decisiones: el `:` inicial activa mensajes propios; `OPTARG` en los casos `:` y `\?` contiene la opción culpable; la validación de `-r` es regex estricta (rechaza 0, negativos y basura); los códigos: 2 = contrato de uso violado, 0 = plan válido; y la ayuda `-h` sale por stdout (es el RESULTADO pedido) con exit 0. Verificados los 5 caminos: éxito, desconocida, valor ausente, retención no numérica y posicionales sobrantes."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "plan_valido", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-d", "datos", "-n", "noche", "-r", "3", "-v"], "expect_exit": 0,
             "expect_stdout_contains": ["plan: destino=datos nombre=noche retención=3 verbose=si"]},
            {"name": "opcion_desconocida", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-x"], "expect_exit": 2,
             "expect_stdout_contains": ["uso: empaquetar.sh", "opción desconocida: -x"]},
            {"name": "valor_ausente", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-d"], "expect_exit": 2,
             "expect_stdout_contains": ["la opción -d requiere un valor"]},
            {"name": "retencion_no_numerica", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-d", "datos", "-n", "noche", "-r", "abc"], "expect_exit": 2,
             "expect_stdout_contains": ["entero positivo"]},
            {"name": "posicionales_sobrantes", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-d", "datos", "-n", "noche", "extra"], "expect_exit": 2,
             "expect_stdout_contains": ["no se esperaban argumentos posicionales"]},
        ],
        tags=["getopts", "cli", "contrato", "testing"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B19
    E(
        language="bash", domain="tooling", subdomain="exit_codes",
        difficulty="hard", task_type="testing",
        messages=[
            ("user", r"""Nuestro validador de logs lo llama un orquestador que SOLO ve el código de salida, así que necesito un contrato documentado y probado: 2 = uso incorrecto (sin argumentos), 3 = fichero inexistente, 4 = formato inválido (indicando la línea), 0 = válido (contando líneas). Todo diagnóstico a stderr. Formato esperado de cada línea: `YYYY-MM-DD HH:MM:SS NIVEL mensaje`. Implementa el validador con una función `die` y las pruebas de cada código."""),
            ("assistant", r"""Diseño: una función `die CODE MSG` centraliza «mensaje a stderr con prefijo error: + exit CODE», para que ningún camino de error escape sin contrato. La validación de formato usa regex en `[[ =~ ]]` por línea, llevando el contador de línea para el mensaje exacto. Importante para el orquestador: el exit 0 SOLO se emite al final, tras validar todo; nunca un `exit 0` implícito por caída del script."""),
            ("tool", r"""$ bash valida_log.sh; echo "rc=$?"
error: uso: valida_log.sh FICHERO
rc=2
$ bash valida_log.sh inexistente.log; echo "rc=$?"
error: no existe: inexistente.log
rc=3
$ bash valida_log.sh malo.log; echo "rc=$?"
error: formato inválido en línea 2: "garbage sin formato"
rc=4
$ bash valida_log.sh ok.log; echo "rc=$?"
validado: 3 líneas
rc=0"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
die() {
  local code=$1; shift
  echo "error: $*" >&2
  exit "$code"
}
(( $# == 1 )) || die 2 "uso: valida_log.sh FICHERO"
fich=$1
[[ -f $fich ]] || die 3 "no existe: $fich"
patron='^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} [A-Z]+ .+'
n=0
while IFS= read -r l || [[ -n $l ]]; do
  n=$((n+1))
  if [[ ! $l =~ $patron ]]; then
    die 4 "formato inválido en línea $n: \"$l\""
  fi
done < "$fich"
echo "validado: $n líneas"
```
Decisiones: códigos SIEMPRE distintos por causa y documentados en la cabecera del contrato — el orquestador puede decidir (2: no reintentar; 3: avisar de provisioning; 4: bloquear el fichero); `read -r l || [[ -n $l ]]` valida también la ÚLTIMA línea sin salto final (bug clásico de `while read`); el regex vive en una variable para no interpolar comillas problemáticas. Verificados los 4 códigos del contrato, cada uno con su mensaje en stderr."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "sin_argumentos_exit_2", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "expect_exit": 2, "expect_stdout_contains": ["uso: valida_log.sh FICHERO"]},
            {"name": "fichero_inexistente_exit_3", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["inexistente.log"], "expect_exit": 3,
             "expect_stdout_contains": ["no existe: inexistente.log"]},
            {"name": "formato_invalido_exit_4", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "malo.log", "content": "2024-03-15 10:00:00 INFO arranque\ngarbage sin formato\n"}],
             "args": ["malo.log"], "expect_exit": 4,
             "expect_stdout_contains": ["formato inválido en línea 2: \"garbage sin formato\""]},
            {"name": "valido_exit_0", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "ok.log", "content": "2024-03-15 10:00:00 INFO arranque\n2024-03-15 10:00:01 WARN lentitud\n2024-03-15 10:00:02 INFO listo\n"}],
             "args": ["ok.log"], "expect_exit": 0,
             "expect_stdout_contains": ["validado: 3 líneas"]},
        ],
        tags=["exit_codes", "stderr", "contrato", "die"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B20
    E(
        language="bash", domain="data", subdomain="arrays_asociativos",
        difficulty="hard", task_type="scripting",
        messages=[
            ("user", r"""Del inventario de la granja (CSV plano servidor,rol,región con cabecera) necesito recuentos por rol y por región usando arrays asociativos de bash. Puntos que quiero ver resueltos: claves leídas de datos (con comillas en el índice), inicialización de contadores sin avisos de unset, y salida ORDENADA (los arrays asociativos no conservan orden)."""),
            ("assistant", r"""Tres sutilezas reales: (1) `por_rol["$rol"]` SIEMPRE con comillas — una clave con espacios o glob chars se expandiría y desharía; (2) el contador se inicializa con `${por_rol["$rol"]:-0}` para no depender de `declare -i` ni de avisos; (3) `${!por_rol[@]}` devuelve las claves en ORDEN ARBITRARIO → ordenar con `sort`. La cabecera se salta comparando el primer campo, sin trucos frágiles de NR."""),
            ("tool", r"""$ bash inventario.sh
rol=cache: 1
rol=db: 2
rol=web: 3
region=ap: 1
region=eu: 3
region=us: 2
$ # sin sort, el orden varía entre ejecuciones:
$ bash inventario.sh | LC_ALL=C sort -r | head -2
rol=web: 3
region=us: 2"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
declare -A por_rol=() por_region=()
while IFS=, read -r srv rol region; do
  if [[ $srv == servidor ]]; then continue; fi
  por_rol["$rol"]=$(( ${por_rol["$rol"]:-0} + 1 ))
  por_region["$region"]=$(( ${por_region["$region"]:-0} + 1 ))
done < inventario.csv
for r in "${!por_rol[@]}"; do echo "rol=$r: ${por_rol["$r"]}"; done | LC_ALL=C sort
for r in "${!por_region[@]}"; do echo "region=$r: ${por_region["$r"]}"; done | LC_ALL=C sort
```
Decisiones: `IFS=, read -r` sin `-a` ni trampas (inventario controlado sin comas embebidas; para CSV con comillas usaríamos el parser del ejemplo de CSV); claves SIEMPRE citadas dentro de `[...]` y en la expansión; `${var:-0}` inicializa sin `set -u` casualties; `LC_ALL=C sort` da el mismo orden en cualquier runner. Verificado sobre 6 servidores: rol web 3, db 2, cache 1; región eu 3, us 2, ap 1 — con salida estable."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "recuentos_correctos", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "inventario.csv", "content": r"""servidor,rol,region
web01,web,eu
web02,web,eu
db01,db,eu
cache01,cache,us
web03,web,us
db02,db,ap
"""}],
             "expect_exit": 0,
             "expect_stdout_contains": ["rol=cache: 1", "rol=db: 2", "rol=web: 3",
                                        "region=ap: 1", "region=eu: 3", "region=us: 2"]},
        ],
        tags=["arrays_asociativos", "declare_a", "sort"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B21
    E(
        language="bash", domain="scripting_automation", subdomain="subshell_pipes",
        difficulty="extreme", task_type="debugging",
        messages=[
            ("user", r"""Este agregador nocturno imprime dentro del bucle las líneas correctas, pero el «válidos: 0» final es falso: sabemos que hay 4. Llevo horas con esto:
```bash
#!/usr/bin/env bash
set -euo pipefail
n=0; suma=0
grep -v '^#' eventos.log | while read -r l; do
  n=$((n+1))
  echo "loop: $l"
done
echo "válidos: $n"
```
El grep funciona (lo probé). ¿Qué está pasando?"""),
            ("assistant", r"""Síntoma: las líneas PASAN por el bucle (el `echo` del cuerpo las muestra) pero el contador exterior queda a 0. Hipótesis primera (fallida): «el grep no entrega nada» — descartada porque el cuerpo sí itera. Hipótesis correcta: el ÚLTIMO comando de un pipeline (`while ... done`) se ejecuta en un SUBSHELL: tiene su propia copia de `n` y `suma`, y al morir el subshell, las variables muere con él. El padre nunca vio esos incrementos. Experimento: demostrar el aislamiento y validar el fix con process substitution, donde NO hay pipe y el while corre en el shell actual."""),
            ("tool", r"""$ printf 'INFO carga 12\n# pausa\nINFO cálculo 34\nINFO envío 46\n# fin\nINFO cierre 8\n' > eventos.log
$ bash agregador.sh
loop: INFO carga 12
loop: INFO cálculo 34
loop: INFO envío 46
loop: INFO cierre 8
válidos: 0
$ bash -c 'x=1; echo hola | x=42; echo "tras pipe: $x"'
tras pipe: 1
$ # con < <(...) el while NO es subshell:
$ bash -c 'x=0; while read -r l; do x=$((x+1)); done < <(echo hola); echo "con procsub: $x"'
con procsub: 1"""),
            ("assistant", r"""Confirmado: en `comando | while`, el while vive en un subshell (copia de variables); con `while ... done < <(comando)` el while corre en el shell principal y los efectos persisten. Causa raíz: pérdida de variables por subshell en pipeline. Corrección:
```bash
#!/usr/bin/env bash
set -euo pipefail
n=0; suma=0
while read -r l; do
  n=$((n+1))
  valor=${l##* }
  suma=$(( suma + valor ))
  echo "loop: $l"
done < <(grep -v '^#' eventos.log)
echo "válidos: $n"
echo "suma: $suma"
```
Decisiones: `< <(...)` mantiene el bucle en el shell actual y redirige stdin desde el PROCESO (no fichero) — grep sigue siendo una tubería por dentro; alternativa equivalente y a veces más clara: `mapfile -t lineas < <(grep ...)` y iterar sobre el array; evitar la «solución» `cat | while` con ficheros temporales. Nota portable: en POSIX sh sin process substitution, este patrón exige ficheros temporales o awk — otra razón para fijar bash en el shebang. Verificado: válidos: 4, suma: 100 (12+34+46+8), y el orden de impresión se conserva."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "original_pierde_variables", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [{"name": "eventos.log", "content": "INFO carga 12\n# pausa\nINFO cálculo 34\nINFO envío 46\n# fin\nINFO cierre 8\n"}],
             "expect_exit": 0,
             "expect_stdout_contains": ["loop: INFO carga 12", "válidos: 0"]},
            {"name": "fijo_contadores_persisten", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "eventos.log", "content": "INFO carga 12\n# pausa\nINFO cálculo 34\nINFO envío 46\n# fin\nINFO cierre 8\n"}],
             "expect_exit": 0,
             "expect_stdout_contains": ["válidos: 4", "suma: 100"]},
        ],
        tags=["subshell", "pipe", "process_substitution", "variables"], stack=["bash"], recovery=True,
    ),
]
