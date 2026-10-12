# ASAP 8 Phase A — forensic audit: Modules / Infra (lane P8-C)

Baseline: `master @ 0c4f3a5` (release 2.58.74). Дата аудита: 10.10.2026. Режим read-only; ТЗ — `plans/current_task.md` §8–§18 (ASAP 8-блок, строки 33792+).

---

## 1. §11 parentGate — Summary OFF ложно блокирует модули → **CONFIRMED**

**UI-гейты (все 7 модулей из ТЗ):** `web/app.js::MODULES` — `parentGate: 'flags.summary_enabled'` у:
- Direct `web/app.js:556`, Factcheck `:562`, Search `:568`, Transcription `:574`, Video Summary `:580`, Web `:590`, Diagnostics (checkup) `:595`. (Media download — без parentGate, `:582-586`.)

**Логика blocked:** `_moduleRuntimeState()` `web/app.js:9166-9186`; parent=false → `'blocked'` на `:9174-9178`; плюс global-gate+global_value=false вне глобального scope → `'blocked'` `:9183-9184`.

**Текст при chat scope:** `moduleRuntimeNotice()` `web/app.js:9189-9220` — `:9200-9203` возвращает «Не работает: отключён глобально» в ЛЮБОЙ области (комментарий `:9198-9199` это явно фиксирует), т.е. и при выбранном чате. Кард-текст «Включён, но не работает» — `:9235`.

**Реальные зависимости (карта для F5):**
- `flags.summary_enabled` — **реальный bootstrap-master, но только startup-ось**: в `bot.py:840-874` роутеры 0a–0i (observer, summary, factcheck, search, youtube, web, checkup, direct_chat, voice_transcription) инклюдятся ТОЛЬКО если `hot.get("flags.summary_enabled")` на старте процесса. Динамической перерегистрации нет → (a) Summary OFF при старте = модули реально мертвы; (b) Summary выключенный ПОСЛЕ старта через UI = роутеры живы, а UI пишет «не работает» — ложь. Ответ на вопрос ТЗ: **да, есть bootstrap-master, замаскированный под Summary** (комментарий в app.js:544-545 признаёт: «регистрация роутеров 0a–0i по flags.summary_enabled»).
- Transcription: AND `flags.summary_enabled` AND `flags.enable_voice_transcription` (`bot.py:873`).
- Video: отдельный runtime-гейт `flags.video_summary_enabled` (`handlers/youtube.py:1355`) поверх bootstrap-оси.
- Direct: собственный тумблер `flags.direct_chat_botword_enabled` (MODULES `:555`).
- Продуктово (без учёта startup-оси) Direct/Factcheck/Search/Web/Diagnostics/Video независимы от Summary — ожидаемая таблица ТЗ §11.3 подтверждается.

---

## 2. §12–13 Initiative — не замкнута → **CONFIRMED (все пункты)**

**(а) defer при TEXT + no prepared_text:** `services/direct_chat_service.py::handle_initiative` `:7242-7256`; условие `if kind != DELIVERY_TEXT or not prepared_text:` `:7320` → bounded defer с backoff `:7328-7347`, `note_decision(candidate_ready)` `:7348-7349`, возврат `candidate_ready` `:7350-7352`. Генерации текста в heartbeat-пути нет.

**(б) heartbeat:** `services/memory_maintenance.py::MemoryMaintenanceService._tick_intent_heartbeat` `:244-283` (регистрация каждые 300 c: `:159-167`) → `handle_initiative(...)` **без prepared_text** `:274-277`. Дуэ-скан по существующим `mca_intents` (`heartbeat_tick`) — новых намерений не создаёт.

**(в) Producers — repo-wide grep `IntentService.create_intent(` / `.create_intent(`:** production call-sites — **НОЛЬ**. Единственное место определения `services/mca_intents.py:956`; все вызовы — тесты: `tests/test_mca09_intents_block_a_round1040.py:62`, `block_b:44`, `block_d:215`, `block_e:121,157,195,291,295,318,367`, `off_parity:89,120,139`, `test_mca10b_random_applications_block_a_round1041.py:572,622`. Ни один реальный producer-событий (unanswered_question/unfinished_topic/…) не существует. Цепочка ТЗ «no intents → heartbeat нечего делать → not_run навсегда» подтверждена. Ностальгия — отдельный контур со своим prepared_text (`services/nostalgia_worker.py:604-630`), intents не создаёт.

**(г) UI «не запускалось»:** `services/status_service.py::intent_snapshot` — `state = "ok" if (count or last) else "not_run"` `:850`; empty-шаблон `:767-768`; module-блок (requested/effective/heartbeat/pending/last_decision/last_skip/next_due) `:741-766, 851-856`. Рендер: `web/app.js:6938` (intentsStateLabel not_run→«не запускалось»), `web/index.html:6736` («Намерений пока нет — инициатива ещё не запускалась»). Статус не различает heartbeat/producers/writer — подтверждено (§17).

**(д) SendRecheck:** `services/mca_intents.py:520-562` (`applies()` покрывает initiative trigger_kind `:528-532`; `check()` — stale/closed/answered/denied/context-version `:534-562`), `plan_logical_send` `:617-632`, chunks `:583-608`. **Уже подключён** в initiative-пути: `direct_chat_service.py:7361-7372` (recheck → cancel с reason) и отправка `:7373-7379`. Переиспользование для REPLY: да — недостающее звено ровно одно: генерация `prepared_text` (Direct L2 Writer, trigger=`initiative`), после чего весь send-контракт (recheck+chunks+ledger `:7398-7409` + mark_attempt `:7391-7397`) работает как есть. Защита от вечного цикла уже есть: `chain_allowed` intent_due — только при attempts==0 или новом событии (`mca_intents.py:650-654`).

---

## 3. §9 Experience scope — тройной mismatch → **CONFIRMED**

1. Каталог: `services/param_catalog.py:2327-2343` — «dotted-ключи memory.experience_* … **per-chat** (chat_params, категория memory)» (EXPERIENCE_LEARNING_ENABLED `:2331`, EXPERIENCE_REVIEW_CADENCE `:2338`).
2. Реестр: `services/module_registry.py:149-168` — Experience с `runtime_gate="global"` (`:156`).
3. Runtime: `services/mca_experience_jobs.py:118-130` `_learning_enabled()` — `hot.get("memory.experience_learning_enabled", ...)` **без chat resolver**; worker глобальный (`tick_experience_review`, один джоб на все чаты — `memory_maintenance.py:229-242`). Per-chat override из UI воркером никогда не прочитается.

---

## 4. §10 Random — module без product master → **CONFIRMED**

`services/module_registry.py:172-194`: Random `master_param=""` (`:179`), rationale прямо: «no master: мастера-тумблера в каталоге нет … мастер — env-ось MCA_RANDOM_SOURCE_ENABLED» (`:189-193`); `ENV_GATES["random"]="MCA_RANDOM_SOURCE_ENABLED"` `:209`, `:385-386`. В каталоге product-мастера нет: только select RANDOM_SOURCE (`param_catalog.py:2302`), вероятности `memory.random_*` (`:2299-2325`) и 6 bool `memory.random_uses_*` (`:1237-1264`); kill-switch env-only и в каталог не дублируется (`:1230`). Тест фиксирует этот gap как норму (`tests/test_asap7_module_completeness.py:225-226` — см. §18).

---

## 5. §15 Embeddings group=unknown → **CONFIRMED (с уточнениями)**

- unknown без labels: `services/embedding_control_plane.py:16-21` (без `EMBEDDING_QUOTA_GROUP_LABELS` / hot `keys.embedding_quota_group_labels` → unknown; вычислять project запрещено), источник labels `:267-269`, hint `:308-309`.
- Весь unknown-пул — ОДНА группа: `UNKNOWN_GROUP_ID="unknown"`, safe default «ВСЕ unknown credentials в ОДНОЙ группе» `:155-157`. Cooldown группы блокирует все её ключи: `acquire()` → `REGISTRY.group_blocked(group_id)` → `EmbeddingGroupCoolingDown` `:799-826`; «все доступные группы cooling/exhausted» `:1122`. Итог: 3 ключа в одном unknown + cooldown = заморожен весь пул — подтверждено.
- UI квота-групп: **ЕСТЬ** (ТЗ-вопрос) — `web/api/memory_agi.py:484-522` `memory_embeddings_panel` (provider/model, credentials=N алиасов, квота-группы, 429 за 10 мин; global-admin only `:495`), рендер `web/index.html:4933-4944`.
- WARN-спам на каждый факт: **REFUTED** для текущего HEAD — один WARN на logical batch (T-4879: `services/summary_memory.py:3064-3074`) + одно notable-событие EMBED_API_DEFERRED на batch `:3075-3081`; per-fact WARN только для неожиданных (не serviceability) ошибок `:3280-3289`; повторных embed-попыток в batch нет (≤1, `:3262-3264`, breaker-тесты `tests/test_asap44_graphrag_batch_breaker.py`).
- Auto-backfill после recovery: **ЕСТЬ, частичный** — `_ensure_vec_retry()` `summary_memory.py:2147-2190`: re-probe раз в 10 мин (`_VEC_REACTIVATE_INTERVAL=600` `:284`) на путях vector_search/_search_graph_facts, успех → fire_and_forget `backfill_archive_vectors` + `backfill_graph_fact_vectors` `:2187-2188` (батчи, потолок, dedup existence-check `:2192-2251`). Триггер — read-path, отдельного планового джоба/прогресса backlog в UI нет.

---

## 6. §16 YouTube 407 → **CONFIRMED**

- `_is_transient`: `services/youtube_transcript_engine.py:527-574`; `if name in ("TransportError", "ProxyError"): return True` `:565-566`. 407 теряется дважды: (1) ProxyError классифицируется по имени типа без разбора статуса; (2) если 407 приходит как `HTTPError`/`DownloadError` — `HTTPError` проверяет `_RETRY_HTTP_STATUSES = {403,429,500,502,503,504}` `:54,559-564` (407 нет → permanent только в этой ветке), но `DownloadError` → `return "http error" in text_l` `:567-568` — «HTTP Error 407» содержит «http error» → **transient**. Каскад: попытка = yt-dlp→transcript-api, transient по OR хотя бы одного движка `:153-155`, ретраи `_MAX_CASCADE_RETRIES=4`, backoff `(1,2,4,8)` c `:52-53`, цикл `:120-172` → ровно повтор 5 попыток / ~27 c при перманентной прокси-ошибке.
- Proxy health UI/test: **НЕТ** — в web/ нет ни connection-test, ни статуса прокси (grep «прокси/proxy_test/connection_test» — только avatar-прокси UI). Secrets masking в engine-логах: error/status/body_bytes — ок.

---

## 7. §14 Stories — humanize → **CONFIRMED**

Сырье в UI: `web/index.html:2529` «**Участники (ID):** {{ story.participants.join(', ') }}» (raw IDs в карточке управления); лента: `:7010-7011` «участники: {{ ev.participants.join(', ') }}»; таблица `:2474` «Эпизодов / Версия»; счётчики+backfill-прогресс витрины — `/api/stories/summary` (`web/api/stories.py:92-117`), лента `/api/stories/feed` `:122-146`, карточка `/api/stories/{id}` `:208+`. Данных для human-карточек достаточно: у story есть title/версия/участники (канон-ID, которые можно резолвить в display names через IdentityResolver/aliases), у эпизодов — даты и число исходных сообщений (обе даты A11 уже в entity ленты).

---

## 8. §1.2 plans reconcile → **RESOLVED (10.10.2026, частично — на владельце)**

- `git ls-files plans/`: **`plans/current_task.md` НЕ в master-трекинге** (owner-owned, только в рабочей копии) — подтверждено.
- `plans/runtime_task.md`, `plans/workflow_state.md` — tracked; сейчас содержат ASAP 8 baseline/Phase 0 и список причин (workflow_state.md:18) — **синхронизированы мной под ASAP 8, uncommitted** → пункт ТЗ «sync runtime pointer/workflow state» = **RESOLVED 10.10.2026** (до коммита — грязное состояние репо, это осознанный uncommitted-шум).
- `plans/features/asap7-cognitive-direct-pipeline` — **активна, tracked** (architecture/audit-*/deploy-w*-evidence/f1–f9-отчёты в master). Рекомендация: архивировать в `plans/archive/asap7-cognitive-direct-pipeline-round1049/` после закрытия Phase A (чекбоксы/содержимое сохранить — прецедент f0). Решение — за Architect.

---

## 9. §1.1 CLAIM→REALITY (5 самых рискованных) — вердикты

| Claim | Код-путь | Вердикт |
|---|---|---|
| Cover Prompt Truth закрыт | backend `web/api/analytics.py:630-659` (`?include_prompt=true`, fail-closed global-admin) существует; reader+manifest-инвариант есть (e6670b0) | **PARTIAL** — backend OK |
| exact prompt доступен (владельцу) | `web/app.js:5523-5551`: include_prompt только при `pipelineSelectedRunId` (`:5530`); в режиме «Последний запуск» selection сброшен (`:5552-5556`) → detail не запрашивается → блок «Фактический промпт» скрыт | **PARTIAL→FALSE в default-режиме** (ТЗ §6.1 подтверждена) |
| Module Contract закрыт | registry есть (`module_registry.py`), но: Random no master (§4), Experience scope mismatch (§3), fake parentGate в UI (§1), env-гейты под INFRASTRUCTURE_RATIONALE | **PARTIAL** (контракт не закрыт) |
| lifecycle нового чата исправлен | `handlers/chat_lifecycle.py` — my_chat_member join/leave + ChatProfileFallbackMiddleware (e6670b0; `tests/test_asap7_chat_lifecycle.py` 476 строк) | **LIVE_PENDING** — my_chat_member-доставка проверяется только на живом чате |
| Help v8/v5 синхронизирован | a1b3279: миграции v7→v8/v4→v5, `tests/test_asap7_f9_help_resync.py` существует | **LIVE_PENDING** — канон доставляется деплоем; /api/info v8/v5 — owner-гейт |

---

## 10. §18 аудит коммитов e6670b0/71b3b69/3e52b96/a1b3279/0c4f3a5 — подозрения (light pass)

1. **`tests/test_asap7_module_completeness.py:225-226`** — `assert mr.effective_gate("random") == (True, True, "both")` с комментарием «мастера-тумблера нет» — тест освящает известный gap §10 как ожидаемое поведение (self-fulfilling pin).
2. **`tests/js/asap7_f8_cover_prompts_test.js:133-160`** — loader тестируется только с предустановленным `pipelineSelectedRunId:'run-f8'` (`:138-139`); default-режим «Последний запуск» (пустой selection) не покрыт — поэтому UI-баг §6.1 зелёный тестами. Test path ≠ live path.
3. **baseline-fикстуры** `tests/fixtures/round1025/catalog_baseline.json` + `f8_baseline.json` (правились в 3e52b96/0c4f3a5) — самоссылочные снапшоты: замораживают и текущие дефекты (например, per-chat классификацию experience) как «канон».
4. `test_m2_ext_no_dead_knobs` (`:142-158`) — ассерт на строку исходника (`'_module_catalog_flag(...)' in gates_src`) — реализация проверяет саму себя; слабый, но не ложный smoke.
5. Явных «тестов-констант» в e6670b0/71b3b69 (lifecycle/cover_fix) не найдено; 0c4f3a5 — только conftest-fix порядка тестов, не self-fulfilling.

---

## 11. Funnel-предложение (Initiative diagnostics, для F-плана)

Источники уже есть: `mca_events` (`intent_created/intent_merged`, `initiative_decided{outcome}`, `recheck_deferred` — запрос в `status_service.py:802-846`), `mca_intents` (status/next_check_at), module-блок (heartbeat/pending/last_skip/next_due). Добавить счётчики: `producers_24h` по origin (пока всегда 0 — честно показывать «нет источников»), `writer_generated` (новое событие при L2-генерации trigger=initiative), `recheck_passed` (plan.outcome.proceed), `sent` (ledger `record_delivered_output` output_kind=initiative). Формула статуса вместо «не запускалось»:
- heartbeat ON + intents=0 + producers=0 → «Heartbeat работает, producers за 24ч не создали ни одного намерения»;
- intents>0 + decisions=0 → «due не избираются (причина последнего скипа: …)»;
- decisions>0 + writer=0 → «N раз candidate_ready→defer: генерация текста отсутствует»;
- writer>0 + sent=0 → «SendRecheck отменил: reason=…».

## 12. Вопросы для Architect

1. Random: заводить product master (ключ/группа каталога) или честно переносить в Memory/Infrastructure/Advanced? Промежуточный вариант ТЗ отклоняет.
2. Experience: worker global + per-chat opt-in (нужен chat-resolver и, вероятно, новый per-chat ключ) — или глобальная настройка с правкой каталога/реестра?
3. `flags.summary_enabled` как скрытый bootstrap-master (bot.py:840-874): выделить отдельный ключ с restart-семантикой в UI или сделать динамическую перерегистрацию?
4. Initiative: владелец producer-событий (Direct L1 vs Coordinator vs воркеры) и допустимо ли создание intent из L1 (allowlist, без прямой записи LLM в DB)?
5. 407: классифицировать `proxy_auth_failed` в общем media/proxy-слое (единый профиль для yt-dlp + transcript-api) или только в `_is_transient`? Нужен ли MiniApp proxy connection-test?
6. Архивировать ли `plans/features/asap7-cognitive-direct-pipeline` и коммитить ли synснутые runtime_task/workflow_state в рамках Phase A?
