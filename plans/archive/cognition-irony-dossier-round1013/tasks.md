# Фича F8 — `cognition-irony-dossier-round1013` («Ирония и Досье Персонажей»)

> **Статус: ✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; реализовано Step 4 @Builder, 13.09.2026). Спека: `spec.md`. Код реализован, полный pytest 0 failed.
> **Раунд:** 10.13. **Нумерация:** T-1468…T-1476 (продолжает F7 T-1467).
> **Тип:** backend (промпт-канон + сборка/хранение досье в контексте). **Приоритет:** P1.
> **Зависимости:** F1 (`cognition-4d-memory-round1013`) — инфраструктура правки канона промптов
> (`PREV`-слепок + `prompt_migrations` + байт-тесты) и временные метки фактов; **F2/F3 желательны**
> (общие промпты лора/памяти), но не блокируют.
> **Может идти параллельно** F4 (`cognition-llm-providers-round1013`) и F6
> (`cognition-ekg-logs-bugfix-round1013`) — затрагивает другие модули (персоны/досье/контекст), не UI-страницу
> «Статус».
> **ТЗ:** `plans/current_task.md`, раздел **2** («Ирония и Досье Персонажей»).
> **Эпик:** `Epic: Cognition-Sleep-Memory Refactor round1013`.

## 0. Цель

LLM перестаёт воспринимать локальные мемы и постиронию как реальные факты биографии людей.
Воркер, собирающий Досье персонажей, получает «Иронический фильтр» в системный промпт и раскладывает
добычу по двум корзинам: **`real_facts`** (реальные факты) и **`chat_memes`** (оскорбительные/абсурдные
титулы и локальные мемы). В контекст досье подаётся двумя раздельными блоками: **[Факты]** и
**[Локальные мемы/Ярлыки]**, поэтому бот не пишет лор чата «как было» по шуткам.

## 1. Требования (дословно из ТЗ §2)

- [x] Внедрить **«Иронический фильтр»** в системный промпт воркера, собирающего **Досье** персонажей.
- [x] Явная инструкция в промпт: **«Пользователи часто шутят и используют сарказм. Оскорбительные или
      абсурдные титулы (например, 'мегачмо', 'повелитель грибов') записывать в отдельный массив
      `chat_memes`, а не в `real_facts`»**.
- [x] Разделять досье в контексте на два блока: **[Факты]** и **[Локальные мемы/Ярлыки]**.

> **Рекогносцировка-предупреждение (@PM, HEAD `ce25dc7`):** сущности `real_facts`/`chat_memes`/`dossier`
> в коде **ОТСУТСТВУЮТ** (greenfield, подтверждено grep). Есть фундамент: карточка человека
> (`get_persona_card`/`build_persona_card`), per-user факты (`graph_facts.target_user`,
> `protected_facts`), JSONB `chat_profiles.relations`, воркер и канон авто-лора (`lore_worker`/
> `lore_prompts`), RAG-контекст (`summary_memory`). **Какую именно сущность делает «воркер, собирающий
> Досье» — фиксирует @Architect (T-1468), код @PM не пишет.**

## 2. Целевые модули (`file:line` на HEAD `ce25dc7`)

- `services/lore_prompts.py` — канон `LORE_MERGE_SYSTEM_PROMPT` `:16`, `LORE_INIT_SYSTEM_PROMPT` `:39`
  (сюда/в новый `dossier_prompts.py` — «Иронический фильтр»); `format_lore_block()` `:99`,
  `format_merge_user_content()` `:150`, `format_init_user_content()` `:164`, `build_merge_user()` `:176`,
  `build_init_user()` `:197` (user-контент воркера).
- `services/lore_worker.py` — `LoreWorker` `:172`, `_run_generation()` `:408`, `_chat_facts()` `:508`
  (точка вызова LLM воркера лора/досье).
- `services/lore_cache.py` — `LoreProfile` `:35` (поле `relations` `:52`), `get()` `:87`,
  `invalidate()` `:147` (кэш профиля; запись `chat_memes` обязана инвалидировать).
- `services/chat_lore_store.py` — `get_relations()` `:577`, `get_relation_manual()` `:588`,
  `put_relation()` `:598`, `_update_relations()` `:676` (существующая **JSONB-структура досье**
  `chat_profiles.relations` — кандидат под `chat_memes` **без новой PG-DDL**).
- `services/database.py` — `get_persona_card()` `:3118`, `get_persona_names()` `:3147`,
  `get_protected_facts()` `:2623`; схема `protected_facts` `:564`, поля `graph_facts`
  (`target_user`/`origin`/`belief_meta`/`kind`) — кандидат под маркер мема без миграции схемы.
- `services/direct_chat_service.py` — `build_persona_card()` `:1443`, `_build_user_relations()` `:824`,
  инжект protected-фактов `:1248` (сборка контекста карточки человека).
- `services/summary_memory.py` — `build_rag_context()` `:693`, `get_rag_context()` `:1958`,
  канон-агрегация персон `:809, 1682-1683, 2583` (сборка блока досье в контекст).
- `services/prompt_migrations.py` — `PROMPT_MIGRATIONS` `:63` (новая ступень `PREV → новый канон`).
- `services/param_catalog.py` — группы `flags_relations` `:297`/`limits_relations` `:247`
  (флаг инициативы и лимиты; только санкционированный Δ).
- `config/settings.py` — дефолты новых флагов/лимитов (если решено выносить).
- Тесты: `tests/test_chat_lore*.py`, `tests/test_direct_chat*.py`, `tests/test_database.py`,
  `tests/test_param_catalog*` (Δ), `tests/test_webapp_round1013_ui.py` (если затронут UI).

## 3. Инварианты (constraints — не нарушать)

- **Ноль новых PG-DDL.** `chat_memes` хранить **только** в существующей JSON-структуре досье
  (`chat_profiles.relations` JSONB) **либо** в существующем SQLite-поле/маркере
  (`graph_facts.belief_meta`/`kind`), **без миграции схемы**. Конкретное место — решение @Architect
  (T-1468); SQLite остаётся **v8**.
- **Правка канона промптов — только** через `PREV`-слепок + `services/prompt_migrations.py`
  (`PROMPT_MIGRATIONS`) + байт-тесты (как в F1). Кастом юзера не перезаписывать.
- **Порядок роутеров `bot.py` не трогать** (искл.: DI-kwargs новых hot-значений).
- **R17:** секреты — только `{configured, last4}`; ничего не логировать (досье — персональные данные,
  в логи не тащить).
- **R16:** id — ключ, не имя; имя берётся из существующих полей (`target_user`/`author_name`), не выдумывается.
- **Каталог-инварианты: REGISTRY 405 / GROUPS 90 / Settings 377 / mapped 88 / `TAB_RULES` 19.** Новые
  ключи/группы — только санкционированным Δ с осознанным обновлением пин-тестов.
- **CAP контекста:** блоки `[Факты]`/`[Локальные мемы/Ярлыки]` учитывают существующий бюджет
  (`_apply_context_budget`); обратная совместимость: старое досье без `chat_memes` → только `[Факты]`.
- **Feature flag:** `flags.irony_filter_enabled` (default OFF); при OFF — поведение 10.12 без изменений.
- **Коммиты:** русские conventional commits, атомарно (код + PREV-слепок + тесты).

## 4. Зависимости

- **Вверх:** F1 (инфраструктура PREV-слепков/`prompt_migrations`/байт-тестов и метки фактов); F2/F3 —
  желательны (общие промпты лора/памяти, чтобы не плодить конфликтующие ступени миграций).
- **Вниз:** нет прямой блокировки. F5 (дашборд) при желании может показать счётчики мемов — вне скоупа F8.
- **Параллелизм:** F8 затрагивает персон/досье/контекст (не UI «Статус») → может идти параллельно **F4 и F6**.
  Единственная общая точка — `services/prompt_migrations.py` (аддитивная ступень); при параллельности
  координировать порядок вливания с F1/F2/F3.

## 5. Definition of Done

- [x] Системный промпт досье содержит «Иронический фильтр» и явную инструкцию про `chat_memes` vs
      `real_facts` (дословная формулировка ТЗ сохранена).
- [x] Абсурдные/оскорбительные титулы (`мегачмо`, `повелитель грибов`, …) не попадают в `real_facts`,
      а складываются в `chat_memes`; реальные сведения — в `real_facts`.
- [x] Досье в контексте подаётся двумя блоками: `[Факты]` и `[Локальные мемы/Ярлыки]`; пустой блок не рендерится.
- [x] Хранение — без новых PG-DDL, в существующей JSON/SQLite-структуре; запись инвалидирует кэш `lore_cache`.
- [x] Метрики/API досье (если есть) отдают разделённые `real_facts`/`chat_memes`; R17 соблюдён.
- [x] Полный `pytest` — **0 failed** (база 5211); `git diff --check` чист; инварианты каталога сверены.
- [x] Флаг `flags.irony_filter_enabled` (default OFF) + staged rollout (§8).

## 6. Чек-лист задач

- [x] **T-1468 (@Architect, гейт):** spec/ADR: что такое «Досье персонажей» в коде и какой воркер его собирает
  (существующий `LoreWorker` vs новый persona-воркер); где хранится `chat_memes` (JSONB
  `chat_profiles.relations` vs `graph_facts.belief_meta`/`kind`) **без PG-DDL**; имена PG-ключей
  (`prompts.*_system_prompt`), ступень `PROMPT_MIGRATIONS`; формат блоков `[Факты]`/`[Локальные мемы/Ярлыки]`
  и бюджет; флаг `flags.irony_filter_enabled`; санкционированный Δ каталога (если есть).
- [x] **T-1469 (@Builder):** «Иронический фильтр» в каноне системного промпта досье (в `lore_prompts.py`
  или новом `dossier_prompts.py`): явная инструкция про `chat_memes` vs `real_facts` дословно из ТЗ §2;
  `PREV_*`-слепок + ступень в `PROMPT_MIGRATIONS` + байт-тесты.
- [x] **T-1470 (@Builder):** запись `chat_memes` в выбранную существующую структуру (JSONB `relations`
  через `chat_lore_store.put_relation/_update_relations` или поле `graph_facts`); Python-merge,
  optimistic-метка, NOTIFY, инвалидация `lore_cache`; **без DDL**.
- [x] **T-1471 (@Builder):** чтение/разделение: `get_persona_card`/`build_persona_card`/`get_protected_facts`
  отдают/фильтруют `real_facts` отдельно от `chat_memes`; мемы не попадают в «реальные» факты RAG.
- [x] **T-1472 (@Builder):** сборка контекста досье (`direct_chat_service` + `summary_memory` +
  `format_lore_block`) — два блока `[Факты]` и `[Локальные мемы/Ярлыки]`; CAP/uncuttable-семантика;
  обратная совместимость (нет `chat_memes` → один блок `[Факты]`).
- [x] **T-1473 (@Builder):** `lore_worker._run_generation`/`build_*_user`: передать «иронический» контекст
  воркеру досье так, чтобы абсурдные титулы классифицировались в `chat_memes` (не в лор как биография).
- [x] **T-1474 (@Builder):** тесты: классификация (мемы vs факты, включая `мегачмо`/`повелитель грибов`);
  два блока и их обрезка по бюджету; обратная совместимость старого досье; инвалидация кэша;
  байт-канон промпта + ступень миграции; регресс `test_chat_lore*`/`test_direct_chat*`/`test_database`.
- [x] **T-1475 (@Builder):** полный `pytest` (0 failed, дельта), `node --check web/app.js` (если UI),
  `git diff --check` clean; независимый пересчёт инвариантов каталога (Δ, если был).
- [x] **T-1476 (@Builder):** флаг `flags.irony_filter_enabled` (default OFF) + staged rollout (§8);
  документировать в spec/ADR.

## 7. Открытые вопросы (@Architect → владелец)

- **F8-Q1:** существует ли отдельный «воркер, собирающий Досье», или его роль исполняет `LoreWorker`/
  `build_persona_card`? Нужен ли новый воркер?
- **F8-Q2:** где хранить `chat_memes` — JSONB `chat_profiles.relations` (per-user) или
  `graph_facts.belief_meta`? Что выбрано, чтобы гарантировать ноль PG-DDL?
- **F8-Q3:** `real_facts` — это `graph_facts.target_user` (weight/status) или отдельный массив в JSONB?
- **F8-Q4:** точный формат заголовков блоков контекста (`[Факты]`/`[Локальные мемы/Ярлыки]`) и их бюджет;
  как соотносится с существующими `<Protected_Facts>`/`<user_relations>`?
- **F8-Q5:** нужен ли ручной просмотр/редактирование мемов в TMA (или только авто-сбор), и входят ли
  мемы в персона-карточку по `/persona`?
- **F8-Q6:** считать ли титул мемом по списку ключевых слов, по LLM-классификации или по обоим?

## 8. Feature flag / progressive delivery

- **Feature flag:** `flags.irony_filter_enabled` (default **OFF**); при OFF — контекст/промпт досье как в 10.12.
- **Rollout stages:** внутренний прогон на тестовом чате → `internal` → **10%** чатов (staged `--chat-id`) →
  **50%** → **100%**; критерии отката: мемы просачиваются в `real_facts`/RAG, рост жалоб на «биографию по
  шуткам», деградация персона-карточек.
- **Rollback:** флаг OFF (мгновенно) + `git revert`; данные `chat_memes` остаются в существующей структуре,
  миграций не требуется.
