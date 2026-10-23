# REL-258100 — evidence релиз-пакета **2.58.100** (bump-only; кандидат samples-ux)

**Кандидат:** кодовая линия **`27b1165aced5c54faf83845160509b1ad2307318`** (samples-ux v2 + ledger,
ревью Approved, 5 slice-гейтов review EXIT 0) + **bump 2.58.99 → 2.58.100** — 31 файл, +33/−33,
применён в рабочем дереве поверх HEAD `532a2d24` (ledger-docs коммит поверх кодовой линии; HEAD
до бампа). **Коммит НЕ создавался** (бриф PKG-SU: «КОМИТИТЬ НЕЛЬЗЯ», пакует оркестратор, строго
`--only` эти 31 файл). В дереве есть НЕЗАКОММИЧЕННАЯ параллельная работа 06G.3 (фактчек) и
plans-правки других лейнов — в пакет НЕ включены (см. «Изоляция»).
**Прод-базис:** 2.58.99 @ `46303ecd` (коммит бампа 99).

## Выбор версии — 2.58.100 (по штатному скрипту)

Штатные бамп-скрипты репо (release-25880…25899, прецедент `pkg99/bump_25899.py`) делают
байт-замену полного токена версии = **численный инкремент последней компоненты**. Никакой
семантической переноса-логики (rollover) в репо нет (grep по `2.59`/rollover — только история).
История: …2.58.97 → 2.58.98 → 2.58.99. ⇒ **2.58.100**. Формат пинов не ломает: js-регэкс
`2\.58\.100` валиден, строковые проверки — contains.

## Bump-манифест (31 файл = SET EQUAL с процедурой 98/99)

| Группа | Файлы | Старое → Новое |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.99"` → `"2.58.100"` (комментарий нетронут) |
| Версия | `README.md` | `v2.58.99` → `v2.58.100` (1 строка) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.99`→`2.58.100`; HEAD (short) `8f220b60`→`27b1165a` |
| py-пины | 24 файла `tests/test_*.py` | `"2.58.99"` → `"2.58.100"` (по 1 строке; `test_webapp_round1026_polygon.py` — 2) |
| js-пины | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.99` → `2\.58\.100` (регэкс) |

`git diff --shortstat -- <31 файл>` = **31 files changed, 33 insertions(+), 33 deletions(-)**.
Каждая изменённая строка = только версия/HEAD-штамп (bump-verify, 33 пары).
Счётчик каталога не менялся (REGISTRY 582, Δ=0; F8 `--check` зелёный — фактчек-флаги уже в
каталоге с PKG-99, samples-ux REGISTRY не менял — пункт 4 брифа подтверждён).

F8-meta HEAD = `27b1165a` — **прямое указание брифа** (штамп кодовой линии кандидата; прецедент
98/99: штамп = кодовая линия, не родитель bump-коммита). Формат short-хэш (8 симв.), полный SHA
в `frozen-fingerprint.txt`.

## Guards

| Проверка | Результат | Статус | Файл |
|---|---|---|---|
| Offline-агрегат бампа (14 проверок: версия/README/meta/набор=31/SET EQUAL proc-99/дизъюнктность с 06G.3/пары=33/каталог 582/171/ΔDDL=0/import) | **EXIT 0, 14/14 PASS** | ЗЕЛЁНЫЙ | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только версия/HEAD-штамп | files=31, pairs=33 (30 версий + meta-версия + meta-HEAD + polygon-вторая = 33), CHECK OK | ЗЕЛЁНЫЙ | `bump-verify.txt` |
| SET EQUAL с процедурой 99 | ref(99) 31 == bump(100) 31; ONLY IN 99: none; ONLY IN 100: none | ЗЕЛЁНЫЙ | `delta-vs-99.txt` |
| ΔDDL бамп-набора (database.py, scripts/, миграции) | **0 файлов** (см. ΔDDL release-to-release ниже) | ЗЕЛЁНЫЙ | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed** (98/99: 29p), EXIT 0 | ЗЕЛЁНЫЙ | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла целиком | **867 passed / 1 failed** (99 финал: 867p/1f). 1f = `test_mca17c…::test_reason_280_single_delta` — **foreign-корень 06G.3**: незакоммиченный `services/mca_events.py` добавил reason-код `attribution_not_found` (факт 302, HEAD 301, пин 301). Файл вне бампа (factcheck/06G.3 запрещён брифом). На чистой линии кандидата (worktree detach HEAD 532a2d24) файл целиком — **8 passed, EXIT 0** (включая пины 301 и user_version 37). Пересанкция 301→302 — обязанность лейна 06G.3 при приземлении (прецедент: PKG-99 оставил пин 36, samples-ux пересанкционировала при приземлении v37) | ИСПРАВЛЕНО ДОКАЗАТЕЛЬСТВОМ: чистая линия зелёная; остаток — foreign 06G.3, вне бампа | `pins24-summary.md`, scratch `pkg-su/pins24-full.txt` |
| Help-sync гард `test_asap8_v6_d14_help_sync.py` | **24 passed** (98/99: 24p), EXIT 0 | ЗЕЛЁНЫЙ | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **38 passed** (98/99: 38p), EXIT 0 | ЗЕЛЁНЫЙ | `focused-js-unit.txt` |
| 4 js пин-теста нодой | **4/4 OK, EXIT=0** | ЗЕЛЁНЫЙ | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=106 bad=0** (98/99: 106/0), EXIT 0 | ЗЕЛЁНЫЙ | scratch `pkg-su/js-sweep.txt` |
| F8-каталог `gen_param_registry_round1025.py --check` | **CHECK OK (582 == REGISTRY)**, EXIT 0 | ЗЕЛЁНЫЙ | `gen-param-check.txt` |
| Миграция samples-ux на реальном пути | `test_samples_categories.py` — **12 passed** (вкл. v36-схема+данные → v37 и идемпотентность бэкфила), EXIT 0 | ЗЕЛЁНЫЙ | `focused-samples-migration.txt` |
| settings import | `APP_VERSION == 2.58.100` | ЗЕЛЁНЫЙ | внутри offline-агрегата |

## ΔDDL release-to-release (2.58.99 → 2.58.100) — ОЖИДАЕМО, задокументировано

В отличие от 97/98/99 (ΔDDL=0 в том числе release-to-release), **этот релиз несёт миграцию
SQLite v36 → v37** — она уже ЗАКОММИЧЕНА в кодовой линии кандидата (`29b91004`, samples-ux §1/§3):

- `services/database.py`: `_SCHEMA_VERSION_HUMOR_SAMPLES = 37`, шаг `humor_samples_v37` после v36;
- состав: **аддитивная** (+6 колонок `humor_samples`: категории, явный режим выражения,
  tombstone/owner-правки), **идемпотентная** (повторный запуск `backfill_categories_v37` безопасен),
  **с сохранением данных** (бэкфил категорий, legacy-строки сохранены для реклассификации владельцем);
- тест реального пути v36-схема+данные → v37 — зелёный (`focused-samples-migration.txt`, 12p);
- ΔDDL **бамп-набора** = 0 (database.py не в 31 файле пакета — он уже в кандидате);
- пин `user_version == 37` в `test_mca17c_invariants_round1047.py` уже пересанкционирован
  samples-ux при приземлении v37 (зелёный на чистой линии — см. pins24);
- деплой применит миграцию при старте сервиса — DevOps уведомлён отдельно (по брифу).

## Изоляция от параллельных лейнов

1. Набор файлов бампа собран **явным перечнем процедуры** (константы в
   `OPENCODE_WORKFLOW_SCRATCH/pkg-su/bump_258100.py`), НЕ через `git status`.
2. Pre-bump проверка: 103 dirty/untracked файла в дереве, **overlap с набором = 0**
   (`pkg-su/precheck_258100.py`, PASS; factcheck-гвард на членство — 0).
3. Финальная сверка `git diff --name-only` → 40 tracked = **31 bump + 9 foreign**:
   foreign — 06G.3 (`services/factcheck_orchestrator.py`, `services/tool_router.py`,
   `services/mca_events.py`, `services/smartmodule_phrases.py`) + plans-правки других лейнов
   (`plans/workflow_state.md`, asap8-v6-3 map/reconciliation, cfg requirements-map, archive
   evidence); **ни один factcheck/06G.3-файл в бамп-набор не попал** (assert в
   offline-агрегате: PASS). Полный список — `final-diff-names.txt`.
4. Worktree для чистой линии создавался/удалялся без stash — параллельный райтер не затронут.

## Отклонения от процедуры 99 (честно)

1. **Версия 2.58.100** — первая в серии с трёхзначной последней компонентой; выбрана штатной
   логикой скрипта (численный инкремент), rollover-конвенции в репо нет.
2. **F8-meta HEAD = `27b1165a`** — кодовая линия кандидата по брифу; фактический git HEAD в
   момент бампа = `532a2d24` (docs-ledger поверх кандидата, код не меняет). Прецедент 98/99.
3. **Foreign-лейн сменился**: в 99 это была незакоммиченная samples-ux; теперь samples-ux — сам
   закоммиченный кандидат, а foreign — незакоммиченный 06G.3 (фактчек). Дизъюнктность
   assert'ится, factcheck-файлы не тронуты.
4. **pins24 1f — foreign 06G.3 (mca_events reason 301→302)**; чистая линия кандидата зелёная
   (worktree-прогон 8/8). Пин не тронут сознательно (аналог PKG-99).
5. **Косметика бамп-скрипта исправлена**: унаследованный от 99 print «2+24+4=30» (суммировал без
   meta) заменён на «3+24+4=31»; первый прогон вышел EXIT=1 на этом унаследованном assert'е
   УЖЕ ПОСЛЕ патча всех 31 файла (все 31 OK-строки в логе), повторная логика не требовалась —
   авторитет верификации: verify (31 файл, 33 пары, EXIT 0). Скрипт идемпотентно fail-closed.

## Намеренно НЕ тронуто (та же политика, что в 97/98/99)

Исторические упоминания версий в комментариях канонов — не пины; `plans/**` — evidence/история;
`web/**`; `services/**`; factcheck/06G.3 файлы. Динамические потребители APP_VERSION
(cache-bust/импорт) версионно-агностичны, захардкоженных версий не содержат (sweep-состав
web/tests/js не изменился — 106).

## Фингерпринт

`frozen-fingerprint.txt` — pre-bump HEAD `532a2d24e939…` (docs-ledger поверх кодовой линии
кандидата `27b1165aced5…`); post-bump sha256_12: settings, README, F8-meta. Финальный
кандидат-фингерпринт фиксирует оркестратор bump-коммитом (--only 31 файл).

Сырые логи/скрипты: `OPENCODE_WORKFLOW_SCRATCH/pkg-su/` (`precheck_258100.py`,
`bump_258100.py`, `verify_258100.py`, `pins24-full.txt`, `js-sweep.txt`,
`mca_events_head.py` — HEAD-модуль для замера 301).
