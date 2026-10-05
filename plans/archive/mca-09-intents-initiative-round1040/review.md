# MCA-09 `mca-09-intents-initiative` — review (T-5043, Reviewer, 05.10.2026)

## Вердикт

**Approved**

## Binding (базис и рабочее дерево)

* HEAD: `28a05e29b0bf55ff6b710e915dd3f1c8fb534e2a` (master). Отклонение от брифа: там был
  HEAD `92252d1` — после постановки задачи прилетел round 10.39 (mca-16, не связана с
  mca-09): `92252d1` — теперь предок. Pre-existing красные проверены на чистом
  `92252d1` (temp worktree); функциональные прогоны — на `28a05e2` + рабочее дерево.
  Радиус не вырос: mca-16 — соседний хост того же планировщика (`memory_maintenance.py`),
  включён в прогоны (см. "What I ran").
* Working-tree manifest: `plans/reports/mca09_wth_manifest_review.txt`, sha256
  `862f2bb55c7a500945498efd5e908a7ef162823d8750e5b697644b7888bddb26` (28 файлов).
  Исключения из рецепта: `plans/workflow_state.md` (process journal),
  `plans/docs/mca-round1027-arch-frames.md` (foreign WIP), untracked debris
  (`node_modules/`, `.playwright-mcp/`, `package.json`, `package-lock.json`,
  `tools/_ui_asap43_*`, `plans/verification_cache.json`).
* `APP_VERSION = "2.58.59"` (`config/settings.py:3072`) — референс OFF-паритета не нарушен.

## Adjudication (ключевой вопрос: candidate_ready)

**Решение: compliant (честный decision-handoff); недостающий send-path — это
следующий запланированный кусок mca-09, а не второй контур. Неблокирующе, честно
декларировано в evidence.md («Чего нет») и совместимо с no-false-acceptance (`:15167+`).**

* Spec D1 (spec.md:17): «аддитивный вход DirectChatService *для решения* … использующий
  тот же CoordinatorDecision, тот же слой A7 и **единственный транспорт**
  `telegram_send.py`». Вход `handle_initiative` (direct_chat_service.py:6316–6405)
  существует, использует тот же `CoordinatorDecision`, единственный
  `telegram_send.send_text`, ledger через существующий mca-22 (`initiative_reply`,
  :795–802) — второй контур не появился.
* Spec D6 (spec.md:135): для nostalgia текст уже сформирован (1 LLM-call внутри
  nostalgia) — путь работает end-to-end: recheck → chunks (одна логическая отправка,
  T-5036) → `send_text` → `mark_attempt` → ledger → честный статус в `nostalgia_log`
  (nostalgia_worker.py:476–510). A17 подтверждено пробегом: silent — ни verbalizer, ни
  отправки.
* Для `intent_due` вне prepared_text генерация не реализована — `handle_initiative`
  возвращает `candidate_ready` (direct_chat_service.py:6342–6348), статус честный: без
  отправки, без LLM, ничего не выдаётся за sent. ТЗ §13.1 (`current_task.md:478`) —
  «Каждый триггер ведёт к *кандидату решения*, не к автоматической реплике»;
  §13.3 `:494` — «Бот выбирает … или молчание»; живое закрытие кандидата в
  реальный контур остаётся задачей живой проверки T-5045 (§11.8).
* Не нарушает: «тишина сама по себе не порождает отправку» (§13.1 `:474`; D5 spec.md:125
  «триггер → кандидат, НЕ автоотправка»).

## Findings

### F-1 (Info) — нет блокирующих находок

Код-гигиена и контракты проверены по всему дифу; требуемых правок нет.

### F-2 Medium (non-blocking, fix до активации в прод K1)

* **Место:** `services/mca_intents.py:1159–1186` (`due_candidates`) +
  `services/direct_chat_service.py:6342–6348` (`candidate_ready` path).
* **Scenario:** pending-intent с прошлым `next_check_at` не получает ни `defer`, ни
  `mark_attempt`, ни bump `next_check_at` на честном пути нет-prepared-text. Heartbeat
  (300 s) реэлектит тот же intent на каждом тике — вечный повтор кандидатов/логов
  (без LLM/отправок, приоритет/статус не меняются).
* **Evidence:** путь повторяется в коде; чистых регресс-тестов нет. Смягчение: prod-вызов
  `create_intent` отсутствует (grep — только tests): таблица пуста, цикл не запустится,
  **пока** не появится создатель intent'ов (следующие блоки mca-09/MCA-10b).
* **Blocking: no** (не Critical/High, не requirement-blocking: честный no-send-статус
  декларирован). **Действие:** bounded fix до T-5044/live: после `candidate_ready`
  при db+intent_id — `defer(intent_id, next_check_at=now+MCA_INTENT_DEFER_BACKOFF_SECONDS)`
  (или просто bump `next_check_at`); + 1 регресс-тест «повторный due-скан завершается».

### F-3 Low (incidental)

* `services/memory_maintenance.py:141–149`: job `intent_heartbeat_tick` регистрируется
  при K2=ON даже если K1=OFF; тело job'а всё равно fail-fast-неактивное
  (`mca_intents.heartbeat_tick:1221–1227`) — двойная защита уже есть, «пустая» регистрация
  — cosmetic. Blocking: no.

### F-4 Low (incidental, не блокирующ)

* `plan_logical_send`/`handle_initiative` передают только `intent_row` в
  `RecheckContext`; сигналы addressee/parent/new replies/tool permission —
  ответственность caller'ов; для первого fake-path все defaults-True. Контур D4
  реализован (SendRecheck механизм/коды/defer/one-re-eval — честны); full-функциональный
  live-контекст должен прийти на следующем блоке. Blocking: no.

## Answers

**R1 (triggers/heartbeat).** Триггеры — закрытый `TRIGGER_KINDS` (mca_intents.py:58–60),
соответствие §13.1 `:478`; `candidate_from_trigger` → кандидат, не автоотправка (:281–300).
Heartbeat: host — существующий APScheduler обслуживания, job `intent_heartbeat_tick`,
300 s код-константа (memory_maintenance.py:51,141–149; max_instances=1, coalesce=True);
тик — только SQL due-скан по `mca_intents` (`due_rows`, bounded LIMIT, батч ≤
`MCA_INTENT_HEARTBEAT_BATCH_MAX`=20, coalesce ≤1/чат/тик, mca_intents.py:1167–1186) +
hygiene (fix F-4); **без LLM**, окно сообщений не читается никогда («500 сообщений» —
запрет соблюдён). Кандидаты отдаются в `handle_initiative` (memory_maintenance.py:235–250) —
единый контур; без bot — честный лог.

**R2 (Intent).** v29 `mca_intents` = 23 колонки (§13.2) + CHECK kind/origin/status/
activation_condition (database.py:1216–1259) + 4 индекса (UNIQUE dedup_key и др.);
миграция через реестр mca-14 (`MigrationStep(29)`, database.py:3141+), аддитивно/
идемпотентно, PG no-op. Жизненный цикл: `_transition` только из pending/deferred (:1069) —
терминальное НЕ флипается; терминальное закрывает dedup-ключ суффиксом `#c:`
(`release_dedup_key`, :835–846) → повторный интерес = НОВАЯ запись (fix F-1:
предшественник в refs через `intent:<id>`, merged_into_id остаётся NULL — live-сканы
видят новую запись). Dedup-merge (chat+kind+subject+topic канон) :993–1015; архирование
+ retention-прун ТОЛЬКО архивных (:768–776; hygiene :1188–1216) — активные не прунятся;
«5–10 не жёсткий предел» (нет продуктового лимита). Дисциплина обязательств:
`creation_allowed` (:122–135) — не каждая фраза; `unanswered_question` требует
canonical goal; остальные — refs на повод; `mark_attempt` → deferred на `new_reply`
(без таймерного повтора); ≥ `MCA_INTENT_MAX_ATTEMPTS` → `abandoned` (честное закрытие,
:1117–1141). A15: `close()`, recheck `already_answered` → `close_intent=fulfilled` —
закрыть без вопроса (:547–550). Источники — mca-04a SourceRef/EvidenceLink (fix F-3:
method "metadata" ∈ `provenance.METHODS` — provenance.py:49–51; intents :911–942).
Записи — только `write_transaction` (mca-01; IntentStore writes :796–862).

**R3 (Decision).** `COORDINATOR_ACTIONS = (reply,react,silent,tool)` сохранён
(direct_chat_service.py:649–653); все новые поля CoordinatorDecision — аддитивные с
defaults (:1056–1068) с нормализациями незнакомых (:1081–1114); enum не сломан; `defer`
НЕ введён (defer = silent + `next_check_at`/status deferred: decide_initiative
mca_intents.py:362–396; apply_recheck :565–580). Silent НЕ проходит вербализатор и ничего
не отправляет (handle_initiative:6337–6341 — early return без send). tool→silent
(`finish_tool_decision`, :447–473): force/explicit никогда не silent;
`delivery_unknown` — без слепого повтора. Уместность — детерминированный слой БЕЗ
третьего LLM-вызова (:345); «nag-таймер» отсутствует: `random_fallback`-defer и
backoff (1800 s) применяются только к необязательной инициативе (direct не задевается);
direct-приоритет: `direct_pending`/`same_event_pending` → silent; dedup только того же
события (не похожих фраз). mca-10a: `build_random_metadata` — read-only копия готового
`ExplorationPolicy.choose` (fix F-2: `actual_source` из `PolicyChoice.source`; второй
draw не делается; :305–339); истина/права/идентичность не рандомизируются (жёсткие стопы
direct/sensitive). mca-11: `tool_outcome` — типизированный статус ToolResult (7,
:1117–1120); счёт notable-only — механизм mca-11; чек→reconcile, пин retries не задеваются;
повторов нет.

**R4 (SendRecheck).** Порядок соблюдён (SendRecheck.check :534–562): enabled →
адресат/родитель (`addressee_ok`/`parent_changed`) → состояние намерения (терминальный /
merged → `intent_closed`; терминальное не реактивируется) → новые ответы / branch
(`already_answered`/`same_branch_replies` → `close_intent=fulfilled`, A15) → tool
permission (без слепого повтора). Ровно одна повторная оценка (`recheck_attempts=0` →
`recheck_again`; вторая смена → defer `recheck_deferred` + backoff, бесконечного
пересмотра нет). Посторонняя ветка НЕ отменяет (branch-scoped сигналы только
`same_branch_replies`). `chain_allowed` (:635–654): intent_due после попытки без нового
события/результата → запрещено; self-reply-chain нет. A16: `plan_logical_send` (:617–632)
— recheck ровно один раз до первого chunk; `chunk_text` чистый — chunks = одна
логическая отправка; silent — без chunks. Cause codes `stale_context` /
`already_answered` / `intent_closed` / `recheck_deferred` — все в REASON_CODES.
Deferred-слоя зависят от полноты контекста caller'ов (F-4) — не blocking.

**Single contour (D6, границы).** Один движок решений (`CoordinatorDecision`), один
транспорт (`telegram_send.send_text`), один store/write-механизм (v29 через
write_transaction), один словарь (`REASON_CODES`), один EvidenceBundle
(`apply_intent_bundle_signals` — frozen `dataclasses.replace` полей `chosen_intent` /
`recent_actions` / `ambiguities` / `unknown` / `contradictions`, второй bundle не
создаётся, M-MCA07-2 сохранены). `NostalgiaWorker` (nostalgia_worker.py:476–510,
533–559): K1+K3 ON → единый Decision/транспорт (silent → честная `skipped`-строка
nostalgia_log, без ложного sent; ошибка → честный `error`, без legacy-фолбэка —
обходимо, чтобы не усложнить second send-path); K1/K3 OFF → legacy `bot.send_message`
байт-в-байт 2.58.59 (`_intent_delegation_enabled` :89–98 — проверено кодом). Границы:
mca-08 — второй классификатор / clarify не введён; mca-15 — stats-intent не дублирован;
mca-16 — outcome-сигналы `note_decision` (`initiative_decided` ≤ 1/ситуация,
contract-outcome mapping `_INITIATIVE_OUTCOMES`) — не ExperienceEpisode/Lesson (опыт
создаёт только mca-16); mca-22 — собственные ответы — только ledger через
`record_delivered_output` (не подтверждение закрытия intent'а).

**Observability.** Процесс `intent.initiative` v1 (mca_process_registry.py:946–979:
стадии trigger/candidate/decide/recheck/deliver/close, widget-ID «Намерения и
инициатива», enabled_gate `MCA_INTENTS_ENABLED`, `_GATE_RESOLVERS` +1 :1048–1049).
§16.3 `intent_snapshot` (status_service.py:617+): честный `disabled/not_run/restricted`
при OFF, chat-scope; новых маршрутов нет (ROUTES_SHA256_F11 не трогался). Reason-коды
ровно +6 (`intent_created`, `intent_merged`, `intent_fulfilled`, `intent_abandoned`,
`intent_archived`, `recheck_deferred` — mca_events.py:267–268), import-счёт **237**
(пересчитан мной), второй словарь нет; KILL_SWITCHES **72** (+4 K1–K4). События —
notable-only через единственный `emit_mca_event`; R17-scan + тест
`test_events_r17_no_raw_text` зелёные; мой обзор `_emit`/`logger`-сайтов: goal /
prepared_text в события/логи не проходят (только entity_id / codes / enums).

**OFF-паритет (K1–K4).** Env-only ClassVar[bool] default ON (settings.py:1494–1514;
env-лимиты 20/3/8/180/1800 :1505–1514 — не в каталоге, Δ каталога = 0). Собственный чек
K1: job не регистрируется при K1/K2 OFF (memory_maintenance.py:63–71,141),
`heartbeat_tick` → disabled без SQL (mca_intents.py:1221–1227),
`candidate_from_trigger` → None, nostalgia → legacy. K3: `decide_initiative` → silent +
`disabled` (:366–369), `handle_initiative` → disabled (:6328–6330), nostalgia
delegation → off → legacy direct-send. Прогоны (OFF 6 passed) подтверждают
подмножества; K1 = бит-в-бит 2.58.59 (0 чтений/записей v29, 0 кандидатов/событий).
0 env-overrides (defaults True/True/True/True, проверено import-прогоном).

**R17.** Серверный канон goal/reason ≤200 через `sanitize` (`canon_text`), refs через
`_SAFE_TOKEN_RE`; события/логи — ID/коды/enum/числа; `plans/current_task.md` не
изменялся (git status).

## What I ran (точные счета)

| Проверка | Команда (сжатая) | Результат |
|---|---|---|
| focused mca09 (6 файлов) | `pytest tests/test_mca09_intents_block_{a..e}+off -q` | **77 passed** |
| A7 invariants batch (3 файла) | `test_decision_making + test_tool_coordinator + test_direct_decision_matrix` | **177 passed** |
| A7 full batch + mca-07/08/13/17a (9 файлов) | полный набор | **513 passed** |
| Adjacent/frontier slice (10 файлов: mca-10a-b, mca-11 ×2, mca-15, mca-05, mca-16-a, mca-14, memory_maintenance, nostalgia_worker, status_service) | набор | **349 passed** |
| RED on clean HEAD `92252d1` (temp worktree + копия новых тестов) | `test_mca09_block_a + off` | **2 collection errors** (`cannot import name 'mca_intents'`) — тесты реально привязаны к новой функциональности |
| Pre-existing red #1 on clean `92252d1` (worktree) | `test_tool_loop -k count_reaches_model` | **1 failed** (повторен: устаревший ожидаемый текст vs фактическая строка статистики) |
| Pre-existing red #2 (`test_migrate_env_to_pg`) | clean `92252d1` → **21 passed / 0 failed**; также рабочее дерево (28a05e2 + WT mca-09) → **21 passed / 0 failed** | **не воспроизводится** (влемб «22 vs 21» — не текущее) |
| Словари/счётчики | import-счёт | REASON_CODES **237** (+6), KILL_SWITCHES **72** (+4), APP_VERSION **2.58.59** |

## Классификация pre-existing красных (проверено на чистом HEAD `92252d1`)

* `test_tool_loop::…count_reaches_model` — **pre-existing, повторен** (1 failed на
  92252d1). Файлы не в mca-09 diff — по сути устаревшее ожидание mca-15-текста.
  Классификация: unrelated/pre-existing, Severity Low, бэклог (accepted-with-note). Не
  влияет на release-радиус.
* `test_migrate_env_to_pg` («22 vs 21 keys») — **не воспроизводится** (21/21 и на чистом
  `92252d1`, и на рабочем дереве). Видимо закрыт предыдущими раундами. Классификация:
  не блокирует; указать в бэклоге, что pre-existing-red list должен быть обновлён.

## Residual notes

* Finding F-2 (Medium): до T-5044 (деплой + активация K1 в прод) — добавить
  bump/defer `next_check_at` на пути нет-prepared-текст (`candidate_ready`) + 1
  регресс-тест. Bounded fix, в T-5043 не вносимый.
* Recheck-слой — механизм D4 реализован полностью (ordер, коды, defer, one re-eval,
  A16); полные сигналы (адресат/родитель/новые ответы/разрешения инструмента)
  подаются caller'ом (F-4). Не блокирует (честный scaffold); но Builder должен
  при следующем блоке дописать реальные сигналы в RecheckContext.
* Live T-5045 — **[PENDING OWNER]** — после T-5044 деплоя и активации K1 в прод:
  создание/закрытие намерения реально видно; повторного вопроса после закрытия нет;
  silent без отправки; stale-check при смене темы; витрина §16.3. Требуется реальный
  чат без имитации.
* Binding: HEAD `28a05e2` + WT manifest `plans/reports/mca09_wth_manifest_review.txt`
  (sha256 `862f2bb5…`, 28 файлов; исключения — см. Binding). Любые изменения WT, не
  вошедшие в manifest, инвалидируют этот ревью.

## Stop-rule

Требования имеют прямые доказательства (77 + 177 + 513 + 349), diff и границы контура
поняты; непокрытый failure-механизм (due-candidate loop) задокументирован с
ограничением (таблица пуста в прод, prod-созданий нет). Блокирующих находок нет.---

## Addendum: F-2 resolved — micro-fix recheck (Reviewer, 05.10.2026)

**Scope verified exactly:** `services/direct_chat_service.py` — only the
`candidate_ready` branch of `handle_initiative` (:6342–6374); + regression test
`tests/test_mca09_intents_block_e_round1040.py::test_candidate_ready_defers_intent_backoff`
(pre-fix RED: old path would re-elect immediately — `next_check_at` stays past);
evidence.md F-2 note. No other behavior change (silent path / send path / recheck untouched).

**Fix correctness (spec D2/D3/D10):** bounded defer —
`service.defer(intent_id, next_check_at=now+backoff, activation_condition=preserved)`;
`attempts` NOT inflated (defer is not an attempt; `mark_attempt` only on real sends);
`MAX_ATTEMPTS=3` honored (3 real attempts → `abandoned`, then terminal guard skips);
hygiene respected (`expired`/terminal rows skipped by `status IN ('pending','deferred')`
guard, direct_chat_service.py:6354–6355); notable `recheck_deferred` emitted via
`service.defer`; decision carries `next_check_at` back. Test asserts: no re-election at
+301 s; re-election exactly at backoff end; 3 attempts → abandoned; then no due rows.

**Counts (rerun by Reviewer):** mca09 focused (6 файлов) — **78 passed** (77+1);
affected batch A7+mca-07/08/13/17a (9 файлов) — **513 passed**; uses `intent_defer_backoff_seconds()` (env/мин 60, default 1800).

**Binding (refreshed):** HEAD `28a05e29…` unchanged; manifest v2
`plans/reports/mca09_wth_manifest_review.txt`, sha256
**`6d6b6d7410129892fb2898d30bd91f3c83c0bd80811e4a3d030514b758c9e63a`** (28 файлов;
supersedes `862f2bb5…` from the original review; self-file excluded from recipe —
stable non-self-referential digest).

**F-2 status: RESOLVED** (fixed, verified, covered). **Verdict remains: Approved.**
Residual (cosmetic): silent-branch of `handle_initiative` does not plan next_check_at —
today unreachable in the heartbeat path (permissive defaults → candidate_ready), keep
in mind if situation flags become non-trivial in upcoming blocks.