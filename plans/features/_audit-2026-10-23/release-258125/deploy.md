# REL-258125 — деплой 2.58.125 и пост-проверки

Дата: 24.10.2026, 08:39–08:42 UTC. Лейн: DEPLOY-258125. Сервер: `198.46.175.136`, сервис `admin_bot`.

## DEPLOY_SOURCE

- **Кандидат:** `f0e6a0cd68b8a1f93fc8ad242834d44a383b7f9b` = 2.58.125 (docs-tip `331fe27e` не деплоился).
- База: `39a06b88` (2.58.124, был live) → `76004f34` (docs) → `6e9f10a2` (URL quotes fix, code) → `f0e6a0cd` (bump).
- Состав кода против 2.58.124: `services/style_policy.py` (`_URL_RE` + `_url_span_end`), `config/settings.py` (версия), `tests/test_quotes_modes.py`; остальное — docs/карты.
- **MUTABLE_WORKTREE_REQUIRED: no** — на сервере `git fetch origin master` + `git checkout -fq f0e6a0cd`; рабочее дерево разработки не участвовало.
- Write scope: `release/fix-2.58.124` в origin (ветка отката); на сервере — checkout + рестарт + `~/deploy-258125/bot_settings_pre.json`. Код приложения не правился.

## Результат

- `git rev-parse HEAD` до: `39a06b88…` → после: `f0e6a0cd68b8…`; `APP_VERSION "2.58.125"`; tracked dirty `0` до и после, untracked `13` (без изменений).
- `systemctl restart admin_bot` → OK; `active`; **MainPID 1030683 → 1035251**; **NRestarts 0**.
- `http://127.0.0.1:8000/healthz` → **HTTP 200** `{"status":"ok","version":"2.58.125"}`; процесс слушает `127.0.0.1:8000`.
- Публичный `https://198.46.175.136/healthz` → `000` и с рабочей машины (TLS alert), и с самого сервера — та же известная сетевая/TLS проблема, что и в 2.58.124; каналом доказательства служит loopback-ответ процесса.
- Журнал (окно 587 строк, включает остановку старого процесса): CRITICAL `0`, `database is locked` `0`, `prompt_rollback` `0`. ` ERROR ` `1` и `Traceback` `3` — все от **старого PID 1030683 в 08:40:40** при остановке 2.58.124 (`database: rollback failed — connection marked unrecoverable`), до старта нового процесса в 08:40:51. У нового PID 1035251 после старта: **0 CRITICAL / 0 ERROR / 0 Traceback**.

## Каноны / Core / adopt

- `FACTORY_SET 47f0d1eb8de4` — **без изменений**.
- `bot_settings`: 537 ключей до и после, добавленных/удалённых нет. Ключи `prompts.*` (checkup, direct_l1_planner, direct_chat_verbalizer, direct_chat, summary, factcheck): `unchanged_vs_pre=True` для всех; кастомы владельца не тронуты (`кастом юзера — НЕ трогаем`).
- `withheld_values(pg_get=…)` → **11 строк** — каноны не потеряны, набор блоков прежний.
- Core patch идемпотентен: `CORE_POST_LEN 3294`, `SHA12 ead77b2ab509`, `CORE_UNCHANGED_AFTER_RESTART True`, `PATCH_CHANGES_ON_PRE []`, `PATCH_IDEMPOTENT True`, `detail_level=full`, `revision 8`, оба авторских абзаца на месте.
- adopt не повторён: `ADOPTED 0`, `BUILD_START 0`; миграции промптов — штатные `уже новый канон` / `core patch: абзацы уже есть`.

## URL-кавычки (read-only `apply_style_policy`, `record=False`)

| Вход | A — normalize | B — strip («Без кавычек») | Итог |
|---|---|---|---|
| `https://x/?q=«y»` | тот же текст, sha `c02e4de086ef` | тот же текст, sha `c02e4de086ef` | **OK**, байт-в-байт |
| `Он сказал «текст» …` | `"текст"`, `"ещё"`, `-` | `текст`, `ещё`, `-` | **OK**, обычные кавычки обрабатываются |
| `«https://x/a»` | `"https://x/a"` | `https://x/a` | **OK**, ёлочки-обёртка правятся |
| код/JSON в backticks и ```…``` | без изменений | без изменений | **OK** |

Во всех прогонах одно активное правило `quotation_marks` (`QRULES n=1`, mode normalize/strip). Защищённые регионы не задеты.

## Откат

- Ветка `release/fix-2.58.124` создана и запушена: `76004f3470cfe44f41a1dbbefd3f583db9b8614e` (2.58.124 + docs; против `39a06b88` отличаются только `plans/`, код идентичен — проверено `git diff --stat`).
- Процедура: `cd /var/www/admin_bot && git checkout -fq 76004f34 && sudo systemctl restart admin_bot` (+ healthz 2.58.124). `ΔDDL=0`, миграций нет, FACTORY_SET тот же.
- Бэкап `bot_settings`: `/home/nik/deploy-258125/bot_settings_pre.json` (537 строк).
- Второй уровень: `39a06b88` / `58b1bcca`.

## Вердикт

**Деплой: VERIFIED** — точный кандидат `f0e6a0cd` работает как 2.58.125, сервис active, NRestarts 0, healthz 200/2.58.125, каноны/FACTORY_SET/Core/withheld не изменились, adopt не повторён, URL-кавычки защищены байт-в-байт в A и B, обёртка `«URL»` по-прежнему правится.

**Релиз в целом не закрыт (зона PM/Reviewer):** `requirements_gate.py check --stage release --candidate f0e6a0cd… --deployed-commit f0e6a0cd… --map plans/features/p0-corrective-factcheck-speech/requirements-map.json` → **EXIT 1**, `errors=1123` — карта всё ещё привязана к `39a06b88`, candidate-bound evidence по `f0e6a0cd` нет. Это привязка карты, не дефект деплоя; откат остаётся готовым.
