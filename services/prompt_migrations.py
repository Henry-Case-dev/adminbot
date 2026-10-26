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
    PREV_CHAT_VERBALIZER_CLAR,
    PREV_CHAT_W1_SYSTEM_PROMPT,
    PREV_DIRECT_L1_PLANNER_BASE,
    PREV_DIRECT_L1_PLANNER_1021,
    PREV_DIRECT_L1_PLANNER_1022,
    PREV_DIRECT_L1_PLANNER_L1D,
    PREV_DIRECT_L1_PLANNER_W1,
    PREV_DIRECT_L1_PLANNER_CLAR,
    PREV_DIRECT_L1_PLANNER_R3,
    PREV_DIRECT_L1_PLANNER_R3B,
    PREV_DIRECT_L1_PLANNER_P0CS,
    PREV_DIRECT_L1_PLANNER_P0CS2,
    PREV_DIRECT_L1_PLANNER_P0CINT,
    PREV_DIRECT_L1_PLANNER_P0CINTR2,
    CORE_REAL_EVENTS_PARAGRAPH,
    CORE_FREE_SPEECH_PARAGRAPH,
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
    PREV_SUMMARY_L2_WRITER_R1030_P0,
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
        (PREV_CHAT_VERBALIZER_W1_31, DIRECT_VERBALIZER_SYSTEM_PROMPT),
        # SPEECH-CANON R3b (23.10.2026, T10-BOUNDARY / CLAR-CTX-HONEST):
        # канон 2.58.113 (W1 §3.1 + абзацы §4.2) ведёт на канон с одной
        # узкой инструкцией о честной границе истории. Только точное
        # совпадение байт; абзацы владельца не пересказаны.
        (PREV_CHAT_VERBALIZER_CLAR, DIRECT_VERBALIZER_SYSTEM_PROMPT)],
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
        (PREV_DIRECT_L1_PLANNER_W1, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        # SPEECH-INIT-FIX R3 (23.10.2026, evidence/r2/results.md §7):
        # прод-канон 2.58.113 (канон W1 + контракт уточнений) ведёт на
        # канон с усиленными смысловыми критериями доставки/адресата и
        # target для реакции. Только точное совпадение байт.
        (PREV_DIRECT_L1_PLANNER_CLAR, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        # SPEECH-CANON R3b (23.10.2026, T20 / §4.1 продолжение): канон R3
        # (база R3 + контракт §4.1 + правила) ведёт на канон с узким
        # усилением продолжения после ответа на уточнение. Только точное
        # совпадение байт; правила и секция участия не менялись.
        # SPEECH-P0-CORE-SERIOUS (25.10.2026, §1 аддендума): канон R3b
        # (база R3 + контракт §4.1 + продолжение + правила) доведён до правила 7
        # маршрутизации личного разбора. Ступень узнаёт прод-байты R3b целиком;
        # кастомы владельца не перетираются.
        # P0-CORRECTIVE (25.10.2026, §1.1 corrective): правило 7 заменено
        # смысловым критерием «разбор уже сказанного → research; мнение →
        # answer», JSON — 9. Верхняя ступень узнаёт ТЕКУЩИЕ активные байты
        # (P0CS) точно и ведёт на новую редакцию.
        # P0-CORRECTIVE ред.2 (25.10.2026, §1.1): приоритет разбора в
        # смешанной просьбе («разбери накопленное + скажи оценку») — ступени
        # узнают и редакцию 1 (P0CS2, ``f6f5d3b1fc1d``), и прежние P0CS/R3b.
        # P0C-INT R2 (25.10.2026, `probes_final4.md` §3): редакция 3 —
        # просьба разобрать материал = research независимо от вопроса-оценки
        # в конце; разбор не выбирает hostile_rebuff. Верхняя ступень —
        # редакция 2 (PREV_..._P0CINT, 9288/``23aae0c9499d``).
        # P0C-INT R3 (26.10.2026, `probes_final5-rerun.md` §4): редакция 4 —
        # `response_act` отделён от `tone` (грубость меняет только манеру);
        # верхняя ступень — редакция 3 (PREV_..._P0CINTR2, 9391).
        (PREV_DIRECT_L1_PLANNER_P0CINTR2, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        (PREV_DIRECT_L1_PLANNER_P0CINT, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        (PREV_DIRECT_L1_PLANNER_P0CS2, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        (PREV_DIRECT_L1_PLANNER_P0CS, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        (PREV_DIRECT_L1_PLANNER_R3B, DIRECT_L1_PLANNER_SYSTEM_PROMPT),
        (PREV_DIRECT_L1_PLANNER_R3, DIRECT_L1_PLANNER_SYSTEM_PROMPT)],
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
        (PREV_SUMMARY_L2_WRITER_R1029_ASAP41, SUMMARY_L2_WRITER_SYSTEM_PROMPT),
        # SPEECH-P0-B2 (25.10.2026, source-owner-p0-hotfix §4,
        # MEMORY-NO-UNSUPPORTED-CAUSAL-STORY): прод-канон 2.58.130 (R1030
        # байт-в-байт) ведёт на канон без обязательной причинной драматургии.
        (PREV_SUMMARY_L2_WRITER_R1030_P0, SUMMARY_L2_WRITER_SYSTEM_PROMPT)],
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
# цепочка ступеней `(новый канон, прежний канон)`, по ОДНОЙ ступени на вызов.
# Нужна потому, что `git revert` возвращает код-константы, но НЕ откатывает
# значение в PG. `COMPRESS_PROMPT` и `extract` не входят — в 10.21 не менялись.
#
# Цепочка (REL-F1, 24.10.2026): если ступеней больше одной, повторный вызов
# `rollback_prompt_canons` снимает следующую — полный откат к прод-канону
# 2.58.113 требует ровно столько вызовов, сколько ступеней (L1 — 2, L2 — 1),
# дальше — no-op на последнем `old`. Первая ступень каждой цепочки — это
# по-прежнему «непосредственно прежний» канон (ADR-1013-3, стек цел).
ROLLBACK_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
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
        [(CHAT_SYSTEM_PROMPT, PREV_CHAT_W1_SYSTEM_PROMPT)],
    # MCA-23 (Wave 3, §11): откат Вербализатора direct — на прод-канон
    # 10.23 (с cap-правилом); ключ в PG не удаляется.
    # ASAP W1: откат — на прод-канон 2.58.110 (d0ef0d376fc3).
    # ASAP 2 (23.10.2026): откат снимает только ступень уточнений —
    # на канон W1 §3.1 (прод 2.58.111).
    # SPEECH-CANON R3b (23.10.2026): откат снимает только ступень R3b — на
    # канон 2.58.113 (PREV_CHAT_VERBALIZER_CLAR: §3.1 + абзацы §4.2).
    "prompts.direct_chat_verbalizer_system_prompt":
        [(DIRECT_VERBALIZER_SYSTEM_PROMPT, PREV_CHAT_VERBALIZER_CLAR)],
    # ASAP W1 (P0-G): откат — на прод-канон L1D 2.58.110 (ace6246bd360,
    # блок «ФОРМА УЧАСТИЯ»); снимается только секция «ВЫБОР УЧАСТИЯ».
    # ASAP 2 (23.10.2026): откат снимает ступень уточнений — на канон W1
    # (прод 2.58.111); стек ступеней цел.
    # SPEECH-INIT-FIX R3 (23.10.2026): откат снимает только ступень R3 —
    # на непосредственный прежний прод-канон 2.58.113 (PREV_..._CLAR:
    # канон W1 + контракт уточнений); стек ступеней цел.
    # SPEECH-CANON R3b (23.10.2026): откат снимает только ступень R3b — на
    # канон R3 (PREV_DIRECT_L1_PLANNER_R3: база R3 + контракт §4.1 + правила).
    # SPEECH-P0-CORE-SERIOUS (25.10.2026, §1 аддендума): верхняя ступень —
    # правило 7 маршрутизации личного разбора.
    # P0-CORRECTIVE (25.10.2026, §1.1): правило 7 заменено смысловой связкой
    # «материал/история → research; мнение → answer» (JSON — 9). Ред.2 добавила
    # приоритет разбора в смешанной просьбе. P0C-INT R2 (25.10.2026,
    # `probes_final4.md` §3): ред.3 — разбор материала не отменяется вопросом-
    # оценкой и не выбирает hostile_rebuff. Откат снимает ТОЛЬКО новую
    # редакцию — на активные байты ред.2 (P0CINT, 9288), затем P0CS2; стек
    # прежних ступеней цел (ADR-1013-3).
    "prompts.direct_l1_planner_system_prompt": [
        # ступень 0: активный канон ред.4 → P0CINTR2 (активные байты ред.3)
        (DIRECT_L1_PLANNER_SYSTEM_PROMPT, PREV_DIRECT_L1_PLANNER_P0CINTR2),
        # ступень 1: P0CINTR2 → P0CINT (активные байты ред.2)
        (PREV_DIRECT_L1_PLANNER_P0CINTR2, PREV_DIRECT_L1_PLANNER_P0CINT),
        # ступень 2: P0CINT → P0CS2 (активные байты ред.1)
        (PREV_DIRECT_L1_PLANNER_P0CINT, PREV_DIRECT_L1_PLANNER_P0CS2),
        # ступень 2: P0CS2 → P0CS (правило 7 старой редакции)
        (PREV_DIRECT_L1_PLANNER_P0CS2, PREV_DIRECT_L1_PLANNER_P0CS),
        # ступень 3: P0CS → R3b (прод-байты без правила 7)
        (PREV_DIRECT_L1_PLANNER_P0CS, PREV_DIRECT_L1_PLANNER_R3B),
        # ступень 4: R3b → канон R3 (база R3 + контракт §4.1 + правила)
        (PREV_DIRECT_L1_PLANNER_R3B, PREV_DIRECT_L1_PLANNER_R3),
        # ступень 4: R3 → прод-канон 2.58.113 (контракт уточнений).
        # Полный откат до 2.58.113 = пять вызовов rollback_prompt_canons.
        (PREV_DIRECT_L1_PLANNER_R3, PREV_DIRECT_L1_PLANNER_CLAR)],
    # ASAP W1 (P0-F «точечно»): откат — на прод-канон 2.58.110 (с identity).
    "prompts.factcheck_verbalizer_system_prompt":
        [(FACTCHECK_VERBALIZER_SYSTEM_PROMPT, PREV_FACTCHECK_VERBALIZER_W1)],
    "prompts.summary_system_prompt":
        # CFG-07A-2: откат ведёт на НЕПОСРЕДСТВЕННЫЙ прежний прод-канон
        # 2.58.100 (снимается только ступень CFG-07A; стек ступеней цел).
        [(SYSTEM_PROMPT, PREV_SUMMARY_CFG07A_SYSTEM_PROMPT)],
    "prompts.checkup_system_prompt":
        # CFG-07A-2: откат на непосредственный прежний прод-канон 2.58.100.
        # P0-CHECKUP (24.10.2026): первый вызов снимает ТОЛЬКО новую ступень
        # P0 — на прод-канон 2.58.118 (PREV_CHECKUP_P0, 38d63d86b54d);
        # второй — историческую ступень CFG-07A (2.58.100). Стек цел
        # (ADR-1013-3: ни одна ступень не теряется).
        [(CHECKUP_SYSTEM_PROMPT, PREV_CHECKUP_P0_SYSTEM_PROMPT),
         (PREV_CHECKUP_P0_SYSTEM_PROMPT,
          PREV_CHECKUP_CFG07A_SYSTEM_PROMPT)],
    "prompts.factcheck_system_prompt":
        # UNIFIED-CORE (C14): откат ведёт на НЕПОСРЕДСТВЕННЫЙ прежний
        # прод-канон (с обходом safety, релиз 2.58.97) — снимается только
        # ступень C14; стек ступеней цел (ADR-1013-3).
        [(FACTCHECK_SYSTEM_PROMPT, PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT)],
    "prompts.search_system_prompt":
        # CFG-07A-2: откат на непосредственный прежний прод-канон 2.58.100
        # (снимается только ступень CFG-07A; ADR-1013-3).
        [(SEARCH_SYSTEM_PROMPT, PREV_SEARCH_CFG07A_SYSTEM_PROMPT)],
    "prompts.youtube_system_prompt":
        [(YOUTUBE_SYSTEM_PROMPT, PREV_YOUTUBE_CFG07A_SYSTEM_PROMPT)],
    "prompts.youtube_video_system_prompt":
        [(YOUTUBE_VIDEO_SYSTEM_PROMPT, PREV_YOUTUBE_VIDEO_CFG07A_SYSTEM_PROMPT)],
    "prompts.webpage_system_prompt":
        [(WEBPAGE_SYSTEM_PROMPT, PREV_WEBPAGE_CFG07A_SYSTEM_PROMPT)],
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
        [(SUMMARY_EDITOR_SYSTEM_PROMPT, PREV_SUMMARY_EDITOR_R1025_HOTFIX4)],
    "prompts.factcheck_analyst_system_prompt":
        # UNIFIED-CORE (C13): откат снимает только ступень C13 (мёртвый
        # tone_hint) — на непосредственный прежний прод-канон с полем.
        [(FACTCHECK_ANALYST_SYSTEM_PROMPT,
         PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT)],
    # 10.27 (ASAP-2): откат ступени R1027 ведёт на НЕПОСРЕДСТВЕННО прежний
    # канон PREV_*_R1027 (полный канон R1026 с блоком маркировки) — снимается
    # только шаг many-to-many/смысла, стек ступеней сохраняется (ADR-1013-3).
    # ASAP 4.1 волна 3 (T-4607/T-4609): откат map-канона/блока источника —
    # на НЕПОСРЕДСТВЕННО прежний прод-канон 2.58.46 (rollback-паритет с
    # kill-switch SUMMARY_L1_SEMANTIC_MAP_ENABLED/SUMMARY_WRITER_SOURCE_
    # INPUT_ENABLED=false; read-side смещение через существующую лестницу).
    "prompts.summary_l1_clusterizer_system_prompt":
        [(SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
         PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41)],
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
    # SPEECH-P0-B2 (25.10.2026): новая верхняя ступень — P0-фактологический
    # канон; первый вызов снимает ТОЛЬКО её (на прод-байты 2.58.130 —
    # PREV_SUMMARY_L2_WRITER_R1030_P0), второй — историческую ступень
    # источника (R1029, 2.58.46). Стек ступеней цел (ADR-1013-3).
    "prompts.summary_l2_writer_system_prompt": [
        (SUMMARY_L2_WRITER_SYSTEM_PROMPT, PREV_SUMMARY_L2_WRITER_R1030_P0),
        (PREV_SUMMARY_L2_WRITER_R1030_P0,
         PREV_SUMMARY_L2_WRITER_R1029_ASAP41)],
    # 10.28 (ASAP-2.1): откат Рассказчика — на прежний канон R1028 (до правки
    # §25); ключ в PG не удаляется.
    # LEGFIX (22.10.2026): откат снимает ТОЛЬКО ступень LEGFIX — на
    # непосредственный прежний канон (слепок PREV_SUMMARY_NARRATOR_LEGFIX);
    # стек ступеней цел (ADR-1013-3).
    "prompts.summary_narrator_system_prompt":
        [(SUMMARY_NARRATOR_SYSTEM_PROMPT, PREV_SUMMARY_NARRATOR_LEGFIX)],
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

#: ADDENDUM #2 (24.10.2026): принцип свободы речи на уровне личности. Патч
#: вставляет ОДИН абзац перед «Грубость»/«Ритм» (после абзаца о реальных
#: событиях), только если смысла ещё нет; идемпотентно, авторские байты целы.
_CORE_FREE_SPEECH_ANCHOR = "Свобода речи."
_CORE_FREE_SPEECH_EQUIVALENT = ("внешним настройкам безопасности",
                                "свободно и прямо")
_CORE_FREE_SPEECH_CHANGE = "added: " + _CORE_FREE_SPEECH_ANCHOR
_CORE_FREE_SPEECH_INSERT_ANCHORS = _CORE_INSERT_ANCHORS


def _core_has_free_speech_meaning(text: str) -> bool:
    """Принцип свободы речи уже прямо выражен владельцем?"""
    if _CORE_FREE_SPEECH_ANCHOR in text:
        return True
    return all(marker in text for marker in _CORE_FREE_SPEECH_EQUIVALENT)


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
    имеющийся смысл не дублируется. ADDENDUM #2 (24.10.2026): затем так же
    вставляется абзац «Свобода речи» перед «Грубость»/«Ритм». Возврат
    ``(patched, changes)``: ``changes`` — список удалённых фрагментов и, при
    вставке, маркеры ``added: …`` (пусто = править нечего, идемпотентно).
    Никогда не бросает; на пустом/нестроковом входе — ``(вход, [])``.

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
        if not _core_has_free_speech_meaning(patched):
            block = "\n\n" + CORE_FREE_SPEECH_PARAGRAPH
            for anchor in _CORE_FREE_SPEECH_INSERT_ANCHORS:
                if anchor in patched:
                    patched = patched.replace(anchor, block + anchor, 1)
                    break
            else:
                patched = patched.rstrip() + block
            changes.append(_CORE_FREE_SPEECH_CHANGE)
        return patched, changes
    except Exception:      # pragma: no cover — патч не роняет миграцию
        return str(text or ""), []


#: Ключ отчёта/лога шага Core-патча (значение — маркер, не текст канона).
CORE_PATCH_REPORT_KEY = "character.core"
CORE_PATCH_APPLIED = "core_patched"


def _core_change_log_labels(changes: list[str]) -> tuple[list[str], int]:
    """R17-safe метки изменений: ``added: <заголовок>`` → заголовок, прочее —
    счётчик удалённых служебных фрагментов (их текст в лог не попадает)."""
    added: list[str] = []
    removed = 0
    for change in changes:
        if change.startswith("added: "):
            added.append(change[len("added: "):])
        else:
            removed += 1
    return added, removed


async def migrate_core_owner_patch(cache) -> dict[str, str]:
    """Штатная миграция активной авторской редакции Full Core (B1-фикс).

    Делегирует решение ``owner_preserve_core_full_patch`` (единственный
    owner-preserving патч): он добавляет недостающие абзацы владельца
    («Как говорить о реальных событиях», «Свобода речи») и НЕ переписывает
    авторские байты. Здесь только безопасная проводка в старт:

    * читается ГЛОБАЛЬНЫЙ документ ``character.core`` (per-chat overrides не
      трогаются — как и в остальных миграциях канонов);
    * пустой ``full_text`` / документа нет → действует заводская редакция
      (в ней оба абзаца уже есть) → no-op;
    * байты прежних заводских v1/v2 → no-op: их ведёт superseded-гвард
      ``prompt_registry.core_selection`` (патч их не переписывает);
    * запись — только когда патч реально что-то добавил, через штатный
      ``write_speech_value`` (журнал провенанса + history), с
      ``set_level=False``: выбор владельца ``detail_level`` не меняется;
    * идемпотентно: повторный прогон видит смысл и возвращает пустой отчёт;
    * откат: добавленные абзацы остаются в истории ревизий
      (``character.prompt_history``), поэтому прежняя редакция восстановима;
      автоматическое вырезание авторского текста не выполняется намеренно.

    Возвращает ``{"character.core": "core_patched"}`` при вставке, иначе ``{}``.
    Никогда не бросает: сбой шага не отменяет миграцию канонов.
    """
    report: dict[str, str] = {}
    try:
        if cache is None or not getattr(cache, "pg_available", False):
            logger.info("[prompt_migration] core patch skip: PG недоступен")
            return report
        from services import prompt_registry as pr
        from services.prompt_factory import _doc_from_raw, write_speech_value

        raw = cache.get(pr.CORE_DOC_KEY, None)
        if raw is None:
            logger.info("[prompt_migration] core patch: документа владельца "
                        "нет — действует заводская редакция | key=%s",
                        pr.CORE_DOC_KEY)
            return report
        document = _doc_from_raw(raw)
        source = pr.doc_field_text(document, "full_text")
        if not source.strip():
            logger.info("[prompt_migration] core patch: полной редакции "
                        "владельца нет | key=%s", pr.CORE_DOC_KEY)
            return report
        patched, changes = owner_preserve_core_full_patch(source)
        if _CORE_SUPERSEDED_NOTE in changes:
            logger.info("[prompt_migration] core patch: прежняя заводская "
                        "редакция — ведёт superseded-гвард | key=%s | sha=%s",
                        pr.CORE_DOC_KEY, pr.sha12(source))
            return report
        if not changes:
            logger.info("[prompt_migration] core patch: абзацы уже есть, "
                        "авторские байты целы | key=%s | sha=%s",
                        pr.CORE_DOC_KEY, pr.sha12(source))
            return report
        result = await write_speech_value(
            pr.CORE_FULL_BLOCK_ID, patched, cache=cache,
            reason="core_patch_migration", set_level=False)
        if not result.get("applied"):
            logger.warning("[prompt_migration] core patch: запись отклонена | "
                           "key=%s | reason=%s", pr.CORE_DOC_KEY,
                           result.get("reason", ""))
            return report
        added, removed = _core_change_log_labels(changes)
        report[CORE_PATCH_REPORT_KEY] = CORE_PATCH_APPLIED
        logger.info("[prompt_migration] core patch: добавлены абзацы | key=%s "
                    "| added=%s | removed=%d | chars=%d->%d | sha=%s->%s",
                    pr.CORE_DOC_KEY, ",".join(added) or "-", removed,
                    len(source), len(patched), pr.sha12(source),
                    pr.sha12(patched))
        return report
    except Exception:      # pragma: no cover — патч не роняет старт
        logger.warning("[prompt_migration] core owner patch failed",
                       exc_info=True)
        return report


async def _attest_migrated_canon(cache, key: str, value: str) -> None:
    """P0-PROMPTS (24.10.2026): записать канон через провенанс реестра.

    `_mark_provenance` делает мигрированный заводской канон ДЕЙСТВУЮЩИМ слоем
    (иначе резолвер удерживает его как `provenance_missing`). Идемпотентно:
    если аттестованная ревизия уже совпадает с байтами — записи нет.
    Best-effort: сбой журнала не отменяет уже выполненную миграцию значения.
    """
    from services import prompt_registry as pr
    spec = pr.by_pg_key(key)
    if spec is None or not pr.withholding_required(spec):
        # Провенанс нужен только блокам, которые иначе удерживаются; остальные
        # каноны не создают ложного withheld.
        return
    entry = pr.attested_revision(spec.block_id, cache=cache)
    if entry and str(entry.get("sha256_12") or "") == pr.sha12(value):
        return
    try:
        from services.prompt_factory import _mark_provenance
        await _mark_provenance(cache, spec.block_id, pg_key=key, value=value,
                               kind="factory_reset",
                               reason="canon_migration")
    except Exception:      # pragma: no cover — журнал не роняет миграцию
        logger.warning("[prompt_migration] провенанс канона не записан | "
                       "key=%s", key, exc_info=True)


async def migrate_prompt_canons(cache) -> dict[str, str]:
    """Авто-миграция канонов промптов (раунд 5): канон → новый канон;
    кастом юзера НЕ трогаем; PG down / ключ отсутствует → skip с логом
    [prompt_migration]. Возврат: dict обновлённых ключей (пусто — ничего
    не обновлено). Вызывается из bot.py main() сразу после cache.init().

    B1 (24.10.2026): после ступеней канонов тем же стартом выполняется
    owner-preserving патч активной авторской редакции Full Core
    (``migrate_core_owner_patch``) — иначе новые абзацы владельца не доезжали
    до действующей редакции в PG.
    """
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
            # P0-PROMPTS: значение уже новый канон, но провенанс мог быть
            # потерян прежней миграцией — аттестуем идемпотентно.
            await _attest_migrated_canon(cache, key, matched[1])
            logger.info("[prompt_migration] уже новый канон | key=%s", key)
            continue
        new = matched[2]
        await cache.set(key, new, "prompts")
        await _attest_migrated_canon(cache, key, new)
        report[key] = "updated"
        logger.info("[prompt_migration] канон обновлён | key=%s", key)
    # B1 (24.10.2026): активная авторская редакция Full Core получает новые
    # абзацы владельца тем же стартом (owner-preserving патч, идемпотентно).
    report.update(await migrate_core_owner_patch(cache))
    return report


async def rollback_prompt_canons(cache) -> dict[str, str]:
    """Обратная канон-миграция раунда 10.21 (F3 Д9, ADR-1021-3 §5).

    Снимает у каждого ключа ровно ОДНУ ступень своей цепочки
    (`ROLLBACK_MIGRATIONS`): сначала текущий канон → непосредственный прежний,
    повторный вызов — следующая ступень, пока не достигнут последний `old`
    (целевой прод-канон отката). Идемпотентна: на последней ступени — no-op.
    Кастом юзера не трогаем (WARNING), ключ отсутствует / PG down — skip.
    Вызывается вручную (runbook @DevOps) при откате `git revert` — столько
    раз, сколько ступеней нужно снять (L1 R3b: 2 вызова до канона 2.58.113,
    L2: 2 вызова — P0-канон → прод-байты 2.58.130 → R1029/2.58.46)."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[prompt_rollback] skip: PG недоступен")
        return report
    for key, steps in ROLLBACK_MIGRATIONS.items():
        current = cache.get(key)
        if current is None:
            logger.info("[prompt_rollback] ключ отсутствует | key=%s", key)
            continue
        target = None
        for new, old in steps:
            if current == new:
                target = old
                break
        if target is None:
            if current == steps[-1][1]:
                logger.info("[prompt_rollback] уже прежний канон | key=%s",
                            key)
            else:
                logger.warning("[prompt_rollback] кастом юзера — НЕ трогаем | "
                               "key=%s | chars=%d", key, len(current))
            continue
        await cache.set(key, target, "prompts")
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
