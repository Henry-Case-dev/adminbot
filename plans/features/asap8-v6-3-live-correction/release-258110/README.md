# REL-258110 — релизный бамп 2.58.109 → 2.58.110 (PKG-110, 22.10.2026)

Лейн PKG-110. Процедура — бамп-прецедент 106–109 (31-файловый SET EQUAL набор).
Дельта — только версия/HEAD-токены + release evidence (жёсткий pathspec); чужой
dirty-worktree (284 записи других лейнов) не захвачен.

## Состав релизной дельты (2.58.109 → 2.58.110; Approved REV-INITIATIVE-L1D, REV-TAILS-2)

| Коммиты | Суть |
|---|---|
| `e67a58e7` | INITIATIVE-L1D (zone 1, директива владельца owner-corrective-initreply 22.10) — контракт L1D «форма участия принадлежит L1»: канон `services/chat_prompts.py` (+70, поля формы участия delivery/target_*), лестница `services/prompt_migrations.py` (ступень прод-канона 2.58.109 `PREV_DIRECT_L1_PLANNER_1022` → канон L1D), переотпечаток FACTORY_SET **c19d35a1c093 → `3507bd6f92eb`** (`services/prompt_registry.py`, константа `FACTORY_SET_SHA256_12`), слепок-тест `tests/test_expression_isolation_followup.py` + NEW `tests/test_direct_l1_l1d_contract.py` (15: схема/приоритеты/INITIATIVE_LINE/фолбэки) |
| `d87284c1` | INITIATIVE-L1D (zone 2) — транспорт исполняет решение L1: резолвер 2.58.109 (`_initiative_reply_target`/`_initiative_ref_ids`/24h-hardcode) удалён; `_validate_plan_target` — только технические проверки выбранной L1 цели; `reply_to_message_id` ТОЛЬКО из плана (delivery=reply + target_message_id; fail-soft plain при самодостаточном тексте, cancel+bounded defer при семантическом адресате, 400 gone — без сдирания биндинга); NEW `_execute_initiative_react` — реакция через `react_moai` на валидную цель, статус `reacted`; L1 видит окно с msg/user id и reply-ссылками, последние ответы бота, allowed reactions, адресата-наблюдателя; honest reason-метки `target_*`; `tests/test_asap8_initreply_binding.py` переписан под контракт L1D (14: директива §8 кейсы 1-8 как CONTRACT + 400-gone cancel-vs-failsoft + ностальгия без изменений; моки, 0 provider-вызовов) |
| `6196464d`, `db2b7044` | evidence-биндинги L1D (`initreply-l1d.md` VERIFIED по директиве 22.10; нормализация candidate full-sha, блокер REV-INITIATIVE-L1D снят) |
| `81419cfd`, `c39c776e`, `20bc0dc3` | TAILS-биндинги (14 RFL + 2 process, 4 RFL CFG-02A full-chain, SCEN-B + LIVE-SCENARIOS offline-harness; план EXIT 0 148/246/26) |
| `deb8b31e`, `7a358c2c` | review-коррекции REV-TAILS-2 (честная формулировка V02 capture, классификация REQ-B11-E2E) |

F8-meta HEAD-токен = **`7a358c2c`** — голова релизной дельты PKG-110; git HEAD на
пребампе = `7a358c2c`, расхождений нет.

## Bump-набор (31 файл = SET EQUAL процедурам 106–109)

| Роль | Файл(ы) | Замена |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.109"` → `"2.58.110"` (только версия, комментарий без изменений) |
| Версия | `README.md` | `v2.58.109` → `v2.58.110` (единственная строка версии) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.109`→`2.58.110`; HEAD (short) `1e3e5949`→`7a358c2c` |
| 24 py-пина | 24 файла `tests/test_*.py` | `2.58.109`→`2.58.110` (polygon — 2 вхождения) |
| 4 js-пина | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.109` → `2\.58\.110` (regex) |

`git diff` по bump-набору = **31 файл, 33 пары строк, только version/HEAD-токены**
(bump-verify: non-token deltas NONE). Каталог не тронут (REGISTRY 582, Δ=0; F8
`--check`: **582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны).

## Канонная эволюция в поезде (главное отличие от 106–109)

В поезде 110 есть канонная эволюция: FACTORY_SET **c19d35a1c093 → `3507bd6f92eb`**
(ступень prompt_migrations `PREV_DIRECT_L1_PLANNER_1022`, константа с `e67a58e7`).
Гвард fingerprint сверяет с НОВЫМ значением: офлайн-проба venv
`factory_set_fingerprint()` == константа == **`3507bd6f92eb`** — PASS.
**При деплое обязателен плановый рестарт** (без него прод продолжит считать старый
fingerprint и L1D-канон не поднимется).

## Guards

| Проверка | Результат | Статус | Артефакт |
|---|---|---|---|
| Pre-bump (HEAD=7a358c2c, dirty∩bump=0, SET EQUAL proc-109, токены 32+1 в 31 файле) | PASS | VERIFIED | scratch `pkg110_*` (семантика вошла в bump-offline-check) |
| Offline-агрегат (**18** проверок: settings/README/meta/токены/SET EQUAL/foreign-guard/пары=33/каталог 582/ΔDDL=0 bump-scope и release-to-release, schema v37 + prompt_migrations=canon-ladder-note, **fingerprint 3507bd6f92eb live+import**) | **EXIT 0, 18/18 PASS** | VERIFIED | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только version/HEAD-токены | files=31, pairs=33, non-token deltas NONE, CHECK OK | VERIFIED | `bump-verify.txt` |
| SET EQUAL с процедурой 106–109 | ref(109) 31 == bump(110) 31; ONLY IN 109: none; ONLY IN 110: none | VERIFIED | `delta-vs-109.txt` |
| ΔDDL (bump-scope + release-to-release; ≠ 0 → STOP) | **0 файлов** bump-набора в DDL-периметре; schema v37 не менялась; `services/database.py` вне release-дельты; `services/prompt_migrations.py` в дельте — намеренная ступень канон-лестницы PREV_DIRECT_L1_PLANNER_1022, НЕ SQLite-DDL (рестарт при деплое обязателен) | VERIFIED | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | VERIFIED | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла (venv aiogram 3.31.0) | **868 passed / 0 failed, EXIT 0** — паритет 101–109 | VERIFIED | `pins24-summary.md`, `pins24-full.txt` |
| Help-sync `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | VERIFIED | `focused-help-sync.txt` |
| JS-unit `test_webapp_js_unit.py` | **39 passed**, EXIT 0 (набор не менялся — новых JS в поезде нет) | VERIFIED | `focused-js-unit.txt` |
| Node пин-регрессы | **5/5 OK** (4 js-пина + mini-lens) | VERIFIED | `js-pins-node.txt` |
| JS-syntax sweep (`node --check` web/ + tests/js) | **107 файлов / 0 bad**, EXIT 0 (= база 106–109) | VERIFIED | `js-pins-node.txt` |
| F8-генератор `--check` | **CHECK OK: реестр 582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны, EXIT 0 | VERIFIED | `gen-param-check.txt` |
| Write-points single-writer (`test_mca01_...` `-k write_points`) | **1 passed**, 32 deselected, EXIT 0 | VERIFIED | `focused-write-points.txt` |
| Цель: initreply-биндинг `test_asap8_initreply_binding.py` (контракт L1D, директива §8) | **14 passed**, EXIT 0 (файл содержит 14 тестов с `d87284c1`; «12» в брифе/commit-msg лейна — документарный пересчёт кейсов директивы, файл не менялся) | VERIFIED | `focused-initreply-binding.txt` |
| Цель: L1D-контракт `test_direct_l1_l1d_contract.py` | **15 passed**, EXIT 0 (файл содержит 15 тестов с `e67a58e7`; «17» в evidence лейна — документарное расхождение, файл не менялся) | VERIFIED | `focused-l1d-contract.txt` |
| Цель: related инициативные сьюты (f6 23 + p0-init-arch 17 + w5-vitality 18 + w5-gates 17 + p0-initfix 10 + smartmodule_utils 36 + nostalgia-ab 8) | **129 passed**, EXIT 0 (aiosqlite-warning teardown — pre-existing тест-инфа, rc=0, прецедент 109) | VERIFIED | `focused-initiative-related.txt` |
| Цель: mca19 fence-регресс `test_mca19_block_b_round1043.py` | **33 passed**, EXIT 0 (прецедент release-258108) | VERIFIED | `focused-mca19-regression.txt` |

## Изоляция

Полный снимок `git status --porcelain` — `final-diff-names.txt` (284 записи: 31 файл
бампа + чужой dirty/untracked-хвост других лейнов, в пакет не входит; чужие py-модификации
— только `_`-инструменты/deploy-скрипты вне продуктового дерева, тестами не импортируются).
Коммит — только 31 файл + `plans/features/asap8-v6-3-live-correction/release-258110/`
(этот каталог) по явному pathspec. Review-evidence других лейнов в pathspec не входят
(foreign-guard PASS).

Не в скоупе лейна: пуш и деплой (по брифу PKG-110).

## Замечания (честные)

- **Интерпретатор гвардов.** Все pytest-прогоны через `.venv/Scripts/python.exe`
  (venv: Python 3.12.0, aiogram 3.31.0). Глобальный `py -3` для pytest-гвардов
  не использовался (venv-дисциплина, диагностический прецедент REL-258108).
- **Счётчики initreply/l1d vs бриф.** Бриф ожидал «initreply_binding 12p,
  l1d_contract 17p» — фактические файлы содержат 14 и 15 тестов (не менялись с
  `d87284c1`/`e67a58e7`); расхождение документарное (в evidence лейна считали
  кейсы директивы, не строки `def test_`). Прогонялись файлы ЦЕЛИКОМ, все зелёные.
- **aiosqlite-ворнинг в related-сьютe.** `focused-initiative-related.txt`:
  leaked-connections warning при rc=0 и 129/129 passed — pre-existing наблюдение
  teardown'а (прецедент 109), на вердикт не влияет; related-nonblocking.
- Комментарий `APP_VERSION` в settings.py не переписывается (прецедент 105–109:
  описание релиза живёт в commit message и этом README).
- Исторические упоминания версий (README-хвост, docs) намеренно не менялись.
