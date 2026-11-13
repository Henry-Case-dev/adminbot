"""Benchmark: current global staged KNN vs rowid-scoped KNN on real local data."""
import json
import sqlite3
import time

import sqlite_vec

PATH = r"C:\Code\Python\adminbot\local_database_2026-09-04_history.db"
con = sqlite3.connect(f"file:{PATH}?mode=ro", uri=True)
con.enable_load_extension(True)
sqlite_vec.load(con)
con.row_factory = sqlite3.Row

# real query vector of the archive (same space/dim)
row = con.execute("select embedding from graph_facts_vec limit 1").fetchone()
raw = row["embedding"]
if isinstance(raw, (bytes, bytearray, memoryview)):
    blob = bytes(raw)
    floats = list(__import__("struct").unpack(f"<{len(blob) // 4}f", blob))
elif isinstance(raw, str):
    floats = json.loads(raw)
else:
    floats = list(raw)
vec = json.dumps(floats)
print("query bytes", len(vec), "dims", len(floats))


def timed(label, sql, params, repeat=3):
    best = None
    rows = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        rows = con.execute(sql, params).fetchall()
        dt = (time.perf_counter() - t0) * 1000
        best = dt if best is None else min(best, dt)
    print(f"{label}: rows={len(rows)} best={best:.1f} ms")
    return rows


CHAT_SMALL = 5885953495
CHAT_TINY = 1313107079

# 1) current current-pipeline global KNN at cap 512 (approx staged final attempt)
timed("global KNN k=512", "SELECT fact_id, chat_id, origin, expires_at, distance "
      "FROM graph_facts_vec WHERE embedding MATCH ? AND k = ?", (vec, 512))
timed("global KNN k=20", "SELECT fact_id, chat_id, origin, expires_at, distance "
      "FROM graph_facts_vec WHERE embedding MATCH ? AND k = ?", (vec, 20))

# 2) exact scoped KNN through rowid IN subquery
timed("scoped small chat k=20", "SELECT v.fact_id, v.chat_id, v.distance "
      "FROM graph_facts_vec v WHERE v.embedding MATCH ? AND v.k = ? "
      "AND v.rowid IN (SELECT id FROM graph_facts WHERE chat_id = ?)",
      (vec, 20, CHAT_SMALL))
timed("scoped tiny chat k=20", "SELECT v.fact_id, v.chat_id, v.distance "
      "FROM graph_facts_vec v WHERE v.embedding MATCH ? AND v.k = ? "
      "AND v.rowid IN (SELECT id FROM graph_facts WHERE chat_id = ?)",
      (vec, 20, CHAT_TINY))
timed("scoped big chat k=20", "SELECT v.fact_id, v.chat_id, v.distance "
      "FROM graph_facts_vec v WHERE v.embedding MATCH ? AND v.k = ? "
      "AND v.rowid IN (SELECT id FROM graph_facts WHERE chat_id = ?)",
      (vec, 20, -1002661910336))
timed("scoped big chat k=40", "SELECT v.fact_id, v.chat_id, v.distance "
      "FROM graph_facts_vec v WHERE v.embedding MATCH ? AND v.k = ? "
      "AND v.rowid IN (SELECT id FROM graph_facts WHERE chat_id = ?)",
      (vec, 40, -1002661910336))

# 3) what the current global-overfetch sees for small chat / tiny chat
for chat, want in ((CHAT_SMALL, 10), (CHAT_TINY, 10)):
    rows = con.execute(
        "SELECT fact_id, chat_id FROM graph_facts_vec WHERE embedding MATCH ? "
        "AND k = ?", (vec, 512)).fetchall()
    own = [r for r in rows if r["chat_id"] == chat]
    print(f"global k=512 for chat {chat}: total={len(rows)} own={len(own)} "
          f"want={want} partial={len(own) < want}")
