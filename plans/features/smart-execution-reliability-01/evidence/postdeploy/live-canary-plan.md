# Live-canary plan — 24 live/postdeploy строк на 0e4a144d (2.58.200)

Дата: 2026-11-14. Автор: PM. Состояние: план; ни одна строка не переведена в VERIFIED.

Контекст: обе карты (`requirements-map.json`, `requirements-map-fc-amendment.json`) перебинжены на
выкаченный `0e4a144db476a1535ae3a2b79a7cce30354ad866` (2.58.200). Все обязательные строки без
live-требования уже VERIFIED; остались ровно 24 id, у которых `live_required=true`,
`live_when=postdeploy`, статус `READY_FOR_LIVE` и ранее одобренный Reviewer `postrelease_wait`.
Этот план описывает, как получить реальные production-наблюдения по каждому id, кто их снимает и
какую форму доказательства PM примет.

## 1. Правила съёма (обязательны для всех исполнителей)

- **SSH/fail2ban.** Одна короткая recon-сессия + один основной прогон; не чаще ~1 подключения в
  минуту; таймаут ~15 с; при закрытом порте — пауза ≥22 мин, максимум один автоповтор. Статус сервиса
  проверять по HTTP (`https://admin-bot.duckdns.org/healthz`), он не ограничен.
- **Идентичность.** Каждый артефакт обязан в начале фиксировать: `git -C /var/www/admin_bot rev-parse
  HEAD` = `0e4a144d…`, `APP_VERSION` = `2.58.200`, `/healthz` 200 `{"status":"ok","version":"2.58.200"}`.
  Без этой тройки наблюдение не принимается за 2.58.200.
- **Секреты и приватность.** Ключи/токены/DSN/содержимое личных сообщений не печатать; chat ids — как
  `CHAT1..CHAT3`; в отчётах только не-секретные фрагменты.
- **Настройки владельца.** Ничего не перезаписывать. Для проверок с `budgets ON` использовать
  временный синтетический chat-scope внутри harness (или отдельный тестовый chat id), затем удалить;
  глобальные/чатовые строки и промпты — не трогать.
- **Платные вызовы.** Только ограниченные canary: ≤2 реальных LLM-прогона на SMART-сценарий и ≤3 на
  factcheck-сценарий за волну; никаких массовых прод-прогонов.
- **Один источник — один артефакт.** Сырые значения в файл, затем краткая ссылка в evidence. Не
  пересказ «работает», а конкретные строки/числа.

## 2. Доступные production-источники

| Код | Источник | Что даёт |
|---|---|---|
| `journal` | `sudo -u adminbot journalctl -u admin_bot -n N --no-pager` (и `-o json` для `_SYSTEMD_INVOCATION_ID`) | старт/рестарт, tracebacks/errors, `mca_event` (factcheck_diagnostics, проверки), предупреждения, отсутствие заморозок/повторов |
| `manifest` | `/var/www/admin_bot/.deploy/release.json` | `deployed_sha`, `version`, `previous_sha`, `release_branch`, `dirty_tracked` |
| `effective-config` | standalone `config.settings` + PG `bot_settings` / `chat_profiles.chat_params` (read-only SQL) | factory/env значения, persisted master switch, per-chat overrides, `updated_at`, capacity-источник |
| `db` | read-only SQL к рабочей БД | spool/attempt-журнал, событийный поток/курсор/lag, evidence/claim rows, счётчики |
| `smart-harness` | in-process на прод-дереве: `cd /var/www/admin_bot`, `venv/bin/python /tmp/<canary>.py`; реальные `Settings`, БД, провайдеры; `bot` = capture-stub (сообщение НЕ отправляется) | реальные provider/LLM/tool-пути, payload, capacity, бюджеты, локальный-first чтение кода, отказы источников |
| `factcheck-harness` | то же, но вызов `services.factcheck_orchestrator.run_factcheck(FactcheckRequest(...), service=…, db=…, bot=<capture>, cache=…)` | полный фактчек-путь с реальным поиском/LLM, diagnostics, DB-строки, `delivered/remainder` |
| `healthz` | HTTP `/healthz` | версия/живость без SSH |

Прецеденты таких harness: `plans/features/smart-execution-reliability-01/evidence/g/g_probe.py`
(in-process SMART, cwd = прод-дерево) и
`plans/features/add-exp/evidence/release-25896/acceptance/harness/accept96_live.py`
(in-process на проде, Telegram-delivery заглушён, PG/SQLite реальные, `cleanup_spec.json`). Новый
harness пишется в `/tmp/<canary>/`, после прогона нужные файлы копируются в репозиторий и `/tmp`
удаляется.

## 3. Форма evidence, которую PM примет для VERIFIED

```json
{
  "type": "production",            // "live" только если наблюдение получено из реального Telegram-обмена
  "candidate_commit": "0e4a144db476a1535ae3a2b79a7cce30354ad866",
  "deployed_commit": "0e4a144db476a1535ae3a2b79a7cce30354ad866",
  "ref": "live/<file>.md §<n> — что именно снято",
  "observation": "фактические значения/строки: healthz+HEAD+APP_VERSION, затем конкретные числа/логи",
  "artifact_path": "plans/features/smart-execution-reliability-01/evidence/postdeploy/live/<file>",
  "artifact_sha256": "<sha256 реального файла>"
}
```

PM отклоняет запись, если: нет `artifact_path`/sha; артефакт не содержит идентичности 0e4a144d/2.58.200;
наблюдение пересказано без сырых значений; использованы owner-изменения настроек; отправлены
сообщения в чаты без реальной необходимости. После привязки доказательства PM меняет статус строки на
VERIFIED и удаляет (не переписывая) `postrelease_wait` только по решению Reviewer/Orchestrator — до
этого строка остаётся READY_FOR_LIVE.

## 4. Сводная таблица

| # | id | срез | минимальное наблюдаемое | источник | доступно агенту сейчас |
|---|---|---|---|---|---|
| 1 | `SXR-A1-04` | S1-BUDGET-MASTER | effective budgets по CHAT1..3 + global: значения, источник, `budget_gate`-резолвер | effective-config + smart-harness | **да** (read-only) |
| 2 | `SXR-F2-01` | S6-GITHUB | реальный запрос к публичному GitHub из deployed-кода без `destination_blocked`; причина локализована | smart-harness + journal | **да** (1–2 запроса) |
| 3 | `SXR-F4-01` | S6-GITHUB | чтение репо/файла/символа, ветка/commit, rate-limit/private — фактическая причина; + естественный запрос о коде | smart-harness + live-чат для последнего пункта | частично (harness — да, natural request — нет) |
| 4 | `SXR-H3-01` | S8-SELFDIAG | `journalctl` под service-user rc=0, uid≠root, совпадающий InvocationID, чужой unit недоступен | journal + shell | **да** |
| 5 | `SXR-H4-01` | S8-SELFDIAG | manifest identity после рестарта; SourceReader видит тот же SHA; чекап использует | manifest + smart-harness (+ SXR-L7) | частично (чекап-часть — после #15) |
| 6 | `SXR-I1-01` | S9-EVENT-PIPELINE | нет 5-сек заморозок/повторов OperationalError; spool дренируется идемпотентно, записи сохранены | journal + db | частично (нужен реальный contention) |
| 7 | `SXR-I2-01` | S9-EVENT-PIPELINE | курсор двигается > окна за прогон; `lag_rows`=COUNT-дистанция; backlog падает; нет потерь/дублей | db + journal | частично (нужен реальный дренаж) |
| 8 | `SXR-K3-01` | S12-ACCEPT | пользовательские настройки/модели/ключи/промпты не перезаписаны; исправления активны без OFF/SHADOW | effective-config + db | **да** |
| 9 | `SXR-L1-01` | S12-ACCEPT | master OFF без скрытого enforcement; сценарий >4 раундов, >6 вызовов, >2 tool calls в раунде; usage пишется; ON-контракт | smart-harness (реальный LLM) + effective-config | **да** (платно, bounded) |
| 10 | `SXR-L2-01` | S12-ACCEPT | evidence сверх прежних лимитов в финальном payload; хвост источника сохранён; несколько результатов; честное превышение окна | smart-harness (payload capture) | **да** |
| 11 | `SXR-L3-01` | S12-ACCEPT | 8 capacity-сценариев: catalog/proven/unknown/смена модели/fallback/каталог недоступен/context exceeded | smart-harness + effective-config | частично (2 сценария — provider-ошибки) |
| 12 | `SXR-L4-01` | S12-ACCEPT | реальный запрос о собственном коде: local-first, identity, commit/path, прочитанные строки, результат в ответе | live-чат | **нет** → deferral |
| 13 | `SXR-L5-01` | S12-ACCEPT | разрешённое внешнее чтение (DNS/peer/identity) + отдельный отказ запрещённому назначению (SSRF) | smart-harness + journal | **да** |
| 14 | `SXR-L6-01` | S12-ACCEPT | 7 вариантов деградации, данные сохранены, заглушка не публикуется; то же в поиске и фактчеке | smart-harness + factcheck-harness | **да** |
| 15 | `SXR-L7-01` | S12-ACCEPT | реальная команда «чекап»: runtime-факты, журнал, код, полный/честный частичный отчёт | live-чат | **нет** → deferral |
| 16 | `SXR-L8-01` | S12-ACCEPT | по I1–I6: причина/фикс/проверка; мемы-spool; fresh stream курсор; lesson_rejected; reason codes | journal + db + harness | частично (I1/I2 наследуют #6/#7) |
| 17 | `SFC-5-10` | S14-FC-RESOURCES | новые значения на штатном пути без ручного включения; при OFF старый бюджет не enforced; `sources` | effective-config + factcheck-harness | **да** |
| 18 | `SFC-7-06` | S15-FC-EVIDENCE | delivered+remainder=total; DB rows == delivered; `factcheck_diagnostics` с route/stop_reason | factcheck-harness + journal + db | **да** (1 прогон) |
| 19 | `SFC-12-02` | S17-FC-ACCEPT | обычный фактчек **ответом** на сообщение: subject разрешён, поиск по исходному материалу, многосоставное и короткая реплика | live-чат (+harness для пайплайна) | **нет** (нужен живой триггер) → deferral |
| 20 | `SFC-12-07` | S17-FC-ACCEPT | заводские значения и их effective-применение A–J: OFF продолжает поиск, ON без скрытых старых caps | factcheck-harness + effective-config | **да** |
| 21 | `SFC-12-09` | S17-FC-ACCEPT | исходный сценарий (страны/традиция): материал сохранён, вопрос определён, поиск по нему, нет преждевременной остановки, прямой ответ | factcheck-harness + journal | **да** (1 прогон) |
| 22 | `SFC-13-01` | S17-FC-ACCEPT | request/correlation ID, route, deployed SHA, effective budget state+source, счётчики, coverage, результат | journal + factcheck-harness | **да** |
| 23 | `SFC-13-03` | S14-FC-RESOURCES | различимы sufficient / no_progress / provider failure / technical deadline / ON-budget / hidden enforcement | journal + factcheck-harness (инъекции) | **да** |
| 24 | `SFC-14-03` | S17-FC-ACCEPT | сквозной результат, а не константы/один user_hint/тесты; нет деградации обычного фактчека; closure в родительском эпике | journal + harness + release-evidence | частично (closure-часть — Orchestrator) |

## 5. Волны исполнения

**Волна 1 — read-only, без LLM (одна SSH-сессия, «recon + main»):**
`SXR-A1-04`, `SXR-H3-01`, `SXR-H4-01` (manifest/SourceReader часть), `SXR-K3-01`,
`SXR-I1-01`/`SXR-I2-01` (то, что наблюдаемо без ожидания события). Ожидаемый выход:
`evidence/postdeploy/live/wave1-readonly-<date>.md` + сырые JSON/SQL-выгрузки. Владелец работ:
DevOps (прод-доступ, journal, SQL); PM привязывает.

**Волна 2 — in-process SMART harness, bounded (≤2 реальных LLM-прогона):**
`SXR-F2-01`, `SXR-F4-01` (harness-часть), `SXR-L1-01`, `SXR-L2-01`, `SXR-L3-01` (детерминированные
сценарии), `SXR-L5-01`, `SXR-L6-01`, `SXR-L8-01` (I3–I6 часть). Владелец: Builder (harness) +
DevOps (запуск на проде). Выход: `live/wave2-smart-<date>.md` + `raw/*.json`.

**Волна 3 — in-process factcheck harness, bounded (≤3 прогона):**
`SFC-5-10` (resolver/sources часть), `SFC-7-06`, `SFC-12-07`, `SFC-12-09`, `SFC-13-01`, `SFC-13-03`, `SFC-14-03` (техническая часть).
Владелец: Builder + DevOps. Выход: `live/wave3-factcheck-<date>.md` + `raw/*.json`.

**Волна 4 — только живой чат (сейчас агенту недоступно):**
`SXR-L4-01`, `SXR-L7-01`, `SFC-12-02` (+ natural-request часть `SXR-F4-01`, чекап-часть `SXR-H4-01`).

После каждой волны PM обновляет только затронутые строки (VERIFIED или оставляет READY_FOR_LIVE с
уточнённым trigger) и фиксирует факт в binding-документе; повторного аудита всего эпика не требуется.

## 6. Строки, не наблюдаемые агентом сейчас, и путь отложенности

Все три строки уже несут одобренный Reviewer `postrelease_wait` (`nonblocking=true`), поэтому
остаются READY_FOR_LIVE без блокировки остальных работ. Уточнённые триггеры:

| id | почему сейчас нельзя | реальный триггер | кто и что снимет |
|---|---|---|---|
| `SXR-L4-01` | нужен входящий вопрос в чате о собственном коде Adminbot; у агентов нет канала инъекции входящих сообщений | ближайшее естественное сообщение владельца/теста в чате с вопросом о коде бота (или наличие разрешённого MTProto-тест-аккаунта) | DevOps/Builder: `journal` + диагностическая трасса этого запроса (local-first, identity, commit/path, строки) → `live/l4-<date>.md` |
| `SXR-L7-01` | нужна реальная команда «чекап» в чате | ближайшая реальная команда «чекап» (естественная либо разрешённый тестовый чат) | DevOps: отчёт чекапа + journal-трасса + runtime identity → `live/l7-<date>.md` |
| `SFC-12-02` | нужен реальный фактчек **ответом** на сообщение (сам триггер reply-пути) | ближайший реальный вызов «фактчек» ответом на текст в чате | DevOps: `factcheck_diagnostics` + subject/search в журнале + результат → `live/fc-12-02-<date>.md` |

Наследуемые частично-отложенные пункты (не отдельные строки): natural-request часть `SXR-F4-01`
(живой запрос о внешнем коде), contention-часть `SXR-I1-01` (реальный конкурентный доступ к журналу
мемов), дренаж-часть `SXR-I2-01` (несколько циклов fresh stream на backlog 2M строк), provider-error
сценарии `SXR-L3-01` (реальные ошибки каталога/провайдера), чекап-часть `SXR-H4-01`.

## 7. Что PM НЕ примет

- Пересказ «всё работает» без артефакта и без идентичности 0e4a144d/2.58.200.
- Наблюдения, снятые до рестарта на 2.58.200, либо из standalone-процесса без чатового слоя (например,
  `budget_gate.budgets_enabled` из standalone возвращает factory-значение — это не effective state).
- Симуляцию вместо реального события там, где acceptance требует именно реальный обмен
  (`SXR-L4-01`, `SXR-L7-01`, `SFC-12-02`) — для них допустимо только живое наблюдение.
- Изменение настроек владельца ради зелёного результата; отправку тестовых сообщений в чужие чаты.
- Owner-задачи вместо агентских: ни один пункт этого плана не передаётся владельцу как QA.

## 8. Текущее состояние

Все 24 id остаются `READY_FOR_LIVE` с прежним `postrelease_wait`; ни одного VERIFIED без наблюдения.
Общий статус эпика после ребиндинга: реализация выкачена, обязательные не-live строки VERIFIED,
acceptance = PENDING_FUTURE_EVIDENCE по этим 24 id (см. `binding/binding-0e4a144d.md`).
