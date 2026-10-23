# a0-probe remote export + KNN responder (read-only).
# Runs on prod with the project venv (sqlite_vec). Never writes to the DB:
# connection is opened with mode=ro and PRAGMA query_only=ON.
import base64
import json
import os
import sqlite3
import sys
import time
import zlib

OUT = sys.stdout


def emit(tag, payload):
    OUT.write(tag + " " + json.dumps(payload, ensure_ascii=False) + "\n")
    OUT.flush()


try:
    import sqlite_vec
except Exception as exc:  # pragma: no cover
    emit("ERR", {"reason": "import sqlite_vec: %s" % exc})
    raise SystemExit(9)

DB = os.environ.get("A0_DB", "/var/www/admin_bot/local_database.db")
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=15.0)
con.row_factory = sqlite3.Row
con.enable_load_extension(True)
con.load_extension(sqlite_vec.loadable_path())
con.enable_load_extension(False)
con.execute("PRAGMA query_only=ON")
qonly = con.execute("PRAGMA query_only").fetchone()[0]

ddl_row = con.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts_vec'"
).fetchone()
ddl = ddl_row["sql"] if ddl_row else ""
live_rows = con.execute("SELECT count(*) c FROM graph_facts_vec").fetchone()["c"]
source_rows = con.execute("SELECT count(*) c FROM graph_facts").fetchone()["c"]
import re as _re
_m = _re.search(r"float\[(\d+)\]", ddl or "")
ddl_dims = int(_m.group(1)) if _m else 0
try:
    blob_len_row = con.execute("SELECT length(embedding) n FROM graph_facts_vec LIMIT 1").fetchone()
    blob_len = int(blob_len_row["n"]) if blob_len_row else 0
except Exception:
    blob_len = 0
dims = (blob_len // 4) or ddl_dims

chats = [
    {"chat_id": r["chat_id"], "n": int(r["n"])}
    for r in con.execute(
        "SELECT f.chat_id AS chat_id, count(*) AS n FROM graph_facts_vec v "
        "JOIN graph_facts f ON f.id = v.fact_id GROUP BY f.chat_id "
        "ORDER BY n DESC"
    ).fetchall()
]
origins = [
    {"origin": r["origin"], "n": int(r["n"])}
    for r in con.execute(
        "SELECT coalesce(f.origin,'') AS origin, count(*) AS n FROM graph_facts_vec v "
        "JOIN graph_facts f ON f.id = v.fact_id GROUP BY f.origin ORDER BY n DESC LIMIT 20"
    ).fetchall()
]
emit("META", {
    "db": DB,
    "query_only": int(qonly),
    "ddl": ddl,
    "live_rows": int(live_rows),
    "source_rows": int(source_rows),
    "blob_bytes": blob_len,
    "ddl_dims": ddl_dims,
    "dims": dims,
    "chats": chats,
    "origins": origins,
})

NOW = int(time.time())
MAX_CHARS = 8000
pool = con.execute(
    "SELECT v.rowid AS rowid, f.id AS id, f.chat_id AS chat_id, "
    "coalesce(f.origin,'') AS origin, length(f.fact) AS n "
    "FROM graph_facts_vec v JOIN graph_facts f ON f.id = v.fact_id "
    "WHERE (f.expires_at IS NULL OR f.expires_at > ?) "
    "AND f.fact IS NOT NULL AND length(f.fact) BETWEEN 40 AND ? "
    "ORDER BY f.chat_id ASC, f.id ASC",
    (NOW, MAX_CHARS),
).fetchall()


def bucket(n):
    if n < 200:
        return "short"
    if n < 2000:
        return "mid"
    return "long"


by_chat = {}
for r in pool:
    by_chat.setdefault(r["chat_id"], []).append(dict(r))

chat_ids = sorted(by_chat, key=lambda c: (-len(by_chat[c]), str(c)))
# Both real chats must be represented; extra chats (if any) are capped by size.
target_chats = chat_ids[:3]
per_chat = 60 // max(1, len(target_chats))
per_chat = max(per_chat, 20)

QUOTA = {"short": (0.35, 3), "mid": (0.40, 3), "long": (0.25, 2)}


def pick_for_chat(rows, want):
    picked, seen = [], set()

    def take(rows_sub, count):
        if not rows_sub or count <= 0:
            return
        # origin diversity first: round-robin by origin
        groups = {}
        for r in rows_sub:
            groups.setdefault(r["origin"], []).append(r)
        order = sorted(groups, key=lambda o: (-len(groups[o]), o))
        idx = 0
        while count > 0 and any(groups[o] for o in order):
            o = order[idx % len(order)]
            if groups[o]:
                r = groups[o].pop(0)
                if r["id"] not in seen:
                    picked.append(r)
                    seen.add(r["id"])
                    count -= 1
            idx += 1

    for name, (share, minimum) in QUOTA.items():
        sub = [r for r in rows if bucket(int(r["n"])) == name]
        take(sub, max(minimum, int(round(want * share))))
    if len(picked) < want:
        take(rows, want - len(picked))
    return picked[:want]


chosen = []
for cid in target_chats:
    chosen.extend(pick_for_chat(by_chat[cid], per_chat))
# dedupe, keep order
uniq, ids = [], []
for r in chosen:
    if r["id"] in ids:
        continue
    ids.append(r["id"])
    uniq.append(r)
chosen = uniq

rows_out = []
CHUNK = 200
for i in range(0, len(chosen), CHUNK):
    part = chosen[i:i + CHUNK]
    q = (
        "SELECT v.rowid AS rowid, v.embedding AS embedding, f.id AS id, "
        "f.chat_id AS chat_id, coalesce(f.origin,'') AS origin, f.fact AS fact "
        "FROM graph_facts_vec v JOIN graph_facts f ON f.id = v.fact_id "
        "WHERE v.rowid IN (%s)" % ",".join("?" * len(part))
    )
    for r in con.execute(q, [p["rowid"] for p in part]).fetchall():
        raw = bytes(r["embedding"])
        rows_out.append({
            "rowid": int(r["rowid"]),
            "id": int(r["id"]),
            "chat_id": r["chat_id"],
            "origin": r["origin"],
            "text": r["fact"],
            "n": len(r["fact"] or ""),
            "dim": len(raw) // 4,
            "emb_b64": base64.b64encode(raw).decode("ascii"),
        })

payload = {
    "exported_at": NOW,
    "db_live_rows": int(live_rows),
    "db_source_rows": int(source_rows),
    "dims": dims,
    "rows": rows_out,
}
raw_json = json.dumps(payload, ensure_ascii=False).encode("utf-8")
emit("SAMPLE", {
    "rows": len(rows_out),
    "dims": dims,
    "json_bytes": len(raw_json),
    "zlib_b64": base64.b64encode(zlib.compress(raw_json, 6)).decode("ascii"),
})

emit("READY", {"dims": dims})
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    if msg.get("done"):
        break
    vec = msg.get("v") or []
    try:
        if len(vec) != dims:
            emit("KNN", {"id": msg.get("id"), "error": "dims",
                         "got": len(vec), "want": dims})
            continue
        blob = json.dumps([float(x) for x in vec])
        cur = con.execute(
            "SELECT rowid, fact_id, distance FROM graph_facts_vec "
            "WHERE embedding MATCH ? AND k = ?", (blob, 5))
        top = [[int(r["rowid"]),
                int(r["fact_id"]) if r["fact_id"] is not None else None,
                float(r["distance"])] for r in cur.fetchall()]
        emit("KNN", {"id": msg.get("id"), "top": top})
    except Exception as exc:
        emit("KNN", {"id": msg.get("id"), "error": str(exc)[:200]})

emit("DONE", {"knn_done": True})
