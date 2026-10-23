"""Телеметрия доставки инициативы (аудит 24.10.2026, G1–G7).

Покрытие:
* G1 решение несёт выбранную L1 форму (`delivery:chat|reply`), `tgt:`,
  `tgt_user:`, `addr:` и `corr:` + `trace_id` (связка решение ↔ доставка);
* G2 `status` = `action.delivery_kind`: реакция больше не выглядит как reply,
  старые записи без `.` читаются как прежде;
* G3 манифест доставки несёт `reply:`, `delivery:`, `form:` и наконец
  заполненный (R17-safe) `config_version`;
* G4 ledger-строка инициативы несёт фактический `parent_message_ref`;
* G5 причины привязки `target_*` переживают whitelist `reason_code`;
* G6 скалярный `entity_id` (correlation Observer) не теряется при вставке;
* G7 фактическая форма доставки — в существующем событии доставки, плюс
  причина расхождения «выбрано reply → отправлено chat»;
* R17: в payload нет текста сообщений; новых колонок/таблиц нет.

TEST-LIFECYCLE: REGRESSION owner=INIT-DELIVERY-TELEMETRY/G1-G7
"""
from __future__ import annotations

import json
import time

import pytest

from services import initiative_diagnostics as diag
from services import mca_events
from services.database import DatabaseService

CHAT = -777001
CHAT_L1D = -3301
USER_L1D = 777
SECRET_TEXT = "секретный текст инициативы который не должен попасть в события"


class _Decision:
    def __init__(self, action="reply", intent_id="intent-1",
                 trigger_kind="new_message", reason_code="default"):
        self.action = action
        self.intent_id = intent_id
        self.trigger_kind = trigger_kind
        self.reason_code = reason_code


class _FakeBot:
    def __init__(self):
        self.id = 42


class _FakeWriter:
    def __init__(self, plan):
        self.plan = plan
        self.text = "Ответ по существу, без разметки."

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        return self.plan

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        return self.text


@pytest.fixture(autouse=True)
def _clean():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


async def _db(tmp_path, name="init_tel.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _rows(db, name):
    cursor = await db.db.execute(
        "SELECT * FROM mca_events WHERE event_name = ? ORDER BY id", (name,))
    return [dict(r) for r in await cursor.fetchall()]


def _tokens(row) -> list[str]:
    return json.loads(row.get("entity_ids") or "[]")


# ═══ G1/G2: решение несёт выбранную форму, реакция ≠ reply ══════════════════

@pytest.mark.asyncio
async def test_decision_event_carries_chosen_form_targets_and_correlation(
        tmp_path):
    db = await _db(tmp_path)
    try:
        from services import mca_intents as mi
        mi.note_decision(
            _Decision(), chat_id=CHAT, outcome="ok", action="reply",
            delivery="reply", delivery_kind="text",
            target_message_id=4242, target_user_id=555,
            addressee_user_id=556, correlation_id="c0ffee1234567890")
        await mca_events.flush_events(db)
        row = (await _rows(db, "initiative_decided"))[-1]
        tokens = _tokens(row)
        assert "delivery:reply" in tokens
        assert "tgt:4242" in tokens
        assert "tgt_user:555" in tokens
        assert "addr:556" in tokens
        assert "corr:c0ffee1234567890" in tokens
        assert "intent:intent-1" in tokens
        assert row["trace_id"] == "c0ffee1234567890"
        assert row["status"] == "reply.text"
        assert row["outcome"] == "success"
        assert SECRET_TEXT not in str(row)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_react_decision_status_is_not_reply(tmp_path):
    db = await _db(tmp_path)
    try:
        from services import mca_intents as mi
        mi.note_decision(
            _Decision(action="react"), chat_id=CHAT, outcome="silent",
            reason_code="target_missing", action="react", delivery="react",
            delivery_kind="react", target_message_id=99,
            correlation_id="abc123")
        await mca_events.flush_events(db)
        row = (await _rows(db, "initiative_decided"))[-1]
        action, kind = diag._split_decision_status(row["status"])
        assert (action, kind) == ("react", "react")
        assert action != "reply"
        assert row["outcome"] == "silent"
        # G5: причина привязки не выброшена whitelist'ом
        assert row["reason_code"] == "target_missing"
        assert "delivery:react" in _tokens(row)
    finally:
        await db.close()


def test_target_reason_codes_survive_contract():
    for code in ("target_invalid", "target_missing", "target_no_tg_id",
                 "target_stale", "target_addressee_mismatch",
                 "target_unavailable", "target_gone"):
        event = mca_events.build_event("initiative_decided", outcome="cancelled",
                                       reason_code=code)
        assert event is not None
        assert event.get("reason_code") == code, code


# ═══ G3/G7: манифест доставки — фактическая форма, reply_to, config_version ═

@pytest.mark.asyncio
async def test_delivery_manifest_has_actual_form_reply_and_config_version(
        tmp_path):
    db = await _db(tmp_path)
    try:
        from services import mca_intents as mi
        mi.note_delivery_manifest(
            chat_id=CHAT, correlation_id="corr-9", message_id=777,
            core_revision="r7.abc123", style_policy_revision="r2.def456",
            identity_revision="i3.ghi789", manifest_id="m4.jkl000",
            composer_state="on", reply_to=321, delivery="reply",
            delivery_form="reply", mismatch="")
        await mca_events.flush_events(db)
        row = (await _rows(db, "initiative_delivery_manifest"))[-1]
        tokens = _tokens(row)
        assert "reply:321" in tokens
        assert "delivery:reply" in tokens
        assert "form:reply" in tokens
        assert "mismatch:none" in tokens
        # G3: config_version РАНЬШЕ уходил пустым (`=`/`;` и >64 символов
        # резались R17-валидатором code-поля)
        version = str(row["config_version"] or "")
        assert version, "config_version обязан сохраняться"
        assert len(version) <= 64
        assert "=" not in version and ";" not in version
        parsed = diag._parse_manifest_version(version)
        assert parsed["core_revision"] == "r7.abc12"   # компактная сводка
        assert parsed["style_policy_revision"] == "r2.def45"
        assert parsed["manifest_id"] == "m4.jkl00"
        assert parsed["composer"] == "on"
        # полные ревизии — в токенах (компактный формат их не режет)
        assert "core:r7.abc123" in tokens
        assert "manifest:m4.jkl000" in tokens
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delivery_manifest_records_mismatch_reason(tmp_path):
    db = await _db(tmp_path)
    try:
        from services import mca_intents as mi
        mi.note_delivery_manifest(
            chat_id=CHAT, correlation_id="corr-10", message_id=778,
            delivery="reply", delivery_form="chat",
            mismatch="target_missing")
        await mca_events.flush_events(db)
        row = (await _rows(db, "initiative_delivery_manifest"))[-1]
        tokens = _tokens(row)
        assert "delivery:reply" in tokens
        assert "form:chat" in tokens
        assert "mismatch:target_missing" in tokens
        assert "reply:-" in tokens
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_react_delivery_event_records_actual_form(tmp_path):
    db = await _db(tmp_path)
    try:
        from services import mca_intents as mi
        mi.note_delivery_manifest(
            chat_id=CHAT, correlation_id="corr-react", message_id=None,
            reply_to=654, delivery="react", delivery_form="react")
        await mca_events.flush_events(db)
        row = (await _rows(db, "initiative_delivery_manifest"))[-1]
        tokens = _tokens(row)
        assert "form:react" in tokens
        assert "reply:654" in tokens
        assert "msg:-" in tokens
    finally:
        await db.close()


# ═══ G6: correlation Observer-события не теряется без DDL ═══════════════════

@pytest.mark.asyncio
async def test_scalar_entity_id_is_persisted_as_correlation(tmp_path):
    db = await _db(tmp_path)
    try:
        mca_events.emit_mca_event("initiative_sent", outcome="success",
                                  component="initiative",
                                  stage="observer:humor", chat_id=CHAT,
                                  entity_id="a1b2c3d4e5f60718")
        await mca_events.flush_events(db)
        row = (await _rows(db, "initiative_sent"))[-1]
        assert row["trace_id"] == "a1b2c3d4e5f60718"
    finally:
        await db.close()


# ═══ Обратная совместимость: старые события читаются как раньше ═════════════

@pytest.mark.asyncio
async def test_legacy_events_still_readable(tmp_path):
    db = await _db(tmp_path)
    try:
        old = int(time.time())
        await db.db.execute(
            "INSERT INTO mca_events (ts, level, event_name, outcome, chat_id, "
            "stage, reason_code, status, entity_ids, config_version) "
            "VALUES (?, 'INFO', 'initiative_decided', 'silent', ?, "
            "'new_message', 'l1_react', 'reply', '[\"intent:old\"]', NULL)",
            (old, CHAT))
        await db.db.commit()
        action, kind = diag._split_decision_status("reply")
        assert (action, kind) == ("reply", "")
        counts = await diag._action_counts(db, old - 60, CHAT)
        assert counts["other"] == 1 and counts["react"] == 0
        rows = await diag._decision_rows(db, old - 60, CHAT)
        assert rows[-1]["action"] == "reply"
        assert rows[-1]["delivery_kind"] == ""
        assert rows[-1]["intent_id"] == "old"
        # старый формат config_version тоже парсится
        legacy = diag._parse_manifest_version(
            "core=abc123;style=def456;identity=iii789;manifest=mmm000;"
            "composer=on")
        assert legacy["core_revision"] == "abc123"
        assert legacy["composer"] == "on"
        # старый манифест без токенов form/reply читается честно пустым
        refs = await diag._manifest_refs(db, old - 60, CHAT)
        assert refs == {}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_decision_reader_exposes_new_signals(tmp_path):
    db = await _db(tmp_path)
    try:
        from services import mca_intents as mi
        mi.note_decision(
            _Decision(), chat_id=CHAT, outcome="ok", action="reply",
            delivery="chat", delivery_kind="text", target_message_id=11,
            target_user_id=22, addressee_user_id=33,
            correlation_id="beef1234")
        await mca_events.flush_events(db)
        rows = await diag._decision_rows(db, diag._now() - 300, CHAT)
        row = rows[-1]
        assert row["action"] == "reply" and row["delivery_kind"] == "text"
        assert row["delivery"] == "chat"
        assert row["target_message_id"] == "11"
        assert row["target_user_id"] == "22"
        assert row["addressee_user_id"] == "33"
        assert row["correlation_id"] == "beef1234"
        assert SECRET_TEXT not in json.dumps(row, ensure_ascii=False)
    finally:
        await db.close()


# ═══ G4/G7 интеграция: фактическая форма и reply_to в ledger/событиях ═══════

def _situation_l1d():
    from services import mca_intents as mi
    return mi.InitiativeSituation(
        trigger_kind="intent_due", chat_id=CHAT_L1D, direct_pending=False,
        same_event_pending=False, sensitive_moment=False, relations_ok=True,
        bot_replied_recently=False, reply_needed=False, topic_open=True,
        open_intent_ids=None, requested_source="observer")


def _candidate_l1d():
    from services import mca_intents as mi
    return mi.candidate_from_trigger(
        trigger_kind="intent_due", chat_id=CHAT_L1D, reason_code="default")


async def _msg(db, *, tg_id, age_s=600):
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, 'x', ?, 'text', 'addr', 0, ?)",
        (USER_L1D, CHAT_L1D, int(time.time()) - int(age_s), tg_id))
    await db.db.commit()
    return cursor.lastrowid


async def _run_send(db, monkeypatch, *, plan, row_id, correlation):
    from services import initiative_observer as obs
    from services.direct_chat_service import handle_initiative
    calls: list = []

    async def _send(bot, chat_id, text, **kwargs):
        calls.append(dict(kwargs))

        class _Msg:
            message_id = 9001 + len(calls)

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _send)
    opportunity = obs.build_opportunity_row(
        CHAT_L1D, kind="topic_interest", goal="ответить человеку",
        fallback="dispute", rows=[{"id": row_id}], now=int(time.time()),
        addressee_user_id=None)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT_L1D, situation=_situation_l1d(),
        candidates=[_candidate_l1d()], db=db,
        writer_service=_FakeWriter(plan), correlation_id=correlation,
        opportunity_row=opportunity)
    return result, calls


@pytest.mark.asyncio
async def test_send_records_actual_reply_form_and_ledger_parent(
        tmp_path, monkeypatch):
    from services.direct_l1 import L1Plan
    db = await _db(tmp_path, "g4_reply.db")
    row_id = await _msg(db, tg_id=555003)
    result, calls = await _run_send(
        db, monkeypatch,
        plan=L1Plan(action="reply", delivery="reply",
                    target_message_id=row_id, confidence=0.9,
                    confidence_bucket="high", source="llm"),
        row_id=row_id, correlation="corr-g4-reply")
    try:
        assert result["status"] == "sent"
        assert calls[0].get("reply_to_message_id") == 555003
        cursor = await db.db.execute(
            "SELECT parent_message_ref FROM mca_bot_outputs "
            "WHERE source_feature = 'mca09_intents'")
        refs = [r[0] for r in await cursor.fetchall()]
        assert refs == ["tg:555003"]
        await mca_events.flush_events(db)
        manifest = (await _rows(db, "initiative_delivery_manifest"))[-1]
        tokens = _tokens(manifest)
        assert "form:reply" in tokens
        assert "delivery:reply" in tokens
        assert "reply:555003" in tokens
        assert "mismatch:none" in tokens
        decided = (await _rows(db, "initiative_decided"))[-1]
        assert decided["trace_id"] == "corr-g4-reply"
        assert decided["status"] == "reply.text"
        assert "tgt:%d" % row_id in _tokens(decided)
        assert "delivery:reply" in _tokens(decided)
        assert SECRET_TEXT not in str(manifest)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_mismatch_chosen_reply_sent_chat_keeps_reason(tmp_path,
                                                           monkeypatch):
    from services.direct_l1 import L1Plan
    db = await _db(tmp_path, "g4_mismatch.db")
    row_id = await _msg(db, tg_id=555004, age_s=40 * 3600)  # устаревшая цель
    result, calls = await _run_send(
        db, monkeypatch,
        plan=L1Plan(action="reply", delivery="reply",
                    target_message_id=row_id, confidence=0.9,
                    confidence_bucket="high", source="llm"),
        row_id=row_id, correlation="corr-g4-mismatch")
    try:
        assert result["status"] == "sent"
        assert "reply_to_message_id" not in calls[0]
        cursor = await db.db.execute(
            "SELECT parent_message_ref FROM mca_bot_outputs "
            "WHERE source_feature = 'mca09_intents'")
        assert [r[0] for r in await cursor.fetchall()] == [None]
        await mca_events.flush_events(db)
        manifest = (await _rows(db, "initiative_delivery_manifest"))[-1]
        tokens = _tokens(manifest)
        assert "form:chat" in tokens
        assert "delivery:reply" in tokens
        assert "mismatch:target_stale" in tokens
    finally:
        await db.close()
