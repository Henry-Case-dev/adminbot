# W6 / EVOL-SRC-READER — проверенное чтение исходного кода

Ветка: `feat/evol-src-reader`, база `5fc2ded5` (содержимое задеплоенного 2.58.149).
Контракт: `plans/features/evol/arch/source-reader-contract.md` (ARCHITECT_REQUIRED, заморожен).
Источник требования: `plans/current_task.md` §1 (строки 1176–1236).
Роль отчёта: Builder-сдача одной полосы. Reviewer проверяет независимо.
Ревизия 2: закрыты B1/B2/B3 и миноры независимого ревью
(`plans/features/evol/reports/w20-src-reader-review.md`), см. §10.

## 0. Итог одной фразой

Появился 16-й инструмент `read_source_code` (`discover|locate|read`): он находит
публичный репозиторий, локализует файл по дереву и **читает настоящие байты файла
на конкретном commit**, отдавая commit-pinned ссылку, точный `line_range` и
фрагмент кода, который является точной подстрокой прочитанных байт. Ни
`SafeFetcher`, ни `source_reuse`, ни evidence-окно, ни словарь причин не
дублируются: новых кодов телеметрии — 0, новых таблиц/миграций/каталог-ключей — 0.

## 1. Что реализовано (контракт → код → тест)

| Пункт контракта | Реализация | Тест |
|---|---|---|
| §1 один инструмент, три операции, `additionalProperties: false`, `required: [operation]` | `services/tool_schemas.py:854` (`TOOL_READ_SOURCE_CODE`), канон 15→16 в хвост (`:978`) | `TestToolCanon::test_schema_is_strict_and_operation_only_required`, `test_canon_is_16_and_new_tool_is_last` |
| §1 аргументы: url/repo/query/ref/path/symbol/line_start/line_end/follow/language; вывод `url` из `ctx.resolved_url`, `query` из `ctx.query` | `services/tool_router.py` (`_read_source_code`) | `TestToolResultMapping`, `TestEvidenceWindow::test_window_comes_from_tool_context_budget` |
| §1.1 Evidence Contract: `status/stage/verified/host/repo/ref/commit/path/source_kind/verified_url/line_range/snippet/.../not_checked/followup_incomplete/candidates/error/provenance/read_level/reused/network_calls/latency_ms` | `_read_payload`, `_not_source_payload`, `_error_payload`, базовая форма payload с постоянными ключами | `TestEvidenceHonesty::test_not_checked_block_is_present_in_every_status`, `TestVerifiedFetch`, `TestByteSemantics` |
| §1.2 V1.1–V1.2: HTTP 200 для точной `(repo, commit, path)` + непустые декодированные байты | `GitHubProvider.read_file` (+ сверка `path` из ответа `contents`), `decode_source_bytes` | `test_server_200_for_another_path_is_not_verified`, `TestByteSemantics` |
| §1.2 V1.3: `line_range` вычислен из байт, `snippet` — их точная подстрока | `build_snippet` режет **по смещениям строк** исходного текста (`line_spans`), CRLF сохраняется | `test_crlf_file_verifies_and_snippet_is_exact_substring`, `test_utf8_cyrillic_file_verifies_with_correct_lines`, `test_big_file_is_cut_by_dynamic_window_not_by_4000` |
| §1.2 V1.4–V1.5: `verified_url` commit-pinned, `source_kind == "file"` | `_verified_url`, `_kind_for_path` (README → `readme`) | `test_blob_link_returns_verified_commit_pinned_fragment`, `test_readme_is_read_but_never_verified` |
| §2 граница провайдера: `SourceProvider` + единственная реализация GitHub, чужие хосты — `unsupported/provider_unconfigured` по hostname | `services/source_reader.py` (`GitHubProvider`, `SourceProvider`, `SUPPORTED_HOSTS`, `parse_source_url`) | `TestUrlParsing::test_foreign_and_lookalike_hosts_are_unsupported`, `test_unsupported_host_is_provider_unconfigured` |
| §2 транспорт — только существующий `SafeFetcher`; лимиты/таймаут/SSRF/редиректы/маскирование | `GitHubProvider._fetch` (профиль `html`, `max_bytes=SOURCE_READ_MAX_FILE_BYTES`, `trusted=False`) | `test_ssrf_redirect_to_private_target_is_blocked`, `test_credentialed_link_is_stripped_and_never_reaches_network` |
| §2 ref со слэшами: перебор кандидатов, `ref` в query (`commits?sha=`, `contents?ref=`) | `_ref_path_candidates`, `_resolve_identity` | `test_branch_with_slash_has_shortest_ref_first`, `test_commit_pinned_url_skips_branch_resolution`, `test_reuse_same_link_with_branch_slash_reuses` |
| §2 эндпоинты `contents/blobs/raw/tree/commits/search.repositories`, id эндпоинта в `provenance.endpoint` | `ENDPOINT_*`, `SourceFile.endpoint` | `test_blob_link...` (`endpoint in {contents,blobs,raw}`, `"://" not in provenance`) |
| §3 discovery без словарей: ссылка → 0 поисковых вызовов; имя → `repos`; описание → `search.repositories` + каскад (только URL-формы) | `_discover`, `_discover_candidates`, `_cascade_candidates`, `_score_repo`, `rank_paths` | `TestDiscovery` (3 теста), `TestUrlParsing::test_non_url_and_repo_spec` |
| §3 неоднозначность → `ambiguous` + ≤3 кандидата + ОДИН вопрос | `_ambiguous_payload`, `_ambiguous` | `test_two_equally_plausible_repos_ask_one_question` |
| §3 `search_found ≠ source_fetched` | `_kind_for_path`, `_read_payload` | `test_readme_is_read_but_never_verified`, `test_description_only...` |
| §4 bounded follow-up: идентификаторы из тела → стемы дерева → `files[]` с собственными `verified/line_range/verified_url` | `sibling_identifiers`, `rank_sibling_paths`, `_followup` | `TestFollowUp` (5 тестов) |
| §4 «класс лишь выставляет параметр» → обязательный обход + `followup_incomplete` + `not_checked` | `is_parameter_only`, ветка `parameter_only` | `test_parameter_only_triggers_chain_and_reports_not_checked` |
| §4 лимиты `SOURCE_READ_MAX_FILES/DEPTH/REQUESTS/FILE_BYTES` (3/1/8/2 МБ, потолки 6/2/16) | `config/settings.py:1449-1459`, `max_files/max_depth/max_requests`, `_exhausted()` | `test_file_budget_produces_untried_paths`, `test_request_budget_fuse_stops_the_lookup` |
| §4 сбой дерева не отменяет подтверждённое чтение | `_followup` (try/except → `not_checked.reason="tree_unavailable"`) | `test_tree_failure_does_not_destroy_verified_read` |
| §5 таксономия отказов, 0 новых `REASON_CODES` | `_classify_http_status`, `_REASON_FOR_CODE` (все значения проверены по словарю) | `TestHonestFailures`, `test_every_mapped_reason_code_exists_in_dictionary` |
| §6 kill-switch env-only, гейт анонса, схема безусловна | `config/settings.py:1449`; `services/tool_schemas.py:1023` (гейт), применение — `services/tool_schemas.py:1146`; серверный отказ — `services/tool_router.py:2906` | `test_kill_switch_off_hides_tool_and_performs_no_lookup`, `test_disabled_provider_path_reports_disabled` |
| §6 `METERED_TOOLS` | `services/tool_loop.py:67`, `:82` | `test_metered_and_read_only_evidence_classification` |
| §6 capability/evidence-проводка (мёртвый флаг снят) | `services/evidence_policy.py:183`, `services/direct_chat_service.py:2395`, `services/capability_registry.py:872` | `TestEvidencePolicyChain` (4 теста) |
| §6 телеметрия стадий, R17 | `_emit_stage` через существующий `mca_retrieval_context.emit_stage_event` | `TestTelemetry` (2 теста) |
| §6/§3 повторное чтение — существующий `source_reuse`, TTL, chat-isolation | `_source_identity`, `_source_pointer_matches`, `_source_reuse_payload` | `TestQualifiedReuse` (9 тестов) |

## 2. Где именно гейт анонса

`services/tool_schemas.py:1023` — `read_source_code_enabled()` (env-only
`SOURCE_READ_ENABLED`, default ON); применение —
`services/tool_schemas.py:1146` (`disabled.add(SOURCE_READ_TOOL_NAME)` внутри
`active_tools`). Схема и канон `TOOL_CALLING_TOOLS == 16` безусловны.

## 3. Тесты и mutation-проверки

Файл: `tests/test_evol_source_reader.py` — **74 теста**, сети нет: провайдер
работает через существующий `SafeFetcher` с `httpx.MockTransport`, DNS-резолв
подменён (`sf._resolve_ip`), фикстурный GitHub отдаёт фиксированные байты/JSON.

Mutation-проверки (временный откат фикса → RED, восстановление → GREEN, EOL
файла сохраняется байт-в-байт):

| # | Что сломано | RED | GREEN |
|---|---|---|---|
| B1a | `split_lines` снова `str.splitlines()` (теряет CR) | 2 failed (`crlf_file_verifies...`, `decode_rule_is_strict`) | 7 passed |
| B1b | декодирование с latin-1-откатом и без проверки бинаря | 3 failed (`binary_file_never_verifies`, `invalid_utf8_is_not_source`, `decode_rule_is_strict`) | 7 passed |
| B2a | identity снова из сырых аргументов (ссылка игнорируется) | 1 failed (`reuse_same_link_with_branch_slash_reuses`) | 9 passed |
| B2b | сверка указателя игнорирует `ref` (только `path`) | 3 failed (`other_ref`, `changed_ref`, `changed_commit`) | 9 passed |
| B3 | повторный срез `snippet` до 2000 символов | 1 failed (`reuse_keeps_honest_truncation_metadata`) | 1 passed |
| N1 | сигнал снова читает только dict-форму `error` | 2 failed (`fetch_failure_sets_out_of_band_signal`, `provider_5xx_signal_is_retryable`) | 3 passed |

## 4. Отклонения от буквы контракта и почему

1. **Порядок кандидатов ref**: «короткий ref первым» — иначе обычная ссылка
   `blob/<branch>/<глубокий путь>` не находится за лимит 4 пробы, а квота
   GitHub без токена 60/час. Требование про ветки со слэшем выполняется при
   любом порядке («первый 200 = истина»). Reviewer признал деталь приемлемой.
2. **Имя события телеметрии**: `mca07_source_discover|locator|fetch|followup` —
   §1.2.5 требует различимости стадий, что в одном событии невозможно.
3. **`snippet` без префиксов номеров строк**: доставляется точная подстрока
   байт, номера — в `line_range`/`files[].line_range`. Иначе V1.3 стал бы
   непроверяемым, либо появилась бы вторая копия текста.
4. **`error` строкой-кодом**, полная запись в `error_detail` — совместимость с
   `tool_result._payload_error_code` без правок конвейера.
5. **Порядок эндпоинтов файла**: `contents?ref` → `blobs` (sha, >1 МБ) → `raw`.
6. **`no_relevant_results`** — только payload-код; в телеметрию уходит
   существующий `retrieval_empty`.
7. **`METERED_EVIDENCE_READ_ONLY`** — по ER-08 (read-only проверка не режется
   денежным счётчиком); анти-петлевые границы сохранены.
8. **`payload.ref` = ref, к которому чтение реально привязано** (резолвнутый),
   а не сырая догадка разбора `/blob/`: для ветки `feature/x` «сырое» значение
   `feature` вводило бы в заблуждение и ломало reuse-идентичность.

## 5. Статус строк карты (`requirements-map.json`, слайс `EVOL-SRC-READER`)

В слайсе 61 строка: 30 `required` + 5 `duplicate`-заголовков с `req_id
EVOL-SRC-READER` + 26 уже `VERIFIED` строк других слайсов (`ER-*`). Карту я не
правил (рамка задачи): статус проставляет PM/Reviewer по этому отчёту.

| Строка | О чём | Статус в моей части | Доказательство |
|---|---|---|---|
| L01184 | прямая ссылка на файл/директорию/репозиторий | provable | `TestUrlParsing`, `test_blob_link_returns_verified_commit_pinned_fragment` |
| L01185 | только название репозитория | provable | `test_repo_name_then_locate_then_verified_read`, `parse_repo_spec` |
| L01186 | только естественное описание механизма | provable | `test_description_only...`, `test_two_equally_plausible...` |
| L01196 | Repository Discovery | provable | `_discover/_discover_candidates/_score_repo`, `TestDiscovery` |
| L01197 | Source Locator (README ≠ исходник) | provable | `rank_paths`, `is_parameter_only`, `test_readme_is_read_but_never_verified` |
| L01198 | Verified Fetch (contents/raw/API, commit, слэш-ветки) | provable | `GitHubProvider.read_file`, `TestVerifiedFetch`, `TestByteSemantics` |
| L01199 | Bounded Follow-up | provable | `_followup`, `TestFollowUp` (5) |
| L01200 | Evidence Contract (объём/обрезка/provenance/стадии) | provable | `_read_payload/_not_source_payload/_error_payload`, `TestEvidenceHonesty`, `TestTelemetry`, `test_reuse_keeps_honest_truncation_metadata` |
| L01206 | однозначный репозиторий находится сам | provable (в части инструмента) | discovery без ссылки; маршрутизация — L1/Writer (промпт-канон не менялся) |
| L01207 | конкурирующие репозитории → кандидаты + одна развилка | provable | `test_two_equally_plausible_repos_ask_one_question` |
| L01208 | действующая ссылка на файл/строки/commit | provable | `verified_url` commit-pinned |
| L01209 | конкретный технический результат отказа | provable | `_classify_http_status`, `TestHonestFailures` (6) |
| L01210 | исходный случай (GregTech…), без зашитых имён | provable (структурно) | в коде нет имён примера; имена только в тестовых данных |
| L01211 | «найди файл» → подтверждённое чтение | provable (в части инструмента) | `verified=false` без байт; обязательный `source_kind=="file"` |
| L01217 | не выдумывать прошлые реплики и даты | provable (в части payload) | `test_payload_never_carries_chat_chronology_or_quotes` |
| L01218 | исправление ошибки — не новая фантазия | provable (в части payload) | повторное чтение даёт те же байты/строки; временных полей нет |
| L01219 | диалоговые обязательства | не менялось этим слайсом | промпт-канон байт-в-байт (ER-65 OK) |
| L01220 | точный смысл статуса инструмента | provable | `verified` только по байтам; `source_missing` ≠ `symbol_not_found`; `TestByteSemantics` (бинарь/пустой/каталог ≠ «нет файла») |
| L01221 | характер бота тот же | не менялось этим слайсом | `chat_prompts/prompt_*` не тронуты |
| L01223 | §1.5 приёмка без живых проверок | provable | 74 детерминированных теста |
| L01228 | blob-ссылка → проверенное содержимое | provable | `test_blob_link_returns_verified_commit_pinned_fragment` |
| L01229 | имя + описание → discovery → fetch → связанный файл | provable | `test_repo_name_then_locate_then_verified_read` |
| L01230 | только описание → найден либо честная неоднозначность | provable | `test_description_only...`, `test_two_equally_plausible...` |
| L01231 | «лишь выставляет параметр» → цепочка | provable | `test_parameter_only_triggers_chain...`, `test_depth_limit_is_reported_not_hidden` |
| L01232 | 403/404/rate limit/timeout/HTML/сниппет → честный статус | provable | `TestHonestFailures` (404, 403+rate, 403, 502, HTML, чужой хост, SSRF) + `TestByteSemantics` |
| L01233 | неверная дата → нет выдуманной хронологии | provable (в части payload) | `test_payload_never_carries_chat_chronology_or_quotes` |
| L01234 | нет лишних вызовов/утечек/обхода прав/исполнения | provable | `TestQualifiedReuse` (0 вызовов на reuse), AST-инвариант, `test_payload_never_contains_tokens...` |
| L02230 (ER-50) | discovery → verified code fetch с ref/commit/line range | provable (в части инструмента) | весь набор выше |
| L02360 (ER-S03) | «найди файл/реализацию» без URL | provable (в части инструмента) | discovery без ссылки; маршрутизация — L1 |
| L02401 (ER-S35) | исходный код из локального файла пользователя | вне рамки слайса | — |

Граница честности: «в части инструмента» не доказывает поведение LLM.

## 6. Что добавил бы живой прогон (границы доказательства)

`live_required=false`, `live_when=preprod`. Живой GitHub дал бы: реальную
анонимную квоту и `x-ratelimit-remaining`, отсутствие REST-квоты у `raw`,
secondary rate limit (403 без `retry-after`), `tree_truncated` на огромных
репозиториях, приватный доступ с токеном, слэш-ветки в реальном репозитории,
CRLF-исходник из реального репозитория (после B1), маршрутизацию в живом
диалоге. Ни один пункт не является гейтом §1.5.

## 7. ER-65 snapshot

Не перегенерировался: pinned sources этого слайса (`/sources` — промптовые
модули, `tool_loop`, `tool_schemas`, `direct_chat_service`) не менялись после
ревизии 1. `tools/er65_prompt_segment_snapshot.py --check` → OK (27 стадий / 58
сегментов, два изолированных процесса байт-в-байт). Промпт-канон не тронут.

## 8. Инцидентальные находки

- Предсуществующие падения базы (55 тестов: webapp/UI, summary-волны,
  `test_104` c `toggleModule`, `test_mca11_money_limits`, `test_mca23`
  routes-sha) — не мои, воспроизводятся на `5fc2ded5`.
- Порядко-зависимые тесты (`test_dream_belief_bot_provenance`,
  `test_factcheck_fc_r1_fix`) падают только в общем прогоне, изолированно PASS.
- `plans/current_task.md` в worktree не отслеживается git; читал из основного
  репозитория, не менял.

## 9. Рамка записи и файлы

Новые: `services/source_reader.py`, `tests/test_evol_source_reader.py`, этот
отчёт. Правки: `services/tool_schemas.py`, `config/settings.py`,
`services/tool_loop.py`, `services/tool_router.py`,
`services/capability_registry.py`, `services/direct_chat_service.py`,
`services/evidence_policy.py`, `plans/features/evol/evidence/er65/*`, пин-тесты
канона (16 файлов). Не тронуты: `services/prompt_*`, `services/chat_prompts.py`,
`web/**`, `services/safe_fetch.py`, `services/source_reuse.py`,
`services/mca_events.py`, `services/search_aggregator.py`,
`services/web_content_extractor.py`, `handlers/**`, `bot.py`.
Деплой не выполнялся; в Telegram ничего не отправлялось.

## 10. Ревизия 2 — исправления по независимому ревью

### B1. Байтовые семантики (`services/source_reader.py`)

**Правило декодирования (новое):** `decode_source_bytes(data)`:
1. пустые байты → `empty_content`;
2. NUL в **сырых** байтах → `binary_content` (бинарь однозначен);
3. строгий `utf-8` **без откатов** → ошибка → `invalid_encoding`;
4. доля управляющих символов (все, кроме `\t\n\r\f\v`) > 2% → `binary_content`;
5. иначе — `ok=True`.

`ok=False` → `status:"unsupported"` + `reason` (закрытые теги
`invalid_encoding|binary_content|empty_content|path_is_directory|symlink|submodule`),
`snippet=""`, `verified=false`. Это НЕ `source_missing`: файл существует.

**Строки и фрагмент:** `split_lines` делит только по `\n` и сохраняет `\r`
(CRLF-файл не теряет перевод строки); `build_snippet` режет **по смещениям строк**
(`line_spans`) исходного текста, поэтому `snippet` — точный срез байт при любых
переводах строк, а `line_range` считается по реальному файлу. Синтаксический
разбор (поиск символа, «параметр-только») снимает хвостовой `\r`
(`strip_line_ending`), чтобы CRLF не влиял на распознавание форм.

Наблюдаемые числа (пробы на одинаковом сценарии):
| Проба | До (кандидат `daf0385a`) | После |
|---|---|---|
| A. CRLF-исходник | `status=ok, verified=False` (причина не указана) | `status=ok, verified=True`, snippet=124 симв., `\r\n` сохранены, построчное совпадение с `line_range` |
| I. Бинарный файл (PNG+NUL) | `status=ok, verified=True` с NUL в snippet | `status=unsupported, verified=False, reason=binary_content`, snippet=0 |

### B2. Идентичность reuse (`services/tool_router.py`)

**Поля идентичности (новое):** `_source_identity(url, repo, ref, path, symbol)`
→ `{repo, pairs: ((ref, path), …), ref, path, symbol}`, где `repo` берётся из
ссылки (`parse_source_url`) либо из `repo`-аргумента, а `pairs` — все допустимые
пары `(ref, path)` из ссылки («короткий ref первым») плюс явные аргументы.
`_source_pointer_matches` требует: `pointer.repo == identity.repo` (когда repo
известен) И `(pointer.ref, pointer.path) ∈ identity.pairs` (когда есть пары);
если пар нет — reuse допустим только внутри того же repo и только на уже
найденный непустой path. Дополнительно: совпадение `delivered_chars` с длиной
сохранённого фрагмента; `commit` и `sha256` обязательны; discovery reuse не
использует вовсе.

Наблюдаемые числа:
| Проба | До | После |
|---|---|---|
| B. две ссылки, разные ref, один claim | `reused=True, ref=main, network_calls=0` (чужой commit как verified) | `reused=False, ref=main, network_calls>0` — читается запрошенная версия |
| C. вторая ссылка на другой файл | `reused=True`, отдан чужой `ParallelLogic.java` | `reused=False, path=ParallelConfig.java`, `chanceLimit` в snippet |
| слэш-ветка `feature/x`, та же ссылка дважды | reuse работал, но `ref` показывался как `feature` | `ref=feature/x`, `reused=True, network_calls=0` |

### B3. Честная обрезка на reuse (`services/tool_router.py`)

**Правило (новое):** в запись источника кладётся **весь доставленный** фрагмент
(без среза до 2000) и метаданные именно этого фрагмента:
`delivered_chars, truncated, why, effective_limit, remainder_lines, line_range,
file_total_lines, language, symbol, symbol_found, parameter_only`. Reuse-ответ
воспроизводит эти значения (`limit_source="reuse"`), а при расхождении
`delivered_chars` и длины сохранённого текста запись не используется (лучше
перечитать, чем отдать усечённое как полное). Память: LRU 256 записей ×
доставленный фрагмент (ограничен evidence-окном, обычно ≤ 10 тыс. симв.).

Наблюдаемые числа (файл 1200 строк, бюджет 8000):
| | До | После |
|---|---|---|
| 1-й read | chars=9983, range=[1,510], truncated=True, rem=690 | то же |
| повтор | chars=2000, range=[1,510], truncated=False, rem=0 | chars=9983, range=[1,510], truncated=True, rem=690, `reused=True`, network_calls=0 |

### Миноры

* **N1 (исходящий сигнал §2)**: читается `error_detail` (dict-форма `error`
  поддержана для совместимости). `take_signal(ctx)` теперь отдаёт
  `{error_code, stage, reason, retryable}`; тесты: 404 → `source_missing`
  `retryable=False`, 502 → `provider_unavailable retryable=True`.
* **N2 (каталог/пустой файл)**: `unsupported` + `reason=path_is_directory`
  (`source_kind=directory`) и `reason=empty_content`; `source_missing` остался
  только для реального «нет repo/ref/path».
* **N3 (`capability_not_ready` вне словаря)**: подтверждено — значения нет в
  `mca_events.REASON_CODES` (314). `ERR_UNSUPPORTED_KIND` отображается на
  существующий `parse_error`; добавлен тест
  `test_every_mapped_reason_code_exists_in_dictionary`, проверяющий **все**
  значения `_REASON_FOR_CODE` по словарю.
* **N4 (вакейтный тест креденшелов)**: переписан в
  `test_credentialed_link_is_stripped_and_never_reaches_network`: проверяет
  фактические хосты контактов (`api.github.com`/`raw.githubusercontent.com`),
  отсутствие `user:pass`/`Authorization`/URL в payload и то, что сам
  `SafeFetcher.guarded_target` отклоняет креденшелы (`credentials_in_url`).
* **N5 (перекодирование EOL)**: рабочая копия приведена к окончаниям строк базы;
  кумулятивный диф к `5fc2ded5` идентичен с `--ignore-cr-at-eol` и без него
  (31 файл, +4154/−83), перекодирования в коммите нет.
* **N6 (мелочи)**: `capability_registry` указывает исполнителя
  `services.tool_router` (фактический обработчик); неиспользуемый `safe_log_ref`
  удалён; `files[].verified` в follow-up учитывает `source_kind=="file"` и
  пропускает нечитаемые (не-UTF-8) смежные файлы.

Дополнительно (найдено при пробах): сбой дерева на этапе follow-up больше не
превращает уже подтверждённое чтение в ошибку — цепочка помечается неполной
(`not_checked.reason="tree_unavailable"`), тест
`test_tree_failure_does_not_destroy_verified_read`.

### Прогоны ревизии 2

* `tests/test_evol_source_reader.py` — **74 passed**;
* 22 файла регрессии канона/ER-65 — **966 passed**, `er65 --check` OK;
* mutation-матрица (6 мутаций, откат каждого фикса) — RED→GREEN, см. §3.
