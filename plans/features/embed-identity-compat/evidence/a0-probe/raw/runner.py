"""A0-probe runner (EMBED-A0-PROBE lane).

One SSH session to prod:
  * exports a stratified sample of graph_facts_vec JOIN graph_facts (read-only),
  * keeps the session open and answers full-index sqlite-vec KNN queries with
    the vectors produced locally through the new apinet gateway.

Local side runs the REAL `ecp.compat_probe` (commit 30a2f868, worktree) against
an in-memory copy of the exported rows and the serving embed call shape
(POST {EMBEDDING_BASE_URL}/embeddings, Bearer EMBEDDING_API_KEY).

Nothing is written to prod. Secrets are never printed or persisted.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path

import httpx
import paramiko
import sqlite_vec

HOST = "198.46.175.136"
USER = "nik"
REPO = Path(r"C:\Code\Python\adminbot")
WORKTREE = Path(r"C:\Users\main\AppData\Local\Temp\opencode\a0-probe-wt")
OUTDIR = Path(r"C:\Users\main\AppData\Local\Temp\opencode\a0probe\out")
HEALTHZ = "https://admin-bot.duckdns.org/healthz"

sys.path.insert(0, str(WORKTREE))
os.chdir(WORKTREE)


# ── env / creds (never printed) ─────────────────────────────────────────────
def read_dotenv(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


def read_ssh_password() -> str:
    text = (REPO / "deploy_commands.txt").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^pass:\s*(\S+)\s*$", text, re.M)
    if not m:
        raise SystemExit("ssh credential not found")
    return m.group(1)


# ── embed client (serving wire shape) ───────────────────────────────────────
class StoredEmbed:
    """Dry-run embedder: returns vectors already stored in the DB (no network)."""

    def __init__(self):
        self.calls = []
        self.by_text = {}
        self.source = {}

    async def __call__(self, texts):
        started = time.perf_counter()
        try:
            vectors = [self.source[t] for t in texts]
        except KeyError as exc:
            self.calls.append({"n": len(texts), "ok": False, "error": "missing text"})
            raise RuntimeError("missing text") from exc
        self.calls.append({"n": len(texts), "ok": True, "http": 200,
                           "vectors": len(vectors), "dims": len(vectors[0]),
                           "latency_s": round(time.perf_counter() - started, 3)})
        for t, v in zip(texts, vectors):
            self.by_text[t] = v
        return vectors


class ServingEmbed:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.url = base_url.rstrip("/") + "/embeddings"
        self._key = api_key
        self.model = model
        self.calls: list[dict] = []
        self.by_text: dict[str, list[float]] = {}

    async def __call__(self, texts):
        texts = list(texts)
        started = time.perf_counter()
        rec = {"n": len(texts)}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
                resp = await client.post(
                    self.url,
                    json={"model": self.model, "input": texts},
                    headers={"Authorization": f"Bearer {self._key}"},
                )
        except Exception as exc:
            rec.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                        "latency_s": round(time.perf_counter() - started, 3)})
            self.calls.append(rec)
            raise
        rec["http"] = resp.status_code
        rec["latency_s"] = round(time.perf_counter() - started, 3)
        if resp.status_code != 200:
            rec.update({"ok": False, "error": resp.text[:400]})
            self.calls.append(rec)
            raise RuntimeError(f"embed HTTP {resp.status_code}")
        data = resp.json()
        items = data.get("data") or []
        if items and all("index" in it for it in items):
            items = sorted(items, key=lambda it: it["index"])
        vectors = [it["embedding"] for it in items]
        rec.update({"ok": True, "vectors": len(vectors),
                    "dims": len(vectors[0]) if vectors else 0,
                    "model": data.get("model")})
        self.calls.append(rec)
        if len(vectors) != len(texts):
            raise RuntimeError(f"vectors={len(vectors)} != inputs={len(texts)}")
        for text, vec in zip(texts, vectors):
            self.by_text[text] = vec
        return vectors


# ── async shim over sqlite3 (what compat_probe expects from db.db) ──────────
class _Cur:
    def __init__(self, cur):
        self._cur = cur

    async def fetchall(self):
        return self._cur.fetchall()

    async def fetchone(self):
        return self._cur.fetchone()


class _Conn:
    def __init__(self, con):
        self._con = con

    async def execute(self, sql, params=()):
        return _Cur(self._con.execute(sql, list(params)))


class _DB:
    def __init__(self, con):
        self.db = _Conn(con)


def build_memory_db(rows: list[dict], dims: int) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.enable_load_extension(True)
    con.load_extension(sqlite_vec.loadable_path())
    con.execute(
        "CREATE TABLE graph_facts (id INTEGER PRIMARY KEY, chat_id INTEGER, "
        "fact TEXT, origin TEXT, expires_at INTEGER)")
    con.execute(
        f"CREATE VIRTUAL TABLE graph_facts_vec USING vec0("
        f"embedding float[{dims}] distance_metric=cosine, +fact_id INTEGER, "
        f"+chat_id INTEGER, +origin TEXT, +expires_at INTEGER)")
    for row in rows:
        blob = base64.b64decode(row["emb_b64"])
        con.execute(
            "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at) "
            "VALUES (?,?,?,?,NULL)",
            (int(row["id"]), row["chat_id"], row["text"], row.get("origin") or ""))
        con.execute(
            "INSERT INTO graph_facts_vec (rowid, embedding, fact_id, chat_id, "
            "origin, expires_at) VALUES (?,?,?,?,?,NULL)",
            (int(row["rowid"]), blob, int(row["id"]), row["chat_id"],
             row.get("origin") or ""))
    con.commit()
    return con


def cosine(a, b) -> float:
    num = sum(float(x) * float(y) for x, y in zip(a, b))
    da = sum(float(x) * float(x) for x in a) ** 0.5
    db_ = sum(float(y) * float(y) for y in b) ** 0.5
    return num / (da * db_) if da > 0 and db_ > 0 else 0.0


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": round(sum(values) / len(values), 6),
            "min": round(min(values), 6), "max": round(max(values), 6)}


def healthz() -> dict:
    out = {"url": HEALTHZ}
    try:
        t0 = time.perf_counter()
        resp = httpx.get(HEALTHZ, timeout=20.0)
        out.update({"http": resp.status_code,
                    "latency_s": round(time.perf_counter() - t0, 3),
                    "body": resp.text[:300]})
    except Exception as exc:
        out.update({"error": f"{type(exc).__name__}: {exc}"[:300]})
    return out


# ── live run ────────────────────────────────────────────────────────────────
def build_dry_db() -> str:
    """Synthetic 3072-dim DB mirroring the prod vec0 DDL (dry-run only)."""
    import tempfile

    dims = 3072
    path = os.path.join(tempfile.mkdtemp(prefix="a0dry-"), "dry.db")
    con = sqlite3.connect(path)
    con.enable_load_extension(True)
    con.load_extension(sqlite_vec.loadable_path())
    con.execute("CREATE TABLE graph_facts (id INTEGER PRIMARY KEY, chat_id INTEGER, "
                "fact TEXT, origin TEXT, expires_at INTEGER)")
    con.execute(f"CREATE VIRTUAL TABLE graph_facts_vec USING vec0("
                f"embedding float[{dims}] distance_metric=cosine, +fact_id INTEGER, "
                f"+chat_id INTEGER, +origin TEXT, +expires_at INTEGER)")
    origins = ["chat_history", "user_note", "summary"]
    for i in range(60):
        fid = 7000 + i
        chat = 111 if i % 2 == 0 else 222
        n = 100 if i % 3 == 0 else (900 if i % 3 == 1 else 2500)
        text = f"dry fact {fid} " + "z" * n
        vec = [((fid * 13 + k * 7) % 1000) / 1000.0 for k in range(dims)]
        con.execute("INSERT INTO graph_facts VALUES (?,?,?,?,NULL)",
                    (fid, chat, text, origins[i % 3]))
        con.execute("INSERT INTO graph_facts_vec(rowid, embedding, fact_id, chat_id, "
                    "origin, expires_at) VALUES (?,?,?,?,?,NULL)",
                    (fid, struct.pack(f"<{dims}f", *vec), fid, chat, origins[i % 3]))
    con.commit()
    con.close()
    return path


def run_live(args, dry: bool = False) -> dict:
    env = read_dotenv(REPO / ".env")
    base_url = env.get("EMBEDDING_BASE_URL", "")
    api_key = env.get("EMBEDDING_API_KEY", "")
    model = env.get("EMBEDDING_MODEL_NAME", "")
    if not dry and not (base_url and api_key and model):
        raise SystemExit("embedding env incomplete")

    client = None
    proc = None
    if dry:
        embed = StoredEmbed()
        dbp = build_dry_db()
        rp = Path(__file__).with_name("remote_probe.py")
        proc = subprocess.Popen(
            [sys.executable, str(rp)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
            env=dict(os.environ, A0_DB=dbp, PYTHONIOENCODING="utf-8"))
        stdin, stdout, stderr = proc.stdin, proc.stdout, proc.stderr
        connect_s = 0.0
    else:
        embed = ServingEmbed(base_url, api_key, model)
        remote_src = Path(__file__).with_name("remote_probe.py").read_text(encoding="utf-8")
        remote_b64 = base64.b64encode(remote_src.encode("utf-8")).decode("ascii")
        remote_cmd = (
            "cd /var/www/admin_bot && PY='' && "
            "for c in .venv/bin/python venv/bin/python /usr/bin/python3 python3; do "
            "if command -v \"$c\" >/dev/null 2>&1 && \"$c\" -c 'import sqlite_vec' >/dev/null 2>&1; "
            "then PY=\"$c\"; break; fi; done; "
            "[ -z \"$PY\" ] && { echo 'ERR {\"reason\":\"no python with sqlite_vec\"}'; exit 9; }; "
            f"exec \"$PY\" -c \"$(printf %s '{remote_b64}' | base64 -d)\""
        )
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        t_conn = time.perf_counter()
        client.connect(HOST, 22, USER, read_ssh_password(), timeout=30,
                       banner_timeout=30, auth_timeout=30,
                       allow_agent=False, look_for_keys=False)
        connect_s = round(time.perf_counter() - t_conn, 2)
        stdin, stdout, stderr = client.exec_command(remote_cmd, timeout=1800)
        stdout.channel.settimeout(1800)

    err_buf: list[str] = []

    def drain():
        try:
            for line in iter(stderr.readline, ""):
                err_buf.append(line[:400])
        except Exception:
            pass

    threading.Thread(target=drain, daemon=True).start()

    meta = None
    sample = None
    knn: dict[int, list] = {}
    result = {"connect_s": connect_s, "ssh_connections": 0 if dry else 1}

    def send(payload):
        stdin.write(json.dumps(payload) + "\n")
        stdin.flush()

    while True:
        line = stdout.readline()
        if not line:
            break
        line = line.rstrip("\n")
        if not line or " " not in line:
            continue
        tag, _, body = line.partition(" ")
        if tag == "META":
            meta = json.loads(body)
        elif tag == "SAMPLE":
            head = json.loads(body)
            raw = zlib.decompress(base64.b64decode(head["zlib_b64"]))
            sample = json.loads(raw.decode("utf-8"))
            result["sample_transfer"] = {
                "rows": head["rows"], "json_bytes": head["json_bytes"],
                "wire_bytes": len(head["zlib_b64"]), "dims": head["dims"]}
            if meta is None:
                raise SystemExit("sample before meta")
            dims = int(meta["dims"])
            if dry:
                embed.source = {
                    r["text"]: list(struct.unpack(
                        f"<{len(base64.b64decode(r['emb_b64'])) // 4}f",
                        base64.b64decode(r["emb_b64"])))
                    for r in sample["rows"]}
            print(f"[a0] sample rows={len(sample['rows'])} dims={dims} "
                  f"wire={len(head['zlib_b64'])}B", file=sys.stderr, flush=True)
            try:
                _run_local(sample, dims, embed, result)
            except Exception as exc:
                result["local_error"] = f"{type(exc).__name__}: {exc}"[:300]
                print(f"[a0] local probe failed: {result['local_error']}",
                      file=sys.stderr, flush=True)
            # remote announces READY after the export; consume it before KNN
            while True:
                head_line = stdout.readline()
                if not head_line:
                    raise SystemExit("ssh closed before READY")
                htag, _, hbody = head_line.rstrip("\n").partition(" ")
                if htag == "READY":
                    break
                if htag == "ERR":
                    raise SystemExit(f"remote error: {hbody[:200]}")
            # full-index KNN for every embedded vector, same SSH session
            order = result.get("_ordered_ids") or []
            knn_error = None
            for fid in order:
                try:
                    send({"id": fid, "v": result["_vectors"][fid]})
                    ack = stdout.readline()
                    if not ack:
                        knn_error = "ssh closed during knn"
                        break
                    tag2, _, body2 = ack.rstrip("\n").partition(" ")
                    if tag2 != "KNN":
                        knn_error = f"unexpected reply: {ack[:120]}"
                        break
                    msg = json.loads(body2)
                    knn[int(msg["id"])] = msg
                except Exception as exc:
                    knn_error = f"{type(exc).__name__}: {exc}"[:200]
                    break
            result["knn_error"] = knn_error
            print(f"[a0] knn queried={len(knn)} error={knn_error}",
                  file=sys.stderr, flush=True)
            try:
                send({"done": True})
            except Exception:
                pass
            result["knn"] = {str(k): v for k, v in knn.items()}
            # drain remaining lines until DONE
            while True:
                tail = stdout.readline()
                if not tail:
                    break
                t2, _, b2 = tail.rstrip("\n").partition(" ")
                if t2 == "DONE":
                    break
            break
        elif tag in ("ERR",):
            result["remote_error"] = body[:400]
    if dry:
        proc.stdin.close()
        rc = proc.wait(timeout=300)
    else:
        rc = stdout.channel.recv_exit_status()
        client.close()
    result["remote_rc"] = rc
    result["stderr_tail"] = err_buf[-5:]
    result["meta"] = meta
    result["sample_head"] = {k: v for k, v in (sample or {}).items() if k != "rows"}
    result["_sample_json"] = sample
    return result


def _run_local(sample: dict, dims: int, embed: ServingEmbed, result: dict):
    from services import embedding_control_plane as ecp

    rows = sample["rows"]
    con = build_memory_db(rows, dims)
    db = _DB(con)
    old = {int(r["id"]): base64.b64decode(r["emb_b64"]) for r in rows}
    old_vec = {fid: list(struct.unpack(f"<{len(b) // 4}f", b)) for fid, b in old.items()}
    by_id = {int(r["id"]): r for r in rows}

    t0 = time.perf_counter()
    probe = asyncio.run(ecp.compat_probe(db, "graph_facts_vec", embed_fn=embed))
    probe_s = round(time.perf_counter() - t0, 3)
    result["probe"] = probe
    result["probe_elapsed_s"] = probe_s
    result["probe_calls"] = list(embed.calls)

    probe_ids = [int(x) for x in (probe.get("sample_ids") or [])]
    checked_ids = probe_ids or [int(r["id"]) for r in rows[:12]]

    # Extended pass: one more batch (<=48 texts) if budget allows.
    remaining = [r for r in rows if int(r["id"]) not in checked_ids]
    calls_used = len(embed.calls)
    budget_left = 3 - calls_used
    extended = {"attempted": 0, "vectors": 0, "calls": [], "error": None,
                "batch_size": 0, "ids": []}
    api_down = (probe.get("reason_code") == "api_unavailable")
    if remaining and budget_left > 0 and not api_down:
        batch = remaining if len(remaining) <= 48 else remaining[:48]
        extended.update({"attempted": len(batch), "batch_size": len(batch)})
        before = len(embed.calls)
        try:
            asyncio.run(embed([r["text"] for r in batch]))
            extended["vectors"] = len(batch)
            extended["ids"] = [int(r["id"]) for r in batch]
        except Exception as exc:
            extended["error"] = f"{type(exc).__name__}: {exc}"[:300]
        extended["calls"] = embed.calls[before:]

    vectors = dict(embed.by_text)
    # map text -> fact id (texts are unique inside the sample by construction)
    vectors_by_fact = {}
    for r in rows:
        vec = vectors.get(r["text"])
        if vec is not None:
            vectors_by_fact[int(r["id"])] = [float(x) for x in vec]

    cos_all = {}
    for fid, vec in vectors_by_fact.items():
        cos_all[fid] = round(cosine(vec, old_vec[fid]), 8)

    result["_vectors"] = vectors_by_fact
    result["_ordered_ids"] = sorted(vectors_by_fact)
    result["_by_id"] = {fid: {"chat_id": by_id[fid]["chat_id"],
                              "origin": by_id[fid]["origin"],
                              "n": by_id[fid]["n"]} for fid in vectors_by_fact}
    result["extended"] = extended
    result["cosine"] = cos_all
    result["embed_calls"] = list(embed.calls)
    result["dims_seen"] = sorted({len(v) for v in vectors_by_fact.values()})
    result["sample_rows"] = len(rows)


def finish_live(result: dict) -> dict:
    sample = result.pop("_sample_json")
    rows = (sample or {}).get("rows") or []
    vectors = result.pop("_vectors", {})
    by_id = result.pop("_by_id", {})
    result.pop("_ordered_ids", None)
    cos_all = result.get("cosine") or {}
    knn = result.get("knn") or {}

    hit1, hit5, dist_self = [], [], []
    per_row = []
    for fid_s, msg in knn.items():
        fid = int(fid_s)
        top = msg.get("top") or []
        ids = [t[1] if t[1] is not None else t[0] for t in top if isinstance(t, list)]
        rowids = [t[0] for t in top if isinstance(t, list)]
        h1 = 1 if (ids and (ids[0] == fid or rowids[0] == fid)) else 0
        h5 = 1 if (fid in ids or fid in rowids) else 0
        hit1.append(h1)
        hit5.append(h5)
        per_row.append({"id": fid, "chat_id": by_id.get(fid, {}).get("chat_id"),
                        "origin": by_id.get(fid, {}).get("origin"),
                        "n": by_id.get(fid, {}).get("n"),
                        "cosine": cos_all.get(fid),
                        "top_ids": ids[:5], "hit1": h1, "hit5": h5,
                        "error": msg.get("error")})
    probe = result.get("probe") or {}
    knn_ids = {int(k) for k in knn}
    probe_checked = [int(x) for x in (probe.get("sample_ids") or []) if int(x) in knn_ids]
    probe_rows = [r for r in per_row if r["id"] in set(probe_checked)]
    result["full_index"] = {
        "queried": len(per_row),
        "hit1": round(sum(hit1) / len(hit1), 4) if hit1 else None,
        "hit5": round(sum(hit5) / len(hit5), 4) if hit5 else None,
        "hit1_probe_sample": round(sum(r["hit1"] for r in probe_rows) / len(probe_rows), 4) if probe_rows else None,
        "hit5_probe_sample": round(sum(r["hit5"] for r in probe_rows) / len(probe_rows), 4) if probe_rows else None,
        "probe_sample_queried": len(probe_rows),
        "per_row": per_row,
    }
    result["cosine_stats_all"] = stats(list(cos_all.values()))
    result["cosine_stats_probe"] = stats([cos_all[i] for i in probe_checked if i in cos_all])
    result["embed_calls_total"] = len(result.get("embed_calls") or [])
    result["latency_s_total"] = round(sum(c.get("latency_s") or 0 for c in (result.get("embed_calls") or [])), 3)
    result["sample_meta"] = {
        "rows": len(rows),
        "dims": rows[0]["dim"] if rows else None,
        "chats": sorted({str(r["chat_id"]) for r in rows}),
        "origins": sorted({str(r.get("origin") or "") for r in rows}),
        "length_buckets": {
            "short": sum(1 for r in rows if (r.get("n") or 0) < 200),
            "mid": sum(1 for r in rows if 200 <= (r.get("n") or 0) < 2000),
            "long": sum(1 for r in rows if (r.get("n") or 0) >= 2000),
        },
    }
    return result, rows


# ── self-test (no network, no prod) ─────────────────────────────────────────
def self_test(mode: str) -> dict:
    from services import embedding_control_plane as ecp

    dims = 64
    rows = []
    by_text = {}
    for i in range(60):
        fid = 1000 + i
        chat = 111 if i % 2 == 0 else 222
        n = 80 if i % 3 == 0 else (900 if i % 3 == 1 else 2500)
        text = f"selftest fact {fid} " + ("x" * n)
        vec = [((fid * 37 + k * 11) % 1000) / 1000.0 for k in range(dims)]
        blob = struct.pack(f"<{dims}f", *vec)
        rows.append({"rowid": fid, "id": fid, "chat_id": chat, "origin": "selftest",
                     "text": text, "n": len(text), "dim": dims,
                     "emb_b64": base64.b64encode(blob).decode()})
        if mode == "random":
            new_vec = [((fid * 97 + k * 7919) % 997) / 997.0 for k in range(dims)]
        else:
            new_vec = vec
        new_blob = struct.pack(f"<{dims}f", *new_vec)
        by_text[text] = list(struct.unpack(f"<{dims}f", new_blob))
    sample = {"rows": rows, "dims": dims}
    con = build_memory_db(rows, dims)
    db = _DB(con)

    async def fake_embed(texts):
        return [by_text[t] for t in texts]

    probe = asyncio.run(ecp.compat_probe(db, "graph_facts_vec", embed_fn=fake_embed))
    return probe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", choices=["same", "random"])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--out", default=str(OUTDIR))
    args = ap.parse_args()
    if args.self_test:
        print(json.dumps(self_test(args.self_test), ensure_ascii=False))
        return 0

    out = Path(args.out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    if args.dry:
        before = {"dry": True}
        result = run_live(args, dry=True)
        payload, rows = finish_live(result)
        payload["healthz_before"] = before
        payload["dry"] = True
        (out / "dry_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "dry": True,
            "probe": payload.get("probe"),
            "calls": payload.get("embed_calls_total"),
            "full_index": {k: v for k, v in (payload.get("full_index") or {}).items()
                           if k != "per_row"},
            "cosine": payload.get("cosine_stats_all"),
            "remote_rc": payload.get("remote_rc"),
        }, ensure_ascii=False))
        return 0
    before = healthz()
    t0 = time.perf_counter()
    result = run_live(args)
    wall = round(time.perf_counter() - t0, 2)
    after = healthz()
    payload, rows = finish_live(result)
    payload["healthz_before"] = before
    payload["healthz_after"] = after
    payload["wall_s"] = wall
    payload["worktree_head"] = os.popen(f'git -C "{WORKTREE}" rev-parse HEAD').read().strip()

    (out / "raw" / "run_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    sample = {
        "exported_at": (payload.get("sample_head") or {}).get("exported_at"),
        "dims": rows[0]["dim"],
        "db_live_rows": (payload.get("sample_head") or {}).get("db_live_rows"),
        "note": "prod read-only export; embedding = float32 values (7 dp)",
        "rows": [{
            "id": r["id"], "rowid": r["rowid"], "chat_id": r["chat_id"],
            "origin": r["origin"], "text": r["text"], "n": r["n"],
            "embedding": [round(x, 7) for x in struct.unpack(
                f"<{len(base64.b64decode(r['emb_b64'])) // 4}f",
                base64.b64decode(r["emb_b64"]))],
        } for r in rows],
    }
    (out / "sample.json").write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "verdict": (payload.get("probe") or {}).get("verdict"),
        "checked": (payload.get("probe") or {}).get("checked"),
        "mean": (payload.get("probe") or {}).get("mean"),
        "min": (payload.get("probe") or {}).get("min"),
        "hit5": (payload.get("probe") or {}).get("hit5"),
        "reason_code": (payload.get("probe") or {}).get("reason_code"),
        "calls": payload.get("embed_calls_total"),
        "sample_rows": payload.get("sample_rows"),
        "full_index_hit1": (payload.get("full_index") or {}).get("hit1"),
        "full_index_hit5": (payload.get("full_index") or {}).get("hit5"),
        "healthz": [before.get("http"), after.get("http")],
        "out": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
