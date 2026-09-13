# Фича F5 — `settings-persistence-audit-round1014` (Багфикс сохранения настроек + реактивность параметров)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 13.09.2026). Все задачи @Builder T-1512…T-1522 закрыты; ревью-гейты (T-1523/T-1524/T-1525) открыты.
> **Раунд:** 10.14. **Нумерация:** T-1511…T-1525 (продолжает T-1510).
> **Тип:** backend + frontend. **Приоритет:** P0 (блокеры владельца).
> **Зависимости:** нет (можно параллельно F1/F2; **согласовать с активной фичей `config-read-path-audit`**).
> **ТЗ:** `plans/current_task.md`, раздел **4** («Багфикс: Сохранение настроек и реактивность параметров»).
> **Эпик:** `Epic: Self-Awareness / Persona round1014`. **Baseline:** HEAD `2edc65b`, pytest 5392/0.

## 0. Цель

Изменённые в мини-аппе параметры (особенно в разделе PERMsoc) должны **сохраняться**: немедленно
коммититься в БД, переживать переключение Global ↔ чат и рестарт `admin_bot`, и **реально применяться**
рантаймом (воркеры, RAG, LLM-клиенты), а не игнорироваться хардкод-дефолтами.

**Контекст §4 Step 0:** global-save внедрён в 10.12 (`saveBlock` `web/app.js:2431`, `saveConfigItem`
`:3214`, `saveKeyItem` `:3263`); R10.12-1 закрыт. Нужен **end-to-end read-path аудит**. Активная фича
`config-read-path-audit` (F-5) — про то же: **сверить объём, не дублировать задачи**.

## 1. Требования (дословно из ТЗ §4)

- [x] **Аудит пайплайна сохранения:** вся цепочка от Vue-компонентов до БД (PostgreSQL/SQLite); изменения
      должны немедленно коммититься в БД при нажатии «Сохранить» и гарантированно переживать рестарт
      демона `admin_bot`.
- [x] **Фикс Scope-маршрутизации:** при переключении в верхнем меню (Global ↔ Конкретный чат) введённые
      настройки должны корректно сохраняться для своего скоупа, а не перезатираться закэшированными/
      дефолтными значениями при рендеринге.
- [x] **Привязка к рантайму:** полная ревизия **ВСЕХ** изменяемых параметров мини-аппа; сохранённые в БД
      значения реально подхватываются процессами бота (воркеры, RAG, LLM-клиенты), а не игнорируются
      хардкод-дефолтами.

## 2. Целевые модули (`file:line` на HEAD `2edc65b`)

- **Запись (frontend):** `saveBlock` `web/app.js:2431`, `saveConfigItem` `:3214`, `saveKeyItem` `:3263`;
  `api()` авто-`X-Chat-Id` `:1253-1254`; `scope-switcher`/`activeChatId`; `routes.py:414-417` (422 при
  `per_chat=false`).
- **Хранилище:** `services/chat_params.py` (`is_dm_scope` `:31-35`, `overrides` `:41-85`, `gates`,
  DM-default OFF `:397-412`); `services/pg_db.py` (**DDL разрешён**: `personas`/`persona_traits`/`persona_state`); `services/database.py` (v9); `services/config_cache.py`.
- **Чтение/рантайм:** `services/hot_config.py`/`ConfigCache` `hot.get(key, default)`; `services/param_catalog.py`
  (касты по типу); `web/api/routes.py`; `/debug_config` (дамп из RAM, формат `key = value`) — инструмент
  верификации (см. `config-read-path-audit/tasks.md`).
- **Потребители рантайма (верифицировать «сохранено ↔ подхвачено»):**
  - воркеры: `services/dream_worker.py`, `services/lore_worker.py`, `services/nostalgia_worker.py`,
    `services/summary_memory.py`, `services/memory_health.py`, `services/memory_maintenance.py`;
  - RAG: `services/summary_memory.py` (`build_rag_context`/`get_rag_context`/`_graph_fact_weight`),
    `services/tool_router.py`;
  - LLM-клиенты/провайдеры: `services/llm_client.py`, `services/llm_probe.py`, `services/worker_budget.py`,
    `services/status_service.py`;
  - гейты: `services/feature_gates.py`.
- Тесты: `tests/test_hot_config*`, `tests/test_config_cache*`, `tests/test_hot_migration*`, `tests/test_param_catalog*`,
  `tests/test_webapp_*`; новый `tests/test_settings_persistence_round1014.py`.

## 3. Инварианты (constraints — не нарушать)

- ✅ **PG-DDL разрешён** (UPD п.1): новые таблицы `personas`/`persona_traits`/`persona_state` — часть аудита персистентности.
- ✅ **SQLite переведён на v9** (F1, origin `bot_self_reply`); для F5 это означает новый write-watcher миграции, сам F5 v9 не бампает.
- ⛔ Порядок роутеров `bot.py` не трогать (искл.: DI-kwargs).
- **Каталог-инварианты: REGISTRY 427 / GROUPS 90 / Settings 399 / categorized 403 / mapped 88 / TAB_RULES 19.**
  Новые параметры — только санкционированный Δ + пин-тесты.
- **Согласование с активной F-5 `config-read-path-audit`:** не дублировать задачи T-651/T-652 (касты), не
  дублировать grep-аудит `settings\.` — переиспользовать/сослаться, зафиксировать границы в §7.
- **R17:** секреты — `{configured,last4}`; не логировать. **R16:** id — ключ, не имя.
- `media/`/`.env` не трогать; никаких хардкод-дефолтов в рантайме вместо `hot.get`.
- **Ключевая проверка:** «сохранено в БД ↔ подхвачено рантаймом» для КАЖДОГО изменяемого параметра.
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`, пин-тесты каталога, R17-скан,
  русские conventional commits.

## 4. Зависимости

- **Вверх:** нет.
- **Вниз:** косвенно F2/F3/F6 (персона сохраняется через тот же пайплайн; после аудита он надёжен).
- **Порядок:** можно параллельно F1/F2 (разные файлы), но **`web/app.js` делят F3/F4/F7** — согласовать
  ступени вливания.

## 5. Definition of Done

- [x] Инвентаризация ВСЕХ изменяемых параметров мини-аппа выполнена (таблица §6); для каждого —
      классификация SavePath / Scope / RuntimeConsumer / статус.
- [x] Цепочка Vue → API → БД проtrace-ена; найденные дефекты записи закрыты.
- [x] Scope-маршрутизация Global ↔ чат: переключение не затирает введённое; значения читаются из своего
      скоупа; 422/per_chat-кейсы обработаны.
- [x] Сохранённое переживает рестарт `admin_bot` (проверено сквозной процедурой).
- [x] Для каждого параметра подтверждено, что рантайм читает БД (через `hot.get`/`/debug_config`), либо
      осознанно зафиксировано исключение с пометкой.
- [x] Границы с `config-read-path-audit` задокументированы (нет дублей).
- [x] Полный `pytest` — **0 failed** (база 5392); `node --check web/app.js` clean; `git diff --check` чист.

## 6. Чек-лист задач

- [ ] **T-1511 (@Architect, гейт):** spec/ADR: методика аудита и формат матрицы; границы с
  `config-read-path-audit`; таксономия дефектов (потеря при scope-свитче / потеря при рестарте / запись не
  доходит / рантайм игнорирует); критерии «осознанного исключения»; план фиксов; Δ каталога (если нужен).
- [x] **T-1512 (@Builder, инвентаризация):** составить полную таблицу изменяемых параметров мини-аппа —
  категория/группа (`models`, `keys`, `prompts`, `limits`, `flags`, `reactions`, `content`), `per_chat`
  (true/false), тип, widget, API-роут, БД-ключ/PG-ключ, рантайм-потребитель. **Дополнительно (UPD):** dedicated-API
  `GET/PUT/DELETE /api/persona` (PG `personas`), `GET/POST /api/info/guide` (PG `content.intelligence_guide`),
  provider-блок `intel_reflection` (models/keys, per_chat=False), флаги `persona_enabled`/`bot_self_awareness_enabled`.
  Зафиксировать в отчёте фичи.
- [x] **T-1513 (@Builder, save-path):** проtrace-ить `saveBlock` `:2431` / `saveConfigItem` `:3214` /
  `saveKeyItem` `:3263` → `api()` → `routes.py` → `chat_params`/`bot_settings`/`config_cache`; найти места,
  где запись теряется/не коммитится; починить.
- [x] **T-1514 (@Builder, scope):** Global ↔ чат: проверить `X-Chat-Id`, `per_chat`, 422 `routes.py:414-417`,
  `chat_params.overrides`/`gates`; устранить перезатирание закэшированными/дефолтными значениями при
  рендеринге; добавить явный сброс черновика при смене скоупа.
- [x] **T-1515 (@Builder, restart):** гарантировать немедленный commit в БД (не только в кэш/память);
  сквозной тест «сохранил → `systemctl restart admin_bot` → значение на месте».
- [x] **T-1516 (@Builder, read-path):** сверка с активной `config-read-path-audit`: grep `settings\.` в
  рантайм-пути → каждое прямое чтение мигрировать на `hot.get` ИЛИ осознанно оставить с пометкой
  (**не дублировать** уже закрытые задачи; сослаться на `config-read-path-audit/tasks.md`).
- [x] **T-1517 (@Builder, рантайм-воркеры):** для воркеров (`dream_worker`, `lore_worker`, `nostalgia_worker`,
  `summary_memory`, `memory_health`, `memory_maintenance`) проверить, что лимиты/флаги читаются из БД, а не
  из import-time дефолтов; исправить и покрыть тестом.
- [x] **T-1518 (@Builder, рантайм-RAG):** RAG (`build_rag_context`/`get_rag_context`/`_graph_fact_weight`,
  `tool_router`) — сохранённые веса/доли/пороги реально влияют; исправить и покрыть тестом.
- [x] **T-1519 (@Builder, рантайм-LLM):** LLM-клиенты/провайдеры (`llm_client`, `llm_probe`,
  `worker_budget`, `status_service`) — base_url/модели/ключи/бюджеты читаются из БД; `model_source` не
  рассинхронен (учесть R10.9-1). R17: только `{configured,last4}`.
- [x] **T-1520 (@Builder, verification):** сквозная процедура верификации: изменить параметр в админке →
  `/debug_config <ENV_NAME>` показывает новое значение; описать шаги в отчёте.
- [x] **T-1521 (@Builder, tests):** регресс-тесты: save-path (per_chat true/false), scope-переключение,
  restart-персистентность, рантайм-чтение (воркер/RAG/LLM), **dedicated-API persona/guide**, `intel_reflection`
  (probe/фоллбэк), границы с `config-read-path-audit`; `tests/test_settings_persistence_round1014.py`.
- [x] **T-1522 (@Builder):** `node --check web/app.js`, полный `pytest` (0 failed, дельта), `git diff --check`
  clean; независимый пересчёт инвариантов каталога (если Δ).
- [ ] **T-1523 (@PM):** отчёт-инвентарь (§6 таблица) + список найденных дефектов и их статусов; человекопонятный
  итог владельцу.
- [ ] **T-1524 (@Reviewer, гейт):** независимая проверка save/read-path и scope-кейсов, **dedicated-API persona/guide**,
  provider-блока `intel_reflection`, R17-скан, сверка с `config-read-path-audit` (нет дублей/дыр).
- [ ] **T-1525 (@PM/@DevOps, гейт):** live-чеклист на Android/Telegram (PERMsoc + другие разделы); при
  необходимости — верификация на проде после деплоя.

## 7. Границы с активной F-5 `config-read-path-audit` (обязательно к сверке)

Активная фича `plans/features/config-read-path-audit/tasks.md` покрывает: остаточный grep-аудит `settings\.`,
import-time чтения (пример `UserIdFilter(hot.get(...))` в `alan.py:120`), верификацию через `/debug_config`,
тесты `test_hot_config`/`test_config_cache`/`test_hot_migration`.
Разграничение раунда 10.14:
- **F-5 (активная):** read-path config, точечно.
- **F5 round1014:** **запись** + **scope-маршрутизация** + **рестарт-персистентность** + **инвентаризация
  ВСЕХ параметров**. Пересечение по read-path — сослаться, не дублировать (решение @Architect T-1511).

## 8. Открытые вопросы (@Architect → владелец)

- **F5-Q1:** как разграничить задачи с активной `config-read-path-audit` (что переносим, что дублируем-нет)?
- **F5-Q2:** «немедленно коммититься» — sync-await до ответа UI или optimistic UI + background commit?
- **F5-Q3:** нужен ли каталог-Δ (напр. per_chat для ранее глобальных ключей) при фиксе scope-маршрутизации?
- **F5-Q4:** рантайм-потребители, читающие import-time (декораторы/фильтры) — выносить за `cache.init` или
  фиксировать фолбек-семантику (согласовать с F-5)?
- **F5-Q5:** объём ручной live-верификации на проде (все группы или выборка)?

## 9. Feature flag / progressive delivery

- **Feature flag:** не требуется (фикс существующего пайплайна). Rollback = `git revert`.
- **Progressive delivery:** неприменимо; верификация — статически + live (владелец/QA), опц. прод-чек после
  деплоя.
