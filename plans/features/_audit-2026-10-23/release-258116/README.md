# REL-258116 — релизный поезд 2.58.115 → 2.58.116 (24.10.2026)

Лейн `RELEASE-258116`. База — tip ветки `release/2.58.115` (`e5e32179`, версия 2.58.115).
Работа — в отдельном worktree `C:\Code\Python\adminbot-wt258115`.
Основной чекаут не изменялся. Прод/SSH не затрагивались.

## Точки

| Что | SHA |
|---|---|
| База (`release/2.58.115` = 2.58.115) | `e5e32179d7ae86ebbde91b685e56bb64b76b587e` |
| Cherry-pick inspector r2 (`4553495a`) | `d47c2aab4e32cb508c1b5157ca1d9a205b93b38d` |
| Pre-bump HEAD поезда (F8-meta HEAD-токен) | `3f0da7c89e4fa54a5d265284edb48d2cf50b35cb` |
| Bump-коммит 2.58.116 | `5b31d3998aeeea2709a75c880003937a0b8e60fc` |
| Точка отката (прод 2.58.114) | `e9f7595bad3f56145078ad599edf4b7182d2e1df` |

Версия: **2.58.116**. Bump-набор: **31 файл / 33 пары строк** (README + settings +
F8-meta + 24 py-пина + 4 JS-пина), `SET EQUAL` процедуре 114/115.

## Состав поезда

| Функция | Коммит в поезде | Источник |
|---|---|---|
| INS-R17/fallback/error: style-маскировка на границе Inspector, журнал КАЖДОЙ попытки fallback, error-статусы chat/background | `d47c2aab` | `4553495a` (review r2) |
| SOUL-1 OFF parity: эталон перезаписан под каноны R3/R3B (13 passed) | `3f0da7c8` | новое (на базе 5 failed) |

Черри-пик: конфликт был только по документации
`plans/features/asap-speech-arch/evidence/inspector-exact.md` (файл отсутствовал
в ветке). Взята версия коммита (doc-only, кода не касается), семантических
конфликтов **0**. Код/тесты авто-мержились чисто, байты 4 кодовых файлов
сверены с `4553495a`.

Каноны не менялись: `services/prompt_registry.py` отсутствует в дельте,
`factory_set_fingerprint() == FACTORY_SET_SHA256_12 == 0163a686c401`
(probe rc=0; `frozen-fingerprint.txt`). Bump fingerprint не меняет.

## SOUL-1 parity: почему эталон перезаписан

Старый baseline был снят на канонах ASAP 2 (код `5ad73933`, FACTORY_SET
`24ae494ac422`); с 2.58.114 действуют R3 §3.7 (`af7de4e9`) + R3B (`a8d047a7`),
FACTORY_SET `0163a686c401`. Поэтому на базе было 5 failed / 8 passed
(зафиксировано в REL-258115).

Перезапись тем же offline-стендом; тест **не ослаблен** (сравнение len + sha256_12
осталось). Дельта доказана арифметически (`verify_delta.py`, 30/30 checks):

| Секция | before | after | Δ | Причина |
|---|---|---|---|---|
| P1 SYSTEM | 3225 / `1d4c51c39147` | 3479 / `22894e57203b` | +254 | R3B: `"\n\n"` + инструкция о границе истории (252) после §3.1 «КАК ПИСАТЬ» |
| P2 SYSTEM | 3073 / `d7281532954d` | 3327 / `b3c71e14e2a4` | +254 | то же |
| P5b SYSTEM | 3225 / `1d4c51c39147` | 3479 / `22894e57203b` | +254 | то же |
| P4 SYSTEM | 6542 / `c987c03e3ee0` | 8261 / `6c2ddc17c998` | +1719 | R3 §3.7: блок участия W1→R3 (1533→2682) + R3B продолжение §4.1 (+570) |
| P3 SYSTEM | 1324 / `a0bf8aba9cd2` | без изменений | 0 | legacy modes-OFF база R3/R3B не тронута |
| P5a SYSTEM | 1107 / `6bae7eb26bc3` | без изменений | 0 | синтезатор не тронут |
| USER во всех секциях | — | байт-в-байт | 0 | — |

Дополнительно: тот же стенд, прогнанный на коде ASAP 2 (`5ad73933`), даёт
**байт-в-байт** старый артефакт (`parity-base-regen.txt` == `parity-before.txt`),
т.е. эталон не правился руками. Артефакты: `parity-before.txt`,
`parity-base-regen.txt`, `parity-after.txt`, `diff.md`, `verify-delta.txt`,
скрипты `rerecord_parity.py` / `verify_delta.py`.

## ΔDDL

**0** в прод-периметре (`services/`, `web/`, `config/`, `scripts/`, `tools/`):
0 совпадений DDL-токенов в добавленных строках `e5e32179..5b31d399`;
schema/migration-файлы не затронуты. См. `ddl-check.txt`.

## Guards

| Проверка | Результат | Артефакт |
|---|---|---|
| Bump-verify | files=31, pairs=33, non-token **NONE**, CHECK OK | `bump-verify.txt` |
| F8 `--check` | `582 == REGISTRY`, карта полна, R17-чисто, EXIT 0 | `gen-param-check.txt` |
| Factory fingerprint | `2.58.116 0163a686c401 0163a686c401` | `frozen-fingerprint.txt` |
| F8-пины | 29 passed | `focused-core.txt` |
| Frozen-пины канонов (prompt_migrations + clar + r3b + corrective + frozen) | 43 + 24 + 7 + 12 + 4 passed | `focused-core.txt` |
| pins24 (24 файла) | **868 passed / 0 failed** (72.74s) | `pins24-full.txt` |
| help-sync | 21 + 24 passed | `focused-core.txt` |
| JS-unit (`node --test tests/js/*.js`) | 90 pass / 0 fail | `js-pins-node.txt` |
| node-пины + mini-lens | 5/5 rc=0 | `js-pins-node.txt` |
| JS-syntax sweep | 90 файлов / 0 bad | `js-pins-node.txt` |
| py_compile изменённых py | 32 файла / 0 bad | `py-compile.txt` |
| Frozen UI-ассеты | 0 изменённых файлов (`web/index.html`, `app.js`, `static/`) | `frozen-assets.txt` |
| `test_soul1_composer_parity_off.py` | **13 passed** | `focused-core.txt` |
| `test_speech_inspector_exact.py` | **16 passed** | `focused-core.txt` |
| `test_llm_client.py` | **115 passed** | `focused-core.txt` |
| `test_asap3_hidden_limits.py` | **13 passed** | `focused-core.txt` |
| `test_asap3_identity_aliases.py` | **22 passed** | `focused-core.txt` |
| `test_asap2_boundary_marker.py` | **8 passed** | `focused-core.txt` |
| UI e2e Inspector | **checks=142 failures=0** | `e2e-inspector.txt` |
| W4 UI e2e | **failures=0** | `e2e-w4.txt` |
| ASAP3 hint e2e | **PASS: 10 проверок** | `e2e-asap3-hint.txt` |
| Мутационный свидетель эталона | 2/2 мутации **DETECTED**, восстановление green | `mutation-witness.txt` |

## Откат

- Прод-откат: `e9f7595b` (2.58.114) — код без новых коммитов поезда.
- Локально: `git revert 5b31d399 3f0da7c8 d47c2aab` или возврат ветки на `e5e32179`.

## Изоляция / примечания

- Основной чекаут (`C:\Code\Python\adminbot`) не изменялся.
- Временный worktree `C:\Code\Python\adminbot-wt258116base` на `5ad73933`
  использован только для регенерации старого эталона; следов в коммитах нет.
- E2E-скрипты пишут PNG в `plans/features/asap-speech-arch/evidence/inspector/`;
  эти untracked-артефакты в коммит не входят.
- Полный repository-wide pytest в лейне не запускался (запрещено брифом).
- Деплой/SSH не выполнялись: лейн заканчивается FF-пушем `HEAD:master`.
