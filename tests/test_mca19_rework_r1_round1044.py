"""MCA-19 Rework R1 (round 10.44) — закрытие находок review T-5124 (Needs Fixes).

Покрытие:
  * H-1: `record_media_analysis` — конфликт UNIQUE-гранулы ПОСЛЕ посторонних
    вставок на shared-соединении возвращает ИСТИННЫЙ id существующей строки
    (на прежнем коде RED: stale `lastrowid` чужой вставки → несуществующий id
    → повторный платный vision-вызов с потерей результата / CAS-перезапись
    чужой analysis-строки). Репро ревьюера: 2 анализа + 3 посторонние вставки;
  * H-2: прод-шов единого renderer'а D9 через РЕАЛЬНУЮ точку сборки контекста
    (`build_chat_context` — тот же шов, что в handlers search/factcheck):
    ready-анализ → OCR/описание-блок в контексте, нет анализа → honest
    pending-строка; K1 OFF / requested OFF → контекст байт-в-байт прежний;
  * H-2/п.2: стадия `consumers` — success только при фактических
    потребителях (мастер OFF → honest skipped/vision_disabled);
  * M-1: probe 2xx → ok-вердикт без противоречивого reason-кода
    (прежний «vision_unsupported» при success);
  * M-2: tool-pending — reason по семантике бюджета ожидания
    (`deadline_exceeded`), не «deferred» (код переполнения очереди D20).

Оффлайн: bot/transport-двойники; реальных LLM/vision вызовов и отправок в
чаты нет (no-false-acceptance).
"""
import asyncio
import datetime
import json
import struct
import time
import zlib

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

from services import mca_gates, mca_vision
from services.chat_context import build_chat_context, format_chat_context
from services.database import DatabaseService
from services.mca_vision import (DESC_LABEL, OCR_LINE_LABEL, PENDING_LINE,
                                 UNTRUSTED_DATA_CHANNEL)
from tests.test_mca19_block_b_round1043 import patched_settings

CHAT_A = -1004000000031

DT_NOON = datetime.datetime(2026, 10, 6, 12, 0, 0,
                            tzinfo=datetime.timezone.utc)
TS_NOON = int(DT_NOON.timestamp())


# ── минимальные двойники (прецедент test_mca19_block_d_round1043) ───────────

def make_png(width=10, height=10) -> bytes:
    def chunk(tag, data):
        raw = tag + data
        return (struct.pack(">I", len(data)) + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF))
    row = b"\x00" + b"\x40\x50\x60" * width
    body = zlib.compress(row * height)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0,
                                         0, 0))
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


PNG_BYTES = make_png()


def _photo(serial=1):
    return PhotoSize(file_id=f"fid_{serial}", file_unique_id=f"uniq_{serial}",
                     width=800, height=600, file_size=12345)


def _photo_message(chat_id=CHAT_A, tg_id=401, *, caption=None, serial=1,
                   sent_at=None):
    return Message(
        message_id=tg_id,
        date=datetime.datetime.fromtimestamp(
            sent_at or TS_NOON, tz=datetime.timezone.utc),
        chat=Chat(id=chat_id, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Вася"),
        photo=[_photo(serial), _photo(serial)],
        caption=caption,
    )


class _FakeBot:
    def __init__(self, blobs):
        self.blobs = blobs

    async def get_file(self, file_id):
        class _F:
            pass
        f = _F()
        f.file_id = file_id
        return f

    async def download(self, tg_file, destination=None):
        destination.write(self.blobs[tg_file.file_id])


def _transport_vision(calls: list):
    async def _t(url, *, payload, headers, timeout):
        calls.append(url)
        return 200, {
            "choices": [{"message": {"content": json.dumps({
                "ocr_blocks": [{"text": "привет от бота",
                                "bbox": [0, 0, 5, 5]}],
                "visual_description": "скриншот чата",
                "uncertainty": [],
                "self_reported_confidence": 0.7,
            })}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
        }
    return _t


def _analysis_rec(asset_id, scope, **kw):
    rec = dict(asset_id=asset_id, access_scope=scope,
               analysis_schema_version=1, analyzer_provider="openai_compat",
               analyzer_model="vlm-x", analyzer_config_revision="cfg1",
               prompt_version="vision_v1", quality_profile="default",
               status="pending")
    rec.update(kw)
    return rec


_CREATED_DBS: list = []


async def _fresh(tmp_path, name="mca19r1.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    _CREATED_DBS.append(d)
    return d


@pytest.fixture(autouse=True)
def _env():
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()

    async def _closer():
        while _CREATED_DBS:
            await _CREATED_DBS.pop().close()
    yield
    try:
        asyncio.run(_closer())
    except Exception:
        pass
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()


def _cap_ok():
    mca_vision.store_capability(
        mca_vision.resolve_route(),
        mca_vision.CapabilityVerdict("ok", "", True, time.monotonic()))


async def _save_message(db, tg_id, *, caption=None, text=None,
                        media_type="photo", author="Вася"):
    """Каноническая запись (mca-03 + Wave-1 Origin-шов)."""
    from services import message_identity
    await message_identity.save_live_message(
        db, user_id=42, chat_id=CHAT_A, text=text, caption=caption,
        timestamp=TS_NOON, sent_at=TS_NOON, ingested_at=TS_NOON,
        media_type=media_type, author_name=author, is_forward=False,
        forward_source="", tg_message_id=tg_id, media_ref=None,
        reply_to_id=None, reply_to_author_id=None, quote_text=None,
        quote_author_id=None, forward_author_id=None)


# ═══════════════ H-1: конфликт гранулы после посторонних вставок ════════════

@pytest.mark.asyncio
async def test_h1_conflict_after_foreign_inserts_returns_true_id(tmp_path):
    """Репро ревьюера: 2 анализа + 3 посторонние вставки → повторная гранула
    возвращает ИСТИННЫЙ id существующей строки (на прежнем коде — stale
    lastrowid=3, несуществующий analysis-id → потеря результата)."""
    d = await _fresh(tmp_path)
    try:
        id1 = await d.record_media_analysis(_analysis_rec("a1", "chat:1"))
        id2 = await d.record_media_analysis(_analysis_rec("a2", "chat:1"))
        assert id1 > 0 and id2 > 0 and id1 != id2
        # Три посторонних INSERT на том же shared-соединении (другая таблица).
        for i in range(3):
            await d.upsert_media_asset({
                "asset_id": f"fx{i}", "message_key": f"{CHAT_A}:{700+i}",
                "chat_id": CHAT_A, "tg_message_id": 700 + i,
                "asset_kind": "photo", "file_id": f"f{i}",
                "file_unique_id": f"u{i}", "size_variant": "large"})
        # Конфликт гранулы a1: истинный id существующей строки, НЕ stale
        # lastrowid последней чужой вставки.
        got = await d.record_media_analysis(_analysis_rec("a1", "chat:1"))
        assert got == id1
        row = await d.get_media_analysis(got)
        assert row is not None and row["asset_id"] == "a1"
        # Строк-гранул по-прежнему две (дубля нет).
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM mca_media_analyses")
        assert (await cur.fetchone())["c"] == 2
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_h1_conflicted_id_finishes_without_second_paid_call(tmp_path):
    """Возвращённый при конфликте id — рабочий: CAS-finish проходит по
    СУЩЕСТВУЮЩЕЙ строке (результат не выбрасывается, второй платный
    vision-вызов не нужен; на прежнем коде finish по несуществующему id
    терял результат → vision_stale_discarded)."""
    d = await _fresh(tmp_path)
    try:
        aid = await d.record_media_analysis(_analysis_rec("a1", "chat:1"))
        for i in range(3):
            await d.upsert_media_asset({
                "asset_id": f"fy{i}", "message_key": f"{CHAT_A}:{710+i}",
                "chat_id": CHAT_A, "tg_message_id": 710 + i,
                "asset_kind": "photo", "file_id": f"g{i}",
                "file_unique_id": f"v{i}", "size_variant": "large"})
        got = await d.record_media_analysis(_analysis_rec("a1", "chat:1"))
        assert got == aid
        ok = await d.finish_media_analysis(
            got, expected_revision=1, status="ready",
            ocr_blocks=[{"text": "текст", "channel": UNTRUSTED_DATA_CHANNEL}],
            visual_description="описание", completed_at=999)
        assert ok is True
        row = await d.get_media_analysis(got)
        assert row["status"] == "ready" and row["completed_at"] == 999
    finally:
        await d.close()


# ═══════════════ H-2: прод-шов renderer'а через сборку контекста ════════════

async def _pipeline_ready_analysis(tmp_path, monkeypatch, events: list):
    """Полный авто-конвейер до ready-анализа (двойники bot/transport) +
    перехват стадийных событий. Возвращает (db, msg)."""
    monkeypatch.setattr(mca_vision, "pipeline_stage_event",
                        lambda stage, outcome, **kw: events.append((stage,
                                                                   outcome,
                                                                   kw)))
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    await _save_message(db, 401, caption="смотрите что прислали")
    msg = _photo_message(tg_id=401, caption="смотрите что прислали")
    assets = await mca_vision.register_intake_assets(db, msg)
    store = mca_vision._job_store()
    mca_vision._RUNTIME["job_store"] = store
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    jobs = [j for j in await store.active() if j["status"] == "queued"]
    await store.mark_running(jobs[0]["job_id"])
    job = await store.get(jobs[0]["job_id"])
    calls: list = []
    await mca_vision.process_asset_job(
        job, db=db, bot=_FakeBot({"fid_1": PNG_BYTES}),
        transport=_transport_vision(calls))
    assert calls                                    # vision-вызов был ровно один
    return db, msg


@pytest.mark.asyncio
async def test_h2_renderer_block_in_built_context(tmp_path, monkeypatch):
    """Сквозной: полный конвейер → готовый анализ → РЕАЛЬНАЯ точка сборки
    контекста (build_chat_context) содержит блок фасада D9 (OCR-лейбл канала
    недоверенных данных + визуальное описание) вместо старого маркера;
    стадия consumers — честный success (потребители фактически есть)."""
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        events: list = []
        db, _msg = await _pipeline_ready_analysis(tmp_path, monkeypatch, events)
        try:
            assert ("consumers", "success",) in [
                (s, o) for s, o, _kw in events]

            rows = await db.get_recent_messages(CHAT_A, 10)
            out = await build_chat_context(db, rows, chat_id=CHAT_A)
            # Блок D9 на месте исходного поста: OCR через канал недоверенных
            # данных + описание + «два времени» (Распознано: …).
            assert OCR_LINE_LABEL in out
            assert UNTRUSTED_DATA_CHANNEL in out
            assert "привет от бота" in out
            assert DESC_LABEL in out
            assert "скриншот чата" in out
            assert "Распознано:" in out
            # Старый маркер вытеснен блоком фасада.
            assert "[медиа: photo" not in out
            # Прежняя сборка (без шва) маркер сохраняет — дельта видима.
            legacy = format_chat_context(rows)
            assert "[медиа: photo" in legacy and OCR_LINE_LABEL not in legacy
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_h2_pending_line_without_ready_analysis(tmp_path, monkeypatch):
    """Актив есть, готового анализа нет → честный pending-текст на месте
    исходного поста (не «[фото]» и не пустота)."""
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        db = await _fresh(tmp_path)
        try:
            mca_vision.bind_runtime(db)
            _cap_ok()
            await _save_message(db, 411)
            await mca_vision.register_intake_assets(
                db, _photo_message(tg_id=411))
            rows = await db.get_recent_messages(CHAT_A, 10)
            out = await build_chat_context(db, rows, chat_id=CHAT_A)
            assert PENDING_LINE in out
            assert "[медиа: photo" not in out
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_h2_gate_off_context_byte_identical(tmp_path, monkeypatch):
    """K1 OFF → байт-в-байт прежний контекст (старый маркер как есть);
    requested OFF (пер-чат тумблер владельца) → так же байт-в-байт."""
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        db = await _fresh(tmp_path)
        try:
            mca_vision.bind_runtime(db)
            _cap_ok()
            await _save_message(db, 421)
            await mca_vision.register_intake_assets(
                db, _photo_message(tg_id=421))
            rows = await db.get_recent_messages(CHAT_A, 10)
            legacy = format_chat_context(rows)
            assert "[медиа: photo" in legacy

            monkeypatch.setattr(mca_gates, "vision_enabled", lambda: False)
            out_k1 = await build_chat_context(db, rows, chat_id=CHAT_A)
            assert out_k1 == legacy                      # байт-в-байт

            monkeypatch.setattr(mca_gates, "vision_enabled", lambda: True)

            async def _off(chat_id=None):
                return False
            monkeypatch.setattr(mca_vision, "resolve_requested", _off)
            out_req = await build_chat_context(db, rows, chat_id=CHAT_A)
            assert out_req == legacy                     # байт-в-байт
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_h2_text_only_window_parity(tmp_path, monkeypatch):
    """Окно без медиа: сборка со швом байт-в-байт равна прежней (шов ничего
    не добавляет и не меняет)."""
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        db = await _fresh(tmp_path)
        try:
            # media_type='' — строка текста (NOT NULL-колонка; пусто →
            # не медиа-строка контекста).
            await _save_message(db, 431, text="обычный текст", media_type="")
            rows = await db.get_recent_messages(CHAT_A, 10)
            legacy = format_chat_context(rows)
            assert legacy
            out = await build_chat_context(db, rows, chat_id=CHAT_A)
            assert out == legacy
        finally:
            await db.close()


# ═══════════════ H-2/п.2: честная стадия consumers ══════════════════════════

def test_consumers_stage_outcome_honest(monkeypatch):
    """success — только при фактических потребителях (мастер ON: контекстный
    шов + tool); мастер OFF → honest skipped/vision_disabled (не success)."""
    monkeypatch.setattr(mca_gates, "vision_enabled", lambda: True)
    assert mca_vision.consumers_stage_outcome() == ("success", None)
    monkeypatch.setattr(mca_gates, "vision_enabled", lambda: False)
    assert mca_vision.consumers_stage_outcome() == ("skipped",
                                                    "vision_disabled")


# ═══════════════ M-1: probe success без противоречивого reason ══════════════

@pytest.mark.asyncio
async def test_m1_probe_success_has_no_unsupported_reason():
    """2xx → ok-вердикт с отсутствующим reason ('' → reason_code=None в
    событиях): /api/vision/state при работающем vision не отвечает
    «vision_unsupported»."""
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        async def _t(url, *, payload, headers, timeout):
            return 200, {"choices": [{"message": {"content": "ок"}}]}

        verdict = await mca_vision.probe_connection(transport=_t)
        assert verdict.capability == "ok" and verdict.image_input is True
        assert not verdict.reason
        state = await mca_vision.resolve_effective_state()
        assert state.effective_enabled is True
        assert not state.reason


# ═══════════════ M-2: tool-pending ≠ deferred ═══════════════════════════════

@pytest.mark.asyncio
async def test_m2_tool_pending_reason_is_wait_budget(tmp_path):
    """Бюджет ограниченного ожидания исчерпан → reason по семантике
    (`deadline_exceeded`), не `vision_deferred` (код переполнения очереди
    D20). Статус честен: pending, job_linked."""
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        db = await _fresh(tmp_path)
        try:
            mca_vision.bind_runtime(db)
            _cap_ok()
            await _save_message(db, 441)
            await mca_vision.register_intake_assets(
                db, _photo_message(tg_id=441))
            mca_vision._PENDING_TRIGGERS.clear()
            res = await mca_vision.recognize_target(
                db, chat_id=CHAT_A, reply_tg_id=441, wait_seconds=0)
            assert res["status"] == "pending" and res["job_linked"]
            assert res["reason"] == "deadline_exceeded"
            assert res["reason"] != "vision_deferred"
        finally:
            await db.close()
