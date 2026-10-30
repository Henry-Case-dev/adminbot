"""EVOL-014 — бэкенд инициативных мемов (офлайн, без сети и Telegram).

TEST-LIFECYCLE: CONTRACT owner=EVOL-014 (квота, гейты, промпт, изоляция чатов)
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import initiative_observer as obs
from services import mca_exploration as mx
from services import mca_random_source as mrs
from services import meme_initiative as meme
from services import prompt_registry as pr

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
                    summarizer=None, gate=None, sender=None, messages=None,
                    reader=None, settings=None, ledger=None,
                    image_status=None, model_chars=200, **kwargs):
    led = ledger if ledger is not None else _ledger(tmp_path)
    if source is None:
        source = _Hit()
    if provider is None:
        provider = _Provider()
    if summarizer is None:
        async def summarizer(cid, rows, target, system):
            return "хук"
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

    async def scenario():
        down = _Hit(deferred=True)
        result, provider, _ = await _consider(
            tmp_path, source=down, summarizer=summarizer)
        fallback = _Hit(value=0.01, fallback="provider_unavailable")
        masked, _, _ = await _consider(
            tmp_path, source=fallback, summarizer=summarizer,
            ledger=result and _ledger(tmp_path))
        return result, provider, down, masked

    # второй вызов со своим ledger — проще двумя корутинами
    async def both():
        down = _Hit(deferred=True)
        missing = _Hit(missing=True)
        fallback = _Hit(value=0.0, fallback="provider_unavailable")
        a, provider, _ = await _consider(
            tmp_path, source=down, summarizer=summarizer)
        (tmp_path / "b").mkdir()
        (tmp_path / "c").mkdir()
        b, _, _ = await _consider(
            tmp_path / "b", source=missing, summarizer=summarizer)
        c, _, _ = await _consider(
            tmp_path / "c", source=fallback, summarizer=summarizer)
        return a, b, c, provider, down

    a, b, c, provider, down = _run(both())
    assert a.reason == meme.SKIP_RANDOM_UNAVAILABLE
    assert b.reason == meme.SKIP_RANDOM_UNAVAILABLE
    assert c.reason == meme.SKIP_RANDOM_UNAVAILABLE
    assert provider.calls == []
    assert called["summary"] == 0
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


# ── 4. лимит длины до суммаризатора, без обрезки ───────────────────────────

def test_length_limit_is_applied_before_summarizer(tmp_path):
    seen = {}
    order = []

    async def summarizer(_cid, _rows, target, system):
        order.append("summary")
        seen["target"] = target
        seen["system"] = system
        return "хук"

    provider = _Provider()

    async def wrapped(prompt, chat_id, job_id):
        order.append("provider")
        return await provider(prompt, chat_id, job_id)

    result, _, _ = _run(_consider(
        tmp_path, summarizer=summarizer, provider=wrapped, model_chars=80,
        gate=lambda _cid: _async_pair(False, "recheck_demoted")))
    expected = 80 - len(PREFIX) - 1
    assert seen["target"] == expected
    assert seen["target"] != 80
    assert seen["system"] == meme.MEME_SUMMARY_SYSTEM_PROMPT
    assert order == ["summary", "provider"]
    assert result.reason == meme.SKIP_PUBLISH
    assert result.limit.source == "model_capability"
    assert result.limit.summary_target == expected
    assert result.prompt == f"{PREFIX} хук"
    assert result.prompt_origin == "factory"


def test_overlong_summary_is_not_truncated(tmp_path):
    async def summarizer(_cid, _rows, target, _system):
        return "я" * (int(target) + 4)

    provider = _Provider()
    result, _, led = _run(_consider(
        tmp_path, summarizer=summarizer, provider=provider, model_chars=80))
    assert result.reason == meme.SKIP_SUMMARY
    assert result.detail == "exceeded_precomputed_limit"
    assert provider.calls == []
    assert led.spent(-100, "2026-10-30") == 0
    prompt, error = meme.build_image_prompt(PREFIX, "я" * 50, summary_target=10)
    assert prompt == "" and error == "exceeded_precomputed_limit"


def test_length_source_is_explicit():
    limit = meme.resolve_length_limit(
        model_chars=400, admin=120, explicit=90, prefix=PREFIX)
    assert limit.source == "explicit_override"
    assert limit.value == 90
    admin = meme.resolve_length_limit(
        model_chars=400, admin=120, explicit=None, prefix=PREFIX)
    assert admin.source == "admin_setting"
    unknown = meme.resolve_length_limit(
        model_chars=None, admin=None, explicit=None, prefix=PREFIX)
    assert unknown.known is False and unknown.source == "unknown"


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
    db_text = (pathlib.Path(__file__).resolve().parent.parent
               / "services" / "database.py").read_text(encoding="utf-8")
    assert meme.RESERVATION_TABLE not in db_text


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
