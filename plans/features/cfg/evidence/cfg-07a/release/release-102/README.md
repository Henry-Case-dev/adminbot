# REL-258102 — evidence релиз-пакета **2.58.102** (bump-only; кандидат CFG-07A F1)

**Кандидат:** кодовая линия **`6388899de5d9fa0033e1a9d8acbbca83ed504b49`** (CFG-07A F1
payload-level custom_clean scope для 7 не-фактчек канон-ключей, ревью Approved
REV-CFG07A-F1; кандидат сам является HEAD, docs-ledger поверх него в момент бампа не
добавлялся) + **bump 2.58.101 → 2.58.102** — 31 файл, +33/−33, применён в рабочем дереве
поверх HEAD `6388899d`. **Коммит НЕ создавался** (бриф PKG-102: «КОМИТИТЬ НЕЛЬЗЯ»,
пакует оркестратор, строго `--only` эти 31 файл). В дереве есть незакоммиченные правки
других лейнов — в пакет НЕ включены (см. «Изоляция»).
**Прод-базис:** 2.58.101 @ `e3fd364c` (деплой VERIFIED; кандидат F1 `6388899d` —
следующий кодовый коммит поверх него).

## Структура evidence — выбор документирован

Evidence PKG-102 живёт в **подкаталоге `release/release-102/`** (этот каталог). Исторический
набор REL-258101 остаётся в корне `release/` (префикс-less). Следующие релизы cfg-07a
продолжают схему `release/release-<версия>/`. Scratch-логи: `OPENCODE_WORKFLOW_SCRATCH/pkg-102/`.

## Выбор версии — 2.58.102 (по штатному скрипту)

Штатные бамп-скрипты репо (release-25880…258102, прецедент `pkg-101/bump_258101.py`) делают
байт-замену полного токена версии = **численный инкремент последней компоненты**. Rollover-логики
в репо нет. История: …2.58.100 → 2.58.101 → **2.58.102**. Формат пинов не ломает: js-регэкс
`2\.58\.102` валиден, строковые проверки — contains.

## Bump-манифест (31 файл = SET EQUAL с процедурой 101)

| Группа | Файлы | Старое → Новое |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.101"` → `"2.58.102"` (комментарий нетронут) |
| Версия | `README.md` | `v2.58.101` → `v2.58.102` (1 строка) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.101`→`2.58.102`; HEAD (short) `211a8c1b`→`6388899d` |
| py-пины | 24 файла `tests/test_*.py` | `"2.58.101"` → `"2.58.102"` (по 1 строке; `test_webapp_round1026_polygon.py` — 2) |
| js-пины | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.101` → `2\.58\.102` (регэкс) |

`git diff --shortstat -- <31 файл>` = **31 files changed, 33 insertions(+), 33 deletions(-)**.
Каждая изменённая строка = только версия/HEAD-штамп (bump-verify, 33 пары).
Счётчик каталога не менялся (REGISTRY 582, Δ=0; F8 `--check` зелёный — **582 == REGISTRY**,
CFG-07A F1 REGISTRY не менял — это suppress-слой поверх effective-значений).

F8-meta HEAD = `6388899d` — **прямое указание брифа** (штамп кодовой линии кандидата;
прецедент 98/99/100/101: штамп = кодовая линия, не родитель bump-коммита). Формат
short-хэш (8 симв.), полный SHA в `frozen-fingerprint.txt`.

## Guards

| Проверка | Результат | Статус | Файл |
|---|---|---|---|
| Offline-агрегат бампа (16 проверок: версия/README/meta/набор=31/SET EQUAL proc-101/дизъюнктность/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release/**фингерпринт 037080375ac8 live**/import) | **EXIT 0, 16/16 PASS** | ЗЕЛЁНЫЙ | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только версия/HEAD-штамп | files=31, pairs=33 (30 версий + meta-версия + meta-HEAD + polygon-вторая = 33), CHECK OK | ЗЕЛЁНЫЙ | `bump-verify.txt` |
| SET EQUAL с процедурой 101 | ref(101) 31 == bump(102) 31; ONLY IN 101: none; ONLY IN 102: none | ЗЕЛЁНЫЙ | `delta-vs-101.txt` |
| ΔDDL (бриф: suppress-слой без DDL, ≠0 ⇒ СТОП) | **0 файлов** в бамп-наборе И release-to-release (схема остаётся v37, задеплоена с 2.58.100); СТОП не сработал | ЗЕЛЁНЫЙ | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла целиком | **868 passed, EXIT 0** — совпадает с 101 | ЗЕЛЁНЫЙ | `pins24-summary.md`, scratch `pkg-102/pins24-full.txt` |
| Help-sync гард `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **38 passed**, EXIT 0 | ЗЕЛЁНЫЙ | `focused-js-unit.txt` |
| 4 js пин-теста нодой | **4/4 OK, EXIT=0** | ЗЕЛЁНЫЙ | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=106 bad=0**, EXIT 0 | ЗЕЛЁНЫЙ | scratch `pkg-102/js-sweep.txt` |
| F8-каталог `gen_param_registry_round1025.py --check` | **CHECK OK (582 == REGISTRY)**, EXIT 0 | ЗЕЛЁНЫЙ | `gen-param-check.txt` |
| Фингерпринт фабричного набора | `factory_set_fingerprint()` == `FACTORY_SET_SHA256_12` == **`037080375ac8`** (runtime-проба), `services/prompt_registry.py` не в дельте — **не менялся**, как требует бриф | ЗЕЛЁНЫЙ | внутри offline-агрегата + `frozen-fingerprint.txt` |
| settings import | `APP_VERSION == 2.58.102` | ЗЕЛЁНЫЙ | внутри offline-агрегата |

## ΔDDL (2.58.101 → 2.58.102) — 0, как требует бриф

CFG-07A F1 — канон-работа (payload-уровень: подавление FORBIDDEN-маркеров в effective-значениях
OWNER-CUSTOM persisted-ключей, сохранённый текст не мутируется): DDL не несёт. Проверено двумя
осями (`ddl-check.txt`):

- ΔDDL **бамп-набора** = 0 (ни `services/database.py`, ни `scripts/`, ни миграционных файлов в 31);
- ΔDDL **release-to-release** = 0 (схема SQLite остаётся v37 — миграция v36→v37 задеплоена с
  2.58.100; константа `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` в кандидате неизменна,
  `services/database.py` в дельте отсутствует). Условие СТОП (ΔDDL≠0) не сработало;
  DevOps-уведомление о миграции для этого релиза не требуется.

## Изоляция от параллельных лейнов

1. Набор файлов бампа собран **явным перечнем процедуры** (константы в
   `OPENCODE_WORKFLOW_SCRATCH/pkg-102/bump_258102.py`), НЕ через `git status`.
2. Pre-bump проверка: 111 dirty/untracked файлов в дереве (samples-ux-хвост, tools/_*,
   workflow_state и пр.), **overlap с набором = 0** (`pkg-102/precheck_258102.py`, PASS;
   factcheck/06G.3-гвард на членство — 0; HEAD = `6388899d`, кандидат).
3. Финальная сверка `git diff --name-only` → 37 tracked = **31 bump + 6 foreign**; все 6 foreign —
   plans-доки других лейнов (`plans/workflow_state.md`, asap8-v6-3 map/reconciliation,
   cfg-06 w7-dispute-metrics, archive mca-17c evidence, samples-ux map); **ни один
   factcheck/06G.3-файл в бамп-набор не попал и не изменён** (assert в offline-агрегате: PASS).
   Полный список — `final-diff-names.txt`.
4. Файлы factcheck/06G.3 не тронуты вовсе.

## Отличия от процедуры 101 (честно)

1. **Версия 2.58.102** — штатный численный инкремент, rollover-конвенции в репо нет.
2. **F8-meta HEAD = `6388899d`** — кодовая линия кандидата по брифу; кандидат сам является
   git HEAD (в 101 поверх кандидата лежал docs-ledger `3be137ab`). Прецедент 98/99/100/101.
3. **Offline-агрегат расширен до 16 проверок**: добавлена runtime-проба фингерпринта
   `factory_set_fingerprint() == 037080375ac8` (прямое требование приёмки брифа PKG-102).
4. **Evidence-структура**: подкаталог `release-102/` вместо корня `release/` (см. выше).
5. Отклонений выполнения нет: precheck PASS → bump 31 OK-строк с первого прогона →
   verify EXIT 0 с первого прогона; все focused-гарды зелёные с первого прогона.

## Намеренно НЕ тронуто (та же политика, что в 97/98/99/100/101)

Исторические упоминания версий в комментариях канонов (слепки PREV_*_* фиксируют прод-байты —
это данные, не пины); `plans/**` — evidence/история; `web/**`; `services/**`; factcheck/06G.3
файлы. Динамические потребители APP_VERSION (cache-bust/импорт) версионно-агностичны,
захардкоженных версий не содержат (sweep-состав web/tests/js не изменился — 106).

## Фингерпринт

`frozen-fingerprint.txt` — pre-bump HEAD `6388899de5d9…` (сам кандидат; отдельного docs-ledger
поверх нет); factory-фингерпринт `037080375ac8` — не менялся (runtime-проба в offline-агрегате);
post-bump sha256_12: settings, README, F8-meta. Финальный кандидат-фингерпринт фиксирует
оркестратор bump-коммитом (--only 31 файл).

Сырые логи/скрипты: `OPENCODE_WORKFLOW_SCRATCH/pkg-102/` (`precheck_258102.py`,
`bump_258102.py`, `verify_258102.py`, `pins24-full.txt`, `js-sweep.txt`).
