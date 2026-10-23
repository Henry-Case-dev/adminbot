"""Build a read-only reduced copy of prod DB (tables used by the resolver).

Run on prod with a python that can load sqlite_vec. Source opened mode=ro.
"""
import json
import os
import sqlite3
import sys

SRC = "/var/www/admin_bot/local_database.db"
DST = os.path.join(sys.argv[1], "copy.db")
TABLES = [
    ("mca_embedding_index_generations", "entity"),
    ("graph_facts", "entity"),
    ("graph_facts_vec", "vec"),
    ("smart_archive_facts", "entity"),
    ("smart_archive", "vec"),
]
VEC_COLS = {
    "graph_facts_vec": ["embedding", "fact_id", "chat_id",
                        "origin", "expires_at"],
    "smart_archive": ["embedding", "fact_id", "chat_id"],
}
# `embedding_i8` — производная coarse-колонка (int8); sqlite-vec 0.1.9 не даёт
# перезаписать её прочитанным значением, а резолвер/проба/KNN читают только
# `embedding` (float). Для копии колонка опускается; исходный DDL пишется в meta.
DROP_COL_SQL = "embedding_i8 int8[3072], "

import sqlite_vec

dst = sqlite3.connect(DST)
dst.enable_load_extension(True)
dst.load_extension(sqlite_vec.loadable_path())
try:
    dst.load_extension(sqlite_vec.loadable_path(), entrypoint="sqlite3_vec_init")
except Exception:
    pass
print("VEC", dst.execute("select vec_version()").fetchone()[0])
dst.enable_load_extension(False)

src = sqlite3.connect("file:%s?mode=ro" % SRC, uri=True, timeout=30)
src.enable_load_extension(True)
src.load_extension(sqlite_vec.loadable_path())
src.enable_load_extension(False)
src.execute("PRAGMA query_only=ON")

meta = {"query_only_src": src.execute("PRAGMA query_only").fetchone()[0],
        "vec_version": dst.execute("select vec_version()").fetchone()[0],
        "tables": {}}
for name, kind in TABLES:
    row = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                      (name,)).fetchone()
    ddl = row[0] if row else None
    meta["tables"][name] = {"ddl": ddl}
    if not ddl:
        meta["tables"][name]["skipped"] = "no_ddl"
        continue
    create_sql = ddl.replace(DROP_COL_SQL, "") if kind == "vec" else ddl
    dst.execute(create_sql)
    if kind == "vec":
        cols = VEC_COLS[name]
        sel = "rowid, " + ", ".join(cols)
        ins = "INSERT INTO %s(rowid, %s) VALUES (%s)" % (
            name, ", ".join(cols), ", ".join("?" for _ in range(len(cols) + 1)))
    else:
        cols = [r[1] for r in src.execute("PRAGMA table_info(%s)" % name)]
        sel = ", ".join(cols)
        ins = "INSERT INTO %s(%s) VALUES (%s)" % (
            name, sel, ", ".join("?" for _ in range(len(cols))))
    cur = src.execute("SELECT %s FROM %s" % (sel, name))
    total = 0
    while True:
        batch = cur.fetchmany(400)
        if not batch:
            break
        dst.executemany(ins, [tuple(r) for r in batch])
        total += len(batch)
    dst.commit()
    n_src = src.execute("SELECT count(*) FROM %s" % name).fetchone()[0]
    n_dst = dst.execute("SELECT count(*) FROM %s" % name).fetchone()[0]
    meta["tables"][name].update({"src_rows": n_src, "dst_rows": n_dst})
    print("TABLE", name, n_src, n_dst)

try:
    meta["task_jobs"] = [dict(zip(("id", "kind", "status", "reason",
                                   "created_at", "updated_at"), r))
                         for r in src.execute(
        "SELECT id, kind, status, reason, created_at, updated_at FROM task_jobs "
        "WHERE kind LIKE '%embedding%' OR kind LIKE '%graphrag%' "
        "ORDER BY id DESC LIMIT 20")]
except Exception as exc:
    meta["task_jobs_err"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])

meta["counts_src"] = {}
for name, _kind in TABLES:
    try:
        meta["counts_src"][name] = src.execute(
            "SELECT count(*) FROM %s" % name).fetchone()[0]
    except Exception as exc:
        meta["counts_src"][name] = "err:%s" % type(exc).__name__
meta["dst_size"] = os.path.getsize(DST)
with open(os.path.join(sys.argv[1], "meta.json"), "w", encoding="utf-8") as fh:
    json.dump(meta, fh, ensure_ascii=False, indent=1, default=str)
dst.close()
src.close()
print("COPY_OK")
