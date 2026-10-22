# REL-258112 — релизный поезд 2.58.111 → 2.58.112 (23.10.2026)

Лейн `RELEASE-258112`. Собрано из коммитов, уже находящихся в `HEAD` на старте:
ничего не черри-пикалось, W4-UI (незакоммиченный в основном чекауте) не захвачен.

## Точки

| Что | SHA |
|---|---|
| База (pre-bump `HEAD` / `master`) | `924b3b51d5a5b28cc4e0c65279b8a7acad54982a` |
| `origin/master` до push (2.58.111 + deploy docs) | `ec359bb3265b46c40081dd60e0654bb8482131e1` |
| Прод сейчас (2.58.111) — точка отката | `fbf9013d89b03e38473ce6824a460fdbb736fff8` |
| Поезд (21 коммит, `origin/master..HEAD`) | `ec359bb3..924b3b51` |
| Bump-коммит | этот коммит; SHA — в отчёте лейна |

Версия: **2.58.112**. F8-meta HEAD-токен = `924b3b51` (голова поезда до bump).
Байт-точный набор версии: 31 файл / 33 пары строк, `SET EQUAL` процедурам 106–111.

## Состав поезда (уже в HEAD, без черри-пиков)

Полный список — `train-commits.txt`. Группы:

| Функция | Коммиты | Статус по брифу |
|---|---|---|
| ASAP-2 Direct Chat corrective (+ probe, фикс блокеров, docs) | `5ad73933`, `ceba0e13`, `40389f55`, `a18733b5`, `34af90ff`, `29161a60`, `e64ecf5e`, `4b4146c7`, `f7156fee`, `13855e60` | Approved, probe 38/45 |
| Summary factview + B-1 (published cancel) | `138330c0`, `10f3a2a0` | Approved |
| Summary L2-ревизия всех абзацев + фикстура | `b1525b60`, `425ea79d` | Approved |
| Embed fallback slots | `468d1041` | Approved |
| Embed rebuild identity + честный статус | `d3ba845b`, `5877810d` | Approved for controlled deployment |
| B11 честная диагностика job-статусов | `3334141a`, `924b3b51` | `3334141a` Approved; `924b3b51` (N1 follow-up) — в поезде, на ре-ревью |
| SOUL-1 фикстура OFF-baseline | `4bd2f3c6` | — |
| W3 evals docs | `e5774789`, `13855e60` | — |

## Каноны промптов / fingerprint

Bump не меняет ни одного канонного файла (`services/chat_prompts.py`,
`services/prompt_migrations.py`, `services/prompt_registry.py` в bump-наборе нет).

Фактические значения на кандидате:

- `FACTORY_SET_SHA256_12` = **`24ae494ac422`**
- `factory_set_fingerprint()` (runtime) = **`24ae494ac422`** (runtime == constant, PASS)
- Пин-тест `tests/test_expression_isolation_followup.py` явно утверждает `24ae494ac422`.

Историческая справка: `fd4e88754749` — константа 2.58.111 (канон W1). В этом поезде
коммит `5ad73933` (ASAP-2) заменил её на `24ae494ac422`; bump 112 её не трогает.
Значение `fd4e88754749` осталось только в комментариях-лестницах PREV как ссылка
на прежние прод-байты. Поэтому в отчёте фиксируются оба факта, но гвард проверяет
актуальную пару `24ae494ac422` (constant == runtime).

## ΔDDL

**0.** В bump-наборе нет файлов DDL-периметра. В релизной дельте `origin/master..HEAD`
добавленных строк SQLite-DDL (`CREATE/ALTER/DROP TABLE|INDEX|VIEW`, `ADD COLUMN`,
`user_version=`) — **0** из 4843 добавленных py-строк. `services/database.py` изменён
коммитом `d3ba845b`, но это SELECT + переиспользование существующего INSERT
(идемпотентность поколений), не схема. `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` не менялся.
`prompt_migrations.py`/`chat_prompts.py`/`prompt_registry.py` в дельте — лестница
промпт-канонов ASAP-2 (не SQLite DDL).

## Guards (все через `.venv/Scripts/python.exe`, Python 3.12.0, aiogram 3.31.0)

| Проверка | Результат | Артефакт |
|---|---|---|
| Offline-агрегат (18 проверок: версии, SET EQUAL, foreign-guard, 33 пары, каталог 582, ΔDDL, fingerprint, import) | **18/18 PASS, EXIT 0** | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = version/HEAD-токен | files=31, pairs=33 (+33/−33), non-token **NONE**, CHECK OK | `bump-verify.txt` |
| SET EQUAL с bump-набором 111 | ref(111)=31 == bump(112)=31; ONLY IN: none | `delta-vs-111.txt` |
| F8-генератор `--check` | CHECK OK: реестр **582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны | `gen-param-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed** | `focused-f8-pins.txt` |
| pins24 (24 py-пин-файла) | **868 passed / 0 failed, EXIT 0** | `pins24-summary.md`, `pins24-full.txt` |
| Help-sync `test_asap8_v6_d14_help_sync.py` | **24 passed** | `focused-help-sync.txt` |
| JS-unit `test_webapp_js_unit.py` | **39 passed** | `focused-js-unit.txt` |
| Node пин-регрессы + mini-lens | **5/5 OK** | `js-pins-node.txt` |
| JS-syntax sweep (`node --check` web/ + tests/js) | **107 файлов / 0 bad** | `js-pins-node.txt` |
| py_compile изменённых py | **25 файлов / 0 bad** | `py-compile.txt` |
| Frozen-пины канонов (`test_expression_isolation_followup`, `test_soul1_registry_completeness`, `test_soul1_core_registry_api`, `test_soul1_w4_humor_craft`, `test_samples_fewshot`) | **66 passed** | `frozen-pins.txt` |
| Frozen UI-ассеты `tools/soul1_w4_frozen_check.py` | **FROZEN-ASSETS-OK** | `frozen-assets.txt` |
| Write-points single-writer | **1 passed**, 32 deselected | `focused-write-points.txt` |
| Цель ASAP-2: `test_asap2_clar_contract`, `test_asap7_direct_l1`, `test_mca08_character_speech`, `test_prompt_migrations` | **155 passed** | `focused-asap2.txt` |
| Смежные каноны: `test_direct_l1_l1d_contract`, `test_asap_w1_semantics`, `test_direct_l1_corrective_r1` | **48 passed** | `focused-canon-adjacent.txt` |
| Цель Summary: fact_view_v2_anchors, l2_review_multi_paragraph, generator, inc01_shutdown, failsoft, publish_integration | **179 passed** | `focused-summary.txt` |
| Цель Embed: fallback_slots_routing, graphrag_identity_reindex, memory overview API, memory lookup | **74 passed** | `focused-embed.txt` |
| Цель B11: `test_asap8_v63_b11_report.py` | **24 passed** | `focused-b11.txt` |

Суммарно по прогонам — **1507 passed / 0 failed** (наборы намеренно пересекаются,
например F8-пины и summary-пины входят в pins24; счёт дан по прогонам, не unique).

## Изоляция

Работа выполнена в отдельном worktree `C:\Code\Python\adminbot-wt258112` от
`924b3b51`; основной чекаут с грязным W4-UI (`web/app.js`, `web/index.html`,
`web/static/app.css`, `web/static/glass-refraction.js`) не изменялся.
`git status` релизного worktree = только 31 файл bump + этот каталог evidence
(`final-diff-names.txt`). Коммит/push — по явному pathspec, без `git add -A`.

## Честные замечания

- В поезде есть намеренная канонная эволюция ASAP-2 (не bump): при деплое
  **обязателен плановый рестарт**, иначе активная конфигурация останется на
  прежних байтах; лестница PREV/ROLLBACK переводит её идемпотентно.
- Прод не трогался: деплой/рестарт — не в этом лейне.
- `fd4e88754749` из брифа — прежняя константа 2.58.111; актуальная фактическая
  пара — `24ae494ac422` (constant == runtime). Это расхождение зафиксировано,
  а не замаскировано.
