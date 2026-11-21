# P0-EMBED-503-FAILOVER - независимое ревью r1

- Задача: `p0-embed-503-failover`, ticket `P0-EMBED-503-FAILOVER` (queue 47, P0).
- База/деплой: `374dc60609986a9250170a34a48c93bf2ba85e29` / 2.58.228 (`release/mod-acl-m4b3-2.58.228`).
- Кандидат: `fix/embed-503-failover`; код `4ace0a3ae52c321edfd2ef425d933198b6d08377`; tip `d00a01b07eec2143f355dcba6067f92074e3d064` (код + evidence).
- Owner input: `plans/owner_inputs/2026-11-22-p0-embed-503-failover.md`, sha256 `d23bf6f96c69e8ddd1537a07f8f203fbf434b0022f693e5368a64c8731828f09`, раздел A / DoD A.
- Контракт/карта: `plans/features/p0-embed-503-failover/requirements-map.json`, `plan.md` (10 обязательных `req_id`), live evidence DevOps `evidence/live-route-2026-11-22.md/.json` (master `f2540ac60`).
- Дата ревью: 2026-11-22, локальное время 03:11 +12. Reviewer независимый; продукт/тесты/карта/очередь/деплой не менялись; этот файл - единственная запись.

## 1. Вердикт

**APPROVED_FOR_RELEASE_PREPARATION.** Дефект "5xx/timeout не исключает отказавшую ногу, все <=4 попытки уходят в primary"
закрыт в коде: per-operation исключение, failover на независимую ногу, короткая парковка в существующем
`credential_health`, bounded retry для single-leg, без второго breaker и без изменения `budget=4`. Identity-гейт
не ослаблен: fallback-вектор пишется только при `serviceable && compatible` от существующего
`resolve_index_compat`, иначе text-only + FTS; кэш под configured identity не загрязняется. Мои независимые прогоны:
RED на базе 6F/4P по правильным причинам, GREEN 585/0/0/0, 10/10 нового файла, 3 мутации убиты, отдельные probes
подтвердили повторную 503-парковку без бомбардировки, auth/quota-семантику и probe-recovery.

**DoD A закрыт не полностью и не объявляется VERIFIED.** Кодовая часть failover готова к деплою; живой failover,
фактический admission Google PCI, до/после backlog и recovery tick - только после деплоя. `apinet` не починен;
Google admission по-прежнему не доказан, поэтому продуктовое "векторная память восстановлена" не заявляется.

```json
{
  "artifact": "P0-EMBED-503-FAILOVER review r1",
  "task": "p0-embed-503-failover",
  "ticket": "P0-EMBED-503-FAILOVER",
  "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
  "base": "374dc60609986a9250170a34a48c93bf2ba85e29",
  "base_version": "2.58.228",
  "candidate_branch": "fix/embed-503-failover",
  "candidate_code": "4ace0a3ae52c321edfd2ef425d933198b6d08377",
  "candidate_tip": "d00a01b07eec2143f355dcba6067f92074e3d064",
  "owner_input_sha256": "d23bf6f96c69e8ddd1537a07f8f203fbf434b0022f693e5368a64c8731828f09",
  "product_scope": [
    "services/embedding_control_plane.py",
    "services/summary_memory.py",
    "tests/test_p0_embed_503_failover.py"
  ],
  "product_scope_only_3_files": true,
  "new_flags": 0,
  "new_endpoints": 0,
  "ddl": 0,
  "app_version_unchanged": true,
  "ui_unchanged": true,
  "config_handlers_web_model_indexes_settings_unchanged": true,
  "blocking_findings": 0,
  "nonblocking_findings": 2,
  "covered_rows": [
    {"id": "E503-FAILOVER-01", "status": "PASS_CODE_DEPLOY_PENDING"},
    {"id": "E503-AUTH-01", "status": "PASS"},
    {"id": "E503-IDENTITY-01", "status": "PASS_CODE_LIVE_ADMISSION_UNKNOWN"},
    {"id": "E503-RECOVERY-01", "status": "REVIEW_LIVE_BEFORE_AFTER_PENDING"},
    {"id": "E503-DIAG-01", "status": "PASS_CODE"},
    {"id": "E503-ACCEPT-MATRIX-01", "status": "REVIEW_LIVE_HALF_PENDING"},
    {"id": "E503-EXCLUSIONS-01", "status": "PASS_SCOPE_DEPLOY_PENDING"},
    {"id": "E503-ROUTE-01", "status": "EXTERNAL_EVIDENCE_f2540ac60_NOT_RERUN"},
    {"id": "E503-REPORT-01", "status": "PENDING_FINAL_REPORT"}
  ],
  "findings": [
    {
      "id": "E503-R1-N01",
      "scope": "BACKLOG_ONLY",
      "severity": "low",
      "blocking": false,
      "title": "Read/query path не проверяет route-совместимость фактически обслужившей fallback-ноги",
      "contract_refs": ["E503-IDENTITY-01 (write-centric wording)", "owner A.3"],
      "expected": "Для текущего P0 запись гейтится; при этом KNN-запрос не должен смешивать пространства, если fallback-нога имеет другой MSI.",
      "actual": "`vector_search`/`_knn_graph_facts` проверяют `_index_generation_ok` для configured identity и затем используют вектор любой обслужившей ноги (`summary_memory.py:4289-4297`, `6279-6291`). В текущей конфигурации active MSI `e540d4ad890e121d` совпадает с Google MSI (live evidence), поэтому фактического расхождения чтения нет; при будущем fallback с другой моделью/размерностью KNN получит чужой space вместо честного FTS.",
      "repro": "Source-read обоих read-путей; текущие MSI сверены по live-route JSON. Отдельного runtime-дефекта на текущем конфиге нет.",
      "recommendation": "Не блокирует этот P0 (контракт write-centric, текущий MSI совпадает). При появлении fallback с другим MSI - применить route-aware допуск и к query-embed (FTS при несовместимости)."
    },
    {
      "id": "E503-R1-N02",
      "scope": "BACKLOG_ONLY",
      "severity": "low",
      "blocking": false,
      "title": "Не-primary alias (в т.ч. `extra_N` на том же endpoint) требует собственного durable admission",
      "contract_refs": ["E503-IDENTITY-01", "существующий PCI/admission-контракт"],
      "expected": "Запись разрешена только при доказанной совместимости фактической connection.",
      "actual": "`connection_identity()` включает `credential_alias`/`quota_group`; для alias вне primary route-gate вызывает resolver с его PCI. При отсутствии admission именно для этого PCI вектор остаётся text-only, даже если endpoint/модель совпадают с primary. Это существующая семантика admission (не новый гейт), но операционно важно: `EMBEDDING_EXTRA_*`-ключи на том же endpoint без своего допуска теперь не пишут векторы.",
      "repro": "Source-read `connection_identity`/`admission_valid`; тест `test_5xx_fallback_write_blocked_until_existing_admission` доказывает блокировку до допуска и запись после допуска для Google PCI.",
      "recommendation": "Зафиксировать в release-заметке; при использовании extra-ключей - получить существующий canary/probe/admission для их PCI."
    }
  ],
  "do_dod_a": {
    "verdict": "PARTIAL_NOT_VERIFIED",
    "technical_failover": "CLOSED_AT_REVIEW (10/10, RED 6F/4P, 3 mutations killed)",
    "live": "PENDING_DEPLOY",
    "apinet": "EXTERNAL_503_REMAINS_NOT_FIXED",
    "google_admission": "UNPROVEN_BY_EXISTING_GATE_LIVE_RESULT_UNKNOWN",
    "backlog": "4463/1187/143_NOT_RECALCULATED"
  }
}
```

## 2. Что проверено лично (код и вызывающие пути)

1. **Реальный дефект на базе.** `_pick_credential()` брал первый healthy; `_on_error()` на 5xx/timeout возвращал
   `transport` без исключения ноги; следующий `_pick_credential()` снова отдавал primary. RED-прогон на базе
   воспроизвёл именно это (см. §3), а не только отсутствие новых констант.
2. **Фикс.** `embed()` ведёт `excluded: set[alias]`; `_pick_credential(pool, excluded)`; `_mark_transport_failure()`
   исключает ногу и паркует её в **существующем** `QuotaGroupRegistry.credential_health` (`HEALTH_COOLDOWN`,
   `_PROVIDER_UNAVAILABLE_COOLDOWN_S=60`). Второго breaker/менеджера retry не создано; `_ATTEMPT_BUDGET=4` не менялся.
   `credential_health()` сам возвращает healthy после `until`, поэтому probe-recovery встроен в существующий слой.
3. **Single-leg.** `_mark_transport_failure` при `excluded == empty` и отсутствии другой пригодной ноги возвращает
   `False` (без парковки); цикл сохраняет прежние <=4 bounded attempts. Проверено тестом и тем, что этот тест
   проходит и на базе (поведение не изменилось).
4. **Auth/quota.** 401/403 -> `LLMAuthError` (`llm_client.py:1942-1954`), `_on_error` -> `auth_failed` только своего
   credential и terminal `raise`; независимые слоты не трогаются. 429 -> group cooldown + credential cooldown,
   `defer`; отсутствие ключей -> один legacy-вызов и терминал. Атрибуция идёт по `stats.credentials_used[-1]`,
   который заполняется перед HTTP-вызовом (`embedding_control_plane.py:1628-1631`), т.е. не "предыдущей" ногой.
5. **Identity/admission.** В `resolve_index_compat` добавлены только опциональные override `space_now/conn_now/model_now`;
   существующие вызовы без них идут прежним путём (сигнатура keyword-only). `_serving_route_write_allowed` требует
   `serviceable=True` и `state=compatible` от того же резолвера; при `COMPATIBILITY_UNKNOWN/INSUFFICIENT/INCOMPATIBLE`
   запись не выполняется. `admission_valid` по-прежнему требует совпадения и `space`, и `conn`; admission по имени
   модели не выдаётся. Тест поднимает реальную generation/admission-строку и реальный resolver.
6. **Write-seams.** Гейт стоит в `_save_graph_fact_embedding` (single/`remember_user_fact`, с precomputed dedup-вектором),
   `_save_archive_embedding` и обоих backfill'ах перед INSERT. Других писателей `graph_facts_vec`/`smart_archive` в
   `services/**` нет (grep). В `_save_graph_fact_embedding` отказ помечает batch как serviceability-state, поэтому
   остальные факты батча не делают повторных сетевых попыток (<=1 попытка на batch).
7. **Provenance.** `_LAST_SERVED_CREDENTIAL` - `ContextVar`, пишется только в `_on_success` фактической ноги, чистится в
   `embed()` и `MemoryManager._embed()`. Embed не уходит в `to_thread`/`run_in_executor` (проверено grep по services),
   поэтому контекст не теряется. Fallback-вектор не кладётся в `embedding_cache` под configured identity; cache-hit
   имеет provenance `None` и безопасен, т.к. fallback-векторы в кэш не попадают. `_dedup_decide` не делает
   дополнительных embed между dedup-вектором и записью.
8. **R17.** Логи содержат alias/provider/model/index/state/reason; ключи и тексты не логируются. `last_served_credential`
   хранит alias/provider/model/base_url/quota_group; наружу (в лог) base_url не выводится.
9. **Совместимость с существующими путями.** `_index_generation_ok`, `_vec_write_allowed`, canary, generation/adoption,
   recovery tick и backfill не переписаны; добавлены только проверка фактической ноги и skip кэша. 585-тестовый
   профиль и дополнительные `test_evol010_embedding_defects.py`/`test_embed_meta_wire.py` зелёные.

## 3. Независимо выполненные проверки

| # | Проверка | Результат |
|---|---|---|
| 1 | Новый файл на candidate (`d00a01b`, код `4ace0a3`), `pytest tests/test_p0_embed_503_failover.py -q --timeout=180` | **10 passed** (9.9 s) |
| 2 | 15-файловый профиль Builder'а на candidate, тот же интерпретатор/`--timeout=180` | **585 passed, 0 failed/errors/skipped** (83.56 s) |
| 3 | Извлечённый base `374dc606` (blob-хеши совпали с git) + новый тест-файл | **6 failed, 4 passed**: `['k-primary','k-primary'] != ['k-primary','k-fb1']` для server_error и timeout; all-legs остаётся на primary; 4 passed - single-leg, auth, 429, no-keys. RED не подменён отсутствием констант: основной дефект воспроизведён утверждением. |
| 4 | Мутация M1: `_mark_transport_failure` -> `return False` в temp-копии candidate | `test_primary_5xx...` (2 параметра) **FAILED** `['k-primary','k-primary']`; тест дискриминирует exclusion. |
| 5 | Мутация M2: `_vec_write_allowed` -> `return True` | `test_scenario_03_same_name_different_space_is_incompatible` **FAILED** `assert True is False`; identity-гейт не тавтологичен. |
| 6 | Мутация M3: `_serving_route_write_allowed` -> `return True` | Реальный кейс **FAILED** `assert 1 == 0` для `COUNT(graph_facts_vec)`; недоказанный Google-вектор записался бы. |
| 7 | Мой probe A (candidate, 3 ноги, 60 s park): primary 503 -> fb1 200; второй logical request в пределах 60 s | Вызовы 1-го: `[primary, fb1]`; 2-го: `[fb1]` - primary не дёргается; health primary=`cooldown`, fb1/fb2=`healthy`. |
| 8 | Мой probe B: primary 503 -> fb1 401 | Терминал `LLMAuthError`; primary=`cooldown`, fb1=`auth_failed`, fb2=`healthy`; следующий запрос идёт в fb2 (independent slots не выведены). |
| 9 | Мой probe C: все три 503 (60 s park) | 3 HTTP-вызова ровно по одной ноге; все три `cooldown`; немедленный следующий запрос - **0 HTTP**, `EmbeddingNoUsableCredential`. |
| 10 | Probe recovery: cooldown=0 | Первый запрос primary 503 -> fb1; следующий запрос снова primary и успешен (`last_served=primary`). Ограниченная probe-попытка работает, постоянной блокировки нет. |
| 11 | Extra suites: `test_evol010_embedding_defects.py`, `test_embed_meta_wire.py` | **16 passed** (классы/`_embed_fail_reason` не сломаны). |
| 12 | Границы: `git diff --name-only 374dc6060..4ace0a3ae` | ровно `services/embedding_control_plane.py`, `services/summary_memory.py`, `tests/test_p0_embed_503_failover.py`; `git diff 374dc6060..d00a01b07` добавляет только `plans/features/p0-embed-503-failover/evidence/*`. |
| 13 | `APP_VERSION` base/candidate, DDL/config/web/handlers/model/indexes/settings | `2.58.228` в обоих; в diff нет `config/**`, `handlers/**`, `web/**`, DDL, `plans/progress_scope.json`, `plans/workflow_state.md`. |
| 14 | Проверка evidence-метаданных Builder'а (`tests-final-2026-11-22.json`) | `base_sha=374dc606...`, `candidate_sha=4ace0a3...`, 585 passed, 0 failures; мой независимый прогон дал тот же исход. |

Мутационные и probe-скрипты выполнялись только в temp-копии base+candidate-файлов; рабочий worktree кандидата не
изменялся (чистый `git status`). Temp-копия удалена после проверок.

## 4. Тесты: дискриминация и честность

- `RecordingLLM` подменяет только HTTP-границу (`embed_once`), а не проверяемую логику; executor, registry, scheduler,
  `resolve_index_compat`, generation/admission и DB - реальные.
- RED-тесты падают утверждением о неверной ноге, а не только `AttributeError` (timeout/503 - оба; e2e/recovery -
  ожидаемый `AttributeError` новой константы на базе, это новые тесты, а не доказательство дефекта).
- 4 passed на базе - именно неизменные контракты (single-leg 4 попытки, 401 не трогает независимые слоты, 429
  group cooldown, no-keys legacy terminal). Это подтверждает, что кандидат не "починил" их случайно.
- E2E-тест использует реальный `MemoryManager`, реальную FTS, реальную БД; вместо sqlite-vec - плоская таблица
  (существующий прецедент `test_asap44_graphrag_batch_breaker`), контракт записи/idempotency проверяется без
  расширения. Это ограничение теста, но не тавтология: gate/resolver/admission-строка реальные.
- Fallback-вектор проверяется отсутствием строки в `embedding_cache` (`text`-колонка реально существует и
  заполняется, см. `_embed_cache_store`), затем durable admission для Google conn разрешает запись. Обе стороны
  (блокировка и допуск) проверены.

## 5. Границы и риски

- **Не тронуто:** `config/**`, `handlers/**`, `web/**`, DDL/схема, `APP_VERSION`, модель/индексы, ключи/настройки
  владельца, `plans/progress_scope.json`, `plans/workflow_state.md`. Деплоя/SSH/LLM/БД-записей не было.
- **Не сломаны:** single-leg bounded retry, batch breaker, recovery/backfill, canary/generation/admission,
  `llm_client` (585 + 16 targeted passed), старый `EmbeddingRetriesExhausted`/`EmbeddingNoUsableCredential` контракт.
- **Не второй breaker:** парковка использует `mark_credential`/`credential_health`; авто-истечение 60 s; probe
  recovery; при повторном 503 парковка повторяется, но не чаще одного окна. Постоянной блокировки primary нет.
- **Парковка 60 s - продуктовый компромисс:** одна transient 503 паркует ногу на 60 s; новые факты в это окно могут
  остаться text-only и будут добраны backfill'ом. Это соответствует owner-запросу "короткая парковка, не бомбить
  шлюз", но означает задержку записи, а не потерю фактов.
- **Stale admission:** `_serving_route_cache` TTL 60 s может задержать подхват нового durable admission до 60 s
  (bounded, документировано). Для fallback-маршрута кэш не может обойти `_vec_write_allowed` configured identity;
  отзыв admission без смены generation в течение TTL - теоретический узкий край, отдельного production-пути для него
  нет.
- **Legacy-режим:** при `EMBED_CONTROL_PLANE_ENABLED=false`/пустом пуле provenance отсутствует, route-gate инертен
  (прежнее поведение). Effective prod - control plane ON (live evidence), поэтому текущий P0 это не затрагивает.

## 6. Ограничения ревью

- **Живого failover нет:** деплой не выполнялся; реального `primary 503 -> Google` через production-путь в этом
  ревью нет. Код/тесты подтверждают маршрутизацию и admission-поведение, но не production-эффект.
- **Google admission:** live evidence показывает `COMPATIBILITY_UNKNOWN` для Google PCI; сам admission не выдан и не
  должен выдаваться этим ревью. Live evidence не записал `active_generation.fingerprint` и не вызвал resolver с
  фактическим Google fingerprint - поэтому `INSTANT`-ветка для Google в проде не измерена. После деплоя нужно
  записать фактический `resolve_index_compat` для serving-route: допускает ли существующий гейт Google (тогда векторы
  пишутся) или требует свой canary/probe (тогда text-only + FTS). Оба исхода соответствуют контракту; подменять
  результат нельзя.
- **Backlog не пересчитан:** 4463 eligible без вектора / 1187 за 24 h / 143 text-only; повторный замер и recovery tick -
  после деплоя. `smart_archive source_empty/superseded` - отдельная проблема, не 503.
- **Нет live smoke:** реальный embed smoke по профилям уже выполнен DevOps на master `f2540ac60`; я его не повторял
  (production/LLM запрещены в этой роли). Это внешнее evidence, не моё.
- **Не полный регресс:** 585 целевых + 16 дополнительных + новый файл; весь ~10k-тестовый набор не гонялся.
- **UI-гейт:** визуальных/интерактивных изменений нет (diff - только services/tests/evidence), поэтому Playwright и
  Browser Use для этого кандидата не применимы; UI "ИИ" не менялся.
- **Линия:** master двигался во время ревью (`b3796892` -> `c0d355391`); артефакт коммитится на текущий master;
  кандидат не смержен; `progress_scope.json`/`workflow_state.md` не правились.

## 7. Рекомендация по DoD A и строкам

- **E503-FAILOVER-01 - PASS (code) / DEPLOY_PENDING.** Per-operation exclusion, failover на независимые ноги,
  bounded retry/single-leg, парковка и probe recovery, негативный тест и мутация выполнены.
- **E503-AUTH-01 - PASS.** 401/403 -> `LLMAuthError` (existing `llm_client` mapping), независимые слоты не выводятся;
  429 уважает cooldown; отсутствие ключей - один legacy-terminal. Покрыто тестами, включая существующий
  `test_llm_client.py`/`test_embedding_control_plane_asap4.py` (в 585).
- **E503-IDENTITY-01 - PASS (code) / live admission unknown.** Смешивание запрещено: недоказанный fallback-вектор не
  пишется и не кэшируется; после durable admission для фактической connection запись проходит. Имя модели само по
  себе не допускает.
- **E503-RECOVERY-01 - REVIEW.** E2E-тест и существующие recovery/backfill зелёные; реальные до/после backlog и
  `embed_recovery_tick` - после деплоя.
- **E503-DIAG-01 - PASS (code).** Логи различают transport error (alias/provider), парковку, fallback served,
  route-not-admitted (state/reason/compat_class); ключи/тексты не выводятся.
- **E503-ACCEPT-MATRIX-01 - REVIEW.** Негативная матрица (503->fb1->fb2, all-down->FTS, recovery, 401/403/429,
  incompatible, backfill) покрыта unit/e2e; "совместимый fallback" в проде не наблюдался, live smoke - внешнее
  evidence DevOps.
- **E503-EXCLUSIONS-01 - PASS (scope) / deploy pending.** Diff ровно 3 файла; UI/DDL/space/ключи/настройки не
  тронуты; второй retry/breaker не создан.
- **E503-ROUTE-01 - внешнее evidence, не повторялось.** `live-route-2026-11-22.md/.json` на `f2540ac60`: primary
  503, fallback_1/2 200/3072/MSI e540..., admission Google false, backlog 4463/1187/143.
- **E503-REPORT-01 - после деплоя.** В отчёте разделить "failover исправлен" и "apinet работает"; не выдавать
  Google admission/backlog за факт без live-замера.
- **Release preparation:** кандидат можно готовить к деплою. После деплоя обязательна агентская live-проверка:
  отсутствие повторных primary-вызовов при 503, `embed mode=fallback served`, фактический admission-исход для
  serving route, text-only/FTS без записи недоказанного вектора, backlog до/после и recovery tick при
  восстановлении admitted-провайдера. Это работа агентов, не owner QA; сам деплой этим ревью не выполнялся.
