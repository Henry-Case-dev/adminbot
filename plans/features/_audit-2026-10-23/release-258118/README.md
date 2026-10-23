# REL-258118 — релизный поезд 2.58.117 → 2.58.118 (24.10.2026)

Полоса `RELEASE-258118`. Цель — финальный выпуск: донести в поезд фикс лимитов
`849eeed9` (review r2) и поднять версию. Worktree `C:\Code\Python\adminbot-wt258115`,
ветка `release/2.58.115`.

Прод/SSH в полосе **не трогались**. Push FF-обновлением `HEAD:master`.

## Состав поезда

| Этап | SHA | Комментарий |
|---|---|---|
| База (`release/2.58.115` = 2.58.117) | `9dfd6db6` | tip прошлого поезда, версия 2.58.117 |
| Cherry-pick limits review r2 (`master 849eeed9`) | `47ed033e` | `git cherry-pick -x` |
| Pre-bump HEAD (F8-meta HEAD-токен) | `47ed033e` | — |
| Bump-коммит 2.58.118 | `9ed68ee8` | 31 файл / 33 пары |
| Точка отката | `e9f7595b` | 2.58.114, общая для 115/116/117/118 |

Версия: **2.58.118**. Bump-набор: **31 файл / 33 пары**
(README + settings + F8-meta + 20 py-пинов + polygon×2 + 4 JS-пина), `SET EQUAL`
с proc-114…117, `non-token deltas NONE`.

## Cherry-pick 849eeed9

Содержание: закрытие ревью r2 по лимитам (`services/direct_chat_service.py` — flat links WARN,
честный cap мемов, арифметика инвентаря; `tests/test_asap3_hidden_limits.py` — расширение
набора; evidence `limits-inventory.md`).

Единственный конфликт — `plans/features/asap3-corrective/evidence/limits-inventory.md`:
путь отсутствует на ветке (`modify/delete`), в исходном коммите файл изменён. Разрешён
версией коммита (файл создан целиком, `create mode`), это evidence-документ полосы.

Проверка эквивалентности: `git show --format= 849eeed9 -- <2 файла>` и
`git show --format= 47ed033e -- <2 файла>` дают **идентичное тело патча** 144 ±строк
(различия только в hunk-заголовках и index-блобах). Т.е. код и тесты перенесены
без искажений; в коммит попало 399 вставки / 20 удалений (вместо 195/42) из-за
создания evidence-файла целиком.

## Fingerprint

`services/prompt_registry.py` не менялся в поезде:
`factory_set_fingerprint() == FACTORY_SET_SHA256_12 == 0163a686c401` на 2.58.118
(`frozen-fingerprint.txt`). Как и требовалось — fingerprint **не меняется**.

## ΔDDL

**0** в прод-периметре (`services/`, `web/`, `config/`, `scripts/`, `tools/`):
28 добавленных строк (cherry-pick), 0 DDL-токенов в диапазоне `9dfd6db6..9ed68ee8`
(`ddl-check.txt`). Schema/migration-дельта отсутствует.

## Guards

Интерпретатор всех pytest/py_compile прогонов: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`
(Python 3.12.0, aiogram 3.31.0 — по `requirements.txt`). Node: v24.16.0.

| Проверка | Наблюдение | Артефакт |
|---|---|---|
| Bump-verify | files=31, pairs=33, non-token **NONE**, CHECK OK | `bump-verify.txt` |
| F8 `--check` | `582 == REGISTRY`, карта полна, R17-чисто, EXIT 0 | `gen-param-check.txt` |
| Factory fingerprint | `2.58.118 0163a686c401 0163a686c401` | `frozen-fingerprint.txt` |
| F8-пины | 29 passed | `focused-core.txt` |
| Frozen-пины канонов | prompt_migrations 43 + clar_contract 24 + r3b 7 + corrective 12 + expression 4 | `focused-core.txt` |
| pins24 (24 py-пина) | **868 passed / 0 failed**, 68.40s | `pins24-full.txt` |
| help-sync | 21 + 24 passed | `focused-core.txt` |
| JS-unit (`node --test tests/js/*.js`) | 90 pass / 0 fail | `js-pins-node.txt` |
| node-пины + mini-lens | 5/5 rc=0 | `js-pins-node.txt` |
| JS-syntax sweep | 90 файлов / 0 bad | `js-pins-node.txt` |
| py_compile изменённых py | 27 файлов / 0 bad | `py-compile.txt` |
| Frozen UI-ассеты | 0 изменений (`web/index.html`, `app.js`, `static/`) | `frozen-assets.txt` |
| `test_soul1_composer_parity_off.py` | **13 passed** | `focused-core.txt` |
| `test_speech_inspector_exact.py` | **17 passed** | `focused-core.txt` |
| `test_llm_client.py` | **115 passed** | `focused-core.txt` |
| `test_asap3_hidden_limits.py` (содержание cherry-pick) | **16 passed** | `focused-core.txt` |
| `test_asap3_style_hint_limits.py` | 16 passed | `focused-core.txt` |
| UI e2e Inspector | **checks=142 failures=0** | `e2e-inspector.txt` |
| W4 UI e2e | **failures=0**, POST=8, notes=163 | `e2e-w4.txt` |
| ASAP3 hint UI e2e | **PASS: 10 проверок**, failures=0 | `hint-e2e.txt` |
| ΔDDL | 0 hits | `ddl-check.txt` |

## Откат

- Общая точка: `e9f7595b` (2.58.114) — как у поездов 115/116/117.
- Точечно: `git revert 9ed68ee8` (bump) и/или `git revert 47ed033e` (limits fix);
  возврат ветки на `9dfd6db6` эквивалентен 2.58.117.
- Bump безопасен при откате в любую сторону: меняет только токены версии и F8-метапин.

## Ограничения / замечания

- Основной worktree (`C:\Code\Python\adminbot`) не трогался.
- Untracked `plans/features/asap-speech-arch/evidence/inspector/` (PNG от прошлого поезда)
  остаётся вне коммита.
- Repository-wide pytest и deploy/restart/live-Telegram в полосе не выполнялись.
- Деплой в этой полосе не производится: только push FF `HEAD:master`.
