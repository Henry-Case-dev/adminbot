# REL-258103 — evidence релиз-пакета **2.58.103** (bump-only; поезд CFG-07CG-TAIL)

**Поезд (кандидат):** HEAD **`79df9f5dd4ddcb963ad48ef64bbcf74e584dfcb0`** = docs-ledger
`79df9f5d` поверх B1-телеметрии `8cd2ca14` поверх egress-guard `f1e31d27`
(ревью хвоста Approved REV-CFG07CG-TAIL; B1 — по предписанию review-07cg-tail).
Ф8-meta HEAD-штамп = `79df9f5d` — **прямое указание брифа PKG-103** (прецедент 98–102:
штамп = HEAD кодовой линии кандидата; здесь HEAD сам является=train-леджером).
+ **bump 2.58.102 → 2.58.103** — 31 файл, +33/−33, применён в рабочем дереве поверх
HEAD `79df9f5d`. **Коммит НЕ создавался** (бриф PKG-103: «КОМИТИТЬ НЕЛЬЗЯ», пакует
оркестратор, строго `--only` эти 31 файл). В дереве есть незакоммиченные правки других
лейнов — в пакет НЕ включены (см. «Изоляция»).
**Прод-базис:** 2.58.102 @ `79df9f5d` (задеплоен; бамп поверх него).

## Bump-манифест (31 файл = SET EQUAL с процедурой 102)

| Группа | Файлы | Старое → Новое |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.102"` → `"2.58.103"` (комментарий нетронут) |
| Версия | `README.md` | `v2.58.102` → `v2.58.103` (1 строка) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.102`→`2.58.103`; HEAD (short) `6388899d`→`79df9f5d` |
| py-пины | 24 файла `tests/test_*.py` | `"2.58.102"` → `"2.58.103"` (по 1 строке; `test_webapp_round1026_polygon.py` — 2) |
| js-пины | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.102` → `2\.58\.103` (регэкс) |

`git diff --shortstat -- <31 файл>` = **31 files changed, 33 insertions(+), 33 deletions(-)**.
Каждая изменённая строка = только версия/HEAD-штамп (bump-verify, 33 пары).
Счётчик каталога не менялся (REGISTRY 582, Δ=0; F8 `--check` зелёный — **582 == REGISTRY**;
поезд CFG-07CG-TAIL REGISTRY не менял — egress-гвард/телеметрия/канон-слой поверх effective).

## Guards

| Проверка | Результат | Статус | Файл |
|---|---|---|---|
| Offline-агрегат бампа (16 проверок: версия/README/meta/набор=31/SET EQUAL proc-102/дизъюнктность/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release/**фингерпринт 037080375ac8 live**/import) | **EXIT 0, 16/16 PASS** | ЗЕЛЁНЫЙ | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только версия/HEAD-штамп | files=31, pairs=33 (30 версий + meta-версия + meta-HEAD + polygon-вторая = 33), CHECK OK | ЗЕЛЁНЫЙ | `bump-verify.txt` |
| SET EQUAL с процедурой 102 | ref(102) 31 == bump(103) 31; ONLY IN 102: none; ONLY IN 103: none | ЗЕЛЁНЫЙ | `delta-vs-102.txt` |
| ΔDDL (бриф: bump-only без DDL, ≠0 ⇒ СТОП) | **0 файлов** в бамп-наборе И release-to-release (схема остаётся v37, задеплоена с 2.58.100); СТОП не сработал | ЗЕЛЁНЫЙ | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла целиком | **868 passed, EXIT 0** — совпадает с 101/102 | ЗЕЛЁНЫЙ | `pins24-summary.md`, scratch `pkg-103/pins24-full.txt` |
| Help-sync гард `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **38 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-js-unit.txt` |
| 4 js пин-теста нодой | **4/4 OK, EXIT=0** | ЗЕЛЁНЫЙ | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=106 bad=0**, EXIT 0 | ЗЕЛЁНЫЙ | scratch `pkg-103/js-sweep.txt` |
| F8-каталог `gen_param_registry_round1025.py --check` | **CHECK OK (582 == REGISTRY)**, EXIT 0 | ЗЕЛЁНЫЙ | `gen-param-check.txt` |
| Фингерпринт фабричного набора | `factory_set_fingerprint()` == `FACTORY_SET_SHA256_12` == **`037080375ac8`** (runtime-проба), `services/prompt_registry.py` не в дельте — **не менялся**, как требует бриф | ЗЕЛЁНЫЙ | внутри offline-агрегата + `frozen-fingerprint.txt` |
| settings import | `APP_VERSION == 2.58.103` | ЗЕЛЁНЫЙ | внутри offline-агрегата |

## ΔDDL (2.58.102 → 2.58.103) — 0, как требует бриф

Бамп-пакет не несёт DDL ни одной осью (`ddl-check.txt`):

- ΔDDL **бамп-набора** = 0 (ни `services/database.py`, ни `scripts/`, ни миграционных файлов в 31);
- ΔDDL **release-to-release** = 0 (схема SQLite остаётся v37 — миграция v36→v37 задеплоена с
  2.58.100; константа `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` в HEAD неизменна,
  `services/database.py` в дельте отсутствует). Условие СТОП (ΔDDL≠0) не сработало;
  DevOps-уведомление о миграции для этого релиза не требуется.
- Сам поезд (уже закоммичен): `f1e31d27`/`8cd2ca14` — egress-гвард на outbound-швах и
  telemetry stage_event (prompt/routing/observability-слой), DDL не несут.

## Изоляция от параллельных лейнов

1. Набор файлов бампа собран **явным перечнем процедуры** (константы в
   `OPENCODE_WORKFLOW_SCRATCH/pkg-103/bump_258103.py`), НЕ через `git status`.
2. Pre-bump проверка: 112 dirty/untracked файлов в дереве (samples-ux-хвост, asap8-карты,
   owner-доки, workflow_state, tools/_*, node_modules и пр.), **overlap с набором = 0**
   (`pkg-103/precheck_258103.py`, PASS; factcheck/06G.3-гвард на членство — 0;
   HEAD = `79df9f5d`, поезд-леджер).
3. Финальная сверка `git diff --name-only` → 39 tracked = **31 bump + 8 foreign**; все 8 foreign —
   plans-доки других лейнов (`plans/workflow_state.md`, `plans/owner_live_checks.md`,
   `plans/owner_questions.md`, asap8-v6-3 map/reconciliation, cfg-06 w7-dispute-metrics,
   archive mca-17c evidence, samples-ux map); **ни один factcheck/06G.3-файл в бамп-набор
   не попал и не изменён** (assert в offline-агрегате: PASS). Полный список —
   `final-diff-names.txt`.
4. Файлы factcheck/06G.3 не тронуты вовсе.

## Отличия от процедуры 102 (честно)

1. **Версия 2.58.103** — штатный численный инкремент, rollover-конвенции в репо нет.
2. **F8-meta HEAD = `79df9f5d`** — прямое указание брифа PKG-103 (HEAD = docs-ledger поезда).
3. Отклонений выполнения нет: precheck PASS → бамп 31 OK-строк с первого прогона →
   verify EXIT 0 (16/16) с первого прогона; все focused-гарды зелёные с первого прогона
   (29p/868p/24p/38p/4×node/106×node-check/F8 --check 582).

## Намеренно НЕ тронуто (та же политика, что в 97–102)

Исторические упоминания версий в комментариях канонов (слепки PREV_*_* фиксируют
прод-байты — это данные, не пины); `plans/**` — evidence/история; `web/**`; `services/**`;
factcheck/06G.3 файлы. Динамические потребители APP_VERSION (cache-bust/импорт)
версионно-агностичны, захардкоженных версий не содержат (sweep-состав web/tests/js
не изменился — 106).

## Фингерпринт

`frozen-fingerprint.txt` — pre-bump HEAD `79df9f5dd4dd…` (docs-ledger поезда поверх
`8cd2ca14`/`f1e31d27`); factory-фингерпринт `037080375ac8` — не менялся (runtime-проба в
offline-агрегате); post-bump sha256_12: settings `61df15f9c5f4`, README `c5b31ae8dd0e`,
F8-meta `280e777be27b`. Финальный кандидат-фингерпринт фиксирует оркестратор bump-коммитом
(--only 31 файл).

Сырые логи/скрипты: `OPENCODE_WORKFLOW_SCRATCH/pkg-103/` (`precheck_258103.py`,
`bump_258103.py`, `verify_258103.py`, `pins24-full.txt`, `js-sweep.txt`).
