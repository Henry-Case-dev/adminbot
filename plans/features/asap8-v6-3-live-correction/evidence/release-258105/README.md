# REL-258105 — evidence релизного бампа **2.58.105** (bump-only; поезд: фикс мини-линзы)

**Поезд релиза (бриф PKG-105):** фикс мини-линзы **`6c1dea40`** (web-only U08.4d/U08.5.1,
binding `.lg-mini-lens` → `toggleFullscreen`/FullscreenPolicy, REV-MINILENS **Approved**,
`evidence/review-minilens.md`) + prep-отметка **`7e42c7ee`** (prep-rfl-binding defect #1 note).
Других кодовых изменений в дельте нет. **F8-meta HEAD-штамп = `7e42c7ee`** — явное указание
брифа PKG-105 (HEAD дельты релиза; прецедент 104: штамп = голова поезда, git HEAD может
нести docs-коммиты сверху). Git HEAD на момент пребампа = `7a70e41a` (soul-1 AMD-probes,
docs-only `plans/features/soul-1/**`, параллельный лейн SOUL-AMD-PROBES — закоммитил во время
старта лейна; `merge-base --is-ancestor 7e42c7ee` = on-train, precheck PASS).
**База сравнения:** 2.58.104 @ `8ea6ed4e` (релизный бамп; procedure set 104).

## Bump-процедура (31 файл = SET EQUAL с процедурой 104)

| Категория | Файл | Действие при бампе |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.104"` → `"2.58.105"` (комментарий не тронут) |
| Версия | `README.md` | `v2.58.104` → `v2.58.105` (1 строка) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.104`→`2.58.105`; HEAD (short) `d860a529`→`7e42c7ee` |
| py-пины | 24 файла `tests/test_*.py` | `"2.58.104"` → `"2.58.105"` (по 1 строке; `test_webapp_round1026_polygon.py` — 2) |
| js-пины | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.104` → `2\.58\.105` (regex) |

`git diff --shortstat` по bump-набору = **31 файл, +33/−33**. Каждая изменённая строка =
только version/HEAD-токены (bump-verify, 33 пары). Каталог не реиздавался
(REGISTRY 582, Δ=0; F8 `--check` вердикт — **582 == REGISTRY**).

Единственное изменение вне 31-файлового набора: `tests/test_webapp_js_unit.py` **+13 строк** —
новый тест `asap8_u084d_mini_lens_binding_test.js` (6c1dea40) не подхватывался JS-раннером;
по брифу PKG-105 добавлен в конфиг набора (правки самого теста нет). JS-unit: 38 → **39 passed**.

## Guards

| Гвард | Результат | Статус | Файл |
|---|---|---|---|
| Offline-агрегат процедуры (16 проверок: settings/README/meta/набор=31/SET EQUAL proc-104/foreign-guard/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release/фингерпринт 037080375ac8 live/import) | **EXIT 0, 16/16 PASS** | VERIFIED | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только version/HEAD-токены | files=31, pairs=33 (30 замен + meta-версия + meta-HEAD + polygon-дубль = 33), CHECK OK | VERIFIED | `bump-verify.txt` |
| SET EQUAL с процедурой 104 | ref(104) 31 == bump(105) 31; ONLY IN 104: none; ONLY IN 105: none | VERIFIED | `delta-vs-104.txt` |
| ΔDDL (бриф: bump-only, ΔDDL=0 иначе STOP) | **0 файлов** в DDL-периметре и release-to-release (константа схемы v37 с 2.58.100); остановка не сработала | VERIFIED | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | VERIFIED | `focused-f8-pins.txt` |
| pins24: все 24 py пин-теста | **868 passed / 0 failed, EXIT 0** — идентично 101/102/103/104 | VERIFIED | `pins24-summary.md`, scratch `pkg-105/pins24-full.txt` |
| Help-sync `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | VERIFIED | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **39 passed** (38 + mini_lens_binding, добавлен в набор по брифу), EXIT 0 | VERIFIED | `focused-js-unit.txt` |
| 4 js пин-регрессии через node | **4/4 OK, EXIT=0** | VERIFIED | `js-pins-node.txt` |
| mini-lens binding node (нативно) | **MINI-LENS-BINDING-OK, EXIT=0** | VERIFIED | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=107 bad=0**, EXIT 0 (106 в proc-104 +1 новый тест-файл из 6c1dea40) | VERIFIED | scratch `pkg-105/js-sweep.txt` |
| F8-генератор `gen_param_registry_round1025.py --check` | **CHECK OK (582 == REGISTRY)**, EXIT 0 | VERIFIED | `gen-param-check.txt` |
| Фингерпринт заводского набора | `factory_set_fingerprint()` == `FACTORY_SET_SHA256_12` == **`037080375ac8`** (runtime-проба), `services/prompt_registry.py` не в дельте | VERIFIED | offline-агрегат + `frozen-fingerprint.txt` |
| settings import | `APP_VERSION == 2.58.105` | VERIFIED | офлайн-агрегат |

## ΔDDL (2.58.104 → 2.58.105) — 0, миграция не требуется

Двойная проверка в `ddl-check.txt`:

- ΔDDL **bump-периметра** = 0 (ни `services/database.py`, ни `scripts/`, ни миграционных
  сервисов: файлов из 31);
- ΔDDL **release-to-release** = 0 (схема SQLite остаётся v37 — переход v36→v37 уже
  выкачен с 2.58.100; константа `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` на HEAD неизменна,
  `services/database.py` не в дельте). Остановка (ΔDDL≠0) не сработала; DevOps-уведомление
  о миграции не требуется.
- Код поезда (не bump): `6c1dea40` — web-only (index.html/app.js/app.css + 2 JS-теста),
  DDL не касается; `7e42c7ee` — docs-only.

## Изоляция от параллельных лейнов: факты

1. Bump-файлы перечислены **явной энумерацией процедуры** (скрипт
   `OPENCODE_WORKFLOW_SCRATCH/pkg-105/bump_258105.py`), а не `git status`.
2. Pre-bump сверка: 98 dirty/untracked файлов в дереве (параллельные лейны soul-1/cfg/
   samples-ux и пр.), **overlap с bump-набором = 0** (`pkg-105/precheck_258105.py`, PASS;
   factcheck/06G.3-guard файлы в наборе = 0; HEAD on train: `7e42c7ee` — предок HEAD).
3. Пост-бамп `git diff --name-only`: 31 bump + 1 set-config (`tests/test_webapp_js_unit.py`,
   санкционировано брифом) + 3 foreign tracked (чужие лейны, **в пакет не входят**); полный
   список — `final-diff-names.txt`.
4. soul-1/** и cfg/** лейном PKG-105 не тронуты; коммит — по явному pathspec
   (31 файл + set-config + evidence), чужие staged/dirty изменения в коммит не попадают.

## Отличия от процедуры 104 (все санкционированы)

1. **Версия 2.58.105** — обычный инкремент последней компоненты, rollover-логики нет.
2. **F8-meta HEAD = `7e42c7ee`** — явное указание брифа PKG-105 (голова дельты релиза;
   git HEAD `7a70e41a` = docs-only soul-1 коммит параллельного лейна поверх поезда).
3. **JS-unit набор 38 → 39**: `mini_lens_binding` добавлен в `tests/test_webapp_js_unit.py`
   по брифу («добавлять в набор можно, правки самого теста — нет»); тест не менялся.
   Соответственно syntax-sweep 106 → 107 файлов (новый тест-файл из 6c1dea40).
4. Остальное идентично: precheck PASS → бамп 31 OK → verify EXIT 0 (16/16) →
   фокусированные гварды зелёные (29p/868p/24p/39p/5-node/107-syntax/F8 --check 582).

## Риски от выката (для DevOps, от бампа — ноль)

Bump-пакет меняет только APP_VERSION (cache-bust/версионирование) и версионные пины
тестов. Функциональная дельта поезда — `6c1dea40` (уже отревьюена REV-MINILENS Approved:
web-only, 6 файлов, fullscreen-policy не тронут, селекторы стекла расширены классом
`.lg-mini-lens`). U08.4d/U08.5.1 остаются PENDING до deployed live check (владелец,
добровольно) — на бамп и выкат не влияет.

## Фингерпринт

`frozen-fingerprint.txt` — release-train head `7e42c7ee028518bd…` (бриф PKG-105 / F8-meta
штамп), git HEAD пребампа `7a70e41a07f5e7c0…` (docs-only поверх); factory-фингерпринт
`037080375ac8` не изменён (runtime-проба в offline-агрегате); post-bump sha256_12 трёх
версионных якорей — в файле. Кандидатный фингерпринт фиксируется bump-коммитом
(pathspec: 31 файл + set-config + evidence).

Цех процедуры: `OPENCODE_WORKFLOW_SCRATCH/pkg-105/` (`precheck_258105.py`,
`bump_258105.py`, `verify_258105.py`, `pins24-full.txt`, `js-sweep.txt`).
