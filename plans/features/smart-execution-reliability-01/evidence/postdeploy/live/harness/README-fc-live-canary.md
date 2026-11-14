# FACTCHECK-REQUEST-INTEGRITY v2 — production live-canary harness

`fc_live_canary.py` — один самодостаточный скрипт для сбора **фактического
боевого** evidence по строкам `READY_FOR_LIVE` карты
`plans/features/smart-execution-reliability-01/requirements-map-fc-amendment.json`.

Скрипт ничего не доказывает сам по себе: он **наблюдает** развёрнутый релиз и
пишет машинно-читаемый отчёт. Ни одна строка карты этим файлом не помечается
`VERIFIED` — verdict остаётся за независимым Reviewer / PM.

Автор: Builder (SMART-EXECUTION-RELIABILITY-01 / S17-FC-ACCEPT, unit
`fc-live-canary`). Скрипт написан по коду релиза `2.58.200`
(`0e4a144d…`, release worktree `13884daa`), никакой production-код не изменялся.

**Версия harness: `1.1.0`.** После независимого аудита (Needs Fixes) исправлено:
self-test ограничен по времени (per-step + watchdog, сеть блокируется),
вакуумные утверждения заменены проверяемыми, каждый check публикует
`evidence_class`, отчёт содержит candidate binding (`harness_sha256` +
git HEAD/branch + deployed SHA). Подробности — §7.

> **Evidence привязывается к кандидату.** Коммитимый артефакт — этот harness
> файл вместе с JSON-отчётом. `harness_sha256` в JSON — sha256 байт самого
> файла; `candidate_binding.git_head`/`deployed_sha` — чекаут, который
> наблюдался. Перед сдачей evidence файл harness должен быть закоммичен; хэш в
> отчёте позволяет Reviewer проверить, что запускался именно он.

---

## 1. Точная команда для production

```bash
# DevOps копирует ОДИН файл в /tmp; рабочее дерево /var/www/admin_bot остаётся чистым
scp fc_live_canary.py root@192.255.209.205:/tmp/fc_live_canary.py

ssh root@192.255.209.205
cd /var/www/admin_bot

# 1) dry-run: identity, effective state, capacity — без вызовов провайдеров
venv/bin/python /tmp/fc_live_canary.py --dry-run \
    --json-out /tmp/fc_live_canary_dryrun.json

# 2) полный прогон (5 реальных фактчеков, лимит вызовов 60)
venv/bin/python /tmp/fc_live_canary.py \
    --json-out /tmp/fc_live_canary.json \
    --allow-provider-calls --max-provider-calls 60

# при необходимости только подмножество проверок
venv/bin/python /tmp/fc_live_canary.py --allow-provider-calls \
    --checks ordinary_factcheck,production_smoke \
    --json-out /tmp/fc_live_canary_smoke.json

# 3) явный offline-режим (без провайдеров; прод-проверки = not_observed)
venv/bin/python /tmp/fc_live_canary.py --offline \
    --json-out /tmp/fc_live_canary_offline.json
```

`--json-out` — единственный артефакт; stdout печатает короткую сводку
(`checks/observed/not_observed/errors/production_observed/by_evidence_class`),
всё остальное — в JSON.
Код возврата: `0` — harness отработал (даже если проверки дали `error`);
`2` — bootstrap невозможен (не тот cwd, нет модулей релиза, нет БД);
`1` — только для `--self-test`.

**Ограничение времени.** `--self-test` имеет локальный bound на каждый шаг
(`--self-test-step-timeout`, default 20 с), общий deadline
(`--self-test-timeout`, default 75 с) и процесс-level watchdog (deadline + 5 с):
зависший шаг помечается `timed_out`, остальные шаги либо выполняются в остатке
бюджета, либо `skipped_due_to_deadline`; процесс гарантированно завершается.
Офлайн self-test не делает ни одного сетевого вызова: на время self-test
`connect/connect_ex/create_connection/getaddrinfo` блокируются, попытка сети
попадает в `checks.S15_no_network_attempts=false`. Полный canary ограничен
`--check-timeout` (default 900 с на проверку).

### Предпосылки production-прогона

| Условие | Зачем |
|---|---|
| cwd = `/var/www/admin_bot` | импорт развёрнутого кода + `.env` (`load_dotenv` читает cwd) |
| `venv/bin/python` (Python 3.12) | только установленные зависимости проекта; новых пакетов нет |
| `.env` с `POSTGRES_DSN`, `LLM_*` | effective-state (read-only) и реальные LLM-вызовы |
| доступ к `127.0.0.1:8000/healthz` | identity/health часть smoke-check |
| `systemctl show admin_bot` (опционально) | `process_started_at` для `deploy_identity` |

Если `POSTGRES_DSN` недоступен, harness честно запишет
`effective.pg.available=false` и будет считать effective-состояние по
заводским значениям — это **не** production effective state, и проверки
`SFC-12-07`/`SFC-5-10`, зависящие от него, будут отмечены как неприменимые.

---

## 2. Соответствие проверок и требований

| Check id | req_ids | Что реально наблюдается |
|---|---|---|
| `ordinary_factcheck` | SFC-12-02, SFC-7-06, SFC-13-01 | обычный `фактчек` ответом на текстовое сообщение: запрос принят (`outcome=verdict`), цель/предмет разрешены, `user_hint` пуст и предмет не потерян, поиск по материалу, ≥2 claim units и ≥2 queries, evidence `refs>=2` и `evidence_chars>=500`, содержательный ответ `>=120` символов; `stop_reason ∈ {sufficient_evidence, paths_exhausted}`; durable-строки привязаны к scope прогона (`chat_id+trigger+target`, ровно 1 run-строка) и `delivered rows == DB rows`; `delivered+remainder==total` из `factcheck_diagnostics.evidence_delivery` (отсутствие события — провал, не «по умолчанию ок»); полный observability-бандл (correlation id, route, SHA, эффективные бюджеты + источник, queries/candidates/opened/claim units/evidence chars, model capacity, stop_reason, cover, итог) |
| `multipart_and_short_reply` | SFC-12-02 | многосоставное сообщение (4 предложения): ≥2 queries, части не потеряны (`parts>=4` или `claim_units>=4`), `refs>=2`, ожидаемый `stop_reason`; контекстная короткая реплика «А это точно?»: предмет остаётся материалом, поиск идёт по исходному материалу, есть evidence, ответ не подменяется общим уточнением |
| `budget_scenarios` | SFC-12-07, SFC-5-10 | сценарии A–J: реальный effective-state (read-only PG) + контролируемые прогоны planner'а; OFF не даёт дедлайна/cap'ов, OFF исполняет весь план даже при сохранённом старом лимите, ON даёт 120/600/24/64/100000/20/32 и не оставляет скрытых старых потолков, сохранённый пользовательский лимит применяется, evidence > 8000 символов доходит до аналитика, 16 частей сохраняются lossless, 10 результатов не урезаются до 4 (`page_size=20`, явный `max_rows_per_query=4` даёт ровно 4), lossless-порции при ON (>100000 симв. → ≥2 порции) и единственная порция при OFF, физический предел модели/источника обрабатывается честно (truncate + remainder, `rows+remainder==total`). `evidence_class=plumbing` (транспорт — скриптовый двойник) |
| `metric_distinguishability` | SFC-13-03 | контролируемые прогоны `run_retrieval` + `classify_retrieval` + `evidence_diagnostics`: различимы `sufficient_evidence`, `no_progress`, `providers_unavailable`, `technical_limit`, `budget_exhausted`, маркер `unexplained_stop`; частичный результат не маркируется технической аварией; `deadline_exceeded` не универсальное объяснение. `evidence_class=plumbing` |
| `original_production_scenario` | SFC-12-09 | исходный кейс владельца (вопрос про страны + сообщение о традиции): материал сохранён, вопрос пользователя опознан, поиск построен по вопросу, источники открыты, ранней остановки по старым бюджетам нет, ответ прямой (упоминает страну/страны из вопроса), неоднозначность «внешнего влияния» обозначена, и ответ **не является эхом** входного материала/вопроса harness (`answer_not_a_harness_echo` — проверяемое утверждение, а не `True` by construction) |
| `production_smoke` | SFC-14-03 | identity: git HEAD == manifest `deployed_sha`, `APP_VERSION` == версия манифеста == `/healthz`, effective `flags.factcheck_pipeline_v2`; короткий реальный фактчек дошёл до ответа; safety-блок (Telegram не задействован, PG не открывался или открыт read-only) |

Карта/сьюты: `plans/features/smart-execution-reliability-01/requirements-map-fc-amendment.json`,
owner source `plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2-full.md`
(§1.1 исходный кейс, §5.2 значения, §6 завершение поиска, §12.1–§12.8 приёмка,
§13 наблюдаемость, §14 DoD).

---

## 3. Безопасность (жёсткие ограничения, реализованы кодом)

* **Telegram I/O отсутствует.** `aiogram.Bot` не создаётся. Все исходящие
  методы — `StubBot.send_message/send_chat_action/set_message_reaction/
  edit_message_text/delete_message` — только записывают попытку в память.
  Индикатор «печатает…» отключён in-memory (иначе aiogram сам ходил бы в сеть),
  пауза между чанками выставлена 0 с.
* **Реальная история чатов не пишется.** Синтетический чат
  `SYNTH_CHAT` живёт во временной SQLite-базе, созданной с нуля
  (`DatabaseService.initialize()` в `mkdtemp`); после прогона каталог удаляется.
* **Production PostgreSQL — только read-only.** `asyncpg` подключается с
  `default_transaction_read_only=on` и выполняет лишь `SELECT` по
  `bot_settings` / `chat_profiles` для effective-state. Chat id в отчёте
  заменены на `chat-1…chat-N`.
* **Учётные записи провайдера не засоряются.** У `LLMClient` в инстансе
  отключены `_record_global_usage` / `_record_analytics` /
  `_record_sent_call` / `_record_sent_attempts` (usage/analytics/trace в PG),
  поэтому реальные вызовы не создают строк usage для синтетического чата.
* **Конфигурация не сохраняется.** Hot-config и chat-params подменяются
  in-memory шимами из read-only снимка PG; после прогона восстанавливаются.
  Ничего не записывается в `bot_settings`, `chat_profiles`, `.env`.
* **Провайдеры только по флагу.** Без `--allow-provider-calls` не выполняется
  ни один реальный LLM/поиск/fetch-вызов; такие проверки получают статус
  `not_observed`. Каждый реальный вызов (LLM, search, page fetch) считается;
  при превышении `--max-provider-calls` вызов блокируется
  (`ProviderCallCapReached`), прогон деградирует честно и не продолжает тратить.
* **Секреты не печатаются.** Маскируются `sk-…`, bot-token, `api_key=…`,
  e-mail-подобные значения, DSN; URL обрезаются до scheme+host+path; тексты
  приводятся в укороченном виде.

Итоговый отчёт содержит блок `safety` с машинной фиксацией:
`telegram_bot_is_stub=true`, `outbound_delivered_to_telegram=0`,
`config_persisted=false`, `production_pg.opened` (реально ли открывалась PG),
`production_pg.mode` (`read_only` / `not_opened`), `provider_calls_total=<n>`;
`real_telegram_bot_constructed` вычисляется из фактического класса бота, а не
объявляется константой.

---

## 4. Стоимость и время

Реальные вызовы выполняют только 5 сценариев (check 1, 2a, 2b, 5, 6).
Остальные проверки — контролируемые прогоны planner'а с локальным
двойником агрегатора (сеть не используется).

Ориентир на один прогон (production, budgets effective OFF):

| Сценарий | LLM-вызовы | Поисковые вызовы | Открытий страниц |
|---|---|---|---|
| ordinary | 3–5 | 2–4 (+1 refine) | ≤ 2 |
| multipart (4 части) | 3–5 | 4–8 | ≤ 2 |
| short reply | 4–6 | 1–3 | ≤ 2 |
| original (вопрос) | 4–6 | 1–3 | ≤ 2 |
| smoke | 3–4 | 1–2 | ≤ 1 |

Суммарно ≈ **20–45** вызовов; дефолтный cap — **60**. При исчерпании cap
поднимать осознанно (`--max-provider-calls 90`) и фиксировать фактическое
число из `call_budget` отчёта. Время: один реальный фактчек ≈ 20–90 с
(бюджеты OFF не ставят продуктовый дедлайн), весь прогон ≈ 3–8 минут.

---

## 5. Как читать результат

### Класс доказательности (`checks[].evidence_class`)

| Класс | Значение | Можно ли считать production-evidence |
|---|---|---|
| `production` | Вердикт опирается на реальный прогон боевого кода с боевым транспортом (LLM/поиск/fetch) и/или на real read-only production state | Да, при `status=observed` |
| `plumbing` | Вердикт опирается на скриптовые двойники транспорта (контролируемые сценарии planner'а/retrieval); проверяет контракт кода, но не боевой транспорт | Нет; это не production-доказательство (см. `production_evidence=false`) |
| `unavailable` | Нужный транспорт/состояние отсутствуют (offline, нет PG, v2 выключен, прогон не выполнялся) | Нет |

`production_evidence` вычисляется как `status=observed AND
evidence_class=production`; сводка отчёта содержит
`summary.by_evidence_class` и `summary.production_observed`. Смешивать нельзя:
`budget_scenarios`/`metric_distinguishability` даже при `observed` остаются
`plumbing`, а реальные подтверждения для их строк берутся из production-частей
(ordinary/original/smoke + read-only effective state в `details`).

### `checks[].status`

* `observed` — прогон выполнен, все встроенные утверждения прошли;
* `not_observed` — прогон не выполнялся (нет `--allow-provider-calls`,
  effective `flags.factcheck_pipeline_v2=false`, недоступен PG). Это **не**
  провал требования, но и **не** доказательство: строка остаётся не
  подтверждённой;
* `error` — прогон выполнен, но встроенные утверждения/исключение показывают
  отклонение; список не прошедших пунктов — в `details.assertions`.

Ключевые поля `details`:

* `bundle.request_correlation_id` — id прогона (тот же, что в
  `factcheck_diagnostics` / `factcheck_claims` / LLM-логах);
* `details.db_binding` — привязка durable-строк к прогону: `scope`
  (`chat_id+trigger+target`), `runs_for_scope` (должно быть 1),
  `scope_unique`, `durable_run_id`, `delivered_rows` vs `db_evidence_rows`,
  `db_claim_chars`. Durable `run_id` генерируется кодом релиза (`tfr-<hex>`),
  поэтому привязка идёт по уникальному scope, а не по «последней строке чата»;
* `bundle.route` — `envelope_temporal` (единый v2-путь) либо
  `v2:envelope_temporal` из `factcheck_admission`;
* `bundle.stop_reason` — машинная причина завершения retrieval;
* `bundle.delivered_rows` / `bundle.db_evidence_rows` — сверка БД ↔ payload;
* `bundle.answer_preview` — доставленный текст (сокращён);
* `observability[]` — требуемый §13 бандл по каждому прогону;
* `effective` — снимок effective-настроек: `synthetic_chat` (как видит новый
  чат), `real_chats` (реальные чаты как `chat-1…N`, включая явно сохранённые
  лимиты и их источники), `global`, `pipeline_v2_enabled`,
  `temporal_factcheck_enabled`, `model_capacity`.

Отчёт также содержит `harness_sha256` (sha256 байт самого файла harness) и
`candidate_binding`:

```json
"candidate_binding": {
  "harness_path": ".../fc_live_canary.py",
  "harness_sha256": "<64 hex>",
  "repo_root": "/var/www/admin_bot",
  "git_head": "<40 hex>",
  "branch": "release/2.58.200",
  "dirty": false,
  "deployed_sha": "<40 hex>",
  "release_manifest": {"present": true, "deployed_sha": "...", "version": "2.58.200"},
  "binding_status": "verified|partial|missing",
  "binding_reasons": ["..."]
}
```

`binding_status=verified` = есть 40-hex HEAD, есть sha256 harness, чекаут не
грязный и (если манифест присутствует) его `deployed_sha` совпадает с HEAD.
`partial` — есть расхождение (грязное дерево/манифест/конфликт identity),
`missing` — нет HEAD или хэша. Отсутствие `.deploy/release.json` на dev/release
worktree отражается в `binding_reasons`, но не делает git-привязку фиктивной.

Проверка перед сдачей evidence:

```bash
sha256sum fc_live_canary.py        # должно совпасть с candidate_binding.harness_sha256
git -C /var/www/admin_bot rev-parse HEAD   # должно совпасть с git_head/deployed_sha
```

---

## 6. Ограничения (важно для Reviewer)

1. Харнесс вызывает `services.factcheck_orchestrator.run_factcheck` напрямую —
   это тот же код, который вызывает handler, но без aiogram-слоя (BinaryHandler
   и кулдаун-логика хендлера не исполняются). Разрешение публикации,
   suitability-гейт, envelope, planner, retrieval, analyst/validator/verbalizer,
   renderer, durable-записи — боевые.
2. `FactCheckService` создаётся без `ToolRouter`: envelope-путь его не
   использует, но lore/metric-инструменты в этом прогоне недоступны.
3. Медиа/Vision-ветки (изображения, альбомы, OCR) в эти строки не входят и не
   проверяются.
4. Каждый сценарий выполняется **один раз**; ответы провайдеров и выдача
   поисковиков изменчивы. Повторять прогон при `error`/странном ответе, а не
   «усреднять» один успешный.
5. Эвристики исходного сценария («прямой ответ», «неоднозначность») —
   детекторы для человека: харнесс фиксирует факт упоминания стран из самого
   вопроса и наличие оговорки, но окончательную смысловую оценку делает
   Reviewer по `answer_preview`.
6. `deadline_exceeded`/`budget_exhausted` в ответе — это сигнал остановки
   поиска; харнесс помечает такой ответ как отклонение исходного сценария
   (`no_old_budget_early_stop`), а не как успех.
7. Временная SQLite-база — реальная схема `DatabaseService`, но без
   накопленной истории чата: контекст сценария ограничен синтетическими
   сообщениями.
8. `not_observed` нельзя читать как «требование не выполнено»; это
   «доказательство не собрано». PM/Reviewer должны зафиксировать такие строки
   как `UNVERIFIED`, а не `VERIFIED`.
9. `--max-provider-calls` считает вызовы уровня пайплайна (один
   `llm.generate` / один поисковый запрос / одно открытие страницы), а не
   внутренние HTTP-ретраи клиента: фактическое число сетевых попыток может
   быть больше счётчика. Внутренние таймауты клиента/провайдера/фетчера
   остаются боевыми; поверх каждой проверки стоит внешний bound
   (`--check-timeout`, default 900 с), а весь офлайн self-test ограничен
   step/total/watchdog-бюджетами.
10. Прогон не изолирован от изменчивости провайдеров: при `error` нужно
    смотреть `details.assertions`, а не подгонять ожидания.
11. `--self-test` проверяет API именно того чекаута, который указан в
    `--repo-root` (по умолчанию cwd). На чекауте с другой версией релиза
    (например, локальный main новее `2.58.200`) self-test честно падает на
    несовпадении API (`resolve_claim_publication` и т.п.) — запускать его нужно
    в release worktree/на production-чекауте, который наблюдаем.
12. `--offline` (или отсутствие `--allow-provider-calls`) не производит
    production-evidence: все прод-проверки `not_observed`, а
    `budget_scenarios`/`metric_distinguishability` остаются `plumbing`.


---

## 7. Локальная валидация (что уже прогнано автором)

```powershell
# cwd = read-only worktree релиза (13884daa == 0e4a144d + docs)
python -m py_compile fc_live_canary.py
python fc_live_canary.py --self-test --json-out selftest.json    # provider-free, bounded
python fc_live_canary.py --offline --json-out canary_offline.json # без вызовов провайдеров
python fc_live_canary.py --dry-run --json-out dryrun.json
```

`--self-test` (провайдеры не вызываются, сеть заблокирована) проверяет:
self-hash harness; публикацию/предмет/envelope/гейт/план по реальным функциям
релиза; OFF-контракт planner'а (полный план без дедлайна и `budgets_enabled=false`);
различимость 4 stop reason'ов (`sufficient_evidence`/`no_progress`/
`providers_unavailable`/`technical_limit`); упаковку evidence (>8000 символов и
честный remainder при малой ёмкости, `rows+remainder==total`); декомпозицию 16
частей с lossless-текстом; 10 candidates и `page_size`/порции; редакцию
секретов; заводские значения 120/600/24/64/100000/20/32; полный прогон
`run_factcheck` со стабовым транспортом (маршрут `envelope_temporal`,
`delivered rows == DB rows` по scope, `claim_chars`, correlation id, события);
негативные контроли (каждый predicate обязан вернуть `false` на сломанном
входе); отсутствие сетевых попыток.

Ожидаемый результат на release-чекауте: `self_test_passed=true` (16/16),
`--offline`: `observed=2` (оба `plumbing`), `not_observed=4`,
`production_observed=0`.

Фактически получено автором (release worktree `13884daa`, main-repo venv,
Windows, без сети):

```text
py_compile ............................... COMPILE OK
--self-test .............................. self_test_passed=true, 16/16, ~0.25 s
   S0 harness sha256 ..................... ok
   S1 publication ........................ ok (target_source=stored_reply)
   S2 material subject ................... ok (origin=material)
   S3 envelope ........................... ok (claim_chars=235, target id present)
   S4 gate ............................... ok (checkable_in_context, 2 claim items)
   S5 plan ............................... ok (3 queries, needs_web=True)
   S6 OFF full plan ...................... ok (attempted=6/6, budget_seconds=None,
                                               budgets_enabled=false)
   S7 stop reasons ....................... ok (4/4 значений)
   S8 evidence packing ................... ok (16000 chars; remainder=3 при 1200)
   S9 parts .............................. ok (16 частей, текст сохранён)
   S10 results & portions ................ ok (candidates=10, portions=3 lossless)
   S11 redaction ......................... ok
   S12 pipeline plumbing ................. ok (route=envelope_temporal,
                                               delivered=2 == db=2, scope_unique=true,
                                               claim_chars=235, 16 mca-событий)
   S13 factory values .................... ok (120/600/24/64/100000/20/32)
   S14 assertion sensitivity ............. ok (13/13 негативных контролей)
   S15 no network attempts ............... ok (guard armed, 0 попыток)
--offline ................................. observed=2, not_observed=4, errors=0,
                                            production_observed=0,
                                            by_evidence_class={plumbing:2,
                                            production:0, unavailable:4}
--dry-run ................................. exit 0, identity/effective/capacity
```

Доказательство bound'а (probe, не production): при намеренно зависшем
`resolve_claim_publication` self-test завершился за 6.02 с при
`--self-test-timeout 6 --self-test-step-timeout 2`: `S1 timed_out(timeout_s=2)`,
`S12 timed_out(4)`, `S13/S14 skipped_due_to_deadline`, `passed=false`,
watchdog не понадобился. Сетевой guard проверен отдельно: `create_connection` и
`getaddrinfo` бросают `ProviderCallsDisabled` и попадают в `attempts`.

Документированная версия harness (`HARNESS_VERSION=1.1.0`) имеет
`sha256=9513548e5830bd442ac0d869e2cd6637f6c18c7f7f6bb1a113aac2dec563cacd`;
фактический хэш запуска всегда указан в `candidate_binding.harness_sha256`
отчёта (для этой версии файла значения должны совпадать).

Локально `identity_code` = `unknown`/`path_denied` — это артефакт git-worktree
(`.git` — файл вне корня); на production-чекауте `deploy_identity` читает
манифест и даёт `deployed_sha`. Git-фолбэк (`git rev-parse`) страхует оба
случая.

---

## 8. Чего этот файл не делает

* не деплоит, не меняет конфигурацию и не перезапускает сервис;
* не отправляет сообщения в Telegram и не пишет в реальные чаты;
* не пишет в production PostgreSQL;
* не редактирует карты требований, планы и код приложения;
* не выдаёт `plumbing`-результаты за production-evidence и не помечает
  `not_observed` как успех;
* не объявляет требования выполненными: только собирает evidence для
  независимой проверки.
