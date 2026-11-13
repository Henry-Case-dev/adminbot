"""Probe: rowid IN pre-filter inside vec0 KNN (sqlite-vec 0.1.9)."""
import json
import sqlite3

import sqlite_vec

con = sqlite3.connect(":memory:")
con.enable_load_extension(True)
sqlite_vec.load(con)
con.row_factory = sqlite3.Row


def unit(i, dim=8):
    v = [0.0] * dim
    v[i % dim] = 1.0
    return v


con.execute("CREATE VIRTUAL TABLE t USING vec0("
            "embedding float[8] distance_metric=cosine, +chat_id integer, "
            "+fact_id integer)")
con.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY, chat_id INTEGER, fact TEXT)")
mapping = {1: 1, 2: 1, 3: 2, 4: 2, 5: 2}
vectors = {1: unit(0), 2: unit(1), 3: unit(0), 4: unit(0), 5: unit(0)}
for fid, chat in mapping.items():
    con.execute("INSERT INTO facts(id, chat_id, fact) VALUES (?,?,?)",
                (fid, chat, f"fact {fid}"))
    con.execute("INSERT INTO t(rowid, embedding, chat_id, fact_id) VALUES (?,?,?,?)",
                (fid, json.dumps(vectors[fid]), chat, fid))


def report(label, sql, params):
    try:
        print(label, "=>", [dict(r) for r in con.execute(sql, params).fetchall()])
    except Exception as exc:  # noqa: BLE001
        print(label, "=> ERROR", type(exc).__name__, str(exc)[:300])


q = json.dumps(unit(0))
report("global k=2", "SELECT rowid, fact_id, distance FROM t "
       "WHERE embedding MATCH ? AND k = ?", (q, 2))
report("rowid IN literal chat1", "SELECT rowid, fact_id, distance FROM t "
       "WHERE embedding MATCH ? AND k = ? AND rowid IN (1, 2)", (q, 2))
report("rowid IN subquery chat1", "SELECT rowid, fact_id, distance FROM t "
       "WHERE embedding MATCH ? AND k = ? AND rowid IN "
       "(SELECT id FROM facts WHERE chat_id = 1)", (q, 2))
report("rowid IN subquery chat2 k=2", "SELECT rowid, fact_id, distance FROM t "
       "WHERE embedding MATCH ? AND k = ? AND rowid IN "
       "(SELECT id FROM facts WHERE chat_id = 2)", (q, 2))
report("rowid IN empty", "SELECT rowid, fact_id, distance FROM t "
       "WHERE embedding MATCH ? AND k = ? AND rowid IN "
       "(SELECT id FROM facts WHERE chat_id = 99)", (q, 2))
report("rowid IN + aux read", "SELECT rowid, chat_id, fact_id, distance FROM t "
       "WHERE embedding MATCH ? AND k = ? AND rowid IN (3, 4, 5)", (q, 2))

# int8 column + rowid IN
con.execute("CREATE VIRTUAL TABLE t8 USING vec0("
            "embedding float[8] distance_metric=cosine, embedding_i8 int8[8], "
            "+chat_id integer, +fact_id integer)")
for fid, chat in mapping.items():
    con.execute(
        "INSERT INTO t8(rowid, embedding, embedding_i8, chat_id, fact_id) "
        "VALUES (?,?,vec_quantize_int8(?, 'unit'),?,?)",
        (fid, json.dumps(vectors[fid]), json.dumps(vectors[fid]), chat, fid))
report("int8 rowid IN subquery chat1", "SELECT rowid, fact_id, distance FROM t8 "
       "WHERE embedding_i8 MATCH vec_quantize_int8(?, 'unit') AND k = ? "
       "AND rowid IN (SELECT id FROM facts WHERE chat_id = 1)", (q, 2))

# EXPLAIN to see scan plan
try:
    plan = con.execute(
        "EXPLAIN QUERY PLAN SELECT rowid FROM t WHERE embedding MATCH ? AND k = ? "
        "AND rowid IN (SELECT id FROM facts WHERE chat_id = 1)", (q, 2)).fetchall()
    print("plan =>", [dict(r) for r in plan])
except Exception as exc:  # noqa: BLE001
    print("plan => ERROR", type(exc).__name__, str(exc)[:200])
