"""
verify.py — Harness de verificación ejecutable del dataset AI-ku_programming.

Ejecuta los planes de verificación (`_verify_plan`) de cada ejemplo contra el
código contenido en sus bloques cercados, en sandboxes temporales aislados,
y produce el objeto `verification` del dataset.

Uso:
    python3 verify.py <results.json> [modules/m_*.py ...]
    python3 verify.py <results.json> --all
    python3 verify.py <results.json> --resample 0.15   # re-ejecuta el 15% sin caché

El results.json acumula resultados indexados por hash de contenido del
ejemplo, de modo que re-ejecuciones solo procesan ejemplos nuevos o cambiados.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import blocks_of  # noqa: E402

HARNESS_VERSION = "aiku-verify 1.0"
SANDBOX_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tmp", "verify")
MAX_OUT = 200_000

EXT = {"python": ".py", "bash": ".sh", "js": ".js", "php": ".php", "c": ".c",
       "cpp": ".cpp", "java": ".java", "sql": ".sql", "html": ".html",
       "text": ".txt"}

COMPILE_CMD = {
    "c": ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra"],
    "cpp": ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra"],
}


def have(tool):
    return shutil.which(tool) is not None


TOOLCHAIN = {
    "python": sys.executable,
    "gcc": have("gcc"),
    "g++": have("g++"),
    "node": have("node"),
    "php": have("php"),
    "javac": have("javac"),
    "java": have("java"),
    "bash": have("bash"),
}


def tool_missing(lang, action):
    if lang == "python":
        return None
    if lang == "bash":
        return None if TOOLCHAIN["bash"] else "bash no disponible"
    if lang == "js":
        return None if TOOLCHAIN["node"] else "node no disponible"
    if lang == "c":
        return None if TOOLCHAIN["gcc"] else "gcc no disponible"
    if lang == "cpp":
        return None if TOOLCHAIN["g++"] else "g++ no disponible"
    if lang == "php":
        return None if TOOLCHAIN["php"] else "php no disponible en el entorno de construcción"
    if lang == "java":
        return None if (TOOLCHAIN["javac"] and TOOLCHAIN["java"]) else "javac/java no disponibles (solo JRE)"
    if lang == "sql":
        return None  # stdlib sqlite3
    if lang == "html":
        if action == "html_check" and not TOOLCHAIN["node"]:
            return "node no disponible para validar scripts"
        return None
    return None


def run_cmd(cmd, cwd, stdin_text="", timeout=10):
    try:
        p = subprocess.run(cmd, cwd=cwd, input=stdin_text, text=True,
                           capture_output=True, timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or "", None
    except subprocess.TimeoutExpired as e:
        out = e.stdout or b""
        err = e.stderr or b""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        return None, out, err, "timeout"
    except FileNotFoundError:
        return None, "", "", "tool_missing"


def clip(s, n=2000):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + f"\n…[+{len(s)-n} chars]"


def get_block(rec, msg_idx, blk_idx):
    msgs = rec["messages"]
    m = msgs[msg_idx]
    blks = blocks_of(m["content"])
    if blk_idx >= len(blks):
        raise KeyError(f"block {blk_idx} fuera de rango en mensaje {msg_idx}")
    return blks[blk_idx][1]


def write_fixtures(cwd, fixtures):
    for f in fixtures or []:
        name = os.path.basename(f.get("name", "fixture.txt"))
        with open(os.path.join(cwd, name), "w", encoding="utf-8") as fh:
            fh.write(f.get("content", ""))


def do_compile(lang, src_path, args, cwd, timeout):
    base = COMPILE_CMD.get(lang)
    if base is None:
        if lang == "java":
            cmd = ["javac", src_path]
        else:
            raise ValueError(lang)
    else:
        cmd = base + list(args or []) + [src_path, "-o", "bin"]
    return run_cmd(cmd, cwd, timeout=timeout)


def run_binary(lang, cwd, args, stdin_text, timeout):
    if lang in ("c", "cpp"):
        cmd = ["./bin"] + list(args or [])
    elif lang == "java":
        main = "Main"
        cmd = ["java", "-cp", cwd, main] + list(args or [])
    else:
        raise ValueError(lang)
    return run_cmd(cmd, cwd, stdin=stdin_text if False else stdin_text, timeout=timeout)


SQL_SPLIT = re.compile(r";[ \t]*(?:\r?\n|$)")


def do_sql(cwd, main_sql, setup_sqls, expect_note):
    # isolation_level=None => autocommit controlado por el propio SQL:
    # permite BEGIN/COMMIT/ROLLBACK explícitos de los ejemplos de transacciones
    con = sqlite3.connect(":memory:", isolation_level=None)
    out = []
    err = None
    try:
        for label, src in [("setup", s) for s in setup_sqls] + [("main", main_sql)]:
            for stmt in [s.strip() for s in SQL_SPLIT.split(src) if s.strip()]:
                short = " ".join(stmt.split())[:80]
                try:
                    cur = con.execute(stmt)
                except sqlite3.Error as exc:
                    err = f"SQL error en ({label}) «{short}»: {exc}"
                    out.append(f"ERROR: {exc}")
                    break
                if cur.description:
                    rows = cur.fetchmany(200)
                    out.append(f"SQL> {short}")
                    for row in rows:
                        out.append("|".join("" if v is None else str(v) for v in row))
                    out.append(f"({len(rows)} filas)")
                else:
                    out.append(f"OK ({label}): {short}")
            if err:
                break
        con.commit()
    finally:
        con.close()
    return "\n".join(out), err


def do_html_check(src, tmpdir):
    if not re.search(r"<!DOCTYPE\s+html", src, re.I):
        return False, "falta <!DOCTYPE html>", True
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S | re.I)
    for i, code in enumerate(scripts):
        if not code.strip():
            continue
        p = os.path.join(tmpdir, f"inline_{i}.js")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(code)
        rc, _, err, tk = run_cmd(["node", "--check", p], tmpdir, timeout=10)
        if rc != 0:
            return False, f"script en línea {i} con error de sintaxis: {clip(err, 400)}", True
    return True, f"DOCTYPE ok; {len(scripts)} script(s) en línea con sintaxis válida", True


def exec_step(step, rec, tmpdir):
    """Ejecuta un paso del plan. Devuelve dict {name, passed, detail, executed, tool}."""
    name = step.get("name", "paso")
    action = step["action"]
    lang = step["lang"]
    timeout = min(int(step.get("timeout_s", 10)), 30)
    repeat = max(1, int(step.get("repeat", 1)))
    args = list(step.get("args") or [])
    stdin_text = step.get("stdin", "")

    miss = tool_missing(lang, action)
    if miss:
        return {"name": name, "passed": True, "executed": False, "tool": lang,
                "detail": f"NO EJECUTADO: {miss}"}

    src = get_block(rec, step.get("msg", -1), step.get("block", 0))
    fname = step.get("filename") or ("Main.java" if lang == "java" else "main" + EXT.get(lang, ".txt"))
    src_path = os.path.join(tmpdir, os.path.basename(fname))
    with open(src_path, "w", encoding="utf-8") as fh:
        fh.write(src)
    write_fixtures(tmpdir, step.get("fixtures"))

    exp_exit = step.get("expect_exit", 0)
    exp_fail = bool(step.get("expect_fail", False))
    exp_cf = bool(step.get("expect_compile_fail", False))
    has_pos = step.get("expect_stdout_contains") or []
    has_neg = step.get("expect_stdout_not_contains") or []

    stdout_only = bool(step.get("stdout_only", False))

    def eval_expect(rc, out, err, tk):
        text = (out or "") if stdout_only else (out or "") + "\n" + (err or "")
        problems = []
        if exp_cf:
            okc = (rc is not None and rc != 0) or tk == "timeout"
            return okc, ("compilación falló como se esperaba" if okc else "se esperaba fallo de compilación y compiló OK")
        if exp_fail:
            observed = (rc is None and tk == "timeout") or (rc is not None and rc != 0)
            if observed:
                how = "timeout" if rc is None else f"exit {rc}"
                return True, f"fallo observado como se esperaba ({how})"
            return False, f"se esperaba fallo pero terminó con exit {rc}"
        if rc is None:
            problems.append(f"timeout tras {timeout}s")
        elif rc != exp_exit:
            problems.append(f"exit {rc} != esperado {exp_exit}")
        for s in has_pos:
            if s not in text:
                problems.append(f"falta en salida: {s!r}")
        for s in has_neg:
            if s in text:
                problems.append(f"aparece en salida (no debería): {s!r}")
        return not problems, "; ".join(problems) or "salida conforme a lo esperado"

    # ---- acciones
    if action == "syntax":
        if lang == "python":
            cmd = [sys.executable, "-m", "py_compile", src_path]
        elif lang == "bash":
            cmd = ["bash", "-n", src_path]
        elif lang == "js":
            cmd = ["node", "--check", src_path]
        elif lang == "php":
            cmd = ["php", "-l", src_path]
        else:
            return {"name": name, "passed": False, "executed": False, "tool": lang,
                    "detail": "syntax no soportada para este lenguaje"}
        rc, out, err, tk = run_cmd(cmd, tmpdir, timeout=timeout)
        passed = rc == 0
        return {"name": name, "passed": passed, "executed": True, "tool": lang,
                "detail": ("sintaxis OK" if passed else f"error de sintaxis: {clip(err or out, 400)}")}

    if action == "compile":
        rc, out, err, tk = do_compile(lang, src_path, step.get("cargs") or [], tmpdir, timeout)
        passed, detail = eval_expect(rc, out, err, tk)
        return {"name": name, "passed": passed, "executed": True, "tool": lang,
                "detail": clip(detail + ((" | " + (err or "")[:300]) if err and not passed else ""))}

    if action in ("run", "compile_run"):
        if lang in ("c", "cpp", "java"):
            # cargs = flags del compilador; args = argumentos del programa
            rc, cout, cerr, tk = do_compile(lang, src_path, step.get("cargs") or [], tmpdir, timeout)
            if action == "compile":
                return {"name": name, "passed": rc == 0, "executed": True, "tool": lang,
                        "detail": clip("compila OK" if rc == 0 else "fallo de compilación: " + (cerr or cout), 600)}
            if rc != 0:
                return {"name": name, "passed": False, "executed": True, "tool": lang,
                        "detail": clip("no compila: " + (cerr or cout), 600)}
        results = []
        for _ in range(repeat):
            if lang == "python":
                cmd = [sys.executable, src_path] + args
            elif lang == "bash":
                cmd = ["bash", src_path] + args
            elif lang == "js":
                cmd = ["node", src_path] + args
            elif lang == "php":
                cmd = ["php", src_path] + args
            elif lang in ("c", "cpp", "java"):
                cmd = (["./bin"] if lang in ("c", "cpp") else ["java", "-cp", ".", "Main"]) + args
            else:
                return {"name": name, "passed": False, "executed": False, "tool": lang,
                        "detail": f"run no soportado para {lang}"}
            rc, out, err, tk = run_cmd(cmd, tmpdir, stdin_text=stdin_text, timeout=timeout)
            results.append(eval_expect(rc, out, err, tk))
        if exp_fail and repeat > 1:
            passed = any(r[0] for r in results)
            detail = ("fallo reproducido en alguna de "
                      f"{repeat} ejecuciones: " + next((r[1] for r in results if r[0]), "—")
                      if passed else
                      f"ninguna de {repeat} ejecuciones falló como se esperaba")
        else:
            passed = all(r[0] for r in results)
            detail = next((r[1] for r in results if not r[0]), f"OK en {repeat} ejecución(ones)")
        return {"name": name, "passed": passed, "executed": True, "tool": lang, "detail": clip(detail, 600)}

    if action == "sql":
        setup_sqls = []
        for pair in step.get("setup") or []:
            setup_sqls.append(get_block(rec, pair[0], pair[1]))
        out, err = do_sql(tmpdir, src, setup_sqls, step)
        if err:
            return {"name": name, "passed": False, "executed": True, "tool": "sql", "detail": clip(err, 600)}
        text = out
        problems = []
        for s in has_pos:
            if s not in text:
                problems.append(f"falta en salida SQL: {s!r}")
        for s in has_neg:
            if s in text:
                problems.append(f"aparece en salida SQL (no debería): {s!r}")
        return {"name": name, "passed": not problems, "executed": True, "tool": "sql",
                "detail": clip("; ".join(problems) or "consultas ejecutadas y salida conforme", 600)}

    if action == "html_check":
        passed, detail, executed = do_html_check(src, tmpdir)
        return {"name": name, "passed": passed, "executed": executed, "tool": "html", "detail": clip(detail, 400)}

    return {"name": name, "passed": False, "executed": False, "tool": lang,
            "detail": f"acción desconocida: {action}"}


def content_hash(rec):
    h = hashlib.sha256()
    h.update(json.dumps([m["content"] for m in rec["messages"]], ensure_ascii=False).encode())
    h.update(json.dumps(rec.get("_verify_plan", [])).encode())
    return h.hexdigest()


def verify_record(rec, force=False):
    """Devuelve (verification_dict, drop_reason_or_None)."""
    plan = rec.get("_verify_plan") or []
    steps = []
    executed_any = False
    hard_fail = None
    for k, step in enumerate(plan):
        with tempfile.TemporaryDirectory(prefix=f"aiku_{uuid.uuid4().hex[:8]}_", dir=SANDBOX_ROOT) as tmpdir:
            try:
                r = exec_step(step, rec, tmpdir)
            except Exception as exc:  # noqa: BLE001
                r = {"name": step.get("name", f"paso{k}"), "passed": False, "executed": True,
                     "tool": step.get("lang", "?"), "detail": f"excepción del harness: {exc}"}
        steps.append(r)
        if r["executed"]:
            executed_any = True
            if not r["passed"]:
                hard_fail = f"paso '{r['name']}' falló: {r['detail']}"

    ok = hard_fail is None
    n_pass = sum(1 for s in steps if s["passed"])
    verification = {
        "executed": executed_any,
        "steps": [{"name": s["name"], "passed": s["passed"], "executed": s["executed"],
                   "detail": s["detail"]} for s in steps],
        "summary": (f"{n_pass}/{len(steps)} comprobaciones superadas"
                    + ("" if executed_any else " (entorno sin toolchain para este lenguaje)")),
        "harness": HARNESS_VERSION,
    }
    if not plan:
        verification["executed"] = False
        verification["summary"] = "ejemplo analítico/ conceptual sin verificación ejecutable aplicable"
        verification["steps"] = []
        return verification, None
    return verification, (None if ok else hard_fail)


def record_worker(args):
    rec, force = args
    try:
        ver, drop = verify_record(rec, force=force)
    except Exception as exc:  # noqa: BLE001
        ver, drop = {"executed": False, "steps": [], "summary": f"error del harness: {exc}",
                     "harness": HARNESS_VERSION}, f"error del harness: {exc}"
    return content_hash(rec), ver, drop


def main():
    results_path = sys.argv[1]
    rest = sys.argv[2:]
    resample = 0.0
    if "--resample" in rest:
        i = rest.index("--resample")
        resample = float(rest[i + 1])
        rest = rest[i:i] + rest[i + 2:]

    os.makedirs(SANDBOX_ROOT, exist_ok=True)
    cache = {}
    if os.path.exists(results_path):
        with open(results_path, encoding="utf-8") as fh:
            cache = json.load(fh)

    # recolectar ejemplos de los módulos indicados
    import importlib.util
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    targets = []
    for arg in rest:
        if arg == "--all":
            mdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")
            paths = [os.path.join(mdir, f) for f in sorted(os.listdir(mdir)) if f.endswith(".py")]
        else:
            paths = [arg]
        for p in paths:
            spec = importlib.util.spec_from_file_location("vm_" + os.path.basename(p).replace(".py", ""), p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for i, rec in enumerate(getattr(mod, "EXAMPLES", [])):
                rec["_module"] = os.path.basename(p)
                rec["_index"] = i
                targets.append(rec)

    todo, reused = [], 0
    for rec in targets:
        h = content_hash(rec)
        if h in cache and resample == 0.0:
            reused += 1
        else:
            todo.append(rec)

    print(f"ejemplos: {len(targets)} | en caché: {reused} | a verificar: {len(todo)}")
    drops = []
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2) * 2)) as ex:
        futs = {ex.submit(record_worker, (rec, resample > 0)): rec for rec in todo}
        done = 0
        for fut in as_completed(futs):
            h, ver, drop = fut.result()
            cache[h] = ver
            rec = futs[fut]
            done += 1
            if drop:
                drops.append((rec["_module"], rec["_index"], drop))
            if done % 25 == 0:
                print(f"  … {done}/{len(todo)} verificados, {len(drops)} descartes")

    tmp = results_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)
    os.replace(tmp, results_path)

    print("-" * 60)
    print(f"verificación completa: {len(targets)} ejemplos, {len(drops)} descartes")
    for mod, idx, why in drops[:40]:
        print(f"  DROP {mod}#{idx}: {clip(why, 160)}")
    if len(drops) > 40:
        print(f"  … y {len(drops) - 40} descartes más")
    return 0


if __name__ == "__main__":
    sys.exit(main())
