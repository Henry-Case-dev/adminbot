# AGI Memory Implementation — spec (Раунд 9, эпик 06.09.2026)

**HEAD:** 84c4887 · **Файл:** `plans/features/agi-memory-implementation/spec.md` · **Создано:** T-815 (A1, @Architect)
**Назначение:** единый дизайн эпика Фазы 2 research `plans/docs/agi-memory-research.md` (§3–7, §10): 2a «Отношения
(A-Life) + dig_into_lore» → 2b «Сон» (beliefs) → 2c «Ностальгия» (слой A, затем B); закрывает Q1–Q14 из раздела A
`tasks.md` (врезки «Q-N:» в §3; сводка — §3.7). PM-база подтверждена или уточнена; уточнения, МЕНЯЮЩИЕ требования
задач, помечены `(изменено @Architect T-815)` в тексте и сведены в §0. Правки кода НЕ вносились; `tasks.md` НЕ
правился (дельты — только в этом документе).

**RUNTIME WARNING (соблюдается):** SQLite-схема прода/локально — user_version **v7**. Единственная миграция эпика —
**v8** (rebuild `graph_facts`, задача D1; исполняется в фазе 2b); код задач B–C на v8-колонки
(`importance`/`kind`/`belief_meta`/origin `derived_belief`) НЕ ссылается и работает на v7. Новые таблицы
(`users_meta`, `dream_state`, `memory_dream_log`, `nostalgia_log`) — только идемпотентные `CREATE TABLE IF NOT EXISTS`
в init БЕЗ bump user_version (образцы `bot_reply_parents`/`chat_summary_levels`, database.py:239-258). PG-дельта —
ТОЛЬКО два аддитивных `ALTER TABLE chat_profiles ADD COLUMN IF NOT EXISTS` (`relations JSONB`,
`relations_enabled BOOLEAN`) в `DDL_STATEMENTS` (pg_db.py:33-121); без иных PG-структур (в частности, CHECK
`chat_lore_history.field` НЕ расширяется — см. D-2). Промпт-канон R9 — со слепком `PREV_R9_CHAT_SYSTEM_PROMPT`,
4-й ступенью `PROMPT_MIGRATIONS` и байт-тестами. Запрещено: `tools/history_import/`, `manage.py`, миграции v2–v7,
`local_database_*.db*`-файлы (не удалять/не блокировать), смена порядка роутеров bot.py, правки
LEGACY/PREV/PREV_R8-слепков.

## 0. Дельты против PM-базы/задач tasks.md (@Architect T-815; задачи НЕ правились)

| # | Задача | PM-база | Решение (см. §3) |
|---|---|---|---|
| D-1 | T-816/B1 | users_meta с `trust`/`intimacy` + `manual_stage` в SQLite | `trust`/`intimacy` НЕ храним (v1 не вычисляет и не инжектит; «теплоту» дают стадия + активность); `manual_stage` в SQLite НЕТ — ручное живёт в PG `relations` (Q1). Состав колонок — §3.1.1 |
| D-2 | T-818/B3 | история правок relations через `chat_lore_history` field='relations' | НЕВОЗМОЖНО: CHECK `chat_lore_history.field` в PG не содержит 'relations', а rebuild/ALTER CHECK запрещён (PG-дельта аддитивная). Аудит правки — внутри значения JSONB (`updated_by`/`updated_at` per user); `chat_lore_history` НЕ трогаем |
| D-3 | T-818/B3 | per-chat тумблер в `relations.enabled` JSONB | отдельная колонка `relations_enabled BOOLEAN NOT NULL DEFAULT FALSE` (вторым ADD COLUMN IF NOT EXISTS) |
| D-4 | T-824/D3 | кластеризация «по subject/объекту триплета» | в `graph_facts` нет колонки subject (триплеты живут текстом) — жадные токен-кластеры по значимым токенам/именам участников (Q9, §3.4.3); vec0-кандидаты в v1 НЕ используем (дешевле и детерминированнее) |
| D-5 | T-824/D3 | окно сна «04:00–06:00 через вычисление следующего тика» | тик `IntervalTrigger(hours=limits.dream_tick_hours)` БЕЗ привязки к часу + внутритиковый гейт: LLM-дистилляции только в local-часы `[dream_window_start_hour, dream_window_end_hour)`; вне окна тик делает бесплатную кластеризацию и помечает дистилляции `window_skip`. Ручной `run_once` окно игнорирует (Q9) |
| D-6 | T-825/D4 | supersede «при противоречии» | LLM-суждение о противоречии в v1 НЕ вводим: новый belief supersedes старый belief того же чата с тем же «якорным токеном» темы (§3.4.6) |
| D-7 | T-825/D4 | кнопка TMA «удалить belief» | мягкое удаление: `status='unconfirmed'` + `last_confirmed_at=NULL` (исключается из RAG, вычищается review); hard-delete не делаем (согласованность FTS5/vec0) |
| D-8 | T-829/F2 | `POST /api/memory/nostalgia/test` (dry-run) | НЕ реализуем в v1 (LLM-деньги без пользы; проверка — через лог срабатываний) |
| D-9 | T-820/C1 | dig: факты графа рендером «[дата] факт» | единый формат: L1-сниппеты `[Имя ГГГГ-ММ-ДД]: текст` + строки `факт ГГГГ-ММ-ДД: текст` (до `dig_max_facts`=3). Beliefs из dig НЕ исключаются: 2a работает на v7 и после v8 код не перестраивается (см. §3.2.1 п.6) |
| D-10 | T-819/B4 | блок «1 строка на активного юзера окна», позиция рядом с protected/lore | позиция: СРАЗУ ПОСЛЕ `<Target_User>` (важное ближе к концу); kind `relations` — uncuttable (в кортеже :812), защита — только cap ДО инжекта (Q3) |
| D-11 | T-821/C2 | пре-гейт маркеров, default по A1 | `flags.dig_pre_gate_enabled` default **false**; `flags.dig_enabled` default **true** (тратит раунды только по вызову модели) |
| D-12 | T-826/E1, T-827/E2 | слой A/B в чатах с is_active-профилем | слой A/B ТОЛЬКО `chat_id < 0` (группы/супергруппы); лички исключены (Q13) |
| D-13 | T-824/D3 | `memory_dream_log` — аудит «снов» | одна строка на тик-чат (kind='run') + одна строка на попытку дистилляции (distilled/skipped/error); watermark чата — `dream_state` (PK chat_id) |

**Фикс-раунд по ревью @Reviewer (major-1…major-6; канон R9 НЕ задеплоен — правки текста безопасны, ступень PREV_R9→CHAT валидна):**

| # | Задача | PM-база/спека | Решение (фикс-раунд) |
|---|---|---|---|
| D-14 | T-819/B4, T-832/G1 | инжект `<user_relations>`: «1 строка на активного юзера окна» | компактная карточка ТОЛЬКО целевого собеседника: `{Имя}: {стадия_ru}, в чате с {first_seen:ГГГГ-ММ}, {msg30} сообщ. за 30 дней` (+ «(ручная пометка админа)» при manual; + «\| пометка: {note}» если есть). Гейты/позиция после Target_User/uncuttable/cap 600 — без изменений. `msg30` — лёгкий COUNT за 30д-окно (`db.count_user_msg30`), значение в users_meta НЕ хранится (состав колонок §3.1.1 без изменений). Текст — §3.1.4 |
| D-15 | T-821/C2, T-832/G1 | канон R9: п.5 ПРИОРИТЕТЫ + абзац ОТНОШЕНИЯ в одну строку | dig-контракт — ТОЛЬКО в ИНСТРУМЕНТЫ п.2 (ПРИОРИТЕТЫ = ровно раунд 8, без п.5); ОТНОШЕНИЯ — 5 пунктов списком (своему/знакомому как обычно; ветерану теплее; новичку короче; ручная пометка админа важнее расчёта; блок/стадии не упоминать). Вставка `<user_relations>` в «как читать» — с дефисом (« - »), без «—». Текст — §3.2.2(б) |
| D-16 | T-824/D3, T-833/G2 | кандидаты DreamWorker «любой origin» | источники «жизни чата» — ровно 4: `chat_history`/`history_import`/`bot_direct_reply`/`user_memory` (константа `_DREAM_SOURCE_ORIGINS`; производные контенты и beliefs не передистиллируются — нет рекурсии). Текст — §3.4.3 |
| D-17 | T-827/E2, T-834/G3 | Q14: явная пауза `now < last_sent + nostalgia_pause_hours` | пауза неявная, окно проверки неотвеченных = `memory.nostalgia_pause_hours` (24 ч): пока ≥ `unanswered_max` последних sent чата за окно не отвечены — тик пропускает чат. Текст — §3.5.3 п.6 |
| D-18 | T-828/F1 | relations GET: «Сортировка: last_seen DESC (None в конце)» | итоговая сортировка списка — `activity_score` DESC (None/0 в конце; last_seen — вторичный стабилизатор). Текст — §3.6.1 |
| D-19 | T-816/B1, T-828/F1 | (уточнение чтения) | `refresh_users_meta` агрегирует ПО ВСЕЙ истории чата (first_seen «стариков» корректно → veteran; msg30/active_days30 — отдельное 30д-окно), а не окном 30д: частота пересчёта ограничена TTL-гейтом (`relations_recalc_ttl_minutes` в users_meta.last_recalc_at) + RAM-TTL кэша 60 с — горячий путь без полных сканов |
| D-20 | T-824/D3 | тик DreamWorker `dream_tick_hours` (24) | период тика — МИНУТЫ: ключ `memory.dream_tick_minutes` (60) вместо `dream_tick_hours` (REGISTRY-запись переименована); триггер `IntervalTrigger(minutes=…)` — первый тик внутри окна [4, 6) local дистиллирует при старте в любое время суток; вне окна — бесплатная кластеризация + `window_skip`, watermark не двигается (D-5/D-13). Текст — §3.4.1/§3.6.4 |

Прочие уточнения без пометки в задачах (не меняют требований, только конкретика): канон R9 — точные тексты правок
(§3.2.2), итоговые имена конфиг-ключей (§3.6.4), формат инжекта (§3.1.4), importance-правило (§3.3.2), форматы
логов (§3.4.1/§3.5.2), RBAC эндпоинтов (§3.6).

---

## 1. Обзор

Эпик превращает бота из «поисковика по памяти» в «существо с памятью» (research §1) тремя подфазами в ОДНОМ деплое
(одна реализация, порядок B→C→D→E→F; каждая боевая подфича отключаема тумблером; поведение прода без включения НЕ
меняется, кроме двух неизбежных изменений: канон R9 в 2a и миграция v8 в 2b):

- **2a. Отношения (A-Life).** У каждого участника чата — «карточка отношений»: авто-стадия
  (`stranger|acquaintance|regular|veteran`) и активность, считаемые SQL-агрегатами по `smart_messages` с
  экспоненциальным decay и анти-откатом (SQLite `users_meta`, аддитивный CREATE TABLE); ручная стадия и заметка
  админа — PG `chat_profiles.relations JSONB` через существующий чат-лор-стек (профиль, 409-оптимизм по
  `updated_at`, NOTIFY, fail-open). Перед генерацией ответа инжектится блок `<user_relations>` (сразу после
  `<Target_User>`); тональное правило (нюфаг → сдержаннее, ветеран → теплее) — в каноне R9. Отдельного TMA-раздела
  «Отношения» нет: настройки — per-chat внутри «Лор чатов», глобальные флаги/лимиты — в REGISTRY.
- **2a. dig_into_lore.** Третий tool direct_chat: «помнишь / а помните / как мы тогда / в 2024 / что было с <имя> /
  год назад» → FTS5 по `smart_messages` с фильтром года/сезона и расширением ключей именами (алиасы-резолв +
  граф-обход до глубины 2 как источник имён) + (mode facts/both) факты графа; 5–8 сниппетов с датами, лимит ~3500
  симв.; НЕ бросает. Контракт «вызови ДО ответа» — в каноне R9 (ИНСТРУМЕНТЫ п.2); код-пре-гейт маркеров — флагом
  off. LLM-«справки-что это было» в v1 нет (только сниппеты).
- **2b. Сон (beliefs).** Миграция v8: `graph_facts` += `importance/source_ids/kind/belief_meta`, origin
  `derived_belief`, `user_version=8`, детерминированный backfill importance. Importance-правило БЕЗ LLM на записи
  фактов. `DreamWorker` (тик `limits.dream_tick_minutes`=60 (D-20), флаг `flags.dream_enabled` default false): кандидаты по
  watermark `dream_state`, кластеризация БЕЗ LLM (жадные токен-кластеры), пороги повторяемости и суммы важности,
  бюджеты кластеров/дистилляций/токенов в сутки (= денежный лимит), 1 облачный LLM-вызов на кластер
  (`DREAM_DISTILL_PROMPT` → 0–2 beliefs с обязательными `source_ids`), supersede по якорному токену темы, аудит
  `memory_dream_log`, эмбеддинг боевым embed-путём. Beliefs участвуют в RAG как факты с меткой «[убеждение]» (только
  direct-рендер origin_labels).
- **2c. Ностальгия.** Слой A (при ответе, 0 добавочных LLM-вызовов): «золотые» факты (важность ≥ порога, давность ≥
  порога, kind='fact', тема запроса) → строка-маркер «nostalgia_hint: вспомни и вплети, если уместно…» в промпт;
  флаг `flags.nostalgia_layer_a_enabled` default false. Слой B: `NostalgiaWorker` (тик
  `limits.nostalgia_tick_minutes`=60, флаг `flags.nostalgia_enabled` default false) — тихие группы/супергруппы,
  кандидаты «N лет назад в этот день» (диапазон timestamp ±2 дня) и золотые факты последней темы, порог
  «агрессивности», 1 облачный LLM-вызов → 1–2 фразы «кстати…» → отправка в чат; жёсткий анти-спам (тишина, quiet
  hours, cooldown, max/сутки, стоп после 2 неотвеченных + пауза), аудит `nostalgia_log`.

**Принципы владельца (жёсткие):** (1) боевые воркеры — только облачные модели через существующий `LLMClient`
(apinet/deepseek + fallback, путь обычных ответов бота); локальная Ollama в бою не используется; (2) A-Life-настройки
живут ВНУТРИ раздела «Лор чатов» (PG `chat_profiles`, per chat_id; блок «Участники и отношения» во вкладке «Лор
чатов», блоки «Синтез (сон)»/«Ностальгия» — во вкладке «Память и RAG»); (3) один эпик (2a+2b+2c) — один деплой;
(4) RUNTIME WARNING §0.

**Карта по коду (проверено по HEAD 84c4887):** `database.py` (_SCHEMA_SQL :192-202; аддитивные образцы :239-258;
цепочка initialize :275-284; `_migrate_history_import_v7` :614-709; `_GRAPH_FACT_ORIGINS_SQL` :59-63;
`insert_graph_fact` :1382-1429; `save_smart_message` :1009-1039; `get_active_participants` :1664-1676) ·
`pg_db.py` (DDL_STATEMENTS :33-121; SEED_CATEGORIES :163-165) · `chat_lore_store.py` (ChatLoreConflict :149;
`_PROFILE_COLS`/SELECT-хелперы; `_to_profile` :192+) · `lore_cache.py` (LoreProfile frozen :35-50) ·
`lore_runtime.py` (set_lore_components :19; геттеры :34-47; db НЕ проброшен — Q2) · `tool_schemas.py`
(TOOL_CALLING_TOOLS :53) · `tool_router.py` (registry :102-105; `_query_chat_memory` :141-202; helpers :206-224) ·
`tool_loop.py` (TOOL_MAX_ROUNDS=4, ≤2 tool_calls/раунд) · `chat_prompts.py` (канон R8 :85-109; слепки :32-82) ·
`prompt_migrations.py` (PROMPT_MIGRATIONS :58-76; авто-миграция :80-114) · `direct_chat_service.py`
(`_build_user_content` :589-666; `_apply_context_budget` :795-896; `_build_rag_block` :1355-1409;
`_chat_lore_state` :1035) · `summary_memory.py` (`get_rag_facts` :1810-1832; `get_rag_context` :1773-1806;
`_ORIGIN_LABELS` :223-233; `_format_origin_labeled_line` :533; `build_rag_context` :545; `search_long_term` :1264;
`search_graph_facts_fts` — database.py:1431) · `param_catalog.py` (GROUPS :98-242; TAB_RULES :1060-1081; категория
memory :38-48) · `bot.py` (on_startup: MemoryMaintenance :452-455; lore-блок :459-486) · `memory_maintenance.py`
(каркас AsyncIOScheduler :40-80) · `web/api/chat_lore.py` (RBAC :70-95; 409-паттерн; router) ·
`web/app.js`/`index.html` (TABS :33-48; generic-конфиг :338-440; кастом chat_lore :494-743).

---

## 2. Требования

### 2.1 Функциональные требования

| FR | Подфаза | Коротко (что/зачем) | Раздел |
|----|----|----|----|
| FR-1 | 2a | Таблица `users_meta` (SQLite, CREATE IF NOT EXISTS, PK(chat_id,user_id)) + db-методы: агрегатный пересчёт, touch при записи сообщения, чтение | §3.1.1 |
| FR-2 | 2a | Расчёт активности/стадии/decay + анти-откат; ленивый пересчёт с TTL; manual приоритетнее авто | §3.1.2 |
| FR-3 | 2a | PG: `chat_profiles.relations JSONB` + `relations_enabled`; store-методы get/put/delete_relation/set_relations_enabled, 409-оптимизм, аудит в JSONB | §3.1.3 |
| FR-4 | 2a | Инжект `<user_relations>` в `_build_user_content` (после Target_User; гейты флагов; uncuttable; cap) | §3.1.4 |
| FR-5 | 2a | Tool `dig_into_lore` (схема; ветка роутера; год/«N лет назад»/person/mode; рендер; лимиты; НЕ бросает) | §3.2.1 |
| FR-6 | 2a | Канон R9: ИНСТРУМЕНТЫ += dig-контракт; абзац ОТНОШЕНИЯ; `<user_relations>` в «как читать»; `PREV_R9` + 4-я ступень миграции | §3.2.2 |
| FR-7 | 2a | Пре-гейт маркеров ностальгии (код; флаг `dig_pre_gate_enabled` off по умолчанию) | §3.2.3 |
| FR-8 | 2b | Миграция v8: rebuild `graph_facts` (+importance/source_ids/kind/belief_meta, origin `derived_belief`, backfill), user_version=8; `memory_dream_log`+`dream_state` CREATE IF NOT EXISTS; insert_graph_fact += параметры | §3.3.1 |
| FR-9 | 2b | Importance-правило БЕЗ LLM на записи (в `db.insert_graph_fact`, дефолт при None) | §3.3.2 |
| FR-10 | 2b | DreamWorker: каркас/старт, кандидаты-чаты/watermark/окно, кластеризация без LLM, пороги, бюджеты (кластеры/дистилляции/токены/сутки) | §3.4.1–3.4.4 |
| FR-11 | 2b | Дистилляция: промпт-канон `dream_prompts.py`, 1 облачный LLM-вызов на кластер, запись belief (source_ids обязательны, weight 0.6, importance=Σ, kind='belief', belief_meta), supersede, эмбеддинг, рендер-метка, аудит | §3.4.5–3.4.7 |
| FR-12 | 2c | Слой A: «золотые» факты → строка-маркер в промпт; 0 добавочных LLM-вызовов; флаг off; только чаты chat_id<0 | §3.5.1 |
| FR-13 | 2c | Слой B: NostalgiaWorker + промпт-канон `nostalgia_prompts.py`; условия тика/анти-спам; кандидаты; отправка; лог | §3.5.2–3.5.5 |
| FR-14 | API | Relations API: GET список (SQLite+PG merge), PUT/DELETE по юзеру (409), тумблер через settings; RBAC; db через lore_runtime (Q2) | §3.6.1 |
| FR-15 | API | Dream API: run (202/409-анти-рейс), beliefs GET, delete (мягкий), log GET | §3.6.2 |
| FR-16 | API | Nostalgia log GET | §3.6.2 |
| FR-17 | TMA | Вкладка «Лор чатов»: блок «Участники и отношения»; вкладка «Память и RAG»: мини-блоки «Синтез (сон)»/«Ностальгия»; REGISTRY-ключи | §3.6.3–3.6.4 |

**Вне скоупа:** локальная LLM в боевых воркерах; отдельный TMA-раздел «Отношения»; LLM-«справка-что это было» в dig
(v1 — только сниппеты); LLM-importance на каждое сообщение/пачку (v1 — правило); полный MemGPT-роллинг; ностальгия
в личках (chat_id>0); graph community detection; «любимые темы юзера» в `<user_relations>`; POST /nostalgia/test
(D-8); новые PG-таблицы и изменение CHECK `chat_lore_history` (D-2); правки `tools/history_import/`, миграций
v2–v7, слепков LEGACY/PREV/PREV_R8; чистка истории-БД.

### 2.2 NFR (нефункциональные)

- **NFR-1 (только облачные LLM):** все LLM-вызовы воркеров/тулов/эмбеддингов — через существующий `LLMClient`
  (горячие ключи `models.*`/`keys.*`, путь обычных ответов бота; bot.py:468-473 — образец создания при
  необходимости). Локальная Ollama (qwen3.5:9b и др.) в боевых воркерах запрещена (ограничение владельца; research
  §1/§8). Эмбеддинги beliefs — боевой embed-путь LLMClient (int8 опция как у graph_facts).
- **NFR-2 (RUNTIME v8):** единственный rebuild — v8 `graph_facts` в D1 (образец `_migrate_history_import_v7`);
  v8-колонки недоступны коду 2a-задач (B–C работают на v7: без SELECT/WHERE на importance/kind/belief_meta).
  Новые таблицы — `CREATE TABLE IF NOT EXISTS` без bump user_version. PG — только два аддитивных ADD COLUMN IF NOT
  EXISTS. Авто-миграция PG-промпта (канон R9) при деплое.
- **NFR-3 (мультичат, per-chat):** всё состояние — per `chat_id` (users_meta PK(chat_id,user_id); dream_state PK
  chat_id; nostalgia_log (chat_id, ts); PG-профили). Глобальные бюджеты (дистилляции/токены/сутки) — отдельно от
  per-chat лимитов. Никаких хардкод-чатов.
- **NFR-4 (fail-open):** любая новая точка (relations-чтение/инжект, dig, importance, воркеры, слой A/B, API) при
  ошибке БД/LLM/PG откатывается к предыдущему поведению с WARNING (дедуп-счётчики для частых ошибок), без падения
  запроса/бота и без «фантомных» LLM-денег. Тул-роутер никогда не бросает (строка результата). Инжект: флаг
  off/ошибка/нет данных → блока нет (0 влияния).
- **NFR-5 (анти-спам и бюджеты — условие приёмки 2b/2c):** ностальгия B: тишина, quiet hours, cooldown, max/сутки,
  стоп после 2 неотвеченных + pause, лог-аудит каждого решения; «сон»: не чаще тика/сутки на чат, глобальные лимиты
  кластеров/дистилляций/токенов в сутки (= денежный бюджет), дистилляции только в окне 04–06 local (кроме ручного
  run); dig — лимиты раундов tool_loop (TOOL_MAX_ROUNDS=4, ≤2 tool_calls/раунд).
- **NFR-6 (канон-дисциплина):** каждая user-facing промпт-правка — PREV-слепок + ступень `PROMPT_MIGRATIONS` +
  байт-тесты + авто-миграция PG при деплое. Промпты дистилляции/ностальгии — канон-константы модулей
  (`services/dream_prompts.py`, `services/nostalgia_prompts.py`), НЕ PG-сиды и НЕ REGISTRY (Q10). LEGACY/PREV/PREV_R8
  не трогать; тон/стиль канона (торопливое письмо, запрет «»/— в ответах, 1–2 предложения) не менять.
- **NFR-7 (нагрузка и деньги):** все новые записи — через единственное SQLite-соединение (WAL + busy_timeout 5 с,
  короткие транзакции); воркеры `max_instances=1` + `coalesce`; горячий путь не блокируется (touch — внутри
  save_smart_message с try/except; инжект — чтение по PK + TTL-кэш). Дневной расход ограничен hot-ключами;
  дефолты консервативные (боевые подфичи off).

---

## 3. Техдизайн (секции B–F; решения Q1–Q14 — врезками «Q-N:»)

### 3.1 Отношения (2a): users_meta + расчёт + PG relations + инжект

#### 3.1.1 users_meta — схема и db-методы (B1; Q1/Q4)

**Q1 (хранилище ручного):** ручная стадия и заметка админа — в PG `chat_profiles.relations JSONB` (map
`str(user_id) → {"manual_stage": "stranger"|"acquaintance"|"regular"|"veteran"|null, "note": str|null,
"updated_by": int|null, "updated_at": iso}`); правки — store-методами чат-лора с optimistic-409 по `updated_at`
профиля (§3.1.3). SQLite (`users_meta`) — ТОЛЬКО считаемое, read-only для web-api. Итоговая стадия инжекта:
`manual ?? auto`. История правок — внутри JSONB (D-2), НЕ в `chat_lore_history`.

**Q4 (состав колонок users_meta):** колонки research §5 сокращены: `trust`/`intimacy` НЕ храним (v1 их не вычисляет
и не инжектит; «теплоту» дают стадия + активность); `manual_stage` в SQLite НЕ заводим (Q1). Итог:

```sql
-- services/database.py, _SCHEMA_SQL (инициализация; строго CREATE TABLE IF NOT EXISTS,
-- user_version НЕ поднимается; образец bot_reply_parents database.py:239-258)
CREATE TABLE IF NOT EXISTS users_meta (
    chat_id            INTEGER NOT NULL,
    user_id            INTEGER NOT NULL,
    first_seen         INTEGER,              -- unix ts первого сообщения
    last_seen          INTEGER,              -- unix ts последнего сообщения
    msg_count          INTEGER NOT NULL DEFAULT 0,   -- всего (неавторитетно; счётчик-касание)
    active_days        INTEGER NOT NULL DEFAULT 0,   -- уникальных дней в 30д-окне
    activity_score     REAL    NOT NULL DEFAULT 0,   -- Σ 0.5^((now-ts)/half-life) за 30д
    relationship_stage TEXT    NOT NULL DEFAULT 'stranger',  -- авто-стадия (manual в PG)
    last_stage_change  INTEGER,               -- unix ts последнего изменения стадии
    last_recalc_at     INTEGER NOT NULL DEFAULT 0,   -- unix ts пересчёта (TTL-метка)
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_users_meta_chat_last
    ON users_meta (chat_id, last_seen DESC);
```

Методы `DatabaseService` (B1; единственное соединение, короткие транзакции):
- `refresh_users_meta(chat_id, user_ids=None, *, now=None) -> int` — ОДИН SQL-агрегат по `smart_messages` (образец
  `get_active_participants` :1664-1676; покрыт `idx_smart_messages_chat_ts`):
  `SELECT user_id, COUNT(*) AS total, MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts,
  COUNT(CASE WHEN timestamp>=? THEN 1 END) AS msg30,
  COUNT(DISTINCT CASE WHEN timestamp>=? THEN timestamp/86400 END) AS active_days30
  FROM smart_messages WHERE chat_id=? AND user_id IS NOT NULL [AND user_id IN (…)]
  GROUP BY user_id ORDER BY msg30 DESC, user_id ASC LIMIT ?` (D-19: агрегат ПО ВСЕЙ истории —
  total/first_ts/last_ts без фильтра окна, msg30/active_days30 — 30д-CASE'ы; при явном `user_ids` LIMIT не
  применяется). Затем в Python: `activity_score = Σ 0.5**((now − ts)/half_life)` по ts сообщений окна (для этого
  отдельный лёгкий SELECT (user_id, timestamp) того же окна; если строк окна чата >
  `limits.relations_scan_max_rows` (50000) — окно сжимается вдвое, до 3 итераций; вклад отброшенных < 0.35 и
  затухает, деградация осознанная). Батч-UPSERT в users_meta с правилом стадии §3.1.2. Возврат числа строк.
- `get_users_meta(chat_id, user_ids=None, limit=…) -> list[dict]` — SELECT по PK/чату.
- `touch_user_meta(chat_id, user_id, ts)` — «касание»: `INSERT … (chat_id,user_id,first_seen,last_seen,msg_count,
  last_recalc_at) VALUES … ON CONFLICT(chat_id,user_id) DO UPDATE SET last_seen=excluded.last_seen,
  msg_count=msg_count+1`. Вызов — ВНУТРИ `save_smart_message` (:1009-1039, единая точка записи L1 сообщений юзеров):
  после INSERT+FTS-строки, `if user_id is not None: try/except` — сбой не роняет сохранение (fail-open + WARNING с
  дедуп-счётчиком; 1 UPDATE по PK на сообщение, ~1 мс). Точка покрывает direct-путь и прочие сохранения; импорт
  истории (user_id NULL) и бот-сообщения (в smart_messages не пишутся) не касаются.
- Вспомогательный SELECT «последнее сообщение юзера/чата» для тишины/анти-спама — §3.5 (общий хелпер
  `last_user_message_ts(chat_id, bot_id, after_ts=None)`).

#### 3.1.2 Расчёт стадий, decay, анти-откат, ленивый кэш (B2; Q5)

**Q5 (стадии/decay/анти-откат):** авто-стадия — чистые тестируемые функции в `services/user_relations.py`; пороги —
hot-лимиты группы `limits_relations` (§3.6.4; дефолты по research §5 и задачам):

```
candidate(auto) по совокупным (msg_total, days_in_chat = now − first_seen):
  veteran      : msg_total >= 1000 И days_in_chat >= 365      (relations_veteran_min_msg/min_days)
  regular      : msg_total >= 200  И days_in_chat >= 90       (relations_regular_min_msg/min_days)
  acquaintance : msg_total >= 10   И days_in_chat >= 7        (relations_acquaintance_min_msg/min_days)
  stranger     : иначе
```

`first_seen` — по всей истории чата (для импортированного чата уходит в 2024 — «старики» корректно получают
veteran; это цель фичи). Анти-откат (Replika-урок research §5, задачи B2):
1. `now − last_seen > relations_hold_absent_days` (60) → стадия НЕ понижается (падает только `activity_score`);
2. иначе понижение — не чаще раза в `relations_stage_change_min_days` (30) с `last_stage_change` И только при
   `msg_30d < relations_downgrade_msg_30d` (10);
3. максимум на 1 ступень за раз (veteran→regular, никогда veteran→stranger);
4. ручная стадия из PG полностью блокирует авто (инжект-стадия = manual ?? auto) и НЕ трогает
   `relationship_stage`/`last_stage_change` (сброс manual → снова авто из колонки).
Повышение — мгновенно по правилам (без кулдауна); `last_stage_change` обновляется на любое изменение стадии.
Тон-санкции за абьюз — существующими кулдаунами, НЕ понижением стадии (research §5; задач не меняем).

Ленивый пересчёт: `RelationsService(db, aliases)` в `services/user_relations.py`; RAM-кэш per chat:
`dict[chat_id] → (mono_expire, rows_by_user)`, TTL 60 с. `ensure_fresh(chat_id, user_ids)` — при протухании/отсутствии
строк вызывает `db.refresh_users_meta` для запрошенных user_ids (инжект, FR-4); API-список (FR-14) — refresh топ-N
без явного списка. Расчётный код без зависимостей от PG (тесты на фикстуре SQLite). «Любимые темы юзера» — НЕ
реализуем (research §5 «опционально»).

#### 3.1.3 PG relations (B3; Q1/Q3, D-2/D-3)

- `pg_db.py` DDL_STATEMENTS — два аддитивных оператора (в конец кортежа; оба идемпотентны, применяются на старте как
  все DDL_STATEMENTS, pg_db.py:279):
  `ALTER TABLE chat_profiles ADD COLUMN IF NOT EXISTS relations JSONB NOT NULL DEFAULT '{}'` и
  `ALTER TABLE chat_profiles ADD COLUMN IF NOT EXISTS relations_enabled BOOLEAN NOT NULL DEFAULT FALSE`.
- `chat_lore_store.py`: `_PROFILE_COLS` += `relations`, `relations_enabled`; `_to_profile` — `json.loads(relations)`
  (пустой/нулевой → `{}`); `_to_row` — `json.dumps` (только при изменении); `lore_cache.py` `LoreProfile` (frozen)
  += `relations: dict = field(default_factory=dict)`, `relations_enabled: bool = False`; `to_dict()` += оба поля.
- Методы store (все: резолв chat_id как у `get_profile`; PG down → `ChatLorePgUnavailable`; профиля нет → PUT/DELETE
  через `ensure_profile`-семантику (существующий паттерн), GET → пусто):
  - `get_relations(chat_id) -> dict[str, dict]` — копия JSONB;
  - `put_relation(chat_id, user_id, *, stage='auto'|None, note=..., expected_updated_at) -> LoreProfile`: новый
    словарь ключа `str(user_id)` — `{"manual_stage": stage|null, "note": note|null, "updated_by": <telegram_id>,
    "updated_at": <now iso>}`; `UPDATE chat_profiles SET relations=$json::jsonb, updated_at=now() WHERE chat_id=$1
    AND updated_at=$expected::timestamptz` → 0 строк → `ChatLoreConflict(chat_id, current_updated_at)`
    (существующий класс, chat_lore_store.py:149); NOTIFY `lore_updated` внутри транзакции. `stage='auto'` → ключ
    удаляется из объекта (сброс на авто);
  - `delete_relation(chat_id, user_id, *, expected_updated_at)` — удаление ключа, тот же optimistic-паттерн;
  - `set_relations_enabled(chat_id, enabled: bool, *, expected_updated_at)` — колонка, optimistic; БЕЗ истории
    (паттерн `set_active`, lifecycle-прецедент). Переключение доступно из API settings-роута (§3.6.1).
- История `chat_lore_history` НЕ пишется (D-2): CHECK поля не содержит 'relations' (pg_db.py:92-94), расширять
  нельзя; аудит каждой правки — `updated_by`/`updated_at` внутри JSONB-значения. Осознанное ограничение v1: полного
  аудит-трейла правок отношений нет (последняя правка видна в карточке).
- Fail-open: нет PG-профиля → relations-часть пуста/создаётся ensure-профилем; инжект-сторона не ломается
  (гейт relations_enabled=false без профиля).

#### 3.1.4 Инжект `<user_relations>` (B4; Q3, D-10/D-14)

**Q3 (позиция/бюджет/формат):** блок kind `"relations"` — в `_build_user_content` СРАЗУ ПОСЛЕ `("target", …)`
(:633), ДО `_chat_lore_state`/protected. В `_apply_context_budget` kind `relations` добавляется в кортеж
`uncuttable` (:812 `("target","protected","lore","current","sandwich")` → += `"relations"`); защита от раздувания —
только cap `limits.relations_inject_max_chars` (600) ДО инжекта (урезание с конца строки + маркер `…[обрезано]`).
Гейты: `flags.relations_tone_enabled` (default false) И per-chat `relations_enabled` из PG-профиля (через
`get_lore_cache()`; компонент отсутствует/ошибка/профиля нет/false → блок не рендерится, 0 влияния). D-14
(фикс-раунд): блок — компактная карточка ТОЛЬКО ЦЕЛЕВОГО собеседника (адресата `<Target_User>`), НЕ список
активных юзеров окна (компактнее, тон относится к собеседнику; в v1 этого достаточно для правила канона).
Источник — `RelationsService.get_user_relation(chat_id, target_user_id)` (+ manual из PG — тот же вызов, что у
`_chat_lore_state`, дедуп на 1 запрос). Формат (имя — `target_name` из каскада хендлера, escape_xml_text;
`first_seen` — ts, `msg30` — лёгкий 30д-Count `db.count_user_msg30`; D-19: whole-history refresh):

```
<user_relations>{Имя}: {стадия_ru}, в чате с {first_seen:ГГГГ-ММ}, {msg30} сообщ. за 30 дней</user_relations>
```

`стадия_ru`: stranger=нюфаг, acquaintance=знакомый, regular=свой, veteran=ветеран; при ручной пометке — суффикс
«(ручная пометка админа)» в строке; при заметке админа — хвост ` | пометка: {note}` (escape_xml_text; XML-
экранирование). Пусто → блок не рендерится. uid-скобок в строках НЕТ (имена уже разрешены каскадом; дискриминаторы
не нужны — компактность). Тональное правило — в каноне R9 (§3.2.2); сам инжект тон не задаёт. Тесты G1: формат,
пусто/флаги/fail-open/PG-нет/бюджет-урезание не трогает relations (uncuttable).

### 3.2 dig_into_lore + канон R9 (2a)

#### 3.2.1 Tool dig_into_lore (C1; Q6)

**Q6 (схема/семантика):** третий элемент тул-сета; `services/tool_schemas.py`:

```python
TOOL_DIG_INTO_LORE = {
    "type": "function",
    "function": {
        "name": "dig_into_lore",
        "description": ("Глубокое копание в историю чата с датами и именами: помнишь/а помните/как мы тогда/"
                        "в 2024/что было с {имя}/ровно год назад/кто был тот. Вызывай ПЕРВЫМ и ОБЯЗАТЕЛЬНО до "
                        "ответа, когда речь про старое событие, конкретный год или человека из прошлого чата. "
                        "В query передай тему, в year - год (если назван), в person - имя (если названо). "
                        "Результат: датированные выдержки из переписки и факты."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "О чем вспомнить (обязательно)."},
                "year": {"type": "integer", "description": "Год события, например 2024 (необязательно)."},
                "person": {"type": "string", "description": "Имя участника, например Ваня (необязательно)."},
                "mode": {"type": "string", "enum": ["messages", "facts", "both"], "default": "both",
                         "description": "messages - переписка (FTS), facts - факты графа, both - и то и то."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
TOOL_CALLING_TOOLS = [TOOL_QUERY_CHAT_MEMORY, TOOL_DIG_INTO_LORE, TOOL_EXECUTE_WEB_SEARCH]
```

Порядок массива = канону R9 (query_chat_memory → dig_into_lore → execute_web_search): при ностальгии модель сначала
копает память, а не веб (research §4(в)); тул-сет ≤6 — ок.

Ветка `_dig_into_lore` в реестре tool_router.py (:102-105) с переиспользованием `_require_query`/`_resolve_name`/
`_format_timestamp`/`_truncate` (:206-224). Алгоритм (dispatch ВСЕГДА возвращает строку, НЕ бросает; флаг
`flags.dig_enabled`, default true → off: строка «Инструмент dig_into_lore отключен.»):
1. Валидация: mode не из enum → 'both' (WARNING); year вне [2000, текущий] → игнор (WARNING); query пуст →
   `_require_query` (фолбэк на текст сообщения); person → str ≤ 100 симв.
2. Ключи FTS: `keywords(query)`; при person — резолв форм имени через `self.deps.aliases` (каскад алиас/канон-имя/
   ник/юзернейм участника, найденного по display-имени; метод поиска «по имени» — если отсутствует в AliasResolver,
   используется casefold-форма person как токен). Все формы — OR-токенами.
3. Период: (а) year задан → `[Y-01-01 00:00, Y-12-31 23:59]` local (timezone `limits.summary_timezone`/settings);
   (б) иначе (фикс-раунд major-2): regex в query `(\d{1,2})\s+(?:лет|год(?:а)?)\s+назад` ИЛИ слова
   `(несколько|пару|тройку) лет назад` (N = 3/2/3) → `year = now.year − N` (диапазон = год целиком, как в (а));
   `limits.dig_year_back_window_days` (2) — зарегистрированный ключ окна точной даты (запас на будущее);
   (в) иначе периода нет (вся история, ранк решает).
4. Имена из графа (источник ИМЁН для FTS, не дат — research §4 п.2; фикс-раунд major-2): метод
   `db.dig_graph_related_names(chat_id, seed_terms, max_depth=limits.dig_graph_hop_depth (2), cap≈40)` — BFS по
   `nodes`/`edges` (entity_name casefold-содержит токен person/query, len≥4; ≤cap имён, visited-set). Если узлы/рёбра
   пусты ИЛИ метода нет — фолбэк `db.dig_fallback_target_names`: `SELECT DISTINCT target_user FROM graph_facts WHERE
   chat_id=? AND status='confirmed' AND target_user IS NOT NULL AND length(target_user)>1 LIMIT 300` → оставить те,
   что casefold-содержат токен. Собранные имена — OR-токенами (значимые слова, len≥3; общий кап merged ≈40). Всё
   best-effort (try/except → пусто).
5. Выборка (mode messages/both): `memory.search_long_term(chat_id, keywords_all, limit=dig_max_snippets*4)` (как
   `_query_chat_memory` :150-151), пост-фильтр периода по `timestamp`, нормализация `dict(row)` (T-678-урок),
   `_resolve_name`, рендер `[{Имя} {YYYY-MM-DD}]: {text}` (дата без времени; текст trim; дедуп по тексту) — максимум
   `limits.dig_max_snippets` (8).
6. Факты (mode facts/both): `memory.search_graph_facts_fts(chat_id, match_query, limit=dig_max_facts*3, now_ts,
   include_direct_reply=False)` (database.py:1431) + пост-фильтр периода по `rag_ts` (`COALESCE(message_timestamp,
   created_at)`); рендер `факт {YYYY-MM-DD}: {fact}` — до `limits.dig_max_facts` (3). v7-совместимо: колонки v8 не
   используются; после v8 beliefs попадают в выдачу как обычные факты (D-9) — код НЕ перестраивается.
7. Рендер: секции пустой строкой; `_truncate` к `limits.dig_max_symbols` (3500). Пусто →
   «По запросу «{query}» в истории ничего не найдено.» Ошибка этапа → WARNING + секция пуста (общая рамка НЕ
   бросает).

#### 3.2.2 Канон R9 (C2; текст правок — @Architect в этом документе)

**Q7 (контракт/пре-гейт):** контракт dig — в каноне (п.2); код-пре-гейт маркеров — отдельно, флагом off (п.3.2.3).

1. **Слепок:** текущий канон R8 (chat_prompts.py:85-109, HEAD 84c4887, байт-в-байт) → `PREV_R9_CHAT_SYSTEM_PROMPT`
   (константа в chat_prompts.py; докстринг «слепок HEAD 84c4887 до правок раунда 9»). LEGACY/PREV/PREV_R8 не трогать.
2. **`CHAT_SYSTEM_PROMPT` R9** = канон R8 + ТРИ аддитивные правки (всё остальное побайтово):

   (а) «КАК ЧИТАТЬ КОНТЕКСТ»: после «<Protected_Facts> и <chat_lore> - важные факты, помни о них всегда.» добавить
   « <user_relations> - твои отношения с участниками чата (стадия и активность).» (до «Теги не цитируй дословно…»).

   (б) После «ПРИОРИТЕТЫ» (после п.4 «Не путай людей…»), перед «ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:», вставить абзац
   (текст без «» и длинных тире; фикс-раунд major-3/D-15 — финальный текст канона, ПРИОРИТЕТЫ при этом БЕЗ п.5,
   dig-контракт — ровно в одном месте, ИНСТРУМЕНТЫ п.2):
   ```
   ОТНОШЕНИЯ:
   В блоке <user_relations> - отношения с тем, кто сейчас пишет (стадия и активность).
   1. Своему или знакомому отвечай как обычно.
   2. Ветерану чата - теплее, с отсылками к общему прошлому.
   3. Новичку - короче, без глубоких отсылок к лору.
   4. Если у собеседника есть ручная пометка админа - она важнее расчёта, не спорь с ней.
   5. Не упоминай сам блок и стадии в ответе.
   ```
   (нумерация/пунктуация — по образцу существующих блоков канона).

   (в) «ИНСТРУМЕНТЫ» — заменить перечень пунктов на три (хвост блока «Вызвал инструмент - отвечай строго по его
   результату. Не выдумывай цифры и факты…» — без изменений):
   ```
   ИНСТРУМЕНТЫ:
   У тебя есть инструменты - используй их, когда ответ требует данных, которых нет в контексте:
   1. query_chat_memory - история и факты этого чата. Вызывай ПЕРВЫМ при вопросах про прошлое: «сколько раз
   упоминалось слово или тема», «когда это было», «кто говорил», любая статистика чата. Результат инструмента
   содержит число совпадений и даты - цифры бери только из него.
   2. dig_into_lore - датированные выдержки из старой переписки и факты графа. Вызывай ПЕРВЫМ и ОБЯЗАТЕЛЬНО до
   ответа, когда юзер вспоминает: помнишь/а помните/как мы тогда/год назад/в 2024/что было с (именем)/кто был тот.
   В запросе передавай год и имя, если они названы. Не отвечай по памяти, пока не посмотришь результат копания.
   3. execute_web_search - свежие внешние данные: новости, проверка фактов в интернете, то, чего нет в контексте и
   памяти. Для вопросов о прошлом чата его не используй.
   ```
   Пункт 2 задаёт словесные триггеры («помнишь», «как мы тогда», «год назад», год, «что было с …»). «ГЛАВНОЕ
   ОГРАНИЧЕНИЕ», ПРИОРИТЕТЫ, стиль — без изменений (NFR-1/6; D-15: ПРИОРИТЕТЫ = ровно раунд 8, добавленный при
   реализации п.5 dig-триггера из канона УДАЛЁН — дубликат ИНСТРУМЕНТЫ п.2).

3. **Миграции:** `services/prompt_migrations.py` — 4-я ступень `PROMPT_MIGRATIONS["prompts.direct_chat_system_prompt"]`
   (:59-62): `(PREV_R9_CHAT_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT)`. Авто-миграция PG при деплое — H2.
4. **Байт-тесты:** `tests/test_direct_chat_prompts.py` — новый reference R9; тест `PREV_R9 == канон R8 из HEAD
   84c4887`; контракт dig (триггеры в п.2), правило ОТНОШЕНИЯ (п.4), `<user_relations>` в «как читать».
   `tests/test_prompt_migrations.py` — ступень (PREV_R9 → updated; R9 → no-op; кастом → не трогаем).

#### 3.2.3 Пре-гейт маркеров (C2(6); Q7)

Флаг `flags.dig_pre_gate_enabled`, default **false** (D-11; консервативно: dig живёт по контракту канона всегда и
тратит раунды только по вызову модели). В direct-пути (`handle`, после `_build_user_content`, перед генерацией;
фикс-раунд major-1) при флаге ON: (1) маркеры в тексте сообщения (regex, casefold-независимо): `помнишь`, `помните`,
`как мы тогда`, `как вы тогда`, `год назад`, `лет назад`, `в 20\d\d`, `кто был тот`, `а было же`, `когда-то`;
(2) → принудительный dig-ретривал: `tool_router.dispatch("dig_into_lore", {query, mode:"both"}, ctx)` — публичный
роутер-путь того же кода ветки `_dig_into_lore` — выполняется ДО генерации, результат инжектится в user-контент
блоком kind `"dig"` (секция `<dig_result>…</dig_result>` ПЕРЕД `<Target_User>`; фикс-кап `_DIG_RESULT_MAX_CHARS`≈3600
до инжекта; служебные ответы «отключен»/«ОШИБКА …»/пусто НЕ инжектятся; результат «ничего не нашёл…» инжектится —
модель видит, что копание уже было). Раунды TOOL_MAX_ROUNDS при этом не тратятся (результат уже в контексте).
Пусто/ошибка/флаг off → ничего не инжектится (fail-open). Гейт «RAG-контент беден» (из PM-базы) НЕ используется:
маркер — достаточное условие (модель сама решает по результату). Тест «маркер → dig ДО ответа» — с моком
memory/роутера.

### 3.3 Миграция v8 + importance (2b)

#### 3.3.1 Миграция v8 (D1; Q8)

**Q8 (важность существующих фактов/дефолт):** колонка `importance INTEGER NOT NULL DEFAULT 0`; после rebuild —
детерминированный backfill-правилом БЕЗ LLM (два UPDATE, §3.3.2-формула по origin/длине) — старые факты не выпадают
из «сна»/«золотых» навсегда. Записываемые факты (после D2) получают importance на записи (никогда не 0).

1. `_GRAPH_FACT_ORIGINS_SQL` (database.py:59-63) += `'derived_belief'` (единое место списка; вступает в силу при
   rebuild — v8).
2. Константа `_SCHEMA_VERSION_AGI_MEMORY = 8` (по образцу :42-49).
3. `_migrate_agi_memory_v8()` (образец `_migrate_history_import_v7` :614-709; вызов в `initialize` после v7 (:275-284),
   строго после v7-ступени; D1 исполняется в фазе 2b — до E1, но после B/C-задач, которые на v8-колонки не
   ссылаются):
   - guard: CREATE-текст `graph_facts` в `sqlite_master` НЕ содержит `importance` → иначе no-op (повторный запуск);
   - `ALTER TABLE graph_facts RENAME TO graph_facts_v8_legacy` → CREATE нового `graph_facts` (v7-колонки: id,
     chat_id, fact, origin CHECK(_GRAPH_FACT_ORIGINS_SQL), expires_at, created_at, target_user, status, supersedes,
     weight, last_confirmed_at, message_timestamp; НОВЫЕ: `importance INTEGER NOT NULL DEFAULT 0`, `source_ids TEXT`,
     `kind TEXT NOT NULL DEFAULT 'fact' CHECK(kind IN ('fact','belief'))`, `belief_meta TEXT`) →
     `INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, created_at, target_user, status, supersedes,
     weight, last_confirmed_at, message_timestamp) SELECT id, chat_id, fact, origin, expires_at, created_at,
     target_user, status, supersedes, weight, last_confirmed_at, message_timestamp FROM graph_facts_v8_legacy`
     (id сохраняется — FTS5 `graph_facts_fts` rowid валидны, НЕ пересоздаётся) →
   - backfill importance (по образцу §3.3.2-правила, БЕЗ LLM): (а) `UPDATE graph_facts SET importance = CASE origin
     WHEN 'user_memory' THEN 6 WHEN 'chat_history' THEN 4 WHEN 'history_import' THEN 2 WHEN 'bot_direct_reply' THEN 3
     WHEN 'voice_transcript' THEN 2 WHEN 'video_transcript' THEN 2 WHEN 'search_fact' THEN 3 WHEN 'youtube_content'
     THEN 3 WHEN 'web_content' THEN 3 END`; (б) `UPDATE graph_facts SET importance = MIN(10, importance + 1) WHERE
     length(fact) >= 200` →
   - `DROP TABLE graph_facts_v8_legacy` → индексы: повтор существующих (CREATE INDEX IF NOT EXISTS — id UNIQUE по
     факту PK; (chat_id, created_at); частичный history_import) + новые: `idx_graph_facts_chat_kind ON
     graph_facts(chat_id, kind)` и частичный `idx_graph_facts_beliefs ON graph_facts(chat_id) WHERE kind='belief'`
     (сон/ностальгия/API) → `PRAGMA user_version = 8`.
4. Аддитивные таблицы (CREATE IF NOT EXISTS в init, БЕЗ bump): `dream_state`, `memory_dream_log` (§3.4.1).
5. `db.insert_graph_fact` (:1382-1429) += параметры `importance: int | None = None`, `source_ids: str | None = None`,
   `kind: str | None = None`, `belief_meta: str | None = None`: importance=None → правило §3.3.2; kind → 'fact';
   INSERT-список колонок расширяется новыми (всегда пишутся: importance/kind/source_ids/belief_meta); существующие
   вызовы не меняются (дефолты). FTS-строка и commit — как сейчас.
6. Тесты (на копии фикстурной БД): данные/id сохранены, FTS5-поиск работает после миграции, origin-CHECK включает
   derived_belief, importance-бэкфилл применён и зажат [1..10], PRAGMA=8, повторный запуск no-op, регресс v2–v7,
   время rebuild на сэмпле ~10k строк (порог — по образцу замеров v7; на проде замер в H2).

#### 3.3.2 Importance-правило на записи (D2; Q8)

В `db.insert_graph_fact` при `importance is None` — правило БЕЗ LLM (единая точка: все origins пишут через неё):

```
importance = база по origin:
  user_memory → 6        history_import → 2   bot_direct_reply → 3
  voice_transcript/video_transcript → 2
  youtube_content/web_content/search_fact → 3
  chat_history → 4       (derived_belief → не через этот путь: DreamWorker передаёт явный importance)
+1 если текст содержит год (regex \b(19|20)\d{2}\b) ИЛИ число ≥ 3 цифр
+1 если длина факта >= 200 символов
clamp 1..10
```

Чистая функция `rule_importance(origin, fact) -> int` (в database.py рядом с insert_graph_fact или в
summary_memory — по месту вызова; тесты границ/дефолтов в test_graphrag_memory/test_database). Пачечный
LLM-importance НЕ вводим (Q8: v1 — правило; research §3 «и/или один LLM-вызов на пачку» — вне v1).

### 3.4 DreamWorker и beliefs (2b)

#### 3.4.1 Таблицы и каркас (D3)

```sql
CREATE TABLE IF NOT EXISTS dream_state (          -- watermark «сна» per chat (CREATE IF NOT EXISTS)
    chat_id INTEGER PRIMARY KEY,
    last_run_at INTEGER,                          -- unix ts последнего тика чата
    last_processed_fact_id INTEGER NOT NULL DEFAULT 0   -- max обработанный graph_facts.id чата
);
CREATE TABLE IF NOT EXISTS memory_dream_log (     -- аудит: строка на тик-чат + на дистилляцию
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    run_at INTEGER NOT NULL,                      -- unix ts события
    kind TEXT NOT NULL DEFAULT 'run',             -- 'run' | 'distilled' | 'skipped' | 'error'
    cluster_id INTEGER,                           -- № кластера в тике (для 'run' NULL)
    source_ids TEXT,                              -- JSON-массив id фактов-источников
    belief_id INTEGER,                            -- id созданного belief (для distilled)
    tokens INTEGER NOT NULL DEFAULT 0,            -- оценка токенов LLM-вызова (len/4)
    status TEXT                                   -- 'ok'/'unchanged'/'error'/'window_skip'
);
```

`services/dream_worker.py` — каркас `memory_maintenance.py` (AsyncIOScheduler + IntervalTrigger +
`max_instances=1` + `coalesce`), БЕЗ PG-lock (состояние в SQLite; PG-lock только у lore_worker). Конструктор
`DreamWorker(db, memory, llm)`; `start()` регистрирует джоб `dream_tick` ТОЛЬКО при
`flags.dream_enabled` (default false): `IntervalTrigger(minutes=limits.dream_tick_minutes=60, timezone=…)` (D-20,
фикс-раунд: минутный тик вместо суточного). bot.py
on_startup — после lore-блока (:459-486), по образцу LoreWorker (свой LLMClient при необходимости:
`_llm_client or LLMClient(hot…)` :468-473); try/except fail-open. `stop()` — как у соседей. Метод
`async run_once(chat_id: int | None = None) -> dict` — для ручного запуска (F2): общий код тика; in-process
`asyncio.Lock` `_run_lock`: повторный вызов при идущем прогоне → немедленный возврат `{"status": "already_running"}`
(API 409). `run_once` игнорирует окно диалогов (D-5) и бюджеты соблюдает.

#### 3.4.2 Тик: кандидаты-чаты и окно (D3; Q9)

**Q9 (чаты-кандидаты/окно сна):**
- Кандидаты-чаты: SQLite-агрегат по `graph_facts` против `dream_state`: чаты, где `id > COALESCE(ds.last_processed_fact_id, 0)` (для чатов БЕЗ строки dream_state — `created_at > now − limits.dream_initial_window_hours` (168 ч: неделя — первый «сон» не захлёбывается историей импорта)); порог «есть смысл» — новых фактов ≥ `limits.dream_min_new_facts_per_chat` (5); лимит чатов за тик `limits.dream_max_chats_per_run` (10), сортировка по числу новых DESC.
- Окно: LLM-дистилляции — только в local-часы `[limits.dream_window_start_hour (4), limits.dream_window_end_hour (6))` (timezone `limits.summary_timezone`/settings.SUMMARY_TIMEZONE). Вне окна тик делает отбор+кластеризацию (бесплатно), дистилляции помечает status='window_skip' и завершает тик (денег вне окна не тратит). D-20 (фикс-раунд): тик МИНУТНЫЙ (`IntervalTrigger(minutes=dream_tick_minutes=60)`) — повтор внеоконного скипа происходит через час, первый тик внутри окна дистиллирует; watermark вне окна не двигается (D-13). Ручной `run_once` окно игнорирует.
- Watermark обновляется в конце тика чата: `dream_state` upsert (last_run_at, last_processed_fact_id = MAX(id) обработанного).
- «Не пик» дополнительно: тик не запускается, если в чате были сообщения за последние `limits.dream_quiet_check_minutes` (30) — не пересекаемся с живым диалогом (дёшево: MAX(timestamp) smart_messages).

#### 3.4.3 Кластеризация без LLM (D3; Q9)

Кандидаты: новые факты чата (id > last_processed), `status='confirmed'`, `expires_at IS NULL OR > now`, origins —
ровно 4 «жизненных» источника `_DREAM_SOURCE_ORIGINS`: `chat_history`/`history_import`/`bot_direct_reply`/
`user_memory` (D-16, фикс-раунд: производные контенты search_fact/youtube_content/web_content/voice_transcript/
video_transcript и сами beliefs НЕ передистиллируются — нет рекурсии),
прошедшие гейт protected-семантики: текст факта НЕ входит в тексты `protected_facts` чата (chat-level + user-level,
до 500 текстов — прецедент memory_maintenance-merge; точное вхождение/совпадение после trim+casefold). Значимые
токены факта: слова len≥5, не из стоп-списка (и/в/на/не/что/как/так/это/был/была/было/были/его/её/свой/весь/она/
они/по/из/от/за/с/у/к/до/о/об/бы/же/ли/но/или) + имена участников чата (алиасы/roster-имена, casefold). Жадная
кластеризация: факты по id ASC; факт входит в первый кластер с ≥ `limits.dream_cluster_overlap_tokens` (2) общими
значимыми токенами ЛИБО общим именем-участником; иначе — новый кластер. Пороги в дистилляцию: членов ≥
`limits.dream_repeat_threshold` (3) И Σ importance ≥ `limits.dream_importance_sum_threshold` (12). Кандидаты —
по Σ importance DESC, в работу ≤ `limits.dream_max_clusters_per_run` (5). (D-4: subject-колонки нет; vec0-путь в v1
не используем — дешевле, детерминированно, тестируемо.)

#### 3.4.4 Бюджеты (D3)

- кластеров на тик: `limits.dream_max_clusters_per_run` (5);
- дистилляций в сутки (глобально): `limits.dream_distillations_per_day` (30) — `SELECT COUNT(*) FROM
  memory_dream_log WHERE kind='distilled' AND run_at >= <start of local day>`; достигнут → стоп тика (WARNING);
- токенов в сутки (денежный): `limits.dream_tokens_per_day` (60000) — оценка `max(1, len(prompt)/4 + len(answer)/4)`,
  сумма по `memory_dream_log.tokens` за local-сутки; достигнут → стоп тика (fail-open: оценка приблизительная, но
  консервативная);
- пер-чат: не чаще тика/сутки (watermark).
Каждая дистилляция перед вызовом LLM проверяет оба суточных бюджета; «почти у предела» (осталось < 5 дистилляций
или < 5000 токенов) → тик завершается заранее (WARNING).

#### 3.4.5 Дистилляция и промпт-канон (D4; Q10)

**Q10 (промпты дистилляции/ностальгии — константы модулей):** `services/dream_prompts.py`,
`services/nostalgia_prompts.py` — по образцу `lore_prompts.py`; НЕ PG-сиды и НЕ REGISTRY-ключи (не user-facing;
прецедент `_CHAT_RAG_RERANK_SYSTEM_PROMPT` summary_memory.py:237). Задачи не меняются (PM-база подтверждена).

`DREAM_DISTILL_PROMPT` (текст финально пишет @Architect при реализации C1-этапом; структура и требования — здесь):
```
СИСТЕМНАЯ РОЛЬ:
Ты - синтезатор долговременной памяти чата. Тебе дают кластер фактов (каждый с номером, датой и текстом),
повторяющихся в переписке чата. Если в кластере есть устойчивое повторяющееся правило про человека, обычай чата
или регулярное событие - сформулируй 1-2 коротких убеждения (до 120 символов каждое), обобщающих эти факты.
Убеждение не должно противоречить ни одному факту кластера.

ПРАВИЛА:
1. Отвечай СТРОГО одним JSON-объектом без пояснений:
   {"beliefs":[{"text":"...","evidence":[<номера фактов>]}]}
2. Каждое убеждение опирается минимум на 2 факта кластера; evidence - их номера.
3. Текст убеждения - без кавычек-ёлочек и длинных тире.
4. Если устойчивого повторения нет или факты противоречат друг другу - верни {"beliefs":[]}.

USER:
Кластер фактов чата:
1. [2024-05-12] Вася опять не заплатил за пиво
2. ...
```

Вызов: ОДИН `llm.generate([system, user])` на кластер (облачный LLMClient, hot-ключи models/keys, дефолтные
таймауты; локальная LLM запрещена — NFR-1). user-блок: до 25 фактов `N. [ГГГГ-ММ-ДД] текст` (дата =
message_timestamp или created_at), сортировка по важности DESC. Парсинг: JSON-объект; `beliefs: []` → лог
distilled/status='unchanged' (бюджеты не тратятся сверх 1 вызова); кривой JSON/исключение → 1 retry → error
(fail-open); evidence с номерами вне списка — отбрасываются; belief с evidence < 2 реальных фактов — НЕ пишется
(анти-галлюцинации; каждое убеждение обязано иметь ≥2 source_ids).

#### 3.4.6 Запись beliefs и supersede (D4; D-6)

Запись: `db.insert_graph_fact(chat_id, fact=b.text, origin='derived_belief', expires_at=None, weight=0.6
(константа _DREAM_BELIEF_WEIGHT), importance=min(10, Σ importance источников), source_ids=json.dumps([id…]),
kind='belief', belief_meta=json.dumps({"confidence", "sources_count", "distilled_at", "cluster_id"}), status=
'confirmed')`. Правила:
- `source_ids` пусто/нет реальных id → belief НЕ пишется (лог 'error');
- embedding — `_save_graph_fact_embedding` (боевой embed-путь, как у обычных фактов; неудача → факт живёт
  текстом+FTS — деградация как в бою);
- supersede (D-6): перед INSERT — `SELECT id FROM graph_facts WHERE chat_id=? AND kind='belief' AND
  supersedes IS NULL ORDER BY created_at DESC LIMIT 1`-класс поиск «того же якорного токена» (первый значимый токен
  текста нового belief, len≥5 не стоп) в тексте старого; найден → `UPDATE graph_facts SET supersedes=new_id WHERE
  id=old_id` (старый остаётся, ссылка фиксирует замену; RAG видит confirmed у обоих — ранг решает; review-дедуп не
  трогаем);
- nodes/edges НЕ создаём; protected-гейт — на входе кластера (§3.4.3);
- аудит: строка memory_dream_log kind='distilled' (chat_id, run_at, cluster_id, source_ids, belief_id, tokens,
  status) на каждый результат дистилляции (в т.ч. unchanged/skipped/error/window_skip) + строка kind='run' на
  тик-чат (cluster_id=NULL, status='ok').

#### 3.4.7 Рендер beliefs в RAG (D4)

Beliefs участвуют в retrieval как обычные факты (тексты в FTS graph_facts_fts + эмбеддинги в vec0 — запись из
3.4.6). Рендер-метка — ТОЛЬКО direct-рендер `_ORIGIN_LABELS` (summary_memory.py:223-233) +=
`"derived_belief": "убеждение"` → строка `[убеждение] {ГГГГ-ММ-ДД} {текст}` в `build_rag_context(origin_labels=True)`
(:545-562; единственный потребитель — direct `_build_rag_block` :1399 и rerank-кандидаты). Легаси
`<context>`-рендеры (`origin_labels=False`) и прочие пайплайны не меняются (NFR-2 раунда 8: метки только в
direct-рендере). Дата belief в рендере — created_at (у beliefs нет message_timestamp).

#### 3.4.8 Мягкое удаление и защита beliefs (F4-кнопки)

- «Удалить» (D-7): новый db-метод `soft_delete_graph_fact(fact_id)` → `UPDATE graph_facts SET
  status='unconfirmed', last_confirmed_at=NULL WHERE id=? AND kind='belief'` — belief исключается из RAG
  (статус-фильтр confirmed везде), вычищается существующим review-воркером. Hard-delete не делаем (FTS5/vec0
  согласованность).
- «Сделать protected»: INSERT текста в `protected_facts` чата (user_name NULL — chat-level) существующим методом
  записи protected (тем, что использует память-команда; точное имя — по коду при реализации). Belief остаётся в
  графе; в дальнейшем гейт «сна» (§3.4.3) его не тронет (текст в protected).

### 3.5 Ностальгия (2c): слой A, затем слой B

#### 3.5.1 Слой A (E1; Q12)

**Q12 (флаги-дефолты для прода — сводно):** все боевые подфичи off по умолчанию
(`relations_tone_enabled`, `dream_enabled`, `nostalgia_layer_a_enabled`, `nostalgia_enabled`, `dig_pre_gate_enabled`),
кроме `dig_enabled` (true — тул доступен, раунды тратит только по вызову модели) и per-chat `relations_enabled`
(колонка false до включения админом в TMA). Канон R9 и миграция v8 — единственные неизбежные изменения поведения.

Флаг `flags.nostalgia_layer_a_enabled` default **false**. Только чаты `chat_id < 0` (D-12). Точка: `_build_rag_block`
(direct_chat_service.py:1355-1409) — после F2-дедупа и F4-реранка, ДО рендера; условия: флаг ON, `kept` непуст,
query есть, чат групповой. Вызов нового метода `memory.fetch_golden_facts(chat_id, query, *, min_importance,
min_age_days, limit)` (v8-колонки; KNN/FTS тем же путём `_search_graph_facts`, но с SQL-фильтром
`f.kind='fact' AND f.importance >= ? AND COALESCE(f.message_timestamp, f.created_at) < ?`; origin beliefs исключены
(нет даты события); НИКОГДА не бросает → []). Пороги: `limits.nostalgia_golden_min_days` (60),
`limits.nostalgia_golden_min_importance` (5); максимум `limits.nostalgia_layer_a_max_hints` (1) на ответ. Если
золотой факт уже в `kept` — хинт не добавляем (нет нового сигнала). При найденном: блок kind `"nostalgia"` в
user-контент ПОСЛЕ `relations`/до mood (фикс-кап `limits.nostalgia_hint_max_chars` (300) ДО инжекта; в порядке
урезания участвует последним):

```
nostalgia_hint: вспомни и вплети, если уместно: [2024-07-12] {текст факта}
```

Решение о вплетении — за LLM; 0 добавочных LLM-вызовов; ошибка → хинта нет (WARNING). Канон R9 НЕ правится
(подсказка самодостаточна; блок редкий и маленький).

#### 3.5.2 Лог и кандидаты-«золотые» слоя B (E2)

```sql
CREATE TABLE IF NOT EXISTS nostalgia_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,                        -- unix ts события
    kind TEXT NOT NULL DEFAULT 'golden',        -- 'year_back' | 'golden' | 'none'
    fact_id INTEGER,                            -- graph_facts.id (для 'golden')
    status TEXT NOT NULL,                       -- 'sent' | 'skipped' | 'error'
    meta TEXT,                                  -- JSON: reason, candidate_text, llm_skipped
    created_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nostalgia_log_chat_ts ON nostalgia_log (chat_id, ts);
```

Кандидаты (per chat, на тике):
- «N лет назад в этот день»: строки `smart_messages` c `timestamp ∈ [now − N*365д ± limits.nostalgia_year_back_days_window (2)]` (N=1; для N>1 — только если регекс года в теме диалога), непустой текст, ≤3 строки «[Имя YYYY-MM-DD]: текст»; вес набора 0.7;
- «золотые» по последней теме: ключи последних 5 юзерских сообщений → `fetch_golden_facts` (§3.5.1) — 1–2 факта; вес факта `0.3 + 0.05*importance` (importance 5..10 → 0.55..0.8).
При нескольких кандидатах — максимальный вес. Порог срабатывания `0.3 + limits.nostalgia_aggressiveness*0.5`
(дефолт 0.3 → порог 0.45): вес ниже → skip reason='threshold'. `aggressiveness` (0..1) влияет ТОЛЬКО на порог
(частота — max_per_day/cooldown/тишиной; решение: «насколько слабый повод сработает»).

#### 3.5.3 Условия тика и анти-спам (E2; Q13/Q14)

**Q13 (релей/чаты):** слой B — ТОЛЬКО группы/супергруппы (`chat_id < 0`; лички исключены — D-12). Список чатов —
НОВЫЙ read-only метод `ChatLoreStore.list_active_chat_ids()` (`SELECT chat_id FROM chat_profiles WHERE is_active`;
существующий `list_active_chats` НЕ переиспользуем — у него `AND auto_enabled`, семантика лора). PG down/пусто →
тик no-op (WARNING). Отправка: `NostalgiaWorker` получает `bot` (Telegram Bot из bot.py on_startup; прецедент
GoodmorningRelay) и шлёт `bot.send_message(chat_id, text)` БЕЗ parse_mode (plain; html-инъекций нет). Сбой отправки
→ nostalgia_log status='error'.

**Q14 (детект неотвеченных; D-17 фикс-раунд):** стоп после `limits.nostalgia_unanswered_max` (2) проактивных
подряд без ответа. Проверка в момент кандидата: последние `unanswered_max`+1 записей `status='sent'` чата за окно
`limits.nostalgia_pause_hours` (24 ч — НЕ константа 24, окно = ключ паузы) из nostalgia_log;
каждая «отвечена», если `SELECT COUNT(*) FROM smart_messages WHERE chat_id=? AND user_id IS NOT NULL AND
user_id != ?(bot_id) AND timestamp > sent_ts` > 0 (бот-сообщения в smart_messages не пишутся — прецедент observer;
импортные user_id NULL не считаются). Последние 2 sent (в окне pause_hours) не отвечены → skip reason='unanswered';
пауза НЕЯВНАЯ: пока окно pause_hours не пройдёт ИЛИ юзер не ответит, то же условие повторяется на следующих тиках
(отправки не будет). Та же формула cooldown (разные ключи): между sent — `limits.nostalgia_cooldown_hours` (12).

Условия per chat на тике (последовательно; skip-причины пишутся в nostalgia_log только для «дорогих» шагов —
candidate/threshold/llm; дешёвые скипы — WARNING-лог, без строк: не мусорить таблицу):
1. `flags.nostalgia_enabled` (global, hot) ON; чат `chat_id < 0`; профиль is_active (список Q13).
2. Тишина: последнее юзерское сообщение (`MAX(timestamp)`, user_id NOT NULL AND != bot_id) старше
   `limits.nostalgia_min_silence_minutes` (45); истории нет вовсе → skip (no_history).
3. Quiet hours: local-час (timezone summary_timezone) — активны если `hour >= nostalgia_quiet_start_hour (23)` ИЛИ
   `hour < nostalgia_quiet_end_hour (8)` (пересечение полуночи) → skip.
4. Cooldown 12 ч с последнего sent (Q14-формула) → skip.
5. `COUNT(status='sent')` за local-сутки ≥ `limits.nostalgia_max_per_day` (3) → skip.
6. Неотвеченные ≥ `unanswered_max` (Q14/D-17) → skip (пауза неявная, окно pause_hours).
7. Бот исключён из «юзеров» везде (`bot_id` в конструкторе).

#### 3.5.4 Текст и LLM-вызов (E2; Q10)

`NOSTALGIA_PROMPT` (services/nostalgia_prompts.py; финальный текст — при реализации):
```
СИСТЕМНАЯ РОЛЬ:
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год
назад в этот день и/или старые факты по последней теме разговора. Если вспомнить уместно и по делу - напиши 1-2
короткие фразы «кстати...» в своём стиле: ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире.
Если вспоминать неуместно или память бедна - ответь ровно одним словом: UNCHANGED.

USER:
В чате давно тихо. Вот память:
<кандидаты>
```

Вызов: 1 облачный LLM-вызов на срабатывание (LLMClient; NFR-1). Ответ `UNCHANGED` (равенство с точностью до
регистра/пробелов) → nostalgia_log 'skipped' reason='unchanged' (лимит max_per_day НЕ тратится — только sent).
Текст: trim, cap `limits.nostalgia_max_send_chars` (400); пустой → skipped reason='empty'. Отправка по Q13 →
'error' при исключении Bot API (retry не делаем; следующий тик сам повторит при выполнении условий). Успех →
status='sent', meta={candidate, kind, fact_id}. Примечание: слой B не ограничен окном «сна» (4–6) — это разные
воркеры; анти-спам отдельный, пересечений нет (WAL single-writer выдержит: вызовы редкие, короткие транзакции).

#### 3.5.5 Каркас NostalgiaWorker (E2)

`services/nostalgia_worker.py`: AsyncIOScheduler + `IntervalTrigger(minutes=limits.nostalgia_tick_minutes=60,
timezone=…)` + max_instances=1 + coalesce; джоб `nostalgia_tick` при `flags.nostalgia_enabled` (default false).
`NostalgiaWorker(db, memory, store, llm, bot, bot_id)`; `start()`/`stop()`; bot.py on_startup — после DreamWorker
(try/except fail-open; store из lore_runtime; store отсутствует → воркер живёт, но чаты пусты). Тик: чаты Q13
последовательно; ошибка чата → WARNING (тик жив). Каждый шаг — короткие чтения; максимум 1 LLM-вызов + 1 отправка
на чат.

### 3.6 API/TMA

#### 3.6.1 Relations API (F1; Q2)

**Q2 (db в lore_runtime):** `services/lore_runtime.py` += компонент db: `set_lore_components(store=None, cache=None,
notify=None, worker=None, db=None)` (новый kwarg; существующие вызовы совместимы — reset_lore_runtime/autouse-
fixture conftest обнуляют всё) + геттер `get_lore_db()` (None — не установлен). Новые web-api-роуты (relations)
читают SQLite-часть только через `get_lore_db()`; db None/ошибка → SQLite-часть пуста (fail-open), PG-часть
работает.

Файл: расширение существующего `web/api/chat_lore.py` (роуты relations в том же модуле — общие helpers
`_components`/`can_access_chat`/`_conflict`; D-решение: отдельный файл НЕ заводим, прецедент shared-helper).
Роуты (все под `Depends(get_tma_user)`; «доступ к чату» = `can_access_chat` §3.8 раунда 7: глобальный admin ИЛИ
строка chat_admins; PUT/DELETE/тумблер — те же права):
- `GET /api/chat_lore/{chat_id}/relations` → `{chat_id, users: [{user_id, name, stage_auto, stage_manual, stage,
  msg_count, msg_30d, active_days_30, activity_score, first_seen, last_seen, note}]}`: SQLite-часть —
  `db.refresh_users_meta(chat_id)` без явного списка (лимит `limits.relations_api_max_users`=150; агрегат по всей
  истории с окном 30д — быстрый GROUP BY по индексу) + `get_users_meta`; PG-часть — `store.get_relations(chat_id)`
  (manual/note мержатся по `str(user_id)`); `name` — каскад aliases (uid → алиас → ник → юзернейм), при None — uid.
  Сортировка (D-18, фикс-раунд): `activity_score` DESC (None/0 — в конце, стабильно по last_seen/user_id). 404: чат не существует/нет доступа → 403; PG down → 503-паттерн
  `_components` (SQLite-часть всё равно пуста при db None — ответ 503 как у chat_lore, единообразно).
- `PUT /api/chat_lore/{chat_id}/relations/{user_id}` body `{stage: 'auto'|'stranger'|'acquaintance'|'regular'|
  'veteran', note?: str|null, updated_at: str}`: stage вне enum → 422; `store.put_relation(…, expected_updated_at=
  updated_at)`; `ChatLoreConflict` → 409 `{detail:{code:"conflict", current_updated_at}}` (`_conflict`-хелпер :121);
  история НЕ пишется (D-2); NOTIFY; ответ — обновлённый профиль (relations + updated_at). Профиля нет →
  ensure_profile перед записью (не создаёт auto-лор-эффектов — is_active=true дефолт).
- `DELETE /api/chat_lore/{chat_id}/relations/{user_id}` body `{updated_at}` → сброс на авто (удаление ключа);
  409-паттерн как выше.
- Тумблер per-chat: расширение существующего `PUT /api/chat_lore/{chat_id}/settings` — body += `relations_enabled:
  bool|null`; `store.update_settings` обрабатывает ключ через `set_relations_enabled` (БЕЗ истории; 409 по
  updated_at как у прочих полей). (Тумблер нужен админу «Лор чатов», чтобы включить тон по стадиям в чате.)

#### 3.6.2 Dream/Nostalgia API (F2; D-7/D-8)

Новый модуль `web/api/memory_agi.py` (APIRouter; include в `web/app.py` рядом с api_router/chat_lore_router,
prefix="/api"); DI — `lore_runtime` (get_lore_db) + модульные держатели воркеров: `lore_runtime` расширяется
геттерами `get_dream_worker()`/`get_nostalgia_worker()` и set-параметрами (по образцу lore-компонентов; воркер не
установлен → 503). Права: ручной запуск/удаление — ТОЛЬКО глобальный admin (паттерн `_is_global_admin`); GET-логи —
глобальный admin (консервативно; moderator-выдачи не расширяем, известные роли не трогаем).
- `POST /api/memory/dream/run` body `{chat_id?: int|null}`: воркер установлен и не бежит → `asyncio.create_task(
  worker.run_once(chat_id))` + ответ **202** `{status: "started"}`; уже бежит → **409** `{detail:{code:
  "already_running"}}`; воркер нет/флаг выключен — run работает (ручной запуск не зависит от flags.dream_enabled,
  только от флага «бежит»); окно 4–6 ручной запуск игнорирует (D-5). (Синхронный ответ после LLM-прогона не делаем:
  до 5 кластеров × минуты — таймаут API; прецедент async-запусков.)
- `GET /api/memory/dream/beliefs?chat_id=&limit=50` → последние `kind='belief'`: id, fact, weight, importance,
  source_ids (list), belief_meta (dict), status, supersedes, created_at, chat_id.
- `DELETE /api/memory/dream/beliefs/{id}` → мягкое удаление (`soft_delete_graph_fact`, §3.4.8) → 200; id нет/не
  belief → 404.
- `GET /api/memory/dream/log?limit=100` → строки memory_dream_log (аудит «снов»; TMA «последние сны»).
- `POST /api/memory/dream/beliefs/{id}/protect` → «сделать protected» (§3.4.8) → 200.
- `GET /api/memory/nostalgia/log?chat_id=&limit=100` → строки nostalgia_log (status sent/skipped/error + meta).
- `POST /api/memory/nostalgia/test` — НЕ реализуем (D-8).

Коды по конвенции: 401 (нет initData)/403/404/409/422/503 (PG/компонент недоступны — fail-open).

#### 3.6.3 TMA-блоки (F3/F4)

- **«Лор чатов» → блок «Участники и отношения»** (index.html, кастомная ветка `chat_lore` :494-743; НОВАЯ карточка
  под карточкой профиля): видимость — глобальный admin ИЛИ chat-admin текущего чата (по can_access_chat-семантике
  фронта: кнопки правок — при правах; при отсутствии — блок скрыт или read-only список по решению реализации;
  минимум: скрыт для остальных). Контент: тумблер «Влиять на тон бота (relations_enabled)» (per-chat) + таблица
  участников: имя (каскад), авто-стадия, select ручной стадии («авто»/нюфаг/знакомый/свой/ветеран), скор
  (activity_score, msg_30d), first/last_seen, заметка (textarea, кнопка «сохранить»), кнопки «сбросить на авто» и
  «удалить заметку» (одна кнопка «сброс» стирает и stage и note). 409-флоу как chatLore409 (:124, модалка
  «перезагрузить?» → reload). app.js: data `relationsList`, `relationsEnabled`; методы `loadRelations/saveRelation/
  resetRelation/saveRelationsToggle` (PUT settings с updated_at профиля); обновление при смене чата; тосты.
- **«Память и RAG» → мини-блоки «Синтез (сон)» и «Ностальгия»** (index.html, config-секция :338-440, ПОД
  generic-рендером, `v-if="activeTab === 'memory_rag'"`):
  - «Синтез (сон)»: кнопка «Запустить синтез сейчас» (POST run, спиннер, ответ 202/409), список последних beliefs
    (GET, карточки: дата, текст, вес, importance, source_ids-count) с кнопками «удалить» (мягкое) и «сделать
    protected», «лог снов» (GET log, компактно). Права: кнопка run/удаление — глобальный admin (ответ 403 иначе);
    список — по canViewTab('memory_rag').
  - «Ностальгия»: «последние срабатывания» (GET log; статусы sent/skipped/error с meta-reason; пусто — «пока
    пусто»).
  - Разметка: вложенный div после generic-групп; app.js-методы dreamBeliefs/runDreamNow/dreamDelete/dreamProtect/
    nostalgiaLog (api()-хелпер, тосты, 401/403-редирект как соседи).
- **REGISTRY-ключи** (§3.6.4): flags/limits relations — новые группы `flags_relations`/`limits_relations`
  (категории flags/limits → стандартная вкладка настроек; исключений TAB_RULES не требуют: `except`-правила не
  затрагивают новые группы, memory_rag-правила — явные frozenset'ы); dig — группы `flags_memory`/`limits_memory`
  (вкладка «Память и RAG», TAB_RULES :1072-1076 — новые ключи попадают автоматически); dream/nostalgia — НОВАЯ
  категория memory с группами `memory_dream`/`memory_nostalgia` (рендерятся на «Память и RAG» через
  `(CATEGORY_MEMORY, None)` :1075; категория уже существует — SEED_CATEGORIES включает, _category_title «Память»
  заведён в routes.py). Никаких новых TMA-вкладок.

**Q11 (размещение настроек REGISTRY):** relations → категории flags/limits (группы `flags_relations`/
`limits_relations`) — глобальные пороги и рубильник тона, рендер на общей вкладке настроек; per-chat тумблер
`relations_enabled` — колонка PG-профиля (блок «Участники и отношения»); dig → `flags_memory`/`limits_memory`
(память/поиск); dream/nostalgia → категория memory (группы `memory_dream`/`memory_nostalgia`, вкладка «Память и
RAG»). Итог: A-Life-настройки чата — в «Лор чатов» (PG per chat), остальное — существующие категории/группы, без
новых вкладок и без пересечений TAB_RULES.

#### 3.6.4 Итоговые конфиг-ключи (все — REGISTRY-записи + дефолты config/settings.py + PG-сид; флаги/лимиты через hot.get с фолбэком settings)

Флаги (default **false**, если не указано):
`flags.relations_tone_enabled` (f) · `flags.dig_enabled` (**t**) · `flags.dig_pre_gate_enabled` (f) ·
`flags.dream_enabled` (f) · `flags.nostalgia_layer_a_enabled` (f) · `flags.nostalgia_enabled` (f).

Лимиты relations (группа `limits_relations`; вкладка настроек): `relations_acquaintance_min_msg` (10),
`relations_acquaintance_min_days` (7), `relations_regular_min_msg` (200), `relations_regular_min_days` (90),
`relations_veteran_min_msg` (1000), `relations_veteran_min_days` (365), `relations_hold_absent_days` (60),
`relations_stage_change_min_days` (30), `relations_downgrade_msg_30d` (10), `relations_decay_half_life_days` (14),
`relations_recalc_ttl_minutes` (5), `relations_scan_max_rows` (50000), `relations_inject_max_chars` (600),
`relations_api_max_users` (150).

Лимиты dig (группа `limits_memory`): `dig_max_snippets` (8), `dig_max_facts` (3), `dig_max_symbols` (3500),
`dig_graph_hop_depth` (2), `dig_year_back_window_days` (2).

Лимиты dream (категория memory, группа `memory_dream`): `dream_tick_minutes` (60, D-20 фикс-раунд; был
`dream_tick_hours` (24) — ключ переименован, REGISTRY-запись заменена),
`dream_window_start_hour` (4), `dream_window_end_hour` (6), `dream_initial_window_hours` (168),
`dream_min_new_facts_per_chat` (5), `dream_max_chats_per_run` (10), `dream_quiet_check_minutes` (30),
`dream_cluster_overlap_tokens` (2), `dream_repeat_threshold` (3), `dream_importance_sum_threshold` (12),
`dream_max_clusters_per_run` (5), `dream_distillations_per_day` (30), `dream_tokens_per_day` (60000).

Лимиты nostalgia (категория memory, группа `memory_nostalgia`): `nostalgia_tick_minutes` (60),
`nostalgia_min_silence_minutes` (45), `nostalgia_quiet_start_hour` (23), `nostalgia_quiet_end_hour` (8),
`nostalgia_cooldown_hours` (12), `nostalgia_pause_hours` (24), `nostalgia_unanswered_max` (2),
`nostalgia_max_per_day` (3), `nostalgia_golden_min_days` (60), `nostalgia_golden_min_importance` (5),
`nostalgia_layer_a_max_hints` (1), `nostalgia_hint_max_chars` (300), `nostalgia_year_back_days_window` (2),
`nostalgia_aggressiveness` (0.3, float 0..1), `nostalgia_max_send_chars` (400).

Константы (НЕ ключи): `_DREAM_BELIEF_WEIGHT` (0.6), промпт-каноны `DREAM_DISTILL_PROMPT`/`NOSTALGIA_PROMPT`,
`_ORIGIN_LABELS['derived_belief'] = 'убеждение'`, `PREV_R9_CHAT_SYSTEM_PROMPT`.

### 3.7 Сводка решений Q1–Q14

| Q | Вопрос | Решение |
|---|---|---|
| Q1 | relations: manual в PG vs SQLite | manual-стадия/заметка — PG `chat_profiles.relations JSONB`; SQLite `users_meta` — только считаемое (read-only для API). История правок — внутри JSONB (D-2), 409 по updated_at профиля |
| Q2 | db в lore_runtime | да: `set_lore_components(..., db=None)` + `get_lore_db()`; web-api relations читает SQLite только через runtime |
| Q3 | позиция/бюджет `<user_relations>` | сразу после `<Target_User>`; kind `relations` в uncuttable; cap `relations_inject_max_chars` (600) до инжекта; per-chat тумблер — колонка `relations_enabled` (D-3) |
| Q4 | состав users_meta | без trust/intimacy и без manual_stage; PK(chat_id,user_id); см. SQL §3.1.1 |
| Q5 | стадии/decay/анти-откат | пороги конъюнкцией (msg_total И days); decay Σ0.5^((now−ts)/14д); понижение: ≤1/30д, −1 ступень, при last_seen>60д — НЕ понижать; manual блокирует авто |
| Q6 | dig-схема | query/year/person/mode (enum, default both); год→диапазон; «N лет назад»→год now.year−N (major-2); person→алиасы-формы; граф-имена BFS≤2 (фолбэк target_user); рендер `[Имя ГГГГ-ММ-ДД]: текст` + `факт …`; не бросает |
| Q7 | пре-гейт маркеров | контракт в каноне R9 (ИНСТРУМЕНТЫ п.2); код-пре-гейт флагом `dig_pre_gate_enabled` default false; результат dig инжектится `<dig_result>` до Target_User |
| Q8 | importance старых/дефолт | колонка DEFAULT 0; бэкфилл правилом (origin-база+длина, 2 UPDATE); на записи правило (никогда 0); пачечный LLM — вне v1 |
| Q9 | sleep-window/чаты-кандидаты | тик IntervalTrigger(minutes=dream_tick_minutes)=60 (D-20); LLM-дистилляции только 4–6 local (иначе window_skip, watermark не двигается); кандидаты по dream_state watermark (нет строки — неделя); окно не пересекается с диалогом (30 мин тишины) |
| Q10 | промпты PG vs константы | константы модулей (`dream_prompts.py`/`nostalgia_prompts.py`), НЕ PG/REGISTRY |
| Q11 | REGISTRY-размещение | relations → flags/limits (группы flags_relations/limits_relations); dig → flags_memory/limits_memory; dream/nostalgia → категория memory (memory_dream/memory_nostalgia) |
| Q12 | флаги-дефолты прода | off всё, кроме dig_enabled (t) и per-chat relations_enabled (f до включения админом); неизбежные изменения: канон R9 + v8 |
| Q13 | релей ностальгии | только chat_id<0; чаты = is_active PG-профили (новый `list_active_chat_ids`); отправка `bot.send_message` без parse_mode; PG down → no-op |
| Q14 | детект неотвеченных | по smart_messages: нет юзерских сообщений (user_id != bot) после sent_ts; ≥2 подряд в окне `nostalgia_pause_hours` (24) → skip (пауза неявная — D-17) |

---

## 4. Edge cases

1. **PG down / компоненты lore_runtime не установлены:** relations-инжект → блока нет (0 влияния); relations API →
   503 (как chat_lore); NostalgiaWorker → no-op тик; PUT relations → 503, данные не теряются (JSONB не тронут).
2. **SQLite занят (воркер vs диалог):** единственное соединение WAL + busy_timeout 5 с; записи воркеров —
   короткие транзакции; конфликт → WARNING, повтор на следующем тике; пользовательский путь никогда не блокируется
   инжектом/тачем (try/except).
3. **Миграция v8 на живой БД (~1.9–2.2M smart_messages; graph_facts — сотни тысяч):** rebuild в D1 при старте;
   контрольный снапшот перед деплоем (H2); повторный запуск no-op (guard); FTS5 graph_facts_fts НЕ пересоздаётся
   (rowid стабильны) — иначе потеряли бы индекс на ~минуты и ранг-порядок.
4. **2a-код до D1:** ветка dig-фактов и все B/C-пути работают на v7 (не трогают v8-колонки); после v8 dig
   продолжает работать без изменений (D-9). Золотой слой A и fetch_golden_facts — только после v8 (E1 по задачам
   идёт после D1).
5. **Повторяющийся текст «как мы тогда»:** юзер ностальгирует, а RAG нашёл шум → пре-гейт off (по умолчанию), dig
   по контракту канона; лимиты раундов не меняются (модель сама решает, когда тул нужен).
6. **dig с годом, где ничего нет:** «ничего не найдено» — НЕ ошибка (строка, не throw); модель ответит по
   контексту.
7. **Импортированная история (user_id NULL, 2024–2025):** в users_meta НЕ попадает (touch только user_id NOT NULL);
   dig/FTS по ней работает (имена из author_name); ностальгия-кандидаты «год назад» по smart_messages — строки
   импорта с датами (главный источник год-назад-контента); «отвеченность» юзерскими сообщениями не зависит от
   импорта (user_id NOT NULL).
8. **Первый запуск DreamWorker без dream_state:** окно неделя (не вся история импорта) + лимит чатов/тик —
   контролируемый прогрев; первый «сон» после включения флага.
9. **Belief без source_ids / галлюцинация:** не пишется (3.4.6); evidence <2 реальных — отбрасывается; protected-
   гейт на входе кластера.
10. **Бюджеты в нуле/лимите:** дистилляции/токены/сутки достигнуты → тик завершается; деньги не тратятся;
    счётчики по логам (день local).
11. **Ручная стадия + отсутствие юзера:** manual блокирует авто И анти-откат (стадия держится); сброс на авто
    DELETE-эндпоинтом.
12. **Конфликт 409 (два админа правят relations одновременно):** optimistic по updated_at профиля (любое изменение
    профиля бампает метку) → второй получает 409 + current_updated_at → reload.
13. **Dig/BFS-граф пуст (нет nodes/edges у фактов):** фолбэк target_user-выборка; оба пути — best-effort.
14. **Тул-вызов dig с mode=facts на v7-БД без важности:** колонки v8 не нужны (поиск по FTS-тексту графа);
    importance/kind не читаются.
15. **Ностальгия B: чат, где бот единственный писавший** — «тишина» считается по юзерским сообщениям; бот-свои
    строки не в smart_messages; пустая история → skip no_history.
16. **Текст ностальгии > 400 симв. / UNCHANGED / пустой ответ LLM:** cap-обрезка; UNCHANGED → skipped; пусто →
    skipped; лимиты дня не тратятся (только sent).
17. **Отправка ностальгии в чат, где бот удалён:** Bot API ошибка → nostalgia_log error; следующий тик сам
    повторит при условиях; тик жив (WARNING).
18. **dig-инструмент и личный чат (chat_id>0):** работает (память лички) — ограничение «только группы» касается
    инжектов relations-тона и слоёв ностальгии A/B (D-12), НЕ тула.
19. **Канон-правка R9 в проде с кастомом:** кастом юзера не трогаем (ступень миграции); байт-тесты гарантируют
    слепок == R8-канон из git.
20. **Время local vs UTC:** все окна/сутки — timezone `limits.summary_timezone`/settings.SUMMARY_TIMEZONE (существующий
    паттерн планировщиков); ts в SQLite — unix.

---

## 5. Acceptance criteria (сводные; детальные — в задачах G1–G4)

**AC-1 (2a relations):** users_meta создаётся идемпотентно без bump user_version; refresh даёт корректные
first/last_seen, msg-счётчики, active_days, activity_score с полураспадом 14д; стадии по порогам; анти-откат
(60д отсутствия — стадия не падает; активный спад — не чаще 1 ступени/30д, потолок veteran→regular); manual из PG
приоритетнее авто; инжект `<user_relations>` — формат/позиция после Target_User/cap; флаг off ИЛИ per-chat off ИЛИ
нет PG-профиля → блока нет (fail-open); бюджет-урезание не трогает relations (uncuttable); PUT relations → 409 при
рассинхроне, 422 при кривой стадии, NOTIFY/кэш-инвалидация.
**AC-2 (2a dig/канон):** dig в тул-сете (≤6); валидация mode/год; фильтр года и «N лет назад» по timestamp; person
→ расширение именами (алиасы/граф); рендер `[Имя ГГГГ-ММ-ДД]: текст` + `факт …` ≤ лимитов; «ничего не найдено»
при пусто; НЕ бросает; канон R9: ИНСТРУМЕНТЫ п.2 (dig) + ОТНОШЕНИЯ + `<user_relations>` в «как читать»; PREV_R9 ==
R8-канон (HEAD); 4-я ступень миграции работает; пре-гейт: маркер + бедный RAG → dig-результат в контексте (флаг ON);
флаг OFF → 0 изменений поведения.
**AC-3 (2b v8/importance):** PRAGMA=8; данные/id/FTS сохранены после rebuild; origin CHECK включает derived_belief;
важность-бэкфилл в [1..10]; повторный запуск no-op; регресс v2–v7; правило на записи (границы); existing-записи не
ломаются.
**AC-4 (2b сон):** DreamWorker тикает только при флаге; кандидаты по watermark (нет строки — неделя); кластер без
повторяемости/суммы → в дистилляцию не идёт; дистилляция: 0–2 beliefs, JSON-контракт, belief без source_ids НЕ
пишется, supersede по якорному токену, бюджеты (кластеры/дистилляции/токены/сутки — stop), window_skip вне 4–6,
protected-гейт, memory_dream_log-аудит, метка «[убеждение]» только в direct-рендере.
**AC-5 (2c ностальгия):** слой A: маркер только для «золотых» (kind='fact', давность ≥60д, importance ≥5, тема-
матч) и при флаге; максимум 1; контекст не ломается; 0 LLM-вызовов сверх нормы. Слой B: тишина/quiet hours/cooldown/
max_per_day/стоп после 2 неотвеченных + пауза (Q14); aggressiveness меняет порог; кандидат «год назад» по диапазону
timestamp; LLM-UNCHANGED → skipped; отправка через bot (мок); статусы лога sent/skipped/error; только chat_id<0;
PG down → no-op.
**AC-6 (API/TMA):** relations GET/PUT/DELETE — 401 без initData, 403 без прав, 409 optimistic, 503 при PG down,
422 при валидации; dream run — 202/409 already_running, GET beliefs/log, DELETE (мягкий), protect; nostalgia log GET;
TMA: блок «Участники и отношения» в «Лор чатов» (права), мини-блоки в memory_rag под generic-рендером;
REGISTRY-ключи видны в нужных вкладках (TAB_RULES-аудит, дублей групп нет).
**AC-7 (глобально):** полный pytest 4321+ → 0 failed; `git diff --check` чист; секреты не логируются; флаги-дефолты
консервативные (AC-по-умолчанию: прод-поведение без включения не меняется кроме канона R9 и v8); README-раздел +
ARCHITECTURE.md-раздел (H1/H3).

---

## 6. Порядок реализации и тесты

**Порядок Builder'а (единый эпик; порядок задач сохраняется, B4 исполняется ПОСЛЕ C2 — данные раньше рендера,
канон R9 единый):**

1. **B1** (T-816) → **B2** (T-817): users_meta/методы; user_relations.py расчёт/кэш. Минимум-тесты в задачах;
   полные — G1 (tests/test_user_relations.py).
2. **B3** (T-818): PG relations (DDL + store + LoreProfile). Минимум-тесты (tests/test_chat_lore_store.py,
   test_lore_cache.py + новые кейсы relations).
3. **C1** (T-820): dig-тул + ветка роутера (работает на v7). Минимум-тесты (tests/test_tool_schemas.py —
   регистрация/валидация, tests/test_tool_router.py — вызовы/рендер/лимиты/«не бросает»).
4. **C2** (T-821): канон R9 + PREV_R9 + 4-я ступень + байт-тесты (tests/test_direct_chat_prompts.py,
   test_prompt_migrations.py); пре-гейт (test_direct_chat.py — «маркер → dig ДО ответа»).
5. **B4** (T-819): инжект `<user_relations>` (исполняется после C2 — канон уже ссылается на блок). Тесты —
   tests/test_direct_chat_relations_inject.py (по конвенции G1) или в test_direct_chat.py.
6. **D1** (T-822): миграция v8 + memory_dream_log/dream_state + insert_graph_fact-параметры (tests/test_database.py,
   tests/test_history_migration_v8.py или в test_database.py по конвенции: PRAGMA/данные/FTS/no-op/регресс v2–v7).
7. **D2** (T-823): importance-правило (tests/test_graphrag_memory.py/test_database.py — границы/дефолты).
8. **D3** (T-824) → **D4** (T-825): DreamWorker + дистилляция/промпт-канон/запись beliefs/supersede/эмбеддинг/
   рендер-метка (tests/test_dream_worker.py — по конвенции G2; LLM замокан).
9. **E1** (T-826): слой A (fetch_golden_facts + маркер; tests/test_direct_chat.py + test_summary_memory.py —
   «золотые»/флаг/лимит).
10. **E2** (T-827): NostalgiaWorker + промпт-канон + анти-спам (tests/test_nostalgia_worker.py — по конвенции G3;
    LLM/бот замоканы).
11. **F1–F4** (T-828–T-831): relations API (tests/test_chat_lore_api.py — новые кейсы), memory_agi API
    (tests/test_memory_agi_api.py), TMA-блоки (tests/test_webapp_lore_ui.py — блок relations; test_frontend_tab_mapping.py
    при изменении TABS не меняется — новых вкладок нет; memory_rag-мини-блоки — по конвенции фронт-тестов при
    наличии, иначе ручная проверка H3).
12. **G1–G4** (T-832–T-835): сводная матрица 2a/2b/2c → пункт → тест; API-аудит (401/403/404/409/422/503);
    UI-аудит; полный pytest → 0 failed; `git diff --check` чист.
13. **H1–H3** (T-836–T-838): README/ARCHITECTURE.md; деплой (@DevOps: бэкап → миграция v8 → CREATE IF NOT EXISTS →
    PG-DDL → канон R9 → воркеры → live-верификация); отчёт.

**Новые тест-файлы (по конвенции):** tests/test_user_relations.py (G1) · tests/test_dream_worker.py (G2) ·
tests/test_nostalgia_worker.py (G3) · relations-кейсы в tests/test_chat_lore_api.py / test_chat_lore_store.py ·
tests/test_memory_agi_api.py (F2) · миграционные кейсы v8 — в tests/test_database.py (регресс v2–v7 там же).

**Изменяемые файлы (сводно):** services/database.py (users_meta/методы/touch/v8/dream_state/memory_dream_log/
nostalgia_log/insert_graph_fact-параметры/soft_delete/fetch-хелперы для «золотых») · services/user_relations.py (НОВЫЙ)
· services/pg_db.py (2 ALTER) · services/chat_lore_store.py (+relations-методы/list_active_chat_ids) ·
services/lore_cache.py (LoreProfile) · services/lore_runtime.py (db + воркер-геттеры) · services/tool_schemas.py ·
services/tool_router.py (+_dig_into_lore) · services/chat_prompts.py (R9 + PREV_R9) · services/prompt_migrations.py
(4-я ступень) · services/direct_chat_service.py (инжект relations/пре-гейт/слой A) · services/summary_memory.py
(importance-хук? нет — в database; fetch_golden_facts; _ORIGIN_LABELS) · services/dream_worker.py (НОВЫЙ) ·
services/dream_prompts.py (НОВЫЙ) · services/nostalgia_worker.py (НОВЫЙ) · services/nostalgia_prompts.py (НОВЫЙ) ·
web/api/chat_lore.py (relations-роуты + settings-тумблер) · web/api/memory_agi.py (НОВЫЙ) · web/app.py (include) ·
web/app.js / web/index.html (блоки) · services/param_catalog.py / config/settings.py / services/pg_db.py (SEED) ·
bot.py (старт воркеров после lore-блока) · tests/* (выше) · README.md / plans/* (H).

**Изменяемое НЕ входит:** tools/history_import/, manage.py, миграции v2–v7, LEGACY/PREV/PREV_R8-слепки, порядок
роутеров bot.py, файлы local_database_*.db*, PG-структуры вне двух ALTER.
