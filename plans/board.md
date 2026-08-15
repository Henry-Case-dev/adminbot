# AdminBot — Kanban Board

## 📋 Backlog

### Epic 24: SmartModule — сервис Summary (v2.22.0) — 2026-08-16 — ✅ DEPLOYED (коммит `a68732c`; ⚠️ Н1 BotFather `/setprivacy` → Disable — ручное действие пользователя)

> **Шаг воркфлоу:** 1/3 (PM) ✅ → 2 (@Architect) ✅ → 3 (@Builder ✅ T-174…T-189, @Reviewer ✅ T-188-D APPROVED 2026-08-16, @DevOps ✅ T-190/T-191). Epic 24 ЗАДЕПЛОЕН (v2.22.0). Осталось пользователю: Н1 — BotFather `/setprivacy` → **Disable**.
> Требования R1–R18, PM-решения D59–D64, системный промпт (дословно) и риски —
> в `plans/backlog.md` (Epic 24). Дизайн — `plans/ARCHITECTURE.md` Section 33 (T-173, Done).

- [x] T-174 (@Builder, P0, ←T-173): Конфигурация — settings.py + .env.example (LLM_*, окна памяти, MAX_SUMMARY_PARTS, ALLOWED_SUMMARY_IDS, алиасы, троттлинг; D59) — **Done: 24 поля + секция SmartModule в .env.example + requirements (httpx/APScheduler/sqlite-vec)**
- [x] T-175 (@Builder, P0, ←T-173): БД — таблица `smart_messages` + CRUD + миграция (R1) — **Done: _SCHEMA_SQL (smart_messages+author_name, 2×FTS5, smart_archive_facts) + 10 методов**
- [x] T-176 (@Builder, P0, ←T-175): Память L1+L2 — окно генерации 6ч (один проход) + RAG-сырьё (R2) — **Done: get_window_messages + search_long_term (FTS5-префиксы)**
- [x] T-177 (@Builder, P1, ←T-175/T-178): Память L3 — sqlite-vec архив: суммаризация по темам/фактам + KNN (R2) — **Done: initialize() с ленивой загрузкой vec0, compress_and_purge пачками, KNN без JOIN (ограничение vec0 0.1.x)**
- [x] T-178 (@Builder, P0, ←T-173/T-174): LLM-клиент — генерация deepseek-v4-flash + эмбеддинги gemini-embedding-001, провайдер-агностик (R4/R5) — **Done: httpx, retry 429/5xx/timeout с backoff, LLMError-иерархия**
- [x] T-179 (@Builder, P1, ←T-177/T-178): Фоллбек FTS5 при недоступности sqlite-vec ИЛИ эмбеддингов (R3/D60) — **Done: vector_search → FTS5 при любом сбое; тест деградации зелёный**
- [x] T-180 (@Builder, P0, ←T-175): XML-контекст `<chat_history><message …/></chat_history>` (R6) — **Done: saxutils + control-символы, описания медиа, капы окна**
- [x] T-181 (@Builder, P1, ←T-180): Алиасы: каскад alias → nickname → username (без @) → user_id (R7/D61) — **Done: JSON-словарь + кэш; тест «нет @» на всех ветках**
- [x] T-182 (@Builder, P0, ←T-173): Системный промпт — захардкодить ДОСЛОВНО, `{max_symbols}` плейсхолдер (R11) — **Done: байт-в-байт тест против backlog.md; подстановка через replace (не format — {username} остаётся литералом)**
- [x] T-183 (@Builder, P0, ←T-178..T-182): APScheduler — 00:00/06:00/12:00/18:00, TZ Asia/Yekaterinburg, MemoryJobStore (R8) — **Done: AsyncIOScheduler + CronTrigger с явным timezone, max_instances=1+coalesce, shutdown идемпотентен**
- [x] T-184 (@Builder, P0, ←T-183): Ручной триггер `/summary` — ALLOWED_SUMMARY_IDS пуст → всем (R9/D62) — **Done: summary_router 0b + observer 0a (UNHANDLED всегда), интеграция 13 роутеров зелёная**
- [x] T-185 (@Builder, P1, ←T-184): ThrottlingMiddleware — in-memory, молчаливое прерывание при спаме (R10) — **Done: router-scoped на summary_router, key=chat+user**
- [x] T-186 (@Builder, P0, ←T-183): Чанкинг ≤4096 по пробелам, `{max_symbols}=(parts*4000)-200`, UX-ошибки (R12/R13/D63) — **Done: + SUMMARY_CHUNK_DELAY между чанками, TelegramRetryAfter→sleep+1 повтор, _ensure_shiz_postfix со стрипом @**
- [x] T-187 (@Builder, P1, ←T-183): Observability — Better Stack, полные стектрейсы, сырые ответы LLM (R14) — **Done: logger.exception + raw response в INFO**
- [x] T-188 (@Builder + @Reviewer, P0, ←T-186): Тесты — максимальное покрытие + отсутствие конфликтов с 12 роутерами + полный pytest (R15) + code review (T-188-D) — **DONE: A/B/C @Builder (157 новых тестов, интеграция 13 роутеров) + T-188-D @Reviewer APPROVED 2026-08-16. Ревью: 829 passed подтверждён личным прогоном; вердикт APPROVE WITH FIXES → 2 точечных фикса внесены ревьюером (`await _summary_service.shutdown()` в bot.py on_shutdown — не-awaited coroutine; vec0-purge → документированная форма `rowid IN`) + 1 QA-тест test_vec_purge_removes_vectors → итог 830 passed. Low-замечания (не блокируют, на T-189): экранирование l2/l3-цитат в псевдо-XML, /summary@bot обходит троттлинг, нет жёсткого капа чанков по MAX_SUMMARY_PARTS, SUMMARY_CHUNK_DELAY=2.0 зафиксировать в доках**
- [x] T-189 (@Builder, P1, ←T-188): README (ироничный тон) + ARCHITECTURE/MEMORY, v2.22.0 (R15) — **Done: README секция SmartModule (фичи/память/деградация/все env-переменные/прод-требования BotFather setprivacy+LLM_API_KEY), changelog v2.22.0, фиксы Low-2 (экранирование <memory>/<facts> через escape_xml_text) и Low-3 (троттлинг /summary@BotName) + 6 тестов, Low-4/Low-5/E9 задокументированы, ARCHITECTURE 33.16 (фактические решения), итог 835 passed**
- [x] T-190 (@Builder + @DevOps, P0, ←T-189): Коммит на русском (conventional) в master + push; .env не коммитим (R15/R17) — **Done: коммит `a68732c` (35 файлов, v2.22.0), push origin/master OK; .env не коммичен**
- [x] T-191 (@DevOps, P0, ←T-190): Деплой — ssh nik@198.46.175.136, git pull, nano .env, systemctl restart/status, отчёт (R16) — **Done: git pull `a68732c` (fast-forward), .env +LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME/SUMMARY_TIMEZONE (без дублей), venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1, restart → active (running) PID 920105, curl apinet.cloud OK (список моделей, auth по ключу), лог: sqlite-vec dim=768 + scheduler cron 0,6,12,18 Asia/Yekaterinburg, трейсбеков нет. ⚠️ Н1 (BotFather /setprivacy → Disable) — ручное действие пользователя**

### Epic 25: Багфикс — /summary не реагирует + удаление команды — 2026-08-16 — 🆕 PLANNED

> **Шаг воркфлоу:** 1/3 (PM) ✅ → 2 (@Architect) ✅ (T-192 RCA + T-193 Section 34) → **PM-гейт ✅ APPROVED 2026-08-16** → 3 (@Builder ✅ T-194/T-195 DONE 2026-08-16) → **@Reviewer ✅ T-196 APPROVED 2026-08-16** → T-197/T-198 READY FOR @DevOps. Требования R25-1…R25-4, PM-решения D65/D66 и риски — в `plans/backlog.md` (Epic 25). Дизайн фикса — `plans/ARCHITECTURE.md` Section 34 (T-193, @Architect DONE; T-193-B — PM APPROVED).
> **Реализация @Builder (T-194/T-195):** B1 ack «ща гляну, подожди» отдельным send_message до пайплайна; B2 `generate_and_send(chat_id, manual=False)` (scheduler без изменений); B3 троттлинг валидирует mention через `data["bot"].me()` (чужая mention не жжёт слот, `base == "/summary"` точное сравнение, guard на пробельный текст, R8-молчание + INFO-лог с remaining); B4 пустое окно → UX (manual) / INFO (cron); B5 lock busy → «уже делаю саммари, подожди» + очередь; B6 `bot` из DI хендлера в `_safe_send` (работает при `_generator is None`); B7 `message.delete()` сразу после ack, try/except → WARNING; B8 INFO-логи всех состояний; B9 наблюдатель не пишет `/summary*` (guard по префиксу, text и caption). Тесты: +25 (860 total), 0 регрессий.
> **Гипотезы RCA:** H-A нет ack при долгом LLM (~3.5 мин) · H-B пустое окно L1 → молчание · H-C троттлинг 60с глотает повторы · H-D гонка cron/Lock · H-E ALLOWED_SUMMARY_IDS на проде · H-F бесшумный сбой отправки. Исключено: недостижимость хендлера, privacy-блокировка.
> **RCA-вывод (T-192):** первопричина — асимметрия троттлинг-мидлвари с aiogram Command-фильтром: 18:02:19 `/summary@RofloslavBot` (чужая mention) сжёг слот троттлинга и был корректно отклонён хендлером, 18:02:31 повтор `/summary` — молча сглочен троттлингом (H-C ✅). H-A/H-B/H-D/E/F не реализовались (доказательства: journalctl+smart_messages+aiogram source); закрыты превентивно B1/B4/B5.

- [x] T-192 (@Architect + @DevOps, P0, —): RCA — прод-логи Better Stack/Sentry + journalctl за момент теста, прод .env, статус Н1 + админ-права `delete_messages`, следы cron; отчёт причин по H-A…H-F → feed в T-193/T-194. **Done: первопричина — чужая mention `/summary@RofloslavBot` сожгла слот троттлинга (middleware матчит без валидации mention), повтор `/summary` через 12с молча сглочен (журнал: единственная строка «throttled», «triggered» — ноль; БД: id=68/69; aiogram 3.29.1 validate_mention). H-A/H-B/H-D/E/F не подтвердились (окно 91 msg, бот жив, ALLOWED пуст, cron не совпал). Доказательства в Section 34.2**
- [x] T-193 (@Architect, P0, ←T-192): Дизайн фикса в ARCHITECTURE.md Section 34 — ack-механика (D66), UX-ответы вместо молчания (H-B/H-C/H-F), best-effort удаление (D65), решения по троттлингу/cron-гонке. **Done: Section 34 (34.1–34.10), решения B1–B9: B1 ack «ща гляну, подожди» отдельным send_message до пайплайна; B2 manual-флаг (cron без ack); B3 симметрия троттлинга с Command-фильтром (чужая mention не жжёт слот, R8-молчание сохранено); B4 пустое окно → UX; B5 lock занят → «уже делаю саммари, подожди» + очередь; B6 страховки UX; B7 delete best-effort сразу после ack (WARNING при отказе, удаляется только команда); B8 логирование состояний; B9 наблюдатель не пишет /summary* в память. Тесты + риски (R8/R9 сохранены, ack отсекается bot.id-фильтром). T-194 READY FOR BUILDER** ✅ **PM-аппрув 2026-08-16: B1–B9 сверены с R25-1…R25-4 + исходным ТЗ (R7/R8). Замечания Builder (не блокируют): (1) B6 — `_safe_send` использует `_generator.bot` → при `_generator is None` UX не доставляется; ввести `bot` в `setup_summary` (обязательно) или принимать `bot` параметром хендлера; (2) B3 — сохранить guard `if text.strip()` из текущего кода (иначе IndexError на пробельном тексте) и сравнение `base == "/summary"` вместо startswith (полная симметрия с Command); (3) backlog синхронизирован: H-C остаётся молчаливой (R8), только INFO-лог. Гейт открыт.**
- [x] T-194 (@Builder, P0, ←T-193): **READY FOR BUILDER** — Реализация — ack «ща подумаю» до LLM; UX-ответы вместо молчания; удаление команды (best-effort try/except); логирование этапов. **DoD:** /summary отвечает всегда (кроме осознанных случаев); команда удаляется; сбой удаления логируется и не ломает ответ — **Done: B1–B9 реализованы (см. ниже)**
- [x] T-195 (@Builder, P0, ←T-194): **READY FOR BUILDER** — Тесты — ack до LLM, UX-ветки H-B/H-F, чужая mention не жжёт слот, delete после обработки, delete-ошибка не роняет пайплайн; полный pytest. **DoD:** 835 + новые, 0 регрессий — **Done: +25 новых тестов (860 total), полный прогон зелёный, 0 регрессий**
- [x] T-196 (@Reviewer, P1, ←T-195): Ревью фикса. **DoD:** аппрув в board.md, R25-1…R25-4 проверены — **Done: APPROVED 2026-08-16. Личный прогон 860 passed (835+25), 0 регрессий. B1–B9 соответствуют Section 34. Первопричина закрыта: чужая mention не жжёт слот и проходит мимо троттлинга; своя/без mention троттлится; `base == "/summary"` точное сравнение (/summaryfoo не матчится); case-insensitive mention; guard на пробельный текст. R8 сохранён (троттлинг молчалив, только INFO+remaining), R9 сохранён (denied без ack/delete/ответа, INFO). B7: delete после ack, try/except → WARNING, удаляется только команда. B6: bot из DI хендлера — работает при `_generator is None`. aiogram 3.29.1 проверен по исходникам venv: "bot" есть в data (middleware + handler-DI), `Bot.me()` кэшируется (`self._me`, нет N+1), `Message.delete()` → DeleteMessage. Low-замечания (не блокируют; на T-198/будущий эпик): (1) мидлварь не смотрит `caption`, а Command-фильтр смотрит (`text or caption`) → команда-капшн обходит троттлинг (pre-existing с Epic 24, сериализуется Lock; требует решения PM/Architect); (2) «ack sent» логируется и при неудачной отправке ack (косметика); (3) `bot.me()` в мидлвари без try/except — сбой первого getMe уронит обработку update (бот жив, errors-handler); (4) `self._last` растёт без TTL (pre-existing). Передача @DevOps (T-197) разрешена.**
- [ ] T-197 (@DevOps, P0, ←T-196): Коммит на русском (conventional) + push. **DoD:** коммит в master, .env не коммичен
- [ ] T-198 (@DevOps, P0, ←T-197): Деплой на прод + верификация /summary живьём через логи. **DoD:** в логах виден полный пайплайн — triggered + ack + отправка + удаление (или WARNING удаления с причиной)

## 🔧 In Progress

*No items in progress.*

## 🔍 In Review

*No items in review.*

## ✅ Done

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

**Updated:** 2026-08-16 — **Epics 1-24 ALL DEPLOYED ✅** (v2.22.0, коммит `a68732c`). Epic 24 «SmartModule: Summary»: @Builder T-174…T-189 ✅, @Reviewer T-188-D APPROVED ✅, @DevOps T-190 (коммит+пуш `a68732c`) ✅ / T-191 (деплой на прод: git pull, .env, venv-зависимости, restart → active (running), smoke apinet.cloud OK) ✅. Н1 (BotFather `/setprivacy` → Disable) — ручное действие пользователя (невыполнимо через SSH). **Epic 25 (багфикс /summary + удаление команды): @Architect ✅ T-192 (RCA: чужая mention сожгла слот троттлинга + повтор молча сглочен; H-A/H-B/H-D/E/F не подтвердились) + T-193 (Section 34, B1–B9). PM-гейт ✅ APPROVED 2026-08-16 (B1–B9 сверены с R25-1…R25-4 и исходным ТЗ R7/R8; замечания Builder: B6 bot-инжекция, B3 strip-guard + точное сравнение). T-194/T-195 → READY FOR BUILDER, передано @Builder.**
