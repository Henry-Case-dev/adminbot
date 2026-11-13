"""EVOL-014 — бэкенд инициативных мемов (офлайн, без сети и Telegram).

TEST-LIFECYCLE: CONTRACT owner=EVOL-014 (квота, гейты, промпт, изоляция чатов)
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import pathlib
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import initiative_observer as obs
from services import mca_exploration as mx
from services import mca_random_source as mrs
from services import meme_initiative as meme
from services import prompt_registry as pr
from services.database import DatabaseService

PREFIX = "Создай мем с шрифтом импакт:"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}


@pytest.fixture(autouse=True)
def _reset_ring():
    meme.reset_process_attempts()
    pr.reset_cache()
    yield
    meme.reset_process_attempts()
    pr.reset_cache()


def _ledger(tmp_path):
    led = meme.SqliteQuotaLedger(str(tmp_path / "meme.db"))
    led.apply_schema()
    return led


def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=8, daily_limit=3,
                cooldown_seconds=0, min_messages=1,
                trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


def _rows(chat_id: int, n: int = 3) -> list[dict]:
    return [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


class _Hit:
    def __init__(self, value=0.0, *, deferred=False, fallback=None,
                 missing=False):
        self.value = value
        self.deferred = deferred
        self.fallback = fallback
        self.missing = missing
        self.calls = 0

    async def draw_probability(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        if self.missing:
            return None
        return mrs.DrawResult(
            value=None if self.deferred else self.value,
            deferred=self.deferred,
            fallback_reason=self.fallback,
            source="pseudorandom" if self.fallback else "quantum",
            selected_source="quantum",
            draw_id="draw-1")


class _Provider:
    def __init__(self, *, ok=True, called=True, reason=""):
        self.ok = ok
        self.called = called
        self.reason = reason
        self.calls = []

    async def __call__(self, prompt, chat_id, job_id):
        self.calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=self.ok, called=self.called,
                               reason=self.reason, content=b"png")


def _run(coro):
    return asyncio.run(coro)


async def _consider(tmp_path, chat_id=-100, *, source=None, provider=None,
                    summarizer=None, joke_generator=None, gate=None,
                    sender=None, messages=None,
                    reader=None, settings=None, ledger=None,
                    image_status=None, model_chars=200, **kwargs):
    led = ledger if ledger is not None else _ledger(tmp_path)
    if source is None:
        source = _Hit()
    if provider is None:
        provider = _Provider()
    if summarizer is None:
        async def summarizer(cid, rows, system):
            return "хук"
    if joke_generator is None:
        async def joke_generator(cid, summary, instruction):
            return "прикол"
    result = await meme.consider_chat(
        None, chat_id,
        settings=settings if settings is not None else _settings(),
        ledger=led,
        now=NOW,
        tz_name="UTC",
        tz_source="utc_fallback",
        initiative_enabled=lambda: True,
        image_status=IMAGE_OK if image_status is None else image_status,
        random_source=source,
        messages=messages if messages is not None else _rows(chat_id),
        message_reader=reader,
        summarizer=summarizer,
        joke_generator=joke_generator,
        image_provider=provider,
        publish_gate=gate,
        sender=sender,
        model_chars=model_chars,
        **kwargs)
    return result, provider, led


# ── 1. подсервис, тумблеры ──────────────────────────────────────────────────

def test_default_off_and_text_initiative_untouched(tmp_path):
    assert meme.DEFAULT_ENABLED is False
    assert meme.MemeSettings().enabled is False
    assert meme.blocks_text_initiative() is False
    assert obs.INITIATIVE_OUTPUT_KINDS == ("initiative_reply",)
    assert meme.OUTPUT_KIND == "meme_initiative"
    assert meme.OUTPUT_KIND not in obs.INITIATIVE_OUTPUT_KINDS

    text = []

    async def text_reply():
        text.append("reply")

    async def scenario():
        await text_reply()
        provider = _Provider()
        result, _, _ = await _consider(
            tmp_path, provider=provider,
            settings=_settings(enabled=False))
        return result, provider

    result, provider = _run(scenario())
    assert text == ["reply"]
    assert result.reason == meme.SKIP_DISABLED
    assert provider.calls == []
    assert result.as_dict()["blocks_text_initiative"] is False


def test_initiative_off_stops_memes(tmp_path):
    provider = _Provider()

    async def scenario():
        return await meme.consider_chat(
            None, -100,
            settings=_settings(),
            ledger=_ledger(tmp_path),
            initiative_enabled=lambda: False,
            image_status=IMAGE_OK,
            image_provider=provider,
            random_source=_Hit(),
            messages=_rows(-100),
            model_chars=200)

    result = _run(scenario())
    assert result.reason == meme.SKIP_INITIATIVE_DISABLED
    assert provider.calls == []
    src = inspect.getsource(obs.InitiativeObserverRunner.run)
    assert src.index("observer_enabled") < src.index("_meme_phase")


def test_meme_phase_failure_does_not_raise():
    runner = obs.InitiativeObserverRunner.__new__(obs.InitiativeObserverRunner)
    runner._db = None
    runner._llm = None
    runner._bot = None

    async def boom(*_a, **_k):
        raise RuntimeError("meme down")

    async def scenario():
        original = meme.on_initiative_cycle
        meme.on_initiative_cycle = boom
        try:
            await runner._meme_phase({"chats": {-100: {}}})
        finally:
            meme.on_initiative_cycle = original

    _run(scenario())


# ── 2. квантовый контур, без тихого random ──────────────────────────────────

def test_purpose_is_sanctioned_extension_not_exploration():
    assert mrs.PURPOSE_MEME_TRIGGER == "meme_trigger"
    assert mrs.purpose_sanctioned(mrs.PURPOSE_MEME_TRIGGER)
    assert mrs.PURPOSE_MEME_TRIGGER not in mrs.EXPLORATION_PURPOSES
    assert mrs.PURPOSE_MEME_TRIGGER not in mx.PURPOSES_10B
    assert "import random" not in inspect.getsource(meme)


def test_random_unavailable_is_recorded_not_masked(tmp_path, monkeypatch):
    def explode():
        raise AssertionError("silent random fallback")

    monkeypatch.setattr(random, "random", explode)
    called = {"summary": 0}

    async def summarizer(*_a, **_k):
        called["summary"] += 1
        return "хук"

    # второй вызов со своим ledger — проще двумя корутинами
    async def both():
        down = _Hit(deferred=True)
        missing = _Hit(missing=True)
        # INIT-COORD §2: значение из fallback-пути — ДЕЙСТВИТЕЛЬНОЕ решение
        # (владелец разрешил `memory.random_fallback_to_pseudorandom`), а не
        # отказ: мем публикуется, фактический источник честно в трассировке.
        fallback = _Hit(value=0.0, fallback="provider_unavailable")
        a, provider, _ = await _consider(
            tmp_path, source=down, summarizer=summarizer)
        (tmp_path / "b").mkdir()
        (tmp_path / "c").mkdir()
        b, _, _ = await _consider(
            tmp_path / "b", source=missing, summarizer=summarizer)
        c, _, _ = await _consider(
            tmp_path / "c", source=fallback, summarizer=summarizer,
            gate=lambda _cid: _async_pair(True, "ok"), sender=None)
        return a, b, c, provider, down

    a, b, c, provider, down = _run(both())
    assert a.reason == meme.SKIP_RANDOM_UNAVAILABLE
    assert b.reason == meme.SKIP_RANDOM_UNAVAILABLE
    # Fallback — не отказ: генерация состоялась, причина не random_unavailable.
    assert c.reason != meme.SKIP_RANDOM_UNAVAILABLE
    assert c.generated is True
    trace = c.stage_facts[meme.STAGE_ELIGIBLE]["random"]
    assert trace["source"] == "pseudorandom"
    assert trace["fallback_reason"] == "provider_unavailable"
    assert trace["hit"] is True and trace["value"] == 0.0
    assert provider.calls == []
    assert called["summary"] == 1
    assert down.kwargs["purpose"] == mrs.PURPOSE_MEME_TRIGGER


def test_random_miss_is_logged(tmp_path):
    async def summarizer(*_a, **_k):
        raise AssertionError("summary after miss")

    result, provider, _ = _run(_consider(
        tmp_path, source=_Hit(value=0.9),
        settings=_settings(trigger_probability=0.05),
        summarizer=summarizer))
    assert result.reason == meme.SKIP_RANDOM_MISS
    assert provider.calls == []
    snap = meme.analytics_snapshot(None, chat_id=-100)
    assert snap["skip_reasons"].get(meme.SKIP_RANDOM_MISS) == 1


# ── 3. один чат, окно настраивается ─────────────────────────────────────────

def test_window_is_configurable_and_chats_do_not_mix(tmp_path):
    seen = []

    async def reader(chat_id, limit):
        seen.append((chat_id, limit))
        return _rows(chat_id, n=limit)

    async def scenario():
        led = _ledger(tmp_path)
        await _consider(tmp_path, -100, reader=reader, messages=None,
                        settings=_settings(window_messages=17, min_messages=1),
                        ledger=led, gate=(lambda _c: _async_pair(False, "x")),
                        sender=None)
        await _consider(tmp_path, -200, reader=reader, messages=None,
                        settings=_settings(window_messages=9, min_messages=1),
                        ledger=led, gate=(lambda _c: _async_pair(False, "x")))
        return led

    _run(scenario())
    assert seen == [(-100, 17), (-200, 9)]
    assert "chat_id = ?" in meme.WINDOW_SQL
    assert meme.DEFAULT_WINDOW_MESSAGES == 500
    assert meme.MemeSettings().window_messages == 500


async def _async_pair(ok, reason):
    return ok, reason


# ── 4. потолок относится к итоговому prompt, а не к выжимке ─────────────────

def test_length_budget_goes_to_joke_stage_not_summarizer(tmp_path):
    """Этап A не получает числовой цели; J = L - T уходит этапу B."""
    seen = {}
    order = []

    async def summarizer(_cid, _rows, system):
        order.append("summary")
        seen["system"] = system
        return "хук"

    async def joke_generator(_cid, summary, instruction):
        order.append("joke")
        seen["summary"] = summary
        seen["instruction"] = instruction
        return "прикол"

    provider = _Provider()

    async def wrapped(prompt, chat_id, job_id):
        order.append("provider")
        return await provider(prompt, chat_id, job_id)

    result, _, _ = _run(_consider(
        tmp_path, summarizer=summarizer, joke_generator=joke_generator,
        provider=wrapped, model_chars=80,
        gate=lambda _cid: _async_pair(False, "recheck_demoted")))
    expected = 80 - (len(PREFIX) + 1)          # T: шаблон + пробел
    assert order == ["summary", "joke", "provider"]
    assert seen["system"] == meme.MEME_SUMMARY_SYSTEM_PROMPT
    assert seen["summary"] == "хук"
    assert f"не более {expected} символов" in seen["instruction"]
    assert result.reason == meme.SKIP_PUBLISH
    assert result.limit.source == "model_capability"
    assert result.limit.ceiling == 80
    assert result.limit.template_chars == len(PREFIX) + 1
    assert result.limit.joke_budget == expected
    assert result.prompt == f"{PREFIX} прикол"
    assert result.prompt_origin == "factory"


def test_long_summary_is_not_truncated_and_feeds_joke_whole(tmp_path):
    """Выжимка длиннее старого потолка доходит до этапа B целиком."""
    long_summary = "маркер-выжимки " * 200
    seen = {}

    async def summarizer(_cid, _rows, _system):
        return long_summary

    async def joke_generator(_cid, summary, _instruction):
        seen["summary"] = summary
        return "прикол"

    sent = []

    async def sender(chat_id, content, prompt):
        sent.append((chat_id, content, prompt))

    provider = _Provider()
    result, _, led = _run(_consider(
        tmp_path, summarizer=summarizer, joke_generator=joke_generator,
        provider=provider, model_chars=80,
        gate=lambda _cid: _async_pair(True, "ok"), sender=sender))
    assert seen["summary"] == long_summary.strip()
    assert len(seen["summary"]) > 80
    assert result.reason == "sent"
    assert len(sent) == 1 and sent[0][0] == -100
    assert provider.calls and provider.calls[0][0] == f"{PREFIX} прикол"
    assert led.spent(-100, "2026-10-30") == 1


def test_length_source_is_explicit():
    limit = meme.resolve_meme_budget(
        model_chars=400, admin=120, explicit=90, template=PREFIX)
    assert limit.source == "explicit_override"
    assert limit.ceiling == 90
    admin = meme.resolve_meme_budget(
        model_chars=400, admin=120, explicit=None, template=PREFIX)
    assert admin.source == "admin_setting"
    unknown = meme.resolve_meme_budget(
        model_chars=None, admin=None, explicit=None, template=PREFIX)
    # P0.5 (§1.4.1): пустой потолок = РЕЖИМ АВТО, а не «неизвестный лимит»:
    # числа нет, генерация не блокируется, `0` наружу не выдаётся за бюджет.
    assert unknown.known is False and unknown.source == "auto"
    assert unknown.mode == "auto"
    assert unknown.joke_budget == 0
    assert unknown.as_dict()["joke_budget"] is None
    assert unknown.as_dict()["ceiling"] is None


# ── 5. заводской prompt дословно и через реестр ─────────────────────────────

def test_factory_prompt_is_exact_literal_and_registered():
    assert meme.MEME_IMAGE_PROMPT == PREFIX
    assert pr.factory_text(meme.IMAGE_PROMPT_BLOCK_ID) == PREFIX
    view = meme.active_prompt_view(meme.IMAGE_PROMPT_BLOCK_ID)
    assert view["text"] == PREFIX
    assert view["differs_from_factory"] is False
    edited = meme.active_prompt_view(
        meme.IMAGE_PROMPT_BLOCK_ID, override="Свой префикс:")
    assert edited["differs_from_factory"] is True
    assert edited["text"] == "Свой префикс:"
    assert pr.FACTORY_REVISION_SEALS[meme.IMAGE_PROMPT_BLOCK_ID][0] == \
        "meme-image-evol014"
    assert pr.block(meme.SUMMARY_PROMPT_BLOCK_ID) is not None
    problems = pr.audit_unregistered_prompt_constants(
        pathlib.Path(__file__).resolve().parent.parent)
    assert problems == []


def test_manual_prefix_is_used_and_marked(tmp_path):
    async def gate(_cid):
        return False, "recheck_demoted"

    result, provider, _ = _run(_consider(
        tmp_path, gate=gate, prompt_override="Другая инструкция:"))
    assert result.prompt.startswith("Другая инструкция: ")
    assert not result.prompt.startswith(PREFIX)
    assert result.prompt_origin == "custom"
    assert provider.calls and provider.calls[0][0].startswith(
        "Другая инструкция: ")


# ── 6. image-зависимость с конкретной причиной ──────────────────────────────

@pytest.mark.parametrize("reason", [
    meme.SKIP_IMAGE_MODULE_OFF,
    meme.SKIP_IMAGE_NOT_CONFIGURED,
    meme.SKIP_IMAGE_UNHEALTHY,
])
def test_image_dependency_reason_blocks_before_provider(tmp_path, reason):
    provider = _Provider()
    result, _, led = _run(_consider(
        tmp_path, provider=provider,
        image_status={"available": False, "reason": reason}))
    assert result.reason == reason
    assert provider.calls == []
    assert led.spent(-100, "2026-10-30") == 0


# ── 7–8. аналитика отдельно; publish-гейт не шлёт ───────────────────────────

def test_publish_gate_blocks_delivery_and_records_reason(tmp_path):
    sent = []

    async def sender(*args):
        sent.append(args)

    async def gate(_cid):
        return False, "recheck_demoted"

    result, provider, _ = _run(_consider(
        tmp_path, gate=gate, sender=sender))
    assert result.generated is True
    assert result.published is False
    assert result.reason == meme.SKIP_PUBLISH
    assert result.detail == "recheck_demoted"
    assert sent == []
    assert len(provider.calls) == 1


def test_analytics_are_separate_from_initiative(tmp_path):
    async def gate(_cid):
        return False, "recheck_demoted"

    _run(_consider(tmp_path, gate=gate))
    led = meme.SqliteQuotaLedger(str(tmp_path / "meme.db"))
    snap = meme.analytics_snapshot(led, chat_id=-100)
    assert snap["output_kind"] == meme.OUTPUT_KIND
    assert snap["separate_from_initiative"] is True
    assert snap["coverage"] == "durable"
    assert "delivered" not in snap["counters"]
    assert snap["counters"][meme.STAGE_IMAGE] == 1
    assert snap["counters"][meme.STAGE_PUBLISH] == 1
    assert snap["skip_reasons"][meme.SKIP_PUBLISH] == 1
    assert obs.reason_label(meme.SKIP_PUBLISH) != meme.SKIP_PUBLISH


def test_sender_not_bound_does_not_send(tmp_path):
    async def gate(_cid):
        return True, "ok"

    result, provider, _ = _run(_consider(tmp_path, gate=gate, sender=None))
    assert result.published is False
    assert result.reason == meme.SKIP_PUBLISH
    assert result.generated is True
    assert len(provider.calls) == 1


# ── 10–11. квота ────────────────────────────────────────────────────────────

def _reserve(led, chat_id, job, limit, bucket="2026-10-30", now_ts=1_700_000_000):
    return led.reserve(chat_id=chat_id, day_bucket=bucket, job_id=job,
                       limit=limit, tz_name="UTC", tz_source="utc_fallback",
                       now_ts=now_ts)


def test_quota_default_three_zero_disables_and_midday_limit(tmp_path):
    assert meme.DEFAULT_DAILY_LIMIT == 3
    led = _ledger(tmp_path)
    assert _reserve(led, -1, "a", 0).ok is False
    assert led.spent(-1, "2026-10-30") == 0
    assert _reserve(led, -1, "b", 3).ok is True
    assert _reserve(led, -1, "c", 3).ok is True
    denied = _reserve(led, -1, "d", 1)
    assert denied.ok is False
    assert denied.reason == meme.SKIP_QUOTA
    assert led.spent(-1, "2026-10-30") == 2
    other = _reserve(led, -2, "e", 3)
    assert other.ok is True
    assert led.spent(-2, "2026-10-30") == 1
    assert led.spent(-1, "2026-10-30") == 2


def test_retry_same_job_does_not_double_count(tmp_path):
    led = _ledger(tmp_path)
    first = _reserve(led, -1, "job-1", 3)
    second = _reserve(led, -1, "job-1", 3)
    assert first.ok and first.already is False
    assert second.ok and second.already is True
    assert led.spent(-1, "2026-10-30") == 1
    reopened = meme.SqliteQuotaLedger(str(tmp_path / "meme.db"))
    assert reopened.spent(-1, "2026-10-30") == 1


def test_day_boundary_and_timezone_label():
    late_utc = datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)
    moscow = meme.day_window(-1, late_utc, tz_name="Europe/Moscow",
                             tz_source="chat")
    utc = meme.day_window(-1, late_utc, tz_name="UTC",
                          tz_source="utc_fallback")
    assert moscow.bucket == "2026-10-31"
    assert moscow.timezone_source == "chat"
    assert utc.bucket == "2026-10-30"
    assert utc.timezone_source == "utc_fallback"
    assert "UTC" in utc.timezone_name


def test_new_day_bucket_resets_spent_slots(tmp_path):
    led = _ledger(tmp_path)
    for i in range(3):
        assert _reserve(led, -1, f"d0-{i}", 3, bucket="2026-10-30").ok
    assert led.spent(-1, "2026-10-30") == 3
    assert _reserve(led, -1, "d0-x", 3, bucket="2026-10-30").ok is False
    assert _reserve(led, -1, "d1-0", 3, bucket="2026-10-31").ok is True
    assert led.spent(-1, "2026-10-31") == 1
    assert led.spent(-1, "2026-10-30") == 3


def test_concurrent_workers_cannot_exceed_cap(tmp_path):
    led = _ledger(tmp_path)

    def one(i):
        return led.reserve(
            chat_id=-7, day_bucket="2026-10-30", job_id=f"w-{i}",
            limit=3, tz_name="Europe/Moscow", tz_source="chat",
            now_ts=1_700_000_000 + i)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(8)))
    oks = [item for item in results if item.ok]
    assert len(oks) == 3
    assert led.spent(-7, "2026-10-30") == 3
    # второй чат в том же залпе не теряет свою квоту
    def other(i):
        return led.reserve(
            chat_id=-8, day_bucket="2026-10-30", job_id=f"o-{i}",
            limit=3, tz_name="UTC", tz_source="utc_fallback",
            now_ts=1_700_000_100 + i)

    with ThreadPoolExecutor(max_workers=6) as pool:
        other_results = list(pool.map(other, range(6)))
    assert sum(1 for item in other_results if item.ok) == 3
    assert led.spent(-8, "2026-10-30") == 3
    assert led.spent(-7, "2026-10-30") == 3


def test_zero_and_exhausted_quota_skip_before_provider(tmp_path):
    called = {"summary": 0, "provider": 0}

    async def summarizer(*_a, **_k):
        called["summary"] += 1
        return "хук"

    provider = _Provider()

    async def scenario():
        led = _ledger(tmp_path)
        zero, _, _ = await _consider(
            tmp_path, settings=_settings(daily_limit=0), ledger=led,
            summarizer=summarizer, provider=provider)
        for i in range(3):
            _reserve(led, -100, f"filled-{i}", 3)
        full, _, _ = await _consider(
            tmp_path, settings=_settings(daily_limit=3), ledger=led,
            summarizer=summarizer, provider=provider)
        return zero, full

    zero, full = _run(scenario())
    assert zero.reason == meme.SKIP_QUOTA
    assert full.reason == meme.SKIP_QUOTA
    assert called["summary"] == 0
    assert provider.calls == []


def test_failed_provider_call_consumes_slot(tmp_path):
    provider = _Provider(ok=False, reason="timeout")
    result, _, led = _run(_consider(tmp_path, provider=provider))
    assert result.reason == meme.SKIP_IMAGE_FAILED
    assert result.generated is False
    assert led.spent(-100, "2026-10-30") == 1
    counts = led.status_counts(-100, "2026-10-30")
    assert counts.get("provider_failed") == 1


def test_schema_absent_is_honest_disabled(tmp_path):
    provider = _Provider()

    async def scenario():
        return await meme.consider_chat(
            None, -100,
            settings=_settings(),
            ledger=None,
            initiative_enabled=lambda: True,
            image_status=IMAGE_OK,
            image_provider=provider,
            random_source=_Hit(),
            messages=_rows(-100),
            model_chars=200)

    result = _run(scenario())
    assert result.reason == meme.SKIP_SCHEMA
    assert provider.calls == []
    note = meme.schema_integration_note()
    assert "40" in note
    assert meme.SCHEMA_VERSION_TARGET == 40
    # Шаг v40 зарегистрирован; DDL живёт в модуле-владельце и НЕ дублируется
    # текстом в database.py (одна схема — один владелец).
    db_text = (pathlib.Path(__file__).resolve().parent.parent
               / "services" / "database.py").read_text(encoding="utf-8")
    assert "meme.SCHEMA_DDL_SQLITE" in db_text
    assert f"CREATE TABLE IF NOT EXISTS {meme.RESERVATION_TABLE}" not in db_text
    assert f"CREATE TABLE IF NOT EXISTS {meme.ATTEMPT_TABLE}" not in db_text


def test_cooldown_and_low_activity_before_provider(tmp_path):
    led = _ledger(tmp_path)
    reserved = _reserve(led, -100, "prev", 3, now_ts=int(NOW.timestamp()) - 10)
    assert reserved.ok
    led.mark("prev", "provider_called")

    async def summarizer(*_a, **_k):
        raise AssertionError("should not summarize")

    cooled, provider, _ = _run(_consider(
        tmp_path, ledger=led, settings=_settings(cooldown_seconds=3600),
        summarizer=summarizer))
    assert cooled.reason == meme.SKIP_COOLDOWN
    assert provider.calls == []

    async def reader(_cid, _limit):
        return _rows(-100, n=1)

    (tmp_path / "act").mkdir()
    quiet, _, _ = _run(_consider(
        tmp_path / "act", reader=reader, messages=None,
        settings=_settings(min_messages=4, window_messages=8),
        summarizer=summarizer))
    assert quiet.reason == meme.SKIP_ACTIVITY


def test_in_flight_serializes_same_chat(tmp_path):
    led = _ledger(tmp_path)
    assert _reserve(led, -5, "live", 3, now_ts=1_700_000_000).ok
    assert led.fresh_inflight(-5, 1_700_000_010) is True
    assert led.spent(-5, "2026-10-30") == 1
    assert led.fresh_inflight(-5, 1_700_000_000 + 1000) is False
    assert _reserve(led, -5, "later", 3, now_ts=1_700_000_000 + 1000).ok
    assert led.spent(-5, "2026-10-30") == 2


def test_quota_view_labels_timezone_and_remaining(tmp_path):
    led = _ledger(tmp_path)
    _reserve(led, -3, "q1", 3)
    day = meme.day_window(-3, NOW, tz_name="UTC", tz_source="utc_fallback")
    # bucket of NOW utc noon is 2026-10-30, same as _reserve default
    view = meme.quota_view(led, chat_id=-3, day=day, limit=3)
    assert view["spent"] == 1
    assert view["remaining"] == 2
    assert view["limit"] == 3
    assert view["timezone_source"] == "utc_fallback"
    assert view["next_reset"]


# ── 12. мост «цикл инициативы → мем» подключён к реальному конвейеру ───────

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeWindowDB:
    """Мини-db для живого пути: путь SQLite + окно сообщений."""

    def __init__(self, path, rows):
        self.db_path = str(path)
        self._rows = [dict(row) for row in rows]

    async def execute(self, _sql, params=()):
        if not params:
            return _FakeCursor(list(self._rows))
        chat_id, limit = int(params[0]), int(params[-1])
        rows = [row for row in self._rows
                if int(row.get("chat_id", chat_id)) == chat_id]
        return _FakeCursor(rows[:limit])


class _FakeLLM:
    def __init__(self, text="мемный хук", *, _chat_model="chat-model"):
        self.text = text
        self._chat_model = _chat_model
        self.calls: list[tuple[list, dict]] = []

    async def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.text


def _wire_live_pipeline(monkeypatch, tmp_path, led, *, llm=None,
                        provider_calls=None):
    """Подменяет только платные/внешние границы; мост остаётся настоящим."""
    llm = llm if llm is not None else _FakeLLM()
    provider_calls = provider_calls if provider_calls is not None else []

    async def _settings_loader(_chat_id=None):
        return _settings(window_messages=50, min_messages=1)

    async def _image_dependency(_chat_id, health=None):
        return dict(IMAGE_OK)

    async def _model_chars():
        return 200

    async def _random_source(_db):
        return _Hit(value=0.0)

    async def _image(prompt, chat_id, job_id):
        provider_calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=True, called=True, reason="", content=b"png")

    async def _gate(_db, _chat_id, _now_ts):
        return True, "ok"

    monkeypatch.setattr(meme, "load_settings", _settings_loader)
    monkeypatch.setattr(meme, "image_dependency", _image_dependency)
    monkeypatch.setattr(meme, "model_prompt_chars", _model_chars)
    monkeypatch.setattr(meme, "default_random_source", _random_source)
    monkeypatch.setattr(meme, "_default_image", _image)
    monkeypatch.setattr(meme, "_default_publish_gate", _gate)
    db = _FakeWindowDB(led.path, _rows(-100, n=6))
    return llm, provider_calls, db


def _runner(db, llm):
    runner = obs.InitiativeObserverRunner.__new__(obs.InitiativeObserverRunner)
    runner._db = db
    runner._llm = llm
    runner._bot = None
    return runner


def test_meme_phase_runs_real_pipeline_and_journals_stages(
        tmp_path, monkeypatch):
    """Без заглушки on_initiative_cycle: фаза реально доходит до генерации."""
    led = _ledger(tmp_path)
    llm, provider_calls, db = _wire_live_pipeline(monkeypatch, tmp_path, led)
    payload = {"chats": {-100: {}}}

    _run(_runner(db, llm)._meme_phase(payload))

    attempts = payload["meme"]["attempts"]
    assert [item["chat_id"] for item in attempts] == [-100]
    assert attempts[0]["stage"] == meme.STAGE_PUBLISH
    assert attempts[0]["reason"] == meme.SKIP_PUBLISH
    assert attempts[0]["detail"] == "publisher_not_bound"
    assert attempts[0]["generated"] is True

    rows = led.attempts(-100)
    stages = {row["stage"] for row in rows}
    assert {meme.STAGE_SUMMARY, meme.STAGE_JOKE, meme.STAGE_IMAGE} <= stages
    assert meme.STAGE_CONSIDERED in stages and meme.STAGE_ELIGIBLE in stages
    reasons = {row["reason_code"] for row in rows if row["reason_code"]}
    assert meme.SKIP_CYCLE_EXCEPTION not in reasons
    assert meme.SKIP_SUMMARY not in reasons
    assert meme.SKIP_JOKE_FAILED not in reasons
    # Два РАЗНЫХ вызова: выжимка (без потолка) и прикол (с явным лимитом).
    assert len(llm.calls) == 2
    summary_messages, summary_kwargs = llm.calls[0]
    assert summary_kwargs["step"] == "meme_summary"
    assert summary_kwargs["module"] == "initiative"
    summary_body = json.loads(summary_messages[1]["content"])
    assert "target_chars" not in summary_body          # потолок снят с выжимки
    # EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 §4.1 P7/§5.4: внутренний номер
    # сообщения не едет в выжимку мема (её текст становится словами мема и
    # картинкой) — в поле `id` стоит метка прогона, различимость сообщений
    # сохранена порядком и меткой. Строка с id=0 адресации не имеет (R16) —
    # метка пустая, id не выдумывается.
    ids = [item["id"] for item in summary_body["messages"]]
    assert [value for value in ids if value] == [
        f"M{index}" for index in range(1, 6)]
    assert all(not str(value).isdigit() for value in ids)
    joke_messages, joke_kwargs = llm.calls[1]
    assert joke_kwargs["step"] == "meme_joke"
    assert joke_kwargs["module"] == "initiative"
    assert joke_messages[1]["content"] == "мемный хук"   # прикол из выжимки
    expected_j = 200 - (len(PREFIX) + 1)
    assert f"не более {expected_j} символов" in joke_messages[0]["content"]
    assert provider_calls and provider_calls[0][0].startswith(PREFIX + " ")
    snap = meme.analytics_snapshot(led, chat_id=-100)
    assert snap["counters"][meme.STAGE_SUMMARY] == 1
    assert snap["counters"][meme.STAGE_IMAGE] == 1


def test_meme_phase_bridge_exception_is_cycle_exception(tmp_path, monkeypatch):
    """Ошибка моста — отдельная причина, а не «провал выжимки»."""
    led = _ledger(tmp_path)
    llm, _, db = _wire_live_pipeline(monkeypatch, tmp_path, led)

    async def boom(*_a, **_k):
        raise RuntimeError("bridge down")

    monkeypatch.setattr(meme, "consider_chat", boom)
    payload = {"chats": {-100: {}}}
    _run(_runner(db, llm)._meme_phase(payload))

    attempt = payload["meme"]["attempts"][0]
    assert attempt["reason"] == meme.SKIP_CYCLE_EXCEPTION
    assert attempt["detail"] == "RuntimeError"
    assert attempt["stage"] == meme.STAGE_FAILED

    rows = led.attempts(-100)
    assert [row["reason_code"] for row in rows if row["reason_code"]] == [
        meme.SKIP_CYCLE_EXCEPTION]
    snap = meme.analytics_snapshot(led, chat_id=-100)
    assert snap["skip_reasons"] == {meme.SKIP_CYCLE_EXCEPTION: 1}
    assert meme.SKIP_SUMMARY not in snap["skip_reasons"]
    assert obs.reason_label(meme.SKIP_CYCLE_EXCEPTION) != meme.SKIP_CYCLE_EXCEPTION


def test_retry_of_released_slot_is_not_daily_quota(tmp_path):
    """Повтор снятой брони — slot_released; квота при этом не «исчерпана»."""
    led = _ledger(tmp_path)
    assert _reserve(led, -100, "rel-1", 3, now_ts=int(NOW.timestamp())).ok
    led.mark("rel-1", "released", "not_called")
    assert led.status_counts(-100, "2026-10-30").get("released") == 1

    async def summarizer(*_a, **_k):
        return "хук"

    result, provider, _ = _run(_consider(
        tmp_path, ledger=led, summarizer=summarizer, job_id="rel-1"))
    assert result.reason == meme.SKIP_SLOT_RELEASED
    assert result.reason != meme.SKIP_QUOTA
    assert result.detail == "job_released"
    assert provider.calls == []
    assert led.spent(-100, "2026-10-30") == 0
    assert obs.reason_label(meme.SKIP_SLOT_RELEASED) != meme.SKIP_SLOT_RELEASED


def test_default_summarizer_matches_real_client_contract(monkeypatch):
    """Легкая выжимка совпадает по контракту с НАСТОЯЩИМ LLM-клиентом.

    Фейковый llm не поймал бы дрейф сигнатуры, из-за которого живой путь
    падал на TypeError. Транспорт подменён, сеть не используется.
    """
    from services.llm_client import LLMClient

    client = LLMClient("https://llm.example.invalid/v1", "sk-test",
                       "chat-model", "")
    seen: dict = {}

    class _Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "  хук  "}}]}

    async def _post(path, payload, **_kwargs):
        seen["path"] = path
        seen["payload"] = payload
        return _Response()

    monkeypatch.setattr(client, "_post", _post)
    summary = _run(meme._default_summarize(
        client, _rows(-100, 2), "система", chat_id=-100,
        model="другая-модель"))

    assert summary == "хук"
    assert seen["path"] == "/chat/completions"
    assert seen["payload"]["messages"][0] == {
        "role": "system", "content": "система"}
    body = json.loads(seen["payload"]["messages"][1]["content"])
    assert "target_chars" not in body        # у выжимки больше нет потолка
    assert [item["id"] for item in body["messages"]] == [0, 1]
    # Модель задаётся общим клиентом: подмены на одну выжимку нет.
    assert seen["payload"]["model"] == "chat-model"


def test_default_joke_matches_real_client_contract(monkeypatch):
    """Этап B тем же клиентом: задание в system, выжимка в user.

    MEME-JOKE-SPEECH: system собирает единый речевой композер, поэтому
    сообщение НАЧИНАЕТСЯ с задания и содержит J-директиву, а не равно ей
    (речевые слои владельца дописываются после задания). Возврат этапа —
    ``(текст прикола, диагностика сборки)``.
    """
    from services.llm_client import LLMClient

    client = LLMClient("https://llm.example.invalid/v1", "sk-test",
                       "chat-model", "")
    seen: dict = {}

    class _Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "  прикол  "}}]}

    async def _post(path, payload, **_kwargs):
        seen["path"] = path
        seen["payload"] = payload
        return _Response()

    monkeypatch.setattr(client, "_post", _post)
    joke, speech = _run(meme._default_joke(
        client, "выжимка целиком",
        instruction=meme.joke_instruction(meme.MEME_JOKE_PROMPT, 42),
        chat_id=-100))

    assert joke == "прикол"
    assert seen["path"] == "/chat/completions"
    system_message = seen["payload"]["messages"][0]
    assert system_message["role"] == "system"
    assert system_message["content"].startswith(
        meme.joke_instruction(meme.MEME_JOKE_PROMPT, 42))
    assert seen["payload"]["messages"][1] == {
        "role": "user", "content": "выжимка целиком"}
    assert "не более 42 символов" in system_message["content"]
    assert seen["payload"]["model"] == "chat-model"
    # Сборка состоялась (композер fail-open не сработал) и связана с payload.
    assert speech["composer"] == "on"
    assert speech["system_sha12"] == hashlib.sha256(
        system_message["content"].encode("utf-8")).hexdigest()[:12]


def test_in_flight_check_precedes_paid_summary(tmp_path):
    """Свежая чужая бронь отсекает попытку ДО платной выжимки."""
    led = _ledger(tmp_path)
    assert _reserve(led, -100, "live", 3, now_ts=int(NOW.timestamp()) - 30).ok
    called = {"summary": 0}

    async def summarizer(*_a, **_k):
        called["summary"] += 1
        return "хук"

    result, provider, _ = _run(_consider(
        tmp_path, ledger=led, summarizer=summarizer))
    assert result.reason == meme.SKIP_IN_FLIGHT
    assert called["summary"] == 0
    assert provider.calls == []


# ── 13. шаг схемы v40 в реальном DatabaseService (интеграция, не заметка) ──

def test_v40_step_registered_and_ddl_owned_by_module():
    """Шаг v40 существует в раннере, DDL — у модуля-владельца, PG не обещан."""
    from services.database import DatabaseService, _SCHEMA_VERSION_MEME_QUOTA
    from services import pg_db

    steps = {s.version: s.name for s in DatabaseService.migration_steps()}
    assert steps.get(40) == meme.SCHEMA_MIGRATION_STEP_NAME
    assert steps.get(40) == "meme_quota_journal_v40"
    assert steps.get(39) == "prompt_revision_journal_v39"   # сосед не сдвинут
    assert steps.get(38) == "quote_metadata_v38"
    assert _SCHEMA_VERSION_MEME_QUOTA == meme.SCHEMA_VERSION_TARGET == 40
    assert callable(DatabaseService._migrate_meme_quota_v40)
    # Журнала квоты на PostgreSQL нет: пустые PG-таблицы никто не читает.
    assert all(
        meme.RESERVATION_TABLE not in stmt and meme.ATTEMPT_TABLE not in stmt
        for stmt in pg_db.DDL_STATEMENTS)


@pytest.mark.asyncio
async def test_fresh_db_migrates_to_v41_with_quota_and_claim_tables(tmp_path):
    from services import publication_coordination as pub
    from services.database import (DatabaseService,
                                   _SCHEMA_VERSION_PUBLISH_CLAIM)

    svc = DatabaseService(str(tmp_path / "v40_fresh.db"))
    await svc.initialize()
    try:
        latest = max(s.version for s in DatabaseService.migration_steps())
        cur = await svc.db.execute("PRAGMA user_version")
        # UNIFIED-REPLY UR-C-SCHED (06.11.2026, 1ca13926, уже в 2.58.161):
        # хвост схемы 41 -> 42 (аддитивная slot_claims_v42, PG no-op).
        # MEMORY-02 (2.58.163): хвост 42 -> 43 (аддитивная mca_entity_canonical).
        # MEMORY-07 (contracts §5.1): хвост 43 -> 44 (mca_community_builds /
        # mca_community_members, аддитивно, PG no-op).
        # VMQ-V (VOICE-01 P0, 09.11.2026): хвост 44 -> 45 (версия расшифровки
        # голосового source-ref в smart_messages, аддитивно, PG no-op).
        # MOD-ACL-UX-01 amendment (09.11.2026): хвост 45 -> 46 (семантический
        # контракт уроков, аддитивно, PG no-op).
        assert (await cur.fetchone())[0] == latest == 47
        assert _SCHEMA_VERSION_PUBLISH_CLAIM == 41
        book = await svc.db.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = 40")
        row = await book.fetchone()
        assert row is not None
        assert row["name"] == "meme_quota_journal_v40"
        assert row["checksum"]
        cur = await svc.db.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = 41")
        row = await cur.fetchone()
        assert row is not None
        assert row["name"] == pub.CLAIM_MIGRATION_STEP_NAME
        assert row["checksum"]
        cur = await svc.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN (?, ?, ?)", (meme.RESERVATION_TABLE,
                                      meme.ATTEMPT_TABLE, pub.CLAIM_TABLE))
        assert {r["name"] for r in await cur.fetchall()} == {
            meme.RESERVATION_TABLE, meme.ATTEMPT_TABLE, pub.CLAIM_TABLE}
        cur = await svc.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
            "('idx_meme_reservation_chat_day', 'idx_meme_attempt_chat_ts')")
        assert len(await cur.fetchall()) == 2
        # Настоящий признак готовности: журнал открывается на реальной БД.
        led = meme.open_ledger(svc)
        assert led is not None and led.table_present() is True
        store = pub.open_store(svc)
        assert store is not None and store.table_present() is True
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_v39_db_upgrades_to_v40_without_data_loss(tmp_path):
    from services import message_identity as mi
    from services import publication_coordination as pub
    from services.database import DatabaseService

    path = str(tmp_path / "v39_upgrade.db")

    class _EraDB(DatabaseService):
        @staticmethod
        def migration_steps():
            return [s for s in DatabaseService.migration_steps()
                    if s.version < 40]

    old = _EraDB(path)
    await old.initialize()
    try:
        cur = await old.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 39
        # До шага журнала квоты нет — и это честный schema_absent, а не тишина.
        assert meme.open_ledger(old) is None
        assert pub.open_store(old).table_present() is False
        await mi.save_live_message(old, chat_id=-100, user_id=1,
                                   text="до-v40-строка", tg_message_id=11)
        cur = await old.db.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 39")
        checksum_39 = (await cur.fetchone())["checksum"]
    finally:
        await old.close()

    svc = DatabaseService(path)
    await svc.initialize()
    try:
        latest = max(s.version for s in DatabaseService.migration_steps())
        cur = await svc.db.execute("PRAGMA user_version")
        # UNIFIED-REPLY UR-C-SCHED (1ca13926): хвост схемы 41 -> 42.
        # MEMORY-02 (2.58.163): хвост 42 -> 43 (mca_entity_canonical).
        # MEMORY-07 (contracts §5.1): хвост 43 -> 44 (mca_community_*).
        # VMQ-V (09.11.2026): хвост 44 -> 45 (версия расшифровки голоса).
        # MOD-ACL-UX-01 amendment (09.11.2026): хвост 45 -> 46 (семантический
        # контракт уроков, аддитивно, PG no-op).
        assert (await cur.fetchone())[0] == latest == 47
        cur = await svc.db.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 39")
        assert (await cur.fetchone())["checksum"] == checksum_39
        cur = await svc.db.execute(
            "SELECT name FROM schema_migrations WHERE version = 40")
        assert (await cur.fetchone())["name"] == "meme_quota_journal_v40"
        cur = await svc.db.execute(
            "SELECT name FROM schema_migrations WHERE version = 41")
        assert (await cur.fetchone())["name"] == pub.CLAIM_MIGRATION_STEP_NAME
        row = await svc.get_smart_message_by_tg_id(-100, 11)
        assert row is not None and row["text"] == "до-v40-строка"
        led = meme.open_ledger(svc)
        assert led is not None
        # Журнал добавлен пустым: расхода до миграции не выдумывается.
        assert led.spent(-100, "2026-10-30") == 0
        # Бронь добавлена пустой: прошлых публикаций не выдумывается.
        assert pub.open_store(svc).snapshot(-100) == {}
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_real_db_path_publishes_meme_and_journals_quota(tmp_path):
    """Мем реально проходит путь на РЕАЛЬНОЙ БД: окно из БД, бронь в таблице."""
    from services import message_identity as mi
    from services.database import DatabaseService

    svc = DatabaseService(str(tmp_path / "v40_live.db"))
    await svc.initialize()
    try:
        for offset, text in enumerate(("первая реплика", "вторая", "третья")):
            await mi.save_live_message(svc, chat_id=-100, user_id=1,
                                       text=text, tg_message_id=500 + offset)
        led = meme.open_ledger(svc)
        assert led is not None

        provider = _Provider()
        published = []

        async def gate(chat_id):
            return True, "ok"

        async def sender(chat_id, content, caption):
            published.append((chat_id, content, caption))

        async def summarizer(chat_id, rows, system):
            assert len(rows) == 3          # окно прочитано из настоящей таблицы
            return "хук"

        async def joke_generator(chat_id, summary, instruction):
            assert summary == "хук"
            return "прикол"

        result = await meme.consider_chat(
            svc, -100, settings=_settings(), ledger=led, now=NOW,
            tz_name="UTC", tz_source="utc_fallback",
            initiative_enabled=lambda: True, image_status=IMAGE_OK,
            random_source=_Hit(), summarizer=summarizer,
            joke_generator=joke_generator,
            image_provider=provider, publish_gate=gate, sender=sender,
            model_chars=200)

        assert result.published is True and result.reason == "sent"
        assert len(provider.calls) == 1
        assert provider.calls[0][0] == f"{PREFIX} прикол"
        assert len(published) == 1 and published[0][0] == -100
        assert published[0][2] == f"{PREFIX} прикол"   # внутренний аргумент

        cur = await svc.db.execute(
            f"SELECT status FROM {meme.RESERVATION_TABLE} WHERE chat_id = ?",
            (-100,))
        statuses = [r["status"] for r in await cur.fetchall()]
        assert statuses == ["provider_called"]
        cur = await svc.db.execute(
            f"SELECT stage, outcome FROM {meme.ATTEMPT_TABLE} WHERE chat_id = ?",
            (-100,))
        journal = await cur.fetchall()
        stages = {r["stage"] for r in journal}
        assert {"summary", "joke", "image_generation", "publish"} <= stages
        assert "published" in {r["outcome"] for r in journal}
        assert not {r for r in journal if r["outcome"] == "failed"}
        day = meme.day_window(-100, NOW, tz_name="UTC",
                             tz_source="utc_fallback")
        assert led.spent(-100, day.bucket) == 1
        # Второй чат — свой независимый счётчик на той же таблице.
        assert led.spent(-200, day.bucket) == 0

        # Атомарная бронь на реальном файле: кап держится, replay не двоит.
        ledger2 = meme.SqliteQuotaLedger(str(svc.db_path))
        assert ledger2.reserve(chat_id=-300, day_bucket=day.bucket,
                               job_id="cap-1", limit=1, tz_name="UTC",
                               tz_source="utc_fallback",
                               now_ts=int(NOW.timestamp())).ok
        blocked = ledger2.reserve(chat_id=-300, day_bucket=day.bucket,
                                  job_id="cap-2", limit=1, tz_name="UTC",
                                  tz_source="utc_fallback",
                                  now_ts=int(NOW.timestamp()))
        assert blocked.ok is False and blocked.reason == meme.SKIP_QUOTA
        replay = ledger2.reserve(chat_id=-300, day_bucket=day.bucket,
                                 job_id="cap-1", limit=1, tz_name="UTC",
                                 tz_source="utc_fallback",
                                 now_ts=int(NOW.timestamp()))
        assert replay.already is True and ledger2.spent(-300, day.bucket) == 1
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_v40_restart_is_noop_and_keeps_quota_rows(tmp_path, caplog):
    import logging
    from services.database import DatabaseService

    path = str(tmp_path / "v40_restart.db")
    svc = DatabaseService(path)
    await svc.initialize()
    led = meme.open_ledger(svc)
    assert led is not None
    assert led.reserve(chat_id=-7, day_bucket="2026-10-30", job_id="j1",
                       limit=3, tz_name="UTC", tz_source="utc_fallback",
                       now_ts=1_700_000_000).ok
    await svc.close()

    svc2 = DatabaseService(path)
    with caplog.at_level(logging.INFO, logger="services.database"):
        await svc2.initialize()
    try:
        latest = max(s.version for s in DatabaseService.migration_steps())
        cur = await svc2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == latest
        cur = await svc2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version = 40")
        assert (await cur.fetchone())["c"] == 1
        cur = await svc2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version = 41")
        assert (await cur.fetchone())["c"] == 1
        assert "migration v40 applied" not in caplog.text
        led2 = meme.open_ledger(svc2)
        assert led2 is not None
        assert led2.spent(-7, "2026-10-30") == 1   # расход пережил рестарт
    finally:
        await svc2.close()


# ═════════════════════════════════════════════════════════════════════════════
# P0-INIT-MEME-UX-DIAG §3 — СКВОЗНАЯ ИДЕНТИЧНОСТЬ ПОПЫТКИ
# ═════════════════════════════════════════════════════════════════════════════
# TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-11-P0-INIT-MEME-UX-DIAG
# (§3: родитель до первого гейта, режим в detail JSON, дочерние id `{run}#step`).

#: Тот же базис времени, что `NOW` файла (фиксированное время, без sleep).
NOW_TS = int(NOW.timestamp())

def _journal(led, chat_id=-100):
    return led.attempts(chat_id, limit=200)


class _Message:
    def __init__(self, message_id):
        self.message_id = message_id


class _Sender:
    """Шов отправки: возвращает сообщение с id (как боевой transport)."""

    def __init__(self, message_id=900):
        self.calls: list[tuple] = []
        self.message_id = message_id

    async def __call__(self, chat_id, content, prompt):
        self.calls.append((chat_id, content, prompt))
        return _Message(self.message_id)


def _ledger_named(tmp_path, name: str):
    led = meme.SqliteQuotaLedger(str(tmp_path / name))
    led.apply_schema()
    return led


def test_early_refusal_has_its_own_run_id(tmp_path):
    """Отказ ДО генерации — тоже попытка со своим родителем (не пустой id)."""
    led = _ledger(tmp_path)
    provider = _Provider()

    async def scenario():
        return await meme.consider_chat(
            None, -100,
            settings=_settings(),
            ledger=led,
            initiative_enabled=lambda: False,
            image_status=IMAGE_OK,
            image_provider=provider,
            random_source=_Hit(),
            messages=_rows(-100),
            model_chars=200)

    result = _run(scenario())
    assert result.reason == meme.SKIP_INITIATIVE_DISABLED
    assert provider.calls == []
    # Родитель mint'ится ДО первого гейта: ранний отказ его уже несёт.
    assert result.job_id, "ранний отказ обязан иметь run_id"
    rows = _journal(led)
    assert rows, "ранний отказ обязан оставить строку журнала"
    assert {str(row.get("job_id")) for row in rows} == {result.job_id}
    # Одна логическая попытка, а не две (прежний ключ `row:{attempt_id}`).
    from web.api.initiative_publications import _meme_attempts_grouped
    attempts = _meme_attempts_grouped(rows)
    assert len(attempts) == 1, [item["attempt_id"] for item in attempts]
    assert attempts[0]["attempt_id"] == "meme:" + result.job_id
    assert attempts[0]["stage"] == meme.STAGE_SKIPPED


def test_cooldown_quota_quiet_refusals_carry_run_id(tmp_path):
    """Own-гейты (квота/кулдаун/тихие часы) тоже пишут непустой `job_id`."""
    led = _ledger(tmp_path)

    async def quota_refusal():
        # Лимит 0 = мем остановлен лимитом; кулдаун и тихие часы выключены,
        # чтобы отказ пришёл ровно от квоты.
        return await meme.consider_chat(
            None, -100, settings=_settings(daily_limit=0), ledger=led,
            now=NOW, now_ts=NOW_TS, tz_name="UTC", tz_source="utc_fallback",
            initiative_enabled=lambda: True, image_status=IMAGE_OK,
            image_provider=_Provider(), random_source=_Hit(),
            messages=_rows(-100), model_chars=200)

    quota = _run(quota_refusal())
    assert quota.reason == meme.SKIP_QUOTA

    # Успешный проход создаёт last_provider_ts — источник кулдауна.
    ok, _, _ = _run(_consider(tmp_path, ledger=led, sender=_Sender()))
    assert ok.published is True

    async def cooldown_refusal():
        return await meme.consider_chat(
            None, -100, settings=_settings(cooldown_seconds=600), ledger=led,
            now=NOW, now_ts=NOW_TS, tz_name="UTC", tz_source="utc_fallback",
            initiative_enabled=lambda: True, image_status=IMAGE_OK,
            image_provider=_Provider(), random_source=_Hit(),
            messages=_rows(-100), model_chars=200)

    cooldown = _run(cooldown_refusal())
    assert cooldown.reason == meme.SKIP_COOLDOWN

    async def quiet_refusal():
        return await meme.consider_chat(
            None, -100,
            settings=_settings(quiet_hours="00:00-23:59"), ledger=led,
            now=NOW, now_ts=NOW_TS, tz_name="UTC", tz_source="utc_fallback",
            initiative_enabled=lambda: True, image_status=IMAGE_OK,
            image_provider=_Provider(), random_source=_Hit(),
            messages=_rows(-100), model_chars=200)

    quiet = _run(quiet_refusal())
    assert quiet.reason == meme.SKIP_QUIET

    for result in (quota, cooldown, quiet):
        assert result.job_id, result.reason
    rows = _journal(led)
    for result in (quota, cooldown, quiet):
        assert any(str(row.get("job_id")) == result.job_id for row in rows), \
            result.reason
    # Ни одной строки без идентификатора — иначе агрегатор склеит «две попытки».
    assert [row for row in rows if not str(row.get("job_id") or "")] == []


def test_child_llm_calls_are_namespaced_under_the_parent_run(tmp_path):
    """Выжимка и прикол — дочерние шаги ОДНОГО родителя, а не свои run_id."""
    seen: list[str] = []

    class _LLM:
        _chat_model = ""

        async def generate(self, messages, *, temperature=0.0, chat_id=None,
                           module="", step="", correlation_id=""):
            seen.append(str(correlation_id))
            return "прикол" if step == "meme_joke" else "хук"

    control = _ledger(tmp_path)

    async def scenario():
        # Тот же вызов, что у боевого пути: без summarizer/joke_generator,
        # с реальным LLM-клиентом (контракт `generate`).
        return await meme.consider_chat(
            None, -100, settings=_settings(), ledger=control,
            initiative_enabled=lambda: True, image_status=IMAGE_OK,
            llm=_LLM(), image_provider=_Provider(), random_source=_Hit(),
            messages=_rows(-100), model_chars=200)

    result = _run(scenario())
    assert result.job_id
    assert seen, "ни один платный шаг не был вызван"
    assert seen == ["%s#meme_summary" % result.job_id,
                    "%s#meme_joke" % result.job_id], seen


def test_terminal_journal_row_records_attempt_mode(tmp_path):
    """Режим попытки — в detail JSON ТЕРМИНАЛЬНОЙ строки (manual и авто)."""
    manual_led = _ledger_named(tmp_path, "manual.db")
    auto_led = _ledger_named(tmp_path, "auto.db")

    async def manual_run():
        return await meme.consider_chat(
            None, -100, settings=_settings(), ledger=manual_led,
            image_status=IMAGE_OK, image_provider=_Provider(),
            random_source=_Hit(), messages=_rows(-100), model_chars=200,
            manual=True, sender=_Sender(), publish_gate=None)

    manual = _run(manual_run())
    auto, _, _ = _run(_consider(tmp_path, ledger=auto_led, sender=_Sender()))

    manual_row = manual_led.attempts(-100, limit=1)[0]
    auto_row = auto_led.attempts(-100, limit=1)[0]
    manual_facts = meme.parse_attempt_facts(manual_row)
    auto_facts = meme.parse_attempt_facts(auto_row)
    assert manual_facts.get("mode") == meme.MODE_MANUAL
    assert auto_facts.get("mode") == meme.MODE_AUTOMATIC
    # Точный ключ режима попытки не может быть занят бюджетом этапа «прикол».
    assert manual_facts.get("attempt_mode") == meme.MODE_MANUAL
    assert auto_facts.get("attempt_mode") == meme.MODE_AUTOMATIC
    # Режим пишется в СУЩЕСТВУЮЩЕЕ поле detail, схемы не меняем.
    assert set(manual_facts) <= {
        "mode", "attempt_mode", "detail", "events", "publish", "publication",
        "summary", "joke", "image_generation", "eligible"}
    # Ось read-model читает ТУ ЖЕ терминальную строку: этап «прикол» со своим
    # бюджетным `mode=auto` не подменяет режим ручной попытки.
    from services import initiative_diagnostics as diag
    axis = diag._meme_last_attempt(manual_led.attempts(-100, limit=200))
    assert axis["mode"] == diag.MODE_MANUAL, axis
    assert axis["run_id"] == manual.job_id
    assert axis["outcome"] == manual.outcome
    assert manual.manually_triggered is True
    assert auto.manually_triggered is False


# ═════════════════════════════════════════════════════════════════════════════
# Ревью 400021cc, блокер 6 — терминальная попытка не теряется
# ═════════════════════════════════════════════════════════════════════════════
# TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-11-P0-INIT-MEME-UX-DIAG
# (журнал попыток — единственный источник правды витрины; потеря строки
# означала «77 попыток за сутки» вместо 228 реальных).


def _attempt_row(attempt_id="lost-1", *, chat_id=-100, ts=None):
    return {
        "attempt_id": attempt_id,
        "chat_id": chat_id,
        "job_id": "run-1",
        "ts": int(ts if ts is not None else NOW.timestamp()),
        "stage": meme.STAGE_PUBLISH,
        "outcome": "published",
        "reason_code": "sent",
        "detail": '{"mode":"automatic"}',
        "limit_source": "auto",
        "limit_value": 600,
        "window_messages": 12,
    }


def test_attempt_write_is_retried_before_any_fallback(tmp_path, monkeypatch):
    """Транзиентная блокировка: повтор спасает строку, спул не нужен."""
    led = _ledger(tmp_path)
    calls = {"n": 0}
    original = meme.SqliteQuotaLedger._insert_attempt

    def flaky(self, row):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return original(self, row)

    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", flaky)
    led.record_attempt(_attempt_row())

    assert calls["n"] == 2, calls
    assert [row["attempt_id"] for row in led.attempts(-100, limit=5)] == \
        ["lost-1"]
    assert not pathlib.Path(led.pending_path()).exists()


def test_attempt_survives_permanent_journal_failure_via_spool(
        tmp_path, monkeypatch):
    """Журнал недоступен постоянно: строка durable-спулится и ВИДНА читателю."""
    led = _ledger(tmp_path)
    original = meme.SqliteQuotaLedger._insert_attempt

    def broken(self, row):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", broken)
    led.record_attempt(_attempt_row("lost-A"))
    # Дurable-фолбэк: файл рядом с журналом, без новых таблиц.
    assert pathlib.Path(led.pending_path()).exists()
    # Читатель (витрина/аналитика) строку видит, хотя таблица её не приняла.
    rows = led.attempts(-100, limit=5)
    assert [row["attempt_id"] for row in rows] == ["lost-A"]
    assert led.attempts(-101, limit=5) == []      # чужой чат не подмешивается

    # Журнал снова жив: строка переносится в таблицу, спул очищается,
    # дубля нет (INSERT OR IGNORE по attempt_id).
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", original)
    rows = led.attempts(-100, limit=5)
    assert [row["attempt_id"] for row in rows] == ["lost-A"]
    assert not pathlib.Path(led.pending_path()).exists()
    led.record_attempt(_attempt_row("lost-A"))    # повторная запись — no-op
    assert [row["attempt_id"] for row in led.attempts(-100, limit=5)] == \
        ["lost-A"]


def test_spooled_and_journal_rows_are_merged_in_order(tmp_path, monkeypatch):
    """Спул склеивается с таблицей по времени, а не теряется позади."""
    led = _ledger(tmp_path)
    led.record_attempt(_attempt_row("fresh", ts=NOW.timestamp()))
    original = meme.SqliteQuotaLedger._insert_attempt

    def broken(self, row):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", broken)
    led.record_attempt(_attempt_row("newest", ts=NOW.timestamp() + 60))

    rows = led.attempts(-100, limit=5)
    assert [row["attempt_id"] for row in rows] == ["newest", "fresh"]
    # Аналитика видит объединённый журнал, а не только таблицу.
    snapshot = meme.analytics_snapshot(led, chat_id=-100)
    assert int(snapshot["counters"][meme.STAGE_PUBLISH]) == 2, snapshot

    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", original)
    led.attempts(-100, limit=5)
    assert [row["attempt_id"] for row in led.attempts(-100, limit=5)] == \
        ["newest", "fresh"]


def test_spool_flush_never_drops_unread_rows(tmp_path, monkeypatch):
    """Больше одной порции: КАЖДАЯ строка доезжает до таблицы, хвост не теряется."""
    led = _ledger(tmp_path)
    original = meme.SqliteQuotaLedger._insert_attempt
    # Паузы между ретраями — про транзиентную блокировку, а не про логику:
    # в тесте 501 недоступная запись не должна стоить 50 секунд сна.
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())

    def broken(self, row):
        raise sqlite3.OperationalError("database is locked")

    total = meme.ATTEMPT_SPOOL_BATCH * 2 + 101        # 501 при BATCH=200
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", broken)
    for index in range(total):
        led.record_attempt(_attempt_row("spool-%03d" % index,
                                        ts=NOW.timestamp() + index))
    spool_path = pathlib.Path(led.pending_path())
    assert spool_path.exists()
    # Читатель видит строки даже при недоступном журнале (bounded чтение).
    visible = led.attempts(-100, limit=total)
    assert len(visible) == meme.ATTEMPT_SPOOL_MAX_ROWS or len(visible) == total

    # Журнал восстановился: перенос идёт порциями, но НИ ОДНА строка не теряется.
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", original)
    led._flush_pending_attempts()
    assert not spool_path.exists(), "спул должен исчезнуть только после полного переноса"
    conn = sqlite3.connect(str(tmp_path / "meme.db"))
    try:
        cur = conn.execute(
            "SELECT attempt_id FROM meme_initiative_attempt ORDER BY attempt_id")
        in_table = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
    assert len(in_table) == total, (len(in_table), total)
    assert in_table == ["spool-%03d" % index for index in range(total)]


def test_spool_keeps_unread_tail_when_batch_is_limited(tmp_path, monkeypatch):
    """Остаток файла сохраняется, если перенос прерван (журнал снова упал)."""
    led = _ledger(tmp_path)
    original = meme.SqliteQuotaLedger._insert_attempt
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())

    def broken(self, row):
        raise sqlite3.OperationalError("database is locked")

    total = meme.ATTEMPT_SPOOL_BATCH + 5
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", broken)
    for index in range(total):
        led.record_attempt(_attempt_row("keep-%03d" % index,
                                        ts=NOW.timestamp() + index))

    # Один шаг переноса при «полуживом» журнале: вставилась только первая
    # порция, остаток обязан остаться в файле.
    state = {"n": 0}

    def half_broken(self, row):
        state["n"] += 1
        if state["n"] > meme.ATTEMPT_SPOOL_BATCH // 2:
            raise sqlite3.OperationalError("database is locked")
        return original(self, row)

    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", half_broken)
    led._flush_pending_attempts()

    spool_path = pathlib.Path(led.pending_path())
    assert spool_path.exists(), "непрочитанный остаток нельзя удалять"
    with open(spool_path, "r", encoding="utf-8") as handle:
        left = [line for line in handle if line.strip()]
    assert len(left) == total - meme.ATTEMPT_SPOOL_BATCH // 2, len(left)

    # Журнал жив: остаток доезжает полностью, дублей нет.
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", original)
    led._flush_pending_attempts()
    assert not spool_path.exists()
    conn = sqlite3.connect(str(tmp_path / "meme.db"))
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM meme_initiative_attempt")
        assert int(cur.fetchone()[0]) == total
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# architecture-identity.md §1 — инвариант D: совместный отказ журнала и спула
# ═════════════════════════════════════════════════════════════════════════════
# TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-11-P0-INIT-MEME-UX-DIAG
# (RW-D4-BOTH-WRITE-FAIL: содержание терминальной попытки не сводится к
# анонимному предупреждению; строка удерживается процессом, переносится в
# первый освободившийся носитель, иначе её ПОЛНЫЙ payload уходит в лог).


def _publication_row(attempt_id, *, chat_id=-100, ts=None, reason="sent",
                     outcome="published", job_id="run-1"):
    """Строка как её пишет `_finish`: detail несёт режим и факты публикации."""
    detail = json.dumps({
        "attempt_mode": "manual",
        "detail": "sent",
        "publication": {
            "output": {"ledger_id": 7, "tg_message_id": 4321},
            "delivery": "sent",
            "manual": True,
        },
    }, ensure_ascii=False)
    row = _attempt_row(attempt_id, chat_id=chat_id, ts=ts)
    row.update(outcome=outcome, reason_code=reason, detail=detail,
               job_id=job_id)
    return row


def _break_journal(monkeypatch):
    """Журнал недоступен постоянно (диск/права/IO — не транзиентный лок)."""

    def broken(self, row):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt", broken)


def _break_spool(monkeypatch):
    """Спул недоступен: тот же каталог, что у журнала (файловый отказ)."""
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_spool_attempt",
                        lambda self, row: False)
    return True


def test_both_carriers_ok_puts_the_row_in_the_journal_only(tmp_path,
                                                           monkeypatch):
    """Контроль: оба носителя живы — строка в журнале, удержания нет."""
    led = _ledger(tmp_path)
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())

    led.record_attempt(_publication_row("ok-1"))

    assert meme.held_unpersisted(led.path) == []
    assert not pathlib.Path(led.pending_path()).exists()
    assert [row["attempt_id"] for row in led.attempts(-100, limit=5)] == \
        ["ok-1"]


def test_journal_failure_keeps_the_row_in_the_spool_without_holding(
        tmp_path, monkeypatch):
    """Свойство 1: спул работает — строка durable-спулится, удержания нет."""
    led = _ledger(tmp_path)
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())
    _break_journal(monkeypatch)

    led.record_attempt(_publication_row("spooled-A"))

    assert pathlib.Path(led.pending_path()).exists()
    assert meme.held_unpersisted(led.path) == [], \
        "спул справился — удерживать нечего"
    assert [row["attempt_id"] for row in led.attempts(-100, limit=5)] == \
        ["spooled-A"]
    assert led.attempts(-101, limit=5) == []


def test_both_carriers_fail_hold_the_row_then_flush_it_exactly_once(
        tmp_path, monkeypatch):
    """Свойство 2: оба носителя упали → строка удержана и перенесена ровно раз.

    Mutation: убрать `_retry_unpersisted()` из `record_attempt` — строка навсегда
    остаётся в `_unpersisted`, в журнале её нет, тест красный.
    """
    led = _ledger(tmp_path)
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())
    original_insert = meme.SqliteQuotaLedger._insert_attempt
    original_spool = meme.SqliteQuotaLedger._spool_attempt
    _break_journal(monkeypatch)
    _break_spool(monkeypatch)

    led.record_attempt(_publication_row("held-1", ts=NOW.timestamp()))

    assert [row["attempt_id"] for row in meme.held_unpersisted(led.path)] == \
        ["held-1"]
    assert not pathlib.Path(led.pending_path()).exists()
    assert led.attempts(-100, limit=5) == [], "в журнале строки ещё нет"

    # Носители освободились: следующая ЗАПИСЬ сначала переносит удержанное.
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt",
                        original_insert)
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_spool_attempt",
                        original_spool)
    led.record_attempt(_publication_row("held-2", ts=NOW.timestamp() + 1))

    rows = led.attempts(-100, limit=10)
    assert sorted(row["attempt_id"] for row in rows) == ["held-1", "held-2"]
    assert meme.held_unpersisted(led.path) == [], "удержанная строка перенесена"
    # Ровно один раз: повторная запись того же attempt_id — no-op (ID2).
    led.record_attempt(_publication_row("held-1"))
    ids = [row["attempt_id"] for row in led.attempts(-100, limit=10)]
    assert ids.count("held-1") == 1, ids


def test_both_carriers_fail_log_the_full_row_without_truncation(
        tmp_path, monkeypatch, caplog):
    """Свойство 3: последний рубеж — ПОЛНАЯ строка в логе, без усечения.

    Mutation: вернуть прежнюю запись `attempt[:12] + тип ошибки` — JSON в логе
    не разбирается и/или в нём нет outcome/reason_code/фактов публикации.
    """
    led = _ledger(tmp_path)
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())
    _break_journal(monkeypatch)
    _break_spool(monkeypatch)
    attempt_id = "attempt-" + "0123456789abcdef"      # длиннее 12 символов
    caplog.set_level("ERROR")

    led.record_attempt(_publication_row(attempt_id))

    errors = [rec for rec in caplog.records
              if rec.levelno == 40 and "attempt LOST" in rec.getMessage()]
    assert len(errors) == 1, [r.getMessage() for r in caplog.records]
    message = errors[0].getMessage()
    payload = json.loads(message.split("row=", 1)[1])
    assert payload["attempt_id"] == attempt_id, "id не усечён"
    assert payload["outcome"] == "published"
    assert payload["reason_code"] == "sent"
    assert set(payload) == set(meme.SPOOL_FIELDS)
    detail = json.loads(payload["detail"])
    assert detail["attempt_mode"] == "manual"
    assert detail["publication"]["output"]["tg_message_id"] == 4321
    assert detail["publication"]["delivery"] == "sent"


def test_held_row_is_not_fabricated_into_the_read_model(tmp_path, monkeypatch):
    """Свойство 4: что именно видит durable-читатель, пока строка удержана.

    Держится такая гарантия: удержанная строка не подделывается (не появляется
    половинчатой и не сливается с чужой), не теряется (полный payload в логе) и
    переносится в первый освободившийся носитель при следующей записи. Пока
    переноса не было, durable-читатель показывает ПРЕДЫДУЩУЮ попытку — это
    принятое остаточное окно RW-D4-BOTH-WRITE-FAIL (architecture-identity.md
    §1), а не выданная за правду «последняя» попытка: строки с удержанным
    `attempt_id` в ответе нет вовсе.
    """
    led = _ledger(tmp_path)
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())
    led.record_attempt(_publication_row("older", ts=NOW.timestamp()))
    original_insert = meme.SqliteQuotaLedger._insert_attempt
    original_spool = meme.SqliteQuotaLedger._spool_attempt
    _break_journal(monkeypatch)
    _break_spool(monkeypatch)

    led.record_attempt(_publication_row("held", ts=NOW.timestamp() + 60))

    rows = led.attempts(-100, limit=10)
    assert [row["attempt_id"] for row in rows] == ["older"], rows
    assert all(row.get("outcome") for row in rows), "половинчатых строк нет"

    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt",
                        original_insert)
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_spool_attempt",
                        original_spool)
    led.record_attempt(_publication_row("after", ts=NOW.timestamp() + 120))

    ids = [row["attempt_id"] for row in led.attempts(-100, limit=10)]
    assert ids == ["after", "held", "older"], ids


def test_unpersisted_cap_logs_the_oldest_in_full(tmp_path, monkeypatch, caplog):
    """Свойство 5: за потолком 200 самая старая строка пишется в лог целиком.

    Потолок — общий на ПУТЬ журнала: держат ДВА разных экземпляра одного файла
    (`open_ledger` создаёт новый объект каждый проход), а реестр один.

    Mutation: молча вытеснять (`pop(0)` без записи) — в логе нет evicted-строки,
    факт пропадает анонимно, тест красный.
    """
    led_a = _ledger(tmp_path)
    led_b = meme.SqliteQuotaLedger(led_a.path)
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())
    _break_journal(monkeypatch)
    _break_spool(monkeypatch)
    total = meme.ATTEMPT_UNPERSISTED_MAX + 1
    caplog.set_level("ERROR")

    for index in range(total):
        owner = led_a if index % 2 == 0 else led_b
        owner.record_attempt(_attempt_row("cap-%03d" % index,
                                          ts=NOW.timestamp() + index))

    held = meme.held_unpersisted(led_a.path)
    assert len(held) == meme.ATTEMPT_UNPERSISTED_MAX
    assert held[0]["attempt_id"] == "cap-001"
    assert held[-1]["attempt_id"] == "cap-%03d" % (total - 1)

    evicted = [rec.getMessage() for rec in caplog.records
               if "evicted over cap" in rec.getMessage()]
    assert len(evicted) == 1, evicted
    payload = json.loads(evicted[0].split("row=", 1)[1])
    assert payload["attempt_id"] == "cap-000"
    assert set(payload) == set(meme.SPOOL_FIELDS)
    assert payload["stage"] == meme.STAGE_PUBLISH


def test_held_row_survives_a_new_ledger_instance_on_same_path(
        tmp_path, monkeypatch):
    """Свойство 6 (CORRECTION RW-D4): удержание живёт на ПУТИ журнала, не на объекте.

    Production берёт `meme.open_ledger(db)` на каждый проход (наблюдатель,
    `/meme`, отчёты, диагностика) — это НОВЫЙ объект того же файла. Поэтому
    переносчиком удержанной строки почти всегда является другой экземпляр. На
    прежнем коде (`self._unpersisted`) строка A не доезжала до журнала никогда:
    запись B видела только B, а единственным следом оставался ERROR.

    Mutation: вернуть список на экземпляр — тест красный (в журнале нет
    `cross-1`, реестр пути не пуст).
    """
    led_a = _ledger(tmp_path)
    path = led_a.path
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())
    original_insert = meme.SqliteQuotaLedger._insert_attempt
    original_spool = meme.SqliteQuotaLedger._spool_attempt
    _break_journal(monkeypatch)
    _break_spool(monkeypatch)

    led_a.record_attempt(_publication_row("cross-1", ts=NOW.timestamp()))

    assert [row["attempt_id"] for row in meme.held_unpersisted(path)] == \
        ["cross-1"]
    assert led_a.attempts(-100, limit=5) == [], "в журнале строки ещё нет"

    # Следующий проход = новый объект того же файла. Читатель не переносит.
    led_b = meme.SqliteQuotaLedger(path)
    assert led_b.attempts(-100, limit=5) == []
    assert len(meme.held_unpersisted(path)) == 1

    # Носители освободились: перенос делает уже ДРУГОЙ экземпляр.
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt",
                        original_insert)
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_spool_attempt",
                        original_spool)
    led_b.record_attempt(_publication_row("cross-2", ts=NOW.timestamp() + 1))

    ids = sorted(row["attempt_id"] for row in led_b.attempts(-100, limit=10))
    assert ids == ["cross-1", "cross-2"], ids
    assert meme.held_unpersisted(path) == [], "чужое удержание не перенесено"
    # Ровно один раз: повторная запись того же attempt_id — no-op (ID2).
    led_b.record_attempt(_publication_row("cross-1"))
    ids = [row["attempt_id"] for row in led_b.attempts(-100, limit=10)]
    assert ids.count("cross-1") == 1, ids


def test_two_ledgers_in_two_threads_hold_and_flush_without_loss(
        tmp_path, monkeypatch):
    """Свойство 7: общий реестр удержания безопасен при двух потоках.

    Наблюдатель, `/meme` и отчёты живут в одном процессе: пять удержаний из
    одного потока и пять из другого на одном файле должны дать ровно десять
    строк, а перенос — без потерь и без дублей.
    """
    led_a = _ledger(tmp_path)
    path = led_a.path
    led_b = meme.SqliteQuotaLedger(path)
    monkeypatch.setattr(meme, "ATTEMPT_WRITE_DELAYS", ())
    original_insert = meme.SqliteQuotaLedger._insert_attempt
    original_spool = meme.SqliteQuotaLedger._spool_attempt
    _break_journal(monkeypatch)
    _break_spool(monkeypatch)
    first = ["thr-a-%d" % index for index in range(5)]
    second = ["thr-b-%d" % index for index in range(5)]

    def hold(ledger, attempt_ids):
        for attempt_id in attempt_ids:
            ledger.record_attempt(_publication_row(attempt_id,
                                                   ts=NOW.timestamp()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        done = [pool.submit(hold, led_a, first),
                pool.submit(hold, led_b, second)]
    for future in done:
        future.result()

    assert sorted(row["attempt_id"] for row in meme.held_unpersisted(path)) == \
        sorted(first + second), "потеря или дубль при одновременном удержании"

    monkeypatch.setattr(meme.SqliteQuotaLedger, "_insert_attempt",
                        original_insert)
    monkeypatch.setattr(meme.SqliteQuotaLedger, "_spool_attempt",
                        original_spool)
    with ThreadPoolExecutor(max_workers=2) as pool:
        done = [pool.submit(led_a.record_attempt, _publication_row("thr-c")),
                pool.submit(led_b.record_attempt, _publication_row("thr-d"))]
    for future in done:
        future.result()

    ids = sorted(row["attempt_id"] for row in led_a.attempts(-100, limit=20))
    assert ids == sorted(first + second + ["thr-c", "thr-d"]), ids
    assert meme.held_unpersisted(path) == []


def test_id_conc_aggregator_keeps_chats_and_competitors_apart(tmp_path):
    """P0IM-ID-CONC: одинаковый `ts` и конкурирующие холдеры не сливаются.

    (а) две попытки в РАЗНЫХ чатах с одинаковым `ts` — две группы, изоляция
    чтения по чату; (б) два конкурирующих холдера в одном чате дают две
    терминальные строки с разными родителями: прошедшую и конфликтную, без
    третьей псевдо-группы `row:{attempt_id}` и без потери строки.

    Предусловие ID5: один процесс-писатель на файл журнала (systemd-инстанс
    один); спул-дренаж с `os.replace` рассчитан именно на это.
    """
    from services import publication_coordination as pub
    from web.api.initiative_publications import _meme_attempts_grouped

    led = _ledger(tmp_path)
    ts = int(NOW.timestamp())
    led.record_attempt(_publication_row(
        "a-1", chat_id=-100, ts=ts, job_id="meme:-100:2026-11-03:aaaa"))
    led.record_attempt(_publication_row(
        "b-1", chat_id=-101, ts=ts, job_id="meme:-101:2026-11-03:bbbb"))

    rows_a = led.attempts(-100, limit=10)
    rows_b = led.attempts(-101, limit=10)
    assert [row["attempt_id"] for row in rows_a] == ["a-1"]
    assert [row["attempt_id"] for row in rows_b] == ["b-1"]
    groups_a = _meme_attempts_grouped(rows_a)
    groups_b = _meme_attempts_grouped(rows_b)
    assert len(groups_a) == 1 and len(groups_b) == 1
    # Один и тот же ts и одинаковый текст не склеивают попытки: ключ — родитель.
    both = _meme_attempts_grouped(rows_a + rows_b)
    assert len(both) == 2, both
    assert {item["attempt_id"] for item in both} == {
        "meme:meme:-100:2026-11-03:aaaa", "meme:meme:-101:2026-11-03:bbbb"}

    # (б) конкурирующие холдеры в одном чате.
    store = pub.SqliteClaimStore(led.path)
    first = store.acquire(chat_id=-102, holder_kind=pub.KIND_TEXT_INITIATIVE,
                          now=ts)
    assert first.granted is True
    assert store.begin_sending(chat_id=-102, claim_id=first.claim_id,
                               now=ts).granted is True
    contender = store.acquire(chat_id=-102, holder_kind=pub.KIND_MEME_INITIATIVE,
                              now=ts, interval_seconds=1800)
    assert contender.granted is False
    # Автоматический путь честно видит занятый слот: конфликт + где именно
    # (семантика брони не меняется — S5-MEME её уже зафиксировал).
    assert contender.reason == pub.REASON_CONFLICT
    assert contender.detail == pub.DETAIL_CLAIM_HELD
    assert contender.state == "sending"

    led.record_attempt(_publication_row(
        "holder-win", chat_id=-102, ts=ts, reason="sent",
        job_id="meme:-102:2026-11-03:win"))
    led.record_attempt(_publication_row(
        "holder-lose", chat_id=-102, ts=ts, reason="publication_in_flight",
        outcome="skipped", job_id="meme:-102:2026-11-03:lose"))

    groups = _meme_attempts_grouped(led.attempts(-102, limit=10))
    assert len(groups) == 2, groups
    assert all(not item["attempt_id"].startswith("meme:row:") for item in groups)
    assert all(item["job_id"] for item in groups)
    assert all(item["incomplete_historical"] is False for item in groups)
    assert {item["reason_code"] for item in groups} == {
        "sent", "publication_in_flight"}
    # Ни одна из двух строк не исчезла: журнал содержит обе.
    assert sorted(row["attempt_id"] for row in led.attempts(-102, limit=10)) == \
        ["holder-lose", "holder-win"]


# ── P0IM-AC-MATRIX-FAIL: обрыв после LLM A/B и пустой ответ image API ───────
# Два узких негативных случая матрицы отказов (§P0IM-AC-MATRIX-FAIL):
#   (a) провайдер картинки падает ПОСЛЕ обеих LLM-стадий — одна попытка,
#       терминальный этап failed, публикации/доставки нет;
#   (b) провайдер вернул ok=True, но content=None — публиковать нечего,
#       честный отказ `empty_content`, одна попытка, доставки нет.

class _RaisingProvider:
    """Провайдер картинки, падающий на вызове (сбой внешнего API)."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, prompt, chat_id, job_id):
        self.calls += 1
        raise RuntimeError("provider down")


class _EmptyContentProvider:
    """ok=True, но изображения нет: публиковать нечего."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, prompt, chat_id, job_id):
        self.calls += 1
        return SimpleNamespace(ok=True, called=True, reason="",
                               content=None, filename="image.png")


def _single_failed_attempt(led):
    from web.api.initiative_publications import _meme_attempts_grouped

    rows = led.attempts(-100, limit=50)
    groups = _meme_attempts_grouped(rows)
    assert len(groups) == 1, groups
    attempt = groups[0]
    assert attempt["kind"] == "meme", attempt
    assert attempt["outcome"] not in ("published", "deferred"), attempt
    assert attempt["delivered"] is False, attempt
    assert attempt["message_id"] is None, attempt
    assert "publish" not in [s["stage"] for s in attempt["stages"]], attempt
    return rows, attempt


def test_provider_failure_after_llm_stages_is_one_failed_attempt(tmp_path):
    """(a) Сбой картинки после A/B: один failed-исход, без публикации/доставки.

    Обе LLM-стадии уже состоялись (summary+joke), затем провайдер падает —
    повторной попытки/второй строки-попытки и доставки быть не должно.
    """
    provider = _RaisingProvider()
    deliveries: list = []

    async def sender(chat_id, content, prompt=""):
        deliveries.append((chat_id, content))
        return SimpleNamespace(message_id=999)

    async def scenario():
        return await _consider(tmp_path, provider=provider, sender=sender)

    result, _, led = _run(scenario())
    assert provider.calls == 1, provider.calls
    assert result.outcome == "failed", result.as_dict()
    assert result.reason == meme.SKIP_IMAGE_FAILED, result.as_dict()
    assert deliveries == [], "сбой не должен доходить до отправки"

    rows, attempt = _single_failed_attempt(led)
    stages = [row["stage"] for row in rows]
    assert meme.STAGE_SUMMARY in stages and meme.STAGE_JOKE in stages, stages
    assert attempt["stage"] == meme.STAGE_FAILED, attempt
    assert attempt["reason_code"] == meme.SKIP_IMAGE_FAILED, attempt


def test_empty_image_content_is_an_honest_failure_not_publication(tmp_path):
    """(b) ok=True + content=None: не публикуем, одна попытка, `empty_content`."""
    provider = _EmptyContentProvider()
    deliveries: list = []

    async def sender(chat_id, content, prompt=""):
        deliveries.append((chat_id, content))
        return SimpleNamespace(message_id=999)

    async def scenario():
        return await _consider(tmp_path, provider=provider, sender=sender)

    result, _, led = _run(scenario())
    assert provider.calls == 1, provider.calls
    assert result.outcome == "failed", result.as_dict()
    assert result.reason == meme.SKIP_IMAGE_FAILED, result.as_dict()
    assert result.detail == "empty_content", result.as_dict()
    assert deliveries == [], "пустая картинка не публикуется"

    rows, attempt = _single_failed_attempt(led)
    assert attempt["stage"] == meme.STAGE_FAILED, attempt
    assert attempt["reason_code"] == meme.SKIP_IMAGE_FAILED, attempt
    terminal = [row for row in rows if row["stage"] == meme.STAGE_FAILED][0]
    facts = meme.parse_attempt_facts(terminal)
    assert facts.get("detail") == "empty_content", facts
    assert attempt["generated"] is False, attempt


# ── P0IM-PB-LLM: короткая идентичность шагов, без полного текста ────────────
# Журнал попытки должен называть ФАКТИЧЕСКИЙ провайдер/модель, отсутствие
# слота и источник/редакцию/sha12 промпта, а также статус/формат/байты Image
# API. Полные сообщения, выжимка, прикол и промпты в durable detail не едут —
# для них есть существующее кольцо композера/Inspector (P0IM-PB-ACCESS).

class _IdentityLLM:
    """Клиент с реальным швом идентичности (`_chat_model`/`_provider_label`)."""

    _chat_model = "unit/model-x"

    def __init__(self):
        self.correlations = []

    def _provider_label(self, model):
        return "provider.example"

    async def generate(self, messages, **kwargs):
        # Тот же correlation_id, что рантайм передаёт в настоящий LLMClient
        # (и по которому кольцо/Inspector находят полный текст шага).
        self.correlations.append(str(kwargs.get("correlation_id") or ""))
        return "LLM-OUT-SECRET"


class _FormatProvider:
    """Провайдер с именем файла: формат берётся из него, байты — только число."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, prompt, chat_id, job_id):
        self.calls += 1
        return SimpleNamespace(ok=True, called=True, reason="",
                               content=b"png", filename="meme.png")


def test_llm_identity_is_short_and_full_text_stays_out_of_journal(tmp_path):
    """§P0IM-PB-LLM: identity/prompt/Image API — в detail, текстов там нет."""
    led = _ledger(tmp_path)
    provider = _FormatProvider()
    llm = _IdentityLLM()

    async def scenario():
        # Реальные дефолтные шаги A/B: identity берётся у того же клиента,
        # который реально делает вызовы (не тестовые хуки).
        return await meme.consider_chat(
            None, -100, settings=_settings(), ledger=led, now=NOW,
            tz_name="UTC", tz_source="utc_fallback",
            initiative_enabled=lambda: True, image_status=IMAGE_OK,
            random_source=_Hit(), messages=_rows(-100), llm=llm,
            image_provider=provider, model_chars=200)

    result = _run(scenario())
    assert result.outcome == "blocked", result.as_dict()  # нет sender — не доставка
    # Те же correlation_id, по которым PB-ACCESS ищет полный текст в кольце.
    assert llm.correlations == [result.job_id + "#meme_summary",
                                result.job_id + "#meme_joke"], llm.correlations
    rows = led.attempts(-100, limit=50)
    by_stage = {row["stage"]: meme.parse_attempt_facts(row) for row in rows}

    summary = by_stage[meme.STAGE_SUMMARY]
    joke = by_stage[meme.STAGE_JOKE]
    image = by_stage[meme.STAGE_IMAGE]
    for facts in (summary, joke):
        llm = facts.get("llm")
        assert isinstance(llm, dict), facts
        assert llm["provider"] == "provider.example", llm
        assert llm["model"] == "unit/model-x", llm
        assert llm["slot"] is None and llm["slot_reason"] == "slot_not_used", llm
        prompt = facts.get("prompt")
        assert prompt and len(str(prompt.get("sha12") or "")) == 12, prompt
        assert prompt.get("source"), prompt
        assert prompt.get("revision") not in (None, ""), prompt
    api = image.get("api")
    assert api and api["status"] == "ok" and api["ok"] is True, api
    assert api["format"] == "png" and api["format_source"] == "filename", api
    assert api["bytes"] == 3 and api["bytes_present"] is True, api
    assert len(str(image.get("prompt_sha12") or "")) == 12, image

    # Тексты ответа модели и промптов в durable detail НЕ попадают.
    dump = json.dumps([dict(row) for row in rows], ensure_ascii=False)
    assert "LLM-OUT-SECRET" not in dump, "полный ответ модели утёк в журнал"
    assert "Придумай короткий" not in dump, "текст промпта утёк в журнал"
    assert "Создай мем" not in dump, "текст image-промпта утёк в журнал"


# ═════════════════════════════════════════════════════════════════════════════
# SMART-EXECUTION-RELIABILITY-01 I1 — журнал под открытой транзакцией писателя
# ═════════════════════════════════════════════════════════════════════════════
# TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-14-SMART-EXECUTION-RELIABILITY-01
# (§I1: реальная причина OperationalError, нормальная запись, идемпотентный
#  спул, отсутствие потерь/дублей, наблюдаемая причина отказа).
#
# Production 13.11.2026 (09:36, journal window): три попытки `_insert_attempt`
# съели по полному `busy_timeout` (29.454 → 44.601 = 15.147 с), строка ушла в
# спул, следующий перенос добавил ещё 5.011 с. Причина — НЕ схема/права/диск,
# а открытая транзакция единственного писателя приложения: файловое
# соединение журнала ждёт её в `busy_timeout`.

def _journal_ids(led) -> list[str]:
    conn = sqlite3.connect(led.path)
    try:
        return [row[0] for row in conn.execute(
            "SELECT attempt_id FROM meme_initiative_attempt "
            "ORDER BY attempt_id").fetchall()]
    finally:
        conn.close()


def test_blocked_journal_write_is_bounded_and_recovers(tmp_path):
    """Чужая открытая транзакция: запись ограничена по времени и не теряется.

    Синхронный путь (`record_attempt`) не имеет права ждать полный
    `busy_timeout` × 3 в петле событий: строка уходит в durable-спул, видна
    читателю, а после освобождения журнала переносится ровно один раз.
    """
    led = _ledger(tmp_path)
    led.record_attempt(_attempt_row("pre-1", ts=NOW_TS))
    spool_path = pathlib.Path(led.pending_path())

    blocker = sqlite3.connect(led.path, isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute(
            "INSERT INTO meme_initiative_attempt (attempt_id, chat_id, "
            "job_id, ts, stage, outcome, reason_code, detail, limit_source, "
            "limit_value, window_messages) VALUES "
            "('foreign-1', -100, 'run-2', 1, 'considered', 'passed', '', '', "
            "'', NULL, NULL)")
        started = time.monotonic()
        led.record_attempt(_publication_row("spool-1", ts=NOW_TS + 5))
        elapsed = time.monotonic() - started
    finally:
        blocker.execute("COMMIT")
        blocker.close()

    # Граница: три коротких попытки + паузы, а не 15 с посреди прохода.
    assert elapsed < 2.0, "запись журнала заморозила вызывающего: %.2fs" % elapsed
    assert spool_path.exists(), "строка обязана уйти в durable-спул"
    assert _journal_ids(led) == ["foreign-1", "pre-1"], _journal_ids(led)

    # Витрина видит спулёную строку сразу (последняя попытка не «пропала»).
    visible = led.attempts(-100, limit=5)
    assert [row["attempt_id"] for row in visible][:2] == ["spool-1", "pre-1"]

    # Журнал освободился: перенос идемпотентен, старые строки не тронуты.
    for _ in range(2):
        led._flush_pending_attempts()
    assert not spool_path.exists()
    assert _journal_ids(led) == ["foreign-1", "pre-1", "spool-1"]
    last = led.attempts(-100, limit=1)
    assert [row["attempt_id"] for row in last] == ["spool-1"]


@pytest.mark.asyncio
async def test_journal_write_waits_for_writer_through_single_writer(tmp_path):
    """Горячий путь: запись ждёт ЕДИНОГО писателя асинхронно, без спула.

    Пока чужая транзакция открыта, `record_attempt_async` ждёт её (а не
    падает в спул), петля событий продолжает работать, а после коммита строка
    ложится в журнал тем же `INSERT OR IGNORE`.
    """
    db_path = tmp_path / "single-writer.db"
    meme.SqliteQuotaLedger(str(db_path)).apply_schema()
    svc = DatabaseService(str(db_path))
    await svc.initialize()
    try:
        ledger = meme.open_ledger(svc)
        assert ledger is not None and ledger._journal_writer is not None

        holder_started = asyncio.Event()
        release = asyncio.Event()

        async def _holder(_conn):
            await svc.db.execute(
                "INSERT INTO meme_initiative_attempt (attempt_id, chat_id, "
                "job_id, ts, stage, outcome, reason_code, detail, "
                "limit_source, limit_value, window_messages) VALUES "
                "('foreign-1', -100, '', 1, 'considered', 'passed', '', '', "
                "'', NULL, NULL)")
            holder_started.set()
            await release.wait()
            return 1

        holder = asyncio.create_task(
            svc.write_transaction(_holder, op_name="test_i1_hold"))
        await asyncio.wait_for(holder_started.wait(), timeout=5)

        ticks = {"n": 0}

        async def _ticker():
            while True:
                ticks["n"] += 1
                await asyncio.sleep(0.01)

        ticker = asyncio.create_task(_ticker())
        try:
            write = asyncio.create_task(
                ledger.record_attempt_async(_publication_row("journal-1",
                                                             ts=NOW_TS)))
            await asyncio.sleep(0.3)
            assert not write.done(), "запись должна ждать писателя, а не спул"
            assert ticks["n"] >= 10, "петля событий стояла на busy_timeout"
            release.set()
            await asyncio.wait_for(write, timeout=5)
        finally:
            ticker.cancel()
            try:
                await ticker
            except asyncio.CancelledError:
                pass
        await asyncio.wait_for(holder, timeout=5)

        assert _journal_ids(ledger) == ["foreign-1", "journal-1"]
        assert not pathlib.Path(ledger.pending_path()).exists(), \
            "при живом писателе durable-спул не нужен"
        # Последняя попытка — записанная строка (витрина читает журнал).
        assert [row["attempt_id"] for row in ledger.attempts(-100, limit=1)] == \
            ["journal-1"]
    finally:
        await svc.close()


def test_spool_drain_is_idempotent_and_keeps_existing_rows(tmp_path):
    """Повторный перенос: ни дублей, ни потерь; накопленные строки не тронуты."""
    led = _ledger(tmp_path)
    for index in range(3):
        led.record_attempt(_attempt_row("old-%d" % index, ts=NOW_TS + index))
    before = {row["attempt_id"]: dict(row) for row in led.attempts(-100, limit=50)}

    spool_path = pathlib.Path(led.pending_path())
    spooled = [_attempt_row("pending-a", ts=NOW_TS + 10),
               _attempt_row("pending-b", ts=NOW_TS + 11)]
    spool_path.write_text(
        "".join(json.dumps(meme._spool_payload(row), ensure_ascii=False) + "\n"
                for row in spooled), encoding="utf-8")

    led._flush_pending_attempts()
    led._flush_pending_attempts()

    assert not spool_path.exists()
    assert _journal_ids(led) == ["old-0", "old-1", "old-2",
                                 "pending-a", "pending-b"]
    after = {row["attempt_id"]: dict(row) for row in led.attempts(-100, limit=50)}
    for attempt_id in ("old-0", "old-1", "old-2"):
        assert after[attempt_id] == before[attempt_id], \
            "накопленная строка изменилась при переносе спула"


def test_journal_failure_logs_real_sqlite_detail_without_row_content(
        tmp_path, caplog):
    """Отказ журнала наблюдаем: тип, текст SQLite, операция, таблица, время.

    Причина больше не сводится к имени класса, но содержимое попытки
    (detail с текстом/ответом) в лог не уходит.
    """
    led = _ledger(tmp_path)
    conn = sqlite3.connect(led.path)
    try:
        conn.execute("DROP TABLE meme_initiative_attempt")
        conn.commit()
    finally:
        conn.close()

    row = _attempt_row("diag-1")
    row["detail"] = '{"secret":"PRIVATE-REPLY-TEXT"}'
    with caplog.at_level(logging.WARNING, logger="services.meme_initiative"):
        led.record_attempt(row)

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "attempt spooled (journal unavailable)" in text
    assert "op=INSERT OR IGNORE" in text
    assert "table=meme_initiative_attempt" in text
    assert "busy_timeout_ms=" in text and "elapsed_ms=" in text
    assert "OperationalError" in text
    assert "no such table" in text
    assert "PRIVATE-REPLY-TEXT" not in text, "содержимое попытки утекло в лог"


@pytest.mark.asyncio
async def test_finish_async_writes_attempt_rows_through_single_writer(tmp_path):
    """Пайплайн (`_finish_async`) пишет строки журнала единым писателем.

    Проверяется именно связка «итог попытки → writer→ журнал»: строки те же
    (этап + терминал), durable-спул не задействован, витрина видит попытку.
    """
    db_path = tmp_path / "finish.db"
    meme.SqliteQuotaLedger(str(db_path)).apply_schema()
    svc = DatabaseService(str(db_path))
    await svc.initialize()
    try:
        ledger = meme.open_ledger(svc)
        assert ledger is not None and ledger._journal_writer is not None
        result = meme.AttemptResult(
            chat_id=-100, stage=meme.STAGE_PUBLISH, outcome="published",
            reason="sent", detail="sent",
            counters={meme.STAGE_CONSIDERED: 1, meme.STAGE_PUBLISH: 1},
            stage_facts={meme.STAGE_PUBLISH: {"delivery": "sent"}})
        await meme._finish_async(result, ledger=ledger, now_ts=NOW_TS,
                                 settings=_settings())
    finally:
        await svc.close()

    rows = ledger.attempts(-100, limit=10)
    stages = sorted(str(row.get("stage")) for row in rows)
    assert stages == sorted([meme.STAGE_CONSIDERED, meme.STAGE_PUBLISH]), stages
    terminal = [row for row in rows if row["stage"] == meme.STAGE_PUBLISH][0]
    assert terminal["outcome"] == "published"
    assert meme.attempt_mode_of(meme.parse_attempt_facts(terminal)) == "auto"
    assert not pathlib.Path(ledger.pending_path()).exists()


@pytest.mark.asyncio
async def test_writer_failure_rolls_back_and_keeps_other_writers_moving(
        tmp_path, caplog):
    """Отказ writer'а не оставляет открытую транзакцию на общем соединении.

    Иначе единственный писатель держит write-lock: соседний путь (бронь квоты
    на своём соединении) падает по `busy_timeout` — ровно класс production
    инцидента. Лог обязан назвать ФАКТИЧЕСКИЙ таймаут пути (5000 у соединения
    приложения, не 250 файлового).
    """
    db_path = tmp_path / "writer-fail.db"
    meme.SqliteQuotaLedger(str(db_path)).apply_schema()
    svc = DatabaseService(str(db_path))
    await svc.initialize()
    try:
        ledger = meme.open_ledger(svc)
        assert ledger is not None and ledger._journal_writer is not None
        con = sqlite3.connect(str(db_path))
        try:
            con.execute("DROP TABLE meme_initiative_attempt")
            con.commit()
        finally:
            con.close()

        with caplog.at_level(logging.WARNING, logger="services.meme_initiative"):
            await ledger.record_attempt_async(_publication_row("fail-1",
                                                              ts=NOW_TS))

        assert not svc.db.in_transaction, \
            "отказ writer'а оставил открытую транзакцию на общем соединении"
        log = "\n".join(record.getMessage() for record in caplog.records)
        assert "no such table" in log
        assert "busy_timeout_ms=5000" in log, log

        # Чужой writer получает lock сразу: соединение не удерживает транзакцию.
        started = time.monotonic()
        other = sqlite3.connect(str(db_path), timeout=1, isolation_level=None)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("COMMIT")
        finally:
            other.close()
        assert time.monotonic() - started < 1.0, "write-lock остался занят"

        # Носитель восстановился: строка переносится ровно один раз.
        assert pathlib.Path(ledger.pending_path()).exists()
        meme.SqliteQuotaLedger(str(db_path)).apply_schema()
        for _ in range(2):
            ledger._flush_pending_attempts()
        assert not pathlib.Path(ledger.pending_path()).exists()
        assert _journal_ids(ledger) == ["fail-1"], _journal_ids(ledger)
    finally:
        await svc.close()


def test_spool_drain_deduplicates_already_written_attempt_id(tmp_path):
    """Спул может содержать attempt_id, уже лежащий в журнале (сбой между
    вставкой и удалением файла): повторный перенос не даёт дубля и не застревает.

    Свойство держится `INSERT OR IGNORE`; при простом `INSERT` строка «dup-1»
    падает на PK и спул не опустошается.
    """
    led = _ledger(tmp_path)
    led.record_attempt(_attempt_row("dup-1", ts=NOW_TS))
    spool_path = pathlib.Path(led.pending_path())
    rows = [_attempt_row("dup-1", ts=NOW_TS),
            _attempt_row("new-2", ts=NOW_TS + 1)]
    spool_path.write_text(
        "".join(json.dumps(meme._spool_payload(row), ensure_ascii=False) + "\n"
                for row in rows), encoding="utf-8")

    led._flush_pending_attempts()

    assert not spool_path.exists(), "спул обязан опустеть при дубликате"
    assert _journal_ids(led) == ["dup-1", "new-2"], _journal_ids(led)
    assert [row["attempt_id"] for row in led.attempts(-100, limit=10)] == \
        ["new-2", "dup-1"]
