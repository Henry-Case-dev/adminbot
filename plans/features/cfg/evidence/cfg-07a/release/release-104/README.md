# REL-258104 — evidence релиз-пакета **2.58.104** (bump-only; поезд CFG-07D.5)

**Поезд (кандидат):** pre-bump HEAD **`dd6acf831e2ce4db410198cfa98041410ad17097`** = docs-ledger
`dd6acf83` поверх 07D.5-волны `d860a529` (bounded metatext retry + FA/MB detectors;
ревью Approved REV-07D5-R2 после repair-цикла F1–F4).
F8-meta HEAD-штамп = `d860a529` — **прямое указание брифа PKG-104** (штамп = HEAD кодовой
линии кандидата — коммит 07D.5; ledger лежит поверх него).
+ **bump 2.58.103 → 2.58.104** — 31 файл, +33/−33, применён в рабочем дереве поверх
HEAD `dd6acf83`. **Коммит НЕ создавался** (бриф PKG-104: «КОМИТИТЬ НЕЛЬЗЯ», пакует
оркестратор, строго `--only` эти 31 файл). В дереве есть незакоммиченные правки других
лейнов — в пакет НЕ включены (см. «Изоляция»).
**Прод-базис:** 2.58.103 @ `79df9f5d` (задеплоен; бамп поверх нового поезда).

## Bump-манифест (31 файл = SET EQUAL с процедурой 103)

| Группа | Файлы | Старое → Новое |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.103"` → `"2.58.104"` (комментарий нетронут) |
| Версия | `README.md` | `v2.58.103` → `v2.58.104` (1 строка) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.103`→`2.58.104`; HEAD (short) `79df9f5d`→`d860a529` |
| py-пины | 24 файла `tests/test_*.py` | `"2.58.103"` → `"2.58.104"` (по 1 строке; `test_webapp_round1026_polygon.py` — 2) |
| js-пины | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.103` → `2\.58\.104` (регэкс) |

`git diff --shortstat -- <31 файл>` = **31 files changed, 33 insertions(+), 33 deletions(-)**.
Каждая изменённая строка = только версия/HEAD-штамп (bump-verify, 33 пары).
Счётчик каталога не менялся (REGISTRY 582, Δ=0; F8 `--check` зелёный — **582 == REGISTRY**;
поезд CFG-07D.5 REGISTRY не менял — retry/detector-слой поверх verbalize_validated).

## Guards

| Проверка | Результат | Статус | Файл |
|---|---|---|---|
| Offline-агрегат бампа (16 проверок: версия/README/meta/набор=31/SET EQUAL proc-103/дизъюнктность/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release/**фингерпринт 037080375ac8 live**/import) | **EXIT 0, 16/16 PASS** | ЗЕЛЁНЫЙ | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только версия/HEAD-штамп | files=31, pairs=33 (30 версий + meta-версия + meta-HEAD + polygon-вторая = 33), CHECK OK | ЗЕЛЁНЫЙ | `bump-verify.txt` |
| SET EQUAL с процедурой 103 | ref(103) 31 == bump(104) 31; ONLY IN 103: none; ONLY IN 104: none | ЗЕЛЁНЫЙ | `delta-vs-103.txt` |
| ΔDDL (бриф: bump-only без DDL, ≠0 ⇒ СТОП) | **0 файлов** в бамп-наборе И release-to-release (схема остаётся v37, задеплоена с 2.58.100); СТОП не сработал | ЗЕЛЁНЫЙ | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла целиком | **868 passed, EXIT 0** — совпадает с 101/102/103 | ЗЕЛЁНЫЙ | `pins24-summary.md`, scratch `pkg-104/pins24-full.txt` |
| Help-sync гард `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **38 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-js-unit.txt` |
| 4 js пин-теста нодой | **4/4 OK, EXIT=0** | ЗЕЛЁНЫЙ | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=106 bad=0**, EXIT 0 | ЗЕЛЁНЫЙ | scratch `pkg-104/js-sweep.txt` |
| F8-каталог `gen_param_registry_round1025.py --check` | **CHECK OK (582 == REGISTRY)**, EXIT 0 | ЗЕЛЁНЫЙ | `gen-param-check.txt` |
| Фингерпринт фабричного набора | `factory_set_fingerprint()` == `FACTORY_SET_SHA256_12` == **`037080375ac8`** (runtime-проба), `services/prompt_registry.py` не в дельте — **не менялся**, как требует бриф | ЗЕЛЁНЫЙ | внутри offline-агрегата + `frozen-fingerprint.txt` |
| settings import | `APP_VERSION == 2.58.104` | ЗЕЛЁНЫЙ | внутри offline-агрегата |

## ΔDDL (2.58.103 → 2.58.104) — 0, как требует бриф

Бамп-пакет не несёт DDL ни одной осью (`ddl-check.txt`):

- ΔDDL **бамп-набора** = 0 (ни `services/database.py`, ни `scripts/`, ни миграционных файлов в 31);
- ΔDDL **release-to-release** = 0 (схема SQLite остаётся v37 — миграция v36→v37 задеплоена с
  2.58.100; константа `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` в HEAD неизменна,
  `services/database.py` в дельте отсутствует). Условие СТОП (ΔDDL≠0) не сработало;
  DevOps-уведомление о миграции для этого релиза не требуется.
- Сам поезд (уже закоммичен): `d860a529` — bounded metatext retry + FA/MB детекторы
  (prompt/detector-слой поверх `verbalize_validated`), DDL не несёт; `dd6acf83` — docs-ledger.

## Изоляция от параллельных лейнов

1. Набор файлов бампа собран **явным перечнем процедуры** (константы в
   `OPENCODE_WORKFLOW_SCRATCH/pkg-104/bump_258104.py`), НЕ через `git status`.
2. Pre-bump проверка: 118 dirty/untracked файлов в дереве (asap8-v6-3 services-правки
   `factcheck_service.py`/`negative_constraints.py`/`prompt_style_blocks.py`, plans-доки,
   owner-доки, workflow_state, tools/_*, node_modules и пр.), **overlap с набором = 0**
   (`pkg-104/precheck_258104.py`, PASS; factcheck/06G.3-гвард на членство — 0;
   HEAD = `dd6acf83`, поезд-леджер).
3. Финальная сверка `git diff --name-only` → 42 tracked = **31 bump + 11 foreign**; все 11 foreign —
   чужие правки (`services/factcheck_service.py`, `services/negative_constraints.py`,
   `services/prompt_style_blocks.py` — asap8-v6-3-лейн; plans-доки: `plans/workflow_state.md`,
   `plans/owner_live_checks.md`, `plans/owner_questions.md`, asap8-v6-3 map/reconciliation,
   cfg-06 w7-dispute-metrics, archive mca-17c evidence, samples-ux map); **ни один
   factcheck/06G.3-файл в бамп-набор не попал и не изменён** (assert в offline-агрегате: PASS).
   Полный список — `final-diff-names.txt`.
4. Файлы factcheck/06G.3 (гвард-набор 8 файлов) не тронуты вовсе; `services/prompt_registry.py`
   не в дельте (фингерпринт цел).

## Отличия от процедуры 103 (честно)

1. **Версия 2.58.104** — штатный численный инкремент, rollover-конвенции в репо нет.
2. **F8-meta HEAD = `d860a529`** — прямое указание брифа PKG-104 (HEAD кодовой линии = 07D.5;
   pre-bump git HEAD `dd6acf83` = docs-ledger поверх волны).
3. Отклонений выполнения нет: precheck PASS → бамп 31 OK-строк с первого прогона →
   verify EXIT 0 (16/16) с первого прогона; все focused-гарды зелёные с первого прогона
   (29p/868p/24p/38p/4×node/106×node-check/F8 --check 582).

## Намеренно НЕ тронуто (та же политика, что в 97–103)

Исторические упоминания версий в комментариях канонов (слепки PREV_*_* фиксируют
прод-байты — это данные, не пины); `plans/**` — evidence/история; `web/**`; `services/**`
(включая 3 dirty-файла asap8-лейна); factcheck/06G.3 файлы. Динамические потребители
APP_VERSION (cache-bust/импорт) версионно-агностичны, захардкоженных версий не содержат
(sweep-состав web/tests/js не изменился — 106).

## Фингерпринт

`frozen-fingerprint.txt` — pre-bump HEAD `dd6acf831e2c…` (docs-ledger поезда поверх
07D.5 `d860a529`); factory-фингерпринт `037080375ac8` — не менялся (runtime-проба в
offline-агрегате); post-bump sha256_12: settings `см. файл`, README `см. файл`,
F8-meta `см. файл`. Финальный кандидат-фингерпринт фиксирует оркестратор bump-коммитом
(--only 31 файл).

Сырые логи/скрипты: `OPENCODE_WORKFLOW_SCRATCH/pkg-104/` (`precheck_258104.py`,
`bump_258104.py`, `verify_258104.py`, `pins24-full.txt`, `js-sweep.txt`).
