"""MCA-17 (группа «Фоновые воркеры сна/памяти», волна W1-C2) —
инструментирование процессов nostalgia.run / lore.compile / sleep.dream /
persona.traits / anticliche.run через единый `emit_mca_event` (REUSE mca-13).

Покрытие:
  * start + ОДИН терминальный outcome на осмысленный шаг (прогон ностальгии /
    прогон лора чата / тик сна / шаг черт / refresh-цикл анти-клише);
  * маппинг исходов success/skipped/failed на существующие reason_code §17.2
    (мета-проверка: ни один эмит не содержит код вне `me.REASON_CODES`);
  * R17: поля только из whitelist контракта (component/reason_code/chat_id/
    duration_ms) — текстов нет;
  * fail-open: сбой эмиссии никогда не рвёт воркер;
  * master OFF у обычного сна → событий нет (без шума каждый тик), manual → есть.
"""
import asyncio
import time

import pytest

from services import mca_events as me
from services.anticliche_worker import AntiClicheWorker
from services.dream_worker import DreamWorker
from services.lore_worker import LoreWorker
from services.nostalgia_worker import NostalgiaWorker

CHAT_ID = -1002661910336
NOW = int(time.time())

_ALLOWED_FIELDS = me.ALLOWED_FIELDS


@pytest.fixture(autouse=True)
def _reset_buffer():
    me.reset_pending()
    yield
    me.reset_pending()


@pytest.fixture
def events(monkeypatch):
    """Перехват `emit_mca_event` (lazy-импорт в воркерах резолвит атрибут
    модуля в момент вызова) — список собранных событий."""
    captured: list[dict] = []

    def _fake(event_name, *, outcome, level="INFO", **fields):
        captured.append({"event_name": event_name, "outcome": outcome,
                         "level": level, **fields})
        return {"event_name": event_name, "outcome": outcome}

    monkeypatch.setattr(me, "emit_mca_event", _fake)
    yield captured


def _hot_cache(monkeypatch, values: dict | None = None):
    """hot-кэш-заглушка (прецедент test_nostalgia_worker/_dream_worker)."""
    class _FakeHotCache:
        def __init__(self, vals):
            self._values = dict(vals or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    from services import hot_config as hot
    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


def _assert_contract_emits(captured: list[dict]) -> None:
    """Мета-контракт §17: исходы валидны, reason_code — только из словаря,
    поля — только из whitelist (R17: без текстов)."""
    for ev in captured:
        assert ev["outcome"] in me.ALL_OUTCOMES
        code = ev.get("reason_code")
        if code is not None:
            assert code in me.REASON_CODES, code
        assert ev.get("component") in {
            "nostalgia.run", "lore.compile", "sleep.dream",
            "persona.traits", "anticliche.run",
        }
        for key in ev:
            assert key in _ALLOWED_FIELDS | {
                "event_name", "outcome", "level", "schema_version", "ts",
            }, key


# ── nostalgia.run ───────────────────────────────────────────────────────────

def _nostalgia_worker(monkeypatch, *, enabled=True, store=None,
                      run_tick=None) -> NostalgiaWorker:
    _hot_cache(monkeypatch, {"memory.nostalgia_enabled": enabled})
    w = NostalgiaWorker(db=None, memory=None, store=store)
    if run_tick is not None:
        async def _impl(*, manual, only_chat=None):
            return run_tick
        w._run_tick = _impl
    return w


def test_nostalgia_start_and_success(events, monkeypatch):
    stats = {"chats": 1, "candidates": 2, "sent": 1, "skipped": 1, "errors": 0}
    w = _nostalgia_worker(monkeypatch, enabled=True, run_tick=stats)
    out = _run_coro(w._run(manual=False))
    assert out == stats
    assert [(e["event_name"], e["outcome"]) for e in events] == [
        ("nostalgia_run", "start"), ("nostalgia_run", "success")]
    assert events[1]["component"] == "nostalgia.run"
    assert "duration_ms" in events[1]
    _assert_contract_emits(events)


def test_nostalgia_skipped_no_candidates(events, monkeypatch):
    class _Store:
        async def list_active_chat_ids(self):
            return [CHAT_ID]

    w = _nostalgia_worker(monkeypatch, enabled=True,
                          run_tick={"chats": 1, "candidates": 0, "sent": 0,
                                    "skipped": 1, "errors": 0})
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(w._run(manual=False))
    finally:
        loop.close()
    assert [(e["event_name"], e["outcome"]) for e in events] == [
        ("nostalgia_run", "start"), ("nostalgia_run", "skipped")]
    assert events[1]["reason_code"] == "no_relevant_memory"
    _assert_contract_emits(events)


def test_nostalgia_skipped_disabled_when_flag_off(events, monkeypatch):
    w = _nostalgia_worker(monkeypatch, enabled=False,
                          run_tick={"chats": 0, "candidates": 0, "sent": 0,
                                    "skipped": 0, "errors": 0})
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(w._run(manual=True))
    finally:
        loop.close()
    assert events[-1]["outcome"] == "skipped"
    assert events[-1]["reason_code"] == "disabled"
    _assert_contract_emits(events)


def test_nostalgia_failed_when_store_missing(events, monkeypatch):
    class _BrokenStore:
        async def list_active_chat_ids(self):
            raise RuntimeError("pg down")

    w = _nostalgia_worker(monkeypatch, enabled=True, store=_BrokenStore())
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(w._run(manual=False))
    finally:
        loop.close()
    assert events[-1]["outcome"] == "failed"
    assert events[-1]["reason_code"] == "memory_service_missing"
    _assert_contract_emits(events)


def test_nostalgia_failed_on_llm_errors_only(events, monkeypatch):
    w = _nostalgia_worker(monkeypatch, enabled=True,
                          run_tick={"chats": 1, "candidates": 1, "sent": 0,
                                    "skipped": 0, "errors": 1})
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(w._run(manual=False))
    finally:
        loop.close()
    assert events[-1]["outcome"] == "failed"
    assert events[-1]["reason_code"] == "provider_unavailable"


def test_nostalgia_emit_fail_open(events, monkeypatch):
    """Fail-open: падение эмиссии не рвёт прогон воркера."""

    def _boom(*a, **kw):
        raise RuntimeError("emit broken")

    monkeypatch.setattr(me, "emit_mca_event", _boom)
    stats = {"chats": 1, "candidates": 1, "sent": 1, "skipped": 0, "errors": 0}
    w = _nostalgia_worker(monkeypatch, enabled=True, run_tick=stats)
    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(w._run(manual=False))
    finally:
        loop.close()
    assert out == stats


# ── lore.compile ────────────────────────────────────────────────────────────

def test_lore_start_and_skip_no_profile(events, monkeypatch):
    """Реальный impl-путь: профиля нет → skipped/source_missing."""

    class _Store:
        async def get_profile(self, chat_id):
            return None

    w = LoreWorker(store=_Store())
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(w.generate_for_chat(CHAT_ID))
    finally:
        loop.close()
    assert result == {"status": "skipped", "reason": "no_profile"}
    assert [(e["event_name"], e["outcome"]) for e in events] == [
        ("lore_compile", "start"), ("lore_compile", "skipped")]
    assert events[1]["reason_code"] == "source_missing"
    assert events[0]["chat_id"] == str(CHAT_ID) or \
        events[0]["chat_id"] == CHAT_ID
    _assert_contract_emits(events)


@pytest.mark.parametrize("result,expected", [
    ({"status": "ok", "changed": True}, ("success", None)),
    ({"status": "skipped", "reason": "quiet_window"},
     ("skipped", "retrieval_empty")),
    ({"status": "skipped", "reason": "period_not_due"},
     ("skipped", "intent_not_due")),
    ({"status": "skipped", "reason": "cooldown"}, ("skipped", "cooldown")),
    ({"status": "skipped", "reason": "locked"}, ("skipped", "lock_exhausted")),
    ({"status": "skipped", "reason": "budget_skip"},
     ("skipped", "budget_exceeded")),
    ({"status": "skipped", "reason": "auto_disabled"},
     ("skipped", "disabled")),
    ({"status": "error", "reason": "llm_error"},
     ("failed", "model_unavailable")),
    ({"status": "failed"}, ("failed", None)),
])
def test_lore_terminal_mapping(events, monkeypatch, result, expected):
    w = LoreWorker(store=None)

    async def _impl(chat_id, *, manual=False):
        return result

    w._generate_for_chat_impl = _impl
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(w.generate_for_chat(CHAT_ID))
    finally:
        loop.close()
    assert len(events) == 2
    assert events[1]["outcome"] == expected[0]
    assert events[1].get("reason_code") == expected[1]
    _assert_contract_emits(events)


def test_lore_emit_fail_open(events, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("emit broken")

    monkeypatch.setattr(me, "emit_mca_event", _boom)
    w = LoreWorker(store=None)

    async def _impl(chat_id, *, manual=False):
        return {"status": "ok"}

    w._generate_for_chat_impl = _impl
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(w.generate_for_chat(CHAT_ID))
    finally:
        loop.close()
    assert result == {"status": "ok"}


# ── sleep.dream ─────────────────────────────────────────────────────────────

def _dream_worker(monkeypatch, *, master_on=True, stats=None,
                  raise_in_impl=None) -> DreamWorker:
    async def _resolve(key, *, chat_id=None, default=None, **kw):
        return master_on

    from services import dream_worker as dw
    monkeypatch.setattr(dw, "resolve_setting_cached", _resolve)
    w = DreamWorker(db=object())

    async def _impl(*, manual, only_chat=None):
        if raise_in_impl is not None:
            raise raise_in_impl
        return dict(stats or {})

    w._run_impl = _impl
    return w


def _run_coro(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.mark.parametrize("stats,expected", [
    ({"chats": 1, "clusters": 2, "distilled": 1, "unchanged": 0, "errors": 0,
      "window_skips": 0, "budget_stop": False}, ("success", None)),
    ({"chats": 0, "clusters": 0, "distilled": 0, "unchanged": 0, "errors": 0,
      "window_skips": 0, "budget_stop": False},
     ("skipped", "no_relevant_memory")),
    ({"chats": 1, "clusters": 0, "distilled": 0, "unchanged": 0, "errors": 0,
      "window_skips": 0, "budget_stop": False},
     ("skipped", "no_new_contribution")),
    ({"chats": 1, "clusters": 0, "distilled": 0, "unchanged": 0, "errors": 0,
      "window_skips": 1, "budget_stop": False},
     ("skipped", "schedule_outside_window")),
    ({"chats": 1, "clusters": 1, "distilled": 0, "unchanged": 0, "errors": 0,
      "window_skips": 1, "budget_stop": True},
     ("skipped", "resource_limit")),
    ({"chats": 1, "clusters": 1, "distilled": 0, "unchanged": 1, "errors": 0,
      "window_skips": 0, "budget_stop": False}, ("success", None)),
    ({"chats": 1, "clusters": 1, "distilled": 2, "unchanged": 0, "errors": 0,
      "window_skips": 0, "budget_stop": True}, ("success", "run_partial")),
    ({"chats": 1, "clusters": 1, "distilled": 0, "unchanged": 0, "errors": 1,
      "window_skips": 0, "budget_stop": False},
     ("failed", "model_unavailable")),
])
def test_dream_terminal_mapping(events, monkeypatch, stats, expected):
    w = _dream_worker(monkeypatch, master_on=True, stats=stats)
    _run_coro(w._run(manual=False))
    assert [(e["event_name"], e["outcome"]) for e in events] == [
        ("sleep_dream", "start"), ("sleep_dream", expected[0])]
    assert events[1].get("reason_code") == expected[1]
    assert events[1]["component"] == "sleep.dream"
    _assert_contract_emits(events)


def test_dream_master_off_no_events_manual_emits(events, monkeypatch):
    """Master OFF: авто-тик — событий нет (без шума), manual — есть."""
    w = _dream_worker(monkeypatch, master_on=False,
                      stats={"chats": 1, "clusters": 0, "distilled": 0,
                             "unchanged": 0, "errors": 0, "window_skips": 0,
                             "budget_stop": False})
    _run_coro(w._run(manual=False))
    assert events == []
    _run_coro(w._run(manual=True))
    assert [e["outcome"] for e in events] == ["start", "skipped"]
    _assert_contract_emits(events)


def test_dream_failed_and_reraise_on_exception(events, monkeypatch):
    w = _dream_worker(monkeypatch, master_on=True,
                      raise_in_impl=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        _run_coro(w._run(manual=False))
    assert [(e["event_name"], e["outcome"]) for e in events] == [
        ("sleep_dream", "start"), ("sleep_dream", "failed")]


def test_dream_emit_fail_open(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("emit broken")

    monkeypatch.setattr(me, "emit_mca_event", _boom)
    w = _dream_worker(monkeypatch, master_on=True,
                      stats={"chats": 1, "clusters": 1, "distilled": 1,
                             "unchanged": 0, "errors": 0, "window_skips": 0,
                             "budget_stop": False})
    stats = _run_coro(w._run(manual=False))
    assert stats["distilled"] == 1


# ── persona.traits ──────────────────────────────────────────────────────────

def _traits_worker(monkeypatch, *, persona_on=True, once_result=None,
                   raise_once=None) -> DreamWorker:
    from services import chat_params

    async def _gate(chat_id, key, default=None):
        return persona_on

    monkeypatch.setattr(chat_params, "get_chat_param", _gate)
    w = DreamWorker(db=object())

    async def _once(chat_id, *, now=None, manual=False):
        if raise_once is not None:
            raise raise_once
        return dict(once_result or {})

    w._run_persona_traits_once = _once
    return w


@pytest.mark.parametrize("once_result,expected", [
    ({"status": "ok", "traits": 3}, ("success", None)),
    ({"status": "ok", "traits": 0}, ("skipped", "no_new_contribution")),
    ({"status": "empty", "traits": 0}, ("skipped", "no_relevant_memory")),
    ({"status": "budget", "traits": 0}, ("skipped", "resource_limit")),
    ({"status": "error", "traits": 0}, ("failed", None)),
])
def test_persona_traits_terminal_mapping(events, monkeypatch, once_result,
                                         expected):
    w = _traits_worker(monkeypatch, persona_on=True, once_result=once_result)
    written = _run_coro(w._run_persona_traits_step(CHAT_ID, NOW))
    assert written == once_result["traits"]
    assert [(e["event_name"], e["outcome"]) for e in events] == [
        ("persona_traits", expected[0])]
    assert events[0].get("reason_code") == expected[1]
    assert events[0]["component"] == "persona.traits"
    assert events[0]["chat_id"] in (str(CHAT_ID), CHAT_ID)
    _assert_contract_emits(events)


def test_persona_traits_skipped_disabled(events, monkeypatch):
    w = _traits_worker(monkeypatch, persona_on=False)
    written = _run_coro(w._run_persona_traits_step(CHAT_ID, NOW))
    assert written == 0
    assert len(events) == 1
    assert events[0]["outcome"] == "skipped"
    assert events[0]["reason_code"] == "disabled"


def test_persona_traits_failed_on_exception(events, monkeypatch):
    w = _traits_worker(monkeypatch, persona_on=True,
                       raise_once=RuntimeError("boom"))
    written = _run_coro(w._run_persona_traits_step(CHAT_ID, NOW))
    assert written == 0
    assert len(events) == 1
    assert events[0]["outcome"] == "failed"
    assert "reason_code" not in events[0]


# ── anticliche.run ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,expected", [
    ("ok", ("success", None)),
    ("empty", ("skipped", "no_new_contribution")),
    ("fresh", ("skipped", "cooldown")),
    ("disabled", ("skipped", "disabled")),
    ("budget_skip", ("skipped", "budget_exceeded")),
    ("fetch_error", ("failed", "provider_unavailable")),
    ("llm_error", ("failed", "model_unavailable")),
    ("parse_error", ("failed", "parse_error")),
    ("write_error", ("failed", None)),
])
def test_anticliche_terminal_mapping(events, monkeypatch, status, expected):
    w = AntiClicheWorker()

    async def _impl(*, source=None, force=False):
        return {"status": status, "count": 0, "version": 0, "source": "x"}

    w._refresh_impl = _impl
    _run_coro(w.refresh())
    assert [(e["event_name"], e["outcome"]) for e in events] == [
        ("anticliche_run", "start"), ("anticliche_run", expected[0])]
    assert events[1].get("reason_code") == expected[1]
    assert events[1]["component"] == "anticliche.run"
    _assert_contract_emits(events)


def test_anticliche_disabled_real_path(events, monkeypatch):
    """Реальный ранний выход: флаг OFF → impl возвращает disabled без
    fetch/PG; обёртка даёт пару start+skipped/disabled."""
    from services import anticliche_cache
    monkeypatch.setattr(anticliche_cache, "enabled", lambda: False)
    w = AntiClicheWorker()
    result = _run_coro(w.refresh())
    assert result["status"] == "disabled"
    assert [(e["event_name"], e["outcome"]) for e in events] == [
        ("anticliche_run", "start"), ("anticliche_run", "skipped")]
    assert events[1]["reason_code"] == "disabled"


def test_anticliche_emit_fail_open(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("emit broken")

    monkeypatch.setattr(me, "emit_mca_event", _boom)
    from services import anticliche_cache
    monkeypatch.setattr(anticliche_cache, "enabled", lambda: False)
    w = AntiClicheWorker()
    result = _run_coro(w.refresh())
    assert result["status"] == "disabled"
