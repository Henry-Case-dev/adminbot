# Фича F7 — `settings-worker-sync` (единый источник истины настроек: per-chat DB > глобальный DB > env-дефолт, реактивные воркеры)

> **Статус: ⏳ PLANNED** (Step 1 @PM → Step 2 @Architect, итерация 2 после human-gate, 15.09.2026). Реализация — T-1759…T-1764 (@Builder), гейты T-1758 (@Architect) / T-1765 (@DevOps) / T-1766 (@Reviewer/@PM).
> **Spec:** `spec.md`. **ADR:** `adr-1018-7-settings-single-source-of-truth.md` (обязателен).
> **Раунд:** 10.18. **Нумерация:** T-1758…T-1766 (продолжает T-1757).
> **Тип:** backend (`services/worker_settings.py` новый, `services/dream_worker.py`, `web/api/memory_agi.py`, `bot.py` LISTEN) + точечно frontend (`web/app.js`). **Приоритет:** **P0** (симптом владельца: тумблеры ON в UI, воркеры OFF).
> **Зависимости:** нет (блокирует F2/F4/F5). **Конфликт файлов:** `services/dream_worker.py` (F2), `web/api/memory_agi.py` (F2/F3), `web/app.js` (F2/F4).
> **ТЗ:** `plans/current_task.md` UPD п.3 (строки 119-121), п.4.
> **Baseline:** HEAD `118a03c`; pytest **6007 passed / 0 failed**; каталог **435/406/411/90/88/19**; SQLite **v9**.

## 0. Цель
Устранить рассинхрон «настройки UI → воркеры»: воркеры и статус-API резолвят значение по приоритету **per-chat DB → глобальный DB → env-дефолт**, переключение тумблера действует без рестарта, источник значения виден в логах.

## 1. Диагноз (детали — spec §2)
- Слой чата (`chat_profiles.chat_params.overrides`) пишется UI-ом, но **не читается** `DreamWorker` (`dream_worker.py:252-253`) и статус-API (`memory_agi.py:442-444,386`).
- Планировщик DreamWorker регистрирует джоб **один раз** на старте (`dream_worker.py:294-351`, `bot.py:560`) → нет реактивности.
- `pg_notify('chat_params_updated')` без `LISTEN` (`chat_params.py:37,304`).
- `flags.deep_sleep_enabled` недостижим из окна «Сон» (`param_catalog.py:1823-1825,831-835`).

## 2. Требования
- [x] Единый accessor `resolve_setting`/`resolve_setting_cached` (per-chat → global → default) — T-1759.
- [x] `DreamWorker` читает пороги/лимиты/флаги **по чату**; `flags.deep_sleep_enabled`/`trigger` — по чату — T-1760.
- [x] Тумблер действует **без рестарта** (джоб всегда зарегистрирован, решение — в тике) — T-1761.
- [x] Статус-API учитывает `chat_id` + отдаёт `source` (аддитивно, R16) — T-1762.
- [x] Тумблер Глубокого сна достижим из окна «Сон» (каталог-Δ=0) — T-1763.
- [x] Таблица «настройка → пишется → читается → статус» зафиксирована; `nostalgia` — backlog — T-1764.
- [x] Полный `pytest` 0 failed (кроме pre-existing `test_tool_download_quality_round1017` — stale doc-path, вне F7); JS-гейты; каталог **Δ=0**.

## 3. Constraints
- **Без фича-флагов** (владелец: базовая логика). Откат = `git revert`.
- **Каталог Δ=0** (REGISTRY 435 / Settings 406 / GROUPS 90 / mapped 88 / TAB_RULES 19).
- **DDL нет**; SQLite v9, PG-схема без изменений.
- **R16/R17**, fail-open (PG down → глобальный/дефолт, бот жив), порядок роутеров `bot.py` не менять, `media/`/`.env` не трогать.
- Ревью-гейты: `pytest` 0 регрессий; `node --check web/app.js`; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check`; русские conventional commits.

## 4. Порядок
`T-1759` (accessor) → `T-1760` (воркеры) → `T-1761` (реактивность) → `T-1762` (статус-API) → `T-1763` (UI) → `T-1764` (тесты/аудит/backlog) → `T-1765` (@DevOps) → `T-1766` (@Reviewer/@PM).

## 5. Definition of Done
- [ ] Запись тумблера в scope чата → воркер видит значение (регресс-тест воспроизводит симптом и его отсутствие).
- [ ] Переключение ON/OFF Сна и Глубокого сна действует без рестарта.
- [ ] `cognition/status?chat_id=…` отдаёт `enabled` по чату и `source` (аддитивно).
- [ ] В логах виден `source=` и `chat_id`.
- [ ] Каталог-Δ=0; полный `pytest` 0 failed; JS-гейты чистые.

## 6. Чек-лист задач

- [x] **T-1758 (@Architect, гейт):** `spec.md` + **ADR-1018-7** — приоритет per-chat DB > global DB > default, единый accessor, реактивная реконфигурация планировщика, `LISTEN`/TTL, UI-доступ к deep-флагу, границы для `tick_minutes`.
- [x] **T-1759 (@Builder):** новый `services/worker_settings.py` — единый read-path `resolve_setting` (`resolve_setting_cached` — тонкая обёртка воркеров; `setting_source` — диагностика без I/O) (семантика каста = `chat_params._resolve_from_root`); fail-open; R17-safe лог `source`.
- [x] **T-1760 (@Builder):** `services/dream_worker.py` — `_key_for(chat_id, …)`; per-chat резолв порогов/лимитов в `_process_chat`/`_candidates`/`_budget_reason`; per-chat `flags.deep_sleep_enabled`/`memory.deep_sleep_trigger` в `_maybe_deep_after_sleep`/`_run_deep_once`/`_deep_tick`; `_key()` сохранить (обратная совместимость); gate-fallback per-chat (`feature_gates.gates_enabled(..., fallback=)`); kill-switch `flags.<feature>_enabled` приоритетнее fallback (R10.18-3); при `manual=True` флаг/триггер deep НЕ гейтят каскад (ADR-1018-2 D2, R10.18-10). Тик-слой (`min_new_facts_per_chat`/`max_chats_per_run`/`quiet_check_minutes`/`initial_window_hours`) — **осознанно глобальный** (spec §2.3, ADR D3, R10.18-5).
- [x] **T-1761 (@Builder):** реактивность — `start()` регистрирует джоб всегда; решение «работать/не работать» — per-chat в `_process_chat` (глобальный резолв без мёртвого раннего return, R10.18-4); выключение не прерывает активный `_run`; лог `tick_minutes applies on restart`.
- [x] **T-1762 (@Builder):** `web/api/memory_agi.py` — `cognition_status`/`deep_sleep_status` резолвят `enabled` по `chat_id` и отдают аддитивный `source` (R16); `deep_sleep_status` принимает `chat_id: Query() = None`.
- [x] **T-1763 (@Builder):** `web/index.html` (окно «Сон») — подпись+ссылка на тумблер Глубокого сна (**без** расширения TAB_RULES, каталог-Δ=0; ссылка на фактический маршрут `#/ai/memory`, R10.18-11).
- [x] **T-1764 (@Builder):** `services/chat_params_notify.py` — `LISTEN chat_params_updated` на ОТДЕЛЬНОМ соединении (`ChatParamsNotify`, `asyncpg.connect` + backoff; НЕ `Pool.add_listener` — R10.18-1) → `invalidate_chat_from_notify` (fail-open, rate-limited WARNING); тесты реального монтирования/инвалидации/реконнекта (R10.18-2); финализация аудит-таблицы (spec §2.3); backlog-задача по аналогичному рассинхрону `memory.nostalgia_enabled`.
- [ ] **T-1765 (@DevOps, гейт):** деплой (SSH pull + `systemctl restart admin_bot` + live-проверка: включить чат-тумблер → `cognition/status` `enabled=true`, `source='chat'`, лог `[settings] … source=chat`). Пароль в репо **НЕ хранить**.
- [ ] **T-1766 (@Reviewer + @PM, гейт):** сверка DoD; R16-аддитивность; каталог-Δ=0; отсутствие регрессов F2-путей; подтверждение, что глобальный путь не сломан.

### 6a. Audit-fix Батч 1 (@Scanner, `round10.18_scanner_audit.md`)

- [x] **S10.18-1 (High):** per-chat расход бюджета Сна — `count_dream_log(..., chat_id=)`/`sum_dream_log_tokens(..., chat_id=)` (`services/database.py`), `_process_chat` считает `distilled/tokens_today` по чату; регресс-тест «чат A с override не глушится расходом чата B» (`test_dream_worker.py::TestPerChatBudget`).
- [x] **S10.18-2 (Medium):** per-chat `trigger`/`hour` в `_deep_tick` + helper `_deep_candidate_chat_ids`; тесты `test_deep_tick_resolves_trigger_per_chat`, обновлён `test_deep_tick_fixed_at_target_hour`.
- [x] **S10.18-3 (Medium):** статусы используют тот же fallback, что воркер (`feature_gates.master_fallback`; `gates_get`/`allowed_features`/`oversight`/`web/api/oversight`); `cognition_status.dream.effective` + `active` по нему; тесты `TestStatusMatchesWorkerBehavior`.
- [x] **S10.18-4 (Medium):** decay гейтится глобальным master Сна; тесты `TestDecayGatedByDreamMaster`.
- [x] **S10.18-5 (Medium):** manual-каскад по целевому чату + кап `_MANUAL_DEEP_CASCADE_MAX`; тесты `TestManualDeepCascade`.
- [x] **S10.18-6 (Medium):** нет `BETTERSTACK_HOST` → ERROR «логи НЕ отправляются»; тесты `test_skipped_when_no_host`/`test_skipped_marker_without_token` обновлены.
- [x] **S10.18-7/-11 (Low):** `ChatParamsNotify.stop()` вызывается из `on_shutdown()`; сильные ссылки на `create_task` в `_on_notify` (`_pending` + done-callback); тест `TestListenerStopLifecycle`.
- [x] **S10.18-8 (Low):** stale-доки (bot.py:565, `plans/ARCHITECTURE.md` §10/§16/§17, `README.md` env-таблица/«Мониторинг») приведены к контракту 10.18.
- [x] **S10.18-9 (Low):** docstring `mask` уточнён; §9 Q4 спеки F1 синхронизирован с T-1706.
- [x] **S10.18-10 (Low):** `TestListenerFailOpen` изолирует reload `config.settings` (восстановление + выгрузка `bot`).
- [x] **S10.18-12 (Info):** backlog-задача по `memory.nostalgia_enabled` подтверждена; код Nostalgia в батче не трогается.
- [x] **S10.18-15 (Medium):** `feature_gates._master_fallback_default("dream")` = `settings.DREAM_ENABLED` (единый дефолт с воркером); регресс-тесты `TestDreamGateFallback::test_master_fallback_default_matches_worker_env_on/_off` (`test_settings_worker_sync_round1018.py`).
- [x] **S10.18-16 (Low):** удалены мёртвые sync-хелперы `_window_open`/`_daily_limit`/`_budget_reason` (`_key()` сохранён); hot-path — `*_for`-варианты; `spec.md` §4.2 синхронизирован.
- [x] **S10.18-17 (Low):** `_deep_tick` → предгейт `_deep_fixed_possible()` (глобальный `fixed` ИЛИ per-chat override в `ChatParamsCache.has_any_override`, без SQL/I/O; ключи-стикеры `note_overrides` переживают инвалидацию/`set_chat_params`); тесты `test_deep_sleep.py::test_deep_tick_skips_candidate_sql_when_disabled` / `..._proceeds_when_per_chat_override` + unit `test_chat_params.py::test_has_any_override_scans_loaded_cache_only` / `test_set_chat_params_notes_override_for_pregate`.
- [x] **Гигиена:** `test_tool_download_quality_round1017::test_adr_supersede_recorded` ищет ADR в `plans/archive/` (fallback с `plans/features/`).

## 7. Риски / ADR-конфликты

| # | Риск | Мера |
|---|---|---|
| R1 | Двойной резолв (воркер + `gates_enabled`) даёт расхождение | Один accessor; слои «master-флаг» vs «kill-switch» различимы и задокументированы |
| R2 | Pag нагрузка от per-chat чтений | `ChatParamsCache` (TTL 120с); резолв раз на чат |
| R3 | `LISTEN` не поддержан в окружении | Fail-open + WARNING; TTL — осознанная граница |
| R4 | Зависимость F2/F4/F5 от F7 | F7 — первая в раунде |
| R5 | Аналогичный разрыв в Nostalgia/Lore | Таблица + backlog (T-1764) |

**Требуется новый ADR:** да — ADR-1018-7.

## 8. Feature flag / progressive delivery
- **Флаги не вводятся** (базовая логика, решение владельца).
- **Rollout:** F7 — первая; проверка на проде сразу после деплоя (live-проверка тумблера).
- **Rollback:** `git revert` (изменения локальны, данных не пишут).

## 9. Handoff / деплой
`@Orchestrator` — план F7 готов. Спека/ADR — T-1758 (@Architect). Реализация — T-1759…T-1764 (@Builder). **Деплой — @DevOps (T-1765). Пароль сервера в репозитории НЕ хранится.**
