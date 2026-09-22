# Round 10.25 — сквозной архитектурный слой (Step 2 @Architect · Эпик 1 «Liquid Glass Control Center»)

> **Назначение:** архитектурная карта раунда 10.25 (аналог `plans/archive/round1023-architecture.md` / `round1024-architecture.md`) — чтобы видеть фичи, их слои, зависимости, ступени общих файлов, инварианты и kill-switch’и в одном месте.
> **Мастер-ТЗ:** `plans/current_task.md` v6.0 — **untracked**, в git НЕ коммитить, секреты не цитировать (R17/R18).
> **Baseline:** ветка `master`, HEAD `da561bc` (раунд 10.24, ✅ COMPLETED+DEPLOYED+ARCHIVED); pytest **7911/0**; SQLite `user_version=12`; каталог **REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418**; APP_VERSION 2.58.0.
> **Объём Эпика 1:** **12 фич (F0 + F1–F11)**, приоритет P0. **F0 (Wave 0, добавлена UPD)** — обязательные багфиксы сохранения конфигурации, выполнялась **до F1**; папка — `plans/archive/f0-config-bugfixes-round1025/` (**✅ ARCHIVED**, Шаг 8 @PM 20.09.2026; spec.md + 4 ADR + tasks.md, T-2410…T-2455). Внутри F0 — блок **F0.5 «устойчивость к `database is locked`»** (T-2442…T-2455) — прод-деградация 20.09.2026, **расширение ADR-1024-18** (`plans/archive/sqlite-lock-resilience-round1024`, `smart_cache`) на `database.py`/`summary_memory`/`persistent_throttling`. Эпик 2 (Summary Hybrid Pipeline) — **не** в этом раунде; стартует только после приёмки Эпика 1 (F10). **Эпик 3 «Agentic Intelligence»** (раунд 10.26+, после Эпиков 1–2) — **верхнеуровнево** в `plans/backlog.md` (фичи A0–A10); архитектура — отдельным `round*-architecture.md` при старте Эпика 3.
>
> **📌 PM-аннотация (UPD, Step 1):** F0 добавлена в Wave 0, изменён порядок фич (F11 перед F9), F9 сужена (persistence/409 → F0). **Детальный `spec.md`/ADR по F0 и AMEND `physical-two-call-pipeline` для Эпика 3 — зона Step 2 @Architect** (PM архитектуру не создаёт).
>
> **✅ F0 — COMPLETED + MERGED + ARCHIVED (Step 7 Merge / Шаг 8 @PM, 20.09.2026):** реализована и принята — @Reviewer **Approved** (итерация 3), @Scanner **Critical 0 / High 0** (повторный аудит, `round1025_f0_scanner_audit.md` §5); ADR **1025-2/3/4/5** приняты; контракты интегрированы в глобальную архитектуру — `plans/ARCHITECTURE.md` **§9** (save-path/409), **§10** (DB-lock наблюдаемость), **§49** (анти-клише AMEND), **§51** (F17 AMEND), **§52** (полный раздел F0). pytest **7946/0**; JS **19/19**; Δ DDL=0; Δ каталога=0; `smart_cache` не тронут; остаточный техдолг — **M-2** + Info/Low (§52.8). **Архив:** `plans/archive/f0-config-bugfixes-round1025/`. **⚠️ Live-приёмка (T-2419/T-2433/T-2454) — post-deploy gate, НЕ выполнена; деплой в прод НЕ подтверждён.** Бэкап `var/backups/web-round1025-f0-<ts>/` и теги `pre-round1025*` хранятся до утверждения владельцем (R18).

---

## 1. Обзор фич

| # | Фича (папка `plans/features/*-round1025`; ✅ архивные — `plans/archive/*`) | Слой | Роль | Зависит от | Δ каталога | DDL | Kill-switch |
|---|---|---|---|---|---|---|---|
| **F0** ✅ | `plans/archive/f0-config-bugfixes-round1025/` (ARCHIVED, Шаг 8 @PM) | persistence/state + UI (web/api) + **backend (надёжность БД, F0.5)** | **Wave 0, выполнялась ДО F1** | — | 0 | 0 | — (F0.1–F0.4 багфикс); **F0.5 → `DB_LOCK_RESILIENCE_ENABLED`** (env-only, default ON) |
| **F1** | `ia-shell-navigation-round1025` | IA + app shell (web + nav-метаданные) | **ядро/каркас** | F8 (Wave 0), **F0** (контракт сохранения) | nav-метаданные (0 ParamSpec/Group) | 0 | `IA_V2_ENABLED` |
| **F2** | `design-tokens-liquidglass-v2-round1025` | web (CSS/токены) | визуал | F1 | 0 | 0 | (по фиче) |
| **F3** | `global-scope-selector-round1025` | UI + state (web) | §5 селектор области | F1 | 0 | 0 | — |
| **F4** ✅ | `module-catalog-quickpanel-store-round1025` (архив — `plans/archive/module-catalog-quickpanel-store-round1025/`) | UI + state (web) | §31–§45 каталог/избранное/store | F2, F3 | 0 | 0 | — |
| **F5** ✅ | `plans/archive/module-workspace-tabs-round1025/` (ARCHIVED, Шаг 8 @PM; **ADR-1025-15**) | UI + IA (web) | §46/§48 workspace-табы | F4 ✅ | 0 | 0 | — (откат `git revert` + `openModuleWindow`) |
| **F6** ✅ | `plans/archive/memory-analytics-reorg-round1025/` (ARCHIVED, Шаг 8 @PM; Merge §65) | UI + adapter (web/api) | §4/§21–§30 память↔аналитика, ExecutionGraph | F1, F4 | 0 | 0 | — |
| **F7** ✅ | `plans/archive/permsoc-local-space-round1025/` (ARCHIVED, Шаг 8 @PM; Merge §66; **ADR-1025-20**) | UI + backend | §60–§67 локальное пространство PERMsoc | F3 ✅, F4 ✅ | 0 | 0 | — |
| **F8** ✅ | `plans/archive/parameter-registry-widget-map-round1025/` (ARCHIVED, Шаг 8 @PM 23.09.2026; Merge §67; **ADR-1025-21**; deploy **NOT_APPLICABLE**) | реестр/инвентарь (read-only enabler, **Wave 0**) | §1/§2/§3/§117 реестр 459 + карта экранов/виджетов + бэкап/diff | — | 0 | 0 | — |
| **F9** ✅ | `plans/archive/secrets-and-save-states-round1025/` (ARCHIVED, Шаг 8 @PM 23.09.2026; Merge §68; **ADR-1025-22**; DEPLOYED `f5fbd5f`/`c610c5f`/`49c1ae1`, 2.58.16) | UI + API | §50 секреты + визуальный SaveBar §69/§78 (**persistence/409/state → F0**) | **F0** ✅, F4 ✅, F5 ✅ | 0 | 0 | — |
| **F10** | `epic1-verification-round1025` | верификация (gate) | §71–§79/§114/§116/§117 приёмка Эпика 1 (+ критерии §6 F0) | **F0**, F1–F9, F11 | — | — | — |
| **F11** ▶️ | `status-showcase-dashboard-round1025` | UI (web) | §11–§21 композиция виджетов Статуса | F1, F2, F6 | 0 | 0 | — |

> **Итог Эпика 1:** Δ каталога = **0** (только nav-метаданные F1; реестр F8 — read-only инвентарь; F0 — багфикс); Δ DDL = **0** (SQLite `v12`, PG без изменений; **F0.5 — тоже Δ DDL = 0**, без миграций). Новые рубильники — env-only `ClassVar` (default ON), вне `param_catalog`. **F0.1–F0.4 — без флагов** (откат: `git revert` + точка отката T-2410); **F0.5 — `DB_LOCK_RESILIENCE_ENABLED`** (default ON, откат флагом OFF).
>
> **Статус F0 (обновлено на Archive/Шаг 8):** ✅ **COMPLETED + MERGED + ARCHIVED** — папка перенесена в `plans/archive/f0-config-bugfixes-round1025/` (spec.md + 4 ADR + tasks.md; содержимое/чекбоксы/UTF-8 сохранены); pytest **7946 passed / 0 failed** (база 7911 → +35); JS **19/19**; Δ DDL=0 (`user_version=12`); Δ каталога=0 (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / Settings 418); `smart_cache` не переписан. Новые env-only `ClassVar`: `DB_LOCK_RESILIENCE_ENABLED` (ON), `ANTICLICHE_MAX_PATTERNS_PER_RUN` (40), `ANTICLICHE_MAX_ROUNDS` (3). **⚠️ Открыты live-приёмки @DevOps (post-deploy gate, НЕ выполнены): T-2419 / T-2433 / T-2454** (§52.9 `ARCHITECTURE.md`); **деплой в прод не подтверждён**. Бэкап/теги `pre-round1025*` не удаляются до утверждения владельцем (R18).
>
> **Статус ASAP-хотфикса `hotfix-media-tma-round1025` (обновлено на Archive/Шаг 8 @PM, 21.09.2026):** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED** — папка перенесена в **`plans/archive/hotfix-media-tma-round1025/`** (spec.md + adr-1025-6-bot-api-local-mode.md + tasks.md; содержимое/чекбоксы/UTF-8 сохранены). Коммиты `8b16c4a` (ядро) + `ee23e47` (ревью-итерация) + docs `65e39fb` (origin/master). @Reviewer Approved; @Scanner **Critical 0 / High 0** (2 Medium → техдолг, 4 Low, 4 Info). pytest **7976/0** (7946 + 30 новых), JS **19/19**. **Прод:** `TELEGRAM_LOCAL=1` (контейнер `--local`, общий `.env`), `APP_VERSION` **2.58.1**, `/api/health`=200, `database is locked`=**0**, WAL **159 МБ → 0**. Интеграция — `plans/ARCHITECTURE.md` **§53**; аудит — `plans/reports/round1025_hotfix_scanner_audit.md`. **⏳ Открыт live-гейт владельца (post-deploy, НЕ выполнено): T-2463 / T-2472 / T-2479** (тест видео >20 МБ, консоль TMA). **Следующая задача — возврат к F1 (T-2481):** `git stash pop` (`stash@{0}`, 25 файлов) + untracked F1 из `var/backups/f1-wip-20260921-015653/` поверх `65e39fb`; ожидаемые конфликты — `?v=`/`APP_VERSION` и `IA_V2_ENABLED`; **F1-WIP НЕ трогать до явной задачи**. F1-WIP цел (`git stash@{0}: wip(f1)`, 25 файлов). **Остаточный техдолг:** M-1 (R17 в логе медиа), M-2 (двойной рубильник `TELEGRAM_LOCAL`↔`DOWNLOAD_ENABLED`), LLM-таймауты (провайдер), RAM/swap/graceful-stop, `?v=` для 3 vendor-скриптов, точечный `.gitignore` (§53).
>
> **Статус F1 `ia-shell-navigation-round1025` (обновлено на Archive/Шаг 8 @PM, 21.09.2026):** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED** — папка перенесена в **`plans/archive/ia-shell-navigation-round1025/`** (spec.md + adr-1025-1-ia-v2.md + tasks.md; содержимое/чекбоксы/UTF-8 сохранены). Deploy `fe0f7bb`, `APP_VERSION` **2.58.2**. Коммиты `ff34115` (IA v2 + AppShell), `b1c87b0` (ревью-правки), `78e612a` (аудит Scanner: H-1/Medium). @Reviewer Approved; @Scanner **0 Critical**, H-1 + 2 Medium закрыты (`plans/reports/round1025_f1_scanner_audit.md`). pytest **7996/0**, JS **21/21**. **Δ каталога = 0** (NAV-метаданные: `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21`), **Δ DDL = 0**. Интеграция — `plans/ARCHITECTURE.md` **§54**. F1-WIP восстановлен (T-2481 выполнен). **⏳ Открыт live-гейт владельца: T-2409 — очистка бэкапа только после утверждения владельца.** **Следующая — F2/F3 (Волна 1).**
>
> **Статус P0-фикса после F1 (`fea2daa`, hotfix2; обновлено на Archive/Шаг 8 @PM, 21.09.2026):** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED** — запись фичи перенесена в **`plans/archive/p0-fix-render-media-paths-round1025/tasks.md`** (FIX 1–4). `stickyFieldFailed` computed→methods (регрессия F0 `d5750fc` → пустые config-разделы ИИ: llm/names/smart-cache/memory); container→host путь Bot API (`normalize_api_file_path`/`read_host_file_bytes`, `web/api/avatars.py`; traversal-guard fail-closed сохранён); `APP_VERSION 2.58.2`; усилена `tools/ui_round1025_matrix.py` (непустой config + AI-маршруты + FAIL на console/pageerror). @Scanner **0 Critical / 0 High** (2 Medium → техдолг, 3 Low) — `plans/reports/round1025_hotfix2_scanner_audit.md`; pytest **8003/0**, JS **21/21**. Интеграция — `plans/ARCHITECTURE.md` **§54.1**. **⏳ Открыт live-гейт владельца: реальные видео/ГС/аватары + разделы TMA.** **Остаточный техдолг:** M-1 (сырой `file_path` в логе медиа → логировать `name`), M-2 (avatars `exc_info` — трейсбек не маскируется), TOCTOU-guard, vendor-скрипты без `?v=`, ложно-зелёная матрица при сбое импорта каталога.
>
> **Статус Хотфикса-3 `hotfix3-summary-stt-anticliche-round1025` (обновлено на Archive/Шаг 8 @PM, 21.09.2026):** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED** — папка перенесена в **`plans/archive/hotfix3-summary-stt-anticliche-round1025/`** (spec.md + adr-1025-7 + tasks.md; содержимое/чекбоксы/UTF-8 сохранены). Коммиты `090d2e7`+`fb65965`+`cfe7342`, docs `5f624cd`; `APP_VERSION` **2.58.3**, health 200, `database is locked`=0. @Reviewer Approved; @Scanner **0 Critical / 0 High**; pytest **8041/0**, JS **22/22**. **Δ DDL=0, Δ каталога=0.** Интеграция — `plans/ARCHITECTURE.md` **§55**. **⏳ T-2505 — live-гейт владельца (post-deploy, НЕ выполнено):** саммари с обложкой `article sent`; видео 28 МБ `reason=compressed`; анти-клише «Сохранено N из M»; `llm_stats` в TMA. **Техдолг:** grep-JS-тест анти-клише; реальный ffmpeg `-c copy` на 28 МБ; Info >999 частей; второй LLM-провайдер (не внедряем); M-1 лог `file_path`→`name`; avatars `exc_info`; vendor `?v=`; TOCTOU. **Следующая — F2/F3 (Волна 1).**
>
> **Статус Хотфикса-4 `hotfix4-cover-nav-shell-round1025` (обновлено на Archive/Шаг 8 @PM, 21.09.2026):** ✅ **COMPLETED + MERGED + DEPLOYED + ARCHIVED** — папка перенесена в **`plans/archive/hotfix4-cover-nav-shell-round1025/`** (spec.md + adr-1025-8 + tasks.md; содержимое/чекбоксы/UTF-8 сохранены). Deploy `f2328fb`, `APP_VERSION` **2.58.4**, health 200, `database is locked`=0; @Reviewer Approved; @Scanner **0 Critical / 0 High**; pytest **8071/0**, JS **23/23**, matrix **0**. **A:** корень — per-chat override `prompts.summary_cover_style` игнорировался (читался только глобальный `hot.get`) → фикс `summary_generator._resolve_cover_style_text` (chat→global→default, fail-open) + `has_heading` word-boundary + self-contained канон Редактора (`PREV_*`) + фолбэк при пустом `cover_prompt`. **B:** `--tg-viewport-bottom-offset`+CSS-фолбэк+`viewport-fit=cover`+вертикальная проверка матрицы. **C:** «Статус»+«Справка» первыми для всех. **Δ DDL=0, Δ каталога=0.** Интеграция — `plans/ARCHITECTURE.md` **§56**; спека/ADR — `plans/archive/hotfix4-cover-nav-shell-round1025/{spec.md, adr-1025-8-cover-style-viewport-shell.md, tasks.md}`. **⏳ T-2527 — live-гейт владельца (post-deploy, НЕ выполнено):** обложка с авторским стилем (`style_is_default=false`/`has_comic`/`has_heading` + `article sent`); панель/шторка в пределах экрана; Статус+Справка первыми. **Техдолг:** fake-pool в `test_pg_backed`; async `get_chat_param` на путь обложки (TTL ~120 с); реальный ffmpeg 28 МБ; grep-JS-тест анти-клише; второй LLM-провайдер; M-1 лог `file_path`→`name`; avatars `exc_info`; vendor `?v=`; TOCTOU. **Следующая — F4 (Волна 2).**
>
> **Статус Волны 1 + пакета «Волна 1.5» (обновлено @Memory, Step 10, 22.09.2026):** ✅ **Волна 1** — **F2 `design-tokens-liquidglass-v2-round1025`** + **hotfix5 `summary-cover-window-round1025`** + **F3 `global-scope-selector-round1025`** — COMPLETED + MERGED + ARCHIVED + DEPLOYED (пакет, коммит `4cde1bc`, `APP_VERSION` 2.58.6, Merge — `plans/ARCHITECTURE.md` **§57**; архивы `plans/archive/design-tokens-liquidglass-v2-round1025/`, `plans/archive/hotfix5-summary-cover-window-round1025/` (ретро **ADR-1025-11**), `plans/archive/global-scope-selector-round1025/` (ретро **ADR-1025-10**); @Scanner C0/H0, health 200, `database is locked`=0; полный pytest 8146/5/1, JS 25/25; Δ DDL=0, Δ каталога=0). ✅ **Волна 1.5** — **`hotfix6-webview-shell-heartbeat-round1025`** — COMPLETED + MERGED + ARCHIVED + DEPLOYED (коммиты `055525c`+`ba75751`, push `441e8f7..ba75751`, прод fast-forward `4cde1bc..ba75751`, `APP_VERSION` **2.58.7**, health 200, `database is locked`=0; Merge — **§58**; архив `plans/archive/hotfix6-webview-shell-heartbeat-round1025/` + **ADR-1025-12** + `deployment.md` VERIFIED; pytest **8185/0**, JS **26/26**, matrix **0**; **§15 SUPERSEDE/вынесено из F11 `status-showcase-dashboard-round1025`**). **Следующий шаг — F4 `module-catalog-quickpanel-store-round1025`** (Волна 2, зависит от F2/F3) → F5–F11 → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. ⏳ Открыты live-гейты владельца: **T-2617** (реальный Telegram WebView, hotfix6) + F2 **T-2561**, F3, hotfix5, F1 **T-2409**, hotfix3 **T-2505**, hotfix4 **T-2527**. Детали — `plans/metrics.md` (разделы 10.25-F2 / 10.25-HOTFIX5 / 10.25-F3 / 10.25-HOTFIX6), `plans/MEMORY.md`.
>
> **Статус Волны 1.6 + F4 (обновлено @Memory, Step 10, 22.09.2026):** ✅ **Волна 1.6** — **`hotfix7-shell-glass-heartbeat-round1025`** — COMPLETED + MERGED + ARCHIVED + DEPLOYED (коммиты `7073e34`+`a9cec67`+`2a67829`, `APP_VERSION` **2.58.8**, Merge — **§59**, архив + **ADR-1025-13** + `deployment.md` VERIFIED; pytest 8207/0, JS 27/27, matrix 0; §15 AMEND ADR-1025-12 D4/D2). ✅ **Волна 2 — F4 `module-catalog-quickpanel-store-round1025`** — **COMPLETED + MERGED + ARCHIVED + DEPLOYED** (коммиты **`7f9fed1`** (код+тесты, `APP_VERSION` 2.58.8→**2.58.9**) + **`28eb02d`** (планы: Merge §60 + архивация + Scanner-аудит) + **`f0db773`** (deploy-doc); прод fast-forward `2a67829..28eb02d`, `systemctl restart` active, `/api/health` **200**, served `?v=2.58.9`, `database is locked`=0; Merge — **§60** (§60.1–§60.13); архив — `plans/archive/module-catalog-quickpanel-store-round1025/` + **ADR-1025-14** + `deployment.md` **VERIFIED**; @Reviewer Approved (итер.2, блокер F4-M1 закрыт), @Scanner **C0/H0/M0** (L2/I3); pytest **8229/0**, JS `MODULE-STORE-OK`/`MODULE-CATALOG-OK`, Δ DDL=0, Δ каталога=0; техдолг **§60.10**). **Следующий шаг — F5 `module-workspace-tabs-round1025`** (§46 workspace-табы; заменит реализацию шва `openModuleWorkspace`, не меняя точку входа) → F6 → F7 → F11 → F9 → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. ⏳ Открыты live-гейты владельца: **T-2656** (F4, реальный Telegram WebView) + T-2682 (hotfix7), T-2617 (hotfix6), F2 T-2561, F3, hotfix5, F1 T-2409, hotfix-media T-2463/T-2472/T-2479, hotfix3 T-2505, hotfix4 T-2527. Детали — `plans/metrics.md` (**10.25-F4**, 10.25-HOTFIX7), `plans/MEMORY.md`.
>
> **Статус Волны 3 — F5 `module-workspace-tabs-round1025` (обновлено @Memory, Step 10, 22.09.2026):** ✅ **COMPLETED + MERGED + ARCHIVED + DEPLOYED** (коммиты **`63dddd3`** (код+тесты, `APP_VERSION` 2.58.9→**2.58.10**) + **`0d3ea40`** (планы: Merge §61 + архивация + Scanner-аудит) + **`af137cd`** (deploy-doc); прод `/var/www/admin_bot` fast-forward `28eb02d..0d3ea40`, `systemctl restart` active (Main PID 96796), `/api/health` **200**, `/healthz` **200** (version 2.58.10), served `?v=2.58.10`, `database is locked`=0; Merge — **§61**; архив — `plans/archive/module-workspace-tabs-round1025/` + **ADR-1025-15** + `deployment.md` **VERIFIED**; @Reviewer **Approved** (итер.2/3, блокер M-F5S-1 закрыт), @Scanner **C0/H0/M0/L0** (Info 2) → «к деплою ДА»; pytest **8245 passed / 1 skipped / 5 failed** (5 — env `aiogram`, вне F5), F5 pytest **19 passed**, JS `MODULE-WORKSPACE-OK`/`PROMPTS-SINGLE-SOURCE-OK`/`MODELS-GROUPS-OK`, Playwright **10 вьюпортов × 17 маршрутов — failures: 0**; **Δ DDL=0, Δ каталога=0** (459/98/96/21/418); техдолг **§61.8** (Low 3 + Info 2). До неё закрыты: F0 (Wave 0), hotfix-media, F1, P0-fix (hotfix2), hotfix3, hotfix4, Волна 1 (F2+hotfix5+F3), Волна 1.5 (hotfix6), Волна 1.6 (hotfix7), Волна 2 (F4).
>
> **Статус Волны 1.8 — `hotfix9-shell-liquidglass-darkaurora-round1025` (UPD3; обновлено @Memory, Step 10, 22.09.2026):** ✅ **COMPLETED + MERGED + ARCHIVED + DEPLOYED** (коммиты **`470b63a`** (код+тесты+vendor, 36 файлов) + **`8d61926`** (планы: Merge §63 + архивация + Scanner-аудит) + **`dba76e8`** (deploy-doc); прод `/var/www/admin_bot` fast-forward `1a8ed18..8d61926`, `systemctl restart` active (Main PID 154704), `/api/health` **200**, `/healthz` **200** (`version 2.58.12`), `APP_VERSION` **2.58.11 → 2.58.12**, served `?v=2.58.12`, новые ассеты same-origin 200, `database is locked`=0; Merge — **§63**; архив — `plans/archive/hotfix9-shell-liquidglass-darkaurora-round1025/` + **ADR-1025-17** + `deployment.md` **VERIFIED**; @Reviewer **Approved** (итер.2; H-H9S-1/M-H9R-1/L-H9S-1..3 закрыты), @Scanner **C0/H0/M0/L0** (Info 3) → «к деплою ГОТОВО»; pytest **8291 passed / 0 failed** (база 8272), Playwright §12 **failures: 0** (10 вьюпортов × 5 режимов), прототип стекла **failures: 0** (`displacementScale=14.56`, `diffGlass=15.97`); **Δ DDL=0, Δ каталога=0**; техдолг **§63.11**). До неё закрыты: F0 (Wave 0), hotfix-media, F1, P0-fix (hotfix2), hotfix3, hotfix4, Волна 1 (F2+hotfix5+F3), Волна 1.5 (hotfix6), Волна 1.6 (hotfix7), Волна 2 (F4), Волна 3 (F5).
>
> **▶️ Следующая — F6 `memory-analytics-reorg-round1025`** (Волна 3; §4/§21–§30 Память↔Аналитика + ExecutionGraph; зависит от F1 ✅ и F4 ✅; Step 0 ✅, Step 1 @PM — следующий, немедленно, T-2839) → F7 → F11 → F9 → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. ⏳ Открыты live-гейты владельца: **T-2830** (hotfix9, PENDING OWNER VERIFICATION) + T-2776 (hotfix8), T-2742 (F5), T-2656 (F4), T-2682 (hotfix7), T-2617 (hotfix6), F2 T-2561, F3, hotfix5, F1 T-2409, hotfix-media T-2463/T-2472/T-2479, hotfix3 T-2505, hotfix4 T-2527. Детали — `plans/metrics.md` (**10.25-HOTFIX9**, 10.25-F5), `plans/MEMORY.md`.
>
> **Статус Волны 3 — F7 `permsoc-local-space-round1025` + F6 (обновлено @Memory, Step 10, 23.09.2026):** ✅ **F6 `memory-analytics-reorg-round1025`** — COMPLETED + MERGED + ARCHIVED + DEPLOYED (коммиты `02b99e9`/`cddacda`/`947191e`, `APP_VERSION` 2.58.14, Merge **§65**; архив + **ADR-1025-19** + **ADR-1025-19a**; pytest 8334/1/5-env, JS 37/37; техдолг §65.10). ✅ **F7 `permsoc-local-space-round1025`** — COMPLETED + MERGED + ARCHIVED + **DEPLOYED** (коммиты `6bf00e7`/`908f471`/`e2b452c`/`3bab70f`, `APP_VERSION` 2.58.14 → **2.58.15**, Merge **§66**, архив `plans/archive/permsoc-local-space-round1025/` + **ADR-1025-20** + `deployment.md` **VERIFIED**; @Reviewer Approved итер.3, @Scanner **C0/H0/M0/L3/I3** → «к деплою ДА»; F7 pytest 33, полный pytest **8374/0**, JS **38/38**, Playwright-матрица **failures: 0**; Δ DDL=0, Δ каталога=0 (459/418/434/98/96/21); health 200, `/healthz` 2.58.15, served `?v=2.58.15`, `database is locked`=0; техдолг **§66.8**). **▶️ Активная фича — F8 `parameter-registry-widget-map-round1025`** (обязательный аудит §1–§3/§117) → F11 → F9 → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. ⏳ Открыты live-гейты владельца: **T-2961** (F7) + T-2917 (F6), T-2862 (hotfix10), T-2830 (hotfix9), T-2776 (hotfix8), T-2742 (F5), T-2656 (F4), T-2682 (hotfix7), T-2617 (hotfix6), F2 T-2561, F3, hotfix5, F1 T-2409, hotfix-media T-2463/T-2472/T-2479, hotfix3 T-2505, hotfix4 T-2527. Детали — `plans/metrics.md` (**10.25-F7**, 10.25-F6), `plans/MEMORY.md`.
>
> **Статус Wave 0 — F8 `parameter-registry-widget-map-round1025` (обновлено @Memory, Step 10, 23.09.2026):** ✅ **COMPLETED + MERGED + ARCHIVED; deploy — NOT_APPLICABLE (обосновано, ADR-1025-21 D5)** (Шаг 7 Merge **§67** → Шаг 8 @PM архивация → Шаг 9 @DevOps NOT_APPLICABLE → Шаг 10 @Memory; T-2964…T-3023, **60 задач**; **ADR-1025-21**; архив `plans/archive/parameter-registry-widget-map-round1025/` + `deployment.md` **NOT_APPLICABLE**; @Reviewer **Approved** (3 Low + 1 Medium неблокирующие), @Scanner **C0/H0/M0/L3/I4 → «к приёмке ДА»**; полный pytest **8403/0** (+29), реестр **459**×23/0 пустых, дельта 411→459 = **48**, карта экранов «без места»=0, `config_snapshot_diff` 8 срезов/0 изменений, `--check` идемпотентен; **Δ DDL=0, Δ каталога=0** (459/418/434/98/96/21); **CSP/zero-build**; **`APP_VERSION` 2.58.15 без bump**; `tools/*` рантаймом не импортируются → рестарт/cache-bust не нужны; техдолг **§67.4** — Low 3 + Info 4; **PENDING OWNER VERIFICATION — T-3021** живой PG-снимок «до/после»). Merge-раздел `plans/ARCHITECTURE.md` **§67**. **▶️ Следующая — F9 `secrets-and-save-states-round1025`** (§50 + визуальный SaveBar §69/§78; зависит от F0/F4/F5 ✅) → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. Детали — `plans/metrics.md` (**10.25-F8**), `plans/MEMORY.md`.
>
> **Статус UI-слоя секретов — F9 `secrets-and-save-states-round1025` (обновлено @Memory, Step 10, 23.09.2026):** ✅ **COMPLETED + MERGED + ARCHIVED + DEPLOYED** (Шаг 7 Merge **§68** → Шаг 8 @PM архивация → Шаг 9 @DevOps deploy **VERIFIED** → Шаг 10 @Memory; T-3024…T-3062, **39 задач**; **ADR-1025-22**; архив `plans/archive/secrets-and-save-states-round1025/` + `deployment.md` **VERIFIED**; коммиты **`f5fbd5f`** (код+тесты, 31 файл) + **`c610c5f`** (планы, 15 файлов) + **`49c1ae1`** (deploy-doc); @Reviewer **Approved** итер.2 (H-F9S-1 + L-F9S-1..4 закрыты), @Scanner **C0/H0/M0/L0/I2 → «к деплою ДА»**; полный pytest **8421/0/1** (5 env `rich` вне scope), JS **40/40**, матрица **failures: 0**; **Δ DDL=0, Δ каталога=0** (459/418/434/98/96/21; 28 секретов = 20 UI + 8 env-only); CSP/zero-build; **`APP_VERSION` 2.58.15 → 2.58.16**; прод ff `908f471..c610c5f`, active, health 200, `/healthz` 2.58.16, served `?v=2.58.16`, `database is locked`=0; техдолг **§68.8** — I-F9S-1 + I-F9S-2 + док-ниты; **PENDING OWNER VERIFICATION — T-3059** реальный TMA/WebView). Merge-раздел `plans/ARCHITECTURE.md` **§68**. **▶️ Следующая — F11 `status-showcase-dashboard-round1025`** (§11–§21 композиция виджетов Статуса; §15 уже вынесено в hotfix6) → затем приёмка Эпика 1 (**F10** `epic1-verification-round1025`) → **Эпик 2** (10.26) → **Эпик 3**. Детали — `plans/metrics.md` (**10.25-F9**), `plans/MEMORY.md`.

---

## 2. Порядок и ступени

**Сквозной порядок (обновлён UPD: F0 — Wave 0 ДО F1; F11 перед F9):**
```
F0 ✅ ARCHIVED (Wave 0: точка отката + багфиксы сохранения §1–§6; `plans/archive/f0-config-bugfixes-round1025/`)
  └ внутри: T-2410 (откат) → T-2411 (репро) → F0.5 (T-2442…T-2455: database is locked, ПЕРВЫМ по приоритету) → F0.1 → F0.2 → F0.3 → F0.4 → T-2439…T-2441
  └ post-deploy gate (НЕ выполнен): T-2419 / T-2433 / T-2454 ──► F1 (только после критических фиксов F0)
F8 ✅ ARCHIVED (Wave 0 ∥ F0: read-only инвентарь/бэкап/baseline; реестр 459/дельта 48; deploy NOT_APPLICABLE) ──► читается F1
   └─► F1 (IA + shell + роутинг + kill-switch)  ── каркас всего
          ├─► F2 (Liquid Glass токены) ─┐
          ├─► F3 (селектор области) ────┴─► F4 (каталог + store) ─► F5 (workspace-табы)
          │                                                        ├─► F6 ✅ (память/аналитика) ─► F11 ▶️ (Статус-виджеты; следующая)
          │                                                        ├─► F7 (PERMsoc)
          │                                                        └─► F9 ✅ (секреты UI + SaveBar; DEPLOYED 2.58.16, §68)
   └─► F10 (приёмка Эпика 1 — gated, последняя: после F1…F9, F11)
```

**Ступени общих файлов (строго сериализовано):**
- `services/param_catalog.py`: **F1 (nav-метаданные) → F8 (реестр/карта) → F4/F5/F7**.
- `web/app.js`, `web/index.html`, `web/static/app.css`: **F0 → F1 → F2 → F3 → F4 → F5 → F6 → F7 → F11 → F9 → F10**.
- `config/settings.py`: F1 (`IA_V2_ENABLED`) → далее аддитивно по фичам.
- `web/api/routes.py`: **F0 (save/state-machine)** → F1 (`ui_flags` +1 bool) → далее аддитивно.
- `web/static/telegram-init.js`: **F1**.

Правило: фича более поздней ступени читает результат предыдущей и не переписывает её блоки.

---

## 3. F1 — ключевые архитектурные решения (детали в `spec.md` / `adr-1025-1-ia-v2.md`)

### 3.1. Новая IA (§4)
```
Публичные:   Статус (#/, стартовая) · Справка (#/how)
Админ:       Модули (#/modules) · ИИ (#/ai) · Память (#/memory) · Доступы (#/access)
Локальное:   PERMsoc (#/permsoc)

#/memory hub:  #/memory/rag · #/memory/lore · #/memory/relations
#/ai hub:      #/ai/llm · #/ai/prompts · #/ai/smart-cache · #/ai/names · #/ai/persona
#/modules:     #/modules/budgets · #/modules/images
#/access:      #/access/{roles,local,admins}
```
- Статус — единственная главная; отдельной «Обзор» нет.
- «Сводка» → «Аналитика» (**label**; канонический hash `#/oversight` сохранён), открывается из Статуса.
- «Память» — отдельный раздел; из «ИИ» уезжают `memory_rag`, `chat_lore`, `relations`.
- PERMsoc остаётся локальным.
- Legacy-алиасы: `#/ai/memory|/lore|/relations` → новые.

### 3.2. Backend nav-метаданные (Δ=0)
`services/param_catalog.py`: `NAV_MEMORY="memory"`, `NAV_TITLES["memory"]="Память"`, `NAV_ORDER=(modules,ai,memory,permsoc)`, `TAB_NAV`: 3 переноса в `memory`. `TAB_RULES`/`GROUPS`/`REGISTRY` не трогаются. `GET /api/access/param_permissions` группирует матрицу по новому `nav` автоматически.

### 3.3. Kill-switch
`IA_V2_ENABLED` env-only `ClassVar` (default **ON**), доставка `GET /api/me.ui_flags` (ADR-1024-13). OFF → legacy-константы `NAV_ITEMS`/`HUBS` + `.navbar-band` рендерятся как раньше (байт-в-байт). Legacy-константы сохраняются литерально.

### 3.4. Shell (§6/§7) и адаптивность (§70)
- ≥1200: sidebar ≈232 + header ≈64 + контент; формы 1200–1440.
- <768: компактный header, селектор области под заголовком (F3), одна колонка, `.bottom-nav` (админ: Статус/Модули/ИИ/Ещё; пользователь: Статус/Справка), «Ещё» (Справка/Память/Доступы/PERMsoc/Профиль); без 7-вкладочной полосы.
- 4 диапазона (320–767 / 768–991 / 992–1199 / ≥1200), `container queries`, без горизонтального скролла страницы, touch ≥44×44.
- TMA: `BackButton`, `viewportStableHeight`, `safeAreaInset`, `contentSafeAreaInset` (`telegram-init.js`).

### 3.5. Сохранность
Δ каталога=0 · Δ DDL=0 · API аддитивен · baseline-фикстура `sorted(pg_key)`/`{group_id: tab_id}` + тест равенства множеств (никакой параметр/группа не потеряны) · 100% покрытие «inventory ↔ IA-map» · OFF/ON-тест.

---

## 4. SUPERSEDE / REVISE карта

| Ранее | Действие | Причина |
|---|---|---|
| menu-freeze 10.20/10.21 (`test_frontend_tab_mapping`, `test_webapp_nav_disclosure_ui`, `test_round106_ia_smoke`, `NAV_ORDER`/`TAB_NAV`/`NAV_ITEMS`) | **SUPERSEDE → ADR-1025-1 D4** | ТЗ §4 задаёт новую IA; заморозка снимается |
| «navbar = ровно 6 пунктов» (7 тестовых файлов, см. F1 spec §3.5) | **SUPERSEDE** | Появление «Памяти» (7-й пункт) и sidebar |
| «sidebar запрещён» (10.6 A1) | **SUPERSEDE** | ТЗ §6 вводит desktop-sidebar ≥1200 |
| OD4 10.20 (`#161616`/`#14CBB6`) / 10.20-UPD3 orange | **SUPERSEDE → F2/ADR-1025-9** (палитра §8; AMEND ADR-1020-9) | ТЗ §8/§9/§10 |
| 10.24 F6 `prompts-refactor-accordion-modes` | **REVISE → F5 (workspace-табы §48/§69)** | Аккордеоны как основная навигация запрещены |
| «Сводка» (label 10.8) | **RENAME → «Аналитика»** | ТЗ §4/§21 |
| Persistence/409/412/state-machine сохранения в F9 (исходная декомпозиция) | **MOVE → F0 (Wave 0)**; F9 сужена до UI-секретов + визуального SaveBar | UPD §2/§6: неисправное сохранение нельзя переносить в новые компоненты |
| `ADR-1024-18` (устойчивость `smart_cache` к `database is locked`, 10.24 F17 `sqlite-lock-resilience-round1024`) | **AMEND/EXTEND → F0.5 / ADR-1025-5** — тот же контракт (PRAGMA-паритет WAL/`busy_timeout=5000`/`synchronous=NORMAL`; bounded retry **только на `locked`** `_LOCK_RETRIES=3`/backoff 0.1/0.2/0.4с; явный `event=*_lock_exhausted` + счётчик; fail-open последним рубежом; env-only kill-switch) на `services/database.py` (`write_transaction`: single-writer `self._lock` + `commit_if` + rollback на `BaseException`/`CancelledError`) + `summary_memory.py` + `persistent_throttling.py` + `direct_chat_service.py` | прод-логи 20.09.2026: 6 стеков `database is locked` (chat_id -1002661910336); тот же класс дефекта вне зоны прошлого фикса; `smart_cache` **не дублируется**. ✅ реализовано/принято |
| `ADR-1012-1`/`ADR-1024-21` (per-chat save-path, merge `overrides`/`perm_overrides`) | **AMEND → F0.1/F0.2 / ADR-1025-2** — serialize мутаций по `chat_id` (`asyncio.Lock` + `pg_advisory_xact_lock`), idempotent short-circuit `revalidated:true`, честный 409 `conflicting[]`, единый `persistItems`, атомарный global `ConfigCache.set_many` + per-key optimistic | одно действие порождало 2 мутации с одним токеном → ложный 409 + три противоречивых тоста. ✅ реализовано/принято; merge-контракт F20 сохранён |
| `ADR-1023-4 D2`/`ADR-1024-3` (лимит анти-клише) | **AMEND → F0.3 / ADR-1025-3** — разведены «вместимость БД» (`limits.anticliche_max_patterns`) и «размер партии» (`ANTICLICHE_MAX_PATTERNS_PER_RUN`); bounded-пополнение (`ANTICLICHE_MAX_ROUNDS` + `worker_budget`); дедуп против БД; «0 новых» ≠ `llm_error`; ключ global-only | conflation семантик → усечённый JSON/«20 вместо 200» + ложная «ошибка модели». ✅ реализовано/принято |
| 10.8/10.20 save-UI (SaveBar/тосты) | **AMEND → F0.4 / ADR-1025-4** — один итог на операцию (`notify(operationId,result)`, `err>warn>ok`, очередь ≤3, safe-area, per-field ошибки, `saveState` в sticky-save) | запрет противоречивых/перекрывающих уведомлений (§5 ТЗ). ✅ реализовано/принято |
| `physical-two-call-pipeline` (инвариант «ровно 2 LLM-вызова», 10.22) | **AMEND (Эпик 3, Step 2)** — `action`-решение не добавляет **третий** LLM-вызов | UPD §13/§38 |
| `response_mode` = стиль Вербализатора (ADR-1023-3) | **AMEND (Эпик 3, Step 2)** — разделить `action` {reply/react/silent/tool} и `style` | UPD §38/§39 |

---

## 5. Инварианты раунда (нарушать нельзя)

1. **Сохранность 100%:** все разделы/маршруты/параметры/значения/виджеты/права/PERMsoc/промпты/модели/ключи/лор/отношения — доступны после рефакторинга (§1/§79/§116).
2. **Δ каталога = 0, Δ DDL = 0** (общий итог Эпика 1).
3. **Технические ключи и смысл `null/0/-1/""`** не меняются; локальное не перезаписывается глобальным; никаких новых дефолтов при открытии формы.
4. **RBAC-семантика** не меняется; права проверяются на сервере.
5. **CSP/zero-build:** только self-host, без inline-скриптов/стилей, без vue-router и новых state-библиотек (Vue 3 global).
6. **Логи остаются на Статусе** (§20); виджеты Статуса не удаляются.
7. **PERMsoc локальный**; не переносится в глобальные настройки.
8. **Порядок роутеров `bot.py`** не сдвигается.
9. **OFF-совместимость:** все env-only kill-switch’и default ON; OFF возвращает прежнее поведение.
10. **`plans/current_task.md` не коммитить**, секреты не цитировать (R17/R18).
11. **F0 — первым (Wave 0):** неисправный механизм сохранения не переносится в F1+; точка отката — первая задача (**T-2410**).
12. **F0.5 — без тихой потери записи:** retry **ограничен** (только `locked`); fail-open/фоллбэк — **последний** рубеж с обязательным структурированным `event=*_lock_exhausted` + счётчиком; **Δ DDL = 0**; `smart_cache` из ADR-1024-18 **не переписывается** — только расширение контракта на другие сервисы; OFF kill-switch `DB_LOCK_RESILIENCE_ENABLED` = baseline.

---

## 6. Риски раунда и стратегия приёмки

| Риск | Ур. | Снятие |
|---|---|---|
| «Объявлено готово, но визуально провалено» (10.20-UI-rework, 10.22 F2) | High | Реальная Chromium/Playwright-проверка §71 (F10), `scrollWidth`, `getBoundingClientRect`, скриншоты; запрет закрытия по отчёту |
| Потеря параметра/экрана при переносе IA | Critical | Δ=0 + baseline-фикстура + авто-тест «inventory ↔ IA-map» (F1/F8/F10) |
| SUPERSEDE маркер-тестов без атомарности | High | Код+эталоны в одном коммите; новый inventory-тест сравнивает множества, а не размеры |
| Мобильный скролл/обрезание переключателей | High | §70 + `container queries` + Playwright на 320/390/768/992/1200/1440+ |
| Декларативные kill-switch’и | Medium | Тесты OFF/ON для каждого флага |
| Конфликты ступеней общих файлов | Medium | Строгая сериализация **F0 → F1 → F2 → F3 → F4 → F5 → F6 → F7 → F11 → F9 → F10** |
| Неисправное сохранение перенесено в новые компоненты (F1+) | Critical | **F0 Wave 0** закрывается до F1; критерии §6 (10 пунктов) + точка отката T-2410 |
| Прод-потеря записи из-за `database is locked` (память/ответы/throttling) | Critical | **F0.5** до приёмки F0: диагностика первопричины (T-2443), bounded retry только на `locked` + сериализация (T-2445/T-2446), явный лог+счётчик (T-2448), live-приёмка (T-2454); **расширение ADR-1024-18**, не «лечение по симптому» |
| Долгий retry подвешивает hot-path/хендлер | High | F0.5: попытки ограничены, fail-open последним рубежом, тесты (b)/(c)/(g) T-2452 |

**Приёмка Эпика 1 (F10):** JS-гейты (`node --check`, `routing_test.js`, `vue_mount_test.js`) + полный `pytest` без регрессий к **7976/0** (после хотфикса; база F0 — 7946/0) + Playwright-матрица §71 + сверка конфигурации до/после + отчётные карты (§117).

---

## 7. Артефакты Step 2 (@Architect)

- **F0** (Wave 0, ✅ COMPLETED + MERGED + **ARCHIVED** → `plans/archive/f0-config-bugfixes-round1025/`): `spec.md` + `tasks.md` (T-2410…T-2455); ADR: **`adr-1025-2-save-state-machine.md`** (F0.1/F0.2), **`adr-1025-3-anticliche-semantics.md`** (F0.3), **`adr-1025-4-toasts-savebar.md`** (F0.4), **`adr-1025-5-db-lock-resilience.md`** (F0.5 — **AMEND/EXTEND `ADR-1024-18`**). Интеграция в глобальную архитектуру — `plans/ARCHITECTURE.md` **§52** (+ §9/§10/§49/§51).
- **F1** (✅ COMPLETED + MERGED + DEPLOYED + **ARCHIVED**): `plans/archive/ia-shell-navigation-round1025/{spec.md, adr-1025-1-ia-v2.md, tasks.md}` (`ff34115`,`b1c87b0`,`78e612a`; `plans/ARCHITECTURE.md` §54). ⏳ live-гейт владельца: T-2409.
- **P0-фикс после F1** (✅ COMPLETED + MERGED + DEPLOYED + **ARCHIVED**): `plans/archive/p0-fix-render-media-paths-round1025/tasks.md` (FIX 1–4; `fea2daa`; `plans/ARCHITECTURE.md` §54.1). ⏳ live-гейт владельца: реальные видео/ГС/аватары + разделы TMA.
- **ASAP-хотфикс media/TMA** (✅ COMPLETED + MERGED + DEPLOYED + **ARCHIVED**): `plans/archive/hotfix-media-tma-round1025/{spec.md, tasks.md (T-2456…T-2481), adr-1025-6-bot-api-local-mode.md}`. ⏳ live-гейт владельца: T-2463/T-2472/T-2479. Интеграция — `plans/ARCHITECTURE.md` **§53**.
- `plans/round1025-architecture.md` (этот файл; PM-аннотация по Wave 0/F0 — Step 1, детальная архитектура — Step 2).
- **Эпик 3** (раунд 10.26+): `spec.md`/ADR — Step 2 @Architect при старте Эпика 3 (в т.ч. AMEND `physical-two-call-pipeline`).

## 8. Ссылки

- Мастер-ТЗ: `plans/current_task.md` (§0–§7, §68, §70, §71, §79, §116, §117) + **блок UPD** (строки 3718–5918: F0 §1–§6, Human Gate §7–§10, Эпик 3 §11–§54) — **untracked, не коммитить**, секреты не цитировать.
- **F0** (Wave 0, ✅ **ARCHIVED**): `plans/archive/f0-config-bugfixes-round1025/tasks.md` (T-2410…T-2455; F0.5 — T-2442…T-2455). **F0.5-прецедент:** `plans/archive/sqlite-lock-resilience-round1024/{ADR-1024-18.md,tasks.md}`; `services/memory_rebuild.py:69-72,92-111`; `services/database.py:514-520,589-594`; `services/llm_client.py:604` (тест-хук backoff).
- F1 (✅ **ARCHIVED**): `plans/archive/ia-shell-navigation-round1025/{tasks.md,spec.md,adr-1025-1-ia-v2.md}`
- **P0-фикс после F1** (✅ **ARCHIVED**): `plans/archive/p0-fix-render-media-paths-round1025/tasks.md`
- F8 (Wave 0): `plans/features/parameter-registry-widget-map-round1025/`
- Прочие фичи: `plans/features/<name>-round1025/`
- Отчёты: `plans/reports/round1024_scanner_audit.md`, `round1023_scanner_audit.md`, `round1020_ui_rework_scanner_audit.md`, `round1020_ui_rework_reviewer.md`
- **F0-отчёты (Merge):** `plans/reports/f0-round1025-report.md` (§54), `f0-save-audit-round1025.md` (аудит 14 механизмов), `f0-5-db-lock-round1025.md` (карта соединений/первопричина DB-lock), `round1025_f0_scanner_audit.md` (§1–§4 аудит + §5 повторный аудит), `global_map.md`/`full_audit_results.md` (снимок @Scanner)
- **Хотфикс-отчёты (Merge):** `plans/reports/round1025_hotfix_scanner_audit.md` (Critical 0/High 0; M-1/M-2 → техдолг), `global_map.md`/`full_audit_results.md` (снимок @Scanner); `plans/ARCHITECTURE.md` §53
- **F1-отчёты (Merge/Deploy):** `plans/reports/round1025_f1_scanner_audit.md` (0 Critical; H-1 + 2 Medium закрыты), `plans/ARCHITECTURE.md` §54
- **P0-фикс hotfix2:** `plans/reports/round1025_hotfix2_scanner_audit.md` (0 Critical/0 High; M-1/M-2 → техдолг), `plans/ARCHITECTURE.md` §54.1; тест `tests/test_media_local_path_round1025.py`
- Архив-образцы: `plans/archive/round1024-architecture.md`, `plans/archive/round1023-architecture.md`
- Канон: `plans/ARCHITECTURE.md`, `plans/project.md`, `plans/docs/canon/architecture.md`
