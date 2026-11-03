# AC-DATA — независимое ревью (Reviewer)

- Кандидат: `4e470cf74636a71e4debf9041c0c7a078fcbd8d1` (ветка `feat/ac-data-sources`), база `a9f326f8` (предок подтверждён).
- Пакет: AC-DATA — реестр источников, честные статусы/ревизии/свежесть, LKG, четыре вида здоровья.
- Источники требований: `plans/owner_inputs/2026-11-02-anticliche-memory-admin-ux-spec.md` §2.1/§2.2/§3.1/§3.2/§8.3, `arch/integration-decisions.md` §1/§7, карта `requirements-map.json` (38 строк `items` + 14 строк `additional_requirements` со `slice=AC-DATA`).
- Отчёт Builder: `reports/w-ac-data.md` (прочитан целиком, проверялся независимо).
- Дата ревью: 03.11.2026.

## Вердикт

**Needs Fixes** — два блокера уровня данных (не косметика), оба с узкой правкой; остальное поведение пакета подтверждено.

- B1: ложные «версия 0» / «0 правил» в ранних выходах `_refresh_impl`. Владелец: Builder. Требование: AC-INV-08.
- B2: событие проверки источника не фиксирует source_id/http/revision/unchanged/duration. Владелец: Builder. Требование: AC-EVENT-SOURCE-CHECKED (M071), §2.1/§4.4.

## Что проверено лично (не по отчёту Builder)

**Реализация (читал код, не отчёт):** `services/anticliche_sources.py` целиком (2181 стр.), `services/anticliche_cache.py::read_active_version`, диф `services/anticliche_worker.py`, DDL двух таблиц в `services/pg_db.py`, `web/api/anticliche.py` (3 read-endpoint), сверка таксономии/подписей §3.2 с `STATUS_LABELS`, сверка полей события с `mca_events.build_event`/`ALLOWED_FIELDS`/`REASON_CODES`.

**Тесты (читал тела и утверждения):** `tests/test_anticliche_sources_ac_data.py` — 62 теста, утверждения проверяют наблюдаемый результат (статусы, `next_attempt_at`, `docs_parsed`, версия/набор в кэше, состояние источника, тела ответов API), а не внутренние вызовы; сеть не используется (транспорт инъектируется); негативные кейсы есть (403 без признака политики, HTML вместо Markdown, невалидный JSON, PG down, все источники упали). Адаптация старых тестов (`test_anticliche_round1023.py`, `...semantics_round1025.py`, `...hotfix3...`) контракт не ослабляет: фикстуры приведены к настоящей форме ответа Wikipedia API, id `manual` заменён на `local/manual`, агрегат `fetch_error` заменён на `sources_unavailable`, добавлено усиливающее утверждение `result["version"] == 1`.

**Прогоны:**
- `pytest tests/test_anticliche_sources_ac_data.py -q` — **62 passed**.
- Затронутые области (`test_anticliche_*`, `test_pg_db.py`, `test_budget_*_round1024.py`, `test_round1025_f8_registry.py`, `test_external_log_round1024.py`) — **349 passed**, 0 failed.

**Мутации (сделал сам, откат через `git checkout`, дерево после — чистое):**

- 403 превращён в `policy_blocked` по одному коду — падают `test_transport_classification[403...auth_failed]`, `test_single_403_is_not_policy_block`.
- игнор `Retry-After` — падают `test_retry_after_capped_by_policy`, `test_rate_limited_check_schedules_retry_after`.
- `policy_blocked` с автоматическим cooldown — падают `test_policy_block_has_no_automatic_retry`, `test_policy_blocked_check_schedules_nothing`.
- убран LKG-фолбэк на `anticliche_cache` — падает `test_unreadable_snapshot_falls_back_to_cache_with_version`.
- убран union по lineage — падает `test_lineage_shared_upstream_is_one_confirmation`.
- виды здоровья сведены (reachability := content) — падают `test_analysis_independent_from_reachability`, `test_health_endpoint_returns_four_kinds`.

**Собственные контрпримеры (не из набора Builder):**
- P1: банк v9 с 1 правилом + `DYNAMIC_ANTICLICHE_ENABLED=false` — `refresh(force=True)` возвращает `status=disabled, version=0, rules=null` (эндпоинт отдаст `version=0, rules=0`), при этом банк цел.
- P4: банк v9 с 1 правилом + свежий `fetched_at` — `refresh(force=False)` возвращает `status=fresh, version=9` без ключа `rules`, эндпоинт отдаёт `rules=0`.
- P3 (обратное направление §2.2): источники зелёные + пустой банк — `reachability=ok`, `content=ready`, `runtime=no_published_rules`; независимость видов подтверждена и в эту сторону.
- P2: все источники «зелёные», но проверены 30 дней назад — `summary.stale=4`, при этом агрегат `reachability=ok` (см. N1).
- Событие проверки: собрал реальное событие через `emit_check_event` — в нём нет `source_id`, `http_code`, `revision`, `unchanged`, `docs`, `bytes`, `duration_ms` (см. B2).

## Живые сетевые факты — что воспроизвёл сам

Прогон реальным адаптером (`check_source(..., manual=True)`, честный `User-Agent: adminbot-anticliche/1.0`, без записи в PG), 03.11.2026, машина разработчика:

- `wikipedia`: `policy_blocked`, HTTP 403, тело «Please respect our robot policy https://w.wiki/4wJS when crawling us. Contact bot-traffic@wikimedia.org...», `next_attempt_at=null`, `paused_reason=policy_blocked`.
- `ru-repo-a`: `available`, HTTP 200, ревизия `324b1555...`, 6/6 документов разобрано, `licence_spdx=NOASSERTION` (как и описано в отчёте).
- `ru-repo-b`: `available`, HTTP 200, ревизия `17e91018...`, 1/1 документ, `licence_spdx=MIT`.
- `ru-repo-c`: `available`, HTTP 200, ревизия `35ad747a...`, 3/3 документа, `licence_spdx=MIT`.

Дополнительно скачал `LICENSE` каждого репозитория: у всех трёх текст MIT («Permission is hereby granted...»). Заголовки: `tsalkin/russian-humanizer` — «MIT License / Copyright (c) 2026 Russian Humanizer contributors / Adapted in structure from blader/humanizer (MIT)...» (lineage-запись в реестре подтверждается самим документом), `miolamio/agent-skills` — «Copyright (c) 2026 Anthony Vdovitchenko», `Vladimir-Human/humanizer-ru` — «Copyright (c) 2026 Vladimir».

**Итог по живым утверждениям:** воспроизведено полностью — 403 robot-policy у Wikipedia, `available` с реальными ревизиями у трёх репозиториев, MIT по факту чтения LICENSE. Не воспроизводилось: поведение с IP прод-сервера (по определению иное) и полный LLM-анализ (это AC-PIPE). Цифра «26 530 chars» для `ru-repo-a` из отчёта не воспроизводится: сейчас **23 969** символов (b — 12 058, c — 26 824 совпали); похоже, в отчёте для A указаны байты. На код не влияет (N4).

## Пункты делегирования

1. **Реестр §3.1 — PROVEN.** Все 9 id стабильны и совпадают с §3.1 (`test_registry_ids_are_stable`); реальные пути трёх репозиториев проверены живым запросом (6/6, 1/1, 3/3 документов); `local/manual` без URL и HTTP; `wikipedia` — `wiki_api`; четыре `bib-*` — `auto_check=False`, `counts_as_live=False`, `permits_analysis=False`, транспорт не вызывается (`test_bibliography_is_never_fetched`), знаменатели `live_http=4 / local=1 / references=4` (`test_denominators_exclude_local_and_bibliography`). Лицензия/атрибуция записаны; MIT подтверждён мной по LICENSE на ревизии.
2. **Таксономия §3.2 — PROVEN, кроме ложных нулей в счётчиках ответа refresh (B1).** 403 без положительного признака политики даёт `auth_failed` (тест + мутация); `policy_blocked` не ретраится автоматически (`next_attempt_at=None`, `attempt_decision` всегда `allowed=False`; живой ответ Wikipedia это подтверждает); 429 уважает `Retry-After` с потолком, без заголовка — bounded backoff с jitter; 5xx/timeout — тот же bounded backoff; `local/manual` не имеет HTTP-статуса (`transport_code=local`, `http_status=None`, сбой только `db_error`); `stale` — отдельная пометка `reachability.freshness`, транспортный статус она не заменяет.
3. **Независимость — PROVEN.** Wikipedia 403 не влияет на другие источники (`test_wiki_policy_block_does_not_affect_others`); исключение транспорта изолировано (`check_source` не бросает, `check_sources` дополнительно ловит через `gather(return_exceptions=True)`); независимые `check_id`; worker публикует по здоровому источнику со `partial_success` (`test_partial_success_publishes_from_healthy_source`). Lineage: `independent_confirmations(['ru-repo-a','wikipedia']) == 1`, неподтверждённое происхождение видно в `unverified_lineage`.
4. **Хранилище — PROVEN.** Ровно две таблицы по решению Architect (`anticliche_source_state` = последняя реальная проверка + `enabled`; `anticliche_snapshot` = immutable версии), DDL идемпотентный; история — существующий `mca_events` (`component=anticliche`, `stage=source_check`, `operation_id=check_id`, исходы `success/skipped/failed` входят в терминальные, значит durable-путь включён). LKG: `ok`/`lkg`/`none`/`unavailable`, при недоступном PG `version=None`, `rules=None` — не 0 (`test_pg_down_is_unavailable_not_zero`); действующий набор в `/sources` не отдаётся как «0 правил» (P1/P4: `/sources` показывает v9/1). **Не proven в части счётчиков ответа refresh — B1.**
5. **Четыре вида здоровья — PROVEN.** `build_health` отдаёт ровно `reachability/content/analysis/runtime`; «все источники красные + runtime работает» (`test_kinds_are_separate_fields`) и обратное «источники зелёные + `no_published_rules`» (мой P3) — оба состояния воспроизведены; `works_previous_version`, `compiler_error`, `unavailable` — отдельные состояния; `analysis` берётся только из `last_analysis_status`, не из доступности источника.
6. **Read API — PROVEN.** `GET /api/anticliche/sources`, `/sources/{id}` (404 на неизвестный), `/health` — под тем же `_require_global_admin` (`roles_srv.access_for` проверяет `is_global_admin`), что и legacy-эндпоинты; секретов нет (id/коды/числа/лицензии/URL, без тел документов и ключей); знаменатели честные; `analysis`-поля `None` вместо выдуманных нулей; пагинации нет осознанно (9 источников).
7. **Живое утверждение — воспроизведено мной** (раздел выше). Ограничение: проверка с машины разработчика, IP прод-сервера другой; статус — результат последней реальной проверки на конкретном хосте.

## Блокеры

### B1. BLOCKER (Builder, AC-INV-08): ответ refresh показывает «версия 0» / «0 правил» при существующем наборе

- Где: `services/anticliche_worker.py:604-605` (ветка `disabled`) и `:618-619` (ветка `fresh`) — единственные два выхода, которые не собираются из `base` с реальными `version`/`rules`.
- Наблюдение: банк v9 с 1 правилом, AntiCliche выключен — `refresh(force=True)` даёт `version=0, rules=null`, `/api/anticliche/refresh` (`int(... or 0)`) отдаёт `version=0, rules=0`. Свежий `fetched_at` — `status=fresh, version=9`, ключа `rules` нет, эндпоинт отдаёт `rules=0`.
- Влияние: ровно тот ложный «0 правил / версия 0», который запрещён §1 п.8. Ветка `disabled` достижима через API (kill-switch), ветка `fresh` — на каждом тике планировщика; AC-API/AC-UI будут строиться на этом контракте (в отчёте Builder заявлено «version теперь реальная действующая» — на этих двух ветвях это неверно).
- Минимальная коррекция: вычислить `pg`, `stored`, `current_version`, `current_rules` до обоих гейтов (или взять `anticliche_cache.read_active_version(pg)`) и возвращать `{**base, "status": ...}`; добавить 2 теста: «disabled + существующий банк — version/rules не нули» и «fresh-skip + существующий банк — rules не 0».
- Перепроверка: `pytest tests/test_anticliche_sources_ac_data.py -q` с новыми утверждениями + мой P1/P4-сценарий.

### B2. BLOCKER (Builder, AC-EVENT-SOURCE-CHECKED/M071): событие проверки не идентифицирует источник и не несёт деталей probe

- Где: `services/anticliche_sources.py:1606-1651` (`emit_check_event`).
- Наблюдение (реальное событие через `emit_mca_event`): `{component, stage, status, operation_id, attempt, reason_code}` — нет `source_id`, `http_code`, `revision`, `unchanged`, `docs`, `bytes`; `duration_ms` не появляется никогда, потому что `_base_check` не заводит длительность. Второй вызов `emit_agentic_event("ANTI_CLICHE_SOURCE_CHECK", ...)` — тихий no-op: такого типа нет в `AGENTIC_EVENT_TYPES`, а его поля `http/docs/failures` не входят в whitelist.
- Влияние: по сохранённым данным нельзя ответить «какой источник, что отдал, какая ревизия»; вкладки «Журнал»/«Анализ» (инвариант §1 п.7, пошаговая история фактического чтения документов) не собираются из PG. Последняя проверка полная (в `anticliche_source_state`), истории деталей нет.
- Минимальная коррекция: замерять `duration_ms` в `check_source`/`check_sources`; в `emit_check_event` передавать `entity_id=check["source_id"]`, `trace_id` (параметр; AC-PIPE пробрасывает id прогона), `duration_ms` и `source_ref_json={"source_id","http","revision","changed","docs","bytes","transport"}`; лишний agentic-вызов либо зарегистрировать в enum с полями, либо убрать.
- Проверено, что правка проходит санитайзер: `build_event(..., entity_id="ru-repo-b", trace_id="run-42", source_ref_json={...})` сохраняет все поля.
- Перепроверка: тест «событие проверки содержит source_id/http/revision/changed/duration» + пробник события.

## Неблокирующие наблюдения (в бэклог, без расширения пакета)

- **N1.** Все источники «зелёные», но проверены 30 дней назад — `reachability.status=ok` при `summary.stale=4`. Обязанность AC-UI: рисовать «Данные устарели / Последняя проверка N дней назад» из `freshness`/`summary.stale` и не закрашивать агрегат зелёным. Дешёвое улучшение: отдать `stale` внутри `reachability_health`.
- **N2.** Административно выключенный источник в агрегате `reachability` попадает в `unchecked`, хотя `summarize` различает `disabled`. Косметика; строка источника показывает `disabled` верно.
- **N3.** `attribution` у `ru-repo-b/c` — метка репозитория, а не строка копирайта из LICENSE. Для MIT-атрибуции стоит подставить правообладателя (одна строка в реестре).
- **N4.** В отчёте `w-ac-data.md` §6 для `ru-repo-a` указано «26 530 chars», фактически 23 969 (b/c совпали). Поправить цифру.
- **N5.** Нет явного теста «не-админ получает 403» на трёх новых GET. Гард тот же, что у проверенных legacy-эндпоинтов, поэтому RBAC-паритет держится, но тест стоит добавить в AC-API.
- **N6.** `T-SRC-CONCURRENCY` (cron + manual не создают конкурирующих публикаций) — **UNVERIFIED**: в `refresh` нет single-flight-замка (есть только `max_instances=1` у APScheduler, что не покрывает manual+cron), теста нет. Естественный владелец — AC-API (мутации/single-flight); строку карты нужно либо перенести туда, либо закрыть замком и тестом. Дублирование правил при этом исключено (дедуп по фразе в `_normalize_stored`), теряется только вклад одного из прогонов.
- **N7.** `T-SRC-UNCHANGED` в части «0 новых LLM-вызовов и неизменная версия» — proven (`test_unchanged_revision_keeps_version`); часть «changed без approved delta даёт `no_change`» относится к AC-PIPE.

## Что AC-PIPE должен использовать как есть (не дублировать)

1. Реестр и статусы: `anticliche_sources.SOURCES/all_sources/get_source/state_enabled`, `check_source`/`check_sources`, `record_check`, `emit_check_event`. Свой реестр, свой HTTP-клиент и свой User-Agent не заводить (`fetch_document` — единственный транспорт).
2. Тексты документов: `fetch_source_documents(source, revision=...)` даёт `{text, documents[], documents_parsed, bytes, chars, content_status}`. Разбор «пример клише != пояснение», категории и карантин — на стороне AC-PIPE.
3. После активации `ru-repo-*` писать фактическое число разобранных документов в `docs_parsed`, иначе `content_health` останется `partial`/`failed`.
4. Готовность анализа: писать `last_analysis_status` / `last_success_analysis_at` в `anticliche_source_state` (колонки уже есть) — только оттуда берётся `analysis`-вид здоровья. Не выводить «анализ завершён» из reachability.
5. Публикация: одна транзакция `INSERT anticliche_snapshot(state='published')` + upsert `anticliche_cache`; таблицы уже созданы (`pg_db.py` — сериализованный файл, AC-PIPE пишет строки, а не DDL). После этого `read_active_version` даёт `ok`.
6. Run-события: `trace_id=run_id` для проверок и стадий (сейчас у проверок его нет — часть B2).
7. Считать здоровье только через `build_views/summarize/build_health/analysis_readiness`, LKG — только через `anticliche_cache.read_active_version`. Retry/cooldown — только `attempt_decision`/`compute_next_attempt`; второй политики не нужно.
8. Read API `/api/anticliche/sources`, `/sources/{id}`, `/health` уже есть; AC-API добавляет только мутации. Новые статусы `partial_success`/`unchanged`/`sources_unavailable` уже в `anticliche_cache.ALLOWED_STATUSES`; legacy-блок в `web/app.js` покажет их сырым кодом (`map[st]` или сам код) — это долг AC-UI (блок по §5.1 удаляется).
9. `ru-repo-*` выключены по умолчанию осознанно (до детерминированного разбора); включать их — обычный per-source флаг после Stage B, не новая канарейка.

## Состояние карты и гейта

`requirements_gate.py check --stage review --slice AC-DATA --candidate 4e470cf7...` — **FAIL**: 53 ошибки, все строки AC-DATA в статусе `PENDING` (52 релевантные строки: 38 `items` + 14 `additional_requirements`), `slice_candidate_pins` содержит только AC-P0 (`acb8cfe4`). Это учётная часть: после исправления B1/B2 PM привязывает строки AC-DATA к кандидату и вносит evidence. Сейчас `APPROVED_BEHAVIOR` не выставляется: есть FAILED-строки (AC-INV-08, AC-EVENT-SOURCE-CHECKED) и одна UNVERIFIED (T-SRC-CONCURRENCY).

## Полный прогон и классификация предсуществующих падений

Полный набор на кандидате (мой собственный прогон): **75 failed, 17861 passed, 41 skipped, 23 errors, 1145.96 s** — в точности цифры из отчёта Builder (§10.1), значит они не выдуманы.

Классификация (не на словах): взял 98 упавших/ошибочных node id из кэша last-failed, откатил в рабочем дереве 13 файлов кандидата к базе `a9f326f8` (кроме `services/anticliche_sources.py` и нового теста — их в базе нет) и прогнал тот же список повторно: **48 failed / 31 passed / 19 errors** — те же числа, что и на кандидате, ни одного нового падения. Дополнительно проверил 6 представителей поимённо (`test_forbidden_paths_out_of_diff`, `test_version_and_catalog`, `test_counts_unchanged`, `test_forbidden_paths_out_of_diff_vs_baseline`, `test_grid`, `test_js_unit_round1021_ui_audit`) — все шесть падают и на базе.

Причина падений: это baseline-сторожа, которые сравнивают дерево с древним тегом `pre-round1026-a1` (в diff 7490 файлов, 29 web-путей прошлых выпущенных волн) и CSS/JS-ожидания, не относящиеся к AntiCliche. 31 из 98 id проходят при изолированном запуске — набор зависит от порядка (UI/E2E). Ни одно падение не относится к AC-DATA; рабочее дерево после эксперимента чистое, новый набор по-прежнему 62 passed.

## Ограничения ревью

- Падения вне затронутых областей — предсуществующие (см. раздел выше); в затронутых областях 349 passed / 0 failed.
- Живые проверки — с машины разработчика; IP прод-сервера даст другой результат проверки (штатно и задокументировано Builder).
- LLM-анализ, публикация snapshot, компилятор и UI в этот пакет не входят и здесь не проверялись.

---

# Re-review 2 (03.11.2026) - проверка исправления B1/B2

- Кандидат: `5e6fe90264e1859993d42d4ed7bb1342b47ac907` (ветка `feat/ac-data-sources`), предыдущий ревью-кандидат `4e470cf7`, общая база `a9f326f8`. Правка затрагивает `services/anticliche_sources.py`, `services/anticliche_worker.py`, `tests/test_anticliche_sources_ac_data.py` и отчёт Builder; `services/anticliche_cache.py`, `web/api/anticliche.py`, `services/pg_db.py` в этой правке не менялись.
- Читал сам (не по отчёту): новый `_refresh_impl` с гейтами и Stage A, `_base_check`/`_finish` (duration/manual), `emit_check_event` целиком, `check_source`/`check_sources`, `mca_events.build_event` + `ALLOWED_FIELDS`/`_CODE_FIELDS`/`_JSON_FIELDS`/`REASON_CODES`, `agentic_events._safe_value`/`_IDENT_RE`, DDL `mca_events` в `services/database.py`, все 4 новых теста целиком.

## B1 - закрыт (VERIFIED)

Свой сценарий, не из набора Builder: банк **v12 с 3 правилами**, одна строка `anticliche_cache`.

| Гейт | Наблюдаемый результат (мой прогон) |
| --- | --- |
| kill-switch OFF (`DYNAMIC_ANTICLICHE_ENABLED=false`), `refresh(force=True)` | `status=disabled, version=12, rules=3, count=0`; транспорт - 0 вызовов; LLM - 0 вызовов; `cache_row` до/после совпадает полностью |
| freshness-skip (`force=False`, `fetched_at` вчера) | `status=fresh, version=12, rules=3, count=0`; транспорт 0, LLM 0; `cache_row` не изменён |

Проверил и настоящую пользовательскую поверхность: `POST /api/anticliche/refresh` (реальный роутер, `TestClient`, global-admin) при выключенном AntiCliche отдаёт `{"status":"disabled","count":0,"version":12,"rules":3}` - прежних `version=0, rules=0` нет.

`count=0` на гейтах не ложный ноль: в этом контракте `count` = число НОВЫХ правил текущего прогона (ср. `return {**base, "status": status, "count": new_total, ...}`), на гейте публикации не было.

## B2 - закрыт (VERIFIED)

Своё событие: реальная проверка, затем `emit_check_event`, затем `mca_events.flush_events` в штатный `DatabaseService` (SQLite), затем SELECT из `mca_events`. Четыре кейса (успех, 403 robot-policy, `local/manual`, wikipedia с ревизией).

Сохранённая строка успешной проверки (как есть из БД): `event_name=anticliche_source_checked`, `outcome=success`, `level=INFO`, `component=anticliche`, `stage=source_check`, `status=available`, `operation_id=<check_id>`, `attempt=1`, `trace_id=run-77`, `duration_ms=47`, `entity_ids=["test-a"]`, `source_ref_json={source_id: "test-a", transport: "http", http: 200, revision: "", changed: true, unchanged: false, content_status: "parsed", docs_fetched: 1, docs_parsed: 1, bytes: 115, chars: 62, error_code: "", manual: false}`.

Остальные кейсы:
- 403 robot-policy: `outcome=failed`, `level=WARN`, `status=policy_blocked`, `reason_code=cooldown` (прошёл whitelist), в `source_ref_json`: `http=403`, `error_code=policy_blocked`, `docs_parsed=0`.
- `wikipedia`: `source_ref_json.revision=b4fcf24c…` (40-hex не маскируется санитайзером), `entity_ids=["wikipedia"]`.
- `local/manual` (слэш в id): `entity_ids=["local/manual"]`, `source_ref_json.source_id="local/manual"`, `http=null`, `transport=local`, `manual=true`.

`trace_id` не выдумывается: без параметра колонка NULL. `duration_ms` измеренный (`time.monotonic`): на мгновенном синтетическом транспорте honest `0`, на задержке 20 мс -> 47.
Тихий no-op убран по-настоящему: `emit_agentic_event("ANTI_CLICHE_SOURCE_CHECK")` в дереве отсутствует (grep по репозиторию - только упоминания в отчётах), второго канала эмиссии нет, потребителей этого agentic-типа нет.

Замечание (не блокер): `entity_id` принимается `build_event`, но колонки `entity_id` в `mca_events` нет - в БД это поле теряется (остаётся в лог-строке). Корреляция в хранилище идёт через `entity_ids` и `source_ref_json.source_id`; оба работают, включая `local/manual`.

## Регрессии - не обнаружены

Прогнал сам (не по отчёту):

- `tests/test_anticliche_sources_ac_data.py` - **66 passed** (повторно после отката всех моих мутаций; `git status` по `services/`, `tests/`, `web/` чистый).
- Набор затронутых модулей (12 файлов: anticliche x5, `test_pg_db`, budget x4, `test_round1025_f8_registry`, `test_external_log_round1024`) - **361 passed, 0 failed**.
- Контракт событий/воркеров: `test_agentic_events_round1026` + `test_mca13_event_contract_round1027` + `test_mca17a_observability_core_round1027` + AC-DATA - **212 passed, 1 failed** (`test_registry_event_names_exist_in_code`).
- `test_mca17_sleep_memory_workers_round1050` + `test_mca01_tx_task_supervisor_round1027` + `test_add_exp_expression` + `test_soul1_style_policy` - **173 passed, 1 failed** (`test_write_points_go_through_single_writer`).

Точечно перепроверил ранее подтверждённое (тесты в этих же прогонах): реестр 9 стабильных id, таксономия §3.2 (`policy_blocked` без авторетрая, `Retry-After` с потолком), независимость источников и lineage, две таблицы + журнал, LKG (`ok`/`lkg`/`none`/`unavailable`), четыре вида здоровья.

**Read API RBAC теперь доказан живым вызовом** (закрывает прежнее N5): не-админ получает **403** на всех трёх `GET /api/anticliche/{sources, sources/{id}, health}`, глобальный админ - **200**. Проверено на том же ASGI-приложении, но с не-админским набором ролей.

## Два предсуществующих падения - воспроизведены на базе `4e470cf7`

Отдельный чистый checkout базы (`git worktree`, detached `4e470cf7`), те же два теста: **2 failed**, те же числа - `database.py 217 vs 207`, `prompt_release_policy.py`, `direct.reply: вымышленные события {'mca07_answer_cache'}`. Файлы `services/database.py`, `services/mca_process_registry.py`, `services/prompt_release_policy.py` отсутствуют в диффе ветки (`git diff --name-only a9f326f8 5e6fe902`). Вывод: предсуществующие, к AC-DATA и к правке B1/B2 отношения не имеют.

## Репродукция мутаций Builder (сделал сам)

| Мутация (откат через `git checkout --` + проверка `git status`) | Результат |
| --- | --- |
| disabled-ветка возвращает `version=0, rules=0` | RED: `TestRefreshGatesReportRealBank::test_disabled_kill_switch_reports_real_bank` - `assert 0 == 9` |
| fresh-ветка возвращает `{version, source}` без `rules` | RED: `test_fresh_skip_reports_real_rule_count` - `KeyError: 'rules'` |
| `emit_check_event` без `source_ref_json`/`entity_ids`/`entity_id` | RED: оба теста `TestCheckEventHistory` (`TypeError: the JSON object must be ... not NoneType`) |

Заявления Builder о мутациях подтверждены: тесты ловят именно эти дефекты, а не текущую реализацию. После отката набор снова 66 passed.

## Блокер, оставшийся с прошлого ревью: T-SRC-CONCURRENCY - подтверждён FAILED

- Требование владельца: `plans/owner_inputs/2026-11-02-anticliche-memory-admin-ux-spec.md`, строка 659, п.20 списка проверок: «Одновременно cron+manual не создают две конкурентные публикации/дубли правил». В карте - `T-SRC-CONCURRENCY`, `slice=AC-DATA`, `status=PENDING`.
- Где: `services/anticliche_worker.py::refresh/_refresh_impl` - single-flight нет; на каждом вызове читается `stored`, позже вызывается `anticliche_cache.write_patterns` (полная перезапись списка, version+1).
- Мой воспроизводящий прогон (два одновременных `refresh(force=True)` на одном воркере, медленный LLM, пустой банк): `run1 -> ok, count=1, version=1`; `run2 -> ok, count=1, version=2`; итог `final_version=2`, в банке **одно** правило (второго прогона), правило первого прогона потеряно.
- Дублей при этом нет (дедуп по фразе работает), но «две конкурентные публикации» есть, и вклад одного прогона молча пропадает.
- Достижимость в проде: кнопка обновления (`POST /api/anticliche/refresh`) во время недельного тика планировщика; окно гонки - секунды-минуты (сеть + LLM).
- Минимальная коррекция (проектный паттерн уже есть в `dream_worker`/`nostalgia_worker`/`lore_worker`): сериализовать публикацию одним `asyncio.Lock` в `refresh` (для multi-process - `pg_try_advisory_lock`); второй вызов ждёт либо отвечает честным `busy` со **реальным** банком (`**bank`, не нулями). Тест: два одновременных `refresh` -> ни одно правило не потеряно, дублей нет, публикации не налагаются.
- Почему это не учётная механика: требование проверяемое и в текущем коде **не выполняется**; строка не может остаться `PENDING` без замка и теста. Если пакет решает, что владелец строки - AC-API, это отдельное решение PM/Architect со ссылкой, а не молчаливый перенос.

## Прочие наблюдения (не блокеры, в бэклог)

- **N8.** Гейты читают материализованную строку `anticliche_cache`, а не `read_active_version` (снимок - авторитет). Состояние «есть published snapshot, строки кэша нет» сегодня недостижимо (писателя `anticliche_snapshot` в ветке нет), но при нём гейт отдаёт `version=0, rules=0`, а `/sources` - `active_version 18/42` (проверено пробником). Контракт для AC-PIPE уже записан (публикация snapshot + upsert кэша в одной транзакции) - его надо соблюсти, иначе вернётся тот же ложный ноль.
- **N9.** В автоматическом пути (`_refresh_impl -> check_sources`) `trace_id` не передаётся, поэтому у событий cron-проверок `trace_id` NULL. Это честно (не выдумывается), но связать историю с прогоном сможет только AC-PIPE, передав `run_id`.
- **N10.** При полностью недоступном PG гейты отдают `0` (fail-open `fetch_cache`). Это прежнее поведение всего refresh-контракта и задокументировано; честное «неизвестно» даёт read API через `read_active_version -> unavailable`.

## Сводка приёмки на кандидате `5e6fe902`

- VERIFIED: B1 (AC-INV-08 на обоих гейтах, включая реальный `POST /refresh`), B2 (AC-EVENT-SOURCE-CHECKED/M071, сохранённое событие), реестр §3.1, таксономия §3.2 (`policy_blocked` без авторетрая, `Retry-After`), независимость и lineage, две таблицы + журнал, LKG, четыре вида здоровья, read API RBAC (доказан вызовом), классификация предсуществующих падений.
- FAILED: T-SRC-CONCURRENCY (воспроизведено, см. выше).
- UNVERIFIED: новых нет.

## Вердикт Re-review 2

**Needs Fixes** - но только по одной строке: B1 и B2 **закрыты**, регрессий нет, поведение правки безопасно.

- По поведению ветку можно интегрировать: правка не несёт чужих изменений, не добавляет sqlite write-точек (числа аудита те же, что на базе), не меняет DDL и read API.
- Пакет AC-DATA **не закрывается**: остаётся воспроизведённое обязательное требование владельца T-SRC-CONCURRENCY. Владелец - Builder (замок + тест) либо PM/Architect с явным переносом строки в AC-API и обоснованием.
- Учётная часть: `requirements_gate.py check --stage review --slice AC-DATA --candidate 5e6fe902...` падает (все строки `PENDING`, `candidate_commit` в карте - старый). Это работа PM после закрытия блокера: привязать строки и evidence к `5e6fe902`.
- Перепроверка после правки: тот же двойной `refresh` (правило первого прогона не теряется, дублей нет), `tests/test_anticliche_sources_ac_data.py`, и прогон набора затронутых модулей (361) для контроля регрессий.

---

# Re-review 3 (03.11.2026) - проверка T-SRC-CONCURRENCY (single-flight публикации)

- Кандидат: `ff0a7994` (ветка `feat/ac-data-sources`), предыдущий ревью-кандидат `5e6fe902`, общая база `a9f326f8`. Диф правки: `services/anticliche_worker.py` (73 добавлено / 8 удалено), `tests/test_anticliche_sources_ac_data.py` (141 добавлено), отчёт Builder `w-ac-data-concurrency.md`. `anticliche_cache.py`, `anticliche_sources.py`, `web/api/anticliche.py`, `services/pg_db.py` в этой правке не менялись (`git diff --name-only 5e6fe902 ff0a7994`).
- Читал сам, не по отчёту: `refresh`, `_refresh_cycle`, `_busy_result`, `_bank_from_stored`, `_ANTICLICHE_TERMINAL`, `_refresh_level`, `tick`, весь `_refresh_impl` (единственный `write_patterns` - в самом конце, `stored` читается до гейтов), endpoint `POST /api/anticliche/refresh`, реальные замки `dream_worker`/`nostalgia_worker`, `REASON_CODES` в `services/mca_events.py`, запуск воркера и веб-сервера в `bot.py`.

## 1. Реализация - VERIFIED

- Один `asyncio.Lock` (`_run_lock`) в `__init__`. `refresh`: `if self._run_lock.locked(): return await self._busy_result(...)`, иначе `async with self._run_lock: return await self._refresh_cycle(...)`.
- Между проверкой `locked()` и захватом нет `await`: при свободном замке `Lock.acquire()` возвращает управление без переключения event-loop, поэтому окно "проверил - потерял" в одном цикле недостижимо. Это не только комментарий: мой забег (п.2) и мутация (п.4) ведут себя ровно так.
- Паттерн совпадает с проектным: `dream_worker.run_once/tick` (`services/dream_worker.py:690-693`, `:743-747`) и `nostalgia_worker` (`:663-665`, `:679-681`) - отказ, а не ожидание в очереди.
- `busy` зарегистрирован как штатный skip там, где это нужно существующему коду: `_ANTICLICHE_TERMINAL["busy"] = ("skipped", "queue_coalesced")` (код `queue_coalesced` реально есть в `REASON_CODES`, `services/mca_events.py:66`), `_refresh_level("busy") -> INFO`, `tick` относит `busy` к `skipped` с `reason=busy`. Записи в кэш нет: `_busy_result` делает только чтение `fetch_cache` и `trace_step`.
- Формула действующего банка вынесена в `_bank_from_stored` и используется и гейтами `_refresh_impl`, и `busy` - разойтись по нулям/не нулям они больше не могут.
- Механизм достаточен для этого деплоя: `bot.py` поднимает ОДИН `AntiClicheWorker` и `set_runtime_worker(...)` до старта uvicorn в том же event-loop (`bot.py:804-808`, `:1483-1494`). То есть cron-тик и HTTP-запрос обслуживает один и тот же объект в одном цикле; multi-process сценария (и необходимости `pg_try_advisory_lock`) здесь нет.

## 2. Мой собственный забег - гонка воспроизведена и закрыта

Сценарий не из набора Builder: банк v5 с ДВУМЯ правилами, один источник, транспорт отдаёт разный текст на каждую проверку, модель блокируется на первом вызове до сигнала.

| Шаг | Наблюдение (мой прогон) |
| --- | --- |
| прогон 1 ушёл в LLM, держит замок | - |
| вызов 2 во время прогона 1 | `status=busy, version=5, rules=2, count=0, published=False`; объект строки кэша ТОТ ЖЕ (записи не было); LLM 1 вызов, транспорт 1 вызов |
| после release | прогон 1: `status=ok, version=6, count=1`; в банке 3 правила без дублей: два старых целы, правило прогона 1 на месте |
| публикации | ровно одна (version 5 -> 6, а не 7) |
| замок после | `running is False`; третий `refresh` не `busy` |
| события | ровно 2: `anticliche_run/start` и терминал `success`; у `busy` своего события нет |

Дополнительный фальсификатор, которого не было в наборе Builder: исключение внутри `_refresh_impl`. `refresh` пробрасывает его, `async with` освобождает замок, `running is False`, следующий вызов не получает "вечный busy". Залипания в `busy` нет.

## 3. HTTP-поверхность - VERIFIED на настоящей гонке

Не "замок занят вручную", а реально идущий прогон: в отдельном потоке выполняется `refresh(force=True)` и висит в модели, в главном потоке - штатный `TestClient` и `POST /api/anticliche/refresh` (global-admin).

Наблюдение: **200**, тело `{status: busy, version: 5, rules: 2, count: 0, published: false, source: manual}`; на момент ответа банк v5 (эндпоинт не писал), поток прогона ещё жив; после завершения прогона - v6 и 3 правила, LLM 1 вызов, транспорт 1 вызов. Прежних ложных нулей и второго прогона нет.

## 4. Мутация - RED подтверждён (сделал сам)

Убрал guard (`refresh` = сразу `_refresh_cycle`), откат через `git checkout -- services/anticliche_worker.py`, дерево после чистое.

| Прогон | Результат |
| --- | --- |
| мой забег | прогон 1 `ok v7`, прогон 2 `ok v6`: ДВЕ публикации; итог v7 = два старых правила + правило прогона 1, правило прогона 2 молча потеряно; LLM 2, транспорт 2 (исходный дефект из Re-review 2 воспроизведён) |
| `TestRefreshSingleFlight` | RED |
| `TestRefreshEndpointBusy` | RED: эндпоинт запустил второй настоящий прогон (`fetch_error` вместо `busy`) |

Значит тесты ловят именно отсутствие замка, а не текущую реализацию. После отката набор снова зелёный.

## 5. B1/B2 не регрессировали (проверил заново своими числами)

- Банк v5, 2 правила: kill-switch OFF -> `status=disabled, version=5, rules=2`, транспорта нет; freshness-skip (`force=False`) -> `status=fresh, version=5, rules=2, count=0`.
- Событие проверки: реальный probe, `source_ref_json = {source_id: test-a, transport: http, http: 200, revision: "", changed: true, unchanged: false, content_status: parsed, docs_fetched: 1, docs_parsed: 1, bytes: 49, chars: 49, error_code: ""}`, `duration_ms >= 10`, `trace_id` проброшен.

## 6. Прогоны

- `tests/test_anticliche_sources_ac_data.py` - **68 passed** (было 66; два новых теста конкурентности входят).
- Затронутые области: 11 файлов - **355 passed**, плюс `test_hotfix3_anticliche_report_round1025.py` - **8 passed** = 363, **0 failed** (цифра отчёта Builder подтверждена).
- Контракт событий/воркеров (`test_agentic_events_round1026`, `test_mca13_event_contract_round1027`, `test_mca17a_observability_core_round1027`, `test_mca17_sleep_memory_workers_round1050`, `test_mca01_tx_task_supervisor_round1027`, AC-DATA) - **292 passed, 2 failed**: те же предсуществующие падения, что и в Re-review 2, с теми же числами - `test_registry_event_names_exist_in_code` (`direct.reply: вымышленные события {mca07_answer_cache}`) и `test_write_points_go_through_single_writer` (`database.py 217 vs 207`). Файлы `services/database.py` и `services/direct_chat_service.py` отсутствуют в диффе ветки (`git diff --name-only a9f326f8 ff0a7994`), к AC-DATA отношения не имеют.
- Правка не добавляет sqlite-точек записи, DDL и изменений read API: диф - только воркер, тест и отчёт.

## 7. Сводка Re-review 3

- VERIFIED: T-SRC-CONCURRENCY (single-flight, честный `busy` с реальным банком, настоящая HTTP-поверхность, ровно одна публикация, освобождение замка), регрессий B1/B2 нет.
- Ограничения (не блокеры, уже в бэклоге): **N11** - `apply_manual` (PUT) пишет банк без этого замка, правка правил во время прогона всё ещё может потеряться (вне строки T-SRC-CONCURRENCY, владелец AC-API); **N12** - legacy `web/app.js` покажет `busy` сырым кодом (AC-UI); **N13** - multi-process не покрыт, но в текущем одно-процессном деплое не требуется.
- Карта: все 52 строки `slice=AC-DATA` по-прежнему `PENDING`, `slice_candidate_pins` содержит только AC-P0; `requirements_gate.py check --stage review --slice AC-DATA --candidate ff0a7994` - FAIL (53 ошибки, все учетные). Это работа PM: привязать строки и evidence к `ff0a7994`.

## Вердикт Re-review 3

**Approved** по поведению кандидата `ff0a7994`. Требование владельца "одновременно cron и manual не создают две конкурентные публикации / дублей правил" выполняется и воспроизведено мной вживую, включая настоящий HTTP-вызов во время идущего прогона. AC-DATA можно объявлять завершённым по поведению и мёржить ветку; учётная привязка строк (52 PENDING) остаётся за PM и не является дефектом кода.