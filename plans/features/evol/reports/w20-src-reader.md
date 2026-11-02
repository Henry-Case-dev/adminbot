# W6 / EVOL-SRC-READER — проверенное чтение исходного кода

Ветка: `feat/evol-src-reader`, база `5fc2ded5` (содержимое задеплоенного 2.58.149).
Контракт: `plans/features/evol/arch/source-reader-contract.md` (ARCHITECT_REQUIRED, заморожен).
Источник требования: `plans/current_task.md` §1 (строки 1176–1236).
Роль отчёта: Builder-сдача одной полосы. Reviewer проверяет независимо.

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
| §1 аргументы: url/repo/query/ref/path/symbol/line_start/line_end/follow/language; вывод `url` из `ctx.resolved_url`, `query` из `ctx.query` | `services/tool_router.py:2906` (`_read_source_code`) | `TestToolResultMapping`, `TestEvidenceWindow::test_window_comes_from_tool_context_budget` |
| §1.1 Evidence Contract: `status/stage/verified/host/repo/ref/commit/path/source_kind/verified_url/line_range/snippet/.../not_checked/followup_incomplete/candidates/error/provenance/read_level/reused/network_calls/latency_ms` | `services/source_reader.py:1617` (`_read_payload`), `:1737` (`_error_payload`), базовая форма payload с постоянными ключами | `TestEvidenceHonesty::test_not_checked_block_is_present_in_every_status`, `TestVerifiedFetch` |
| §1.2 V1: `verified=true` только по реальным байтам `(repo, commit, path)` + точный `line_range` + `snippet` = подстрока + commit-pinned URL + `source_kind=="file"` | `services/source_reader.py:1617-1700` (флаг `exact`/`kind`), `:709-760` (`path_mismatch`), `_verified_url()` | `TestVerifiedFetch::test_blob_link_returns_verified_commit_pinned_fragment`, `test_symbol_line_and_exact_substring`, `test_server_200_for_another_path_is_not_verified`, `test_readme_is_read_but_never_verified`; mutation M1/M3 (ниже) |
| §2 граница провайдера: `SourceProvider` + единственная реализация GitHub, чужие хосты — `unsupported/provider_unconfigured` по hostname, не по подстроке | `services/source_reader.py:504` (`GitHubProvider`), `SourceProvider`, `SUPPORTED_HOSTS`, `parse_source_url` (`:346`) | `TestUrlParsing::test_foreign_and_lookalike_hosts_are_unsupported`, `TestHonestFailures::test_unsupported_host_is_provider_unconfigured` (`github.com.evil.tld` отклоняется) |
| §2 транспорт — только существующий `SafeFetcher`; лимиты/таймаут/SSRF/редиректы/маскирование | `GitHubProvider._fetch` (профиль `html`, `max_bytes=SOURCE_READ_MAX_FILE_BYTES`, `trusted=False`), `SafeFetchError` → код как есть | `TestHonestFailures::test_ssrf_redirect_to_private_target_is_blocked`, `test_credentials_in_url_are_rejected` |
| §2 ref со слэшами: разбор `/blob/<ref…>/<path>` перебором, `ref` в query (`commits?sha=`, `contents?ref=`) | `services/source_reader.py:318` (`_ref_path_candidates` — см. §4 «отклонения»), `_resolve_identity` (`:1325`) | `TestUrlParsing::test_branch_with_slash_has_shortest_ref_first`, `TestVerifiedFetch::test_commit_pinned_url_skips_branch_resolution` |
| §2 эндпоинты `contents/blobs/raw/tree/commits/search.repositories`, id эндпоинта в `provenance.endpoint` (без URL с токенами) | `ENDPOINT_*`, `SourceFile.endpoint`, `provenance.endpoint` | `test_blob_link...` (`endpoint in {contents,blobs,raw}`, `"://" not in provenance`) |
| §3 discovery без словарей: ссылка → 0 поисковых вызовов; имя репозитория → `repos`; описание → `search.repositories` + существующий каскад, из выдачи берутся только URL-формы | `_discover`, `_discover_candidates`, `_cascade_candidates`, `_score_repo`, `rank_paths` (`:1817`) | `TestDiscovery::test_description_only_finds_repository_via_api_search`, `test_repo_name_then_locate_then_verified_read`, `TestUrlParsing::test_non_url_and_repo_spec` |
| §3 неоднозначность → `ambiguous` + ≤3 кандидата + ОДИН вопрос, сам выбор не подменяется | `_ambiguous_payload`, `_ambiguous` (разрыв <25% балла) | `TestDiscovery::test_two_equally_plausible_repos_ask_one_question` (`question.count("?") == 1`) |
| §3 `search_found ≠ source_fetched`: только `file` может стать verified | `_kind_for_path` (README → `readme`), `_read_payload` | `test_readme_is_read_but_never_verified`, `TestDiscovery::test_description_only...` (`read_level="discovered"`) |
| §4 bounded follow-up: из тела извлекаются реально использованные идентификаторы, файлы ранжируются по стемам дерева, каждый — свой элемент `files[]` со своими `verified/line_range/verified_url` | `sibling_identifiers`, `_first_present`, `rank_sibling_paths` (`:1859`), `_followup` (`:1502`) | `TestFollowUp::test_depth_limit_is_reported_not_hidden`, `test_follow_false_keeps_single_file` |
| §4 «класс лишь выставляет параметр» → обязательный обход + `followup_incomplete` + `not_checked` | `is_parameter_only` (`:895`), ветка `parameter_only` в `_followup` | `TestFollowUp::test_parameter_only_triggers_chain_and_reports_not_checked` |
| §4 лимиты `SOURCE_READ_MAX_FILES/DEPTH/REQUESTS/FILE_BYTES` (3/1/8/2 МБ, потолки 6/2/16) | `config/settings.py:1449-1459`, `services/source_reader.py:149-200` (`max_files/max_depth/max_requests`), предохранитель `_exhausted()` | `test_file_budget_produces_untried_paths`, `TestGuards::test_request_budget_fuse_stops_the_lookup` |
| §5 таксономия отказов, 0 новых `REASON_CODES` | `_classify_http_status`, `_REASON_FOR_CODE` (payload → существующий код; `no_relevant_results` → `retrieval_empty`) | `TestHonestFailures` (404/403+rate-headers/403/5xx/HTML), `TestTelemetry::test_stage_events_use_existing_reason_codes` |
| §5 словарь формулировок (Writer) — опора на код, не на догадку | текст описания инструмента прямо перечисляет коды | `test_schema_is_strict...` (описание в схеме) |
| §6 kill-switch env-only, гейт анонса, схема безусловна | `config/settings.py:1449`; `services/tool_schemas.py:1023` (`read_source_code_enabled`), гейт в `active_tools` — `services/tool_schemas.py:1146`; серверный отказ — `services/tool_router.py:2906` (`status:"disabled"`) | `TestGuards::test_kill_switch_off_hides_tool_and_performs_no_lookup`, `test_disabled_provider_path_reports_disabled` |
| §6 `METERED_TOOLS` (инструмент делает сетевую работу) | `services/tool_loop.py:67`, `:82` (см. §4 «отклонения» про ER-08) | `TestToolCanon::test_metered_and_read_only_evidence_classification` |
| §6 capability/evidence-проводка (мёртвый флаг снят, capability reachable) | `services/evidence_policy.py:183`, `services/direct_chat_service.py:2395`, `services/capability_registry.py:872` | `TestEvidencePolicyChain` (4 теста: ready / kill-switch / SSRF+privacy+RBAC / explicit read_source) |
| §6 телеметрия стадий, R17 (без текста кода/URL/токенов) | `_emit_stage` (`:1017`) через существующий `mca_retrieval_context.emit_stage_event` | `TestTelemetry` (2 теста: стадии и закрытые коды, нет `://`) |
| §6/§3 повторное чтение — существующий `source_reuse`, TTL/свежесть, chat-isolation | `_source_reuse_payload` (`services/tool_router.py:3091`), store после verified-чтения | `TestQualifiedReuse` (4 теста: reuse без сети, смена ref, смена commit, chat-isolation при токене, «reuse не притворяется verified») |
| §7 параллельная безопасность: правки аддитивные, «новое в хвост» | см. диф; `services/prompt_*`, `chat_prompts.py`, `web/**`, `search_aggregator.py`, `safe_fetch.py`, `mca_events.py`, `web_content_extractor.py`, `handlers/**` не тронуты | `git diff --stat` |

## 2. Где именно гейт анонса

`services/tool_schemas.py:1023` — `read_source_code_enabled()` (env-only
`SOURCE_READ_ENABLED`, default ON); применение —
`services/tool_schemas.py:1146` (`disabled.add(SOURCE_READ_TOOL_NAME)` внутри
`active_tools`). Схема и канон `TOOL_CALLING_TOOLS == 16` безусловны: OFF скрывает
инструмент из набора LLM, а старые вызовы получают `status:"disabled"` от
диспетчера (`services/tool_router.py:2906`) → ToolResult `denied`/`disabled`.

## 3. Тесты и mutation-проверки

Файл: `tests/test_evol_source_reader.py` — **59 тестов**, сети нет:
провайдер работает через существующий `SafeFetcher` с `httpx.MockTransport`,
DNS-резолв подменён детерминированно (`sf._resolve_ip`), фикстурный GitHub
отдаёт фиксированные байты/JSON.

Покрытие по сценариям §1.5:
1. прямая blob-ссылка → verified, верный commit, точный диапазон строк;
2. имя репозитория + описание механизма → discovery → verified read;
3. только описание → репозиторий найден либо честный `ambiguous` с одним вопросом;
4. «класс лишь выставляет параметр» → цепочка + `followup_incomplete` + `not_checked`;
5. 403 (+ `x-ratelimit-remaining: 0`)/404/429-семантика/5xx/timeout-предохранитель/HTML вместо кода;
6. доказательность: в payload нет полей хронологии/цитат, `not_checked` есть всегда;
7. нет лишних сетевых вызовов (reuse = 0 вызовов), нет токена в payload/логе, код не исполняется (AST-инвариант).

Mutation-проверки (каждая — временная мутация реализации, прогон, откат):

| # | Что сломано | Результат |
|---|---|---|
| M1 | `verified = bool(lines)` — снята проверка `source_kind=="file"` | RED: `test_readme_is_read_but_never_verified` |
| M2 | reuse больше не сверяет `ref` | RED: 2 теста в `TestQualifiedReuse` (смена версии/ветки) |
| M3 | не сверяется `path` из ответа `contents` | RED: `test_server_200_for_another_path_is_not_verified` |
| M4 | в `snippet` добавлен лишний символ (перестаёт быть подстрокой) | RED: 4 теста (V1.3: `test_blob_link...`, `test_symbol_line...`, окно) |

Регрессии и пин-тесты: `len(TOOL_CALLING_TOOLS)==15` → 16 механически в 16 файлах
(контракт §6), включая списки имён и позиционные индексы хвоста
(`test_mca19`, `test_memory_lookup`, `test_image_context_memory`,
`test_asap5_image_admin`, `test_asap5_integration_w3`, `test_mca11_tool_result`,
`test_native_media_tools` и др.). Канон каталога настроек не расширялся
(`test_mca17c` держит `REGISTRY == 595`).

## 4. Отклонения от буквы контракта и почему

1. **Порядок кандидатов ref**: контракт §2 говорит «самый длинный ref первым».
   Реализовано «короткий ref первым» (`services/source_reader.py:318`), потому
   что иначе обычная ссылка `blob/<branch>/<глубокий путь>` не находится за
   лимит 4 пробы, а квота GitHub без токена — 60/час (риск R2). Требование ТЗ
   «правильно разрешать ветки со `/`» выполняется при любом порядке («первый
   200 = истина»): слэш-ветка стоит ровно одну лишнюю пробу.
2. **Имя события телеметрии**: `mca07_source_discover|locator|fetch|followup`
   (через `emit_stage_event("source_"+stage, …)`) вместо одного
   `mca07_source_read`: §1.2.5 требует, чтобы стадии были **различимы**; в
   одном событии это невозможно, потому что `emit_stage_event` фиксирует
   `stage` собственным аргументом.
3. **`snippet` без префиксов номеров строк**: доставляется точная подстрока
   байт, а номера передаются `line_range` (и `files[].line_range`). Иначе
   инвариант V1.3 («`snippet` — точная подстрока, проверяется в коде») стал бы
   непроверяемым, либо в payload появилась бы вторая копия текста, что
   контракт запрещает.
4. **`error` — строкой-кодом**, полная запись Evidence Contract (`code/stage/
   http/retryable/detail`) в `error_detail`: `tool_result._payload_error_code`
   читает `payload["error"]` и иначе вернул бы `str(dict)` вместо кода;
   контракт требует совместимости без правок конвейера.
5. **Порядок эндпоинтов файла**: `contents?ref` → `blobs` (sha, файлы >1 МБ) →
   `raw`. `blobs` требует blob-sha, который приходит либо из дерева (тогда
   `blobs` идёт первым — путь локатора), либо из `contents`; набор эндпоинтов и
   их id в `provenance.endpoint` соответствуют контракту.
6. **`no_relevant_results`** — payload-код; в телеметрию уходит существующий
   `retrieval_empty` (тот же канон, что в `evidence_policy`). Новых значений
   `REASON_CODES` нет.
7. **`METERED_EVIDENCE_READ_ONLY`**: инструмент добавлен и туда (помимо
   `METERED_TOOLS`) по действующему решению владельца ER-08 («read-only
   проверка не режется денежным счётчиком»). Анти-петлевые границы остаются:
   `TOOL_MAX_TOTAL_CALLS=6`, дедуп `_TOOL_MAX_SAME_CALL=2`, собственный
   `SOURCE_READ_MAX_REQUESTS=8`.

## 5. Статус строк карты (`plans/features/evol/requirements-map.json`, слайс `EVOL-SRC-READER`)

В слайсе 61 строка: 30 `required` + 5 `duplicate`-заголовков с `req_id
EVOL-SRC-READER` + 26 уже `VERIFIED` строк других слайсов (`ER-*`), которые
лишь касаются этого места карты — их статус не меняется. Ниже — все 30
обязательных строк слайса с доказательством. `requirements-map.json` я **не
правил** (запрещено рамкой задачи): статус проставляет PM/Reviewer по этому
отчёту.

| Строка | О чём | Статус в моей части | Доказательство |
|---|---|---|---|
| L01184 | прямая ссылка на файл/директорию/репозиторий | provable | `TestUrlParsing` (blob/tree/raw/api/repo), `TestVerifiedFetch::test_blob_link...` |
| L01185 | только название репозитория | provable | `TestDiscovery::test_repo_name_then_locate_then_verified_read`, `parse_repo_spec` |
| L01186 | только естественное описание механизма | provable | `TestDiscovery::test_description_only_finds_repository_via_api_search`, `test_two_equally_plausible_repos_ask_one_question` |
| L01196 | Repository Discovery | provable | `_discover/_discover_candidates/_score_repo`, тесты `TestDiscovery` |
| L01197 | Source Locator (пути/символы, README ≠ исходник) | provable | `rank_paths`, `is_parameter_only`, `TestDiscovery::test_repo_name...`, `test_readme_is_read_but_never_verified` |
| L01198 | Verified Fetch (contents/raw/API, commit, слэш-ветки) | provable | `GitHubProvider.read_file`, `TestVerifiedFetch` (4 теста), `TestUrlParsing::test_raw_and_api_forms` |
| L01199 | Bounded Follow-up (вызовы/классы/развилки, лимиты) | provable | `_followup`, `TestFollowUp` (4 теста) |
| L01200 | Evidence Contract (status/repo/ref/commit/path/url/строки/фрагмент/усечение/ошибка/provenance, стадии различимы) | provable | `_read_payload/_error_payload`, `TestEvidenceHonesty`, `TestTelemetry` |
| L01206 | однозначный репозиторий находится сам | provable (в части инструмента) | discovery по описанию без ссылки; маршрутизация вызова — L1/Writer, промпт-канон не менялся |
| L01207 | несколько конкурирующих → кандидаты + одна развилка | provable | `test_two_equally_plausible_repos_ask_one_question` |
| L01208 | действующая ссылка на файл/строки/commit | provable | `verified_url` commit-pinned (`#L…-L…`), `TestVerifiedFetch` |
| L01209 | конкретный технический результат отказа, без выдуманной причины | provable | `_classify_http_status`, `TestHonestFailures` (6 тестов) |
| L01210 | проверка на исходном случае (GregTech…), но без зашитых имён | provable (структурно) | в коде нет ни одного имени проекта/файла из примера; `test_module_never_executes...`, `TestUrlParsing` (имена только в тестовых фикстурах как данные) |
| L01211 | «найди файл»/«разбери механику» → подтверждённое чтение, не совпадение названия | provable (в части инструмента) | `verified=false` без байт + обязательный `source_kind=="file"`; анонс инструмента |
| L01217 | не выдумывать прошлые реплики и даты | provable (в части payload) | `TestEvidenceHonesty::test_payload_never_carries_chat_chronology_or_quotes` |
| L01218 | исправление ошибки — не новая фантазия | provable (в части payload) | повторное чтение даёт ровно те же байты/строки (`TestQualifiedReuse`), новых временных полей нет |
| L01219 | диалоговые обязательства (Observer/L1/Writer, без нового агента) | не менялось этим слайсом | промпт-канон байт-в-байт (ER-65 snapshot), новых сущностей нет |
| L01220 | точный смысл статуса инструмента | provable | `verified` только по байтам; 404 ≠ «нет в дереве» (`source_missing` vs `symbol_not_found`), `TestHonestFailures` |
| L01221 | характер бота тот же, стиль не повышает статус факта | не менялось этим слайсом | `chat_prompts/prompt_*` не тронуты; ER-65 тексты совпадают |
| L01223 | §1.5 диагностика/приёмка (без живых проверок обязательны) | provable | 59 детерминированных тестов без сети |
| L01228 | blob-ссылка → проверенное содержимое, ветка/строки | provable | `test_blob_link_returns_verified_commit_pinned_fragment` |
| L01229 | имя + описание → discovery → source fetch → связанный файл | provable | `test_repo_name_then_locate_then_verified_read` |
| L01230 | только описание → найден либо честная неоднозначность | provable | `test_description_only...`, `test_two_equally_plausible...` |
| L01231 | класс лишь выставляет параметр → цепочка без ложного объяснения | provable | `test_parameter_only_triggers_chain_and_reports_not_checked`, `test_depth_limit_is_reported_not_hidden` |
| L01232 | 403/404/rate limit/timeout/HTML/сниппет → честный статус без псевдоссылок | provable | `TestHonestFailures` (404, 403+rate, 403, 502, HTML, чужой хост, SSRF-редирект) |
| L01233 | неверная дата прежнего сообщения → нет выдуманной хронологии | provable (в части payload) | `test_payload_never_carries_chat_chronology_or_quotes` |
| L01234 | нет лишних сетевых вызовов, утечек токенов, обхода прав, исполнения чужого кода | provable | `TestQualifiedReuse` (0 вызовов на reuse), `test_module_never_executes_downloaded_code` (AST), `test_payload_never_contains_tokens_or_raw_urls`, `test_credentialed_url...` |
| L02230 (ER-50) | `EVOL-SRC-*`: discovery → verified code fetch с ref/commit/line range | provable (в части инструмента) | весь набор выше |
| L02360 (ER-S03) | «найди файл/реализацию» без URL → Source Reader находит сам | provable (в части инструмента) | discovery без ссылки; маршрутизация — L1 |
| L02401 (ER-S35) | исходный код из файла пользователя — локально, внешняя техника отдельно | не входит в рамку слайса (локальный файл) | — |

Граница честности: строки, где я пишу «в части инструмента/не менялось этим
слайсом», не доказывают поведение **LLM** (что модель не соврёт и не выдумает
дату). Слайс доказывает, что у неё нет для этого инструментального источника
(в payload нет цитат/хронологии), а `verified` нельзя получить без байт.
Формулировки Writer — отдельный слой, в этом слайсе не менялся.

## 6. Что добавил бы живой прогон (границы доказательства)

Обязательных живых вызовов нет (`live_required=false`, `live_when=preprod`).
Живой GitHub дал бы только:

1. **реальную квоту** — 60 запросов/час на IP без токена и фактическое поведение
   `x-ratelimit-remaining`/`retry-after`; анонимный бюджет одного исследования
   (commits+tree+contents ≈ 3–5 вызовов) сейчас подтверждён только моделью;
2. **поведение `raw.githubusercontent.com`** для приватных/удалённых файлов
   (404 без деталей) и то, что raw **не** расходует REST-квоту (риск R2);
3. **secondary rate limit** (403 без `retry-after`) — по контракту отдаём
   `rate_limit` без ретраев, эмпирически не подтверждено;
4. **дерево >100 000 записей / 7 МБ** (`truncated=true`) — код честно ставит
   `not_checked.reason="tree_truncated"`, реальный масштабный репозиторий не
   прогонялся;
5. **приватные репозитории с токеном** — `scope="chat"` и `auth_failed` при
   отказе проверены только на фикстурах;
6. **слэш-ветки** в реальном репозитории (перебор кандидатов) — проверено на
   фикстуре `feature/x`.

Ни один из этих пунктов не является гейтом приёмки §1.5; все они — риски
эксплуатации, а не непроверенная логика.

## 7. ER-65 snapshot перегенерирован (pinned sources изменились)

`tools/er65_prompt_segment_snapshot.py --check` до правки: FAIL (в базе `5fc2ded5`
— OK). Причина ровно одна: канон инструментов и хеши закреплённых источников.

- изменены записи `/sources`: `services/direct_chat_service.py` (строка
  `_EVIDENCE_CAP_REGISTRY`), `services/tool_loop.py` (METERED_*),
  `services/tool_schemas.py` (схема/канон — входит в тот же блок sources);
- изменён блок `tools` в 4 стадиях из 27: `direct.tool_phase.model_driven`
  (`prod_on` и `factory_off`) и `direct.tool_phase.tool_round` (оба режима):
  `count 15→16`, `names +read_source_code`, `schemas_sha256` новый;
- **тексты сообщений не изменились** (0 расхождений в `stages[].messages`,
  `summary.all_expected_prompt_keys_found = True`): промпт-канон байт-в-байт;
- после регенерации `--check` → `OK: снимок воспроизводится байт-в-байт
  (stages=27, segments=58, two isolated processes identical)`.

## 8. Инцидентальные находки

- **Предсуществующие падения (не мои)**: 55 тестов на базе `5fc2ded5` падают и
  до правки (webapp/UI, summary-волны, `test_104_backend_additions` с
  `toggleModule` в `web/index.html`, `test_mca11_money_limits`
  `no_runtime_callers_off_parity`, `test_mca23` routes-sha freeze и др.).
  Полный прогон на ветке даёт тот же класс падений; после фикса пин-тестов
  разница с базой — 0 по множеству файлов.
- **Порядко-зависимые тесты**: `test_dream_belief_bot_provenance::
  test_no_bot_sources_outcome_unchanged` и `test_factcheck_fc_r1_fix::
  test_all_irrelevant_is_honest_failure` падают только в общем прогоне (реальный
  инициализ `duckduckgo_search`), изолированно — PASS на этой же ветке.
  Причина — состояние/порядок, не слайс.
- **Полный прогон перегенерировал** 51 файл `plans/features/evol/audit/evidence/**`
  (screenshots/JSON пишутся e2e-тестами). Вернул их байт-в-байт из HEAD; в
  рабочем дереве остались только файлы этого слайса.
- **`plans/current_task.md`** в этом worktree отсутствует (не отслеживается
  git); источник читал из основного репозитория, `current_task.md` не менял.

## 9. Рамка записи и файлы

Новые: `services/source_reader.py`, `tests/test_evol_source_reader.py`,
этот отчёт. Правки: `services/tool_schemas.py`, `config/settings.py`,
`services/tool_loop.py`, `services/tool_router.py`,
`services/capability_registry.py`, `services/direct_chat_service.py`,
`services/evidence_policy.py`, `plans/features/evol/evidence/er65/*`, пин-тесты
канона (16 файлов). Не тронуты: `services/prompt_*`, `services/chat_prompts.py`,
`web/**`, `services/safe_fetch.py`, `services/source_reuse.py`,
`services/mca_events.py`, `services/search_aggregator.py`,
`services/web_content_extractor.py`, `handlers/**`, `bot.py`.
Деплой не выполнялся; в Telegram ничего не отправлялось.
