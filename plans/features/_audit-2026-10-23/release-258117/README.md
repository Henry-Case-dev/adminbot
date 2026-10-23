# REL-258117 — релизный поезд 2.58.116 → 2.58.117 (24.10.2026)

Лейн `RELEASE-258117`. База — tip ветки `release/2.58.115` (`be3e83d1`, версия 2.58.116).
Работа — в отдельном worktree `C:\Code\Python\adminbot-wt258115`.
Основной чекаут не изменялся. Прод/SSH не затрагивались, деплой не выполнялся.

## Точки

| Что | SHA |
|---|---|
| База (`release/2.58.115` = 2.58.116) | `be3e83d1` |
| Cherry-pick inspector r3 (`64785490`) | `d10fd151` |
| Pre-bump HEAD поезда (F8-meta HEAD-токен) | `d10fd151` |
| Bump-коммит 2.58.117 | `724b77ac` |
| Точка отката (прод 2.58.114) | `e9f7595b` |

Версия: **2.58.117**. Bump-набор: **31 файл / 33 пары строк** (README + settings +
F8-meta + 24 py-пина + 4 JS-пина), `SET EQUAL` процедуре 114/115/116, `non-token deltas NONE`.

## Состав поезда

| Функция | Коммит в поезде | Источник |
|---|---|---|
| INS-R17/fallback/error (r2, style-маскировка, журнал каждой попытки, error-статусы) | `d47c2aab` — уже в базе 2.58.116 | `4553495a` |
| SOUL-1 OFF parity: эталон под каноны R3/R3B (13 passed) | `3f0da7c8` — уже в базе 2.58.116 | — |
| Inspector r3: `generate_chat` primary-error пишет журнал КАЖДОЙ фактической HTTP-попытки через `_record_sent_attempts` | `d10fd151` | `64785490` (review r3) |

Черри-пик: **конфликтов 0** (git auto-merge `services/llm_client.py`; исходный коммит не
трогает файл версии). Байты `tests/test_speech_inspector_exact.py` и
`plans/features/asap-speech-arch/evidence/inspector-exact.md` совпадают с `64785490`
(`git rev-parse <commit>:<path>`). `services/llm_client.py` отличается от `64785490`
ровно на **+45 строк уже существующей в базе** работы (EMBED-META-WIRE, CANARY-03);
диф `64785490:llm_client` → `d10fd151:llm_client` состоит только из этих вставок —
удалений нет, т.е. хунк r3 применён байт-в-байт, локального дрейфа нет.

## Каноны / fingerprint

`services/prompt_registry.py` в дельте отсутствует:
`factory_set_fingerprint() == FACTORY_SET_SHA256_12 == 0163a686c401` на 2.58.117
(probe rc=0, `frozen-fingerprint.txt`). Bump fingerprint не меняет.

## ΔDDL

**0** в прод-периметре (`services/`, `web/`, `config/`, `scripts/`, `tools/`):
4 добавленные строки в периметре, 0 DDL-токенов за диапазон `be3e83d1..724b77ac`
(`ddl-check.txt`). Schema/migration-файлы не затронуты.

## Guards

| Проверка | Результат | Артефакт |
|---|---|---|
| Bump-verify | files=31, pairs=33, non-token **NONE**, CHECK OK | `bump-verify.txt` |
| F8 `--check` | `582 == REGISTRY`, карта полна, R17-чисто, EXIT 0 | `gen-param-check.txt` |
| Factory fingerprint | `2.58.117 0163a686c401 0163a686c401` | `frozen-fingerprint.txt` |
| F8-пины | 29 passed | `focused-core.txt` |
| Frozen-пины канонов | 43 + 24 + 7 + 12 + 4 passed | `focused-core.txt` |
| pins24 (24 файла) | **868 passed / 0 failed** (66.49s) | `pins24-full.txt` |
| help-sync | 21 + 24 passed | `focused-core.txt` |
| JS-unit (`node --test tests/js/*.js`) | 90 pass / 0 fail | `js-pins-node.txt` |
| node-пины + mini-lens | 5/5 rc=0 | `js-pins-node.txt` |
| JS-syntax sweep | 90 файлов / 0 bad | `js-pins-node.txt` |
| py_compile изменённых py | 27 файлов / 0 bad | `py-compile.txt` |
| Frozen UI-ассеты | 0 изменённых (`web/index.html`, `app.js`, `static/`) | `frozen-assets.txt` |
| `test_soul1_composer_parity_off.py` | **13 passed** | `focused-core.txt` |
| `test_speech_inspector_exact.py` | **17 passed** (r3-проба: 4 HTTP-попытки → 4 error-записи) | `focused-core.txt` |
| `test_llm_client.py` | **115 passed** | `focused-core.txt` |
| UI e2e Inspector | **checks=142 failures=0** | `e2e-inspector.txt` |
| W4 UI e2e | **failures=0**, POST=8, notes=163 | `e2e-w4.txt` |
| ΔDDL | 0 hits | `ddl-check.txt` |

## Откат

- Прод-откат: `e9f7595b` (2.58.114) — код без коммитов поездов 115/116/117.
- Локально: `git revert 724b77ac` (bump) и/или возврат ветки на `be3e83d1`.

## Изоляция / примечания

- Основной чекаут (`C:\Code\Python\adminbot`) не изменялся.
- E2E-скрипты пишут PNG в `plans/features/asap-speech-arch/evidence/inspector/`;
  эти untracked-артефакты в коммит не входят.
- Полный repository-wide pytest в лейне не запускался (запрещено брифом).
- Деплой/SSH не выполнялись: лейн заканчивается FF-пушем `HEAD:master`.
