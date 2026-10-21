"""INIT-REPLY-FIX (owner-obs diagnostics 21.10.2026 §4) — reply-привязка
инициативного ответа к сообщению адресата.

Дефект: addressee_user_id + source_refs доезжают до Writer/L1, но точка
отправки в handle_initiative звала send_text БЕЗ reply_to_message_id —
24/24 инициативных отправок за 7д уходили standalone (журнал 18–21.10).

Контракт (диагностика §4.1–4.3):
* при адресате reply ставится: msg:<smart_messages.id> → колонка
  smart_messages.tg_message_id (фолбэк — последний tg_message_id адресата
  в чате), ТОЛЬКО на первом чанке (прецедент
  smartmodule_utils.send_chunked_reply);
* без адресата/ссылок (ностальгия/heartbeat) — отправка без reply
  (поведение прежнее);
* протухшая цель (старше 24ч) → без reply; цель исчезла к моменту
  отправки (400 «message to be replied not found») → ровно один повтор
  без reply (паттерн smartmodule_utils._send_once).

Верификация на моках: 0 provider-вызовов, 0 сообщений в реальные чаты;
R17 — проверяются только id/kwargs, содержимое не логируется.

TEST-LIFECYCLE: CONTRACT owner=INIT-REPLY-FIX (reply при адресате, первый чанк)
TEST-LIFECYCLE: CONTRACT owner=INIT-REPLY-FIX (без адресата — без reply)
TEST-LIFECYCLE: REGRESSION owner=INIT-REPLY-FIX (протухшая/пропавшая цель)
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
    """Duck-typed writer (контракт §13.2: plan + generate)."""

    def __init__(self, text="Отвечаю адресату по существу."):
        self.text = text
        self.plan_calls = 0
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        self.plan_calls += 1
        return L1Plan(action="reply", confidence=0.9,
                      confidence_bucket="high", source="llm")

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


async def _addressee_message(db, *, tg_id: int, age_s: int = 600) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, ?, 'text', 'addr', 0, ?)",
        (USER, CHAT, "вопрос адресата", int(time.time()) - int(age_s), tg_id))
    await db.db.commit()
    return cursor.lastrowid


# ═══ 1. Адресат есть → reply на его сообщение, только на первом чанке ════════

@pytest.mark.asyncio
async def test_addressed_initiative_reply_binds_to_addressee_message(
        tmp_path, monkeypatch):
    db = await _db(tmp_path, "initreply_a.db")
    calls: list = []

    async def _fake_send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7100 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    now = int(time.time())
    msg_row_id = await _addressee_message(db, tg_id=555001)
    opportunity_row = obs.build_opportunity_row(
        CHAT, kind="topic_interest", goal="обсудить вопрос адресата",
        fallback="dispute", rows=[{"id": msg_row_id}], now=now,
        addressee_user_id=USER, rationale="прямой вопрос адресата")
    writer = _FakeWriter()
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-initreply-a", opportunity_row=opportunity_row)
    assert result["status"] == "sent"
    assert len(calls) == 1
    # msg:<smart_messages.id> → tg_message_id этой же строки
    assert calls[0].get("reply_to_message_id") == 555001
    await db.close()


@pytest.mark.asyncio
async def test_addressed_initiative_reply_only_on_first_chunk(
        tmp_path, monkeypatch):
    db = await _db(tmp_path, "initreply_b.db")
    calls: list = []

    async def _fake_send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7200 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    now = int(time.time())
    msg_row_id = await _addressee_message(db, tg_id=555002)
    opportunity_row = obs.build_opportunity_row(
        CHAT, kind="topic_interest", goal="обсудить вопрос адресата",
        fallback="dispute", rows=[{"id": msg_row_id}], now=now,
        addressee_user_id=USER, rationale="прямой вопрос адресата")
    writer = _FakeWriter(text="ч" * 9000)   # 3 чанка по CHUNK_LIMIT=4096
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=writer,
        correlation_id="corr-initreply-b", opportunity_row=opportunity_row)
    assert result["status"] == "sent"
    assert len(calls) == 3
    # reply ТОЛЬКО у первого чанка (прецедент send_chunked_reply)
    assert calls[0].get("reply_to_message_id") == 555002
    assert "reply_to_message_id" not in calls[1]
    assert "reply_to_message_id" not in calls[2]
    await db.close()


# ═══ 2. Без адресата (ностальгия/heartbeat) → без reply ══════════════════════

@pytest.mark.asyncio
async def test_nostalgia_without_addressee_sends_without_reply(
        tmp_path, monkeypatch):
    db = await _db(tmp_path, "initreply_c.db")
    calls: list = []

    async def _fake_send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7300 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    # путь ностальгии: prepared_text передан, opportunity_row/writer нет
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db,
        prepared_text="А помнишь, как мы обсуждали то лето?",
        correlation_id="corr-initreply-c")
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "reply_to_message_id" not in calls[0]
    await db.close()


# ═══ 3. Протухшая/пропавшая цель → отправка без reply ════════════════════════

@pytest.mark.asyncio
async def test_stale_target_sends_without_reply(tmp_path, monkeypatch):
    db = await _db(tmp_path, "initreply_d.db")
    calls: list = []

    async def _fake_send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 7400 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    now = int(time.time())
    msg_row_id = await _addressee_message(db, tg_id=555003,
                                          age_s=25 * 3600)   # > 24ч
    opportunity_row = obs.build_opportunity_row(
        CHAT, kind="topic_interest", goal="обсудить вопрос адресата",
        fallback="dispute", rows=[{"id": msg_row_id}], now=now,
        addressee_user_id=USER, rationale="прямой вопрос адресата")
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=_FakeWriter(),
        correlation_id="corr-initreply-d", opportunity_row=opportunity_row)
    assert result["status"] == "sent"
    assert len(calls) == 1
    assert "reply_to_message_id" not in calls[0]
    await db.close()


@pytest.mark.asyncio
async def test_gone_target_retries_once_without_reply(tmp_path, monkeypatch):
    db = await _db(tmp_path, "initreply_e.db")
    calls: list = []

    async def _fake_send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("reply_to_message_id"):
            raise TelegramBadRequest(
                method="sendMessage",
                message="Bad Request: message to be replied not found")

        class _Msg:
            message_id = 7500 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    now = int(time.time())
    msg_row_id = await _addressee_message(db, tg_id=555004)
    opportunity_row = obs.build_opportunity_row(
        CHAT, kind="topic_interest", goal="обсудить вопрос адресата",
        fallback="dispute", rows=[{"id": msg_row_id}], now=now,
        addressee_user_id=USER, rationale="прямой вопрос адресата")
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], db=db, writer_service=_FakeWriter(),
        correlation_id="corr-initreply-e", opportunity_row=opportunity_row)
    # отправка состоялась — ровно один повтор без reply
    assert result["status"] == "sent"
    assert len(calls) == 2
    assert calls[0].get("reply_to_message_id") == 555004
    assert "reply_to_message_id" not in calls[1]
    await db.close()
