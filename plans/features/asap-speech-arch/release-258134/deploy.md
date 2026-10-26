# Deploy 2.58.134 — release/p0-2026-10-26 (DEPLOY-258134)

**Дата:** 26.10.2026 (server UTC 15:24–15:31). **Ветка:** `release/p0-2026-10-26`.
**Одобренный код-коммит (candidate):** `d167d686` (merge p0-delta DELTA-DEPTH `8e8c8c27` «verbatim §11 owner instruction + writer substance requirement»; Reviewer Approved).
**Bump-коммит = deployed SHA:** `076f7391a01157bad106372d405d109085a78dbc` (`chore(release-258134): bump 2.58.133 -> 2.58.134 (31-file/33-pin proc set, F8-meta HEAD=d167d686, deltaDDL=0)`; 31 файл / 33 пина: README `v2.58.134`, APP_VERSION, F8-meta (APP_VERSION 2.58.134 + HEAD `d167d686`), 24 py-теста (polygon — 2 пина), 4 JS escaped-regex; файл-сет побайтно совпадает с эталоном `b5716022`).
**Предыдущий прод:** `b5716022` (2.58.133, healthz 200, active, NRestarts 0, dirty 13 untracked).
**DeltaDDL:** **0** — bump-дифф содержит только версии-пины (0 файлов миграций/SQL/schema/requirements); живой журнал нового процесса подтверждает `[database] migrations: start | current user_version=37 | pending=[]` → `complete | user_version=37 | total 0.0s`.

## Guard'ы (post-bump, worktree `adminbot-wt-rel-p0`)

| Guard | Результат |
|---|---|
| `py -3 tools/gen_param_registry_round1025.py --check` | **OK**: реестр 582 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны |
| `py -3 -m compileall services config` | **OK** (rc=0) |
| Push | `b5716022..076f7391 release/p0-2026-10-26 -> origin` |

## Деплой (SSH, 2 сеанса: recon + main, fail2ban-safe)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot`. Одиночные логины, интервал > 1 мин, без ретраев.

| Шаг | Результат |
|---|---|
| Recon (15:24:10Z) | HEAD `b5716022`, dirty 13, unit active/running, **NRestarts 0**, healthz `{"status":"ok","version":"2.58.133"}`; драйвер r1 на сервере (sha256 `ca500edb…` подтверждён), выкачан в scratch для r3-обёртки |
| Pre-state (15:27:07Z) | HEAD `b5716022`, dirty 13, MainPID 288472, healthz 2.58.133 |
| `git fetch origin release/p0-2026-10-26` | rc 0, `b5716022..076f7391` (fetch attempt 1 — хватило, askpass не понадобился) |
| `git checkout --detach 076f7391` | rc 0, HEAD = `076f7391a01157bad106372d405d109085a78dbc`, dirty 13 сохранены |
| Артефакт-пины (sha256_12, deployed) | `settings.py 10073eb7567e`, `README.md c92afdfcf659`, `param-registry…meta.md 310e45a26922`, `direct_chat_service.py 5add3022e464`, `direct_l1.py 4ce9c972d5b0`, `prompt_style_blocks.py 7e67090aa59a` — **все 6/6 совпадают с локальным `076f7391`** (candidate-биндинг) |
| `sudo -S systemctl restart admin_bot` | RESTART_RC=0, новый MainPID **308006** |
| Post (settle ~22 c) | healthz loopback **200** `{"status":"ok","version":"2.58.134"}` (READY_5); unit `active/running`, **NRestarts = 0** |
| Журнал (окно рестарта, epoch-якорь) | **0 ERROR / CRITICAL, 0 Traceback**; migrations `user_version=37, pending=[], 0.0s` |
| Внешний healthz | `https://admin-bot.duckdns.org/healthz` → **200** `2.58.134` (сразу после деплоя и повторно после re-probe) |

## RE-PROBE DELTA-DEPTH (read-only, реальный LLM, без Telegram)

Отдельный контур — как в r2: staging `/tmp/p0d` из deployed SHA (`git archive 076f7391`, sha-пины staging совпали с продом 4/4), SQLite снапшот-копия (sqlite3 backup, 1563 MB, прод не тронут), PG `default_transaction_read_only=on` (`ro_ok:ReadOnlySQLTransactionError`), FakeBot (ноль Telegram). Драйвер r1 байт-в-байт (`ca500edb…`), обёртка `rerun_r3.py` (`fe36a233…`) — subset S03+S06 + полный захват kw-payload Writer с счётчиками delta-констант. Прогон 26.10 15:29–15:31 UTC (S03 64.7 s, S06 16.1 s). Исполнительное примечание: первая probe-сессия оборвалась клиентским channel-read timeout — серверный прогон пережил разрыв и завершился сам; raws добраны resume-сессией (проверенный в r2 паттерн). Результаты — `plans/features/p0-delta-analysis/evidence/live-s03-reprobe.md`; raws — scratch `deploy-258134/r3-results/` (sha256-список внутри).

**Итог:** S03 **PASS** — `DELTA_READY_INSTRUCTION_TEXT` ровно 1× (носитель plan_block, остальные поля 0) + substance-строка 1×; ответ Writer-композиция 1627 симв. (темы/атмосфера/выводы по срезу 8–26.10.2026 + честный partial-coverage) вместо coverage-stub 125 симв. из r2; story не доставлен (`delivery_allowed=false`), similarity 0.089, выдуманных дат/цитат нет. S06 **PASS** — casual 58 симв., delta 0× во всех полях (research-only правило), без анонса.

## Откат (задокументирован, не выполнялся)

```
cd /var/www/admin_bot && git checkout b571602226c5e5a5845850597f6100e3a6e0d12a && sudo systemctl restart admin_bot
```
Ожидаемое после отката: 2.58.133, healthz 200. Примечания: (1) untracked 13 файлов пережили checkout — не мешают; (2) re-probe писал только в снапшот-копию БД и read-only PG — прод-данные не изменялись; (3) staging-остатки `/tmp/p0d` — scratch, прод не влияет (драйвер r1 сохранён для будущих проб).

## Итог

- **Deployed:** `076f7391` (= candidate `d167d686` + release-bump), healthz **2.58.134/200** (loopback + внешний), unit active, **NRestarts 0**, журнал чист, DDL=0 подтверждён живым процессом, артефакт-пины 6/6.
- Технические деплой-проверки — **VERIFIED** (версия/healthz/unit/journal/DDL=0/артефакт-пины/rollback-readiness).
- Обязательная live-проверка DELTA-DEPTH (S03 substance + S06 sanity) — **PASS** (`live-s03-reprobe.md`).
