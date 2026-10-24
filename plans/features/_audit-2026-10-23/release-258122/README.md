# Release 2.58.122 — трейн подготовки (RELEASE-258122)

**База:** `999e547a` (ветка `release/2.58.119`, версия 2.58.121, FACTORY_SET `47f0d1eb8de4`).
**Pick:** `324868f0` — cherry-pick `7209532f`.
**Bump:** `c128675a` (2.58.121 → 2.58.122).
**Версия:** `2.58.122`. **Не задеплоено.**

## Состав (1 cherry-pick + bump)

| Коммит | Что |
|---|---|
| `324868f0` | cherry-pick `7209532f` — Full Core patch владельца подключается к стартовой миграции канона (B1). 4 файла, +333/−3: `services/prompt_factory.py`, `services/prompt_migrations.py`, `tests/test_p0_checkup_core_contract.py`, evidence `core-patch-wire.md`. Конфликтов нет (auto-merge двух файлов, правок вручную не потребовалось). |
| `c128675a` | bump 2.58.121 → 2.58.122: 31 файл / 33 версионных токена, F8-meta HEAD = `324868f0`, ΔDDL=0 |

**FACTORY_SET:** `2.58.122 47f0d1eb8de4 47f0d1eb8de4` — **не меняется** (SET EQUAL proc-121).

## Guards (venv Python 3.12, Node v24)

| Проверка | Результат | Файл |
|---|---|---|
| bump-verify | files=31, pairs=33, non-token deltas **NONE**, F8-meta HEAD=`324868f0` = pre-bump HEAD, APP_VERSION 2.58.122 | `bump-verify.txt` |
| F8 `--check` | EXIT 0 (реестр 582 == REGISTRY, карта полна, R17-чисто) | `gen-param-check.txt` |
| Factory fingerprint | `47f0d1eb8de4` == константа | `frozen-fingerprint.txt` |
| pins24 (24 файла версионных пинов) | **867 passed / 1 failed** — см. ниже | `pins24-full.txt` |
| help-sync | **21 passed** + **24 passed** | `guards-compact.txt` |
| core-patch (checkup) | **16 passed** (было 12; +4 теста из pick) | `guards-compact.txt` |
| prompts | **9 passed** | `guards-compact.txt` |
| factcheck | **28 passed** | `guards-compact.txt` |
| telemetry | **13 passed** | `guards-compact.txt` |
| composer parity | **13 passed** | `guards-compact.txt` |
| `test_prompt_migrations` (pick-механизм) | **43 passed** | `guards-compact.txt` |
| JS-unit (`node --test tests/js/*.js`) | **90 pass / 0 fail** | `js-unit.txt` |
| JS-syntax (`node --check`) | checked=90, bad=0 | `js-syntax.txt` |
| py_compile (`999e547a..HEAD`) | 3 файла, rc=0 | `py-compile.txt` |
| ΔDDL | **0** (в diff только `prompt_factory.py`/`prompt_migrations.py`, схемы не тронуты) | `ddl-check.txt` |

## Единственный красный тест — pre-existing

`tests/test_summary_publish_integration_round1026.py::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article`
падает (`_deliver_l2_rich.assert_awaited_once()` → awaited 0 times) **и на базе `999e547a` без pick и без bump**
(проверено детач-чекаутом `999e547a`: тот же FAILED, 1 failed). Причина — окружение воркtree: в
`adminbot-wt258119` нет `.env`, поэтому runtime-настройки отличаются от основного репозитория; версия/pick
на результат не влияют. Итог: 867+1 = 868 тестов, счёт не изменился относительно 2.58.121.

## Откат

См. `rollback.md`. Точка отката — `999e547a` (2.58.121); без-bump код — `324868f0`.
