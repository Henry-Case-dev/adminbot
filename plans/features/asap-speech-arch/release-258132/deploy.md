# Deploy 2.58.132 — release/p0-2026-10-26 (DEPLOY-258132)

**Дата:** 26.10.2026. **Ветка:** `release/p0-2026-10-26`.
**Одобренный код-коммит (candidate):** `11b250bf` (merge task/p0-delta @ `2ef0615a`; review Approved + micro-fix).
**Bump-коммит = deployed SHA:** `d3a9a2cc8ff22779c121e7c97a1432d42f13e6e4` (`chore(release-258132): bump 2.58.131 -> 2.58.132 (31-file/32-pin proc set, F8-meta HEAD=11b250bf, deltaDDL=0)`, 31 файл, 33 пина: README, APP_VERSION, F8-meta (APP_VERSION 2.58.132 + HEAD `11b250bf`), 24 py-теста (polygon — 2 пина), 4 JS (escaped-regex)).
**Предыдущий прод:** `fa74ecf8` (2.58.131, healthz 200, active, NRestarts 0).
**DeltaDDL:** **0** — `git diff fa74ecf8 11b250bf --stat`: 18 файлов, только код/тесты/evidence; миграций/SQL нет; прод-журнал подтверждает `[database] migrations: start | current user_version=37 | pending=[]` → `complete | user_version=37 | total 0.0s`. `requirements*.txt` diff пуст (0 зависимостей).

## Guard'ы (post-bump, worktree `adminbot-wt-rel-p0`)

| Guard | Результат |
|---|---|
| `py -3 tools/gen_param_registry_round1025.py --check` | **OK**: реестр 582 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны |
| `py -3 -m compileall services` | **OK** (rc=0) |
| factcheck/delta focused tests | пройдены до merge (734 + 1110+152) — по заданию не повторялись |

## Деплой (SSH, 2 сеанса, fail2ban-safe)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot`. Recon (~15 c) + основной сеанс; интервал > 1 мин, одиночный логин, без ретраев.

| Шаг | Результат |
|---|---|
| Pre-state | HEAD `fa74ecf8`, dirty **13** (untracked, не тронуты), healthz `{"status":"ok","version":"2.58.131"}`, active, NRestarts 0 |
| `git fetch origin release/p0-2026-10-26` | rc 0, `fa74ecf8..d3a9a2cc` |
| `git checkout --detach d3a9a2cc` | rc 0, HEAD = `d3a9a2cc`, dirty 13 сохранены |
| `sudo systemctl restart admin_bot` | RESTART_OK, новый MainPID **260518** |
| Post (settle ~45 c) | unit `active/running`, **NRestarts = 0**, healthz loopback **200** `{"status":"ok","version":"2.58.132"}` |
| Журнал (окно рестарта) | **0 ERROR / CRITICAL**; 2 Traceback — pid 224410 (СТАРЫЙ процесс, шатдаун-гонка `no active connection` при остановке 11:32:40, до старта нового) → новых ошибок нет; `NEWPID_ERR=0` |
| `flags.factcheck_wide_context` | **ON сохранён**: `[factcheck_wide_context_migration] уже применено — no-op` (pid 260518) |
| Внешний healthz (27.10, +12 ч) | **200** `{"status":"ok","version":"2.58.132"}` |
| LLM auth в проде с деплоя | реальных 401/auth-ошибок нет (grep-совпадения — hex-хэши) |

## LIVE-SCENARIOS §12 (read-only, реальный LLM, без Telegram)

Отдельный контур: стейджинг `/tmp/p0d` из deployed SHA (`git archive`, `STAGE_MATCH`), SQLite — серверный снапшот-копия (`sqlite3 backup` API, 1.6 GB, прод не тронут), PostgreSQL — `default_transaction_read_only=on` (probe `ro_ok:ReadOnlySQLTransactionError`), FakeBot (ноль Telegram). Драйвер `live_scenarios_12.py` (sha256 `ca500edb…`), реальный `_handle_turn` + реальный hot-конфиг из PG (`wide_context_hot=true`, модель `deepseek/deepseek-v4.1-flash`). Прогон 26.10 12:42–12:50, все 10 сценариев выполнены. Результаты и вердикты — `plans/features/p0-delta-analysis/evidence/live-scenarios.md`; raws — `OPENCODE_WORKFLOW_SCRATCH/p0d-258132-live-scenarios/` (sha256-список внутри).

**Итог §12:** 8/10 критериев PASS; **FAIL** — «lore story не подменяет analysis-ответ» на S03/S05/S07/S10 (story дословно/почти дословно становится ответом при research-плане, гейт доставки при этом честно `False`). → Builder → Reviewer (см. live-scenarios.md §Находка).

## Откат (задокументирован, не выполнялся)

```
cd /var/www/admin_bot && git checkout fa74ecf8 && sudo systemctl restart admin_bot
```
Ожидаемое после отката: 2.58.131, healthz 200. Примечания: (1) fresh-снапшоты/стейджинг лежат в `/tmp/p0d` (scratch, прод не влияет); (2) untracked 13 файлов пережили checkout — не мешают; (3) прогон §12 писал только в снапшот-копию БД — прод-данные не изменялись.

## Итог

- **Deployed:** `d3a9a2cc` (= candidate `11b250bf` + release-bump), healthz **2.58.132/200** (loopback + внешний, стабильность +12 ч), NRestarts 0, журнал чист.
- Технические деплой-проверки — **VERIFIED** (версия/healthz/unit/journal/DDL=0/wide-context/rollback-readiness).
- Обязательная live-приёмка §12 — **FAILED** по одному критерию (lore-подмена analysis-ответов) → маршрут Builder→Reviewer; прод на 2.58.132 не откатывается (поведение не хуже 2.58.131, гейт-улучшение осталось).
