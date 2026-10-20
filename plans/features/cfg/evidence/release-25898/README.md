# REL-25898 — evidence релиз-пакета **2.58.98** (bump-only; UNIFIED-CORE + R1-fixes)

**Кандидат:** кодовая линия **`1b23d4c9beb1544169f51781c2c8a45e8797f719`** (UNIFIED-CORE
`37097f7c` + R1-fixes `1b23d4c9`; RECHECK-25898-R1 `Approved`) + **bump 2.58.97 → 2.58.98** —
31 файл, +33/−33, применён в рабочем дереве поверх `d82ddc8c` (docs-only; runtime-байты
не менялись). **Коммит НЕ создавался** (по брифу PKG-98: коммитит оркестратор после
REV-REL, строго `--only` эти 31 файл; в рабочем дереве есть 2 чужих pre-existing
plans-правки других лейнов — вне пакета).
**Прод-базис:** 2.58.97 @ `99f5672c`. Изоляция: проверки в главном дереве (tracked-состояние
= HEAD + bump-only правки); отклонение от isolated-worktree процедуры 97 — следствие
запрета коммитов, зафиксировано ниже.

## Bump-манифест (31 файл = SET EQUAL с fcd73a38)

| Группа | Файлы | Старое → Новое |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.97"` → `"2.58.98"` (коммент нетронут) |
| Версия | `README.md` | `v2.58.97` → `v2.58.98` (1 строка) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.97`→`2.58.98`; HEAD (short) `2428768`→`1b23d4c` |
| py-пины | 24 файла `tests/test_*.py` | `"2.58.97"` → `"2.58.98"` (по 1 строке; `test_webapp_round1026_polygon.py` — 2) |
| js-пины | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.97` → `2\.58\.98` (регэкс) |

Счётчик каталога не менялся (REGISTRY 579, Δ=0).

## Guards (все зелёные)

| Проверка | Результат | Файл |
|---|---|---|
| Offline-агрегат бампа (11 проверок: версия/README/meta/набор/пары/DDL/import) | **EXIT 0, 11/11 PASS** | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только версия/HEAD-штамп | **files=31, pairs=33, VERSION-ONLY OK** | `bump-verify.txt` |
| ΔDDL-периметр (database.py, scripts/, миграции) | **ΔDDL = 0** (0 файлов) | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed in 3.24s** (97: 29p) | `focused-f8-pins.txt` |
| Все 24 py pin-файла целиком | **868 passed, 0 failed in 64.92s** | scratch `pins24-full.txt` (сырой лог) |
| Help-sync гард `test_asap8_v6_d14_help_sync.py` | **24 passed in 3.01s** (97: 24p) | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **38 passed in 5.32s** (97: 38p) | `focused-js-unit-38.txt` |
| 4 js pin-теста нодой | **4/4 OK, EXIT=0** | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=106 bad=0** (97: 106/0) | `js-sweep-106.txt` |
| F8-каталог `gen_param_registry_round1025.py --check` | **CHECK OK (579 == REGISTRY)**, EXIT 0 | `gen-param-check.txt` |
| settings import | `APP_VERSION == 2.58.98` | внутри offline-агрегата |

## Дельта vs процедура 97

**`delta-vs-97.txt`: ref files 31 == bump files 31, SET EQUAL: True** (ONLY IN 97: none;
ONLY IN 98: none). Профиль строк идентичен (+33/−33).

## Отклонения от процедуры 97 (честно)

1. **Bump не закоммичен** — требование брифа PKG-98 (коммитит оркестратор). Verify работает
   `working tree vs HEAD d82ddc8c`; 2 чужие plans-правки других лейнов исключены явно
   (перечислены в `bump-verify.txt`), в bump-коммит не войдут (`--only`).
2. **F8-meta HEAD = `1b23d4c`** — штамп кодовой линии кандидата v2 (прямое указание брифа),
   а не родитель будущего bump-коммита (родителем будет docs-коммит `d82ddc8c`). В 97 штамп
   совпадал с родителем bump. Семантика та же: «runtime-код, под которым издан реестр».
   Формат файла — short-хэш (7 симв.), полный SHA записан здесь и в `frozen-fingerprint.txt`.
3. **Полный `pytest -q` поезда в этот лейн не входит** (бриф: «код/тесты не менять», скоуп =
   механика бампа). Кандидат кода `1b23d4c9` уже прошёл полный прогон (12f/14632p/7err =
   base parity, 0 new failures) и RECHECK-25898-R1 `Approved`; bump меняет только
   версионные строки. Вместо двух полных прогонов 97 здесь: 24/24 pin-файла целиком
   (868p) + F8-пины + help-sync + JS-юнит + JS-syntax + каталог.
4. Изоляция в отдельном worktree не применялась (см. «Кандидат») — некоммитный bump
   нельзя перенести в чистое дерево без коммита/stash; влияние ограничено тем, что
   фокусные guards не зависят от чужих plans-правок (планы — не код/тесты).

## Намеренно НЕ тронуто (та же политика, что в 97)

`services/factcheck_prompts.py:203`, `services/prompt_migrations.py:165,276`,
`tests/test_prompt_migrations.py:239` — упоминания «релиз 2.58.97» в исторических
комментариях канонов (не пины); `plans/**` — evidence/история. Динамические потребители
APP_VERSION (cache-bust/импорт: `test_aliases_render_round1022`, `test_hotfix_round1025_cachebust`,
`test_mca16_experience_block_e_round1039`, `test_smoke_round1016_miniapp_selfhost`,
`tests/js/round1026_polygon_background_test.js`) версионно-агностичны, захардкоженных
версий не содержат.

## Фингерпринт

`frozen-fingerprint.txt` — pre-bump HEAD `d82ddc8cd…`, кодовая линия `1b23d4c9be…`;
post-bump sha256_12: settings `d8f56d928859`, README `bb3de3547148`, F8-meta `69c5248d05a5`.
Финальный кандидат-фингерпринт фиксирует оркестратор bump-коммитом.

Сырые логи/скрипты: `OPENCODE_WORKFLOW_SCRATCH/pkg98/` (`bump_25898.py`, `verify_25898.py`,
`js_sweep.js`, `pins24-full.txt`, `ref97-files.txt`, копия evidence-trio).
