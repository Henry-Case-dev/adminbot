# INCIDENT-TAIL-25887 — хвост INC-SUMMARY-01 на проде 2.58.87 (Summary-тики, `P_ERR`, graceful-стопы 85/86/87)

Захваты: read-only SSH, **два одиночных логина, без ретраев, без изменений на хосте** (только чтение; DB открывалась `mode=ro` из stdin, файлы на сервере не создавались):
сессия №1 — **2026-10-17 23:46:41 UTC** (полный прогон); сессия №2 — **2026-10-17 23:55:48 UTC**
(короткая, закрыла два дефекта самого скрипта: относительный `DB_PATH` читался из home; строки тиков были вытеснены из `tail` слишком широким grep — `scheduler` матчил `apscheduler` каждые 5 c).
Прод: **2.58.87 @ `82e110d6`** (ветка `release/fix-2.58.87`, TRACKED_MOD=0).
Сырые логи/скрипты: `OPENCODE_WORKFLOW_SCRATCH/incident-tail/run-25887.txt`, `run-25887-s2.txt`,
`verify_incident_tail_25887.py`, `verify_incident_tail_25887_s2.py`.

## 1. Свежие Summary-тики (новые с прошлого наблюдения 17.10 05:46 UTC)

Все три плановых тика (cron `0,6,12,18 Asia/Yekaterinburg` = 19/01/07/13 UTC) — **терминальные, каждый с публикацией rich** в чат `-1002661910336`:

| Тик UTC | run_id (short) | Процесс | State | L2 | Публикация (rich) |
|---|---|---|---|---|---|
| 17.10 07:00:00 | `008c3640` | 2.58.83 | DEGRADED (health=degraded) | `l2_review_rejected` → LEGACY_FALLBACK | `SUMMARY_PUBLISH … status=rich … message_id=1163554` (cover style `medved_press` rev7 — OK после retry) |
| 17.10 13:00:00 | `5187dee4` | 2.58.83 | **DONE** (health=ok, fallback=none) | `SUMMARY_L2_STAGE outcome=success` (9 абзацев) → HYBRID_PUBLISHED | `message_id=1164062` (cover styled OK) |
| 17.10 19:00:02 | `39339fd9` | 2.58.84 | DEGRADED (health=degraded) | `l2_review_rejected` → LEGACY_FALLBACK | `message_id=1164381` (cover `bad_json` → base-fallback, публикация всё равно rich) |

- **Закрыт отложенный 3-й тик** (`tick-observation-25883.md` §Отложено: 07:00) + два новых; итого на линии инцидент-фикса 5/5 терминальных ранов с публикацией: 16.10 19:00 → `1162997`, 17.10 01:00 → `1163339`, 07:00 → `1163554`, 13:00 → `1164062`, 19:00 → `1164381`.
- **13:00 — первый полностью чистый ран** после инцидента: `SUMMARY_COMPLETE … status=ok | fallback=none | cover_status=ok | health=ok`.
- DB: `nonterminal_count=0`; states DEGRADED 32 / DONE 14 / FAILED 1; фантом `da33f05d…` без изменений (`updated_at`=16.10 16:12:30, штатное durable-состояние). При каждом рестарте 17.10: `startup recovery: нетерминальных Summary-ранов без живого владельца нет`. `SUMMARY_ORPHAN_RUN_CLOSED=0` за всё окно.
- Disabled-чат `-1004482340693` на каждом тике — штатный `cron skip (disabled, source=chat)`.
- Тик 18.10 01:00 UTC на момент захвата ещё не наступил; пройдёт уже на 2.58.87 (точка естественного следующего наблюдения, не блокер).

## 2. `P_ERR` — вердикт: найден и идентифицирован (к инциденту не относится)

Разыскивавшаяся с 17.10 одиночная ERROR-строка (окно «между 16.10 19:22 и 17.10 05:46»):

```
2026-10-17 01:56:41,958 - services.llm_client - ERROR - LLM timeout | url=https://nano-gpt.com/api/v1/chat/completions | reason=total_budget_exceeded | provider=nano-gpt.com
```

Контекст (тот же процесс, цикл `lore_worker`, **не** Summary-пайплайн): 01:56:11 retry (ReadTimeout) → 01:56:41 `total_budget_exceeded` → 01:56:42 **fallback на api.deepseek.com** → 01:57:13 fallback-retry (ReadTimeout) → **01:57:44 `LLM fallback OK`**; цикл завершён штатно: `lore_compile … outcome=success … duration_ms=192991`. Транзиентный провайдерский таймаут, fallback отработал; влияния на сводку нет.

ERROR по окну 16.10 18:00 → 17.10 23:47: `ERR=7 / CRIT=0 / Traceback=1`:
1. 16.10 18:08:40 `TelegramNetworkError` при остановке старого 2.58.82 (известная, на стопе);
2. 17.10 01:56:41 — сам `P_ERR` (выше);
3–7. 17.10 19:03:12 (внутри тика 19:00) — кластер из 5 строк: `LLMTimeoutError` на L3 graph-extract, `SmartModule L3 (retention ON): extract failed — batch kept, pipeline continues` (+1 Traceback той же точки); ран завершился и опубликовался.

За сутки `LAST24H_ERR=6` (P_ERR + кластер 19:03); **с деплоя 2.58.87 (≥23:00): `ERR=0 / CRIT=0 / Traceback=0`**.

## 3. Graceful-стопы рестартов (85/86/87; фон 83/84)

Окно 16.10 18:00 → 17.10 23:46: `STARTED=10 / STOPPING=10`. **Сигнальных убийств после 16.10 — ноль**: `stop-sigterm=1` и `Killing=2` относятся только к известному стопу старого 2.58.82 (16.10 18:09:40, `State 'stop-sigterm' timed out. Killing.` + SIGKILL, `Failed with result 'timeout'`) — задокументирован ранее. У всех остальных: `Deactivated successfully` (exit 0), `SUMMARY_SHUTDOWN_SQLITE_LEFTOVER=0` за всё окно, drain `in_flight=0 | cancelled=0 | finalized=0 | left=0`.

| # | Время UTC | Событие | PID | Подпись |
|---|---|---|---|---|
| 1 | 16.10 18:08:40 | стоп 2.58.82 (деплой 83) | 2894631 | известный негraceful: `bye` есть, но SIGKILL через 60 c (старый код) |
| 2 | 16.10 18:10:14 | 83, 2-й рестарт | 2916597 | graceful: sqlite closed, `bye elapsed_ms=770`, Deactivated OK |
| 3 | 17.10 18:44:58 | FS-84: 83→84 | 2916763 | graceful: `bye=3787 ms`, Deactivated 18:45:12 |
| 4 | 17.10 18:45:46 | FS-84, 2-й рестарт | 3204802 | graceful: `bye=636 ms`, Deactivated 18:45:49 |
| 5 | 17.10 21:04:43 | **85: 84→85** | 3204968 | graceful: sqlite closed, `bye=3228 ms`, Deactivated 21:04:54 |
| 6 | 17.10 21:46:06 | 86 попытка-1: 85→86 | 3232336 | graceful: `bye=1605 ms`, Deactivated 21:46:12 |
| 7 | 17.10 21:47:48 | 86 авто-откат (фаза миграции → 85) | 3240765 | мгновенный чистый выход `Deactivated successfully` (exit 0); drain/bye не логируются (компоненты не подняты); SIGKILL нет |
| 8 | 17.10 21:51:24 | 86 попытка-2: 85→86 | 3241212 | graceful: `bye=2022 ms`, Deactivated 21:51:30 |
| 9 | 17.10 21:54:47 | 86 enablement: рестарт с осями ON | 3242398 | graceful: `bye=693 ms`, Deactivated 21:54:51 |
| 10 | 17.10 22:49:55 | **87: 86→87** | 3243319 | graceful: sqlite closed, `bye=3269 ms`, Deactivated 22:50:08 |

- Арифметика по брифу: «выкаты 85/86/87» — это **6 стоп-событий** (85:1; 86: 3 graceful + 1 микро-стоп в фазе миграции при авто-откате; 87:1); все — graceful, 0 SIGKILL.
- После каждого старта: `SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)` (85: 21:05:15; 87: 22:50:29).

## 4. Сервис / healthz / версия

- `ActiveState=active SubState=running`, MainPID=3254462, **NRestarts=0**, ExecMainStatus=0, `ExecMainStartTimestamp=Sat 2026-10-17 22:50:08 UTC` (совпадает с рестартом 87).
- healthz loopback `200 {"status":"ok","version":"2.58.87"}`; 443 (--resolve) — 200, то же тело; `/web/` — 15×`2.58.87`, 0×`2.58.86`; `app.css` 200.
- git: HEAD `82e110d67120b86373fb23a81c8612ec5143a589` (`release/fix-2.58.87`), TRACKED_MOD=0; `APP_VERSION = "2.58.87"`.
- Журнал: ретенция покрывает ≥ 15.10 12:00 (окно поиска `P_ERR` доступно), объём 200.9M.

## Ключевые строки-доказательства

- `SUMMARY_RUN_DONE … "publication": "rich", "message_id": 1164062, "fallback": "none", "pipeline_health": "ok"` (13:00, первый чистый ран).
- `SUMMARY_COMPLETE | run_id=008c3640… | status=ok | duration_ms=466931 | cover_status=ok | publication_status=ok | health=degraded` (07:00).
- `services.llm_client - ERROR - LLM timeout … reason=total_budget_exceeded` → `services.llm_client - WARNING - LLM fallback attempt … provider=api.deepseek.com` → `services.llm_client - WARNING - LLM fallback OK | model=deepseek-flash` (17.10 01:56–01:57, `P_ERR` + восстановление).
- `[shutdown] bye | elapsed_ms=3228` (85) и `[shutdown] bye | elapsed_ms=3269` (87); `admin_bot.service: Deactivated successfully.` в обоих.
- `HZ8000={"status":"ok","version":"2.58.87"}` · `HZ443_HTTP=200` · `NRestarts=0`.

## Вердикт

**Инцидент Summary (INC-SUMMARY-01) закрывается**: все свежие тики терминальны и опубликованы rich, идентифицирован и объяснён последний неразобранный `P_ERR`, все рестарты выкатов 85/86/87 — graceful (SIGKILL/leftover/orphan отсутствуют), прод здоров на 2.58.87.
Остаётся (не блокеры, вне инцидента): (а) следующий плановый тик 18.10 01:00 UTC пройдёт уже на 2.58.87 — точка естественного наблюдения; (б) предсуществующие классы — L2→legacy-деградация части ранов и cover-style `bad_json` (публикация rich сохраняется), L3 graph-extract timeout 19:03 со штатным `batch kept`; (в) фантом-бейдж Oversight — предсуществующее, durable-состояние корректно (FAILED).

Incidental (класс: предсуществующее, вне инцидента, `uncertain`): в `usage_json` SUMMARY_RUN_DONE у **всех** ранов (включая DONE, в т.ч. 16–17.10 до деплоя 86/87) стоят `coverage=0.0` и `source_considered=0` — согласуется с заменой единого скаляра покрытия на 4 оси Inspector в линии 2.58.83 (см. док-строку `APP_VERSION` в журнале/git); поля, похоже, legacy. На поведение публикации не влияет; включено в леджер как наблюдение, не как блокер.

Происхождение/дисциплина: 2 одиночных read-only логина (23:46:41 и 23:55:48 UTC, интервал ~9 мин, без ретраев и параллельных коннектов); предшественников в окне не найдено; изменений на проде нет (ни файлов, ни git, ни systemd).
