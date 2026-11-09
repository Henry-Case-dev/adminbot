"""MOD-ACL-UX-01 M2 — полнота состояния capability (ТЗ §2.1/§2.2/§2.3).

Проверяется РЕАЛЬНОЕ состояние, а не факт вызова функций:

* `ready` собирается из технических предпосылок (dependencies/indexes/
  providers/permissions) и даёт конкретный машинный код причины;
* `authorized` / `can_read` / `can_edit` — отдельные оси: «может читать, но
  не менять» — нормальное состояние, а не `enabled=false`;
* `consent_required` ≠ `permission_denied` ≠ `emergency_block` ≠
  `gate_conflict:<x>` — разные причины, не подменяют друг друга;
* `gates_opt_in=false` — согласие, а НЕ мастер-запрет (§2.4-8);
* конфликт двух записей одной capability больше не «тихий false» (§2.4-4);
* `observed_at`/`version`/`pending_restart`/`last_activity_at` присутствуют
  и заполняются честно (нет источника → None, а не выдуманное значение).
"""
import copy
import types

import pytest

from services import chat_params, feature_gates, hot_config, module_registry
from services import mca_experience_jobs as jobs


class _Cache:
    """chat_params-кэш: root + optimistic-версия профиля, без side effects."""

    def __init__(self, by_chat=None, version="2026-11-09T10:00:00+00:00"):
        self.by_chat = copy.deepcopy(by_chat or {})
        self.version = version
        self.invalidated: list[int] = []

    async def get_chat_params(self, chat_id):
        data = self.by_chat.get(int(chat_id), {})
        return {"overrides": dict(data.get("overrides") or {}),
                "gates": dict(data.get("gates") or {})}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), self.version

    async def get_chat_params_checked(self, chat_id):
        return await self.get_chat_params(chat_id), True

    async def invalidate_chat(self, chat_id):
        self.invalidated.append(int(chat_id))


@pytest.fixture
def world(monkeypatch):
    class World:
        def __init__(self):
            self.globals: dict = {}

    w = World()
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: w.globals.get(key, default))
    monkeypatch.setattr(module_registry, "env_enabled",
                        lambda module_id: True)
    chat_params.set_activity_provider(None)
    yield w
    chat_params.set_chat_params_cache(None)
    chat_params.set_activity_provider(None)


def _set_chat(by_chat, **kwargs):
    cache = _Cache(by_chat, **kwargs)
    chat_params.set_chat_params_cache(cache)
    return cache


def _root(overrides=None, gates=None):
    return {"overrides": dict(overrides or {}), "gates": dict(gates or {})}


# ── Prerequisites: состав готовности ────────────────────────────────────────

def test_prerequisites_empty_means_not_evaluated():
    """Пустой набор предпосылок — `ready=None` («не оценивалось»), а не
    ложное «готово» и не «не готово» (§2.2)."""
    ready, reason = chat_params.Prerequisites().evaluate()
    assert ready is None and reason is None


def test_prerequisites_report_concrete_reason_per_group():
    """Каждая группа даёт свой код: провайдер/индекс/зависимость/права."""
    cases = [
        (chat_params.Prerequisites(providers={"stt": False}),
         "provider_missing:stt"),
        (chat_params.Prerequisites(indexes={"embeddings": False}),
         "index_missing:embeddings"),
        (chat_params.Prerequisites(dependencies={"dream_worker": False}),
         "dependency_missing:dream_worker"),
        (chat_params.Prerequisites(permissions={"chat_profile": False}),
         "permission_missing:chat_profile"),
    ]
    for pre, expected in cases:
        ready, reason = pre.evaluate()
        assert ready is False and reason == expected
    ready, reason = chat_params.Prerequisites(
        providers={"llm": True}, dependencies={"worker": True}).evaluate()
    assert ready is True and reason is None
    # первая недоступная по фиксированному порядку групп — не случайная
    ready, reason = chat_params.Prerequisites(
        dependencies={"worker": False},
        providers={"llm": False}).evaluate()
    assert reason == "dependency_missing:worker"


@pytest.mark.asyncio
async def test_desired_on_ready_false_with_exact_reason(world):
    """§2.2/§10-6: desired=ON, но провайдер недоступен → requested ON,
    ready=false, конкретная причина, НЕ «тихий OFF» в хранилище."""
    world.globals = {"flags.dream_enabled": False}
    stored = {-100: _root(gates={"dream": True})}
    _set_chat(stored)
    state = await feature_gates.gate_state(
        -100, "dream", root=stored[-100],
        prerequisites=chat_params.Prerequisites(providers={"stt": False}))
    assert state.desired is True and state.chat_state == chat_params.ON
    assert state.ready is False
    assert state.effective_runtime is False
    assert state.reason_code == "provider_missing:stt"
    # сохранённое значение не переписано
    assert stored[-100]["gates"]["dream"] is True


@pytest.mark.asyncio
async def test_gate_readiness_uses_real_llm_provider_check(world, monkeypatch):
    """`with_readiness=True` на gates-домене: реальная проверка LLM-провайдера
    (hot-ключи `models.llm_*`), а не заглушка."""
    world.globals = {"flags.dream_enabled": True,
                     "models.llm_base_url": "https://llm.example/v1",
                     "models.llm_model_name": "m"}
    _set_chat({-100: _root({})})
    ready_state = await feature_gates.gate_state(
        -100, "dream", root=_root({}), with_readiness=True)
    assert ready_state.ready is True and ready_state.reason_code is None
    # провайдер не настроен → готовность ложная с кодом
    import types as _types
    world.globals = {"flags.dream_enabled": True,
                     "models.llm_base_url": "",
                     "models.llm_model_name": ""}
    monkeypatch.setattr(feature_gates, "settings",
                        _types.SimpleNamespace(LLM_BASE_URL="",
                                               LLM_MODEL_NAME=""))
    not_ready = await feature_gates.gate_state(
        -100, "dream", root=_root({}), with_readiness=True)
    assert not_ready.ready is False
    assert not_ready.reason_code == "provider_missing:llm"
    # фичи без LLM-зависимости готовность не выдумывают
    plain = await feature_gates.gate_state(
        -100, "permsoc", root=_root({}), with_readiness=True)
    assert plain.ready is None


# ── Права зрителя: can_read / can_edit / authorized ────────────────────────

class _Ctx:
    def __init__(self, *, global_admin=False, role_chat=None, dm=False,
                 rank=1):
        self.is_global_admin = global_admin
        self.role_chat = role_chat
        self.is_local_admin = role_chat == "local_admin"
        self.is_dm_owner = dm
        self.rank = rank


def test_can_read_differs_from_can_edit_for_reader():
    """Может читать состояние, но не менять: can_read=True, can_edit=False
    (§2.2: это не `enabled=false`)."""
    moderator = _Ctx(role_chat="moderator", rank=2)
    can_read, can_edit = feature_gates.gate_authorization(
        moderator, "dream", -100)
    assert can_read is True and can_edit is False

    local = _Ctx(role_chat="local_admin", rank=3)
    assert feature_gates.gate_authorization(local, "dream", -100) == (
        True, True)                       # тяжёлые — можно (Q3)
    assert feature_gates.gate_authorization(local, "permsoc", -100) == (
        True, False)                      # permsoc — только global admin
    assert feature_gates.gate_authorization(
        _Ctx(global_admin=True, rank=4), "permsoc", -100) == (True, True)


@pytest.mark.asyncio
async def test_permission_denied_is_distinct_from_consent_required(world):
    """`permission_denied` (нет права читать) и `consent_required` (нет
    согласия) — разные коды, и ни один не подменяет emergency-ось."""
    world.globals = {"flags.dream_enabled": True}
    root = _root({})
    _set_chat({-100: root})

    denied = await feature_gates.gate_state(
        -100, "dream", root=root, ctx=_Ctx(rank=1))
    # ctx без гранта → can_read=False по правилам guard'а
    assert denied.can_read is False and denied.can_edit is False
    assert denied.reason_code == "permission_denied"
    assert denied.desired is True and denied.effective_runtime is True

    consent = await feature_gates.gate_state(
        -100, "dream", root=root, opt_in=False)
    assert consent.reason_code == "consent_required"
    assert consent.can_read is None          # права не оценивались

    blocked = await chat_params.resolve_gate_capability(
        -100, "dream", global_value=True, root=root, emergency_block=True)
    assert blocked.reason_code == "emergency_block"
    assert blocked.desired is True           # пользовательский выбор сохранён

    off = await chat_params.resolve_gate_capability(
        -100, "dream", global_value=False, root=root)
    assert off.reason_code == "capability_off"

    ok = await chat_params.resolve_gate_capability(
        -100, "dream", global_value=True, root=root, consent=True)
    assert ok.reason_code is None


@pytest.mark.asyncio
async def test_gates_opt_in_is_consent_not_veto(world):
    """§2.3/§2.4-8: `gates_opt_in=false` не выключает тяжёлые автоматически;
    согласие видно отдельной осью. Явный выбор чата сам является согласием
    (write-path `auto_opt_in` → `has_opt_in`), и код исчезает."""
    world.globals = {"flags.dream_enabled": True}
    _set_chat({-100: _root({})})
    no_consent = await feature_gates.gate_state(-100, "dream",
                                                root=_root({}), opt_in=False)
    assert no_consent.effective_runtime is True          # НЕ veto
    assert no_consent.consent is False
    assert no_consent.reason_code == "consent_required"

    consent = await feature_gates.gate_state(-100, "dream",
                                             root=_root({}), opt_in=True)
    assert consent.consent is True and consent.reason_code is None
    # у лёгких фич opt-in не участвует вовсе
    light = await feature_gates.gate_state(-100, "permsoc", root=_root({}),
                                           opt_in=False)
    assert light.consent is None
    assert light.reason_code == "capability_off"    # наследован глобальный OFF


@pytest.mark.asyncio
async def test_opt_in_legacy_does_not_disable_chat_gates(world):
    """§2.4-8 (новый чат): отсутствие согласия не превращает явные
    чатовые гейты в «всё выключено»."""
    world.globals = {"flags.dream_enabled": False,
                     "memory.nostalgia_enabled": False}
    root = _root(gates={"dream": True})
    _set_chat({-100: root})
    assert await feature_gates.gates_enabled(
        -100, "dream", root=root) is True
    # nostalgia по умолчанию (INHERIT) остаётся выключенной — но это
    # наследование, а не «opt-in запретил»
    assert await feature_gates.gates_enabled(
        -100, "nostalgia", root=root) is False


# ── Конфликт двух записей одной capability ─────────────────────────────────

@pytest.mark.asyncio
async def test_gate_conflict_is_named_not_silent(world):
    """§2.4-4: `gates.permsoc=OFF` и alias `overrides.flags.permsoc_enabled=ON`
    противоречат друг другу. Раньше alias молча игнорировался — теперь это
    видно кодом `gate_conflict:<alias>`, authoritative-путь не меняется."""
    world.globals = {"flags.permsoc_enabled": False}
    root = _root({"flags.permsoc_enabled": True}, {"permsoc": False})
    _set_chat({-100: root})
    state = await feature_gates.gate_state(-100, "permsoc", root=root)
    assert state.desired is False and state.chat_state == chat_params.OFF
    assert state.conflict == "flags.permsoc_enabled"
    assert state.reason_code == "gate_conflict:flags.permsoc_enabled"
    assert (await feature_gates.gates_enabled(-100, "permsoc",
                                              root=root)) is False
    # согласованные значения конфликтом не считаются
    agree = _root({"flags.permsoc_enabled": False}, {"permsoc": False})
    state2 = await feature_gates.gate_state(-100, "permsoc", root=agree)
    assert state2.conflict is None and state2.reason_code == "capability_off"


@pytest.mark.asyncio
async def test_declared_conflicts_are_reported(world):
    """Объявленный владельцем домена конфликт capability тоже даёт код."""
    state = await chat_params.resolve_gate_capability(
        -100, "dream", global_value=True, root=_root({}),
        conflict_with={"nostalgia": True})
    assert state.reason_code == "gate_conflict:nostalgia"
    assert state.conflict == "nostalgia"


# ── Живые поля состояния ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_carries_version_observed_at_and_pending_restart(world):
    """`version` = optimistic-метка профиля (§2.4-6), `observed_at` — момент
    снимка; `pending_restart` — проверенный факт (пустой список capability,
    которым нужен перезапуск)."""
    world.globals = {"flags.dream_enabled": True}
    _set_chat({-100: _root({})},
              version="2026-11-09T11:22:33+00:00")
    state = await feature_gates.gate_state(
        -100, "dream", root=_root({}), with_observation=True)
    assert state.version == "2026-11-09T11:22:33+00:00"
    assert state.observed_at and "T" in state.observed_at
    assert state.pending_restart is False
    assert state.last_activity_at is None      # источника нет → честный None
    assert chat_params.RESTART_REQUIRED_CAPABILITIES == frozenset()


@pytest.mark.asyncio
async def test_has_opt_in_reads_profile_column_not_empty_root(world):
    """Согласие чата живёт в колонке `chat_profiles.gates_opt_in`, которой НЕТ
    в `chat_params`-root. Раньше `has_opt_in(root=root)` всегда возвращал
    False → каждый тяжёлый гейт получал ложный `consent_required`."""
    class _Conn:
        def __init__(self, value):
            self.value = value
            self.queries = []

        async def fetchrow(self, sql, *args):
            self.queries.append(sql)
            return {"gates_opt_in": self.value}

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            conn = self.conn

            class _CM:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *exc):
                    return False

            return _CM()

    pg = types.SimpleNamespace(pool=_Pool(_Conn(True)))
    # root без колонки → честный запрос к профилю
    assert await feature_gates.has_opt_in(-100, pg,
                                          root={"overrides": {}}) is True
    # явное значение в root уважается (если владелец чтения его положил)
    assert await feature_gates.has_opt_in(
        -100, pg, root={"gates_opt_in": False}) is False


@pytest.mark.asyncio
async def test_activity_provider_fills_last_activity_and_fails_open(world):
    """Провайдер активности — единственный источник `last_activity_at`;
    ошибка провайдера не роняет резолв (None + WARNING)."""
    world.globals = {"memory.experience_learning_enabled": True}
    _set_chat({-100: _root({})})

    async def _provider(chat_id, capability, key):
        assert chat_id == -100
        return "2026-11-09T09:00:00+00:00"

    chat_params.set_activity_provider(_provider)
    state = await jobs.learning_state(-100)
    assert state.last_activity_at is None      # горячий путь не читает
    observed = await chat_params.resolve_param_capability(
        -100, jobs.LEARNING_KEY, capability="experience", with_observation=True)
    assert observed.last_activity_at == "2026-11-09T09:00:00+00:00"

    async def _boom(*_a, **_kw):
        raise RuntimeError("activity source down")

    chat_params.set_activity_provider(_boom)
    tolerant = await chat_params.resolve_param_capability(
        -100, jobs.LEARNING_KEY, capability="experience", with_observation=True)
    assert tolerant.last_activity_at is None
    assert tolerant.desired is True            # решение не пострадало


# ── Глобальная смена на лету (F) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_hot_change_reaches_running_process(world):
    """§2.4-6/§10-5: изменение глобального слоя видно следующему резолву без
    перезапуска (hot-config), чатовый выбор при этом не меняется."""
    key = "flags.initiative_enabled"
    world.globals = {key: False}
    _set_chat({-100: _root({}), -200: _root({key: True})})
    assert await chat_params.resolve_module_capability(-100, "initiative") \
        is not None
    inherit_before = await chat_params.resolve_module_capability(-100,
                                                                 "initiative")
    own_before = await chat_params.resolve_module_capability(-200, "initiative")
    assert inherit_before.effective_runtime is False
    assert own_before.effective_runtime is True

    world.globals = {key: True}                # hot-правка «на лету»
    inherit_after = await chat_params.resolve_module_capability(-100,
                                                                "initiative")
    own_after = await chat_params.resolve_module_capability(-200, "initiative")
    assert inherit_after.effective_runtime is True
    assert inherit_after.source == "global"
    assert own_after.effective_runtime is True and own_after.source == "chat"
