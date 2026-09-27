"""m_debug_extra3.py — Debugging multi-lenguaje IV (task 4-d-bis) del dataset AI-ku_programming.

8 ejemplos de depuracion (task_type=debugging, recovery=True) con el metodo explicito:
sintoma -> hipotesis (incluye una hipotesis fallida que se descarta con evidencia)
-> experimento -> causa raiz -> correccion -> nueva ejecucion -> verificacion.

Distribucion: Bash 3 (IFS heredado en read, [ ] vs [[ ]] con variable vacia y patron,
sed -i en directorio sin permiso de escritura), JavaScript 2 (parseInt sin radix,
promesa no retornada en funcion async), SQL 2 (ORDER BY con alias ambiguo tras JOIN,
COUNT inflado por fan-out del JOIN), Python 1 (logging configurado despues de emitir).

Dificultad: 4 hard, 3 very_hard, 1 extreme.
Dominios: scripting_automation, backend, databases.

Cada ejemplo trae plan de verificacion doble: el bug falla o produce la salida
incorrecta descrita (msg=1) y el fix pasa (msg=-1).
"""

from schema import E

EXAMPLES = [
    # ------------------------------------------------------------- Bash (3)
    E(
        language="bash",
        domain="scripting_automation",
        subdomain="field_splitting",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", """Nuestro script de despliegue planifica servicios a partir de un fichero de tareas. En
el portatil funciona, pero en el job del orquestador —que inyecta un perfil de entorno
antes de ejecutar— todas las lineas se reportan como malformadas y el rollout se aborta.
Esto es lo que hay en el repo:

```bash
#!/usr/bin/env bash
# rollout.sh — plan de despliegue: servicio y timeout por linea de tasks.txt
source ./profile.sh   # perfil inyectado por el orquestador

fail=0
n=0
while read -r svc timeout; do
  n=$((n+1))
  if [[ -z $svc || -z $timeout ]]; then
    echo "ERROR: linea $n malformada: '$svc' / timeout='$timeout'"
    fail=1
    continue
  fi
  echo "plan: $svc ($timeout s)"
done < tasks.txt

if [[ $fail -ne 0 ]]; then
  echo "ROLLOUT_FALLIDO"
  exit 1
fi
echo "ROLLOUT_OK servicios=$n"
```

El fichero tasks.txt tiene tres lineas: «migrate_db 30», «seed_cache 45» y «smoke_test 10»."""),
            ("assistant", """Sintoma: en el job las tres lineas de tasks.txt salen como malformadas con timeout
vacio; con el mismo fichero y script en mi sesion interactiva el plan sale completo. La
diferencia de entorno es el perfil inyectado. Hipotesis 1 (fallida): tasks.txt llega con
finales de linea CRLF y el \\r contamina el segundo campo. Experimento: od -c tasks.txt no
muestra ningun \\r y una lectura con el IFS por defecto separa bien los dos campos —
descartada. Hipotesis 2: el perfil exportado hace IFS=':' para recorrer listas de rutas;
read hereda ese IFS y, como ':' no es espacio, la linea «migrate_db 30» ya no se trocea:
svc absorbe la linea entera y timeout queda vacio. Experimento: comparar la misma lectura
con IFS por defecto y con IFS=':' forzado."""),
            ("tool", """$ od -c tasks.txt | head -n 2
0000000   m   i   g   r   a   t   e   _   d   b       3   0  \\n   s   e
0000020   e   d   _   c   a   c   h   e       4   5  \\n
(sin \\r en el fichero: hipotesis 1 descartada)
$ printf 'migrate_db 30\\n' | { read -r svc timeout; printf 'IFS_defecto <%s><%s>\\n' "$svc" "$timeout"; }
IFS_defecto <migrate_db><30>
$ printf 'migrate_db 30\\n' | { IFS=: read -r svc timeout; printf 'IFS_heredado <%s><%s>\\n' "$svc" "$timeout"; }
IFS_heredado <migrate_db 30><>
$ bash rollout.sh
ERROR: linea 1 malformada: 'migrate_db 30' / timeout=''
ERROR: linea 2 malformada: 'seed_cache 45' / timeout=''
ERROR: linea 3 malformada: 'smoke_test 10' / timeout=''
ROLLOUT_FALLIDO
$ echo $?
1"""),
            ("assistant", """Confirmado: con IFS=':' la linea no se parte (svc se traga todo y timeout queda vacio);
con el IFS por defecto si. Causa raiz: read trocea con el IFS vigente en el momento de
ejecutarse; el perfil del orquestador exporta IFS=':' y el script nunca lo neutraliza, de
modo que el comportamiento depende de quien invoque el script. Correccion: leer la linea
cruda con IFS= read -r (inmune al IFS heredado; ademas -r evita que las contrabarras se
coman) y trocear despues de forma explicita con IFS=' ' en una lectura puntual:

```bash
#!/usr/bin/env bash
# rollout.sh — plan de despliegue: servicio y timeout por linea de tasks.txt
source ./profile.sh   # perfil inyectado por el orquestador (exporta IFS=':')

fail=0
n=0
while IFS= read -r raw || [[ -n $raw ]]; do   # la linea se lee INTACTA
  n=$((n+1))
  [[ -z $raw || $raw == "#"* ]] && continue
  IFS=' ' read -r svc timeout <<<"$raw"       # troceado explicito, independiente del entorno
  if [[ -z $svc || -z $timeout ]]; then
    echo "ERROR: linea $n malformada: '$svc' / timeout='$timeout'"
    fail=1
    continue
  fi
  echo "plan: $svc ($timeout s)"
done < tasks.txt

if [[ $fail -ne 0 ]]; then
  echo "ROLLOUT_FALLIDO"
  exit 1
fi
echo "ROLLOUT_OK servicios=$n"
```

Verificacion con las mismas fixtures y el mismo perfil hostil: plan: migrate_db (30 s) /
plan: seed_cache (45 s) / plan: smoke_test (10 s) / ROLLOUT_OK servicios=3, exit 0. La
alternativa de restaurar IFS=$' \\t\\n' al inicio tambien funciona, pero fijar el IFS en
cada read documenta la intencion y no depende de que nadie vuelva a exportarlo despues."""),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [
                 {"name": "profile.sh",
                  "content": "export IFS=':'  # inyectado por el orquestador para recorrer rutas\n"},
                 {"name": "tasks.txt", "content": "migrate_db 30\nseed_cache 45\nsmoke_test 10\n"},
             ],
             "expect_fail": True,
             "expect_stdout_contains": ["ROLLOUT_FALLIDO"],
             "expect_stdout_not_contains": ["ROLLOUT_OK"],
             "timeout_s": 10},
            {"name": "fix_correcto", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "profile.sh",
                  "content": "export IFS=':'  # inyectado por el orquestador para recorrer rutas\n"},
                 {"name": "tasks.txt", "content": "migrate_db 30\nseed_cache 45\nsmoke_test 10\n"},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["plan: migrate_db (30 s)", "plan: seed_cache (45 s)",
                                        "plan: smoke_test (10 s)", "ROLLOUT_OK servicios=3"],
             "timeout_s": 10},
        ],
        tags=["bash", "ifs", "read-builtin", "env-inheritance"],
        stack=["bash"],
        recovery=True,
    ),
    E(
        language="bash",
        domain="scripting_automation",
        subdomain="test_operators",
        difficulty="extreme",
        task_type="debugging",
        messages=[
            ("user", """El triaje de logs debe ARCHIVAR todo lo que termina en .log y MANTENER el resto. En el
job de staging clasifica mal: db.log y nginx.log aparecen como MANTENER, y ademas la
linea vacia que queda al final de files.txt provoca un error extrano del builtin test.
Curiosamente, cuando lo pruebo desde mi sesion en un directorio «limpio», funciona.
Script del repo:

```bash
#!/usr/bin/env bash
# triage.sh — decide que hacer con cada fichero listado en files.txt
while read -r f; do
  if [ $f = *.log ]; then
    echo "ARCHIVAR $f"
  else
    echo "MANTENER $f"
  fi
done < files.txt
```

En el directorio de trabajo del job hay, entre otros ficheros, el propio files.txt y un
app.log real (vacio)."""),
            ("assistant", """Sintoma: para db.log y nginx.log la rama ARCHIVAR no se toma (deberia), y con la linea
vacia test explota con un error de operador. Hipotesis 1 (fallida): files.txt viene
contaminado (CRLF o espacios). Experimento: od -c files.txt muestra bytes limpios y, con
el mismo bucle reescrito con [[ ]], el triaje sale correcto — descartada. Hipotesis 2:
[ ] es un comando ordinario y sus argumentos sufren el procesamiento normal del shell
ANTES de que test los vea: la palabra sin comillas *.log sufre expansion de pathname —
y como en el directorio del job existe un app.log, el patron se expande al literal
app.log y la comparacion deja de ser un patron; y con la linea vacia, $f sin comillas
desaparece por word splitting y test recibe un operando de menos (de ahi el «unary
operator expected»). Experimento: traza con bash -x para ver que palabras recibe test."""),
            ("tool", """$ od -c files.txt
0000000   a   p   p   .   l   o   g  \\n   d   b   .   l   o   g  \\n   n
0000020   i   n   g   x   .   l   o   g  \\n  \\n
(bytes limpios: hipotesis 1 descartada)
$ bash triage.sh
ARCHIVAR app.log
MANTENER db.log
MANTENER nginx.log
triage.sh: linea 4: [: =: unary operator expected
MANTENER 
$ bash -x triage.sh 2>&1 | sed -n '2p;4p;6p'
+ [ app.log = app.log ]
+ [ db.log = app.log ]
+ [  = app.log ]
(en la traza se ve: test nunca ve un patron, ve el LITERAL app.log; y con f vacio
recibe dos palabras en lugar de tres)"""),
            ("assistant", """La traza cierra el caso: test nunca ve un patron, ve el literal app.log (el shell expandio
*.log contra el directorio de trabajo), y con la linea vacia le llegan dos palabras en vez
de tres. Causa raiz: [ ] es un comando ordinario; word splitting y globbing transforman
sus argumentos antes de la evaluacion, asi que una variable sin citar que puede estar
vacia y un patron sin citar producen comparaciones distintas de las previstas. [[ ]] es
una palabra clave del shell: no hace splitting ni globbing, el lado derecho de == se
interpreta como patron y la variable vacia sigue siendo un operando. Correccion:
condicion con [[ $f == *.log ]], guard explicito para lineas vacias y lectura con IFS=
read -r para no perder ninguna linea:

```bash
#!/usr/bin/env bash
# triage.sh — decide que hacer con cada fichero listado en files.txt
while IFS= read -r f || [[ -n $f ]]; do
  if [[ -z $f ]]; then
    echo "SALTAR linea vacia"
    continue
  fi
  if [[ $f == *.log ]]; then
    echo "ARCHIVAR $f"
  else
    echo "MANTENER $f"
  fi
done < files.txt
echo "TRIAJE_OK"
```

Verificacion sobre la misma fixture: ARCHIVAR app.log / ARCHIVAR db.log / ARCHIVAR
nginx.log / SALTAR linea vacia / TRIAJE_OK, exit 0. Si por portabilidad POSIX hubiera que
quedarse en [ ], la forma segura seria citar ambos lados ([ "$f" = "$patron" ]) y
renunciar al patron — pero [[ ]] existe exactamente para este caso."""),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "fixtures": [
                 {"name": "files.txt", "content": "app.log\ndb.log\nnginx.log\n\n"},
                 {"name": "app.log", "content": ""},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["ARCHIVAR app.log", "MANTENER db.log", "MANTENER nginx.log"],
             "expect_stdout_not_contains": ["ARCHIVAR db.log", "ARCHIVAR nginx.log"],
             "timeout_s": 10},
            {"name": "fix_correcto", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "files.txt", "content": "app.log\ndb.log\nnginx.log\n\n"},
                 {"name": "app.log", "content": ""},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["ARCHIVAR app.log", "ARCHIVAR db.log", "ARCHIVAR nginx.log",
                                        "SALTAR linea vacia", "TRIAJE_OK"],
             "timeout_s": 10},
        ],
        tags=["bash", "test-builtin", "globbing", "word-splitting"],
        stack=["bash"],
        recovery=True,
    ),
    E(
        language="bash",
        domain="scripting_automation",
        subdomain="atomic_file_update",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", """El job de hotfix parchea la plantilla de configuracion in situ con sed -i. En produccion,
donde /opt/app/templates se monta de solo lectura, el job muere con Permission denied
aunque podemos leer el fichero y somos su dueno. Replica local del fallo:

```bash
#!/usr/bin/env bash
# hotfix.sh — actualiza el puerto de la plantilla de configuracion
set -euo pipefail

mkdir -p templates
cat > templates/app.conf <<'EOF'
listen_port=@PORT@
workers=4
EOF
chmod 444 templates/app.conf
chmod 555 templates        # simula el mount read-only de produccion

sed -i 's/@PORT@/8080/' templates/app.conf
echo "PATCH_OK"
cat templates/app.conf
```"""),
            ("assistant", """Sintoma: sed -i muere con Permission denied sobre un fichero que podemos leer y cuyo
dueno somos, y set -e aborta el script. Hipotesis 1 (fallida): el fichero es 444 y a sed
no le gusta; si lo dejo escribible (chmod 644) el fallo deberia desaparecer. Experimento:
chmod 644 y reintentar — el fallo persiste, descartada: sed -i no escribe SOBRE el
fichero, lo REEMPLAZA. Hipotesis 2: sed -i materializa un fichero temporal en el MISMO
directorio que el original y luego lo renombra; por eso necesita permiso de ESCRITURA DEL
DIRECTORIO, no del fichero. Con templates en 555 (mount ro) no puede crear el temporal.
Experimento: intentar crear cualquier fichero dentro de templates y mirar el error de
sed, que nombra un temporal sedXXXXXX en ese directorio."""),
            ("tool", """$ chmod 644 templates/app.conf && sed -i 's/@PORT@/8080/' templates/app.conf
sed: couldn't open temporary file ./templates/sedK8sQ2x: Permission denied
(el fichero YA era escribible y sigue fallando: hipotesis 1 descartada)
$ touch templates/.probe
touch: cannot touch 'templates/.probe': Permission denied
(nadie puede crear ficheros ahi: el limite es del DIRECTORIO, no del fichero)
$ strace -e trace=openat,renameat sed -i 's/@PORT@/8080/' templates/app.conf 2>&1 | tail -n 3
openat(AT_FDCWD, "templates/sedLm0Pqz", O_RDWR|O_CREAT|O_EXCL, 0600) = -1 EACCES (Permission denied)
write(2, "sed: couldn't open temporary file ./templates/sedLm0Pqz: Permission denied", 75) = 75
+++ exited with 4 +++"""),
            ("assistant", """Confirmado: sed -i crea ./templates/sedXXXXXXXX y renombra; sin permiso de escritura del
directorio fracasa con exit 4 aunque el fichero sea editable. Causa raiz: -i no es
«editar en el sitio» sino «reemplazar la entrada de directorio», y ese namespace pertenece
al directorio. En produccion el directorio es un mount read-only: chmod tampoco es opcion.
Correccion: no mutar la plantilla versionada; RENDERIZAR el artefacto hacia un directorio
escribible con escritura atomica mktemp + mv dentro del mismo directorio de salida:

```bash
#!/usr/bin/env bash
# hotfix.sh — renderiza la configuracion hacia build/ (la plantilla queda intacta)
set -euo pipefail

mkdir -p templates build
cat > templates/app.conf <<'EOF'
listen_port=@PORT@
workers=4
EOF
chmod 444 templates/app.conf
chmod 555 templates        # simula el mount read-only de produccion

tmp=$(mktemp build/app.conf.XXXXXX)
trap 'rm -f "$tmp"' EXIT
sed 's/@PORT@/8080/' templates/app.conf > "$tmp"
mv "$tmp" build/app.conf    # rename atomico en el mismo directorio: nunca parcial
echo "RENDER_OK"
cat build/app.conf
```

Verificacion: sed lee la plantilla (con lectura basta) y escribe en build/ (escribible);
mv es un rename dentro del mismo directorio, atomico y sin temporales huerfanos. Salida:
RENDER_OK, listen_port=8080, workers=4. La plantilla original no cambia (diff vacio),
que es justo lo que exige el pipeline: los fuentes versionados son inmutables y los
artefactos, derivados."""),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "bash", "msg": 1, "block": 0,
             "expect_fail": True,
             "expect_stdout_not_contains": ["PATCH_OK"],
             "timeout_s": 10},
            {"name": "fix_correcto", "action": "run", "lang": "bash", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["RENDER_OK", "listen_port=8080", "workers=4"],
             "expect_stdout_not_contains": ["@PORT@"],
             "timeout_s": 10},
        ],
        tags=["sed", "in-place-edit", "permissions", "atomic-write"],
        stack=["bash"],
        recovery=True,
    ),
    # ------------------------------------------------------ JavaScript (2)
    E(
        language="javascript",
        domain="backend",
        subdomain="number_parsing",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", """El planificador de jobs lee plan.json, donde el equipo de firmware anota las mascaras de
lanes con prefijo de base (binario con 0b, octal con 0o, hex con 0x) y los reintentos en
decimal. Al arrancar, el planificador muere con «mascara invalida» para todos los jobs con
mascara binaria, mientras que el job con mascara hex pasa. Codigo:

```js
const fs = require("fs");

const plan = JSON.parse(fs.readFileSync("plan.json", "utf8"));

const lanesOf = (mask) => {
  const m = parseInt(mask);              // sin radix
  if (!Number.isInteger(m) || m <= 0) {
    throw new Error(`mascara invalida (${mask} -> ${m})`);
  }
  const lanes = [];
  for (let bit = 0; bit < 8; bit++) {
    if (m & (1 << bit)) lanes.push(bit);
  }
  return lanes;
};

let ok = 0;
for (const job of plan.jobs) {
  const retries = parseInt(job.retries);
  const lanes = lanesOf(job.mask);
  console.log(`job ${job.name} lanes=${lanes.join(",")} retries=${retries}`);
  ok++;
}
console.log(`PLAN_OK jobs=${ok}`);
```

El plan.json adjunto al job:

```json
{
  "jobs": [
    {"name": "ingest", "mask": "0b101", "retries": "3"},
    {"name": "compact", "mask": "0x10", "retries": "2"},
    {"name": "publish", "mask": "0b110", "retries": "1"}
  ]
}
```"""),
            ("assistant", """Sintoma: los jobs con mascara 0b... mueren con «mascara invalida (0b101 -> 0)»; el de
mascara 0x10 pasa y calcula lanes=4, correcto por accidente. Si el prefijo fuera el
problema, 0x tambien fallaria: el comportamiento es inconsistente. Hipotesis 1 (fallida):
plan.json llega corrupto (BOM, claves mal escritas). Experimento: JSON.parse no falla y
las claves mask/retries estan bien — descartada. Hipotesis 2: parseInt sin radix aplica la
regla de prefijos de ES2015+ SOLO para hex: «0x10» se auto-detecta como hexadecimal (16),
pero «0b101» NO se detecta como binario — parseInt deja de parsear en la «b» y devuelve 0.
Experimento: sondeo en node con la terna problematica y las versiones con radix explicito."""),
            ("tool", """$ node -e 'for (const v of ["0b101", "0x10", "0o17", "3"]) console.log(v, "=>", parseInt(v));'
0b101 => 0
0x10 => 16
0o17 => 0
3 => 3
$ node -e 'console.log(parseInt("0b101", 2), parseInt("0o17", 8), parseInt("0x10", 16));'
0 0 16
(el prefijo 0b/0o NO se admite ni siquiera pasando radix: hay que trocearlo)
$ node -e 'console.log(parseInt("b101", 2), parseInt("o17", 8), parseInt("10", 16), parseInt("3", 10));'
5 15 16 3
(con radix explicito y prefijo troceado, cada base parsea como corresponde)"""),
            ("assistant", """Confirmado: sin radix, parseInt("0b101") da 0 (se detiene en la «b») y parseInt("0x10")
da 16 (el prefijo 0x si se auto-detecta): el comportamiento por defecto es inconsistente
entre bases y por eso el fallo era selectivo. Causa raiz: parseInt sin radix delega la
base en heuristicas de prefijo; para 0b/0o no existen y para 0x si. Correccion: un parser
con radix EXPLICITO para cada prefijo y radix 10 por defecto — nunca depender de la
deteccion automatica:

```js
const fs = require("fs");

function parseIntWithRadix(value) {
  if (value.startsWith("0b")) return parseInt(value.slice(2), 2);
  if (value.startsWith("0o")) return parseInt(value.slice(2), 8);
  if (value.startsWith("0x")) return parseInt(value.slice(2), 16);
  const m = parseInt(value, 10);
  if (Number.isNaN(m)) throw new Error(`numero no parseable: ${value}`);
  return m;
}

const plan = JSON.parse(fs.readFileSync("plan.json", "utf8"));

const lanesOf = (mask) => {
  const m = parseIntWithRadix(mask);
  if (!Number.isInteger(m) || m <= 0) {
    throw new Error(`mascara invalida (${mask} -> ${m})`);
  }
  const lanes = [];
  for (let bit = 0; bit < 8; bit++) {
    if (m & (1 << bit)) lanes.push(bit);
  }
  return lanes;
};

let ok = 0;
for (const job of plan.jobs) {
  const retries = parseIntWithRadix(job.retries);
  const lanes = lanesOf(job.mask);
  console.log(`job ${job.name} lanes=${lanes.join(",")} retries=${retries}`);
  ok++;
}
console.log(`PLAN_OK jobs=${ok}`);
```

Verificacion con la misma plan.json: job ingest lanes=0,2 retries=3 / job compact lanes=4
retries=2 / job publish lanes=1,2 retries=1 / PLAN_OK jobs=3, exit 0. Regla anadida al
estilo del equipo: todo parseInt nuevo lleva radix; el linter lo rechaza si falta."""),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "js", "msg": 1, "block": 0,
             "fixtures": [
                 {"name": "plan.json",
                  "content": '{\n  "jobs": [\n    {"name": "ingest", "mask": "0b101", "retries": "3"},\n'
                             '    {"name": "compact", "mask": "0x10", "retries": "2"},\n'
                             '    {"name": "publish", "mask": "0b110", "retries": "1"}\n  ]\n}\n'},
             ],
             "expect_fail": True,
             "expect_stdout_contains": ["mascara invalida (0b101 -> 0)"],
             "expect_stdout_not_contains": ["PLAN_OK"],
             "timeout_s": 10},
            {"name": "fix_correcto", "action": "run", "lang": "js", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "plan.json",
                  "content": '{\n  "jobs": [\n    {"name": "ingest", "mask": "0b101", "retries": "3"},\n'
                             '    {"name": "compact", "mask": "0x10", "retries": "2"},\n'
                             '    {"name": "publish", "mask": "0b110", "retries": "1"}\n  ]\n}\n'},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["job ingest lanes=0,2 retries=3",
                                        "job compact lanes=4 retries=2",
                                        "job publish lanes=1,2 retries=1",
                                        "PLAN_OK jobs=3"],
             "timeout_s": 10},
        ],
        tags=["javascript", "parseint", "radix", "config-parsing"],
        stack=["javascript"],
        recovery=True,
    ),
]

EXAMPLES += [
    E(
        language="javascript",
        domain="backend",
        subdomain="async_error_flow",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", """El runner de jobs marca el pipeline como OK y, un instante despues, el proceso muere con
un rechazo de promesa no gestionado. El catch del bucle nunca llega a ejecutarse, aunque
el fichero del job b no existe (el job a si esta en artifacts). Codigo:

```js
const fs = require("fs");

const JOBS = ["a", "b"];
const load = (id) => fs.promises.readFile(`${id}.json`, "utf8");

async function runJob(id) {
  if (!id) throw new Error("id vacio");
  load(id).then((raw) => {
    console.log(`${id}: ${raw.length} bytes`);
  });
}

async function main() {
  for (const id of JOBS) {
    try {
      await runJob(id);
    } catch (e) {
      console.log(`FALLO_CONTROLADO ${id}: ${e.code ?? e.message}`);
    }
  }
  console.log("PIPELINE_OK");
}

main();
```

Adjuntos del job: a.json existe con el contenido {"job":"a"}; b.json no existe y debe
tratarse como fallo controlado, no como caida del proceso."""),
            ("assistant", """Sintoma doble: el proceso imprime PIPELINE_OK (con un job que no existe) y despues
crashea con ENOENT no gestionado, exit 1; el catch del bucle nunca imprime
FALLO_CONTROLADO. Hipotesis 1 (fallida): el catch no captura por el tipo del error o por
el encadenamiento opcional de e.code. Experimento: registrar un console.log dentro del
catch y otro tras el await — el catch NO se ejecuta nunca, asi que el rechazo no esta
llegando al await: descartada. Hipotesis 2: runJob es async pero llama a
load(id).then(...) SIN return: la promesa de load queda huerfana (fire-and-forget),
await runJob(id) resuelve al instante con undefined y el rechazo futuro de load no tiene
dueno. En Node moderno un rechazo sin gestor es fatal (modo throw por defecto), por eso
el proceso muere tras terminar la parte sincrona: PIPELINE_OK sale ANTES del crash.
Experimento: observar el orden de eventos en la ejecucion."""),
            ("tool", """$ node runner.js
PIPELINE_OK
node:internal/fs/promises:1345
  return new FileHandle(await PromisePrototypeThen(
                        ^

Error: ENOENT: no such file or directory, open 'b.json'
    at async open (node:internal/fs/promises:1345:25)
    at async Object.readFile (node:internal/fs/promises:1996:14) {
  errno: -2,
  code: 'ENOENT',
  syscall: 'open',
  path: 'b.json'
}

Node.js v24.21.0
$ echo $?
1
(el catch del bucle nunca se ejecuto: no hay ningun FALLO_CONTROLADO en stdout, y
PIPELINE_OK salio ANTES del crash)"""),
            ("assistant", """El orden de eventos cierra el diagnostico: await sobre una funcion async cuyo cuerpo no
retorna la promesa de load resuelve de inmediato; el rechazo real llega mas tarde y no
tiene nadie esperandolo. Causa raiz: falta return en runJob — load(id).then(...) crea una
cadena huerfana; el try/catch del llamador solo puede capturar rechazos de la promesa que
la funcion retorna. Correccion: retornar la promesa (return load(...).then(...)); con eso
el catch recibe el ENOENT y el pipeline degrada con elegancia:

```js
const fs = require("fs");

const JOBS = ["a", "b"];
const load = (id) => fs.promises.readFile(`${id}.json`, "utf8");

async function runJob(id) {
  if (!id) throw new Error("id vacio");
  return load(id).then((raw) => {
    console.log(`${id}: ${raw.length} bytes`);
  });
}

async function main() {
  for (const id of JOBS) {
    try {
      await runJob(id);
    } catch (e) {
      console.log(`FALLO_CONTROLADO ${id}: ${e.code ?? e.message}`);
    }
  }
  console.log("PIPELINE_OK");
}

main();
```

Verificacion: salida «a: 11 bytes», luego «FALLO_CONTROLADO b: ENOENT» y «PIPELINE_OK»,
exit 0. El unico cambio es la palabra return. Regla de equipo a partir de ahora: toda
promesa creada dentro de una funcion async se retorna o se gestiona, nunca queda suelta;
y el CI usa --unhandled-rejections=strict para que nada de esto pase inadvertido."""),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "js", "msg": 1, "block": 0,
             "fixtures": [
                 {"name": "a.json", "content": '{"job":"a"}'},
             ],
             "expect_fail": True,
             "expect_stdout_contains": ["PIPELINE_OK"],
             "expect_stdout_not_contains": ["FALLO_CONTROLADO"],
             "timeout_s": 10},
            {"name": "fix_correcto", "action": "run", "lang": "js", "msg": -1, "block": 0,
             "fixtures": [
                 {"name": "a.json", "content": '{"job":"a"}'},
             ],
             "expect_exit": 0,
             "expect_stdout_contains": ["a: 11 bytes", "FALLO_CONTROLADO b: ENOENT", "PIPELINE_OK"],
             "timeout_s": 10},
        ],
        tags=["javascript", "promises", "async-await", "unhandled-rejection"],
        stack=["javascript"],
        recovery=True,
    ),
    # ---------------------------------------------------------------- SQL (2)
    E(
        language="sql",
        domain="databases",
        subdomain="query_sorting",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", """El informe de auditoria «movimientos de junio, cronologico por pedido» sale en un orden
que no responde a ninguna fecha de pedido: los pedidos aparecen ordenados por la
antiguedad del CLIENTE. La base y la consulta (SQLite):

```sql
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), amount INTEGER NOT NULL, created_at TEXT NOT NULL);
INSERT INTO users VALUES (1, 'ana', '2024-01-01'), (2, 'bruno', '2024-02-01'), (3, 'carla', '2024-03-01');
INSERT INTO orders VALUES (101, 3, 90, '2024-06-10'), (102, 1, 120, '2024-06-15'), (103, 2, 80, '2024-06-05');
```

```sql
SELECT u.name, o.amount, u.created_at AS date, o.created_at AS date
FROM users u JOIN orders o ON o.user_id = u.id
ORDER BY date;
```

Lo esperado por la auditoria: bruno (pedido del 2024-06-05), carla (2024-06-10) y ana
(2024-06-15), en ese orden."""),
            ("assistant", """Sintoma: el listado sale como ana (2024-01-01), bruno (2024-02-01), carla (2024-03-01):
esas son fechas de ALTA de usuario, no de pedido. Hipotesis 1 (fallida): ASC/DESC
invertido o collation extrana. Experimento: ORDER BY date DESC tampoco da el orden por
pedido (daria 2024-03-01, 2024-02-01, 2024-01-01) — descartada. Hipotesis 2: el SELECT
declara el MISMO alias date para dos columnas distintas (u.created_at y o.created_at):
tras el JOIN el nombre es ambiguo, y SQLite no avisa — resuelve ORDER BY date contra la
PRIMERA columna de salida con ese nombre, la de users. Es una ambiguedad silenciosa:
otros motores la rechazan con error, SQLite elige la primera y ordena por la columna
equivocada. Experimento: comparar el orden de la consulta tal cual con el de un ORDER BY
cualificado a la tabla de orders."""),
            ("tool", """$ sqlite3 auditoria.db
sqlite> SELECT u.name, o.amount, u.created_at AS date, o.created_at AS date
   ...> FROM users u JOIN orders o ON o.user_id = u.id
   ...> ORDER BY date;
ana|120|2024-01-01|2024-06-15
bruno|80|2024-02-01|2024-06-05
carla|90|2024-03-01|2024-06-10
(orden por fecha de alta del usuario: confirma la hipotesis 2)
sqlite> SELECT u.name, o.amount, o.created_at AS order_date
   ...> FROM users u JOIN orders o ON o.user_id = u.id
   ...> ORDER BY o.created_at;
bruno|80|2024-06-05
carla|90|2024-06-10
ana|120|2024-06-15
(cronologico por pedido, como pide la auditoria)"""),
            ("assistant", """Causa raiz: alias duplicado (date) para dos columnas distintas tras el JOIN; la
resolucion de nombres de ORDER BY elige la primera coincidencia en la lista de salida
(users.created_at) sin ningun aviso. Correccion: (1) un alias unico y significativo por
columna (signup_date, order_date) y (2) ORDER BY cualificado con la tabla (o.created_at),
inmune a colisiones de alias:

```sql
SELECT u.name, o.amount, u.created_at AS signup_date, o.created_at AS order_date
FROM users u JOIN orders o ON o.user_id = u.id
ORDER BY o.created_at;
```

Verificacion sobre la misma base: bruno|80|2024-02-01|2024-06-05 / carla|90|2024-03-01|
2024-06-10 / ana|120|2024-01-01|2024-06-15 — cronologico por pedido. Nota para el equipo:
en SQLite la ambiguedad de alias de salida no es un error, se resuelve al primero; la
defensa es no reutilizar alias y cualificar siempre tras un JOIN."""),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["ana|120|2024-01-01|2024-06-15\nbruno|80|2024-02-01|2024-06-05"],
             "expect_stdout_not_contains": ["carla|90|2024-03-01|2024-06-10\nana|120|2024-01-01|2024-06-15"],
             "timeout_s": 10},
            {"name": "fix_correcto", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["bruno|80|2024-02-01|2024-06-05\ncarla|90|2024-03-01|2024-06-10",
                                        "carla|90|2024-03-01|2024-06-10\nana|120|2024-01-01|2024-06-15"],
             "expect_stdout_not_contains": ["ana|120|2024-01-01|2024-06-15\nbruno|80|2024-02-01|2024-06-05"],
             "timeout_s": 10},
        ],
        tags=["sql", "sqlite", "order-by", "join-alias"],
        stack=["sql"],
        recovery=True,
    ),
    E(
        language="sql",
        domain="databases",
        subdomain="aggregate_queries",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", """El cuadro de mando «clientes por ciudad» pinta cifras imposibles: norte aparece con 3
clientes cuando solo hay 2, sur con 3 cuando hay 1, y este —que tiene un cliente sin
pedidos— no aparece en el informe. La base y la consulta:

```sql
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), amount INTEGER NOT NULL);
INSERT INTO customers VALUES (1, 'ana', 'norte'), (2, 'bruno', 'norte'), (3, 'carla', 'sur'), (4, 'david', 'este');
INSERT INTO orders VALUES (101, 1, 50), (102, 1, 70), (103, 2, 30), (104, 3, 10), (105, 3, 20), (106, 3, 30);
```

```sql
SELECT c.city, COUNT(*) AS customers_count
FROM customers c JOIN orders o ON o.customer_id = c.id
GROUP BY c.city
ORDER BY c.city;
```

Cifras reales contadas a mano sobre la tabla customers: norte=2, sur=1, este=1."""),
            ("assistant", """Sintoma: norte=3, sur=3 y este desaparece del informe. Hipotesis 1 (fallida): hay
pedidos duplicados que inflan el conteo. Experimento: SELECT customer_id, COUNT(*) FROM
orders GROUP BY customer_id no devuelve duplicados — descartada. Hipotesis 2: el JOIN 1:N
produce una fila por CADA pedido, asi que COUNT(*) cuenta PEDIDOS, no CLIENTES: ana tiene
2 pedidos y bruno 1, de ahi el 3 de norte; y el INNER JOIN excluye de plano a los clientes
sin pedidos, por eso este ni aparece. Experimento: comparar COUNT(*) con
COUNT(DISTINCT c.id) y cambiar el INNER JOIN por LEFT JOIN."""),
            ("tool", """$ sqlite3 dashboard.db "SELECT c.city, COUNT(*) FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.city ORDER BY c.city;"
norte|3
sur|3
$ sqlite3 dashboard.db "SELECT c.city, COUNT(DISTINCT c.id) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id GROUP BY c.city ORDER BY c.city;"
este|1
norte|2
sur|1
(COUNT(*) contaba filas del join: ana tiene 2 pedidos y bruno 1, luego 3 filas para
norte; con DISTINCT el cliente cuenta una sola vez, y el LEFT JOIN conserva a david
aunque no tenga pedidos)"""),
            ("assistant", """Causa raiz: COUNT(*) sobre un JOIN 1:N mide filas del join (pedidos), no la entidad que
el KPI declara (clientes); y el INNER JOIN silencia las ciudades sin pedidos. Correccion:
COUNT(DISTINCT c.id) para contar cada cliente una sola vez y LEFT JOIN para que las
ciudades con clientes sin pedidos no desaparezcan. Alternativa equivalente: subconsulta
derivada con agregacion previa ((SELECT customer_id, COUNT(*) FROM orders GROUP BY
customer_id) s) — el punto es no contar filas crudas del join:

```sql
SELECT c.city, COUNT(DISTINCT c.id) AS customers_count
FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
GROUP BY c.city
ORDER BY c.city;
```

Verificacion sobre la misma base: este|1 / norte|2 / sur|1, coincide con el recuento
manual de la tabla customers. Regla de equipo: en informes con JOIN, COUNT nunca lleva *;
se nombra la entidad que el KPI cuenta."""),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "sql", "lang": "sql", "msg": 1, "block": 1,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["norte|3", "sur|3"],
             "expect_stdout_not_contains": ["norte|2", "sur|1", "este|1"],
             "timeout_s": 10},
            {"name": "fix_correcto", "action": "sql", "lang": "sql", "msg": -1, "block": 0,
             "setup": [[1, 0]],
             "expect_stdout_contains": ["este|1", "norte|2", "sur|1"],
             "expect_stdout_not_contains": ["norte|3", "sur|3"],
             "timeout_s": 10},
        ],
        tags=["sql", "join", "count-distinct", "fan-out"],
        stack=["sql"],
        recovery=True,
    ),
    # ------------------------------------------------------------ Python (1)
    E(
        language="python",
        domain="backend",
        subdomain="logging_setup",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", """La auditoria exige que el log evidencie la configuracion con la que arranco el proceso:
la linea «AUDIT ... arranque config=local lotes=3» debe aparecer SIEMPRE. En el servicio
no aparece: el log empieza directamente en «cargando clientes.csv». En mi portatil
tampoco sale, asi que no es problema del collector. Codigo:

```python
import logging

log = logging.getLogger("ingest")
AUDIT_ID = "AUD-2024-0042"

def load_file(name):
    log.info("cargando %s", name)
    return len(name) * 7

# diagnostico de arranque: debe quedar evidencia de la config efectiva
log.info("AUDIT %s arranque config=local lotes=3", AUDIT_ID)

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    total = sum(load_file(n) for n in ("clientes.csv", "pedidos.csv"))
    log.info("AUDIT %s fin total=%d", AUDIT_ID, total)
    print("FIN_OK total=%d" % total)

if __name__ == "__main__":
    main()
```"""),
            ("assistant", """Sintoma: la linea de arranque (emitida en tiempo de import, antes de main) no aparece
nunca; las demas si. Hipotesis 1 (fallida): el nivel efectivo del logger esta por encima
de INFO (p. ej. WARNING heredado del raiz). Experimento: forzar
logging.getLogger().setLevel(logging.DEBUG) en el entrypoint: la linea de arranque SIGUE
sin aparecer mientras que las de dentro de main salen — descartada: no es el nivel, es
CUANDO se emite. Hipotesis 2: orden de configuracion: la emision ocurre en tiempo de
import y basicConfig se ejecuta DESPUES (dentro de main). Un registro emitido sin
handlers se descarta para siempre: logging no guarda historico ni reemite registros
previos a la configuracion, y el handler de ultimo recurso (lastResort) solo atiende
WARNING+, de modo que un INFO prematuro se pierde en silencio. Experimento: reemitir el
mismo mensaje como warning sin tocar nada mas — si aparece, confirma que el problema es
«emitido antes de que existiera handler»."""),
            ("tool", """$ python3 -c 'import logging; logging.getLogger().setLevel(logging.DEBUG); logging.getLogger("ingest").info("prueba nivel")'
(sin salida: sin basicConfig el INFO tampoco sale — descarta la hipotesis del nivel)
$ python3 ingest.py
INFO:ingest:cargando clientes.csv
INFO:ingest:cargando pedidos.csv
INFO:ingest:AUD-2024-0042 fin total=161
FIN_OK total=161
$ python3 - <<'PY'
import logging
log = logging.getLogger("ingest")
log.warning("AUDIT ... arranque config=local lotes=3")
PY
AUDIT ... arranque config=local lotes=3
(el WARNING si sale por lastResort: el mensaje se emitia ANTES de que existiera handler)"""),
            ("assistant", """El WARNING de prueba sale por el handler de ultimo recurso y el INFO no: la emision
ocurre en tiempo de import y basicConfig todavia no se ha ejecutado; logging no reemite
ni almacena registros anteriores a la configuracion. Causa raiz: orden de configuracion —
el modulo raiz emite (el diagnostico de auditoria vive a nivel de modulo) ANTES de que
main() instale los handlers; todo lo emitido antes se descarta. Correccion: configurar el
logging en el primer momento de vida del proceso (arriba del modulo de entrada, antes de
cualquier emision, incluidas las de import) y dejar main() solo con logica:

```python
import logging

# la config va PRIMERO: nada puede emitir antes de que existan handlers
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

log = logging.getLogger("ingest")
AUDIT_ID = "AUD-2024-0042"

def load_file(name):
    log.info("cargando %s", name)
    return len(name) * 7

# diagnostico de arranque: debe quedar evidencia de la config efectiva
log.info("AUDIT %s arranque config=local lotes=3", AUDIT_ID)

def main():
    total = sum(load_file(n) for n in ("clientes.csv", "pedidos.csv"))
    log.info("AUDIT %s fin total=%d", AUDIT_ID, total)
    print("FIN_OK total=%d" % total)

if __name__ == "__main__":
    main()
```

Verificacion: la primera linea del log es ahora INFO:ingest:AUD-2024-0042 arranque
config=local lotes=3 y el total sigue siendo 161 (FIN_OK total=161): la correccion no
altero la logica, solo el orden. Regla equivalente para bibliotecas: nunca basicConfig en
el import; para aplicaciones: configurar en el entrypoint antes de importar modulos que
emiten."""),
        ],
        verify=[
            {"name": "bug_reproduce", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["FIN_OK total=161", "INFO:ingest:cargando clientes.csv"],
             "expect_stdout_not_contains": ["arranque config=local"],
             "timeout_s": 10},
            {"name": "fix_correcto", "action": "run", "lang": "python", "msg": -1, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["AUD-2024-0042 arranque config=local lotes=3",
                                        "FIN_OK total=161"],
             "timeout_s": 10},
        ],
        tags=["python", "logging", "config-order", "observability"],
        stack=["python"],
        recovery=True,
    ),
]
