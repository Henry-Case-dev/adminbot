# REL-258107 — релизный бамп 2.58.106 → 2.58.107 (PKG-107, 22.10.2026)

Лейн PKG-107. Процедура — бамп-прецедент 106
(`OPENCODE_WORKFLOW_SCRATCH/pkg-107/{precheck,bump,verify}_258107.py`).
Дельта — только версия/HEAD-токены + release evidence (жёсткий pathspec); чужой
dirty-worktree (181 файл других лейнов) не захвачен.

## Состав релизной дельты (2.58.106 → 2.58.107, все Approved)

| Коммиты | Суть |
|---|---|
| `97818475` + `50c825ab` | FC-R1 — фактчек: единый retrieval для envelope + смысловые запросы + evidence-quality + per-claim вердикты + биндинг рендерера; cfg-map rows (FC-UNIFY/FC-SEMQUERY/FC-EVIDQ/FC-PERCLAIM/FC-RENDER) |
| `47522e7b` | corrective L1 — позитивные критерии react/silent в каноне L1 + контекст предыдущих ответов бота |
| `44a4827a` | corrective expression — изоляция мата в Expression, тема мата удалена из Core и всех канонов (fingerprint `037080375ac8` → **`c19d35a1c093`**) |
| `d8bade8d` | corrective nostalgia — право отказа и семантическая оценка кандидата вместо императивов |
| `4d9fd4be` + `bbcafef5` | docs — директивы владельца 21.10 и три диагностических отчёта с отметками о фиксах |

F8-meta HEAD-токен = **`bbcafef5`** — голова релизной дельты PKG-107 (бриф explicit:
«голова на пребампе»; git HEAD на пребампе = `bbcafef5`, расхождений нет).

## Bump-набор (31 файл = SET EQUAL процедуре 106)

| Роль | Файл(ы) | Замена |
|---|---|---|
| Версия | `config/settings.py` | `APP_VERSION = "2.58.106"` → `"2.58.107"` (только версия, комментарий без изменений) |
| Версия | `README.md` | `v2.58.106` → `v2.58.107` (единственная строка версии) |
| F8-meta | `plans/docs/param-registry-round1025.meta.md` | APP_VERSION `2.58.106`→`2.58.107`; HEAD (short) `edab6582`→`bbcafef5` |
| 24 py-пина | 24 файла `tests/test_*.py` | `2.58.106`→`2.58.107` (polygon — 2 вхождения) |
| 4 js-пина | 4 файла `tests/js/round1025_hotfix{7,8,9,10}_*.js` | `2\.58\.106` → `2\.58\.107` (regex) |

`git diff --shortstat` по bump-набору = **31 файл, +33/-33**. Содержательные
изменения релиза = только version/HEAD-токены (bump-verify, 33 пары). Каталог
не тронут (REGISTRY 582, Δ=0; F8 `--check` подтверждает: **582 == REGISTRY**).

Отличие от 106: набор фактчек/corrective-коммитов уже в истории (бриф INPUTS
HEAD = `bbcafef5`); новых UI/JS в поезде нет (syntax-sweep 107/0 = база 106).
Канонные счётчики каталога (582/171) НЕ пересанкционировались — corrective
меняла каноны промптов (`prompt_registry` FACTORY_SET, `prompt_migrations`
лестница), а не param-каталог; F8 `--check` зелёный без диагностики.

**Fingerprint:** гвард сверяет с НОВЫМ `c19d35a1c093` (бриф PKG-107 explicit:
старый `037080375ac8` больше не актуален). Источник константы —
`services/prompt_registry.py: FACTORY_SET_SHA256_12 = "c19d35a1c093"`
(обновлён corrective-волной `44a4827a`); офлайн-гвард сверяет
runtime `factory_set_fingerprint()` == константа == `c19d35a1c093` — PASS;
регрессия `tests/test_expression_isolation_followup.py` (в corrective-наборе)
тоже держит новое значение. Обновления источника константы не потребовалось.

## Guards

| Проверка | Результат | Статус | Артефакт |
|---|---|---|---|
| Pre-bump (HEAD on train, overlap dirty∩bump=0, foreign-guard, токены, set=31) | PASS | VERIFIED | scratch `pkg-107/` (лог ниже в bump-offline-check) |
| Offline-агрегат (16 проверок: settings/README/meta/версии=31/SET EQUAL proc-106/foreign-guard/пары=33/каталог 582/171/ΔDDL=0 bump-scope и release-to-release/fingerprint c19d35a1c093 live+import) | **EXIT 0, 16/16 PASS** | VERIFIED | `bump-offline-check.txt` |
| Bump-verify: каждая изменённая строка = только version/HEAD-токены | files=31, pairs=33, CHECK OK | VERIFIED | `bump-verify.txt` |
| SET EQUAL с процедурой 106 | ref(106) 31 == bump(107) 31; ONLY IN 106: none; ONLY IN 107: none | VERIFIED | `delta-vs-106.txt` |
| ΔDDL (bump-scope + release-to-release; ≠ 0 → STOP) | **0 файлов** в bump-наборе из DDL-периметра; схема v37 не менялась; в release-дельте `83012fcf..HEAD` из периметра только `services/prompt_migrations.py` — cumulative diff без DDL-токенов (лестница канонов); database.py/chat_migration.py/config_migrations.py не тронуты | VERIFIED | `ddl-check.txt` |
| F8-пины `test_round1025_f8_registry.py` | **29 passed**, EXIT 0 | VERIFIED | `focused-f8-pins.txt` |
| pins24: все 24 py пин-файла | **868 passed / 0 failed, EXIT 0** — паритет 101–106 | VERIFIED | `pins24-summary.md`, scratch `pkg-107/pins24-full.txt` |
| Help-sync `test_asap8_v6_d14_help_sync.py` | **24 passed**, EXIT 0 | VERIFIED | `focused-help-sync.txt` |
| JS-unit `test_webapp_js_unit.py` | **39 passed**, EXIT 0 (набор не менялся — новых JS в поезде нет) | VERIFIED | `focused-js-unit.txt` |
| Node пин-регрессы | **5/5 OK** (4 js-пина + mini-lens) | VERIFIED | `js-pins-node.txt` |
| JS-syntax sweep (`node --check` web/ + tests/js) | **107 файлов / 0 bad**, EXIT 0 (= база 106) | VERIFIED | `js-pins-node.txt` |
| F8-генератор `--check` | **CHECK OK: реестр 582 == REGISTRY**, карта полна, R17-чисто, TSV/map идемпотентны, EXIT 0 | VERIFIED | `gen-param-check.txt` |
| Write-points single-writer (`test_mca01_...` `-k write_points`) | **1 passed**, 32 deselected, EXIT 0 | VERIFIED | `focused-write-points.txt` |
| NEW: фактчек `test_factcheck_fc_r1_fix.py` | **22 passed**, EXIT 0 | VERIFIED | `focused-factcheck-fc-r1.txt` |
| NEW: corrective выборка (L1 `test_direct_l1_corrective_r1` + expression `test_expression_isolation_followup` + nostalgia `test_nostalgia_corrective_r1`) | **25 passed**, EXIT 0 | VERIFIED | `focused-corrective.txt` |

## Изоляция

Полный снимок `git diff --name-only` — `final-diff-names.txt` (181 чужой
dirty/untracked файл других лейнов не входит в пакет). Коммит — только 31 файл
+ `plans/features/corrective-fix-2026-10-21/release-258107/` (этот каталог).
Review-evidence других лейнов (`review-corrective-r1.md`, `review-fc-r1.md`)
в pathspec не входят (foreign-guard PASS).

Не в скоупе лейна: пуш и деплой (по брифу PKG-107).

## Замечания (честные)

- Комментарий `APP_VERSION` в settings.py остался от волны asap8-v6 (прецедент
  105/106: при бампе комментарий не переписывается, описание релиза живёт в
  commit message и этом README).
- Исторические ссылки «прод 2.58.106 = ровно эти байты»
  (`services/chat_prompts.py:548`, `services/prompt_migrations.py:156`,
  `tests/test_direct_l1_corrective_r1.py`) — провенанс прод-байтов 2.58.106,
  не пины версии; намеренно не менялись (после деплоя 107 факт «прод 106»
  остаётся исторически верным для зафиксированных канон-байтов).
