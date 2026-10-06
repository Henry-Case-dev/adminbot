"""MCA-19 Wave 2, блок E (`mca-19-image-understanding`, round 10.43) —
производные факты/SourceRef, честный missing_source, «Аналитика»/витрина,
POST /api/vision/test + GET /api/vision/state (ADR-1028-19 D12/D13/D15;
T-5113…T-5116, T-5103-UI хвост).

Контракты:
  * D12/SC-R4a (→A67): производный факт трассируется SourceRef'ом ДО
    message + asset + analysis revision + OCR block (гранулярность
    обязательна); provenance OFF → честный [] (не фабрикация);
  * D15/SC-R4d (→A68-фрагмент): процесс `vision.media` v1 code-declared
    со стадиями `:1699` точно; snapshot честен (OFF → vision_disabled,
    без рисования «зрения»);
  * D14: недоступный файл → vision_missing_source (см. block C — здесь
    reason-словарь фиксируется в snapshot-контракте);
  * routes: POST /api/vision/test + GET /api/vision/state зарегистрированы
    ( conscious re-pin ROUTES_SHA256_F11; routes-набор f8_baseline
    переиздан tools/_mca19_wave2_bump_pins.py).

Оффлайн; реальных вызовов нет. R17: секретов нет.
"""
import asyncio
import json

import pytest

from services import mca_gates, mca_process_registry as reg, mca_vision
from services.database import DatabaseService

CHAT_A = -1004000000031

_CREATED_DBS: list = []


async def _fresh(tmp_path, name="mca19e.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    _CREATED_DBS.append(d)
    return d


@pytest.fixture(autouse=True)
def _env():
    mca_vision.reset_runtime()
    yield
    try:
        asyncio.run(_drain())
    except Exception:
        pass
    mca_vision.reset_runtime()


async def _drain():
    while _CREATED_DBS:
        await _CREATED_DBS.pop().close()


@pytest.fixture()
def _enabled():
    from tests.test_mca19_block_b_round1043 import patched_settings
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        yield


async def _ready_analysis(db, *, asset_id="as1", tg=501, ocr_texts=()):
    """Готовый анализ (fixture-запись БЕЗ LLM)."""
    await db.upsert_media_asset({
        "asset_id": asset_id, "message_key": f"{CHAT_A}:{tg}",
        "chat_id": CHAT_A, "tg_message_id": tg, "asset_kind": "photo",
        "file_id": "fid", "file_unique_id": "uniq", "size_variant": "large"})
    aid = await db.record_media_analysis({
        "asset_id": asset_id, "access_scope": mca_vision.access_scope_for(
            CHAT_A),
        "analyzer_config_revision": "cfg", "quality_profile": "default",
        "status": "running"})
    blocks = [{"text": t, "channel": mca_vision.UNTRUSTED_DATA_CHANNEL}
              for t in ocr_texts]
    ok = await db.finish_media_analysis(
        aid, expected_revision=1, status="ready",
        ocr_blocks=blocks or None,
        visual_description="на картинке кот",
        uncertainty=["фон размыт"])
    assert ok
    return await db.get_media_analysis(aid)


# ── D12/SC-R4a: SourceRef производного факта до OCR block ───────────────────

@pytest.mark.asyncio
async def test_source_ref_granularity_asset_revision_ocr(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    analysis = await _ready_analysis(db, ocr_texts=("я увольняюсь",
                                                    "цена 100"))
    refs = mca_vision.analysis_source_ref(
        chat_id=CHAT_A, tg_message_id=501,
        asset_id=str(analysis["asset_id"]),
        analysis_revision=int(analysis["revision"]),
        ocr_index=0)
    assert refs.entity_type == "media_asset"
    assert refs.store == "sqlite"
    assert (f"{CHAT_A}:501#{analysis['asset_id']}"
            f"#rev{analysis['revision']}#ocr_block:0") in refs.entity_id
    combined = mca_vision.analysis_source_ref(
        chat_id=CHAT_A, tg_message_id=501,
        asset_id=str(analysis["asset_id"]),
        analysis_revision=int(analysis["revision"]))
    assert "#combined" in combined.entity_id


@pytest.mark.asyncio
async def test_derived_fact_refs_resolved_and_deduped(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    analysis = await _ready_analysis(db, ocr_texts=("текст A",))
    refs = await mca_vision.derived_fact_source_refs(
        db, chat_id=CHAT_A, tg_message_id=501, analysis_row=analysis)
    # message + ocr_block:0 + combined (mca-04a get-or-create).
    assert len(refs) == 3
    assert len(set(refs)) == 3
    # Идемпотентность (дедуп mca-04a): повтор — те же id.
    refs2 = await mca_vision.derived_fact_source_refs(
        db, chat_id=CHAT_A, tg_message_id=501, analysis_row=analysis)
    assert refs2 == refs


@pytest.mark.asyncio
async def test_derived_fact_refs_off_is_honest(tmp_path, monkeypatch,
                                               _enabled):
    """provenance OFF → честный [] — SourceRef'ы НЕ фабрикуются."""
    db = await _fresh(tmp_path)
    analysis = await _ready_analysis(db, ocr_texts=("текст B",))
    from services import provenance
    monkeypatch.setattr(provenance, "provenance_enabled", lambda: False)
    refs = await mca_vision.derived_fact_source_refs(
        db, chat_id=CHAT_A, tg_message_id=501, analysis_row=analysis)
    assert refs == []


# ── D15/SC-R4d: процесс vision.media v1 + честный snapshot ──────────────────

def test_vision_media_v1_stages_exact():
    proc = reg.get_process("vision.media")
    assert proc is not None and proc.version == "1"
    assert proc.owner_feature == "mca-19"
    assert proc.stages == mca_vision.vision_stages()
    assert proc.stages == ("ingest", "download", "decode", "vision",
                           "validate", "store", "project", "reindex",
                           "consumers")
    assert proc.widget_id  # контракт mca-17c


@pytest.mark.asyncio
async def test_snapshot_honest_when_disabled(tmp_path, monkeypatch):
    """K1 OFF → честный «выключено владельцем/рубильником»; БЕЗ сети."""
    db = await _fresh(tmp_path)
    monkeypatch.setattr(mca_gates, "vision_enabled", lambda: False)
    snap = await mca_vision.runtime_snapshot(db)
    assert snap["requested"] is False
    assert snap["effective_enabled"] is False
    assert snap["reason"] == "vision_disabled"
    assert snap["process"] == "vision.media"
    assert snap["stages"] == list(mca_vision.vision_stages())
    assert snap["queue"] is not None and snap["last"] is None


@pytest.mark.asyncio
async def test_snapshot_queue_and_last(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    from services.task_supervisor import TaskJobStore
    store = TaskJobStore(db)
    await store.enqueue(owner="vision.analytics-test",
                        kind=mca_vision.VISION_JOB_KIND,
                        coalesce_key="vision:asset:snap1",
                        payload=json.dumps({"asset_id": "snap1",
                                            "chat_id": CHAT_A}))
    analysis = await _ready_analysis(db)
    snap = await mca_vision.runtime_snapshot(db)
    assert snap["queue"]["queued"] == 1
    assert snap["last"] is not None
    assert snap["last"]["status"] == "ready"
    assert snap["last"]["revision"] == analysis["revision"]


@pytest.mark.asyncio
async def test_snapshot_without_db_fail_open():
    snap = await mca_vision.runtime_snapshot(None)
    assert snap["queue"] is None and snap["last"] is None
    assert "reason" in snap and "stages" in snap


# ── routes: /api/vision/test + /api/vision/state (conscious re-pin F11) ─────

def test_vision_routes_registered():
    import re
    from pathlib import Path
    txt = (Path(__file__).resolve().parents[1] / "web" / "api" / "routes.py") \
        .read_text(encoding="utf-8")
    assert '@api_router.post("/vision/test")' in txt
    assert '@api_router.get("/vision/state")' in txt
    # RBAC — прецедент /api/random/test (global admin ИЛИ право на ключ).
    chunk = txt[txt.index('post_vision_test'):]
    assert 'keys.vision_api_key' in chunk
    assert "_VISION_TEST_MIN_INTERVAL" in txt   # rate-limit ≥10с
    # Проба — нейтральное изображение на бэкенде (R17: prompt игнорируется).
    assert "probe_connection" in chunk


def test_vision_routes_in_fixture_baseline():
    """Routes-набор f8_baseline переиздан (+2 endpoint, Wave 2)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    fx = json.loads((root / "tests" / "fixtures" / "round1025"
                     / "f8_baseline.json").read_text(encoding="utf-8"))
    txt = (root / "web" / "api" / "routes.py").read_text(encoding="utf-8")
    routes = set(re.findall(
        r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', txt))
    assert {"/vision/test", "/vision/state"} <= set(fx["routes"])
    assert routes == set(fx["routes"])
