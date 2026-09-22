# AdminBot — backlog.md (глобальные неначатые эпики)

Только эпики, которые можно начать планировать. Канон-блоки промптов — в `docs/canon/`; закрытые эпики 1–85 — история в git-истории (прежние файлы plans/, удалены 03.09.2026).

## Раунд 10.25 (Эпик 1) + Раунд 10.26 (Эпик 2) + Раунд 10.26+ (Эпик 3): «Liquid Glass Control Center + Summary Hybrid Pipeline + Agentic Intelligence» — MASTER SPECIFICATION v6.0 (`plans/current_task.md`) — 🟦 PLANNING (Step 1 @PM: декомпозиция; **UPD применён** — F0 Wave 0 + Human Gate GO по F1 + Эпик 3; `spec.md`/ADR — Step 2 @Architect) · **F0 ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаги 8–9, 20.09.2026); live-приёмка: T-2454 ✅ подтверждён, T-2419/T-2433 — ручные (владелец)**; **Волна 1 (F2 \`design-tokens-liquidglass-v2-round1025\` + hotfix5 \`summary-cover-window-round1025\` + F3 \`global-scope-selector-round1025\`) ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026), Merge \`plans/ARCHITECTURE.md\` §57; \`APP_VERSION\` 2.58.6; пакет задеплоен (Шаг 9 @DevOps, коммит `4cde1bc`, `APP_VERSION` 2.58.6, health 200, `database is locked`=0); live-гейты владельца открыты**; **hotfix6 `hotfix6-webview-shell-heartbeat-round1025` (Волна 1.5, по итогам живой приёмки; блоки A–D: glass/панель mobile/сердцебиение §15/шапка) — ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026; Merge §58); deploy ✅ VERIFIED (Шаг 9 @DevOps, `055525c`+`ba75751`, `APP_VERSION` 2.58.7, health 200); live T-2617 ⏳; см. отдельный раздел ниже**; **✅ HOTFIX7 `hotfix7-shell-glass-heartbeat-round1025` (Волна 1.6, ВНЕПЛАНОВЫЙ ПРИОРИТЕТНЫЙ по UPD «Срочный фикс текущего фронта») — ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026; Merge `plans/ARCHITECTURE.md` §59; T-2658…T-2694, 37); deploy ✅ VERIFIED (Шаг 9 @DevOps, `7073e34`/`a9cec67`/`2a67829`, `APP_VERSION` 2.58.8); live-гейт владельца T-2682 ⏳; F4 — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM, 22.09.2026; Merge §60; deploy ✅ `7f9fed1`/`28eb02d`/`f0db773`, `APP_VERSION` 2.58.9, live T-2656 ⏳) — см. строку F4 ниже**

**Триггер:** новое единое ТЗ `plans/current_task.md` («MASTER SPECIFICATION v6.0»), прямо **заменяющее все предыдущие версии ТЗ** (§0). Два строго последовательных эпика: **Эпик 1** — полный рефакторинг Mini App (IA/shell, Liquid Glass, глобальный селектор области, каталог+store модулей, workspace, Память/Аналитика, PERMsoc, реестр параметров, секреты, приёмка); **Эпик 2** — новый гибридный пайплайн Саммари и расширение Adaptive System 2, **начинается только после завершения и проверки Эпика 1** (§0/§79). Анализ Шага 0 — @Memory (используется как данность, не переделывается).

**🆕 UPD (Step 1 @PM, применено 20.09.2026; источник — `plans/current_task.md`, блок UPD строки 3718–5918 «Human Gate + F0 Bugfix + Epic 3: Agentic Intelligence»):**
- **F0 — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаги 8–9 @PM/@DevOps, 20.09.2026); live-приёмка: T-2454 ✅ подтверждён, T-2419 (TMA, владелец) / T-2433 (ждёт владельца) — ручные; деплой в прод подтверждён (commit `3a91c84`, health 200).** Обязательные багфиксы конфигурации (P0, Wave 0, выполнялся ДО F1 «не переносить неисправный механизм сохранения в новые компоненты»): **F0.1** конфликт версий 409 (три противоречивых результата одной операции); **F0.2** аудит **всех** механизмов сохранения (цикл load→edit→save→re-read→compare; HTTP 200 ≠ подтверждение); **F0.3** анти-клише (лимит 200, фактически 20; «Ошибка модели»; семантика «вместимость базы» vs «паттернов за обновление»; события `ANTI_CLICHE_*`); **F0.4** тосты/SaveBar (одно итоговое уведомление на операцию, safe area, без stack trace поверх страницы); **🆕 F0.5 — устойчивость к `database is locked`** (прод-логи 20.09.2026: 6 стеков `sqlite3.OperationalError: database is locked`, chat_id=-1002661910336; тихая потеря записи памяти/ответов/throttling). **Архив:** `plans/archive/f0-config-bugfixes-round1025/` (spec.md + 4 ADR + tasks.md), задачи **T-2410…T-2455 (46)**: F0.1–F0.4 = T-2410…T-2441 (32), **F0.5 = T-2442…T-2455 (14)**; критерии приёмки — §6 (10 пунктов).
- **F0.5 — преемственность:** это **расширение ADR-1024-18** (`plans/archive/sqlite-lock-resilience-round1024`, T-2322…T-2327), который закрыл тот же класс дефекта **только** для `services/smart_cache.py`. F0.5 переносит контракт (PRAGMA-паритет WAL/`busy_timeout=5000`/`synchronous=NORMAL`; bounded retry `_LOCK_RETRIES=3`/backoff 0.1с **только на `locked`**; явный `event=*_lock_exhausted` + счётчик; fail-open последним рубежом; kill-switch) на `services/database.py` + `summary_memory.py` + `persistent_throttling.py` + `direct_chat_service.py`; `smart_cache` **не дублируется/не трогается**. **F0.5 — реализовано и заархивировано вместе с F0.**
- **✅ ИТОГ F0 (Архив, Шаг 8 @PM + Деплой, Шаг 9 @DevOps, 20.09.2026): COMPLETED + MERGED + ARCHIVED + DEPLOYED.** Реализованы F0.1–F0.4 (T-2410…T-2441) и F0.5 (T-2442…T-2455). @Reviewer = **Approved**; @Scanner (повторный аудит) = **Critical 0 / High 0**; @Architect Merge (`plans/ARCHITECTURE.md` §52 + AMEND-карта). Показатели: pytest **7946/0**, JS **19/19**, **Δ DDL=0**, **Δ каталога=0**, `smart_cache` не тронут. Папка — `plans/archive/f0-config-bugfixes-round1025/` (spec.md + 4 ADR + tasks.md; содержимое и чекбоксы сохранены, UTF-8). **✅ Live-приёмка (post-deploy gate):** **T-2454** ✅ **подтверждён** — до деплоя за 24ч **633** записи `database is locked` от `summary_memory`, после рестарта **0**, `*_lock_exhausted` не срабатывал; **T-2433** — воркер `AntiClicheWorker` зарегистрирован, кэш fresh (`count=20/200`), форс-пополнение до 200 **не запускалось** (ждёт владельца); **T-2419** — ⏸ ручная проверка владельцем в TMA (Fallback/409). **Деплой подтверждён:** commit **`3a91c84`** (push origin/master), прод `/var/www/admin_bot` fast-forward `da561bc..3a91c84`, `systemctl restart admin_bot` → active, `/api/health` **200**. Приёмка — `plans/reports/f0-round1025-report.md`, `plans/reports/f0-5-db-lock-round1025.md`, `plans/reports/round1025_f0_scanner_audit.md`. **Бэкап `var/backups/web-round1025-f0-<ts>/` и теги `pre-round1025*` НЕ удалять** до утверждения владельцем (R18).
- **Связь F0 ↔ F9:** persistence / 409 / единая state-machine сохранения вынесены **в ранний F0 (Wave 0)** — ✅ **реализовано и заархивировано** (`plans/archive/f0-config-bugfixes-round1025/`); в **F9** остаются только **UI-слой секретов §50** и **визуальная часть SaveBar** (без дублирования серверной логики; F9 читает результат F0, блоки F0 не переписывает).
- **Human Gate по F1 — GO с уточнениями (§7–§10):** Аналитика — технический маршрут `#/oversight`, label «Аналитика», переход из Статуса, **без дублирующей страницы**; **профиль** — использовать существующий блок Telegram-пользователя (не создавать новый экран); **планшет 768–1199** — без постоянного sidebar (компактная навигация / drawer), полноценный sidebar с 1200 px, селектор области легкодоступен; **нижнее меню — 4 пункта** (Статус/Модули/ИИ/Ещё), «Память» — в «Ещё», на вложенных страницах — текущий раздел + понятный путь назад; **заморозка меню 10.20–10.21 снята**, аккордеоны 10.24 — **не основной способ навигации** (только второстепенные настройки); новая палитра `#090D17`/`#151B2A` + акценты (бирюзовый/фиолетовый/приглушённый синий), анимированный градиент **сохранить и замедлить**; в F1 сохранить быстрые генеральные тумблеры модулей (глобально/чат), **доступ к старому каталогу**, существующие виджеты (мониторинг интеллекта, убеждения, парадигмы, эволюция, сон, лента досье, дерево LLM-вызовов, граф, логи) — **без заглушек**; `IA_V2_ENABLED` — **только временный механизм отката**, не вторая архитектура.
- **Эпик 3 «Agentic Intelligence» (после Эпиков 1 и 2; исследование допустимо заранее, но не блокирует):** единый координатор инструментов, последовательные tool calls, единый Image Request (direct|tool), генерация из досье/RAG, дневной лимит изображений (atomic reserve + idempotency, scope global/chat), structured memory lookup `get_user_context(purpose)`, новый Decision Making (`action` {reply/react/silent/tool} отдельно от `style`), реакции Telegram (`setMessageReaction`), события `DECISION_*`/`TOOL_*`/`REACTION_SENT`/`MESSAGE_IGNORED`/`IMAGE_*`, интеграция в существующий ExecutionGraph и Mini App; 22 сценария §52 и приёмка §53.
- **⚠️ Термины ТЗ ≠ имена в коде (зафиксировано @Memory, перепроверять не нужно):** `revision` ≠ `updated_at` (фактический optimistic-лок — по `updated_at`, прецеденты 10.20/10.21/BYOK); «Fallback» (резервный режим Вербализатора, §UPD3 №2) ≠ LLM fallback / резервная модель; «ExecutionGraph» — **фактически существует** (`web/api/analytics.py` + `llm_usage_events` + `web/app.js::tokenFlowTree/tokenFlowNodes` 10.23/10.24), вторую визуализацию не создавать (только adapter + новые kind-узлы); `get_user_context(...)` — **предлагаемый контракт**, в коде такого API нет (есть досье + RAG + `dig_into_lore`).
- **⚠️ SUPERSEDE / AMEND (к объявлению на Step 2 @Architect):** `tma-menu-freeze` 10.20/10.21 (уже SUPERSEDE в F1); палитра OD4 `#161616`/`#14CBB6` + градиент `#FF8A3D` (10.20-UPD3, ADR-1020-9/D4 — SUPERSEDE в F2); **`physical-two-call-pipeline`** — новое `action`-решение **не должно добавлять третий LLM-вызов** (решение о действии — внутри существующих Стейдж-1/Синтезатора, не отдельным вызовом; §13 «не создавать дополнительный LLM-вызов там, где достаточно программной логики»); аккордеоны 10.24 F6 — **REVISE** (F5); ExecutionGraph — **REUSE** (F6/S8, §51).

**Baseline (Step 0 @Memory):** HEAD **`da561bc`** (= `origin/master`, дерево чистое); раунд 10.24 — COMPLETED+DEPLOYED+ARCHIVED; pytest **7911 passed / 0 failed**; SQLite `user_version=12`; APP_VERSION **2.58.0**; каталог REGISTRY **459** / Settings **418** / GROUPS **98** / `_TAB_BY_GROUP` **96** / `TAB_RULES`=`TAB_NAV`=`CONFIG_TAB_TITLES` **21**; прод — `da561bc` active. Фронтенд: **Vue 3 global zero-build + self-host** (CSP `script-src 'self'`, ADR-1016-2 / ADR-1024-13), **без CDN и без новых state-библиотек** (§39).

**⚠️ SUPERSEDE / REVISE (объявлено новым ТЗ — прежние инварианты сняты):**
- **«Заморозка меню/навигации» (инварианты 10.20/10.21) — SUPERSEDE.** Маркеры `test_frontend_tab_mapping`, `test_webapp_nav_disclosure_ui`, `test_round106_ia_smoke`, `_TAB_BY_GROUP`/`TAB_NAV`/`NAV_ORDER` **снимаются** новой IA §4 (Публичные: Статус/Справка; Административные: Модули/ИИ/**Память**/Доступы; Локальное: PERMsoc). `services/param_catalog.py` и маркер-тесты обновляются **атомарно** (код + эталон + тест одним коммитом).
- **Палитры — SUPERSEDE.** Палитра OD4 (10.20: `#161616`/`#14CBB6`) и градиент `#FF8A3D` (10.20-UPD3) заменяются палитрой **§8**; **AMEND ADR-1020-9**.
- **10.24 F6 `prompts-refactor-accordion-modes` — REVISE.** Аккордеоны как основная навигация запрещены (§48/§69); допускаются только для редких технических параметров; «один промпт — один источник данных».
- **ExecutionGraph — REUSE, не дублировать.** Де-факто существует (`web/api/analytics.py` + `llm_usage_events` + `web/app.js::tokenFlowTree/tokenFlowNodes`, 10.23/10.24). Вторая визуализация запрещена — только **adapter** нормализованной модели §23 + новые kind-узлы §111.
- **L1/L2 разведены (§81):** прямой чат — L1 Синтезатор / L2 Вербализатор; Саммари — L1 Кластеризатор / L2 Писатель; §82 — до 4 независимых слотов моделей (провайдер+модель+промпт+параметры+fallback).

### ⚡ ASAP-хотфикс round1025 — `hotfix-media-tma-round1025` (внеплановый, между F0 и F1) — ✅ COMPLETED + MERGED + DEPLOYED (20.09.2026)

**Триггер:** подтверждённые боевые дефекты после деплоя F0 (`3a91c84`): (1) видео/транскрибация падает (облачный лимит Bot API 20 МБ); (2) LLM `ReadTimeout` (провайдер); (3) «разделы миниаппа не открываются» (cache-bust); (4) диагностируемость логов.

**Статус:** ✅ **COMPLETED + MERGED + DEPLOYED.** Коммиты `8b16c4a` (ядро) + `ee23e47` (ревью-итерация) + docs `65e39fb`; origin/master. @Reviewer **Approved**; @Scanner **Critical 0 / High 0** (2 Medium → техдолг, 4 Low, 4 Info). pytest **7976/0** (7946 + 30 новых), JS **19/19**. **Прод:** `TELEGRAM_LOCAL=1` (контейнер `--local`, общий `.env`), `APP_VERSION` **2.58.1**, `/api/health`=200, `database is locked`=**0**, WAL **159 МБ → 0**. Интеграция — `plans/ARCHITECTURE.md` **§53**; аудит — `plans/reports/round1025_hotfix_scanner_audit.md`. **Архив:** `plans/archive/hotfix-media-tma-round1025/` (spec.md + adr-1025-6-bot-api-local-mode.md + tasks.md; T-2456…T-2481).

**⚠️ Открыто — live-гейт владельца (post-deploy, НЕ выполнено):**
- **T-2463** — тест видео **> 20 МБ** (скачивание + файл на диске + транскрибация).
- **T-2472** — консоль TMA: нет `ReferenceError` в config-разделах, грузится новая версия ассетов.
- **T-2479** — пост-деплойная верификация медиа / cache-bust / логов.

**Остаточный техдолг (§53, не блокеры):** **M-1** (R17 в логе медиа), **M-2** (двойной рубильник `TELEGRAM_LOCAL`↔`DOWNLOAD_ENABLED`), LLM-таймауты/провайдер, RAM/swap/graceful-stop, `?v=` для 3 vendor-скриптов, точечный `.gitignore` для zip-архивов.

**Следующая задача — возврат к F1 (T-2481):** `git stash pop` (`stash@{0}`, 25 файлов) + вернуть untracked F1 из `var/backups/f1-wip-20260921-015653/` поверх `65e39fb`; ожидаемые конфликты — `?v=`/`APP_VERSION` и `IA_V2_ENABLED`; **F1-WIP НЕ трогать до явной задачи**; бэкапы/теги не удалять (R18).

### 🩹 P0-фикс после F1 — `p0-fix-render-media-paths-round1025` (hotfix2, внеплановый, между F1 и F2) — ✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED (21.09.2026)

**Триггер:** прод-инцидент сразу после деплоя F1 (`fe0f7bb`): пустые config-разделы ИИ (render-регрессия F0 `d5750fc`, проявившаяся в F1) + видео/ГС/аватары (контейнерный абсолютный путь локального Bot API).

**Статус:** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED.** Коммит **`fea2daa`** (hotfix2); интеграция — `plans/ARCHITECTURE.md` **§54.1**. @Reviewer Approved; @Scanner **Critical 0 / High 0** (2 Medium → техдолг, 3 Low) — `plans/reports/round1025_hotfix2_scanner_audit.md`; pytest **8003/0**, JS **21/21**. **Архив:** `plans/archive/p0-fix-render-media-paths-round1025/tasks.md` (**FIX 1–4**). **FIX:** 1) render `stickyFieldFailed` computed→methods; 2) media/avatars `normalize_api_file_path`/`read_host_file_bytes` (traversal-guard fail-closed); 3) `APP_VERSION` **2.58.2**; 4) матрица `tools/ui_round1025_matrix.py` (непустой config + AI-маршруты + FAIL на console/pageerror).

**⚠️ Открыто — live-гейт владельца (post-deploy, НЕ выполнено):** реальные **видео/ГС/аватары** (загрузка/транскрибация, аватар из локального Bot API) + **разделы TMA** (`#/ai/llm`, `#/ai/names`, `#/smart-cache`, `#/memory/rag` не пустые, нет `ReferenceError`).

**Техдолг (§53/§54.1, не блокеры):** **M-1** — `services/media_download.py:153-155` логирует сырой `file_path` (содержит `<bot_id>:<token>`) → логировать `PurePosixPath(file_path).name`/`sanitize`; **M-2 (avatars)** — `web/api/avatars.py:199-201` `exc_info=True`: `SecretMaskFilter` мутирует только `record.msg`, **трейсбек не маскируется**; **TOCTOU-guard** (гонка check-then-use `exists()` перед копированием); **vendor-скрипты без `?v=`** (`telegram-web-app.js`/`vue`/`chart`, §53 L-2); **matrix** — `_config_stub()` при сбое импорта `param_catalog` молча даёт пустой stub; Low: тавтологичный ассерт (`round1025_save_state_test.js`), нет регресс-тестов на symlink/двойной префикс.

### 🔥 Хотфикс-3 после hotfix2 — `hotfix3-summary-stt-anticliche-round1025` (внеплановый, между F1/hotfix2 и F2) — ✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED (21.09.2026)

**Статус:** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED.** Коммиты `090d2e7` (ядро) + `fb65965` (ревью R-1…R-8) + `cfe7342` (bump); docs `5f624cd`. `APP_VERSION` **2.58.3**, `/api/health`=200, `database is locked`=0. @Reviewer Approved; @Scanner **Critical 0 / High 0**. pytest **8041/0**, JS **22/22**. **Δ DDL=0, Δ каталога=0**. Интеграция — `plans/ARCHITECTURE.md` **§55**. **Архив:** `plans/archive/hotfix3-summary-stt-anticliche-round1025/` (spec.md + adr-1025-7 + tasks.md; T-2482…T-2506). **⚠️ Открыто — live-гейт владельца (post-deploy, НЕ выполнено) — T-2505:** саммари с обложкой (`article sent`); видео 28 МБ (`reason=compressed`); ручное сохранение анти-клише «Сохранено N из M»; `llm_stats` в TMA.

**Триггер:** прод-дефекты после hotfix2 (`fea2daa`, 21.09.2026): (A) **[P0]** саммари уходит plain-текстом без обложки — Stage-1 «Редактор» System 2 handoff не парсится (`parse_summary_handoff` — невалидная выжимка) из-за таймаутов `nano-gpt.com` → `summary system2: невалидная выжимка редактора — fallback` → одиночный путь → `cover_prompt=""` → plain (успешные rich-отправки с обложкой в логах **есть**: 01:03/05:13/07:03); (B) **[P0]** видео/ГС не транскрибируются (лимиты 25/20 МБ, реальный файл 28 МБ) — нет извлечения/сжатия аудио перед STT; (C) **[P0]** анти-клише — `build_patterns` молча дропает ручные фразы (длина <2/>120, хардкод-клише, дубли, cap), API отдаёт 200 и уменьшенный `count`, UI всегда пишет «Сохранено»; (D) **[P1]** хронические LLM-таймауты `nano-gpt.com` (24ч: `ReadTimeout=189`, `LLMTimeoutError=28`, `GraphExtractionError=10`).

**Диагностика @explore + @DevOps — используется КАК ДАННОСТЬ, перепроверке не подлежит.**

**Задачи:** **T-2482…T-2506 (25)**. Преемственность: максимум до хотфикса — **T-2481** (`plans/archive/hotfix-media-tma-round1025/`), дублей нет. **Порядок: A ∥ C (независимы) → B → D → регресс → деплой/верификация.**

**Контуры работ (детали — `plans/archive/hotfix3-summary-stt-anticliche-round1025/tasks.md`):**
- **A — саммари/обложка** (T-2483…T-2487): разбивка fallback НЕ теряет обложку (генерировать `cover_prompt` + rich через `build_cover_media`/`send_rich_message`), либо устойчивость Stage-1 (retry при таймауте + безопасный парсинг `parse_summary_handoff`); обязательное логирование причины фолбэка (сейчас тихо); kill-switch env-only `SUMMARY_COVER_FALLBACK_ENABLED` (default ON). Файлы: `services/summary_generator.py` (`:393-399`, `:500-504`, `_deliver_rich` `:667-716`, логи `:685-709`), `services/telegram_send.py` (`:168-187`, `:190-215`). **Рабочий rich-путь не ломать.**
- **B — STT** (T-2494…T-2499): helper (ffmpeg → **ogg/opus mono 16 kHz ~24 kbps**) + fallback-чанкинг; покрыть видео (`handlers/youtube.py:607-655,1082-1206`) и ГС/кружки (`handlers/voice_transcription.py:272-280`); гейт `SmartModule/service.py:94-148` → compress-then-STT; логировать `reason=compressed`; kill-switch env-only `STT_AUDIO_COMPRESS_ENABLED` (default ON). Лимиты `config/settings.py:1373-1374`.
- **C — анти-клише честность** (T-2488…T-2493): возвращать разбивку отброшенного (`invalid|hardcoded|duplicate|over_limit`) + фактический `count`; UI `web/app.js:4938-4959` — честный warn «N из M»; согласовать лимит длины (**500 vs 120**); **ручные фразы пользователя НЕ фильтровать** хардкод-правилами (`find_forbidden_cliches`), применять их только к автогенерации. Файлы: `services/anticliche_worker.py:226-258`, `services/negative_constraints.py:217-237,297-335`, `web/api/anticliche.py:29-42,130-141`.
- **D — LLM-таймауты (P1)** (T-2500…T-2501): безопасная подстройка таймаутов/ретраев (fail-fast) и/или второй резервный провайдер; пометить корень как провайдерский; метрика доли таймаутов/fallback; логирование причины.
- **Регресс/ревью/деплой/верификация** (T-2502…T-2506): ✅ pytest **8041/0**, JS **22/22**, matrix **0**, `database is locked` = **0**; @Scanner Critical 0/High 0; деплой `5f624cd` (`APP_VERSION` 2.58.3, health 200); **⏳ live-гейт владельца T-2505** (обложка `article sent`; видео 28 МБ `reason=compressed`; анти-клише «Сохранено N из M»; `llm_stats` в TMA); архивация выполнена (Шаг 8 @PM).

**Флаги/откат:** поэтапная раскатка internal→10%→50%→100% **не требуется** (пет-проект, один прод) — env-only `ClassVar` kill-switches (`SUMMARY_COVER_FALLBACK_ENABLED`, `STT_AUDIO_COMPRESS_ENABLED`, default ON; OFF → прежнее поведение); откат — тег точки отката (T-2482) + `git revert`. **Δ DDL = 0**, **Δ каталога = 0**. Бэкапы/теги/`stash@{0}` не удалять (R18).

**Техдолг (§55, не блокеры):** grep-JS-тест анти-клише; реальный ffmpeg-прогон 28 МБ (не только мок); Info >999 частей; второй LLM-провайдер (не внедряем); **M-1** (сырой `file_path` в логе медиа → `name`); avatars `exc_info` (трейсбек не маскируется); vendor-скрипты без `?v=`; TOCTOU-guard (`exists()` перед копированием).

### 🖼️🧭 Хотфикс-4 после hotfix3 — `hotfix4-cover-nav-shell-round1025` (внеплановый, между hotfix3 и F2) — ✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED (21.09.2026)

**Статус:** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED.** Deploy `f2328fb`; `APP_VERSION` **2.58.4**, `/api/health`=200, `database is locked`=0. @Reviewer Approved; @Scanner **0 Critical / 0 High**. pytest **8071/0**, JS **23/23**, matrix **0**. **Δ DDL=0, Δ каталога=0**. Интеграция — `plans/ARCHITECTURE.md` **§56**. **Архив:** `plans/archive/hotfix4-cover-nav-shell-round1025/` (spec.md + adr-1025-8 + tasks.md; T-2507…T-2528). **⚠️ Открыто — T-2527 live-гейт владельца (post-deploy, НЕ выполнено):** обложка с авторским стилем (в логе `style_is_default=false` / `has_comic` / `has_heading` + `article sent`); панель/шторка в пределах экрана на mobile; Статус+Справка первыми.

**Триггер:** прод-дефекты после hotfix3 (`cfe7342`) по итогам раунда 10.25: **(A) [P0]** стиль обложки саммари не применяется; **(B) [P0]** нижняя панель mobile уезжает за экран; **(C) [P0]** Статус и Справка не первые в нижней навигации и не всем видны. **Диагностика @explore + @DevOps — используется КАК ДАННОСТЬ, перепроверке не подлежит.**

**Детали:** `tasks.md` — `plans/archive/hotfix4-cover-nav-shell-round1025/tasks.md`. **Задачи:** **T-2507…T-2528 (22)**; преемственность — максимум до хотфикса **T-2506**, дублей нет.

**Техдолг (§56, не блокеры):** fake-pool в `test_pg_backed`; доп. async `get_chat_param` на путь обложки (кэш TTL ~120 с); реальный ffmpeg-прогон 28 МБ; grep-JS-тест анти-клише; второй LLM-провайдер (не внедряем); M-1 лог `file_path`→`name`; avatars `exc_info`; vendor `?v=`; TOCTOU-guard.

**Контуры работ (детали — `tasks.md`):**
- **A — обложка/стиль** (T-2508…T-2513): R17-safe маркеры (`has_comic`/`has_heading`/`style_is_default`) вместо дампа текста; гарантировать применение настроенного `prompts.summary_cover_style` и его редактируемость в Mini App (`services/param_catalog.py:412-413`, `services/summary_generator.py:757-758`); устранить конфликт канона — `SUMMARY_EDITOR_COVER_PROMPT_BLOCK` (`services/summary_prompts.py:136-139`) запрещает «текст, буквы и водяные знаки», а владелец требует заголовок; починить баг `_resolve_cover_prompt` (`services/summary_generator.py:691-692`: непустой `draft` + пустой `cover_prompt` → `""`, фолбэк hotfix3 не срабатывает). **Рабочий rich-путь не ломать; Δ каталога = 0.**
- **B — панель/shell** (T-2514…T-2518): позиционирование `.bottom-nav` (`web/static/app.css:1345`, `bottom: 0` = layout-вьюпорт) относительно `--tg-viewport-stable-height` (`app.css:683`), симметрично `.more-sheet`; `--tg-viewport-bottom-offset` в `web/static/telegram-init.js` + `viewport-fit=cover` (`web/index.html:5`); вертикальная проверка `rect.bottom <= innerHeight` в `tools/ui_round1025_matrix.py`.
- **C — порядок навигации** (T-2519…T-2521): `bottomNavItems` (`web/app.js:1358-1373`) — `status`+`how` всегда первые два для всех ролей; `mobileMoreItems` (`web/app.js:1376-1381`) — убрать дубликат `how`, «Ещё» только для скрытых (`memory`/`access`/`permsoc`). **`services/param_catalog.py`/`sidebarGroups` не трогать.**
- **Регресс/деплой** (T-2522…T-2528): ✅ bump `APP_VERSION` **2.58.4**; pytest **8071/0**, JS **23/23**, matrix **0**; @Scanner 0/0; деплой `f2328fb` (health 200); **⏳ T-2527 live-гейт владельца** (обложка с **настроенным** стилем/заголовком, панель в пределах экрана, Статус+Справка первыми); архивация выполнена (Шаг 8 @PM).

**Флаги/откат:** поэтапная раскатка internal→10%→50%→100% **не требуется** (пет-проект, один прод; прецедент §53/§54.1/§55) — «поставка» = деплой + cache-bust `APP_VERSION`; откат — тег `pre-round1025-hotfix4` (T-2507) + `git revert`. **Δ DDL = 0**, **Δ каталога = 0**. Бэкапы/теги/`stash@{0}` не удалять (R18).

**Открытые вопросы:** где именно редактируется/теряется `prompts.summary_cover_style`; нужно ли явно разрешать заголовок «PERMsoc» в каноне; CSS-only фикс панели vs `--tg-viewport-bottom-offset`; нужен ли `viewport-fit=cover`; как уложить 5 пунктов админа в лимит 4; нужен ли env-only kill-switch для B/C.

### 🩹 Хотфикс-5 (пакет Волны 1) — `hotfix5-summary-cover-window-round1025` (внеплановый, после hotfix4, перед F3) — ✅ COMPLETED + MERGED + ARCHIVED (22.09.2026)

**Статус:** ✅ **COMPLETED + MERGED + ARCHIVED.** Коммиты базы `b3fb6a5` → ревью `cbaec05` → финал **`412f844`**. Merge — `plans/ARCHITECTURE.md` **§57.2**. @Reviewer **Approved**; @Scanner **C0/H0** (`plans/reports/round1025_hotfix5_scanner_audit.md` + пакетный `round1025_package_scanner_audit.md`). pytest базы 8041/0 → целевые **87 passed** / пакет **152 passed**, JS **24/24**; **Δ DDL=0, Δ каталога=0**. **✅ деплой пакетом (Шаг 9 @DevOps, коммит `4cde1bc`, `APP_VERSION` 2.58.6, health 200, `database is locked`=0) выполнен; ⏳ live-гейт владельца открыт.**

**Триггер:** verbose-путь генерации обложки умножал внешний ретрай ×2 на внутренний 429/503 (до **4 сетевых вызовов** / ~4×окна), слепой ретрай на невосстановимых классах (`bad_request`/`unauthorized`/`forbidden`/`payment_required`), смешение image- и LLM-бюджета, хрупкий `chat_id` в планировщике.

**Задачи:** T-2563…T-2573 (11, ретро-нумерация Шага 8). **Архив:** `plans/archive/hotfix5-summary-cover-window-round1025/` (ретро-оформлены `spec.md` + **ADR-1025-11** + `tasks.md`; папки/spec/ADR/tasks до Шага 8 отсутствовали — waiver/процессный техдолг).

**Фиксы (ADR-1025-11 D1–D4):** ≤2 попытки, владелец повторов — внешний цикл; `generate(..., retry=False)` → `_request_with_retry(max_retries=0)`; селективный ретрай (`is_transient_reason`), `break` на детерминированных; реальный дедлайн `asyncio.wait_for` → worst-case `attempts×окно+backoff` (**362 c**); отдельный **env-only** `image_calls`-бюджет (`WORKER_DAILY_IMAGE_CALLS_PER_CHAT/_GLOBAL`, ровно одно списание, LLM-контур изолирован); R17-safe логи (`reason`/`reason_class`/`provider`(host)/`chat_id`/`latency_ms`; `redact_url`); `int(raw_chat_id)` в `try/except` — тик не падает, DM-фильтр сохранён.

**Техдолг (§57.5):** L10.25H5-1 (полнота `reason_class`), L10.25H5-2 (grep-тест вместо поведенческого), балласт `*.zip`/бэкапов (git-ignored).

### 🌗 Хотфикс-6 (пакет Волны 1.5) — `hotfix6-webview-shell-heartbeat-round1025` (внеплановый, между F3 и F4) — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026); live-гейт владельца T-2617 ⏳

**Триггер:** **живая приёмка владельца после деплоя Волны 1** (пакет `4cde1bc`, `APP_VERSION` **2.58.6**): **A** Liquid Glass фактически без преломления/искажения + панели меню (sidebar/drawer) и шапка (header) без стекла (§9); **B** нижняя панель на мобильном всё ещё уползает за нижний край; **C** сердцебиение (§15) расширяется за пределы экрана на мобильном и фактически является SVG с циклической подсветкой вместо реального интерактивного Canvas 2D + `requestAnimationFrame`; **D** верхняя панель — ⛶ ниже нативных кнопок Telegram, плотная группа селектор/бейдж/аватар/роль, наложение на контент, фуллскрин не работает. **Источник анализа (Шаг 0 @Memory, KG `HOTFIX6-webview-shell-heartbeat-round1025`) — используется как данность, перепроверке не подлежит.**

**Статус:** ✅ **COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026; деплой VERIFIED — `055525c`+`ba75751`, `APP_VERSION` 2.58.7, health 200, `database is locked`=0); ⏳ live-гейт владельца T-2617 открыт.** Архив — **`plans/archive/hotfix6-webview-shell-heartbeat-round1025/`** (`spec.md` + **ADR-1025-12** + `tasks.md`, **T-2581…T-2618, 38**; дублей ID нет — максимум до пакета **T-2580**; T-2615 ревью/аудит ✅, T-2618 архивация ✅). Merge @Architect — `plans/ARCHITECTURE.md` **§58**. @Reviewer **Approved** (итер.2, 12/12); @Scanner **Critical 0 / High 0** / M1 / L3 / I3 (`plans/reports/round1025_hotfix6_scanner_audit.md`); AA — `plans/reports/round1025_hotfix6_contrast.md`. Baseline: HEAD **`441e8f7`**, `APP_VERSION` **2.58.6 → 2.58.7** (рабочее дерево), pytest **8146/5/1** (5 — env), SQLite `v12`; целевые pytest **119 passed**, JS-маркеры `HOTFIX6-LENS-HEARTBEAT-SHELL-OK`/`JS-UNIT-OK`. **Приёмка:** Playwright §71 (10 вьюпортов; в окружении не воспроизведён — нет `playwright`) **+ ОТДЕЛЬНО реальный Telegram WebView** (владелец, T-2617). **Инварианты:** Δ DDL = 0, Δ каталога = 0, CSP/zero-build (ADR-1016-2/ADR-1024-13), запрет WebGL (Canvas 2D разрешён), env-only UI-флаги (`GET /api/me.ui_flags`), **нативные кнопки Telegram CSS не двигать** (ARCHITECTURE §604/§642/§56), R17/R18.

**Блоки (детали — `tasks.md`):** **0** точка отката/baseline (T-2581) → **Step 2 @Architect** (T-2582) → **A1** преломление без `backdrop-filter: url()` (T-2583…T-2587: диагностика/тир, edge-weighted карта, честная лестница A/B/C, перф/reduced-motion, тесты) → **A2** стекло панелей sidebar/drawer/header/bottom-nav/more-sheet (T-2588…T-2592) → **B** `contentSafeAreaInset.bottom` + реальный WebView (T-2593…T-2596) → **C1** overflow heartbeats (T-2597…T-2598) → **C2** Canvas 2D + rAF по §15 (T-2599…T-2605: телеметрия отдельно/polling 10–30 с, состояния+гистерезис, тултип, реальные источники, reduced-motion) → **D1–D5** шапка (T-2606…T-2611) → атомарные маркер-тесты F2/F3/hotfix4 одним коммитом (T-2612), bump (T-2613), регресс (T-2614), ревью/аудит (T-2615), деплой (T-2616), live-гейт Playwright+реальный WebView (T-2617), архив (T-2618).

**⚠️ SUPERSEDE / AMEND (объявлено на Step 2, реализовано):** **§15 «живое сердцебиение» вынесено из F11** `status-showcase-dashboard-round1025` и реализовано в этом пакете (в F11 остаются §12/§13/§14/§16/§17/§18/§19/§20/§21); **AMEND ADR-1025-9** (F2: уровень A + стекло панелей), **AMEND ADR-1025-8/hotfix4** (B), **AMEND ADR-1025-10/F3 и F1** (D: перенос селектора/шапки); новый ADR — **ADR-1025-12** (Merge-карта §58.6).

**Остаточный техдолг (§58.7, не блокеры):** **[M-H6-1]** перф-цена foreground SVG-линзы (`feTurbulence`+`feDisplacementMap`) на реальном WebKit/iOS **не измерена** (преемник F2 `M10.25F2-3`; смягчено env-ручкой `UI_LENS_MAX_NODES`, подтверждение — в T-2617); **[L-H6-1]** Canvas-heartbeat `role="img"` на интерактивном элементе + «висячая» `aria-describedby="hb-tip"` (фикс — `role="button"`/`v-show`); **[L-H6-2]** линза на скролл-контейнерах (`overflow-y:auto`) прокручивается вместе с контентом (декоративно, контраст не затронут); **[L-H6-3]** комментарий `web/app.js:6534-6535` о stale-пороге расходится с кодом (`> 120000` мс); **[I-H6-3]** `README.md:5` «Тестов: 5936» устарело (предсуществующий `L10.25F2-4`); **[I-H6-1]** разовый `<canvas>` для feature-detect heartbeat (дёшево, Vue-кэш); **[Playwright Info]** матрица `tools/ui_round1025_matrix.py` не воспроизведена (нет `playwright`); **[Процессный — pending sync]** @Scanner не обновил `plans/reports/full_audit_results.md`/`audit_backlog.md` (только `global_map.md`) — закрыть на Шаге 10 @Memory.

**Флаги/откат:** поэтапная раскатка internal→10%→50%→100% **НЕ применяется** (пет-проект, один прод; прецедент §53/§54.1/§55/§56) — «поставка» = деплой + cache-bust `APP_VERSION`; env-only kill-switches `UI_GLASS_TIER_OVERRIDE`/`UI_HEARTBEAT_CANVAS_ENABLED`/`UI_HEADER_COMPACT_V2` (ADR-1024-13, default ON); откат — тег `pre-round1025-hotfix6` (T-2581) + `git revert`. Бэкапы/теги/`stash@{0}` не удалять (R18).

### ✅ Хотфикс-7 (Волна 1.6, ПРИОРИТЕТНЫЙ по UPD) — `hotfix7-shell-glass-heartbeat-round1025` (внеплановый, выше F4) — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026); Merge §59; live T-2682 ⏳ владелец

**Триггер:** **новый авторитетный приоритетный UPD владельца «Срочный фикс текущего фронта»** (`plans/current_task.md`, **строки 6073–6154**, прочитан дословно; файл НЕ изменялся). Текущая реализация верхней панели и glass-эффекта признана неудовлетворительной; UPD вышел **приоритетнее F4** → **F4 переведена в ⏸ PAUSED**. Источник анализа Шага 0 (@Memory) — **как данность** (`plans/workflow_state.md`, `plans/MEMORY.md`).

**Блоки UPD (1–6) + UPD 7:**
1. **layout + fullscreen** — стабильная геометрия header/sidebar/main/bottom-nav в desktop и mobile fullscreen; в fullscreen ничего не пропадает/режется/наезжает/меняет высоту; **виджет «Сердцебиение» не исчезает в fullscreen**; проверка container sizing/overflow/z-index/sticky/fixed/safe-area/высот и Telegram fullscreen/webview.
2. **heartbeat premium** — заменить «линию + плавающую точку» на premium pulse-индикатор; цвет/интенсивность от **реальных** метрик (норма — бирюзово-зелёный, warning — янтарный/оранжевый, critical — красно-розовый); пульс/свечение; **НЕ** бесконечный `translateX`; состояние читается с первого взгляда; normal/fullscreen/mobile.
3. **glass shell** — header и sidebar **серо-графитовые**, визуально отдельный слой, не в цвет карточек; shell vs карточки отличаются по тону и глубине.
4. **liquid glass качество** — полупрозрачный серо-графитовый base + backdrop blur + мягкая внутренняя подсветка + тонкая светлая обводка + слабый specular highlight + аккуратная текстура + разделение по глубине; **без грубой виньетки/грязного затемнения**; премиально и читабельно.
5. **shell-выравнивание** — header без наезда на контент; sidebar/topbar цельные; mobile safe-area/Telegram chrome/нижний bar/fullscreen; устранить съезды.
6. **обязательная проверка** — desktop normal, desktop fullscreen, tablet, mobile regular, **mobile fullscreen inside Telegram WebView**; скриншоты + Playwright (heartbeat виден везде, header не ломается, glass качественный, sidebar/topbar серые и отделены, ничего не съезжает).
7. **после фиксов (без human gate)** — аудит `current_task.md`, поиск невыполненных задач, продолжение по приоритетам; в отчёте явно: (1) что исправлено по UI, (2) какие пункты ТЗ оставались, (3) что взято следующим.

**Первопричины (Step 0 @Memory — как данность):** (a) `.app-sidebar` (`web/static/app.css:1570`) и карточки `.card/.module-card/.hub-card` (`:169-176`,`:1037`) используют **один** токен `--glass-bg=rgba(21,27,42,.5)` с одинаковым blur/бордером/тенью → shell слился с карточками; (b) `_hbDraw` (`web/app.js:6658-6674`) рисует бегущую синусоиду + сдвигающийся вбок импульс `pulseX` → «линия + плавающая точка»; (c) «грязный» вид: тяжёлая `--glass-shadow rgba(3,7,18,.75)` (`app.css:60`), плотный `body::before` (opacity .42, `:126-138`), подложка `.85`; (d) fullscreen: `.app-shell` одновременно `min-height: var(--tg-viewport-stable-height,100vh)` (`:805-810`) и `height:100dvh; overflow:hidden` (`:819-828`) — подозрение на обрезку; `--header-h` только `scroll-padding-top`.

**Статус:** ✅ **COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026); Merge `plans/ARCHITECTURE.md` §59 (@Architect).** **Архив — `plans/archive/hotfix7-shell-glass-heartbeat-round1025/`** (`spec.md` + **ADR-1025-13** + `tasks.md` + `evidence.md` + `review.md`; `deployment.md` допишет @DevOps на Шаге 9; содержимое/чекбоксы сохранены, UTF-8; **35 [x] / 2 [ ]** — открыты только **T-2690** deploy и **T-2682** live-гейт). **Задачи: T-2658…T-2694 (37)**; дублей ID нет (максимум занятого — F4 T-2657). @Reviewer **Approved** (итер.2, F-1…F-4 закрыты, `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → «к деплою ДА»** (`plans/reports/round1025_hotfix7_scanner_audit.md`); AA — `plans/reports/round1025_hotfix7_contrast.md`; матрица 5 режимов — `plans/reports/round1025_hotfix7_ui_report.md` (**failures: 0**). Числа: pytest **8207/0**, JS **27/27**, `APP_VERSION` **2.58.8**; **Δ DDL = 0**, **Δ каталога = 0** (459/98/96/21/418). **✅ deploy — Шаг 9 @DevOps (VERIFIED: коммиты `7073e34`/`a9cec67`/`2a67829`, `APP_VERSION` 2.58.8, health 200, `database is locked`=0); ⏳ live-гейт владельца T-2682.** Техдолг — **§59.8**: **L-H7-1** (мёртвый `@supports`-фолбэк shell из-за порядка каскада; AA безопасна 6.46:1), **L-H7-2** (OFF-путь флагов не «байт-в-байт»: рамка+тень header, DPR-cap в legacy), **L-H7-3** (specular∩texture worst-case 4.44:1), **Info** I-H7-1/-2/-3 + Playwright в CI @Scanner (опора на прогон @Builder). **Трассируемость UPD → задачи, инварианты** — в `plans/archive/hotfix7-shell-glass-heartbeat-round1025/tasks.md`.

**Блоки задач:** 0 точка отката/baseline + Step 2 (T-2658…T-2660) → **A** layout+fullscreen (T-2661…T-2665) → **B** heartbeat premium (T-2666…T-2670) → **C** glass shell (T-2671…T-2672) → **D** liquid glass (T-2673…T-2677) → **E** shell-выравнивание (T-2678…T-2680) → **F** приёмка 5 режимов + live-гейт (T-2681…T-2683) → **F2** регресс/инварианты/маркеры (T-2684…T-2685) → **G** ревью/аудит (T-2686…T-2687) → **H** Merge/bump/deploy (T-2688…T-2690) → **I** UPD 7 аудит ТЗ и продолжение (T-2691…T-2693) → **J** архивация/синк (T-2694).

**AMEND / СОХРАНИТЬ (Step 2):** **AMEND ADR-1025-12 D2** (стекло панелей) и **D4** (визуал heartbeat); **уточнение ADR-1025-9 D2** (значения). **СОХРАНИТЬ:** ADR-1025-12 **D3** (`computeBottomOffset` = max трёх инсетов), **D5** (нативные кнопки не двигать, `--header-h`, fullscreen-sync ADR-1024-24), **D1** (foreground-линза/feature-detect), deny-list tier C, фон §10, контраст AA §8, write-path F0 `persistItems`, IA F1, store-контракт F4 §37–§42.

**Инварианты:** **Δ DDL = 0**, **Δ каталога = 0**, CSP/zero-build (ADR-1016-2/ADR-1024-13), **запрет WebGL** (Canvas 2D/rAF — разрешён и переиспользуется), нативные кнопки Telegram CSS не двигать, IA/маршруты не ломать, новый редизайн с нуля запрещён. Откат — тег `pre-round1025-hotfix7` (T-2658) + `git revert`; soft — env-only `UI_GLASS_TIER_OVERRIDE`/`UI_HEARTBEAT_CANVAS_ENABLED`/`UI_HEADER_COMPACT_V2` (default ON). Бэкапы/теги/`stash@{0}` не удалять (R18).

**Аудит остатка ТЗ (UPD 7) — ✅ выполнен:** **`plans/reports/round1025_tz_remaining_audit.md`** (+ **§9 «Итоговый отчёт UPD-7»** — три обязательных блока) — что закрыто (F0/F1/F2/F3 + hotfix-media/2/3/4/5/6 + §15 + **HOTFIX7**), что осталось (F4 ⏸, F5–F11; Эпик 2 S1–S10; Эпик 3 A0–A10; внеплановый бэклог), рекомендуемый порядок. **Порядок продолжения (обновлён Шаг 8 @PM по HOTFIX8):** **HOTFIX7 ✅ → F4 ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (2.58.9) → F5 ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026; Merge §61; deploy ✅ Шаг 9 @DevOps, `APP_VERSION` 2.58.10; live T-2742 ⏳) → HOTFIX8 ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM, 22.09.2026; Merge §62; deploy ✅ Шаг 9 @DevOps, `APP_VERSION` 2.58.11; live T-2776 ⏳) → HOTFIX9 ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026; Merge §63; задеплоено 2.58.12; live T-2830 ⏳ PENDING OWNER VERIFICATION) → **HOTFIX10** ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026; Merge §64; архив — `plans/archive/hotfix10-liquidglass-rollback-shell-geometry-round1025/`; deploy ✅ задеплоено 2.58.13 (Шаг 9 @DevOps, `deployment.md` VERIFIED); live ⏳ PENDING OWNER VERIFICATION) → **F6** ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026; Merge §65; архив — `plans/archive/memory-analytics-reorg-round1025/`; deploy ✅ задеплоено 2.58.14 (Шаг 9 @DevOps, `deployment.md` VERIFIED), live ⏳ PENDING OWNER VERIFICATION) → **F7** `permsoc-local-space-round1025` ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 23.09.2026; Merge §66; архив — `plans/archive/permsoc-local-space-round1025/`; deploy ✅ задеплоено 2.58.15 (`deployment.md` VERIFIED, health 200, `database is locked`=0), live ⏳ PENDING OWNER VERIFICATION) → **F8** ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026; Merge §67; deploy **NOT_APPLICABLE**) → **F9** `secrets-and-save-states-round1025` ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026; Merge §68; архив — `plans/archive/secrets-and-save-states-round1025/`; @Reviewer Approved итер.2, @Scanner C0/H0/M0/L0/Info 2; техдолг §68.8; deploy ⏳ Шаг 9 @DevOps (T-3058); live ⏳ PENDING OWNER VERIFICATION (T-3059)) → **▶️ следующая F11** `status-showcase-dashboard-round1025` → **F10** `epic1-verification-round1025` → СТОП-ГЕЙТ Эпика 1 → Эпик 2 → Эпик 3. **HOTFIX9 задеплоен (2.58.12); HOTFIX10 (UPD4, P0) — ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026; Merge §64), deploy ✅ задеплоено 2.58.13 (Шаг 9 @DevOps); F6 — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаги 8–10 @PM/@DevOps/@Memory, 23.09.2026; Merge §65), deploy — ✅ задеплоено 2.58.14 (Шаг 9 @DevOps, T-2916); следующая — F7 `permsoc-local-space-round1025` немедленно** (T-2869, §8, без human gate).

### ✅ Хотфикс-8 (Волна 1.7, ПРИОРИТЕТНЫЙ по UPD2) — `hotfix8-shell-glass-aurora-round1025` (внеплановый, выше F6) — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM, 22.09.2026; Merge §62; deploy ✅ Шаг 9 @DevOps — задеплоено 2.58.11); live T-2776 ⏳ владелец

**Триггер:** **новое авторитетное приоритетное уточнение владельца** `plans/current_task.md`, **строки 6156–6496** («# UPD2: СРОЧНОЕ УТОЧНЕНИЕ ПО SHELL / LIQUID GLASS / BACKGROUND», прочитано дословно, файл **НЕ изменялся**). Текущая реализация shell / Liquid Glass / фона признана не соответствующей ТЗ; UPD2 **приоритетнее F6** → **F6 `memory-analytics-reorg-round1025` — ⏸ «ЖДЁТ»**. Источник анализа Шага 0 (@Memory) — **как данность** (`plans/workflow_state.md`, `plans/MEMORY.md`).

**Скоуп UPD2 (§1–§10):** (A) **layout/shell/mobile/fullscreen** — съезды, наложения в шапке, перекрытие контента bottom-nav, конфликт SaveBar↔внутренний скролл, стабильная геометрия (§1.1/§5.4/§5.5/§7); (B) **Liquid Glass** — вернуть sidebar/topbar тёмно-серый графитовый характер, снять цветную «линзу»/ореол/виньетку (`[data-glass="a"]::before`), отделить shell от карточек, точные токены §4 (bg .72/.78, border .08, highlight .06, shadow `0 8px 24px .18`, backdrop `blur(18px) saturate(115%)`), очень слабый SVG displacement, радиусы (§1.2/§3/§4/§5.1–5.3); (C) **aurora/mesh background** — заменить почти мёртвый conic-градиент на 3–5 размытых blob-слоёв (сине-фиолет/бирюза/deep teal/индиго, разные фазы, morphing, слабый grain, пауза hidden) (§1.3/§6); (D) приёмка 5 режимов + аудит остатка ТЗ (§8.5/§9/§10).

**⚠️ Объективное ограничение (НЕ human gate, решение @Architect):** UPD2 §2 упоминает «**Framer Motion**» и «**React**». Проект — **Vue 3 global zero-build + CSP `script-src 'self'`** (ADR-1016-2/ADR-1024-13): без CDN/инлайна/новых библиотек/сборщика. **Framer Motion React-only → подключить нельзя.** Эквивалент (CSS / WAAPI / Canvas 2D / SVG) выбирает **@Architect → ADR-1025-16**.

**Статус:** ✅ **COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026).** Merge — `plans/ARCHITECTURE.md` **§62** (T-2785, Шаг 7 @Architect); **архив — `plans/archive/hotfix8-shell-glass-aurora-round1025/`** (`spec.md` + **ADR-1025-16** + `tasks.md` + `evidence.md` + `review.md`; `deployment.md` допишет @DevOps на Шаге 9; содержимое/чекбоксы сохранены, UTF-8; **41 [x] / 4 [ ]**). **Задачи — T-2745…T-2789 (45)**; дублей ID нет (максимум занятого до пакета — F5 **T-2744**). @Reviewer **Approved** (T-2783, `review.md`); @Scanner **Critical 0 / High 0 / Medium 0** (T-2784; Low 3 / Info 3 — follow-up; `plans/reports/round1025_hotfix8_scanner_audit.md`); AA — `plans/reports/round1025_hotfix8_contrast.md`; матрица 5 режимов — `plans/reports/round1025_hotfix8_ui_report.md` (**failures: 0**). Baseline HEAD **`a1e6db3`** (= tag `pre-round1025-hotfix8`), `APP_VERSION` **2.58.10**. **Δ DDL=0, Δ каталога=0** (459/98/96/21/418), CSP/zero-build, без WebGL/новых библиотек. **✅ deploy — Шаг 9 @DevOps (T-2786 bump 2.58.10→2.58.11 → T-2787 deploy, **VERIFIED** — задеплоено 2.58.11; коммиты `98551b2`/`5124522`/`1a8ed18`/`d3179c1`, прод fast-forward `af137cd..1a8ed18`, `/api/health` **200**, `database is locked`=0); ⏳ live-гейт владельца T-2776.** Техдолг — **§62.7** (L-H8R-1…5 / L-H8S-1…3, не блокеры). **Следующая — F6 `memory-analytics-reorg-round1025` (после деплоя HOTFIX8).**

**Корневые причины (по коду = данность Step 0):** (1) shell-панели несут `data-glass="a"` (`index.html:55/3824/3840`) → `[data-glass="a"]::before` (`app.css:1142-1157`) рисует **цветную линзу** teal/blue/violet с radial-mask = «аура/виньетка»; (2) `--shell-border-color .20`/`--shell-highlight .18` слишком светлые = «дешёвый ореол»; (3) shell-токены не совпадают с UPD2 §4; (4) фон — один conic-слой 75–105 с, opacity .30 = визуально мёртв.

**Блоки задач:** 0 baseline + Step 2 (T-2745…T-2747) → **A** layout/shell/mobile/fullscreen + SaveBar/scroll (T-2748…T-2756) → **B** Liquid Glass: токены §4 + снятие линзы/halo + subtle стекло (T-2757…T-2766) → **C** aurora/mesh background (T-2767…T-2773) → **D** приёмка 5 режимов + acceptance §9 + аудит ТЗ §10 (T-2774…T-2780) → **E** регресс/инварианты (T-2781…T-2782) → **F** ревью/аудит (T-2783…T-2784) → **G** Merge §62 / bump 2.58.11 / deploy / архивация / метрики (T-2785…T-2789).

**Acceptance criteria UPD2 §9 (зафиксированы явно; полный список — в `tasks.md`):** **НЕ принято** — shell как карточки; яркий ореол вокруг shell; дешёвый blur/виньетка; статичный фон; mobile перекрывает контент; конфликт SaveBar↔scroll; нет разделения по глубине. **Принято** — shell тёмно-серый glass-слой; стекло subtle/дорогое/аккуратное; фон живой и атмосферный; desktop/mobile/fullscreen стабильны; единый polished Control Center UI. **5 режимов:** desktop normal · desktop fullscreen · tablet · mobile portrait · **mobile fullscreen inside Telegram WebView**.

**Открытые вопросы для @Architect:** (a) эквивалент Framer Motion; (b) точная механика aurora (blob-слои / Canvas 2D+RAF) в рамках CSP; (c) как снять линзу с shell, сохранив стекло; (d) точные значения токенов/радиусов и разделение фон→shell→карточки; (e) где снять/оставить SVG displacement.

**Инварианты:** **Δ DDL = 0**, **Δ каталога = 0**, CSP/zero-build (ADR-1016-2/ADR-1024-13), **без WebGL**, **без новых библиотек** (в т.ч. Framer Motion/React), IA/маршруты не ломать, новый редизайн с нуля запрещён; **сохранить** F5 §61 / F4 §60 / F1 / F2 / F3, **SaveBar F9**, `computeBottomOffset`/hotfix4, fullscreen-sync ADR-1024-24, hotfix7 shell-layout/AA/§15. Откат — тег `pre-round1025-hotfix8` (T-2745) + `git revert`; soft — env-only `UI_SHELL_GLASS_V2`/`UI_AURORA_BG_ENABLED` (default ON). Бэкапы/теги/`stash@{0}` не удалять (R18).

### ✅ Хотфикс-9 (Волна 1.8, ПРИОРИТЕТНЫЙ по UPD3) — `hotfix9-shell-liquidglass-darkaurora-round1025` (внеплановый, выше F6) — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026; Merge §63; задеплоено 2.58.12); live ⏳ PENDING OWNER VERIFICATION

**Триггер:** **новое авторитетное приоритетное ТЗ владельца** `plans/current_task.md`, **строки 6499–7264** («# UPD3: HOTFIX — SHELL / LIQUID GLASS / BACKGROUND / RESPONSIVE», прочитано дословно; файл **НЕ изменялся**). Реализация shell/glass/фона признана не соответствующей ТЗ; UPD3 был **приоритетнее F6** → после завершения HOTFIX9 **F6 `memory-analytics-reorg-round1025` — следующая немедленно** (UPD3 §17, без human gate). Карта кода Step 0 @Memory (диагональная текстура `--shell-texture`, геометрия `--shell-h`/`computeBottomOffset`, модалки/`.sticky-save`, фон/`.aurora-bg`, стекло `[data-glass="shell"]`/`#lg-lens`) — **как данность**.

**Статус:** ✅ **COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026).** Merge — `plans/ARCHITECTURE.md` **§63** (@Architect, Step 7); **архив — `plans/archive/hotfix9-shell-liquidglass-darkaurora-round1025/`** (`spec.md` + **ADR-1025-17-shell-flex-aurora-glass-csp** + `tasks.md` + `evidence.md` + `review.md`; содержимое/чекбоксы сохранены, UTF-8; **48 [x] / 2 [ ]** — открыты **T-2830** (live PENDING OWNER VERIFICATION), **T-2839** (продолжение F6); **T-2837** (deploy, Шаг 9) и **T-2838** (архивация/синхронизация) ✅). **Задачи — T-2790…T-2839 (50)**; дублей ID нет (максимум занятого до пакета — HOTFIX8 **T-2789**). @Reviewer **Approved** (T-2835, итер.2; блокер H-H9S-1 и M-H9R-1 закрыты; `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 3 → «к деплою ГОТОВО»** (T-2836; `plans/reports/round1025_hotfix9_scanner_audit.md`). Baseline HEAD **`b374c0f`** (= tag `pre-round1025-hotfix9`), `APP_VERSION` **2.58.11**. Прогоны: pytest **8291 passed / 0 failed** (baseline 8272; hotfix9 17/0); матрица `tools/ui_round1025_matrix.py` — **failures 0** (10 вьюпортов × 5 режимов); `tools/glass_prototype_probe.py` — **failures 0** (`displacementScale=14.56`, `diffGlass=15.97`, `diffHole=63.817`); `node --check` OK; `git diff --check` = 0. **Δ DDL=0, Δ каталога=0** (459/98/96/21/418), CSP same-origin vendored (без CDN/inline/eval), SHA-256 vendored 3/3. **✅ deploy — Шаг 9 @DevOps (T-2837, VERIFIED — задеплоено 2.58.12; коммиты `470b63a`/`8d61926`/`dba76e8`, `APP_VERSION` 2.58.11 → 2.58.12, `/api/health`+`/healthz` 200, served `?v=2.58.12`, `database is locked`=0, `deployment.md` VERIFIED); ⏳ live — T-2830 PENDING OWNER VERIFICATION (реальный Telegram WebView не проведён).** Техдолг — **§63.11** (Info 3 + Low 0, не блокеры). **Следующая — F6 `memory-analytics-reorg-round1025` (немедленно после деплоя HOTFIX9, §17, без human gate).**

**Скоуп UPD3 §0–§17 (порядок §2):** (1) геометрия + flex-колонка `shell-mobile` §3/§4 (без новых компенсационных отступов); (2) **нижняя mobile nav P0** внутри flex, safe-area ровно один раз, удалить старый fixed/bottom-offset §4; (3) header/fullscreen через grid/flex, scrollTop при смене раздела, виджеты не исчезают §5; (4) modal/drawer/SaveBar — footer `.modal-actions`, высоты 600–700 px, клавиатура, nav не просвечивает §6; (5) **полное удаление диагональной текстуры** со всех shell-поверхностей §7; (6) графитовый shell по §8 (стартовые токены); (7) **настоящее преломление** — изолированный прототип (`@liquidglassjs/core` **либо альтернатива объективно**) + точечное применение (селектор, ⛶, 1–2 карточки Статуса), sidebar/header — слабый frosted §9; (8) **Dark Aurora Flow** (OGL либо Canvas2D/SVG-фолбэк) §10; (9) Playwright+DOM §12; (10) деплой §14; (11) аудит ТЗ и **немедленное продолжение F6** §15/§17. **§11** — сердцебиение: только устранить исчезновение в fullscreen, **дизайн не менять**.

**Блоки:** 0 baseline+Step 2 (T-2790…T-2792) → **A** геометрия/flex (T-2793…T-2797) → **B** bottom-nav P0 (T-2798…T-2801) → **C** header/fullscreen (T-2802…T-2805) → **D** modal/SaveBar (T-2806…T-2809) → **E** удаление текстуры (T-2810…T-2811) → **F** графит §8 (T-2812…T-2813) → **G** преломление §9 (T-2814…T-2819) → **H** Dark Aurora §10 (T-2820…T-2825) → **I** Playwright/DOM §12 (T-2826…T-2830) → **J** сердцебиение §11 (T-2831…T-2832) → **K** регресс/bump/ревью/аудит/деплой/F6 (T-2833…T-2839).

**⚠️ AMEND — СНЯТИЕ CONSTRAINT «no-libraries» (§1):** внешние библиотеки **РАЗРЕШЕНЫ владельцем** (AMEND прежнего запрета): без Vue→React, без переписывания, **без CDN**, фиксированные версии, локальная сборка клиентских зависимостей, раздача с собственного сервера, проверка CSP/Telegram WebView; npm — инструмент сборки **без** полной миграции сборки. Реализуемо: vendored-бандл `web/static/vendor/` + same-origin `<script src="/static/…">` при CSP `script-src 'self'`. Кандидаты: `@liquidglassjs/core` (§9), **OGL** (§10). **AMEND-карта:** **ADR-1025-16** (D1/D2/D3), **ADR-1025-13**, **ADR-1025-9**; новый **ADR-1025-17** (создаёт @Architect).

**Acceptance criteria UPD3 §13 (зафиксированы явно):** 10 «работа НЕ принята» — nav за экран; header перекрывает контент; модалка скрывает настройки; SaveBar перекрывает последнее поле; сердцебиение исчезает в fullscreen; на shell осталась текстура; shell окрашивается фоном; сильные ореолы; стекло = декоративная виньетка; фон неподвижен. **Доказательная планка:** новый токен / подключение библиотеки / успешная сборка / **Approved** — **НЕ доказывают** выполнение; нужны воспроизводимые проверки §12. **PENDING OWNER VERIFICATION** (живой Telegram WebView) — **не** основание останавливать workflow (§15).

**Инварианты:** **Δ DDL=0**, **Δ каталога=0**, CSP/zero-build (ADR-1016-2/ADR-1024-13), **нативные кнопки Telegram CSS не двигать**, сохранить IA F1 / store F4 §37–§42 / write-path F0 / §11-дизайн сердцебиения, редизайн с нуля запрещён. Откат — тег `pre-round1025-hotfix9` (T-2790) + `git revert`. Бэкапы/теги/`stash@{0}` не удалять (R18).

**Открытые вопросы для @Architect:** (a) flex-колонка vs `computeBottomOffset`/`--shell-h`/fullscreen-sync **ADR-1024-24** — единый источник высоты; (b) объективный разбор `@liquidglassjs/core` (в т.ч. запрещённый `backdrop-filter: url()` по hotfix6); (c) локальная сборка vendored-бандла под CSP (OGL/`@liquidglassjs/core`, DPR-кап, mobile ≈30 FPS); (d) разделение слоёв и удаление `--shell-texture` (сохранить ли `--shell-specular`, AA worst-case L-H7-3); (e) механика Dark Aurora Flow и её фолбэки.

### 🧊🚫 Хотфикс-10 (Волна 1.9, ПРИОРИТЕТНЫЙ по UPD4) — `hotfix10-liquidglass-rollback-shell-geometry-round1025` (внеплановый, выше F6) — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаги 8–9 @PM/@DevOps, 23.09.2026; Merge §64; задеплоено 2.58.13); live ⏳ PENDING OWNER VERIFICATION; F6 — следующая немедленно

**Триггер:** **новое авторитетное приоритетное ТЗ владельца** `plans/current_task.md`, **строки 7267–7482** («# UPD4: P0 HOTFIX — исправление интеграции Liquid Glass и геометрии AppShell», прочитано дословно; файл **НЕ изменялся**). UPD4 **приоритетнее F6** → **F6 `memory-analytics-reorg-round1025` — следующая немедленно после деплоя HOTFIX10** (§8, без human gate). Карта кода Step 0 @Memory — **как данность** (`plans/workflow_state.md`, `plans/MEMORY.md`, `plans/archive/hotfix10-liquidglass-rollback-shell-geometry-round1025/tasks.md`).

**Суть UPD4 §1–§8 + Доп.P0:** (1) **немедленно** отключить `UI_LIQUID_GLASS_LIB` и снять `mountGlass()` с `.scope-trigger`/`.header-fs-btn`/`.status-block` (белые непрозрачные прямоугольники = белый frosted-fallback без `refract`/`source`), полный reload, точечная чистка `.ps-glass__surface/__tint/__rim`/`.ps-glass` **только там, где добавлено экспериментом**, восстановить содержимое селектора/fullscreen/карточки; (2) **правильная реинтеграция** — отдельный декоративный слой в специальном `GlassSurface` (фон/преломление ниже контента, текст выше, без перехвата кликов/изменения геометрии, корректный unmount) только на **1 изолированном декоративном** элементе, честный детект режима (frosted ≠ «рефракция»); (3) **единая рабочая поверхность Main** (убрать цветную полосу слева, без отрицательных отступов, сохранить лимит ширины карточек 1100px); (4) **единая модель высоты** + устранение **двойного** вычета safe-area, вывод конфликтующих legacy-правил nav (`.more-sheet :2033-2053`, `.fullscreen-mode .scroll-area :1042`, legacy `.bottom-nav :1989-1995`); (5) **восстановить `.status-block`** (убрать стеклянный слой, полная видимость сердцебиения/метрик, `overflow`/высоты); (6) **фон не переделывать** — исправить геометрию и анимацию существующего OGL (экспорт/вызов `resize` фона при resize/fullscreen/viewport-смене, пересчёт drawing buffer + viewport + uniforms, `rAF`/время/hidden/reduced-motion, композиция без полосы слева, порядок слоёв 1–5, **без CSS-градиентов**); (7) **два раздельных набора проверок** (без библиотеки / с библиотекой на 1 элементе) + mobile nav/fullscreen/селектор/карточка; (8) **деплой + немедленное продолжение F6** без human gate. **Amend:** ADR-1025-17 **D5/D6**; новый **ADR-1025-18** (создаёт @Architect, Step 2).

**Статус:** ✅ **COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026).** Merge — `plans/ARCHITECTURE.md` **§64** (@Architect, Step 7); **архив — `plans/archive/hotfix10-liquidglass-rollback-shell-geometry-round1025/`** (`spec.md` + **ADR-1025-18** + `tasks.md` + `evidence.md` + `review.md`; содержимое/чекбоксы сохранены, UTF-8; **28 [x] / 2 [ ]** — закрыт **T-2867** (deploy — ✅ @DevOps, `deployment.md` VERIFIED, 2.58.13); открыты **T-2862** (live WebView, **PENDING OWNER VERIFICATION**) и **T-2869** (продолжение F6); T-2868 архивация ✅). @Reviewer **Approved** (T-2865, итер.2; блокер H-1 и Low L-H10-1/L-1/L-2 закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 1 → «к деплою ГОТОВО»** (T-2866; `plans/reports/round1025_hotfix10_scanner_audit.md`). Baseline HEAD **`5184584`** (= tag `pre-round1025-hotfix10`), `APP_VERSION` **2.58.12 → 2.58.13** (✅ закоммичен и задеплоен — Шаг 9 @DevOps: `bf086d4`/`24dc7e3`/`8964f07`). Прогоны: pytest **8319 passed / 0 failed** (baseline 8291), JS **35/35**, матрица `tools/ui_round1025_matrix.py` **failures: 0** (10 вьюпортов, normal+fullscreen, OFF на 5 ширинах), `node --check` OK, `git diff --check`=0. **Δ DDL=0, Δ каталога=0** (459/98/96/21/418), CSP same-origin (без CDN/inline/eval), `--shell-texture`=0, `backdrop-filter:url(`=0. **✅ deploy — Шаг 9 @DevOps (T-2867, VERIFIED — задеплоено 2.58.13; коммиты `bf086d4`/`24dc7e3`/`8964f07`, прод fast-forward `8d61926..24dc7e3`, `/api/health` 200, served `?v=2.58.13`, `database is locked`=0, `deployment.md` VERIFIED; «HTTP 200 ≠ корректный layout»); live — PENDING OWNER VERIFICATION (T-2862, реальный Telegram WebView не проведён, Chromium не выдаётся за WebView).** Техдолг — **§64.9** (Info I-H10-3: глобальный `main.scroll-area{grid-auto-rows:max-content}` — наблюдать «пустые» вкладки на live; прочие не блокеры). **Следующая — F6 `memory-analytics-reorg-round1025` (немедленно — деплой HOTFIX10 выполнен, T-2869, UPD4 §8, без human gate).**

**Задачи:** **T-2840…T-2869 (30)**, блоки: 0 baseline+Step 2 (T-2840…T-2842) → **A** §1 откат стекла (T-2843…T-2847) → **B** §2 `GlassSurface` (T-2848…T-2851) → **C** §3 Main (T-2852) → **D** §4 высота/nav (T-2853…T-2854) → **E** §5 `.status-block` (T-2855) → **F** §6+Доп.P0 фон OGL (T-2856…T-2858) → **G** §7 проверки (T-2859…T-2862) → **H** регресс/bump/ревью/аудит/деплой/архив/F6 (T-2863…T-2869). Дублей ID нет (максимум занятого до пакета — HOTFIX9 **T-2839**).

**Критерии приёмки (зафиксированы явно, полный список — в `tasks.md`):** белые прямоугольники устранены **не** снижением `opacity`; библиотека **не** монтируется на функциональные Vue-компоненты; frosted не выдаётся за преломление; нет яркой вертикальной полосы между Sidebar и Main; 4 пункта nav с подписями видны и нажимаемы; `.status-block` полностью видим и не перекрыт, дизайн не изменён; фон покрывает всю область в normal/fullscreen, сохраняет композицию при resize и реально анимируется (5–10 с); **не** добавлены CSS-градиенты; **не** объявлять дефект устранённым по сборке/Reviewer; **живой WebView — PENDING OWNER VERIFICATION** (не Chromium).

**Инварианты:** **Δ DDL=0**, **Δ каталога=0**, CSP/zero-build (ADR-1016-2/ADR-1024-13), без новых библиотек/WebGL-переделки, нативные кнопки Telegram CSS не двигать, IA F1/store F4 §37–§42/write-path F0 `persistItems` сохранить, редизайн с нуля запрещён. Baseline HEAD **`5184584`**, `APP_VERSION` **2.58.12**, pytest **8291/0** (459/98/96/21/418). Откат — тег `pre-round1025-hotfix10` (T-2840) + `git revert`. Бэкапы/теги/`stash@{0}` не удалять (R18). **Следующая — F6 `memory-analytics-reorg-round1025` (немедленно после деплоя HOTFIX10, T-2869, без human gate).**

**Открытые вопросы для @Architect:** (a) судьба `UI_LIQUID_GLASS_LIB` (kill-switch OFF vs удаление); (b) контракт `GlassSurface` (слои/`pointer-events`/unmount/детект режима; на каком **одном** изолированном элементе); (c) где подложка Main (`.app-shell` vs `main.scroll-area`) и как сохранить лимит 1100px **без** отрицательных отступов; (d) единственный источник высоты (`--app-usable-height` vs `computeBottomOffset` vs `100dvh`) и снятие второго вычета; (e) экспорт/вызов resize OGL-фона и пересчёт drawing buffer/uniforms.

### 🗺️ ЭПИК 1 (Раунд 10.25) — «Liquid Glass Control Center» — 12 фич (F0 + F1–F11; F0 добавлена UPD, F11 добавлена @PM)

| # | Фича (папка `plans/features/…-round1025/`) | ТЗ | Тип | Приоритет | Зависит от | Задачи |
|---|---|---|---|---|---|---|
| **F0** ✅ | `f0-config-bugfixes-round1025` — **✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (`plans/archive/f0-config-bugfixes-round1025/`, Шаги 8–9, 20.09.2026); деплой `3a91c84` (health 200); live-приёмка: T-2454 ✅ подтверждён, T-2419/T-2433 — ручные (владелец).** **UPD/НОВАЯ (Wave 0, ДО F1):** обязательные багфиксы сохранения конфигурации — **F0.1** конфликт версий 409 (конкурентные мутации `prompts.verbilizer_default_mode`: saveConfigItem + saveModalEdits/sticky-SaveBar + saveBlock; нет сериализации и единой state-machine; глобальный путь без optimistic-проверки), **F0.2** аудит **всех** save-механизмов (load→edit→save→re-read→compare), **F0.3** анти-клише (лимит 200 vs фактические 20; ложная «Ошибка модели»; per-chat trap — воркер читает только global; события `ANTI_CLICHE_*`), **F0.4** тосты/SaveBar (одно итоговое уведомление на операцию, safe area, «Подробнее» вместо stack trace), **🆕 F0.5** устойчивость к `database is locked` (расширение ADR-1024-18 на `database.py`/`summary_memory`/`persistent_throttling`) | UPD §1–§6 + «КРИТИЧЕСКОЕ ОБНОВЛЕНИЕ» (стр. 5920–6024) | backend+UI (persistence/state) + backend (надёжность БД) | **P0** | — (Wave 0, **ДО F1**) | **T-2410…T-2455 (46) — детально ниже** |
| **F1** ✅ | `ia-shell-navigation` — **✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED (`plans/archive/ia-shell-navigation-round1025/`, Шаг 8 @PM 21.09.2026); деплой `fe0f7bb` (`APP_VERSION` 2.58.2); @Scanner 0 Critical/0 High (H-1 закрыт); ⏳ live-гейт владельца: T-2409 очистка бэкапа.** новая IA §4 (Статус=старт, Память отдельным разделом, PERMsoc локально), desktop/mobile shell §6/§7 (sidebar ≥1200, планшет 768–1199 — drawer/компакт), hash-deeplink, Справка/Доступы §68, сохранность разделов, доступ к старому каталогу/виджетам, нижнее меню 4 пункта | §4–§7, §68, §70 | IA/shell (web) | **P0** | **F0** (контракт сохранения), F8 (инвентарь/бэкап) | **T-2388…T-2409 (22) — детально ниже** |
| **F2** ✅ | `design-tokens-liquidglass-v2-round1025` — **✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026); Merge `plans/ARCHITECTURE.md` §57.1; финал кода `d2df8ca` (база `e895726`, ревью `0f227a5`); `APP_VERSION` 2.58.5.** Архив — `plans/archive/design-tokens-liquidglass-v2-round1025/` (`spec.md` + `adr-1025-9-design-tokens-liquidglass-v2.md` + `tasks.md`, T-2529…T-2562, 32/34 [x]; **T-2560 deploy выполнен пакетом `4cde1bc`; открыт только T-2561 live-гейт**). @Reviewer **Approved**; @Scanner **C0/H0** (`plans/reports/round1025_f2_scanner_audit.md` + пакетный `round1025_package_scanner_audit.md`) — палитра §8 (SUPERSEDE OD4 + glass 10.20 + `--grad-d #FF8A3D`/`--grad-speed:6s`; AMEND ADR-1020-9), Liquid Glass A/B/C §9 (`feDisplacementMap`, deny-list textarea/таблиц/логов/форм/редакторов), фон 60–90/90–120 с §10 (без оранжевого), контраст AA (`.75rem`), inventory-тест маркеров, Playwright §71 (10 вьюпортов). Техдолг: F2 M-3 (остаточный Medium), L-1/-2/-4, NEW-L1 (iOS Edge UA-gate), NEW-L2. **✅ T-2560 (deploy пакетом `4cde1bc`, `APP_VERSION` 2.58.6) выполнен; ⏳ T-2561 (live-гейт владельца) открыт.** | §8–§10, §70, §71, §117 п.7–8 | визуальная система (web/CSS) | **P0** | F1 | **T-2529…T-2562 (34)** |
| **F3** ✅ | `global-scope-selector-round1025` — **✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026); Merge `plans/ARCHITECTURE.md` §57.3; финал кода `4f31197` (база `76a6c40`, ревью `fb49f29`); `APP_VERSION` 2.58.6.** Архив — `plans/archive/global-scope-selector-round1025/` (ретро-оформлены `spec.md` + **ADR-1025-10** + `tasks.md` T-2574…T-2580). Постоянный селектор области §5 (Глобально/Чат/ЛС, поиск, полный `chat_id` только в `.scope-tech`), источник значения, **«Вернуть глобальное» = DELETE override (не заводской сброс)**, guard несохранённых (`hasUnsavedEdits` + черновики блоков `blockDrafts`/API-ключ/persona/dossier), stale-эпоха (`scopeEpoch`/`_scopeGuard`), §43 «Ожидает применения» — N/A (read-through). @Reviewer iter1/iter2 **Approved**; @Scanner **C0/H0** (`round1025_f3_scanner_audit.md` + пакетный). **Waiver:** Step 2 @Architect формально не оформлялся — ретро-артефакты (процессный техдолг). **✅ deploy пакетом (`4cde1bc`, `APP_VERSION` 2.58.6) выполнен; ⏳ live-гейт владельца открыт.** | §5, §14, §42, §43, §74 | UI+state (web) | **P0** | F1 | **T-2574…T-2580 (ретро)** |
| **F4** ✅ | `module-catalog-quickpanel-store-round1025` — **✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026); Merge `plans/ARCHITECTURE.md` §60 (@Architect, T-2652); архив — `plans/archive/module-catalog-quickpanel-store-round1025/`.** `tasks.md` (блоки 0, A–H, 9; **T-2619…T-2657, 39**; дублей ID нет — максимум до hotfix6 T-2618); @Reviewer **Approved** (итер.2, блокер F4-M1 закрыт); @Scanner **Critical 0 / High 0 / Medium 0 / Low 2 / Info 3 → «к деплою ДА»** (`plans/reports/round1025_f4_scanner_audit.md`); pytest **8229/0**, JS-маркеры `MODULE-STORE-OK`/`MODULE-CATALOG-OK`; `APP_VERSION` **2.58.9**; **Δ DDL=0, Δ каталога=0**. **✅ deploy — Шаг 9 @DevOps (VERIFIED: `7f9fed1`/`28eb02d`/`f0db773`, `APP_VERSION` 2.58.9, health 200, `database is locked`=0); ⏳ live-гейт владельца T-2656 (реальный TMA).** Техдолг **§60.10**: L-F4-1 (defensive re-read 409) / L-F4-6 (§73-гонка без обратной связи) / L-F4S-1 (`stickyFailedKeys`) / L-F4S-2 (`runtimeGate`/parent-gate follow-up) + Info (I-F4S-2 live TMA → T-2656). **Суть:** каталог §31–§45 + панель избранного + канонический `ModuleConfigurationStore` §37–§42 (одна мутация → все представления, `scope_type+scope_id+module_id`, scoped keys, **откат при ошибке §41**), reuse F3/F0 (scopeEpoch/`persistItems`). | §31–§45, §72, §73, §79, §116 | UI+state (web) | **P0** | F2, F3 | T-2619…T-2657 (39) |
| **F5** ✅ | `module-workspace-tabs-round1025` — **✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026); Merge `plans/ARCHITECTURE.md` §61; архив — `plans/archive/module-workspace-tabs-round1025/`.** `tasks.md` (блоки 0, A–H, 9; **T-2695…T-2744, 50**; дублей ID нет). @Reviewer **Approved** (итер.2; FIX-1…FIX-4 + блокер M-F5S-1 закрыты); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 2 → «к деплою ДА»** (`plans/reports/round1025_f5_scanner_audit.md`). pytest **8245 passed / 1 skipped / 5 failed** (5 — env `InputRichMessageMedia`, вне F5); F5 pytest **19 passed**; JS `MODULE-WORKSPACE-OK`/`PROMPTS-SINGLE-SOURCE-OK`/`MODELS-GROUPS-OK`; Playwright §71 **failures: 0**; `APP_VERSION` **2.58.10**; **Δ DDL=0, Δ каталога=0** (459/98/96/21/418; новых API/библиотек нет — reuse `/api/llm/test`,`/api/images/test`). **✅ deploy — Шаг 9 @DevOps (VERIFIED: `63dddd3`/`0d3ea40`/`af137cd`, `APP_VERSION` 2.58.10, health 200, `database is locked`=0); ⏳ live-гейт владельца T-2742 (реальный Telegram WebView).** Техдолг **§61.8** (L: дверь без таба + порядок полей; I-F5S-1 L1/L2 одна модель — по §84; I-F5S-2 Playwright/live не воспроизводились @Scanner; `README.md:5` «Тестов: 5936»). **Суть:** workspace §46 (маршрут + вкладки + тумблер из store F4), раздел ИИ §47 (5 страниц), гибридная библиотека промптов §48 (**один промпт — один источник**, две двери), §49 «Модели и подключения» (6 групп + карточка), §84 L1/L2 и §85 Саммари — **только UI-каркас** (backend-пайплайн — Эпик 2). | §46–§49, §84, §85 | UI+IA (web) | **P0** | F4 | T-2695…T-2744 (50) — `plans/archive/module-workspace-tabs-round1025/tasks.md` |
| **F6** | `memory-analytics-reorg` *(в ТЗ @Memory — `memory-access-reorg`)* — раздел «Память» §52–§59 + «Сводка»→«Аналитика» §21 + карта вызовов §22–§30 (adapter ExecutionGraph, 2 режима, mobile) — **✅ COMPLETED + MERGED + ARCHIVED (Шаг 1 @PM → Step 7 @Architect Merge → Шаг 8 @PM, 23.09.2026; Merge `plans/ARCHITECTURE.md` §65; архив — `plans/archive/memory-analytics-reorg-round1025/`; @Reviewer Approved итер.2, @Scanner C0/H0/M0/L2 (техдолг §65.10); deploy ✅ задеплоено 2.58.14 (Шаг 9 @DevOps, T-2916, `deployment.md` VERIFIED); live — ⏳ PENDING OWNER VERIFICATION (T-2917)).** HOTFIX10 (Волна 1.9, UPD4) — ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026; Merge §64; архив — `plans/archive/hotfix10-liquidglass-rollback-shell-geometry-round1025/`); deploy ✅ задеплоено 2.58.13 (Шаг 9 @DevOps); live ⏳ PENDING OWNER VERIFICATION. Prior closed: HOTFIX9 ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026; Merge §63; архив — `plans/archive/hotfix9-shell-liquidglass-darkaurora-round1025/`, задеплоено 2.58.12); HOTFIX8 ✅ (2.58.11); live T-2776/T-2830 ⏳. Step 0 @Memory ✅; Step 1 @PM ✅ (блоки 0, A–I; T-2870…T-2920, 51; трассируемость REQ→§ТЗ); Step 2 @Architect ✅ (`spec.md` + **ADR-1025-19** + **ADR-1025-19a** AMEND-1); Step 3 @Memory ✅; Step 4 @Builder ✅ (блоки A–H, `APP_VERSION` 2.58.14); Step 5 @Reviewer ✅ **Approved** (итер.2); Step 6 @Scanner ✅ **C0/H0/M0/L2** (`plans/reports/round1025_f6_scanner_audit.md`); Step 7 @Architect ✅ Merge §65; **Step 8 @PM ✅ архивация**; **Step 9 @DevOps ✅ deploy (2.58.14, VERIFIED)**; **Step 10 @Memory ✅ метрики/KG** (F6); **следующая — F8 `parameter-registry-widget-map-round1025`** (обязательный аудит §1–§3), затем F11/F9/F10. | §4, §21–§30, §52–§59, §75, §76 | UI+adapter (web+api) | **P0** | F1, F4 | **T-2870…T-2920 (51) — `plans/archive/memory-analytics-reorg-round1025/tasks.md` (48 [x] / 3 [ ] — открыты T-2917 live PENDING OWNER, T-2919/T-2920 продолжение F7/сверка; ✅ закрыты T-2916 deploy 2.58.14 и T-2918 метрики Шаг 10)** |
| **F7** ✅ | `permsoc-local-space` — локальное пространство §60–§67, мастер-тумблеры §61 (иерархия, сохранение дочерних, **серверная поддержка отключения**), блоки Славик/Костик/Оля/Мимикрия/Общие реакции/Расписания — **✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 23.09.2026; Merge `plans/ARCHITECTURE.md` §66; архив — `plans/archive/permsoc-local-space-round1025/` (`spec.md` + **ADR-1025-20** + `tasks.md` + `evidence.md` + `review.md`); @Reviewer **Approved** (итер.3); @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → «к деплою ДА»** (`plans/reports/round1025_f7_scanner_audit.md`); техдолг **§66.8** (L-F7S-1 / L-F7-4 / L-F7-6); **deploy ✅ задеплоено 2.58.15** (Шаг 9 @DevOps, T-2960, `6bf00e7`/`908f471`/`e2b452c`/`3bab70f`, `deployment.md` VERIFIED); **live ⏳ PENDING OWNER VERIFICATION** (T-2961)).** `tasks.md` — блоки 0, A–G, **T-2921…T-2963 (43)**; закрыты T-2921…T-2960 (deploy) + T-2962 (метрики/KG), открыты T-2961 (live) + T-2963 (продолжение → **F8**). **Следующая — F8** `parameter-registry-widget-map-round1025` (обязательный аудит §1–§3/§117). | §60–§67 | UI+backend | **P0** | F3 ✅, F4 ✅ | **T-2921…T-2963 (43) — `plans/archive/permsoc-local-space-round1025/tasks.md`** |
| **F8** ✅ | `parameter-registry-widget-map` — **✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026); Merge `plans/ARCHITECTURE.md` §67; deploy — NOT_APPLICABLE (обосновано, `deployment.md`); живой PG-снимок — ⏳ PENDING OWNER VERIFICATION (T-3021)** — обязательный аудит §2 + сохранность конфигурации §3 + результаты §117(1–4): реестр параметров, карта «старый экран→параметр→новый экран→API», карта виджетов, бэкап, diff до/после. Архив — `plans/archive/parameter-registry-widget-map-round1025/` (`spec.md` + **ADR-1025-21** + `tasks.md` + `evidence.md` + `review.md` + `deployment.md`). **`tasks.md` — блоки 0, A–I; T-2964…T-3023 (60)**; @Reviewer **Approved**; @Scanner **C0/H0/M0**; pytest **8403/0**; **Δ DDL=0, Δ каталога=0** (459/98/96/21/418); `APP_VERSION` **2.58.15** (без bump); открыто — T-3020 (метрики/KG, Шаг 10), T-3021 (живой PG-снимок). **▶️ Следующая — F9** `secrets-and-save-states-round1025`. | §1–§3, §117 | audit+data-safety (enabler) | **P0** | — (Wave 0) | **T-2964…T-3023 (60) — `plans/archive/parameter-registry-widget-map-round1025/tasks.md`** |
| **F9** ✅ | `secrets-and-save-states` — **✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026); Merge `plans/ARCHITECTURE.md` §68; архив — `plans/archive/secrets-and-save-states-round1025/` (`spec.md` + **ADR-1025-22** + `tasks.md` + `evidence.md` + `review.md`); deploy ⏳ Шаг 9 @DevOps (T-3058), live ⏳ PENDING OWNER VERIFICATION (T-3059); техдолг §68.8** — только **UI-слой секретов §50** (`{configured,last4}`, «Ключ установлен», маска ≠ значение input, отдельные замена/удаление) + **визуальная часть SaveBar §69/§78** (safe area, клавиатура, последнее поле); **persistence/409/412/state-machine/безопасный merge/версия — в F0 (Wave 0)**, не дублируются. @Reviewer **Approved** (итер.2); @Scanner **C0/H0/M0/L0/Info 2** → «к деплою ДА» (`plans/reports/round1025_f9_scanner_audit.md`). Числа: JS **40/40**, pytest **8421/0/1 skipped** (5 env вне scope), **Δ DDL=0**, **Δ каталога=0** (459/418/434/98/96/21; секреты 28), `APP_VERSION` **2.58.16**. Открыты — T-3058 (deploy ⏳ Шаг 9), T-3059 (live PENDING OWNER VERIFICATION), T-3060 (метрики, Шаг 10). **▶️ Следующая — F11** `status-showcase-dashboard-round1025`, затем **F10** `epic1-verification-round1025`. | §50, §51, §69, §78 | UI+API | **P0** | **F0 ✅**, F4 ✅, F5 ✅ | **T-3024…T-3062 (39) — `plans/archive/secrets-and-save-states-round1025/tasks.md`** |
| **F10** | `epic1-verification` — приёмка §71–§79/§116/§117: Playwright-матрица 10 размеров + низкое окно TG Desktop, тесты единого переключателя / независимости чатов / наследования / карты / мониторинга / сердцебиения / секретов (=критерии §6 F0 подтверждены), критерии завершения | §70–§79, §116, §117 | verification (gate) | **P0** | **F0**, F1…F9, F11 | детализация при старте |
| **F11** | `status-showcase-dashboard` — **[добавлено @PM, адаптация: §11–§20 не покрыты в F1–F10 по существу]** витрина «Статус» §11–§20: 12-кол. сетка §12, Hero §13, метрики §14, ~~живое сердцебиение §15 (Canvas 2D+rAF)~~ → **§15 SUPERSEDE/вынесено в `hotfix6-webview-shell-heartbeat-round1025` (Волна 1.5)**, граф §16, сон/бейджи §17, мониторинг интеллекта §18, «Новые факты» §19, логи §20 + превью карты §21 | §11–§21, §70, §77 | UI (web) | **P0** | F1, F2, F6 | детализация при старте |

**Порядок исполнения Эпика 1 (обновлён UPD: F0 — Wave 0 ДО F1; F11 перед F9):**
1. **Волна 0 (P0, обязательна ДО массового переноса настроек в новые компоненты):** **F0 ✅ ARCHIVED + DEPLOYED (COMPLETED+MERGED; багфиксы конфигурации §1–§6 + F0.5 «устойчивость к `database is locked`»); live-приёмка: T-2454 ✅, T-2419/T-2433 — ручные (владелец) — `plans/reports/round1025_f0_scanner_audit.md`** ∥ **F8** (бэкап + инвентарь §2, read-only enabler). **Точка отката — первая задача F0 (T-2410)**; в F1 она дублируется (T-2388). F0 не зависит от F8 по файлам, но оба стартуют первыми.
2. **Волна 0.5 (каркас):** **F1 ✅ ARCHIVED + DEPLOYED** (`fe0f7bb`; IA/shell; потребитель инвентаря F8 и контракта сохранения F0) + **P0-фикс после F1 ✅ ARCHIVED + DEPLOYED** (`fea2daa`, hotfix2: render/media/avatars/APP_VERSION/matrix) + hotfix3 (`cfe7342`) + hotfix4 (`f2328fb`). **Волна 1 далее — закрыта, см. п.3.**
3. **Волна 1 (✅ COMPLETED + MERGED + ARCHIVED, 22.09.2026):** **F2** (токены §8/glass A-B-C §9/фон §10; **T-2529…T-2562**) + **hotfix5** (окно/ретраи обложки, image-бюджет; **T-2563…T-2573**) + **F3** (селектор области §5; **T-2574…T-2580**) — пакет прошёл Шаг 7 Merge (`plans/ARCHITECTURE.md` **§57**) и Шаг 8 @PM (архивация в `plans/archive/`). Итоговый `APP_VERSION` **2.58.6**; @Scanner **C0/H0**. **✅ Шаг 9 @DevOps (деплой пакетом `4cde1bc`, `APP_VERSION` 2.58.6, health 200, `database is locked`=0) выполнен; ⏳ live-гейты владельца открыты.**
4. **Волна 1.5 (✅ COMPLETED + MERGED + ARCHIVED, Шаг 8 @PM, 22.09.2026; Merge §58):** **`hotfix6-webview-shell-heartbeat-round1025`** — **A** Liquid Glass (преломление без `backdrop-filter: url()` + стекло панелей), **B** нижняя панель mobile (`contentSafeAreaInset.bottom`), **C** сердцебиение §15 (overflow + Canvas 2D/rAF; **§15 вынесено из F11**), **D** шапка/⛶/отдельная строка/резерв высоты (T-2581…T-2618). Архив — `plans/archive/hotfix6-webview-shell-heartbeat-round1025/` (`spec.md` + ADR-1025-12 + `tasks.md`). **✅ deploy — Шаг 9 @DevOps (VERIFIED: `055525c`+`ba75751`, `APP_VERSION` 2.58.7); ⏳ live-гейт владельца T-2617.**
5. **Волна 1.6 (✅ COMPLETED + MERGED + ARCHIVED, Шаг 8 @PM, 22.09.2026; Merge §59; ВНЕПЛАНОВЫЙ ПРИОРИТЕТНЫЙ UPD, выше F4):** **HOTFIX7** `hotfix7-shell-glass-heartbeat-round1025` — layout+fullscreen, heartbeat premium, glass shell/liquid glass, shell-выравнивание, приёмка UPD 6, аудит ТЗ UPD 7 (T-2658…T-2694, 37). Архив — `plans/archive/hotfix7-shell-glass-heartbeat-round1025/` (`spec.md` + ADR-1025-13 + `tasks.md` + `evidence.md` + `review.md`); @Reviewer Approved, @Scanner **C0/H0/M0**. **✅ deploy — Шаг 9 @DevOps (VERIFIED: `7073e34`/`a9cec67`/`2a67829`, `APP_VERSION` 2.58.8); ⏳ live-гейт владельца T-2682.** Вставлен между hotfix6 и F4 по UPD «Срочный фикс текущего фронта» (`plans/current_task.md` 6073–6154). **F4 → ✅ возобновлена, ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026; Merge §60; `7f9fed1`/`28eb02d`/`f0db773`, live T-2656 ⏳).**
6. **Волна 2 (✅ COMPLETED + MERGED + ARCHIVED, Шаг 8 @PM, 22.09.2026; Merge §60):** **F4** `module-catalog-quickpanel-store-round1025` (каталог+store; **T-2619…T-2657, 39**) — `spec.md` + **ADR-1025-14** (Step 2 @Architect), build/rework, @Reviewer Approved, @Scanner **C0/H0/M0**, Merge §60. Архив — `plans/archive/module-catalog-quickpanel-store-round1025/`. **✅ deploy — Шаг 9 @DevOps (VERIFIED: `7f9fed1`/`28eb02d`/`f0db773`, `APP_VERSION` 2.58.9); ⏳ live-гейт владельца T-2656.** **Следующая — F5 `module-workspace-tabs-round1025`; отдельного решения владельца не требует.**
7. **Волна 3:** **F5** (workspace+промпты) ✅ → **F6** (Память+Аналитика) ✅ **COMPLETED + MERGED + ARCHIVED + DEPLOYED** (Шаги 8–9 @PM/@DevOps, 23.09.2026; Merge §65; deploy ✅ 2.58.14; live ⏳ PENDING) → **F7** `permsoc-local-space-round1025` ✅ **COMPLETED + MERGED + ARCHIVED + DEPLOYED** (Шаг 8 @PM + Шаг 9 @DevOps, 23.09.2026; Merge §66; архив — `plans/archive/permsoc-local-space-round1025/`; deploy ✅ задеплоено 2.58.15 (`deployment.md` VERIFIED); live ⏳ PENDING OWNER VERIFICATION) → **F8** `parameter-registry-widget-map-round1025` ✅ **COMPLETED + MERGED + ARCHIVED** (Шаг 8 @PM, 23.09.2026; Merge §67; архив — `plans/archive/parameter-registry-widget-map-round1025/`; deploy — **NOT_APPLICABLE**; живой PG-снимок ⏳ PENDING OWNER VERIFICATION) → **F9** `secrets-and-save-states-round1025` ✅ **COMPLETED + MERGED + ARCHIVED** (Шаг 8 @PM, 23.09.2026; Merge §68; архив — `plans/archive/secrets-and-save-states-round1025/`; @Scanner C0/H0/M0/L0/Info 2; deploy ⏳ Шаг 9 @DevOps, live ⏳ PENDING OWNER VERIFICATION) → **▶️ следующая F11** `status-showcase-dashboard-round1025` (Статус-витрина, после F2+F6; **без §15** — сердцебиение в hotfix6) → **F10** `epic1-verification-round1025`.
8. **Волна 4:** **F9** ✅ **COMPLETED + MERGED + ARCHIVED** (Шаг 8 @PM, 23.09.2026; Merge §68; только секреты §50 + визуальный SaveBar; серверный persistence/409/state-machine — в F0) — deploy ⏳ Шаг 9 @DevOps, live ⏳ PENDING OWNER VERIFICATION.
9. **Волна 5:** **F10** (приёмка §71–§79) — после всех; затем **СТОП-ГЕЙТ Эпика 1** (приёмка владельцем) → старт Эпика 2.

> **Порядок фич (единый, по UPD):** **F0 → F1 → F2 → F3 → hotfix6 (Волна 1.5) → HOTFIX7 (Волна 1.6, приоритетный UPD) → F4 → F5 → HOTFIX8 (Волна 1.7) → HOTFIX9 (Волна 1.8, приоритетный UPD3) → **HOTFIX10 (Волна 1.9, приоритетный UPD4)** → F6 ✅ (Merge §65, Шаг 8 @PM 23.09.2026; deploy ✅ Шаг 9 @DevOps, 2.58.14) → **F7** ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 23.09.2026; Merge §66; архив — `plans/archive/permsoc-local-space-round1025/`; deploy ✅ задеплоено 2.58.15 (`deployment.md` VERIFIED); live ⏳ PENDING OWNER) → **F8** ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026; Merge §67; deploy **NOT_APPLICABLE**; живой PG-снимок ⏳ PENDING OWNER VERIFICATION) → **F9** `secrets-and-save-states-round1025` ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 23.09.2026; Merge §68; архив — `plans/archive/secrets-and-save-states-round1025/`; deploy ⏳ Шаг 9, live ⏳ PENDING OWNER VERIFICATION) → **▶️ следующая F11** `status-showcase-dashboard-round1025` → **F10** `epic1-verification-round1025`**. Изменение относительно исходной декомпозиции: F0 добавлена в начало (Wave 0), F11 передвинута **перед** F9 (обе после F4/F5/F6/F7), F9 сужена; **hotfix6** вставлен между F3 и F4 по итогам живой приёмки владельца (блоки A–D), **§15 вынесено из F11 в hotfix6**; **HOTFIX7** вставлен между hotfix6 и F4 по новому приоритетному UPD «Срочный фикс текущего фронта» (§6073–6154), **F4 — ✅ ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026; Merge §60; 2.58.9; live T-2656 ⏳); HOTFIX9 — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026; Merge §63; 2.58.12; live T-2830 ⏳ PENDING OWNER VERIFICATION); HOTFIX10 — ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаги 8–9 @PM/@DevOps, 23.09.2026; Merge §64; задеплоено 2.58.13; live T-2862 ⏳ PENDING OWNER VERIFICATION).**
>
> **▶️ Текущий шаг (Шаг 8 @PM — архивация F9, 23.09.2026; deploy ⏳ Шаг 9; метрики ⏳ Шаг 10):** **F9 `secrets-and-save-states-round1025` (Эпик 1, §50 + визуальный SaveBar §69/§78) — ✅ COMPLETED + MERGED + ARCHIVED** (Merge `plans/ARCHITECTURE.md` **§68**; архив — `plans/archive/secrets-and-save-states-round1025/` (`spec.md` + **ADR-1025-22** + `tasks.md` + `evidence.md` + `review.md`); **T-3024…T-3062, 39**; @Reviewer **Approved** итер.2, @Scanner **C0/H0/M0/L0/Info 2** → «к деплою ДА»; техдолг **§68.8**; JS **40/40**, pytest **8421/0/1 skipped** (5 env вне scope), **Δ DDL=0**, **Δ каталога=0**, `APP_VERSION` **2.58.16**; открыты **T-3058** (deploy — ⏳ Шаг 9 @DevOps), **T-3059** (live-гейт реального TMA/WebView — ⏳ PENDING OWNER VERIFICATION), **T-3060** (метрики/KG — Шаг 10 @Memory)). **Следующий шаг — F11 `status-showcase-dashboard-round1025`** (Статус-витрина §11–§21; зависит от F1/F2/F6), затем **F10** `epic1-verification-round1025` (приёмка Эпика 1). **Ранее закрыт и задеплоен HOTFIX10** (Merge §64; архив — `plans/archive/hotfix10-liquidglass-rollback-shell-geometry-round1025/`; T-2840…T-2869, 30; задеплоено 2.58.13, live T-2862 ⏳). Ранее закрыт и задеплоен **HOTFIX9** (Merge **§63**; deploy Шаг 9 @DevOps **VERIFIED** — `470b63a`/`8d61926`/`dba76e8`, `APP_VERSION` 2.58.11 → **2.58.12**, health 200, `database is locked`=0; @Reviewer Approved, @Scanner C0/H0/M0/L0/I3; pytest 8291/0). Живые гейты владельца (в т.ч. **T-2830** HOTFIX9 PENDING OWNER VERIFICATION, **T-2776**, **T-2742**, **T-2682**, **T-2617**, **T-2656**) закрываются параллельно и не блокируют старт (UPD4 §8 «без human gate»).

**Зависимости Эпика 1:** **F0 → F1** (контракт сохранения / единая state-machine); F1 → (F3, F4, F6, F11); F2 → (F4, F11); F3 → (F4, F7); F4 → (F5, F6, F7, **F9**); F5 → F9; F6 → F11; **все** → F10. F8 — Wave 0 (читается F1). **F0 ↔ F9:** F0 владеет persistence/409/state-machine; F9 — потребитель (UI-секреты + визуальный SaveBar), серверную логику не дублирует.
**Ступени общих файлов:** `services/param_catalog.py` — **F1 (nav-метаданные) → F8 (реестр) → F4/F5/F7**; `web/app.js`/`web/index.html`/`web/static/app.css` — **F0 → F1 → F2 → F3 → hotfix6 → HOTFIX7 → F4 → F5 → HOTFIX8 → HOTFIX9 → HOTFIX10 → F6 → F7 → F11 → F9 → F10** (строго сериализовано, без одновременного редактирования); `web/api/*` — **F0 (save/state-machine) →** F6 (analytics adapter) / F3 (scope) / F9 (секреты), по изоляции эндпоинтов.

**F0 ✅ ARCHIVED + DEPLOYED — детально (Wave 0, выполнялась ДО F1; ✅ COMPLETED+MERGED+DEPLOYED, Шаги 8–9 @PM/@DevOps, 20.09.2026; источник — UPD §1–§6 + «КРИТИЧЕСКОЕ ОБНОВЛЕНИЕ» (стр. 5920–6024); `tasks.md`: `plans/archive/f0-config-bugfixes-round1025/`, T-2410…T-2455; F0.1–F0.4 = T-2410…T-2441, F0.5 = T-2442…T-2455; ✅ live-приёмка: T-2454 подтверждён, T-2419/T-2433 — ручные (владелец)):**
- **F0.1 — конфликт версий 409 (§2):** наблюдаемое — одна операция даёт три противоречивых результата («Сохранено» + «Конфликт версии (409)» + «Не сохранено (1)»). Первопричина (по @Memory): **конкурентные мутации одного ключа `prompts.verbilizer_default_mode`** — `saveConfigItem` (автосейв дропдауна Fallback) + `saveModalEdits` (sticky-SaveBar/`dirtyItems`) + `saveBlock` одновременно; **нет сериализации и единой state-machine**; глобальный путь — **без optimistic-проверки**; текст 409 вводит в заблуждение; не считать заранее доказанным ни один вариант (§2). Требуется: сериализация мутаций по ключу, единый версионный контракт (`revision` ≠ `updated_at` — см. предупреждение выше), обработка 409 по §2.3 (не показывать успех; сохранить черновик; re-read сервера; compare; если значения совпали — признать выполненным; иначе показать реальные конфликтующие поля; **без бесконечных retry**), единое состояние формы §2.4 с частичным успехом (отдельно сохранённые/несохранённые; после ошибки введённые значения не теряются).
- **F0.2 — аудит всех механизмов сохранения (§3):** для каждого механизма (тумблеры модулей, системные промпты, промпты Синтезаторов/Вербализаторов, модели, провайдеры, резервные подключения, API-ключи, числовые лимиты, память, анти-клише, PERMsoc, глобальные/локальные override) прогнать цикл **load → edit → save → re-read → compare**; HTTP 200 — не доказательство; спец-кейсы (несколько полей, быстрое двойное нажатие, переключение чата во время запроса, две админ-сессии, сохранение рядом с полем API-ключа, частичные ошибки, устаревшие ответы); не создавать копию конфигурации на каждый визуальный экземпляр; изоляция scope (чат A ≠ чат B).
- **F0.3 — анти-клише (§4):** потолок 20 уже снят (10.24 F7), но обновление оставляет 20 и показывает «Ошибка модели». Вероятные причины: **stale-кэш при fail-safe** + UI показывает `last_status='llm_error'`; **per-chat trap — воркер читает только global**; события `ANTI_CLICHE_*` отсутствуют. Требуется: найти реальный ключ/сохранённое значение/что читает воркер/override/устаревший кэш/старые дефолты; разделить семантику «максимум паттернов в базе» vs «паттернов за обновление» (§4.3); пакетное пополнение с ограничением попыток/расходов без генерации мусора; честный статус («0 новых» ≠ ошибка модели); события `ANTI_CLICHE_UPDATE_START/MODEL_REQUEST/MODEL_RESPONSE/PARSE_ERROR/DEDUP_COMPLETE/SAVE_COMPLETE/UPDATE_COMPLETE/UPDATE_FAILED` с полями (заданный/применённый лимит, исходное количество, кандидаты, дубликаты, сохранено, итог, модель, длительность, причина).
- **F0.4 — уведомления и SaveBar (§5):** одно итоговое уведомление на операцию; без противоречивых результатов; Telegram safe area; не перекрывать селектор области; ограничить число одновременных тостов; не создавать тост на каждое поле при батч-сохранении; ошибки полей — возле полей; длинная ошибка — действие «Подробнее»; без stack trace огромным тостом. Визуальная часть SaveBar координируется с F9 (без дублей).
- **🆕 F0.5 — устойчивость к `database is locked` (расширение ADR-1024-18; T-2442…T-2455):** прод-логи 20.09.2026 (~08:52–08:53 UTC, chat_id `-1002661910336`) — 6 стеков `sqlite3.OperationalError: database is locked` с WARNING+fail-open/фоллбэком: `summary_memory.memorize_self_reply`→`database.insert_graph_fact`, `direct_chat_service.remember_bot_reply`→`database.upsert_bot_reply`, `summary_memory._knn_graph_facts`→`database.touch_graph_facts`, `summary_memory._embed_cache_store`, `persistent_throttling.reset`, `persistent_throttling.allow`. Класс дефекта уже частично закрыт в 10.24 (`sqlite-lock-resilience-round1024` / **ADR-1024-18** / T-2322…T-2327), но **только для `smart_cache`**. Требуется: диагностика соединений/путей и первопричины (`database.py` уже ставит WAL/`busy_timeout=5000`/`synchronous=NORMAL`, но **не имеет bounded retry**; многошаговые транзакции на общем соединении + интерливинг корутин + конкуренция воркеров снижают эффект `busy_timeout`); PRAGMA-паритет на все затронутые соединения; **bounded retry только на `locked`** с backoff (`_LOCK_RETRIES=3`, 0.1/0.2/0.4с, rollback перед повтором); **запрет тихой потери** (fail-open — только последний рубеж, обязательный структурированный `event=*_lock_exhausted` + счётчик); сериализация многошаговых транзакций (single-writer); легализовать/устранить `self.db.db.execute`; не ронять хендлеры; kill-switch `DB_LOCK_RESILIENCE_ENABLED` (env-only, default ON); regression-тесты (PRAGMA на файловой БД; имитация `locked`→retry успешен; исчерпание→явный WARNING не no-op; non-lock не ретраится; OFF=baseline); live-приёмка (в логах больше нет `database is locked` от этих сервисов). **Инвариант Δ DDL = 0**; `smart_cache` **не дублируется**.
- **Критерии приёмки F0 (§6, 10 пунктов):** 1) установлена причина 409; 2) Fallback сохраняется корректно; 3) проверены остальные механизмы сохранения; 4) локальные настройки не смешиваются с глобальными; 5) проверены сохранение промптов/моделей/секретов; 6) установлена причина ограничения анти-клише; 7) значение 200 применяется по определённой семантике; 8) исправлены противоречивые уведомления; 9) добавлены **regression-тесты**; 10) подтверждена сохранность существующих значений конфигурации. **Пока F0 не завершён — не переносить неисправный механизм сохранения в новые компоненты.**
- **Ступень/отчёт:** `web/app.js`/`web/index.html`/`web/api/*` — **F0 первым** (до F1); F9 читает результат, блоки F0 не переписывает; @Architect — `spec.md`/ADR по необходимости (Step 2); результаты §54 (причина 409, фикс, аудит, причина анти-клише, фикс, regression-тесты).

**Активация/флаги Эпика 1:** env-only kill-switch `ClassVar` (вне `param_catalog`, **default ON**) `IA_V2_ENABLED` (shell/IA) + UI-флаги фич по паттерну **ADR-1024-13** (`GET /api/me.ui_flags`, только bool); OFF → прежнее поведение байт-в-байт; откат — флаг OFF / `git revert` + cache-bust (`APP_VERSION`). **Δ DDL = 0**; **Δ каталога (ParamSpec/GROUPS) = 0** у F1 (только nav-метаданные). Поэтапная раскатка internal→10%→50%→100% **не требуется** (пет-проект, §0) — флаги дают kill-switch. **F0.1–F0.4 — без флагов** (багфикс; откат — `git revert` + точка отката **T-2410**). **Исключение F0.5:** env-only `ClassVar` kill-switch **`DB_LOCK_RESILIENCE_ENABLED`** (default **ON**, вне `param_catalog` → Δ каталога = 0, по образцу `SMART_CACHE_LOCK_RESILIENCE_ENABLED` из ADR-1024-18); OFF → baseline-поведение, откат без `git revert`.

**Гейты Эпика 1:** **Step 2 @Architect** (`spec.md` + ADR + **AMEND/RE-OPEN**-карта: ADR-1020-9 палитра, 10.24-F6, ADR-1013-3 канон промптов, ADR-1024-13 доставка флагов; **F0 — `spec.md`/diagnose-ADR при необходимости**; **F0.5 — AMEND/расширение `ADR-1024-18`**) → @Builder → @Reviewer → **Step 6 @Scanner** → **Step 9 @DevOps** (деплой; **F0: live-приёмка Fallback 409 + анти-клише 200 + уведомления на mobile + отсутствие `database is locked` от `summary_memory`/`direct_chat_service`/`persistent_throttling`**) → **Step 8 @PM** (архивация). **`spec.md`/ADR PM не создаёт.** **✅ Для F0 гейт пройден:** деплой `3a91c84` (push origin/master, `da561bc..3a91c84`, health 200); **T-2454** ✅ подтверждён (0 `database is locked` после рестарта); **T-2433**/ **T-2419** — ручные (владелец; кэш `20/200`, Fallback/409 в TMA).

### 🗺️ ЭПИК 2 (Раунд 10.26) — «Summary Hybrid Pipeline» — 10 фич (S1–S10; старт только после приёмки Эпика 1)

Пайплайн §80: шестичасовой лог → **алгоритмический фильтр** → **восстановление контекста** → **L1 Кластеризатор** → **пакет фактов** → **L2 Писатель** → **форматирование** → **существующий `generate_image`** → **существующий `sendRichMessage`**; при отсутствии обложки — **существующий `sendMessage`**.

| # | Фича (папка `plans/features/…-round1026/`) | ТЗ | Тип | Приоритет | Зависит от | Задачи |
|---|---|---|---|---|---|---|
| **S1** | `summary-filter` — алгоритмический фильтр §87–§89 + вес-алгоритм §88 + тонкая настройка §89 + лимит/чанки §93, namespace `summary.filter.*` (§87), дефолт **ВКЛ** | §80, §87–§89, §93 | backend/алгоритм | **P0** | Эпик 1 | Step 1 при старте Эпика 2 |
| **S2** | `summary-context-restore` — восстановление контекста §90 + спец-случаи §91 + подготовка данных §92 (reply_to-родители, ограниченный соседний контекст, хронология, дубли, исходные `message_id`) | §90–§92 | backend/алгоритм | **P0** | S1 | Step 1 при старте Эпика 2 |
| **S3** | `summary-l1-clusterizer` — L1 Кластеризатор §94–§95 (Conversation Disentanglement; **L1 не пишет Саммари**; строгий JSON-контракт; валидация `message_id`/`evidence_message_ids`; невалидный JSON не передаётся в L2) | §81, §94, §95 | backend/LLM+канон | **P0** | S1, S2 | Step 1 при старте Эпика 2 |
| **S4** | `summary-fact-package` — пакет фактов §96 (название/описание/хронология/факты/подтверждающие ID/фрагменты; без повторного сырого лога; не генерировать «доказательства» самостоятельно) | §96 | backend/сборка | **P0** | S3 | Step 1 при старте Эпика 2 |
| **S5** | `summary-l2-writer-formatter` — L2 Писатель §97–§99 (структура статьи §98, структурированный вывод §99, серверный форматтер → Rich Message; H1 §101, абзацы/акценты §102, экранирование) | §97–§99, §101, §102 | backend/LLM+формат | **P0** | S4 | Step 1 при старте Эпика 2 |
| **S6** | `summary-publish-integration` — публикация §100–§106: reuse `sendRichMessage` (§100) + настоящий H1, **`generate_image` НЕ трогать** (§104), fallback `sendMessage` (§105), коды ошибок §106, сверка документации Telegram §103 | §100–§106, §103 | backend/публикация | **P0** | S5 | Step 1 при старте Эпика 2 |
| **S7** | `summary-logging-runid` — `run_id` + события §108, детали логов §109, фильтр в log viewer §110 (без ключей) | §108–§110 | backend/лог+UI | **P0** | S6 | Step 1 при старте Эпика 2 |
| **S8** | `summary-analytics-adapter` — §111 adapter ExecutionGraph + узлы Filter/Clusterizer/Writer/Formatting/Publication (kind: algorithm/llm/format/publish; **GraphViewer не переписывать**), метрики §112 | §30, §111, §112 | web+api adapter | **P0** | S6, F6 | Step 1 при старте Эпика 2 |
| **S9** | `summary-testing-ui` — тестирование из Mini App §113 (чат/окно/«Проверить пайплайн», **без публикации**, без изменений памяти, без `generate_image` без подтверждения) | §113 | UI+api | **P0** | S5, S6 | Step 1 при старте Эпика 2 |
| **S10** | `summary-deploy` — прямой деплой §107 + проверка §114 + первый рабочий запуск §115 + результаты §117 | §107, §114, §115, §117 | deploy/ops (gate) | **P0** | S1…S9 | Step 1 при старте Эпика 2 |

**Инварианты Эпика 2 (жёстко):**
- **`generate_image` НЕ переписывать** (§104) — модель, провайдер, ключи, промпт обложки, параметры изображения, обработка ошибок, порядок публикации, механизм прикрепления — сохранить.
- **`sendRichMessage` переиспользовать** (§100) — не внедрять новый механизм Rich Message; улучшать форматирование текста; обложка сверху, H1 после изображения.
- **Fallback — существующий `sendMessage`** (§105): H1 → жирный, абзацы/акценты, разбиение по границам абзацев, текст не теряется.
- **Промпты — новый канон + `PREV_*`-слепок + идемпотентная миграция (ADR-1013-3)** — код + эталон `plans/docs/canon/**` + слепки + тесты одним коммитом; обратный путь документирован; «один промпт — один источник».
- **L1/L2 — раздельные модели/провайдеры/промпты** (§81/§82) — до 4 слотов; «не выбрано» → глобальная основная модель (наследование ≠ аварийное резервирование).
- **Одна визуализация** — новые узлы через существующий ExecutionGraph (§111); вторую систему аналитики не создавать.
- **Прямой деплой** (§107): без теневого режима/поэтапного rollout/переключателя Legacy; фильтр и раздельный роутинг включены сразу после деплоя; перед деплоем — минимальные функциональные тесты (§114).

**Порядок Эпика 2:** `S1 → S2 → S3 → S4 → S5 → [S6 ∥ S9 (после S5)] → S7 → S8 → S10`. Канон-цепочка **S3 → S4 → S5 → S6** атомарна (ADR-1013-3). **Δ DDL / новые параметры `summary.filter.*` и слоты моделей** — санкционировать в `spec.md` (параллельное хранилище §87 запрещено). **СТОП-ГЕЙТ:** старт Эпика 2 — только после приёмки Эпика 1 (§0/§79).

### 🗺️ ЭПИК 3 (Раунд 10.26+ / 10.27; старт только после приёмки Эпиков 1 и 2) — «Agentic Intelligence» — 11 фич (A0–A10; верхнеуровнево, детализация — Step 1 @PM при старте Эпика 3)

**Триггер:** UPD §11–§54 (`plans/current_task.md`, строки 4321–5918). После Эпиков 1–2 расширить интеллектуальное поведение бота: **единый координатор инструментов** (не новый агент — расширение существующего Синтезатора), **последовательные tool calls**, **единый Image Request** (direct|tool), **генерация из досье/RAG**, **дневной лимит изображений** (atomic reserve + idempotency), **structured memory lookup** `get_user_context(purpose)`, **новый Decision Making** (`action` {reply/react/silent/tool} отдельно от `style`), **реакции Telegram**, **события / ExecutionGraph / Mini App**. **Инварианты:** не создавать новых агентов/фреймворков; использовать существующие **10 инструментов** (`services/tool_schemas.py`), `tool_loop` (`TOOL_MAX_ROUNDS=4`), image-пути (`generate_and_send`), досье+RAG, `response_mode`; **вторую систему аналитики не создавать**; `action` **не добавляет третий LLM-вызов** (AMEND `physical-two-call-pipeline`); сохранность существующих функций обязательна (§53).

| # | Фича (папка при старте `plans/features/…-round1026/`+, имена условные) | ТЗ | Тип | Приоритет | Зависит от |
|---|---|---|---|---|---|
| **A0** | `agentic-audit` — обязательный read-only архитектурный аудит §12: карта всех инструментов (название/назначение/аргументы/результат/ошибки/доступность/зависимости/возможность последовательного вызова), схема JSON L1↔L2, исследование отказа tool calling генерации изображений, досье/RAG, фактчек, извлечение Markdown из URL, Decision Making, реакции, тумблеры/лимиты. **Enabler (Wave 0 Эпика 3)** | §12, §54 п.1 | audit (read-only) | **P0** | Эпики 1–2 |
| **A1** | `tool-coordinator` — единый координатор инструментов: Синтезатор расширяется (намерение / адресат / необходимость памяти / выбор инструментов / оценка результатов / выбор действия); Вербализатор — только текст по подготовленным фактам; **общий** механизм цепочек, не отдельный обработчик на каждую комбинацию | §13, §14 | backend/LLM-оркестрация | **P0** | A0 |
| **A2** | `sequential-tool-calls` — последовательные зависимые вызовы (A→B; зависимые не параллелить), структурированные контракты результатов/ошибок (данные, не инструкции), ограничения: max вызовов, общий тайм-аут, лимит повторных попыток, защита от повторного одинакового вызова, ограничение расходов, частичный результат | §15–§17, §36, §37 | backend/tool-loop | **P0** | A1 |
| **A3** | `unified-image-request` — единое представление `ImageRequest` (source direct/tool, chat_id, requester_id, original_message_id, user_request, resolved_subjects, context_required/context_sources, final_prompt, generator_config); устранение двойной генерации; фикс tool calling изображений; оба пути → существующий генератор | §18–§21, §25 | backend/tool+image | **P0** | A1, A2 |
| **A4** | `image-context-memory` — генерация из досье/RAG: разрешение имён/алиасов (chat_id/user_id/alias/username/real_name/контекст; при неоднозначности — уточнение/отказ от персонализации), сборка промпта из независимых частей, безопасность (данные ≠ инструкции; арт ≠ достоверный портрет; не придумывать черты лица) | §22–§25, §32–§34, §37 | backend/memory+LLM | **P0** | A3, A6 |
| **A5** | `image-daily-limit` — дневной лимит генерации: **atomic reserve** квоты + **idempotency key** (повторный update не списывает дважды), scope global/chat с наследованием (не смешивать «глобальный дефолт» и «общую квоту всех чатов»), календарный день в TZ чата + время сброса, семантика учёта §28, отдельный учёт запросов/успехов/ошибок; UI «Модули → Генерация изображений → Лимиты» с «Использовано сегодня: N/M», источником и временем сброса | §26–§31, §50 | backend+DDL+UI | **P0** | A3 |
| **A6** | `memory-lookup-api` — structured memory lookup `get_user_context(user_id, chat_id, purpose, max_items)`; purpose: identity/appearance/speech_style/biography/relationships/general; поверх существующих досье+RAG (`dig_into_lore`), **новую базу памяти не создавать**; результат: факты + источники + подтверждённость + временной контекст + признак отсутствия данных; полные досье в каждый запрос не подмешивать | §32–§35 | backend/memory tool | **P0** | A0 |
| **A7** | `decision-making` — расширение существующего механизма: `action` {reply/react/silent/tool} **отдельно** от `style` {casual/serious/deep_research} (не `style=silent`; Вербализатор не генерирует пустой текст); контракт решения (action/target_message_id/tools/style/reason_code); правила когда отвечать/реагировать/молчать с учётом треда/reply_to/предыдущего действия бота; `silent` не запускает L2; контекст предыдущих действий (изображение/статья/вопрос/ожидание инструмента); настройки §48; **без третьего LLM-вызова** (AMEND `physical-two-call-pipeline`) | §38–§40, §42–§48 | backend/LLM+UI | **P0** | A1, A2 |
| **A8** | `telegram-reactions` — `setMessageReaction` (официальный Bot API): проверка доступности реакции в чате, разрешённая альтернатива/отказ, реакция на **правильное** сообщение (не путать reply_to_id/message_id/ID прошлого сообщения бота); не превращать ошибку реакции в длинный текст; существующий `react_moai` (🗿) — база | §41, §44 | backend/Telegram API | **P0** | A7 |
| **A9** | `agentic-events-graph` — события `DECISION_START/COMPLETE`, `TOOL_PLAN_CREATED`, `TOOL_CALL_START/COMPLETE/FAILED`, `REACTION_SENT`, `MESSAGE_IGNORED`, `IMAGE_CONTEXT_RESOLVED`, `IMAGE_GENERATION_START/COMPLETE/FAILED` (+ `ANTI_CLICHE_*` из F0.3) с полями run_id/chat_id/message_id/action/инструменты/причина/длительность/ошибки; **интеграция в существующий ExecutionGraph** (узлы Decision / Memory Lookup / RAG / Web Extraction / Factcheck / Image Prompt Preparation / Image Generation / Reaction / Text Generation; `silent` — без фиктивного Вербализатора) + Mini App §50; приватное содержимое досье в публичные логи **не** выводить | §49, §51 | backend/лог+web adapter | P1 | A1–A8 |
| **A10** | `agentic-verification` — 22 сценария §52 + критерии приёмки §53 + результаты §54 (12 пунктов): tool calling изображений, совместимость direct/tool, досье, лимит только на сервере, параллельные запросы, цепочки, отказ инструмента, невалидные аргументы, превышение лимита вызовов, молчание/реакция, недоступная реакция, глобальные/локальные настройки, отсутствие двойной генерации; карта инструментов, архитектура координатора, контракты, схема вызовов, схема Image Request, досье/RAG, схема лимитов, JSON Schema решения, логи цепочек, сохранность старых функций | §52–§54 | verification (gate) | **P0** | A0–A9 |

**Порядок Эпика 3 (предварительный):** **A0 (аудит) → A1 → A2 → [A3 → A5] ∥ A6 → A4 → A7 → A8 → A9 → A10**. Канон-атомарность при правке промптов — ADR-1013-3. **Δ DDL** (дневной лимит изображений: резерв/учёт + idempotency) — санкционировать в `spec.md`. **СТОП-ГЕЙТ:** старт Эпика 3 — только после приёмки Эпиков 1 и 2 (§0/§10); исследование A0 допустимо заранее, но не блокирует предыдущие эпики.

**AMEND/RE-OPEN Эпика 3 (Step 2 @Architect):** `physical-two-call-pipeline` (action-решение — **не** третий LLM-вызов; §13); ExecutionGraph — REUSE (A9; при необходимости AMEND модели F6/S8); `services/tool_schemas.py` — AMEND канона инструментов ADR-1020-4 (расширение контрактов **без потери** 10 существующих); `response_mode`/STYLE — AMEND ADR-1023-3 (разделение action/style); остатки `tma-menu-freeze` и `IA_V2_ENABLED` — только как временный откат (F1).

**Ссылки:** анализ Шага 0 — @Memory (`plans/MEMORY.md`, KG); UPD — `plans/current_task.md` (строки 3718–5918; **untracked, не коммитить**, секреты не цитировать — R17/R18); свежие замечания — `plans/reports/round1024_scanner_audit.md`, `plans/reports/round1023_scanner_audit.md`, `plans/reports/round1024_*_reviewer.md`, `plans/archive/round1024-web-architecture.md`, `plans/archive/round1024-architecture.md`.

## Раунд 10.24 (19–20.09.2026): «Disaster Recovery: UI & Backend Bloat» — 24 фичи — ✅ COMPLETED + DEPLOYED + ARCHIVED (@Reviewer Approved · @Scanner 0 Critical / 0 High / 0 Medium · @PM Step 8 архивация · @Architect Merge **§51** · feature-HEAD **`cf98b99`** + docs/прод-HEAD **`da561bc`**) (история планирования Step 1 @PM: + **UPD3 applied** + **UPD4 applied** + **UPD5 applied** + **UPD5-critical applied** (бюджеты F20–F23, `current_task.md` строка 404) + **UPD6 applied** (новый UI-баг F24 — «Провайдеры»/fullscreen, `plans/features/providers-fullscreen-advanced-fix-round1024/`); **все 9 Human Gate ЗАКРЫТЫ**; из UPD4-вопросов **№1/№2/№3/№5/№7 закрыты владельцем (UPD5)**, открыты **№4 и №6**; **открытые вопросы G №1–№6 (UPD5-critical, бюджетный кластер) — ждут владельца**; **новые открытые вопросы O №1–№4 (UPD6, fullscreen/аккордеон) — ждут владельца**; Step 2 @Architect — AMEND/RE-OPEN ADR, **канон инструментов AMEND (ADR-1020-4: 9→10)** + **AMEND решения 10.10 (JS/fullscreen → реализовано ADR-1024-24)**; **все Gate-вопросы G/O закрыты и реализованы — см. ✅ ИТОГ ниже**)

**✅ ИТОГ 10.24 (20.09.2026):** эпик **COMPLETED + DEPLOYED + ARCHIVED** (Step 8 @PM + Step 9 @DevOps + Step 10 @Memory). Baseline HEAD **`00eab85`** → код-раунд **`379cfdd`** → feature-HEAD **`cf98b99`** (F23-review-iter1 fix) → docs/прод-HEAD **`da561bc`**. `git diff 00eab85..379cfdd` = **132 файла, +18 264 / −1 016**. **Деплой:** push `00eab85..da561bc`; прод `/var/www/admin_bot` → **`da561bc`**; `systemctl` active; `/api/health` + `/healthz` = 200 (`version=2.58.0`); aiogram 3.31.0; PG 19 таблиц; SQLite `v12` (Δ DDL=0). **Ремонт бюджета чата `-1002661910336`:** `audit-chat-overrides` → `ok=8/absent=0/different=0` (`--strict` exit=1 — исторические вайпы, техдолг). **Диск:** `cleanup --apply` удалил 3× `memory_rebuild_*.db` = 2.2 GiB, `used 17G→15G`, `avail 5.8G→8.0G`, `backups 3.0 GiB→788.6 MiB`.
Реализовано **24 фичи (F1–F24) / 24 ADR (ADR-1024-1…-24: 23 файла + ADR-1024-13 сквозной без файла; F23 — без ADR) / задачи T-2188…T-2387 (200)**; отменены владельцем **T-2191/T-2192** (embeddings, UPD3 №7 — код `embed` не трогается).
@Reviewer — **Approved** по фичам, суммарно **~45 прогонов** (по 2 итерации у большинства; **3** — F5/F11/F19; **1** — F13/F17/F18/F20; **F15** `video-download-native-ux` — UX-часть реализована в составе F14/F16, отдельного коммита/ревью-отчёта нет; **F23** — итерация 1 **Changes Requested** (`379cfdd`) → исправлено `cf98b99`, **финально подтверждено @Reviewer**). @Builder — **~22 цикла доработок**.
@Scanner (независимый сквозной аудит, `plans/reports/round1024_scanner_audit.md`) — **0 Critical / 0 High / 0 Medium**; открыто **3 Low + 5 Info** (техдолг ниже). Полный **pytest — 7911 passed / 0 failed** (+487 к базе 7424; 1 сторонний `StarletteDeprecationWarning`); 8 новых JS-гейтов `tests/js/round1024_*` зелёные; `git diff --check` exit 0.
**Геометрия:** каталог **REGISTRY 457 → 459** (Δ+2), **Settings 416 → 418** (Δ+2), **GROUPS 96 → 98** (Δ+2), categorized 432 → 434, **`_TAB_BY_GROUP` 94 → 96**, **`TAB_RULES` = `TAB_NAV` = `CONFIG_TAB_TITLES` 20 → 21** (F5: +`mod_images`); витрина JS **MODULES 12 → 13**, **TABS 25 → 26**; **SQLite `v12` (Δ DDL = 0)**; **PG Δ DDL = 0**; `DDL_STATEMENTS` = **45**; **APP_VERSION 2.57.0 → 2.58.0**; **канон инструментов R9 9 → 10** (`transcribe_video`). Порядок роутеров `bot.py` не сдвинут (DI-kwarg `transcriber=voice_service`); `.env`/`media/` не тронуты. Архитектура — `plans/ARCHITECTURE.md` **§51** (@Architect Merge; + §50 — F16). **Закрыто раундом:** техдолг 10.23 **I2** (устаревший счётчик инструментов), **S10.19-24** (Won't Fix — история неприкосновенна), ложное закрытие 10.22 F2 (алиасы — RE-OPEN + live-доказательство).
**Архив (Step 8 @PM, 20.09.2026):** все **24 фич-папки** перенесены `plans/features/<feature>-round1024/` → **`plans/archive/<feature>-round1024/`** (3 частично трекнутых — `budget-guardrails`, `logging-infra`, `providers-fullscreen-advanced-fix` — `git mv`; остальные — обычный move; сохранены `spec.md` + `tasks.md` + **`ADR-1024-N.md`**); сквозные доки `round1024-architecture.md`, `round1024-web-architecture.md`, `round1024-upd4-architecture.md` → `plans/archive/`. R18-скан папок — **чисто** (реальных секретов/ключей/токенов/SSH-кред нет); в `plans/features/` остались только 6 backlog-папок, пустых/осиротевших нет.

**Остаточный техдолг 10.24 (Low 3 + Info 5, не блокеры — источник `plans/reports/round1024_scanner_audit.md`):** **L10.24-1** (F19: тристейт форс-повтора может «проглотить» причину → тихий пропуск ответа при раннем `return False` в `force_repeat_from_reply`; практическая частота низкая); **L10.24-2** (F14: `_DOWNLOAD_NATIVE_MAX_BYTES` = 2 ГБ — лимит локального Bot API, для облачного (~50 МБ) гейт не отсекает рано → обобщённое «Не удалось переслать видео» вместо честной причины); **L10.24-3** (F12/F2: тело ошибочного ответа при скачивании изображения логируется без явного `_redact_secret` — hardening R17). **I10.24-1** (F13: медиа-маркер может превысить cap при экстремально малом `limits.chat_current_question_max_chars`); **I10.24-2** (F1: неточный текст `GraphExtractionError` «all N chunk(s) failed»); **I10.24-3** (F4: N+1-резолв `AliasResolver` на каждый `chat_id` в GLOBAL `dossier_feed`, ≤40); **I10.24-4** (F16: полное скачивание видео на каждый youtube+summary cache-miss — осознанно ADR-1024-17, tmp чистится в `finally`); **I10.24-5** (F19: `bot.send_message` вне обёрток `services/telegram_send` в `_reply_media` — файл уже allowlisted, статический egress-guard не нарушен). **D10.24-1** (F22: `audit-chat-overrides --strict` → exit=1 из-за исторических вайпов, текущий дрейф `ok=8/absent=0/different=0`); **D10.24-2** (F9: `disk cleanup --apply` требует root на `var/`).

**Триггер:** владелец **отклонил UI/UX-реализацию 10.23** и выявил боевые баги бэкенда + факты ложных отчётов. Багфикс-итерация по `plans/current_task.md`, секция **UPD2** (строки **123–237**, 11 пунктов) + секция **UPD3** (строки **239–272**, 9 решений владельца по Human Gate) + секция **UPD4** (строки **274–400**, баги, собранные вживую, кластеры **A–D**) + секция **UPD5** (строка **403**, решения владельца: YouTube-пайплайн подтверждён, cookies/POT/proxy разрешены, **разделение инструментов выжимка vs транскрибация**) + **UPD5-critical** (строка **404**: критический баг бюджетов — per-chat настройки целевого чата `-1002661910336` сбрасываются, бот уходит в фразу-заглушку; требование — глобальный master-тумблер бюджетов в «Модулях» (глобально/для выбранного чата) + доказать, что работает). Файл untracked, содержит plaintext-SSH-креды → **не коммитить, значения не цитировать** (R17/R18); API-ключи изображений — только как «ключ из ТЗ».
**Baseline (Step 0 @Memory):** HEAD **`00eab85`** (=`origin/master`, дерево чистое); раунд 10.23 — COMPLETED+DEPLOYED+ARCHIVED (прод **`4314ea4`**); pytest **7424 passed / 0 failed**; SQLite `user_version=12`; каталог REGISTRY **457** / GROUPS **96** (`_TAB_BY_GROUP` 94).
**Отчёт @Memory (UPD4):** `upd4-live-bug-clusters-round1024` (кластеры A–D, координаты, severity, конфликты).

**Реализовано (Step 1 @PM): базово 12 фич-папок; в UPD4 (Step 1c) добавлены ещё 6; в UPD5 (Step 1d) добавлена ещё 1; в UPD5-critical (Step 1e) добавлены ещё 4; в UPD6 (Step 1f) добавлена ещё 1 (F24) — итого 24 фич-папки `plans/features/<name>-round1024/` с `tasks.md`.** Базовый объём — **T-2188…T-2288 (101)**; в UPD3 (Step 1b) добавлены **T-2289** (F8 — Empty State) и **T-2290** (F12 — кнопка «Проверить подключение»); в UPD4 (Step 1c) добавлены F13–F18 — **T-2291…T-2331 (41)**; **в UPD5 (Step 1d) добавлены F13/F14/F15/F16-доработки + новая F19 `media-transcribe-tool-round1024` — T-2332…T-2352 (21)**; **в UPD5-critical (Step 1e) добавлены F20–F23 (бюджеты) — T-2353…T-2379 (27)**; **в UPD6 (Step 1f) добавлена F24 (Провайдеры/fullscreen) — T-2380…T-2387 (8)** → итог **T-2188…T-2387 (200)**, дублей ID нет (фактический максимум до UPD6 — T-2379, подтверждено `plans/features/*-round1024/tasks.md`). **Отменено владельцем:** T-2191/T-2192 (F1, embeddings, UPD3 №7).
> ⚠️ **Оговорка по нумерации:** в отчёте @Memory последним ID 10.23 указан `T-2186`, **однако `T-2187` уже занят** (review-задача в `plans/archive/verbalizer-response-modes-round1023/tasks.md:36`). Во избежание коллизии нумерация раунда 10.24 начата с **`T-2188`**. UPD5-задачи продолжены **с `T-2332`** (максимум до UPD5 — `T-2331`).
> **`spec.md`/`ADR` PM не создаёт — Step 2 @Architect** (в т.ч. AMEND/RE-OPEN, см. ниже).

| # | Фича (папка) | ТЗ | Тип | Приоритет | Зависит от | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `core-llm-error-fixes-round1024` — п.0a: `LLMTimeoutError` в `_extract_and_save_graph` (граф тихо терялся) → deadline/retry + логирование + устойчивость. **п.0b (embeddings 400 «Unknown name `requests`») ОТМЕНЁН владельцем (UPD3 №7)** — код не трогаем | п.0 + UPD3 №7 | backend/LLM + надёжность | **P0** | F2 (лог) | T-2188…T-2195 (8; **T-2191/T-2192 cancelled**) |
| **F2** | `logging-infra-round1024` — п.11: тела ответов сторонних API (Pollinations), причины падения крона клише, трассировка Экстрактора, 4xx embeddings; принцип «тихий откат ≠ тишина в логах»; маскирование секретов | п.11 | инфраструктура логирования (enabler) | P1 | — | T-2196…T-2204 (9) |
| **F3** | `token-metrics-nodeflow-round1024` — п.1: настоящее визуальное дерево (Node Flow) последнего вызова (`Запрос → Синтезатор → Вербализатор → Итог`), русский нейминг, графики день/неделя/месяц (API уже есть) | п.1 | UI (`web/**`) | P1 | — | T-2205…T-2212 (8) |
| **F4** | `dossier-live-feed-round1024` — п.2: вертикальная медленная лента (снизу вверх) + кликабельные строки → модалка «Досье»; backend отдаёт `user_id`; GLOBAL→per-chat. **Гейт №9 согласован (UPD3 №9)** | п.2 + UPD3 №9 | UI + API | P1 | F3 (web-ступень) | T-2213…T-2220 (8) |
| **F5** | `image-module-toggle-round1024` — п.3: карточка «Генерация изображений» в «Модулях» с главным тумблером (default ON); вынести `flags_module_images` из «Прямого чата». **✅ UPD3 №1: отдельный пункт меню, `tma-menu-freeze` для него снят** | п.3 + UPD3 №1 | каталог + UI | P1 | ✅ Gate №1 закрыт | T-2221…T-2226 (6) |
| **F6** | `prompts-refactor-accordion-modes-round1024` — п.4: убить аккордеоны (одиночное поле — открыто), табы режимов — внутрь карточек модулей. **UPD3 №2: дропдаун НЕ удалять → «Резервный режим (Fallback)», дефолт `casual`, только на сбойном пути (не влияет на динамический роутинг Синтезатора)** | п.4 + UPD3 №2 | каталог + UI + backend | P1 | ✅ Gate №2 закрыт, F5 | T-2227…T-2236 (10; Δ каталога = 0) |
| **F7** | `anticliche-cron-limit-round1024` — п.5: снять хардкод-лимит 20. **UPD3 №3: дефолт 200, лимит регулируемый (числовое поле в карточке Анти-клише)** + починить крон (**первый прогон после деплоя**, не через 7 дней) | п.5 + UPD3 №3 | backend/worker + UI | P1 | F2 | T-2237…T-2243 (7) |
| **F8** | `dead-extractor-paradigms-round1024` — п.6: живой дебаг «Глубокого сна», починка парадигм и черт (traits требуют self-фактов `origin='bot_self_reply'`). **UPD3 №4: при отсутствии self-фактов не галлюцинировать → Empty State в UI; обязательно проверить извлечение фактов/парадигм о пользователях** | п.6 + UPD3 №4 | backend + UI | **P0** | F2, ✅ Gate №4 закрыт | T-2244…T-2253 (10) + **T-2289** (Empty State) |
| **F9** | `disk-space-audit-retention-round1024` — п.7: аудит диска (+6 ГБ), очистка, retention, отчёт «причина/что удалено/прогноз». **UPD3 №5: строго 1 бэкап БД; JSONL — 6 мес, НО дампы/архивы истории сообщений — НИКОГДА не удалять (бессрочно); логи — 7 дней** | п.7 + UPD3 №5 | ops/данные (только сервер) | **P0** | ✅ Gate №5 закрыт | T-2254…T-2263 (10) |
| **F10** | `aliases-render-real-fix-round1024` — п.8: реальный data-binding «Словарь алиасов имён» (object-value widget `keyvalue`); прошлый отчёт — ложный | п.8 | UI (`web/**`) | P1 | F3… (web-очередь) | T-2264…T-2270 (7) |
| **F11** | `byok-image-key-round1024` — п.9: сохранение ключа изображений отдельным запросом на `/api/config/keys/own`, заглушка `••••••••••••`, блокировка/очистка поля в GET-режиме; AMEND BYOK-whitelist. **✅ UPD3 №6: сохранение через безопасный эндпоинт согласовано** | п.9 + UPD3 №6 | UI + backend | P1 | ✅ Gate №6 закрыт | T-2271…T-2278 (8) |
| **F12** | `summary-cover-model-compat-round1024` — п.10: **никакой карты модель→параметры**, payload строго по стандарту (любой OpenAI-совместимый провайдер), убрать `size`; п.10.1 — проверка подмешивания `prompts.summary_cover_style` + лог финального промпта. **UPD3 №8: кнопка «Проверить подключение» (тост с сырым текстом ошибки)** | п.10 + 10.1 + UPD3 №8 | backend + UI + лог | P1 | F2 | T-2279…T-2288 (10) + **T-2290** (кнопка теста) |
| **F13** | `native-reply-media-context-round1024` — **UPD4 A-1:** «Бот что на видео» реплаем на нативное TG-видео → контекст реплая text-only (`thread_chain`/`chat_context` скипают пустой текст; `_render_current_question` — только `message.text`) → медиа-маркер в цепочке/окне/вопросе; **байт-в-байт при отсутствии медиа**. **UPD5 №3: маркер несёт сигнал типа запроса (выжимка vs транскрипт) для tool-loop F19** | UPD4 A-1 + UPD5 №3 | backend контекста | P1 | F14 (взаимно) | T-2291…T-2298 (8) + **T-2332** |
| **F14** | `native-media-tools-round1024` — **UPD4 A-2:** «скачай» реплаем на нативное видео → caption-URL перебивает `_handle_native_media`; инструменты `summarize_video`/`download_media` требуют `url`; probe-fail без причины. Приоритет медиа, инструменты нативного медиа; **AMEND ADR-1020-4**, AMEND ADR-1016-1/1017-2. **UPD5 №3: контракт разводит выжимку (`summarize_video`) и транскрибацию (`transcribe_video`); финальный канон 9→10 ведёт F19** | UPD4 A-2 + UPD5 №3 | backend tool-calling + Fast-Track | P1 | F13, F2 | T-2299…T-2306 (8) + **T-2333…T-2335** |
| **F15** | `video-download-native-ux-round1024` — **UPD4 A-3 (UX):** понятное объяснение probe-fail; меню качества неприменимо к реплай-видео; поведение при видео+caption-URL; **AMEND ADR-1016-1/1017-2 (UX)**. **UPD5 №3: ответы различают выжимку и транскрипт (формулировки)** | UPD4 A-3 + UPD5 №3 | UX сообщений | P2 | F14 | T-2307…T-2312 (6) + **T-2336** |
| **F16** | `youtube-multimodal-download-fallback-round1024` — **UPD4 B (P0):** YouTube+summary шлёт в OpenRouter **URL страницы** (не файл) → L1/L2 падают → L3 субтитры; age-restricted субтитры **PERMANENT**. Пайплайн «скачать → мультимодалка → фолбэк субтитры», переиспользовать нативную инфру; **AMEND/архивная граница** `video-multimodal-pipeline-and-incidents`. **UPD5 №1/№2: порядок уровней подтверждён; cookies/POT-proxy разрешены → в scope как опц. уровень для age-restricted; YouTube-«транскрипт» → голый транскрипт курсивом** | UPD4 B + UPD5 №1/№2/№3 | backend видео-пайплайн | **P0** | архив-инфра (есть), F2 | T-2313…T-2321 (9) + **T-2337…T-2342** |
| **F17** | `sqlite-lock-resilience-round1024` — **UPD4 C (Medium):** `smart_cache` (`:89-103`) без WAL/busy_timeout/synchronous/retry → `database is locked` → WARNING + no-op. Паритет с `database.py:514-520` + bounded retry | UPD4 C | backend/БД-инфра | P1 | F2 (лог) | T-2322…T-2327 (6) |
| **F18** | `sqlite-row-get-fix-round1024` — **UPD4 D (Low-Medium):** `web/api/chat_lore.py:666-682::_participant_names` вызывает `r.get(...)` на `aiosqlite.Row` → `AttributeError`. Заменить на `row_get`; превентивный grep. **Опция: merge в F4** | UPD4 D | backend-багфикс | P2 | — | T-2328…T-2331 (4) |
| **F19** | `media-transcribe-tool-round1024` — **UPD5 №3 (НОВАЯ):** разделение инструментов по функциям — **выжимка** (`summarize_video`) vs **транскрибация** (новый `transcribe_video`), чёткие tool-definitions, чтобы LLM выбирала сырой транскрипт или выжимку; команда «транскрипт» принудительно повторяет транскрибацию ГС/кружка и работает для любого видео; YouTube-URL → **голый транскрипт аудио курсивом**; **AMEND ADR-1020-4 (канон R9 9→10)** + **AMEND ADR-1024-15 §2.1/§2.3**; закрывает техдолг 10.23 **I2** | UPD5 №3 | backend tool-calling + команды/оркестрация | **P1** | F13, F14, F16 | T-2343…T-2352 (10) |
| **F20** | `budget-overrides-merge-fix-round1024` — **UPD5-critical (НОВАЯ, P0/Critical):** корневая причина потери per-chat настроек — `web/api/routes.py:482` берёт `chat_overrides = dict(root.get("perm_overrides"))` (матрица прав!) вместо `root.get("overrides")` (значения), затем `:523-529` **полностью перезаписывает** namespace `overrides` = perm_overrides ∪ сохранённый ключ. Одиночный save (`web/app.js:4454-4461`) стирает все прочие per-chat значения (8 seed-ключей целевого чата, вкл. `-1`). Правильный образец — GET `:372-377` и DELETE `:729`. **AMEND ADR-1019-8 / ADR-1012-1** (ожидаемо ADR-1024-21) | UPD5-critical (строка 404) | backend-багфикс (merge per-chat) | **P0 / Critical** | — | T-2353…T-2359 (7) |
| **F21** | `budget-global-toggle-round1024` — **UPD5-critical (НОВАЯ, P0):** master-тумблер бюджетов в «Модулях» — новый ключ **`flags.budgets_enabled`** (+`GroupSpec`) и `toggleKey` у `mod_budgets` (сейчас `noToggle: true`, `web/app.js:393-395`); гейты OFF в `chat_usage.budget_snapshot` (`:194-258`), `worker_budget.consume/_metric_limit` (`:201-227,260-278`), `llm_client._resolve_api_key_and_source` (`:404-420`); UI; семантика OFF (не считать/не ограничивать; счётчики пишутся; дефолт fail-open), глобально **и** per-chat (per-chat приоритетнее), дефолт ON; разграничение с `flags.chat_context_budgets_enabled`. **Δ каталога — в Human Gate** (вопрос G №1). **AMEND ADR-1019-3/1019-8/1019-2-D4** (ожидаемо ADR-1024-22) | UPD5-critical (строка 404) | каталог + backend-гейты + UI | **P0** | **F20** | T-2360…T-2368 (9) |
| **F22** | `budget-data-repair-round1024` — **UPD5-critical (НОВАЯ, P0):** восстановление/аудит `overrides` целевого чата `-1002661910336` (8 per-chat значений из `config/chat_settings_seed.json:11-20`, вкл. `-1`); идемпотентный сид/`manage.py apply-chat-overrides --force` или repair-команда; JSONL-аудит `chat_lore_history field='chat_params'`; **AMEND/разграничение `flags.chat_context_budgets_enabled`** (`direct_chat_service.py:1142-1145`, `scripts/backfill_104_chat_flags.py`). **AMEND ADR-1019-8 D4** (ожидаемо ADR-1024-23) | UPD5-critical (строка 404) | ремонт/аудит данных (PG) | **P0** | **F20** | T-2369…T-2375 (7) |
| **F23** | `budget-guardrails-round1024` — **UPD5-critical (НОВАЯ, опц., P1):** пин-тесты каталога/TAB_RULES после F21; freeze-инвариант меню «Модули» (для «Бюджетов» **не снимать**); сквозные R16/R17/R18; финальный guard-прогон | UPD5-critical (строка 404) | тесты/инварианты | P1 (опц.) | F20, F21, F22 | T-2376…T-2379 (4) |
| **F24** | `providers-fullscreen-advanced-fix-round1024` — **UPD6 (НОВАЯ, боевой UI-баг):** в разделе «Провайдеры» (`llm_providers`) аккордеон «Расширенные системные» (`index.html:559-562`) пропадает при переходе в fullscreen. Первопричина: разрыв «TMA fullscreen ↔ Vue» (`isFullscreen` не читается из `Telegram.WebApp.isFullscreen`, `app.js:939/3651-3665`, подписок на `fullscreenChanged`/`viewportChanged` нет) + **нереактивный** `:open` (`expandOpen()` читает `localStorage` на каждом рендере, `app.js:3768-3779`, поле `data.expand` `:831` мёртвое) → ремаунт WebView пересоздаёт `<details>` и схлопывает. Фикс: инициализация из TMA + подписка/отписка на события; реактивный стейт аккордеона (init из `localStorage` один раз, обновление в `toggleExpand`, бинд `:open`); скоуп — «Провайдеры» или все `details.advanced`; JS-тесты; live-приёмка TMA. **AMEND решения 10.10** (`archive/admin-ui-round1010/spec.md:53`) | UPD6 (живой дефект владельца) | web-UI (Vue/мини-апп + TMA) | **P1 / Medium** (UI, данные не теряет) | — (изолирован; в web-очередь F3→F5→F6→F11→F4→F10) | T-2380…T-2387 (8) |


**UPD4 — детали фич F13–F18 (баги, собранные вживую; `current_task.md` строки 274–400):**
- **Кластер A (нативное видео + tool calling):** A-1 → **F13** (медиа-маркер в контексте; **UPD5:** + сигнал выжимка/транскрипт, T-2332); A-2 → **F14** (приоритет нативного медиа над caption-URL + инструменты нативного медиа; **AMEND ADR-1020-4**, ревизия канона **R9 «8→9→10»** — финальный счётчик 10 и `transcribe_video` ведёт **F19**, закрывает техдолг 10.23 **I2** — устаревший комментарий `tool_schemas.py:241`); A-3 → **F15** (UX: причина probe-fail, меню качества неприменимо к реплай-видео; **UPD5:** + различение выжимка/транскрипт, T-2336).
- **Кластер B (YouTube+summary):** **F16 (P0)** — скачать видео → мультимодальная выжимка → фолбэк субтитры; переиспользование `download → media_share → summarize_media_url` (`handlers/youtube.py:630-662,957-968`); **AMEND/архивная граница** `plans/archive/video-multimodal-pipeline-and-incidents` (spec:37 — «байт-в-байт»; spec:241; FR-B5:52).
- **Кластер C:** **F17 (P1/Medium)** — WAL/busy_timeout/synchronous + bounded retry в `smart_cache`.
- **Кластер D:** **F18 (P2/Low-Medium)** — `row_get` вместо `.get` на `aiosqlite.Row`; **опция merge в F4** (решение владельца — открытый вопрос №6 ниже).
- **UPD5 — F16 (YouTube):** порядок уровней подтверждён (T-2337); cookies/POT-proxy в scope как опц. уровень для age-restricted (T-2338); YouTube-«транскрипт» → голый транскрипт аудио курсивом (T-2339); тесты/review/live (T-2340…T-2342).
- **UPD5 — F19 `media-transcribe-tool-round1024` (НОВАЯ, P1):** инструмент **`transcribe_video`** отдельно от выжимки `summarize_video` (чёткие tool-definitions, T-2343/T-2344/T-2348); dispatch STT (T-2345); команда «транскрипт» принудительно повторяет транскрибацию ГС/кружка (T-2346) и любого видео/YouTube-URL курсивом (T-2347); ревизия канона **9→10** (T-2349); тесты/review/live (T-2350…T-2352). Эксклюзив: `handlers/voice_transcription.py` + `handlers/media_common.py`.
- **Ступени общих файлов (UPD4 + UPD5):** `handlers/video_download.py` — **F14 → F15**; `services/tool_schemas.py`/`services/tool_router.py` — **F14 → F19** (UPD5: финальный канон 10 и `transcribe_video` ведёт F19); `services/thread_chain.py` + `services/chat_context.py` + `services/direct_chat_service.py` — **F13**; `handlers/youtube.py` — **F16 → F19** (UPD5: разведение выжимка/транскрипт); `services/youtube_summarizer_service.py` + `services/youtube_transcript_engine.py` — **F16**; `handlers/voice_transcription.py` + `handlers/media_common.py` — **F19** (эксклюзив); `services/smart_cache.py` — **F17**; `web/api/chat_lore.py` — **F18**.
- **Флаги UPD4/UPD5 (env-only `ClassVar`, default ON):** `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED` (F13), `NATIVE_MEDIA_TOOLS_ENABLED` (F14), `VIDEO_DOWNLOAD_NATIVE_UX_ENABLED` (F15), `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` (F16; при риске нагрузки — OFF без деградации, фолбэк на прежний каскад), `SMART_CACHE_LOCK_RESILIENCE_ENABLED` (F17), **`MEDIA_TRANSCRIBE_TOOL_ENABLED` (F19)**; F18 — без флага (чистый багфикс). Поэтапная раскатка internal→10%→50%→100% — **только для F16 (P0) на усмотрение владельца**; остальные — kill-switch. Откат: флаг OFF / `git revert`; **Δ DDL = 0, Δ каталога = 0** (F16 — параметры только если решит @Architect).

**UPD4 — ОТКРЫТЫЕ ВОПРОСЫ К ВЛАДЕЛЬЦУ (Human Gate):**
1. **B (F16) — ✅ ЗАКРЫТ (UPD5 №1):** порядок «**скачать видео → мультимодалка → фолбэк субтитры**» **подтверждён** владельцем.
2. **B (F16) — ✅ ЗАКРЫТ (UPD5 №2):** **cookies / POT-provider (bgutil :4416) / resident-proxy на проде разрешены**; перенесено **в scope** F16 как **опциональный уровень для age-restricted** (значения только `.env`, R17/R18).
3. **A (F13/F14) — ✅ ЗАКРЫТ (UPD5 №3):** «что на видео»/«че за видос» → **выжимка**; «транскрипт» → **транскрибация**; меню качества для реплай-видео не требуется; раздельные инструменты → **F19**.
4. **A-2 (F14/F15) — 🟡 ОТКРЫТ:** приоритет при наличии **и видео, и caption-URL** (по умолчанию — нативное медиа > caption-URL, T-2299/T-2302; подтвердить/уточнить).
5. **Канон R9 (F14/F19) — ✅ ЗАКРЫТ (UPD5 №3):** согласовано разделение **выжимка/транскрибация**; канон **9→10**; **AMEND ADR-1020-4 (9→10)** + AMEND ADR-1024-15.
6. **D (F18) — 🟡 ОТКРЫТ:** **merge в F4** `dossier-live-feed-round1024` или **отдельная фича** (по умолчанию — отдельная).
7. **Нумерация — ✅ ЗАКРЫТ (UPD5 №7):** делаем **все фичи**, нумерация не важна; результат важнее.

**UPD5 — решения владельца (`current_task.md` строка 403):**
- **№1 (F16):** пайплайн «скачать видео → мультимодальная выжимка → фолбэк на субтитры» — **подтверждён** (F16 подтверждён).
- **№2 (F16):** cookies/POT-/resident-proxy на проде **разрешены** → убрано из Open Questions, перенесено в scope как опциональный уровень для age-restricted (F16 T-2337/T-2338).
- **№3 (F13/F14/F15/F16 + новая F19) — ключевое расширение:** «Что на видео», «Че за видос» и подобные — запрос на **саммаризацию (выжимку)**; «транскрипт» — отдельная команда именно **транскрибации**: принудительно повторяет транскрибацию ГС/кружка, если авто не сработало, и так же работает для любого видео (в т.ч. YouTube — отдаёт **голый транскрипт аудио курсивом**). Итог: **разделение инструментов по функциям** — в tool calling **отдельно инструмент выжимки** (`summarize_video`) и **отдельно транскрибации** (`transcribe_video`), с чёткими определениями, чтобы LLM сама выбирала сырой транскрипт или выжимку → **новая фича F19**.
- **№4–6:** пояснения простыми словами владельцу — от @Orchestrator (в планах не требуются).
- **№7:** делаем **все фичи**, нумерация не важна.
- **AMEND канона инструментов:** **ADR-1020-4: 9→10** (было 8 в ADR-1020-4 + `generate_image` 10.23 = 9; + `transcribe_video` = **10**). Также **AMEND ADR-1024-15 §2.1/§2.3** (F14 зафиксировал 9 и перегруз `mode`).

**UPD5-critical — детали фич F20–F23 (бюджетный кластер, `current_task.md` строка 404):**
- **Симптом:** бюджеты сброшены для чата `-1002661910336` (были бесконечные лимиты); в мини-аппе значения бюджетов сбрасываются и не применяются; бот отвечает фразой-заглушкой `content.no_key_reply` («у чата нет своего ключа, а глобальный недоступен или исчерпан…»).
- **Фраза-заглушка:** `services/sandbox_reply.py:8-11` (`DEFAULT_NO_KEY_REPLY`, ключ `content.no_key_reply`) → ответ `services/direct_chat_service.py:767-781`.
- **Блокировка:** `services/llm_client.py::_resolve_api_key_and_source` (`:385-420`) → `NoApiKeyForChat('budget')` при `snapshot["exceeded"]` (`services/chat_usage.py:404-420`).
- **Корневая причина потери настроек (Critical → F20):** `web/api/routes.py:482` берёт `chat_overrides = dict(root.get("perm_overrides"))` (матрица прав) вместо `root.get("overrides")` (значения); `:523-529` перезаписывает `overrides` = `perm_overrides ∪ patch`. Одиночный save (`web/app.js:4454-4461`) стирает все прочие per-chat значения (8 seed-ключей `config/chat_settings_seed.json:11-20`, вкл. `-1`). Образцы корректного чтения: GET `routes.py:372-377`, DELETE `routes.py:729`.
- **«Самоизлечение»:** сид при рестарте возвращает `overrides` (`bot.py:1049-1051`, `services/chat_settings_seed.py:145-185`), следующая правка снова стирает.
- **Тумблер (F21):** `mod_budgets` помечен `noToggle: true` (`web/app.js:393-395`), секция только `limits` (`:130-135`); механика — `MODULES`+`toggleKey` (`:356-395`, `:3163-3174`).
- **Гейты для OFF (F21):** `services/chat_usage.py:194-258` (`budget_snapshot`), `services/worker_budget.py:201-227,260-278` (`consume`/`_metric_limit`), `services/llm_client.py:404-420`. Резолв флага per-chat — `services/worker_settings.py:123-150`.
- **Существующий близкий гейт (F22 — разграничить):** `flags.chat_context_budgets_enabled` (`services/direct_chat_service.py:1142-1145`; `scripts/backfill_104_chat_flags.py` ставит `false` целевому чату) — усечение бюджета **контекста промпта**, а НЕ master-рубильник лимитов.
- **Ступени общих файлов (UPD5-critical):** `web/api/routes.py` — **F11 → F20 → F22**; `web/app.js` — web-очередь → **F21**; `services/param_catalog.py` — F5 → F6 → F7 → **F21**; `services/llm_client.py` — F1 → **F21**; `services/chat_usage.py` + `services/worker_budget.py` — **F21**; `config/chat_settings_seed.json` + `services/chat_settings_seed.py` + `manage.py` + `scripts/backfill_104_chat_flags.py` — **F22**; `tests/**` (пин-каталог/фронт) — **F23**.
- **Флаги:** **`flags.budgets_enabled`** (F21, каталоговый, default ON — он же продуктовый тумблер; **Δ каталога — в Human Gate G№1**); F20/F22 — поведенческие/ops-фиксы без флага; F23 — без флага. Поэтапная раскатка internal→10%→50%→100% — **опционально для F21** через per-chat/global override; остальное — kill-switch. Откат — флаг ON/`git revert`; **Δ DDL = 0**.

**UPD5-critical — ОТКРЫТЫЕ ВОПРОСЫ К ВЛАДЕЛЬЦУ (Human Gate G; `current_task.md` строка 404):**
1. **G1 (F21) — каталог:** санкция на **Δ каталога** — новый ключ `flags.budgets_enabled` + новая `GroupSpec` (группа-рубильник бюджетов)? (по умолчанию — да, иначе тумблер невозможен).
2. **G2 (F21) — семантика OFF:** «не считать и не ограничивать» (счётчики usage продолжают писаться; дефолт fail-open при недоступности резолва) — подтверждение?
3. **G3 (F21/F22) — иерархия:** master-тумблер перекрывает `flags.chat_context_budgets_enabled` (OFF master отменяет и усечение контекста)?
4. **G4 (F21) — область:** глобально **И** per-chat, при этом per-chat override приоритетнее глобального — подтверждение?
5. **G5 (F22) — ремонт данных:** сид `--force` или ручная правка после фикса F20? Нужен ли JSONL-аудит `chat_lore_history field='chat_params'` в отчёте?
6. **G6 (F20/F22) — приёмка:** кто/где проводит live-приёмку на целевом чате (dev-режим разведён, цели — пост-фикс).

**UPD6 — детали фичи F24 (`providers-fullscreen-advanced-fix-round1024`, живой дефект владельца):**
- **Симптом:** в разделе «Провайдеры» advanced-настройки (аккордеон «Расширенные системные») пропадают при переходе в фулскрин; раскрытие не переживает переход/ре-рендер. **Данные не теряются** (UI-дефект, не связан с F20–F23-бюджетами).
- **Первопричина 1 — разрыв TMA↔Vue:** `isFullscreen: false` (`web/app.js:939`) не читается из `Telegram.WebApp.isFullscreen`; `toggleFullscreen()` (`:3651-3665`) — оптимистичный локальный флаг; подписок на `fullscreenChanged`/`viewportChanged`/`safeAreaChanged` нет (единственное `onEvent` — `'ready'`, `:1650-1651`).
- **Первопричина 2 — нереактивный `:open`:** `expandOpen()` (`web/app.js:3768-3772`) читает `localStorage` в рендере; `toggleExpand()` (`:3773-3779`) пишет только в `localStorage`; ключ `adminbot.expand:llm_providers:prov-advanced` (`_expandKey` `:785-787`); поле `data.expand` (`:831`) мёртвое. Ремаунт WebView → `<details>` пересоздаётся и схлопывается.
- **CSS ни при чём:** `.fullscreen-mode` (`web/static/app.css:659-668,686-690`) меняет только height/overflow; скрытий `:fullscreen`/`.tg-fullscreen`/`@media max-height` нет.
- **Скоуп-риск:** `details.advanced` также в `web/index.html:526-552`, `:804-869`, `:1040-1062`, `:1990-…`, `:2358-…` — потенциально тот же дефект (решение — вопрос O3).
- **AMEND:** решения 10.10 (`plans/archive/admin-ui-round1010/spec.md:53` — «JS не менять, `toggleFullscreen` оптимистичный локальный флаг; слушатель `fullscreenChanged` не требуется») → ожидаемо **ADR-1024-24** (вопрос O4).
- **Ступень общих файлов (UPD6):** `web/app.js` + `web/index.html` — встроить в web-очередь **F3 → F5 → F6 → F11 → F4 → F10**; `web/app.js` также правит **F21** → сериализовать.
- **Флаги:** не требуются (клиентский UI); откат — `git revert` + cache-bust (`?v=`/`APP_VERSION`). **Δ DDL = 0, Δ каталога = 0.**

**UPD6 — ОТКРЫТЫЕ ВОПРОСЫ К ВЛАДЕЛЬЦУ (Human Gate O; живой дефект, F24):**
1. **O1 — платформа/канал:** Android или iOS? Вход через нативную кнопку Telegram или `⛶`? Проявляется ли и при **выходе** из fullscreen?
2. **O2 — ожидание:** advanced на «Провайдерах» должны по умолчанию быть **раскрыты**, или достаточно, чтобы **раскрытие переживало** вход/выход fullscreen?
3. **O3 — скоуп:** только «Провайдеры» или **единый** реактивный аккордеон для всех `details.advanced`?
4. **O4 — AMEND 10.10:** разрешение изменить JS и подписаться на `fullscreenChanged`/`viewportChanged`?

**Порядок исполнения (рекомендация):**
1. **Волна 0 (enabler, параллельно):** **F2** (лог-хуки; минимальный набор сразу) ∥ **F9** (аудит/очистка диска, ops, независимо).
2. **Волна 1 (P0, параллельно, файлы не пересекаются):** **F1** (`llm_client`/`summary_memory`) ∥ **F8** (`dream_worker`); F9 продолжается.
3. **Волна 2 (backend, почти без пересечений):** **F7** (`anticliche_worker/cache`) ∥ **F12** (`image_generation`/`summary_generator`) ∥ **F11-backend** (`chat_keys`/`routes`).
4. **Волна 3 (web-очередь, строго последовательно):** **F3 → F5 → F6 → F11-frontend → F4 → F10**; мелкие UI-правки **F7** (`index.html:394-397`), **F8** (`index.html:2509-2537`, `app.js:6274-6315`) встраиваются в эту же очередь без одновременного редактирования.
5. **UPD4 — Волна A (независимые мелкие, параллельно):** **F17** (`smart_cache.py`) ∥ **F18** (`web/api/chat_lore.py`) — изолированы, можно сразу.
6. **UPD4 — Волна B (нативное видео, последовательно по ступени):** **F13** (контекст) → **F14** (инструменты + маршрутизация; после контракта T-2291) → **F15** (UX поверх F14).
7. **UPD4 — Волна C (P0, самый рискованный):** **F16** (YouTube мультимодалка) — **вопросы №1–2 закрыты (UPD5)** → можно после @Architect spec; параллелен A/B по файлам (`handlers/youtube.py`).
8. **UPD5 — Волна D (разделение инструментов, последовательно по ступеням):** **F13 → F14 → F16 → F19** (`media-transcribe-tool-round1024`). F19 — после F14 (контракт `tool_schemas`/`tool_router`) и F16 (`handlers/youtube.py`); эксклюзив F19 — `handlers/voice_transcription.py` + `handlers/media_common.py`. F19-канон (**9→10**) — финальный, поэтому F14 не фиксирует счётчик 9.
9. **UPD5-critical — Волна E (бюджеты, строго по порядку; live-аудит параллельно):** **F20 → F21 → F22**; **F23** — после них. F20 — первым (иначе настройки/ремонт снова затираются); F21 — после F20 (иначе тумблер/значения не сохраняются); F22 — ремонт данных после F20. **F20 (`web/api/routes.py`) изолирован от web-очереди — можно стартовать сразу;** F21 делит `web/app.js`/`services/param_catalog.py` с web-очередью → встроить в неё; live-аудит целевого чата — параллельно F21-backend после F20.
10. **UPD6 — Волна F (web-багфикс, изолирован):** **F24** (`providers-fullscreen-advanced-fix-round1024`) — встроить в web-очередь (F3 → F5 → F6 → F11 → F4 → F10) без одновременного редактирования `web/app.js`/`web/index.html`; `web/app.js` также правит F21 → сериализовать; старт после закрытия вопросов O1–O4 (в т.ч. санкция AMEND 10.10).

**Ступени общих файлов:** `services/param_catalog.py` — **F5 → F6 → F7** (F5 — вынос группы изображений; F6 — Δ=0, ключ сохраняется; F7 — параметр лимита клише); `web/index.html`/`web/app.js` — **F3 → F5 → F6 → F11 → F4 → F10** (+ F7/F8-UI в очередь, **+ F24-UPD6**); `services/llm_client.py` — **F1**; `services/summary_memory.py` — **F1** (F8 читает); `services/dream_worker.py`/`image_generation.py`/`anticliche_worker.py` — **F2 (лог) первым**, далее F8/F12/F7 соответственно; `services/chat_keys.py` + `web/api/routes.py` — **F11**; `web/api/oversight.py` + `services/database.py:dossier_feed` — **F4**; `services/summary_generator.py` (обложка) — **F12**.

**Топ-риски (полные списки — `tasks.md` каждой фичи):** удаление единственного валидного бэкапа и/или JSONL с историей сообщений при очистке диска (**Critical, F9**); утечка секретов в git/логи/общие настройки (**Critical/High, F2/F11** — маскирование + egress-тест); расширение BYOK меняет модель прав (High, F11); случайное задевание отменённого embeddings-кода (Low, F1); включение/изменение гейтов сна (High, F8); раздувание промпта клише при больших значениях лимита (High, F7 — дефолт 200); изоляция изменения меню под карточку изображений (Low, F5); fallback-режим перехватывает штатный роутинг Синтезатора (High, F6); перенос табов режимов ломает сохранение (Medium, F6); GLOBAL-лента ↔ per-chat досье (High, F4); повторный «ложный» отчёт по алиасам (High, F10 — обязательный live-чек); регресс прямого чата при универсализации image-параметров (High, F12); **путаница двух близких инструментов (выжимка/транскрибация) в tool-loop и принудительный повтор транскрибации (High, F19)**; **утечка YouTube-креды (cookies/POT/proxy) в git/логи (High, F16 — `.env` только, R17/R18)**; **затирание per-chat настроек merge-багом с `perm_overrides` (Critical, F20 — регресс-тесты «два save», seed-overrides выживают)**; **OFF-тумблер отключает бюджеты слишком широко / не работает в одном из трёх гейтов (Critical/High, F21)**; **Δ каталога без санкции ломает `test_param_catalog`/freeze-меню (High, F21 — Human Gate G№1 + F23)**; **ремонт данных до фикса F20 → повторная потеря (Critical, F22 — строгий порядок F20→F22)**; **`--force` сида перетирает намеренный выбор админа (High, F22)**; **путаница master-тумблера с `flags.chat_context_budgets_enabled` (High, F21/F22)**; **ремаунт WebView при fullscreen не воспроизводим локально → фикс может не закрыть дефект (High, F24 — live-приёмка TMA + эскалация @Architect)**; **общий фикс всех `details.advanced` задевает чужие вкладки (Medium, F24 — раздельные `scope`-ключи)**; **AMEND решения 10.10 без санкции владельца (Medium, F24 — Human Gate O4)**; секреты в отчётах (R17/R18, все фичи).

**Конфликты ADR (Step 2 @Architect — AMEND/RE-OPEN):** п.3 → AMEND ADR-1023-5 (каталог; **Gate №1 закрыт: отдельный пункт меню, freeze снят**); п.4 → **AMEND ADR-1023-8** (**Gate №2 закрыт: дропдаун сохранён как Fallback `casual`, только сбойный путь**); п.5 → **AMEND ADR-1023-4 D2** (**Gate №3 закрыт: дефолт 200, регулируемый**); п.6 → **RE-OPEN 10.18/10.20** (**Gate №4 закрыт: Empty State, без галлюцинаций, проверка пользовательских фактов**); п.8 → **RE-OPEN/AMEND F2 10.22**; п.9 → **AMEND `chat_keys`** (**Gate №6 закрыт: BYOK согласован**); п.10 → **AMEND ADR-1023-5/6** (**Gate №8: универсальный payload без карты, кнопка теста**); п.1 → **AMEND ADR-1023-7** (UI-объём); п.2 → **AMEND 10.20 T-1897 / ADR-1022-8** (**Gate №9 закрыт**). Прочие: **п.0 — только п.0a (timeout graph-extract); п.0b embeddings ОТМЕНЁН (UPD3 №7), код не трогаем**; п.7 — ops + retention (**Gate №5 закрыт: 1 бэкап / 6 мес JSONL, кроме истории сообщений / 7 дней логи**); п.11 — новая инфра-политика.
**Конфликты ADR — UPD4:** **F13** → соблюдение **ADR-1023-1/2 байт-в-байт** при отсутствии медиа (без AMEND, но с эталонным тестом); **F14** → **AMEND ADR-1020-4** (канон R9 8→9, финальный счётчик 10 ведёт F19) + **AMEND ADR-1016-1 / ADR-1017-2** (приоритет нативного медиа, контракт отказа probe); **F15** → **AMEND ADR-1016-1 / ADR-1017-2** (UX); **F16** → **AMEND/архивная граница** `plans/archive/video-multimodal-pipeline-and-incidents` (spec:37/241, FR-B5:52); F17/F18 — поведенческие багфиксы без AMEND.
**Конфликты ADR — UPD5:** **F19** → **AMEND ADR-1020-4 (канон инструментов R9 9→10)** + **AMEND ADR-1024-15 §2.1/§2.3** (F14 зафиксировал 9 и перегруз `mode` `summary|transcript` — заменяется раздельными определениями `summarize_video`/`transcribe_video`); также канон `docs/canon` (R9). **F16** → UPD5 №1/№2 не создают нового AMEND сверх архивной границы (порядок уровней и креды — уточнение scope); **F13/F15** — без нового AMEND (сигнал типа запроса/формулировки).
**Конфликты ADR — UPD5-critical:** **F20** → **AMEND ADR-1019-8** (write-path per-chat `overrides`) + **AMEND ADR-1012-1** (per_chat/X-Chat-Id save-путь), ожидаемо ADR-1024-21; **F21** → **AMEND ADR-1019-3** (`mod_budgets` без master-тумблера, `noToggle`) + **AMEND ADR-1019-8** (семантика лимитов `0`/`<0`) + **AMEND ADR-1019-2 D4** (`budget_snapshot`/BYOK-резолв), ожидаемо ADR-1024-22; **F22** → **AMEND ADR-1019-8 D4** (сид/идемпотентность, разграничение `flags.chat_context_budgets_enabled`), ожидаемо ADR-1024-23; **F23** — без нового ADR (тесты/инварианты). **UPD6:** **F24** → **AMEND решения раунда 10.10** (`plans/archive/admin-ui-round1010/spec.md:53` — «JS не менять, `toggleFullscreen` — оптимистичный локальный флаг») — разрешить изменение JS + подписку на `fullscreenChanged`/`viewportChanged`; ожидаемо **ADR-1024-24** (вопрос O4).

**Активация / раскатка:** новых каталоговых флагов-рубильников минимум; env-only `ClassVar` (**default ON**, вне `param_catalog`): `GRAPH_EXTRACT_RETRY_ENABLED` (F1), `EXTERNAL_API_LOGGING_ENABLED`+`EXTERNAL_API_LOG_BODY_CHARS` (F2), `TOKEN_FLOW_NODEFLOW_ENABLED` (F3), `DOSSIER_LIVE_FEED_ENABLED` (F4), `PROMPTS_UI_V2_ENABLED` (F6), `DEEP_SLEEP_EXTRACT_FIX_ENABLED` (F8), `ALIASES_KEYSVALUE_RENDER_ENABLED` (F10), `BYOK_IMAGE_KEY_ENABLED` (F11), `SUMMARY_COVER_MODEL_COMPAT_ENABLED` (F12), **`NATIVE_REPLY_MEDIA_CONTEXT_ENABLED` (F13), `NATIVE_MEDIA_TOOLS_ENABLED` (F14), `VIDEO_DOWNLOAD_NATIVE_UX_ENABLED` (F15), `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` (F16, при риске нагрузки — OFF без деградации), `SMART_CACHE_LOCK_RESILIENCE_ENABLED` (F17), `MEDIA_TRANSCRIBE_TOOL_ENABLED` (F19)**; существующие — `IMAGE_GENERATION_MODULE_ENABLED` (F5), `DYNAMIC_ANTICLICHE_ENABLED` (F7). **UPD5-critical:** `flags.budgets_enabled` (**F21**, каталоговый, default ON — продуктовый master-тумблер; **Δ каталога — Human Gate G№1**); **F20/F22/F23 — без флага** (багфикс / ops-ремонт / тесты); **F24 — без флага** (клиентский web-UI; kill-switch/откат — `git revert` + cache-bust). Осознанный **Δ каталога**: F5 (перенос `flags_module_images` в отдельную вкладку/карточку), F7 (параметр лимита клише, дефолт 200), **F21 (новый ключ `flags.budgets_enabled` + `GroupSpec` — под санкцию владельца)**. **F6: Δ каталога = 0** (UPD3 №2 — ключ `prompts.verbilizer_default_mode` сохраняется как fallback, дефолт `casual`). Поэтапная раскатка internal→10%→50%→100% **не требуется** (прецедент 10.21–10.23), кроме **опционально F16 (P0)**; флаги дают kill-switch; откат — флаг OFF / `git revert` (+ обратная канон-миграция при F6, **F19 — обратная канон-миграция счётчика/имён инструментов**). **Δ DDL = 0** по всем фичам.

**✅ HUMAN GATE — ВСЕ 9 ВОПРОСОВ ЗАКРЫТЫ владельцем (UPD3, `current_task.md` строки 239–272):**
1. **Карточка изображений (UPD3 №1):** ✅ **отдельный пункт в меню «Модули»**; запрет `tma-menu-freeze` для этого пункта **снят**.
2. **`prompts.verbilizer_default_mode` (UPD3 №2):** ✅ дропдаун **НЕ удалять**; переименовать в **«Резервный режим (Fallback)»**, дефолт **`casual`**; **не влияет** на динамический выбор Синтезатора — только при сбое (LLM зависла / нечитаемый ответ).
3. **Потолок клише (UPD3 №3):** ✅ хардкод 20 снять; **дефолт 200**; лимит **регулируемый** — числовое поле ввода в карточке Анти-клише.
4. **Источники traits (UPD3 №4):** ✅ не галлюцинировать; **Empty State** в UI (как работает эволюция/накопление парадигм и черт из self-фактов, почему данных нет); **обязательно** проверить, что извлечение фактов/парадигм о **пользователях** работает без сбоев.
5. **Retention диска (UPD3 №5):** ✅ **строго 1 последний бэкап БД**; JSONL — **6 мес**, НО дампы/архивы **истории сообщений — удалять запрещено** (бесконечное хранение); прочие JSONL (досье, телеметрия, мусор) — резать жёстко; **логи — 7 дней**.
6. **BYOK ключа изображений (UPD3 №6):** ✅ **согласовано** — сохранять через безопасный эндпоинт `/api/config/keys/own`.
7. **Embeddings `requests` (UPD3 №7):** ✅ **ЗАДАЧА ОТМЕНЕНА** — владелец сам заменит ключ на нативный google-эмбеддинг; код embeddings **не трогаем**.
8. **Модели картинок / универсальность Саммари (UPD3 №8):** ✅ **никакой** карты `модель → параметры`; payload строго по стандарту (любой OpenAI-совместимый провайдер), убрать `size`; обложка обязана генерироваться с **любой** моделью; добавить кнопку **«Проверить подключение»** (тестовый промпт → тост с успехом или **сырым текстом ошибки**).
9. **Клик по факту из ленты досье (UPD3 №9):** ✅ согласовано — переключать контекст на чат факта и открывать модалку Досье (*относится к F4 `dossier-live-feed` — уже в объёме*).

**Гейты раунда:** **Step 1 @PM (UPD3/UPD4/UPD5) — выполнен:** решения владельца внесены в `tasks.md` фич и backlog (UPD3 9 гейтов, UPD4 F13–F18, **UPD5 F16-доработки + новая F19**; **UPD5-critical — новый бюджетный кластер F20–F23 (T-2353…T-2379), 6 открытых вопросов G**; **UPD6 — новая F24 `providers-fullscreen-advanced-fix-round1024` (T-2380…T-2387, TMA/fullscreen, AMEND 10.10), 4 открытых вопроса O**); **Step 2 @Architect** (`spec.md` + ADR: новые + **AMEND/RE-OPEN** перечисленных выше; Accepted — до реализации; **UPD5: новая F19 — ожидаемо ADR-1024-20**) → @Builder → @Reviewer → **Step 6 @Scanner** (независимый re-audit) → **Step 9 @DevOps** (F9: аудит/очистка/отчёт + retention; F1/F7/F8/F12: live-проверки; F4/F10/F11: приёмка в TMA; **F16/F19: live-проверки выжимка/транскрипт/age-restricted**; **F20/F21/F22: live-аудит бюджетов целевого чата** — сохранение значений, работа тумблера ON/OFF, отсутствие заглушки; **F24: live-приёмка в TMA** — advanced на «Провайдерах» переживают fullscreen вход/выход) → **Step 8 @PM — ✅ ВЫПОЛНЕН (20.09.2026)** (архив всех 24 фич-папок `plans/features/*-round1024` → `plans/archive/` + 3 сквозных arch-дока). **`spec.md`/`ADR` PM не создаёт.**
**Отчёт-обязательство (ТЗ п.7.3):** справка «причина роста +6 ГБ / что удалено / прогноз на месяц» — в `plans/metrics.md` по завершении F9.
**Не входит в раунд (не переоткрывать):** техдолг 10.23 (**L1–L4**, **I1**, **I3–I4**), 6 существующих backlog-папок (`admin-debug-webview`, `config-read-path-audit`, `frontend-admin-bugfixes`, `post-deploy-admin-minors`, `scam-incident-security-followup`, `user-aliases-admin`). **Исключение (UPD5):** техдолг 10.23 **I2** (устаревший комментарий счётчика инструментов) — **закрывается** в F19 (и подготавливается в F14).

## Раунд 10.23 (19.09.2026): Adaptive System 2, Token Analytics, Dynamic Anti-Cliche Cache & Image Generation — 9 фич — ✅ COMPLETED + MERGED (готов к деплою, Step 9) (@Reviewer Approved — 9/9 · @Scanner 0 Critical / 0 High (2 Medium закрыты follow-up) · @PM Step 8 архивация · @Architect Merge **§49** · HEAD **`8dadbe3`**)

**✅ ИТОГ 10.23 (19.09.2026):** эпик **COMPLETED + MERGED** (готов к деплою, Step 9 @DevOps). Baseline HEAD **`731a845`** → финальный HEAD **`8dadbe3`**.
Реализовано **9 фич (F1–F9) / 9 ADR (ADR-1023-1…-9, Accepted/реализованы) / задачи T-2097…T-2186 (90)**.
@Reviewer — **Approved по всем 9 фичам**; @Scanner (независимый re-audit, `plans/reports/round1023_scanner_audit.md`) — **0 Critical / 0 High**; 2 Medium (**M1** — телеметрия изображений теряла родительский `correlation_id`, **M2** — `response_mode` утекал в user-content Stage-2) **закрыты follow-up-коммитом** (helper `stage2_payload`, проброс `correlation_id`, +6 регресс-тестов); открыто **4 Low (L1–L4) + 4 Info (I1–I4)** — вынесены в техдолг ниже.
Полный **pytest — 7424 passed / 0 failed**; JS-гейт (`node --check web/app.js`) — OK. Архитектура — `plans/ARCHITECTURE.md` **§49** (итог/ADR-карта, @Architect Merge).
**Геометрия (по @Scanner):** каталог **REGISTRY 457** (Δ+18: F2 +2, F5 +5, F6 +1, F8 +10), Settings **416**, GROUPS **96**, `_TAB_BY_GROUP` **94**; пин-тесты `test_param_catalog`/`test_frontend_tab_mapping` обновлены в тех же коммитах; **SQLite `user_version=12` (Δ DDL = 0** — новые таблицы только в PG: `anticliche_cache`, `llm_usage_events`, `llm_model_prices`); канон-миграции info **v4→v5** (`INFO_CANON_VERSION=5`) и guide **v1→v2** (`GUIDE_CANON_VERSION=2`) идемпотентны; порядок роутеров `bot.py` не сдвинут (только DI-kwargs + воркер вне гейта).
**Δ каталога — санкционирован** (F2/F5/F6/F8); env-only kill-switch `ClassVar` **default ON**: `SMART_VERBALIZER_MODES_ENABLED` (F3), `DYNAMIC_ANTICLICHE_ENABLED` (F4), `IMAGE_GENERATION_ENABLED` (F5), `SUMMARY_COVER_ARTICLE_ENABLED` (F6), `TOKEN_ANALYTICS_ENABLED` (F7). Поэтапная раскатка internal→10%→50%→100% **не требуется** — флаги дают kill-switch; откат — флаг OFF / `git revert` (+ обратная канон-миграция F1–F4/F6, DDL-retention F4/F7, обратный снапшот v4 для F9).

**Архив (Step 8 @PM):** все **9 фич-папок** перенесены `plans/features/<feature>-round1023/` → **`plans/archive/<feature>-round1023/`** (4 трекнутых — `git mv`; 5 untracked — обычный move; сохранены `spec.md` + `tasks.md` + **`ADR-1023-N.md`**); карта решений **`plans/features/round1023-architecture.md`** → **`plans/archive/round1023-architecture.md`**. R18-скан папок — **чисто** (приватных ключей/SSH/`sk-`/`ghp_`/`Bearer`-токенов и assignment-маркеров `password`/`api_key`/`secret`/`token` нет; длинные строки — только пути `plans/archive/...`). В `plans/features/` остались только 6 ранее существовавших backlog-папок; пустых/осиротевших папок нет. Ссылок в `tests/` на перемещённые пути **нет** (упоминания `round1023` — только имена тестовых файлов/JS-тестов и докстринги).

Эпик по ТЗ владельца (`plans/current_task.md`, untracked, `.gitignore`): сделать бота умнее (adaptive System 2 с 3 режимами общения), научить генерировать изображения, прозрачно репортить расходы токенов, автоматически обновлять фильтры анти-клише и глубоко понимать ветки диалогов. **Step 1 @PM: 9 фич-папок в `plans/features/`, задачи T-2097…T-2182 (86); `spec.md`/`ADR` — Step 2 @Architect (PM не создаёт).** Секреты из ТЗ (SSH/API-ключ) — **не цитировать, не коммитить** (R17/R18); ключ изображений упоминается только как «ключ из ТЗ current_task.md».

**Baseline (Step 0 @Memory):** HEAD **`731a845`** (master, чистое дерево); прошлый эпик round1022 — COMPLETED+DEPLOYED+ARCHIVED; pytest **6962 passed / 0 failed**; SQLite **user_version=12**; APP_VERSION **2.57.0**; каталог **439/409/414/92/90/20**; прод **`a8a6437`** active.

| # | Фича (папка) | ТЗ | Тип | Приоритет | Зависит от | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `target-message-marking-round1023` — маркировка сообщения-триггера `<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` в обоих рендерерах истории + правило в промпты Синтезаторов (сообщение физически не вырезается) | Ядро: маркировка | backend/LLM + канон | **P0** | — | T-2097…T-2106 (10) |
| **F2** | `factcheck-deep-context-round1023` — двунаправленное окно before/after + граф реплаев для Фактчека + UI-параметр N + промпт-правило обязательного веб-поиска | Ядро: глубокий контекст | backend + канон + UI-параметр | **P0** | F1 | T-2107…T-2115 (9) |
| **F3** | `verbalizer-response-modes-round1023` — роутер `response_mode` (casual/serious/deep_research) в Stage-1 + 3 промпта Вербализатора, типографика (только `-`/`""`) | Умный Вербализатор | backend/LLM + канон | **P0** | F1, F2 | T-2116…T-2125 (10) |
| **F4** | `dynamic-anticliche-cache-round1023` — недельный воркер (Wikipedia/GitHub → LLM → ~20 паттернов в кэш БД); динамический список питает **детектор** (не scrubber); фикс S10.22-4b | Dynamic Anti-Cliche | backend/worker/DDL + канон | P1 | F3 | T-2126…T-2135 (10) |
| **F5** | `image-generation-tool-round1023` — инструмент `generate_image` (ключевики + tool-calling), провайдер Pollinations (GET-режим), блок image в «Провайдеры» + тумблер «Модули», вызов через `worker_budget`; секрет — только env/PG | Генерация изображений | backend/tool/DDL + UI | P1 | F2 (ступень каталога) | T-2136…T-2146 (11) |
| **F6** | `summary-cover-rich-article-round1023` — визуальный промпт (EN ≤300) + «Стиль обложки» + доставка Article `sendRichMessage` + тихий фолбэк на текст | Изображения: Саммари | backend/LLM + канон + egress + UI | P1 | F5, F4, F1 | T-2147…T-2156 (10) |
| **F7** | `token-analytics-dashboard-round1023` — DDL `module/step/input/output/cost_usd/timestamp` + таблица цен + сквозной correlation-id (Stage-1/2/tool-loop) + Flow-node и графики день/неделя/месяц | Аналитика: Token Metrics | backend/DDL + UI | P1 | — (backend); UI после F5 | T-2157…T-2166 (10) |
| **F8** | `ui-verbilizer-tabs-round1023` — разделение карточек на Синтезатор/Вербализатор, Tabs `Casual`/`Serious`/`Deep Research`, блок мониторинга `dynamic_cliche_list` (дата/форс/ручное редактирование) | UI: Промпты System 2&Cliches | каталог + UI + API | P1 | F3, F4, F5 | T-2167…T-2175 (9) |
| **F9** | `help-ui-v5-round1023` — Справка v4→v5: умный Вербализатор, System 2, анти-клише, команды изображений (стиль blockquote/h1/h2 сохранён) | UI: Справка | код-канон + PG-миграция | P2 | F3, F4, F5/F6, F7 | T-2176…T-2182 (7) |

**Порядок исполнения:** `F1 → F2 → [F3 (канон) ∥ F5 (после F2, параллельно F3)] → F4 → F6 → F7 → F8 → F9`.
Строго последовательны (общий канон-контур + ступени файлов): **F1 → F2 → F3 → F4 → F6 → F8 → F9**. Параллелизуемы: **F5** (стартует после ступени `param_catalog` от F2, идёт одновременно с канон-цепочкой F3/F4 — другие файлы) и **F7-backend** (независим, но `web/app.js`/`index.html` делит с F5/F8 → UI-часть F7 встаёт после F5). Обоснование: F1 — база контекста; F2 разделяет с F3 канон/фактчек; F5 — независимый backend/UI, но делит каталог с F2 и web-файлы с F7/F8; F6 опирается на провайдера F5 и канон; F9 — финальная (описывает фактуру всех).

**Канон-атомарность (ADR-1013-3):** `services/prompt_migrations.py` + `plans/docs/canon/**` + `PREV_*`-слепки + тесты — **одним коммитом на фичу**, ступень **F1 → F2 → F3 → F4 → F6**.
**Ступени общих файлов:** `services/param_catalog.py` — F2 → F5 → F8; `web/index.html`/`web/app.js` — F5 → F7 → F8 → F9; `services/system2_handoff.py` — F3 → F6 → F7 (F7 — no-op по коду).
**Эксклюзивы:** `services/summary_xml.py`/`services/canonical_context.py` (F1); `handlers/factcheck.py`/`services/factcheck_prompts.py` (F2); `services/negative_constraints.py` + новый `services/anticliche_worker.py` (F4); `services/tool_schemas.py`/`services/image_generation.py` (F5); `services/summary_generator.py`/`services/summary_prompts.py`/`services/telegram_send.py` (F6); `services/info_service.py`/`info_text.md` (F9).

**Топ-риски (полные списки — `tasks.md` каждой фичи):** утечка секрета изображений в git/логи (**Critical, F5** — только env/PG, тест «нет plaintext»); третий LLM-вызов ломает `physical-two-call-pipeline` (High, F3 — роутер только в Stage-1); динамический кэш нарушает инвариант «список в коде»/grep-тест или превращается в scrubber (High, F4 — решает @Architect); `deep_research` ломает R11/plain саммари (High, F3); `sendRichMessage`/Article не поддержан версией aiogram (High, F6 — веб-ресёрч обязателен); поломка стриминга/доставки саммари (High, F6); байт-эталоны обоих рендереров истории (High, F1); неверная/устаревшая интеграция Pollinations (High, F5 — обязательный веб-ресёрч); рост контекста/стоимости окна фактчека (Medium, F2); изменение каталога ломает `test_param_catalog` и freeze-меню (High/Medium, F8); непрозрачный correlation-id в tool-loop (Medium, F7); секреты в отчётах (R17/R18, все фичи).

**Активация / раскатка:** новых каталоговых флагов-рубильников — env-only `ClassVar` (**default ON**, вне `param_catalog`): `SMART_VERBALIZER_MODES_ENABLED` (F3), `DYNAMIC_ANTICLICHE_ENABLED` (F4), `IMAGE_GENERATION_ENABLED` (F5, + каталоговый тумблер модуля), `SUMMARY_COVER_ARTICLE_ENABLED` (F6), `TOKEN_ANALYTICS_ENABLED` (F7). F2 — поведенческий фикс (Δ каталога — только параметры окна). F1/F9 — без флага. Осознанный **Δ каталога** — в F5 (группы изображений + модуль) и F8 (ключи stage-1/2 + режимы + блок клише); фиксируется в spec. Поэтапная раскатка internal→10%→50%→100% **не требуется** (прецедент 10.21/10.22) — флаги дают kill-switch; откат — флаг OFF / `git revert` (+ обратная канон-миграция для F1–F4/F6, DDL-retention для F4/F7, обратный снапшот v4 для F9).

**Гейты раунда (сквозные, вне фич):** **Step 2 @Architect** (`spec.md` + `ADR-1023-1…-9`, Accepted, до реализации) → реализация @Builder → @Reviewer → **Step 6 @Scanner** (независимый re-audit) → **Step 9 @DevOps** (F5/F6: env-ключ без вывода значения + сид; F9: идемпотентная PG-миграция v4→v5; живые приёмки) → **Step 8 @PM** (✅ **выполнен 19.09**: архив `plans/features/*-round1023` → `plans/archive/`). **`spec.md`/`ADR` PM не создаёт — Step 2.**

**Остаточный техдолг 10.23 (Low/Info, не блокеры — источник `plans/reports/round1023_scanner_audit.md`):** **L1** (Low, F5 / ADR-1023-5 Open Question №1) — `image_calls` ведёт отдельный счётчик `used`, но лимит берётся тот же, что у `llm_calls` → чат с лимитом 60 может получить до 60 LLM-вызовов **плюс** до 60 генераций изображений; требуется подтвердить/уточнить семантику лимита у владельца (при общем капе — считать `llm_calls + image_calls` против одного лимита); **L2** (Low, F6) — `_strip_safe_html` применяется безусловно и затирает инлайновые `<b>/<i>` в rich-канале (блочные теги не трогаются) — применять strip только при канале `plain`; **L3** (Low, F5) — `_download_bytes` качает управляемый провайдером URL без проверки хоста/схемы и без стримингового лимита (`max_bytes` проверяется уже после полной загрузки в память); риск низкий (URL admin-only), желательны стрим с лимитом и/или whitelist хоста; **L4** (Low, F2) — одноразовая миграция `factcheck_context_messages` при уже заданном владельцем `before` пишет WARNING «before уже настроен — НЕ трогаем» на каждом старте (идемпотентность соблюдена, лог-шум безвредный); **I1** (Info, F2) — `thread_chain` при `depth=0` всё равно возвращает 1 ход (`max(1, depth)`); **I2** (Info, F5) — устаревший комментарий «итоговый tool-сет — 7 инструментов» в `services/tool_schemas.py` (фактически 9); doc-only; **I3** (Info) — fallback-путь `SYSTEM2_*` может дать 3-й физический LLM-вызов (Stage-1 → пустой/невалидный Stage-2 → одиночный путь); инвариант «ровно 2» относится к штатному пути, analytics пишет `step=single`; **I4** (Info, F5) — `send_photo` не покрыт регэкспом egress-сканера (`test_outgoing_guard_round1022._SEND_RE`); точка защищена «договором», а не тестом.

**Не входит в раунд (закрыто / отложено, не переоткрывать):** остаточные 10.21 — S10.21-8, N10.21-1/-2, 4 Info S10.21-10…13; техдолг 10.22 — F8 vec-слой, F8 stale-lock TTL, R7 ADR-1022-1 (принят); 6 существующих backlog-папок (`admin-debug-webview`, `config-read-path-audit`, `frontend-admin-bugfixes`, `post-deploy-admin-minors`, `scam-incident-security-followup`, `user-aliases-admin`) — не трогаются. **S10.22-4b** — ✅ закрыт в F4 (анти-клише); открытый техдолг 10.23 (**L1–L4**, **I1–I4**) — в блоке выше.

## Раунд 10.22 (UPD3, 18.09.2026): боевой ребилд досье целевого чата (вариант «а», окно 180 дней + confirmed-cleanup с JSONL-архивом) + фикс словаря алиасов (UI) + True System 2 Pipeline (2 независимых вызова LLM, validator-loop вместо хардкода клише) + regex-предохранитель отправки + актуализация Справки + **новая P0 UI-фича «Пересборка Досье» (async + прогресс + отмена с rollback)** — 8 фич — ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН (19.09.2026 · @Reviewer Approved iter3 · @Scanner re-audit 0 C/0 H/0 M/0 L (1 Info) · @PM Step 8 · @Architect Merge §48 · @DevOps Step 9 деплой)

**✅ ИТОГ 10.22 (19.09.2026):** эпик **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН**. **✅ DEPLOY (Step 9 @DevOps, 19.09.2026):** коммиты **`2d153b5`** (feat: True System 2 Pipeline) + **`a8a6437`** (docs/plans: архивация 8 фич + Merge §48 + Scanner re-audit) → push `acd9311..a8a6437`, HEAD **`a8a6437`**; прод `/var/www/admin_bot` → **`a8a6437`**; `systemctl` **active**; `/api/health` + `/healthz` = **200**; SQLite `user_version=12` (Δ DDL=0); `INFO_CANON_VERSION=4`; env-флаги default ON (`SYSTEM2_*`, `TELEGRAM_SEND_GUARD_ENABLED`, `DOSSIER_REBUILD_UI_ENABLED`). **Боевой прогон F1** (чат `-1002661910336`, окно 4320ч): `scanned=451 cleaned_facts=441 protected_belief_sources=10 rebuilt=2 window_hours_used=4320 backup=yes` — confirmed-факты 451→10, portraits 0→12, memes 0→2, beliefs 71/41 и nodes/edges/overrides без изменений, `smart_messages` не тронуты (+живой трафик); JSONL-архив 441 строка + авто-бэкап. Детали — `plans/metrics.md` (раздел «Детали раунда 10.22»); KG `release-round1022`.
Реализовано **8 фич (F1–F8) / 8 ADR (ADR-1022-1…8, Accepted/реализованы) / задачи T-2019…T-2096 (78)**. @Reviewer — **Approved** (итерация 3);
@Scanner (первичный скан: 2 Medium + 4 Low + 3 Info → пост-скан фиксы) → **re-audit: 0 Critical / 0 High / 0 Medium / 0 Low открыто** (1 Info **S10.22-4b**);
полный **pytest — 6962 passed / 0 failed**; JS-гейты (`node --check web/app.js`, `ALIASES-UNIT-OK`, `DOSSIER-REBUILD-UNIT-OK`, help) — зелёные; `git diff --check` — чисто (только LF/CRLF).
**Геометрия:** каталог **439/409/414/92/90/20** (**Δ=0**); **SQLite v12** (**Δ DDL = 0**); порядок роутеров `bot.py` не сдвинут (только DI-kwargs). Архитектура — `plans/ARCHITECTURE.md` **§48** (итог/ADR-карта); отчёт @Scanner — `plans/reports/round1022_scanner_audit.md`.

**Архив (Step 8 @PM):** все **8 фич-папок** (`git add` → `git mv`) перенесены `plans/features/<feature>-round1022/` → **`plans/archive/<feature>-round1022/`** (сохранены `spec.md` + `tasks.md` + **`ADR-1022-N.md`**); карта решений **`plans/features/round1022-human-gate-map.md`** → **`plans/archive/round1022-human-gate-map.md`**. R18-скан папок — **чисто** (секретов нет; SSH-значения не цитировались). В `plans/features/` остались только 6 ранее существовавших backlog-папок; пустых/осиротевших папок нет. Ссылок в `tests/` на перемещённые пути **нет** (упоминания `round1022` — только имена самих тестовых файлов/папок в комментариях и докстрингах, безопасны).

**Решения UPD3 (Human Gate, закрыты владельцем):** F1/F8 — **вариант «а»**, окно **180 дней**; **confirmed-cleanup** с предварительным **JSONL-архивом**; F3–F5 — физические **2 вызова** LLM (Аналитик/Синтезатор/Редактор → Вербализатор/Рассказчик); F6 — **validator-loop** (браковка клише + до 2 ретраев Вербализатору) **вместо хардкод-`string.replace`**, scrubber тихо режет только `<thought>`/`fact:\d+`; F8 — **async UI** (job-store + прогресс X/Y + persistence при reopen + «Отмена» с **rollback** из стартового снапшота); F2 — ремонт рендера JSON-объекта алиасов; F7 — Справка v4 (канон `<h1>×1` / `<h2>×10` / `<blockquote>×21`).

**Инварианты:** **`imported-history-immutable`** (сырая история `smart_messages` не удаляется; `RAW_HISTORY_TABLES`/`assert_derived_table`/`_guarded_delete`) и **`manual-overrides-immutable`** (`persona_dossier_overrides` не перезаписываются; writer пишет только производные `graph_facts`). **Δ каталога = 0**; env-only `ClassVar`-рубильники (вне `param_catalog`, **default ON**): `SYSTEM2_{FACTCHECK,SUMMARY,DIRECT,VALIDATOR_LOOP}_ENABLED`, `TELEGRAM_SEND_GUARD_ENABLED`, `DOSSIER_REBUILD_UI_ENABLED` (+`DOSSIER_REBUILD_CHUNK_SIZE`/`LOCK_TTL_SECONDS`); поэтапная раскатка internal→10%→50%→100% **не требуется** (kill-switch OFF / `git revert` + обратная канон-миграция для F3–F6).

**Остаточный техдолг (не блокеры, follow-up):** **S10.22-4b** (Info: детектор клише `as_ai` ложно срабатывает при запятой — «Он, как искусственный интеллект…»; редкая лишняя регенерация, не блокер); **F8 vec-слой не восстанавливается** (best-effort, embeddings не в снапшоте — задокументировано); **R7 ADR-1022-1 — принят владельцем** (F1/F8 удаляют валидные `confirmed`-факты без swap-порядка «извлечь→заменить»; компенсация — авто-бэкап `memory_rebuild_*.db` + JSONL-архив `memory_generated_confirmed_*.jsonl` + стартовый снапшот F8); **F8 stale-lock TTL** (`DOSSIER_REBUILD_LOCK_TTL_SECONDS`, 6ч — «stale takeover», lock не снимается при рестарте); прочее accepted (snapshot-missing при kill во время записи, single-writer job-store, caption/media вне regex-скана, остаток S10.22-3).

**✅ @DevOps (Step 9, выполнен 19.09.2026):** **T-2020/2026/2027** (F1: read-only диагноз прода + бэкап БД + **боевой прогон пересборки `-1002661910336`** + post-check неизменности `smart_messages` + верификация counts в БД/UI) — **выполнено** (`scanned=451 cleaned_facts=441 protected_belief_sources=10 rebuilt=2 window_hours_used=4320 backup=yes`); **T-2089** (F8: деплой выполнен; ⏸ **живая приёмка** UI-пересборки — прогресс-бар/reopen-persistence/отмена+откат — **остаётся за владельцем**); **T-2069** (F6: деплой выполнен; ⏸ **живая приёмка** ответа без `<thought>`/`fact:\d+`/`msg:\d+` — **за владельцем**).

**ТЗ:** `plans/current_task.md`, секция **UPD2** (строки **170–241**) + **UPD3** (строки **245–271**, решения владельца после Human Gate) + **UPD3 §2** (252–256, новая UI-фича). Подразделы: «Проблема 1» (175–178), «Проблема 2» (180–185), **ЧАСТЬ 1** System 2 (187–218), **ЧАСТЬ 2** Справка (220–238); **UPD3 §1** Досье/факты (247–249), **UPD3 §2** Кнопка пересборки Досье (252–256), **UPD3 §3** предохранитель/validator-loop (259–262), **UPD3 §4** Справка+алиасы (265–267). Файл **untracked** (`.gitignore`), содержит plaintext-SSH-креды → **не коммитить, значения не цитировать** (R17/R18).
**Цель раунда:** (1) получить **реальный результат в БД** — очистить сгенерированный мусор в досье целевого чата `-1002661910336` (**вариант «а», окно 180 дней + confirmed-cleanup + JSONL-архив**); (2) вернуть рендер поля «Словарь алиасов имён» в UI; (3) заменить костыль `<thought>` внутри одного промпта физическим конвейером из **двух независимых вызовов LLM** (Фактчекер, Саммари, Direct Chat), а клише не вырезать хардкодом, а **браковать ответ и возвращать Вербализатору (max 2 ретрая)**; (4) ввести единый regex-предохранитель (тихо режет только `<thought>`/`fact:\d+`) и negative constraints; (5) актуализировать Справку (System 2, транскрипт vs выжимка); (6) **новая UI-фича:** кнопка «Пересобрать досье» с периодом 30/90/180/Всё время, асинхронная задача + прогресс-бар, persistence при reopen, отмена с rollback из стартового бэкапа.
**Baseline (Step 0 @Memory + read-only диагностика прода):** HEAD **`acd9311`**, рабочее дерево чистое (кроме незакоммиченного `plans/MEMORY.md` от Step 10 10.21); pytest **6779 passed / 0 failed**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION 2.57.0; прод **`a923310`** active.
**Проверенные отчёты (Step 0):** `plans/reports/round1021_scanner_audit.md` (10.21: 0 C/0 H/0 M; открыто Low S10.21-8 + N10.21-1/-2 + 4 Info — **не переоткрывать**), `plans/reports/global_map.md` (карта связностей 10.21).

**Диагностика P1 («трусость миграции»):** команда `manage.py memory rebuild-dossiers` **есть** (`manage.py:635-719`, `:944-1020`; движок `services/memory_rebuild.py:400`+), но guard `_memory_scope` (`manage.py:848-869`) блокирует целевой чат без `--chat <id>` + `--allow-target-chat`; на проде `dossier_portrait=0`, `chat_meme=0` → rebuild **ни разу не запускался**. Сырая история защищена `RAW_HISTORY_TABLES`/`assert_derived_table` (`services/memory_rebuild.py:55-82`) — **инвариант сохранить** (ТЗ разрешает снять блокировки «кроме удаления истории сообщений»). Живой прогон: ожидать `database is locked` (12 в логах) и LLM-таймауты (163).
**Диагностика P2 («пропал словарь алиасов»):** данные **целы** — PG `bot_settings` глобально = объект **38 ключей** (обновлён 04.09), per-chat override нет; `GET /api/config` отдаёт 38 ключей всем ролям (`web/api/routes.py:365`). Каталог: `SUMMARY_ALIASES` type `json`, widget `keyvalue` (`services/param_catalog.py:1163-1166`). Причина — **frontend** (рендер widget `keyvalue` для object-value / stale JS-кэш / воспроизведение в TMA): `web/app.js:3544-3551`, `web/app.js:6331-6350`, `web/index.html:528-533/794-798`. **Restore из бэкапа запрещён** — перезапишет свежие данные.

**🔴 РЕШЕНИЯ UPD3 (владелец, 18.09.2026 — Human Gate пройден; фиксируются в backlog, детали — Step 2b @Architect):**
- **UPD3 §1 (В1, Досье/факты):** выбран **вариант «а»**, окно расширено до **последних 180 дней**; жёсткая очистка сгенерированного мусора `graph_facts` со статусом `confirmed` для чата `-1002661910336` с **предварительным сохранением удаляемых строк в JSONL-архив**; **ручные overrides не трогать**; затем двухслойная пересборка по 180-дневному окну. Инварианты `imported-history-immutable`/`manual-overrides-immutable` — сохраняются.
- **UPD3 §2 (новая UI-фича, P0):** кнопка «Пересобрать досье» в меню Досье (период 30/90/180/Всё время), **фоновая задача + прогресс-бар** («обработано X/Y чанков»), **persistence** при reopen мини-аппа (GET статуса, без падений), **«Отмена» с rollback** из стартового бэкапа (не kill процесса). → фича **F8 `dossier-rebuild-async-ui-round1022`**, T-2077…T-2089.
- **UPD3 §3 (В3, System 2):** физические **2 вызова** (Аналитик + Вербализатор). **Вето на `string.replace` для клише** (хардкод ломает грамматику). Regex Scrubber тихо режет только технические `<thought>` и `fact:\d+`; при обнаружении запрещённого ИИ-клише — **забраковать весь ответ** и вернуть Вербализатору (**max 2 ретрая**) с системным сообщением «Ты нарушил Negative Constraints… Перепиши полностью». **Уточняет/заменяет** прежнюю трактовку F6 «вырезать клише regex'ом» → **validator-loop**.
- **UPD3 §4 (В4 + Проблема 2):** Справка — строго по регламенту (`<blockquote>`, `<h1>`/`<h2>`, без точек/запятых, транскрипт vs выжимка); алиасы — **починить рендер JSON-объекта на фронте** (данные в БД есть, restore из бэкапа запрещён).
- **НЕ переписывалось в этой итерации:** `spec.md`/`ADR-1022-1…-7` и `tasks.md` фич F1–F7 — детальная переработка под UPD3 — **Step 2b @Architect** (не PM). Для **F8** — создать новый `spec.md` + **`ADR-1022-8`** (`plans/features/dossier-rebuild-async-ui-round1022/`). `plans/current_task.md` — не трогается.

**8 фич (нумерация продолжает 10.21 T-2018 → T-2019…T-2089, 71 задача):**

| # | Фича (папка) | ТЗ | Тип | Приоритет | Зависит от | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `urgent-rebuild-dossiers-target-chat-round1022` — боевой прогон rebuild для `-1002661910336`, снятие операционных guard'ов (кроме сырой истории), надёжность при locked/таймаутах, отчёт counts | Пробл.1 | data-migration/CLI + ops | **P0** | — | T-2019…T-2027 (9) |
| **F2** | `urgent-summary-aliases-ui-round1022` — диагноз frontend (object-value widget/кэш), фикс binding, регресс-тест, проверка в TMA | Пробл.2 | frontend `web/**` | **P0** | — | T-2028…T-2034 (7) |
| **F3** | `system2-factcheck-two-call-round1022` — 2 вызова (Аналитик JSON → Вербализатор), AMENDS 10.21-подход с `<thought>` | Ч.1 п.1 | backend/LLM + канон | **P0** | F6 | T-2035…T-2043 (9) |
| **F4** | `system2-summary-two-call-round1022` — Редактор (чистая Markdown-выжимка, отсев нерелевантной истории) → Рассказчик | Ч.1 п.2 | backend/LLM + канон | **P0** | F6 | T-2044…T-2052 (9) |
| **F5** | `system2-direct-chat-two-call-round1022` — Синтезатор тулов (каша логов → чистая JSON-справка) → Вербализатор | Ч.1 п.3 | backend/LLM + канон | **P0** | F6 | T-2053…T-2061 (9) |
| **F6** | `telegram-send-regex-guard-round1022` — negative constraints против клише + единый chokepoint: scrubber тихо режет `<thought>`/`fact:\d+`, а клише — **браковка ответа + validator-loop (max 2 ретрая)** (UPD3 §3, вместо `string.replace`) | Ч.1 п.4 | канон + backend | **P0** | — | T-2062…T-2069 (8) |
| **F7** | `help-ui-system2-round1022` — переписать Справку (`<blockquote>`/`<h1>`/`<h2>`, транскрипт vs выжимка, убрать п.11, блок «Как бот думает (System 2)»), бамп канон-версии | Ч.2 | контент/UI (код-канон) + `web/**` | P1 | F3/F4/F5 (Step 2), F6, F8 (`web/**` ступень) | T-2070…T-2076 (7) |
| **F8** | `dossier-rebuild-async-ui-round1022` — **новая P0 UI-фича**: кнопка «Пересобрать досье» + период 30/90/180/Всё время, фоновая задача (job-store) + прогресс «X/Y чанков», persistence при reopen, «Отмена» с rollback из стартового бэкапа; интеграция с F1 (180 дней + confirmed-cleanup + JSONL) | **UPD3 §2** (252–256) + **UPD3 §1** (247–249) | backend (job-store/API) + frontend `web/**` + data-safety/rollback | **P0** | **F1** (движок/окно/cleanup), F2 (ступень `web/**`) | T-2077…T-2089 (13) |

**Порядок исполнения:** **[F1 ∥ F2 ∥ F6] → [F8 ∥ (F3 → F4 → F5)] → F7**.
Обоснование: F1 и F2 не пересекаются по файлам (`manage.py`/`memory_rebuild.py` vs `web/**`) и несут боевой/регрессионный P0-эффект → стартуют сразу; F6 даёт общий канон-блок negative constraints (`services/prompt_style_blocks.py`) и chokepoint-предохранитель, на которые опираются все Вербализаторы/Рассказчики → идёт **до** F3/F4/F5; **F8 строится на движке F1** (`services/memory_rebuild.py` + `LoreWorker.rebuild_dossier_for_chat`) и на **ступени `web/**` после F2** → стартует после вливания F1 и web-правок F2, **параллельно** канон-цепочке; F3/F4/F5 делят канон-контур (`services/prompt_migrations.py` + `plans/docs/canon/**`) и потому **сериализуются** (F3 → F4 → F5); F7 — последняя (и текст про System 2, и ступень `web/**`).
**Зависимости:** F3/F4/F5 → F6 (negative constraints + validator-loop/chokepoint); **F8 → F1** (движок пересборки + окно 180 дней + confirmed-cleanup/JSONL) и **F2** (ступень `web/**`); F7 → F3/F4/F5 (описание пайплайна), F6 (validator-loop/scrubber) и F8 (ступень `web/**`). F1, F2, F6 — независимы.
**Пересечения файлов / ступени вливания:**
- `services/prompt_style_blocks.py` — **эксклюзив F6 первым**; далее только чтение F3/F4/F5.
- `services/prompt_migrations.py` + `plans/docs/canon/**` — **ступень F6 → F3 → F4 → F5** (канон-атомарность ADR-1013-3: код + эталон + слепки + тесты одним коммитом).
- `services/reply_postprocess.py` — эксклюзив F6 (единый chokepoint: scrubber `<thought>`/`fact:\d+` + **validator-loop/браковка клише**), чтение F3/F4/F5.
- `services/factcheck_service.py`/`factcheck_prompts.py` — эксклюзив F3; `services/summary_generator.py`/`summary_prompts.py` — эксклюзив F4; `services/direct_chat_service.py`/`chat_prompts.py` — эксклюзив F5; `services/tool_loop.py` — read.
- `web/index.html`/`web/app.js` — **ступень F2 → F8 → F7** (KV-редактор алиасов → кнопка/прогресс пересборки Досье → правки Справки).
- `manage.py`/`services/memory_rebuild.py`/`services/lore_worker.py` — эксклюзив F1; F8 — **читает** их после вливания F1 (тот же движок, окно 180 дней, confirmed-cleanup).
- **F8 (новые файлы/зоны):** job-store фоновых задач (новый модуль `services/**`, ср. паттерн `services/progress_reporter.py`), rebuild-эндпоинты в `web/api/chat_lore.py` (или новый `web/api/*`); `web/app.js` (блок Досье `:2739-2795`), `web/index.html` (модалка Досье `:2667-2739`) — общие с F2/F7, ступень выше.
- `services/info_service.py` + `info_text.md` (корень) — эксклюзив F7.
**Риски (полные списки — `tasks.md` каждой фичи):** удаление сырой истории при снятии guard'а (R1/F1) — инвариант `RAW_HISTORY_TABLES` сохранить; `database is locked` (12) и LLM-таймауты (163) (R2/R3/F1); over-delete досье при неполном ростере (R5/F1, ср. N10.21-2); **confirmed-cleanup заденет валидные/ручные данные (R1/F1+F8)** — предварительный JSONL-архив, `overrides` неприкосновенны; restore из бэкапа затрёт свежие данные (R1/F2); **rollback F8 затрёт свежие/ручные данные (R1/F8)** — откат только производных из стартового снапшота; **потеря фонового job при restart/краше (R2/F8)**; **тяжёлый расчёт прогресса на БД ~2M строк (R3/F8)**; **некооперативная отмена оставит частичный результат (R4/F8)**; **гонки/reopen во фронте (R5/F8)**; **конфликт с CLI-прогоном F1 (R6/F8)**; ложные срабатывания regex-предохранителя (R1/F6) и неполный охват точек отправки (R2/F6); **validator-loop — срыв/зацикливание ретраев (F3-F6)** — жёсткий лимит max 2 ретрая + fail-open; невалидный JSON двухслойных вызовов и двойная стоимость/латентность (R1/R2/F3-F5); поломка стриминга/деgraded/`lore_compiled` (R1/F4, R1/F5); канон-атомарность (R4/F3-F5, R4/F6); рассинхрон/санитайзер Справки (R1/R2/F7); секреты в отчётах (R17/R18, все фичи).
**Активация / раскатка:** новых **каталоговых** флагов нет (**Δ каталога = 0**). System 2 и предохранитель — env-only kill-switch `ClassVar` (вне `param_catalog`), **default ON**: `SYSTEM2_FACTCHECK_ENABLED`, `SYSTEM2_SUMMARY_ENABLED`, `SYSTEM2_DIRECT_ENABLED`, `TELEGRAM_SEND_GUARD_ENABLED` (внутри — scrubber `<thought>`/`fact:\d+` + validator-loop/браковка клише, UPD3 §3). **F8** — env-only kill-switch `DOSSIER_REBUILD_UI_ENABLED` (**default ON**, Δ каталога = 0): OFF отключает кнопку/API пересборки. Поэтапная раскатка internal→10%→50%→100% **не требуется** (прецедент 10.21/10.22) — флаги позволяют gradual/kill-switch; F1 — CLI-параметр без флага; F2/F7 — без флага. Откат — kill-switch OFF / `git revert` (+ обратная канон-миграция для F3–F6; для F8 DB-артефакты обратимы: rollback-снапшот + JSONL-архив).
**Гейты раунда (сквозные, вне фич):** **Step 2b @Architect** (переработать `spec.md`/`ADR-1022-1…-7` + `tasks.md` фич F1–F7 под **UPD3**; создать `spec.md` + **`ADR-1022-8`** для F8; ADR **Accepted**) → реализация → @Reviewer → **Step 6 @Scanner** (независимый re-audit) → **Step 9 @DevOps** (F1: бэкап + боевой прогон + post-check неизменности `smart_messages`; **F8: живая приёмка кнопки/прогресса/reopen-persistence/отмены с rollback + post-check неизменности сырой истории и overrides**; F2/F7: cache-bust + приёмка TMA) → **Step 8 @PM** (архив `plans/features/*-round1022` → `plans/archive/`). **`spec.md`/`ADR` PM не создаёт — это Step 2/2b.**
**Не входит в раунд (закрыто / отложено, не переоткрывать):** остаточные 10.21 — S10.21-8 (vec парадигм CLI), N10.21-1 (тест-покрытие), N10.21-2 (бинарный `roster_incomplete`), 4 Info (S10.21-10…13); 6 существующих backlog-папок (`admin-debug-webview`, `config-read-path-audit`, `frontend-admin-bugfixes`, `post-deploy-admin-minors`, `scam-incident-security-followup`, `user-aliases-admin`) — не трогаются.

## Раунд 10.21 (18.09.2026): System 2 Reasoning — многослойная экстракция памяти, строгий grounding фактчекера + CoVe, де-роботизация, пороги Парадигм, ребилд/санитария памяти, автономный UI-аудит — 6 фич — ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН (18.09.2026 · @Reviewer Approved iter3 · @Scanner re-audit 0 C/0 H/0 M · @PM Step 8 · @Architect Merge **§47** · @DevOps Step 9 деплой)

**✅ ИТОГ 10.21 (18.09.2026):** эпик **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН**.
**✅ DEPLOY (Step 9 @DevOps, 18.09.2026):** коммиты **`29fc638`** (feat) + **`a923310`** (docs/plans: архивация + §47 + отчёты) → push `21cd54c..a923310`; прод `/var/www/admin_bot` fast-forward `ec93c3d..a923310`; `systemctl` **active** (PID **3023258**); включены `DREAM_ENABLED=true` / `DEEP_SLEEP_ENABLED=true` / `BELIEF_DECAY_ENABLED=true`; `/api/health` + `/healthz` = **200**; SQLite `user_version=12`; канон-миграция промптов идемпотентна (8 ключей). Детали — `plans/metrics.md` (раздел «Детали раунда 10.21»); KG `release-round1021`.
Реализовано **6 фич** (F1–F6), **ADR-1021-1…-6**, задачи **T-1943…T-2018 (76)**. @Reviewer — **Approved** (итерация 3);
@Scanner (re-audit, `plans/reports/round1021_scanner_audit.md`) — **0 Critical / 0 High / 0 Medium** (открыто 1 Low **S10.21-8** + **N10.21-1/-2** + **4 Info**); полный
**pytest — 6779 passed / 0 failed**; **каталог 439/409/414/92/90/20 (Δ=0)**; **SQLite v12 (Δ DDL = 0)**; JS-гейты (`node --check web/app.js`, `JS-UNIT-OK`, `VUE-MOUNT-OK`) чистые; `git diff --check` clean.
Архитектура — `plans/ARCHITECTURE.md` **§47** (итог/ADR-карта).

**Архив (Step 8 @PM):** все **6 фич-папок** перенесены `plans/features/<feature>-round1021/` → **`plans/archive/<feature>-round1021/`**
(`git mv`; сохранены `spec.md` + `tasks.md` + `ADR-1021-N.md`, а также `ROLLBACK.md` (F3) и `audit.md` (F4)). R18-скан папок — **чисто** (секретов нет).
В `plans/features/` остались только 6 ранее существовавших backlog-папок; пустых/осиротевших папок нет.

**Инварианты:** **`imported-history-immutable`** (сырая история `smart_messages` не удаляется) и **`manual-overrides-immutable`**
(`persona_dossier_overrides` не перезаписываются; writer пишет только производные `graph_facts`). **env-only рубильники** вне каталога (`ClassVar`, Δ=0):
**`MULTILAYER_EXTRACTION_ENABLED`** (**default ON**) — аварийный kill-switch F1; **`DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED`** (**default OFF**) —
активация PG-миграции порогов `migrate_deep_sleep_thresholds` (cooldown 20→6 ч) оператором при ветке B/C.

**Парадигмы (T-1972; `plans/reports/round1021_paradigm_audit.md`):** корень мёртвого мета-слоя — **выключенные** `DREAM_ENABLED` / `DEEP_SLEEP_ENABLED`
(+ `BELIEF_DECAY_ENABLED`), **а не пороги**; санкционированное действие — **включить флаги `memory.dream_enabled` + `flags.deep_sleep_enabled` на деплое**
(per-chat/global), затем при необходимости — ручная консолидация `python manage.py memory consolidate`.

**Resolved / ключевое:** развязка F1 от `IRONY_FILTER_ENABLED` (T-2013: портреты/мемы пишутся при irony OFF, гейтит только kill-switch);
закрыты Medium S10.21-1/-2 и Low S10.21-3…-7/-9.

**Остаточный техдолг (не блокеры, follow-up):** **S10.21-8** (Low: парадигмы CLI без vec-эмбеддинга, `services/memory_maintenance.py:785` — `DreamWorker(memory=None)`);
**N10.21-1** (Low: нет регресс-тестов на `_chat_roster`/`roster_incomplete`/`belief_source`/`initialize_readonly`/пустой Слой Б);
**N10.21-2** (Low: бинарный гард `roster_incomplete` по `independent > 0`); **4 Info** (S10.21-10…13);
**WebView Telegram (Android/Nekogram/iOS) не воспроизводился** (headless ≠ WebView — унаследованное ограничение F6); **IRONY-развязка** — подтвердить в живом прогоне на деплое.

**✅ Пост-архивный фикс теста — РЕШЁН (коммит `29fc638`):** `tests/test_de_robotization_round1021.py` искал
`plans/features/de-robotization-negative-constraints-round1021/ROLLBACK.md` → после архивации доработан **archive-fallback**
(`plans/archive/de-robotization-negative-constraints-round1021/ROLLBACK.md`); тест зелёный (итоговый прогон **6779 passed / 0 failed**).
Прочие упоминания `plans/features/*-round1021` в `tests/` — только комментарии/докстринги, безопасны.

**ТЗ:** `plans/current_task.md` (untracked, .gitignore:70; содержит plaintext SSH-креды → **не коммитить, значения не цитировать**; R17/R18). Части: **ЧАСТЬ 1** (System 2 Reasoning), **ЧАСТЬ 2** (Data Migration), **ЧАСТЬ 3** (UI/UX-аудит).
**Цель эпика:** снять архитектурный потолок наивного RAG и однопроходной генерации: многослойная экстракция памяти (Слой А scratchpad + Слой Б синтезатор), изолированный RAG фактчекера со строгим grounding + Chain-of-Verification, де-роботизация (negative constraints против RLHF-тропов), починка порогов Парадигм/Deep Sleep + консолидация, ребилд/санитария досье и убеждений, автономный браузерный UI-аудит с фиксами.
**Baseline (Step 0 @Memory):** HEAD `21cd54c`; pytest **6574 passed / 0 failed**; SQLite **v12**; каталог **439/409/414/92/90/20**; APP_VERSION 2.57.0; прод `ec93c3d`.
**Предшественники (архив):** `plans/archive/round1020-lore-compiler-rag-refactor/` (T-1866…T-1931), `plans/archive/round1020-ui-rework/` (T-1933…T-1942).
**Follow-up прошлого раунда:** **T-1932** (fallback точки 7 `CONTEXT_POINTS`) — остаётся открытым, в 10.21 не входит.
**Спеки/ADR:** Step 2 @Architect — **ADR-1021-1…-6 `Accepted`** (UPD владельца 18.09.2026: F1/F2/F3 включены по умолчанию; деструктив F5 без обязательного dry-run; tooling F6 Puppeteer→Playwright→честный отказ; **Δ каталога = 0**). `spec.md` PM **не создаёт**.

**Триггер эпика (симптомы деградации):** мусор в досье (Entity Resolution Failure: Тяньаньмэнь/«Кирилл» у Никиты, «инструкции по сокрытию трупа» у Васи); галлюцинации фактчекера (выдуманные теги `[04.2023 | fact:2574]`); мёртвые Парадигмы (мета-слой Deep Sleep пуст); синтетические RLHF-тропы («нет, ты», «ты уже спрашивал»).

**6 фич (нумерация продолжает T-1942 → T-1943…T-2000, 58 задач):**

| # | Фича (папка) | ТЗ | Тип | Приоритет | Зависит от | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `multilayer-memory-extraction-round1021` — Слой А (scratchpad/`<thought>`) + Слой Б (синтезатор), фильтр мусора, entity resolution | Ч.1 Шаг 1 | backend/LLM-память | **P0** | — | T-1943…T-1952 (10) |
| **F2** | `factchecker-grounding-cove-round1021` — строгий grounding (ID/даты только из контекста) + Chain-of-Verification | Ч.1 Шаг 2 | backend/фактчек | **P0** | F1, F3 (канон) | T-1953…T-1961 (9) |
| **F3** | `de-robotization-negative-constraints-round1021` — negative constraints против RLHF-тропов + асимметрия + канон-миграция | Ч.1 Шаг 3 | канон промптов | **P0** | F1, F2 | T-1962…T-1970 (9) |
| **F4** | `paradigm-thresholds-consolidation-round1021` — аудит триггеров Парадигм/Deep Sleep + скрипт Memory Consolidation | Ч.1 Шаг 4 | backend/cognition | P1 | F1, F5 (CLI) | T-1971…T-1979 (9) |
| **F5** | `memory-rebuild-sanitation-round1021` — `manage.py memory rebuild-dossiers` + санитария убеждений/фактов | Ч.2 | data migration/CLI | **P0** | F1, F4 | T-1980…T-1989 (10) |
| **F6** | `ui-audit-puppeteer-round1021` — реальный браузерный E2E-аудит + фиксы + `UI_AUDIT_REPORT.md` | Ч.3 | frontend `web/**` | **P0** | — (параллельно) | T-1990…T-2000 (11) |

**Порядок исполнения:** **F6 (параллельно) ∥ [ F1 → {F2 → F3} → {F4 → F5} ]**.
Обоснование: F6 не пересекается по файлам с бэкендом (`web/**` vs `services/**`+`manage.py`) → стартует сразу; F1 — фундамент (двухэтапный пайплайн), без него F5 бессмыслен; F2 требует F1 (чистый вход) и идёт в паре с F3 (единая канон-миграция `factcheck_prompts.py` + все `*_prompts.py` + `prompt_migrations.py`); F4 даёт консолидацию/пороги, F5 использует её и пайплайн F1.
**Ступени вливания общих файлов:** `services/lore_worker.py`/`dream_worker.py`/`*_prompts.py` — **F1 → F2+F3** (атомарно: код + `docs/canon/**` + слепки `prompt_migrations.py` + тесты); `config/settings.py` + `services/param_catalog.py` + `services/config_migrations.py` + `manage.py` — **F4 → F5** (**Δ каталога = 0**); `web/*` — **эксклюзив F6**.

**⛔ Факт-ошибки ТЗ (обязательно в spec/ADR @Architect):** класса `PersonalityExtractor` **нет** (реально `LoreWorker._classify_dossier`, `services/lore_worker.py:526`; `_classify_dossier_safe` — `:483`); `DreamWorker` **есть** (`services/dream_worker.py:274`); таблицы `user_dossier` **нет** (досье = `graph_facts` + `persona_dossier_overrides`, `services/database.py:428`, `:4420-4448`); команды `manage.py memory` **нет** (argparse, `manage.py:476`; подкоманды `import`/`overrides`/`retention`); `factcheck_service.py` **уже имеет Full Tool Access** (10.20, фаза E) — не переоткрывать; «36 убеждений» — сверить факт на Step 2, валидатор count-agnostic.
**⚠️ Канон-конфликт (ADR-1013-3):** текущий канон **ПРЕДПИСЫВАЕТ** «дай понять, что ты уже проверял ранее / не повторять дважды» (`services/factcheck_prompts.py:43,72,104`; также `search_prompts.py`, `summary_prompts.py`, `web_prompts.py`, `youtube_prompts.py`), а ТЗ это **ЗАПРЕЩАЕТ** → обязательна канон-миграция (правка константы + `docs/canon/**` + `prompt_migrations.py` + тесты одним коммитом).
**⚠️ Инструменты UI-аудита (UPD владельца):** Puppeteer MCP **первым** (`puppeteer_navigate`/`screenshot`/`evaluate`); при недоступности/ошибке — fallback **Playwright ≥1.40 + Chromium** (`requirements.txt:28`, `playwright install chromium --with-deps`; прецедент 10.20-UPD3); если упали оба — **честная фиксация «аудит не выполнен»** в `UI_AUDIT_REPORT.md` (выдумывать результаты запрещено, R2/F6). Human-gate — только спорные дизайн-решения.
**Риски (полные списки — `tasks.md §4` каждой фичи):** двойная стоимость LLM двухслойного пайплайна (R1/F1); потеря полезных фактов фильтром (R2/F1); канон-атомарность и утечка снятого канона (R1/R2/F3); ложно-негативный grounding (R2/F2); деструктивность консолидации и санитарии — авто-бэкап/JSONL-архив/guard, но **инвариант: сырая история не удаляется** (R1/F4, R1/R5/F5); большой объём БД ~2M строк/724 МБ (R3/F4, R3/F5); факт-ошибки `user_dossier` (R2/F5); **галлюцинация отчёта о готовности UI — прецедент 10.20** (R2/F6); регресс 5 дефектов UPD3 (R3/F6); секреты в отчётах/скриншотах R17/R18 (R5/F6).
**Активация / раскатка (UPD владельца):** **флагов нет, поэтапной раскатки 10/50/100% нет.** F1/F2/F3 — **включены по умолчанию**; F4-консолидация — CLI-only без флага; F5 — деструктивный CLI **сразу (дефолт apply)**, без обязательного dry-run и двойных env-подтверждений, страховка — авто-бэкап + JSONL-архив, guard целевого чата, «сырую историю не трогаем»; F6 — без флага. **Δ каталога = 0** (439/409/414/92/90/20 без изменений); откат — `git revert` (+ обратная канон-миграция для F2/F3).
**Открытые гейты раунда (сквозные, вне фич):** Step 2 @Architect (spec/ADR **Accepted**) → реализация → @Reviewer → **Step 6 @Scanner** (независимый re-audit) → SPEC_READY → **Step 9 @DevOps** (для F5: авто-бэкап + боевой прогон + post-check неизменности `smart_messages`; деплой) → **Step 8 @PM** (архив `plans/features/*` → `plans/archive/*`). Отчёт @Scanner 10.20 (`plans/reports/round1020_scanner_audit.md`) — учесть: S10.20-1 (High, сохранение конфиг-вкладок) закрыт в UPD3; не переоткрывать.

## Раунд 10.20 (16.09.2026): «Летописец» (Lore Compiler) + глубокий рефакторинг RAG-архитектуры + UX/UI мини-аппа + Agentic AI (БЛОК 7) + Справка UI (БЛОК 8) — 1 фича-папка (фазы A–H) — ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН (16.09.2026 · commit `995cf83` + R18-fix `741b77c`; @PM Step 8 · @Architect Merge §45)

> **✅ REOPENED → RESOLVED (UI rework) — 17.09.2026 (UPD3 владельца, 16.09.2026):** фронтенд-блок **БЛОК 3** (`miniapp-ux-refactor-round1020`) был провален (отчёт Оркестратора о готовности — галлюцинация; бэкенд работает). **@Reviewer — выговор** за пропуск. Эпик возвращён на доработку — **5 дефектов:** (1) нет Liquid Glass; (2) CSS Grid в одну колонку; (3) КРИТИЧНО пустые поля/секреты (two-way binding, аудит во всех модулях); (4) градиент 5–8s + оранжевый; (5) сломанная sticky-панель «Отмена/Сохранить». До отчётов о готовности — только реальный фикс CSS/стейта. KG: Feature `round1020-ui-rework`, constraints `glassmorphism-contract`/`css-grid-320`/`secret-field-mask`/`gradient-motion-orange`; метрики — `plans/metrics.md`. **➡ ЗАКРЫТО:** доработка `round1020-ui-rework` — **✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН** (17.09.2026 · commit `ec93c3d`; @Reviewer Approved iter2 · @Scanner 0 C/H · pytest 6574/0; архив `plans/archive/round1020-ui-rework/`, §46) — см. раздел «Раунд 10.20-UPD3 (UI-rework)» ниже.
>
> **✅ R17 — Risk Accepted (владелец, 16.09.2026):** ротация НЕ делается, история git НЕ переписывается; R18 остаётся; старый файл — в ignore-листе `plans/docs/r18_scanner_ignore.md`.

**✅ ИТОГ 10.20 (16.09.2026):** эпик **завершён, задеплоен и заархивирован.** Фазы **A–H** выполнены (@Builder);
@Reviewer — **Approved**; @Scanner (re-audit) — **0 Critical / 0 High / 0 Medium / 0 Low** (открыто 5 Info);
pytest **6546 passed / 0 failed**; JS-гейты чистые. Архитектура смержена — `plans/ARCHITECTURE.md` **§45** (@Architect Step 7).
**Деплой (Step 9 @DevOps):** коммит **`995cf83`** (фича) + **`741b77c`** (R18-вычистка кредов из архива 10.16), запушено;
на сервере `systemctl` **active**, MainPID **2668878**, SQLite **`user_version=12`**. **Архив (Step 8 @PM):** папка фичи
`plans/features/round1020-lore-compiler-rag-refactor/` → **`plans/archive/round1020-lore-compiler-rag-refactor/`**
(сохранены `spec.md` + `tasks.md` + `README.md` + `adr-1020-1…-8`); R18-скан папки — **чисто** (секретов нет).

**Папка фичи (архив):** `plans/archive/round1020-lore-compiler-rag-refactor/` (`tasks.md` + `README.md` + `spec.md` + `adr-1020-1…8`).
**Спеки/ADR:** @Architect (Step 2) — **ADR-1020-1…-8 DONE**
(+ SUPERSEDE/AMEND: D206/Epic 50-58.8, канон R11/3.3, F-15 §4, ADR-1013-3 (канон-миграции), ADR-1018-2 (не трогаем)).
**Нумерация:** **T-1866…T-1931 (66 задач)**; фазы **A–H**.
**ТЗ:** `plans/current_task.md` — БЛОК 0 (7–11), БЛОК 1 (14–45), БЛОК 2 (48–76), БЛОК 3 (88–140), БЛОК 4 (144–177),
БЛОК 5 (181–211), БЛОК 6 (225–254), **UPD: О1–О7 (278–291)**, **БЛОК 7 Agentic AI (293–319)**, **БЛОК 8 Справка UI (323–331)**.
**⚠️ Файл ТЗ — untracked и содержит plaintext-секрет (SSH-пароль): не коммитить, значение не цитировать (R17, решение О6).**
**Baseline:** HEAD `2f3e1f0`; pytest **6326 passed / 0 failed**; каталог **437/407/412/92/90/20**; SQLite **v11**; APP_VERSION 2.57.0.
**Диагностика @Memory (Step 0):** `plans/reports/global_map.md`, `plans/reports/round10.19_scanner_audit.md` (§10.4/§10.5), `plans/MEMORY.md`.
**Аудит @Architect (Step 2, Фаза A):** `plans/reports/round1020_llm_engine_audit.md` — рекурсия тулов **есть** (`TOOL_MAX_ROUNDS=4`),
reasoning/scratchpad **отсутствует**, контекст — монолит без middleware, intent-router — rule-based.

**🚦 Human Gate ПРОЙДЕН (16.09.2026) — решения О1–О7 зафиксированы:**
- **О1** — БЛОК 5.5/6.1 = **verify-only**; manual DeepDream привязать к кнопке нового UI и подтвердить.
- **О2** — Time Injection **первым USER-блоком**; system-промпт **статичен**, **Prompt Caching не ломать**.
- **О3** — `compile_lore_story` — **простой флаг ВКЛ/ВЫКЛ, ДЕФОЛТ ON глобально**; **поэтапная раскатка 10/50/100 % ОТМЕНЕНА**.
- **О4** — новый ключ **`limits.chat_timezone`** (расписания сна/бэкапа не смешивать).
- **О5** — глобальный `parse_mode=None` **сохраняется**; для историй Летописца **локально `parse_mode=HTML`** + HTML-теги в промпте; структуру меню не менять.
- **О6** — `current_task.md` untracked, пароль в git **не коммитить**.
- **О7** — аддитивная **`lore_stories` без бампа `user_version`**.

**Фазы эпика (порядок критичен):**

| Фаза | Содержание | ТЗ-блок | Задачи | Тип |
|---|---|---|---|---|
| **A** ✅ | READ-ONLY аудит LLM-движка → отчёт `plans/reports/round1020_llm_engine_audit.md` + Human Gate A (**пройден**) | БЛОК 4 | T-1866…T-1871 | research — **DONE, разблокировала B/C** |
| **B** | Ядро памяти: тотальные метаданные (БЛОК 0), роутинг/ASC-хронология/`/summary`/`dig_into_lore` (БЛОК 2), Time Injection (первым user-блоком) + «Часовой пояс чата», анти-галлюцинации + group-by-authors, persona fallback, «Безлимит (∞)» в «Сводке» (БЛОК 5) | 0/2/5 | T-1872…T-1885 | backend + канон-промпты + UI-виджеты |
| **C** | Новая фича **«Летописец»**: tool `compile_lore_story(topic)` — граф 1–2 уровня + хронология + storytelling-промпт (HTML) + диффы/UPD, `lore_stories` (**7→8 инструментов**, флаг default ON) | БЛОК 1 | T-1886…T-1893 | backend / new feature |
| **D** | UX/UI мини-аппа: критические баги binding/routing, досье участников + ручное редактирование, тикер досье, Liquid Glass, CSS Grid, sticky save, human-readable labels, рестайлинг Advanced-аккордеона (**структуру меню НЕ менять**) | БЛОК 3 | T-1894…T-1904 | frontend |
| **E** | Фактчекер: Full Tool Access (`dig_into_lore`, `compile_lore_story`, веб-поиск) + функциональный промпт; техдолг **S10.19-15**, **S10.19-23**, CLI `retention` (WAL) | БЛОК 6 | T-1905…T-1912 | backend + канон-промпты + ops |
| **G** | **Agentic AI:** (7.1) tool recursion fail-safe + graceful degradation + лог потерянных раундов; (7.2) парсинг `reasoning_content` + stripper reasoning-тегов + локальное снятие канона «1-2 предложения» (P0); (7.3) единый Context Middleware + приоритет метаданных над бюджет-капом + `graph_facts` (`tg_message_id`, `forward_from`) + миграция pg+sqlite; (7.4) EN-`description` всех схем + строгая типизация | **БЛОК 7** | T-1918…T-1927 | backend / LLM-движок + DDL |
| **H** | **Справка UI:** актуализация текстов (Летописец, Фактчек, безлимиты), удаление неактуальных механик, **сохранение дерзкого стиля**; канон `info_service.py`/`info_text.md`/гайд, `web/` | **БЛОК 8** | T-1928…T-1931 | content/UI |
| **F** | SPEC_READY владельцу **до деплоя** → ревью → аудит @Scanner → деплой @DevOps → архив @PM (охватывает B–H) | — | T-1913…T-1917 | гейты (финальные) |

**Порядок исполнения:** **A ✅ → {B ∥ D} → C → E → {G ∥ H} → F.** Обоснование: аудит до проектирования (прямое требование владельца);
D (UI) не зависит от A/B; C стартует после гейта B (роутинг-описание 2.5 ссылается на описание C); E зависит от C (тулы фактчекера) и B (метаданные);
G зависит от B (Context Middleware поверх метаданных), C/E (канон-ступени) и ADR-1020-7; H зависит от C/E (тексты про Летописца и Фактчек).
**Ступени вливания общих файлов:** `tool_schemas.py` **B→C→E→G.4**; `tool_loop.py` **C→G.1**; канон промптов **C→E→G.2c** (все атомарно); `web/*` **D→H**.

**⚠️ Дубли / «уже сделано» — повторно НЕ реализовывать (verify-only):**
- **БЛОК 5.5** (аудит DeepDream/PersonalityExtractor + логирование причин пропуска) — **уже сделано** в 10.18
  (`plans/archive/sleep-manual-cascade-badges/`, ADR-1018-2, T-1717) → **T-1883 (verify-only)**.
- **БЛОК 6.1** (ручной триггер DeepDream, «Форсировать глубокий сон») — **уже реализовано** в 10.18
  (API `POST /api/memory/dream/run`, коммит `16a8c0b`, тесты `tests/test_sleep_manual_cascade_round1018.py`) → **T-1906 (verify-only)**.
- **ASC-хронология** уже есть для DirectChat (`services/summary_memory.py:2316-2368`, канон D206) → БЛОК 2.6 = **аддитивное расширение скоупа** (T-1876).
- **Advanced-аккордеон** уже есть (10.4 D + 10.11 F-11: `progressive_level`, `<details class="advanced">`) → БЛОК 3.8 = **рестайлинг** (T-1902).
- **Tool recursion** уже есть (`services/tool_loop.py::chat_with_tools`, `TOOL_MAX_ROUNDS=4`) → БЛОК 4 = **read-only описание** (T-1866).
- **Имя тула:** в ТЗ — `dig_into_lor` (опечатка), в коде — **`dig_into_lore`** (`services/tool_schemas.py:72`, `services/tool_router.py::_dig_into_lore:413`) — использовать корректное.
- **`factcheck_service.py` тулов не имеет** — посылка БЛОК 6.2 верна.
- **`compile_lore_story` НЕ существует** — реально новая фича (сейчас 7 инструментов: `execute_web_search`, `query_chat_memory`, `dig_into_lore`, `summarize_video`, `download_media`, `get_bot_health`, `get_recent_history`).
- **Reasoning/scratchpad в движке отсутствует** (аудит Q2: читается только `content`, теги не вырезаются) → БЛОК 7.2 = **новый рабочий пакет** (T-1920…T-1922).
- **Контекст — монолит без middleware** (`payload_builder`: 1 system + 1 user) → БЛОК 7.3 = **Context Middleware** (T-1923).
- **`graph_facts` без `tg_message_id`/`forward_from`** (`database.py:286-296`) → БЛОК 7.3 = **расширение схемы + миграция pg+sqlite** (T-1924).
- **`description` схем тулов на русском** (`tool_schemas.py`) → БЛОК 7.4 = **EN + строгая типизация** (T-1925; канон 3.3).
- **Справка** — код-канон `services/info_service.py::DEFAULT_INFO_TEXT` (+ `info_text.md`, `INFO_CANON_VERSION`, `KNOWN_INFO_SNAPSHOTS`), гайд `plans/docs/intelligence_user_guide.md`, рендер `web/index.html:2564-2630` → БЛОК 8 = **правка текста + бамп версии** (T-1929).

**Техдолг БЛОК 6.4 (подтверждён, переносится сюда):** **S10.19-15** (`services/oversight.py:203-216` — двойной
`chat_usage.key_status` в «Сводке»), **S10.19-23** (`services/memory_maintenance.py:389-425` — fsync файла есть,
каталога нет), **CLI `manage.py retention`** (dry-run default, работа при живом боте → WAL/снапшот). Источник —
`plans/reports/round10.19_scanner_audit.md` §10.4/§10.5. Смежно: S10.18-29 (Low, проверен/закрыт фикс-проходом 10.18).

**Feature flags / раскатка (Фаза C; решение О3):** **`flags.lore_compiler_enabled`** (каталог-Δ = **+1 ключ**), **ДЕФОЛТ ON
глобально** для всех чатов; простой тумблер ВКЛ/ВЫКЛ в админке; **поэтапная раскатка 10/50/100 % ОТМЕНЕНА**;
OFF → тул недоступен (остальные 7 работают); откат — toggle OFF / `git revert`. Фазы B/D/E/G/H — безусловные.
**`limits.chat_timezone`** (Δ +1 ключ) — это **данные**, не флаг (О4). Итого каталог-Δ = **+2 ключа + N текстов**.

**🚦 Human Gate — ✅ ПРОЙДЕН (16.09.2026), решения О1–О7 зафиксированы (см. блок выше и `tasks.md` §Решения):**
1. **Дубли 10.18** — подтверждён verify-only (БЛОК 5.5 / 6.1), ADR-1018-2 не переоткрывается (**О1**).
2. **7 → 8 инструментов** (`compile_lore_story`) — санкционировано; флаг простой, **default ON** (**О3**).
3. **Новый ключ каталога «Часовой пояс чата»** (`limits.chat_timezone`) — санкционирован (**О4**); Δ каталога сводится единым гейтом.
4. **Политика `plans/current_task.md`** — untracked, «не коммитить / значение не цитировать» (R17, **О6**).
5. **Объём UX/UI** — подтверждён полностью + «структуру меню не меняем»; **format доставки историй — HTML** (**О5**).
6. **DDL UPD-хранилища** — аддитивная `lore_stories` без бампа `user_version` (**О7**).

**Риски (переносятся в `spec.md`, полный список — `tasks.md §7`, R1–R21):** дубли 10.18; 7→8 инструментов;
канон-атомарность промптов (ADR-1013-3); аддитивность ASC vs семантический RAG; Δ каталога между фазами;
стоимость Time Injection (митигировано О2: первый user-блок); запрет изменения меню; sticky-save vs auto-save/409;
тон фактчекера; секрет в `current_task.md`; **AGENTIC AI (БЛОК 7):** stripper-тегов (R15), EN-схемы/роутинг (R16),
`graph_facts` DDL (R17), приоритет метаданных над капом (R18), протечка снятого канона 1-2 предложения (R19);
**Справка (R20), локальный `parse_mode=HTML` (R21)**.

**⏸ Открыто (human-pending, НЕ блокирует завершение/деплой/архив):**
- **T-1904** (Фаза D): живая UI-приёмка человеком (десктоп/Android/Nekogram), подтверждение «меню не изменено», проверка кнопки «Форсировать глубокий сон» в новом UI (О1/T-1906).
- **T-1931** (Фаза H): приёмка Справки владельцем (стиль/актуальность), сверка с фактическим поведением.

**➡ Follow-up (следующий раунд):** **T-1932** — fallback точки 7 (`vector_search` → `list[str]`): «голые» строки архива в `query_chat_memory` (документированный PENDING, ADR-1020-1 Р6/R26); формат `[ММ.ГГГГ | fact:ID]: текст`, без смены текущего контракта с `summary_generator`.

## Раунд 10.20-UPD3 (UI-rework) — ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН (17.09.2026 · commit `ec93c3d`)

**Папка фичи (архив @PM, Step 8):** `plans/archive/round1020-ui-rework/` — `spec.md`, `ui-contract.md`, `tasks.md`, `adr/ui-rework-1020.md`.

**Статус: ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН.** Доработка БЛОКА 3 закрыта: **5 UI-дефектов исправлены**
(Liquid Glass `rgba(20,25,30,0.5)` + `blur(16px)`; CSS Grid `repeat(auto-fit, minmax(320px,1fr))`; маска секретов `••••••••••••`
при `configured:true` + guard «маска не уходит на сервер»; градиент **6s** + оранжевый `#FF8A3D`; переверстанный `sticky-save`
+ `.sticky-spacer`). @Reviewer — **Approved** (итерация 2, реальный Chromium: CSSOM-зонды, Grid-треки, значения инпутов, offset-замер
sticky); @Scanner — **0 Critical / 0 High** (`M-1`/`L-1`/`L-2` закрыты); полный `pytest` — **6574 passed / 0 failed**;
JS-гейты (`node --check web/app.js`, `JS-UNIT-OK`, `VUE-MOUNT-OK`) чистые. Архитектура — `plans/ARCHITECTURE.md` §46.

**Деплой (@DevOps):** commit **`ec93c3d`**; сервис на `racknerd-f4e3456` — `active`, MainPID `2738993`; прод-`/web/static/app.css`
подтверждён (`blur(16px)`, `rgba(20,25,30,0.5)`, `#FF8A3D`, `6s`, `sticky-spacer`, `Cache-Control: no-store`); `PRAGMA user_version=12`.

**5 дефектов (UPD3, `plans/current_task.md` стр. 365–411):**
1. **Liquid Glass + сломанная верстка** — ✅ исправлено (стекло на модалках/карточках; grid-контейнеры без фона).
2. **CSS Grid** — ✅ «Модули»/«ИИ» заполняют ширину (≥2 трека на десктопе).
3. **КРИТИЧНО: пустые поля/секреты** — ✅ `configured:true` → маска; пусто только при `null`; маска не сохраняется (все модули).
4. **Фоновый градиент** — ✅ 6s + оранжевый, переливы заметны; `prefers-reduced-motion`/`prefers-contrast` сохранены.
5. **Sticky-панель** — ✅ не перекрывает контент, отступы модалки целы, `safe-area` учтён.

**⏸ Остатки (human-pending, НЕ блокируют завершение/деплой/архив):** живая приёмка владельцем — WebView **Telegram Android / Nekogram**
(реальный рендер + fallback `@supports not (backdrop-filter)`) и **скриншот-приёмка §7.5** (согласование внешнего вида градиента/стекла).

**Файлы:** `web/index.html`, `web/static/app.css`, `web/app.js`, `web/api/routes.py`; чтение — `services/param_catalog.py`
(`CHECKUP_BETTERSTACK_SQL_*`, стр. 503–506). **Меню/навигация не изменены** (снимок 25 вкладок / 6 nav / 12 модулей). Флаг не вводится
(каталог-Δ = **0**), раскатки 10→50→100% нет, откат — `git revert`.

> **История провала/фикса (R27–R36):** исходный отчёт о готовности UI был **галлюцинацией** (@Reviewer — выговор за пропуск);
> повторная приёмка выполнена по **фактическому рендеру** (CSSOM-зонды, served-CSS, значения инпутов, offset-замер), доказательство
> вида «grep нашёл» запрещено. Детали и риски — `tasks.md §7` (архив).

**➡ Передать @Memory (Step 10):** финальные числа — pytest **6574/0**, **SQLite v12**; commit **`ec93c3d`**; UI-доработка безусловная
(флаг не вводится, каталог-Δ = **0**); путь архива — `plans/archive/round1020-ui-rework/`; архитектура — `plans/ARCHITECTURE.md` §46.
Предшествующий эпик 10.20: pytest 6546/0, каталог 439/409/414/92/90/20, `compile_lore_story`, `INFO_CANON_VERSION=3`,
архив `plans/archive/round1020-lore-compiler-rag-refactor/`, `§45`.

## F6/F7 (10.19, ревью Батча E, итерация 2/3, 15.09.2026): перенесённые пункты

- **`services/media_integrity.restore_missing_files` (Low, D-4/D-5):** функция **убрана из публичного API** — не имела call-site и реального маппинга `path→file_id` (Bot API `file_path` транзиентен), т.е. фактически не восстанавливала файлы. Реализовать только при появлении персистентного маппинга медиа (`path`/`file_id` в схеме); до тех пор диагностика (`audit_media_files`) остаётся honest-эвристикой (`reliable=false`). Требуется: таблица/колонка маппинга + bounded-восстановление под `flags.download_enabled` + тесты.
- **I-4 (F7 §4.6):** `_dedup_knn` — возможная потеря recall при мультичатовости (глобальный top-k вытесняет свои строки); chat-scoped vec-индекс — при росте числа чатов (не блокер при одном активном чате).

## Раунд 10.19 (15.09.2026): UPD2/UPD3/UPD4 — бюджеты direct-чата (безлимит + раздел «Бюджеты»), BetterStack ingest-Bearer-контракт, расширение контекста, UI «Статуса», синхронизация медиа/аватаров, здоровье памяти + retention, устойчивость GraphRAG-Memorize — 8 фич — ✅ COMPLETED + ЗААРХИВИРОВАН (Step 6 @Scanner + Step 7 @Architect Merge + Step 8 @PM, 16.09.2026)

**✅ ИТОГ 10.19 (16.09.2026):** реализация завершена (UPD2 + UPD3 + UPD4), все **8 фич заархивированы** — перенесены
`plans/features/<feature>/` → **`plans/archive/<feature>/`** (@PM Step 8): F1 `betterstack-ingest-bearer-contract` ·
F2 `direct-chat-budget-unlimited` · F3 `budget-settings-section` · F4 `direct-context-limit-expansion` ·
F5 `status-section-ui-merge` · F6 `media-files-avatars-sync` · F7 `memory-retention-health` ·
F8 `graphrag-memorize-robustness`. В каждой папке сохранены `spec.md` + `tasks.md` + ADR-1019-1…-8
(в т.ч. центральный `budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md`) + артефакты F6
(`ops.md`, `t1829-fetch-failed-diagnosis.md`). В `plans/features/` остались только 6 ранее существовавших
backlog-папок (`admin-debug-webview`, `config-read-path-audit`, `frontend-admin-bugfixes`,
`post-deploy-admin-minors`, `scam-incident-security-followup`, `user-aliases-admin`); пустых/осиротевших папок нет.
Ссылок на перемещаемые пути в `tests/` **не найдено** (grep `plans/features` по `tests/` — единственное совпадение —
комментарий + archive-fallback **10.17** `test_tool_download_quality_round1017.py:362`, уже корректный);
починка путей не потребовалась. Повторный полный прогон после архивации — **6323 passed / 0 failed**.

**Финальные метрики:** полный **pytest — 6323 passed / 0 failed** (база 10.18 = **6139** → **+184**; траектория
Scanner-итераций: 6164 (A) → 6195 (B) → 6232 (C) → 6262 (D) → **6323** (E)); `node --check web/app.js` clean;
`JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` clean.
**Каталог** — санкционированный Δ (UPD3 п.5): **REGISTRY 437 / GROUPS 92 / Settings 407 / categorized 412 /
mapped 90 / `TAB_RULES` = `CONFIG_TAB_TITLES` 20** (+1 ключ, +2 группы, +1 config-вкладка `mod_budgets`
«Бюджеты»; эталон `test_param_catalog`). **SQLite: v10 → v11** (`UNIQUE(chat_id, import_key)` +
`import_checkpoints(path, chat_id)`, F7/ADR-1019-6; идемпотентно/транзакционно/обратимо, FTS5/vec не
пересоздаются; авто-миграция при старте); **новых PG-DDL нет**.
**Фича-флаги:** новых **каталоговых** флагов НЕТ (Δ каталога от флагов = 0) — безусловно активны sentinel-семантика
бюджетов/контекста + per-chat резолв (F2/F4), раздел «Бюджеты» + нейтральный сид данных (F3), единый «Статус» (F5),
локальный медиа-fallback (F6), расширенная диагностика memorize (F8); откат — `git revert`.
**Единственные env-only гейты** (прогрессивная доставка деструктивного пути retention, F7/ADR-1019-6,
`ClassVar` — Δ каталога = 0): `IMPORT_RETENTION_ENABLED` (OFF) × `IMPORT_RETENTION_DRY_RUN` (ON) ×
`IMPORT_RETENTION_BACKUP_CONFIRMED` (OFF) — авто-крон удаляет **только** при `true/false/true`, иначе dry-run +
WARNING; фактический прогон — только CLI `manage.py retention --apply`. Порядок роутеров `bot.py` не сдвинут
(только DI-kwargs + startup `migrate_dream_thresholds` → `migrate_global_budget_defaults` →
`migrate_context_limit_defaults` → `apply_chat_settings_seed`); `.env`/`media/` не тронуты; R16/R17 держатся.
**Объём:** **8 фич, T-1778…T-1865** (исходно T-1778…T-1852 + итерация 2 UPD3 T-1853…T-1865).
@Reviewer — **Approved** по батчам A–E (E — после переделки по **UPD4**: концепция «VIP» удалена из **кода** —
сид универсальный `services/chat_settings_seed.py` + `config/chat_settings_seed.json`, id целевого чата — только
данные JSON + тесты).
@Scanner — **0 Critical / 0 High / 0 Medium по всему эпику** (High S10.19-13 и Medium S10.19-14 закрыты @Builder,
независимо верифицированы — §8.5/§9.1); открыто **2 Low** (S10.19-15, S10.19-23) **+ 1 Low из 10.18** (S10.18-29)
+ **Info**. Отчёт: `plans/reports/round10.19_scanner_audit.md` (§1–§10, итоговая сводка §10.4,
обязательные @DevOps-гейты §10.5); факт-база — `plans/reports/global_map.md`.
@Architect — Merge Phase завершена: `plans/ARCHITECTURE.md` (**818 строк**, §40–§44, SUPERSEDE/AMEND-карта
ADR-1019-1…-8 + сводные инварианты; периметр техдолга — §25).
**UPD2-3 (§3, SSH-фрагмент) — ЗАКРЫТ/ОТМЕНЁН:** решением UPD3 п.1 принят вариант «а» — фрагмент оставить как есть,
историю git (`filter-repo`) **не трогаем**; UPD4 не переоткрывал. Отдельной фичи нет и не будет (только
информационная запись S10.18-13 ниже).
**Коммит/деплой — @DevOps Step 9** (вне этого шага); @Memory Step 10 — финал памяти/метрик.

**➡ Передать @Memory (Step 10):** финальный статус эпика — **COMPLETED** (+ деплой-статус после Step 9);
числа — pytest **6323/0**, каталог **437/407/412/92/90/20**, **SQLite v11**, env-only retention-гейты (трое);
пути артефактов — `plans/archive/<feature>/` (8 папок, имена выше); **ADR-1019-8** (`per-chat-limits-and-seed`,
`plans/archive/budget-settings-section/`) → статус **Accepted/Implemented**; note: **код — источник истины**,
`_STATUS_HINTS = {401, 402, 403, 406}` (в ТЗ-брифе UPD2 §2 значилось `202/402/403/406` — неверно: 202 — это
**успех** BetterStack, в подсказках его нет; 401 — реальный root cause 401-спама). Коммит/деплой — Step 9 (@DevOps).

**🧾 Техдолг / остаточные находки 10.19 (перенесены @PM, Step 8 — не блокеры):**
- **S10.19-15 (Low, F3, перф «Сводки»):** `services/oversight.py:203-216` — `_limits_block` вызывает
  `chat_usage.key_status` **дважды на чат** (по разу на метрику direct-контура) → 2× `budget_snapshot`/
  `used_today` + до 2× чтения `chat_profiles` на чат за построение «Сводки» (кэш 60 с; тест
  `test_direct_contour_reads_key_status` это закрепляет: `seen == [-100, -100]`). Фикс (2 строки) — один
  `key_status`/`budget_snapshot` на чат, обе метрики из результата. Закрыть в ближайшем follow-up.
- **S10.19-23 (Low, F7, durability архива retention):** `services/memory_maintenance.py:389-425`
  (`_archive_imported_history`/`_flush_and_fsync`) — **`fsync` есть у ФАЙЛА, нет у КАТАЛОГА**: при сбое питания
  сразу после создания архива и SQLite-commit запись каталога (имя файла) может не попасть на диск → строки
  удалены, «файла-архива нет» (окно крайне узкое; POSIX требует fsync родительского каталога; ext4/auto_da_alloc
  обычно спасает). Единственная недозакрытая щель в инварианте «архив переживает сбой РАНЬШЕ DELETE». Фикс —
  после `fsync(file)` синхронизировать каталог (`os.open(dir, O_RDONLY)` + `os.fsync` в том же `to_thread`;
  на Windows — no-op) либо задокументировать остаточный риск.
- **S10.18-29 (Low, унаследовано из 10.18/F2, deep-manual маркер):** `run_once(deep=False)` («Сон сейчас») не
  выставляет `_manual_deep_until`, хотя каскад реально запускает Глубокий сон → во время manual-каскада
  `deep_sleep.manual=False` и `active_until=None` вне окна; TTL маркера (900с) не связан с
  `_run_lock`/`_deep_lock`. Фикс — в `run_once` (ветка `deep=False`) или в `_maybe_deep_after_sleep(manual=True)`.
- **Info (перечень §10.4, включая унаследованные из 10.18):**
  **S10.19-3…-6** — `reason=not_json` неточен для D-08-подслучая (кандидат `no_valid_facts`); 4xx/3xx-батчи
  BetterStack не re-buffer'ятся (осознанно ADR-1019-1 D3/D5); верхний `except LLMError` в `memorize_facts`
  фактически недостижим (defensive); `path`-режим пробника несёт реальный токен в URL — только ручная
  диагностика @DevOps (не CI/крон);
  **S10.19-9…-12** — `_belief_name_participates` теряет имена с пунктуацией; контекст/retention-семейства
  подключены в F4/F7 (историческая запись); в «Сводке»/API фона нет sentinel-флагов (только число);
  границы cap фон `used <= limit` vs direct `used >= limit`;
  **S10.19-16…-22** — OFF-тумблер пишет явный `global_value` вместо DELETE (чат не наследует будущие дефолты);
  дубль retention-fallback в policy и `oversight`; инвариант помечает чат «предупреждённым» **до** проверки;
  chars-fallback понижен до `debug` («аварийный путь» тихий); дисплей `limit: -1` при глобальном `−1` без
  accounting-записи (миграция не правит легаси-24000); **S10.19-21 — док-пробел закрыт Merge** (§41–§44);
  финальный purge без `try/except` при docstring «fail-open»;
  **S10.19-24…-27** — архивы `imported_history_*.jsonl` не ротируются; запись архива в event loop;
  `orphan_files`/`missing_on_disk` — bounded-эвристика (`reliable:false`); тест с локальным HTTP-сервером —
  флейки-риск (не продуктовый дефект);
  **S10.18-12** — `NostalgiaWorker` читает `memory.nostalgia_*` только через `hot.get` (global-only; backlog-задача
  T-1764); **S10.18-13** — pre-existing фрагмент SSH-пароля в tracked-файле
  `plans/archive/security-rotation-finalize-round1016/spec.md:35` (задача **отменена** — UPD2-3/UPD3 п.1;
  значение не цитировать, R17); **S10.18-18/-19/-20** — deep-без-капа при явном `?deep=1`; `tokens_today` без
  фильтра `kind`; `previous` = эффективный гейт kill-switch; **S10.18-31/-32/-33** — нормализация STOP_LIST,
  само-петля в degree, `upsert_edge` при отсутствии узла; **S10.18-37/-38** — множитель `importance` меняет
  RAG-порядок (нужен живой прогон RAG-качества) + агрегат открытых Info 10.18.

**🚦 Обязательные @DevOps-гейты 10.19 (Step 9; источник — отчёт @Scanner §10.5) — без них деплой НЕ выполняется:**

| # | Шаг | Действие | Ожидание / abort-условие |
|---|---|---|---|
| **D1** | **Dry-run retention** (до любых изменений) | `python manage.py retention --dry-run` | `mode=dry-run`, `reason ∈ {dry_run, no_candidates}`; кандидаты — **без** целевого чата (у него retention `0`); данные не меняются |
| **D2** | **Бэкап БД + `.env`** | бэкап SQLite/PG (@DevOps-процедура) → `IMPORT_RETENTION_BACKUP_CONFIRMED=true` **только после проверки бэкапа** | без подтверждённого бэкапа авто-крон остаётся dry-run (WARNING в логе) |
| **D3** | **Миграции/сид** | рестарт бота (авто: v11 + `migrate_*` + `apply_chat_settings_seed`) или `python manage.py apply-chat-overrides` | идемпотентно; `applied`/`skipped`; **другие чаты не меняются**; `PRAGMA user_version` (SQLite) = **11** |
| **D4** | **Post-Deploy Gate** (боевая БД, **строго ДО крона**) | SQL из spec F7 §10 (`chat_params -> 'overrides'` целевого чата, 8 ключей) | ровно: retention **0**, бюджеты ключа/фона и контекст **−1**. Любое расхождение → **abort деплоя + откат**, рестарт/крон НЕ запускать |
| **D5** | **BetterStack** | `.env`: `BETTERSTACK_HOST` (US-ingest) + `LOGTAIL_SOURCE_TOKEN` = **Source Token**; рестарт | в journald `[betterstack] attached \| host=… \| token_len=…`; нет `send failed \| reason=status=401`; curl-матрикс T-1779 (только коды, маскированно) — US×Bearer = **202** |
| **D6** | **Live-проверка контекста/бюджетов** | сообщение боту в целевом чате; `GET /api/memory/cognition/status?chat_id=…`, `/api/oversight/summary`, `/api/memory/health` | ответ с расширенным контекстом (симптом «7000→869» снят); «Сводка» — «Безлимит (∞)» по обоим контурам, «Импорт: Вечно»; health отдаёт `storage`/`facts_overdue` |
| **D7** | **Фактический purge** (по решению владельца) | `python manage.py retention --apply` (после D1–D4) | `archived == deleted` при `reason=ok`, файл `imported_history_*.jsonl` создан; размер БД падает; целевой чат не затронут. Авто-крон (`IMPORT_RETENTION_ENABLED`) оставить **OFF**, пока не подтверждён ручной прогон |
| **D8** | **Откат** (при инциденте) | `git revert`; retention → `0`; индекс v11 обратим (`DROP INDEX …chat_import_key` + `CREATE UNIQUE INDEX idx_smart_messages_import_key`); восстановление из бэкапа/архива | данные не теряются; архив `imported_history_*.jsonl` — второй рубеж |

Ниже — исторический документ планирования эпика (Step 1 @PM + Step 2 @Architect, итерации UPD2/UPD3),
сохранён для трассируемости.

**🔵 СТАТУС 10.19 при планировании (Step 1 @PM, 15.09.2026; итерация 2 — UPD3 @Architect, 15.09.2026):** ТЗ — **UPD2** в `plans/current_task.md` (строки 130-175) + **UPD3** (строки 178-216, итерация 2). Эпик — `Epic round1019 (UPD2 bugfixes)` + милстоун `round10.19-epic` (@Memory, Step 0). Создано **8 фича-папок** в `plans/features/` со `tasks.md`; спеки/ADR — за @Architect (Step 2, **итерация 2 обновлена**). **Нумерация:** T-1778…T-1852 (исходно) + **T-1853…T-1865 (итерация 2 UPD3)**.
**Baseline:** HEAD `fd6acc7` (docs-синхронизация 10.18); pytest **6139 passed / 0 failed**; каталог **436/406/411/90/88/19**; SQLite **v10**; прод `release-round1018` (`16a8c0b`, PID 2319614); APP_VERSION 2.57.0.
Преемник — 10.18 (`plans/archive/<feature>/`, 7 фич COMPLETED+DEPLOYED, 75 задач T-1703…T-1777).

**📌 ВАЖНО (Step 0 @Memory + аудит @PM):** UPD2 в ряде мест **построен на неверных посылках** и **прямо конфликтует с решениями прошлых раундов** → требуются **новые ADR/SUPERSEDE/AMEND** и human-gate. Диагностика:
- **§2 (BetterStack):** посылка «чинить `LogtailHandler`/`endpoint=` из `logtail-python`» **неверна** — библиотеки в проекте **нет** (`requirements.txt`/импортов нет, с раунда 4); прод-путь — собственный `services/betterstack_handler.py`. Реальная проблема — **контракт ingest**: сейчас `https://{host}/{token}` (токен в **пути**) **без** `Authorization`, тогда как официальный US-контракт — `POST https://{ingesting_host}` + `Authorization: Bearer {source_token}` (202/402/403/406). Плюс **ложный WARNING** «token == public key SENTRY_DSN» (bot.py:190-195, ADR-1018-1 D4) — на унифицированных US-кластерах Source Token побайтово совпадает с public key (**норма**, владелец дал скриншоты). **Конфликт ↔ ADR-1018-1 D2/D4/D8** → AMEND.
- **§1 (бюджеты direct):** sandbox `reason=budget` при `used_calls=25 / limit_calls=25`; ТЗ требует **безлимит по чату** + отдельный раздел «Бюджеты» + актуальные бары. **Конфликт ↔ F-15 раунда 10.3 `direct-sandbox-budget-investigation`** («дефолты 25/100k НЕ меняются, любой лимит ≤ 0 = ЗАПРЕТ, sandbox — штатно») → SUPERSEDE/AMEND (ADR-1019-2).
- **§3 (SSH-фрагмент):** фрагмент SSH-пароля в **отслеживаемом** файле `plans/archive/security-rotation-finalize-round1016/spec.md:35` (tracked, commit `eb3fd4a`). Владелец: сообщить локацию, убедиться что не попадает в git и **ОТМЕНИТЬ задачу** (оформлено как **пункт отчёта/backlog**, отдельной фича-папки НЕТ). Значение нигде не цитировать (R17).
- **§6 (чекап, прочее):** nano-gpt timeouts — фоллбэк уже работает (принято); обрезка контекста 7000 → **869** (`safe_budget(1000)` при `TOKEN_SAFETY_MULTIPLIER=1.15`); `token_counter` `CHAT_THREAD_MAX_TOKENS=None` → chars-fallback 2000 + WARNING; рассинхрон ФС↔БД (`photos/file_456.jpg`) + `fetch failed` юзера 525660918; память 11864/667/40, 0 прогонов deep/resurrect/decay, `smart_messages` ~2M строк / БД 724 МБ / диск 8 из 23 ГБ; GraphRAG Memorize — `LLMError` первичного извлечения обходит fallback/retry (молчаливая потеря фактов).
- **Смежный техдолг:** `S10.18-12` (Nostalgia читает `memory.nostalgia_*` только через `hot.get`, global-only) — учитывать при правках настроек воркеров (F7); не регрессировать.

**8 фич (нумерация продолжает T-1777 → T-1778…T-1852, 75 задач):**

| # | Фича (папка) | Тип | UPD2 § | Зависит от | Приоритет | Задачи | Новый ADR |
|---|---|---|---|---|---|---|---|
| **F1** | `betterstack-ingest-bearer-contract` | backend/infra | §2 (стр. 133-149) | — (@DevOps: curl-матрикс + `.env`+рестарт) | **P0** | T-1778…T-1788 (11) | ⬜ ADR-1019-1 (**AMEND ADR-1018-1 D2/D4/D8**) |
| **F2** | `direct-chat-budget-unlimited` | backend | §1 (стр. 131-132) | — | **P0** | T-1789…T-1798 (10) | ⬜ ADR-1019-2 (**SUPERSEDE/AMEND F-15** 10.3) |
| **F3** | `budget-settings-section` | backend+TMA/каталог | §1 (стр. 132) | **F2** | **P0/P1** | T-1799…T-1808 (10) | ⬜ ADR-1019-3 (раздел + Δ каталога) |
| **F4** | `direct-context-limit-expansion` | backend+каталог | §6 (стр. 162,164,174) | **F3** | P1 | T-1809…T-1817 (9) | ⬜ ADR-1019-4 |
| **F5** | `status-section-ui-merge` | frontend | §4 §5 (стр. 152-153) | — | **P2** | T-1818…T-1825 (8) | — (UI-спека) |
| **F6** | `media-files-avatars-sync` | backend | §6 (стр. 158) | — | P1 | T-1826…T-1834 (9) | ⬜ ADR-1019-5 |
| **F7** | `memory-retention-health` | backend/ops+каталог | §6 (стр. 166) | **F3/F4** | P1 | T-1835…T-1844 (10) | ⬜ ADR-1019-6 |
| **F8** | `graphrag-memorize-robustness` | backend | §6 (стр. 160) | **F7** (смежность) | P1 | T-1845…T-1852 (8) | ⬜ ADR-1019-7 (**AMEND F-15 §4**) |

**Рекомендуемый порядок исполнения:** **{F1 ∥ F2} → F3 → {F4 ∥ F5} → {F6 ∥ F8} → F7.**
Обоснование: **F1** и **F2** — прод-блокеры (телеметрия «в никуда»; бот отвечает заглушками), разные плоскости → параллельно; **F3** — интерфейс бюджетов, опирается на механизм F2; **F4** — расширение контекста (каталог/настройки, после F3); **F5** — UI-вёрстка (независима); **F6**/**F8** — независимые backend-фиксы (медиа/GraphRAG); **F7** — retention/здоровье памяти последняя (тяжёлая операция + бэкап).
**⚠️ Пересечения файлов:** F2/F3/F4/F7 делят `services/param_catalog.py` и `config/settings.py` (сводить Δ каталога и правки настроек); F3/F5 делят `web/index.html`/`web/app.js`/`app.css` (вливать ступенями **F3 → F5**); F7/F8 делят `services/summary_memory.py` (согласованное вливание); F2/F3 делят `services/chat_usage.py`.

**ADR-конфликты, требующие нового ADR/SUPERSEDE (детали — `plans/features/*/tasks.md` §7):**
- **ADR-1019-1** — **AMEND ADR-1018-1** D2 (URL-форма), D4 (`token==pubkey` — норма unified US, снять WARNING), D8 (curl-матрикс `{path-token, Bearer}×{US,EU}`) — F1.
- **ADR-1019-2** — **SUPERSEDE/AMEND F-15 (10.3)** «0 = запрет», «дефолты не меняются», «sandbox штатно» — F2.
- **ADR-1019-3** — раздел «Бюджеты» + **санкционированный Δ каталога** + аддитивный контракт «Сводки» — F3.
- **ADR-1019-4** — развязка контекстных лимитов, `token_counter`/chars-fallback — F4.
- **ADR-1019-5** — локальный файловый fallback аватаров/медиа — F6.
- **ADR-1019-6** — retention `smart_messages` + включение deep/decay/resurrect — F7.
- **ADR-1019-7** — **AMEND F-15 §4** (устойчивость извлечения фактов; `LLMError`/пустой список) — F8.
- **Смежное:** `S10.18-12` (Nostalgia global-only) и `S10.18-13` (SSH-фрагмент) — см. ниже.

**🧾 Пункт отчёта/backlog (UPD2 §3, строки 150; UPD3 п.1) — БЕЗ фича-папки:** фрагмент SSH-пароля в **tracked**-файле
`plans/archive/security-rotation-finalize-round1016/spec.md:35` (история — commit `eb3fd4a`).
Действия: (1) **сообщить владельцу локацию файла** — сделано; (2) подтвердить статус в git (tracked, присутствует в истории) — подтверждено;
(3) **ОТМЕНИТЬ задачу** (ротация SSH признана ненужной — 10.17 F4 `ssh-rotation-cancelled-round1017`, untracked `current_task.md` — норма).
**✅ РЕШЕНИЕ UPD3 (итерация 2, п.1):** принят **вариант (а)** — фрагмент **оставить как есть**; риск принят (в маркере лишь неполный обрывок секрета);
историю git (`filter-repo`/rewrite) **НЕ трогаем**; задача **ОТМЕНЕНА и закрыта**. Human-gate **(d) закрыт** — rewrite истории не требуется.
**Сам секрет нигде не цитировать (R17).**

**🔴 UPD3 (итерация 2, 15.09.2026) — корректировки планирования:**

Ответ владельца: *«Принято, реализуем per-chat архитектуру»*. Ключевые правки (источник — `plans/current_task.md:178-216`):
- **(1) SSH-фрагмент:** вариант (а) — оставить как есть, историю не трогать, задача закрыта (см. выше).
- **(2) Мультичатовость:** хардкодить безлимиты глобально **ЗАПРЕЩЕНО**; безлимит — только per-chat override. **3 per-chat поля**: «Хранение импорта (дней)» (`0=вечно`), «Лимит токенов/вызовов» (`−1=безлимит`, `0=запрет`), «Лимит контекста» (`−1=безлимит`, `0=не задано`). Изоляция памяти строго по `chat_id` (аудит — F7 §4.6).
- **(3) целевой чат `-1002661910336`:** retention `0`, бюджеты `−1`, фон `−1`, контекст `−1` — **сидом** (`config/chat_settings_seed.json` + `services/chat_settings_seed.py`), id **не** в бизнес-логике; purge импорта для целевого чата **жёстко запрещён** guard'ом.
- **(4) «Сводка»:** бейдж **«Безлимит (∞)»** вместо цифр; статус **«Импорт: Вечно»** / «Импорт: 180 дней» (аддитивный контракт `limits`, R16).
- **(5) Дефолты:** консервативные глобальные (direct 100/500 000, фон 60/300 000) + per-chat безлимит для целевого чата; retention `limits.import_history_retention_days` дефолт 180; точный Δ каталога — `437/92/407/412/90/20` (+1 ключ, +2 группы, +1 вкладка).

**Центральный ADR итерации 2:** **ADR-1019-8** `per-chat-limits-and-seed` (`plans/features/budget-settings-section/`) — мультичатовая модель, sentinel-таблица, сид настроек чатов, guard, изоляция, контракт Сводки. AMEND: ADR-1019-2 (дефолты), ADR-1019-3 (Δ/D6), ADR-1019-4 (D3), ADR-1019-6 (D1/D1a/D1b/D7).

**Новые задачи итерации 2 (T-1853…T-1865):**

| ID | @ | Фича | Задача |
|---|---|---|---|
| T-1853 | @Architect | все | Гейт: ADR-1019-8 + обновление spec/ADR F2/F3/F4/F7 (итерация 2) — **DONE (Step 2)** |
| T-1854 | @Builder | F2 | `services/budget_limits.py` (sentinel-хелперы) + per-chat резолв `chat_usage` |
| T-1855 | @Builder | F2 | консервативные дефолты (100/500k; 60/300k) + тексты каталога |
| T-1856 | @Builder | F3 | каталог-Δ: 2 группы (`limits_chat_key`, `limits_chat_context`) + вкладка `mod_budgets` + JS-parity |
| T-1857 | @Builder | F3 | UI: 3 per-chat поля + тумблер безлимита + бейджи `∞`/`Запрещено` |
| T-1858 | @Builder | F3 | «Сводка»: аддитивный контракт `limits` + UI-тексты (`Импорт: Вечно`) |
| T-1859 | @Builder | F3 | `services/chat_settings_seed.py` + `config/chat_settings_seed.json` + вызов в `bot.py` (идемпотентно) |
| T-1860 | @Builder | F3 | тесты: каталог, Сводка, тумблер, сид настроек чатов, изоляция лимитов |
| T-1861 | @Builder | F4 | per-chat sentinel контекста `−1`/`0` + `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` |
| T-1862 | @Builder | F4 | дефолты контекста 5000/3000/16000 (предохранитель) + описания |
| T-1863 | @Builder | F7 | `services/retention_policy.py` + per-chat retention `0=вечно` + guard allow-list purge |
| T-1864 | @Builder | F7 | изоляция: SQLite **v11** (`(chat_id, import_key)` индекс) + `import_checkpoints.chat_id` + тесты |
| T-1865 | @Reviewer/@PM | все | Гейт: DoD, отсутствие хардкода id, изоляция, аддитивность R16, санкция Δ |

**Human-gate (вопросы владельцу) — после UPD3:**
- **(a)** живой curl-матрикс ingest-контракта BetterStack — @DevOps (маскированный вывод).
- **(b)** «token == pubkey — норма» на unified US — **считано принятым** (AMEND ADR-1018-1 D4).
- **(c)** семантика sentinel + Δ каталога + дефолты — **ПРИНЯТО в UPD3** (ADR-1019-8 §D2/D7/D8).
- **(d)** судьба git-истории с фрагментом SSH-пароля — **ЗАКРЫТО:** вариант (а), историю не трогаем (UPD3 п.1).
- **(e)** целевые лимиты контекста — **ПРИНЯТО:** 5000/3000/16000 предохранитель + per-chat `−1` (данными сида).

**Крытие UPD2 → фичи:**

| Раздел UPD2 | Фича(и) |
|---|---|
| **§1** бюджеты direct / безлимит / раздел + бары «Сводки» (стр. 131-132) | **F2**, **F3** |
| **§2** BetterStack ingest-контракт / Bearer / WARNING (стр. 133-149) | **F1** |
| **§3** SSH-фрагмент (стр. 150) | **пункт отчёта/backlog** (без фичи) |
| **§4** поле поиска по графу (стр. 152) | **F5** |
| **§5** объединение блоков «Статуса», убрать режим/версию (стр. 153) | **F5** |
| **§6** чекап: контекст 869 / token_counter (стр. 162,164,174) | **F4** |
| **§6** чекап: аватары/файлы ФС↔БД (стр. 158) | **F6** |
| **§6** чекап: память 11864/667/40, deep/decay/resurrect, retention (стр. 166) | **F7** |
| **§6** чекап: GraphRAG Memorize невалидный/пустой ответ (стр. 160) | **F8** |
| **§6** чекап: nano-gpt timeouts (стр. 173) | принято (фоллбэк работает) + **F8** (не терять факты) |

**Открытые вопросы для @Architect (историч., закрыты Step 2 и последующими шагами):** контракт и что делать с `token_equals_sentry_public_key` (F1, T-1778); семантика sentinel-безлимита и границы sandbox-пути (F2, T-1789); точные Δ каталога и место раздела «Бюджеты» (F3, T-1799); целевые значения контекста и развязка двух систем (F4, T-1809); макет объединённого «Статуса» (F5, T-1818); стратегия локального fallback аватаров (F6, T-1826); retention-политика и включение сна/декая (F7, T-1835); правила устойчивости извлечения фактов (F8, T-1845).
**Статус (историч.):** ✅ **COMPLETED + ЗААРХИВИРОВАН** (Step 8 @PM, 16.09.2026). Папки — `plans/features/<feature>/` (8) → перенесены в `plans/archive/<feature>/`. **@PM код не пишет.** Итог/метрики/техдолг/@DevOps-гейты — в блоке «✅ ИТОГ 10.19» выше. Коммит/деплой/@Memory-финал — Step 9–10 вне этого шага.

## Раунд 10.18 (15.09.2026): BetterStack US-регион (401) + разблокировка Сна/каскада + апгрейд Графа памяти + пенализация мета-фактов + Матрица ролей + единый источник настроек воркеров — 7 фич — ✅ COMPLETED + ЗААРХИВИРОВАН (Step 6 @Scanner + Step 7 @Architect Merge + Step 8 @PM, 15.09.2026)

**✅ ИТОГ 10.18 (15.09.2026):** реализация завершена, все **7 фич заархивированы** — перенесены
`plans/features/<feature>/` → **`plans/archive/<feature>/`** (@PM Step 8). В каждой папке сохранены
`spec.md` + `tasks.md` + ADR (`adr-1018-1…-7`). В `plans/features/` остались только 6 ранее существовавших
backlog-папок (`admin-debug-webview`, `config-read-path-audit`, `frontend-admin-bugfixes`,
`post-deploy-admin-minors`, `scam-incident-security-followup`, `user-aliases-admin`); пустых/осиротевших папок нет.
Ссылки на перемещаемые пути в `tests/` не найдены (grep `plans/features` — только комментарии/докстринги,
нечтения с диска; починка путей не потребовалась; `tests/test_tool_download_quality_round1017.py` — уже с
archive-fallback).
**Финальные метрики:** полный **pytest — 6139 passed / 0 failed** (база 10.17 = 6007 → **+132**; Scanner-итерации:
6042 → 6052 → 6083 → 6104 → 6137 → **6139** после фикс-прохода); `node --check web/app.js` clean; `JS-UNIT-OK`;
`VUE-MOUNT-OK`; `git diff --check` clean.
Каталог — **Δ=+1** (санкционированный F1): **REGISTRY 436 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 /
`TAB_RULES` = `CONFIG_TAB_TITLES` 19). **SQLite: v9 → v10** (nullable `edges.fact_id` + индекс, F3/ADR-1018-3;
идемпотентная/обратимая ALTER-миграция, FTS5/vec не затрагиваются); **новых PG-DDL нет**.
**Новых фича-флагов НЕТ** — manual-приоритет Сна (F2), graph-scoring-v2 (F3), metafact-penalty (F5) активны
**безусловно** (решение владельца); откат — `git revert`. Порядок роутеров `bot.py` не тронут; `media/`/`.env` не тронуты.
**Объём:** **7 фич, 75 задач** (T-1703…T-1777; порядок F7 → F2 → F3 → {F4 ∥ F5} → F6, F1 параллельно).
@Reviewer — **Approved** по всем батчам (Step 5).
@Scanner — **0 Critical / 0 High**; открыто **1 Low (S10.18-29) + 10 Info**; Medium **S10.18-30** (перф ×2-фазы
`graph_snapshot`, 241 мс → 55.5 мс), Low **S10.18-35** (перенос пенальти в эпи-мерж) и Info **S10.18-36**
(spec §3.1 ↔ ADR-1018-6 D4) закрыты фикс-проходом (§10.6). Отчёт:
`plans/reports/round10.18_scanner_audit.md` (§8–§10, сводки §10.4/§10.6).
@Architect — Merge Phase завершена: `plans/ARCHITECTURE.md` **§39** + SUPERSEDE/AMEND-пометки
(ADR-1018-1 AMEND раунда 4/5; ADR-1018-7 AMEND F-7 §6/F-14 §3.1 + частичный SUPERSEDE «воркеры читают только
`hot.get`»; ADR-1018-2 SUPERSEDE F-10 §5-6 + AMEND ADR-1017-3 §2.3/§2.4; ADR-1018-3 SUPERSEDE ADR-1015-2;
ADR-1018-4 AMEND F2 раунда 10.15; ADR-1018-5 AMEND ADR-1013-3 §2; ADR-1018-6 AMEND RBAC 10.5 §26).
**Коммит/деплой — @DevOps Step 9** (вне этого шага).

**🧾 Техдолг / остаточные находки 10.18 (перенесены @PM, Step 8 — не блокеры):**
- **S10.18-29 (Low, F2, deep-manual маркер):** `run_once(deep=False)` («Сон сейчас») не выставляет
  `_manual_deep_until`, хотя каскад реально запускает Глубокий сон → во время manual-каскада `deep_sleep.manual=False`
  и `active_until=None` вне окна; TTL маркера (900с) не связан с `_run_lock`/`_deep_lock`. Фикс — в `run_once`
  (ветка `deep=False`) или в `_maybe_deep_after_sleep(manual=True)`.
- **S10.18-12 (Info → backlog-задача T-1764):** `NostalgiaWorker` читает `memory.nostalgia_*` только через
  `hot.get` (**global-only**) — аналог симптома Сна не исправлен; перенос на `worker_settings`
  (`_key_for`-паттерн + per-chat `source` в статусе).
- **S10.18-13 (Info, вне батча / R10.18-12):** фрагмент SSH-пароля в **отслеживаемом** файле
  `plans/archive/security-rotation-finalize-round1016/spec.md:35` (ротация CANCELLED). Задача: вычистить строку
  плейсхолдером, проверить `git log -p`, при необходимости согласовать rewrite истории (`filter-repo`) с владельцем.
  Значение в backlog/отчёты/спеки/ADR **не копировать** (R17).
- **S10.18-18 (Info, F2):** явный `POST /api/memory/dream/run?deep=1` без `chat_id` прогоняет deep по всем
  кандидатам без капа `_MANUAL_DEEP_CASCADE_MAX` (осознанно; ограничен `max_chats_per_run` +
  `limits.deep_sleep_tokens_per_day`) → документировать в API-описании.
- **S10.18-19 (Info, F7/F2):** per-chat `tokens_today` суммирует `memory_dream_log` без фильтра `kind` → токены
  deep-прогонов/скипов того же чата входят в бюджет обычного Сна (pre-existing, теперь консистентно per-chat).
- **S10.18-20 (Info, F7):** поле `previous` в ответе kill-switch (`web/api/oversight.py:105-110`) теперь =
  эффективный гейт (с per-chat master-fallback), а не «прежнее явное значение» — семантика сместилась (аддитивно).
- **S10.18-31 (Info, F3):** нормализация STOP_LIST не ловит варианты с внутренним дефисом/пробелом
  («видео-сообщение», «голосовое сообщение») и морфологию («сообщения») — жёстко по ADR; ложных срабатываний нет.
- **S10.18-32 (Info, F3):** само-петля (`source_id == target_id`) даёт 2 строки в `re` → degree/score учитывают её
  дважды (pre-existing `UNION ALL`-семантика).
- **S10.18-33 (Info, F3):** `upsert_edge` — `INSERT … SELECT … FROM nodes WHERE id = ?`: при отсутствии узла вставка
  молча даёт 0 строк → факт коммитится без ребра; рекомендация — WARNING при `rowcount == 0`.
- **S10.18-37 (Info, F5 — живая проверка RAG):** множитель `importance` меняет RAG-порядок для **всех** чатов/фактов
  (было `weight×decay` → стало `×0.55…1.0`); логической ошибки нет, но требуется живой прогон RAG-качества
  (T-1724/T-1749) и фиксация как ожидаемого поведенческого изменения.
- **S10.18-34 (Info, агрегат):** сводка открытых Info Батча 1 (тот же класс, что -18/-19/-20).

Ниже — исторический документ планирования эпика (Step 1 @PM + Step 2 @Architect), сохранён для трассируемости.

**🔵 СТАТУС 10.18 при планировании (Step 1 @PM):** план создан @PM (Step 1). Фича-папки — `plans/features/` (6 на момент плана; итерацией 2 добавлена F7 `settings-worker-sync` → **итого 7**).
Спеки/ADR (Step 2) — за @Architect. **HEAD при планировании:** `118a03c` (docs-синхронизация 10.17).
**APP_VERSION** 2.57.0. **Baseline:** pytest **6007 passed / 0 failed**; каталог-инвариант
**REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19); SQLite **v9**.
Преемник — 10.17 (`plans/archive/*-round1017/`, 5 фич COMPLETED+DEPLOYED, 37 задач T-1666…T-1702).

**📌 ВАЖНО (Step 0 @Memory):** ТЗ 10.18 в ряде мест **построено на неверных посылках** и/или **прямо конфликтует
с действующими ADR** → требуется **5 новых ADR** (см. ниже) + human-gate для §5 и ручного деплоя. Диагностика:
- **§1:** `LogtailHandler` из `logtail-python` **не используется** с раунда 4/5. Реальная точка —
  `bot.py:141-145` → `BetterStackHandler(...)`; дефолт хоста `in.logs.betterstack.com`
  (`services/betterstack_handler.py:39,99,109`; конструктор уже принимает `host=`). Диагноз 401: в
  `LOGTAIL_SOURCE_TOKEN` залит **public key из `SENTRY_DSN`** (значение в ТЗ совпадает с public key), а не Source Token.
  В репо есть комментарий/тест, утверждающий обратное («совпадение — норма») — противоречие устранить.
  «Рантайм-подтягивание `.env`» невозможно без рестарта (`load_dotenv` при импорте, хендлер на уровне модуля).
- **§3.1/§3.2:** прямой конфликт с **ADR-1015-2** (degree = число рёбер, сиды топ-50, cap 120/240,
  `GRAPH_SEED_NODES` — код-константа) → **SUPERSEDE**. У ребра нет `importance` напрямую → Σ importance через
  join к `graph_facts` (perf-risk). Canvas-предохранитель ADR-1013-2 — решить риск 500–800 узлов.
- **§3.3:** конфликт с F2 10.15 (физика всегда вкл, `iterations:250`) → нужно 150 + отключение physics по
  `stabilizationIterationsDone`.
- **§2.3:** конфликт с **ADR-1017-3** («без живого tick-таймера», пересчёт на рендере + polling 15 с);
  **WebSocket в проекте ОТСУТСТВУЕТ**. Дефект: `dreamPhaseBadge`/`deepPhaseBadge` (`web/app.js:1216-1248`) при
  `active=true`/`active_until=null` → «Сон идёт»; backend `memory_agi.py:482-501` считает `active_until` только
  при `dream_in` (окно) → ручной прогон вне окна даёт `null`; `runDreamNow` (`app.js:4974-4993`) не перезагружает
  `cognition` (только beliefs/log через 3 с) → стейл до 15 с. Это же закрывает техдолг **S10.17-2**.
- **§2.2:** конфликт с **F-10 §5-6** («manual не минует gate/budget»); при этом `window_skip` manual **уже**
  обходится (`dream_worker.py:588`). Реальные причины обрыва: kill-switch `gates_enabled(chat_id,"dream")`
  (`:571-577`), бюджеты/near-limit (`:601-620`), `distilled==0` из-за порогов, `DREAM_ENABLED=False` /
  `DEEP_SLEEP_ENABLED=False` (default).
- **§2.4 (0 черт):** traits вызываются только из глубокого сна (`dream_worker.py:1317-1327`); глубокий сон не
  каскадируется при `deep_sleep_enabled=false` / `trigger != after_sleep` / `distilled==0`
  (`_maybe_deep_after_sleep:1100-1119`); traits требуют `bot_self_reply`-фактов. Причина — цепочка флагов/порогов,
  а не промпт.
- **§4:** конфликт с канон-политикой **ADR-1013-3** (`FACT_EXTRACT_PROMPT` — канон R46-2 байт-в-байт +
  `PROMPT_MIGRATIONS`). Важно: `importance` присваивает **не LLM**, а `rule_importance()`
  (`services/database.py:82-104`) + clamp 1..10 в `insert_graph_fact` → хард-лимит стоп-листа логичнее в
  `insert_graph_fact`/`_memorize_facts_inner`.
- **§5:** завязано на каталог-инвариант; перестройка = **санкционированный Δ каталога**. ТЗ неоднозначно → human-gate.
- **Секреты:** `plans/current_task.md` — untracked и в `.gitignore:70`; токены/SSH-пароль из ТЗ **нельзя**
  коммитить/вносить в спеки/ADR/KG. **Ротация SSH CANCELLED** — пароль действующий (вне раунда).

**План (Step 1): 6 фич (нумерация продолжает T-1702 → T-1703…T-1757, 55 задач).**
**ФАКТ (Step 8): 7 фич / 75 задач T-1703…T-1777** — итерацией 2 добавлена **F7 `settings-worker-sync`** (T-1758…T-1766) и расширены F2 (T-1767…T-1772) / F3 (T-1773…T-1777). Таблица ниже — историческая:

| # | Фича (папка) | Тип | ТЗ § | Зависит от | Приоритет | Задачи | Новый ADR |
|---|---|---|---|---|---|---|---|
| **F1** | `betterstack-us-region-401` | backend/infra | §1 | — (@DevOps: .env+restart) | **P0** (прод-шум 401) | T-1703…T-1711 (9) | ✅ ADR-1018-1 (host/token policy) |
| **F2** | `sleep-manual-cascade-badges` | backend+frontend | §2.1–§2.4 | — | **P0** (0 дистилляции/0 черт) | T-1712…T-1726 (15) | ✅ ADR-1018-2 (SUPERSEDE/AMEND F-10 §5-6) + AMEND ADR-1017-3 |
| **F3** | `graph-density-scoring-stoplist` | backend | §3.1–§3.2 | — | **P1** | T-1727…T-1735 (9) | ✅ ADR-1018-3 (**SUPERSEDE ADR-1015-2**) |
| **F4** | `graph-physics-stabilization` | frontend | §3.3 | **F3** (ёмкость) | **P1** | T-1736…T-1741 (6) | ◻ рекомендуется (физика графа) |
| **F5** | `metafact-penalty-extractor-prompt` | backend+промпт-канон | §4 | **F3** (общая STOP_LIST) | **P1** | T-1742…T-1749 (8) | ✅ ADR-1018-4 (канон-миграция + penalty) |
| **F6** | `role-matrix-settings-actualization` | backend/access+frontend | §5 | Δ-свод F1…F5 | **P2** | T-1750…T-1757 (8) | ✅ ADR-1018-5 (матрица + Δ каталога) |

> **Поправка Step 8 (факт vs план):** фактическая привязка ADR — **F4 → ADR-1018-4** (физика),
> **F5 → ADR-1018-5** (канон-миграция + penalty), **F6 → ADR-1018-6** (матрица), **F7 → ADR-1018-7**
> (единый источник настроек). В таблице-плане (выше) ADR-номера F4–F6 устарели; F7 в план не входила.
> Итоговый порядок исполнения — **F7 → F2 → F3 → {F4 ∥ F5} → F6** (F1 — параллельная инфра-плоскость @DevOps).

**Рекомендуемый порядок исполнения:** **{F1 ∥ F2} → F3 → {F4 ∥ F5} → F6.**
Обоснование: **F1** и **F2** — прод-блокеры (шум 401; пустой интеллект), разные плоскости (инфра логов vs воркеры/UI),
могут идти параллельно; **F3** — фундамент для F4 (плотность 500–800 → физика) и даёт общую STOP_LIST для F5;
**F4** и **F5** независимы друг от друга (`web/app.js` vs `services/database.py`+канон); **F6** — последняя, сводит
санкционированные Δ каталога (F1 +1 REGISTRY, возможные Δ F2/F5) в единый обновлённый инвариант.
**⚠️ Пересечения файлов:** F2 и F4 делят `web/app.js` (вливать ступенями **F2 → F4**); F3 и F5 делят
`services/database.py` (согласованное вливание, общий STOP_LIST); F1/F6 делят `config/settings.py` (Δ каталога — сводить);

**Контент по фичам (сжато):**
- **F1 (`betterstack-us-region-401`):** фикс хоста на US + Source Token (не public key), аудит Sentry↔BetterStack,
  новый env-ключ хоста (REGISTRY **435→436**, санкц. Δ), startup-лог (R17), рестарт-зависимость `.env`; curl-матрикс
  токен×хост — только с маскированным выводом.
- **F2 (`sleep-manual-cascade-badges`):** ослабление порогов/пре-гейтов (§2.1); manual-приоритет над
  window_skip/gate/budget (§2.2); реактивные бейджи без WebSocket (§2.3, закрывает S10.17-2); каскад
  Сон→Глубокий→Личность + подробное логирование Личности (§2.4); исследование `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED`.
- **F3 (`graph-density-scoring-stoplist`):** Σ importance (join `graph_facts`) + STOP_LIST центров
  (`видеосообщение, голосовое, сообщение, фото, кружочек, ссылка`) + ×2 за Убеждение/Парадигму; сиды Топ-150/200;
  итог 500–800 узлов; perf-бюджет; SUPERSEDE ADR-1015-2.
- **F4 (`graph-physics-stabilization`):** `stabilization.iterations: 150` + `stabilizationIterationsDone` →
  `physics.enabled=false`; сохранить `reducedMotion`/поиск/подсветку.
- **F5 (`metafact-penalty-extractor-prompt`):** инструкция промпта про СУТЬ/формат (канон-миграция с PREV);
  хард-лимит importance 1–2 для стоп-лист-слов (`видеосообщение, голосовое, фото, кружочек, ссылка, стикер`)
  в точке записи факта; мета-факты не проходят гейты Сна / не доминируют в RAG.
- **F6 (`role-matrix-settings-actualization`):** «Матрица ролей» = фактическое распределение настроек по разделам
  мини-аппа (`web/api/access.py:319-360` — `param_permissions_list`/`group_tab`/`CONFIG_TAB_TITLES`); санкц. Δ
  `TAB_RULES`/`GROUPS`/`mapped` + пин-тесты; RBAC синхронизировать.
- **F7 (`settings-worker-sync`):** единый источник истины настроек — воркеры/статус-API читают
  **per-chat DB → глобальный DB → env-дефолт** через `services/worker_settings.py`; реактивность без
  рестарта (джоб всегда зарегистрирован, решение в тике); `LISTEN chat_params_updated`; статус-API отдаёт
  `source` (R16-аддитивно); каталог-Δ=0. **Backlog-кандидат (T-1764):** аналогичный рассинхрон
  `memory.nostalgia_enabled` — `NostalgiaWorker` читает только глобальный слой (`hot.get`), слой чата не
  резолвится; перенести на `worker_settings` (вне P0 F7). **S10.18-12:** подтверждено, что задача в backlog
  есть; код Nostalgia в батче 1 НЕ трогается.

**🧾 Техдолг 10.18 (R10.18-12, pre-existing, вне батча 1 — Info):** в ОТСЛЕЖИВАЕМОМ git-файле
`plans/archive/security-rotation-finalize-round1016/spec.md` (строка ~35) остался фрагмент SSH-пароля
от раунда-предшественника (ротация была CANCELLED, но фрагмент присутствует в рабочей копии и истории).
**Задача:** вычистить фрагмент из отслеживаемого файла (заменить плейсхолдером), проверить `git log -p`
на наличие фрагмента в истории и, при необходимости, согласовать с владельцем rewrite истории (filter-repo).
Сам секрет в задачи/отчёты/спеки НЕ копировать (R17). Не блокирует раунд 10.18.
**→ Статус Step 8: перенесено в сводный «🧾 Техдолг / остаточные находки 10.18» (S10.18-13) в блоке «✅ ИТОГ 10.18» выше.**

**Покрытие ТЗ → фичи (`plans/current_task.md`):**

| Раздел ТЗ | Фича(и) |
|---|---|
| **§1** BetterStack 401 / US-хост / аудит Sentry / рантайм-.env | **F1** |
| **§2.1** снятие «паранойи» по токенам | **F2** (T-1714) |
| **§2.2** блокировка ручного запуска Сна | **F2** (T-1715) |
| **§2.3** рассинхрон бейджей | **F2** (T-1719…T-1721) |
| **§2.4** каскад Сон→Глубокий→Личность + логирование | **F2** (T-1716…T-1718) |
| **§3.1** скоринг/STOP_LIST/×2 | **F3** |
| **§3.2** плотность 500–800 узлов | **F3** |
| **§3.3** физика vis-network | **F4** |
| **§4** пенализация мета-фактов + промпт | **F5** |
| **§5** Матрица ролей | **F6** |

**ADR-конфликты, требующие нового ADR:** **ADR-1018-1** (F1, host/token policy); **ADR-1018-2** (F2,
SUPERSEDE/AMEND F-10 §5-6 + AMEND ADR-1017-3); **ADR-1018-3** (F3, **SUPERSEDE ADR-1015-2**); **ADR-1018-4**
(F5, канон-миграция ADR-1013-3 + penalty); **ADR-1018-5** (F6, матрица + санкц. Δ каталога).

**Открытые вопросы для @Architect:** политика BetterStack host/token + Sentry (F1, T-1703); границы manual-обхода
и реактивность бейджей без WebSocket (F2, T-1712); формула Σ importance/STOP_LIST/×2/perf/canvas (F3, T-1727);
контракт опций физики (F4, T-1736); канон-миграция промпта + точка хард-лимита (F5, T-1742); целевая карта
«Матрицы ролей» + точные Δ (F6, T-1750).
**Human-gate:** (a) эталон «реального распределения» для §5 (@PM → владелец); (b) подтверждение обхода
safety-гейтов ручным запуском (§2.2); (c) SSH-пароль действующий — в репо не вносить.
**Статус (историч.):** ✅ **COMPLETED + ЗААРХИВИРОВАН** (Step 8 @PM, 15.09.2026). Папки — `plans/features/<feature>/`
(7) → перенесены в `plans/archive/<feature>/`. **@PM код не пишет.** Итог/метрики/техдолг — в блоке «✅ ИТОГ 10.18» выше.
Коммит/деплой/@Memory-финал — Step 9–10 вне этого шага.

## Раунд 10.17 (14.09.2026): UPD3 — мобильный мини-апп (DNS), tool-download quality, бейджи Сна, ОТМЕНА ротации SSH, warnings-hygiene — 5 фич — ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН (Step 8 @PM + Step 9 @DevOps + Step 10 @Memory, 14.09.2026 · commit `b6c153f`)

**✅ ИТОГ 10.17 (14.09.2026):** реализация завершена, все **5 фич заархивированы** — перенесены
`plans/features/*-round1017/` → **`plans/archive/*-round1017/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 6007 passed / 0 failed** (база 10.16 = 5936 → **+71**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`; `git diff --check` clean.
Каталог — **Δ=0**: **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19); новых ключей нет.
БД: **новых миграций нет** (SQLite остаётся **v9**; PG без изменений).
**Объём:** **5 фич, 37 задач** (T-1666…T-1702).
@Reviewer — **APPROVED** (итерация 2). Итерация 1 — **Rejected**: 3 **Medium** — F4 overclaim ротации в
`plans/ARCHITECTURE.md` (§10/§25/§37), F5 транзиенты аватаров на 2 из 6 сайтов (rate-limit залипал в негатив-кэш
на час + трейс), F2 дублирование меню качества (T-1679). Все закрыты @Builder (CANCELLED-пометки в
`plans/ARCHITECTURE.md:326,328,616,624,628`; ветка `except (TelegramRetryAfter, TelegramNetworkError)` на **всех 6**
сайтах `web/api/avatars.py` + тесты некэширования; единый хелпер `services/media_send.py`, обе ветки делегируют).
Low L1–L8 закрыты (`plans/reports/round10.17_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium / 2 Low / 3 Info**. Medium **S10.17-1** (docs-only overclaim
ротации в архивной спеке 10.16 F5) **закрыт @Architect на Merge** (CANCELLED-баннер, DoD помечены); Low **S10.17-2**
(текст бейджа при `cognition==null`) и **S10.17-3** (доки-счётчики — синхронизированы с 6007) — техдолг/не блокеры;
Info S10.17-4/-5/-6 — не блокеры (`plans/reports/round10.17_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§38** + связанные §1/§5/§8/§9/§25).
Артефакты в архиве: `spec.md` + `tasks.md` (×5) + ADR-1017-1 (`adr-1017-1-miniapp-hostname-dns.md`),
ADR-1017-2 (`adr-1017-2-tool-download-quality.md`, **SUPERSEDE ADR-1016-1 §2 п.3/§3**),
ADR-1017-3 (`adr-1017-3-sleep-badge-countdown.md`).
**Симптомы ТЗ закрыты:** F1 — диагностика мини-аппа (HEAD `/web/`+`/healthz`, host-only startup-лог, no-CDN-гейт
с vendor) — живой DNS/Android-смоук @DevOps; F2 — tool-скачивание реально доводит `probe → tdq:<height> →
needs_quality` + callback; F3 — бейджи Сна показывают остаток / `до HH:MM` (+glow), эмодзи целы; F4 — пометки
ОТМЕНЫ ротации в README/ARCHITECTURE/backlog/архиве, кода ноль; F5 — политика логов на всех 6 сайтах
`web/api/avatars.py`, brotli WONTFIX (Caddy `zstd+gzip`).
**Фичи (финал, все ✅ COMPLETED):** F1 `miniapp-mobile-dns-round1017` (T-1666…T-1674, 9) ·
F2 `tool-download-quality-round1017` (T-1675…T-1684, 10) · F3 `sleep-badge-countdown-round1017` (T-1685…T-1691, 7) ·
F4 `ssh-rotation-cancelled-round1017` (T-1692…T-1695, 4) · F5 `warnings-hygiene-round1017` (T-1696…T-1702, 7).
Пути артефактов → **`plans/archive/*-round1017/`**.

**🧾 Техдолг / гейты (10.17):** Low **S10.17-2** (при `cognition==null` бейджи дают «Сон через —»/«Глубокий сон
через —» вместо чистого `—`; §3.4 спеки vs псевдокод §3.2 противоречивы — закреплено тестами, функц. вреда нет);
Info **S10.17-4** (tool-путь скачивания не вызывает `log_download_env_once()` — паритет диагностики),
**S10.17-5** (callback `tdq:` не проверяет hot-флаг `flags.download_enabled`), **S10.17-6** (`/healthz` отдаёт
`APP_VERSION` — принято F1 §3.1 L8; `query=%r` — pre-existing, вне диффа). **WONTFIX** — brotli (в репо build-time
only; Caddy требует `xcaddy`; `zstd+gzip` активны). **@DevOps-гейты ЗАКРЫТЫ деплоем:** DNS-диагностика
(**T-1667/T-1668/T-1671/T-1673** — F1) — A→198.46.175.136, AAAA пусто, TTL 50, `HEAD /web/`=200,
`/healthz` GET+HEAD=200; подтверждение `zstd+gzip`/`Content-Encoding` (**T-1699** — F5) — gzip подтверждён.
Live Android-смоук остаётся ручным шагом владельцу (инструкция в отчёте @DevOps).
**§4 ротация SSH — CANCELLED** (закрыта отменой, а не выполнением; **не открытый гейт**).

**Статус:** ✅ **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН** (Step 8 @PM + Step 9 @DevOps + Step 10 @Memory,
14.09.2026). **Деплой:** commit **`b6c153f`** (`fix(services,handlers,web,docs,plans): раунд 10.17 — ...
(тесты 6007)`), push `772f192..b6c153f`, прод fast-forward `eb3fd4a..b6c153f`, `admin_bot` active PID
**2016726**, лог без traceback; `/api/health`=**200**, `/healthz` GET+HEAD=**200** (no-store),
`HEAD /web/`=**200**, `/api/memory/graph`=**401**, `/api/persona/health`=**401**; DNS A→198.46.175.136
(AAAA пусто, TTL 50), LE notAfter 2026-11-28, Caddy `encode zstd gzip` (gzip подтверждён); миграций/env-правок
нет. **KG (Step 10 @Memory):** создан `release-round1017` (alias `release-b6c153f`) + Feature F4 + финальные
метрики; фичи F1–F5 → COMPLETED+DEPLOYED; ADR-1017-1/2/3 + SUPERSEDES ADR-1016-1; компоненты и Risk-узлы
закрыты; техдолг — `tech-debt-round10.17`. Ниже — исторический документ планирования эпика
(Step 1 @PM + Step 2 @Architect).

**Эпик:** `Epic: UPD3 багфиксы round1017` (@Memory, Step 0).
**Источник ТЗ** — `plans/current_task.md` (**UPD3**, строки 155–160); смежное — **UPD2** (строки 148–153, `DownloadError`/мобильный мини-апп).
**HEAD при планировании:** `772f192` (docs-синхронизация 10.16). **APP_VERSION** 2.57.0.
**Базовая линия (@Memory Step 0):** pytest **5936 passed / 0 failed**; каталог-инвариант **REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / `TAB_RULES` 19** (**Δ=0**); SQLite **v9**; прод `eb3fd4a` / PID **1976836**.
Преемник — 10.16 (`plans/archive/*-round1016/`, 5 фич COMPLETED+DEPLOYED, 41 задача T-1625…T-1665).
**Контекст Step 0 (@Memory):** §1 — `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL` (`config/settings.py:170-173,987-989`), `/menu` (`handlers/menu.py:48-66`) и домен/схема/путь **не менялись** в 10.13–10.16; в `web/` внешних CDN нет (self-host 10.16) → `ERR_NAME_NOT_RESOLVED` = сбой резолва **топ-домена `admin-bot.duckdns.org`** на Android (A→`198.46.175.136`, AAAA нет). §2 — ADR-1016-1 (10.16) явно нормировал «quality в JSON-Schema НЕ добавляется» → **нужен SUPERSEDE**. §3 — бейджи показывают **целевой час**, не остаток (`web/app.js:1210-1245`, `web/api/memory_agi.py:75-88,425-546`). §4 — **ротация ОТМЕНЕНА** (docs-only, без кода). §5 — 3 WARNING `web/api/avatars.py` (генеральный `except` + `exc_info=True`) + «brotli» (в репо только build-time; Caddy brotli требует плагина, zstd+gzip уже включены).
**Инварианты:** каталог-Δ=0, **R17**, **R16**, порядок роутеров `bot.py` (только DI-kwargs), `media/`/`.env` не трогать, **не возвращать внешние CDN**, **Caddy/DNS — вне репо (@DevOps)**.

**5 фич (нумерация продолжает T-1665 → T-1666…T-1702, 37 задач):**

| # | Фича (папка) | Тип | ТЗ / UPD3 | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `miniapp-mobile-dns-round1017` | frontend+infra (DNS @DevOps) | **UPD3 §1** (стр. 155–156) + UPD2 §4 | — (внешняя инфра @DevOps) | **P0** (прод-блокер) | T-1666…T-1674 (9) |
| **F2** | `tool-download-quality-round1017` | backend (tools/download/LLM) | **UPD3 §2** (стр. 157) + UPD2 §1 | — (гейт `flags.download_enabled`) | **P0** (прод-баг) | T-1675…T-1684 (10) |
| **F3** | `sleep-badge-countdown-round1017` | frontend | **UPD3 §3** (стр. 158) | — (данные `/api/memory/cognition/status` уже есть) | P1 | T-1685…T-1691 (7) |
| **F4** | `ssh-rotation-cancelled-round1017` | docs (**без кода**) | **UPD3 §4** (стр. 159) — **ОТМЕНА** | 10.16 F5 `security-rotation-finalize-round1016` (**отменяется**) | **P0 (doc)** | T-1692…T-1695 (4) |
| **F5** | `warnings-hygiene-round1017` | backend+docs/infra | **UPD3 §5** (стр. 160) | — (Caddy — @DevOps, вне репо) | P2/P3 | T-1696…T-1702 (7) |

**Рекомендуемый порядок исполнения:** **F2 → F1 → {F3 ∥ F5} → F4.**
Обоснование: **F2** — прод-блокер скачивания (tool спрашивает качество; SUPERSEDE ADR-1016-1); **F1** — прод-блокер мобильного мини-аппа (диагностика DNS — @DevOps, может идти параллельно F2, разные плоскости); **F3** — UI-баг (независим по файлам `web/app.js`); **F5** — гигиена (не блокер); **F4** — docs-only, можно последней. **⚠️ F1 и F3 обе трогают `web/` (F1 — только при регрессе; F3 — `app.js`), синхронизировать при параллельной работе. F2 — backend, конфликтов с F1/F3 нет.**

**Контент по фичам (сжато):**
- **F1 (`miniapp-mobile-dns`):** Android `net::ERR_NAME_NOT_RESOLVED`, десктоп ок; после 10.16 внешних CDN нет, домен/путь не менялись → сбой резолва топ-домена. Гипотезы: блокировка `duckdns.org` мобильными операторами; протухшая/пустая запись DuckDNS (A→`198.46.175.136`, AAAA нет); Android Private DNS/DoH; кэш. Нужны: DNS-чек-лист @DevOps (резолверы/операторы/AAAA/LE), живой Android-смоук, регресс-аудит репо (git-история `settings.py:170-173,987-989`, `menu.py:48-66`, `web/*`), возможный фоллбэк hostname (ADR), статический гейт «нет внешних CDN».
- **F2 (`tool-download-quality`):** `_download_media` (`services/tool_router.py:564-622`) не скачивает и не спрашивает качество; Fast-Track (`handlers/video_download.py:284-343`) — эталон. **SUPERSEDE ADR-1016-1** в части «quality в JSON-Schema отклонён» (новый ADR-1017-2); `quality` (enum `_DOWNLOAD_QUALITIES`) в схему; запрос качества как Fast-Track; pending(url/qualities/TTL); фикс падения; `services/media_send.py`; R17; регресс-тесты (direct `.mp4` + платформа, моки yt-dlp/cobalt); лимиты tool-loop 4/2 — не менять.
- **F3 (`sleep-badge-countdown`):** `dreamPhaseBadge`/`deepPhaseBadge` (`web/app.js:1210-1245`) показывают `next_wake_at`/`next_run_at` как `HH:MM`; требуется остаток (`Сон через 2ч 15м`, `Глубокий сон через …`), вне фазы вместо «выключен»; в фазе — `до HH:MM` (`active_until`) + свечение; **эмодзи не трогать**; база `now` — `generated_at`; новый `fmtCountdown`; `fmtClock` не ломать.
- **F4 (`ssh-rotation-cancelled`):** решение владельца — секреты в untracked `plans/current_task.md` — норма, ротация **не нужна**; **отменить** задачу 10.16 F5; docs-only: пометка в backlog/архиве + README без overclaim; кода — ноль; R17.
- **F5 (`warnings-hygiene`):** 3 WARNING `web/api/avatars.py` (`:146-148,180-182,208-211/220-223` — генеральный `except Exception` + `exc_info=True` на ожидаемых сбоях) → политика уровней (ожидаемое — debug/без трейса; неожидаемое — WARNING, R17-safe); «brotli»: в репо **build-time only** (`scripts/requirements-font.txt`, OD17), Caddy brotli требует `xcaddy`/`http.encoders.brotli`, `zstd+gzip` уже включены (10.16) → решение+доки (Caddy — @DevOps).

**Покрытие UPD3 → фичи (`plans/current_task.md`):**

| Раздел UPD3 | Фича(и) |
|---|---|
| **§1** «Админка на десктопе работает, на Android `net::ERR_NAME_NOT_RESOLVED`; началось после последних ТЗ» (стр. 155–156) | **F1** |
| **§2** «Через tool calling видео не скачивается и не спрашивает качество (должно спрашивать); прямой путь — ок» (стр. 157) | **F2** |
| **§3** «"Сон через 11:00" → остаток до начала; "Глубокий сон выключен" → остаток; в фазе — "до HH:MM", бейдж светится; эмодзи не трогать» (стр. 158) | **F3** |
| **§4** «Секреты в файле — норма, файл не в репо, ротация не нужна — **отмени задачу**» (стр. 159) | **F4** (отмена задачи 10.16 F5, **без кода**) |
| **§5** «3 WARNING в аватарах (старый код); "brotli" требует плагина Caddy — обработать» (стр. 160) | **F5** |
| Смежное **UPD2 §4** (стр. 153): мини-апп Android + «~1 минута» | **F1** (повтор/эскалация) |
| Смежное **UPD2 §1** (стр. 149–150): `DownloadError` tool/Fast-Track | **F2** |

**Открытые вопросы для @Architect:** стратегия hostname/DNS и граница «репо vs инфра», живой Android-смоук (F1, T-1666); контракт запроса качества в tool-loop + формат `quality` в JSON-Schema + pending/TTL + SUPERSEDE ADR-1016-1 (F2, T-1675); формат остатка/точность/поведение `enabled=false`, «эмодзи не трогать» (F3, T-1685); формулировка пометки об отмене ротации и README-политика (F4, T-1692); классификация 3 WARNING + решение по brotli/`xcaddy` (F5, T-1696).
**Статус (историч.):** ✅ **COMPLETED + ЗААРХИВИРОВАН** (Step 8 @PM, 14.09.2026). Папки — `plans/features/*-round1017/` (5) → перенесены в `plans/archive/*-round1017/`. **@PM код не пишет.**

## Раунд 10.16 (14.09.2026): Багфиксы скачивания + доставка Гайда + полный аудит + мобильный мини-апп + ротация секрета — 5 фич — ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН (Step 8 @PM + Step 9 @DevOps + Step 10 @Memory, 14.09.2026 · commit `eb3fd4a`)

**✅ ИТОГ 10.16 (14.09.2026):** реализация завершена, все **5 фич заархивированы** — перенесены
`plans/features/*-round1016/` → **`plans/archive/*-round1016/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5936 passed / 0 failed** (база 10.15 = 5774 → **+162**; итерация 1 — 5910);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`; `git diff --check` clean.
Каталог — **Δ=0**: **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19); новых ключей нет.
БД: **новых миграций нет** (SQLite остаётся **v9**; PG без изменений; F2 — DML-миграция канона гайда, `canon_version`/`canon_delivered_version`).
**Объём:** **5 фич, 41 задача** (T-1625…T-1665).
@Reviewer — **APPROVED** (итерация 2). Итерация 1 — **Rejected**: **Critical** F4 — CSP `script-src 'self'` без `'unsafe-eval'`
ломает рантайм-компилятор Vue (`Function()`), мини-апп не монтируется; **High** F1 — логирование URL/`str(exc)` в
`tools/video_downloader.py` при заявленном «R17-скан чист»; **High** F2 — доставка канона гайда не гарантирована
(нужен ручной reset); **High** F5 — README рапортовал о невыполненной ротации SSH как о факте. Все закрыты @Builder
(CSP-вариант A `'unsafe-eval'` + поведенческий гейт `tests/js/vue_mount_test.js`; caplog-тесты R17; одноразовая
форс-доставка канона с маркером; честная модальность README); Medium/Low итер.1 закрыты (`plans/reports/round10.16_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium** (итерация 2; закрыты High S10.16-1 — R17-утечка URL на
youtube-пути, Medium S10.16-2 — force-доставка без бэкапа), остаётся **Low 1** — `S10.16-9` (latent hardening)
(`plans/reports/round10.16_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§37** + связанные §1/§3/§5/§9).
Артефакты в архиве: `spec.md` + `tasks.md` (×5) + ADR-1016-1 (`adr-1016-1-download-contract.md`),
ADR-1016-2 (`adr-1016-2-selfhost-csp.md`), ADR-1016-3 (`adr-1016-3-guide-canon-versioning.md`) + `ssh-rotation-checklist.md`.
**Симптомы ТЗ закрыты:** F1 — tool-путь `download_media` (невалидный `"direct"` → `ValueError`) + Fast-Track
probe-диагностика; F2 — фактическая доставка «Гайда по фичам» (версионирование канона, force-reset, PG-only write-path);
F3 — полный аудит 10.13–10.15 + 7 смоук-наборов + FIX Low-техдолга (S10.13-6b/-13, R10.15-4/-10/-11);
F4 — мини-апп на Android (self-host CDN/Vue/Chart.js/Tailwind, CSP, сокращение загрузки); F5 — git-гигиена
`current_task.md` + скан секретов + README/R17.
**Фичи (финал, все ✅ COMPLETED):** F1 `download-fix-round1016` (T-1625…T-1633, 9) · F2 `guide-delivery-round1016`
(T-1634…T-1641, 8) · F3 `audit-recent-epics-round1016` (T-1642…T-1650, 9) · F4 `miniapp-mobile-round1016`
(T-1651…T-1659, 9) · F5 `security-rotation-finalize-round1016` (T-1660…T-1665, 6).
Пути артефактов → **`plans/archive/*-round1016/`**.

**🧾 Техдолг Low (ОТКРЫТ, 10.16 — не блокеры):** `S10.16-9` (latent hardening: 4 raise-сайта
`tools/video_downloader.py:767,772,899,904` интерполируют `{exc}` / тело cobalt-ответа; доступного лог-пути,
печатающего сообщение, нет — утечки нет); **WONTFIX** `S10.13-9` (Timeline-лор in-memory inject vs
`chat_lore_history` — осознанный источник), `S10.13-11` (LIKE-маркер парадигм матчит 2 сериализации — в проде
невоспроизводимо), `R10.14-4` (`dynamic_traits` без `chat_id` — модель «общий характер бота», не утечка).
Источник — `plans/reports/round10.16_scanner_audit.md` §2/§5 + `plans/reports/round10.16_audit.md` §3.

**✅ ГЕЙТЫ ЗАКРЫТЫ ДЕПЛОЕМ (@DevOps Step 9 + @Memory Step 10, 14.09.2026):** **T-1657** — DNS A→198.46.175.136
(AAAA нет), LE notAfter 2026-11-28, `/web/` GET 200 + CSP; Caddy `encode zstd gzip` включено (backup) — сжатие
есть. **T-1641** — гайд доставлен: `canon_version=2`, `canon_delivered_version=2`, `canon_drift=False`,
`prev_html` сохранён, `html_len==seed_len==4592`. **T-1661/T-1664** — SSH-ключ работает; парольный вход
сохранён намеренно (по требованию владельца), полная ротация пароля — по желанию владельца. Прод-смоук
скачивания (F1) — ручной шаг владельцу. **R17-долг (repo-wide):** `plans/current_task.md` содержит SSH-пароль
в рабочей копии (untracked, `.gitignore:70`; в истории утечки нет — скан чист).
**⚠️ ОТМЕНА (UPD3 §4, раунд 10.17):** задача ротации SSH признана **НЕ НУЖНОЙ** — секреты в untracked
`current_task.md` являются нормой, файл не попадает в репозиторий. R-запись выше **не является открытым
действием**; фича F4 10.17 `ssh-rotation-cancelled-round1017` снимает её docs-пометкой **без кода**.
**Статус:** ✅ **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН** (14.09.2026). Реализация @Builder (F1–F5),
@Reviewer **APPROVED** (итерация 2; итер.1 Rejected — Critical CSP `script-src 'self'`), @Scanner **0 C/H/M**
(Low 1 — `S10.16-9`), @Architect — `plans/ARCHITECTURE.md` **§37**. Артефакты: **`plans/archive/*-round1016/`**
(**5 папок**). **Деплой:** commit **`eb3fd4a`**, push `18a9aa1..eb3fd4a`, прод fast-forward `d01a539..eb3fd4a`,
`admin_bot` active PID **1976836**, `/api/health`=**200**, миграций БД нет. KG-синхронизация (Step 10 @Memory):
эпик → COMPLETED+DEPLOYED, релиз-узел `release-round1016`.
Ниже — исторический документ планирования эпика (Step 1 @PM + Step 2 @Architect).

**Эпик:** `Epic: Багфиксы + полный аудит round1016` (@Memory, Step 0).
**Источник ТЗ** — `plans/current_task.md` (**UPD2**, строки 148–153) + §1–§7 (строки 1–76). **HEAD при планировании:** `18a9aa1`
(docs-синхронизация 10.15). **APP_VERSION** 2.57.0.
**Базовая линия (@Memory Step 0):** pytest **5774 passed / 0 failed**; `node --check web/app.js` clean;
`node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог-инвариант **REGISTRY 435 / GROUPS 90 / Settings 406 /
categorized 411 / mapped 88 / `TAB_RULES` 19** (**Δ=0**, новых ключей нет); SQLite **v9** (миграций БД нет).
Преемник — 10.15 (`plans/archive/*-round1015/`, 9 фич COMPLETED+DEPLOYED, 76 задач T-1549…T-1624).
**Контекст @Memory Step 0:** `plans/current_task.md` **не отслеживается git** (`.gitignore:70`; `git ls-files` — «did not match»),
в истории пароля нет, но рабочая копия содержит SSH-пароль (`:62-65`) → ротация (repo-wide R17-долг).
Остаются: **R17** (секреты `{configured,last4}`), **R16** (id — ключ), порядок роутеров `bot.py` (только DI-kwargs),
`media/`/`.env` не трогать, self-host DOMPurify/vis-network, пин-тесты каталога.

**5 фич (нумерация продолжает T-1624 → T-1625…T-1665, 41 задача):**

| # | Фича (папка) | Тип | ТЗ / UPD2 | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `download-fix-round1016` | backend (tools/download) | **UPD2 §1** (+§1 строки 3-8) | — (гейт: `flags.download_enabled`) | **P0** (прод-баг) | T-1625…T-1633 (9) |
| **F2** | `guide-delivery-round1016` | backend+docs | **UPD2 §2** (строка 151) + §7 | — | P1 (прод-регресс) | T-1634…T-1641 (8) |
| **F3** | `audit-recent-epics-round1016` | test/audit | **UPD2 §3** (строка 152) | **F1, F2** (их результаты) | P1 | T-1642…T-1650 (9) |
| **F4** | `miniapp-mobile-round1016` | frontend+infra | **UPD2 §4** (строка 153) | — (Caddy/DNS — @DevOps, вне репо) | P1 | T-1651…T-1659 (9) |
| **F5** | `security-rotation-finalize-round1016` | security+docs | **UPD2 §0** (строка 150) + R17 | **F1–F4** (финализация) | **P0** (безопасность) | T-1660…T-1665 (6) |

**Рекомендуемый порядок исполнения:** **F1 → F2 → {F3 ∥ F4} → F5.**
Обоснование: F1 — прод-блокер скачивания (tool `download_media` передаёт невалидный `"direct"`; Fast-Track probe);
F2 — прод-регресс доставки «Гайда» (миграция пропущена из-за дрейфа PG; write-path в tracked `info_text.md`);
F3 (аудит 10.13–10.15 + смоуки) опирается на результаты F1/F2, но может идти параллельно F4;
F4 (мини-апп Android) независим по файлам (`web/*`), серверная часть — @DevOps; F5 — последняя (ротация секрета + Step 9–10).
**⚠️ F3 делит `tests/*` с F1/F2 — новые смоук-файлы; F4 делит `web/index.html`/`web/app.js` только сам с собой.**

**Контент по фичам (сжато):**
- **F1 (`download-fix`):** tool-путь `services/tool_router.py:592-594` всегда `download(url, "direct")` →
  `tools/video_downloader.py:695-705` `_normalize_quality("direct")` → `int("direct")` = `ValueError` →
  `DownloadError("invalid quality: 'direct'")` (YouTube/TikTok → гарантированный сбой, регресс F8 10.15).
  Fast-Track `handlers/video_download.py:326-331` `probe(url)` → `DownloadError` → `VD_ERROR_PHRASES`
  (`tools/video_download_phrases.py:14`); probe зависит от cookies/proxy/POT/cobalt. Нужны: валидное ветвление
  direct vs авто/качество, категорийная R17-диагностика, смоуки с моками yt-dlp/cobalt.
- **F2 (`guide-delivery`):** «Гайд по фичам» = legacy `content.info_how_it_works` (`services/info_service.py`
  `DEFAULT_INFO_TEXT`/`PREV_DEFAULT_INFO_TEXT`, сид `info_text.md`); миграция `services/config_cache.py:235-266`
  перезаписывает только если PG == `PREV_DEFAULT_INFO_TEXT`, иначе WARNING+пропуск (прод-PG дрейфовал → гайд не обновился).
  `InfoService.save_text` (`info_service.py:202-217`) пишет в **tracked** `info_text.md` → дрейф/блок fast-forward pull.
  Нужны: версионирование канона (реестр PREV/хэши), force-reset, PG-only/неблокирующий write-path, байт/смоук-тесты.
- **F3 (`audit-recent-epics`):** полный аудит 10.13/10.14/10.15: ревизия логики и корнер-кейсов; смоуки «имитация
  реальной работы» (download/probe, tool-loop, guide, graph, sleep, nostalgia, persona); закрыть релевантный
  Low-техдолг (**S10.13-6b/9/11/13**, **R10.14-4**, **R10.15-4/-10/-11**); отчёт `plans/reports/round10.16_audit.md`.
- **F4 (`miniapp-mobile`):** `net::ERR_NAME_NOT_RESOLVED` на Android (десктоп ок); «~1 минута» — таймауты блокирующих
  CDN + крупные несжатые файлы. `web/index.html` внешние `<script>`: `telegram.org` (:11), `cdn.tailwindcss.com` (:12),
  `unpkg.com/vue@3` (:3633), `cdn.jsdelivr.net/npm/chart.js@4` (:3638); нет CSP/bundle/service worker; `index.html` ~235 КБ
  + `app.js` ~285 КБ. Нужны: self-host CDN (паттерн DOMPurify/vis-network, ADR-1013-2) или безопасная замена, CSP,
  минификация/бандлинг, диагностика DNS домана (`config/settings.py:171-173`, `handlers/menu.py:53-63`); Caddy/DNS — @DevOps.
- **F5 (`security-rotation-finalize`):** подтвердить, что `plans/current_task.md` не в git (`.gitignore:70`); ротировать/отозвать
  SSH-пароль (`current_task.md:62-65`, сервер `198.46.175.136`, вне репо, @DevOps); README/R17-hardening; подготовка Step 9–10.

**Инварианты раунда (в каждой tasks.md §3):** **DDL/SQL не требуется** (миграций БД нет); **каталог-Δ = 0** —
**REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / `TAB_RULES` 19** (новые ключи не вводятся);
**R17** секреты `{configured,last4}` (в логи — без URL/текстов/секретов); **R16** id — ключ; порядок роутеров `bot.py`
не трогать (только DI-kwargs); `media/`/`.env` не трогать; **Caddy/DNS — вне репо (@DevOps)**; новых CDN/`v-html` без
санитайза нет; байт-канон info не ломать без слепка; **ревью-гейты:** pytest 0 регрессий, `node --check web/app.js`,
`node tests/js/routing_test.js` → `JS-UNIT-OK`, R17-скан, пин-тесты каталога, русские conventional commits.

**Покрытие UPD2 / ТЗ → фичи (`plans/current_task.md`):**

| Раздел UPD2 / ТЗ | Фича(и) |
|---|---|
| **UPD2 §0** «Проверь, что `current_task.md` не попал в репозиторий» (+ R17-долг) | **F5** |
| **UPD2 §1** «Ошибка скачивания через tool calling (`download_media`); Fast-Track «Бот, скачай» → "битая ссылка"» | **F1** (+ **F3** — смоуки) |
| **UPD2 §2** «Задача 7 не выполнена — гайд по фичам в Справке остался как был» | **F2** (+ **F3** — смоук guide) |
| **UPD2 §3** «Перепроверь всё последними эпиками, полный аудит, тесты, смоук-тесты, логика, корнер-кейсы» | **F3** |
| **UPD2 §4** «Миниапп не запускается на Android `ERR_NAME_NOT_RESOLVED`; на десктопе ок; ранее ~1 минута загрузки» | **F4** |
| §1 «Умная выборка Графа Памяти» (10.15) | **F3** (аудит/смоук graph) |
| §2 «Диагностика и разблокировка Сна» (10.15) | **F3** (аудит/смоук sleep) |
| §3 «Ревамп Ностальгии» (10.15) | **F3** (аудит/смоук nostalgia) |
| §6 «Роутинг команд / Имя / Приоритеты» (10.15) | **F3** (аудит/смоук persona/routing) |
| §7 «Обновление "Гайда по фичам"» | **F2** |

**Открытые вопросы для @Architect:** контракт `download(url, quality?)` и ветвление direct vs авто (T-1625);
формат реестра PREV-слепков и семантика force-reset гайда (T-1634); глубина смоуков и приоритет Low-техдолга (T-1642);
стратегия CSP/Tailwind/бандлинга и DNS-диагностики (T-1651); политика ротации секрета (SSH-ключи vs пароль, T-1660).
**Статус:** ✅ **ЗАВЕРШЁН И ЗААРХИВИРОВАН** (исторический документ планирования; артефакты — `plans/archive/*-round1016/`, 5 папок).
**@PM код не пишет.**


## Раунд 10.15 (14.09.2026): Багфиксы Графа памяти, Воркера Сна и Ностальгии + Tool Calling — 9 фич — ✅ ЗАВЕРШЁН, ЗАДЕПЛОЕН И ЗААРХИВИРОВАН (14.09.2026; архив @PM, деплой @DevOps/@Memory 14.09.2026)

**✅ ИТОГ 10.15 (14.09.2026):** реализация завершена, все **9 фич заархивированы** — перенесены
`plans/features/*-round1015/` → **`plans/archive/*-round1015/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5774 passed / 0 failed** (база 10.14 = 5589 → **+185**; итерация 1 — 5761);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
Каталог — **Δ=0**: **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19);
новых ключей нет (пороги сна/окно ностальгии/tool-лимиты — переиспользуемые значения + код-константы).
БД: **миграций нет** (SQLite остаётся **v9**; PG — без новых таблиц/колонок; политика DDL 10.14 сохранена как
разрешение, но в 10.15 не применялась).
**Объём:** **9 фич, 76 задач** (T-1549…T-1624).
@Reviewer — **APPROVED** (итерация 2). Итерация 1 — **Rejected** по трём блокерам: **H1** F5 — `enabled=false`
не гасил активность бейджа Сна в окне (фронт показывал свечение вместо «☀️/🌅 выключен»); **M1** F6 — нет правой
границы слова у триггеров («Бот, загуглика» консьюмилась); **M2** F6 — безусловный yield в `direct_chat` терял
сообщение при выключенном модуле. Все закрыты @Builder с регресс-тестами (`plans/reports/round10.15_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium** (итерация 2; закрыты Medium R10.15-1 link-first, R10.15-2
`get_bot_health` vs `checkup_enabled`, R10.15-3 ложный консьюм обычной речи), остаются **3 Low** + 3 Info — техдолг
(`plans/reports/round10.15_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§36** + связанные §1/§3/§5/§9/§25).
Артефакты в архиве: `spec.md` + `tasks.md` (×9) + ADR-1015-1 (`adr-1015-1-command-prefix-policy.md`),
ADR-1015-2 (`adr-1015-2-graph-sampling.md`), ADR-1015-3 (`adr-1015-3-tool-calling.md`).
**🚀 Деплой (Step 9–10, 14.09.2026) — ✅ DEPLOYED:** commit **`d01a539`**
(`feat(services,web,api,docs,plans): раунд 10.15 — … (тесты 5774)`), push origin/master `798e044..d01a539`;
прод `nik@198.46.175.136:/var/www/admin_bot`, fast-forward `eb2a232..d01a539` (⚠️ потребовалась **ручная
разблокировка серверного дрейфа `info_text.md`**: backup + `git stash` → pull); `systemd admin_bot`
**active (running) PID 1860445**; `/api/health` = **200**, `/api/memory/graph` = **401**,
`/api/memory/stats` = **401** (не 500). **Миграций БД нет** (SQLite **v9**, PG без изменений);
`.env` не редактировался. **APP_VERSION 2.57.0** — без бампа. Релиз — KG `release-round1015`.
**Фичи (финал, все ✅ COMPLETED):** F1 `graph-sampling-centrality` (T-1549…T-1557) · F2 `graph-frontend-physics-search`
(T-1558…T-1565) · F3 `sleep-unblock-diagnostics` (T-1566…T-1574) · F4 `nostalgia-prompt-revamp` (T-1575…T-1583) ·
F5 `status-graph-ui-relocation` (T-1584…T-1592) · F6 `command-prefix-persona-routing` (T-1593…T-1602) ·
F7 `guide-rewrite-persona` (T-1603…T-1609) · F8 `hybrid-tool-calling` (T-1610…T-1618) · F9 `recent-history-tool`
(T-1619…T-1624). Пути артефактов → **`plans/archive/*-round1015/`**.

**🧾 Техдолг Low (ОТКРЫТ, 10.15 — не блокеры):** `R10.15-4` (yield в `direct_chat` по hot-флагу vs
startup-регистрация download-роутера 4e — осознанный follow-up), `R10.15-10` (link-first привязан к **первому**
вхождению имени), `R10.15-11` (триггер anywhere + **любой** http-URL консьюмит речь); **Info 3:** (1) repo-wide
**R17-долг** — `plans/current_task.md:62-65` содержит SSH-доступ и пароль (файл в `.gitignore`, но уже в истории —
рекомендовано **сменить/отозвать пароль и вычистить историю**; к 10.15 не относится), (2) реестр-комментарий F6
соответствует spec, (3) `info_text.md` §5 `Бот, живой?` — границы триггера корректны. Источник —
`plans/reports/round10.15_scanner_audit.md` §5.
**Статус:** ✅ **ЗАВЕРШЁН, ЗАДЕПЛОЕН И ЗААРХИВИРОВАН** (14.09.2026). @PM Step 8 (Archive) + @DevOps Step 9
(commit `d01a539` / push / прод fast-forward / restart / live-верификация — миграций БД нет) выполнены;
финальные метрики + KG + деплой-статус — @Memory Step 10 (14.09.2026). Эпик помечен **COMPLETED + DEPLOYED** в knowledge graph.
Ниже — исторический документ планирования эпика (Step 1 итер.2 @PM + Step 2 @Architect).

**Эпик:** `Epic: Багфиксы Графа памяти, Воркера Сна и Ностальгии round1015` (@Memory, Step 0).
**Источник ТЗ** — `plans/current_task.md` (разделы 1–7 + **UPD п.1–5**, строки 79–145, включая финальный
деплой-чеклист). **HEAD при планировании:** `798e044` (docs-коммит 10.14). **APP_VERSION** 2.57.0.
**Базовая линия (@Memory Step 0):** pytest **5589 passed / 0 failed** (база финала 10.14); каталог-инвариант
**REGISTRY 435 / GROUPS 90 / Settings 406 / categorized 411 / mapped 88 / `TAB_RULES` 19**; SQLite **v9**.
Преемник — 10.14 (`plans/archive/*-round1014/`, все 8 фич COMPLETED+DEPLOYED, 72 задачи T-1477…T-1548).
Снятые инварианты 10.14 (DDL разрешён) сохраняются как разрешение, но в 10.15 DDL **не требуется**.
Остаются: **R17** (секреты `{configured,last4}`), **R16** (id — ключ), порядок роутеров `bot.py`
(только DI-kwargs), `media/`/`.env` не трогать, пин-тесты каталога, self-host DOMPurify/vis-network.

**9 фич (нумерация продолжает T-1548 → T-1549…T-1624, 76 задач):**

| # | Фича (папка) | Тип | ТЗ | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `graph-sampling-centrality-round1015` | backend | §1 (алгоритм/сироты) | — | **P0** | T-1549…T-1557 (9) |
| **F2** | `graph-frontend-physics-search-round1015` | frontend | §1 (vis-network) | **F1** | P1 | T-1558…T-1565 (8) |
| **F3** | `sleep-unblock-diagnostics-round1015` | backend | §2 | — | **P0** (блокер сна) | T-1566…T-1574 (9) |
| **F4** | `nostalgia-prompt-revamp-round1015` | backend+prompt | §3 | — | P1 | T-1575…T-1583 (9) |
| **F5** | `status-graph-ui-relocation-round1015` | frontend+API | §4+§5+UPD§3 | **F3** (частично, API), **F1/F2** | P1 | T-1584…T-1592 (9) |
| **F6** | `command-prefix-persona-routing-round1015` | backend (routing) | §6 + **UPD §1-2** | — (`flags.persona_enabled`/имя 10.14) | **P0** (регресс-риск) | T-1593…T-1602 (10) |
| **F7** | `guide-rewrite-persona-round1015` | docs+backend+UI | §7 | **F6** (+F5) | P2 | T-1603…T-1609 (7) |
| **F8** | `hybrid-tool-calling-round1015` | backend (LLM/tools) | **UPD §4** | **F6** (fast-track реестр) + существующий `tool_router`/`tool_loop` | P1 | T-1610…T-1618 (9) |
| **F9** | `recent-history-tool-round1015` | backend (LLM/tools) | **UPD §5** | **F8** (tool-loop/реестр/схемы) + **F6** | P1 | T-1619…T-1624 (6) |

**Рекомендуемый порядок исполнения:** **F1 → F2 → F3 → F4 → {F5} → F6 → {F7 ∥ F8} → F9.**
Обоснование: F1 (backend-граф) — фундамент для F2 (фронт `barnesHut`/поиск показывает связный граф);
F3 (fallback порогов сна + `[Sleep]`-диагностика) независима и снимает блокер синтеза убеждений;
F4 (ностальгия) независима; F5 (релокация статистики + бейджи) частично опирается на аддитивное поле
`cognition/status` (согласовать с F3) и делит `web/index.html`/`web/app.js` с F2 — вливать после F2;
**F6** (префиксы/имя/приоритеты) — главный регресс-риск, **без рубильника** (триггер = непустое Имя);
**F7** (гайд) пишется по факту F6; **F8** (гибридный tool-calling) требует fast-track-приоритет F6 и
существующий `tool_router`/`tool_loop`; **F9** (`get_recent_history`) подключается к общему tool-сету F8.
**⚠️ F2, F5 делят `web/index.html`/`web/app.js` — исполнять/вливать ступенями (F2 → F5).**
**F1/F5 делят `web/api/memory_agi.py` — аддитивные поля согласовывать.**
**F4/F3 трогают `services/database.py`/`dream_worker.py`/`nostalgia_worker.py` — вливать согласованно с
пин-тестами каталога.**
**⚠️ F8/F9 делят `services/tool_schemas.py`/`tool_router.py` (аддитивно) — вливать ступенями (F8 → F9):
T-1611 F8 регистрирует `get_recent_history` из F9, T-1620 F9 добавляет саму схему — согласовать без разрыва
tool-сета.)**

**Контент по фичам (сжато):**
- **F1 (Умная выборка графа, §1 backend):** переписать `services/database.py:3610-3665` `graph_snapshot`:
  топ-50 сидов по **Degree Centrality** → раскрытие **всех смежных** узлов и рёбер → удаление **сирот**
  и висячих рёбер (закрывает техдолг **S10.13-14**); cap **120/240** (`web/api/memory_agi.py:58-59`)
  применяется ПОСЛЕ раскрытия; контракт `nodes/edges/truncated/limits` сохранён (R16). API
  `GET /api/memory/graph` (`memory_agi.py:500-520`) без ломки. Новые тесты `graph_snapshot`.
- **F2 (Физика графа + поиск, §1 frontend):** `barnesHut` в `renderCognitionGraph` (`web/app.js:5244-5283`,
  опции `:5259-5272`); инпут **«Поиск по графу»** в «Мониторинге Интеллекта» (`web/index.html:2911-2960`)
  → центрирование камеры на узле по `label` + подсветка; сохранить `reducedMotion`, `_cognitionGraphSig`,
  `destroy`, self-host vis-network (ADR-1013-2).
- **F3 (Разблокировка Сна + диагностика, §2):** динамический fallback порогов в `services/dream_worker.py:485-514`:
  «0 убеждений за 3 дня» → `min_cluster_size=2` / `min_importance_sum=8` (базовые 3/12 из
  `settings.py:1101-1103` переиспользуются); пре-гейт-лог формата
  `[Sleep] Chunks: 15, Clusters formed: 2, Max importance: 9 -> Skipped (threshold 12)` виден в панели
  «Логи» (`services/log_ring.py`); отдельный kill-switch **не вводится** (self-healing: fallback отключается
  при первом синтезированном убеждении; каталог-Δ=0, откат = `git revert`).
- **F4 (Ревамп Ностальгии, §3):** окно `memory.nostalgia_year_back_days_window` `±2`→`±10`
  (`settings.py:1173-1174`, `param_catalog.py:1535`, `nostalgia_worker.py:546-552`, Δ каталога 0);
  инжект **Лора чата** + **локальных мемов** (`database.py:3554` `list_chat_memes`, `lore_cache`/
  `chat_lore_store`) в user-блок `build_nostalgia_user` (`nostalgia_prompts.py:103-116`); переписать
  `NOSTALGIA_PROMPT` (`:21-25`) под «давнего участника» (ирония/сленг, анти-«робот-архивариус»),
  сохранив `{max_words}`/`UNCHANGED`; ADR-1013-3: PREV-слепок + байт-тесты, `PROMPT_MIGRATIONS` не трогать.
- **F5 (Релокация статистики + бейджи, §4+§5):** удалить карточку «Статистика графа памяти» из «Модулей»
  (`web/index.html:1452-1469`), консолидировать метрики в существующий блок «Сводки» (`:1804-1809`) —
  **без дубля**; бейджи `dreamPhaseBadge`/`deepPhaseBadge` (`web/app.js:1204-1224`): неактив
  `[☀️] Сон через [время]` / `[🌅] Глубокий сон через [время]` (без свечения), актив
  `[🌙] Сон до [время]` / `[🌌] Глубокий сон до [время]` (свечение); аддитивное поле API для
  активной фазы (либо расчёт на фронте); мобильный столбик (`index.html:2911-2927`), удалить
  «пробуждение ~11:00» (`:2923-2924`).
- **F6 (Префиксы команд / имя / приоритеты, §6 + UPD §1-2):** **флаг-рубильник `flags.command_prefix_enabled`
  ОТМЕНЁН** (UPD §1) — триггер системы = **непустое поле «Имя» Личности**: имя заполнено → префикс
  `<Имя>, ` и дефолтные `бот`/`ботик`/`ботяра` **отключаются**; имя пусто → префикс `Бот, `, дефолты
  активны. **Работает «из коробки»**, откат = `git revert` + очистка Имени. Точный реестр — **17 команд**
  (`найди`, `поищи`, `загугли`, `транскрипт`, `че за видос`, `о чем видео`, `поясни за видос`,
  `поясни за ссылку`, `че по ссылке`, `о чем статья`, `выжимка`, `ты в порядке`, `живой?` **[слово
  «собака» убрать]**, `чекни здоровье`, `скачай`, `загрузи`, `стяни`) + **исключения** `чекап`/`фактчек`
  (одним словом, **без** префикса). Новые модули `services/command_registry.py` (канон) и
  `services/command_prefix.py` (`active_name`/`split_prefix`/`name_mentioned`/`is_functional_command`);
  обязательный префикс у триггеров (`handlers/search.py:57-101`, `youtube.py:120-215`, `web.py:52-96`,
  `checkup.py:53-80`, `video_download.py:74-75`); при заданном имени — отключить дефолтные ботворды
  (`handlers/direct_chat.py:147-165`); функциональные команды — наивысший приоритет, **yield (UNHANDLED)**
  из direct_chat для download (4e), не уходят в LLM (порядок `bot.py:641-666` **не менять**). **ADR-1015-1.**
  **⚠️ Главный регресс-риск:** ломает `tests/test_epic72_gates.py:69` («эй, бот»→True) и
  `tests/test_direct_chat.py:2994-3010` («бот, загугли») — митигация: мягкий переход (пустой глобальный
  сид → прежнее поведение), пред-деплой чек-лист владельцу, правка тестов под новую семантику.
- **F7 («Гайд по фичам», §7):** переписать `DEFAULT_INFO_TEXT` (`services/info_service.py:20-70`) и
  `info_text.md` (байт-в-байт, `tests/test_info_service.py:28-45`) под **канонический реестр F6 (17+2)** и
  префиксы/имена; правило «Все команды требуют обращения: без имени — «Бот, скачай», с именем — «Олег,
  скачай»»; исключения `чекап`/`фактчек`; blockquotes/инлайн-код; сохранить ироничный стиль; второй гайд
  `content.intelligence_guide` (10.14); доставка нового канона в прод-PG идемпотентной миграцией
  `_migrate_info_how_it_works_v1015` по слепку `PREV_DEFAULT_INFO_TEXT` — **без затирания ручных правок**.
- **F8 (Гибридный вызов функций / Tool Calling, UPD §4):** основная LLM чата (`direct_chat`, DeepSeek)
  получает **JSON-Schema инструменты**; **regex Fast-Track сохраняется и приоритетнее** (F6: префикс+триггер
  → консьюм воркером, LLM не вызывается), свободная форма → `tool_call` через существующий
  `services/tool_loop.py`. Итоговый tool-сет — **7**: `query_chat_memory`, `dig_into_lore`,
  `execute_web_search` (существуют) + `summarize_video`, `download_media`, `get_bot_health` (**новые**) +
  `get_recent_history` (**F9**). Расширение `ToolDeps`(`video`/`downloader`/`health`) и `ToolContext`
  (`bot`/`reply_to_message_id`/`user_id`); `bot.py` — только DI-kwargs, порядок роутеров не трогать.
  **Корнер-кейс скачивания:** `download_media` исполняется на бэкенде и **сам шлёт MP4** (`_send_media`),
  а в LLM возвращается **фиктивный** `tool_response` `{"status":"success","message":"Файл успешно загружен
  в чат"}` (иначе модель «печатает» видео); при сбое — честный `status:"error"`, успех только после
  реальной отправки. Лимиты — **код-константы** (`TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2`),
  R17 (в логи только `tool`/`out_chars`/класс ошибки, без URL). **ADR-1015-3.**
- **F9 (Инструмент `get_recent_history`, UPD §5):** LLM получает тул чтения **сырого лога недавних
  сообщений (L1-окно)** — «что обсуждали 10 минут назад», «кто скинул ту ссылку», «кто прав в споре».
  Параметры: **`depth` (1..150)** — хронологический срез (`database.get_recent_messages`, ASC) **ИЛИ
  `query`** — поиск по сырой SQLite последних часов (FTS + фильтр окна + сортировка); при обоих —
  приоритет `query`; ни одного — `depth=50`. Стенограмма строго `Имя: текст` (R16: alias→author_name→user_id;
  медиа — маркером/текстом; пустой текст пропускается); chat-скоуп `ctx.chat_id`; при пустом результате —
  честная фраза (без галлюцинаций). Лимиты — **код-константы** (`_HISTORY_MAX_DEPTH=150`,
  `_HISTORY_SEARCH_LIMIT=80`, `_HISTORY_QUERY_WINDOW_SECONDS=12h`, `_HISTORY_MAX_SYMBOLS=3500`,
  `_HISTORY_TOOL_TIMEOUT=10s`); `get_recent_messages` **переиспользуется как есть** (DDL не требуется);
  R17. Базовая схема — в F8 (`TOOL_CALLING_TOOLS`), dispatch-ветка в `tool_router.py`.

**Инварианты раунда (в каждой tasks.md §3):** **DDL не требуется** (схема не меняется); **каталог-Δ = 0** —
**REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / `TAB_RULES` 19**, новые ключи **не
вводятся** (флаг `flags.command_prefix_enabled` отменён; пороги сна, окно ностальгии, tool-лимиты —
переиспользуемые/код-константы; F8/F9 — `TOOL_MAX_ROUNDS=4`/`_TOOL_CALLS_PER_ROUND_MAX=2`/`_HISTORY_*` в коде);
**R17** секреты (в логах tool — только `tool`/`out_chars`/класс ошибки, без URL/текста); **R16** id — ключ;
порядок роутеров `bot.py` не трогать (только DI-kwargs: `ToolDeps(video/downloader/health)`); `media/`/`.env`
не трогать; правка промпт-канона ностальгии — PREV-слепок + байт-тесты, `PROMPT_MIGRATIONS` не трогать;
правка info-канона — идемпотентная миграция `_migrate_info_how_it_works_v1015` (не затирать ручное);
**новых `v-html` без санитайза/новых CDN нет** (DOMPurify/vis-network self-host); **feature-flag НЕ
требуется** (UPD §1 отменил рубильник для F6; F8/F9 — расширение существующего механизма, rollback =
`git revert`); **ревью-гейты:** pytest 0 регрессий, `node --check web/app.js`, `node tests/js/routing_test.js`
→ `JS-UNIT-OK`, пин-тесты каталога, R17-скан; русские conventional commits. Деплой-чеклист ТЗ
(ssh → pull → restart → status, plain-language отчёт) — за @DevOps/@PM на Step 9–10.

**✅ Open (закрыто @Architect, Step 2 итерация 1–2, 14.09.2026 — spec.md по всем 9 фичам + 3 ADR):**
- **F1:** невзвешенная Degree Centrality (число рёбер); 50 сидов — код-константа `GRAPH_SEED_NODES`
  (каталог-Δ=0); полный degree в узле; отсечение изолированных компонент; cap ПОСЛЕ раскрытия. **ADR-1015-2.**
- **F3:** fallback порогов как self-healing kill-switch (`services/dream_worker.py`, каталог-Δ=0);
  пре-гейт-лог `[Sleep] Chunks/Clusters/Max importance → Skipped`; источник «0 убеждений» — решён.
- **F4:** PREV-слепок обязателен, `PROMPT_MIGRATIONS` не трогаем; капы лора ≤600 симв., мемы ≤10×120;
  лор активного чата (manual→auto); окно `±10` по дефолту. **ADR-1013-3.**
- **F5:** аддитивные поля API (`active_until`/`ends_at`, расчёт на бэке); `.badge.glow`; мобильный столбик
  (flex-wrap); оконная семантика бейджей **утверждена владельцем (UPD §3, §3а спеки)**.
- **F6 (ключевое):** **флага нет** (UPD §1); per-chat имя → только глобальный sync-кэш
  `get_cached_global_name()`; эвристика склонений (имена ≥3 симв.); дефолтные ботворды off **iff
  `persona_enabled AND name non-empty`**; префикс применяется к 15 префиксным командам, `чекап`/`фактчек` —
  bare; `is_functional_command`-yield для download. **ADR-1015-1.**
- **F7:** доставка — идемпотентная миграция по слепку (не затирать ручное); канон = реестр F6 (17+2).
- **F8:** tool-сет 7 (3 существующих + 3 новых + `get_recent_history` F9); фиктивный `tool_response` для
  `download_media`; лимиты — существующие код-константы; layering через `services/media_send.py`. **ADR-1015-3.**
- **F9:** `depth≤150` ИЛИ `query` (приоритет `query`), стенограмма `Имя: текст`, chat-скоуп, лимиты —
  код-константы; `get_recent_messages` переиспользуется как есть (DDL не требуется).
**Остаточное на @Builder/@Reviewer:** R16/R17, идемпотентность info-миграции, регресс-риск F6 (живые чаты),
фиктивный success скачивания, пин-тесты каталога.

**Покрытие ТЗ (`plans/current_task.md`, разделы 1–7 + UPD п.1–5 → фичи):**

| Раздел ТЗ / UPD | Фича(и) |
|---|---|
| §1 «Умная выборка для Графа Памяти» | **F1** (backend) + **F2** (frontend) |
| §2 «Диагностика и разблокировка Сна» | **F3** |
| §3 «Ревамп Ностальгии» | **F4** |
| §4 «Релокация статистики графа» | **F5** |
| §5 «Редизайн бейджей Сна и мобильная вёрстка» | **F5** |
| §6 «Роутинг команд, Имя личности и Приоритеты» | **F6** |
| §7 «Обновление "Гайда по фичам"» | **F7** |
| **UPD §1** «Отказ от флага-рубильника; непустое Имя = триггер системы; «Бот, » при пустом» | **F6** (+ **F7** — правило в гайде) |
| **UPD §2** «Точный реестр 17 команд + исключения `чекап`/`фактчек`; `живой?` без слова «собака»» | **F6** (+ **F7**) |
| **UPD §3** «Оконная семантика бейджей Сна — утверждена» | **F5** |
| **UPD §4** «Гибридный вызов функций (JSON-Schema tools; regex Fast-Track; корнер-кейс скачивания)» | **F8** |
| **UPD §5** «Инструмент `get_recent_history` (depth≤150 / query, стенограмма `Имя: текст`)» | **F9** |
| Финальный блок «Деплой» (ssh/pull/restart/status/отчёт) | **@DevOps/@PM** (Step 9–10), не фича |

**Итог: все 7 разделов ТЗ + 5 пунктов UPD покрыты; 9 фич, 76 задач (T-1549…T-1624); папки заархивированы.**
**Статус:** ✅ **ЗАВЕРШЁН И ЗААРХИВИРОВАН** (14.09.2026, @PM Step 8 Archive Phase). Планирование (Step 1 итер.2 @PM)
+ Step 2 @Architect — `spec.md` + `tasks.md` во всех **9** папках + 3 ADR (`adr-1015-1-command-prefix-policy`,
`adr-1015-2-graph-sampling`, `adr-1015-3-tool-calling`). Реализация @Builder (F1–F9), @Reviewer **APPROVED**
(итерация 2), @Scanner **0 C/H/M** (3 Low — техдолг, см. блок «ИТОГ 10.15»), @Architect — `plans/ARCHITECTURE.md`
**§36**. Артефакты: **`plans/archive/*-round1015/`** (**9 папок**). Деплой — @DevOps Step 9 (миграций БД нет).
**@PM код не пишет.**



**✅ ИТОГ 10.14 (13.09.2026):** реализация завершена, все **8 фич заархивированы** — перенесены
`plans/features/*-round1014/` → **`plans/archive/*-round1014/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5589 passed / 0 failed** (база 10.13 = 5392 → **+197**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
Каталог — санкционированный прирост (F1 origin/self-awareness, F2 persona-флаги, F6 `content.intelligence_guide`,
F8 `intel_reflection_*`): **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 / mapped 88 / `TAB_RULES` 19).
БД: SQLite **v8→v9** (origin `bot_self_reply`, миграция `_migrate_self_origin_v9`); **PG** — `personas` /
`persona_traits` / `persona_state` (идемпотентный DDL).
**Объём:** **8 фич, 72 задачи** (T-1477…T-1548), все `[x]`.
@Reviewer — **APPROVED** (итерация 2). Итерация 1 — **Rejected** по трём High-блокерам: **H1** optimistic-409
персоны недостижим (`updated_at` не отдавался), **H2** RBAC-действие `edit_persona` не зарегистрировано,
**H3** новые per-chat ключи читались только глобально (`hot.get`); все закрыты @Builder и подтверждены
`file:line` + тестами (`plans/reports/round10.14_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium** (итерация 2; закрыты Medium R10.14-1 RBAC view/edit
`edit_persona` и R10.14-2 traits-LLM вне `worker_budget`), остаются **2 Low** + 2 Info — техдолг
(`plans/reports/round10.14_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§35** + связанные разделы).
Артефакты в архиве: `spec.md` + `tasks.md` (×8) + ADR-1014-1 (`adr-1014-1-persona-storage.md`),
ADR-1014-2 (`adr-1014-2-anti-echo-self.md`) + `settings-persistence-audit-round1014/report.md` + `inventory.tsv`.
**Фичи (финал, все ✅ COMPLETED):** F1 `anti-echo-self-reply` (T-1477…T-1486) · F2 `persona-storage-core`
(T-1487…T-1497) · F3 `persona-ui-tab` (T-1498…T-1504) · F4 `persona-traits-ribbon` (T-1505…T-1510) ·
F5 `settings-persistence-audit` (T-1511…T-1525) · F6 `help-guide-integration` (T-1526…T-1534) ·
F7 `status-layout-reorder` (T-1535…T-1540) · F8 `self-reflection-llm-provider` (T-1541…T-1548).

**🧾 Техдолг Low (ОТКРЫТ, 10.14 — не блокеры):** `R10.14-4` (`dynamic_traits` отдаются без фильтра `chat_id` —
оставлено **осознанно**, соответствует модели «общий характер бота» по F4), `R10.14-7` (warning
`closed 12 leaked aiosqlite connection(s)` — **pre-existing**, не регрессия), `L5` (**hot-path**: на каждый
direct-ответ 2 доп. PG-запроса `resolve_bot_persona`+`get_traits` + запись `persona_state`; кэш отсутствует —
оптимизация на будущее); **Info:** `I10.14-1` (прямой каскад v7→v9 юнит-тестами не покрыт — риска нет),
`I10.14-2` (FIFO-ротация traits глобальная, не per-chat — зафиксировать в ARCH). Источник —
`plans/reports/round10.14_scanner_audit.md` §5.
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.14 (@DevOps + Step 10 @Memory, 13.09.2026):** commit **`eb2a232`**
(`feat(services,web,api,docs,plans): раунд 10.14 — самосознание и личность бота, PG Persona и SQLite v9,
LLM-экстрактор, метрики Сводки, редактор Справки (тесты 5589)`); push origin/master `2edc65b..eb2a232`;
прод `nik@198.46.175.136:/var/www/admin_bot` fast-forward `8800bba..eb2a232`; `admin_bot`
**active (running) PID 1774527**; **миграции применены** (SQLite `PRAGMA user_version=9` / origin
`bot_self_reply`; PG `personas`/`persona_traits`/`persona_state`); `/api/health` = **200**,
`/api/persona/health` = **401** (не 500); `.env` не редактировался (дефолты безопасны, флаги ON в коде).
**APP_VERSION не бампился** (2.57.0). Статус эпика — **COMPLETED + DEPLOYED**. Step 10 @Memory —
метрики+синхронизация выполнены (`plans/metrics.md` строка 10.14; KG `release-round1014`,
`metric-snapshot-round1014-final`). Техдолг Low 2 (`R10.14-4`, `R10.14-7`) + `L5` + Info 2.
Ниже — исторический документ планирования эпика (Step 1 @PM).

**Эпик:** `Epic: Self-Awareness / Persona round1014` (@Memory, Step 0). **Источник ТЗ** —
`plans/current_task.md` (разделы 1–7) + **UPD владельца** (пп.1–5, отменяет DDL-free решения). **HEAD при
планировании:** `2edc65b` (== origin/master, дерево чистое). **APP_VERSION** 2.57.0.
**Базовая линия (@Memory Step 0):** pytest **5392 passed / 0 failed**; `node --check web/app.js` clean;
каталог-инвариант **REGISTRY 427 / GROUPS 90 / Settings 399 / categorized 403 / mapped 88 / `TAB_RULES` 19**;
SQLite **v8** (до миграции v9 в F1). Преемник — 10.13 (`cognition-*-round1013`, архив; все 8 фич COMPLETED,
60 задач T-1417…T-1476).
**UPD владельца (13.09.2026, отменяет редакцию 1 плана):** DDL разрешён; Persona — PG-таблицы
`personas`/`persona_traits`; новый origin `bot_self_reply` + SQLite v9; флаги ON по умолчанию; LLM-экстрактор
с 3-м провайдером; метрики Личности в «Сводке»; справка — БД-редактор.

**8 фич (нумерация продолжает T-1476 → T-1477…T-1548, 72 задачи):**

| # | Фича (папка) | Тип | ТЗ | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `anti-echo-self-reply-round1014` | backend (+PG/SQLite DDL) | п.1 + UPD 1,3 | — (F8-роль `reflection` опциональна: фоллбэк) | **P0** (фундамент: origin+миграция+экстрактор) | T-1477…T-1486 (10) |
| **F2** | `persona-storage-core-round1014` | backend (+PG DDL) | п.2 + UPD 1,2,4 | **F1** (`persona_state` DDL) | **P0** | T-1487…T-1497 (11) |
| **F3** | `persona-ui-tab-round1014` | frontend | п.3 + UPD 2 | **F2** | P1 | T-1498…T-1504 (7) |
| **F4** | `persona-traits-ribbon-round1014` | frontend | п.3.1 + UPD 4 | **F2, F1** (`/api/persona/health`) | P1 | T-1505…T-1510 (6) |
| **F5** | `settings-persistence-audit-round1014` | backend+frontend | п.4 | — (∥ F1/F2; сверка с активной `config-read-path-audit`; охват новых API F8/F2/F6) | **P0** | T-1511…T-1525 (15) |
| **F6** | `help-guide-integration-round1014` | docs+backend+frontend | п.5+п.6 + UPD 5 | **F1, F2, F3** | P2 | T-1526…T-1534 (9) |
| **F7** | `status-layout-reorder-round1014` | frontend | п.7 | — (независима) | P2 | T-1535…T-1540 (6) |
| **F8** | `self-reflection-llm-provider-round1014` | backend+frontend | UPD 3 | **F1, F2** (роль `reflection` для LLM-экстрактора F1; UI-провайдеры; формально self-contained — пусто → основная модель) | P1 | T-1541…T-1548 (8) |

**Рекомендуемый порядок исполнения:** **F1 → F2 → {F3, F4} → {F5 ∥ F8} → F6 → F7.**
Обоснование: F1 задаёт origin `bot_self_reply` + SQLite v9 + LLM-экстрактор (роль `reflection`, фоллбэк на
основную модель) → F2 (PG `personas`/`persona_traits` + core, промпт-склейка, `persona_state`) опирается на
DDL/канон F1; F3 (UI «Личность») и F4 (лента traits + метрики «Сводки») зависят от API F2 и могут идти
параллельно; F5 независима (аудит save/read-path), но делит `web/app.js` и включает в инвентарь новые
сущности F8/F2/F6; **F8** формально self-contained (пустые поля → основная модель), но по указанию владельца
учитывается зависимость от F1/F2: даёт роль `intel_reflection` для LLM-экстрактора F1 и provider-UI — вливать
после/параллельно F1–F2; F6 пишется по факту реализации F1–F3; F7 — чистая перестановка, независима.
**⚠️ F3, F4, F6, F7 все правят `web/index.html`/`web/app.js` — исполнять/вливать ступенями (F4 → F7 → F6).**
**F1/F2 (DDL) и F8 (models/keys) трогают `services/database.py`/`pg_db.py`/каталог — вливать согласованно с
пин-тестами каталога.**
F5 согласуется с активной F-5 `config-read-path-audit` (не дублировать read-path/касты).

**Контент по фичам (сжато):**
- **F1 (Anti-Echo & Self-Reflection, п.1 + UPD 1,3):** новый честный origin `graph_facts.origin='bot_self_reply'`
  (11-й; `status='confirmed'`), SQLite rebuild-миграция **v8→v9** (`_migrate_self_origin_v9`; все 16 колонок +
  FTS/vec; идемпотентно); вес self `limits.graph_fact_weight_bot` = **0.2** (важность 2) против пользовательского
  0.7; экстракт сути **только LLM** (новый `services/self_reflection.py`, роль `reflection` через F8, фоллбэк на
  основную модель); RAG-метка `[Источник: Я сам (Бот)]` + анти-эхо-инструкция (`_build_rag_block`, БЕЗ правки
  PG-канона); opt-in `include_self`; self исключён из Сна/«золотых»/decay/компакции/`graph_stats.facts`;
  `persona_state` (метрики экстрактора — DDL F1); флаг `flags.bot_self_awareness_enabled` **ON**. Модули:
  `services/database.py:53,67-101,…`, `services/summary_memory.py:211-222,…`, `services/dream_worker.py:132-136`,
  `services/direct_chat_service.py:959-990,1690-1771`, `services/llm_client.py:891-954`. **ADR-1014-2.**
- **F2 (Dynamic Persona, п.2 + UPD 1,2,4):** **PG-таблицы `personas`** (scope `is_global`/`chat_id` + CHECK +
  2 partial-unique + FK→`chat_profiles`) и **`persona_traits`** (`dynamic_traits`, cap 50/dedup, provenance
  `chat_id`/`source`); статические `name`/`biography`/`system_prompt_overrides`/`is_aware_ai` (default true);
  резолв per-chat → global → empty; API `GET/PUT/DELETE /api/persona` + `GET /api/persona/health`; промпт-склейка
  + имя-триггер; «Глубокий сон» пишет traits; `flags.persona_enabled` **ON**; сид пустой глобальной персоны.
  **НЕ** `bot_settings`/`chat_params.overrides`. **Naming:** `build_persona_card` (`direct_chat_service.py:1511`,
  `database.py:3390`) — досье ПОЛЬЗОВАТЕЛЯ (F8 10.13), НЕ трогать. **ADR-1014-1.**
- **F3 (UI «Личность», п.3 + UPD 2):** карточка/подраздел в Hub «ИИ» (`web/app.js:270-296`, `#/ai`), форма ТОЛЬКО
  статических полей (Имя/Биография/Характер/чекбокс «Осознаёт себя ИИ»), scope-реактивность (activeChatId/
  `X-Chat-Id`), бейдж+disabled при `flags.persona_enabled=OFF`. Модули: `web/app.js`, `web/index.html`,
  `web/api/routes.py` (персона — PG-API, каталог-Δ нет).
- **F4 (Лента «Эволюция характера» + метрики «Сводки», п.3.1 + UPD 4):** третья бегущая лента рядом с
  «Сон»/«Глубокий сон» (`web/index.html:2916-2943`), переиспользуя `_ribbonLoop`/`ribbonItemClass`
  (`web/app.js:4749-4776`); CSS-сетка 3 колонки; панель метрик Личности в дашборде **«Сводка»** (`#/oversight`):
  `traits_count`, `last_trait_at`, `extractor_status` (+`extractor_last_at`) через `GET /api/persona/health`.
- **F5 (Save/read-path audit, п.4):** инвентаризация ВСЕХ изменяемых параметров мини-аппа + матрица
  «SavePath/Scope/RuntimeConsumer»; цепочка Vue → API → БД; scope Global↔чат (422 `routes.py:414-417`);
  рестарт-персистентность; рантайм-подхват воркерами/RAG/LLM-клиентами; в инвентарь входят **новые сущности
  раунда** (`flags.persona_enabled`, `flags.bot_self_awareness_enabled`, provider-блок `intel_reflection`,
  dedicated-API `/api/persona` и `/api/info/guide`). Модули: `web/app.js:2431,3214,3263`,
  `services/chat_params.py:31-85,397-412`, `services/config_cache.py`, `services/llm_client.py`,
  `services/llm_probe.py`, `services/worker_budget.py`.
- **F6 (docs+справка, п.5/6 + UPD 5):** дополнить `plans/docs/intelligence_user_guide.md` (самосознание/личность),
  интегрировать в «Справку» (`web/index.html:3050-3083`) **вторым редактируемым блоком** под блоком
  использования функций; гайд хранится **в БД** — PG-ключ `content.intelligence_guide`
  `{markdown,updated_at,updated_by}` (json, `content_info`, PG-only), файл — только **источник идемпотентного
  сида**; Markdown-редактор + предпросмотр + **DOMPurify self-host** (без новых CDN); API `GET/POST /api/info/guide`
  (RBAC `edit_info`); `services/info_service.py`, `services/config_cache.py`, `web/api/routes.py`.
- **F7 (порядок «Статус», п.7):** «Сердцебиение» (`index.html:2883-2900`) — сразу под «Сводку» (`:2776`);
  «Мониторинг Интеллекта» (`:2901-2943`) — под «Сервер» (`:2817`). Независима.
- **F8 (3-й LLM-провайдер «Саморефлексия / Экстрактор сути», UPD 3):** новое parent+subBlocks-подключение в
  витрине «LLM Провайдеры»; PG-ключи `models.intel_reflection_base_url/_model_name/_display_name` +
  `keys.intel_reflection_api_key`; роль `reflection` в `LLMClient.generate_worker` (slug `intel_reflection`);
  probe `intel_reflection_main`; пустые поля → основная модель (DeepSeek), ошибка dedicated → `generate()`
  (fail-open). Паттерн ADR-1013-1 (`intel_history`/`intel_bg`). Потребляется F1.

**Инварианты раунда (в каждой tasks.md §3):** **DDL РАЗРЕШЁН** (UPD п.1): PG — идемпотентные
`CREATE TABLE IF NOT EXISTS`/`ON CONFLICT DO NOTHING` (`personas`, `persona_traits`, `persona_state`); SQLite
**v8→v9** rebuild с сохранением всех 16 колонок + FTS/vec и идемпотентным guard'ом; повторный
`PgDatabase.init()`/`initialize()` — no-op. **`graph_facts.origin` CHECK расширяется до 11 значений**
(`bot_self_reply`); `status='self_reply'` НЕ вводится. Порядок роутеров `bot.py` не трогать (только DI-kwargs);
каталог-инварианты **435/90/406/411/88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19 — новые ключи/вкладки/группы только
санкционированным Δ с обновлением пин-тестов (`test_param_catalog`, `test_frontend_tab_mapping`,
`TAB_SECTION_ORDER`, `TAB_RULES`, «группа → ровно 1 вкладка»); **R17** секреты `{configured,last4}`;
**R16** id — ключ, не имя; `media/`/`.env` не трогать; правка промпт-канонов — PREV-слепок +
`prompt_migrations` + байт-тесты (анти-эхо F1 — динамический блок, PG-канон НЕ трогается); байт-канон info
(`DEFAULT_INFO_TEXT`) не ломать; **новых `v-html` без санитайза/новых CDN нет** (DOMPurify self-host); **флаги
`flags.persona_enabled`/`flags.bot_self_awareness_enabled` = ON по умолчанию** (UPD п.2), OFF → байт-в-байт
прежнее поведение; **ревью-гейты:** pytest 0 регрессий, `node --check web/app.js`, пин-тесты каталога,
R17-скан, миграция дважды + «from scratch»; русские conventional commits.

**⚠️ Open (закрыто @Architect Step 2 итерация 2 — ADR-1014-1/2 + spec F1–F8; остаточное на @Builder/@Reviewer):**
- **F1/F2 (UPD):** решено — origin `bot_self_reply` (11-й) + SQLite v9; PG `personas`/`persona_traits` +
  `persona_state`; вес-ключ; LLM-экстрактор роль `reflection`; флаги ON. **@Reviewer/@Scanner:** идемпотентность
  миграций, сохранность 16 колонок/FTS/vec, R17.
- **F8:** решено — parent+subBlocks «LLM для саморефлексии (Экстрактор сути)», `intel_reflection_*`, probe
  fallback. Проверить отсутствие дублей с `intel_history`/`intel_bg`.
- **F3:** решено — отдельный экран/tab «Личность» в Hub «ИИ» (`#/ai/persona`), форма только статических полей;
  OFF → бейдж + disabled.
- **F4:** решено — 3-колоночная сетка, «ДД.ММ: текст», 12 последних traits, метрики в `#/oversight` через
  `/api/persona/health`.
- **F5:** границы с активной `config-read-path-audit` (что переносим/не дублируем) — уточнить при @Builder;
  sync-await vs optimistic UI; объём live-верификации; включить новые сущности F8/F2/F6.
- **F6:** решено — PG-ключ `content.intelligence_guide` (json PG-only) + идемпотентный сид из файла; Markdown +
  DOMPurify; второй блок в «Справке»; RBAC `edit_info`.
- **F7:** точная позиция «Доступности ключей» относительно «Мониторинга Интеллекта» (после «Сервера»; Q1).

**Покрытие ТЗ (`plans/current_task.md`, разделы 1–7 + UPD 1–5 → фичи):**

| Раздел ТЗ / UPD | Фича(и) |
|---|---|
| п.1 «Механика Самосознания (Anti-Echo & Self-Reflection)» | **F1** |
| п.2 «Архитектура Личности (Dynamic Persona)» | **F2** |
| п.3 «UI: Подраздел "Личность" в разделе "ИИ"» | **F3** |
| п.3.1 «Лента "Эволюция характера"» | **F4** |
| п.4 «Багфикс: сохранение и реактивность параметров» | **F5** |
| п.5 «Актуализация доки» | **F6** |
| п.6 «Расширение справки» | **F6** |
| п.7 «Перестановка Сердцебиения / Мониторинга Интеллекта» | **F7** |
| **UPD п.1** «Снятие DDL-инвариантов; PG-Persona; новый origin» | **F1** (`bot_self_reply`+v9) + **F2** (`personas`/`persona_traits`) |
| **UPD п.2** «Флаги ON по умолчанию; поля пустыми» | **F1** (`flags.bot_self_awareness_enabled`) + **F2/F3** (`flags.persona_enabled`) |
| **UPD п.3** «Экстрактор сути только LLM + 3-е подключение (роль `intel_reflection`)» | **F1** (LLM-экстрактор) + **F8** (провайдер/роль) |
| **UPD п.4** «Метрики Личности в "Сводке" (traits, время, статус экстрактора)» | **F4** (UI) + **F1/F2** (`/api/persona/health`) |
| **UPD п.5** «DOMPurify + БД-редактор Справки (не мёртвый файл)» | **F6** |

**Итог: все 7 разделов ТЗ + 5 пунктов UPD покрыты, 8 фич, 72 задачи (T-1477…T-1548); папки заархивированы.**
**Статус:** ✅ **ЗАВЕРШЁН, ЗАДЕПЛОЕН И ЗААРХИВИРОВАН** (13.09.2026, @PM Step 8 Archive Phase; деплой @DevOps
commit `eb2a232`, прод active PID 1774527, health 200). Планирование (Step 1 @PM,
итерация 2 после UPD владельца) и Step 2 @Architect (ADR-1014-1/2 + spec/tasks F1–F8) завершены; реализация
@Builder (F1–F8), @Reviewer **APPROVED** (итерация 2), @Scanner **0 C/H/M** (2 Low — техдолг, см. блок
«ИТОГ 10.14»), @Architect — `plans/ARCHITECTURE.md` **§35**. Артефакты: **`plans/archive/*-round1014/`**
(**8 папок**). **@PM код не пишет.**

## Раунд 10.13 (13.09.2026): Cognition / Sleep / Memory Refactor — 8 фич — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (13.09.2026; архив @PM 13.09.2026)

**✅ ИТОГ 10.13 (13.09.2026):** реализация завершена, все **8 фич заархивированы** — перенесены
`plans/features/cognition-*-round1013/` → **`plans/archive/cognition-*-round1013/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5392 passed / 1 warning / 0 failed** (база 10.12 = 5211 → **+181**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean
(только LF→CRLF-предупреждения). Каталог — санкционированный прирост ADR-1013-1 (8 новых ключей выделенных
LLM + F8-флаги): **REGISTRY 427 / categorized 403 / Settings 399** (GROUPS 90 / `_TAB_BY_GROUP` 88 /
`TAB_RULES` 19). Инварианты: **ноль новых PG-DDL**, SQLite **v8** не бампнут, порядок роутеров `bot.py` не
тронут (только DI-kwarg `aliases=`), **R17**-скан чист, F7-гайд без запрещённого жаргона (grep 0), новые
`v-html`/CDN нет (vis-network self-host).
**Объём:** **8 фич, 60 задач** (T-1417…T-1476), все `[x]`.
@Reviewer — **APPROVED** (итерация 2; итерация 1 — Rejected по BLOCKER-1 [Critical] T-1439 роутер воркеров и
BLOCKER-2 [High] ностальгия; все BLOCKER и ISSUE-3/-4 закрыты и подтверждены `file:line` —
`plans/reports/round10.13_reviewer.md`).
@Scanner — **CLEAN: 0 Critical / 0 High / 0 Medium** (итерация 2; закрыты High S10.13-1 и 4 Medium
S10.13-2/-3/-4/-5), остаются **5 Low** — техдолг (`plans/reports/round10.13_scanner_audit.md`).
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§34** + связанные разделы).
Артефакты в архиве: `spec.md` + `tasks.md` (×8) + ADR-1013-1 (`adr-1013-1-provider-keys.md`),
ADR-1013-2 (`adr-1013-2-graph-library.md`), ADR-1013-3 (`adr-1013-3-prompt-canon-policy.md`).
**Фичи (финал, все ✅ COMPLETED):** F1 `4d-memory` (T-1417…T-1423) · F2 `belief-decay` (T-1424…T-1433) ·
F3 `deep-sleep` (T-1434…T-1442) · F4 `llm-providers` (T-1443…T-1447) · F5 `dashboard` (T-1448…T-1458) ·
F6 `ekg-logs-bugfix` (T-1459…T-1464) · F7 `user-guide` (T-1465…T-1467) · F8 `irony-dossier` (T-1468…T-1476).

**🧾 Техдолг Low (ОТКРЫТ, 10.13 — не блокеры):** `S10.13-9` (Timeline-лор из in-memory
`get_process_accounting().lore_last_inject_at`, а не `chat_lore_history`), `S10.13-11` (LIKE-маркер парадигм
матчит только 2 варианта JSON-сериализации), `S10.13-13` (три дублирующих парсера `belief_meta`),
`S10.13-14` (возможны «висячие» рёбра после cap в `graph_snapshot`), `S10.13-6b` (остаточная
несогласованность `archived_beliefs` без фильтра парадигм). Источник — `plans/reports/round10.13_scanner_audit.md` §5.
**Дальше:** Step 9 — деплой @DevOps (единый коммит эпика, сейчас НЕ закоммичено); Step 10 — метрики @Memory
(проставит деплой-статус поверх `✅ COMPLETED`).
Ниже — исторический документ планирования эпика (Step 1 @PM).

**Эпик:** `Epic: Cognition-Sleep-Memory Refactor round1013` (@Memory, Step 0). **Источник ТЗ** —
`plans/current_task.md` (разделы 1–10). **HEAD при планировании:** `ce25dc7` (docs-коммит 10.12).
**Базовая линия:** pytest **5211 passed / 0 failed**; `node --check web/app.js` clean;
`node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог-инвариант
**REGISTRY 405 / GROUPS 90 / Settings 377 / mapped 88 / `TAB_RULES` 19**; SQLite **v8**.
Ранее заархивирован 10.12 (`plans/archive/providers-kostik-round1012/`); открытые Scanner-ниты
10.12 (R10.12-2/-3/-4 — info) учтены в фичах.

**8 фич (продолжение нумерации T-1417…, все ✅ COMPLETED — 60/60 задач T-1417…T-1476):**

| # | Фича (папка) | Тип | ТЗ | Зависит от | Приоритет | Задачи |
|---|---|---|---|---|---|---|
| **F1** | `cognition-4d-memory-round1013` | backend | п.1 | — | **P0** (фундамент) | T-1417…T-1423 |
| **F2** | `cognition-belief-decay-round1013` | backend | п.4 + 4.1 | F1 | **P0** | T-1424…T-1433 |
| **F3** | `cognition-deep-sleep-round1013` | backend | п.6 + п.3 (backend) | **F1, F2** | P1 | T-1434…T-1442 |
| **F4** | `cognition-llm-providers-round1013` | frontend | п.3 (UI) | — (независима; согласовать ключи с F3) | P1 | T-1443…T-1447 |
| **F5** | `cognition-dashboard-round1013` | frontend | п.5 + п.7 | **API F2, F3** | P1 | T-1448…T-1458 |
| **F6** | `cognition-ekg-logs-bugfix-round1013` | frontend | п.8 + п.9 | — (независима) | P2 | T-1459…T-1464 |
| **F7** | `cognition-user-guide-round1013` | docs | п.10 | **F1–F6, F8 (последняя)** | P3 | T-1465…T-1467 |
| **F8** | `cognition-irony-dossier-round1013` | backend | п.2 | **F1** (инфра промпт-канона/метки); F2/F3 желательны; параллельно F4/F6 | P1 | T-1468…T-1476 |

**Рекомендуемый порядок исполнения:** **F1 → F2 → F3 → {F4 ∥ F6 ∥ F8} → F5 → F7.**
Обоснование: F1 даёт временные метки/единый RAG и инфраструктуру правки промпт-канона → F2 (decay/resurrection)
→ F3 (deep sleep) опирается на beliefs/архив; F4, F6 и F8 независимы (можно параллельно; F8 затрагивает
персоны/досье/контекст, а не UI «Статус»); F5 нужны API F2/F3; F7 пишется по факту реализации.
**F5 и F6 обе правят `web/index.html`/`web/app.js` (страница «Статус») — исполнять последовательно.
F8 делит `services/prompt_migrations.py` с F1/F2/F3 — ступень вливать в согласованном порядке (аддитивно).**

**Контент по фичам (сжато):**
- **F1 (4D-память, п.1):** префикс `[ММ.ГГГГ | Автор: ]` для фактов RAG, пометка
  `(Внимание: возможно устарело)` для фактов >6 мес (настраиваемо), группировка фактов по времени в
  обычном Сне для выводов о динамике. Модули: `services/summary_memory.py`
  (`_date_prefix:669`/`build_rag_context:693`/`get_rag_context:1958`), `services/dream_worker.py`,
  `services/dream_prompts.py`, `services/tool_router.py` (dig_into_lore).
- **F2 (Belief Decay + Resurrection, п.4/4.1):** weight −0.1/мес без подкрепления >6 мес; `<0.3` →
  `archived_belief`; векторный резонанс (пенальти −0.3, воскрешение при пороге); Сон-Реаниматор
  (отмена дублирующего синтеза + восстановление даты); активация по графу (связки 2–3 узлов в L1).
  Модули: `services/dream_worker.py` (`_write_belief:657`), `services/summary_memory.py` (KNN `:2190`),
  `services/memory_health.py`, `services/memory_maintenance.py`, `web/api/memory_agi.py`.
- **F3 («Глубокий сон», п.6 + backend п.3):** ежедневно сразу после обычного сна; «Поиск по якорям»
  (свежие beliefs + выжимка 12ч → RAG ко всей базе); синтез «Мост времени» (парадигма); парадигмы в
  контекст с весом 0.5–0.6; бэкенд-роутер моделей воркеров (историческая память/вехи/лор vs фоновые).
  Модули: `services/dream_worker.py`, `services/dream_prompts.py`, `services/worker_budget.py`,
  `services/llm_client.py`, `services/lore_worker.py`, `services/nostalgia_worker.py`, `web/api/memory_agi.py`.
- **F4 («Провайдеры» UI, п.3):** 2 новых блока подключения (LLM для Исторической памяти/Вехи/Лор;
  LLM для Фоновых проверок/Оценка важности), фоллбэк на основную модель. Формат **parent+subBlocks (10.12)**,
  обязательны `providerCoveredKeys` + `_BLOCK_SAVED_KEY`. Модули: `web/app.js`, `web/index.html`,
  `services/llm_probe.py`, `services/param_catalog.py`, `config/settings.py`, `bot.py` (DI-kwargs).
- **F5 (Дашборд Cognition + виджет «Интеллект и Память», п.5/п.7):** две вертикальные бегущие строки
  (Убеждения/Сон, Парадигмы/Глубокий сон; верх/низ opacity-50, центр 100), бейджи
  `[🌙 Сон активен]`/`[🌌 Глубокий сон активен]`, интерактивный force-directed граф (`vis-network`/`d3.js`),
  статистика → «Модули»; виджет в «Сводке» (пульс процессов, прогресс-бары лимитов/бюджета, метрики БД,
  Timeline). Модули: `web/app.js`, `web/index.html`, `web/api/memory_agi.py`, `web/api/routes.py`,
  `services/status_service.py`, `services/worker_budget.py`.
- **F6 (EKG + багфикс «Логи», п.8/9):** удалить линейный график аптайма, добавить SVG-EKG с CSS-анимацией
  (Load/CPU/RAM: спокойный зелёный ↔ учащённый оранжевый/красный); починить рассинхрон селектора
  `INFO` vs `ALL`, новый комбинированный тег `ERROR+WARNING`, дефолт фильтра при открытии = `ERROR+WARNING`.
  **Контракт `GET /api/status/logs` изменится** — маркерные тесты учесть. Модули: `web/app.js`
  (`logLevel:860`/`loadLogs:3786`/`renderUptimeChart:3575`), `web/index.html` (`:2714-2768`),
  `web/api/routes.py` (`:1124`), `services/log_ring.py` (`get_entries:139`), `services/uptime_heartbeat.py`.
- **F7 (docs, п.10):** `plans/docs/intelligence_user_guide.md` — прозаично, простыми словами, без
  аббревиатур (RAG/LLM/токены/эндпоинты), иронично, готово к публикации; актуализация README (иронично) +
  `APP_VERSION`/cache-bust, русский коммит, push, деплой, отчёт.
- **F8 (Ирония и Досье Персонажей, п.2):** «Иронический фильтр» в системный промпт воркера досье; явная
  инструкция про `chat_memes` vs `real_facts` («мегачмо», «повелитель грибов» → мемы, не биография);
  досье в контексте — два блока `[Факты]`/`[Локальные мемы/Ярлыки]`. **Greenfield:** `real_facts`/`chat_memes`/
  `dossier` в коде НЕТ — сущность/воркер фиксирует @Architect (T-1468). Хранение `chat_memes` — только в
  существующей JSONB `chat_profiles.relations` или SQLite-поле `graph_facts` (**ноль PG-DDL**); правка канона —
  PREV-слепок + `prompt_migrations` + байт-тесты. Модули: `services/lore_worker.py`, `services/lore_prompts.py`,
  `services/lore_cache.py`, `services/chat_lore_store.py`, `services/database.py`
  (`get_persona_card:3118`/`get_protected_facts:2623`), `services/direct_chat_service.py`
  (`build_persona_card:1443`/`_build_user_relations:824`), `services/summary_memory.py`,
  `services/prompt_migrations.py`.

**Инварианты раунда (в каждой tasks.md §3):** ноль новых PG-DDL; SQLite **v8**; порядок роутеров `bot.py`
не трогать (только DI-kwargs); новые provider-блоки — только `parent`+`subBlocks` (10.12) + обязательно
`providerCoveredKeys` и `_BLOCK_SAVED_KEY`; каталог-инварианты **405/90/377/88**, `TAB_RULES` 19 — новые
ключи только санкционированным Δ с обновлением пин-тестов; **R17** секреты `{configured, last4}`;
**R16** id — ключ, не имя; `chat_memes` (F8) — только в существующей JSONB `chat_profiles.relations` или
SQLite-поле `graph_facts`, без миграции схемы; правка промпт-канонов — PREV-слепок + `prompt_migrations` +
байт-тесты; контракт `/api/status/logs` меняется (комбинированный тег) — маркерные тесты;
русские conventional commits.

**⚠️ Open (Step 1, для @Architect):**
- **ТЗ п.2 «Ирония и Досье Персонажей» — ✅ ДЕКОМПОЗИРОВАН 13.09.2026 @PM (Step 1 return):** выделена
  **8-я фича F8** `cognition-irony-dossier-round1013` (T-1468…T-1476) — см. строку F8 выше.
  Greenfield-вопросы (какой воркер = «Досье», где хранить `chat_memes`, формат блоков) — на @Architect (T-1468).
- **F4↔F3:** имена PG-ключей выделенных LLM (UI F4 / роутер F3) фиксируются одним ADR — согласовать.
- **F1↔промпт-канон:** правка `dream_prompts.py` требует PREV-слепка + `prompt_migrations` + байт-тестов —
  оценить объём. **F8 делит `prompt_migrations.py` с F1/F2/F3** — вливать ступени согласованно.

**Статус:** ✅ **ЗАВЕРШЁН И ЗААРХИВИРОВАН** (13.09.2026, @PM Step 8 Archive Phase). Планирование (Step 1)
завершено @PM 13.09.2026; раздел п.2 закрыт фичей F8 (`cognition-irony-dossier-round1013`,
T-1468…T-1476) — все 10 разделов ТЗ покрыты (таблица покрытия — §«Покрытие ТЗ»). Реализация @Builder
(F1–F8), @Reviewer **APPROVED** (итерация 2), @Scanner **0 C/H/M** (5 Low — техдолг, см. блок «ИТОГ 10.13»),
@Architect — `plans/ARCHITECTURE.md` **§34**. Артефакты: **`plans/archive/cognition-*-round1013/`**
(**8 папок**: `spec.md`, `tasks.md`, ADR-1013-1/2/3).

**Покрытие ТЗ (раздел `plans/current_task.md` → фичи):**

| Раздел ТЗ | Фича(и) |
|---|---|
| п.1 «4D-Память» | **F1** |
| п.2 «Ирония и Досье Персонажей» | **F8** |
| п.3 «Выделенные LLM для Интеллекта» | **F3** (backend-роутер) + **F4** (UI-провайдеры) |
| п.4 «Охлаждение Убеждений» | **F2** |
| п.4.1 «Воскрешение» | **F2** |
| п.5 «UI: Дашборд Осмысление + Графы» | **F5** |
| п.6 «Мета-синтез / Глубокий сон» | **F3** |
| п.7 «Виджет Интеллект и Память в Сводке» | **F5** |
| п.8 «Анимация Heartbeat (EKG)» | **F6** |
| п.9 «Багфикс компонента Логи» | **F6** |
| п.10 «Человекочитаемая документация» | **F7** |

**Итог: все 10 разделов покрыты, 8 фич, дыр нет.**

## Раунд 10.12 (12.09.2026): развязка base_url провайдеров (embed ≠ direct) + merge блоков подключения + фразы Костика в PERMsoc — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (13.09.2026; архив @PM 13.09.2026)

**✅ ИТОГ 10.12 (13.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/providers-kostik-round1012/` → **`plans/archive/providers-kostik-round1012/`**
(@PM Step 8).
**Финальные метрики:** полный **pytest — 5211 passed / 0 failed** (база 10.11 = 5172 → **+39**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог — финальный
инвариант **REGISTRY 405 / GROUPS 90 / Settings 377** (санкционированный прирост: новые параметры
`base_url` embed/direct + редактируемый список фраз Костика, ADR-1012-1); R17-скан чист.
@Reviewer — **APPROVED WITH MINOR ISSUES** (дефекты 1–4 закрыты @Builder); @Scanner — **CLEAN**
(low закрыты follow-up; `plans/reports/round10.12_scanner_audit.md`); @Architect — архитектура влита
в `plans/ARCHITECTURE.md` (**§33**).
Артефакты в архиве: `spec.md`, `ADR-1012-1.md`, `tasks.md` (со статус-хедером завершения).
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.12 (@DevOps, 13.09.2026):** commit
`708f7dffa3f9ef46136e33321116055dfd37191a` (`feat(admin,web,api,handlers,plans): раунд 10.12 —
развязка эмбеддингов, фикс сохранения глобальных ключей, объединённые блоки провайдеров, фразы Костика
(тесты 5211)`, 39 файлов), push `32d1aa9..708f7df` (origin/master); README **5211** / `APP_VERSION`
**2.56.0** (+ cache-bust `?v=2.56.0`; `test_app_version_matches_readme`/`test_index_version_param`
зелёные). Локальная верификация: `pytest tests/` → **5210 passed / 1 skipped / 0 failed**
(skip — нет локального `fontTools` в `test_font_subset.py:128`; в каноничном окружении — **5211**);
`node --check web/app.js` clean; `node tests/js/routing_test.js` → **JS-UNIT-OK**.
**Прод** `198.46.175.136:/var/www/admin_bot` — `git pull --ff-only` **`3624789..708f7df`**
(fast-forward; локальные `info_text.md`/бэкапы не конфликтовали).
**`.env` (потребовалась правка, бэкап `.env.bak.1012`):** `LLM_BASE_URL`
`https://apinet.cloud/v1` → **`https://nano-gpt.com/api/v1`** (direct-ответы); добавлен
`EMBEDDING_BASE_URL=https://apinet.cloud/v1`. **Миграция (ADR-1012-1 D1/D3/D4/D5, без `--force`):**
`venv/bin/python scripts/migrate_env_to_pg.py --only-category models,keys,reactions,flags` →
**`created=5 skipped=149`** (models:2, keys:1, reactions:1, flags:1), идемпотентно. Созданы:
`models.embedding_base_url` = **`https://apinet.cloud/v1`**, `models.openrouter_transcribe_display_name`
= `""` (пусто → в UI покажется адрес), `keys.embedding_api_key` = `""` (пусто → рантайм-фолбэк на
`keys.llm_api_key`, OD-1), `reactions.kostik_replies` = список из **14** фраз, `flags.kostik_enabled`
= **true**. Существующие значения сохранены (`ON CONFLICT DO NOTHING`): **resolved
`models.llm_base_url` = `https://nano-gpt.com/api/v1`** (не перезаписан), **resolved
`models.embedding_base_url` = `https://apinet.cloud/v1`**, `limits.kostik_reply_probability` = `0.1`
(прод-значение сохранено). `systemctl restart admin_bot` → **active (running)** (Main PID 1534535,
ActiveEnter 2026-09-12 12:43:59 UTC); `/api/health` → **200 `{"status":"ok"}`**; стартовые логи —
**0 app ERROR/Traceback** (только benign systemd cgroup-варнинги стопа и pre-existing BetterStack 401).
Маркеры 10.12 в проде: `/web/` и `/web/app.js` с `?v=2.56.0`; в `app.js` —
`blockDisplayName`, `list-editor`, `models.embedding_base_url`, `per_chat === false` (4×),
`options.global`, `flags.kostik_enabled`, `reactions.kostik_replies`; в `/web/` — `list-editor-tpl`.
**✅ PROD-деплой закрыт** (README/`APP_VERSION`/cache-bust синхронны; русский commit; push;
pull/restart/status; health **200**; 0 ERROR/Traceback; маркеры 10.12 на месте).
**⚠️ ОТКРЫТО (live Android/Telegram QA, за владельцем/QA):** правка base_url обоих провайдеров
(embed ≠ direct, без взаимного алиасинга); надпись «Название модели» у всех подключений; merged-блоки
(основная+запасная, транскрибация, саммаризация видео); список фраз Костика (add/delete/save) и
реальный ответ Костику.
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/providers-kostik-round1012/` (kebab: `providers-kostik-round1012`; `tasks.md` создан 12.09.2026 @PM; архивирована 13.09.2026 @PM Step 8).
**Нумерация:** **T-1382…T-1408** (продолжает T-1381 — финал 10.11).
**Преемник:** 10.11 `llm-providers-refactor-round1011` (архив; commit `3624789`, прод health 200, pytest 5172).
**Раунд подтверждён:** **10.12** (HEAD `32d1aa9`).
Базовая линия: pytest **5172 passed / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
Каталог-инвариант: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19.
Инварианты: **ноль новых PG-DDL**, SQLite **v8**, `bot.py`-порядок/`media/`/`.env` не трогать, R16/R17.
UI + аддитивный серверный read-path ⟹ feature-flag не требуется, rollback = `git revert`.

**Запрос владельца (`plans/current_task.md`, дословно — `tasks.md` §1):**
1. **BUG:** изменение base_url основного провайдера (`models.llm_base_url`, сейчас `https://nano-gpt.com/api/v1`)
   падает «models.llm_base_url: ключ нельзя переносить на уровень чата», и base_url основного эмбеддинга
   тоже меняется на этот url. Эмбеддинги и основная модель — разные провайдеры, не должны зависеть друг от
   друга. Требуется: **embeddings base_url = `https://apinet.cloud/v1`**, **direct answers base_url =
   `https://nano-gpt.com/api/v1`**. **Без хардкода.**
2. **Блоки подключения:** маленькая надпись у header каждого подключения = значение поля **«Название модели»**;
   «Фолбэк-модель» → **«Запасная модель»** (+ merge в один блок с основной); «Groq (расшифровка)» →
   **«Модель транскрибации»**, «OpenRouter (запасной)» → **«Запасная модель транскрибации»** (+ merge);
   «Видео-модель (OpenRouter)» → **«Саммаризация видео»**, «Запасная видео-модель» → **«Запасная модель
   саммаризации видео»** (+ merge). Проверить семантику транскрибация vs саммаризация (подозрение на своп).
3. **PERMsoc Костик:** вынести захардкоженные фразы (`handlers/kostik.py:30-39` `KOSTIK_REPLIES`) в
   редактируемый список в блоке Костика (каждая фраза — плотное отдельное поле, add/delete); заменить на
   4 фразы владельца + 10 новых; проверить параметр частоты.
4. **Финал:** README (ирония), русский коммит, push, деплой (ssh → pull → restart → status), plain-language отчёт.

**Рекогносцировка (@PM, `32d1aa9`, file:line — детали `tasks.md` §2):**
- **п.1 (root cause 422):** `saveBlock` `web/app.js:2181-2225` → `api()` авто-`X-Chat-Id` `:1253-1254` →
  `routes.py:414-417` 422 при `per_chat=False`; `models.*` `per_chat=False` (`param_catalog.py:110-119`).
  **(root cause алиасинга):** `embeddings_main` биндит `models.llm_base_url` (`web/app.js:417`) — тот же
  ключ, что `direct_main` (`:362`); в рантайме `LLMClient._post` всегда `self._base_url`
  (`llm_client.py:534-544`) и `embed()` идёт туда же (`:926-942`) — отдельного embed-base-url
  settings **нет** (`config/settings.py:317-320`); `status_service.emb_main` тоже берёт `main_base`
  (`:163-164,251-256`). Точки LO `bot.py:316,486,515,542`.
- **п.2:** `PROVIDER_BLOCKS` `web/app.js:358-466` (merge-пары `:359-373`, `:374-388`, `:389-407`;
  subBlocks `:408-436`); рендер/надпись `web/index.html:806-811,946-994` (`.prov-modules` = `{{ b.modules }}` `:810`);
  маппинг/blocks `web/app.js:957-966,2800-2838`; display-name каталог `param_catalog.py:562-577`.
  **Семантика:** STT `handlers/voice_transcription.py:184`→`SmartModule/service.py:69-116` (Groq/OpenRouter
  транскрайберы) — транскрибация; `youtube_summarizer_service.py:101-147,254-303` + `video_cascade_client.py`
  — саммаризация (`video_primary/fallback_model`). **Свопа в коде нет** (подтверждено file:line) — причина
  ощущения: общий `models.openrouter_*`/display-name.
- **п.3:** фразы `handlers/kostik.py:30-39`, выбор `:54`, гейт `:42` `PermsocGateFilter("kostik")`;
  модуль `services/permsoc.py:55-57` (sub-флаг None); каталог-группа `reactions_kostik`
  (`param_catalog.py:311-312`, `KOSTIK_USER_ID` `:1139`; вкладка `:1701`); **частота ЕСТЬ** —
  `limits.kostik_reply_probability` (`settings.py:165`, `.env.example:22`, чтение `handlers/kostik.py:47-48`)
  в группе «Костик: лимиты»; **отдельного owner-блока Костика в `PERMSOC_OWNER_BLOCKS` нет**
  (`web/app.js:473-494` — группа уходит в «Общее»).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.11_scanner_audit.md` (0 blocker/0 major/0 medium;
3 low + 3 info) и `audit_backlog.md`. Включено точечно: R10.11-1 (nested `<details>`/localStorage →
T-1394), R10.11-2/R10.9-2 (embed-status vs runtime → T-1384/T-1386), R10.11-3 (.env-подсказки → T-1383),
R10.11-4 (probe caller base_url → OPEN-Q6), R10.6-1 (generic-дубль → providerCoveredKeys).
**Открытые вопросы (6 шт.)** — `tasks.md` §7 (Q1 дефолты/миграция адресов; Q2 общий openrouter display/base;
Q3 частота в блоке Костика; Q4 owner-блок Костика; Q5 виджет списка фраз; Q6 hardening probe). **@PM код не пишет.**
**Статус:** планирование завершено — передано `@Architect` (spec/ADR), затем `@Builder`/`@DevOps`.

## Раунд 10.11 (12.09.2026): память/сон/ностальгия-отчёт + LLM Провайдеры refactor + key-chart fix — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (12.09.2026; архив @PM 12.09.2026)

**✅ ИТОГ 10.11 (12.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/llm-providers-refactor-round1011/` → **`plans/archive/llm-providers-refactor-round1011/`**
(@PM Step 8).
**Финальные метрики:** полный **pytest — 5172 passed / 0 failed** (база 10.10 = 5145 → **+27**;
@Scanner зафиксировал **5168** на момент аудита — до follow-up R10.11-1/-2/-3); `node --check web/app.js`
clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог-инвариант
**REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88** (без роста; `categorized` **376** — sanctioned
Δ ADR-1011-2: models 40→42, keys 13→15, infra 28→24).
@Reviewer — **APPROVED WITH MINOR ISSUES** (CRITICAL/HIGH/MEDIUM исправлены @Builder); @Scanner —
**CLEAN: 3 low закрыты follow-up, 3 info → техдолг §25** (`plans/reports/round10.11_scanner_audit.md`);
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§32** + §5/§9/§25).
**✅ Пункт 4 (docs-only, без кода) — ЗАВЕРШЁН:** отчёт
**`plans/docs/memory_sleep_nostalgia_lore_report.md`** (6 тем, проза, простыми словами, каждая цифра
с `file:line`); принят @PM (T-1342).
Артефакты в архиве: `spec.md`, `ADR-1011-1.md`, `ADR-1011-2.md`, `ADR-1011-3.md`, `tasks.md`
(со статус-хедером).
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.11 (@DevOps, 12.09.2026):** commit `3624789`
(`feat(admin,web,api,scripts,plans): раунд 10.11 …`, 28 файлов, тесты 5172), push `ec5dd1f..3624789`
(origin/master); README **5172** / `APP_VERSION` **2.55.0** (+ cache-bust `?v=2.55.0`; тесты
`test_app_version_matches_readme`/`test_index_version_query_param` зелёные); прод
`198.46.175.136:/var/www/admin_bot` — `git pull` `772db08..3624789` (fast-forward; `.env` не менялся).
**Миграция каталога (ADR-1011-2):** `venv/bin/python scripts/migrate_env_to_pg.py --only-category
models,keys` (без `--force`) → `created=5 skipped=48` (keys:3, models:2), идемпотентно; 4
embed-фоллбэк-записи резолвятся (`models.embedding_fallback_base_url` =
`https://generativelanguage.googleapis.com/v1beta/openai`, `_model` пустой → рантайм-фолбэк на
основную embed-модель, `keys.embedding_fallback_api_key`/`_2` — `configured(len=53)`); существующие
значения сохранены (ON CONFLICT DO NOTHING). `systemctl restart admin_bot` → **active (running)**
(Main PID 1498180); `/api/health` → **200 `{"status":"ok"}`**; стартовые логи нового PID —
**0 ERROR/Traceback**; `/web/` и `/web/app.js` несут маркеры 10.11
(`providerConnectionBlocks`/`providerAdvancedBlocks`/`subBlocks`/`blockFieldConfigured`/`spanGaps: true`/
`type: 'linear'`/`?v=2.55.0`); `POST /api/llm/test` достижим (**401** без initData — auth, не 404/500).
**⚠️ ОТКРЫТО (live Android/Telegram QA, за владельцем/QA):** **T-1377** — поле ключа + «Проверить»
без повторного ввода; навигация/профиль/сетка; две зоны «Провайдеры»; эмбеддинги (3 подблока);
видео-фоллбэк; media-share внизу; график доступности ключей (статически покрыто
`tests/test_webapp_round1011_ui.py`, JS-юнитами).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/llm-providers-refactor-round1011/` (kebab: `llm-providers-refactor-round1011`; `tasks.md` создан 12.09.2026 @PM; архивирована 12.09.2026 @PM Step 8).
**Нумерация:** **T-1340…T-1381** (продолжает T-1339 — финал 10.10).
**Преемник:** 10.10 `admin-ui-round1010` (архив; commit `ec5dd1f`, прод health 200, pytest 5145).
**Раунд подтверждён:** **10.11** (HEAD `ec5dd1f`).
Базовая линия: pytest **5145 passed / 1 skipped / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
Каталог-инвариант: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19. Инварианты: **ноль новых PG-DDL**, SQLite **v8**, `bot.py`/`media/`/`.env` не трогать, R17. UI/docs-only ⟹ feature-flag не требуется, rollback = `git revert`.

**Дословный запрос владельца (`plans/current_task.md`, приложен, добавлен в `.gitignore`):**
1. **Поле ключа провайдера:** при сохранённом ключе «Проверить» падает «ключ не задан» — сделать, чтобы ключ был явно в поле, если присвоен параметру (иначе пусто), и проверка работала без повторного ввода.
2. **Масштабный рефакторинг UI «LLM Провайдеры» + верхняя навигация** (интуитивно новичку, прагматично, без лишних компонентов):
   2.1 шапка/навигация — крупнее и плотнее иконки, зафиксировать блок профиля (аватар/ник/фулскрин), центрировать+сделать адаптивной сетку карточек;
   2.2 две зоны: **«Подключения»** (сверху, только модели) и **«Расширенные настройки»** (внизу, спойлер с таймаутами/ретраями/защитой);
   2.3 **«Эмбеддинги»** — 1 блок = ровно 3 подблока (Основная / Фоллбэк 1 / Фоллбэк 2), фоллбэкам полный набор полей (Base URL/Модель/ключ/«Проверить»);
   2.4 видео — запасную OpenRouter-модель поднять наверх под основную, полный набор полей, **убрать хардкод**;
   2.5 «Медиа-шара» — вниз в расширенные + human-subtext; весь теххаос (таймауты/защита/поиск-ключи/таймауты-повторы/отпечатки/Circuit Breaker/лимиты Groq) — в самый низ.
3. **Багфикс графика «История доступности ключей»** — разреженные данные дают разорванные чёрточки; нужен непрерывный ступенчатый график (`spanGaps:true`/`stepped:true` или range-маппинг) и X как временная шкала (`time`/`datetime`).
4. **Задача БЕЗ кода:** подробный прозаичный отчёт простыми словами о памяти, сне/синтезе воспоминаний, ностальгии, формировании лора чатов, таймингах/лимитах и сборке контекста (сначала пункт 4).
**Плюс:** README (ирония), русский коммит, push, деплой (ssh → pull → restart → status), human-readable отчёт.

**Рекогносцировка (@PM, `ec5dd1f`, file:line — детали `tasks.md` §2):**
- **п.1:** `PROVIDER_BLOCKS` `web/app.js:369-441` (secret-поля `:375,383,390,398,406,432,434,438`); `blockFieldValue` `:2047-2054` (object-маска → `''`); `blockFieldPlaceholder` `:2055-2061` (`configured ••••last4`); input `web/index.html:807-812`; `testBlock` `:2062-2090` (api_key только если truthy `:2071`); `saveBlock` `:2120-2160` (MINOR-3); `_mask_secret` `web/api/routes.py:194-203`; тест `web/api/routes.py:1243-1264` → `services/llm_probe.py:144-145` (`not_configured "ключ не задан"`) — **root cause подтверждён**.
- **п.2:** рендер `web/index.html:794-842`; данные `web/app.js:645-646`; nav `web/index.html:731-739` + CSS `.navbar-band/.nav-link/.nav-icon` `:204-229` (icon 18px), профиль `:712-727`; hub-сетка `:757-781` + `.hub-grid` `:248-251`; эмбеддинги `web/app.js:408-417` (`testable:false`), видео `:400-407`, media_share `:436-440`, тех-блоки `:418-435`; каталог-группы — `services/param_catalog.py`.
- **п.3:** `keyHistoryChartModel` `web/app.js:3473-3545` (`stepped:true` `:3533`, `spanGaps:false` `:3536`), `renderKeyHistoryChart` `:3546-3590`, X категориальная (`:3577-3578`); canvas `web/index.html:2617-2619`; данные `services/key_history.py`, API `web/api/routes.py:1090-1118`; Chart.js 4 CDN `web/index.html:3040` (time-adapter отсутствует); JS-юниты `tests/js/routing_test.js:586-660`.
- **п.4:** отчёт @Architect по сервисам памяти/сна/ностальгии/лора/контекста (`services/memory*`, `dream*`/`sleep*`, `nostalgia*`, `chat_lore.py`, `context*`; гейты `services/feature_gates.py`; лимиты `services/param_catalog.py`) → **`plans/docs/memory_sleep_nostalgia_lore_report.md`** (ранее ошибочно `plans/reports/round10.11_memory_report.md`).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.10_scanner_audit.md` (0 blocker/0 major/0 medium; low R10.10-1/-2 скрипт DM, R10.10-3 chart-return — **уже закрыт** в 10.10, info R10.10-4/-5). В скоуп 10.11 из аудита прямо ничего не входит; T-1374 перепроверяет R10.10-3 регрессом. `audit_backlog.md` — пересечений blocker/major нет.
**Открытые вопросы (6 шт.)** — `tasks.md` §7 (Q1: ширина/центрирование сетки; Q2: реальные ключи эмбеддинг-фоллбэков vs Δ каталога; Q3: место хардкода видео-фоллбэка и дефолт; Q4: Chart.js time-adapter vs линейная ось; Q5: резолв сохранённого ключа без нарушения R17; Q6: «Поиск: ключи» = advanced или connections). **@PM код не пишет.**
**Статус:** планирование завершено — передано `@Orchestrator` (историческая запись; раунд **завершён и заархивирован** 12.09.2026 @PM Step 8).

## Раунд 10.10 (12.09.2026): admin UI bugfix + DM-модули OFF + Headroom stats — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (12.09.2026; архив @PM 12.09.2026)

**✅ ИТОГ 10.10 (12.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/admin-ui-round1010/` → **`plans/archive/admin-ui-round1010/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5145 passed / 1 skipped / 0 failed** (база 10.9 = 5105 → **+40**;
+1 — регресс-тест standalone-CLI `scripts/disable_dm_heavy_modules.py`, devops-fix `a477747`);
каталог-инвариант **REGISTRY 400 / GROUPS 90 / Settings 372** (mapped 88).
@Reviewer — **APPROVED WITH MINOR ISSUES** (follow-ups закрыты); @Scanner — **CLEAN: low/info**
(большинство находок устранено) (`plans/reports/round10.10_scanner_audit.md`); @Architect — архитектура
влита в `plans/ARCHITECTURE.md` (**§31** + связанные разделы).
Артефакты в архиве: `spec.md`, `ADR-1010-1.md`, `ADR-1010-2.md`, `ADR-1010-3.md`, `tasks.md`
(со статус-хедером).
**⚠️ ОТКРЫТО (PROD data-run, за @DevOps, пост-архив):** **T-1327** — применить DM-скрипт на сервере
(`scripts/disable_dm_heavy_modules.py`: `--dry-run` → `--apply` → повторный `--dry-run` = 0 изменений;
снапшот до apply), затем **T-1328** (верификация: ни одна активная ЛС не имеет модулей ON);
**T-1333** (Headroom stats через серверный прокси); **T-1337/T-1338** (русский commit / push / deploy,
health 200).
**⚠️ ОТКРЫТО (live Android/Telegram QA, за владельцем/QA):** **T-1317** (fullscreen header),
**T-1320** (mobile key-availability chart), **T-1323** (провайдеры: реальные значения полей),
**T-1332** (роли: аватар+ник, ширины) — статически покрыто (`tests/test_webapp_round1010_ui.py`,
JS-юниты).
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.10 (@DevOps, 12.09.2026):** commits `d082800` (раунд, тесты 5144) +
`a477747` (fix scripts: standalone `sys.path` bootstrap + CLI-тест, тесты 5145); push `da85b60..a477747`;
прод `198.46.175.136:/var/www/admin_bot` `git pull --ff-only` `d2d1215..a477747` (fast-forward; `.env`
не менялся); `systemctl restart admin_bot` → **active (running)** (Main PID 1338398);
`/api/health` → **200 `{"status":"ok"}`**; стартовые логи — **0 ERROR/Traceback**; README **5145**,
`APP_VERSION` **2.54.0**. **T-1327/T-1328 (DM data-run):** активная ЛС `5885953495` — `--dry-run` 1 план →
`--apply` (changed=1/noop=0/total=1/errors=0) + снапшот
`var/dm_modules_off_snapshot_20260911T201219Z.json` (до записи) → повторный `--dry-run` **0 изменений**
(идемпотентно); сон/ностальгия/саммаризация — OFF. **Остаётся за владельцем/QA:** live Android
(T-1317/T-1320/T-1323/T-1332).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/admin-ui-round1010/` (kebab: `admin-ui-round1010`; `tasks.md` создан 12.09.2026 @PM; архивирована 12.09.2026 @PM Step 8).
**Нумерация:** **T-1315…T-1339** (продолжает T-1314 — финал 10.9).
**Преемник:** 10.9 `admin-ui-round109` (архив; задеплоен 12.09.2026; commit `d2d1215`, прод fast-forward, health 200).
**Раунд подтверждён:** **10.10**.
Базовая линия: pytest **5105 passed / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
Каталог-инвариант: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88**, `TAB_RULES` 19. **Ноль новых PG-DDL**; `bot.py`/`media/`/`.env` не трогать.

**Дословный запрос владельца (пункты 1–6, дословно в `tasks.md` §1):**
1. **Header padding в FULLSCREEN:** блок профиля (аватар + ник + роль + fullscreen) не перекрывается нативными кнопками Telegram.
2. **Mobile:** график доступности ключей рендерится некорректно (одна плоская полоса) — починить.
3. **«Провайдеры»:** поля Название/Адрес/Модель/Ключ должны показывать **реальные** текущие значения (сейчас выглядят пустыми); поле «Ключ» уже показывает текущее — **оставить как есть**.
4. **ЛС:** модули **сон / ностальгия / саммаризация** — **OFF по умолчанию**; выключить для **ВСЕХ текущих активных ЛС** (data-change существующих чатов).
5. **«Роли»:** список должен показывать **аватар+ник** вместо голого ID (ID — мелким серым рядом); **уменьшить ширину селектора ролей**, **расширить поле ID**.
6. **Headroom stats:** получить и вывести текущую статистику сэкономленных токенов (`headroom_stats` MCP; через серверный прокси).
**Плюс:** README (ирония), русский коммит, push, деплой, plain-language отчёт.

**Рекогносцировка (@PM, HEAD `da85b60`, дерево чистое) — опорные точки (детали `tasks.md` §2):**
- **п.1** шапка `web/index.html:628-722`, блок профиля `:694-709`, fullscreen CSS `:594-612`, safe-area `:588-591,616-620`; JS `web/app.js:717,2344-2358`.
- **п.2** `renderKeyHistoryChart` `web/app.js:3425-3481` (union `ts`, `stepped`, `spanGaps:false`, legend bottom); данные `services/key_history.py:126-203` (ring 5-мин слоты); canvas `web/index.html:2585` (`height="80"`); `GET /api/status/key-history` `web/api/routes.py:1090-1102`.
- **п.3 (root cause найден)** `PROVIDER_BLOCKS` `web/app.js:366-438`; форма `v-model="blockDrafts[f.key]"` `web/index.html:788`; `blockDrafts` создаётся пустым `web/app.js:643` и **нигде не наполняется** → инпуты пустые; `blockFieldValue` (`:2036-2043`) используется только для test/save; «Ключ» показывается через placeholder/маску (`:2044-2050`) — не трогать.
- **п.4 (хранилище)** PG `chat_profiles.chat_params` JSONB (`services/chat_params.py:1-9,41-85`; схема `services/pg_db.py:76-83`): `overrides` (per-chat значения) + `gates` (`dream`/`nostalgia`/`lore_auto`/`permsoc`, `services/feature_gates.py`). DM-идентификатор: `services/chat_params.py:31-35 is_dm_scope` = **`chat_id > 0`**; активные — `is_active=TRUE`. Ключи: Сон `memory.dream_enabled` + gate `dream`; Ностальгия `memory.nostalgia_enabled` + gate `nostalgia`; Саммаризация `flags.summary_enabled` (бегущий конспект — `flags.chat_running_summary_enabled`, уже DM-default OFF через `chat_params.py:397-412`). Безопасный флип — идемпотентный скрипт (`--dry-run`/`--apply`, прецеденты `scripts/backfill_*_gates.py`), снапшот до apply, без DDL.
- **п.5** окно «Роли» `web/index.html:1579-1621` (список `:1598-1605`, формы `:1608-1614`); данные `loadAdmins` `web/app.js:2940-2946` → `GET /api/admins` `web/api/routes.py:705-712` (`cache.admins_full()`, без имени/фото); обогащение — паттерн `user_display_info` `web/api/chat_lore.py:44,60,577-630`, аватары `web/app.js:1232,1266-1298`.
- **п.6** внешний MCP `headroom_stats` через серверный прокси (read-only; R17).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.9_scanner_audit.md` (0 blocker / 0 major / 0 medium; 3 low + 3 info) и `audit_backlog.md`. Включено P2-точечно: **R10.9-1** (`model_source`) и **R10.9-3** (stale docstring `status_service.py`) → **T-1334**. Вне скоупа — follow-up (R10.9-2/-4/-5, R10.7-1/-2, R10.6-1/-2/-3).
**Открытые вопросы (5 шт.)** — `tasks.md` §7 (величина отступа fullscreen; данные vs рендер графика; ключ «саммаризации» для ЛС; источник ника админов; способ забора `headroom_stats`). **@PM не пишет код.**

## Раунд 10.9 (12.09.2026): UI/UX-полировка + model-status — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (12.09.2026; архив @PM 12.09.2026)

**✅ ИТОГ 10.9 (12.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/admin-ui-round109/` → **`plans/archive/admin-ui-round109/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5105 passed / 0 failed** (база 10.8 = 5076 → **+29**);
каталог-инвариант **REGISTRY 400 / GROUPS 90 / Settings 372** (mapped 88; `TAB_RULES`/`CONFIG_TAB_TITLES` = 19).
@Reviewer — **APPROVED WITH MINOR ISSUES** (1 Critical + 1 High + 2 Medium + 3 Low — все устранены,
follow-ups закрыты); @Scanner — **CLEAN: 0 blocker / 0 major / 0 medium**
(3 low R10.9-1/-2/-3 + 3 info R10.9-4/-5/-6 — известный точечный техдолг)
(`plans/reports/round10.9_scanner_audit.md`); @Architect — архитектура влита в
`plans/ARCHITECTURE.md` (**§30** + связанные §1/§9/§25).
Артефакты в архиве: `spec.md`, `ADR-109.md`, `tasks.md` (со статус-хедером).
**R10.9-6 (info, backlog-статус) — ✅ ЗАКРЫТО:** раздел переведён «🟡 ПЛАНИРОВАНИЕ» → «✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН».
**⚠️ [OUT OF SCOPE] Пункт 2 (инфраструктура IDE):** инструмент локального IDE владельца
(OpenCode), **не часть бота**; операционного содержимого (systemd-юнит, firewall,
`opencode.jsonc`) в проекте/архиве нет — только маркеры «вне скоупа».
**Открыто (live-верификация на реальном Android):** **T-1277** (PERMsoc-блоки/тумблеры),
**T-1290** (описания «глазами новичка»), **T-1292** (гейты после удаления «Тяжёлых фич»),
**T-1294** (бюджет в «Сводке»), **T-1302** (dashboard/health), **T-1305** (мобильный dashboard) —
за владельцем/QA; статически покрыто (`tests/test_webapp_round109_ui.py`, JS-юниты).
Пост-архивная фаза @DevOps (commit/push/deploy/live-smoke, **T-1309…T-1311**) — после архивации.
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.9 (@DevOps, 12.09.2026):** commit `d2d1215`, push `51f308b..d2d1215`;
прод `198.46.175.136:/var/www/admin_bot` `git pull --ff-only` `31d2ce7..d2d1215` (fast-forward,
`.env` не менялся — UI-only, новые env-ключи не требуются); `systemctl restart admin_bot` →
**active (running)** (Main PID 1310051); `/api/health` → **200 `{"status":"ok"}`**; стартовые
логи — **0 ERROR/Traceback**; README **5105**, `APP_VERSION` **2.53.0** (T-1307 закрыт).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/admin-ui-round109/` (изолированная папка; `tasks.md` создан 12.09.2026 @PM; архивирована 12.09.2026 @PM Step 8).
**Нумерация:** **T-1270…T-1314** (продолжает T-1269 — финал 10.8).
**Преемник:** 10.8 `admin-ui-round108` (архив; задеплоен 11.09.2026; commit `31d2ce7`, прод fast-forward, health 200).
Базовая линия: pytest **5076 passed / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
**Состав:** один трек — TMA UI/UX-полировка (`web/*`, README/docs). Инварианты: без новых PG-DDL, без изменений `bot.py`/`media/`/`.env`; каталог-инвариант **392/91/364** меняется только осознанно (п.7.2 «Название модели»).
**[OUT OF SCOPE] Пункт 2 — вне проекта:** инфраструктурный инструмент локального IDE владельца (OpenCode), **не часть бота**; в коде/конфиге/тестах проекта ссылок нет. Серверный infra-deliverable и `opencode.jsonc` — вне репозитория. Пункт 2 исходного ТЗ в раунд **не входит**.
**Запрос владельца (пункты 1, 3–8; дословно в `tasks.md` §1):** (1) PERMsoc — разделить «Персоны (ID): Славик и Оля», сгруппировать параметры по владельцу в collapsible-блоки с ровно ОДНИМ рабочим тумблером (без дублей); (3) сохранение параметра не сбрасывает скролл наверх; (4) переписать ВСЕ описания групп/параметров (просто, без жаргона, ирония); (5) «Тяжёлые фичи» — проверить дубль per-module тумблеров, при дубле удалить; (6) «Бюджет фона» показывает нули — починить/проверить дубль со «Сводкой», возможно перенести туда; (7) dashboard — один блок «Доступность ключей» с группами по функциям (Основные/Транскрибация/Саммаризация видео/Эмбеддинги), убрать хардкод имён, реальный Health (502/503/Timeout, не cached 200) + «Название модели» первым полем формы и ограничение ширины формы; (8) ускорить фоновый градиент. **Плюс:** README (ирония), русский коммит, push, деплой, plain-language отчёт.
**Рекогносцировка (@PM, HEAD `51f308b`):** см. `tasks.md` §2 (file:line). Опорные точки: PERMsoc `services/param_catalog.py:300,1104,1156,1668-1680` + `services/permsoc.py:51-72` + `web/index.html:812-854`; скролл `web/app.js:2658-2717,2457-2504,2234-2238`; описания `param_catalog.py:73-140`; «Тяжёлые фичи» `web/index.html:1213-1250` + `services/feature_gates.py:26`; бюджет `web/index.html:1176-1211,1520-1572` + `web/api/gates.py:148`; dashboard `web/index.html:2546-2564` + `services/status_service.py:139-224,386-412`; форма провайдеров `web/index.html:762-804` + `web/app.js:364-430`; градиент `web/index.html:37-39,88-121`.
**Учёт аудита @Scanner:** прочитан `plans/reports/round10.8_scanner_audit.md` (0 blocker/0 major; minor R10.8-1 Esc / R10.8-5 `APP_VERSION`+cache-bust; info R10.8-2/-3/-4). Включено: R10.8-5 → T-1307 (поднять `APP_VERSION` до 2.53.0); R10.7-1/-2 → T-1298 (health); R10.6-1 → T-1304 (дубль generic-рендера). Вне скоупа — follow-up.
**Открытые вопросы (5 шт.)** — `tasks.md` §7 (хранение custom-name, эмбеддинг-фоллбэки, реальный health-тест, общий блок персон, решение по удалению/переносу). **@PM не пишет код.**

## Раунд 10.8 (11.09.2026): UI-доработки после 10.7 — переименование разделов, emoji→иконки, Android-логи, доступы окнами, GLOBAL-бейдж + README — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (11.09.2026; архив @PM 11.09.2026)

**✅ ИТОГ 10.8 (11.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/admin-ui-round108/` → **`plans/archive/admin-ui-round108/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5076 passed / 0 failed** (база 10.7 = 5042 → **+34**);
каталог-инвариант **REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89 — без изменений).
@Reviewer — **APPROVED WITH MINOR ISSUES** (doc-nit исправлен); @Scanner — **0 blocker / 0 major**
(2 minor R10.8-1 Esc / R10.8-5 `APP_VERSION`+cache-bust субсета — закрыты точечно до Merge;
3 info R10.8-2/-3/-4 — известный техдолг) (`plans/reports/round10.8_scanner_audit.md`);
@Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§29** + связанные §1/§9/§25).
Артефакты в архиве: `spec.md`, `ADR-001-access-windows-modal.md`,
`ADR-002-icon-subset-parity.md`, `tasks.md` (со статус-хедером).
**Открыто (live-верификация на реальном Android):** **T-1254** (логи — ширина/дата/текст/нет
невидимого поля) и **T-1258** (три отдельных окна «Доступов») — за владельцем/QA; статически
покрыто (`tests/test_webapp_round108_ui.py`, JS-юнит). Пост-архивная фаза @DevOps
(commit/push/deploy/live-smoke, T-1265…T-1267) — после архивации.
**✅ README-счётчик тестов актуализирован @DevOps: 5073 → 5076** (шапка + changelog;
`APP_VERSION` 2.52.0 совпадает с шапкой README).
**✅ ДЕПЛОЙ-ВЕРИФИКАЦИЯ 10.8 (@DevOps, 11.09.2026):** commit `31d2ce7`, push
`636a75d..31d2ce7`; прод `git pull --ff-only` `7f3b790..31d2ce7` (fast-forward, без конфликтов,
`.env` не менялся — UI-only); `systemctl restart admin_bot` → **active (running)**;
`/api/health` → **200 `{"status":"ok"}`**; шрифт `/static/fonts/material-symbols-rounded.woff2?v=2.52.0`
→ **200 `font/woff2`, 18388 B, `wOF2`**; **0 ERROR/Traceback**. Полный pytest локально — **5076 passed / 0 failed**.
Детали — `plans/archive/admin-ui-round108/tasks.md` §9. **Открыто (live, за владельцем/QA):
T-1254** (логи на реальном Android) и **T-1258** (три окна «Доступов» на живом телефоне).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/admin-ui-round108/` (изолированная папка; `tasks.md` создан 11.09.2026 @PM; архивирована 11.09.2026 @PM Step 8).
**Нумерация:** **T-1243…T-1269** (продолжает T-1242 — финал 10.7).
**Преемник:** 10.7 `admin-ui-bugfixes-round107` (архив; задеплоен 11.09.2026; commit `7f3b790`, прод fast-forward, health 200).
Базовая линия: pytest **5042 passed / 0 failed**, `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
**Ключевой момент:** UI-only (TMA `web/*` + README/docs), без новых PG-DDL, без изменений `bot.py`/`media/`/`.env`; feature-flag не требуется (rollback = `git revert`).

**Запрос владельца (UI, дословно):**
1. **Переименовать разделы:** «Доступы и роли» → **«Доступы»**; «Функции PERMsoc» → **«PERMsoc»**;
   «Настройки AI» → **«ИИ»**; «Как это работает» → **«Справка»**; «Oversight» → **«Сводка»**.
2. **Заменить оставшиеся EMOJI** в блоках/подсекциях внутри разделов на иконки.
3. **Починить регрессию LOGS на Android:** ширина таблицы сломана; **дата исчезла**; колонка текста
   ошибки — в один символ; **невидимое selection-поле всё ещё в первой колонке** (10.7 не долечил).
   Должно работать на Android.
4. **Доступы:** «Матрица ролей», «Локальные админы», «Администраторы» — **каждый в ОТДЕЛЬНОМ окне**
   (не все на одном экране). Переименовать «Администраторы» → **«Роли»**. «Мой доступ» и
   «Telegram ID админа» — **без изменений**.
5. **Убрать внешний GLOBAL-бейдж** справа от селектора чата (дубль бейджа внутри селектора).
**Плюс:** README restructure (ироничный тон сохранить): самый-важный-для-пользователя раздел,
гайд «управление+деплой», changelog под сворачиваемым `<details>`. Русский коммит, push, деплой,
plain-language отчёт.

**Рекогносцировка (@PM, HEAD `7f3b790`, дерево чистое):** см. `plans/features/admin-ui-round108/tasks.md` §2
(file:line). Опорные точки: NAV_ITEMS/TABS/HUBS подписи `web/app.js:156,171,186,189,246-255,261-303`;
emoji `web/app.js:43,184,189` + `web/index.html:809,975,1173,1209,1220,1380,1416,1420,1452,1489,1802,1828,1840,1853,1935,1949,2146,2166,2198,2258,2279,2434,2438,2442,2450,2478,2498,2509,2548,2699,2930`;
иконки/субсет `web/app.js:207-228,2164-2170` + `scripts/build_font_subset.py:46-53` + `web/static/fonts/material-symbols-rounded.woff2`;
логи `web/index.html:2545-2589` + CSS `:400-463` + `web/app.js:3285-3291` (root-cause «дата исчезла» —
`fmtLogTime` отдаёт только `HH:MM:SS`, полная дата лишь в недоступном на тач `:title`; «невидимое поле» —
скорее всего `<button class="log-toggle">▸</button>` `index.html:2574-2577`, глиф отсутствует в Android-шрифте);
доступы `web/index.html:1577-1782` + `web/app.js:288-302,603,1851-1857,1884-1890,2062-2069`;
внешний GLOBAL-бейдж `web/index.html:672-674` (внутренний — `:638-641`, `#id` — `:669-671`).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.7_scanner_audit.md` (0 blocker/0 major; minor R10.7-1;
info R10.7-2…R10.7-5). Включено: **R10.7-4** (font-test gap → T-1249, критично для emoji→иконок).
Вне UI-скоупа/опционально: R10.7-1/-2 (`services/status_service.py` gap-fill), R10.7-3 (`copiedTimer`), R10.6-1
(дубль generic-рендера `llm_providers`) → T-1250 (P2, не раздувать риск); R10.6-2/-3 — отдельный раунд.
**@PM не пишет код.** **Архив:** `plans/archive/admin-ui-round108/` (spec.md, ADR-001, ADR-002, tasks.md со статус-хедером).

## Раунд 10.7 (11.09.2026): UI/UX bugfix после 10.6 — шапка/навигация, статистика, логи — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (11.09.2026; архив @PM 11.09.2026)

**✅ ИТОГ 10.7 (11.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/admin-ui-bugfixes-round107/` → **`plans/archive/admin-ui-bugfixes-round107/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5042 passed / 0 failed**; каталог-инвариант
**REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89). @Reviewer — **APPROVED WITH MINOR ISSUES**
(doc-nit исправлен); @Scanner — **0 blocker / 0 major** (1 minor R10.7-1 — задокументированный
spec-trade-off; info R10.7-2…R10.7-4; R10.7-5 — точность формулировки, не код)
(`plans/reports/round10.7_scanner_audit.md`); @Architect — архитектура влита в
`plans/ARCHITECTURE.md` (**§28** + связанные §9/§25). Артефакты в архиве: `spec.md`, `tasks.md`
(со статус-хедером). Пост-архивная фаза @DevOps (commit/push/деплой/live-smoke 1b/1c/1d/2a/3b) —
выполняется после архивации. Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/admin-ui-bugfixes-round107/` (изолированная папка; `tasks.md` создан 11.09.2026).
**Нумерация:** **T-1224…T-1242** (продолжает T-1223 — Scanner-миноры 10.6).
**Преемник:** 10.6 `tma-ia-modules-rework` (архив, задеплоен 11.09.2026; commit `6f91e8b`).
Базовая линия: pytest **5027 passed / 0 failed**, `node --check` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`.
Финал: pytest **5042 passed / 0 failed** (Δ +19).

**Запрос владельца (bugfix/UI, дословно):**
1. **Header (top panel) & navigation:** (a) render-баг — select показывает `function () { [native code] }`
   (исправить Vue-привязку/потерю контекста); (b) safe area — правые элементы перекрыты нативными
   кнопками Telegram (добавить padding-right); (c) компактный user block (avatar + name + role badge +
   fullscreen) — уменьшить размеры/отступы, элементы НЕ удалять; (d) подписи меню под иконками
   переносятся неправильно («Настрой ки AI», «Как это работае т») — уменьшить кегль (text-xs или меньше)
   и отступы, чтобы влезали в одну строку.
2. **Statistics:** (a) таблица ключей — длинные имена моделей (`whisper-large-v3`) ломают ширину
   (ellipsis/word-break); (b) график — плоская линия (починить отрисовку исторических данных).
3. **Logs:** (a) фильтры — найти/убрать невидимый div/input слева от select «INFO», ломающий grid;
   (b) колонки — фиксированная ширина для уровня (ERROR/INFO) и даты, последняя текстовая колонка `flex:1`
   с корректным переносом; (c) UX — копирование строки лога по клику с визуальным откликом.
**Плюс:** README (ироничный тон), русский коммит, push, деплой, plain-language отчёт.

**Рекогносцировка (@PM, HEAD `2ccf558`, дерево чистое):** см. `plans/features/admin-ui-bugfixes-round107/tasks.md` §3
(file:line). Опорные точки: шапка `web/index.html:558-655`; scope-select `:576-618`; user block `:627-642`;
nav-labels `:205-216`, `:646-654`; таблица ключей `:2459-2495` + CSS `.avail-list` `:344-354`;
графики `web/app.js:3130-3166`, `:3195-3251` + `services/status_service.py:260-281`,`:320-336`
и `services/uptime_heartbeat.py:26` (пишется только `'up'` → плоская линия); фильтры/таблица логов
`web/index.html:2497-2537`; copy/context-loss `web/app.js:3300-3330` (подтверждён `map(this.logText)` без `bind`).

**Учёт аудита @Scanner:** прочитан `plans/reports/round10.6_scanner_audit.md` (новейший; 0 blocker/0 major).
В UI-скоуп 10.7 включён **R10.6-1** (дублирующиеся редакторы LLM-провайдеров — 21 дубль) как опциональная
P2-задача **T-1234**; **R10.6-2** (SSRF `https`) и **R10.6-3** (422-эхо `api_key`, R17) — вне UI-скоупа,
кандидаты 10.8; **R10.6-5** (мёртвые `ICONS`) — низкий приоритет. Ремедиации 10.5 (R10.5-1/-2) закрыты.

**Статус (исторический):** ✅ завершён и заархивирован 11.09.2026 (@PM Step 8) — см. сводку выше.
**@PM не пишет код.**
**Архив:** `plans/archive/admin-ui-bugfixes-round107/` (spec.md, tasks.md).

**✅ ДЕПЛОЙ 10.7 (11.09.2026, @DevOps):** commit `7f3b790`, push `2ccf558..7f3b790`
(`origin/master`); прод `git pull --ff-only` `4055434..7f3b790` (fast-forward), `.env` не менялся
(UI/docs-only); `systemctl restart admin_bot` → **active (running)**, Main PID `1086594`;
`/api/health` → **HTTP 200 `{"status":"ok"}`**; логи старта чистые (**0 ERROR/Traceback**;
единственный WARNING — известный BetterStack 401). Live-smoke TMA UI (1a-1d/2a-2b/3a-3c) —
не автоматизирован, остаётся ручной проверкой владельца. Детали — `tasks.md` §9 архива.

## Раунд 10.6 (11.09.2026): TMA IA/Modules rework — 7 UX/IA-дефектов владельца после 10.5 — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (GO 11.09.2026; архив @PM 11.09.2026)

**✅ ИТОГ 10.6 (11.09.2026):** реализация завершена, фича **заархивирована** — перенесена
`plans/features/tma-ia-modules-rework/` → **`plans/archive/tma-ia-modules-rework/`** (@PM Step 8).
**Финальные метрики:** полный **pytest — 5027 passed / 0 failed**; каталог-инвариант
**REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89; Δ GROUPS 74→91 = +17).
@Reviewer — **APPROVED WITH MINOR ISSUES** (все минорные закрыты до Merge: T-1213…T-1221);
@Scanner — **0 blocker / 0 major** (`plans/reports/round10.6_scanner_audit.md`, worthwhile-миноры
закрыты: T-1222/T-1223); @Architect — архитектура влита в `plans/ARCHITECTURE.md` (§27 +
§2/§6/§9/§25). Артефакты в архиве: `design-project.md`, `spec.md`, `tasks.md` (со статус-хедером).
**✅ Пост-архивная фаза @DevOps завершена (11.09.2026):** commit **`6f91e8b`** + push
**`be7b85b..6f91e8b`** в `origin/master`; прод `git pull` fast-forward **`c01ed72..6f91e8b`**
(`.env`-изменений не требуется — `.env.example` не менялся, 5 master-флагов сидятся в PG
`ON CONFLICT DO NOTHING`), `sudo systemctl restart admin_bot` → **active (running)** (PID 1020830),
`/api/health` = **200**, логи старта чистые (0 трейсбеков; BetterStack 401 — pre-existing).
Ниже — исторический документ планирования эпика.

**Фича:** `plans/archive/tma-ia-modules-rework/` (изолированная папка; `tasks.md` создан 11.09.2026).
**Нумерация:** **T-1155…T-1212** (T-1155…T-1199 — исходный план; T-1200…T-1212 — по закреплённым ответам владельца 11.09.2026; продолжает T-1154 секции H раунда 10.5).
**Преемник:** 10.5 `tma-relume-redesign` (архив, задеплоен 10.09.2026) — владелец принял редизайн,
но зафиксировал **мажорные UX/IA-дефекты** как follow-up.

**Обратная связь владельца (дословно, 7 пунктов):**
1. **TWO nav panels is wrong** — убрать SIDEBAR полностью; навигация ТОЛЬКО через TOP navbar;
   у иконок навбара добавить маленькие подписи ПОД иконками (мелкий шрифт, mobile+desktop).
2. **Desktop FULLSCREEN не скроллится** — исправить.
3. Секции хаотичны, эталонная структура не соблюдена; **«Кастомные модули» НЕ реализовывать
   (AI-галлюцинация)**. **REQUIRED IA:**
   - **«Модули»** = РОВНО 11 модулей, у каждого **on/off toggle** + кнопка **окна со ВСЕМИ
     параметрами/лимитами**: 1 Саммаризация, 2 Прямые ответы, 3 Фактчек, 4 Поиск,
     5 Транскрипт голосовых и видео, 6 Выжимка видео, 7 Скачивание медиа, 8 Веб-страницы,
     9 Диагностика, 10 Сон, 11 Ностальгия.
   - **«Настройки AI»**: убрать **«Лимиты»** (лимиты уходят в Модули). Содержит: LLM Провайдеры,
     Промпты, **Память (all memory+RAG)**, **Умный кэш**, Имена, Участники и отношения, Лор чата.
   - **«LLM Провайдеры»**: все модели/провайдеры/`base_url`; сверху — модель прямых ответов
     (main → fallback); **ОДИН визуальный блок = base_url + model + api key**; кнопка
     **«test connection»**.
   - **«Функции PERMsoc»**: убрать миселённые параметры (Кулдаун скачивания, длительность видео
     для расшифровки, длительность войса, размер видео для расшифровки, символов транскрипта для
     выжимки, Потолок загрузки Groq, Потолок загрузки OpenRouter, Потолок публикации видео,
     TTL опубликованного видео, Таймаут STT видео) → redistribute в правильные Модули.
     **PERMsoc = только захардкоженные простые per-chat функции.**
   - **Персонажи:** **«Леха» и «Костик» — РАЗДЕЛЬНЫЕ items**, не одна секция.

**Инвентаризация @PM (для @Architect):** 10 миселённых ключей **все** лежат в группе
`limits_media`; группа **смешанная** — кроме них там настоящие PERMsoc-параметры
(`GIF_INTERVAL`, `SLAVIC_PHOTO_INTERVAL`, `COMMON_COOLDOWN`, `DANGER_COOLDOWN`,
`SELFDEV_COOLDOWN`, `WORK_COOLDOWN`, `OLYA_COOLDOWN`) ⟹ redistribution требует **расщепления
`limits_media`** (изменение каталога GROUPS). Полная карта «11 модулей → группы/ключи» и
«Настройки AI → 7 подразделов» — в `tasks.md` §2. База 10.5: REGISTRY 387 / GROUPS 74 /
Settings 359. **ЦЕЛЬ 10.6 (закреплено владельцем): REGISTRY 392 / GROUPS 91 / Settings 364
(Δ GROUPS 74→91 = +17).**

**Свежие аудиты @Scanner:** `plans/reports/round10.5_scanner_audit.md` — 0 blocker / 0 major,
2 minor (R10.5-1 BackButton re-init; R10.5-2 DM `models.*` 422). Обе учтены в планах
(T-1160a, раздел LLM Провайдеры). `audit_backlog.md` — поверхность 10.5 просканирована.

**🟢 ГЕЙТ ОТКРЫТ (11.09.2026):** владелец **утвердил** дизайн/IA (`spec.md`/`design-project`) и
дал явное **«proceed»** — HARD GATE T-1156 **ПРОЙДЕН**; реализация `@Builder` **РАЗБЛОКИРОВАНА**.
**Закреплённые ответы владельца (locked) — `tasks.md` §8:**
- **A1/D1 = ДА:** тумблеры модулей реально работают; **Фактчек, Поиск, Выжимка видео,
  Веб-страницы, Диагностика — default ON**; +5 master-флагов ⟹ **REGISTRY 392 / GROUPS 91 /
  Settings 364** (Δ GROUPS 74→91 = +17).
- **A2/D2 = раздельно:** модули — в «Модули»; редакторы промптов/моделей/ключей — в «Настройки AI».
- **A3/D3 = RAG → «Память»:** RAG-доли бюджета и все RAG-ключи уходят в подраздел «Память»
  (расщепление `limits_chat_budgets`).
- **A4/D4 = per-block test:** LLM Провайдеры — визуальные блоки ПО МОДУЛЯМ (base_url+model+api key);
  main → fallback; у каждого блока кнопка test (ошибка key/model или 200).
- **A5/D5:** сервер и логи остаются на «Статус» (просмотр).
- **A6/A7:** emoji → иконка в «Как это работает» и в матрице ролей.
- **A8:** proxy+cookies → из «Провайдеров» в «Модули»; настройки логов/BetterStack/checkup →
  подраздел «Диагностика».
- **A9:** «Доступы и роли» — эксклюзивный аккордеон (открыт ровно один подраздел).
Новые задачи раунда: **T-1200…T-1212** (`tasks.md` §8.4). **Открытых вопросов НЕТ.**

**Свежие аудиты @Scanner (перепроверено 11.09.2026):** `plans/reports/round10.5_scanner_audit.md` —
0 blocker / 0 major, 2 minor (R10.5-1 BackButton re-init; R10.5-2 DM `models.*` 422); новых
отчётов после него нет. Обе ремедиации учтены (T-1160a; DM read-only в LLM Провайдерах).

## Раунд 10.5 (10.09.2026): Редизайн TMA по референсу Relume + гигиена репозитория — ✅ ЗАВЕРШЁН И ЗААРХИВИРОВАН (GO 10.09.2026; архив @PM 10.09.2026)

ТЗ владельца (10.09.2026): (1) добавить `relumesite_example/` в `.gitignore` (сторонний
Relume-экспорт сайта-мокапа, не код проекта; **`media/` НЕ трогать** — политика project.md);
(2) изучить референс (структура разделов, размещение параметров, палитра/стиль);
(3) подтвердить понимание и готовность полностью переделать админ-миниапп.
**REFERENCE:** `relumesite_example/` — 15 статических страниц (`index.htm` + Relume-рантайм
`index.8433654a.js`, стили `index.238f2711.css`), язык RU, реальные описания фич бота.
Заголовки: «Статус сервера и бота» `/`, «Настройки AI» `/ai/`, «Промпты» `/ai/page-13/`,
«Лимиты» `/ai/page-14/`, «Память» `/ai/page-15/`, «Сон и Ностальгия» `/ai/page-16/`,
«LLM Провайдеры» `/ai/llm/`, «Функции PERMsoc» `/permsoc/`, «Модули» `/page-1/`,
«Кастомные модули» `/page-1/page-2/`, «Как это работает» `/page/`, «Доступы и Роли»
`/page-20/`, «Матрица ролей» `/page-20/page-21/`, «Локальные админы чата» `/page-20/page-22/`,
«Управление администраторами» `/page-23/`. **Планирование 10.09.2026 @PM: 1 фича
`tma-relume-redesign` (архив: `plans/archive/`), нумерация T-1066…T-1148** (продолжает T-1065;
**позже расширена до T-1143** ответами OD11–OD15 — см. ниже).
**10.09.2026 (вечер) — решения владельца зафиксированы: OD1=B (полный ребейлд IA по
референсу), OD2=всё сразу (big-bang), OD3=та же технология (Vue3 global / zero-build),
OD4=база палитры референса + анимированные переливы (reduced-motion + WCAG AA над
градиентом), OD5=Material icons (emoji — временный fallback), OD6=структура референса —
эталон.** Уточнение: при OD1+OD3 многостраничная навигация реализуется **hash-routing
внутри одного `index.html` ⟹ hash-routing ОБЯЗАТЕЛЕН** (подтверждено @Memory).
Следующий deliverable — **архитектурно-дизайн проект** (нумерация T-1090…T-1126,
продолжает T-1089); **реализация — только ПОСЛЕ апрува проекта владельцем** (hard-gate).

**10.09.2026 (поздний вечер) — РЕШЕНИЯ ВЛАДЕЛЬЦА OD7–OD10 (SUPERSEDE прежние рек. по D6/D7):**
- **OD7 (было D6) — RESOLVED + РАСШИРЕНО.** «Чат-Профиль» = **САМЫЙ ВАЖНЫЙ элемент** —
  **глобальный переключатель контекста/скоупа** (**GLOBAL ↔ конкретный ЧАТ ↔ ЛС/DM**), который
  **управляет маршрутизацией всех настроек**. Промитентный аккуратный **drop-down селектор чата**;
  список чатов бота, **отфильтрованный по чатам текущего админа** (**RBAC**: случайный пользователь
  **НЕ** меняет параметры там, где запрещено); после выбора — **крупно ИМЯ и АВАТАР** чата.
  **НЕ сворачивается в AI-hub.** Это **хребет роутинга** мини-аппа.
- **OD8 (было D7/B1) — В СКОУПЕ, ПЕРЕРАБОТАНО.** Компактный список **всех API-ключей**:
  имя по модулю + **динамически подтянутые текущий провайдер/модель** (сейчас **хардкод** —
  исправить) + **код ответа сервера** + индикатор доступности; **мелкий шрифт/плотный line-height**;
  затем **график доступности всех ключей по времени** + небольшая **легенда**. Починить раздутый блок.
- **OD9 (было D7/B2) — ИЗ СКОУПА.** CRUD «Кастомных модулей» **не реализовывать** (read-only остаётся).
- **OD10 (было D7/B3) — В СКОУПЕ, РАСШИРЕНО.** Матрица: **все** параметры мини-аппа, сгруппированные
  **по тем же секциям**; по каждому — роли на **чтение/запись**; плюс **управление ролями**, включая
  **создание новых ролей**.
- **Deep-link — остаётся OPEN (D9).** Владелец хочет **сначала объяснение** (@Architect документирует
  простыми словами). **D11 (шрифт):** владелец **сам предоставит** Material Symbols ⟹ нужна
  **спека формата поставки** от @Architect.
Новые задачи: **E3-спеки T-1121…T-1126 (@Architect, 0 кода)**, **реализация T-1127…T-1133 (@Builder,
после GATE)**, **QA T-1134…T-1135**. Нумерация на тот момент — **T-1066…T-1135** (позже расширена
до **T-1143** — см. следующий блок OD11–OD15).

**10.09.2026 (новое сообщение владельца) — ОТВЕТЫ на Q-NEW-1…5, решения OD11–OD15 (финальные):**
- **OD11 (Q-NEW-1) — НЕТ хардкода моделей.** В проекте **не должно быть ни одной захардкоженной
  модели** (Groq/OpenRouter и любые другие) — **исправить**. **КРИТИЧНО:** уже сконфигурированные
  модели/ключи **НЕ должны сломаться** ⟹ **безопасная миграция / сохранение текущих значений**
  (дефолты новых ключей = сегодняшние константы). Следствие: STT-модели становятся конфигурируемыми
  ⟹ **+2 записи каталога (REGISTRY 383→385)** — обоснованное, согласованное исключение.
- **OD12 (Q-NEW-2) — история доступности ключей ПЕРСИСТИТСЯ между сессиями** (переживает рестарт).
  Приоритет — соблюсти «**ноль новых PG-DDL / SQLite v8**»; если невозможно — **явно оговорить
  обоснованное исключение** для владельца (in-memory ring — лишь быстрый слой).
- **OD13 (Q-NEW-3) — deep-link ВЫКЛЮЧЕН (OFF).** **D9 CLOSED**; задачи реализации нет
  (`__TMA_DEEPLINK__`=`false`).
- **OD14 (Q-NEW-4) — шрифт предоставлен:** полный `MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2`
  в **корне проекта** (~5.1 МиБ; сабсет не найден) ⟹ обязательна **ИНСПЕКЦИЯ и вердикт
  (пригоден/непригоден) ДО реализации**. **D11 CLOSED-в-инспекцию.**
- **OD15 (Q-NEW-5) — переименование/удаление ролей РАЗРЕШЕНЫ, КРОМЕ superuser** (абсолютная
  защита). **D12 RESOLVED.**
Новые задачи: **E4-анализ T-1136…T-1138 (@Architect/@Scanner, 0 кода, ДО GATE)**,
**реализация T-1139…T-1142 (@Builder, после GATE)**, **QA T-1143**. `design-project.md` отревизован
до **v4** (T-1138).

**10.09.2026 (ответы владельца на Q1–Q4 `design-project.md` §16.5) — решения OD16–OD19 (финальные):**
- **OD16 (Q1) — адреса провайдеров ОБЯЗАТЕЛЬНЫ в мини-аппе.** **ВСЕ** необходимые параметры
  (провайдер, модель, `base_url`) должны быть **редактируемы из UI**; владелец обязан уметь
  **переключать провайдера И модель** из мини-аппа. Отменяет «base-url hot-only без UI-строки».
  Следствие: **+2 записи каталога** ⟹ счётчики **REGISTRY 387 / GROUPS 74 / Settings 359**
  (383 → +2 STT (OD11) → 385 → +2 адреса (OD16) → 387) — согласованное исключение.
- **OD17 (Q2) — `fonttools`+`brotli` ОДОБРЕНЫ** как **build-time** зависимость (в runtime не
  попадают).
- **OD18 (Q3) — тяжёлый исходник шрифта (5.11 МиБ в корне) → `.gitignore`**; в git только
  **субсет ~13 КБ** + **`LICENSE`** Apache-2.0.
- **OD19 (Q4) — файл `var/status_key_history.json` ОДОБРЕН**, но с **обязательной проверкой
  на утечки**: без сырых API-ключей/секретов, **R17-safe**, права файла, gitignored.
Новые задачи: **E5-ревизия T-1144 (@Architect, 0 кода, ДО GATE → проект v5)** — ✅ **выполнена
10.09.2026**, **реализация T-1145…T-1148 (@Builder, после GATE)**. Итоговая нумерация — **T-1066…T-1148**.
`design-project.md` — **v5 готов** (T-1144) и **ждёт только общего GO** владельца; открытых
вопросов/выборов не осталось.

| # | Задача ТЗ | Фича | Задачи | Ключевые AC / канон |
|---|-----------|------|--------|---------------------|
| 1 | `.gitignore += relumesite_example/` (`media/` НЕ трогать) | `tma-relume-redesign` | T-1066 | ✅ Выполнено 10.09.2026 — раздел «Сторонний референс-сайт Relume», `git check-ignore` подтверждает; `media/` по-прежнему не игнорируется |
| 2 | Глубокий анализ референса (структура/секции/параметры) | `tma-relume-redesign` | T-1067…T-1071 | Инвентаризация 15 страниц; иерархия navbar/sidebar; разбор секций/карточек/таблиц/графиков; дизайн-токены CSS (Inter, scheme-4, акцент `#14CBB6`); компонентные паттерны |
| 3 | Маппинг «раздел референса → вкладка/группа параметров mini-app» | `tma-relume-redesign` | T-1072…T-1075 | Таблица соответствия `param_catalog.TAB_RULES`/TABS-зеркалу; gap-анализ (есть/нет); инвентаризация API-эндпоинтов; отчёт `reference-mapping.md` |
| 4 | Решение: full-rebuild vs reskin | `tma-relume-redesign` | T-1076…T-1077 | ✅ **РЕШЕНО (OD1)**: вариант **B — полный ребейлд** IA по референсу; **всё сразу** (OD2); **та же технология** Vue3 global/zero-build (OD3); палитра-база референса + анимированные градиенты (OD4); Material icons/emoji-fallback (OD5); структура референса — эталон (OD6). **Поздний вечер, OD7–OD10:** Chat-Profile = **промитентный scope-switcher** (GLOBAL/ЧАТ/ЛС, RBAC-фильтр чатов, имя+аватар) — **хребет роутинга**; **B1 в скоуп** (key-availability переработка), **B2 OUT**, **B3 в скоуп** (матрица всех параметров по секциям read/write + создание ролей) |
| 5 | Архитектурно-дизайн проект (**deliverable**) | `tma-relume-redesign` | T-1090…T-1097 (+ **E3-спеки T-1121…T-1126**) | Parity-map без потери фич; градиент-токены; спека Material Symbols (+ **спека поставки шрифта** T-1121); hash-routing; композиция 15 экранов; предложения add/remove/optimize (Exa); test-plan; **спеки OD7–OD10** (scope-switcher T-1123, key-availability T-1124, матрица/роли T-1125; deep-link doc T-1122); финал `design-project.md` v3 (**T-1126**) → **GATE владельца** |
| 5a | **Доуточнения по OD11–OD15 (Q-NEW-1…5)** | `tma-relume-redesign` | **E4: T-1136…T-1138** (pre-gate, @Architect/@Scanner, 0 кода) | **T-1136** — исчерпывающий аудит ВСЕХ хардкодов моделей/ключей/base_url + план safe migration (сохранить текущие значения); **T-1137** — инспекция полного `MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2` из корня → вердикт пригоден/непригоден **до реализации**; **T-1138** — ревизия `design-project.md` → **v4** (OD11–OD15, D9/D11/D12 CLOSED). **✅ Выполнено (0 кода).** |
| 5b | **Доуточнения по OD16–OD19 (Q1–Q4, §16.5)** | `tma-relume-redesign` | **E5: T-1144** (pre-gate, @Architect, 0 кода) | Ревизия `design-project.md` → **v5**: **(OD16)** адреса провайдеров **UI-редактируемы** + переключение провайдера/модели ⟹ каталог **+2** ⟹ **387/74/359**; **(OD17)** `fonttools`+`brotli` build-only; **(OD18)** 5.11 МиБ источник → `.gitignore` (в git субсет+LICENSE); **(OD19)** `var/status_key_history.json` апрув + **leak-safety**. **Разрешено до GATE (анализ).** |
| 6 | Полная переделка (big-bang) + QA | `tma-relume-redesign` | T-1098…T-1118 + **F4 T-1127…T-1133** + **F5 T-1139…T-1142** + **F6 T-1145…T-1148** + **QA T-1134…T-1135, T-1143** | Порядок: токены → shell/navbar → hub → 15 экранов → **scope-switcher → key-availability → role matrix** → **хардкод+миграция → персистентная история → role rename/delete** → **UI-редактируемость провайдера/модели/адресов → fonttools-сборка → .gitignore шрифта → leak-safety key-history** → QA; `node --check`, `TABS`↔`TAB_RULES`, каталог **387/74/359**, маркеры `test_webapp_*`/`test_frontend_tab_mapping`, pytest baseline **4860**, live Telegram. **✅ ВЫПОЛНЕНО и заархивировано 10.09.2026 (@PM Step 8; 4962 passed / 0 failed; см. `plans/archive/tma-relume-redesign/tasks.md` секция H/DoD)** |

**РЕШЕНИЕ (10.09.2026, владелец): выбран вариант B — ПОЛНЫЙ РЕБЕЙЛД** (OD1): берём
навигационную модель референса и полностью перестраиваем IA (navbar + hub-карточки +
отдельные экраны), **всё сразу** (OD2), на **той же технологии** Vue3 global/zero-build
(OD3). Варианты A (reskin) и C (hybrid) — отклонены. Палитра: **база = цвета референса +
анимированные переливы** (OD4) с `prefers-reduced-motion`-фолбэком и **WCAG AA над
движущимся градиентом**; иконки — **Material Symbols** (emoji как временный fallback, OD5);
структура — **полностью как в референсе** (15 страниц, OD6). **Hash-routing внутри одного
`index.html` обязателен** (следствие OD1+OD3; подтверждено @Memory); **D8** — нативный
back через `BackButton` (deep-link — отдельный тумблер, D9). **Поздний вечер (OD7–OD10):**
Чат-Профиль = **промитентный scope-switcher** (GLOBAL/ЧАТ/ЛС) — **хребет роутинга**;
**B1 — в скоуп**, **B2 — OUT**, **B3 — в скоуп** (матрица + создание ролей). **Новое сообщение
владельца (OD11–OD15):** ноль хардкода моделей + safe migration (OD11); персистентная история
доступности ключей (OD12); **deep-link OFF** (OD13); шрифт предоставлен → инспекция (OD14);
rename/delete ролей, кроме superuser (OD15). **Новое сообщение владельца (OD16–OD19, Q1–Q4):**
адреса провайдеров **обязательны в UI** + переключение провайдера/модели ⟹ каталог **387/74/359**
(OD16); `fonttools`+`brotli` build-only (OD17); 5.11 МиБ источник → `.gitignore` (OD18);
`var/status_key_history.json` апрув + **leak-safety** (OD19). **Порядок:** архитектурно-дизайн
проект (T-1090…T-1097) → **спеки OD7–OD10** (E3, T-1121…T-1126) → **анализ OD11–OD15** (E4,
T-1136…T-1138) → **анализ OD16–OD19** (E5, T-1144) → **ревизия проекта v5 + GATE** апрува
владельцем → **только потом** big-bang реализация @Builder (T-1098…T-1118 + F4 T-1127…T-1133 +
F5 T-1139…T-1142 + F6 T-1145…T-1148 + QA T-1134…T-1135, T-1143). **Все прежние открытые
D9/D11/D12 — ЗАКРЫТЫ** (OD13/OD14/OD15); **D6/D7/D8 — RESOLVED** (OD7–OD10 + research T-1119).

**Конфликт-матрица (проверка @PM 10.09.2026):**

| Активная | Пересечение | Решение / порядок |
|----------|-------------|-------------------|
| **F-4** `frontend-admin-bugfixes` (Баг-4 «сверка синхронизации разделов» — проверяет ВСЕ вкладки) | Редизайн меняет карту вкладок/IA **+ добавляет scope-switcher (OD7) и матрицу ролей (OD10)** | **Редизайн 10.5 ДО Бага-4** (иначе сверка по старой карте); либо Баг-4 закрыть до старта 10.5. Приоритет — на решении владельца |
| **F-6** `user-aliases-admin` (фронт-плоскость «Лимиты/Модули», алиасы/каскад имён) | **ПРЯМОЕ:** **OD7** меняет chat-контекст (scope-switcher) и трогает те же рендер-зоны (`index.html`/`app.js`); алиасы **per-chat** (`build_alias_resolver(chat_id)`); **OD10** (матрица/права) пересекается с доступом к «Лимитам/Модулям» | F-6 сейчас — аудит/верификация без ломки UI; редизайн **учитывает per-chat-семантику алиасов** (R16: ID не имя) и F-6-блоки в IA. Scope-switcher обязан сохранять per-chat-контекст алиасов — сверить после реализации OD7 |
| **F-3** `scam-incident-security-followup` (T-663: админ-гейт DM-веток) | **OD7** вводит **явный DM-скоуп**; **OD10** — права на параметры | DM-гейты (`chat_id>0`) **сохранить**; scope-switcher/матрица **не ослабляют** серверные проверки; перепроверить T-663 при вёрстке DM-скоупа |
| **F-1/F-2/F-5** | фронт/бэкенд не пересекаются напрямую | Независимы; учесть при финальном полном pytest |

**✅ СТАТУС (10.09.2026, ФИНАЛ): ЗАВЕРШЁН И ЗААРХИВИРОВАН.** Реализация big-bang
(T-1098…T-1148; секции F/F4/F5/F6/G) **выполнена**; @Reviewer — **APPROVED WITH MINOR ISSUES**,
минорные замечания закрыты до Merge; @Scanner — **0 blocker / 0 major**
(`plans/reports/round10.5_scanner_audit.md`); @Architect — архитектура влита в
`plans/ARCHITECTURE.md` (§25/§26). **Полный pytest — 4962 passed / 0 failed**; `node --check
web/app.js`, `tests/js/routing_test.js` и `git diff --check` — clean. **Фича перенесена
@PM (Step 8 Archive Phase): `plans/features/tma-relume-redesign/` → `plans/archive/tma-relume-redesign/`**
(сохранены `design-project.md` v5, `spec.md` v3, `tasks.md`, `reference-analysis.md`).
**Исторический статус на момент GO:** 🟢 ВСЕ РЕШЕНИЯ ВЛАДЕЛЬЦА ПОЛУЧЕНЫ (OD1–OD19);
**E5-ревизия выполнена — `design-project.md` = v5**
(T-1144 ✅, 0 кода). **🟢 10.09.2026 владелец дал явный общий GO на v5 — hard-gate ПРОЙДЕН**,
секции F/F4/F5/F6/G открыты (@Builder стартует с T-1098; порядок T-1098 → F1–F3 → F4 → F5 →
F6 → G → H). **Доп. требования владельца при GO:** parity каждого параметра мини-аппа
(все значения применяются и персистятся, ноль функциональных потерь), полный `pytest`
(baseline 4860, 0 регрессий) + smoke-тесты, live-верификация (где возможно), README (ироничный
тон), русский conventional-commit + push, деплой на прод, финальный plain-language отчёт
(done/changes/bugs/blockers). T-1066 выполнен (`.gitignore` обновлён,
`relumesite_example/` игнорируется, `media/` не тронут). Deliverable **T-1090…T-1097
готов** — `plans/archive/tma-relume-redesign/design-project.md` (parity-map без потери
фич, градиент-токены, Material Symbols, hash-routing, композиция 15 экранов, test-plan,
add/remove/optimize, Exa-источники). **Решено владельцем (OD7–OD10):**
- **D6 — ✅ RESOLVED (OD7):** «Чат-Профиль» = **промитентный глобальный scope-switcher**
  (GLOBAL/ЧАТ/ЛС) с **RBAC-фильтром** чатов и показом **имени/аватара**; **НЕ** сворачивается
  в AI-hub. Спека — **T-1123**, реализация — **T-1127**.
- **D7 — ✅ RESOLVED:** **B1 — в скоуп** (переработка key-availability: динамич. провайдер/модель,
  компактные строки, код ответа, график+легенда — **T-1124/T-1128/T-1129/T-1132**);
  **B2 — OUT** (read-only, **T-1108**); **B3 — в скоуп и расширен** (все параметры по секциям,
  read/write-роли + **создание ролей** — **T-1125/T-1130/T-1131/T-1133**).
- **D8 — ✅ back RESOLVED (T-1119):** через **нативный `BackButton`**, без своей кнопки;
  `__TMA_BACK__`=`true`.
**Решено владельцем (OD11–OD15, ответы на Q-NEW-1…5):**
- **OD11 — ✅ (Q-NEW-1):** ноль захардкоженных моделей во всём проекте; **safe migration
  с сохранением текущих значений**; STT-модели → каталог **383→385** (согласованное исключение;
  итог с OD16 — **387/74/359**). Аудит — **T-1136**, реализация — **T-1139**.
- **OD12 — ✅ (Q-NEW-2):** история доступности ключей **персистится между сессиями**;
  «ноль PG-DDL / SQLite v8» — приоритетно, иначе **явное исключение**. Реализация — **T-1140**.
- **OD13 — ✅ (Q-NEW-3): D9 CLOSED — deep-link OFF** (`__TMA_DEEPLINK__`=`false`); задач
  реализации нет.
- **OD14 — ✅ (Q-NEW-4): D11 CLOSED-в-инспекцию** — полный `MaterialSymbolsRounded[...].woff2`
  в корне проекта; **инспекция + вердикт до реализации** — **T-1137**; ревизия — **T-1138**.
- **OD15 — ✅ (Q-NEW-5): D12 RESOLVED** — rename/delete ролей разрешены, **кроме superuser**;
  backend — **T-1141**, UI — **T-1142**.
**Решено владельцем (OD16–OD19, ответы на Q1–Q4 из §16.5):**
- **OD16 — ✅ (Q1):** адреса провайдеров **ОБЯЗАТЕЛЬНЫ в мини-аппе**; **все** необходимые
  параметры (провайдер, модель, `base_url`) **редактируемы из UI**; переключение **провайдера
  И модели** из мини-аппа ⟹ **+2 записи каталога** ⟹ **REGISTRY 387 / GROUPS 74 / Settings 359**.
  Ревизия — **T-1144**, реализация — **T-1145**.
- **OD17 — ✅ (Q2):** `fonttools`+`brotli` — **build-only** зависимость. Реализация — **T-1146**.
- **OD18 — ✅ (Q3):** 5.11 МиБ источник шрифта → **`.gitignore`**; в git — субсет ~13 КБ + LICENSE.
  Реализация — **T-1147**.
- **OD19 — ✅ (Q4):** `var/status_key_history.json` одобрен при **обязательной leak-safety-проверке**
  (нет сырых ключей, R17-safe, права, gitignored). Реализация/верификация — **T-1148**.
Детали — `plans/archive/tma-relume-redesign/tasks.md` (§0 / §0.2; **E2: T-1119/T-1120**;
**E3: T-1121…T-1126**; **E4: T-1136…T-1138**; **E5: T-1144**; **F6: T-1145…T-1148**).
Scanner-аудит 10.4 (`plans/reports/round10.4_review_fixes.md`, `audit_backlog.md`,
`full_audit_results.md`, `global_map.md`) проверен **четырежды** 10.09.2026 (в т.ч. при OD11–OD15
и OD16–OD19; `plans/reports/` и `reports/scanner-reports/`): 0 blocker/major; **новых отчётов
по 10.5 нет** (самый свежий — `round10.4_review_fixes.md`, 10.09.2026 05:17). MED-017 (базовый
383/74/359) — **два согласованных исключения**: +2 OD11 (STT) и +2 OD16 (адреса) ⟹ **387/74/359**;
LOW-012 (CSP) — self-host субсета шрифта (OD18).
**Реализация (T-1098…T-1118 + F4 T-1127…T-1133 + F5 T-1139…T-1142 + F6 T-1145…T-1148 +
QA T-1134…T-1135, T-1143, H T-1149…T-1154) — 🟢 РАЗБЛОКИРОВАНА (GO владельца 10.09.2026):
«проект v5 утверждён → @Builder стартует с T-1098». Порядок: токены → shell/navbar → hub →
15 экранов → F4 → F5 → F6 → G → H.**
**CI/деплой-контур (при GO, DoD-пункты e/f):** перед коммитом — полный `pytest` (baseline 4860,
0 регрессий) + `node --check web/app.js` + `git diff --check`; **русский conventional-commit**
(`<type>(<scope>): раунд 10.5 — …`, напр. `feat(admin,web,chat,api): раунд 10.5 — …`) + push в
`master`; затем деплой на **198.46.175.136**: `ssh nik@…` → `cd /var/www/admin_bot` → `git pull`
→ при необходимости правка `.env` → `sudo systemctl restart admin_bot` → `sudo systemctl status
admin_bot`; финальный plain-language отчёт (done/changes/bugs/blockers); README — ироничный тон.
Детали — `plans/archive/tma-relume-redesign/tasks.md` (секция **H**, **✅ DoD**,
**📌 Конвенция коммитов**).**

**🟢 ДЕПЛОЙ-ВЕРИФИКАЦИЯ (10.09.2026, @DevOps):** commit **`918f675`**
(`feat(admin,web,chat,api): раунд 10.5 — редизайн TMA по референсу Relume: navbar, hubs,
hash-роутинг, scope-switcher, key-history, матрица ролей, градиенты, Material Symbols
(тесты 4962)`, 49 файлов) → push **`0bdf272..918f675`** в `origin/master`. Сервер
`cd /var/www/admin_bot && git pull` — **fast-forward `0bdf272..918f675`** (HEAD=**918f675**).
`.env`-изменений **не потребовалось** (Settings 359 без изменений; 4 новые записи каталога —
PG-only `_MODELS_PG_ONLY`, сид `ON CONFLICT DO NOTHING` → журнал «starter bot_settings seeded:
342 (ON CONFLICT DO NOTHING)»). `sudo systemctl restart admin_bot` → **active (running)**,
MainPID=917049, NRestarts=0, ActiveEnterTimestamp 10.09 08:21:05 UTC. Live-проверка:
`curl http://127.0.0.1:8000/api/health` = **200**; статика `web/static/fonts/material-symbols-rounded.woff2`
(13 428 B) и `web/static/vendor/dompurify-3.4.15.min.js` на месте; журнал старта — **0 error/traceback**
(единственный WARNING — известный betterstack 401 в `.env`, pre-existing, не связан с 10.5).
**Остаётся ручное:** live Telegram-smoke 15 экранов / scope-switcher GLOBAL-ЧАТ-ЛС / BackButton /
RBAC-матрица на реальном устройстве (T-1153) — автоматизации недоступно.

## Раунд 10 (07.09.2026): Multi-chat scaling (Variant A) — Granular RBAC, BYOK, chat_params-слой, PERMsoc-изоляция, Feature Gates+бюджет воркеров, TMA IA/UI

Эпик по research `plans/docs/multi-chat-scaling-research.md` (ВЫВОД: вариант А — один бот, per-chat изоляция+бюджеты, Epic 86/PG — не сейчас; 07.09.2026, апрув владельца «запланировать 3 части»). **Планирование: 6 фич, `plans/features/` — T-843…T-924** (нумерация продолжает T-842; spec.md при планировании НЕ создавался — A1-задачи зеркалят PM-базу дизайна и Q-протоколы, прецеденты раундов 7/9). **Часть 1 (RBAC/BYOK/параметры)** — `multi-chat-rbac-byok` (T-843…T-869): роли Global/Local/Moderator/User (+Custom, `bot_roles.role_type` ADD COL, сиды-сеты), `param_permissions` (key→view/edit min-role+hidden_from_local; роль-пикер у инпутов TMA для Global), `chat_profiles.chat_params JSONB` ADD COL + резолв chat_params→bot_settings→дефолт (hot_chat, кэш+NOTIFY+409 по profile updated_at, паттерн chat_lore), локальный админ/chat_admins-строки=local_admin, BYOK: `chat_keys` (свой ключ чата, маска last4, нигде raw), без своего ключа — глобальный + жёсткий бюджет `chat_usage`+`limits.chat_global_key_budget_*` (превышение → «нет ключа»-песочница), поля ключей у локального ВИЗУАЛЬНО ПУСТЫ, промпты «as-is»+«Использовать мой». **Часть 2** — `permsoc-module-isolation` (T-878…T-889): плагин `services/permsoc.py` (реестр 5 модулей: Славик/Костя/Алан+greeting/Оля/передразнивания), единый `PermsocGateFilter` (порядок роутеров bot.py НЕ менять), master `flags.permsoc_enabled` + под-тумблеры (olya/mimic — per-chat-фолбэк), дефолт OFF для новых чатов, backfill-скрипт + карточка в «Реакции и Триггеры» (до TMA-IA); `feature-gates-worker-budget` (T-890…T-902): жёсткий Opt-In (my_chat_member: новый профиль `gates_opt_in=false`, тяжёлые фичи Сон/Ностальгия/авто-лор — default OFF, включение ЯВНОЕ глобальным/локальным админом), `worker_budget`-ледежер в PG (суточные global/per-chat лимиты LLM-вызовов/токенов, приоритеты-деградация ностальгия→лор→сон, jitter-тики, расширение концепции memory_dream_log.tokens), API GET/PUT gates + GET budget, REGISTRY `limits.worker_daily_*`. **Часть 3 (UI/UX)** — `tma-ia-progressive-disclosure` (T-903…T-913): меню «Главная/Статус, Чат-Профиль, Модули и Фичи, Настройки AI, Доступы и Роли» (TABS+menu-тег, маппинг без слома), селектор чатов в шапке (чаты по правам, localStorage), progressive-раскрытие: REGISTRY `progressive_level` basic/advanced, натив `<details>`-аккордеон, роль user read-only (только Статус/Как это работает); `global-oversight-dashboard` (T-914…T-924): Global Oversight — сводка всех чатов (активность/Opt-In/тяжёлые фичи/ключ own/global/админы/бюджет, кэш+custom refresh), kill-switch (override-записи в chat_params+история-аудит, undo) и «запрет глобального ключа per chat», API `web/api/oversight.py` (только global admin; 403 иным), таблица+модалка-детали; `tma-ui-fixes` (T-870…T-877): шапка-flexbox, логи в `<pre><code>` (0.75rem/pre-wrap/break-all/компакт-скролл), relations-аватары+имена (Alias→никнейм→юзернейм, прокси /api/avatar), имена чатов вместо id в титулах, чип «авто» вместо «— авто», компактный дропдаун стадий+широкое поле заметки, перенос «Telegram ID админа» из «Реакции и Триггеры» → «Доступы». **Порядок/зависимости:** рбас/параметры (часть 1) → фронт-фиксы и PERMsoc (независимы после 1) → гейты+бюджет (2.3/2.4) → TMA-IA (нуждается в 1/x) → Oversight (всю). **Статус: ✅ Выполнен и заархивирован (08.09.2026 @PM, HEAD fac1b9f, tests 4717), см. `plans/archive/` — 6 фич F-7…F-12 (T-843…T-924)** — 4717 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §22; закрыто по ревью: T-843..T-924. Вне архива (исполняет @DevOps финальным шагом): PG-DDL (bot_roles.role_type, param_permissions, chat_keys, chat_usage, worker_budget, ALT chat_admins/chat_profiles/chat_lore_history-check) + `scripts/backfill_permsoc_gates.py` + `scripts/backfill_feature_gates.py` + live-верификация. Открытые вопросы (Q1–Q9/Q1–Q6 раунда) закрыты @Architect в A1-задачах кода.

**🔄 Фоллоу-апы раунда 10 — «Ре-дизайн 10.2» (09.09.2026, @Architect; по рекону владельца после прод-просмотра — 3 решения, см. BACKLOG):**
1. **BUG-3 «Функции PERMsoc»** — НАСТОЯЩАЯ вкладка `permsoc` (menu `modules`, тип config): master-тумблер per-chat (gates, global admin -> write, локальный — read-only) + карточки 5 модулей (Славик/Костик/Оля/Леха/передразнивания) с ID персон (`reactions.slavik_user_id`/`kostik_user_id`/`olya_user_id`/`alan_user_id`/`alan_username`), kucha (`reactions.kucha_enabled`), под-флагами (`flags.olya_enabled`/`flags.mimic_enabled`); новые группы каталога `flags_permsoc`/`reactions_permsoc`/`reactions_admin` (выделение из reactions_persons/flags_media/reactions_word_reactions/reactions_mimic), перенос групп `reactions_persons`/`limits_persons` на новую вкладку; из «Реакции и Триггеры» и карточки modules_feats эти ключи УБИРАЮТСЯ (вкладка видна даже при master OFF — гейт в runtime, не в UI; пер-парам доступы — флаги из BUG-6). Спека: `plans/archive/permsoc-module-isolation/spec.md` §10.
2. **BUG-5 пустые блоки «(0)»** — правило рендера по группе: basic-сетка только при basicItems>0; `<details class="advanced">` только при advancedItems>0 (никакого «(0)»; если basic==0 — details рендерится раскрытым); вся карточка группы скрыта при 0/0; то же для per-chat override UI (общий generic-рендер). Хелпер-фильтр в `groupedForTab` (app.js), маркер `<details class="advanced"` остаётся в шаблоне. Спека: `plans/archive/tma-ia-progressive-disclosure/spec.md` §10.
3. **BUG-6 флаги-модель прав** — вместо `view_min_role`/`edit_min_role`/`hidden_from_local`: `{view_roles, edit_roles}` (докетная форма: массивы из {user, moderator, local_admin}; global_admin неявный ВСЕГДА; пустые массивы = только суперюзер; запись подразумевает чтение (union на сервере); legacy-строки мигрируют на чтении (rank>=min → массив; hidden_from_local = фолдинг local_admin из view_roles, чекбокс удалён); DEFAULT_MATRIX: keys=[]/[], prompts=[local_admin]×2 (модератор промпты не видит — хард-правило), остальные view=[moderator,local_admin] edit=[local_admin] (юзер по умолчанию видит только Статус/Справку); НОВЫЙ `DELETE /api/access/param_permissions/{key}` — сброс на дефолт (удаление строки); секционный гейтинг (user) не меняется. Спека: `plans/archive/multi-chat-rbac-byok/spec.md` §3.2.

## Раунд 10.3 (09.09.2026): доработки и фиксы — 7 задач ТЗ (фоллоу-апы после 10.2)

Фоллоу-апы по ТЗ владельца (HEAD == origin/master == `d30b203`, 7 багов ультиматума + 2 бэкенд-рекона; pytest 4760; прод PID 454654). **7 задач → 3 фичи** (`plans/features/`), нумерация T-925…T-973 (продолжает T-924; T-925…T-964 — зафиксированы в KG ранее, файлы tasks.md утрачены при реструктуризации 03.09 → пересозданы @PM по KG-канону). Стадия на старте — PLANNED: spec.md пересоздавал @Architect по наблюдениям сущностей `feature-tma-chat-selector-fixes` / `feature-dm-user-settings` (файлы утрачены при реструктуризации); итоговый статус — см. абзац «Статус (10.09.2026)» ниже.

| # | Задача ТЗ | Фича | AC / канон |
|---|-----------|------|------------|
| 1 | Дубль выбора чата: нативный `<select>` (index.html:414-422) + кнопка «💬 Выбрать чат»/дропдаун (:426-442) + empty-states (:519, :1006) + бейдж (:444-446) | F-13 `tma-chat-selector-fixes` (T-925…T-944) | **AC-1**: остаётся ОДИН нативный select (компактный — без инлайн min/max-w); удалить кнопку/дропдаун (`openChatPicker`/`closeChatPicker`/`pickChat`/`chatPickerOpen`, app.js:151/675/702-711); индикация выбора = значение селектора + compact-бейдж; `activeChatTitle` ЖИВЁТ (index.html:945/1159) |
| 2 | Крестик ✕ сверху справа — выход из Mini App | F-13 | **AC-2**: удалить `closeApp` (index.html:460-461 + app.js:1180-1191); ⛶ `toggleFullscreen` (1193-1207) и мобильный ✕ сайдбара (index.html:376-378) НЕ трогать; grep-проверка других вызовов closeApp |
| 3 | Разделы «Реакции и триггеры», «Провайдеры», «Промпты», «Лимиты» не открываются (пустые) | F-13 | **AC-3** ROOT-CAUSE (подтверждён): Vue 3 v-if/v-for-precedence — `v-if="basicItems(grp).length || advancedItems(grp).length"` на ОДНОМ узле с `v-for="grp in currentTabGroups"` (index.html:551-552): v-if вне скоупа цикла → grp=undefined → все группы схлопываются; регрессия d30b203 (BUG-5). Фикс: `<template v-for>` + v-if на дочернем узле; вторично — configError-баннер на молчаливый 403 (MED-021) |
| 4 | ЛС настраиваются ОТДЕЛЬНО: саммари в ЛС по умолчанию ОТКЛЮЧЕНО; юзер правит параметры/фичи/лимиты/ключи СВОИХ ЛС; наследование от глобальных, кроме изменённых юзером; единственное исключение — саммари default-off | F-14 `dm-user-settings` (T-945…T-964) | **AC-4** канон: DM-скоуп = переиспользование `chat_profiles`/`chat_params` с chat_id=user.id; `is_dm_scope = chat_id > 0`; новый `chat_summary_enabled()` (default-off для ЛС); юзер ЛС = `is_dm_owner` (rank=local_admin, `access_for`); гейт `flags.summary_enabled` bot.py:613-643 НЕ трогать; ноль DDL; REGISTRY 383/71/359 без изменений |
| 5 | WARNING `[direct] no key — sandbox answer | chat=-1002661910336 | reason=budget` при живом ключе и балансе (минуту спустя бот отвечал) | F-15 `direct-sandbox-budget-investigation` (T-965…T-973) | Расследовать: канон — budget = `chat_usage` за день (TZ Екб) + `limits.chat_global_key_budget_*` (req 25 / tok 100k; 0 = запрет); счётчик растёт в конце вызова source='global' (llm_client.py:317-356, chat_usage.py:100-113); диагностика: SQL `chat_usage`/`bot_settings`, `GET /api/config/keys/status`; возможный фикс: диагностические логи бюджет-пути + фоллбэк на BYOK-ключ/ретраи |
| 6 | Раздел «Статус» в сайдбаре перекрыт шапкой; после ухода на другой раздел вернуться нельзя | F-13 | **AC-5** ROOT-CAUSE: мобильный `.sidebar` (index.html:347-350) `z-index:40` == `.header-sticky` `z-index:40` (:328-331), шапка позже в DOM → поверх; фикс `.sidebar { z-index:45 }` (+ `env(safe-area-inset-top)`); MENU_ORDER/TABS — без изменений |
| 7 | WARNING `graphrag memorize: LLM answer is not a JSON list — skipped` | F-15 | Канон: fire-and-forget memorize (direct_chat_service.py:581-584) → `parse_fact_list` (summary_memory.py:380-418); raw НЕ логируется; фикс: лог raw (обрезка/маск, R17), fallback-парсер, 1 ретрай с жёстким промптом |

**Статус (10.09.2026): ✅ Выполнены и заархивированы** — F-13 `tma-chat-selector-fixes` (T-925…T-944), F-14 `dm-user-settings` (T-945…T-964), F-15 `direct-sandbox-budget-investigation` (T-965…T-973) — IMPLEMENTED, аппрув @Reviewer; спеки/задачи — `plans/archive/{tma-chat-selector-fixes,dm-user-settings,direct-sandbox-budget-investigation}/`. **Все 7 задач ТЗ закрыты** (1–3, 6 → F-13; 4 → F-14; 5, 7 → F-15); pytest **4831 passed, 0 failed**; Scanner — 0 blocker/major (отчёт: `plans/reports/full_audit_results.md`); архитектура — `ARCHITECTURE.md` §23–§24 (обновлено @Architect). Техдолг-кандидат на след. раунд: HIGH-004 — полный LLM request/response-лог (в 10.3 делали точечно: диагностика бюджет-пути + raw-memorize с маской секретов); остальное из Scanner-отчёта — вне скоупа раунда. План финальной фазы (полный pytest → README → коммит → деплой + live-проверка) — единый для раунда: исполняется по воркфлоу ПОСЛЕ архивации (README-раздел 10.3 — шаг @PM 10.09.2026; коммит/деплой — следующие шаги).

## Раунд 10.4 (10.09.2026): реструктуризация TMA-миниаппа + точечные фиксы — 9 пунктов ТЗ

ТЗ владельца (HEAD == origin/master == `1410a68`, раунд 10.3 закрыт, рабочее
дерево чистое) — крупная реструктуризация админки миниаппа + точечные фиксы.
Step 0 recon — KG `recon: tma-structure-10.4` (полные координаты: TABS/MENU/
generic-рендер, TAB_RULES param_catalog.py:1374-1406 + _TAB_BY_GROUP :1424-1431
(жёстко: группа → ровно 1 вкладка), REGISTRY 383/71/359 эталон test_param_catalog
MED-017, каскад имён chat_lore.py:585-613/:621-637 + app.js:2335-2346,
точки чтения ТЗ 8). **Планирование 10.09.2026 @PM: 8 фич, T-974…T-1065** (нумерация
продолжает T-973). spec.md — @Architect для каждой фичи (стадия PLANNED).

| # | Задача ТЗ | Фича | Задачи | Ключевые AC / канон |
|---|-----------|------|--------|---------------------|
| 1 | «Реакции и Триггеры»: интервалы/кулдауны/Мимикрия/Dead page → в «Функции PERMsoc» | **A** `frontend-reorg-modules-reactions` | T-974…T-989 | Расширение TAB_PERMSOC: reactions {persons, permsoc, deadpage, mimic, slavik, alan, olya} + flags {permsoc, media} + limits {persons, mimic, deadpage, media}; исключения-списки TAB_LIMITS/TABS-зеркало; REGISTRY 383/71/359 без изменений |
| 2 | «Модули и Фичи» → «Модули»: имена/описания модулей, убрать сводку «Функции PERMsoc» | **A** | T-981…T-984 | MENU_LABELS.modules + label modules_feats → «Модули»; карточки модулей (имя+описание+статус); сводка-кнопка setTab('permsoc') удаляется (вкладка+master остаются); «Модули (вкл/выкл)» (flags_modules+flags_service) → новый config-раздел modules_switches |
| 3 | «Лор чатов»-настройки → в «Лор чатов» под «Расширенные» | **A** (частично) | T-979, T-985-T-986 | TAB_RULES-запись для TAB_CHAT_LORE (limits_lore + flags_lore) + generic-блок в шаблоне chat_lore; права — canEditConfig; исключены из «Лимитов» |
| 4 | Бюджеты «Прямой чат» → флаг вкл/выкл PER-ЧАТ (+ для -1002661910336 ВЫКЛ) | **B** `frontend-limits-temperature-budgets` | T-990…T-993 | Гейт flags.chat_context_budgets_enabled → hot_chat-резолв (async chat_param); override false для -1002661910336 (бэкфил/сид); связь с F-15 (25 req/сутки, sandbox R16); дефолты других чатов не меняются |
| 5 | Температура → выпадающий список | **B** | T-994…T-997 | Новый widget="select" + select_options (ParamSpec); API отдаёт options; валидация 422; REGISTRY без роста; тест widget-keyvalue обновлён |
| 6 | «Имена людей» → отдельный раздел + per-чат/ЛС | **B** | T-998…T-1001 | Новая config-вкладка people_names (limits_user_aliases), KV-редактор; алиасы → per-chat/ЛС-резолв (chat_param паттерн, каскад в web/api/chat_lore.py:555); гейт summary_enabled-плоскости не трогать; F-6-аудит каскада влит (см. ниже) |
| 7 | «Память и RAG» → «Память»; «Сон» и «Ностальгия» → отдельные разделы | **C** `frontend-memory-sleep-nostalgia` | T-1006…T-1017 | TAB_RULES: memory_rag = {limits_memory, limits_graph, flags_memory, memory_infinite}; новые TAB_MEMORY_DREAM / TAB_MEMORY_NOSTALGIA; переразметка basic/advanced (флаги вкл — basic), иначе вкладки пустые после ТЗ 5; гейты gates (F-10) не меняются |
| 8 | «Расширенные» по умолчанию СВЁРНУТЫ (index.html:673-675 `:open="basicItems(grp).length === 0 || expandOpen(activeTab)"`) | **D** `frontend-advanced-collapse-default` | T-1018…T-1023 | :open="expandOpen(activeTab)" — единый источник истины; персист adminbot.expand:<tab> не трогаем; маркер: положительный на :open="expandOpen(activeTab)", негатив на старую строку; итог-анализ эвристики в комментарии |
| 9 | LLM Провайдеры: основные модели → ключи → фолбэк → расширенные | **E** `frontend-llm-providers-layout` | T-1024…T-1032 | TAB_RULES секциями (models_main/keys_llm, groq, openrouter/models_fallback/остальное); groupedForTab — плоская сортировка по (категория, группа) источникам; заголовки секций; маскировка ключей/R17 без изменений; секции advanced ≥1 basic (совместимость с D) |
| 10 | «Участники и отношения» из «Лор чатов» → отдельный раздел; настройки отношений туда | **F** `frontend-relations-participants` | T-1033…T-1044 | Новая вкладка relations (menu chat_profile, свой шаблон; данные — существующий /chat_lore/{id}/relations API); TAB_RULES: relations = {limits_relations, flags_relations} (config-часть вкладки); из chat_lore блок участников удаляется; адаптеры 409/очистка без изменений; known_sections — без расширения |
| 11 | Чат -1002661910336: расширить лимиты контекста/саммари/памяти | **G** `backend-chat-1002661910336-scaling` | T-1045…T-1056 | per-chat overrides через chat_params (get_chat_param паттерн, async); точки чтения: direct_chat_service.py:996-1014/1498-1522/1622/1684-1880/1726, summary_generator.py:133-169, summary_xml.py:63-68, summary_memory.py:1283-1290/1966-2004/2406-2483/2572/2614; бэкфил override для -1002661910336; дефолты/другие чаты НЕ трогать; таблица значений в отчёте; риск: 25 req/сутки глобального ключа (F-15) — наблюдение |
| 12 | «Никнейм/username» в Участниках: у людей username есть, nickname нет / только id | **H** `backend-relations-nickname` | T-1057…T-1065 | Диагностика каскада (alias→nickname(30д/200)→username(топ-50)→''): причины — окно 30д/top-200, _RELATIONS_ENRICH_TOP=50, _display_name uid-снапшот; фикс: имена из users_meta-снапшота + username для ВСЕХ строк (кэш/лениво) или фикс-срез; R16 «id никогда не имя» — сохранить; каскад/отношения без регресса |

**Статус (10.09.2026): ✅ Выполнены и заархивированы** — 8 фич IMPLEMENTED,
аппрув @Reviewer: **D** `frontend-advanced-collapse-default` (T-1018…T-1023),
**C** `frontend-memory-sleep-nostalgia` (T-1006…T-1017), **E**
`frontend-llm-providers-layout` (T-1024…T-1032), **A** `frontend-reorg-modules-reactions`
(T-974…T-989), **B** `frontend-limits-temperature-budgets` (T-990…T-1005),
**F** `frontend-relations-participants` (T-1033…T-1044), **H**
`backend-relations-nickname` (T-1057…T-1065), **G** `backend-chat-1002661910336-scaling`
(T-1045…T-1056); спеки/задачи — `plans/archive/{frontend-advanced-collapse-default,
frontend-memory-sleep-nostalgia,frontend-llm-providers-layout,frontend-reorg-modules-reactions,
frontend-limits-temperature-budgets,frontend-relations-participants,backend-relations-nickname,
backend-chat-1002661910336-scaling}/`. Порядок исполнения **D → C → E → A → B → F → H → G**
соблюдён (обоснование — в плановом блоке выше, при планировании). **Все пункты ТЗ закрыты**
(маппинг — таблица выше); pytest **4860 passed, 0 failed** (4831 → +29: `test_104_backend_additions`
11, `test_progressive_tab_basic_coverage` 3, маркеры webapp_*/frontend_tab_mapping); Scanner-аудит
10.4 — 0 blocker/major (minor/info R10.4-1…R10.4-7 → `ARCHITECTURE.md` §25: R10.4-1/-2/-3 закрыты
follow-up @Builder; R10.4-4…-6 — открыты, кандидаты след. раунда; R10.4-7 — задокументированная
граница G-4 → кандидат F-5). Техдолг-хвосты: **B-13 points 2-4** — per-chat алиасы НЕ доходят до
инжекта `<user_relations>` (работает только точка 1 — TMA-каскад list_relations; отклонение
зафиксировано комментарием в `user_relations.py`, кандидат след. раунда); HIGH-004 (полный LLM
request/response-лог) — отложен, как и в 10.3. Архитектура — `ARCHITECTURE.md` §24–§25 (обновлено
@Architect; счётчик групп 71→74 сверен); REGISTRY 383/74/359 — БЕЗ изменений (эталон
`test_param_catalog`, MED-017); SQLite v8; каноны промптов (R9/PREV_R9, R46-2) и порядок роутеров
`bot.py` — без дифов. Код — в рабочем дереве Merge Phase (коммит/деплой + бэкфилы
`backfill_104_chat_flags.py`/`backfill_104_overrides.py` + live-верификация @DevOps — финальный
шаг раунда).

**Конфликт-матрица с активными фичами F-1…F-6 (проверка @PM 10.09.2026):**

| Активная | Пересечение | Решение / порядок |
|----------|-------------|-------------------|
| **F-1** `post-deploy-admin-minors` (T-648 атомарный POST /api/config; T-651/T-652 касты) | T-648 routes.py POST /api/config — фича B добавляет select-опции и per-chat алиасы (POST путь тот же); T-651 унификация кастов у normalize_value/_coerce — фичи B/G касаются каста (select-значения str; override-касты) | Порядок: **F-1 ДО фиш 10.4-b/g** (после D/C/E/A — не пересекаются). B/G учитывают «атомарность POST» в своих критериях (значение select/алиас — валидный item); T-653 (guard alan) — вне пересечения, но B (температура-float) учесть NaN-поведение (T-654 docstring). |
| **F-2** `admin-debug-webview` | пересечений нет (отдельная страница /debug_config) | Независима; остаётся открытой; верификация — после раунда 10.4 |
| **F-3** `scam-incident-security-followup` (T-663 админ-гейт DM-веток /mimic /deadpage /alangreet, admin_commands.py:40-127) | прямых пересечений нет (admin_commands не дифается); но T-663-плоскость DM (chat_id>0) — та же, что у B (per-chat/ЛС) и F (участники в ЛС) | T-663 — открыта; после 10.4 (иначе расхождение: F добавляет relations-блок для DM — перепроверить при вёрстке T-663: гейт-ветки остаются как есть); отметить в финальной проверке раунда |
| **F-4** `frontend-admin-bugfixes` (Баг-4 «сверка синхронизации разделов», открыт) | Баг-4 проверяет ВСЕ вкладки админки → реструктуризация 10.4 (A/B/C/E/F) меняет карту вкладок; сверку делать ПОСЛЕ | **Порядок: 10.4 (все фронт-фичи) ДО Бага-4** (иначе сверка по старой карте); Баг-4 остаётся открытым, применяется к новой структуре |
| **F-5** `config-read-path-audit` (аудит settings.X vs hot.get) | Фичи G (per-chat резолв) и B (гейт per-chat) добавляют НОВЫЕ read-пути (hot_chat/chat_param); B — алиасы-чтение per-chat | Реестры новых read-путей — в tasks.md G (T-993 AC-B4) и B; **F-5 ПОСЛЕ G/B** (аудит включает новые пути); F-5 остаётся открытой |
| **F-6** `user-aliases-admin` (алиасы в админке — в master 5d011d2; открытые: аудит каскада, «реальный эффект», человеческая верификация, регресс) | **ПРЯМОЕ пересечение с B (ТЗ 6 «Имена людей») и H (ТЗ 9 каскад)** | **Решение: НЕ переоткрывать F-6; влить остаток в 10.4:** аудит каскада AliasResolver → фича H (T-1058/T-1059/T-1063); «реальный эффект» (алиас из админки → /summary/граф) → фича B (T-1005); человеческая верификация → владельцу (сохранить в отчёте B); полный регресс — в каждой фиче. F-6 помечается в графе как «SUPERSEDED_BY(round10.4)» (папка/спека НЕ трогаются, в архив не переносим) |

**Остаётся активным (вне 10.4):** F-1 (перед B/G), F-2 (самостоятельно),
F-3 T-663 (после 10.4, перепроверка DM-плоскости), F-4 Баг-4 (после 10.4),
F-5 (после G/B), F-6 (влить/SUPERSEDED — см. выше); техдолг-кандидаты из
Scanner (plans/reports/full_audit_results.md): HIGH-004 (полный LLM-лог) —
отложен (F-15 сделал точечно); другие HIGH-001/002/003/005/006/007/008 +
MED-* — вне скоупа (дефект-эпик — кандидат на следующий раунд). Диск/SSH
сервера (fail2ban/ufw, деплой-операции) — active (см. MEMORY.md, раздел
«Безопасность сервера»).

**Тест-риски раунда:** test_frontend_tab_mapping.py и
test_webapp_nav_disclosure_ui.py придется обновить в КАЖДОЙ фронт-фиче
(MED-022-прецедент 10.2/10.3 — маркеры фиксируют старое поведение);
test_param_catalog (эталон 383/71/359) — не менять; test_webapp_avatars_ui /
test_webapp_dm_ui / test_webapp_rbac_ui — поправка под новые вкладки;
new Select-widget-тест; структура-разметка (basic ≥1 на вкладку) — новый тест;
`node --check web/app.js` — на каждой фронт-фиче; полный pytest — общий финал
раунда (baseline 4831 + новые, ожидание ~4850-4900).

**Конфликты с активными фичами (проверка @PM 09.09.2026):**
- **F-1 `post-deploy-admin-minors`** — T-648 (атомарный POST /api/config: `web/api/routes.py`) пересекается с F-14 POST /api/config (ensure_scope_profile + is_dm_owner-гейт, routes.py:380-388) → порядок: F-14 ДО T-648; T-650 (docstring `can_edit_param`, deps.py:206-212) — F-14 расширяет саму функцию в `services/access.py` → T-650 после F-14; T-651/652 (унификация кастов) — учесть новый cast в `get_chat_param_defaulted`.
- **F-3 `scam-incident-security-followup`** — T-663 (админ-гейт DM-веток `/mimic /deadpage /alangreet`, admin_commands.py:40-127) — та же DM-плоскость (chat_id>0), что F-14; в F-14 admin_commands.py НЕ диффится, T-663 остаётся открытой → исполнять после F-14, отметить в финальной проверке.
- **F-4 `frontend-admin-bugfixes`** — Баг 4 («сверка синхронизации разделов») затрагивает тот же рендер-зон конфиг-вкладок (index.html:551-552), что AC-3 → порядок: F-13 ДО Бага-4 F-4 (иначе конфликт шаблона и двойная сверка).
- **F-5 `config-read-path-audit`** — остаточный аудит `settings.`-read-путей: новые read-пути F-14 (`chat_summary_enabled`/`get_chat_param_defaulted`) и F-15 (бюджет/`WORKER_BUDGET_TZ`) включить в аудит (стиль «через hot.get» — обязателен).
- **F-6 `user-aliases-admin`** / **F-2 `admin-debug-webview`** — пересечений нет (аудит/верификация, других файлов).

**Scanner-аудит (plans/reports/full_audit_results.md, 09.09.2026) — учтён частично:** HIGH-004 → F-15 (диагностические логи бюджет-пути/raw-memorize; полный LLM request/response-лог — вне 10.3, кандидат в след. раунд), MED-021 → F-13 AC-3 (configError-баннер), MED-019 → F-14 (юнит-тесты DM-матрицы, T-941), MED-017 → F-14 (каталог без изменений — эталон test_param_catalog), MED-022 → обновление маркер-тестов (F-13/F-14), MED-015 → F-15 (точечные правки, сигнатуры не меняем). Остальное (HIGH-001/002/003/005/006/007/008, MED-003…008/011…016/018/020, LOW-*) — вне скоупа 10.3; дефект-эпик «техдолг по аудиту Scanner» — кандидат на след. раунд (список: reports/full_audit_results.md).

## Раунд 9 / Фаза 2 (06.09.2026): AGI Memory Implementation — 2a Отношения (A-Life) + dig_into_lore → 2b «Сон» (beliefs) → 2c Ностальгия

Эпик = реализация Фазы 2 research `plans/docs/agi-memory-research.md` (§3–6, §7, §10; Фаза 1 research-only завершена 06.09) по апруву владельца с правками: **локальная LLM (Ollama qwen3.5:9b) НЕ используется в боевых воркерах** — «сон»/ностальгия/отношения работают только на облачных моделях через существующий LLMClient (apinet/deepseek + fallback, путь обычных ответов; локальная осталась для разовой векторизации истории); **настройки A-Life — ВНУТРИ существующего раздела «Лор чатов»** (PG `chat_profiles`, per-chat, блок «Участники и отношения» во вкладке «Лор чатов»; блоки «Синтез (сон)» и «Ностальгия» — во вкладке «Память и RAG»), новых TMA-разделов не плодим. Планирование: `plans/archive/agi-memory-implementation/tasks.md` — **T-815..T-838** (24 задачи, секции A–H; дизайн-решения и протокол Q1–Q14 — раздел A tasks.md; spec.md при планировании не создавался по ТЗ владельца, прецедент раунда 8). **Решения @PM (структура): одна реализация + один деплой** (все подфазы в одном эпике, порядок B→C→D→E→F, один прод-окно; риск — тумблеры подфич off по умолчанию), задачи сгруппированы по подфазам. Скоуп: 2a — SQLite `users_meta` (аддитивно, PK(chat_id,user_id), стадии stranger→…→veteran с decay/анти-откатом, manual-стадии админа — PG `chat_profiles.relations JSONB` + 409-оптимизм, инжект `<user_relations>` в direct_chat) + tool `dig_into_lore` (3-й в TOOL_CALLING_TOOLS, FTS5+граф-имена+год-фильтр, 5–8 сниппетов, канон R9: ИНСТРУМЕНТЫ+=dig + контракт «помнишь/в 2024 → вызови ДО ответа» + PREV_R9-ступень миграции PG-промпта, пре-гейт маркеров); 2b — миграция **v8** (rebuild graph_facts: importance/source_ids/kind/belief_meta + origin `derived_belief`, user_version=8, по образцу v7) + importance-правило на записи + DreamWorker (облачный LLMClient, кластеризация без LLM, пороги/бюджеты, дистилляция 0–2 beliefs с source_ids, supersede, memory_dream_log); 2c — ностальгия слой A (маркер «можно вспомнить» при ответе, 0 LLM-вызовов) + слой B NostalgiaWorker (тихий период, «N лет назад», один облачный вызов на срабатывание, жёсткий анти-спам: max/сутки, quiet hours, cooldown, стоп после 2 неотвеченных, aggressiveness, nostalgia_log). **RUNTIME WARNING:** SQLite-схема прода/локально — v7; единственная миграция эпика — v8 в фазе 2b (2a работает на v7); новые таблицы — только CREATE IF NOT EXISTS без bump; PG — только ADD COLUMN IF NOT EXISTS relations; промпт-канон R9 — через PREV_R9/PROMPT_MIGRATIONS/байт-тесты. **Статус: ✅ Реализован и заархивирован (06.09.2026) — деплой T-837, см. `plans/archive/agi-memory-implementation/`** — 4562 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §21; закрыто по ревью: T-815..T-835. **Статус: ✅ Полный (06.09.2026) — T-836 (README-раздел «AGI Memory (Фаза 2, раунд 9)» + счётчик 4562) и T-837/T-838 (деплой на прод) закрыты @DevOps:** коммиты 663664e..5694f66 (6 feat + docs(readme) + docs(plans)) → пуш `84c4887..5694f66`; сервер `git pull --ff-only` → `aafb769..5694f66`; бэкап БД до миграции — `/home/nik/backups_adminbot/local_database_20260906_111233_pre_v8.db` (755 МБ, sqlite3 .backup); рестарт `admin_bot` → active; журнал: `[database] migration v8: graph_facts rebuild (importance/source_ids/kind/belief_meta + derived_belief)` + user_version=8, `[prompt_migration] канон обновлён | key=prompts.direct_chat_system_prompt` (R9), DreamWorker/NostalgiaWorker зарегистрированы (флаги off — джобов нет), RelationsService initialized, LoreWorker started, ошибок 0; live-верификация: PRAGMA user_version=8, `graph_facts` = 10557 (сохранено ~10.5k), колонки importance/source_ids/kind/belief_meta + CHECK origin `derived_belief` (INSERT-проба → ok → откат), таблицы users_meta/dream_state/memory_dream_log/nostalgia_log созданы, PG `chat_profiles.relations/relations_enabled` (information_schema) применены, пул concurrency per_chat=3, health `/api/health` = 200, error|traceback = 0.**

## Раунд 8 (06.09.2026): Context-Layer X-Features — 24 пункта [х] из CONTEXT_RESEARCH (атрибуция людей, фокус, память, RAG, промпт)

Эпик по research `plans/docs/CONTEXT_RESEARCH.md` (24 отмеченных `[х]` пункта §2; НЕ входят п.15 «дедуп повторов в окне» и п.19 «порог минимальной релевантности RAG» — `[ ]`): **(Атрибуция)** uid рядом с именем во всех рендерах Global_Context/Thread/UserResolutionMap/Target_User (каскад алиас→никнейм→юзернейм не меняется; «хвосты»-коды не выдаются в чистовых сообщениях), UserResolutionMap по активным участникам (SQL-агрегат), дискриминатор коллизий имён (внутренний, на рендере), привязка фактов к uid/канон-алиасу в memorize/_canon_fact_name, Target_User с uid + protected/RAG-фильтры по людям, «кто спрашивает vs кому адресован» + memorize-хук; **(Фокус)** блок `<Current_Question>`, правила приоритета в системный промпт, защита конспекта от обрезки (verbatim-хвост режется первым), Thread не рвётся на бот-сообщениях (parent-линк бот-реплик), итог ветки над фоном (без LLM), метки свежести блоков; **(Память)** importance-удержание verbatim при переполнении (маркеры имён/«бот»/цитат/чисел), progressive summarization (summary-of-summary, уровни конспекта), compress/purge не трогает protected/высоковесные, пересборка конспекта по заполнению (не по TTL); **(RAG)** подача по rel=cosine×w_eff (не по хронологии), дедуп RAG↔конспект, метки origin+давность, опциональный LLM-реранк top-k (флаг, off по умолчанию, паттерн search_service._rerank_results); **(Промпт)** «как читать блоки» в начало системного промпта, важное к концу user-блока (Target_User/Protected/Current_Question после map/RAG), sandwich-напоминание в конце, стабильный system-префикс для prompt-cache. Меняется `CHAT_SYSTEM_PROMPT` → PREV-слепок + ступень в `PROMPT_MIGRATIONS` + байт-тесты; порядок блоков user-контента → регресс TestContextPartitioning/бюджета. **RUNTIME:** SQLite-схема прода v7 — миграции для пунктов НЕ нужны по умолчанию (новые таблицы — только CREATE IF NOT EXISTS в init; ALTER/bump user_version v8 — только по обоснованию @Architect в A1 для п.10/п.14); локальный graph-воркер истории завершён; история-БД не трогается. Планирование: `plans/features/context-layer-x-features/tasks.md` — T-789..T-814, секции A–H (дизайн-решения и протокол Q1–Q13 — раздел A tasks.md; spec.md при планировании не создавался). **Статус: ✅ Полностью выполнен и задеплоен (06.09.2026)**: 4321 passed / 0 failed, аппрув @Reviewer, архитектура — `ARCHITECTURE.md` §20, закрыто по ревью T-789..T-811 [x]; **деплой (T-813, 21:17 UTC):** git pull --ff-only b198d13..aafb769 → рестарт `admin_bot` → active; SQLite остался v7 (миграций user_version нет), идемпотентные CREATE IF NOT EXISTS применились — таблицы `bot_reply_parents` и `chat_summary_levels` на месте (live-SQL: 2 строки); авто-миграция канона: `[prompt_migration] канон обновлён | key=prompts.direct_chat_system_prompt` (R8); health /api/health = 200; uptime-heartbeat тикает (60s), malformed/error = 0; README-раздел (T-812, коммит 6928df9) и отчёт/закрытие (T-814) выполнены; финальный memory-sync — docs-коммит @DevOps/@Memory; см. `plans/archive/context-layer-x-features/`. Вне архива (исполняет @DevOps финальным шагом в T-812..T-814): README-раздел «Context-Layer X-Features» (T-812), деплой раунда: коммит → пуш → сервер git pull --ff-only, бэкап SQLite-БД, авто-миграция канона `prompts.direct_chat_system_prompt` (migrate_prompt_canons) + идемпотентные CREATE IF NOT EXISTS новых таблиц, рестарт бота, live-верификация (T-813), отчёт юзеру и закрытие (T-814).

## Раунд 7 (05.09.2026): Chat Lore Management v2.0 — PG-профили чатов, авто-лор-воркер, TMA «Лор чатов»

Эпик по research `plans/docs/chat-lore-management-research.md` (вариант C, [x] рекомендован §5) + ТЗ владельца: вывод захардкоженного лора (`services/chat_lore.py`, раунд 5, T-733) в управляемую сущность — 4 новые PG-таблицы (`chat_profiles` manual/auto-лор независимы + `chat_lore_history`-аудит + `chat_links`-ремаппинг + `chat_admins` per-chat), раздел Mini App «Лор чатов» (селектор чатов, ручной/авто-лор, настройки окна/периода, «Сгенерировать сейчас», история, remap; 409-optimistic locking), авто-воркер лора (окно `smart_messages` → Merge-промпт-канон → запись auto_lore; pg_advisory_lock, NOTIFY `lore_updated` + LISTEN-инвалидация RAM-кэша профилей), lifecycle-хендлеры (my_chat_member бота, migrate_to_chat_id), инжект PG-лора в direct_chat (cap, fail-open, флаг `flags.lore_inject_enabled`; легаси SQLite-путь сохраняется при отсутствии PG-профиля), сид `scripts/seed_chat_lore.py` для -1002661910336. **RUNTIME WARNING:** локально работает graph-воркер юзера (SQLite-история) — вне скоупа SQLite-схема/`tools/history_import/`/`manage.py`/`summary_memory`; весь код эпика — PG + FastAPI (`web/api`) + TMA (`web/app.js`+`index.html`) + добавочные aiogram-хендлеры (порядок роутеров bot.py не менять). Планирование: `plans/archive/chat-lore-management-v2/tasks.md` — T-770..T-788, секции A–I (дизайн-решения и протокол Q1–Q9 — раздел A tasks.md; spec.md при планировании не создавался). **Статус: ✅ Выполнен и заархивирован (06.09.2026), см. plans/archive/chat-lore-management-v2/** — 4207 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §19; закрыто по ревью T-770..T-785. Вне архива (исполняет @DevOps финальным шагом в T-786..T-788): README-раздел «Лор чатов (v2.0)» (T-786), деплой раунда на прод: сид `scripts/seed_chat_lore.py` для -1002661910336 + live-верификация вкладки TMA (T-787), отчёт юзеру и закрытие (T-788).

## Раунд 6 / ФАЗА 2 (05.09.2026): эпик импорта истории + бессрочная память (гибрид FTS5 + GraphRAG)

Планирование фазы 2 (пункт 5 раунда 5) после фазы 1 (архив `betterstack-lore-prompts-round5`, 3844 passed; HEAD afe265a; дерево на планирование: `M plans/docs/memory-project-overview.md`). **Эпик** = пункт юзера «Миграция истории чатов, отмена TTL и Гибридная память (FTS5 + GraphRAG)»: 4 JSON в `migrate_history/` (1.08 ГБ, 2.217M сообщений, ОДИН чат, переезжавший между экспортными id 2661910336/2417005237/1691371902; таргет runtime-супергруппа `-1002661910336`) → FTS5-импорт в `smart_messages` (этап на СЕРВЕРЕ: только он, RAM 961МБ, диск ~14ГБ свободно) + GraphRAG-воркер по истории (этап ЛОКАЛЬНО на ноутбуке юзера: Ollama `qwen3.5:9b` через OpenAI-совместимый endpoint, эмбеддинги API gemini-embedding-001 dim 3072 в существующие vec0) + бессрочное хранение (тумблер `memory.infinite_retention`, отмена TTL/purge) + миграция v7 (`graph_facts.message_timestamp`, origin `history_import`) + `manage.py import_history` (tqdm, чекпоинты/resume). Планирование: `plans/archive/history-import-hybrid-memory/tasks.md` — T-747..T-769 (секции A–G; дизайн-решения — раздел A tasks.md, отдельный spec.md создан @Architect 05.09). **Статус: ✅ Выполнен и заархивирован (05.09.2026), см. plans/archive/history-import-hybrid-memory/** — 3936 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §18. Импорт данных — операционный шаг @DevOps/юзера ВНЕ архива: FTS-этап — на сервере (T-767), graph-этап — на ноутбуке юзера (T-768). Вне архива (исполняет @DevOps финальным шагом в T-765..T-769): README-доки (T-765), деплой фазы 2 на прод с тумблером `memory.infinite_retention` ДО импорта (T-766), FTS-импорт (T-767), graph-этап по инструкции (T-768), перенос graph-дельты на прод + отчёт (T-769).

## Раунд 5 (04.09.2026): betterstack-токен, лор-инжект, промпты; фаза 2 — импорт истории (отдельно)

Планирование раунда 5 после раунда 4 (архив ниже). ФАЗА 1, четыре пункта: (1) **betterstack-токен** — root cause 401 найден: код корректен (токен строго из .env, bot.py:115-116), юзер вставил в `LOGTAIL_SOURCE_TOKEN` public key из SENTRY_DSN вместо Source Token (Logs → Sources) → код-эвристики (детект DSN-pubkey, `from=` в attached-маркере, 401-WARNING-подсказка) + отчёт юзеру с curl-инструкцией; (2) **лор-инжект** чата 2661910336 (конфа пермская, бот ошибочно считает её екатеринбургской): миграция v6 protected_facts (user_name nullable) + чат-уровневые факты (user_name IS NULL, видны всем в `<protected_facts>`) + `services/chat_lore.py` (CHAT_LORE_2661910336 + idempotent inject) + инжект/чистка «екатеринбург»-фактов на проде с бэкапом; (3) **память sqlite→PG НЕ выполнять** — Epic 86 заморожен (04.09.2026, решение владельца, см. ниже); (4) **промпты** — во ВСЕ user-facing промпты (9 констант/9 PG-ключей prompts.*) единый запрет кавычек-ёлочек («») и длинных тире (—) + смягчение строчных («Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы»); PREV_-слепки канонов + `services/prompt_migrations.py` (PROMPT_MIGRATIONS + migrate_prompt_canons, замена migrate_direct_chat_prompt_if_legacy). **Статус: ✅ Выполнен и заархивирован (05.09.2026), см. plans/archive/betterstack-lore-prompts-round5/** — 3844 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §17. Вне архива (исполняет @DevOps финальным шагом в T-743..T-746): лор-инжект в прод (T-743), чистка «екатеринбург»-фактов в чате 2661910336 (T-744), деплой и live-проверки (T-745), отчёт юзеру с curl-инструкцией (T-746). Пункт 5 (фаза 2 — импорт истории 4 JSON + FTS5/GraphRAG) — отдельный цикл ПОСЛЕ деплоя фазы 1, в этот раунд не входит.

## Раунд 4 (04.09.2026): собственный BetterStack-хендлер, отказные ответы видео-моделей, «запомни/забудь», промпт-баг TMA

Планирование раунда 4 после раунда 3 (архив ниже). ПЯТЬ блоков. (1) BetterStack: log_config=None уже стоит (hotfix 30.08, bot.py:626-634), реальной причины «логи не идут» в коде не видно; logtail-python 0.4.0 — чёрный ящик (raise_exceptions=False, drop_extra_events=True, тихие дропы, ошибки не логирует); aiogram.event логирует КАЖДЫЙ апдейт на INFO (aiogram 3.31 dispatcher.py:174-185) → спам; уровня не задан. Решение: заменить LogtailHandler собственным BetterStackHandler (logging.Handler, POST на in.logs.betterstack.com, payload-совместимость с logtail frame.py: dt/level/severity/message/context.runtime/context.system, Bearer), буфер+фоновый флашер, ЯВНЫЙ лог ошибок в journald (WARNING, ≤1/60с), счётчики, стартовое тест-событие, flush при shutdown; aiogram.event → WARNING. (2) Видео: free-роуты OR могут отказывать/не получать видео (minimax-m3:free, gemma-4-31b-it:free — только кадры, без аудио; audio+video из free — только nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free, требует live-проверки): отказные ответы («не вижу видео» и т.п.) сейчас проходят как успех L1/L2 и уходят юзеру; даже успешный визуал не слышит звук. Решение: детект отказных/пустых ответов (маркеры + мин-длина) → считать пустым уровнем → каскад на fallback/STT; дефолты: primary → nemotron-omni:free, fallback → minimax-m3:free; промпт-маркер VIDEO_UNAVAILABLE — на решение @Architect (менять канон = PG-миграция). (3) Память-команды «запомни X» / «забудь <слово/фраза>» в direct_chat (существующее: /forget по bot_direct_reply своего target_user, /clear, protected_facts пуста в проде); RBAC чата: ConfigCache admins/roles/get_role (bot_admins: telegram_id/role_name) с фолбэком settings.ADMIN_USER_ID; тумблер flags.memory_commands_user_enabled (default false); хранение — origin 'user_memory' (CHECK-миграция v5) или protected_facts (решение @Architect); журнал graph_fact_compressions; пул CHAT_MEMORY_CMD_*. (4) Промпт-баг TMA: фронт web/app.js:550-551 `isNaN(value)` для str-полей (isNaN('текст')===true) → ложный toast «Некорректное значение…», сервер для str принимает всегда; пустой промпт — 422 сервера или тост (решение @Architect). (5) Research/процесс: отчёты импорта истории (plans/docs/memory-import-research.md — 3 файла ~602МБ ~1.27M сообщений, ТРИ разных чата: 2417005237/2661910336/1691371902 — отметить юзеру; стоимость FTS бесплатно/эмбеддинги ~$0.3-5/LLM-факты ~$3-15 на 100k; free-роуты 50 req/день непригодны) и sqlite→PG (plans/docs/sqlite-to-pg-research.md, Epic 86); .gitignore += migrate_history/ (риск коммита 600МБ — ОТСУТСТВУЕТ); даты в RAG-фактах (created_at «%Y-%m-%d» в рендер chat_history get_rag_context — «что было N-числа» сейчас не работает); правило авто-коммита memory-sync в конце каждого раунда. **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/betterstack-own-handler-video-memory-cmds/** — 3794 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §16. Вне архива (исполняет @DevOps финальным шагом в T-726): правило G1 → plans/project.md, README-правки, коммит всего, пуш, деплой и live-верификация. (Источник: контекст-диагностика @PM 04.09, MEMORY.md.)

## Epic 86: GraphRAG → PostgreSQL

Миграция GraphRAG-хранилища (граф nodes/edges, векторы, индексы, TTL/cleanup) с SQLite на PostgreSQL 16 (asyncpg). Извлечена из Epic 85 (решение человека 30.08). **Статус: ОТМЕНЁН/ЗАМОРОЖЕН (04.09.2026, решение владельца — раунд 5, пункт 3): миграцию памяти sqlite→PG НЕ выполнять, память остаётся на SQLite; DESIGN @Architect не запускать; при необходимости эпик может быть переоткрыт.** (Источники: board.md, backlog.md:8435-8437 в git-истории до 03.09.2026, MEMORY.md.)

## Epic: Улучшения фактчека (аудит FACTCHECK_AUDIT)

4 рекомендации «вне скоупа» из аудита 2026-08-20: (1) жёсткий вердикт-формат в промпте + обязательные источники; (2) параллельный каскад Tavily+Exa (замена последовательного); (3) кэш проверок claim→hash→TTL 1ч; (4) query expansion. **Статус:** не начат; НЕ связан с отложенными идеями RESEARCH_HUMAN. (Источник: FACTCHECK_AUDIT.md в git-истории до 03.09.2026; выжимка — `docs/factcheck-audit.md`.)

## Bugfix-раунд 04.09.2026: TG-видео-команды, безопасный direct-stream, Tool Calling-фиксы

Bugfix-раунд после эпика 04.09 (архив ниже). Три блока: (1) «транскрипт/че за видос/о чем видео/поясни за видос/перескажи видос/че в видосе» работают ТОЛЬКО для YouTube-URL (handlers/youtube.py:47-107: парсер возвращает `(None, None)` без URL → UNHANDLED), обычные TG-видео (video, документы mime video/*, в т.ч. репосты/forward) никем не обрабатываются — единственный медиа-хендлер `F.voice|F.video_note`; (2) маршрутизация скачивания: `is_direct_media_url` стримит «прямые» `.mp4/.webm/...` даже у известных платформ (youtube/tiktok/instagram/vk/x/rutube и пр.), у direct-ветки «скачай» нет `cooldown_touch`, реплай «скачай» на видео-сообщение не разбирает `reply_target`; (3) tool calling direct_chat: `CHAT_SYSTEM_PROMPT` не упоминает инструменты, description'ы `query_chat_memory` не покрывают счётные вопросы («сколько раз…»), результат тула не содержит count/даты, возможна тихая деградация на 1-м раунде (`tool_loop.py:37-49`). **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/tg-video-tool-calling-fixes/** — 3526 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §14. Вне архива: README-правки, коммит всего, пуш, деплой и live-верификация (T-683…T-685) — финальный шаг @DevOps. (Источник: контекст-диагностика @PM 04.09, MEMORY.md.)

## Раунд 3 (04.09.2026): видео-мультимодал по файлам (/media/), «сцуко»-петля, BetterStack

Планирование раунда 3 после bugfix-раунда 04.09 (архив выше). Три проблемы. ПРОБЛЕМА 1 — BetterStack: сервер исправен (токен 26 симв на месте, сеть 200, logtail-python 0.4.0), но события в панель не идут; вероятные причины — тихие потери буфера logtail (Queue 1000, raise_exceptions=False, drop_extra_events=True), жёсткий SIGKILL при рестарте 02:11:14 (stop-sigterm таймаут 30с), сторона панели. ПРОБЛЕМЫ 2+3 — видео: (02:45) выжимка «по памяти» на «немом» TG-видео (транскрипт 29 симв → RAG facts=10; визуального канала у медиа-ветки нет), (03:21) Groq timeout → OpenRouter STT HTTP 400 → отказ; баг CHECK constraint graph_facts.origin без 'video_transcript' (сотни тихих падений), «smart_message row not found» при L2-инъекции; «транскрипт» медиа-ветки без HTML как у кружков. Целевая логика: выжимка и «транскрипт» для ВСЕХ типов видео (YouTube/прямые/нативные/не-YouTube платформы) ТОЛЬКО по реальному контенту; для мультимодалки нативных файлов — новая публикация временных файлов: FastAPI /media/<signed>/<file> (HMAC+TTL, 127.0.0.1:8000) + Caddy-маршрут /media/* наружу. ПРОБЛЕМА 4 — «сцуко»: слово впервые сгенерировала САМА модель deepseek-v4-flash (fallback при аварии apinet 03:43:55), дальше петля style_anchors (копирование дословно, 14/16 ответов) + RAG bot_direct_reply (TTL пусто = вечно); промпт в БД == канону, «сцуко» в промпте нет. **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/video-multimodal-pipeline-and-incidents/** — 3618 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §15. Вне архива (исполняет @DevOps финальным шагом): чистка «сцуко» в БД прода, BetterStack live-тест и TimeoutStopSec, README-правки, коммит всего, пуш, деплой с Caddy-маршрутом /media/*. (Источник: контекст-диагностика @PM 04.09, MEMORY.md.)

## Epic: Мультимодальная саммаризация, Tool Calling, рефакторинг реакций и UX/UI админки (АРХИВ)

4 части: (1) каскадная видео-выжимка через OpenRouter `video_url` — primary `minimax/minimax-m3:free`, fallback `google/gemma-4-31b-it:free`, затем старая логика субтитров (graceful degradation); (2) Tool Calling — `execute_web_search`, `query_chat_memory`; (3) фиксы реакций — тумблеры `reactions.vasya_enabled`/`reactions.kucha_enabled`/`flags.mimic_enabled`/`reactions.alan_mimic_enabled` (default `false`), строгий гейт `slavic_chlen.mp4` по `reactions.slavik_user_id`, Alan → Леха; (4) UX/UI админки — группировка вкладок, KV-редактор `limits.summary_aliases`. **Статус: ✅ Выполнен и заархивирован (04.09.2026), см. plans/archive/multimodal-summarization-tools-reactions-ui/** — 3447 passed, 0 failed, аппрув @Reviewer; архитектура — `ARCHITECTURE.md` §13. Вне архива: деплой и живая верификация (T33/T34) — шаг @DevOps; финальный memory-sync — шаг @Memory.

---

Сознательно отклонённые/отложенные идеи (RESEARCH_HUMAN): per-bot throttle, wallet на чат, triage-гейт, TTS, мемы и пр. — НЕ активны, см. `docs/research-directchat-digest.md`. Закрытые эпики 1–85 — история в git-истории (прежние файлы plans/, удалены 03.09.2026).
