# Release 2.58.127 — speech-simplify поверх PEMsoc (RELEASE-258127-SPEECH)

**Ветка:** `release/2.58.127`.
**База:** `origin/release/2.58.126` tip `d7061ad1`, код `c635bfe9` (APP_VERSION 2.58.126, PEMsoc one-reaction уже на проде).
**Слитая фича:** `origin/task/speech-simplify-final` = `e44a30b4` (Reviewer Approved).
**Merge-коммит:** `be0cc712` (`--no-ff`, без конфликтов).
**Bump:** 2.58.126 → 2.58.127.

## Состав релиза

Один релиз из двух проверенных кусков:

| Источник | Что даёт | Статус до релиза |
|---|---|---|
| `c635bfe9` (2.58.126) | PEMsoc: одна реакция на сообщение (claim across war/slavik/kucha/gif) | на проде, живая |
| `e44a30b4` (speech-simplify) | упрощение речи: базовый регистр, юмор без объяснений, длина ответа, профили мата (off/occasional/frequent), стиль ДВАЧ, фактическая речь; нормализация suppress-pins, freeze PREV/ROLLBACK канонов | Reviewer Approved |

Merge прошёл **без конфликтов** (`plans/progress_scope.json` слился автоматически, обе задачи сохранены: `asap-speech-arch` + `p0-factcheck-speech`/PEMsoc-скоуп).

## Целостность PEMsoc после merge

`git diff --stat origin/release/2.58.126 HEAD` по PEMsoc-файлам — **пусто** (0 изменений):

- `services/pemsoc_reactions.py`
- `handlers/war_alert.py`
- `handlers/slavik.py`
- `services/message_counter.py`

PEMsoc-фикс не затронут merge'ом.

## Тесты (post-merge, до bump)

| Прогон | Результат |
|---|---|
| `pytest test_pemsoc_one_reaction + test_war_alert + test_slavik_handlers + test_slavik_priority -q` | **86 passed** (4.56 s) |
| `pytest tests -k "speech or expression or prompt or checkup or factcheck or unified_core or cfg07" -q` | **1668 passed**, 13980 deselected (67.9 s) |
| `pytest test_cfg07a_f1_custom_suppress + test_speech_simplify_2026_10_25 -q` | 67 passed |

Windows-capture JS-падения не воспроизвелись в этом прогоне: 1668 passed без failures.

## Bump

| Параметр | Значение |
|---|---|
| Файлов | **31** (proc set: 27 `.py/.md` + 4 `tests/js/round1025_hotfix{7,8,9,10}_*.js` через escaped-форму `2\.58\.126`) |
| Пар | **33** (31 файл + meta HEAD + двойное вхождение в `test_webapp_round1026_polygon.py`) |
| Non-token deltas | **NONE** — только `2.58.126 → 2.58.127` + meta HEAD `d3cceb0c → be0cc712` |
| APP_VERSION | `2.58.127` (`config/settings.py:3367`) |
| F8-meta HEAD | `be0cc712` = pre-bump HEAD (честный) |
| ΔDDL | **0** — ни schema/migration/`.sql` в диффе, `user_version` не меняется |

Исключён из bump: `plans/features/pemsoc-one-reaction/release-258126.md` (исторический документ релиза 2.58.126).

## Guards

| Проверка | Результат |
|---|---|
| bump-verify | files=31, pairs=33, non-token deltas NONE, meta HEAD = pre-bump HEAD, APP_VERSION 2.58.127 |
| F8 `--check` (`tools/gen_param_registry_round1025.py`) | **EXIT 0** — реестр 582 == REGISTRY, карта полна, R17-чисто |
| `py_compile` изменённых | rc=0, 25 `.py` |
| `factory_set_fingerprint()` | `f12130fbccb1` — новый speech-набор (до bump `47f0d1eb8de4` на 2.58.126) |
| Core rev | 8 |
| ΔDDL | 0 |

`factory_set_fingerprint()` = `f12130fbccb1` подтверждает, что speech-каноны (5 профилей + style DVACH + factual speech + suppress-нормализация) реально входят в factory-набор 2.58.127.

## Откат

- **Cold:** `c635bfe9` (2.58.126, стабильная, PEMsoc-only). Ветка `release/fix-2.58.126` = `c635bfe9`.
- **Проверка отката:** переключение на `c635bfe9` возвращает APP_VERSION 2.58.126 и factory set `47f0d1eb8de4`; ΔDDL=0 в обе стороны — схема БД не меняется ни вперёд, ни назад.
- Промпты: каноны speech-simplify применяются через `prompt_migrations`; на откате активны PREV/ROLLBACK-версии (`91935804` заморозил PREV-байты), кастомные значения владельца не перезаписываются.

## Deploy

См. раздел «Deploy» ниже — заполняется по факту (deployed commit, healthz, NRestarts, журнал, FACTORY_SET, миграции).
