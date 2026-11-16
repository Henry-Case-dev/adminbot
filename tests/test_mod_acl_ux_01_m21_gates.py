"""MOD-ACL-UX-01 M2.1 — гейты, precedence и отсутствие второго решателя.

Проверяется:
* `nostalgia`: `memory.nostalgia_enabled` — master; legacy
  `flags.nostalgia_enabled` не перекрывает его (design §12.3);
* `initiative`: GLOBAL-дефолт `flags.initiative_enabled` — наследуемое
  значение (не запрет); явный CHAT ON исполняется при GLOBAL OFF; env
  `MCA_INTENTS_ENABLED` остаётся отдельной аварийной осью;
* `character`/`random`: shared-модель/пул остаются живыми, чат решает
  использование через тот же резолвер (GLOBAL default → CHAT override);
* второго resolver/ACL/registry нет: адаптеры вызывают существующий
  `chat_params.resolve_capability`;
* адаптеры только читают: stored values и кэш не переписываются.
"""
import copy
import pathlib
import types

import pytest

from services import chat_params, feature_gates, hot_config, mca_gates
from services import module_registry
from services import initiative_observer

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHAT = -100


class _Cache:
    def __init__(self, by_chat=None):
        self.by_chat = copy.deepcopy(by_chat or {})
        self.invalidated: list[int] = []

    @staticmethod
    def _root(data):
        return {"overrides": dict((data or {}).get("overrides") or {}),
                "gates": dict((data or {}).get("gates") or {})}

    async def get_chat_params(self, chat_id):
        return self._root(self.by_chat.get(int(chat_id)))

    async def get_chat_params_full(self, chat_id):
        return self._root(self.by_chat.get(int(chat_id))), None

    async def get_chat_params_checked(self, chat_id):
        return self._root(self.by_chat.get(int(chat_id))), True

    async def get_chat_params_fresh(self, chat_id):
        return self._root(self.by_chat.get(int(chat_id))), None, True

    async def invalidate_chat(self, chat_id):
        self.invalidated.append(int(chat_id))


@pytest.fixture
def world(monkeypatch):
    class World:
        globals: dict = {}

    w = World()
    w.globals = {}
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: w.globals.get(key, default))
    monkeypatch.setattr(module_registry, "env_enabled", lambda mid: True)
    chat_params.set_chat_params_cache(None)
    yield w
    chat_params.set_chat_params_cache(None)


def _set_chat(world, root):
    world.cache = _Cache({CHAT: root})
    chat_params.set_chat_params_cache(world.cache)
    return world.cache


# ═══ nostalgia precedence ═════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_nostalgia_memory_master_beats_legacy_flags(world):
    """flags.nostalgia_enabled=True не перекрывает master=False."""
    world.globals = {"flags.nostalgia_enabled": True,
                     "memory.nostalgia_enabled": False}
    _set_chat(world, {"overrides": {}, "gates": {}})
    state = await feature_gates.gate_state(CHAT, "nostalgia")
    assert state is not None
    assert state.global_value is False
    assert state.desired is False
    assert state.effective_runtime is False
    assert state.source == "global"

    # И наоборот: legacy OFF не мешает master ON.
    world.globals = {"flags.nostalgia_enabled": False,
                     "memory.nostalgia_enabled": True}
    state = await feature_gates.gate_state(CHAT, "nostalgia")
    assert state.global_value is True
    assert state.effective_runtime is True


@pytest.mark.asyncio
async def test_nostalgia_chat_override_wins_over_both_global_keys(world):
    """GLOBAL OFF + явный chat ON → ON (каноническая семантика §2.1)."""
    world.globals = {"flags.nostalgia_enabled": False,
                     "memory.nostalgia_enabled": False}
    _set_chat(world, {"overrides": {}, "gates": {"nostalgia": True}})
    state = await feature_gates.gate_state(CHAT, "nostalgia")
    assert state.desired is True
    assert state.source == "chat"
    assert state.effective_runtime is True


@pytest.mark.asyncio
async def test_nostalgia_master_fallback_uses_memory_key(world, monkeypatch):
    """`master_fallback` резолвит memory.nostalgia_enabled, не flags.*."""
    seen = []

    async def _resolve(key, chat_id=None, default=None):
        seen.append(key)
        return False

    from services import worker_settings
    monkeypatch.setattr(worker_settings, "resolve_setting_cached", _resolve)
    assert feature_gates.MASTER_FALLBACK_KEYS["nostalgia"] == \
        "memory.nostalgia_enabled"
    assert await feature_gates.master_fallback(CHAT, "nostalgia") is False
    assert seen == ["memory.nostalgia_enabled"]


# ═══ initiative: GLOBAL default, CHAT override, emergency env ═════════════

@pytest.mark.asyncio
async def test_initiative_global_off_chat_on_is_on(world, monkeypatch):
    """GLOBAL OFF + явный CHAT ON → инициатива исполняется в этом чате.

    `flags.initiative_enabled` — наследуемый дефолт, не запрет. Отдельный
    глобальный `flags.initiative_observer_enabled` (гейт тика) остаётся ON;
    env-аварийная ось не активна.
    """
    monkeypatch.setattr(mca_gates, "intents_env_enabled", lambda: True)
    world.globals = {"flags.initiative_enabled": False,
                     "flags.initiative_observer_enabled": True,
                     "initiative.enabled": True}
    _set_chat(world, {"overrides": {"initiative.enabled": True},
                      "gates": {}})
    assert initiative_observer.observer_enabled() is True
    assert await initiative_observer.chat_observer_enabled(CHAT) is True
    assert await initiative_observer.initiative_publish_block_reason(
        CHAT) is None


@pytest.mark.asyncio
async def test_initiative_global_default_is_master_not_legacy_global(world,
                                                                     monkeypatch):
    """Глобальный `initiative.enabled` не перекрывает master-дефолт.

    Если `flags.initiative_enabled=False`, а исторический глобальный
    `initiative.enabled=True` сохранён, INHERIT-чат обязан наследовать OFF:
    authoritative global — master карточки, не read-compat ключ.
    """
    monkeypatch.setattr(mca_gates, "intents_env_enabled", lambda: True)
    world.globals = {"flags.initiative_enabled": False,
                     "initiative.enabled": True}
    _set_chat(world, {"overrides": {}, "gates": {}})
    assert await initiative_observer.chat_observer_enabled(CHAT) is False
    assert await initiative_observer.initiative_publish_block_reason(
        CHAT) == "capability_off"


@pytest.mark.asyncio
async def test_initiative_global_on_chat_off_is_off(world, monkeypatch):
    """GLOBAL ON + явный CHAT OFF → OFF только для этого чата."""
    monkeypatch.setattr(mca_gates, "intents_env_enabled", lambda: True)
    world.globals = {"flags.initiative_enabled": True,
                     "initiative.enabled": True}
    _set_chat(world, {"overrides": {"initiative.enabled": False},
                      "gates": {}})
    assert await initiative_observer.chat_observer_enabled(CHAT) is False
    assert await initiative_observer.initiative_publish_block_reason(
        CHAT) == "capability_off"


@pytest.mark.asyncio
async def test_initiative_emergency_env_overrides_chat(world, monkeypatch):
    """Аварийная env-ось (K1) — отдельная ось, важнее chat; желание не
    подменяется (`desired=True`, `emergency_block=True`)."""
    monkeypatch.setattr(mca_gates, "settings",
                        types.SimpleNamespace(MCA_INTENTS_ENABLED=False))
    world.globals = {"flags.initiative_enabled": True,
                     "flags.initiative_observer_enabled": True,
                     "initiative.enabled": True}
    _set_chat(world, {"overrides": {"initiative.enabled": True},
                      "gates": {}})
    state = await initiative_observer.chat_capability_state(CHAT, fresh=True)
    assert state is not None
    assert state.desired is True           # выбор пользователя не подменён
    assert state.emergency_block is True
    assert state.effective_runtime is False
    assert await initiative_observer.initiative_publish_block_reason(
        CHAT) == "capability_off"


@pytest.mark.asyncio
async def test_initiative_scheduler_ticks_when_chat_is_on(world, monkeypatch):
    """GLOBAL OFF + CHAT ON: тик не ранний `disabled`, а выбирает чат."""
    monkeypatch.setattr(mca_gates, "intents_env_enabled", lambda: True)
    world.globals = {"flags.initiative_enabled": False,
                     "flags.initiative_observer_enabled": True,
                     "initiative.enabled": True}
    _set_chat(world, {"overrides": {"initiative.enabled": True},
                      "gates": {}})
    seen = []

    async def _due(db, *, now=None):
        seen.append("due")
        return [CHAT]

    async def _active(db):
        return {"status": initiative_observer.JOB_RUNNING, "job_id": "job"}

    monkeypatch.setattr(initiative_observer, "_due_chats", _due)
    monkeypatch.setattr(initiative_observer, "get_active_observe", _active)
    assert await initiative_observer.observe_tick(object()) == "running"
    assert seen == ["due"]


# ═══ character / random: shared resource alive, chat decides usage ════════

@pytest.mark.asyncio
async def test_character_chat_off_does_not_stop_global_model(world,
                                                             monkeypatch):
    monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: True)
    world.globals = {"flags.self_model_enabled": True}
    _set_chat(world, {"overrides": {"flags.self_model_enabled": False},
                      "gates": {}})
    assert await mca_gates.self_model_enabled_for_chat(CHAT) is False
    # Глобальная модель/снапшот не «выключены» — меняется только использование.
    assert mca_gates.self_model_enabled() is True


@pytest.mark.asyncio
async def test_random_chat_off_keeps_global_pool(world, monkeypatch):
    monkeypatch.setattr(mca_gates, "random_source_enabled", lambda: True)
    world.globals = {"memory.random_enabled": True}
    _set_chat(world, {"overrides": {"memory.random_enabled": False},
                      "gates": {}})
    assert await mca_gates.random_source_enabled_for_chat(CHAT) is False
    assert mca_gates.random_source_enabled() is True


@pytest.mark.asyncio
async def test_random_global_off_chat_on_is_on(world, monkeypatch):
    """GLOBAL OFF + CHAT ON: пул жив, использование включено в чате."""
    monkeypatch.setattr(module_registry, "env_enabled", lambda mid: True)
    world.globals = {"memory.random_enabled": False}
    _set_chat(world, {"overrides": {"memory.random_enabled": True},
                      "gates": {}})
    assert await mca_gates.random_source_enabled_for_chat(CHAT) is True

    # GLOBAL ON + CHAT OFF → OFF только в этом чате, пул не трогаем.
    world.globals = {"memory.random_enabled": True}
    _set_chat(world, {"overrides": {"memory.random_enabled": False},
                      "gates": {}})
    assert await mca_gates.random_source_enabled_for_chat(CHAT) is False
    assert mca_gates.random_source_enabled() is True


@pytest.mark.asyncio
async def test_random_emergency_env_blocks_chat_on(world, monkeypatch):
    monkeypatch.setattr(
        module_registry, "env_enabled",
        lambda mid: False if mid == "random" else True)
    world.globals = {"memory.random_enabled": True}
    _set_chat(world, {"overrides": {"memory.random_enabled": True},
                      "gates": {}})
    assert await mca_gates.random_source_enabled_for_chat(CHAT) is False


@pytest.mark.asyncio
async def test_character_global_off_chat_on_is_on(world, monkeypatch):
    """GLOBAL OFF + CHAT ON: характер используется в этом чате."""
    monkeypatch.setattr(module_registry, "env_enabled", lambda mid: True)
    world.globals = {"flags.self_model_enabled": False}
    _set_chat(world, {"overrides": {"flags.self_model_enabled": True},
                      "gates": {}})
    assert await mca_gates.self_model_enabled_for_chat(CHAT) is True

    world.globals = {"flags.self_model_enabled": True}
    _set_chat(world, {"overrides": {"flags.self_model_enabled": False},
                      "gates": {}})
    assert await mca_gates.self_model_enabled_for_chat(CHAT) is False


@pytest.mark.asyncio
async def test_character_emergency_env_blocks_chat_on(world, monkeypatch):
    monkeypatch.setattr(
        module_registry, "env_enabled",
        lambda mid: False if mid == "character" else True)
    world.globals = {"flags.self_model_enabled": True}
    _set_chat(world, {"overrides": {"flags.self_model_enabled": True},
                      "gates": {}})
    assert await mca_gates.self_model_enabled_for_chat(CHAT) is False


@pytest.mark.asyncio
async def test_stories_global_off_chat_on_and_emergency(world, monkeypatch):
    """Stories read-контур: GLOBAL OFF + CHAT ON = ON; env K1 — emergency."""
    monkeypatch.setattr(module_registry, "env_enabled", lambda mid: True)
    world.globals = {"flags.stories_vitrina_enabled": False}
    _set_chat(world, {"overrides": {"flags.stories_vitrina_enabled": True},
                      "gates": {}})
    assert await mca_gates.stories_vitrina_enabled_for_chat(CHAT) is True

    world.globals = {"flags.stories_vitrina_enabled": True}
    _set_chat(world, {"overrides": {"flags.stories_vitrina_enabled": False},
                      "gates": {}})
    assert await mca_gates.stories_vitrina_enabled_for_chat(CHAT) is False

    monkeypatch.setattr(
        module_registry, "env_enabled",
        lambda mid: False if mid == "stories" else True)
    _set_chat(world, {"overrides": {"flags.stories_vitrina_enabled": True},
                      "gates": {}})
    assert await mca_gates.stories_vitrina_enabled_for_chat(CHAT) is False


# ═══ fail-closed adapter (F9): решение зафиксировано явно ═════════════════

@pytest.mark.asyncio
async def test_module_enabled_fail_closed_on_resolver_error(world, monkeypatch):
    """Ошибка резолвера не выдаёт разрешение: явный fail-closed."""
    import services.chat_params as cp

    async def _boom(*args, **kwargs):
        raise RuntimeError("resolver down")

    monkeypatch.setattr(cp, "resolve_module_capability", _boom)
    assert await feature_gates.module_enabled(CHAT, module_id="random") is False


# ═══ один резолвер, без второго ACL/registry ══════════════════════════════

def test_no_second_resolver_or_acl():
    offenders = []
    for path in list((ROOT / "services").glob("*.py")) + \
            list((ROOT / "web").rglob("*.py")):
        if path.name == "chat_params.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in ("def resolve_capability(",
                       "def resolve_param_capability(",
                       "def resolve_module_capability(",
                       "class CapabilityState("):
            if marker in text:
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_m21_consumers_use_existing_resolver():
    """12 потребителей не читают глобальный слой как решение о модуле."""
    expected = {
        "services/initiative_observer.py": "resolve_param_capability",
        "services/direct_chat_service.py": "module_enabled(",
        "services/media_download.py": "module_enabled(",
        "services/tool_router.py": "module_enabled(",
        "services/mca_gates.py": "module_enabled(",
        "handlers/direct_chat.py": "module_enabled(",
        "handlers/factcheck.py": "module_enabled(",
        "handlers/search.py": "module_enabled(",
        "handlers/web.py": "module_enabled(",
        "handlers/voice_transcription.py": "module_enabled(",
        "handlers/youtube.py": "module_enabled(",
        "handlers/checkup.py": "module_enabled(",
        "handlers/video_download.py": "media_download.module_enabled",
        "web/api/stories.py": "stories_vitrina_enabled_for_chat",
    }
    for rel, needle in expected.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert needle in text, rel


# ═══ адаптер только читает ════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_adapter_does_not_rewrite_stored_values(world, monkeypatch):
    stored = {"overrides": {"flags.search_enabled": False,
                            "memory.random_enabled": True},
              "gates": {"nostalgia": False}}
    cache = _set_chat(world, stored)
    snapshot = copy.deepcopy(cache.by_chat)
    world.globals = {"flags.search_enabled": True,
                     "memory.random_enabled": True,
                     "flags.nostalgia_enabled": True,
                     "memory.nostalgia_enabled": False}

    async def _forbidden(*args, **kwargs):      # pragma: no cover - guard
        raise AssertionError("adapter не имеет права писать настройки")

    monkeypatch.setattr(chat_params, "set_chat_params", _forbidden)

    assert await feature_gates.module_enabled(
        CHAT, key="flags.search_enabled") is False
    assert await mca_gates.random_source_enabled_for_chat(CHAT) is True
    await feature_gates.gate_state(CHAT, "nostalgia")
    assert cache.by_chat == snapshot
    assert cache.invalidated == []
