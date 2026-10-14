# F6 — Initiative v2: producer → intent → due decision → L2 Writer → SendRecheck → send

Baseline: `master @ 0c4f3a5` → в процессе работы HEAD сместился на `7fdeaaf`
(коммит параллельного лейна F1; файлы F6 с F1 не пересекаются). Автор: Builder F6.
Статус: код + тесты в рабочем дереве (НЕ закоммичено — коммит после Reviewer).
Все тесты F6 + смежные наборы зелёные (см. §7). Коммит — после независимого
ревью (правило лейна).

---

## 0. REV-F6 fixes (second round)

### F1 (High) — producer не срабатывает на ходе с отправленным error/no-key reply
* **Finding:** три точки текстовой отправки `_handle_turn` не помечали
  `_mark_turn_text_replied`: sandbox-фраза `content.no_key_reply`
  (NoApiKeyForChat), `CHAT_ERROR_PHRASES` в `except LLMError` и в
  `except Exception` → при лежащем LLM/отсутствии ключа каждый уникальный
  вопрос порождал durable follow_up → defer → writer_failed → abandoned
  (загрязнение funnel-evidence, §28.16).
* **Fix:** `self._mark_turn_text_replied(chat_id)` после каждой из трёх
  `_reply(...)` — `services/direct_chat_service.py` (NoApiKeyForChat-ветка,
  `except LLMError`, `except Exception`).
* **Тесты (wrapper-уровень, полный `service.handle` — дыра прошла потому,
  что прежние 20 тестов звали producer напрямую):**
  * `test_wrapper_error_phrase_reply_is_not_unanswered_question` — ход с '?'
    + LLMError → error-фраза отправлена, intent НЕ создан (0 активных,
    0 intent_created);
  * `test_wrapper_silent_turn_with_question_creates_intent` — ход с '?'
    без текстового reply (пустой ответ → 🗿-молчание, send_message=0) →
    intent создан (origin=unanswered_question, цель = вопрос).

### F2 (Medium) — `state_label` не обещает «работает» без живого heartbeat
* **Finding:** первая ветка формулы срабатывала при `created==0 and not
  producers_24h` без проверки `heartbeat_last_tick` → после рестарта/при
  выключенном воркере пользователь видел «Heartbeat работает…» — ложь
  (payload честен, метка нет).
* **Fix:** `services/status_service.py` — новая первая ветка
  `last_tick.get("ts") is None` → «Heartbeat ещё не запускался — тика
  инициативы не было» + `top_block_reason="heartbeat_not_run"`; ветка
  «producers=0» теперь достижима только при живом heartbeat.
* **Тест:** `test_i8_heartbeat_not_run_label_is_honest` — ts=None +
  created=0 → метка без слова «работает», содержит «ещё не запускался»,
  top_block_reason=heartbeat_not_run.

Recheck после фиксов: F6-набор 23 passed; status/maintenance/mca09 —
120 passed; direct_chat/handlers/concurrency/L1/epic72 — 279 passed,
1 failed (известный pre-existing concurrency, stash-верифицирован).

---

## 1. Что закрыто (кратко)

* **Producers (детерминированные, LLM в DB не пишет):**
  * `unanswered_question` — конец Direct-хода: сообщение с '?' (URL/команды
    отфильтрованы) и бот не отправил текстовый reply в этом ходе →
    `follow_up` / `unanswered_question` (durable, `time_due` +15 мин, TTL 3
    дня). Реализован как invoke-scoped обёртка `DirectChatService.handle` →
    `_handle_turn` + contextvar-маркер текстовых отправок хода.
  * `explicit_request` — allowlisted-поле `future_intent` в схеме L1
    (`direct_l1.FutureIntent`, kind ∈ {follow_up, open_dispute}, цель ≤200).
    Парсер валидирует схему; intent пишет СЕРВИС (`_f6_create_future_intent`)
    после `_plan_direct_l1` — при любом исходе хода (reply/react/silent).
    Канон промпта L1 бампнут по правилу «правка канона = бамп + слепок»:
    прежняя база заморожена в `PREV_DIRECT_L1_PLANNER_BASE` (ступень миграции
    ведёт прод-ключи на новый канон; тест `test_prev_snapshots_differ_from_new`
    зелёный).
  * **search_result — НЕ реализован (осознанно, см. §6 расхождения):**
    детерминированной точки «async search/tool job завершён с результатом,
    не потреблённым ответом» в пределах write-scope нет; тул-луп Direct
    синхронен (результат потребляется ответом в том же ходе), а внешние
    async-джобы (youtube/cover) — чужие DO_NOT_TOUCH-слои со своими
    reply-путями. Спекулятивная привязка = спам intent'ов (запрещено §13.1).
    Код origin `search_result` и триггер `search_completed` в схеме готовы —
    продюсер привязывается одним вызовом, когда появится событие-владелец.
  * `unfinished_topic`/`answer_extension` — не делались (§6.1: нет
    детерминированного сигнала).
* **Guard-ы:** дедуп по (chat, kind, subject-content) — существующий UNIQUE
  `dedup_key` (subject = `q:<sha1(нормализованный текст)>` — повторный тот же
  вопрос сливается, не спамит; окно = жизнь live-intent + TTL); кап pending на
  чат — существующий `limits.intent_candidates_max` (новых порогов нет,
  §28.16 соблюдён — ничего не ослаблено).
* **Consumer (§13.2):** due candidate → свежая ситуация (`build_initiative_
  situation` — direct_pending/bot_replied_recently/topic_open считаются из
  реального чата, не дефолты) → детерминированный гейт `decide_initiative`
  (уместность, без изменений) → **решение существующей L1-моделью**
  (`DirectChatService.plan_initiative_decision`: тот же `_l1.build_l1_context`
  + `llm.generate(step="l1_planner")` + `parse_l1_plan`; outage/невалид →
  SILENT, без repair-лестницы — инициатива вторична) → REPLY ⇒ генерация
  **существующим Direct L2 Writer** (`DirectChatService.
  generate_initiative_reply` → `_l2_write_answer`, step="l2_writer",
  Вербализатор-канал) → существующий SendRecheck → существующие chunks/
  mark_attempt/ledger (`telegram_send.send_text`, третий Writer не создан).
  Неспособность сгенерировать → `IntentService.note_writer_failure`:
  attempts+1 за РЕАЛЬНУЮ попытку генерации, cap `MCA_INTENT_MAX_ATTEMPTS` →
  терминальное `abandoned` (причина `writer_failed`). **Бесконечного
  candidate_ready нет** (§28.15). Защита `chain_allowed` не тронута.
* **Freshness recheck (§18D):** `build_fresh_recheck_context` строит
  RecheckContext из реального чата (см. матрицу §4) перед решением
  (pre-decision в heartbeat + в handle_initiative) и непосредственно перед
  send. Смена контекста между решением и отправкой → ровно одна переоценка
  (повторное L1-решение + генерация), вторая смена → `recheck_deferred`.
  Новое поле `RecheckContext.direct_request_pending` + ветка в
  `SendRecheck.check` (defer, не close — инициатива не соревнуется с прямым
  обращением, §18D-4). `chain_allowed`/порядок прочих проверок не менялись.
* **Funnel-статус (§13.3/I8/I9):** `intent_snapshot` получил аддитивный
  `module.funnel` (producers_24h по origins — из `stage` события
  `intent_created`; intents_created_24h; due; decisions_24h;
  writer_generated_24h; recheck_passed_24h; sent_24h — по ledger
  `output_kind='initiative_reply'`; heartbeat_last_tick — честный in-memory
  штамп тика) + `state_label` (человеческая диагностическая формула вместо
  «не запускалось») + `top_block_reason`. Названия существующих ключей и
  enum `state` НЕ менялись (аддитивно; рендер — за UI-лецом, см. §6).
* **Funnel-события (R17-safe):** `initiative_writer_generated`,
  `initiative_recheck_passed`, `initiative_sent` (новые имена через
  существующий `_emit`/`emit_mca_event`), origin в `stage` события
  `intent_created`, +5 кодов в закрытый словарь `REASON_CODES`
  (writer_failed, direct_pending, recheck_passed, writer_generated,
  initiative_sent; пин 280→285 обновлён — расширение §17.2 разрешено).

## 2. Producers-карта (точные привязки)

| producer | файл:точка | событие | kind/origin | guard'ы |
|---|---|---|---|---|
| unanswered_question | `services/direct_chat_service.py::DirectChatService.handle` (обёртка; маркер `_mark_turn_text_replied` в 4 точках текстовой отправки `_handle_turn`: фразы throttle/CB/lock + доставленный ответ) | конец хода: `'?' в тексте` (URL вырезаны, команды пропущены) AND нет текстовой отправки хода | follow_up / unanswered_question | dedup по q-hash; кап `intent_candidates_max`; time_due+900s; TTL 3д; K1-гейт |
| explicit_request (future intent) | `direct_chat_service._f6_create_future_intent`, вызов после `_plan_direct_l1` в `_handle_turn`; схема — `direct_l1.normalize_l1_plan` (`future_intent`) | L1 вернул валидный allowlisted future_intent | follow_up\|open_dispute / explicit_request | dedup по q-hash цели; кап; time_due+900s; TTL 3д; создание — только сервисом |
| search_result | — (не привязан, см. §6) | — | topic_interest / search_result | схема готова |

LLM-письмо в DB отсутствует: LLM отдаёт только закрытый enum + короткую цель
в JSON-плане; durable-запись делает `IntentService.create_intent`
(канонизация `canon_text`, R17 ≤200).

## 3. Consumer-путь (heartbeat → send)

```text
memory_maintenance._tick_intent_heartbeat (300s, K1/K2)
  → IntentService.heartbeat_tick (due-скан SQL + гигиена)
  → на каждого due-кандидата (_run_initiative_candidate):
      row fresh fetch; terminal → skip
      build_fresh_recheck_context (§18D pre-decision):
        answered → close(fulfilled, already_answered), без LLM
      worker_budget.consume(llm_calls, global+chat) — существующий F-10
        бюджет; исчерпан → кандидат остаётся due без решения
      build_initiative_situation (реальные флаги из чата)
      handle_initiative(writer_service=handlers.direct_chat._service):
        decide_initiative (дет. гейт) → silent → defer(backoff) [не re-decide каждые 300с]
        L1-модель: plan_initiative_decision (1 call, parse; None → SILENT+defer)
        REPLY → generate_initiative_reply (существующий _l2_write_answer)
          пусто → note_writer_failure: attempts+1; cap → abandoned(writer_failed)
        SendRecheck по СВЕЖИМ условиям (§18D):
          proceed → chunks → send_text → mark_attempt → ledger(initiative_reply)
                    → события writer_generated/recheck_passed/sent
          already_answered → A15 close(fulfilled)
          direct_pending → defer (не соревнуется)
          смена context_version → ровно 1 переоценка; вторая → recheck_deferred
```

Direct-модуль не поднят (`_service is None`) → честный WARN, кандидаты не
решаются (никакого candidate_ready-вранья; intent ограничен TTL/гигиеной).

## 4. Freshness-матрица (§18D)

| Требование | Источник правды | Реакция |
|---|---|---|
| другой пользователь уже ответил/закрыл вопрос | `mca_bot_outputs`: доставленный bot-выход с `sent_at > intent.created_at` (бот ответил после вопроса — разговор ушёл вперёд) | decision-time: close(fulfilled, already_answered); send-time: A15 close (без отправки) |
| та же ли reply-ветка | chat-level intent не фиксирует ветку (ΔDDL=0); смена контекста покрывается fingerprint: `_f6_context_version(chat, created_at, новые human-сообщения окна, bot-выходы)`; активность в ветке бота (reply на bot-сообщение) → direct_pending | смена версии: 1× re-evaluate (L1+генерация заново), 2-я смена → recheck_deferred |
| адресат ещё осмыслен | новое human-сообщение после created_at, адресованное боту (reply на bot-tg-id / `@username` / бот-слово `_BOTWORD_RE`) | direct_request_pending → defer (decision-time: cancel+defer, без LLM) |
| intent не отменён/superseded | fresh fetch `mca_intents` перед решением и перед send (`SendRecheck.check`: terminal/merged → intent_closed) | cancel без отправки |
| прямое обращение к боту | см. выше | defer — инициатива не гонится наперегонки (§18D-4) |
| context/version fingerprint | `_f6_context_version` (R17: числа/ID) vs `last_evaluated_context_version` intent-строки | recheck_again → re-evaluate → defer |
| quiet/cooldown policy | `bot_replies.last_used_at` окно (существующий `_bot_replied_recently`-сигнал в situation), worker-budget | silent/defer |

Ни одно поле не осталось «дефолтным false»: уже_answered/direct_pending/
context_version вычисляются SQL-запросами в durable-состояние; `same_branch_
replies`/`parent_changed` осознанно False с документированной причиной
(chat-level intent без ветки-рефа; покрытие — fingerprint + direct_pending).

## 5. Funnel-поля Status (`intent_snapshot`)

`module.funnel`: `producers_24h{origin: n}` (mca_events `intent_created`,
origin в `stage`), `intents_created_24h`, `due` (mca_intents), `decisions_24h`
/`writer_generated_24h`/`recheck_passed_24h`/`sent_24h` (mca_events; sent —
дополнительно ledger `output_kind='initiative_reply'`), `heartbeat_last_tick`
(in-memory штамп `_heartbeat_last_tick` тика; durable-событие на каждый тик —
спам, не эмитится). `module.state_label` — 4 диагностических состояния +
рабочее: producers=0 → «Heartbeat работает, но producers за 24ч не создали
ни одного намерения»; created>0, decisions=0 → причина последнего скипа;
decisions>0, writer=0 → «генерации нет»; writer>0, sent=0 → «отправка не
проходит (причина)»; sent>0 → «отправлено N за 24ч». `top_block_reason` —
машинный код останова. Останов на freshness recheck виден через
`last_skip.reason_code` (already_answered/direct_pending/stale_context/
recheck_deferred/writer_failed).

## 6. Расхождения с брифом/архитектурой (осознанные, минимально-рискованные)

1. **search_result producer не привязан** — нет детерминированного события-
   владельца в write-scope (см. §1). Не выдумывал сигнал (запрет спама).
2. **`writer_failed` — не новый статус**, а терминальное `abandoned` с
   reason_code `writer_failed`: CHECK-контракт `mca_intents.status` (v29)
   закрытый, ΔDDL=0 (архитектура §0). Семантика «честное закрытие без
   результата» совпадает; funnel различает по reason_code.
3. **UI-рендер `state_label`/funnel — за пределами F6** (web/app.js,
   web/index.html — DO_NOT_TOUCH, параллельный лейн REV-F1). Backend-контракт
   готов и аддитивен; I8 выполнен на уровне payload (проверяется тестом
   `test_i8_*`); подключение рендера — UI-лейн (F7/F10 reconcile).
4. **REACT в инициативе демотируется в SILENT** (reason `l1_react`/
   `delivery_not_text`): у инициативного хода нет сообщения-цели для
   реакции (`react_moai` требует target message_id); честное молчание +
   defer вместо псевдо-реакции. Третьего транспортного пути не создавал.
5. **L1-решение инициативы без repair-лестницы** (1 вызов, невалид → SILENT):
   repair-ladder `_plan_direct_l1` привязан к `message`-объекту входящего
   хода; инициативный контур решает одну бинарную задачу (уместно/нет) —
   bounded-повтор не нужен, outage → defer+backoff (следующий тик повторит).
6. **Учёт расхода LLM** — `worker_budget.consume("llm_calls")` (global+chat)
   на кандидата + durable usage-строки `llm_usage_events` (step=l1_planner/
   l2_writer дают реальные токены). В воркер-приоритет деградации F-10
   `initiative` НЕ добавлялся (чужой закрытый WORKER_IDS; инициатива — самый
   опциональный воркер; degradation-матрица его не блокирует, consume-лимиты
   действуют).

## 7. Тесты

Новый: `tests/test_asap8_f6_initiative.py` — 23 теста (I1–I9 + §18D + дедуп/
кап/гейты producers + L1-allowlist + heartbeat-путь + 3 wrapper-уровневых из
REV-F6 fixes: error-фраза ≠ unanswered, silent-ход создаёт intent, честная
heartbeat_not_run-метка). TEST-LIFECYCLE: CONTRACT
owner=ASAP8/F6. Autouse-фикстура отключает mca-10b exploration-draw:
вероятностный выбор формы-кандидата делает счётчики решение/генерация
недетерминированными (сам 10b покрыт своими тестами; воспроизведённый флейк
зафиксирован и убран детерминизмом).

Обновлён пин: `tests/test_mca10b_random_applications_block_a_round1041.py`
(REASON_CODES 280→285, намеренно — расширение словаря §17.2).

Результаты (локально, py 3.12):

```text
tests/test_asap8_f6_initiative.py ................. 20 passed (×3 подряд)
mca09 blocks A/B/D/E + off_parity + 10b block_a .... 95 passed
tests/test_asap7_direct_l1.py + direct_chat + handlers
  + prompt_migrations + module_registry ............ 325 passed
decision_matrix + llm_decision + epic72_gates ....... 51 passed
mca13/agentic/mca17 events .......................... 97 passed
nostalgia (worker/layer_a/smoke) + status_* ....... 102 passed
test_memory_maintenance.py .......................... 13 passed
финальный контур F6 + intent + reason-pin наборы ... 152 passed
```

Полный `pytest tests/ -q`: 12900 passed / 49 failed — **все 49
классифицированы, F6-контур чист**:
* ~24 — семейство version-pin (APP_VERSION 2.58.75 от коммита F1 7fdeaaf
  против пинов 2.58.74; другой лейн уже обновляет эти пины в worktree);
* ~7 — routes-hash пины (web/api/routes.py правят параллельные лейны);
* 4 — пины счётчика REASON_CODES 280 (mca19_block_f, mca20_integration,
  mca20_rework1) — **моё санкционированное расширение** 280→285, пины
  обновлены в этом лейне (mca17c-пин до 285 уже поднял параллельный лейн);
* 1 — test_direct_chat_concurrency::test_third_handle_waits_for_slot_at_n2
  (stash-проба: падает без изменений F6);
* остальные (outgoing_guard ×2, summary ×4, tool_coordinator/tool_loop,
  kill-switch пины, blockE-бейслайны, cover routes-hash) — stash-проба на
  моём поднаборе: падают без изменений F6 (in-flight правки параллельных
  лейнов F2/F9/deploy в общем worktree).

Важно о параллельности: worktree общий и активно меняется соседними лейнами
(F2 summary_execution_input, F9 youtube proxy, deploy-пины) — счёт фейлов
полного прогона плавает (44→49 между прогонами) без изменений F6.

## 8. Изменённые файлы

```text
services/direct_chat_service.py  (+735: producers, writer/L1-методы сервиса,
                                  handle-обёртка, handle_initiative v2,
                                  freshness-слой, funnel-события)
services/mca_intents.py          (+84: note_writer_failure, direct_pending,
                                  3 funnel-события, origin в intent_created)
services/memory_maintenance.py   (+~90: heartbeat с генерацией, budget,
                                  _heartbeat_last_tick, DI-singleton)
services/status_service.py       (+87: funnel/state_label/top_block_reason)
services/direct_l1.py            (+31: FutureIntent + allowlist-парсинг)
services/chat_prompts.py         (+41/-нск: канон L1 + слепок R1028)
services/mca_events.py           (+4: +5 reason-кодов)
services/database.py             (+5: "initiative_reply" в BOT_OUTPUT_KINDS)
tests/test_asap8_f6_initiative.py (новый, 20 тестов)
tests/test_mca10b_...block_a....py  (пин 285)
tests/test_mca19_block_f_round1043.py (пин 285)
tests/test_mca20_integration_round1045.py (пин 285)
tests/test_mca20_rework1_f1_f2.py (пин 285)
```

## 9. Риски / оставшееся

* **R-F6-1 (live):** живой прогон initiative на проде — owner-gate DoD
  («live initiative works»); локально покрыто интеграционными тестами на
  реальной SQLite (producers→heartbeat→writer→send).
* **R-F6-2:** UI-рендер funnel/state_label не подключён (leich REV-F1);
  до подключения Status покажет старый рендер при новых данных (не врёт —
  старые ключи не менялись).
* **R-F6-3:** LLM-стоимость heartbeat ограничена (budget consume, ≤1
  кандидат/чат/тик, 1 L1-вызов + ≤2 генерации на кандидата), но реальный
  расход стоит понаблюдать по funnel после включения (§28.16: до
  funnel-evidence пороги не трогать).
* **Pre-existing (не моё, зафиксировано):** `_f6_chat_facts` опирается на
  `smart_messages.reply_to_id` = tg-id (живой ingestion); импортированные
  архивы с NULL reply сохраняют честный unknown (не ложный сигнал).
* **Incidental, unrelated/pre-existing (stash-проба на HEAD 7fdeaaf без
  изменений F6 — воспроизводятся):**
  1. `tests/test_decision_making_round1026.py::TestBounds::test_version_
     unchanged` — пин `APP_VERSION == "2.58.74"` против коммита F1
     (версия уже 2.58.75); пин обновляет deploy-лейн.
  2. `tests/test_direct_chat_concurrency.py::test_third_handle_waits_for_
     slot_at_n2` — `llm.call_count == 9 != 3` (L1-стадии дают 3 вызова/ход
     на фейковом не-JSON LLM); падает без моих изменений.
* **Incidental, fixed в своём контуре:** `initiative_reply` отсутствовал в
  `BOT_OUTPUT_KINDS` → ledger молча коэрсил в `other` и funnel `sent` был
  неизмерим (kind добавлен).
