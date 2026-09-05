"""Epic 85 (T-636) — тесты каталога-реестра параметров (84.12.2).

DoD: полнота (каждое поле Settings покрыто), категории каноничны,
секретность (все keys + прокси → secret), инфраструктура исключена
(category=None), prompts — PG-only код-каноны (резолвятся через importlib),
ключи dotted {category}.{snake}.
"""
import dataclasses
import importlib

import pytest

from config.settings import Settings
from services import param_catalog as pc
from services.param_catalog import (
    CATEGORIES,
    GROUPS,
    ParamSpec,
    REGISTRY,
    iter_migratable,
    iter_pg_only,
)


class TestCompleteness:
    """DoD T-636: каждый dataclass-поле Settings покрыто ровно одной записью."""

    def test_every_settings_field_covered(self):
        missing, extra = pc.settings_field_coverage()
        assert missing == set(), f"не покрыты: {sorted(missing)}"
        assert extra == set(), f"лишние записи: {sorted(extra)}"

    def test_settings_field_count(self):
        fields = {f.name for f in dataclasses.fields(Settings)}
        # 271: 265 + 5 (embed-фоллбэк EMBEDDING_FALLBACK_* — раунд 5) +
        # 1 (EMBEDDING_FALLBACK_API_KEY_2 — каскад ключей, задача 1) +
        # 11 (раунд 7, T-776: LORE_* — лор чатов, spec §3.11) +
        # 6 (раунд 8, T-793/T-798/T-801/T-803: контекст-слой, spec §3.G2) +
        # 6 (раунд 8, T-804/T-805/T-808/T-810: уровни L2, дедуп RAG,
        #   purge-гейты, LLM-реранк, spec §3.G2) — каталог пополнен парно
        assert len(fields) == 294
        covered = {s.settings_field for s in REGISTRY.values() if s.settings_field}
        assert covered == fields

    def test_categories_canonical(self):
        for spec in REGISTRY.values():
            assert spec.category in (None, *pc.CATEGORIES)

    def test_pg_keys_dotted_and_unique(self):
        keys = [s.pg_key for s in REGISTRY.values()]
        assert len(keys) == len(set(keys))
        for spec in REGISTRY.values():
            if spec.category is None:
                continue
            assert spec.pg_key.count(".") >= 1
            assert spec.pg_key.startswith(spec.category + ".")

    def test_titles_and_types(self):
        for spec in REGISTRY.values():
            assert spec.title_ru
            assert spec.type in ("str", "int", "float", "bool", "json")


class TestInfraExcluded:
    """84.12.1: infra остаётся в .env — category=None, НЕ мигрируется."""

    INFRA_FIELDS = {
        "API_TOKEN", "DB_PATH", "MEDIA_BASE", "COBALT_API_URL",
        "LOCAL_BOT_API_URL", "TELEGRAM_API_FILES_DIR", "DOWNLOAD_DIR",
        "INFO_TEXT_FILE", "CHECKUP_JOURNALCTL_CMD",
        # embed-фоллбэк (раунд 5): EMBEDDING_FALLBACK_* — infra (.env)
        "EMBEDDING_FALLBACK_BASE_URL", "EMBEDDING_FALLBACK_API_KEY",
        "EMBEDDING_FALLBACK_API_KEY_2",
        "EMBEDDING_FALLBACK_MODEL", "EMBEDDING_FALLBACK_TIMEOUT_SECONDS",
        "EMBEDDING_FALLBACK_MAX_RETRIES",
        # env-only
        "POSTGRES_DSN", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_USER",
        "WEB_PORT", "LOG_RING_MAX_ENTRIES", "UPTIME_EVENTS_RETENTION_HOURS",
        "SENTRY_DSN", "LOGTAIL_SOURCE_TOKEN", "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH", "COBALT_HTTP_PROXY",
    }

    def test_infra_category_none(self):
        for field in self.INFRA_FIELDS:
            spec = pc.get(field)
            assert spec is not None, field
            assert spec.category is None, field

    def test_infra_not_migratable(self):
        for spec in REGISTRY.values():
            if spec.category is None:
                assert not spec.migratable
                assert spec not in iter_migratable()

    def test_env_only_infra_present(self):
        for field in ("POSTGRES_DSN", "WEB_PORT", "LOG_RING_MAX_ENTRIES",
                      "UPTIME_EVENTS_RETENTION_HOURS"):
            spec = pc.get(field)
            assert spec is not None
            assert spec.settings_field is None or spec.env_name == field


class TestSecrets:
    """DoD T-636: все keys-секреты и прокси → secret:true (R17)."""

    SECRET_KEYS = {
        "LLM_API_KEY", "LLM_FALLBACK_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY",
        "GROQ_API_KEY", "OPENROUTER_API_KEY",
        "CHECKUP_BETTERSTACK_SQL_USER", "CHECKUP_BETTERSTACK_SQL_PASSWORD",
        "YOUTUBE_TRANSCRIPT_PROXY_URL", "YOUTUBE_TRANSCRIPT_PROXY_USERNAME",
        "YOUTUBE_TRANSCRIPT_PROXY_PASSWORD", "YOUTUBE_COOKIES_FILE",
        "API_TOKEN", "POSTGRES_DSN", "POSTGRES_PASSWORD", "SENTRY_DSN",
        "LOGTAIL_SOURCE_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
        "COBALT_HTTP_PROXY",
        # embed-фоллбэк (раунд 5): ключ Google AI Studio — секрет (R17)
        "EMBEDDING_FALLBACK_API_KEY",
        # каскад ключей embed-фоллбэка (задача 1): второй ключ — тоже секрет
        "EMBEDDING_FALLBACK_API_KEY_2",
    }

    def test_secret_flags(self):
        for field in self.SECRET_KEYS:
            spec = pc.get(field)
            assert spec is not None, field
            assert spec.secret is True, field

    def test_non_secret_catalog_values(self):
        for field in ("LLM_BASE_URL", "LLM_MODEL_NAME", "SUMMARY_ENABLED",
                      "SEARCH_MAX_SYMBOLS", "SLAVIK_USER_ID"):
            assert pc.get(field).secret is False

    def test_no_secrets_among_migratable_non_keys(self):
        for spec in iter_migratable():
            if spec.category == pc.CATEGORY_KEYS:
                continue
            assert not spec.secret, spec.pg_key


class TestPromptsContentPgOnly:
    """84.12.1: промпты — код-каноны (в .env их НЕТ) → PG-only сиды."""

    def test_prompts_are_pg_only_with_code_source(self):
        prompts = [s for s in REGISTRY.values()
                   if s.category == pc.CATEGORY_PROMPTS]
        assert len(prompts) == 10   # + prompts.youtube_video_system_prompt (04.09.2026)
        for spec in prompts:
            assert spec.settings_field is None
            assert spec.env_name is None
            assert spec.code_source is not None
            assert spec.pg_key.startswith("prompts.")

    def test_prompts_not_migratable(self):
        for spec in REGISTRY.values():
            if spec.category == pc.CATEGORY_PROMPTS:
                assert spec not in iter_migratable()

    def test_code_sources_resolve(self):
        for spec in iter_pg_only():
            if spec.code_source is None:
                continue
            module_name, attr = spec.code_source.rsplit(".", 1)
            value = getattr(importlib.import_module(module_name), attr)
            assert isinstance(value, str) and value

    def test_content_key(self):
        spec = pc.get("content.info_how_it_works") or next(
            s for s in REGISTRY.values() if s.pg_key == "content.info_how_it_works")
        assert spec.category == pc.CATEGORY_CONTENT
        assert spec.settings_field is None

    def test_known_pg_keys(self):
        by_key = {s.pg_key: s for s in REGISTRY.values()}
        assert "limits.search_max_symbols" in by_key
        assert "keys.groq_api_key" in by_key
        assert "flags.summary_enabled" in by_key
        assert "models.llm_base_url" in by_key
        assert "reactions.admin_user_id" in by_key
        assert by_key["keys.groq_api_key"].secret


class TestGroups8424:
    """84.24 (02.09.2026): полнота групп и описаний (244 параметра категорий)."""

    def test_every_categorized_param_has_group_and_description(self):
        missing = [
            (s.pg_key, s.category)
            for s in REGISTRY.values()
            if s.category is not None
            and (not s.group or not s.description.strip())
        ]
        assert missing == []

    def test_group_ids_all_valid_and_prefixed(self):
        ids = {g.id for g in GROUPS}
        for s in REGISTRY.values():
            if s.category is not None:
                assert s.group in ids, f"нет группы {s.group} для {s.pg_key}"
                assert s.group.startswith(s.category + "_"), s.group

    def test_group_ids_unique(self):
        ids = [g.id for g in GROUPS]
        assert len(ids) == len(set(ids))

    def test_groups_cover_all_categories_and_count_63(self):
        # 61 (84.24.2 + задачи 1/2 от 2026-09-03) + models_video_summary +
        # reactions_word_reactions (эпик 04.09.2026) + keys_media/content_media
        # (раунд 3, T-687 — медиа-шара); имя актуализировано fix-раундом
        # 04.09 (m7): 61 → 63; фаза 2 (T-755): 63 → 64 (+ memory_infinite);
        # раунд 7 (T-776): 64 → 66 (+ limits_lore, flags_lore — лор чатов)
        assert len(GROUPS) == 66
        categories_in_groups = {g.category for g in GROUPS}
        assert categories_in_groups == set(CATEGORIES)

    def test_orders_unique_within_category(self):
        from collections import Counter
        dup = {k: v for k, v in Counter(
            (g.category, g.order) for g in GROUPS).items() if v > 1}
        assert dup == {}

    def test_group_fields_nonempty(self):
        for g in GROUPS:
            assert g.title_ru.strip()
            assert g.description.strip()
            assert g.order >= 1

    def test_groups_by_category_sorted_and_get_group(self):
        for cat in CATEGORIES:
            lst = pc.groups_by_category(cat)
            assert lst == sorted(lst, key=lambda g: g.order)
            if lst:
                assert pc.get_group(lst[0].id) is lst[0]
        assert pc.get_group("no_such_group") is None
        assert pc.group_order("no_such_group") == 999
        assert pc.group_order("limits_persons") == 1

    def test_group_counts_match_design(self):
        """84.24.2 + дельты (2026-09-03) + эпик 04.09.2026 (модели-видео,
        тумблеры реакций/мимикрии, видео-промпт) + bugfix 04.09.2026
        (limits +2: расшифровка нативных TG-видео) + раунд 3 (медиа-шара:
        keys +1 / limits +6 / content +2 — T-687) + раунд 4 (T-715:
        flags +1 / limits +1 — память-команды) + фаза 2 (T-755:
        memory +1 — бессрочное хранение) + раунд 7 (T-776: limits +8 /
        flags +3 — лор чатов, spec §3.11) + раунд 8 (T-793/T-798/T-801/
        T-803: limits +5 / flags +1 — контекст-слой, spec §3.G2) + раунд 8
        (T-804/T-805/T-808/T-810: limits +5 / flags +1 — уровни конспекта,
        дедуп RAG, purge-гейты, LLM-реранк, spec §3.G2)."""
        counts = {cat: 0 for cat in CATEGORIES}
        for s in REGISTRY.values():
            if s.category is not None:
                counts[s.category] += 1
        assert counts == {"prompts": 10, "models": 29, "keys": 13,
                          "limits": 147, "flags": 48, "reactions": 38,
                          "content": 3, "memory": 1}
        assert {g.category for g in GROUPS} >= set(CATEGORIES)
