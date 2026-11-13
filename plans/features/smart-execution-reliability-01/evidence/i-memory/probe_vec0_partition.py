"""Probe: sqlite-vec 0.1.9 vec0 partition key / metadata filter support."""
import json
import sqlite3

import sqlite_vec


def connect():
    con = sqlite3.connect(":memory:")
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.row_factory = sqlite3.Row
    return con


def unit(i, dim=8):
    v = [0.0] * dim
    v[i % dim] = 1.0
    return v


def report(label, fn):
    try:
        print(label, "=>", fn())
    except Exception as exc:  # noqa: BLE001 - probe
        print(label, "=> ERROR", type(exc).__name__, str(exc)[:300])


con = connect()
print("vec_version", con.execute("select vec_version()").fetchone()[0])

# 1) partition key column
report("create partition-key table", lambda: con.execute(
    "CREATE VIRTUAL TABLE t_part USING vec0("
    "embedding float[8] distance_metric=cosine, "
    "chat_id integer partition key, +fact_id integer)"
).fetchall())

rows = [(1, unit(0), 0), (1, unit(1), 1), (2, unit(0), 2), (2, unit(0), 3),
        (2, unit(0), 4)]
for chat, vec, fid in rows:
    con.execute("INSERT INTO t_part(chat_id, embedding, fact_id) VALUES (?,?,?)",
                (chat, json.dumps(vec), fid))

report("KNN partition filter chat=2", lambda: [dict(r) for r in con.execute(
    "SELECT fact_id, distance FROM t_part WHERE embedding MATCH ? AND k = ? "
    "AND chat_id = ?", (json.dumps(unit(0)), 2, 2)).fetchall()])
report("KNN partition filter chat=1", lambda: [dict(r) for r in con.execute(
    "SELECT fact_id, distance FROM t_part WHERE embedding MATCH ? AND k = ? "
    "AND chat_id = ?", (json.dumps(unit(0)), 2, 1)).fetchall()])

# 2) metadata column (non-aux) as filter inside KNN
report("create metadata-col table", lambda: con.execute(
    "CREATE VIRTUAL TABLE t_meta USING vec0("
    "embedding float[8] distance_metric=cosine, chat_id integer)"
).fetchall())
for chat, vec in [(1, unit(0)), (2, unit(0)), (2, unit(0))]:
    con.execute("INSERT INTO t_meta(chat_id, embedding) VALUES (?,?)",
                (chat, json.dumps(vec)))
report("KNN metadata filter chat=1", lambda: [dict(r) for r in con.execute(
    "SELECT rowid, chat_id, distance FROM t_meta WHERE embedding MATCH ? "
    "AND k = ? AND chat_id = ?", (json.dumps(unit(0)), 2, 1)).fetchall()])

# 3) auxiliary column in WHERE (expected unsupported)
report("create aux table", lambda: con.execute(
    "CREATE VIRTUAL TABLE t_aux USING vec0("
    "embedding float[8] distance_metric=cosine, +chat_id integer)"
).fetchall())
for chat, vec in [(1, unit(0)), (2, unit(0))]:
    con.execute("INSERT INTO t_aux(chat_id, embedding) VALUES (?,?)",
                (chat, json.dumps(vec)))
report("KNN aux filter chat=1", lambda: [dict(r) for r in con.execute(
    "SELECT rowid, distance FROM t_aux WHERE embedding MATCH ? AND k = ? "
    "AND chat_id = ?", (json.dumps(unit(0)), 2, 1)).fetchall()])

# 4) plain scalar distance scan over vec0 table with aux (no MATCH)
report("scalar vec_distance_cosine scan aux", lambda: [dict(r) for r in con.execute(
    "SELECT rowid, vec_distance_cosine(embedding, ?) AS d FROM t_aux "
    "WHERE chat_id = ? ORDER BY d LIMIT 2",
    (json.dumps(unit(0)), 1)).fetchall()])
report("scalar vec_distance_cosine scan aux count", lambda: con.execute(
    "SELECT count(*) FROM t_aux").fetchone()[0])
