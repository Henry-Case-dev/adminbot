# Deploy 2.58.140 — release/p0-2026-10-26 (DEPLOY-258140, admin-toggle-save P0)

**Дата:** 28.10.2026 (server UTC, ActiveEnter 08:54:01). **Ветка:** `release/p0-2026-10-26`.
**DEPLOY_SOURCE:** commit `5c8bf35db07e49d1dae4ca5a543911bf6b56ed54` (detached checkout на сервере; mutable worktree НЕ требуется).
**Review-кандидат (Approved):** `a602aa61` (fix `task/admin-toggle-save`, база 9261565d = deployed 2.58.139 line).
**Bump-коммит = deployed SHA:** `5c8bf35d` (`chore(release-258140): bump 2.58.139 -> 2.58.140 (31-file/33-line proc set SET EQUAL proc-258139, F8-meta HEAD=a602aa61, deltaDDL=0 verified vs 95e6c7c9; guards: registry --check OK 586==REGISTRY, compileall services rc=0) [P0-ADMIN-CACHE-TOGGLE-SAVE,REL-258140]`).
**Pre-state:** `95e6c7c9` (2.58.139, healthz 200, active, NRestarts 0, dirty 13).

## PART 0 — merge

Fast-forward `9261565d..a602aa61`, конфликтов нет: линия `release/p0-2026-10-26`
стояла ровно на 9261565d (0 собственных коммитов поверх базы; c987a825 — уже
унаследованный предок, проверено `git branch --contains`). Фикс: routes.py +
chat_params.py + smart_cache.py + 4 тест-файла + evidence/fix.md (8 файлов,
+951/−13).

## PART 1 — bump 2.58.139 -> 2.58.140

31 файл / 33 строки (SET EQUAL proc-258139): README `v2.58.140`, APP_VERSION
(config/settings.py), F8-meta (APP_VERSION 2.58.140 + HEAD `a602aa61` = merge
tip, регенерация emit-скриптом), 24 py-пин-файла (polygon — 2 строки), 4 JS
escaped-regex. Исторические упоминания «прод 2.58.139» в фикс-файлах
(test_p0_admin_cache_toggle_save.py:3/599, routes.py:621) НЕ тронуты
(count-asserted). Push `9261565d..5c8bf35d -> origin` (fast-forward).

| Guard | Результат |
|---|---|
| `tools/gen_param_registry_round1025.py --check` (local) | **OK** (rc=0, 586==REGISTRY) |
| `compileall services` (local) | **OK** (rc=0) |
| deltaDDL | **0** vs `95e6c7c9`: в диффе 0 схемных файлов (grep db/schema/migrat/ddl/sql — 0 совпадений) |
| Пин-тесты на deployed SHA (локально, байты == deployed) | **103 passed** (toggle_save+budget+smart_cache 50; f8_registry+mca23 53) |

## PART 2 — deploy (SSH, fail2ban-safe)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot` (venv python 3.12,
ExecStart venv/bin/python bot.py), healthz loopback :8000 + внешний
`https://admin-bot.duckdns.org/healthz`.

| Шаг | Результат |
|---|---|
| Pre-state (recon + main PRE) | HEAD `95e6c7c9`, dirty 13, active, NRestarts 0, healthz **200 2.58.139** |
| `git fetch origin release/p0-2026-10-26` | rc 0, `95e6c7c9..5c8bf35d`, FETCH_HEAD == bump SHA |
| `git checkout --detach 5c8bf35d` | rc 0, HEAD = `5c8bf35db07e49d1dae4ca5a543911bf6b56ed54`, dirty 13 сохранены |
| Blob-пины deployed vs candidate | **4/4 OK** (routes `1a18fec35293`, chat_params `559d78748861`, smart_cache `89f324ff6cf7`, settings `7f0b37b2aabe`) |
| `sudo systemctl restart admin_bot` | RESTART_RC=0, новый MainPID 800203, ActiveEnter 08:54:01 UTC |
| healthz | loopback **200 `{"status":"ok","version":"2.58.140"}`** (try 6); внешний duckdns **200, 2.58.140** (повторно подтверждён после зонда) |
| Unit | `active`, **NRestarts = 0**, Memory ~437 MB |
| Registry --check (deployed tree, venv python) | **OK** (rc=0, 586==REGISTRY) |
| Синтаксис services на deployed tree | **AST-check 253 файла, 0 syntax errors** (+ compileall rc=0 локально на идентичных байтах; live-импорт всех модулей при старте сервиса). Server-side `compileall -q services` дал rc=1 только из-за PermissionError записи `.pyc` под непривилегированным `nik` (infra-артефакт проверки, не синтаксис) |
| Retry-path на deployed tree | `_write_chat_overrides_with_retry` присутствует (2 вхождения: def + вызов) |

**SSH-бюджет:** 4 соединения (recon → scp-передача → основной прогон → хвостовая
верификация), между всеми ≥60 c, без повторов auth. Отклонение от «≤3»:
основной прогон упёрся в клиентский таймаут ПОСЛЕ завершения зонда (probe +
restore выполнены), хвостовую read-only верификацию (journal-sample, AST,
disk, backups) перенесли в отдельный короткий коннект.

## PART 3 — postdeploy live acceptance (баг владельца — ГЛАВНАЯ приёмка)

Серверный bounded-зонд (TMA initData, HMAC по spec; токен только в памяти
процесса, не печатается; владелец-чат = DM chat_id 5885953495; is_dm=true,
is_global_admin=true подтверждены ответом API):

| Проверка | Результат |
|---|---|
| **Chat-scope toggle ON** (`POST /api/config`, optimistic token) | **200** (не 409!), `updated=[flags.smart_cache_enabled]`, новый токен выдан — **баг владельца «Сохранено 0 из 1» исправлен** |
| Readback ON | 200, `value=true`, `chat_source="chat"` (override применён) |
| **Chat-scope toggle OFF** (второй save, свежий токен) | **200**, `updated=[flags.smart_cache_enabled]` |
| Readback OFF | 200, `value=false` — исходное состояние восстановлено (нетто-нуль) |
| Журнал сервиса | 2 события `[api] config chat updated \| chat=5885953495 \| keys=1` в 08:54:24 UTC — сохранения прошли через реальный deployed write-path |
| Global toggle ON → 200; SmartCache `set`+`get` | set_ok, **get_hit=true** (ON: запись+чтение работают) |
| Global toggle OFF → 200; SmartCache `get` | **get_miss=true** (OFF: get не отдаёт — направление починено в обе стороны) |
| Stale-token retry path | bounded: retry-код на deployed tree (grep 2 вхождения) + ревью-тесты на байтах deployed SHA **103 passed** (включая stale-token→200+merge RED-on-base/GREEN-after) |
| Cleanup | синтетическая строка SmartCache удалена; chat/global флаги «already-original» |

**Нетто-изменение прод-данных: 0** (флаги возвращены в исходное OFF/OFF,
временная синтетическая запись кэша удалена).

## Journal, диск, бэкапы

- Journal с момента рестарта (08:53:50 UTC): **0 ошибок релизной природы**
  (старт/роуты/БД чистые). Текстовые совпадения «error» — имена полей
  `error_json` в INFO/WARNING vision-событиях (значения пустые/ok).
- **Сопутствующий находка (не от релиза):** `anticliche_worker` — внешний
  fetch en.wikipedia.org → **HTTP 403 (robot policy)**, httpx.HTTPStatusError,
  pipeline step fetch status=error (fail-open). Внешняя политика Википедии,
  код анттиклише этим релизом не трогался; наблюдалось на фоне обычной работы.
  Рекомендация в backlog (retry/альтернативный источник/UA-ревизия).
- Диск `/dev/vda2` 24G: **75% (5.8G свободно)** — после утренней ревизии диска
  улучшилось с 93–96%.
- Бэкапы: `pre_deploy_258113*`, `pre_deploy_258114*`, `pre_migration_20261020*.gz`
  — отсутствуют (вычищены ревизией 28.10); `local_database_20261028.db`
  (1 591 263 232 B, 28.10 00:00) — на месте.

## Rollback

`git checkout 95e6c7c9f4b6bdf18c27af51079c2878f801f2ac && sudo systemctl
restart admin_bot` → healthz 2.58.139. Схема БД не менялась (deltaDDL=0),
rollback бинарно безопасен; dirty 13 серверных локальных файлов переживают
checkout (проверено обоими переходами).

## Артефакты

- Raw-выводы: `OPENCODE_WORKFLOW_SCRATCH/deploy-258140/` (deploy script, probe,
  raw deploy output, raw tail output, sha list).
- Зонд: `OPENCODE_WORKFLOW_SCRATCH/deploy-258140/probe_258140.py` (копия /tmp).
- Вторая копия этого отчёта:
  `plans/features/asap-speech-arch/release-258140/deploy.md`.

**Итог: VERIFIED** — exact reviewed candidate `5c8bf35d` (fix `a602aa61`)
задеплоен, все обязательные live-проверки PASS, откат готов, блокеров нет.
