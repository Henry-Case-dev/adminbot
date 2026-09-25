"""A5 `image-daily-limit-round1026` (ADR-1026-17, Risk R3) — adversarial-тесты
атомарного резерва/журнала/учёта изображений (T-3599).

Покрытие (по одной приёмочной сцене на тест):
  A1 reserve→commit happy path (квота ровно один раз; журнал committed);
  A2 SC-A5-04 гонка: остаток 1, два параллельных резерва → ровно один;
  A3 deny не расходует; сбой генерации → release возвращает квоту;
  A4 идемпотентность: тот же idem_key дважды → no double spend;
  A5 сбой доставки → committed + delivery_failed, без второй генерации;
  A6 per-chat TZ (day/next_reset) + смена лимита не обнуляет used;
  A7 kill-switch OFF → legacy; fail-open PG → failopen без частичного расхода.

PG-зависимые пути используют минимальный in-memory stub (эмулирует атомарность
conditional UPSERT одиночной синхронной мутацией; транзакция — snapshot/rollback).
R17: только id/коды/числа; реальные секреты/URL не используются.
"""
from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from services import budget_gate
from services import image_generation as ig
from services import telegram_send
from services import worker_budget as wb


# ── Минимальный in-memory PG-stub (атомарность = синхронная мутация) ────────

class _Tx:
    def __init__(self, conn):
        self.conn = conn
        self.snap = None

    async def __aenter__(self):
        self.snap = self.conn._snapshot()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.conn._restore(self.snap)
        return False


class _Conn:
    def __init__(self, state):
        self.s = state

    def _snapshot(self):
        return (
            dict(self.s["budget"]),
            {k: dict(v) for k, v in self.s["res"].items()},
        )

    def _restore(self, snap):
        budget, res = snap
        self.s["budget"] = budget
        self.s["res"] = res

    def transaction(self):
        return _Tx(self)

    async def fetchrow(self, sql, *args):
        await asyncio.sleep(0)                     # точка межзадачного yield
        if sql is wb.RESERVATION_INSERT_SQL:
            key, chat_id, source, message_id, day = args
            if key in self.s["res"]:
                return None
            self.s["res"][key] = {
                "status": "reserved", "error_code": "", "delivery_failed": False,
                "day": day, "chat_id": chat_id, "source": source,
                "message_id": message_id,
                "created_at": datetime.datetime.now(
                    datetime.timezone.utc),
            }
            return {"reservation_key": key}
        if sql is wb.RESERVATION_SELECT_SQL:
            (key,) = args
            r = self.s["res"].get(key)
            return ({"status": r["status"], "error_code": r["error_code"]}
                    if r else None)
        if sql is wb.RESERVATION_RELEASE_SELECT_SQL:
            (key,) = args
            r = self.s["res"].get(key)
            return ({"status": r["status"], "day": r["day"],
                     "chat_id": r["chat_id"], "created_at": r["created_at"]}
                    if r else None)
        if sql is wb.RESERVATION_RELEASE_SQL:
            key, error = args
            r = self.s["res"].get(key)
            if r and r["status"] == "reserved":
                r["status"] = "released"
                r["error_code"] = error
                return {"reservation_key": key}
            return None
        if sql is wb.RESERVE_INCREMENT_SQL:
            day, scope, metric, limit = args
            used = self.s["budget"].get((day, scope, metric), 0)
            if used >= int(limit):                 # атомарная проверка
                return None
            self.s["budget"][(day, scope, metric)] = used + 1
            return {"used": used + 1}
        if sql is wb.RESERVE_RELEASE_SQL:
            day, scope, metric = args
            used = self.s["budget"].get((day, scope, metric), 0)
            new = max(used - 1, 0)
            self.s["budget"][(day, scope, metric)] = new
            return {"used": new}
        if sql is wb.UPSERT_SQL:
            day, scope, metric, amount = args
            used = self.s["budget"].get((day, scope, metric), 0) + int(amount)
            self.s["budget"][(day, scope, metric)] = used
            return {"used": used}
        if sql is wb.SELECT_ROW_SQL:
            day, scope, metric = args
            used = self.s["budget"].get((day, scope, metric))
            return {"used": used} if used is not None else None
        if sql is wb.RESERVATION_DAY_SQL:
            chat_id, day = args
            groups: dict[str, dict] = {}
            for r in self.s["res"].values():
                if r["chat_id"] == chat_id and r["day"] == day:
                    g = groups.setdefault(r["status"], {"n": 0, "df": 0})
                    g["n"] += 1
                    g["df"] += 1 if r["delivery_failed"] else 0
            return [{"status": k, "n": v["n"], "df": v["df"]}
                    for k, v in groups.items()]
        raise AssertionError("unexpected fetchrow: %s" % sql)

    async def fetch(self, sql, *args):
        await asyncio.sleep(0)
        return await self.fetchrow(sql, *args)

    async def execute(self, sql, *args):
        await asyncio.sleep(0)
        if sql is wb.RESERVE_RELEASE_SQL:
            day, scope, metric = args
            used = self.s.budget.get((day, scope, metric), 0)
            new = max(used - 1, 0)
            self.s.budget[(day, scope, metric)] = new
            return "UPDATE 1"
        if sql is wb.RESERVATION_STATUS_SQL:
            key, status, error = args
            self.s["res"][key]["status"] = status
            self.s["res"][key]["error_code"] = error
            return "UPDATE 1"
        if sql is wb.RESERVATION_RELEASE_SQL:
            key, error = args
            r = self.s["res"].get(key)
            if r and r["status"] == "reserved":
                r["status"] = "released"
                r["error_code"] = error
                return "UPDATE 1"
            return None
        if sql is wb.RESERVATION_DELIVERY_SQL:
            key, status, df = args
            r = self.s["res"].get(key)
            if r and r["status"] in ("reserved", "committed"):
                r["status"] = status
                r["delivery_failed"] = bool(df)
                return "UPDATE 1"
            return None
        if sql is wb.RESERVATION_PURGE_SQL:
            return "DELETE 0"
        raise AssertionError("unexpected execute: %s" % sql)


class _Acquire:
    def __init__(self, state, conn_cls):
        self.state = state
        self.conn_cls = conn_cls

    async def __aenter__(self):
        return self.conn_cls(self.state)

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, state, conn_cls=_Conn):
        self.state = state
        self.conn_cls = conn_cls

    def acquire(self):
        return _Acquire(self.state, self.conn_cls)


class _State:
    def __init__(self):
        self.budget = {}
        self.res = {}

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)


class _BoomConn(_Conn):
    """Соединение, падающее на shared-инкременте (модель PG-сбоя в середине)."""

    async def fetchrow(self, sql, *args):
        if sql is wb.RESERVE_INCREMENT_SQL:
            raise RuntimeError("pg boom")
        return await super().fetchrow(sql, *args)


def make_pg(state=None, conn_cls=_Conn):
    state = state or _State()
    return SimpleNamespace(pool=_Pool(state, conn_cls)), state


@pytest.fixture()
def env(monkeypatch):
    """Изолированная PG-среда: fake pool + детерминированные лимиты/TZ."""
    pg, state = make_pg()
    limits = {"global": 200, "chat": 60}

    async def _limit(scope, metric):
        return limits["global"] if scope == "global" else limits["chat"]

    async def _resolve(key, *, chat_id, default):
        return limits["chat"]

    async def _budgets_on(*a, **kw):
        return True

    monkeypatch.setattr(wb, "_metric_limit", _limit)
    monkeypatch.setattr(wb, "_resolve_limit", _resolve)
    monkeypatch.setattr(wb, "_chat_tz_name", lambda chat_id: "UTC")
    monkeypatch.setattr(budget_gate, "budgets_enabled", _budgets_on)
    wb.set_worker_budget_pg(pg)
    _reset_purge()
    yield pg, state, limits
    wb.set_worker_budget_pg(None)


def _reset_purge():
    wb._last_purge_day = ""


def _set_kill_switch(monkeypatch, enabled: bool) -> None:
    """Патч env-only киль-свитча на КЛАССЕ настроек, который реально читает
    `image_generation` (после `importlib.reload(config.settings)` класс
    `ig.settings` может отличаться от `config.settings.Settings` — тот же
    приём, что в `conftest._system2_flags_off_by_default`)."""
    from config.settings import Settings
    classes = {Settings, type(ig.settings), type(wb.settings)}
    for _cls in classes:
        if hasattr(_cls, "IMAGE_DAILY_LIMIT_ENABLED"):
            monkeypatch.setattr(_cls, "IMAGE_DAILY_LIMIT_ENABLED", enabled)


# ── A1: reserve→commit happy path ───────────────────────────────────────────

class TestA1HappyPath:
    @pytest.mark.asyncio
    async def test_reserve_commit_once(self, env):
        pg, state, _ = env
        key = "-1000:101:direct"
        res = await wb.reserve_image(pg, chat_id=-1000, idem_key=key,
                                     source="direct", message_id=101)
        assert res.ok is True
        assert res.reason == "ok"
        assert res.status == "reserved"

        shared_key = (wb.today(), "global", wb.METRIC_IMAGE_CALLS)
        chat_key = (wb.image_day(-1000), "chat:-1000", wb.METRIC_IMAGE_CALLS)
        assert state.budget[shared_key] == 1
        assert state.budget[chat_key] == 1

        await wb.commit_image(pg, key)
        assert state.res[key]["status"] == "committed"
        assert state.res[key]["delivery_failed"] is False
        # Ровно одно списание — commit не инкрементирует повторно.
        assert state.budget[shared_key] == 1
        assert state.budget[chat_key] == 1


# ── A2: SC-A5-04 — гонка при остатке 1 ──────────────────────────────────────

class TestA2Race:
    @pytest.mark.asyncio
    async def test_two_concurrent_reserves_exactly_one(self, env):
        pg, state, limits = env
        limits["global"] = 1
        limits["chat"] = 1
        results = await asyncio.gather(
            wb.reserve_image(pg, chat_id=-2000, idem_key="-2000:1:direct",
                             source="direct", message_id=1),
            wb.reserve_image(pg, chat_id=-2000, idem_key="-2000:2:direct",
                             source="direct", message_id=2),
        )
        ok = [r.ok for r in results]
        assert sorted(ok) == [False, True]           # ровно один резерв
        assert sorted(r.status for r in results) == ["denied", "reserved"]
        # Отказ не превышает лимит и не теряет квоту.
        shared_key = (wb.today(), "global", wb.METRIC_IMAGE_CALLS)
        chat_key = (wb.image_day(-2000), "chat:-2000", wb.METRIC_IMAGE_CALLS)
        assert state.budget[shared_key] == 1          # used ≤ limit = 1
        assert state.budget[chat_key] == 1


# ── A3: deny без расхода; release возвращает квоту ─────────────────────────

class TestA3DenyRelease:
    @pytest.mark.asyncio
    async def test_deny_does_not_consume(self, env):
        pg, state, limits = env
        limits["global"] = 200
        limits["chat"] = 1
        chat_key = (wb.image_day(-3000), "chat:-3000", wb.METRIC_IMAGE_CALLS)
        state.budget[chat_key] = 1                    # остаток 0

        res = await wb.reserve_image(pg, chat_id=-3000,
                                     idem_key="-3000:7:direct",
                                     source="direct", message_id=7)
        assert res.ok is False
        assert res.reason == "limit_chat"
        assert res.status == "denied"
        shared_key = (wb.today(), "global", wb.METRIC_IMAGE_CALLS)
        assert state.budget[shared_key] == 0          # shared-инкремент откачен
        assert state.budget[chat_key] == 1            # отказ не расходует

    @pytest.mark.asyncio
    async def test_generation_failure_release_restores(self, env):
        pg, state, _ = env
        key = "-3001:8:tool"
        res = await wb.reserve_image(pg, chat_id=-3001, idem_key=key,
                                     source="tool", message_id=8)
        assert res.ok is True
        shared_key = (wb.today(), "global", wb.METRIC_IMAGE_CALLS)
        chat_key = (wb.image_day(-3001), "chat:-3001", wb.METRIC_IMAGE_CALLS)
        assert state.budget[shared_key] == 1
        assert state.budget[chat_key] == 1

        await wb.release_image(pg, key, error_code="provider_error",
                               chat_id=-3001)
        assert state.res[key]["status"] == "released"
        assert state.res[key]["error_code"] == "provider_error"
        assert state.budget[shared_key] == 0          # квота возвращена
        assert state.budget[chat_key] == 0
        # Повторный release не откатывает дважды (guard reserved→released).
        await wb.release_image(pg, key, error_code="provider_error",
                               chat_id=-3001)
        assert state.budget[shared_key] == 0
        assert state.budget[chat_key] == 0


# ── A4: идемпотентность D3 ──────────────────────────────────────────────────

class TestA4Idempotency:
    @pytest.mark.asyncio
    async def test_same_key_no_double_spend(self, env):
        pg, state, _ = env
        key = "-4000:55:direct"
        first = await wb.reserve_image(pg, chat_id=-4000, idem_key=key,
                                       source="direct", message_id=55)
        assert first.ok is True and first.status == "reserved"
        second = await wb.reserve_image(pg, chat_id=-4000, idem_key=key,
                                        source="direct", message_id=55)
        assert second.ok is True
        assert second.reason == "already"
        assert second.status == "reserved"
        shared_key = (wb.today(), "global", wb.METRIC_IMAGE_CALLS)
        chat_key = (wb.image_day(-4000), "chat:-4000", wb.METRIC_IMAGE_CALLS)
        assert state.budget[shared_key] == 1          # без двойного списания
        assert state.budget[chat_key] == 1

        await wb.commit_image(pg, key)
        third = await wb.reserve_image(pg, chat_id=-4000, idem_key=key,
                                       source="direct", message_id=55)
        assert third.ok is True and third.reason == "already"
        assert third.status == "committed"
        assert state.budget[shared_key] == 1
        assert state.budget[chat_key] == 1

    @pytest.mark.asyncio
    async def test_replay_denied_returns_prior_outcome(self, env):
        pg, state, limits = env
        limits["global"] = 200
        limits["chat"] = 1
        assert (await wb.reserve_image(pg, chat_id=-4100, idem_key="A",
                                       source="direct")).ok is True
        denied = await wb.reserve_image(pg, chat_id=-4100, idem_key="B",
                                        source="direct")
        assert denied.ok is False and denied.status == "denied"
        replay = await wb.reserve_image(pg, chat_id=-4100, idem_key="B",
                                        source="direct")
        assert replay.ok is False
        assert replay.reason == "already"
        assert replay.status == "denied"
        assert replay.error_code == "limit_chat"
        shared_key = (wb.today(), "global", wb.METRIC_IMAGE_CALLS)
        assert state.budget[shared_key] == 1          # отказ не списан повторно


# ── A5: сбой доставки → commit + delivery_failed, без повтора ───────────────

class TestA5DeliveryFailure:
    @pytest.mark.asyncio
    async def test_send_failure_commits_and_no_second_generation(
            self, env, monkeypatch):
        pg, state, _ = env
        calls = {"n": 0}

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 consume_budget=True, **kw):
            calls["n"] += 1
            return ig.GenerationResult(ok=True, reason="ok",
                                       content=b"\x89PNG", filename="x.png")

        async def _send_boom(*a, **kw):
            raise RuntimeError("telegram down")

        monkeypatch.setattr(ig, "generate", _fake_generate)
        monkeypatch.setattr(telegram_send, "send_photo", _send_boom)

        res = await ig.generate_and_send(object(), -5000, "prompt",
                                         reply_to_message_id=77,
                                         source="direct")
        assert res.ok is False
        assert res.reason == "send_failed"
        key = "-5000:77:direct"
        assert state.res[key]["status"] == "committed"
        assert state.res[key]["delivery_failed"] is True
        assert calls["n"] == 1                        # только одна генерация

        # Replay того же message_id: повторной платной генерации НЕТ.
        res2 = await ig.generate_and_send(object(), -5000, "prompt",
                                          reply_to_message_id=77,
                                          source="direct")
        assert res2.ok is True and res2.reason == "already"
        assert calls["n"] == 1
        shared_key = (wb.today(), "global", wb.METRIC_IMAGE_CALLS)
        assert state.budget[shared_key] == 1


# ── A6: per-chat TZ / сброс / лимит-смена ───────────────────────────────────

class TestA6Timezone:
    @pytest.mark.asyncio
    async def test_day_and_next_reset_use_chat_tz(self, env, monkeypatch):
        tz = "Pacific/Kiritimati"                     # UTC+14
        monkeypatch.setattr(wb, "_chat_tz_name", lambda chat_id: tz)
        assert wb.image_timezone(-6000) == tz
        assert wb.image_day(-6000) == \
            datetime.datetime.now(ZoneInfo(tz)).date()
        now = datetime.datetime.now(ZoneInfo(tz))
        nxt = wb.image_next_reset(-6000)
        assert (nxt.hour, nxt.minute, nxt.second) == (0, 0, 0)
        assert now < nxt <= now + datetime.timedelta(days=1)

    @pytest.mark.asyncio
    async def test_limit_change_does_not_zero_used(self, env, monkeypatch):
        pg, state, limits = env
        tz = "Pacific/Kiritimati"
        monkeypatch.setattr(wb, "_chat_tz_name", lambda chat_id: tz)
        limits["chat"] = 5
        res = await wb.reserve_image(pg, chat_id=-6001, idem_key="-6001:1:tool",
                                     source="tool", message_id=1)
        assert res.ok is True
        limits["chat"] = 10                           # смена лимита
        summary = await wb.image_usage_summary(pg, -6001)
        assert summary["day"] == str(wb.image_day(-6001))
        assert summary["timezone"] == tz
        assert summary["used"] == 1                   # used сохранён
        assert summary["limit"] == 10
        chat_key = (wb.image_day(-6001), "chat:-6001", wb.METRIC_IMAGE_CALLS)
        assert state.budget[chat_key] == 1


# ── A7: kill-switch/master OFF legacy + fail-open ───────────────────────────

class TestA7KillSwitchFailOpen:
    @pytest.mark.asyncio
    async def test_kill_switch_off_is_legacy(self, env, monkeypatch):
        pg, state, _ = env
        _set_kill_switch(monkeypatch, False)

        async def _boom(*a, **kw):
            raise AssertionError("reserve_image must not run when OFF")

        monkeypatch.setattr(wb, "reserve_image", _boom)
        action, key, reason = await ig._reserve_or_consume(
            -8000, source="direct", message_id=1, correlation_id=None)
        assert (action, key, reason) == ("legacy", "", "kill_switch_off")
        assert state.res == {} and state.budget == {}

    @pytest.mark.asyncio
    async def test_kill_switch_off_generate_consumes_like_baseline(
            self, env, monkeypatch):
        _set_kill_switch(monkeypatch, False)
        seen = {}

        async def _g(prompt, *, chat_id=None, correlation_id=None,
                     consume_budget=True, **kw):
            seen["consume"] = consume_budget
            return ig.GenerationResult(ok=True, reason="ok", content=b"x")

        async def _send(*a, **kw):
            return None

        monkeypatch.setattr(ig, "generate", _g)
        monkeypatch.setattr(telegram_send, "send_photo", _send)
        res = await ig.generate_and_send(object(), -8001, "p",
                                         reply_to_message_id=2,
                                         source="direct")
        assert res.ok is True
        assert seen["consume"] is True               # legacy consume внутри generate

    @pytest.mark.asyncio
    async def test_master_budget_off_is_legacy(self, env, monkeypatch):
        async def _off(*a, **kw):
            return False

        monkeypatch.setattr(budget_gate, "budgets_enabled", _off)
        action, key, reason = await ig._reserve_or_consume(
            -8002, source="direct", message_id=3, correlation_id=None)
        assert (action, key, reason) == ("legacy", "", "budgets_off")

    @pytest.mark.asyncio
    async def test_pg_error_failopen_no_partial_consumption(
            self, env, monkeypatch):
        pg2, state2 = make_pg(conn_cls=_BoomConn)
        res = await wb.reserve_image(pg2, chat_id=-8003,
                                     idem_key="-8003:4:direct",
                                     source="direct", message_id=4)
        assert res.ok is True
        assert res.reason == "failopen"
        assert res.status == ""
        # Транзакция целиком откатилась: ни счётчиков, ни журнала.
        assert state2.budget == {}
        assert state2.res == {}

        wb.set_worker_budget_pg(pg2)
        action, key, reason = await ig._reserve_or_consume(
            -8003, source="direct", message_id=4, correlation_id=None)
        assert (action, key, reason) == ("legacy", "", "failopen")
