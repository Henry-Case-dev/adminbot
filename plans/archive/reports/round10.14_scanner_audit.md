# Step 6 — SCANNER AUDIT раунда 10.14 «Самосознание и Личность бота»

> **Сканер:** @Scanner (фоновый аудитор логических ошибок). **Дата:** 13.09.2026.
> **Baseline:** HEAD `2edc65b` + незакоммиченное рабочее дерево (8 фич F1–F8, untracked `services/bot_persona.py`,
> `services/self_reflection.py`, тесты). **Метод:** diff-based (git diff + untracked) + адресная проверка
> инвариантов миграции/PG/RBAC/безопасности + независимый прогон Validator. **Код не правился.**
> **Контекст:** Step 5 @Reviewer `Approved` (итерация 2). Owner разрешил DDL/миграции — не нарушение.

---

## Сводка

| Severity | Кол-во | Открыто (блокирует) |
|---|---|---|
| **Critical** | **0** | — |
| **High** | **0** | — |
| **Medium** | **2 → 0** | Закрыты итерацией 2 (R10.14-1, R10.14-2 — см. §6) |
| **Low** | **5 → 2** | R10.14-4, R10.14-7 (не блокеры) |
| **Info** | **2** | — |

**Вердикт по контракту: открытых Critical/High — НЕТ.** Medium R10.14-1/-2 закрыты повторным аудитом
(итерация 2, §6); остаются только Low. Раунд готов к шагу 7.
*(Итерация 1: Medium 2 были зафиксированы как follow-up — R10.14-1 RBAC view/edit `edit_persona`, R10.14-2 traits-LLM вне `worker_budget`.)*

---

## 1. Таблица находок

| ID | Sev | Файл:строка | Суть | Рекомендация |
|---|---|---|---|---|
| **R10.14-1** | **Medium** | `web/api/routes.py:1381-1386` (`_persona_can_view`) vs `:1365-1378` (`_persona_can_edit`); `web/app.js:2812-2823` | **RBAC view/edit асимметрия `edit_persona`.** Роль с action `edit_persona` **может** `PUT /api/persona` global (`:1457`, `:1374` → 200), но **не может** `GET` global (`:1384-1385` → 403). UI `canViewTab('persona')` для не-global-admin требует выбранный чат (`app.js:2819`) → global-экран редактора недоступен. Спек F2 §5 объявляет GET «auth TMA», а H2-фикс вводил `edit_persona` как рабочий делегируемый action. | Либо разрешить GET global при `match_permission(perms, "edit_persona")`, либо зафиксировать в спеке «view global = только global admin» и убрать dead-ветку возможности PUT global для editor. Добавить тест `GET global as persona_editor` (сейчас нет — `test_persona_api.py` проверяет только GET admin и PUT editor). |
| **R10.14-2** | **Medium** | `services/dream_worker.py:1442-1443` | **LLM-вызов `_run_persona_traits_once` не проходит через `worker_budget`.** Прямой `self._worker_llm("background", …)` без `_deep_budget_ok`/`worker_budget.consume` (ср. deep-sleep путь `:1348-1375`). Токены traits не пишутся в `memory_dream_log`, `sum_dream_log_tokens` их не видит → суточный cap `limits.deep_sleep_tokens_per_day` и ledger `worker_budget` недосчитывают. Спека F2 §3.4 п.5: «Токены — существующий worker_budget». | Обернуть вызов тем же `_deep_budget_ok(chat_id, system+user)` (или `worker_budget.consume(..., "llm_calls"/"llm_tokens")`) до LLM; логировать токены. |
| R10.14-3 | Low | `web/api/routes.py:1439-1440` | `GET /api/persona` отдаёт `persona_enabled` глобальным `hot.get`, хотя `chat_id` доступен → per-chat override флага не отражается в UI-индикаторе `personaDisabled` (`app.js:1125-1127`). Рантайм (`direct_chat_service.py:590-598`) резолвит per-chat корректно. (Ревьюер уже отметил как остаточное Low — подтверждаю.) | Резолвить `await _cp_g(chat_id, "flags.persona_enabled", …)` в async-роуте. |
| R10.14-4 | Low | `web/api/routes.py:1441-1442`; `web/app.js:5153-5158` | `dynamic_traits` отдаются без фильтра `chat_id` (глобальный пул), лента «Эволюция характера» в chat-scope показывает черты других чатов. По спеке F4 traits — глобальный характер бота, поэтому это скорее UX-несогласованность, чем утечка. | Если chat-scope не задуман — оставить как есть и зафиксировать; иначе передавать `chat_id` в `get_traits`. |
| R10.14-5 | Low | `services/summary_memory.py:1771-1777` | Ветка `bot_weight=… if source_type == "bot_self_reply"` в `_memorize_facts_inner` недостижима: self-факты идут минуя `memorize_facts` (напрямую `memorize_self_reply`, `:2103`). Мёртвый код (вреда нет). | Убрать ветку или задокументировать как защитную. |
| R10.14-6 | Low | `tests/test_graphrag_database.py:394`; `tests/test_database.py:789`; `tests/test_history_migration_v7.py:5` | Устаревшие docstring-и: «user_version остаётся 8» / «user_version=8» при фактическом 9. (Ревьюер закрыл только `test_migrate_direct_chat_v2_script.py:7`.) | Поправить комментарии 8→9. |
| R10.14-7 | Low | `pytest` warning | `WARNING: closed 12 leaked aiosqlite connection(s)` сохраняется (похоже, pre-existing). Ревьюер L7. | Отдельный тикет на закрытие `DatabaseService` в новых фикстурах. |
| I10.14-1 | Info | `services/database.py:917-995` | Прямой каскад v7→v9 юнит-тестами не покрыт (покрыты v8→v9 и from-scratch). По анализу guard-ов v8-rebuild интерполирует уже обновлённый `_GRAPH_FACT_ORIGINS_SQL` → v9 корректно no-op; риска нет. | Опционально добавить v7-фикстуру. |
| I10.14-2 | Info | `services/bot_persona.py:504` | FIFO-ротация трейтов — глобальная (`DELETE … NOT IN (… LIMIT $1)` по всей таблице), а не per-chat. Соответствует модели «общий характер бота»; отметить в ARCH при T-1497. | Зафиксировать в документации. |

---

## 2. Разбор Medium-находок (доказательства)

### R10.14-1. RBAC `edit_persona`: PUT global можно, GET global нельзя
- `_persona_can_edit` (`routes.py:1365-1378`): global → `global admin` **или** `match_permission(perms, "edit_persona")`.
- `_persona_can_view` (`routes.py:1381-1386`): global → **только** `is_global_admin`; иначе `can_access_chat` (chat).
- Тесты: `tests/test_persona_api.py:193-195` (GET global MODERATOR → 403), `:230-236` (PUT global persona_editor → 200).
  Теста `GET global persona_editor` нет.
- Независимый probe (Scanner, временный тест, уже удалён) через `_FakeConn`/`TestClient`:
  ```
  GET /api/persona (persona_editor, без X-Chat-Id) -> 403
  GET /api/persona (persona_editor, X-Chat-Id=-100500) -> 200
  ```
  → Подтверждено: роль-редактор персоны не может прочитать глобальную персону, но может её записать.
- `web/app.js:2812-2823`: не-global-admin видит экран «Личность» только при выбранном чате; глобальный
  сценарий из UI недостижим. Контракт F2 §5 (GET — auth TMA) нарушен в сторону ужесточения, что ломает H2-UX.

### R10.14-2. traits-LLM вне worker_budget
- `services/dream_worker.py:1402` `_run_persona_traits_once` → `:1442` `raw = await self._worker_llm("background", messages, temperature=0.3)`.
- `_worker_llm` (`:783-793`) просто вызывает `generate_worker`/`generate`; `llm_client` и `direct_chat_service`
  не содержат `worker_budget` (grep пуст) → учёт отсутствует.
- Deep-sleep для сравнения: `_deep_budget_ok` (`:1348-1375`) делает `worker_budget.consume(None, "global", "llm_calls", 1)`
  и `"llm_tokens"`, а `_deep_llm_once` (`:1336-1346`) логирует токены в `memory_dream_log(kind='deep_run'/'deep_skip')`.
- Итог: дополнительный LLM-вызов на каждый прогон глубокого сна (даже при `duplicate`, т.к. вызов стоит после
  ветки логирования skip, `:1283`) не учитывается ни в суточном капе, ни в бюджете. Расхождение с F2 §3.4 п.5.

---

## 3. Проверено чисто (ключевые инварианты раунда)

| Проверка | Статус | Доказательство |
|---|---|---|
| SQLite v9 rebuild: 16 колонок 1:1 | ✅ | `database.py:959-985` (CREATE 16 / INSERT…SELECT 16); `tests/test_graph_facts_origin_v9.py:104-154` |
| FTS (`content='graph_facts'`) и vec (`rowid=fact_id`) не рассинхронизированы | ✅ | id 1:1 сохранены; FTS-hit по id и vec-rowid тестируются (`test_graph_facts_origin_v9.py:140-143,184-202`); триггеров на `graph_facts` нет (grep `CREATE TRIGGER` пуст) |
| Индексы v8 пересозданы (5) | ✅ | `database.py:987-994`; тест `:134-139` |
| Идемпотентность/двойной прогон/from-scratch | ✅ | guard по `'bot_self_reply' in sql` (`:944`); `PRAGMA user_version=9` безусловно (`:994`); тесты `:157-181` |
| Откат документирован | ✅ | docstring `:949-951`, ADR-1014-2 §D2 |
| PG DDL идемпотентность `personas`/`persona_traits`/`persona_state` | ✅ | `IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` + seed `WHERE NOT EXISTS`; partial-unique `uq_personas_global`/`uq_personas_chat`; FK `chat_profiles(chat_id)` PK (`pg_db.py:76-77`), ON DELETE CASCADE; `ON CONFLICT (is_global) WHERE is_global` / `(chat_id) WHERE chat_id IS NOT NULL` соответствуют partial-индексам |
| Optimistic-409 (H1) сквозной | ✅ | `bot_persona.py:148,408-414,442-446`; `routes.py:1402,1494`; `app.js:4355,4368-4370`; реальный тест без monkeypatch `test_persona_api.py:339-367` |
| Origin-фильтры self (Сон/золотые/decay/dup/stats) | ✅ | `list_new_confirmed_facts` (`:2065-2076`), `search_golden_facts_fts` (`:2477`), `get_live_graph_facts` (`:3420-3428`), `find_exact_dup_groups` (`:3438-3446`), `graph_stats` (`:3685-3696`); `_DREAM_SOURCE_ORIGINS` без self (`dream_worker.py:138-139`); `_reassign_fact_owners` фильтрует `origin='bot_direct_reply'` (`direct_chat_service.py:1066-1070`) |
| per-chat резолв (H3) | ✅ | `_cp_g`/`_cpg` в direct/dream/summary (`direct_chat_service.py:590-598,1013-1017`; `dream_worker.py:1278-1283`; `summary_memory.py:1771-1777,2082-2094`) |
| Веса/важность self | ✅ | вес 0.2 (`summary_memory.py:220-227`), важность 2 (`database.py:97`, `memorize_self_reply`), метка `[Источник: Я сам (Бот)]` (`:318`), TTL как direct |
| Анти-эхо до cap (L4) | ✅ | `direct_chat_service.py:1822-1843` |
| XSS: все `v-html` санитайзятся DOMPurify | ✅ | `index.html:3193,3206,3230,3248` → `sanitized*`/`sanitizeHtml`; fail-closed `app.js:4207-4219`; `renderGuideMarkdown` экранирует HTML и допускает только `https?://` |
| SQL-инъекции | ✅ | новые SQL параметризованы (`$n`/`?`); f-string — только placeholder-индексы/PRAGMA-константы |
| R17 (секреты) | ✅ | `self_reflection.py:118-120,126-128` — только `type(exc).__name__`; `INTEL_REFLECTION_API_KEY` secret; `last_error` этим путём не пишется |
| Каталог 435/406/411/GROUPS 90/mapped 88/TAB_RULES 19 | ✅ | `test_param_catalog.py:78,266,336`; `test_frontend_tab_mapping.py:47-49,82-84`; независ. пересчёт `len(REGISTRY)==435`; `412` строк `inventory.tsv` (411 данных) c `content.intelligence_guide` |
| Флаги ON: `PERSONA_ENABLED`, `BOT_SELF_AWARENESS_ENABLED` default True | ✅ | `settings.py:812-818`; каталог `flags.persona_enabled`/`flags.bot_self_awareness_enabled` |
| Регрессии смежных подсистем | ✅ | `TABS.length==19` не тронут; `bot.py` DI-порядок (только `load_global_cache`); `hot.set_config_cache` ДО прогрева имени (`bot.py:820,829`); parser промптов F2 аддитивен (`dream_prompts.py`) |

---

## 4. Validator (независимый прогон Scanner)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5582 passed, 1 warning** (0 failed), 63.65 s; warning — `closed 12 leaked aiosqlite connection(s)` | 0 |
| `node --check web/app.js` | `NODE_CHECK_OK` | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` (DOMPurify недоступен — ожидаемый fail-closed warn) | 0 |
| `git diff --check` | чисто (только штатные LF/CRLF-предупреждения git) | 0 |

---

## 5. Итог

- **Critical: 0. High: 0.** Medium: **2** (R10.14-1 RBAC view/edit `edit_persona`; R10.14-2 traits-LLM вне
  `worker_budget`) — не блокируют переход к шагу 7, но требуют точечного фикса/follow-up.
- Low: **5** (R10.14-3…-7), Info: **2** (I10.14-1…-2).
- **Контракт: открытых Critical/High НЕТ.**
- Обновлены аддитивно: `plans/reports/global_map.md`, `plans/reports/audit_backlog.md`,
  `plans/reports/full_audit_results.md`.

---

## 6. Повторный аудит (итерация 2) — верификация фиксов @Builder

> **Дата:** 13.09.2026. **Метод:** адресная проверка диффа по коду + прогон тестов; Validator прогнан заново.
> **Код не правился.**

### Статус R10.14-*

| ID | Было | Стало | Файл:строка (доказательство) | Тесты |
|---|---|---|---|---|
| **R10.14-1** | Medium | **CLOSED** | `web/api/routes.py:1365-1372` (`_persona_has_edit_action`), `:1375-1385` (`_persona_can_edit`), `:1388-1399` (`_persona_can_view` → global: `_persona_has_edit_action`); `web/app.js:2820-2825` (`canViewTab('persona')` → `hasPerm('edit_persona')` без выбранного чата) | `tests/test_persona_api.py:197-205` (`test_edit_persona_action_view_global` → 200 global), `:207-213` (chat), `:215-222` (`test_edit_persona_view_put_consistency` GET/PUT оба скоупа), `:193-195` (moderator global 403), `:256-261` (moderator chat PUT 403); `tests/js/routing_test.js:190-195` (global + `edit_persona` → виден) |
| **R10.14-2** | Medium | **CLOSED** | `services/dream_worker.py:1460` (`_deep_budget_ok` **до** LLM traits, fail-safe skip), `:1355-1368` (кап учитывает `kind="deep_traits"`), `:1406-1415` (`_log_persona_traits_tokens` → `deep_traits`), `:1475-1479` (токены done), `:1462`/`:1469-1470` (skip/error) | `tests/test_dream_persona_traits.py:182-201` (превышение → skip без LLM, запись `deep_traits`/`budget_skip`), `:204-225` (токены пишутся `deep_traits`/`done`), `:228-238` (кап видит накопленные `deep_traits`) |

**Симметрия RBAC (проверено по коду):** global GET и global PUT оба проходят через `_persona_has_edit_action`
(`routes.py:1378` и `:1395`); chat PUT — `edit_persona || section.content` (`:1378-1385`), chat GET — то же
`edit_persona` + `can_access_chat` (`:1395-1399`). Роль-редактор без чата видит global-экран; moderator/без прав
по-прежнему 403 (тесты подтверждают). Гейт `flags.persona_enabled` (`dream_worker.py:1278-1280`) и per-chat
резолв не изменены.

### Правки Low (регрессий не выявлено)

| ID | Статус | Проверка |
|---|---|---|
| R10.14-3 (per-chat `persona_enabled`) | **CLOSED** | `routes.py:1452-1460` async-резолв `get_chat_param`; тест `test_persona_api.py:224-238` |
| R10.14-5 (мёртвая ветка `bot_self_reply`) | **CLOSED (док.)** | `summary_memory.py:1771` — явный комментарий «ветка защитная»; поведения не меняет |
| R10.14-6 (docstring `user_version=8`) | **CLOSED** | `tests/test_graphrag_database.py:384`, `tests/test_database.py:932,1376`, `tests/test_history_migration_v7.py:123` → 9 |
| R10.14-4 (`dynamic_traits` без chat_id) | **Low (open)** | `routes.py:1461-1462` `get_traits(limit)` без chat_id — соответствует модели «общий характер» (F4); оставлено осознанно |
| R10.14-7 (aiosqlite leak warning) | **Low (open)** | warning сохраняется (pre-existing), не регрессия |

### Валидатор (итерация 2, прогон Scanner)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5589 passed, 1 warning** (0 failed), 60.58 s; warning — `closed 12 leaked aiosqlite connection(s)` (+7 тестов к итерации 1) | 0 |
| `node --check web/app.js` | `NODE_CHECK_OK` | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` (DOMPurify недоступен — ожидаемый fail-closed warn) | 0 |
| `git diff --check` | чисто (только штатные CRLF-предупреждения git) | 0 |

### Инварианты (spot-check итерации 2)

| Проверка | Статус | Доказательство |
|---|---|---|
| R17 (секреты в логах) | ✅ | `services/self_reflection.py:120,128` — только `type(exc).__name__`; значения ключей не логируются |
| R16 (id — ключ, не имя) | ✅ | персона/трейты по `chat_id`/id (`bot_persona.py`, `routes.py`) |
| Порядок роутеров `bot.py` (только DI-kwargs) | ✅ | `include_router` без изменения контракта; `hot.set_config_cache` до прогрева |
| `media/` и `.env` | ✅ | рабочим деревом не изменены (`git status`: только `.env.example`) |
| Каталог 435 / GROUPS 90 / mapped 88 / TAB_RULES 19 | ✅ | независ. пересчёт `len(REGISTRY)==435`, `len(GROUPS)==90`; `tests/test_frontend_tab_mapping.py:48,82`; `inventory.tsv` = 412 строк (411 данных) |
| DOMPurify self-host | ✅ | `web/static/vendor/dompurify-3.4.15.min.js`; `web/index.html` подключает локально |
| SQLite v9 / PG DDL `personas`/`persona_traits`/`persona_state` | ✅ | v9-миграция и DDL не тронуты фиксами; `pg_db.py:210-272`; тесты F1 зелёные |
| `TABS.length==19` не тронут | ✅ | persona — special-screen (`app.js:2814-2826`), зеркало TABS/TAB_RULES не затронуто |

### Итог итерации 2

- **Critical 0 / High 0 / Medium 0 / Low 2 (R10.14-4, R10.14-7) / Info 2.**
- **ВЕРДИКТ: открытых Critical/High/Medium НЕТ** — блокировок нет, раунд может идти на шаг 7.

*Итерация 2 сформирована @Scanner, 2026-09-13.*
