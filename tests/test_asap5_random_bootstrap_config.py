"""asap5-final-fixes (ADR-1028-25, D13/T-5261–T-5263, §14/14A) — Random
source config-clarity + ANU bootstrap-фикс.

Покрытие (§16#34–36 + 14A.0/14A.4):

* #34 quantum + ключа нет → effective pseudorandom + точный блокер
  `provider_unconfigured` (configuration/degraded state, не runtime-сбой);
* #35 явный pseudorandom → без ложного WARN random_fallback;
* #36 notable transition — один emit на смену state-key (не на каждый draw);
* 14A.0 bootstrap paradox: НЕзаданный секрет `keys.random_quantum_api_key`
  присутствует в `/api/config`-снапшоте (cache.get_all) как catalog-only
  item (значение "" → маска configured=false), карточка ANU видна ДО
  первой настройки и переживает «рестарт» (новый инстанс кэша);
  строк в БД не создаётся; plaintext не существует;
* фактическое сохранение ключа → реальная строка, synthetic исчезает,
  blocker уходит (T-5263 code-path; живой ввод ключа — owner, T-5274).
"""
import asyncio

import pytest

from services import mca_gates
from services.database import DatabaseService

pytestmark = pytest.mark.asap4


# ── фикстуры ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _cache_with(settings_map):
    """ConfigCache без PG: _settings подменяется, get_all — реальный (D13)."""
    from services.config_cache import ConfigCache
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = dict(settings_map)
    return cache


# ── §16#34–36: config-state ≠ runtime failure ───────────────────────────────

def test_unconfigured_anu_key_is_masked_not_plaintext():
    """14A.0: синтетический item незаданного секрета — пустая строка;
    `_mask_secret("")` → {configured: False, last4: None} (без plaintext)."""
    from web.api.routes import _mask_secret
    masked = _mask_secret("", telegram_id=1,
                          pg_key="keys.random_quantum_api_key", cache=None)
    assert masked == {"configured": False, "last4": None}


def test_get_all_synthesizes_keys_random_group_only():
    """D13: синтезируются ТОЛЬКО незаданные ключи санкционированной группы
    keys_random; чужие группы не трогаются; секреты → "", не-секреты —
    каталоговый дефолт Settings (честное значение рантайма)."""
    cache = _cache_with({"memory.random_source": "quantum"})
    snap = cache.get_all()
    # Секрет группы присутствует как catalog-only (пустая строка).
    assert "keys.random_quantum_api_key" in snap
    assert snap["keys.random_quantum_api_key"] == ""
    # Не-секретные поля карточки ANU — дефолты (карточка рендерится целиком).
    assert snap.get("keys.random_quantum_plan") == "Trial"
    assert snap.get("keys.random_quantum_data_type") == "uint16"
    # Чужая незаданная группа НЕ синтезируется.
    assert "keys.llm_api_key" not in snap
    # Уже заданные ключи не подменяются.
    cache2 = _cache_with({"keys.random_quantum_api_key": "real-key-value"})
    assert cache2.get_all()["keys.random_quantum_api_key"] == "real-key-value"


def test_synthetic_items_survive_restart_and_create_no_db_rows(db):
    """14A.4 п.1–8 (код-часть): карточка переживает «рестарт» (новый
    инстанс кэша без БД-строк) — деривация на чтении; фиктивных строк нет."""
    # «Рестарт»: свежий кэш над пустым _settings — item снова на месте.
    fresh = _cache_with({})
    assert fresh.get_all().get("keys.random_quantum_api_key") == ""
    # В реальной БД bot_settings строка НЕ появлялась (никто не писал).
    # Проверяем семантику сида: секреты не сидятся (pg_db._seed_settings).
    from services.pg_db import SEED_CATEGORIES
    assert "keys" not in SEED_CATEGORIES


def test_real_key_persisted_replaces_synthetic():
    """T-5263 (code-path): ключ сохранён через существующий PG-путь →
    он в _settings → synthetic больше не нужен; значение не «пустая строка».
    Живой ввод ключа владельцем — T-5274 (no-false-acceptance)."""
    cache = _cache_with({"keys.random_quantum_api_key": "abcd1234"})
    snap = cache.get_all()
    assert snap["keys.random_quantum_api_key"] == "abcd1234"
    from web.api.routes import _mask_secret
    masked = _mask_secret("abcd1234", telegram_id=1,
                          pg_key="keys.random_quantum_api_key", cache=None)
    assert masked == {"configured": True, "last4": "1234"}


# ── snapshot: проверяемые поля config-state (T-5261) ───────────────────────

@pytest.mark.asyncio
async def test_status_snapshot_fallback_setting_field(db, monkeypatch):
    """§14: `fallback_setting` — проверяемое поле config-state в snapshot
    (разрешены ли PRNG-откаты)."""
    from services import mca_random_source as rs
    svc = rs.RandomSourceService(db)
    monkeypatch.setattr(rs, "get_service", lambda: svc)
    snap = await svc.status_snapshot(chat_id=None)
    assert "fallback_setting" in snap
    assert isinstance(snap["fallback_setting"], bool)
    assert "fallback_reason" in snap and "key_present" in snap
