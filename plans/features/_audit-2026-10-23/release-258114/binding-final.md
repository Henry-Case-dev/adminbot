# BINDING-FINAL — карты к задеплоенному кандидату 2.58.114

- Лейн: `PM-FINAL-BIND-258114`, 24.10.2026.
- Кандидат и задеплоенный коммит: **`e9f7595bad3f56145078ad599edf4b7182d2e1df`** (код на проде, `release/2.58.114`).
- Серверное дерево: `4f64d9c730e35084dc10c377c0ad16731e13a85f` (docs-only, 0 `.py`-файлов; работающий код = `e9f7595b`).
- Предыдущая привязка: `bd1cdc3d73a03199b02206dd5594ec2573717618` (bump 2.58.114) — сохранена в `produced_on` каждой перенесённой записи evidence.
- Worktree: `C:\Code\Python\adminbot-wt258114`; исходник деплоя: `release-258114/deploy.md` (перенесён из деплой-линии без правок, sha256 `22074ee012e3e6ef17d5d22556d2e065031b1e83ef28e276b6cd86852667d5eb`).

## 1. Перенос evidence на задеплоенный кандидат

| Карта | Перенесено записей | candidate_commit | deployed_commit |
|---|---:|---|---|
| ASAP3 `asap3-corrective` | 149 | `e9f7595b…` | `e9f7595b…` |
| ASAP2 `asap2-direct-chat` | 206 | `e9f7595b…` | `e9f7595b…` |
| SPEECH `asap-speech-arch` | 118 | `e9f7595b…` | `e9f7595b…` |

Записи считаются по обоим спискам карты (`items` + `additional_requirements`); там же лежит основной объём ручных обязательств.

- Массовый carry-over: `candidate_commit` заменён на полный `e9f7595b…`, прежнее значение сохранено в `produced_on`; содержательные `observation`/`ref` не переписывались.
- `artifact_sha256` пересчитаны по текущим файлам; прежние значения сохранены в `artifact_sha256_at_produced_on`.
- Исторические полные SHA других коммитов (`fbf9013d…`, `ec359bb3…`, `0f3ed53a…`) остались в `produced_on` — это provenance прогонов, а не привязка к релизу.

## 2. GOV — ревизия диффа кандидата (локально, без прода)

Проверки по `git diff e4ee54f3..e9f7595b` (код и тесты):

| Проверка | Факт |
|---|---|
| Изменённые файлы в `services/ web/ config/ db/ tools/ scripts/ bot.py manage.py` | 19, все существующие |
| Новые файлы в `services/`, `web/`, `config/`, `db/` | 0 |
| Удалённые файлы | 0 |
| Литеральные Telegram ID (8–12 цифр) в 2077 добавленных строках | 0 |
| Имена владельца (`Папаха`, `Толян`, `529151103`) в диффе | 0 |
| ΔDDL / миграции схемы | 0 (`ddl-check.txt`, `user_version=37`) |

По этим фактам закрыты `GOV-NO-NEW-SUBSYSTEMS`, `GOV-REUSE-EXISTING`, `GOV-NO-HARDCODE`, `GOV-KEEP-PROMPTS`, `GOV-NO-HISTORY-REWRITE` (в `items`) и `GOV-NO-GLOBAL-REPLACE`, `GOV-NO-DENYLIST` (в `additional_requirements`).
Остались `PENDING`/`NEEDS_AGENT_CHECK`: `GOV-NO-NEW-LLM` (нужен замер счётчика вызовов), `GOV-KEEP-SAFETY-LIMITS` (срабатывание защитных лимитов), `GOV-NO-SIMPLIFY` (сравнение длины редакций).

## 3. Закрытие по деплою (ASAP3 `MIGRATION`/`DASH`/`HID`)

| Требование | Основание | Статус |
|---|---|---|
| `MIG-FACTORY` | код кандидата: заводские значения Style Policy (`style-phase1.md`) | VERIFIED |
| `MIG-ACTIVE` | `deploy.md` §8–10: активный документ rev12, кастомы не тронуты | VERIFIED |
| `MIG-OFF-DEFAULTS` | `deploy.md` §10: `STYLE_HINT_LIMITS_PRESENT=False` | VERIFIED |
| `MIG-DASH-FACTORY-ON` | `deploy.md` §10: синтез `dash.hard.factory`, `enabled=True` | VERIFIED |
| `MIG-INSPECTOR-DESC` | `ui-phase.md` + `review-ui-r2.md` | VERIFIED |
| `MIG-SCOPES` | нужен read-only SELECT по global/chat-документу и сверка effective | NEEDS_AGENT_CHECK |
| `DASH-DEFAULT-ON` | `deploy.md` §10 + S6 | VERIFIED |
| `DASH-CHAT-OVERRIDE` | S8 (override по chat id) | VERIFIED |
| `DASH-OUTBOUND` | S6 outbound-pass (живой отправки не было) | VERIFIED (test basis) |
| `DASH-DETERMINISTIC` | S6 + `_apply_dash` (regex, без LLM) | VERIFIED |
| `DASH-CHECK-REFLECT` | S6 check-reflect | VERIFIED |
| `DASH-PROTECTED-SEGMENTS` | S7 (URL/код/цитаты/JSON/HTML/version-literal) | VERIFIED |
| `HID-NO-SILENT-DEFAULT` | `deploy.md` §10 (OFF на проде) + 16 тестов hint_limits | VERIFIED |
| `HID-AUDIT-*`, `HID-FIELDS-6`, `HID-USER-SETTINGS`, `HID-TECH-VISIBLE`, `HID-NO-BULK-OFF`, `HID-NO-GLOBAL-EDITOR`, `HID-NO-BUDGET-BREAK` | инвентаризация лимитов не выполнялась | NEEDS_AGENT_CHECK |

`ACC-03` и `ACC-09` оставлены `READY_FOR_LIVE` с `next_check`: после деплоя не было ни одного реального исходящего сообщения и ни одного вызова `GET /api/speech/style` из TMA. Это единственный класс, который нельзя закрыть локально.
`REPORT-*` (7 строк) намеренно не закрывались — ждут финального отчёта по ASAP3.

## 4. `T10-BOUNDARY` / `CLAR-CTX-HONEST` (ASAP2)

Обе строки существуют в карте в `additional_requirements` (`MAN-T10B` / `source_line 230`, `MAN-CLAR-CTX-HONEST` / `source_line 136`) и до этого прогона стояли `PENDING`.

- **`T10-BOUNDARY`** (матрица §6.1 #10: широкий вопрос при частичном доступе к истории) — `VERIFIED` на двух независимых фактах:
  1. A/B одного payload на реальной модели (`asap-speech-arch/evidence/r3b/report.md` §3): до канона `d1b210c156c8` границы нет; после канона `83ff62bbee40` ответ прямо называет ограничение («более ранние сообщения мне не переданы»), служебная метка не опубликована.
  2. `deploy.md` §8: на проде активен именно L2-канон `83ff62bbee40` (3081, `known_canon=True`), кастомы не тронуты.
- **`CLAR-CTX-HONEST`** (честный недостаток контекста, #8/#10, без костыля-восстановителя) — `VERIFIED` по тому же A/B (граница названа честно) плюс durable-тест `tests/test_asap2_clar_contract.py:552-597` (усечённое окно не выдумывает исходную просьбу). Отдельным `req_id` граница истории не дублируется.
- Остаток честно назван: живого прод-диалога после деплоя не было (L1-вызовов 0) — это `WAITING_EXTERNAL` строки `DONE-D6` и запись `deploy.md` §12; A/B не выдаётся за e2e.

## 5. Релизный гейт

Команда: `py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --stage release --candidate e9f7595b --deployed-commit e9f7595b --repo .`

| Карта | required | VERIFIED | PENDING | READY_FOR_LIVE | errors | EXIT |
|---|---:|---:|---:|---:|---:|---:|
| ASAP3 | 234 | 187 | 44 | 3 | 47 | 1 |
| ASAP2 | 110 | 100 | 10 | 0 | 10 | 1 |
| SPEECH | 115 | 86 | 29 | 0 | 28 | 1 |

`EXIT != 0` здесь означает ровно одно: в картах остались обязательные строки без доказательства (`PENDING`/`READY_FOR_LIVE`). Механических ошибок (несуществующий коммит, отсутствующий артефакт, расхождение sha, дубли `req_id`, граф слайсов) гейт не показал — остаток состоит только из строк статуса. У SPEECH одна строка (`REQ-PROOF-EFFECT`, `verification_tier: owner_optional`, политика `plans/owner_live_checks.md`) пропускается гейтом по правилу необязательного наблюдения владельца: 28 ошибок на 29 незакрытых строк.

## 6. Остаток по классам

| Класс | ASAP3 | ASAP2 | SPEECH | Что нужно |
|---|---:|---:|---:|---|
| `CLOSE` (закрыто в этом прогоне) | 24 + 14 строк | 2 | 0 | — |
| `READY_FOR_LIVE` | 3 | 0 | 0 | реальное исходящее сообщение (`ACC-03`, `A16`); вызов style из TMA (`ACC-09`) |
| `NEEDS_AGENT_CHECK` | 23 | 4 | 17 | точные локальные/read-only проверки — перечислены в `next_check` каждой строки |
| `WAITING_EXTERNAL` | 0 | 1 | 1 | первое реальное L1-сообщение (plan_meta); фактический ответ бота в чате |
| `PENDING` (ждёт работы/отчёта) | 21 | 5 | 11 | инвентаризация лимитов, финальный отчёт, UI/Inspector-матрица, T24, tool-маршрут D5 |
| **Итого не закрыто** | **47** | **10** | **29** | |

Числа в таблице — по полю `classification` строк; они не меняют статусы карты и не выдаются за доказательство. Гейт считает только статусы, поэтому расхождение «28 ошибок / 29 строк» у SPEECH объяснено выше.

## 7. Откат и прод

- Код: `git checkout e4ee54f3 && systemctl restart admin_bot` (ветка `release/fix-2.58.113` = `e4ee54f3`, в origin).
- БД: `backups/pre_deploy_258114_20261023.db` (integrity ok).
- Каноны: `plans/features/asap-speech-arch/evidence/r3b/rollback.md` (L1 2 вызова, L2 1 вызов, 3-й no-op).
- Прод после выката: healthz 200 `2.58.114`, PID 812309, NRestarts 0; adopt не повторился (`ADOPTED=0`), generation active, `serviceable=true`.
