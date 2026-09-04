"""Раунд 5 (T-740/T-741, spec 5.3.3, FR-D3/FR-D4) — авто-миграция канонов
промптов (services/prompt_migrations.py).

Покрытие (мок-cache): все 9 ключей PROMPT_MIGRATIONS — prev→new обновляет
(set(key, new, "prompts") + INFO); direct_chat — LEGACY→new и PREV→new (две
ступени); current == new → no-op; кастом юзера → skip + WARNING (не трогаем);
None → skip (сид сделает своё); PG down / cache None → skip; возврат отчёта;
prompts.extract_system_prompt НЕ входит; фиксированный порядок итерации.
"""
import logging

import pytest

from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    LEGACY_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_SYSTEM_PROMPT,
)
from services.checkup_prompts import (
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_SYSTEM_PROMPT,
)
from services.factcheck_prompts import (
    FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_SYSTEM_PROMPT,
)
from services.prompt_migrations import PROMPT_MIGRATIONS, migrate_prompt_canons
from services.search_prompts import PREV_SEARCH_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT
from services.summary_prompts import (
    COMPRESS_PROMPT,
    PREV_COMPRESS_PROMPT,
    PREV_SUMMARY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from services.web_prompts import PREV_WEBPAGE_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT
from services.youtube_prompts import (
    PREV_YOUTUBE_SYSTEM_PROMPT,
    PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT,
    YOUTUBE_SYSTEM_PROMPT,
    YOUTUBE_VIDEO_SYSTEM_PROMPT,
)

_ALL_KEYS = [
    "prompts.direct_chat_system_prompt",
    "prompts.summary_system_prompt",
    "prompts.compress_system_prompt",
    "prompts.checkup_system_prompt",
    "prompts.factcheck_system_prompt",
    "prompts.search_system_prompt",
    "prompts.youtube_system_prompt",
    "prompts.youtube_video_system_prompt",
    "prompts.webpage_system_prompt",
]

# prev-эталон (слепок HEAD 68fb03e) для каждой ступени — первая пара.
_PREV_BY_KEY: dict[str, str] = {
    "prompts.direct_chat_system_prompt": PREV_CHAT_SYSTEM_PROMPT,
    "prompts.summary_system_prompt": PREV_SUMMARY_SYSTEM_PROMPT,
    "prompts.compress_system_prompt": PREV_COMPRESS_PROMPT,
    "prompts.checkup_system_prompt": PREV_CHECKUP_SYSTEM_PROMPT,
    "prompts.factcheck_system_prompt": PREV_FACTCHECK_SYSTEM_PROMPT,
    "prompts.search_system_prompt": PREV_SEARCH_SYSTEM_PROMPT,
    "prompts.youtube_system_prompt": PREV_YOUTUBE_SYSTEM_PROMPT,
    "prompts.youtube_video_system_prompt": PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT,
    "prompts.webpage_system_prompt": PREV_WEBPAGE_SYSTEM_PROMPT,
}

# new-канон (раунд 5) для каждого ключа.
_NEW_BY_KEY: dict[str, str] = {
    "prompts.direct_chat_system_prompt": CHAT_SYSTEM_PROMPT,
    "prompts.summary_system_prompt": SYSTEM_PROMPT,
    "prompts.compress_system_prompt": COMPRESS_PROMPT,
    "prompts.checkup_system_prompt": CHECKUP_SYSTEM_PROMPT,
    "prompts.factcheck_system_prompt": FACTCHECK_SYSTEM_PROMPT,
    "prompts.search_system_prompt": SEARCH_SYSTEM_PROMPT,
    "prompts.youtube_system_prompt": YOUTUBE_SYSTEM_PROMPT,
    "prompts.youtube_video_system_prompt": YOUTUBE_VIDEO_SYSTEM_PROMPT,
    "prompts.webpage_system_prompt": WEBPAGE_SYSTEM_PROMPT,
}


class FakeCache:
    """Фейковый ConfigCache-контракт: pg_available, sync get, async set.
    Хранит dict значений по ключам (get вне словаря → None)."""

    def __init__(self, values=None, pg_available=True):
        self.pg_available = pg_available
        self.values = dict(values or {})
        self.set_calls = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))


class TestPromptMigrationsCatalog:
    def test_all_nine_keys_present(self):
        assert list(PROMPT_MIGRATIONS) == _ALL_KEYS

    def test_no_extract_key(self):
        """prompts.extract_system_prompt НЕ входит (EXTRACT_PROMPT не трогаем)."""
        assert "prompts.extract_system_prompt" not in PROMPT_MIGRATIONS

    def test_direct_chat_two_steps_legacy_then_prev(self):
        steps = PROMPT_MIGRATIONS["prompts.direct_chat_system_prompt"]
        assert steps == [(LEGACY_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT)]

    def test_catalog_points_to_new_canons(self):
        """new во всех ступенях == канону раунда 5 (байт-сверка со спека)."""
        for key, steps in PROMPT_MIGRATIONS.items():
            for _prev, new in steps:
                assert new == _NEW_BY_KEY[key]

    def test_prev_snapshots_differ_from_new(self):
        for key in _ALL_KEYS:
            assert _PREV_BY_KEY[key] != _NEW_BY_KEY[key]


class TestMigratePromptCanons:
    @pytest.mark.asyncio
    async def test_all_prev_values_updated_to_new(self):
        cache = FakeCache(values=_PREV_BY_KEY)
        report = await migrate_prompt_canons(cache)
        assert report == {key: "updated" for key in _ALL_KEYS}
        assert cache.set_calls == [
            (key, _NEW_BY_KEY[key], "prompts") for key in _ALL_KEYS]

    @pytest.mark.asyncio
    async def test_direct_chat_legacy_step_updates(self):
        """Прод мог отстать на канон раунда 2 (LEGACY) → первая ступень."""
        cache = FakeCache(values={
            "prompts.direct_chat_system_prompt": LEGACY_CHAT_SYSTEM_PROMPT})
        report = await migrate_prompt_canons(cache)
        assert report == {"prompts.direct_chat_system_prompt": "updated"}
        assert cache.set_calls == [
            ("prompts.direct_chat_system_prompt", CHAT_SYSTEM_PROMPT, "prompts")]

    @pytest.mark.asyncio
    async def test_already_new_canons_noop(self):
        cache = FakeCache(values=_NEW_BY_KEY)
        report = await migrate_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_custom_user_values_untouched_with_warning(self, caplog):
        cache = FakeCache(values={
            "prompts.direct_chat_system_prompt": "мой кастомный промпт",
            "prompts.summary_system_prompt": "ещё один кастом",
        })
        with caplog.at_level(logging.WARNING,
                             logger="services.prompt_migrations"):
            report = await migrate_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []
        warns = [r for r in caplog.records
                 if "кастом юзера — НЕ трогаем" in r.message]
        assert len(warns) == 2
        assert "key=prompts.direct_chat_system_prompt" in warns[0].message
        assert "chars=" in warns[0].message

    @pytest.mark.asyncio
    async def test_missing_keys_skipped_info(self, caplog):
        cache = FakeCache(values={})
        with caplog.at_level(logging.INFO, logger="services.prompt_migrations"):
            report = await migrate_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []
        infos = [r for r in caplog.records
                 if "ключ отсутствует — сид сделает своё" in r.message]
        assert len(infos) == 9

    @pytest.mark.asyncio
    async def test_pg_unavailable_skipped(self, caplog):
        cache = FakeCache(values=_PREV_BY_KEY, pg_available=False)
        with caplog.at_level(logging.INFO, logger="services.prompt_migrations"):
            report = await migrate_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []
        assert any("[prompt_migration] skip: PG недоступен" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_none_cache_skipped(self, caplog):
        with caplog.at_level(logging.INFO, logger="services.prompt_migrations"):
            report = await migrate_prompt_canons(None)
        assert report == {}
        assert any("[prompt_migration] skip: PG недоступен" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_iteration_order_is_fixed(self, caplog):
        """Логи/порядок set — по порядку объявления PROMPT_MIGRATIONS."""
        cache = FakeCache(values=_PREV_BY_KEY)
        await migrate_prompt_canons(cache)
        assert [key for key, _val, _cat in cache.set_calls] == _ALL_KEYS
