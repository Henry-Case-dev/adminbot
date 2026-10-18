# P0-Vision FIX2 (V-FIX2) — design-note: тик воркера без пропусков, per-chat state, 429, 2026-10-19

Срез закрывает три находки живой приёмки 2.58.91
(`plans/features/p0-vision-universal/evidence/release-25891/acceptance/README.md`,
Findings 2/6 + rate-limit вопрос) и блокер NF-1 ревью `e3fa4e97`
(`plans/features/p0-vision-universal/review-v-fix2.md`). База: HEAD `e3fa4e97`
(master), правки без коммита — на ревью. Файлы: `services/mca_vision.py`
(f8cb004c6c84), `web/api/routes.py` (d54cc29695c7), тесты + два hash-пина
(`tests/test_round1025_f8_registry.py`, `tests/test_mca23_planned_vs_actual.py`);
`web/app.js` не менялся.

## 1. BLOCKER P0V-PIPE-WORKER — почему тик всё ещё пропускался (RCA)

**Симптом (живой журнал, since T0):** `SKIPS=36`
`Execution of job "VisionMediaWorker._tick" skipped: maximum number of running
instances reached (1)`, окно 20:17–21:07, и **серии по 2–5 подряд идущих
тиков** (20:27:23/28/33, 21:02:28…48). Серия из N подряд = инстанс тика жил
N×5 с ⇒ 10–25 с.

**Что это НЕ было:** D9 уже убрал из тика долгие vision-вызовы (claim +
фоновые задачи) — и это подтверждено: обработка шла фоном, ошибок не было.
Долгими оказались **БД-фазы самого тика**:

- `_tick_body` ждал `recover_stale` — write-транзакцию через single-writer
  `DatabaseService.write_transaction` с bounded-retry на лок;
- `_expire_deferred` — до 50 последовательных `finish()` (каждый — отдельная
  write-транзакция с тем же локом);
- чтение `active()` идёт через ЕДИНСТВЕННОЕ aiosqlite-соединение и встаёт в
  очередь за любой пишущей транзакцией.

`busy_timeout` соединения = **5 с** (`services/database.py:_BUSY_TIMEOUT_MS`) —
ровно интервал тика `VISION_TICK_SECONDS = 5`; плюс backoff повторов
(0.1/0.2/0.4 с). Лок в те же окна виден прямо в журнале: `database is locked`
в 20:40:14, 20:41:19/40, 21:03:19/40, а пропуски — в 20:40:18, 20:41:43,
21:03:23/58 (сразу после исчерпания лока). То есть APScheduler выбрасывал
следующий тик, пока предыдущий ещё ждал БД, — и в это время очередь не
обслуживалась вообще.

## 2. Решение (никогда не пропускаемый энтри)

- `_tick` (джоб планировщика) **не делает БД-работы и не имеет ни одного
  `await` до `create_task`**: только `_request_claim()` +
  `_request_maintenance()`. Инстанс завершается в следующей итерации
  event-loop (микросекунды) ⇒ `max_instances=1` выбросить его не может ни при
  долгом vision-вызове (D9), ни при занятой/залоченной БД (FIX2).
  Честная граница этого аргумента: снятие инстанса APScheduler всё равно
  требует одной итерации цикла, поэтому «тик не пропустится» гарантировано
  ровно настолько, насколько жив event-loop; блокировку самого цикла на >5 с
  это не лечит. Наблюдённый отказ — не она: серии по 2–5 подряд идущих
  пропусков означают, что инстанс ЖИЛ 10–25 с (тело тика ждало БД), а не что
  цикл стоял; при стоящем цикле пострадали бы все APScheduler-джобы и
  отзывчивость бота, чего в журнале нет (ERR=0, остальные воркеры тикали).
- **Два независимых фоновых sweep'а** с раздельным single-flight:
  * claim (`_claim_sweep` → `_claim_once`): `active()` + CAS-claim
    (`mark_running` только из `queued`) + запуск обработок + backfill ниже
    live — **быстрый путь, без записи в БД**;
  * уборка (`_maintenance_sweep`): `recover_stale` → `_expire_deferred`,
    каденс `VISION_MAINTENANCE_SECONDS = 30 с` (было — каждый тик, т.е. 5 с:
    лишняя write-нагрузка на и без того залоченную БД; `recover_stale` и TTL
    измеряются минутами/часами).
  Медленная уборка больше не задерживает claim: это разные задачи.
- Каждая фаза bounded (`VISION_SWEEP_STAGE_TIMEOUT_SECONDS = 30 с`); таймаут
  или сбой фазы не отменяет остальные и не роняет процесс. Фазы идемпотентны
  (`recover_stale` — повторный UPDATE, expire — терминальный `finish` только
  из `queued`), поэтому отмена по таймауту безопасна.
- **Сохранены** CAS-claim (без дублей), heartbeat живой джобы,
  `recover_stale(stale_after_seconds=120)`, deferred-TTL → `skipped`,
  приоритет manual > auto, backfill только при пустой live-очереди,
  breaker, `drain`/`shutdown` (sweep'ы живут в lifecycle, но не занимают
  слоты `_inflight` — слоты конкуренции остались ровно `ANALYSIS_CONCURRENCY`).
- Наблюдаемость: при фазе ≥ интервала тика пишется
  `[vision] claim sweep slow | dur=…` / `maintenance stage timeout | stage=…`,
  т.е. в повторной приёмке видно, что именно тормозит, при `SKIPS=0`.

**Тесты (RED→GREEN, `tests/test_p0_vision_fix_core.py`):**
`test_fix2_tick_entry_returns_immediately_while_db_busy` (энтри < 0.5 с при
искусственно 5-секундных `recover_stale`/`active`),
`test_fix2_tick_never_skipped_with_slow_db_stage` (медленная фаза 1 с при
интервале 0.2 с: **ноль** `maximum number of running instances`, планировщик
реально тикал ≥3 раз, медленная фаза шла фоном, очередь при этом доехала до
`ready`). RED-лог содержит подлинный прод-симптом APScheduler.

## 3. P0V-PIPE-E2E / UI — `GET /api/vision/state` без per-chat контекста

`runtime_snapshot(db)` вызывал `resolve_effective_state()` **без chat_id**, т.е.
считал только глобальный слой `flags.vision_enabled`. Прод: глобально
`False`, в чате per-chat override `true` → эндпоинт отдавал
`requested=false/vision_disabled`, хотя рантайм в этом чате работает
(`resolve_effective_state(chat)` → `requested=true`, capability-лимит).

- `runtime_snapshot(db=None, chat_id=None)` → `resolve_effective_state(chat_id)`;
- маршрут принимает `chat_id` (query) или `X-Chat-Id` (header) — **UI править
  не пришлось**: `web/app.js::api()` уже ставит `X-Chat-Id` для активного чата
  (`:6224-6227`), и оба вызова `/api/vision/state` (`:9302`, `:12858`) идут
  без `global:true`;
- без контекста поведение прежнее (глобальный слой); **чужой чат** (нет
  доступа по `access_srv.can_access_chat` для chat-scope ctx) → тоже
  глобальный слой — прецедент `/api/status`, без утечки per-chat настроек;
- RBAC не менялся (global admin ИЛИ `can_view_key_value(keys.vision_api_key)`),
  маскировка секретов не менялась (R17-проверка в тесте).
- Тест: `test_route_vision_state_per_chat_context` (без заголовка — прежний
  `vision_disabled`; с `X-Chat-Id` — `requested=true`; чужой чат — снова
  глобальный слой; секрет не раскрыт).

## 3a. NF-1 (ревью `e3fa4e97`): проба тоже отдаёт контекстный `state`

Ревью нашло: `POST /api/vision/test` вызывал `runtime_snapshot(lore_db())` без
chat-контекста, а UI после пробы делает `self.visionState = vprobe.state`
(`web/app.js:14780`). В прод-сценарии (глобально OFF, per-chat ON) нажатие
«Проверить подключение» возвращало линию/факты к глобальному
`vision_disabled` на ~30 с — прямое противоречие цели FIX2 на том же экране.

Фикс: единый хелпер `_vision_chat_scope(cache, user, chat_id, x_chat_id)`
(та же резолюция, что была в `get_vision_state`: явный `chat_id` → `X-Chat-Id`
→ `can_access_chat` для chat-scope ctx, иначе глобальный слой); применяется в
ОБОИХ маршрутах — `GET /api/vision/state` и `POST /api/vision/test`
(`state = runtime_snapshot(..., chat_id=scope_chat)`). RBAC, R17-маскировка и
контракт ответа пробы не менялись; новых endpoint'ов нет.

**UI не менялся** (`web/app.js` = b14ef48ab16a, clean): проба идёт через
`this.api(...)` (`:14775`), т.е. с `X-Chat-Id` активного чата, поэтому
`vprobe.state` теперь контекстно-корректен; отдельная UI-правка «не перетирать
state» не нужна (устаревшего глобального значения в ответе больше нет).

Тест: `test_route_vision_test_state_per_chat_context` — без заголовка
`requested=false/vision_disabled`; с `X-Chat-Id` включённого чата
`ok=true` + `state.requested=true` (не `vision_disabled`) + секрет не раскрыт;
чужой чат → глобальный слой. RED-NF1: при откаченном `web/api/routes.py` тест
падает `assert False is True` (`red-nf1-2026-10-19.txt`).

## 4. 429 (провайдерский лимит) — «не залипает»

Проверка семантики после 429 (нашла три вещи, две починил, одну зафиксировал):

1. **Transient-TTL вердикта** (D6) уже корректен: `rate_limited` кешируется
   `MCA_VISION_TRANSIENT_TTL_SECONDS` (default 90 с), успех его снимает,
   probe повторяется; breaker — 3 подряд → пауза 60 с (самовосстановление).
   Изменений не потребовалось. `Retry-After` провайдера недоступен
   контрактом транспорта (`transport(url, *, payload, headers, timeout) ->
   (status, body)` — заголовки не возвращаются), поэтому уважать его без
   смены контракта всех моков нельзя; вместо этого — bounded-окно и backoff
   (см. ниже). Честно: это осознанное ограничение, а не «прочитали Retry-After».
2. **Бюджет попыток заканчивался внутри 429-окна.** `JOB_MAX_ATTEMPTS=4` с
   backoff 30/60/120 с ≈ 4 мин, а лимит провайдера длился ~40 мин → актив
   оставался неразобранным навсегда. Теперь `_retry_allowed()`: пока джоба
   моложе `RATE_LIMIT_RETRY_WINDOW_SECONDS = 3600`, для
   `vision_rate_limited` повтор разрешён сверх бюджета попыток (частота
   ограничена `_backoff` ≤ `RETRY_MAX_SECONDS=900` + jitter); за окном —
   честный терминальный `failed` (дальше актив подхватывает backfill-путь).
   Для `vision_unavailable` и прочих причина — прежний бюджет (не менялся).
3. **Архивный путь «залипал навсегда».** У backfill-джобы детерминированный
   `job_id = vision:bf:{asset_id}`, а `mark_running` берёт только `queued`:
   после первой transient-неудачи строка терминальна и sweep её больше
   никогда не берёт (кандидат при этом остаётся навсегда). Теперь
   `_backfill_job_ready()`: `queued` и `next_retry_at` истёк (retry-долг
   уважается — раньше sweep игнорировал backoff и бил по провайдеру сразу),
   либо терминальная transient-неудача (`vision_rate_limited` /
   `vision_unavailable` / `worker_lost`) старше
   `BACKFILL_REARM_COOLDOWN_SECONDS = 900` → `store.requeue()` (существующий
   API mca-01, без новых методов). Постоянные причины
   (`vision_missing_source`, `vision_unreadable`, …) НЕ переставляются.
4. **Сопряжённый дефект, без которого 429 всё равно «залипал»:**
   `finish_media_analysis` завершает строку CAS-бампом `revision = revision+1`,
   а повтор той же гранулы вставлял `revision=1` → при завершении
   `UNIQUE constraint failed: mca_media_analyses.(asset, scope, schema,
   config_revision, quality_profile, revision)`; живая джоба оставалась
   `running`, актив не распознавался (в RED это воспроизведено:
   `IntegrityError` в `test_fix2_rate_limited_live_retry_succeeds_after_limit`).
   Теперь `process_asset_job` берёт свободный `revision` гранулы
   (`_next_granule_revision` = max+1; нет строк → 1 — прежнее поведение
   первой попытки). Это и делает самовосстановление реальным, а не
   формальным.

**Тесты:** `test_fix2_rate_limited_retries_within_window_then_terminal`,
`test_fix2_rate_limited_live_retry_succeeds_after_limit`,
`test_fix2_backfill_rearms_transient_terminal_job` (retry-долг уважается →
cooldown не даёт шторма → после снятия лимита актив реально `ready` →
идемпотентный пропуск готового).

## 5. Остатки/риски (честно)

- **Живое `SKIPS=0` и per-chat state на проде — проверка повторной приёмки**
  (прод/SSH из этой полосы не трогаются). Ожидание: в журнале нет
  `maximum number of running instances`, при занятой БД видна строка
  `claim sweep slow`/`maintenance stage timeout`, а `/api/vision/state`
  с `X-Chat-Id` чата показывает `requested=true` и причину capability-лимита
  (не `vision_disabled`).
- Уборка теперь раз в 30 с (было 5 с): deferred-TTL и `recover_stale`
  измеряются минутами/часами, семантика не меняется; при желании каденс —
  одна константа `VISION_MAINTENANCE_SECONDS`.
- `Retry-After` по-прежнему не читается (контракт транспорта без заголовков);
  поведение ограничено окном+backoff. Если провайдер даёт очень короткие
  лимиты, это может стоить нескольких лишних вызовов — осознанный компромисс.
- Бюджет попыток живой джобы теперь зависит от ВОЗРАСТА (1 ч) для
  `vision_rate_limited`: при постоянно залимитированном провайдере — до
  ~4 доп. вызовов на актив (≤15 мин интервал), дальше терминал + backfill.
- Pre-existing (не FIX2): pin-тесты `ROUTES_SHA256_F11` переутверждены
  осознанно (Δ routes = 0: тот же эндпоинт, опциональный контекст чата);
  `test_write_points_go_through_single_writer` и
  `test_env_off_beats_product_toggle` (в совместном прогоне) падают и на
  чистом HEAD — см. `hashes-and-commands-2026-10-19.md`.
