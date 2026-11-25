"""P0 DIRECT-TRIGGER / L1 AUTONOMY (owner 26.11.2026, lane 1).

Контракт (plans/owner_inputs/2026-11-26-p0-direct-trigger-l1-media.md §1-§3):
  * команда «бот» — запуск разговорного контура, НЕ обязательный текстовый
    ответ; срабатывает только на СОбственном тексте участника (не пересылка,
    не цитата, не текст стороннего бота);
  * тип адресации вычисляется хендлером один раз и передаётся в сервис без
    повторной классификации другим regex;
  * L1 свободно выбирает reply/silent/react; silent после действительного
    обращения — существующая реакция 🗿; без обращения 🗿 не ставится;
  * пустой/битый/сорванный L1 — существующий recovery, не «осознанное
    молчание».

TEST-LIFECYCLE: CONTRACT owner=P0-DIRECT-TRIGGER-2026-11-26
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import (
    Chat, Message, MessageEntity, MessageOriginHiddenUser, MessageOriginUser,
    PhotoSize, TextQuote, User,
)

import handlers.direct_chat as dc_mod
import services.command_prefix as cp
import services.direct_chat_service as dcs
from services.llm_client import LLMError
from tests.test_asap7_direct_l1 import _drive, _FakeLLM, _plan_json

# Прод-дефолты ASAP-3 (в т.ч. DIRECT_SILENT_ACK_ENABLED=ON): conftest гасит
# kill-switch'и для старых тестов без маркера.
pytestmark = [pytest.mark.system2, pytest.mark.asap3]

BOT_ID = 12345
BOT_USERNAME = "test_bot"
CHAT_ID = -1001234567890
USER_ID = 10

_NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
_CHAT = Chat(id=CHAT_ID, type="supergroup")
_HUMAN = User(id=USER_ID, is_bot=False, first_name="Вася")
_OTHER_BOT = User(id=999, is_bot=True, first_name="MusicBot")


def _message(text=None, *, caption=None, entities=None,
             forward_origin=None, reply_to=None, from_user=_HUMAN,
             photo=False, message_id=1) -> Message:
    kwargs = dict(
        message_id=message_id, date=_NOW, chat=_CHAT, from_user=from_user,
        text=text, entities=entities, forward_origin=forward_origin,
        reply_to_message=reply_to)
    if caption is not None:
        kwargs["caption"] = caption
    if photo:
        kwargs["photo"] = [PhotoSize(file_id="p", file_unique_id="pu",
                                     width=1, height=1)]
    return Message(**kwargs)


@pytest.fixture(autouse=True)
def _legacy_direct_l1_off(monkeypatch):
    """Handler-уровень проверяем на legacy-пайплайне (как ADTR-ENTRY)."""
    from config.settings import Settings
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", False)
    yield


@pytest.fixture
def wire():
    service = MagicMock()
    service.handle = AsyncMock()
    dc_mod.setup_direct_chat(service, BOT_ID, BOT_USERNAME)
    yield service
    dc_mod.setup_direct_chat(None, None, None)


# ── 1. Один классификатор: хендлер и сервис не расходятся ───────────────────

def test_single_botword_source():
    # P0: второй независимый regex в сервисе удалён; хендлер использует
    # тот же объект command_prefix, что и сервис.
    assert dc_mod._BOTWORD_RE is cp.BOTWORD_RE
    assert not hasattr(dcs, "_BOTWORD_RE")
    assert dcs.TRIGGER_KEYWORD == cp.TRIGGER_KEYWORD


# ── 2. Команда срабатывает только на собственном тексте ─────────────────────

@pytest.mark.asyncio
async def test_own_keyword_starts_contour(wire):
    msg = _message("эй, бот, глянь")
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is None
    wire.handle.assert_awaited_once()
    assert wire.handle.await_args.kwargs["trigger_type"] == "keyword"


@pytest.mark.asyncio
async def test_own_mention_still_triggers(wire):
    text = "@test_bot привет"
    msg = _message(text, entities=[
        MessageEntity(type="mention", offset=0, length=len(BOT_USERNAME) + 1)])
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is None
    wire.handle.assert_awaited_once()
    assert wire.handle.await_args.kwargs["trigger_type"] == "mention"


@pytest.mark.asyncio
async def test_forwarded_text_keyword_no_trigger(wire):
    origin = MessageOriginUser(date=_NOW, sender_user=_HUMAN)
    msg = _message("Скидочный бот: нажми чтобы найти песню",
                   forward_origin=origin)
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is UNHANDLED
    wire.handle.assert_not_called()


@pytest.mark.asyncio
async def test_forwarded_text_hidden_source_no_trigger(wire):
    # Источник скрыт (имя не получено) — факт пересылки всё равно определён
    # по forward_origin, а не по успешности извлечения имени.
    origin = MessageOriginHiddenUser(date=_NOW, sender_user_name="")
    msg = _message("реклама: скидочный бот", forward_origin=origin)
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is UNHANDLED
    wire.handle.assert_not_called()


@pytest.mark.asyncio
async def test_forwarded_caption_keyword_no_trigger(wire):
    origin = MessageOriginUser(date=_NOW, sender_user=_HUMAN)
    msg = _message(caption="Нажми чтобы найти песню, скидочный бот",
                   forward_origin=origin, photo=True)
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is UNHANDLED
    wire.handle.assert_not_called()


@pytest.mark.asyncio
async def test_third_party_bot_text_no_trigger(wire):
    msg = _message("бот, вот трек", from_user=_OTHER_BOT)
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is UNHANDLED
    wire.handle.assert_not_called()


# ── 3. Нативная цитата vs собственный текст ─────────────────────────────────

def _quote_block(text: str) -> MessageEntity:
    """blockquote-entity на весь фрагмент (UTF-16 offset/length)."""
    return MessageEntity(type="expandable_blockquote", offset=0,
                         length=len(text))


@pytest.mark.asyncio
async def test_keyword_inside_quote_no_trigger(wire):
    quoted = "скидочный бот"
    msg = _message(f"{quoted}\n\nчто это за трек?",
                   entities=[_quote_block(quoted)])
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is UNHANDLED
    wire.handle.assert_not_called()


@pytest.mark.asyncio
async def test_own_text_outside_quote_triggers(wire):
    quoted = "рекламный бот"
    msg = _message(f"{quoted}\n\nбот, что это за трек?",
                   entities=[_quote_block(quoted)])
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is None
    wire.handle.assert_awaited_once()
    assert wire.handle.await_args.kwargs["trigger_type"] == "keyword"


@pytest.mark.asyncio
async def test_native_text_quote_keyword_not_own(wire):
    # Message.quote (TextQuote) — цитируемый фрагмент исходного сообщения;
    # в собственный текст он не входит, команду не запускает.
    msg = Message(
        message_id=2, date=_NOW, chat=_CHAT, from_user=_HUMAN,
        text="что думаешь про этот трек?",
        reply_to_message=_message("пересланный трек", message_id=51),
        quote=TextQuote(text="скидочный бот", position=0, is_manual=True))
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is UNHANDLED
    wire.handle.assert_not_called()


@pytest.mark.asyncio
async def test_reply_to_forwarded_with_own_words_triggers(wire):
    origin = MessageOriginUser(date=_NOW, sender_user=_HUMAN)
    forwarded = _message(caption="Нажми чтобы найти песню", photo=True,
                         forward_origin=origin, message_id=50)
    msg = _message("бот, что это за композиция?", reply_to=forwarded)
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is None
    wire.handle.assert_awaited_once()
    assert wire.handle.await_args.kwargs["trigger_type"] == "keyword"


@pytest.mark.asyncio
async def test_reply_to_bot_still_trigger(wire):
    bot_msg = _message("мой прошлый ответ", from_user=User(
        id=BOT_ID, is_bot=True, first_name="Adminbot"), message_id=60)
    msg = _message("а почему так?", reply_to=bot_msg)
    assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is None
    wire.handle.assert_awaited_once()
    assert wire.handle.await_args.kwargs["trigger_type"] == "reply_to_bot"


# ── 4. L1 сам выбирает действие (без forced override) ───────────────────────

@pytest.mark.asyncio
async def test_l1_reply_executes(monkeypatch):
    llm = _FakeLLM(l1=_plan_json(action="reply"), l2="вот ответ")
    svc, react, bot, msg, user = _drive(monkeypatch, "бот, ну такое", llm=llm)
    await svc.handle(bot, msg, user)
    svc._send_direct_answer.assert_awaited_once()
    assert svc._send_direct_answer.await_args.args[2] == "вот ответ"
    react.assert_not_awaited()


@pytest.mark.asyncio
async def test_l1_silent_gets_moai_not_text(monkeypatch):
    llm = _FakeLLM(l1=_plan_json(action="silent", confidence=0.95),
                   l2="не должно")
    svc, react, bot, msg, user = _drive(monkeypatch, "бот, ну такое", llm=llm)
    await svc.handle(bot, msg, user)
    react.assert_awaited_once()
    assert react.await_args.kwargs.get("reaction") == "🗿"
    svc._send_direct_answer.assert_not_awaited()
    assert llm.calls_of("l2_writer") == []


@pytest.mark.asyncio
async def test_l1_react_executes_chosen_reaction(monkeypatch):
    llm = _FakeLLM(l1=_plan_json(action="react", reaction="🔥"), l2="не должно")
    svc, react, bot, msg, user = _drive(monkeypatch, "бот, ахаха", llm=llm)
    await svc.handle(bot, msg, user)
    react.assert_awaited_once()
    assert react.await_args.kwargs.get("reaction") == "🔥"
    svc._send_direct_answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_genuine_address_silent_has_no_moai(monkeypatch):
    # Фоновый ход без действительного обращения: L1 SILENT — тишина без 🗿
    # (сохранённое поведение; сервис сам резолвит free_will по тексту).
    llm = _FakeLLM(l1=_plan_json(action="silent", confidence=0.95), l2="нельзя")
    svc, react, bot, msg, user = _drive(monkeypatch, "просто болтовня", llm=llm)
    await svc.handle(bot, msg, user)
    react.assert_not_awaited()
    svc._send_direct_answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_silent_ack_conjunction_unit(monkeypatch):
    # 🗿 — только при действительном обращении; free-will без ack.
    svc, react, bot, _msg, _user = _drive(monkeypatch, "просто болтовня")
    await svc._execute_silent_ack(
        bot, chat_id=CHAT_ID, trigger_id=1, addressed_trigger=False,
        addressed=True, reason="l1_silent")
    react.assert_not_awaited()
    await svc._execute_silent_ack(
        bot, chat_id=CHAT_ID, trigger_id=1, addressed_trigger=True,
        addressed=True, reason="l1_silent")
    react.assert_awaited_once()
    assert react.await_args.kwargs.get("reaction") == "🗿"


# ── 5. Recovery: L1 недоступен ≠ осознанное молчание ────────────────────────

@pytest.mark.asyncio
async def test_l1_outage_genuine_address_falls_back_to_reply(monkeypatch):
    llm = _FakeLLM(l1_error=LLMError("l1 outage"), l2="честный fallback")
    svc, react, bot, msg, user = _drive(monkeypatch, "как дела?", llm=llm)
    await svc.handle(bot, msg, user)
    svc._send_direct_answer.assert_awaited_once()
    assert svc._send_direct_answer.await_args.args[2] == "честный fallback"
    react.assert_not_awaited()


@pytest.mark.asyncio
async def test_l1_outage_addressed_silent_preaction_is_not_silent(monkeypatch):
    # Матрица дала бы SILENT (бот недавно отвечал), но L1 упал — это не
    # осознанное молчание: действительное обращение получает recovery-reply.
    llm = _FakeLLM(l1_error=LLMError("l1 outage"), l2="recovery ответ")
    svc, react, bot, msg, user = _drive(monkeypatch, "бот, ну такое", llm=llm)
    svc._bot_replied_recently = AsyncMock(return_value=True)
    await svc.handle(bot, msg, user)
    svc._send_direct_answer.assert_awaited_once()
    assert svc._send_direct_answer.await_args.args[2] == "recovery ответ"
    react.assert_not_awaited()


# ── 6. Конкретная задача выполняется штатно ─────────────────────────────────

@pytest.mark.asyncio
async def test_concrete_task_still_executes(monkeypatch):
    llm = _FakeLLM(l1=_plan_json(action="reply"), l2="2 + 2 = 4")
    svc, react, bot, msg, user = _drive(monkeypatch, "бот, посчитай 2+2",
                                        llm=llm)
    await svc.handle(bot, msg, user)
    svc._send_direct_answer.assert_awaited_once()
    assert "4" in svc._send_direct_answer.await_args.args[2]
    react.assert_not_awaited()
