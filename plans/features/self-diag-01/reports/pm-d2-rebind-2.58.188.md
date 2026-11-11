# PM: перепривязка D2 на выложенный 2.58.188 `c087253d` и снятие книжных блокеров

Дата: 2026-11-11. Скоуп: только планировочные артефакты (`plans/features/self-diag-01/`), без кода,
без `progress_scope.json`, без `workflow_state.md`, без релизов и без изменений прода.

Продолжение записи DevOps `reports/deploy-2.58.188.md` и записи о выкате, зафиксированной в карте
коммитом `e214f058` (там `deployed_commit` и блок `deployment_2_58_188` уже стояли, но
`candidate_commit` и evidence оставались на принятом `02e9d301`, а граф объявлял `D2 depends_on D1`).

## 1. Привязка: почему одна привязка покрывает принятого кандидата и выложенный релиз

| Поле | Значение |
|---|---|
| Принятый и отревьюенный кандидат | `02e9d301358872a108f8094b0d3742dc0de2e741` (вердикт `REV-D2-02e9d301-01`, Approved) |
| Выложенный релиз | 2.58.188 @ `c087253dd7afdbcfa0c5ee96927324dc349627b2`, ветка `release/2.58.188` |
| Предыдущий прод / откат | 2.58.187 @ `952b9ebd4ceb113bbd687401fa8d2cb53b93a3a9` |
| Схема | `user_version=47`, DDL 0, миграций 0, флагов 0 |

Проверено PM на живом репозитории:

- все 9 файлов среза в `c087253d` **побайтово** равны `02e9d301` (blob-id: `diagnostic_policy`
  `b6e3b24a`, `output_projection` `4fcdd821`, `telegram_role_check` `093f8e10`,
  `test_diagnostic_policy` `04ee22a6`, `handlers/checkup` `6ab31598`, `services/access` `3cd71293`,
  `services/chat_keys` `748bbd3c`, `services/tool_router` `6529b512`, `web/api/access` `b2cf9941`);
- дельта `952b9ebd..c087253d`: **M=31** (5 файлов среза + 26 файлов, изменённых только номером
  версии — `APP_VERSION`/пины) и **A=4** (новые файлы среза). Побайтово идентичны 9394−31 = **9363**
  существующих пути. Цифра 9389 (9398−9) в отчёте DevOps не учитывает 26 bump-файлов;
  состав дельты среза от пересчёта не меняется;
- поведенческие наборы перепрогнаны уже на `c087253d` (`tests/test_diagnostic_policy.py` **71 passed**,
  целевой набор 519 passed / 1 предсуществующее падение, tool 392/2, log 137/1, version-пины 811/1,
  ADR-1019 116 passed; все падения воспроизведены на `952b9ebd` — новых 0).

Поэтому перепривязка evidence на `c087253d` не расширяет и не ослабляет вердикт ревью, а исторические
записи (`review_evidence`, `resolution`, `failure_history`, `slice_accounting.after_*`) не переписаны.

**Форма SHA.** `requirements_gate.py` сравнивает `--candidate`/`--deployed-commit` с полями карты как
строки. Вызов гейта задан как `--candidate c087253d --deployed-commit c087253d`, поэтому сравниваемые
поля хранятся в этой же форме; полный SHA остаётся в `deployment_2_58_188.deployed_commit` и
`candidate_binding.deployed_commit_full`.

## 2. Изменённые строки (срез D2)

| Что | Было | Стало |
|---|---|---|
| `candidate_commit` (карта) | `02e9d301…` | `c087253d` |
| `deployed_commit` (карта) | `c087253d…` (полный) | `c087253d` (форма вызова гейта) |
| `evidence[]` всех 41 записи с доказательствами | `d2-evidence-02e9d301.md`, candidate `02e9d301` | `reports/deploy-2.58.188.md` (§2 / §5), candidate `c087253d`; прежняя привязка — в `accepted_candidate_commit` + `superseded_evidence` |
| `SD1-D2-03` | `READY_FOR_LIVE` | **`VERIFIED`** + evidence `type=live` на `evidence/d2/sd1_d2_03.json` + `live_acceptance` |
| `SD1-D2-03b` | `READY_FOR_LIVE` | **`VERIFIED`** (общая приёмка, второй source_line 527) |
| `rollback_ref` живых строк | возврат на 2.58.184 @ `77a63bc5` | возврат на **2.58.187 @ `952b9ebd`** (прежняя ссылка помечена как дорелизная) |
| `SD1-AMX-08`, `SD1-AC-10`, `SD1-AC-11` | `READY_FOR_LIVE` | `READY_FOR_LIVE` (без изменений) + честная заметка `live_state_after_deploy` о том, что наблюдалось и что нет |
| `SD1-AC-14` | `READY_FOR_LIVE` | без изменений (запись о выкате уже была в `postdeploy_note_2026_11_11`) |
| `evidence_supersession` | current = `d2-evidence-02e9d301.md` | current = релизный артефакт + `live_artifact_path`; `02e9d301` добавлен в `chain` как superseded history |
| `slice_accounting` | 35 / 6 / 3 в записях | `after_deploy_2_58_188`: **37 / 4 / 3** в записях, **35 / 4 / 3** по уникальным `req_id` |

Наблюдаемые значения, на которых закрыты `SD1-D2-03` / `SD1-D2-03b` (реальный бот `PERMsoc_bot`
8802473181, проба read-only, **0 отправленных сообщений**):

- `-1004482340693`: `5885953495` и `138811255` → `administrator` → **`chat_admin`** (`source=telegram_api`);
  `350803143` → `left` → `member`; `479167456` → `TelegramBadRequest` → **`unverified`**;
- `-1002661910336`: те же аккаунты → `member` (бот в чате `administrator`, `bot_can_manage=true`);
- protected-класс `prompts`: administrator → **allow** (`allowed_chat_admin_default`), member → **deny**
  (`denied_prompt_content_member`), unverified → **unverified** (`denied_auth_unverified`).

Честные границы приёмки записаны в `live_acceptance.not_observed`: статус `creator` не наблюдался
(ни один опрошенный аккаунт не создатель этих чатов; код трактует `creator` тем же `ADMIN_STATUSES`),
ветка «бот без прав в чате» в этих чатах недостижима (эквивалентный fail-safe наблюдался на `479167456`),
живой ход бота (update → tool → ответ в Telegram) не выполнялся.

**Уточнение контекста (не дефект).** `PUBLIC_TECH`/`CHAT_SCOPED` заводски разрешены участнику
(`get_bot_health`, `read_source_code`, `inspect_runtime` → allow, `allowed_public_class_default`,
`verification=not_required`) — это ровно исполнение `SD1-AC-10`. Прежнее ожидание «участнику отказано
в `get_bot_health`» было ошибочным; оно записано в строке `SD1-AC-10` (`public_class_note`) как
неверное и не должно возвращаться как находка.

## 3. Решение по зависимости `D2 depends_on D1`

**Решение: это была сериализация, а не технический prerequisite. Жёсткое ребро снято, порядок
сохранён как `ordering`.** Тем же решением снято транзитивное `D2 → D0` (см. `dependency_decisions`
в `slice-graph.json`).

Доказательства:

1. **Пересечения по файлам нет.** D1 = `services/system_logs_fetcher.py`, `config/settings.py`,
   `bot.py`, `web/app.js`, `tests/test_checkup_logs_portable.py`; D2 = `services/roles.py`,
   `services/access.py`, `services/telegram_role_check.py`, `services/diagnostic_policy.py`,
   `services/output_projection.py`, `web/api/access.py`, `tests/test_diagnostic_policy.py`,
   `services/tool_router.py`, `handlers/checkup.py` — общих путей **0**.
2. **Реализация D1 уже в проде.** `0c6dc58d` «fix(self-diag-01): D1 — портативный локальный backend
   логов чекапа» — предок предыдущего прод-релиза `952b9ebd` (2.58.187) и выложенного `c087253d`;
   `services/system_logs_fetcher.py` в обоих одинаков, `create_subprocess_shell` и
   `CHECKUP_JOURNALCTL_CMD` в чекап-пути отсутствуют.
3. **Единственный контакт D2 с файлом D1 — уже существующий импорт**
   `from services.system_logs_fetcher import CheckupLogsUnavailableException` в `handlers/checkup.py`;
   он есть на базе `77a63bc5` и на `952b9ebd`, дельтой D2 не добавлен. Контракт не меняется.
4. **Релиз прошёл без участия D1**: 9/9 файлов среза в `c087253d` равны принятому `02e9d301`, DDL 0.

Что это **не** означает: строки D1 (17 записей) остаются `PENDING` — и это честно, у них нет
собственных доказательств (inventory по живому HEAD, портативный backend на новом VPS, сетевой trace
отсутствия Better Stack), хотя код в проде. Это отдельная книжная работа владельца слайса D1, а не
дефект D2. Если D1 начнёт менять `services/system_logs_fetcher.py`, `config/settings.py`, `bot.py`
или `web/app.js`, ребро возвращается на время этих правок как writer-сериализация.

Про D0: `d0-discovery.md` существует и совпадает с `d0_sha256` (`306c23e7…`), его потребители —
D6/AC-09 (байты промпта) и D1 (`SD1-D1-14`), а не D2; строки D0 остаются `PENDING` как отдельная
незакрытая приёмка планировочного артефакта.

## 4. Бэклог (заведено один раз)

`plans/backlog.md`, раздел «Добавлено 2026-11-11 (выкладка 2.58.188 — SELF-DIAG-01 D2, наблюдения вне
дельты)»: аккаунт `479167456` получает `TelegramBadRequest` на `getChatMember` в обоих чатах и поэтому
никогда не подтверждается как админ чата — fail-safe `unverified`, утечки нет; severity **low**;
вне дельты D2 (`reports/deploy-2.58.188.md` §7).

## 5. Гейты (дословно, запуск из корня проекта)

План-гейт:

```
stage=plan inventory=183 manual=53 scoped=0 errors=0
```

Release-гейт среза D2 (`--candidate c087253d --deployed-commit c087253d`):

```
FAIL: SD1-D2-23: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SD1-D2-24: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SD1-AMX-08: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
FAIL: SD1-AMX-09: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SD1-AC-10: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
FAIL: SD1-AC-11: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
FAIL: SD1-AC-14: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
stage=release inventory=183 manual=53 scoped=44 errors=7
```

Семь ошибок — ровно семь законно открытых строк среза, ни одной книжной:

- `SD1-AMX-09` (PENDING) — входы `inspect_runtime` (D3) и отрисованная админская поверхность (D6) ещё не существуют;
- `SD1-D2-23` (PENDING) — нет обязательного флага sensitivity при регистрации провайдера;
- `SD1-D2-24` (PENDING) — нет evidence bundle D3 и typed settings adapter;
- `SD1-AMX-08` (RFL) — нужен реальный отзыв админства в чужом чате на середине вызова;
- `SD1-AC-10`, `SD1-AC-11` (RFL) — нужен живой ход бота в реальном чате (сообщения не отправлялись);
- `SD1-AC-14` (RFL) — «ноль раскрытий» по всем маршрутам только живым перебором в чате.

## 6. Состояние D2 одной строкой

D2 выложен (2.58.188 @ `c087253d`), привязан к выложенному релизу, живая приёмка `getChatMember`
снята и закрыта (`SD1-D2-03`/`03b` → VERIFIED); остаются 3 PENDING и 4 READY_FOR_LIVE — ни одной
книжной ошибки, релизный гейт слайса красный только по ним.
