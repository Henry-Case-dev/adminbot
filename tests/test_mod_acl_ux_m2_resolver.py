"""MOD-ACL-UX-01 M2 — канонический резолвер GLOBAL-дефолт → CHAT-override.

Контракт (ТЗ §2.1/§2.2/§2.3.1):
* GLOBAL — наследуемый дефолт, НЕ запрет: GLOBAL OFF + явный чат ON → ON;
* настройка чата три-состояние INHERIT/ON/OFF; отсутствие записи ≠ `false`;
* один резолвер (`services.chat_params`) для всех gated capability;
* сохранённые значения не переписываются, emergency env-ось — отдельно.

Тесты проверяют ФАКТИЧЕСКОЕ состояние (desired/effective/source), а не факт
вызова функций.
"""
import copy
import json

import pytest

from services import chat_params, feature_gates, mca_gates, module_registry
from services import hot_config
from services import mca_experience_jobs as jobs
from scripts import mod_acl_effective_state_report as report_mod


class _Cache:
    """chat_params-кэш чата: root-лейаут без side effects."""

    def __init__(self, by_chat=None):
        self.by_chat = copy.deepcopy(by_chat or {})
        self.invalidated: list[int] = []

    async def get_chat_params(self, chat_id):
        data = self.by_chat.get(int(chat_id), {})
        return {"overrides": dict(data.get("overrides") or {}),
                "gates": dict(data.get("gates") or {})}

    async def get_chat_params_checked(self, chat_id):
        return await self.get_chat_params(chat_id), True

    async def invalidate_chat(self, chat_id):
        self.invalidated.append(int(chat_id))


@pytest.fixture
def world(monkeypatch):
    """Изолированный мир: hot-глобалы, env-оси, chat_params-кэш."""
    class World:
        def __init__(self):
            self.globals: dict = {}
            self.env: dict = {}

    w = World()
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: w.globals.get(key, default))
    monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                        lambda: w.env.get("MCA_EXPERIENCE_LESSONS_ENABLED",
                                          True))
    monkeypatch.setattr(mca_gates, "experience_review_enabled", lambda: True)
    monkeypatch.setattr(module_registry, "env_enabled",
                        lambda module_id: w.env.get(f"env:{module_id}", True))
    yield w
    chat_params.set_chat_params_cache(None)


def _set_chat(world, by_chat):
    cache = _Cache(by_chat)
    chat_params.set_chat_params_cache(cache)
    return cache


def _root(overrides=None, gates=None):
    return {"overrides": dict(overrides or {}), "gates": dict(gates or {})}


# INHERIT/ON/OFF × GLOBAL ON/OFF — ровно таблица §2.1 (6 строк).
# (global, chat, expected): chat None ⇒ записи нет (INHERIT).
TRUTH_TABLE = [
    (True, None, True),
    (True, True, True),
    (True, False, False),
    (False, None, False),
    (False, True, True),     # строка 5 — сломанная до M2 для per-chat
    (False, False, False),
]


@pytest.mark.asyncio
async def test_six_case_table_global_module(world):
    """Все шесть строк таблицы для глобального модуля (initiative)."""
    key = "flags.initiative_enabled"
    for global_on, chat, expected in TRUTH_TABLE:
        world.globals = {key: global_on}
        _set_chat(world, {-100: _root({} if chat is None else {key: chat})})
        state = await chat_params.resolve_module_capability(-100, "initiative")
        assert state is not None
        assert state.desired is expected, (global_on, chat)
        assert state.effective_runtime is expected, (global_on, chat)
        assert state.chat_state == ("inherit" if chat is None else
                                    ("on" if chat else "off"))
        assert state.source == ("global" if chat is None else "chat")
        # раздельные оси не схлопнуты: readiness/authz/observed — None,
        # emergency — False; отдельного bool «всё вместе» нет.
        assert state.ready is None and state.authorized is None
        assert state.observed is None and state.emergency_block is False


@pytest.mark.asyncio
async def test_six_case_table_per_chat_experience(world):
    """Все шесть строк для per_chat-модуля «Опыт и уроки» + worker-гейт."""
    key = "memory.experience_learning_enabled"
    for global_on, chat, expected in TRUTH_TABLE:
        world.globals = {key: global_on}
        _set_chat(world, {-100: _root({} if chat is None else {key: chat})})
        state = await jobs.learning_state(-100)
        assert state.desired is expected, (global_on, chat)
        assert state.effective_runtime is expected, (global_on, chat)
        assert await jobs.learning_enabled_for_chat(-100) is expected
        assert state.chat_state == ("inherit" if chat is None else
                                    ("on" if chat else "off"))


@pytest.mark.asyncio
async def test_absent_is_inherit_explicit_false_is_off(world):
    """Отсутствие ключа (INHERIT) и явный `false` (OFF) различимы и дают
    разный effective при глобальном ON."""
    key = "flags.initiative_enabled"
    world.globals = {key: True}
    _set_chat(world, {-100: _root({}), -200: _root({key: False})})
    absent = await chat_params.resolve_module_capability(-100, "initiative")
    explicit = await chat_params.resolve_module_capability(-200, "initiative")
    assert (absent.chat_state, explicit.chat_state) == (
        chat_params.INHERIT, chat_params.OFF)
    assert absent.desired is True and absent.effective_runtime is True
    assert explicit.desired is False and explicit.effective_runtime is False
    assert (absent.source, explicit.source) == ("global", "chat")


@pytest.mark.asyncio
async def test_global_off_chat_on_worker_runs_and_selects(world):
    """GLOBAL OFF + Chat ON: worker не выключен глобалью и берёт только
    eligible-чаты (INHERIT наследует OFF)."""
    key = "memory.experience_learning_enabled"
    world.globals = {key: False}
    _set_chat(world, {
        -100: _root({key: True}),        # явный ON
        -200: _root({}),                 # INHERIT → OFF
    })
    assert jobs.review_enabled() is True                     # job тикает
    assert await jobs.learning_enabled_for_chat(-100) is True
    assert await jobs.learning_enabled_for_chat(-200) is False


@pytest.mark.asyncio
async def test_stored_explicit_false_is_never_rewritten(world, monkeypatch):
    """Резолвер и read-пути не пишут: сохранённые `false` остаются `false`."""
    world.globals = {"memory.experience_learning_enabled": True}
    stored = {
        -100: _root(
            {"memory.experience_learning_enabled": False,
             "flags.initiative_enabled": False},
            {"dream": False, "permsoc": False}),
        -200: _root({}),
    }
    cache = _set_chat(world, stored)
    snapshot = copy.deepcopy(cache.by_chat)

    async def _forbidden(*args, **kwargs):      # pragma: no cover - guard
        raise AssertionError("резолвер не имеет права писать настройки")

    monkeypatch.setattr(chat_params, "set_chat_params", _forbidden)

    await jobs.learning_enabled_for_chat(-100)
    await chat_params.resolve_module_capability(-100, "initiative")
    await feature_gates.gates_enabled(-100, "dream",
                                      root=_root(gates={"dream": False}))
    await feature_gates.gates_enabled(-200, "permsoc", root=_root({}))
    assert cache.by_chat == snapshot
    assert cache.invalidated == []
    assert stored[-100]["overrides"]["memory.experience_learning_enabled"] \
        is False


@pytest.mark.asyncio
async def test_env_kill_switch_overrides_table(world):
    """Аварийный env-гейт перекрывает и GLOBAL ON, и явный чат ON; желание
    пользователя при этом не подменяется (`desired` остаётся True)."""
    exp_key = "memory.experience_learning_enabled"
    world.globals = {exp_key: True, "flags.initiative_enabled": True}
    world.env = {"MCA_EXPERIENCE_LESSONS_ENABLED": False,
                 "env:initiative": False}
    _set_chat(world, {-100: _root({exp_key: True,
                                   "flags.initiative_enabled": True})})
    exp = await jobs.learning_state(-100)
    assert exp.desired is True and exp.emergency_block is True
    assert exp.effective_runtime is False
    assert await jobs.learning_enabled_for_chat(-100) is False

    init = await chat_params.resolve_module_capability(-100, "initiative")
    assert init.desired is True and init.emergency_block is True
    assert init.effective_runtime is False


@pytest.mark.asyncio
async def test_gate_domain_rows_and_permsoc_alias(world):
    """Домен gates идёт через тот же резолвер; read-compat alias permsoc
    (overrides["flags.permsoc_enabled"]) действует только при INHERIT."""
    world.globals = {"flags.permsoc_enabled": False}
    cases = [
        (None, None, False),      # INHERIT → глобальный OFF
        (True, None, True),       # чат-гейт ON при глобальном OFF
        (False, None, False),
        (None, True, True),       # alias-чата ON
        (None, False, False),     # alias-чата OFF
        (False, True, False),     # явный гейт важнее alias
    ]
    for gate, alias, expected in cases:
        gates = {} if gate is None else {"permsoc": gate}
        overrides = {} if alias is None else {"flags.permsoc_enabled": alias}
        root = _root(overrides, gates)
        _set_chat(world, {-100: root})
        effective = await feature_gates.gates_enabled(-100, "permsoc",
                                                      root=root)
        assert effective is expected, (gate, alias)
        # второй потребитель того же capability согласован с первым
        from services import permsoc
        assert await permsoc.master_enabled(-100) is expected


@pytest.mark.asyncio
async def test_one_resolver_no_second_gateway(world):
    """Одна семантика для модульного и гейтового домена: одинаковый вход →
    одинаковый desired (независимые копии приоритета удалены)."""
    world.globals = {}
    _set_chat(world, {-100: _root({"flags.initiative_enabled": True},
                                  {"dream": True})})
    module_state = await chat_params.resolve_module_capability(-100,
                                                               "initiative")
    gate_state = await chat_params.resolve_gate_capability(
        -100, "dream", root=_root(gates={"dream": True}),
        global_value=False)
    assert module_state.desired is True and gate_state.desired is True
    assert module_state.chat_state == gate_state.chat_state == chat_params.ON
    assert module_state.source == gate_state.source == "chat"


def test_state_snapshot_exposes_separate_axes():
    """Снимок для API/UI: три состояния + раздельные оси отдельными полями,
    без схлопывания в один bool (§2.2)."""
    state = chat_params.resolve_capability(
        capability="experience", key="memory.experience_learning_enabled",
        domain=chat_params.DOMAIN_OVERRIDE, chat_id=-100, root=_root({}),
        global_value=True, ready=False, authorized=True, observed=None)
    snapshot = state.as_dict()
    assert snapshot["chat_state"] == chat_params.INHERIT
    assert snapshot["desired"] is True          # наследует глобальный ON
    assert snapshot["source"] == "global"
    assert snapshot["effective_runtime"] is False   # ready=False блокирует
    assert snapshot["ready"] is False           # готовность — своя ось
    assert snapshot["authorized"] is True       # права — своя ось
    assert snapshot["observed"] is None         # наблюдение — своя ось
    assert set(snapshot) == {
        "capability", "key", "domain", "chat_id", "chat_state", "desired",
        "source", "global_value", "global_source", "emergency_block",
        "effective_runtime", "ready", "authorized", "observed"}


# ── before/after impact report ──────────────────────────────────────────────

FIXTURE = {
    "globals": {
        "flags.initiative_enabled": False,
        "memory.experience_learning_enabled": False,
        "flags.dream_enabled": False,        # старый тихий veto
        "memory.dream_enabled": True,
    },
    "env": {"MCA_EXPERIENCE_LESSONS_ENABLED": True},
    "chats": [
        {"chat_id": -100, "overrides": {
            "memory.experience_learning_enabled": True}},
        {"chat_id": -200, "gates": {"dream": False}},
        {"chat_id": -300},
        {"chat_id": -400, "gates": {"dream": True}},
    ],
}


def test_impact_report_is_deterministic_on_fixture(tmp_path):
    """Отчёт детерминирован и перечисляет изменённые чаты ПОШТУЧНО."""
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")
    globals_map, chats, env_map = report_mod.load_fixture(str(path))

    first = report_mod.build_report(globals_map, chats, env_map)
    second = report_mod.build_report(globals_map, chats, env_map)
    assert first == second

    pairs = {(i["chat_id"], i["capability"]) for i in first["changed"]}
    assert pairs == {
        (-100, "module:experience"),   # GLOBAL OFF + чат ON → теперь ON
        (-100, "gate:dream"),          # старый flags-veto снят
        (-300, "gate:dream"),          # то же для INHERIT-чата
    }
    assert first["changed_pairs"] == 3
    assert first["changed_chats"] == [-300, -100]
    # направление изменения — только OFF → ON (ничего не выключилось)
    assert all(item["new"] and not item["old"] for item in first["changed"])

    md_first = report_mod.render_markdown(first, source_label="fixture")
    md_second = report_mod.render_markdown(second, source_label="fixture")
    assert md_first == md_second
    # каждый чат с изменением назван отдельно, без процентов
    assert "- -300: " in md_first or "- -300:" in md_first
    assert "- -100:" in md_first
    assert "%" not in md_first
