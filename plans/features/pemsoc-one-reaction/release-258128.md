# Release 2.58.128 — PEMsoc fallback/common claim

**Ветка:** `release/2.58.128` (lane `RELEASE-258128-PEMSOC-DEFAULT`).
**База:** `origin/release/2.58.127` tip `186d7a40` (код `b2ac3fa5`, APP 2.58.127, speech-simplify уже на проде).
**Фича:** `origin/task/pemsoc-one-reaction` = `006bb394` (Reviewer Approved).
**Merge:** `87a7a4f3` (`--no-ff`, без конфликтов — `plans/progress_scope.json` уже содержал обе задачи).
**Bump:** 2.58.127 → 2.58.128.

## Что меняется относительно прода

Ровно 9 файлов (`git diff --stat 186d7a40` → merge):

- `handlers/common.py` — общая реакция тоже заявляет claim (одна реакция между common/war/slavik);
- `handlers/war_alert.py`, `handlers/slavik.py` — claim-участие в «одной реакции»;
- `services/common_relay.py` — `CommonRelay.send_common` возвращает `bool`; тихий пропуск освобождает claim, чтобы дефолт сработал;
- `services/pemsoc_reactions.py` — release claim при неуспешной отправке (дефолт «пошёл нахуй» гарантирован);
- `services/message_counter.py` — учёт;
- `tests/test_common.py`, `tests/test_pemsoc_one_reaction.py` — RED→GREEN покрытие;
- `plans/features/pemsoc-one-reaction/impl.md` — описание.

**Речь не тронута:** в diff базы нет ни одного файла `speech_*`/`expression`/`prompt_*`/`style_policy`; speech-simplify `e44a30b4` остаётся как в 2.58.127.

## Тесты (post-merge, до bump)

| Набор | Результат |
|---|---|
| `pytest test_pemsoc_one_reaction test_common test_war_alert test_slavik_handlers test_slavik_priority test_message_counter -q` | **277 passed** (4.77 s) |
| `pytest tests -k "speech or expression or prompt or checkup or factcheck or unified_core or cfg07" -q -s` | **1668 passed**, 13988 deselected (64.2 s) |
| `py_compile` изменённых модулей (`handlers/common.py`, `handlers/war_alert.py`, `handlers/slavik.py`, `services/common_relay.py`, `services/message_counter.py`, `services/pemsoc_reactions.py`, `config/settings.py`) | OK (exit 0) |

**Расхождение с заданием по числу PEMsoc-тестов:** в задании ожидалось 289, фактически **277** — и в `adminbot-wt-pemsoc` (`origin/task/pemsoc-one-reaction`), и в релизной ветке. То есть merge поведение не меняет, число 289 в задании завышено; приёмка по факту 277 на обеих сторонах.

## Guard-проверки

| Проверка | Значение |
|---|---|
| `factory_set_fingerprint()` | **f12130fbccb1** (совпадает с 2.58.127) |
| ΔDDL | **0** — в diff нет `*.sql`/schema/migration файлов, `user_version` не меняется |
| Каталог параметров | Δ не ожидается (bump non-token NONE); F8-мета: APP 2.58.128, HEAD `87a7a4f3` |
| Bump-набор | **31 файл / 32 пина** (27 `.py/.md` + 4 `tests/js/round1025_hotfix{7,8,9,10}_*.js` escaped-пины `2\.58\.127`); stale-пинов `2.58.127` вне `plans/features` — 0 |

## Откат

- Холодный: `git checkout b2ac3fa5` (APP 2.58.127, PEMsoc + speech как на проде до релиза) + `systemctl restart admin_bot`.
- Ветка отката: `release/fix-2.58.127` → `b2ac3fa5` (запушена).
- Тёплого флага нет: изменение — поведение claim-логики, не переключаемая фича.

## Deploy (факт)

Сервер: `nik@198.46.175.136`, прод `/var/www/admin_bot`, unit `admin_bot`.
Серверное время: `2026-10-24T18:07:47Z` → `18:08:50Z`.

| Проверка | Факт |
|---|---|
| Pre-deploy HEAD | `b2ac3fa5` (2.58.127) |
| Deployed commit (server `git rev-parse HEAD`) | **`dcaca75b`** = release SHA (совпадает с кандидатом) |
| APP_VERSION на сервере | `2.58.128` |
| Состояние unit | `active/running`, MainPID **1147862**, **NRestarts = 0** |
| `/healthz` loopback `127.0.0.1:8000` | HTTP **200**, `{"status":"ok","version":"2.58.128"}` |
| Журнал нового PID (184 строки) | **0** CRITICAL / **0** ERROR / **0** Traceback / `GIF send failed` **0** |
| `War Alert` / `Slavic` | 2 / 0 строк — без исключений (WAR=2 — штатная процедура) |
| Импорты на проде | `CommonRelay.send_common` — coroutine **True**; `services.pemsoc_reactions` — **OK** |
| `factory_set_fingerprint()` | **f12130fbccb1** (как на 2.58.127) |
| Core | `character.core` patch: «абзацы уже есть, авторские байты целы», `sha=ead77b2ab509` = **rev 8**; adopt-событий **0** |
| ΔDDL | **0**: `PRAGMA user_version` = **37** (как до релиза), 18 строк `[prompt_migration]` — штатные решения «уже новый канон / кастом не трогаем» |

`https://127.0.0.1/healthz` и `:8080` дают 000 — приложение слушает только loopback `:8000` за Caddy (публичный вход — `:443`, вне loopback-проверки). Тестовых сообщений в рабочие чаты не отправлялось, поэтому `common_relay`/`pemsoc` в журнале 0 строк: фича срабатывает только на реальной реакции.

## Итог

2.58.128 на проде: PEMsoc fallback/common claim (`006bb394`) доставлен, speech-simplify не менялся, healthz 200/2.58.128, NRestarts 0, 0 ERROR/Traceback, FACTORY_SET `f12130fbccb1`, ΔDDL=0, Core rev 8 без повторного adopt.
Откат готов: `b2ac3fa5` / ветка `release/fix-2.58.127`.
