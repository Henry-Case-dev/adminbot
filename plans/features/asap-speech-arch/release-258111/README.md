# REL-258111 — релизный бамп 2.58.110 → 2.58.111 (PKG-111, 23.10.2026)

Лейн PKG-111. Процедура — бамп-прецедент 106–110 (31-файловый SET EQUAL набор).
Дельта — только версия/HEAD-токены + release evidence (жёсткий pathspec); чужой
dirty-worktree других лейнов не захвачен.

## Состав релизной дельты (2.58.110 → 2.58.111; Approved review-w1.md)

| Коммиты | Суть |
|---|---|
| `700f762c` | W1 P0-A/B/C/E/F/G — фабричные каноны = тексты владельца §3.1/3.2/3.3/3.6 байт-в-байт (verbalizer §3.1 + data-reader P0A-RISK, core full/compact v3 §3.2/3.3 asap-core-*-v3 без мат-регулирования и SOUL-16-ремарки, PREV-цепочка v1/v2 + деривация; tool phase §3.6; L1 «ВЫБОР УЧАСТИЯ» §3.7; factcheck-вербализатор без identity-фразы) |
| `809a4fac` | W1 P0-D — Expression header = §3.4 байт-в-байт («ПРАВИЛА МАНЕРЫ РЕЧИ», PREV_EXPRESSION_HEADER док.) |
| `d0b84d84` | W1 процедура канонов — FACTORY_SET 553a281fe2fd → **`fd4e88754749`** (changed=6), лестницы PREV_*_W1 (direct_chat 11-я, verbalizer 3-я, l1 4-я ступень; НОВАЯ лестница `prompts.factcheck_verbalizer_system_prompt`), ROLLBACK, гвард superseded-core v1+v2, owner_preserve_core_full_patch |
| `a1db2991` | narrator LEGFIX — identity-фраза снята из канона Рассказчика (ступень LEGFIX verbalizer/tool_phase/narrator, PREV_SUMMARY_NARRATOR_LEGFIX) |
| `0f3ed53a` | W1 §9.1 чек-лист `tests/test_asap_w1_semantics.py` (21 тест CONTRACT owner=ASAP-W1) + контракт-тесты канонов под новые байты |
| `beb3f272` | W1 evidence (`evidence/w1/`: README, semantics-*.md, matrix-p0f.md, migrations.md, test-run.md, direct-runtime-assembly-w1.txt) + карта |
| `d3c385fe` | микродефект F2 — type-пины каталога == тип дефолта Settings (cooldown int→float и time_daily, 2 ключа) |
| `53cd023b` | микродефект webapp — HEAD /static/app.css отдаёт content-length == GET-телу |

F8-meta HEAD-токен = **`beb3f272`** — голова релизной дельты PKG-111; git HEAD на
пребампе = `beb3f272`, расхождений нет.

Review: `evidence/w1/review-w1.md` Approved — P0-C/D/E/F/G VERIFIED; P0-A/B
PENDING-W2: активная конфигурация мигрируется при деплое (owner_preserve_core_full_patch).

## Bump-набор (31 файл = SET EQUAL процедурам 106–110)

| Роль | Файл(ы) | Замена |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.110"` → `"2.58.111"` (только версия, комментарий без изменений) |
| Версия | `README.md` | `v2.58.110` → `v2.58.111` (единственная строка версии) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.110`→`2.58.111`; HEAD (short) `804f4963`→`beb3f272` |
| 24 py-пина | 24 файла `tests/test_*.py` | `2.58.110`→`2.58.111` (polygon — 2 вхождения) |
| 4 js-пина | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.110` → `2\.58\.111` (regex) |

`git diff` по bump-набору = **31 файл, 33 пары строк, только version/HEAD-токены**
(bump-verify: non-token deltas NONE). Каталог не тронут (REGISTRY 582, Δ=0; F8
`--check`: **582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны).

## Канонная эволюция в поезде

В поезде 111 канонная эволюция W1: FACTORY_SET **c19d35a1c093 → 3507bd6f92eb**
(уже в 2.58.110) **→ 553a281fe2fd → `fd4e88754749`** (ступени PREV_*_W1 +
LEGFIX, константа с `d0b84d84`). Гвард fingerprint сверяет с НОВЫМ значением:
офлайн-проба venv `factory_set_fingerprint()` == константа == **`fd4e88754749`**
— PASS. **При деплое обязателен плановый рестарт**: без него прод продолжит
считать старый fingerprint; рестарт также применяет owner_preserve_core_full_patch
к активной конфигурации (P0-A/B → W2).

## Guards

| Проверка | Результат | Статус | Артефакт |
|---|---|---|---|
| Pre-bump (HEAD=beb3f272, dirty∩bump=0, SET EQUAL proc-110, токены 33 в 31 файле) | PASS | VERIFIED | семантика вошла в `bump-offline-check.txt` |
| Offline-агрегат (**18** проверок: settings/README/meta/токены/SET EQUAL/foreign-guard/пары=33/каталог 582/ΔDDL=0 bump-scope и release-to-release, schema v37 + prompt_migrations=canon-ladder-note, **fingerprint fd4e88754749 live+import**) | **EXIT 0, 18/18 PASS** | VERIFIED | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только version/HEAD-токены | files=31, pairs=33 (+33/−33), non-token deltas NONE, CHECK OK | VERIFIED | `bump-verify.txt` |
| SET EQUAL с процедурой 106–110 | ref(110) 31 == bump(111) 31; ONLY IN 110: none; ONLY IN 111: none | VERIFIED | `delta-vs-110.txt` |
| ΔDDL (bump-scope + release-to-release; ≠ 0 → STOP) | **0 файлов** bump-набора в DDL-периметре; schema v37 не менялась; `services/database.py` вне release-дельты; `services/chat_prompts.py`/`services/prompt_migrations.py`/`services/prompt_registry.py` в дельте — намеренная канон-лестница W1 (PREV_*_W1 + LEGFIX), НЕ SQLite-DDL (рестарт при деплое обязателен) | VERIFIED | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | VERIFIED | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла (venv aiogram 3.31.0) | **868 passed / 0 failed, EXIT 0** — паритет 101–110 | VERIFIED | `pins24-summary.md`, `pins24-full.txt` |
| Help-sync `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | VERIFIED | `focused-help-sync.txt` |
| JS-unit `test_webapp_js_unit.py` | **39 passed**, EXIT 0 (набор не менялся — новых JS в поезде нет) | VERIFIED | `focused-js-unit.txt` |
| Node пин-регрессы | **5/5 OK** (4 js-пина + mini-lens) | VERIFIED | `js-pins-node.txt` |
| JS-syntax sweep (`node --check` web/ + tests/js) | **107 файлов / 0 bad**, EXIT 0 (= база 106–110) | VERIFIED | `js-pins-node.txt` |
| F8-генератор `--check` | **CHECK OK: реестр 582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны, EXIT 0 | VERIFIED | `gen-param-check.txt` |
| Write-points single-writer (`test_mca01_...` `-k write_points`) | **1 passed**, 32 deselected, EXIT 0 | VERIFIED | `focused-write-points.txt` |
| Цель: W1-семантика `test_asap_w1_semantics.py` (§9.1, байт-точность канонов) | **21 passed**, EXIT 0 | VERIFIED | `focused-w1-semantics.txt` |
| Цель: initreply-биндинг `test_asap8_initreply_binding.py` (контракт L1D; файл не менялся с `d87284c1`) | **14 passed**, EXIT 0 | VERIFIED | `focused-initreply-binding.txt` |
| Цель: L1D-контракт `test_direct_l1_l1d_contract.py` (файл не менялся с `e67a58e7`) | **15 passed**, EXIT 0 | VERIFIED | `focused-l1d-contract.txt` |
| Цель: mca19 fence-регресс `test_mca19_block_b_round1043.py` | **33 passed**, EXIT 0 (прецедент release-258108/110) | VERIFIED | `focused-mca19-regression.txt` |
| Цель: F2 type-пины `test_cfg03_param_audit.py` (вкл. `test_type_family_regressions_fixed`, фикс `d3c385fe`) | **17 passed**, EXIT 0 | VERIFIED | `focused-f2-type-family.txt` |
| Цель: app.css HEAD `test_webapp_api.py -k app_css` (вкл. content-length==GET, фикс `53cd023b`) | **2 passed**, EXIT 0 | VERIFIED | `focused-app-css-head.txt` |
| Цель: narrator LEGFIX `test_summary_asap21_prompt_migrations.py` (вкл. REGRESSION `test_narrator_canon_has_no_identity_legacy`, owner=FIX-SMALL-DEFECTS/narrator) | **22 passed**, EXIT 0 | VERIFIED | `focused-narrator-legfix.txt` |

## Изоляция

Полный снимок `git status --porcelain` — `final-diff-names.txt` (138 записей: 31 файл
бампа + этот каталог evidence + чужой dirty/untracked-хвост других лейнов, в пакет
не входит). Коммит — только 31 файл + `plans/features/asap-speech-arch/release-258111/`
по явному pathspec (foreign-guard PASS).

Не в скоупе лейна: пуш и деплой (по брифу PKG-111).

## Замечания (честные)

- **Интерпретатор гвардов.** Все pytest-прогоны через `.venv/Scripts/python.exe`
  (venv: Python 3.12.0, aiogram 3.31.0). Глобальный `py -3` для pytest-гвардов
  не использовался (venv-дисциплина, прецедент REL-258108/110).
- **initreply/l1d-счётчики** = фактические содержимые файлов (14/15), совпадают
  с брифом PKG-111; файлы с релиза 110 не менялись.
- **fingerprint-гвард**: офлайн-проба `factory_set_fingerprint()` сверена с
  константой `FACTORY_SET_SHA256_12` (services/prompt_registry.py:1640) — обе
  `fd4e88754749`; проверка выполняется после bump (версия не влияет на канон).
- Комментарий `APP_VERSION` в settings.py не переписывается (прецедент 105–110).
- Исторические упоминания версий (README-хвост, docs, слепки PREV_*_W1 = байты
  прод-канона 2.58.110 в W1-тестах/evidence) намеренно не менялись — это ссылки
  на прод-базу, а не пины текущей версии.
