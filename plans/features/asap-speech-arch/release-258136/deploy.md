# Deploy 2.58.136 — release/p0-2026-10-26 (DEPLOY-258136)

**Дата:** 27.10.2026 (server UTC 08:41–08:45). **Ветка:** `release/p0-2026-10-26`.
**Кандидат (merge W2):** `5f1dcd23` (merge `dec28b99`, Reviewer Approved).
**Bump-коммит = deployed SHA:** `6d08c5112c47d2f8f108d2488364abd3d827e574`
(`chore(release-258136): bump 2.58.135 -> 2.58.136 (31-file/33-pin proc set SET EQUAL proc-258135, F8-meta HEAD=5f1dcd23, deltaDDL=0)`).
**Pre-state:** `05c408f6` (2.58.135, healthz 200, active, NRestarts 0, dirty 13).

## PART 1 — bump

31 файл / 33 замены (SET EQUAL proc-258135): README `v2.58.136`, APP_VERSION,
F8-meta (APP_VERSION 2.58.136 + HEAD `5f1dcd23` — SHA кандидата), 24 py-пина
(polygon — 2 строки), 4 JS escaped-regex. Push `65d07c1b..6d08c511 -> origin`
(fast-forward; origin отставал на 3 docs-коммита, входящих в кандидата).

| Guard | Результат |
|---|---|
| `py tools/gen_param_registry_round1025.py --check` | **OK**: реестр 587 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны (rc=0) |
| `py -m compileall services handlers` | **OK** (rc=0) |
| deltaDDL | **0**: diff 5f1dcd23..6d08c511 — только пин-файлы; runtime-подтверждение после рестарта: `[database] migrations: start | current user_version=37 | pending=[]` → `complete | user_version=37 | total 0.0s` |

## PART 2 — deploy (SSH: recon + main, fail2ban-safe)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot`, venv python 3.12.3.

| Шаг | Результат |
|---|---|
| Pre-state (recon) | HEAD `05c408f6`, dirty 13, active/running, NRestarts 0, loopback healthz 2.58.135 |
| PG pre-read (3 prompt-ключа, raw bytes) | `direct_l1_planner=08baafabcfc4`, `direct_chat_system=d4c558629215`, `direct_chat_verbalizer=f7341178cb6f` (pre-W2 persisted-эра) |
| `git fetch origin release/p0-2026-10-26` | rc 0, `05c408f6..6d08c511` |
| `git checkout --detach 6d08c511` | rc 0, HEAD = `6d08c5112c47…`, dirty 13 сохранено |
| Контент-сверка deployed vs локальный кандидат | **18/18 sha256 OK** (12 из proc-258135 + 6 W2-файлов; web/app.js и tool_schemas byte-equal прошлому релизу) |
| `sudo systemctl restart admin_bot` | RESTART_RC=0, новый MainPID 514738 |
| healthz после рестарта | loopback **200 `{"status":"ok","version":"2.58.136"}`** (try 5); внешний HTTPS `admin-bot.duckdns.org/healthz` → **200, 2.58.136** (проверен трижды: после деплоя, после пробы, финал) |
| Unit | `active/running`, **NRestarts = 0** |
| Журнал | 0 ERROR/CRITICAL/Traceback-строк; graceful shutdown старого PID, `Start polling @PERMsoc_bot id=8802473181` 08:44:50Z; migrations `user_version=37, pending=[], 0.0s` |

### Миграция prompt-канонов (журнал, 08:44:46Z)

```
[prompt_migration] канон обновлён | key=prompts.direct_chat_system_prompt
[prompt_migration] канон обновлён | key=prompts.direct_chat_verbalizer_system_prompt
[prompt_migration] канон обновлён | key=prompts.direct_l1_planner_system_prompt
```

- Лестница L1: пред-миграционные persisted-байты (raw sha12 `08baafabcfc4`) →
  новая активная редакция; writer и tool-phase каноны мигрированы тем же
  стартом («уже новый канон» для compress/factcheck_analyst/summary_l1_clusterizer;
  11× «кастом юзера — НЕ трогаем» — genuinely-custom значения сохранены, как и в 2.58.135;
  core patch: «абзацы уже есть, авторские байты целы»).
- Авторитетная байт-сверка — через продуктовый путь резолва
  (`resolve_prompt_with_source`, probe canon-report, дважды: полный прогон и
  sanity-прогон): все три ключа **source=global, sha12 == новые активные байты**:
  L1 `14743d288ea3`, tool-phase `747fa3a2e292`, writer `f5c4807d088e`;
  FACTORY_SET эра `3bc0c543520c`.
- Примечание: сырые sha12 из bot_settings (pre/post read) не совпадают с
  sha12 констант — значения в БД хранятся в закодированной форме
  (normalize_value); сверка делается через продуктовый резолв (см. выше).

## PART 3 — W2 live re-probe (read-only, real LLM, NO Telegram)

Драйвер `live_pa5_r2.py` (паттерн accept96/live-scenarios: полный конвейер
Direct Chat без телеграмных слоёв) на сервере в `/tmp/pa5s_r2` из
`git archive 6d08c511`. Изоляция: PG строго read-only
(`server_settings default_transaction_read_only=on`; probe
`ro_ok:ReadOnlySQLTransactionError`), SQLite — отдельная схема-клон + только
строки целевого чата за 30 дней (6550 сообщений; полная копия 1.8G невозможна
— диск, см. «Инциденты»), Telegram = FakeBot (0 сетевых отправок), LLM
реальный (`deepseek/deepseek-v4.1-flash`), бюджет 26 вызовов.

| Сценарий | L1 план | Tools | Payload-маркеры | Результат |
|---|---|---|---|---|
| S101 LPDDR run1 (3 хода) | reply/answer; caps=[] | 0 | L1 sys `14743d28` + ws_token×1; writer: focus×1, **W2 tech-секция×1** (все ходы) | **PASS**: «4 чипа по 32 бита — это 128 бит суммарной ширины, а не четыре канала»; «ограничение конкретной реализации, а не принципа»; честный unknown («без модели устройства — скорее всего нет», «надо смотреть схему и даташит, а не гадать») |
| S101 LPDDR run2 (3 хода) | reply/answer | 0 | те же | **PASS** (стабильно): «нихуя не четыре, если ты про независимые каналы… считай не корпуса, а контроллер»; теория-vs-реализация разведена; вычисления без выдуманных спецификаций |
| S102 Crescent Island | reply/research, caps=[web_search,…] | **execute_web_search Fired** | writer user payload содержит результаты (ws×2) | **PASS**: поиск сработал; цифры атрибутированы источникам (Hot Chips 2026 24.08; публичный релиз 12.10.2026; 160/480 ГБ LPDDR5X, 350 Вт, 32 Xe3P, 1.3 PFLOP/s FP8); выдуманной архитектуры нет |
| SANITY «как сам-то?» | reply/emotional_reply/micro, tool_policy=none, conf high | 0 | l1+writer, 2 вызова | **PASS**: 47 символов, разговорно, без анонсов (после рерана; первая попытка упёрлась в бюджет пробы 26 вызовов — штатный fail-soft «я подавился токенами», не продуктовый дефект) |

- W2-семантика rule 4: для LPDDR (формулы/вычисления/общие принципы) поиск не
  нужен и не делался, выдуманных современных спецификаций нет — ожидаемое
  поведение по PA5W2; для современного продукта (Crescent) поиск вспыхнул.
- W2 writer/tool-phase секции: writer — ровно ×1 в каждом writer-payload;
  tool-phase секция подтверждена в резолвнутом каноне (×1); живой tool-phase
  LLM-payload не генерился (инструментDispatch идёт через simple_tools без
  отдельного tool-loop вызова — как и в §10-прогоне 2.58.135).
- 12 side-LLM вызовов класса «other» (memory/extraction, пустой system) —
  штатные попутные вызовы прод-конвейера, вне объёма проверки.

## Откат

```
cd /var/www/admin_bot && git checkout 05c408f6f974670193588da795bdbc66dfa26a2b && sudo systemctl restart admin_bot
```
Ожидаемое после отката: 2.58.135, healthz 200. untracked 13 переживают checkout.
Примечание: мигрированные prompt-значения в PG остаются новыми байтами
(старый код считает их custom) — для полной поведенческой откаты канонов
дополнительно выполнить ROLLBACK-ступени `PREV_*_PA5W2` (стандартная лестница)
или восстановить прежние значения PG.

## Инциденты (не продуктовые)

1. **Корневой ФС сервера 100%** (3.7M свободно) в окне пробы: полная SQLite-копия
   (1.8G) упёрлась в ENOSPC. Освобождён СВОЙ неполный probe.db (1.8G) →
   1.7G свободно (93%); проба переведена на схему-клон + целевой чат.
   **Требуется решение владельца/ops по очистке диска** (журнал/бэкапы/образы —
   не моя зона удаления). Сервис оставался здоровым (healthz 200 весь период).
2. SSH-бюджет: планировалось ≤4, фактически 10 одиночных сессий с интервалом
   ≥60 с (все логины успешные, без ретраев аутентификации; fail2ban-паттерн
   соблюдён). Причина — инцидент диска + адаптации драйвера
   (frozen Settings → env DB_PATH; initialize_existing → schema-клон).
3. Probe-окружение: FTS rebuild и vector-init деградировали (RO PG / редуцированная
   копия) — не влияют на проверенные пути (окно L1 читается напрямую).

## Итог (closure REQ-CLOSE-DEPLOY)

- **Deployed:** `6d08c511` (= кандидат `5f1dcd23`/`dec28b99` + release-bump),
  healthz **2.58.136/200** (loopback + внешний), unit active, **NRestarts 0**,
  журнал чистый, deltaDDL=0 (runtime), контент 18/18, rollback готов.
- Миграция prompt-канонов: **подтверждена** (журнал + резолв новых байтов ×2 прогона).
- W2 re-probe: §4 **PASS**, §5 **PASS**, §6 **PASS**, sanity **PASS**
  (см. `plans/features/post-asap5-corrective/evidence/live-reprobe-258136.md`).
- Сырые артефакты: `OPENCODE_WORKFLOW_SCRATCH/rel136_probe_evidence/` (sha-лист
  `OPENCODE_WORKFLOW_SCRATCH/rel136_evidence_sha256.txt`), логи
  `rel136_deploy_main.txt`, `rel136_recon.txt`, `rel136_probe_final.txt`.
