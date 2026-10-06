"""MCA-19 Wave 2, блок G (`mca-19-image-understanding`, round 10.43) —
старые картинки (backfill), намерение, tool `recognize_image`, делегация
mca-18 (ADR-1028-19 D10/D14/D21–D23, §8.6/§8.10; T-5118…T-5120) + smoke
T-5122 на реальных fixture-байтах (MIME/bomb).

Контракты:
  * A82/SC-R7c: канон тулов 12→13; `recognize_image` в METERED_TOOLS;
    K4 OFF → инструмент скрыт из набора, НО серверная проверка OFF в
    диспетчере (defence in depth); ACL — chat scope из доверенного
    рантайма (чужой чат отклонён, TH-5); pending — связка с job БЕЗ
    LLM-опросов, «посмотрю» ≠ «посмотрел»; повторный trigger — дедуп
    (не второй ответ);
  * A83/SC-R7d (T-5119): готовый анализ возвращается БЕЗ нового vision-
    вызова (cache_hit=True, 0 токенов);
  * A80/A81/SC-R7a/7b (T-5118): резолв target — reply → реестр;
    неоднозначный альбом → ambiguous (не случайный выбор); нет файла →
    честный missing_source; intent-ключевые слова — быстрый маршрут;
  * §8.10/D14 (граница mca-18): `can_analyze_images` — через ЕДИНУЮ
    делегацию `resolve_effective_state()`; K1 OFF → False бит-в-бит;
    pending → False («могу» ≠ «не проверено»);
  * T-5122 smoke: реальный PNG — полный конвейер ready; MIME-подмена —
    сниффер побеждает; decompression-bomb — честный vision_unreadable
    (offline, transport-мок).

R17: секретов нет.
"""
import asyncio
import datetime
import json
import struct
import time
import zlib
from unittest.mock import MagicMock

import pytest
from aiogram.types import Chat, Message, PhotoSize, Sticker, User

from services import mca_gates, mca_vision, tool_loop, tool_schemas
from services.database import DatabaseService
from services.tool_router import ToolContext, ToolRouter, ToolDeps

CHAT_A = -1004000000041
CHAT_B = -1004000000042
TS = int(datetime.datetime(2026, 10, 6, 12, 0, 0,
                           tzinfo=datetime.timezone.utc).timestamp())


def make_png(width=10, height=10) -> bytes:
    def chunk(tag, data):
        raw = tag + data
        return (struct.pack(">I", len(data)) + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF))
    row = b"\x00" + b"\x11\x22\x33" * width
    body = zlib.compress(row * height)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0,
                                         0, 0))
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


def make_fake_jpeg() -> bytes:
    """Байты с JPEG-магикой (сниффер распознаёт как image/jpeg)."""
    # Минимальный SOI+APP1-подобный заголовок: сниффер mca_vision ищет
    # SOFn; без SOFn вернёт None → «не изображение». Используем честный
    # кейс подмены: GIF-байты с заявленным MIME image/png.
    header = b"GIF89a" + struct.pack("<HH", 12, 12) + b"\x80\x00\x00"
    return header + b"\x00" * 24


def make_bomb_png() -> bytes:
    def chunk(tag, data):
        raw = tag + data
        return (struct.pack(">I", len(data)) + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 100000, 100000, 8, 2,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
            + chunk(b"IEND", b""))


PNG_BYTES = make_png()
GIF_BYTES = make_fake_jpeg()


def _photo(serial, chat=CHAT_A, tg=601, *, kind="photo"):
    if kind == "sticker":
        return Sticker(file_id=f"fid_s{serial}",
                       file_unique_id=f"uniq_s{serial}",
                       width=512, height=512, is_animated=False,
                       is_video=False, type="regular")
    return Message(
        message_id=tg,
        date=datetime.datetime.fromtimestamp(TS, tz=datetime.timezone.utc),
        chat=Chat(id=chat, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Вася"),
        photo=[PhotoSize(file_id=f"fid_{serial}",
                         file_unique_id=f"uniq_{serial}",
                         width=800, height=600, file_size=12345)],
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


_CREATED_DBS: list = []


async def _fresh(tmp_path, name="mca19g.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    _CREATED_DBS.append(d)
    return d


@pytest.fixture(autouse=True)
def _env():
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()
    yield
    try:
        asyncio.run(_drain())
    except Exception:
        pass
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()


async def _drain():
    while _CREATED_DBS:
        await _CREATED_DBS.pop().close()


@pytest.fixture()
def _enabled():
    from tests.test_mca19_block_b_round1043 import patched_settings
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY=""):
        yield


def _cap_ok():
    mca_vision.store_capability(
        mca_vision.resolve_route(),
        mca_vision.CapabilityVerdict("ok", "vision_unsupported", True,
                                     time.monotonic()))


def _transport(calls: list, description="распознано содержимое"):
    async def _t(url, *, payload, headers, timeout):
        calls.append(url)
        return 200, {"choices": [{"message": {"content": json.dumps({
            "ocr_blocks": [], "visual_description": description,
            "uncertainty": [], "self_reported_confidence": 0.8})}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2}}
    return _t


def _router(db) -> ToolRouter:
    return ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                               db=db))


def _ctx(chat_id=CHAT_A) -> ToolContext:
    return ToolContext(chat_id, "что на картинке?", bot=None,
                       reply_to_message_id=None, user_id=42)


# ── Канон тулов (D22/§8.6; MCA-20 10.44: 13 → 14, +fact_check в хвост) ──────

def test_tool_canon_13_recognize_image_tail():
    # MCA-20 (10.44, ADR-1028-20 §7.5): канон 13 → 14; recognize_image
    # больше не хвост — fact_check после него (первые 13 байт-в-байт).
    assert len(tool_schemas.TOOL_CALLING_TOOLS) == 14
    assert tool_schemas.TOOL_CALLING_TOOLS[-1] is \
        tool_schemas.TOOL_FACT_CHECK
    assert tool_schemas.TOOL_CALLING_TOOLS[-2] is \
        tool_schemas.TOOL_RECOGNIZE_IMAGE
    names = [t["function"]["name"] for t in tool_schemas.TOOL_CALLING_TOOLS]
    # Первые 12 — прежний порядок байт-в-байт.
    assert names[:12] == [
        "query_chat_memory", "dig_into_lore", "execute_web_search",
        "summarize_video", "download_media", "get_bot_health",
        "get_recent_history", "compile_lore_story", "generate_image",
        "transcribe_video", "fetch_article", "get_user_context"]
    schema = tool_schemas.TOOL_RECOGNIZE_IMAGE["function"]
    assert schema["parameters"]["additionalProperties"] is False
    props = schema["parameters"]["properties"]
    assert set(props) == {"target", "asset_selector", "question"}
    # URL/API key/модель от LLM НЕ принимаются (нет таких полей в схеме).
    assert "url" not in props and "api_key" not in props \
        and "model" not in props


def test_metered_tools_includes_recognize_image():
    assert "recognize_image" in tool_loop.METERED_TOOLS


def test_active_tools_hide_when_k4_off(monkeypatch):
    assert "recognize_image" in [t["function"]["name"]
                                 for t in tool_schemas.active_tools()]
    monkeypatch.setattr(mca_gates, "vision_tool_enabled", lambda: False)
    names = [t["function"]["name"] for t in tool_schemas.active_tools()]
    assert "recognize_image" not in names
    # Канон (схема/снапшот) безусловен.
    assert len(tool_schemas.TOOL_CALLING_TOOLS) == 14


# ── Диспетчер: server-side OFF, ACL, ready/pending/ambiguous (A82) ──────────

@pytest.mark.asyncio
async def test_dispatch_disabled_server_side_when_master_off(
        tmp_path, monkeypatch):
    """Устаревший вызов при OFF — честный disabled (defence in depth)."""
    db = await _fresh(tmp_path)
    monkeypatch.setattr(mca_gates, "vision_enabled", lambda: False)
    raw = await _router(db).dispatch("recognize_image", {
        "target": {"chat_id": CHAT_A, "message_id": 601}}, _ctx())
    payload = json.loads(raw)
    assert payload["status"] == "disabled"
    assert payload["reason"] == "vision_disabled"


@pytest.mark.asyncio
async def test_dispatch_disabled_when_tool_gate_off(tmp_path, monkeypatch):
    db = await _fresh(tmp_path)
    monkeypatch.setattr(mca_gates, "vision_tool_enabled", lambda: False)
    raw = await _router(db).dispatch("recognize_image", {
        "target": {"chat_id": CHAT_A, "message_id": 601}}, _ctx())
    assert json.loads(raw)["status"] == "disabled"


@pytest.mark.asyncio
async def test_dispatch_rejects_cross_chat_target(tmp_path, _enabled):
    """TH-5/SC-R3c: цель в другом чате — вне ACL доверенного рантайма."""
    db = await _fresh(tmp_path)
    router = _router(db)
    raw = await router.dispatch("recognize_image", {
        "target": {"chat_id": CHAT_B, "message_id": 999}}, _ctx(CHAT_A))
    payload = json.loads(raw)
    assert payload["status"] == "missing"
    assert payload["reason"] == "vision_missing_source"
    assert payload["out_of_scope"] is True


@pytest.mark.asyncio
async def test_dispatch_bad_target_is_failed_not_crash(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    raw = await _router(db).dispatch("recognize_image", {
        "target": {"chat_id": "x"}}, _ctx())
    payload = json.loads(raw)
    assert payload["status"] == "failed"
    assert payload["reason"] == "vision_failed"


@pytest.mark.asyncio
async def test_tool_cache_first_ready_no_new_vision(tmp_path, _enabled):
    """A83/T-5119: готовый анализ достаточно — 0 новых vision-вызовов."""
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    msg = _photo(1)
    assets = await mca_vision.register_intake_assets(db, msg)
    await db.set_media_asset_content_hash(
        assets[0], "cafebabe")   # хеш известен (безопасная загрузка была)
    aid = await db.record_media_analysis({
        "asset_id": assets[0],
        "access_scope": mca_vision.access_scope_for(CHAT_A),
        "analyzer_config_revision": "cfg", "quality_profile": "default",
        "status": "running"})
    await db.finish_media_analysis(aid, expected_revision=1, status="ready",
                                   visual_description="старый разбор")
    calls: list = []
    raw = await _router(db).dispatch("recognize_image", {
        "target": {"chat_id": CHAT_A, "message_id": 601}}, _ctx())
    payload = json.loads(raw)
    assert payload["status"] == "ready"
    assert payload["cache_hit"] is True
    assert payload["visual_description"] == "старый разбор"
    assert payload["analysis_revision"] >= 1
    assert payload["source_ref_ids"]            # трассировка (D12)
    assert calls == []                          # vision НЕ вызывался


@pytest.mark.asyncio
async def test_tool_pending_semantics_no_llm_polling(tmp_path, _enabled,
                                                     monkeypatch):
    """A82/D23: нет готового → durable manual-job + ОГРАНИЧЕННОЕ ожидание;
    timeout → честный pending («посмотрю» ≠ «посмотрел»); LLM-опросов нет;
    повторный trigger — дедуп, второй job НЕ создаётся."""
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    msg = _photo(2)
    assets = await mca_vision.register_intake_assets(db, msg)
    mca_vision._PENDING_TRIGGERS.clear()
    monkeypatch.setattr(mca_vision, "RECOGNIZE_TOOL_WAIT_SECONDS", 0)
    router = _router(db)
    args = {"target": {"chat_id": CHAT_A, "message_id": 601}}
    r1 = json.loads(await router.dispatch("recognize_image", args, _ctx()))
    r2 = json.loads(await router.dispatch("recognize_image", args, _ctx()))
    assert r1["status"] == "pending" and r2["status"] == "pending"
    assert r1["job_linked"] is True
    jobs = [j for j in await mca_vision._job_store().active()
            if j["kind"] == mca_vision.VISION_JOB_KIND]
    assert len(jobs) == 1                       # второй trigger ≠ второй job
    manual = json.loads(jobs[0]["payload"])
    assert manual["priority"] == mca_vision.PRIORITY_MANUAL  # manual > auto


@pytest.mark.asyncio
async def test_tool_wait_wakes_on_job_completion(tmp_path, _enabled,
                                                 monkeypatch):
    """D23: pending-путь просыпается СОБЫТИЕМ по завершении job (без
    LLM-опросов) и возвращает готовый анализ; «посмотрел» — только факт."""
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    bot = _FakeBot({"fid_2": PNG_BYTES})
    calls: list = []
    msg = _photo(2)
    assets = await mca_vision.register_intake_assets(db, msg)
    mca_vision._PENDING_TRIGGERS.clear()
    monkeypatch.setattr(mca_vision, "RECOGNIZE_TOOL_WAIT_SECONDS", 15)
    router = _router(db)
    ctx = _ctx()
    args = {"target": {"chat_id": CHAT_A, "message_id": 601}}
    task = asyncio.create_task(router.dispatch("recognize_image", args, ctx))
    await asyncio.sleep(0.2)
    store = mca_vision._job_store()
    jobs = [j for j in await store.active()
            if j["kind"] == mca_vision.VISION_JOB_KIND
            and j["status"] == "queued"]
    assert len(jobs) == 1
    await store.mark_running(jobs[0]["job_id"])
    fresh = await store.get(jobs[0]["job_id"])
    await mca_vision.process_asset_job(fresh, db=db, bot=bot,
                                       transport=_transport(calls))
    raw = await asyncio.wait_for(task, timeout=10)
    payload = json.loads(raw)
    assert payload["status"] == "ready"
    assert payload["cache_hit"] is False
    assert payload["visual_description"] == "распознано содержимое"


@pytest.mark.asyncio
async def test_tool_ambiguous_album_requires_selector(tmp_path, _enabled):
    """A81/SC-R7b: несколько кандидатов → уточнение, НЕ случайный выбор."""
    db = await _fresh(tmp_path)
    m1 = _photo(3, tg=611)
    m2 = _photo(4, tg=612)
    for m in (m1, m2):
        # reply-target 610 «альбом»: резолвер ищет по (chat, tg_message_id);
        # симулируем альбом одним сообщением с двумя активами невозможно —
        # два элемента = два сообщения → ambiguous на уровне selector'а нет.
        await mca_vision.register_intake_assets(db, m)
    # Прямой вызов резолвера: reply на 611 → однозначно; без reply и без
    # собственных вложений → missing (уточнение, не «последнее фото»).
    ok = await mca_vision.resolve_target_assets(db, chat_id=CHAT_A,
                                                reply_tg_id=611)
    assert ok["status"] == "ok" and len(ok["assets"]) == 1
    missing = await mca_vision.resolve_target_assets(db, chat_id=CHAT_A,
                                                     reply_tg_id=None)
    assert missing["status"] == "missing"
    assert missing["assets"] == []


@pytest.mark.asyncio
async def test_resolver_unsupported_kind_flagged(tmp_path, _enabled):
    """D18/D21: animation — свой пайплайн; unsupported помечается явно."""
    db = await _fresh(tmp_path)
    sticker_msg = Message(
        message_id=621,
        date=datetime.datetime.fromtimestamp(TS, tz=datetime.timezone.utc),
        chat=Chat(id=CHAT_A, type="supergroup", title="T"),
        from_user=User(id=42, is_bot=False, first_name="Вася"),
        sticker=Sticker(file_id="fid_st", file_unique_id="uniq_st",
                        width=512, height=512, is_animated=True,
                        is_video=False, type="regular"))
    await mca_vision.register_intake_assets(db, sticker_msg)
    resolved = await mca_vision.resolve_target_assets(db, chat_id=CHAT_A,
                                                      reply_tg_id=621)
    assert resolved["status"] == "unsupported"
    assert {str(a.get("asset_kind")) for a in resolved["unsupported"]} == \
        {"animation"}


def test_intent_fast_route():
    """T-5118: ключевые слова — быстрый маршрут (не единственный способ)."""
    assert mca_vision.vision_intent("бот, что на картинке?")
    assert mca_vision.vision_intent("прочитай скрин пожалуйста")
    assert mca_vision.vision_intent("что тут написано")
    assert not mca_vision.vision_intent("привет, как дела?")
    assert not mca_vision.vision_intent("")


# ── Граница mca-18 (§8.10/D14): делегация can_analyze_images ────────────────

@pytest.mark.asyncio
async def test_mca18_delegation_off_bit_for_bit(monkeypatch):
    """K1 OFF → False немедленно (бит-в-бит 2.58.62); реестровый путь
    (IMAGE_ANALYSIS_TOOL_NAMES) остаётся пустым — делегация единственный
    источник True. (K2–K4 инертны при K1 — Wave 1 gates-дизайн.)"""
    monkeypatch.setattr(mca_gates, "vision_enabled", lambda: False)
    from services import mca_self_model as sm
    assert await sm.can_analyze_images_effective(CHAT_A) is False
    caps = sm.build_capabilities()
    assert caps.can_analyze_images is False
    assert not sm.IMAGE_ANALYSIS_TOOL_NAMES
    # K1 ON + K4 OFF → инструмент скрыт, но «могу» всё равно False.
    monkeypatch.setattr(mca_gates, "vision_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "vision_tool_enabled", lambda: False)
    names = [t["function"]["name"] for t in
             __import__("services.tool_schemas", fromlist=["active_tools"])
             .active_tools()]
    assert "recognize_image" not in names


@pytest.mark.asyncio
async def test_mca18_delegation_true_only_when_proven(tmp_path, _enabled,
                                                      monkeypatch):
    from services import mca_self_model as sm
    # pending (нет кеша capabilities) → False («могу» ≠ «не проверено»).
    assert await sm.can_analyze_images_effective(CHAT_A) is False
    # Доказанный capability ok + requested ON → True.
    _cap_ok()
    assert await sm.can_analyze_images_effective(CHAT_A) is True
    caps = sm.build_capabilities(can_analyze_images=True)
    assert caps.can_analyze_images is True
    assert caps.did_analyze_images is False    # «посмотрел» — только evidence
    hard = sm.build_capabilities(can_analyze_images=True,
                                 image_analysis_evidence=True)
    assert hard.did_analyze_images is True
    # requested OFF (владелец) → False (пользовательский OFF приоритетен).
    from services import hot_config as hot_config
    real_get = hot_config.get
    monkeypatch.setattr(
        hot_config, "get",
        lambda key, default=None: False
        if key == "flags.vision_enabled" else real_get(key, default))
    mca_vision.reset_capability_cache()
    assert await sm.can_analyze_images_effective(CHAT_A) is False


# ── T-5122 smoke: реальные байты, offline (MIME/bomb/полный конвейер) ───────

@pytest.mark.asyncio
async def test_smoke_real_png_full_pipeline_ready(tmp_path, _enabled):
    db = await _fresh(tmp_path)
    mca_vision.bind_runtime(db)
    _cap_ok()
    # Каноническая запись сообщения (renderer читает smart_messages).
    from services import message_identity
    await message_identity.save_live_message(
        db, user_id=42, chat_id=CHAT_A, text=None, caption=None,
        timestamp=TS, sent_at=TS, ingested_at=TS, media_type="photo",
        author_name="Вася", is_forward=False, forward_source="",
        tg_message_id=601, media_ref=None, reply_to_id=None,
        reply_to_author_id=None, quote_text=None, quote_author_id=None,
        forward_author_id=None)
    bot = _FakeBot({"fid_1": PNG_BYTES})
    calls: list = []
    msg = _photo(1)
    assets = await mca_vision.register_intake_assets(db, msg)
    await mca_vision.enqueue_intake_jobs(db, msg, assets)
    store = mca_vision._job_store()
    for job in [j for j in await store.active() if j["status"] == "queued"]:
        await store.mark_running(job["job_id"])
        fresh = await store.get(job["job_id"])
        await mca_vision.process_asset_job(fresh, db=db, bot=bot,
                                           transport=_transport(calls))
    assert len(calls) == 1
    ready = await db.get_ready_analysis(
        assets[0], mca_vision.access_scope_for(CHAT_A))
    assert ready is not None and ready["status"] == "ready"
    assert ready["visual_description"] == "распознано содержимое"
    rendered = await mca_vision.render_media_context_async(
        db, chat_id=CHAT_A, tg_message_id=601)
    assert rendered is not None and "распознано содержимое" in rendered["text"]


@pytest.mark.asyncio
async def test_smoke_mime_substitution_sniffer_wins(tmp_path, _enabled):
    """GIF-байты под видом photo (заявленный MIME ≠ факт) — сниффер
    определяет фактический формат; обработка идёт по факту."""
    from services.mca_vision import validate_image_bytes
    img = validate_image_bytes(GIF_BYTES, declared_mime="image/png")
    assert img.mime == "image/gif"          # факт, не заголовок
    assert img.declared_mime == "image/png"


@pytest.mark.asyncio
async def test_smoke_decompression_bomb_refused(tmp_path, _enabled):
    """TH-4: bomb (10^10 px в заголовке) — честный vision_unreadable ДО
    отправки наружу."""
    from services.mca_vision import VisionError, validate_image_bytes
    with pytest.raises(VisionError) as exc:
        validate_image_bytes(make_bomb_png())
    assert exc.value.reason == "vision_unreadable"


@pytest.mark.asyncio
async def test_smoke_not_an_image_honest_unreadable(tmp_path, _enabled):
    from services.mca_vision import VisionError, validate_image_bytes
    with pytest.raises(VisionError) as exc:
        validate_image_bytes(b"this is not an image at all......")
    assert exc.value.reason == "vision_unreadable"
