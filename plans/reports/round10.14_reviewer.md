# Step 5 — STRICT REVIEW раунда 10.14 «Самосознание и Личность бота»

> **Ревьюер:** @Reviewer (Senior Principal / Validator / Security). **Дата:** 13.09.2026.
> **Baseline:** HEAD `2edc65b`. **Объём:** все незакоммиченные изменения (`git diff` + untracked) по 8 фичам (F1–F8).
> **Метод:** построчный аудит диффа/untracked + чтение `spec.md`/`tasks.md`/ADR + прогон Validator + сверка инвариантов.

## ВЕРДИКТ: **Rejected**

Ключевые требования контракта не доведены end-to-end: optimistic-конкурентность персоны (`409`) объявлена в spec/DoD и tasks, но физически недостижима (токен `updated_at` нигде не отдаётся и не отправляется); RBAC-действие `edit_persona` не зарегистрировано в `ACTIONS_TREE`, поэтому его невозможно выдать; новые per-chat ключи (`flags.persona_enabled`, `flags.bot_self_awareness_enabled`, `limits.graph_fact_weight_bot`) в рантайме читаются только глобально через `hot.get`, т.е. per-chat override сохраняется в БД и молча игнорируется — ровно тот класс дефекта, который F5 обязана была закрыть. Дополнительно отчёт-инвентарь F5 устарел/неполон (410 строк vs categorized 411, «F6 не реализована» — уже неверно).

---

## 1. Число задач: подтверждено/не подтверждено

Всего в 8 `tasks.md`: **72** (T-1477…T-1548). Закрыто `[x]`: **54**. Открыто `[ ]`: **18**.

**Подтверждение:** все `@Builder`-задачи закрыты. Все 18 открытых — исключительно гейты/пост-задачи `@Architect/@PM/@Reviewer/@DevOps`. Однако 5 из них — это `@Architect`-гейты, которые, по условию приёмки, должны быть доведены к финалу, а **T-1497 не является гейтом** и фактически не выполнена (см. M4).

| Фича | Открытые `[ ]` |
|---|---|
| F1 anti-echo-self-reply | T-1486 (@PM/@Reviewer, гейт) |
| F2 persona-storage-core | **T-1487 (@Architect, гейт)**, T-1496 (гейт), **T-1497 (@Architect, post-impl — НЕ гейт)** |
| F3 persona-ui-tab | T-1503 (гейт), T-1504 (live) |
| F4 persona-traits-ribbon | T-1510 (гейт) |
| F5 settings-persistence-audit | **T-1511 (@Architect, гейт)**, T-1523, T-1524, T-1525 |
| F6 help-guide-integration | **T-1526 (@Architect, гейт)**, T-1533, T-1534 |
| F7 status-layout-reorder | **T-1535 (@Architect, гейт)**, T-1540 |
| F8 self-reflection-llm-provider | **T-1541 (@Architect, гейт)**, T-1548 |

Статусы «🟢 IMPLEMENTED» проставлены во всех 8 `tasks.md`. При этом `plans/backlog.md` для раунда 10.14 всё ещё держит `🟣 SPEC_READY` / «Builder не начат» (Low, см. L1).

---

## 2. Таблица по фичам (соответствие контракту)

| Фича | Вердикт | Подтверждено (доказательства) | Расхождения |
|---|---|---|---|
| **F1** anti-echo-self-reply | ✅ по коду | origin `bot_self_reply` в CHECK (`database.py:73-80`); вес 0.2 (`summary_memory.py:220-222`, `settings.py:813`); важность 2 (`database.py:97`); метка `[Источник: Я сам (Бот)]` (`summary_memory.py:312`); LLM-экстрактор + фоллбэк + fail-safe (`self_reflection.py:93-133`); анти-эхо (`summary_memory.py:315-320`, `direct_chat_service.py:1826-1828`); исключения self (`database.py:2072,2477,3424,3445,3692-3698`) | нет по F1-ядру |
| **F2** persona-storage-core | ⚠️ с дефектами | PG DDL идемпотентен + CHECK/FK/partial-unique (`pg_db.py:209-283`); scope-резолв per-chat→global→empty (`bot_persona.py:172-192`); API GET/PUT/DELETE/health (`routes.py:1418-1525`); `is_aware_ai=false`-блок (`bot_persona.py:32-36,226-228`); traits cap/дедуп/FIFO (`bot_persona.py:423-466`) | **H1** optimistic-409 недостижим; **H2** RBAC `edit_persona` не выдаётся; **H3** per-chat флаги игнорируются |
| **F3** persona-ui-tab | ✅ | Карточка Hub `#/ai/persona` (`app.js:296-300`), `ROUTE_TO_TAB`/`ROUTE_PARENT` (`app.js:607,629`), special-screen 3 поля + чекбокс (`index.html:3110-3171`), scope-гвард (`app.js:4300-4346`); `TABS` не тронут (19, `app.js:18`) | **H2** (видимость зависит от незарегистрированного action) |
| **F4** persona-traits-ribbon | ✅ | 3-я лента (`index.html:2955-2970`), grid 3→1 (`index.html:698`), переиспользован `_ribbonLoop` (`app.js:1252-1254,5053-5068`), адаптер/`fmtDayMonth` (`app.js:5037-5049,5090-5099`), метрики Сводки (`index.html:1820-1839`, `app.js:1120-1128,2098-2105`) | нет |
| **F5** settings-persistence-audit | ⚠️ с дефектами | R10.9-4 инвалидация health (`status_service.py:333-356`, `routes.py:71-84,740`); R10.4-7 per-chat cap (`direct_chat_service.py:1816-1820`); scope-сброс (`app.js:1741-1747`) | **H3** per-chat флаги/вес не читаются; **M1** inventory/report устарели |
| **F6** help-guide-integration | ✅ | ключ `content.intelligence_guide` (`param_catalog.py:396-399`); идемпотентный сид (`config_cache.py:232-254`); `get_guide/save_guide` (`info_service.py:78-77,161-198`); `GET/POST /api/info/guide` (`routes.py:1115-1156`); DOMPurify self-host (`index.html:3615`), все `v-html` санитайзятся (`index.html:3193,3206,3230,3248`); XSS-юниты + fail-closed (`app.js:4207-4219`) | **M2** относительный путь сид-файла |
| **F7** status-layout-reorder | ✅ | Порядок Сводка→Сердцебиение→Бот→Сервер→Мониторинг→Доступность→История (`index.html:1719/2832/2859/2885/2920/2989/3021`), маркер-тест `TestStatusLayoutOrderF7` | нет |
| **F8** self-reflection-llm-provider | ✅ | +4 ключа (`param_catalog.py:510-515,635-645`, `settings.py:444-455`); роль `reflection` (`llm_client.py:895-900`); probe (`llm_probe.py:39-46,74-80,120-124`); provider-блок (`app.js:491-501`), `providerCoveredKeys` рекурсивен (`app.js:3094-3106`); `.env.example` 4 плейсхолдера | нет |

---

## 3. Проблемы по severity

### [High] H1. Optimistic-409 персоны недостижим (токен `updated_at` не отдаётся/не отправляется)
- **Файлы/строки:** `web/api/routes.py:1387-1399` (`_persona_scope_payload` — нет `updated_at`), `web/api/routes.py:1475-1490` (PUT возвращает тот же payload); `services/bot_persona.py:135-143` (`BotPersona` не несёт `updated_at`), `services/bot_persona.py:361-407` (`save_persona` возвращает `BotPersona` без токена); `web/app.js:4347-4360` (`savePersona` шлёт тело без `updated_at`); `web/app.js:4366-4368` (обработка 409 — мёртвый код).
- **Проблема:** сервер сравнивает `expected_updated_at` с текущим `updated_at` строки (`bot_persona.py:374-377`), но `updated_at` не входит ни в GET-, ни в PUT-ответ. Клиент не может узнать текущий токен и прислать его; UI всегда шлёт `updated_at=null`, при котором проверка конфликта вообще отключается (`if expected_updated_at is not None and existing is not None`). Тест `test_conflict_409` (`tests/test_persona_api.py:220-229`) подменяет `save_persona` моком и не ловит разрыв.
- **Почему важно:** DoD F2/§3.5 и T-1490 прямо требуют «optimistic-токен updated_at (409)», spec §5 включает `409` в контракт. Фактически конкурентные правки персоны из UI перетирают друг друга без предупреждения — это потеря пользовательских данных.
- **Требуемый фикс:** прокинуть `updated_at` в `BotPersona` (или возвращать отдельным полем), включить его в `_persona_scope_payload` и в ответ PUT; в `loadPersona` сохранять токен в `personaMeta`, в `savePersona` отправлять `updated_at`; нормализовать сравнение (epoch/ISO в одном формате). Добавить сквозной тест «GET→PUT с устаревшим токеном→409», а не только monkeypatch-мок.

### [High] H2. RBAC-действие `edit_persona` не зарегистрировано — право невозможно выдать
- **Файлы/строки:** `services/permissions.py:40-49` (`ACTIONS_TREE` содержит только `edit_info`, `control.*`, `debug.config`); `web/api/routes.py:1364-1374` (`match_permission(perms, "edit_persona")`); `web/app.js:2817-2823` (`hasPerm('edit_persona')`); `web/api/routes.py:862-867` (валидация ролей с `known_actions=ACTION_IDS` даст 422 на `edit_persona`).
- **Проблема:** spec F2 §5 и T-1490 задают RBAC «global — action `edit_persona`; chat — action `edit_persona` или секция `content`». Действия нет в каталоге `ACTIONS_TREE`, а `validate_permissions` отвергает неизвестные actions → выдать его через `/api/roles` нельзя (только прямая правка БД). Ветка `match_permission(..., "edit_persona")` и UI-проверка `hasPerm('edit_persona')` фактически мертвы; работает лишь фолбэк на `section.content`.
- **Почему важно:** контракт RBAC не реализован; администратор не может делегировать правку персоны точечно, не выдавая всю секцию content.
- **Требуемый фикс:** добавить `edit_persona` в `ACTIONS_TREE` (или явно зафиксировать в spec, что право не вводится, и убрать мёртвые ветки). Тест: роль с `edit_persona` валидируется и даёт доступ; без неё — 403.

### [High] H3. Новые per-chat ключи читаются только глобально (`hot.get`), per-chat override игнорируется
- **Файлы/строки:** `services/direct_chat_service.py:589` (`hot.get("flags.persona_enabled", …)`); `services/direct_chat_service.py:1007` (`hot.get("flags.bot_self_awareness_enabled", …)`); `services/bot_persona.py:204` (тот же флаг); `services/dream_worker.py:1276`; `services/summary_memory.py:220-222` (`_origin_weight` → `hot.get("limits.graph_fact_weight_bot", …)`) и `services/summary_memory.py:2070,2077-2078` (`memorize_self_reply` — флаг/вес/TTL).
- **Проблема:** каталог объявляет `flags.persona_enabled`, `flags.bot_self_awareness_enabled`, `limits.graph_fact_weight_bot` как `per_chat=True` (проверено: `cli> param_catalog.get_by_pg_key(...).per_chat == True`), UI сохраняет их в `chat_params.overrides` (X-Chat-Id). Но все рантайм-потребители читают глобальное значение `ConfigCache`; `get_chat_param` (который учитывает override) не используется. Для сравнения: `flags.chat_context_budgets_enabled` читается корректно per-chat (`direct_chat_service.py:806-810`).
- **Почему важно:** это ядро задачи F5 §4 («Фикс Scope-маршрутизации… значения читаются из своего скоупа», «Привязка к рантайму»). Админ, выключив самоосознание/личность для конкретного чата, получит их включёнными. F5-отчёт (`report.md:56-67`) ошибочно классифицирует это как «OK».
- **Требуемый фикс:** в async-путях резолвить эти ключи через `get_chat_param(chat_id, key, hot.get(key, default))` (`_cp_g`) — и в `_origin_weight`/`memorize_self_reply`/`handle`/`_build_rag_block`/`dream_worker`; `build_persona_prompt_block` принимает резолвнутый `enabled` параметром (sync-функция). Либо — если per-chat не задуман — перевести ключи в `per_chat=False` и зафиксировать это в spec. Добавить регресс-тест «override OFF для чата → self-факт не пишется / persona-блок пуст».

### [Medium] M1. F5-отчёт и inventory устарели/неполны относительно финального каталога
- **Файлы/строки:** `plans/features/settings-persistence-audit-round1014/inventory.tsv` — 410 строк данных (411 с шапкой), при `categorized == 411`; отсутствует `content.intelligence_guide`. `plans/features/settings-persistence-audit-round1014/report.md:5` (REGISTRY 434 / categorized 410), `report.md:9` («410 строк»), `report.md:31-33` («`/api/info/guide` … ещё не существует (F6 … не реализована)»).
- **Проблема:** отчёт-инвентарь — deliverable T-1512/T-1523; F6 уже реализована, каталог финально 435/406/411. Инвентарь не содержит гайд-ключ и не отражает dedicated `/api/info/guide`, который T-1512 (UPD) прямо требовала внести. Утверждение про несуществующий F6-роут противоречит коду.
- **Почему важно:** матрица «все изменяемые параметры → save/scope/runtime» неполна; гейт T-1524 сверяется именно с ней.
- **Требуемый фикс:** пересобрать `inventory.tsv` из `REGISTRY` (411 categorized, включая `content.intelligence_guide`), актуализировать цифры и статус F6 в `report.md`.

### [Medium] M2. Сид гайда F6 зависит от CWD (относительный путь)
- **Файлы/строки:** `services/info_service.py:77` (`GUIDE_SEED_FILE = "plans/docs/intelligence_user_guide.md"`), `services/info_service.py:81-89,174`; `services/config_cache.py:239`.
- **Проблема:** путь относительный; при запуске демона с иным `WorkingDirectory` (systemd/docker) `open` даст `OSError` → сид молча пропускается (`config_cache.py:242-245`), а `get_guide` отдаёт `DEFAULT_GUIDE_MARKDOWN=""`. Гайд в проде будет пустым без явной ошибки.
- **Почему важно:** production readiness/конфигурируемость; источник истины гайда — БД, но первичное наполнение ломается.
- **Требуемый фикс:** базировать путь от файла модуля/корня проекта (`Path(__file__).resolve().parents[1]`) или вынести в настройку (`INFO_GUIDE_SEED_FILE`) как `INFO_TEXT_FILE`; тест с не-корневым CWD.

### [Medium] M4. Не закрыта T-1497 (ARCHITECTURE.md) и не обновлён README эпика
- **Файлы/строки:** `plans/features/persona-storage-core-round1014/tasks.md:88` (`T-1497` — `[ ]`); `plans/ARCHITECTURE.md` (раздел о новой Persona отсутствует, grep не находит новых сущностей); `plans/current_task.md:52` (актуализация README в финале — README не изменён).
- **Проблема:** T-1497 — не гейт, а обязательная пост-задача Architect; README-требование ТЗ не выполнено.
- **Требуемый фикс:** внести §Persona в `plans/ARCHITECTURE.md`; актуализировать README (или перенести в финал деплоя с явной отметкой).

### [Low] L1. `plans/backlog.md` держит `🟣 SPEC_READY` для раунда 10.14, тогда как все фичи `🟢 IMPLEMENTED`
- **Файл:** `plans/backlog.md` (заголовок раунда 10.14). Расхождение статусов.

### [Low] L2. Дублирование логики бейджа scope
- **Файлы/строки:** `web/app.js:1130-1133` (`personaScopeBadge`) дублирует `web/app.js:1288-1291` (`scopeLabel`). Достаточно переиспользовать `scopeLabel`.

### [Low] L3. Приватный реэкспорт `_GUIDE_KEY` через `config_cache`
- **Файлы/строки:** `web/api/routes.py:27` импортирует `_GUIDE_KEY` из `services.config_cache` (там он реэкспорт `services.info_service.GUIDE_KEY`). Импорт приватного имени через чуждый модуль; импортировать напрямую из `info_service`.

### [Low] L4. Анти-эхо добавляется ПОСЛЕ обрезки cap
- **Файлы/строки:** `services/direct_chat_service.py:1816-1828`. `content[:cap]` применяется до добавления `_SELF_ECHO_INSTRUCTION`, поэтому итоговый `<RAG_Memory>` превышает `limits.graph_rag_context_max_chars` примерно на длину инструкции. Инструкцию стоит добавлять до расчёта бюджета.

### [Low] L5. Hot-path оверхед на каждый direct-ответ
- **Файлы/строки:** `services/direct_chat_service.py:589-597` (при каждом сообщении: `resolve_bot_persona` + `get_traits` = 2 доп. PG-запроса), `services/self_reflection.py:67-80` (PG-write `persona_state` на каждый ответ). Кэш трейтов/статуса отсутствует. Функционально верно, но требует внимания по нагрузке.

### [Low] L6. Устаревший docstring теста
- **Файл:** `tests/test_migrate_direct_chat_v2_script.py:7` — «финальный user_version == 8» (фактически 9).

### [Low] L7. Провал `pytest` оставляет 12 «leaked aiosqlite connections»
- **Доказательство:** вывод Validator: `WARNING: closed 12 leaked aiosqlite connection(s)`. Стоит проверить, что новые тесты закрывают `DatabaseService` (возможно, часть — pre-existing).

---

## 4. Результаты Validator (запущено @Reviewer)

| Команда | Результат |
|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5573 passed, 1 warning** (0 failed), 61.75s. Warning: `WARNING: closed 12 leaked aiosqlite connection(s)`. Exit 0 |
| `node --check web/app.js` | `NODE_CHECK_OK`, exit 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` (DOMPurify недоступен в среде — ожидаемый fail-closed warn), exit 0 |
| `git diff --check` | чисто, exit 0 |

Заявленные в `tasks.md` числа (`5428/5482/5508/5527/5573`) противоречат друг другу (разные снапшоты по фичам) — это косметика, но финальный прогон подтверждает **5573/0**.

---

## 5. Инварианты (актуальные) — сверено

| Инвариант | Статус | Доказательство |
|---|---|---|
| REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / TAB_RULES 19 | ✅ | `test_param_catalog.py:78,266,336`; `test_frontend_tab_mapping.py:47-49,82-84`; независимый пересчёт `cli` |
| R17 `{configured,last4}`, ключи не логируются | ✅ | R17-скан нового кода: `self_reflection.py:119,127` (только `type(exc).__name__`), `bot_persona`, `routes` — значений ключей в логах нет |
| R16 (id — ключ, не имя) | ✅ | Персона/черты — id/chat_id; name-триггер — имя для UX, не ключ хранения |
| Порядок роутеров `bot.py` (только DI) | ✅ | `bot.py` +6 строк: только `load_global_cache()` (`bot.py:829-833`) |
| `media/` и `.env` не трогать | ✅ | `git status` — изменён только `.env.example` (плейсхолдеры) |
| Новых CDN нет | ✅ | DOMPurify self-host `web/static/vendor/dompurify-3.4.15.min.js` (`index.html:3615`) |
| SQLite v9 / CHECK 11 origins / FTS+vec | ✅ | `database.py:57,73-80,919-996`; тесты `test_graph_facts_origin_v9.py` (все 16 колонок, FTS-хит, vec-rowid, no-op, from scratch) |
| Reverse-миграция документирована | ✅ | ADR-1014-2 §D2 `adr-1014-2-anti-echo-self.md:33`; F1 `tasks.md:104` |
| `TABS.length == 19` не изменён | ✅ | `app.js:18` (persona — special-screen, не в `TABS`/`TAB_RULES`) |
| Никаких `v-html` без санитайза | ✅ | `index.html` все 4 `v-html` → `sanitized*`/`sanitizeHtml`; `app.js:4207-4219` fail-closed |
| SQL-инъекции | ✅ | Все новые запросы параметризованы (`$1..$n`/`?`); динамика — только placeholder-индексы |

---

## 6. Что исправить @Builder (минимально достаточный чек-лист)

1. **[H1]** Отдавать `updated_at` персоны в `GET/PUT /api/persona` и отправлять его из UI; сквозной тест `GET → PUT(устаревший токен) → 409`; убрать мёртвую обработку 409 или сделать её рабочей.
2. **[H2]** Зарегистрировать `edit_persona` в `ACTIONS_TREE` (`services/permissions.py`) с тестом роли; либо официально снять право из spec/кода (убрать мёртвые ветки) — решение зафиксировать в spec.
3. **[H3]** Резолвить `flags.persona_enabled`, `flags.bot_self_awareness_enabled`, `limits.graph_fact_weight_bot` через `get_chat_param` в async-путях (`direct_chat_service`, `summary_memory`, `dream_worker`) и прокидывать результат в `build_persona_prompt_block`; регресс-тест per-chat OFF. Либо перевести эти ключи в `per_chat=False`.
4. **[M1]** Пересобрать `inventory.tsv` (411 categorized, +`content.intelligence_guide`, +`/api/info/guide`) и актуализировать `report.md` (цифры 435/406/411, статус F6).
5. **[M2]** Сделать путь сид-файла гайда абсолютным/конфигурируемым; тест при не-корневом CWD.
6. **[M4]** Внести §Persona в `plans/ARCHITECTURE.md`; закрыть/прокомментировать открытые `@Architect`-гейты (T-1487/1511/1526/1535/1541) и T-1497.
7. **[L1–L7]** Актуализировать статус раунда в `backlog.md`; убрать дубль `personaScopeBadge`→`scopeLabel`; импортировать `GUIDE_KEY` из `info_service`; перенести анти-эхо до обрезки cap; поправить docstring v8→v9; разобраться с утечкой aiosqlite-соединений.

---

**Итог: код отклонён. Возврат на доработку @Builder.**

---

# Повторное ревью (итерация 2)

> **Ревьюер:** @Reviewer. **Дата:** 13.09.2026. **Baseline:** HEAD `2edc65b` + рабочее дерево (итерация 2 @Builder).
> **Метод:** построчная проверка исправлений по `file:line` + независимый прогон Validator. Код не правился.

## ИТОГОВЫЙ ВЕРДИКТ: **Approved**

Все три High-блокера (`H1`, `H2`, `H3`) и оба Medium (`M1`, `M2`) закрыты фактически и подтверждены кодом/тестами; Validator зелёный. `M4` в части README закрыт, часть `ARCHITECTURE.md` — штатная пост-задача `@Architect` (T-1497, пишется ПОСЛЕ аппрува — прецедент §33/§34, где архитектурные разделы содержат «@Reviewer Approved»), поэтому аппрув кода не блокирует.

## 1. Подтверждение исправлений по severity

| ID | Статус | Доказательство (file:line) |
|---|---|---|
| **H1** optimistic-409 | **Подтверждено** | `services/bot_persona.py:148` (`updated_at` в `BotPersona`); SELECT `updated_at` (`:40,44`); `UPSERT … RETURNING updated_at` (`:57,69`); нормализация токена `_ts_key` + сравнение (`:269-289,408-414`); `save_persona` возвращает токен (`:445-446`); `_persona_scope_payload` отдаёт `updated_at` (`web/api/routes.py:1402`) и PUT его возвращает (`:1494`); UI шлёт токен (`web/app.js:4355`) и 409-обработчик перезагружает персону (`:4368-4370`). Сквозной тест **без monkeypatch `save_persona`**: `tests/test_persona_api.py:339-367` (`TestOptimisticEndToEnd`: GET→токен, PUT(stale)→409 c `current_updated_at`, PUT(fresh)→200 + новый токен) через реальный `save_persona`/`set_persona_pool`. Отдельный 409-route-тест `:248-257`. |
| **H2** RBAC `edit_persona` | **Подтверждено** | `services/permissions.py:44` — `{"id": "edit_persona", "title": "Редактировать «Личность»"}` в `ACTIONS_TREE`; `ACTION_IDS` (`:52`); серверная валидация ролей больше не отвергает право — `known_actions=ACTION_IDS` (`web/api/routes.py:862-870`, в т.ч. `:869`); проверка прав `match_permission(perms, "edit_persona")` (`routes.py:1374`); UI `hasPerm('edit_persona')` (`web/app.js:2821`). Тесты доступа 200/403: `tests/test_persona_api.py:220-236` (chat и global через роль `persona_editor`), `:193-195,208-218` (403). |
| **H3** per-chat резолв | **Подтверждено** | Async-пути используют `get_chat_param`: persona-гейт в direct-пути (`services/direct_chat_service.py:590-598`, резолв передан в `build_persona_prompt_block(..., enabled=True)`), self-awareness (`:1013-1017`), контекст-бюджеты (`:809-812`), `dream_worker` (`services/dream_worker.py:1278-1283`), `summary_memory` — вес само-факта (`:1771-1777`, `:2091-2094`) и гейт (`:2082-2086`). Оставшиеся `hot.get` для этих ключей — только **fallback-аргумент** `get_chat_param` либо sync-ветка `enabled is None` (`bot_persona.py:214`, `direct_chat_service.py:1142`), что документировано. Тесты: `tests/test_settings_persistence_round1014.py:301-338` (per-chat OFF → self-факт не пишется; per-chat вес 0.9 реально попадает), `tests/test_persona_prompt.py:66-72` (per-chat `enabled=False` не перебивается глобальным `hot.get`). |
| **M1** inventory/report | **Подтверждено** | `inventory.tsv` — **411 строк данных** + шапка (`wc -l` = 412), содержит `content.intelligence_guide` + `POST /api/info/guide` (`inventory.tsv:397`); `report.md` актуализирован (REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / TAB_RULES 19), статус F6 описан корректно, ложного «всё OK» нет — блок H3-фикса задокументирован. |
| **M2** путь сид-файла | **Подтверждено** | `services/info_service.py:78-81` — `_PROJECT_ROOT = Path(__file__).resolve().parents[1]`, `GUIDE_SEED_FILE` абсолютный. |
| **M4** ARCHITECTURE/README | **README — да; ARCHITECTURE — пост-задача @Architect** | `README.md` обновлён (раунд 10.14, 5582 тестов, инварианты 435/406/411/90/88/19); `plans/ARCHITECTURE.md` раздел §10.14 пока отсутствует, `T-1497` — `[ ]` (`plans/features/persona-storage-core-round1014/tasks.md:88`). Прецедент §33/§34 (runtime-разделы содержат «@Reviewer Approved») подтверждает, что раздел пишется @Architect **после** аппрува кода — не блокер для кода. |
| **L1** backlog | Подтверждено (`plans/backlog.md:5` — `🟢 IMPLEMENTED`) | — |
| **L2** дубль badge | Подтверждено (`web/app.js:1130-1132` — `return this.scopeLabel;`) | — |
| **L3** `_GUIDE_KEY` | Подтверждено (`web/api/routes.py:30-32` — импорт из `services.info_service`) | — |
| **L4** анти-эхо до cap | Подтверждено (`services/direct_chat_service.py:1827-1843` — инструкция добавляется ДО `content[:cap]`) | — |
| **L6** docstring v9 | Подтверждено (`tests/test_migrate_direct_chat_v2_script.py:7`) | — |
| **L5** hot-path оверхед | **Не закрыто (Low, не блокер)** | `direct_chat_service.py:594-596` — на каждый ответ `resolve_bot_persona` + `get_traits` (2 PG-запроса), кэш не введён. |
| **L7** aiosqlite leak | **Не закрыто (Low, не блокер)** | Validator по-прежнему: `WARNING: closed 12 leaked aiosqlite connection(s)`. |

## 2. Результаты Validator (запущено @Reviewer, итерация 2)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5582 passed, 1 warning** (0 failed), 58.99s; warning — `closed 12 leaked aiosqlite connection(s)` | **0** |
| `node --check web/app.js` | OK | **0** |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` (DOMPurify недоступен в среде — ожидаемый fail-closed warn) | **0** |
| `git diff --check` | чисто (только штатные LF/CRLF-предупреждения git) | **0** |

Каталог независимо пересчитан @Reviewer: REGISTRY **435** / categorized **411**; `content.intelligence_guide` присутствует; `per_chat=True` у `flags.persona_enabled`, `flags.bot_self_awareness_enabled`, `limits.graph_fact_weight_bot`; тесты-инварианты подтверждают 406/90/88/19 (`tests/test_param_catalog.py:78,266`, `tests/test_frontend_tab_mapping.py:47-48,82-84`).

## 3. Остаточные замечания (не блокируют аппрув)

- **[Low] `web/api/routes.py:1440`** — `GET /api/persona` отдаёт `persona_enabled` глобальным `hot.get`, а не per-chat, хотя `chat_id` доступен (async-роут). Влияет только на UI-индикатор блокировки персоны (`app.js:1125-1126`), не на рантайм (рантайм резолвит per-chat корректно). Рекомендуется резолвить через `get_chat_param(chat_id, …)` для консистентности. Не hot-path.
- **[Low] `handlers/direct_chat.py:150`** — sync-триггер по имени использует глобальный `hot.get("flags.persona_enabled")`; per-chat имя на sync-пути не поддерживается (комментарий + spec §3.3/§7.4: кэш глобального имени). Осознанное ограничение, не дефект рантайм-резолва `handle`.
- **[Low] L5** — hot-path оверхед (2 PG-запроса + запись `persona_state` на ответ); кэш трейтов/статуса отсутствует.
- **[Low] L7** — предупреждение о 12 aiosqlite-соединениях (похоже, pre-existing; рекомендуется разобраться отдельным тикетом).
- **[@Architect] T-1497 / M4** — влить §Persona в `plans/ARCHITECTURE.md`; закрыть архитектурные гейты T-1487/1511/1526/1535/1541. Обязательство **до деплоя**, не блокирует код-аппрув.
- **Косметика** — `plans/backlog.md:5` сообщает «итерация 1/3 правок», фактически идёт итерация 2.

## 4. Инварианты (перепроверены в итерации 2)

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты не в логах) | ✅ | `services/self_reflection.py:118-120,126-128` — только `type(exc).__name__`; новых утечек нет |
| R16 (id — ключ, не имя) | ✅ | Персона/черты — `chat_id`/id; имя — UX-триггер |
| Порядок роутеров `bot.py` | ✅ | diff `bot.py` — только `await load_global_cache()` (`bot.py:829-833`), DI-порядок не тронут |
| `media/` и `.env` | ✅ | `git status` — изменён только `.env.example`; `media/` чист |
| Каталог 435/406/411/90/88/19 | ✅ | независимый пересчёт + `test_param_catalog`/`test_frontend_tab_mapping` |
| Новых CDN нет | ✅ | DOMPurify self-host (`index.html:3615`), новых CDN-доменов не добавлено (tailwind/vue/chart.js — legacy) |
| SQLite v9 / CHECK origins | ✅ | `database.py:57,73-80`; `test_graph_facts_origin_v9.py` |
| `TABS.length == 19` | ✅ | `tests/test_frontend_tab_mapping.py:47-48` |

---

**Итог итерации 2: код и исправления @Builder приняты. `Approved`.** Остаточные Low и пост-задача @Architect (T-1497/ARCHITECTURE.md) вынесены за рамки аппрува кода и фиксируются как обязательства до деплоя.
