# AdminBot — Kanban Board

## 📋 Backlog

### Epic 26: GraphRAG-память — граф знаний поверх SQLite (v2.24.0) — 2026-08-16 — 🆕 IN PROGRESS (реализация ✅, преддеплойный P1-фикс T-206)

> **Шаг воркфлоу:** 1/3 (PM) ✅ → 2 (@Architect T-199/T26.0 — Section 35 + дословный EXTRACT_PROMPT) ✅ APPROVED PM → 3 (@Builder/@Reviewer/@DevOps): T-200…T-204 ✅ (реализовано + ревью), T-206 (P1-фикс) → In Progress, T-205 (деплой) — ПОСЛЕ T-206.
> Требования R26-1…R26-7, PM-решения D67–D71 (chat_id в nodes/edges + UNIQUE(chat_id, entity_name); per-batch изоляция «граф до удаления сырья»; минимальный набор настроек; нормализация сущностей/отношений; graph_facts=[] default + escape + тег первым) и риски 1–10 — в `plans/backlog.md` (Epic 26).
> 🚨 **P1 (найдено @Reviewer при ревью T-204, pre-existing с Epic 24 `a68732c`):** медиа-без-подписи нет в `smart_messages_fts` (`if text:` при вставке), но FTS-удаление безусловно → `sqlite3.DatabaseError: database disk image is malformed` в `compress_and_purge`. Фикс — **T-206 (T26.7), чинить ДО деплоя T-205.**

- [x] T-199 (T26.0) (@Architect + @PM, P0, —): Проектирование GraphRAG — ARCHITECTURE.md Section 35 (DDL nodes/edges, flow extract→graph→delete в _compress_batch, traversal в SummaryGenerator._run), ДОСЛОВНЫЙ EXTRACT_PROMPT, self-review — **✅ APPROVED PM 2026-08-16 (T26.0-D)**
- [x] T-200 (T26.1) (@Builder, P0, ←T-199): Миграция схемы — nodes/edges + chat_id + UNIQUE(chat_id, entity_name) + индексы + upsert CRUD (INSERT OR IGNORE / ON CONFLICT weight+1) — **Done**
- [x] T-201 (T26.2) (@Builder, P0, ←T-200): Entity extraction в архивации — EXTRACT_PROMPT (verbatim), JSON try/except, граф ДО удаления сырья, per-batch isolation (ошибка → пачка остаётся), graceful degradation — **Done**
- [x] T-202 (T26.3) (@Builder, P0, ←T-200): Graph traversal для /summary — сущности окна L1, SQL weight DESC LIMIT 5, справки «[Историческая справка: …]», тег `<historical_graph_facts>` первым в user-промпте, escape_xml_text, fallback без секции — **Done**
- [x] T-203 (T26.4) (@Builder, P1, ←T-199): Конфигурация — GRAPH_RAG_ENABLED / GRAPH_EDGE_WEIGHT_INCREMENT / GRAPH_TOP_EDGES_LIMIT / GRAPH_EXTRACT_MAX_TRIPLETS + .env.example — **Done**
- [x] T-204 (T26.5) (@Builder + @Reviewer, P0, ←T-201/T-202): Тесты — парсер JSON, upsert, traversal, чат-изоляция, кривой JSON → пачка остаётся, пустой граф, дубликаты сущностей, pipeline с graph_facts; полный pytest (860 + новые); @Reviewer code review — **Done; ревью APPROVED, найдена P1 → T-206**
- [ ] T-206 (T26.7) (@Builder + @Reviewer, **P1, 🚨 БЛОКЕР T-205**): P1-фикс FTS-удаления для медиа без подписи — `delete_smart_messages_by_ids` / `delete_smart_messages_older_than` удаляют из FTS безусловно, но вставка была под `if text:` → `sqlite3.DatabaseError: database disk image is malformed` в `compress_and_purge` (вызов вне try/except). Минимальный фикс: зеркалить условие вставки в обеих DELETE + регрессионные тесты (медиа без подписи → delete не падает; обычный текст → delete работает; FTS-консистентность) — **→ In Progress (срочно)**
- [ ] T-205 (T26.6) (@Builder + @DevOps, P0, ←T-204, ⛔ ←T-206): README (ироничный тон) + коммит на русском + push + деплой (ssh nik@198.46.175.136, git pull, systemctl restart/status admin_bot) — **деплой только после фикса T-206**

## 🔧 In Progress

- 🚧 T-206 (T26.7) (@Builder, P1 — 🚨 БЛОКЕР деплоя T-205) — Epic 26: фикс FTS-удаления для медиа без подписи (`delete_smart_messages_by_ids` / `delete_smart_messages_older_than`, services/database.py). Pre-existing с Epic 24 (`a68732c`), подтверждён @Reviewer при ревью T-204. Минимальный фикс: зеркалировать `if text:` в обеих DELETE; регрессионные тесты: медиа без подписи → delete не падает; обычный текст → delete работает; FTS-консистентность. Чинить до T-205.

## 🔍 In Review

*No items in review.*

## ✅ Done

### Epic 26: T-199…T-204 — дизайн + реализация GraphRAG — ✅ (PM 2026-08-16; преддеплойный P1-фикс → T-206)

> **Итог:** T-199 (T26.0) — дизайн `plans/ARCHITECTURE.md` Section 35 (35.1–35.11) **APPROVED PM 2026-08-16 (T26.0-D)**.
> T-200…T-204 (T26.1…T26.5) — **реализовано @Builder и прошло ревью @Reviewer (T26.5-G APPROVED)**:
> DDL nodes/edges (chat_id + UNIQUE), extraction в compress_and_purge (D68 per-batch isolation),
> traversal get_graph_facts (тег `<historical_graph_facts>` первым, escape), настройки GRAPH_* (D69),
> тесты test_graphrag_database/test_graphrag_memory + полный pytest.
> ⚠️ @Reviewer подтвердил **P1 pre-existing баг** (Epic 24, `a68732c`): медиа-без-подписи нет в FTS, но FTS-удаление безусловно → malformed DB в compress_and_purge. Выделен **T-206 (T26.7)** — чинить ДО деплоя T-205 (коммита Epic 26 ещё нет — код в рабочем дереве).

- [x] 👤 T-199 (T26.0) (@Architect + @PM, P0) — Архитектурное проектирование GraphRAG + фиксация промпта
  - [x] T26.0-A: Section 35 (35.1–35.11): DDL nodes/edges, flow extract→graph→delete, traversal, открытые вопросы 1–10
  - [x] T26.0-B: EXTRACT_PROMPT зафиксирован дословно (35.3 + services/summary_prompts.py)
  - [x] T26.0-C: Self-review — изоляция от 860 тестов, graceful degradation, LLM-нагрузка
  - [x] T26.0-D: **APPROVED PM 2026-08-16** — R26-1…R26-7 покрыты, риски 1–10 закрыты (35.9); T26.1…T26.4 → READY FOR BUILDER
- [x] T-200 (T26.1) (@Builder, P0) — Миграция схемы: nodes/edges + chat_id + UNIQUE + индексы + upsert CRUD (R26-1, D67) — Done
- [x] T-201 (T26.2) (@Builder, P0) — Entity Extraction в архивации: EXTRACT_PROMPT (verbatim), JSON try/except, граф ДО удаления сырья, per-batch isolation (R26-2, D68) — Done
- [x] T-202 (T26.3) (@Builder, P0) — Graph traversal для /summary: сущности L1, SQL weight DESC LIMIT 5, справки «[Историческая справка: …]», `<historical_graph_facts>` первым, escape_xml_text, fallback (R26-3, D71) — Done
- [x] T-203 (T26.4) (@Builder, P1) — Конфигурация GRAPH_* (4 параметра) + .env.example (R26-6, D69) — Done
- [x] T-204 (T26.5) (@Builder + @Reviewer, P0) — Тесты (парсер JSON, upsert, traversal, чат-изоляция, кривой JSON → пачка остаётся, pipeline с graph_facts) + полный pytest — Done; @Reviewer (T26.5-G) **APPROVED 2026-08-16** — с находкой P1 → T-206

### Epic 24: T-173 — Архитектурное проектирование SmartModule/Summary — 2026-08-16 — ✅ APPROVED (PM, T-173-E)

> **Итог:** дизайн `plans/ARCHITECTURE.md` Section 33 (33.1–33.15, решения A1–A15) APPROVED.
> R1–R18 покрыты полностью; риски 1–12 backlog + Н1–Н4 закрыты решениями (33.14).
> Минорные замечания для @Builder (не блокируют): (1) в 33.8 сказано «+18 полей» — в блоке 24 поля, поправить число в комментарии; (2) `_ensure_shiz_postfix` проверяет только наличие приписки «самым главным шизом объявляется», но не убирает `@`, если LLM сам написал её с @ — добавить стрип `@` в финальном имени; (3) число новых тестов в 33.13 (~120) уточнить по факту в T-188-C.
> T-174 → READY FOR BUILDER. Передача @Builder.

- [x] 👤 T-173 (@Architect + @PM, P0) — Epic 24: Архитектурное проектирование SmartModule/Summary (2026-08-16)
  - [x] T-173-A: Модули, data flow, схема БД, контракты — `plans/ARCHITECTURE.md` **Section 33** (33.1–33.15)
  - [x] T-173-B: Позиции роутеров — `summary_observer_router` 0a + `summary_router` 0b (ДО catch-all 5/6); сбор всех сообщений — отдельный роутер с UNHANDLED
  - [x] T-173-C: Общая `local_database.db`; сжатие L3 — шаг пайплайна под общим `asyncio.Lock` (без отдельной джобы)
  - [x] T-173-D: Self-review — изоляция от 12 роутеров, фоллбек-пути FTS5, таймауты LLM, секция 33.14
  - [x] T-173-F: RESEARCH.md верифицирован (context7 — API-key недоступен; duckduckgo — anomaly; рабочий стек: exa + webfetch docs.aiogram.dev; секция «Методология» + источники с датами)
  - [x] T-173-E: **APPROVED PM 2026-08-16** — R1–R18 ✅, риски закрыты, конвенции соблюдены (settings.py хелперы, bot.py on_startup-wiring, _SCHEMA_SQL-миграции, инъекции setup_*, MessageCounterMiddleware router-scoped не задет)

### Epic 25: T-192/T-193 — RCA + дизайн фикса /summary — 2026-08-16 — ✅ APPROVED (PM)

> **Итог:** RCA T-192 (первопричина: асимметрия троттлинг-мидлвари с Command-фильтром — чужая mention `/summary@RofloslavBot` сожгла слот, повтор молча сглочен) + дизайн T-193 (`plans/ARCHITECTURE.md` Section 34, 34.1–34.10, решения B1–B9) APPROVED.
> R25-1…R25-4 покрыты; исходное ТЗ R7 (ALLOWED пуст=всем, запрет без реакции — denied не удаляем/не отвечаем) и R8 (молчаливый троттлинг — B3 сохраняет) не нарушены.
> Замечания для @Builder (не блокируют): (1) B6 — `_safe_send` должен использовать инжектированный `bot` (в `setup_summary` или параметром хендлера), иначе при `_generator is None` UX не доставляется (сейчас `_generator.bot` → AttributeError → лог вместо сообщения); (2) B3 — сохранить guard `if text.strip()` текущего кода и использовать точное сравнение `base == "/summary"` (startswith ловит `/summaryfoo` — тот же класс асимметрии, что и первопричина); (3) backlog синхронизирован: H-C остаётся молчаливой (R8) — UX только для H-B/H-F.
> T-194/T-195 → READY FOR BUILDER. Передача @Builder.

- [x] 👤 T-192 (@Architect + @DevOps, P0) — Epic 25: RCA бага «/summary не реагирует» (2026-08-16)
  - [x] T-192-A: прод-логи journalctl/smart_messages за момент теста + прод .env
  - [x] T-192-B: Н1 (BotFather setprivacy), админ-права delete_messages, следы cron
  - [x] T-192-C: сопоставление с H-A…H-F — H-C ✅ подтверждена (триггер), асимметрия middleware/Command ✅ (первопричина)
  - [x] T-192-D: отчёт причин — ARCHITECTURE.md Section 34.2 + сводка board.md
- [x] 👤 T-193 (@Architect + @PM, P0) — Epic 25: Дизайн фикса (2026-08-16)
  - [x] T-193-A: Section 34 (34.1–34.10): ack (D66), best-effort удаление (D65), B1–B9, тест-план 34.8, риски 34.9
  - [x] T-193-B: **APPROVED PM 2026-08-16** — B1–B9 сверены с R25-1…R25-4 и исходным ТЗ R7/R8; 2 замечания Builder (B6 bot-инжекция, B3 strip-guard/точное сравнение); backlog синхронизирован (H-C молчалива)

### Epic 24: T-174…T-191 — реализация и деплой SmartModule — ✅ DEPLOYED (v2.22.0, коммит `a68732c`)

> Перенесено из колонки Backlog при архивации (PM, 2026-08-16). Полный трек — `plans/backlog.md` (Epic 24).
> ⚠️ Н1 BotFather `/setprivacy` → Disable — ручное действие пользователя.

- [x] T-174..T-189 (@Builder): конфиг (24 поля), БД smart_messages+CRUD, память L1/L2/L3 (sqlite-vec + FTS5-фоллбек), LLM-клиент (httpx, retry 429/5xx), XML-контекст, алиасы, системный промпт (verbatim), APScheduler 00/06/12/18 Asia/Yekaterinburg, /summary, троттлинг, чанкинг, observability — Done (157 новых тестов)
- [x] T-188-D (@Reviewer): code review SmartModule — APPROVED 2026-08-16 (830 passed после 2 точечных фиксов)
- [x] T-189 (@Builder): README (ироничный тон) + ARCHITECTURE 33.16 + MEMORY, v2.22.0 — Done (итог 835 passed)
- [x] T-190 (@Builder + @DevOps): коммит `a68732c` (35 файлов, на русском, conventional) + push origin/master — Done (.env не коммичен)
- [x] T-191 (@DevOps): деплой — git pull, .env +LLM_*, venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1, restart → active (running) PID 920105, smoke apinet.cloud OK — Done

### Epic 25: T-194…T-198 — фикс /summary — ✅ DEPLOYED (v2.23.0-fix, коммит `c364f18`)

> Перенесено из колонки Backlog при архивации (PM, 2026-08-16). Полный трек — `plans/backlog.md` (Epic 25).

- [x] T-194 (@Builder): реализация B1–B9 (ack «ща гляну, подожди», UX-ветки, delete best-effort, логирование этапов) — Done
- [x] T-195 (@Builder): +25 тестов (860 total), полный прогон зелёный, 0 регрессий — Done
- [x] T-196 (@Reviewer): APPROVED 2026-08-16 (личный прогон 860 passed; 4 Low-замечания не блокируют — на будущий эпик)
- [x] T-197 (@DevOps): коммит `c364f18` (11 файлов, +1001/−84) + push origin/master — Done (860 passed перед коммитом, .env не тронут)
- [x] T-198 (@DevOps): деплой fast-forward `a68732c..c364f18`, restart → active (running) PID 923954, старт чистый — Done. ⚠️ Pre-existing: L3 dimension mismatch (768 vs 3072) → FTS5-фоллбек; stop-timeout systemd при рестарте. Живой тест /summary — после теста пользователем

### Epic 23: Точная настройка danger-словаря (v2.21.0) — 2026-08-16 — ✅ DEPLOYED (коммит `756d237`)

> **Цель:** Убрать ложноположительные секции danger-словаря (Flight/arrival, Падение/сбитие),
> перевести Shelter и Атаку/угрозу на фразы-связки, добавить «хлопок»-синонимы, ввести
> механику DANGER_PHRASES.
> **PM-решения:** D55 (DANGER_PHRASES + ветка фраз в DangerWordFilter, regex по краям фразы
> IGNORECASE, возврат {"matched_word"} совместимый; env-оверрайд фраз НЕ вводим),
> D56 (Shelter: −26 одиночных форм, +10 фраз), D57 (вспышка*/взрыв* остаются,
> +хлопок/хлопки/хлопнуло/хлопнул, омоним-риск принят), D58 (Атака: −28 одиночных форм, +7 фраз).
> Target: v2.21.0. Prod .env НЕ меняли (DANGER_WORDS пустой → дефолты из word_lists.py).
> **Итог:** DONE & DEPLOYED ✅ — T-169..T-172 (включая деплойные подзадачи E..G) закрыты,
> 672 теста PASS (621+51). Коммит `756d237` (feat(danger)) на master, пуш в origin.
> Деплой: git pull 0c74220..756d237 (9 файлов) на 198.46.175.136:/var/www/admin_bot,
> systemctl restart OK — active (running) PID 917681, логи чистые. .env DANGER_WORDS пустой →
> дефолты (118 слов + 17 фраз), проверка «118 17» совпала. Прод v2.21.0.

- [x] T-169 (@Builder): Словарь — Flight удалить, Падение удалить, Shelter→10 фраз (DANGER_PHRASES), Flash + «хлопок» (D56, D57)
- [x] T-170 (@Builder): Атака/угроза → 7 фраз (D58)
- [x] T-171 (@Builder): Механика DANGER_PHRASES в DangerWordFilter + тесты (обновить сломанные, новые на фразы/негатив)
- [x] T-172 (@Builder + @DevOps): Доки DONE ✅ (README «187 словоформ» → 118 + 17 фраз, v2.21.0/672, ARCHITECTURE, MEMORY) + коммит DONE ✅ (`756d237` feat(danger) на master) + деплой DONE ✅ (E..G: pull 0c74220..756d237, 9 файлов; .env DANGER_WORDS пустой → дефолты; «118 17» совпала; PID 917681; логи чистые)

### Chore (2026-08-16): danger_drone.mp4 в danger-пул — ✅ DEPLOYED (коммит `0c74220`)

> **Итог:** T-168 DONE & DEPLOYED. Все подзадачи A..E закрыты. Деплой: git pull на сервере
> fast-forward 1dbb6da..0c74220 (5 файлов), danger_drone.mp4 на месте (права 644, хэш 918c9be9...
> совпал), danger-пул = 16 файлов. systemctl restart OK — active (running), PID 916795, логи чистые.

- [x] T-168 (@Builder): Медиа: danger_drone.mp4 в danger-пул (коммит + деплой)
  - [x] T-168-A: Verify — файл существует локально (16-й файл пула), не в .gitignore ✓
  - [x] T-168-B: Коммит `0c74220` (chore(media): danger_drone.mp4 в danger-пул) + push в origin ✓
  - [x] T-168-C: Деплой — SSH git pull на 198.46.175.136:/var/www/admin_bot (fast-forward 1dbb6da..0c74220) ✓
  - [x] T-168-D: Verify на сервере — danger_drone.mp4 присутствует, chmod 644, хэш совпал, пул = 16 файлов ✓
  - [x] T-168-E: Smoke test — danger-слово → ответ из danger-пула; danger_drone.mp4 распознаётся как video ✓
  - ⚠️ Политика media/ соблюдена: файл закоммичен, НЕ в .gitignore, НЕ удалён.

### Epic 22: Гонка функций и точность триггеров (Olya/Mimic/Slavik/PostPicker) — 2026-08-15 ✅ DEPLOYED (v2.20.0, коммит `1dbb6da`)

> **Цель:** Устранить гонку ответов у Славика (приветствие vs dead page vs «пошёл нахуй»),
> сделать триггеры точнее: Olya — только SaveAsBot-видео, mimic — не передразнивать репосты,
> PostPicker — не выбирать пост, отправленный в предыдущий раз.
> **PM-решения:** D51 (Olya: ИЛИ + OLYA_ALWAYS_SEND=False), D52 (MIMIC_FORWARDS_ENABLED=False),
> D53 (DEAD_PAGE_POST_ON_JOIN=False, dead page только на репосты Славы из @d_pages, catchall-гейт),
> D54 (channel_state `dead_page_last_sent:{chat_id}`). Target: v2.20.0.
> **Итог:** реализовано и задеплоено. 621 тест PASS (586 baseline + 35 новых), 0 регрессий.
> Коммит `1dbb6da` на master, пуш в origin. Деплой: 198.46.175.136:/var/www/admin_bot,
> git pull c683903..1dbb6da (21 файл, +1778/-224), prod .env DEAD_PAGE_POST_ON_JOIN=True→False
> (бэкап .env.bak.2026-08-15), systemctl restart OK, active (running), PID 914116. Прод v2.20.0.

- [x] T-163 (@Builder): Olya — реагировать только на SaveAsBot-видео (D51)
  - [x] T-163-A: OLYA_ALWAYS_SEND default → False (settings.py + .env.example)
  - [x] T-163-B: Сохранить ИЛИ: caption-признак ИЛИ репост из OLYA_SAVEASBOT_CHANNEL_IDS
  - [x] T-163-C: AC: обычное видео → False; репост SaveAsBot → True; caption → True; ALWAYS_SEND=True → True
  - [x] T-163-D: Тесты (≈5) + README/.env.example
- [x] T-164 (@Builder): Mimic — не передразнивать репосты (D52)
  - [x] T-164-A: MIMIC_FORWARDS_ENABLED: bool = False (settings.py + .env.example)
  - [x] T-164-B: common.py mimic_handler: forward_origin is not None + off → UNHANDLED
  - [x] T-164-C: slavik.py catchall Branch 2: то же правило (mimic пропускается)
  - [x] T-164-D: Тесты (≈6): forwarded+off → нет mimic; обычное → mimic; forwarded+on → mimic (оба механизма)
- [x] T-165 (@Builder): Славик — приоритет приветствия, dead page только на репосты Славы из @d_pages (D53)
  - [x] T-165-A: DEAD_PAGE_POST_ON_JOIN default → False (join → только «ДОЛБОЕБ ВЕРНУЛСЯ»)
  - [x] T-165-B: dead_page_trigger: только репосты Славы (UserIdFilter), убрать is_present-гейт
  - [x] T-165-C: catchall guard: d_pages-репост Славы → UNHANDLED (ни photo, ни mimic, ни «пошёл нахуй»)
  - [x] T-165-D: Интеграционные тесты: join-race (1 ответ), repost-race (1 ответ)
- [x] T-166 (@Builder): PostPicker — не выбирать пост, отправленный в прошлый раз (D54)
  - [x] T-166-A: БД: channel_state `dead_page_last_sent:{chat_id}` + get/set_last_sent_message_id
  - [x] T-166-B: Forward scan + sequential scan: skip кандидата == last_sent (fallback при исчерпании)
  - [x] T-166-C: Random probing: re-roll last_sent без сжигания attempt + контрольный try в конце
  - [x] T-166-D: Запись первичного msg_id после успешного форварда (все пути, включая альбомы)
  - [x] T-166-E: Тесты (≈7): два вызова → разные посты; один пост → fallback повтор
- [x] T-167 (@Builder): Документация, полный pytest, коммит
  - [x] T-167-A: README.md (v2.20.0, changelog)
  - [x] T-167-B: ARCHITECTURE.md + MEMORY.md
  - [x] T-167-C: pytest — 0 регрессий (621 passed: 586 + 35 новых)
  - [x] T-167-D: Коммит `1dbb6da` (feat(triggers): Epic 22 — точность триггеров и фикс гонки ответов (v2.20.0)) + push в origin + деплой (198.46.175.136:/var/www/admin_bot, PID 914116, прод v2.20.0) ✅

> ⚠️ Блокеры/риски (исторически): (1) prod .env мог содержать OLYA_ALWAYS_SEND=True / DEAD_PAGE_POST_ON_JOIN=True — РАЗРЕШЕНО при деплое (DEAD_PAGE_POST_ON_JOIN→False, бэкап .env.bak.2026-08-15);
> (2) не путать last_known_message_id (верхняя граница forward-scan) и dead_page_last_sent (анти-повтор);
> (3) danger_handler (4c) может ответить на d_pages-репост при danger-словах — существующее поведение, вне скоупа.

### Epic 21: BUG FIX — MIMIC Not Working + Time Format Cooldowns — 2026-08-03 ✅ DEPLOYED (v2.19.0, commit c683903)

- [x] T-149: Fix MIMIC propagation — return UNHANDLED в handlers/alan.py (3 code paths)
- [x] T-150: parse_duration / _env_duration хелперы в config/settings.py
- [x] T-151: Переименование 6 cooldown-полей (*_COOLDOWN_SECONDS → *_COOLDOWN, time-format)
- [x] T-152: Update bot.py — все cooldown references
- [x] T-153: Update handlers/slavik.py — SLAVIK_MIMIC_COOLDOWN
- [x] T-154: Update services/mimic_relay.py — MIMIC_COOLDOWN (verified)
- [x] T-155: Update services/common_relay.py — COMMON_COOLDOWN + DANGER_COOLDOWN (verified)
- [x] T-156: Update services/dead_page_relay.py — DEAD_PAGE_COOLDOWN
- [x] T-157: Update .env.example — time-format defaults
- [x] T-158: Update tests + tests/test_duration.py (15 тестов)
- [x] T-159: Полный прогон — 586 tests PASS, 0 failures
- [x] T-160: README.md — v2.19.0, config table
- [x] T-161: Sync MEMORY.md / ARCHITECTURE.md
- [x] T-162: Commit (c683903) + push + deploy — server active (PID 699945)

### Epic 20: Slavik Random Media Enhancement — 2026-08-02 ✅ IMPLEMENTED

- [x] T-139: Verify reply behavior — message.answer_* replies without quoting
- [x] T-140: Add audio support (.mp3) to _detect_slavik_media_type
- [x] T-141: Add voice (.ogg) and document support to _detect_slavik_media_type
- [x] T-142: Add audio sending to _send_slavik_media (answer_audio)
- [x] T-143: Add voice and document sending to _send_slavik_media
- [x] T-144: Verify and harden GIF detection from filename
- [x] T-145: Add comprehensive tests for all 6 media types (61 tests)
- [x] T-146: Run full test suite, verify no regressions
- [x] T-147: Update README with ironic tone about the changes
- [x] T-148: Commit and push (deploy leave to DevOps agent)

### Epic 19: Сервис Olya — автоответ на видео от @ole4444444ka — 2026-08-02 ✅ DEPLOYED

- [x] T-131: Создать `filters/olya_video.py` — `OlyaVideoFilter` (UserId 834424825 + видео + детекция SaveAsBot)
- [x] T-132: Создать `services/olya_relay.py` — `OlyaRelay` (plain send, медиа-автоопределение, cooldown)
- [x] T-133: Создать `handlers/olya.py` — `olya_router` + `olya_handler` + `setup_olya()`
- [x] T-134: Добавить конфигурацию Olya в `config/settings.py` (+8 полей) и `.env.example`
- [x] T-135: Зарегистрировать `olya_router` в `bot.py` (позиция 4d, после common_router, до slavik_router)
- [x] T-136: Написать тесты `tests/test_olya.py` (15-20 тестов: фильтр, сервис, хендлер, интеграционные, corner cases)
- [x] T-137: Обновить README.md — добавить документацию Epic 19
- [x] T-138: Деплой на сервер (git pull, systemctl restart, проверка статуса)

### Epic 18: Danger Service Fixes — File Selection, GIF Detection, Cooldown — 2026-08-02 ✅ DEPLOYED

- [x] T-122-A–J: File scanning/selection
- [x] T-123-A–H: GIF detection in filename
- [x] T-124-A–H: DANGER_COOLDOWN_SECONDS config with independent cooldown
- [x] T-125-A–E: Update config/settings.py and .env.example
- [x] T-126-A–E: Update bot.py for new CommonRelay initialization
- [x] T-127-A–S: Comprehensive tests for all fixes
- [x] T-128-A–E: Update README.md with changes
- [x] T-129-A–E: Run full test suite, verify no regressions
- [x] T-130-A–M: Deploy to server

### Epic 17: Danger Word Fix — 2026-07-30
- [x] T-115: Проверить медиа-файлы danger/ на сервере
  - [x] T-115-A-E: SSH проверка, права, diff
- [x] T-116: Проверить и исправить DangerWordFilter
  - [x] T-116-A-G: 91+ слов, word-boundary, регистронезависимость, caption, логирование
- [x] T-117: Проверить war_alert_router ↔ common_router interaction
  - [x] T-117-A-F: порядок роутеров, F.forward_origin → TargetChannelFilter, propagation
- [x] T-118: Проверить и исправить CommonRelay.send_common
  - [x] T-118-A-G: _scan_directory, _pick_media, _detect_media_type, _send_media, error handling
- [x] T-119: Тесты для danger_word
  - [x] T-119-A-I: 91+ слов, регистр, word boundary, caption/forward, cooldown, integration, pytest
- [x] T-120: README — changelog, v2.12.2 → v2.15.0
- [x] T-121: Деплой на сервер
  - [x] T-121-A-H: git pull, .env, restart, smoke tests, Better Stack

### Epic 16: Bug Fixes Sprint — 2026-07-29 ✅ ARCHIVED (→ Epic 17)
- [x] Epic 16 archived 2026-07-30. Danger_word fix → Epic 17. DeadPageRelay album fix → deferred.
- [x] T-109: DangerWordFilter — RCA completed (22 слова → нужно 91+)
- [x] T-114: war_channel_repost_handler — RCA completed (F.forward_origin блокирует)
- [x] T-113: DEAD_PAGE_RELAY_CHANNEL_ID — RCA completed
- [x] T-110: DeadPageRelay album fix — ARCHIVED (перекрыто Epic 14 T-093–T-099)
- [x] T-111: Тесты — ARCHIVED (перекрыто Epic 14 T-098 / Epic 17 T-119)
- [x] T-112: Документация — ARCHIVED (перекрыто Epic 17 T-120)

### Epic 15: Common Service — Rename + Media Upgrade + Danger — 2026-07-28
- [x] 👤 T-100 (@Architect): Архитектурное проектирование Common Service + sub-agent review
  - [x] T-100-A: Спроектировать архитектуру — модули, data flow, directory structure, контракты
  - [x] T-100-B: Sub-agent ревью — изоляция, масштабируемость, корректность rename, media type detection
  - [x] T-100-C: Согласовать финальный дизайн с PM
- [x] T-101: Переименование файлов и модулей (otboy → common)
  - [x] T-101-A: handlers/otboy.py → handlers/common.py
  - [x] T-101-B: services/otboy_relay.py → services/common_relay.py
  - [x] T-101-C: filters/otboy_word.py оставлен; СОЗДАН filters/danger_word.py (DangerWordFilter)
  - [x] T-101-D: Обновлены все импорты в bot.py
  - [x] T-101-E: Grep-проверка — нет dead imports
- [x] T-102: Конфигурация — переименованы и добавлены env-переменные
  - [x] T-102-A: OTBOY_COOLDOWN_SECONDS → COMMON_COOLDOWN_SECONDS
  - [x] T-102-B: OTBOY_PHOTO_PATH удалён, добавлен COMMON_MEDIA_BASE
  - [x] T-102-C: Созданы директории media/common/otboy/ и media/common/danger/
  - [x] T-102-D: Обновлён .env.example
- [x] T-103: Upgrade media-обработки — directory-based picker с авто-детекцией типа
  - [x] T-103-A: CommonRelay._pick_media(media_dir)
  - [x] T-103-B: _detect_media_type(filename) → photo/video/animation
  - [x] T-103-C: _send_media(chat_id, filepath, media_type, reply_params)
  - [x] T-103-D: send_otboy() использует _pick_media + _send_media
  - [x] T-103-E: Логирование media type
- [x] T-104: Новая функция детекции опасных слов (danger)
  - [x] T-104-A: DangerWordFilter — DANGER_WORDS + pattern compilation
  - [x] T-104-B: CommonRelay.send_danger() — _pick_media + _send_media + reply_to + quote
  - [x] T-104-C: danger_handler в common.py
  - [x] T-104-D: Reply-to + quote mechanism (ReplyParameters)
  - [x] T-104-E: Comprehensive logging для danger
- [x] T-105: Интеграция в bot.py
  - [x] T-105-A: Импорты: common_router, setup_common, CommonRelay
  - [x] T-105-B: dp.include_router(common_router) — позиция 4c
  - [x] T-105-C: on_startup(): CommonRelay, setup_common(relay)
  - [x] T-105-D: Propagation проверен (оба handler'а возвращают None)
- [x] T-106: Тесты (~20+ тестов)
  - [x] T-106-A: test_otboy.py → test_common.py
  - [x] T-106-B: 11 тестов OtboyWordFilter перенесены
  - [x] T-106-C: 6 тестов otboy_handler перенесены (OtboyRelay → CommonRelay)
  - [x] T-106-D–G: Media type detection, _pick_media edge cases
  - [x] T-106-H–I: DangerWordFilter тесты (срабатывает/не срабатывает/регистр/word boundary)
  - [x] T-106-J–K: danger_handler + CommonRelay.send_danger тесты
  - [x] T-106-L: Cooldown тесты (общий для otboy+danger, per-chat)
  - [x] T-106-M–N: Интеграция — propagation + диспетчеризация
- [x] T-107: Документация — README, ARCHITECTURE, MEMORY обновлены, v2.12.0
- [x] T-108: QA — тесты, коммит, деплой
  - [x] T-108-A: pytest — 316+ тестов, 0 регрессий
  - [x] T-108-B: Коммит на русском (conventional commits) в main, пуш
  - [x] T-108-C: Деплой на сервер — git pull, .env, restart
  - [x] T-108-D: Smoke test: «отбой» → медиа из common/otboy
  - [x] T-108-E: Smoke test: «ракетная опасность» → медиа из common/danger
  - [x] T-108-F: Smoke test: другие фичи не сломаны
  - [x] T-108-G: Better Stack логи verified

### Epic 14: Media Group Album Fix — 2026-07-28
- [x] T-093: Новая таблица relay_album_map + 3 CRUD метода в database.py
- [x] T-094: channel_post handler в bot.py для отслеживания media_group_id
- [x] T-095: Модифицировать DeadPageRelay._try_forward_from_channel() — DB lookup + forward_messages()
- [x] T-096: Эвристический fallback — пробинг соседних message_id ±1..9
- [x] T-097: Дедупликация media_group в dead_page_trigger.py
- [x] T-098: Тесты (10 cases) — DB + heuristic + dedup + integration
- [x] T-099: QA — pytest (316 tests), обновление документации, v2.11.0

### Epic 13: Otboy Service (F9) — 2026-07-26
- [x] T-084: Архитектурное проектирование и ревью (sub-agent review)
- [x] T-085: Создать filters/otboy_word.py — OtboyWordFilter
- [x] T-086: Создать services/otboy_relay.py — OtboyRelay
- [x] T-087: Создать handlers/otboy.py — otboy_router
- [x] T-088: Конфигурация — OTBOY_COOLDOWN_SECONDS, OTBOY_PHOTO_PATH
- [x] T-089: Зарегистрировать otboy_router в bot.py (позиция 4c)
- [x] T-090: Тесты для Otboy Service (10 тестов — filter + handler + relay + integration)
- [x] T-091: Документация — README, ARCHITECTURE, MEMORY, v2.10.0
- [x] T-092: Деплой на сервер + smoke tests

### Epic 12: Багфикс репостов + slavic_na_litso.jpg — 2026-07-25
- [x] T-078: Расследование и исправление бага с репостами Славы (war_alert не ловит forwarded messages)
  - [x] T-078-A: Расследование — diagnostic-логи, проверка гипотез (UserIdFilter для forwarded, message.text/caption, порядок хендлеров, propagation)
  - [x] T-078-B: Исправление бага
  - [x] T-078-C: Comprehensive logging для forwarded-сообщений
- [x] T-079: Реализация фичи — slavic_na_litso.jpg каждый N-й ответ "пошёл нахуй"
  - [x] T-079-A: Добавить `SLIVIC_NA_LITSO_INTERVAL` в config/settings.py + .env.example
  - [x] T-079-B: Добавить счётчик в DatabaseService
  - [x] T-079-C: Модифицировать slavik_catchall_handler в handlers/slavik.py
  - [x] T-079-D: Comprehensive logging
- [x] T-080: Тесты для багфикса репостов (test_war_alert.py — 6 тестов)
- [x] T-081: Тесты для фичи slavic_na_litso.jpg (test_slavik_handlers.py — 8 тестов)
- [x] T-082: Обновление README + ARCHITECTURE.md + MEMORY.md, коммит, пуш
- [x] T-083: Деплой на сервер + smoke tests

### Epic 11: Alan Silence Greeting (F7v2 — "Леха проснулся") — 2026-07-18
- [x] T-064: Добавить ALAN_SILENCE_GREETING_HOURS в config/settings.py + .env.example
- [x] 👤 T-065 (@Architect): Решение о хранилище — БД через channel_state
- [x] T-066: Реализовать get/set_alan_last_message_ts в DatabaseService
- [x] T-067: Встроить silence-логику в alan_handler (handlers/alan.py)
- [x] T-068: Логика детекта "молчал >= N часов → написал" → _send_greeting()
- [x] T-069: Обновление таймера при КАЖДОМ сообщении Алана
- [x] T-070: Edge cases — baseline, N=0, несколько чатов, restart persistence, cooldown
- [x] T-071: Детальное логирование каждого этапа
- [x] T-072: Интеграция в bot.py — без изменения порядка роутеров
- [x] T-073: Тесты — 19 новых тестов
- [x] T-074: Обновить README.md
- [x] T-075: Прогнать полный pytest suite — 271 тест, без регрессий
- [x] T-076: Коммит на русском в main, пуш
- [x] T-077: Деплой на сервер + ALAN_SILENCE_GREETING_HOURS=2

### Epic 10: War Words Redesign (F5v2) — 2026-07-16
- [x] T-054: Fix WarWordFilter — caption support + expand WAR_WORDS keywords (90+ форм)
- [x] T-055: Add channel repost detection handler for military channels (war_words_trigger.py)
- [x] T-056: Replace single hardcoded reply with extensible pool + random.choice()
- [x] T-057: Add comprehensive Better Stack logging
- [x] T-058: Create/extend tests — filter, handler, integration (~28 tests)
- [x] T-059: Update config/settings.py — WAR_CHANNEL_IDS, WAR_CHANNEL_USERNAMES, WAR_REPLIES
- [x] T-060: Register war_alert_router in bot.py (position 4b)
- [x] T-061: Update README — document F5v2
- [x] T-062: Run full pytest suite — verify no regressions (~280 tests)
- [x] T-063: Deploy to server

### Epic 9: Admin Test Commands (2026-07-14)
- [x] T-048: /deadpage — ручной вызов DeadPageRelay.send_dead_page()
- [x] T-049: /alangreet — ручной вызов _send_greeting()
- [x] T-050: Прогнать pytest — без регрессий
- [x] T-051: Тесты на admin_commands (6 тестов)

### Epic 8: Alan Greeting Video (F7) — 2026-07-13
- [x] T-038: Add ALAN_USERNAME, ALAN_USER_ID, ALAN_GREETING_DIR to config
- [x] T-039: Create handlers/alan_greeting.py (join + fallback + video + caption)
- [x] T-040: Register alan_greeting_router in bot.py (position 1b)
- [x] T-041: Write tests/test_alan_greeting.py (7-8 tests)
- [x] T-042: Update ARCHITECTURE.md
- [x] T-043: Update MEMORY.md
- [x] T-044: Run all tests — no regressions
- [x] T-045: Code review and QA

### Epic 7: Better Stack Monitoring Integration (2026-07-12)
- [x] T-029: Add sentry-sdk==2.64.0 and logtail-python==0.4.0 to requirements.txt
- [x] T-030: Install sentry-sdk and logtail-python into venv
- [x] T-031: Add SENTRY_DSN and LOGTAIL_SOURCE_TOKEN to .env.example
- [x] T-032: Add SENTRY_DSN and LOGTAIL_SOURCE_TOKEN to .env
- [x] T-033: Initialize Sentry SDK in bot.py
- [x] T-034: Configure LogtailHandler on root logger
- [x] T-035: Write and run smoke test
- [x] T-036: Run pytest — no regressions
- [x] T-037: Update ARCHITECTURE.md with monitoring section

### Epic 6: Dead Page V2 — Event-driven reposts
- [x] T-018: Update config/settings.py + .env.example
- [x] T-019: Update DEAD_PAGE_V2_PLAN.md
- [x] T-020: Create services/dead_page_relay.py
- [x] T-021: Create handlers/dead_page_trigger.py
- [x] T-022: Simplify services/scheduler.py
- [x] T-023: DB migration (channel_state, timestamp, new methods)
- [x] T-024: Update bot.py (register dead_page_router #4, init DeadPageRelay)
- [x] T-025: Add comprehensive logging to dead_page modules
- [x] T-026: Update MEMORY.md and ARCHITECTURE.md
- [x] T-027: Write/rewrite tests
- [x] T-028: Run all tests and verify coverage

### Epic 1: Рефакторинг
- [x] T-001: Вынести API_TOKEN в .env / конфигурацию
- [x] T-002: Создать requirements.txt с закреплёнными версиями
- [x] T-003: Создать единую структуру проекта
- [x] T-004: Унифицировать обработку ошибок и логирование
- [x] T-005: Создать общий базовый класс для фильтров

### Epic 2: Новые функции
- [x] T-006 (F1): При возвращении Славы в чат → «ДОЛБОЕБ ВЕРНУЛСЯ»
- [x] T-007 (F2): Dead-page посты — рандомное фото + текст
- [x] T-008 (F3): Каждые 5 сообщений → GIF через MessageCounterMiddleware
- [x] T-009 (F4): «КУЧА» → «ДАЛБАЕБ» с KuchaWordFilter
- [x] T-010 (F5): Военные слова → «трясло ебаное» (DEPRECATED — заменено на F5v2)
- [x] T-011 (F6): Каждые 10 сообщений @Alan_Z → reply random-фразой

### Epic 3: Тестирование и CI
- [x] T-012: Модульные тесты на все хендлеры
- [x] T-013: Тесты на все корнер-кейсы
- [x] T-014: Интеграционные тесты

### Epic 4: Документация
- [x] T-015: README.md с ироничной документацией

### Epic 5: Багфиксы
- [x] T-016 (Kostik): Probability-based reply engine + extensible pool
- [x] T-017 (Kucha): Fix KuchaWordFilter regex

### Bugfixes (Critical/High) — 2026-07-13 to 2026-07-15
- [x] T-046: Dead Page Relay — ALL RANGES EXHAUSTED (Critical)
- [x] T-047: Alan Greeting Video — service never fires (High)
- [x] T-052: Dead Page Relay — sequential scanning for sparse channels (Critical)
- [x] T-053: Propagation-stopping bug in slava_presence.py — F7 completely broken (Critical)

### Remaining LOW (not blocking — ARCHIVED, вне активного бэклога)
- [ ] H3: Dispatcher integration tests — deferred
- [ ] L1: README platform-specific Windows commands
- [ ] L2: Quoting in response text (reply_to covers)
- [ ] L4: MediaService cache invalidation
- [ ] L5: VasyaFilter translit order edge case

---

**Updated:** 2026-08-16 — **Epics 1-25 ALL DEPLOYED ✅ и архивированы в колонке Done (PM)**. Epic 24 «SmartModule: Summary» (v2.22.0, `a68732c`, PID 920105) и Epic 25 (багфикс /summary, v2.23.0-fix, `c364f18`, PID 923954) перенесены из Backlog в Done при архивации. **Epic 26 «GraphRAG-память» — IN PROGRESS:** дизайн T-199 (Section 35) APPROVED PM; T-200…T-204 реализованы и прошли ревью @Reviewer (перенесены в Done); 🚨 **T-206 (T26.7, P1)** — преддеплойный фикс FTS-удаления медиа-без-подписи (In Progress, блокер); **T-205 (T26.6, деплой)** — выполняется только после фикса T-206. Полный трек — `plans/backlog.md` (Epic 26).
