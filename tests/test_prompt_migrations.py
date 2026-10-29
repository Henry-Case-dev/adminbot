"""Раунд 5 (T-740/T-741, spec 5.3.3, FR-D3/FR-D4) — авто-миграция канонов
промптов (services/prompt_migrations.py).

Раунд 8 (T-790, Context-Layer X-Features): direct_chat — три ступени
LEGACY→new, PREV→new, PREV_R8→new (PREV_R8 — слепок канона раунда 5,
HEAD b198d13).

Раунд 9 (AGI Memory, T-821, spec §3.2.2): direct_chat — четвёртая ступень
PREV_R9→new (PREV_R9 — слепок канона раунда 8, HEAD 84c4887).

Покрытие (мок-cache): все 9 ключей PROMPT_MIGRATIONS — prev→new обновляет
(set(key, new, "prompts") + INFO); direct_chat — LEGACY→new, PREV→new,
PREV_R8→new и PREV_R9→new (четыре ступени); current == new → no-op; кастом
юзера → skip + WARNING (не трогаем); None → skip (сид сделает своё); PG down /
cache None → skip; возврат отчёта; prompts.extract_system_prompt НЕ входит;
фиксированный порядок итерации.
"""
import hashlib
import logging

import pytest

from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
    LEGACY_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_CFG07A_SYSTEM_PROMPT,
    PREV_CHAT_MCA23_SYSTEM_PROMPT,
    PREV_CHAT_R1021_SYSTEM_PROMPT,
    PREV_CHAT_R1023_SYSTEM_PROMPT,
    PREV_CHAT_R2020_SYSTEM_PROMPT,
    PREV_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_VERBALIZER_MCA23,
    PREV_CHAT_VERBALIZER_R1023,
    PREV_CHAT_VERBALIZER_W1,
    PREV_CHAT_VERBALIZER_W1_31,
    PREV_CHAT_VERBALIZER_CLAR,
    PREV_CHAT_VERBALIZER_PA5W2,
    PREV_CHAT_W1_SYSTEM_PROMPT,
    PREV_CHAT_W2_SYSTEM_PROMPT,
    PREV_DIRECT_L1_PLANNER_BASE,
    PREV_DIRECT_L1_PLANNER_1021,
    PREV_DIRECT_L1_PLANNER_1022,
    PREV_DIRECT_L1_PLANNER_L1D,
    PREV_DIRECT_L1_PLANNER_CLAR,
    PREV_DIRECT_L1_PLANNER_R3,
    PREV_DIRECT_L1_PLANNER_R3B,
    PREV_DIRECT_L1_PLANNER_P0CS,
    PREV_DIRECT_L1_PLANNER_P0CS2,
    PREV_DIRECT_L1_PLANNER_P0CINT,
    PREV_DIRECT_L1_PLANNER_P0CINTR2,
    PREV_DIRECT_L1_PLANNER_PA5W1,
    PREV_DIRECT_L1_PLANNER_PA5W2,
    PREV_DIRECT_L1_PLANNER_W1,
    PREV_R8_CHAT_SYSTEM_PROMPT,
    PREV_R9_CHAT_SYSTEM_PROMPT,
    PREV_R1022_CHAT_SYSTEM_PROMPT,
)
from services.checkup_prompts import (
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_CFG07A_SYSTEM_PROMPT,
    PREV_CHECKUP_P0_SYSTEM_PROMPT,
    PREV_CHECKUP_R1021_SYSTEM_PROMPT,
    PREV_CHECKUP_SYSTEM_PROMPT,
)
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    FACTCHECK_SYSTEM_PROMPT,
    FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
    PREV_FACTCHECK_ANALYST_R1023,
    PREV_FACTCHECK_ANALYST_R1023_F2,
    PREV_FACTCHECK_ANALYST_R1023_F3,
    PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT,
    PREV_FACTCHECK_R1021_SYSTEM_PROMPT,
    PREV_FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT,
    PREV_FACTCHECK_VERBALIZER_W1,
)
from services.prompt_migrations import (
    PROMPT_MIGRATIONS,
    ROLLBACK_MIGRATIONS,
    migrate_prompt_canons,
    rollback_prompt_canons,
)
from services.search_prompts import (
    PREV_R1022_SEARCH_SYSTEM_PROMPT,
    PREV_SEARCH_CFG07A_SYSTEM_PROMPT,
    PREV_SEARCH_R1021_SYSTEM_PROMPT,
    PREV_SEARCH_SYSTEM_PROMPT,
    SEARCH_SYSTEM_PROMPT,
)
from services.summary_prompts import (
    COMPRESS_PROMPT,
    PREV_COMPRESS_PROMPT,
    PREV_R1021_SUMMARY_SYSTEM_PROMPT,
    PREV_R1022_SUMMARY_SYSTEM_PROMPT,
    PREV_R2020_SUMMARY_SYSTEM_PROMPT,
    PREV_SUMMARY_CFG07A_SYSTEM_PROMPT,
    PREV_SUMMARY_EDITOR_R1023,
    PREV_SUMMARY_EDITOR_R1023_F3,
    PREV_SUMMARY_EDITOR_R1023_F6,
    PREV_SUMMARY_EDITOR_R1025_HOTFIX4,
    PREV_SUMMARY_L1_CLUSTERIZER_R1026,
    PREV_SUMMARY_L1_CLUSTERIZER_R1027,
    PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41,
    PREV_SUMMARY_L2_WRITER_R1026,
    PREV_SUMMARY_L2_WRITER_R1027,
    PREV_SUMMARY_L2_WRITER_R1028,
    PREV_SUMMARY_L2_WRITER_R1028_ASAP4,
    PREV_SUMMARY_L2_WRITER_R1029_ASAP41,
    PREV_SUMMARY_L2_WRITER_R1030_P0,
    PREV_SUMMARY_NARRATOR_R1023,
    PREV_SUMMARY_NARRATOR_R1028,
    PREV_SUMMARY_NARRATOR_LEGFIX,
    PREV_SUMMARY_SYSTEM_R1028,
    PREV_SUMMARY_SYSTEM_PROMPT,
    SUMMARY_EDITOR_SYSTEM_PROMPT,
    SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
    SUMMARY_L2_WRITER_SYSTEM_PROMPT,
    SUMMARY_NARRATOR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from services.web_prompts import (
    PREV_R1022_WEBPAGE_SYSTEM_PROMPT,
    PREV_WEBPAGE_CFG07A_SYSTEM_PROMPT,
    PREV_WEBPAGE_R1021_SYSTEM_PROMPT,
    PREV_WEBPAGE_SYSTEM_PROMPT,
    WEBPAGE_SYSTEM_PROMPT,
)
from services.youtube_prompts import (
    PREV_R1022_YOUTUBE_SYSTEM_PROMPT,
    PREV_R1022_YOUTUBE_VIDEO_SYSTEM_PROMPT,
    PREV_YOUTUBE_CFG07A_SYSTEM_PROMPT,
    PREV_YOUTUBE_R1021_SYSTEM_PROMPT,
    PREV_YOUTUBE_SYSTEM_PROMPT,
    PREV_YOUTUBE_VIDEO_CFG07A_SYSTEM_PROMPT,
    PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT,
    PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT,
    YOUTUBE_SYSTEM_PROMPT,
    YOUTUBE_VIDEO_SYSTEM_PROMPT,
)

_ALL_KEYS = [
    "prompts.direct_chat_system_prompt",
    # MCA-23 (Wave 3, §11): первые ступени ключа Вербализатора direct.
    "prompts.direct_chat_verbalizer_system_prompt",
    # ASAP 7 (F1, §1.3): новый ключ L1 Planner Direct (PG-ключ сидит F2).
    "prompts.direct_l1_planner_system_prompt",
    "prompts.summary_system_prompt",
    "prompts.compress_system_prompt",
    "prompts.checkup_system_prompt",
    "prompts.factcheck_system_prompt",
    "prompts.search_system_prompt",
    "prompts.youtube_system_prompt",
    "prompts.youtube_video_system_prompt",
    "prompts.webpage_system_prompt",
    # Раунд 10.23 (F1, ADR-1023-1): Stage-1 промпты (PG-ключи создаёт F8).
    "prompts.summary_editor_system_prompt",
    "prompts.factcheck_analyst_system_prompt",
    # ASAP W1 (P0-F «точечно», SOUL1-CLOSE-R1 04.3): первая ступень ключа
    # Вербализатора фактчека.
    "prompts.factcheck_verbalizer_system_prompt",
    # Раунд 10.26 (S3, ADR-1026-5 D4): новый ключ L1-Кластеризатора.
    "prompts.summary_l1_clusterizer_system_prompt",
    # Раунд 10.26 (S5, ADR-1026-7 D3/D4): новый ключ L2-Писателя.
    "prompts.summary_l2_writer_system_prompt",
    # ASAP-2.1 (round1028, контракт g): Narrator получает ступени миграции.
    "prompts.summary_narrator_system_prompt",
]
# ВНИМАНИЕ: порядок _ALL_KEYS == порядку объявления PROMPT_MIGRATIONS
# (test_iteration_order_is_fixed); фактчек-вербализатор сидит после
# factcheck_analyst.

# prev-эталон (слепок HEAD 68fb03e) для каждой ступени — первая пара.
_PREV_BY_KEY: dict[str, str] = {
    "prompts.direct_chat_system_prompt": PREV_CHAT_SYSTEM_PROMPT,
    # MCA-23: слепок базы канона Вербализатора 10.23 (без типографики).
    "prompts.direct_chat_verbalizer_system_prompt":
        PREV_CHAT_VERBALIZER_R1023,
    # ASAP 7 (F1): слепок базы канона L1 Planner (без правил).
    "prompts.direct_l1_planner_system_prompt": PREV_DIRECT_L1_PLANNER_BASE,
    "prompts.summary_system_prompt": PREV_SUMMARY_SYSTEM_PROMPT,
    "prompts.compress_system_prompt": PREV_COMPRESS_PROMPT,
    "prompts.checkup_system_prompt": PREV_CHECKUP_SYSTEM_PROMPT,
    "prompts.factcheck_system_prompt": PREV_FACTCHECK_SYSTEM_PROMPT,
    "prompts.search_system_prompt": PREV_SEARCH_SYSTEM_PROMPT,
    "prompts.youtube_system_prompt": PREV_YOUTUBE_SYSTEM_PROMPT,
    "prompts.youtube_video_system_prompt": PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT,
    "prompts.webpage_system_prompt": PREV_WEBPAGE_SYSTEM_PROMPT,
    # Раунд 10.23 (F1): слепок прод-канона Stage-1 промптов ДО F1.
    "prompts.summary_editor_system_prompt": PREV_SUMMARY_EDITOR_R1023,
    "prompts.factcheck_analyst_system_prompt": PREV_FACTCHECK_ANALYST_R1023,
    # Раунд 10.26 (S3): слепок базы канона L1 ДО правила маркировки.
    "prompts.summary_l1_clusterizer_system_prompt":
        PREV_SUMMARY_L1_CLUSTERIZER_R1026,
    # Раунд 10.26 (S5): слепок базы канона L2 ДО правила маркировки.
    "prompts.summary_l2_writer_system_prompt": PREV_SUMMARY_L2_WRITER_R1026,
    # ASAP-2.1 (round1028, контракт g): слепок прод-канона Рассказчика ДО правки.
    "prompts.summary_narrator_system_prompt": PREV_SUMMARY_NARRATOR_R1023,
    # ASAP W1 (P0-F «точечно»): слепок прод-канона Вербализатора фактчека
    # 2.58.110 (с identity-фразой).
    "prompts.factcheck_verbalizer_system_prompt":
        PREV_FACTCHECK_VERBALIZER_W1,
}

# new-канон (раунд 5) для каждого ключа.
_NEW_BY_KEY: dict[str, str] = {
    "prompts.direct_chat_system_prompt": CHAT_SYSTEM_PROMPT,
    # MCA-23: канон Вербализатора без unconditional cap-правила.
    "prompts.direct_chat_verbalizer_system_prompt":
        DIRECT_VERBALIZER_SYSTEM_PROMPT,
    # ASAP 7 (F1): канон L1 Planner (планировщик, не писатель).
    "prompts.direct_l1_planner_system_prompt":
        DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    "prompts.summary_system_prompt": SYSTEM_PROMPT,
    "prompts.compress_system_prompt": COMPRESS_PROMPT,
    "prompts.checkup_system_prompt": CHECKUP_SYSTEM_PROMPT,
    "prompts.factcheck_system_prompt": FACTCHECK_SYSTEM_PROMPT,
    "prompts.search_system_prompt": SEARCH_SYSTEM_PROMPT,
    "prompts.youtube_system_prompt": YOUTUBE_SYSTEM_PROMPT,
    "prompts.youtube_video_system_prompt": YOUTUBE_VIDEO_SYSTEM_PROMPT,
    "prompts.webpage_system_prompt": WEBPAGE_SYSTEM_PROMPT,
    # Раунд 10.23 (F1): Stage-1 каноны с правилом маркировки.
    "prompts.summary_editor_system_prompt": SUMMARY_EDITOR_SYSTEM_PROMPT,
    "prompts.factcheck_analyst_system_prompt": FACTCHECK_ANALYST_SYSTEM_PROMPT,
    # Раунд 10.26 (S3): канон L1 с правилом маркировки.
    "prompts.summary_l1_clusterizer_system_prompt":
        SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
    # Раунд 10.26 (S5): канон L2 с правилом маркировки.
    "prompts.summary_l2_writer_system_prompt": SUMMARY_L2_WRITER_SYSTEM_PROMPT,
    # ASAP-2.1 (round1028, контракт g): канон Рассказчика (§25 — шиза —
    # творческое решение модели).
    "prompts.summary_narrator_system_prompt": SUMMARY_NARRATOR_SYSTEM_PROMPT,
    # ASAP W1 (P0-F «точечно»): канон Вербализатора фактчека без identity.
    "prompts.factcheck_verbalizer_system_prompt":
        FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
}

# Слепки прод-канона раунда 10.21 (F2+F3) — для новой ступени.
_PREV_R1021_BY_KEY: dict[str, str] = {
    "prompts.direct_chat_system_prompt": PREV_CHAT_R1021_SYSTEM_PROMPT,
    "prompts.summary_system_prompt": PREV_R1021_SUMMARY_SYSTEM_PROMPT,
    "prompts.checkup_system_prompt": PREV_CHECKUP_R1021_SYSTEM_PROMPT,
    "prompts.factcheck_system_prompt": PREV_FACTCHECK_R1021_SYSTEM_PROMPT,
    "prompts.search_system_prompt": PREV_SEARCH_R1021_SYSTEM_PROMPT,
    "prompts.youtube_system_prompt": PREV_YOUTUBE_R1021_SYSTEM_PROMPT,
    "prompts.youtube_video_system_prompt": PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT,
    "prompts.webpage_system_prompt": PREV_WEBPAGE_R1021_SYSTEM_PROMPT,
}
# compress в 10.21 не менялся — ступени/отката для него нет.
# Раунд 10.23 (F1): в ROLLBACK добавлены ключи Stage-1 промптов (цель — слепок
# R1023; PG-ключи создаёт F8); цели существующих ключей R1021 не меняются.
# MCA-23 (Wave 3): direct-ключи — цель отката НЕПОСРЕДСТВЕННО прежний канон
# (снимается только ступень MCA-23; ADR-1013-3).
_ROLLBACK_KEYS = [
    "prompts.direct_chat_system_prompt",
    "prompts.direct_chat_verbalizer_system_prompt",
    # ASAP W1 (P0-G/P0-F): откат L1-планера и Вербализатора фактчека
    # (позиция — по порядку объявления ROLLBACK_MIGRATIONS).
    "prompts.direct_l1_planner_system_prompt",
    "prompts.factcheck_verbalizer_system_prompt",
    # R1021-ключи (direct_chat уже выписан выше — без дубля).
    *list(_PREV_R1021_BY_KEY)[1:],
    "prompts.summary_editor_system_prompt",
    "prompts.factcheck_analyst_system_prompt",
    # Раунд 10.26 (S3, ADR-1026-5 D4): откат ключа L1.
    "prompts.summary_l1_clusterizer_system_prompt",
    # Раунд 10.26 (S5, ADR-1026-7 D4): откат ключа L2.
    "prompts.summary_l2_writer_system_prompt",
    # ASAP-2.1 (round1028, контракт g): откат ключа Narrator.
    "prompts.summary_narrator_system_prompt",
]
_ROLLBACK_TARGET_BY_KEY: dict[str, str] = {
    **dict(_PREV_R1021_BY_KEY),
    # F1 (10.23, R1023F1-07): чат откатывался на канон R1023 (снимает только
    # F1). MCA-23 (Wave 3): откат снимал ТОЛЬКО ступень MCA-23 →
    # НЕПОСРЕДСТВЕННО прежний прод-канон PREV_CHAT_MCA23.
    # CFG-07A-2 (20.10.2026): откат ведёт на НЕПОСРЕДСТВЕННЫЙ прежний
    # прод-канон 2.58.100 (MCA-23-композиция; снимается только ступень
    # CFG-07A; стек ступеней цел — ADR-1013-3, как у C14 фактчека).
    # POST-ASAP5 W2 (27.10.2026): первый откат снимает секцию «ПОИСК И
    # НЕПОДТВЕРЖДЁННЫЕ ХАРАКТЕРИСТИКИ» → байты W1 (PREV_CHAT_W2_SYSTEM_
    # PROMPT); стек ступеней цел.
    "prompts.direct_chat_system_prompt": PREV_CHAT_W2_SYSTEM_PROMPT,
    # MCA-23 (§11): откат Вербализатора direct → прод-канон 10.23 (с cap).
    # ASAP W1 (22.10.2026): откат → прод-канон 2.58.110 (d0ef0d376fc3).
    # ASAP 2 (23.10.2026): откат снимает ТОЛЬКО ступень уточнений → канон
    # W1 §3.1 (прод 2.58.111, be03964322aa); стек ступеней цел.
    # SPEECH-CANON R3b (23.10.2026): откат снимает ТОЛЬКО ступень R3b →
    # канон 2.58.113 (§3.1 + абзацы §4.2).
    # POST-ASAP5 W2 (27.10.2026): первый откат снимает секцию расчётов →
    # байты R3b (PREV_CHAT_VERBALIZER_PA5W2, 83ff62bbee40).
    "prompts.direct_chat_verbalizer_system_prompt":
        PREV_CHAT_VERBALIZER_PA5W2,
    # ASAP W1 (P0-G, §3.7): откат → прод-канон L1D 2.58.110 (ace6246bd360).
    # ASAP 2 (23.10.2026): откат снимает ТОЛЬКО ступень уточнений → канон
    # W1 (прод 2.58.111, f8ab20121c02); стек ступеней цел.
    # SPEECH-INIT-FIX R3 (23.10.2026): откат снимает ТОЛЬКО ступень R3 →
    # непосредственный прод-канон 2.58.113 (канон W1 + контракт уточнений).
    # SPEECH-CANON R3b (23.10.2026): откат снимает ТОЛЬКО ступень R3b →
    # канон R3 (база R3 + контракт §4.1 + правила).
    # P0-CORRECTIVE (25.10.2026): верхняя ступень — смысловая маршрутизация
    # L1; откат снимает только её → текущие активные байты P0CS. Ред.2:
    # первый откат снимает приоритет разбора → P0CS2 (f6f5d3b1fc1d).
    # POST-ASAP5 W1 (27.10.2026): первый откат снимает секцию «ИЗМЕНЕНИЕ
    # ЗАДАЧИ И ВОЗРАЖЕНИЯ» → байты ред.4 (PREV_DIRECT_L1_PLANNER_PA5W1,
    # 422e9d73d316).
    # POST-ASAP5 W2 (27.10.2026): первый откат снимает семантику поиска в
    # правиле 4 → байты ред.5 (PREV_DIRECT_L1_PLANNER_PA5W2, 902dd00edf52).
    "prompts.direct_l1_planner_system_prompt": PREV_DIRECT_L1_PLANNER_PA5W2,
    # ASAP W1 (P0-F «точечно»): откат → прод-канон 2.58.110 (с identity).
    "prompts.factcheck_verbalizer_system_prompt":
        PREV_FACTCHECK_VERBALIZER_W1,
    # ASAP-2.1 (round1028, контракт g): откат Legacy Single вёл на канон
    # 2.58.33 (PREV_SUMMARY_SYSTEM_R1028).
    # CFG-07A-2: откат → НЕПОСРЕДСТВЕННО прежний прод-канон 2.58.100
    # (PREV_SUMMARY_CFG07A; снимается только ступень CFG-07A).
    "prompts.summary_system_prompt": PREV_SUMMARY_CFG07A_SYSTEM_PROMPT,
    # F6 (10.23): откат Редактора снимает ступень cover_prompt → канон F3.
    # hotfix4 (10.25, T-2511): откат снимает ТОЛЬКО ступень HOTFIX4 (разрешение
    # короткого заголовка) → слепок канона F6 (жёсткий запрет надписей).
    "prompts.summary_editor_system_prompt": PREV_SUMMARY_EDITOR_R1025_HOTFIX4,
    # UNIFIED-CORE (C14, 20.10.2026): откат фактчека — НЕПОСРЕДСТВЕННО прежний
    # прод-канон (с обходом safety, релиз 2.58.97); стек ступеней цел.
    "prompts.factcheck_system_prompt":
        PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT,
    # CFG-07A-2 (20.10.2026, ADR-1013-3): откаты 6 канонов НЕ-фактчек
    # маршрутов — НЕПОСРЕДСТВЕННО прежний прод-канон 2.58.100
    # (PREV_*_CFG07A; снимается только ступень CFG-07A).
    # P0-CHECKUP (24.10.2026): откат снимает ТОЛЬКО новую ступень P0 — на
    # прод-канон 2.58.118 (PREV_CHECKUP_P0, 38d63d86b54d).
    "prompts.checkup_system_prompt": PREV_CHECKUP_P0_SYSTEM_PROMPT,
    "prompts.search_system_prompt": PREV_SEARCH_CFG07A_SYSTEM_PROMPT,
    "prompts.youtube_system_prompt": PREV_YOUTUBE_CFG07A_SYSTEM_PROMPT,
    "prompts.youtube_video_system_prompt":
        PREV_YOUTUBE_VIDEO_CFG07A_SYSTEM_PROMPT,
    "prompts.webpage_system_prompt": PREV_WEBPAGE_CFG07A_SYSTEM_PROMPT,
    # UNIFIED-CORE (C13): откат Аналитика снимает только ступень C13 (мёртвый
    # tone_hint) → непосредственный прежний прод-канон с полем.
    "prompts.factcheck_analyst_system_prompt":
        PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT,
    # S3 (10.26): откат L1 снимает ступень маркировки → слепок базы канона S3.
    # ASAP-2 (round1027, контракт l): откат снимает ступень R1027 →
    # непосредственный прежний канон R1026 (PREV_*_R1027 = база+блок).
    # ASAP 4.1 волна 3 (T-4607, ADR-1028-8 D3): откат map-канона →
    # непосредственный прежний прод-канон 2.58.46 (PREV_*_R1027_ASAP41).
    "prompts.summary_l1_clusterizer_system_prompt":
        PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41,
    # S5 (10.26): откат L2 снимает ступень маркировки → слепок базы канона S5.
    # ASAP-2: откат ступени R1027 (ДЛИНА/ДЕДУП/авторы) → канон R1026.
    # ASAP-2.1 (round1028): откат ступени R1028 → НЕПОСРЕДСТВЕННО прежний
    # канон PREV_*_R1028 (контракт (g)).
    # ASAP-4 (волна D, ADR-1028-7 D4): откат ступени R1029 prose-first →
    # непосредственный прежний прод-канон PREV_*_R1028_ASAP4 (запрет цитат).
    # ASAP 4.1 волна 3 (T-4609, ADR-1028-8 D4/AM-4): откат блока источника →
    # канон R1029 (прод 2.58.46).
    # SPEECH-P0-B2 (25.10.2026): верхняя ступень — фактологический канон;
    # первый откат снимает только её → прод-байты 2.58.130 (R1030), второй —
    # историческую ступень источника (R1029).
    "prompts.summary_l2_writer_system_prompt":
        PREV_SUMMARY_L2_WRITER_R1030_P0,
    # ASAP-2.1 (round1028): откат Рассказчика → прежний канон R1028.
    # LEGFIX (22.10.2026): откат снимает ТОЛЬКО ступень LEGFIX →
    # непосредственный прежний канон (слепок PREV_*_LEGFIX).
    "prompts.summary_narrator_system_prompt": PREV_SUMMARY_NARRATOR_LEGFIX,
}


class FakeCache:
    """Фейковый ConfigCache-контракт: pg_available, sync get, async set.
    Хранит dict значений по ключам (get вне словаря → None)."""

    def __init__(self, values=None, pg_available=True):
        self.pg_available = pg_available
        self.values = dict(values or {})
        self.set_calls = []
        self.provenance_sets = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        # P0-PROMPTS (24.10.2026): миграция дополнительно пишет журнал
        # провенанса (`character.prompt_history`). Он не является записью
        # канона: учитываем отдельно, чтобы проверки порядка/набора канонов
        # оставались точными.
        if key == "character.prompt_history":
            self.provenance_sets.append((key, value, category))
            self.values[key] = value
            return
        self.set_calls.append((key, value, category))
        self.values[key] = value

    def apply_writes(self):
        for key, value, _cat in self.set_calls:
            self.values[key] = value
        self.set_calls.clear()


class TestPromptMigrationsCatalog:
    def test_all_expected_keys_present(self):
        assert list(PROMPT_MIGRATIONS) == _ALL_KEYS

    def test_no_extract_key(self):
        """prompts.extract_system_prompt НЕ входит (EXTRACT_PROMPT не трогаем)."""
        assert "prompts.extract_system_prompt" not in PROMPT_MIGRATIONS

    def test_direct_chat_ten_steps_legacy_prev_r8_r9_r2020(self):
        """Раунд 10.21/10.22: ступени PREV_CHAT_R1021 и PREV_R1022 → канон
        (блоки A/B); прежние ступени сохранены и указывают на тот же новый
        канон. MCA-23 (§10): ступень прод-канона 10.21/10.23 (с cap) →
        канон MCA23. CFG-07A-2: ступень прод-канона 2.58.100 (MCA23-
        композиция) → чистый канон (честный слив + контракт пометок)."""
        from services.chat_prompts import (
            PREV_CHAT_CFG07A_SYSTEM_PROMPT,
            PREV_R1022_CHAT_SYSTEM_PROMPT,
        )
        steps = PROMPT_MIGRATIONS["prompts.direct_chat_system_prompt"]
        assert steps == [(LEGACY_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_R8_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_R9_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_CHAT_R2020_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_CHAT_R1021_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_R1022_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_CHAT_R1023_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_CHAT_MCA23_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         (PREV_CHAT_CFG07A_SYSTEM_PROMPT,
                          CHAT_SYSTEM_PROMPT),
                         # ASAP W1 (P0-F, §3.6): прод-канон 2.58.110 →
                         # канон с ролевым блоком владельца.
                         (PREV_CHAT_W1_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
                         # POST-ASAP5 W2 (§5.2/§5.3/§10.5): прод-канон после
                         # W1 → канон с секцией «ПОИСК И НЕПОДТВЕРЖДЁННЫЕ
                         # ХАРАКТЕРИСТИКИ».
                         (PREV_CHAT_W2_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT)]

    def test_w1_steps_present(self):
        """ASAP W1 (22.10.2026, §3.1-3.7): ступени прод-канонов 2.58.110
        (tool phase/L2 writer/L1) и первая ступень Вербализатора фактчека."""
        from services.chat_prompts import PREV_DIRECT_L1_PLANNER_L1D
        from services.factcheck_prompts import (
            FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
            PREV_FACTCHECK_VERBALIZER_W1,
        )
        assert (PREV_CHAT_W1_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT) in \
            PROMPT_MIGRATIONS["prompts.direct_chat_system_prompt"]
        assert (PREV_CHAT_VERBALIZER_W1,
                DIRECT_VERBALIZER_SYSTEM_PROMPT) in \
            PROMPT_MIGRATIONS["prompts.direct_chat_verbalizer_system_prompt"]
        assert (PREV_DIRECT_L1_PLANNER_L1D,
                DIRECT_L1_PLANNER_SYSTEM_PROMPT) in \
            PROMPT_MIGRATIONS["prompts.direct_l1_planner_system_prompt"]
        assert PROMPT_MIGRATIONS["prompts.factcheck_verbalizer_system_prompt"] \
            == [(PREV_FACTCHECK_VERBALIZER_W1,
                 FACTCHECK_VERBALIZER_SYSTEM_PROMPT)]

    def test_catalog_points_to_new_canons(self):
        """new во всех ступенях == канону раунда 5 (байт-сверка со спека)."""
        for key, steps in PROMPT_MIGRATIONS.items():
            for _prev, new in steps:
                assert new == _NEW_BY_KEY[key]

    def test_prev_snapshots_differ_from_new(self):
        for key in _ALL_KEYS:
            assert _PREV_BY_KEY[key] != _NEW_BY_KEY[key]


# ═══════════════════════════════════════════════════════════════════════════
# EVOL-016/012 (30.10.2026, решение владельца 29.10.2026): строковые ступени
# и барьер «кастом юзера — НЕ трогаем» СНЯТЫ. Активацию решает релизная
# политика (метка заводской ревизии + печать, журнал версий/активаций):
#   * старт (migrate_prompt_canons) — делегатор apply_release (cutover);
#   * любая устаревшая редакция (LEGACY/PREV_*) — просто снимок legacy в
#     журнале, активной становится ТЕКУЩАЯ заводская ревизия по метке;
#   * рестарт без новой метки не меняет ничего;
#   * rollback_prompt_canons/migrate_core_owner_patch — отказ без записи.
# Слепки PREV_* и карты PROMPT_MIGRATIONS/ROLLBACK_MIGRATIONS сохранены как
# БАЙТ-ЭТАЛОНЫ (тестируются словарные тесты выше) — не как механизм.
# ═══════════════════════════════════════════════════════════════════════════

from services import prompt_registry as pr
from services import prompt_release_policy as prp


@pytest.fixture()
def journal(monkeypatch):
    """Memory-стор журнала как default_journal (юнит-контур без PG)."""
    store = prp.MemoryPromptJournal()
    monkeypatch.setattr(prp, "default_journal", lambda cache=None: store)
    yield store
    pr.set_release_policy_active(False)
    from services import prompt_factory as _pf
    _pf._HISTORY_FROZEN = False
    pr.reset_cache()


def _factory(key: str) -> str:
    """Текущий заводской текст PG-ключа (единый источник — реестр)."""
    spec = pr.by_pg_key(key)
    assert spec is not None, key
    return pr.factory_text(spec.block_id)


class TestMigratePromptCanons:
    """Стартовая проводка релизной политики (бывшая канон-миграция)."""

    @pytest.mark.asyncio
    async def test_all_stale_values_updated_to_current_factory(self, journal):
        """Cutover: любое устаревшее значение → снимок legacy + заводская."""
        cache = FakeCache(values=dict(_PREV_BY_KEY))
        report = await migrate_prompt_canons(cache)
        cache.apply_writes()
        for key in _ALL_KEYS:
            assert report.get(key) in ("updated", "same"), (key, report)
            assert cache.values[key] == _factory(key), key
            # прежние байты сохранены как неизменяемая ревизия legacy
            legacy = [r for r in journal.revisions.values()
                      if r.pg_key == key and r.origin == "legacy"
                      and r.content_sha12 == pr.sha12(_PREV_BY_KEY[key])]
            assert len(legacy) == 1, key

    @pytest.mark.asyncio
    async def test_stale_canons_activate_current_factory_revision(
            self, journal):
        """Любой устаревший канон (LEGACY/R8/R9/R2020/MCA23) — не «ступень»,
        а просто прежнее значение: активна ТЕКУЩАЯ заводская ревизия."""
        for stale in (LEGACY_CHAT_SYSTEM_PROMPT, PREV_R8_CHAT_SYSTEM_PROMPT,
                      PREV_R9_CHAT_SYSTEM_PROMPT,
                      PREV_CHAT_R2020_SYSTEM_PROMPT,
                      PREV_CHAT_MCA23_SYSTEM_PROMPT):
            store = prp.MemoryPromptJournal()
            monkey_store = store
            prp_default = prp.default_journal
            prp.default_journal = lambda cache=None, _s=monkey_store: _s
            try:
                key = "prompts.direct_chat_system_prompt"
                cache = FakeCache(values={key: stale})
                await migrate_prompt_canons(cache)
                cache.apply_writes()
                assert cache.values[key] == _factory(key), type(stale)
                legacy = [r for r in store.revisions.values()
                          if r.pg_key == key and r.origin == "legacy"
                          and r.content_sha12 == pr.sha12(stale)]
                assert len(legacy) == 1, type(stale)
            finally:
                prp.default_journal = prp_default
                pr.set_release_policy_active(False)

    @pytest.mark.asyncio
    async def test_already_new_canons_restart_is_full_noop(self, journal):
        """Рестарт с той же заводской ревизией: ни записи значения, ни строк."""
        cache = FakeCache(values=dict(_NEW_BY_KEY))
        await migrate_prompt_canons(cache)
        cache.apply_writes()
        first = (len(journal.activations), len(journal.revisions),
                 len(cache.set_calls))
        report = await migrate_prompt_canons(cache)
        assert all(v == "same" for v in report.values())
        assert (len(journal.activations), len(journal.revisions),
                len(cache.set_calls)) == first
        assert cache.values == dict(_NEW_BY_KEY) or all(
            cache.values[key] == _NEW_BY_KEY.get(key, cache.values[key])
            for key in _NEW_BY_KEY)

    @pytest.mark.asyncio
    async def test_custom_value_becomes_legacy_snapshot_no_warning(
            self, journal, caplog):
        """EVOL-012: кастом владельца — ревизия legacy, заводская активна,
        никакого WARN «кастом юзера — НЕ трогаем»."""
        cache = FakeCache(values={
            "prompts.direct_chat_system_prompt": "мой кастомный промпт",
            "prompts.summary_system_prompt": "ещё один кастом",
        })
        with caplog.at_level(logging.WARNING,
                             logger="services.prompt_migrations"):
            report = await migrate_prompt_canons(cache)
        cache.apply_writes()
        assert report["prompts.direct_chat_system_prompt"] == "updated"
        assert cache.values["prompts.direct_chat_system_prompt"] == \
            _factory("prompts.direct_chat_system_prompt")
        barrier = [r for r in caplog.records
                   if "НЕ трогаем" in r.message or "кастом" in r.message]
        assert barrier == []

    @pytest.mark.asyncio
    async def test_missing_keys_activated_not_deferred_to_seed(self, journal):
        """Пустой ключ: skipped_empty (автор не выдумывается), затем активация
        заводской ревизии — сид больше не ожидается поставить канон."""
        cache = FakeCache(values={})
        report = await migrate_prompt_canons(cache)
        cache.apply_writes()
        empty = [a for a in journal.activations
                 if a.kind == "legacy_import" and a.outcome == "skipped_empty"]
        assert len(empty) >= len(_ALL_KEYS)
        for key in _ALL_KEYS:
            assert cache.values[key] == _factory(key), key
            assert report.get(key) in ("updated", "same"), key

    @pytest.mark.asyncio
    async def test_pg_unavailable_skipped(self, caplog):
        """PG/журнал недоступен → skip (активация из констант запрещена)."""
        cache = FakeCache(values=dict(_PREV_BY_KEY), pg_available=False)
        with caplog.at_level(logging.INFO,
                             logger="services.prompt_release_policy"):
            report = await migrate_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []
        assert any("skip" in r.message and "недоступен" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_none_cache_skipped(self, caplog):
        with caplog.at_level(logging.INFO,
                             logger="services.prompt_release_policy"):
            report = await migrate_prompt_canons(None)
        assert report == {}
        assert any("skip" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_iteration_order_is_fixed(self, journal):
        """Порядок применения — детерминированный (обход sorted по block_id,
        отчёт в ключах pg_key; порядок повторного прогона идентичен)."""
        cache = FakeCache(values=dict(_PREV_BY_KEY))
        report = await migrate_prompt_canons(cache)
        block_order = [
            pr.by_pg_key(key).block_id for key in report
            if pr.by_pg_key(key) is not None]
        assert block_order == sorted(block_order)
        report2 = await migrate_prompt_canons(cache)
        assert list(report2) == list(report)


class TestRound1021Migration:
    """F2+F3 (раунд 10.21): карты слепков сохранены как байт-эталоны;
    исполнение ступеней снято (откат — через журнал ревизий)."""

    def test_rollback_keys_match_r1021_keys(self):
        assert list(ROLLBACK_MIGRATIONS) == _ROLLBACK_KEYS

    def test_r1021_prev_step_present_for_each_key(self):
        for key, prev in _PREV_R1021_BY_KEY.items():
            assert (prev, _NEW_BY_KEY[key]) in PROMPT_MIGRATIONS[key]

    def test_rollback_map_points_new_to_prev(self):
        for key, target in _ROLLBACK_TARGET_BY_KEY.items():
            # первая ступень цепочки — по-прежнему непосредственный канон
            assert ROLLBACK_MIGRATIONS[key][0] == (_NEW_BY_KEY[key], target)

    def test_compress_not_in_rollback(self):
        assert "prompts.compress_system_prompt" not in ROLLBACK_MIGRATIONS

    @pytest.mark.asyncio
    async def test_r1021_snapshots_update_to_current_factory(self, journal):
        cache = FakeCache(values=dict(_PREV_R1021_BY_KEY))
        report = await migrate_prompt_canons(cache)
        cache.apply_writes()
        for key in _PREV_R1021_BY_KEY:
            assert cache.values[key] == _factory(key), key
            assert report.get(key) in ("updated", "same"), key

    @pytest.mark.asyncio
    async def test_rollback_refuses_without_writes(self, caplog):
        """Откат лестницей снят: ERROR и отказ, БД не пишется (EVOL-016)."""
        cache = FakeCache(values=dict(_NEW_BY_KEY))
        with caplog.at_level(logging.ERROR,
                             logger="services.prompt_migrations"):
            report = await rollback_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []
        assert any("отказ" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_rollback_idempotent(self):
        cache = FakeCache(values=dict(_PREV_R1021_BY_KEY))
        report = await rollback_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_rollback_custom_untouched(self, caplog):
        """Кастом владельца более не предмет «отката лестницей»: отказ целиком."""
        cache = FakeCache(values={"prompts.factcheck_system_prompt": "мой кастом"})
        with caplog.at_level(logging.ERROR,
                             logger="services.prompt_migrations"):
            report = await rollback_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []
        assert any("отказ" in r.message for r in caplog.records)
        assert not any("кастом юзера — НЕ трогаем" in r.message
                       for r in caplog.records)

    @pytest.mark.asyncio
    async def test_rollback_pg_down_skipped(self, caplog):
        cache = FakeCache(values=dict(_NEW_BY_KEY), pg_available=False)
        with caplog.at_level(logging.ERROR,
                             logger="services.prompt_migrations"):
            report = await rollback_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []
        assert any("отказ" in r.message for r in caplog.records)


class TestRound1023Migration:
    """F1 (раунд 10.23, ADR-1023-1): слепки PREV_*_R1023 и ключи Stage-1."""

    def test_chat_r1023_step_present(self):
        assert (PREV_CHAT_R1023_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT) in \
            PROMPT_MIGRATIONS["prompts.direct_chat_system_prompt"]

    def test_stage1_keys_migrate_from_r1023(self):
        assert (PREV_SUMMARY_EDITOR_R1023, SUMMARY_EDITOR_SYSTEM_PROMPT) in \
            PROMPT_MIGRATIONS["prompts.summary_editor_system_prompt"]
        assert (PREV_FACTCHECK_ANALYST_R1023,
                FACTCHECK_ANALYST_SYSTEM_PROMPT) in \
            PROMPT_MIGRATIONS["prompts.factcheck_analyst_system_prompt"]

    def test_r1023_snapshots_differ_from_new(self):
        assert PREV_SUMMARY_EDITOR_R1023 != SUMMARY_EDITOR_SYSTEM_PROMPT
        assert PREV_FACTCHECK_ANALYST_R1023 != FACTCHECK_ANALYST_SYSTEM_PROMPT
        assert PREV_CHAT_R1023_SYSTEM_PROMPT != CHAT_SYSTEM_PROMPT

    def test_rollback_targets_r1023_for_stage1_keys(self):
        # hotfix4 (10.25, T-2511): непосредственный прежний канон Редактора —
        # слепок HOTFIX4 (канон F6 с жёстким запретом надписей); каждая
        # обратная ступень снимает ровно одну предыдущую.
        assert ROLLBACK_MIGRATIONS["prompts.summary_editor_system_prompt"] == [(
            SUMMARY_EDITOR_SYSTEM_PROMPT, PREV_SUMMARY_EDITOR_R1025_HOTFIX4)]
        # UNIFIED-CORE (C13, 20.10.2026): откат Аналитика снимает ступень C13
        # (мёртвый tone_hint) — на непосредственный прежний прод-канон.
        assert ROLLBACK_MIGRATIONS["prompts.factcheck_analyst_system_prompt"] == [(
            FACTCHECK_ANALYST_SYSTEM_PROMPT,
            PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT)]

    def test_rollback_chat_targets_pre_mca23(self):
        """MCA-23 (Wave 3): откат чата вёл на канон ДО MCA-23.
        CFG-07A-2 (ADR-1013-3): откат — на НЕПОСРЕДСТВЕННО прежний
        прод-канон 2.58.100. ASAP W1: откат — на прод-канон 2.58.110
        (PREV_CHAT_W1; снимается только ступень W1, стек ступеней цел).
        POST-ASAP5 W2: первый откат снимает секцию поиска → байты W1
        (PREV_CHAT_W2), второй — до 2.58.110."""
        assert ROLLBACK_MIGRATIONS["prompts.direct_chat_system_prompt"] == [
            (CHAT_SYSTEM_PROMPT, PREV_CHAT_W2_SYSTEM_PROMPT),
            (PREV_CHAT_W2_SYSTEM_PROMPT, PREV_CHAT_W1_SYSTEM_PROMPT)]

    @pytest.mark.asyncio
    async def test_rollback_refuses_journal_restore_instead(self, journal, caplog):
        """Байты прежнего канона возвращаются ЖУРНАЛОМ (activate_revision),
        а не лестницей; прямой rollback_prompt_canons — отказ."""
        cache = FakeCache(values={
            "prompts.direct_chat_system_prompt": CHAT_SYSTEM_PROMPT})
        with caplog.at_level(logging.ERROR,
                             logger="services.prompt_migrations"):
            report = await rollback_prompt_canons(cache)
        assert report == {}
        assert cache.set_calls == []
        # журнал: прежние байты — восстанавливаемая ревизия (manual)
        rev = prp.RevisionRow(
            revision_id=pr.revision_id_for(
                "direct.base.tool_phase", "global", None, "manual",
                pr.sha12(PREV_CHAT_W2_SYSTEM_PROMPT)),
            block_id="direct.base.tool_phase", scope="global",
            origin="manual", content_sha12=pr.sha12(PREV_CHAT_W2_SYSTEM_PROMPT),
            body=PREV_CHAT_W2_SYSTEM_PROMPT,
            pg_key="prompts.direct_chat_system_prompt")
        await journal.insert_revision(rev)
        res = await prp.activate_revision(
            "direct.base.tool_phase", rev.revision_id, cache=cache,
            store=journal, actor="runbook")
        assert res["applied"]
        cache.apply_writes()
        assert cache.values["prompts.direct_chat_system_prompt"] == \
            PREV_CHAT_W2_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_r1023_snapshots_update_and_rollback(self, journal):
        values = {
            "prompts.direct_chat_system_prompt": PREV_CHAT_R1023_SYSTEM_PROMPT,
            "prompts.summary_editor_system_prompt": PREV_SUMMARY_EDITOR_R1023,
            "prompts.factcheck_analyst_system_prompt":
                PREV_FACTCHECK_ANALYST_R1023,
        }
        cache = FakeCache(values=dict(values))
        report = await migrate_prompt_canons(cache)
        cache.apply_writes()
        for key in values:
            assert cache.values[key] == _factory(key), key
            assert report.get(key) in ("updated", "same"), key
        rollback_cache = FakeCache(values={
            "prompts.summary_editor_system_prompt": SUMMARY_EDITOR_SYSTEM_PROMPT,
            "prompts.factcheck_analyst_system_prompt":
                FACTCHECK_ANALYST_SYSTEM_PROMPT,
        })
        rollback = await rollback_prompt_canons(rollback_cache)
        assert rollback == {}                    # лестница снята
        assert rollback_cache.set_calls == []


class TestMca23Migration:
    """MCA-23 (Wave 3, §10/§11): слепки канонов — байт-эталоны; активация —
    релизная политика, откат — журнал ревизий."""

    def test_verbalizer_key_steps(self):
        steps = PROMPT_MIGRATIONS[
            "prompts.direct_chat_verbalizer_system_prompt"]
        assert steps == [
            (PREV_CHAT_VERBALIZER_R1023, DIRECT_VERBALIZER_SYSTEM_PROMPT),
            (PREV_CHAT_VERBALIZER_MCA23, DIRECT_VERBALIZER_SYSTEM_PROMPT),
            # ASAP W1 (P0-A, §3.1): прод-канон 2.58.110 → канон владельца.
            (PREV_CHAT_VERBALIZER_W1, DIRECT_VERBALIZER_SYSTEM_PROMPT),
            # ASAP 2 (23.10.2026, §4.2): канон W1 §3.1 (прод 2.58.111)
            # → канон с абзацами уточнений в «КАК ПИСАТЬ».
            (PREV_CHAT_VERBALIZER_W1_31, DIRECT_VERBALIZER_SYSTEM_PROMPT),
            # SPEECH-CANON R3b (23.10.2026): канон 2.58.113 → канон с одной
            # узкой инструкцией о честной границе истории.
            (PREV_CHAT_VERBALIZER_CLAR, DIRECT_VERBALIZER_SYSTEM_PROMPT),
            # POST-ASAP5 W2 (§4/§6): канон R3b → канон с секцией
            # «ТЕХНИЧЕСКИЕ РАСЧЁТЫ И ГИПОТЕЗЫ».
            (PREV_CHAT_VERBALIZER_PA5W2, DIRECT_VERBALIZER_SYSTEM_PROMPT)]

    def test_mca23_snapshots_differ_from_new(self):
        assert PREV_CHAT_MCA23_SYSTEM_PROMPT != CHAT_SYSTEM_PROMPT
        assert PREV_CHAT_VERBALIZER_MCA23 != DIRECT_VERBALIZER_SYSTEM_PROMPT
        # слепки содержат прежний cap-текст, новый канон — нет
        assert "одно-два предложения" in PREV_CHAT_VERBALIZER_MCA23
        assert "одно-два предложения" not in DIRECT_VERBALIZER_SYSTEM_PROMPT
        assert "СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" \
            in PREV_CHAT_MCA23_SYSTEM_PROMPT
        assert "СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" \
            not in CHAT_SYSTEM_PROMPT

    def test_verbalizer_rollback_targets_r1023_full(self):
        """MCA-23: откат снимал ступень MCA-23 → прод-канон 10.23.
        ASAP W1: откат — на НЕПОСРЕДСТВЕННЫЙ прежний прод-канон 2.58.110
        (PREV_CHAT_VERBALIZER_W1, d0ef0d376fc3).
        ASAP 2 (23.10.2026): откат снимает ТОЛЬКО ступень уточнений →
        канон W1 §3.1 (прод 2.58.111, PREV_CHAT_VERBALIZER_W1_31).
        SPEECH-CANON R3b: откат снимает ТОЛЬКО ступень R3b → канон 2.58.113
        (§3.1 + абзацы §4.2, PREV_CHAT_VERBALIZER_CLAR).
        POST-ASAP5 W2: первый откат снимает секцию расчётов → байты R3b
        (PREV_CHAT_VERBALIZER_PA5W2, 83ff62bbee40)."""
        assert ROLLBACK_MIGRATIONS[
            "prompts.direct_chat_verbalizer_system_prompt"] == [
                (DIRECT_VERBALIZER_SYSTEM_PROMPT,
                 PREV_CHAT_VERBALIZER_PA5W2),
                (PREV_CHAT_VERBALIZER_PA5W2, PREV_CHAT_VERBALIZER_CLAR)]

    @pytest.mark.asyncio
    async def test_r3b_rollback_chain_restores_258113_bytes(self, journal):
        """REL-F1 (24.10.2026), переписан на EVOL-016: байты 2.58.113
        восстанавливаются ЖУРНАЛОМ ревизий, а не лестницей.

        Байт-эталоны сохранены: текущие каноны L1 ``14743d28`` / L2
        ``f5c4807d``, целевые байты отката 2.58.113 — L1 ``c987c03e`` /
        L2 ``d1b210c1``. Лестница больше не исполняется (отказ без записи);
        повторный deploy снова активирует новые каноны; кастом владельца
        вне журнала не перетирается.
        """
        l1_key = "prompts.direct_l1_planner_system_prompt"
        l2_key = "prompts.direct_chat_verbalizer_system_prompt"
        l1_block = "direct.base.l1_planner"
        l2_block = "direct.base.l2_writer"

        def sha12(text: str) -> str:
            return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

        # «копия текущих значений» после boot-проводки
        cache = FakeCache(values={l1_key: DIRECT_L1_PLANNER_SYSTEM_PROMPT,
                                  l2_key: DIRECT_VERBALIZER_SYSTEM_PROMPT})
        assert (sha12(cache.values[l1_key]), sha12(cache.values[l2_key])) == \
            ("14743d288ea3", "f5c4807d088e")

        # лестница снята: любые вызовы — отказ без записи
        assert await rollback_prompt_canons(cache) == {}
        assert cache.set_calls == []

        # журнал: прежние байты 2.58.113 — восстанавливаемые ревизии
        for block_id, key, prev in ((l1_block, l1_key,
                                     PREV_DIRECT_L1_PLANNER_CLAR),
                                    (l2_block, l2_key,
                                     PREV_CHAT_VERBALIZER_CLAR)):
            await journal.insert_revision(prp.RevisionRow(
                revision_id=pr.revision_id_for(block_id, "global", None,
                                               "manual", pr.sha12(prev)),
                block_id=block_id, scope="global", origin="manual",
                content_sha12=pr.sha12(prev), body=prev, pg_key=key))
        for block_id, key, prev in ((l1_block, l1_key,
                                     PREV_DIRECT_L1_PLANNER_CLAR),
                                    (l2_block, l2_key,
                                     PREV_CHAT_VERBALIZER_CLAR)):
            rev = await journal.get_revision(
                pr.revision_id_for(block_id, "global", None, "manual",
                                   pr.sha12(prev)))
            res = await prp.activate_revision(block_id, rev.revision_id,
                                              cache=cache, store=journal,
                                              actor="runbook")
            assert res["applied"] and res["activation_kind"] == "manual_rollback"
        cache.apply_writes()
        assert cache.values[l1_key] == PREV_DIRECT_L1_PLANNER_CLAR
        assert cache.values[l2_key] == PREV_CHAT_VERBALIZER_CLAR
        assert (sha12(cache.values[l1_key]), sha12(cache.values[l2_key])) == \
            ("c987c03e3ee0", "d1b210c156c8")
        assert (len(cache.values[l1_key]), len(cache.values[l2_key])) == \
            (6542, 2827)

        # повторный deploy: релизная политика снова активирует новые каноны
        store2 = prp.MemoryPromptJournal()
        prp_default = prp.default_journal
        prp.default_journal = lambda cache=None, _s=store2: _s
        try:
            report = await migrate_prompt_canons(cache)
            cache.apply_writes()
            assert report[l1_key] == "updated" and report[l2_key] == "updated"
            assert cache.values[l1_key] == DIRECT_L1_PLANNER_SYSTEM_PROMPT
            assert cache.values[l2_key] == DIRECT_VERBALIZER_SYSTEM_PROMPT
        finally:
            prp.default_journal = prp_default
            pr.set_release_policy_active(False)

        # кастом владельца вне журнала: лестницей не трогался и раньше,
        # теперь отказ получает вся операция отката — байты не меняются
        custom = FakeCache(values={
            l1_key: PREV_DIRECT_L1_PLANNER_R3 + " правка владельца",
            l2_key: DIRECT_VERBALIZER_SYSTEM_PROMPT})
        assert await rollback_prompt_canons(custom) == {}
        assert custom.set_calls == []

    @pytest.mark.asyncio
    async def test_pre_mca23_canon_activates_current_factory(self, journal):
        """Прод на каноне 10.21/10.23 → активна ТЕКУЩАЯ заводская ревизия."""
        cache = FakeCache(values={
            "prompts.direct_chat_system_prompt":
                PREV_CHAT_MCA23_SYSTEM_PROMPT})
        report = await migrate_prompt_canons(cache)
        cache.apply_writes()
        assert cache.values["prompts.direct_chat_system_prompt"] == \
            _factory("prompts.direct_chat_system_prompt")
        assert report["prompts.direct_chat_system_prompt"] == "updated"

    @pytest.mark.asyncio
    async def test_verbalizer_prev_values_activate_current_factory(
            self, journal):
        """Оба прод-значения 10.23 (база и полный канон) → текущий канон."""
        for prev in (PREV_CHAT_VERBALIZER_R1023, PREV_CHAT_VERBALIZER_MCA23):
            store = prp.MemoryPromptJournal()
            prp_default = prp.default_journal
            prp.default_journal = lambda cache=None, _s=store: _s
            try:
                key = "prompts.direct_chat_verbalizer_system_prompt"
                cache = FakeCache(values={key: prev})
                report = await migrate_prompt_canons(cache)
                cache.apply_writes()
                assert cache.values[key] == \
                    _factory("prompts.direct_chat_verbalizer_system_prompt")
                assert report[key] == "updated"
            finally:
                prp.default_journal = prp_default
                pr.set_release_policy_active(False)

    @pytest.mark.asyncio
    async def test_verbalizer_custom_becomes_legacy_snapshot(self, journal):
        cache = FakeCache(values={
            "prompts.direct_chat_verbalizer_system_prompt":
                "мой кастомный вербализатор"})
        report = await migrate_prompt_canons(cache)
        cache.apply_writes()
        key = "prompts.direct_chat_verbalizer_system_prompt"
        assert cache.values[key] == _factory(key)
        assert report[key] == "updated"

    @pytest.mark.asyncio
    async def test_resolve_after_migration_gives_new_canon(self, journal,
                                                           monkeypatch):
        """resolve после проводки: hot-слой отдаёт текущий заводской канон.

        SOUL-1 (W1, §1.2/§7.2): effective-значение проходит реестр речевых
        инструкций — известные сегменты legacy-личности вычищаются на сборке.
        Проверяется АКТИВНАЯ ревизия (текущий канон, не PREV).
        """
        from services import hot_config as hot
        from services.prompt_style_blocks import resolve_prompt
        key = "prompts.direct_chat_verbalizer_system_prompt"
        for prev in (PREV_CHAT_VERBALIZER_R1023, PREV_CHAT_VERBALIZER_MCA23,
                     PREV_CHAT_VERBALIZER_W1):
            fresh = prp.MemoryPromptJournal()
            monkeypatch.setattr(prp, "default_journal",
                                lambda cache=None, _s=fresh: _s)
            cache = FakeCache(values={key: prev})
            await migrate_prompt_canons(cache)
            # FakeCache.set не мутирует values — воспроизводим запись в PG.
            for _key, _value, _cat in cache.set_calls:
                cache.values[_key] = _value
            hot.set_config_cache(cache)
            try:
                resolved = resolve_prompt(key, "CODE_DEFAULT")
                assert resolved == DIRECT_VERBALIZER_SYSTEM_PROMPT
                assert resolved != prev
                assert "бот-абьюзер" not in resolved
            finally:
                hot.set_config_cache(None)
            pr.set_release_policy_active(False)

    @pytest.mark.asyncio
    async def test_verbalizer_missing_key_activated(self, journal):
        """Пустой ключ → skipped_empty + активация заводской ревизии."""
        cache = FakeCache(values={})
        report = await migrate_prompt_canons(cache)
        cache.apply_writes()
        key = "prompts.direct_chat_verbalizer_system_prompt"
        assert cache.values[key] == _factory(key)
        assert report[key] in ("updated", "same")

    @pytest.mark.asyncio
    async def test_verbalizer_rollback_and_reapply(self, journal, caplog):
        """Откат/повторное применение через журнал (лестница снята)."""
        key = "prompts.direct_chat_verbalizer_system_prompt"
        block_id = "direct.base.l2_writer"
        cache = FakeCache(values={key: DIRECT_VERBALIZER_SYSTEM_PROMPT})
        with caplog.at_level(logging.ERROR,
                             logger="services.prompt_migrations"):
            report = await rollback_prompt_canons(cache)
        assert report == {} and cache.set_calls == []
        assert any("отказ" in r.message for r in caplog.records)
        # журнал: канон W1 §3.1 — восстанавливаемая ревизия
        await journal.insert_revision(prp.RevisionRow(
            revision_id=pr.revision_id_for(block_id, "global", None, "manual",
                                           pr.sha12(PREV_CHAT_VERBALIZER_W1_31)),
            block_id=block_id, scope="global", origin="manual",
            content_sha12=pr.sha12(PREV_CHAT_VERBALIZER_W1_31),
            body=PREV_CHAT_VERBALIZER_W1_31, pg_key=key))
        rev = await journal.get_revision(
            pr.revision_id_for(block_id, "global", None, "manual",
                               pr.sha12(PREV_CHAT_VERBALIZER_W1_31)))
        res = await prp.activate_revision(block_id, rev.revision_id,
                                          cache=cache, store=journal,
                                          actor="runbook")
        assert res["applied"]
        cache.apply_writes()
        assert cache.values[key] == PREV_CHAT_VERBALIZER_W1_31
