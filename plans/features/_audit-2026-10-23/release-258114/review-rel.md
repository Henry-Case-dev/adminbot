# REV-REL-258114 — независимое релизное ревью поезда 2.58.114

- LANE_ID: `REV-REL-258114` (read-only; записан только этот файл)
- Дата: 23.10.2026, UTC+12
- Код-кандидат: `bd1cdc3d73a03199b02206dd5594ec2573717618` (bump 2.58.114)
- Docs-кандидат / tip ветки `release/2.58.114`: `7ca3c684` (только `plans/**`)
- База поезда: `eb3abd63` (2.58.113 + docs-привязки); прод-точка 2.58.113: `e4ee54f3`
- Worktree ревью: `C:\Code\Python\adminbot-wt258114` (tip `7ca3c684`; код идентичен `bd1cdc3d`)

## Вердикт

**Needs Fixes** — один блокер F1 (процедура отката промптов). Код-кандидат сам по себе
готов: обязательные scoped-гейты дают EXIT 0, канон-лестницы байт-в-байт совпадают с
прод-значениями 2.58.113, ΔDDL=0, guard-числа воспроизводятся. После исправления F1
(правка runbook + один dry-run, без правок кода) деплой `bd1cdc3d` разрешается как
**Approved for controlled deployment, parent not DONE**.

Родитель не `DONE`: остаются postdeploy-проверки и закрытие REPORT/DONE-строк.

## 1. Состав и provenance

`git log eb3abd63..bd1cdc3d` = **12 коммитов**: 11 черри-пиков + bump. Состав совпадает
с `train-commits.txt` / README (ASAP3 style/identity×2/UI×2/accept, ASAP2 telemetry/boundary,
Speech R3/R3b, интеграционный шов).

Проверка provenance (код-патчи, `git patch-id --stable`, без `plans/**`):

- 9 из 10 пар «исходный коммит → SHA в поезде» — **SAME**.
- `258d3fae → af7de4e9` (R3): полный patch-id отличается только из-за базовой версии
  `tests/test_asap_speech_i_matrix.py` (в поезде файл новый, полный R2+R3-вариант — это
  раскрыто в README). Пограничные патчи `services/direct_chat_service.py` и
  `services/direct_l1.py` для R3 — **SAME**; итоговый blob тест-файла совпадает с R3.
- Смысловых расхождений с отревьюженным кодом не найдено.

Ревью-покрытие:

| Блок | Артефакт | Статус |
|---|---|---|
| ASAP3 identity | `review-identity.md` → `review-identity-r2.md` | R1 Needs Fixes → **APPROVED** (A16 — postdeploy) |
| ASAP3 UI | `review-ui.md` → `review-ui-r2.md` | блокеры 1–3 закрыты, **PASS** |
| ASAP3 style | отдельного `review-style.md` **нет** | закрыто этим ревью: лимиты/бюджет/dash + 16 тестов; рекомендация — добавить артефакт |
| ASAP3 accept | builder-evidence (`acceptance.md`) | функционально проверено гейтом; REPORT-* остаются PENDING |
| ASAP2 telemetry | `evidence/review-telemetry.md` | **PASS** |
| ASAP2 boundary/T20 | `evidence/boundary-t20.md` | своё evidence; T10 — честно `not_reproduced`, postdeploy |
| Speech R3 | `evidence/r3/review.md` | **Approved for controlled deployment** |
| Speech R3b | `evidence/r3b/review.md` | код/канон **PASS**, evidence-фиксы F1/F2; F3 — postdeploy |
| Шов `667dc434` | этот файл | 1 строка fail-open + allowlist; корректно |

Неотревьюженного кода в поезде не осталось. Отдельный `review-style.md` отсутствует —
это процессный долг, а не дефект поведения.

## 2. Канон / миграция (критично) — PASS

Проверено независимо на точном кандидате:

| Проверка | Результат |
|---|---|
| `PREV_DIRECT_L1_PLANNER_CLAR` == реальный канон 2.58.113 | **да**: `c987c03e3ee0` (6542 симв.) |
| `PREV_CHAT_VERBALIZER_CLAR` == реальный канон 2.58.113 | **да**: `d1b210c156c8` (2827 симв.) |
| Прод-PG 2.58.113 (snapshot) | L1 `c987c03e3ee0`, L2 `d1b210c156c8` — **точно совпадают** |
| Новый L1 | `6c2ddc17c998` (8261 симв.) |
| Новый L2 | `83ff62bbee40` (3081 симв.) |
| `FACTORY_SET_SHA256_12` == `factory_set_fingerprint()` | **`0163a686c401` == `0163a686c401`** |
| Метки фабрики | `l1-planner-continuation-r3b`, `l2-writer-clar-boundary` |
| Изменённых ключей фабрики | **2** (`direct.base.l1_planner`, `direct.base.l2_writer`) |
| Idempotency / custom / one-step rollback | подтверждено `test_asap_speech_r3b_canon` + `test_prompt_migrations` (89 passed вместе с clar-contract/style) |

Механика boot-миграции (`migrate_prompt_canons`): при старте active PG со значением
2.58.113 совпадёт с `PREV_*` и получит новые каноны; повторный запуск — no-op; кастом
(не точное совпадение байт) не перезаписывается (WARNING). Это тот же путь, что уже
сработал на 2.58.113 (snapshot: stored sha = канон).

История: отдельной PG-таблицы истории промптов нет — `cache.set` делает upsert
`bot_settings`. Старые байты сохраняются как замороженные `PREV_*` в коде (паттерн
ADR-1013-3) и как цель `ROLLBACK_MIGRATIONS`; это проверено хешами выше.

## 3. Bump / guards

- `APP_VERSION = "2.58.114"`; bump-коммит: **31 файл** (30 код/тест + `soul-1/evidence/w4/frozen-assets.txt`),
  изменения только токена версии; нет нетокеновых правок кода.
- F8-meta HEAD = **`667dc434`** (`plans/docs/param-registry-round1025.meta.md`) = фактический pre-bump HEAD.
- ΔDDL = **0**; `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` не менялся; PG — no-op.
- Guard-числа (переиспользованы логи, выборочно перепроверены): pins24 **868/0**,
  help-sync **154**, JS-unit **39**, targets **242**, UI e2e **10 проверок**,
  compact **POST=22 / failures=0**, W4 **failures=0 (320/390/1280)**.
- Независимо прогнаны: `test_asap_speech_i_matrix.py` + `test_asap3_identity_aliases.py` — **47 passed**;
  `test_asap_speech_r3b_canon.py` + `test_prompt_migrations.py` + `test_asap2_clar_contract.py` +
  `test_asap3_style_hint_limits.py` — **89 passed**.
- Frozen UI assets: `FROZEN-ASSETS-OK` (needle-счётчики HEAD == current).

## 4. Гейты (`--stage review`, полный SHA `bd1cdc3d73a0…`)

EXIT 0 — подтверждено лично:

| Карта | Slice | scoped / errors | EXIT |
|---|---|---|---|
| ASAP3 | STYLE-LIMITS | 20 / 0 | **0** |
| ASAP3 | UI | 21 / 0 | **0** |
| ASAP3 | IDENTITY | 70 / 0 | **0** |
| ASAP2 | CLAR-PLAN | 5 / 0 | **0** |
| ASAP2 | CLAR-L2 | 4 / 0 | **0** |

Честный остаток (не блокеры деплоя; блокируют `release-stage`/`DONE`):

| Карта | Slice | errors | Что именно |
|---|---|---:|---|
| ASAP3 | ACCEPT | 8 | только `REPORT-*` (PENDING) |
| ASAP2 | TESTS | 2 | `TESTS-METHOD-REAL`, `T10-BOUNDARY` |
| ASAP2 | CLAR-L1 | 2 | `CLAR-L1-DIST4`, `CLAR-L1-CONTINUATION` |
| ASAP2 | MIGR | 2 | `MIGR-PAYLOAD`, `MIGR-HOTAPPLY` |
| ASAP2 | DONE-CRITERIA | 5 | `DONE-D1/D5/D6/D8/REPORT` |
| SPEECH | INIT-LIVE | 18 | PENDING (`T-I-COVERAGE`, `T-UI-*`, `T-GLASS-PERF`, `P0D-QUOTED`, `INIT-48H`, `EVAL-MODES`) + 4 stale |

Важно: 4 строки SPEECH (`INIT-I08`, `INIT-I09`, `INIT-TESTS`, `EVAL-EGRESS`) помечены
`VERIFIED`, но evidence привязано к `fbf9013d`/`ec359bb3`, не к `bd1cdc3d`; гейт их
законно валит. Поведение по ним покрыто R3/R3B A/B и тестами, но provenance нужно
перепривязать или понизить до PENDING (F3).

## 5. Риски

**а) Шов aliases на L1-сайте — исправлен корректно.** `667dc434` заменил
`alias_resolver=self.aliases` на `getattr(self, "aliases", None)` в инициативном L1-пути;
`alias_resolver` уже опционален, fail-open идентичен Writer-сайту. `test_i07` проходит.

**б) Allowlist `test_tool_coordinator` — законен.** Добавлена ровно запись
`services/summary_aliases.py` в набор санкционированных изменений, с NOTE и ссылкой на
identity-ревью; сама bounds-проверка не ослаблена.

**в) `T10-BOUNDARY` / `CLAR-CTX-HONEST` оставлены PENDING обоснованно.** R3B A/B показал,
что новый канон меняет ответ (T20: clarification→answer; T10: граница названа), но
прод-наблюдения ещё нет; `boundary-t20.md` честно фиксирует `not_reproduced` на старом
каноне. Закрываются postdeploy-проверкой L2 (1 сообщение + ответ L2), не требуют решения владельца.

**г) `EVAL-MODES` открыт.** occasional/frequent дали 0/3 vs 0/3 (r3) и 0/2 (r2) —
недостаточно данных; это PENDING, не блокер деплоя, нужен 48h-прогон.

## 6. Откат и блокер F1

- Точки: `eb3abd63` (2.58.113 + docs) — база; `e4ee54f3` — bump 2.58.113.
- ΔDDL=0: схемы/индексов/`user_version` нет; `plan_meta` — аддитивный JSON, старый код его игнорирует.
- Embedding-индекс не трогается: adopt не повторяется, rebuild не планируется.
- Промпты: boot-миграция меняет `bot_settings`; **PG-истории нет** (только `PREV_*` в коде).
  `rollback_prompt_canons` — ровно одна ступень: L1 → `PREV_DIRECT_L1_PLANNER_R3` (канон R3),
  L2 → `PREV_CHAT_VERBALIZER_CLAR` (2.58.113). Повторный вызов — no-op.
- **F1 (блокер):** cold-revert на `eb3abd63` **не вернёт** промпты: код 2.58.113 видит новые
  байты как кастом и оставляет их (проверено вызовом `migrate_prompt_canons` версии 2.58.113:
  `{}`, оба значения не тронуты). `rollback.md` говорит «снимает R3b, затем R3» — вторая
  ступень L1 автоматически не выполняется. Для полного возврата L1 к 2.58.113 нужно вручную
  выставить `PREV_DIRECT_L1_PLANNER_CLAR` (или добавить ступень в rollback-карту).

## 7. Обязательные postdeploy (чек-лист DevOps)

1. Рестарт: в логе `[prompt_migration] канон обновлён` для L1 и L2; stored/effective sha12 =
   `6c2ddc17c998` / `83ff62bbee40`; `PREV_*` остаются в коде; L2 `withheld` не маскирует новый канон.
2. Канон-лестницы: live L1 `l1_system_sha12 = 6c2ddc17c998`; L2 composed = `83ff62bbee40`.
3. Embedding: adopt не повторился, rebuild не запущен, `graph_facts_vec` = active; B11 — честный маркер.
4. Style: лимиты OFF → нет обрезки; частичный лимит наследует второй; `dash` активно заменяется;
   Inspector показывает `budget_excluded`/`user_limit` честно; 390/1280 без overflow.
5. Identity/aliases: смена алиаса в UI действует со следующего хода, без рестарта; чужой чат не протекает.
6. ASAP2 telemetry: в `plan_meta` есть `needs_clar` и `clar_target_present`, текста цели нет (R17).
7. Граница/продолжение: L2 один раз называет ограничение истории; ответ на уточнение продолжает
   задачу без повторного вопроса — закрывает T10-BOUNDARY/CLAR-CTX-HONEST и F3 R3B.
8. Следующий тик Summary: одна успешная публикация, без дублей; B11 не «зелёный» при сбое.
9. 48h/EVAL: `INIT-48H` — earliest 25.10.2026 13:14 UTC; `EVAL-MODES` — по накопленным прогонам.
10. Закрыть REPORT-*/DONE-*, перепривязать 4 stale SPEECH-строки, затем `--stage release`
    с фактическим deployed SHA.

## 8. Acceptance ledger (сводка)

| Область | Статус | Комментарий |
|---|---|---|
| Состав/provenance 11+1 | **VERIFIED** | 9/10 patch-id SAME; R3 delta SAME; шов проверен |
| Канон R3/R3B, лестница, идемпотентность, custom | **VERIFIED** | хеши, snapshot, 89 тестов |
| Bump/F8/guards/DDL | **VERIFIED** | 31 файл, `0163a686c401`, 868/0, 242, UI 10/POST22/W4 0 |
| Гейты STYLE/UI/IDENTITY/CLAR-PLAN/CLAR-L2 | **VERIFIED** | EXIT 0 лично |
| 4 SPEECH-строки на чужом SHA | **UNVERIFIED (provenance)** | поведение покрыто R3/R3B; перепривязать |
| T10-BOUNDARY/CLAR-CTX-HONEST, A16, B11, next Summary | **READY_FOR_LIVE** | postdeploy-чек-лист §7 |
| REPORT-*/DONE-*/EVAL-MODES/INIT-48H | **PENDING** | закрытие родителя, не деплой |
| Откат промптов L1 до 2.58.113 | **FAILED** | F1: вторая ступень не автоматическая, cold-revert не возвращает канон |

## 9. Находки

**F1 — BLOCKER (runbook/откат; правка без кода).**
`rollback.md` обещает «ROLLBACK снимает R3b, затем R3», но второй вызов — no-op, а
cold-revert оставляет оба новых канона в PG. Воспроизведение: `rollback_prompt_canons`
дважды → L1 остаётся `PREV_DIRECT_L1_PLANNER_R3`; `migrate_prompt_canons` версии 2.58.113
на новых байтах → `{}`. Минимальная правка: в runbook добавить точную процедуру полного
возврата L1 (`bot_settings` = `PREV_DIRECT_L1_PLANNER_CLAR`) и порядок «rollback канонов →
git revert»; recheck — один dry-run на копии PG. После этого деплой разрешён.

**F2 — PROCESS (не блокирует).** Нет `review-style.md`; 25 STYLE-строк опираются только на
builder-evidence. Это ревью независимо проверило лимиты/бюджет/dash и прогнало 16 тестов,
поэтому поведение принято; для истории стоит добавить короткий sign-off.

**F3 — GATE DEBT (не блокирует деплой, блокирует release-stage).** 4 SPEECH-строки
`VERIFIED` с evidence на `fbf9013d`/`ec359bb3`. Перепривязать к `bd1cdc3d` или понизить.

**F4 — POSTDEPLOY LIST (закрыто этим файлом).** В артефактах релиза отдельного
postdeploy-списка не было; §7 — обязательный чек-лист, его нужно принять как есть.