"""ASAP-VISION-SYNC-01 волна 2 — потребители медиа: соседний текст, неодно-
значность, альбом, фоновые потребители (сводки/факты/инициатива/поиск),
изоляция чатов и v2-маршрут фактчека (offline, без живых отправок и сети).

TEST-LIFECYCLE: CONTRACT/REGRESSION owner=ASAP-VISION-SYNC-01
(plans/current_task.md §3/§4/§8 + патч-ноты отчёта w8-vision-sync-core.md §6).

Покрытие (сценарии §8, волна 2): 7, 8, 9, 18, 19 + завершение патч-нот ядра:
`_run_inner` v2 (pending → no_claim запрещён; терминальный отказ → честное
«содержимое картинки не проверено»), `_empty_content_phrase` хендлера,
каталогизация настроек распознавания (§5: владелец видит и меняет).

Границы: SQLite в tmp, Vision-транспорт не вызывается (анализ кладётся в БД
готовым), LLM — контрактные двойники. Telegram/сеть — нет.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from handlers import factcheck as hfc
from services import chat_context
from services import hot_config as hot
from services import mca_vision
from services import media_readiness as mr
from services import param_catalog as pc
from services.database import DatabaseService
from services.initiative_observer import InitiativeObserverRunner
from services.search_service import SearchService
from services.smartmodule_phrases import (
    FACTCHECK_IMAGE_NO_CLAIM_PHRASES,
    FACTCHECK_IMAGE_PENDING_AUTO_PHRASES,
    FACTCHECK_IMAGE_PENDING_PHRASES,
    FACTCHECK_MEDIA_ERROR_PHRASES,
    FACTCHECK_NO_CLAIM_PHRASES,
)
from services.summary_memory import MemoryManager
from tests.test_evol_vision_sync_core import (   # переиспользуемая обвязка ядра
    _add_image as _core_add_image,
    _add_message as _core_add_message,
    _ready_analysis as _core_ready_analysis,
    _record as _core_record,
    patched_settings,
)

pytestmark = [pytest.mark.asap3]

CHAT = -1009100001
CHAT2 = -1009100002
USER_ID = 5151
NOW = int(time.time())

VISION_BASE = "http://vlm.local/v1"


# ── обвязка ────────────────────────────────────────────────────────────────

class _Cfg:
    """Горячая конфигурация для теста (hot.get читает только .get)."""

    def __init__(self, values: dict):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture(autouse=True)
def _vision_env():
    mca_vision.reset_capability_cache()
    mca_vision.reset_route_param_memo()
    hot.set_config_cache(None)
    with patched_settings(VISION_ENABLED=True,
                          VISION_API_BASE_URL=VISION_BASE,
                          VISION_MODEL="test-vlm",
                          VISION_API_KEY="test-key",
                          VISION_API_TYPE="openai_compatible",
                          VISION_MAX_OUTPUT_TOKENS=0):
        yield
    mca_vision.reset_capability_cache()
    mca_vision.reset_route_param_memo()
    hot.set_config_cache(None)


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "vision-sync-w2.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


def _row(tg_id: int, text: str = "", *, author: str = "Сергей",
         media_type: str = "text", ts: int | None = None,
         is_forward=False, forward_source=None, reply_to=None):
    return {"id": int(tg_id), "chat_id": CHAT, "user_id": USER_ID,
            "text": text, "author_name": author, "media_type": media_type,
            "timestamp": int(ts or NOW), "tg_message_id": int(tg_id),
            "is_forward": is_forward, "forward_source": forward_source,
            "reply_to_id": reply_to}


# Обёртки: обвязка ядра по умолчанию пишет в свой CHAT — здесь всегда наш чат.

async def _msg(db, tg_id: int, **kw):
    return await _core_add_message(db, tg_id, chat_id=kw.pop("chat_id", CHAT),
                                   **kw)


async def _img(db, tg_id: int, *, serial: int, media_group=None,
               chat_id=None):
    return await _core_add_image(db, tg_id, chat_id=int(chat_id or CHAT),
                                 serial=serial, media_group=media_group)


async def _rec(db, asset_id, *, chat_id=None, **kw):
    return await _core_record(db, asset_id, chat_id=int(chat_id or CHAT), **kw)


async def _ready(db, asset_id, *, text, chat_id=None,
                 description="скриншот"):
    return await _core_ready_analysis(db, asset_id, text=text,
                                      chat_id=int(chat_id or CHAT),
                                      description=description)


async def _vision_job(db, tg_id: int, asset_id: str, *, serial: int) -> None:
    """Настоящая задача распознавания — production-состояние «pending».

    Отложить запрос имеет смысл только когда работа реально идёт (§4.6): актив
    без анализа И без задачи — не ожидание, поэтому тесту нужен durable-job."""
    await mca_vision.enqueue_asset_analysis(
        db, {"asset_id": asset_id, "tg_message_id": int(tg_id),
             "file_id": f"fid_{serial}", "media_group_id": ""},
        chat_id=CHAT)


class _CaptureLLM:
    def __init__(self, answer: str = "конспект окна"):
        self.answer = answer
        self.calls: list = []

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)
        return self.answer

    async def generate_background(self, messages, **kwargs):
        return await self.generate(messages)


# ════════════════════════════════════════════════════════════════════════════
# §8.7 — обычный текстовый вопрос рядом с чужим фото НЕ ждёт Vision
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc7_plain_text_near_foreign_photo_does_not_wait(db):
    """Фото висит в очереди распознавания, но вопрос про другое — быстрый путь
    без ожидания (прямой путь Direct: allow_adjacent только при явной ссылке)."""
    await _msg(db, 700, media_type="photo", author="Аня")
    asset_id = await _img(db, 700, serial=71)
    await _rec(db, asset_id, status="running")        # анализ идёт
    await _msg(db, 701, text="как вообще дела?", author="Петя")

    assert mr.is_media_dependent(query="как вообще дела?", own_media=False,
                                 reply_media=False) is False

    started = time.monotonic()
    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=701, query="как вообще дела?",
        consumer="direct", wait_seconds=5.0, allow_adjacent=False)
    elapsed = time.monotonic() - started

    assert readiness is None, "обычный текст не должен связываться с фото"
    assert elapsed < 1.0, f"барьер ждал Vision на обычный текст ({elapsed:.2f}s)"


# ════════════════════════════════════════════════════════════════════════════
# §8.8 — два соседних фото разных участников: НЕ случайное, а неоднозначность
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc8_two_neighbour_photos_return_ambiguity(db):
    """Слабая связь с двумя равноценными кандидатами → `ambiguous` с обоими
    адресами и БЕЗ выбранного актива (никакой случайной картинки)."""
    await _msg(db, 800, media_type="photo", author="Аня")
    a1 = await _img(db, 800, serial=81)
    await _ready(db, a1, text="Аня: счёт за март")
    await _msg(db, 801, media_type="photo", author="Петя")
    a2 = await _img(db, 801, serial=82)
    await _ready(db, a2, text="Петя: чек из магазина")
    await _msg(db, 802, text="бот, фактчек", author="Оля")

    resolved = await mr.resolve_target_media(
        db, chat_id=CHAT, message_id=802, allow_adjacent=True)
    assert resolved["association_status"] == mr.ASSOC_AMBIGUOUS, resolved
    assert resolved["assets"] == []                       # ничего не выбрано
    assert resolved["source_message_ids"] == (800, 801)   # оба кандидата видны
    assert resolved["reason_code"] == "ambiguous_target"

    # Потребитель получает честную неоднозначность, а не чужой OCR.
    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=802, query="бот, фактчек",
        consumer="factcheck", wait_seconds=0.0, allow_adjacent=True)
    assert readiness is not None
    assert readiness.association_status == mr.ASSOC_AMBIGUOUS
    assert readiness.asset_id == ""
    assert readiness.ocr_blocks == ()
    block = readiness.evidence_block()
    assert "счёт за март" not in block
    assert "чек из магазина" not in block


# ════════════════════════════════════════════════════════════════════════════
# §8.9 — альбом: учитываются ВСЕ изображения media group
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc9_album_collects_all_media_group_images(db):
    """Альбом из трёх фото: свидетельство содержит OCR всех трёх (а не одного
    случайного кадра), источник — элементы media group."""
    group = "album-w2-1"
    for idx, tg in enumerate((900, 901, 902), start=1):
        await _msg(db, tg, media_type="photo", media_group=group, author="Аня")
        asset = await _img(db, tg, serial=90 + idx, media_group=group)
        await _ready(db, asset, text=f"страница {idx} отчёта")

    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=900, caption="разбери альбом",
        query="разбери альбом", media_group_id=group, consumer="direct",
        wait_seconds=0.0, enqueue=False)

    assert readiness is not None and readiness.ready
    assert readiness.association_kind == mr.ASSOC_ALBUM
    assert set(readiness.source_message_ids) == {900, 901, 902}
    block = readiness.evidence_block()
    for idx in (1, 2, 3):
        assert f"страница {idx} отчёта" in block

    # Неполный альбом: ещё один кадр распознаётся — альбом честно остаётся
    # pending (не отвечаем по одному кадру), а источники включают все элементы.
    await _msg(db, 903, media_type="photo", media_group=group,
               author="Аня")
    await _rec(db, await _img(db, 903, serial=94, media_group=group),
               status="running")
    partial = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=900, caption="разбери альбом",
        query="разбери альбом", media_group_id=group, consumer="direct",
        wait_seconds=0.0, enqueue=False)
    assert partial is not None and partial.pending
    assert set(partial.source_message_ids) == {900, 901, 902, 903}
    partial_block = partial.evidence_block()
    assert "НЕИЗВЕСТНО" in partial_block        # честно: содержимое неизвестно
    assert "ничего нет" in partial_block        # запрет на «картинки/текста нет»


# ════════════════════════════════════════════════════════════════════════════
# §8.18 — фоновые потребители: pending не становится содержимым/знанием
# ════════════════════════════════════════════════════════════════════════════

async def _window_rows(db, photo_tg: int) -> list:
    """Окно больше хвоста конспекта (tail=30) с одним фото и текстом вокруг."""
    rows = []
    for i in range(31):
        tg = 1000 + i
        author = "Оля" if i % 2 else "Петя"
        await _msg(db, tg, text=f"болтовня номер {i}", author=author)
        rows.append(_row(tg, f"болтовня номер {i}", author=author))
    await _msg(db, photo_tg, media_type="photo", author="Аня")
    rows.insert(15, _row(photo_tg, "", author="Аня", media_type="photo"))
    return rows


@pytest.mark.asyncio
async def test_sc18_summary_defers_on_pending_and_uses_ready_ocr(db):
    """Сводка: (а) при pending конспект окна НЕ пишется (знание не создаётся,
    сообщений в чат нет — только терминальный статус); (б) после готовности
    анализ входит в материал со ссылкой на источник (msg/asset/ревизия)."""
    photo_tg = 1100
    rows = await _window_rows(db, photo_tg)
    asset_id = await _img(db, photo_tg, serial=110)
    analysis_id = await _rec(db, asset_id, status="running")

    llm = _CaptureLLM()
    memory = MemoryManager(db, llm)

    status = await memory._build_running_summary_impl(CHAT, rows)
    assert status == "skipped_media_pending"
    assert llm.calls == []                      # LLM не зван: знание не строится
    assert await db.get_running_summary(CHAT, time.time()) is None

    # Анализ завершился — тот же путь строит конспект с OCR и ссылкой.
    await db.finish_media_analysis(
        analysis_id, expected_revision=1, status="ready",
        ocr_blocks=[{"text": "Итого по счёту: 12 340",
                     "channel": "untrusted_data"}],
        visual_description="фото платёжки")
    status2 = await memory._build_running_summary_impl(CHAT, rows)
    assert status2 == "success"
    payload = llm.calls[0][-1]["content"]
    assert "Итого по счёту: 12 340" in payload
    assert f"msg:{photo_tg}" in payload         # правильный источник
    assert "asset:" in payload                  # ссылка на актив
    assert "анализ v" in payload                # ревизия анализа
    stored = await db.get_running_summary(CHAT, time.time())
    assert stored is not None and stored["summary"]


@pytest.mark.asyncio
async def test_sc18_graph_facts_only_from_finished_analysis(db):
    """Факты/граф: извлечение видит готовый OCR со ссылкой; неготовое фото не
    отдаёт выдуманного содержимого (pending не доказательство)."""
    photo_pending, photo_ready = 1200, 1201
    await _msg(db, photo_pending, media_type="photo", author="Аня")
    asset_pending = await _img(db, photo_pending, serial=121)
    await _rec(db, asset_pending, status="running")
    await _msg(db, photo_ready, media_type="photo", author="Петя")
    asset_ready = await _img(db, photo_ready, serial=122)
    await _ready(db, asset_ready, text="Договор подписан 1 июня")

    batch = [_row(photo_pending, "", author="Аня", media_type="photo"),
             _row(photo_ready, "", author="Петя", media_type="photo"),
             _row(1300, "обсуждаем условия", author="Оля")]
    llm = _CaptureLLM("[]")
    memory = MemoryManager(db, llm)
    written: list = []

    async def _capture(chat_id, triplets):
        written.append(triplets)

    memory._write_graph_triplets = _capture           # type: ignore[assignment]
    import services.summary_memory as sm
    old_retry = sm._graph_retry_enabled
    sm._graph_retry_enabled = lambda: False
    try:
        await memory._extract_and_save_graph(CHAT, batch)
    finally:
        sm._graph_retry_enabled = old_retry

    payload = llm.calls[0][-1]["content"]
    assert "Договор подписан 1 июня" in payload
    assert f"msg:{photo_ready}" in payload            # ссылка на источник
    assert payload.count("изображение") == 1          # только готовый кадр


@pytest.mark.asyncio
async def test_sc18_initiative_and_search_do_not_use_unready_media(db):
    """Инициатива отсекает медиа-строки (не создаёт утверждений о картинке);
    поиск получает отрендеренный статус: pending — честное «не распознано»,
    ready — OCR. Выдуманного содержимого нет ни там, ни там."""
    # Инициатива: фото-строка не элегибельна, текст — элегибелен.
    assert InitiativeObserverRunner._scan_eligible(
        {"media_type": "photo", "text": "", "is_forward": 0, "user_id": 1,
         "chat_id": CHAT}) == "non_text"
    assert InitiativeObserverRunner._scan_eligible(
        {"media_type": "text", "text": "нормальный текст", "is_forward": 0,
         "user_id": 1, "chat_id": CHAT}) is None

    # Поиск: pending → в контексте честная строка ожидания, без содержимого.
    # (Здесь — медиа без подписи: рендерер контекста подставляет медиа-блок
    # именно для строк без текста; случай «фото с подписью» для поиска
    # зафиксирован в отчёте как известный зазор вне зоны этой волны.)
    await _msg(db, 1400, media_type="photo", author="Аня")
    asset_pending = await _img(db, 1400, serial=141)
    await _rec(db, asset_pending, status="running")
    rows_pending = [_row(1400, "", author="Аня", media_type="photo")]
    ctx_pending = await chat_context.build_chat_context(db, rows_pending,
                                                        chat_id=CHAT)
    assert "не распознано" in ctx_pending.lower()

    captured: list = []

    class _LLM:
        async def generate(self, messages, **kwargs):
            captured.append(messages)
            return "ответ по поиску"

    class _Agg:
        async def search(self, query, max_symbols):
            return "результат поиска"

    import services.search_service as ss
    old_owner = ss.speech_owner_block
    ss.speech_owner_block = AsyncMock(return_value="")
    try:
        service = SearchService(_Agg(), _LLM(), memory=None)
        await service.research("что на скрине?", chat_id=None,
                              chat_context=ctx_pending)
    finally:
        ss.speech_owner_block = old_owner
    # Финальный payload (не только реранк) содержит честный статус картинки.
    assert any("не распознано" in m[-1]["content"].lower() for m in captured)

    # ready → тот же путь даёт OCR (актуальный анализ доходит до вопроса).
    await _msg(db, 1401, media_type="photo", author="Петя")
    asset_ready = await _img(db, 1401, serial=142)
    await _ready(db, asset_ready, text="Скрин: перевод 5000")
    rows_ready = [_row(1401, "", author="Петя", media_type="photo")]
    ctx_ready = await chat_context.build_chat_context(db, rows_ready,
                                                      chat_id=CHAT)
    assert "Скрин: перевод 5000" in ctx_ready


# ════════════════════════════════════════════════════════════════════════════
# §8.19 — изоляция чатов: чужое изображение не становится источником
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sc19_foreign_chat_image_never_becomes_source(db):
    """Фото принадлежит ДРУГОМУ чату: в этом чате оно не находится ни как своё,
    ни как reply, ни как соседнее, и не попадает в знание окна."""
    await _msg(db, 1500, chat_id=CHAT2, media_type="photo")
    foreign_asset = await _img(db, 1500, chat_id=CHAT2, serial=151)
    await _ready(db, foreign_asset, chat_id=CHAT2,
                 text="Чужой чат: закрытый документ")

    await _msg(db, 1501, text="что тут написано?")
    resolved = await mr.resolve_target_media(
        db, chat_id=CHAT, message_id=1501, reply_to_message_id=1500,
        allow_adjacent=True)
    assert resolved["association_status"] == mr.ASSOC_MISSING
    assert resolved["assets"] == []

    readiness = await mr.prepare_media_evidence(
        db, chat_id=CHAT, message_id=1501, reply_to_message_id=1500,
        query="что тут написано?", consumer="direct", wait_seconds=0.0,
        allow_adjacent=True)
    if readiness is not None:
        assert readiness.asset_id == ""
        assert "закрытый документ" not in readiness.evidence_block()

    # Фоновое знание окна тоже не видит чужой актив (изоляция в запросах).
    from services.summary_memory import visual_window_state
    state = await visual_window_state(
        db, CHAT, [_row(1500, "", author="Аня", media_type="photo")],
        consumer="summary")
    assert state["ready"] == {} and state["pending"] == {}


# ════════════════════════════════════════════════════════════════════════════
# Патч-нота ядра §6.1 — v2-маршрут фактчека: pending НЕ даёт no_claim
# ════════════════════════════════════════════════════════════════════════════

class _FakeCache:
    def __init__(self):
        self.store: dict = {}

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.store.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.store[key] = payload


def _factcheck_req(target_id: int, target_text: str):
    from services.factcheck_orchestrator import FactcheckRequest
    return FactcheckRequest(chat_id=CHAT, trigger_tg_message_id=target_id + 1,
                            target_tg_message_id=target_id,
                            target_text=target_text, kind="reply")


@pytest.mark.asyncio
async def test_v2_pending_media_forbids_no_claim(db):
    """v2-маршрут: пока OCR не готов, ответ НЕ из пула «нечего проверять» и не
    вердикт — отложенный исход, лимит не расходуется."""
    from services import factcheck_orchestrator as orch

    hot.set_config_cache(_Cfg({"limits.vision_readiness_wait_seconds": 0.01}))
    await _msg(db, 1600, media_type="photo", caption="фактчек",
               author="Аня")
    asset_id = await _img(db, 1600, serial=161)
    await _rec(db, asset_id, status="running")
    await _vision_job(db, 1600, asset_id, serial=161)

    service = MagicMock()
    service.check_claim = AsyncMock(side_effect=AssertionError(
        "v2 не должен дойти до платной проверки при pending"))
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(side_effect=AssertionError("LLM offline"))
    bot = AsyncMock()

    outcome = await orch.run_factcheck(
        _factcheck_req(1600, "фактчек"), service=service, db=db, bot=bot,
        cache=_FakeCache())

    assert outcome == orch.OUTCOME_PENDING
    assert outcome in orch.REFUNDABLE_OUTCOMES
    sent = bot.send_message.await_args.args[1]
    # Review-fix2 (P1): намерение зарегистрировано → фраза честно говорит
    # «продолжу сам» вместо «повтори через минуту» (оба пула — pending).
    assert sent in (FACTCHECK_IMAGE_PENDING_PHRASES
                    + FACTCHECK_IMAGE_PENDING_AUTO_PHRASES)
    assert sent not in FACTCHECK_NO_CLAIM_PHRASES
    assert len(await _intent_payloads(db)) == 1
    assert service.check_claim.await_count == 0


@pytest.mark.asyncio
async def test_v2_terminal_vision_failure_is_honest_not_no_claim(db):
    """Терминальный отказ распознавания при пустом тексте: v2 говорит
    «содержимое картинки не проверено» (а не «нечего проверять») и не
    выдумывает вердикт."""
    from services import factcheck_orchestrator as orch

    hot.set_config_cache(_Cfg({"limits.vision_readiness_wait_seconds": 0.01}))
    await _msg(db, 1700, media_type="photo", caption="", author="Аня")
    asset_id = await _img(db, 1700, serial=171)
    await _rec(db, asset_id, status="failed",
                  error_reason="provider_timeout")

    service = MagicMock()
    service.check_claim = AsyncMock(side_effect=AssertionError(
        "при непроверенной картинке вердикта быть не должно"))
    bot = AsyncMock()

    outcome = await orch.run_factcheck(
        _factcheck_req(1700, ""), service=service, db=db, bot=bot,
        cache=_FakeCache())

    assert outcome == orch.OUTCOME_UNAVAILABLE
    sent = bot.send_message.await_args.args[1]
    first_line = sent.split("\n", 1)[0]
    assert first_line in FACTCHECK_MEDIA_ERROR_PHRASES
    assert first_line not in FACTCHECK_NO_CLAIM_PHRASES
    assert first_line not in FACTCHECK_IMAGE_NO_CLAIM_PHRASES
    assert "НЕ проверено" in sent          # честная оговорка о картинке
    assert service.check_claim.await_count == 0


def test_handler_empty_content_phrase_matches_media_state():
    """Патч-нота §6.2: `_empty_content_phrase` при непроверенной картинке больше
    не выдаёт «нечего проверять» (хендлер, DI-off ветка — чистая функция)."""
    from services.factcheck_service import ClaimMediaMaterial, ClaimPublication

    unchecked = ClaimPublication(
        text="", caption_text="", has_image=True,
        media=ClaimMediaMaterial(image_present=True, image_unchecked=True,
                                 unchecked_reason="provider_timeout",
                                 image_count=1))
    phrase = hfc._empty_content_phrase(unchecked, None)
    assert phrase in FACTCHECK_MEDIA_ERROR_PHRASES
    assert phrase not in FACTCHECK_IMAGE_NO_CLAIM_PHRASES
    assert phrase not in FACTCHECK_NO_CLAIM_PHRASES

    ready_no_text = ClaimPublication(
        text="", caption_text="", has_image=True,
        media=ClaimMediaMaterial(image_present=True, image_analyzed=True,
                                 image_count=1))
    assert hfc._empty_content_phrase(ready_no_text, None) \
        in FACTCHECK_IMAGE_NO_CLAIM_PHRASES

    pending = ClaimPublication(
        text="", caption_text="", has_image=True,
        media=ClaimMediaMaterial(image_present=True, image_not_analyzed=True,
                                 pending_count=1, image_count=1))
    assert hfc._empty_content_phrase(pending, None) \
        in FACTCHECK_IMAGE_PENDING_PHRASES


# ════════════════════════════════════════════════════════════════════════════
# §5 — админские настройки распознавания видны и меняемы (каталог)
# ════════════════════════════════════════════════════════════════════════════

def test_vision_settings_catalogized_and_effective():
    """Каталог: предел ответа модели + границы ожидания/жизни задачи видны в
    каталоге; значение предела реально влияет на вызов (не «мёртвая ручка»)."""
    keys = {
        "models.vision_max_output_tokens": "models_vision",
        "models.vision_reasoning": "models_vision",
        "models.vision_structured_output": "models_vision",
        "limits.vision_readiness_wait_seconds": "limits_vision",
        "limits.vision_association_window_seconds": "limits_vision",
        "limits.vision_pending_intent_ttl_seconds": "limits_vision",
        "limits.vision_job_lease_seconds": "limits_vision",
        "limits.vision_queue_wait_seconds": "limits_vision",
        "limits.vision_job_lifetime_seconds": "limits_vision",
        "limits.vision_job_max_recoveries": "limits_vision",
        "limits.vision_job_backoff_base_seconds": "limits_vision",
        "limits.vision_job_backoff_max_seconds": "limits_vision",
    }
    for key, group in keys.items():
        spec = pc.REGISTRY[key]
        assert spec.group == group, key
        assert not spec.hidden, key
        assert spec.description.strip(), key
        assert spec.type in ("int", "str"), key

    # Лимиты распознавания — та же вкладка, что и остальные лимиты Vision.
    assert pc.group_tab("limits_vision") == pc.TAB_MOD_VISION

    # Значение предела ответа читается кодом из горячей конфигурации.
    route = mca_vision.VisionRoute(
        source="dedicated", base_url=VISION_BASE, model="test-vlm",
        api_type="openai_compatible", api_key_present=True,
        config_revision="cfg1")
    assert mca_vision.resolve_output_token_limit(route) == \
        mca_vision.OUTPUT_TOKEN_DEFAULT          # заводской путь (0 → по классу)
    hot.set_config_cache(_Cfg({"models.vision_max_output_tokens": 8192}))
    assert mca_vision.resolve_output_token_limit(route) == 8192
    hot.set_config_cache(_Cfg({"models.vision_max_output_tokens": 2}))
    assert mca_vision.resolve_output_token_limit(route) == \
        mca_vision.OUTPUT_TOKEN_FLOOR            # нижняя граница-защита
    hot.set_config_cache(None)


# ════════════════════════════════════════════════════════════════════════════
# REVIEW-FIX2 (ASAP-VISION-SYNC-01): B1, B2, P1, P2
# ════════════════════════════════════════════════════════════════════════════

from tests.test_evol_vision_sync_core import (      # noqa: E402
    _photo_message,
    _text_message,
)


async def _intent_payloads(db) -> list:
    import json
    cur = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind=? AND status IN "
        "('queued','running') ORDER BY created_at", (mr.PENDING_INTENT_KIND,))
    rows = [dict(r) for r in await cur.fetchall() or []]
    return [json.loads(r["payload"] or "{}") for r in rows]


# ── B1: «содержимое картинки НЕ проверено» доходит до ответа ────────────────

@pytest.mark.asyncio
async def test_b1_v2_captioned_photo_terminal_failure_is_not_no_claim(db):
    """B1 (v2): фото с подписью-просьбой «проверь скрин», анализ упал
    (provider_timeout), вокруг 15 сообщений. Раньше гейт отвечал «нечего
    проверять» — без единого слова о том, что картинку не распознали."""
    from services import factcheck_orchestrator as orch

    hot.set_config_cache(_Cfg({"limits.vision_readiness_wait_seconds": 0.01}))
    await _msg(db, 1800, media_type="photo", caption="проверь скрин",
               author="Аня")
    asset_id = await _img(db, 1800, serial=181)
    await _rec(db, asset_id, status="failed", error_reason="provider_timeout")
    for i in range(14):
        await _msg(db, 1810 + i, text=f"болтовня номер {i}", author="Петя")

    service = MagicMock()
    service.check_claim = AsyncMock(side_effect=AssertionError(
        "по непроверенной картинке вердикт не выдумывается"))
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(side_effect=AssertionError("LLM offline"))
    bot = AsyncMock()

    outcome = await orch.run_factcheck(
        _factcheck_req(1800, "проверь скрин"), service=service, db=db,
        bot=bot, cache=_FakeCache())

    assert outcome == orch.OUTCOME_UNAVAILABLE
    assert outcome != orch.OUTCOME_NO_CLAIM
    sent = bot.send_message.await_args.args[1]
    first_line = sent.split("\n", 1)[0]
    assert first_line in FACTCHECK_MEDIA_ERROR_PHRASES
    assert first_line not in FACTCHECK_NO_CLAIM_PHRASES
    assert "НЕ проверено" in sent               # оговорка о содержимом картинки
    assert service.check_claim.await_count == 0


@pytest.mark.asyncio
async def test_b1_v1_gate_refusal_keeps_media_caveat(db, monkeypatch):
    """B1 (v1-маршрут): отказ гейта «нечего проверять» при непроверенной
    картинке заменяется причиной + оговоркой о содержимом изображения."""
    await _msg(db, 1900, media_type="photo", caption="проверь скрин",
               author="Аня")
    asset_id = await _img(db, 1900, serial=191)
    await _rec(db, asset_id, status="failed", error_reason="provider_timeout")
    for i in range(14):
        await _msg(db, 1910 + i, text=f"болтовня номер {i}", author="Петя")

    target = _photo_message(1900, serial=191, caption="проверь скрин")
    trigger = _text_message(1999, "фактчек").model_copy(
        update={"reply_to_message": target})

    service = MagicMock()
    service.check_claim = AsyncMock(side_effect=AssertionError(
        "вердикта по непроверенной картинке быть не должно"))
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(side_effect=AssertionError("LLM offline"))
    hfc.setup_factcheck(service, db)
    monkeypatch.setattr(hfc, "_pipeline_v2_enabled", lambda: False)
    monkeypatch.setattr(hfc, "_temporal_on", lambda: False)

    gate_decision = MagicMock()
    gate_decision.decision = "no_claim_after_context"

    async def _gate(chat_id, before, after, **kwargs):
        return "", gate_decision

    monkeypatch.setattr(hfc, "_fetch_context_with_gate", _gate)

    bot = AsyncMock()
    # Публикация собирается единым резолвером (services.factcheck_service);
    # здесь она подаётся напрямую, чтобы тест проверял ИМЕННО формулировку
    # раннего отказа при непроверенной картинке, а не окружение рендера
    # (состояние `media_unchecked` из упавшего анализа доказано в v2-тесте и
    # в core-тестах §8.25).
    from services.factcheck_service import ClaimMediaMaterial, ClaimPublication

    unverified = ClaimPublication(
        text="проверь скрин", caption_text="проверь скрин", has_image=True,
        media=ClaimMediaMaterial(image_present=True, image_unchecked=True,
                                 unchecked_reason="provider_timeout",
                                 image_count=1))

    async def _resolve(message, tgt):
        return unverified

    monkeypatch.setattr(hfc, "_resolve_publication", _resolve)
    await hfc.factcheck_handler(trigger, bot=bot)

    sent = bot.send_message.await_args.args[1]
    first_line = sent.split("\n", 1)[0]
    assert first_line in FACTCHECK_MEDIA_ERROR_PHRASES
    assert first_line not in FACTCHECK_NO_CLAIM_PHRASES
    assert "НЕ проверено" in sent
    assert service.check_claim.await_count == 0


def test_b1_gate_refusal_helper_covers_both_pools():
    """B1: единый шов раннего отказа (v1) — причина + оговорка для обоих
    пулов (no_claim / уточнение), и прежняя фраза без непроверенной картинки."""
    from services.factcheck_service import ClaimMediaMaterial, ClaimPublication

    unchecked = ClaimPublication(
        text="проверь скрин", caption_text="проверь скрин", has_image=True,
        media=ClaimMediaMaterial(image_present=True, image_unchecked=True,
                                 unchecked_reason="provider_timeout",
                                 image_count=1))
    for pool in (FACTCHECK_NO_CLAIM_PHRASES, hfc.FACTCHECK_CLARIFY_PHRASES):
        text = hfc._gate_refusal_text(unchecked, pool)
        first = text.split("\n", 1)[0]
        assert first in FACTCHECK_MEDIA_ERROR_PHRASES
        assert "НЕ проверено" in text

    clean = ClaimPublication(text="Земля плоская", caption_text="Земля плоская")
    text = hfc._gate_refusal_text(clean, FACTCHECK_NO_CLAIM_PHRASES)
    assert text in FACTCHECK_NO_CLAIM_PHRASES       # прежнее поведение


# ── B2: «анализа нет и задачи нет» — не вечный pending ─────────────────────

@pytest.mark.asyncio
async def test_b2_missing_analysis_does_not_block_digest(db):
    """B2: у фото есть актив, но нет ни анализа, ни задачи (Vision был
    выключен при приёме). Раньше конспект окна не строился НИКОГДА: элемент
    висел в pending, а watchdog его не видел. Теперь это не ожидание."""
    from services.summary_memory import visual_window_state

    photo_tg = 2100
    rows = await _window_rows(db, photo_tg)
    await _img(db, photo_tg, serial=210)      # анализа нет, задачи нет

    state = await visual_window_state(db, CHAT, rows, consumer="summary")
    assert state["pending"] == {}, "«анализа нет» — не идущая работа"
    assert int(photo_tg) in state["missing"]
    assert state["ready"] == {} and state["failed"] == {}

    llm = _CaptureLLM()
    memory = MemoryManager(db, llm)
    status = await memory._build_running_summary_impl(CHAT, rows)
    assert status == "success"
    payload = llm.calls[0][-1]["content"]
    assert "болтовня номер 3" in payload
    assert "изображение" not in payload.lower()   # содержимого картинки нет
    stored = await db.get_running_summary(CHAT, time.time())
    assert stored is not None and stored["summary"]


@pytest.mark.asyncio
async def test_b2_running_analysis_still_defers_digest(db):
    """B2 (граница): реально идущий анализ (есть задача) по-прежнему
    откладывает конспект — defer только для настоящего pending."""
    photo_tg = 2200
    rows = await _window_rows(db, photo_tg)
    asset_id = await _img(db, photo_tg, serial=220)
    await _rec(db, asset_id, status="running")

    llm = _CaptureLLM()
    memory = MemoryManager(db, llm)
    status = await memory._build_running_summary_impl(CHAT, rows)
    assert status == "skipped_media_pending"
    assert llm.calls == []


# ── P1: отложенный фактчек (durable) возобновляется сам ────────────────────

@pytest.mark.asyncio
async def test_p1_factcheck_pending_defers_and_resumes_once(db, monkeypatch):
    """P1 (§4.6): фактчек с pending-OCR сохраняется одним durable-намерением и
    возобновляется тем же worker-sweep'ом Vision — один логический результат,
    без повторной присылки запроса пользователем и без второго ответа."""
    from services import factcheck_orchestrator as orch

    # Единая ветка вычисления (legacy): temporal-конверт здесь не предмет теста.
    monkeypatch.setattr("services.mca_gates.temporal_factcheck_enabled",
                        lambda: False)
    hot.set_config_cache(_Cfg({"limits.vision_readiness_wait_seconds": 0.01}))
    await _msg(db, 2300, media_type="photo", caption="проверь скрин",
               author="Аня")
    asset_id = await _img(db, 2300, serial=231)
    analysis_id = await _rec(db, asset_id, status="running")
    await _vision_job(db, 2300, asset_id, serial=231)

    service = MagicMock()
    service.check_claim = AsyncMock(return_value="Вердикт: не подтверждается")
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(return_value="ок")
    bot = AsyncMock()

    previous_handler = getattr(mr, "_RESUME_HANDLER", None)
    mr.set_resume_handler(None)
    orch.bind_runtime(db=db, service=service)
    try:
        outcome = await orch.run_factcheck(
            _factcheck_req(2300, "проверь скрин"), service=service, db=db,
            bot=bot, cache=_FakeCache())
        assert outcome == orch.OUTCOME_PENDING

        intents = await _intent_payloads(db)
        assert len(intents) == 1, intents
        assert intents[0]["consumer"] == orch.FACTCHECK_RESUME_CONSUMER
        assert intents[0]["notified"] is False

        # Повторный тот же запрос не создаёт второе намерение (coalesce).
        await orch.run_factcheck(
            _factcheck_req(2300, "проверь скрин"), service=service, db=db,
            bot=bot, cache=_FakeCache())
        assert len(await _intent_payloads(db)) == 1

        bot.reset_mock()
        await db.finish_media_analysis(
            analysis_id, expected_revision=1, status="ready",
            ocr_blocks=[{"text": "Скрин: перевод 5000",
                         "channel": "untrusted_data"}],
            visual_description="скриншот перевода")

        first = await mr.resume_deferred_requests(db, bot=bot)
        assert first["resumed"] == 1
        delivered = bot.send_message.await_count
        assert delivered >= 1
        assert service.check_claim.await_count == 1

        second = await mr.resume_deferred_requests(db, bot=bot)
        assert second["resumed"] == 0
        assert bot.send_message.await_count == delivered      # дубля нет
        assert await _intent_payloads(db) == []               # намерение закрыто
    finally:
        mr.set_resume_handler(previous_handler)


@pytest.mark.asyncio
async def test_p1_factcheck_terminal_failure_resumes_honestly_once(db, monkeypatch):
    """P1: терминальный отказ Vision тоже завершает отложенный фактчек —
    одним честным ответом с причиной и оговоркой (без выдуманного вердикта)."""
    from services import factcheck_orchestrator as orch
    from services.task_supervisor import TaskJobStore

    monkeypatch.setattr("services.mca_gates.temporal_factcheck_enabled",
                        lambda: False)
    hot.set_config_cache(_Cfg({"limits.vision_readiness_wait_seconds": 0.01}))
    await _msg(db, 2400, media_type="photo", caption="проверь скрин",
               author="Аня")
    asset_id = await _img(db, 2400, serial=241)
    analysis_id = await _rec(db, asset_id, status="running")
    await _vision_job(db, 2400, asset_id, serial=241)

    service = MagicMock()
    service.check_claim = AsyncMock(side_effect=AssertionError(
        "по непроверенной картинке вердикт не выдумывается"))
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(return_value="ок")
    bot = AsyncMock()

    previous_handler = getattr(mr, "_RESUME_HANDLER", None)
    mr.set_resume_handler(None)
    orch.bind_runtime(db=db, service=service)
    try:
        assert await orch.run_factcheck(
            _factcheck_req(2400, "проверь скрин"), service=service, db=db,
            bot=bot, cache=_FakeCache()) == orch.OUTCOME_PENDING
        bot.reset_mock()

        job = (await _intent_payloads(db))[0]
        await db.finish_media_analysis(
            analysis_id, expected_revision=1, status="failed",
            error_reason="provider_timeout")
        # Задача распознавания закрывается тем же терминалом (иначе ядро
        # честно считает, что запланирован retry, и ждёт дальше).
        store = TaskJobStore(db)
        for row in await store.active():
            if row.get("kind") == mca_vision.VISION_JOB_KIND:
                await store.finish(str(row.get("job_id")), status="failed",
                                   reason_code="provider_timeout")

        summary = await mr.resume_deferred_requests(db, bot=bot)
        assert summary["terminal"] == 1
        sent = bot.send_message.await_args.args[1]
        assert sent.split("\n", 1)[0] in FACTCHECK_MEDIA_ERROR_PHRASES
        assert "НЕ проверено" in sent
        assert service.check_claim.await_count == 0
        assert job["consumer"] == orch.FACTCHECK_RESUME_CONSUMER
        assert await _intent_payloads(db) == []
    finally:
        mr.set_resume_handler(previous_handler)


@pytest.mark.asyncio
async def test_p1_v1_pending_request_defers_and_resumes_once(db, monkeypatch):
    """P1 (v1-маршрут, DEFAULT): пока OCR идёт, хендлер больше не просит
    «повтори через минуту», а регистрирует то же durable-намерение — ответ
    приходит сам после распознавания, ровно один раз."""
    from services import factcheck_orchestrator as orch
    from services.factcheck_service import ClaimMediaMaterial, ClaimPublication

    monkeypatch.setattr(hfc, "_pipeline_v2_enabled", lambda: False)
    monkeypatch.setattr(hfc, "_temporal_on", lambda: True)
    # Возобновлённый прогон идёт через единый оркестратор (в фоне нет aiogram-
    # объектов исходной просьбы); временной контур выключен — проверяется
    # обычное вычисление, а не маршрут конверта.
    monkeypatch.setattr("services.mca_gates.temporal_factcheck_enabled",
                        lambda: False)
    hot.set_config_cache(_Cfg({"limits.vision_readiness_wait_seconds": 0.01}))
    await _msg(db, 2600, media_type="photo", caption="проверь скрин",
               author="Аня")
    asset_id = await _img(db, 2600, serial=261)
    analysis_id = await _rec(db, asset_id, status="running")
    await _vision_job(db, 2600, asset_id, serial=261)

    target = _photo_message(2600, serial=261, caption="проверь скрин",
                            chat_id=CHAT)
    trigger = _text_message(2699, "фактчек", chat_id=CHAT).model_copy(
        update={"reply_to_message": target})

    service = MagicMock()
    service.check_claim = AsyncMock(return_value="Вердикт: не подтверждается")
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(return_value="ок")
    hfc.setup_factcheck(service, db)
    orch.bind_runtime(db=db, service=service)

    gate_decision = MagicMock()
    gate_decision.decision = "no_claim_after_context"

    async def _gate(chat_id, before, after, **kwargs):
        return "", gate_decision

    monkeypatch.setattr(hfc, "_fetch_context_with_gate", _gate)

    pending_pub = ClaimPublication(
        text="проверь скрин", caption_text="проверь скрин", has_image=True,
        media=ClaimMediaMaterial(image_present=True, image_not_analyzed=True,
                                 pending_count=1, image_count=1))

    async def _resolve(message, tgt):
        return pending_pub

    monkeypatch.setattr(hfc, "_resolve_publication", _resolve)

    previous_handler = getattr(mr, "_RESUME_HANDLER", None)
    mr.set_resume_handler(None)
    bot = AsyncMock()
    try:
        await hfc.factcheck_handler(trigger, bot=bot)

        sent = bot.send_message.await_args.args[1]
        first_line = sent.split("\n", 1)[0]
        assert first_line in FACTCHECK_IMAGE_PENDING_AUTO_PHRASES
        assert "повтори через минуту" not in sent
        assert service.check_claim.await_count == 0

        intents = await _intent_payloads(db)
        assert len(intents) == 1, intents
        assert intents[0]["consumer"] == orch.FACTCHECK_RESUME_CONSUMER

        # Анализ готов → продолжение самим sweep'ом; вердикт один.
        await db.finish_media_analysis(
            analysis_id, expected_revision=1, status="ready",
            ocr_blocks=[{"text": "Скрин: перевод 5000",
                         "channel": "untrusted_data"}],
            visual_description="скриншот перевода")
        bot.reset_mock()
        first = await mr.resume_deferred_requests(db, bot=bot)
        assert first["resumed"] == 1
        delivered = bot.send_message.await_count
        assert delivered >= 1
        assert service.check_claim.await_count == 1

        second = await mr.resume_deferred_requests(db, bot=bot)
        assert second["resumed"] == 0
        assert bot.send_message.await_count == delivered
        assert await _intent_payloads(db) == []
    finally:
        mr.set_resume_handler(previous_handler)


@pytest.mark.asyncio
async def test_p1_repeat_request_supersedes_deferred_intent(db, monkeypatch):
    """P1: повторная просьба по тому же сообщению отменяет старое намерение —
    один логический ответ (свежий прогон важнее отложенного)."""
    from services import factcheck_orchestrator as orch

    monkeypatch.setattr("services.mca_gates.temporal_factcheck_enabled",
                        lambda: False)
    hot.set_config_cache(_Cfg({"limits.vision_readiness_wait_seconds": 0.01}))
    await _msg(db, 2650, media_type="photo", caption="проверь скрин",
               author="Аня")
    asset_id = await _img(db, 2650, serial=266)
    await _rec(db, asset_id, status="running")
    await _vision_job(db, 2650, asset_id, serial=266)

    service = MagicMock()
    service.check_claim = AsyncMock(return_value="Вердикт: не подтверждается")
    service.llm = MagicMock()
    service.llm.generate = AsyncMock(return_value="ок")
    bot = AsyncMock()

    previous_handler = getattr(mr, "_RESUME_HANDLER", None)
    mr.set_resume_handler(None)
    orch.bind_runtime(db=db, service=service)
    try:
        await orch.run_factcheck(
            _factcheck_req(2650, "проверь скрин"), service=service, db=db,
            bot=bot, cache=_FakeCache())
        assert len(await _intent_payloads(db)) == 1

        assert await orch.cancel_deferred_factcheck(
            db, chat_id=CHAT, target_message_id=2650) is True
        assert await _intent_payloads(db) == []
        # Повторная отмена — no-op (идемпотентность state-машины).
        assert await orch.cancel_deferred_factcheck(
            db, chat_id=CHAT, target_message_id=2650) is False
    finally:
        mr.set_resume_handler(previous_handler)


@pytest.mark.asyncio
async def test_p1_fresh_request_after_ready_prevents_second_answer(db,
                                                                  monkeypatch):
    """P1 (один логический результат): если пользователь всё же повторил
    просьбу и анализ уже готов, отвечает ЭТОТ прогон, а отложенное намерение
    снимается — второго ответа из sweep'а нет."""
    from services import factcheck_orchestrator as orch
    from services.factcheck_service import ClaimMediaMaterial, ClaimPublication

    monkeypatch.setattr(hfc, "_pipeline_v2_enabled", lambda: False)
    monkeypatch.setattr(hfc, "_temporal_on", lambda: True)
    monkeypatch.setattr("services.mca_gates.temporal_factcheck_enabled",
                        lambda: False)
    hot.set_config_cache(_Cfg({"limits.vision_readiness_wait_seconds": 0.01}))
    await _msg(db, 2670, media_type="photo", caption="проверь скрин",
               author="Аня")
    asset_id = await _img(db, 2670, serial=268)
    analysis_id = await _rec(db, asset_id, status="running")
    await _vision_job(db, 2670, asset_id, serial=268)

    target = _photo_message(2670, serial=268, caption="проверь скрин",
                            chat_id=CHAT)
    trigger = _text_message(2698, "фактчек", chat_id=CHAT).model_copy(
        update={"reply_to_message": target})

    service = MagicMock()
    service.check_claim = AsyncMock(return_value="Вердикт: не подтверждается")
    service.llm = MagicMock()
    hfc.setup_factcheck(service, db)
    orch.bind_runtime(db=db, service=service)

    state = {"publication": ClaimPublication(
        text="проверь скрин", caption_text="проверь скрин", has_image=True,
        media=ClaimMediaMaterial(image_present=True, image_not_analyzed=True,
                                 pending_count=1, image_count=1))}

    async def _resolve(message, tgt):
        return state["publication"]

    monkeypatch.setattr(hfc, "_resolve_publication", _resolve)

    refusal = MagicMock()
    refusal.decision = "no_claim_after_context"
    checkable = MagicMock()
    checkable.decision = "checkable"
    gate = {"decision": refusal}

    async def _gate(chat_id, before, after, **kwargs):
        return "", gate["decision"]

    monkeypatch.setattr(hfc, "_fetch_context_with_gate", _gate)

    previous_handler = getattr(mr, "_RESUME_HANDLER", None)
    mr.set_resume_handler(None)
    bot = AsyncMock()
    try:
        await hfc.factcheck_handler(trigger, bot=bot)
        assert len(await _intent_payloads(db)) == 1

        # Анализ готов; пользователь повторяет просьбу — побеждает этот прогон.
        await db.finish_media_analysis(
            analysis_id, expected_revision=1, status="ready",
            ocr_blocks=[{"text": "Скрин: перевод 5000",
                         "channel": "untrusted_data"}],
            visual_description="скриншот перевода")
        state["publication"] = ClaimPublication(
            text="проверь скрин", caption_text="проверь скрин", has_image=True,
            media=ClaimMediaMaterial(image_present=True, image_analyzed=True,
                                     image_count=1))
        gate["decision"] = checkable
        monkeypatch.setattr(hfc, "_temporal_on", lambda: False)
        bot.reset_mock()
        await hfc.factcheck_handler(trigger, bot=bot)

        assert await _intent_payloads(db) == []       # намерение снято
        assert service.check_claim.await_count == 1
        delivered = bot.send_message.await_count
        assert delivered == 1

        summary = await mr.resume_deferred_requests(db, bot=bot)
        assert summary["resumed"] == 0
        assert bot.send_message.await_count == delivered   # второго ответа нет
    finally:
        mr.set_resume_handler(previous_handler)


# ── P2: статья и поиск видят содержимое фото С ПОДПИСЬЮ ────────────────────
@pytest.mark.asyncio
async def test_p2_captioned_photo_evidence_in_article_and_search(db):
    """P2: фото с подписью раньше уходило в статью/поиск как «подпись [фото]».
    Теперь готовый OCR с адресом (msg/asset/анализ vN) доходит до обоих
    потребителей, а непроверенное изображение — только честной строкой."""
    from services.chat_context import build_chat_context
    from services.summary_memory import visual_evidence_lines, visual_window_state
    from services.summary_xml import XmlGroundingBuilder

    await _msg(db, 2500, media_type="photo", caption="что на скрине?",
               author="Аня")
    asset_id = await _img(db, 2500, serial=251)
    await _ready(db, asset_id, text="Скрин: перевод 5000",
                 description="скриншот перевода")
    rows = [_row(2500, "что на скрине?", author="Аня", media_type="photo")]

    # Поиск: явный оптик-ин для потребителя, которому нужен поиск по картинке.
    ctx = await build_chat_context(db, rows, chat_id=CHAT,
                                   media_for_captioned=True)
    assert "Скрин: перевод 5000" in ctx
    assert f"msg:{CHAT}:2500" in ctx
    # Паритет остальных потребителей: без флага подпись рендерится как прежде.
    ctx_legacy = await build_chat_context(db, rows, chat_id=CHAT)
    assert "Скрин: перевод 5000" not in ctx_legacy
    assert "что на скрине?" in ctx_legacy

    # Статья (L1/L2 XML): свидетельство вместо плейсхолдера «[фото]».
    state = await visual_window_state(db, CHAT, rows, consumer="summary")
    evidence = visual_evidence_lines(state)
    xml_ctx = XmlGroundingBuilder().build(
        [_xml_row(2500, "что на скрине?", author="Аня")], window_caps=(None, None),
        media_evidence=evidence)
    assert "Скрин: перевод 5000" in xml_ctx
    assert "[фото]" not in xml_ctx
    assert f"msg:2500" in xml_ctx
    assert "анализ v" in xml_ctx

    # Непроверенное изображение: в статье честная строка, а не «[фото]».
    await _msg(db, 2501, media_type="photo", caption="а это?", author="Петя")
    failed_asset = await _img(db, 2501, serial=252)
    await _rec(db, failed_asset, status="failed",
               error_reason="provider_timeout")
    rows2 = [_row(2501, "а это?", author="Петя", media_type="photo")]
    state2 = await visual_window_state(db, CHAT, rows2, consumer="summary")
    evidence2 = visual_evidence_lines(state2)
    xml_ctx2 = XmlGroundingBuilder().build(
        [_xml_row(2501, "а это?", author="Петя")], window_caps=(None, None),
        media_evidence=evidence2)
    assert "не распознано" in xml_ctx2
    assert "[фото]" not in xml_ctx2


def _xml_row(tg_id: int, text: str, *, author: str = "Сергей") -> dict:
    """Строка окна в форме, которую читает XmlGroundingBuilder."""
    return _row(tg_id, text, author=author, media_type="photo")


@pytest.mark.asyncio
async def test_p2_summary_consumers_get_matching_evidence_shape(db):
    """P2 (регресс шва): фактам/графу нужен `{msg: {text, refs}}`, статье —
    строка. Один и тот же источник состояния, но разные формы: иначе готовый
    OCR не доходит до статьи/фактов (или путь фонового потребителя падает)."""
    from services.summary_generator import SummaryGenerator
    from services.summary_memory import _build_batch_text, visual_window_state

    await _msg(db, 2700, media_type="photo", caption="что на скрине?",
               author="Аня")
    asset_id = await _img(db, 2700, serial=271)
    await _ready(db, asset_id, text="Скрин: перевод 5000",
                 description="скриншот перевода")
    rows = [_row(2700, "что на скрине?", author="Аня", media_type="photo")]

    state = await visual_window_state(db, CHAT, rows, consumer="summary")
    facts = SummaryGenerator._media_facts_evidence(state)
    lines = SummaryGenerator._media_xml_evidence(state)
    assert facts and isinstance(facts[2700], dict)
    assert lines and isinstance(lines[2700], str)

    text = _build_batch_text(rows, skip_empty=True, media_evidence=facts)
    assert "Скрин: перевод 5000" in text          # готовый OCR дошёл до фактов
    assert "msg:" in text and "asset:" in text    # адрес источника сохранён
    assert "Скрин: перевод 5000" in lines[2700]


def test_p2_facts_evidence_excludes_unready_media():
    """P2: ожидающая/упавшая картинка не становится «фактом» — в долговременное
    знание идёт только завершённый анализ (честный статус — в статье, не в
    фактах)."""
    from services.summary_generator import SummaryGenerator

    assert SummaryGenerator._media_facts_evidence(
        {"ready": {}, "pending": {1: "vision_queued"},
         "failed": {2: "provider_timeout"}, "missing": {}}) is None
    assert SummaryGenerator._media_xml_evidence(None) is None


# ── review-fix3: гибридный путь статьи (L1/L2) получает визуальные данные ──

class _StopHybrid(BaseException):
    """Прерывание тестового прогона сразу после захвата payload Writer'а.

    Наследуется от BaseException намеренно: `_run_hybrid_l2` гасит любые
    `Exception` (LEVEL-3/UX), а тесту нужен ровно один факт — что ушло в
    Writer статьи, без последующих публикаций/фолбэков."""


@pytest.mark.asyncio
async def test_review_fix3_hybrid_article_payload_carries_visual_evidence(
        db, monkeypatch):
    """review-fix3 (§4/§8.18/§9.3): статья по умолчанию строится гибридным
    контуром, поэтому готовый OCR captioned-фото обязан попадать в §92-payload
    этого контура (раньше — только в Legacy XML). Без медиа элемент прежний."""
    from types import SimpleNamespace

    from services import summary_generator as sg
    from services import summary_l1_clusterizer as sl1
    from services.summary_memory import visual_window_state

    await _msg(db, 3000, media_type="photo", caption="что на скрине?",
               author="Аня")
    asset_id = await _img(db, 3000, serial=301)
    await _ready(db, asset_id, text="Скрин: перевод 5000",
                 description="скриншот перевода")
    rows = [_row(3000, "что на скрине?", author="Аня", media_type="photo")]

    # 1) Паритет по умолчанию: без свидетельства элемент §92 байт-в-байт
    #    прежний (подпись автора, никакого OCR).
    plain = sl1.build_l1_payload(rows, CHAT)
    assert plain[0]["text"] == "что на скрине?"
    assert "перевод 5000" not in plain[0]["text"]

    # 2) Сам payload принимает свидетельство: адрес источника сохранён.
    state = await visual_window_state(db, CHAT, rows, consumer="summary")
    lines = sg.SummaryGenerator._media_xml_evidence(state)
    assert lines and "перевод 5000" in lines[3000]
    enriched = sl1.build_l1_payload(rows, CHAT, visual_evidence=lines)
    assert "что на скрине?" in enriched[0]["text"]
    assert "Скрин: перевод 5000" in enriched[0]["text"]
    for token in ("msg:", "asset:", "анализ v"):
        assert token in enriched[0]["text"]
    assert enriched[0]["message_type"] == "photo"

    # 3) Продакшн-путь: `_run_hybrid_l2` (Hybrid L1/L2 — режим по умолчанию)
    #    отдаёт Writer'у статьи payload, уже содержащий OCR и адрес источника.
    memory = MagicMock()
    memory.db = db
    gen = sg.SummaryGenerator(memory=memory, xml=MagicMock(),
                              llm=MagicMock(), bot=None)
    l1_map = {"schema_version": 1,
              "topics": [{"topic_id": "topic_001", "title": "скрин перевода",
                          "message_ids": [3000], "participants": [],
                          "short_hint": ""}],
              "events": [], "unassigned_message_ids": []}
    fake_l1 = SimpleNamespace(
        usable=True, payload=l1_map, threads_count=1, invalid_reason=None,
        status="ok", duration_ms=1.0, map_degraded=False, map_stats={})

    async def _fake_run_l1(**kwargs):
        return fake_l1

    monkeypatch.setattr(sl1, "run_l1", _fake_run_l1)
    captured: dict = {}

    async def _capture(chat_id, rows_arg, payload_items, *args, **kwargs):
        captured["payload"] = payload_items
        captured["visual"] = kwargs.get("visual_evidence")
        raise _StopHybrid()

    monkeypatch.setattr(gen, "_run_writer_source_stage", _capture)

    # Writer-от-окна — прод-дефолт ON (conftest держит kill-switch OFF для
    # остальных тестов набора: здесь он осознанно возвращается к продакшну).
    with patched_settings(SUMMARY_WRITER_SOURCE_INPUT_ENABLED=True):
        with pytest.raises(_StopHybrid):
            await gen._run_hybrid_l2(CHAT, rows, None, "review-fix3-run")

    payload = captured.get("payload")
    assert payload, "Writer статьи не получил payload — гибридный путь не дошёл"
    assert "Скрин: перевод 5000" in payload[0]["text"]
    assert "msg:" in payload[0]["text"] and "asset:" in payload[0]["text"]
    assert "анализ v" in payload[0]["text"]
    assert "[фото]" not in payload[0]["text"]


@pytest.mark.asyncio
async def test_review_fix3_hybrid_payload_honest_status_for_unready_media(db):
    """review-fix3: нераспознанное изображение в статье — честный статус
    (ожидание/отказ с причиной), а не выдуманное содержимое и не пустая
    подпись."""
    from services import summary_l1_clusterizer as sl1
    from services.summary_generator import SummaryGenerator
    from services.summary_memory import visual_window_state

    await _msg(db, 3100, media_type="photo", author="Аня")
    pending_asset = await _img(db, 3100, serial=311)
    await _vision_job(db, 3100, pending_asset, serial=311)
    await _msg(db, 3101, media_type="photo", caption="а это?", author="Петя")
    failed_asset = await _img(db, 3101, serial=312)
    await _rec(db, failed_asset, status="failed", error_reason="provider_timeout")

    rows = [_row(3100, "", author="Аня", media_type="photo"),
            _row(3101, "а это?", author="Петя", media_type="photo")]
    state = await visual_window_state(db, CHAT, rows, consumer="summary")
    lines = SummaryGenerator._media_xml_evidence(state)
    payload = sl1.build_l1_payload(rows, CHAT, visual_evidence=lines)

    assert "распознаётся" in payload[0]["text"]        # идёт работа — честно
    assert "не распознано" in payload[1]["text"]       # отказ назван
    assert "а это?" in payload[1]["text"]              # подпись сохранена


@pytest.mark.asyncio
async def test_review_fix3_legacy_full_window_reduction_keeps_visual_evidence(
        db):
    """review-fix3 (§9.3): урезанная иерархическая свёртка большого окна
    (Legacy full-window) — тоже потребление §92-содержимого, поэтому готовый
    OCR доходит и туда, а не только в плоский XML малого окна."""
    from services.summary_generator import SummaryGenerator
    from services.summary_memory import visual_window_state

    await _msg(db, 3200, media_type="photo", caption="что на скрине?",
               author="Аня")
    asset_id = await _img(db, 3200, serial=321)
    await _ready(db, asset_id, text="Скрин: перевод 5000",
                 description="скриншот перевода")
    rows = [_row(3200, "что на скрине?", author="Аня", media_type="photo")]

    memory = MagicMock()
    memory.db = db
    gen = SummaryGenerator(memory=memory, xml=MagicMock(),
                           llm=MagicMock(), bot=None)
    state = await visual_window_state(db, CHAT, rows, consumer="summary")
    lines = SummaryGenerator._media_xml_evidence(state)

    with_visual, _cov = await gen._build_legacy_full_window_context(
        CHAT, rows, "review-fix3-legacy", visual_evidence=lines)
    without, _cov2 = await gen._build_legacy_full_window_context(
        CHAT, rows, "review-fix3-legacy")
    assert with_visual and "Скрин: перевод 5000" in with_visual
    assert "msg:" in with_visual and "asset:" in with_visual
    assert without and "Скрин: перевод 5000" not in without
    assert "что на скрине?" in without       # подпись прежняя, без OCR

