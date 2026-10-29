"""EVOL-015 — Telegram quote (выделенный фрагмент reply) полный конвейер.

Покрывает (offline-фикстуры, без сети/Telegram):
  * миграция v38: аддитивные колонки `smart_messages` (position/is_manual/
    entities), идемпотентность, книга `schema_migrations`;
  * ингест: полный quote-блок из aiogram `Message.quote` (TextQuote) —
    text/author/position (VERBATIM UTF-16 offset, НЕ пересчитывается)/
    is_manual/entities (safe JSON);
  * персист: канонический путь (identity ON) и legacy (OFF) — round-trip
    с рестарт-симуляцией (переоткрытие БД);
  * контекст: ChainItem несёт quote; рендер `format_chain_line` помечает
    выделенный фрагмент как ПРИОРИТЕТНЫЙ ПРЕДМЕТ у хода-триггера;
    недоступный оригинал — честная пометка ограничения;
  * регресс: обычный reply (без quote) — байт-в-байт прежняя строка;
  * изоляция: оба чата — без перекрёстных утечек цитат/авторов;
  * телеметрия: quote_present / quote_missing_in_transport /
    quote_delivered_to_context / quote_unavailable (R17: без текстов);
  * рендеры: `<Speech_Understanding>` (предмет вопроса) и canonical
    envelope (UTF-16 offset suffix).
TEST-LIFECYCLE: CONTRACT (user-контракт EVOL-015, plans/current_task.md §4).
"""
import json

import pytest

from services import claim_envelope as _ce
from services import canonical_messages as _cm
from services import message_identity as _mi
from services import thread_chain
from services.canonical_context import format_context_item
from services.database import DatabaseService, row_get


# ── фикстуры/хелперы ─────────────────────────────────────────────────────────

async def _fresh(tmp_path, name="evol015.db") -> DatabaseService:
    svc = DatabaseService(str(tmp_path / name))
    await svc.initialize()
    return svc


class _Ent:
    """Минимальный двойник aiogram MessageEntity (скалярные поля)."""

    def __init__(self, type="bold", offset=0, length=5, url=None,
                 user=None, language=None, custom_emoji_id=None):
        self.type = type
        self.offset = offset
        self.length = length
        self.url = url
        self.user = user
        self.language = language
        self.custom_emoji_id = custom_emoji_id


class _Quote:
    """Минимальный двойник aiogram TextQuote."""

    def __init__(self, text, position, is_manual=False, entities=None):
        self.text = text
        self.position = position
        self.is_manual = is_manual
        self.entities = entities


class _User:
    def __init__(self, uid):
        self.id = uid


class _Msg:
    """Минимальный двойник aiogram Message для `_extract_quote_fields`."""

    def __init__(self, *, chat_id=-1003000000001, message_id=501,
                 reply_to=None, quote=None):
        self.chat = type("C", (), {"id": chat_id})()
        self.message_id = message_id
        self.reply_to_message = reply_to
        self.quote = quote


# ── v38: аддитивная миграция ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v38_additive_columns_and_book(tmp_path):
    d = await _fresh(tmp_path)
    try:
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 38
        info = await d.db.execute("PRAGMA table_info(smart_messages)")
        cols = {r["name"] for r in await info.fetchall()}
        assert {"quote_text", "quote_author_id", "quote_position",
                "quote_is_manual", "quote_entities"} <= cols
        book = await d.db.execute(
            "SELECT name FROM schema_migrations WHERE version = 38")
        row = await book.fetchone()
        assert row is not None and row["name"] == "quote_metadata_v38"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v38_restart_idempotent_and_old_row_intact(tmp_path):
    d = await _fresh(tmp_path)
    try:
        await _mi.save_live_message(
            d, chat_id=100, user_id=1, text="до-миграции-строка",
            tg_message_id=7)
    finally:
        await d.close()
    # рестарт-симуляция: новый экземпляр на той же БД, повторный runner
    d2 = DatabaseService(str(tmp_path / "evol015.db"))
    await d2.initialize()
    try:
        cur = await d2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 38
        row = await d2.get_smart_message_by_tg_id(100, 7)
        assert row["text"] == "до-миграции-строка"
        # строка без quote-данных = честный NULL (задним числом не дорисуется)
        assert row_get(row, "quote_position") is None
        assert row_get(row, "quote_is_manual") is None
    finally:
        await d2.close()


# ── ингест: полный quote-блок ────────────────────────────────────────────────

def test_ingest_extracts_full_quote_metadata():
    from handlers.summary import _extract_quote_fields
    target = _Msg(message_id=500)
    target.from_user = _User(2)
    msg = _Msg(message_id=501, reply_to=target, quote=_Quote(
        text="если S Pen", position=1234, is_manual=True,
        entities=[_Ent(offset=0, length=10), _Ent(type="mention",
                                                  offset=2, length=4,
                                                  user=_User(9))]))
    fields = _extract_quote_fields(msg)
    assert fields["quote_text"] == "если S Pen"
    assert fields["quote_author_id"] == 2          # автор reply_to_message
    assert fields["quote_position"] == 1234        # verbatim, не пересчёт
    assert fields["quote_is_manual"] == 1
    ents = json.loads(fields["quote_entities"])
    assert ents[0] == {"type": "bold", "offset": 0, "length": 10}
    assert ents[1]["user_id"] == 9                 # user схлопнут в user_id


def test_ingest_quote_absent_and_malformed():
    from handlers.summary import _extract_quote_fields
    # обычный reply без quote — все поля None (честный unknown)
    target = _Msg(message_id=500)
    target.from_user = _User(2)
    plain = _Msg(message_id=501, reply_to=target, quote=None)
    assert _extract_quote_fields(plain) == {
        "quote_text": None, "quote_author_id": None, "quote_position": None,
        "quote_is_manual": None, "quote_entities": None}
    # битые типы position/is_manual → None (не мусор в SQL-binding)
    weird = _Msg(message_id=502, reply_to=target, quote=_Quote(
        text="x", position="не-число", is_manual="да"))
    fields = _extract_quote_fields(weird)
    assert fields["quote_position"] is None
    assert fields["quote_is_manual"] is None
    # quote без reply_to → автор честно None
    orphan = _Msg(message_id=503, reply_to=None, quote=_Quote("фрагмент", 5))
    assert _extract_quote_fields(orphan)["quote_author_id"] is None


def test_ingest_entities_serialization_bounded():
    from handlers.summary import _serialize_quote_entities, \
        _QUOTE_ENTITIES_MAX_CHARS
    assert _serialize_quote_entities(None) is None
    assert _serialize_quote_entities([]) is None
    # bounded: не более 32 entities, переполнение лимита → None (честный unknown)
    few = [_Ent(url="x" * 20) for _ in range(10)]
    out = _serialize_quote_entities(few)
    assert out is not None and len(out) <= _QUOTE_ENTITIES_MAX_CHARS
    assert out.count("{") == 10
    overflow = [_Ent(url="x" * 200) for _ in range(40)]
    assert _serialize_quote_entities(overflow) is None


# ── персист + контекст: фикстура «если S Pen» ───────────────────────────────

async def _save_spen_pair(d, *, chat_id=-1003000000001):
    """Оригинал (длинный текст про S27 Pro) + reply с цитатой «если S Pen»."""
    original = ("Обзор Samsung S27 Pro: экран 27 дюймов, 4K. "
                "Многие спрашивают про стилус: если S Pen поддерживается, "
                "то рисовать удобно. Цена и даты выхода — под вопросом.")
    await _mi.save_live_message(
        d, chat_id=chat_id, user_id=2, text=original, sent_at=1700000000,
        tg_message_id=500)
    quote_position = original.index("если S Pen")   # UTF-16 == Python для BMP
    await _mi.save_live_message(
        d, chat_id=chat_id, user_id=1, text="Че это такое",
        sent_at=1700000060, tg_message_id=501, reply_to_id=500,
        reply_to_author_id=2, quote_text="если S Pen", quote_author_id=2,
        quote_position=quote_position, quote_is_manual=0,
        quote_entities=json.dumps([{"type": "bold", "offset": 0,
                                    "length": 10}]))
    return original, quote_position


@pytest.mark.asyncio
async def test_a_spen_quote_marks_subject_in_context(tmp_path):
    d = await _fresh(tmp_path)
    try:
        original, position = await _save_spen_pair(d)
        chain = await thread_chain.collect_thread_chain(
            d, -1003000000001, 501, depth=5)
        assert [it.item_id for it in chain] == ["tg:501", "tg:500"]
        trigger, root = chain
        assert trigger.quote_text == "если S Pen"
        assert trigger.quote_position == position      # verbatim
        assert trigger.quote_original_available is True
        line = thread_chain.format_chain_line(
            trigger, None, trigger_message_id=501)
        # выделенный фрагмент = ПРЕДМЕТ ответа (структурный ассерт)
        assert "если S Pen" in line
        assert "ПРИОРИТЕТНЫЙ ПРЕДМЕТ" in line
        assert "автор: 2" in line
        # полный оригинал присутствует как контекст (отдельный ход)
        root_line = thread_chain.format_chain_line(root, None, 501)
        assert "S27 Pro" in root_line
        # (1) обычный текст вопроса тоже на месте
        assert "Че это такое" in line
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_b_mid_message_repeated_substring(tmp_path):
    d = await _fresh(tmp_path)
    try:
        original = "тест раз, тест два, тест три"
        second = original.index("тест", original.index("тест") + 1)
        await _mi.save_live_message(
            d, chat_id=100, user_id=2, text=original, tg_message_id=500)
        await _mi.save_live_message(
            d, chat_id=100, user_id=1, text="что тут?", tg_message_id=501,
            reply_to_id=500, quote_text="тест", quote_author_id=2,
            quote_position=second, quote_is_manual=0)
        chain = await thread_chain.collect_thread_chain(d, 100, 501, depth=5)
        assert chain[0].quote_position == second       # 2-е вхождение, вербатим
        assert chain[0].quote_text == "тест"
        line = thread_chain.format_chain_line(chain[0], None, 501)
        assert "«тест»" in line and "ПРИОРИТЕТНЫЙ ПРЕДМЕТ" in line
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_c_newline_emoji_utf16_offset_verbatim(tmp_path):
    d = await _fresh(tmp_path)
    try:
        # эмодзи = 2 UTF-16 units: UTF-16 offset «текст» = 8 (Python index 4).
        original = "😍😍😍 текст с переносом\nвторой строки"
        await _mi.save_live_message(
            d, chat_id=100, user_id=2, text=original, tg_message_id=500)
        quote_text = "текст с переносом\nвторой строки"
        utf16_position = 8              # Telegram UTF-16 offset (≠ py 4)
        await _mi.save_live_message(
            d, chat_id=100, user_id=1, text="а что тут", tg_message_id=501,
            reply_to_id=500, quote_text=quote_text, quote_author_id=2,
            quote_position=utf16_position, quote_is_manual=1)
        row = await d.get_smart_message_by_tg_id(100, 501)
        # сохранено ВЕРБАТИМ (не пересчитано поиском: py-index был бы 4)
        assert row_get(row, "quote_position") == 8
        assert row_get(row, "quote_text") == quote_text   # \n сохранён
        assert row_get(row, "quote_is_manual") == 1
        chain = await thread_chain.collect_thread_chain(d, 100, 501, depth=5)
        line = thread_chain.format_chain_line(chain[0], None, 501)
        # перенос схлопнут каноном (_squash), текст цитаты доставлен целиком
        assert "текст с переносом второй строки" in line
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_d_plain_reply_byte_parity(tmp_path):
    d = await _fresh(tmp_path)
    try:
        await _mi.save_live_message(
            d, chat_id=100, user_id=2, text="оригинал", tg_message_id=500)
        # reply БЕЗ quote-полей (старые строки/обычные ответы)
        await _mi.save_live_message(
            d, chat_id=100, user_id=1, text="вопрос", tg_message_id=501,
            reply_to_id=500, reply_to_author_id=2)
        chain = await thread_chain.collect_thread_chain(d, 100, 501, depth=5)
        assert all(it.quote_text is None for it in chain)
        assert all(it.quote_position is None for it in chain)
        line = thread_chain.format_chain_line(chain[0], None, 501)
        # байт-в-байт равен прежнему рендеру (format_context_item напрямую)
        expected = format_context_item(
            ts=chain[0].ts, author=thread_chain.speaker_tag(
                chain[0].name, chain[0].uid),
            item_id=chain[0].item_id, forward_source=None,
            text=chain[0].text, kind="msg", is_target=True)
        assert line == expected
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_e_quote_unavailable_original(tmp_path, monkeypatch):
    events = []

    def fake_emit(event_name, **kwargs):
        events.append((event_name, kwargs))

    import services.mca_events as me
    monkeypatch.setattr(me, "emit_mca_event", fake_emit)
    d = await _fresh(tmp_path)
    try:
        # reply с цитатой, НО оригинал (tg 999) не сохранён
        await _mi.save_live_message(
            d, chat_id=100, user_id=1, text="что это", tg_message_id=501,
            reply_to_id=999, quote_text="фрагмент", quote_author_id=2,
            quote_position=3, quote_is_manual=0)
        chain = await thread_chain.collect_thread_chain(d, 100, 501, depth=5)
        assert len(chain) == 1
        assert chain[0].quote_original_available is False
        line = thread_chain.format_chain_line(chain[0], None, 501)
        assert "фрагмент" in line
        assert "оригинал недоступен" in line
        assert "ПРИОРИТЕТНЫЙ ПРЕДМЕТ" not in line      # не обещаем лишнего
        # телеметрия: quote_unavailable (context), R17 — без текстов
        quote_events = [e for e in events if e[0] == "quote"]
        assert any(kw.get("stage") == "quote_unavailable"
                   and kw.get("component") == "context"
                   for _, kw in quote_events)
        assert all("фрагмент" not in str(kw) for _, kw in quote_events)
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_f_persist_roundtrip_restart(tmp_path):
    d = await _fresh(tmp_path)
    _, position = await _save_spen_pair(d)
    await d.close()
    d2 = DatabaseService(str(tmp_path / "evol015.db"))
    await d2.initialize()
    try:
        row = await d2.get_smart_message_by_tg_id(-1003000000001, 501)
        assert row["quote_text"] == "если S Pen"
        assert row["quote_author_id"] == 2
        assert row_get(row, "quote_position") == position
        assert row_get(row, "quote_is_manual") == 0
        assert json.loads(row_get(row, "quote_entities")) == [
            {"type": "bold", "offset": 0, "length": 10}]
    finally:
        await d2.close()


@pytest.mark.asyncio
async def test_g_two_chats_isolation(tmp_path):
    d = await _fresh(tmp_path)
    try:
        chat_a, chat_b = -1003000000001, -1003000000002
        for chat, quote in ((chat_a, "цитата А"), (chat_b, "цитата Б")):
            await _mi.save_live_message(
                d, chat_id=chat, user_id=2, text=f"оригинал {chat}",
                tg_message_id=500)
            await _mi.save_live_message(
                d, chat_id=chat, user_id=1, text="вопрос", tg_message_id=501,
                reply_to_id=500, quote_text=quote, quote_author_id=2,
                quote_position=0, quote_is_manual=0)
        row_a = await d.get_smart_message_by_tg_id(chat_a, 501)
        row_b = await d.get_smart_message_by_tg_id(chat_b, 501)
        assert row_a["quote_text"] == "цитата А"
        assert row_b["quote_text"] == "цитата Б"
        # окно каждого чата несёт только свои quote-значения
        win_a = await d.get_smart_window(chat_a, 0, 10)
        win_b = await d.get_smart_window(chat_b, 0, 10)
        assert {r["quote_text"] for r in win_a if r["quote_text"]} == \
            {"цитата А"}
        assert {r["quote_text"] for r in win_b if r["quote_text"]} == \
            {"цитата Б"}
        # цепочка каждого чата — только свои ходы/цитаты
        chain_a = await thread_chain.collect_thread_chain(d, chat_a, 501, 5)
        assert chain_a[0].quote_text == "цитата А"
        assert chain_a[1].text.endswith(str(chat_a))
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_legacy_off_path_persists_quote(tmp_path, monkeypatch):
    monkeypatch.setattr(_mi, "identity_enabled", lambda: False)
    d = await _fresh(tmp_path)
    try:
        rid = await _mi.save_live_message(
            d, chat_id=100, user_id=1, text="вопрос", tg_message_id=501,
            reply_to_id=500, quote_text="оф-цитата", quote_author_id=2,
            quote_position=42, quote_is_manual=1,
            quote_entities=json.dumps([{"type": "italic", "offset": 1,
                                        "length": 3}]))
        assert rid > 0
        row = await d.get_smart_message_by_tg_id(100, 501)
        assert row["quote_text"] == "оф-цитата"
        assert row_get(row, "quote_position") == 42
        assert row_get(row, "quote_is_manual") == 1
        assert json.loads(row_get(row, "quote_entities"))[0]["length"] == 3
    finally:
        await d.close()


# ── телеметрия ингеста ───────────────────────────────────────────────────────

def test_ingest_telemetry_taxonomy(monkeypatch):
    from handlers import summary as h
    events = []

    def fake_emit(event_name, **kwargs):
        events.append((event_name, kwargs))

    import services.mca_events as me
    monkeypatch.setattr(me, "emit_mca_event", fake_emit)
    target = _Msg(message_id=500)
    target.from_user = _User(2)
    with_quote = _Msg(message_id=501, reply_to=target,
                      quote=_Quote("фрагмент", 3))
    h._extract_quote_fields(with_quote)
    plain = _Msg(message_id=502, reply_to=target, quote=None)
    h._extract_quote_fields(plain)
    # события эмитит сам обработчик; здесь проверяем маппинг кода на outcome
    h._emit_quote_event("present", chat_id=1, message_id=501)
    h._emit_quote_event("missing_in_transport", chat_id=1, message_id=502)
    names = {kw.get("stage"): kw for name, kw in events if name == "quote"}
    assert names["quote_present"]["outcome"] == "success"
    assert names["quote_present"]["component"] == "ingestion"
    assert names["quote_missing_in_transport"]["outcome"] == "skipped"
    # R17: в событиях нет текстов
    assert all("фрагмент" not in str(kw) for kw in names.values())


@pytest.mark.asyncio
async def test_context_telemetry_delivered(monkeypatch, tmp_path):
    events = []

    def fake_emit(event_name, **kwargs):
        events.append((event_name, kwargs))

    import services.mca_events as me
    monkeypatch.setattr(me, "emit_mca_event", fake_emit)
    d = await _fresh(tmp_path)
    try:
        await _save_spen_pair(d)
        chain = await thread_chain.collect_thread_chain(
            d, -1003000000001, 501, depth=5)
        thread_chain.format_chain_line(chain[0], None, 501)
        delivered = [kw for name, kw in events
                     if name == "quote"
                     and kw.get("stage") == "quote_delivered_to_context"]
        assert delivered and delivered[0]["component"] == "context"
    finally:
        await d.close()


# ── окно/ 最近: SELECT'ы несут quote-поля ────────────────────────────────────

@pytest.mark.asyncio
async def test_window_selects_return_quote_fields(tmp_path):
    d = await _fresh(tmp_path)
    try:
        await _save_spen_pair(d)
        window = await d.get_smart_window(-1003000000001, 0, 10)
        by_tg = {r["tg_message_id"]: r for r in window}
        assert by_tg[501]["quote_text"] == "если S Pen"
        assert by_tg[500]["quote_text"] is None
        raw = await d.get_smart_raw(-1003000000001, 2 ** 31, 10)
        assert any(r["quote_text"] == "если S Pen" for r in raw)
        recent = await d.get_recent_messages(-1003000000001, 10)
        assert any(r["quote_text"] == "если S Pen" for r in recent)
    finally:
        await d.close()


# ── рендеры: Speech_Understanding и canonical envelope ──────────────────────

def test_speech_block_quote_subject_and_parity():
    # с доставленным текстом цитаты — предмет вопроса ПЕРВОЙ строкой
    u = _ce.build_speech_understanding(
        "Че это такое", has_reply_parent=True, quote_text_present=True,
        quote_text="если S Pen")
    block = _ce.render_speech_block(u)
    assert "Предмет вопроса — выделенная цитата" in block
    assert "«если S Pen»" in block
    assert block.index("Предмет вопроса") < block.index("Цитата принадлежит")
    # без текста цитаты — байт-паритет прежнему блоку
    u_old = _ce.build_speech_understanding(
        "Че это такое", has_reply_parent=True, quote_text_present=True)
    expected = ("<Speech_Understanding>\n"
                "Цитата принадлежит её автору: не приписывай чужие слова "
                "себе; если автор не установлен — не додумывай его.\n"
                "</Speech_Understanding>")
    assert _ce.render_speech_block(u_old) == expected


def test_canonical_envelope_quote_suffix():
    row = {"id": 9, "user_id": 1, "chat_id": 100, "text": "вопрос",
           "reply_to_id": None, "timestamp": 0, "media_type": "text",
           "author_name": "вася", "is_forward": 0, "forward_source": "",
           "tg_message_id": 501, "caption": None, "sent_at": None,
           "ingested_at": None, "edited_at": None, "sent_at_source": None,
           "source_kind": "live", "namespace": "live",
           "source_record_id": None, "content_hash": None,
           "media_ref": None, "reply_to_kind": None,
           "reply_to_author_id": None, "quote_text": "если S Pen",
           "quote_author_id": 2, "quote_position": 1234,
           "quote_is_manual": 1, "quote_entities": None,
           "forward_author_id": None, "message_state": "active",
           "state_evidence": None, "current_revision": 1}
    msg = _cm.message_from_row(row)
    assert msg.quote_position == 1234
    out = _cm.format_canonical_envelope(msg)
    assert "> если S Pen (автор цитаты: 2; фрагмент UTF-16 offset 1234)" in out
    assert "выделенный фрагмент" in out
    # без v38-полей — прежний формат без суффикса
    legacy = _cm.CanonicalMessage(
        message_ref="tg:501", source_ref_id=None, row_id=9, chat_id=100,
        tg_message_id=501, revision=1, source_kind="live",
        speaker_entity_id=1, speaker_display_name="вася", sent_at=None,
        ingested_at=None, edited_at=None, reply_to_message_ref=None,
        reply_to_speaker_entity_id=None, quote_text="если S Pen",
        quote_source_ref=None, quote_speaker_entity_id=2,
        forward_source=None, forward_speaker_entity_id=None,
        is_forward=False, thread_id=None, media_type="text",
        media_ref=None, content_hash=None, message_state="active",
        raw_text="вопрос", caption=None)
    out_legacy = _cm.format_canonical_envelope(legacy)
    assert "> если S Pen (автор цитаты: 2) — выделенный фрагмент" in out_legacy
    assert "UTF-16 offset" not in out_legacy


# ── dcs-проводка: живой quote → Speech_Understanding (EVOL-015 §5) ──────────

def test_dcs_wiring_live_quote_reaches_speech_block(monkeypatch):
    import types

    import services.mca_gates as gates
    from services.direct_chat_service import DirectChatService

    monkeypatch.setattr(gates, "character_speech_enabled", lambda: True)
    svc = DirectChatService.__new__(DirectChatService)

    def _msg(chat_type="group", quote=None, reply_to=None):
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(type=chat_type),
            reply_to_message=reply_to, quote=quote)

    # (a) живой reply с цитатой: фрагмент доходит, блок активен, предмет —
    #     первой строкой
    msg = _msg(quote=types.SimpleNamespace(
        text="если S Pen", position=10, is_manual=False, entities=[]))
    u = svc._build_speech_understanding(msg, "Че это такое")
    assert u is not None
    assert u.quote is True
    assert u.quote_text == "если S Pen"
    block = _ce.render_speech_block(u)
    assert "Предмет вопроса — выделенная цитата" in block
    assert "«если S Pen»" in block
    # (b) обычный reply без quote — прежнее поведение (нет предмета)
    u_plain = svc._build_speech_understanding(_msg(), "привет")
    assert u_plain is not None
    assert u_plain.quote_text == ""
    assert _ce.render_speech_block(u_plain) == ""
    # (c) битый quote-текст (не-str/пустой) → None, честный unknown
    u_bad = svc._build_speech_understanding(
        _msg(quote=types.SimpleNamespace(text="   ", position=0)), "вопрос")
    assert u_bad.quote_text == ""
    # (d) атрибуция из mca-22-контура сохранена (bundle с автором)
    bundle = types.SimpleNamespace(quoted_speaker="2", ambiguities=())
    u_bundle = svc._build_speech_understanding(_msg(), "вопрос",
                                               bundle=bundle)
    assert u_bundle.quote_attribution == _ce.QUOTE_ATTRIBUTION_KNOWN
