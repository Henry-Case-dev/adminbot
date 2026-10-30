"""ASAP-VISION-SYNC-01 CORE — контракт готовности медиа, выходной контракт
Vision и watchdog жизненного цикла (offline, без живых отправок).

TEST-LIFECYCLE: CONTRACT/REGRESSION owner=ASAP-VISION-SYNC-01
(plans/current_task.md §0–§9 + доп. требование владельца «watchdog»).

Покрытие (сценарии §8, ядро): 1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14, 15, 16,
17, 20 и сценарии watchdog 21–25.

Границы: без Telegram, без сети. Vision-транспорт — контрактный мок.
Сценарии 7/8/9/18/19 (соседнее фото без зависимости, ambiguity двух фото,
альбом-полнота, сводки/память/инициатива, cross-chat) — следующая волна
(зафиксировано в отчёте w8-vision-sync-core.md).
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager

import pytest
import pytest_asyncio

from config.settings import settings
from services import factcheck_service as fcs
from services import hot_config as hot
from services import mca_vision
from services import media_readiness as mr
from services.database import DatabaseService
from services.task_supervisor import TaskJobStore

pytestmark = [pytest.mark.asap3]

CHAT = -1009000001
CHAT2 = -1009000002
USER_ID = 4242
NOW = int(time.time())

VISION_BASE = "http://vlm.local/v1"


@contextmanager
def patched_settings(**kw):
    saved = {k: getattr(settings, k) for k in kw}
    for key, value in kw.items():
        object.__setattr__(settings, key, value)
    try:
        yield
    finally:
        for key, value in saved.items():
            object.__setattr__(settings, key, value)


@pytest.fixture(autouse=True)
def _vision_enabled():
    mca_vision.reset_capability_cache()
    mca_vision.reset_route_param_memo()
    hot.set_config_cache(None)
    with patched_settings(VISION_ENABLED=True,
                          VISION_API_BASE_URL=VISION_BASE,
                          VISION_MODEL="test-vlm",
                          VISION_API_KEY="test-key",
                          VISION_API_TYPE="openai_compatible"):
        yield
    mca_vision.reset_capability_cache()
    mca_vision.reset_route_param_memo()
    hot.set_config_cache(None)


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "vision-sync.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


# ── обвязка БД ──────────────────────────────────────────────────────────────

async def _add_message(db, tg_id: int, *, chat_id: int = CHAT,
                       text: str = "", media_type: str = "text",
                       caption: str = "", reply_to=None,
                       media_group=None, author: str = "Сергей",
                       ts: int | None = None):
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, sent_at, media_type, caption, author_name, is_forward, "
        "tg_message_id, media_group_id) VALUES (?,?,?,?,?,?,?,?,?,0,?,?)",
        (USER_ID, int(chat_id), text, reply_to, ts or NOW, ts or NOW,
         media_type, caption or "", author, int(tg_id), media_group))
    await db.db.commit()
    return int(cursor.lastrowid)


async def _add_image(db, tg_id: int, *, chat_id: int = CHAT, serial: int = 1,
                     media_group=None, kind: str = "photo",
                     content_hash: str = ""):
    asset_id = mca_vision.make_asset_id(chat_id, tg_id, f"uniq_{serial}",
                                        "default")
    await db.upsert_media_asset({
        "asset_id": asset_id, "chat_id": int(chat_id),
        "tg_message_id": int(tg_id), "asset_kind": kind,
        "file_id": f"fid_{serial}", "file_unique_id": f"uniq_{serial}",
        "size_variant": "default", "mime": "image/jpeg",
        "byte_size": 1234, "width": 800, "height": 600,
        "media_group_id": media_group, "revision": 1})
    if content_hash:
        await db.set_media_asset_content_hash(asset_id, content_hash)
    return asset_id


async def _record(db, asset_id: str, *, chat_id: int = CHAT,
                  status: str = "running", ocr=None, description: str = "",
                  uncertainty=None, error_reason=None, model: str = "test-vlm",
                  config_revision: str = "cfg1"):
    analysis_id = await db.record_media_analysis({
        "asset_id": asset_id,
        "access_scope": mca_vision.access_scope_for(chat_id),
        "analysis_schema_version": mca_vision.ANALYSIS_SCHEMA_VERSION,
        "analyzer_provider": "dedicated", "analyzer_model": model,
        "analyzer_config_revision": config_revision,
        "prompt_version": mca_vision.PROMPT_VERSION,
        "quality_profile": mca_vision.QUALITY_PROFILE_DEFAULT,
        "status": status, "config_revision": config_revision, "revision": 1})
    if status != "running":
        await db.finish_media_analysis(
            analysis_id, expected_revision=1, status=status,
            ocr_blocks=ocr, visual_description=description or None,
            uncertainty=uncertainty, error_reason=error_reason)
    return analysis_id


async def _ready_analysis(db, asset_id: str, *, text: str = "Перевод: 1000",
                          chat_id: int = CHAT, description: str = "скриншот"):
    return await _record(db, asset_id, chat_id=chat_id, status="ready",
                         ocr=[{"text": text, "channel": "untrusted_data"}],
                         description=description)


async def _store(db):
    return TaskJobStore(db)


class Transport:
    """Контрактный мок Vision-транспорта (очередь сценариев ответа)."""

    def __init__(self, script=None, default=None):
        self.calls: list = []
        self._script = list(script or [])
        self._default = default

    async def __call__(self, url, *, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload,
                           "headers": dict(headers or {})})
        item = self._script.pop(0) if self._script else self._default
        if isinstance(item, BaseException):
            raise item
        return item


def _body(content: str, *, finish_reason: str = "stop",
          reasoning_tokens: int = 0, output_tokens: int = 0) -> dict:
    usage = {"prompt_tokens": 10, "completion_tokens": output_tokens}
    if reasoning_tokens:
        usage["completion_tokens_details"] = {"reasoning_tokens":
                                              reasoning_tokens}
    return {"choices": [{"message": {"role": "assistant",
                                     "content": content},
                         "finish_reason": finish_reason}],
            "usage": usage}


def _analysis_json(text: str) -> str:
    return json.dumps({"ocr_blocks": [{"text": text}],
                       "visual_description": "скриншот переписки",
                       "uncertainty": []}, ensure_ascii=False)


def _image_bytes() -> bytes:
    import struct
    import zlib
    def _chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
            + _chunk(b"IEND", b""))


# ════════════════════════════════════════════════════════════════════════════
# Сценарии §8
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc1_photo_with_caption_factcheck_uses_ocr(db):
    """§8.1: фото с подписью «фактчек» — OCR готов → тезис из изображения
    доходит до материала проверки (источник — текст картинки, не подпись)."""
    await _add_message(db, 100, media_type="photo", caption="фактчек")
    asset_id = await _add_image(db, 100, serial=1)
    await _ready_analysis(db, asset_id, text="Цена выросла на 30%")

    media = await fcs.load_claim_media(db, CHAT, 100,
                                       message_ids=[100], expected_images=1)
    assert media.image_present is True
    assert media.image_analyzed is True
    assert media.pending_count == 0
    assert "Цена выросла на 30%" in media.text_suffix
    assert "OCR" in media.text_suffix

    publication = await fcs.resolve_claim_publication(
        db, CHAT, 100, base_text="фактчек")
    assert "Цена выросла на 30%" in publication.text
    assert publication.media_dependency() == "ready"
    assert publication.admission_blocked_by_pending_media() is False


@pytest.mark.asyncio
async def test_sc2_photo_then_separate_factcheck_message(db):
    """§8.2: сначала фото, затем отдельное «фактчек» — находится правильное
    фото из той же ветки (adjacent_before), авторство сохранено."""
    await _add_message(db, 200, media_type="photo", author="Аня")
    asset_id = await _add_image(db, 200, serial=2)
    await _ready_analysis(db, asset_id, text="Курс доллара 92 рубля")
    await _add_message(db, 201, text="бот, фактчек")

    resolved = await mr.resolve_target_media(
        db, chat_id=CHAT, message_id=201, allow_adjacent=True)
    assert resolved["association_status"] == mr.ASSOC_RESOLVED
    assert resolved["association_kind"] == mr.ASSOC_ADJACENT_BEFORE
    assert resolved["source_message_ids"] == (200,)
    assert resolved["assets"][0]["asset_id"] == asset_id

    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=201,
        query="бот, фактчек", consumer="factcheck", wait_seconds=0.0,
        allow_adjacent=True)
    assert readiness is not None and readiness.ready
    assert "Курс доллара 92 рубля" in readiness.evidence_block()
    assert readiness.analysis_revision


@pytest.mark.asyncio
async def test_sc3_request_then_photo_resumes_once(db):
    """§8.3: «проверю картинку, сейчас скину» → фото: ожидающее намерение
    связывается durable и возобновляется РОВНО один раз."""
    await _add_message(db, 300, text="сейчас скину скрин, разбери")
    intent = await mr.register_pending_intent(
        db, chat_id=CHAT, trigger_message_id=300,
        consumer="direct", question="сейчас скину скрин, разбери",
        user_id=USER_ID)
    assert intent.get("job_id")

    await _add_message(db, 301, media_type="photo")
    asset_id = await _add_image(db, 301, serial=3)
    linked = await mr.link_pending_intent_for_message(
        db, chat_id=CHAT, tg_message_id=301, media_group_id=None,
        asset_ids=[asset_id])
    assert linked is not None
    assert linked["trigger_message_id"] == 300
    assert linked["tg_message_id"] == 301
    assert linked["question"] == "сейчас скину скрин, разбери"

    first = await mr.claim_resume_for_turn(db, chat_id=CHAT, message_id=301)
    assert first is not None and first["resumed"] is True
    second = await mr.claim_resume_for_turn(db, chat_id=CHAT, message_id=301)
    assert second is None          # ровно одно возобновление


@pytest.mark.asyncio
async def test_sc4_reply_to_photo_found_by_reply_id(db):
    """§8.4: reply на чужую фотографию — источник найден по
    reply_to_message_id, чужой чат не участвует."""
    await _add_message(db, 400, media_type="photo", author="Слава")
    asset_id = await _add_image(db, 400, serial=4)
    await _ready_analysis(db, asset_id, text="Скрин заказа №4411")
    await _add_message(db, 401, text="что тут написано?", reply_to=400)
    # тот же tg_id в другом чате — изоляция
    await _add_message(db, 400, chat_id=CHAT2, media_type="photo")
    await _add_image(db, 400, chat_id=CHAT2, serial=5)

    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=401, reply_to_message_id=400,
        query="что тут написано?", consumer="direct", wait_seconds=0.0,
        own_media=False, reply_media=True)
    assert readiness.association_kind == mr.ASSOC_REPLY
    assert readiness.asset_id == asset_id
    assert "Скрин заказа №4411" in readiness.evidence_block()


@pytest.mark.asyncio
async def test_sc5_quote_has_priority_over_plain_reply(db):
    """§8.5: цитата фрагмента рядом с фото — приоритет явной связи (quote),
    цитата сохраняется в свидетельстве."""
    await _add_message(db, 500, media_type="photo")
    asset_id = await _add_image(db, 500, serial=6)
    await _ready_analysis(db, asset_id, text="Итого: 41 200 руб.")
    await _add_message(db, 501, text="вот про эту строку", reply_to=500)

    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=501, reply_to_message_id=500,
        quote_text="Итого: 41 200", query="про эту строку",
        consumer="direct", wait_seconds=0.0,
        own_media=False, reply_media=True)
    assert readiness.association_kind == mr.ASSOC_QUOTE
    block = readiness.evidence_block()
    assert 'association="quote"' in block
    assert "Итого: 41 200" in block


@pytest.mark.asyncio
async def test_sc6_photo_and_caption_waits_for_vision(db):
    """§8.6: фото и подпись в одном сообщении — pending НЕ отдаётся как
    готовый разбор; Writer получает честное «содержимое неизвестно»."""
    await _add_message(db, 600, media_type="photo", caption="что на скрине?")
    asset_id = await _add_image(db, 600, serial=7)
    await _record(db, asset_id, status="running")     # анализ не завершён

    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=600, caption="что на скрине?",
        query="что на скрине?", consumer="direct", wait_seconds=0.0,
        enqueue=False)
    assert readiness is not None
    assert readiness.association_kind == mr.ASSOC_OWN_CAPTION
    assert readiness.pending is True
    assert readiness.ocr_blocks == ()
    block = readiness.evidence_block()
    assert 'status="pending"' in block
    assert "НЕИЗВЕСТНО" in block
    assert "ничего нет" in block


@pytest.mark.asyncio
async def test_sc10_single_flight_enqueues_one_analysis(db):
    """§8.10: два обращения к одному активу — одна durable-задача (один
    Vision-вызов), без второго исполнителя."""
    asset = {"asset_id": await _add_image(db, 700, serial=8),
             "tg_message_id": 700, "asset_kind": "photo",
             "file_id": "fid_8", "media_group_id": ""}
    store = await _store(db)
    first = await mca_vision.enqueue_asset_analysis(db, asset, chat_id=CHAT)
    second = await mca_vision.enqueue_asset_analysis(db, asset, chat_id=CHAT)
    jobs = [j for j in await store.active()
            if j.get("kind") == mca_vision.VISION_JOB_KIND]
    assert len(jobs) == 1
    assert first["job_id"] == second["job_id"]
    assert jobs[0]["coalesce_key"] == f"vision:asset:{asset['asset_id']}"


@pytest.mark.asyncio
async def test_sc11_vision_finishes_after_l1_before_writer(db):
    """§8.11: Vision завершился после L1, но до Writer — финальный payload
    содержит OCR АКТУАЛЬНОЙ ревизии (старый pending-снимок заменяется)."""
    await _add_message(db, 800, media_type="photo", caption="разбери скрин")
    asset_id = await _add_image(db, 800, serial=9)
    analysis_id = await _record(db, asset_id, status="running")

    before_l1 = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=800, caption="разбери скрин",
        query="разбери скрин", consumer="direct", wait_seconds=0.0,
        enqueue=False)
    assert before_l1.pending is True
    old_block = before_l1.evidence_block()
    assert 'status="pending"' in old_block

    # анализ завершился между L1 и Writer
    await db.finish_media_analysis(
        analysis_id, expected_revision=1, status="ready",
        ocr_blocks=[{"text": "Счёт за август: 12 340", "channel":
                     "untrusted_data"}],
        visual_description="платёжный документ")

    fresh = await mr.refresh_media_evidence(db, before_l1, consumer="direct")
    new_block = fresh.evidence_block()
    assert fresh.ready is True
    assert 'status="ready"' in new_block
    assert "Счёт за август: 12 340" in new_block
    assert new_block != old_block
    assert fresh.analysis_revision == 2       # CAS-бамп ревизии


@pytest.mark.asyncio
async def test_sc12_interactive_timeout_is_honest_pending_not_missing(db):
    """§8.12: Vision не успел до предела ожидания — нет фиктивного «не вижу»:
    pending зафиксирован и запрос отложен durable (ровно одна запись)."""
    await _add_message(db, 900, media_type="photo", caption="что тут?")
    asset_id = await _add_image(db, 900, serial=10)
    await _record(db, asset_id, status="running")

    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=900, caption="что тут?",
        query="что тут?", consumer="direct", wait_seconds=0.05,
        enqueue=False)
    assert readiness.pending is True
    assert readiness.analysis_status == mr.ANALYSIS_PENDING
    assert "недоступ" not in readiness.evidence_block().lower()

    deferred = await mr.defer_until_ready(
        db, readiness, consumer="direct", message_id=900,
        query="что тут?", notify=True)
    assert deferred.get("job_id")
    again = await mr.defer_until_ready(
        db, readiness, consumer="direct", message_id=900, query="что тут?")
    assert again["job_id"] == deferred["job_id"]      # не вторая запись

    store = await _store(db)
    intents = [j for j in await store.active()
               if j.get("kind") == mr.PENDING_INTENT_KIND]
    assert len(intents) == 1
    payload = json.loads(intents[0]["payload"])
    assert payload["readiness"]["analysis_status"] == mr.ANALYSIS_PENDING
    assert payload["linked"]["asset_ids"] == [asset_id]


@pytest.mark.asyncio
async def test_sc13_restart_recovers_from_durable_state(db):
    """§8.13: рестарт процесса — готовность читается из БД, локальный
    asyncio.Event не нужен (новый процесс видит готовый результат)."""
    await _add_message(db, 1000, media_type="photo")
    asset_id = await _add_image(db, 1000, serial=11)
    await _ready_analysis(db, asset_id, text="строка из старого процесса")

    asset = await db.get_media_assets_for_message(CHAT, 1000)
    # новый экземпляр сервиса/процесса: никаких предварительных событий
    mca_vision._READY_WAITERS.clear()
    waited = await mca_vision.await_asset_ready(
        db, asset[0], chat_id=CHAT, wait_seconds=0.0)
    assert waited["status"] == "ready"
    assert waited["cache_hit"] is True
    assert any("строка из старого процесса" in str(b.get("text"))
               for b in mca_vision.analysis_from_row(
                   waited["analysis"]).ocr_blocks)


@pytest.mark.asyncio
async def test_sc14_truncated_json_finish_reason_length(db):
    """§8.14: обрезанный JSON + finish_reason=length — причина определена
    (output_truncated) и применяется bounded-восстановление (бюджет вывода
    увеличивается), а не бесконечный повтор того же запроса."""
    image = mca_vision.validate_image_bytes(_image_bytes())
    truncated = _analysis_json("строка")[:20]
    transport = Transport(script=[
        (200, _body(truncated, finish_reason="length", output_tokens=4096)),
        (200, (_body(_analysis_json("полный текст скриншота"),
                     output_tokens=200))),
    ])
    analysis = await mca_vision.analyze_image_bytes(image, chat_id=CHAT,
                                                    transport=transport)
    assert analysis.status == "ready"
    assert analysis.diagnostics["strategy_changes"] == ["output_limit_raised"]
    assert transport.calls[1]["payload"]["max_tokens"] > \
        transport.calls[0]["payload"]["max_tokens"]
    assert len(transport.calls) == 2      # ровно один recovery-повтор


@pytest.mark.asyncio
async def test_sc14b_terminal_truncation_after_bounded_recovery(db):
    """§8.14 (терминальная ветка): если восстановление не помогло — честный
    `output_truncated`, а не «пусто» и не бесконечные повторы."""
    image = mca_vision.validate_image_bytes(_image_bytes())
    cut = _analysis_json("строка")
    transport = Transport(default=(200, _body(cut[:25], finish_reason="length",
                                              output_tokens=4096)))
    analysis = await mca_vision.analyze_image_bytes(image, chat_id=CHAT,
                                                    transport=transport)
    assert analysis.status == "failed"
    assert analysis.error_reason == "output_truncated"
    assert len(transport.calls) == 2      # bounded (2 попытки), не больше
    assert analysis.diagnostics["schema_valid"] is False
    assert analysis.diagnostics["analysis_ready"] is False


@pytest.mark.asyncio
async def test_sc15_http_200_empty_choices_is_not_ok(db):
    """§8.15: HTTP 200 с пустыми choices / невалидным телом — НЕ «Vision OK»:
    провайдер подтверждён транспортом, но схема/готовность — нет."""
    image = mca_vision.validate_image_bytes(_image_bytes())
    transport = Transport(default=(200, {"choices": []}))
    analysis = await mca_vision.analyze_image_bytes(image, chat_id=CHAT,
                                                    transport=transport)
    diagnostics = analysis.diagnostics
    assert diagnostics["transport_success"] is False
    assert diagnostics["schema_valid"] is False
    assert analysis.status == "failed"
    assert analysis.error_reason == "empty_content"

    report = await mr.run_admin_check(db, chat_id=CHAT, transport=transport)
    assert report["ok"] is False
    assert report["provider"] == "failed"
    assert report["reason_code"]


@pytest.mark.asyncio
async def test_sc16_thinking_model_long_ocr_no_fixed_truncation(db):
    """§8.16: thinking-модель + большой OCR — reasoning-токены не считаются
    «успехом», бюджет вывода увеличивается, фиксированного символьного
    обрезания нет (весь длинный текст доходит)."""
    image = mca_vision.validate_image_bytes(_image_bytes())
    long_text = "OCR-строка " * 900        # ~9000 символов
    transport = Transport(script=[
        # весь бюджет ушёл в размышление: content пуст, finish_reason=length
        (200, _body("", finish_reason="length", reasoning_tokens=3000,
                    output_tokens=3000)),
        (200, _body(_analysis_json(long_text), output_tokens=6000)),
    ])
    with patched_settings(VISION_MODEL="test-vlm-reasoning"):
        analysis = await mca_vision.analyze_image_bytes(image, chat_id=CHAT,
                                                        transport=transport)
    assert analysis.status == "ready"
    assert analysis.diagnostics["reasoning_tokens"] == 3000
    assert analysis.diagnostics["strategy_changes"] == [
        "reasoning_budget_raised"]
    text = analysis.ocr_blocks[0]["text"]
    assert len(text) > 5000                # не обрезано фиксированным лимитом
    # reasoning-параметр не отправляется вслепую (маршрут его не подтверждал)
    assert "reasoning_effort" not in transport.calls[0]["payload"]


@pytest.mark.asyncio
async def test_sc16b_rejected_reasoning_param_is_learned(db):
    """§8.16 (маршрут): если провайдер ОТКЛОНИЛ reasoning-параметр, он больше
    не отправляется, а запрос повторяется без него (установленный класс)."""
    image = mca_vision.validate_image_bytes(_image_bytes())
    route = mca_vision.resolve_route(CHAT)
    mca_vision.mark_route_param_rejected(route, "response_format")
    transport = Transport(default=(200, _body(_analysis_json("текст"))))
    analysis = await mca_vision.analyze_image_bytes(image, chat_id=CHAT,
                                                    transport=transport)
    assert analysis.status == "ready"
    assert "response_format" not in transport.calls[0]["payload"]


@pytest.mark.asyncio
async def test_sc17_factcheck_pending_forbids_no_claim(db):
    """§8.17: фактчек видит pending OCR — нет права на `no_claim`; после ready
    тезис извлекается из изображения."""
    await _add_message(db, 1100, media_type="photo", caption="фактчек",
                       author="Аня")
    asset_id = await _add_image(db, 1100, serial=12)
    analysis_id = await _record(db, asset_id, status="running")

    # Ожидание не задаём (0 c) — проверяем именно контракт состояния, а не
    # длительность: pending НЕ даёт права на no_claim.
    publication = await fcs.resolve_claim_publication(
        db, CHAT, 1100, base_text="фактчек", media_wait_seconds=0.0)
    assert publication.admission_blocked_by_pending_media() is True

    await db.finish_media_analysis(
        analysis_id, expected_revision=1, status="ready",
        ocr_blocks=[{"text": "Заявление: пенсия вырастет на 15%",
                     "channel": "untrusted_data"}],
        visual_description="фото документа")
    publication2 = await fcs.resolve_claim_publication(
        db, CHAT, 1100, base_text="фактчек", media_wait_seconds=0.0)
    assert publication2.media_dependency() == "ready"
    assert "пенсия вырастет на 15%" in publication2.text


@pytest.mark.asyncio
async def test_sc20_vision_failure_with_text_is_honestly_split(db):
    """§8.20: отказ Vision + независимый текст — ответ честно отделяет
    доступный текст от непроверенного визуального содержимого."""
    await _add_message(db, 1200, text="в этом посту точно есть ложь",
                       media_type="photo", caption="в этом посту точно есть ложь")
    asset_id = await _add_image(db, 1200, serial=13)
    await _record(db, asset_id, status="failed", error_reason="provider_timeout")

    publication = await fcs.resolve_claim_publication(
        db, CHAT, 1200, base_text="в этом посту точно есть ложь",
        media_wait_seconds=0.0)
    assert publication.media_dependency() == "unchecked"
    notice = publication.notice()
    assert "НЕ проверено" in notice
    assert "не ответил вовремя" in notice     # человеческая причина
    assert "в этом посту точно есть ложь" in publication.text
    assert publication.media.image_unchecked is True
    # картинка не выдумана: OCR-материала нет
    assert "OCR" not in publication.text


# ════════════════════════════════════════════════════════════════════════════
# WATCHDOG (§watchdog; сценарии 21–25)
# ════════════════════════════════════════════════════════════════════════════

async def _queued_job(db, chat_id: int, asset_id: str, *, attempt: int = 0,
                      status: str = "queued", heartbeat_age: int | None = None,
                      deadline_in: int | None = None, updated_age: int = 0):
    store = await _store(db)
    job_id = await store.enqueue(
        owner="vision.media", kind=mca_vision.VISION_JOB_KIND,
        coalesce_key=f"vision:asset:{asset_id}",
        payload=mca_vision._vision_payload(
            asset_id=asset_id, chat_id=chat_id, tg_message_id=700,
            file_id="fid", media_group_id="", priority="auto",
            user_id=USER_ID),
        max_attempts=4,
        deadline_at=(int(time.time()) + deadline_in)
        if deadline_in is not None else None)
    if status != "queued" or attempt:
        now = int(time.time())
        hb = None if heartbeat_age is None else now - int(heartbeat_age)
        await db.db.execute(
            "UPDATE task_jobs SET status=?, attempt=?, heartbeat_at=?, "
            "updated_at=? WHERE job_id=?",
            (status, int(attempt), hb, now - int(updated_age), str(job_id)))
        await db.db.commit()
    return job_id


@pytest.mark.asyncio
async def test_sc21_stuck_external_call_times_out_and_terminates(db):
    """§8.21: воркер завис на внешнем API — watchdog различает «живой долгий»
    и настоящий сбой: сначала bounded-recovery, после исчерпания попыток —
    терминал с конкретной причиной; потребитель не висит."""
    await _add_message(db, 1300, media_type="photo")
    asset_id = await _add_image(db, 1300, serial=14)
    await _record(db, asset_id, status="running")
    store = await _store(db)
    job_id = await _queued_job(db, CHAT, asset_id, attempt=0,
                               status="running", heartbeat_age=10_000)

    # долгий, но ЖИВОЙ вызов (свежий heartbeat) — не зависание
    live_id = await _queued_job(db, CHAT, asset_id, status="running",
                                heartbeat_age=1)
    summary = await mr.watchdog_sweep(db, store=store)
    assert summary["alive"] >= 1
    assert (await store.get(live_id))["status"] == "running"

    # реальный срыв: попытки восстановления уже исчерпаны → терминал
    await db.db.execute("UPDATE task_jobs SET attempt=? WHERE job_id=?",
                        (mr.max_recoveries(), str(job_id)))
    await db.db.commit()
    doubled = False
    for _ in range(4):
        summary = await mr.watchdog_sweep(db, store=store)
        row = await store.get(job_id)
        if row is not None and 0 < int(row.get("fencing_token") or 0):
            doubled = True
        if row is None or row["status"] in ("failed", "completed",
                                            "cancelled"):
            break
        await db.db.execute(
            "UPDATE task_jobs SET status='running', heartbeat_at=?, "
            "attempt=? WHERE job_id=?",
            (0, mr.max_recoveries(), str(job_id)))
        await db.db.commit()
    row = await store.get(job_id)
    assert doubled is True
    assert row["status"] == "failed"
    assert row["reason_code"] in ("worker_lost", "deadline_exceeded")

    # потребитель получает честный терминальный исход, а не вечный pending
    waited = await mca_vision.await_asset_ready(
        db, (await db.get_media_assets_for_message(CHAT, 1300))[0],
        chat_id=CHAT, wait_seconds=0.05)
    assert waited["status"] in ("failed", "unavailable")
    assert waited["reason_code"]


@pytest.mark.asyncio
async def test_sc22_orphaned_running_job_requeued_safely(db):
    """§8.22: воркер упал, оставив `running` — watchdog находит осиротевшую
    задачу и безопасно возвращает её в очередь (fencing_token сдвинут)."""
    await _add_message(db, 1400, media_type="photo")
    asset_id = await _add_image(db, 1400, serial=15)
    await _record(db, asset_id, status="running")
    store = await _store(db)
    job_id = await _queued_job(db, CHAT, asset_id, attempt=1,
                               status="running", heartbeat_age=9000)
    before = await store.get(job_id)

    summary = await mr.watchdog_sweep(db, store=store)
    after = await store.get(job_id)
    assert summary["requeued"] >= 1
    assert after["status"] == "queued"
    assert after["reason_code"] == "worker_lost"
    assert after["fencing_token"] > before["fencing_token"]
    # старый владелец больше не может завершить задачу
    stale_finish = await store.finish(
        job_id, status="completed", result_ref="old",
        fencing_token=before["fencing_token"])
    assert stale_finish is False


@pytest.mark.asyncio
async def test_sc23_late_old_worker_cannot_overwrite_newer_result(db):
    """§8.23: старый воркер завершил работу после рестарта — новый результат
    не перезаписывается, дублирующей отправки нет."""
    await _add_message(db, 1500, media_type="photo")
    asset_id = await _add_image(db, 1500, serial=16)
    store = await _store(db)
    job_id = await _queued_job(db, CHAT, asset_id, attempt=1,
                               status="running", heartbeat_age=9000)
    before = await store.get(job_id)

    # новый владелец уже сохранил актуальную ревизию
    analysis_id = await _record(db, asset_id, status="ready",
                                ocr=[{"text": "новая ревизия: 4321",
                                      "channel": "untrusted_data"}])
    analysis_row = await db.get_media_analysis(analysis_id)

    summary = await mr.watchdog_sweep(db, store=store)
    assert summary["already_ready"] >= 1
    after = await store.get(job_id)
    assert after["status"] == "completed"

    # устаревшая запись старого владельца отклоняется по fencing
    stale = await store.finish(job_id, status="completed", result_ref="old",
                              fencing_token=before["fencing_token"])
    assert stale is False
    row = await db.get_media_analysis(analysis_id)
    assert row["status"] == "ready"
    assert row["revision"] == analysis_row["revision"]   # не перезаписано
    scope = mca_vision.access_scope_for(CHAT)
    ready = await mca_vision.resolve_ready_for_asset(
        db, (await db.get_media_assets_for_message(CHAT, 1500))[0], scope)
    assert any("новая ревизия: 4321" in str(b.get("text"))
               for b in mca_vision.analysis_from_row(ready).ocr_blocks)


@pytest.mark.asyncio
async def test_sc24_restart_during_wait_resumes_once(db):
    """§8.24: рестарт приложения во время ожидания — связанный запрос
    возобновляется из durable-состояния и даёт РОВНО один логический
    результат (второй проход не отправляет повторно)."""
    await _add_message(db, 1600, media_type="photo", caption="проверь картинку")
    asset_id = await _add_image(db, 1600, serial=17)
    analysis_id = await _record(db, asset_id, status="running")

    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=1600, caption="проверь картинку",
        query="проверь картинку", consumer="factcheck", wait_seconds=0.0,
        enqueue=False)
    await mr.defer_until_ready(db, readiness, consumer="factcheck",
                               message_id=1600, query="проверь картинку")

    # «рестарт»: новый процесс видит только БД
    mca_vision._READY_WAITERS.clear()
    sends: list = []

    async def _resume(intent, states):
        sends.append(intent["trigger_message_id"])

    assert (await mr.resume_deferred_requests(db, chat_id=CHAT,
                                              resume=_resume))["waiting"] == 1
    assert sends == []

    await db.finish_media_analysis(
        analysis_id, expected_revision=1, status="ready",
        ocr_blocks=[{"text": "Итоговая сумма 88 000", "channel":
                     "untrusted_data"}], visual_description="квитанция")
    first = await mr.resume_deferred_requests(db, chat_id=CHAT,
                                              resume=_resume)
    second = await mr.resume_deferred_requests(db, chat_id=CHAT,
                                               resume=_resume)
    assert first["resumed"] == 1
    assert second["resumed"] == 0
    assert sends == [1600]                 # ровно одно возобновление


@pytest.mark.asyncio
async def test_sc25_attempts_exhausted_terminal_no_hallucination(db):
    """§8.25: попытки исчерпаны — терминальный статус с причиной, запрос
    завершается без выдуманного разбора и без бесконечного ожидания."""
    await _add_message(db, 1700, media_type="photo", caption="фактчек")
    asset_id = await _add_image(db, 1700, serial=18)
    await _record(db, asset_id, status="running")
    store = await _store(db)
    job_id = await _queued_job(db, CHAT, asset_id,
                               attempt=mr.max_recoveries(),
                               status="running", heartbeat_age=9000)

    summary = await mr.watchdog_sweep(db, store=store)
    assert summary["terminal"] >= 1
    row = await store.get(job_id)
    assert row["status"] == "failed"
    assert row["reason_code"] == "worker_lost"

    publication = await fcs.resolve_claim_publication(
        db, CHAT, 1700, base_text="фактчек", media_wait_seconds=0.0)
    assert publication.media_dependency() == "unchecked"
    assert "НЕ проверено" in publication.notice()
    assert publication.media.image_unchecked is True


@pytest.mark.asyncio
async def test_watchdog_non_recoverable_reason_is_terminal(db):
    """Watchdog: невосстановимая причина (неподдерживаемый ввод) не
    повторяется — сразу терминал с причиной."""
    await _add_message(db, 1800, media_type="photo")
    asset_id = await _add_image(db, 1800, serial=19)
    await _record(db, asset_id, status="running")
    store = await _store(db)
    job_id = await _queued_job(db, CHAT, asset_id, attempt=0,
                               status="running", heartbeat_age=9000)
    action = await mr.recover_job(
        db, store, await store.get(job_id), reason="vision_unsupported")
    assert action["action"] == "terminal"
    row = await store.get(job_id)
    assert row["status"] == "failed"
    assert row["reason_code"] == "vision_unsupported"


@pytest.mark.asyncio
async def test_watchdog_diagnostics_expose_stage_and_lease(db):
    """Диагностика операций: стадия, время в стадии, попытка, lease,
    ожидающие потребители — без приватных текстов и без второго журнала."""
    await _add_message(db, 1900, media_type="photo")
    asset_id = await _add_image(db, 1900, serial=20)
    await _record(db, asset_id, status="running")
    await _queued_job(db, CHAT, asset_id, attempt=2, status="running",
                      heartbeat_age=30)
    rows = await mr.watchdog_diagnostics(db)
    assert rows
    row = next(r for r in rows if r["asset_id"] == asset_id)
    assert row["stage"] == "running"
    assert row["attempt"] == 2
    assert row["lease_expires_in"] is not None
    assert set(row) >= {"job_id", "asset_id", "consumer", "stage",
                        "stage_seconds", "lease_expires_in"}
