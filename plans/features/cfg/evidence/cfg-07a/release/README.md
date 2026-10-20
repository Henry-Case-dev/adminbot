# REL-258101 — evidence релиз-пакета **2.58.101** (bump-only; кандидат CFG-07A-2)

**Кандидат:** кодовая линия **`211a8c1bdb992b30f90046b8bc1146a564f0b5dd`** (CFG-07A-2
anti-backstage contract на 7 не-фактчек канонах, ревью Approved REV-CFG07A2) + **ledger**
`3be137ab` (VERIFIED-свидетельства) + **bump 2.58.100 → 2.58.101** — 31 файл, +33/−33,
применён в рабочем дереве поверх HEAD `3be137ab` (ledger-docs коммит поверх кодовой линии;
HEAD до бампа). **Коммит НЕ создавался** (бриф PKG-101: «КОМИТИТЬ НЕЛЬЗЯ», пакует оркестратор,
строго `--only` эти 31 файл). В дереве есть незакоммиченные plans-правки других лейнов —
в пакет НЕ включены (см. «Изоляция»).
**Прод-базис:** 2.58.100 @ `acc285d7` (коммит бампа 100, деплой VERIFIED).

## Выбор версии — 2.58.101 (по штатному скрипту)

Штатные бамп-скрипты репо (release-25880…258101, прецедент `pkg-su/bump_258100.py`) делают
байт-замену полного токена версии = **численный инкремент последней компоненты**. Rollover-логики
в репо нет. История: …2.58.99 → 2.58.100 → **2.58.101**. Формат пинов не ломает: js-регэкс
`2\.58\.101` валиден, строковые проверки — contains.

## Bump-манифест (31 файл = SET EQUAL с процедурой 99/100)

| Группа | Файлы | Старое → Новое |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.100"` → `"2.58.101"` (комментарий нетронут) |
| Версия | `README.md` | `v2.58.100` → `v2.58.101` (1 строка) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.100`→`2.58.101`; HEAD (short) `27b1165a`→`211a8c1b` |
| py-пины | 24 файла `tests/test_*.py` | `"2.58.100"` → `"2.58.101"` (по 1 строке; `test_webapp_round1026_polygon.py` — 2) |
| js-пины | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.100` → `2\.58\.101` (регэкс) |

`git diff --shortstat -- <31 файл>` = **31 files changed, 33 insertions(+), 33 deletions(-)**.
Каждая изменённая строка = только версия/HEAD-штамп (bump-verify, 33 пары).
Счётчик каталога не менялся (REGISTRY 582, Δ=0; F8 `--check` зелёный — **582 == REGISTRY**,
samples-ux каталог уже в линии с PKG-99/100, CFG-07A-2 канон-правки REGISTRY не меняли).

F8-meta HEAD = `211a8c1b` — **прямое указание брифа** (штамп кодовой линии кандидата; прецедент
98/99/100: штамп = кодовая линия, не родитель bump-коммита). Формат short-хэш (8 симв.), полный SHA
в `frozen-fingerprint.txt`.

## Guards

| Проверка | Результат | Статус | Файл |
|---|---|---|---|
| Offline-агрегат бампа (15 проверок: версия/README/meta/набор=31/SET EQUAL proc-100/дизъюнктность с 06G.3/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release/import) | **EXIT 0, 15/15 PASS** | ЗЕЛЁНЫЙ | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только версия/HEAD-штамп | files=31, pairs=33 (30 версий + meta-версия + meta-HEAD + polygon-вторая = 33), CHECK OK | ЗЕЛЁНЫЙ | `bump-verify.txt` |
| SET EQUAL с процедурой 100 | ref(100) 31 == bump(101) 31; ONLY IN 100: none; ONLY IN 101: none | ЗЕЛЁНЫЙ | `delta-vs-100.txt` |
| ΔDDL (бриф: канон-правки без DDL, ≠0 ⇒ СТОП) | **0 файлов** в бамп-наборе И release-to-release (схема остаётся v37, задеплоена с 2.58.100); СТОП не сработал | ЗЕЛЁНЫЙ | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла целиком | **868 passed, EXIT 0** — полностью зелёный (в 100 было 867p/1f: foreign-дефект 06G.3 reason-302; 06G.3 приземлился в `c849dbf4` с пересанкцией пина — остаток устранён, бамп-набор не менялся) | ЗЕЛЁНЫЙ | `pins24-summary.md`, scratch `pkg-101/pins24-full.txt` |
| Help-sync гард `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **38 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-js-unit.txt` |
| 4 js пин-теста нодой | **4/4 OK, EXIT=0** | ЗЕЛЁНЫЙ | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=106 bad=0**, EXIT 0 | ЗЕЛЁНЫЙ | scratch `pkg-101/js-sweep.txt` |
| F8-каталог `gen_param_registry_round1025.py --check` | **CHECK OK (582 == REGISTRY)**, EXIT 0 | ЗЕЛЁНЫЙ | `gen-param-check.txt` |
| settings import | `APP_VERSION == 2.58.101` | ЗЕЛЁНЫЙ | внутри offline-агрегата |

## ΔDDL (2.58.100 → 2.58.101) — 0, как требует бриф

CFG-07A-2 — канон-работа (FROZEN-байты канонов, лестница PREV_*_CFG07A, миграции промптов):
DDL не несёт. Проверено двумя осями (`ddl-check.txt`):

- ΔDDL **бамп-набора** = 0 (ни `services/database.py`, ни `scripts/`, ни миграционных файлов в 31);
- ΔDDL **release-to-release** = 0 (схема SQLite остаётся v37 — миграция v36→v37 задеплоена с
  2.58.100; константа `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` в кандидате неизменна,
  `services/database.py` в дельте отсутствует). Условие СТОП (ΔDDL≠0) не сработало;
  DevOps-уведомление о миграции для этого релиза не требуется.

## Изоляция от параллельных лейнов

1. Набор файлов бампа собран **явным перечнем процедуры** (константы в
   `OPENCODE_WORKFLOW_SCRATCH/pkg-101/bump_258101.py`), НЕ через `git status`.
2. Pre-bump проверка: 109 dirty/untracked файлов в дереве, **overlap с набором = 0**
   (`pkg-101/precheck_258101.py`, PASS; factcheck-гвард на членство — 0; HEAD = `3be137ab`).
3. Финальная сверка `git diff --name-only` → 37 tracked = **31 bump + 6 foreign**; все 6 foreign —
   plans-доки других лейнов (`plans/workflow_state.md`, asap8-v6-3 map/reconciliation,
   cfg-06 w7-dispute-metrics, archive mca-17c evidence, samples-ux map); **ни один
   factcheck/06G.3-файл в бамп-набор не попал и не изменён** (assert в offline-агрегате: PASS).
   Полный список — `final-diff-names.txt`.
4. Файлы 06G.3 (factcheck) не тронуты вовсе — по брифу.

## Отклонения от процедуры 100 (честно)

1. **Версия 2.58.101** — штатный численный инкремент, rollover-конвенции в репо нет.
2. **F8-meta HEAD = `211a8c1b`** — кодовая линия кандидата по брифу; фактический git HEAD в
   момент бампа = `3be137ab` (docs-ledger поверх кандидата, код не меняет). Прецедент 98/99/100.
3. **Foreign-лейн сменился**: в 100 это был незакоммиченный 06G.3 (фактчек-исходники);
   теперь 06G.3 приземлился (`c849dbf4`), foreign = только plans-правки других лейнов (6 шт.).
   Дизъюнктность assert'ится, factcheck-файлы не тронуты.
4. **pins24 стал полностью зелёным** (868/868): единственный failure pkg-su (867p/1f, foreign
   reason-301→302) устранён приземлением 06G.3, отдельного вмешательства не требовал.
5. Отклонений выполнения нет: precheck PASS → bump 31 OK-строк с первого прогона →
   verify EXIT 0 с первого прогона. Унаследованный от 99 косметический дефект скрипта
   (count «2+24+4=30») в pkg-su уже исправлен — здесь воспроизводился в исправленном виде.

## Намеренно НЕ тронуто (та же политика, что в 97/98/99/100)

Исторические упоминания версий в комментариях канонов (слепки PREV_*_* фиксируют прод-байты
2.58.100 по замыслу CFG-07A-2 — это данные, не пины); `plans/**` — evidence/история; `web/**`;
`services/**`; factcheck/06G.3 файлы. Динамические потребители APP_VERSION
(cache-bust/импорт) версионно-агностичны, захардкоженных версий не содержат (sweep-состав
web/tests/js не изменился — 106).

## Фингерпринт

`frozen-fingerprint.txt` — pre-bump HEAD `3be137ab7b24…` (docs-ledger поверх кодовой линии
кандидата `211a8c1bdb99…`); post-bump sha256_12: settings, README, F8-meta. Финальный
кандидат-фингерпринт фиксирует оркестратор bump-коммитом (--only 31 файл).

Сырые логи/скрипты: `OPENCODE_WORKFLOW_SCRATCH/pkg-101/` (`precheck_258101.py`,
`bump_258101.py`, `verify_258101.py`, `pins24-full.txt`, `js-sweep.txt`).
