# REL-258119 — релизный поезд P0 2.58.118 → 2.58.119 (24.10.2026)

Полоса `RELEASE-258119`. База — `origin/master` `81431843` (2.58.118).
Worktree `C:\Code\Python\adminbot-wt258119`, ветка `release/2.58.119`.
Прод/SSH в полосе **не трогались**. Только push FF `HEAD:master`.

## Состав поезда

| Этап | SHA | Комментарий |
|---|---|---|
| База (`origin/master`) | `81431843` | 2.58.118 |
| Expression budget/FREQUENT (P0E) | `09f56517` → `466d4dfb` | `-x` |
| Factcheck per-part/evidence/OCR (P0B-база) | `b93f1557` → `022ec0a1` | `-x` — **добавлен как обязательный предок** (см. ниже) |
| Checkup genre canon + Core patch | `9051e9fe` → `0d98ea29` | `-x`, конфликты версии/структуры |
| Factcheck review r1 (F1–F6) | `5b692967` → `c43d0363` | `-x` |
| Prompts/freepseech/provenance/inspector (P0-PROMPTS) | `3fcac03c` → `ce376934` | `-x` |
| Read-path stubs | `c9b47890` → `a985af19` | `-x` |
| FACTORY_SET на фактической базе | `c3ed71a3` | переутверждение отпечатка |
| Bump 2.58.119 | `90915aec` | 31 файл / 33 пары |
| withheld-фикстуры + швы | `c0cfba4d` | сделан self-contained |
| owner-source P0 (byte-pin) | `6613c883` | вернул файл, снятый при разрешении конфликта |

Версия: **2.58.119**. Bump-набор: **31 файл / 33 пары**, `non-token deltas: NONE`
(`bump-verify.txt`), `SET EQUAL` proc-118. F8-meta HEAD-штамп = `c3ed71a3`
(фактический pre-bump HEAD).

## Отклонение от брифа: `b93f1557` (обязательный предок)

Бриф перечислял `5b692967` без его предка `b93f1557`. Факты:

* `tests/test_factcheck_p0_fc.py` на `origin/master` **отсутствует**: файл
  создаёт `b93f1557` (16 тестов), `5b692967` дописывает ещё 12 → **28**;
* гейт брифа `test_factcheck_p0_fc (28)` без `b93f1557` недостижим, а
  `5b692967` патчит несуществующий файл (гарантированный конфликт).

`b93f1557` добавлен как минимально необходимое условие заявленного объёма
(не расширение scope). Числа сошлись: 28 и 529.

## Отклонение: FACTORY_SET

Ожидание брифа `071b1f3ec5f9` **недостижимо** на `origin/master`. Значение на
ветке-фиче считалось от её до-слияния основания. Побайтная сверка 89 блоков
(`factory_texts()`):

| Блок | до (2.58.118) | после |
|---|---|---|
| `checkup.base.system` | `38d63d86b54d` | `0f5fb7b8d25c` |
| `message.checkup_fallback_notice` | `76f1059b73af` | `ba3fe05850c6` |
| `core.personality` | `2ab417d11404` | `5597c09dd5f8` |
| `core.personality.compact` | `9e6a4ec8b1ea` | `8dbb8c10ddc6` |

Изменены ровно 4 фабрики P0, состав набора (89) не менялся. Итог:
`FACTORY_SET_SHA256_12 == factory_set_fingerprint() == 47f0d1eb8de4`
(`frozen-fingerprint.txt`).

## Разрешённые конфликты

1. `services/prompt_migrations.py` (checkup): импорт — union (`PREV_DIRECT_L1_PLANNER_CLAR/_R3`
   из релизной линии + `CORE_REAL_EVENTS_PARAGRAPH` из фичи).
2. `ROLLBACK_MIGRATIONS["prompts.checkup_system_prompt"]`: релизная линия уже
   перешла на многоступенчатые лестницы (`list[tuple]`), фича писала одиночный
   шаг. Разрешено **двумя ступенями**: `0f5fb7b8d25c → 38d63d86b54d → 0ce06cb149f8`
   (P0 → прод-канон 2.58.118 → исторический CFG-07A). Ни одна ступень не потеряна
   (ADR-1013-3).
3. `services/prompt_registry.py`, `tests/test_expression_isolation_followup.py` —
   только токен версии/отпечатка (версия коммита).
4. `plans/.../source-2026-10-24.md` — `modify/delete`: файл создан вне поезда и
   модифицирован `3fcac03c`; удаление ломало 2 byte-pin теста Checkup → файл
   восстановлен из `3fcac03c` побайтно (`6613c883`).

## Найденные и закрытые дефекты поставки

* `tests/test_p0_prompts_core.py` требовал фикстуры
  `plans/.../evidence/withheld/` — у автора они лежали **untracked**, в чистом
  дереве 4 теста падали `FileNotFoundError`. Фикстуры добавлены в поезд.
* `test_p0_prompts_core::test_direct_l2_writer_factory_edition_is_not_a_warning`
  исходил из того, что persisted-байты L2 ≠ заводская редакция. На релизной базе
  они совпадают (`83ff62bbee40`), поэтому `identical_to_factory` не попадает в
  список Inspector — ассерт приведён к правилу P0 (строка отсутствует), сильные
  проверки `resolve_speech_value` сохранены.
* `tests/test_asap_speech_r3b_canon.py` — провенанс-журнал
  `character.prompt_history` теперь пишется отдельным списком (паттерн
  `test_prompt_migrations`), добавлена проверка аттестации L2.
* `tests/test_asap_speech_i_matrix.py` — маркер ветки `frequent` обновлён на
  новую формулировку P0-E.

## Guards

Интерпретатор pytest/py_compile: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`
(Python 3.12). Node: v24.16.0.

| Проверка | Наблюдение | Артефакт |
|---|---|---|
| Bump-verify | files=31, pairs=33, non-token **NONE**, CHECK OK | `bump-verify.txt` |
| F8 `--check` | `582 == REGISTRY`, карта полна, R17-чисто, EXIT 0 | `gen-param-check.txt` |
| Factory fingerprint | `2.58.119 47f0d1eb8de4 47f0d1eb8de4` | `frozen-fingerprint.txt` |
| F8-пины | 29 passed | `focused-core.txt` |
| help-sync | 21 + 24 passed | `focused-core.txt` |
| pins24 | **868 passed / 0 failed** | `pins24-full.txt` |
| JS-unit (`node --test "tests/js/*.js"`) | **90 pass / 0 fail** | `js-unit.txt` |
| JS-syntax (`node --check`) | 90 файлов / 0 bad | `js-syntax.txt` |
| py_compile изменённых py | 70 файлов / rc=0 | `py-compile.txt` |
| Focused core + P0 (17 файлов) | **299 passed** | `focused-core.txt` |
| `test_soul1_composer_parity_off.py` | **13 passed** | run log |
| `test_speech_inspector_exact.py` | **17 passed** | run log |
| `test_p0_checkup_core_contract.py` | **12 passed** | run log |
| `test_asap3_hidden_limits.py` | **16 passed** | run log |
| `test_factcheck_p0_fc.py` | **28 passed** | `factcheck-p0-fc.txt` |
| `-k "factcheck or search_aggregator or temporal"` | **529 passed** | `factcheck-sweep.txt` |
| Широкий фильтр `prompt\|speech\|registry\|provenance\|core` | **1461 passed / 0 failed** | `wide-filter.txt` |
| ΔDDL | **0** | `ddl-check.txt` |
| W4 UI e2e | падает и на базе 2.58.118 → pre-existing, не поездом | `e2e-w4.txt` |
| ASAP3 hint e2e | скрипт отсутствует в репозитории — не воспроизведён (не PASS) | — |

## ΔDDL

**0** (`ddl-check.txt`): 0 DDL-токенов в прод-периметре (`services/`, `web/`,
`config/`, `scripts/`, `tools/`) на диапазоне `81431843..HEAD`. Schema-дельта
отсутствует.

## UI-активы

Изменены намеренно (P0-PROMPTS, Inspector saved-vs-active):
`web/api/speech.py`, `web/app.js`, `web/index.html` (`frozen-assets.txt`).
Это не «frozen-0» предыдущего поезда; регресс подтверждён тестами
`test_speech_inspector_exact.py` (17) и `test_p0_prompts_core.py`.

## Откат

См. `rollback.md`.

## Ограничения полосы

* Repository-wide pytest не гонялся; широкий фильтр
  `prompt|speech|registry|provenance|core` — **1461 passed, 0 failed** (`wide-filter.txt`).
  На неизменённой базе `81431843` тот же фильтр даёт 2 RED
  (`test_soul1_machine_profile_no_core`, `test_soul1_w5_observer_gates`) — их закрывает
  `c9b47890`, в поезде они зелёные.
* W4 UI e2e (`tools/ui_soul1_w4_speech_e2e.py --no-shots`) падает **и на неизменённом
  дереве** (`adminbot-wt258115`, 2.58.118): «карточек 0, ожидалось 20» в «Примерах»
  на 320/390/430. Классификация: pre-existing/окружение, поездом не внесено.
* ASAP3 hint e2e (10 проверок) в полосе не воспроизведён: скрипт прошлой полосы жил
  в scratch и в репозитории отсутствует. Пропуск зафиксирован, не выдан за PASS.
* Живых чат-проб и деплоя нет.
