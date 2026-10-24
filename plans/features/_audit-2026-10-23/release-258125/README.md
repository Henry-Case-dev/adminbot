# Release 2.58.125 — URL-quotes fix (QUOTES-URL-FIX) (RELEASE-258125)

**База:** `76004f34` (`origin/master` на момент push: docs-only привязка requirements map поверх релизного tip `c6290ca1` = 2.58.124; APP_VERSION 2.58.124, FACTORY_SET `47f0d1eb8de4`).
**Pick:** `6e9f10a2` (cherry-pick `f0092e8a`).
**Bump:** `f0e6a0cd` (2.58.124 → 2.58.125).
**Версия:** `2.58.125`. **Задеплоено** 24.10.2026 (прод 2.58.125 @ `f0e6a0cd`); привязка карты P0 — `plans/features/p0-corrective-factcheck-speech/evidence/binding-258125.md`.

Во время lane `origin/master` ушёл вперёд (`c6290ca1` → `76004f34`, только `plans/**`), поэтому train перебазирован на `76004f34`; guard-прогоны выполнены на итоговом кандидате.

## Что в релизе (1 cherry-pick + bump)

| Коммит | Что |
|---|---|
| `6e9f10a2` | cherry-pick `f0092e8a` — `fix(style): keep guillemets inside URLs protected (QUOTES-URL-FIX)`: `services/style_policy.py` — кавычки-ёлочки внутри URL больше не «закрываются» посреди ссылки; `tests/test_quotes_modes.py` +31 строка (quotes 30 → 40). Конфликтов при pick не было. |
| `f0e6a0cd` | bump 2.58.124 → 2.58.125: 31 файл / 33 пары, F8-meta HEAD = `6e9f10a2`, ΔDDL=0. |

**FACTORY_SET:** `2.58.125 47f0d1eb8de4 47f0d1eb8de4` — **не изменился** (каноны промптов не тронуты).

## Guards (venv Python 3.12, node v24.16.0)

| Проверка | Результат | Артефакт |
|---|---|---|
| bump-verify | files=31, pairs=33, non-token deltas **NONE**, F8-meta HEAD=`6e9f10a2` = pre-bump HEAD, APP_VERSION 2.58.125 | `bump-verify.txt` |
| F8 `--check` | CHECK OK (582 == REGISTRY) | `gen-param-check.txt` |
| Factory fingerprint | `47f0d1eb8de4` == `47f0d1eb8de4` (SET EQUAL) | `frozen-fingerprint.txt` |
| quotes modes | **40 passed** (было 30 в 2.58.124; +10 от pick) | `guards-compact.txt` |
| quota removal | **8 passed** | `guards-compact.txt` |
| asap3 acceptance | **8 passed** | `guards-compact.txt` |
| parity (composer OFF) | **13 passed** | `guards-compact.txt` |
| pins24 (24 пиновых-процессных файла) | **868 passed** | `pins24-full.txt` |
| py_compile (изменённые .py `76004f34..HEAD`) | 27 файлов, rc=0 | `py-compile.txt` |
| ΔDDL | **0** (prod perimeter) | `ddl-check.txt` |

## Откат

См. `rollback.md`. Холодный откат — `76004f34` (2.58.124); pick без bump — `6e9f10a2`.
