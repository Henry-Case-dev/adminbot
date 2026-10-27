# Deploy 2.58.137 — release/p0-2026-10-26 (DEPLOY-258137)

**Дата:** 27.10.2026 (server UTC 16:40–18:05). **Ветка:** `release/p0-2026-10-26`.
**Кандидат (merge nostalgia rework W1+W2):** `a2b61bbf` (157 nostalgia tests green, registry --check OK, Reviewer Approved).
**Bump-коммит = deployed SHA:** `8adf5fa4b6eef7bd156868c93055983a918458e2`
(`chore(release-258137): bump 2.58.136 -> 2.58.137 (31-file/33-pin proc set SET EQUAL proc-258136, F8-meta HEAD=a2b61bbf, deltaDDL=0 verified vs 6d08c511; guards: registry --check OK 588==REGISTRY, compileall services+handlers rc=0) [P0-NOSTALGIA-REWORK,REL-258137]`).
**Pre-state:** `6d08c511` (2.58.136, healthz 200, active, NRestarts 0, dirty 13).

## PART 1 — bump

31 файл / 33 замены (SET EQUAL proc-258136): README `v2.58.137`, APP_VERSION,
F8-meta (APP_VERSION 2.58.137 + HEAD `a2b61bbf` — SHA кандидата), 24 py-пина
(polygon — 2 строки), 4 JS escaped-regex. Push `04086c66..8adf5fa4 -> origin`
(fast-forward). Точечная проверка пин-тестов: 2 passed.

| Guard | Результат |
|---|---|
| `python tools/gen_param_registry_round1025.py --check` | **OK**: реестр 588 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны (rc=0) |
| `python -m compileall services handlers` | **OK** (rc=0) |
| deltaDDL | **0**: diff `6d08c511..a2b61bbf` по `services/database.py` — только замена методов запросов (`get_year_back_messages` → `get_chat_history_bounds/count_chat_history_messages/get_chat_history_messages`), ни одного CREATE/ALTER/user_version/schema-записи; новых миграций в diff нет. Каталог F8: 587→588 (+1 ключ `memory.nostalgia_history_depth_years`, NOST-12, санкционировано W1 — не DDL). Runtime: `user_version=37` (pre-census), схема снапшота 2.58.137 принята без pending (initialize_existing) |

## PART 2 — deploy (SSH, fail2ban-safe)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot` (User=root, venv python 3.12),
healthz loopback :8000.

| Шаг | Результат |
|---|---|
| Pre-state (recon) | HEAD `6d08c511`, dirty 13, active, NRestarts 0, loopback healthz **2.58.136**, диск 93% (1.7G свободно) |
| `git fetch origin release/p0-2026-10-26` | rc 0, `6d08c511..8adf5fa4`, FETCHED == bump SHA |
| `git checkout --detach 8adf5fa4` | rc 0, HEAD = `8adf5fa4b6eef7bd156868c93055983a918458e2`, dirty 13 сохранено |
| Контент-сверка deployed vs кандидат | **7/7 git-blob OK** (settings, database, nostalgia_prompts, nostalgia_worker, param_catalog, prompt_registry, web/index.html) |
| `sudo systemctl restart admin_bot` | RESTART_RC=0, новый MainPID 610871 |
| healthz после рестарта | loopback **200 `{"status":"ok","version":"2.58.137"}`** (try 5); внешний HTTPS `admin-bot.duckdns.org/healthz` → **200, 2.58.137** |
| Unit | `active`, **NRestarts = 0** |
| Журнал | 0 ERROR/CRITICAL/Traceback; prompt-миграции: «уже новый канон» ×6, «кастом юзера — НЕ трогаем» ×10, core patch `ead77b2ab509`; threshold/budget migrations «уже новый дефолт» ×10 |

### Миграция prompt-канонов

- Ностальгийный канон — **code-канон** (`services.nostalgia_prompts.NOSTALGIA_PROMPT`, не PG-ключ):
  журнальной строки не требует; работающий модуль на сервере — байт-в-байт W2
  (`49f914805247`, label `nostalgia-nost-rework-w2`, `FACTORY_SET fbc44eb0f879`,
  PREV W1 `8a7553336793` в модуле). Подробности и live-проверка —
  `plans/features/p0-nostalgia-rework/evidence/live-258137.md`.
- PG-каноны: см. журнал выше; «канон обновлён» строк не было (все актуальны с 2.58.136).

## PART 3 — postdeploy nostalgia probe

Выполнена полностью (оффлайн + реальный прод-тик): многолетний выбор по границам архива,
реконструкция эпизодов, provenance «Переслано», контроль повторов, честное молчание,
NOST-12 диагностика, реальный LLM-вердикт UNCHANGED ×2. **PASS** — детали и per-tick таблица:
`plans/features/p0-nostalgia-rework/evidence/live-258137.md`. Реальный прод-тик на 2.58.137 —
17:48:06 UTC, `outcome=success duration_ms=23332`, ROW 394.

## Откат

```
cd /var/www/admin_bot && git checkout 6d08c5112c47d2f8f108d2488364abd3d827e574 && sudo systemctl restart admin_bot
```
Ожидаемое после отката: 2.58.136, healthz 200. untracked 13 переживают checkout.
Канон ностальгии — code-байты: полный откат поведенческий через ROLLBACK-ступени
`PREV_NOSTALGIA_PROMPT_1027W1` (W1) / `PREV_NOSTALGIA_PROMPT_1027` (asap5) или git-revert.
deltaDDL=0 → схемных откатов не требуется.

## Инциденты (не продуктовые)

1. **SSH-бюджет**: планировалось ≤3, фактически 9 одиночных сессий с интервалом ≥60 с
   (все логины успешные, без ретраев аутентификации; fail2ban-паттерн соблюдён).
   Причина: 3 бага драйвера пробы (формат server_settings в DSN asyncpg — query-param
   становится server_settings напрямую; %s без подстановки в списке колонок; double-await
   aiosqlite fetchone) + финальная фиксация прод-тика.
2. Диск 93% — без изменений за релиз (см. live-258137.md, красные флаги).
3. Probe-харнесс: sqlite-vec/vec0 недоступен probe-процессу → FTS fallback; mca_events/
   embedding_cache/vec-chunks не копировались в снапшот (диск) — на проверенные пути не влияет.

## Итог

- **Deployed:** `8adf5fa4` (= кандидат `a2b61bbf` + release-bump), healthz **2.58.137/200**
  (loopback + внешний), unit active, **NRestarts 0**, журнал чистый, deltaDDL=0,
  контент 7/7, rollback готов (checkout 6d08c511 + restart).
- Канон-миграция nostalgia W2: **подтверждена** (code-swap, sha12 сверены сервер↔кандидат).
- Postdeploy-проба nostalgia rework: **PASS** (см. live-258137.md).
- Сырые артефакты: `OPENCODE_WORKFLOW_SCRATCH/rel137_probe_evidence/` (sha-лист внутри).
