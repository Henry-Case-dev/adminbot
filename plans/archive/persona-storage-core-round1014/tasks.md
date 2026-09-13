# Фича F2 — `persona-storage-core-round1014` (Архитектура личности: PG-хранилище + ядро)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 13.09.2026). `spec.md` + `adr-1014-1` + код готовы; pytest 5482/0.
> **Раунд:** 10.14. **Нумерация:** T-1487…T-1497 (продолжает T-1486).
> **Тип:** backend (+ PG-DDL). **Приоритет:** P0 (ядро эпика; от него зависят F3/F4/F6).
> **Зависимости:** **F1** (`persona_state` DDL). **ТЗ:** `plans/current_task.md` §2 + **UPD п.1,2,4**.
> **Эпик:** Self-Awareness / Persona round1014. **Baseline:** HEAD `2edc65b`, pytest 5392/0.

## 0. Цель

Бот получает настраиваемую личность (name/biography/system_prompt_overrides/is_aware_ai) и динамические черты
(`dynamic_traits`), обновляемые «Глубоким сном». Хранилище — **PG-таблицы** (`personas`, `persona_traits`), scope
глобально/на чат. **DDL разрешён владельцем** (UPD п.1).

**Greenfield:** `build_persona_card` (`direct_chat_service.py:1511`, `database.py:3390`) — карточка **ПОЛЬЗОВАТЕЛЯ**
(досье F8 10.13), НЕ бот. Naming-разграничение обязательно.

## 1. Требования (ТЗ §2 + UPD)

- [x] **Схема Persona** со скоупами: глобально (`is_global=true`) или per-`chat_id`; **не** `bot_settings`/`chat_params.overrides`.
- [x] **Статические:** `name`, `biography`, `system_prompt_overrides`, `is_aware_ai` (false → запрет признавать ИИ).
- [x] **Динамические:** `dynamic_traits`; DeepSleep анализирует поведение бота и пишет черты.
- [x] **Флаги ON по умолчанию**; имя/биография пусты.
- [x] **Метрики** Личности доступны API (для F4).

## 2. Целевые модули (`file:line` на HEAD `2edc65b`)

- `services/pg_db.py` — `DDL_STATEMENTS`, `PgDatabase.init`; новые таблицы + сид.
- `services/bot_persona.py` — новый: резолв/промпт-блок/UPSERT/трейты/health/name-cache.
- `services/direct_chat_service.py` — `handle` `:575` (склейка persona-блока); `build_persona_card` `:1511` НЕ ТРОГАТЬ.
- `handlers/direct_chat.py` — `_is_direct_trigger` `:127-155` (имя-триггер).
- `services/dream_worker.py` `_run_deep_once` `:1140`; `services/dream_prompts.py` (новый промпт).
- `services/param_catalog.py` `_FLAGS`; `config/settings.py`; `.env.example`.
- `web/api/routes.py` — `GET/PUT/DELETE /api/persona`, `GET /api/persona/health`.
- Тесты: `tests/test_bot_persona.py`, `tests/test_persona_prompt.py`, `tests/test_dream_persona_traits.py`,
  `tests/test_param_catalog.py`, `tests/test_direct_chat*`.

## 3. Инварианты (обновлено: DDL РАЗРЕШЁН)

- ✅ **PG-DDL разрешён**: `personas`/`persona_traits` аддитивны, идемпотентны (`IF NOT EXISTS`), с partial-unique,
  CHECK скоупа и FK `chat_id→chat_profiles(chat_id) ON DELETE CASCADE`.
- ⛔ **Персона НЕ в `bot_settings`/`chat_params.overrides`** (UPD п.1).
- ⛔ Порядок роутеров `bot.py` не трогать (искл.: DI-kwargs). `media/`/`.env` не трогать.
- **R17** (`{configured,last4}`), **R16** (id — ключ, не имя).
- **Naming:** «Persona/Dossier» 10.13 = пользователь; новая Persona = личность БОТА.
- **Каталог-Δ F2:** ровно `flags.persona_enabled` (+1); общий Δ раунда: REGISTRY 435 / GROUPS 90 / Settings 406 /
  categorized 411 / mapped 88 / TAB_RULES 19.
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`, пин-тесты каталога, R17-скан,
  русские conventional commits, атомарно.

## 4. Зависимости

- **Вверх:** **F1** (`persona_state` + self-факты).
- **Вниз:** **F3** (UI), **F4** (лента+health), **F6** (гайд). F3/F4 параллельны после F2.

## 5. Definition of Done

- [x] Persona в PG (`personas`/`persona_traits`); scope `is_global`/`chat_id` first-class; ноль ключей персоны в `bot_settings`.
- [x] Статические поля сохраняются и подхватываются в промпт; `is_aware_ai=false` → запрет.
- [x] `persona_traits` наполняется DeepSleep; cap/dedup/провенанс.
- [x] `GET/PUT/DELETE /api/persona` + `GET /api/persona/health` scope-aware; контракт для F3/F4.
- [x] Нет конфликта с F8-досье; naming задокументирован.
- [x] Полный `pytest` 0 failed (база 5392); `node --check` clean; `git diff --check` чист.

## 6. Чек-лист задач

- [ ] **T-1487 (@Architect, гейт):** spec/ADR редакции 2: PG-схема `personas`/`persona_traits`, scope/is_global,
  резолв, API, миграция/сид, где `dynamic_traits` (таблица — обоснование), промпт-блок/приоритет, name-триггер,
  Δ каталога (только `flags.persona_enabled`).
- [x] **T-1488 (@Builder):** PG DDL: `personas` (+partial unique +CHECK +FK), `persona_traits` (+индексы),
  `ALTER persona_state` (traits-колонки); идемпотентный сид глобальной пустой персоны.
- [x] **T-1489 (@Builder):** `services/bot_persona.py`: `resolve_bot_persona`, `build_persona_prompt_block`,
  `_NO_AI_DISCLOSURE_BLOCK`, `save_persona`/`delete_persona`, name-cache.
- [x] **T-1490 (@Builder):** API `GET/PUT/DELETE /api/persona` (scope, RBAC `edit_persona`, optimistic 409, 422/503);
  `GET /api/persona/health`.
- [x] **T-1491 (@Builder):** склейка persona-блока в промпт direct (`:575`); имя-триггер (`_is_direct_trigger`);
  каталог `flags.persona_enabled` + settings + `.env.example`; пин-тесты.
- [x] **T-1492 (@Builder):** DeepSleep `_run_persona_traits_once` + `PERSONA_EVOLUTION_PROMPT`; `append_traits`
  (дедуп/cap/FIFO/провенанс); `persona_state.last_trait_*`; fail-open.
- [x] **T-1493 (@Builder):** `get_traits` (ORDER BY created_at DESC) для F4; `get_persona_health`
  (traits_count/last_trait_at/extractor_status) для F4; `load_global_cache` при старте.
- [x] **T-1494 (@Builder):** тесты: PG DDL/сид идемпотентность, scope-резолв, промпт-байт-тесты, `is_aware_ai`,
  name-триггер, трейты (дедуп/cap), health, отсутствие регресса F8-досье, пин-тесты Δ.
- [x] **T-1495 (@Builder):** `node --check web/app.js`, полный `pytest` (0 failed), `git diff --check`; независимый
  пересчёт инвариантов каталога; grep отсутствия `content.persona_*` в `bot_settings`.
- [ ] **T-1496 (@PM/@Reviewer, гейт):** сверка DoD/инвариантов, проверка DDL/идемпотентности, маркерные тесты,
  naming, R17-скан; зафиксировать контракт API для F3/F4.
- [ ] **T-1497 (@Architect):** влить архитектуру персоны в `plans/ARCHITECTURE.md` (новый §) после реализации.

## 7. Открытые вопросы (закрыты владельцем)

- **F2-Q1:** storage → PG-таблицы (UPD п.1). **F2-Q2:** traits → таблица `persona_traits`. **F2-Q3:** `is_aware_ai` → код-блок.
- **F2-Q4:** блок — хвостом промпта. **F2-Q5:** пусто → байт-в-байт.

## 8. Feature flag / progressive delivery

- `flags.persona_enabled` **default True** (UPD п.2). OFF → прежнее поведение. Rollback = OFF + `git revert`;
  откат схемы — `DROP TABLE persona_traits, personas`.
