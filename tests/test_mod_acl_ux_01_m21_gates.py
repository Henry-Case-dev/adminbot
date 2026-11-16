"""MOD-ACL-UX-01 M2.1 — гейты, precedence и отсутствие второго решателя.

Проверяется:
* `nostalgia`: `memory.nostalgia_enabled` — master; legacy
  `flags.nostalgia_enabled` не перекрывает его (design §12.3);
* `initiative`: product master (`flags.initiative_enabled` + env) остаётся
  AND-осью; chat ON не обходит глобальный master;
* `character`/`random`: shared-модель/пул — глобальный master, чат может
  только отключить использование у себя;
* второго resolver/ACL/registry нет: адаптеры вызывают существующий
  `chat_params.resolve_capability`;
* адаптеры только читают: stored values и кэш не переписываются.
"""
import copy
import pathlib

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


# ═══ initiative: product master + emergency env ═══════════════════════════

@pytest.mark.asyncio
async def test_initiative_product_master_and_stays(world, monkeypatch):
    """Chat ON не обходит product master `flags.initiative_enabled`."""
    monkeypatch.setattr(initiative_observer, "observer_enabled", lambda: False)
    world.globals = {"flags.initiative_enabled": False,
                     "initiative.enabled": True}
    _set_chat(world, {"overrides": {"initiative.enabled": True},
                      "gates": {}})
    assert await initiative_observer.initiative_publish_block_reason(
        CHAT) == "capability_off"
    # Тот же глобальный master остаётся аварийной осью и в chat-состоянии:
    # чат ON не делает состояние исполняемым.
    assert await initiative_observer.chat_observer_enabled(CHAT) is False
    assert initiative_observer.observer_enabled() is False


@pytest.mark.asyncio
async def test_initiative_emergency_env_overrides_chat(world, monkeypatch):
    """Аварийная env-ось (K1) — отдельная ось, важнее chat; желание не
    подменяется (`desired=True`, `emergency_block=True`)."""
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
    world.globals = {"flags.initiative_enabled": True,
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


# ═══ character / random: shared master, chat → usage ══════════════════════

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
async def test_random_global_master_blocks_chat_on(world):
    """GLOBAL OFF + CHAT ON не обходит выключенный shared-пул."""
    world.globals = {"memory.random_enabled": False}
    _set_chat(world, {"overrides": {"memory.random_enabled": True},
                      "gates": {}})
    assert await mca_gates.random_source_enabled_for_chat(CHAT) is False


@pytest.mark.asyncio
async def test_character_global_master_blocks_chat_on(world):
    """GLOBAL OFF + CHAT ON не включает глобально выключенную модель."""
    world.globals = {"flags.self_model_enabled": False}
    _set_chat(world, {"overrides": {"flags.self_model_enabled": True},
                      "gates": {}})
    assert await mca_gates.self_model_enabled_for_chat(CHAT) is False


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
