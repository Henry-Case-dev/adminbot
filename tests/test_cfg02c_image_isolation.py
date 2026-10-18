"""CFG-02C — жёсткая изоляция `user_image` ↔ `summary_cover` (13 строк слайса).

Покрытие строк карты `plans/features/cfg/requirements-map.json` (слайс CFG-02C):

  * CFG-02C.1 / CFG-02C.7 / CFG-02.AC8 — двусторонний негатив счётчиков:
    user daily `0` + freq ON → Base/Style Edit работают; обложки не трогают
    `chat:<id>.image_calls` и частотные заряды; пользовательский мем не
    создаёт строк журнала `summary_cover` и не расходует квоту Summary;
  * CFG-02C.2 — явный тип потребления от call-site до журнала
    (`user_image` | `summary_cover:{base,styled_edit,retry_recovery,fallback}`),
    не из текста промпта; исторические строки не переклассифицируются;
  * CFG-02C.3 — правила Summary сохранены: styled edit / recovery / fallback
    не списывают image-бюджет, повторный styled-запуск не удваивает платный
    вызов, в user-витрине обложек нет;
  * CFG-02C.4 — общий техбюджет (`WORKER_DAILY_IMAGE_CALLS_GLOBAL`) остаётся
    отдельным shared-контуром: отказ по нему называет технический бюджет и
    shared-TZ (не «пользовательскую квоту» чата), расход показывается
    раздельно по типам операций;
  * CFG-02C.6 — параллель/ошибки/рестарт: изоляция и атомарность сохранены,
    двойных списаний и переноса расхода между контурами нет;
  * CFG-02C.5 — витрина: «Пользовательские изображения» + «Обложки сводок
    здесь не учитываются» + разбивка агрегата по источникам.

TEST-LIFECYCLE: CONTRACT owner=CFG-02C (изоляция учёта user_image/summary_cover)
TEST-LIFECYCLE: REGRESSION owner=CFG-02C (дефект-класс: обложка списывала
per-chat `image_calls`, shared-отказ маскировался под пользовательскую квоту)
"""
from __future__ import annotations

import asyncio
import datetime
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings                        # noqa: E402
from services import budget_gate                            # noqa: E402
from services import capability_registry as caps             # noqa: E402
from services import image_generation as ig                  # noqa: E402
from services import lore_runtime                            # noqa: E402
from services import persistent_throttling as pt             # noqa: E402
from services import telegram_send                           # noqa: E402
from services import worker_budget as wb                     # noqa: E402
from services.database import DatabaseService                # noqa: E402
from tests.test_image_daily_limit_round1026 import (         # noqa: E402
    _Conn, _reset_purge, make_pg)

JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

CHAT = -1009101
CHAT_OTHER = -1009102
USER_A = 111
USER_B = 222

QUOTA_KEY = "limits.image_daily_limit"
FREQ_ENABLED_KEY = "limits.image_freq_limit_enabled"
FREQ_BURST_KEY = "limits.image_freq_limit_burst"
FREQ_COOLDOWN_KEY = "limits.image_freq_limit_cooldown_seconds"
FREQ_MODE_KEY = "limits.image_freq_limit_mode"

SHARED_TZ = "Asia/Yekaterinburg"
CHAT_TZ = "Europe/Moscow"

# Контрактные значения типа (строгий pin — отдельный тест проверяет константы).
COVER = getattr(ig, "CONSUMPTION_COVER", "summary_cover")
USER_TYPE = getattr(ig, "CONSUMPTION_USER", "user_image")
STAGE_BASE = getattr(ig, "COVER_STAGE_BASE", "base")
STAGE_STYLED = getattr(ig, "COVER_STAGE_STYLED_EDIT", "styled_edit")
STAGE_RECOVERY = getattr(ig, "COVER_STAGE_RETRY_RECOVERY", "retry_recovery")
STAGE_FALLBACK = getattr(ig, "COVER_STAGE_FALLBACK", "fallback")


# ═══ окружение: PG-стаб + слои настроек + runtime SQLite (throttle_state) ═══

def _set_env(name: str, value, monkeypatch) -> None:
    classes = {Settings, type(ig.settings), type(wb.settings)}
    for _cls in classes:
        if hasattr(_cls, name):
            monkeypatch.setattr(_cls, name, value)


class _IsoConn(_Conn):
    """PG-стаб + read-only пути квоты/агрегатов (по фактическому состоянию)."""

    async def fetch(self, sql, *args):
        if sql is wb.SELECT_ALL_SQL:
            day = args[0]
            return [{"day": day, "scope": scope, "metric": metric,
                     "used": used}
                    for (d, scope, metric), used in sorted(
                        self.s["budget"].items()) if d == day]
        if sql is wb.SELECT_SQL:
            day, scope = args
            return [{"day": day, "scope": scope, "metric": metric,
                     "used": used}
                    for (d, s, metric), used in sorted(
                        self.s["budget"].items())
                    if d == day and s == scope]
        return await super().fetch(sql, *args)


def _noop_send():
    async def _send(*a, **kw):
        return None
    return _send


def _fake_generate_factory(calls: list, *, results=None):
    """Фейковый провайдер: results — очередь GenerationResult (или ok)."""
    queue = list(results or [])

    async def _fake(prompt, *, chat_id=None, correlation_id=None,
                    consume_budget=True, **kw):
        calls.append({"prompt": prompt, "consume_budget": consume_budget})
        if queue:
            return queue.pop(0)
        return ig.GenerationResult(ok=True, reason="ok", content=b"x")
    return _fake


def _enable_freq(env, *, burst=1, cooldown=600.0, mode="per_chat") -> None:
    env.hot[FREQ_ENABLED_KEY] = True
    env.hot[FREQ_BURST_KEY] = burst
    env.hot[FREQ_COOLDOWN_KEY] = cooldown
    env.hot[FREQ_MODE_KEY] = mode


async def _throttle_rows(db) -> list[tuple]:
    cur = await db.db.execute(
        "SELECT chat_id, user_id, burst_left, last_ts FROM throttle_state "
        "WHERE scope = ?", (pt.IMAGE_FREQ_SCOPE,))
    rows = await cur.fetchall()
    return [tuple(r) for r in rows]


def _chat_key(chat_id: int) -> tuple:
    return (wb.image_day(chat_id), f"chat:{chat_id}", wb.METRIC_IMAGE_CALLS)


def _shared_key() -> tuple:
    return (wb.today(), "global", wb.METRIC_IMAGE_CALLS)


def _chat_used(env, chat_id: int) -> int:
    return int(env.state.budget.get(_chat_key(chat_id), 0))


def _shared_used(env) -> int:
    return int(env.state.budget.get(_shared_key(), 0))


def _cover_rows(env) -> list[dict]:
    return [r for r in env.state.res.values()
            if str(r.get("source", "")).startswith("summary_cover")]


def _user_rows(env) -> list[dict]:
    return [r for r in env.state.res.values()
            if not str(r.get("source", "")).startswith("summary_cover")]


@pytest.fixture()
def hot(monkeypatch):
    from services import hot_config as hot_mod
    store: dict = {}

    class _FakeConfigCache:
        def get(self, key, default=None):
            return store.get(key, default)

    monkeypatch.setattr(hot_mod, "_cache", _FakeConfigCache())
    return store


@pytest.fixture()
def overrides(monkeypatch):
    from services import chat_params as cp
    store: dict = {}

    class _FakeChatCache:
        async def get_chat_params(self, chat_id):
            return {"overrides": dict(store.get(int(chat_id), {}))}

        async def get_chat_params_checked(self, chat_id):
            return {"overrides": dict(store.get(int(chat_id), {}))}, True

    monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCache())
    return store


@pytest.fixture()
def wall(monkeypatch):
    state = {"now": 1_800_000_000.0}

    class FakeTime:
        @staticmethod
        def time():
            return state["now"]

    monkeypatch.setattr(pt, "time", FakeTime)
    return state


@pytest_asyncio.fixture()
async def env(monkeypatch, hot, overrides, wall, tmp_path):
    """Изолированная среда на ФАКТИЧЕСКОМ резолве лимитов (R9): слой настроек
    (`hot` = global, `overrides` = чат) читается реальным `worker_settings`
    (без патча `_metric_limit`/`_resolve_limit`), shared-потолок — env."""
    pg, state = make_pg(conn_cls=_IsoConn)

    async def _budgets_on(*a, **kw):
        return True

    # TZ-честность: shared-день и день чата РАЗНЫЕ (иначе тест TZ бессмыслен).
    monkeypatch.setattr(wb, "DAY_TZ", SHARED_TZ)
    monkeypatch.setattr(wb, "_chat_tz_name", lambda chat_id: CHAT_TZ)
    monkeypatch.setattr(budget_gate, "budgets_enabled", _budgets_on)
    _set_env("WORKER_DAILY_IMAGE_CALLS_PER_CHAT", 60, monkeypatch)
    _set_env("WORKER_DAILY_IMAGE_CALLS_GLOBAL", 200, monkeypatch)
    _set_env("IMAGE_DAILY_LIMIT_ENABLED", True, monkeypatch)
    _set_env("IMAGE_CONTEXT_MEMORY_ENABLED", False, monkeypatch)
    wb.set_worker_budget_pg(pg)
    _reset_purge()

    db = DatabaseService(str(tmp_path / "iso.db"))
    await db.initialize()
    lore_runtime.set_lore_components(db=db)
    try:
        yield SimpleNamespace(pg=pg, state=state, hot=hot, overrides=overrides,
                              db=db, wall=wall, tmp_path=tmp_path)
    finally:
        lore_runtime.set_lore_components()
        wb.set_worker_budget_pg(None)
        await db.close()


def _patch_cover_image(monkeypatch, env, calls, *, results=None):
    """Провайдер + temp-файл (обложка): реальный `generate_image_verbose`."""
    monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls,
                                                               results=results))
    monkeypatch.setattr(ig, "_write_temp_image",
                        lambda content: str(env.tmp_path / "cover.jpg"))


async def _cover(env, *, chat_id=CHAT, corr="c-1", stage=None, prompt="cover"):
    kwargs = {"consumption_type": COVER}
    if stage is not None:
        kwargs["cover_stage"] = stage
    return await ig.generate_image_verbose(prompt, chat_id=chat_id,
                                           correlation_id=corr, **kwargs)


# ═══ CFG-02C.2: таксономия типа потребления ═══════════════════════════════

class TestTaxonomy:
    def test_constants_exact_values(self):
        """Тип — явные константы (не вывод из промпта/имени инструмента)."""
        assert ig.CONSUMPTION_USER == "user_image"
        assert ig.CONSUMPTION_COVER == "summary_cover"
        assert ig.COVER_STAGE_BASE == "base"
        assert ig.COVER_STAGE_STYLED_EDIT == "styled_edit"
        assert ig.COVER_STAGE_RETRY_RECOVERY == "retry_recovery"
        assert ig.COVER_STAGE_FALLBACK == "fallback"
        assert wb.CONSUMPTION_USER == "user_image"
        assert wb.CONSUMPTION_COVER == "summary_cover"

    def test_journal_type_mapping_forward_only(self):
        """Единый маппер журнал→тип; исторические строки (direct/tool) —
        пользовательские (обложки в журнал не писались) — без перезаписи."""
        assert wb.journal_consumption_type("direct") == "user_image"
        assert wb.journal_consumption_type("tool") == "user_image"
        assert wb.journal_consumption_type("") == "user_image"
        assert wb.journal_consumption_type(None) == "user_image"
        assert wb.journal_consumption_type("summary_cover:base") \
            == "summary_cover"
        assert wb.journal_consumption_type("summary_cover:fallback") \
            == "summary_cover"


# ═══ CFG-02C.1/.7 / AC8: обложка при user daily=0 + freq ON ════════════════

class TestCoverIsolationFromUserQuota:
    @pytest.mark.asyncio
    async def test_base_cover_works_when_user_daily_zero_and_freq_on(
            self, env, monkeypatch):
        """(a) user daily `0` + freq ON → Base-обложка работает; user-счётчики
        и частотные заряды не двигаются; user-путь по-прежнему честно
        запрещён своей квотой (она не «съедена» обложкой)."""
        env.hot[QUOTA_KEY] = 0
        _enable_freq(env)
        calls: list = []
        _patch_cover_image(monkeypatch, env, calls)

        path, reason = await _cover(env, stage=STAGE_BASE, corr="cover-base")
        assert (path, reason) == (str(env.tmp_path / "cover.jpg"), "ok")
        assert len(calls) == 1

        assert _chat_used(env, CHAT) == 0          # user-квота не тронута
        assert _shared_used(env) == 1              # shared-контур списан
        assert await _throttle_rows(env.db) == []  # freq не тронут
        rows = _cover_rows(env)
        assert len(rows) == 1
        assert rows[0]["status"] == "committed"
        assert rows[0]["source"].startswith("summary_cover:")
        assert not _user_rows(env)                 # user-строк нет

        # Пользовательская генерация: своя квота `0` всё ещё действует.
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        monkeypatch.setattr(ig, "generate", _fake_generate_factory([]))
        denied = await ig.generate_and_send(object(), CHAT, "мем",
                                            reply_to_message_id=5,
                                            user_id=USER_A)
        assert denied.ok is False and denied.reason == "budget"
        assert _chat_used(env, CHAT) == 0

    @pytest.mark.asyncio
    async def test_cover_journal_is_typed_shared_only(self, env, monkeypatch):
        """(f) Строка журнала обложки типизирована; per-chat контур не
        инкрементируется даже при живой user-квоте."""
        env.hot[QUOTA_KEY] = 3
        calls: list = []
        _patch_cover_image(monkeypatch, env, calls)
        path, reason = await _cover(env, stage=STAGE_BASE, corr="cover-1")
        assert reason == "ok" and path
        rows = _cover_rows(env)
        assert rows[0]["source"] == "summary_cover:base"
        assert wb.journal_consumption_type(rows[0]["source"]) == "summary_cover"
        assert _chat_used(env, CHAT) == 0
        assert _shared_used(env) == 1

    @pytest.mark.asyncio
    async def test_cover_retry_does_not_touch_user_counters(self, env,
                                                            monkeypatch):
        """(c) transient-ретрай обложки: одно списание, user-контуры чисты."""
        env.hot[QUOTA_KEY] = 3
        _enable_freq(env)
        calls: list = []
        monkeypatch.setattr(ig, "_image_max_attempts", lambda: 2)
        monkeypatch.setattr(ig, "_image_retry_backoff", lambda: 0.0)
        _patch_cover_image(
            monkeypatch, env, calls,
            results=[ig.GenerationResult(ok=False, reason="timeout"),
                     ig.GenerationResult(ok=True, reason="ok",
                                         content=b"x")])
        path, reason = await _cover(env, stage=STAGE_BASE, corr="cover-retry")
        assert reason == "ok" and path
        assert len(calls) == 2                     # ретрай был реальным
        assert _chat_used(env, CHAT) == 0
        assert _shared_used(env) == 1              # списание ОДНО
        assert await _throttle_rows(env.db) == []

    @pytest.mark.asyncio
    async def test_cover_fallback_does_not_touch_user_counters(
            self, env, monkeypatch):
        """(c) image-fallback обложки — внутри того же одного списания."""
        from services import media_execution as me
        env.hot[QUOTA_KEY] = 3
        calls: list = []
        _patch_cover_image(
            monkeypatch, env, calls,
            results=[ig.GenerationResult(ok=False, reason="bad_request")])

        async def _fallback(prompt, **kw):
            return SimpleNamespace(ok=True, content=b"fb")

        monkeypatch.setattr(me, "maybe_media_fallback", _fallback)
        path, reason = await _cover(env, stage=STAGE_FALLBACK,
                                    corr="cover-fb")
        assert reason == "ok" and path
        assert _chat_used(env, CHAT) == 0
        assert _shared_used(env) == 1
        rows = _cover_rows(env)
        assert len(rows) == 1 and rows[0]["status"] == "committed"

    @pytest.mark.asyncio
    async def test_cover_provider_error_releases_shared_keeps_user_clean(
            self, env, monkeypatch):
        """(c,d) терминальный сбой обложки: shared-квота возвращена, журнал
        released, user-контуры не тронуты."""
        env.hot[QUOTA_KEY] = 3
        _enable_freq(env)
        calls: list = []
        _patch_cover_image(
            monkeypatch, env, calls,
            results=[ig.GenerationResult(ok=False, reason="bad_request")])
        path, reason = await _cover(env, stage=STAGE_BASE, corr="cover-fail")
        assert path is None and reason == "bad_request"
        assert _shared_used(env) == 0              # квота возвращена (release)
        assert _chat_used(env, CHAT) == 0
        rows = _cover_rows(env)
        assert len(rows) == 1 and rows[0]["status"] == "released"
        assert await _throttle_rows(env.db) == []


# ═══ CFG-02C.1/.7: пользовательский мем не входит в контур Summary ═════════

class TestUserIsolationFromCoverContour:
    @pytest.mark.asyncio
    async def test_direct_and_tool_memes_do_not_touch_cover_contour(
            self, env, monkeypatch):
        """(b) direct- и tool-пути — один user-контур; строк журнала
        `summary_cover` не создаётся, агрегат обложек остаётся нулевым."""
        env.hot[QUOTA_KEY] = 5
        _enable_freq(env, burst=5)
        monkeypatch.setattr(ig, "generate", _fake_generate_factory([]))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        # Spy: cover-контур учёта не вызывается пользовательским путём вообще.
        cover_charge_calls = {"n": 0}

        async def _cover_spy(chat_id, *, stage, correlation_id):
            cover_charge_calls["n"] += 1
            return "none", "", "ok"

        monkeypatch.setattr(ig, "_cover_charge", _cover_spy)
        assert (await ig.generate_and_send(object(), CHAT, "мем",
                                           reply_to_message_id=1,
                                           source="direct",
                                           user_id=USER_A)).ok
        request = ig.build_image_request("tool", CHAT, "мем",
                                         requester_id=USER_A,
                                         original_message_id=2)
        assert (await ig.run_image_request(request, bot=object(),
                                           correlation_id="r-tool")).ok

        assert cover_charge_calls["n"] == 0        # cover-override не вызван
        assert _cover_rows(env) == []              # контур Summary не тронут
        assert len(_user_rows(env)) == 2
        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["cover"]["requests"] == 0
        assert summary["cover"]["success"] == 0
        assert summary["requests"] == 2            # user-витрина: только user
        assert summary["success"] == 2

    @pytest.mark.asyncio
    async def test_user_denial_by_daily_quota_does_not_write_cover_rows(
            self, env, monkeypatch):
        """(b) user-отказ по своей квоте: denied-строка — пользовательская,
        `summary_cover` не появляется; shared не расходуется."""
        env.hot[QUOTA_KEY] = 1
        monkeypatch.setattr(ig, "generate", _fake_generate_factory([]))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "мем",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        denied = await ig.generate_and_send(object(), CHAT, "мем",
                                            reply_to_message_id=2,
                                            user_id=USER_A)
        assert denied.ok is False and denied.reason == "budget"
        assert _cover_rows(env) == []
        assert _shared_used(env) == 1              # второй отказ не списал
        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["cover"]["requests"] == 0
        assert summary["denied"] == 1
        assert summary["success"] == 1


# ═══ CFG-02C.3: styled edit / recovery — без image-бюджета (сохранить) ═════

class TestStyledEditAndRecovery:
    @pytest.mark.asyncio
    async def test_styled_edit_does_not_touch_budget_or_user_counters(
            self, env, monkeypatch, tmp_path):
        """Style Edit: свой provider-вызов, но НЕ image-бюджет и не
        user-счётчики; user daily `0` + freq ON его не блокируют; повторный
        styled-запуск не удваивает списание."""
        from services import cover_style_jobs as j
        from services import summary_generator as sg
        from services.cover_style_edit import EditResult
        from tests.test_cover_style_wave_b_asap4 import (
            _STYLE_IMG, _patch_pg, _patch_profile, _patch_provenance,
            _patch_issue_counter, _png, _profile, _flag)

        env.hot[QUOTA_KEY] = 0          # пользовательская квота запрещена
        _enable_freq(env)               # и частотная пауза активна
        _flag(monkeypatch, True)
        _patch_pg(monkeypatch)
        _patch_profile(monkeypatch, _profile(references=[]))
        _patch_provenance(monkeypatch)
        _patch_issue_counter(monkeypatch)

        async def _slot(*, profile, connection, pg=None):
            return {"base_url": "https://edit.example/v1",
                    "model": "qwen-image-edit", "provider": "edit.example",
                    "connection_id": "default", "custom_unresolved": False,
                    "configured": True}

        monkeypatch.setattr(j, "resolve_style_slot_inherited", _slot)
        edit_calls: list = []

        async def _edit(prompt, **kw):
            edit_calls.append(kw)
            return EditResult(ok=True, content=_STYLE_IMG, reason="ok",
                              latency_ms=5)

        monkeypatch.setattr(j, "edit_image", _edit)
        budget_spy = {"consume": 0, "reserve": 0, "commit": 0, "release": 0}

        async def _c(*a, **kw):
            budget_spy["consume"] += 1
            return True

        async def _r(*a, **kw):
            budget_spy["reserve"] += 1
            return wb.ImageReserveResult(ok=True, reason="ok",
                                         status="reserved")

        async def _k(*a, **kw):
            budget_spy["commit"] += 1

        async def _rel(*a, **kw):
            budget_spy["release"] += 1

        monkeypatch.setattr(wb, "consume", _c)
        monkeypatch.setattr(wb, "reserve_image", _r)
        monkeypatch.setattr(wb, "commit_image", _k)
        monkeypatch.setattr(wb, "release_image", _rel)

        base = _png(tmp_path / "base.png")
        gen = SimpleNamespace(memory=SimpleNamespace(db=None))
        snapshot = {"chat_id": CHAT, "selected_style_id": "medved_press",
                    "style_revision": 1, "enabled": True,
                    "pipeline_mode": "generate_then_edit",
                    "selection_source": "global"}
        meta1 = await sg.SummaryGenerator._maybe_apply_cover_style(
            gen, CHAT, base, "iso-run-1", snapshot=snapshot)
        assert meta1 is not None and meta1.get("styled_path")
        # Повторный styled-запуск того же base: ни второго платного image-
        # списания, ни строк журнала Summary-обложки.
        meta2 = await sg.SummaryGenerator._maybe_apply_cover_style(
            gen, CHAT, base, "iso-run-2", snapshot=snapshot)
        assert meta2 is not None
        assert len(edit_calls) == 2                # styled-вызовы состоялись
        assert budget_spy == {"consume": 0, "reserve": 0, "commit": 0,
                              "release": 0}
        assert _cover_rows(env) == []
        assert _chat_used(env, CHAT) == 0
        assert _shared_used(env) == 0
        assert await _throttle_rows(env.db) == []

    @pytest.mark.asyncio
    async def test_recovery_retry_stage_does_not_touch_user_counters(
            self, env, monkeypatch, tmp_path):
        """Recovery (bounded retry styled-этапа): бюджета не тратит,
        user-счётчики и частотные заряды не меняются; user daily `0` его не
        блокирует; правила сохранены."""
        from services import cover_style_jobs as j
        from services.cover_style_edit import EditResult
        from services import summary_generator as sg
        from tests.test_cover_style_wave_b_asap4 import (
            _patch_pg, _patch_profile, _patch_provenance,
            _patch_issue_counter, _png, _profile, _flag)

        env.hot[QUOTA_KEY] = 0
        _enable_freq(env)
        _flag(monkeypatch, True)
        _patch_pg(monkeypatch)
        _patch_profile(monkeypatch, _profile(references=[]))
        _patch_provenance(monkeypatch)
        _patch_issue_counter(monkeypatch)

        async def _slot(*, profile, connection, pg=None):
            return {"base_url": "https://edit.example/v1",
                    "model": "qwen-image-edit", "provider": "edit.example",
                    "connection_id": "default", "custom_unresolved": False,
                    "configured": True}

        monkeypatch.setattr(j, "resolve_style_slot_inherited", _slot)
        attempts = {"n": 0}

        async def _edit(prompt, **kw):
            attempts["n"] += 1
            return EditResult(ok=False, reason="provider_timeout")

        monkeypatch.setattr(j, "edit_image", _edit)
        assert j.recovery_max_attempts() >= 1
        base = _png(tmp_path / "base.png")
        gen = SimpleNamespace(memory=SimpleNamespace(db=None))
        snapshot = {"chat_id": CHAT, "selected_style_id": "medved_press",
                    "style_revision": 1, "enabled": True,
                    "pipeline_mode": "generate_then_edit",
                    "selection_source": "global"}
        meta = await sg.SummaryGenerator._maybe_apply_cover_style(
            gen, CHAT, base, "iso-run-rec", snapshot=snapshot)
        assert meta is not None
        assert attempts["n"] >= 1                  # styled-этап был
        assert _chat_used(env, CHAT) == 0
        assert _shared_used(env) == 0
        assert _cover_rows(env) == []
        assert await _throttle_rows(env.db) == []


# ═══ CFG-02C.4 / AC9: shared-потолок честен; расход раздельно ══════════════

class TestSharedCeilingHonesty:
    @pytest.mark.asyncio
    async def test_user_denial_names_technical_budget_and_shared_tz(
            self, env, monkeypatch):
        """(e) Отказ по env shared-потолку: причина и текст называют
        ТЕХНИЧЕСКИЙ бюджет и shared-TZ, а не пользовательскую квоту чата."""
        env.hot[QUOTA_KEY] = 50
        _set_env("WORKER_DAILY_IMAGE_CALLS_GLOBAL", 1, monkeypatch)
        monkeypatch.setattr(ig, "generate", _fake_generate_factory([]))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "мем",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        denied = await ig.generate_and_send(object(), CHAT, "мем",
                                            reply_to_message_id=2,
                                            user_id=USER_A)
        assert denied.ok is False
        assert denied.reason == "shared_budget"
        assert caps.failure_code_for_reason("shared_budget") \
            == "quota_exhausted"
        assert ig._image_reason_code("shared_budget") \
            == "financial_limit_reached"

        block = ig._image_error_block(denied, chat_id=CHAT)
        assert "Технический бюджет" in block
        assert f"({SHARED_TZ})" in block
        assert "Суточная квота обновится" not in block   # не user-квота
        assert f"({CHAT_TZ})" not in block

    @pytest.mark.asyncio
    async def test_cover_denial_names_technical_source(self, env, monkeypatch):
        """(e) Отказ обложке по shared-потолку тоже называет технический
        источник (не «пользовательская квота»)."""
        env.hot[QUOTA_KEY] = 50
        _set_env("WORKER_DAILY_IMAGE_CALLS_GLOBAL", 1, monkeypatch)
        calls: list = []
        _patch_cover_image(monkeypatch, env, calls)
        first = await _cover(env, corr="cover-ok")
        assert first[1] == "ok"
        second = await _cover(env, corr="cover-deny")
        assert second[0] is None and second[1] == "shared_budget"
        assert len(calls) == 1                     # второй платной попытки нет
        denied = [r for r in _cover_rows(env) if r["status"] == "denied"]
        assert len(denied) == 1
        assert denied[0]["error_code"] == "limit_global"

    @pytest.mark.asyncio
    async def test_usage_breakdown_separates_user_and_cover(self, env,
                                                            monkeypatch):
        """(e,f) Агрегат: расход user vs cover показан раздельно, один
        счётчик не выдаётся за другой."""
        env.hot[QUOTA_KEY] = 5
        monkeypatch.setattr(ig, "generate", _fake_generate_factory([]))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        calls: list = []
        _patch_cover_image(monkeypatch, env, calls)
        assert (await ig.generate_and_send(object(), CHAT, "мем",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        assert (await _cover(env, corr="cover-1"))[1] == "ok"

        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["success"] == 1             # только user
        assert summary["cover"]["success"] == 1    # только cover
        assert summary["shared_used"] == 2         # физический потолок общий
        day = await wb.get_day_summary(env.pg)
        assert day["global"]["image_calls"]["cover_used"] == 1
        assert day["global"]["image_calls"]["used"] == 2
        entry = next(c for c in day["chats"] if c["scope"] == f"chat:{CHAT}")
        assert entry["image_calls"]["used"] == 1   # per-chat = только user

    @pytest.mark.asyncio
    async def test_user_quota_note_keeps_chat_tz(self, env, monkeypatch):
        """TZ-регрессия: отказ по пользовательской квоте называет TZ чата."""
        env.hot[QUOTA_KEY] = 0
        monkeypatch.setattr(ig, "generate", _fake_generate_factory([]))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        denied = await ig.generate_and_send(object(), CHAT, "мем",
                                            reply_to_message_id=1,
                                            user_id=USER_A)
        assert denied.ok is False and denied.reason == "budget"
        block = ig._image_error_block(denied, chat_id=CHAT)
        assert "Суточная квота обновится" in block
        assert f"({CHAT_TZ})" in block
        assert "Технический бюджет" not in block


# ═══ CFG-02C.6: параллель / рестарт / атомарность ══════════════════════════

class TestConcurrencyAndRestart:
    @pytest.mark.asyncio
    async def test_parallel_user_and_cover_isolated(self, env, monkeypatch):
        """(d) Параллельно в одном чате: обложка и мем не мешают друг другу
        по продуктовым квотам; двойных списаний нет."""
        env.hot[QUOTA_KEY] = 1
        monkeypatch.setattr(ig, "generate", _fake_generate_factory([]))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        calls: list = []
        _patch_cover_image(monkeypatch, env, calls)
        # Пользовательская квота уже исчерпана (1/1).
        assert (await ig.generate_and_send(object(), CHAT, "мем",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        cover_res, user_res = await asyncio.gather(
            _cover(env, corr="cover-par"),
            ig.generate_and_send(object(), CHAT, "мем",
                                 reply_to_message_id=2, user_id=USER_A))
        assert cover_res[1] == "ok"                # обложка прошла
        assert user_res.ok is False                # мем — своя квота исчерпана
        assert _chat_used(env, CHAT) == 1          # ровно одно user-списание
        assert _shared_used(env) == 2              # user + cover, без дублей
        assert len(_cover_rows(env)) == 1
        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["cover"]["success"] == 1
        assert summary["success"] == 1

    @pytest.mark.asyncio
    async def test_inflight_cover_reservation_does_not_block_user(
            self, env, monkeypatch):
        """(d) «Рестарт в середине»: висящая reserved-строка обложки не
        переносит расход в user-контур и не блокирует пользователя."""
        env.hot[QUOTA_KEY] = 5
        res = await wb.reserve_image(
            env.pg, chat_id=CHAT, idem_key="cover:inflight:1",
            source="summary_cover:base", consumption_type=wb.CONSUMPTION_COVER)
        assert res.ok is True and res.status == "reserved"
        assert _chat_used(env, CHAT) == 0
        assert _shared_used(env) == 1
        monkeypatch.setattr(ig, "generate", _fake_generate_factory([]))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "мем",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        assert _chat_used(env, CHAT) == 1
        assert _shared_used(env) == 2
        day = await wb.get_day_summary(env.pg)
        assert day["global"]["image_calls"]["cover_used"] == 1


# ═══ CFG-02C.5: витрина «Пользовательские изображения» + разбивка ═════════

class TestUiContract:
    def test_html_labels_explanation_and_breakdown(self):
        assert "data-image-quota-scope-label" in HTML
        assert "data-image-quota-shared-breakdown" in HTML
        m = re.search(r"data-image-quota-scope-label[^>]*>(.*?)</div>", HTML,
                      re.S)
        assert m, "подпись области «Лимиты генерации» не найдена"
        label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1)))
        assert "Пользовательские изображения" in label
        assert "Обложки сводок здесь не учитываются" in label
        shared = re.search(r"data-image-quota-shared-breakdown[^>]*>(.*?)</div>",
                           HTML, re.S)
        assert shared, "разбивка общего бюджета не найдена"
        breakdown = re.sub(r"\s+", " ",
                           re.sub(r"<[^>]+>", " ", shared.group(1)))
        assert "обложки" in breakdown.lower()
        assert "cover_used" in shared.group(0) or "cover_used" in HTML

    def test_js_group_description_names_user_images_and_covers(self):
        m = re.search(r"limits_images: \{\s*title: '([^']+)',\s*"
                      r"description: \((.*?)\),\s*\},", JS, re.S)
        assert m, "витринное описание группы limits_images не найдено"
        assert m.group(1) == "Лимиты генерации"
        desc = re.sub(r"\s+", " ", m.group(2))
        assert "Пользовательские изображения" in desc
        assert "Обложки сводок" in desc and "не учитываются" in desc
