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

## Deploy (факт)

Сервер: `nik@198.46.175.136`, прод `/var/www/admin_bot`, unit `admin_bot`.
Серверное время: `2026-10-24T17:41–17:48Z`.

| Проверка | Факт |
|---|---|
| Pre-deploy HEAD | `c635bfe9` (2.58.126) |
| Deployed commit (server-reported `git rev-parse HEAD`) | **`b2ac3fa5`** = release SHA (совпадает с одобренным кандидатом) |
| APP_VERSION на сервере | `2.58.127` |
| `systemctl restart admin_bot` | OK (`sudo -n`, NOPASSWD-правило для systemctl) |
| Состояние unit | `active/running`, MainPID **1141997**, **NRestarts = 0** |
| `/healthz` loopback `127.0.0.1:8000` | HTTP **200**, `{"status":"ok","version":"2.58.127"}` (два замера: 17:43:48Z, 17:45:23Z) |
| Журнал нового процесса (609 строк, 17:41:45Z→) | **0** CRITICAL / **0** ERROR / **0** Traceback / `GIF send failed` **0** |
| `War Alert` / `Slavic` / `GIF` | 2 / 0 / 0 строк в окне — без исключений (WAR=2 — штатные записи процедуры) |
| Импорты | `services.pemsoc_reactions`, `services.mca_expression` — `IMPORTS_OK` |
| `factory_set_fingerprint()` на проде | `f12130fbccb1` — **новый speech-набор** (было `47f0d1eb8de4` на 2.58.126), т.е. speech-каноны реально активны |
| Core | `character.core` патч: «абзацы уже есть, авторские байты целы», `sha=ead77b2ab50` = **rev 8**; adopt не повторялся |
| ΔDDL | **0**: `PRAGMA user_version` = **37** (как до релиза), DDL-операций в логе старта нет |

### `prompt_migrations` при старте (17:42:03Z, 18 строк `[prompt_migration]`)

Миграция выполнилась поштатно, кастомные значения владельца **не перезаписаны** (ровно требуемое поведение):

- `INFO — уже новый канон`: `prompts.factcheck_analyst_system_prompt`, `prompts.summary_l1_clusterizer_system_prompt` и др.
- `WARNING — кастом юзера, НЕ трогаем`: `prompts.summary_narrator_system_prompt` (1788 симв.), `prompts.summary_l2_writer_system_prompt` (8388), `prompts.factcheck_verbalizer_system_prompt` (1712) — зафиксировано, байты сохранены.
- `INFO — core patch: абзацы уже есть, авторские байты целы`.

Ограничение честно: прямые значения `prompts.*` из PostgreSQL не прочитаны (доступ к `/proc/<pid>/environ` и к `journalctl` требует пароля; NOPASSWD-правило есть только у `systemctl`). Поведение миграции подтверждено журналом по каждому ключу, включая решения «не трогать кастом».

## Итог

2.58.127 на проде: PEMsoc-фикс сохранён (86 passed, файлы без диффа), speech-simplify `e44a30b4` доставлен, healthz 200/2.58.127, NRestarts 0, 0 ERROR/Traceback, FACTORY_SET `f12130fbccb1`, ΔDDL=0. Откат готов: `c635bfe9` / ветка `release/fix-2.58.126`.
