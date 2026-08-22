# AdminBot — Kanban Board

## 📋 Backlog

*(пусто)*

## 🔧 In Progress

### Epic 56: /info — правка пользователя (раздел 6 «Прямое обращение к Богу Машине») + `<code>`→`<blockquote>` — ✅ IMPLEMENTED + REVIEWED (APPROVED WITH NOTES), 🚧 DEPLOY PENDING (@DevOps T-440, target v2.40.0, P0)

> Полный трек — `plans/backlog.md` (Epic 56). Требования R56-1…R56-7, решения D223–D225.
> Правка пользователя (раздел 6 «6. Прямое обращение к Богу Машине» — слова-триггеры,
> реплай на бота, тег @) существует ТОЛЬКО в локальной рабочей копии. Локальная копия =
> источник истины (D224); серверный `info_text.md` == HEAD `c7a6da5` (старого канона — факт
> сверки T-438-A); после коммита git-канон == источнику истины.
> Теги `<code>` не видны в мобильном Telegram → замена ТОЛЬКО тегов на `<blockquote>`
> (27 мест), текст не трогать. Обязательная сверка ЧЕРЕЗ EXA: Telegram Bot API formatting
> options (blockquote в HTML parse mode — Bot API 7.0 (December 29, 2023); expandable 7.7 — не используется) + aiogram 3.29.1
> передача `parse_mode` (T-437). Канон-цепочка (5 мест) синхронно: DEFAULT_INFO_TEXT =
> info_text.md = ARCHITECTURE 53.3 (оба блока) = backlog «Канон R44-1» (plain). Порядок
> деплоя инвертирован (D225): канон в git → коммит+пуш → `git pull` на проде, правку
> пользователя НЕ терять. v2.40.0 (minor, D223 — прецедент D220). База: прод v2.39.0
> (`c7a6da5`, PID 1053785), 2354 теста, Epics 1–55 ALL CLOSED. Без @Orchestrator.

- [x] T-437 (@Architect, P0) — exa-ресёрч (Telegram Bot API blockquote/expandable + aiogram parse_mode) + вердикт + новый канон Section 53.3/63 (оба блока) + правки тестов дословно. **DoD:** вердикт зафиксирован; решение по замене зафиксировано; Section 53.3 (или 63) с новым каноном; правки тестов перечислены; вопросы 1–5 закрыты. ✅ **DONE (Шаг 2 @Architect: `<blockquote>` в HTML parse mode поддержан с Bot API 7.0 (December 29, 2023 — НЕ 7.1); expandable (7.7) НЕ нужен; Section 53.3 «Дополнение Epic 56»).**
- [x] T-438 (@Builder, P0) — серверный `info_text.md` (SSH `nik@198.46.175.136`, пароль у @DevOps) ↔ локально байт-в-байт; замена ТОЛЬКО тегов `<code>`→`<blockquote>` (27 мест); канон-цепочка 5 мест; тесты (счётчики/strip/маркеры); pytest 0 регрессий. **DoD:** сверка байт-в-байт; только теги заменены; 5 мест синхронны; тесты зелёные; 0 регрессий (2354). ✅ **DONE (Шаг 4 @Builder: сверка T-438-A — серверный файл == HEAD `c7a6da5`, правка пользователя только в локальной копии; 27 `<code>`→`<blockquote>`, текст не тронут; канон-цепочка синхронна; 2354 passed / 0 failed).**
- [ ] T-439 (@Reviewer, P0) — байт-в-байт сверка 5 мест; дифф только теги; 0 регрессий; APPROVED. **DoD:** APPROVED; 5 мест синхронны; дифф = только замены тегов.
- [ ] T-440 (@DevOps, P0) — бэкап `info_text.md.bak.epic56` ДО всего; коммит (код+канон+тесты+info_text.md, без mp4) + пуш; деплой: `git pull` (при локальных изменениях серверного файла — сверка/checkout, правку НЕ терять), restart, 0 traceback, smoke /info. **DoD:** бэкап есть; коммит запушен; правка не потеряна; новый PID; 0 traceback; smoke OK.
- [ ] T-441 (@Docs, P1) — README v2.40.0 + MEMORY. **DoD:** доки актуализированы; Epic 56 CLOSED.

**Updated:** 2026-08-23 — **Epic 56 ✅ IMPLEMENTED + REVIEWED (APPROVED WITH NOTES) — DEPLOY PENDING (@DevOps T-440)**: T-437/T-438 DONE; T-439 APPROVED WITH NOTES — замечания закрыты @Docs (T-441): Medium-1 — источник истины = локальная копия пользователя (сервер == HEAD `c7a6da5`, правки на проде НЕТ); Low-1 — Bot API 7.0 (December 29, 2023), НЕ 7.1. Далее — @DevOps (T-440 коммит+пуш+деплой). Epics 1–55 ALL CLOSED.**

### Epic 55: /info — «Что нового» по последним апдейтам — ✅ DEPLOYED & CLOSED (v2.39.0, коммит `c7a6da5`, прод PID 1053785, 2354 теста, 2026-08-23, Шаг 8 @Memory)

> Полный трек — `plans/backlog.md` (Epic 55). Требования R55-1…R55-5, решения D220–D222.
> В /info добавить НЕДОСТАЮЩУЮ информацию по последним апдейтам (Epic 52 v2.37.0, Epic 53
> v2.38.0, Epic 54 v2.38.1) — новый раздел «Что нового» тем же иронично-свойским стилем,
> append ПОСЛЕ раздела 5; существующие 5 разделов НЕ менять (требование пользователя).
> Канон-цепочка (5 мест) обновляется СИНХРОННО: info_service.py::DEFAULT_INFO_TEXT =
> info_text.md = ARCHITECTURE.md 53.3 (python+html блоки) = backlog «Канон R44-1» (без тегов)
> — иначе падают байт-в-байт тесты test_info_service.py. Фактура: Epic 52 (Алан — трейдинг
> убран, новые темы, выключен; common/work выключено; Славик — одно действие; dead page —
> месть за удалённый репост; direct_chat — слова «бот»-семейства); Epic 53 (Алан v2 — 5 тем
> × 5 фраз + вопросы-подколы, всё ещё выключен; фикс 502 — circuit breaker, не висит 60с,
> человечные фразы; RESEARCH_HUMAN.md); Epic 54 (фоллбэк DeepSeek включён на проде). Без
> эмодзи/маркдауна/секретов (R17). Прод-процедура: бэкап info_text.md.bak.epic55 +
> git checkout -- info_text.md ДО pull. v2.39.0 (minor, D220). База: прод v2.38.1 (`148328a`,
> PID 1052789), 2354 теста, Epics 1–54 ALL CLOSED. Без @Orchestrator.

- [x] T-431 (@Architect, P0) — канон-текст нового раздела «Что нового» (html, стиль существующих) + Section 53.3 (ОБА блока, append) + маркеры для test_covers_features; закрыть вопросы 1–4. **DoD:** канон байт-в-байт (html+plain), 53.3 дополнена, маркеры перечислены дословно, существующие 5 разделов не тронуты. ✅ **DONE (Шаг 2 @Architect).**
- [x] T-432 (@Builder, P0) — канон-цепочка: DEFAULT_INFO_TEXT + info_text.md + backlog «Канон R44-1» (plain) — append байт-в-байт из 53.3. **DoD:** 5 мест синхронны, дифф только append, старые 5 разделов не тронуты. ✅ **DONE (Шаг 4 @Builder).**
- [x] T-433 (@Builder + @QA, P0) — тесты: маркеры новых фич + байт-в-байт (3 теста зелёные) + полный pytest 0 регрессий (2354). **DoD:** маркеры добавлены, 0 регрессий, diff --check чист. ✅ **DONE (2354 passed / 0 failed; APPROVED WITH NOTES).**
- [x] T-434 (@DevOps, P1) — коммит на русском + пуш origin/master (код+канон+тесты+info_text.md одним коммитом, D123-стиль). **DoD:** коммит запушен. ✅ **DONE (Шаг 7: коммит `c7a6da5`, пуш 148328a..c7a6da5, 8 файлов, без mp4).**
- [x] T-435 (@DevOps, P0) — деплой v2.39.0: бэкап info_text.md.bak.epic55 + git checkout -- info_text.md ДО pull; git pull --ff-only; restart (новый PID); journalctl 0 traceback; smoke /info (новый раздел + старые 5). **DoD:** бэкап есть, pull ff, новый PID, 0 traceback, smoke OK. ✅ **DONE (Шаг 7: бэкап + checkout ДО pull, pull ff 148328a..c7a6da5, PID 1053785, 0 traceback, smoke «Что нового» 1 + старые секции 4).**
- [x] T-436 (@Docs, P1) — README v2.39.0 + MEMORY. **DoD:** доки актуализированы, Epic 55 CLOSED. ✅ **DONE (T-436-A: README v2.39.0 + MEMORY + Low-3 «До Epic 55:» — ранее; финализация Шаг 8: Epic 55 помечен CLOSED).**

**Updated:** 2026-08-23 — **Epic 55 ✅ DEPLOYED & CLOSED (v2.39.0, Шаг 8 @Memory)**: все T-431…T-436 DONE ([x]). Шаг 7 @DevOps: коммит `c7a6da5` (8 файлов, без mp4) + пуш origin/master (148328a..c7a6da5); деплой — бэкап info_text.md.bak.epic55 + checkout ДО pull, pull ff, restart OK, PID 1053785, 0 traceback; smoke по файлу: «Что нового» 1 + старые секции 4. Тесты 2354/0. Раздел 6 «Что нового» на проде. Epics 1–55 ALL CLOSED.**

### Epic 53: ALAN_REPLIES v2 + LLM 502 (direct_chat) + RESEARCH_HUMAN — ✅ DEPLOYED & CLOSED (v2.38.0, коммит `a8f82b1`, прод PID 1052443, 2354 тестов, 2026-08-23, Шаг 8 @Memory)

> Полный трек — `plans/backlog.md` (Epic 53). Требования R53-1…R53-4, решения D215–D217.
> П1 — ALAN_REPLIES v2: 5 новых тем (NixOS/Линукс, Продажа SSD, Витамины Life Extension,
> 5-сек прогулки с гантелями, Уличный тренажёр+колени) довести до ПОЛНОЦЕННЫХ (≥4-5 фраз, сейчас
> по 3 — огрызки); старые темы СОХРАНЯЮТСЯ (D215 — их требуют контракты test_topic_coverage);
> фразу alan.py:43 («разминался сегодня?...») → пул издевательских токсичных вопросов (3-5);
> прод `ALAN_REPLIES_ENABLED=false` НЕ менять (проверка в T-426). П2 — LLM 502 direct_chat
> (рецидив Epic 47: ReadTimeout→502→502, ретраи не спасают): расследование (T-418) + фикс D216 —
> circuit breaker (ОСНОВНОЙ: N=3 подряд → кулдаун + человеческая фраза) + опциональный
> фоллбэк-провайдер (LLM_FALLBACK_BASE_URL/MODEL/API_KEY, пусто=выключен) + диагностика 502;
> health-check НЕ делаем (обоснование D216). П3 — `plans/RESEARCH_HUMAN.md` (D217): ВСЕ
> рекомендации RESEARCH.md §6 человеческим языком (что/зачем/что даст/цена/приоритет) + чекбоксы
> [ ]; RESEARCH.md НЕ трогать. v2.38.0, база 2302, пуш origin/master.

- [x] T-418 (@Architect, P0) — расследование 502 (llm_client/settings/direct_chat_service + логи прода) + Section 62 (дизайн CB/фоллбэк + каноны фраз VERBATIM: 5 тем × ≥4-5 + пул вопросов + CHAT_LLM_DOWN_PHRASES)
- [x] T-419 (@Builder, P1) — ALAN_REPLIES v2 (handlers/alan.py): 5 тем расширить до ≥4-5 фраз; alan.py:43 → пул издевательских вопросов; старые темы не трогать; test_alan.py (полнота тем, word-boundary чистота)
- [x] T-420 (@Builder, P0) — llm_client: диагностика 502 (тело ≤500, R17) + CircuitBreaker (порог 3, кулдаун 300-600с, half-open) + фоллбэк-провайдер (LLM_FALLBACK_*, пусто=выключен) + settings/.env.example
- [x] T-421 (@Builder, P0) — direct_chat: CB OPEN → без вызова LLM, фраза из CHAT_LLM_DOWN_PHRASES (новый пул, VERBATIM); R50-8 CHAT_ERROR_PHRASES не трогать; успех → сброс CB
- [x] T-422 (@Builder + @QA, P0) — тесты: мок httpx (502×3 → LLMError; 502×2+успех; таймаут; CB OPEN без HTTP; фоллбэк on/off; лог 502), direct_chat CB-ветка, alan-полнота; полный pytest 0 регрессий (2354 passed / 0 failed)
- [x] T-423 (@Docs, P2) — plans/RESEARCH_HUMAN.md: все рекомендации §6 (6.1–6.11 + P0/P1/P2 + чек-лист) простыми словами + [ ] чекбоксы; RESEARCH.md не трогать
- [x] T-424 (@Docs, P2) — README v2.38.0 (иронично) + MEMORY — **Done (Шаг 7, README v2.38.0)**
- [x] T-425 (@DevOps, P1) — коммит на русском + пуш origin/master — **Done (Шаг 7, коммит `a8f82b1`, пуш 56cccd6..a8f82b1)**
- [x] T-426 (@DevOps, P1) — деплой v2.38.0: .env.bak.epic53, ПРОВЕРИТЬ ALAN_REPLIES_ENABLED=false (НЕ менять), LLM_FALLBACK_* не ставить; restart; journalctl 0 traceback; smoke (alan false, direct_chat, славик, checkup) — **Done (Шаг 7, PID 1052443, 0 traceback)**

**Updated:** 2026-08-23 — **Epic 53 ✅ DEPLOYED & CLOSED (v2.38.0, Шаг 8 @Memory)**: все T-418…T-426 DONE ([x]). Шаг 7 @DevOps: коммит `a8f82b1` + пуш origin/master (56cccd6..a8f82b1); деплой Fast-forward на прод — .env не менялся (ALAN_REPLIES_ENABLED=false сохранён, LLM_CB_*/LLM_FALLBACK_* на дефолтах), бэкап .env.bak.epic53, restart OK, PID 1052443, journalctl 0 traceback. 2354 passed / 0 failed. Инцидент 502 → RESOLVED (фикс задеплоен). Epics 1–53 ALL CLOSED.

### Epic 54: Включение фоллбэк-провайдера (прямой API DeepSeek) — ✅ DEPLOYED & CLOSED (v2.38.1, коммит `148328a`, прод PID 1052789, 2354 теста, 2026-08-23, Шаг 8 @Memory)

> Полный трек — `plans/backlog.md` (Epic 54). Решения D218/D219. Конфигурационный эпик:
> основной LLM (apinet.cloud, deepseek-v4-flash) ОСТАЁТСЯ; опциональный фоллбэк (механика
> Epic 53/62.4, уже в v2.38.0 `a8f82b1`) ВКЛЮЧАЕТСЯ на проде тремя переменными — прямой API
> DeepSeek. Верифицировано (@Memory, доки DeepSeek): `LLM_FALLBACK_BASE_URL=https://api.deepseek.com`,
> `LLM_FALLBACK_MODEL=deepseek-v4-flash` (официальная; `deepseek-chat`/`deepseek-reasoner`
> заретированы 2026-07-24 — НЕ использовать); ключ — задан пользователем (в планах/логах
> НЕ публиковать, R17). Код менять НЕ нужно. Версия: v2.38.1 (chore, patch) — без кода/тестов,
> только прод-конфиг и доки. Коммит — только планы/доки (если есть); прод .env меняется напрямую.
> Фоллбэк покрывает только chat/completions — embeddings остаются на apinet.cloud.
> База: прод v2.38.0 (`a8f82b1`, PID 1052443), 2354 теста, Epics 1–53 ALL CLOSED. Без @Orchestrator.

- [x] T-427 (@DevOps, P0) — прод .env: бэкап `.env.bak.epic54` ДО правки; +`LLM_FALLBACK_BASE_URL`/`LLM_FALLBACK_MODEL`/`LLM_FALLBACK_API_KEY`; первичный apinet.cloud НЕ трогать; ключ не засветить (R17). **DoD:** бэкап есть, 3 переменные добавлены, ключ не в логах/планах. — **Done (Шаг 7: 3 переменные добавлены, бэкап `.env.bak.epic54`, дублей нет, apinet.cloud не тронут; ключ задан пользователем — значение не публикуем)**
- [x] T-428 (@DevOps, P0) — верификация: smoke-curl с сервера → `POST https://api.deepseek.com/chat/completions` Bearer из .env → 200; restart admin_bot → active (running), НОВЫЙ PID (был 1052443); journalctl 0 traceback. **DoD:** curl 200, новый PID, 0 traceback. — **Done (Шаг 7: HTTP 200, PID 1052789, 0 traceback, WARNING «partially configured» отсутствует)**
- [x] T-429 (@Architect, P1) — подтвердить «код менять не нужно» + ARCHITECTURE.md Section 62.4: короткое дополнение о включении фоллбэка на проде (канон-текст — в backlog T-429). **DoD:** вердикт зафиксирован, Section 62.4 дополнена. — **Done (Шаг 2: вердикт «код менять НЕ нужно» + канон-текст в Section 62.4)**
- [x] T-430 (@Docs + @DevOps, P1) — деплой-отчёт + README changelog v2.38.1 + MEMORY (фоллбэк включён); коммит планов/доков на русском + пуш origin/master. **DoD:** доки актуализированы, Epic 54 CLOSED. — **Done (Шаг 7: README v2.38.1 + MEMORY; коммит `148328a`, пуш a8f82b1..148328a, 5 файлов)**

**Updated:** 2026-08-23 — **Epic 54 ✅ DEPLOYED & CLOSED (v2.38.1, Шаг 8 @Memory)**: все T-427…T-430 DONE ([x]). Шаг 7 @DevOps: прод .env — бэкап `.env.bak.epic54` + 3 переменные `LLM_FALLBACK_*` (primary apinet.cloud не тронут; ключ задан пользователем — значение не публикуем); smoke-curl `https://api.deepseek.com/chat/completions` → HTTP 200; restart OK, PID 1052789, 0 traceback, WARNING «partially configured» отсутствует. @Docs: README v2.38.1 + MEMORY. Коммит `148328a` (5 файлов) запушен в origin/master (a8f82b1..148328a). Фоллбэк DeepSeek ACTIVE. Epics 1–54 ALL CLOSED.

### Epic 48: Откат degraded-саммари (Summary: LLM или ничего) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.36.0, P0 — «в первую очередь»)

> Полный трек — `plans/backlog.md` (Epic 48). Требования R48-1…R48-6, решения D186–D189.
> Саммари = ЛИБО от LLM, ЛИБО никакое: degraded-вывод (`_degraded_summary`, `_DEGRADED_HEADER`, `_DEGRADED_LINE_CHARS`, ветка «B» в `_run` 142-148) УДАЛЯЕТСЯ. Retry-once (`SUMMARY_RETRY_ONCE_PAUSE=5с`) СОХРАНЯЕТСЯ (LLM-путь): второй фейл → raise → UX R13. Удалить `SUMMARY_DEGRADED_ENABLED/COUNT` из settings.py (289/291) + .env.example (155-156); прод `.env` — SUMMARY_DEGRADED_* отсутствуют (проверено PM). UX R13 байт-в-байт не трогать. Тест-переписать: degraded-цепочка → «retry ×2 → UX», удалить disabled/limits/empty-тесты (test_summary_generator.py, test_settings_helpers.py 246-307). Док-долг: Section 56.6 → финальная реализация (Section 57). Каноны промптов не трогать; миграций нет; база 2099; v2.36.0 (прод `6d0cba0`). Без @Orchestrator.

- [ ] T-381 (@Architect, P0) — Section 57: финализация 56.6 (Epic 48) + дизайн чекап-фикса (Epic 49); закрыть открытые вопросы 1–2
- [ ] T-382 (@Builder, P0) — откат кода: удалить degraded из summary_generator.py (retry-once и UX R13 сохранить)
- [ ] T-383 (@Builder, P0) — удалить SUMMARY_DEGRADED_* из settings.py + .env.example (прод .env не трогать — отсутствуют)
- [ ] T-384 (@Builder, P0) — тесты: переписать degraded-цепочку → UX R13; удалить disabled/limits/empty; 0 регрессий (база 2099)
- [ ] T-385 (@Builder + @Reviewer, P0) — ревью APPROVED + полный прогон 0 регрессий
- [ ] T-386 (@Builder, P1) — README v2.36.0 + MEMORY

### Epic 49: Чекап 400: расследование + фикс + разделение UX-фраз — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.36.0, P0)

> Полный трек — `plans/backlog.md` (Epic 49). Требования R49-1…R49-5, решение D187.
> Инцидент 2026-08-20T09:33:58 UTC (PID 1013533): стабильный `LLM HTTP 400` apinet.cloud
> (llm_client.py:180 → generate:198 → checkup_service.py:31 → handlers/checkup.py:77-81);
> юзер получил «база подавилась логами» (CHECKUP_LLM_ERROR_PHRASES) — ложный след (упал LLM).
> Порядок: (1) диагностика СНАЧАЛА — лог длины payload + тело 4xx (сейчас НЕ логируется),
> окно deepseek-v4-flash у apinet.cloud (ресёрч), фактическая длина user-сообщения чекапа
> (≤20000 симв. `_MAX_LOG_SYMBOLS`, journalctl-фолбек Epic 45); (2) фикс первопричины по Section 57
> (обрезка/сжатие контекста и/или scrub управляющих символов; гипотезы (а) окно/(б) символы/(в) параметр);
> (3) попутно: checkup.py:81 `logger.exception` → WARNING (долг Epic 47) + сплит UX-фраз
> (LLMError → «LLM/мозги», ошибки логов → «база»; тексты R42-5/R13 байт-в-байт, только маппинг).
> Каноны CHECKUP_SYSTEM_PROMPT не трогать; миграций нет; база 2099; v2.36.0. Без @Orchestrator.

- [ ] T-387 (@Architect, P0) — Section 57: дизайн диагностики 4xx + ресёрч окна модели + финальное решение фикса + UX-маппинг; закрыть открытые вопросы 1–6
- [ ] T-388 (@Builder, P0) — llm_client: диагностический лог 4xx (payload length + тело, без секретов R17)
- [ ] T-389 (@Builder, P0) — фикс первопричины по Section 57 (обрезка/сжатие контекста и/или scrub символов)
- [ ] T-390 (@Builder, P0) — checkup.py:81 WARNING без traceback + сплит UX-пулов (маппинг, тексты не менять)
- [ ] T-391 (@Builder + @Reviewer, P0) — тесты 4xx-диагностики/обрезки/WARNING/маппинга + 0 регрессий (база 2099) + ревью APPROVED
- [ ] T-392 (@Builder, P1) — README v2.36.0 + MEMORY

### Epic 50: DirectChat (прямое общение с сохранением контекста) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.36.0, P1)

> Полный трек — `plans/backlog.md` (Epic 50). Требования R50-1…R50-9, решение D188.
> Подсервис DirectChat в SmartModule: бот НИКОГДА не инициирует диалог; отвечает ТОЛЬКО на Reply
> своему сообщению ЛИБО упоминание юзернейма/тега; все ответы — Reply на сообщение обращающегося;
> идентификация через AliasResolver (Алиас → Никнейм → Юзернейм). Конфиг: CHAT_GLOBAL_CONTEXT_LIMIT=100 /
> CHAT_BURST_LIMIT=3 / CHAT_COOLDOWN_SECONDS=300 / CHAT_DIRECT_REPLY_TTL_DAYS="" (пусто = вечно).
> Context Partitioning: <RAG_Memory> (по хронологии) / <Global_Context> / <Conversation_Thread>
> (рекурсивные реплаи) / <Target_User>. Канон CHAT_SYSTEM_PROMPT + пулы кулдауна (4) и ошибок (3) —
> VERBATIM в backlog (R50-4/7/8). Temporal GraphRAG: origin='bot_direct_reply', TTL по CHAT_DIRECT_REPLY_TTL_DAYS
> (пусто → expires_at NULL), метаданные target_user/chat_id/timestamp, ORDER BY timestamp ASC при сборке
> <RAG_Memory>. Token Bucket: CHAT_BURST_LIMIT зарядов/юзер, восстановление через 300с, кулдаун-пул.
> ⚠️ ОТКРЫТЫЙ ВОПРОС: CHECK `graph_facts.origin` (database.py:133-134) НЕ допускает 'bot_direct_reply'
> → возможна идемпотентная миграция user_version (прецедент Epic 46 T-360) или ALTER ADD COLUMN target_user;
> created_at в graph_facts уже есть → ORDER BY без новой колонки (по Section 58). Каноны промптов не трогать;
> база 2099; v2.36.0. Без @Orchestrator.

- [ ] T-393 (@Architect, P1) — Section 58: каноны VERBATIM + дизайн (триггеры/token bucket/context partitioning/memorize/ORDER BY); закрыть открытые вопросы 1–8 (вкл. миграцию origin)
- [ ] T-394 (@Builder, P1) — конфиг CHAT_GLOBAL_CONTEXT_LIMIT/CHAT_BURST_LIMIT/CHAT_COOLDOWN_SECONDS/CHAT_DIRECT_REPLY_TTL_DAYS + .env.example
- [ ] T-395 (@Builder, P1) — каноны: CHAT_SYSTEM_PROMPT + CHAT_COOLDOWN_PHRASES (4) + CHAT_ERROR_PHRASES (3) + тест-эталоны
- [ ] T-396 (@Builder, P1) — DirectChatService: token bucket + context partitioning + payload-порядок (R51-2) + Reply-отправка
- [ ] T-397 (@Builder, P1) — хендлер: Reply-на-бота (reply_to_message.from_user==bot_id) ИЛИ упоминание @username; wiring
- [ ] T-398 (@Builder, P1) — GraphRAG: memorize origin='bot_direct_reply' + метаданные + TTL + ORDER BY created_at ASC; фильтр от флуда других подсервисов
- [ ] T-399 (@Builder + @Reviewer, P1) — тесты DirectChat (триггеры/bucket/каноны/partitioning/metadata/ORDER BY) + 0 регрессий (база 2099) + ревью APPROVED
- [ ] T-400 (@Builder, P1) — README v2.36.0 + MEMORY

### Epic 51: Intelligent Caching (Token Optimization) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.36.0, P1)

> Полный трек — `plans/backlog.md` (Epic 51). Требования R51-1…R51-5, решение D189.
> Уровень 1 — Exact Match Cache: локальный SQLite/Redis кэш по ключу MD5(команда + нормализованный
> запрос/URL) → СГЕНЕРИРОВАННЫЙ ОТВЕТ БОТА; TTL 30 мин; повторная ссылка → НЕ лезет в Trafilatura/Tavily
> и НЕ дергает LLM — мгновенный токсичный ответ (FactCheck/SmartSearch/Web/YouTube). Уровень 2 — DeepSeek
> Prompt Caching: «Статичное — вверх, Динамичное — вниз»; строгий порядок payload для ВСЕХ LLM-вызовов:
> (1) System Prompt → НАЧАЛО; (2) User Resolution Map (алиасы/имена чата); (3) Bot Knowledge (RAG);
> (4) динамика (контекст/история/текст страницы) → КОНЕЦ. Тесты: (а) Token Bucket кулдаун; (б) Exact Match
> (второй вызов URL НЕ вызывает LLM); (в) system на индексе 0; (г) memorize мок с метаданными
> (timestamp/chat_id/user); (д) деплой git pull + systemctl restart. Каноны промптов/эталоны не трогать
> (только порядок секций); UX R13/R42 не менять; миграций БД нет; база 2099; v2.36.0. Без @Orchestrator.

- [ ] T-401 (@Architect, P1) — Section 59: дизайн MD5-нормализация/хранилище/TTL/LRU + Prompt Cache совместимость + безупречность эталонов; закрыть открытые вопросы 9–13
- [ ] T-402 (@Builder, P1) — smart_cache: MD5-ключ + TTL 30м + врезка ДО Trafilatura/Tavily/LLM (factcheck/search/youtube/web); кэш-хит → reply
- [ ] T-403 (@Builder, P1) — payload-билдер (system на 0-м индексе; user map; RAG; динамика в конце) для всех генераторов; эталоны-тесты порядка
- [ ] T-404 (@Builder + @Reviewer, P1) — тесты (а)–(г) + 0 регрессий (база 2099) + ревью APPROVED
- [ ] T-405 (@Builder, P1) — README v2.36.0 + MEMORY

### Epic 48–51: Релиз v2.36.0 (общий деплой, T-406/T-407) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅)

> Общий релиз Epics 48/49/50/51 (откат degraded + чекап-400 + DirectChat + Intelligent Caching).
> Коммит одними код+тесты (D123-стиль), пуш origin/master; прод .env: SUMMARY_DEGRADED_* отсутствуют
> (проверено) — подтвердить при деплое; при необходимости новых переменных (CHAT_*/SMART_CACHE_*) —
> бэкап `.env.bak.epic48_51` + добавление. Миграций БД нет ПО УМОЛЧАНИЮ (вопрос origin Epic 50 —
> по Section 58, идемпотентная миграция user_version при одобрении @Architect). Деплой:
> git pull --ff-only → systemctl restart admin_bot → active (running), новый PID → journalctl -n 50
> (0 traceback) → smoke: /summary (LLM или UX — НЕ degraded), чекап (без «база подавилась логами» при
> падении LLM), DirectChat (Reply боту + упоминание), кэш (повторный URL → мгновенный ответ).

- [ ] T-406 (@DevOps, P0) — коммит на русском + пуш origin/master (Epics 48–51 одним коммитом, D123-стиль)
- [ ] T-407 (@DevOps, P0) — деплой v2.36.0: git pull --ff-only; .env (проверка SUMMARY_DEGRADED_* отсутствуют, +CHAT_*/SMART_CACHE_* при необходимости); systemctl restart admin_bot; journalctl 0 traceback; smoke всех подсервисов

### Epic 47: Resilience — LLM-клиент и GraphRAG-память (прод-инцидент падений) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.35.1)

> Полный трек — `plans/backlog.md` (Epic 47). Требования R47-1…R47-6, решения D180–D185.
> Инцидент: 2 падения за сутки (01:00:02/03, 07:00:22 UTC) — graphrag memorize (summary_memory.py:631), LLM-клиент (llm_client.py:120), генератор саммари (summary_generator.py:124); пользователь получил «не смог сделать саммари потому что упал апи» и «база подавилась». Логи: LLMTimeoutError/httpx.ReadTimeout attempt=2 (factcheck), LLMError 502 after 3 attempts (summary). Текущее устройство: транспортные ConnectError/ReadError НЕ ретраятся (мгновенный LLMError, llm_client.py:87-89); backoff 0.5*2**n без капса/jitter; Retry-After не читается; худший случай ~181.5с; memorize → logger.exception (631-635), батч 8000 симв. теряется; summary без retry-once и деградации; фактчек/хуки логируют ERROR на ожидаемых LLMError. Решение: ретраи транзиентных (timeout/5xx/429/транспортные) с капс+jitter+Retry-After (прецедент YouTube Epic 41), WARNING вместо ERROR-шторма, memorize-повтор батча, summary retry-once/деградированный вывод, UX R13 — финальный fallback без изменений. Каноны промптов НЕ трогать; миграций нет; база 2070; v2.35.1 (прод eef5939). Без @Orchestrator.

- [ ] T-371 (@Architect, P0) — Section 56: дизайн resilience (LLM-клиент + memorize + summary + логи); закрыть открытые вопросы PM 1–7
- [ ] T-372 (@Builder, P0) — конфиг LLM_RETRY_*/budget + .env.example
- [ ] T-373 (@Builder, P0) — llm_client: ретраи транзиентных + капс/jitter + Retry-After + WARNING-логи
- [ ] T-374 (@Builder, P0) — memorize: WARNING вместо ERROR + повтор батча (факты не теряются)
- [ ] T-375 (@Builder, P0) — summary_generator: retry-once/деградированный вывод + классы логов
- [ ] T-376 (@Builder, P1) — фактчек/хуки: классы логов (LLMError → WARNING)
- [ ] T-377 (@Builder + @Reviewer, P0) — тесты новых веток + полный прогон 0 регрессий (база 2070) + ревью APPROVED
- [ ] T-378 (@Builder, P1) — README v2.35.1 + MEMORY
- [ ] T-379 (@DevOps, P0) — коммит + пуш v2.35.1 (код+тесты одним коммитом)
- [ ] T-380 (@DevOps, P0) — деплой БЕЗ миграций: git pull, restart, journalctl (0 ERROR-шторма memorize), smoke

### Epic 45: Betterstack SQL API (Checkup) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.35.0)

> Полный трек — `plans/backlog.md` (Epic 45). Требования R45-1…R45-5, решения D171–D174.
> Основная ступень CheckupLogsFetcher — SQL API: POST `eu-fsn-3-connect.betterstackdata.com:443`, Basic auth, `Content-type: plain/text`, SQL-тело, детерминированный парсинг **JSONEachRow** (вместо Pretty) → «Timestamp - Level - Message». Креды `CHECKUP_BETTERSTACK_SQL_HOST/USER/PASSWORD` (значения ТОЛЬКО @DevOps в прод .env, бэкап `.env.bak.epic45`; в планы — только имена, R17; в коде не логировать). Фолбек journalctl неприкосновенен; судьба легаси `BETTERSTACK_TOKEN/SOURCE_IDS/QUERY` и Telemetry-ступени Epic 44 — @Architect (Section 54). MCP — запасной вариант, НЕ основной. curl-верификация SQL API на проде — обязательный шаг деплоя. Общий релиз v2.35.0 с Epic 46. Без @Orchestrator.

- [ ] T-351 (@Architect, P0) — Section 54: дизайн SQL API + судьба легаси/Telemetry + каскад ступеней; закрыть открытые вопросы PM 1–6
- [ ] T-352 (@Builder, P0) — конфиг CHECKUP_BETTERSTACK_SQL_HOST/USER/PASSWORD + .env.example (только имена, R17)
- [ ] T-353 (@Builder, P0) — fetcher: POST + Basic + plain/text + JSONEachRow; 401/404/таймаут → каскад journalctl (фолбек без изменений)
- [ ] T-354 (@Builder + @Reviewer, P0) — тесты TestFetcherBetterstack под SQL API + полный прогон 0 регрессий (baseline 1976+ Epic 44) + ревью APPROVED
- [ ] T-355 (@Builder, P1) — README v2.35.0 + MEMORY
- [ ] T-356 (@DevOps, P0) — коммит + пуш (код+тесты одним коммитом)
- [ ] T-357 (@DevOps, P0) — деплой: .env.bak.epic45 + SQL-креды, git pull, restart, **curl-верификация SQL API (обязательный шаг)**, smoke чекап

### Epic 46: GraphRAG-память + диагностика (origin/TTL, Fact Extractor, гибридный RAG, аудит фактчека) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.35.0)

> Полный трек — `plans/backlog.md` (Epic 46). Требования R46-1…R46-8, решения D175–D179; каноны R46-2/R46-4 VERBATIM в backlog (промпт-экстрактор, XML `<context>/<user_gossip>/<bot_knowledge>`, RAG-инструкция).
> Шаг 0 (диагностика, уже выполнена): БД не повреждена (vec0 float[3072] self-heal, локов 0); первопричины: исторический dim-сдвиг 768→3072 (векторы потеряны, backfill'а нет), L3-архив пуст (ретеншн 30д, чату 4д — сжатие не запускалось), эпизодические 403 /v1/embeddings (решены .env в Epic 44). Миграция nodes/edges: +`origin TEXT` (chat_history|search_fact|youtube_content|web_content) +`expires_at INTEGER`; TTL: chat_history → NULL (вечно), остальные → 14 дней (`GRAPH_FACT_TTL_DAYS`), ленивое исключение из RAG (D175). `memorize_facts(raw_text, source_type)` в SmartModule/memory.py (фактически `services/summary_memory.py`): raw → DeepSeek (канон-промпт R46-2) → JSON-триплеты → embed (`gemini-embedding-001`, dim=3072, механизм НЕ менять) → SQLite origin/expires_at; токсичные ответы бота НЕ сохранять. Хуки fire-and-forget (`asyncio.create_task`, ДО генерации): search_service::research + factcheck_service::check_claim (после aggregator.search()), youtube_summarizer_service::summarize (после fetch_transcript), web_summarizer_service::summarize (после extractor.extract), summary_generator::_run (после get_window_messages). Гибридный RAG: новый entrypoint векторного поиска по запросу юзера для ВСЕХ пайплайнов, XML-канон, escape_xml_text, канон-инструкция во ВСЕ системные промпты (Checkup — @Architect). Фиксы Шага 0: EMBEDDING_DIM дефолт 3072 (или авто), 403-устойчивость + повторная активация vec, backfill из smart_archive_facts, PRAGMA user_version, разделение логов vec vs 403. Аудит фактчека (код НЕ менять) → `plans/FACTCHECK_AUDIT.md`. Общий релиз v2.35.0 с Epic 45. Без @Orchestrator.

- [ ] T-358 (@Architect, P0) — Section 55: дизайн GraphRAG v2 + каноны VERBATIM; закрыть открытые вопросы PM 1–9
- [ ] T-359 (@Builder, P0) — конфиг: EMBEDDING_DIM (3072/авто), GRAPH_FACT_TTL_DAYS=14 + .env.example
- [ ] T-360 (@Builder, P0) — миграции: ALTER TABLE origin/expires_at + PRAGMA user_version + entity_type CHECK + скрипт для прод (идемпотентный)
- [ ] T-361 (@Builder, P0) — memorize_facts (канон-промпт R46-2 VERBATIM, DeepSeek, JSON try/except, embed, origin/expires_at)
- [ ] T-362 (@Builder, P0) — фиксы Шага 0: EMBEDDING_DIM, 403-ретраи + повторная активация vec, backfill, разделение логов
- [ ] T-363 (@Builder, P0) — хуки 4 пайплайнов (fire-and-forget, тихий лог Betterstack при падении)
- [ ] T-364 (@Builder, P0) — гибридный RAG: entrypoint + XML-канон + TTL-фильтр (ленивый WHERE) + escape_xml_text
- [ ] T-365 (@Builder, P0) — правки ВСЕХ системных промптов + канон-инструкция R46-4 VERBATIM + эталоны (Checkup — по Section 55)
- [ ] T-366 (@Builder + @Reviewer, P0) — тесты TTL/Extractor (FakeLLM)/миграционные/эталоны + полный прогон 0 регрессий (база 1981) + ревью APPROVED
- [ ] T-367 (@Builder, P1) — README v2.35.0 + MEMORY
- [ ] T-368 (@Builder, P1) — аудит фактчека → plans/FACTCHECK_AUDIT.md (код НЕ меняем)
- [ ] T-369 (@DevOps, P0) — коммит + пуш v2.35.0 (Epic 45+46, код+миграции+тесты одним коммитом)
- [ ] T-370 (@DevOps, P0) — деплой: git pull → скрипт миграции (на остановленном боте) → restart → journalctl (0 старых ошибок векторной БД)

### Epic 44: Новый /info-текст + фикс прав удаления + Betterstack Telemetry — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.34.1)

> Полный трек — `plans/backlog.md` (Epic 44). Требования R44-1…R44-3 (канон R44-1 VERBATIM в backlog), решения D166–D170.
> R44-1: новый текст /info (HTML: `<b>`/`<code>`/`<a>`; суть менять нельзя) → Section 53, `DEFAULT_INFO_TEXT`, `info_text.md` в репо (старый блок 52.4 — «заменён в Section 53»). R44-2: /info при отказе delete → пул прав И справка (убрать `return`, handlers/info.py:50-59). R44-3: облачная ступень Checkup через Telemetry API token (Bearer, env `BETTERSTACK_TOKEN`) + конфигурируемый `CHECKUP_BETTERSTACK_URL` (эндпоинт — @Architect); фолбек journalctl неприкосновенен; curl-верификация на проде обязательна (200 → схема зафиксирована; 401/404 → честный отчёт, каскад на journalctl). Uptime token НЕ используется. Baseline: прод v2.34.0 (`cb339d6`, PID 990054), 1976 тестов. Без @Orchestrator.

- [ ] T-343 (@Architect, P0) — Section 53: HTML-канон нового DEFAULT_INFO_TEXT + пометка 52.4 + тест-хелпер + фикс-дизайн reply-таргета; веб-ресёрч эндпоинта Betterstack (telemetry JSON:API vs SQL/Query API ClickHouse); закрыть открытые вопросы PM 1–6
- [ ] T-344 (@Builder, P0) — новый DEFAULT_INFO_TEXT байт-в-байт + info_text.md в репо (R44-1, D167)
- [ ] T-345 (@Builder, P0) — фикс handlers/info.py:50-59: убрать return, пул прав → ПРОДОЛЖИТЬ (R44-2, D168)
- [ ] T-346 (@Builder, P0) — fetcher: CHECKUP_BETTERSTACK_URL + Bearer Telemetry token + парсер новой схемы; фолбек journalctl без изменений (R44-3, D169)
- [ ] T-347 (@Builder + @Reviewer, P0) — тесты: test_info_service/test_info_handlers #2/#3/test_checkup_logs_fetcher переписать под новый канон/поведение; полный прогон 0 регрессий (baseline 1976); ревью APPROVED (D170)
- [ ] T-348 (@Builder, P1) — README v2.34.1 + MEMORY
- [ ] T-349 (@DevOps, P0) — коммит на русском + пуш master (код+канон+тесты+info_text.md одним коммитом, D123-стиль)
- [ ] T-350 (@DevOps, P0) — деплой v2.34.1: .env.bak.epic44 + BETTERSTACK_TOKEN (Telemetry) в прод .env, бэкап+checkout info_text.md перед pull, git pull --ff-only, restart, curl-верификация эндпоинта (обязательный шаг), smoke /info+чекап

### Epic 41: YouTube engine hardening (ru-first, ретраи 4–5 + токсичные сообщения, логи фолбека) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-19, Шаг 1 @PM ✅, target v2.33.1)

> Полный трек — `plans/backlog.md` (Epic 41). Требования R41-1…R41-5 (R41-4 = NON-GOAL: BetterStack-алерт ОТМЕНЁН пользователем), решения D151–D157.
> Контекст: инцидент 2026-08-19 01:24:55 (`v-6q7YMmjnM` — 429 на 'en' + пустой timedtext через DC-выход VPN; флап ~50/50). ru-first (`ignoreerrors: True` + skip языков без filepath + `extract_info → None`), ретраи в движке (классификация ДО обёртки; yt-dlp N → фолбек transcript-api N → исключение), колбэк `on_retry(attempt, max_attempts)` (kwarg; прецеденты search_aggregator.py:64, message_counter.py:33), пул `YOUTUBE_RETRY_PHRASES` (~5 вариаций, random.choice, строчными; канон создаст @Architect; пулы 5.1–5.7 не трогать), video_id в handler-логи, HTTP-статус/размер тела в фолбек-WARNING.
> Прокси уже стоит (гейт Epic 40 пройден) — повторный полный гейт не обязателен. Без @Orchestrator.

- [ ] T-315 (@Architect, P0) — дизайн Section 50 + КАНОН YOUTUBE_RETRY_PHRASES (5 токсичных вариаций, строчными, дословно); закрыть открытые вопросы PM 1–4 (число ретраев 4/5, backoff-схема)
- [x] T-316 (@Builder, P0) — движок: ru-first + ретраи с backoff + классификация + `on_retry` kwarg (R41-1/R41-2, D151–D154)
- [x] T-317 (@Builder, P0) — пул YOUTUBE_RETRY_PHRASES + тест-канон (R41-2, D155)
- [x] T-318 (@Builder, P0) — сервис+хендлер: on_retry-замыкание → `_reply`, video_id в handler-логи, логи фолбека (R41-2/R41-3/R41-5, D153)
- [x] T-319 (@Builder + @Reviewer, P0) — тесты: 2 сломанных ассерта + ~15–20 кейсов (monkeypatch asyncio.sleep); полный прогон 0 регрессий (baseline 1796); ревью APPROVED
- [x] T-320 (@Builder, P1) — README v2.33.1 + MEMORY
- [x] T-321 (@DevOps, P0) — коммит на русском + пуш master — **Done (Шаг 7, коммит `eaa84c5`, пуш `5c99566..eaa84c5`)**
- [x] T-322 (@DevOps, P0) — деплой v2.33.1: git pull, restart, journalctl -n 50, живой smoke (полный гейт не обязателен) — **Done (Шаг 7: прод ff `bb472ba..eaa84c5`, PID 986288, proxy=set, 0 новых traceback, xray без изменений)**

### Epic 42: Checkup (самодиагностика, в SmartModule) — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.34.0)

> Полный трек — `plans/backlog.md` (Epic 42). Требования R42-1…R42-6, решения D158–D162.
> Триггеры: чекап / ты в порядке / живой собака / пульс бота / чекни здоровье / как сервак (реплай, кулдаун 300с, MAX_SYMBOLS 3000). Каскад: Betterstack `/api/v2/events` (Bearer из `LOGTAIL_SOURCE_TOKEN`, D160) → фолбек journalctl (D161) → LLM DeepSeek с токсичным отчётом. Пулы `CHECKUP_FALLBACK/DEAD/LLM_ERROR` дословно из ТЗ; троттлинг — `THROTTLE_PHRASES` (5.1). Роутер 0g после 0f web под SUMMARY_ENABLED. Без @Orchestrator.

- [ ] T-323 (@Architect, P0) — дизайн Section 51 + каноны пулов/CHECKUP_SYSTEM_PROMPT (байт-в-байт); закрыть открытые вопросы PM 1–5
- [ ] T-324 (@Builder, P0) — конфиг CHECKUP_COOLDOWN_SECONDS=300 / CHECKUP_MAX_SYMBOLS=3000 + токен (D160)
- [ ] T-325 (@Builder, P0) — пулы CHECKUP_FALLBACK/DEAD/LLM_ERROR + тест-канон
- [ ] T-326 (@Builder, P0) — CHECKUP_SYSTEM_PROMPT (.replace {max_symbols}, байт-в-байт)
- [ ] T-327 (@Builder, P0) — fetcher-каскад fetch_system_logs (4 шага, приписка фолбека)
- [ ] T-328 (@Builder, P0) — checkup-сервис + хендлер 0g (триггеры-regex, кулдаун 300с)
- [ ] T-329 (@Builder, P0) — wiring bot.py + test_summary_handlers router_count 13→14
- [ ] T-330 (@Builder + @Reviewer, P0) — тесты (~20) + полный прогон + ревью (baseline 1796)
- [ ] T-331 (@Builder, P1) — README v2.34.0 (Checkup) + MEMORY

### Epic 43: /info + live-редактор /edit_info — 🚧 IN PROGRESS (одобрено пользователем, 2026-08-20, Шаг 1 @PM ✅, target v2.34.0)

> Полный трек — `plans/backlog.md` (Epic 43). Требования R43-1…R43-5, решения D162–D165.
> /info: delete команды (нет прав → пул), текст из `info_text.md` (файл на диске + кэш), set_my_commands «Справка по фичам бота», кулдаун 300с. /edit_info: только ADMIN_USER_ID, рендер-валидация превью в DM (не спамить чат), успех → файл+кэш. Пулы `INFO_*` дословно из ТЗ; троттлинг — `THROTTLE_PHRASES` (5.1). Регистрация безусловная (по прецеденту admin_commands, Epic 9). Деплой v2.34.0 общий с Epic 42 (T-341/T-342). Без @Orchestrator.

- [ ] T-332 (@Architect, P0) — дизайн Section 52 + канон дефолтного info_text.md; закрыть открытые вопросы PM 1–5
- [ ] T-333 (@Builder, P0) — конфиг INFO_COOLDOWN_SECONDS=300 + INFO_TEXT_FILE
- [ ] T-334 (@Builder, P0) — пулы INFO_NO_DELETE_RIGHTS/NOT_ADMIN/BAD_MARKUP/EDIT_OK + тест-канон
- [ ] T-335 (@Builder, P0) — info_service: info_text.md + кэш + дефолтный текст
- [ ] T-336 (@Builder, P0) — хендлер /info (delete → пул, экранирование, кулдаун, set_my_commands)
- [ ] T-337 (@Builder, P0) — хендлер /edit_info (ADMIN_USER_ID, DM-превью-валидация, файл+кэш)
- [ ] T-338 (@Builder, P0) — wiring + test_bot_commands len(_COMMANDS) 1→2
- [ ] T-339 (@Builder + @Reviewer, P0) — тесты 100% /info /edit_info, моки ФС, set_my_commands + ревью
- [ ] T-340 (@Builder, P1) — README v2.34.0 (/info) + MEMORY
- [ ] T-341 (@DevOps, P0) — коммит + пуш v2.34.0 (Epic 42+43)
- [ ] T-342 (@DevOps, P0) — деплой v2.34.0: git pull, journalctl-права (D161), curl Bearer (D160), restart, smoke (чекап + /info + /edit_info)

## 🔍 In Review

*(пусто)*

## ✅ Done

### Epic 40: YouTube VPN-прокси (xray) + разблокировка деплоя Epic 39 — ✅ DEPLOYED & ARCHIVED (v2.33.0, коммит `bb472ba`, прод PID 980709, 1796 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-19, Шаг 1 Epic 41). Полный трек — `plans/backlog.md` (Epic 40).
> **Итог:** T-309…T-314 ALL DONE (по plans/MEMORY.md, Шаг 8). xray-core 26.3.27 + http-inbound 127.0.0.1:10808 с accounts (эмпирика: поле users молча игнорируется) + systemd enable/Restart=always; выходной IP 195.181.173.207 (AS60068); гейт 49.7 ПРОЙДЕН (3/4: sNhhvQGsMEc/cUbIkNUFs-4/aPYGbtkSE7A OK; dQw4w9WgXcQ — известный кейс пустого timedtext, не блок). Epic 39 разблокирован: прод v2.33.0 активирован, **PID 980709**, 0 traceback, proxy=set. Код не менялся. Тесты: 1796 passed (1789 + 7).

### Epic 39: YouTube engine fix — yt-dlp → youtube-transcript-api фолбек — ✅ DEPLOYED & ARCHIVED (v2.33.0, коммит `bb472ba`, прод PID 980709, 1796 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-19, Шаг 1 Epic 41). Полный трек — `plans/backlog.md` (Epic 39).
> **Итог:** T-302…T-306 DONE (Section 48, yt-dlp primary + фолбек transcript-api 0.6.3, +2 ключа настроек), T-307 коммит `bb472ba`; T-308 DEPLOY_BLOCKED на гейте T-308-C был СНЯТ Epic 40 (гейт 3/4 через прокси) → v2.33.0 в проде (PID 980709, 0 traceback).

### Epic 38: Refactoring WebSummarizer — Jina → Trafilatura + Tavily/Exa фолбеки — ✅ DEPLOYED & ARCHIVED (v2.32.1, коммит `f0bc4d6`, прод PID 974412, 1763 теста)

> Перенесено из In Progress при архивации (PM, 2026-08-19, Шаг 1 Epic 39). Полный трек — `plans/backlog.md` (Epic 38).
> **Итог:** T-294…T-301 ALL DONE. @Architect: Section 47; @Builder: Jina полностью удалён, WebContentExtractor (trafilatura → Tavily → Exa → исключение), wiring, +тесты; @Reviewer: APPROVED; @DevOps: коммит `f0bc4d6` «refactor(smartmodule): Epic 38 — WebSummarizer: Jina → Trafilatura + Tavily/Exa (v2.32.1)» + деплой v2.32.1 (pip install trafilatura, .env без JINA_API_KEY, бэкап `.env.bak.epic38`, PID 974412, 0 traceback). **ЭПИК 38 ЗАКРЫТ. Прод v2.32.1. Тесты: 1763 passed / 0 failed (1757 baseline + 6).**

- [x] T-294 (@Architect, P0) — дизайн Section 47 — **Done (Шаг 2)**
- [x] T-295 (@Builder, P0) — удаление Jina Reader (R38-2) — **Done**
- [x] T-296 (@Builder, P0) — WebContentExtractor + каскад trafilatura→Tavily→Exa (R38-3) — **Done**
- [x] T-297 (@Builder, P0) — wiring WebSummarizer (R38-3/R38-4, D135) — **Done**
- [x] T-298 (@Builder + @Reviewer, P0) — тесты + полный прогон 1763 passed + ревью APPROVED (R38-5) — **Done**
- [x] T-299 (@Builder, P1) — README v2.32.1 + MEMORY — **Done**
- [x] T-300 (@DevOps, P0) — коммит `f0bc4d6` + пуш — **Done (Шаг 7)**
- [x] T-301 (@DevOps, P0) — деплой v2.32.1 (PID 974412, 0 traceback) — **Done (Шаг 7)**

### Epic 37: SmartModule — YouTubeSummarizer + WebSummarizer — ✅ DEPLOYED & ARCHIVED (v2.32.0, коммит `747cb99`, прод PID 969047, 1757 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-19, Шаг 1 Epic 38). Полный трек — `plans/backlog.md` (Epic 37).
> **Итог:** T-281…T-293 ALL DONE. @Architect: Section 46 (46.1–46.15); @Builder: 19 новых файлов + 7 правок (движки YouTube/Jina, промпты-эталоны, пулы 5.6/5.7, сервисы, хендлеры 0e/0f, wiring), 1757 passed / 0 failed (1593 + 164); @Reviewer: APPROVED; @DevOps: коммит `747cb99` (31 файл) + деплой v2.32.0 (git pull ff, .env +5 ключей, бэкап `.env.bak.epic37`, PID 969047, 0 traceback).
> **Прод-дефекты движков (пост-деплой):** Web-фича мертва (Jina 401: JINA_API_KEY пуст + блок анонимных запросов AS36352; селектор не вычленял статью) → **Epic 38** (рефакторинг WebSummarizer, v2.32.1, ЗАКРЫТ); YouTube-фича сломана IP-блоком YouTube → **Epic 39** (одобрено пользователем, In Progress, v2.33.0). **ЭПИК 37 АРХИВИРОВАН. Прод v2.32.0.**

- [x] T-281 (@Architect, P0) — дизайн Section 46 в ARCHITECTURE.md — **Done (Шаги 2–3)**
- [x] T-282…T-289 (@Builder, P0) — конфиг, промпты, движки, пулы, сервисы, хендлеры, wiring — **Done (Шаг 4)**
- [x] T-290 (@Builder + @Reviewer, P0) — тесты + полный прогон 1757 passed + ревью APPROVED — **Done (Шаги 5–6)**
- [x] T-291 (@Builder, P1) — README v2.32.0 + MEMORY — **Done**
- [x] T-292 (@DevOps, P0) — коммит `747cb99` + пуш — **Done (Шаг 7)**
- [x] T-293 (@DevOps, P0) — деплой v2.32.0 (PID 969047, 0 traceback) — **Done (Шаг 7)**

### Epic 36: FactCheck — парсинг caption альбомов + адаптивный размер ответов — ✅ DEPLOYED & ARCHIVED (v2.31.3, коммит `2e26690`, прод PID 951645, 1593 тестов)

> Перенесено из In Progress при архивации (PM, 2026-08-18, Шаг 1 Epic 37). Полный трек — `plans/backlog.md` (Epic 36).
> **Итог:** T-274…T-280 ALL DONE. @Architect: Section 45 (буфер `MediaGroupCaptionBuffer` TTL 60с/LRU 100 + промпты-эталоны 42.5.1/42.5.2); @Builder: буфер альбомов (fill в observer 0a, чтение в `_extract_target_text`), блок «ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА» в обоих промптах, +20 тестов, README v2.31.3; @Reviewer: APPROVED (личный прогон 1593 passed / 0 failed / 0 skipped, BLOCKER/MAJOR НЕТ); @DevOps: коммит `2e26690` (19 файлов, +982/−28) + пуш (`585da8d..2e26690`) + деплой (git pull ff, PID 951645, 0 traceback). **ЭПИК 36 ЗАКРЫТ. Прод v2.31.3. Тесты: 1593 passed / 0 failed (1573 + 20).**

- [x] T-274 (@Architect, P0) — дизайн буфера media groups + правки промптов (ARCHITECTURE.md Section 45) — **Done (Шаг 2)**
- [x] T-275 (@Builder, P0) — буфер/парсинг caption альбомов в factcheck — **Done (Шаг 4: `services/media_group_buffer.py` TTL 60с/LRU 100 + fill в summary_observer 0a + чтение в `_extract_target_text`)**
- [x] T-276 (@Builder, P0) — блок «ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА» в обоих промптах + эталоны 42.5.1/42.5.2 + тесты (одним коммитом, D123) — **Done (Шаг 4)**
- [x] T-277 (@Builder, P1) — тесты, 0 регрессий — **Done (Шаг 4: +20 тестов, 1593 passed / 0 failed, `git diff --check` чист)**
- [x] T-278 (@Reviewer, P0) — ревью — **Шаг 5 ✅ APPROVED (личный прогон 1593 passed / 0 failed / 0 skipped; BLOCKER/MAJOR НЕТ, 4 MINOR не-блокера)**
- [x] T-279 (@DevOps, P0) — коммит на русском + пуш + деплой v2.31.3 — **Done (Шаг 7: коммит `2e26690`, 19 файлов +982/−28, пуш `585da8d..2e26690`, деплой ff, PID 951645, 0 traceback)**
- [x] T-280 (@Builder, P1) — README changelog — **Done (Шаг 4, changelog «✨ Новое в v2.31.3 (Epic 36)»)**

### Epic 35: Hotfix — alan_greeting тройной greeting (race condition F7v2) — ✅ DEPLOYED & ARCHIVED (v2.31.2, коммит `585da8d`, прод PID 950693, 1573 тестов)

> Перенесено из In Progress при архивации (Memory, 2026-08-17, Шаг 8). Полный трек — `plans/backlog.md` (Epic 35).
> **Итог:** T-268…T-273 ALL DONE. @Architect: RCA подтверждён (check-then-act race F7v2/join, 3 параллельных апдейта) + Section 44; @Builder: per-chat `asyncio.Lock` (`_greeting_locks`/`_get_greeting_lock`) + claim кулдауна/ts ДО `await _send_greeting()` + rollback (handlers/alan_greeting.py, handlers/alan.py), +9 тестов, README v2.31.2; @Reviewer: APPROVED (личный прогон 1573 passed / 0 failed); @DevOps: коммит `585da8d` «fix(alan): Epic 35 — race condition тройного greeting F7v2 (v2.31.2)» (**9 файлов, +764/−79**) + пуш origin (`5fb532b..585da8d`) + деплой (git pull --ff-only, `.env`/зависимости не тронуты, `systemctl restart admin_bot` → active (running) **PID 950693**, journalctl 0 traceback). **ЭПИК 35 ЗАКРЫТ (Шаг 8). Прод v2.31.2. Epics 1–35 ALL DEPLOYED. Тесты: 1573 passed / 0 failed (1564 + 9).**

- [x] T-268 (@Architect, P0) — RCA-подтверждение по логам + дизайн фикса в ARCHITECTURE.md (Section 44) — **Done (Шаг 2)**
- [x] T-269 (@Builder, P0) — реализация фикса race condition (по дизайну Architect) — **Done (Шаг 4: per-chat `asyncio.Lock` (`_greeting_locks`/`_get_greeting_lock` в alan_greeting.py, общий для F7v2 + обоих join-путей) + claim-before-send (кулдаун и ts записываются ДО `await _send_greeting()`, `ts_written`-флаг, rollback при неудаче)**
- [x] T-270 (@Builder, P1) — юнит/интеграционные тесты на конкурентный сценарий (3 параллельных хендлера → ровно 1 greeting), 0 регрессий (baseline 1564) — **Done (Шаг 4, +9 тестов, 1573 passed / 0 failed)**
- [x] T-271 (@Reviewer, P0) — ревью — **Шаг 5 ✅ APPROVED (2026-08-17: соответствие Section 44 дословно, дедлоков нет, BLOCKER/MAJOR НЕТ; личный прогон 1573 passed / 0 failed / 0 skipped; diff-check чист, секретов 0)**
- [x] T-272 (@DevOps, P0) — коммит на русском + пуш + деплой v2.31.2 (git pull, restart, status, проверка логов) — **Done (Шаг 7, коммит `585da8d`, пуш `5fb532b..585da8d`, деплой ff, прод v2.31.2, PID 950693, 0 traceback)**
- [x] T-273 (@Builder, P1) — README changelog v2.31.2 (ироничный тон) — **Done (Шаг 4, changelog «🔧 Исправлено в v2.31.2 (Epic 35)»)**

### Epic 34: Hotfix — SmartSearch TelegramBadRequest «message to be replied not found» — ✅ DEPLOYED & ARCHIVED (v2.31.1, коммит `5fb532b`, прод PID 949763, 1564 тестов)

> Перенесено из In Progress при архивации (Memory, 2026-08-17, Шаг 8). Полный трек — `plans/backlog.md` (Epic 34).
> **Итог:** T-261…T-267 ALL DONE. @Architect: RCA подтверждён + Section 43 (43.1–43.6); @Builder: `_send_once` fallback в `services/smartmodule_utils.py` (хендлеры БЕЗ правок), +9 тестов, README v2.31.1; @Reviewer: APPROVED (личный прогон 1564 passed / 0 failed); @DevOps: коммит `5fb532b` «fix(smartmodule): Epic 34 — fallback при удалённом reply-таргете SmartSearch (v2.31.1)» (**9 файлов, +621/−49**) + пуш origin (`1172fb5..5fb532b`) + деплой (git pull --ff-only, `.env`/venv не тронуты, `systemctl restart admin_bot` → active (running) **PID 949763**, journalctl 0 traceback, смоук OK). **ЭПИК 34 ЗАКРЫТ (Шаг 8). Прод v2.31.1. Epics 1–34 ALL DEPLOYED. Тесты: 1564 passed / 0 failed (1555 + 9).**

- [x] T-261 (@Architect, P0) — RCA-подтверждение + дизайн фикса (ARCHITECTURE.md Section 43) — **Done (Шаг 2)**
- [x] T-262 (@Builder, P0) — fallback «retry без reply_to_message_id» в smartmodule_utils (send_chunked_reply/_reply) + логирование — **Done (Шаг 4, `_send_once`/`_is_reply_target_gone`, WARNING→INFO)**
- [x] T-263 (@Builder, P1) — применение фолбека в handlers/search.py (+ factcheck.py при необходимости), без дублей — **Done (Шаг 4, хендлеры БЕЗ правок, 43.3; доказано тестами #8/#9)**
- [x] T-264 (@Builder, P1) — юнит-тесты fallback (мок bot.send_message: 1-й TelegramBadRequest → 2-й без reply OK), 0 регрессий (baseline 1555) — **Done (Шаг 4, +9 тестов, 1564 passed / 0 failed)**
- [x] T-265 (@Reviewer, P0) — code review — **Done (Шаг 5, APPROVED: личный прогон 1564 passed / 0 failed, diff-check чист, хендлеры не тронуты, секретов нет; BLOCKER/MAJOR НЕТ)**
- [x] T-266 (@DevOps, P0) — коммит на русском + пуш + деплой v2.31.1 (git pull, restart, status) — **Done (Шаг 7, коммит `5fb532b`, прод v2.31.1, PID 949763, 0 traceback)**
- [x] T-267 (@Builder, P1) — README-фикс при необходимости (или skip) — **Done (Шаг 4, changelog «🔧 Исправлено в v2.31.1 (Epic 34)»)**

### Epic 33: SmartModule Extension — FactCheck + SmartSearch + SearchAggregator — ✅ DEPLOYED & ARCHIVED (v2.31.0, коммит `1172fb5`, 1555 тестов, прод PID 948950)

> Перенесено из In Progress при архивации (Memory, 2026-08-17, Шаг 8). Полный трек — `plans/backlog.md` (Epic 33).
> **Итог:** T-249…T-260 ALL DONE. @Architect: Section 42 (42.1–42.12), D109 RESOLVED (промпты 42.5.1/42.5.2 дословно); @Builder: конфиг 6 ключей, SearchAggregator (Tavily→Exa→DDG→AllSearchEnginesFailedException), хендлеры factcheck (0c) / search (0d), пулы 5.1–5.5 байт-в-байт, промпты байт-в-байт, cleanup/чанкинг/logger.exception, README v2.31.0; @Reviewer: NEEDS FIXES → фиксы → **APPROVED** (1555 passed лично: 1392 + 150 + 4 интеграционных + 9 хелперов, 0 failed); @DevOps: коммит `1172fb5` «feat(smartmodule): Epic 33 — FactCheck и SmartSearch с SearchAggregator (v2.31.0)» (**32 файла, +3610/−43**) + пуш, деплой (git pull ff `2bad5ff..1172fb5`; pip install duckduckgo-search 8.1.1; .env +6 ключей: EXA_API_KEY/TAVILY_API_KEY/SEARCH_MAX_SYMBOLS=4000/FACTCHECK_MAX_SYMBOLS=4000/SEARCH_COOLDOWN_SECONDS=300/FACTCHECK_COOLDOWN_SECONDS=300, бэкап `.env.bak.epic33`) → active (running) **PID 948950**, 0 traceback, «SmartModule FactCheck + SmartSearch (Epic 33) initialized». **ЭПИК 33 ЗАКРЫТ (Шаг 8). Прод v2.31.0. Epics 1–33 ALL DEPLOYED.**

- [x] T-249 (@Architect, P0) — дизайн Section 42 + D109 RESOLVED — **Done (Шаг 2)**
- [x] T-250 (@Builder, P0) — конфиг 6 ключей + валидация (R33-1, D104) — **Done (Шаг 4a)**
- [x] T-251 (@Builder, P0) — SearchAggregator: каскад Tavily→Exa→DDG (R33-2, D105) — **Done (Шаг 4a)**
- [x] T-252 (@Builder, P0) — FactCheck-хендлер (R33-3, D106/D107) — **Done (Шаг 4a)**
- [x] T-253 (@Builder, P0) — SmartSearch-хендлер (R33-4, D106/D107) — **Done (Шаг 4a)**
- [x] T-254 (@Builder, P1) — пулы 5.1–5.5 дословно (R33-5, D108) — **Done (Шаг 4a)**
- [x] T-255 (@Builder, P1) — промпты байт-в-байт (R33-6) — **Done (Шаг 4a)**
- [x] T-256 (@Builder, P1) — надёжность: cleanup/чанкинг/логи (R33-7, D110) — **Done (Шаг 4a)**
- [x] T-257 (@Builder + @Reviewer, P0) — тесты + полный прогон + ревью APPROVED (1555 passed) — **Done (Шаг 5)**
- [x] T-258 (@Builder, P1) — README v2.31.0 + .env.example (R33-8) — **Done**
- [x] T-259 (@DevOps, P0) — коммит `1172fb5` + пуш (32 файла, +3610/−43) — **Done**
- [x] T-260 (@DevOps, P0) — деплой v2.31.0 (PID 948950, 6 ключей .env, duckduckgo-search 8.1.1, 0 traceback) — **Done (Шаг 8)**

### Epic 32: Фикс гифки Славика + сервис Оли (caption/репост) + SUMMARY_THROTTLE_SECONDS=300 — ✅ DEPLOYED & ARCHIVED (v2.30.0, коммит `2bad5ff`, 1392 теста, прод PID 942078)

> Перенесено из Backlog при архивации (PM, 2026-08-17, Шаг 1 Epic 33). Полный трек — `plans/backlog.md` (Epic 32).
> **Итог:** T-242…T-248 ALL DONE. @Builder: гифка Славика (settings-снапшот GIF_PATH/GIF_INTERVAL, is_file-guard → WARNING+skip, ERROR/INFO-логи вместо глушения, D99), Оля (`_normalize_caption` + триггер `@saveasbot` + origin-матрица MessageOriginUser/Channel/HiddenUser, D100–D102), тесты **1392 passed** (1366 + 26 новых, 0 failed), ревью @Reviewer APPROVED; @DevOps: прод .env `SUMMARY_THROTTLE_SECONDS=300.0` (D103), коммит `2bad5ff` «fix(media): Epic 32 — починен Славик (stale путь гифки), Оля теперь только caption/репост, таймаут саммари 300с на проде (v2.30.0)» + пуш, деплой (git pull ff `0f25c7e..2bad5ff`; .env: удалён устаревший `GIF_PATH`, +`SUMMARY_THROTTLE_SECONDS=300.0`, +`OLYA_SAVEASBOT_USER_IDS=523131145`, бэкап `.env.bak.epic32`) → active (running) **PID 942078**, 0 traceback, WARNING «GIF file not found» отсутствует. **ЭПИК 32 ЗАКРЫТ. Прод v2.30.0. Epics 1–32 ALL DEPLOYED.**

- [x] T-242 (@Builder, P0) — гифка Славика (R32-1, D99) — **Done**
- [x] T-243 (@Builder, P0) — Оля: нормализация caption + репосты (R32-2, D100/D101/D102) — **Done**
- [x] T-244 (@DevOps, P0) — прод SUMMARY_THROTTLE_SECONDS=300.0 (R32-3, D103) — **Done**
- [x] T-245 (@Builder, P1) — тесты + полный прогон (1392 passed) — **Done**
- [x] T-246 (@Builder, P1) — README v2.30.0 + .env.example — **Done**
- [x] T-247 (@DevOps, P0) — коммит `2bad5ff` + пуш — **Done**
- [x] T-248 (@DevOps, P0) — деплой v2.30.0 (PID 942078, 0 traceback) — **Done**

### Epic 31: /summary для всех + setMyCommands + таймаут-фразы — ✅ DEPLOYED & ARCHIVED (v2.29.0, 1366 тестов)

> Перенесено из Backlog/In Review при архивации (PM, 2026-08-17). Полный трек — `plans/backlog.md` (Epic 31).
> **Итог:** T-235…T-241 ALL DONE. @Builder: `SUMMARY_ADMIN_ONLY` + allow-check (D94), `services/bot_commands.py` (setMyCommands, BotCommandScopeDefault, «set_my_commands ok»), `_THROTTLE_PHRASES` (7) + `format_remaining_seconds`, тесты **1366 passed** (1327 + 39 новых, 0 failed/skipped); @Reviewer T-238-E **APPROVED** (2026-08-17); T-239 README v2.29.0 + .env.example; @DevOps T-240 коммит + пуш, T-241 деплой: .env `ALLOWED_SUMMARY_IDS=` пусто + `SUMMARY_ADMIN_ONLY=False` (бэкап `.env.bak.epic31`), restart → active (running), «set_my_commands ok», 0 traceback, /summary доступен всем. **ЭПИК 31 ЗАКРЫТ. Прод v2.29.0. Эпики 1–31 ALL DEPLOYED.**

- [x] T-235 (@Builder, P0) — `SUMMARY_ADMIN_ONLY` + allow-check D94 — **Done**
- [x] T-236 (@Builder, P0) — `services/bot_commands.py` + вызов в on_startup — **Done**
- [x] T-237 (@Builder, P0) — `_THROTTLE_PHRASES` (7) + `format_remaining_seconds` + reply-ветка — **Done**
- [x] T-238 (@Builder + @Reviewer, P0) — тесты 1366 passed + ревью — **Done (APPROVED)**
- [x] T-239 (@Builder, P1) — README v2.29.0 + .env.example — **Done**
- [x] T-240 (@DevOps, P0) — коммит + пуш — **Done**
- [x] T-241 (@DevOps, P0) — деплой v2.29.0 (ALLOWED_SUMMARY_IDS пусто, SUMMARY_ADMIN_ONLY=False) — **Done**

### Epic 30: Common Expansion — selfdev/work-реакции, goodmorning-рассылка, фикс нумерации промпта — ✅ DEPLOYED (v2.28.0, коммит `714a4f6`, 1327 тестов, прод PID 939545)

> Перенесено из Backlog/In Progress/In Review при архивации (PM, 2026-08-17). Полный трек — `plans/backlog.md` (Epic 30, статус DEPLOYED).
> **Итог:** T-227…T-234 ALL DONE. @Builder: selfdev (SELFDEV_WORDS 48/фраз 17, 87 юнитов), work (WORK_WORDS 128/фраз 31, 183 юнита), goodmorning (captions 6 = 3 канона + 3 новых, relay, APScheduler, 39 юнитов), фикс нумерации промпта 1–6 (D90, байт-в-байт ✅); T-231 — @Builder + @Reviewer **APPROVED** (1327 passed: 1002 baseline + 325 новых, 0 failed/skipped, пересечения списков ∅, `git diff --check` чист); T-232 — README v2.28.0 + .env.example; T-233/T-234 (@DevOps) — коммит `714a4f6` «feat(common): Epic 30 — selfdev/work-реакции, goodmorning-рассылка и фикс нумерации промпта (v2.28.0)» (30 файлов, 8 медиа) + пуш + деплой: git pull ff `7160a33..714a4f6`, .env (бэкап `.env.bak.epic30`: GOODMORNING_TARGET_CHAT_IDS=-1002661910336 ВКЛЮЧЕНА, SELFDEV/WORK_COOLDOWN=5m), restart → active (running) **PID 939545**, «Goodmorning scheduler started (07:00 Asia/Yekaterinburg, 1 chats)», 0 traceback. Шаг 8 (@Memory): docs-коммит `4b50272`. **ЭПИК 30 ЗАКРЫТ (Шаг 8), Epics 1–30 ALL DEPLOYED.**

- [x] T-227 (@Builder, P0) — selfdev-функция (R30-1, D85/D87/D92) — **Done** (фильтр+хендлер+коулдаун, 87 юнитов)
- [x] T-228 (@Builder, P0) — work-функция (R30-2, D86/D87/D92) — **Done** (фильтр+хендлер+коулдаун, 183 юнита)
- [x] T-229 (@Builder, P0) — goodmorning-рассылка (R30-3, D88/D89) — **Done** (captions+relay+scheduler+bot.py, 39 юнитов)
- [x] T-230 (@Builder, P1) — фикс нумерации промпта (R30-4, D90) — **Done** (1–6, байт-в-байт ✅)
- [x] T-231 (@Builder + @Reviewer, P0) — тесты 1327 passed + ревью — **Done (APPROVED)**
- [x] T-232 (@Builder, P1) — README v2.28.0 + .env.example — **Done**
- [x] T-233 (@DevOps, P0) — коммит `714a4f6` + пуш (30 файлов, медиа в коммите) — **Done**
- [x] T-234 (@DevOps, P0) — деплой v2.28.0 (PID 939545, goodmorning ON, 0 traceback) — **Done (Шаг 8: `4b50272`)**

### Epic 29: T-221…T-226 — UX-полировка (код + тесты + доки + коммит + деплой) — ✅ DONE & DEPLOYED (v2.27.0, коммит `7160a33`, 1002 passed, прод PID 937634)

> Перенесено из Backlog при архивации (PM, 2026-08-17). Полный трек — `plans/backlog.md` (Epic 29).
> **Итог:** T-221 (@Architect) — Section 38 (38.1–38.7), DESIGN ✅; T-222 — пул 20 ack-фраз (`_UX_ACK_VARIANTS`, канон первым) + `random.choice`, delete ДО ack; T-223 — промпт v4 (пункт 3 удалён, пункт 6 — канон пользователя дословно), эталон backlog 1518–1539 (22 строки), слайс `lines[1517:1539]`; T-224 — доки (ARCHITECTURE/MEMORY/README/board); T-225 — тесты + полный прогон 1002 passed (995 baseline + 7 новых), 0 failed, 0 skipped; T-226 — коммит `7160a33` «feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)» + пуш + деплой (git pull ff `ac80ce8..7160a33`, .env НЕ тронут, restart → active (running) PID 937634, 0 traceback, dim=3072). **ЭПИК 29 ЗАКРЫТ (Шаг 8).**

- [x] T-221 (@Architect, P0) — Section 38 (38.1–38.7), порядок delete→ack — **Done (DESIGN ✅)**
- [x] T-222 (@Builder, P1) — пул ack-фраз + `random.choice` + 4 ассерта → принадлежность пулу — **Done**
- [x] T-223 (@Builder, P0) — промпт v4 + эталон backlog + слайс `lines[1517:1539]` — **Done (байт-в-байт ✅)**
- [x] T-224 (@Builder, P1) — доки (ARCHITECTURE/MEMORY/README/board) — **Done**
- [x] T-225 (@Builder + @Reviewer, P0) — тесты + полный прогон 1002 passed — **Done (ревью @Reviewer — T-225-C)**
- [x] T-226 (@Builder + @DevOps, P0) — коммит `7160a33` + пуш + деплой v2.27.0 (PID 937634, 0 traceback) — **Done (2026-08-17, Шаг 8)**

### Epic 28: T-211…T-220 — качество памяти: векторы, репосты, алиасы, очистка — ✅ DEPLOYED (v2.26.0, коммит `ac80ce8` + `ccfad99`, 995 тестов)

> Перенесено из колонки Backlog при архивации (PM, 2026-08-16). Полный трек — `plans/backlog.md` (Epic 28).
> **Итог:** T-211…T-219 реализованы (@Builder), ревью @Reviewer PASS (995 passed). T-220 DONE: коммит `ac80ce8` «feat(summary): Epic 28 — качество памяти: репосты, алиасы, векторное автолечение и cleanup (v2.26.0)» + пуш в origin/master; деплой выполнен (git pull, restart, логи проверены: нет Dimension mismatch, алиасы работают). Шаг 8 (@Memory): `ccfad99` — финальная синхронизация. ЭПИК 28 ЗАКРЫТ.

- [x] T-211…T-219 (@Builder, @Reviewer) — реализация + ревью PASS (995 passed) — **Done**
- [x] T-220 (@Builder + @DevOps + @PM) — коммит `ac80ce8` + пуш + деплой v2.26.0 + Шаг 8 `ccfad99` — **Done**

### Epic 27: T-207…T-210 — новый системный промпт + SUMMARY_ALIASES на прод — ✅ DEPLOYED (v2.25.0, коммиты `1d7bed4` + `17fcd18`, 939 тестов, PID 934174)

> Перенесено из колонки Backlog при архивации (PM, 2026-08-16). Полный трек — `plans/backlog.md` (Epic 27).
> **Итог:** T-207 — SYSTEM_PROMPT заменён на «бот-абьюзер v2» дословно (эталон backlog R11 v2, строки 1518–1538, байт-в-байт ✅; тесты D72; полный pytest 939 passed / 0 регрессий) и T-208 — доки (MEMORY.md «заморожено» → R11 v2, README промпт v2, ARCHITECTURE верифицирован) DONE. T-209 — прод: .env +SUMMARY_ALIASES (36 пар, бэкап `.env.bak.epic27`, python3: JSON OK, sha1 совпал с репо), git pull fast-forward `7c7c241..1d7bed4`, systemctl restart → active (running), **PID 934174**, 0 traceback. T-210 — коммит `1d7bed4` «feat(summary): Epic 27 — новый системный промпт бота-абьюзера v2 и SUMMARY_ALIASES (v2.25.0)» (8 файлов, .env НЕ коммичен, .env.example коммичен) + пуш в origin/master. Шаг 8 (@Memory): финальная синхронизация `17fcd18`. ЭПИК 27 ЗАКРЫТ. ⚠️ Pre-existing не-блокер → Epic 28: L3 dimension mismatch (768 vs 3072) → FTS5-фоллбек.

- [x] T-207 (@Builder, **P0**): Замена SYSTEM_PROMPT на новый дословный текст (эталон backlog R11 v2, строки 1518–1538) + тесты (хелпер-диапазон 1517:1538, набор плейсхолдеров D72) + полный pytest 939 — **Done (байт-в-байт ✅)**
- [x] T-208 (@Builder, **P1**, ←T-207): Доки — ARCHITECTURE.md, MEMORY.md («заморожено» → R11 v2), README (промпт v2) — **Done**
- [x] T-209 (@DevOps, **P0**, ←T-207): SUMMARY_ALIASES (36 пар) в продовый .env (бэкап `.env.bak.epic27`, JSON OK, sha1 совпал) + git pull + restart admin_bot + верификация — **Done (PID 934174, 0 traceback)**
- [x] T-210 (@DevOps + @PM, **P1**, ←T-207/T-208): Коммит `1d7bed4` (conventional, 8 файлов) + пуш; .env не коммичен — **Done (Шаг 8: `17fcd18`)**

### Epic 26: T-199…T-206 — дизайн, реализация и деплой GraphRAG — ✅ DEPLOYED (v2.24.0, коммит `7c7c241`, 939 тестов, PID 926618)

> **Итог:** T-199 (T26.0) — дизайн `plans/ARCHITECTURE.md` Section 35 (35.1–35.11) **APPROVED PM 2026-08-16 (T26.0-D)**.
> T-200…T-204 (T26.1…T26.5) — **реализовано @Builder и прошло ревью @Reviewer (T26.5-G APPROVED)**:
> DDL nodes/edges (chat_id + UNIQUE), extraction в compress_and_purge (D68 per-batch isolation),
> traversal get_graph_facts (тег `<historical_graph_facts>` первым, escape), настройки GRAPH_* (D69),
> тесты test_graphrag_database/test_graphrag_memory + полный pytest.
> ⚠️ @Reviewer подтвердил **P1 pre-existing баг** (Epic 24, `a68732c`) → выделен **T-206 (T26.7)**: FTS-DELETE зеркалит условие вставки (`text IS NOT NULL AND text != ''`) в `delete_smart_messages_by_ids`/`delete_smart_messages_older_than` + chat_id-фильтр + 6 регрессионных тестов — **FIXED в релизе v2.24.0**.
> **T-205 (T26.6) DONE:** коммит `7c7c241` «feat(graphrag): Epic 26 — граф знаний nodes/edges, entity extraction и гибридный поиск /summary (v2.24.0)» + пуш + деплой: git pull fast-forward `c364f18..7c7c241`, .env +GRAPH_* (бэкап .env.bak.epic26), systemctl restart → active (running), Main PID 926618, nodes/edges созданы, 0 traceback. Тесты: 939 passed (860+73+6). ЭПИК 26 ЗАКРЫТ (Шаг 8, @Memory). Известный не-блокер: SIGTERM ~95с рестарт (pre-existing).

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
- [x] T-206 (T26.7) (@Builder + @Reviewer, P1) — P1-фикс FTS-удаления медиа без подписи + 6 регрессионных тестов — **FIXED (релиз v2.24.0)**
- [x] T-205 (T26.6) (@Builder + @DevOps, P0) — README + коммит `7c7c241` + пуш + деплой — **DEPLOYED (v2.24.0, PID 926618, 939 тестов)**

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

**Updated:** 2026-08-17 — **Epic 32 (v2.30.0) АРХИВИРОВАН: T-242…T-248 ALL DONE & DEPLOYED (коммит `2bad5ff`, 1392 теста, PID 942078).** Открыт **Epic 33 «SmartModule Extension: FactCheck + SmartSearch + SearchAggregator» (v2.31.0, IN PROGRESS)**: Шаг 1 (PM) ✅ — требования R33-1…R33-8, решения D104–D111 в `plans/backlog.md`; T-249 (@Architect, дизайн) → T-250…T-258 (@Builder) → T-259/T-260 (@DevOps). ⚠️ Блокер D109: дословные тексты промптов — у пользователя. Без @Orchestrator. **→ 2026-08-17, Шаг 4b (@Builder): Epic 33 IMPLEMENTED (T-249 ✅, T-250…T-256 ✅, T-257-A…E ✅ — 10 новых тест-файлов, 150 тестов, полный прогон 1542 passed / 0 failed, `git diff --check` чист); блокер D109 СНЯТ (промпты 42.5.1/42.5.2 байт-в-байт); T-257-F — @Reviewer (ожидается); T-258 README (@Builder) → T-259/T-260 (@DevOps).** **→ 2026-08-17, Шаг 5 (@Builder, фиксы ревью): @Reviewer NEEDS FIXES закрыты — BLOCKER-1 (реальные ключи в backlog.md R33-1 → плейсхолдеры; grep: ключи только в .env), MAJOR-1 (новая интеграция `test_epic33_router_isolation.py`: Dispatcher 0a/0c/0d/4c через feed_update — «найди ракету» → 1 ответ от search, factcheck → reply на target, observer 0a пишет память, danger/common живы), MINOR 1–4 (.env +4 явных ключа и чистый UTF-8-комментарий; убран `.lower()` в factcheck.py:72; `test_settings_helpers.py` 9 тестов вскрыл и закрыл `NameError: logging` в settings.py); прогон **1555 passed / 0 failed**. Повторное ревью @Reviewer ожидается.** **→ 2026-08-17, Шаг 5 (повторное ревью, @Reviewer): ✅ APPROVED — все замечания закрыты и подтверждены лично (BLOCKER-1: grep по фрагментам ключей — только .env; MAJOR-1: 4 теста через `Dispatcher.feed_update` содержательны; MINOR 1–4 ✅; промпты/пулы байт-в-байт повторно; роутеры 0c/0d не сдвинуты; `git diff --check` чист; полный прогон 1555 passed / 0 failed подтверждён лично). T-257 ЗАКРЫТ. Впереди: T-258 README (@Builder) → T-259/T-260 (@DevOps).** **→ 2026-08-17, Шаг 8 (@Memory, ФИНАЛЬНАЯ синхронизация): Epic 33 ✅ DEPLOYED & ARCHIVED — T-249…T-260 ALL DONE. Коммит `1172fb5` «feat(smartmodule): Epic 33 — FactCheck и SmartSearch с SearchAggregator (v2.31.0)» (32 файла, +3610/−43) + пуш в origin/master. Деплой на прод nik@198.46.175.136:/var/www/admin_bot: git pull ff `2bad5ff..1172fb5`, pip install duckduckgo-search 8.1.1, .env +6 ключей (бэкап `.env.bak.epic33`), systemctl restart → active (running) MainPID 948950, 0 traceback, «SmartModule FactCheck + SmartSearch (Epic 33) initialized». Тесты 1555 passed / 0 failed. Прод v2.31.0. Epics 1–33 ALL DEPLOYED. Цикл воркфлоу (Шаги 0–8) завершён.**
**Updated:** 2026-08-18 — **Epic 36 (v2.31.3) АРХИВИРОВАН: T-274…T-280 ALL DONE & DEPLOYED (коммит `2e26690`, 1593 теста, PID 951645).** Открыт **Epic 37 «SmartModule: YouTubeSummarizer + WebSummarizer» (v2.32.0, IN PROGRESS)**: Шаг 1 (PM) ✅ — требования R37-1…R37-9, решения D124–D133 в `plans/backlog.md`; T-281 (@Architect, Section 46) → T-282…T-291 (@Builder) → T-292/T-293 (@DevOps). Без @Orchestrator.
**Updated:** 2026-08-20 — **Epic 42 «Checkup» + Epic 43 «/info + live-редактор» открыты (Шаг 1 @PM ✅, target v2.34.0)**: требования R42-1…R42-6 / R43-1…R43-5, решения D158–D165, задачи T-323…T-342 в `plans/backlog.md`; T-323/T-332 (@Architect, Sections 51/52) → @Builder → @Reviewer → @DevOps (деплой v2.34.0 общий). Epic 41 (v2.33.1) — ждёт архивации (Шаг 8 @Memory). Без @Orchestrator.


---

### Epic 48–51 (v2.36.0): АРХИВИРОВАНО ✅ (2026-08-23, по MEMORY.md — DEPLOYED & CLOSED, коммит `b394e1e`, 2205 тестов, PID 1018603, user_version=2)

- [x] Epic 48: откат degraded-саммари (LLM или ничего) — T-381…T-386
- [x] Epic 49: чекап 400 (scrub C0, CHECKUP_MAX_INPUT_SYMBOLS, UX-сплит) — T-387…T-392
- [x] Epic 50: DirectChat (роутер 0h, каноны R50-4/R50-7/R50-8, миграция 1→2) — T-393…T-400
- [x] Epic 51: Intelligent Caching (SmartCache + Prompt Caching, Sections 59) — T-401…T-405
- [x] Релиз v2.36.0 (миграция на остановленном боте + деплой) — T-406/T-407

### Epic 52: Запрос пользователя 2026-08-23 (ALAN_REPLIES/common/slavik/direct_chat + ресёрч) — ✅ DEPLOYED & ARCHIVED (v2.37.0, коммит `56cccd6`, прод PID 1051710, 2302 теста)

> Перенесено из In Progress при архивации (PM, 2026-08-23, Шаг 1 Epic 53). Полный трек — `plans/backlog.md` (Epic 52).
> **Итог (по MEMORY.md, Шаг 8):** T-408…T-414 + T-417 ALL DONE; Section 61 (D213/D214);
> @Researcher T-412 (RESEARCH.md §6); @QA 2302 passed / 0 failed (+97); @Reviewer APPROVED;
> @DevOps коммит `56cccd6` + пуш origin/master + деплой (b394e1e..56cccd6, .env.bak.epic52:
> ALAN_REPLIES_ENABLED=false + COMMON_WORK_MEDIA_ENABLED=false, PID 1051710, 0 traceback).
> **ЭПИК 52 ЗАКРЫТ. Прод v2.37.0.**

- [x] T-408 (@Builder, P1) — ALAN_REPLIES: трейдинг выпилен, ироничные темы (NixOS/нейрокластер/планшет/SSD/витамины 100500%/5-сек прогулка/тренажёр+колени) + ALAN_REPLIES_ENABLED (гейт ТОЛЬКО на реплики, F7v2 жив) — **Done (Шаг 4, прод false)**
- [x] T-409 (@Builder, P1) — common/work: COMMON_WORK_MEDIA_ENABLED=false + COMMON_MEDIA_ENABLED (D213) — **Done**
- [x] T-410 (@Builder, P1) — Славик: одно действие (dead page > GIF > рандом-медиа > mimic > «пошёл нахуй»); join → только «ДОЛБОЕБ ВЕРНУЛСЯ» — **Done**
- [x] T-411 (@Builder, P1) — direct_chat: «бот»/«ботохуета»+синонимы (word-boundary, reply to) + DIRECT_CHAT_BOTWORD_ENABLED — **Done**
- [x] T-412 (@Researcher, P2) — ресёрч direct_chat → RESEARCH.md §6 (6.1–6.11, D214 подтверждён) — **Done**
- [x] T-413 (@QA, P1) — макс покрытие + прогон 2302 passed / 0 failed + конфликты 0a–0g > 0h — **Done (Шаг 5)**
- [x] T-414 (@Docs, P2) — README v2.37.0 (иронично) + MEMORY — **Done**
- [x] T-415 (@DevOps, P1) — коммит `56cccd6` + пуш origin/master — **Done (Шаг 7)**
- [x] T-416 (@DevOps, P1) — деплой v2.37.0 (PID 1051710, 0 traceback, smoke) — **Done (Шаг 7)**
- [x] T-417 (@Builder, P1) — Dead page delete (R52-8, D214): InaccessibleMessage-детект + маппинг БД + пул фраз — **Done (Шаг 4)**

**Updated:** 2026-08-23 — **Epic 52 ✅ DEPLOYED & ARCHIVED (v2.37.0, коммит `56cccd6`, прод PID 1051710, 2302 теста)**: перенесено из In Progress при архивации (PM, Шаг 1 Epic 53). Все T-408…T-417 DONE; итог по MEMORY.md Шаг 8 (коммит запушен в origin/master, деплой b394e1e..56cccd6, прод .env: ALAN_REPLIES_ENABLED=false + COMMON_WORK_MEDIA_ENABLED=false, 0 ошибок).
