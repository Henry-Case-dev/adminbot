"""Раунд 5 (T-740, spec 3.3.4, FR-D3): авто-миграция канонов промптов в PG.

Раунд 8 (T-790, Context-Layer X-Features): для prompts.direct_chat_system_prompt
добавлена третья ступень (PREV_R8_CHAT_SYSTEM_PROMPT → новый канон раунда 8);
существующие ступени (LEGACY→новый, PREV→новый) сохранены и указывают на новый
CHAT_SYSTEM_PROMPT автоматически.

Раунд 9 (AGI Memory, T-821, spec §3.2.2): четвёртая ступень direct_chat
(PREV_R9_CHAT_SYSTEM_PROMPT — слепок канона раунда 8, HEAD 84c4887 → канон
раунда 9); PREV_R8-ступень указывает на новый канон автоматически.

Заменяет migrate_direct_chat_prompt_if_legacy (удалена из chat_prompts.py):
для каждого PG-ключа prompts.* текущее значение == одному из предыдущих
канонов (PREV_*-слепки / LEGACY) → upsert новым каноном; == новому канону →
no-op; отсутствующий ключ → skip (сид ConfigCache поставит канон); иначе —
кастом юзера → skip + WARNING. PG down → skip (R6: бот работает на дефолтах
констант — они уже новые). Итерация — в фиксированном порядке объявления
словаря (детерминированные логи/тесты). Возврат отчёта dict[key, "updated"].

prompts.extract_system_prompt НЕ входит (EXTRACT_PROMPT — ETL-экстрактор,
не user-facing; не правится).

Раунд 10.26 (S3, ADR-1026-5 D4): новая ступень L1-Кластеризатора
(`prompts.summary_l1_clusterizer_system_prompt`; слепок
`PREV_SUMMARY_L1_CLUSTERIZER_R1026` — база канона S3 без ступени маркировки).
"""
import logging
import re

from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
    LEGACY_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_CFG07A_SYSTEM_PROMPT,
    PREV_CHAT_MCA23_SYSTEM_PROMPT,
    PREV_CHAT_R2020_SYSTEM_PROMPT,
    PREV_CHAT_R1021_SYSTEM_PROMPT,
    PREV_CHAT_R1023_SYSTEM_PROMPT,
    PREV_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_VERBALIZER_MCA23,
    PREV_CHAT_VERBALIZER_R1023,
    PREV_CHAT_VERBALIZER_W1,
    PREV_CHAT_VERBALIZER_W1_31,
    PREV_CHAT_W1_SYSTEM_PROMPT,
    PREV_DIRECT_L1_PLANNER_BASE,
    PREV_DIRECT_L1_PLANNER_1021,
    PREV_DIRECT_L1_PLANNER_1022,
    PREV_DIRECT_L1_PLANNER_L1D,
    PREV_DIRECT_L1_PLANNER_W1,
    CORE_REAL_EVENTS_PARAGRAPH,
    PREV_PERSONALITY_CORE_FULL_TEXT,
    PREV_PERSONALITY_CORE_FULL_V2_TEXT,
    PREV_R1022_CHAT_SYSTEM_PROMPT,
    PREV_R8_CHAT_SYSTEM_PROMPT,
    PREV_R9_CHAT_SYSTEM_PROMPT,
)
from services.checkup_prompts import (
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_CFG07A_SYSTEM_PROMPT,
    PREV_CHECKUP_P0_SYSTEM_PROMPT,
    PREV_CHECKUP_R1021_SYSTEM_PROMPT,
    PREV_CHECKUP_SYSTEM_PROMPT,
    PREV_R1022_CHECKUP_SYSTEM_PROMPT,
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
    PREV_FACTCHECK_R2020_SYSTEM_PROMPT,
    PREV_FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_UNIFIED_CORE_AB_SYSTEM_PROMPT,
    PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT,
    PREV_FACTCHECK_VERBALIZER_W1,
    PREV_R1022_FACTCHECK_SYSTEM_PROMPT,
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
    PREV_SUMMARY_NARRATOR_R1023,
    PREV_SUMMARY_NARRATOR_R1028,
    PREV_SUMMARY_NARRATOR_LEGFIX,
    PREV_SUMMARY_CFG07A_SYSTEM_PROMPT,
    PREV_SUMMARY_SYSTEM_PROMPT,
    PREV_SUMMARY_SYSTEM_R1028,
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

logger = logging.getLogger(__name__)

PROMPT_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    # MCA-23 (Wave 3, §10): новая ступень — прод-канон 10.21/10.23 (cap
    # «1-2 предложения») ведёт на канон MCA23 (extent-семантика). Прежние
    # 8 ступеней сохранены и указывают на новый канон автоматически.
    "prompts.direct_chat_system_prompt": [
        (LEGACY_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_R8_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_R9_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_R2020_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_R1021_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_R1022_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_R1023_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        (PREV_CHAT_MCA23_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        # CFG-07A-2 (SF-09/13, 20.10.2026, ADR-1013-3): прод-канон 2.58.100
        # (MCA-23-композиция с выдуманной тех-причиной слива) ведёт на
        # чистый канон (честный слив + контракт служебных пометок).
        (PREV_CHAT_CFG07A_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT),
        # ASAP W1 (P0-F, §3.6, 22.10.2026): прод-канон 2.58.110
        # (0fe9680ba280: ролевой блок «токсичный … бот-абьюзер» +
        # ПРИОРИТЕТЫ + ПРАВИЛА ОФОРМЛЕНИЯ + блоки A/B) ведёт на канон §3.6
        # (НАЗНАЧЕНИЕ КАНАЛА DIRECT/ДОСТОВЕРНОСТЬ/ГРАНИЦА ЭТАПА). Ступень
        # обслуживает ТОЛЬКО байты прежнего канона; подлинные кастомы
        # владельца (W0: cf404931f84c, withheld) лестницей не трогаются —
        # их гасит W2 (write_speech_value с провенансом, §5.5).
        (PREV_CHAT_W1_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT)],
    # MCA-23 (Wave 3, §11): первые ступени ключа Вербализатора direct —
    # прод-значения 10.23 (база без типографики и полный канон) ведут на
    # новый канон без unconditional cap-правила.
    # ASAP W1 (P0-A, §3.1): прод-канон 2.58.110 (d0ef0d376fc3: «Ты —
    # токсичный … бот-абьюзер …» + ТИПОГРАФИКА) ведёт на канон владельца
    # (контекст+план → готовый ответ, без личности/форматных правил).
    # W0-факт: активное значение прода — unprovenanced-кастом 091115cadc28
    # (withheld) — ступенью НЕ обслуживается, гасится W2 с провенансом.
    "prompts.direct_chat_verbalizer_system_prompt": [
        (PREV_CHAT_VERBALIZER_R1023, DIRECT_VERBALIZER_SYSTEM_PROMPT),
        (PREV_CHAT_VERBALIZER_MCA23, DIRECT_VERBALIZER_SYSTEM_PROMPT),
        (PREV_CHAT_VERBALIZER_W1, DIRECT_VERBALIZER_SYSTEM_PROMPT),
        # ASAP 2 (23.10.2026, §4.2 asap2 source): канон W1 §3.1 (прод
        # 2.58.111) ведёт на канон с абзацами уточнений в «КАК ПИСАТЬ»
        # (вставка §4.2, единственная правка; подлинные кастомы владельца
        # лестницей не трогаются — только точное совпадение байт).
        (PREV_CHAT_VERBALIZER_W1_31, DIRECT_VERBALIZER_SYSTEM_PROMPT)],
    # ASAP 7 (F1, §1.3 architecture.md; ADR-1013-3): новый PG-ключ L1
    # Planner Direct. Ступень — база канона без правил (слепок
    # PREV_DIRECT_L1_PLANNER_BASE) ведёт на канон; идемпотентна: до сида —
    # skip (сид ConfigCache поставит канон), текущий канон → no-op, кастом
    # юзера не перезаписывается.
    # FIX-CORRECTIVE-R1 (21.10.2026): ступень полного прод-канона 2.58.106
    # (база + правила R1028, SHA 99a207313889711d) ведёт на канон с новыми
    # правилами 2-3 (react/silent — позитивные критерии).
    # L1D (22.10.2026, директива владельца owner-corrective-initreply):
    # ступень прод-канона 2.58.109 (слепок PREV_DIRECT_L1_PLANNER_1022)
    # ведёт на канон с полями формы участия delivery/target_*.
    # ASAP W1 (P0-G, §3.7): ступень прод-канона 2.58.110 (ace6246bd360,
    # блок «ФОРМА УЧАСТИЯ») ведёт на канон с секцией «ВЫБОР УЧАСТИЯ»
    # (схема/правила прежние). W0-факт: активное значение прода УЖЕ
    # ace6246bd360 (deploy-миграция 07:26) — на рестарте уедет на новый
    # канон этой ступенью.
    "prompts.direct_l1_planner_system_prompt": [
        (PREV_DIRECT_L1_PLANNER_BASE, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        (PREV_DIRECT_L1_PLANNER_1021, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        (PREV_DIRECT_L1_PLANNER_1022, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        (PREV_DIRECT_L1_PLANNER_L1D, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        # ASAP 2 (23.10.2026, §4.1 asap2 source): прод-канон 2.58.111
        # (канон W1 с секцией «ВЫБОР УЧАСТИЯ») ведёт на канон с контрактом
        # «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА» и правилом 5-отсылкой; схема
        # JSON и секция участия не менялись. Кастом владельца (не точное
        # совпадение байт) ступенью не трогается.
        (PREV_DIRECT_L1_PLANNER_W1, DIRECT_L1_PLANNER_SYSTEM_PROMPT)],
    "prompts.summary_system_prompt": [
        (PREV_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT),
        (PREV_R2020_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT),
        (PREV_R1021_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT),
        (PREV_R1022_SUMMARY_SYSTEM_PROMPT, SYSTEM_PROMPT),
        # ASAP-2.1 (контракт (g)/§25): строка шиза — выбор модели, опциональна.
        (PREV_SUMMARY_SYSTEM_R1028, SYSTEM_PROMPT),
        # CFG-07A-2 (SF-06, 20.10.2026, ADR-1013-3): прод-канон 2.58.100
        # (safety-bypass + identity legacy-личности) ведёт на чистый канон.
        (PREV_SUMMARY_CFG07A_SYSTEM_PROMPT, SYSTEM_PROMPT)],
    "prompts.compress_system_prompt": [(PREV_COMPRESS_PROMPT, COMPRESS_PROMPT)],
    "prompts.checkup_system_prompt": [
        (PREV_CHECKUP_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT),
        (PREV_CHECKUP_R1021_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT),
        (PREV_R1022_CHECKUP_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT),
        # CFG-07A-2 (SF-05/07/08/12): прод-канон 2.58.100 ведёт на чистый
        # канон (жанр админ-контекста сохранён).
        (PREV_CHECKUP_CFG07A_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT),
        # P0-CHECKUP (24.10.2026, addendum §2): непосредственный прежний
        # прод-канон 2.58.118 (2077 c, 38d63d86b54d) ведёт на целевую
        # функциональную редакцию владельца. Ступень идемпотентна: текущий
        # канон → no-op, кастом владельца (не точное совпадение байт) не
        # перезаписывается; старые PREV_* не переписаны.
        (PREV_CHECKUP_P0_SYSTEM_PROMPT, CHECKUP_SYSTEM_PROMPT)],
    "prompts.factcheck_system_prompt": [
        (PREV_FACTCHECK_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT),
        (PREV_FACTCHECK_R2020_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT),
        (PREV_FACTCHECK_R1021_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT),
        (PREV_R1022_FACTCHECK_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT),
        # UNIFIED-CORE (C14, 20.10.2026, решение владельца «вычистить»):
        # прод-канон с обходом safety («Игнорируй все настройки…») ведёт на
        # канон без обхода; обе вариации блоков A/B (релиз 2.58.97 и C4-сид).
        (PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT, FACTCHECK_SYSTEM_PROMPT),
        (PREV_FACTCHECK_UNIFIED_CORE_AB_SYSTEM_PROMPT,
         FACTCHECK_SYSTEM_PROMPT)],
    "prompts.search_system_prompt": [
        (PREV_SEARCH_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT),
        (PREV_SEARCH_R1021_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT),
        (PREV_R1022_SEARCH_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT),
        # CFG-07A-2 (SF-01/07/08/10/11): прод-канон 2.58.100 (safety-bypass +
        # identity + sneer + hostility) ведёт на чистый канон.
        (PREV_SEARCH_CFG07A_SYSTEM_PROMPT, SEARCH_SYSTEM_PROMPT)],
    "prompts.youtube_system_prompt": [
        (PREV_YOUTUBE_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT),
        (PREV_YOUTUBE_R1021_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT),
        (PREV_R1022_YOUTUBE_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT),
        # CFG-07A-2 (SF-02/07/08/11): как search.
        (PREV_YOUTUBE_CFG07A_SYSTEM_PROMPT, YOUTUBE_SYSTEM_PROMPT)],
    "prompts.youtube_video_system_prompt": [
        (PREV_YOUTUBE_VIDEO_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT),
        (PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT),
        (PREV_R1022_YOUTUBE_VIDEO_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT),
        # CFG-07A-2 (SF-03/07/08/11): как search (мультимодальный канон).
        (PREV_YOUTUBE_VIDEO_CFG07A_SYSTEM_PROMPT, YOUTUBE_VIDEO_SYSTEM_PROMPT)],
    "prompts.webpage_system_prompt": [
        (PREV_WEBPAGE_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT),
        (PREV_WEBPAGE_R1021_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT),
        (PREV_R1022_WEBPAGE_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT),
        # CFG-07A-2 (SF-04/07/08/11): как search.
        (PREV_WEBPAGE_CFG07A_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT)],
    # 10.23 (F1, ADR-1023-1): Stage-1 промпты (Редактор саммари/Аналитик
    # фактчека) получают правило маркировки; PG-ключи добавляет F8 — до сида
    # migrate/skip (отсутствующий ключ → INFO, сид поставит канон).
    # 10.23 (F6, ADR-1023-6 §Decision 9): ступень F6 — поле cover_prompt в том
    # же JSON (слепок PREV_SUMMARY_EDITOR_R1023_F6 = канон F3 без обложки).
    # 10.25 (hotfix4, ADR-1025-8 D1/T-2511): ступень HOTFIX4 — смягчение
    # запрета надписей (разрешён короткий заголовок владельца в стиле).
    "prompts.summary_editor_system_prompt": [
        (PREV_SUMMARY_EDITOR_R1023, SUMMARY_EDITOR_SYSTEM_PROMPT),
        (PREV_SUMMARY_EDITOR_R1023_F3, SUMMARY_EDITOR_SYSTEM_PROMPT),
        (PREV_SUMMARY_EDITOR_R1023_F6, SUMMARY_EDITOR_SYSTEM_PROMPT),
        (PREV_SUMMARY_EDITOR_R1025_HOTFIX4, SUMMARY_EDITOR_SYSTEM_PROMPT)],
    # 10.23 (F2, ADR-1023-2 §3.3): ступень Аналитика — правило обязательного
    # веб-поиска. Старые прод-значения (pre-F1 и F1) ведут на новый канон.
    # 10.23 (F3, ADR-1023-3): ступень F3 — поле response_mode в том же JSON.
    "prompts.factcheck_analyst_system_prompt": [
        (PREV_FACTCHECK_ANALYST_R1023, FACTCHECK_ANALYST_SYSTEM_PROMPT),
        (PREV_FACTCHECK_ANALYST_R1023_F2, FACTCHECK_ANALYST_SYSTEM_PROMPT),
        (PREV_FACTCHECK_ANALYST_R1023_F3, FACTCHECK_ANALYST_SYSTEM_PROMPT),
        # UNIFIED-CORE (C13, 20.10.2026): канон с мёртвым tone_hint ведёт
        # на канон без поля (схема JSON без изменения контракта).
        (PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT,
         FACTCHECK_ANALYST_SYSTEM_PROMPT)],
    # ASAP W1 (P0-F «точечно», SOUL1-CLOSE-R1 04.3, ADR-1013-3): первая
    # ступень ключа Вербализатора фактчека — прод-канон 2.58.110 (identity
    # «Ты — токсичный, ироничный фактчекер … двача» + ТИПОГРАФИКА) ведёт на
    # канон без identity-фразы (жанровые правила/контракты прежние).
    "prompts.factcheck_verbalizer_system_prompt": [
        (PREV_FACTCHECK_VERBALIZER_W1, FACTCHECK_VERBALIZER_SYSTEM_PROMPT)],
    # 10.26 (S3, ADR-1026-5 D4; ADR-1013-3): новый PG-ключ L1-Кластеризатора.
    # Ступень — правило маркировки целевого сообщения (TARGET_INSTRUCTION_BLOCK);
    # идемпотентна: до сида — skip (сид ConfigCache поставит канон), текущий
    # канон → no-op, кастом юзера не перезаписывается.
    # 10.27 (ASAP-2, ADR-1027-10 D1/kонтракт (l)): ступень R1026→R1027
    # (many-to-many §95-v2, §7 «извлечение смысла»): оба прежних канона
    # (база S3 без блока и канон S3+блок) ведут на новый канон R1027.
    # ASAP 4.1 волна 3 (T-4607, ADR-1028-8 D3 SUPERSEDE): ступень
    # R1027→R1030 semantic map v1 — прод-канон 2.58.46 (слепок
    # PREV_*_R1027_ASAP41) ведёт на map-канон (один коммит код+эталон+тесты,
    # прецедент R4-D-003). Prompt-миграция явная (spec §2 B.1).
    "prompts.summary_l1_clusterizer_system_prompt": [
        (PREV_SUMMARY_L1_CLUSTERIZER_R1026, SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT),
        (PREV_SUMMARY_L1_CLUSTERIZER_R1027, SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT),
        (PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41,
         SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT)],
    # 10.26 (S5, ADR-1026-7 D4; ADR-1013-3): новый PG-ключ L2-Писателя
    # (`prompts.summary_l2_writer_system_prompt`; слепок PREV — база канона S5
    # без правила маркировки целевого сообщения). Ступень идемпотентна: до сида
    # — skip (сид ConfigCache поставит канон), текущий канон → no-op, кастом юзера
    # не перезаписывается.
    # 10.27 (ASAP-2, контракт (l)/T-3942): ступень R1026→R1027 (блок ДЛИНА/
    # ДЕДУПЛИКАЦИЯ + авторы/ответы пакета v2; числа — в length-блоке user-
    # контента, НЕ в каноне).
    # 10.28 (ASAP-2.1, контракт (g)): ступень R1027→R1028 (грамматика §15 +
    # двачерский голос §16 + typography §17 + emphasis_spans/finale §18–§19).
    # ASAP-4 волна D (ADR-1028-7 D4, T-4428): ступень R1028→R1029
    # prose-first — SUPERSEDE запрета прямых цитат (§50.3): старый прод-канон
    # (слепок PREV_*_R1028_ASAP4) ведёт на новый канон с evidence-ссылками.
    "prompts.summary_l2_writer_system_prompt": [
        (PREV_SUMMARY_L2_WRITER_R1026, SUMMARY_L2_WRITER_SYSTEM_PROMPT),
        (PREV_SUMMARY_L2_WRITER_R1027, SUMMARY_L2_WRITER_SYSTEM_PROMPT),
        (PREV_SUMMARY_L2_WRITER_R1028, SUMMARY_L2_WRITER_SYSTEM_PROMPT),
        (PREV_SUMMARY_L2_WRITER_R1028_ASAP4, SUMMARY_L2_WRITER_SYSTEM_PROMPT),
        # ASAP 4.1 волна 3 (T-4609, ADR-1028-8 D4/AM-4): ступень
        # R1029→R1030 — блок источника (Full SourceWindow первоклассно,
        # FactPackage = derived view).
        (PREV_SUMMARY_L2_WRITER_R1029_ASAP41, SUMMARY_L2_WRITER_SYSTEM_PROMPT)],
    # 10.28 (ASAP-2.1, контракт (g)/§25): ступени Рассказчика — шиза выбирает
    # модель (строка опциональна); прежние каноны R1023/R1028 ведут на новый.
    # LEGFIX (22.10.2026, закрытие backlog «narrator-канон identity-фраза»,
    # bindings.cfg-final §6): прод-канон ДО снятия identity-фразы (класс
    # SF-07) ведёт на новый канон.
    "prompts.summary_narrator_system_prompt": [
        (PREV_SUMMARY_NARRATOR_R1023, SUMMARY_NARRATOR_SYSTEM_PROMPT),
        (PREV_SUMMARY_NARRATOR_R1028, SUMMARY_NARRATOR_SYSTEM_PROMPT),
        (PREV_SUMMARY_NARRATOR_LEGFIX, SUMMARY_NARRATOR_SYSTEM_PROMPT)],
}
# prompts.extract_system_prompt НЕ входит (EXTRACT_PROMPT не трогаем)

# Обратная канон-миграция раунда 10.21 (F3 Д9, ADR-1021-3 §5): key →
# (новый канон 10.21, прежний прод-канон R1021). Нужна потому, что `git revert`
# возвращает код-константы, но НЕ откатывает значение в PG. `COMPRESS_PROMPT`
# и `extract` не входят — в 10.21 не менялись.
ROLLBACK_MIGRATIONS: dict[str, tuple[str, str]] = {
    # F1 (10.23, R1023F1-07): откат чата ведёт на непосредственный прежний
    # канон (снимает только последнюю ступень, сохраняя блоки A/B и правило
    # маркировки; стек ступеней цел, ADR-1013-3).
    # MCA-23 (Wave 3): откат снимал ступень MCA-23 (на PREV_CHAT_MCA23).
    # CFG-07A-2 (20.10.2026): откат ведёт на НЕПОСРЕДСТВЕННЫЙ прежний
    # прод-канон 2.58.100 (MCA-23-композиция; снимается только ступень
    # CFG-07A, стек ступеней цел — ADR-1013-3).
    # ASAP W1 (22.10.2026): откат снимает только ступень W1 — на прод-канон
    # 2.58.110 (PREV_*_W1); стек ступеней цел.
    "prompts.direct_chat_system_prompt":
        (CHAT_SYSTEM_PROMPT, PREV_CHAT_W1_SYSTEM_PROMPT),
    # MCA-23 (Wave 3, §11): откат Вербализатора direct — на прод-канон
    # 10.23 (с cap-правилом); ключ в PG не удаляется.
    # ASAP W1: откат — на прод-канон 2.58.110 (d0ef0d376fc3).
    # ASAP 2 (23.10.2026): откат снимает только ступень уточнений —
    # на канон W1 §3.1 (прод 2.58.111).
    "prompts.direct_chat_verbalizer_system_prompt":
        (DIRECT_VERBALIZER_SYSTEM_PROMPT, PREV_CHAT_VERBALIZER_W1_31),
    # ASAP W1 (P0-G): откат — на прод-канон L1D 2.58.110 (ace6246bd360,
    # блок «ФОРМА УЧАСТИЯ»); снимается только секция «ВЫБОР УЧАСТИЯ».
    # ASAP 2 (23.10.2026): откат снимает ступень уточнений — на канон W1
    # (прод 2.58.111); стек ступеней цел.
    "prompts.direct_l1_planner_system_prompt":
        (DIRECT_L1_PLANNER_SYSTEM_PROMPT, PREV_DIRECT_L1_PLANNER_W1),
    # ASAP W1 (P0-F «точечно»): откат — на прод-канон 2.58.110 (с identity).
    "prompts.factcheck_verbalizer_system_prompt":
        (FACTCHECK_VERBALIZER_SYSTEM_PROMPT, PREV_FACTCHECK_VERBALIZER_W1),
    "prompts.summary_system_prompt":
        # CFG-07A-2: откат ведёт на НЕПОСРЕДСТВЕННЫЙ прежний прод-канон
        # 2.58.100 (снимается только ступень CFG-07A; стек ступеней цел).
        (SYSTEM_PROMPT, PREV_SUMMARY_CFG07A_SYSTEM_PROMPT),
    "prompts.checkup_system_prompt":
        # CFG-07A-2: откат на непосредственный прежний прод-канон 2.58.100.
        # P0-CHECKUP (24.10.2026): откат снимает ТОЛЬКО новую ступень P0 —
        # на прод-канон 2.58.118 (PREV_CHECKUP_P0, 38d63d86b54d); стек
        # ступеней цел (ADR-1013-3).
        (CHECKUP_SYSTEM_PROMPT, PREV_CHECKUP_P0_SYSTEM_PROMPT),
    "prompts.factcheck_system_prompt":
        # UNIFIED-CORE (C14): откат ведёт на НЕПОСРЕДСТВЕННЫЙ прежний
        # прод-канон (с обходом safety, релиз 2.58.97) — снимается только
        # ступень C14; стек ступеней цел (ADR-1013-3).
        (FACTCHECK_SYSTEM_PROMPT, PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT),
    "prompts.search_system_prompt":
        # CFG-07A-2: откат на непосредственный прежний прод-канон 2.58.100
        # (снимается только ступень CFG-07A; ADR-1013-3).
        (SEARCH_SYSTEM_PROMPT, PREV_SEARCH_CFG07A_SYSTEM_PROMPT),
    "prompts.youtube_system_prompt":
        (YOUTUBE_SYSTEM_PROMPT, PREV_YOUTUBE_CFG07A_SYSTEM_PROMPT),
    "prompts.youtube_video_system_prompt":
        (YOUTUBE_VIDEO_SYSTEM_PROMPT, PREV_YOUTUBE_VIDEO_CFG07A_SYSTEM_PROMPT),
    "prompts.webpage_system_prompt":
        (WEBPAGE_SYSTEM_PROMPT, PREV_WEBPAGE_CFG07A_SYSTEM_PROMPT),
    # 10.23 (F1, ADR-1023-1): обратный шаг для новых PG-ключей F8.
    # 10.23 (F2, ADR-1023-2): правило веб-поиска. После вливания F3 (ступень
    # F2→F3) откат Аналитика ведёт на непосредственный прежний канон —
    # PREV_FACTCHECK_ANALYST_R1023_F3 (F2-правило веб-поиска в нём СОХРАНЕНО);
    # снимается только ступень F3 (response_mode). Прямой откат сразу к F1
    # (PREV_..._F2) не выражается — стек ступеней F1→F2→F3, каждая снимает
    # ровно предыдущую.
    # 10.23 (F3, ADR-1023-3): откат снимает только ступень F3 — на слепок без
    # поля response_mode (PREV_SUMMARY_EDITOR_R1023_F3/PREV_..._F3).
    # 10.25 (hotfix4): откат снимает только ступень HOTFIX4 — на слепок
    # канона F6 (жёсткий запрет надписей).
    "prompts.summary_editor_system_prompt":
        (SUMMARY_EDITOR_SYSTEM_PROMPT, PREV_SUMMARY_EDITOR_R1025_HOTFIX4),
    "prompts.factcheck_analyst_system_prompt":
        # UNIFIED-CORE (C13): откат снимает только ступень C13 (мёртвый
        # tone_hint) — на непосредственный прежний прод-канон с полем.
        (FACTCHECK_ANALYST_SYSTEM_PROMPT,
         PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT),
    # 10.27 (ASAP-2): откат ступени R1027 ведёт на НЕПОСРЕДСТВЕННО прежний
    # канон PREV_*_R1027 (полный канон R1026 с блоком маркировки) — снимается
    # только шаг many-to-many/смысла, стек ступеней сохраняется (ADR-1013-3).
    # ASAP 4.1 волна 3 (T-4607/T-4609): откат map-канона/блока источника —
    # на НЕПОСРЕДСТВЕННО прежний прод-канон 2.58.46 (rollback-паритет с
    # kill-switch SUMMARY_L1_SEMANTIC_MAP_ENABLED/SUMMARY_WRITER_SOURCE_
    # INPUT_ENABLED=false; read-side смещение через существующую лестницу).
    "prompts.summary_l1_clusterizer_system_prompt":
        (SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
         PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41),
    # 10.26 (S5, ADR-1026-7 D4): откат снимает ключ L2 на слепок базы канона S5
    # (без правила маркировки целевого сообщения). L2 врезан за kill-switch
    # (default OFF), поэтому откат значения поведения не меняет; ключ в PG не
    # удаляется.
    # 10.27 (ASAP-2): откат ступени R1027 — на канон R1026 (PREV_*_R1027).
    # 10.28 (ASAP-2.1): откат ступени R1028 — на НЕПОСРЕДСТВЕННО прежний
    # канон PREV_*_R1028 (полный канон ASAP-2 R1027).
    # ASAP-4 (волна D, ADR-1028-7 D4): откат ступени R1029 prose-first — на
    # НЕПОСРЕДСТВЕННО прежний прод-канон PREV_*_R1028_ASAP4 (с запретом
    # цитат; rollback-паритет с kill-switch SUMMARY_L2_REVIEW_ENABLED=false).
    # ASAP 4.1 волна 3 (T-4609): откат блока источника — на канон R1029
    # (прод 2.58.46; parity с SUMMARY_WRITER_SOURCE_INPUT_ENABLED=false).
    "prompts.summary_l2_writer_system_prompt":
        (SUMMARY_L2_WRITER_SYSTEM_PROMPT, PREV_SUMMARY_L2_WRITER_R1029_ASAP41),
    # 10.28 (ASAP-2.1): откат Рассказчика — на прежний канон R1028 (до правки
    # §25); ключ в PG не удаляется.
    # LEGFIX (22.10.2026): откат снимает ТОЛЬКО ступень LEGFIX — на
    # непосредственный прежний канон (слепок PREV_SUMMARY_NARRATOR_LEGFIX);
    # стек ступеней цел (ADR-1013-3).
    "prompts.summary_narrator_system_prompt":
        (SUMMARY_NARRATOR_SYSTEM_PROMPT, PREV_SUMMARY_NARRATOR_LEGFIX),
}


# ═══════════════════════════════════════════════════════════════════════════
# ASAP W1 (P0-B, §3.2 «Особая осторожность») — owner-preserving патч Core
# ═══════════════════════════════════════════════════════════════════════════
# W0-факт (plans/features/asap-speech-arch/evidence/w0-inventory.md §3):
# активный ``character.core.full_text`` = владельческая правка 22.10
# (act:f59ba0f42a48, owner_edit, doc rev 6, 2327c) — мат-абзац владелец уже
# удалил сам; служебная ремарка «**Важно:** … см. SOUL-16 …» ОСТАЛАСЬ
# (унаследована от фабрики v2). Патч удаляет из активного текста владельца
# ТОЛЬКО служебную ремарку (и точечные ссылки «см. SOUL-NN»), всё остальное
# сохраняя байт-в-байт (ДОП-2: авторские изменения не перезаписываются,
# показывается diff). Чистая функция для W2 (запись через write_speech_value
# с провенансом owner_edit + history); БД сама по себе не трогается.

#: Точная служебная ремарка фабрики v2 (удалена в v3, §3.2): абзац целиком,
#: с предшествующей пустой строкой. Байты = PREV хвост «**Важно:** …».
_CORE_SERVICE_REMARK_V2 = (
    "\n\n**Важно:** это *семантическое описание характера*, а не форматный "
    "контракт. Запреты на кавычки, точки, оформление ссылок, эмодзи и т.п. "
    "живут в отдельном редактируемом слое «Стиль письма», см. SOUL-16; они "
    "не должны загрязнять Core. Сохранить исходную формулировку ядра по "
    "смыслу и владельческую возможность менять любой фрагмент.")

#: Узкое точечное упоминание «см. SOUL-NN» (если владелец переформулировал
#: абзац, но метка осталась). Только связка «см. SOUL-<цифры>», остальной
#: текст владельца не трогается.
_CORE_SOUL_REF_RE = re.compile(r"\s*см\.\s*SOUL-\d+")

#: Известные прежние заводские байты (v1/v2) — гасятся гвардом superseded-core
#: (prompt_registry.core_selection), owner-preserving патч для них не нужен.
_CORE_SUPERSEDED_NOTE = "см. prompt_registry.core_selection superseded-core"

#: P0-CHECKUP/CORE (24.10.2026, addendum §3): единственный недостающий
#: универсальный абзац владельца. Патч вставляет его ТОЛЬКО если смысла нет
#: (якорь/пара смысловых маркеров отсутствует), в позицию после «Как рождается
#: юмор» и перед «Грубость»/«Ритм»; остальные байты владельца сохраняются.
_CORE_REAL_EVENTS_ANCHOR = "Как говорить о реальных событиях."
_CORE_REAL_EVENTS_EQUIVALENT = ("характерные детали", "цельн")
_CORE_REAL_EVENTS_CHANGE = "added: " + _CORE_REAL_EVENTS_ANCHOR
#: Заголовки абзацев активной владельческой редакции (v2-стиль и v3-стиль):
#: первый найденный — точка вставки нового абзаца.
_CORE_INSERT_ANCHORS = (
    "\n\nГрубость и конфликт.",
    "\n\n**Грубость.**",
    "\n\nГрубость.",
    "\n\n**Ритм.**",
    "\n\nРитм.",
)


def _core_has_real_events_meaning(text: str) -> bool:
    """Смысл «фактура → цельная сцена» уже прямо выражен владельцем?"""
    if _CORE_REAL_EVENTS_ANCHOR in text:
        return True
    return all(marker in text for marker in _CORE_REAL_EVENTS_EQUIVALENT)


def owner_preserve_core_full_patch(text: str) -> tuple[str, list[str]]:
    """Минимальный owner-preserving патч активного Full Core (W2-ступень).

    Удаляет ТОЛЬКО: (а) точную служебную ремарку v2 (абзац «**Важно:** …»)
    и (б) точечные остатки «см. SOUL-NN». Всё остальное — байт-в-байт
    владельческий текст. P0-CHECKUP/CORE (24.10.2026): если универсального
    смысла «Как говорить о реальных событиях» в редакции нет, абзац владельца
    (addendum §3) вставляется в позицию после «Как рождается юмор»; уже
    имеющийся смысл не дублируется. Возврат ``(patched, changes)``: ``changes``
    — список удалённых фрагментов и, при вставке, маркер ``added: …`` (пусто =
    править нечего, идемпотентно). Никогда не бросает; на пустом/нестроковом
    входе — ``(вход, [])``.

    НЕ применяется к байтам, равным прежним заводским редакциям (v1/v2) —
    их ведёт на фабрику гвард superseded-core (``_CORE_SUPERSEDED_NOTE``).
    """
    try:
        source = str(text or "")
        if not source:
            return source, []
        if source in (PREV_PERSONALITY_CORE_FULL_TEXT,
                      PREV_PERSONALITY_CORE_FULL_V2_TEXT):
            return source, [_CORE_SUPERSEDED_NOTE]
        changes: list[str] = []
        patched = source
        if _CORE_SERVICE_REMARK_V2 in patched:
            patched = patched.replace(_CORE_SERVICE_REMARK_V2, "")
            changes.append(_CORE_SERVICE_REMARK_V2.lstrip("\n"))
        if "SOUL-" in patched:
            refs = _CORE_SOUL_REF_RE.findall(patched)
            patched = _CORE_SOUL_REF_RE.sub("", patched)
            for ref in refs:
                stripped = ref.strip()
                if stripped not in changes:
                    changes.append(stripped)
        if changes:
            patched = patched.rstrip()
        if not _core_has_real_events_meaning(patched):
            block = "\n\n" + CORE_REAL_EVENTS_PARAGRAPH
            for anchor in _CORE_INSERT_ANCHORS:
                if anchor in patched:
                    patched = patched.replace(anchor, block + anchor, 1)
                    break
            else:
                patched = patched.rstrip() + block
            changes.append(_CORE_REAL_EVENTS_CHANGE)
        return patched, changes
    except Exception:      # pragma: no cover — патч не роняет миграцию
        return str(text or ""), []


async def migrate_prompt_canons(cache) -> dict[str, str]:
    """Авто-миграция канонов промптов (раунд 5): канон → новый канон;
    кастом юзера НЕ трогаем; PG down / ключ отсутствует → skip с логом
    [prompt_migration]. Возврат: dict обновлённых ключей (пусто — ничего
    не обновлено). Вызывается из bot.py main() сразу после cache.init()."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[prompt_migration] skip: PG недоступен")
        return report
    for key, steps in PROMPT_MIGRATIONS.items():
        current = cache.get(key)
        if current is None:
            logger.info("[prompt_migration] ключ отсутствует — сид сделает "
                        "своё | key=%s", key)
            continue
        matched = None
        for prev, new in steps:
            if current == new:
                matched = ("new", new)
                break
            if current == prev:
                matched = ("prev", prev, new)
                break
        if matched is None:
            logger.warning("[prompt_migration] кастом юзера — НЕ трогаем | "
                           "key=%s | chars=%d", key, len(current))
            continue
        if matched[0] == "new":
            logger.info("[prompt_migration] уже новый канон | key=%s", key)
            continue
        new = matched[2]
        await cache.set(key, new, "prompts")
        report[key] = "updated"
        logger.info("[prompt_migration] канон обновлён | key=%s", key)
    return report


async def rollback_prompt_canons(cache) -> dict[str, str]:
    """Обратная канон-миграция раунда 10.21 (F3 Д9, ADR-1021-3 §5).

    Возвращает PG-значения `prompts.*` с нового канона 10.21 на прежний
    прод-канон (`PREV_*_R1021`). Идемпотентна: повторный прогон — no-op.
    Кастом юзера не трогаем (WARNING), ключ отсутствует / PG down — skip.
    Вызывается вручную (runbook @DevOps) при откате `git revert`."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[prompt_rollback] skip: PG недоступен")
        return report
    for key, (new, old) in ROLLBACK_MIGRATIONS.items():
        current = cache.get(key)
        if current is None:
            logger.info("[prompt_rollback] ключ отсутствует | key=%s", key)
            continue
        if current == old:
            logger.info("[prompt_rollback] уже прежний канон | key=%s", key)
            continue
        if current != new:
            logger.warning("[prompt_rollback] кастом юзера — НЕ трогаем | "
                           "key=%s | chars=%d", key, len(current))
            continue
        await cache.set(key, old, "prompts")
        report[key] = "rolled_back"
        logger.info("[prompt_rollback] канон откачен | key=%s", key)
    return report


# ═══════════════════════════════════════════════════════════════════════════
# SOUL-1 / W1 — удаление legacy-речи из effective-слоя (§1.2 + §7.2)
# ═══════════════════════════════════════════════════════════════════════════
# Контракт (source-architectural-clarification §7.2, design-source §4 R4):
#   * до удаления сделан backup (evidence/w1/backup-speech-config.json);
#   * удаляется ТОЛЬКО известный канон (байты совпали с известным слепком):
#     сегменты старой личности вычищаются детерминированно
#     (``prompt_registry.suppress_legacy_speech`` — прецедент
#     ``response_extent.strip_cap_phrases``); кастом владельца НЕ
#     перезаписывается никогда (owner-decisions «a»: витрина конфликта);
#   * оригиналы неизменно сохраняются в ``character.migration_snapshots``
#     (append-only, прецедент design §2.1) — источник не теряется;
#   * идемпотентность: повторный прогон видит уже нормализованное значение
#     (sha совпал с записанным) и делает no-op;
#   * откат: ``rollback_legacy_speech`` возвращает оригиналы; значения в PG
#     при этом всегда остаются восстановимыми.

MIGRATION_SNAPSHOTS_KEY = "character.migration_snapshots"
MIGRATION_SNAPSHOTS_CATEGORY = "content"

#: Категории bot_settings, участвующие в речевом слое (IP: только prompts).
SPEECH_MIGRATION_CATEGORY = "prompts"


def _load_migration_snapshots(cache) -> dict:
    """Неизменяемый блок захваченных оригиналов (только чтение/дополнение)."""
    import json as _json
    raw = None
    try:
        raw = cache.get(MIGRATION_SNAPSHOTS_KEY, None) if cache else None
    except Exception:          # pragma: no cover — PG down
        raw = None
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except Exception:
            raw = None
    if not isinstance(raw, dict):
        return {"captured_at": "", "items": {}}
    if not isinstance(raw.get("items"), dict):
        raw["items"] = {}
    return raw


def _classify_legacy_value(key: str, block_id: str, current,
                           snapshots: dict) -> tuple[str, str, tuple]:
    """``(класс, предсказанное действие, labels)`` для одного ключа."""
    from services import prompt_registry as pr
    if current is None:
        return "absent", "skip:сид поставит канон", ()
    if not isinstance(current, str):
        return "invalid", "skip:не строковое значение", ()
    item = (snapshots.get("items") or {}).get(key) or {}
    if item.get("normalized_sha256_12") == pr.sha12(current):
        return "already_normalized", "no-op:идемпотентно", ()
    factory = pr.factory_text(block_id)
    if factory and current == factory:
        cls = "canon_current"
    elif pr.is_known_canon(current):
        cls = "canon_prev_step"
    else:
        cls = "custom_legacy"
    stripped, info = pr.suppress_legacy_speech(current, source="global")
    if cls == "custom_legacy":
        action = ("keep:кастом владельца — НЕ трогаем"
                  + (" (старая личность видна в витрине конфликта)"
                     if info.legacy_present else ""))
        return cls, action, ()
    if not info.applied:
        return cls, "no-op:legacy-сегментов не найдено", ()
    return cls, "normalize:вычистить известные сегменты личности", info.labels


async def plan_legacy_speech_removal(cache) -> dict:
    """Фаза A (read-only): предпросмотр удаления legacy-речи из PG.

    Ничего не пишет. Для каждого речевого блока с PG-ключом возвращает
    класс значения, предсказанное действие, счётчики и sha —
    «source → registry mapping» проверяем: каждый ключ привязан к Registry ID.
    """
    from services import prompt_registry as pr
    snapshots = _load_migration_snapshots(cache)
    pg_available = bool(getattr(cache, "pg_available", False))
    items: list[dict] = []
    for spec in sorted(pr.legacy_persona_blocks(), key=lambda s: s.block_id):
        if not spec.pg_key:
            continue
        current = None
        if pg_available and cache is not None:
            try:
                current = cache.get(spec.pg_key, None)
            except Exception:      # pragma: no cover — PG down
                current = None
        cls, action, labels = _classify_legacy_value(
            spec.pg_key, spec.block_id, current, snapshots)
        stripped, info = pr.suppress_legacy_speech(
            current if isinstance(current, str) else "", source="global")
        items.append({
            "registry_id": spec.block_id,
            "key": spec.pg_key,
            "class": cls,
            "action": action,
            "owner_lane": spec.owner_lane,
            "chars": len(current) if isinstance(current, str) else 0,
            "sha256_12": pr.sha12(current or "") if isinstance(current, str)
            else "",
            "target_chars": len(stripped),
            "target_sha256_12": pr.sha12(stripped),
            "removed": info.removed,
            "removed_labels": list(info.labels or labels),
        })
    return {"pg_available": pg_available, "write": False,
            "registry_version": pr.REGISTRY_VERSION,
            "snapshots_key": MIGRATION_SNAPSHOTS_KEY,
            "items": items,
            "predicted_writes": sum(1 for row in items
                                    if row["class"] in ("canon_current",
                                                        "canon_prev_step")
                                    and row["removed"] > 0)}


async def normalize_legacy_speech(cache, *, apply: bool = False,
                                  actor=None) -> dict:
    """Фаза B: идемпотентная транзакционная нормализация известных канонов.

    ``apply=False`` (дефолт) → dry-run, ничего не пишет.
    ``apply=True`` → один ``ConfigCache.set_many`` (одна PG-транзакция):
      * известные каноны заменяются версией без legacy-сегментов личности;
      * оригиналы дописываются в ``character.migration_snapshots``
        (неизменяемый блок, только дополнение);
      * кастомы владельца НЕ перезаписываются (WARNING);
      * PG down → skip (поведение рантайма не меняется — там работает
        детерминированное подавление на сборке).
    """
    import json as _json
    from services import prompt_registry as pr
    report = {"apply": bool(apply), "updated": {}, "kept_custom": [],
              "skipped": [], "pg_available": bool(
                  getattr(cache, "pg_available", False))}
    plan = await plan_legacy_speech_removal(cache)
    if not report["pg_available"] or cache is None:
        logger.info("[prompt_legacy_speech] skip: PG недоступен")
        report["reason"] = "pg_unavailable"
        return report
    snapshots = _load_migration_snapshots(cache)
    items = dict(snapshots.get("items") or {})
    changed_snapshots = False
    batch: list[tuple] = []
    for row in plan["items"]:
        key = row["key"]
        cls = row["class"]
        if cls in ("absent", "invalid", "already_normalized"):
            report["skipped"].append({"key": key, "class": cls})
            continue
        if cls == "custom_legacy":
            report["kept_custom"].append({"key": key, "chars": row["chars"],
                                          "sha256_12": row["sha256_12"]})
            logger.warning("[prompt_legacy_speech] кастом владельца — НЕ "
                           "трогаем | key=%s | registry=%s", key,
                           row["registry_id"])
            continue
        if row["removed"] <= 0:
            report["skipped"].append({"key": key, "class": cls})
            continue
        current = cache.get(key)
        stripped, _info = pr.suppress_legacy_speech(current, source="global")
        entry = items.get(key) or {}
        if entry.get("original_sha256_12") not in (None, row["sha256_12"]):
            # Оригинал уже захвачен в другой ревизии — не перезаписываем
            # неизменяемый блок, только дополняем нормализованный sha.
            logger.info("[prompt_legacy_speech] snapshot уже есть | key=%s",
                        key)
        if not entry:
            items[key] = {
                "registry_id": row["registry_id"],
                "class": cls,
                "original_sha256_12": row["sha256_12"],
                "original_chars": row["chars"],
                "text": current,
                "normalized_sha256_12": row["target_sha256_12"],
                "at": _utc_now(),
                "by": str(actor) if actor is not None else "",
            }
            changed_snapshots = True
        else:
            entry["normalized_sha256_12"] = row["target_sha256_12"]
            entry["last_normalized_at"] = _utc_now()
            items[key] = entry
            changed_snapshots = True
        batch.append((key, stripped, SPEECH_MIGRATION_CATEGORY))
        report["updated"][key] = {"registry_id": row["registry_id"],
                                  "from_sha256_12": row["sha256_12"],
                                  "to_sha256_12": row["target_sha256_12"],
                                  "removed": row["removed"]}
    if not report["apply"]:
        report["would_write"] = len(batch)
        report["written"] = 0
        return report
    if changed_snapshots:
        doc = {"captured_at": snapshots.get("captured_at") or _utc_now(),
               "items": items}
        batch.append((MIGRATION_SNAPSHOTS_KEY, doc,
                      MIGRATION_SNAPSHOTS_CATEGORY))
    report["written"] = 0
    if not batch:
        return report
    await cache.set_many(batch)
    report["written"] = len(batch)
    logger.info("[prompt_legacy_speech] нормализовано ключей: %d "
                "(snapshots=%s)", len(batch), changed_snapshots)
    return report


async def rollback_legacy_speech(cache) -> dict:
    """Откат нормализации: вернуть оригиналы из ``migration_snapshots``.

    Идемпотентно: ключ, значение которого уже не равно нормализованному
    (правка владельца после миграции), НЕ перезаписывается — WARNING.
    """
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[prompt_legacy_speech] rollback skip: PG недоступен")
        return report
    from services import prompt_registry as pr
    snapshots = _load_migration_snapshots(cache)
    batch: list[tuple] = []
    for key, item in sorted((snapshots.get("items") or {}).items()):
        text = item.get("text")
        if not isinstance(text, str):
            continue
        current = cache.get(key, None)
        if current is None:
            report[key] = "absent"
            continue
        if current == text:
            report[key] = "already_original"
            continue
        if pr.sha12(current) != item.get("normalized_sha256_12"):
            logger.warning("[prompt_legacy_speech] rollback: значение "
                           "изменено после миграции — НЕ трогаем | key=%s",
                           key)
            report[key] = "changed_after_migration"
            continue
        batch.append((key, text, SPEECH_MIGRATION_CATEGORY))
        report[key] = "rolled_back"
    if batch:
        await cache.set_many(batch)
    return report


def _utc_now() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
