# REL-258118 — прод-деплой 2.58.118 (VERIFIED)

Дата/время: 2026-10-23, T0 UTC 17:51:21Z (рестарт 17:51:27Z), подтверждение 17:54:01Z.
Сервер: `racknerd-f4e3456` (`198.46.175.136`), приложение `/var/www/admin_bot`.

## DEPLOY_SOURCE

| Параметр | Значение |
|---|---|
| Код (кандидат) | `9ed68ee8` — bump 2.58.117 → 2.58.118 |
| Tip релиза (docs) | `092e5e63` — evidence + bump |
| Родитель кандидата | `47ed033e` (limits review r2, cherry-pick `849eeed9`) |
| Прод перед деплоем | `724b77ac` (2.58.117), healthz 200 |
| Прод после деплоя | `9ed68ee8` (detached), healthz 200 / 2.58.118 |
| Деплой-режим | `git fetch origin master` + `git checkout -fq 9ed68ee8` |

`MUTABLE_WORKTREE_REQUIRED: yes` — деплой шёл через изменение HEAD рабочего дерева
`/var/www/admin_bot`. Записи других файлов нет: `TRACKED_DIRTY=0` до и после,
новых untracked-файлов деплой не создал, `plans/` не тронут (root-owned файлов не было,
chown не потребовался).

## Результат

| Проверка | Наблюдение |
|---|---|
| HEAD на проде | `9ed68ee8`, `APP_VERSION="2.58.118"`, tree чистый |
| Сервис | `active`, MainPID **858447**, NRestarts **0**, ExecMainStatus 0 (два замера) |
| healthz | `{"status":"ok","version":"2.58.118"}` — 200 в T0 и в 17:54:01Z (502 только на тиках 1–2 прогрева, тик 3 = 200) |
| ΔDDL | **0**: в диапазоне `724b77ac..9ed68ee8` менялись только `README.md`, `config/settings.py` (версия), `services/direct_chat_service.py`, тесты и `plans/**`; `user_version` **37** до и после |

## Каноны и промпты (без изменений)

PG `bot_settings`, `sha12` до/после — **идентичны**:

| Ключ | sha12 | known_canon |
|---|---|---|
| `prompts.direct_l1_planner_system_prompt` (L1) | **6c2ddc17c998** | True |
| `prompts.direct_chat_verbalizer_system_prompt` (L2) | **83ff62bbee40** | True |
| `prompts.direct_chat_system_prompt` | f30c6d73da82 | True |
| `prompts.direct_chat_synthesizer_system_prompt` | 6bae7eb26bc3 | True |
| fingerprint `factory_set_fingerprint()` | **0163a686c401** | — |

`prompt_migration`=17 в журнале старта — это только `уже новый канон` / `кастом юзера — НЕ трогаем`;
фактических миграций и `prompt_rollback` (**0**) нет. Повторной миграции не было.

## Embedding / adopt

- `ADOPTED`=**0**, `BUILD_START`=**0** → adopt не повторялся, перестройка индекса не запускалась.
- `mca_embedding_index_generations` до/после совпадает построчно:
  `graph_facts_vec` gen1 `96f80838f683e1cb` `active` (adopt1:…:12:1.00);
  `smart_archive` gen1/gen2 `building` (FTS-only, pre-existing, durable job отсутствует).
- Счётчики не изменились: `graph_facts`=20207, `graph_facts_vec`=20320, eligible=15944.

## Style / B11

- `style.policy` до/после идентичен: `revision=12`, правила `emoji.hard.off`,
  `quotation_marks.hard.no_graphic`, `trailing_period.hard.strip` — все `enabled=True`,
  `hint_limits` отсутствует. `services/style_policy.py` в дельте поезда **нет** →
  dash-фабрика (`dash.hard.factory`) и стилевая семантика не менялись.
- B11 (`tools/v63_b11_mechanisms_report.py`, read-only): `B11_RC=0`,
  `ok=7 / attention=2 / unknown=1`, `not_green_rule` на месте.
  `attention`: `graph_memory`, `embeddings` («job cancelled — не успешный терминал»);
  `unknown`: `experience`. Это ровно базовый профиль 2.58.113 (`ok=6/attention=2/unknown=1/degraded=1`),
  ложного `ok` нет; `degraded` исчез. Новых деградаций поезд не внёс.

## Журнал с момента старта (два замера)

`CRITICAL`=0, ` ERROR `=0, `Traceback`=0, `database is locked`=0,
`ADOPTED`=0, `BUILD_START`=0, `prompt_rollback`=0.
`WARNING`=20 — все относятся к известным pre-existing механизмам:
`[prompt_registry] persisted speech value withheld` (provenance gate, 9 строк, включая L2
`direct_chat_verbalizer` `provenance_mismatch`) и `embedding generation not serviceable
(index=smart_archive … FTS-only, build pending — durable job missing)`.

## Бэкап и откат

- Бэкап БД **не снимался**: ΔDDL=0, поезд не меняет схему и не пишет данные
  (`config/settings.py` — только версия, `direct_chat_service.py` — логика лимитов).
  Прежний бэкап 2.58.114 остаётся схема-совместимой точкой восстановления.
- Откат проверен на проде: `git cat-file -t 724b77ac` → commit; worktree из `724b77ac`
  материализуется, `APP_VERSION="2.58.117"`; ветка-указатель `release/fix-2.58.117` = `724b77ac` создана и запушена в origin.
- Команда отката: `cd /var/www/admin_bot && git checkout -fq 724b77ac && sudo systemctl restart admin_bot`
  → healthz 2.58.117. Общая точка отката поездов 115–118: `e9f7595b` (2.58.114).

## Дисциплина SSH

2 подключения, один логин `nik`: T0 17:51:21Z и подтверждение 17:54:01Z (интервал >60 с),
без ретраев и поллеров. Fail2ban-триггеров нет.

## Вердикт

**VERIFIED.** Прод на `9ed68ee8` / 2.58.118, сервис здоров, каноны L1/L2 и fingerprint
не изменились, adopt/перестройка не повторялись, стиль не тронут, журнал без
CRIT/ERROR/Traceback/locks, откат на 2.58.117 готов.

Живых чат-проб в реальные чаты не отправлялось (нет отдельной авторизации);
поведение лимитов проверится на штатном трафике.
