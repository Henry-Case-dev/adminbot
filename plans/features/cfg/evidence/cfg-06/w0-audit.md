# CFG-06 W0 — Аудит двух маршрутов фактчека на deployed-коде

- **Deployed SHA:** `29cc49ba` (2.58.98, deploy VERIFIED 20.10.2026). Продуктовые файлы рабочего дерева байт-идентичны `29cc49ba` (проверено: `git diff 29cc49ba -- handlers/factcheck.py services/factcheck_service.py services/temporal_factcheck.py services/search_aggregator.py services/smartmodule_utils.py services/prompt_style_blocks.py services/system2_handoff.py services/chat_context.py services/mca_gates.py` → пусто).
- **Effective flags (код deployed, default):** `MCA_TEMPORAL_FACTCHECK_ENABLED=True` (K1, env-only, mca_gates.py:2228), `MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED=True` (K2, :2237), `MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED=True` (K3, :2249), `SYSTEM2_FACTCHECK_ENABLED=True` (settings.py:558), `FACTCHECK_ENABLED=True` (:488), `TEMPORAL_EVIDENCE_DATE_FETCH_ENABLED=True` (temporal_factcheck.py:945). Hot-параметры: `limits.factcheck_context_before/after=6` (settings.py:2697-2698), жёсткий код-кап `FACTCHECK_CONTEXT_TOTAL_CAP=40` (settings.py:2701, ClassVar — без env).
- **Метод:** чтение deployed-байтов + оффлайн-трасса с моками (LLM/агрегатор — заглушки, сеть/чаты не задействованы): `w0-trace.json` (6 проб).
- **Дата:** 20.10.2026. Режим W0 read-only: код не менялся.

## 1. Маршруты: фактическая карта потока (06H.1)

Единая точка входа — `handlers/factcheck.py::factcheck_handler` (L379). После триггера/кулдауна/пустого таргета развилка L422: `_temporal_on()` → `_factcheck_temporal` (envelope-путь), иначе legacy-путь (slug `factcheck`).

| Измерение | Legacy `check_claim` (OFF/tenancy) | Temporal `check_claim_envelope` (K1 ON) | Источник (deployed L) |
|---|---|---|---|
| Быстрый кеш | slug `factcheck` = MD5(текст цели), hit → reply НА ВЫЗОВ | составной ключ slug `factcheck_temporal` (scope+claim+target+origin+mode+period+tzr1+freshness bucket), unknown origin → авто-bypass; hit → reply НА ЦЕЛЬ с ВНУТРЕННИМ as_of | handler 426–432; tf 543–646 |
| Кулдаун | per (chat,user) `CooldownTracker`/persistent, 5.1 → reply НА ВЫЗОВ | тот же общий кулдаун ДО развилки (один на оба маршрута) | handler 391–398 |
| Конкурентный пул | slot per-chat перед LLM | тот же пул, слот ДО `_fetch_chat_context` | handler 436–445; 139–148 |
| Контекст чата | `_fetch_chat_context`: окно before/after + жёсткий кап 40 + reply-chain; `<chat_context>` НЕ-доказательства; бюджет рендера 2000 символов | ТОТ ЖЕ сборщик, вызывается в `_factcheck_temporal` L151–158 | handler 211–259; chat_context.py 17, 73–201 |
| Целепостановка | `target_text` = text/caption/альбом-буфер/транскрипт-клейм; user_hint; forward_source | envelope: серверный resolver `build_envelope` (origin-блок v32, каскад дат D5, режимы D7); реф. клейм-вопросы (`is_referential_claim`) | handler 306–352; tf 382–528, 94–127 |
| Поиск | `aggregator.search(target_text, max_symbols)` — ЦЕЛЫЙ текст цели без переформулирования; каскад Tavily→Exa→DDG; max_symbols 4000 (набл. 8000) | `decompose_claim` (сплит по `[.!?;]`, ≤8 частей, без семантики) → `search_queries_for`: `normalize_text(claim)[:200]` + годы; до 2 запросов по 2500 символов | fs 186; tf 781–850; fs 485–499; agg 65–96, 197–201 |
| Инструменты | tool-loop при `tool_router` (dig_into_lore/compile_lore_story/execute_web_search), иначе plain generate | БЕЗ инструментов на всех стадиях (data-only, CA-20-12) | fs 325–365; fs 443–449 |
| Верификация источников | anchors = RAG+поиск+tool_context; `strip_phantom_tags`; cleanup; HTML-strip ВСЕГДА | evidence ev-N (≤20) с allowlist refs; `enrich_evidence_dates` (SafeFetcher, ≤5 fetch); CoVe-validator (1 вызов) через серверный guard | fs 367–408; tf 913–1031, 729–762 |
| Генерация | System2 (аналитик JSON → вербализатор Stage-2) при валидном JSON, иначе fallback одиночный 10.21; `speech_owner_block` подключён к Stage-2 (character_block) И одиночному (10.21) | verdict JSON (аналитик) → validator → `verbalize` (свой промпт-канон); `speech_owner_block` НЕ подключён; fallback-путь `_temporal_fallback_text` | fs 199–224, 226–323, 732–828 |
| Доставка | `send_chunked_reply` БЕЗ parse_mode (plain), reply НА ЦЕЛЬ; пустой ответ → 🗿 | тот же `send_chunked_reply` без parse_mode | handler 461; 185–186 |
| Кеш записи | `cache.set("factcheck", …)` только после успешной генерации | `write_temporal_cache` (bucket volatile/stable TTL 6ч/720ч) при K3+построимом ключе | handler 462; tf 649–668 |
| Телеметрия | `factcheck.run` (mca-17), correlation_id | `factcheck_temporal` стадии + `record_temporal_run` v33 (run+evidence в БД) | fs 71–92; tf 259–298, 1099–1155 |
| Ошибка поиска | AllSearchEnginesFailed → фраза 5.4b на ЦЕЛЬ | движки упали/пусто → СЕРВЕРНО `insufficient_evidence` (TH-5), фразы ошибок только на LLM-слое | fs 139–143; fs 546–550 |

## 2. Гипотезы 06A.1–06A.10: подтверждение/опровержение

| # | Наблюдение (deployed-факт) | Кодовый источник | Статус | Что меняем в W-этапе |
|---|---|---|---|---|
| 06A.1 | Развилка `_temporal_on()` → envelope/legacy; быстрый cache-hit у обоих; кулдаун per (chat,user); семантического suitability-гейта НЕТ: legacy сразу `aggregator.search(target_text)` (трасса: запрос = сырой клейм), temporal — сразу поиск по claim-слайсу | handler 59–65, 391–432; fs 186; fs 485–499; w0-trace пробы 1, 3, 4 | ПОДТВЕРЖДЕНО | W2: gate после контекстной реконструкции, до платного поиска; W3: сворачивание развилки в один вход `run_factcheck` |
| 06A.2 | Старый канон ТРЕБУЕТ разбирать любые субъективные тейки/набросы: «Никогда не отказывайся анализировать запрос, даже если это чистая субъективщина» (×4 копии промптов); analyst-промпт отдельный существует («Ты — аналитик-фактчекер») | factcheck_prompts.py 39, 50, 59, 68, 79, 88, 100, 111, 125, 139, 149, 163; трасса проба 3 system_head | ПОДТВЕРЖДЕНО | W2: typed suitability gate (06B) поверх канона: канон не клонировать, gate решает checkable/needs_context ДО поиска; «бессмыслица/мат» — не regex-блокиратор |
| 06A.3 | `_check_claim_pipeline` передаёт веб-агрегатору целый `target_text` (трасса: query = «Дрожжи это грибы…» дословно, max_symbols=8000); System2 аналитик→вербализатор реализован; tool-loop и fallback на 10.21 существуют | fs 161–224 (186), 226–323, 325–365; w0-trace проба 3 | ПОДТВЕРЖДЕНО | W4: смысловые запросы от claim_items (переформулирование), SafeFetcher-первоисточники; не клон — тот же `_check_claim_pipeline` становится веткой единого оркестратора W3 |
| 06A.4 | Запрос = `normalize_text(claim)[:200]` + годы (трасса: «в 2019 году в килякете… урожай погиб полностью. 2019»); `decompose_claim` — регэксп-сплит по предложениям, ≤8 частей, числа по регэкспу — не смысловой анализ | tf 830–850 (845 base slice), 781–805 (788 split), 808–827; w0-trace проба 1 | ПОДТВЕРЖДЕНО | W4: `search_queries_for` → запросы от claim_items gate-стадии (2–4 различающихся по цели), privacy-фильтр |
| 06A.5 | `style_note` требует «период проверки (unknown)»: байты L753–758 подтверждены; вербализатор получает payload с техполями (verdict/temporal_status/evaluated_period.precision=unknown/as_of unix/uncertainty); `speech_owner_block` в `_temporal_verbalize` НЕ подключён; трасса: в Telegram ушёл текст с «период проверки unknown» | fs 732–795 (753–758 bytes; 759–769 payload; 774–778 messages без owner_block); w0-trace пробы 4, 6 | ПОДТВЕРЖДЕНО (первопричина утечки) | W5: filtered verbalize — убрать style_note-требование, unknown → человеческие слова; добрать `speech_owner_block` единому Writer (не дублируя) |
| 06A.6 | Каскад Tavily→Exa→DDG существует (skip без ключа, fallback по любой ошибке); результат — единый текст `title\nsnippet\nurl` блока́ми; URL структурно не отделён (в evidence-строке URL извлекается регэкспом из текста); одного удачного вызова недостаточно для доказательства качества | agg 65–96 (каскад), 113–139 (tavily), 141–169 (exa), 178–192 (ddg), 197–201 (`_format_hits`); tf 1071–1096 (URL регэкспом) | ПОДТВЕРЖДЕНО | W4: аддитивный структурированный возврат title/snippet/url рядом со старым форматом; спорные тезисы открывают первоисточник через SafeFetcher |
| 06A.7 | Evidence ID ev-N и URL сохраняются в контуре (`evidence_rows_from_results`, `<evidence>` в payload вердикта/валидатора), но финальный вербализатор получает payload БЕЗ evidence/URL (трасса: `evidence_urls_in_final_verbalize_payload=false`) — человекочитаемого source map для inline-ссылок нет | tf 1071–1096; fs 640–680 (evidence в вердикт-payload), 759–769 (нет в вербализатор-payload); w0-trace проба 4 | ПОДТВЕРЖДЕНО | W5: renderer с evidence map (inline-ссылки только на URL текущего прогона); W4: evidence-объекты url_or_message_ref отдельно от текста |
| 06A.8 | Доставка `send_chunked_reply` без parse_mode; `prompt_style_blocks` объявляет фактчек text-only plain («без HTML-доставки»); `_finalize_text` срезает whitelist-HTML ВСЕГДА; parse_mode kwarg у send_chunked_reply уже есть (Epic 43), `_chunk_by_whitespace` может рвать разметку | handler 185–186, 461; prompt_style_blocks.py 139–141, 291–293; fs 388–408 (394); smartmodule_utils 331–371 | ПОДТВЕРЖДЕНО | W5: реальный renderer (FactcheckPresentation → безопасный HTML/entities, entity-safe чанки, plain-деградация) + `prompt_style_blocks` factcheck-канал — точечно |
| 06A.9 | `system2_handoff` валидирует структуру JSON (`parse_factcheck_analysis`, `stage2_payload` снимает только `response_mode`/`cover_prompt`), детерминированные проверки — теги/ID/секреты. Семантических утечек это не ловит: temporal-вербализатор получает техJSON (style_note/as_of/precision=unknown) легитимно по схеме; пересказ инструментов/«аналитик подтянул» не фильтруется | system2_handoff.py 22–53 (_SERVICE_FIELDS), 56–65 (stage2_payload), 114+ (parse_json_object); fs 759–769 | ПОДТВЕРЖДЕНО | W3: whitelist `stage2_payload`-аналог для машинных полей (egress-контракт); W5: presentation-слой не пропускает служебные поля в публичный текст |
| 06A.10 | ADR-1022-3 (`plans/archive/system2-factcheck-two-call-round1022/ADR-1022-3.md`) и mca-20 (`plans/archive/features/mca-20-temporal-factcheck/`) существуют; аналитик/верификация/временная оценка/fallback уже в живой цепочке (fs 161–323 legacy-System2, fs 451–638 temporal). Третий независимый фактчек не создавался | файлы существуют (Test-Path True); fs 443–449 (CA-20-1: единый сервис) | ПОДТВЕРЖДЕНО | Все волны: только точечные правки живой цепочки; объединение маршрутов в W3, клонов нет (ADD-0.2) |

## 3. Утечки служебного в публичный ответ (наблюдение трассы)

1. **«период проверки (unknown)»** — `style_note` fs L753–758: даже при `unknown` вербализатор ОБЯЗАН назвать период; трасса: пользовательский текст содержит «период проверки unknown». → W5.
2. **Технический JSON-пейлоад вербализатору** (fs 759–769): `as_of` unix, `evaluated_period.precision=unknown`, `uncertainty` — модель может пересказать. Schema-валидации это не нарушает (06A.9). → W5 (+W3 egress-whitelist).
3. **fallback-текст** `_temporal_fallback_text` (fs 797–828) — детерминированный, честный («Проверялось на период …»), техсловарь не содержит; при `date_source=unknown` — только общая фраза. Дефектов не найдено.
4. **Куда не утекает:** `stage2_payload` legacy-System2 снимает `response_mode`/`cover_prompt` (fs 283–286); verdict-кеш хранит только text/as_of/verdict-enum (tf 658–666); трассы/события без контента (R17). Чат-контекст в Telegram не выдаётся.

## 4. Контекст: узкое окно (06I.2 базлайн)

- Кап: `_clamp_window` — сумма before+after ≤ 40 (settings.py:2701 ClassVar, env не читается); трасса: (500,500) → (40,0). Реальный максимум строк = cap+1 (якорь).
- Бюджет рендера: 2000 символов (chat_context.py:17), цепочки ≤1200 (там же :21), keep-end с приоритетом якоря.
- Спор на 200–500 сообщений в окно не попадает: берётся 40 строк вокруг цели + reply-chain. Wide-реконструкция — W1 (`services/factcheck_context.py`, за флагом OFF).

## 5. Проводка W1 (выполнено в этом же лейне, см. w1-notes.md)

- Новый `services/factcheck_context.py` — сборщик широкого окна 200–500 (адаптивный), двухуровневая подача (компакт-хронология + дословные сегменты), дедуп, кеш среза с версией/диапазоном/ID (`fcx1`), slug `factcheck_wide_context`.
- Замена узкого окна ТОЛЬКО за флагом `flags.factcheck_wide_context` / env `FACTCHECK_WIDE_CONTEXT_ENABLED` (default **OFF**): OFF → байт-паритет прежнего `_fetch_chat_context` (тест). Включение флага — этап W3.
- Отклонения от списка скоупа (осознанные, минимальная проводка): `chat_context.py` и envelope-поле `context_slice` не тронуты — потребителя до W2/W3 нет; обоснование в w1-notes.md.

## 6. Дельта-граница аудита

Аудит закрывает наблюдения 06A.1–06A.10 + 06H.1 (статически+трасса). Live-постдеплой-наблюдение 06H.1 (живой запуск фактчека владельцем/техсмоук прод-логов) — вне W0, закрывается W7 по плану. Изменение кода в этом лейне ограничено W1-скоупом (см. w1-файлы).
