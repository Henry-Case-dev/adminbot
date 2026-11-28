"""P0T-REPLY-01 (28.11.2026, owner §190/192) — смысловая цель reply в Direct.

Контракт: цель reply в прямом ответе определяется ФАКТИЧЕСКИМ СМЫСЛОМ ответа,
а не событием, запустившим генерацию. Транспорт не выбирает цель:
* план L1 (source llm/repair) просит `delivery=reply` + `target_message_id` →
  существующая техническая проверка `_validate_plan_target`, привязка к её tg-id;
* осмысленный план без `delivery=reply` → отправка без привязки;
* цель недоступна (нет в БД / чужой чат / устарела / чужой автор) →
  fail-soft обычная отправка БЕЗ перепривязки к триггеру и БЕЗ отмены;
* `l1_plan=None` (L1 OFF) и `source="fallback"` → байт-паритет: reply на
  сообщение-триггер;
* L1-контекст Direct получает `[msg:N]` и для окна, и для P0-сообщений
  (триггер/цитируемое), иначе корректную цель нельзя назвать.

Детерминированно проверяется исполнение ПОДСТАВЛЕННОГО решения, а не
поведение LLM (фактический выбор модели — live-only, BOUNDED ACCEPTANCE).
0 provider-вызовов (fake LLM), 0 реальных сообщений (fake bot), R17 — только
id/коды/длины, тексты не логируются.

TEST-LIFECYCLE: CONTRACT owner=P0T-REPLY-01 (§190/192: цель по смыслу)
TEST-LIFECYCLE: REGRESSION owner=P0T-REPLY-01 (2.58.273: reply всегда на триггер)
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from services import direct_chat_service as dcs
from services import direct_l1 as _l1
from services.database import DatabaseService
from services.llm_client import LLMError


CHAT_ID = -1001234567890
AUDIO_AUTHOR = 411
PHOTO_AUTHOR = 422
TRIGGER_TG = 501
PHOTO_TG = 502
TRIGGER_ROW = 0        # заполняется хелпером (smart_messages.id)
PHOTO_ROW = 0


class _Bot:
    """Записывает фактические kwargs отправки; id доставленного — синтетика."""

    id = 12345

    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": int(chat_id), "text": str(text),
                          **dict(kwargs)})
        return SimpleNamespace(message_id=9000 + len(self.sent))

    async def send_chat_action(self, chat_id, action="typing", **kwargs):
        return True


class _Memory:
    """Минимальный windows-контракт; DB-чтения идут в реальный DatabaseService."""

    def __init__(self, window):
        self.window = list(window)

    async def get_window_messages(self, chat_id):
        return list(self.window)

    async def get_rag_context(self, chat_id, query, *, sort_by_timestamp=False,
                              include_direct_reply=False):
        return ""

    async def get_rag_facts(self, chat_id, query, *,
                            include_direct_reply=False, include_self=False):
        return []

    async def retrieve_fact_candidates(self, chat_id, query, *, limit=None,
                                       include_direct_reply=False,
                                       include_self=False,
                                       include_archived=False):
        return []

    async def rerank_rag_facts(self, query, facts):
        return list(facts)

    async def memorize_facts(self, chat_id, raw_text, source_type,
                             target_user=None, *, tg_message_id=None,
                             forward_from=""):
        return None

    async def memorize_self_reply(self, chat_id, essence):
        return 1


class _LLM:
    """Fake LLM: l1_planner → план (или ошибка), l2_writer → финальный текст."""

    def __init__(self, *, l1=None, l2="ответ по существу", l1_error=None):
        self.l1_reply = l1
        self.l2_text = l2
        self.l1_error = l1_error
        self.calls: list[str] = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append(str(step))
        if step == "l1_planner":
            if self.l1_error is not None:
                raise self.l1_error
            return self.l1_reply
        if step == "l2_writer":
            return self.l2_text
        return self.l2_text


def _plan(**over) -> str:
    data = {"action": "reply", "reaction": None,
            "response_act": "answer", "extent": "auto", "tone": "inherit",
            "emotional_mirroring": "none", "structure": "chat",
            "delivery_hint": "plain", "tool_policy": "none",
            "capabilities_needed": [], "needs_clarification": False,
            "clarification_target": None, "confidence": 0.9}
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


async def _db(tmp_path, name="p0t.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _insert(db, *, tg_id: int, user_id: int, media_type: str = "text",
                  text: str = "сообщение", age_s: int = 30,
                  chat_id: int = CHAT_ID) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (user_id, chat_id, text, int(time.time()) - int(age_s), media_type,
         f"u{user_id}", tg_id))
    await db.db.commit()
    return int(cursor.lastrowid)


async def _window(db) -> list:
    since = int(time.time()) - 86400
    return await db.get_smart_window(CHAT_ID, since, 100)


def _message(text: str, *, tg_id: int, user_id: int):
    from tests.test_direct_chat import _message as base_message, _user
    msg = base_message(text=text, message_id=tg_id, user=_user(user_id=user_id))
    msg.chat = SimpleNamespace(id=CHAT_ID, type="supergroup")
    return msg


async def _run(tmp_path, monkeypatch, *, plan, text="бот, что это за трек?",
               tg_id=TRIGGER_TG, user_id=AUDIO_AUTHOR, answer="ответ",
               l1_error=None, l1_enabled=True):
    """Реальный Direct-ход: fake LLM/бот, реальная БД, реальный `_send_direct_answer`."""
    from tests.test_direct_chat import _make_service
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", l1_enabled)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    db = await _db(tmp_path)
    rows = await _window(db)
    svc = _make_service(memory=_Memory(rows), db=db, llm=_LLM(
        l1=plan, l2=answer, l1_error=l1_error))
    svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc.remember_bot_reply = AsyncMock()
    bot = _Bot()
    msg = _message(text, tg_id=tg_id, user_id=user_id)
    await svc.handle(bot, msg, _user_ref(user_id))
    await db.close()
    return svc, bot, db, msg


def _user_ref(user_id: int):
    from tests.test_direct_chat import _user
    return _user(user_id=user_id)


async def _seed_media_window(tmp_path) -> tuple[DatabaseService, int, int]:
    """Триггер — аудио; в окне обложка и фото ДРУГОГО автора.

    Обложка новее фото: «последнее сообщение окна» ≠ предмет ответа, поэтому
    эвристика «последняя строка окна» обязана отличаться от цели плана."""
    db = await _db(tmp_path)
    audio_row = await _insert(db, tg_id=TRIGGER_TG, user_id=AUDIO_AUTHOR,
                              media_type="audio", text="трек", age_s=60)
    photo_row = await _insert(db, tg_id=PHOTO_TG, user_id=PHOTO_AUTHOR,
                              media_type="photo", text="", age_s=30)
    await _insert(db, tg_id=504, user_id=AUDIO_AUTHOR,
                  media_type="photo", text="обложка", age_s=5)
    return db, audio_row, photo_row


def _reply_of(call: dict):
    return call.get("reply_to_message_id")


# ═══ 1. Окно «аудио + фото»: цель — фото другого автора ═════════════════════

@pytest.mark.asyncio
async def test_plan_target_photo_in_audio_window(tmp_path, monkeypatch):
    db, audio_row, photo_row = await _seed_media_window(tmp_path)
    await db.close()
    plan = _plan(delivery="reply", target_message_id=photo_row)
    _svc, bot, _db2, msg = await _run(tmp_path, monkeypatch, plan=plan,
                                      answer="это обложка альбома, а не трек")
    assert bot.sent, "ответ должен быть доставлен"
    assert _reply_of(bot.sent[0]) == PHOTO_TG
    assert _reply_of(bot.sent[0]) != msg.message_id
    assert all(_reply_of(c) is None for c in bot.sent[1:])


@pytest.mark.asyncio
async def test_plan_target_chunked_reply_only_first_chunk(tmp_path, monkeypatch):
    db, _audio_row, photo_row = await _seed_media_window(tmp_path)
    await db.close()
    plan = _plan(delivery="reply", target_message_id=photo_row)
    long_answer = " ".join(["слово"] * 1600)       # > 4096 символов
    _svc, bot, _db2, _msg = await _run(tmp_path, monkeypatch, plan=plan,
                                       answer=long_answer)
    assert len(bot.sent) > 1, [len(c["text"]) for c in bot.sent]
    assert _reply_of(bot.sent[0]) == PHOTO_TG
    assert all(_reply_of(c) is None for c in bot.sent[1:])


# ═══ 2-3. Осмысленный план без delivery=reply → без привязки ═════════════════

@pytest.mark.asyncio
async def test_delivery_chat_means_no_reply(tmp_path, monkeypatch):
    db, _audio_row, photo_row = await _seed_media_window(tmp_path)
    await db.close()
    plan = _plan(delivery="chat", target_message_id=photo_row,
                 target_user_id=PHOTO_AUTHOR)
    _svc, bot, _db2, _msg = await _run(tmp_path, monkeypatch, plan=plan)
    assert bot.sent and all(_reply_of(c) is None for c in bot.sent)


@pytest.mark.asyncio
async def test_delivery_absent_means_no_reply(tmp_path, monkeypatch):
    db, _audio_row, _photo_row = await _seed_media_window(tmp_path)
    await db.close()
    plan = _plan()                      # поле delivery не пришло вовсе
    _svc, bot, _db2, _msg = await _run(tmp_path, monkeypatch, plan=plan)
    assert bot.sent and all(_reply_of(c) is None for c in bot.sent)


# ═══ 4-6. Недоступная цель → plain send (НЕ триггер), причина в логе ════════

@pytest.mark.asyncio
async def test_missing_target_is_plain_send_not_trigger(tmp_path, monkeypatch,
                                                       caplog):
    db, _audio_row, _photo_row = await _seed_media_window(tmp_path)
    await db.close()
    plan = _plan(delivery="reply", target_message_id=999999)
    with caplog.at_level("INFO", logger=dcs.logger.name):
        _svc, bot, _db2, msg = await _run(tmp_path, monkeypatch, plan=plan)
    assert bot.sent, "молчание на прямое обращение запрещено"
    assert all(_reply_of(c) is None for c in bot.sent)
    assert all(_reply_of(c) != msg.message_id for c in bot.sent)
    assert any("reply target unavailable" in r.message
               and "target_missing" in r.message for r in caplog.records), \
        [r.message for r in caplog.records if "reply target" in r.message]


@pytest.mark.asyncio
async def test_foreign_chat_target_is_plain_send(tmp_path, monkeypatch):
    db, _audio_row, _photo_row = await _seed_media_window(tmp_path)
    foreign = await _insert(db, tg_id=777, user_id=PHOTO_AUTHOR,
                            media_type="photo", chat_id=-555)
    await db.close()
    plan = _plan(delivery="reply", target_message_id=foreign)
    _svc, bot, _db2, _msg = await _run(tmp_path, monkeypatch, plan=plan)
    assert bot.sent and all(_reply_of(c) is None for c in bot.sent)


@pytest.mark.asyncio
async def test_stale_target_is_plain_send(tmp_path, monkeypatch):
    db, _audio_row, _photo_row = await _seed_media_window(tmp_path)
    stale = await _insert(db, tg_id=888, user_id=PHOTO_AUTHOR,
                          media_type="photo", age_s=10 * 86400)
    await db.close()
    from services import hot_config as hot
    window_hours = float(hot.get("limits.summary_window_hours",
                                 Settings.SUMMARY_WINDOW_HOURS) or 0)
    assert 10 * 24 > window_hours, window_hours
    plan = _plan(delivery="reply", target_message_id=stale)
    _svc, bot, _db2, _msg = await _run(tmp_path, monkeypatch, plan=plan)
    assert bot.sent and all(_reply_of(c) is None for c in bot.sent)


@pytest.mark.asyncio
async def test_addressee_mismatch_is_plain_send(tmp_path, monkeypatch):
    db, _audio_row, photo_row = await _seed_media_window(tmp_path)
    await db.close()
    # цель — сообщение PHOTO_AUTHOR, а план называет адресатом AUDIO_AUTHOR
    plan = _plan(delivery="reply", target_message_id=photo_row,
                 target_user_id=AUDIO_AUTHOR)
    _svc, bot, _db2, msg = await _run(tmp_path, monkeypatch, plan=plan)
    assert bot.sent and all(_reply_of(c) is None for c in bot.sent)
    assert all(_reply_of(c) != msg.message_id for c in bot.sent)


# ═══ 7. Цель — сам триггер: сохранённая корректная возможность ═══════════════

@pytest.mark.asyncio
async def test_plan_target_trigger_is_honoured(tmp_path, monkeypatch):
    db, audio_row, _photo_row = await _seed_media_window(tmp_path)
    await db.close()
    plan = _plan(delivery="reply", target_message_id=audio_row,
                 target_user_id=AUDIO_AUTHOR)
    _svc, bot, _db2, msg = await _run(tmp_path, monkeypatch, plan=plan)
    assert bot.sent
    assert _reply_of(bot.sent[0]) == msg.message_id == TRIGGER_TG


# ═══ 8. fallback / L1 OFF — байт-паритет: reply на триггер ══════════════════

@pytest.mark.asyncio
async def test_fallback_plan_keeps_trigger_reply(tmp_path, monkeypatch):
    db, _a, _p = await _seed_media_window(tmp_path)
    await db.close()
    _svc, bot, _db2, msg = await _run(
        tmp_path, monkeypatch, plan=None,
        l1_error=LLMError("planner down"))
    assert bot.sent
    assert _reply_of(bot.sent[0]) == msg.message_id


@pytest.mark.asyncio
async def test_l1_off_keeps_trigger_reply(tmp_path, monkeypatch):
    db, _a, _p = await _seed_media_window(tmp_path)
    await db.close()
    _svc, bot, _db2, msg = await _run(
        tmp_path, monkeypatch, plan=None, l1_enabled=False)
    assert bot.sent
    assert _reply_of(bot.sent[0]) == msg.message_id


# ═══ 9. L1-контекст: [msg:id] у окна и у P0-сообщений ═══════════════════════

def test_direct_l1_context_marks_window_and_p0_ids():
    audio_row = {"id": 11, "tg_message_id": TRIGGER_TG, "user_id": AUDIO_AUTHOR,
                 "author_name": "audio", "text": "трек", "timestamp": 100,
                 "media_type": "audio", "reply_to_id": None}
    photo_row = {"id": 12, "tg_message_id": PHOTO_TG, "user_id": PHOTO_AUTHOR,
                 "author_name": "photo", "text": "фото", "timestamp": 110,
                 "media_type": "photo", "reply_to_id": None}
    reply_row = {"id": 13, "tg_message_id": 503, "user_id": PHOTO_AUTHOR,
                 "author_name": "photo", "text": "про что?", "timestamp": 90,
                 "media_type": "text", "reply_to_id": None}
    text = _l1.build_l1_context(
        query="а это что?", current_question="а это что?",
        reply_block="photo: про что?",
        window=[audio_row, photo_row, reply_row],
        trigger_message_id=TRIGGER_TG, reply_to_message_id=503,
        with_ids=True, preallocated=False, budget_tokens=4000,
        history_partial=False)
    # окно размечено тем же диалектом
    assert f"[msg:{photo_row['id']}]" in text
    # P0-сообщения исключены из окна, но их id назван в их секциях
    assert f"[msg:{audio_row['id']}]" in text
    assert f"[msg:{reply_row['id']}]" in text
    message_section = text.split("[СООБЩЕНИЕ]", 1)[1].split("\n\n", 1)[0]
    assert f"[msg:{audio_row['id']}]" in message_section
    reply_section = text.split(f"[{_l1.L1_REPLY_SECTION}]", 1)[1]
    assert f"[msg:{reply_row['id']}]" in reply_section.split("\n\n", 1)[0]


def test_direct_l1_context_without_ids_has_no_msg_markup():
    """Паритет прежнего формата: with_ids=False не добавляет [msg:N]."""
    row = {"id": 11, "tg_message_id": TRIGGER_TG, "user_id": AUDIO_AUTHOR,
           "author_name": "audio", "text": "трек", "timestamp": 100,
           "media_type": "audio", "reply_to_id": None}
    text = _l1.build_l1_context(
        query="вопрос", current_question="вопрос", window=[row],
        trigger_message_id=TRIGGER_TG, with_ids=False, preallocated=False,
        budget_tokens=4000)
    assert "[msg:" not in text


def test_initiative_context_keeps_no_p0_prefix():
    """Инициатива не передаёт P0-id → секция СООБЩЕНИЕ байт-паритетна."""
    row = {"id": 11, "tg_message_id": TRIGGER_TG, "user_id": AUDIO_AUTHOR,
           "author_name": "audio", "text": "трек", "timestamp": 100,
           "media_type": "audio", "reply_to_id": None}
    text = _l1.build_l1_context(
        query="повод наблюдателя", window=[row], with_ids=True,
        preallocated=False, budget_tokens=4000)
    message_section = text.split("[СООБЩЕНИЕ]", 1)[1].split("\n\n", 1)[0]
    assert message_section.strip() == "повод наблюдателя"


# ═══ предикат «план — решение модели» ══════════════════════════════════════

def test_plan_delivery_is_semantic_only_model_decisions():
    def plan(source):
        return _l1.L1Plan(action="reply", source=source)

    assert _l1.plan_delivery_is_semantic(plan("llm")) is True
    assert _l1.plan_delivery_is_semantic(plan("repair")) is True
    assert _l1.plan_delivery_is_semantic(plan("fallback")) is False
    assert _l1.plan_delivery_is_semantic(plan("")) is False
    assert _l1.plan_delivery_is_semantic(plan("garbage")) is False
    assert _l1.plan_delivery_is_semantic(None) is False
