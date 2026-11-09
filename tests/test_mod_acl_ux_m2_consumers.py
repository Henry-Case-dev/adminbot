"""MOD-ACL-UX-01 M2 — инвентарь потребителей gated capability (ТЗ §2.4-1/§2.4-2).

Проверяется два утверждения:

1. **Поведенчески:** каждый публичный потребитель решения (воркеры памяти,
   experience-job, PERMsoc, API гейтов) при `GLOBAL OFF + явный CHAT ON`
   возвращает ON — то есть проходит через ЕДИНЫЙ резолвер, а не решает сам;
2. **Структурно:** в коде нет второго решателя — прежние «глобальный флаг как
   жёсткое вето» удалены, а чтение `chat_params["overrides"]`/приоритет
   живут только в `services/chat_params.py` (прочие чтения — документированные
   диагностические, не decision-path).
"""
import ast
import copy
import pathlib

import pytest

from services import chat_params, feature_gates, hot_config, module_registry
from services import mca_experience_jobs as jobs
from services import permsoc

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Cache:
    def __init__(self, by_chat=None):
        self.by_chat = copy.deepcopy(by_chat or {})
        self.invalidated: list[int] = []

    async def get_chat_params(self, chat_id):
        data = self.by_chat.get(int(chat_id), {})
        return {"overrides": dict(data.get("overrides") or {}),
                "gates": dict(data.get("gates") or {})}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None

    async def get_chat_params_checked(self, chat_id):
        return await self.get_chat_params(chat_id), True

    async def invalidate_chat(self, chat_id):
        self.invalidated.append(int(chat_id))


@pytest.fixture
def world(monkeypatch):
    class World:
        def __init__(self):
            self.globals = {}
            self.calls: list[tuple[str, str]] = []

    w = World()
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: w.globals.get(key, default))
    monkeypatch.setattr(module_registry, "env_enabled", lambda mid: True)
    real = chat_params.resolve_capability

    def _recording(**kwargs):
        w.calls.append((kwargs.get("capability") or kwargs.get("key"),
                        kwargs.get("domain")))
        return real(**kwargs)

    monkeypatch.setattr(chat_params, "resolve_capability", _recording)
    chat_params.set_chat_params_cache(None)
    yield w
    chat_params.set_chat_params_cache(None)


def _chat_on(keys=()):
    chat_params.set_chat_params_cache(_Cache({
        -100: {"overrides": {k: True for k in keys},
               "gates": {"dream": True, "permsoc": True}}}))
    chat_params.set_chat_params_cache(
        chat_params.get_chat_params_cache())


@pytest.mark.asyncio
async def test_every_consumer_reaches_single_resolver(world):
    """Все потребители отдают ON при GLOBAL OFF + явном CHAT ON, и каждый
    вызов проходит через `chat_params.resolve_capability` (записано в
    `world.calls`)."""
    world.globals = {"flags.dream_enabled": False,
                     "flags.permsoc_enabled": False,
                     "memory.experience_learning_enabled": False,
                     "flags.initiative_enabled": False}
    _chat_on(keys=("memory.experience_learning_enabled",
                   "flags.initiative_enabled"))

    assert await feature_gates.gates_enabled(-100, "dream") is True
    assert await permsoc.master_enabled(-100) is True
    assert await jobs.learning_enabled_for_chat(-100) is True

    state = await chat_params.resolve_module_capability(-100, "initiative")
    assert state is not None and state.effective_runtime is True

    capabilities = {name for name, _domain in world.calls}
    assert {"dream", "permsoc", "experience", "initiative"} <= capabilities


@pytest.mark.asyncio
async def test_consumer_state_exposes_tri_state(world):
    """API/статус-потребители получают полное состояние (три-состояние +
    раздельные оси), а не только bool."""
    world.globals = {"flags.dream_enabled": False}
    _chat_on()
    state = await feature_gates.gate_state(-100, "dream")
    snapshot = state.as_dict()
    assert snapshot["chat_state"] == "on"
    assert snapshot["desired"] is True and snapshot["source"] == "chat"
    assert snapshot["global_value"] is False
    for field in ("ready", "authorized", "observed", "reason_code",
                  "pending_restart", "version", "can_read", "can_edit"):
        assert field in snapshot


# ── структурные проверки: второго решателя нет ─────────────────────────────

def _function_source(rel_path: str, func_name: str) -> str:
    text = (ROOT / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{rel_path}: функция {func_name} не найдена")


def test_lore_worker_has_no_own_global_veto():
    """`lore_worker` больше не решает сам: глобальный флаг не встречается в
    функции генерации (он был вторым, более сильным решателем)."""
    src = _function_source("services/lore_worker.py", "_generate_for_chat_impl")
    assert 'hot.get("flags.lore_auto_enabled"' not in src
    assert "gates_enabled(" in src


def test_nostalgia_worker_has_no_own_global_veto():
    """Тик и чатовая обработка «Ностальгии» не выключаются глобальным флагом
    самостоятельно (`if not self._flag("enabled")` удалён) — только
    канонический `gates_enabled`."""
    tick = _function_source("services/nostalgia_worker.py", "_run_tick")
    assert '_flag("enabled", settings.NOSTALGIA_ENABLED)' not in tick
    chat = _function_source("services/nostalgia_worker.py", "_process_chat")
    assert '_flag("enabled", settings.NOSTALGIA_ENABLED)' not in chat
    assert 'gates_enabled(chat_id, "nostalgia")' in chat


def test_dream_worker_delegates_to_feature_gates():
    src = (ROOT / "services/dream_worker.py").read_text(encoding="utf-8")
    assert 'gates_enabled(chat_id, "dream"' in src


def test_overrides_priority_is_implemented_once():
    """Приоритет «чат → глобал» реализован только в chat_params: остальные
    модули-потребители не читают `overrides` напрямую (единственное
    исключение — диагностический `worker_settings.setting_source`, который
    документирован как НЕ decision-path)."""
    consumers = [
        "services/feature_gates.py",
        "services/permsoc.py",
        "services/mca_experience_jobs.py",
        "web/api/gates.py",
    ]
    for rel in consumers:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert '.get("overrides")' not in src, rel
        assert '["overrides"]' not in src, rel

    # диагностический путь — явно разрешён и помечен в docstring
    diag = (ROOT / "services/worker_settings.py").read_text(encoding="utf-8")
    assert "НЕ decision-path" in diag
    assert "cp.read_override" in diag and "cp.read_global" in diag


def test_gates_api_and_config_use_canonical_state():
    """API-поверхности берут состояние из резолвера, а не собирают своё."""
    gates_api = (ROOT / "web/api/gates.py").read_text(encoding="utf-8")
    assert "feature_gates.gate_state(" in gates_api
    assert '"states"' in gates_api
    routes = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
    assert "resolve_module_capability(" in routes
    registry = (ROOT / "services/module_registry.py").read_text(
        encoding="utf-8")
    assert "def gate_snapshot(module_id: str, state" in registry


def test_no_second_resolver_module():
    """Канонический резолвер один: функции разрешения определены только в
    `services/chat_params.py` (второй копии `resolve_capability` нет)."""
    offenders = []
    for path in list((ROOT / "services").glob("*.py")) + \
            list((ROOT / "web").rglob("*.py")):
        if path.name == "chat_params.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "def resolve_capability(" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


# ── API-витрина: «выбор чата» не подменяется «готовностью» ──────────────────

@pytest.mark.asyncio
async def test_gates_api_keeps_choice_when_not_ready(world, monkeypatch):
    """GET /api/chat/{id}/gates: тумблер = выбор чата (как у воркера), а
    готовность — отдельная ось. Если LLM-провайдер не настроен, настройка ON
    не должна выглядеть ВЫКЛЮЧЕННОЙ (иначе это «тихий OFF» в UI, §2.2), но
    `states[].ready=False` и конкретный код причины обязаны быть."""
    import types

    from services import roles as roles_srv
    from web.api import gates as gates_api

    world.globals = {"flags.dream_enabled": True,
                     "models.llm_base_url": "",
                     "models.llm_model_name": ""}
    monkeypatch.setattr(feature_gates, "settings",
                        types.SimpleNamespace(LLM_BASE_URL="",
                                              LLM_MODEL_NAME=""))
    _chat_on()

    async def _no_fallback(chat_id, feature):
        return None

    async def _opt_in(chat_id, pg=None, root=None):
        return True

    async def _access_for(*_a, **_kw):
        return types.SimpleNamespace(
            is_global_admin=True, role_chat=None, is_local_admin=False,
            is_dm_owner=False, rank=4)

    monkeypatch.setattr(feature_gates, "master_fallback", _no_fallback)
    monkeypatch.setattr(feature_gates, "has_opt_in", _opt_in)
    monkeypatch.setattr(roles_srv, "access_for", _access_for)

    cache = types.SimpleNamespace(pg=None, pg_available=True)
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(cache=cache)))
    user = types.SimpleNamespace(id=777)

    out = await gates_api.gates_get(-100, request, user)
    assert out["gates"]["dream"] is True            # выбор чата сохранён
    state = out["states"]["dream"]
    assert state["ready"] is False                  # готовность — своя ось
    assert state["reason_code"] == "provider_missing:llm"
    assert state["desired"] is True and state["chat_state"] == "on"
    assert state["can_read"] is True and state["can_edit"] is True
