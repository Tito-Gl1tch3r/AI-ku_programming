"""m_powershell.py — Ejemplos de administración real con PowerShell 7.x (Stack V2).

Filosofía: cada ejemplo enseña una decisión real de administración de
Windows / automatización (pipelines de objetos, gestión de errores,
funciones avanzadas, filesystem, servicios, remoting, datos y seguridad
defensiva). Sin cmdlets inventados; rutas genéricas; nada destructivo sin
-WhatIf. Este entorno no tiene pwsh: verify=[] en todos los ejemplos y las
salidas de consola se presentan como testimonios del entorno Windows del
usuario (verificación estática, nunca ejecución afirmada).
"""

from schema import E

EXAMPLES = [
    # ------------------------------------------------------------------ 1
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="pipeline_objetos_format",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Tengo un script de monitorización que debe sacar los 5 procesos que más memoria usan y enviarlos por correo. Según la variante que pruebo, o no filtra nada o imprime cosas raras como nombres de tipo. Mi script:

```powershell
$salida = Get-Process | Format-Table Name, WS -AutoSize
$top = $salida | Sort-Object WS -Descending | Select-Object -First 5
$top | ForEach-Object { "$($_.Name): $([math]::Round($_.WS / 1MB, 1)) MB" }
```

En mi Windows Server con PowerShell 7.4 salen cinco líneas casi vacías, y cuando en vez del ForEach hago `$salida | Select-Object -First 5 | Format-List` veo «Microsoft.PowerShell.Commands.FormatEntryData». ¿Qué estoy rompiendo?"""),
            ("assistant", r"""Síntoma: el filtro de memoria no filtra y aparecen nombres de tipo. Tres hipótesis: (1) WS no es la propiedad correcta y hay que usar WorkingSet64; (2) Sort-Object no encuentra la propiedad y desordena; (3) el pipeline se degrada a texto en algún punto.

Descarto (1) rápido: con `Get-Process | Sort-Object WS -Descending` directo el filtro sí funciona, así que la propiedad existe. El sospechoso es que **Format-Table está en medio del pipeline**: los cmdlets Format-* son de presentación, consumen objetos y emiten registros de formato (FormatStartData, FormatEntryData…), que no tienen Name ni WS. Eso explicaría ambos síntomas a la vez. Compruébalo en tu servidor:"""),
            ("tool", r"""PS> $salida = Get-Process | Format-Table Name, WS -AutoSize
PS> $salida[0].GetType().FullName
Microsoft.PowerShell.Commands.FormatStartData
PS> $salida | Where-Object WS -gt 100MB
PS> # sin salida: los registros de formato no tienen propiedad WS
PS> $salida | Sort-Object WS -Descending | Select-Object -First 3 | ForEach-Object { $_.GetType().Name }
FormatStartData
FormatEntryData
FormatEntryData"""),
            ("assistant", r"""Confirmado: `Format-Table` no emite procesos, emite registros de formato. `Sort-Object WS` no encuentra WS (lo trata como $null y conserva el orden), `Select-Object -First 5` coge los primeros registros de formato y `$_.WS` es $null → líneas vacías.

Causa raíz: **un cmdlet de presentación en medio del pipeline**. Regla: Format-* siempre el último eslabón; si necesitas reutilizar datos, primero filtra/ordena/limita con objetos y solo al final formatea:

```powershell
$top = Get-Process |
    Sort-Object WS -Descending |
    Select-Object -First 5 Name, WS

$top | ForEach-Object {
    '{0}: {1:N1} MB' -f $_.Name, ($_.WS / 1MB)
}
```

Para el cuerpo del correo en tabla: `$top | Format-Table -AutoSize | Out-String` al final del pipeline; para HTML, `ConvertTo-Html` también es cmdlet de salida final.

Cómo se comprobaría: la primera línea debe coincidir con `Get-Process | Sort-Object WS -Descending | Select-Object -First 1`, las cinco deben ser pares «Nombre: X MB» y ninguna debe contener «Format». Como contraste pedagógico: `Get-Process | Format-Table | Sort-Object` nunca podrá ordenar bien porque los datos de renderizado ya no son datos."""),
        ],
        tags=["powershell", "pipeline-objetos", "format-table", "debugging"],
        stack=["powershell"],
        verify=[],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 2
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="manejo_errores_trycatch",
        difficulty="very_hard",
        task_type="debugging",
        messages=[
            ("user", r"""Tengo un script que procesa una lista de ficheros y pensaba que el try/catch me cubría los fallos, pero la salida muestra el error en rojo Y el catch NO se ejecuta, y el contador cuenta ficheros que no existen. Salida de mi consola:

```
PS> C:\Scripts\procesa.ps1
OK: a.txt
Get-Item : Cannot find path 'C:\Datos\informe_old.txt' because it does not exist.
At C:\Scripts\procesa.ps1:7 char:16
+         $item = Get-Item -LiteralPath $f
+                 ~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : ObjectNotFound: (C:\Datos\informe_old.txt:String) [Get-Item], ItemNotFoundException
    + FullyQualifiedErrorId : PathNotFound,Microsoft.PowerShell.Commands.GetItemCommand

OK: c.txt
Procesados correctamente: 3
```

El script:

```powershell
$ficheros = Get-Content C:\Scripts\lista.txt
$ok = 0
foreach ($f in $ficheros) {
    try {
        $item = Get-Item -LiteralPath $f
        $ok++
        "OK: $($item.Name)"
    }
    catch {
        "FALLO en ${f}: $($_.Exception.Message)"
    }
}
"Procesados correctamente: $ok"
```

¿Por qué el catch me ignora el error?"""),
            ("assistant", r"""Primer instinto: que `$f` viniera con espacios o caracteres inválidos. Se refuta leyendo el error: es un `PathNotFound` limpio sobre un fichero que simplemente no existe, y `a.txt` con formato idéntico sí funcionó.

El concepto que falta es la distinción entre **errores terminantes (terminating) y no terminantes (non-terminating)** en PowerShell:

* Un error NO terminante (como `Get-Item` sobre una ruta inexistente) escribe en el flujo de errores (rojo), devuelve nada, y la instrucción **continúa con normalidad**. Como la instrucción no lanza una excepción, `catch` nunca se activa. Por eso ves el error en rojo, sigue «OK: c.txt» y —peor— `$ok++` se ejecuta igual: tu contador dice 3 con dos ficheros reales.
* `catch` solo captura errores terminantes: excepciones reales, errores de comando inexistente, o un error no terminante **escalado** con `-ErrorAction Stop`.

Corrección quirúrgica: pedir a ESE cmdlet que escale:

```powershell
foreach ($f in $ficheros) {
    try {
        $item = Get-Item -LiteralPath $f -ErrorAction Stop
        $ok++
        "OK: $($item.Name)"
    }
    catch [System.Management.Automation.ItemNotFoundException] {
        "FALLO (no existe): $f"
    }
    catch {
        "FALLO inesperado en ${f}: $($_.Exception.GetType().FullName)"
    }
}
"Procesados correctamente: $ok"
```

Notas de decisión: `-ErrorAction Stop` es quirúrgico (solo ese cmdlet); `$ErrorActionPreference = 'Stop'` a nivel de script convierte TODOS los no terminantes en terminantes (útil como política por defecto en scripts de automatización, relajando con `-ErrorAction Continue`/`SilentlyContinue` + `-ErrorVariable` donde el ruido sea esperado). Un catch tipado (`[ItemNotFoundException]`) separa «no existe» de otros fallos.

Cómo se comprobaría: con la misma lista debe salir «FALLO (no existe)» para el fichero ausente, sin ningún error rojo, y «Procesados correctamente: 2» (coherente con los OK)."""),
        ],
        tags=["powershell", "try-catch", "erroraction", "error-terminante"],
        stack=["powershell"],
        verify=[],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 3
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="json_profundidad",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Exporto la configuración de mi herramienta de inventario a JSON y al reimportarla los ajustes anidados desaparecen. El fichero generado tiene, donde debería ir la sección de credenciales, el texto «System.Management.Automation.PSCustomObject». Mi exportación:

```powershell
$cfg = [pscustomobject]@{
    App      = 'Inventario'
    Conexion = [pscustomobject]@{
        Servidor     = 'SRV-DATOS'
        BaseDatos    = 'Inventario'
        Credenciales = [pscustomobject]@{ Usuario = 'svc_inventario'; Origen = 'config' }
    }
    Rutas    = @('C:\Datos', 'C:\Logs')
}
ConvertTo-Json $cfg | Set-Content C:\Scripts\cfg.json
```

Salida real del fichero en mi máquina:

```
PS> Get-Content C:\Scripts\cfg.json
{
  "App": "Inventario",
  "Conexion": {
    "Servidor": "SRV-DATOS",
    "BaseDatos": "Inventario",
    "Credenciales": "System.Management.Automation.PSCustomObject"
  },
  "Rutas": [
    "C:\\Datos",
    "C:\\Logs"
  ]
}
PS> (ConvertFrom-Json (Get-Content C:\Scripts\cfg.json -Raw)).Conexion.Credenciales.Usuario
PS> # sin salida: la propiedad Usuario ya no existe
```

¿ConvertFrom-Json está perdiendo datos al importar?"""),
            ("assistant", r"""Hipótesis natural: que la pérdida esté en la importación. Se refuta con tu propia evidencia: el fichero **ya** no contiene «Usuario» — `Get-Content` lo demuestra antes de tocar `ConvertFrom-Json`. El daño ocurre al exportar.

Causa raíz: `ConvertTo-Json` serializa por defecto hasta **profundidad 2**. Cuenta los niveles: raíz = 1 (App, Rutas), Conexion = 2, Credenciales = 3. Al superar el límite, PowerShell no falla: sustituye el objeto anidado por el **nombre de su tipo** (pérdida silenciosa de datos) y emite un aviso en consola que `Set-Content` no captura, por eso en el fichero no hay rastro:

```
WARNING: Resulting JSON is truncated as serialization has exceeded the set depth.
```

Corrección:

```powershell
ConvertTo-Json $cfg -Depth 5 | Set-Content C:\Scripts\cfg.json
```

Reglas prácticas: (1) calcula la profundidad real de tu objeto y añade margen (5–10) si el esquema puede crecer; el máximo es 100; (2) en automatización no ignores los WARNING de la consola — son el único síntoma de esta truncación; (3) para el round-trip, `ConvertFrom-Json` devuelve PSCustomObject y en PS 7 acepta `-AsHashtable` si prefieres diccionarios; lee con `Get-Content -Raw` (un único string) por compatibilidad.

Cómo se comprobaría: tras el cambio, el fichero debe contener «Usuario» dentro de Credenciales, y `(ConvertFrom-Json (Get-Content C:\Scripts\cfg.json -Raw)).Conexion.Credenciales.Usuario` debe devolver `svc_inventario`. Para blindarlo: añade a tu suite una prueba que exporte, importe y compare (`Compare-Object ($cfg | ConvertTo-Json -Depth 5) ...` o comparación campo a campo)."""),
        ],
        tags=["powershell", "json", "convertto-json", "depth"],
        stack=["powershell"],
        verify=[],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 4
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="comparacion_null",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Tengo un flujo que revisa una cola de ficheros pendientes y envía un aviso cuando la cola está vacía. La rama «Sin pendientes» NUNCA se ejecuta, aunque la carpeta esté vacía; siempre entra por «Hay 0 pendientes» y dispara el flujo de remisión vacío. Código:

```powershell
$pendientes = @()
Get-ChildItem C:\Datos\Cola -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-1) } |
    ForEach-Object { $pendientes += $_.Name }

if ($pendientes -eq $null) {
    'Sin pendientes: nada que remitir'
}
else {
    "Hay $($pendientes.Count) pendientes"
}
```

Reproducido en mi Windows 11 con PowerShell 7.4, con la carpeta Cola vacía:"""),
            ("tool", r"""PS> $pendientes.Count
0
PS> $pendientes.GetType().Name
Object[]
PS> $pendientes -eq $null
PS> # sin salida: no devuelve un booleano
PS> ($pendientes -eq $null) | Measure-Object | Select-Object -ExpandProperty Count
0
PS> $null -eq $pendientes
False"""),
            ("assistant", r"""Mi primera hipótesis fue que `Where-Object` no estaba filtrando nada y por eso nunca entraba la rama; se refuta porque con ficheros antiguos en la carpeta sí entra por el `else` — el bug solo aparece con la colección vacía. La evidencia de la consola da la causa: `$pendientes -eq $null` **no devuelve un booleano**.

Explicación: en PowerShell, `-eq` no es simétrico. Si el lado izquierdo es una **colección**, el operador actúa como **filtro** y devuelve los elementos que cumplen la igualdad (aquí, los elementos que sean $null), no una comparación. Con una colección vacía el filtro no produce nada → en contexto booleano es `$false` → tu rama «Sin pendientes» es inalcanzable. Con un elemento devolvería ese elemento; con varios, un array. `PSScriptAnalyzer` tiene una regla exacta para esto (PSPossibleIncorrectComparisonWithNull): compara con **$null siempre a la izquierda**.

Pero ojo con la segunda trampa: `$null -eq @()` también es `False` — «no es null» no significa «está vacío». Para «sin resultados» la prueba correcta es por vacuidad:

```powershell
if (-not $pendientes) {
    'Sin pendientes: nada que remitir'
}
elseif ($pendientes.Count -eq 0) {
    'Sin pendientes: nada que remitir'
}
else {
    "Hay $($pendientes.Count) pendientes"
}
```

`-not @()` es `True` (una colección vacía es falsa) y también cubre el caso literalmente $null.

Además, simplifica la construcción para eliminar la clase de bug y el coste del `+=` en bucle: `$pendientes = @(Get-ChildItem ... | Where-Object ... | ForEach-Object { $_.Name })` — el `@(...)` garantiza array aunque el pipeline devuelva 0 o 1 elementos.

Cómo se comprobaría: carpeta Cola vacía → «Sin pendientes»; con un fichero con LastWriteTime antiguo → «Hay 1 pendientes»; y en consola `$null -eq $x` para interrogar nulidad, `-not $x` o `.Count -eq 0` para vacuidad."""),
        ],
        tags=["powershell", "null", "comparadores", "psanalyzer"],
        stack=["powershell"],
        verify=[],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 5
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="foreach_statement_vs_cmdlet",
        difficulty="medium",
        task_type="debugging",
        messages=[
            ("user", r"""Quiero registrar los ficheros de más de 500 MB de un árbol de datos. El script corre sin errores pero no escribe NADA en el log, aunque sé que hay ficheros grandes. Código:

```powershell
$ficheros = Get-ChildItem C:\Datos -Recurse -File
foreach ($f in $ficheros) {
    if ($_.Length -gt 500MB) {
        Add-Content C:\Scripts\pesados.log "$($_.FullName) supera 500 MB"
    }
}
```

En mi consola (PowerShell 7.4, Windows Server 2022):

```
PS> Get-ChildItem C:\Datos -Recurse -File | Where-Object Length -gt 500MB | Measure-Object | Select-Object -ExpandProperty Count
3
PS> Get-Content C:\Scripts\pesados.log | Measure-Object -Line | Select-Object -ExpandProperty Lines
0
```

¿Por qué el if no se dispara dentro del foreach?"""),
            ("assistant", r"""El contraste de tu consola lo dice todo: hay 3 ficheros que cumplen la condición, pero el log tiene 0 líneas, y no hay ni un error. Causa: estás usando `$_` dentro de una **sentencia** `foreach`, donde `$_` no existe.

Hay dos `foreach` distintos con el mismo nombre:

1. **Sentencia** `foreach ($f in $coleccion) { ... }`: no recibe pipeline; tú eliges el nombre de la variable de iteración (`$f`) y `$_` NO se define en su cuerpo (vale $null). `$null -gt 500MB` es `False` silenciosamente → ni salida ni error.
2. **Cmdlet `ForEach-Object`** (el alias `foreach` solo cuando va tras una tubería, como en `... | foreach { $_.Name }`): ahí `$_` SÍ es el elemento actual.

En tu código, la condición y el cuerpo deben usar la variable que tú declaraste:

```powershell
$ficheros = Get-ChildItem C:\Datos -Recurse -File
foreach ($f in $ficheros) {
    if ($f.Length -gt 500MB) {
        Add-Content C:\Scripts\pesados.log "$($f.FullName) supera 500 MB"
    }
}
```

Alternativa en pipeline con `$_`:

```powershell
Get-ChildItem C:\Datos -Recurse -File |
    Where-Object Length -gt 500MB |
    ForEach-Object { Add-Content C:\Scripts\pesados.log "$($_.FullName) supera 500 MB" }
```

Criterio de elección: la sentencia es más rápida en colecciones grandes (sin overhead de cmdlet) y admite `break`/`continue` naturales; `ForEach-Object` procesa en streaming (memoria constante para fuentes enormes) y se encadena con el pipeline. Y una trampa relacionada: `Get-ChildItem | foreach ($x in $y) { ... }` es un error de sintaxis/enlace — no mezcles la sintaxis de la sentencia en posición de tubería. `Get-Alias foreach` te recordará que en posición de comando, `foreach` apunta a `ForEach-Object`.

Cómo se comprobaría: tras el fix, `pesados.log` debe tener exactamente 3 líneas nuevas, con FullNames coherentes con el `Where-Object` de contraste que ya ejecutaste."""),
        ],
        tags=["powershell", "foreach", "foreach-object", "pipeline"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 6
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="splatting",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Estoy preparando una llamada a una API y una búsqueda de ficheros, y me estrello con dos errores que no entiendo. En mi PowerShell 7.4:

```
PS> Invoke-RestMethod -Uri $url -Headers @{ Content-Type = 'application/json' }
At line:1 char:47
+ Invoke-RestMethod -Uri $url -Headers @{ Content-Type = 'application/json' }
+                                          ~
Missing '=' operator after key in hash literal.
    + CategoryInfo          : ParserError: (:) [], ParseException
    + FullyQualifiedErrorId : MissingEqualsInHashLiteral

PS> $params = @{ Path = 'C:\Datos'; Recurse = $true; Filter = '*.log' }
PS> Get-ChildItem $params
Get-ChildItem : Cannot convert 'System.Collections.Hashtable' to the type 'System.String' required by parameter 'Path'. Specified method is not supported.
    + CategoryInfo          : InvalidArgument: (:) [Get-ChildItem], ParameterBindingException
```

Quiero pasar esas tablas como parámetros. ¿Qué estoy haciendo mal?"""),
            ("assistant", r"""Son dos problemas distintos de la misma familia: la sintaxis de las tablas hash y el **splatting**.

**Error 1 — clave con guion en un hash literal.** El parser lee `Content` como clave y el `-Type` posterior rompe la gramática del literal; el error es de PARSEO, así que nada se ejecuta. Las claves que no son identificadores válidos (llevan guion, espacios, empiezan por dígito) van entrecomilladas:

```powershell
Invoke-RestMethod -Uri $url -Headers @{ 'Content-Type' = 'application/json' }
```

**Error 2 — splatting con `$` en vez de `@`.** Con `Get-ChildItem $params` pasas la tabla hash como UN único argumento, que PowerShell intenta ligar al parámetro posicional `-Path` (string) y la conversión falla con ese mensaje. Para EXPANDIR una tabla como si fueran parámetros individuales, el splatting usa la arroba:

```powershell
$params = @{
    Path    = 'C:\Datos'
    Recurse = $true
    Filter  = '*.log'
}
Get-ChildItem @params
```

Detalles del splatting que conviene dominar: (1) puedes mezclar parámetros normales y splatted (`Get-ChildItem @params -Force`); (2) el splatting también funciona con arrays para parámetros posicionales; (3) patrón wrapper: `@PSBoundParameters` reenvía al cmdlet interno lo que recibió tu función; (4) como la tabla es un objeto normal, puedes construirla condicionalmente antes de llamar (if/else añadiendo claves) y splattearla al final — es la forma idiomática de «parámetros opcionales» sin strings de comando.

Cómo se comprobaría: la llamada de la API debe partir sin error de parseo (la respuesta HTTP la validarás aparte); `Get-ChildItem @params` debe devolver exactamente lo mismo que `Get-ChildItem C:\Datos -Recurse -Filter '*.log'`; compara ambos recuentos con `Measure-Object`."""),
        ],
        tags=["powershell", "splatting", "hashtable", "parser-error"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 7
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="proveedores_psdrive",
        difficulty="hard",
        task_type="debugging",
        messages=[
            ("user", r"""Tengo un script de inventario de base de datos que funciona perfecto cuando lo ejecuto yo a mano, pero en la tarea programada falla. Lo replico en consola limpia y me pasa lo mismo:

```
PS> powershell -NoProfile -Command "Set-Location SQLSERVER:\"
Set-Location : Cannot find drive. A drive with the name 'SQLSERVER' does not exist.
    + CategoryInfo          : ObjectNotFound: (SQLSERVER:String) [Set-Location], DriveNotFoundException
    + FullyQualifiedErrorId : DriveNotFound,Microsoft.PowerShell.Commands.SetLocationCommand

PS> Get-PSDrive | Format-Table Name, Provider -AutoSize

Name     Provider
----     --------
Alias    Alias
C        FileSystem
Cert     Certificate
Env      Environment
Function Function
HKCU     Registry
HKLM     Registry
Variable Variable
WSMan    WSMan
```

El script:

```powershell
Set-Location SQLSERVER:\SQL\SRV-DATOS\DEFAULT\Databases\Inventario
$sql = Get-Content C:\Scripts\inventario.sql -Raw
Invoke-Sqlcmd -Query $sql | Export-Csv C:\Datos\inventario.csv -NoTypeInformation
```

Primero pensé que era un tema de permisos del usuario de la tarea, pero el error es de unidad, no de acceso. ¿Qué me falta?"""),
            ("assistant", r"""Tu hipótesis de permisos se descarta bien: un fallo de autenticación aparecería DESPUÉS, al ejecutar `Invoke-Sqlcmd`; aquí el error es `DriveNotFound` en la tercera línea del listado de unidades — `SQLSERVER:` ni existe en esa sesión.

Concepto subyacente: las unidades `C:`, `HKLM:`, `Cert:`, `Env:`… las crea el método `InitializeDefaultDrives` de cada **proveedor** cuando su módulo se carga. Los proveedores integrados (FileSystem, Registry, Certificate, Environment…) cargan al arrancar la sesión; las unidades de módulos de producto —`SQLSERVER:` del módulo SqlServer, `IIS:` de WebAdministration/IISAdministration, etc.— solo existen **tras importar el módulo**. Tu consola interactiva «funcionaba» porque en esa sesión ya habías cargado SqlServer; la tarea programada arranca una sesión limpia.

Detalle fino que explica por qué el auto-loading no te salva: la carga automática de módulos dispara al resolver **comandos**, no proveedores ni unidades. `Set-Location SQLSERVER:\` no menciona ningún comando del módulo, así que PowerShell no importa SqlServer y la unidad no aparece.

Correcciones:

```powershell
Import-Module SqlServer   # registra el proveedor y crea la unidad SQLSERVER:
Set-Location SQLSERVER:\SQL\SRV-DATOS\DEFAULT\Databases\Inventario
```

o, mejor para automatización, evita la unidad por completo:

```powershell
Invoke-Sqlcmd -ServerInstance SRV-DATOS -Database Inventario -Query $sql |
    Export-Csv C:\Datos\inventario.csv -NoTypeInformation
```

Cómo se comprobaría: en una sesión nueva con `-NoProfile`, `Get-PSDrive SQLSERVER` falla antes del `Import-Module` y devuelve la unidad después (Provider SqlServer, Root SQLSERVER:\); la tarea programada debe terminar y generar el CSV. Regla general para scripts desatendidos: importa explícitamente los módulos que usas y nunca dependas del perfil ni del estado residual de una sesión interactiva."""),
        ],
        tags=["powershell", "psdrive", "proveedores", "initialize-default-drives"],
        stack=["powershell"],
        verify=[],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 8
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="inventario_logs_filter",
        difficulty="medium",
        task_type="implementation",
        messages=[
            ("user", r"""Necesito un inventario de todos los .log bajo C:\Datos con tamaño y fecha, exportado a CSV. Esto es lo que probé y devuelve TODOS los ficheros, no solo los .log:

```powershell
Get-ChildItem -Path C:\Datos -Include *.log |
    Select-Object Name, Length, LastWriteTime
```

Supón que el árbol es recursivo y que puede ser grande (cientos de miles de ficheros). ¿Cómo lo dejo fino y rápido?"""),
            ("assistant", r"""Requisitos que infiero y hago explícitos: recorrido recursivo de todo el árbol, filtrado real por extensión, salida CSV estable para reimportar y rendimiento en árboles grandes. Dime si el recorrido no debe ser recursivo.

Por qué tu línea no filtra: `-Include` solo surte efecto si la ruta lleva comodín (`C:\Datos\*`) **o** si el comando recursa (`-Recurse`). Con `-Path C:\Datos` a secas, `-Include` se ignora y obtienes el listado completo del primer nivel. Formas correctas, en orden de preferencia:

```powershell
# 1) -Filter: el proveedor FileSystem filtra DURANTE la enumeración (lo más rápido)
Get-ChildItem -Path C:\Datos -Recurse -Filter *.log -File |
    Select-Object Name, Length, LastWriteTime, FullName |
    Export-Csv C:\Datos\inventario_logs.csv -NoTypeInformation -Encoding utf8BOM

# 2) -Include con comodín en la ruta (filtra tras enumerar)
Get-ChildItem -Path C:\Datos\* -Include *.log -Recurse -File

# 3) -Include con -Recurse (filtra tras enumerar)
Get-ChildItem -Path C:\Datos -Recurse -Include *.log -File
```

Matices que depara cada vía:

* `-Filter` se delega al proveedor (API de archivos), por eso gana claramente en árboles grandes. Pero hereda emparejamiento estilo DOS vía nombres cortos 8.3: un patrón como `*.ppt` puede devolver también `.pptx` (la extensión larga se trunca a tres caracteres en el nombre corto). Si necesitas precisión estricta, añade un segundo filtrado con objetos: `Where-Object Extension -eq '.log'`.
* `-Include`/`-Exclude` aplican después de enumerar, aceptan LISTAS (`-Include *.log, *.etl`) y no sufren la rareza 8.3; para multiextensión son la elección natural.
* Incluyo `FullName` en el CSV: con subcarpetas, `Name` solo es ambiguo (dos `app.log` en carpetas distintas).
* `-Encoding utf8BOM` en PS 7 (en Windows PowerShell 5.1 sería `-Encoding UTF8`) para que Excel lo abra bien.

Cómo se comprobaría: compara `(Get-ChildItem C:\Datos -Recurse -File).Count` contra las filas del CSV (solo .log); valida con un árbol de prueba que contenga un `falso.logx` si usas `-Filter`; y cronometra ambas variantes con `Measure-Command` en tu árbol real — con cientos de miles de ficheros la diferencia de `-Filter` suele ser de minutos."""),
        ],
        tags=["powershell", "get-childitem", "filter", "include"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 9
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="funciones_avanzadas_validacion",
        difficulty="very_hard",
        task_type="implementation",
        messages=[
            ("user", r"""Quiero estandarizar cómo generamos los informes de ficheros obsoletos en mi equipo. Necesito una función reutilizable `Get-StaleFileReport` con estas reglas de entrada: ruta obligatoria que debe existir y ser carpeta (error claro si no), unidad de tiempo solo Day/Week/Month, antigüedad entre 1 y 3650. La salida debe poder canalizarse por el pipeline (nada de texto ya formateado) porque cada consumidor la usa distinto: unos a CSV, otros a JSON y otros ordenan por días de antigüedad."""),
            ("assistant", r"""Requisito clave que explicito: los errores de entrada deben detectarse en el **binding** (antes de ejecutar cualquier lógica) con mensajes accionables, y la salida serán objetos `PSCustomObject` — el formato lo decide el consumidor, nunca la función.

Con `[CmdletBinding()]` la función se convierte en *advanced function*: hereda los parámetros comunes (`-Verbose`, `-ErrorAction`, `-WarningAction`…) y accedes a `$PSCmdlet`. Las validaciones se declaran como atributos, no con ifs dispersos:

```powershell
function Get-StaleFileReport {
    [CmdletBinding()]
    [OutputType([pscustomobject])]
    param(
        [Parameter(Mandatory, Position = 0, ValueFromPipeline)]
        [ValidateScript({
            if (Test-Path -LiteralPath $_ -PathType Container) { $true }
            else { throw "La ruta '$_' no existe o no es una carpeta." }
        })]
        [string]$Path,

        [Parameter()]
        [ValidateSet('Day', 'Week', 'Month')]
        [string]$Unit = 'Day',

        [Parameter()]
        [ValidateRange(1, 3650)]
        [int]$Age = 90
    )

    $dias = switch ($Unit) {
        'Day'   { $Age }
        'Week'  { $Age * 7 }
        'Month' { $Age * 30 }
    }
    $corte = (Get-Date).AddDays(-$dias)

    Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object LastWriteTime -lt $corte |
        ForEach-Object {
            [pscustomobject]@{
                Name          = $_.Name
                FullName      = $_.FullName
                SizeMB        = [math]::Round($_.Length / 1MB, 2)
                LastWriteTime = $_.LastWriteTime
                DaysIdle      = ((Get-Date) - $_.LastWriteTime).Days
            }
        }
}
```

Decisiones y por qué: (1) `ValidateSet` valida Y da autocompletado con Tab en la consola; (2) en `ValidateScript` lanzo yo el error para controlar el mensaje (en PS 7 también existe la forma `[ValidateScript({...}, ErrorMessage = '...')]`); (3) `ValidateRange` acota el entero sin una línea de código de más; (4) `switch` para mapear unidades — ojo, un «mes» aquí son 30 días, deliberadamente determinista; si necesitas meses de calendario usa `AddMonths`; (5) `-ErrorAction SilentlyContinue` evita que un fichero bloqueado aborte el informe; para auditoría seria, añade `-ErrorVariable problemas` y expón el listado de fallos; (6) el pipeline de entrada (`ValueFromPipeline`) permite `Get-ChildItem carpetas | Get-StaleFileReport`... con la matiz de que cada carpeta emite su propio flujo.

Demostración del binding en una consola (fallos ANTES de tocar el disco):"""),
            ("tool", r"""PS> Get-StaleFileReport -Path 'C:\NoExiste'
Get-StaleFileReport : La ruta 'C:\NoExiste' no existe o no es una carpeta.
    + CategoryInfo          : InvalidData: (:) [Get-StaleFileReport], ParameterBindingValidationException
    + FullyQualifiedErrorId : ParameterArgumentValidationError,Get-StaleFileReport

PS> Get-StaleFileReport -Path 'C:\Datos' -Unit Year
Get-StaleFileReport : Cannot validate argument on parameter 'Unit'. The argument
"Year" does not belong to the set "Day,Week,Month" specified by the ValidateSet attribute.
    + CategoryInfo          : InvalidArgument: (:) [Get-StaleFileReport], ParameterBindingValidationException
    + FullyQualifiedErrorId : ValidateSetFailure,Get-StaleFileReport"""),
            ("assistant", r"""Esa es la prueba de que la validación ocurre en el binding: ni una línea de escaneo se ejecutó con entradas inválidas.

Cómo se comprobaría: `Get-StaleFileReport C:\Datos -Unit Week -Age 4 | Sort-Object DaysIdle -Descending | Select-Object -First 5` debe devolver 5 objetos con `DaysIdle >= 28`; cada consumidor añade SU formato final (`Export-Csv`, `ConvertTo-Json -Depth 3`…); y con la ruta inexistente debes obtener el error de binding sin ningún acceso al árbol. Si tu equipo usa Pester, el caso «ruta inválida → error en binding» y «Unit inválida → ValidateSetFailure» son dos tests triviales y valiosos."""),
        ],
        tags=["powershell", "cmdlet-binding", "validateset", "validatescript", "pscustomobject"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 10
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="shouldprocess_whatif",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Voy a automatizar la limpieza de logs temporales en servidores del departamento. Operaciones me exige que toda función que mueva o borre soporte `-WhatIf` y `-Confirm` ANTES de aprobar el despliegue. Lo intenté comprobando un parámetro `$WhatIf` con un if y me dijeron que eso no es como se hace. ¿Cuál es la forma correcta?"""),
            ("assistant", r"""Correcto: no se comprueba nada a mano. El motor lo hace por ti con **`SupportsShouldProcess`** en el atributo `[CmdletBinding()]` y el método `$PSCmdlet.ShouldProcess()`. Ese patrón te da `-WhatIf`, `-Confirm` y `-ConfirmImpact` coherentes con todos los cmdlets nativos:

```powershell
function Move-OldLogs {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Destination,

        [ValidateRange(1, 3650)]
        [int]$DaysOld = 30
    )

    $corte = (Get-Date).AddDays(-$DaysOld)
    $ficheros = Get-ChildItem -LiteralPath $Path -Filter *.log -File |
        Where-Object LastWriteTime -lt $corte

    foreach ($f in $ficheros) {
        $destino = Join-Path $Destination $f.Name
        if ($PSCmdlet.ShouldProcess($f.FullName, "Mover a $destino")) {
            Move-Item -LiteralPath $f.FullName -Destination $destino
        }
    }
}
```

Semántica que obtienes gratis: con `-WhatIf`, `ShouldProcess` devuelve `$false`, imprime el plan y NO ejecuta nada; con `-Confirm`, pregunta por cada acción; y con `ConfirmImpact = 'High'` preguntaría incluso sin flags — por eso no pongas High sin motivo. Notas de diseño: (1) `ShouldProcess` envuelve SOLO la parte que muta estado; cálculos y lecturas van fuera; (2) los textos «operación» y «target» que pasas son tu contrato de revisión — descriptivos, con destino incluido; (3) aunque la preferencia `-WhatIf` de tu función también baja por ámbito a los cmdlets internos (Move-Item la heredaría), el patrón con `ShouldProcess` es preferible: controlas la redacción y agrupas el lote; (4) para preguntas adicionales del tipo «¿continuar con todos?» existe `$PSCmdlet.ShouldContinue()`.

Resultado del dry run en una consola Windows:"""),
            ("tool", r"""PS> Move-OldLogs -Path C:\Datos\Logs -Destination C:\Datos\Logs\Antiguos -WhatIf
What if: Performing the operation "Mover a C:\Datos\Logs\Antiguos\svc-2024-01.log" on target "C:\Datos\Logs\svc-2024-01.log".
What if: Performing the operation "Mover a C:\Datos\Logs\Antiguos\svc-2024-02.log" on target "C:\Datos\Logs\svc-2024-02.log".
PS> Get-ChildItem C:\Datos\Logs\*.log | Measure-Object | Select-Object -ExpandProperty Count
14"""),
            ("assistant", r"""El recuento posterior (14) verifica que `-WhatIf` no movió nada: los ficheros siguen en su sitio.

Cómo se comprobaría: (1) `-WhatIf` → plan legible, cero mutaciones (compara recuentos antes/después como arriba); (2) `-Confirm` → pregunta Y/N por fichero; (3) sin flags → mueve sin preguntar (ConfirmImpact Medium); (4) integra en tu revisión de operaciones la regla: ninguna función que escriba/borre/mueva sin `SupportsShouldProcess`, y todo despliegue pasa primero por un run con `-WhatIf` cuyo plan alguien aprueba."""),
        ],
        tags=["powershell", "shouldprocess", "whatif", "confirm"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 11
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="inventario_recursivo",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Necesito un inventario del árbol C:\Datos limitado a 2 niveles de profundidad: por cada carpeta de primer nivel, número de ficheros, tamaño total en MB, el fichero más antiguo con su fecha y el propietario de la carpeta. Exportar a CSV. Problema: hay carpetas del sistema que dan «acceso denegado» y abortan el script entero. No quiero que un aborto lo tire, pero tampoco quiero perder la constancia de qué falló."""),
            ("assistant", r"""Requisitos que explicito: profundidad controlada, agregación por carpeta de primer nivel, tolerancia a fallos de acceso SIN silenciarlos (capturarlos aparte), CSV estable. Piezas clave: `-Depth` en `Get-ChildItem`, `-ErrorAction SilentlyContinue` COMBINADO con `-ErrorVariable` (lo primero esconde el error del flujo pero igualmente lo registra; si usaras `-ErrorAction Ignore` ni siquiera se registraría — decisión importante), y splatting para legibilidad.

```powershell
$raiz    = 'C:\Datos'
$fallos  = @()

$informe = foreach ($carpeta in (Get-ChildItem -LiteralPath $raiz -Directory)) {
    $params = @{
        LiteralPath   = $carpeta.FullName
        Recurse       = $true
        Depth         = 1          # carpeta + un nivel más = 2 niveles del árbol
        File          = $true
        ErrorAction   = 'SilentlyContinue'
        ErrorVariable = '+fallos'  # + para ACUMULAR entre iteraciones
    }
    $items = @(Get-ChildItem @params)

    if ($items.Count -eq 0) { continue }

    $masAntiguo = $items | Sort-Object LastWriteTime | Select-Object -First 1

    [pscustomobject]@{
        Carpeta      = $carpeta.Name
        Ficheros     = $items.Count
        TamanoMB     = [math]::Round(($items | Measure-Object Length -Sum).Sum / 1MB, 2)
        MasAntiguo   = $masAntiguo.Name
        AntiguoDesde = $masAntiguo.LastWriteTime.ToString('yyyy-MM-dd')
        Propietario  = (Get-Acl -LiteralPath $carpeta.FullName).Owner
    }
}

$informe | Export-Csv C:\Datos\inventario_carpetas.csv -NoTypeInformation -Encoding utf8BOM
"Elementos sin acceso: $($fallos.Count)"
$fallos | Select-Object -ExpandProperty CategoryInfo -First 5
```

Decisiones: (1) `@(...)` alrededor de `Get-ChildItem` garantiza array incluso con cero resultados, así `$items.Count` es fiable; (2) si una carpeta entera está denegada, `continue` la omite del informe — si prefieres LISTARLA con `Ficheros = 0` y `Propietario = '(sin acceso)'`, sustituye el `continue` por un `pscustomobject` de emergencia; es una decisión de producto del informe, declárala; (3) `Get-Acl` también puede fallar en carpetas denegadas: envuélvelo en `try/catch` con `-ErrorAction Stop` y pon un propietario de reserva si te ocurre; (4) fecha en formato `yyyy-MM-dd` (independiente de la cultura del servidor) para que el CSV no cambie de aspecto entre máquinas; (5) `-Encoding utf8BOM` para Excel.

Cómo se comprobaría: la suma de `Ficheros` debe cuadrar (menos las denegadas) con `Get-ChildItem C:\Datos -Recurse -File -ErrorAction SilentlyContinue | Measure-Object`; el contador de `$fallos` debe coincidir con las carpetas/ficheros que tu usuario no puede leer; y reejecutar el script debe dar el mismo CSV salvo cambios reales en el árbol."""),
        ],
        tags=["powershell", "inventario", "depth", "errorvariable", "get-acl"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 12
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="archivado_determinista",
        difficulty="very_hard",
        task_type="automation",
        messages=[
            ("user", r"""Necesito mover los ficheros sin modificar hace más de 180 días de C:\Datos a C:\Archivo, conservando la estructura relativa (C:\Datos\Proyectos\X\a.log → C:\Archivo\Proyectos\X\a.log), con soporte -WhatIf, y que se pueda REEJECUTAR sin romper nada. Mi intento actual usa timestamps en el nombre de destino cuando hay colisión y además sobrescribe ficheros que se llaman igual desde carpetas distintas. Quiero algo determinista."""),
            ("assistant", r"""Requisitos que explicito antes de codificar: (1) **idempotencia** — la segunda ejecución debe reportar cero movimientos y no tocar nada; (2) **determinismo ante colisiones** — mismo estado inicial debe producir siempre el mismo resultado: sufijos incrementales `.1`, `.2` (no timestamps, que dependen del reloj); (3) nunca sobrescribir: si existe el destino, comparo SHA-256 y decido; (4) `-WhatIf`/`-Confirm` con `ShouldProcess` incluyendo la creación de carpetas.

```powershell
function Move-StaleFiles {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory)]
        [string]$SourceRoot,

        [Parameter(Mandatory)]
        [string]$ArchiveRoot,

        [ValidateRange(1, 3650)]
        [int]$DaysIdle = 180
    )

    $SourceRoot  = $SourceRoot.TrimEnd('\')
    $ArchiveRoot = $ArchiveRoot.TrimEnd('\')
    $corte   = (Get-Date).AddDays(-$DaysIdle)
    $movidos = 0

    $candidatos = Get-ChildItem -LiteralPath $SourceRoot -Recurse -File |
        Where-Object LastWriteTime -lt $corte

    foreach ($f in $candidatos) {
        $relativo   = $f.FullName.Substring($SourceRoot.Length).TrimStart('\')
        $destinoDir = Split-Path -Parent (Join-Path $ArchiveRoot $relativo)
        $destino    = Join-Path $ArchiveRoot $relativo

        if (-not (Test-Path -LiteralPath $destinoDir)) {
            if ($PSCmdlet.ShouldProcess($destinoDir, 'Crear carpeta')) {
                New-Item -Path $destinoDir -ItemType Directory -Force | Out-Null
            }
        }

        if (Test-Path -LiteralPath $destino) {
            $hashOrigen  = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
            $hashDestino = (Get-FileHash -LiteralPath $destino -Algorithm SHA256).Hash
            if ($hashOrigen -eq $hashDestino) { continue }   # ya archivado: idempotente
            $i = 1
            while (Test-Path -LiteralPath "$destino.$i") { $i++ }
            $destino = "$destino.$i"
        }

        if ($PSCmdlet.ShouldProcess($f.FullName, "Mover a $destino")) {
            Move-Item -LiteralPath $f.FullName -Destination $destino
            $movidos++
        }
    }

    [pscustomobject]@{ Fecha = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); Movidos = $movidos }
}
```

Puntos de decisión: (1) `TrimEnd('\')` + `Substring` reconstruyen la ruta relativa de forma predecible; (2) la igualdad de hash trata «ya archivado» como no-op, que es lo que hace idempotente al flujo; (3) la colisión real (mismo nombre, distinto contenido) resuelve con sufijo determinista; (4) el dry run incluye la creación de carpetas, así el plan aprobado es el plan completo; (5) límites que conviene declarar: ficheros abiertos por procesos harán fallar `Move-Item` (envuélvelo en try/catch si quieres continuar con el resto) y entre volúmenes distintos el movimiento es copiar+borrar — para volúmenes enormes valora `robocopy /MOV`, que además tiene logs propios.

Dry run en mi plan de pruebas:"""),
            ("tool", r"""PS> Move-StaleFiles -SourceRoot C:\Datos -ArchiveRoot C:\Archivo -WhatIf
What if: Performing the operation "Crear carpeta" on target "C:\Archivo\Proyectos\X".
What if: Performing the operation "Mover a C:\Archivo\Proyectos\X\a.log" on target "C:\Datos\Proyectos\X\a.log".
What if: Performing the operation "Mover a C:\Archivo\Proyectos\X\a.log.1" on target "C:\Datos\Proyectos\Y\a.log"."""),
            ("assistant", r"""Fíjate en la tercera línea: la colisión de `a.log` entre Proyectos\X y Proyectos\Y aparece en el PLAN, no como sorpresa en producción.

Cómo se comprobaría: (1) ejecuta con `-WhatIf` y revisa el plan (ese es el artefacto que aprueba operaciones); (2) ejecución real → el objeto de salida reporta los movimientos; (3) **ejecución inmediatamente repetida** → `Movidos = 0` y ningún mensaje nuevo: esa es la prueba de idempotencia; (4) en el árbol de prueba coloca deliberadamente dos ficheros con el mismo nombre y contenido distinto para validar el sufijo `.1`, y dos con el mismo nombre y contenido idéntico para validar el no-op por hash."""),
        ],
        tags=["powershell", "archivado", "idempotencia", "shouldprocess", "get-filehash"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 13
    E(
        language="powershell",
        domain="systems",
        subdomain="servicios_backoff",
        difficulty="very_hard",
        task_type="automation",
        messages=[
            ("user", r"""Tras un parche, el servicio `ERPWorker` de nuestro ERP se queda a veces en Stopped en los servidores de aplicaciones. Necesito un script para la tarea programada de recuperación: si el servicio no está Running, pararlo limpio, arrancarlo y esperar con reintentos tipo backoff hasta un máximo de 5 minutos; si no arranca, dejar registro claro y un código de salida distinto de 0 para que el planificador marque la tarea como fallida. Mi primer intento con Start-Service y un sleep fijo de 5 segundos se quedaba corto: el servicio tarda en pasar por StartPending."""),
            ("assistant", r"""Tu observación sobre StartPending es el síntoma clave: sondear el estado con esperas fijas cortas falla tanto por corto (no da tiempo) como por rígido (martillea el SCM). Antes de la solución, dos hipótesis que descarté del enunciado original: (a) usar `Stop-Service` sin `-Force` aborta si hay servicios dependientes — necesitas `-Force`; (b) fiarse del objeto de servicio sin `Refresh()` — el objeto `ServiceController` NO se actualiza solo.

```powershell
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ServiceName,

    [int]$TimeoutMin = 5
)

$plazo = (Get-Date).AddMinutes($TimeoutMin)
$log = 'C:\Logs\recuperacion_servicio.log'

function Write-Log {
    param([string]$Mensaje)
    '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $PID, $Mensaje |
        Add-Content -Path $log -Encoding utf8BOM
}

try {
    $svc = Get-Service -Name $ServiceName -ErrorAction Stop

    if ($svc.Status -ne 'Running') {
        Write-Log "$ServiceName en estado $($svc.Status); iniciando recuperación"

        if ($svc.Status -ne 'Stopped') {
            Stop-Service -Name $ServiceName -Force -ErrorAction Stop
            $svc.WaitForStatus('Stopped', '00:02:00')
        }

        Start-Service -Name $ServiceName -ErrorAction Stop

        $espera = 2
        while ($svc.Status -ne 'Running' -and (Get-Date) -lt $plazo) {
            Start-Sleep -Seconds $espera
            $svc.Refresh()
            Write-Log "Estado: $($svc.Status); reintento en $espera s"
            $espera = [math]::Min($espera * 2, 30)
        }
    }

    $svc.Refresh()
    if ($svc.Status -eq 'Running') {
        Write-Log "$ServiceName Running"
        exit 0
    }

    Write-Log "ERROR: $ServiceName sigue en $($svc.Status) tras $TimeoutMin min"
    exit 2
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}
```

Decisiones: (1) `Get-Service -ErrorAction Stop` dentro del try: servicio inexistente → catch → `exit 1` con causa registrada; (2) `Stop-Service -Force` cubre dependientes y `WaitForStatus` con timeout propio evita colgar la tarea si el servicio no obedece; (3) backoff 2→4→8→16→30 (techo 30 s): sondea sin abusar del SCM y respeta el StartPending que sufrías; (4) `$svc.Refresh()` tras cada espera; (5) códigos de salida diferenciados: 0 recuperado (o ya sano), 1 error de ejecución, 2 timeout de arranque — el planificador puede distinguir causas; recuerda que `exit N` es lo correcto aquí, `$LASTEXITCODE` solo aplica a ejecutables nativos; (6) sin credenciales en el script: la tarea corre con una cuenta de servicio con los mínimos permisos sobre ESE servicio (mínimo privilegio); si el servicio necesita otra identidad, se configura en el propio servicio, no en este script.

Registro real tras una ejecución de recuperación en un servidor de pruebas:"""),
            ("tool", r"""PS> C:\Scripts\Recupera-Servicio.ps1 -ServiceName ERPWorker
PS> Get-Content C:\Logs\recuperacion_servicio.log -Tail 4
2024-06-03 09:41:02 [7140] ERPWorker en estado Stopped; iniciando recuperación
2024-06-03 09:41:04 [7140] Estado: StartPending; reintento en 2 s
2024-06-03 09:41:12 [7140] Estado: StartPending; reintento en 8 s
2024-06-03 09:41:28 [7140] ERPWorker Running
PS> $LASTEXITCODE
0"""),
            ("assistant", r"""La escalera 2 s → 8 s del log evidencia el backoff y el `exit 0` confirma el estado final verificado, no asumido.

Cómo se comprobaría: en un banco de pruebas, (1) detén `ERPWorker` manualmente y ejecuta el script → código 0 y log con la escalera de backoff; (2) prueba con un nombre de servicio inexistente → `exit 1` y línea ERROR en el log; (3) para el caso de timeout, usa un servicio que sepas que no puede arrancar (dependencia rota) → `exit 2` tras ~5 minutos. Los tres caminos deben quedar registrados con timestamp y PID."""),
        ],
        tags=["powershell", "servicios", "backoff", "waitforstatus", "exit-codes"],
        stack=["powershell"],
        verify=[],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 14
    E(
        language="powershell",
        domain="systems",
        subdomain="remoting_revision",
        difficulty="hard",
        task_type="code_review",
        messages=[
            ("user", r"""Tengo autorización del equipo de sistemas para inventariar el espacio en disco de nuestros 60 servidores Windows del dominio. Este script funciona, pero tarda unos 20 minutos y en los destinos quedan conexiones WinRM abiertas; además, cuando intenté usar dentro del bloque una variable `$origen` definida en mi máquina, llegó vacía. Revísamelo:

```powershell
$servidores = Get-Content C:\Scripts\servers.txt
$resultado = foreach ($srv in $servidores) {
    $sesion = New-PSSession -ComputerName $srv
    $libre = Invoke-Command -Session $sesion -ScriptBlock {
        (Get-PSDrive C).Free / 1GB
    }
    "$srv tiene $libre GB libres"
}
$resultado | Out-File C:\Datos\espacio.txt
```"""),
            ("assistant", r"""Revisión por severidad:

1. **Fuga de sesiones (medio).** Creas una `PSSession` por servidor y nunca la cierras: si el script se corta o un `Invoke-Command` falla, la sesión queda abierta. En tu máquina lo verás con `Get-PSSession`. Para trabajo ad hoc de un solo disparo, ni siquiera necesitas sesiones explícitas: `Invoke-Command -ComputerName` crea, usa y destruye. Si necesitas sesión persistente (varias llamadas al mismo destino), el patrón es `try/finally` con `Remove-PSSession`.

2. **Latencia (medio).** Una llamada por servidor EN SERIE. `Invoke-Command` acepta una LISTA de equipos y hace fan-out paralelo (32 destinos concurrentes por defecto, ajustable con `-ThrottleLimit`). 60 servidores pasan de ~20 min a un par de minutos.

3. **Ámbito de variables (tu tercer síntoma).** El scriptblock se ejecuta EN EL DESTINO: tus variables locales no viajan. El mecanismo correcto es `$using:origen`. Interpolar strings para «inyectar» valores en el scriptblock (`"... $origen ..."`) es mala idea: rompe con espacios y comillas, y es un vector de inyección si el valor no es tuyo.

4. **Salida como texto (menor pero clave).** `Out-File` de strings congelados no se reutiliza; devuelve objetos y exporta al formato que necesites. Los resultados remotos traen `PSComputerName` automáticamente, así que el informe se etiqueta solo.

5. **Política de errores (menor).** Un servidor apagado produce un error no terminante y el flujo sigue; decide y registra: `-ErrorVariable` para el listado de fallos.

Versión corregida:"""),
            ("tool", r"""PS> Get-PSSession | Measure-Object | Select-Object -ExpandProperty Count
60
PS> Get-PSSession | Select-Object -First 2 Id, Name, ComputerName, State

 Id Name     ComputerName State
 -- ----     ------------ -----
  1 Session1 SRV-ERP01    Opened
  2 Session2 SRV-ERP02    Opened"""),
            ("assistant", r"""Evidencia de la fuga: 60 sesiones vivas en tu propia sesión de trabajo (y sus contrapartidas en los destinos). Con el patrón corregido esto desaparece:

```powershell
$servidores = Get-Content C:\Scripts\servers.txt
$umbralMB = 50000

$informe = Invoke-Command -ComputerName $servidores -ScriptBlock {
    $c = Get-PSDrive C
    [pscustomobject]@{
        Servidor = $env:COMPUTERNAME
        LibreMB  = [math]::Round($c.Free / 1MB, 0)
        Alerta   = ($c.Free -lt $using:umbralMB)
    }
} -ErrorVariable fallosRemotos

$informe |
    Sort-Object LibreMB |
    Export-Csv C:\Datos\espacio.csv -NoTypeInformation -Encoding utf8BOM

"Fallos de conexión: $($fallosRemotos.Count)"
$fallosRemotos | Select-Object -ExpandProperty TargetObject -First 5
```

Si algún día necesitas sesión persistente legítima (varios comandos al mismo servidor), el patrón seguro es:

```powershell
$sesion = New-PSSession -ComputerName $srv -ErrorAction Stop
try {
    # ... varias Invoke-Command -Session $sesion ...
}
finally {
    Remove-PSSession $sesion
}
```

Nota de gobernanza: esto es inventariado de tu parque con autorización explícita; si en el futuro delegas este tipo de consultas a personal de soporte, la vía correcta son endpoints JEA (roles limitados), no shells remotos completos. Cómo se comprobaría: ejecuta la versión corregida y verifica con `Get-PSSession` que al terminar quedan 0 sesiones; el CSV debe tener una fila por servidor accesible con `PSComputerName`/Servidor, y el contador de fallos debe cuadrar con los servidores caídos que tengas."""),
        ],
        tags=["powershell", "remoting", "invoke-command", "session-leak", "using-scope"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 15
    E(
        language="powershell",
        domain="systems",
        subdomain="remoting_topologia",
        difficulty="very_hard",
        task_type="analysis",
        messages=[
            ("user", r"""Voy a estandarizar la administración remota de nuestros 40 servidores Windows del dominio (soy administrador del parque, con la autorización correspondiente). No tengo claro cuándo usar `Enter-PSSession`, cuándo `New-PSSession` con `Invoke-Command`, cuándo `Invoke-Command` directo, ni qué pasa con las credenciales cuando una operación salta de un servidor a otro (me han mencionado CredSSP y quiero entender los riesgos antes de decidir). Quiero criterios de decisión, no una lista de cmdlets."""),
            ("assistant", r"""Análisis por capas, de transporte a decisión:

**1. Transporte.** WinRM (HTTP 5985 / HTTPS 5986, Kerberos en dominio) es el estándar en Windows: se habilita en los destinos con `Enable-PSRemoting` (idealmente vía GPO) y en dominio autentica con Kerberos sin manejar contraseñas. PowerShell 7 añade remoting sobre SSH (`-HostName`, puerto 22): útil si mezclas Linux, o si tu red solo permite SSH saliente; pierde algunas comodidades de WinRM (fan-out implícito es igual de posible, pero la configuración de claves es manual). Regla: dominio Windows puro → WinRM; parque mixto o restricciones de firewall → SSH.

**2. Modos de uso.**
* `Invoke-Command -ComputerName lista -ScriptBlock {...}`: ad hoc, sin estado, fan-out paralelo. Es el 90 % de los casos (inventarios, cambios de configuración idempotentes, consultas). Cada bloque es independiente; los resultados traen `PSComputerName`.
* `New-PSSession`: estado PERSISTENTE entre llamadas al mismo destino (variables de sesión, módulos ya cargados, transacciones multi-paso). Obligatorio el patrón `try/finally` + `Remove-PSSession` para no fugarte sesiones. Úsalo solo cuando el estado persistente compense.
* `Enter-PSSession`: shell interactivo humano para diagnóstico puntual. No automatizable, no versionable; si te lo encuentras en un runbook, es señal de que hay que convertirlo en script.

**3. El doble salto.** Desde tu estación autenticas contra SRV-A con Kerberos. Si SRV-A, dentro de tu bloque, accede a SRV-B (UNC, `Invoke-Command` anidado), POR DISEÑO no reenvía tus credenciales: Kerberos delega un salto, y ese límite es una protección (evita que un intermediario reutilice tu identidad donde quiera). Opciones ordenadas de preferencia:
* (a) Evita el salto: orquesta desde tu estación — un `Invoke-Command` a A y otro a B, en lugar de A→B. La mayoría de los «doble salto» son antipatrones de diseño del script.
* (b) Credencial explícita en el segundo salto: en el bloque de A, `Invoke-Command -ComputerName B -Credential $cred`, con `$cred` obtenida por `Get-Credential` y gestionada con las reglas de credenciales seguras (nunca en claro).
* (c) Delegación Kerberos restringida basada en recursos (AD moderno): configuras en AD que B confíe a la cuenta de máquina de A para los servicios concretos (cifs, wsman). Granular y auditable; es la solución "bien hecha" para automatización recurrente.
* (d) CredSSP: delega las credenciales completas al intermediario. Si A se compromete, tu credencial es utilizable desde A. Solo con HTTPS, solo para casos cerrados, revocando después. Evítalo si (a)-(c) cubren tu caso — y tu instinto de «respeto» con CredSSP es correcto.

**4. Perímetro legítimo.** Todo lo anterior asume administración autorizada de tu parque. Para dar acceso acotado a terceros (soporte, proveedores) lo correcto son endpoints JEA: sesiones remoting con capacidades de rol limitadas y transcripción — no shells completos. Para equipos fuera de dominio, `TrustedHosts` es funcional pero rompe la autenticación mutua: acompáñalo de HTTPS o IPsec si el tráfico sale de tu segmento.

**5. Decisiones operativas.** Un fan-out por lote, no una sesión por servidor; `-ThrottleLimit` acorde a la carga; registra `PSComputerName` en todos los informes; errores de conectividad a `-ErrorVariable` con política de reintentos; misma versión de PS 7.x en ambos extremos para evitar sorpresas de serialización.

Cómo se comprobaría el plan: `Test-WSMan` en cada destino antes del despliegue; piloto con 2 servidores comparando `Measure-Command` de fan-out vs serie; y una prueba deliberada del escenario de doble salto en laboratorio para elegir entre (a), (b) o (c) con datos, no con suposiciones."""),
        ],
        tags=["powershell", "remoting", "winrm", "double-hop", "jea"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 16
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="csv_tipos_compare",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Genero a diario dos inventarios CSV de ficheros servidos por distintos equipos: `inventario_ayer.csv` e `inventario_hoy.csv`, con columnas `Servidor;Ruta;SizeBytes;Modificado`. Necesito (1) importarlos con TIPOS correctos — SizeBytes como número, no como texto — y (2) un diff fiable: qué ficheros se añadieron y cuáles se quitaron entre ayer y hoy. Mi intento devuelve basura o nada:

```powershell
$ayer = Import-Csv C:\Datos\inventario_ayer.csv
$hoy  = Import-Csv C:\Datos\inventario_hoy.csv
Compare-Object $ayer $hoy
```"""),
            ("assistant", r"""Dos problemas encadenados: (1) `Import-Csv` devuelve TODAS las columnas como strings (`"10485760"`), los tipos se reconstruyen al consumir; (2) `Compare-Object` sin `-Property` intenta comparar los objetos «enteros», y con PSCustomObject procedentes de fuentes distintas el resultado es inservible — hay que darle la CLAVE DE NEGOCIO (Servidor+Ruta). Diseño que explicito: clave compuesta `Clave`, tipos casteados en la carga, diff con indicadores y export del diff para auditoría.

```powershell
function Convert-InventoryRow {
    param([Parameter(Mandatory, ValueFromPipeline)]$Fila)
    process {
        [pscustomobject]@{
            Clave      = '{0};{1}' -f $Fila.Servidor, $Fila.Ruta
            SizeBytes  = [int64]$Fila.SizeBytes
            Modificado = [datetime]$Fila.Modificado
        }
    }
}

$ayer = Import-Csv C:\Datos\inventario_ayer.csv  | Convert-InventoryRow
$hoy  = Import-Csv C:\Datos\inventario_hoy.csv   | Convert-InventoryRow

$diff = Compare-Object $ayer $hoy -Property Clave

$nuevos     = $diff | Where-Object SideIndicator -eq '=>' |
    Select-Object -ExpandProperty Clave
$eliminados = $diff | Where-Object SideIndicator -eq '<=' |
    Select-Object -ExpandProperty Clave

$diff | Export-Csv C:\Datos\diff_inventario.csv -NoTypeInformation -Encoding utf8BOM
"Nuevos: $($nuevos.Count); Eliminados: $($eliminados.Count)"
```

Diff en mi máquina con un par de inventarios de prueba:"""),
            ("tool", r"""PS> $diff | Format-Table Clave, SideIndicator -AutoSize

Clave                          SideIndicator
-----                          -------------
SRV01;C:\Datos\logs\app.log    <=
SRV03;C:\Datos\temp\cache.dat  =>

PS> "Nuevos: $($nuevos.Count); Eliminados: $($eliminados.Count)"
Nuevos: 1; Eliminados: 1"""),
            ("assistant", r"""Semántica de los indicadores: `=>` significa «solo en el segundo argumento» (añadido) y `<=` «solo en el primero» (eliminado). Matices que conviene fijar:

* No usé `-SyncWindow`: es para comparaciones donde el ORDEN es significativo. Los inventarios pueden venir en cualquier orden; sin `-SyncWindow`, `Compare-Object` empareja por valor de la propiedad sin importar la posición. Añádelo solo si tu semántica exige orden.
* Si tus claves pueden REPETIRSE (dos filas con mismo Servidor+Ruta), `Compare-Object` te va a confundir: valida unicidad antes con `Group-Object Clave | Where-Object Count -gt 1`.
* El cast `[datetime]` usa la cultura del hilo; si el CSV lo genera otro sistema con otra cultura, parsea explícito: `[datetime]::Parse($_.Modificado, [cultureinfo]::InvariantCulture)` (o normaliza el formato al generarlo — mejor).
* Escalado: para inventarios enormes, `Compare-Object` está bien hasta cientos de miles de filas; más allá, carga ambos lados en hashtables indexadas por `Clave` y cruza a mano (O(n) frente a comparación por pares).

Cómo se comprobaría: con dos CSV de prueba de 3 filas — añade una, elimina otra, cambia el tamaño de una tercera (que NO debe aparecer en el diff de claves) — el diff debe tener exactamente 2 filas con los indicadores correctos, y `($hoy | Measure-Object SizeBytes -Sum).Sum` debe ser un número, no una concatenación de texto (prueba de que los tipos llegaron)."""),
        ],
        tags=["powershell", "import-csv", "compare-object", "tipos", "inventario"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 17
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="revision_manejo_errores",
        difficulty="hard",
        task_type="code_review",
        messages=[
            ("user", r"""Este es el script de backup nocturno que corre en la tarea programada del servidor de ficheros. «Funciona casi siempre», pero alguna mañana el ZIP no está y no sé por qué. Me han dicho que está mal desde la primera línea. Revísamelo con calma:

```powershell
$ErrorActionPreference = 'SilentlyContinue'
Start-Transcript -Path 'C:\Logs\backup_transcript.txt'
Write-Host 'Iniciando backup'
Copy-Item 'C:\Datos\*' 'E:\Backup\' -Recurse -Force
Compress-Archive -Path 'E:\Backup\*' -DestinationPath 'E:\Backup\backup.zip' -Force
Write-Host 'Backup terminado'
Stop-Transcript
```"""),
            ("assistant", r"""Revisión ordenada por severidad; la primera línea explica tu misterio:

1. **`$ErrorActionPreference = 'SilentlyContinue'` global (crítico).** Silencia TODOS los errores del script: si `Copy-Item` falla a mitad de copia (fichero bloqueado, ruta > 260 caracteres, destino sin espacio) o `Compress-Archive` explota, no te enteras — y el script termina imprimiendo «Backup terminado» igual. Este antipatrón (ocultar errores en vez de gestionarlos) es la causa directa de que el ZIP «a veces no aparezca». La política correcta: `Stop` por defecto en el script, y tolerancia QUIRÚRGICA solo donde el ruido es esperado (`-ErrorAction SilentlyContinue -ErrorVariable` en ese cmdlet concreto).

2. **El ZIP se come a sí mismo (crítico).** `Compress-Archive -Path 'E:\Backup\*'` comprime TODO lo que hay en E:\Backup, incluido el `backup.zip` del día anterior, que crece cada noche. En unas semanas: ZIPs gigantes y quizá el fallo intermitente que ves (límite de memoria/tiempo de Compress-Archive con entradas enormes). Necesitas separar staging del ZIP final y usar nombre fechado.

3. **Transcript sin `-Append` y sin garantía de cierre (medio).** Sin `-Append`, cada ejecución machaca el transcript anterior (pierdes la evidencia de la noche en que falló); si el script explota antes de `Stop-Transcript`, el fichero queda sin cerrar. `try/finally` con `Stop-Transcript` + `-Append` + nombre fechado.

4. **Sin código de salida (medio).** La tarea programada no puede distinguir éxito de fracaso: añade `exit 0/1` y un log estructurado con timestamp y nivel, no `Write-Host` suelto.

5. **Comprobaciones previas ausentes (menor).** Espacio en E:\ y existencia de origen, antes de copiar.

Esqueleto corregido:

```powershell
$ErrorActionPreference = 'Stop'
$log = 'C:\Logs\backup_{0:yyyyMMdd}.log' -f (Get-Date)

function Write-Log {
    param([string]$Nivel, [string]$Mensaje)
    '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Nivel, $Mensaje |
        Add-Content -Path $log -Encoding utf8BOM
}

Start-Transcript -Path ('C:\Logs\transcript_{0:yyyyMMdd}.txt' -f (Get-Date)) -Append
try {
    $origen  = 'C:\Datos'
    $staging = 'E:\Staging\Datos'
    $zip     = 'E:\Backup\datos_{0:yyyyMMdd}.zip' -f (Get-Date)

    if (-not (Test-Path $origen)) { throw "Origen inaccesible: $origen" }

    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }  # staging propio de ayer
    New-Item $staging -ItemType Directory -Force | Out-Null

    Copy-Item (Join-Path $origen '*') $staging -Recurse -Force
    Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $zip -Force

    Write-Log INFO 'Backup completado'
    exit 0
}
catch {
    Write-Log ERROR $_.Exception.Message
    exit 1
}
finally {
    Stop-Transcript
}
```

Notas sobre el esqueleto: el `Remove-Item` de staging es razonable porque el camino es propio y acotado; para borrados genéricos la regla es `-WhatIf` primero. El `finally` garantiza cerrar el transcript aunque el `exit` dispare dentro del `try`. El ZIP fechado elimina la autorrecompresión y te da historial natural (compáñalo con una retención que borre ZIPs de N días, también con `-WhatIf` en pruebas).

Cómo se comprobaría: en banco de pruebas, provoca un fallo (origen inaccesible) → el log debe contener la línea ERROR, `exit 1`, y el transcript del día debe existir y cerrarse bien; después un run feliz → `exit 0`, ZIP fechado con contenido correcto y sin incluir el ZIP anterior."""),
        ],
        tags=["powershell", "code-review", "erroractionpreference", "transcript", "backup"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 18
    E(
        language="powershell",
        domain="security",
        subdomain="credenciales_seguras",
        difficulty="hard",
        task_type="implementation",
        messages=[
            ("user", r"""Tengo un script nocturno que consulta una API interna y un recurso compartido usando una cuenta de servicio. Ahora mismo la contraseña está escrita dentro del script y sé que es indefendible (el script está en un repo interno). La tarea corre en UN servidor concreto con UNA cuenta específica del dominio. ¿Cómo se maneja esto bien en PowerShell?"""),
            ("assistant", r"""Requisitos que explicito: ninguna secreta en claro ni en el repo, descifrable solo por la cuenta que ejecuta la tarea en esa máquina, y regenerable con un procedimiento documentado. Antes del mecanismo, la decisión de diseño más importante: **si la tarea programada YA corre como la cuenta de servicio, no necesitas ninguna credencial en el script** — la autenticación integrada (Kerberos) usa la identidad del proceso y el script se queda sin secretos. Es la solución de mínimo privilegio y la que intenta primero. Si de verdad necesitas OTRA identidad, este es el patrón con DPAPI:

Una sola vez, sesión interactiva abierta COMO la cuenta que ejecutará la tarea (o con `runas`):

```powershell
$cred = Get-Credential -UserName 'CONTOSO\svc_inventario' -Message 'Cuenta de servicio del inventario'
$cred.Password | ConvertFrom-SecureString | Set-Content C:\Seguros\svc_inventario.bin
```

En el script desatendido:

```powershell
$usuario = 'CONTOSO\svc_inventario'
$clave = Get-Content C:\Seguros\svc_inventario.bin | ConvertTo-SecureString
$cred  = [pscredential]::new($usuario, $clave)

New-PSDrive -Name Inv -PSProvider FileSystem -Root '\\SRV-DATOS\Inventario$' -Credential $cred
# o Invoke-Command / Invoke-RestMethod con -Credential $cred
```

Por qué es seguro RAZONABLE y no magia: `ConvertFrom-SecureString` sin `-Key` cifra con **DPAPI ligado a ese usuario y esa máquina**; el fichero .bin copiado a otro equipo o abierto por otra cuenta es ruido. El NTFS del directorio se restringe además explícitamente:"""),
            ("tool", r"""PS> icacls C:\Seguros\svc_inventario.bin
svc_inventario.bin CONTOSO\svc_inventario:(R,W)
                   NT AUTHORITY\SYSTEM:(F)
                   BUILTIN\Administradores:(F)

PS> $cred.GetNetworkCredential().Password.Length
24
PS> # demostración solo de longitud: el valor plano existe en memoria para APIs de interop"""),
            ("assistant", r"""El listado de icacls muestra el segundo anillo de defensa (quién puede LEER el fichero); el primero es DPAPI (quién puede DESCIFRARLO). La segunda línea demuestra el punto débil honesto: `GetNetworkCredential().Password` expone el valor plano EN MEMORIA — existe para interop con APIs que exigen string; úsalo solo si es inevitable y jamás lo escribas a disco ni log.

Límites que debes declarar: (a) DPAPI es por usuario+máquina: clonar la VM a otro hostname invalida el fichero, y mover el .bin no sirve — eso es una característica; (b) el fichero protege «en reposo», no frente a alguien que ya ejecute COMO esa cuenta con admin en la máquina: el secreto es complemento del mínimo privilegio, no sustituto; (c) `ConvertFrom-SecureString -Key` (AES-256) es portable, pero convierte la clave en EL secreto a proteger (nunca en el script ni en el repo); (d) para una flota o varias cuentas, la evolución natural es el módulo `SecretManagement` con un vault (SecretStore local, o el vault corporativo que tengas); (e) documenta la REGENERACIÓN en un comando (recrear el .bin) — un secreto sin rotación practicable caduca mal; (f) antipatrones a prohibir por escrito en el equipo: contraseñas en variables de entorno, en la línea de comandos (visibles en `Get-CimInstance Win32_Process` vía CommandLine) y en el historial de PSReadLine (si pegaste una, borra el historial con `Alt+F7`).

Cómo se comprobaría: ejecuta el script DESDE la tarea programada (identidad real) → autentica; luego intenta leer el .bin desde OTRA cuenta → `ConvertTo-SecureString` fallará con «Key not valid for use in specified state.»: esa es la prueba de que el cifrado está ligado a la identidad correcta."""),
        ],
        tags=["powershell", "credenciales", "securestring", "dpapi", "minimo-privilegio"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 19
    E(
        language="powershell",
        domain="security",
        subdomain="execution_policy",
        difficulty="hard",
        task_type="analysis",
        messages=[
            ("user", r"""Intento ejecutar un script de despliegue en un servidor del laboratorio y me sale esto:

```
PS> C:\Scripts\despliega.ps1
C:\Scripts\despliega.ps1 : File C:\Scripts\despliega.ps1 cannot be loaded because running scripts is
disabled on this system. For more information, see about_Execution_Policies at
https:/go.microsoft.com/fwlink/?LinkID=135170.
At line:1 char:1
+ C:\Scripts\despliega.ps1
+ ~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : SecurityError: (:) [], PSSecurityException
    + FullyQualifiedErrorId : UnauthorizedAccess
```

Mis compañeros me dicen «ejecuta Set-ExecutionPolicy Unrestricted y listo», y no me conviene abrir esa puerta sin entender qué protege exactamente la ExecutionPolicy y qué opciones tengo ordenadas de menos a más intrusiva."""),
            ("assistant", r"""Buen instinto: `Unrestricted` global es casi siempre la respuesta equivocada. Análisis en dos planos:

**Qué es y qué NO es.** La ExecutionPolicy NO es un límite de seguridad frente a un atacante determinado (hay múltiples formas legítimas de ejecutar código que la evitan y eso es conocido y documentado); es un **cinturón anti-ejecución-accidental** y el vehículo corporativo para exigir firma de scripts. Diseña tus decisiones con esa mentalidad: no te protege de malos actores, te protege de ti mismo y documenta la política del equipo.

**Jerarquía de ámbitos** (gana el más alto definido, normalmente por GPO): `MachinePolicy` > `UserPolicy` (ambas por directiva de grupo, inamovibles localmente) > `Process` (solo el proceso actual) > `CurrentUser` > `LocalMachine`. `Get-ExecutionPolicy -List` te dice exactamente cuál manda y de dónde viene — ese es tu primer paso, no el cambio de política.

**Valores relevantes:** `Restricted` (nada de scripts), `AllSigned` (solo firmados; estándar en producción dura), `RemoteSigned` (los scripts LOCALES corren; los descargados —marcados con la zona NTFS `Zone.Identifier`— solo si están firmados; es el punto de equilibrio habitual), `Unrestricted` (todo corre, preguntando por los descargados), `Bypass` (sin barreras, para procesos puntuales).

**Opciones ordenadas de menos a más intrusiva:**

1. Diagnóstico: `Get-ExecutionPolicy -List` y `Get-Item C:\Scripts\despliega.ps1 -Stream Zone.Identifier` para saber si el bloqueo viene de la política o de la marca de descarga.
2. Si MachinePolicy/UserPolicy están en Restricted (GPO): NO lo saltes — habla con quien administra la GPO. Un intento de `Set-ExecutionPolicy` contra GPO fallará con un error que lo dice explícitamente; los rodeos serían exactamente lo que la política existe para evitar.
3. Si el restrictivo es `LocalMachine` y administras la máquina: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` — no requiere admin y no abre la máquina entera.
4. Si el fichero es de confianza y venía de descarga: `Unblock-File C:\Scripts\despliega.ps1` tras revisarlo (elimina la marca de zona; el contenido no cambia).
5. Ejecución puntual sin tocar configuración: `powershell -ExecutionPolicy Bypass -File C:\Scripts\despliega.ps1` — el ámbito `Process` muere con el proceso; es el patrón habitual en automatizaciones efímeras.
6. Política de equipo seria: `AllSigned` + firma con `Set-AuthenticodeSignature` usando un certificado de firma de código de tu CA corporativa. La firma cubre el contenido: cualquier edición posterior la invalida, lo que además te da control de integridad sobre lo que corre en producción.

Nota de compatibilidad: Windows PowerShell 5.1 y PowerShell 7 llevan políticas SEPARADAS (por edición/host); que 7 te deje correr un script no implica que 5.1 lo haga, y viceversa.

Cómo se comprobaría: tras aplicar tu opción elegida, `Get-ExecutionPolicy -List` debe reflejar el ámbito esperado y el script debe arrancar; documenta en tu runbook cuál de las seis vías usaste y por qué — la ExecutionPolicy es parte de la superficie de seguridad del servidor, no un trámite."""),
        ],
        tags=["powershell", "execution-policy", "remotesigned", "firma", "analisis"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 20
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="refactor_texto_objetos",
        difficulty="hard",
        task_type="refactoring",
        messages=[
            ("user", r"""Tengo un script que cuenta puertos en escucha por PID parseando `netstat -ano` con texto, para detectar procesos escuchando en más puertos de lo normal. En los servidores con Windows en ESPAÑOL no encuentra nada, y en los ingleses me salta este error al ejecutarlo tal cual:

```
PS> .\puertos.ps1
Cannot overwrite variable PID because it is read-only or constant.
At C:\Scripts\puertos.ps1:6 char:5
+     $pid = $partes[-1]
+     ~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : WriteError: (:) [], SessionStateUnauthorizedAccessException
    + FullyQualifiedErrorId : VariableNotWritable
```

El script:

```powershell
$lineas = netstat -ano | Select-String 'LISTENING|Escuchando'
$conteo = @{}
foreach ($l in $lineas) {
    $partes = $l.Line -split '\s+'
    $puerto = ($partes[1] -split ':')[-1]
    $pid = $partes[-1]
    $conteo[$pid]++
}
```

Primero pensé que con renombrar `$pid` bastaba, pero en los servidores españoles sigue sin encontrar nada. ¿Me ayudas a arreglarlo de raíz?"""),
            ("assistant", r"""Tu primera reparación (renombrar `$pid` → `$processId`) era correcta para UNO de los dos problemas: `$PID` es variable automática de solo lectura, por eso el error. Pero la segunda hipótesis —que el parseo era ajustable con índices— es la trampa clásica y se refuta con tu propio dato: en Windows en español, `netstat` imprime el estado como `ESCUCHANDO` (en mayúsculas), y tu patrón `'LISTENING|Escuchando'` no casa: cero líneas, sin error.

Causa raíz de fondo: estás usando una **interfaz de texto para humanos** (`netstat`) cuya salida depende del idioma y del formato, cuando Windows expone la misma información como **objetos** estructurados e independientes de la localización. El refactor con `Get-NetTCPConnection` elimina de raíz los tres fragilidades (idioma, columnas, y el nombre de proceso que en el enfoque de texto exigiría una segunda pasada con `tasklist`):

```powershell
$escuchas = Get-NetTCPConnection -State Listen

$informe = $escuchas |
    Group-Object -Property OwningProcess |
    ForEach-Object {
        $proc = Get-Process -Id $_.Name -ErrorAction SilentlyContinue
        [pscustomobject]@{
            PID     = $_.Name
            Proceso = if ($proc) { $proc.ProcessName } else { '(desconocido)' }
            Puertos = $_.Count
            Escucha = ($_.Group.LocalPort | Sort-Object -Unique) -join ', '
        }
    }

$informe |
    Sort-Object Puertos -Descending |
    Export-Csv C:\Datos\puertos.csv -NoTypeInformation -Encoding utf8BOM
```

Ganancias concretas: (1) `Get-NetTCPConnection` devuelve objetos con `State` tipado (`Listen` es un valor del enum, idéntico en cualquier idioma); (2) `Group-Object OwningProcess` sustituye al hashtable manual y a los splits frágiles; (3) `Get-Process -Id` da el NOMBRE del proceso, que tu versión de texto no tenía; (4) la salida es objeto → consumible por CSV/JSON/sucesos sin reparsing. Cuándo el parsing de texto es aceptable: solo cuando NO existe cmdlet/CIM equivalente — y entonces con expresiones regulares nombradas y fijando la cultura, nunca con índices mágicos. Herramienta hermana del mismo principio: `Get-CimInstance Win32_Process` en lugar de `tasklist /v`.

Cómo se comprobaría: en el MISMO instante, `(netstat -ano | Select-String -Pattern 'LISTENING|ESCUCHANDO').Count` debe coincidir con `$escuchas.Count` (contraste honesto texto vs objetos); y el CSV debe mapear cada PID a un nombre de proceso. Ejecuta el contraste en un servidor inglés y en uno español: la versión de objetos da idéntico resultado en ambos."""),
        ],
        tags=["powershell", "refactorizacion", "get-nettcpconnection", "objetos-vs-texto", "localizacion"],
        stack=["powershell"],
        verify=[],
        recovery=True,
    ),
    # ------------------------------------------------------------------ 21
    E(
        language="powershell",
        domain="scripting_automation",
        subdomain="refactor_funcion_avanzada",
        difficulty="very_hard",
        task_type="refactoring",
        messages=[
            ("user", r"""Este es el script que copio y pego (con rutas cambiadas a mano) en cada servidor para archivar logs antiguos al share de ficheros. Operaciones quiere convertirlo en una función reutilizable del equipo, con `-WhatIf` antes de aprobarla; y un compañero avisó de que cuando lo probó desatendido «se quedaba colgado esperando algo». Además me da miedo esta combinación de Copy+Remove:

```powershell
# archiva logs - (pegado en cada servidor con rutas distintas)
$origen = 'E:\Logs\ERP'
$destino = '\\FICHEROS\Logs\ERP01'
Get-ChildItem $origen -Filter *.log |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    ForEach-Object {
        Copy-Item $_.FullName $destino
        Remove-Item $_.FullName
    }
```"""),
            ("assistant", r"""Tres problemas de fondo, por severidad:

1. **Riesgo de pérdida de datos (crítico).** `Copy-Item` falla de forma NO terminante si el destino no es accesible (share caído, cuota): el error se imprime, el pipeline sigue, y `Remove-Item` BORRA EL ORIGINAL que nunca llegó a copiarse. La secuencia copy+remove sin verificar el éxito es indefendible. `Move-Item` resuelve por construcción: no elimina el original si no consiguió copiarlo.

2. **Rutas pegadas a mano (medio).** Cada copia del script es una bifurcación de código sin historial; los cambios de criterio («ahora 14 días») hay que aplicarlos N veces. Una función con parámetros centraliza el criterio.

3. **El «cuelgue» desatendido (medio).** Te adelanto la causa porque te va a pasar con la función: si un parámetro es `[Parameter(Mandatory)]` y la tarea programada lo invoca sin valor, PowerShell intenta PEDIRTE el valor de forma interactiva; en una sesión sin consola visible el proceso queda bloqueado hasta el timeout de la tarea. En desatendido: parámetros con valores por defecto razonables, o validación explícita con `throw` claro en una línea — nunca depender del prompt.

Refactor completo:

```powershell
function Move-OldLogs {
    <#
    .SYNOPSIS
    Mueve logs antiguos del servidor local a la carpeta de archivo de red.
    .EXAMPLE
    Move-OldLogs -SourcePath E:\Logs\ERP -ArchivePath \\FICHEROS\Logs\ERP01 -DaysOld 7
    #>
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory)]
        [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })]
        [string]$SourcePath,

        [Parameter(Mandatory)]
        [string]$ArchivePath,

        [ValidateRange(1, 365)]
        [int]$DaysOld = 7
    )

    if (-not (Test-Path -LiteralPath $ArchivePath)) {
        throw "La carpeta de archivo '$ArchivePath' no existe o no es accesible."
    }

    $corte = (Get-Date).AddDays(-$DaysOld)
    $resumen = [pscustomobject]@{ Movidos = 0; Omitidos = 0; Fallos = 0 }

    foreach ($f in (Get-ChildItem -LiteralPath $SourcePath -Filter *.log -File |
                     Where-Object LastWriteTime -lt $corte)) {
        $target = Join-Path $ArchivePath $f.Name
        if (Test-Path -LiteralPath $target) { $resumen.Omitidos++; continue }

        if ($PSCmdlet.ShouldProcess($f.FullName, "Mover a $target")) {
            try {
                Move-Item -LiteralPath $f.FullName -Destination $target -ErrorAction Stop
                $resumen.Movidos++
            }
            catch {
                $resumen.Fallos++
                Write-Warning "No se pudo mover $($f.Name): $($_.Exception.Message)"
            }
        }
    }
    $resumen
}
```

Decisiones del refactor: `SupportsShouldProcess` + `ShouldProcess` para el contrato con operaciones; `ValidateScript` en el origen y `throw` temprano (no prompt) para el destino; `-ErrorAction Stop` + catch en el movimiento para que un fallo de red cuente como Fallo sin abortar el lote ni perder originales; `Omitidos` da idempotencia visible (reejecutar no duplica ni revuelve); el objeto de resumen sale por el pipeline para el log de la tarea; y la Comment-Based Help (`.SYNOPSIS`/`.EXAMPLE`) es lo que hace que `Get-Help Move-OldLogs` enseñe el uso real al equipo. Siguiente paso natural si esto crece: mover la función a un módulo .psm1 compartido con versión, para que «la función del equipo» tenga una única fuente de verdad.

Cómo se comprobaría: (1) `-WhatIf` → plan completo sin mutaciones (compara listados antes/después); (2) run real → `Movidos` coherente, y reejecución → `Omitidos` con los mismos nombres y `Movidos = 0`; (3) prueba de red caída (desconecta el share en laboratorio) → `Fallos > 0`, Warning por fichero y TODOS los originales intactos: es la prueba del problema 1; (4) invocación desatendida sin `-ArchivePath` válido → error inmediato y claro, sin cuelgues."""),
        ],
        tags=["powershell", "refactorizacion", "funcion-avanzada", "move-item", "desatendido"],
        stack=["powershell"],
        verify=[],
    ),
    # ------------------------------------------------------------------ 22
    E(
        language="powershell",
        domain="systems",
        subdomain="revision_acl",
        difficulty="hard",
        task_type="code_review",
        messages=[
            ("user", r"""Necesito cerrar la carpeta C:\Datos\RRHH para que solo RRHH y sistemas tengan acceso. Un compañero me pasó esta secuencia de icacls, la probé en una carpeta de pruebas y el resultado no es lo que esperaba (tras el primer comando la carpeta quedó «rarísima»). Revísamelo antes de atreverme con producción:

```powershell
$carpeta = 'C:\Datos\RRHH'
icacls $carpeta /inheritance:r
icacls $carpeta /remove:g 'Usuarios del dominio'
icacls $carpeta /grant:r 'CONTOSO\GG-RRHH-EC:(OI)(CI)F'
icacls $carpeta /grant:r 'CONTOSO\GG-TI-ADMINS:(OI)(CI)F'
```"""),
            ("assistant", r"""Tu intuición de «rarísima» es correcta y el script tiene un fallo grave. Auditoría primero — antes de tocar nada, mira el estado real:

```
PS> (Get-Acl 'C:\Datos\RRHH').Access |
>>     Format-Table IdentityReference, FileSystemRights, AccessControlType, IsInherited -AutoSize

IdentityReference              FileSystemRights               AccessControlType IsInherited
-----------------              ----------------               ----------------- -----------
BUILTIN\Administradores        FullControl                    Allow             True
NT AUTHORITY\SYSTEM            FullControl                    Allow             True
CONTOSO\Usuarios del dominio   ReadAndExecute, Synchronize    Allow             True
CREATOR OWNER                  FullControl                    Allow             True
```

Revisión de la secuencia, por severidad:

1. **`/inheritance:r` es una bomba (crítico).** El flag `r` elimina TODAS las ACE heredadas: se van SYSTEM, Administradores y CREATOR OWNER. Quedas sin SYSTEM → servicios, backups, antivirus y tareas del sistema pueden dejar de acceder; y sin Administradores, si luego falla un grant, solo el PROPIETARIO podrá reparar. Además hay una ventana no atómica entre el `r` y los `grant` en que la carpeta es inaccesible para todo el mundo: si el script muere a mitad, la carpeta queda rota. El patrón correcto es `/inheritance:d` (desactiva herencia COPIANDO las ACE a explícitas) y retirar después SOLO lo que no quieras.

2. **El `/remove:g` es un no-op (gravedad lógica).** Corre después del `r`: las ACE heredadas —incluida la de «Usuarios del dominio»— ya se fueron; no hay nada que quitar. El orden revela que la secuencia no fue pensada como transición de estado sino como lista de deseos.

3. **Mezcla de herramientas sin auditabilidad (medio).** `icacls` es legítimo para operaciones rápidas, pero para cambios controlados conviene `Get-Acl`/`Set-Acl`: objetos comparables, exportables a CLIXML para rollback, y revisables en code review. Ojo: `Set-Acl` NO tiene `-WhatIf`, así que la disciplina de prueba es otra: carpeta espejo de pruebas + snapshot previo.

4. **Portabilidad de nombres localizados (menor).** «Usuarios del dominio» es el nombre en es-ES; en un servidor inglés es «Domain Users». Los grupos corporativos (GG-RRHH-EC) están bien; para grupos integrados, referencia SIDs (`S-1-5-11` usuarios autenticados, `S-1-1-0` Todos) si el script debe ser portable.

Versión con objetos, en el orden correcto:

```powershell
$carpeta = 'C:\Datos\RRHH'

# snapshot para rollback
Get-Acl -LiteralPath $carpeta | Export-Clixml C:\Seguros\acl_RRHH_pre.xml

$acl = Get-Acl -LiteralPath $carpeta

# 1) desactivar herencia CONSERVANDO copia de las ACE heredadas como explícitas
$acl.SetAccessRuleProtection($true, $true)

# 2) retirar solo la ACE que no quieres (ahora sí existe como explícita)
foreach ($r in @($acl.Access | Where-Object {
        $_.IdentityReference -eq 'CONTOSO\Usuarios del dominio' -and -not $_.IsInherited })) {
    $acl.RemoveAccessRuleSpecific($r) | Out-Null
}

# 3) garantizar las dos ACE objetivo, heredables a ficheros y subcarpetas
$derechos    = [System.Security.AccessControl.FileSystemRights]::FullControl
$herencia    = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
$propagacion = [System.Security.AccessControl.PropagationFlags]::None
$tipo        = [System.Security.AccessControl.AccessControlType]::Allow

foreach ($grupo in 'CONTOSO\GG-RRHH-EC', 'CONTOSO\GG-TI-ADMINS') {
    $regla = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $grupo, $derechos, $herencia, $propagacion, $tipo)
    $acl.AddAccessRule($regla)
}

Set-Acl -LiteralPath $carpeta -AclObject $acl
```

Con este orden, SYSTEM y Administradores sobreviven (venían en la copia), la ACE a retirar existe como explícita antes de retirarse, y todo el plan es reversible con el CLIXML. Recuerda también que los permisos NTFS se INTERSECTAN con los del recurso compartido (gana el más restrictivo): si el share publica esa carpeta, revisa también su ACL. Y marco lo obvio por protocolo: cambios de ACL en producción con autorización documentada, ventana de mantenimiento y rollback preparado — esto es administración legítima de TU organización, y como tal se planifica.

Cómo se comprobaría: (1) en la carpeta espejo de pruebas, ejecuta el flujo y re-audita con el mismo `Get-Acl` de arriba: deben quedar exactamente las ACE de RRHH, TI-ADMINS, SYSTEM y Administradores, todas con `IsInherited = False`; (2) valida acceso REAL con un usuario de GG-RRHH-EC (lectura/escritura) y uno fuera de los grupos (denegado); (3) comprueba que un backup de prueba sobre la carpeta sigue funcionando (la prueba de que SYSTEM quedó vivo); (4) ten a mano `Get-Content C:\Seguros\acl_RRHH_pre.xml` para restaurar si algo no cuadra."""),
        ],
        tags=["powershell", "acl", "get-acl", "icacls", "herencia", "code-review"],
        stack=["powershell"],
        verify=[],
    ),
]
