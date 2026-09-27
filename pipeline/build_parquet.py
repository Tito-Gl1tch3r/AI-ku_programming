"""
build_parquet.py — Construye el Parquet final único del dataset AI-ku_programming.

Pasos:
  1. Carga todos los módulos de modules/*.py (orden determinista).
  2. Valida cada registro (esquema) y descarta los inválidos con motivo.
  3. Verifica con el harness (caché en .tmp/verify_results.json) y descarta fallos.
  4. Deduplica (exacto + aproximado).
  5. Asigna ids deterministas y splits (train 92% / val 5% / test 3%).
  6. Rellena provenance/verification/tags y escribe data/AI-ku_programming.parquet.
  7. Escribe docs/stats.json y calcula el checksum SHA-256.

Uso:  python3 build_parquet.py
"""

import hashlib
import json
import os
import sys
from collections import Counter
from difflib import SequenceMatcher

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import validate_record  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(BASE)
MODULES_DIR = os.path.join(BASE, "modules")
RESULTS = os.path.join(REPO, ".tmp", "verify_results.json")
OUT_PARQUET = os.path.join(REPO, "data", "AI-ku_programming.parquet")
OUT_STATS = os.path.join(REPO, "docs", "stats.json")

CREATED = "2026-09-28"
PIPELINE = "AI-ku Programming Pipeline v2.0 (authored + executed-verified)"

COLUMNS = ["id", "split", "language", "stack", "domain", "subdomain",
           "difficulty", "task_type", "messages", "verification",
           "provenance", "tags"]


def norm(s):
    return " ".join((s or "").split()).lower()


def content_key(rec):
    u = next((m["content"] for m in rec["messages"] if m["role"] == "user"), "")
    return norm(u)[:800] + "||" + norm(rec["messages"][-1]["content"])[:800]


def main():
    os.makedirs(os.path.dirname(OUT_PARQUET), exist_ok=True)
    os.makedirs(os.path.dirname(OUT_STATS), exist_ok=True)

    with open(RESULTS, encoding="utf-8") as fh:
        vcache = json.load(fh)

    # ---- carga y validación
    records = []
    invalid = []
    for fname in sorted(f for f in os.listdir(MODULES_DIR) if f.endswith(".py")):
        import importlib.util
        path = os.path.join(MODULES_DIR, fname)
        spec = importlib.util.spec_from_file_location("bm_" + fname.replace(".py", ""), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for i, rec in enumerate(getattr(mod, "EXAMPLES", [])):
            rec["_module"] = fname
            rec["_index"] = i
            errors, _ = validate_record(rec)
            if errors:
                invalid.append((fname, i, "; ".join(errors[:3])))
            else:
                records.append(rec)
    print(f"cargados: {len(records)} válidos, {len(invalid)} inválidos")
    for m, i, e in invalid[:30]:
        print(f"  INVALID {m}#{i}: {e}")

    # ---- verificación (usar caché del harness)
    kept, dropped = [], []
    for rec in records:
        from verify import content_hash
        h = content_hash(rec)
        ver = vcache.get(h)
        if ver is None:
            dropped.append((rec["_module"], rec["_index"], "sin verificación (no estaba en caché)"))
            continue
        rec["_verification"] = ver
        had_plan = bool(rec.get("_verify_plan"))
        if had_plan and not ver.get("steps"):
            dropped.append((rec["_module"], rec["_index"], "plan de verificación sin resultados"))
            continue
        failed = [s for s in ver.get("steps", []) if s.get("executed") and not s.get("passed")]
        if failed:
            dropped.append((rec["_module"], rec["_index"],
                            f"verificación fallida: {failed[0]['name']} — {failed[0]['detail'][:120]}"))
            continue
        kept.append(rec)
    print(f"tras verificación: {len(kept)} conservados, {len(dropped)} descartados")
    for m, i, d in dropped[:30]:
        print(f"  DROP {m}#{i}: {d}")

    # ---- deduplicación exacta + aproximada
    seen, corpus = {}, []
    dupes = 0
    for rec in kept:
        k = content_key(rec)
        if k in seen:
            dupes += 1
            continue
        seen[k] = rec
        corpus.append(rec)

    def near_dup(prune_target):
        users = [(r, content_key(r)[:800]) for r in prune_target]
        removed = set()
        for a in range(len(users)):
            ra, ta = users[a]
            if id(ra) in removed:
                continue
            for b in range(a + 1, len(users)):
                rb, tb = users[b]
                if id(rb) in removed:
                    continue
                if abs(len(ta) - len(tb)) > 0.3 * max(len(ta), len(tb), 1):
                    continue
                sm = SequenceMatcher(None, ta, tb)
                if sm.real_quick_ratio() < 0.92:
                    continue
                if sm.ratio() >= 0.92:
                    removed.add(id(rb))
        out = [r for r in prune_target if id(r) not in removed]
        return out, len(removed)

    corpus, near_removed = near_dup(corpus)
    dupes += near_removed
    print(f"tras deduplicación: {len(corpus)} ejemplos ({dupes} duplicados eliminados)")

    # ---- ids, splits, tags, provenance
    corpus.sort(key=lambda r: (r["language"], r["domain"], r["subdomain"], r["_module"], r["_index"]))

    def split_of(rec_id):
        n = int(hashlib.sha1(rec_id.encode()).hexdigest(), 16) % 1000
        return "train" if n < 920 else ("val" if n < 970 else "test")

    rows = []
    for i, rec in enumerate(corpus):
        rid = f"aiku-prog-{i:05d}"
        tags = list(dict.fromkeys(rec.get("tags") or []))
        stack = list(dict.fromkeys(rec.get("stack") or [rec["language"]]))
        if len(stack) > 1:
            tags.append("stack-v2")
        if rec.get("_recovery"):
            tags.append("error-recovery")
        tags.append("verified-executed" if rec["_verification"].get("executed") else "verified-static")
        tags = list(dict.fromkeys(tags))

        rec["id"] = rid
        rec["split"] = split_of(rid)
        rec["verification"] = rec["_verification"]
        rec["provenance"] = {
            "origin": "original",
            "method": "authored + executed-verification harness",
            "sources": [],
            "license": "MIT",
            "created": CREATED,
            "pipeline": PIPELINE,
        }
        rec["tags"] = tags
        rows.append({c: rec[c] for c in COLUMNS})

    # ---- esquema Arrow explícito
    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("split", pa.string()),
        pa.field("language", pa.string()),
        pa.field("stack", pa.list_(pa.string())),
        pa.field("domain", pa.string()),
        pa.field("subdomain", pa.string()),
        pa.field("difficulty", pa.string()),
        pa.field("task_type", pa.string()),
        pa.field("messages", pa.list_(pa.struct([("role", pa.string()), ("content", pa.string())]))),
        pa.field("verification", pa.struct([
            ("executed", pa.bool_()),
            ("steps", pa.list_(pa.struct([("name", pa.string()), ("passed", pa.bool_()), ("detail", pa.string())]))),
            ("summary", pa.string()),
            ("harness", pa.string()),
        ])),
        pa.field("provenance", pa.struct([
            ("origin", pa.string()), ("method", pa.string()), ("sources", pa.list_(pa.string())),
            ("license", pa.string()), ("created", pa.string()), ("pipeline", pa.string()),
        ])),
        pa.field("tags", pa.list_(pa.string())),
    ])

    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, OUT_PARQUET, compression="zstd")

    # ---- checksum + estadísticas
    hsh = hashlib.sha256()
    with open(OUT_PARQUET, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            hsh.update(chunk)

    def dist(field):
        return dict(Counter(r[field] for r in corpus).most_common())

    def has_tag(rec, t):
        return t in rec["tags"]

    def pct(fn):
        return round(100.0 * sum(1 for r in corpus if fn(r)) / max(1, len(corpus)), 2)

    tokens_est = int(sum(len(m["content"]) for r in corpus for m in r["messages"]) / 4)

    stats = {
        "dataset": "AI-ku_programming",
        "version": "2.0",
        "created": CREATED,
        "total_examples": len(corpus),
        "tokens_estimate": tokens_est,
        "tokens_method": "aprox. chars/4 sobre role=content",
        "duplicates_removed": dupes,
        "invalid_records_rejected": len(invalid),
        "verification_failed_rejected": len(dropped),
        "checksum_sha256_parquet": hsh.hexdigest(),
        "parquet_bytes": os.path.getsize(OUT_PARQUET),
        "dist_language": dist("language"),
        "dist_domain": dist("domain"),
        "dist_difficulty": dist("difficulty"),
        "dist_task_type": dist("task_type"),
        "dist_split": dist("split"),
        "pct_executed": pct(lambda r: r["verification"]["executed"]),
        "pct_with_testing": pct(lambda r: r["task_type"] == "testing" or any("test" in t for t in r["tags"])),
        "pct_with_debugging": pct(lambda r: r["task_type"] == "debugging" or "debugging" in r["tags"]),
        "pct_with_tool_calling": pct(lambda r: any(m["role"] == "tool" for m in r["messages"])),
        "pct_agentic": pct(lambda r: r["domain"] == "agentic" or "agentic" in r["tags"]),
        "pct_multidisciplinary": pct(lambda r: len(set(r["stack"])) > 1),
        "pct_error_recovery": pct(lambda r: "error-recovery" in r["tags"]),
        "modules_used": sorted({r["_module"] for r in corpus}),
    }
    with open(OUT_STATS, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)

    print("-" * 60)
    print(f"Parquet: {OUT_PARQUET} ({stats['parquet_bytes']} bytes)")
    print(f"Ejemplos: {stats['total_examples']} | tokens aprox: {tokens_est:,}")
    print(f"SHA-256: {stats['checksum_sha256_parquet']}")
    print(f"Lenguajes: {stats['dist_language']}")
    print(f"Dificultad: {stats['dist_difficulty']}")
    print(f"Ejecutados: {stats['pct_executed']}% | debugging: {stats['pct_with_debugging']}% "
          f"| tool: {stats['pct_with_tool_calling']}% | agentic: {stats['pct_agentic']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
