# MEMORY.md — AdminBot

> **Версия:** v2.22.0 DEPLOYED (Epic 24 SmartModule: Summary, коммит `a68732c`). **Epic 25 (багфикс /summary) — IMPLEMENTED + REVIEW PASSED (Section 34 B1–B9, 860 тестов; Шаг 6 sync @Memory).**
> **Дата:** 2026-08-16
> **Обновление:** 2026-08-16 — **Epic 25 (багфикс /summary) — Шаг 6 (@Memory, граф знаний после реализации и ревью): T-194/T-195 IMPLEMENTED (@Builder, B1–B9 в summary_throttling.py / summary_generator.py / handlers/summary.py), T-196 REVIEW APPROVED (@Reviewer, 860 тестов подтверждены лично, 4 Low-замечания не блокируют). Тесты: 860 PASS (835+25), 0 регрессий. Осталось: T-197 (коммит+пуш) и T-198 (деплой+верификация) → @DevOps.**
> **Обновление:** 2026-08-16 — **Epic 25 (багфикс /summary) — Шаг 3 (@Memory, граф знаний после фазы архитектуры): RCA ПОДТВЕРЖДЁН прод-логами (асимметрия ThrottlingMiddleware vs aiogram Command-фильтр), Section 34 (B1–B9) DESIGN APPROVED (PM: B6 ⚠️, B3 ⚠️). T-192/T-193 Done, T-194/T-195 READY FOR BUILDER.**
> **Обновление:** 2026-08-16 — **Epic 25 (багфикс /summary) — Шаг 0 (@Memory, синхронизация контекста по баг-репорту): «/summary не реагирует» + требование удалять сообщение команды из чата.**
> **Обновление:** 2026-08-16 — **Epic 24 «SmartModule: Summary» — Шаг 8 (@Memory, финальная синхронизация): ВЕСЬ запрос пользователя выполнен ✅. T-190 DONE (835 тестов PASS локально; коммит `a68732c`, 35 файлов, +4495/−28; docs-коммит `818e195`; пуш master; HEAD = origin/master). T-191 DONE (прод 198.46.175.136: git pull ff `756d237..a68732c`, .env +LLM-ключи, venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1, smoke T-191-D ✅ apinet.cloud/v1/models OK, restart → active (running) PID 920105). Осталось пользователю вручную: Н1 BotFather `/setprivacy` → Disable (критично) + живая проверка `/summary`.**
> **Статус:** Epics 1–24 ALL DEPLOYED ✅ (v2.22.0, `a68732c` + `818e195`, 835 тестов). Epic 24 DEPLOYED на проде (PID 920105, 0 трейсбеков). **Epic 25: IMPLEMENTED + REVIEW PASSED — T-192/T-193/T-194/T-195/T-196 Done, 860 тестов PASS (835+25), 0 регрессий. Осталось: T-197 (коммит+пуш) + T-198 (деплой+верификация) → @DevOps.** Ручные действия пользователя: Н1 (BotFather `/setprivacy` → Disable) и живая проверка `/summary` в чате.
> **Текущий коммит:** `a68732c` (feat(summary): Epic 24 — SmartModule с трехуровневой памятью и саммари чата (v2.22.0)) + docs-коммит `818e195` (синхронизация board.md) — оба в origin/master (github.com/Henry-Case-dev/adminbot.git).
> **Сервер:** 198.46.175.136:/var/www/admin_bot, systemctl active (running), PID 920105, логи чистые: «sqlite-vec loaded (dim=768)», «SmartModule Summary (Epic 24) initialized (TZ=Asia/Yekaterinburg)», cron 0,6,12,18, все 14 роутеров зарегистрированы.

---

## 🐛 Epic 25: багфикс /summary — IMPLEMENTED + REVIEW PASSED (Шаг 6, @Memory, 2026-08-16)

> **Статус:** RCA ПОДТВЕРЖДЁН прод-логами (T-192 ✅) → Section 34 (B1–B9) DESIGN APPROVED (T-193 ✅) → **IMPLEMENTED** (@Builder T-194/T-195 ✅, 860 тестов PASS) → **REVIEW APPROVED** (@Reviewer T-196 ✅, 4 Low-замечания не блокируют). Осталось: **T-197/T-198 → @DevOps.** Прод: v2.22.0 (PID 920105).

### 🔬 RCA — подтверждён прод-логами Better Stack (T-192, 2026-08-16)

**Первопричина — асимметрия ThrottlingMiddleware с aiogram Command-фильтром:**

1. **18:02:19** пользователь прислал `/summary@RofloslavBot` (чужая mention) → middleware **сжёг слот троттлинга** (`startswith` без валидации mention) → `Command("summary")` **отклонил** сообщение (aiogram 3.29.1 `validate_mention`) → **тишина**;
2. **18:02:31** повтор `/summary` → **throttled** (12с < 60с) → молчание (by design R8).
3. За весь boot **ни одной строки** `triggered` / `window_size` / `LLM request` в логах — пайплайн не запускался ни разу.

**Опровергнутые гипотезы:** H-A/H-B/H-D/H-E/H-F ❌ — окно 91 msg НЕ пустое (наблюдатель работает); бот active; `ALLOWED_SUMMARY_IDS` не задан; 18:02 UTC не совпадает с cron-тиком (0,6,12,18 Asia/Yekaterinburg).

### 🏗️ Section 34 (ARCHITECTURE.md 34.1–34.10): решения B1–B9 — IMPLEMENTED (T-194/T-195) + REVIEWED (T-196)

| # | Решение | Суть |
|---|---------|------|
| **B1** | Ack до пайплайна | «ща гляну, подожди» — только manual, `send_message` (не reply) |
| **B2** | `generate_and_send(chat_id, manual=False)` | cron — без ack |
| **B3** ⚠️ | Троттлинг | Чужая mention не потребляет слот (`data["bot"].me()`, кэш, case-insensitive); точное сравнение `base == "/summary"` вместо `startswith`; guard `text.strip()`; R8-молчание сохранено; Low-3 жив |
| **B4** | Пустое окно | manual → UX «тут тишина, саммарить нечего»; cron → INFO |
| **B5** | Lock занят | UX «уже делаю саммари, подожди» + очередь |
| **B6** ⚠️ | Страховка `_generator is None` | UX-ошибка; `_safe_send(bot)` принимает bot из DI хендлера (ревью J1 — вместо `setup_summary`) |
| **B7** | `message.delete()` | Сразу после ack (НЕ finally), try/except → WARNING; только исходная команда; denied — не удаляем. **Отменяет A11** |
| **B8** | Логирование всех состояний | triggered / throttled+remaining / ack / window empty / locked / llm ok/fail / chunk / command deleted; denied DEBUG→INFO |
| **B9** | Наблюдатель | Не пишет `/summary*` в smart_messages |

### ✅ Реализация (T-194/T-195, @Builder, 2026-08-16) — B1–B9 IMPLEMENTED

- `services/summary_throttling.py` (B3): `_parse_command` — валидация mention через `data["bot"].me()` (кэш aiogram, case-insensitive); чужая mention НЕ жжёт слот и пропускается; точное сравнение `base == "/summary"`; guard `text.strip()`; R8-молчание + INFO-лог с remaining (B8).
- `services/summary_generator.py` (B2/B4/B5): `generate_and_send(chat_id, manual=False)`; константы `_UX_EMPTY`/`_UX_BUSY`; пустое окно / занятый lock → UX (manual) + INFO (cron).
- `handlers/summary.py` (B1/B6/B7/B8/B9): ack «ща гляну, подожди» отдельным `send_message` до пайплайна; `_safe_send(bot)` с DI bot (работает при `_generator is None`); `message.delete()` сразу после ack, try/except → WARNING; INFO-логи всех состояний; наблюдатель не пишет `/summary*` в text и caption.
- **Тесты: 860 PASS / 0 failed** (835 baseline + 25 новых), 0 регрессий.

### 🔍 Ревью (T-196, @Reviewer, 2026-08-16) — APPROVED ✅

- 860 тестов подтверждены личным прогоном; критичных багов нет. Первопричина T-192 закрыта (чужая mention не жжёт слот и проходит мимо троттлинга; своя/без mention троттлится; `base == "/summary"`; guard на пробельный текст).
- Подтверждены: **J1** (DI bot вместо `setup_summary`), **J2** (нет bot в data → своя mention), **J3** (ассерты DeleteMessage), **J4** (FakeLock), **J5** (B9 и caption). `Bot.me()` кэшируется aiogram — 1 вызов на процесс.
- R8/R9 сохранены: троттлинг молчалив (INFO+remaining), denied — без ack/delete/ответа (INFO).

| # | Low-замечание (не блокирует, на T-198/будущий эпик) | Статус |
|---|------------------------------------------------|--------|
| L1 | Мидлварь проверяет только `event.text` — команда-капшн может обойти троттлинг | ⚠️ pre-existing (с Epic 24), сериализуется Lock, на будущее |
| L2 | «ack sent» логируется даже при неудачной отправке ack | ⚠️ косметика |
| L3 | `bot.me()` в мидлвари без try/except | ⚠️ на будущее |
| L4 | `_last` растёт без TTL | ⚠️ pre-existing |

### 📋 Статусы задач

- **board.md:** T-192/T-193/T-194/T-195/T-196 ✅ Done. **T-197 (коммит на русском + push) / T-198 (деплой + верификация /summary живьём) → READY FOR @DevOps.**
- ⚠️ **Деплойный риск для DevOps:** удаление чужих сообщений (B7) требует админ-права `delete_messages` у бота в чате (иначе 400 Bad Request → WARNING-лог, best-effort).

### Журнал Epic 25

| Шаг | Дата | Событие |
|-----|------|---------|
| Шаг 0 | 2026-08-16 | @Memory context sync по баг-репорту («/summary не реагирует» + требование удаления команды) |
| Шаг 1 | 2026-08-16 | @PM: задачи T-192/T-193 |
| Шаг 2 | 2026-08-16 | @Architect: T-192 RCA по прод-логам (первопричина подтверждена) + T-193 Section 34 (B1–B9) |
| Шаг 3 | 2026-08-16 | @Memory: граф знаний + MEMORY.md обновлены (RCA DONE + DESIGN APPROVED) → Builder |
| Шаг 4 | 2026-08-16 | @Builder: T-194/T-195 — B1–B9 реализованы (summary_throttling.py / summary_generator.py / handlers/summary.py), 860 тестов PASS (835+25), 0 регрессий |
| Шаг 5 | 2026-08-16 | @Reviewer: T-196 — APPROVED, 860 тестов подтверждены лично, J1–J5 подтверждены, 4 Low-замечания |
| Шаг 6 | 2026-08-16 | @Memory: граф знаний + MEMORY.md обновлены (IMPLEMENTED + REVIEW PASSED) → @DevOps (T-197/T-198) |

---

## ✅ Epic 24: SmartModule — сервис Summary (v2.22.0) — DEPLOYED (2026-08-16)

> **Запрос пользователя (2026-08-16):** спроектировать и реализовать автономный сервис
> **SmartModule** с подсервисом **Summary** для существующего бота. Все требования обязательные.
> **Статус (2026-08-16):** Шаг 1 (PM) ✅ → Шаг 2 (@Architect, T-173) ✅ → Шаг 4 (@Builder, T-174–T-188 A/B/C) ✅ →
> Шаг 5 (@Reviewer, T-188-D: **APPROVE WITH FIXES → Approved**) ✅ → Шаг 7 (@DevOps, T-190/T-191) ✅ → Шаг 8 (@Memory, финал) ✅.
> **Epic 24 DEPLOYED: прод v2.22.0 (PID 920105).**
> **Тесты: 835 PASS / 0 failed** (672 baseline + 163 новых; 830 после ревью + правки T-189).
> **Файлы:** CREATE `services/llm_client.py`, `summary_prompts.py`, `summary_aliases.py`, `summary_xml.py`,
> `summary_memory.py`, `summary_generator.py`, `summary_scheduler.py`, `summary_throttling.py`,
> `handlers/summary.py`; MODIFY `config/settings.py` (+24 поля), `services/database.py` (_SCHEMA_SQL + 11 методов),
> `bot.py` (роутеры 0a/0b + wiring on_startup/on_shutdown), `requirements.txt` (httpx, APScheduler 3.x, sqlite-vec),
> `.env.example`; локальный `.env` с реальным LLM_API_KEY (gitignored — в коммит не попадёт).
> **Ревью-фиксы (T-188-D):** (1) bot.py on_shutdown → `await _summary_service.shutdown()` (была не-awaited корутина, High);
> (2) summary_memory.py `_purge_archive`: DELETE по rowid IN вместо fact_id IN (документированная vec0-форма);
> (3) +1 QA-тест `test_vec_purge_removes_vectors`.
> **Завершение:** T-189 (README/доки + фиксы Low-замечаний) ✅ → T-190 (коммит `a68732c` + пуш) ✅ → T-191 (деплой, PID 920105) ✅.
> **Осталось пользователю (вручную):** Н1 — BotFather `/setprivacy` → Disable; живая проверка `/summary` в чате.
> **Критично (пост-деплой, вручную):** риск **Н1** — BotFather `/setprivacy` → **Disable** обязателен (иначе память L1/L2/L3 пустая). Через SSH невыполнимо.

### Подтверждённые технические решения (реализация + реальные тесты, 2026-08-16)

- **sqlite-vec 0.1.9 работает на Windows/Py3.12** — реальные тесты без skip.
- **vec0 0.1.x не поддерживает WHERE по auxiliary-колонкам в KNN** → фильтр чата в Python.
- **FTS5 unicode61 + свой префиксный поиск** с санитайзом `*` и `"`.
- **APScheduler 3.11 требует tz в CronTrigger**; shutdown(wait=False) + asyncio.sleep(0).
- **Латентный баг дизайна 33.7 ИСПРАВЛЕН:** `{username}` подставляется литералом, `{max_symbols}` — через `.replace()` (str.format не вызывается).
- Наблюдатель через `@router.message()` без фильтра; медиа без caption сохраняются ([фото]/[видео]), чистые сервисные пропускаются; удаление пачки по ids после успешного сжатия; `SUMMARY_CHUNK_DELAY=2.0`.
- Живой smoke apinet.cloud ✅ на проде (T-191-D): curl apinet.cloud/v1/models → валидный список моделей (auth по ключу принята).

### Low-замечания ревьюера (закрыты в T-189)

| # | Замечание | Статус (T-189) |
|---|-----------|----------------|
| L1 | XML-экранирование l2/l3-блоков (`<memory>`/`<facts>`) не реализовано | ✅ FIXED — `escape_xml_text` для `<memory>`/`<facts>` |
| L2 | Троттлинг не ловит `/summary@BotName` (команда с упоминанием бота) | ✅ FIXED — троттлинг ловит `/summary@BotName` + тесты |
| L3 | Нет жёсткого капа чанков по MAX_SUMMARY_PARTS | ⚠️ Задокументирован в README (осознанный лимит) |
| L4 | location/contact/dice классифицируются как `other` и не сохраняются | ⚠️ Задокументирован в README |

### Суть запроса (кратко)

| # | Требование |
|---|-----------|
| R1 | SQLite (aiosqlite): таблица `smart_messages` — id, user_id, chat_id, text, reply_to_id, timestamp, media_type |
| R2 | Трёхуровневая память: L1 окно 6ч (один проход) → L2 полная `FULL_MEMORY_RETENTION_DAYS` (RAG-цитаты) → L3 архив sqlite-vec (суммаризация→векторы, KNN, `ARCHIVE_MEMORY_RETENTION_DAYS`) |
| R3 | Фоллбек: sqlite-vec недоступен ИЛИ эмбеддинги падают → **FTS5**; try-except вокруг всех вызовов эмбеддингов |
| R4/R5 | LLM через **apinet.cloud**: генерация `deepseek-v4-flash`, эмбеддинги `gemini-embedding-001`; .env: LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME |
| R6 | XML-контекст: `<chat_history><message id timestamp author reply_to_id type>…</message></chat_history>` |
| R7 | Алиасы: каскад `alias → nickname → username (без @) → user_id` |
| R8 | APScheduler: TZ Asia/Yekaterinburg, 00:00/06:00/12:00/18:00, ТОЛЬКО MemoryJobStore |
| R9/R10 | Ручной `/summary` (ALLOWED_SUMMARY_IDS пуст = всем) + кастомный ThrottlingMiddleware (in-memory, молчаливый) |
| R11 | Системный промпт — захардкодить ДОСЛОВНО: токсичный «бот-абьюзер», маленькие буквы, без эмодзи/маркдауна, приписка «самым главным шизом объявляется {username}» (текст в backlog.md) |
| R12/R13 | `{max_symbols} = (MAX_SUMMARY_PARTS*4000)-200`; чанкинг по пробелам ≤4096; UX-ошибки на маленькой букве («не смог сделать саммари потому что упал апи», «база данных подавилась») |
| R14–R17 | Better Stack observability (стектрейсы, сырые ответы LLM); тесты + README ироничный; коммит на русском; деплой SSH nik@198.46.175.136 (/var/www/admin_bot, git pull, systemctl restart adminbot); LLM_API_KEY в .env НЕ коммитим |

### Архитектурные решения A1–A15 (Section 33, @Architect, 2026-08-16)

| # | Решение |
|---|---------|
| **A1** | Плоские модули `services/summary_*.py` + `handlers/summary.py` (НЕ подпакет `smartmodule/`) |
| **A2** | Общая `local_database.db` + миграции `_SCHEMA_SQL` (отдельный smartmodule.db отклонён) |
| **A3** | `summary_observer_router` на позиции **0a** (catch-all, всегда `UNHANDLED`) |
| **A4** | `summary_router` на позиции **0b** (ДО admin/catch-all 5/6, никогда не `UNHANDLED`) |
| **A5** | L3-сжатие — шаг пайплайна под общим `asyncio.Lock`, отдельной джобы APScheduler НЕТ |
| **A6** | Каскад памяти vec0 KNN → FTS5; факты архива пишутся в текст ВСЕГДА |
| **A7** | L2-RAG — FTS5 keyword/phrase-поиск из токенов L1 (без доп. LLM-вызова) |
| **A8** | Имена резолвятся в момент сохранения в `author_name` (alias → nickname → username → user_id) |
| **A9** | `SUMMARY_ALIASES` — JSON-строка `{"<user_id>": "<alias>"}` |
| **A10** | Промпты в `services/summary_prompts.py` (SYSTEM_PROMPT дословно, R11) |
| **A11** | `/summary` из чата НЕ удаляется |
| **A12** | Деплой-нота: BotFather `/setprivacy` → **Disable** (иначе память пустая — риск **Н1**) |
| **A13** | Зависимости: `httpx>=0.27`, `APScheduler>=3.10,<4`, `sqlite-vec>=0.1.2` (graceful fallback) |
| **A14** | Постобработка: чанкинг ≤4096 по пробелам + автодописывание шиз-приписки |
| **A15** | Throttling — router-scoped outer middleware только на `summary_router` (key chat+user, TTL 60s, молчаливый return) |

**Структура файлов (Section 33.2):** `services/llm_client.py`, `summary_memory.py`,
`summary_xml.py`, `summary_aliases.py`, `summary_generator.py`, `summary_scheduler.py`,
`summary_throttling.py`, `summary_prompts.py`, `handlers/summary.py` (+ точечные правки
`config/settings.py` +18 полей, `services/database.py`, `bot.py`, `.env.example`).

**БД (Section 33.3):** `smart_messages` (+author_name), FTS5 `smart_messages_fts`,
`smart_archive_facts` (+FTS5), vec0 `smart_archive` (лениво, только при загруженном sqlite-vec).

**LLM (Section 33.4):** одна httpx-сессия, `/v1/chat/completions` + `/v1/embeddings`,
retry 429/5xx с backoff, иерархия LLMError; `embed()` оборачивается try/except у вызывающего.

**Критичный риск Н1:** BotFather `/setprivacy` → **Disable** обязателен на проде (T-191) —
иначе бот в группе не видит сообщения, память L1/L2/L3 пустая.

### Финальный деплой-дайджест (T-190/T-191 DONE, 2026-08-16)

1. **T-190 ✅:** локальный прогон **835 тестов PASS**; коммит `a68732c` «feat(summary): Epic 24 — SmartModule с трехуровневой памятью и саммари чата (v2.22.0)» — 35 файлов, +4495/−28 (включая медиа leha_greeting_18-21.mp4 и olya_cringe-03.mp4, проверены); пуш master ✅ (c093de7..a68732c); docs-коммит `818e195` (синхронизация board.md) ✅; локальный HEAD = origin/master, дерево чистое; `.env` не коммичен.
2. **T-191 ✅:** прод 198.46.175.136 (/var/www/admin_bot): git pull ff `756d237..a68732c`; prod `.env` +LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME/SUMMARY_TIMEZONE (без дублей); venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1; smoke **T-191-D ✅** — curl apinet.cloud/v1/models → валидный список моделей; рестарт → active (running), PID 920105; логи чистые: «sqlite-vec loaded (dim=768)», «SmartModule Summary (Epic 24) initialized (TZ=Asia/Yekaterinburg)», cron 0,6,12,18, все 14 роутеров, трейсбеков нет.
3. **Наблюдение:** старый процесс v2.21.0 (PID 917681) завис в shutdown ~90с и был SIGKILLнут systemd — поведение старого кода; новый v2.22.0 стартует чисто.
4. **Н1 (критично, ВРУЧНУЮ пользователем — не через SSH):** BotFather `/setprivacy` → **Disable** — иначе бот в группе не видит сообщения, память L1/L2/L3 пустая. Плюс живая проверка `/summary` в чате.
5. **Политика media/** (соблюдена): медиа добавлены сознательно (leha_greeting_18-21.mp4, olya_cringe-03.mp4), закоммичены, НЕ в .gitignore, НЕ удалены.

### Baseline перед стартом Epic 24

- Прод **v2.21.0** (коммит `756d237`), бот active (PID 917681), 0 ошибок.
- **672 теста** локально; 12 роутеров (0:admin → 1:slava_presence → 1b:alan_greeting → 2:kostik → 3:alan → 4:dead_page → 4b:war_alert → 4c:common → 4d:olya → 5:slavik → 6:vasya); 5 таблиц БД.
- requirements.txt: aiogram 3.7+, python-dotenv, aiosqlite, pytest(+asyncio), sentry-sdk 2.64.0, logtail-python 0.4.0 (LLM/sqlite-vec/APScheduler/httpx отсутствуют — будут добавлены).
- Сервер: 198.46.175.136:/var/www/admin_bot, сервис adminbot (systemctl).

---

## 🔍 Context Sync Summary (2026-08-15) — Epic 22 DONE & DEPLOYED, v2.20.0 в продакшене

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-21** | ✅ DEPLOYED | 160+ задач T-001–T-162 + T2/T3/T4 + Epic 18 A/B/C. v2.19.0 (commit c683903) был в продакшене до 2026-08-15. |
| **Epic 22** | ✅ DONE & DEPLOYED | «Гонка функций и точность триггеров» — PM-решения D51–D54, T-163..T-167 (включая D) завершены. 621 тест PASS (+35 новых). Коммит `1dbb6da`, пуш, деплой. Прод v2.20.0. |
| **Review (current)** | ✅ APPROVED | 621 tests pass / 0 failed. 3 раунда ревью, все замечания закрыты (README v2.20.0/621, планы IMPLEMENTED, board «In Review»). |
| **Сервер** | ✅ ACTIVE | 198.46.175.136:/var/www/admin_bot. systemctl: active (running), PID 914116 (был 699945). Логи чистые (Bot started, listening...). HEAD=1dbb6da. |

---

## 📁 Политика media/ (по указанию пользователя, 2026-08-16) — ОБЯЗАТЕЛЬНА К ИСПОЛНЕНИЮ

> **Всё, что добавляется или удаляется в папке `media/` (`media/common/danger`, `media/olya/cringe`, `media/slavik_random` и т.п.), — делается СОЗНАТЕЛЬНО и СПЕЦИАЛЬНО для загрузки на сервер и дальнейшего использования ботом.**

- Media-файлы **НЕ являются случайными артефактами**: их НЕЛЬЗЯ исключать из коммитов как мусор, НЕЛЬЗЯ добавлять в `.gitignore`, НЕЛЬЗЯ удалять без явного указания пользователя.
- ❌ Рекомендация «добавить `danger_drone.mp4` в `.gitignore`» была **ОШИБОЧНОЙ и ОТМЕНЯЕТСЯ**.
- ✅ `media/common/danger/danger_drone.mp4` — **16-й файл danger-пула**, добавлен намеренно: его нужно **закоммитить и задеплоить**. Пул danger-медиа используется сервисом danger-слов (DangerWordFilter → CommonRelay), media_picker выбирает файлы из папки автоматически — дополнительный код не требуется.

---

## 🚧 Epic 22: Гонка функций и точность триггеров — v2.20.0 (DONE & DEPLOYED, 2026-08-15)

> **Цель:** Устранить гонку ответов Славика (приветствие vs dead page vs «пошёл нахуй»),
> сделать триггеры точнее: Olya — только SaveAsBot-видео, mimic — не передразнивать репосты,
> PostPicker — не выбирать пост, отправленный в предыдущий раз.
> **Статус:** DONE & DEPLOYED ✅ — T-163..T-167 (A/B/C/D) завершены, ревью 3 раунда (замечания закрыты), 621 тест PASS, 0 регрессий.
> Коммит `1dbb6da` на master, пуш в origin, деплой на 198.46.175.136:/var/www/admin_bot (git pull c683903..1dbb6da, 21 файл, +1778/-224, systemctl restart OK, PID 914116). Прод v2.20.0.
> **Target (достигнут):** v2.20.0, 621 тест (586 baseline + 35 новых), 0 регрессий.

### PM-решения D51–D54

| # | Решение | Задача | Суть |
|---|---------|--------|------|
| **D51** | Olya SaveAsBot-only | T-163 | Логика **ИЛИ** сохраняется (caption ИЛИ репост из `OLYA_SAVEASBOT_CHANNEL_IDS`=523131145). Дефолт `OLYA_ALWAYS_SEND` True→**False**. ⚠️ prod .env может содержать `OLYA_ALWAYS_SEND=True`. |
| **D52** | Mimic forwards gate | T-164 | Единый параметр **`MIMIC_FORWARDS_ENABLED=False`** для ОБОИХ mimic-механизмов (`handlers/common.py::mimic_handler`, `handlers/slavik.py::_slavik_mimic_should_trigger`). `forward_origin is not None` + off → mimic пропущен. |
| **D53** | Slavik race fix | T-165 | `DEAD_PAGE_POST_ON_JOIN=False` (join → только «ДОЛБОЕБ ВЕРНУЛСЯ»); dead_page_trigger — только репосты Славы (`UserIdFilter`, is_present-гейт убран); catch-all Branch 0 гейт: d_pages-репост → `UNHANDLED`. Приоритет: приветствие > dead page > «пошёл нахуй». |
| **D54** | PostPicker last-sent | T-166 | Ключ `channel_state` **`dead_page_last_sent:{chat_id}`** (≠ `last_known_message_id`). last_sent исключается из forward/sequential/random веток; fallback-повтор при единственном посте; запись primary msg_id после успеха. Фикс бага «почти всегда id 3». |

### Задачи Epic 22

| Task | Название | Компоненты | Статус |
|------|----------|-----------|--------|
| **T-163** | Olya: только SaveAsBot-видео (D51) | config/settings.py, .env.example, tests/test_olya.py | ✅ DONE (APPROVED) |
| **T-164** | Mimic: не передразнивать репосты (D52) | config/settings.py, handlers/common.py, handlers/slavik.py | ✅ DONE (APPROVED) |
| **T-165** | Славик: приоритет приветствия + dead page на репосты Славы (D53) | handlers/dead_page_trigger.py, handlers/slavik.py, tests/test_slavik_priority.py (NEW) | ✅ DONE (APPROVED) |
| **T-166** | PostPicker: не выбирать last-sent пост (D54) | services/database.py, services/dead_page_relay.py | ✅ DONE (APPROVED) |
| **T-167** | README (ироничный тон), полный pytest (621), conventional commit на русском | README/ARCHITECTURE/MEMORY | ✅ A/B/C/D DONE (APPROVED + DEPLOYED, коммит `1dbb6da`) |

### Ключевой API-контекст (Section 30.2)

- aiogram 3.x `message.forward_origin`: **None** для обычных сообщений, `MessageOriginChannel` для репостов из каналов (`origin.chat.id` — канал-источник); legacy `forward_from*` deprecated (Bot API 7.0).
- MagicMock gotcha: атрибуты автогенерируются и truthy — тестовые фабрики должны явно выставлять `msg.forward_origin = None`; гейты mock-safe через `isinstance`.
- `forwardMessage(s)` — `Bad Request: message to forward not found` = штатный признак отсутствующего пробного id → `continue`.

### Риски миграции (Section 30.9)

| # | Риск | Митигация |
|---|------|-----------|
| R1 | Prod `.env` с явными `OLYA_ALWAYS_SEND=True` / `DEAD_PAGE_POST_ON_JOIN=True` | Деплой-чеклист DevOps |
| R2 | Контракт `_try_forward_from_channel: bool → int\|None` | 9 assertion-строк в тестах обновляются в T-166 |
| R5 | Sequential scan «всегда id 3» | skip last_sent; при единственном посте — осознанный повтор |
| R7 | Миграция БД | Не нужна — переиспользуется `channel_state` |

### Результаты ревью — 3 раунда, APPROVED ✅

- 621 тест PASS / 0 failed (+35 новых: `tests/test_slavik_priority.py` NEW, классы `TestMimicForwardsGate`, `TestAntiRepeatLastSent` и др.).
- Флаки-тест `test_sequential_scan_finds_only_post` детерминирован патчем `random.randint` (side_effect [77..86], 25/25 PASS).
- Все замечания закрыты: README v2.20.0/621, статусы планов IMPLEMENTED, board «In Review», нумерация T-167 выровнена.
- Наблюдения ревьюера (не блокеры): README пишет «ДОЛБОЕВ» vs планы «ДОЛБОЕБ»; фактическая ветка — master.
- ✅ Деплой-чеклист DevOps выполнен (2026-08-15): prod `.env` → `DEAD_PAGE_POST_ON_JOIN=False` (True→False, бэкап `.env.bak.2026-08-15`); `OLYA_ALWAYS_SEND` и `MIMIC_FORWARDS_ENABLED` отсутствуют в .env — активны дефолты False.
- ❌→✅ `media/common/danger/danger_drone.mp4` — **ОТМЕНЕНО пользователем (2026-08-16):** рекомендация «добавить в `.gitignore`» была ошибочной. Файл добавлен НАМЕРЕННО (16-й файл danger-пула) → должен быть ЗАКОММИЧЕН и ЗАДЕПЛОЕН.

---

## ✅ Epic 23: Правка danger-словаря — v2.21.0 (DONE & DEPLOYED, 2026-08-16)

> **Цель:** Сократить и уточнить danger-словарь: убрать «шумные» секции, добавить фразовые шаблоны (shelter/атака), сохранить совместимость `{"matched_word"}`.
> **Статус (2026-08-16):** DONE & DEPLOYED ✅ — T-169..T-172 DONE (включая деплойные подзадачи E..G), **672 теста PASS** (621 baseline + 51 новых), ревью 2 раунда APPROVED. Деплой: git pull `0c74220..756d237` (9 файлов) на 198.46.175.136:/var/www/admin_bot; `.env` DANGER_WORDS пустой → дефолты активны; проверка «118 17» совпала; systemctl active (running) PID 917681; логи чистые. **Прод v2.21.0.**

### Факты реализации

| Параметр | Было | Стало |
|----------|------|-------|
| **DANGER_WORDS** | 191 словоформа | **118** (удалены Flight, Shelter, Атака/угроза, Падение/сбитие; добавлены хлопок/хлопки/хлопнуло/хлопнул) |
| **DANGER_PHRASES** | — | **17 фраз**: 10 shelter + 7 атака, longest-first |
| **Итого паттернов** | 191 | **135** (118 слов + 17 фраз) |

### Механика (D55–D58)

- `_build_phrase_patterns` в `DangerWordFilter` (filters/danger_word.py): фразы проверяются **ДО** слов, границы по краям фразы, `re.IGNORECASE`.
- Возврат `{"matched_word": ...}` **совместимый** — Telegram quote API не сломан.
- **Env-независимо:** дефолты в `filters/word_lists.py`; `DANGER_WORDS` env var — только опциональный override. Прод `.env` НЕ трогаем.
- Потребители: `war_alert` (роутер 4b) и `danger_handler` (роутер 4c) — единый словарь.

### Тесты — 672 PASS / 0 failed

- **672** = 621 baseline + 51 новых.
- Переписаны/добавлены: `TestDangerPhrases` (**42 кейса**), контрактный тест (**17 фраз**), негативы.
- Ревью: 2 раунда, APPROVED ✅ (2 фикса тестов выполнены дословно).

### Задачи Epic 23

| Task | Название | Статус |
|------|----------|--------|
| **T-169** | Правка DANGER_WORDS в filters/word_lists.py (191→118) | ✅ DONE + APPROVED |
| **T-170** | DANGER_PHRASES (17 фраз) в filters/word_lists.py | ✅ DONE + APPROVED |
| **T-171** | `_build_phrase_patterns` + тесты (TestDangerPhrases 42 кейса, контракт 17 фраз) | ✅ DONE + APPROVED |
| **T-172** | README/планы + коммит + деплой v2.21.0 | ✅ DONE & DEPLOYED (E..G закрыты, коммит `756d237`, PID 917681) |

---

## 🔍 Context Sync Summary (2026-08-03) — Epic 21 DEPLOYED ✅

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-20** | ✅ DEPLOYED | 130+ задач T-001–T-148 + T2/T3/T4 + Epic 18 A/B/C + Epic 19 + Epic 20. v2.18.0 в продакшене. |
| **Epic 21** | ✅ DEPLOYED | MIMIC propagation fix + Time-format cooldowns. 14 задач T-149–T-162. D49 + D50. Commit c683903. |
| **Review** | ✅ PASS | 586 tests pass. 0 failures. Zero regressions. |
| **Сервер** | ✅ ACTIVE | nik@198.46.175.136:/var/www/admin_bot. systemctl: active (running), PID 699945, 121.6M. |
| **DevOps (T-162)** | ✅ DEPLOYED | Commit c683903, push origin/master, server pull + restart successful. Zero errors in logs. |

---

## ✅ Epic 21: MIMIC Propagation Fix + Time-Format Cooldowns — v2.19.0 (DEPLOYED, 2026-08-03)

> **Цель:** Исправить propagation-блокировку в `alan_handler` (MIMIC не работал для Alan) и перевести все кулдауны на человекочитаемый time-format (1s/1m/1h/1d).
> **Статус:** DEPLOYED ✅ — все 14 задач T-149–T-162 выполнены и задеплоены в production. 586 тестов проходят.
> **Версия:** v2.19.0 (деплой на сервер выполнен).
> **Коммит:** `c683903` на master, пуш в origin/master.
> **Сервер:** nik@198.46.175.136:/var/www/admin_bot, PID 699945, active (running), 121.6M.

### Root Cause: alan_handler blocks propagation

```
Alan (138811255) пишет сообщение в чат
    ↓
alan_router (pos 3): UserIdFilter matches → alan_handler()
    → считает сообщение, возможно делает reply
    → implicit return None ← БЛОКИРУЕТ propagation
    ↓
common_router (pos 4c): НИКОГДА не получает события
    → mimic_handler НЕ срабатывает (MIMIC сломан для Alan)
    → danger_handler / otboy_handler тоже не получают
```

**SLAVIK_MIMIC НЕ затронут** — он изолирован в `slavik_router` (позиция 5), который получает события независимо от `alan_router`.

### Design Decisions — IMPLEMENTED

| # | Решение | Описание | Статус |
|---|---------|----------|--------|
| **D49** | return UNHANDLED в alan_handler | Добавить `from aiogram.dispatcher.event.bases import UNHANDLED` + `return UNHANDLED` в конце `alan_handler()` И в ранних return (строки 84, 89). 1 файл (`handlers/alan.py`), 3 строки изменения. | ✅ IMPLEMENTED |
| **D50** | Time-format cooldowns | Новые хелперы `_parse_duration()` и `_env_duration()` в `config/settings.py`. Поддерживаемые форматы: `1s`, `30s`, `1m`, `5m`, `1h`, `2h`, `1d`, `0`. Переименование 6 полей: `*_COOLDOWN_SECONDS` → `*_COOLDOWN`. Backward-compat через fallback для plain integer значений. | ✅ IMPLEMENTED |

### Cooldown Renames — COMPLETED

| Старое имя | Новое имя | Новый Default | Было |
|-----------|----------|---------------|------|
| `MIMIC_COOLDOWN_SECONDS` | `MIMIC_COOLDOWN` | `"1h"` (3600s) | `60.0` |
| `SLAVIK_MIMIC_COOLDOWN_SECONDS` | `SLAVIK_MIMIC_COOLDOWN` | `"60s"` (60s) | `60.0` |
| `COMMON_COOLDOWN_SECONDS` | `COMMON_COOLDOWN` | `"0"` (disabled) | `0` |
| `DEAD_PAGE_COOLDOWN_SECONDS` | `DEAD_PAGE_COOLDOWN` | `"10s"` (10s) | `10` |
| `DANGER_COOLDOWN_SECONDS` | `DANGER_COOLDOWN` | `"60s"` (60s) | `60.0` |
| `OLYA_COOLDOWN_SECONDS` | `OLYA_COOLDOWN` | `"60s"` (60s) | `60.0` |

### Tasks Epic 21 — IMPLEMENTED

| Task | Название | Компонент | Статус |
|------|----------|-----------|--------|
| **T-149** | MIMIC propagation fix — `return UNHANDLED` в `alan_handler` (3 места: line 84, 89, end) | `handlers/alan.py` | ✅ IMPLEMENTED |
| **T-150** | Создать `_parse_duration()` и `_env_duration()` хелперы | `config/settings.py` | ✅ IMPLEMENTED |
| **T-151** | Переименовать 6 cooldown полей в Settings dataclass | `config/settings.py` | ✅ IMPLEMENTED |
| **T-152** | Обновить `bot.py` — переименовать вызовы `settings.*_COOLDOWN` | `bot.py` | ✅ IMPLEMENTED |
| **T-153** | Обновить `handlers/slavik.py` — `SLAVIK_MIMIC_COOLDOWN` | `handlers/slavik.py` | ✅ IMPLEMENTED |
| **T-154** | Обновить `services/dead_page_relay.py` — `DEAD_PAGE_COOLDOWN` | `services/dead_page_relay.py` | ✅ IMPLEMENTED |
| **T-155** | Verify mimic_relay + common_relay — без внутренних изменений | `services/*.py` | ✅ IMPLEMENTED (verified, no changes) |
| **T-156** | Добавить тест UNHANDLED в `alan_handler` | `tests/test_alan.py` | ✅ IMPLEMENTED |
| **T-157** | Обновить `.env.example` — time-format defaults | `.env.example` | ✅ IMPLEMENTED |
| **T-158** | Создать `tests/test_duration.py` — 15 test cases | `tests/test_duration.py` (NEW) | ✅ IMPLEMENTED |
| **T-159** | Полный прогон тестов — 586 tests PASS, 0 failures | `pytest` | ✅ IMPLEMENTED |
| **T-160** | Обновить `README.md` — version v2.19.0, config table, 586 tests | `README.md` | ✅ IMPLEMENTED |
| **T-161** | Sync MEMORY.md — Epic 21 completion status | `plans/` | ✅ IMPLEMENTED |
| **T-162** | Commit, push, deploy | DevOps | ✅ DEPLOYED (commit c683903, server: PID 699945) |

### Reviewer Audit — 3 Issues Found, ALL FIXED

| # | Severity | Описание | Файл | Status |
|---|----------|----------|------|--------|
| **1** | HIGH | `.env` line 26: `DEAD_PAGE_COOLDOWN_SECONDS=0` → `DEAD_PAGE_COOLDOWN=0` (старое имя поля) | `.env` | ✅ FIXED |
| **2** | HIGH | `handlers/alan.py` lines 84, 89: Early returns `return` → `return UNHANDLED` (блокировали propagation на ранних выходах) | `handlers/alan.py` | ✅ FIXED |
| **3** | MEDIUM | `.env`: Missing new cooldown variables (COMMON_COOLDOWN, DANGER_COOLDOWN, MIMIC_COOLDOWN, SLAVIK_MIMIC_COOLDOWN, OLYA_COOLDOWN) | `.env` | ✅ FIXED |

### Affected Files — IMPLEMENTED

| Файл | Тип | Изменения |
|------|-----|-----------|
| `config/settings.py` | MODIFY | +2 хелпера (`_parse_duration`, `_env_duration`), 6 переименований полей, тип float→str |
| `handlers/alan.py` | MODIFY | +import UNHANDLED, +return UNHANDLED (3 строки: lines 84, 89, end) |
| `bot.py` | MODIFY | ~6 строк переименований `*_COOLDOWN_SECONDS` → `*_COOLDOWN` |
| `handlers/slavik.py` | MODIFY | 1 строка переименования `SLAVIK_MIMIC_COOLDOWN` |
| `services/dead_page_relay.py` | MODIFY | 2 строки переименования `DEAD_PAGE_COOLDOWN` |
| `services/mimic_relay.py` | VERIFIED | БЕЗ ИЗМЕНЕНИЙ — внутренние параметры `cooldown_seconds` не переименованы |
| `services/common_relay.py` | VERIFIED | БЕЗ ИЗМЕНЕНИЙ — внутренние параметры `cooldown_seconds`/`danger_cooldown_seconds` не переименованы |
| `.env.example` | MODIFY | 6 переменных переименованы с time-format значениями + комментарий |
| `.env` | MODIFY | Reviewer fixes: DEAD_PAGE_COOLDOWN + missing vars |
| `README.md` | MODIFY | v2.19.0, config table sync, 586 tests |
| `tests/test_alan.py` | MODIFY | +1 тест (UNHANDLED return) |
| `tests/test_duration.py` | **CREATE** | 15 тестов `_parse_duration` + `_env_duration` |

### Test Suite (586 total)

| Area | Count | Delta |
|------|-------|-------|
| Baseline (Epic 20 deployed) | 570 | — |
| Epic 21: test_alan.py (UNHANDLED) | +1 | T-156 |
| Epic 21: test_duration.py (NEW) | +15 | T-158 |
| **Total** | **586** | **+16 net** |

### Architectural Decisions Summary

| # | Решение | Описание | Статус |
|---|---------|----------|--------|
| **D49** | return UNHANDLED in alan_handler | 3 return paths updated (end + 2 early returns). Propagation restored. | ✅ IMPLEMENTED |
| **D50** | Time-format cooldowns | `_parse_duration`(s/m/h/d) + `_env_duration` with backward-compat. 6 fields renamed. | ✅ IMPLEMENTED |

---

## 📋 Project Overview

**AdminBot** — юмористический Telegram-бот для личного чата трёх друзей (Слава, Костик, Вася).  
Написан на **Python** с использованием **aiogram 3.x**. Работает через long-polling.

### Стек
| Компонент | Технология | Статус |
|-----------|-----------|--------|
| Рантайм | Python 3.x + asyncio | ✅ |
| Фреймворк | aiogram 3.7+ | ✅ |
| База данных | SQLite (local_database.db) | ✅ 9 таблиц после Epic 24 (было 5), WAL mode |
| Конфигурация | .env + config/settings.py | ✅ Все настройки через env, time-format cooldowns |
| Тесты | pytest + pytest-asyncio | ✅ 860 тестов локально PASS (Epic 25 IMPLEMENTED+REVIEWED; прод пока v2.22.0 = 835) |
| Документация | ARCHITECTURE.md, MEMORY.md | ✅ |
| Мониторинг | ✅ Sentry + Logtail | Error tracking + cloud logging via Better Stack |

### Пользователи чата

| Персона | User ID | Прозвище | Роутер |
|---------|--------|----------|--------|
| **Слава (Slavik)** | `479167456` | «Куча» | `handlers/slavik.py` |
| **Костик (Kostik)** | `350803143` | — | `handlers/kostik.py` |
| **Вася (Vasya)** | no ID | — | `handlers/vasya.py` |
| **@Alan_Z** | `138811255` | — | `handlers/alan.py` (F6 + F7v2) + `handlers/alan_greeting.py` (F7) |
| **Admin** | `5885953495` | — | `handlers/admin_commands.py` (Epic 9) |

---

## 🏗️ Key Architectural Decisions

### 1. Router Priority Order (КРИТИЧНО — v2.22.0)
```
0a. summary_observer_router — Epic 24: catch-all сбор ВСЕХ сообщений в память (всегда UNHANDLED)
0b. summary_router — Epic 24: /summary (ДО admin и catch-all 5/6, никогда UNHANDLED) + ThrottlingMiddleware
0.  admin_commands_router (Command filters) — /deadpage, /alangreet
1.  ChatMemberUpdated (slava_presence_router) — F1
1b. ChatMemberUpdated (alan_greeting_router) — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6 + F7v2 silence greeting
    → RETURNS UNHANDLED (D49) — propagation restored for Alan
4.  dead_page_router — Dead Page V2 trigger from @d_pages
4b. war_alert_router — F5v2: war keywords (Slava) + TargetChannelFilter repost detection
4c. common_router — F9/F10: otboy_handler + danger_handler + mimic_handler (ALL users, DUAL cooldown)
4d. olya_router — F11: Olya video trigger (user_id=834424825) + plain send media
5.  slavik_router (user_id=479167456) + middleware F3 + F4 + catch-all + slavik_mimic (F8)
6.  vasya_router (text filters, no user restriction)
```

### 2. Фичи (F1–F11)

| # | Фича | Реализация | Статус |
|---|------|------------|--------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | ✅ |
| **F2** | Dead Page V2: forwardMessage из @d_pages + fallback | `DeadPageRelay` + `DeadPageTrigger` | ✅ |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | ✅ |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` + `KuchaWordFilter` | ✅ |
| **F5v2** | War Words Alert: caption fix, 90+ keywords, TargetChannelFilter, random replies | `handlers/war_alert.py` | ✅ |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` (returns UNHANDLED) | ✅ |
| **F7** | Alan join → random greeting video | `handlers/alan_greeting.py` | ✅ |
| **F7v2** | Alan silence greeting — "Леха проснулся" | `handlers/alan.py` (inlined, returns UNHANDLED) | ✅ |
| **F8** | slavic_na_litso.jpg — каждый N-й "пошёл нахуй" → фото | `handlers/slavik.py` | ✅ |
| **E9** | Admin test commands: /deadpage, /alangreet | `handlers/admin_commands.py` | ✅ |
| **F9** | Otboy Service — детект "отбой" → common/otboy/ media | `handlers/common.py` (otboy_handler) + `CommonRelay` | ✅ |
| **F10** | Danger Detection — 135+ keywords from word_lists.py | `handlers/common.py` (danger_handler) + `DangerWordFilter` + `CommonRelay` (dual cooldown) | ✅ |
| **F11** | Olya Service — видео от @ole4444444ka → cringe media | `handlers/olya.py` + `OlyaRelay` + `OlyaVideoFilter` | ✅ |

### 3. Database Schema (SQLite, 9 tables после Epic 24)

| Таблица | Назначение | Ключевые колонки |
|---------|-----------|-----------------|
| `user_presence` | Присутствие пользователя (F1, F2) | `user_id`, `chat_id`, `is_present` |
| `message_counters` | Счётчик сообщений (F3, F6) | `chat_id`, `user_id`, `count` |
| `dead_page_posts` | Учёт dead-page постов (F2 V2) | `chat_id`, `slot`, `timestamp` |
| `channel_state` | Ключ-значение (F2 V2, F7v2) | `key` (TEXT PK), `value` (TEXT) |
| `relay_album_map` | Трекинг media_group_id для альбомов (Epic 14) | `message_id` (INTEGER PK), `media_group_id` (TEXT, INDEXED) |
| `smart_messages` | Сырые сообщения чата (Epic 24, L1/L2) | `id`, `chat_id`, `user_id`, `author_name`, `text`, `reply_to_id`, `media_type`, `timestamp` |
| `smart_messages_fts` | FTS5-индекс сообщений (L2-RAG) | `text`, content=`smart_messages` |
| `smart_archive_facts` | Факты L3-сжатия (текстовая ветка, ВСЕГДА) | `id`, `chat_id`, `fact`, `timestamp` |
| `smart_archive_facts_fts` | FTS5-индекс фактов (фоллбек L3) | `fact`, content=`smart_archive_facts` |
| `smart_archive` | vec0-векторная ветка L3 (лениво) | `rowid`, `fact_id`, `chat_id`, `embedding float[768]` |

### 4. Config (env-configurable via settings.py, TIME-FORMAT v2.19.0)

| Переменная | По умолчанию | Назначение |
|-----------|-------------|------------|
| `API_TOKEN` | (required) | Telegram Bot Token |
| `SLAVIK_USER_ID` | `479167456` | Slava's Telegram user ID |
| `KOSTIK_USER_ID` | `350803143` | Kostik's Telegram user ID |
| `ALAN_USER_ID` | `138811255` | Alan's Telegram user ID |
| `ALAN_SILENCE_GREETING_HOURS` | `6.0` | F7v2: hours of silence before greeting (prod=2) |
| `ADMIN_USER_ID` | `5885953495` | Admin user ID (Epic 9) |
| `GIF_INTERVAL` | `5` | Send GIF every N messages |
| `GIF_PATH` | `media/slavic_chlen.mp4` | GIF file path |
| `WAR_CHANNEL_IDS` | `1654872411` | War repost detection channel IDs (F5v2) |
| `WAR_CHANNEL_USERNAMES` | `` | War repost detection channel usernames (F5v2) |
| `WAR_REPLIES` | `` | Custom war reply phrases (F5v2) |
| `SLIVIC_NA_LITSO_INTERVAL` | `10` | F8: каждый N-й "пошёл нахуй" → фото |
| `MIMIC_COOLDOWN` | `1h` | F6: MIMIC cooldown (time-format: 1s/1m/1h/1d) ✅ v2.19.0 |
| `SLAVIK_MIMIC_COOLDOWN` | `60s` | F8: Slavik MIMIC cooldown (time-format) ✅ v2.19.0 |
| `COMMON_COOLDOWN` | `0` | F9/F10: shared cooldown for common sub-services (0=off, time-format) ✅ v2.19.0 |
| `DANGER_COOLDOWN` | `60s` | F10: danger-specific cooldown (dual-layer, time-format) ✅ v2.19.0 |
| `DEAD_PAGE_COOLDOWN` | `10s` | F2 V2: dead page relay cooldown (time-format) ✅ v2.19.0 |
| `OLYA_COOLDOWN` | `60s` | F11: Olya service cooldown (time-format) ✅ v2.19.0 |
| `COMMON_MEDIA_BASE` | `media/common` | F9/F10: base directory for common/otboy/ and common/danger/ |
| `DANGER_WORDS` | `(135+ keywords)` | F10: comma-separated danger keywords (единый источник: filters/word_lists.py) |
| `OLYA_ENABLED` | `True` | F11: enable/disable Olya Service (0=off) |
| `OLYA_USER_ID` | `834424825` | F11: Olya's Telegram user ID (@ole4444444ka) |
| `OLYA_MEDIA_BASE` | `media/olya/cringe` | F11: media directory for Olya cringe files |
| `OLYA_CAPTION_TEXT` | `(SaveAsBot text)` | F11: key caption text for Condition A detection |
| `OLYA_SAVEASBOT_CHANNEL_IDS` | `523131145` | F11: channel IDs for SaveAsBot repost detection |
| `OLYA_ALWAYS_SEND` | `False` | F11: always send media regardless of caption/repost match ✅ v2.20.0 IMPLEMENTED (Epic 22 D51: дефолт True→False) |
| `MIMIC_FORWARDS_ENABLED` | `False` | Epic 22 D52 (NEW) ✅ v2.20.0 IMPLEMENTED: mimic только обычные сообщения; True = включая репосты (forward_origin is not None) |
| `DEAD_PAGE_POST_ON_JOIN` | `False` | Epic 22 D53 ✅ v2.20.0 IMPLEMENTED: при входе только «ДОЛБОЕБ ВЕРНУЛСЯ» (dead page на join выключен) |
| `dead_page_last_sent:{chat_id}` | — (channel_state) | Epic 22 D54 ✅ v2.20.0 IMPLEMENTED: anti-repeat ключ БД — PostPicker не выбирает последний отправленный пост |

---

## Previous Completed Epics

| Version | Date | Epic | Tasks | Tests |
|---------|------|------|-------|-------|
| v1.0.0 | 2026-07-07 | Epic 1-4 | T-001–T-017 | 130 |
| v2.0.0 | 2026-07-12 | Epic 6 (Dead Page V2) | T-018–T-028 | 137 |
| v2.1.0 | 2026-07-12 | Epic 7 (Monitoring) | T-029–T-037 | 146 |
| v2.2.0 | 2026-07-13 | Epic 8 (F7 Alan Greeting) | T-038–T-045 | 164 |
| v2.3.0 | 2026-07-14 | Bugfixes T-046–T-047 | T-046–T-047 | 32 |
| v2.4.0 | 2026-07-14 | Epic 9 (Admin Commands) | T-048–T-051 | 181 |
| v2.5.0 | 2026-07-14 | T-052 (Sequential Scan) | T-052 | 185 |
| v2.6.0 | 2026-07-15 | T-053 (Propagation Fix) | T-053 | 190 |
| v2.7.0 | 2026-07-16 | Epic 10 (F5v2 War Words) | T-054–T-063 | 252 |
| v2.8.0 | 2026-07-18 | Epic 11 (F7v2) | T-064–T-077 | 271 |
| v2.9.2 | 2026-07-26 | Epic 12 (F8) | T-078–T-083 | 280 |
| v2.10.0 | 2026-07-26 | Epic 13 (F9 Otboy) | T-084–T-092 | 305 |
| v2.11.0 | 2026-07-28 | Epic 14 (Album Fix) | T-093–T-099 | 316 |
| v2.12.0 | 2026-07-28 | Epic 15 (Common Service) | T-100–T-107 | 372 |
| v2.12.1 | 2026-07-29 | Epic 16 (Bug Fixes) | T-109–T-115 | 387 |
| v2.13.0 | 2026-07-30 | Epic 17 (Danger Word Fix) | T2–T4 | 399 |
| v2.15.0 | 2026-08-02 | 4 Major Fixes | — | 458 |
| v2.16.0 | 2026-08-02 | Epic 18 (Danger Service Fixes) | A/B/C | 478 |
| v2.17.0 | 2026-08-02 | Epic 19 (Olya Service) | T-131–T-138 | 509 |
| v2.18.0 | 2026-08-02 | Epic 20 (Slavik Random Media) | T-139–T-148 | 570 |
| **v2.19.0** | **2026-08-03** | **Epic 21 (MIMIC fix + Time-format cooldowns)** | **T-149–T-162** | **586** |
| **v2.20.0** | **2026-08-15** | **Epic 22 (Гонка функций и точность триггеров)** | **T-163–T-167 (DEPLOYED, `1dbb6da`)** | **621** |
| **v2.21.0** | **2026-08-16** | **Epic 23 (Правка danger-словаря)** | **T-169–T-172 (DONE & DEPLOYED, `756d237`)** | **672** |
| **v2.22.0** | **2026-08-16** | **Epic 24 (SmartModule: Summary)** | **T-173–T-191 (DONE & DEPLOYED, `a68732c` + `818e195`)** | **835** |
| **v2.22.1 (in work)** | **2026-08-16** | **Epic 25 (багфикс /summary + удаление команды)** | **T-192–T-198 (5/7 Done: IMPLEMENTED + REVIEW PASSED; T-197/T-198 → @DevOps)** | **860** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **DEPLOYED** | T-001 – T-148 + T2/T3/T4 + v2.15.0 fixes + Epic 18 A/B/C (DEPLOYED across 20 Epics) ✅ |
| **DEPLOYED** | Epic 21: T-149 – T-162 (DEPLOYED, commit c683903, 586 tests pass) ✅ |
| **DEPLOYED** | Epic 22: T-163 – T-167 (DEPLOYED, commit `1dbb6da`, 621 tests pass, прод v2.20.0) ✅ |
| **DEPLOYED** | Chore T-168: danger_drone.mp4 в danger-пул — DONE & DEPLOYED ✅ (коммит `0c74220`, pull 1dbb6da..0c74220, chmod 644, хэш совпал, пул 16 файлов, PID 916795, smoke OK) |
| **DEPLOYED** | Epic 23: T-169 – T-172 (DONE & DEPLOYED ✅, коммит `756d237`, 672 теста, прод v2.21.0, PID 917681) — словарь 118 слов + 17 фраз, .env DANGER_WORDS пустой (дефолты активны), проверка «118 17» совпала, логи чистые |
| **DEPLOYED** | Epic 24: T-173 – T-191 (DONE & DEPLOYED ✅, коммит `a68732c` + docs `818e195`, 835 тестов, прод v2.22.0, PID 920105, smoke apinet.cloud OK) — Н1 BotFather `/setprivacy` → Disable остаётся ручным действием пользователя |
| **IN REVIEW → READY FOR @DevOps** | Epic 25: T-192 – T-198 — T-192/T-193/T-194/T-195/T-196 ✅ Done (B1–B9 IMPLEMENTED, ревью APPROVED, 860 тестов); T-197 (коммит+пуш) и T-198 (деплой+верификация) → @DevOps |

> Epics 1-22 ALL DEPLOYED ✅ (v2.20.0, commit `1dbb6da`, PID 914116). **Epic 22 «Гонка функций и точность триггеров» DONE & DEPLOYED ✅ — реализация (D51–D54) + ревью 3 раунда (APPROVED) + коммит/пуш/деплой (T-167-D).**
> 621 тест. 11 роутеров, 5 таблиц БД, Sentry + Logtail мониторинг.
> MIMIC propagation FIXED. All 6 cooldowns in time-format (1s/1m/1h/1d).
> Epic 22 реализовано и задеплоено: D51 (Olya SaveAsBot-only, OLYA_ALWAYS_SEND=False), D52 (MIMIC_FORWARDS_ENABLED=False), D53 (Slavik race fix, DEAD_PAGE_POST_ON_JOIN=False), D54 (PostPicker last-sent). v2.20.0, 621 тест.

---

## 🚀 Deployment Details

| Параметр | Значение |
|----------|----------|
| **Версия в проде** | v2.22.0 (Epic 24 DEPLOYED) |
| **Текущий коммит** | `a68732c` (feat(summary): Epic 24 — SmartModule с трехуровневой памятью и саммари чата (v2.22.0)) + docs `818e195`; прод HEAD после pull ff `756d237..a68732c` |
| **Дата** | 2026-08-16 |
| **Сервер** | 198.46.175.136 |
| **Путь** | /var/www/admin_bot |
| **Статус** | systemctl status adminbot → active (running), PID 920105, логи чистые («sqlite-vec loaded (dim=768)», «SmartModule Summary initialized (TZ=Asia/Yekaterinburg)», cron 0,6,12,18, 14 роутеров) |
| **Git remote** | origin (github.com/Henry-Case-dev/adminbot.git) — pushed успешно, локальный HEAD = origin/master |
| **Тесты** | 860 PASS локально (835 + 25 Epic 25); прод v2.22.0 — 835 |
| **Эпики** | 1-24 ALL DEPLOYED ✅ |
| **Epic 25** | T-192–T-196 Done (860 тестов, ревью APPROVED); T-197/T-198 pending → READY FOR @DevOps |
| **Задачи** | T-001 – T-191 ALL DEPLOYED ✅ |
| **.env на проде** | +LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME/SUMMARY_TIMEZONE (без дублей); DANGER_WORDS пустой → дефолты; DEAD_PAGE_POST_ON_JOIN=False; OLYA_ALWAYS_SEND и MIMIC_FORWARDS_ENABLED — дефолты False |
| **Ошибки** | 0 errors, 0 трейсбеков. Все сервисы инициализированы корректно. |
| **Ручные действия** | Н1: BotFather `/setprivacy` → Disable (критично); живая проверка `/summary` в чате |

---

*Обновление: 2026-08-16 — EPIC 24 (v2.22.0): DEPLOYED ✅ (Шаг 8, @Memory — финальная синхронизация). ВЕСЬ запрос пользователя выполнен. @DevOps: T-190 DONE (835 тестов PASS локально; коммит a68732c «feat(summary): Epic 24 — SmartModule с трехуровневой памятью и саммари чата (v2.22.0)» — 35 файлов, +4495/−28, включая медиа leha_greeting_18-21.mp4 и olya_cringe-03.mp4, проверены; пуш master c093de7..a68732c; docs-коммит 818e195 (синхронизация board.md), пуш ✅; HEAD = origin/master, дерево чистое; .env не коммичен). T-191 DONE (прод 198.46.175.136: git pull ff 756d237..a68732c; prod .env +LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME/SUMMARY_TIMEZONE без дублей; venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1; smoke T-191-D ✅ curl apinet.cloud/v1/models → валидный список моделей; restart → active (running) PID 920105; логи: «sqlite-vec loaded (dim=768)», «SmartModule Summary initialized (TZ=Asia/Yekaterinburg)», cron 0,6,12,18, 14 роутеров, трейсбеков нет). Наблюдение: старый процесс v2.21.0 (PID 917681) завис в shutdown ~90с → SIGKILL systemd (поведение старого кода, новый стартует чисто). Открытые ручные действия пользователя (не через SSH): Н1 BotFather /setprivacy → Disable (критично, иначе память L1/L2/L3 пустая); живая проверка /summary в чате. board.md: T-190 ✅ Done, T-191 ✅ Done, Epic 24 ✅ DEPLOYED (v2.22.0).*

*Обновление: 2026-08-16 — EPIC 24 (v2.22.0): IMPLEMENTED + REVIEW PASSED ✅ (Шаг 6, @Memory — граф и MEMORY.md синхронизированы). @Builder: T-174–T-188 A/B/C DONE (9 новых модулей services/summary_*.py + llm_client.py + handlers/summary.py; settings.py +24 поля; database.py _SCHEMA_SQL + 11 методов; bot.py роутеры 0a/0b + wiring; requirements.txt httpx/APScheduler 3.x/sqlite-vec; .env.example). @Reviewer T-188-D: APPROVE WITH FIXES → Approved (фиксы: await shutdown() в on_shutdown; _purge_archive rowid IN; +QA-тест test_vec_purge_removes_vectors). Тесты: 830 PASS / 0 failed (672 + 158: 147 в 9 новых файлах + 11 в test_database.py). Подтверждено: sqlite-vec 0.1.9 на Windows/Py3.12; vec0 KNN без WHERE по auxiliary-колонкам → chat-фильтр в Python; APScheduler 3.11 требует tz в CronTrigger; {username} литералом + {max_symbols} через .replace() (фикс бага 33.7). Low-замечания → T-189: XML-экранирование l2/l3-блоков; /summary@BotName не ловится троттлингом; нет капа чанков по MAX_SUMMARY_PARTS; location/contact/dice не сохраняются. Живой smoke apinet.cloud локально невозможен (ReadTimeout) → T-191-D на проде. Остаток: T-189/T-190/T-191; Н1 (BotFather /setprivacy → Disable) критичен для деплоя.*

*Обновление: 2026-08-16 — ЗАФИКСИРОВАНА ПОЛИТИКА MEDIA-ПАПКИ (указание пользователя): всё, что добавляется/удаляется в media/ (media/common/danger, media/olya/cringe, media/slavik_random и т.п.), делается СОЗНАТЕЛЬНО и СПЕЦИАЛЬНО для загрузки на сервер и использования ботом; media-файлы НЕ исключаются из коммитов как мусор, НЕ добавляются в .gitignore, НЕ удаляются без явного указания. Рекомендация «danger_drone.mp4 → .gitignore» — ОШИБОЧНАЯ, ОТМЕНЕНА. danger_drone.mp4 — 16-й файл danger-пула, добавлен намеренно. Новая chore-задача: коммит + деплой media/common/danger/danger_drone.mp4.*

*Обновление: 2026-08-15 — EPIC 22 STATUS: DONE & DEPLOYED ✅ (v2.20.0, коммит `1dbb6da`). «Гонка функций и точность триггеров» — PM-решения D51–D54 реализованы и задеплоены (Olya SaveAsBot-only / MIMIC_FORWARDS_ENABLED=False / Slavik race fix / PostPicker last-sent). Задачи T-163–T-167 (A/B/C/D) выполнены: ревью 3 раунда APPROVED, 621 тест PASS (586 baseline + 35 новых), 0 регрессий. Деплой: сервер 198.46.175.136:/var/www/admin_bot, git pull c683903..1dbb6da (21 файл, +1778/-224), systemctl restart OK, active (running), PID 914116 (был 699945), логи чистые. Prod .env: DEAD_PAGE_POST_ON_JOIN=True→False (бэкап .env.bak.2026-08-15); OLYA_ALWAYS_SEND и MIMIC_FORWARDS_ENABLED отсутствуют — дефолты False. media/common/danger/danger_drone.mp4 — добавлен намеренно (16-й файл danger-пула), к коммиту и деплою; рекомендация про .gitignore ОТМЕНЕНА пользователем (2026-08-16).*

*Предыдущий статус (2026-08-15): EPIC 22 IMPLEMENTED + APPROVED ✅ (коммит и деплой pending). T-163–T-167-C выполнены @Builder, ревью 3 раунда — APPROVED. 621 тест PASS. НЕ закоммичен/НЕ задеплоен (базовый коммит c683903 v2.19.0 в проде).*

*Предыдущий статус (2026-08-03): EPIC 21 STATUS: DEPLOYED ✅. MIMIC propagation fix (D49: return UNHANDLED in alan_handler, 3 code paths). Time-format cooldowns (D50: _parse_duration с 1s/1m/1h/1d, 6 полей переименовано). 586 тестов пасс. All 14 tasks T-149–T-162 COMPLETE + DEPLOYED. Commit c683903, push origin/master.*

*Обновление: 2026-08-16 — CHORE T-168: IN PROGRESS 🚧. PM добавил T-168 в backlog.md (T-168-A..E + AC) и board.md (In Progress, @Builder): chore — коммит + деплой `media/common/danger/danger_drone.mp4` (16-й файл danger-пула). Architect добавил Section 31 в ARCHITECTURE.md (Конвенция media/ + инвентарь пулов). Код не требуется — media_picker подхватывает файл автоматически. Ожидает @Builder: verify → коммит `chore(media): danger_drone.mp4 в danger-пул` (на русском) → push → деплой (git pull на 198.46.175.136) → verify на сервере → smoke test. Соблюдать политику media/: НЕ в .gitignore, НЕ удалять.*

*Обновление: 2026-08-16 — CHORE T-168: A/B DONE ✅, APPROVED ревьюером. Коммит `0c74220` (chore(media): danger_drone.mp4 в danger-пул) сделан и запушен в master. Состав: 1 медиа-файл + 4 plans-файла, кода нет. danger_drone.mp4 закоммичен (blob `918c9be9…`, 2 574 925 байт, ftyp isom/MP4), working tree clean. C/D/E (деплой на сервер / verify на сервере / smoke test) — PENDING. Прод пока на `1dbb6da` (v2.20.0) до деплоя.*

*Обновление: 2026-08-16 — CHORE T-168: DONE & DEPLOYED ✅. Все подзадачи A..E закрыты. Деплой: git pull на сервере fast-forward 1dbb6da..0c74220 (5 файлов: danger_drone.mp4 + 4 plans). danger_drone.mp4 на месте (2 574 925 байт), права 644, хэш 918c9be9... совпал, danger-пул = 16 файлов. systemctl restart OK: active (running), PID 916795, логи чистые. Smoke test пройден. Прод HEAD = 0c74220 (v2.20.0 + медиа).*

*Обновление: 2026-08-16 — EPIC 23: IMPLEMENTED + APPROVED ✅ (коммит/деплой PENDING). «Правка danger-словаря» — T-169..T-171 DONE: DANGER_WORDS 191→118 (удалены Flight/Shelter/Атака-угроза/Падение-сбитие; добавлены хлопок/хлопки/хлопнуло/хлопнул), новая DANGER_PHRASES=17 (10 shelter + 7 атака, longest-first). Механика: _build_phrase_patterns в DangerWordFilter — фразы→слова, {"matched_word"} совместимо, env-независимо. Тесты: 672 PASS (621+51; TestDangerPhrases 42 кейса, контракт 17 фраз, негативы). Ревью 2 раунда APPROVED (2 фикса тестов выполнены дословно). T-172 (README/доки/коммит/деплой) PENDING. Прод на 0c74220 (v2.20.0 + T-168 media). Целевая версия v2.21.0.*

*Обновление: 2026-08-16 — EPIC 23: T-172-A..D DONE ✅, деплой (E..G) PENDING — DevOps. README: v2.21.0, 672 теста, «187 словоформ» → 118 слов + 17 фраз (135 паттернов), примеры словаря (атака/угроза/прилет → фразы, добавлен хлопок), changelog «Изменено в v2.21.0 (Epic 23)» с D55–D58. backlog: T-169..T-171 [x], T-172-A..D [x], деплой [ ]; статус Epic 23 → IMPLEMENTED (APPROVED, деплой pending). board: Epic 23 → In Review с пометкой «APPROVED, деплой pending», футер синхронизирован. Коммит feat(danger) на master + push в origin. Состав: word_lists.py, danger_word.py, test_filters.py, test_common.py, README.md, ARCHITECTURE.md, MEMORY.md, backlog.md, board.md. Прод на 0c74220 (v2.20.0 + T-168 media).*

*Обновление: 2026-08-16 — EPIC 23: IN PROGRESS 🚧 (СПЛАНИРОВАН, целевая версия v2.21.0). PM и Architect спланировали Epic 23 «Правка danger-словаря»: решения D55–D58, задачи T-169..T-172. DANGER_WORDS: 118 словоформ (было 191) — удалены секции Flight (10), Shelter (26), Атака/угроза (28), Падение/сбитие (13); добавлены хлопок/хлопки/хлопнуло/хлопнул. Новая DANGER_PHRASES (17 фраз: 10 shelter + 7 атака). Механика: _build_phrase_patterns в DangerWordFilter — фразы проверяются до слов, границы по краям фразы, IGNORECASE, возврат {"matched_word": ...} совместимый. Потребители: war_alert (4b) и danger_handler (4c) — единый словарь. Итог 135 паттернов; target ≈646 тестов. Прод .env не трогаем.*

*Обновление: 2026-08-16 — EPIC 23: DONE & DEPLOYED ✅ (v2.21.0, коммит `756d237`). Деплой: git pull 0c74220..756d237 (9 файлов) на 198.46.175.136:/var/www/admin_bot, systemctl restart OK — active (running) PID 917681, логи чистые. .env DANGER_WORDS пустой → активны дефолты word_lists.py (118 слов + 17 фраз, 135 паттернов). Python-проверка «118 17» на сервере совпала. Все 23 Epic'а COMPLETE и DEPLOYED. Прод v2.21.0, бот активен, 0 ошибок.*

*Обновление: 2026-08-16 — EPIC 24 (v2.22.0-in-progress): Шаг 3 (@Memory) — фаза архитектуры (T-173) завершена, граф знаний и MEMORY.md синхронизированы. Дизайн Section 33 (A1–A15, риски 33.14) зафиксирован в ARCHITECTURE.md; RESEARCH.md верифицирован (методология: context7 — Invalid API key / duckduckgo — anomaly → рабочий стек exa + webfetch docs.aiogram.dev). board.md: T-173 → In Review, T-174 → READY FOR BUILDER. Код не писался — передача @Builder после PM-аппрува T-173-E. Предупреждения для @Builder: Н1 BotFather /setprivacy → Disable (T-191); порядок роутеров 0a/0b не менять; 12 существующих роутеров и MessageCounterMiddleware не трогать; sqlite-vec — только graceful fallback (R3).*

*Обновление: 2026-08-16 — EPIC 25 (багфикс /summary): IMPLEMENTED + REVIEW PASSED ✅ (Шаг 6, @Memory — граф знаний и MEMORY.md синхронизированы). @Builder: T-194/T-195 DONE — B1–B9 реализованы (summary_throttling.py B3: _parse_command, me()-валидация mention case-insensitive, чужая mention не жжёт слот и пропускается, base == "/summary", guard text.strip(), R8-молчание + INFO remaining; summary_generator.py B2/B4/B5: generate_and_send(chat_id, manual=False), _UX_EMPTY/_UX_BUSY, пустое окно/lock UX manual + INFO cron; handlers/summary.py B1/B6/B7/B8/B9: ack «ща гляну, подожди» send_message, _safe_send(bot) с DI bot, message.delete() после ack try/except WARNING, INFO-логи всех состояний, наблюдатель не пишет /summary* в text и caption). Тесты: 860 PASS (835+25), 0 регрессий. @Reviewer: T-196 APPROVED — 860 подтверждены личным прогоном, J1–J5 подтверждены, Bot.me() кэшируется (1 вызов на процесс); 4 Low-замечания не блокируют: (1) троттлинг смотрит только event.text — команда-капшн обходит (pre-existing, сериализуется Lock); (2) «ack sent» при неудаче; (3) bot.me() без try/except; (4) _last без TTL. Остаток: T-197 (коммит на русском + push) и T-198 (деплой + верификация /summary живьём через логи) → @DevOps. Деплойный риск B7: админ-права delete_messages у бота в чате (иначе 400 Bad Request → WARNING, best-effort).*
