# RCA C06A — «Initiative ON часами, Status: не запускалось» (P0)

Лейн: V6-SCAN-A; HEAD `1e98027` (2.58.77); read-only. Симптом зафиксирован владельцем на проде.

## 1. Полная трасса контура на HEAD

```text
Producers (создание intent, только при Direct-ходах):
  direct_chat_service.handle (:1844) — обёртка над _handle_turn
    ├─ ход с '?' без текстового reply → _f6_maybe_create_unanswered_question (:7474)
    │    guard'ы: intents_enabled() на момент хода, dedup q-hash, cap intent_candidates_max, K1-гейт
    └─ L1 вернул future_intent → _f6_create_future_intent (:7512, после _plan_direct_l1, :2487)
  search_result — схема готова, продюсер НЕ привязан (f6-report §6.1 — осознанно)

Consumer (heartbeat):
  MemoryMaintenanceService.start() → регистрация джобы intent_heartbeat_tick (300с)
    ТОЛЬКО если intent_heartbeat_enabled() на момент старта (memory_maintenance.py:185-193)
  _tick_intent_heartbeat (:276-323)
    → mca_intents.heartbeat_tick (mca_intents.py:1296-1309: hygiene + due_candidates,
       due_rows SQL, ≤1 кандидат/чат/тик)
    → service = handlers.direct_chat._service (DI-singleton :45-53)
    → gates: self.bot is not None AND intent_decision_enabled() (K3)
    → _run_initiative_candidate (:325-381): fresh recheck (already_answered→close),
       worker_budget.consume(global+chat), situation, handle_initiative
  handle_initiative (direct_chat_service.py:7708+):
    decide_initiative (дет. гейт) → silent → defer+backoff, note_decision(outcome=silent)
    L1: plan_initiative_decision (:7331) → REPLY → generate_initiative_reply (:7384, L2 Writer)
    → SendRecheck (fresh) → chunks → send_text → mark_attempt → ledger(output_kind=initiative_reply)
    → события: initiative_decided / initiative_writer_generated / initiative_recheck_passed /
      initiative_sent; intents: pending→deferred→fulfilled/abandoned(writer_failed)/expired

Status (funnel):
  status_service.intent_snapshot (:738-954):
    state = "ok" if (active intents OR intent-события ever) else "not_run"  (:941)
    module.funnel: producers_24h / intents_created_24h / due / decisions_24h /
      writer_generated_24h / recheck_passed_24h / sent_24h / heartbeat_last_tick (in-memory!)
    module.state_label + top_block_reason (диагностическая формула F6, :906-936)

UI (проверено grep на HEAD):
  web/app.js:7216-7249 — рендерит ТОЛЬКО requested/effective/source/pending/next_due/
  heartbeat.{enabled,job,tick_seconds} и legacy state→intentsStateLabel (:7217:
  not_run→«не запускалось»).
  state_label / funnel / top_block_reason / producers_24h / heartbeat_last_tick —
  В UI НЕ УПОМИНАЮТСЯ НИ РАЗУ → f6-report R-F6-2 подтверждён на HEAD: funnel не подключён.
  index.html:426 — «Heartbeat: тик активен/выключен» из heartbeat.enabled (живой гейт),
  НЕ из факта тика.
```

## 2. Что буквально видит владелец

«не запускалось» = legacy `state=not_run` = у чата 0 активных intent'ов И 0 intent-событий
(status_service.py:941; запрос :802-808 берёт события БЕЗ ограничения по времени). Это диагноз
«продюсеры ни разу не создали намерение», а НЕ «heartbeat мёртв» — эти два отказа UI не различает:
heartbeat-строка показывает `enabled` (гейт), факт тика (`heartbeat_last_tick`) скрыт в funnel,
который не рендерится. Отсюда и противоречие симптома: «ON часами» (карточка: Работает + тик
активен) при «не запускалось» (счётчики нулевые, объяснение невидимо).

## 3. Конкретные точки отказа/застревания (файл:строка)

### R1 — Hot-включение инициативы НЕ запускает heartbeat (асимметрия toggle) — главный кандидат
- Джоба регистрируется один раз в `start()`: `if _intent_heartbeat_tick_enabled()`
  (memory_maintenance.py:185-193). Если при старте процесса `flags.initiative_enabled` /
  `flags.intent_heartbeat_enabled` / env K1/K2 были OFF — джобы нет.
- Владелец включает Initiative тумблером (hot) → UI сразу показывает «Работает» +
  «Heartbeat: тик активен» (status_service.py:762 берёт ЖИВЫЙ гейт; index.html:426-432 даже
  пишет «тумблер применяется сразу (hot)»), но планировщик джобу не знает ДО рестарта.
- Semantics asymmetric: OFF после старта — hot-эффективен (тик читает гейт на каждом заходе,
  mca_intents.py:1299-1300), ON после старта — НЕ эффективен до рестарта. Это класс «broken
  toggle» (тот же тип, что D08 Random).
- Совместимо с симптомом: после такого включения producers при Direct-ходах могли создавать
  intent'ы (create_intent гейтится intents_enabled() живым — mca_intents.py:992-995... проверка
  в create_intent → creation_allowed → intents_enabled), но due-скан не работает → intents
  висят pending → в 24ч funnel decisions=0. Однако тогда state='ok' (интенты есть). Симптом
  «не запускалось» (0 интентов) требует дополнительно, что интенты не создавались вовсе
  (см. R2/R3) либоowner смотрел до первых Direct-ходов.

### R2 — Producers требуют точных условий Direct-хода — легитимный «0», но невидимый
- unanswered_question создаётся только если: ход Direct (бот-слово/reply/mention), в сообщении
  есть '?' (URL/команды отфильтрованы), и бот НЕ отправил текстовый reply в ходе
  (direct_chat_service.py:1844-1938, 7 маркеров _mark_turn_text_replied).
- Если бот отвечает на всё — producers_24h пусто; future_intent зависит от L1-плана.
- state_label сказал бы ровно это («Heartbeat работает, но producers... не создали ни одного
  намерения», status_service.py:917-919) — но UI это не рендерит.

### R3 — `heartbeat_last_tick` in-memory (memory_maintenance.py:42)
- После каждого рестарта штамп `ts=None` до первого тика → funnel честно «Heartbeat ещё не
  запускался» (status_service.py:910-916) — но (а) не рендерится, (б) после рестарта врёт в
  обратную сторону недолго (до первого тика). Дуральное с R1: если джоба не зарегистрирована,
  ts=None навсегда — и это единственное место, где это видно.

### R4 — Молчаливые стопы середины воронки (застревание в deferred/pending)
- LLM outage → SILENT + defer+backoff (f6-report §6.5); K3 off → handle_initiative вернёт
  disabled (direct_chat_service.py:7728-7730), кандидаты копятся.
- worker_budget исчерпан → кандидат остаётся due без решения (memory_maintenance.py:360-371,
  INFO-лог только в лог).
- Direct-модуль не поднят (`_service is None`) → WARN и пропуск (memory_maintenance.py:308-312).
- Всё это отражено в funnel/last_skip/top_block_reason — снова невидимо в UI.

### R5 — Порог observable: `state` смотрит события ever, funnel — 24ч
- state=not_run снимается, если события были когда-либо; funnel считается за 24ч
  (status_service.py:860). После тихого периода оба показывают «пусто» — неоднозначность
  «не работает» vs «нечего делать» (v6: редкие сообщения могут быть нормой; невидимый pipeline — нет).

## 4. Чем доказать/опровергнуть работу на проде — controlled production observation (минимальный план)

Шаг 1. Факт тиков (дешево, без UI): снять `/api/status` (admin) → `intents.module`:
  - `heartbeat.enabled` (гейт) vs `funnel.heartbeat_last_tick` (факт):
    enabled=true + heartbeat_last_tick=null → **R1 подтверждён** (джоба не зарегистрирована).
  - state_label/top_block_reason — диагностическая формула (если R1 — будет «ещё не запускался»).
Шаг 2. task/scheduler: в логах старта `MemoryMaintenance started (...)` перечисляет merge/review/
  wal/embed — регистрации intent-джобы там НЕТ в строке; проверить наличие джобы можно косвенно
  через 300-секундные INFO `[mca09] intent heartbeat | due=... expired=...` (пишется только при
  due/expired/archived>0, memory_maintenance.py:294-299) — тишина в логах ≠ отсутствие тика
  (недостаток наблюдаемости, чинить в фиксе).
Шаг 3. Продусеры: `SELECT ts, stage, reason_code FROM mca_events WHERE chat_id=<чат владельца>
  AND event_name='intent_created' ORDER BY ts DESC LIMIT 20;` — если пусто при активных Direct-
  ходах с '?', проверить, отправлял ли бот текстовые replies в те же ходы (R2), и был ли
  intents_enabled в те моменты (тумблер/env K1).
Шаг 4. Воронка за 24ч: счётчики funnel из /api/status + SQL:
  `SELECT status, COUNT(*) FROM mca_intents WHERE chat_id=... GROUP BY status;`
  pending+deferred>0 при decisions_24h=0 → застревание до решения (R4: K3/budget/service None).
  decisions>0, writer=0 → L1 всегда SILENT; writer>0, sent=0 → SendRecheck/transport.
Шаг 5. Свежий E2E-проб (если R1 исключён): в controlled-чате задать вопрос боту без получения
  ответа → intent_created в течение хода; ждать ≤300с тик → initiative_decided (+possible send);
  сравнить таймлайны mca_events. Порог/пороги НЕ ослаблять (v6 §C06A).

Критерий: работа доказана связкой `intent_created → ... → initiative_sent` на живом чате +
`sent_24h>0` и state_label «Инициатива работает: отправлено N за 24ч» (в payload). Любой ноль на
стадии = конкретная стадия с reason_code — это и есть требование v6 «отсутствие запуска =
конкретная стадия».

## 5. Что из funnel не доведено до UI (точный перечень остатка)

1. `module.state_label` — диагностическая формула (5 состояний) — не рендерится.
2. `module.top_block_reason` — машинный код останова — не рендерится.
3. `module.funnel.*` — producers_24h{origin}, intents_created_24h, due, decisions_24h,
   writer_generated_24h, recheck_passed_24h, sent_24h — не рендерятся.
4. `funnel.heartbeat_last_tick` — единственный liveness-факт — не рендерится; UI показывает
   конфигурационный heartbeat.enabled, создавая ложное «тик активен».
5. Различение effective/master есть (registry gate), различение «registered job vs живой тик» — нет.
6. Legacy `state=not_run` маппится в «не запускалось» без объяснения — именно эту строку видит
   владелец (app.js:7217).

## 6. Остаточные действия (не кодить в этой фазе)

- A1 (evidence): выполнить §4 шаги 1-4 на проде — установить фактическую стадию останова
  (ожидаемый исход: R1, т.к. рестарты деплоя регулярно пересоздают процесс, а владелец включал
  тумблер hot; проверить также env MCA_INTENTS_ENABLED/MCA_INTENT_HEARTBEAT_ENABLED в прод-env).
- A2 (design, Architect): семантика включения heartbeat — либо re-registration hot-тоггла
  (scheduler add_job по конфигу), либо честный `restart_required` в UI для heartbeat-оси;
  синхронизировать с D08 broken-toggle подходом. Плюс durable-штамп тика (вместо in-memory),
  если观测-требования D12 потребуют истории.
- A3 (UI slice): подключить funnel/state_label/top_block_reason/heartbeat_last_tick к карточке
  Initiative и Status-блоку (данные уже в payload, аддитивно; совместимо с D12).
- A4: fake-clock E2E для сценария «hot-ON после старта без рестарта» — сейчас такого теста нет
  (обнаруженный тестовый разрыв).
