# Фича F7 — `memory-retention-health` (Здоровье памяти: 11864/667/40, 0 прогонов глубокого сна/воскрешений/охлаждения; retention `smart_messages` ~2M строк, БД 724 МБ, диск 8/23 ГБ)

> **Статус: ✅ IMPLEMENTED + 🔧 итерация 5 (фиксы D-2.1…D-2.8 ревью итерации 4, 16.09.2026).** Реализация — T-1836…T-1843 + T-1863/T-1864 выполнены; итерация 3 (§11) закрывает D-1…D-7 + Lows, итерация 4 (§12) — UPD4 п.1–4, итерация 5 (§13) — D-2.1…D-2.8. T-1835/T-1853 (@Architect) закрыты, T-1844 (@Reviewer/@PM) — повторное ревью. Деплой (бэкап БД + dry-run → purge) — @DevOps.
> **Spec/ADR:** создаёт @Architect — `spec.md` + **ADR-1019-6** (retention-политика `smart_messages` + включение/настройка сна/декая/воскрешений).
> **Раунд:** 10.19 (UPD2, `plans/current_task.md:130-175`). **Нумерация:** T-1835…T-1844.
> **Тип:** backend/ops (`services/dream_worker.py`, `services/summary_memory.py`, `web/api/memory_agi.py`, `config/settings.py`, `services/param_catalog.py`). **Приоритет:** **P1** (диск/БД в двух шагах от переполнения; память копит «склероз»).
> **Зависимости:** **F3/F4** (каталог/настройки с человекочитаемыми описаниями); **F8** (смежность GraphRAG). **Конфликт файлов:** `services/param_catalog.py` (F3/F4), `config/settings.py` (F4).
> **ТЗ:** UPD2 **п.6** (строка 166): «11864 факта, из них просрочено 667, не подтверждено 40; глубокий сон 0 прогонов, воскрешений 0, охлаждение 0; `smart_messages` почти 2 миллиона, БД 724 МБ, диск 8 из 23 ГБ; проработай остальные вопросы чекапа».
> **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/406/411/90/88/19**; SQLite **v10**; APP_VERSION 2.57.0.

## 0. Цель

Объяснить и привести в порядок здоровье памяти: почему 0 прогонов **глубокого сна/воскрешений/охлаждения**, что делать с 667 просроченными и 40 неподтверждёнными фактами, и ввести **retention-политику** для `smart_messages` (~2M строк) — автоматическую очистку/архивацию, чтобы не переполнить БД/диск (724 МБ БД, 8/23 ГБ свободно).

**Требуется (UPD2 п.6, строка 166):**
- Диагностика и включение/настройка **глубокого сна** (0 прогонов), **воскрешений** (0), **охлаждения/декая** (0) — объяснить и настроить.
- **Retention-политика** `smart_messages` — автоматическая очистка/архивация (рост ~2M строк).
- Объяснение метрик 11864 / 667 просрочено / 40 не подтверждено и «что делать».
- Безопасность данных: не потерять нужное; миграции/чистки — идемпотентны.

## 1. Доказательства / карта кода (HEAD `fd6acc7`)

- `web/api/memory_agi.py:357-382` — `memory_health_summary`: сейчас отдаёт `beliefs_active/archived`, `resurrections_total`, `decay_runs_total`, `last_decay_at` (**нет** overdue/unconfirmed).
- `services/database.py:2272-2284` — `count_beliefs_by_status`; `:3972-4041` — `graph_stats` (источники метрик графа/фактов).
- `services/dream_worker.py:1086-1105` — `_maybe_decay`: гейт `flags.belief_decay_enabled` (**default False** → 0 прогонов).
- `services/dream_worker.py:1107-1163` — `_decay_step`; `:1192-1246` — `_try_reanimate` (воскрешение).
- `config/settings.py:1090` — `DREAM_ENABLED=False`; `:1137` — `DEEP_SLEEP_ENABLED=False` (default OFF → 0 прогонов глубокого сна).
- `services/summary_memory.py:123` — `compress_and_purge` (точка сжатия/очистки).
- `config/settings.py:472,474` — `FULL_MEMORY_RETENTION_DAYS=30`, `ARCHIVE_MEMORY_RETENTION_DAYS=90`.
- `config/settings.py:558` — `INFINITE_RETENTION=False`; `:534` — комментарий о retention для graph.
- retention графа: `GRAPH_UNCONFIRMED_RETENTION_DAYS=14`, `GRAPH_COMPRESSION_LOG_RETENTION_DAYS=90` (см. карту @Memory).
- `services/memory_maintenance.py:286-313` — `review` (обслуживание памяти).
- **Таблица `smart_messages`** (~2M строк) — основной драйвер размера БД; политика очистки/архивации неочевидна.

## 2. Требования

- [ ] Диагностика: **почему** 0 прогонов deep sleep / resurrect / decay (флаги `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED`/`flags.belief_decay_enabled` default OFF) — зафиксировать и объяснить владельцу простыми словами.
- [ ] Включение/настройка (по решению владельца) глубокого сна/декая/воскрешений — через конфиг/UI, не хардкодом.
- [ ] **Retention-политика `smart_messages`**: автоматическая очистка/архивация по возрасту с настраиваемым сроком; безопасная (транзакционно, идемпотентно, без потери нужного).
- [ ] Метрики здоровья расширены аддитивно (R16): просрочено (667), не подтверждено (40), размер таблиц/БД.
- [ ] Настройки retention/сна — с человекочитаемыми описаниями (в связке с F3/F4).
- [ ] Замеры: размер БД/диска до/после; отсутствие деградации производительности.
- [ ] Миграции/чистки — идемпотентны, с обратным путём (политика DDL project.md).

## 3. Constraints (инварианты раунда)

- **Данные не терять безвозвратно**: предпочтительна архивация перед purge; бэкап-процедура (@DevOps).
- **R17** (без секретов/текстов фактов в логах), **R16** (аддитивные поля).
- **Каталог:** Δ только с санкцией (human-gate (c)).
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- **DDL:** санкционирован, но retention по возможности без новых таблиц; если DDL — идемпотентно + обратный путь.
- **Ревью-гейты:** полный `pytest` 0 регрессий; `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** T-1835 (@Architect, ADR-1019-6); решение владельца о включении сна/декая и сроках retention.
- **Вверх (код):** **F3/F4** — каталог/UI-паттерн.
- **Вниз:** F8 (смежность GraphRAG) — согласовать.
- **Порядок:** F3 → F4 → F7; с F8/T-1845 — свести диагностику memorise.

## 5. Definition of Done

- [x] Владельцу объяснено (простым языком), почему 0 прогонов глубокого сна/воскрешений/охлаждения, и это включено/настроено по его решению.
- [x] Retention `smart_messages` работает: старые строки архивируются/чистятся автоматически; срок настраиваем.
- [x] Метрики здоровья показывают просроченные/неподтверждённые факты (667/40) и размеры хранилищ.
- [x] Размер БД/диска стабилизирован (evidence до/после), без потери значимых данных.
- [x] Полный `pytest` **0 failed**; каталог-Δ согласован; R17-скан чист.

## 6. Чек-лист задач

- [x] **T-1835 (@Architect, гейт):** `spec.md` + **ADR-1019-6** — retention-политика `smart_messages` (срок/архивация/purge/бэкап), семантика и разблокировка deep sleep/decay/resurrect (`DREAM_ENABLED`/`DEEP_SLEEP_ENABLED`/`flags.belief_decay_enabled`), целевые значения, аддитивные метрики, Δ каталога; ответ на human-gate (c)/(e).
- [x] **T-1836 (@Builder):** retention `smart_messages` — джоб/интеграция очистки-архивации по возрасту, настраиваемый срок, идемпотентность, безопасность (архив перед purge).
- [x] **T-1837 (@Builder):** глубокий сон 0 прогонов — диагностика и включение/настройка (флаги default OFF); логирование причины пропуска.
- [x] **T-1838 (@Builder):** охлаждение/decay — включение/настройка гейта `flags.belief_decay_enabled`, проверка `decay_run`-маркеров.
- [x] **T-1839 (@Builder):** воскрешения 0 — диагностика `_try_reanimate` (условия срабатывания) и настройка.
- [x] **T-1840 (@Builder):** `memory_health_summary` — аддитивно добавить просроченные/неподтверждённые факты (667/40) и размеры хранилищ (R16).
- [x] **T-1841 (@Builder):** каталог/настройки retention и сна — человекочитаемые описания (Δ по санкции).
- [x] **T-1842 (@Builder):** тесты — retention (архив/purge/границы), идемпотентность, метрики здоровья, гейты сна/декая.
- [x] **T-1843 (@Builder):** замер БД/диска до/после; проверка отсутствия деградации; гейты — полный `pytest` 0 failed; `git diff --check` clean.
- [ ] **T-1844 (@Reviewer + @PM, гейт):** сверка DoD; безопасность чистки (нет потери нужных данных); согласованность ADR-1019-6 ↔ код; подтверждение включения/объяснения владельцу.

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | Retention/purge может удалить нужные данные | Архив перед purge; настраиваемый срок; бэкап @DevOps; T-1835 |
| R2 | Включение `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` меняет поведение/расход токенов | Настройка + бюджеты (F2/F3); постепенное включение; лог |
| R3 | Декай заархивирует «живые» убеждения | Пороги/гейт по ADR; тесты T-1842 |
| R4 | Δ каталога без санкции | Human-gate (c) |
| R5 | Retention-джоб конкурирует с воркерами за БД | Расписание/jitter; замер T-1843 |
| R6 | Метрики 667/40 могут трактоваться неверно | Пояснение в UI/доке (F3-паттерн) |
| R7 | `S10.18-12` (Nostalgia global-only) — смежный рассинхрон настроек | Учесть: настройки воркеров читать через `worker_settings`; не регрессировать |

**ADR:** требуется новый **ADR-1019-6**.

## 8. Feature flag / progressive delivery

- **Feature flag:** рекомендуется для retention/включения сна (гейты уже существуют: `flags.belief_decay_enabled`, `DEEP_SLEEP_ENABLED`). Rollout internal → тестовый чат → 100%.
- **Rollback:** выключить гейты/`git revert`; при purge — восстановление из бэкапа (процедура @DevOps).
- **Progressive delivery:** retention сначала в «dry-run»/лог-режиме (только подсчёт) → затем фактическое удаление.

## 9. Handoff / деплой

`@Orchestrator` — план F7 готов. Spec/ADR — T-1835 (@Architect). Реализация — T-1836…T-1843 (@Builder). **Деплой (SSH + бэкап БД + рестарт + live-проверка метрик/размеров) — @DevOps. Секреты в репозитории НЕ хранятся.**

## 10. 🔴 Итерация 2 — UPD3 (15.09.2026): per-chat retention `0=вечно`, guard, изоляция памяти

> **Источник:** `plans/current_task.md:184-207`. **ADR:** `../budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md`; `adr-1019-6` D1/D1a/D1b/D7 (updated). **Обновлены:** `spec.md` §3/§4.1/§4.6/§5/§9.

- [ ] **T-1853 (@Architect, гейт) — ✅ DONE (Step 2).**
- [x] **T-1863 (@Builder):** `services/retention_policy.py` (`retention_state`, `imported_history_purge_allowed`, `resolve_import_retention_days`); per-chat retention `0=вечно`; `purge_imported_history(*, chat_cutoffs: dict[int,int], …)` — allow-list guard; целевой чат (`0`) **никогда** не в purge. Единственный call-site — `memory_maintenance.run_import_retention` (вызов из крона `compress_and_purge`, throttle 6ч).
- [x] **T-1864 (@Builder):** изоляция — SQLite **v11** (`idx_smart_messages_chat_import_key UNIQUE(chat_id, import_key)`, drop глобального) + `import_checkpoints.chat_id`; тесты двух чатов (I-2/I-6).
- [ ] **Зависимость:** seed-`enforce` retention `0` для `-1002661910336` — F3 T-1859.
- [ ] **Порядок деплоя:** dry-run → бэкап → DDL v11 → purge.

## 11. 🔴 Итерация 3 — фиксы ревью Батча E (15.09.2026)

> **Источник:** ревью Батча E (D-1…D-7 + Lows). **ADR:** `adr-1019-6` D1/D1a/D2/D7 (обновлены). **Гейты:** pytest 6323 passed / 0 failed; `node --check`/JS-тесты; `git diff --check`.

- [x] **D-1 (Critical) — fail-closed chat-слой + hard-deny целевого чата:** `worker_settings.resolve_setting_with_source` → `source='error'` при недоступном `ChatParamsPool`/ошибке чтения (`ChatParamsCache.get_chat_params_checked`); `retention_policy._resolve_days` при `'error'` → `(0,'error')`; `run_import_retention` отменяет прогон целиком (`chat_layer_unavailable`); hard-deny по `enforce`-данным сида (`chat_settings_seed.enforced_eternal_chat_ids` → `source='seed_enforced'`). Тест на РЕАЛЬНОМ резолвере: целевой чат не в `chat_cutoffs`, удаления нет.
- [x] **D-2 (High) — гейт деструктивного purge:** env-only `IMPORT_RETENTION_ENABLED` (default OFF) + `IMPORT_RETENTION_DRY_RUN` (default ON); авто-крон вызывает шаг только при явном включении; ручные `manage.py retention` / `retention --apply`. Δ каталога НЕ меняется (ClassVar).
- [x] **D-3 (Medium) — disk scan вне event loop:** `asyncio.to_thread(_scan_disk, …)`.
- [x] **D-4 (Medium) — honest-контракт метрик ФС↔БД:** `db_media_rows`/`text_media_paths`/`reliable=false`/`basis='text_scan'`; UI/API не выдают эвристику за точный рассинхрон.
- [x] **D-5 (Medium) — тяжёлые COUNT:** TTL-кэш (60с / 120с) для `/api/memory/health` и `/api/status/media-health`.
- [x] **D-6 (Medium) — UI метрик здоровья памяти:** блок «Здоровье памяти» в «Мониторинге Интеллекта» (`facts_overdue/facts_unconfirmed/smart_messages_total/storage` + предупреждение при низком `disk_free`).
- [x] **D-7 (Medium) — purge строго по архиву:** `chat_max_ids` (`id <= max_id`), сверка `candidates == archived` иначе `archive_mismatch`; `candidates` не подменяется `deleted`.
- [x] **Lows:** `restore_missing_files` убран из публичного API (backlog); rebuild `import_checkpoints` в транзакции + `DROP TABLE IF EXISTS …_old` + тест повторного прогона; снят устаревший комментарий `_SCHEMA_VERSION_EDGES_FACT_ID`; тесты инварианта сида на реальном резолвере.
- [ ] **T-1844 (@Reviewer + @PM, гейт):** повторное ревью Батча E после фиксов.

## 12. 🔴 Итерация 4 — UPD4 (`plans/current_task.md:219-240`, 16.09.2026)

> **Причина:** ревью Батча E отклонило реализацию: концепция «VIP» просочилась в **код** (идентификаторы/«VIP-гарды»), не было бэкап-гейта, требовался двухэтапный гейт данных. **ADR:** `adr-1019-6` (updated), **ADR-1019-8 §D10**.

- [x] **UPD4 п.1 — «VIP» удалён из кода:** `services/vip_seed.py` → `services/chat_settings_seed.py`, `config/vip_chats.json` → `config/chat_settings_seed.json`, `tests/test_vip_seed_round1019.py` → `tests/test_chat_settings_seed_round1019.py`; `apply_chat_settings_seed`/`load_chat_settings_seed`/`enforced_eternal_chat_ids`; CLI `manage.py apply-chat-overrides`; мета-ключ `chat_settings_seed_version`; источник резолва `source='seed_enforced'`. Код-путь generic (`for entry in seed["chats"]`), нулевые вхождения `vip`/`VIP` в коде (grep-доказательство); id — только в JSON-данных и тестах.
- [x] **UPD4 п.2 — fail-safe (D-1) подтверждён:** недоступный chat-слой → `source='error'` → `allowed=False` (fallback `0`=вечно), `run_import_retention` отменяет прогон (`chat_layer_unavailable`); тест на РЕАЛЬНОМ резолвере (без monkeypatch policy): строка целевого чата НЕ в `chat_cutoffs`, удаления нет.
- [x] **UPD4 п.3 — dry-run + бэкап-гейт (D-2):** `IMPORT_RETENTION_BACKUP_CONFIRMED` (env-only, default OFF); авто-крон удаляет только при `ENABLED=true` + `DRY_RUN=false` + `BACKUP_CONFIRMED=true`, иначе dry-run + WARNING (`auto_purge_dry_run`); CLI `retention --dry-run|--apply`.
- [x] **UPD4 п.4 — двухэтапный гейт данных:** spec F7 §10 — обязательный SQL-чеклист @DevOps (`chat_profiles.chat_params` целевого чата: `retention=0`, бюджеты/фон/контекст `-1`) **до** рестарта; при расхождении — abort+откат. @Reviewer проверяет только наличие/корректность сида.
- [ ] **T-1844 (@Reviewer + @PM, гейт):** повторное ревью Батча E после UPD4 (итерация 4).

## 13. 🔴 Итерация 5 — фиксы D-2.1…D-2.8 (ревью итерации 4, 16.09.2026)

> **Причина:** ревью итерации 4 подтвердило UPD4 п.1–4 PASS, но отклонило Батч E по D-2.1…D-2.8. **Инварианты UPD4 не тронуты:** нет `VIP`/`if chat_id ==` в коде; fail-safe; dry-run+бэкап-гейт; SQL-чеклист @DevOps; каталог 437/407/412/92/90/20; SQLite v11. **Гейты:** pytest **6323 passed / 0 failed**; `node --check web/app.js`; `node tests/js/routing_test.js`; `node tests/js/vue_mount_test.js`; `git diff --check` clean.

- [x] **D-2.1 (Medium) — RecursionError при негативном env-дефолте:** `retention_policy._normalized` больше НЕ вызывает себя рекурсивно; единый `_fallback_for(...)`/`_FALLBACK_DAYS` (невалидный `IMPORT_HISTORY_RETENTION_DAYS` → 180). Тесты: `test_invalid_global_default_no_recursion`, `test_negative_env_default_purges_with_chat_layer`.
- [x] **D-2.2 (Medium) — fsync архива ДО purge:** `_flush_and_fsync` (`flush()+os.fsync`) через `asyncio.to_thread`; `ok=True` только после fsync (иначе `fail-safe` не удаляет). Тесты: `test_archive_fsync_before_first_delete` (порядок fsync→delete, непустой архив), `test_flush_and_fsync_calls_os_fsync`.
- [x] **D-2.3 (Medium) — тесты D-5/D-3-артефактов:** TTL-кэш `/api/memory/health` (`test_health_counts_cached_within_ttl`), эндпоинт `/api/status/media-health` (200 + состав полей + `reliable is False` + R17: `TestMediaHealthApi`, `TestMediaHealthEndpoint`), `_scan_disk` через `asyncio.to_thread` (`TestScanDiskOffEventLoop`).
- [x] **D-2.4 (Low) — fail-safe при нечитаемом сиде:** `enforced_eternal_chat_ids_checked` → `(ids, ok)`; `ok=False` → `source='seed_unavailable'` (purge запрещён); WARNING при пустом `enforce`; кэш разбора файла (mtime+size). Тесты: `TestSeedCheckedAndCache`, `test_unreadable_seed_denies_purge`.
- [x] **D-2.5 (Low) — docstring ↔ код:** общий хелпер `DatabaseService._delete_fts_rows`; `purge_imported_history` и `delete_smart_messages_by_ids` используют его; docstring исправлен.
- [x] **D-2.6 (Low) — «-1 дней» в UI:** `oversight` берёт нормализованный fallback из `retention_policy.normalized_retention_default()` (один источник истины).
- [x] **D-2.7 (Low) — синхронизация доков:** этот `tasks.md` (заголовок + pytest 6303→6323); `media-files-avatars-sync/tasks.md` (D-3 + тест); `tests/test_media_integrity_round1019.py` (docstring `_scan_disk` теперь backed тестом); T-1829 — артефакт [`t1829-fetch-failed-diagnosis.md`](../media-files-avatars-sync/t1829-fetch-failed-diagnosis.md).
- [x] **D-2.8 (Low) — legacy-хардкод в CLI:** `manage.py:44` `DEFAULT_TARGET_CHAT` → `LEGACY_TARGET_CHAT_ID` с явным legacy-маркером (вне бизнес-логики; id — только данные/тесты).
- [ ] **T-1844 (@Reviewer + @PM, гейт):** повторное ревью Батча E после итерации 5.
