# Release 2.58.130 — cover-400 learned safe ceiling

**Ветка:** `release/2.58.130` (lane `RELEASE-258130-COVER-CEILING`).
**База:** `origin/release/2.58.129` tip `1b4e70a3` (код 2.58.129 — `79ec3726`, APP 2.58.129).
**Кандидат:** `origin/task/cover-400-headroom` = `95f33503` (Reviewer Approved).
**Merge:** `4136794e` (`--no-ff`, без конфликтов). **Bump:** 2.58.129 → 2.58.130.

## Что изменилось относительно 2.58.129

Ровно 3 файла (`1b4e70a3..4136794e`, +200 строк, 0 удалений):

- `services/image_capabilities.py` — изученный безопасный потолок (`_LEARNED_CEILINGS`) больше не истекает вместе с TTL кэша возможностей: выученное значение переживает инвалидацию;
- `services/cover_style_jobs.py` — потребитель потолка читает изученное значение;
- `tests/test_cover400_learned_ceiling.py` (новый) — контракт: обученный потолок переживает TTL.

**2.58.129 не потерян:** `provider_meta` (фикс cover-style JSON) на месте — `services/cover_style_jobs.py:3017-3024`.
Speech / PEMsoc / `handlers/*` / `style_policy` в diff отсутствуют.

## Тесты (post-merge, до bump)

| Набор | Результат |
|---|---|
| `pytest test_cover400_learned_ceiling.py test_cover_style_edit_extract.py test_asap44_cover_final_closure.py -q` | **34 passed** (7.8 s) |
| `pytest tests -k "cover_style or cover_prompt or extra_cover or asap4" -q` | **1154 passed**, 14515 deselected (159.7 s) — 1150 базовых + 4 новых |
| `pytest tests -k "speech or expression or prompt or checkup or factcheck or unified_core or cfg07" -q` | **1668 passed**, 14001 deselected (73.1 s) — паритет с базой |
| `pytest test_pemsoc_one_reaction.py test_common.py -q` | **181 passed** (3.7 s) |
| `py_compile` `services/image_capabilities.py`, `services/cover_style_jobs.py`, `tests/test_cover400_learned_ceiling.py` | OK |
| `pytest test_round1025_f8_registry.py test_webapp_round1026_polygon.py test_summary_deploy_round1026.py -q` (после bump) | **78 passed** (8.9 s) |

Уточнение по PEMsoc: фильтр `-k "pemsoc or common"` даёт 197 на базе `1b4e70a3` **и** на кандидате — это не регрессия; заявленные 181 — ровно пара файлов `test_pemsoc_one_reaction.py` + `test_common.py`.

## Guard-проверки

| Проверка | Значение |
|---|---|
| `factory_set_fingerprint()` | **f12130fbccb1** (как в 2.58.129) |
| ΔDDL | **0** — нет изменений `*.sql`/schema/migration |
| Bump-набор | **31 файл / 32 пина**: README, `config/settings.py`, F8-мета + 27 тест-`.py` + 4 `tests/js/*.js` (escaped `2\.58\.129`) |
| F8-мета HEAD | `4136794e` (pre-bump HEAD) |
| Stale-пины `2.58.129` вне evidence прошлого релиза | 0 |

## Откат

- Тёплый/холодный: `git checkout 79ec3726` (APP 2.58.129) + `systemctl restart admin_bot`.
- Ветка отката: `release/fix-2.58.129` → `79ec3726`.
- Мягкий откат поведения cover-400: значения выученного потолка — память процесса, TTL-инвалидация их не сохраняет между рестартами; продуктовая функция без нового флага (как в 2.58.129), откат только кодом.

## Deploy (факт)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot`, `venv/bin/python`.
Окно: `2026-10-24T21:02:59Z` → `21:04:20Z`. SSH: **2 коннекта** (deploy 21:02:59Z + read-only Core-подтверждение с паузой 65 с), один логин, без ретраев.

| Проверка | Результат |
|---|---|
| Pre-deploy HEAD / версия | `79ec3726` / 2.58.129, `DIRTY=0`, unit active, NRestarts 0 |
| `git fetch origin release/2.58.130` | rc 0, ветка создана, `534ac7dd` присутствует |
| Deployed commit (server `git rev-parse HEAD`) | **`534ac7dd`** = release SHA (побайтово равен кандидату) |
| `APP_VERSION` на диске | `2.58.130` |
| unit | `active/running`, MainPID **1182846**, **NRestarts = 0** |
| `/healthz` loopback | HTTP **200**, `{"status":"ok","version":"2.58.130"}` (6-я попытка, ~18 с старта) |
| `/healthz` публично (443) | **200** |
| Журнал нового PID (170 строк) | **0** CRITICAL / **0** ERROR / **0** Traceback |
| cover-строки в журнале | 4 INFO (`[cover_styles] seed ensure | profile=medved_press`, media recovery, shutdown recovery, scheduler), **0** исключений |
| `_LEARNED_CEILINGS` | атрибут есть, тип `dict` (import на проде) |
| `compile_style_prompt` | callable (import на проде) |
| `factory_set_fingerprint()` на проде | **f12130fbccb1** |
| ΔDDL | **0**: `PRAGMA user_version` = **37** до и после |
| Core | `character.core` = JSON `origin=owner_edit`, **revision 8**, `full_text` содержит F1-маркер и «Свобода речи»; `character.prompt_history` — 1 запись. Промпт-путь в diff отсутствует, миграций канона в журнале нет |
| Откат подтверждён на сервере | `79ec3726` присутствует, `release/fix-2.58.129` запушен |

Замечание по Core: `sha12(a37678237533)` ≠ `ead77b2ab509` из evidence 2.58.129. Причина — в прошлом evidence записан sha **канона** (rev 8), а живое значение — owner-custom вариант (`origin=owner_edit`) с тем же revision 8; наш diff не содержит промптов/personality. Это уточнение метки прошлого релиза, не регрессия 2.58.130.

Ограничение (как в 2.58.129): `requirements_gate.py --stage release` по карте `plans/features/cfg/requirements-map.json` не переиздавался под patch-релиз — карта привязана к `79ec3726`; фиктивная привязка не создавалась. Требования к карте — PM/Reviewer.

Платные cover-пробы и тестовые сообщения в чаты **не отправлялись**.

