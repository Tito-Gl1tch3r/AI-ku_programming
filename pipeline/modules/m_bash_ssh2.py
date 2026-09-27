"""m_bash_ssh2.py — Stack V2, continuación de m_bash_ssh (16 ejemplos: 11 Bash + 5 SSH).

Parte 2 del par Bash/SSH. Evita solapar pipefail/comillas/subshell (parte 1) y
profundiza: flock con liberación explícita (dos intentos), backoff determinista
con escala sleep 0, xargs -P con código 123, getopts con sysexits 64, claves de
arrays asociativos con espacios, watchdog pgrep con umbral, rotación de logs
por generaciones con tar determinista, dedupe en una pasada con awk, fusión de
CSVs con cabecera común, trap ERR con localización, checkpoint efecto-primero;
y SSH legítimo de administración propia: ssh_config razonado, doctor de
authorized_keys (ejecutable en laboratorio local), túneles -L/-R, rsync de
backups con verificación de hash y hardening de sshd. Las conexiones remotas
NO se ejecutan: los pasos SSH se limitan a sintaxis y a explicar cómo se
comprobaría (ssh -G, sshd -t, ss, manifiestos de hash).
"""

from schema import E

EXAMPLES = [
    # ------------------------------------------------------------------ B01
    E(
        language="bash", domain="scripting_automation", subdomain="flock_dos_intentos",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", r"""El job de precios se lanza desde dos sitios (cron y un hook de despliegue) y necesito exclusión mutua DEMOSTRABLE, no solo «que parezca que funciona». Requisitos: (1) si otra instancia sostiene el cerrojo, el intento nuevo se rechaza con exit 1 y mensaje claro; (2) cuando el titular LIBERA explícitamente, un intento posterior debe entrar; (3) el propio script debe incluir la demo de los dos intentos (rechazo → liberación → éxito) para poder verla en CI sin temporizadores."""),
            ("assistant", r"""Diseño con `flock` sobre el descriptor 9: el titular abre `precio.lock` con `exec 9>` y lo ADQUIERE con `flock -n 9` (no bloqueante: en jobs automáticos preferimos fallar rápido a encolar sin límite). El modo `worker` reabre el mismo fichero y compite por el cerrojo; como cada proceso tiene su propia open file description, mientras el titular no libere, el worker pierde. La liberación explícita es `flock -u 9` — aunque al morir el proceso el kernel libera igualmente, hacerla explícita permite la demo determinista de los dos intentos: rechazo con el cerrojo sostenido y éxito tras `flock -u`, sin sleeps ni esperas."""),
            ("tool", r"""$ bash precios.sh
principal: sostiene el cerrojo
intento 1: worker: cerrojo ocupado, saliendo
principal: cerrojo liberado (flock -u)
worker: cerrojo adquirido, trabajo simulado ejecutado
intento 2: adquirido tras la liberación
principal: fin
$ bash precios.sh; echo "rc=$?"   # repetible: mismo resultado en cada pasada
principal: sostiene el cerrojo
intento 1: worker: cerrojo ocupado, saliendo
principal: cerrojo liberado (flock -u)
worker: cerrojo adquirido, trabajo simulado ejecutado
intento 2: adquirido tras la liberación
principal: fin
rc=0"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == worker ]]; then
  exec 9>>precio.lock
  if flock -n 9; then
    echo "worker: cerrojo adquirido, trabajo simulado ejecutado"
    flock -u 9
  else
    echo "worker: cerrojo ocupado, saliendo" >&2
    exit 1
  fi
  exit 0
fi
exec 9>precio.lock
flock -n 9 || { echo "principal: el cerrojo ya está sostenido" >&2; exit 1; }
echo "principal: sostiene el cerrojo"
if bash "$0" worker 2>rechazo.txt; then
  echo "principal: error interno, el segundo intento no debía entrar" >&2
  exit 1
fi
echo "intento 1: $(<rechazo.txt)"
flock -u 9
echo "principal: cerrojo liberado (flock -u)"
if bash "$0" worker 2>/dev/null; then
  echo "intento 2: adquirido tras la liberación"
fi
echo "principal: fin"
```
Decisiones: el worker abre con `>>` (append) para no truncar el fichero de lock del titular; el titular verifica su adquisición con `flock -n 9 || exit` en vez de darla por hecha — abrir el fd no basta, el cerrojo hay que tomarlo; el rechazo del hijo se captura en un fichero para mostrarlo como evidencia con `$(<rechazo.txt)`; y si el hijo ENTRARA (regresión futura), el padre lo detecta con el `if bash "$0" worker` y aborta: la demo es también un test de regresión. Alternativas documentadas: `flock -w 0` equivale a `-n`, y `-w 30` sirve para colas pacientes. Verificado: intento 1 rechazado (rc 1), liberación explícita, intento 2 exitoso, y el conjunto repetible en cada pasada."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "exclusion_y_liberacion_demostradas", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["principal: sostiene el cerrojo",
                                        "intento 1: worker: cerrojo ocupado, saliendo",
                                        "principal: cerrojo liberado (flock -u)",
                                        "worker: cerrojo adquirido, trabajo simulado ejecutado",
                                        "intento 2: adquirido tras la liberación",
                                        "principal: fin"]},
        ],
        tags=["flock", "exclusion_mutua", "cron", "cerrojos"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B02
    E(
        language="bash", domain="scripting_automation", subdomain="backoff_escalado",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", r"""Contra el proveedor de firmas tenemos dos experiencias opuestas: con reintentos inmediatos nos extendía el bloqueo (cada llamada fallida apuraba más el rate limit) y con pausas fijas de 1s el job nocturno se eternizaba. Quiero un `retry` con backoff exponencial (100ms, 200ms, 400ms, ... con tope en 800ms), máximo de intentos configurable, que informe cada intento y el backoff acumulado. Y un requisito de CI: las pausas reales deben poder escalarse a cero (`sleep 0`) SIN tocar la lógica, para que el test sea rápido pero ejecute el mismo código que producción."""),
            ("assistant", r"""Primera estrategia (reintento inmediato, presupuesto corto): descartada — el proveedor responde mejor a ventana creciente que a martilleo; lo demostraré con un modo `fijo` que se agota. Estrategia final: backoff exponencial base 100ms con tope 800ms y presupuesto de intentos por argumento. El requisito de CI se resuelve con un factor de ESCALA: el retardo se calcula en milisegundos (bash no tiene flotantes) y el `sleep` real es `ms*ESCALA/1000`; con ESCALA=0 el `sleep` degenera en `sleep 0` (un yield) y la POLÍTICA de backoff se calcula e informa igual que en producción. El servicio inestable del test es reproducible sin red: un contador en fichero que responde OK a partir de la 4ª llamada."""),
            ("tool", r"""$ bash reintentar.sh exp 5
intento 1 falló (backoff 100ms)
intento 2 falló (backoff 200ms)
intento 3 falló (backoff 400ms)
respuesta: OK
backoff total: 700ms
$ bash reintentar.sh fijo 2; echo "rc=$?"
intento 1 falló (backoff 100ms)
error: agotados 2 intentos
rc=1"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
# ESCALA: multiplicador real de las pausas. En producción: 1. En CI/demo: 0.
escala=${ESCALA:-0}
dormir() {
  local s
  s=$(LC_ALL=C awk -v ms="$(( $1 * escala ))" 'BEGIN{printf "%.3f", ms/1000}')
  sleep "$s"
}
llamada() {
  local n
  n=$(<intentos.txt); n=$((n+1)); printf '%s\n' "$n" > intentos.txt
  if (( n >= 4 )); then echo "respuesta: OK"; return 0; fi
  return 1
}
retry() {
  local modo=$1 max=$2 intento=1 delay=0 total=0
  until llamada; do
    if (( intento >= max )); then
      echo "error: agotados $max intentos" >&2
      return 1
    fi
    if [[ $modo == fijo ]]; then
      delay=100
    else
      delay=$(( 100 * (2 ** (intento-1)) ))
      (( delay > 800 )) && delay=800
    fi
    echo "intento $intento falló (backoff ${delay}ms)" >&2
    dormir "$delay"
    total=$(( total + delay ))
    intento=$(( intento+1 ))
  done
  echo "backoff total: ${total}ms"
}
: > intentos.txt
retry "${1:-exp}" "${2:-5}"
```
Decisiones: `until llamada` repite la llamada respetando su código de salida, así el mecanismo sirve para CUALQUIER comando; la política (fijo vs exponencial) es un parámetro, no dos copias del bucle; el tope `(( delay > 800 )) && delay=800` evita backoff absurdos con servicios caídos de verdad (con 5 intentos no llega a actuar: 100+200+400); el total se acumula en ENTEROS de ms y se reporta una sola vez — cero flotantes en bash; y `dormir` es el único punto que conoce ESCALA, así el test corre en milisegundos sin bifurcar la lógica. En producción: `ESCALA=1 bash reintentar.sh exp 5`. Verificado: modo exp prospera en la 4ª llamada con 700ms acumulados; modo fijo con presupuesto 2 se agota con rc 1 y sin «respuesta: OK»."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "exito_con_backoff_exponencial", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["exp", "5"], "expect_exit": 0,
             "expect_stdout_contains": ["intento 1 falló (backoff 100ms)",
                                        "intento 2 falló (backoff 200ms)",
                                        "intento 3 falló (backoff 400ms)",
                                        "respuesta: OK",
                                        "backoff total: 700ms"]},
            {"name": "estrategia_fija_se_agota", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["fijo", "2"], "expect_exit": 1,
             "expect_stdout_contains": ["error: agotados 2 intentos", "intento 1 falló (backoff 100ms)"],
             "expect_stdout_not_contains": ["respuesta: OK"]},
        ],
        tags=["retry", "backoff", "determinismo", "resiliencia"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B03
    E(
        language="bash", domain="scripting_automation", subdomain="xargs_paralelo_fallos",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", r"""Publicamos lotes de chunks validándolos en paralelo; anoche se publicó un lote corrupto y nadie entendió cómo pudo salir a producción. La validación está ahí, mírala:
```bash
#!/usr/bin/env bash
set -euo pipefail
# v1: «no queremos que CI muera por un chunk suelto»
printf '%s\0' *.chunk | xargs -0 -P 3 -n 1 -r sh -c 'grep -q "^schema:" "$1" || exit 1' _ || true
echo "lote validado: listo para publicar"
```
Los chunks los genera un proceso upstream; si a un chunk le falta la línea `schema:`, debe bloquearse la publicación entera, no colarse."""),
            ("assistant", r"""Síntoma: publicación con chunks inválidos y CI en verde. Hipótesis inicial (fallida): «el grep no encuentra la línea por algún espacio» — descartada: los chunks corruptos NO contienen la línea en absoluto y el grep hace su trabajo. La causa vive en la ÚLTIMA línea del pipeline: `|| true` enmascara el código de salida de `xargs`. Y hay una semántica de xargs poco conocida: con `-P 3` los workers van en paralelo y si ALGUNO falla (rc 1-125), xargs termina con el código 123. Es decir, xargs YA estaba gritando el fallo; el `|| true` lo silencia y el script sigue con exit 0. Experimento: quitar el `|| true` y observar el 123, y listar los culpables con `grep -L`."""),
            ("tool", r"""$ printf '%s\0' *.chunk | xargs -0 -P 3 -n 1 -r sh -c 'grep -q "^schema:" "$1" || exit 1' _ ; echo "rc=$?"
rc=123
$ grep -L '^schema:' *.chunk
chunk_03.chunk
chunk_05.chunk"""),
            ("assistant", r"""Confirmado: xargs devuelve 123 cuando algún worker falla, y `grep -L` nombra los dos chunks culpables. La corrección: preservar el rc de xargs (sin `|| true`), invocar como worker `bash "$0" worker` (script autocontenido) para recolectar los rechazos, y FALLAR el lote entero si hubo cualquiera:
```bash
#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == worker ]]; then
  f=$2
  if grep -q '^schema:' "$f"; then
    echo "ok: $f"
  else
    echo "rechazado: $f (falta 'schema:')" >> fallos.log
    exit 1
  fi
  exit 0
fi
rm -f fallos.log resultados.txt
total=$(printf '%s\n' *.chunk | wc -l)
rc=0
printf '%s\0' *.chunk | LC_ALL=C sort -z | xargs -0 -P 3 -n 1 -r bash "$0" worker > resultados.txt || rc=$?
oks=$(grep -c '^ok: ' resultados.txt || true)
malos=0
[[ -f fallos.log ]] && malos=$(wc -l < fallos.log)
echo "validación: $oks/$total correctos, $malos rechazados (xargs rc=$rc)"
if (( rc != 0 )); then
  echo "--- fallos ---"
  LC_ALL=C sort fallos.log
  echo "lote rechazado: NO publicar"
  exit 1
fi
echo "lote validado: listo para publicar"
```
Decisiones: `rc=0; pipeline || rc=$?` captura el 123 sin que `set -e` mate el script antes de reportar; los workers anexan los rechazos a `fallos.log` (líneas cortas: los append son atómicos en la práctica) y se ordenan al imprimir porque con `-P 3` el orden de finalización no es determinista; `printf '%s\0' *.chunk | LC_ALL=C sort -z` fija el orden de ENTRADA de forma reproducible; y el mensaje final distingue «lote validado» (rc 0) de «lote rechazado: NO publicar» (rc 1) para que el pipeline decida. Lección: nunca enmascarar códigos de herramientas de lote — el 123 es la señal estándar de «algún hijo falló». Verificado: 4/6 correctos, 2 rechazados nombrados, publicación bloqueada; y con lote sano, rc 0 y «listo para publicar»."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "bug_publica_con_fallos", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [
                 {"name": "chunk_01.chunk", "content": "schema: ventas v2\nfila-1\n"},
                 {"name": "chunk_02.chunk", "content": "schema: ventas v2\nfila-2\n"},
                 {"name": "chunk_03.chunk", "content": "fila-3 sin marca\n"},
                 {"name": "chunk_04.chunk", "content": "schema: ventas v2\nfila-4\n"},
                 {"name": "chunk_05.chunk", "content": "fila-5 corrupta\n"},
                 {"name": "chunk_06.chunk", "content": "schema: ventas v2\nfila-6\n"},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["lote validado: listo para publicar"],
             "expect_stdout_not_contains": ["rechazado"]},
            {"name": "fix_bloquea_y_nombra_culpables", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "chunk_01.chunk", "content": "schema: ventas v2\nfila-1\n"},
                 {"name": "chunk_02.chunk", "content": "schema: ventas v2\nfila-2\n"},
                 {"name": "chunk_03.chunk", "content": "fila-3 sin marca\n"},
                 {"name": "chunk_04.chunk", "content": "schema: ventas v2\nfila-4\n"},
                 {"name": "chunk_05.chunk", "content": "fila-5 corrupta\n"},
                 {"name": "chunk_06.chunk", "content": "schema: ventas v2\nfila-6\n"},
             ],
             "expect_exit": 1,
             "expect_stdout_contains": ["validación: 4/6 correctos, 2 rechazados (xargs rc=123)",
                                        "rechazado: chunk_03.chunk (falta 'schema:')",
                                        "rechazado: chunk_05.chunk (falta 'schema:')",
                                        "lote rechazado: NO publicar"],
             "expect_stdout_not_contains": ["listo para publicar"]},
            {"name": "fix_lote_sano_publica", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "chunk_01.chunk", "content": "schema: ventas v2\nfila-1\n"},
                 {"name": "chunk_02.chunk", "content": "schema: ventas v2\nfila-2\n"},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["validación: 2/2 correctos, 0 rechazados (xargs rc=0)",
                                        "lote validado: listo para publicar"]},
        ],
        tags=["xargs", "paralelo", "exit_123", "pipeline"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B04
    E(
        language="bash", domain="tooling", subdomain="cli_sysexits",
        difficulty="hard", task_type="testing",
        messages=[
            ("user", r"""La CLI de empaquetado la van a llamar orquestadores escritos en tres lenguajes distintos, así que el contrato de códigos de salida debe ser EXPLÍCITO y estándar, no «el 2 porque sí». Contrato pedido: uso incorrecto de la línea de comandos → 64 (EX_USAGE de sysexits.h); éxito → 0. Opciones: `-k CLAVE` (obligatoria), `-t SEG` timeout con rango válido 1..300 (por defecto 60), `-v` repetible (nivel de verbosidad), `-h` ayuda. Al menos un FICHERO posicional obligatorio. Quiero el script y las pruebas de cada violación del contrato."""),
            ("assistant", r"""Buena decisión usar sysexits.h: el 64 es el código canónico de «el usuario escribió mal la invocación», distinguible de cualquier fallo posterior de ejecución. Puntos técnicos de getopts: el `:` inicial activa el modo silencioso (los mensajes de error son NUESTROS, no los de bash); en los casos `:` y `\?`, OPTARG contiene la opción culpable; tras el bucle, `shift $((OPTIND-1))` deja solo los posicionales. La validación de `-t` debe rechazar no-numéricos ANTES de la aritmética (un `(( OPTARG < 1 ))` con "abc" explotaría por su cuenta) y el rango 1..300 se comprueba en la misma condición con cortocircuito por `||`."""),
            ("tool", r"""$ bash empaquetar2.sh -k release -t 120 -vv a.log b.log
plan: clave=release timeout=120s verbosidad=2 ficheros=2
$ bash empaquetar2.sh -k release -t 500 a.log; echo "rc=$?"
uso: empaquetar2.sh -k CLAVE [-t SEG] [-v]... FICHERO...
error: -t exige un entero entre 1 y 300 (recibido: '500')
rc=64
$ bash empaquetar2.sh -k release; echo "rc=$?"
uso: empaquetar2.sh -k CLAVE [-t SEG] [-v]... FICHERO...
error: falta al menos un FICHERO
rc=64"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
uso() {
  echo "uso: empaquetar2.sh -k CLAVE [-t SEG] [-v]... FICHERO..." >&2
}
clave="" timeout=60 verbosidad=0
while getopts ":k:t:vh" opt; do
  case $opt in
    k) clave=$OPTARG ;;
    t) if [[ ! $OPTARG =~ ^[0-9]+$ ]] || (( OPTARG < 1 )) || (( OPTARG > 300 )); then
         uso; echo "error: -t exige un entero entre 1 y 300 (recibido: '$OPTARG')" >&2
         exit 64
       fi
       timeout=$OPTARG ;;
    v) verbosidad=$(( verbosidad+1 )) ;;
    h) echo "uso: empaquetar2.sh -k CLAVE [-t SEG] [-v]... FICHERO..."
       exit 0 ;;
    :) uso; echo "error: la opción -$OPTARG requiere un valor" >&2; exit 64 ;;
    \?) uso; echo "error: opción desconocida: -$OPTARG" >&2; exit 64 ;;
  esac
done
shift $(( OPTIND-1 ))
[[ -n $clave ]] || { uso; echo "error: falta -k CLAVE (obligatoria)" >&2; exit 64; }
(( $# > 0 )) || { uso; echo "error: falta al menos un FICHERO" >&2; exit 64; }
echo "plan: clave=$clave timeout=${timeout}s verbosidad=$verbosidad ficheros=$#"
```
Decisiones: TODAS las violaciones del contrato de invocación salen por 64 con la línea de uso en stderr; la ayuda `-h`, en cambio, es una RESPUESTA pedida: stdout y 0. `-v` es acumulable sin lógica extra (`verbosidad=$((verbosidad+1))`) y el plan informa el nivel; el regex `^[0-9]+$` se evalúa primero y el `||` cortocircuita antes de tocar la aritmética con basura; y el `plan:` final es la única salida del camino de éxito, fácil de consumir por los orquestadores. Verificados los seis caminos: plan válido, -t fuera de rango, -t no numérica, opción desconocida, valor ausente y obligatorias incumplidas (-k y FICHERO)."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "plan_valido", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-k", "release", "-t", "120", "-vv", "a.log", "b.log"], "expect_exit": 0,
             "expect_stdout_contains": ["plan: clave=release timeout=120s verbosidad=2 ficheros=2"]},
            {"name": "timeout_fuera_de_rango_64", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-k", "release", "-t", "500", "a.log"], "expect_exit": 64,
             "expect_stdout_contains": ["-t exige un entero entre 1 y 300 (recibido: '500')"]},
            {"name": "timeout_no_numerico_64", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-k", "release", "-t", "abc", "a.log"], "expect_exit": 64,
             "expect_stdout_contains": ["-t exige un entero entre 1 y 300"]},
            {"name": "opcion_desconocida_64", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-x"], "expect_exit": 64,
             "expect_stdout_contains": ["opción desconocida: -x"]},
            {"name": "valor_ausente_64", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-t"], "expect_exit": 64,
             "expect_stdout_contains": ["la opción -t requiere un valor"]},
            {"name": "falta_fichero_64", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["-k", "release"], "expect_exit": 64,
             "expect_stdout_contains": ["falta al menos un FICHERO"]},
            {"name": "falta_clave_64", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["a.log"], "expect_exit": 64,
             "expect_stdout_contains": ["falta -k CLAVE (obligatoria)"]},
        ],
        tags=["getopts", "sysexits", "cli", "contrato"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B05
    E(
        language="bash", domain="data", subdomain="claves_con_espacios",
        difficulty="hard", task_type="debugging",
        messages=[
            ("user", r"""El resumen de transferencias por host da cifras imposibles: para `web-01` y `web-02` cuadra con mi suma a mano, pero las claves de sala con espacio (`rack norte`, `rack sur`) se comportan mal. Formato del log, separado por `|`: host|bytes. Los nombres de sala SÍ pueden contener espacios, así que no puedo prohibirlos. El script:
```bash
#!/usr/bin/env bash
set -euo pipefail
declare -A total=()
while IFS='|' read -r host bytes; do
  [[ $host == host ]] && continue
  total["$host"]=$(( ${total["$host"]:-0} + bytes ))
done < transferencias.log
for k in ${!total[@]}; do
  echo "$k: ${total[$k]}"
done | LC_ALL=C sort
```
Los datos de hoy: web-01|120, rack norte|350, web-02|80, rack norte|50, rack sur|90, web-01|40."""),
            ("assistant", r"""Primera hipótesis (fallida): «la suma aritmética pierde filas». Se descarta rápido: los totales de los hosts SIN espacios cuadran y el `while` consume los 6 registros. Segunda hipótesis: el problema vive en la EXPANSIÓN de claves, no en la aritmética. Fíjate en la asimetría del script: las ESCRITURAS usan `total["$host"]` (citadas) pero la ITERACIÓN usa `${!total[@]}` SIN comillas. Sin comillas, la expansión sufre word splitting: la clave `rack norte` se parte en las palabras `rack` y `norte`, y `${total[$k]}` acaba consultando claves que NO existen. Con `set -u`, leer una clave inexistente de un array asociativo es error fatal. Experimento: imprimir las claves con y sin comillas."""),
            ("tool", r"""$ bash resumen.sh; echo "rc=$?"
bash: línea 10: total[$k]: unbound variable
rc=1
$ declare -A t=(); t["rack norte"]=400; t["rack sur"]=90
$ printf '[%s]\n' ${!t[@]}
[rack]
[norte]
[sur]
$ printf '[%s]\n' "${!t[@]}"
[rack norte]
[rack sur]"""),
            ("assistant", r"""Confirmado con el experimento mínimo: `${!t[@]}` sin comillas parte `rack norte` en dos palabras — el bucle jamás ve la clave real y `${total[$k]}` consulta claves fantasma hasta que `set -u` aborta. Causa raíz: expansión sin citar de `${!total[@]}` con claves que contienen espacios. Corrección (dos comillas, no una):
```bash
#!/usr/bin/env bash
set -euo pipefail
declare -A total=()
while IFS='|' read -r host bytes; do
  [[ $host == host ]] && continue
  total["$host"]=$(( ${total["$host"]:-0} + bytes ))
done < transferencias.log
for k in "${!total[@]}"; do
  echo "$k: ${total[$k]}"
done | LC_ALL=C sort
```
Decisiones: `for k in "${!total[@]}"` — la expansión citada entrega cada clave COMO UNA palabra; en el cuerpo, `"${total[$k]}"` cita el VALOR (inocuo en un echo simple, obligatorio en cuanto la línea crece) y el subíndice `$k` es seguro porque las claves llegan íntegras. Nota: las escrituras del bucle original ya estaban citadas — el bug solo apareció al ITERAR, y por eso el fix toca exclusivamente la línea del `for`. El `LC_ALL=C sort` mantiene la salida estable sin importar el locale del runner. Verificado sobre los 6 registros: rack norte: 400 (350+50), rack sur: 90, web-01: 160, web-02: 80."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "bug_muere_con_clave_espaciada", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [{"name": "transferencias.log", "content": r"""host|bytes
web-01|120
rack norte|350
web-02|80
rack norte|50
rack sur|90
web-01|40
"""}],
             "expect_fail": True,
             "expect_stdout_contains": ["unbound variable"]},
            {"name": "fix_totales_correctos", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "transferencias.log", "content": r"""host|bytes
web-01|120
rack norte|350
web-02|80
rack norte|50
rack sur|90
web-01|40
"""}],
             "expect_exit": 0,
             "expect_stdout_contains": ["rack norte: 400", "rack sur: 90",
                                        "web-01: 160", "web-02: 80"]},
        ],
        tags=["arrays_asociativos", "word_splitting", "set-u", "debugging"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B06
    E(
        language="bash", domain="systems", subdomain="watchdog_pgrep",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", r"""Necesito un watchdog de instancias para la guardia: cuenta cuántos procesos de un patrón hay vivos y compara contra un umbral (por encima → alerta con exit 1; dentro → exit 0). El problema es el test: en CI no hay procesos de mi servicio, y la variante con capturas congeladas de `ps` ya la tengo en otro script. Quiero que ESTE use `pgrep -fc` de verdad y que su test sea determinista: el propio script debe fabricar un número EXACTO de procesos vivos, contarlos y apagarlos limpio, sin sleeps largos ni carreras."""),
            ("assistant", r"""El truco para el determinismo: el script se autoinvoca en modo `worker` 4 veces; cada worker gira en un bucle `until [[ -f apagado.flag ]]; do sleep 0; done` — vivos y con consumo mínimo hasta que el padre cree la bandera. El padre cuenta con `pgrep -fc -- "$patrón"`, donde el patrón incluye el basename del script, la palabra `worker` y el PID del padre: así el conteo es inmune a ejecuciones concurrentes y no se cuenta a sí mismo. El bucle de espera re-intenta con `sleep 0` hasta ver EXACTAMENTE los 4 workers (la ventana fork→exec hace que un primer conteo pueda quedarse corto). Apagado determinista: `touch apagado.flag` + `wait` para recogerlos, y un trap EXIT garantiza que ningún worker quede huérfano aunque el script muera antes."""),
            ("tool", r"""$ bash watchdog.sh 10; echo "rc=$?"
observados: 4 procesos con patrón 'watchdog.sh worker 7222'
dentro del umbral: 4 <= 10
rc=0
$ bash watchdog.sh 3; echo "rc=$?"
observados: 4 procesos con patrón 'watchdog.sh worker 7363'
umbral superado: 4 > 3 (escala el servicio o revisa fugas)
rc=1"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == worker ]]; then
  until [[ -f apagado.flag ]]; do sleep 0; done
  exit 0
fi
umbral=${1:?uso: watchdog.sh UMBRAL}
patron="$(basename "$0") worker $$"
trap 'touch apagado.flag' EXIT
rm -f apagado.flag
for _ in 1 2 3 4; do
  bash "$0" worker "$$" &
done
n=0
for _ in $(seq 1 500); do
  n=$(pgrep -fc -- "$patron" || true); n=${n:-0}
  (( n == 4 )) && break
  sleep 0
done
echo "observados: $n procesos con patrón '$patron'"
touch apagado.flag
wait
if (( n > umbral )); then
  echo "umbral superado: $n > $umbral (escala el servicio o revisa fugas)"
  exit 1
fi
echo "dentro del umbral: $n <= $umbral"
```
Decisiones: `pgrep -fc` imprime el CONTEO (-c) contra la línea completa de comandos (-f); su exit 1 «sin coincidencias» se neutraliza con `|| true` para que `set -e` no mate el sondeo — un conteo 0 es un valor legítimo, no un fallo; el patrón anclado al `$$` del padre hace el test inmune a otros tests concurrentes; `touch apagado.flag` ANTES de `wait` evita colgar esperando workers que ya no pueden terminar; y el trap EXIT es el cinturón anti-huérfanos. En producción, el bloque de fabricación se sustituye por `patron='mi-servicio'` y nada más cambia: los códigos 0/1 son el contrato con el sistema de alertas. Verificado: umbral 10 → verde; umbral 3 → alerta rc 1; conteo exacto 4 en cada pasada."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "dentro_del_umbral", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["10"], "expect_exit": 0,
             "expect_stdout_contains": ["observados: 4 procesos", "dentro del umbral: 4 <= 10"]},
            {"name": "umbral_superado", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["3"], "expect_exit": 1,
             "expect_stdout_contains": ["observados: 4 procesos",
                                        "umbral superado: 4 > 3 (escala el servicio o revisa fugas)"]},
        ],
        tags=["pgrep", "watchdog", "umbral", "determinismo"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B07
    E(
        language="bash", domain="systems", subdomain="rotacion_generaciones",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", r"""Auditoría nos pidió los logs del martes y NO ESTÁN: solo existe el de ayer. La rotación la hace este script mínimo y juraría que funcionaba:
```bash
#!/usr/bin/env bash
set -euo pipefail
log=app.log
if (( $(wc -c < "$log") > 200 )); then
  mv "$log" "$log.1"
  echo "rotado"
fi
wc -c "$log.1"
```
El job corre a diario. Hoy app.log pesa 488 bytes y ayer app.log.1 pesaba 244. ¿Dónde está el log del martes?"""),
            ("assistant", r"""Síntoma: solo sobrevive UNA generación. Hipótesis a confirmar con el propio script: `mv app.log app.log.1` SOBREESCRIBE el app.log.1 de ayer sin advertir — mv no pregunta cuando el destino existe. El log del martes (que estaba en app.log.1) se pierde en el instante del mv. Experimento: ejecutar la rotación con un app.log.1 preexistente y mirar qué queda dentro. La corrección será un desplazamiento de generaciones en orden inverso (.1→.2 antes de mover el actual a .1) y, ya que tocamos el job, el archivo en tar DETERMINISTA (comprobable byte a byte entre ejecuciones) para la auditoría."""),
            ("tool", r"""$ # estado antes: app.log (hoy, 488 bytes) y app.log.1 (ayer, 244 bytes)
$ bash rota_v1.sh
rotado
488 app.log.1
$ # wc dice 488: el fichero de 244 bytes de AYER fue pisado por el de hoy
$ ls app.log.*
app.log.1"""),
            ("assistant", r"""Confirmado: `wc -c app.log.1` tras la rotación da 488 — el de 244 de ayer desapareció pisado por `mv`. Causa raíz: rotación sin desplazamiento de generaciones. Corrección con retención de 3 generaciones y archivo determinista:
```bash
#!/usr/bin/env bash
set -euo pipefail
log=app.log
max_bytes=200
size=$(wc -c < "$log")
if (( size <= max_bytes )); then
  echo "sin rotación: $size bytes <= $max_bytes"
  exit 0
fi
echo "rotación: $log $size bytes > $max_bytes umbral"
if [[ -f "$log.1" ]]; then
  mv "$log.1" "$log.2"
  echo "generación: $log.1 -> $log.2 ($(wc -c < "$log.2") bytes preservados)"
fi
mv "$log" "$log.1"
echo "generación: $log -> $log.1"
: > "$log"
archivar() {
  local destino=$1
  tar --sort=name --owner=0 --group=0 --numeric-owner --mtime='@1710460800' \
      -cf - "$log.1" "$log.2" | gzip -n > "$destino"
}
archivar logs_archivo.tar.gz
archivar logs_verificacion.tar.gz
if cmp -s logs_archivo.tar.gz logs_verificacion.tar.gz; then
  echo "determinismo: dos pasadas de archivo byte a byte idénticas"
else
  echo "determinismo: FALLO, los archivos difieren" >&2
  exit 1
fi
rm -f logs_verificacion.tar.gz
echo "archivo: logs_archivo.tar.gz ($(tar -tzf logs_archivo.tar.gz | wc -l) ficheros)"
tar -tzf logs_archivo.tar.gz
```
Decisiones: el desplazamiento va en orden INVERSO (primero .1→.2, después actual→.1): al revés pisarías igual; el wc del fichero desplazado deja constancia de los bytes preservados; el tar es determinista por construcción — `--sort=name` (orden fijo), `--owner=0 --group=0 --numeric-owner` (sin usuarios del runner), `--mtime='@1710460800'` (fecha fija) y `gzip -n` (cabecera gzip sin timestamp ni nombre) — y el script lo DEMUESTRA: archiva dos veces y compara con `cmp`; si alguien elimina un flag mañana, el determinismo se rompe y el test lo canta. Verificado: 488>200 dispara la rotación, ayer (244) preservado en .2, archivo con 2 ficheros y determinismo probado en la misma ejecución; por debajo del umbral no toca nada."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "bug_pisa_generacion_anterior", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [
                 {"name": "app.log", "content": r"""2024-03-15 09:00:01 INFO servicio activo con datos de prueba
2024-03-15 09:00:02 INFO servicio activo con datos de prueba
2024-03-15 09:00:03 INFO servicio activo con datos de prueba
2024-03-15 09:00:04 INFO servicio activo con datos de prueba
2024-03-15 09:00:05 INFO servicio activo con datos de prueba
2024-03-15 09:00:06 INFO servicio activo con datos de prueba
2024-03-15 09:00:07 INFO servicio activo con datos de prueba
2024-03-15 09:00:08 INFO servicio activo con datos de prueba
"""},
                 {"name": "app.log.1", "content": r"""2024-03-14 09:00:01 INFO servicio activo con datos de prueba
2024-03-14 09:00:02 INFO servicio activo con datos de prueba
2024-03-14 09:00:03 INFO servicio activo con datos de prueba
2024-03-14 09:00:04 INFO servicio activo con datos de prueba
"""},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["rotado", "488 app.log.1"],
             "expect_stdout_not_contains": ["244 app.log.1"]},
            {"name": "fix_preserva_y_archiva_determinista", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "app.log", "content": r"""2024-03-15 09:00:01 INFO servicio activo con datos de prueba
2024-03-15 09:00:02 INFO servicio activo con datos de prueba
2024-03-15 09:00:03 INFO servicio activo con datos de prueba
2024-03-15 09:00:04 INFO servicio activo con datos de prueba
2024-03-15 09:00:05 INFO servicio activo con datos de prueba
2024-03-15 09:00:06 INFO servicio activo con datos de prueba
2024-03-15 09:00:07 INFO servicio activo con datos de prueba
2024-03-15 09:00:08 INFO servicio activo con datos de prueba
"""},
                 {"name": "app.log.1", "content": r"""2024-03-14 09:00:01 INFO servicio activo con datos de prueba
2024-03-14 09:00:02 INFO servicio activo con datos de prueba
2024-03-14 09:00:03 INFO servicio activo con datos de prueba
2024-03-14 09:00:04 INFO servicio activo con datos de prueba
"""},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["rotación: app.log 488 bytes > 200 umbral",
                                        "generación: app.log.1 -> app.log.2 (244 bytes preservados)",
                                        "generación: app.log -> app.log.1",
                                        "determinismo: dos pasadas de archivo byte a byte idénticas",
                                        "archivo: logs_archivo.tar.gz (2 ficheros)",
                                        "app.log.2"]},
            {"name": "debajo_del_umbral_no_rota", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "app.log", "content": "2024-03-15 09:00:01 INFO servicio activo con datos de prueba\n2024-03-15 09:00:02 INFO servicio activo con datos de prueba\n"}],
             "expect_exit": 0,
             "expect_stdout_contains": ["sin rotación: 122 bytes <= 200"]},
        ],
        tags=["rotacion", "mv", "tar", "determinismo", "retencion"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B08
    E(
        language="bash", domain="data", subdomain="dedupe_una_pasada",
        difficulty="hard", task_type="debugging",
        messages=[
            ("user", r"""El flujo de eventos tiene entrega at-least-once: algunos eventos llegan DUPLICADOS (reintentos del productor) y un escritor defectuoso añade espacios al final de algunas líneas. Preparo el informe de eventos únicos con:
```bash
#!/usr/bin/env bash
set -euo pipefail
in=${1:?uso: eventos_dedup.sh EVENTOS_LOG}
sort -u "$in" > limpio.log
echo "dedupe: $(wc -l < "$in") -> $(wc -l < limpio.log)"
cat limpio.log
```
Dos quejas del cliente: el informe sale DESORDENADO (exige el orden cronológico del fichero original) y sigue habiendo eventos fantasma. Fichero de hoy, 4 líneas (la última termina en espacio): evento=login usuario=ana; evento=login usuario=ana; evento=compra usuario=ana; y evento=login usuario=ana con un espacio final."""),
            ("assistant", r"""Dos fallas distintas del mismo comando. (1) `sort -u` ORDENA: el informe sale reordenado por collation, no por llegada — el orden cronológico muere. (2) `sort -u` deduplica por igualdad EXACTA de línea: `evento=login usuario=ana` y la variante con espacio final son DOS claves distintas y ambas sobreviven — por eso el fantasma. Además el patrón es ineficiente para ficheros grandes: sort es O(n log n) con temporales en disco, cuando la deduplicación por primera aparición es O(n) streaming. Experimento: contar lo que deja sort -u y ver el fantasma con `cat -A` (que marca el fin de línea con $)."""),
            ("tool", r"""$ bash eventos_dedup.sh eventos.log; echo "rc=$?"
dedupe: 4 -> 3
evento=compra usuario=ana
evento=login usuario=ana
evento=login usuario=ana
$ cat -A eventos.log | tail -1
evento=login usuario=ana $
$ # cat -A confirma el espacio final: la 3ª línea del informe es el fantasma,
$ # y 'compra' ha adelantado a 'login' en el orden de salida"""),
            ("assistant", r"""Confirmado: 4→3 con fantasma dentro y orden reordenado. Causa raíz: usar sort -u (reordena e igualdad exacta) para un problema de primera-aparición con normalización. Corrección: awk de UNA pasada que recorta espacios/tabuladores finales y emite cada línea normalizada solo la primera vez:
```bash
#!/usr/bin/env bash
set -euo pipefail
in=${1:?uso: eventos_dedup.sh EVENTOS_LOG}
total=$(wc -l < "$in")
LC_ALL=C awk '{ sub(/[ \t]+$/, ""); if (!visto[$0]++) print }' "$in" > limpio.log
kept=$(wc -l < limpio.log)
echo "dedupe: $total -> $kept (eliminados $((total-kept)))"
cat limpio.log
```
Decisiones: `sub(/[ \t]+$/, "")` normaliza EN EL MOMENTO de leer, así la clave de `visto` es la línea limpia y el fantasma muere; el idioma `!visto[$0]++` imprime en la PRIMERA aparición (la comparación ocurre antes del incremento) y conserva el orden de entrada sin ordenar nada — O(n), sin temporales, streaming puro: escala igual de bien a ficheros de gigas; el recorte es solo del extremo derecho, no toca espacios internos de los datos. Por qué no `awk '!visto[$0]++'` a secas: sin normalización, el fantasma con espacio seguiría vivo. Verificado: 4→2 (eliminados 2), orden cronológico intacto y ninguna línea con espacio residual."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "bug_fantasma_y_desorden", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [{"name": "eventos.log", "content": "evento=login usuario=ana\nevento=login usuario=ana\nevento=compra usuario=ana\nevento=login usuario=ana \n"}],
             "args": ["eventos.log"], "expect_exit": 0,
             "expect_stdout_contains": ["dedupe: 4 -> 3", "evento=login usuario=ana "]},
            {"name": "fix_orden_y_sin_fantasma", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [{"name": "eventos.log", "content": "evento=login usuario=ana\nevento=login usuario=ana\nevento=compra usuario=ana\nevento=login usuario=ana \n"}],
             "args": ["eventos.log"], "expect_exit": 0,
             "expect_stdout_contains": ["dedupe: 4 -> 2 (eliminados 2)",
                                        "evento=login usuario=ana",
                                        "evento=compra usuario=ana"],
             "expect_stdout_not_contains": ["usuario=ana "]},
        ],
        tags=["awk", "dedupe", "una_pasada", "normalizacion"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ B09
    E(
        language="bash", domain="data", subdomain="fusion_csv_cabecera",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", r"""El data warehouse rechaza el ingest trimestral: le mando la concatenación de los CSV mensuales y aparece la CABECERA repetida tres veces, que ingiere como filas de datos. Necesito un fusionador para `ventas_enero.csv`, `ventas_febrero.csv` y `ventas_marzo.csv` (mismo esquema `fecha,region,importe`) que: (1) escriba la cabecera UNA sola vez; (2) VERIFIQUE que los tres ficheros comparten exactamente la misma cabecera (si divergen, abortar con código distinto); (3) valide que cada fila tiene el mismo número de campos que la cabecera; y (4) resuma lo fusionado. Nada de colas de paquete ni pandas: bash puro, ficheros pequeños."""),
            ("assistant", r"""Plan: dos comprobaciones en seco ANTES de escribir nada (cabeceras idénticas entre ficheros; número de campos por fila), después la fusión y el resumen — así el fichero de salida nunca queda a medias con datos rechazables. Para la fusión, `awk 'FNR==1{next}'` sobre la lista de ficheros: FNR se reinicia por fichero, así que salta la primera línea de CADA uno; la cabecera única la emite el propio script con `echo`. Los códigos de fallo separan causas: 2 = falta fichero, 3 = cabecera divergente, 4 = fila con campos inconsistentes — el orquestador puede diagnosticar sin abrir el log."""),
            ("tool", r"""$ bash fusiona.sh
fusión: 3 ficheros, 8 filas, cabecera común verificada (3 campos)
2024-03-05,sur,1500
2024-03-12,este,210
2024-03-29,norte,890
$ head -5 ventas_fusionadas.csv
fecha,region,importe
2024-01-03,norte,1200
2024-01-17,sur,450
2024-01-28,este,980
2024-02-02,norte,640"""),
            ("assistant", r"""Implementación:
```bash
#!/usr/bin/env bash
set -euo pipefail
out=ventas_fusionadas.csv
ficheros=()
for mes in enero febrero marzo; do
  f="ventas_$mes.csv"
  [[ -f $f ]] || { echo "error: falta $f" >&2; exit 2; }
  ficheros+=("$f")
done
cabecera=$(head -n1 "${ficheros[0]}")
nf_cab=$(LC_ALL=C awk -F, 'NR==1{print NF; exit}' "${ficheros[0]}")
for f in "${ficheros[@]}"; do
  if [[ $(head -n1 "$f") != "$cabecera" ]]; then
    echo "error: cabecera divergente en $f" >&2
    exit 3
  fi
done
if ! LC_ALL=C awk -F, -v esperado="$nf_cab" '
  FNR > 1 && NF != esperado {
    printf "error: %s línea %d tiene %d campos (esperados %d)\n", FILENAME, FNR, NF, esperado
    malo=1
  }
  END { exit malo ? 1 : 0 }' "${ficheros[@]}"; then
  echo "error: filas inconsistentes, abortando" >&2
  exit 4
fi
{
  echo "$cabecera"
  LC_ALL=C awk 'FNR==1{next} {print}' "${ficheros[@]}"
} > "$out"
filas=$(( $(wc -l < "$out") - 1 ))
echo "fusión: ${#ficheros[@]} ficheros, $filas filas, cabecera común verificada ($nf_cab campos)"
tail -n 3 "$out"
```
Decisiones: `FNR==1{next}` salta la cabecera de CADA fichero (NR no valdría: no se reinicia) — por eso la cabecera sale una única vez sin grep -v frágiles; la comparación de cabeceras es EXACTA (incluye orden de columnas: `region,fecha` contaría como divergente, que es lo querido); la validación de campos usa `FNR > 1` para no marcar la propia cabecera y reporta fichero:línea exacto del defecto; el bloque `{ echo; awk; } > "$out"` escribe la salida de una vez; y `tail -n 3` deja a la vista el final de la fusión como evidencia. Verificado: 3 ficheros, 8 filas (3+2+3), cabecera única, y con una cabecera alterada en marzo el script aborta con 3 nombrando el fichero."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "fusion_correcta", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "ventas_enero.csv", "content": "fecha,region,importe\n2024-01-03,norte,1200\n2024-01-17,sur,450\n2024-01-28,este,980\n"},
                 {"name": "ventas_febrero.csv", "content": "fecha,region,importe\n2024-02-02,norte,640\n2024-02-21,oeste,730\n"},
                 {"name": "ventas_marzo.csv", "content": "fecha,region,importe\n2024-03-05,sur,1500\n2024-03-12,este,210\n2024-03-29,norte,890\n"},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["fusión: 3 ficheros, 8 filas, cabecera común verificada (3 campos)",
                                        "2024-03-05,sur,1500",
                                        "2024-03-29,norte,890"]},
            {"name": "cabecera_divergente_aborta", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "ventas_enero.csv", "content": "fecha,region,importe\n2024-01-03,norte,1200\n"},
                 {"name": "ventas_febrero.csv", "content": "fecha,region,importe\n2024-02-02,norte,640\n"},
                 {"name": "ventas_marzo.csv", "content": "fecha,region,importe,moneda\n2024-03-05,sur,1500,eur\n"},
             ],
             "expect_exit": 3,
             "expect_stdout_contains": ["cabecera divergente en ventas_marzo.csv"]},
        ],
        tags=["csv", "fusion", "awk", "validacion"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B10
    E(
        language="bash", domain="systems", subdomain="trap_err_localizacion",
        difficulty="hard", task_type="analysis",
        messages=[
            ("user", r"""Un script de despliegue muere a veces con exit 2 sin más contexto, y solo ocurre en producción; no puedo iterar a ciegas. Quiero instrumentalizarlo para que CUALQUIER fallo no controlado reporte: código, LÍNEA exacta, función donde ocurrió y el COMANDO que falló. Además me han hablado de `bash -x` con PS4 para trazado paso a paso: quiero ver cómo se combinan ambas cosas. Recuerda que el script usa `set -e`, y que hay sondas legítimas con `grep -q`/`[[ ]]` que devuelven distinto de cero SIN ser errores."""),
            ("assistant", r"""Diseño del manejador: `trap ... ERR` con `set -E` (errtrace) para que el trap se herede dentro de funciones. Dentro del manejador, `$?` (capturado PRIMERO) da el código; `$LINENO` da la línea del comando que falló; `FUNCNAME[0]` da el marco donde ocurrió (dentro de una función devuelve su nombre; en el nivel superior, main); y `$BASH_COMMAND` es exactamente el comando que estaba ejecutándose — oro puro para el diagnóstico. Sobre las sondas legítimas: el ERR trap NO se dispara cuando el comando falla en CONTEXTO DE CONDICIÓN (`if comando`, `comando && ...`, `while comando`), que es justo donde viven los grep -q sondeadores: el diseño no necesita `|| true` defensivos. La distinción clave: contexto de condición = sondeo; fuera de él = fallo real que el trap reporta."""),
            ("tool", r"""$ bash traza_err.sh; echo "rc=$?"
aviso: pasos.md ausente (controlado: el trap no actúa en contextos de condición)
fase 1 correcta
ls: cannot access 'documento_ausente.txt': No such file or directory
ERR: rc=2, línea 9, en procesa: ls documento_ausente.txt
rc=2
$ # trazado paso a paso del mismo script con PS4:
$ PS4='+ traza ${BASH_SOURCE}:${LINENO}: ' bash -x traza_err.sh 2>&1 | grep 'traza'
+ traza traza_err.sh:8: echo 'fase 1 correcta'
+ traza traza_err.sh:9: ls documento_ausente.txt"""),
            ("assistant", r"""Instrumentalización:
```bash
#!/usr/bin/env bash
set -Eeuo pipefail
trap 'rc=$?
  echo "ERR: rc=$rc, línea $LINENO, en ${FUNCNAME[0]:-main}: $BASH_COMMAND" >&2
  exit "$rc"' ERR
existe() { [[ -f $1 ]]; }
procesa() {
  echo "fase 1 correcta"
  ls documento_ausente.txt
}
if ! existe pasos.md; then
  echo "aviso: pasos.md ausente (controlado: el trap no actúa en contextos de condición)" >&2
fi
procesa
echo "nunca se imprime"
```
Lectura del resultado: la sonda `if ! existe pasos.md` falla sin disparar el trap (contexto de condición: es una pregunta, no un error) y el flujo continúa; el `ls` falla FUERA de condición → trap → reporte con rc 2, línea 9 (el `ls` dentro de procesa), marco `procesa` y el comando literal — y `set -e` remata con exit 2, conservando el código semántico. El xtrace con `PS4='+ traza ${BASH_SOURCE}:${LINENO}: '` complementa al trap: muestra CADA comando expandido con su línea (8 y 9), útil cuando el fallo depende de valores, no solo de ubicación. Reglas para producción: el manejador captura `$?` primero (cualquier comando intermedio lo pisaría), termina con `exit "$rc"` para no enmascarar el código, y reporta a stderr. Verificado: sonda controlada sin falsa alarma, fallo real localizado con línea+función+comando, y trazado PS4 coherente."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "fallo_localizado", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "expect_exit": 2,
             "expect_stdout_contains": ["aviso: pasos.md ausente (controlado: el trap no actúa en contextos de condición)",
                                        "fase 1 correcta",
                                        "ERR: rc=2",
                                        ": ls documento_ausente.txt"],
             "expect_stdout_not_contains": ["nunca se imprime"]},
        ],
        tags=["trap", "err", "ps4", "xtrace", "diagnostico"], stack=["bash"],
    ),

    # ------------------------------------------------------------------ B11
    E(
        language="bash", domain="scripting_automation", subdomain="checkpoint_efecto_primero",
        difficulty="extreme", task_type="debugging",
        messages=[
            ("user", r"""El publicador de lotes tiene un bug que ya costó un ticket: anoche el proceso murió a mitad y, tras relanzarlo, la tarea 3 nunca se ejecutó, aunque el checkpoint decía lo contrario. Versión instrumentada que reproduce lo de anoche (la línea del crash inyectado es nueva, lo demás es el código de producción):
```bash
#!/usr/bin/env bash
set -euo pipefail
if [[ -f progreso.txt ]]; then hecho=$(<progreso.txt); else hecho=0; fi
i=0
while IFS= read -r tarea; do
  i=$((i+1))
  (( i <= hecho )) && continue
  echo "$i" > progreso.txt
  if [[ -f inyectar_fallo && $i == 3 ]]; then
    echo "crash simulado en la tarea $i" >&2
    exit 1
  fi
  printf 'hecho: %s\n' "$tarea" >> resultados.log
  echo "hecho: $tarea"
done < lote.txt
echo "fin: $i tareas"
```
Lote: tarea-a..tarea-d. Quiero entender la pérdida Y un rediseño donde un crash en cualquier punto NO pierda ni duplique efectos."""),
            ("assistant", r"""Síntoma: checkpoint dice 3 (hecho hasta la 3) pero el efecto de la tarea 3 no existe. Hipótesis: el orden de las operaciones. En el script, la MARCA (`echo "$i" > progreso.txt`) se escribe ANTES del EFECTO (`printf ... >> resultados.log`): si el proceso muere entre ambas — exactamente la ventana que hoy simulamos con la bandera — el relanzamiento salta la tarea creyéndola hecha y el efecto se pierde para siempre. Experimento: reproducir la secuencia completa con la banda inyectada y auditar resultados.log. El rediseño correcto invierte el orden (EFECTO primero, marca después) y exige que el efecto sea IDEMPOTENTE (sobrescribir en vez de anexar): así un crash entre efecto y marca provoca re-procesamiento, nunca pérdida ni duplicado. Además sustituyo el contador único por marcas atómicas por tarea (tmp+mv), que permiten reanudar sin asumir orden."""),
            ("tool", r"""$ bash publica_v1.sh; echo "rc=$?"      # 1ª pasada: crash inyectado en la 3ª
hecho: tarea-a
hecho: tarea-b
crash simulado en la tarea 3
rc=1
$ rm inyectar_fallo && bash publica_v1.sh   # relanzamiento del operador
hecho: tarea-d
fin: 4 tareas
$ cat resultados.log
hecho: tarea-a
hecho: tarea-b
hecho: tarea-d
$ grep -c 'tarea-c' resultados.log; echo "rc=$?"
0
rc=1"""),
            ("assistant", r"""Confirmado: `progreso.txt` quedó en 3 y tarea-c NO está en resultados.log — el checkpoint mintió porque se escribió antes del efecto. Rediseño (efecto → crash-window → marca atómica), con la prueba de crash+reanudación integrada:
```bash
#!/usr/bin/env bash
set -euo pipefail
procesa_lote() {
  local tarea
  while IFS= read -r tarea; do
    if [[ -f "marcas/$tarea.ok" ]]; then
      echo "omitido (ya hecho): $tarea"
      continue
    fi
    # 1) EFECTO primero, idempotente (sobrescribe, no anexa)
    printf 'resultado de %s\n' "$tarea" > "salidas/$tarea.txt"
    # 2) ventana de crash: muere DESPUÉS del efecto, ANTES de la marca
    if [[ -f inyectar_fallo && $tarea == tarea-c ]]; then
      echo "crash simulado tras el efecto de tarea-c (aún sin marca)" >&2
      exit 1
    fi
    # 3) marca atómica: temporal + mv
    : > "marcas/$tarea.ok.tmp"
    mv "marcas/$tarea.ok.tmp" "marcas/$tarea.ok"
    echo "procesado: $tarea"
  done < lote.txt
}
mkdir -p marcas salidas
if [[ -f inyectar_fallo ]]; then
  if ( procesa_lote ); then
    echo "error: se esperaba el crash simulado" >&2
    exit 1
  fi
  rm -f inyectar_fallo
  echo "reanudado: relanzando tras el crash"
fi
procesa_lote
total=$(wc -l < lote.txt)
marcas_n=$(find marcas -name '*.ok' | wc -l)
salidas_n=$(find salidas -type f | wc -l)
tmp_n=$(find marcas -name '*.tmp' | wc -l)
echo "cobertura: $marcas_n/$total con marca, $salidas_n salidas, $tmp_n temporales"
if (( marcas_n != total || salidas_n != total || tmp_n != 0 )); then
  echo "error: cobertura inconsistente" >&2
  exit 1
fi
echo "verificado: efecto único por tarea y marcas atómicas"
```
Decisiones: orden «efecto → marca» con efecto IDEMPOTENTE (sobrescribir `salidas/$tarea.txt`) convierte el re-procesamiento tras crash en inofensivo: si muere tras el efecto, al reanudar la rehace y sobrescribe el mismo resultado — exactamente-once EFECTO con at-least-once EJECUCIÓN; la marca por TAREA (fichero .ok) sustituye al contador único y la escritura `tmp + mv` es atómica: jamás existe una marca a medias; el crash se inyecta en la MISMA ventana que antes (tras el efecto, antes de la marca) para comparar manzanas con manzanas; y la verificación final cruza marcas, salidas y residuos .tmp. Verificado: crash en tarea-c → reanudación la REPROCESA, 4/4 con marca, 4 salidas, 0 temporales, sin duplicados posibles por construcción."""),
        ],
        verify=[
            {"name": "sintaxis", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "bug_pierde_tarea", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [
                 {"name": "lote.txt", "content": "tarea-a\ntarea-b\ntarea-c\ntarea-d\n"},
                 {"name": "inyectar_fallo", "content": "\n"},
             ],
             "expect_fail": True,
             "expect_stdout_contains": ["crash simulado en la tarea 3"]},
            {"name": "fix_reprocesa_sin_perder", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "lote.txt", "content": "tarea-a\ntarea-b\ntarea-c\ntarea-d\n"},
                 {"name": "inyectar_fallo", "content": "\n"},
             ],
             "timeout_s": 20,
             "expect_exit": 0,
             "expect_stdout_contains": ["procesado: tarea-a",
                                        "procesado: tarea-b",
                                        "crash simulado tras el efecto de tarea-c (aún sin marca)",
                                        "reanudado: relanzando tras el crash",
                                        "omitido (ya hecho): tarea-a",
                                        "procesado: tarea-c",
                                        "procesado: tarea-d",
                                        "cobertura: 4/4 con marca, 4 salidas, 0 temporales",
                                        "verificado: efecto único por tarea y marcas atómicas"]},
        ],
        tags=["checkpoint", "idempotencia", "atomicidad", "reanudacion"], stack=["bash"], recovery=True,
    ),

    # ------------------------------------------------------------------ S12
    E(
        language="ssh", domain="systems", subdomain="ssh_config_razonado",
        difficulty="hard", task_type="documentation",
        messages=[
            ("user", r"""Mi ~/.ssh/config es un zoo de alias inconsistentes y siempre escribo `ssh -i ... usuario@...` a mano. Situación: un bastión (`bastion.corp.example`, usuario `ops`, clave específica) y tres servidores internos SOLO alcanzables a través de él (web01 10.20.0.11, web02 10.20.0.12, db01 10.20.0.13; usuario `deploy`, otra clave). Quiero: aliases cortos, el salto por el bastión declarado en la config (no con -J cada vez), clave correcta por grupo de hosts sin depender del agente, y valores por defecto prudentes (detección de conexiones muertas, no acumular claves probadas). Explícame DIRECTIVA A DIRECTIVA qué hace cada línea y cómo validar el resultado SIN abrir ninguna conexión."""),
            ("assistant", r"""Estructura razonada de un config ssh: los bloques `Host` se evalúan EN ORDEN y el PRIMER valor obtenido para cada opción gana, por eso los bloques específicos van ANTES que `Host *`. El salto se declara con `ProxyJump` (opción moderna, equivalente a `-J`: abre el TCP del destino A TRAVÉS del bastión sin exponer rutas). `IdentityFile` + `IdentitiesOnly yes` es el par clave: la primera elige fichero, la segunda impide que el agente ofrezca OTRAS claves primero — evita el clásico «Too many authentication failures» cuando el agente tiene media docena. `ServerAliveInterval`/`ServerAliveCountMax` detectan conexiones medio muertas (nada que ver con TCPKeepAlive, que solo ve TCP vivo, no la sesión). `HashKnownHosts` ofusca los hosts en known_hosts. El bloque escribe el fichero con permisos 600 — sin eso, ssh avisa y algunos entornos lo rechazan."""),
            ("tool", r"""$ bash -n escribe_config.sh && echo "sintaxis ok"
sintaxis ok"""),
            ("assistant", r"""El bloque (solo escribe el fichero local: NO se conecta a nada):
```bash
#!/usr/bin/env bash
# escribe ~/.ssh/config razonado; no abre ninguna conexión
mkdir -p ~/.ssh
chmod 700 ~/.ssh
cat > ~/.ssh/config <<'EOF'
# Anfitrión de salto: puerta de entrada a la red interna
Host bastion
    HostName bastion.corp.example
    User ops
    IdentityFile ~/.ssh/id_ed25519_bastion
    IdentitiesOnly yes

# Internos: solo alcanzables A TRAVÉS del bastión (TCP reenviado por SSH)
Host web01 web02 db01
    User deploy
    ProxyJump bastion
    IdentityFile ~/.ssh/id_ed25519_deploy
    IdentitiesOnly yes

Host web01
    HostName 10.20.0.11
Host web02
    HostName 10.20.0.12
Host db01
    HostName 10.20.0.13

# Valores por defecto prudentes para TODO lo demás
Host *
    ServerAliveInterval 60
    ServerAliveCountMax 3
    TCPKeepAlive no
    AddKeysToAgent yes
    HashKnownHosts yes
EOF
chmod 600 ~/.ssh/config
```
Directiva a directiva: `HostName` — la dirección real tras el alias (`ssh web01` resuelve a 10.20.0.11); `User` — usuario por defecto para ese bloque (ya no hace falta `deploy@`); `ProxyJump bastion` — el salto: ssh abre una conexión al bastión y POR ELLA tuneliza el TCP hacia el interno, cifrado extremo a extremo desde tu máquina; `IdentityFile` — qué clave privada probar; `IdentitiesOnly yes` — probar SOLO esa clave aunque el agente ofrezca más (evita agotar intentos del servidor); `ServerAliveInterval 60` + `ServerAliveCountMax 3` — cada 60s un sondeo de aplicación; 3 sin respuesta → conexión dada por muerta; `TCPKeepAlive no` — no fiarse de los keepalives TCP (pueden «vivir» tras un NAT que ya perdió la sesión); `AddKeysToAgent yes` — al usar una clave, cargarla en el agente; `HashKnownHosts yes` — nombres ofuscados en known_hosts. CÓMO SE COMPROBARÍA sin conectar (todo local): `ssh -G web01` vuelca la config RESUELTA para ese alias — ahí verificas `user deploy`, `hostname 10.20.0.11`, `proxyjump bastion` e `identityfile`; `stat -c %a ~/.ssh/config` debe dar 600; `ssh-keygen -l -f ~/.ssh/id_ed25519_deploy` confirma que la clave existe y es legible; y `ssh -v web01 exit` (cuando toca conectar de verdad) muestra qué config y claves usa en el handshake. Aquí no he ejecutado ninguna de esas conexiones: solo la sintaxis del bloque y la escritura local están verificadas."""),
        ],
        verify=[
            {"name": "sintaxis_del_bloque", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
        ],
        tags=["ssh_config", "proxyjump", "identityfile", "hardening_dosificacion"], stack=["bash", "ssh"],
    ),

    # ------------------------------------------------------------------ S13
    E(
        language="ssh", domain="security", subdomain="authorized_keys_permisos",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", r"""Mi clave pública deja de funcionar en el servidor laboratorio cada cierto tiempo: `ssh -v` acaba en «Permission denied (publickey)» con la clave OFRECIDA y aceptada en intentos previos. El administrador dice que la clave sigue en authorized_keys y que no toca sshd_config. Sospecho de los permisos porque un compañero hizo `chmod -R 777 ~` para «arreglar» un script. Necesito: (1) el razonamiento de POR QUÉ sshd puede rechazar una clave válida por permisos, (2) la lista exacta de condiciones que exige sshd, y (3) un verificador/corrector que pueda ejecutar AQUÍ MISMO (sin servidor) sobre un $HOME de laboratorio para demostrar el antes y el después."""),
            ("assistant", r"""El razonamiento: con `StrictModes yes` (el DEFAULT de OpenSSH), sshd comprueba la propiedad y los permisos de tu home, de `~/.ssh` y de `~/.ssh/authorized_keys` ANTES de aceptar la clave; si algo es escribible por grupo/otros (o el propietario no cuadra), sshd ASUME que un tercero podría haber manipulado el fichero y se niega a usarlo. El síntoma en el cliente es tramposo: la clave se ofrece y el servidor la rechaza en silencio — la razón real solo aparece en el log del SERVIDOR (`/var/log/auth.log`: «Authentication refused: bad ownership or modes for file ...»). Condiciones que exige sshd: (a) home NO escribible por grupo/otros; (b) `~/.ssh` con 700 y propietario correcto; (c) `authorized_keys` con 600 y propietario correcto; (d) ficheros no enlazados a sitios raros (no hay symlink jugando). El verificador de abajo opera en un `labhome/` local con permisos mal inducidos a propósito: nada toca tu home real."""),
            ("tool", r"""$ bash doctor_claves.sh laboratorio
laboratorio: induzco permisos incorrectos (755 en .ssh, 644 en authorized_keys)
corregido: labhome/.ssh 755 -> 700
corregido: authorized_keys 644 -> 600
ok: propietario correcto (ops)
claves: 1 línea(s) con formato de clave pública válida
estado final: conforme con StrictModes (700 en labhome/.ssh, 600 en authorized_keys)
$ stat -c '%a %n' labhome/.ssh labhome/.ssh/authorized_keys
700 labhome/.ssh
600 labhome/.ssh/authorized_keys"""),
            ("assistant", r"""El verificador/corrector (100% local sobre `labhome/`):
```bash
#!/usr/bin/env bash
set -euo pipefail
# doctor_claves.sh — diagnostica y corrige lo que sshd (StrictModes) exige
# sobre ~/.ssh y authorized_keys. Modo "laboratorio": monta un $HOME de
# prueba con permisos incorrectos para demostrar el antes y el después.
if [[ ${1:-} == laboratorio ]]; then
  mkdir -p labhome/.ssh
  printf '%s\n' 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAbcdefghij1234567890abcdefghijclave-demo ops@lab' > labhome/.ssh/authorized_keys
  chmod 755 labhome/.ssh
  chmod 644 labhome/.ssh/authorized_keys
  echo "laboratorio: induzco permisos incorrectos (755 en .ssh, 644 en authorized_keys)"
  set -- labhome
fi
raiz=${1:-$HOME}
dir_ssh="$raiz/.ssh"
ak="$dir_ssh/authorized_keys"
if [[ ! -f $ak ]]; then
  echo "error: no existe $ak" >&2
  exit 2
fi
p_dir=$(stat -c %a "$dir_ssh")
p_ak=$(stat -c %a "$ak")
if [[ $p_dir == 700 ]]; then
  echo "ok: $dir_ssh con permisos $p_dir"
else
  chmod 700 "$dir_ssh"
  echo "corregido: $dir_ssh $p_dir -> 700"
fi
if [[ $p_ak == 600 ]]; then
  echo "ok: authorized_keys con permisos $p_ak"
else
  chmod 600 "$ak"
  echo "corregido: authorized_keys $p_ak -> 600"
fi
if [[ $(stat -c %u "$dir_ssh") == "$(id -u)" && $(stat -c %u "$ak") == "$(id -u)" ]]; then
  echo "ok: propietario correcto ($(id -un))"
else
  echo "atención: propietario distinto del usuario actual (chown manual necesario)" >&2
fi
claves=$(grep -cE '^(ssh-(ed25519|rsa)|ecdsa-sha2-[a-z0-9-]+) AAAA[0-9A-Za-z+/=]+' "$ak" || true)
echo "claves: $claves línea(s) con formato de clave pública válida"
echo "estado final: conforme con StrictModes (700 en $dir_ssh, 600 en authorized_keys)"
```
Qué hace y por qué: verifica EXACTAMENTE las dos condiciones que sshd endurece (700 en `.ssh`, 600 en authorized_keys), corrige con chmod si difieren, comprueba propietario con `stat -c %u` contra `id -u` (en el servidor, un UID distinto tras un restore es causa clásica) y valida que cada línea sea una clave pública con formato reconocible (tipo + blob base64) — una línea corrupta en authorized_keys también cuelga la autenticación. En el SERVIDOR real el diagnóstico se completaría con: `sudo tail /var/log/auth.log | grep -i 'bad ownership\|refused'` tras un intento fallido, y del lado cliente `ssh -vvv usuario@host` muestra «Server refuses our key». Nada de esto se ha ejecutado contra un servidor aquí: la demo corre sobre `labhome/`, local y verificable."""),
        ],
        verify=[
            {"name": "sintaxis_del_bloque", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
            {"name": "doctor_corrige_laboratorio", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "args": ["laboratorio"], "expect_exit": 0,
             "expect_stdout_contains": ["laboratorio: induzco permisos incorrectos (755 en .ssh, 644 en authorized_keys)",
                                        "corregido: labhome/.ssh 755 -> 700",
                                        "corregido: authorized_keys 644 -> 600",
                                        "claves: 1 línea(s) con formato de clave pública válida",
                                        "estado final: conforme con StrictModes (700 en labhome/.ssh, 600 en authorized_keys)"]},
        ],
        tags=["authorized_keys", "strictmodes", "permisos", "diagnostico"], stack=["bash", "ssh"],
    ),

    # ------------------------------------------------------------------ S14
    E(
        language="ssh", domain="systems", subdomain="tuneles_ssh_l_r",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", r"""Dos necesidades reales de acceso legítimo a MI infraestructura: (1) desde mi portátil quiero hablar con el Postgres de producción (`db-prod.internal:5432`), que solo es alcanzable desde el bastión — me han dicho que use un túnel SSH `-L`, pero no entiendo quién escucha dónde; (2) al revés: quiero que un compañero alcance mi servidor de desarrollo local (puerto 3000) a través de nuestro relay público, y creo que eso es `-R`. Explica la TOPOLOGÍA de cada uno (quién escucha, quién conecta), las opciones que evitan túneles zombis, y cómo se comprobaría el funcionamiento sin afirmar que aquí se abre nada."""),
            ("assistant", r"""La confusión clásica se disuelve fijando el PUNTO DE ESCUCHA. Con `-L bind_local:destino` el LISTENER nace en tu máquina: lo que llegue al puerto local viaja por el SSH hasta el servidor remoto y desde allí se abre TCP hacia el destino — el destino lo alcanza el SERVIDOR SSH, no tú (por eso db-prod.internal es alcanzable: el bastión está en su red). Con `-R bind_remoto:destino` el listener nace en el REMOTO: tu servidor sshd remoto publica el puerto y, cuando alguien conecta, el tráfico vuelve POR TU túnel hacia el destino que TÚ alcanzas desde tu máquina. Opciones anti-zombi: `-N` (no ejecutar comando remoto: solo túnel), `-o ExitOnForwardFailure=yes` (si el puerto remoto/local está ocupado, muere en vez de quedarse «vivo» sin túnel), y `-o ServerAliveInterval` para que las conexiones muertas se corten. En `-R`, el bind por defecto escucha solo en loopback del remoto: eso es lo correcto salvo que quieras exponer a terceros (y entonces `GatewayPorts` entra en juego en el servidor sshd remoto)."""),
            ("tool", r"""$ bash -n abre_tuneles.sh && echo "sintaxis ok"
sintaxis ok"""),
            ("assistant", r"""Los dos túneles (el fichero solo DECLARA los comandos: no se abre ninguna conexión aquí):
```bash
#!/usr/bin/env bash
# abre_tuneles.sh — declaraciones de túneles SSH (no se ejecutan en este entorno)

# Túnel LOCAL (-L): escucha en MI portátil, el destino lo alcanza el BASTIÓN
# Topología:  portátil:15432 --SSH--> bastion.corp.example --TCP--> db-prod.internal:5432
ssh -N \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L 15432:db-prod.internal:5432 \
    bastion

# Túnel REMOTO (-R): escucha en el RELAY, el destino lo alcanzo YO desde aquí
# Topología:  colega --> relay.example:8080 --SSH--> portátil:3000
ssh -N \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -R 127.0.0.1:8080:localhost:3000 \
    relay.example
```
Lectura de cada argumento de `-L 15432:db-prod.internal:5432`: `15432` es el puerto local que escucha tu ssh (por eso luego conectas a localhost:15432); `db-prod.internal:5432` es el destino AL QUE CONECTA EL BASTIÓN cuando alguien usa el túnel; `bastion` cierra la tríada (host por el que viaja el SSH). En `-R 127.0.0.1:8080:localhost:3000`: `127.0.0.1:8080` es la interfaz/puerto que PUBLICA el relay (anclado a loopback: solo procesos del propio relay, no internet entero); `localhost:3000` es tu dev server visto DESDE tu portátil; `relay.example` es el extremo SSH. CÓMO SE COMPROBARÍA en tu entorno (no aquí): (1) con el túnel -L arriba, `ss -ltn | grep 15432` muestra el listener local y `psql -h 127.0.0.1 -p 15432 -c 'select 1'` valida el recorrido completo; (2) con el -R arriba, desde el relay `ss -ltn | grep 8080` y desde la máquina del colega `curl -I http://relay.example:8080`; (3) matar el proceso ssh y repetir el ss debe dejar de mostrar el puerto — así se distingue un túnel vivo de un zombi. Aquí solo he verificado la sintaxis del bloque con `bash -n`; ninguna conexión se ha abierto."""),
        ],
        verify=[
            {"name": "sintaxis_del_bloque", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
        ],
        tags=["tuneles", "tunel_local", "tunel_remoto", "topologia"], stack=["bash", "ssh"],
    ),

    # ------------------------------------------------------------------ S15
    E(
        language="ssh", domain="systems", subdomain="backup_rsync_verificado",
        difficulty="very_hard", task_type="automation",
        messages=[
            ("user", r"""Quiero un backup nocturno de `~/proyectos` hacia `backup.corp.example:/backups/portatil` con estas exigencias del equipo de infraestructura: exclusión de residuos (`*.tmp`, `.cache/`, `node_modules/`), preservar permisos y timestamps, que el destino sea RÉPLICA fiel (si algo desapareció del origen, desaparece del backup) pero sin sorpresas, registro de qué cambió, y una verificación de integridad que NO se fíe solo de «rsync dijo ok»: compara hashes de los ficheros respaldados. Dame el script razonado y explica cada flag; aquí no se ejecuta (no hay red ni credenciales), pero quiero saber exactamente cómo se probaría."""),
            ("assistant", r"""Elecciones con justificación: `rsync -a` preserva recursivamente permisos, propietario (en la medida que permita el usuario), timestamps y enlaces — es el mínimo para una réplica fiel; el `/` FINAL del origen es semántico (copia el CONTENIDO de ~/proyectos dentro de /backups/portatil, sin anidar un `proyectos/` — la fuente número uno de backups anidados equivocados). `--delete` cumple «réplica fiel» pero es el flag peligroso: por eso se combina con excludes ESTABLES y se revisa el primer run con `--dry-run`; los excludes sin barra inicial (`*.tmp`) casan a cualquier profundidad y con barra (`node_modules/`) solo directorios. `--itemize-changes` imprime línea por fichero con qué cambió (>f.st = contenido+size+timestamp) y `--stats` el resumen. La verificación por hash: manifiesto `sha256sum` en origen y destino con la MISMA lista de ficheros (mismos excludes, MISMO orden determinista con `sort -z`), y `diff` — si difiere una línea, sabes QUÉ fichero llegó corrupto. Es más caro que el -c de rsync pero auténtico: no compara metadatos, compara contenido."""),
            ("tool", r"""$ bash -n backup_rsync.sh && echo "sintaxis ok"
sintaxis ok"""),
            ("assistant", r"""El script (se ejecutaría en tu máquina contra el servidor de backup; aquí solo se valida su sintaxis):
```bash
#!/usr/bin/env bash
set -euo pipefail
# backup_rsync.sh — réplica con excludes + verificación por manifiesto de hash
destino="backup.corp.example:/backups/portatil"
origen="$HOME/proyectos/"
rsync -a --delete \
      --exclude='*.tmp' \
      --exclude='.cache/' \
      --exclude='node_modules/' \
      --itemize-changes \
      --stats \
      "$origen" "$destino/" | tee /tmp/rsync.log
# verificación de integridad: mismo universo de ficheros en ambos lados
find "$HOME/proyectos" -type f ! -name '*.tmp' ! -path '*/.cache/*' ! -path '*/node_modules/*' -print0 \
  | LC_ALL=C sort -z | xargs -0 sha256sum > /tmp/origen.sha256
ssh backup.corp.example \
  'cd /backups/portatil && find . -type f ! -name "*.tmp" ! -path "*/.cache/*" ! -path "*/node_modules/*" -print0 | LC_ALL=C sort -z | xargs -0 sha256sum' \
  > /tmp/destino.sha256
if diff -u /tmp/origen.sha256 /tmp/destino.sha256; then
  echo "backup verificado: manifiestos de hash idénticos"
else
  echo "backup INCOHERENTE: revisar /tmp/*.sha256" >&2
  exit 1
fi
```
Decisiones y prueba razonada: la primera ejecución real se hace con `--dry-run --itemize-changes` añadido para AUDITAR qué borraría `--delete` antes de permitirlo (regla de oro del equipo: nunca un `--delete` sin dry-run previo); `tee` deja el registro de cambios para el histórico; los dos `find` usan el MISMO criterio de exclusión que rsync para que los manifiestos comparen el mismo universo de ficheros, y `LC_ALL=C sort -z` da el mismo orden en ambas máquinas — sin eso, diff daría falsos positivos por orden; el `diff` falla el script (exit 1) si un solo hash no cuadra. Cómo se probaría de verdad: (1) `bash -n backup_rsync.sh` (hecho aquí, local); (2) dry-run contra el backup real y lectura del itemize; (3) primera copia real + manifiestos idénticos; (4) prueba de destrucción controlada: tocar un fichero del destino, relanzar y comprobar que diff DETECTA la diferencia y el script sale 1 — esa es la prueba de que la verificación verifica. Nada de esto se ha ejecutado aquí: sin red ni credenciales, sería deshonesto afirmarlo."""),
        ],
        verify=[
            {"name": "sintaxis_del_bloque", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
        ],
        tags=["rsync", "backup", "sha256", "excludes"], stack=["bash", "ssh"],
    ),

    # ------------------------------------------------------------------ S16
    E(
        language="ssh", domain="security", subdomain="hardening_sshd",
        difficulty="medium", task_type="implementation",
        messages=[
            ("user", r"""Checklist de endurecimiento para mi servidor laboratorio Debian (acceso propio, sin usuarios externos): desactivar login de root y autenticación por contraseña, dejar solo a mis dos usuarios (`deploy`, `auditar`), cortar reenvíos que no uso y MitM de fuerza bruta con fail2ban (solo concepto y configuración, sin instalar nada aquí). La restricción operativa que me aterra: NO perder la sesión actual ni quedarme fuera si me equivoco. Dame el orden seguro de operaciones y qué hace cada directiva."""),
            ("assistant", r"""El orden seguro importa más que las directivas: (1) escribir la config en un drop-in `sshd_config.d/99-hardening.conf` (no tocar el principal: los drop-ins se fusionan y son revertibles); (2) VALIDAR con `sshd -t` — analiza la sintaxis SIN reiniciar nada ni cortar sesiones; (3) `reload` (no restart: reload no corta las conexiones establecidas); (4) probar un NUEVO login desde una SEGUNDA sesión/terminal ANTES de cerrar la actual — esa sesión abierta es tu cuerda de seguridad: si el login nuevo falla, la config se revierte sin haber perdido acceso. Sobre las directivas: `PermitRootLogin no` elimina el usuario más bombardeado de internet; `PasswordAuthentication no` + `KbdInteractiveAuthentication no` fuerzan clave (con fail2ban delante, el escaneo de contraseñas deja de tener superficie); `AllowUsers` lista blanca explícita (todo lo demás no existe); `MaxAuthTries`/`LoginGraceTime` reducen la ventana por conexión; `AllowTcpForwarding local` permite -L (túneles hacia dentro) pero niega -R/OpenSSH forward dinámico desde el servidor; `ClientAliveInterval/CountMax` limpia sesiones colgadas. fail2ban: vigila el log de auth, y una IP que acumula `maxretry` fallos dentro de `findtime` recibe un bloqueo de firewall durante `bantime` — mitigación, no sustituto de claves."""),
            ("tool", r"""$ bash -n hardening_sshd.sh && echo "sintaxis ok"
sintaxis ok"""),
            ("assistant", r"""El bloque (se ejecutaría EN el servidor propio; aquí solo se valida sintaxis y se razona):
```bash
#!/usr/bin/env bash
set -euo pipefail
# hardening_sshd.sh — orden seguro: escribir -> validar -> recargar -> probar en 2ª sesión
cat <<'EOF' | sudo tee /etc/ssh/sshd_config.d/99-hardening.conf
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers deploy auditar
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowTcpForwarding local
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
# fail2ban: concepto — la cárcel sshd bloquea por firewall las IPs agresoras
cat <<'EOF' | sudo tee /etc/fail2ban/jail.local
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
EOF
# VALIDACIÓN SIN CORTAR NADA: falla si la config no es válida
sudo sshd -t && echo "sshd: sintaxis de configuración válida"
sudo systemctl reload ssh && echo "sshd: recargado sin cortar la sesión actual"
echo "siguiente paso obligatorio: probar 'ssh deploy@este-host' desde otra sesión ANTES de cerrar esta"
```
Qué hace cada directiva: `PermitRootLogin no` — root no puede entrar por SSH (ni con clave); `PasswordAuthentication no` — solo claves, adiós diccionarios; `KbdInteractiveAuthentication no` — cierra también el camino PAM interactivo; `AllowUsers deploy auditar` — lista blanca: cualquier otro usuario es rechazado antes de pedir credenciales; `MaxAuthTries 3` — 3 intentos por conexión y fuera; `LoginGraceTime 30` — 30s para autenticar o se cae la conexión; `X11Forwarding no` — sin reenvío gráfico que no usas; `AllowTcpForwarding local` — permite -L pero niega -R (no publicar puertos desde el servidor); `ClientAliveInterval 300` + `CountMax 2` — sesiones muertas se limpian a los ~10 min. Y la cárcel fail2ban: `maxretry 5` fallos en `findtime 10m` → la IP pasa `bantime 1h` bloqueada por firewall. La prueba de no-encierro es manual y OBLIGATORIA: segunda terminal, login nuevo, solo entonces cerrar la sesión actual; si fallara, `sudo rm /etc/ssh/sshd_config.d/99-hardening.conf && sudo sshd -t && sudo systemctl reload ssh` desde la sesión aún viva. Aquí no se ha ejecutado nada remoto: sintaxis verificada con `bash -n` y razonamiento verificado contra la documentación de OpenSSH."""),
        ],
        verify=[
            {"name": "sintaxis_del_bloque", "action": "syntax", "lang": "bash", "msg": -1, "block": 0},
        ],
        tags=["sshd", "hardening", "fail2ban", "allowusers"], stack=["bash", "ssh"],
    ),
]
