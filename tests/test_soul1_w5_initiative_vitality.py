"""SOUL-1 / W5 — честная жизнеспособность инициативы (SOUL-18.2/18.4/18.5/18.6).

Покрытие:

* **окна 24/48ч из durable-источников:** число сканов/наблюдённых/оценок/
  возможностей, распределение молчания по причинам, попытки отправки,
  доставки, дубли, задержка и «последние» штампы; нули видны нулями, а
  неполное покрытие окна честно помечено;
* **health ≠ outcome:** живые тики НЕ выдаются за отправку; «возможности
  есть, сообщений нет» — предупреждение с распределением причин;
  opportunities=0 при 2000+ живых сообщениях диагностируется как задушенные
  ворота; низкая естественная активность — не ошибка;
* **сопоставление доставки:** `message_id` + ревизии Core/Style из манифеста
  доставки + дубли + задержка;
* **причины молчания не теряются:** коды инициативных решений выживают в
  контракте событий (regression ранее отбрасывал `reason_code`);
* **безопасная проверка:** trace до mock send, ноль публикаций по умолчанию,
  воронка не подменяется, preview ограничен;
* **RBAC + R17:** только глобальный админ; сырой текст чата в payload нет.

TEST-LIFECYCLE: CONTRACT owner=SOUL-18.2/18.4/18.5/18.6 (soul-1, W5)
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from services import chat_params
from services import hot_config
from services import initiative_diagnostics as diag
from services import mca_events
from services import initiative_observer as obs
from services.database import DatabaseService
from services.task_supervisor import TaskJobStore

CHAT = -2026

TEST_TOKEN = "123456:TEST_TOKEN_W5"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeChatParams:
    def __init__(self, by_chat=None):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


def _caches(by_chat=None, hot=None):
    hot_config.set_config_cache(_FakeHot(hot or {}))
    chat_params.set_chat_params_cache(_FakeChatParams(by_chat or {}))


@pytest.fixture(autouse=True)
def _clean():
    mca_events.reset_pending()
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    diag._vitality_cache.clear() if hasattr(diag, "_vitality_cache") else None
    yield
    mca_events.reset_pending()
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


async def _db(tmp_path, name) -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db, *, chat_id=CHAT, text="реплика", ts_ago=60, user_id=42):
    ts = int(time.time()) - int(ts_ago)
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
        (user_id, chat_id, text, ts))
    await db.db.commit()
    return cursor.lastrowid


async def _many_msgs(db, count: int, *, ts_ago=120, chat_id=CHAT):
    ts = int(time.time()) - int(ts_ago)
    await db.db.executemany(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
        [(42 + (i % 3), chat_id, "реплика %d" % i, ts) for i in range(count)])
    await db.db.commit()


async def _job(db, *, ts_ago: int, counters: dict, chats=None) -> str:
    store = TaskJobStore(db)
    payload = {
        obs.CURSOR_KEY: 0,
        "counters": {**obs.default_counters(), **counters},
        "chats": chats or {},
        "day": {"stamp": 0, "observed": 0, "opportunities": 0},
        "last_diag_ts": 0,
    }
    job_id = await store.enqueue(owner="asap8b01", kind=obs.OBSERVE_JOB_KIND,
                                 payload=json.dumps(payload),
                                 max_attempts=3)
    ts = int(time.time()) - int(ts_ago)
    await db.db.execute(
        "UPDATE task_jobs SET status = 'completed', created_at = ?, "
        "updated_at = ?, finished_at = ?, progress_at = ? WHERE job_id = ?",
        (ts, ts, ts, ts, job_id))
    await db.db.commit()
    return job_id


async def _event(db, name: str, *, chat_id=CHAT, ts_ago: int = 60,
                 outcome: str = "success", stage=None, reason_code=None,
                 status=None, entity_ids=None, config_version=None) -> None:
    mca_events.emit_mca_event(name, outcome=outcome, component="initiative",
                              chat_id=chat_id, stage=stage,
                              reason_code=reason_code, status=status,
                              entity_ids=entity_ids,
                              config_version=config_version)
    await mca_events.flush_events(db)
    ts = int(time.time()) - int(ts_ago)
    await db.db.execute("UPDATE mca_events SET ts = ? WHERE id = "
                        "(SELECT MAX(id) FROM mca_events)", (ts,))
    await db.db.commit()


async def _ledger(db, *, ts_ago=60, message_id=555, hash_="h1",
                  correlation="corr-1", chars=40) -> None:
    ts = int(time.time()) - int(ts_ago)
    await db.db.execute(
        "INSERT INTO mca_bot_outputs (bot_user_id, chat_id, tg_message_id, "
        "revision_no, sent_at, parent_message_ref, output_kind, content_text, "
        "content_ref, content_hash, correlation_id, source_feature, "
        "delivery_status, created_at) VALUES (?, ?, ?, 1, ?, NULL, ?, ?, "
        "NULL, ?, ?, 'mca09_intents', 'delivered', ?)",
        (999, CHAT, message_id, ts, diag.OUTPUT_KIND_INITIATIVE,
         "т" * int(chars), hash_, correlation, ts))
    await db.db.commit()


# ═══ 1. Нули — нулями, покрытие — честное ═══════════════════════════════════

@pytest.mark.asyncio
async def test_empty_db_gives_zeros_and_insufficient_coverage(tmp_path):
    db = await _db(tmp_path, "w5_empty.db")
    try:
        window = await diag.collect_window(db, hours=24)
        assert window["scans"] == 0
        assert window["observed"] == 0
        assert window["opportunities"] == 0
        assert window["delivered"] == 0
        assert window["coverage"] == "insufficient"
        assert window["sends"] == []
        assert window["decisions"] == {"say": 0, "react": 0, "silent": 0,
                                       "cancelled": 0, "other": 0}
        assert window["latency_seconds"] == {"p50": None, "max": None,
                                             "samples": 0}
        verdict = diag.activity_verdict(window, live_messages=None,
                                        master_on=True, chat_on=None)
        assert verdict["state"] == "no_data"
        assert verdict["warning"] == ""
        assert verdict["health"]["heartbeat_ok"] is False
        assert "heartbeat≠outcome" in verdict["health"]["note"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_window_deltas_come_from_durable_counters(tmp_path):
    db = await _db(tmp_path, "w5_delta.db")
    try:
        # baseline (30ч назад) и внутриоконные значения
        await _job(db, ts_ago=30 * 3600, counters={
            "passes": 10, "observed": 1000, "eligible": 500, "evals": 20,
            "opportunities": 5, "sent": 1, "errors": 0,
            "eval_skips": {"min_gap": 7}})
        await _job(db, ts_ago=20 * 3600, counters={
            "passes": 20, "observed": 2000, "eligible": 900, "evals": 30,
            "opportunities": 7, "sent": 1, "errors": 1,
            "eval_skips": {"min_gap": 9, "not_enough_messages": 4}})
        await _job(db, ts_ago=3600, counters={
            "passes": 30, "observed": 2600, "eligible": 1200, "evals": 40,
            "opportunities": 10, "sent": 2, "errors": 1,
            "eval_skips": {"min_gap": 12, "not_enough_messages": 9}})
        window_24 = await diag.collect_window(db, hours=24)
        # 24ч: базовая точка — САМЫЙ СТАРЫЙ прогон внутри окна (20ч назад)
        assert window_24["coverage"] == "full"
        assert window_24["scans"] == 10
        assert window_24["observed"] == 600
        assert window_24["opportunities"] == 3
        assert window_24["delivered"] == 1
        assert window_24["eval_skips"] == {"min_gap": 3,
                                          "not_enough_messages": 5}
        window_48 = await diag.collect_window(db, hours=48)
        # 48ч: базовая точка — прогон 30ч назад → дельта больше
        assert window_48["observed"] == 1600
        assert window_48["opportunities"] == 5
        assert window_48["eval_skips"]["min_gap"] == 5
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_coverage_partial_when_history_shorter_than_window(tmp_path):
    db = await _db(tmp_path, "w5_partial.db")
    try:
        await _job(db, ts_ago=2 * 3600, counters={"passes": 1, "observed": 10})
        await _job(db, ts_ago=3600, counters={"passes": 2, "observed": 30})
        window = await diag.collect_window(db, hours=24)
        assert window["coverage"] == "partial"
        assert "короче окна" in window["coverage_note"]
        assert window["observed"] == 20
    finally:
        await db.close()


# ═══ 2. Возможности по видам, решения и причины молчания ═══════════════════

@pytest.mark.asyncio
async def test_opportunity_kinds_and_silence_reasons_distribution(tmp_path):
    db = await _db(tmp_path, "w5_reasons.db")
    try:
        await _job(db, ts_ago=2 * 3600, counters={"passes": 1, "observed": 5,
                                                  "opportunities": 0})
        await _job(db, ts_ago=3600, counters={"passes": 3, "observed": 25,
                                              "opportunities": 3})
        await _event(db, diag.OPPORTUNITY_EVENT, stage="opportunity:humor:say",
                     ts_ago=600)
        await _event(db, diag.OPPORTUNITY_EVENT,
                     stage="opportunity:dispute:react", ts_ago=500)
        await _event(db, diag.OPPORTUNITY_EVENT, stage="opportunity:none",
                     outcome="skipped", ts_ago=400)
        # молчание с причиной и отказ
        await _event(db, diag.DECIDED_EVENT, outcome="silent",
                     reason_code="recent_reply", status="silent",
                     stage="new_message", ts_ago=300)
        await _event(db, diag.DECIDED_EVENT, outcome="silent",
                     reason_code="default", status="silent", ts_ago=280)
        await _event(db, diag.DECIDED_EVENT, outcome="cancelled",
                     reason_code="intent_closed", status="say", ts_ago=200)
        window = await diag.collect_window(db, hours=24)
        assert window["opportunities_by_kind"] == {"humor": 1, "dispute": 1}
        assert window["decisions"]["silent"] == 2
        assert window["decisions"]["cancelled"] == 1
        codes = {item["reason_code"]: item["count"]
                 for item in window["silence_by_reason"]}
        assert codes["recent_reply"] == 1
        assert codes["default"] == 1          # код больше не отбрасывается
        assert codes["intent_closed"] == 1
        labels = {item["reason_code"]: item["label"]
                  for item in window["silence_by_reason"]}
        assert labels["recent_reply"]
        assert labels["recent_reply"] != "recent_reply"
        assert window["refusals"] == 1
    finally:
        await db.close()


def test_initiative_reason_codes_survive_event_contract():
    """Regression W5: `build_event` раньше молча выбрасывал эти причины."""
    codes = ("default", "recent_reply", "l1_unavailable", "l1_silent",
             "l1_react", "recheck_demoted", "delivery_not_text",
             "initiative_delivered_manifest", "initiative_check_dry_run")
    for code in codes:
        event = mca_events.build_event("initiative_decided", outcome="silent",
                                       reason_code=code)
        assert event is not None
        assert event.get("reason_code") == code, code


# ═══ 3. Health ≠ outcome: вердикты и предупреждения ════════════════════════

@pytest.mark.asyncio
async def test_opportunities_without_messages_is_a_warning(tmp_path):
    db = await _db(tmp_path, "w5_warn.db")
    try:
        await _job(db, ts_ago=3600, counters={"passes": 5, "observed": 40,
                                              "opportunities": 4,
                                              "silent_decisions": 4})
        await _event(db, diag.OPPORTUNITY_EVENT, stage="opportunity:humor:say",
                     ts_ago=900)
        for i in range(4):
            await _event(db, diag.DECIDED_EVENT, outcome="silent",
                         reason_code="recent_reply", status="silent",
                         ts_ago=800 - i)
        await _many_msgs(db, 30, ts_ago=200)
        live = await obs.live_messages(db, CHAT)
        window = await diag.collect_window(db, hours=24, chat_id=CHAT)
        verdict = diag.activity_verdict(
            window, live_messages=live, master_on=True, chat_on=True,
            liveness={"ts": int(time.time()) - 60, "status": "completed"})
        assert verdict["state"] == "opportunities_no_messages"
        assert verdict["level"] == "warn"
        assert verdict["title"] == "Возможности есть, сообщений нет"
        assert verdict["warning"]
        assert verdict["recommendation"]
        assert verdict["reasons"], "распределение причин обязательно"
        # health отделён от outcome: тик живой, но это НЕ отправка
        assert verdict["health"]["heartbeat_ok"] is True
        assert verdict["counters"]["delivered"] == 0
        assert verdict["silent_streak"] == 4
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_live_chat_without_opportunities_is_diagnosed(tmp_path):
    db = await _db(tmp_path, "w5_busy.db")
    try:
        await _job(db, ts_ago=3600, counters={"passes": 5, "observed": 2500})
        await _many_msgs(db, 2100, ts_ago=300)
        live = await obs.live_messages(db, CHAT)
        assert live >= 2000
        window = await diag.collect_window(db, hours=24, chat_id=CHAT)
        verdict = diag.activity_verdict(window, live_messages=live,
                                        master_on=True, chat_on=True)
        assert verdict["state"] == "observer_silent_live_chat"
        assert verdict["level"] == "warn"
        assert "не находятся" in verdict["title"]
        assert verdict["recommendation"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_low_activity_is_not_an_error(tmp_path):
    db = await _db(tmp_path, "w5_low.db")
    try:
        await _job(db, ts_ago=3600, counters={"passes": 3, "observed": 6})
        await _many_msgs(db, 5, ts_ago=600)
        live = await obs.live_messages(db, CHAT)
        window = await diag.collect_window(db, hours=24, chat_id=CHAT)
        verdict = diag.activity_verdict(window, live_messages=live,
                                        master_on=True, chat_on=True)
        assert verdict["state"] == "low_activity"
        assert verdict["level"] == "info"
        assert verdict["warning"] == ""
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_disabled_scope_is_reported_not_hidden(tmp_path):
    db = await _db(tmp_path, "w5_off.db")
    try:
        await _job(db, ts_ago=3600, counters={"passes": 3, "observed": 12})
        window = await diag.collect_window(db, hours=24, chat_id=CHAT)
        verdict = diag.activity_verdict(window, live_messages=100,
                                        master_on=False, chat_on=False)
        assert verdict["state"] == "disabled"
        assert verdict["level"] == "warn"
        assert verdict["warning"]
    finally:
        await db.close()


# ═══ 4. Доставка: message_id, манифест, дубли, задержка ════════════════════

@pytest.mark.asyncio
async def test_sends_are_correlated_with_message_id_and_manifest(tmp_path):
    db = await _db(tmp_path, "w5_sends.db")
    try:
        await _job(db, ts_ago=3600, counters={"passes": 2, "observed": 12,
                                              "opportunities": 1, "sent": 1})
        await _ledger(db, ts_ago=600, message_id=777, hash_="aaa",
                      correlation="corr-777", chars=48)
        await _ledger(db, ts_ago=500, message_id=778, hash_="aaa",
                      correlation="corr-778", chars=48)
        await _event(db, diag.MANIFEST_EVENT, ts_ago=600,
                     entity_ids=["initiative_delivery", "corr:corr-777",
                                 "msg:777", "core:abc123", "style:def456",
                                 "identity:iii789", "manifest:mmm000",
                                 "composer:on"],
                     config_version=("core=abc123;style=def456;"
                                     "identity=iii789;manifest=mmm000;"
                                     "composer=on"))
        await _event(db, diag.WRITER_GENERATED_EVENT, ts_ago=700,
                     entity_ids=["intent:intent-1"])
        await _event(db, diag.SENT_EVENT, ts_ago=610,
                     entity_ids=["intent:intent-1"])
        await _event(db, diag.RECHECK_PASSED_EVENT, ts_ago=650,
                     entity_ids=["intent:intent-1"])
        window = await diag.collect_window(db, hours=24, chat_id=CHAT)
        assert window["delivered_ledger"] == 2
        assert window["send_attempts"] == 1
        assert window["duplicates"] == 1, "одинаковый текст → дубль"
        top = window["sends"][0]
        assert top["message_id"] in (777, 778)
        assert top["chars"] == 48
        manifest_send = [s for s in window["sends"]
                         if s["message_id"] == 777][0]
        assert manifest_send["core_revision"] == "abc123"
        assert manifest_send["style_policy_revision"] == "def456"
        assert manifest_send["manifest_id"] == "mmm000"
        assert manifest_send["composer"] == "on"
        # доставка без манифеста — честно пусто, а не «текущие» значения
        no_manifest = [s for s in window["sends"]
                       if s["message_id"] == 778][0]
        assert no_manifest["core_revision"] == ""
        assert no_manifest["composer"] == ""
        assert window["latency_seconds"]["samples"] == 1
        assert window["latency_seconds"]["p50"] == 90
        assert window["last"]["delivered_ts"] > 0
    finally:
        await db.close()


# ═══ 5. Безопасная проверка: mock send, без публикации ═════════════════════

class _FakeWriter:
    def __init__(self, text="Инициативная реплика без кавычек"):
        self.text = text
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        from services.direct_l1 import L1Plan
        return L1Plan(action="reply", confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        return self.text


class _FakeLLM:
    def __init__(self, verdict=None):
        self.verdict = verdict or {
            "opportunity": True, "kind": "humor", "action": "say",
            "horizon": "now", "addressee_user_id": None, "topic_key": "tema",
            "goal": "повод", "rationale": "уместно"}
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return json.dumps(self.verdict, ensure_ascii=False)


async def _event_names(db, name) -> list[dict]:
    await mca_events.flush_events(db)
    cursor = await db.db.execute(
        "SELECT outcome, reason_code, stage, status FROM mca_events WHERE "
        "event_name = ? ORDER BY ts, rowid", (name,))
    return [dict(r) for r in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_check_dry_run_reaches_mock_send_without_publishing(tmp_path):
    db = await _db(tmp_path, "w5_check.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 4,
                    "initiative.eval_min_interval_seconds": 0,
                    "initiative.min_gap_seconds": 0,
                    "initiative.eval_llm_budget_per_day": 10}})
    writer = _FakeWriter()
    try:
        for i in range(6):
            await _msg(db, text="живой повод для проверки %d" % i, ts_ago=300 - i)
        result = await diag.run_check(db, chat_id=CHAT, writer_service=writer,
                                      llm=_FakeLLM())
        assert result["available"] is True
        assert result["published"] is False
        assert result["publish_mode"] == "mock"
        assert result["verdict"]["kind"] == "humor"
        assert result["mock_send"]["attempted"] is True
        assert result["mock_send"]["published"] is False
        assert result["mock_send"]["would_send_chars"] > 0
        assert result["mock_send"]["preview"].startswith("Инициативная")
        assert len(result["mock_send"]["preview"]) <= diag.PREVIEW_CHARS
        stages = [step["stage"] for step in result["trace"]]
        for expected in ("gates", "window", "evaluate", "decision", "writer",
                         "mock_send"):
            assert expected in stages, stages
        # воронка не подменяется: диагностика не пишет решения/отправки
        assert await _event_names(db, diag.DECIDED_EVENT) == []
        assert await _event_names(db, diag.SENT_EVENT) == []
        markers = await _event_names(db, diag.CHECK_EVENT)
        assert markers and markers[-1]["reason_code"] == \
            "initiative_check_dry_run"
        assert markers[-1]["stage"] == "diagnostics:mock"
    finally:
        await db.close()


class _RowCapturingWriter:
    """Writer-двойник: фиксирует ФАКТИЧЕСКИЙ контекст повода из dry-run."""

    def __init__(self, text="Инициативная реплика из повода"):
        self.text = text
        self.contexts: list[dict] = []

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        self.contexts.append(dict(intent_row or {}))
        from services.direct_l1 import L1Plan
        return L1Plan(action="reply", confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.contexts.append(dict(intent_row or {}))
        return self.text


@pytest.mark.asyncio
async def test_check_dry_run_carries_live_ephemeral_opportunity_context(
        tmp_path):
    """TEST-LIFECYCLE: REGRESSION owner=P0A-INIT

    «Проверить инициативу» обязана показывать ТУ ЖЕ цепочку, что боевой
    путь наблюдателя: dry-run передаёт Writer контекст эфемерного повода
    (goal/kind/origin/created_at), а не пустую строку («цель не указана»).
    Регресс (REV-INIT-FIX): dry-run звал handle_initiative БЕЗ
    opportunity_row."""
    db = await _db(tmp_path, "w5_check_ctx.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 4,
                    "initiative.eval_min_interval_seconds": 0,
                    "initiative.min_gap_seconds": 0,
                    "initiative.eval_llm_budget_per_day": 10}})
    writer = _RowCapturingWriter()
    try:
        for i in range(6):
            await _msg(db, text="живой повод для проверки %d" % i,
                       ts_ago=300 - i)
        result = await diag.run_check(db, chat_id=CHAT, writer_service=writer,
                                      llm=_FakeLLM())
        assert result["mock_send"]["attempted"] is True
        assert writer.contexts, "Writer не был вызван в dry-run"
        row = writer.contexts[0]
        assert row, "dry-run отдал Writer пустой контекст повода"
        assert row.get("goal") == "повод"
        assert row.get("kind") == "topic_interest"
        assert row.get("origin") == "observer_opportunity"
        assert row.get("status") == "ephemeral"
        assert row.get("chat_id") == CHAT
        assert int(row.get("created_at") or 0) > 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_check_dry_run_goal_fallback_uses_original_verdict_kind(
        tmp_path):
    """TEST-LIFECYCLE: REGRESSION owner=P0A-INIT (review F1)

    Пустая цель вердикта (канон даёт "") — фолбэк goal обязан быть каноном
    ОРИГИНАЛЬНОГО verdict-kind («dispute»), а не маппед-вида intent-kind
    («open_dispute»): извлечение производителя строки не имеет права менять
    значения боевого пути наблюдателя (byte-identical, REV-DIAG-MINIFIX F1)."""
    db = await _db(tmp_path, "w5_check_fallback.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 4,
                    "initiative.eval_min_interval_seconds": 0,
                    "initiative.min_gap_seconds": 0,
                    "initiative.eval_llm_budget_per_day": 10}})
    writer = _RowCapturingWriter()
    verdict = {"opportunity": True, "kind": "dispute", "action": "say",
               "horizon": "now", "addressee_user_id": None,
               "topic_key": "spor", "goal": "", "rationale": "спор"}
    try:
        for i in range(6):
            await _msg(db, text="спорный повод для проверки %d" % i,
                       ts_ago=300 - i)
        result = await diag.run_check(db, chat_id=CHAT, writer_service=writer,
                                      llm=_FakeLLM(verdict))
        assert result["mock_send"]["attempted"] is True
        assert writer.contexts, "Writer не был вызван в dry-run"
        row = writer.contexts[0]
        assert row.get("goal") == "dispute"
        assert row.get("kind") == "open_dispute"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_check_publish_is_off_without_owner_axis(tmp_path):
    db = await _db(tmp_path, "w5_publish.db")
    _caches({CHAT: {}})
    writer = _FakeWriter()

    class _RealBot:
        id = 42
        sent: list = []

        async def send_message(self, chat_id, text, **kwargs):
            self.sent.append((int(chat_id), str(text)))

            class _M:
                message_id = 1

            return _M()

    bot = _RealBot()
    try:
        for i in range(6):
            await _msg(db, text="повод для публикации %d" % i, ts_ago=300 - i)
        result = await diag.run_check(
            db, chat_id=CHAT, writer_service=writer, llm=_FakeLLM(),
            bot=bot, publish=True, confirm_publish=True)
        assert result["published"] is False
        assert result["publish_disabled_reason"] == "publish_axis_off"
        assert bot.sent == [], "без оси владельца публикации быть не может"
        assert result["mock_send"]["published"] is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_check_without_llm_is_honest(tmp_path):
    db = await _db(tmp_path, "w5_check_nollm.db")
    _caches({CHAT: {}})
    try:
        for i in range(5):
            await _msg(db, text="повод без оценщика %d" % i, ts_ago=300 - i)
        result = await diag.run_check(db, chat_id=CHAT,
                                      writer_service=_FakeWriter(), llm=None)
        assert result["available"] is True
        assert result["mock_send"]["attempted"] is False
        stage = [s for s in result["trace"] if s["stage"] == "evaluate"][0]
        assert stage["status"] == "skipped"
        assert stage["reason_code"] == "llm_unavailable"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_vitality_payload_has_no_chat_text(tmp_path):
    db = await _db(tmp_path, "w5_r17.db")
    try:
        secret = "СЕКРЕТНЫЙ-ТЕКСТ-УЧАСТНИКА-901"
        await _msg(db, text=secret, ts_ago=120)
        await _job(db, ts_ago=3600, counters={"passes": 1, "observed": 1})
        payload = await diag.collect_vitality(db, chat_id=CHAT, hours=24)
        dumped = json.dumps(payload, ensure_ascii=False)
        assert secret not in dumped
        assert payload["activity"]["state"] in (
            "low_activity", "no_data", "observer_silent_live_chat",
            "opportunities_no_messages", "ok")
    finally:
        await db.close()




# ═══ 6. API: RBAC, форма ответа, публикация по умолчанию выключена ═════════

def _make_init_data(user_id: int = ADMIN_ID) -> str:
    import hashlib
    import hmac
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkW5",
        "user": json.dumps({"id": user_id, "first_name": "A"},
                           separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, v) for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": _make_init_data(user_id)}


def _build_client(monkeypatch, db):
    """TestClient приложения с реальной БД в lore_runtime (паттерн W3-STATUS)."""
    import types
    from services.config_cache import ConfigCache
    from services import lore_runtime
    from web.app import create_app
    from web.api import deps as deps_mod
    from web.api import initiative_vitality as iv

    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    lore_runtime.set_lore_components(db=db)
    iv._vitality_cache.clear()
    iv._events_cache.clear()
    cache = ConfigCache(pg=None, retry_attempts=1, retry_delay=0)
    return TestClient(create_app(cache)), lore_runtime, iv


def test_api_401_without_init_data(tmp_path, monkeypatch):
    """Оба endpoint'а закрыты RBAC (как существующий memory-API)."""
    import asyncio

    async def _run():
        db = await _db(tmp_path, "w5_api401.db")
        try:
            tc, _lore, _iv = _build_client(monkeypatch, db)
            with tc:
                assert tc.get(
                    "/api/memory/initiative-vitality").status_code == 401
                assert tc.post("/api/memory/initiative-check",
                               json={"chat_id": CHAT}).status_code == 401
        finally:
            await db.close()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


def test_api_vitality_and_check_are_admin_only_and_honest(tmp_path,
                                                          monkeypatch):
    import asyncio

    async def _run():
        db = await _db(tmp_path, "w5_api.db")
        try:
            await _msg(db, text="живой повод", ts_ago=120)
            await _job(db, ts_ago=3600, counters={"passes": 2, "observed": 3,
                                                  "opportunities": 1})
            await _ledger(db, ts_ago=300, message_id=901, correlation="c-1")
            tc, lore_runtime, iv = _build_client(monkeypatch, db)

            async def _no_engine():
                return None, None

            monkeypatch.setattr(iv, "_writer_and_llm", _no_engine)
            try:
                with tc:
                    resp = tc.get("/api/memory/initiative-vitality?chat_id=%d"
                                  % CHAT, headers=_hdr())
                    assert resp.status_code == 200, resp.text
                    body = resp.json()
                    assert body["available"] is True
                    assert body["chat_scoped"] is True
                    assert body["gates"]["effective"]["profile"] == "normal"
                    assert body["gates"]["items"], "причины ворот обязательны"
                    assert body["funnel"]["job"] is not None
                    assert body["sends"][0]["message_id"] == 901
                    assert "activity" in body and "windows" in body
                    check = tc.post("/api/memory/initiative-check",
                                    json={"chat_id": CHAT}, headers=_hdr())
                    assert check.status_code == 200, check.text
                    payload = check.json()
                    assert payload["published"] is False
                    assert payload["publish_mode"] == "mock"
                    assert payload["mock_send"]["published"] is False
                    assert payload["llm_calls"] == 0
                    from web.api import memory_agi
                    monkeypatch.setattr(memory_agi, "_is_global_admin",
                                        lambda cache, tid: tid != MODERATOR_ID)
                    denied = tc.get("/api/memory/initiative-vitality",
                                    headers=_hdr(MODERATOR_ID))
                    assert denied.status_code == 403
            finally:
                lore_runtime.reset_lore_runtime()
        finally:
            await db.close()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
