# MCA-15 `mca-15-chat-statistics` — evidence (Builder, блоки A–D: T-4919…T-4936)

- **Фича:** `mca-15-chat-statistics`; **шаг:** Builder, блоки A–D (Step 3; A+B — часть 1, C+D — часть 2) + интегрированный focused-пакет (T-4937).
- **База:** HEAD `f1cacbd` (2.58.55) + **незакоммиченный** рабочий diff (no stage/commit — по инструкции).
- **Санкции:** ADR-1028-12 D1–D10 / spec §9 (Δ DDL=0, Δ каталога=0, K1–K3 env-only, reason_code аддитивно, canon 12, tool-поверхность — stats-режим `query_chat_memory`).
- **R17:** в коде/тестах/логах — коды/числа/ID/хэши; сырой и нормализованный текст запроса в durable-канал не пишется.
- **Не трогалось:** `plans/current_task.md`; чужие грязные файлы `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md` (были изменены до старта — не мои).

## 1. T-4919 — repro/аудит §24.1 на текущем HEAD

Адаптированный probe §26: реальные функции текущего дерева (`build_fts_query`,
`search_messages_fts_count_by_author`, `_dig_json_payload`) на реальной SQLite
FTS5 (in-memory), 7 синтетических сообщений. AST-извлечение не нужно — probe
исполняет текущие функции напрямую (изменение зависимостей после волн
mca-03/04a/07/22/08 учтено). Тест-класс `TestReproProbe`
(`tests/test_mca15_chat_statistics_round1028.py`).

Truth set (подтверждён на текущем HEAD): фраза `"вася шиз"` = **1**;
prefix-OR `"вася"* OR "шиз"*` = **5**; +«петя» в OR = **6**; prefix «шиз» = **4**
(включает «шизофрения» — префикс, не корень).

| # §24.1 | Статус | Доказательство / где закрыт |
|---|---|---|
| 1. prefix-OR вместо фразы | **RED воспроизведён** (5 vs 1) | `TestReproProbe.test_truth_set…`; FIX: режимы `build_fts_query` + stats `exact_phrase/token` (T-4926) |
| 2. graph/person-имена в счётчике | **RED воспроизведён** (5→6 при +имени) | `test_expanded_query_documents_measurement_drift`; FIX: измерение = токены запроса+person, expansion → `retrieve()` (`test_dig_expansion_does_not_change_measurement`) |
| 3. COUNT сообщений ≠ occurrences | **RED воспроизведён** (3 вхождения в 1 сообщении = 1 строка) | probe; FIX: metric `occurrences` (`token_scan_unicode61_v1`), `messages` назван сообщениями |
| 4. фильтры сниппетов ≠ фильтры счётчика; LIMIT до фильтра | **RED по коду** (person_uid только в сниппетах; окно после top-N) | FIX: `author_ids`/interval/quote-forward/source — в SQL до LIMIT, один фильтр-источник `_message_measure_filters` (`test_a39_*`) |
| 5. группировка по display name | **RED по коду** (`mentions_by_authors[name] += …`) | FIX: ключ — user_id, имя — подпись; `authors`/`mentions_by_authors`-merge по ID (`test_two_same_names…`, dig/lore-тесты) |
| 6. «Найдено N упоминаний» приписывает точный смысл | **RED по коду** (`tool_router:667`) | FIX K1 ON: «Широкий поиск (префиксы, не морфология): N сообщений…» (`test_header_*`) |
| 7. ошибка счётчика = 0, статуса нет | **RED по коду** (fail-open оставлял `total_mentions=0`) | FIX: `stats_count_error`, `value=null`, отдельный статус (`test_dig_counter_error_*`) |
| 8. truncation оставляет голый `total_mentions` | **RED воспроизведён** (`{"truncated":true,"total_mentions":5}`) | FIX K1 ON: `insufficient_output_budget`/сохранение status/stats (`test_truncation_red_off_and_fixed_on`, `test_dig_json_payload_on_no_bare_number`) |
| 9. lore-агрегаты как «упоминания» | **RED по коду** (`build_lore_story_user:307`) | FIX: `chat_statistics.measure` + ярлык метода/единицы, ID-ключ (`test_lore_aggregates_typed_and_id_keyed`, `test_lore_prompt_labeled_not_bare`) |
| 10. полнота bot-history/PG | **вне досягаемости в A+B** (нет PG-корпуса сообщений; нет надёжного поля «бот») | Честные статусы: сумма хранилищ → `unsupported`; `sender human/bot` → `unsupported`, `unknown` отдельным счётчиком; live-проверка — T-4940 `PENDING OWNER` |
| 11. factcheck-маршрут форсирует поиск | **вне досягаемости по одному ответу**; исправлена классификация намерения (D6) | T-4920: `historical_evidence` vs `social_banter`; глобального запрета памяти нет |

**Три числа кейса Васи (12 786 / 198 720 / 11 814):** исходные данные
(tool arguments/output/БД) отсутствуют — **не воспроизводились и не
выдумывались** (`PENDING OWNER`, §24.1/§26, no-false-acceptance).

## 2. Что реализовано (блоки A+B)

**Новый сервис `services/chat_statistics.py`:**
- `StatsQuery` (frozen) по D1: `metric` (`messages/occurrences/distinct_authors`),
  `match_mode` (`exact_phrase/token/prefix/all_terms/any_terms`), `text/terms`,
  `author_ids`/`subject_ids` (раздельная семантика: subject без подтверждённой
  атрибуции → `unsupported`), `chat_id`, interval, `timezone`,
  `source_kinds` (`live` = `import_key IS NULL`, `import` = IS NOT NULL),
  `sender_kinds` (human/bot → unsupported), `quote_forward`
  (include/exclude/only; нет колонок метаданных → unsupported),
  `normalization_version="cs-norm-1"`, `corpus_scope=smart_messages`,
  `query_spec_hash` (sha256 канонизированной спеки).
- `measure()`: count + examples из **одной** спеки; фильтры в SQL **до LIMIT**;
  watermark `{max_id,max_timestamp}`, examples с `id <= max_id`; dedup-проверка
  области (`count_duplicate_identity_rows(chat_id=…)`) → `partial` +
  `stats_partial_corpus` + `excluded_count`; occurrences — bounded keyset-скан
  (`MCA_CHAT_STATS_OCCURRENCE_MAX_ROWS`, кап → `partial`, `value=null`);
  `distinct_authors` — `COUNT(DISTINCT user_id)`, `user_id IS NULL` →
  `unknown_count`; ошибка → `error`/`value=null` (`stats_count_error`);
  `prefix` явно помечен «не морфологический анализ».
- `classify_stats_intent(text, *, reply_parent, addressed)` (D6, без LLM):
  `chat_statistics`/`historical_evidence`/`social_banter`/`mixed`; закрытые
  маркеры, контекст/reply; `stats_hint` только для измеримых интентов и
  адресованных сообщений; `notable` — для notable-only событий.
- `collect_candidates()` — единственная точка retrieval mca-15: обёртка
  `mca_retrieval_context.retrieve()` (L-MCA07-5); в count-пути не участвует.

**FIX измерительных путей (K1 ON; OFF — байт-паритет):**
- `summary_memory.build_fts_query(keywords, mode="prefix_or")` — аддитивные
  режимы; default = старая prefix-OR-формула.
- `database.search_messages_fts`/`_count`/`_count_by_author` — аддитивные
  фильтры (`since/until/author_ids/source_kind/quote_forward/max_id/after_id`),
  `max_id`/`unknown_count` в результате; `count_duplicate_identity_rows(chat_id=None)`.
- `tool_router._query_chat_memory` — ярлык единицы/метода; `_dig_into_lore` —
  измерение без graph-expansion, счётчик с теми же фильтрами (person/окно),
  ошибка ≠ 0, типизированный `stats`-блок, авторы по каноническому ID,
  expansion-кандидаты через `retrieve()`; `_dig_json_payload` — truncation без
  голого числа; `ToolContext.stats_intent` (аддитивно).
- `lore_compiler_service` — агрегаты через `chat_statistics.measure`
  (ID-ключ, имя — подпись); `lore_prompts.build_lore_story_user` — аддитивные
  `authors/stats_label/stats_method` (пустые → прежний текст).
- `direct_chat_service._stats_intent_block` — классификация + stats-хинт в
  payload до LLM; `ctx.stats_intent`; событие `stats_intent` notable-only;
  K3 OFF → без классификации/хинта/события. Инструменты не блокируются.
- Санкции: Settings ClassVar K1–K3 + 2 env-лимита; `mca_gates` KILL_SWITCHES +
  резолверы; `_GATE_RESOLVERS` +3; `REASON_CODES` +7 (мои блоки; +4
  `numeric_claim_*` — блок C). Δ DDL=0, каталог не менялся.

**Тестовая инфраструктура:** `tests/test_mca15_chat_statistics_round1028.py`
(48 тестов) + обновлены существующие контракт-тесты под осознанно изменённое
K1-ON поведение (ярлык, типизированный dig-payload, аддитивные ключи счётчика,
3 теста graph-expansion → OFF-паритет).

Регрессии §24.5 в B-части (привязаны к тестам): OR vs фраза
(`test_a38_*`), 3 вхождения в одном сообщении (`occurrences=11`, id3),
два одинаковых имени (`test_two_same_names…`), смена алиаса
(там же, user_id=10 не дробится), фильтр автора до LIMIT
(`test_a39_author_filter_before_limit`), год/TZ
(`test_time_bounds_timezone_dates`), quote/forward/unknown
(`test_a39_time_and_quote_filters_identical`), bot messages → unsupported
(`test_unsupported_paths_not_guessed`), duplicate import
(`test_duplicate_import_partial…`).

## 3. Файлы

| Файл | Δ |
|---|---|
| `services/chat_statistics.py` | **новый** (сервис D1/D4/D6 + intent + retrieve-wrapper) |
| `services/summary_memory.py` | `build_fts_query` + режимы (аддитивно) |
| `services/database.py` | фильтры/watermark/unknown в 3 FTS-методах; dedup scope |
| `services/tool_router.py` | ярлык, dig-измерение/статусы/тип-блок, truncation, `ctx.stats_intent` |
| `services/lore_compiler_service.py` | агрегаты через measure; ID-ключ авторов |
| `services/lore_prompts.py` | `authors/stats_label/stats_method` (аддитивно) |
| `services/direct_chat_service.py` | intent-классификация + stats-хинт + `ctx.stats_intent` |
| `config/settings.py` | K1–K3 ClassVar + 2 env-лимита (env-only, каталог Δ=0) |
| `services/mca_gates.py` | KILL_SWITCHES + 5 резолверов |
| `services/mca_events.py` | +7 reason_code (единый словарь) |
| `services/mca_process_registry.py` | `_GATE_RESOLVERS` +3 (процесс — блок D) |
| `tests/test_mca15_chat_statistics_round1028.py` | **новый** focused A+B |
| `tests/test_tool_router.py`, `test_memory_core_round1020.py`, `test_summary_memory.py`, `test_scanner_fixes_round1020.py` | обновление контракт-ожиданий K1 ON + OFF-паритет |

## 4. Focused-проверки (точные команды/числа)

| ID | Команда | Результат |
|---|---|---|
| E-MCA15-1 | `.venv\Scripts\python.exe -m pytest tests/test_mca15_chat_statistics_round1028.py -q` | **48 passed** (3.1s) |
| E-MCA15-2 | focused+adjacent batch: mca15 + tool_router + scanner_fixes_round1020 + summary_memory + memory_core_round1020 + lore_compiler_round1020 + lore_prompts + direct_chat + direct_chat_lore_inject + direct_two_call_round1022 + mca01 + mca02 + mca03 + mca05 + mca07 + mca08×2 + mca13 + mca14 + mca17a + mca22×2 + belief_decay + chat_lore + chat_lore_store (`-q`) | **1150 passed, 0 failed** (46s) |
| E-MCA15-3 | ранние прогоны тех же смежных наборов (до финальных правок): 267/309/518/699/112 — все зелёные | pass |

Полный suite не гонялся (release policy; Δ не cross-cutting за пределы перечисленных смежных зон).

## 5. OFF-паритет

- **K1 OFF** (`MCA_CHAT_STATISTICS_ENABLED=false`): `query_chat_memory` —
  прежняя строка «Найдено N упоминаний»; `_dig_into_lore` — прежний payload
  (`total_mentions`, `mentions_by_authors`, graph-names в merged и в счётчике);
  `_dig_json_payload` — прежний fallback `{truncated,total_mentions}`;
  lore — прежние параметры промпта; `build_fts_query` default — байт-в-байт.
  Тесты: `test_query_chat_memory_off_parity`, `test_dig_off_parity_payload`,
  `test_dig_json_payload_off_parity`, `test_truncation_red_off_and_fixed_on`,
  `test_graph_names_bfs_expands_query_tokens` (OFF), `test_person_expands…` (OFF),
  `test_graph_empty_falls_back…` (OFF), `test_build_fts_query_modes`.
- **K3 OFF**: `_stats_intent_block` → `("", None)` — классификация/хинт/событие
  не выполняются (`test_k3_off_parity`).
- **K2**: зарегистрирован (ClassVar/резолвер/KILL_SWITCHES/`_GATE_RESOLVERS`);
  поверхность гарда — блоки C/D (см. §9–§10), паритет проверен.
- Скан-кап occurrences и env-лимиты — не kill-switch (env-only, вне каталога).

## 6. Блоки C+D — что реализовано (T-4929…T-4936)

**T-4929 (D4) `services/chat_statistics.py`:** `MetricResult` (frozen) с полями
§5.1 + аддитивные `metric/method/method_label/author_counts/verified_phrase`;
`NumericClaim{metric_id,unit,value,scope_key,human_label}`;
`metric_id = cs:<sha1-12 query_spec_hash>`; `human_label`/`verified_phrase` —
детерминированные (число+единица+метод+область+полнота), без сырого текста;
`build_metric_result`/`claim_for_result`/`claims_for_result` (ok/partial с
числом; разбивка по авторам — отдельные claims); `metric_result_payload` (§4.2);
`build_measurement_diagnostic` + `emit_measurement_event` (§24.5, R17-safe).
Повторный запрос — пересчёт (durable-кеша нет).

**T-4930/T-4931 (D5) `services/negative_constraints.py`:** `NumericContract`
{claims, verified_phrase, stats_expected}; `check_numeric_claims` (закрытый
список маркеров единиц; цитаты/даты/годы/возраст свободны; `source_text` —
намеренно НЕ подтверждение, A41); `apply_numeric_guard` (≤1 детерминированная
коррекция: замена на `verified_phrase` либо снятие фразы; caveat при
`stats_expected` без проверки); `verbalize_validated` += опциональный
`numeric_contract` (≤1 numeric-повтор `NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT` в
общем бюджете ≤2; fallback `verified_phrase`/черновик/снятие). Точки:
direct System2 (`_synthesize_direct_answer` + событие `numeric_claim_guard`),
финальная сборка `handle` (после lore-story, до отправки; повторный гард после
duplicate-regeneration), factcheck System2 (claims из `raw.metric_results`),
постпроцессор = тот же `verbalize_validated`. Второго LLM-судьи/парафразера нет.

**Tool-поверхность (D3):** `TOOL_QUERY_CHAT_MEMORY` += опциональный `stats`
(metric/match_mode/phrase/terms/author/quote_forward/sender; canon 12 не
меняется); `_query_chat_memory` при `stats` и K1 ON → `measure()` → типизированный
JSON + `ToolContext.metric_results`; `author` резолвится алиас-контуром
(0/≥2 совпадений → `unsupported`/`ambiguous_identity`, без угадывания);
K1 OFF/без `stats` → прежний путь. `_dig_into_lore` регистрирует MetricResult
своим измерением; `_stats_json_payload` — урезание с сохранением
schema/status/unit/scope/method → `insufficient_output_budget`/value=null.

**T-4932:** lore UPD-ветка `unchanged` → `stats_recheck=True` +
`lore_stats_recheck_flagged` (lore не удаляется/не перезаписывается);
свежая компиляция отдаёт `metric_result` → claim хода; старые числа снимает
финальный numeric-гард.

**T-4934:** диагностика §24.5 в `source_ref_json` события `chat_statistics`:
intent/hash/метод/единица/scope/watermark/data_as_of/coverage/статус/claims/
`example_source_refs`; SQL и сырой/нормализованный текст не попадают (тест).

**T-4935:** placeholder `episodes.timeline` заменён процессом
`chat.statistics` v1 (stages `intent→measurement→claim_check→delivery`,
gate K1, widget «Измерения, проверки и отказы», события
`stats_intent`/`chat_statistics`/`numeric_claim_guard`); AMEND `direct.reply`
(stage `claim_check`); reason-коды +4 → итого **+11** (единый словарь).

## 7. Блоки C+D — файлы

| Файл | Δ |
|---|---|
| `services/chat_statistics.py` | +MetricResult/NumericClaim/claims/human_label/verified_phrase/payload/диагностика/событие |
| `services/negative_constraints.py` | +NumericContract/check/correct/apply/`numeric_contract` в `verbalize_validated` |
| `services/prompt_style_blocks.py` | +`NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT` |
| `services/tool_router.py` | +stats-режим `_query_chat_memory`, `_stats_json_payload`, `metric_results`/`lore_stats_recheck`, dig-регистрация, lore-флаги |
| `services/tool_schemas.py` | +опциональный объект `stats` (canon 12 сохранён) |
| `services/direct_chat_service.py` | +`_numeric_contract_from_ctx`, контракт в System2, финальный гард `handle`, события |
| `services/factcheck_service.py` | +claims из tool-ctx в System2-контракт |
| `services/lore_compiler_service.py` | +`metric_result`/`stats_recheck` в результате compile |
| `services/mca_events.py` | +4 reason_code (итого +11 на фичу) |
| `services/mca_process_registry.py` | +`chat.statistics` v1; AMEND `direct.reply` |
| `tests/test_mca15_chat_statistics_round1028.py` | +43 теста блоков C+D (итого 91) |
| `tests/test_mca17a_observability_core_round1027.py` | обновление «будущих» процессов (placeholder → реальный `chat.statistics`) |

## 8. Focused-проверки (точные команды/числа)

| ID | Команда | Результат |
|---|---|---|
| E-MCA15-4 | `.venv\Scripts\python.exe -m pytest tests/test_mca15_chat_statistics_round1028.py -q` | **91 passed** (3.6s; 48 A+B + 43 C+D), exit 0 |
| E-MCA15-5 | интегрированный пакет T-4937: mca15 + tool_router + scanner_fixes_round1020 + summary_memory + memory_core_round1020 + lore_compiler_round1020 + lore_prompts + direct_chat + direct_two_call_round1022 + direct_chat_lore_inject + mca07_retrieval + mca08×2 + mca22 core/truthset + mca13 + mca14 + mca17a + negative_constraints + database + tool_schemas + factcheck×2 + summary_generator + verbilizer_response_modes + anticliche + param_catalog (`-q`) | **1337 passed, 0 failed** (34.9s), exit 0 |
| E-MCA15-6 | R17-скан: `git diff -U0 -- services config \| Select-String '^\+' \| Select-String 'logger\.\|emit_mca_event'` + grep `logger\.\|emit_mca_event` по `services/chat_statistics.py` | **0 строк с сырым/нормализованным текстом** (только коды/ID/класс ошибки/длины) |

Полный suite не гонялся (release policy; Δ не cross-cutting за пределы
перечисленных смежных зон). JS не гонялся — UI не тронут. F8/каталог — не
требуется (Δ каталога=0, `test_catalog_delta_zero`).

## 9. OFF-паритет (блоки C+D)

- **K2 OFF** (`MCA_NUMERIC_CLAIM_GUARD_ENABLED=false`): `verbalize_validated`
  игнорирует `numeric_contract` (один вызов, stats без numeric-ключей);
  `apply_numeric_guard` — текст как есть; `_numeric_contract_from_ctx` → None.
  Тесты: `TestNumericGuardVerbalize::test_k2_off_parity`,
  `::test_apply_guard_none_and_off_parity`,
  `TestNumericGuardSendPaths::test_k2_off_contract_none`.
- **K1 OFF**: stats-объект игнорируется → прежний путь «Найдено N упоминаний»,
  `ctx.metric_results == []`
  (`TestStatsToolMode::test_stats_mode_off_parity`); прежние K1-паритеты A+B
  сохранены.
- **Все три OFF**: `_numeric_contract_from_ctx`=None, `_stats_intent_block`=
  ("",None), `_dig_json_payload` = `{truncated,total_mentions}`
  (`TestNumericGuardSendPaths::test_all_three_off_full_parity`).
- **K2 OFF-поверхность `handle`**: контракт None → `apply_numeric_guard`
  возвращает текст без изменений (паритет 2.58.55).

## 10. reason_code / реестр

- Единый `mca_events.REASON_CODES`: санкционированные 11 присутствуют
  (`TestProcessRegistry::test_reason_codes_eleven_sanctioned`); блоки A+B
  добавили 7, блоки C+D — ровно 4 (`numeric_claim_mismatch`,
  `numeric_claim_corrected`, `numeric_claim_fallback`,
  `lore_stats_recheck_flagged`); второй словарь не создавался.
- Реестр mca-17a: процесс `chat.statistics` v1 + стадии; `direct.reply` AMEND
  (`claim_check`); OFF → `STATUS_DISABLED`, без событий → `not_run`
  (`TestProcessRegistry`).

## 11. Остаточные риски / наблюдения

- `quote/forward`: схема NOT NULL-defaults (`is_forward=0`, `forward_source=''`)
  не различает «явно не цитата» и «метаданные не записаны»; COALESCE трактует
  default как «не цитата». Нет колонок метаданных → `unsupported` (guard).
  Остаточный риск: честный, виден в `scope.quote_forward`; live-сверка — T-4940.
- occurrences — собственная unicode61-токенизация (не FTS rank), метод
  `token_scan_unicode61_v1` назван в результате; кап → `partial`.
- `search_messages_fts_count*` теперь возвращают +2 ключа (`max_id`,
  `unknown_count`) — аддитивно; тесты с exact-equality обновлены.
- **Numeric-гард и маркер «раз» (принятый риск THR-2/THR-3):** число рядом с
  «раз» в стат-контексте без claim (например, обычная реплика «я тебе 5 раз
  говорил») снимается/заменяется; это прямое следствие закрытого списка
  маркеров spec §7.1. Даты/годы/возраст/цитаты свободны (тесты).
- **Wrong attribution без числа** («не тот автор, но верное число») гардом не
  ловится — остаточный риск THR-3, компенсация: `verified_phrase` с областью.
- Внешние грязные файлы (`plans/workflow_state.md`,
  `plans/docs/mca-round1027-arch-frames.md`) — не мои, не трогал.
- Incidental: `services/tool_schemas.py` после правки получил CRLF — EOL
  возвращён к LF репозитория (diff = +58 строк, без шума).
