"""L1D (owner-corrective-initreply 22.10.2026) — форма участия решается L1,
транспорт только исполняет решение с техническими проверками цели (§6).

Дефект 2.58.109 (отменён директивой): детерминированный резолвер
``_initiative_reply_target`` превращал инициативу в reply при наличии
``source_refs``/``addressee_user_id`` — транспорт принимал смысловое
решение вместо LLM.

Новый контракт (§2-§8 директивы):
* привязка reply ТОЛЬКО из плана L1 (delivery=reply + target_message_id);
* target_user_id — смысловой адресат, сам по себе reply НЕ включает;
* react — исполняется существующим react_moai без текста;
* SILENT — ничего не отправляется;
* цель недоступна → БЕЗ произвольной перепривязки: fail-soft обычная
  отправка (текст самостоятелен) ИЛИ отмена/SendRecheck (прямой ответ
  человеку потерял бы смысл);
* reply только у первого чанка; ностальгия/heartbeat (без L1) — путь прежний.

Верификация на моках: 0 provider-вызовов, 0 сообщений в реальные чаты;
R17 — проверяются только id/kwargs, содержимое не логируется.

TEST-LIFECYCLE: CONTRACT owner=INITREPLY-L1D (§8 кейсы 1-8, форма из плана L1)
TEST-LIFECYCLE: REGRESSION owner=INITREPLY-L1D (2.58.109: source_refs ≠ команда reply)
TEST-LIFECYCLE: REGRESSION owner=INITREPLY-L1D (нет произвольной перепривязки цели)
"""
from __future__ import annotations

import time

import pytest
from aiogram.exceptions import TelegramBadRequest

from services import initiative_observer as obs
from services import mca_intents as mi
from services.database import DatabaseService
from services.direct_chat_service import handle_initiative
from services.direct_l1 import L1Plan

CHAT = -3301
USER = 777
OTHER = 888


class _FakeBot:
    def __init__(self):
        self.id = 42
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), str(text), dict(kwargs)))

        class _Msg:
            message_id = 5000 + len(self.sent)

        return _Msg()


class _FakeWriter:
    """Duck-typed writer (контракт §13.2: plan + generate); план задаёт тест."""

    def __init__(self, plan: L1Plan | None = None, text="Ответ по существу."):
        self.plan = plan or L1Plan(action="reply", confidence=0.9,
                                   confidence_bucket="high", source="llm")
        self.text = text
        self.plan_calls = 0
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        self.plan_calls += 1
        return self.plan

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        return self.text


async def _db(tmp_path, name: str) -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


def _situation() -> mi.InitiativeSituation:
    return mi.InitiativeSituation(
        trigger_kind="intent_due", chat_id=CHAT, direct_pending=False,
        same_event_pending=False, sensitive_moment=False, relations_ok=True,
        bot_replied_recently=False, reply_needed=False, topic_open=True,
        open_intent_ids=None, requested_source="observer")


def _candidate():
    return mi.candidate_from_trigger(
        trigger_kind="intent_due", chat_id=CHAT, reason_code="default")


async def _message(db, *, tg_id: int, user_id: int = USER,
                   age_s: int = 600, text: str = "вопрос адресата") -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, ?, 'text', 'addr', 0, ?)",
        (user_id, CHAT, text, int(time.time()) - int(age_s), tg_id))
    await db.db.commit()
    return cursor.lastrowid


def _opportunity(db_row_id: int, *, addressee: int | None = USER) -> dict:
    return obs.build_opportunity_row(
        CHAT, kind="topic_interest", goal="обсудить вопрос адресата",
        fallback="dispute", rows=[{"id": db_row_id}], now=int(time.time()),
        addressee_user_id=addressee, rationale="прямой вопрос адресата")


async def _run(tmp_path, name, *, writer, opportunity=None,
               monkeypatch=None, send_hook=None) -> tuple[dict, list]:
    calls: list = []

    async def _default_send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7000 + len(calls)

        return _Msg()

    if monkeypatch is not None:
        monkeypatch.setattr("services.telegram_send.send_text",
                            send_hook or _default_send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=await _db(tmp_path, name),
        writer_service=writer,
        correlation_id=f"corr-{name}", opportunity_row=opportunity)
    return result, calls


# ═══ §8 кейс 1: L1 выбрала standalone при заполненных source_refs ════════════

@pytest.mark.asyncio
async def test_case1_standalone_despite_source_refs(tmp_path, monkeypatch):
    """РЕГРЕССИЯ 2.58.109: source_refs/addressee в поводе — контекст, а не
    команда reply. L1 решила standalone → обычное сообщение."""
    db = await _db(tmp_path, "l1d_c1.db")
    row_id = await _message(db, tg_id=555001)
    opportunity = _opportunity(row_id)          # source_refs + addressee ЕСТЬ
    writer = _FakeWriter(L1Plan(action="reply", delivery="",
                                confidence=0.9, confidence_bucket="high"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7100 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c1", opportunity_row=opportunity)
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "reply_to_message_id" not in calls[0]
    await db.close()


# ═══ §8 кейс 2: standalone со смысловым адресатом — без reply ════════════════

@pytest.mark.asyncio
async def test_case2_standalone_with_semantic_addressee(tmp_path,
                                                        monkeypatch):
    """Сценарий C: обращение к человеку внутри обычного сообщения;
    target_user_id сам по себе reply НЕ включает."""
    db = await _db(tmp_path, "l1d_c2.db")
    row_id = await _message(db, tg_id=555002)
    writer = _FakeWriter(L1Plan(action="reply", delivery="chat",
                                target_user_id=USER, confidence=0.9,
                                confidence_bucket="high",
                                source="llm"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7200 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c2",
        opportunity_row=_opportunity(row_id))
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "reply_to_message_id" not in calls[0]
    await db.close()


# ═══ §8 кейс 3: L1 выбрала reply на конкретное сообщение ═════════════════════

@pytest.mark.asyncio
async def test_case3_reply_to_l1_chosen_message(tmp_path, monkeypatch):
    """Сценарий B: delivery=reply + target_message_id → reply именно на
    выбранное L1 сообщение (tg_message_id этой строки)."""
    db = await _db(tmp_path, "l1d_c3.db")
    row_id = await _message(db, tg_id=555003)
    writer = _FakeWriter(L1Plan(action="reply", delivery="reply",
                                target_message_id=row_id, confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7300 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c3",
        opportunity_row=_opportunity(row_id, addressee=None))
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert calls[0].get("reply_to_message_id") == 555003
    await db.close()


# ═══ §8 кейс 4: несколько пользователей — транспорт не выбирает адресата ═════

@pytest.mark.asyncio
async def test_case4_transport_never_picks_addressee(tmp_path, monkeypatch):
    """В окне несколько участников; addressee_user_id в поводе указывает на
    одного, план L1 — без привязки → НИКАКОГО reply (старый фолбэк «последнее
    сообщение адресата» удалён). И наоборот: привязка идёт строго к цели из
    плана, даже если она другого пользователя."""
    db = await _db(tmp_path, "l1d_c4.db")
    row_user = await _message(db, tg_id=555004, user_id=USER)
    await _message(db, tg_id=555005, user_id=OTHER, text="мнение другого")
    await _message(db, tg_id=555006, user_id=USER, text="ещё реплика")
    # (a) план без привязки: старый резолвер ответил бы 555006 (последнее
    # сообщение адресата) — теперь обычная отправка.
    writer = _FakeWriter(L1Plan(action="reply", confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7400 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c4a",
        opportunity_row=_opportunity(row_user))
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "reply_to_message_id" not in calls[0]
    # (b) план выбрал сообщение ДРУГОГО пользователя — транспорт исполняет.
    other_row = await _message(db, tg_id=555007, user_id=OTHER,
                               text="мысль для ответа")
    writer2 = _FakeWriter(L1Plan(action="reply", delivery="reply",
                                 target_message_id=other_row,
                                 confidence=0.9, confidence_bucket="high",
                                 source="llm"))
    calls2: list = []

    async def _send2(bot, chat_id, text, **kwargs):
        calls2.append(dict(kwargs))

        class _Msg:
            message_id = 7500 + len(calls2)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send2)
    result2 = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer2,
        correlation_id="corr-l1d-c4b",
        opportunity_row=_opportunity(row_user))
    assert result2["status"] == "sent"
    assert calls2[0].get("reply_to_message_id") == 555007
    await db.close()


# ═══ §8 кейс 5: SILENT — ничего не отправляется ══════════════════════════════

@pytest.mark.asyncio
async def test_case5_silent_sends_nothing(tmp_path, monkeypatch):
    db = await _db(tmp_path, "l1d_c5.db")
    row_id = await _message(db, tg_id=555008)
    writer = _FakeWriter(L1Plan(action="silent", confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []
    reacts: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7600 + len(calls)

        return _Msg()

    async def _react(bot, chat_id, message_id, *, reaction=None,
                     reason_code=None):
        reacts.append((chat_id, message_id, reaction))
        return "ok"

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    monkeypatch.setattr("services.direct_chat_service.react_moai", _react)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c5",
        opportunity_row=_opportunity(row_id))
    assert result["status"] == "silent"
    assert result["reason_code"] == "l1_silent"
    assert calls == [] and reacts == []
    assert writer.generate_calls == 0
    await db.close()


# ═══ §8 кейс 6: поддерживаемая реакция исполняется без текста ════════════════

@pytest.mark.asyncio
async def test_case6_react_executes_without_text(tmp_path, monkeypatch):
    db = await _db(tmp_path, "l1d_c6.db")
    row_id = await _message(db, tg_id=555009)
    writer = _FakeWriter(L1Plan(action="react", reaction="😂",
                                target_message_id=row_id, confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []
    reacts: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7700 + len(calls)

        return _Msg()

    async def _react(bot, chat_id, message_id, *, reaction=None,
                     reason_code=None):
        reacts.append((chat_id, message_id, reaction, reason_code))
        return "ok"

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    monkeypatch.setattr("services.direct_chat_service.react_moai", _react)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c6",
        opportunity_row=_opportunity(row_id, addressee=None))
    assert result["status"] == "reacted"
    assert result["reason_code"] == "l1_react"
    # реакция ровно на выбранное L1 сообщение, без текстового сообщения
    assert reacts == [(CHAT, 555009, "😂", "l1_react")]
    assert calls == []
    assert writer.generate_calls == 0
    await db.close()


@pytest.mark.asyncio
async def test_case6b_invalid_reaction_is_honest_silence(tmp_path,
                                                         monkeypatch):
    """Невалидная реакция/цель → честное молчание БЕЗ подмены (§6/§7)."""
    db = await _db(tmp_path, "l1d_c6b.db")
    row_id = await _message(db, tg_id=555010)
    writer = _FakeWriter(L1Plan(action="react", reaction="🚀",   # не в allowed
                                target_message_id=row_id, confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []
    reacts: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7750 + len(calls)

        return _Msg()

    async def _react(bot, chat_id, message_id, *, reaction=None,
                     reason_code=None):
        reacts.append((chat_id, message_id, reaction))
        return "ok"

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    monkeypatch.setattr("services.direct_chat_service.react_moai", _react)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c6b",
        opportunity_row=_opportunity(row_id, addressee=None))
    assert result["status"] == "silent"
    assert result["reason_code"] == "l1_react"
    assert reacts == [] and calls == []
    await db.close()


# ═══ §8 кейс 7: цель отсутствует/устарела — без произвольной перепривязки ════

@pytest.mark.asyncio
async def test_case7_missing_target_failsoft_no_rebinding(tmp_path,
                                                          monkeypatch):
    """Цели нет; в плане нет смыслового адресата → текст самостоятелен:
    ровно одна обычная отправка (fail-soft), НЕ другая цель."""
    db = await _db(tmp_path, "l1d_c7a.db")
    row_id = await _message(db, tg_id=555011)
    writer = _FakeWriter(L1Plan(action="reply", delivery="reply",
                                target_message_id=10 ** 9,   # не существует
                                confidence=0.9, confidence_bucket="high",
                                source="llm"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7800 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c7a",
        opportunity_row=_opportunity(row_id, addressee=None))
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "reply_to_message_id" not in calls[0]
    await db.close()


@pytest.mark.asyncio
async def test_case7b_stale_target_with_addressee_cancels(tmp_path,
                                                          monkeypatch):
    """Устаревшая цель + смысловой адресат: прямой ответ человеку без
    привязки теряет смысл → SendRecheck-семантика (отмена, БЕЗ отправки)."""
    db = await _db(tmp_path, "l1d_c7b.db")
    row_id = await _message(db, tg_id=555012, age_s=48 * 3600)  # вне окна
    writer = _FakeWriter(L1Plan(action="reply", delivery="reply",
                                target_message_id=row_id,
                                target_user_id=USER, confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7900 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c7b",
        opportunity_row=_opportunity(row_id))
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "target_stale"
    assert calls == []            # «тот же текст в общий чат» не уходит
    await db.close()


@pytest.mark.asyncio
async def test_case7c_addressee_mismatch_no_rebinding(tmp_path, monkeypatch):
    """Цель принадлежит не тому пользователю, кому L1 адресовала ответ →
    без произвольной перепривязки: отмена (адресат в плане указан)."""
    db = await _db(tmp_path, "l1d_c7c.db")
    other_row = await _message(db, tg_id=555013, user_id=OTHER)
    writer = _FakeWriter(L1Plan(action="reply", delivery="reply",
                                target_message_id=other_row,
                                target_user_id=USER, confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7950 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c7c",
        opportunity_row=_opportunity(other_row))
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "target_addressee_mismatch"
    assert calls == []
    await db.close()


# ═══ §8 кейс 8: разбивка длинного текста — reply только у первого чанка ══════

@pytest.mark.asyncio
async def test_case8_reply_only_on_first_chunk(tmp_path, monkeypatch):
    db = await _db(tmp_path, "l1d_c8.db")
    row_id = await _message(db, tg_id=555014)
    writer = _FakeWriter(L1Plan(action="reply", delivery="reply",
                                target_message_id=row_id, confidence=0.9,
                                confidence_bucket="high", source="llm"),
                         text="ч" * 9000)          # 3 чанка по CHUNK_LIMIT
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 8000 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-c8",
        opportunity_row=_opportunity(row_id, addressee=None))
    assert result["status"] == "sent"
    assert len(calls) == 3
    assert calls[0].get("reply_to_message_id") == 555014
    assert "reply_to_message_id" not in calls[1]
    assert "reply_to_message_id" not in calls[2]
    await db.close()


# ═══ Цель исчезла на момент отправки (400): семантика решения ════════════════

@pytest.mark.asyncio
async def test_gone_target_with_addressee_cancels_without_send(tmp_path,
                                                               monkeypatch):
    """400 «message to be replied not found» при смысловом адресате:
    нельзя снять привязку прямого ответа — отмена без отправки."""
    db = await _db(tmp_path, "l1d_gone_a.db")
    row_id = await _message(db, tg_id=555015)
    writer = _FakeWriter(L1Plan(action="reply", delivery="reply",
                                target_message_id=row_id,
                                target_user_id=USER, confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("reply_to_message_id"):
            raise TelegramBadRequest(
                method="sendMessage",
                message="Bad Request: message to be replied not found")

        class _Msg:
            message_id = 8100 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-gone-a",
        opportunity_row=_opportunity(row_id))
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "target_gone"
    assert len(calls) == 1        # единственная попытка с reply; без-reply нет
    await db.close()


@pytest.mark.asyncio
async def test_gone_target_without_addressee_retries_once(tmp_path,
                                                          monkeypatch):
    """400 без смыслового адресата (текст самостоятелен): прежний прецедент —
    ровно один повтор без reply."""
    db = await _db(tmp_path, "l1d_gone_b.db")
    row_id = await _message(db, tg_id=555016)
    writer = _FakeWriter(L1Plan(action="reply", delivery="reply",
                                target_message_id=row_id, confidence=0.9,
                                confidence_bucket="high", source="llm"))
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("reply_to_message_id"):
            raise TelegramBadRequest(
                method="sendMessage",
                message="Bad Request: message to be replied not found")

        class _Msg:
            message_id = 8200 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-l1d-gone-b",
        opportunity_row=_opportunity(row_id, addressee=None))
    assert result["status"] == "sent"
    assert len(calls) == 2
    assert calls[0].get("reply_to_message_id") == 555016
    assert "reply_to_message_id" not in calls[1]
    await db.close()


# ═══ Ностальгия/heartbeat (без L1) — путь прежний ════════════════════════════

@pytest.mark.asyncio
async def test_nostalgia_without_writer_sends_without_reply(tmp_path,
                                                            monkeypatch):
    db = await _db(tmp_path, "l1d_nostalgia.db")
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 8300 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db,
        prepared_text="А помнишь, как мы обсуждали то лето?",
        correlation_id="corr-l1d-nostalgia")
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "reply_to_message_id" not in calls[0]
    await db.close()
