# Release 2.58.120 — P0 финальный выпуск (RELEASE-258120)

**База:** `41ba6bc6` (ветка `release/2.58.119`, версия 2.58.119, факт-сет `47f0d1eb8de4`).
**HEAD:** `913cdb27` (bump 2.58.119 → 2.58.120).
**Версия:** `2.58.120`.

## Состав (2 пика + bump)

| Коммит | Что |
|---|---|
| `cd0c4d1a` | cherry-pick `81864863` — Expression: снапшоты FREQUENT выровнены под owner-переписку (ASAP W1 s3.4 → P0-E s6.3), +3 файла (evidence `expression.md`, `test_add_exp_expression.py`, `test_asap_w1_semantics.py`) |
| `d928708a` | cherry-pick `57efa10a` — Initiative: измеримая телеметрия формы доставки (audit G1–G7): decision несёт delivery/targets/corp, `status=action.kind`, manifest form/reply/mismatch + непустой `config_version`, ledger `parent_message_ref`, whitelisted `target_*` причины, `entity_id` корреляция сохранена; реакция не отчитывается как reply. 10 файлов, из них новый `tests/test_initiative_delivery_telemetry.py` (11 тестов) |
| `913cdb27` | bump 2.58.119 → 2.58.120, 31 файл (proc-сет), F8-meta HEAD-штамп `d928708a` |

**Конфликты cherry-pick:** нет (оба пика применились чисто; `direct_chat_service.py`,
`test_asap_w1_semantics.py`, `test_mca17c_invariants_round1047.py` — auto-merge без
конфликтных маркеров).

## FACTORY_SET

`APP_VERSION=factory_set_fingerprint()=FACTORY_SET_SHA256_12` →
`2.58.120 47f0d1eb8de4 47f0d1eb8de4` (`frozen-fingerprint.txt`).
**SET EQUAL proc-119**: набор промптов/параметров не менялся относительно 2.58.119.

## Guards

Интерпретатор: `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (Python 3.12.0),
Node v24.x. Каталог артефактов — этот.

| Проверка | Наблюдение | Артефакт |
|---|---|---|
| Bump-verify | files=31, pairs=32, non-token deltas **NONE**, CHECK OK; F8-meta HEAD `d928708a` = pre-bump HEAD | `bump-verify.txt` |
| F8 `--check` | `582 == REGISTRY`, карта полна, R17-чисто, EXIT 0 | `gen-param-check.txt` |
| Factory fingerprint | `2.58.120 47f0d1eb8de4 47f0d1eb8de4` | `frozen-fingerprint.txt` |
| F8-пины | **29 passed** | `f8-pins.txt` |
| help-sync | **21 passed** + **24 passed** | `help-sync.txt`, `help-sync-d14.txt` |
| pins24 (24 файла с версионным пином) | **868 passed / 0 failed** | `pins24-full.txt` |
| JS-unit (`node --test "tests/js/*.js"`) | **90 pass / 0 fail** | `js-unit.txt` |
| JS-syntax (`node --check`) | 90 файлов / 0 bad | `js-syntax.txt` |
| py_compile изменённых py (диапазон `41ba6bc6..HEAD`) | 35 файлов / rc=0 | `py-compile.txt` |
| `test_soul1_composer_parity_off.py` | **13 passed** | `parity.txt` |
| `test_factcheck_p0_fc.py` | **28 passed** | `factcheck-p0-fc.txt` |
| `-k "factcheck or search_aggregator or temporal"` | **529 passed** (15019 deselected) | `factcheck-sweep.txt` |
| `test_p0_checkup_core_contract.py` | **12 passed** | `checkup-core.txt` |
| `test_p0_prompts_core.py` | **9 passed** | `prompts-core.txt` |
| `test_asap3_hidden_limits.py` | **16 passed** | `limits.txt` |
| `test_speech_inspector_exact.py` | **17 passed** | `inspector.txt` |
| `test_initiative_delivery_telemetry.py` | **11 passed** | `initiative-telemetry.txt` |
| initiative + mca-events (7 файлов) | **120 passed** | `initiative-events.txt` |
| ΔDDL | **0** в прод-периметре на `41ba6bc6..HEAD` | `ddl-check.txt` |
| W4 UI e2e (`tools/ui_round1025_matrix.py`) | rc=1, `failures: 178` — **то же самое число на базе 2.58.118 `81431843`** → pre-existing, не поездом | `e2e-w4.txt`, `e2e-w4-base118.txt` |

Файлы обязательного прогона initiative/events: `test_asap8_f6_initiative.py` (23),
`test_asap8_v63_b01_initiative_observer.py` (13), `test_initiative_delivery_telemetry.py` (11),
`test_p0_initfix_initiative_observer.py` (10), `test_soul1_w5_initiative_vitality.py` (18),
`test_mca13_event_contract_round1027.py` (25), `test_mca17_perimeter_events.py` (20) = **120**.
Замечание: в evidence пика записан глоб `test_mca*events*`, который буквально не ловит
`test_mca13_event_contract_round1027.py`; число 120 достигается на `test_mca*event*`.

## Отличия от bump-сета 2.58.119

`pairs=32` вместо `33`: то же множество 31 файла, но `tests/test_scope_selector_round1025.py`
сейчас несёт один версионный токен вместо двух (файл менялся в поезде 2.58.119).
Множество файлов совпадает с proc-сетом 2.58.119.

## Ограничения полосы

* Repository-wide pytest не гонялся (как в предыдущих поездах).
* Деплой не выполнялся: прод остаётся на 2.58.118 (`9ed68ee8`).

## Откат

См. `rollback.md`. Точка отката базы — `41ba6bc6` (2.58.119), пре-bump — `d928708a`.
