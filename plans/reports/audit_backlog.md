# Audit Backlog

<!-- Format: one item per line, `- [ ]` = pending, `- [x]` = done -->
<!-- High-priority (git-changed) files go on top; no code-change files this run. -->

## Round 10.21 scan + re-audit (Step 6 @Scanner, 18.09.2026) — all scanned/closed (diff-based, HEAD 21cd54c + worktree)
- [x] services/grounding_validator.py (F2: anchors только из доверенных источников — S10.21-5 CLOSED; дата-теги без
      `fact:ID` проверяются — S10.21-4 CLOSED; fail-open, no ReDoS)
- [x] services/factcheck_service.py + services/tool_loop.py (F2: `tool_context` до cleanup; `trusted_parts` =
      rag/results/chat_context/tool_context, `<claim>`/`<user_hint>` исключены — S10.21-5 CLOSED)
- [x] services/dossier_prompts.py + services/lore_worker.py (F1: слои A/B, фильтр, дедуп, бюджет; пустой `memes` Слоя Б
      больше не перетирается мемами А — S10.21-7 CLOSED)
- [x] services/database.py (`get/upsert_generated_dossier`; `initialize_readonly` (`mode=ro`, без DDL/WAL/создания файла) —
      S10.21-6 CLOSED; схема v12, Info S10.21-11 открыт)
- [x] services/memory_rebuild.py (F5: allowlist+`RAW_HISTORY_TABLES`+`_guarded_delete`; бэкап→JSONL→сверка→DELETE;
      `_chat_roster` union nodes+portraits+overrides + `roster_incomplete`/`roster_size` — S10.21-2 CLOSED;
      `belief_source` исключает опоры убеждений — S10.21-3 CLOSED; Info S10.21-13 открыт)
- [x] manage.py (F4/F5 CLI `memory`; guard целевого чата; `audit` через `initialize_readonly` — S10.21-6 CLOSED)
- [x] services/memory_maintenance.py (F4 consolidate fail-closed; per-chat кап `deep_sleep_max_paradigms_per_run` +
      `deep_sleep_top_k` — S10.21-1 CLOSED; Low S10.21-8 парадигмы без vec — ОТКРЫТО, вне скоупа фиксов)
- [x] services/config_migrations.py + services/prompt_migrations.py + `*_prompts.py` (F3/F4: PREV_*_R1021 + ROLLBACK,
      идемпотентные миграции порогов, docs-канон синхронен — чисто)
- [x] services/prompt_style_blocks.py (F3: блоки A/B, R46-4 без «уже проверял» — чисто)
- [x] config/settings.py + bot.py + .env.example (env-only ClassVar, порядок роутеров не тронут, Δ каталога = 0 — чисто)
- [x] web/app.js + web/index.html + web/api/chat_lore.py + tests/js/round1021_ui_audit_test.js (F6: `_syntheticGroup` в
      methods, `positionScopePanel`; регресс зелёный — чисто)
- [x] tools/ui_audit_round1021.py + UI_AUDIT_REPORT.md + tools/_ui_audit_raw.json (F6: реальный Playwright-рендер;
      S10.21-9 CLOSED — `tools/_ui_audit_shots/` и `tools/_ui_audit_raw.json` в `.gitignore`, `git check-ignore -v` OK)
- [x] tests/test_*_round1021.py + тесты канонов/промптов — 217 целевых passed; фиксы S10.21-2/-3/-6/-7 подтверждены
      7 ad-hoc пробами @Scanner (своих регресс-тестов у этих 4 веток нет — новый Low N10.21-1)
- **СВОДКА RE-AUDIT: Critical 0 / High 0 / Medium 0 (open).** Low: S10.21-8 (вне скоупа) + N10.21-1 (тест-покрытие) +
  N10.21-2 (бинарный `roster_incomplete`). Info 4. Вердикт: **раунд передаётся на Merge/деплой**; обязательных
  возвратов @Builder нет. Отчёт: `round1021_scanner_audit.md` §«Re-audit после пост-скан фиксов».

## Round 10.20 scan + re-audit (T-1915, 2026-09-16) — all scanned/closed (diff-based, HEAD 2f3e1f0 + worktree)
- [x] web/index.html + web/app.js (S10.20-1 High CLOSED: `<sticky-save>` в ветке `currentTabIsConfig`
      (:704) + модалка «Модулей» (:967) + «Доступы» (:1549) + футер досье (:2694); S10.20-6 CLOSED:
      `saveModalEdits` не снапшотит при ошибках, `stickyFailed`; S10.20-10 CLOSED: длинная история → plain)
- [x] services/tool_router.py (S10.20-2 `resolve_lore_compiler_flag`; S10.20-3 `_dig_json_payload`
      с валидным JSON; S10.20-4 `lore_verbatim_instruction`/`strip_lore_html`)
- [x] services/factcheck_service.py (S10.20-2 per-chat флаг; S10.20-4 без «ДОСЛОВНО» + strip HTML)
- [x] services/smartmodule_utils.py (S10.20-4/10/11: `strip_lore_html`, комментарий sanitize)
- [x] services/lore_compiler_service.py (S10.20-5 `last_ts` по включённым диалогам; S10.20-8/M1
      header-safe `_trim_pairs`; S10.20-14 tz `_date`; S10.20-15 `_empty_dense`)
- [x] services/status_service.py (S10.20-7 per-chat cap приоритетнее acct + `context.source`)
- [x] services/database.py (M2 докстринг `_LORE_NODE_SCAN_LIMIT`; M3 `dossier_feed` пул `limit*20`;
      S10.20-13 `initialize_existing` валидация; S10.20-16 докстринг)
- [x] services/canonical_context.py (S10.20-9 паттерны 6-кортежа `direct_rag`/`legacy_rag`)
- [x] tests/test_scanner_fixes_round1020.py + tests/test_webapp_round1020_ui.py +
      tests/js/round1020_ui_test.js (панель в каждой ветке, S10.20-6)
- **Принято обоснованно (не закрываем):** S10.20-12 (Time Injection/prompt-cache — ADR-1020-3),
  S10.20-17 (RBAC-паритет `persona_dossier_overrides` — вне скоупа).
- **СВОДКА: Critical 0 / High 0 / Medium 0 / Low 0 (open) / Info 5.** Новых находок нет.
  Валидатор: pytest **6546 passed / 0 failed** (87.49 s); `node --check web/app.js` OK;
  `routing_test.js`/`round1020_ui_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` exit 0. **ВЕРДИКТ: «нет Critical/High»** → @Orchestrator, шаг 7.

## Round 10.18 БАТЧ 4 (финал эпика) scan (2026-09-15) — all scanned (diff-based: F5 `metafact-penalty-extractor-prompt` + F6 `role-matrix-settings-actualization`, HEAD 118a03c + worktree)
- [x] services/graph_stoplist.py (F5: `METAFACT_PENALTY_IMPORTANCE=1`, `is_metafact_stopword`; списки centers≠penalty — чисто)
- [x] services/database.py (F5: `insert_graph_fact` += `subject/object` + централизованный срез `imp=min(imp,1)`;
      `f.importance` в SELECT `search_graph_facts_fts`/`get_graph_fact_records`. Находка: S10.18-35)
- [x] services/summary_memory.py (F5: `PREV_FACT_EXTRACT_PROMPT` байт-в-байт + аддитивный канон (AST-проба);
      `_importance_factor` в FTS+KNN ветках `_search_graph_facts` (взаимоисключающие → нет двойного применения); S10.18-37)
- [x] services/param_catalog.py (F6: `NAV_*`/`NAV_TITLES`/`NAV_ORDER`/`TAB_NAV`/`tab_nav`, `CONFIG_TAB_TITLES[PERMsoc]`=«PERMsoc»; Δ=0)
- [x] web/api/access.py (`param_permissions_list` += `nav/nav_title/nav_order`, R16; 403/форма прав не изменены)
- [x] web/app.js + web/index.html (F6: `matrixSections` по nav, `NAV_GROUP_ORDER/TITLES` — parity-тест, вложенный шаблон, «Прочее»; S10.18-36)
- [x] tests/test_metafact_penalty_round1018.py (новый: канон-байты, стоп-листы, срез (обе стороны/нормализация/явный importance),
      memorise-путь, поведенческий гейт Сна, RAG FTS/KNN/золотые, границы множителя) + test_frontend_tab_mapping/test_webapp_api
- **Открыто (Батч 4):**
  - [ ] **S10.18-35 [low, new]** F5-срез покрывает только memorise-путь; эпи-мерж (`memory_maintenance.py:250-258`)
        ре-вычисляет importance от origin → слитый мета-факт теряет пенальти (imp 1→4) → прокинуть пенальти в merge.
  - Info: S10.18-36 (spec §3.1 «3 nav» vs фактические 4 группы с «Прочее» — синхронизировать с ADR D4),
    S10.18-37 (F5-множитель меняет RAG-порядок всех чатов — живая проверка), S10.18-38 (сводка остатков эпика).
- **СВОДКА ЭПИКА 10.18 (F1–F7, батчи 1–4): Critical 0 / High 0 / Medium 1 (S10.18-30) / Low 2 (S10.18-29, -35) / Info 11.**
  **Вердикт: эпик готов к @Reviewer/@PM (T-1749/T-1757) → Merge/архивация → деплой @DevOps**; до деплоя желательно
  закрыть S10.18-30 (перф ×2-фазы `graph_snapshot`).
- Валидатор @Scanner (независимо): pytest **6137 passed / 0 failed** (67.8 c); `node --check web/app.js` OK;
  `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19;
  SQLite v10; nav-интроспекция 161/180/65/5 = 411.

## Round 10.18 БАТЧ 3 scan (2026-09-15) — all scanned (diff-based: F3 `graph-density-scoring-stoplist` + F4 `graph-physics-stabilization`, HEAD 118a03c + worktree)
- [x] services/database.py (F3: миграция v10 `_migrate_edges_fact_id_v10` (guard/индекс вне `_SCHEMA_SQL`/user_version=10),
      `graph_snapshot` (score=Σ importance, bound-pool, STOP_LIST центров, ×2, cap 800/2400, сироты/truncated),
      `_belief_participation_blob`, `upsert_edge(fact_id, commit)`, `insert_graph_fact(commit)`. Находки: S10.18-30/-32/-33)
- [x] services/graph_stoplist.py (новый: centers/penalty списки, normalize_token/predicates — чисто; S10.18-31)
- [x] services/summary_memory.py (атомарность fact+edge: commit=False ×2 + единый commit + rollback; cron-путь NULL)
- [x] web/api/memory_agi.py (лимиты 800/2400/150; `limits` аддитивно; manual-маркеры/`_badge_active_until`; S10.18-29)
- [x] web/app.js (F4: physics 150 + `once`-авто-отключение, guard по тождеству, reducedMotion; S10.18-22/-26 закрыты)
- [x] tests/test_graph_scoring_round1018.py (новый: миграция/fresh/legacy/FTS, скоринг/degree, STOP_LIST, ×2/substring/multiword,
      fact_id-путь/COALESCE/атомарность, плотность 500–800, константы) + 11 обновлённых тестов (user_version 9→10)
- **Закрыто в Батче 3:** S10.18-21 [medium] (предгейт `_deep_tick` + `has_any_override` удалены), S10.18-22 [medium]
  (restore-polling только на «Статусе» + `closeModule`), S10.18-23 [low] (manual-маркеры воркера), S10.18-24 [low]
  (`_FALLBACK_MIN_IMPORTANCE_SUM=6`), S10.18-25 [low] (`0` = «без лимита»), S10.18-26 [info] (ретраи снимаются).
- **Открыто (Батч 3):**
  - [ ] **S10.18-30 [medium, new]** перф ×2-фазы `graph_snapshot` (`database.py:3796-3833`): замер — полный ≈238 мс
        (15k рёбер/200 beliefs), SQL ≈59 мс, ×2-цикл ≈176 мс; линейно растёт с belief-блобом (≈2.3 с при 4000, ≈6.5 с при 10 000);
        выполняется в event loop на каждый `/api/memory/graph` (15с / 5с при manual) → заменить на O(1)-множество токенов/кэш.
  - [ ] **S10.18-29 [low, new]** `run_once(deep=False)` не ставит `_manual_deep_until` → `deep_sleep.manual=False` и
        `active_until=None` во время deep-фазы manual-каскада вне окна; TTL 900с не связан с локами.
  - Info (open): S10.18-31 (варианты STOP_LIST с дефисом/пробелом), S10.18-32 (self-loop ×2 в degree/score),
    S10.18-33 (`upsert_edge` при отсутствии узла → факт без ребра), S10.18-34 (S10.18-18/-19/-20 из Батча 1),
    плюс S10.18-12 (nostalgia backlog T-1764), S10.18-13 (SSH-фрагмент, вне батча).
  - **ВЕРДИКТ: БАТЧ 4 (F5 экстрактор + F6 матрица ролей) РАЗРЕШЁН** (0 Critical / 0 High).
- Валидатор @Scanner (независимо): pytest **6104 passed / 0 failed** (75.4 c); `node --check web/app.js` OK;
  `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19;
  SQLite v10 (миграция проверена пробой fresh/legacy/idempotent).

## Round 10.18 БАТЧ 2 scan (2026-09-15) — all scanned (diff-based: F2 `sleep-manual-cascade-badges`, HEAD 118a03c + worktree)
- [x] services/dream_worker.py (F2: manual-обход gate (`gate_override`)/бюджетов (`budget_override`)/near-limit/window;
      `_dream_budget_ok`/`_deep_budget_ok(manual=True)` — 4 независимых `consume`, verdict игнорируется; каскад
      `_maybe_deep_after_sleep(manual, only_chat)` + `_MANUAL_DEEP_CASCADE_MAX=1`; `_deep_result`; `_deep_fixed_possible`;
      `_run_persona_traits_once` reason-коды. Находки: S10.18-21/-23/-24/-25/-27)
- [x] services/config_migrations.py (новый; `migrate_dream_thresholds`: идемпотентность/кастом/PG down — чисто)
- [x] config/settings.py (пороги 2/8/2/10/60/300000/10; DREAM/DEEP_ENABLED оставлены False — S10.18-28)
- [x] bot.py (вызов `migrate_dream_thresholds` после `migrate_prompt_canons`; маркер BetterStack без `last4`)
- [x] web/api/memory_agi.py (`_badge_active_until`; `dream/deep_sleep.manual`; `effective`/`source` — S10.18-23)
- [x] web/app.js (S10.17-2 закрыт; оптимистичная `active`; `_retryCognition`; `restartCognitionPolling`/restore — S10.18-22/-26)
- [x] services/param_catalog.py (тексты порогов/DREAM_ENABLED; Δ=0) + services/feature_gates.py (`_master_fallback_default` — S10.18-15 closed)
- [x] services/chat_params.py (`has_any_override`/`note_overrides`/`_override_keys_seen` — S10.18-21)
- [x] tests/* (новый `test_sleep_manual_cascade_round1018.py` + deep_sleep/dream_worker/webapp1015/smoke1016/fallback1015/persona_traits/chat_params/js-routing)
- **Закрыто в Батче 2:** S10.18-15 [medium] (`settings.DREAM_ENABLED`-дефолт), S10.18-16 [low] (мёртвые sync-хелперы), S10.18-17 [low] (`_deep_fixed_possible`).
- **Открыто (Батч 2):**
  - [ ] **S10.18-21 [medium, new]** предгейт `_deep_tick` (`dream_worker.py:1282-1333`, `chat_params.py:150-183`) видит
        только прогретый кэш → per-chat `trigger='fixed'` молча пропускается на cold-start/после NOTIFY (откат R10.18-2).
  - [ ] **S10.18-22 [medium, new]** `_restoreCognitionPolling` (`app.js:5440-5463`, `closeModule:2371-2373`) стартует 15с
        без гейта `activeTab` и не снимается при закрытии модалки → polling вне «Статуса» бессрочно (JS-тест фиксирует).
  - [ ] **S10.18-23 [low, new]** `manual = running && !in_window` (`memory_agi.py:590-601`) — авто-тик вне окна помечается
        «ручным»; `active_until` 900с для него.
  - [ ] **S10.18-24 [low, new]** дефолты 2/8 == fallback-константы (`dream_worker.py:168-170`) → F3-fallback no-op.
  - [ ] **S10.18-25 [low, new]** `0` как per-chat лимит противоречив (`dream_worker.py:723-733`).
  - Info: S10.18-26 (`_retryCognition` без очистки), S10.18-27 (manual deep без кап/cooldown — принято),
    S10.18-28 (`DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` False; T-1713/T-1724/T-1725/T-1726/T-1772 открыты);
    плюс из Батча 1: S10.18-12 (nostalgia backlog T-1764), S10.18-13 (SSH-фрагмент R10.18-12, вне батча),
    S10.18-18…-20.
  - **ВЕРДИКТ: БАТЧ 3 (F3 граф + миграция v10) РАЗРЕШЁН** (0 Critical / 0 High).
- Валидатор @Scanner (независимо): pytest **6083 passed / 0 failed** (69.6 c); `node --check web/app.js` OK;
  `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19.

## Round 10.18 scan (2026-09-15, БАТЧ 1/3) — all scanned (diff-based: F7 settings-worker-sync + F1 betterstack-us-region-401, HEAD 118a03c + worktree)
- [x] services/worker_settings.py (F7: `resolve_setting`/`_with_source`/`_cached`/`setting_source`; сентинел `hot.get(key,_SENTINEL)`
      проходит `_coerce` без изменений — интроспекция `_cast_to_type`; каст == `chat_params._resolve_from_root`; fail-open)
- [x] services/dream_worker.py (F7: `_key_for`/`_window_open_for`/`_daily_limit_for`/`_budget_reason_for`; `start()` регистрирует
      джобы ВСЕГДА; `_maybe_deep_after_sleep(…, manual)`; gate-fallback per-chat. Находки: S10.18-1…-5)
- [x] services/feature_gates.py (F7: `_explicit_flag_value` + `fallback`; без fallback поведение прежних вызовов не изменилось — grep 5 callers)
- [x] services/chat_params.py (`invalidate_chat_from_notify` — fail-open) + services/chat_params_notify.py (LISTEN на отдельном
      `asyncpg.connect` + backoff + закрытие conn; `stop()` не вызывается — S10.18-7; untracked tasks — S10.18-11)
- [x] services/betterstack_handler.py (F1: host обязателен, `DEFAULT_HOST=""`, `extract_sentry_public_key`,
      `token_equals_sentry_public_key`, `_HINT_401`; S10.18-8 доки)
- [x] bot.py (F1 attach/skip-маркеры + last4; F7 `_start_chat_params_listener` + cancel на shutdown; stale-коммент :565)
- [x] services/param_catalog.py (`BETTERSTACK_HOST` в `_INFRA_ENV_ONLY`, REGISTRY 436)
- [x] web/api/memory_agi.py (chat_id-резолв + аддитивный `source`; S10.18-3 kill-switch не учитывается)
- [x] web/index.html (hint-ссылка на `#/ai/memory` — маршрут существует, TAB_RULES не расширен)
- [x] scripts/betterstack_host_token_probe.py + tests/test_betterstack_probe.py (матrix host×token, dry-run, R17-маскирование)
- [x] tests/* (settings_worker_sync_round1018, dream_worker, betterstack_handler, monitoring_smoke, param_catalog, 12 пин-тестов каталога)
- [x] plans/* (spec/adr/tasks F1+F7, backlog 10.18, ARCHITECTURE/README — drift S10.18-8/-9)
- **ЗАКРЫТО @Builder (10.18, Батч 1):**
  - [x] **S10.18-1 [high]** per-chat суточные лимиты Сна vs глобальные счётчики — `count_dream_log`/`sum_dream_log_tokens`
        получили `chat_id`; `_process_chat` считает расход по чату; регресс-тест `TestPerChatBudget`.
  - [x] **S10.18-2 [medium]** per-chat `deep_sleep_trigger`/`hour` в `_deep_tick` (+`_deep_candidate_chat_ids`); тесты.
  - [x] **S10.18-3 [medium]** статусы используют тот же fallback, что воркер (`feature_gates.master_fallback`); `cognition`
        отдаёт `dream.effective`, `active` по нему; тесты `TestStatusMatchesWorkerBehavior`.
  - [x] **S10.18-4 [medium]** decay гейтится глобальным master Сна (`TestDecayGatedByDreamMaster`).
  - [x] **S10.18-5 [medium]** manual-каскад по целевому чату + кап (`TestManualDeepCascade`).
  - [x] **S10.18-6 [medium]** нет `BETTERSTACK_HOST` → ERROR «логи НЕ отправляются»; тесты обновлены.
  - [x] S10.18-7…-11 [low] — `stop()` вызывается в `on_shutdown`; сильные ссылки на `create_task` в `_on_notify`; stale-доки
        (bot.py/ARCHITECTURE/README) синхронизированы; спека F1 §9 Q4 ↔ T-1706 и docstring `mask`; изоляция reload
        `config.settings` в тесте (restore `settings_mod.settings` + pop `bot` в `finally`).
  - [x] Гигиена: `test_tool_download_quality_round1017` ищет ADR в `plans/archive/`.
  - Info: S10.18-12 (Nostalgia backlog + задача есть), S10.18-13 (SSH-фрагмент, R10.18-12 — вне батча), S10.18-14 (инварианты целы).
- **⏱ Итерация 2 @Scanner (повторный аудит, 15.09.2026) — CLOSED S10.18-1…-11, -14 (11 закрыто); OPEN:**
  - [x] **S10.18-15 [medium, new]** `services/feature_gates.py:55-72` — `master_fallback` default `False` ≠
        `settings.DREAM_ENABLED`: env `DREAM_ENABLED=true` + нет DB-ключа `memory.dream_enabled` → воркер ON, статус
        гейтов/`cognition.effective` OFF (воспроизведено скриптом). Фикс — default из `settings`.
        **CLOSED (fix @Builder, итерация 3):** `_master_fallback_default("dream")=settings.DREAM_ENABLED`; тесты
        `test_master_fallback_default_matches_worker_env_on/_off`.
  - [x] **S10.18-16 [low, new]** `services/dream_worker.py:753,766,784-793` — мёртвые sync-хелперы
        `_window_open`/`_daily_limit`/`_budget_reason` (0 вызовов в проде и тестах) → удалить/deprecate.
        **CLOSED (fix @Builder, итерация 3):** удалены; `_key()` сохранён.
  - [x] **S10.18-17 [low, new]** `services/dream_worker.py:1205-1230` — `_deep_tick` делает `get_dream_candidate_chats`
        + N per-chat resolve каждый тик (60 мин) даже без `fixed`-чатов (раньше ранний return без I/O) → дешёвый предгейт.
        **CLOSED (fix @Builder, итерация 3):** `_deep_fixed_possible()` + `ChatParamsCache.has_any_override`; тесты
        `test_deep_tick_skips_candidate_sql_when_disabled` / `test_deep_tick_proceeds_when_per_chat_override`.
  - Info (open): S10.18-12 (Nostalgia/backlog T-1764), S10.18-13 (SSH-фрагмент, R10.18-12, вне батча),
    S10.18-18 (`?deep=1` без капа — осознанно), S10.18-19 (`tokens_per_day` без фильтра `kind` — pre-existing),
    S10.18-20 (`previous` kill-switch = effective — семантика поля).
  - **ВЕРДИКТ итерации 2: БАТЧ 2 (F2) РАЗРЕШЁН** (0 Critical / 0 High).
- Валидатор @Builder (итерация 3): pytest **6057 passed / 0 failed**; `node --check web/app.js` clean; `JS-UNIT-OK`;
  `VUE-MOUNT-OK`; `git diff --check` clean; каталог-интроспекция 436/406/411/90/88/19; SQLite v9.
- Валидатор @Builder (итерация 1): pytest **6052 passed / 0 failed**; `node --check web/app.js` clean; `JS-UNIT-OK`; `VUE-MOUNT-OK`;
  `git diff --check` clean; каталог-интроспекция 436/406/411/90/88/19; SQLite v9; `logtail`-импортов нет.
- Валидатор @Scanner (независимо): pytest **6052 passed / 0 failed** (75.6 c); целевые 10.18 — 121 passed;
  `git ls-files` подтверждает трекинг архивного `spec.md` с фрагментом пароля (S10.18-13).

## Round 10.17 scan (2026-09-14) — all scanned (diff-based, 5 фич F1–F5, HEAD 772f192 + worktree)
- [x] services/tool_router.py (F2: `_download_media` probe→меню→`needs_quality`; `_download_now` direct/явное
      качество/bounded fallback; `store/peek/pop_tool_download_pending` TTL 600; `_quality_arg`; R17-логи без URL)
- [x] handlers/video_download.py (F2: callback `tdq:` c валидацией высоты до consume, busy без потери pending,
      chat_action; Fast-Track-меню делегировано в `services/media_send`; F1 host-only лог в `handlers/menu.py`)
- [x] services/media_send.py (F2: единый `QUALITY_ROW_SIZE`/`build_quality_keyboard`/`quality_menu_text`/`send_quality_menu`)
- [x] services/tool_schemas.py (F2: опциональный `quality` enum `QUALITY_ENUM`)
- [x] tools/video_downloader.py (F2: `QUALITY_ENUM` = `("max",)+_ALLOWED_HEIGHTS`)
- [x] web/app.py (F1: `_startup_diag` host-only; HEAD `/web/`,`/index.html`; GET/HEAD `/healthz`)
- [x] web/app.js (F3: `fmtCountdown`; `dreamPhaseBadge`/`deepPhaseBadge` — остаток/до, ветка «выключен» удалена)
- [x] web/api/avatars.py (F5: `_log_bot_api_failure` + 6 сайтов — ожидаемое DEBUG, транзиент WARNING без кэша,
      generic WARNING с трейсом)
- [x] tests/* (F1 `test_webapp_dns_round1017`, F2 `test_tool_download_quality_round1017`,
      F3 `test_webapp_round1017_sleep` + JS, F5 `test_avatars_round1017`; обновлены регресс-маркеры 1015/1016)
- [x] plans/README/ARCHITECTURE/MEMORY/backlog/archive (F4 CANCELLED, brotli-WONTFIX, SUPERSEDE ADR-1016-1)
- **Открыто (не блокеры шага 7; 0 Critical / 0 High / 1 Medium / 2 Low / 3 Info):**
  - [ ] **S10.17-1 [medium]** `plans/archive/security-rotation-finalize-round1016/spec.md:3,72,79-83` —
        архивная спека без CANCELLED-баннера, §8 «ротация обязательна в любом случае» (docs-only).
  - [ ] **S10.17-2 [low]** `web/app.js:1216-1247` — `cognition==null` → «Сон через —» vs spec §3.4 «—».
  - [ ] **S10.17-3 [low]** доки-счётчики: `tool-download-quality/spec.md:245`, `sleep-badge-countdown/spec.md:125` (5951/5985).
  - Info: S10.17-4 (tool env-preflight), S10.17-5 (callback без hot-гейта), S10.17-6 (`/healthz` version — принято).
- Валидатор: pytest **6007 passed**/0 fail (79.62 c); `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`;
  `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0. Инварианты: R17/R16, роутеры `bot.py`,
  `media/`/`.env`, каталог 435/406/411/90/88/19, tool-set 7, лимиты 4/2, PREV/`PROMPT_MIGRATIONS`, SQLite v9 — целы.

## Round 10.16 scan (2026-09-14) — all scanned (diff-based, 5 фич F1–F5)
- [x] tools/video_downloader.py (F1: `DownloadError.reason`+`default_reason` подклассов,
      `download(url, quality=None)`, `_normalize_quality` None/auto/best/max/direct→`max`+диапазон 144…4320,
      `download_env_summary`/`log_download_env_once`, R17-лог-сайты без URL)
- [x] config/settings.py (F1: `get_ytdlp_pot_provider` — единый POT-источник, env-only, каталог-Δ=0)
- [x] handlers/video_download.py (F1: горячий гейт `flags.download_enabled`, `download_available`,
      `_download_without_menu` bounded fallback, `_probe_error_phrase`/`_fallback_phrases`, reason-логи)
- [x] services/tool_router.py (F1: `download(url)` без `"direct"`, DownloadError→`status:"error"` R17)
- [x] bot.py (F1/F3: только снятие startup-гейта вокруг 4e — порядок роутеров не изменён)
- [x] handlers/direct_chat.py (F3: `_functional_module_active` + `download_available`)
- [x] services/info_service.py + services/config_cache.py + handlers/info.py + web/api/routes.py + web/app.js
      (F2: canon_version/normalize_canon/KNOWN_INFO_SNAPSHOTS, force-reset+prev_html, PG-only save_text,
      drift-preserve, UI resetInfoCanon)
- [x] services/database.py + dream_worker.py + summary_memory.py + command_prefix.py
      (F3 FIX: S10.13-6b archived_beliefs-фильтр, S10.13-13 единый `parse_belief_meta`,
      R10.15-10 `split_prefix_anywhere(url_before)`)
- [x] handlers/youtube.py + handlers/web.py (F3: `_has_video_target`/link-first; residual R17-лог YouTube)
- [x] web/index.html + web/static/app.css + telegram-init.js + vendor/* + tailwind.config.js + web/app.py
      (F4: self-host, CSP `unsafe-eval`, `/static/app.css` с `?v=`)
- [x] plans/features/*-round1016/ + plans/reports/round10.16_*.md + ssh-rotation-checklist.md (F5: docs/scan)
- [x] tests/* (new: test_download_round1016, test_guide_delivery_round1016, test_smoke_round1016_* ×7,
      tests/js/vue_mount_test.js; обновлены маркерные/каталог/JS)
- **Итерация 2 (после фиксов @Builder) — закрыто:**
  - [x] **S10.16-1 [high→closed]** R17: youtube-лог-сайты — только `error=<Class> reason=<reason>`
        (`handlers/youtube.py:697-699,705-707`); caplog-тест `test_download_round1016.py:711-748` покрывает путь.
  - [x] **S10.16-2 [medium→closed]** бэкап канона: `config_cache.py:292,317-323` + `info_service.py:285-291`.
  - [x] **S10.16-3 [low→closed]** `download_available()` задокументирован (`handlers/video_download.py:126-136`).
  - [x] **S10.16-4 [low→closed]** touch после успешного старта (`video_download.py:462-468`).
  - [x] **S10.16-5 [low→closed]** мёртвый `probe_unavailable` удалён (`video_download.py:415-426`).
  - [x] **S10.16-6 [low→closed]** `is_platform_url` публичный (`tools/video_downloader.py:235`).
  - [x] **S10.16-7 [low→closed]** native media — только класс (`video_download.py:698-701`).
  - [x] **S10.16-8 [low→closed]** аватар same-origin прокси (`web/app.js:1564-1590`), CSP OK.
  - [ ] **S10.16-9 [low, latent]** 4 raise-сайта ещё интерполируют `{exc}` (`video_downloader.py:767,772,899,904`),
        `:835` — тело cobalt до 500 символов; лог-пути их не печатают (утечки нет) — hardening.
- Валидатор итерации 2: pytest **5936 passed**/0 fail (69.4 c), `node --check web/app.js` OK, `routing_test.js`
  JS-UNIT-OK, `vue_mount_test.js` VUE-MOUNT-OK, `git diff --check` OK. Инварианты: R17/R16, роутеры `bot.py`,
  `media/`/`.env`, каталог 435/406/411/90/88/19, tool-set 7, PREV/`PROMPT_MIGRATIONS`, SQLite v9 — целы.
  **Открыто: 0 Critical / 0 High / 0 Medium / 1 Low (latent).**

## Round 10.15 scan (2026-09-14) — all scanned (diff-based, 9 фич F1–F9)
- [x] services/command_registry.py (NEW: канон 17 + `чекап`/`фактчек` bare, `_HEAD`/`_TAIL` word-boundaries,
      `matches`/`group_of`/`matches_group`/`has_trigger_word`)
- [x] services/command_prefix.py (NEW: `active_name`/`command_prefix_tokens`/`split_prefix`/`name_mentioned`/
      `functional_group`/`is_functional_command`; префикс якорён к `^`)
- [x] services/media_send.py (NEW: общий `send_media`, фолбэк video→document, R17-лог)
- [x] handlers/search.py / youtube.py / web.py / checkup.py / video_download.py (F6: снятие префикса,
      триггеры из реестра, консьюм без цели `COMMAND_NO_TARGET_PHRASES`)
- [x] handlers/direct_chat.py (F6: `name_mentioned`, отключение ботвордов при имени, `_FUNCTIONAL_FLAGS`/
      `_functional_module_active`, yield UNHANDLED, имя в `_parse_memory_command`)
- [x] bot.py (F8 DI: `youtube_service`/`checkup_service`/`_shared_video_downloader` → `ToolDeps(video/downloader/
      db/health)`; порядок роутеров не тронут)
- [x] services/tool_schemas.py (F8/F9: +`summarize_video`/`download_media`/`get_bot_health`/`get_recent_history`, итого 7)
- [x] services/tool_router.py (F8: `_summarize_video`/`_download_media` (успех только после `send_media`)/
      `_get_bot_health`; F9: `_get_recent_history` depth/query + `_history_lines`; `ToolHealthDeps`)
- [x] services/direct_chat_service.py (F8: `ToolContext(bot/reply_to_message_id/user_id)`)
- [x] services/database.py (F1: `graph_snapshot` CTE Degree Centrality + 1-hop + сироты + оба конца рёбер)
- [x] web/api/memory_agi.py (F1 `GRAPH_SEED_NODES=50`; F5 `_in_hour_window`/`_local_hour` + `active`/`active_until`,
      H1-гейт `enabled`)
- [x] web/app.js / web/index.html (F2 barnesHut + поиск по графу; F5 релокация метрик, `intel-header`, бейджи
      «через/до»/«выключен», удалён `loadCognitionStats`)
- [x] services/dream_worker.py (F3 `_sleep_fallback_active` 2/8, детект раз на тик, `[Sleep]` WARNING/INFO)
- [x] services/nostalgia_prompts.py / nostalgia_worker.py / config/settings.py / param_catalog.py (F4: окно 10,
      лор/мемы капы 600/10/120, PREV-слепок, промпт-ревамп)
- [x] services/info_service.py / config_cache.py / info_text.md / plans/docs/intelligence_user_guide.md (F7 канон +
      идемпотентная миграция по `PREV_DEFAULT_INFO_TEXT`)
- [x] tests/* (8 новых файлов + обновления), tests/conftest.py (сброс persona-name кэша)
- [x] plans/features/*-round1015/ (9 спек + ADR-1015-1/-2/-3 + tasks), plans/reports/round10.15_scanner_audit.md
### Round 10.15 — повторный аудит (итерация 2, 2026-09-14)
- [x] **R10.15-1 [medium] closed** — `command_prefix.split_prefix_anywhere():61-77`; link-first в
      `youtube.py:206-215`/`web.py:97-106` (URL строго до обращения + `matches_group` остатка); тесты
      `test_command_registry_round1015.py:153-161,225-242`.
- [x] **R10.15-2 [medium] closed** — `tool_router.py:623` гейт `flags.checkup_enabled` до `fetch()`/`checkup()`
      (тест `test_tool_calling_round1015.py:438-455`).
- [x] **R10.15-3 [medium] closed** — обычная речь без URL → `UNHANDLED` (`youtube.py:200-205`, `web.py:91-96`;
      тесты `:249-279`); residual R10.15-11.
- [x] **R10.15-5 [low] closed** — `memory_agi.py:497-501` независимый `deep_active_until`.
- [x] **R10.15-6 [low] closed** — `tool_router.py:657-661` fallback `ctx.query` (тест
      `test_recent_history_tool_round1015.py:134-148`).
- [x] **R10.15-7 [low] closed** — мёртвые `is_functional_command`/`command_registry.matches` удалены (grep 0).
- [x] **R10.15-8 [low] closed** — `database.py:3651-3652` seed join `nodes`+`nwhere` (тест
      `test_webapp_round1015_graph.py:105-118`).
- [x] **R10.15-9 [low] closed** — `tool_router.py:576-591` общий кулдаун 4e через `get_download_cooldown`
      (`handlers/video_download.py:116-122`); тесты `test_tool_calling_round1015.py:289-335`.
- **Открыто (не блокеры шага 7; 0 Critical / 0 High / 0 Medium / 3 Low / 3 Info):**
  - [ ] **R10.15-4 [low]** F6 M2-остаток: yield по hot-флагу vs startup-регистрация 4e (`direct_chat.py:461-463`,
        `bot.py:747-753`) — осознанный follow-up.
  - [ ] **R10.15-10 [low]** link-first привязан к первому вхождению имени (`command_prefix.py:71-77`;
        `youtube.py:206-215`; `web.py:97-106`) — узкий false-negative.
  - [ ] **R10.15-11 [low]** «триггер anywhere + любой http-URL» консьюмит обычную речь с не-media ссылкой
        (`youtube.py:203`; `web.py:94`) — residual R10.15-3.
  - Info: R17-долг `plans/current_task.md:62-65` (вне диффа).
- Валидатор итерации 2: pytest **5774 passed**/0 fail, `node --check web/app.js` clean, `routing_test.js`
  JS-UNIT-OK, `git diff --check` OK. Инварианты: R17/R16, роутеры `bot.py`, `media/`/`.env`, каталог
  435/406/411/90/88/19, tool-set 7, PREV байт-идентичен, `PROMPT_MIGRATIONS` не тронут — целы.

## Round 10.14 scan (2026-09-13) — all scanned (diff-based, 8 фич F1–F8)
- [x] services/database.py (F1 SQLite v8→v9: `_migrate_self_origin_v9` rebuild 16 колонок/id 1:1,
      guard + безусловный `user_version=9`, 5 индексов, origin-исключения self в list_new_confirmed/
      golden/live/dup/graph_stats, `include_self` в `search_graph_facts_fts`; `rule_importance` self=2)
- [x] services/bot_persona.py (NEW: scope-резолв per-chat→global→empty, prompt-блок + `_NO_AI_DISCLOSURE_BLOCK`,
      UPSERT/optimistic `updated_at`/`PersonaConflict`, traits cap/дедуп/FIFO, persona_state-метрики, name-cache)
- [x] services/self_reflection.py (NEW: LLM-экстрактор сути, роль `reflection`→фоллбэк main, fail-safe '', метрики)
- [x] services/summary_memory.py (`_origin_weight(bot_weight=…)`, `memorize_self_reply`, `include_self`
      через `_search/_knn/_vec*`+`_filter_vec_rows`, метка `[Источник: Я сам (Бот)]`, `_SELF_ECHO_INSTRUCTION`)
- [x] services/direct_chat_service.py (persona-хвост system prompt per-chat; self-aware ветка
      `_memorize_in_background` (query=bot_direct_reply + essence=bot_self_reply); анти-эхо ДО cap;
      `_reassign_fact_owners` изолирует self по origin; `include_self=True` только direct-RAG)
- [x] services/dream_worker.py / dream_prompts.py (F2 `_run_persona_traits_once` + `PERSONA_EVOLUTION_PROMPT`/
      `build_persona_user`/`parse_persona_traits`; гейт per-chat `flags.persona_enabled`, fail-open)
- [x] services/pg_db.py (F1 `persona_state` DDL+сид; F2 `personas`/`persona_traits` DDL, partial-unique,
      FK CASCADE, ALTER persona_state; идемпотентность)
- [x] services/permissions.py (`edit_persona` в ACTIONS_TREE/ACTION_IDS) — H2 закрыт
- [x] services/info_service.py + config_cache.py (F6 `content.intelligence_guide`, `GUIDE_SEED_FILE` абсолютный,
      идемпотентный сид) ; services/param_catalog.py (Δ +1 content, +1 limit, +2 flag, +3 models, +1 key)
- [x] services/status_service.py (R10.9-4 `invalidate_health_cache` по `models.*`/`keys.*`)
- [x] config/settings.py (+INTEL_REFLECTION_*×4, +GRAPH_FACT_WEIGHT_BOT/BOT_SELF_AWARENESS_ENABLED,
      +PERSONA_ENABLED, ClassVar SELF_ESSENCE_MAX_CHARS/PERSONA_TRAITS_MAX/PERSONA_TRAIT_MAX_CHARS)
- [x] web/api/routes.py (`GET/PUT/DELETE /api/persona`, `GET /api/persona/health`, `GET/POST /api/info/guide`,
      health-инвалидация в config/BYOK); web/api/memory_agi.py (fallback `bot_self_replies`)
- [x] web/app.js (F3 special-screen persona + ROUTE_*/canViewTab; F4 3-я лента + метрики + `fmtDayMonth`;
      F6 Markdown-гайд + fail-closed sanitize; F8 provider-блок `intel_reflection`; F5 scope-reset черновиков)
- [x] web/index.html (F3 карточка persona; F4 3-я лента + панель «Личность»; F6 гайд-блок; F7 порядок карточек;
      CSS `.guide-markdown`/`.cognition-ribbons 3`)
- [x] bot.py (только `await load_global_cache()` после `set_config_cache` — DI-порядок не тронут)
- [x] .env.example (+INTEL_REFLECTION_* плейсхолдеры, +GRAPH_FACT_WEIGHT_BOT/BOT_SELF_AWARENESS_ENABLED/PERSONA_ENABLED)
- [x] tests/* (new: test_graph_facts_origin_v9, test_bot_persona, test_persona_api, test_persona_prompt,
      test_self_reflection, test_self_reflection_provider_round1014, test_dream_persona_traits,
      test_help_guide_round1014, test_settings_persistence_round1014, test_webapp_round1014_ui; обновлены
      маркерные/каталог/JS) — pytest 5582/0, node --check OK, JS-UNIT-OK, git diff --check clean
- [x] plans/features/*-round1014/ (8 спек + ADR-1014-1/-2 + tasks), plans/reports/round10.14_scanner_audit.md
- **Открыто (Low, не блокеры, после итерации 2; 0 Critical / 0 High / 0 Medium / 2 Low / 2 Info):**
  **R10.14-4 [low]** `dynamic_traits` не фильтруются по chat_id (`routes.py:1461-1462`) — осознанно
  (traits = общий характер бота, F4). **R10.14-7 [low]** 12 leaked aiosqlite-соединений (pre-existing).
  **I10.14-1/2 [info]**: v7→v9-каскад без прямой фикстуры (safe по guard-анализу); FIFO-ротация трейтов глобальная.
- **Сквозной паттерн 10.14:** dedicated-API с собственным scope/RBAC сверять парой view↔edit;
  новые LLM-вызовы воркеров — всегда через worker_budget.

### Round 10.14 — повторный аудит (итерация 2, 2026-09-13)
- [x] Ре-верификация фиксов @Builder: **R10.14-1 (Medium) closed** — `routes.py:1365-1372`
      `_persona_has_edit_action`, `:1388-1399` `_persona_can_view` согласован с `_persona_can_edit`;
      `app.js:2820-2825` `canViewTab('persona')` → global-экран при `edit_persona`; тесты
      `test_persona_api.py:197-222` (view global/chat + GET/PUT consistency), `routing_test.js:190-195`;
      moderator/без прав по-прежнему 403 (`:193-195`, `:256-261`). **R10.14-2 (Medium) closed** —
      `dream_worker.py:1460` `_deep_budget_ok` до traits-LLM, `:1355-1368` кап учитывает `deep_traits`,
      `:1406-1415`/`:1475-1479` логирование токенов; тесты `test_dream_persona_traits.py:182-238`.
- [x] Low закрыты: R10.14-3 (`routes.py:1452-1460`, тест `:224-238`), R10.14-5 (док. `summary_memory.py:1771`),
      R10.14-6 (docstring 8→9 в 4 файлах).
- [x] Валидатор: pytest **5589 passed**/0 fail (60.58 s), `node --check web/app.js` OK,
      `routing_test.js` JS-UNIT-OK, `git diff --check` OK. Инварианты: R17/R16, роутеры `bot.py`,
      `media/`/`.env` не тронуты, REGISTRY 435/GROUPS 90/mapped 88/TAB_RULES 19, DOMPurify self-host,
      SQLite v9/PG DDL целы.
- Итог итерации 2: **0 Critical / 0 High / 0 Medium / 2 Low** открытых; вердикт — открытых
  Critical/High/Medium НЕТ.

## Round 10.13 scan (2026-09-13) — all scanned (diff-based, 8 фич F1–F8)
- [x] services/summary_memory.py (F1 `_fact_prefix`/`_stale_suffix`/4-кортежи RAG; F2 `_knn_graph_facts`
      архив+penalty+`_resurrect_resonant`, `graph_activation_facts`)
- [x] services/dream_worker.py (F2 decay/`_reinforce`/`_try_reanimate`; F3 packet/bridge/`_run_deep_*`/
      `_deep_tick`/`_deep_budget_ok`/`_write_paradigm`; роутер `_worker_llm`)
- [x] services/dream_prompts.py (PREV-слепок, правило 5, `order_dream_rows`, `build_bridge_user`,
      `parse_bridge_answer`, DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT)
- [x] services/database.py (F2 belief-хелперы + `list_recent_beliefs` status/kind; F3 deep-маркеры/
      `count_paradigms`; F8 `meme_exists`/`list_chat_memes`; F5 `graph_snapshot`/`graph_stats`;
      `search_graph_facts_fts(include_archived)`; `sum_dream_log_tokens(kind)`)
- [x] services/direct_chat_service.py (F5 `_PROCESS_ACCOUNTING`/`record_*`; F2 graph-activation hook;
      F8 persona-блоки [Факты]/[Мемы])
- [x] services/lore_worker.py (F8 `_classify_dossier*`/`_window_names`/`_canon`; F3 `_worker_llm` history)
- [x] services/dossier_prompts.py (NEW; канон + keyword fail-safe + parser + `format_dossier_block`)
- [x] services/lore_prompts.py / dream_prompts.py (PREV-слепки, ироническая заметка)
- [x] services/llm_client.py (`generate_worker`/`_worker_profile` — history/background, фоллбэк)
- [x] services/llm_probe.py (`_LLM_BLOCKS`/`_BLOCK_SAVED_KEY` intel_*, `_saved_api_key` фоллбэк)
- [x] services/memory_health.py (счётчики убеждений/парадигм)
- [x] services/nostalgia_worker.py (`_worker_llm` background)
- [x] services/log_ring.py (`ERROR+WARNING`)
- [x] services/status_service.py (`server.cpu_count`, `context`)
- [x] services/tool_router.py (dig: `include_archived`, единый RAG-рендер)
- [x] services/worker_budget.py (`WORKER_DEEP_SLEEP`, `allowed_workers` позиция -1)
- [x] config/settings.py (+INTEL_*×8, +RAG_STALE_AFTER_DAYS, BELIEF_*×6, DEEP_SLEEP_*×6, IRONY_FILTER_ENABLED;
      APP_VERSION 2.57.0)
- [x] services/param_catalog.py (Δ +22: F1/F2/F3/F4/F8; `_PG_ID_OVERRIDES`; select-widget DEEP_SLEEP_TRIGGER)
- [x] web/api/memory_agi.py (`cognition/status`, `graph`, `stats`, `timeline`, `deep-sleep`, `health`,
      `?deep=1`, beliefs status/kind)
- [x] web/api/routes.py (logs 422/=, docstring)
- [x] web/app.js (F4 2 provider-блока; F5 cognition-polling/graph/ленты/виджет; F6 EKG + logLevel watch)
- [x] web/index.html (F5 дашборд/виджет, F6 EKG + селектор логов; CSS)
- [x] web/static/vendor/vis-network/vis-network.min.js (NEW, self-host v9.1.9)
- [x] bot.py (DI `aliases=AliasResolver` в LoreWorker; router order не тронут)
- [x] .env.example (+INTEL_*, RAG_STALE_AFTER_DAYS, DEEP_SLEEP_*) — **нет** BELIEF_*/IRONY_FILTER (S10.13-12)
- [x] tests/* (new: test_belief_decay, test_deep_sleep, test_dossier_*, test_webapp_round1013[_f5]_ui;
      обновлены маркерные/каталог/JS) — pytest 5383/0, JS-UNIT-OK, node --check clean
- [x] plans/features/cognition-*-round1013/ (8 спек + ADR-1013-1/2/3), plans/docs/intelligence_user_guide.md,
      README.md, plans/MEMORY.md, plans/backlog.md (doc-only)
- [x] plans/reports/round10.13_scanner_audit.md — итог: **0 critical / 1 high / 4 medium / 9 low**
- **Открыто (follow-up, не блокеры после фикса high):** S10.13-1 [high] неэкранированный `target_user`
  в `_fact_prefix` (RAG-промпт); S10.13-2 deep-sleep cooldown/суточный кап обходятся на неуспешных
  прогонах (`deep_run` пишется только при written>0; кап суммирует только `deep_run`);
  S10.13-3 F2-decay архивирует F3-парадигмы (`list_confirmed_beliefs` без фильтра `type='paradigm'`);
  S10.13-4 реаниматор (`kind='skipped'/status='resurrected'`) не виден в `resurrections_total`/health/
  Timeline; S10.13-5 F5-ленты beliefs/paradigms без `chat_id`; S10.13-6 `graph_stats` facts без
  `status` и beliefs с парадигмами; S10.13-7 `or <default>` блокирует 0-значения; S10.13-8 deep-sleep TZ
  = SUMMARY_TIMEZONE (спека: WORKER_BUDGET_TZ); S10.13-9 Timeline lore = in-memory inject (спека:
  chat_lore_history); S10.13-10 probe не зеркалит runtime base/model-фолбэк; S10.13-11 LIKE-маркер
  парадигм хрупок; S10.13-12 `.env.example`/описание irony-флага; S10.13-13 три дубля парсера
  `belief_meta`; S10.13-14 граф может отдавать «висячие» рёбра.
  Из прошлых раундов: R10.12-1/-5, R10.12-2/-3/-4, R10.11-1…-6, R10.10-*, R10.9-*.

### Round 10.13 — повторный аудит (итерация 2, 2026-09-13)
- [x] Ре-верификация фиксов @Builder: S10.13-1 (High) closed — `summary_memory.py:723-728`
      `escape_xml_text`+схлопывание `\n\t`, рантайм `&lt;/RAG_Memory&gt;`, тест
      `tests/test_webapp_round1013_ui.py:63-84`; S10.13-2 closed (`dream_worker.py:1153-1156`,
      `_log_deep_skip:1373-1381`, `_deep_budget_ok:1329-1348`, `database.py:2088-2117`);
      S10.13-3 closed (`database.py:1932-1954`, тест `test_belief_decay.py:215-228`);
      S10.13-4 closed (`dream_worker.py:1019-1026`, `memory_health.py:80-82`,
      `memory_agi.py:313,548-553`); S10.13-5 closed (`web/app.js:4830-4835`).
- [x] Low: закрыты S10.13-7 (`_hot_number`), -8 (`_deep_tz_name`=WORKER_BUDGET_TZ),
      -10 (`llm_probe._intel_probe_fallback`), -12 (`.env.example` + описание флага).
- [x] Валидатор: pytest **5392 passed**/0 fail (60.75 s), `node --check web/app.js` clean,
      `routing_test.js` JS-UNIT-OK, `git diff --check` OK. Инварианты: 0 PG-DDL, SQLite v8,
      роутеры bot.py, REGISTRY 427/GROUPS 90/mapped 88/TAB_RULES 19, vis-network self-host.
- **Открыто (Low, не блокеры, итерация 2):** S10.13-9 Timeline-лор = in-memory inject
  (`memory_agi.py:596-604`); S10.13-11 хрупкий LIKE-маркер парадигм (`database.py:1941-1942`
  и др.); S10.13-13 три дубля парсера `belief_meta` (`database.py:1919-1930`,
  `dream_worker.py:857-869`, `summary_memory.py:70`); S10.13-14 «висячие» рёбра графа
  (`database.py:3538-3541`); **новый S10.13-6b** `archived_beliefs` без фильтра парадигм
  (`database.py:3590-3592`).
- Итог итерации 2: **0 Critical / 0 High / 0 Medium / 5 Low** открытых; вердикт — High
  открытых НЕТ.

## Round 10.12 scan (2026-09-13) — all scanned
- [x] config/settings.py (`LLM_BASE_URL` default → nano-gpt; +`EMBEDDING_BASE_URL`, +`EMBEDDING_API_KEY`,
      +`OPENROUTER_TRANSCRIBE_DISPLAY_NAME`; +`DEFAULT_KOSTIK_REPLIES`/`KOSTIK_REPLIES`/`KOSTIK_ENABLED`;
      Settings 372→377)
- [x] services/llm_client.py (`embed_base_url`/`embed_api_key` DI, `_embed_base_url`/`_embed_api_key`,
      `_current_embed_api_key`, `_post(base_url=…, channel='embed')`, отдельный `_embed_client`-кэш;
      chat-путь/ретраи/`EMBEDDING_FALLBACK_*` целы)
- [x] services/status_service.py (`emb_base`/`emb_key` из embed-ключей; `emb_main` без алиасинга `main_base`;
      `stt_openrouter` → `models.openrouter_transcribe_display_name`)
- [x] services/llm_probe.py (`_BLOCK_SAVED_KEY` primary-embed → `keys.embedding_api_key`; `_saved_api_key`
      фолбэк на `keys.llm_api_key`; Google-фоллбэки не затронуты) — инфо-нит по docstring (R10.12-2)
- [x] services/param_catalog.py (Δ +5: `models.embedding_base_url`, `models.openrouter_transcribe_display_name`,
      `keys.embedding_api_key`, `flags.kostik_enabled`, `reactions.kostik_replies` widget=list;
      `_REACTIONS` 6-элементные строки)
- [x] services/permsoc.py (`PermsocModule('kostik').sub_flag_key='flags.kostik_enabled'`;
      `DEFAULT_SUB_FLAGS['flags.kostik_enabled']=True`)
- [x] handlers/kostik.py (литерал удалён; thin-alias; `hot.get('reactions.kostik_replies', default)` +
      `_resolve_replies`; пустой список → молчание)
- [x] bot.py (только 4 пары DI `embed_base_url`/`embed_api_key`; router order/media не тронуты)
- [x] web/app.js (`api()` global-опция без утечки в fetch; `saveBlock`/`saveConfigItem` global-save;
      merged `PROVIDER_BLOCKS` + `blockDisplayName`; owner-блок Костика; `list-editor`)
- [x] web/index.html (merged-заголовки + `{{ blockDisplayName }}`; ветка `widget==='list'` в обоих
      generic-шаблонах; `#list-editor-tpl`)
- [x] .env.example (nano-gpt/apinet defaults; `EMBEDDING_API_KEY` комментарий; плейсхолдеры)
- [x] tests/js/routing_test.js (merged-блоки, global-save, `saveConfigItem`, `blockDisplayName`,
      `list-editor`, owner-блок), tests/test_webapp_round1012_ui.py (NEW), test_llm_client.py,
      test_kostik.py, test_permsoc.py, test_param_catalog.py, test_status_service.py, test_webapp_api.py,
      test_migrate_env_to_pg.py, test_round106_ia_smoke.py, test_frontend_tab_mapping.py,
      test_webapp_parity_smoke.py, test_webapp_round10{9,10,11}_ui.py
- [x] plans/features/providers-kostik-round1012/ (spec + ADR-1012-1 + tasks), plans/backlog.md (doc-only)
- [x] plans/reports/round10.12_scanner_audit.md (итог: 0 blocker/0 high/0 medium; 2 low R10.12-1/-5,
      3 info R10.12-2…-4)
- Открыто (follow-up, не блокеры): **R10.12-1** `web/app.js:3092-3112` `saveKeyItem` не переведён на
  global-save → 422 для `keys.*` вне provider-блоков (`CHECKUP_BETTERSTACK_SQL_*`, `YOUTUBE_COOKIES_FILE`,
  `YOUTUBE_TRANSCRIPT_PROXY_*`) при активном чате; **R10.12-5** `web/app.js:362,380,400` parent
  `modules==title` → `blockDisplayName` дублирует заголовок (косметика); R10.12-2 stale docstring
  `llm_probe.py:14`; R10.12-3 `KOSTIK_ENABLED` вне `.env.example`; R10.12-4 index-key в `list-editor`
  (`index.html:3181`). Из прошлых раундов: R10.11-1/-2/-3 (low), R10.11-4/-5/-6 (info), R10.10-1/-2/-4/-5,
  R10.9-1/-2/-3/-4, R10.7-1/-2, R10.6-1/-2/-3.

## Round 10.11 scan (2026-09-12) — all scanned
- [x] services/param_catalog.py (ADR-1011-2: 4 embed-фоллбэк-записи переведены из `_INFRA`
      в first-class каталог; REGISTRY 400/GROUPS 90/Settings 372/mapped 88 без изменений;
      categorized 372→376, infra 28→24; models 42 / keys 15)
- [x] services/llm_probe.py (`_BLOCK_SAVED_KEY` + `_saved_api_key` — R17-резолв сохранённого
      ключа при пустом `api_key`; `video_fallback`/`embeddings_main`/`_fallback1/2` в
      `KNOWN_BLOCKS`/`_EMBEDDING_BLOCKS`; kind=embeddings)
- [x] services/llm_client.py (embed-фоллбэк через `hot.get` с прежними кwarg-дефолтами)
- [x] services/status_service.py (embed-фоллбэк base/model/key1/key2 через `hot.get`)
- [x] web/app.js (`providerConnectionBlocks`/`providerAdvancedBlocks` — computed; `video_fallback`;
      embeddings 3 подблока; `zone:'advanced'` для guard/search/media_share; рекурсивный
      `providerCoveredKeys`; `blockFieldConfigured`/`last4ByKey`; `keyHistoryChartModel` —
      точки `{x,y}` + `spanGaps:true`; X linear + HH:MM callback + `parsing:false`)
- [x] web/index.html (две зоны, `<component :is=details/div>`, subBlocks-рендер, key-hint,
      nav/hub CSS 2.1, `:value`+`@input` без префилла секретов)
- [x] .gitignore (+plans/current_task.md), plans/backlog.md (doc-only)
- [x] tests/js/routing_test.js (chart-точки/ось; R17-draft; computed-зоны; video/embeddings),
      tests/test_webapp_round1011_ui.py (NEW), test_round106_ia_smoke.py, test_webapp_api.py
      (376; blank api_key → saved), test_param_catalog.py (42/15), test_migrate_env_to_pg.py (15)
- [x] plans/features/llm-providers-refactor-round1011/ (spec + ADR-1011-1/-2/-3 + tasks),
      plans/docs/memory_sleep_nostalgia_lore_report.md (п.4, docs-only)
- [x] plans/reports/round10.11_scanner_audit.md (итог: 0 blocker/0 high/0 medium; 3 low
      R10.11-1…-3, 3 info R10.11-4…-6)
- Открыто (follow-up, не блокеры): R10.11-1 (nested details делят localStorage-ключ),
  R10.11-2 (`embedding_fallback_model`: status vs runtime при явной очистке), R10.11-3
  (устаревшие «правьте в .env» для embed-ключей), R10.11-4 (probe + caller base_url —
  hardening), R10.11-5 (мёртвый `destroy`), R10.11-6 (нет headless Chart.js-теста).
  Из прошлых раундов: R10.10-1/-2 (скрипт DM), R10.10-4/-5 (фронт), R10.9-1/-2/-3/-4,
  R10.7-1/-2, R10.6-1/-2/-3.
- Обязательный деплой-шаг (ADR-1011-2): `python scripts/migrate_env_to_pg.py
  --only-category models,keys` (БЕЗ `--force`) до UI-проверки сохранённых embed-ключей.

## Round 10.10 scan (2026-09-12) — all scanned
- [x] web/index.html (fullscreen `.fullscreen-mode header.header-sticky` padding `max(env,--tg-*)`;
      10.7 width/10.9 scroll целы; «Провайдеры» `:value`+`@input`; «Роли» аватар/ник/ID `text-[10px]`
      `text-gray-500 font-mono`, `w-24`, `flex-1 min-w-0`, `shrink-0`; `.keys-chart` wrapper)
- [x] web/app.js (`keyHistoryChartModel` + `SAMPLE_BUCKET`/`MIN_BUCKETS`/окно от конца; `maintainAspectRatio:false`
      + `keyHistoryChartHeight` + `$nextTick`; `blockFieldValue` `''`-очистка; сброс `blockDrafts`/`blockResults`
      в `loadConfig`/`setActiveChat`; `loadAdmins` blob-аватары; `adminInitial`)
- [x] services/chat_params.py (`_DM_DISABLED_GATES`/`_DM_DISABLED_OVERRIDES`; `ensure_scope_profile(dm=True)`
      дефолты OFF; групповой путь и `bot.py` не тронуты)
- [x] scripts/disable_dm_heavy_modules.py (NEW: dry-run/`--apply`/`--chat-id`/`--snapshot-out`/`--restore`;
      snapshot до записи + abort; idempotent; merged namespaces; partial-failure → exit 1; 0 DDL)
- [x] web/api/avatars.py (`global_user_display_info`, `_user_name_cache`, транзиентные НЕ кэшируются)
- [x] web/api/routes.py (`GET /api/admins` enrichment копий, `gather`+`Semaphore(5)`, fail-open, RBAC не ослаблен)
- [x] tests/test_webapp_round1010_ui.py (NEW), tests/test_scripts_round1010_dm_off.py (NEW),
      tests/js/routing_test.js (chart/`blockFieldValue`/`adminInitial` юниты), tests/test_chat_params.py,
      tests/test_webapp_api.py, tests/test_webapp_avatars_ui.py
- [x] plans/features/admin-ui-round1010/ (spec/tasks + ADR-1010-1/-2/-3), plans/backlog.md
- [x] plans/reports/round10.10_scanner_audit.md (итог: 0 blocker/0 high/0 medium; 3 low R10.10-1…-3, 2 info R10.10-4/-5)
- Открыто (follow-up, не блокеры): R10.10-1 staged-отчёт `noop/total`; R10.10-2 `meta.note` вне snapshot;
  R10.10-3 chart-return без destroy; R10.10-4 аватары админов без skip; R10.10-5 дубль `adminInitial`.
  Из прошлых раундов: R10.9-1/-2/-3 (status_service), R10.9-4 (health cache-key), R10.7-1/-2,
  R10.6-1 (дубль generic-рендера), R10.6-2/-3 (SSRF/422-эхо `api_key`).

## Round 10.9 scan (2026-09-12) — all scanned
- [x] config/settings.py (+SLAVIK_ENABLED default True; +7 LLM/GROQ/OPENROUTER/EMBEDDING*_DISPLAY_NAME; Settings 372)
- [x] services/permsoc.py (slavik sub_flag_key=`flags.slavik_enabled`; DEFAULT_SUB_FLAGS True)
- [x] services/param_catalog.py (GROUPS 90/REGISTRY 400/mapped 88; −reactions_persons; SLAVIK_USER_ID→reactions_slavik;
      OLYA_USER_ID→reactions_olya; +7 display-name ParamSpec; переписаны title/description без жаргона/AI-шаблона; TAB_PERMSOC без persons)
- [x] services/status_service.py (llm_registry: group_id/group_title/display_name/provider=host/kind; probe_openai-интеграция;
      `_check_health` кэш по module_id 2xx 60с/ошибки 10с; emb main+2fb; `_display`/`_model_from`; healthLabel-контракт)
- [x] services/llm_probe.py (probe_openai chat/embeddings/stt; `_post_multipart`+`_silent_wav`; timeout/unreachable/error/not_configured; sanitize R17)
- [x] web/app.js (PERMSOC_OWNER_BLOCKS/TOGGLE_KEYS; `_permsocOwnerGroups`/`permsocOwnerOn`/`canToggleOwner`/`toggleOwner`;
      `llmGroups`; `healthBadge`/`healthLabel`; `_preserveScroll` (document+`.scroll-area`); −whoCanToggle/−optInCount;
      PROVIDER_BLOCKS display-name первым + человеческие label'ы; loadModules без бюджета; loadOversight→loadBudgetInfo)
- [x] web/index.html (owner-блоки `<component is=details/div>` + один `<summary>`-тумблер; −мастер-карта permsoc;
      −«Тяжёлые фичи»; «Бюджет фона (день)» в «Сводке»; блок «Доступность ключей» 4 группы; «История доступности ключей»;
      `configLoading && !configItems.length`; `max-w-3xl`; --grad-speed 14s/grad-drift 18s)
- [x] tests/test_webapp_round109_ui.py (NEW 18 тестов), tests/test_status_service.py (probe_openai/кэш-ошибок/группы), test_key_availability.py,
      test_param_catalog.py, test_frontend_tab_mapping.py, test_round106_ia_smoke.py, test_webapp_parity_smoke.py, test_webapp_api.py,
      test_permsoc.py, test_webapp_dm_ui.py, test_webapp_key_availability_ui.py, test_webapp_status_control.py,
      test_webapp_nav_disclosure_ui.py, test_webapp_avatars_ui.py, test_webapp_round108_ui.py, test_104_backend_additions.py
- [x] tests/js/routing_test.js (`_preserveScroll` два-скроллера юнит; спиннер-условие)
- [x] plans/features/admin-ui-round109/ (spec.md, tasks.md, ADR-109.md)
- [x] plans/backlog.md, plans/reports/round10.9_scanner_audit.md (0 blocker/0 major/0 medium; 3 low R10.9-1…3, 3 info R10.9-4…6)
- Открыто (follow-up, не блокеры): R10.9-1 (`model_source`); R10.9-2 (emb-fallback display/read);
  R10.9-3 (stale docstring status_service); R10.9-4 (health cache-key по module_id).
  Из прошлых раундов вне UI-скоупа: R10.7-1/-2 (`status_service` gap-fill), R10.6-1 (дубль generic-рендера),
  R10.6-2/-3 (SSRF/422-эхо `api_key`).

## Round 10.8 scan (2026-09-11) — all scanned
- [x] web/app.js (labels TABS/NAV/HUBS; ICONS 20→37 (17 new, 6 dead из 10.7 не вернулись);
      applyRoute accessOpen-нормализация; openAccessWindow/closeAccessWindow (−setAccess);
      setTab cleanup copiedTimer/copiedIndex; fmtLogTime DD.MM HH:MM:SS)
- [x] web/index.html (заголовки разделов; emoji→Material (§2.2); логи: div.log-code/.log-row/
      .log-head/.log-msg без жёстких ширин и break-all, toggle chevron/spacer; «Доступы»:
      3 modal-backdrop + плитки, `sec-*` целы; удалён внешний GLOBAL-бейдж)
- [x] scripts/build_font_subset.py (ICON_NAMES 37; `_marker_key` sha(src|names);
      `_write_icon_codepoints` → build/icon_codepoints.json)
- [x] web/static/fonts/material-symbols-rounded.woff2 (субсет 18 388 B, cmap 37/37)
- [x] README.md (структура: «самое важное», управление+деплой, changelog под `<details>`,
      шапка v2.52.0/5073)
- [x] tests/test_webapp_round108_ui.py (NEW: renames/emoji/badge/logs/access-windows)
- [x] tests/test_font_subset.py (паритет ICONS↔ICON_NAMES + cmap через fontTools; Test C/D)
- [x] tests/test_webapp_tma_fixes_ui.py, test_webapp_round107_ui.py (логи: блок-раскладка,
      toggle-иконка, отсутствие жёстких ширин)
- [x] tests/test_frontend_tab_mapping.py, test_round106_ia_smoke.py (access windows)
- [x] tests/test_webapp_hubs_matrix_ui.py, test_webapp_parity_smoke.py (новые лейблы)
- [x] tests/test_webapp_key_availability_ui.py (sec-roles/sec-matrix вместо слайсинга)
- [x] tests/test_webapp_back_button.py (openAccessWindow/closeAccessWindow/ROUTE_PARENT)
- [x] tests/test_webapp_nav_disclosure_ui.py (⚙️→iconGlyph('settings')), test_webapp_avatars_ui.py (✕==4)
- [x] tests/js/routing_test.js (applyRoute #/access/roles→'roles', #/ai→null; fmtLogTime дата)
- [x] plans/features/admin-ui-round108/ (spec.md, tasks.md, ADR-001, ADR-002)
- [x] plans/backlog.md, plans/reports/round10.8_scanner_audit.md (итог: 0 блокеров/0 major,
      2 minor R10.8-1 Esc / R10.8-5 APP_VERSION=2.51.0 vs README v2.52.0 + кэш старого
      субсета `.woff2` (max-age 86400, URL не версионирован) → tofu; 3 info; R10.7-3/R10.7-4 закрыты)
- Открыто (НЕ 10.8, кандидаты 10.9): R10.7-1/-2 (`services/status_service.py`),
  R10.6-1 (дубль generic-рендера `llm_providers`), R10.6-2/-3 (SSRF/422-эхо `api_key`).

## Round 10.7 scan (2026-09-11) — all scanned
- [x] web/app.js (scope* → computed 6 шт; ICONS −6 мёртвых; fmtLogTime; copyText
      finally-remove + preventScroll + boolean execCommand; copyLogRow + copiedIndex;
      copyAllLogs self.logText)
- [x] web/index.html (1b `header.header-sticky`+env safe-area; 1c компактный user block;
      1d nav-label keep-all/2-line clamp/0.625rem; 2a scoped `.keys-avail` fixed+ellipsis;
      3a `.clipboard-ghost` opacity/contain strict без visibility:hidden; 3b log-колонки;
      3c `log-copied`/`copyLogRow`)
- [x] services/status_service.py (2b `_bucketize` gap-fill 'down' до now_slot;
      `last_heartbeat` = последний 'up'/None)
- [x] tests/test_webapp_round107_ui.py (NEW: маркеры 1b/1c/1d/2a/3a/3b/3c)
- [x] tests/js/routing_test.js (стаб document/navigator/execCommand; 3a ghost-removed,
      DEF-2 false-execCommand, 3c copyLogRow, 1a computed)
- [x] tests/test_status_service.py (gap-fill up/down/down/up, trailing downtime,
      last_heartbeat None/truthy)
- [x] tests/test_font_subset.py (R106-5: `\ue887` help вместо `\ue850`)
- [x] tests/test_webapp_avatars_ui.py (`_Static.body` — regex определения функции)
- [x] tests/test_webapp_back_button.py (1a: 6 scope* в computed, не methods)
- [x] tests/test_webapp_tma_fixes_ui.py (3c: `copyLogRow(log,i)` + `log-copied`)
- [x] plans/backlog.md, plans/features/admin-ui-bugfixes-round107/ (spec/tasks)
- [x] plans/reports/round10.7_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major,
      1 minor + 3 info + 1 nit; R10.6-5 закрыт)

## Round 10.6 scan (2026-09-11) — all scanned
- [x] config/settings.py (5 master-флагов FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP_ENABLED, default True)
- [x] services/param_catalog.py (GROUPS 91/REGISTRY 392/Settings 364/mapped 89; расщепления
      limits_media→4, limits_persons→2, limits_youtube_web→2, limits_cooldowns→0,
      flags_modules→7, flags_chat_behavior→7, reactions_kostik NEW, limits_rag NEW;
      _FLAGS +TAB_RULES/CONFIG_TAB_TITLES 19;_TAB_BY_GROUP 89, DDL-free)
- [x] services/llm_probe.py (NEW: _safe_base SSRF-минимум, sanitize_error R17,
      KNOWN_BLOCKS, probe_block/_probe_search, per-field search_keys:tavily/exa)
- [x] web/api/routes.py (POST /api/llm/test: requires_global_admin, rate-limit 5с/ttl-прунинг,
      LlmTestRequest; reset_llm_test_rate_limit — тест-точка)
- [x] handlers/factcheck.py, search.py, web.py, checkup.py, youtube.py
      (5 master-гейтов hot.get→UNHANDLED; youtube — только mode=="summary")
- [x] web/app.js (MODULES 11, PROVIDER_BLOCKS 9, accessOpen-аккордеон, scope/route-алиасы,
      activeModule-модалка, Esc/back-закрытие, canEditConfig DM per_chat R10.5-2,
      initBackButton ready R10.5-1, TAB_SECTION_ORDER 19, emoji→Material)
- [x] web/index.html (sidebar/☰/MENU_ORDER удалены, nav-label, scroll-модель,
      модуль-карточки+модалка, prov-блоки+test-кнопка, аккордеон, iconGlyph help/matrix)
- [x] tests/test_round106_gates.py (NEW: OFF→UNHANDLED ×5 + default ON)
- [x] tests/test_round106_ia_smoke.py (NEW: каталог-инвариант, nav, IA, llm_probe, SSRF)
- [x] tests/test_frontend_tab_mapping.py, test_param_catalog.py, test_webapp_api.py
      (POST /api/llm/test 403/200/429/R17), test_webapp_nav_disclosure_ui.py,
      test_webapp_hubs_matrix_ui.py, test_webapp_parity_smoke.py, test_webapp_dm_ui.py,
      test_webapp_agi_ui.py, test_webapp_back_button.py, test_webapp_lore_ui.py,
      test_webapp_avatars_ui.py, tests/js/routing_test.js (маркеры новой IA)
- [x] plans/features/tma-ia-modules-rework/ (spec v2, design-project v2, tasks)
- [x] plans/backlog.md (doc-only)
- [x] plans/reports/round10.6_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major,
      3 minor + 3 info)

## Round 10.5 scan (2026-09-10) — all scanned
- [x] .gitignore (relumesite_example/, MaterialSymbolsRounded*.woff2, var/, build/)
- [x] services/key_history.py (NEW: allowlist, атомарный снимок, ring, fail-open)
- [x] services/param_catalog.py (_MODELS_PG_ONLY: +4 PG-only → REGISTRY 387/74/359)
- [x] services/config_cache.py (rename_role/role_usage/_scrub_param_permissions — DML-only)
- [x] services/status_service.py (_resolve/llm_registry module_id|module_title|model_source;
      _build_llm_card → key_history.record; maybe_save)
- [x] services/video_cascade_client.py (base_url hot + инвалидация клиента)
- [x] SmartModule/transcriber/groq_transcriber.py (hot base_url/model)
- [x] SmartModule/transcriber/openrouter_transcriber.py (hot base_url/model)
- [x] web/api/routes.py (roles DELETE + /rename; GET /status/key-history; get_roles role_type)
- [x] web/api/access.py (param_permissions_list: tab/tab_title/group*/title/secret метаданные)
- [x] web/app.py (mount /static — self-host fonts/vendor)
- [x] web/app.js (hash-роутер, navbar/hub, scope-dropdown+a11y, матрица, key-avail,
      role rename/delete, sanitize fail-closed, scopeEpoch-гварды, иконки PUA)
- [x] web/index.html (токены+градиенты, @font-face, navbar/hub, scope-dropdown,
      матрица, key-avail, self-host dompurify, адаптив)
- [x] scripts/build_font_subset.py + scripts/requirements-font.txt (NEW, build-time only)
- [x] web/static/fonts/* (субсет 13 КБ + LICENSE Apache-2.0)
- [x] web/static/vendor/dompurify-3.4.15.min.js (self-host, pinned)
- [x] conftest.py (M6: STATUS_KEY_HISTORY_FILE → temp)
- [x] tests/test_key_availability.py, test_roles_admin.py, test_font_subset.py,
      test_webapp_back_button.py, test_webapp_hubs_matrix_ui.py, test_webapp_js_unit.py,
      test_webapp_key_availability_ui.py, test_webapp_parity_smoke.py, tests/js/routing_test.js (NEW)
- [x] tests/test_menu.py, test_param_catalog.py, test_video_cascade.py, test_webapp_api.py,
      test_webapp_avatars_ui.py, test_webapp_deps.py, test_webapp_dm_ui.py,
      test_webapp_nav_disclosure_ui.py, test_webapp_rbac_ui.py (маркеры обновлены)
- [x] plans/features/tma-relume-redesign/ (spec v3, design-project v5, tasks, reference-analysis)
- [x] plans/MEMORY.md, plans/backlog.md (doc-only)
- [x] plans/reports/round10.5_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major)

## Round 10.4 scan (2026-09-10) — all scanned
- [x] plans/features/* (8 спек: A reorg, B limits-temp-budgets, C memory-sleep-nostalgia,
      D advanced-collapse, E llm-providers-layout, F relations-participants,
      G chat-1002661910336-scaling, H relations-nickname)
- [x] services/param_catalog.py (TAB_RULES/CONFIG_TAB_TITLES/_TAB_BY_GROUP,
      select_options/labels, _MEMORY progressive_level, _ADVANCED_GROUPS)
- [x] services/chat_params.py (_resolve_from_root G-2: _cast_type_ok + isfinite)
- [x] services/direct_chat_service.py (_cp_g-точки, _budget_gate B-2,
      _apply_context_budget(enabled, tokens), _thread_limit, window[-max(1,..)],
      _active_participants, level2 cap, thread depth)
- [x] services/summary_aliases.py (+build_alias_resolver)
- [x] services/summary_generator.py (_chat_limit: rag_l2/max_context_tokens/chars)
- [x] services/summary_memory.py (window/rag/retention/compress/edge_weight per-chat)
- [x] services/user_relations.py (_display_name B-13-limitation, документирование)
- [x] web/api/routes.py (GET select_options/labels; POST валидация — обе ветки)
- [x] web/api/chat_lore.py (list_relations: Semaphore(5) username-всем, photo-топ-50,
      per-chat alias_resolver B-13)
- [x] web/app.js (TABS-зеркало, flatGroupRank, sectionTitle, chatLoreTab/relationsTab,
      setTab-сброс, relChat-гвард, relations-автозагрузка, карточки модулей)
- [x] web/index.html (select-виджет basic+advanced, `:open="expandOpen"`, relations-
      шаблон (участники+конфиг-блок+аккордеон), lore-конфиг-блок, удаление блока
      участников из лора, карточки модулей)
- [x] scripts/backfill_104_chat_flags.py (идемпотентность/безопасность)
- [x] scripts/backfill_104_overrides.py (множители, caps, skip-логика None-дефолтов)
- [x] tests/test_104_backend_additions.py, test_progressive_tab_basic_coverage.py,
      test_frontend_tab_mapping.py + обновлённые маркер-тесты (4860 passed)
- [x] plans/reports/round10.4_review_fixes.md (соответствие реальности: 3 пункта —
      R10.4-3/4/7 расхождения зафиксированы)

## Round 10.3 scan (2026-09-10) — all scanned
- [x] plans/features/tma-chat-selector-fixes/ (spec)
- [x] plans/features/dm-user-settings/ (spec)
- [x] plans/features/direct-sandbox-budget-investigation/ (spec)
- [x] services/access.py (DM-ветки can_access_chat/eligible_type/can_edit_param)
- [x] services/roles.py (is_dm_owner/DM_OWNER_PRESET/access_for DM-ветка)
- [x] services/chat_params.py (is_dm_scope/ensure_scope_profile/get_chat_param_defaulted/chat_summary_enabled)
- [x] services/llm_client.py (NoApiKeyForChat.details, BYOK-фоллбэк, usage-учёт)
- [x] services/direct_chat_service.py (S2-гейт, sandbox WARNING details)
- [x] services/summary_memory.py (S1-гейт, _mask_llm_raw, fallback-парсер, ретрай)
- [x] services/summary_scheduler.py (S3: skip chat_id>0)
- [x] services/chat_lore_store.py (П.2: chat_id<0)
- [x] services/oversight.py (П.4: chat_id<0)
- [x] web/api/routes.py (DM-гейты GET/POST/keys/delete/status)
- [x] web/api/access.py (DM-строка, фильтр <0)
- [x] web/api/gates.py (DM read/403 write)
- [x] web/api/chat_lore.py (DM→404)
- [x] web/app.js (canViewTab/canEditConfig/isDmCtx/configError/setActiveChat/closeApp)
- [x] web/index.html (селектор, template v-for/v-if, бейдж, z-index 45, баннер)
- [x] tests/test_dm_access.py, test_webapp_dm_ui.py + обновлённые тест-файлы (4831 passed)

## High priority (git working tree)
- [x] plans/MEMORY.md (untracked, doc-only)

## Root files
- [x] bot.py
- [x] manage.py
- [x] conftest.py
- [x] deploy_v2.9.2.py
- [x] check_remote_bot.py
- [x] debug_remote.py
- [x] docker-compose.yml
- [x] requirements.txt
- [x] pytest.ini
- [x] .gitignore
- [x] .env.example
- [x] info_text.md

## config/
- [x] config/settings.py
- [x] config/__init__.py

## handlers/
- [x] handlers/__init__.py
- [x] handlers/common.py
- [x] handlers/menu.py
- [x] handlers/media_common.py
- [x] handlers/info.py
- [x] handlers/search.py
- [x] handlers/admin_commands.py
- [x] handlers/alan.py
- [x] handlers/alan_greeting.py
- [x] handlers/kostik.py
- [x] handlers/slavik.py
- [x] handlers/slava_presence.py
- [x] handlers/olya.py
- [x] handlers/vasya.py
- [x] handlers/dead_page_trigger.py
- [x] handlers/dead_page_delete.py
- [x] handlers/war_alert.py
- [x] handlers/chat_lifecycle.py
- [x] handlers/direct_chat.py
- [x] handlers/factcheck.py
- [x] handlers/summary.py
- [x] handlers/video_download.py
- [x] handlers/voice_transcription.py
- [x] handlers/web.py
- [x] handlers/youtube.py
- [x] handlers/checkup.py
- [x] handlers/debug_config.py

## filters/
- [x] filters/__init__.py
- [x] filters/admin_word.py
- [x] filters/danger_word.py
- [x] filters/kucha_word.py
- [x] filters/olya_video.py
- [x] filters/otboy_word.py
- [x] filters/selfdev_word.py
- [x] filters/target_channel.py
- [x] filters/user_id.py
- [x] filters/vasya_name.py
- [x] filters/word_lists.py
- [x] filters/work_word.py

## services/
- [x] services/__init__.py
- [x] services/access.py
- [x] services/betterstack_handler.py
- [x] services/bot_commands.py
- [x] services/chat_access.py
- [x] services/chat_context.py
- [x] services/chat_keys.py
- [x] services/chat_lore.py
- [x] services/chat_lore_store.py
- [x] services/chat_params.py
- [x] services/chat_prompts.py
- [x] services/chat_usage.py
- [x] services/checkup_prompts.py
- [x] services/checkup_service.py
- [x] services/common_relay.py
- [x] services/config_cache.py
- [x] services/control_service.py
- [x] services/database.py
- [x] services/dead_page_relay.py
- [x] services/debug_config.py
- [x] services/direct_chat_service.py
- [x] services/dream_prompts.py
- [x] services/dream_worker.py
- [x] services/feature_gates.py
- [x] services/goodmorning_captions.py
- [x] services/goodmorning_relay.py
- [x] services/goodmorning_scheduler.py
- [x] services/hot_config.py
- [x] services/info_service.py
- [x] services/llm_circuit_breaker.py
- [x] services/llm_client.py
- [x] services/log_ring.py
- [x] services/lore_cache.py
- [x] services/lore_notify.py
- [x] services/lore_prompts.py
- [x] services/lore_runtime.py
- [x] services/lore_worker.py
- [x] services/media_download.py
- [x] services/media_group_buffer.py
- [x] services/media_picker.py
- [x] services/media_share.py
- [x] services/memory_backup.py
- [x] services/memory_health.py
- [x] services/memory_maintenance.py
- [x] services/message_counter.py
- [x] services/mimic_relay.py
- [x] services/mimic_transform.py
- [x] services/nostalgia_prompts.py
- [x] services/nostalgia_worker.py
- [x] services/olya_relay.py
- [x] services/oversight.py
- [x] services/param_catalog.py
- [x] services/payload_builder.py
- [x] services/permissions.py
- [x] services/permsoc.py
- [x] services/persistent_throttling.py
- [x] services/pg_db.py
- [x] services/progress_reporter.py
- [x] services/prompt_migrations.py
- [x] services/roles.py
- [x] services/sandbox_reply.py
- [x] services/scheduler.py
- [x] services/search_aggregator.py
- [x] services/search_prompts.py
- [x] services/search_service.py
- [x] services/smart_cache.py
- [x] services/smartmodule_concurrency.py
- [x] services/smartmodule_phrases.py
- [x] services/smartmodule_throttling.py
- [x] services/smartmodule_urls.py
- [x] services/smartmodule_utils.py
- [x] services/status_service.py
- [x] services/summary_aliases.py
- [x] services/summary_cleanup.py
- [x] services/summary_generator.py
- [x] services/summary_memory.py
- [x] services/summary_prompts.py
- [x] services/summary_scheduler.py
- [x] services/summary_throttling.py
- [x] services/summary_xml.py
- [x] services/system_logs_fetcher.py
- [x] services/token_counter.py
- [x] services/tool_loop.py
- [x] services/tool_router.py
- [x] services/tool_schemas.py
- [x] services/typing_manager.py
- [x] services/uptime_heartbeat.py
- [x] services/user_relations.py
- [x] services/video_cascade_client.py
- [x] services/web_content_extractor.py
- [x] services/web_prompts.py
- [x] services/web_runtime.py
- [x] services/web_summarizer_service.py
- [x] services/worker_budget.py
- [x] services/youtube_prompts.py
- [x] services/youtube_summarizer_service.py
- [x] services/youtube_transcript_engine.py

## scripts/
- [x] scripts/__init__.py
- [x] scripts/backfill_feature_gates.py
- [x] scripts/backfill_permsoc_gates.py
- [x] scripts/migrate_direct_chat_v2.py
- [x] scripts/migrate_env_to_pg.py
- [x] scripts/migrate_epic60_v3.py
- [x] scripts/migrate_graphrag_v2.py
- [x] scripts/run_golden_questions.py
- [x] scripts/seed_chat_lore.py

## tools/
- [x] tools/__init__.py
- [x] tools/cookies_export.py
- [x] tools/video_downloader.py
- [x] tools/video_download_phrases.py
- [x] tools/history_import/__init__.py

## web/
- [x] web/__init__.py
- [x] web/app.py
- [x] web/app.js
- [x] web/index.html
- [x] web/api/__init__.py
- [x] web/api/access.py
- [x] web/api/admins.py
- [x] web/api/avatars.py
- [x] web/api/chat_lore.py
- [x] web/api/config.py
- [x] web/api/direct_chat.py
- [x] web/api/keys.py
- [x] web/api/logs.py
- [x] web/api/oversight.py
- [x] web/api/params.py
- [x] web/api/permissions.py
- [x] web/api/relations.py
- [x] web/api/roles.py
- [x] web/api/status.py
- [x] web/api/system.py
- [x] web/api/usage.py
- [x] web/api/workers.py

## SmartModule/
- [x] SmartModule/__init__.py
- [x] SmartModule/service.py

## tests/
- [x] tests/__init__.py
- [x] tests/conftest.py
- [x] tests/test_*.py (all test files)
## Round 10.20 (T-1915) scan (2026-09-16) — diff-based: БЛОКИ 0–8 эпика `round1020`, HEAD 2f3e1f0 + worktree
- [x] services/canonical_context.py (14 точек, representation/pattern, `strip_context_header`/`format_context_item`/
      `format_chat_time`; pattern `legacy_rag` рассинхронизирован с рантаймом — S10.20-9)
- [x] services/context_middleware.py (header-safe `truncate_keep_header`, `limit<=0` → заголовок; чисто)
- [x] services/lore_compiler_service.py (`_trim` режет header — S10.20-8; `last_ts` обгоняет материал — S10.20-5;
      `_EMPTY_DENSE` shared list — S10.20-15; `_date` UTC — S10.20-14)
- [x] services/reply_postprocess.py (`strip_reasoning_tags`: no-op/парные/незакрытые/лишние — верно; чисто)
- [x] services/tool_loop.py (graceful degradation BLOCK 7.1; NoApiKeyForChat-проброс; PartialText; чисто)
- [x] services/llm_client.py (`reasoning` аддитивно; reasoning-only без LLMBadResponseError; чисто)
- [x] services/direct_chat_service.py (точки 2/3 канона, `_line_markers` header-strip, Time Injection,
      `_send_direct_answer` HTML+фолбэк; per-chat флаг vs роутер — S10.20-2; чанк-дубль — S10.20-10)
- [x] services/database.py (v11→v12 `graph_facts` provenance — идемпотентно/PG no-op; `lore_stories`,
      `persona_dossier_overrides` без бампа; `lore_graph_slice`/`lore_dense_dialogs`; 17/17 `memorize_facts`;
      `dossier_feed` RANDOM — reviewer M3 + S10.20-16)
- [x] services/tool_schemas.py (8 тулов EN, `active_tools`/`factcheck_tools` — новые списки, dict-схемы общие — ок)
- [x] services/tool_router.py (JSON-контракт dig ломается капом — S10.20-3; per-chat флаг — S10.20-2;
      `_LORE_RETURN_INSTRUCTION` в фактчеке — S10.20-4)
- [x] services/factcheck_service.py / services/factcheck_prompts.py (Full Tool Access, DI-kwarg; канон +функц. блоки)
- [x] services/summary_memory.py / summary_generator.py / summary_cleanup.py (6-кортежи R16, ASC после дедупа,
      header-strip токенов, archive-маркер; чисто)
- [x] services/oversight.py (`key_status` 1× вместо 2× — контракт сохранён; чисто)
- [x] services/memory_maintenance.py / manage.py (fsync каталога no-op win32; retention-снапшот;
      `initialize_existing` без проверки схемы — S10.20-13)
- [x] services/status_service.py (per-chat context budget; acct затирает cap — S10.20-7)
- [x] services/param_catalog.py / config/settings.py (каталог 439/92/20, +1 tz-ключ, +1 флаг; Δ санкционирован)
- [x] web/index.html + web/app.js + web/static/app.css + web/api/* (`openModuleWindow`/тумблер/досье/тикер/
      sticky-save; МЕНЮ не изменено; **S10.20-1 [High] — конфиг-вкладки без сохранения**; S10.20-6)
- **Открыто (Round 10.20):**
  - [ ] **S10.20-1 [high, new] BLOCKER** — `web/index.html:170-700`: добавить `<sticky-save>` в ветку
        `currentTabIsConfig` (перед :700) + тест «панель есть в каждой ветке без авто-сейва».
  - [ ] S10.20-2 [medium, new] — per-chat `flags.lore_compiler_enabled` в `tool_router._compile_lore_story`
        и `factcheck_service` (сегодня только глобальный `hot.get`).
  - [ ] S10.20-3 [medium, new] — `dig_into_lore`: усечение секций ДО `json.dumps` (или `truncated: true`).
  - [ ] S10.20-4 [medium, new] — `_LORE_RETURN_INSTRUCTION` не подмешивать вне DirectChat / срезать HTML в фактчеке.
  - [ ] S10.20-5 [medium, new] — `last_ts` считать по фактически включённым в промпт строкам.
  - [ ] S10.20-6 [medium, new] — `saveModalEdits`: не снимать baseline при ошибках сохранения.
  - [ ] S10.20-7 [medium, new] — «Бюджет контекста»: приоритет per-chat cap над `acct.context_limit`.
  - [ ] S10.20-8 [medium, подтверждение reviewer M1–M3] — `_trim` (header), кап скана узлов, `ORDER BY RANDOM()`.
  - [ ] Low: S10.20-9 (pattern `legacy_rag`), -10 (чанк-дубль HTML), -11 (`javascript:` href), -12 (cache),
        -13 (`initialize_existing`), -14 (`_date` UTC), -15 (`_EMPTY_DENSE`), -16 (докстринг fail-open),
        -17 (запись досье moderator'ом).
- **СВОДКА ЭПИКА 10.20: Critical 0 / High 1 / Medium 7 / Low 9 / Info 5.**
  **ВЕРДИКТ: есть Critical/High → возврат к @Builder (S10.20-1), затем повторный ревью UI-фазы (T-1904).**
- Валидатор @Scanner: pytest **6523 passed / 0 failed** (89.52 c); `node --check web/app.js` OK;
  `routing_test.js` + `round1020_ui_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` exit 0; каталог 439/92/20; SQLite v12.
