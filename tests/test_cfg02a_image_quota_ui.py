"""CFG-02A — суточная квота изображений: видима, управляема, реально влияет.

Покрытие строк карты `plans/features/cfg/requirements-map.json` (слайс CFG-02A):
  * CFG-02.D / CFG-02A.1 — секция «Лимиты генерации» в модуле «Генерация
    изображений» → «Основные настройки»; фактическое GLOBAL/CHAT-значение,
    один источник истины (каталог `limits.image_daily_limit`);
  * CFG-02A.2 — название/единицы/источник/расход/остаток/TZ/ближайший сброс
    и точная подсказка про списание (несколько картинок, повторная доставка);
  * CFG-02A.3 — GLOBAL-дефолт, независимый CHAT-override, сброс override →
    наследование без изменения GLOBAL, семантика 0/−1/>0, невалидный ввод
    не отправляется (клиент) + серверный тип-контракт;
  * CFG-02A.4 — изменение значения без рестарта меняет worker_budget/
    reserve_image и разрешение/отказ; честный режим применения (тахометр:
    env kill-switch / master-рубильник / shared env-бюджет);
  * CFG-02A.5 — отказ ДО платного вызова с честным временем сброса по TZ;
  * CFG-02A.6 — все пользовательские пути учтены; повторная обработка того же
    запроса не списывает квоту второй раз (idempotency журнала);
  * CFG-02A.7 — тесты GLOBAL/CHAT/возврат/0/−1/малое число/второй чат/
    рестарт/смена суток+TZ/параллель/ошибка провайдера/ошибка Telegram
    delivery/shared-limit/factory-дефолт.

PG-зависимые пути ПЕРЕИСПОЛЬЗУЮТ минимальный in-memory стаб из
`tests/test_image_daily_limit_round1026.py` (второй стаб не создаётся).

TEST-LIFECYCLE: CONTRACT owner=CFG-02A (каталог/UI-контракт)
TEST-LIFECYCLE: REGRESSION owner=CFG-02A (дефект «суточный лимит не виден в
модуле и не управляет генерацией»)
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

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import budget_gate                       # noqa: E402
from services import image_generation as ig            # noqa: E402
from services import param_catalog as pc                # noqa: E402
from services import telegram_send                      # noqa: E402
from services import worker_budget as wb                # noqa: E402
from services.param_catalog import TAB_MOD_IMAGES       # noqa: E402
from tests.test_image_daily_limit_round1026 import (    # noqa: E402
    _reset_purge, _set_kill_switch, make_pg)

JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

IMAGE_QUOTA_KEY = "limits.image_daily_limit"
QUOTA_GROUP = "limits_images"
CHAT = -1009001
CHAT_OTHER = -1009002


# ═══ окружение (слои настроек + PG-стаб) ═══════════════════════════════════

def _set_env(name: str, value, monkeypatch) -> None:
    """Патч env-поля Settings на КЛАССАХ, которые реально читает рантайм
    (прецедент `_set_kill_switch`: после reload классов может быть несколько)."""
    from config.settings import Settings
    classes = {Settings, type(ig.settings), type(wb.settings)}
    for _cls in classes:
        if hasattr(_cls, name):
            monkeypatch.setattr(_cls, name, value)


@pytest.fixture()
def hot(monkeypatch):
    """ConfigCache-двойник: `store` = ГЛОБАЛЬНЫЙ слой настроек.

    Запись в `store` эквивалентна POST /api/config (ConfigCache обновляется
    in-process) — так проверяется hot-reload БЕЗ рестарта процесса."""
    from services import hot_config as hot_mod
    store: dict = {}

    class _FakeConfigCache:
        def get(self, key, default=None):
            return store.get(key, default)

    monkeypatch.setattr(hot_mod, "_cache", _FakeConfigCache())
    return store


@pytest.fixture()
def overrides(monkeypatch):
    """chat_params-двойник: per-chat overrides по chat_id (слой ЧАТА)."""
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
def env(monkeypatch, hot, overrides):
    """Изолированная среда: PG-стаб + управляемые слои настроек + детерминант."""
    pg, state = make_pg()
    monkeypatch.setattr(wb, "_chat_tz_name", lambda chat_id: "UTC")

    async def _budgets_on(*a, **kw):
        return True

    monkeypatch.setattr(budget_gate, "budgets_enabled", _budgets_on)
    _set_env("WORKER_DAILY_IMAGE_CALLS_PER_CHAT", 60, monkeypatch)
    _set_env("WORKER_DAILY_IMAGE_CALLS_GLOBAL", 200, monkeypatch)
    _set_kill_switch(monkeypatch, True)
    wb.set_worker_budget_pg(pg)
    _reset_purge()
    yield SimpleNamespace(pg=pg, state=state, hot=hot, overrides=overrides)
    wb.set_worker_budget_pg(None)


def _chat_key(chat_id: int) -> tuple:
    return (wb.image_day(chat_id), f"chat:{chat_id}", wb.METRIC_IMAGE_CALLS)


def _shared_key() -> tuple:
    return (wb.today(), "global", wb.METRIC_IMAGE_CALLS)


async def _reserve(chat_id: int, msg_id: int, source: str = "direct"):
    """Резерв одной пользовательской генерации.

    ``pg=None`` — как в проде: используется runtime-PG, выставленный фикстурой
    (`worker_budget.set_worker_budget_pg`)."""
    return await wb.reserve_image(
        None, chat_id=chat_id,
        idem_key=ig.build_image_idem_key(chat_id, message_id=msg_id,
                                         source=source),
        source=source, message_id=msg_id)


# ═══ CFG-02.D / CFG-02A.1: каталог + UI-проводка (CONTRACT) ════════════════

class TestCfg02aCatalogAndUiContract:
    """Видимость и «один источник истины»: каталог (ключ/группа/тип) +
    витринные подписи web/app.js + разметка секции в web/index.html."""

    def test_catalog_key_invariants(self):
        """Каталог НЕ переименовывается (Δ каталога = 0): меняются только
        витринные подписи — иначе ломаются замороженные артефакты каталога
        (прецедент R1 CFG-01; каталоговые названия — CFG-03)."""
        groups = {g.id: g for g in pc.GROUPS}
        grp = groups[QUOTA_GROUP]
        assert grp.category == "limits"
        spec = pc.get_by_pg_key(IMAGE_QUOTA_KEY)
        assert spec is not None
        assert spec.type == "int"
        assert spec.group == QUOTA_GROUP
        assert spec.per_chat is True          # GLOBAL-дефолт + CHAT override
        assert spec.secret is False

    def test_catalog_artifacts_untouched(self):
        """Замороженные срезы каталога не сдвинуты этим слайсом."""
        assert len(pc.REGISTRY) == 579
        assert len(pc.GROUPS) == 120

    def test_vitrina_labels_and_units(self):
        """CFG-02A.1/02A.2: секция «Лимиты генерации» + «Изображений в сутки»
        + единицы + семантика 0/−1 + политика списания — на уровне витрины."""
        m = re.search(r"limits_images: \{\s*title: '([^']+)'", JS)
        assert m, "витринное имя группы limits_images не найдено"
        assert m.group(1) == "Лимиты генерации"
        m2 = re.search(r"'limits\.image_daily_limit': \{\s*title: '([^']+)'",
                       JS)
        assert m2, "витринная подпись параметра не найдена"
        assert m2.group(1) == "Изображений в сутки"
        blk = re.search(r"'limits\.image_daily_limit': \{(.*?)\n    \},",
                        JS, re.S).group(1)
        assert "генераций в сутки" in blk
        assert "0 — генерация запрещена" in blk
        assert "−1 — безлимит" in blk
        assert "повторная доставка" in blk
        # Подписи доезжают до элементов конфига (единый display-путь).
        assert "CONFIG_ITEM_DISPLAY_OVERRIDES[item.key]" in JS

    def test_group_belongs_to_images_module_tab(self):
        assert QUOTA_GROUP in pc.tab_group_ids(TAB_MOD_IMAGES)

    def test_js_mirror_declares_limits_group(self):
        """Зеркало TAB_RULES: без объявления группы в источниках вкладки
        суточная квота не рендеровалась нигде (вкладка «Лимиты» скрывалась
        как пустая) — корневая причина UI-дефекта CFG-02.D."""
        m = re.search(r"\{ id: 'mod_images'.*?\n      \] \},",
                      JS, re.S)
        assert m, "запись mod_images не найдена в web/app.js"
        block = m.group(0)
        assert "groups: ['limits_images']" in block
        assert "category: 'limits'" in block

    def test_limits_group_renders_on_settings_tab(self):
        """Требование владельца: секция — в «Основные настройки» модуля."""
        m = re.search(r"workspaceGroupTab: function \(m, grp\) \{(.*?)\n      \},",
                      JS, re.S)
        assert m
        body = m.group(1)
        assert "grp.id === 'limits_images'" in body
        assert "return 'settings';" in body

    def test_ui_marks_facts_and_guard(self):
        for marker in ("data-image-quota-facts", "data-image-quota-value",
                       "data-image-quota-used", "data-image-quota-remaining",
                       "data-image-quota-tz", "data-image-quota-reset",
                       "data-image-quota-mode", "data-image-quota-hint",
                       "data-image-quota-shared", "data-image-quota-input"):
            assert marker in HTML, marker
        assert 'min="-1" step="1"' in HTML
        # Старая read-only врезка на отдельной вкладке «Лимиты» убрана —
        # одно место фактов и одно место настройки (второго источника нет).
        assert "data-image-limits" not in HTML
        assert "data-image-limit-chat" not in HTML

    def test_ui_hint_is_factual(self):
        """Подсказка точно объясняет списание: одна генерация = одно списание;
        повторная обработка/доставка — не списывают (02A.2)."""
        m = re.search(r"data-image-quota-hint>(.*?)</div>", HTML, re.S)
        assert m, "подсказка не найдена"
        hint = re.sub(r"\s+", " ", m.group(1))
        assert "одно списание" in hint
        assert "повторная" in hint and "не списывают" in hint
        assert "каждая новая генерация списывается отдельно" in hint

    def test_client_guard_blocks_invalid_value(self):
        assert f"var IMAGE_QUOTA_KEY = '{IMAGE_QUOTA_KEY}'" in JS
        assert "function imageQuotaValueValid(raw)" in JS
        m = re.search(r"function imageQuotaValueValid\(raw\) \{(.*?)\n  \}",
                      JS, re.S)
        assert m and "IMAGE_QUOTA_MIN" in m.group(1)
        assert "saveImageDailyLimit: async function" in JS
        body = re.search(r"saveImageDailyLimit: async function \(item, raw\)"
                         r" \{(.*?)\n      \},", JS, re.S)
        assert body
        blk = body.group(1)
        assert "imageQuotaValueValid(raw)" in blk
        assert "imageQuotaInputError" in blk
        # Пустой/пробельный ввод — НЕВАЛИДЕН (B1 ревью `10c15cf5`):
        # `Number('') === 0` иначе молча сохраняет 0 («генерация запрещена»).
        fn = re.search(r"function imageQuotaValueValid\(raw\) \{(.*?)\n  \}",
                       JS, re.S)
        assert fn and "String(raw).trim() === ''" in fn.group(1)
        assert "raw == null" in fn.group(1)
        # Невалидное значение НЕ уходит на сервер (return ДО saveConfigItem).
        assert blk.index("return false;") < blk.index("saveConfigItem(item)")
        # Значение без изменений не сохраняется: пересинхронизация поля при
        # смене области не создаёт per-chat override «на ровном месте».
        assert "return true;   // no-op: 0 POST" in blk
        # Загрузка фактов повешена на вкладку «Основные настройки».
        assert "if (tab === 'settings') this.maybeLoadImageQuota();" in JS


# ═══ CFG-02A.4: значение реально влияет без рестарта ════════════════════════

class TestCfg02aEffectiveImpact:
    """Правка настройки (глобально/в чате) меняет фактический лимит и
    разрешение/отказ резерва БЕЗ рестарта; чужие чаты и общий бюджет не
    смешиваются."""

    @pytest.mark.asyncio
    async def test_global_change_takes_effect_without_restart(self, env):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        # GLOBAL: 2 генерации/сутки (как «минимум» владельца).
        env.hot[IMAGE_QUOTA_KEY] = 2
        shared, per_chat, source = await wb.image_limits(CHAT)
        assert (shared, per_chat, source) == (200, 2, "global")
        for msg in (1, 2):
            res = await _reserve(CHAT, msg)
            assert res.ok is True, res
        denied = await _reserve(CHAT, 3)
        assert denied.ok is False and denied.reason == "limit_chat"
        assert env.state.budget[_chat_key(CHAT)] == 2

        # Возврат 5 без рестарта: третья попытка проходит.
        env.hot[IMAGE_QUOTA_KEY] = 5
        again = await _reserve(CHAT, 4)
        assert again.ok is True, again
        assert env.state.budget[_chat_key(CHAT)] == 3

    @pytest.mark.asyncio
    async def test_small_positive_one_then_deny(self, env):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 1        # граница: малое положительное
        assert (await _reserve(CHAT, 1)).ok is True
        denied = await _reserve(CHAT, 2)
        assert denied.ok is False and denied.reason == "limit_chat"
        assert denied.status == "denied"

    @pytest.mark.asyncio
    async def test_zero_is_forbidden_and_does_not_consume(self, env):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 0        # 0 = запрет (канон budget_limits)
        denied = await _reserve(CHAT, 1)
        assert denied.ok is False and denied.reason == "limit_chat"
        assert env.state.budget.get(_chat_key(CHAT), 0) == 0
        assert env.state.budget.get(_shared_key(), 0) == 0   # shared откачен

    @pytest.mark.asyncio
    async def test_minus_one_is_unlimited_and_still_accounted(self, env):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = -1       # −1 = безлимит
        for msg in range(1, 6):
            assert (await _reserve(CHAT, msg)).ok is True
        assert env.state.budget[_chat_key(CHAT)] == 5        # расход учтён
        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["limit"] == -1
        assert summary["used"] == 5

    @pytest.mark.asyncio
    async def test_chat_override_isolated_and_reset_keeps_global(
            self, env):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 3        # GLOBAL-дефолт
        env.overrides[CHAT] = {IMAGE_QUOTA_KEY: 1}   # CHAT override
        _s, per_chat, source = await wb.image_limits(CHAT)
        assert (per_chat, source) == (1, "chat")
        # Другой чат работает по GLOBAL — override его не касается.
        assert (await _reserve(CHAT_OTHER, 1)).ok is True
        assert (await _reserve(CHAT_OTHER, 2)).ok is True
        # Чат с override: ровно 1 генерация.
        assert (await _reserve(CHAT, 1)).ok is True
        assert (await _reserve(CHAT, 2)).ok is False
        # Сброс override → наследование GLOBAL, GLOBAL не изменён.
        env.overrides.pop(CHAT)
        _s2, per_chat2, source2 = await wb.image_limits(CHAT)
        assert (per_chat2, source2) == (3, "global")
        assert env.hot[IMAGE_QUOTA_KEY] == 3
        assert (await _reserve(CHAT, 3)).ok is True   # новый ключ запроса
        assert env.state.budget[_chat_key(CHAT)] == 2

    @pytest.mark.asyncio
    async def test_factory_default_when_keys_absent(self, env):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        _shared, per_chat, source = await wb.image_limits(CHAT)
        assert (per_chat, source) == (60, "default")   # заводской default
        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["source"] == "default"
        assert summary["limit"] == 60

    @pytest.mark.asyncio
    async def test_restart_keeps_used_and_limit(self, env):
        """Счётчик дня и значение живут в слоях PG/каталога: «рестарт»
        процесса (пере-инициализация PG-биндинга) не обнуляет расход."""
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 2
        assert (await _reserve(CHAT, 1)).ok is True
        wb.set_worker_budget_pg(None)       # «рестарт»: процесс-локальный слой
        wb.set_worker_budget_pg(env.pg)     # тот же PG/каталог после рестарта
        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["used"] == 1
        assert summary["limit"] == 2
        assert (await _reserve(CHAT, 2)).ok is True
        assert (await _reserve(CHAT, 3)).ok is False

    @pytest.mark.asyncio
    async def test_day_change_resets_usage_and_reset_time_in_chat_tz(
            self, env, monkeypatch):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        tz = "Pacific/Kiritimati"            # UTC+14
        monkeypatch.setattr(wb, "_chat_tz_name", lambda chat_id: tz)
        env.hot[IMAGE_QUOTA_KEY] = 1
        assert (await _reserve(CHAT, 1)).ok is True
        assert (await _reserve(CHAT, 2)).ok is False
        # Смена суток (следующий календарный день чата) — квота снова полная.
        tomorrow = wb.image_day(CHAT) + datetime.timedelta(days=1)
        monkeypatch.setattr(wb, "image_day", lambda chat_id: tomorrow)
        assert (await _reserve(CHAT, 3)).ok is True
        nxt = wb.image_next_reset(CHAT)
        now = datetime.datetime.now(ZoneInfo(tz))
        assert now < nxt <= now + datetime.timedelta(days=1)
        assert (nxt.hour, nxt.minute, nxt.second) == (0, 0, 0)
        assert wb.image_timezone(CHAT) == tz

    @pytest.mark.asyncio
    async def test_parallel_reserves_exactly_one_at_boundary(
            self, env, monkeypatch):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 1
        _set_env("WORKER_DAILY_IMAGE_CALLS_GLOBAL", 1, monkeypatch)
        results = await asyncio.gather(
            _reserve(CHAT, 1), _reserve(CHAT, 2))
        assert sorted(r.ok for r in results) == [False, True]
        assert env.state.budget[_shared_key()] == 1
        assert env.state.budget[_chat_key(CHAT)] == 1

    @pytest.mark.asyncio
    async def test_reserve_mode_is_honest(self, env, monkeypatch):
        """Честный режим применения: reserve по умолчанию; kill-switch OFF и
        master OFF дают legacy с ПРИЧИНОЙ (UI не заявляет «лимит применён»)."""
        assert await ig.image_reserve_mode(CHAT) == ("reserve", "ok")

        async def _off(*a, **kw):
            return False

        monkeypatch.setattr(budget_gate, "budgets_enabled", _off)
        assert await ig.image_reserve_mode(CHAT) == ("legacy", "budgets_off")

        async def _on(*a, **kw):
            return True

        monkeypatch.setattr(budget_gate, "budgets_enabled", _on)
        _set_kill_switch(monkeypatch, False)
        assert await ig.image_reserve_mode(CHAT) == (
            "legacy", "kill_switch_off")
        # Диагностика §27 отдаёт тот же факт в существующем ответе бюджета.
        env.hot[IMAGE_QUOTA_KEY] = 7
        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["reserve_path"] == "legacy"
        assert summary["reserve_reason"] == "kill_switch_off"


# ═══ CFG-02A.5: отказ ДО платного вызова + честный сброс ═══════════════════

class TestCfg02aRefusalHonesty:

    @pytest.mark.asyncio
    async def test_deny_before_paid_call_with_reset_time(self, env,
                                                         monkeypatch):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 0        # квота исчерпана/запрещена
        calls = {"gen": 0}

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 consume_budget=True, **kw):
            calls["gen"] += 1
            return ig.GenerationResult(ok=True, reason="ok", content=b"x")

        monkeypatch.setattr(ig, "generate", _fake_generate)
        res = await ig.generate_and_send(object(), CHAT, "prompt",
                                         reply_to_message_id=77,
                                         source="direct")
        assert res.ok is False and res.reason == "budget"
        assert calls["gen"] == 0            # отказ ДО платного вызова
        denied = env.state.res[f"{CHAT}:77:direct"]
        assert denied["status"] == "denied"
        assert denied["error_code"] == "limit_chat"

    def test_refusal_text_carries_honest_reset_time(self, env, monkeypatch):
        monkeypatch.setattr(wb, "_chat_tz_name",
                            lambda chat_id: "Asia/Yekaterinburg")
        res = ig.GenerationResult(ok=False, reason="budget")
        block = ig._image_error_block(res, chat_id=CHAT)
        from services.chat_prompts import IMAGE_FAILURE_QUOTA_TEXT
        assert IMAGE_FAILURE_QUOTA_TEXT in block      # речевая форма SOUL-1
        nxt = wb.image_next_reset(CHAT)
        stamp = nxt.strftime("%d.%m.%Y %H:%M")
        assert f"Суточная квота обновится {stamp}" in block
        assert "(Asia/Yekaterinburg)" in block
        # Дневной сброс не подменяется коротким cooldown-ом: времени «через
        # N минут» в отказе нет.
        assert "через" not in block.lower()

    def test_reset_note_is_fail_open(self, monkeypatch):
        """Ошибка резолва периода не искажает отказ выдуманным временем."""
        monkeypatch.setattr(wb, "image_next_reset",
                            lambda chat_id: (_ for _ in ()).throw(RuntimeError()))
        assert ig.image_quota_reset_note(CHAT) == ""


# ═══ CFG-02A.6: пользовательские пути и повторная обработка ═════════════════

class TestCfg02aUserPaths:
    """Пользовательская генерация (direct/tool) списывается ровно один раз;
    повторная обработка того же запроса квоту не увеличивает."""

    @pytest.mark.asyncio
    async def test_direct_and_tool_paths_use_chat_quota(self, env,
                                                        monkeypatch):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 2        # квота на два обращения
        seen = []

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 consume_budget=True, **kw):
            return ig.GenerationResult(ok=True, reason="ok", content=b"x")

        async def _send(*a, **kw):
            return None

        orig_reserve = wb.reserve_image

        async def _spy_reserve(pg, *, chat_id, idem_key, source, **kw):
            seen.append((chat_id, source, idem_key))
            return await orig_reserve(pg, chat_id=chat_id, idem_key=idem_key,
                                      source=source, **kw)

        monkeypatch.setattr(ig, "generate", _fake_generate)
        monkeypatch.setattr(telegram_send, "send_photo", _send)
        monkeypatch.setattr(wb, "reserve_image", _spy_reserve)

        direct = await ig.generate_and_send(object(), CHAT, "prompt",
                                            reply_to_message_id=11,
                                            source="direct")
        assert direct.ok is True
        assert seen[-1][0] == CHAT and seen[-1][1] == "direct"
        # Повторная обработка того же сообщения (ретрай Telegram/повтор):
        # второй платной генерации и второго списания НЕТ.
        replay = await ig.generate_and_send(object(), CHAT, "prompt",
                                            reply_to_message_id=11,
                                            source="direct")
        assert replay.ok is True and replay.reason == "already"
        assert env.state.budget[_chat_key(CHAT)] == 1

        # Семантический путь инструмента (source='tool') — та же квота.
        tool = await ig.generate_and_send(object(), CHAT, "prompt",
                                          reply_to_message_id=12,
                                          source="tool")
        assert tool.ok is True
        assert seen[-1][0] == CHAT and seen[-1][1] == "tool"
        assert env.state.budget[_chat_key(CHAT)] == 2

    @pytest.mark.asyncio
    async def test_provider_error_returns_quota_and_delivery_keeps_charge(
            self, env, monkeypatch):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 5
        state = {"fail": True}

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 consume_budget=True, **kw):
            if state["fail"]:
                return ig.GenerationResult(ok=False, reason="timeout")
            return ig.GenerationResult(ok=True, reason="ok", content=b"x")

        async def _send_boom(*a, **kw):
            raise RuntimeError("telegram down")

        monkeypatch.setattr(ig, "generate", _fake_generate)
        failed = await ig.generate_and_send(object(), CHAT, "prompt",
                                            reply_to_message_id=21,
                                            source="direct")
        assert failed.ok is False and failed.reason == "timeout"
        assert env.state.res[f"{CHAT}:21:direct"]["status"] == "released"
        assert env.state.budget.get(_chat_key(CHAT), 0) == 0   # квота возвращена

        state["fail"] = False
        monkeypatch.setattr(telegram_send, "send_photo", _send_boom)
        sent = await ig.generate_and_send(object(), CHAT, "prompt",
                                          reply_to_message_id=22,
                                          source="direct")
        assert sent.ok is False and sent.reason == "send_failed"
        row = env.state.res[f"{CHAT}:22:direct"]
        assert row["status"] == "committed"      # генерация состоялась — расход
        assert row["delivery_failed"] is True
        assert env.state.budget[_chat_key(CHAT)] == 1


# ═══ CFG-02A.7: негатив/границы слоя настроек ══════════════════════════════

class TestCfg02aLayerBoundaries:

    @pytest.mark.asyncio
    async def test_shared_env_limit_denies_even_with_chat_quota_left(
            self, env, monkeypatch):
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 50
        _set_env("WORKER_DAILY_IMAGE_CALLS_GLOBAL", 1, monkeypatch)
        assert (await _reserve(CHAT, 1)).ok is True
        denied = await _reserve(CHAT, 2)
        assert denied.ok is False and denied.reason == "limit_global"
        summary = await wb.image_usage_summary(env.pg, CHAT)
        assert summary["shared_limit"] == 1
        assert summary["shared_used"] == 1

    @pytest.mark.asyncio
    async def test_invalid_type_in_override_falls_back_to_global(self, env):
        """Мусор в слое чата не становится лимитом (fail-open на GLOBAL)."""
        _ = env  # фикстура: runtime-PG/слои настроек активны для вызова
        env.hot[IMAGE_QUOTA_KEY] = 4
        env.overrides[CHAT] = {IMAGE_QUOTA_KEY: "abc"}
        _shared, per_chat, source = await wb.image_limits(CHAT)
        assert (per_chat, source) == (4, "global")

    def test_catalog_int_cast_and_gap_documented(self):
        """Слой каталога: '12' кастуется в int (как в API-пути); нечисловое
        значение НЕ превращается в лимит молча.

        Диапазонная валидация — на клиенте (`imageQuotaValueValid`, тест
        `test_client_guard_blocks_invalid_value`); каталоговые min/max для
        параметров — предмет CFG-03 (аудит ВСЕХ параметров), прецедент R1
        CFG-01: здесь второй источник истины не создаётся."""
        assert pc.normalize_value(IMAGE_QUOTA_KEY, "12") == 12
        assert pc.normalize_value(IMAGE_QUOTA_KEY, "abc") == "abc"
