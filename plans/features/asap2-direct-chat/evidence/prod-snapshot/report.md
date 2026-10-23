# ASAP2-PROD-SNAP — фактическая конфигурация промптов на проде 2.58.113

**Дата снимка:** 23.10.2026, ≈06:55Z (локально 18:55, UTC+12).
**Прод:** `198.46.175.136`, `/var/www/admin_bot`, venv проекта.
**Режим:** read-only. PG — только `SELECT`; сервис не перезапускался, `.env` не печатался, чаты не трогались, LLM-вызовов не было.
**SSH:** **1 коннект** (paramiko, один логин `nik`, пароль из `deploy_commands.txt` не выводился). Предыдущих коннектов в лейне не было, интервал не нарушался.
**Сырой вывод:** `raw-snapshot.json` (`CB10387E…0448`), скрипт снимка: `probe.py` (`C2014B87…1AD5`).

---

## 1. Deploy / rollback / health

| Параметр | Факт |
|---|---|
| `HEAD` | `e4ee54f3cc12c39492c60eb2a0865f5da429454c` |
| Ветка | `master` |
| Коммит | `chore(release-258113): bump 2.58.112 -> 2.58.113`, `2026-10-23T16:46:23+12:00` |
| Версия в коде | `APP_VERSION = "2.58.113"` (`config/settings.py`) |
| healthz (localhost) | `200 {"status":"ok","version":"2.58.113"}` |
| systemd | `active`; `MainPID=726282`, `NRestarts=0`, `ExecMainStatus=0` |
| Точка отката | `release/fix-2.58.111` = `fbf9013d89b03e38473ce6824a460fdbb736fff8` (ветка подтверждена в `origin`; объект коммита на сервере присутствует) |
| Backup БД | `backups/pre_deploy_258113_1792734640.db`, 1 497 432 064 B, `root:developers` |
| Диск | `/` 17G/24G занято, свободно 5.6G |

Оговорки:
- На сервере **нет локальной ветки** `release/fix-2.58.111` (`git rev-parse` → MISSING), но коммит `fbf9013d` присутствует и ветка есть в `origin`. Откат: `git fetch origin release/fix-2.58.111 && git checkout fbf9013d` (или по SHA) + `systemctl restart admin_bot`.
- `MainPID` отличается от зафиксированного в `deploy.md` (715288 → 726282): после деплоя сервис перезапускался. Текущий старт чистый (`NRestarts=0`, `ExecMainStatus=0`), healthz отдаёт 2.58.113.
- `integrity_check=ok` бэкапа в этом лейне **не перепроверялся** (файл 1.5 ГБ); запись `deploy.md` от 23.10 принята как есть.

## 2. Factory / active PG / effective

| Ключ | Factory (константа = реестр) | Active PG (raw) | Effective | Вывод |
|---|---|---|---|---|
| `prompts.direct_l1_planner_system_prompt` | sha256 `c987c03e3ee0…748c`, **6542** симв. | тот же sha256, 6542; `updated_at 2026-10-23 05:53:24.657Z` | тот же sha256, 6542; `source=global`, `withheld=false` | **factory == active == effective**, канон ASAP 2 |
| `prompts.direct_chat_verbalizer_system_prompt` | sha256 `d1b210c156c8…1b42`, **2827** симв. | тот же sha256, 2827; `updated_at 2026-10-23 05:53:24.646Z` | тот же sha256, 2827; но `source=default`, **`withheld=true`**, причина `provenance_unavailable`, `stored_sha12=d1b210c156c8` | байты **factory == active == effective**; действует заводская редакция, сохранённое значение формально удержано провенансом |

Что это значит:
- Для L1 effective берётся из глобального PG (`source=global`), PG-запись обновлена на деплое (05:53:24Z) и **байт-в-байт равна заводскому канону**.
- Для L2 сохранённое PG-значение **уже равно новому канону**, но реестр не считает его «аттестованным» (`provenance_unavailable`) и удерживает, отдавая заводскую редакцию. Байты совпадают, поэтому на ответ это не влияет; важна семантика: `PG-only rollback для L2 — no-op` подтверждён, действует factory.
- Предыдущая запись `arch-audit §2` про `stored_sha=be03964322aa` устарела: на 2.58.113 stored sha = `d1b210c156c8`, т.е. PG был приведён к новому канону при boot-миграции.

## 3. Per-chat overrides

| Чат | Документ `chat_profiles.chat_params` | Overrides этих двух ключей | Прочие prompt-overrides |
|---|---|---|---|
| `-1002661910336` | есть, 26 overrides | **нет** | `prompts.summary_cover_style`, `prompts.summary_cover_style_id`, `prompts.summary_system_prompt`, `prompts.verbilizer_default_mode` |
| `-1004482340693` | есть, 3 overrides | **нет** | нет prompt-ключей |

- Override L1/L2 для обоих чатов отсутствует — перетирать нечего.
- Read-path Direct L1/L2 для этих ключей **глобальный**: `resolve_prompt()` → `hot.get()` без `chat_id` (подтверждено на дереве `e4ee54f3`: `services/prompt_style_blocks.py`, вызовы `services/direct_chat_service.py` для L1 и L2). Даже появившийся chat-slot не попал бы в Direct payload без смены кода.

## 4. Effective payload: уточнения

Проверено на **эффективных байтах прода** (6542 / 2827) и на функции сборки плана деплойнутого коммита `e4ee54f3` (`services/direct_l1.py:build_l2_plan_block`).

| Проверка | Факт |
|---|---|
| Контракт «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА» в L1 | ровно **1** вхождение |
| Старый императив «Ничего кроме вопроса не пиши» | **отсутствует** (L1 и L2) |
| Директива claim-envelope «Если без уточнения ответ может быть не о том» | **отсутствует** в L1 |
| Маркер `clarify=ask` в L1-каноне | **отсутствует**; код `_l1_speech_hints` подаёт только `clarify=assume` |
| Правило §4.2 в L2 («Вместо ответа задавай один конкретный уточняющий вопрос…») | ровно **1** вхождение |
| §4.3-директива в L2 system-каноне | **отсутствует** (она живёт только в `<Response_Plan>` при валидном плане) |

Сборка `<Response_Plan>` (реальные выходы функции на проде):

| Случай | «смысловой акт: clarification» | «недостающий предмет» | §4.3-директива | chars |
|---|---|---|---|---|
| `needs_clarification=false`, target пуст | нет | нет | **нет** | 77 |
| `response_act=clarification`, но `needs_clarification=false` | **нет** | нет | **нет** | 48 |
| `needs_clarification=true`, target=`media_target` | да | да | **да** | 439 |
| `needs_clarification=true`, target пуст | **нет** | нет | **нет** | 48 |

Вывод: второго приказа уточнять нет; §4.3 доходит до модели **только** при непустом target. При `false`/пустом target модели не уходит ни акт `clarification`, ни директива.

Ограничение (честно): **платного вызова L1 не делалось**. Доказательство — эффективные байты прода + фактический выход функции сборки плана на деплойнутом коммите; system-сообщение L1 — это ровно эффективный канон (`direct_chat_service.py`, `resolve_prompt(...)` → `messages[0]`), без второго system-промпта.

## 5. Статистика уточнений за 7 дней

| Метрика | Значение |
|---|---|
| `llm_usage_events`, `direct_chat/l1_planner` | **384** вызова |
| Из них с `plan_meta` | **324** |
| `plan_meta` содержит `needs_clarification` / `clarification_target` | **нет** (whitelist: action/response_act/extent/tone/bucket/confidence/capabilities/tools/inherited/fallback/latency_ms/input_chars/model/source/execution_mode/credential_source/…) |
| `needs_clarification=true` за 7 дней | **not_instrumented** |
| Ложные уточнения по follow-up | **not_instrumented** |
| Цепочки >1 уточнения | **not_instrumented** |

Доступный прокси (не равен `needs_clarification`): `response_act=clarification` — **46 из 324** строк с `plan_meta` (14.2%). Это выбранный L1 смысловой акт ответа, а не флаг технического уточнения; смешивать нельзя. 60 вызовов L1 без `plan_meta` — до/вне durable-инструментации.

Чтобы получить настоящую статистику, нужна аддитивная ось в `plan_meta` (например `needs_clar` bool + `clar_target_present` bool, R17-safe). Это изменение продукта/инструментации → Builder/Reviewer, не DevOps-фикс.

## 6. Что закрывает этот снимок

| Строка карты | Статус после снимка | Основание |
|---|---|---|
| `MIGR-INSPECT` | **можно VERIFIED** | factory/active/effective + overrides по обоим ключам, §2–§3 |
| `MIGR-EFFECTIVE` | **можно VERIFIED** | active PG обновлён; L1 effective=global; L2 effective=factory (withheld, PG-only rollback no-op), §2 |
| `MIGR-PAYLOAD` | **можно VERIFIED с оговоркой** | §4: нет второго приказа, §4.3 только при target; платного L1-вызова не было |
| `MIGR-BOTHSIDES` | **можно VERIFIED** | factory == active == effective на самом сервере; оба односторонних состояния исключены, §2 |
| `MIGR-DEVOPS` | **можно VERIFIED** | деплой 2.58.113 (`deploy.md`) + этот postdeploy-снимок конфигурации, health, rollback |
| `DONE-D4` | **можно VERIFIED** | effective L1/L2 соответствует новым канонам ASAP 2, §2/§4 |
| `DONE-D9` | **можно VERIFIED** (live postdeploy) | deploy+health+effective+payload; статистика честно `not_instrumented`, §5 |

Не закрывает: `MIGR-HOTAPPLY` (hot apply правки промпта в UI не проверялся), `MIGR-REVISION/OWNER/NORESET` — вне этого лейна.

Карта и `workflow_state.md` **не редактировались** (вне write scope). Обновление строк и `requirements_gate.py check --stage release --candidate e4ee54f3 --deployed-commit e4ee54f3` — за Orchestrator/PM.

## 7. Находки

1. **LOW (наблюдаемость):** `needs_clarification` не попадает в durable `plan_meta`, поэтому частоту/ложность уточнений на проде измерить нельзя. §5. Отдельная задача Builder/Reviewer.
2. **LOW (провенанс L2):** сохранённое значение L2 удерживается (`provenance_unavailable`) при байтовом совпадении с factory. Поведение корректное, но Inspector будет показывать «Factory» при формально записанном PG-значении — это ожидаемая семантика провенанса, не дефект.
3. **INFO (процесс):** сервис перезапускался после деплоя (MainPID 715288 → 726282). Текущий старт здоров, версия та же.
