"""Раунд 10.19 (F2 direct-chat-budget-unlimited, T-1854/T-1855) — sentinel
безлимита, per-chat резолв бюджета, невозможность ложного sandbox.

Покрытие:
  * sentinel-семантика (`0`=запрет, `<0`=безлимит, `>0`=cap) и изоляция
    семейств (бюджет / контекст / retention — НЕ взаимозаменяемы);
  * per-chat override бьёт глобальный слой (ADR-1018-7 D1) для `chat_usage`;
  * `chat_id=None` → только глобальный слой;
  * консервативные глобальные дефолты (100 / 500 000 — НЕ безлимит);
  * `budget_snapshot`/`budget_exceeded`: `exceeded_metric`, `source`, `day`;
  * `tokens ≪ limit` → НЕ exceeded (ложный sandbox невозможен);
  * внутренняя несогласованность → ERROR + fail-open (exceeded=False);
  * fail-open при недоступном usage (PG down);
  * изоляция контуров: `chat_usage` не трогает `worker_budget`;
  * S10.19-1: валидный `[]` виден в логах (INFO, не только DEBUG).

R17: значения секретов/ключей не используются.
"""
import logging

import pytest

from config.settings import settings
from services import budget_limits as bl
from services import chat_usage
from services import chat_params as cp
from services import hot_config as hot


class _FakeHot:
    """Глобальный слой (bot_settings): заданные ключи, иначе default."""

    def __init__(self, values):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakeChatCache:
    def __init__(self, overrides):
        self.overrides = overrides or {}

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides)}

    async def invalidate_chat(self, chat_id):
        pass


class _FakeConn:
    """Минимальный asyncpg-коннект для UPSERT worker_budget."""

    def __init__(self):
        self.rows = {}                       # (scope, metric) -> used

    async def fetchrow(self, sql, *args):
        key = (args[1], args[2])
        self.rows[key] = self.rows.get(key, 0) + int(args[3])
        return {"used": self.rows[key]}


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


class _FakePgWorker:
    def __init__(self):
        self.conn = _FakeConn()
        self.pool = _FakePool(self.conn)


def _setup(monkeypatch, *, hot_values=None, overrides=None, used=None,
           used_raises=False):
    monkeypatch.setattr(hot, "_cache", _FakeHot(hot_values))
    monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCache(overrides))
    if used_raises:
        async def _boom(pg, chat_id):
            raise RuntimeError("PG down")
        monkeypatch.setattr(chat_usage, "used_today", _boom)
    else:
        async def _used(pg, chat_id):
            return dict(used or {})
        monkeypatch.setattr(chat_usage, "used_today", _used)


# ── sentinel-семантика (§3.1 / ADR-1019-8 D2) ──────────────────────────────

class TestSentinel:
    def test_budget_state_table(self):
        assert bl.budget_state(0) == "forbidden"
        assert bl.budget_state(-1) == "unlimited"
        assert bl.budget_state(-99) == "unlimited"
        assert bl.budget_state(25) == "cap"
        assert bl.budget_state("100") == "cap"
        assert bl.budget_state("abc") == "forbidden"   # мусор → запрет

    def test_is_helpers(self):
        assert bl.is_forbidden(0) and not bl.is_forbidden(-1)
        assert bl.is_unlimited(-1) and not bl.is_unlimited(0)
        assert not bl.is_unlimited(5)
        assert bl.FORBIDDEN == 0 and bl.UNLIMITED == -1

    def test_families_not_interchangeable(self):
        # `0` означает РАЗНОЕ в разных семействах — защита от смешения.
        assert bl.budget_state(0) == "forbidden"
        assert bl.context_state(0) == "unset"
        assert bl.retention_state(0) == "eternal"
        assert bl.retention_state(180) == "cap"
        assert bl.retention_state(-1) == "invalid"
        assert bl.context_state(-1) == "unlimited"
        assert bl.context_state(5000) == "cap"
        # «0 = вечно» из retention НЕ допустимо в бюджете.
        assert bl.retention_state(0) != bl.budget_state(0)


# ── ядро `_exceeds` ─────────────────────────────────────────────────────────

class TestExceeds:
    def test_calls_cap(self):
        assert chat_usage._exceeds(100, 500000, 100, 10, 0) == "calls"

    def test_tokens_cap_with_estimate(self):
        assert chat_usage._exceeds(100, 1000, 1, 999, 2) == "tokens"

    def test_not_exceeded(self):
        assert chat_usage._exceeds(100, 500000, 3, 699, 0) is None

    def test_zero_is_forbidden(self):
        assert chat_usage._exceeds(0, 500000, 0, 0, 0) == "forbidden"
        assert chat_usage._exceeds(100, 0, 0, 0, 0) == "forbidden"

    def test_unlimited_never_exceeds(self):
        assert chat_usage._exceeds(-1, -1, 10 ** 9, 10 ** 9, 0) is None


# ── per-chat резолв + дефолты ──────────────────────────────────────────────

class TestPerChatResolve:
    @pytest.mark.asyncio
    async def test_chat_override_beats_global(self, monkeypatch):
        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 100,
                           chat_usage.KEY_BUDGET_TOKENS: 500000},
               overrides={chat_usage.KEY_BUDGET_REQUESTS: 7})
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["limit_calls"] == 7
        assert snap["source_calls"] == "chat"
        assert snap["limit_tokens"] == 500000
        assert snap["source_tokens"] == "global"

    @pytest.mark.asyncio
    async def test_none_chat_id_ignores_chat_override(self, monkeypatch):
        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 100},
               overrides={chat_usage.KEY_BUDGET_REQUESTS: 7})
        value = await chat_usage._budget_limit_requests(chat_id=None)
        assert value == 100

    @pytest.mark.asyncio
    async def test_conservative_defaults_not_unlimited(self, monkeypatch):
        _setup(monkeypatch)          # пустой hot → env-дефолты
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["limit_calls"] == settings.CHAT_GLOBAL_KEY_BUDGET_REQUESTS
        assert snap["limit_tokens"] == settings.CHAT_GLOBAL_KEY_BUDGET_TOKENS
        assert snap["limit_calls"] == 100
        assert snap["limit_tokens"] == 500000
        assert snap["unlimited"] is False
        assert snap["source_calls"] == "default"

    @pytest.mark.asyncio
    async def test_per_chat_unlimited(self, monkeypatch):
        _setup(monkeypatch,
               overrides={chat_usage.KEY_BUDGET_REQUESTS: -1,
                          chat_usage.KEY_BUDGET_TOKENS: -1},
               used={chat_usage.METRIC_CALLS: 10 ** 6,
                     chat_usage.METRIC_TOKENS: 10 ** 9})
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["unlimited"] is True
        assert snap["exceeded"] is False
        assert snap["exceeded_metric"] is None
        assert snap["source_calls"] == "chat"


# ── снимок, ложный sandbox, fail-open ──────────────────────────────────────

class TestSnapshot:
    @pytest.mark.asyncio
    async def test_prod_symptom_calls_exhausted_tokens_far(self, monkeypatch):
        """Прод-лог: used_calls=25/limit=25, used_tokens=699/limit=100000 →
        exceeded, metric='calls' (не «вообще бюджет»), source диагностируем."""
        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 25,
                           chat_usage.KEY_BUDGET_TOKENS: 100000},
               used={chat_usage.METRIC_CALLS: 25,
                     chat_usage.METRIC_TOKENS: 699})
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["exceeded"] is True
        assert snap["exceeded_metric"] == "calls"
        assert snap["used_tokens"] == 699
        assert snap["source"] == "global"
        assert snap["day"] == str(chat_usage.today())

    @pytest.mark.asyncio
    async def test_no_false_budget_stop_when_tokens_far(self, monkeypatch):
        """Ложный `reason=budget` невозможен: used_tokens ≪ limit → нет стопа."""
        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 25,
                           chat_usage.KEY_BUDGET_TOKENS: 500000},
               used={chat_usage.METRIC_CALLS: 3,
                     chat_usage.METRIC_TOKENS: 699})
        assert await chat_usage.budget_exceeded(object(), -100) is False
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["exceeded"] is False
        assert snap["exceeded_metric"] is None

    @pytest.mark.asyncio
    async def test_zero_limit_is_forbidden(self, monkeypatch):
        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 0},
               used={})
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["exceeded"] is True
        assert snap["exceeded_metric"] == "forbidden"
        assert snap["forbidden"] is True

    @pytest.mark.asyncio
    async def test_failopen_usage_unavailable(self, monkeypatch):
        """PG down: usage недоступно → exceeded=False, unlimited=False (бот жив,
        в sandbox без доказанной причины не уходим); вычисленный source
        сохраняется (снимок не противоречит себе — D-4)."""
        _setup(monkeypatch,
               overrides={chat_usage.KEY_BUDGET_REQUESTS: -1,
                          chat_usage.KEY_BUDGET_TOKENS: -1},
               used_raises=True)
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["exceeded"] is False
        assert snap["unlimited"] is False
        assert snap["forbidden"] is False
        assert snap["source"] == "chat"          # оба лимита из chat-override
        assert snap["source_calls"] == "chat"
        assert snap["source_tokens"] == "chat"

    @pytest.mark.asyncio
    async def test_failopen_keeps_forbidden_visible(self, monkeypatch):
        """`0`-лимит виден даже при недоступном PG: forbidden=True, source
        вычислен (не хардкод 'default') — D-4 ревью Батча B."""
        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 0,
                           chat_usage.KEY_BUDGET_TOKENS: 500000},
               used_raises=True)
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["exceeded"] is False     # fail-open: без доказанного usage
        assert snap["forbidden"] is True     # но запрет честно виден
        assert snap["unlimited"] is False
        assert snap["source"] == "global"
        assert snap["source_calls"] == "global"
        assert snap["source_tokens"] == "global"

    @pytest.mark.asyncio
    async def test_inconsistent_state_logs_error_and_failopen(
            self, monkeypatch, caplog):
        _setup(monkeypatch, used={chat_usage.METRIC_CALLS: 1})
        monkeypatch.setattr(chat_usage, "_exceeds",
                            lambda *a, **kw: "bogus-metric")
        with caplog.at_level(logging.ERROR, logger="services.chat_usage"):
            snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["exceeded"] is False
        assert snap["exceeded_metric"] is None
        assert any("inconsistent budget state" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_key_status_additive_fields(self, monkeypatch):
        _setup(monkeypatch,
               overrides={chat_usage.KEY_BUDGET_REQUESTS: -1},
               used={chat_usage.METRIC_CALLS: 5})
        status = await chat_usage.key_status(object(), -100)
        # старые поля (R16) сохранены
        assert status["calls"]["used"] == 5
        assert status["calls"]["limit"] == -1
        # аддитивные
        assert status["calls"]["unlimited"] is True
        assert status["calls"]["forbidden"] is False
        assert status["calls"]["source"] == "chat"
        assert status["tokens"]["unlimited"] is False


# ── изоляция контуров (T-1795) ─────────────────────────────────────────────

class TestContourIsolation:
    @pytest.mark.asyncio
    async def test_worker_budget_resolves_independently(self, monkeypatch):
        """Изоляция контуров: фон резолвит лимиты собственным `_metric_limit`
        (per-chat), значения direct-бюджета на них не влияют."""
        from services import worker_budget as wb
        monkeypatch.setattr(hot, "_cache", _FakeHot({
            chat_usage.KEY_BUDGET_REQUESTS: -1,
            chat_usage.KEY_BUDGET_TOKENS: -1,
        }))
        assert await wb._metric_limit("chat:-1", wb.METRIC_CALLS) == \
            settings.WORKER_DAILY_LLM_CALLS_PER_CHAT == 60
        assert await wb._metric_limit("chat:-1", wb.METRIC_TOKENS) == \
            settings.WORKER_DAILY_LLM_TOKENS_PER_CHAT == 300000
        # direct-бюджет и фон — разные пространства ключей.
        assert wb.LIMIT_CALLS_PER_CHAT != chat_usage.KEY_BUDGET_REQUESTS

    def test_worker_settings_per_chat_defaults_unchanged(self):
        """Фон per-chat env-дефолты (F2 §4.5): 60 / 300 000 — предохранитель,
        НЕ безлимит."""
        assert settings.WORKER_DAILY_LLM_CALLS_PER_CHAT == 60
        assert settings.WORKER_DAILY_LLM_TOKENS_PER_CHAT == 300000


# ── sentinel фонового контура (D-1/D-2: `-1`=безлимит, `0`=запрет) ─────────

class TestWorkerBudgetSentinel:
    @pytest.mark.asyncio
    async def test_metric_limit_uses_settings_defaults(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch)                  # пустой hot → env-дефолты
        assert await wb._metric_limit("chat:-1", wb.METRIC_CALLS) == 60
        assert await wb._metric_limit("chat:-1", wb.METRIC_TOKENS) == 300000
        assert await wb._metric_limit("global", wb.METRIC_CALLS) == \
            settings.WORKER_DAILY_LLM_CALLS_GLOBAL
        assert await wb._metric_limit("global", wb.METRIC_TOKENS) == \
            settings.WORKER_DAILY_LLM_TOKENS_GLOBAL

    @pytest.mark.asyncio
    async def test_metric_limit_per_chat_override(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch,
               overrides={wb.LIMIT_CALLS_PER_CHAT: -1},
               hot_values={wb.LIMIT_CALLS_PER_CHAT: 60})
        # per-chat override побеждает глобальный слой (60 → -1).
        assert await wb._metric_limit("chat:-100", wb.METRIC_CALLS) == -1

    @pytest.mark.asyncio
    async def test_consume_unlimited_records_and_allows(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch, overrides={wb.LIMIT_CALLS_PER_CHAT: -1})
        pg = _FakePgWorker()
        for _ in range(50):
            assert await wb.consume(pg, "chat:-100", "llm_calls", 1) is True
        # расход всё равно учитывается (безлимит снимает cap, не учёт)
        assert pg.conn.rows[("chat:-100", "llm_calls")] == 50

    @pytest.mark.asyncio
    async def test_consume_zero_is_forbidden(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch, overrides={wb.LIMIT_CALLS_PER_CHAT: 0})
        pg = _FakePgWorker()
        assert await wb.consume(pg, "chat:-100", "llm_calls", 1) is False

    @pytest.mark.asyncio
    async def test_consume_cap_still_applies(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch, overrides={wb.LIMIT_CALLS_PER_CHAT: 2})
        pg = _FakePgWorker()
        assert await wb.consume(pg, "chat:-100", "llm_calls", 1) is True
        assert await wb.consume(pg, "chat:-100", "llm_calls", 1) is True
        assert await wb.consume(pg, "chat:-100", "llm_calls", 1) is False

    def test_allowed_workers_sentinel(self):
        from services import worker_budget as wb
        ids = ("nostalgia", "lore", "dream")
        assert all(wb.allowed_workers(ids, 10 ** 9, -1).values())    # безлимит
        assert not any(wb.allowed_workers(ids, 0, 0).values())       # запрет
        cap = wb.allowed_workers(ids, 10, 10)                        # cap
        assert cap["nostalgia"] is True and cap["dream"] is False


# ── S10.19-1: валидный `[]` виден в логах ──────────────────────────────────

class TestEmptyValidVisibility:
    def test_first_event_is_info_with_empty_total(self, monkeypatch, caplog):
        from services import summary_memory as sm
        monkeypatch.setattr(sm, "_memorize_empty_state", {})
        monkeypatch.setattr(sm, "_memorize_empty_totals", {})
        with caplog.at_level(logging.INFO, logger="services.summary_memory"):
            sm._log_empty_valid(-100, "chat_history")
        infos = [r for r in caplog.records
                 if r.levelno == logging.INFO
                 and "empty valid list" in r.getMessage()]
        assert len(infos) == 1
        assert "empty_total=1" in infos[0].getMessage()

    def test_repeat_within_window_is_debug(self, monkeypatch, caplog):
        from services import summary_memory as sm
        monkeypatch.setattr(sm, "_memorize_empty_state", {})
        monkeypatch.setattr(sm, "_memorize_empty_totals", {})
        with caplog.at_level(logging.DEBUG, logger="services.summary_memory"):
            sm._log_empty_valid(-100, "chat_history")
            sm._log_empty_valid(-100, "chat_history")
        infos = [r for r in caplog.records
                 if r.levelno == logging.INFO
                 and "empty valid list" in r.getMessage()]
        assert len(infos) == 1          # повтор подавлен (rate-limit 60с)
        assert sm._memorize_empty_totals[(-100, "chat_history")] == 2

    def test_dictionaries_bounded(self, monkeypatch):
        from services import summary_memory as sm
        monkeypatch.setattr(sm, "_memorize_empty_state", {})
        monkeypatch.setattr(sm, "_memorize_empty_totals", {})
        sm._memorize_empty_totals.update(
            {(i, "x"): 1 for i in range(sm._MEMORIZE_WARN_STATE_MAX + 50)})
        sm._evict_memorize_state()
        assert len(sm._memorize_empty_totals) <= sm._MEMORIZE_WARN_STATE_MAX
