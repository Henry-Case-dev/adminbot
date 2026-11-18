"""One end-to-end smoke for release 2.58.215 — no network.

1) L1 snapshot/route for z-ai/glm-5.3-uncensored: resolve only; the capability
   adapter seam is injected (no HTTP), route composition is real.
2) Vision: download_api_file_bytes on the real transport with the documented
   cloud_fetcher injection (local file absent -> cloud fallback), warning text
   captured.
3) Scheduler: slot_claim gap probe — the same call-site class that was fixed
   (sync in-loop vs asyncio.to_thread) on a temp DB with a held write-lock.
"""
import asyncio
import json
import re
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
os.environ.setdefault("ADMINBOT_SKIP_DOTENV", "1")
os.environ["MEDIA_DOWNLOAD_CLOUD_FALLBACK"] = "1"
sys.path.insert(0, str(ROOT))

from config.settings import settings                    # noqa: E402
from services import hot_config as hot                  # noqa: E402
from services import direct_l1 as l1                    # noqa: E402
from services import media_download as md               # noqa: E402
from services import model_capacity as cap              # noqa: E402
from services import slot_claims as sc                  # noqa: E402
from services.llm_client import LLMClient               # noqa: E402

MODEL = "z-ai/glm-5.3-uncensored"
BASE = "https://nano-gpt.com/api/v1"
RESULT = {}


# ── 1. L1 route snapshot (capability seam injected, no HTTP) ───────────────
async def _capability_stub(base_url, model, *, slot=None, route=None):
    return cap.model_capability(
        cap.CapacityResult(
            provider=cap.detect_provider_class(base_url), model=model,
            declared_context_window=128000, runtime_context_window=None,
            effective_context_window=128000, max_output_tokens=8192,
            source=cap.SOURCE_PROVIDER_CATALOG,
            confidence=cap.CONFIDENCE_VERIFIED,
            resolved_at=time.time(), fallback_used=False,
            supports_reasoning=True, output_token_field="max_tokens"),
        endpoint=cap._base_url_host(base_url))


async def l1_smoke():
    hot.set_config_cache(type("RoHot", (), {
        "get": lambda self, key, default=None: {
            "models.llm_base_url": BASE,
            "models.llm_model_name": MODEL,
            "keys.llm_api_key": "smoke-key-not-real",
            "models.embedding_model_name": "text-embedding-3-small",
        }.get(key, default)})())
    original = cap.resolve_model_capability
    cap.resolve_model_capability = _capability_stub
    try:
        llm = LLMClient(BASE, "smoke-key-not-real", MODEL, "text-embedding-3-small")
        slot = l1.resolve_l1_model(-1002661910336)
        route = await l1.resolve_l1_route(slot, llm)
    finally:
        cap.resolve_model_capability = original
    data = json.loads(json.dumps(route.as_event_fields()))
    data.update({
        "usable": route.usable,
        "key_available": route.key_available,
        "dedicated_slot_model": slot.model,
        "dedicated": slot.dedicated,
    })
    assert data["model"] == MODEL, data
    assert data["endpoint"] == "nano-gpt.com", data
    assert data["provider"] == "nanogpt", data
    assert data["key_slot"] == "main" and data["dedicated"] is False, data
    assert data["usable"] and data["key_available"], data
    assert float(data["timeout_seconds"]) == 180.0, data
    assert float(data["deadline_seconds"]) == 360.0, data
    assert data["timeout_source"] == "transport_policy", data
    assert data["output_field"] == "max_tokens", data
    assert int(data["max_output_tokens"]) == 4608, data
    assert data["window_confidence"] == "verified", data
    RESULT["l1_route"] = data


# ── 2. Vision transport: real code, injected cloud fetcher ────────────────
class _APIFlag:
    is_local = True


class _Session:
    api = _APIFlag()


class _TGFile:
    file_path = "photos/gone.png"


class _Bot:
    id = 123
    token = "123:smoke"
    session = _Session()

    async def get_file(self, file_id):
        return _TGFile()

    async def download(self, *a, **kw):
        raise RuntimeError("aiogram transport unavailable (smoke)")


async def vision_smoke():
    async def fetcher(token, file_id, rel_path, *, timeout, max_bytes):
        assert token == "123:smoke" and file_id == "smoke-file", (token, file_id)
        return b"\x89PNG-smoke-bytes"

    diag = {}
    data = await md.download_api_file_bytes(
        _Bot(), "smoke-file", site="vision", attempts=1, sleep=0.0,
        cloud_fetcher=fetcher, diagnostics=diag)
    assert data == b"\x89PNG-smoke-bytes", data
    assert diag["outcome"] == "cloud_fallback", diag
    RESULT["vision"] = {"bytes": len(data), "diagnostics": diag}


# ── 3. Scheduler: same-class loop-gap probe ───────────────────────────────
async def _gap(mode: str, hold_s: float = 0.5):
    tmp = tempfile.mkdtemp(prefix="gap-258215-")
    path = os.path.join(tmp, "claims.db")
    store = sc.SqliteSlotClaimStore(path)
    store.apply_schema()
    import sqlite3
    import threading
    ready = threading.Event()

    def holder():
        conn = sqlite3.connect(path, timeout=10, isolation_level=None)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO slot_claims (kind, chat_id, local_date, local_slot, "
            "slot_utc_instant, config_version, claimed_at, fired, reason_code) "
            "VALUES ('probe', 99, '2026-01-01', '00', 0, '', 0, 0, '')")
        ready.set()
        time.sleep(hold_s)
        conn.execute("ROLLBACK")
        conn.close()

    t = threading.Thread(target=holder, daemon=True)
    t.start()
    await asyncio.to_thread(ready.wait, 5.0)
    gaps, done = [], asyncio.Event()
    last = time.monotonic()

    async def ticker():
        nonlocal last
        while True:
            now = time.monotonic()
            gaps.append((now - last) * 1000.0)
            last = now
            if done.is_set():
                return
            await asyncio.sleep(0.005)

    ticker_task = asyncio.create_task(ticker())
    await asyncio.sleep(0.05)
    t0 = time.monotonic()

    def claim():
        return store.try_claim(kind="probe", chat_id=1, local_date="2026-01-01",
                              local_slot="06", slot_utc_instant=1,
                              config_version="probe", claimed_at=1)

    if mode == "sync":
        claim()
    else:
        await asyncio.to_thread(claim)
    claim_ms = (time.monotonic() - t0) * 1000.0
    done.set()
    await ticker_task
    t.join(timeout=10)
    for name in os.listdir(tmp):
        os.remove(os.path.join(tmp, name))
    os.rmdir(tmp)
    return {"claim_ms": round(claim_ms), "max_gap_ms": round(max(gaps), 1)}


async def scheduler_smoke():
    sync = await _gap("sync")
    thread = await _gap("thread")
    assert sync["claim_ms"] >= 400, sync
    assert thread["claim_ms"] >= 400, thread
    assert thread["max_gap_ms"] < 100, thread
    assert thread["max_gap_ms"] < sync["max_gap_ms"] / 3, (sync, thread)
    RESULT["scheduler"] = {"sync": sync, "thread": thread}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


async def main():
    await l1_smoke()
    handler = _Capture()
    md.logger.addHandler(handler)
    md.logger.setLevel(logging.WARNING)
    try:
        await vision_smoke()
    finally:
        md.logger.removeHandler(handler)
    RESULT["vision"]["warnings"] = handler.lines
    pattern = re.compile(r"^\[vision\] cloud fallback used \| "
                         r"file_id=smoke-file \| local=[a-z_]+$")
    assert any(pattern.match(line) for line in handler.lines), handler.lines
    assert any("[vision] bot transport failed | class=provider_error" == line
               for line in handler.lines), handler.lines
    await scheduler_smoke()
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))


asyncio.run(main())
