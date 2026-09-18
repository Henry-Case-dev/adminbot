# Задачи: dossier-rebuild-async-ui-round1022

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 1 @PM (+ Шаг 2b @Architect: `spec.md` + `ADR-1022-8` **Accepted**) · Тип: backend (job-store/API) + frontend `web/**` + data-safety/rollback
> **ТЗ:** `plans/current_task.md`, **UPD3 §2** «Новая фича UI (Кнопка пересборки Досье)» (строки **252–256**) + **UPD3 §1** (строки **247–249**: вариант (а), окно 180 дней, confirmed-cleanup + JSONL-архив). Файл untracked, SSH-креды — **не цитировать, не коммитить** (R17/R18).
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION 2.57.0; прод `a923310` active.

## Цель
Дать владельцу **кнопку «Пересобрать досье»** в мини-аппе (меню Досье, карточка юзера) с выбором периода **30/90/180 дней / Всё время**: запуск **фоновой задачи** на бэкенде, **понятный прогресс-бар** («обработано 45/180 чанков»), **сохранение прогресса** при закрытии/открытии мини-аппа, **кнопка «Отмена» с откатом (rollback)** досье/фактов юзера из бэкапа, сделанного в момент старта. Пересборка идёт **тем же движком, что F1** (`memory_rebuild` + `LoreWorker`).

## ТЗ (кратко)
(1) В меню Досье — кнопка «Пересобрать досье» + период 30/90/180/Всё время. (2) Асинхронность + прогресс-бар: запуск на бэкенде фоновой задачей, фронт показывает прогресс. (3) Persistence: закрыл/открыл мини-апп — прогресс не сбрасывается, фронт делает GET статуса и рисует текущий прогресс, ничего не падает. (4) «Отмена»: бэкенд **не убивает процесс, а выполняет rollback** — восстанавливает старое досье/факты юзера из стартового бэкапа.

## Решение (Шаг 0)
**Что уже есть:**
- Досье-модалка UI: логика `web/app.js:2739-2795` (`openDossier`/`loadDossier`/`closeDossier`/`saveDossier`), стейт `web/app.js:881-893`, шаблон `web/index.html:2667-2739`, кнопка входа «Досье» `web/index.html:1681-1682`.
- API досье: `web/api/chat_lore.py:906-959` (`GET`/`PUT dossier`), сборка payload `_dossier_payload` `:838-902`; RBAC/скоуп чата `_require_chat` (`:917`/`:938`).
- Движок пересборки (F1/10.21): `services/memory_rebuild.py:400` `rebuild_dossiers(db, *, chat_ids, dry_run, limit, pipeline, backup_dir, window_hours, batch)`; pipeline `services/lore_worker.py:691-717` `rebuild_dossier_for_chat(chat_id, window_hours, limit)` (окно `smart_messages` — **только чтение**); CLI-путь `manage.py:944-1020`, guard `_memory_scope` `manage.py:848-869`.
- Безопасность F1: `_safety_backup` + `_archive_and_delete` (JSONL + сверка `candidates == archived`) `services/memory_rebuild.py:420-462`; allowlist производных `assert_derived_table` `:55-82`; инварианты `RAW_HISTORY_TABLES`/`persona_dossier_overrides`.
- Паттерн thread-safe прогресса (не переиспользуется 1:1): `services/progress_reporter.py:92-264` (мост `run_coroutine_threadsafe`, троттлинг ≥2с, same-text guard, fail-open).
- Прецедент фоновой задачи и статус-эндпоинтов: `web/api/memory_agi.py:335` (`asyncio.create_task(worker.run_once(...))`), `:455` (`deep_sleep_status`), `:530` (`cognition_status`).

**Что новое:**
- **Job-store** фоновых пересборок: `job_id → {status, chat_id, user_id, period, scanned/total, stage, created/updated_at, backup_path, error, result}` с персистентностью (переживает restart/повторное открытие TMA).
- **API:** POST запуск (period 30/90/180/all) → `job_id`; GET статус/прогресс; POST cancel. RBAC + валидация периода.
- **Frontend:** кнопка + селектор периода, прогресс-бар «X/Y чанков», восстановление при reopen (GET статуса), кнопка «Отмена» + подтверждение и отображение отката.
- **Стартовый бэкап + rollback:** снапшот производных досье/фактов юзера на старте; при отмене — восстановление из него (DELETE новых + INSERT сохранённых), идемпотентно.
- **Интеграция UPD3 §1:** окно по умолчанию **180 дней**, confirmed-cleanup мусора `graph_facts` для целевого чата `-1002661910336` с предварительным JSONL-архивом.

**Конфликт / инварианты:**
- **`imported-history-immutable`:** `smart_messages`/импорт **не мутируются** (окно — только чтение; `RAW_HISTORY_TABLES`/`assert_derived_table` сохраняются).
- **`manual-overrides-immutable`:** `persona_dossier_overrides` **не трогаются** ни пересборкой, ни rollback'ом; бэкап/восстановление — только производные `graph_facts` (`chat_meme`/`dossier_portrait`).
- **RBAC/скоуп:** кнопка и API доступны только админу чата (как `_require_chat`); без секретов в логах/отчётах (R17/R18).
- ТЗ UPD2 про «жёстко запустить CLI» уже покрыто F1; **эта фича — UI/async-обёртка** над тем же движком (не дублировать логику пересборки).

## Задачи
- [x] **T-2077** [@Architect] ADR: контракт фоновой пересборки — job-store (схема/персистентность/ретенция), статусы (`queued/running/cancelling/cancelled/done/failed/interrupted`), API (start/status/cancel), схема прогресса «X/Y чанков», **стартовый бэкап + rollback-контракт**, кооперативная отмена, интеграция с F1 (`rebuild_dossiers` + `rebuild_dossier_for_chat`), блокировка per `(chat_id,user_id)`, RBAC, откат фичи.
- [x] **T-2078** [@Builder] Job-store/менеджер фоновых задач: `job_id` → статус/период/прогресс/`snapshot_ref`/ошибка; **файловый** store (`services/dossier_rebuild_jobs.py`, `tmp→os.replace`+fsync, retention 50/7д, `asyncio.Lock`) для выживания restart и reopen TMA; thread-safe обновление прогресса (паттерн `services/progress_reporter.py:92-264`), fail-open. **Δ DDL = 0.**
- [x] **T-2079** [@Builder] API в `web/api/chat_lore.py` (или новый router): `POST /chat_lore/{chat_id}/dossier/{user_id}/rebuild` (period ∈ `30|90|180|all`) → `job_id`; `GET .../rebuild/{job_id}` статус/прогресс; `POST .../rebuild/{job_id}/cancel`; RBAC `_require_chat` + валидация периода/скоупа.
- [x] **T-2080** [@Builder] Запуск фоновой задачи (`asyncio.create_task`, прецедент `web/api/memory_agi.py:335`): маппинг period → `window_hours` (**180 → 4320**; 30→720; 90→2160; `all` → 0), вызов аддитивного `LoreWorker.rebuild_dossier_for_user(chat_id, target_user=name, window_hours=..., chunk_size=settings.DOSSIER_REBUILD_CHUNK_SIZE, progress_cb=..., cancel_cb=...)` в `services/lore_worker.py`; loop не блокируется, 409 при уже активном job для `(chat_id,user_id)`.
- [x] **T-2081** [@Builder] **Стартовый снапшот (точечный, «бэкап на старте»):** `rollback_<job_id>.jsonl` производных досье/фактов целевого юзера (`graph_facts` со `status` `confirmed`/`chat_meme`/`dossier_portrait`, `kind='fact'`, `target_user=name`) + FTS/vec-флаг; fsync; fail-closed без снапшота.
- [x] **T-2082** [@Builder] **Отмена + rollback:** кооперативный cancel (`cancel_cb` между чанками/стадиями) → архив текущих производных (`cancelled_<job_id>.jsonl`) + удаление через guard → восстановление снапшота (`INSERT OR REPLACE` по `id` + FTS; vec best-effort), идемпотентно; `persona_dossier_overrides`/`smart_messages`/beliefs/nodes/edges не трогаются; финальный статус `cancelled` + `rollback.done`.
- [x] **T-2083** [@Builder] Репортинг прогресса: `total = ceil(COUNT(окна)/chunk_size)` (дешёвый COUNT), `processed` после каждого чанка/слоя; запись в job-store с троттлингом; **fail-open**; только counts/коды в логах (R17).
- [x] **T-2084** [@Builder] Интеграция UPD3 §1: окно **180 дней** по умолчанию; confirmed-cleanup сгенерированного мусора `graph_facts` для целевого чата `-1002661910336` с **предварительным JSONL-архивом** удаляемых строк; ручные overrides не трогать.
- [x] **T-2085** [@Builder] Frontend UI: кнопка **«Пересобрать досье»** + селектор периода (**30/90/180/Всё время**) в модалке Досье (`web/index.html:2667-2739`, `web/app.js:2739-2795`); стейт в `web/app.js:881-893`; прогресс-бар «обработано X/Y чанков».
- [x] **T-2086** [@Builder] Frontend **persistence**: хранить активный `job_id` (localStorage/серверный список) и при reopen/`visibilitychange` делать GET статуса, дорисовывать прогресс/результат; корректные состояния (`running/done/failed/cancelled`), ничего не падает.
- [x] **T-2087** [@Builder] Frontend **отмена:** кнопка «Отмена» + подтверждение → POST cancel, показ отката, обновление досье после отмены/завершения; защита от гонок (повторные клики, reopen, закрытие модалки).
- [x] **T-2088** [@Builder] Тесты: API/job-store (start/status/cancel), отмена+rollback (данные восстановлены), persistence-восстановление (GET после reopen), маппинг period→окно, guard/RBAC, **неизменность `smart_messages` + `persona_dossier_overrides`**, прогресс «X/Y».
- [ ] **T-2089** [@DevOps] Деплой + живая приёмка: пересборка целевого чата через UI (прогресс-бар, reopen persistence, отмена+откат); post-check неизменности сырой истории/overrides; отчёт (R17/R18). *(Остаётся @DevOps: код/тесты готовы — pytest 6953/0; живой прогон и деплой вне @Builder.)*

## Риски
- **R1 (Critical):** rollback затирает свежие/ручные данные → откат **только производных** из стартового снапшота; `persona_dossier_overrides`/`smart_messages` неприкосновенны; сверка counts до/после (T-2081/T-2082/T-2088).
- **R2 (High):** фоновая задача живёт в процессе и теряется при restart/краше → персистентный job-store + статус `interrupted`; **авто-resume не делается** (небезопасно), доступен ручной rollback из стартового снапшота (T-2078/T-2082/T-2086).
- **R3 (High):** прогресс на большом объёме БД (~2M строк / 724 МБ, ср. R3 10.21) → `total` без полного тяжёлого скана, троттлинг, fail-open (T-2083).
- **R4 (High):** некооперативная отмена оставит частичный результат → cancel-флаги между стадиями + **обязательный rollback**, статус не «done» (T-2082).
- **R5 (Medium):** гонки/reopen во фронте, «странные» состояния → единый источник истины — job-store, идемпотентный GET (T-2086/T-2087).
- **R6 (Medium):** одновременный CLI-прогон F1 и UI-job → блокировка per `(chat_id,user_id)`, отказ при активном job (T-2077/T-2079).
- **R7 (Medium):** период «Всё время» и двойная стоимость LLM тяжелы → дефолт **180**, предупреждение для «Всё время» (T-2080).
- **R8 (R17/R18):** сырые тексты/секреты в логах/отчётах → только counts, маскирование (T-2083/T-2089).

## Зависимости / ступени вливания
- **Зависит от F1** `urgent-rebuild-dossiers-target-chat-round1022` — тот же движок пересборки + UPD3 §1 (180 дней, confirmed-cleanup + JSONL); правки `services/memory_rebuild.py`/`services/lore_worker.py` от F1 читаются **после вливания F1**.
- **Общие `web/index.html`/`web/app.js`** — ступень **F2 → F8 → F7** (`urgent-summary-aliases-ui` → эта фича → `help-ui-system2`); правки F2 вливаются первыми, Справка (F7) — последней.
- **Эксклюзив F8:** job-store-модуль + rebuild-эндпоинты в `web/api/chat_lore.py` (или новый `web/api/*`); `web/app.js` (блок Досье), `web/index.html` (модалка Досье).
- С **F6** (`telegram-send-regex-guard`) пересечений нет; канон (`plans/docs/canon/**`, `services/prompt_migrations.py`) **не трогается**.
- Флага нет в каталоге: **Δ каталога = 0** (см. Feature flag ниже).

## Feature flag / раскатка
- **Флаг:** `DOSSIER_REBUILD_UI_ENABLED` — env-only `ClassVar` (вне `param_catalog`, **Δ каталога = 0**), **default ON**; kill-switch OFF отключает кнопку/API без редеплоя.
- **Раскатка:** поэтапная `internal → 10% → 50% → 100%` **не требуется** (прецедент 10.21/10.22); при желании владельца — gradual-доставка за флагом.
- **Откат:** kill-switch OFF / `git revert` коммита фичи; DB-артефакты обратимы (rollback-снапшот + JSONL-архив — второй рубеж).
