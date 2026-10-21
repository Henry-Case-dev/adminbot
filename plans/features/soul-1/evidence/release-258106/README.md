# REL-258106 — релизный бамп 2.58.105 → 2.58.106 (PKG-106, 21.10.2026)

Бриф PKG-106. Процедура — байт-в-байт прецедент 105
(`OPENCODE_WORKFLOW_SCRATCH/pkg-106/{precheck,bump,verify}_258106.py`).
Коммит — только версионный набор + этот evidence (явный pathspec); пуш и деплой
не входят в лейн.

## Поезд релиза (дельта 2.58.105 → 2.58.106, все Approved)

| Коммит | Что |
|---|---|
| `2f1a49ad` + `20252faa` | SOUL-14.1 — диаграмма влияния слоёв «Как рождается ответ» (web+API+e2e) |
| `a8d049f3` + `6f8710a8` | SOUL-14.2 — телеметрия extent (speech_extent в существующий mca_events-контур) |
| `cdb0492f` | фикс мигратора — backup строк при отрицательном chat_id (chat_running_summary transfer); ΔDDL=0 |
| `4f0ae438` | asap8: исполняемые пробы + B12.6 остатки (tests+evidence+docs, runtime=0) |
| `edab6582` | ярлык 14.2 READY_FOR_LIVE + write-points audit provenance (docs+test) |

F8-meta HEAD-штамп = **`edab6582`** — явное указание брифа PKG-106 (голова на
пребампе; git HEAD на момент пребампа = `edab6582`, совпадает со штампом).

Пост-бамп заметка (честная фиксация по прецеденту 104/105): после коммита
бампа `83012fcf` параллельный A/B-лейн лёг сверху docs-only коммитом
`1aadf16b` (soul-1/evidence/ab, 22 файла). Штамп F8-meta `edab6582` остаётся
головой дельты релиза 2.58.105 → 2.58.106; docs-коммиты поверх поезда штатны
и в бамп-пакет не входят.

## Bump-процедура (31 файл = SET EQUAL с процедурой 105)

| Что | Файл(ы) | Правка |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.105"` → `"2.58.106"` (комментарий не тронут) |
| Версия | `README.md` | `v2.58.105` → `v2.58.106` (единственная строка версии) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.105`→`2.58.106`; HEAD (short) `7e42c7ee`→`edab6582` |
| 24 py-пина | 24 файла `tests/test_*.py` | `2.58.105`→`2.58.106` (polygon — 2 строки) |
| 4 js-пина | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.105` → `2\.58\.106` (regex) |

`git diff --shortstat` по bump-набору = **31 файл, +33/-33**. Каждая изменённая
строка = только version/HEAD-токены (bump-verify, 33 пары). Каталог не
реиздавался (REGISTRY 582, Δ=0; F8 `--check` зелёный — **582 == REGISTRY**).

Отличие от 105: **set-config правка не нужна** — поезд 106 не добавил ни одного
нового JS-теста (js-unit остаётся 39; в 105 регистрировали mini-lens binding).
Регистрация новых тестов 14.1/14.2 — штатная: `tests/test_soul14_telemetry_extent.py`
и `tests/test_soul14_layers_payload.py` подбираются pytest автоматически
(`pytest.ini: testpaths = tests`; collect-only = 17 тестов), e2e
`tests/ui_soul14_layers_e2e.py` — самостоятельный раннер по конвенции ui-e2e
(встроенный HTTP-сервер + venv playwright, запуск
`.venv/Scripts/python.exe tests/ui_soul14_layers_e2e.py`).

## Guards

| Гвард | Результат | Статус | Артефакт |
|---|---|---|---|
| Offline-агрегат процедуры (16 проверок: settings/README/meta/набор=31/SET EQUAL proc-105/foreign-guard/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release/фингерпринт 037080375ac8 live/import) | **EXIT 0, 16/16 PASS** | VERIFIED | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только version/HEAD-токены | files=31, pairs=33 (30 замен + meta-версия + meta-HEAD + polygon-дубль = 33), CHECK OK | VERIFIED | `bump-verify.txt` |
| SET EQUAL с процедурой 105 | ref(105) 31 == bump(106) 31; ONLY IN 105: none; ONLY IN 106: none | VERIFIED | `delta-vs-105.txt` |
| ΔDDL (bump-scope + release-to-release; != 0 ⇒ STOP) | **0 файлов** в DDL-периметре bump-набора; схема v37 не тронута; в дельте поезда из DDL-периметра только `services/chat_migration.py` (cdb0492f) — в добавленных строках 0 DDL-токенов (бэкап-логика, не схема) | VERIFIED | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | VERIFIED | `focused-f8-pins.txt` |
| pins24: все 24 py пин-теста | **868 passed / 0 failed, EXIT 0** — идентично 101–105 | VERIFIED | `pins24-summary.md`, scratch `pkg-106/pins24-full.txt` |
| Help-sync `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | VERIFIED | `focused-help-sync.txt` |
| JS-unit sweep `test_webapp_js_unit.py` | **39 passed**, EXIT 0 (без изменений набора — поезд не добавил JS-тестов) | VERIFIED | `focused-js-unit.txt` |
| 4 js пин-регрессии + mini-lens через node | **5/5 OK, EXIT=0** | VERIFIED | `js-pins-node.txt` |
| JS-syntax sweep `node --check` (web + tests/js) | **files=107 bad=0**, EXIT 0 (те же 107, что в proc-105 — новых .js в поезде нет) | VERIFIED | `js-pins-node.txt` |
| F8-генератор `gen_param_registry_round1025.py --check` | **CHECK OK (582 == REGISTRY)**, EXIT 0 | VERIFIED | `gen-param-check.txt` |
| 14.1 e2e `tests/ui_soul14_layers_e2e.py` | **5 сценариев (360/390/no-layers-390/unknown-360/desktop), failures=0, EXIT 0** (двойной прогон, отчёт с per-scenario JSON) | VERIFIED | `soul14-layers-e2e.txt`, `layers-e2e-report.json` |
| 14.1 payload `test_soul14_layers_payload.py` | **6 passed**, EXIT 0 | VERIFIED | `focused-soul14-payload.txt` |
| 14.2 телеметрия `test_soul14_telemetry_extent.py` | **11 passed**, EXIT 0 | VERIFIED | `focused-soul14-telemetry.txt` |
| Write-points `test_mca01… -k write_points` | **1 passed** (32 deselected), EXIT 0 | VERIFIED | `focused-write-points.txt` |
| Фингерпринт заводского набора | `factory_set_fingerprint()` == `FACTORY_SET_SHA256_12` == **`037080375ac8`** (runtime-проба), `services/prompt_registry.py` не в дельте | VERIFIED | offline-агрегат + `frozen-fingerprint.txt` |
| settings import | `APP_VERSION == 2.58.106` | VERIFIED | офлайн-агрегат |

## ΔDDL (2.58.105 → 2.58.106) — 0, миграций не требуется

Двойная проверка в `ddl-check.txt`:

- ΔDDL **bump-пакета** = 0 (ни `services/database.py`, ни `scripts/`, ни
  миграционных сервисов: файлов периметра в наборе нет);
- ΔDDL **release-to-release** = 0 (схема SQLite остаётся **v37**;
  `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` на HEAD неизменна; в дельте
  `a6246e33..edab6582` из DDL-периметра затронут только
  `services/chat_migration.py` (cdb0492f) — скан добавленных строк на
  CREATE TABLE / ALTER TABLE / ADD COLUMN / user_version / DDL_STATEMENTS:
  **0 попаданий** — это бэкап строк перед transfer, не схема).
  DevOps-уведомление о миграции не требуется.

## Изоляция от параллельных лейнов: факты

1. Bump-файлы изменялись **явным перечислением процедуры** (скрипт
   `OPENCODE_WORKFLOW_SCRATCH/pkg-106/bump_258106.py`), а не `git status`.
2. Pre-bump сверка: 280 dirty/untracked файлов в дереве (параллельные лейны
   soul-1 A/B-док, cfg и др.), **overlap с bump-набором = 0**
   (`precheck_258106.py`, PASS; factcheck/06G.3-guard файлов в наборе = 0).
3. Финальный diff `git diff --name-only`: 213 файла = 31 bump + evidence +
   чужие грязные файлы параллельных лейнов (**в пакет НЕ входят**); полный
   список — `final-diff-names.txt`.
4. Коммит — только явный pathspec (31 bump-файл + эта директория evidence);
   чужие staged/dirty изменения не включаются. Пуш/деплой — вне лейна.

## Отличия от процедуры 105 (кроме номеров)

1. Версия 2.58.106 — обычный инкремент, rollover-логики нет.
2. F8-meta HEAD = `edab6582` (голова на пребампе; в 105 git HEAD нёс docs-only
   коммит поверх поезда — здесь совпадает со штампом).
3. Set-config-правка не потребовалась (см. выше) — единственное содержательное
   отличие процедуры; SET EQUAL подтверждён офлайн-агрегатом.
