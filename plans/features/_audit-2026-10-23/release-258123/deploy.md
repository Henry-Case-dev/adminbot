# REL-258123 — прод-деплой 2.58.123 (Expression final contract в хвосте system)

Дата/время (UTC): checkout `06:58:03Z`, рестарт `06:58:16Z`, healthz 200 `06:58:36Z`,
пост-батарея `07:00:00Z` и `07:08–07:11Z`.
Сервер: `racknerd-f4e3456` (`198.46.175.136`), приложение `/var/www/admin_bot`.

## DEPLOY_SOURCE

| Параметр | Значение |
|---|---|
| Кандидат (код) | `3dfdf9cb8ecb05423e0d39d9defe8ca563cd780f` — bump 2.58.122 → 2.58.123 (31-файловый proc-set, F8-meta HEAD=`8d718a04`, deltaDDL=0) |
| Tip релиза | `6e587696` (docs/evidence REL-258123), `origin/master` = `6e587696`; кандидат — его предок |
| Прод до деплоя | `c128675a` (2.58.122), healthz 200, MainPID 953134, NRestarts 0, TRACKED_DIRTY=0 |
| Прод после деплоя | `3dfdf9cb` (detached), `APP_VERSION="2.58.123"` |
| Деплой-режим | `git fetch -q origin master` + `git checkout -fq 3dfdf9cb` + `sudo systemctl restart admin_bot` |
| `MUTABLE_WORKTREE_REQUIRED` | **yes** — меняется HEAD `/var/www/admin_bot`; tracked dirty 0 до и после, untracked 13 (pre-existing) |
| Rollback-указатель | ветка `release/fix-2.58.122` = `c128675a` создана и запушена в `origin`; на сервере объект `c128675a` присутствует (`git cat-file -t` = commit) |

## Результат

| Проверка | Наблюдение |
|---|---|
| HEAD / версия | `3dfdf9cb8ecb05423e0d39d9defe8ca563cd780f`, `2.58.123` |
| healthz | `{"status":"ok","version":"2.58.123"}` — HTTP 200 (три замера: 06:58:36Z, 07:00:00Z, 07:11Z); в окне старта 3×502 затем 200 |
| Сервис | `active`, MainPID **1014187**, NRestarts **0**, ExecMainStatus 0, ActiveEnterTimestamp 06:58:16Z |
| ΔDDL | **0** (по контракту bump-коммита); бэкап не создавался — ΔDDL=0 |

## Каноны

| Ключ / артефакт | Факт на проде |
|---|---|
| `factory_set_fingerprint()` | **`47f0d1eb8de4`**, совпадает с константой `FACTORY_SET_SHA256_12` ✔ |
| `prompts.checkup_system_prompt` | `ed50299b0f57`, 2352 c — **байт-в-байт как в 2.58.122** ✔ |
| `prompts.direct_l1_planner_system_prompt` | `92428c51110d`, 8412 c — без изменений ✔ |
| `prompts.summary_l2_writer_system_prompt` | `d268726aaa62`, 8514 c — без изменений ✔ |
| `style.policy` | `f4c6292269bf`, 3525 c — без изменений ✔ |
| `character.expression` | `ae896ff34c4c`, 275 c — без изменений ✔ |
| Миграция канонов на старте | 7× `уже новый канон` (direct_chat, direct_chat_verbalizer, direct_l1_planner, compress, factcheck_analyst, summary_l1_clusterizer, summary_narrator), 10× `кастом юзера — НЕ трогаем`; `prompt_rollback`=0 |

## Core patch

- Журнал старта: `[prompt_migration] core patch: абзацы уже есть, авторские байты целы | key=character.core | sha=ead77b2ab509`.
- PG `character.core`: оба абзаца присутствуют, **каждый ровно 1 раз** (`CORE_COUNT_P1=1`, `CORE_COUNT_P2=1`), sha и длина не менялись относительно 2.58.122 → **повторного добавления нет, шаг идемпотентен** ✔

## Embedding / adopt

- `ADOPTED`=**0**, `BUILD_START`=**0**, `prompt_rollback`=**0** → adopt не повторялся, перестройка не запускалась ✔
- `graph_facts_vec`: `embedding index serviceable | class=ADMITTED_COMPATIBLE` (generation активна и обслуживается) ✔
- `smart_archive`: `embedding generation not serviceable | status=building | gen_fp=2d0efab0e817 new_fp=2d0efab0e817 — FTS-only (A06) | build pending — durable job missing` — **pre-existing**, как в 2.58.122, не регрессия.
- `mca07_retrieval`: `outcome=skipped | reason_code=embedding_generation_changed` — следствие pre-existing smart_archive.

## Expression final contract

| Проверка | Наблюдение |
|---|---|
| Прод-код (2.58.123) | `services/prompt_composer.py`: `if expression_final: _append(parts, expression_final)` (стр. 1718–1719) стоит **непосредственно перед** `system = _joined(parts)` (стр. 1721) → блок последний в system ✔ |
| Рантайм-контракт (прод-интерпретатор) | `pytest tests/test_p0_expression_final_contract.py -q` → **15 passed**; тест утверждает `system.rstrip().endswith(final_text)`, `<Expression_Settings>` ровно 1 и **до** финального заголовка |
| `render_expression_final_contract` | `off`=106 c, `occasional`=280 c, `frequent`=464 c, `inherit`=**0** (второго регулятора нет) |
| Заголовок | `ПРАВИЛО РЕЧИ (действует поверх остальных инструкций этого сообщения):` |
| Единственный источник частоты | `FREQ_SHA=4b4100524a22` = `next_sha12` ладдера (`prev fcfcf6fcea09 → next 4b4100524a22`), квот/постпроцессора нет |

**Блок режима в конце system-сообщения L2: ДА** (код + прод-тест + рантайм-рендер; в реальные чаты ничего не отправлялось).

## Журнал с момента старта

`LINES`=262: `CRITICAL`=0, ` ERROR `=0, `Traceback`=0, `database is locked`=0.
`WARNING`=11 — все известные: 10× `кастом юзера — НЕ трогаем` (миграция канонов) + 1× `smart_archive ... status=building` (pre-existing). Неизвестных предупреждений нет.

## Откат

```bash
cd /var/www/admin_bot && git checkout -fq c128675a && sudo systemctl restart admin_bot   # → 2.58.122
```
Указатель `release/fix-2.58.122`=`c128675a` запушен в origin; коммит уже в объектной базе сервера.
Core-патч и каноны отката не требуют (данные не менялись).

## Дисциплина SSH

**4 подключения** (06:58:03Z, 07:00:00Z, 07:03:38Z, ~07:08Z), один логин `nik`, один пароль-вход на коннект,
интервалы >60 c, без ретраев после ошибок и без поллеров; fail2ban-триггеров нет.
Превышение плана (2–3) на один коннект — из-за двух ошибок механики проб: суффикс RC ломал heredoc-маркер,
и на сервере нет `python` (только `venv/bin/python`). Данные не пострадали, деплой не переигрывался.

## Находки (не блокируют деплой)

1. **Withheld не измерен независимо в этом прогоне**: `withheld_values()` без `pg_get` возвращает 0 записей
   (нужен DB-getter). Фактически состояние withheld **не менялось**: все канон-ключи в PG байт-в-байт как в
   2.58.122. Напоминание из `release-258122`: живой замер давал **11** записей (`unclassified / provenance_unavailable`),
   а не «8» — расхождение pre-existing, требует сверки PM/Reviewer с фикстурами.
2. **`smart_archive` generation остаётся `building` (FTS-only, durable job missing)** — pre-existing с 2.58.118;
   на retrieval влияет (`mca07_retrieval skipped`), к релизу 2.58.123 отношения не имеет.
3. **Бюджет инструкций в композере — есть в задеплоенном 2.58.123, снят в локальном worktree (в работе).**
   Кандидат сам квоту не вводит — наоборот, финальный контракт **вне** бюджета именно чтобы не вытеснять
   `Style_Policy_Hint` («при бюджете 1200», комментарий `services/prompt_composer.py`). При этом на Windows-мастере
   прямо во время деплоя шла отдельная незакоммиченная правка «QUOTA-REMOVAL (ADDENDUM #3 §2.7)» (15 файлов
   `services/*`, `tests/*`, mtime 07:09–07:12Z), которая удаляет бюджет инструкций. Она **не входит** в
   задеплоенный `3dfdf9cb` и требует обычного цикла Builder→Reviewer→deploy. Деплой 2.58.123 от этого не зависит.

## Вердикт

**Деплой VERIFIED.** Прод на `3dfdf9cb` / **2.58.123**, сервис здоров (`active`, NRestarts 0), FACTORY_SET
`47f0d1eb8de4` не изменён, каноны Core/Checkup/Expression байт-в-байт прежние, Core-патч **идемпотентен**
(абзацы по 1 разу, sha не менялся), adopt/перестройка не повторялись, журнал чистый, Expression-контракт
речи стоит **в конце** system (прод-тест 15/15), откат на `c128675a` готов.

Не проверено и не заявляется: живое поведение речи в чатах (проб не отправляли — нет отдельной авторизации);
итоговый release-gate по карте требований — вне рамок этой полосы.

Сырые ключевые строки замеров: `raw/evidence.txt`.
