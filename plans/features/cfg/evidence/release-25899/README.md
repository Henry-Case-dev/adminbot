# REL-25899 — evidence релиз-пакета **2.58.99** (bump-only; кандидат CFG-06 v4)

**Кандидат:** кодовая линия **`8f220b60d72ea5cfeb77515881a7042c20cbc5b7`** (CFG-06 v4,
`Approved` RECHECK-R2) + **bump 2.58.98 → 2.58.99** — 31 файл, +33/−33, применён в
рабочем дереве поверх `8f220b60` (HEAD до бампа). **Коммит НЕ создавался** (бриф
PKG-99: «КОМИТИТЬ НЕЛЬЗЯ», пакует оркестратор, строго `--only` эти 31 файл).
В дереве есть НЕЗАКОММИЧЕННАЯ параллельная работа samples-ux и plans-правки других
лейнов — в пакет НЕ включены (см. «Изоляция»).
**Прод-базис:** 2.58.98 @ `f9e7dd67` (коммит бампа 98).

## Bump-манифест (31 файл = SET EQUAL с fcd73a38/98)

| Группа | Файлы | Старое → Новое |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.98"` → `"2.58.99"` (коммент нетронут) |
| Версия | `README.md` | `v2.58.98` → `v2.58.99` (1 строка) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.98`→`2.58.99`; HEAD (short) `1b23d4c`→`8f220b60` |
| py-пины | 24 файла `tests/test_*.py` | `"2.58.98"` → `"2.58.99"` (по 1 строке; `test_webapp_round1026_polygon.py` — 2) |
| js-пины | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.98` → `2\.58\.99` (регэкс) |

Счётчик каталога не менялся (REGISTRY 579, Δ=0; F8 `--check` зелёный).

## Guards

| Проверка | Результат | Статус | Файл |
|---|---|---|---|
| Offline-агрегат бампа (13 проверок: версия/README/meta/набор/дизъюнктность/пары 33 версии+15 ресанкций/DDL/import) | **EXIT 0, 13/13 PASS** (было 12/12; пары расщеплены на версии/ресанкции — фикс-лейн) | ЗЕЛЁНЫЙ | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только версия/HEAD-штамп **или санкционированная ресанкция 458→461 с провенансом** | files=31, pairs=48 (33 версии + 15 ресанкций), CHECK OK | ЗЕЛЁНЫЙ | `bump-verify.txt` |
| SET EQUAL с процедурой 98 | ref 31 == bump 31; ONLY IN 98: none; ONLY IN 99: none | ЗЕЛЁНЫЙ | `delta-vs-98.txt` |
| ΔDDL-периметр (database.py, scripts/, миграции) в бамп-наборе | **ΔDDL = 0** (0 файлов) | ЗЕЛЁНЫЙ | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed** (98: 29p), EXIT 0 | ЗЕЛЁНЫЙ | `focused-f8-pins.txt` |
| Все 24 py pin-файла целиком (после пересанкции 458→461) | **867 passed / 1 failed** (98: 868p/0f). 1f = `test_mca17c…::test_no_ddl_catalog_ks_tools_delta` — **foreign-корень**: чужие незакоммиченные samples-ux правки `services/database.py` (миграция v37), пин ассертит санкционированную v36; в HEAD `8f220b60` `_SCHEMA_VERSION_HUMOR_SAMPLES = 36` → на чистой линии кандидата тест зелёный (**868p/0f**). Детали и флейк `test_on_l1` — `pins-fix.md` | **ИСПРАВЛЕНО 15/16; остаток — foreign samples-ux, вне бампа** | `pins-fix.md`, scratch `pkg99/pins24-fulltrace.txt` |
| 19 не-пиновых тестов с тем же инвариантом (синхронизированы тем же правилом) | **571 passed / 2 failed**; 2f = `test_param_catalog.py` (покрытие каталогом 3 новых полей) — **pre-existing красота чистого HEAD вне guards**, чинится только в `services/param_catalog.py` (вне лейна) | ЗЕЛЁНЫЙ для ресанкции; 2f pre-existing вне guards | scratch `pkg99/other19-after-fix.txt`, `pins-fix.md` |
| Help-sync гард `test_asap8_v6_d14_help_sync.py` | **24 passed** (98: 24p), EXIT 0 | ЗЕЛЁНЫЙ | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **38 passed** (98: 38p), EXIT 0 | ЗЕЛЁНЫЙ | `focused-js-unit.txt` |
| 4 js pin-теста нодой | **4/4 OK, EXIT=0** | ЗЕЛЁНЫЙ | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=106 bad=0** (98: 106/0), EXIT 0 | ЗЕЛЁНЫЙ | scratch `pkg99/js-sweep.txt` |
| F8-каталог `gen_param_registry_round1025.py --check` | **CHECK OK (579 == REGISTRY)**, EXIT 0 | ЗЕЛЁНЫЙ | `gen-param-check.txt` |
| settings import | `APP_VERSION == 2.58.99`; `len(fields(Settings)) == 461`; 3 фактчек-поля `default False` | ЗЕЛЁНЫЙ | внутри offline-агрегата + `pins-fix.md` |

## pins24: 16 падений → фикс-лейн FIX-PKG99-PINS (20.10)

Полный разбор — **`pins-fix.md`**. Кратко:

- **15 из 16** — инвариант `len(fields(Settings)) == 458`, факт 461. Корень:
  кандидат **`5af56d8b`** (CFG-06 v2, Approved) добавил 3 поля фактчек-конвейера
  (`FACTCHECK_WIDE_CONTEXT_ENABLED`, `FACTCHECK_SUITABILITY_GATE_ENABLED`,
  `FACTCHECK_PIPELINE_V2_ENABLED`, все `default False` — сверено с картой).
  **Пересанкционировано 458→461** в 34 тестах (15 в бамп-наборе + 19 вне guards,
  по прямому указанию брифа «синхронизируй если тестовые»), каждое место несёт
  комментарий-провенанс `CFG-06 v2 (5af56d8b): +3 поля фактчек-конвейера,
  пересанкционировано 20.10`. Список было/стало — `pins-fix.md`.
- **16-е падение (`test_mca17c_invariants_round1047`) — ДРУГОЙ корень, не 458**:
  `PRAGMA user_version: assert 37 == 36` — FOREIGN-дефект рабочего дерева: чужая
  незакоммиченная samples-ux волна добавила миграцию v37 в
  `services/database.py` (ADD-SAMPLES-UX §1/§3). В HEAD-линии кандидата база
  инициализируется в v36 (`_SCHEMA_VERSION_HUMOR_SAMPLES = 36`) → на чистом
  чекауте релиз-коммита тест зелёный. Пин 36→37 НЕ менялся сознательно:
  санкционировать пином чужую незакоммиченную миграцию нельзя, а в
  закоммиченном состоянии (пакет без database.py) такой пин стал бы красным.
  Действие: лейн samples-ux пересанкционирует пин при приземлении v37.
- **Флейк `test_on_l1_not_usable_level2_l2_publishes_article`** (не из 16):
  падал в 2 полных прогонах подряд, затем прошёл (867p/1f), проходит соло и
  целым файлом. Pre-existing, root в services summary-пути (L1
  `invalid_json`→degraded недетерминизм); вне лейна, задокументирован.
- **`test_param_catalog.py` (вне guards, вне бампа)**: 2 теста красные и на
  чистом HEAD — 3 новых поля не каталогизированы (`services/param_catalog.py`
  не содержит `flags.factcheck_*`-ключей; кандидат каталог не трогал, при том
  что комментарии полей ссылаются на hot-ключи `flags.factcheck_*`). Владелец
  CFG-06/F8-каталога: либо каталогизация (+3 ключа, каскад пинов каталога),
  либо явная санкция исключения. Вне фикс-лейна (services/** запрещён).

## Изоляция от параллельных лейнов (отклонение от 98, задокументировано)

1. Набор файлов бампа собран **явным перечнем процедуры** (константы в
   `OPENCODE_WORKFLOW_SCRATCH/pkg99/bump_25899.py`), НЕ через `git status`.
2. Pre-bump проверка: 25 чужих dirty-файлов, **overlap с набором = 0**
   (`pkg99/precheck_25899.py`, PASS).
3. Финальная сверка `git diff --name-only` → 56 файлов = **31 bump + 25 foreign**;
   в foreign — samples-ux (`services/mca_expression.py`, `services/mca_sample_library.py`,
   `web/api/speech.py`, `web/app.js`, `web/index.html`, `web/static/app.css`,
   `tests/test_add_exp_expression.py`, `tests/test_unified_core_route_coverage.py`,
   `tests/ui_p0a_ux_speech_compact_e2e.py`, `services/database.py`) и plans-правки
   других лейнов; **ни один samples-ux/фактчек-файл в бамп-набор не попал**
   (assert в offline-агрегате: PASS). Полный список — `final-diff-names.txt`.
4. `services/database.py` имеет чужие незакоммиченные правки — в пакет не входит,
   ΔDDL бампа = 0 (периметр считался строго по 31 файлу набора).

## Отклонения от процедуры 98 (честно)

1. **Bump не закоммичен** — бриф PKG-99 (в 98 коммитил-таки оркестратор после
   REV-REL; здесь то же требование, явно). Verify работает `working tree vs HEAD 8f220b60`.
2. **F8-meta HEAD = `8f220b60`** — штамп кодовой линии кандидата (прягое указание
   брифа; прецедент 98: штамп = кодовая линия кандидата, не родитель bump-коммита).
   Формат — short-хэш (7 симв.), полный SHA в `frozen-fingerprint.txt`.
3. **Foreign-набор не был фиксированным whitelist из 2 файлов** (как в 98): дерево
   несёт большую незакоммиченную samples-ux волну. Заменено на явную энумерацию
   31 файла + assert дизъюнктности с samples-ux/фактчеком (требование брифа).
4. **Offline-агрегат: 12 проверок вместо 11** — добавлена проверка дизъюнктности
   бамп-набора с samples-ux/фактчеком.
5. **pins24: 852p/16f → исправлено фикс-лейном FIX-PKG99-PINS (20.10)**:
   15 инвариантов 458→461 пересанкционированы (см. `pins-fix.md`); финальный
   прогон **867p/1f**, где 1f — foreign samples-ux v37 (см. раздел выше);
   на чистой линии кандидата — 868p/0f. Дополнительно синхронизированы 19
   не-пиновых тестов с тем же инвариантом (указание брифа) — они выходят за
   31-файловый бамп-набор и должны быть включены оркестратором в пакет
   (иначе в закоммиченной линии эти 19 файлов останутся со stale-инвариантом 458).
6. Косметика: print бамп-скрипта унаследовал от 98 метку «2+24+4=30» (суммирует без
   meta); фактически пропатчено **31** файл — доказано OK-строками лога, `git diff`
   и SET EQUAL. Скрипт идемпотентно fail-closed (повторный запуск упадёт на assert).

## Намеренно НЕ тронуто (та же политика, что в 97/98)

Исторические упоминания версий в комментариях канонов (например
`tests/test_prompt_migrations.py:239`, промпт-каноны) — не пины; `plans/**` —
evidence/история; samples-ux файлы; `web/**`; `services/**`. Динамические
потребители APP_VERSION (cache-bust/импорт) версионно-агностичны, захардкоженных
версий не содержат (sweep 98 это подтверждал, состав web/tests/js не изменился — 106).

## Фингерпринт

`frozen-fingerprint.txt` — pre-bump HEAD `8f220b60d72e…` (кандидат CFG-06 v4,
Approved RECHECK-R2); post-bump sha256_12: settings `5694b0e46d81`,
README `2929c37a0390`, F8-meta `d7c6e574a775`. Финальный кандидат-фингерпринт
фиксирует оркестратор bump-коммитом (--only 31 файл). Фикс-лейн
FIX-PKG99-PINS (20.10) изменил только `tests/**` (34 файла) — три
зафингерпринченных файла не тронуты; лог ресанкции — scratch
`pkg99/resanction-log.txt`, скрипт `pkg99/resanction_461_25899.py` (34 сайта,
fail-closed).

Сырые логи/скрипты: `OPENCODE_WORKFLOW_SCRATCH/pkg99/` (`precheck_25899.py`,
`bump_25899.py`, `verify_25899.py`, `run_pins24_25899.py`, `js_sweep.js`,
`setequal_fingerprint_25899.py`, `pins24-full.txt`, `js-sweep.txt`,
`final-diff-names.txt` — копия).
