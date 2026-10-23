"""EMBED-RESOLVER-PREDEPLOY: run the CANDIDATE resolver on the real prod DB copy.

Reads only the local copy (never the prod DB). Writes only inside the copy
(a copy of the copy for the legacy variant), so the adopt path can be observed.

Usage: py -3 run_resolver.py
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
os.chdir(REPO)
sys.path.insert(0, str(REPO))

import httpx  # noqa: E402

COPY_GZ = HERE / "copy.db.gz"
COPY = HERE / "copy.db"
LEGACY = HERE / "copy_legacy.db"
OUT = HERE / "results"
CALLS: list[dict] = []


def extract() -> None:
    if COPY.exists() and COPY.stat().st_size > 100_000_000:
        return
    with gzip.open(COPY_GZ, "rb") as src, COPY.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)


def read_dotenv() -> dict:
    env = {}
    for line in (REPO / ".env").read_text(encoding="utf-8",
                                          errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def make_embed_fn():
    env = read_dotenv()
    base = env.get("EMBEDDING_BASE_URL", "").rstrip("/")
    key = env.get("EMBEDDING_API_KEY", "")
    model = env.get("EMBEDDING_MODEL_NAME", "")

    async def embed_fn(texts):
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{base}/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "input": list(texts)})
        body = resp.json()
        vectors = [item["embedding"] for item in body["data"]]
        CALLS.append({"texts": len(texts), "http": resp.status_code,
                      "latency_s": round(time.perf_counter() - t0, 2),
                      "dims": len(vectors[0]) if vectors else 0})
        return vectors

    return embed_fn


async def open_db(path: Path):
    import sqlite_vec
    from services.database import DatabaseService
    db = DatabaseService(path)
    await db.initialize_existing()
    await db.db.enable_load_extension(True)
    await db.db.load_extension(sqlite_vec.loadable_path())
    await db.db.enable_load_extension(False)
    return db


async def registry(db) -> list[dict]:
    cur = await db.db.execute(
        "SELECT generation_id, index_name, generation, status, model, dims, "
        "preprocessing_version, provider, endpoint_fingerprint, "
        "config_revision, pause_reason, next_allowed_at, fingerprint, "
        "activated_at, superseded_at FROM mca_embedding_index_generations "
        "ORDER BY index_name, generation")
    return [dict(r) for r in await cur.fetchall()]


async def main() -> int:
    extract()
    OUT.mkdir(exist_ok=True)
    from services import embedding_control_plane as ecp

    payload: dict = {"copy": {"path": str(COPY), "size": COPY.stat().st_size}}
    payload["code"] = {
        "module": "services/embedding_control_plane.py",
        "preprocessing_version": ecp._current_preprocessing_version(),
        "adoption_enabled": ecp.adoption_enabled(),
    }

    db = await open_db(COPY)
    try:
        payload["registry_before"] = await registry(db)
        payload["config"] = {
            "model": ecp._current_model(),
            "dims": await ecp._current_dim(db, "graph_facts_vec"),
            "space": await ecp._current_space(db, "graph_facts_vec"),
            "conn": ecp._current_conn(),
            "fingerprint_now": await ecp._current_fingerprint(db,
                                                             "graph_facts_vec"),
            "admission_enabled": ecp.adoption_enabled(),
        }
        t0 = time.perf_counter()
        payload["graph_facts_vec_step1"] = await ecp.resolve_index_compat(
            db, "graph_facts_vec")
        payload["graph_facts_vec_step1"]["elapsed_s"] = round(
            time.perf_counter() - t0, 3)

        step2 = None
        if payload["graph_facts_vec_step1"].get("needs_probe"):
            t0 = time.perf_counter()
            embed_fn = make_embed_fn()
            step2 = await ecp.ensure_index_compat(
                db, "graph_facts_vec", embed_fn=embed_fn)
            step2["elapsed_s"] = round(time.perf_counter() - t0, 3)
        payload["graph_facts_vec_step2"] = step2
        payload["embed_calls"] = CALLS

        payload["registry_after"] = await registry(db)
        payload["active_after"] = await db.get_active_embedding_generation(
            "graph_facts_vec")
        payload["latest_after"] = await db.get_latest_embedding_generation(
            "graph_facts_vec")

        payload["smart_archive"] = await ecp.resolve_index_compat(
            db, "smart_archive")
        payload["graph_facts_vec_recheck"] = await ecp.resolve_index_compat(
            db, "graph_facts_vec")
    finally:
        await db.db.close()

    # ── legacy variant on a separate copy (preproc NULL / NULL model+dims) ──
    if LEGACY.exists():
        LEGACY.unlink()
    shutil.copyfile(COPY, LEGACY)
    db2 = await open_db(LEGACY)
    try:
        legacy: dict = {}
        await db2.db.execute(
            "UPDATE mca_embedding_index_generations "
            "SET preprocessing_version = NULL, status = 'building', "
            "config_revision = NULL, activated_at = NULL")
        await db2.db.commit()
        legacy["rows_after_null"] = await registry(db2)
        legacy["case_a_preproc_null"] = await ecp.resolve_index_compat(
            db2, "graph_facts_vec")
        legacy["case_a_recheck_needs_probe"] = bool(
            legacy["case_a_preproc_null"].get("needs_probe"))
        # `fingerprint` в проде NOT NULL — «недоказуемый» провенанс
        # моделируется невоспроизводимым хешем, а не NULL.
        await db2.db.execute(
            "UPDATE mca_embedding_index_generations "
            "SET model = NULL, dims = NULL, provider = NULL, "
            "fingerprint = ?, endpoint_fingerprint = NULL",
            ("0" * 64,))
        await db2.db.commit()
        legacy["case_b_full_legacy_null"] = await ecp.resolve_index_compat(
            db2, "graph_facts_vec")
        legacy["registry_after_cases"] = await registry(db2)
        await db2.db.execute(
            "UPDATE mca_embedding_index_generations "
            "SET model = 'text-embedding-004', dims = 3072, "
            "preprocessing_version = NULL, fingerprint = ?",
            ("0" * 64,))
        await db2.db.commit()
        legacy["case_c_other_model"] = await ecp.resolve_index_compat(
            db2, "graph_facts_vec")
        payload["legacy_variants"] = legacy
    finally:
        await db2.db.close()

    (OUT / "resolver_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    print(json.dumps({
        "config": payload["config"],
        "step1": {k: payload["graph_facts_vec_step1"].get(k) for k in
                  ("state", "reason_code", "needs_probe", "action", "class",
                   "serviceable", "space", "dims", "rows", "candidate")},
        "step2": None if not payload["graph_facts_vec_step2"] else {
            k: payload["graph_facts_vec_step2"].get(k) for k in
            ("state", "reason_code", "action", "class", "serviceable",
             "admission", "canary")},
        "calls": payload["embed_calls"],
        "smart_archive": {k: payload["smart_archive"].get(k) for k in
                          ("state", "reason_code", "action", "source_empty",
                           "needs_probe")},
        "recheck": {k: payload["graph_facts_vec_recheck"].get(k) for k in
                    ("state", "reason_code", "action", "class", "serviceable")},
        "registry_after": payload["registry_after"],
        "legacy": {k: (v if not isinstance(v, dict) else {
            kk: v.get(kk) for kk in ("state", "reason_code", "action", "class",
                                     "needs_probe", "legacy_rows")})
                   for k, v in (payload.get("legacy_variants") or {}).items()
                   if not k.startswith("rows") and not k.startswith("registry")},
    }, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
