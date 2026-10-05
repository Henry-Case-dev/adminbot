# MCA-09 `mca-09-intents-initiative` — evidence (Builder, T-5020…T-5042)

**Статус: blocks A–F focused green; F-1…F-4 закрыты.** Фингерпринт: HEAD `62357c8`
+ рабочее дерево (uncommitted, без stage/commit). База: SQLite v28→**v29**,
`APP_VERSION` 2.58.59 (bump — deploy T-5044, не здесь).

## Collision notice (для истории)

18:31–18:47 05.10.2026 параллельная Builder-сессия дважды перезаписала
`services/mca_intents.py`. Решением @Orchestrator сессия закрыта; её последний
вариант (995 строк: IntentStore/IntentService/InitiativeCandidate/
InitiativeSituation + детерминированные Decision-помощники) принят
**КАНОНИЧЕСКИМ**; я — единственный владелец модуля и всей оставшейся работы.
Коллизия устранена без встречных перезаписей: мои интеграционные швы (enum'ы
Decision-контракта в `direct_chat_service`, `TRIGGER_KINDS` из модуля, хост
`heartbeat_tick`) сохранены и адаптированы.

## F-1…F-4 — закрыто (pre-fix RED зафиксирован)

* **F-1 High** (перезапись повторного интереса невидима active-сканам):
  ссылка на предшественника перенесена в `source_refs_json`/refs (spec §2
  «merged_into_id/refs»); `merged_into_id` остаётся NULL → новая АКТИВНАЯ
  запись видна `due_rows`/`count_active`/`find_live_by_base`. Тест
  `test_reinterest_record_due_visible` (был xfail → green).
* **F-4 Medium** (гигиена не вызывалась тиком): `IntentService.heartbeat_tick`
  вызывает `hygiene` (expire/archive/prune, bounded); хост
  `MemoryMaintenanceService._tick_intent_heartbeat` использует сервис и
  передаёт due-кандидатов в `handle_initiative`. Тест
  `test_hygiene_runs_in_tick`.
* **F-2 Medium** (`PolicyChoice.source` не маппился): `build_random_metadata`
  заполняет `actual_source` из `choice.source` (+`requested_source` из
  аргумента/атрибута). Тест `test_single_probability_check_and_metadata_f2`
  (xfail-тест удалён, green).
* **F-3 Medium** (нет durable-связей mca-04a): `_register_source_refs` создаёт
  SourceRef'ы (get-or-create) + `EvidenceLink` «intent ← ref». Дополнительно
  найден и исправлен скрытый дефект: `method="intent_origin"` не входит в
  закрытый `provenance.METHODS` → все связи молча отбрасывались; заменён на
  `metadata`. Тест `test_source_refs_mca04a_durable_links` (RED → green).
* **Дополнительно найден и исправлен (blocker наблюдаемости D9):** все
  `_emit`-вызовы модуля использовали outcome'ы `ok/merged/abandoned/deferred`
  — не входящие в контракт mca-13 → `build_event` молча отбрасывал КАЖДОЕ
  событие. Заменены на `success/skipped/silent/cancelled/failed`; добавлен
  тест `test_lifecycle_events_pass_mca13_contract` (реальная эмиссия) +
  `test_events_r17_no_raw_text` (R17: без сырого текста/секретов).

## Reviewer F-2 (bounded pre-deploy item) — закрыт

**Finding:** на `candidate_ready`-пути (`handle_initiative`, нет prepared_text)
intent с прошедшим `next_check_at` не получал defer/bump → heartbeat
переизбирал его каждые 300 с бесконечно (латентно: прод-вызовов `create_intent`
ещё нет).

**Pre-fix RED:** `test_candidate_ready_defers_intent_backoff` — падал
(`next_check_at` оставался `NOW-10` вместо `NOW+1800`).

**Fix:** на candidate_ready — bounded defer: `next_check_at = now +
MCA_INTENT_DEFER_BACKOFF_SECONDS` (1800), существующий `activation_condition`
сохраняется, `attempts` НЕ растут (это не фактическая попытка), `defer` шлёт
notable `recheck_deferred`; `decision.next_check_at` отражает серверное
планирование; MAX_ATTEMPTS=3 (3 реальные попытки → abandoned) и
гигиена (expire/archive) уважаются жизненным циклом. Прочие пути/поведение не
менялись (silent-путь — вне рамки этого bounded-фикса, см. ниже).

**Files:** `services/direct_chat_service.py` (candidate_ready-ветка),
`tests/test_mca09_intents_block_e_round1040.py` (+1 regression-тест).

**Rerun:** mca09 focused — **78 passed** (77→78, +1); affected batch
(direct/decision + mca-07/08/13/17a) — **513 passed**; frontier+хост/ностальгия/
статус/egress — **207 passed**.

## Blocks D+E+F (T-5035…T-5042)

* **D (T-5035/36/37):** `SendRecheck` (порядок: включённость → адресат/
  родитель → состояние намерения → новые ответы → разрешения инструмента;
  посторонняя ветка не отменяет; ровно одна повторная оценка → defer
  `recheck_deferred`; коды `stale_context`/`already_answered`/`intent_closed`);
  `apply_recheck`, `chunk_text` (chunks = одна логическая отправка),
  `plan_logical_send` (recheck один раз до первого chunk; silent без chunks),
  `chain_allowed` (нет цепочек без нового события/результата). A16-fixture.
* **E (T-5038/39/40):** единый вход `direct_chat_service.handle_initiative`
  (тот же `CoordinatorDecision`, silent не идёт в Вербализатор/отправку,
  единственный транспорт `telegram_send.send_text`, ledger
  `initiative_reply`); `NostalgiaWorker._delegate_initiative` (K1+K3 ON →
  единый Decision/транспорт; OFF → legacy direct-send байт-в-байт; silent →
  честный `skipped`, ошибка → честный `error`, без второго send-path);
  T-5039: `apply_intent_bundle_signals` (M-MCA07-2 поля единственного bundle,
  frozen replace); T-5040: процесс `intent.initiative` v1 в реестре (стадии
  trigger/candidate/decide/recheck/deliver/close, widget-ID «Намерения и
  инициатива», enabled_gate, `_GATE_RESOLVERS`) + §16.3-снимок
  `StatusService.intent_snapshot` (disabled/not_run/restricted; RBAC/чат-скоуп).
* **F (T-5041/42):** OFF-паритет всех kill-switch (K1 бит-в-бит: 0 SQL по
  v29, кандидатов/событий нет, nostalgia legacy; K2/K3/K4 — подмножества);
  focused-регрессия + R17-скан.

## Focused-прогоны (точные команды)

```
.venv\Scripts\python.exe -m pytest tests/test_mca09_intents_block_a_round1040.py \
  tests/test_mca09_intents_block_b_round1040.py \
  tests/test_mca09_intents_block_c_round1040.py \
  tests/test_mca09_intents_block_d_round1040.py \
  tests/test_mca09_intents_block_e_round1040.py \
  tests/test_mca09_intents_off_parity_round1040.py -q
→ 78 passed   (A16 + B11 + C20 + D10 + E15 + OFF6; E15 — Reviewer-F-2 regression)

.venv\Scripts\python.exe -m pytest tests/test_decision_making_round1026.py \
  tests/test_tool_coordinator_round1026.py tests/test_direct_decision_matrix_asap3.py \
  tests/test_telegram_reactions_round1026.py tests/test_mca07_retrieval_context_round1027.py \
  tests/test_mca08_character_speech.py tests/test_mca08_style_form.py \
  tests/test_mca13_event_contract_round1027.py tests/test_mca17a_observability_core_round1027.py -q
→ 513 passed   (direct/decision + mca-07/08/13/17a; A7-инварианты живы)

.venv\Scripts\python.exe -m pytest tests/test_mca10a_random_source_block_b_round1037.py \
  tests/test_mca10a_random_source_block_d_round1037.py tests/test_mca11_tool_result_round1028.py \
  tests/test_mca11_costs_round1028.py tests/test_mca15_chat_statistics_round1028.py \
  tests/test_mca16_experience_block_e_round1039.py -q
→ 265 passed   (mca-10a/11/15/16 соседние контуры)

.venv\Scripts\python.exe -m pytest tests/test_mca05_episodes_stories_round1027.py \
  tests/test_mca16_experience_block_a_round1039.py tests/test_mca14_schema_additive_round1027.py \
  tests/test_memory_maintenance.py tests/test_nostalgia_worker.py \
  tests/test_status_service.py tests/test_outgoing_guard_round1022.py -q
→ 207 passed   (frontier v29 + хост/ностальгия/статус/egress-guard)
```

R17-скан: `emit_mca_event`/`_emit`/`logger.*` в `mca_intents`/`direct_chat_service`
не несут `goal`/`prepared_text`/`candidate_text`/сырья — 0 находок; тест
`test_events_r17_no_raw_text`. `plans/current_task.md` не изменялся.

## DDL v29 / OFF-паритет / санкции

* v29 (реестр mca-14): `MigrationStep(29)` «intents», таблица `mca_intents`
  (23 колонки §13.2, CHECK на kind/origin/status/activation_condition) + 4
  индекса (`idx_mca_intents_dedup` UNIQUE, `_chat_status_due`, `_status_due`,
  `_chat_kind_status`); свежая БД → `user_version=29`, книга ровно 1 строка,
  повтор — no-op; симулированный v28→v29 + backup-guard (`pre_migration_*.db`);
  PG — no-op (SQLite-only).
* reason_code: 231→**237** (ровно +6, второй словарь не создавался);
  kill-switches: 68→**72** (K1–K4 env-only, default ON, 0 env-оверрайдов);
  Δ каталога = 0 (F8 NOT_APPLICABLE; env-only лимиты 20/3/8/180/1800 не в
  `param_catalog`); канон инструментов 12 не менялся; второго
  контура/очереди/словаря/bundle/RandomSource нет.

## Изменённые файлы

`services/mca_intents.py` (новый, канонический + правки F-1…F-4/D/E),
`services/direct_chat_service.py` (AMEND CoordinatorDecision + DecisionCandidate
+ `handle_initiative` + `initiative_reply`), `services/memory_maintenance.py`
(джоб/тик/hygiene/bot), `services/nostalgia_worker.py` (делегирование),
`services/mca_process_registry.py` (intent.initiative v1), `services/status_service.py`
(§16.3), `services/mca_gates.py`, `services/mca_events.py`,
`services/database.py`, `config/settings.py`, `services/provenance.py`,
`bot.py` (bot=bot); тесты mca09 (6 файлов, новые) + обновлены frontier-пины
`test_mca05`/`test_mca16_a`/`test_status_service` (v29/новый ключ `intents`).

## Related (не входило в bounded-фикс)

Аналогично candidate_ready, silent-путь `handle_initiative` пока не применяет
`decision.next_check_at` к намерению (defer/backoff на silent-исходах
wrong_moment/recent_reply/random_fallback не персистится) — потенциально тот
же класс «переизбрания», но вне рамок инструкции Reviewer («no other
changes»); кандидат на отдельный bounded-фикс/проверку при активации K1.

## Чего нет (честно)

Генерация текста для `intent_due`-кандидатов вне prepared_text не реализована —
`handle_initiative` возвращает `candidate_ready` (отправки нет, за отправку не
выдаётся); live-приёмка T-5045 и deploy T-5044 — вне шага; полный suite не
гонялся (focused-only); paid-вызовов нет.
