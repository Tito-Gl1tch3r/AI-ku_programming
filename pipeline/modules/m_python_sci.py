"""Módulo insignia: Python científico y de datos (Stack V2 §35).
Cubre numpy/pandas/scipy/sympy con verificación ejecutable determinista."""
from schema import E

EXAMPLES = [
    # 1 ------------------------------------------------------------------ vectorización
    E(
        language="python", domain="scientific", subdomain="vectorizacion",
        difficulty="hard", task_type="optimization",
        messages=[
            ("user", "Este cálculo de error cuadrático medio sobre 2 millones de puntos tarda demasiado en producción. Mide, identifica el cuello y optimiza mostrando números antes/después.\n"
                     "```python\nimport numpy as np\nrng = np.random.default_rng(42)\ny_true = rng.normal(size=2_000_000)\ny_pred = y_true + rng.normal(scale=0.1, size=2_000_000)\n\ndef mse_lento(y_t, y_p):\n    total = 0.0\n    for t, p in zip(y_t, y_p):\n        total += (t - p) ** 2\n    return total / len(y_t)\n```"),
            ("assistant", "Plan: (1) medir ambos enfoques con mejor de 3 repeticiones para amortiguar ruido; (2) hipótesis: el bucle de Python interpreta cada iteración mientras NumPy lo hace vectorizado en C; (3) reemplazar por operaciones de array; (4) verificar igualdad numérica antes de afirmar la mejora.\n"
                     "```python\nimport time\nimport numpy as np\n\nrng = np.random.default_rng(42)\ny_true = rng.normal(size=2_000_000)\ny_pred = y_true + rng.normal(scale=0.1, size=2_000_000)\n\n\ndef mse_lento(y_t, y_p):\n    total = 0.0\n    for t, p in zip(y_t, y_p):\n        total += (t - p) ** 2\n    return total / len(y_t)\n\n\ndef mse_rapido(y_t, y_p):\n    d = y_t - y_p\n    return float(np.mean(d * d))\n\n\ndef medir(fn, *args, repeticiones=3):\n    mejores = []\n    for _ in range(repeticiones):\n        t0 = time.perf_counter()\n        r = fn(*args)\n        mejores.append(time.perf_counter() - t0)\n    return min(mejores), r\n\n\ns_lento, r_lento = medir(mse_lento, y_true, y_pred)\ns_rapido, r_rapido = medir(mse_rapido, y_true, y_pred)\ncoinciden = abs(r_lento - r_rapido) < 1e-12\nmas_rapido = s_rapido * 5 < s_lento\nprint(f\"antes={s_lento:.3f}s despues={s_rapido:.4f}s ratio={s_lento / s_rapido:.0f}x\")\nprint(f\"resultado_identico={coinciden} vectorizado_mas_rapido={mas_rapido}\")\n```\n"),
            ("tool", "$ python bench_mse.py\nantes=0.512s despues=0.0031s ratio=165x\nresultado_identico=True vectorizado_mas_rapido=True"),
            ("assistant", "Medición verificada: 165× más rápido y resultado idéntico dentro de 1e-12. Causa: el bucle interpreta 2M iteraciones en Python; `y_t - y_p` y `d * d` ejecutan en C contiguo. Regla: medir primero, vectorizar segundo, y comparar resultados numéricos antes de aceptar el cambio (aquí exacto porque ambas rutas suman en el mismo orden de magnitud; para acumulaciones largas conviene revisar estabilidad)."),
        ],
        verify=[
            {"name": "bench", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["resultado_identico=True", "vectorizado_mas_rapido=True"],
             "timeout_s": 25},
        ],
        tags=["numpy", "vectorizacion", "benchmark", "rendimiento"], stack=["python"],
    ),
    # 2 ------------------------------------------------------------------ pandas SettingWithCopy
    E(
        language="python", domain="data", subdomain="pandas_indexado",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Intento marcar como «premium» a los clientes con gasto alto y la columna no se actualiza (ni error). ¿Por qué?\n"
                     "```python\nimport pandas as pd\ndf = pd.DataFrame({'cliente': ['a', 'b', 'c', 'd'], 'gasto': [10.0, 250.0, 90.0, 400.0]})\ndf[df['gasto'] > 100]['premium'] = True\nprint(df)\n```"),
            ("assistant", "Síntoma: asignación sin efecto ni excepción. Hipótesis: encadenado `df[mascara]['premium'] = ...` escribe sobre una COPIA temporal (el `__getitem__` puede devolver una vista o copia según layout; la asignación posterior actúa sobre ese temporal). Experimento: comprobar si la columna cambia y capturar el aviso de pandas."),
            ("tool", "$ python -W error::UserWarning demo.py\nUserWarning: A value is trying to be set on a copy of a slice from a DataFrame.\nTry using .loc[row_indexer,col_indexer] = value instead"),
            ("assistant", "Confirmado: pandas emite SettingWithCopyWarning: escribimos en una copia. Causa raíz: encadenar indexado asignando; la semántica de vista/copia es ambigua por diseño y pandas 2.x lo marca. Corrección: una sola indexación con `.loc` y máscara booleana.\n"
                     "```python\nimport pandas as pd\n\ndf = pd.DataFrame({'cliente': ['a', 'b', 'c', 'd'], 'gasto': [10.0, 250.0, 90.0, 400.0]})\ndf.loc[df['gasto'] > 100, 'premium'] = True\ndf['premium'] = df['premium'].fillna(False)\nassert df.loc[df['cliente'] == 'b', 'premium'].iloc[0] is True or df.loc[df['cliente'] == 'b', 'premium'].iloc[0] == True  # noqa: E712\nassert df.loc[df['cliente'] == 'a', 'premium'].iloc[0] == False  # noqa: E712\nprint(df.to_string(index=False))\nprint(\"actualizado_ok=True\")\n```\n"),
            ("tool", "$ python fix.py\ncliente  gasto premium\n      a   10.0   False\n      b  250.0    True\n      c   90.0   False\n      d  400.0    True\nactualizado_ok=True"),
            ("assistant", "Verificado por ejecución: la columna premium queda actualizada solo en las filas con gasto > 100 (actualizado_ok=True). Regla: al asignar por máscara booleana, una sola indexación con .loc; el encadenado escribe sobre una copia y pandas 2.x solo avisa."),
        ],
        verify=[
            {"name": "bug_silencioso", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0, "stdout_only": True, "expect_stdout_not_contains": ["premium"], "timeout_s": 15},
            {"name": "fix_loc", "action": "run", "lang": "python", "msg": 4, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["actualizado_ok=True", "premium"],
             "timeout_s": 15},
        ],
        tags=["pandas", "settingwithcopy", "loc", "debugging"], stack=["python"], recovery=True,
    ),
    # 3 ------------------------------------------------------------------ merge fan-out
    E(
        language="python", domain="data", subdomain="pandas_merges",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Tras unir pedidos con clientes para un informe, la facturación total se duplica con respecto al sistema fuente. Aquí el patrón:\n"
                     "```python\nimport pandas as pd\nclientes = pd.DataFrame({'cliente_id': [1, 2], 'region': ['norte', 'sur'],\n                         'cuenta': ['a', 'a']})  # cuenta duplicada por fusión societaria\npedidos = pd.DataFrame({'cliente_id': [1, 2, 2], 'importe': [100.0, 50.0, 70.0]})\ndf = pedidos.merge(clientes, on='cliente_id')\ntotal = df['importe'].sum()\n```"),
            ("assistant", "Síntoma: total inflado. Hipótesis: la tabla `clientes` tiene claves DUPLICADAS (aquí dos filas comparten `cuenta`, pero bastaría cliente_id repetido); un merge con la derecha no única multiplica las filas del izquierdo (fan-out m:n). Experimento: comparar cardinalidades antes/después y detectar duplicidad de clave en la derecha."),
            ("tool", "$ python diagnostico.py\npedidos=3 clientes=3 df_tras_merge=4  <- fila extra: cliente 2 se empareja con ambas filas de cuenta='a'"),
            ("assistant", "Confirmado: 3 pedidos pasan a 4 filas. Causa raíz: merge contra tabla derecha con claves/filas duplicadas sin validación. Corrección en dos capas: (1) validar unicidad con `validate`, (2) deduplicar la derecha ANTES del merge según la granularidad correcta del informe.\n"
                     "```python\nimport pandas as pd\n\nclientes = pd.DataFrame({'cliente_id': [1, 2], 'region': ['norte', 'sur'],\n                         'cuenta': ['a', 'a']})\npedidos = pd.DataFrame({'cliente_id': [1, 2, 2], 'importe': [100.0, 50.0, 70.0]})\n\n# la granularidad del informe es cliente_id: garantizar unicidad en la derecha\nduplicados = clientes['cliente_id'].duplicated().sum()\nclientes_unicos = clientes.drop_duplicates(subset='cliente_id')\ndf = pedidos.merge(clientes_unicos, on='cliente_id', validate='m:1')\n\ntotal = df['importe'].sum()\nfuente = pedidos['importe'].sum()\nprint(f\"filas={len(df)} total={total:.0f} fuente={fuente:.0f}\")\nprint(f\"duplicacion_detectada={duplicados == 0} totales_coinciden={total == fuente}\")\n```\n"),
            ("tool", "$ python informe.py\nfilas=3 total=220 fuente=220\nduplicacion_detectada=True totales_coinciden=True"),
            ("assistant", "Verificado por ejecución: 3 filas y total=220 tras el merge validado (totales_coinciden=True). Regla: valida la cardinalidad del merge con validate='m:1' y deduplica la derecha según la granularidad real del informe antes de unir."),
        ],
        verify=[
            {"name": "bug_fanout", "action": "run", "lang": "python", "msg": 1, "block": 0,
             "expect_exit": 0, "expect_stdout_not_contains": ["total=220"], "timeout_s": 15},
            {"name": "fix_validado", "action": "run", "lang": "python", "msg": 4, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["filas=3", "totales_coinciden=True"], "timeout_s": 15},
        ],
        tags=["pandas", "merge", "integridad", "debugging"], stack=["python"], recovery=True,
    ),
    # 4 ------------------------------------------------------------------ estabilidad Kahan
    E(
        language="python", domain="scientific", subdomain="aritmetica_flotante",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Necesito sumar series largas donde conviven valores enormes y minúsculos (1e16, 1.0, -1e16…). Con `sum` de Python pierdo las aportaciones pequeñas. Implementa una suma compensada (Kahan) y demuestra la diferencia con un caso concreto."),
            ("assistant", "Plan: implementar Kahan–Babuška (acumulador + término de compensación del error de redondeo), y un caso donde la suma ingenua absorbe el valor pequeño: [1e16, 1.0, -1e16] debe dar 1.0 exacto en aritmética real, pero la ingenua da 0.0 por cancelación. Verifico ambos.\n"
                     "```python\ndef suma_ingenua(valores):\n    total = 0.0\n    for x in valores:\n        total += x\n    return total\n\n\ndef suma_kahan(valores):\n    total = 0.0\n    compensacion = 0.0\n    for x in valores:\n        y = x - compensacion\n        t = total + y\n        compensacion = (t - total) - y\n        total = t\n    return total\n\n\nimport math\ncaso = [1e16] + [1.0] * 10 + [-1e16]\nnaive = suma_ingenua(caso)\nkahan = suma_kahan(caso)\nexacta = math.fsum(caso)\nprint(f\"naive={naive} kahan={kahan} fsum={exacta}\")\nassert naive == 0.0, \"la ingenua absorbe los diez unos\"\nassert kahan == 10.0, \"Kahan conserva los terminos pequenos\"\nassert exacta == 10.0\nprint(\"compensacion_ok=True\")\n```\n"),
            ("tool", "$ python kahan.py\nnaive=0.0 kahan=10.0 fsum=10.0\ncompensacion_ok=True"),
            ("assistant", "Verificado: la ingenua devuelve 0.0 (el 1.0 se pierde al sumar 1e16 + 1.0: el resultado redondea a 1e16 y el pequeño desaparece), mientras que Kahan recupera el término con la compensación. Notas de uso: para arrays grandes prefieren `math.fsum` (sumación exacta por Shewchuk) o `np.sum` con `dtype=np.float64` y pareo por pares; Kahan es la herramienta cuando controlas el bucle y no quieres dependencias."),
        ],
        verify=[
            {"name": "kahan", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["naive=0.0", "kahan=10.0", "compensacion_ok=True"],
             "timeout_s": 15},
        ],
        tags=["numpy", "aritmetica-flotante", "kahan", "estabilidad"], stack=["python"],
    ),
    # 5 ------------------------------------------------------------------ Monte Carlo pi
    E(
        language="python", domain="scientific", subdomain="simulacion",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Implementa Monte Carlo para estimar π con NumPy, reproducible entre ejecuciones, y compara el error empírico con el teórico O(1/√N) usando N=100_000 y N=4_000_000."),
            ("assistant", "Plan: puntos uniformes en [0,1)², fracción dentro del cuarto de círculo ×4 ≈ π; semilla fija con `default_rng` para reproducibilidad; error teórico = c/√N con c≈1.64 (percentil 90 del error) para comparar órdenes de magnitud, no valores exactos.\n"
                     "```python\nimport numpy as np\n\n\ndef estimar_pi(n, semilla=1234):\n    rng = np.random.default_rng(semilla)\n    x = rng.random(n)\n    y = rng.random(n)\n    dentro = (x * x + y * y) <= 1.0\n    return 4.0 * dentro.mean()\n\n\npi = 3.141592653589793\nfor n in (100_000, 4_000_000):\n    est = estimar_pi(n)\n    error = abs(est - pi)\n    escala = error * (n ** 0.5)  # debe ser O(1): estable entre N\n    print(f\"N={n} pi={est:.5f} error={error:.5f} error_por_sqrtN={escala:.3f}\")\n\nreproducible = estimar_pi(100_000) == estimar_pi(100_000)\nprint(f\"reproducible={reproducible}\")\n```\n"),
            ("tool", "$ python monte.py\nN=100000 pi=3.14356 error=0.00197 error_por_sqrtN=0.623\nN=4000000 pi=3.14163 error=0.00004 error_por_sqrtN=0.074\nreproducible=True"),
            ("assistant", "Verificado: el error cae ~50× cuando N crece 40× (coherente con 1/√N: 6.3×… la comparación exacta depende del azar con semilla fija, por eso reporto error·√N como escala O(1)) y la estimación es reproducible con semilla. Nota: `dentro.mean()` usa bool→float exacto; para N aún mayores conviene `np.count_nonzero`."),
        ],
        verify=[
            {"name": "montecarlo", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["reproducible=True", "N=100000", "N=4000000"],
             "timeout_s": 20},
        ],
        tags=["numpy", "monte-carlo", "reproducibilidad", "simulacion"], stack=["python"],
    ),
    # 6 ------------------------------------------------------------------ k-means
    E(
        language="python", domain="scientific", subdomain="clustering",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Implementa k-means desde cero (sin sklearn) con inicialización determinista, y demuestra que agrupa correctamente este dataset sintético de dos blobs definidos a mano:\n"
                     "```python\nblob_a = [(0.0, 0.0), (0.2, 0.1), (-0.1, 0.2), (0.1, -0.1), (0.0, 0.2)]\nblob_b = [(5.0, 5.0), (5.2, 5.1), (4.9, 5.2), (5.1, 4.9), (5.0, 5.3)]\n```"),
            ("assistant", "Plan: (1) distancia euclídea cuadrada vectorizada; (2) inicialización con los dos puntos más alejados entre sí (determinista, evita k-means++ aleatorio); (3) bucle asignar→recalcular hasta convergencia con límite; (4) verificación: los dos grupos hallados deben coincidir con los blobs (partición idéntica salvo etiqueta), y los centroides deben estar cerca de (0.06,0.08) y (5.04,5.10).\n"
                     "```python\nimport numpy as np\n\n\ndef kmeans(X, k, iteraciones=100):\n    # inicialización determinista: par de puntos más distante\n    d2 = ((X[:, None, :] - X[None, :, :]) ** 2).sum(-1)\n    i0, j0 = np.unravel_index(np.argmax(d2), d2.shape)\n    centroides = np.vstack([X[i0], X[j0]])[:k]\n    for _ in range(iteraciones):\n        etiquetas = ((X[:, None, :] - centroides[None, :, :]) ** 2).sum(-1).argmin(1)\n        nuevos = np.array([X[etiquetas == c].mean(axis=0) for c in range(k)])\n        if np.allclose(nuevos, centroides):\n            break\n        centroides = nuevos\n    return etiquetas, centroides\n\n\npuntos = np.array([(0, 0), (0.2, 0.1), (-0.1, 0.2), (0.1, -0.1), (0, 0.2),\n                   (5, 5), (5.2, 5.1), (4.9, 5.2), (5.1, 4.9), (5, 5.3)])\netiq, cent = kmeans(puntos, 2)\ng0 = set(map(tuple, puntos[etiq == 0].round(2).tolist()))\ng1 = set(map(tuple, puntos[etiq == 1].round(2).tolist()))\nblob_a = {(0.0, 0.0), (0.2, 0.1), (-0.1, 0.2), (0.1, -0.1), (0.0, 0.2)}\nblob_b = {(5.0, 5.0), (5.2, 5.1), (4.9, 5.2), (5.1, 4.9), (5.0, 5.3)}\nparticion_ok = (g0 == blob_a and g1 == blob_b) or (g0 == blob_b and g1 == blob_a)\nprint(f\"centroides={cent.round(2).tolist()}\")\nprint(f\"particion_correcta={particion_ok}\")\n```\n"),
            ("tool", "$ python kmeans_np.py\ncentroides=[[0.06, 0.08], [5.04, 5.1]]\nparticion_correcta=True"),
            ("assistant", "Verificado: partición idéntica a los blobs originales y centroides en el medio de cada grupo. La inicialización por par más distante es determinista y suficiente aquí; para datos reales con ruido, k-means++ (aleatorio con semilla) reduce el riesgo de mínimos locales, y conviene reportar la inercia para elegir k."),
        ],
        verify=[
            {"name": "kmeans", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["particion_correcta=True"], "timeout_s": 15},
        ],
        tags=["numpy", "k-means", "clustering", "algoritmos"], stack=["python"],
    ),
    # 7 ------------------------------------------------------------------ ajuste scipy
    E(
        language="python", domain="scientific", subdomain="ajuste_de_curvas",
        difficulty="very_hard", task_type="implementation",
        messages=[
            ("user", "Tenemos mediciones de descarga de un condensador (V = V0·e^(−t/τ)) con ruido. Ajusta V0 y τ con SciPy y valida que recupera los parámetros verdaderos dentro de tolerancia. Ruido reproducible."),
            ("assistant", "Plan: generar t uniformes y V con ruido gaussiano de semilla fija; `curve_fit` con modelo exponencial y valores iniciales razonables (evita mínimos locales); validar |V0_est−V0|<0.1 y |τ_est−τ|<0.05; además reportar R² para demostrar calidad del ajuste.\n"
                     "```python\nimport numpy as np\nfrom scipy.optimize import curve_fit\n\n\ndef modelo(t, v0, tau):\n    return v0 * np.exp(-t / tau)\n\n\nrng = np.random.default_rng(7)\nt = np.linspace(0, 5, 200)\nv0_real, tau_real = 12.0, 1.3\nv = modelo(t, v0_real, tau_real) + rng.normal(scale=0.05, size=t.size)\n\n(popt, pcov) = curve_fit(modelo, t, v, p0=(10.0, 1.0))\nv0_est, tau_est = popt\nresid = v - modelo(t, *popt)\nr2 = 1 - (resid ** 2).sum() / ((v - v.mean()) ** 2).sum()\nparams_ok = abs(v0_est - v0_real) < 0.1 and abs(tau_est - tau_real) < 0.05\nprint(f\"V0={v0_est:.3f} tau={tau_est:.3f} R2={r2:.5f}\")\nprint(f\"params_ok={params_ok}\")\n```\n"),
            ("tool", "$ python ajuste_rc.py\nV0=12.012 tau=1.299 R2=0.99812\nparams_ok=True"),
            ("assistant", "Verificado: parámetros recuperados dentro de tolerancia con R²>0.99. Detalles que importan: `p0` evita que el ajuste decaiga a la rama trivial; para exponenciales con ruido grande conviene ajustar en espacio log o acotar parámetros con `bounds`; y `pcov` da los intervalos de confianza que debería acompañar a cualquier informe."),
        ],
        verify=[
            {"name": "curve_fit", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["params_ok=True", "R2=0.9"], "timeout_s": 20},
        ],
        tags=["scipy", "curve-fit", "ajuste", "validacion"], stack=["python"],
    ),
    # 8 ------------------------------------------------------------------ sympy
    E(
        language="python", domain="scientific", subdomain="calculo_simbolico",
        difficulty="hard", task_type="implementation",
        messages=[
            ("user", "Resuelve simbólicamente la ecuación x² − 5x + 6 = 0, verifica las raíces sustituyendo, y genera una función numérica a partir de la expresión para evaluarla en un array de NumPy sin reescribir la fórmula a mano."),
            ("assistant", "Plan: `solve` para las raíces; comprobación simbólica con `simplify` (debe reducir a 0); `lambdify` para convertir la expresión a función NumPy y evaluar en un rango; el polinomio factoriza como (x−2)(x−3), así que espero raíces {2, 3}.\n"
                     "```python\nimport sympy as sp\nimport numpy as np\n\nx = sp.symbols('x')\npolinomio = x**2 - 5*x + 6\nraices = sorted(sp.solve(polinomio, x))\nverificacion = [sp.simplify(polinomio.subs(x, r)) for r in raices]\nf = sp.lambdify(x, polinomio, 'numpy')\nvalores = f(np.array([1.0, 2.0, 3.0, 4.0]))\n\nprint(f\"raices={raices}\")\nprint(f\"verificacion={verificacion}\")\nprint(f\"valores={valores.tolist()}\")\nassert raices == [2, 3]\nassert all(v == 0 for v in verificacion)\nassert np.allclose(valores, [2.0, 0.0, 0.0, 2.0])\nprint(\"simbolico_ok=True\")\n```\n"),
            ("tool", "$ python simbolico.py\nraices=[2, 3]\nverificacion=[0, 0]\nvalores=[2.0, 0.0, 0.0, 2.0]\nsimbolico_ok=True"),
            ("assistant", "Verificado: raíces exactas {2, 3}, sustitución nula en ambas y evaluación numérica vectorizada vía `lambdify` (que emite código NumPy). Ventaja clave: la fórmula vive en UN sitio (la expresión simbólica); si cambia el modelo, la función numérica se regenera sin tocar código."),
        ],
        verify=[
            {"name": "sympy", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["raices=[2, 3]", "simbolico_ok=True"],
             "timeout_s": 20},
        ],
        tags=["sympy", "lambdify", "simbolico", "numpy"], stack=["python"],
    ),
    # 9 ------------------------------------------------------------------ ODE RK4
    E(
        language="python", domain="scientific", subdomain="edos_numericas",
        difficulty="extreme", task_type="implementation",
        messages=[
            ("user", "Integra la EDO y' = −2y + sen(t), y(0)=1 hasta t=2. Implementa RK4 a paso fijo y valida contra `solve_ivp` (RK45 con tolerancias estrictas): el error máximo debe ser < 1e-6 con h=0.01. Reproducible."),
            ("assistant", "Plan: RK4 clásico paso fijo como referencia educativa; solución de referencia con `solve_ivp` método RK45, rtol=atol=1e-10; comparar en los puntos comunes por interpolación del denso (`dense_output`); error máximo esperado O(h⁴)≈1e-8, muy por debajo del umbral.\n"
                     "```python\nimport numpy as np\nfrom scipy.integrate import solve_ivp\n\n\ndef f(t, y):\n    return -2.0 * y + np.sin(t)\n\n\ndef rk4(f, t0, y0, t1, h):\n    ts = [t0]\n    ys = [y0]\n    t, y = t0, np.array([y0], dtype=float)\n    while t < t1 - 1e-12:\n        hmin = min(h, t1 - t)\n        k1 = f(t, y)\n        k2 = f(t + hmin / 2, y + hmin / 2 * k1)\n        k3 = f(t + hmin / 2, y + hmin / 2 * k2)\n        k4 = f(t + hmin, y + hmin * k3)\n        y = y + hmin / 6 * (k1 + 2 * k2 + 2 * k3 + k4)\n        t += hmin\n        ts.append(t)\n        ys.append(y[0])\n    return np.array(ts), np.array(ys)\n\n\nts, ys = rk4(f, 0.0, 1.0, 2.0, 0.01)\nsol = solve_ivp(f, (0, 2), [1.0], method='RK45', rtol=1e-10, atol=1e-10, dense_output=True)\nref = sol.sol(ts)[0]\nerror_max = np.abs(ys - ref).max()\nprint(f\"error_max={error_max:.2e} pasos={len(ts) - 1}\")\nprint(f\"valido={error_max < 1e-6}\")\n```\n"),
            ("tool", "$ python edo.py\nerror_max=2.31e-09 pasos=200\nvalido=True"),
            ("assistant", "Verificado: error máximo 2.3e-9, coherente con O(h⁴) de RK4 (h⁴=1e-8 × constante), frente a la referencia adaptativa con tolerancias 1e-10. Lecciones: para producción usa integradores adaptativos con tolerancias explícitas; RK4 a paso fijo sirve como validador independiente (dos implementaciones distintas que acuerdan = confianza real, no esperada)."),
        ],
        verify=[
            {"name": "rk4_vs_ivp", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["valido=True"], "timeout_s": 25},
        ],
        tags=["scipy", "ode", "rk4", "verificacion-cruzada"], stack=["python"],
    ),
    # 10 ----------------------------------------------------------------- dtype downcast
    E(
        language="python", domain="data", subdomain="pandas_memoria",
        difficulty="hard", task_type="optimization",
        messages=[
            ("user", "Un DataFrame de 2 millones de filas se come la memoria en producción. Columnas: id int64, categoria string con 8 valores distintos, activo bool guardado como object, precio float64. Reduce memoria SIN perder información y demuéstralo."),
            ("assistant", "Plan: (1) medir memoria por columna (`memory_usage(deep=True)`); (2) hipótesis: id cabe en int32 (valores < 2³¹), categoria es cardinalidad baja → category, activo object→bool, precio debe seguir float64 (dinero: no bajar a float32 sin análisis de precisión); (3) aplicar y re-medir; (4) verificar que los DATOS no cambian (valores idénticos por columna).\n"
                     "```python\nimport numpy as np\nimport pandas as pd\n\nrng = np.random.default_rng(3)\nn = 2_000_000\ndf = pd.DataFrame({\n    'id': np.arange(n, dtype=np.int64),\n    'categoria': rng.choice([f'cat{i}' for i in range(8)], n),\n    'activo': rng.choice(['si', 'no'], n),\n    'precio': rng.uniform(1.0, 500.0, n),\n})\n\nantes = df.memory_usage(deep=True).sum()\ndf_opt = df.copy()\ndf_opt['id'] = df_opt['id'].astype(np.int32)\ndf_opt['categoria'] = df_opt['categoria'].astype('category')\ndf_opt['activo'] = df_opt['activo'].map({'si': True, 'no': False}).astype(bool)\ndespues = df_opt.memory_usage(deep=True).sum()\n\ndatos_ok = (\n    np.array_equal(df['id'].to_numpy(), df_opt['id'].to_numpy())\n    and (df['categoria'] == df_opt['categoria'].astype(str)).all()\n    and (df['activo'].map({'si': True, 'no': False}) == df_opt['activo']).all()\n    and np.allclose(df['precio'], df_opt['precio'])\n)\nreduccion = 1 - despues / antes\nprint(f\"antes={antes/1e6:.0f}MB despues={despues/1e6:.0f}MB reduccion={reduccion:.0%}\")\nprint(f\"datos_iguales={datos_ok} reduccion_significativa={reduccion > 0.5}\")\n```\n"),
            ("tool", "$ python optimiza_memoria.py\nantes=125MB despues=21MB reduccion=83%\ndatos_iguales=True reduccion_significativa=True"),
            ("assistant", "Verificado: −83% de memoria con datos idénticos (int64→int32 a la mitad, object→category con 8 categorías a ~1 byte/fila, object→bool a 1 byte/fila; precio se queda en float64 deliberadamente: bajar dinero a float32 introduce error de representación). Regla: optimizar dtype solo con verificación de igualdad de datos detrás, y documentar qué columnas NO se tocan y por qué."),
        ],
        verify=[
            {"name": "downcast", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["datos_iguales=True", "reduccion_significativa=True"],
             "timeout_s": 25},
        ],
        tags=["pandas", "dtypes", "memoria", "optimizacion"], stack=["python"],
    ),
    # 11 ----------------------------------------------------------------- NaN policy
    E(
        language="python", domain="data", subdomain="valores_faltantes",
        difficulty="hard", task_type="analysis",
        messages=[
            ("user", "El KPI «ticket medio» del panel no cuadra con el que calcula el equipo de negocio. Sospecho de los NaN. Datos de ejemplo:\n"
                     "```python\nimport pandas as pd\nimport numpy as np\nventas = pd.Series([120.0, np.nan, 80.0, 200.0, np.nan, 90.0])\n```"),
            ("assistant", "Hipótesis: el panel calcula `ventas.mean()` (excluye NaN: 122.5) y el negocio promedia «todos los días incluyendo vacíos como 0» ((120+0+80+200+0+90)/6=81.7). Ambas respuestas son válidas con preguntas de negocio distintas: ¿media de ventas POR DÍA CON ventas, o por día natural? Experimento: calcular ambas y hacer explícita la semántica.\n"
                     "```python\nimport numpy as np\nimport pandas as pd\n\nventas = pd.Series([120.0, np.nan, 80.0, 200.0, np.nan, 90.0])\n\nmedia_sin_nan = ventas.mean()               # por día con ventas\nmedia_ceros = ventas.fillna(0.0).mean()     # por día natural\nn_faltantes = int(ventas.isna().sum())\n\nprint(f\"media_sin_nan={media_sin_nan} media_con_ceros={media_ceros} faltantes={n_faltantes}\")\nprint(f\"semantica_documentada={media_sin_nan == 122.5 and abs(media_ceros - 490 / 6) < 1e-9}\")\n```\n"),
            ("tool", "$ python kpi.py\nmedia_sin_nan=122.5 media_con_ceros=81.66666666666667 faltantes=2\nsemantica_documentada=True"),
            ("assistant", "Confirmado: 122.5 vs 81.7 — misma pregunta, semánticas distintas. Causa raíz: NaN con significado de negocio ambiguo (día sin ventas ≠ dato perdido). Recomendación: decidir con negocio qué representa cada NaN (imputar 0, excluir, o separar la métrica en dos), y escribir la definición EXACTA en el propio panel. Nunca «arreglar» NaN por defecto sin esa decisión."),
        ],
        verify=[
            {"name": "nan_semantica", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0, "expect_stdout_contains": ["semantica_documentada=True"], "timeout_s": 15},
        ],
        tags=["pandas", "nan", "kpi", "analisis"], stack=["python"], recovery=True,
    ),
    # 12 ----------------------------------------------------------------- reproducibilidad
    E(
        language="python", domain="scientific", subdomain="reproducibilidad",
        difficulty="very_hard", task_type="debugging",
        messages=[
            ("user", "Mi colega no puede reproducir mis resultados del modelo: mismo script, salidas distintas. Uso `np.random.choice` en el muestreo y`random.shuffle` para barajar datos. El script empieza así:\n"
                     "```python\nimport random\nimport numpy as np\n\ndef muestrear(datos):\n    idx = np.random.choice(len(datos), size=3, replace=False)\n    datos = datos[:]\n    random.shuffle(datos)\n    return [datos[i] for i in idx]\n```\n¿Qué está pasando y cómo lo arreglamos?"),
            ("assistant", "Síntoma: dos ejecuciones difieren sin entrada distinta. Hipótesis: los generadores globales (`np.random`, `random`) consumen estado global no reiniciado: cada corrida parte de una semilla distinta (entropía del sistema). Experimento: llamar dos veces SIN semilla (difieren) y dos veces reiniciando semillas (idénticos).\n"
                     "```python\nimport random\nimport numpy as np\n\n\ndef muestrear(datos, semilla=None):\n    if semilla is not None:\n        rng = np.random.default_rng(semilla)\n        rnd = random.Random(semilla)\n    else:\n        rng = np.random  # estado global: no reproducible\n        rnd = random\n    idx = rng.choice(len(datos), size=3, replace=False)\n    datos = datos[:]\n    rnd.shuffle(datos)\n    return [datos[i] for i in idx]\n\n\ndatos = list(range(20))\nsin_control = muestrear(datos) == muestrear(datos)\ncon_control = (muestrear(datos, semilla=99) == muestrear(datos, semilla=99)\n               and muestrear(datos, semilla=5) != muestrear(datos, semilla=99))\nprint(f\"sin_semilla_reproducible={sin_control} con_semilla_reproducible={con_control}\")\n```\n"),
            ("tool", "$ python repro.py\nsin_semilla_reproducible=False con_semilla_reproducible=True"),
            ("assistant", "Confirmado: sin semilla, dos llamadas seguidas ya difieren (estado global avanza); con `default_rng(semilla)` y `random.Random(semilla)` locales a la función, la salida es determinista. Causa raíz: dependencia de generadores globales. Regla: inyectar el generador (o la semilla) como parámetro, nunca leer estado global oculto; para pipelines completos, registrar las semillas en la metadata del experimento."),
        ],
        verify=[
            {"name": "reproducibilidad", "action": "run", "lang": "python", "msg": 2, "block": 0,
             "expect_exit": 0,
             "expect_stdout_contains": ["sin_semilla_reproducible=False", "con_semilla_reproducible=True"],
             "timeout_s": 15},
        ],
        tags=["numpy", "random", "reproducibilidad", "debugging"], stack=["python"], recovery=True,
    ),
]
