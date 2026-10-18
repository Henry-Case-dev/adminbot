# ASAP8 — REV-INCIDENT-TAIL: независимая проверка закрытия инцидента Summary (INC-SUMMARY-01) — 18.10.2026

**Вердикт: инцидент закрывается.** Пункты §1–§5 отчёта `incident-tail-25887.md` (sha256 `d2a6596fe1fe2eb2…`, мой пересчёт совпал) подтверждены по raw-логам двух сессий и репо; блокирующих находок нет. Остаток — только естественная точка наблюдения (тик 18.10 01:00 UTC на 2.58.87) и трекинг untracked-документов инцидента. Правок карт не требуется (строк инцидента в картах нет — §6).

## Привязка

| Поле | Значение |
|---|---|
| Отчёт | `plans/features/asap8-v6-3-live-correction/incident-tail-25887.md` — sha256 `d2a6596fe1fe2eb2…` (пересчитан) |
| Raw | `OPENCODE_WORKFLOW_SCRATCH/incident-tail/run-25887.txt` (23:46:41 UTC), `run-25887-s2.txt` (23:55:48 UTC) + `verify_incident_tail_25887{,_s2}.py` |
| Прод (по raw) | 2.58.87 @ `82e110d6`; SSH мной не выполнялся — всё по raw/репо |

## 1. Тики — VERIFIED

- **07:00 `008c3640`**: `SUMMARY_L2_STAGE outcome=failed reason_code=l2_review_rejected` → `SUMMARY_LEGACY_FALLBACK trigger=l2_unusable`; `SUMMARY_PUBLISH success status=rich message_id=1163554`; `SUMMARY_RUN_DONE status=degraded fallback=legacy pipeline_health=degraded` ✓.
- **13:00 `5187dee4`**: `PUBLISH_RICH_COMPLETE … message_id=1164062` (sendRichMessage); `RUN_DONE status=ok fallback=none pipeline_health=ok package_grade=semantic` — первый полностью чистый ран ✓.
- **19:00 `39339fd9`**: L2 `l2_review_rejected` → legacy fallback; `COVER_STYLE_FAILED reason=bad_json fallback=style_failed` → base (публикация всё равно rich); `PUBLISH rich 1164381`; `RUN_DONE degraded/legacy` ✓.
- DB (s2, на процессе): `nonterminal_count=0`; states DEGRADED 32 / DONE 14 / FAILED 1; фантом `da33f05d…` FAILED `updated_at=16.10 16:12:30`; 5/5 терминальных ранов линии инцидент-фикса с `published`+message_id (1162997/1163339/1163554/1164062/1164381) ✓; `ORPHAN=0`, `ORPHANCLOSED=0`, `startup recovery: нетерминальных ранов нет` на всех 8 рестартах окна; disabled-чат `cron skip (disabled, source=chat)` на каждом тике ✓.
- **Закрытие отложенного тика:** `tick-observation-25883.md` §Отложено (07:00 UTC, `NOT_BEFORE 07:20`) — ран получен и терминален; его DEGRADED-класс совпадает с уже классифицированной предсуществующей L2-деградацией (публикация есть) — закрытие корректно.

## 2. `P_ERR` — VERIFIED; с выводом согласен

- Точная строка в raw: `2026-10-17 01:56:41,958 services.llm_client ERROR LLM timeout | url=nano-gpt.com… | reason=total_budget_exceeded | provider=nano-gpt.com` ✓; контекст — цикл `lore_worker` (не Summary): `01:56:42 LLM fallback attempt → api.deepseek.com` → `01:57:44 LLM fallback OK | model=deepseek-flash` → `lore_compile outcome=success duration_ms=192991` ✓.
- Согласен: одиночный транзиент провайдера со штатным fallback, влияния на сводку нет.
- ERR-баланс: `FULL_ERR=7` (TelegramNetworkError на стопе старого 2.58.82 16.10 18:08:40 + сам P_ERR + 5-строчный кластер 19:03:12 L3 graph-extract), `FULL_CRIT=0`, `FULL_TB=1` (тот же кластер), `LAST24H_ERR=6`, `SINCE87_ERR=0 / CRIT=0` — сходится ✓. Кластер 19:03 — внутри тика 19:00, штатный `SmartModule L3 (retention ON): extract failed — batch kept, pipeline continues`, ран опубликован ✓.

## 3. Стопы — VERIFIED

- `STARTED=10 / STOPPING=10`; уникальных `Deactivated successfully` = **9** (мой пересчёт; «10-я» найденная строка — дубль из grep-контекста `-B1 -A16`), `Failed with result 'timeout'` = 1, `SIGKILL=1` — всё это только известный стоп старого 2.58.82 (16.10 18:09:40) ✓; `BYE=9`, `DRAINDONE=9`, `LEFTOVER=0`, `ORPHANCLOSED=0` ✓.
- Микро-стоп 21:47:48 (авто-откат в фазе миграции) — `Deactivated successfully` без drain/bye (компоненты не подняты) — корректно отделён от полноценных graceful-стопов.
- Все стопы 85/86/87: drain `in_flight=0 | cancelled=0 | finalized=0 | left=0`, `sqlite closed`, `[shutdown] bye` (ms), `Deactivated successfully`; сигнальных убийств после старого 82 — ноль ✓. После каждого старта — `SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)` (85: 21:05:15; 87: 22:50:29) ✓.

## 4. Сервис — VERIFIED

- healthz loopback `200 {"status":"ok","version":"2.58.87"}` + HZ443 (--resolve) `200`, `HZ443_HTTP=200`; `WEB_VER = 15×2.58.87` (0×2.58.86); `CSS_HTTP=200`.
- `MainPID=3254462 NRestarts=0 ExecMainStartTimestamp=22:50:08 UTC ExecMainStatus=0 active/running`; `HEAD=82e110d6` (`release/fix-2.58.87`), `TRACKED_MOD=0`, `APP_VER=2.58.87` ✓.

## 5. Дисциплина (2 логина вместо 1) — ПРИЕМЛЕМО (документировано)

- Два одиночных логина: **23:46:41** и **23:55:48 UTC** (интервал ≈9 мин 07 с). Каждый скрипт: один `SSHClient.connect` (timeout 30), без ретраев и параллельных коннектов; удалённые команды — только чтение (`systemctl show/status`, `journalctl`, `sed/awk/grep`, `sqlite` с `mode=ro`+`query_only` через stdin, `curl`), серверных redirects/tmp/записей в raw нет; локальные записи — только Tee в лог на рабочей машине. fail2ban-лимиты не нарушены (2 успешных логина, пауза 9 мин, без провалов).
- Изменений на проде нет: `TRACKED_MOD=0`, `NRestarts=0`, `ExecMainStartTimestamp` один и тот же до/после обеих сессий (22:50:08), journal содержит только чтения ✓.
- Ниточка: формулировка «предшественников в окне не найдено» прямо в raw не зафиксирована (нет `last/who`) — читается как «в лейне только эти 2 сессии» (файлов ровно два, скрипты без ретраев); не влияет на вывод.

## 6. Карты — правок не требуется

- **asap8-карта:** строк инцидента нет. Мои 4 первичных «попадания» — false-positive: подстрока `fix-report` матчила `fullscreen-hotfix-report.md` в U07-строках (fullscreen, не инцидент). **soul-карты:** ссылок на инцидент нет.
- Инцидент трекается документами (`incident-summary-01-fix-report.md`, `incident-summary-01-shutdown-report.md`, `review-incident-summary-01.md`, `tick-observation-25883.md`, `incident-tail-25887.md`), а не картой → **точных правок (req_id/текст) нет — перечислять нечего**; карты не трогал.
- Рекомендации (вне гейта, не блокеры): (а) закоммитить 4 untracked документа инцидента (`incident-tail-25887.md`, `tick-observation-25883.md`, `incident-summary-01-code-analysis.md`, `incident-summary-01-prod-forensics.md`) — за лейном/PM; (б) Orchestrator — перевести `INC-SUMMARY-01` в CLOSED в `workflow_state.md` (сейчас «INCIDENT-TAIL DONE → VERIFY-INCIDENT идёт») со ссылкой на этот вердикт; (в) точка наблюдения — тик **18.10 01:00 UTC** на 2.58.87 (первый тик на новой линии); (г) инцидентная ниточка `usage_json coverage=0.0 / source_considered=0` у всех ранов (включая DONE) — в отчёте как наблюдение; при касании Inspector проверить legacy-поля (backlog).

## Ledger

| Пункт | Статус |
|---|---|
| 1. Тики (3 терминальных/rich, nonterminal=0, phantom, deferred-tick) | VERIFIED |
| 2. `P_ERR` (lore_worker, fallback OK, ERR=6/24ч, 0 с 87) | VERIFIED (одиночный транзиент) |
| 3. Стопы (10=9 graceful+1 известный, SIGKILL/leftover/orphan=0) | VERIFIED |
| 4. Сервис (healthz 2.58.87, 15×, NRestarts=0, HEAD) | VERIFIED |
| 5. Дисциплина (2 логина, read-only, следов нет) | ПРИЕМЛЕМО (документировано) |
| 6. Карты (правок нет; рекомендации) | VERIFIED (нет строк инцидента) |

**Итог:** инцидент закрывается; блокирующих находок нет; остаток — точка наблюдения 18.10 01:00 UTC и трекинг документов/леджера.
