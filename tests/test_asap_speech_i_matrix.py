# -*- coding: utf-8 -*-
"""INIT-LIVE (source-2026-10-22 §7) — property/regression матрица инициативы.

Покрывает машинно-проверяемые части I-01…I-09 без provider-вызовов:
  * I-01/I-04: форма участия (chat/reply/react/silent) — ТОЛЬКО из плана L1,
    транспорт не приклеивает текст к последнему сообщению;
  * I-02: reply-привязка идёт ровно к выбранному L1 target_message_id;
  * I-03/I-09: react/silent не превращаются в текст; невалидная реакция —
    честное молчание (без подмены);
  * I-05/I-06: удалённая/чужая цель — техническая проверка, без произвольной
    перепривязки и без отправки в другой чат;
  * I-07: L1 получает собственные недавние ответы бота (bot_replies);
  * I-08: хрупкий JSON (нет delivery, мусорный target, невалидный action) —
    fail-closed: reply-привязки не возникает.

TEST-LIFECYCLE: CONTRACT owner=INIT-LIVE/I-01..I-09 (форма участия из плана)
TEST-LIFECYCLE: REGRESSION owner=INIT-LIVE/I-05,I-06 (нет перепривязки цели)
TEST-LIFECYCLE: REGRESSION owner=INIT-LIVE/I-08 (fail-closed parser)
TEST-LIFECYCLE: REGRESSION owner=SPEECH-INIT-FIX/R3 (адресат↔цель, react-target,
bot_replies-окно инициативы)
"""
from __future__ import annotations

import time

import pytest

from services import direct_l1 as _l1
from services import mca_expression as _expr
from services import mca_intents as mi
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService, handle_initiative
from services.direct_l1 import L1Plan

CHAT = -4401
FOREIGN_CHAT = -4499
USER = 99001
OTHER = 99002
BOT = 42


class _FakeBot:
    def __init__(self):
        self.id = BOT
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), str(text), dict(kwargs)))

        class _Msg:
            message_id = 5000 + len(self.sent)

        return _Msg()


class _FakeWriter:
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


async def _message(db, *, chat_id=CHAT, tg_id: int, user_id: int = USER,
                   age_s: int = 300, text: str = "реплика") -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, ?, 'text', 'addr', 0, ?)",
        (user_id, chat_id, text, int(time.time()) - int(age_s), tg_id))
    await db.db.commit()
    return cursor.lastrowid


async def _run(tmp_path, name, *, plan, db=None, messages=None) -> tuple:
    sent: list = []
    reacts: list = []

    async def _send(bot, chat_id, text, **kwargs):
        sent.append({"chat_id": int(chat_id), "text": str(text),
                     "kwargs": dict(kwargs)})

        class _Msg:
            message_id = 7000 + len(sent)

        return _Msg()

    async def _react(bot, chat_id, message_id, *, reaction=None,
                     reason_code=None):
        reacts.append((chat_id, message_id, reaction))
        return "ok"

    import services.telegram_send as ts
    orig_send = ts.send_text
    import services.direct_chat_service as dcs
    orig_react = dcs.react_moai
    ts.send_text = _send
    dcs.react_moai = _react
    try:
        db = db or await _db(tmp_path, name)
        result = await handle_initiative(
            bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
            candidates=[_candidate()], db=db, writer_service=_FakeWriter(plan),
            correlation_id="corr-%s" % name,
            opportunity_row={
                "goal": "проверка формы участия", "kind": "topic_interest",
                "origin": "observer", "created_at": int(time.time()),
                "addressee_user_id": None})
        return result, sent, reacts, db
    finally:
        ts.send_text = orig_send
        dcs.react_moai = orig_react


# ═══ I-01/I-03/I-04/I-09: форма участия определяется ТОЛЬКО планом ═══════════

@pytest.mark.asyncio
@pytest.mark.parametrize("plan_kwargs,status,text_sent", [
    # I-01/I-04: план выбрал чат — обычное сообщение, без reply
    ({"action": "reply", "delivery": "chat"}, "sent", True),
    ({"action": "reply", "delivery": ""}, "sent", True),
    # I-03: молчание — полноценный исход
    ({"action": "silent"}, "silent", False),
    # I-09: реакция — без текста
    ({"action": "react", "reaction": "😂"}, "reacted", False),
])
async def test_i01_i04_i03_i09_plan_drives_form(tmp_path, plan_kwargs,
                                                status, text_sent):
    """Ни одна форма не «вшита»: один и тот же вход, разные планы → разные
    исходы. Для react нужна валидная цель — добавляем её в план тестом."""
    plan = L1Plan(confidence=0.9, confidence_bucket="high", source="llm",
                  **plan_kwargs)
    db = await _db(tmp_path, "form-%s.db" % status)
    row = await _message(db, tg_id=660001)
    if plan.action == "react":
        plan.target_message_id = row
    result, sent, reacts, _ = await _run(
        tmp_path, "form-%s" % status, plan=plan, db=db)
    assert result["status"] == status
    assert bool(sent) is text_sent
    if text_sent:
        assert "reply_to_message_id" not in sent[0]["kwargs"]
    if status == "reacted":
        assert reacts and reacts[0][1] == 660001
    await db.close()


@pytest.mark.asyncio
async def test_i02_reply_binds_exact_l1_target(tmp_path):
    """I-02: reply идёт ровно на выбранный L1 [msg:N], не на последнее."""
    db = await _db(tmp_path, "i02.db")
    older = await _message(db, tg_id=660010, text="первый тезис")
    newest = await _message(db, tg_id=660011, text="последняя реплика")
    plan = L1Plan(action="reply", delivery="reply",
                  target_message_id=older, confidence=0.9,
                  confidence_bucket="high", source="llm")
    result, sent, _, _ = await _run(tmp_path, "i02", plan=plan, db=db)
    assert result["status"] == "sent"
    assert sent and sent[0]["kwargs"].get("reply_to_message_id") == 660010
    assert newest != older
    await db.close()


# ═══ I-05/I-06: цель исчезла / чужая — без перепривязки ══════════════════════

@pytest.mark.asyncio
async def test_i05_deleted_target_cancels_for_semantic_addressee(tmp_path):
    db = await _db(tmp_path, "i05.db")
    row = await _message(db, tg_id=660020, user_id=USER)
    await db.db.execute("DELETE FROM smart_messages WHERE id=?", (row,))
    await db.db.commit()
    plan = L1Plan(action="reply", delivery="reply", target_message_id=row,
                  target_user_id=USER, confidence=0.9,
                  confidence_bucket="high", source="llm")
    result, sent, _, _ = await _run(tmp_path, "i05", plan=plan, db=db)
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "target_missing"
    assert sent == []          # «тот же текст в общий чат» не уходит
    await db.close()


@pytest.mark.asyncio
async def test_i05_deleted_target_standalone_failsoft_no_rebinding(tmp_path):
    """Текст самостоятелен (адресата в плане нет) — ровно одна обычная
    отправка, НЕ на другую цель."""
    db = await _db(tmp_path, "i05b.db")
    row = await _message(db, tg_id=660021)
    await _message(db, tg_id=660022)      # более свежая цель — не выбирать
    await db.db.execute("DELETE FROM smart_messages WHERE id=?", (row,))
    await db.db.commit()
    plan = L1Plan(action="reply", delivery="reply", target_message_id=row,
                  confidence=0.9, confidence_bucket="high", source="llm")
    result, sent, _, _ = await _run(tmp_path, "i05b", plan=plan, db=db)
    assert result["status"] == "sent"
    assert len(sent) == 1
    assert "reply_to_message_id" not in sent[0]["kwargs"]
    await db.close()


@pytest.mark.asyncio
async def test_i06_foreign_chat_target_never_used(tmp_path):
    """I-06: target из ДРУГОГО чата отклоняется; сообщение не уходит ни туда,
    ни как reply здесь."""
    db = await _db(tmp_path, "i06.db")
    foreign = await _message(db, chat_id=FOREIGN_CHAT, tg_id=660030,
                             text="чужой чат")
    plan = L1Plan(action="reply", delivery="reply",
                  target_message_id=foreign, target_user_id=USER,
                  confidence=0.9, confidence_bucket="high", source="llm")
    result, sent, _, _ = await _run(tmp_path, "i06", plan=plan, db=db)
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "target_missing"
    assert all(s["chat_id"] == CHAT for s in sent)
    assert sent == []
    await db.close()


@pytest.mark.asyncio
async def test_i02_addressee_mismatch_never_bound(tmp_path):
    """I-02/R3: текст адресован USER, а цель — сообщение OTHER →
    техническая проверка отклоняет привязку (без перепривязки на другое)."""
    db = await _db(tmp_path, "i02-mismatch.db")
    other_row = await _message(db, tg_id=660012, user_id=OTHER,
                               text="чужая реплика")
    plan = L1Plan(action="reply", delivery="reply",
                  target_message_id=other_row, target_user_id=USER,
                  confidence=0.9, confidence_bucket="high", source="llm")
    result, sent, _, _ = await _run(tmp_path, "i02m", plan=plan, db=db)
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "target_addressee_mismatch"
    assert sent == []
    await db.close()


@pytest.mark.asyncio
async def test_i09_react_without_target_is_honest_silence(tmp_path):
    """I-09/R3: реакция без target_message_id НЕ исполняется и не
    подменяется текстом (grace); канон требует цель для реакции."""
    db = await _db(tmp_path, "i09-no-target.db")
    await _message(db, tg_id=660013)
    plan = L1Plan(action="react", reaction="😂", confidence=0.9,
                  confidence_bucket="high", source="llm")
    result, sent, reacts, _ = await _run(tmp_path, "i09n", plan=plan, db=db)
    assert result["status"] == "silent"
    assert result["reason_code"] == "l1_react"
    assert sent == [] and reacts == []
    canon = " ".join(
        __import__("services.chat_prompts", fromlist=["x"])
        .DIRECT_L1_PLANNER_SYSTEM_PROMPT.split())
    assert ("Для реакции укажи target_message_id сообщения, на которое "
            "ставится реакция") in canon
    await db.close()


# ═══ I-07: L1 видит собственные ответы; молчание допустимо ═══════════════════

@pytest.mark.asyncio
async def test_i07_recent_bot_replies_reach_l1_context(tmp_path):
    db = await _db(tmp_path, "i07.db")
    await db.db.execute(
        "INSERT OR REPLACE INTO bot_replies (chat_id, tg_message_id, text,"
        " last_used_at) VALUES (?,?,?,?)",
        (CHAT, 777001, "Читаю, но отвечаю, когда есть что сказать.",
         time.time() - 60))
    await db.db.commit()
    texts = await DirectChatService._recent_bot_replies(
        type("_S", (), {"db": db})(), CHAT)
    assert texts == ("Читаю, но отвечаю, когда есть что сказать.",)
    context = _l1.build_l1_context(
        query="повод", window=[{"id": 1, "user_id": USER,
                                "author_name": "Гоша", "text": "ну?"}],
        bot_replies=texts, with_ids=True)
    assert _l1.BOT_REPLIES_SECTION in context
    assert "Читаю, но отвечаю" in context
    assert "[msg:1]" in context
    # «может промолчать» — равноправие форм в каноне инициативы
    assert "промолчать" in _l1.INITIATIVE_LINE
    assert "никакая форма не имеет приоритета" in _l1.INITIATIVE_LINE
    # R3: reply только к сообщению смыслового адресата
    assert "reply уместен только к сообщению" in _l1.INITIATIVE_LINE
    await db.close()


@pytest.mark.asyncio
async def test_i07_bot_reply_older_than_600s_reaches_initiative_l1(
        tmp_path, monkeypatch):
    """I-07/R3 (RED на 2.58.113): ответ бота старше 600 с (10 мин) не
    попадал в L1, потому что окно bot_replies было окном анти-спама Direct.
    Инициатива обязана видеть свои ответы в окне своего контекста
    (limits.summary_window_hours); Direct-дефолт не меняется."""
    from services import direct_chat_service as dcs
    db = await _db(tmp_path, "i07-wide.db")
    await db.db.execute(
        "INSERT OR REPLACE INTO bot_replies (chat_id, tg_message_id, text,"
        " last_used_at) VALUES (?,?,?,?)",
        (CHAT, 777002, "Я уже отвечал на это.", time.time() - 1200))
    await db.db.commit()
    fake = type("_S", (), {"db": db})()

    class _Mem:
        async def get_window_messages(self, chat_id):
            return [{"id": 5, "user_id": USER, "author_name": "Гоша",
                     "text": "бот читает?"}]

    class _Llm:
        captured = []

        async def generate(self, messages, **kwargs):
            _Llm.captured.append(messages)
            raise RuntimeError("stop-after-context")

    svc = DirectChatService.__new__(DirectChatService)
    svc.memory = _Mem()
    svc.llm = _Llm()
    svc.db = db

    async def _persona(_chat_id):
        return ""

    monkeypatch.setattr(dcs.DirectChatService, "_initiative_persona_block",
                        lambda self, chat_id: _persona(chat_id))
    monkeypatch.setattr(dcs, "reaction_mechanics_enabled",
                        lambda: False)

    await dcs.DirectChatService.plan_initiative_decision(
        svc, CHAT, {"goal": "уточнить статус", "kind": "follow_up"})
    user_msg = _Llm.captured[0][-1]["content"]
    assert _l1.BOT_REPLIES_SECTION in user_msg
    assert "Я уже отвечал на это." in user_msg
    # Direct-дефолт (без параметра) остаётся прежним 600-секундным окном
    direct_texts = await DirectChatService._recent_bot_replies(fake, CHAT)
    assert direct_texts == ()
    await db.close()


# ═══ I-08: хрупкий parser — fail-closed для reply ════════════════════════════

@pytest.mark.parametrize("raw,action,delivery,target,binding", [
    ('{"action":"reply","delivery":"reply","target_message_id":12}',
     "reply", "reply", 12, True),
    ('{"action":"reply","delivery":"reply","target_message_id":"abc"}',
     "reply", "reply", None, False),
    ('{"action":"reply","delivery":"reply","target_message_id":true}',
     "reply", "reply", None, False),
    ('{"action":"reply","delivery":"reply","target_message_id":-7}',
     "reply", "reply", None, False),
    ('{"action":"reply","delivery":"reply"}',
     "reply", "reply", None, False),
    ('{"action":"reply"}', "reply", "", None, False),
    ('{"action":"reply","delivery":"telepathy","target_message_id":5}',
     "reply", "", 5, False),
    ('{"action":"answer","delivery":"reply","target_message_id":5}',
     None, None, None, False),
    ('not json at all', None, None, None, False),
])
def test_i08_parser_fail_closed_for_reply(raw, action, delivery, target,
                                          binding):
    plan = _l1.parse_l1_plan(raw)
    if action is None:
        assert plan is None       # невалидный action → bounded repair/None
        return
    assert plan.action == action
    assert plan.delivery == delivery
    assert plan.target_message_id == target
    # единственная комбинация, включающая Telegram-reply, — точная и полная
    assert _l1.reply_binding_requested(plan) is binding


# ═══ EVAL-MODES / P0D: режим — из конфигурации, не из содержимого ═══════════

_MODE_MARKERS = {
    "off": "Не используй мат в собственной речи.",
    "occasional": "Матерись иногда",
    "frequent": "Матерись часто",
}


@pytest.mark.parametrize("mode", ["off", "occasional", "frequent"])
def test_eval_modes_assembly_has_exactly_one_branch(mode):
    """Каждая сборка слоя несёт РОВНО одну ветку режима, не все три."""
    settings = _expr.build_expression_settings(None, {"profanity": mode})
    text = settings.text
    assert settings.mode == mode
    present = [m for m, marker in _MODE_MARKERS.items() if marker in text]
    assert present == [mode]
    assert text.count("<Expression_Settings>") == 1


def test_p0d_quoted_content_does_not_change_mode():
    """P0D-QUOTED: содержимое (цитата/RAG/примеры) не выбирает режим.

    `resolve_effective` принимает ТОЛЬКО документы конфигурации; любой
    контент-документ (note/посторонние ключи) режим не переключает.
    """
    noisy = {"profanity": "off",
             "note": "«да вы все охуели с такими ценами» — цитата из чата",
             "quoted_source": "мат в чужой речи", "rag": "пример с матом"}
    effective = _expr.resolve_effective(None, noisy)
    assert effective["controls"]["profanity"]["value"] == "off"
    text = _expr.render_expression_text(effective)
    assert _MODE_MARKERS["off"] in text
    assert _MODE_MARKERS["occasional"] not in text
    assert _MODE_MARKERS["frequent"] not in text
    # примеры в режиме off сохраняют режим off (не переключают слой)
    rows = [{"context_note": "цитата", "input_text": "он сказал: охуели",
             "reply_text": "бывает"}]
    block = _expr.render_expression_examples_block("off", rows)
    assert block.startswith('<Expression_Examples mode="off">')
    assert "mode=\"occasional\"" not in block
