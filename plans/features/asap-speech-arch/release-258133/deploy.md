# Deploy 2.58.133 — release/p0-2026-10-26 (DEPLOY-258133)

**Дата:** 27.10.2026 (server UTC 26.10 13:49–14:05). **Ветка:** `release/p0-2026-10-26`.
**Одобренный код-коммит (candidate):** `2d4eaad6` (merge p0-delta micro-fix `eaabb66f` «LORE-VERBATIM-GATE — verbatim-return instruction only when lore story delivery allowed»; Reviewer Approved).
**Bump-коммит = deployed SHA:** `b571602226c5e5a5845850597f6100e3a6e0d12a` (`chore(release-258133): bump 2.58.132 -> 2.58.133 (31-file/33-pin proc set, F8-meta HEAD=2d4eaad6, deltaDDL=0)`; 31 файл / 33 пина: README `v2.58.133`, APP_VERSION, F8-meta (APP_VERSION 2.58.133 + HEAD `2d4eaad6`), 24 py-теста (polygon — 2 пина), 4 JS escaped-regex; файл-сет побайтно совпадает с эталоном `d3a9a2cc`).
**Предыдущий прод:** `d3a9a2cc` (2.58.132, healthz 200, active, NRestarts 0, dirty 13 untracked).
**DeltaDDL:** **0** — bump-дифф содержит только версии-пины (0 файлов миграций/SQL/schema/requirements); живой журнал нового процесса подтверждает `[database] migrations: start | current user_version=37 | pending=[]` → `complete | user_version=37 | total 0.0s`.

## Guard'ы (post-bump, worktree `adminbot-wt-rel-p0`)

| Guard | Результат |
|---|---|
| `py -3 tools/gen_param_registry_round1025.py --check` | **OK**: реестр 582 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны |
| `py -3 -m compileall services` | **OK** (rc=0) |
| Push | `fee098ac..b5716022 release/p0-2026-10-26 -> origin` |

## Деплой (SSH, 2 сеанса: recon + main, fail2ban-safe)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot`. Одиночные логины, интервал > 1 мин, без ретраев.

| Шаг | Результат |
|---|---|
| Recon (13:49:41Z) | HEAD `d3a9a2cc`, dirty 13, unit active/running, **NRestarts 0**, healthz `{"status":"ok","version":"2.58.132"}`; драйвер r1 на сервере (sha256 `ca500edb…` подтверждён) |
| Pre-state (13:50:26Z) | HEAD `d3a9a2cc`, dirty 13, MainPID 260518, healthz 2.58.132 |
| `git fetch origin release/p0-2026-10-26` | rc 0, `d3a9a2cc..b5716022` (fetch attempt 1 — хватило, askpass не понадобился) |
| `git checkout --detach b5716022` | rc 0, HEAD = `b571602226c5e5a5845850597f6100e3a6e0d12a`, dirty 13 сохранены |
| Артефакт-пины (sha256_12, deployed) | `settings.py ec489d05564e`, `README.md 0d7a28731fb7`, `param-registry…meta.md b85ef567f6c4`, `direct_chat_service.py a3dc914c6cd3`, `tool_router.py fe25ca5898dd`, `direct_l1.py ff7e9c9713e8` — **все совпадают с локальным `b5716022`** (candidate-биндинг) |
| `sudo -S systemctl restart admin_bot` | RESTART_RC=0, новый MainPID **288472** |
| Post (settle ~25 c) | healthz loopback **200** `{"status":"ok","version":"2.58.133"}`; unit `active/running`, **NRestarts = 0** |
| Журнал (окно рестарта, epoch-якорь) | **0 ERROR / CRITICAL, 0 Traceback**; migrations `user_version=37, pending=[], 0.0s` |
| Внешний healthz | `https://admin-bot.duckdns.org/healthz` → **200** `2.58.133` (сразу после деплоя; повторно после re-probe) |
| LLM/Telegram | re-probe шёл параллельно живому боту без замечаний (см. `live-scenarios-r2.md`) |

## RE-PROBE §12-r2 (read-only, реальный LLM, без Telegram)

Отдельный контур: стейджинг `/tmp/p0d` из deployed SHA (`git archive b5716022`, sha-пины совпали), SQLite — свежий снапшот-копия (`sqlite3 backup`, 1562 MB, прод не тронут), PostgreSQL — `default_transaction_read_only=on` (probe `ro_ok:ReadOnlySQLTransactionError`), FakeBot (ноль Telegram). Драйвер r1 **байт-в-байт тот же** (sha256 `ca500edb…`), обёртка `rerun_r2.py` (sha256 `73256c69…`) — только выборка сценариев + дозапись ctx-флагов, файл драйвера не изменялся. Реальный `_handle_turn`, hot-конфиг из PG (`wide_context_hot=true`, модель `deepseek/deepseek-v4.1-flash`). Прогон 26.10 13:53–14:02 UTC, 6 сценариев S02/S03/S04/S05/S07/S10. Результаты — `plans/features/p0-delta-analysis/evidence/live-scenarios-r2.md`; raws — scratch `deploy-258133/r2-results/` (sha256-список внутри).

**Итог §12-r2:** FAIL-критерий r1 «lore story подменяет analysis-ответ» — **ЗАКРЫТ**: на S03/S05/S07/S10 верbatim-инструкция в payload отсутствует, story не доставлен (`story_delivered_as_reply=false`), ответы Writer-композиция (similarity к story 0.008–0.072). S02 честный отказ сохранён. S04 — примечание по классификации L1 (см. r2-документ).

## Откат (задокументирован, не выполнялся)

```
cd /var/www/admin_bot && git checkout d3a9a2cc8ff22779c121e7c97a1432d42f13e6e4 && sudo systemctl restart admin_bot
```
Ожидаемое после отката: 2.58.132, healthz 200. Примечания: (1) untracked 13 файлов пережили checkout — не мешают; (2) re-probe писал только в снапшот-копию БД и read-only PG — прод-данные не изменялись; (3) staging-остатки `/tmp/p0d` — scratch, прод не влияет; зависший shutdown-процесс прогона убран, `/tmp/p0d` оставлен для инспекции Reviewer.

## Итог

- **Deployed:** `b5716022` (= candidate `2d4eaad6` + release-bump), healthz **2.58.133/200** (loopback + внешний), unit active, **NRestarts 0**, журнал чист, DDL=0 подтверждён живым процессом.
- Технические деплой-проверки — **VERIFIED** (версия/healthz/unit/journal/DDL=0/артефакт-пины/rollback-readiness).
- Обязательная live-приёмка §12 (re-probe) — **PASS** по всем критериям лейна (детали и примечание S04 — `live-scenarios-r2.md`).
