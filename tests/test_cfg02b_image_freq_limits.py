"""CFG-02B — частотный лимит генераций изображений (burst + пауза).

Покрытие строк карты `plans/features/cfg/requirements-map.json` (слайс
CFG-02B, 17 строк):

  * CFG-02B.1 / CFG-02.AC2 — отдельный переключатель «Лимит частоты
    генерации», Factory Default ВЫКЛЮЧЕНО; при OFF ограничение не
    запрещает/не замедляет генерации и не пишет состояние; суточная квота
    работает независимо;
  * CFG-02B.2 / .2.1 / .2.2 / .2.3 — компактные настройки: «Сколько
    генераций подряд» (положительное целое), «Время ожидания» (секунды),
    «Считать лимит» — ОДИН select из двух взаимоисключающих вариантов,
    заводской `per_user`;
  * CFG-02B.3 / AC4 / AC5 — per-user счётчик `(chat_id, user_id)`: A не
    блокирует B; per-chat: один запас на чат; CHAT-override локален,
    глобальный — дефолт с источником; DM (положительный chat_id) и ключ
    скоупа; счётчик не смешан с дневным;
  * CFG-02B.4 / AC6 / AC7 — семантика «подряд»/паузы: списание ПЕРЕД
    платной попыткой, полное восстановление после паузы от последнего
    допущенного обращения, смена конфига/режима не сбрасывает состояние,
    OFF снимает запрет немедленно, состояние переживает рестарт и делится
    между воркерами, параллельные запросы не дают двойного списания;
  * CFG-02B.5 — все пользовательские пути (ключевик/direct-пре-гейт, L1/Tool
    Router, повторный вызов) через один limiter; этапы обложек Summary НЕ
    проходят пользовательский частотный лимитер (ни per-user, ни per-chat);
  * CFG-02B.6 / AC3 — отказ ДО платного вызова с фактическим остатком
    («через 8 мин 20 сек»), свежий остаток на каждую попытку, текст
    редактируем через Factory Defaults (`message.image_failure.freq_limited`);
  * CFG-02B.7 — политика списания/возврата: replay не списывает частоту
    второй раз; provider error/delivery failure не возвращают заряд
    (восстановление только по времени); при исчерпании ОБОИХ лимитов
    сообщение показывает оба (частотную паузу и суточный сброс);
  * CFG-02B.8 — секция «Лимиты генерации»: активность/scope/остаток/
    источник/следующая доступность (факты API + витрина).

TEST-LIFECYCLE: CONTRACT owner=CFG-02B (лимитер: ключи, семантика, пути)
TEST-LIFECYCLE: REGRESSION owner=CFG-02B (дефект-класс: обход/скрытое
списание/отказ после платного вызова)
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings                        # noqa: E402
from services import budget_gate                             # noqa: E402
from services import image_generation as ig                  # noqa: E402
from services import lore_runtime                            # noqa: E402
from services import param_catalog as pc                     # noqa: E402
from services import persistent_throttling as pt             # noqa: E402
from services import telegram_send                           # noqa: E402
from services import worker_budget as wb                     # noqa: E402
from services.database import DatabaseService                # noqa: E402
from services.param_catalog import TAB_MOD_IMAGES            # noqa: E402
from tests.test_image_daily_limit_round1026 import (         # noqa: E402
    _Conn, _reset_purge, make_pg)

JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

CHAT = -1009001
CHAT_OTHER = -1009002
USER_A = 101
USER_B = 202

FREQ_ENABLED_KEY = "limits.image_freq_limit_enabled"
FREQ_BURST_KEY = "limits.image_freq_limit_burst"
FREQ_COOLDOWN_KEY = "limits.image_freq_limit_cooldown_seconds"
FREQ_MODE_KEY = "limits.image_freq_limit_mode"
FREQ_GROUP = "limits_images"


# ═══ окружение: PG-стаб + слои настроек + runtime SQLite (throttle_state) ═══

class _QuotaConn(_Conn):
    """PG-стаб + read-only пути проверки суточной квоты и usage-агрегатов."""

    async def fetch(self, sql, *args):
        if sql is wb.SELECT_ALL_SQL:
            return [{"day": wb.today(), "scope": f"chat:{CHAT}",
                     "metric": wb.METRIC_IMAGE_CALLS, "used": 1}]
        if sql is wb.SELECT_SQL:
            _day, scope = args
            if scope == f"chat:{CHAT}":
                return [{"day": wb.image_day(CHAT), "scope": scope,
                         "metric": wb.METRIC_IMAGE_CALLS, "used": 1}]
            return []
        return await super().fetch(sql, *args)


def _set_env(name: str, value, monkeypatch) -> None:
    """Патч env-поля Settings на всех классах, которые читает рантайм."""
    classes = {Settings, type(ig.settings), type(wb.settings)}
    for _cls in classes:
        if hasattr(_cls, name):
            monkeypatch.setattr(_cls, name, value)


def _noop_send():
    async def _send(*a, **kw):
        return None
    return _send


def _always_true():
    async def _yes(*a, **kw):
        return True
    return _yes


def _fake_generate_factory(calls: list, *, ok=True, reason="ok"):
    async def _fake(prompt, *, chat_id=None, correlation_id=None,
                    consume_budget=True, **kw):
        calls.append({"prompt": prompt, "chat_id": chat_id,
                      "consume_budget": consume_budget})
        if ok:
            return ig.GenerationResult(ok=True, reason="ok", content=b"x")
        return ig.GenerationResult(ok=False, reason=reason)
    return _fake


def _enable_freq(env, *, burst=2, cooldown=600.0, mode="per_user",
                 chat_id=None, enabled=True) -> None:
    """Включить лимитер в глобальном слое (или override слоя чата)."""
    layer = env.hot if chat_id is None else env.overrides.setdefault(
        int(chat_id), {})
    layer[FREQ_ENABLED_KEY] = enabled
    layer[FREQ_BURST_KEY] = burst
    layer[FREQ_COOLDOWN_KEY] = cooldown
    layer[FREQ_MODE_KEY] = mode


async def _throttle_rows(db) -> list[tuple]:
    """Снимок строк throttle_state scope='image_freq' (read-only)."""
    cur = await db.db.execute(
        "SELECT chat_id, user_id, burst_left, last_ts FROM throttle_state "
        "WHERE scope = ?", (pt.IMAGE_FREQ_SCOPE,))
    rows = await cur.fetchall()
    return [tuple(r) for r in rows]


@pytest.fixture()
def hot(monkeypatch):
    """ConfigCache-двойник: `store` = глобальный слой (POST /api/config —
    hot-reload без рестарта)."""
    from services import hot_config as hot_mod
    store: dict = {}

    class _FakeConfigCache:
        def get(self, key, default=None):
            return store.get(key, default)

    monkeypatch.setattr(hot_mod, "_cache", _FakeConfigCache())
    return store


@pytest.fixture()
def overrides(monkeypatch):
    """chat_params-двойник: per-chat overrides (слой ЧАТА)."""
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
    """Управляемая стена `time.time()` персистентного лимитера."""
    state = {"now": 1_800_000_000.0}

    class FakeTime:
        @staticmethod
        def time():
            return state["now"]

    monkeypatch.setattr(pt, "time", FakeTime)
    return state


@pytest_asyncio.fixture()
async def env(monkeypatch, hot, overrides, wall, tmp_path):
    """Изолированная среда: PG-стаб + слои настроек + runtime SQLite."""
    pg, state = make_pg(conn_cls=_QuotaConn)
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
    _set_env("WORKER_DAILY_IMAGE_CALLS_PER_CHAT", 60, monkeypatch)
    _set_env("WORKER_DAILY_IMAGE_CALLS_GLOBAL", 200, monkeypatch)
    _set_env("IMAGE_DAILY_LIMIT_ENABLED", True, monkeypatch)
    _set_env("IMAGE_CONTEXT_MEMORY_ENABLED", False, monkeypatch)
    wb.set_worker_budget_pg(pg)
    _reset_purge()

    db = DatabaseService(str(tmp_path / "freq.db"))
    await db.initialize()
    lore_runtime.set_lore_components(db=db)
    try:
        yield SimpleNamespace(pg=pg, state=state, limits=limits, hot=hot,
                              overrides=overrides, db=db, wall=wall,
                              path=str(tmp_path / "freq.db"))
    finally:
        lore_runtime.set_lore_components()
        wb.set_worker_budget_pg(None)
        # «Лишние» инстансы тест закрывает сам (тест-цикл) — здесь страховка.
        for extra in getattr(env, "_extra_dbs", []):
            try:
                await extra.close()
            except Exception:      # pragma: no cover - страховка teardown
                pass
        await db.close()


def _bind_extra_db(env, path: str) -> DatabaseService:
    """«Рестарт»/второй воркер: новый процесс-локальный SQLite-инстанс."""
    extra = DatabaseService(path)
    env._extra_dbs = list(getattr(env, "_extra_dbs", [])) + [extra]
    return extra


# ═══ CFG-02B.1/.2/.2.1/.2.2/.2.3: каталог, дефолты, витрина ═══════════════

class TestCatalogAndDefaults:
    def test_factory_defaults_off_and_per_user(self):
        """Factory Default: ВЫКЛЮЧЕНО; режим — per_user (заводской выбор)."""
        assert Settings.IMAGE_FREQ_LIMIT_ENABLED is False
        assert Settings.IMAGE_FREQ_LIMIT_MODE == "per_user"
        assert int(Settings.IMAGE_FREQ_LIMIT_BURST) >= 1
        assert float(Settings.IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS) >= 0.0

    def test_catalog_keys_shapes(self):
        # CFG-03-F2 (22.10.2026): cooldown "float" == тип дефолта Settings
        # (_env_float_min, 300.0); резолвер читает float(...).
        for key, typ in ((FREQ_ENABLED_KEY, "bool"), (FREQ_BURST_KEY, "int"),
                         (FREQ_COOLDOWN_KEY, "float"),
                         (FREQ_MODE_KEY, "str")):
            spec = pc.get_by_pg_key(key)
            assert spec is not None, key
            assert spec.type == typ, key
            assert spec.group == FREQ_GROUP, key
            assert spec.per_chat is True, key
            assert spec.secret is False, key

    def test_mode_is_single_select_with_two_options(self):
        spec = pc.get_by_pg_key(FREQ_MODE_KEY)
        assert spec.widget == "select"
        assert tuple(spec.select_options) == ("per_user", "per_chat")
        assert len(spec.select_labels) == 2

    def test_group_belongs_to_images_module_tab(self):
        assert FREQ_GROUP in pc.tab_group_ids(TAB_MOD_IMAGES)

    @pytest.mark.asyncio
    async def test_resolver_paths_source_and_normalization(self, env):
        limits = await pt.resolve_image_freq_limits(CHAT)
        assert limits.enabled is False            # заводской OFF
        assert limits.mode == "per_user"
        assert limits.source in ("default", "global", "chat")

        _enable_freq(env, burst=4, cooldown=90.0, mode="per_chat")
        limits = await pt.resolve_image_freq_limits(CHAT)
        assert limits.enabled is True and limits.mode == "per_chat"
        assert limits.burst == 4 and limits.cooldown == 90.0
        assert limits.source == "global"

        # CHAT override локален; глобальный остаётся дефолтом для других.
        _enable_freq(env, burst=1, cooldown=30.0, mode="per_user",
                     chat_id=CHAT)
        assert (await pt.resolve_image_freq_limits(CHAT)).burst == 1
        assert (await pt.resolve_image_freq_limits(CHAT)).source == "chat"
        assert (await pt.resolve_image_freq_limits(CHAT_OTHER)).burst == 4

        # Мусор: burst ≤ 0 → 1; отрицательный cooldown → 0; неизвестный
        # режим → per_user (без «вечного лока» и без скрытого безлимита).
        assert pt.normalize_image_freq_limits(0, -5, "junk") == (1, 0.0,
                                                                 "per_user")
        assert pt.normalize_image_freq_limits("x", "y", None) == (1, 0.0,
                                                                  "per_user")


# ═══ CFG-02B.1 / AC2: заводской OFF — не вмешивается ═══════════════════════

class TestFactoryOff:
    @pytest.mark.asyncio
    async def test_off_does_not_limit_and_writes_nothing(self, env,
                                                         monkeypatch):
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        for i in range(3):
            res = await ig.generate_and_send(object(), CHAT, "p",
                                             reply_to_message_id=10 + i,
                                             user_id=USER_A)
            assert res.ok is True, res.reason
        assert len(calls) == 3                  # ни одна не замедлена/срезана
        assert await _throttle_rows(env.db) == []   # состояние не пишется

    @pytest.mark.asyncio
    async def test_off_state_is_not_applied_even_when_saved(self, env,
                                                            monkeypatch):
        """Настройки сохранены при OFF — не применяются (§02B.1)."""
        env.hot[FREQ_BURST_KEY] = 1
        env.hot[FREQ_COOLDOWN_KEY] = 600.0
        env.hot[FREQ_MODE_KEY] = "per_chat"
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        for i in range(2):
            assert (await ig.generate_and_send(object(), CHAT, "p",
                                               reply_to_message_id=40 + i,
                                               user_id=USER_A)).ok
        assert await _throttle_rows(env.db) == []


# ═══ CFG-02B.6 / AC3: отказ до платного вызова + фактический остаток ═══════

class TestBurstCooldownRefusal:
    @pytest.mark.asyncio
    async def test_third_attempt_denied_before_paid_call(self, env,
                                                         monkeypatch):
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())

        first = await ig.generate_and_send(object(), CHAT, "p",
                                          reply_to_message_id=1,
                                          user_id=USER_A)
        second = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_A)
        assert first.ok and second.ok
        assert len(calls) == 2

        third = await ig.generate_and_send(object(), CHAT, "p",
                                          reply_to_message_id=3,
                                          user_id=USER_A)
        assert third.ok is False and third.reason == "freq_limit"
        assert len(calls) == 2            # ПЛАТНЫЙ вызов не состоялся
        assert third.retry_after_seconds == pytest.approx(600.0, abs=2.0)

        # Свежий остаток на каждую попытку (не «замороженная» цифра).
        env.wall["now"] += 100.0
        again = await ig.generate_and_send(object(), CHAT, "p",
                                          reply_to_message_id=4,
                                          user_id=USER_A)
        assert again.ok is False and again.reason == "freq_limit"
        assert again.retry_after_seconds == pytest.approx(500.0, abs=2.0)

    @pytest.mark.asyncio
    async def test_after_pause_generation_allowed_again(self, env,
                                                        monkeypatch):
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        for i in (1, 2):
            assert (await ig.generate_and_send(object(), CHAT, "p",
                                               reply_to_message_id=i,
                                               user_id=USER_A)).ok
        denied = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=3,
                                           user_id=USER_A)
        assert denied.ok is False
        env.wall["now"] += 601.0            # пауза истекла
        after = await ig.generate_and_send(object(), CHAT, "p",
                                          reply_to_message_id=4,
                                          user_id=USER_A)
        assert after.ok is True             # после паузы снова можно
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_bot_reply_carries_factual_remaining(self, env,
                                                       monkeypatch):
        """Прямой пользовательский путь: ответ бота содержит фактический
        остаток и указывает, для кого действует ограничение."""
        _enable_freq(env, burst=1, cooldown=620.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        ctx = SimpleNamespace(bot=object(), chat_id=CHAT, user_id=USER_A,
                              reply_to_message_id=1, correlation_id="r1")
        ok_block = await ig.maybe_handle_keyword(ctx, "бот, нарисуй мем")
        assert 'status="ok"' in ok_block
        ctx2 = SimpleNamespace(bot=object(), chat_id=CHAT, user_id=USER_A,
                               reply_to_message_id=2, correlation_id="r2")
        block = await ig.maybe_handle_keyword(ctx2, "бот, нарисуй мем")
        assert 'status="error"' in block
        assert "через 10 мин" in block            # 620 сек → 10 мин 20 сек
        assert "весь чат" in block                # scope честно назван

    @pytest.mark.asyncio
    async def test_per_user_reply_names_user_scope(self, env, monkeypatch):
        _enable_freq(env, burst=1, cooldown=300.0, mode="per_user")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        res = await ig.generate_and_send(object(), CHAT, "p",
                                        reply_to_message_id=2, user_id=USER_A)
        assert res.ok is False and res.reason == "freq_limit"
        details = await ig.image_denial_details(res, CHAT, user_id=USER_A)
        assert "для тебя" in details
        assert "мин" in details


# ═══ CFG-02B.3 / AC4 / AC5: per-user и per-chat ════════════════════════════

class TestPerUserPerChat:
    @pytest.mark.asyncio
    async def test_per_user_a_exhausted_b_continues(self, env, monkeypatch):
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_user")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        a_second = await ig.generate_and_send(object(), CHAT, "p",
                                              reply_to_message_id=2,
                                              user_id=USER_A)
        assert a_second.ok is False and a_second.reason == "freq_limit"
        b_first = await ig.generate_and_send(object(), CHAT, "p",
                                             reply_to_message_id=3,
                                             user_id=USER_B)
        assert b_first.ok is True          # исчерпание A не блокирует B

    @pytest.mark.asyncio
    async def test_per_chat_shared_supply(self, env, monkeypatch):
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_B)).ok
        third = await ig.generate_and_send(object(), CHAT, "p",
                                          reply_to_message_id=3,
                                          user_id=USER_A)
        assert third.ok is False           # общий запас исчерпан
        b_third = await ig.generate_and_send(object(), CHAT, "p",
                                             reply_to_message_id=4,
                                             user_id=USER_B)
        assert b_third.ok is False         # любой из них заблокирован

    @pytest.mark.asyncio
    async def test_buckets_are_isolated_per_chat(self, env, monkeypatch):
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        other = await ig.generate_and_send(object(), CHAT_OTHER, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_A)
        assert other.ok is True            # другой чат — свой запас

    @pytest.mark.asyncio
    async def test_dm_positive_chat_id_not_mixed_with_daily(self, env,
                                                            monkeypatch):
        """DM (chat_id = user_id, положительный) работает; частотный счётчик
        не смешан с дневной квотой (daily используется независимо)."""
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_user")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        dm = USER_A
        assert (await ig.generate_and_send(object(), dm, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        denied = await ig.generate_and_send(object(), dm, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_A)
        assert denied.ok is False
        # Дневная квота списана ровно один раз (пауза частоты её не трогает).
        key = (wb.image_day(dm), f"chat:{dm}", wb.METRIC_IMAGE_CALLS)
        assert env.state.budget.get(key, 0) == 1

    @pytest.mark.asyncio
    async def test_unknown_requester_uses_chat_bucket_no_bypass(self, env,
                                                                monkeypatch):
        """Неизвестный requester в режиме per_user не получает «новый»
        счётчик — считается общий запас чата (обхода нет)."""
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_user")
        assert pt.image_freq_bucket_user("per_user", None) == 0
        assert pt.image_freq_bucket_user("per_user", USER_B) == USER_B
        assert pt.image_freq_bucket_user("per_chat", USER_B) == 0
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=None)).ok
        denied = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=2,
                                           user_id=None)
        assert denied.ok is False


# ═══ CFG-02B.4 / AC6 / AC7: семантика, hot-reload, рестарт, параллель ══════

class TestSemanticsLifecycle:
    @pytest.mark.asyncio
    async def test_off_lifts_pause_immediately_state_preserved(self, env,
                                                               monkeypatch):
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        assert not (await ig.generate_and_send(object(), CHAT, "p",
                                               reply_to_message_id=2,
                                               user_id=USER_A)).ok
        rows_before = await _throttle_rows(env.db)

        env.hot[FREQ_ENABLED_KEY] = False        # выключили без рестарта
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=3,
                                           user_id=USER_A)).ok

        env.hot[FREQ_ENABLED_KEY] = True         # включили обратно
        again = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=4,
                                           user_id=USER_A)
        assert again.ok is False                 # пауза не «подарена»
        assert await _throttle_rows(env.db) == rows_before   # не сброшено

    @pytest.mark.asyncio
    async def test_config_change_during_pause_keeps_state(self, env,
                                                          monkeypatch):
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        # Увеличение лимита посреди паузы не выдаёт «бонусных» зарядов.
        env.hot[FREQ_BURST_KEY] = 5
        still = await ig.generate_and_send(object(), CHAT, "p",
                                          reply_to_message_id=2,
                                          user_id=USER_A)
        assert still.ok is False
        # Уменьшение паузы честно укорачивает остаток на СЛЕДУЮЩЕЙ проверке.
        env.hot[FREQ_COOLDOWN_KEY] = 60.0
        shorter = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=3,
                                           user_id=USER_A)
        assert shorter.ok is False
        assert shorter.retry_after_seconds == pytest.approx(60.0, abs=2.0)

    @pytest.mark.asyncio
    async def test_mode_switch_does_not_reset_counters(self, env,
                                                       monkeypatch):
        """Переключение scope НЕ сбрасывает счётчики (скрытых «подарков» нет):
        после смены режима применяется счётчик нового scope со своим честным
        состоянием, а возврат к прежнему режиму возвращает прежний запрет."""
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_user")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        env.hot[FREQ_MODE_KEY] = "per_chat"
        # Новый счётчик (чат) ещё не расходовался — своё состояние честное.
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_A)).ok
        denied_chat = await ig.generate_and_send(object(), CHAT, "p",
                                                 reply_to_message_id=3,
                                                 user_id=USER_A)
        assert denied_chat.ok is False           # и он не «неограниченный»
        env.hot[FREQ_MODE_KEY] = "per_user"
        # Возврат к per-user: персональный запрет НЕ сброшен переключениями.
        assert not (await ig.generate_and_send(object(), CHAT, "p",
                                               reply_to_message_id=4,
                                               user_id=USER_A)).ok
        rows = {r[1]: r[2] for r in await _throttle_rows(env.db)}
        assert rows.get(USER_A) == 0 and rows.get(0) == 0

    @pytest.mark.asyncio
    async def test_state_survives_restart_and_is_shared_between_workers(
            self, env, monkeypatch):
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        # «Рестарт»/второй воркер: новый инстанс на той же БД (состояние
        # throttle_state лежит в БД, а не в инстансе).
        db2 = _bind_extra_db(env, env.path)
        await db2.initialize()
        lore_runtime.set_lore_components(db=db2)
        denied = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_A)
        assert denied.ok is False
        assert denied.retry_after_seconds == pytest.approx(600.0, abs=2.0)
        await db2.close()

    @pytest.mark.asyncio
    async def test_parallel_attempts_consume_exactly_burst(self, env,
                                                           monkeypatch):
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        results = await asyncio.gather(*[
            ig.generate_and_send(object(), CHAT, "p",
                                 reply_to_message_id=100 + i,
                                 user_id=USER_A)
            for i in range(5)])
        assert sum(1 for r in results if r.ok) == 2   # ровно ёмкость
        assert len(calls) == 2                        # и 2 платных вызова

    @pytest.mark.asyncio
    async def test_hot_reload_burst_takes_effect_without_restart(self, env,
                                                                 monkeypatch):
        """Смена лимита без рестарта: накопленные заряды обрезаются до нового
        лимита (кламп CFG-01), «бонусов» из старого запаса нет."""
        _enable_freq(env, burst=3, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        env.hot[FREQ_BURST_KEY] = 1               # без рестарта
        # Накопленные 2 заряда обрезаны до нового лимита 1 → эта попытка
        # расходует единственный допустимый заряд...
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_A)).ok
        # ...и со следующей попытки действует уже новый лимит.
        denied = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=3,
                                           user_id=USER_A)
        assert denied.ok is False


# ═══ CFG-02B.5: единый limiter для пользовательских путей; обложки — нет ══

class TestUserPathsAndCovers:
    @pytest.mark.asyncio
    async def test_direct_and_tool_paths_share_one_limiter(self, env,
                                                           monkeypatch):
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        # direct-путь (source="direct")
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           source="direct",
                                           user_id=USER_A)).ok
        # tool-путь (source="tool" через единый раннер)
        request = ig.build_image_request("tool", CHAT, "prompt",
                                         requester_id=USER_A,
                                         original_message_id=2)
        tool = await ig.run_image_request(request, bot=object(),
                                          correlation_id="r-tool")
        assert tool.ok is False and tool.reason == "freq_limit"
        assert len(calls) == 1                     # платного вызова не было

    @pytest.mark.asyncio
    async def test_summary_cover_path_is_not_charged(self, env, monkeypatch,
                                                     tmp_path):
        """Контур обложек (generate_image_verbose) не проходит пользовательский
        частотный лимитер ни per-user, ни per-chat."""
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_chat")

        async def _budget_ok(chat_id):
            return True

        monkeypatch.setattr(ig, "_consume_budget", _budget_ok)
        monkeypatch.setattr(ig, "_write_temp_image",
                            lambda content: str(tmp_path / "cover.jpg"))

        async def _fake_generate(prompt, **kw):
            return ig.GenerationResult(ok=True, reason="ok", content=b"cover")

        monkeypatch.setattr(ig, "generate", _fake_generate)
        path, reason = await ig.generate_image_verbose(
            "cover prompt", chat_id=CHAT, correlation_id="cover-1")
        assert reason == "ok" and path
        assert await _throttle_rows(env.db) == []   # заряд не израсходован

        # Пользовательский путь по-прежнему располагает полным запасом.
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=9,
                                           user_id=USER_A)).ok

    @pytest.mark.asyncio
    async def test_tool_path_message_carries_remaining_and_user(
            self, env, monkeypatch):
        """Tool-путь (§02B.5): сообщение модели получает ФАКТИЧЕСКИЙ остаток
        паузы, а участник доезжает до общего лимитера."""
        from unittest.mock import MagicMock

        from services.tool_router import ToolContext, ToolDeps, ToolRouter
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_user")
        captured = {}

        async def _fake_send(bot, chat_id, prompt, *, reply_to_message_id=None,
                             correlation_id=None, source="direct",
                             user_id=None):
            captured["user_id"] = user_id
            captured["source"] = source
            return ig.GenerationResult(ok=False, reason="freq_limit",
                                       retry_after_seconds=620.0)

        monkeypatch.setattr(ig, "unified_image_request_enabled", lambda: False)
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            _always_true())
        monkeypatch.setattr(ig, "generate_and_send", _fake_send)
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        ctx = ToolContext(CHAT, "бот, нарисуй мем", bot=object(),
                          reply_to_message_id=1, user_id=USER_A,
                          correlation_id="r-tool-freq")
        raw = await router._generate_image({"prompt": "кот"}, ctx)
        payload = json.loads(raw)
        assert payload["status"] == "error"
        assert payload["reason"] == "freq_limit"
        assert "через 10 мин" in payload["message"]     # свежий остаток
        assert "для тебя" in payload["message"]         # scope честно назван
        assert captured["user_id"] == USER_A            # участник доехал
        assert captured["source"] == "tool"

    @pytest.mark.asyncio
    async def test_direct_pre_gate_message_carries_remaining(self, env,
                                                             monkeypatch):
        """Прямой путь до конца: бот-блок отказа содержит остаток и не
        выполняет платный вызов."""
        _enable_freq(env, burst=1, cooldown=310.0, mode="per_user")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        first = SimpleNamespace(bot=object(), chat_id=CHAT, user_id=USER_B,
                                reply_to_message_id=1, correlation_id="a")
        assert 'status="ok"' in await ig.maybe_handle_keyword(
            first, "бот, нарисуй кота")
        second = SimpleNamespace(bot=object(), chat_id=CHAT, user_id=USER_B,
                                 reply_to_message_id=2, correlation_id="b")
        block = await ig.maybe_handle_keyword(second, "бот, нарисуй кота")
        assert 'status="error"' in block
        assert "через 5 мин" in block
        assert "для тебя" in block
        assert len(calls) == 1                          # платного вызова нет


# ═══ CFG-02B.7 / AC7: replay, ошибки провайдера/доставки, оба лимита ═══════

class TestReplayAndFailures:
    @pytest.mark.asyncio
    async def test_replay_does_not_consume_frequency_twice(self, env,
                                                           monkeypatch):
        _enable_freq(env, burst=3, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        first = await ig.generate_and_send(object(), CHAT, "p",
                                          reply_to_message_id=1,
                                          user_id=USER_A)
        assert first.ok is True
        replay = await ig.generate_and_send(object(), CHAT, "p",
                                            reply_to_message_id=1,
                                            user_id=USER_A)
        assert replay.ok is True and replay.reason == "already"
        assert len(calls) == 1
        rows = await _throttle_rows(env.db)
        assert rows and rows[0][2] == 2          # списано ровно 2 заряда (3−1)

    @pytest.mark.asyncio
    async def test_provider_error_keeps_charge_quota_returned(self, env,
                                                              monkeypatch):
        """Провайдер упал: дневная квота возвращена (release), заряд частоты
        НЕ возвращается (восстановление только по времени) — политика
        зафиксирована тестом."""
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate",
                            _fake_generate_factory(calls, ok=False,
                                                   reason="timeout"))
        failed = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)
        assert failed.ok is False and failed.reason == "timeout"
        assert env.state.budget.get(
            (wb.image_day(CHAT), f"chat:{CHAT}", wb.METRIC_IMAGE_CALLS),
            0) == 0                              # квота возвращена
        rows = await _throttle_rows(env.db)
        assert rows and rows[0][2] == 1          # но заряд остаётся расходом

    @pytest.mark.asyncio
    async def test_delivery_failure_keeps_charge(self, env, monkeypatch):
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))

        async def _boom(*a, **kw):
            raise RuntimeError("telegram down")

        monkeypatch.setattr(telegram_send, "send_photo", _boom)
        res = await ig.generate_and_send(object(), CHAT, "p",
                                        reply_to_message_id=1,
                                        user_id=USER_A)
        assert res.ok is False and res.reason == "send_failed"
        rows = await _throttle_rows(env.db)
        assert rows and rows[0][2] == 1          # расход состоялся

    @pytest.mark.asyncio
    async def test_both_limits_details_list_both(self, env, monkeypatch):
        """Оба лимита исчерпаны → сообщение содержит обе причины и сроки."""
        _enable_freq(env, burst=1, cooldown=600.0, mode="per_chat")
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        env.limits["chat"] = 1                   # суточная квота исчерпана
        denied = await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_A)
        assert denied.ok is False
        # Дневной отказ дополняется честной частотной строкой (оба лимита).
        details_daily = await ig.image_denial_details(
            denied, CHAT, user_id=USER_A, daily_already_shown=True)
        assert "мин" in details_daily or "сек" in details_daily
        # Частотный отказ дополняется суточной квотой (оба лимита).
        details_freq = await ig.image_denial_details(
            ig.GenerationResult(ok=False, reason="freq_limit",
                                retry_after_seconds=620.0),
            CHAT, user_id=USER_A)
        assert "через 10 мин" in details_freq
        assert "Суточная квота" in details_freq
        assert "оба ограничения" in details_freq


# ═══ CFG-02B.8: факты для секции «Лимиты генерации» ════════════════════════

class TestUsageFacts:
    @pytest.mark.asyncio
    async def test_facts_report_activity_scope_source_availability(
            self, env, monkeypatch):
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_user")
        monkeypatch.setattr(telegram_send, "send_photo", _noop_send())
        calls = []
        monkeypatch.setattr(ig, "generate", _fake_generate_factory(calls))
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=1,
                                           user_id=USER_A)).ok
        summary = await wb.image_usage_summary(None, CHAT,
                                               viewer_user_id=USER_A)
        freq = summary.get("freq")
        assert freq, "секция «Лимиты генерации» не получает факты частоты"
        assert freq["enabled"] is True and freq["active"] is True
        assert freq["mode"] == "per_user"
        assert freq["source"] == "global"
        assert freq["per_user"]["user_id"] == USER_A
        assert freq["per_user"]["charges_left"] == 1
        assert freq["per_chat"]["charges_left"] == 2   # per_user не трогал чат
        assert freq["per_user"]["next_available_at"] is None   # паузы нет

        # Исчерпание: следующий доступный момент появляется честно.
        assert (await ig.generate_and_send(object(), CHAT, "p",
                                           reply_to_message_id=2,
                                           user_id=USER_A)).ok
        summary2 = await wb.image_usage_summary(None, CHAT,
                                                viewer_user_id=USER_A)
        freq2 = summary2["freq"]
        assert freq2["per_user"]["charges_left"] == 0
        assert freq2["per_user"]["next_available_at"]

    @pytest.mark.asyncio
    async def test_facts_are_honest_when_not_active(self, env, monkeypatch):
        # Заводской OFF: активность честно выключена.
        summary = await wb.image_usage_summary(None, CHAT,
                                               viewer_user_id=USER_A)
        freq = summary["freq"]
        assert freq["enabled"] is False and freq["active"] is False
        assert freq["active_reason"] == "switch_off"
        assert freq["source"] in ("default", "global", "chat")

        # Включён, но master-рубильник бюджетов OFF → не действует (честно).
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_chat")

        async def _budgets_off(*a, **kw):
            return False

        monkeypatch.setattr(budget_gate, "budgets_enabled", _budgets_off)
        summary2 = await wb.image_usage_summary(None, CHAT,
                                                viewer_user_id=USER_A)
        assert summary2["freq"]["enabled"] is True
        assert summary2["freq"]["active"] is False
        assert summary2["freq"]["active_reason"] == "master_off"

    @pytest.mark.asyncio
    async def test_day_summary_passes_viewer(self, env):
        _enable_freq(env, burst=2, cooldown=600.0, mode="per_user")
        summary = await wb.get_day_summary(env.pg, viewer_user_id=USER_B)
        entry = next(c for c in summary["chats"]
                     if c["scope"] == f"chat:{CHAT}")
        assert entry["image_usage"]["freq"]["per_user"]["user_id"] == USER_B


# ═══ витрина (web/app.js + web/index.html) ════════════════════════════════

class TestUiContract:
    def test_js_declares_keys_labels_and_helpers(self):
        for token in ("IMAGE_FREQ_ENABLED_KEY", "IMAGE_FREQ_BURST_KEY",
                      "IMAGE_FREQ_COOLDOWN_KEY", "IMAGE_FREQ_MODE_KEY",
                      "'limits.image_freq_limit_enabled'",
                      "'limits.image_freq_limit_mode'",
                      "imageFreqSettingsHidden", "imageFreqFacts",
                      "imageFreqActiveLabel", "imageFreqRemainingText",
                      "imageFreqNextLabel"):
            assert token in JS, token

    def test_js_labels_are_human_and_factual(self):
        m = re.search(r"'limits\.image_freq_limit_enabled': \{\s*title: "
                      r"'([^']+)'", JS)
        assert m and "частот" in m.group(1).lower()
        block = re.search(
            r"'limits\.image_freq_limit_enabled': \{(.*?)\n    \},",
            JS, re.S).group(1)
        # Заводской OFF назван честно (без шаблона «Включает… Выключено» —
        # запрет round109 §4.2.3): лимит не действует по умолчанию.
        assert "не действует" in block.lower()
        assert "заводской" in block.lower()
        burst = re.search(r"'limits\.image_freq_limit_burst': \{(.*?)\n    \},",
                          JS, re.S).group(1)
        assert "подряд" in burst
        cool = re.search(
            r"'limits\.image_freq_limit_cooldown_seconds': \{(.*?)\n    \},",
            JS, re.S).group(1)
        assert "секунд" in cool and "мин" in cool
        mode = re.search(r"'limits\.image_freq_limit_mode': \{(.*?)\n    \},",
                         JS, re.S).group(1)
        assert "пользовател" in mode.lower() and "чат" in mode.lower()

    def test_ui_marks_facts_block_and_dependent_settings(self):
        for marker in ("data-image-freq-facts", "data-image-freq-active",
                       "data-image-freq-mode", "data-image-freq-remaining",
                       "data-image-freq-source", "data-image-freq-next",
                       "data-image-freq-note"):
            assert marker in HTML, marker
        # Скрытие зависимых настроек при OFF (компактность §02B.2).
        assert "imageFreqSettingsHidden(item)" in HTML

    def test_mode_is_rendered_as_single_select(self):
        assert "widget === 'select'" in HTML        # общий select-рендер
        assert "IMAGE_FREQ_MODE_KEY" in JS
