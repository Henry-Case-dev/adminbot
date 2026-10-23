# ASAP2 — привязка read-only снимка прода 2.58.113 к карте требований

**Лейн:** `PM-BIND-ASAP2-PROD`, 23.10.2026 (локально, UTC+12).
**Снимок:** `evidence/prod-snapshot/report.md` (sha256 `278f281cf55e30d9dde699d9d23d29d7a7874f0880cb7c6744826c9a5c24dd8e`), сырой вывод `evidence/prod-snapshot/raw-snapshot.json` (sha256 `cb10387ec0055b11c822df2c14dc019d0b53aac53d9b398e09408ed344210448`), скрипт `probe.py`.
**Прод:** `2.58.113` @ `e4ee54f3` (HEAD == master). Прод в этом лейне не трогался: SSH не выполнялся, файлы читались только из репозитория.
**Карта:** `plans/features/asap2-direct-chat/requirements-map.json` (`candidate_commit=deployed_commit=e4ee54f3`, `strict_evidence=true`).

## Итог привязки

| Строка | Было | Стало | Основание |
|---|---|---|---|
| `MIGR-INSPECT` | PENDING | **VERIFIED** | factory/active/effective + per-chat overrides по обоим ключам, read-path глобальный (§2–§3) |
| `MIGR-EFFECTIVE` | PENDING | **VERIFIED** | L1 effective=global PG; L2 effective=factory при withheld, байты совпадают, PG-only откат L2 = no-op (§2) |
| `MIGR-BOTHSIDES` | PENDING | **VERIFIED** | factory == active == effective на сервере, оба односторонних состояния исключены (§2) |
| `MIGR-DEVOPS` | PENDING | **VERIFIED** | деплой/health/rollback/backup (§1) + `release-258113/deploy.md`, ΔDDL=0 |
| `DONE-D4` | PENDING | **VERIFIED** | effective = новые каноны, owner edits учтены честно, rollback возможен (§2, §4) |
| `DONE-D9` | READY_FOR_LIVE | **VERIFIED** | postdeploy: deploy+health+effective+демонстрация payload; статусы DEPLOYED/TESTED разделены, `LIVE_VERIFIED` не заявлен (§1–§4) |
| `MIGR-PAYLOAD` | PENDING | **PENDING** | эффективные байты и выход `build_l2_plan_block` доказаны, но полный model payload и платный вызов L1 не снимались (§4, честное ограничение) |
| `MIGR-HOTAPPLY` | VERIFIED | **PENDING** | hot apply правки промпта в живом процессе не наблюдался (§6 прямо это исключает); in-process резолв доказан только T34 |
| `MIGR-REVISION` / `MIGR-OWNER` / `MIGR-NORESET` | VERIFIED | **VERIFIED** | добавлены производственные основания (§2, §3); остаточная граница — история `prompt_migrations` на проде не перезапрашивалась (SSH-бюджет) |
| `DONE-D6`, `TESTS-METHOD-REAL/PARAPHRASE/SCREENSHOT` | PENDING | **PENDING** | прод-статистика `needs_clarification` = `not_instrumented`; закрывать только прогонами сценариев |

Требования: **109 required → 79 VERIFIED / 30 PENDING / 0 READY_FOR_LIVE**.

## Откуда именно берутся промпты на проде (§2)

| Ключ | Factory | Active PG | Effective | Вывод |
|---|---|---|---|---|
| `prompts.direct_l1_planner_system_prompt` | `c987c03e…748c`, 6542 | тот же | тот же, `source=global` | действует PG-запись, она равна заводскому канону |
| `prompts.direct_chat_verbalizer_system_prompt` | `d1b210c1…1b42`, 2827 | тот же | тот же, `source=default`, `withheld=true` (`provenance_unavailable`) | действует заводская редакция; сохранённое значение удержано провенансом |

Следствия, которые важны для будущих правок:

1. Правка только Python-константы без active PG не изменит L1 (effective берётся из PG).
2. Правка только PG без константы/реестра не изменит L2 (значение удерживается провенансом) — и «PG-only откат» для L2 является no-op.
3. Per-chat override этих двух ключей на проде отсутствует; read-path Direct L1/L2 не читает chat-slot (`resolve_prompt` без `chat_id`), поэтому даже появившийся chat-slot не попадёт в payload без смены кода.

## Что снимок НЕ доказывает (не выдавать за успех)

1. **Полный model payload / факт вызова L1.** Доказано: эффективные байты прода (6542/2827) — это ровно то, что уходит как system-сообщение, и реальные выходы `build_l2_plan_block` на деплоированном коммите (77 / 48 / 439 / 48 симв.; §4.3 только при `needs_clarification=true` + непустом target). Не доказано: снятый `messages[]` тестового маршрута и платный L1-вызов. Поэтому `MIGR-PAYLOAD` остаётся PENDING.
2. **Hot apply в живом процессе.** `MIGR-HOTAPPLY` — PENDING: правка промпта через Inspector → effective без рестарта не наблюдалась; миграция при boot и отсутствие новых таблиц (ΔDDL=0) доказаны.
3. **Статистика уточнений.** `needs_clarification` не попадает в durable `plan_meta` (whitelist без этого поля): за 7 дней 384 вызова `direct_chat/l1_planner`, 324 с `plan_meta`, `needs_clarification=true` — `not_instrumented`. Прокси `response_act=clarification` = 46/324 (14.2%) **не равен** флагу и не подменяет его. Строки `DONE-D6`/`TESTS-METHOD-*` по телеметрии не закрываются.
4. **Живое сообщение в чате.** В чаты ничего не отправлялось (PET_PROJECT: личные device/live-наблюдения владельца добровольны и не являются гейтом). `DONE-D9` подтверждён как набор артефактов (commit, тесты, демонстрация effective payload, deploy/rollback/health), а не как `LIVE_VERIFIED` в смысле наблюдения ответа в чате.

## Release-гейт

```
py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check \
  --map plans/features/asap2-direct-chat/requirements-map.json \
  --stage release --candidate e4ee54f3 --deployed-commit e4ee54f3
→ stage=release inventory=71 manual=74 scoped=109 errors=30, EXIT 1
```

Все 30 ошибок — `mandatory not ['VERIFIED'] (got PENDING)`, то есть только реально незакрытые строки; структурных ошибок (evidence/artifact_sha256/candidate/live-evidence/graph) нет.

Остаток (30): `T10, T11, T14, T17, T18, T20, T22, T24, T26` (9 сценариев без живого прогона), `CLAR-L1-PRINCIPLE, CLAR-L1-PRIOR, CLAR-L1-CONTINUATION, CLAR-CTX-HONEST, CLAR-L2-NOMENU, CLAR-L2-ROLE, CLAR-L1-DIST2…DIST5, CLAR-PLAN-ONETARGET` (11 семантических/структурных), `DONE-D1, DONE-D5, DONE-D6, DONE-D8, DONE-REPORT` (5), `TESTS-METHOD-REAL, TESTS-METHOD-PARAPHRASE, TESTS-METHOD-SCREENSHOT` (3), `MIGR-PAYLOAD, MIGR-HOTAPPLY` (2).

## Backlog из снимка (не новые требования карты)

1. **Наблюдаемость:** добавить в `plan_meta` аддитивную ось `needs_clar` (bool) + `clar_target_present` (bool), R17-safe (без текста), чтобы частоту и ложность уточнений можно было измерять в проде. Задача Builder/Reviewer.
2. **Провенанс L2:** Inspector показывает «Factory» при формально записанном PG-значении (`provenance_unavailable`) — ожидаемая семантика провенанса, не дефект; решать только если появится требование показывать «stored, withheld».

## Оговорка о процессе

`arch-audit §2` содержал `stored_sha=be03964322aa` для L2 — на 2.58.113 stored = `d1b210c156c8` (PG приведён к новому канону boot-миграцией). Расхождение зафиксировано в наблюдении `MIGR-INSPECT`; сама arch-audit как исторический документ не переписывалась.
