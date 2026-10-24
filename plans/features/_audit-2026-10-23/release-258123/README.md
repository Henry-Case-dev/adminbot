# Release 2.58.123 — финальный Expression-контракт (RELEASE-258123B)

**База:** `19ff9072` (`origin/master`, версия 2.58.122, FACTORY_SET `47f0d1eb8de4`).
**Pick:** `8d718a04` — cherry-pick `90fc3ad1`, конфликтов нет.
**Bump:** `3dfdf9cb` (2.58.122 → 2.58.123).
**Версия:** `2.58.123`. **Не задеплоено** (по указанию lane).

## Состав (1 cherry-pick + bump)

| Коммит | Что |
|---|---|
| `8d718a04` | cherry-pick `90fc3ad1` — финальный контракт речи в конце system для FREQUENT (тот же источник PROFANITY_INSTRUCTIONS, без квот/постпроцесса); 5 файлов, +559/-3: `services/mca_expression.py`, `services/prompt_composer.py`, `tests/test_p0_expression_final_contract.py` (15), evidence `expression-v2.md` + raw probes. |
| `3dfdf9cb` | bump 2.58.122 → 2.58.123: 31 файл / 32 пары, F8-meta HEAD = `8d718a04`, ΔDDL=0 |

**FACTORY_SET:** `2.58.123 47f0d1eb8de4 47f0d1eb8de4` — без изменений (SET EQUAL proc-122).

## Guards (venv Python 3.12)

| Проверка | Результат | Артефакт |
|---|---|---|
| bump-verify | files=31, pairs=32, non-token deltas **NONE**, F8-meta HEAD=`8d718a04` = pre-bump HEAD, APP_VERSION 2.58.123 | `bump-verify.txt` |
| F8 `--check` | EXIT 0 | `gen-param-check.txt` |
| Factory fingerprint | `47f0d1eb8de4` == `47f0d1eb8de4` | `frozen-fingerprint.txt` |
| composer parity | **13 passed** | `guards-compact.txt` |
| expression final contract | **15 passed** | `guards-compact.txt` |
| prompts | **9 passed** | `guards-compact.txt` |
| checkup | **16 passed** (фактический набор; в брифе ожидалось 12) | `guards-compact.txt` |
| factcheck | **28 passed** | `guards-compact.txt` |
| telemetry | **13 passed** | `guards-compact.txt` |
| py_compile (`19ff9072..HEAD`) | 28 файлов, rc=0 | `py-compile.txt` |
| ΔDDL | **0** (prod perimeter) | `ddl-check.txt` |

Полный pytest и W4 e2e не запускались (pre-existing, вне лимита 12 минут по указанию lane).

## Откат

См. `rollback.md`. Точка отката — `19ff9072` (2.58.122); pick без bump — `8d718a04`.
