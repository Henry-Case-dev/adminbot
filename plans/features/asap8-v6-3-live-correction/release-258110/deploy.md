# Deploy 2.58.110 — VERIFIED @ a8d2a45a

LANE: DEVOPS-DEPLOY-258110 · Release review: REV-REL-258110 **Approved**
(`release-258110/review-rel.md`) · Дата деплоя: 2026-10-22, T0 = 07:26:20Z (epoch 1792653980).

## Состав и источник

Поезд 2.58.110 — канонная эволюция L1-планера (INITREPLY-L1D): новый канон
с полями формы участия `delivery/target_*` (FACTORY_SET `c19d35a1c093` →
`3507bd6f92eb`), ступень лестницы `PREV_DIRECT_L1_PLANNER_1022`, транспорт
исполняет решение L1 (`_execute_initiative_react`, планерный
reply_to_message_id, резолвер-эвристика 2.58.109 удалён) + tails-биндинги
+ bump. Runtime-дельта a1d8bd62..a8d2a45a = ровно 7 файлов
(`config/settings.py` + 6 сервисов); web/handlers/migrations — 0;
ΔDDL = 0 (`services/database.py` b7fdd7615a52 без изменений, schema v37).

- **DEPLOY_SOURCE**: `origin/master @ a8d2a45a` (запушен до деплоя);
  на сервере `git fetch` + `git checkout -B master origin/master`.
- **MUTABLE_WORKTREE_REQUIRED**: no (fetch+checkout+рестарт; на сервере
  tracked_mod=0 после checkout).
- Откат: ветка `release/fix-2.58.109` = `a1d8bd62`, создана и запушена в
  origin **до** деплоя; сервер подтвердил `origin/release/fix-2.58.109`
  == a1d8bd62 (RB_IS_ANCESTOR=1). Процедура: `git checkout -f a1d8bd62` +
  `sudo systemctl restart admin_bot`. DDL-реверса не требуется. Нюанс
  канон-отката — в review-rel.md (неблокирующее замечание 1), отражён в
  deploy.json.

## Плановый рестарт — обязательный (одобрен ревью)

FACTORY_SET — runtime-константа процесса + лестница стартовой канон-миграции
(прецедент 2.58.107). Выполнен один раз в T0: stop PID 434185 → старт
07:26:29 UTC PID 447331, **NRestarts=0**, ExecMainStatus=0.

## Верификация (сервер-наблюдаемая)

| Проверка | Результат |
|---|---|
| Прод-HEAD после checkout | `a8d2a45a`, tracked_mod=0 |
| healthz loopback:8000 | 200 `{"status":"ok","version":"2.58.110"}` |
| healthz внешний 443 (admin-bot.duckdns.org) | 200 `2.58.110` |
| Сервис | active/running, MainPID=447331, **NRestarts=0**, старт 07:26:29 UTC |
| Runtime-хэши (sha256_12) | все 7 == кандидату (settings `7595eed634c5`, chat_prompts `f19c6e9c731b`, direct_chat `c992071e0aa8`, direct_l1 `5617571078a2`, initiative_observer `cd85479553a9`, prompt_migrations `4ba3e6ad08ac`, prompt_registry `0deee316c723`; README `138dddf5106f`, database `b7fdd7615a52`) |
| Git blob (sha1_12) | все 6 сервисов + settings — 1:1 с кандидатом |
| Финальная сверка (07:32:16Z, отдельный коннект) | sha+blob 6 сервис-файлов == кандидату; `/healthz` 200, `/web/` 200, index `v=2.58.110` ×15 |
| Маркеры | APP_VERSION "2.58.110" ×1; F8-meta `7a358c2c` ×1; константа `3507bd6f92eb` ×2; PREV_1022 в chat_prompts ×2 / prompt_migrations ×3; `_execute_initiative_react` ×3 |
| Журнал с T0 | 0 CRITICAL / 0 ERROR / 0 RuntimeWarning; **1 Traceback — классифицирован** (см. «Инциденты») |

## Канонная лестница L1D (postdeploy §8 ревью — выполнено)

1. **Журнал старта** 07:26:44 UTC: `[prompt_migration] канон обновлён |
   key=prompts.direct_l1_planner_system_prompt` — ступень
   PREV_DIRECT_L1_PLANNER_1022 → новый канон сработала. Всего 16 строк
   миграций, 0 ошибок: 12× «кастом юзера — НЕ трогаем» (все 7 целевых
   CFG07A-ключей среди них; ещё 5 — кастомы прежних раундов) + 3× «уже
   новый канон».
2. **Fingerprint-проба (read-only, venv)**: константа == computed ==
   **3507bd6f92eb** — процесс реально загрузил новый канон-набор.
   Замороженные байты PREV_1022 целы (5fdc90b3f1143abe / 3022).
3. **7 кастомных ключей владельца**: SELECT-сверка sha256_12+len против
   замера 2.58.101 (подтверждён live 2.58.107) — **7/7 EQ_BASELINE**,
   хранимые байты не тронуты.
4. **Effective/PG-проба**: значение `prompts.direct_l1_planner_system_prompt`
   в PG после старта = **новому канону байт-в-байт** (sha16 `ace6246bd360…`,
   4264 символа; было 3022), маркеры delivery/target_* присутствуют,
   правила 2–3 (react/silent) целы. Fingerprint кода PG-миграцию не
   доказывает — доказан SELECT (рекомендация ревью выполнена).

## Live-наблюдение L1D (по плану, НЕ гейт)

Первое живое решение пришло само, в окно деплоя: 07:28:11 UTC реальное
сообщение владельца (msg 3472, trigger reply_to_bot) → **L1_PLAN**
`{action=react, response_act=banter, extent=one_word, tone=playful,
confidence=0.7}` → DIRECT_REACT 💀 (source=l1_planner) → исполнение.
Телеграм отклонил эмодзи (`REACTION_INVALID`) → fail-soft
`outcome=unavailable` зафиксирован. Цепочка «L1 решает → транспорт
исполняет» работает live. Живой случай `delivery=reply` в окно не
поступал — распределение форм = 48ч телеметрия L1_PLAN (не гейт).
Сообщений в реальные чаты деплой не отправлял (PET_PROJECT-правило).

## Инциденты

- **INC-258110-REACTION-INVALID** (low, L1D react path): планер выбрал 💀,
  недопустимый в чате → Telegram `REACTION_INVALID` → WARNING + fail-soft,
  процесс жив (NRestarts=0). Риска нет; продуктовый нюанс «валидность
  эмодзи-реакции» — кандидат в 48ч наблюдение. @Orchestrator как
  наблюдение, не блокер релиза.

## SSH-дисциплина (fail2ban)

5 коннектов, одиночный nik, паузы ≥100 с, без поллеров/ретраев:
recon 07:24:05Z → main-деплой 07:26:13Z → final 07:29:30Z (байты/сервис OK;
SFTP-пробы не запустились из-за порядка rm в скрипте — ошибка инструмента,
не прода) → final-fix 07:32:16Z (пробы fingerprint/L1-PG/кастомы OK) →
журнал-трейсбек 07:34:2xZ. HTTP/443-пробы — с локальной машины. Секреты не
печатались и в evidence не попали.

## Release gate

`requirements_gate.py check --stage release --candidate a8d2a45a
--deployed-commit a8d2a45a` → exit 1 (`release-258110/release-gate.txt`).
Задокументированный legacy-класс (release-25883/258105/258109): строки
openworkflow-coverage-v1 карты привязаны к историческим кандидатам волн,
ребиндинг запрещён review-tailbind; map `candidate_commit` остаётся
`d87284c1` (ревью-биндинг среза INITREPLY-L1D, гейт EXIT 0 в REV-REL-258110).
Поезд-левел биндинг = REV-REL-258110 Approved + deploy evidence,
привязанная к задеплоенному коммиту; `deployed_commit` карты обновлён
на a8d2a45a.

## Итог

Деплой 2.58.110 VERIFIED @ a8d2a45a. Канонная лестница L1-планера
применена, кастомы владельца целы, откат-состояние известно и проверено.
Блокеров доставки нет. Открыто (не гейт): 48ч телеметрия форм участия +
наблюдение REACTION_INVALID.
