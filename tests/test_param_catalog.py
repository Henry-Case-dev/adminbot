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
        #   purge-гейты, LLM-реранк, spec §3.G2) + 15 (раунд 9, T-816/T-817:
        #   RELATIONS_* — отношения, spec §3.6.4) + 14 (раунд 9, T-824/T-825:
        #   DREAM_* — «сон», spec §3.6.4, категория memory) + 17 (раунд 9,
        #   T-826/T-827: NOSTALGIA_* — ностальгия A/B, spec §3.6.4,
        #   категория memory) + 2 (раунд N, T-839: SMARTMODULE_CONCURRENCY_*
        #   — параллельность smart module, группа limits_chat) + 7 (раунд 9,
        #   фикс-раунд: DIG_ENABLED/DIG_PRE_GATE_ENABLED + 5 limits.dig_* —
        #   dig_into_lore, spec §3.6.4) + 9 (раунд 10, F-7 §5.2/F-10 §5.2:
        #   WORKER_BUDGET_TZ, CHAT_GLOBAL_KEY_BUDGET_TOKENS/REQUESTS,
        #   WORKER_DAILY_LLM_CALLS/TOKENS_GLOBAL, _PER_CHAT,
        #   WORKER_PRIORITY_ORDER, WORKER_BUDGET_JITTER_MINUTES)
        #   + PERMSOC_ENABLED (раунд 10, F-9 §3, мастер-тумблер PERMsoc)
        #   + SLAVIK_ENABLED (раунд 10.9, ADR-109-4) + 7 (*_DISPLAY_NAME,
        #   ADR-109-1) = 372
        #   + раунд 10.12 (ADR-1012-1): +5 — EMBEDDING_BASE_URL, EMBEDDING_API_KEY,
        #   OPENROUTER_TRANSCRIBE_DISPLAY_NAME, KOSTIK_REPLIES, KOSTIK_ENABLED
        #   = 377
        #   + раунд 10.13 (F1 cognition-4d-memory, spec §7): +1 —
        #   RAG_STALE_AFTER_DAYS (limits.rag_stale_after_days) = 378
        #   + F2 (cognition-belief-decay, spec §7): +6 — BELIEF_DECAY_ENABLED,
        #   BELIEF_INACTIVITY_DAYS, BELIEF_DECAY_PER_MONTH,
        #   BELIEF_ARCHIVE_THRESHOLD, BELIEF_RESONANCE_PENALTY,
        #   BELIEF_RESONANCE_THRESHOLD = 384
        #   + F3 (cognition-deep-sleep, spec §7): +6 — DEEP_SLEEP_ENABLED,
        #   DEEP_SLEEP_TRIGGER, DEEP_SLEEP_HOUR, DEEP_SLEEP_TOP_K,
        #   DEEP_SLEEP_MAX_PARADIGMS_PER_RUN, DEEP_SLEEP_TOKENS_PER_DAY = 390
        #   + F8 (cognition-irony-dossier, spec §8): +1 —
        #   IRONY_FILTER_ENABLED (flags.irony_filter_enabled) = 391
        #   + F4 (cognition-llm-providers, spec §6): +8 —
        #   INTEL_HISTORY_BASE_URL/MODEL_NAME/DISPLAY_NAME/API_KEY,
        #   INTEL_BG_BASE_URL/MODEL_NAME/DISPLAY_NAME/API_KEY = 399
        #   + F1 (anti-echo-self-reply-round1014, spec §5): +2 —
        #   GRAPH_FACT_WEIGHT_BOT, BOT_SELF_AWARENESS_ENABLED = 401
        #   + F2 (persona-storage-core-round1014, spec §2.4): +1 —
        #   PERSONA_ENABLED = 402 (PERSONA_TRAITS_MAX/PERSONA_TRAIT_MAX_CHARS
        #   — ClassVar, в dataclass.fields не входят).
        #   + F8 (self-reflection-llm-provider-round1014, spec §2.1): +4 —
        #   INTEL_REFLECTION_BASE_URL/MODEL_NAME/DISPLAY_NAME/API_KEY = 406.
        #   + F3 (budget-settings-section, 10.19/ADR-1019-3 D3): +1 —
        #   IMPORT_HISTORY_RETENTION_DAYS (limits_memory, sentinel retention
        #   0=вечно) = 407. CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS — ClassVar
        #   (F4 infra, в dataclass.fields не входит).
        #   + C (lore-compiler-round1020, БЛОК 1/О3): +1 —
        #   LORE_COMPILER_ENABLED (flags_module_direct, default ON) = 409.
        #   + раунд 10.23 (F5/ADR-1023-5 D5): +5 — IMAGE_BASE_URL,
        #   IMAGE_MODEL, IMAGE_GET_MODE, IMAGE_API_KEY,
        #   IMAGE_GENERATION_MODULE_ENABLED = 416.
        #   + раунд 10.24 (F7/ADR-1024-3 D1): +1 — ANTICLICHE_MAX_PATTERNS
        #   (limits.anticliche_max_patterns, default 200) = 417.
        #   + раунд 10.24 (F21/ADR-1024-22 D8): +1 — BUDGETS_ENABLED
        #   (flags.budgets_enabled, default True) = 418.
        #   ANTICLICHE_FIRST_RUN_DELAY_MINUTES — ClassVar (env-only, в
        #   dataclass.fields не входит).
        assert len(fields) == 418
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
        # embed-фоллбэк (раунд 5): тайминги остаются infra (.env).
        # 10.11 (ADR-1011-2): BASE_URL/MODEL/API_KEY/API_KEY_2 переведены в
        # first-class каталог (models/keys) — здесь их больше нет.
        "EMBEDDING_FALLBACK_TIMEOUT_SECONDS",
        "EMBEDDING_FALLBACK_MAX_RETRIES",
        # env-only
        "POSTGRES_DSN", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_USER",
        "WEB_PORT", "LOG_RING_MAX_ENTRIES", "UPTIME_EVENTS_RETENTION_HOURS",
        "SENTRY_DSN", "LOGTAIL_SOURCE_TOKEN", "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH", "COBALT_HTTP_PROXY",
        # 10.18 (F1, ADR-1018-1 D3): US ingest host BetterStack (env-only)
        "BETTERSTACK_HOST",
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
                      "UPTIME_EVENTS_RETENTION_HOURS", "BETTERSTACK_HOST"):
            spec = pc.get(field)
            assert spec is not None
            assert spec.settings_field is None or spec.env_name == field

    def test_betterstack_host_env_only_not_secret(self):
        """F1 (ADR-1018-1 D3): хост BetterStack — env-only, не секрет."""
        spec = pc.get("BETTERSTACK_HOST")
        assert spec is not None
        assert spec.category is None
        assert spec.settings_field is None
        assert spec.secret is False


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
        # раунд 10.12 (OD-1): отдельный ключ primary-эмбеддингов — секрет
        "EMBEDDING_API_KEY",
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
        # + prompts.youtube_video_system_prompt (04.09.2026);
        # + prompts.summary_cover_style (10.23 F6/ADR-1023-6) = 11;
        # + 10 ключей F8 (Stage-1/Stage-2 + режимы Вербализатора) = 21.
        assert len(prompts) == 21
        for spec in prompts:
            assert spec.settings_field is None
            assert spec.env_name is None
            assert spec.code_source is not None
            assert spec.pg_key.startswith("prompts.")

    def test_prompts_not_migratable(self):
        for spec in REGISTRY.values():
            if spec.category == pc.CATEGORY_PROMPTS:
                assert spec not in iter_migratable()

    def test_summary_cover_style_widget_textarea(self):
        """10.23 (F6/ADR-1023-6 §3.2): «Стиль обложки» — widget textarea."""
        spec = pc.get_by_pg_key("prompts.summary_cover_style")
        assert spec is not None
        assert spec.widget == "textarea"
        assert pc.resolve_progressive_level(spec) == "advanced"

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
        # Раунд 10.4 (B-1): flags.chat_context_budgets_enabled — рендер-группа
        # limits_chat_budgets (блок «Прямой чат: бюджеты токенов»; категория
        # и per_chat-семантика ключа НЕ меняются) — единственное исключение.
        NON_PREFIXED = {"flags.chat_context_budgets_enabled": "limits_chat_budgets"}
        for s in REGISTRY.values():
            if s.category is not None:
                assert s.group in ids, f"нет группы {s.group} для {s.pg_key}"
                if s.pg_key in NON_PREFIXED:
                    assert s.group == NON_PREFIXED[s.pg_key], s.pg_key
                else:
                    assert s.group.startswith(s.category + "_"), s.group

    def test_group_ids_unique(self):
        ids = [g.id for g in GROUPS]
        assert len(ids) == len(set(ids))

    def test_groups_cover_all_categories_and_count_63(self):
        # 61 (84.24.2 + задачи 1/2 от 2026-09-03) + models_video_summary +
        # reactions_word_reactions (эпик 04.09.2026) + keys_media/content_media
        # (раунд 3, T-687 — медиа-шара); имя актуализировано fix-раундом
        # 04.09 (m7): 61 → 63; фаза 2 (T-755): 63 → 64 (+ memory_infinite);
        # раунд 7 (T-776): 64 → 66 (+ limits_lore, flags_lore — лор чатов);
        # раунд 9 (T-816/T-817): 66 → 68 (+ limits_relations, flags_relations);
        # раунд 9 (T-824/T-825): 68 → 69 (+ memory_dream — «сон», spec §3.6.4);
        # раунд 9 (T-826/T-827): 69 → 70 (+ memory_nostalgia — «ностальгия»,
        # spec §3.6.4/Q11); раунд 10 (F-10 T-896): 70 → 71 (+ limits_worker —
        # бюджет фона, фикс R3); ре-дизайн 10.2 (BUG-3): 71 → 74
        # (+ flags_permsoc, reactions_permsoc, reactions_admin — «Функции
        # PERMsoc», spec §10 B)
        # ре-дизайн 10.5 (T-1139/T-1145): models +4 — осознанное исключение;
        # раунд 10.6 (T-1201/T-1180): +5 master-флагов; GROUPS 91.
        # раунд 10.9: reactions_persons удалена → GROUPS 90.
        # 10.19 (F3/ADR-1019-3 D2/D3): +2 — limits_chat_key, limits_chat_context
        # (санкция UPD3 п.5) → GROUPS 92.
        # 10.23 (F5/ADR-1023-5 D5): +3 — models_images, keys_images,
        # flags_module_images → GROUPS 95.
        # 10.24 (F7/ADR-1024-3 D1): +1 — limits_anticliche (группа лимита
        # клише, вкладка prompts) → GROUPS 97.
        # 10.24 (F21/ADR-1024-22 D8): +1 — flags_module_budgets (master-группа
        # бюджетов, вкладка mod_budgets) → GROUPS 98.
        assert len(GROUPS) == 98
        categories_in_groups = {g.category for g in GROUPS}
        assert categories_in_groups == set(CATEGORIES)

    def test_orders_unique_within_category(self):
        """Единственные разрешённые совпадения (order) — из таблицы групп
        BUG-3 (spec §10 B): reactions_persons/reactions_admin (order 1) и
        flags_memory/flags_permsoc (order 3) — переезды групп без смещения
        соседей; остальные порядки — строго уникальны."""
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
        assert pc.group_order("limits_alan") == 1

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
        дедуп RAG, purge-гейты, LLM-реранк, spec §3.G2) + раунд 9
        (T-816/T-817: limits +14 / flags +1 — отношения, spec §3.6.4) +
        раунд 9 (T-824/T-825: memory +14 — «сон», spec §3.6.4) +
        раунд 9 (T-826/T-827: memory +17 — «ностальгия» слои A/B, spec
        §3.6.4/Q11) + раунд N (T-839: limits +2 — параллельность smart
        module, группа limits_chat) + раунд 9 (фикс-раунд: limits +5 /
        flags +2 — dig_into_lore, spec §3.6.4/Q11, группы flags_memory/
        limits_memory) + раунд 10 (F-7 §5.2: limits +2 — бюджеты
        глобального ключа; F-10 §5.2: limits +7 — воркер-бюджеты и TZ;
        content +1 — content.no_key_reply). Редизайн 10.5 (T-1139/T-1145):
        models +4 — 2 STT-модели (OD11) + 2 адреса провайдеров (OD16),
        осознанное исключение; GROUPS 74 / Settings 359 не меняются.
        Раунд 10.11 (ADR-1011-2): embed-фоллбэки — sanctioned Δ каталога
        (models +2 / keys +2) без роста REGISTRY 400 и Settings 372
        (перенос записей из infra, не добавление).
        Раунд 10.12 (ADR-1012-1): +5 — models +2 (EMBEDDING_BASE_URL,
        OPENROUTER_TRANSCRIBE_DISPLAY_NAME), keys +1 (EMBEDDING_API_KEY),
        flags +1 (KOSTIK_ENABLED), reactions +1 (KOSTIK_REPLIES).
        Раунд 10.13 (F8): flags +1 (IRONY_FILTER_ENABLED).
        Раунд 10.13 (F4): models +6 / keys +2 (INTEL_HISTORY_*/INTEL_BG_*).
        Раунд 10.14 (F1 anti-echo-self-reply): limits +1
        (GRAPH_FACT_WEIGHT_BOT) / flags +1 (BOT_SELF_AWARENESS_ENABLED).
        Раунд 10.14 (F8 self-reflection): models +3 / keys +1
        (INTEL_REFLECTION_BASE_URL/MODEL_NAME/DISPLAY_NAME/API_KEY).
        Раунд 10.14 (F6 help-guide-integration): content +1
        (content.intelligence_guide, PG-only).
        10.19 (F3/ADR-1019-3 D3, UPD3 п.5): limits +1
        (IMPORT_HISTORY_RETENTION_DAYS, группа limits_memory) → 188.
        10.20 (C/ADR-1020-4 п.5, О3): flags +1
        (LORE_COMPILER_ENABLED, группа flags_module_direct, default ON).
        10.24 (F7/ADR-1024-3 D1): limits +1 (ANTICLICHE_MAX_PATTERNS,
        группа limits_anticliche, default 200) → limits 192.
        10.24 (F21/ADR-1024-22 D8): flags +1 (BUDGETS_ENABLED,
        группа flags_module_budgets, default ON) → flags 67."""
        counts = {cat: 0 for cat in CATEGORIES}
        for s in REGISTRY.values():
            if s.category is not None:
                counts[s.category] += 1
        # 10.23 (F6/ADR-1023-6): prompts +1 (prompts.summary_cover_style).
        # 10.23 (F8/ADR-1023-8, review iter1): prompts +10 (Stage-1/2 + режимы);
        # content без изменений (phantom content.dynamic_cliche_list удалён —
        # F4 хранит клише в PG-таблице, ключ был бы «мёртвой ручкой»).
        assert counts == {"prompts": 21, "models": 56, "keys": 20,
                          "limits": 192, "flags": 67, "reactions": 39,
                          "content": 5, "memory": 34}
        assert {g.category for g in GROUPS} >= set(CATEGORIES)


class TestDigCatalog:
    """Раунд 9 (фикс-раунд major-5, spec §3.6.4/Q11): REGISTRY dig_into_lore —
    2 флага (flags_memory) + 5 лимитов (limits_memory); дефолты Settings ==
    спека; ключи на вкладке «Память и RAG»."""
    EXPECTED_LIMITS = {
        "DIG_MAX_SNIPPETS": 8,
        "DIG_MAX_FACTS": 3,
        "DIG_MAX_SYMBOLS": 3500,
        "DIG_GRAPH_HOP_DEPTH": 2,
        "DIG_YEAR_BACK_WINDOW_DAYS": 2,
    }

    def test_dig_flags_registered_and_defaults(self):
        s = Settings()
        assert s.DIG_ENABLED is True              # Q12/D-11: тул доступен
        assert s.DIG_PRE_GATE_ENABLED is False    # D-11: пре-гейт off
        for field, default in self.EXPECTED_LIMITS.items():
            assert getattr(s, field) == default, field
        flag_keys = [k for k, spec in REGISTRY.items()
                     if spec.group == "flags_memory" and k.startswith("DIG_")]
        assert sorted(flag_keys) == ["DIG_ENABLED", "DIG_PRE_GATE_ENABLED"]
        for field in ("DIG_ENABLED", "DIG_PRE_GATE_ENABLED"):
            spec = pc.get(field)
            assert spec.category == pc.CATEGORY_FLAGS
            assert spec.pg_key == f"flags.{field.lower()}"

    def test_dig_limits_group_memory_and_tab(self):
        for field in self.EXPECTED_LIMITS:
            spec = pc.get(field)
            assert spec is not None and spec.category == pc.CATEGORY_LIMITS
            assert spec.group == "limits_memory"
            assert spec.pg_key == f"limits.{field.lower()}"
        assert pc.group_tab("limits_memory") == pc.TAB_MEMORY_RAG
        assert pc.group_tab("flags_memory") == pc.TAB_MEMORY_RAG

    def test_dream_tick_minutes_replaces_hours(self):
        """D-20: период тика «сна» — минуты (60); старого hours-ключа нет."""
        spec = pc.get("DREAM_TICK_MINUTES")
        assert spec is not None
        assert spec.pg_key == "memory.dream_tick_minutes"
        assert spec.type == "int"
        assert Settings().DREAM_TICK_MINUTES == 60
        assert pc.get("DREAM_TICK_HOURS") is None
        assert pc.get_by_pg_key("memory.dream_tick_hours") is None


class TestPermsocGroupsRedesign:
    """Ре-дизайн 10.2, BUG-3 (spec §10 B): группы «Функции PERMsoc» —
    состав ключей и раскладка по вкладке permsoc; pg-ключи не тронуты."""

    def test_flags_permsoc_keys(self):
        keys = sorted(k for k, spec in REGISTRY.items()
                      if spec.group == "flags_permsoc")
        # 10.9 (ADR-109-4): + SLAVIK_ENABLED — независимый тумблер Славика.
        # 10.12 (ADR-1012-1 D3): + KOSTIK_ENABLED.
        assert keys == ["KOSTIK_ENABLED", "MIMIC_ENABLED", "OLYA_ENABLED",
                        "PERMSOC_ENABLED", "SLAVIK_ENABLED"]
        for field in keys:
            spec = pc.get(field)
            assert spec.category == pc.CATEGORY_FLAGS
            assert spec.pg_key.startswith("flags.")

    def test_reactions_permsoc_keys(self):
        keys = sorted(k for k, spec in REGISTRY.items()
                      if spec.group == "reactions_permsoc")
        assert keys == ["ALAN_MIMIC_ENABLED", "KUCHA_ENABLED"]
        for field in keys:
            spec = pc.get(field)
            assert spec.category == pc.CATEGORY_REACTIONS
            assert spec.pg_key.startswith("reactions.")

    def test_reactions_admin_group_single_key(self):
        keys = [k for k, spec in REGISTRY.items()
                if spec.group == "reactions_admin"]
        assert keys == ["ADMIN_USER_ID"]
        spec = pc.get("ADMIN_USER_ID")
        assert spec.pg_key == "reactions.admin_user_id"

    def test_groups_on_permsoc_tab(self):
        for gid in ("reactions_kostik", "reactions_alan",
                    "reactions_permsoc", "flags_permsoc", "limits_alan",
                    "limits_kostik"):
            assert pc.group_tab(gid) == pc.TAB_PERMSOC, gid
        # 10.9: reactions_persons удалена; ID персон — в блоках владельцев.
        assert pc.get_group("reactions_persons") is None
        assert pc.get("SLAVIK_USER_ID").group == "reactions_slavik"
        assert pc.get("OLYA_USER_ID").group == "reactions_olya"

    def test_group_titles_new(self):
        by_id = {g.id: g for g in GROUPS}
        assert by_id["flags_permsoc"].title_ru == "Функции PERMsoc: рубильники"
        assert by_id["reactions_permsoc"].title_ru == "Персонаж-реакции PERMsoc"
        assert by_id["reactions_admin"].title_ru == "Админ (ID)"