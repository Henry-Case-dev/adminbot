"""ASAP 8 v6 C06A — funnel → UI (status payload contract + 4 состояния).

Контракт v6 §C06A: Status раздельно показывает effective/master,
scheduler registered/last/next tick, воронку 24ч (producers/created/due/
decisions/writer/recheck/sent), state_label + top_block_reason. Редкие/
нулевые значения могут быть корректны — невидимый pipeline нет.

Python-сторона проверяет payload `intent_snapshot()` — ровно те поля,
которые маппит `web/app.js::intentModuleStatus()` (registered/next_tick/
last_tick/funnel/state_label/top_block_reason). Рендер проверяется
Playwright/Browser Use (см. c06a-report.md).

TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/C06A (payload→UI mapping)
"""
import time

import pytest

from services import mca_events
from services import mca_gates
from services import memory_maintenance as mm
from services.database import DatabaseService
from services.status_service import StatusService

CHAT = -100778


@pytest.fixture(autouse=True)
def _clean_mm_globals():
    mca_events.reset_pending()
    mm._heartbeat_last_tick.update({"ts": None, "due": 0, "enabled": None})
    yield
    mm._heartbeat_last_tick.update({"ts": None, "due": 0, "enabled": None})
    mca_events.reset_pending()


async def _db(tmp_path, name="c06a_st.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _snapshot(db) -> dict:
    """intent_snapshot с подменённым lore_runtime.get_lore_db (прецедент F6)."""
    from services import lore_runtime
    original = lore_runtime.get_lore_db
    lore_runtime.get_lore_db = lambda: db
    try:
        return await StatusService().intent_snapshot(chat_id=CHAT,
                                                     chat_scope_allowed=True)
    finally:
        lore_runtime.get_lore_db = original


def _set_stamp(ts, *, due=0, enabled=True):
    mm._heartbeat_last_tick.update({"ts": ts, "due": due,
                                    "enabled": enabled})


@pytest.mark.asyncio
async def test_payload_exposes_ui_mapping_fields(tmp_path, monkeypatch):
    """Payload содержит ВСЕ поля, которые читает UI-маппинг v6 C06A:
    heartbeat.registered/next_tick/last_tick + funnel.* + state_label +
    top_block_reason. registered/next_tick приходят из живого планировщика
    (в тестах планировщик не запущен → честное registered=False)."""
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled", lambda: True)
    db = await _db(tmp_path, "c06a_map.db")
    try:
        _set_stamp(int(time.time()), due=0, enabled=True)
        snap = await _snapshot(db)
        mod = snap["module"]
        hb = mod["heartbeat"]
        # UI mapping: heartbeat-факты
        assert "registered" in hb and hb["registered"] is False
        assert "next_tick" in hb
        assert hb["last_tick"]["ts"] is not None
        assert hb["last_tick"]["enabled"] is True
        # UI mapping: funnel-ключи 24ч
        funnel = mod["funnel"]
        for key in ("producers_24h", "intents_created_24h", "due",
                    "decisions_24h", "writer_generated_24h",
                    "recheck_passed_24h", "sent_24h", "heartbeat_last_tick"):
            assert key in funnel, key
        assert funnel["heartbeat_last_tick"] is not None
        # UI mapping: диагностика
        assert "state_label" in mod and mod["state_label"]
        assert "top_block_reason" in mod
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_state_1_heartbeat_never_ran(tmp_path):
    """Состояние 1: ts=None → «ещё не запускался» + heartbeat_not_run
    (не «работает» — контракт REV-F6 F2 сохранён)."""
    db = await _db(tmp_path, "c06a_s1.db")
    try:
        _set_stamp(None)
        snap = await _snapshot(db)
        mod = snap["module"]
        assert "ещё не запускался" in mod["state_label"]
        assert "работает" not in mod["state_label"]
        assert mod["top_block_reason"] == "heartbeat_not_run"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_state_2_gate_off_stamp_honest(tmp_path):
    """Состояние 2 (v6 C06A): тик проходит, но штамп enabled=False →
    честное «Heartbeat выключен», а не «работает»."""
    db = await _db(tmp_path, "c06a_s2.db")
    try:
        _set_stamp(int(time.time()), enabled=False)
        snap = await _snapshot(db)
        mod = snap["module"]
        assert "выключен" in mod["state_label"]
        assert "работает" not in mod["state_label"]
        assert mod["top_block_reason"] == "heartbeat_disabled"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_state_3_producers_zero_visible(tmp_path):
    """Состояние 3: тик есть, producers за 24ч = 0 → диагноз «producers»
    виден в payload (раньше считался только legacy «не запускалось»)."""
    db = await _db(tmp_path, "c06a_s3.db")
    try:
        _set_stamp(int(time.time()), enabled=True)
        snap = await _snapshot(db)
        mod = snap["module"]
        assert "producers" in mod["state_label"]
        assert mod["funnel"]["intents_created_24h"] == 0
        assert mod["funnel"]["producers_24h"] == {}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_state_4_norm_sent_visible(tmp_path, monkeypatch):
    """Состояние 4 («норма»): intent_created + initiative_sent за 24ч →
    «Инициатива работает: отправлено N» + счётчики воронки непустые."""
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled", lambda: True)
    db = await _db(tmp_path, "c06a_s4.db")
    try:
        _set_stamp(int(time.time()), enabled=True)
        # «Норма» в формуле F6 достижима только полной цепочкой
        # decided→writer→recheck→sent (стадии воронки 24ч).
        mca_events.emit_mca_event(
            "intent_created", outcome="success", component="intents",
            chat_id=CHAT, stage="unanswered_question")
        for name in ("initiative_decided", "initiative_writer_generated",
                     "initiative_recheck_passed", "initiative_sent"):
            mca_events.emit_mca_event(
                name, outcome="success", component="intents", chat_id=CHAT)
        await mca_events.flush_events(db)
        snap = await _snapshot(db)
        mod = snap["module"]
        funnel = mod["funnel"]
        assert funnel["producers_24h"].get("unanswered_question") == 1
        assert funnel["intents_created_24h"] == 1
        assert funnel["sent_24h"] == 1
        assert "Инициатива работает" in mod["state_label"]
        assert mod["top_block_reason"] == ""
    finally:
        await db.close()
