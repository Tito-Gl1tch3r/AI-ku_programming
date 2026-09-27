"""
validate_module.py — Autochequeo de un módulo de ejemplos.

Uso:
    cd /home/z/my-project/aiku_programming/pipeline
    python3 validate_module.py modules/m_ejemplo.py

Comprueba (en seco, sin ejecutar código):
  * el módulo expone EXAMPLES (lista no vacía)
  * cada ejemplo pasa validate_record (vocabularios, roles, secretos, plan verify)
  * duplicados internos (exactos y aproximados)
Salida: informe + código de salida 0 (ok) / 1 (errores).
"""

import importlib.util
import os
import sys
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import validate_record, blocks_of  # noqa: E402


def load_module(path):
    spec = importlib.util.spec_from_file_location("m_" + os.path.basename(path).replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def norm(s):
    return " ".join((s or "").split()).lower()


def main(path):
    mod = load_module(path)
    examples = getattr(mod, "EXAMPLES", None)
    if not isinstance(examples, list) or not examples:
        print(f"[ERROR] {path}: no expone EXAMPLES (lista no vacía)")
        return 1

    n_err = n_warn = 0
    seen_exact = {}
    users = []
    total = 0
    dist = {"difficulty": {}, "task_type": {}, "language": {}}

    for i, rec in enumerate(examples):
        rec["_module"] = os.path.basename(path)
        rec["_index"] = i
        total += 1
        try:
            errors, warnings = validate_record(rec)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] ejemplo {i}: excepción en validación: {exc}")
            n_err += 1
            continue
        for e in errors:
            print(f"[ERROR] ejemplo {i}: {e}")
            n_err += 1
        for w in warnings:
            print(f"[AVISO] ejemplo {i}: {w}")
            n_warn += 1

        # user content para dedupe aproximado
        u = next((m["content"] for m in rec["messages"] if m["role"] == "user"), "")
        users.append((i, norm(u)[:600]))
        key = hash(norm(u) + norm(rec["messages"][-1]["content"]))
        if key in seen_exact:
            print(f"[ERROR] ejemplo {i}: duplicado exacto del ejemplo {seen_exact[key]}")
            n_err += 1
        else:
            seen_exact[key] = i

        for field in dist:
            v = rec.get(field)
            dist[field][v] = dist[field].get(v, 0) + 1

    # dedupe aproximado O(n^2) con bail-out barato
    for a in range(len(users)):
        ia, ta = users[a]
        for b in range(a + 1, len(users)):
            ib, tb = users[b]
            if abs(len(ta) - len(tb)) > 0.35 * max(len(ta), len(tb), 1):
                continue
            r = SequenceMatcher(None, ta, tb).real_quick_ratio()
            if r < 0.93:
                continue
            r = SequenceMatcher(None, ta, tb).ratio()
            if r >= 0.93:
                print(f"[ERROR] ejemplos {ia} y {ib}: posible duplicado (similitud {r:.3f} en el enunciado)")
                n_err += 1

    print("-" * 60)
    print(f"Módulo: {path}")
    print(f"Ejemplos: {total} | errores: {n_err} | avisos: {n_warn}")
    for field, d in dist.items():
        print(f"  {field}: " + ", ".join(f"{k}={v}" for k, v in sorted(d.items(), key=lambda kv: str(kv[0]))))
    print("RESULTADO: " + ("OK" if n_err == 0 else "FALLO — corrige los errores"))
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("uso: python3 validate_module.py modules/<modulo>.py")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
