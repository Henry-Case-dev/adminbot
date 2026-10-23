# Release 2.58.121 — телеметрия инициативы (RELEASE-258121)

**База:** `95803de0` (ветка `release/2.58.119`, поезд 2.58.120, версия 2.58.120, FACTORY_SET `47f0d1eb8de4`).
**HEAD:** `a2feac65` (bump 2.58.120 → 2.58.121).
**Версия:** `2.58.121`.

## Что добавлено (1 cherry-pick + bump)

| Коммит | Что |
|---|---|
| `1058fb33` | cherry-pick `5d0f8a2a` — Initiative telemetry: закрытие ревью-находок. 5-й пин `REASON_CODES` = 309; `entity_id`→`trace_id` скоупится только к initiative-событиям; `delivery:unknown` для незаданной L1-формы; correlation на recheck-cancel; `react_target` как token. 6 файлов, +114/−35: `services/direct_chat_service.py`, `services/mca_events.py`, `services/mca_intents.py`, `tests/test_initiative_delivery_telemetry.py`, `tests/test_mca10b_random_applications_block_a_round1041.py`, evidence `init-delivery-telemetry.md` |
| `a2feac65` | bump 2.58.120 → 2.58.121, 31 файл (proc-сет), F8-meta HEAD-штамп `1058fb33`, ΔDDL=0 |

**Конфликты cherry-pick:** нет (auto-merge `services/direct_chat_service.py`, дерево чистое).

## FACTORY_SET

`APP_VERSION=factory_set_fingerprint()=FACTORY_SET_SHA256_12` →
`2.58.121 47f0d1eb8de4 47f0d1eb8de4` (`frozen-fingerprint.txt`). **SET EQUAL proc-120**: набор
промптов/фабрик/параметров не изменился относительно 2.58.120.

## Guards (venv Python 3.12.0, Node v24.x; всё зелёное)

| Проверка | Результат | Артефакт |
|---|---|---|
| Bump-verify | files=31, pairs=33, non-token deltas **NONE**, CHECK OK; F8-meta HEAD `1058fb33` = pre-bump HEAD | `bump-verify.txt` |
| F8 `--check` | `582 == REGISTRY`, карта полна, R17-чисто, EXIT 0 | `gen-param-check.txt` |
| Factory fingerprint | `2.58.121 47f0d1eb8de4 47f0d1eb8de4` | `frozen-fingerprint.txt` |
| pins24 (24 файла с пинами версий) | **868 passed / 0 failed** | `pins24-full.txt` |
| help-sync | **21 passed** + **24 passed** | `help-a.txt`, `help-b.txt` |
| JS-unit (`node --test "tests/js/*.js"`) | **90 pass / 0 fail** | `js-unit.txt` |
| JS-syntax (`node --check`) | checked=90, bad=0 | `js-syntax.txt` |
| py_compile (py из `95803de0..HEAD`) | 36 файлов / rc=0 | `py-compile.txt` |
| `test_soul1_composer_parity_off.py` | **13 passed** | `parity.txt` |
| `test_factcheck_p0_fc.py` | **28 passed** | `factcheck.txt` |
| `test_p0_checkup_core_contract.py` | **12 passed** | `checkup.txt` |
| `test_p0_prompts_core.py` | **9 passed** | `prompts.txt` |
| `test_asap3_hidden_limits.py` | **16 passed** | `limits.txt` |
| `test_speech_inspector_exact.py` | **17 passed** | `inspector.txt` |
| `test_initiative_delivery_telemetry.py` | **13 passed** | `telemetry.txt` |
| `test_mca10b_random_applications_block_a_round1041.py` | **17 passed** | `mca10b.txt` |
| initiative + mca-events (7 файлов) | **122 passed** | `initiative-events.txt` |
| ΔDDL (`95803de0..HEAD`) | **0** в `services/ web/ config/ scripts/ tools/` | `ddl-check.txt` |

Состав initiative/events (122): `test_asap8_f6_initiative.py` (23), `test_asap8_v63_b01_initiative_observer.py` (13),
`test_initiative_delivery_telemetry.py` (13), `test_p0_initfix_initiative_observer.py` (10),
`test_soul1_w5_initiative_vitality.py` (18), `test_mca13_event_contract_round1027.py` (25),
`test_mca17_perimeter_events.py` (20). Ранее было 120 — +2 теста пришли с `5d0f8a2a`.

## W4 UI e2e

`tools/ui_round1025_matrix.py` в этом лейне **не перезапускался** (жёсткий лимит лейна). Статус
унаследован из лейна 258120: rc=1, `failures: 178` — **pre-existing**, та же картина на базовой
2.58.118 `81431843` (`../release-258120/e2e-w4.txt`, `../release-258120/e2e-w4-base118.txt`).
Дельта 2.58.120 → 2.58.121 не содержит правок `web/` или UI-ассетов (только telemetry-пик и версия),
поэтому ожидаемый профиль не меняется. Не блокирует.

## Ограничения

* Repository-wide pytest не гонялся (как в 258119/258120).
* Поезд 2.58.121 **не задеплоен**.

## Откат

См. `rollback.md`. Точка отката — `95803de0` (2.58.120), до-bump — `1058fb33`.
