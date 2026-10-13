# C06A — Initiative heartbeat observable (v6, Wave B, P0) — отчёт

Лейн: C06A. HEAD базы `6230fde`. Симптом владельца: «Initiative ON часами, Status: не
запускалось». RCA: `rca-c06a-initiative.md` (R1 — hot-ON не запускал heartbeat; R3 —
liveness in-memory; A3 — funnel не подключён к UI). Пороги инициативы не тронуты;
producer'ы F6 не изменялись (`tests/test_asap8_f6_initiative.py` — 23/23 зелёные).

## 1. Что сделано

### 1.1 Hot-toggle симметричен (R1) — `services/memory_maintenance.py`
- Джоба `intent_heartbeat_tick` теперь регистрируется в `start()` ВСЕГДА (прецедент
  `embed_recovery`), а гейт K1/K2 читается тиком на каждом заходе через
  `mca_intents.heartbeat_tick()` (уже было: инертен при OFF, 0 SQL).
- Семантика toggle: OFF-hot останавливает работу тика, ON-hot запускает ≤300 с,
  рестарт не нужен. Прежняя асимметрия («OFF-hot эффективен, ON — только после
  рестарта») устранена.
- `_intent_heartbeat_tick_enabled()` сохранена (контракт/тесты mca-09), больше не
  управляет регистрацией — docstring обновлён.
- Стартовый лог теперь перечисляет heartbeat: `MemoryMaintenance started (…
  intent_hb=300s[always-on])` (закрывает пробл. наблюдаемости §4-шаг2 RCA).

### 1.2 Liveness персистентен (R3) — `services/memory_maintenance.py`
- `_heartbeat_last_tick` = {ts, due, enabled} — кэш-вид durable-штампа.
- Durable-носитель: СУЩЕСТВУЮЩАЯ таблица `task_jobs` (v14), ОДНА строка с фиксированным
  `job_id='intent_heartbeat_liveness'`, `status='completed'` (терминальный — супервайзер
  не подбирает), `heartbeat_at` = ts последнего тика, payload = {due, enabled}. UPSERT
  по PK через `write_transaction` (mca-01). Новой таблицы/миграции нет; per-intent
  task_jobs по-прежнему не создаются (тест mca-09 обновлён: разрешён ровно этот job_id).
- `start()` гидрирует штамп из БД (fail-open, startup-task) → после рестарта Status
  больше не врёт «тик ещё не был» до первого тика.
- Новое `intent_heartbeat_job_info()` — {registered, next_tick} из ЖИВОГО планировщика;
  `shutdown()` очищает ссылку на активный сервис.
- Наблюдаемость тика: при enabled тик пишет INFO на КАЖДЫЙ заход
  («[mca09] intent heartbeat tick ran | due=…», включая пустой due=0) — «мёртвый» vs
  «праздный» различимы в журнале; гейт OFF → DEBUG (без спама).

### 1.3 Funnel → UI (A3) — `services/status_service.py`, `web/app.js`, `web/index.html`
- `intent_snapshot().heartbeat` дополнен (аддитивно): `registered`, `next_tick`,
  `last_tick` {ts, due, enabled}.
- Диагностическая формула: добавлено 4-е честное состояние `heartbeat_disabled`
  («Heartbeat выключен — гейт K1/K2 OFF, тики остановлены») — различает «тик проходит,
  но гейт OFF» от «работает». Существующие ветки (heartbeat_not_run / producers /
  no_decision / no_writer / recheck_blocked / sent) не тронуты (контракт REV-F6 F2).
- `app.js intentModuleStatus()`: + stateLabel, topBlockReason, funnel, heartbeat-факты
  (registered/nextTick/lastTick); + хелперы `topBlockLabel` (человекочитаемый блокер) и
  `funnelProducersLabel` (origin: N).
- Карточка `mod_initiative` (index.html): строка «Heartbeat: …» заменена раздельными
  фактами — гейт (hot) / джоба зарегистрирована / последний тик (durable) / следующий
  тик. Ложное «тик активен» по голому гейту больше не показывается (R1-симптом).
  Добавлены: строка state_label + блокер, лента воронки 24ч (Продюсеры по origin,
  Создано, Due, Решений, Writer, Recheck, Отправлено).
- Блок «Инициатива» на Статусе: legacy «Намерений пока нет — не запускалась» заменён
  funnel-диагностикой (state_label + блокер + воронка + heartbeat-факты), голый текст
  остаётся только как fallback при отсутствии module-блока. Компактный бейдж состояния
  сохранён. При state=ok рендер блока не изменён (замороженный контракт mca-12).

### 1.4 search_result producer — НЕ создан
По контракту v6: продюсера нет — счётчик честно пуст; придумывать ради числа запрещено
(f6-report §6.1 фиксирует привязку как отдельную работу).

## 2. Тесты

Новые (`TEST-LIFECYCLE` указан в шапках):
- `tests/test_asap8_v6_c06a_heartbeat.py` (REGRESSION, owner=ASAP8-v6/C06A):
  1) старт с гейтом OFF → джоба зарегистрирована; hot-ON без рестарта → тик отработал
  (штамп ts/enabled/due, due-скан нашёл намерение); 2) hot-OFF → работа остановлена,
  штамп enabled=False, INFO «tick ran» нет; 3) рестарт → durable-штамп гидрируется
  (ts совпадает), джоба перерегистрирована, registered=True; 4) пустой тик пишет INFO
  «tick ran … due=0» и пишет durable-строку.
- `tests/test_asap8_v6_c06a_status_ui.py` (CONTRACT, payload→UI mapping): payload
  содержит все поля, которые читает app.js (heartbeat.registered/next_tick/last_tick,
  funnel.*, state_label, top_block_reason); 4 состояния: ts=None → heartbeat_not_run
  («ещё не запускался», не «работает»), enabled=False → heartbeat_disabled,
  producers=0 → диагноз «producers» виден, норма (полная цепочка decided→writer→
  recheck→sent) → «Инициатива работает: отправлено N за 24ч».

Обновлён существующий: `tests/test_mca09_intents_block_b_round1040.py` — ассерт
«task_jobs без intent-строк» уточнён: per-intent строк по-прежнему 0, плюс ровно одна
сервисная liveness-строка (обоснование в §1.2; контракт mca-09 «per-intent task_jobs
нет» защищён точнее, чем раньше).

## 3. Прогон

```
pytest tests/test_asap8_v6_c06a_heartbeat.py tests/test_asap8_v6_c06a_status_ui.py
       tests/test_asap8_f6_initiative.py tests/test_memory_maintenance.py
       tests/test_status_service.py tests/test_mca09_intents_block_b_round1040.py
       tests/test_mca09_intents_block_e_round1040.py tests/test_asap7_module_registry.py
       tests/test_asap8_f8_embeddings.py -q
→ 137 passed
node --check web/app.js → OK
```
`tests/test_asap8_f6_initiative.py` — 23/23 (не ослабляли, не правили). «22 leaked
aiosqlite» — преждебазовый шум (воспроизводится на HEAD без моих правок).

## 4. UI-проверки (Playwright + Browser Use, реальные web/index.html+app.js)

Харнесс (scratch, не в репо): реальный UI + FakeConn-ConfigCache (прецедент
tools/ui_audit_round1021.py), /api/status — стаб с двумя сценариями:
A «норма» (полная воронка) и B = симптом владельца (state=not_run, ts=None,
heartbeat_not_run).

Playwright (детерминированно):
- Desktop 1280, карточка Модули→Инициатива (A): гейт/джоба/последний тик/следующий тик,
  state_label, 7 бейджей воронки, pending/ближайшая проверка, последнее решение/пропуск —
  все значения из payload отрисованы.
- Desktop 1280, Статус (B): бейдж «не запускалось» + диагноз «Heartbeat ещё не
  запускался … · блокер: heartbeat ещё ни разу не тикал» + воронка нулей + «Heartbeat:
  гейт включён · джоба зарегистрирована · тиков ещё не было».
- Mobile 390: горизонтального оверфлоу нет (hOverflow=0), воронка переносится (7
  бейджей), диагноз B видим.
- pageerror/JS-исключений: 0. Консоль: только стендовые 503 `/api/memory/*` (нет бот-БД
  за харнессом; поллеры памяти, обрабатываются UI как «нет данных») — среда, не код.

Browser Use (реальный Chrome, скриншоты в scratch):
`c06a_card_desktop_A.png`, `c06a_card_mobile_A.png`, `c06a_status_desktop_B_notrun.png`,
`c06a_status_mobile_B_notrun.png`, `c06a_status_desktop_A_ok.png`.
Инспекция подтвердила рендер; Visual Neighborhood Sweep: новых дефектов вокруг карточки
нет. Замечание среды (не дефект продукта): в харнессе тумблер модуля показывает
«Выключен», т.к. ui_audit-фикстура сеет все bool-параметры False; в проде тумблер
отражает реальный конфиг.

## 5. Controlled production observation (после деплоя — доказательство работы)

Шаг 0. Рестарт с новым кодом. В логе старта: `MemoryMaintenance started (…
intent_hb=300s[always-on])` — джоба зарегистрирована независимо от гейта на момент
старта (раньше регистрации в строке могло не быть).

Шаг 1. Факт тиков (дёшево, без UI): лог — каждые ≤300 с INFO
`[mca09] intent heartbeat tick ran | due=0 expired=0 archived=0` даже при пустом
результате. Тишина этих строк ≥300 с = тик действительно мёртв (раньше тишина была
неинтерпретируема).

Шаг 2. /api/status → `intents.module`:
- `heartbeat.enabled` (живой гейт) отдельно от `heartbeat.registered` (джоба в
  планировщике) и `heartbeat.next_tick` (next_run_time — если NULL при
  registered=false, сервис обслуживания не поднят);
- `heartbeat.last_tick` {ts, due, enabled} — переживает рестарт (проверка: ts в
  Status сразу после рестарта совпадает с до-рестартным);
- `state_label` + `top_block_reason` + `funnel.*` — стадия останова видна без SQL.
Ожидаемый исход по R1: после hot-включения тумблера ≤300 с появляется первый
«tick ran» и `last_tick.ts` оживает — без рестарта.

Шаг 3. Durable-штамп (SQL, опционально):
`SELECT heartbeat_at, payload FROM task_jobs WHERE job_id='intent_heartbeat_liveness';`
— одна строка, обновляется каждым тиком.

Шаг 4. Воронка/застревания (как в RCA §4): `mca_events` (intent_created по origin,
initiative_*), `SELECT status, COUNT(*) FROM mca_intents WHERE chat_id=… GROUP BY
status` — pending+deferred>0 при decisions_24h=0 → стадия решения (K3/budget/service
None); UI теперь показывает тот же диагноз через top_block_reason/last_skip.

Критерий доказательства (без ослабления порогов): связка `intent_created → … →
initiative_sent` на живом чате + `sent_24h>0` и state_label «Инициатива работает:
отправлено N за 24ч». Любой ноль = конкретная стадия с reason_code в UI.

## 6. Инцидентальные находки

- `related-nonblocking`: status `state=not_run` считает события «ever», funnel — 24ч
  (R5 RCA): остаётся, UX-неоднозначность смягчена диагностикой, семантика state не
  менялась (замороженный контракт mca-12).
- `related-nonblocking`: `web/api/analytics.py` usage_summary падает на None-row без
  guard (наблюдено только на FakeConn-стенде; в проде строка есть) — воспроизвести в
  проде маловероятно, но guard был бы дёшев (вне WRITE_SCOPE).
- `unrelated/pre-existing`: «22 leaked aiosqlite connections» при прогоне существующих
  сюит — воспроизводится на чистом HEAD.
- `uncertain`: семантика `state` (ever) vs funnel (24h) при тихом периоде — владельцу
  теперь виден top_block_reason, но решение «ok при старых событиях» остаётся за
  Architect (mca-12).

## 7. Файлы

- `services/memory_maintenance.py` — always-on регистрация, durable-штамп
  (persist/load/hydrate), intent_heartbeat_job_info, INFO на каждый тик.
- `services/status_service.py` — heartbeat.registered/next_tick/last_tick; ветка
  heartbeat_disabled.
- `web/app.js` — intentModuleStatus() + topBlockLabel + funnelProducersLabel.
- `web/index.html` — карточка mod_initiative (heartbeat-факты, state_label, воронка);
  Статус-блок not_run → funnel-диагностика.
- `tests/test_asap8_v6_c06a_heartbeat.py`, `tests/test_asap8_v6_c06a_status_ui.py` —
  новые; `tests/test_mca09_intents_block_b_round1040.py` — уточнение ассерта.
- Не коммитить (по брифу); R17 соблюдён (в коде/логах/тестах — id/коды/числа).

@Orchestrator — лейн C06A готов к строгому ревью.
