# spec.md — F2 `factcheck-deep-context-round1023`

> **Раунд 10.23** · Приоритет **P0** · Шаг 2 @Architect · Тип: backend (окно/граф) + канон промпта + UI-параметр
> **ADR:** `ADR-1023-2.md` (**Accepted**). **Задачи:** `tasks.md` (T-2107…T-2115).
> **ТЗ:** «Глубокий контекст и граф реплаев» + «Форсированный Веб-поиск (Фактчекер)». Untracked, секреты не цитировать/не коммитить (R17/R18).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a8a6437`.
> **Зависит от:** F1 (ступень канон-контура). **Сквозной слой:** `round1023-architecture.md` §3.3, §3.4, §4.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Окно контекста фактчека | `handlers/factcheck.py:58` (`_fetch_chat_context`), вызов `:227-228` |
| Рендер окна | `services/chat_context.py:23` (`format_chat_context`, cap 2000) |
| Ключ/дефолт | `limits.factcheck_context_messages` (`services/param_catalog.py:1040`), `settings.FACTCHECK_CONTEXT_MESSAGES` (`config/settings.py:826`, default 6) |
| Только «последние N» | `DatabaseService.get_recent_messages(chat_id, limit)` (`services/database.py:1783`) |
| Граф реплаев (direct) | `services/direct_chat_service.py:2417` (`_collect_thread_chain`), глубина `CHAT_THREAD_MAX_DEPTH` (`:1006`) |
| Двухвызовный фактчек | `services/factcheck_service.py::_check_claim_two_call`, `services/factcheck_prompts.py` |
| Группа каталога | `limits_factcheck` (`services/param_catalog.py:206`) |
| Канон-контур | `services/prompt_migrations.py` + `plans/docs/canon/**` |

### 0.1. Уточнения / инварианты

- Текущее окно — только «последние N»; ТЗ требует **до и после** целевого + цепочки ответов.
- Дублировать `FACTCHECK_CONTEXT_MESSAGES` нельзя: legacy-ключ становится источником одноразовой миграции, активный код читает только `before`/`after`.
- Канон-атомарность (ADR-1013-3); F2 идёт **после F1**.
- `_collect_thread_chain` переиспользуется, но **логику direct не ломаем** (R3).

## 1. Цель

Фактчек получает сообщения **до и после** целевого, видит программно построенные цепочки реплаев и обязан искать подтверждение в вебе для тейков о реальном мире.

## 2. Требуемое поведение

1. Окно: `N_before` сообщений старше якоря + якорь + `N_after` новее; хронологический порядок ASC; параметры редактируются в UI раздела «Фактчек: лимиты».
2. Граф реплаев: для якоря строится цепочка «кто кому отвечал» (общий util), инжектируется отдельным под-блоком (не доказательства), fail-open.
3. Промпт-правило: тейк о реальном мире/новостях/датах/политике/общеизвестных фактах → обязательный веб-поиск.
4. Legacy-ключ не создаёт второй источник правды; миграция значения `before` идемпотентна.

## 3. Архитектура и контракты

### 3.1. Двунаправленное окно (T-2108)

- Новые ключи каталога (group `limits_factcheck`): `FACTCHECK_CONTEXT_BEFORE` (`limits.factcheck_context_before`, default **6**), `FACTCHECK_CONTEXT_AFTER` (`limits.factcheck_context_after`, default **6**).
- Код-кап: `FACTCHECK_CONTEXT_TOTAL_CAP = 40` (жёстко в коде). Кап считается по **сумме `before + after`**; якорь БД добавляется сверх капа → фактический максимум строк окна **cap + 1 = 41** (R1023F2-06).
- Бюджет рендера: `format_chat_context(..., reply_chains=...)` гарантирует **длину всего `<chat_context>` ≤ `max_chars`** (обёртка + окно + цепочка); дальние ходы цепочки вытесняются первыми, при нехватке места под-блок опускается. Отдельный жёсткий потолок цепочки — `_REPLY_CHAINS_MAX_CHARS = 1200` (R1023F2-01).
- Grounding: `chat_context`/`<reply_chains>` **исключены** из источников grounding-якорей (`FactCheckService._trusted_text`); якоря — только RAG/поиск/tool-контекст (R1023F2-04).
- **Legacy `FACTCHECK_CONTEXT_MESSAGES`:** активный код-путь **не читает**; одноразовая идемпотентная миграция `migrate_factcheck_context_defaults` переносит его значение в `before`, если `before` не задан; ключ остаётся в реестре (пины), но уходит из UI-вида фактчека (внутренний).
- **Δ каталога F2 = +2** (Settings/REGISTRY 439→441). Группа/вкладка не меняются (`tma-menu-freeze`).
- Новый метод БД: `get_messages_around(chat_id, target_tg_message_id, before, after) -> list` — anchor-выборка (id < anchor / id == anchor / id > anchor) ASC; fail-open → legacy `get_recent_messages(before + after)`. Фактический максимум строк = `before + after + 1` (якорь), где `before + after ≤ cap`.

### 3.2. Граф реплаев (T-2109)

- Вынести `_collect_thread_chain` из `DirectChatService` в общий util (напр. `services/thread_chain.py::collect_thread_chain(db, chat_id, message, depth)`) без дублирования логики; direct переключается на util (регресс direct обязателен).
- Инжекция: цепочка строится для **якоря** (целевого сообщения); глубина = `limits.chat_thread_max_depth` (паритет с direct; новый ключ НЕ вводим).
- Формат — канонический (`format_context_item`), отдельным `<reply_chains>`-под-блоком с note «цепочки — контекст, не доказательства».
- Fail-open: нет цепочки/ошибка БД → блок опускается (прежнее поведение).

### 3.3. Промпт-правило веб-поиска (T-2110/T-2111)

- В `FACTCHECK_ANALYST_SYSTEM_PROMPT` (Stage-1): «Если проверяемый тейк касается реального мира, новостей, дат, политики или общеизвестных фактов — ты ОБЯЗАН вызвать веб-поиск, а не опираться только на память чата».
- Канон-миграция ADR-1013-3 (слепок `PREV_FACTCHECK_ANALYST_R1023` + `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` + `plans/docs/canon/**`) — одним коммитом.
- Правило не отменяет F1-маркировку (обе правки одного промпта — согласовать порядок: F1 → F2).

### 3.4. UI-параметры (T-2112)

- Два int-параметра отображаются generic-рендером каталога в разделе фактчека; структура меню не меняется.

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `handlers/factcheck.py` | `_fetch_chat_context` → двунаправленное окно + инжекция цепочки; проброс триггера (F1) |
| `services/database.py` | новый `get_messages_around` |
| **NEW** `services/thread_chain.py` | общий util цепочки реплаев |
| `services/direct_chat_service.py` | переключение на util (только вынос; direct-поведение не менять) |
| `config/settings.py` | `FACTCHECK_CONTEXT_BEFORE/AFTER` + `FACTCHECK_CONTEXT_TOTAL_CAP` |
| `services/param_catalog.py` | +2 ключа; legacy — внутренний |
| `services/config_migrations.py` | `migrate_factcheck_context_defaults` (идемпотентна) |
| `bot.py` | вызов миграции (порядок роутеров не сдвигать) |
| `services/factcheck_prompts.py` + `services/prompt_migrations.py` + `plans/docs/canon/**` | правило веб-поиска + канон-миграция |
| `services/chat_context.py` | приём `trigger_message_id` (F1) + блок цепочек |

## 5. План тестирования (T-2113/T-2114)

1. Границы: `before/after = 0`, большое N (кап), дефолты 6/6; порядок ASC; якорь включён ровно один раз.
2. Legacy-миграция: значение legacy → `before`; идемпотентность; кастом не затирается.
3. Граф: цепочка для якоря; паритет с direct-логикой; fail-open при отсутствии цепочки.
4. Промпт: наличие правила веб-поиска; канон-миграция (migrate/rollback).
5. UI: параметры рендерятся/сохраняются; структура меню не изменена (`test_frontend_tab_mapping`).
6. Регресс: `test_factcheck_handlers.py`, `test_factcheck_service.py`, `test_factcheck_two_call_round1022.py`, `test_direct_chat.py`, `test_param_catalog.py`. Полный pytest — 0 failed.

## 6. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Дублирование `FACTCHECK_CONTEXT_MESSAGES` | before/after — единственный код-путь; legacy — только миграция |
| R2 | Medium | Рост контекста/стоимости | кап 40, дефолты 6/6, тест границ |
| R3 | Medium | Вынос `_collect_thread_chain` ломает direct | общий util + полный регресс direct |
| R4 | Medium | Канон-атомарность | один коммит (T-2111) |
| R5 | R17/R18 | raw-сообщения в логах | только counts/коды |

## 7. Критерии приёмки

- Фактчек получает N до и N после целевого; цепочки реплаев инжектируются общим util; правило веб-поиска в промпте; канон-миграция атомарна; UI-параметры работают; полный pytest — 0 failed.

## 8. Feature flag / раскатка / откат

- Поведенческий фикс, флага нет. **Δ каталога = +2; DDL = 0.**
- Откат — `git revert` + обратная канон-миграция; миграция значения обратима (значение сохраняется в legacy-ключе).

## 9. Открытые вопросы (Human Gate)

- Дефолты 6/6 и кап 40 — подтвердить (стоимость). См. ADR-1023-2 §Human Gate.
- Legacy-ключ «внутренний» vs полное удаление из каталога: выбран внутренний (не ломает пины/Δ ровно +2).

## 10. Задачи

См. `tasks.md` (T-2107…T-2115). **T-2107** — этот spec + ADR-1023-2 (выполнен).
