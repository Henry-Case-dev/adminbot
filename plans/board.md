# AdminBot — Kanban Board

## 📋 Backlog

*(пусто)*

## 🔧 In Progress

### Epic 39: YouTube engine fix — yt-dlp → youtube-transcript-api фолбек — 🚧 IN PROGRESS (одобрено пользователем, target v2.33.0, Шаг 1 @PM ✅, 2026-08-19)

> Полный трек — `plans/backlog.md` (Epic 39). Требования R39-1…R39-6, решения D139–D144.
> yt-dlp (Python-API, lazy, to_thread) — основной движок → фолбек youtube-transcript-api 0.6.3 с proxies/cookies; контракт движка/сервис/хендлер/пулы/промпты/троттлинг БЕЗ изменений.
> Новые ключи (опциональные): YOUTUBE_TRANSCRIPT_PROXY_URL / YOUTUBE_COOKIES_FILE. Передача @Architect (T-302, Section 48). Без @Orchestrator.

- [ ] T-302 (@Architect, P0) — дизайн Section 48: каскад yt-dlp → transcript-api, приоритет треков (зеркало `_pick_transcript`), нормализация, тест-план, риски; закрыть открытые вопросы PM 1–6 (R39-1…R39-6)
- [ ] T-303 (@Builder, P0) — settings +2 ключа (R17: не логировать значения) + requirements yt-dlp floor-пин + .env.example (R39-3)
- [ ] T-304 (@Builder, P0) — движок: yt-dlp primary + фолбек transcript-api 0.6.3 (proxies/cookies); контракт `fetch_transcript` не менять (R39-1/R39-2/R39-4, D139–D141)
- [ ] T-305 (@Builder + @Reviewer, P0) — тесты: мок yt-dlp, каскад, kwargs, сохранение классов; полный прогон 0 регрессий (baseline 1763); ревью APPROVED (R39-5)
- [ ] T-306 (@Builder, P1) — README v2.33.0 + MEMORY
- [ ] T-307 (@DevOps, P0) — коммит на русском + пуш master (R39-6)
- [ ] T-308 (@DevOps, P0) — деплой: pip install yt-dlp (floor-пин), .env (бэкап `.env.bak.epic39`), restart, ОБЯЗАТЕЛЬНАЯ верификация реальных ссылок с серверного IP (dQw4w9WgXcQ, cUbIkNUFs-4, aPYGbtkSE7A + ru-manual видео) (R39-6)

## 🔍 In Review

*(пусто — Epic 31 перенесён в Done при архивации)*

## ✅ Done

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
