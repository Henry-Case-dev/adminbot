"""ASAP 8 v6 Wave A1 — D08: PG-only ключи каталога в get_all() (/api/config).

Root cause (ledger D08): `config_cache.get_all()` синтезировал catalog-only
items ТОЛЬКО для группы keys_random, поэтому PG-only ParamSpec
`memory.random_enabled` (нет Settings-поля, нет строки bot_settings до
первой записи) отсутствовал в /api/config → карточка модуля «Случайность»
получала null → тумблер упирался в «Параметр недоступен: memory.random_enabled».

Контракт после фикса:
  * синтетика для ВСЕХ PG-only ключей (settings_field/env_name = None,
    не hidden) с честными дефолтами по классам (secret/code_source/bool/
    str/int-float-json);
  * persistent (bot_settings) всегда выигрывает у синтетики;
  * честный флаг источника: синтетика → get_updated_at(key) is None;
  * синхронный get()/hot_config читает только bot_settings — рантайм и
    env AND-гейт (MCA_RANDOM_SOURCE_ENABLED) синтетикой не затронуты;
  * ANU-синтетика keys_random не сломана.

TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/D08
"""
import json

import pytest

from config.settings import settings
from services.config_cache import ConfigCache, _PG_ONLY_BOOL_DEFAULTS
from services.param_catalog import REGISTRY


# ── Фикстуры (минимальные фейки из tests/test_config_cache.py) ──────────────

class _FakeConn:
    def __init__(self, settings_rows):
        self._settings_rows = settings_rows
        self.queries = []

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))

    async def fetch(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        if "bot_settings" in sql:
            return self._settings_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _FakePg:
    def __init__(self, pool=None, fail_connect=False):
        self._pool = pool
        self._fail_connect = fail_connect

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        if self._fail_connect:
            raise ConnectionError("pg down")

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


async def _cache_with_rows(settings_rows) -> ConfigCache:
    cache = ConfigCache(pg=_FakePg(pool=_FakePool(_FakeConn(settings_rows))),
                        retry_attempts=1, retry_delay=0)
    await cache.init()
    return cache


async def _cache_degraded() -> ConfigCache:
    """PG недоступен: _settings пуст → вся синтетика видна."""
    cache = ConfigCache(pg=_FakePg(fail_connect=True),
                        retry_attempts=1, retry_delay=0)
    await cache.init()
    return cache


def _pg_only_specs():
    return [s for s in REGISTRY.values()
            if s.category is not None and s.settings_field is None
            and s.env_name is None and not s.hidden]


# ── D08: memory.random_enabled присутствует без строки БД ───────────────────

@pytest.mark.asyncio
async def test_d08_random_enabled_present_without_db_row():
    """Root cause D08: PG-only master виден в /api/config до первой записи."""
    cache = await _cache_degraded()
    snap = cache.get_all()
    assert "memory.random_enabled" in snap
    assert snap["memory.random_enabled"] is True   # PRODUCT_DEFAULTS (F5 §5.3)


@pytest.mark.asyncio
async def test_d08_synthetic_items_are_default_source():
    """Честный флаг источника: синтетика → updated_at None (default)."""
    cache = await _cache_degraded()
    snap = cache.get_all()
    assert "memory.random_enabled" in snap
    assert cache.get_updated_at("memory.random_enabled") is None


@pytest.mark.asyncio
async def test_d08_write_makes_item_persistent():
    """После записи строка (память/БД) выигрывает: persistent, не синтетика.

    P0 PERSIST-FIX: запись без пула теперь явная ConfigCacheUnavailableError,
    поэтому тест даёт пул (прежде проверял тихий in-memory успех при PG down).
    """
    cache = await _cache_with_rows([])
    assert cache.get_all()["memory.random_enabled"] is True
    await cache.set("memory.random_enabled", False, "memory")
    snap = cache.get_all()
    assert snap["memory.random_enabled"] is False
    # синтетика больше не нужна: значение из _settings (persistent-слой)
    assert cache.get("memory.random_enabled") is False


@pytest.mark.asyncio
async def test_d08_persistent_row_wins_over_synthetic():
    """Существующая строка bot_settings не перезаписывается синтетикой."""
    cache = await _cache_with_rows([
        {"key": "memory.random_enabled", "value": False,
         "category": "memory"},
    ])
    assert cache.get_all()["memory.random_enabled"] is False


@pytest.mark.asyncio
async def test_d08_runtime_read_and_env_gate_unaffected():
    """AND-гейт не задет: синтетика живёт только в get_all() — синхронный
    get() (hot_config/рантайм) читает только bot_settings; env-ось
    MCA_RANDOM_SOURCE_ENABLED в config_cache не читается вовсе."""
    cache = await _cache_degraded()
    assert "memory.random_enabled" in cache.get_all()
    assert cache.get("memory.random_enabled") is None          # рантайм-слой
    assert cache.get("memory.random_enabled", True) is True    # fail-open как был
    from services import module_registry
    assert module_registry.ENV_GATES["random"] == "MCA_RANDOM_SOURCE_ENABLED"


@pytest.mark.asyncio
async def test_d08_anu_keys_random_synthesis_intact():
    """ANU-прецедент не сломан: секреты keys_random → '', не-секреты →
    дефолт Settings (прежний контракт D13/T-5262)."""
    cache = await _cache_degraded()
    snap = cache.get_all()
    assert snap["keys.random_quantum_api_key"] == ""
    assert snap["keys.random_quantum_endpoint"] == \
        settings.RANDOM_QUANTUM_ENDPOINT
    assert snap["keys.random_quantum_batch_length"] == \
        int(settings.RANDOM_QUANTUM_BATCH_LENGTH)


# ── Полнота синтетики по каталогу (контракт «ВСЕ PG-only ключи») ────────────

@pytest.mark.asyncio
async def test_d08_all_pg_only_keys_present_with_honest_defaults():
    """Каждый PG-only ключ каталога присутствует в get_all() с честным
    дефолтом своего класса; hidden — вне синтетики (внутренние ключи)."""
    cache = await _cache_degraded()
    snap = cache.get_all()
    for spec in _pg_only_specs():
        assert spec.pg_key in snap, f"PG-only ключ отсутствует: {spec.pg_key}"
        if spec.code_source is not None:
            assert isinstance(snap[spec.pg_key], str) \
                and snap[spec.pg_key], spec.pg_key
        elif spec.secret:
            assert snap[spec.pg_key] == "", spec.pg_key
        elif spec.type == "bool":
            assert snap[spec.pg_key] is True or \
                snap[spec.pg_key] is False, spec.pg_key
        elif spec.type == "str":
            assert snap[spec.pg_key] == "", spec.pg_key
        else:  # int/float/json: «не задано владельцем»
            assert snap[spec.pg_key] is None, spec.pg_key
    # hidden-ключ остаётся внутренним (не синтезируется)
    assert "prompts.summary_cover_style_id" not in snap


@pytest.mark.asyncio
async def test_d08_pg_only_bool_defaults_cover_catalog():
    """Контракт покрытия: КАЖДЫЙ PG-only bool каталога имеет запись в
    PRODUCT_DEFAULTS или _PG_ONLY_BOOL_DEFAULTS — новый ключ без решения
    о дефолте = RED."""
    from services.module_registry import PRODUCT_DEFAULTS
    bool_keys = {s.pg_key for s in _pg_only_specs() if s.type == "bool"}
    covered = set(_PG_ONLY_BOOL_DEFAULTS) | set(PRODUCT_DEFAULTS)
    missing = bool_keys - covered
    assert not missing, f"PG-only bool без честного дефолта: {sorted(missing)}"


@pytest.mark.asyncio
async def test_d08_random_uses_defaults_true():
    """MCA-10b: memory.random_uses_* — fail-open True (зеркало рантайма)."""
    cache = await _cache_degraded()
    snap = cache.get_all()
    for key in sorted(k for k in snap if k.startswith("memory.random_uses_")):
        assert snap[key] is True, key


@pytest.mark.asyncio
async def test_d08_prompt_code_source_synthesized():
    """prompts с code_source синтезируются код-каноном (прецедент сида)."""
    cache = await _cache_degraded()
    snap = cache.get_all()
    value = snap["prompts.checkup_system_prompt"]
    assert isinstance(value, str) and value.strip()


@pytest.mark.asyncio
async def test_d08_synthetic_json_serializable():
    """Синтетика уходит в JSONB-совместимый payload /api/config без сюрпризов
    типов (None/bool/str/int — JSON-типы)."""
    cache = await _cache_degraded()
    snap = cache.get_all()
    for spec in _pg_only_specs():
        value = snap[spec.pg_key]
        assert value is None or isinstance(
            value, (bool, int, float, str, list, dict)), spec.pg_key


@pytest.mark.asyncio
async def test_d08_settings_backed_keys_unchanged():
    """Ключи с Settings-полем вне keys_random — прежнее поведение: в
    деградации (без сида) их в get_all() НЕТ, синтетика D08 на них не
    распространяется; keys_random-пара при этом синтезируется."""
    cache = await _cache_degraded()
    snap = cache.get_all()
    assert "limits.search_max_symbols" not in snap   # settings-backed, не PG-only
    assert "keys.random_quantum_endpoint" in snap    # keys_random — синтетика D13


@pytest.mark.asyncio
async def test_d08_api_render_contract_for_synthetic_items():
    """Контракт рендера /api/config (web/api/routes.py): синтетический
    секрет '' → маска {configured: False, last4: None} (ANU-прецедент),
    None-значение не-секрета проходит как честное «не задано»."""
    from web.api.routes import _mask_secret
    assert _mask_secret("", 1, "keys.direct_l1_api_key", None) == \
        {"configured": False, "last4": None}
    assert _mask_secret(None, 1, "limits.direct_l1_context_tokens", None) == \
        {"configured": False, "last4": None}
    # не-секреты не маскируются вовсе (routes.py: значение проходит как есть)
    cache = await _cache_degraded()
    assert cache.get_all()["flags.direct_l1_enabled"] is True
    assert cache.get_all()["limits.direct_l1_context_tokens"] is None
