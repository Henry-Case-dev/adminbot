# MCA-15 `mca-15-chat-statistics` — spec (design-freeze, Step 2 @Architect, 05.10.2026)

- **Фича:** `mca-15-chat-statistics` (эпик `memory-context-autonomy`, Wave 2; deps `mca-03`+`mca-07` закрыты; приоритетный хвост после `mca-08`).
- **Статус:** `DESIGN_FROZEN` — T-4917 выполнен; санкции T-4918 выданы (§9); Builder T-4919+ разрешён.
- **ADR:** `adr-1028-12-chat-statistics.md` (D1–D10 + AMEND-регистр; Proposed → Accepted по merge, ожидаемый раздел `plans/ARCHITECTURE.md` **§116** — следующий свободный на 05.10.2026, подтвердить на merge).
- **Источник:** `plans/current_task.md:1094–1171` (§24) + probe `:1283–1321` (§26); приёмки §19 `:919–923` (A38–A42); §20.2 `:1017`; §27.1 `:1358`; план `mca-round1027-plan.md:135–138, 202, 235, 208`.
- **Входные документы:** `requirements-map.md` (MCA15-R1…R4, CA-15-1…10), `tasks.md` (T-4916…T-4941).
- **Базовая точка:** HEAD `f1cacbd` (PM-архив mca-08 поверх `5e079d1`; код-база **2.58.55**), прод **2.58.55**, SQLite **v26**, каталог **489**, canon `TOOL_CALLING_TOOLS == 12`, PG — no-op база. `plans/current_task.md` не изменяется (R17/R18).

**Re-верификация якорей 05.10.2026 (по текущему дереву; mca-08 `3d03ff6` затронул `database.py`/`direct_chat_service.py`/`negative_constraints.py`/`mca_gates.py`/`mca_events.py`/`mca_process_registry.py`/`settings.py`):**

| Якорь requirements-map | Факт сейчас | Комментарий |
|---|---|---|
| `summary_memory.py:877` `build_fts_query` | ✅ `:877` | prefix-OR (`"kw"*`); не затронут |
| `summary_memory.py:2369` `count_mentions` | ✅ `:2369` | prefix-OR-семантика; legacy-путь |
| `database.py:5834` `search_messages_fts_count_by_author` | ✅ `:5834` | COUNT(*) сообщений, GROUP BY `author_name,user_id`, since/until в SQL |
| `database.py:5830` `search_messages_fts_count` | ⚠️ def `:5813`, `:5830` — return | сдвиг внутри метода (mca-08 не менял тело счётчиков) |
| `tool_router.py:336` `_dig_json_payload` | ✅ `:336` | финальный минимум `{truncated,total_mentions}` `:377–380` |
| `tool_router.py:606/673` `_query_chat_memory`/`_dig_into_lore` | ✅ `:606`/`:673` | рендер «Найдено N упоминаний» `:667`; graph-expansion `:697–712`; счётчик fail-open `:831–855`; `total_mentions` `:862` |
| `lore_compiler_service.py:70` | ✅ `:70` | stats через `search_messages_fts_count_by_author` `:108`; `total_mentions` `:138`; слияние по имени `_mentions_by_authors` `:253–260` |
| `lore_prompts.py:285` `build_lore_story_user` | ✅ `:285` | блок «Статистика: упоминаний…» `:305–318` |
| `mca_retrieval_context.py:452` `retrieve()` | ✅ `:452` | единая точка mca-07 |
| `negative_constraints.py:342` `verbalize_validated` | ⚠️ **`:434`** (было `:342` до mca-08) | mca-08 добавил `form_contract`/`fallback_text` + G1–G3; точки входа: direct `direct_chat_service.py:2728`, factcheck `factcheck_service.py:195`, summary `summary_generator.py:3309` |
| `tool_schemas.py:539` canon 12 | ✅ `:539`; `TOOL_CALLING_TOOLS` `:489–502` | `query_chat_memory` `:82`, `dig_into_lore` `:111` |
| `mca_gates.py:29` KILL_SWITCHES | ✅ `:29`; mca-08 K1–K4 `:257–278`; резолверы `:808–840` | |
| `mca_events.py:60` REASON_CODES | ✅ `:60`; mca-08 ровно +9 `:216–227` | единый словарь |
| `mca_process_registry.py` | ✅ `direct.reply` `:508`; `style.scope` `:536`; placeholder `episodes.timeline` owner `mca-15` `:821–827` | placeholder будет заменён реальным процессом (§10) |
| `database.py` реестр mca-14 | ✅ `MigrationStep` `:1184`; `migration_steps()` `:1820`; latest v26 `:1899` | v27 НЕ санкционируется (§9.1) |
| `direct_chat_service.py:2425–2427` lore-обход verbalizer | ✅ | готовый `lore_story` доставляется как `answer` |
| `settings.py:2840` APP_VERSION | ✅ `2.58.55` | |

---

## 1. Scope и трассировка

| REQ | Суть | §spec | Задачи |
|---|---|---|---|
| **MCA15-R1** | Воспроизводимый дефект; intent `social_banter`/`historical_evidence`/`chat_statistics`; без жёсткой реплики; reason_code цели | §6, §8 | T-4919…T-4922 |
| **MCA15-R2** | ChatStatistics/StatsQuery; единицы/режимы; author≠subject; фильтры до LIMIT; канонические ID; dedup/watermark; bounded | §3, §4 | T-4923…T-4928 |
| **MCA15-R3** | MetricResult/NumericClaim; контроль на всех путях; ≤1 коррекция; truncation; honest null | §5, §7 | T-4929…T-4933 |
| **MCA15-R4** | Диагностика §24.5 + регрессии | §10, §11 | T-4934…T-4936 |
| GEN-R17 (контракт) | Реестр процесса/стадий, widget-ID для mca-17c | §10 | T-4935 |

**В scope:** StatsQuery/measurement поверх существующих репозиториев; MetricResult/NumericClaim и контроль чисел на всех путях отправки; intent-различение; FIX измерительных путей §24.1; диагностика/наблюдаемость; focused/регрессионные тесты §24.5.
**Явно вне scope:** денежные лимиты/бюджеты и ToolResult-контракт цепочек (mca-11); Intent/Decision lifecycle и action-schema (mca-09); lessons/reward (mca-16); UI/рендер/диагностические действия (mca-17c); SelfModel (mca-18); вторые retrieval/identity/provenance/постпроцессор/словарь событий/очередь/координатор/LLM-провайдер; durable metric-кеш (не санкционирован).

## 2. Инварианты (сквозные)

1. **OFF-паритет:** каждый kill-switch (K1–K3, §9.3) OFF → соответствующая поверхность **байт-в-бит 2.58.55** (тексты, payload, БД-записи, события); все три OFF — полный паритет.
2. **Вторых механизмов нет:** измерение — один сервис `services/chat_statistics.py`; постобработка чисел — существующий `verbalize_validated` (+`negative_constraints`-хелперы); retrieval — только `retrieve()` mca-07; identity — mca-03; словарь событий — один.
3. **Канон 12:** `TOOL_CALLING_TOOLS` не меняется; stats-режим — аддитивный параметр существующего `query_chat_memory`.
4. **M-MCA07-2/action-schema:** поля EvidenceBundle и `CoordinatorDecision.action` (`reply/react/silent/tool`) не меняются; intent-значения — аддитивны.
5. **R17:** в durable-логи/события — ID/коды/числа/хэши; сырой/нормализованный текст запроса и сообщений не журналируется; диагностика опирается на `query_spec_hash` + метод/область/счётчики.
6. **Число не хранится как вечный факт о человеке:** MetricResult живёт в рамках хода; повторный запрос — пересчёт; никакого durable-кеша/снапшот-таблицы (§9.1).
7. **Честные статусы:** ошибка/таймаут ≠ 0; неполный корпус ≠ «никогда»; unsupported ≠ «ничего не найдено».

## 3. D1 — StatsQuery и измерение (MCA15-R2)

**Один сервис** `services/chat_statistics.py` (чистые контракты + исполнение поверх существующих репозиториев; без LLM, без второго FTS-движка).

### 3.1. Контракт `StatsQuery` (frozen dataclass)

| Поле | Значения | Семантика |
|---|---|---|
| `metric` | `messages` / `occurrences` / `distinct_authors` | единицы измерения; по умолчанию `messages` |
| `match_mode` | `exact_phrase` / `token` / `prefix` / `all_terms` / `any_terms` | фраза (quoted FTS) / один токен / явный prefix (`"term"*`) / AND / OR |
| `text` / `terms` | фраза и/или список | `exact_phrase` требует `text`; `all_terms`/`any_terms` — ≥2 terms |
| `author_ids` | канонические user_id | фильтр автора (НЕ имя); резолв имён → ID — на tool-слое (§4.3) |
| `subject_ids` | канонические ID субъекта | отдельная семантика: «о ком»; при отсутствии подтверждённой атрибуции (mca-22/provenance) → `unsupported`, не угадывать |
| `chat_id` | int | обязателен |
| `interval` | `from`/`to` unix (nullable) | окно по `timestamp` в SQL **до** LIMIT |
| `timezone` | tz-имя | только для человекочитаемых дат (прецедент `LoreCompilerService._date:277`) |
| `source_kinds` | `live` / `import` / `any` | `live` = `import_key IS NULL`, `import` = `import_key IS NOT NULL` (одна таблица `smart_messages`) |
| `sender_kinds` | `human` / `bot` / `unknown` / `any` | без надёжного поля «бот» в корпусе: `human`/`bot` → `unsupported`; `unknown`/`any` — считаются все, unknown отдельным счётчиком |
| `quote_forward` | `include` / `exclude` / `only` | по метаданным `is_forward`/`forward_source`/`quote_text`; нет метаданных → `unknown_count`, не угадывать |
| `normalization_version` | `"cs-norm-1"` | канон нормализации пробелов/регистра/пунктуации; участвует в `query_spec_hash` |
| `corpus_scope` | `smart_messages` (дефолт) | двуххранилищная политика §3.4 |

`query_spec_hash` = sha256 канонизированной JSON-спеки (без сырого текста наружу). Инвариант: **фильтры count и examples строятся из одной нормализованной спеки и действуют в SQL до LIMIT**; примеры выбираются из той же выборки.

### 3.2. Метрики и методы

- `messages` — `COUNT(*)` сообщений, где FTS-совпадение ≥1 (единица: сообщения; REUSE `search_messages_fts_count*`).
- `occurrences` — число вхождений токенов/фразы внутри текстов совпавших сообщений (единица: вхождения). Метод: bounded keyset-скан совпавших строк порциями; токенизация — `[а-яёa-z0-9]+` после casefold (unicode61-совместимо), фраза = последовательность соседних токенов, prefix = токены с префиксом. Ярлык метода: `occurrence_method="token_scan_unicode61_v1"`. Лимит `MCA_CHAT_STATS_OCCURRENCE_MAX_ROWS` (env-only, default 20000): превышен → `status=partial`, `value=null`, причина `stats_partial_corpus` (не выдавать частичное число за полное).
- `distinct_authors` — `COUNT(DISTINCT user_id)` по совпавшим сообщениям; `author_name` — **подпись**, не ключ; `user_id IS NULL` → `unknown_count`, не сливается и не приписывается.
- `prefix` не называется морфологией/корнем: `human_label` и method-поле явно пишут «совпадение по префиксу (не морфологический анализ)». Строгий «корень» не вычисляется (вне движка).

### 3.3. FTS-сборка (FIX §24.1 п.1)

`build_fts_query` (`summary_memory.py:877`) расширяется **аддитивным** параметром режима: `build_fts_query(keywords, mode="prefix_or")`; `prefix_or` = текущая формула (все существующие вызовы — байт-паритет). Новые режимы: `exact_phrase` (quoted), `token`, `prefix`, `all_terms` (AND), `any_terms` (OR). Один сборщик, без второго FTS-механизма.

### 3.4. Два хранилища / dedup / watermark

- Корпус сообщений — **один**: SQLite `smart_messages` (+FTS). PG сообщений чата не содержит; запрос, требующий «сумму SQLite+PG», → `unsupported` (не складывать counts без проверки пересечения).
- Канонические ID (mca-03 `(chat_id, tg_message_id)`): live-повтор не создаёт дубль (`save_smart_message_identity:5269`); импорт идемпотентен (`import_key` UNIQUE `(chat_id, import_key)`). Перед измерением — проверка дублей identity в области (REUSE `count_duplicate_identity_rows:2066`); дубли есть → `status=partial` + `stats_partial_corpus` + `excluded_duplicates`, не молчаливый двойной счёт.
- **Watermark/snapshot:** count-запрос возвращает `watermark={max_id, max_timestamp}`; examples читаются с `id <= watermark.max_id` — примеры и число относятся к одной версии данных; `data_as_of` — момент измерения. Долгих транзакций нет; измерение — read-only bounded операция (без новых job-типов/очередей).
- Масштаб (2 млн строк): отбор — FTS/индексы; occurrences — потоковый скан с капом; тяжёлое не блокирует event loop (bounded порции).

## 4. D3 — Tool-поверхность (канон 12, MCA15-R2)

### 4.1. Решение: структурированный режим существующего `query_chat_memory` — **новый инструмент не создаётся**

- В схему `TOOL_QUERY_CHAT_MEMORY` (`tool_schemas.py:82`) добавляется **опциональный** объект `stats` (аддитивно; `TOOL_CALLING_TOOLS` остаётся 12; dispatch-реестр `tool_router.py:555–568` не меняется):
  `metric` (enum), `match_mode` (enum), `phrase`, `terms` (array), `author` (имя/алиас — сервер резолвит в канонический user_id), `quote_forward` (enum), `sender` (enum). `time_range` переиспользуется существующий (расширяется сервером в `interval`).
- Без `stats` → **прежнее** поведение `_query_chat_memory` (K1 OFF — байт-в-бит, включая строку «Найдено N упоминаний»).
- Со `stats` (K1 ON) → вызов `chat_statistics.measure(query)`; результат — типизированный JSON-блок + детерминированная фактическая формулировка; `MetricResult` регистрируется в `ToolContext.metric_results` (аддитивное поле, прецедент `lore_story`/`lore_compiled` `tool_router.py:508–512`).
- Резолв `author` — существующим identity/alias-контуром; неоднозначность → `partial`/`unsupported` + существующий reason `ambiguous_identity`; слияние двух людей по имени запрещено.
- `subject` в LLM-схему **не выносится**: субъектная семантика идёт через `historical_evidence` (§6) и `retrieve()`; StatsQuery-поле `subject_ids` существует для контракта и честно отвечает `unsupported` без подтверждённой атрибуции.

### 4.2. Результат stats-режима

Типизированный JSON (прецедент `_dig_json_payload`): `metric_id`, `status`, `value`, `unit`, `method`, `human_label`, `scope`, `coverage`, `time_bounds`, `data_as_of`/`watermark`, `excluded_count`, `unknown_count`, `examples` (≤ `MCA_CHAT_STATS_EXAMPLES_MAX`, env-only default 20), `verified_phrase`. `total_mentions` в прежнем виде **не отдаётся** (R3).

### 4.3. FIX измерительных путей (R2, §24.1 п.2–9; под K1)

- `_query_chat_memory` (legacy-ветка без `stats`): строка `:667` больше не приписывает точный смысл широкому счёту — при prefix/OR-матче ярлык «широкий поиск (префиксы): N сообщений», unit=messages, method указан; точная фраза/occurrences — только через `stats`-режим.
- `_dig_into_lore` (`:673`): счётчик применяет **те же** фильтры, что сниппеты (person_uid, year-bounds, quote/forward); graph-expansion имён — только кандидаты для примеров, **не** условие измерения; при ошибке счётчика — отдельный статус (`stats_count_error`), не ноль и не молчание (`:831–855`); результат вместо голого `total_mentions` `:862` несёт типизированный блок (status/unit/method/scope/coverage).
- `_dig_json_payload` (`:336`): при урезании сначала убираются `examples`/`snippets`/`facts`, затем — необязательные поля; schema/status/unit/scope/method сохраняются; если не помещается обязательное — `{"status":"insufficient_output_budget","value":null,...}`, а не `{truncated,total_mentions}` (`:377–380`).
- `LoreCompilerService`/`build_lore_story_user` (`:70`/`:285`): агрегаты маршрутизируются через `chat_statistics` (тот же MetricResult); «упоминаний: N» не выдаётся за точное число фразы без метода; слияние авторов по имени (`_mentions_by_authors:253`) сохраняется только как подпись, ключ — канонический ID; UPD-ветка `unchanged` со старой сохранённой историей не публикует непроверенные агрегаты (§7.3).

### 4.4. Retrieval (L-MCA07-5, CA-15-1)

- Примеры/кандидаты для `historical_evidence` и graph-expansion идут через `retrieve()` (`mca_retrieval_context.py:452`); второй комбинированный retrieval не создаётся.
- Измерение — **не retrieval**: это явный запрос к `smart_messages` по нормализованной спеке; `retrieve()` не участвует в count-пути и не меняет условие измерения.

## 5. D4 — MetricResult и NumericClaim (MCA15-R3)

### 5.1. `MetricResult` (frozen dataclass)

`metric_id` (`cs:<sha1-12 query_spec_hash>`), `status` ∈ `ok|partial|unsupported|error`, `value: int|None`, `unit` ∈ `messages|occurrences|authors`, `query_spec_hash`, `human_label` (детерминированный, с методом/единицей/областью), `scope` (chat_id, corpus, interval, tz), `coverage` ∈ `known_complete|partial|unknown`, `time_bounds` (first/last seen), `data_as_of` + `watermark`, `author_ids`, `filters`, `excluded_count`, `unknown_count`, `example_source_refs` (канонические item-ID, R17-safe), `duration_ms`, `error`/`reason`.

Правила: `value=0,status=ok` — только после успешного расчёта заданной области; timeout/ошибка → `value=null,status=error`; неполный корпус/dedup/скан-кап → `status=partial` (+ `stats_partial_corpus`), ноль в partial-корпусе не превращается в «никогда»; unsupported → `value=null` + причина.

### 5.2. `NumericClaim` и per-turn реестр

`NumericClaim {metric_id, unit, value, scope_key, human_label}`. Реестр — `ToolContext.metric_results` (in-memory, один ход). Долговременного хранения числа нет; повторный запрос — пересчёт (§9.1). `verified_phrase` — детерминированная формулировка сервиса (число + единица + область + полнота), готовый слот для финального сборщика.

## 6. D6 — Intent: banter / historical_evidence / chat_statistics (MCA15-R1)

Детерминированный классификатор `classify_stats_intent(text, *, reply_parent, addressed)` в `services/chat_statistics.py` (без LLM; контекст и reply, **не** слова «никогда»/«бот» сами по себе):

| Интент | Правило (закрытое) | Поведение |
|---|---|---|
| `chat_statistics` | явная просьба измерить: «сколько … раз/сообщений/упоминаний», «посчитай», «статистика» + объект счёта | stats-режим доступен; в payload — короткий канон-хинт «используй stats с явной метрикой» (прецедент `format_nostalgia_hint`); reason `chat_stats_intent` |
| `historical_evidence` | «найди/покажи/вспомни, когда/где … называл/говорил» без маркеров счёта | одно подтверждённое событие; поиск через существующий контур/`retrieve()`; подсчёт архива не обязателен; reason `historical_evidence_intent` |
| `social_banter` | утверждение/подкол без просьбы проверить (нет императива счёта/поиска) | короткий ответ/реакция/молчание; обязательного отчёта нет; хинт не добавляется; reason `social_banter_intent` |
| `mixed` | есть и просьба измерить, и шутка/эмоция | две цели: stats-хинт + обычная реплика; обе допустимы |

Инвариант: **нет пути, где подкол получает обязательный статистический отчёт** — для `social_banter` без `mixed` не строится MetricResult-хинт, а NumericClaim-гард (§7) не даёт опубликовать незаземлённые числа; инструменты при этом **не блокируются** глобально (юмор не запрещает память). Классификация не трогает `CoordinatorDecision.action`/action-schema mca-09; новые значения intent — аддитивны. `reason_code` объясняет цель поиска (три кода выше). Жёсткой реплики на конкретный пример (Вася/«шиз») в коде нет — только закрытые маркеры.

## 7. D5 — Контроль чисел на всех путях (MCA15-R3)

### 7.1. Один детерминированный гард в существующем контуре

`services/negative_constraints.py` (тот же постпроцессор-контур; **не** второй LLM-судья и не второй paraphrase-модуль): `check_numeric_claims(candidate, contract, *, source_text=None) -> str|None` + `NumericContract {claims, verified_phrase, stats_expected}`. REUSE нормализации чисел mca-08 (`_NUMBER_TOKEN_RE`/`_canon_number`/`_number_signature` `:44–92`).

Алгоритм (детерминированный): числа извлекаются и канонизируются; числа внутри кавычек/цитат и вне «статистического контекста» (закрытый список маркеров единиц: сообщени/раз/упомина/вхожден/автор/участник) не блокируются — даты, возраст, цитаты, обычная речь свободны. Число в статистическом контексте обязано соответствовать `NumericClaim` **этого хода** с совместимой единицей; совпадение с числом из tool output/другого запроса **не** является подтверждением (A41). Нарушение → `numeric_claim_mismatch`.

### 7.2. Точки применения (все пути отправки)

1. `verbalize_validated` (`:434`) — новый **опциональный** параметр `numeric_contract: NumericContract | None = None` (default None → байт-паритет): direct System2 (`direct_chat_service.py:2728`), factcheck (`:195`), summary (`:3309` — без контракта, no-op). Нарушение → **≤1** ограниченная коррекция (`NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT` с `verified_phrase`, внутри существующего бюджета ≤2 ретраев, бюджет не растёт); не исправлено → `fallback_text` (проверенный черновик) либо `verified_phrase` (детерминированная фраза с оговоркой) либо удаление неподтверждённой статистической части; stats-ключи `numeric_claim_*`, события notable-only.
2. Финальная сборка direct (`direct_chat_service.py`, после подстановки готовой lore-story `:2425–2427` и любых финальных веток) — тот же `check_numeric_claims` по `ToolContext.metric_results`: покрывает lore-story в обход verbalizer, fallback и прямые тексты. Коррекция здесь детерминированная (замена нарушающей статистической фразы на `verified_phrase` либо удаление), без второго LLM-вызова.
3. Постпроцессор — это и есть п.1/п.2 (расширение существующего контура); отдельный модуль запрещён (mca-22 §18, тест `tests/test_mca22_core_round1027.py:810–813`).

### 7.3. Truncation и старые истории

- `total_mentions` без описания не отдаётся; при урезании первыми уходят examples; обязательное не помещается → `insufficient_output_budget`, `value=null` (§4.3).
- Ошибка счётчика видна отдельно от успешных сниппетов (`stats_count_error`; A40).
- Сохранённые lore-истории с агрегатами старой версии: **не удаляются**; при доставке UPD-ветки `unchanged` непроверенные статистические числа не публикуются (замена/снятие + `lore_stats_recheck_flagged`); перепроверка — повторной компиляцией по запросу.

## 8. Reuse inventory (reused vs extended/FIX)

| Существующий путь | Решение | Где |
|---|---|---|
| `build_fts_query` prefix-OR | **EXTEND** аддитивный `mode` (default = старая формула) | `summary_memory.py:877` |
| `search_messages_fts_count` / `_count_by_author` | **REUSE** + расширение фильтров (author_id, interval, quote/forward, source_kind); канонический ключ — user_id | `database.py:5813/:5834` |
| `search_messages_fts` | **REUSE** (examples из той же спеки) | `database.py:5797` |
| `count_duplicate_identity_rows` | **REUSE** (dedup-проверка области) | `database.py:2066` |
| `count_mentions` | **НЕ используется** stats-путём (prefix-OR); legacy-путь под K1 OFF | `summary_memory.py:2369` |
| `_query_chat_memory` | **FIX** ярлык/статус + stats-режим | `tool_router.py:606/:667` |
| `_dig_into_lore` счётчик/graph-expansion | **FIX**: общие фильтры count/examples; expansion — кандидаты; ошибка ≠ 0 | `tool_router.py:673/:697–712/:831–862` |
| `_dig_json_payload` | **FIX** контракт урезания (`insufficient_output_budget`) | `tool_router.py:336/:377–380` |
| `LoreCompilerService` / `build_lore_story_user` | **REUSE** + маршрутизация агрегатов через `chat_statistics`; ID-ключ, имя — подпись | `lore_compiler_service.py:70/:108/:253`, `lore_prompts.py:285` |
| `retrieve()` mca-07 | **REUSE** (historical_evidence/кандидаты; не count-путь) | `mca_retrieval_context.py:452` |
| `verbalize_validated` | **EXTEND** `numeric_contract` (как mca-08 `form_contract`) | `negative_constraints.py:434` |
| `sanitize_outgoing` | **REUSE** неизменным (egress-канон) | `outgoing_guard` |
| `mca_gates`/`mca_events`/`mca_process_registry` | **REUSE** аддитивно (K1–K3, +11 кодов, процесс/стадии) | §9–§10 |
| `ToolContext` | **EXTEND** `metric_results`/`stats_intent` (аддитивно) | `tool_router.py:460–516` |
| identity/alias-каскад (mca-03) | **REUSE** (канонические ID; имя — подпись) | `_resolve_name:2538` |

## 9. Санкции T-4918 (поимённо; Builder не выбирает)

### 9.1. Δ DDL: **0** (v27 НЕ санкционируется)

MetricResult/NumericClaim живут в памяти хода; повторный запрос — пересчёт; watermark — `MAX(id)`/`MAX(timestamp)` в самом измерении; lore-схема не меняется. Ни одной новой таблицы/колонки/индекса; реестр mca-14 не расширяется (latest v26 остаётся); PG — no-op. Backup-guard не срабатывает (нет нового шага). Если Builder упрётся в необходимость durable-кеша/снапшот-таблицы — **стоп и эскалация** @Architect (новая санкция).

### 9.2. Δ каталога: **0**

Все новые настройки — env-only `ClassVar` в `config/settings.py`; `param_catalog.py`/TSV вне diff; F8 — **NOT_APPLICABLE** (переиздание не требуется); каталог остаётся **489**. Схема `query_chat_memory` — не каталог (tool-schemas вне `param_catalog`); canon 12 сохраняется.

### 9.3. Kill-switches: ровно **3**, env-only, default ON; OFF = байт-в-бит 2.58.55

| # | Имя | OFF = |
|---|---|---|
| K1 | `MCA_CHAT_STATISTICS_ENABLED` | нет stats-режима/measurement/MetricResult; `query_chat_memory`/`_dig_into_lore`/`_dig_json_payload`/lore-агрегаты как 2.58.55 (включая «Найдено N упоминаний» и голый `total_mentions`) |
| K2 | `MCA_NUMERIC_CLAIM_GUARD_ENABLED` | `verbalize_validated` без numeric-контракта; финальная сборка direct без гарда; новые параметры игнорируются |
| K3 | `MCA_STATS_INTENT_ENABLED` | классификатор/хинт/reason-коды интента не работают; intent-поведение как 2.58.55 |

Регистрация: `mca_gates.KILL_SWITCHES` + функции-резолверы + `_GATE_RESOLVERS` (mca_process_registry) + Settings `ClassVar`. Env-only лимиты (не kill-switches): `MCA_CHAT_STATS_OCCURRENCE_MAX_ROWS` (20000), `MCA_CHAT_STATS_EXAMPLES_MAX` (20). Все три OFF = полный паритет 2.58.55.

### 9.4. reason_code: аддитивно, **ровно +11**, единый словарь `mca_events.REASON_CODES` (второй запрещён)

`chat_stats_intent`, `historical_evidence_intent`, `social_banter_intent`, `stats_count_error`, `stats_partial_corpus`, `stats_unsupported`, `insufficient_output_budget`, `numeric_claim_mismatch`, `numeric_claim_corrected`, `numeric_claim_fallback`, `lore_stats_recheck_flagged`. Имена событий: `chat_statistics`, `stats_intent`, `numeric_claim_guard` (свободная ось event_name mca-13). Повторно используемые существующие коды: `ambiguous_identity`, `provider_unavailable`, `timeout` — не дублируются.

### 9.5. Tool-поверхность

Расширение `query_chat_memory` (опциональный `stats`); `TOOL_CALLING_TOOLS == 12` — **не менять**; новый инструмент не регистрируется; dispatch-таблица не расширяется. Прецедент «12→+1» (mca-19) не применяется.

### 9.6. Risk: **R3 подтверждён**

Поверхность — все пути отправки (числа в Telegram), семантика счёта (пользовательская правда), intent-маршрутизация, архив 2 млн строк. Обязателен `threat-failure-analysis.md` — приложен (THR-1…THR-12, FM-регистр). Эскалация @Architect при: (а) необходимости durable-кеша (Δ DDL); (б) свободном text-to-SQL/втором retrieval; (в) изменении action-schema; (г) ослаблении egress/постпроцессора.

### 9.7. Deploy / rollback / merge

- **Пер-фичевый релиз CA-11 (прецедент mca-06/mca-08):** bump **2.58.55 → 2.58.56**; атомарная пара feat+docs + deploy-doc; DDL нет → миграционного шага/backup-guard нет; health 200; focused-повтор; prod ff без force; kill-switches 0 env-оверрайдов.
- **Rollback:** soft — K1–K3 `false` + рестарт (OFF=2.58.55); cold — `git revert` фича-коммита (Δ DDL=0 → схема не откатывается); restore БД не требуется.
- **Merge:** `plans/ARCHITECTURE.md` **§116** + ADR-1028-12 → Accepted.
- **Запрещено:** менять canon 12; создавать второй retrieval/постпроцессор/словарь событий/LLM-судью; durable-кеш; трогать `plans/current_task.md`; делать UI.

## 10. Наблюдаемость (mca-17a, GEN-R17)

- `mca_process_registry.py`: заменить placeholder `episodes.timeline` (`:821–827`, owner `mca-15`, неверное имя/назначение) на `ProcessDefinition(process_id="chat.statistics", version="1")`: stages `intent → measurement → claim_check → delivery`; `state_source=("mca_events",)`, `enabled_gate="MCA_CHAT_STATISTICS_ENABLED"`, widget `"Измерения, проверки и отказы"` (контракт §27.1 `:1358` для mca-17c, рендер не делать). AMEND `direct.reply`: stages += `claim_check` (события notable-only).
- Диагностика §24.5 (R17-safe): intent + reason_code; аргументы (коды/ID, с учётом доступа); `query_spec_hash` + нормализация/метод/единица; corpus/snapshot (`watermark`, `data_as_of`, `coverage`); count status; NumericClaim mapping (`metric_id`); исход проверки; финальная доставка (длина/статус). Сырой/нормализованный текст — не в durable-канал.
- K*-OFF → честный `not_run`/`disabled` в реестре; per-reply «успехов» не эмитим (урок M-ASAP31-2).

## 11. Поведенческий план приёмки

1. **RED/аудит §24.1 (T-4919):** адаптировать probe §26 к текущему HEAD (AST-функции `build_fts_query`/`search_messages_fts_count_by_author`/`_dig_json_payload`; 7 синтетических сообщений; truth set: фраза 1 / prefix-OR 5 / +«петя» 6 / prefix «шиз» 4; truncation больше не оставляет голый `total_mentions`). Каждый пункт §24.1 — «воспроизведён (RED) / уже исправлен (тест) / вне досягаемости».
2. **Focused-контракты (T-4922/T-4928/T-4933/T-4936):** A38 (фраза/OR/prefix/occurrences — разные единицы и значения); A39 (author/time/quote-фильтры и LIMIT — общие для числа и примеров, unknown учтён); A40 (ошибка count / обрезанный payload / частичный корпус — нет ложного нуля и «никогда»); A41 (число другого запроса через verbalizer/lore fallback не публикуется); A42 (подкол vs явная просьба); регрессии §24.5 целиком (OR/фраза; 3 вхождения в одном сообщении; два одинаковых имени; смена алиаса; фильтр автора до LIMIT; год/TZ; quote/forward/unknown; bot messages; duplicate import; ошибка счётчика; payload truncation; число из другого metric; ноль в частичном корпусе; stale cache после импорта → пересчёт; lore-story обход; подкол vs просьба).
3. **OFF-паритет:** байт-сравнение текстов/payload/БД-записей по каждому K1–K3 и комбинированно.
4. **Интеграционные:** direct + System2 с реально включёнными функциями (прецедент `:878`); factcheck-путь с lore-агрегатами; смежные наборы tool_router/database/summary_memory/lore_compiler/lore_prompts/direct_chat/negative_constraints + mca-07 retrieval + mca-22 core (в т.ч. тест `:810`).
5. **Live (T-4940):** реальный чат — подкол без просьбы → нет обязательного отчёта; явная просьба посчитать → проверяемое число с единицей/областью; диагностика по trace; три числа кейса Васи — только при наличии исходных данных (`:1171`), иначе `PENDING OWNER` без имитации.

## 12. Failure-mode register

Полный R3-анализ — `threat-failure-analysis.md` (THR-1…THR-12). Кратко: FM-1 ложное измерение (метод/единица/фильтры) → типизация+метод+truth set; FM-2 утечка числа в обход гарда → финальная сборка direct + все точки verbalizer; FM-3 банter → отчёт → инвариант §6 + отсутствие MetricResult; FM-4 stale/дубли → watermark/recompute/dedup-check; FM-5 деградация БД/таймаут → honest status/value=null; FM-6 R17 → hash/ID/числа; FM-7 регрессия OFF → K1–K3 + байт-паритет-тесты.

## 13. Матрица spec → tasks

| Spec § | Задачи |
|---|---|
| §3 (D1/D2) | T-4923, T-4924, T-4925, T-4926 |
| §4 (D3, FIX, retrieve) | T-4926, T-4927 |
| §5 (D4) | T-4929 |
| §6 (D6, intent) | T-4920, T-4921 |
| §7 (D5, контроль) | T-4930, T-4931, T-4932 |
| §9 (санкции) | T-4918, T-4939 |
| §10 (наблюдаемость) | T-4934, T-4935 |
| §11 (приёмка) | T-4919, T-4922, T-4928, T-4933, T-4936, T-4937, T-4938, T-4940 |
| §9.7 (merge/reconcile) | T-4941 |

**Статус:** `DESIGN_FROZEN` / `SANCTIONS_ISSUED` — все решения приняты, Builder T-4919+ может стартовать без архитектурных вопросов. Блокеров нет; live-часть — `PENDING OWNER`. `plans/current_task.md` не изменялся.
