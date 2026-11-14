# SMART-CORRECTIVE-01 — привязка production-расследования к требованиям

Дата: 2026-11-14. Автор: PM. Область: **только** `plans/features/smart-corrective-01/requirements-map.json` и этот файл.
Реализация этим документом **не авторизуется**. `plans/progress_scope.json`, `plans/workflow_state.md`, родительские SMART-карты, код и тесты не изменялись.

## 1. Границы и правило

1. Привязываются только строки, чья приёмка является **наблюдаемым production-фактом**: расследование двух чекап-запусков (§2), production-данные §4 (W-12), наблюдательные §2-строки, фактическая доставка промпта.
2. Ни одна implementation-строка S1-S6 и ни один AC-01…AC-24 не переводится в VERIFIED и не переформулируется.
3. Где владелец просил факты, которые **доказуемо невосстановимы**, статус остаётся PENDING с явным `evidence_state` и списком `unrecoverable` — доказательства не выдумываются.
4. Прежние доказательства 2.58.200 не переписываются; новые записи имеют собственный candidate/deployed SHA.

## 2. Идентичность и артефакты

| Поле | Значение |
|---|---|
| candidate / deployed commit | `0e4a144db476a1535ae3a2b79a7cce30354ad866` (оба поля) |
| Версия / ветка | `2.58.200` / `release/2.58.200`, PID 709883, start `2026-11-14T05:18:59Z` |
| Отчёт (durable) | `plans/features/smart-corrective-01/investigation/production-runs-and-incidents.md`, sha256 `47049fa82a39dd134a1ec70f95987250c5dd18b502b7a73666b19e3508954118` |
| Redacted raw | `plans/features/smart-corrective-01/investigation/raw/production-runs-and-incidents-2.58.200.txt`, sha256 `cd7edfcce9ed85ff4f1b670f3e2ddc2112963db33afe0766f3fd6e60680c20b6`, commit `264b4ab0` |
| Режим | read-only: только SELECT/journalctl/systemd show/каталог провайдера; без деплоя, рестартов, Telegram-сообщений и платных probe |

Все 22 записи evidence в карте указывают на реальные файлы в репозитории с совпадающим sha256 и на candidate `0e4a144d`.

## 3. S0-INVESTIGATE — два чекап-запуска (§2.1, 17 пунктов)

Ключевые восстановленные факты (основание для строк ниже):

- **Запуск A `чекап`**: `CHAT_DM8`, `smart_messages.id=2407142`, 05:47:36Z, correlation `checkup:e37c9a5d4a184d7ba189e0469ed075ba`, отчёт `output_id 1686` 05:48:23, 3 059 chars. 7 раундов / 8 tool calls, `research_reason=ok`, `research_degraded=false`, все 7 LLM-вызовов GLM/nano-gpt. `read_source_code` **дважды вернул один и тот же** 141-строчный файл (8 846 chars), `services/mca_watchdog.py` — 329 строк; GitHub/SafeFetcher не вызывался (`network_calls=0`). Точные arguments не сохранены.
- **Запуск B reply**: `smart_messages.id=2407145`, 05:54:47Z, reply на 224, correlation `0c1bb1ed17574a5c908525d5fe3f805b`, ответ `output_id 1687` 05:57:33, 2 487 chars. 4 раунда / 3 tool calls (2 успешных, 1 `source_missing`/404); локальный 404 **не** переключился на GitHub (`network_calls=0`); успешный round 3 вернул 329 строк `services/mca_watchdog.py`; финальный writer — `deepseek-flash` после таймаута nano-gpt; `tool_reason=finish`, не лимит.

| Строка | Пункт приёмки | Чем подтверждается | Статус |
|---|---|---|---|
| `SC-REP-BASE` | исходный запуск зафиксирован: ЛС, «чекап», отчёт по 2.58.200 | message 2407142, маршрут checkup→`CheckupService.checkup`, output 1686 / 3 059 chars | **VERIFIED** |
| `SC-REP-FAIL` | исследование завершилось без анализа реализации: код watchdog не прочитан | 141-строчный файл против 329-строчного watchdog; отчёт сам заявил «механизм остался непроверенным» | **VERIFIED** (путь файла — inference, отмечено) |
| `SC-REP-STOP` | чекап завершился до анализа реализации | остановка на раунде 7, `research_reason=ok`, реального лимита нет (8 calls при `MCA_TOOL_MAX_*=0`) | **VERIFIED** |
| `SC-REP-ESSENCE` | дефект: исследование не доведено внутри чекапа, отдельный запрос дал больше | A: self-declared непроверенность; B: 329 строк кода и содержательный разбор | **VERIFIED** |
| `SC-REP-FOLLOWUP` | второй запрос владельца в reply | message 2407145, reply_to 224, текст дословно | **VERIFIED** |
| `SC-REP-FOLLOW-READ` | ответ разобрал watchdog: process_id, stale, recover_stale, progress, ERROR, takeover | round 3 (329 строк) + используемые символы совпадают с кодом | **VERIFIED** |
| `SC-REP-CONSIST` | содержание сверено с исходниками 2.58.200 | символы/поведение совпадают с deployed `0e4a144d` и `watchdog-code-analysis.md` | **VERIFIED** |
| `SC-REP-GH-UNCONF` | GitHub fallback не подтверждён; отсутствие не утверждается без трасс | трассы есть: `network_calls=0` в A и в B round 2 | **VERIFIED** (основание — трасса, не ответ владельца) |
| `SC-REP-TRACE-GAP` | источник/ref/строки/calls/полнота не подтверждены и обозначены ограничением | источник, ref_kind, [1,141]/[1,329] и последовательность calls подтверждены; arguments/query/symbol, путь A и pre-cleanup тексты — нет | **PENDING** (см. §7) |
| `SC-INV-MANDATE` | read-only расследование на production-данных, журналах, traces, LLM-сведениях | 4 149 строк журнала текущего окна + 69 339 предыдущего boot, SQLite ro, PG read-only, `mca_events`/`llm_usage_events` | **VERIFIED** |
| `SC-INV-NOTGUESS` | не только исходники и гипотезы | route/identity/correlation/usage/fallback восстановлены из БД и журналов; у каждой строки класс доказанности | **VERIFIED** |
| `SC-INV-COMPARE` | сопоставлены маршруты двух запусков | таблица §A.4: A 7/8 без fallback, B 4/3 с writer-fallback и 404 без GitHub | **VERIFIED** |
| `SC-INV-NOINVENT` | невосстановимое не выдумывается | §«Ограничения доказательств» 1-11, args не подбирались, путь A помечен inference | **VERIFIED** |
| `SC-INV-OBSDEF` | пробел наблюдаемости зафиксирован, сценарий воспроизведён, наблюдаемость обеспечена | первые две части выполнены; обеспечение наблюдаемости — S5C/S5D | **PENDING** (см. §8) |
| `SC-INV-NOBLOCK` | отсутствие трассы не блокирует исправление подтверждённых дефектов | §«Ограничения…» 11 + `plan.md` §8.5: W-01…W-11 не заблокированы | **VERIFIED** (правило действует постоянно) |
| `SC-INV-EXIST` | существующие события/корреляция, без новой trace-платформы и секретов | использованы `mca_events`/`mca_incidents`/`task_jobs`/journal; chat id и текст промпта не публиковались | **VERIFIED** |

## 4. S0-PRODDATA — шесть `watchdog.jobs` инцидентов (W-12)

Восстановлено: 6 активных инцидентов (memory 3, vision.media 12, summary 3, asap8b01 **73**, mca16 15, qnd.event 19 повторов), все связанные job-ы терминальные (20 completed asap8b01, 15 completed mca16, 18 interrupted qnd, vision 8/3, summary 2/1, memory 1 cancelled); `queued`/`running` — **0**.

Смысл «72/73» (это и был открытый вопрос W-12):

- 73 — число **детекций**, не падений: span 23,0 сут, средний интервал ~7,6 ч; формула `(last-first)/60 ≈ repeat_count` не выполняется.
- «Самый старый» по `first_ts` — memory-инцидент `inc_330e13ec` (2026-10-02); 72/73 относится к `inc_4627f4bd` (asap8b01, first 2026-10-22). Оба факта зафиксированы.
- Свежий job 3550: created 06:34:03, heartbeat 06:34:04, takeover 06:35:12 при `stale=60 c`, finished 06:35:49 **completed** → **подтверждённый false-takeover**.
- `WATCHDOG_TAKEOVER` всего 125; в событии нет job identifiers (`entity_ids=NULL`), связь восстановлена по соседнему `INCIDENT` и времени.
- Effective: `MCA_JOB_STALE_SECONDS=60`, `HEARTBEAT=15`, progress-stall `600`, watchdog/incidents `true`, `process_started_at=05:18:59Z`; `mca_media_analyses.running=8` — старые строки состояния без подтверждённого потребителя.
- Классификация: detection artifacts (job завершился позже последней регистрации) + один подтверждённый false-takeover; шесть «активных» записей ≠ шесть текущих падений.

| Строка | Пункт приёмки | Чем подтверждается | Статус |
|---|---|---|---|
| `SC-WD-W12` | production-данные §4 по шести инцидентам + detection/restart/real failure/остаточная неопределённость | §B.1-B.6 отчёта; две записи evidence: `production` (данные) и `live` (состояние прода: active, `/healthz` 200, нет queued/running) | **VERIFIED**, `production_data_state=RECEIVED` |

W-12 закрывается как **расследование**. Финальная атрибуция/закрытие инцидентов остаются в `SC-WD-W05`/`SC-WD-W11`, поэтому `AC-23` — PENDING.

## 5. Строки §2 в S4-COMPLETION (наблюдательные, не implementation)

`SC-REP-FAIL`, `SC-REP-STOP`, `SC-REP-ESSENCE` размещены в S4, но их acceptance описывает **поведение исходного запуска**, а не исправление. Они переведены в VERIFIED с пометкой `evidence_slice_note`; реализация остаётся в `SC-CMP-EARLY`/`SC-CMP-*` и не затронута. `SC-REP-CAUSE` и `SC-REP-NOFOLLOWUP` требуют устранения условий → **остались PENDING**.

## 6. Доставка промпта чекапа (срез S6-PROMPT; в задании координатора — «S4 prompt-delivery»)

Production-факт: **применённый слой — global**, сохранённая владельцем редакция маршрутом чекапа **не используется**.

| Факт | Значение |
|---|---|
| Телеметрия запуска A | `prompt_source=global`, `prompt_hash=ccaf4803efe2ff79`, `prompt_version_used=global:ccaf4803efe2`, `prompt_chars=9 966` |
| Global row | `prompts.checkup_system_prompt` — 3 030 chars, sha256_16 `b0c70f974e0e`, updated `2026-10-31T12:26:32Z`, factory revision `checkup-p0-24-10` |
| `CHAT_DM8` override | отсутствует |
| `CHAT_C2` override | 12 469 chars, sha256_16 `31d175065461`, `manual_edit`, `06:11:54Z`, revision `rev:d31300ef35a0` — **не DM**, создан после обоих запусков, в A/B не участвовал |
| Резолвер | `services/checkup_service.py:85-95` читает только global (`hot.get('prompts.checkup_system_prompt')`); chat override не читается |

| Строка | Что фиксируется | Статус |
|---|---|---|
| `SC-PRM-VERSION` | установлено, какая версия реально применялась (global, hash/char/version) | **VERIFIED** + `production_finding`: сохранённая редакция не была применённым слоем |
| `SC-PRM-TELEMETRY` | использована существующая телеметрия `prompt_source/hash/version_used/chars` | **VERIFIED** |
| `SC-PRM-OWNER` | ручная редакция учтена как факт (C2, 12 469 chars, 06:11:54Z) | **VERIFIED**, но **не** записано как «доставлено» |
| `SC-PRM-PRESERVE` | сохранность значения при исправлениях и деплое | **PENDING** (доказывается на деплое corrective-релиза) + `production_finding` о расхождении слоя |
| `SC-PRM-NOTPROOF` | наличие строки в константе/админке/preview ≠ доставка | **PENDING** (правило ревью S8) + `production_finding` |
| `AC-15` | сохранённая владельцем редакция реально применяется | **PENDING**: на `0e4a144d` AC-15 **не выполнен** — доставляется global; формулировка AC не менялась |

## 7. Невосстановимые данные (не блокируют подтверждённые дефекты)

1. **Arguments tool-вызовов не хранятся**: для denied/failed есть только `args_fingerprint` (`inspect_runtime`: `f8fd28779c6508a5`, `88f6dd74bf3c427d`; `read_source_code` B round 2: `cab51a375a18197f`). Пути/query/symbol/line ranges, выбранные моделью, восстановить нельзя; подбор по вероятным комбинациям совпадений не дал.
2. **141-строчный файл запуска A** идентифицирован только по совокупности (`line_count=141`, `path_depth=6`, deployed tree, текст ответа) — это **inference**, не literal trace.
3. **`direct_turn_writer.usage_json` обрезан 2 000 символами** → revision/hash промпта для B не восстановимы.
4. **Pre-cleanup тексты моделей не хранятся** (есть delivered text, digest, chars).
5. **`checkup_triggered.trace_id=NULL`** → join только через `mca_bot_outputs` и время.
6. **Успешные tool calls не эмитятся в `mca_events`** → последовательность восстановлена по journal `TOOL_*`.
7. **`WATCHDOG_TAKEOVER` не сохраняет job_ids** → связь по времени и соседнему `INCIDENT`.
8. **`mca_media_analyses.running=8`** — только строки состояния без события-потребителя.
9. **Per-sweep история инцидентов не хранится**: `repeat_count` кумулятивен, `jobs_json` ≤ 20.
10. **Текст промпта не копировался** в отчёт/raw (только hash/длина/source).

**Правило владельца (owner input §2.2, строка 132; строка карты `SC-INV-NOBLOCK`):** отсутствие исторической трассы не должно блокировать исправление независимо подтверждённых дефектов кода. Поэтому:

- `SC-REP-TRACE-GAP` остаётся **PENDING** с `evidence_state=PARTIALLY_UNRECOVERABLE` и конкретным списком `unrecoverable`; закрытие требует явного принятия ограничения Reviewer/Architect (или сужения формулировки владельцем) и **не** блокирует S1-S6.
- `SC-INV-OBSDEF` остаётся **PENDING**: пробелы зафиксированы и сценарий воспроизведён, но «обеспечить наблюдаемость для повторной production-проверки» — это реализация S5C/S5D.

## 8. Effective-state, зафиксированный как production-факт

Блок `effective_state` в карте (артефакт — тот же отчёт):

| ID | Значение | Куда привязано |
|---|---|---|
| `EFF-FACTCHECK-V2` | **true**: PG `flags.factcheck_pipeline_v2` (2026-10-20), env отсутствует, code default False; значение приходит из PG | `SC-OVL-FC-SEM`, `SC-ACC-REG-01/02` (регрессия семантики обязана идти по v2-пути) |
| `EFF-CHECKUP-PROMPT-LAYER` | global 3 030 chars / `b0c70f974e0e`; composed 9 966 / `ccaf4803efe2`; chat override не читается | `SC-PRM-OWNER/VERSION/TELEMETRY/PRESERVE`, `AC-15` |
| `EFF-CHECKUP-FLAGS` | `checkup_enabled=true`, `checkup_memory_metrics_enabled=true` | контекст S6/AC-15 |
| `EFF-WATCHDOG-LIMITS` | stale 60 / heartbeat 15 / progress 600 / vision lease 180; watchdog и incidents включены | `SC-WD-W06/W08/W12` |
| `EFF-BUDGETS` | master budgets OFF, `MCA_TOOL_MAX_*=0`, `TOOL_CHAIN_LIMITS_ENABLED=true` (factory) — 8 calls прошли | `SC-SEARCH-FIND-CAP`, `SC-SEARCH-OFF`, `SC-BUD-NOTINF`, `SC-BUD-GUARD` |
| `EFF-PROVIDER-NANOGPT` | 1048576/32768 verified; 39 OK / 1 timeout / 1 fallback; класс «HTTP 200 + пустой content» сохраняется | все postdeploy real-LLM canaries: допускать fallback/retry |

Соседние production-факты (budgets OFF на реальном прогоне, поведение провайдера) **не** переводились в VERIFIED ни для одной implementation-строки — они доступны Builder/Reviewer как вход, но реализация не проверена.

## 9. Итог по статусам

| Метрика | Значение |
|---|---|
| Обязательных строк в карте | 384 |
| VERIFIED | **18** (13 S0-INVESTIGATE + `SC-WD-W12` + `SC-REP-FAIL/STOP/ESSENCE` + `SC-PRM-VERSION/TELEMETRY/OWNER`) |
| PENDING | **366**, включая намеренно оставленные `SC-REP-TRACE-GAP`, `SC-INV-OBSDEF`, `SC-PRM-PRESERVE`, `SC-PRM-NOTPROOF`, `AC-15`, `AC-23`, `SC-OVL-FC-SEM`, `SC-ACC-REG-01/02` |
| Записей evidence | 22 на 20 строках (все — candidate/deployed `0e4a144d`, реальные файлы с совпадающим sha256) |
| Implementation-строки S1-S6 | без изменений, все PENDING |
| AC-01…AC-24 | без изменений, все PENDING; у `AC-15` и `AC-23` добавлена production-находка без изменения формулировки |

## 10. Что дальше (вне этого документа)

1. S0/S0-PRODDATA считаются выполненными до предела восстановимости; W-12 = RECEIVED.
2. Оставшиеся ограничения: `SC-REP-TRACE-GAP` (принять ограничение) и `SC-INV-OBSDEF` (S5C/S5D).
3. Реализация S1-S6 по-прежнему требует Architect-контракта (`architecture-plan.md`), независимого ревью на точном candidate и обычных гейтов; этот документ разрешение на implementation не выдаёт.

## 11. Гейт и housekeeping

- `stage=plan inventory=224 manual=232 scoped=0 errors=0` → `evidence/gate-plan-after-investigation.txt`.
- PM-прогон: `WorkspaceData/runs/…/smart-corrective-01-0097aecc4a7a/artifact-15aa6c55b4` (закрывается `run-close --confirmed-idle --confirmed-evidence --apply`).
