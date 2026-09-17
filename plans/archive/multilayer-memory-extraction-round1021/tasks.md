# F1 — Многослойная экстракция памяти (Слой А + Слой Б) — раунд 10.21

> **Статус (UPD 10.21 fix-round 3):** 🔵 IMPLEMENTED — @Builder закрыл Issue 1 (персистенция портрета,
> T-2001…T-2004 + T-2012), Issue 7 (descope `DreamWorker`, spec §4.1) и fix-round 2: развязка от
> irony-гейта (T-2013) и учёт legacy-retry в бюджете (T-2012). Передано на пере-ревью (T-2005).
> **Статус (UPD 10.21):** 🟠 REVIEW FIXES — @Reviewer вернул вердикт **Needs fixes** (Issue 1 High, Issue 7 Low);
> @Architect зафиксировал контракт персистенции портрета (spec §3.2.1 / ADR-1021-1 §8); открыты T-2001…T-2005.
> **Статус (исходный):** 🔵 IMPLEMENTED (Step 4 @Builder) — целевые тесты + полный pytest зелёные; передано @Reviewer.
> **Статус (исходный):** 🟡 PLANNED (Step 1 @PM, 18.09.2026). Спека/ADR — Step 2 @Architect (**spec.md НЕ создавать здесь**).
> **Тип:** backend / LLM-пайплайн памяти. **Приоритет:** **P0** (ядро эпика).
> **Нумерация:** **T-1943 … T-1952**.
> **ТЗ:** `plans/current_task.md`, **ЧАСТЬ 1 → Шаг 1 «Многослойная экстракция памяти (Фильтр бреда)»**.
> **Baseline (Step 0 @Memory):** HEAD `21cd54c`; pytest **6574 passed / 0 failed**; SQLite **v12**;
> каталог **439/409/414/92/90/20**; APP_VERSION 2.57.0.
> **R17/R18:** `plans/current_task.md` — untracked, содержит plaintext SSH-креды: **не коммитить, значения не цитировать**.
> **Предшественники (архив):** `plans/archive/round1020-lore-compiler-rag-refactor/` (фазы A–H, T-1866…T-1931),
> `plans/archive/round1020-ui-rework/` (T-1933…T-1942).

## 1. Цель

Устранить **Entity Resolution Failure** и мусор в досье: заменить однопроходную экстракцию воркеров
(`LoreWorker`, `DreamWorker`) на **двухэтапный пайплайн**:

- **Слой А (Scratchpad / Мыслитель):** анализирует сырые чанки и явно рассуждает в `<thought>`-блоках —
  «это копипаста про Тяньаньмэнь или факт о Никите?», «это мем/шутка/цитата — игнорируем».
- **Слой Б (Синтезатор):** получает **только** отфильтрованные выводы Слоя А и формирует досье как
  **психологический портрет и паттерны поведения**, а не вырванные цитаты.

## 2. Решение (Шаг 0) — что уже есть / что новое / факт-ошибки ТЗ

### 2.1 Что уже есть (verify-only — НЕ переоткрывать)
- **`DreamWorker` существует** — `services/dream_worker.py:274` (`class DreamWorker`), фоновый синтез
  убеждений из повторяющихся фактов («сон»); пороги — `config/settings.py:1140-1161` (`DREAM_*`).
- **Канон досье реализован** в `LoreWorker`: `_classify_dossier_safe` (`services/lore_worker.py:483`),
  `_classify_dossier` (`services/lore_worker.py:526`) — LLM-классификация окна в `real_facts`/`chat_memes`,
  запись `chat_memes` как `graph_facts.status='chat_meme'`, идемпотентность `db.meme_exists`.
- **Промпты досье/лора уже есть:** `services/dossier_prompts.py`, `services/lore_prompts.py`,
  `services/dream_prompts.py`.
- **Reasoning-черновик уже парсится с 10.20:** `services/llm_client.py:1012-1020` (алиасы
  `reasoning_content`→`reasoning`→`thinking`), в `content` не подмешивается (`:1014`).
- **Стриппер reasoning-тегов уже есть:** `services/reply_postprocess.py::strip_reasoning_tags`,
  список тегов включает `thought`/`scratchpad`/`analysis`/`thinking` (`reply_postprocess.py:29`).

### 2.2 Что новое (реализовать)
- Двухслойный пайплайн **внутри воркеров памяти** (не в чат-движке): Слой А → промежуточный артефакт → Слой Б.
- Жёсткий **фильтр мусора** на входе досье (мемы, копипасты, шутки, спам, чужие имена).
- **Entity resolution**: различение «упоминание имени» vs «факт о человеке»; защита от коллизий имён
  (Никита/Кирилл — разные люди; шуточные инструкции «Васи» — не факт).
- Контракт досье: только психологический портрет/паттерны, без вырванных цитат.
- **Д3:** портрет обновляет только генерируемые производные; ручные `persona_dossier_overrides` **не перезаписываются**.

### 2.3 ⚠️ Факт-ошибки ТЗ (обязательно отразить в spec/ADR @Architect)
- **Класса `PersonalityExtractor` в коде НЕТ.** Реальная точка — `LoreWorker._classify_dossier`
  (`services/lore_worker.py:526`) и `LoreWorker._classify_dossier_safe` (`:483`). В tasks он не упоминается как существующий.
- **Таблицы `user_dossier` в БД НЕТ.** Досье = `graph_facts` (статусы/типы) + `persona_dossier_overrides`
  (`services/database.py:428`, read/write `:4420-4448`). Миграция «сбросить `user_dossier`» **неприменима**
  (см. F5 — санитария работает по `graph_facts` + `persona_dossier_overrides`).
- **`DreamWorker` — есть** (`services/dream_worker.py:274`), а не «отсутствует».
- Переиспользовать уже существующие `reasoning`-парсинг и `strip_reasoning_tags` — **не дублировать**.

## 3. Задачи

- [x] **T-1943** [@Architect] Research + spec/ADR-1021-1: двухслойная экстракция (Слой А/Б), контракт промежуточного артефакта, фильтр мусора, entity resolution. **Обязателен веб-ресёрч** (self-reflection/self-correction в агентных системах, System 1 vs System 2, Mem0/LangGraph) + `sequentialthinking` (прямое требование ТЗ ЧАСТЬ 1). Учесть факт-ошибки §2.3. *(Выполнено @Architect: `spec.md` + `ADR-1021-1.md` ACCEPTED.)*
- [x] **T-1944** [@Builder] Слой А (Scratchpad/Мыслитель) — worker-side reasoning: генерация `<thought>`-разбора сырых чанков; промежуточный артефакт не попадает в досье/ответы. *(Реализовано: `LAYER_A_SYSTEM_PROMPT` + `parse_layer_a` + `build_layer_a_user` в `services/dossier_prompts.py`; строгий JSON-скретчпад (`reason` = обоснование), артефакт живёт только в `LoreWorker` и не пишется/не инжектится; отдельный стриппер не вводился — R4.)*
- [x] **T-1945** [@Builder] Слой Б (Синтезатор) — потребляет **только** отфильтрованные выводы Слоя А; на выходе — психологический портрет/паттерны, без вырванных цитат. Ручные `persona_dossier_overrides` не перезаписываются (Д3). *(Реализовано: `LAYER_B_SYSTEM_PROMPT` + `parse_layer_b` + `validate_layer_b` + `build_layer_b_user`; вход — только `person_fact`+мемы; портрет in-memory (новый DDL запрещён spec §3.2), Д3 — path не вызывает `set_dossier_override`.)*
- [x] **T-1946** [@Builder] Фильтр мусора: мемы, копипасты, шутки, спам, «чужие» имена → отсев до записи в досье; явная причина пропуска для логов. *(Реализовано: `filter_layer_a_candidates` (kind/evidence/ростер), причины в `dropped` (`no_evidence`/`unknown_entity`/`kind_*`/`empty_meme`); R17-логи только counts/kind.)*
- [x] **T-1947** [@Builder] Entity resolution: различение упоминания имени vs факта о человеке; защита от коллизий (Никита/Кирилл, шуточные «инструкции»). *(Реализовано: `person_fact` валиден только с непустым `evidence` и именем из ростера; `other_person`/вне ростера → отсев; evidence-привязка вместо упоминания.)*
- [x] **T-1948** [@Builder] Промпты Слоя А/Б в `services/dossier_prompts.py` / `services/lore_prompts.py` / `services/dream_prompts.py` + синхронизация канона (`docs/canon/`) и `services/prompt_migrations.py` при необходимости. *(Реализованы модульные канон-константы в `dossier_prompts.py`; `prompt_migrations`/PG-сид не тронуты — прецедент `DOSSIER_SYSTEM_PROMPT`, ADR-1013-3 §2; `lore_prompts`/`dream_prompts`/canon не требуются.)*
- [x] **T-1949** [@Builder] Интеграция в `LoreWorker` (**DreamWorker — вне периметра F1, descope в F4**, см. spec §4.1): пайплайн A→B **включён по умолчанию**; ветвление — только аварийный env-only ClassVar kill-switch (`MULTILAYER_EXTRACTION_ENABLED`, default ON, вне каталога). Сохранить идемпотентность и путь kill-switch OFF. *(Реализовано в `LoreWorker._classify_dossier`: A→фильтр→B по умолчанию; `Settings.MULTILAYER_EXTRACTION_ENABLED` ClassVar (default ON) → путь 10.20 байт-совместим; бюджет A+B через `_budget_ok(..., calls=2)`; `DreamWorker` вне скоупа F1 (F4). Δ каталога = 0.)*
- [x] **T-1950** [@Builder] Тесты: двухслойность, фильтр мусора (кейсы Тяньаньмэнь/«Кирилл»/«Вася»), entity resolution, неприкосновенность overrides, kill-switch OFF → путь 10.20, отсутствие регрессий. *(Реализовано: `tests/test_multilayer_extraction_round1021.py` — 33 теста; путь 10.20 явно зафиксирован kill-switch OFF в `test_dossier_irony.py`; полный pytest 6607/0.)*
- [x] **T-1951** [@Reviewer] Ревью F1 по фактическому поведению пайплайна (не по grep). *(Проведено @Reviewer — Step 5, вердикт **Needs fixes**: Issue 1 (High) — портрет/паттерны/темы вычисляются, но не персистятся и никем не читаются; Issue 7 (Low) — T-1949 упоминал `DreamWorker`, фактически не тронут. Переоткрывается новыми задачами T-2001…T-2005.)*
- [x] **T-1952** [@Builder] Фиксы по ревью. *(Первый прогон: fix round 10.21 — T-2001…T-2004 ниже.)*

## 3.1 Fix-round 10.21 — Issue 1 (High): персистенция портрета (UPD @Architect)

> Спека: spec §3.2 (per-target Слой Б) + **§3.2.1 «Контракт персистенции портрета»**; ADR-1021-1 §8.
> **Инварианты:** без нового DDL (`user_version`=12); `persona_dossier_overrides` неприкосновенны; Δ каталога = 0;
> R17 — без текстов сообщений/портрета в логах.

- [x] **T-2001** [@Builder] **Слой Б per-target:** обновить `LAYER_B_SYSTEM_PROMPT` → выход
  `{"portraits":[{"target","portrait","patterns","themes"}],"memes":[...]}`; `parse_layer_b` читает `portraits`,
  legacy-поля `portrait`/`patterns`/`themes` принимает, но помечает как неперсистируемые; `validate_layer_b`
  применяет анти-цитатный валидатор к каждому `portrait`/`patterns`/`themes` (отклонение → `field`/`reason`,
  R17). `build_layer_b_user` не меняется по формату входа. *(spec §3.2; ADR-1021-1 §8.2.)* *(Реализовано:
  per-target промпт; `parse_layer_b` отдаёт `portraits[]` + `legacy_fields_present`; `validate_layer_b`
  валидирует каждый персональный портрет (`field=portrait[i]`); + `render_generated_portrait`.)*
- [x] **T-2002** [@Builder] **Персистенция без DDL:** `services/database.py` — `get_generated_dossier(chat_id, target_user)`
  (fail-open) и `upsert_generated_dossier(chat_id, target_user, portrait, patterns, themes, now_ts)`
  (строка `graph_facts.status='dossier_portrait'`, `kind='fact'`, `origin='chat_history'`, `weight=0.3`,
  `belief_meta={generated:true,generator:"layer_b",contract_version:1,patterns,themes,updated_at}`;
  идемпотентный SELECT→FTS-safe UPDATE/INSERT). `services/lore_worker.py::_classify_dossier_multilayer` —
  после `validate_layer_b` писать портреты по каждому валидному `target` ростера (fail-open, R17: counts).
  Схема/`user_version` НЕ меняются. *(spec §3.2.1.)* *(Реализовано: `get_generated_dossier`/
  `upsert_generated_dossier`; `LoreWorker._write_generated_portraits` после `validate_layer_b`; DDL/v12 не тронуты.)*
- [x] **T-2003** [@Builder] **Потребители:** `web/api/chat_lore.py::_dossier_payload` — аддитивные
  `portrait`/`patterns`/`themes`/`generated_updated_at`/`portrait_source` (`manual` при непустом `manual_traits`,
  иначе `generated`/`none`; ручная правка приоритетна, сгенерированный портрет не перекрывает её);
  `services/direct_chat_service.py::build_persona_card` — блоки `[Психологический портрет]`/`[Паттерны]`/`[Темы]`
  (fail-open; строки нет → байт-в-байт прежний вывод); `web/index.html` — рендер портрета/паттернов/тем в модалке
  досье с пометкой «сгенерировано автоматически · Слой Б». Досье-контракт аддитивен (R16). *(spec §3.2.1.)*
  *(Реализовано: `_dossier_payload` + `generated_portrait` и `portrait_source`; `build_persona_card` +
  `_format_generated_portrait_block`; модалка досье.)*
- [x] **T-2004** [@Builder] **Тесты F1:** per-target `portraits` парсятся/валидируются; ровно одна строка
  `dossier_portrait` на (chat,target) и идемпотентность повторного прогона (UPDATE, не дубль); `get_generated_dossier`
  возвращает `patterns`/`themes`; verbatim-поле не персистится; `user_version`=12 и `sqlite_master` без новых
  объектов (тест-интроспекция); изоляция от RAG/`get_persona_card`/`list_chat_memes`/`_list_orphan_facts`;
  приоритет `manual_traits` (`portrait_source='manual'`); `set_dossier_override` не вызывается; kill-switch OFF
  байт-совместим. *(spec §8 п.8–11.)* *(Реализовано: `tests/test_multilayer_extraction_round1021.py` —
  классы TestLayerBPerTarget/TestPortraitPersistence/TestPortraitIsolation; +48 тестов в файле.)*
- [x] **T-2012** [@Builder] **Fix-round бюджет:** `_budget_ok(calls=2)` не учитывал retry (до 4 вызовов) и
  fallback-путь 10.20 (3-й вызов). Добирать `consume` на месте по факту (`_budget_extra_calls`) + тест
  фактического числа consume при retry/fallback. *(spec §8.6; T-1950 «Бюджет».)* *(Реализовано:
  `_budget_extra_calls` вызывается на retry Слоя А/Б, перед fallback **и на retry запасного пути 10.20**
  (`_classify_dossier_legacy`); тесты `TestBudgetActualConsume`.)*
- [x] **T-2013** [@Builder] **Fix-round 2 (Low): развязка от irony-гейта.** Двухслойный пайплайн (и
  персистенция портретов/мемов) выполняется **независимо** от `IRONY_FILTER_ENABLED`, управляясь только
  kill-switch `MULTILAYER_EXTRACTION_ENABLED` (default ON). Историческое поведение irony-фильтра не
  меняется: при kill-switch OFF путь 10.20 по-прежнему гейтится `flags.irony_filter_enabled`. *(spec §5.)*
  *(Реализовано: `_classify_dossier_safe`; тесты `test_irony_off_multilayer_on_still_writes` /
  `test_killswitch_off_irony_off_writes_nothing`.)*
- [x] **T-2005** [@Reviewer] **Пере-ревью F1** по фактическому поведению: портрет реально читается потребителями,
  merge/приоритет overrides, изоляция, нулевой DDL, R17. *(Проведено @Reviewer — вердикт Needs fixes
  fix-round 2; закрыто фиксами T-2012/T-2013, передано на повторное ревью. Чекбокс отмечен по контракту
  передачи @Orchestrator.)*

## 4. Риски

- **R1 — двойная стоимость LLM:** двухслойный пайплайн ×2 вызова на чанк; риск роста расходов и латентности воркеров. Митигация: батчинг чанков, лимиты, бюджеты воркеров (`services/worker_budget.py`).
- **R2 — потеря полезных фактов фильтром:** агрессивный отсев мусора может убрать реальные сильные факты. Митигация: логирование причин отсева + метрики + аварийный kill-switch / `git revert`.
- **R3 — пересечение с F2/F3/F5:** общий периметр `services/**` и `*_prompts.py`; канон правится атомарно (ADR-1013-3). Ступени вливания — §6.
- **R4 — уже существующий `strip_reasoning_tags`:** не изобретать второй стриппер; `<thought>` Слоя А — внутренний артефакт.
- **R5 — факт-ошибки ТЗ** (`PersonalityExtractor`, `user_dossier`) приведут к неверному дизайну, если не перепроверить на Step 2.

## 5. Зависимости и ступени вливания

- Зависит от: **F2** (строгий grounding — Слой Б не должен выдумывать), **F3** (negative constraints — стиль портрета).
- Делает возможным: **F5** (rebuild-dossiers использует новый двухэтапный пайплайн).
- Общие файлы: `services/lore_worker.py`, `services/dream_worker.py`, `*_prompts.py` — **сводить атомарно** после F2/F3 (порядок в backlog).

## 6. Активация и kill-switch (UPD Human Gate — решение зафиксировано)

- **Флага нет; включено по умолчанию** и работает безусловно. Раскатки 10/50/100% **нет**.
- Аварийный **env-only ClassVar** kill-switch `MULTILAYER_EXTRACTION_ENABLED` (default **ON**, вне каталога,
  прецедент retention-гейтов) → **Δ каталога = 0** по всем осям.
- Откат: аварийно kill-switch; штатно — `git revert` (схема БД v12 не меняется).
