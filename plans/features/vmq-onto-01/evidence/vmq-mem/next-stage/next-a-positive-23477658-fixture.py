"""Fixture for the C2-auto lexical-row mechanism check.

Inserts ONE synthetic 2023 fact into a derivative DB copy (never the source
copy) and indexes it in the external-content FTS. The fact is not an archive
row: it exists only to exercise the REAL `_rag_unified_rows` lexical path for
the exact C2 question (the archive has no 2023-2024 row with >=2 shared stems).

Recorded limitation: the row has no `graph_facts_vec` entry, so the vector leg
cannot find it — the row is reachable lexically only.
"""
import os, sqlite3, sys, datetime, hashlib

SRC_DB = os.environ["SRC_DB"]
DERIV = os.environ["DERIV"]
FACT_TEXT = os.environ.get(
    "FACT_TEXT", "Михаил сейчас строил планы на выходные и звал всех в баню")
CHAT = -1002661910336
TS = int(datetime.datetime(2023, 5, 13, 18, 0,
                           tzinfo=datetime.timezone.utc).timestamp())


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if os.path.exists(DERIV):
    os.remove(DERIV)
src = sqlite3.connect("file:%s?mode=ro" % SRC_DB.replace("\\", "/"), uri=True)
dst = sqlite3.connect(DERIV)
with dst:
    src.backup(dst)
src.close()
cur = dst.execute(
    "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
    "message_timestamp, status, kind, weight) "
    "VALUES (?, ?, 'history_import', ?, ?, 'confirmed', 'fact', 0.5)",
    (CHAT, FACT_TEXT, TS, TS))
fact_id = cur.lastrowid
dst.execute("INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
            (fact_id, FACT_TEXT))
dst.commit()
print("fixture fact_id=%s ts=%s text=%s" % (fact_id, TS, FACT_TEXT))
print("fixture_db", DERIV, "bytes", os.path.getsize(DERIV),
      "sha256", sha(DERIV))
dst.close()
