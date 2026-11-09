# REL-258122 — прод-деплой 2.58.122 (Core-patch wire + P0 каноны)

Дата/время (UTC): рекон `01:46:11Z`, рестарт `01:46:27Z`, подтверждение `01:47:53Z`,
повторный рестарт (идемпотентность) `01:49:10Z`.
Сервер: `racknerd-f4e3456` (`198.46.175.136`), приложение `/var/www/admin_bot`.

## DEPLOY_SOURCE

| Параметр | Значение |
|---|---|
| Кандидат (код) | `c128675a` — bump 2.58.121 → 2.58.122 на `324868f0` (Core-patch wire B1) |
| Tip релиза в origin | `a43675f6` (docs/evidence REL-258122, `origin/master`) |
| Прод до деплоя | `9ed68ee8` (2.58.118), healthz 200, MainPID 858447, NRestarts 0 |
| Прод после деплоя | `c128675a` (detached), `APP_VERSION="2.58.122"` |
| Деплой-режим | `git fetch origin master` + `git checkout -fq c128675a` + `sudo systemctl restart admin_bot` |
| `MUTABLE_WORKTREE_REQUIRED` | **yes** (меняется HEAD `/var/www/admin_bot`); `TRACKED_DIRTY=0` до и после, untracked=13 (pre-existing) |
| Rollback-указатель | ветка `release/fix-2.58.121` = `999e547a` создана и запушена в origin |

## Результат

| Проверка | Наблюдение |
|---|---|
| HEAD / версия | `c128675a6a1294c657f13149994b6424b6fae539`, `2.58.122` |
| Сервис | `active`, MainPID **953134** (после 2-го рестарта), NRestarts **0**, ExecMainStatus ok |
| healthz | `{"status":"ok","version":"2.58.122"}` — HTTP 200 (оба замера) |
| ΔDDL | **0**: в диффе `9ed68ee8..c128675a` нет `CREATE/ALTER/DROP/ADD COLUMN`; `user_version` **37** до и после |

## Каноны (P0)

| Ключ / артефакт | Факт на проде |
|---|---|
| `factory_set_fingerprint()` | **`47f0d1eb8de4`** ✔ |
| `checkup.base.system` (factory) | **`0f5fb7b8d25c`**, 3210 c ✔ (в PG `prompts.checkup_system_prompt` = `ed50299b0f57`, 2352 c, `withheld`) |
| Эффективный checkup system | source=**default (factory)** → `0f5fb7b8d25c` ✔ |
| Expression FREQUENT | ladder `prev fcfcf6fcea09 → next 4b4100524a22` ✔ (код-константа, PG-ключа нет) |
| L1 / L2 / direct tool phase | L1 `92428c51110d` (global, активна); L2 и direct — `withheld` → factory (`83ff62bbee40`, `f30c6d73da82`) |
| Withheld | **11** записей, все `class=unclassified`, `reason=provenance_unavailable`; ни одна не активирована, PG-байты не перезаписаны |

Миграция канонов на старте: `[prompt_migration] уже новый канон` (direct L1/L2, direct_chat,
compress, factcheck_analyst, summary_l1_clusterizer, summary_narrator) и
`кастом юзера — НЕ трогаем` для остальных; `prompt_rollback`=0. Т.е. PG-значения не переписаны,
эффективные каноны = заводские 2.58.122.

## Core patch (B1)

- Шаг миграции в журнале старта: `[prompt_migration] core patch: добавлены абзацы | key=character.core |
  added=Как говорить о реальных событиях.,Свобода речи. | removed=0 | chars=1995->3294 | sha=3de4884f29ce->ead77b2ab509`.
- Активная редакция: `revision 7 → 8`, `detail_level=full` (не переключён), оба абзаца присутствуют.
- Авторские байты: вычитание двух вставленных абзацев даёт **исходный текст дословно**
  (`AUTHOR_BYTES_RESTORED=True`, 1995 c); `owner_preserve_core_full_patch(pre) == post` — правка
  ровно та, что задумана.
- История: `character.prompt_history` записей **4** (append-only), запись провенанса выполнена.
- Повторный рестарт (01:49:10Z): `core patch: абзацы уже есть, авторские байты целы`, sha не изменился
  (`ead77b2ab509`), ревизия осталась 8 — **дублирования нет, шаг идемпотентен**.

## Embedding / adopt

- `ADOPTED`=**0**, `BUILD_START`=**0**, `prompt_rollback`=**0** → adopt не повторялся, перестройка не запускалась.
- `mca_embedding_index_generations`: `graph_facts_vec` gen1 `96f80838f683…` **active**;
  `smart_archive` gen1/gen2 `building` (FTS-only, pre-existing; в журнале
  `embedding generation not serviceable | index=smart_archive | status=building`) — как в 2.58.118.

## Checkup / Style / B11

- Фактический checkup system (эффективный) содержит «СУТЬ АНАЛИЗА» дословно ✔, вхождений «строчн» — **0**
  (требования строчной буквы нет), упоминание Style Policy — 1 ✔.
- Style Policy применяется **на выходе**: `services/checkup_service.py::_apply_outbound_style` →
  `style_policy.apply_style_policy` (прод-код 2.58.122); документ `style.policy` в PG на месте (3525 c).
- B11 (`tools/v63_b11_mechanisms_report.py`, read-only): `B11_RC=0`, `not_green_rule` на месте;
  Summary scheduler — «последняя попытка деградирована (резервный контур)», **не зелёный**;
  также не зелёные graph_memory, embeddings, experience. Ложного `ok` нет.

## Журнал с момента старта (два замера)

`CRITICAL`=0, ` ERROR `=0, `Traceback`=0, `database is locked`=0, `ADOPTED`=0, `BUILD_START`=0.
WARNING — только известные: `кастом юзера — НЕ трогаем` (миграция канонов) и
`embedding generation not serviceable (smart_archive, pre-existing)`.

## Бэкап и откат

- Бэкап перед деплоем: `~/deploy-258122/bot_settings_pre.json` (537 строк `bot_settings`, включая
  `character.core` rev7 и все каноны) — полная точка восстановления промптов.
- ΔDDL=0, схема не менялась (`user_version` 37).
- Откат кода: `cd /var/www/admin_bot && git checkout -fq 999e547a && sudo systemctl restart admin_bot`
  → healthz 2.58.121. Коммит `999e547a` уже в объектной базе сервера (предок задеплоенного `c128675a`),
  указатель `release/fix-2.58.121` запушен в origin.
- Откат Core-патча (если потребуется отдельно): прежняя редакция лежит в `character.prompt_history`;
  вырезание абзацев автоматически не делается (REQ-CORE-KEEP-VOICE).
- Стек канонов Checkup: `CHECKUP → PREV_CHECKUP_P0 → PREV_CHECKUP_CFG07A` (2 ступени сохранены);
  Expression: `rollback_profanity_frequent_text() == PREV` (`fcfcf6fcea09`).

## Дисциплина SSH

3 подключения одним логином `nik`, интервалы >60 с (01:46:11Z → 01:47:53Z → 01:48:53Z), без ретраев
и поллеров, один пароль-вход на коннект. Fail2ban-триггеров нет.

## Находки (не блокируют деплой)

1. **Withheld в проде = 11, все `unclassified / provenance_unavailable`** (не «8 legacy_incompatible»).
   Провенанс-записи для этих ключей в PG отсутствуют, поэтому класс не определяется; поведение
   безопасное (значения не активируются, заводские каноны действуют), но фактическое число и класс
   расходятся с описанием в ревью 2.58.121 — нужна сверка Reviewer/PM с фикстурами.
   Следствие для владельца: его собственные редакции Summary/Checkup/Factcheck/L2/direct в проде
   **не действуют**, вместо них заводские (pre-existing с 2.58.118, не регрессия поезда).
2. **Release-gate красный по карте P0**: `requirements_gate.py check --stage release
   --candidate c128675a --deployed-commit c128675a` → `stage=release inventory=202 manual=179
   scoped=295 errors=591`, `candidate_commit` в карте пуст, все позиции `PENDING`. Это PM-работа
   (B2 из `release-258121/review-rel.md`), не дефект деплоя; финальный `DONE` без неё невозможен.

## Вердикт

**Деплой VERIFIED, релизная приёмка BLOCKED (карта P0 не привязана к кандидату).**
Прод на `c128675a` / 2.58.122, сервис здоров, FACTORY_SET `47f0d1eb8de4`, Checkup и Expression
каноны эффективны, Core-патч применён ровно один раз с сохранением авторских байтов и без
дублирования на повторном рестарте, adopt/перестройка не повторялись, журнал чистый. Откат готов
(`999e547a`). Живых чат-проб в реальные чаты не отправлялось (нет отдельной авторизации).

Сырые выводы замеров: `raw/phase1.out` (recon+деплой), `raw/phase2.out` (первый postcheck),
`raw/phase3.out` (повторный рестарт + probe + B11).
