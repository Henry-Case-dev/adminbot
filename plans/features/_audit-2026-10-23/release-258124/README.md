# Release 2.58.124 — кавычки (A/B), удаление квот инструкций, UI-cleanup, A7/F2 fix (RELEASE-258124)

**База:** `6e587696` (`origin/master`, версия 2.58.123, FACTORY_SET `47f0d1eb8de4`).
**Bump:** `39a06b88` (2.58.123 → 2.58.124).
**Версия:** `2.58.124`. **Не задеплоено** (деплой вне этой lane).

## Что вошло (4 cherry-pick + bump)

| Коммит | Что |
|---|---|
| `f00050a5` | cherry-pick `0315696b` — детерминированные режимы кавычек A/B (ADDENDUM #3 §1): `services/style_policy.py`, `services/prompt_style_blocks.py`, UI-пресеты (`web/app.js`, `web/index.html`), тесты `test_quotes_modes.py` (30). |
| `42657294` | cherry-pick `73963d0c` — удаление искусственных квот инструкций A1–A6 (ADDENDUM #3 §2.7): `prompt_composer.py`, `mca_expression.py`, `mca_gates.py`, `prompt_registry.py`; `test_quota_removal_composer.py` (8). |
| `4df74a81` | cherry-pick `9f0f6ce8` — снятие composer-budget plumbing из speech API/UI (QUOTA-UI-CLEANUP): `web/api/speech.py`, `prompt_registry.py`. |
| `58b1bcca` | cherry-pick `b4b26376` — снятие капа owner-note и сведение quotes-пресета к одному правилу (fix A7/F2). |
| `39a06b88` | bump 2.58.123 → 2.58.124: 31 файл / 33 пары, F8-meta HEAD = `58b1bcca`, ΔDDL=0. |

Конфликтов не было (два auto-merge в `services/prompt_registry.py` — версия коммита принята целиком).

**FACTORY_SET:** `2.58.124 47f0d1eb8de4 47f0d1eb8de4` — **не изменился** (удаление квот не трогает байты канонов).

## Guards (venv Python 3.12, node v24.16.0)

| Проверка | Результат | Файл |
|---|---|---|
| bump-verify | files=31, pairs=33, non-token deltas **NONE**, F8-meta HEAD=`58b1bcca` = pre-bump HEAD, APP_VERSION 2.58.124 | `bump-verify.txt` |
| F8 `--check` | CHECK OK (582 == REGISTRY) | `gen-param-check.txt` |
| Factory fingerprint | `47f0d1eb8de4` == `47f0d1eb8de4` (SET EQUAL) | `frozen-fingerprint.txt` |
| quotes modes | **30 passed** | `guards-compact.txt` |
| quota removal | **8 passed** | `guards-compact.txt` |
| asap3 acceptance | **8 passed** | `guards-compact.txt` |
| parity (composer OFf) | **13 passed** | `guards-compact.txt` |
| expression final contract | **15 passed** | `guards-compact.txt` |
| prompts core | **9 passed** | `guards-compact.txt` |
| checkup core | **16 passed** (в брифе указано 12 — фактическое число 16, как и в 2.58.123) | `guards-compact.txt` |
| factcheck P0-FC | **28 passed** | `guards-compact.txt` |
| initiative telemetry | **13 passed** | `guards-compact.txt` |
| help-sync (f9) | **21 passed** | `guards-compact.txt` |
| help-sync (d14) | **24 passed** | `guards-compact.txt` |
| prompt migrations | **43 passed** | `guards-compact.txt` |
| JS unit suite | **39 passed** (node) | `guards-compact.txt` |
| JS syntax (`node --check`) | checked=99 bad=0 | `js-syntax.txt` |
| pins24 (24 версионно-запиненных файла) | **868 passed** | `pins24-full.txt` |
| py_compile (изменённые .py `6e587696..HEAD`) | 44 файла, rc=0 | `py-compile.txt` |
| ΔDDL | **0** (prod perimeter) | `ddl-check.txt` |

Примечание: в 2.58.123 падал `test_summary_publish_integration_round1026::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article` (pre-existing); на этом кандидате он проходит — 868 passed без падений.

## Откат

См. `rollback.md`. Холодный откат — `6e587696` (2.58.123); pick'и без bump — `58b1bcca`.
