"""Решение владельца 25.10.2026: широкий контекст фактчека по умолчанию.

Проверяется: новый code-дефолт, hot-откат без рестарта, одноразовая
идемпотентная миграция сохранённого `false` (ручное выключение после неё не
перетирается), каталог/группа UI и реальная проводка широкого контекста
(не только флаг), включая пустую цель.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

import handlers.factcheck as fh
from config.settings import settings
from services import factcheck_context as fcx
from services import factcheck_suitability as fsg
from services import param_catalog
from services.config_migrations import (
    FACTCHECK_WIDE_CONTEXT_KEY,
    FACTCHECK_WIDE_CONTEXT_MIGRATION_MARKER,
    migrate_factcheck_wide_context_default,
)

CHAT_ID = -1002661910336


class _FakeCache:
    pg_available = True

    def __init__(self, store=None):
        self.store = dict(store or {})

    def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, layer=None):
        self.store[key] = value


class _Db:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def get_messages_around(self, chat_id, target, before, after):
        self.calls.append((chat_id, target, before, after))
        return list(self.rows)

    async def get_recent_messages(self, chat_id, limit):
        return list(self.rows[-limit:]) if limit else []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        return None


def _row(tg, text):
    return {"id": tg, "chat_id": CHAT_ID, "tg_message_id": tg, "text": text,
            "caption": None, "reply_to_id": None, "timestamp": 1792200000 + tg,
            "media_type": "text", "author_name": "Вася", "is_forward": False,
            "forward_source": None}


class _NullCache:
    """Не кеширует: тест проверяет фактический вызов DB, не прошлый прогон."""

    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        return None


# ── Дефолт и откат ──────────────────────────────────────────────────────────

def test_new_code_default_is_on():
    # class-атрибут (инстанс могли временно переопределить другие тесты)
    assert type(settings).FACTCHECK_WIDE_CONTEXT_ENABLED is True


def test_wide_context_enabled_defaults_true(monkeypatch):
    from services import hot_config as hot
    monkeypatch.setattr(hot, "get", lambda key, default=None: default)
    old = getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", None)
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", True)
    try:
        assert fcx.wide_context_enabled() is True
    finally:
        object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", old)


def test_manual_off_is_honoured(monkeypatch):
    from services import hot_config as hot
    monkeypatch.setattr(hot, "get",
                        lambda key, default=None: False)
    assert fcx.wide_context_enabled() is False


# ── Одноразовая миграция ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_migration_raises_inherited_false_once():
    cache = _FakeCache({FACTCHECK_WIDE_CONTEXT_KEY: False})
    report = await migrate_factcheck_wide_context_default(cache)
    assert report == {FACTCHECK_WIDE_CONTEXT_KEY: "updated"}
    assert cache.get(FACTCHECK_WIDE_CONTEXT_KEY) is True
    assert cache.get(FACTCHECK_WIDE_CONTEXT_MIGRATION_MARKER) is True


@pytest.mark.asyncio
async def test_migration_is_idempotent_and_keeps_manual_off():
    cache = _FakeCache({FACTCHECK_WIDE_CONTEXT_KEY: False})
    await migrate_factcheck_wide_context_default(cache)
    # владелец выключил ПОСЛЕ миграции
    cache.store[FACTCHECK_WIDE_CONTEXT_KEY] = False
    report = await migrate_factcheck_wide_context_default(cache)
    assert report == {}
    assert cache.get(FACTCHECK_WIDE_CONTEXT_KEY) is False


@pytest.mark.asyncio
async def test_migration_noop_when_true_or_missing():
    cache = _FakeCache({FACTCHECK_WIDE_CONTEXT_KEY: True})
    assert await migrate_factcheck_wide_context_default(cache) == {}
    assert cache.get(FACTCHECK_WIDE_CONTEXT_MIGRATION_MARKER) is True
    empty = _FakeCache()
    assert await migrate_factcheck_wide_context_default(empty) == {}
    assert empty.get(FACTCHECK_WIDE_CONTEXT_MIGRATION_MARKER) is None


@pytest.mark.asyncio
async def test_migration_skips_without_pg():
    cache = _FakeCache({FACTCHECK_WIDE_CONTEXT_KEY: False})
    cache.pg_available = False
    assert await migrate_factcheck_wide_context_default(cache) == {}
    assert cache.get(FACTCHECK_WIDE_CONTEXT_KEY) is False


# ── Каталог / UI-контракт ───────────────────────────────────────────────────

def test_catalog_spec_visible_in_modules_factcheck():
    spec = param_catalog.REGISTRY["FACTCHECK_WIDE_CONTEXT_ENABLED"]
    assert spec.group == "flags_module_factcheck"
    assert param_catalog.TAB_MOD_FACTCHECK == "mod_factcheck"
    assert "по умолчанию" in spec.description.lower()
    assert "200–500" in spec.description
    assert "без рестарта" in spec.description
    assert getattr(type(settings), spec.settings_field) is True
    assert spec.pg_id == "flags.factcheck_wide_context"


@pytest.mark.asyncio
async def test_context_window_sees_caption_of_photo_message():
    """Подпись (caption) — содержание окна: раньше такие строки выпадали."""
    row = _row(295, None)
    row["caption"] = "Сдан объект 12.10.2026 по данным мэрии"
    db = _Db([row, _row(296, "болтовня и флуд")])
    probe = await fsg.resolve_context_claim(
        db, CHAT_ID, target_tg_message_id=999, trigger_tg_message_id=1000,
        cache=None)
    assert probe is not None and probe.claim is not None
    assert "Сдан объект" in probe.claim.text


# ── Проводка: широкий контекст реально используется ────────────────────────

@pytest.mark.asyncio
async def test_wide_context_used_for_nonempty_target(monkeypatch):
    rows = [_row(280 + i, "болтовня и флуд") for i in range(30)]
    rows[0] = _row(280, "Дальний факт: сборка 2.58.130 вышла 25.10.2026")
    rows.append(_row(300, "цель с текстом"))
    db = _Db(rows)
    monkeypatch.setattr(fh, "_db", db)
    monkeypatch.setattr(fh, "_cp_g", AsyncMock(return_value=6))
    monkeypatch.setattr(fcx, "wide_context_enabled", lambda: True)
    monkeypatch.setattr("services.smart_cache.get_smart_cache",
                        lambda: _NullCache())
    feed = await fh._fetch_chat_context(
        CHAT_ID, 6, 6, target_tg_message_id=300, trigger_message_id=301,
        claim_text="цель с текстом")
    assert "<chat_context" in feed
    assert "Дальний факт" in feed          # окно шире 6 сообщений
    assert db.calls and db.calls[0][2] > 6  # before >> узкого окна


@pytest.mark.asyncio
async def test_empty_target_probe_uses_wide_context_even_if_gate_off():
    rows = [_row(295 + i, "болтовня и флуд") for i in range(20)]
    rows[0] = _row(295, "Сдан объект 12.10.2026 по данным мэрии")
    db = _Db(rows)
    probe = await fsg.resolve_context_claim(
        db, CHAT_ID, target_tg_message_id=999, trigger_tg_message_id=1000,
        cache=None)
    assert probe is not None
    assert probe.claim is not None
    assert "Сдан объект" in probe.claim.text
    assert probe.window_messages >= 20
    assert db.calls and db.calls[0][2] > 6
