# Аудит остатка ТЗ `plans/current_task.md` — раунд 10.25 (HOTFIX7 / UPD п.7)

> **Источник:** `plans/current_task.md` (MASTER SPECIFICATION v6.0, untracked — не коммитить/не изменять; R17/R18). **Триггер:** UPD «Срочный фикс текущего фронта», строки **6073–6154**, пункт **7** («выполнить аудит current_task.md; найти все невыполненные задачи; продолжить по приоритетам»).
> **Автор:** @PM (Step 1), 22.09.2026. **Опора:** Step 0 @Memory (`plans/workflow_state.md`, `plans/MEMORY.md`), реестр фич `plans/backlog.md`, `plans/ARCHITECTURE.md` §52–§59.
> **Статус:** `plans/current_task.md` **не изменялся**. Закрытые пункты не помечаются как открытые и наоборот; ничего не удаляется.
> **Обновление Шага 8 (@PM, 22.09.2026):** HOTFIX7 — ✅ **COMPLETED + MERGED + ARCHIVED** (Merge `plans/ARCHITECTURE.md` **§59**; архив `plans/archive/hotfix7-shell-glass-heartbeat-round1025/`); открыты только **T-2690 (deploy, Шаг 9 @DevOps)** и **T-2682 (live-гейт владельца)**. Разделы §1–§8 актуализированы; **§9 — итоговый отчёт UPD-7 (три обязательных блока, пригоден для цитирования оркестратором).**

## 1. Что уже закрыто (по этому ТЗ)

| Блок ТЗ | Пакет | Статус | Артефакт / интеграция |
|---|---|---|---|
| §1–§6 UPD (багфиксы сохранения/409/анти-клише/тосты + `database is locked`) | **F0** `f0-config-bugfixes-round1025` | ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (`3a91c84`) | `plans/archive/f0-config-bugfixes-round1025/`, ADR-1025-2/3/4/5, ARCHITECTURE §52 |
| §4–§7/§68/§70 IA+shell | **F1** `ia-shell-navigation-round1025` | ✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED (`fe0f7bb`) | `plans/archive/ia-shell-navigation-round1025/`, ADR-1025-1, §54 |
| ASAP-медиа/transcribe/cache-bust (внеплановый) | **hotfix-media-tma-round1025** | ✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED | `plans/archive/hotfix-media-tma-round1025/`, ADR-1025-6, §53 |
| P0 render/media/avatars после F1 | **p0-fix-render-media-paths-round1025** (hotfix2) | ✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED (`fea2daa`) | `plans/archive/p0-fix-render-media-paths-round1025/`, §54.1 |
| Саммари-обложка / STT-сжатие / анти-клише-честность / LLM-таймауты | **hotfix3** | ✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED (`cfe7342`) | `plans/archive/hotfix3-summary-stt-anticliche-round1025/`, ADR-1025-7, §55 |
| Обложка-стиль / нижняя панель mobile / порядок навигации | **hotfix4** | ✅ COMPLETED + MERGED + DEPLOYED + ARCHIVED (`f2328fb`) | `plans/archive/hotfix4-cover-nav-shell-round1025/`, ADR-1025-8, §56 |
| Окно/ретраи обложки, image-бюджет | **hotfix5** (пакет Волны 1) | ✅ COMPLETED + MERGED + ARCHIVED; deploy `4cde1bc` (2.58.6) | `plans/archive/hotfix5-summary-cover-window-round1025/`, ADR-1025-11, §57.2 |
| §8–§10 токены/фон/AA | **F2** `design-tokens-liquidglass-v2-round1025` | ✅ COMPLETED + MERGED + ARCHIVED; deploy 2.58.6 | `plans/archive/design-tokens-liquidglass-v2-round1025/`, ADR-1025-9, §57.1 |
| §5/§14/§42/§43/§74 селектор области | **F3** `global-scope-selector-round1025` | ✅ COMPLETED + MERGED + ARCHIVED; deploy 2.58.6 | `plans/archive/global-scope-selector-round1025/`, ADR-1025-10, §57.3 |
| §9 glass/линза, §15 сердцебиение (Canvas 2D), нижняя панель, шапка | **hotfix6** (Волна 1.5) | ✅ COMPLETED + MERGED + ARCHIVED + DEPLOYED (`ba75751`, 2.58.7) | `plans/archive/hotfix6-webview-shell-heartbeat-round1025/`, ADR-1025-12, §58 |
| **UPD 1–6** (layout/fullscreen/glass/heartbeat/приёмка) | **HOTFIX7** `hotfix7-shell-glass-heartbeat-round1025` | ✅ **COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026; Merge §59); ⏳ deploy — Шаг 9 @DevOps; ⏳ live-гейт T-2682** (T-2658…T-2694) | `plans/archive/hotfix7-shell-glass-heartbeat-round1025/` (`spec.md` + ADR-1025-13 + `tasks.md` + `evidence.md` + `review.md`), ARCHITECTURE §59, `plans/reports/round1025_hotfix7_{scanner_audit,contrast,ui_report}.md` |
| **§15 «живое сердцебиение»** (исходно в F11) | вынесено в **hotfix6**, перерабатывается в **HOTFIX7** (UPD 2) | §15 SUPERSEDE/вынесено; в HOTFIX7 — премиальный визуал | ADR-1025-12 D4 (§58.6), ADR-1025-13 (ожидается) |
| §2 (реестр параметров), §3 (сохранность конфигурации), §117(1–4) | **F8** `parameter-registry-widget-map-round1025` | ⚠️ **не завершён** (см. §2 ниже) — частично покрыт аудитами F0 | `plans/features/parameter-registry-widget-map-round1025/tasks.md` (заготовка) |

## 2. Что осталось (открытые фичи Эпика 1)

| # | Фича | ТЗ | Статус | Комментарий |
|---|---|---|---|---|
| **F4** | `module-catalog-quickpanel-store-round1025` | §31–§45, §72, §73, §79, §116 | ⏸ **PAUSED** (Step 0–1 done; `tasks.md` T-2619…T-2657, 39) | Возврат **после** HOTFIX7 (UPD вышел приоритетнее). `spec.md`/ADR-1025-13 — Step 2 @Architect НЕ начат |
| **F5** | `module-workspace-tabs-round1025` | §46–§49, §84, §85 | 🟦 заготовка Step 1 (детализация при старте) | Зависит от F4 |
| **F6** | `memory-analytics-reorg-round1025` | §4, §21–§30, §52–§59, §75, §76 | 🟦 заготовка Step 1 | Зависит от F1, F4; адаптер ExecutionGraph (не дублировать) |
| **F7** | `permsoc-local-space-round1025` | §60–§67 | 🟦 заготовка Step 1 | Зависит от F3, F4; мастер-тумблеры + серверная поддержка отключения |
| **F8** | `parameter-registry-widget-map-round1025` | §1–§3, §117 | 🟦 заготовка Step 1 (Wave 0 enabler) | Обязательный аудит §2 + карта виджетов + бэкап/diff; **не завершён** |
| **F9** | `secrets-and-save-states-round1025` | §50, §51, §69, §78 | 🟦 заготовка Step 1 (сужена) | Только UI-слой секретов + визуальный SaveBar; серверный persistence закрыт в F0 |
| **F10** | `epic1-verification-round1025` | §71–§79, §114, §116, §117 | 🟦 заготовка Step 1 (gate) | Завершает Эпик 1; Playwright 10 размеров + критерии §6 F0 |
| **F11** | `status-showcase-dashboard-round1025` | §11–§21, §70, §77 | 🟦 заготовка Step 1; **§15 вынесено** | Зависит от F1, F2, F6; §15 повторно не реализовывать (§58.6) |

## 3. Что осталось: Эпик 2 «Summary Hybrid Pipeline» (§80–§115) — НЕ начат

Старт **только после приёмки Эпика 1** (§0/§79). 10 фич **S1–S10** (`plans/backlog.md`): S1 фильтр → S2 восстановление контекста → S3 L1 Кластеризатор → S4 пакет фактов → S5 L2 Писатель/форматтер → [S6 публикация ∥ S9 UI-тестирование] → S7 логирование/run_id → S8 adapter ExecutionGraph → S10 deploy. Канон-цепочка S3→S4→S5→S6 атомарна (ADR-1013-3). `generate_image`/`sendRichMessage` — reuse, не переписывать.

## 4. Что осталось: Эпик 3 «Agentic Intelligence» (§11–§54 UPD) — НЕ начат

Старт **только после приёмки Эпиков 1 и 2**. 11 фич **A0–A10**: A0 аудит (read-only Wave 0) → A1 координатор → A2 последовательные tool calls → [A3 ImageRequest → A5 дневной лимит] ∥ A6 `get_user_context` → A4 генерация из досье/RAG → A7 Decision Making → A8 реакции Telegram → A9 события/ExecutionGraph → A10 верификация (22 сценария §52). Инвариант: `action` **не добавляет третий LLM-вызов** (AMEND `physical-two-call-pipeline`); новых агентов/фреймворков не создавать.

## 5. Внеплановый бэклог и старые активные фичи (вне Эпиков 1–3)

Из `plans/features/` (активны, не в архиве), с преемственностью к текущему ТЗ:

- **`post-deploy-admin-minors`** (F-1: T-648 атомарный POST /api/config, T-651/652 касты) — открыт; порядок F-1 ДО B/G-фич раунда 10.4.
- **`config-read-path-audit`** (F-5: аудит `settings.X` vs `hot.get`) — открыт; **после** G/B (новые read-пути F-14/F-15).
- **`frontend-admin-bugfixes`** (F-4 «сверка синхронизации разделов») — открыт; применять к текущей карте вкладок.
- **`scam-incident-security-followup`** (F-3: T-663 DM-гейт `/mimic /deadpage /alangreet`) — открыт; после F-14.
- **`user-aliases-admin`** (F-6: аудит каскада, «реальный эффект», верификация, регресс) — **SUPERSEDED_BY(round10.4)**; папку/спеку не трогать.
- **`admin-debug-webview`** (F-2: страница `/debug_config`) — открыт, независим.
- **Техдолг Scanner** (`plans/reports/full_audit_results.md`): HIGH-001/002/003/005/006/007/008, MED-* — вне скоупа текущих раундов; кандидат на отдельный дефект-эпик. HIGH-004 (полный LLM-лог) — частично закрыт в F-15, полностью отложен.
- **Epic 86 (GraphRAG→PG)** — ОТМЕНЁН/ЗАМОРОЖЕН (решение владельца 04.09.2026).
- **Epic «Улучшения фактчека»** — не начат (4 рекомендации, `docs/factcheck-audit.md`).
- **RESEARCH_HUMAN (отложено):** per-bot throttle, wallet на чат, triage-гейт, TTS, мемы — не активны.

## 6. Открытые live-гейты владельца (не блокеры, но требуют человека)

| Пакет | Live-гейт |
|---|---|
| HOTFIX7 | **T-2682** — mobile fullscreen inside Telegram WebView (heartbeat/header/glass/sidebar) |
| hotfix6 | **T-2617** — реальный WebView (линза/perf, heartbeat) |
| F2 | **T-2561** — палитра/glass/фон AA |
| F3 | live-приёмка селектора области |
| hotfix5 | live-проверка окна/ретраев обложки |
| F1 | **T-2409** — очистка бэкапа (ручная) |
| hotfix-media | **T-2463** (видео >20 МБ), **T-2472** (консоль TMA), **T-2479** |
| P0-fix / hotfix3 / hotfix4 | **T-2505** (обложка/STT/анти-клише), **T-2527** (обложка-стиль/панель/порядок) |

## 7. Рекомендуемый порядок продолжения (по приоритетам)

1. **HOTFIX7 (UPD 1–6)** — ✅ **выполнен, заархивирован (Шаг 8 @PM) и смёржен (§59);** остались только **deploy (Шаг 9 @DevOps, T-2690)** и **live-гейт владельца T-2682**. *(T-2658…T-2694)*
2. **UPD 7 — этот аудит + продолжение без human gate:** после deploy **возобновить F4** (Step 2 @Architect → build) как ближайшую actionable фичу Эпика 1.
3. **F4 → F5 → F6 → F7 → F11 → F9 → F10** (единый порядок Эпика 1), параллельно закрывать открытые live-гейты владельца.
4. **СТОП-ГЕЙТ Эпика 1** (F10 + приёмка владельцем) → **Эпик 2 (S1–S10)** → **Эпик 3 (A0–A10)**.
5. Отдельной полосой — старые открытые фичи (F-1…F-6) и техдолг Scanner, не блокируя Эпик 1.

## 8. Что взято следующим в работу (UPD 7, п.3)

- **Немедленно:** **deploy HOTFIX7 (Шаг 9 @DevOps, T-2690)** — код/тесты/отчёты в рабочем дереве, **не закоммичены**; коммит/push → прод → restart → health 200/`database is locked`=0/`APP_VERSION` 2.58.8 → `deployment.md` в архиве.
- **Следом (без human gate):** возобновление **F4** `module-catalog-quickpanel-store-round1025` — **Step 2 @Architect** (`spec.md` + новый ADR; ⚠️ `ADR-1025-13` занят HOTFIX7 → брать следующий свободный `ADR-1025-14`) и реализация (T-2619…T-2657), т.к. это следующий P0-блок Эпика 1 и от него зависят F5/F6/F7/F9.
- **Параллельно:** держать открытыми live-гейты владельца; не начинать Эпик 2 до приёмки Эпика 1.

---

## 9. Итоговый отчёт UPD-7 (обязательные три блока)

> **Источник:** UPD «Срочный фикс текущего фронта», `plans/current_task.md` п.7 (строки 6138–6154). **Автор:** @PM, Шаг 8 (T-2693), 22.09.2026. Формулировки пригодны для дословного цитирования оркестратором в финальном отчёте.

### 9.1. Что исправлено по UI-фиксам (HOTFIX7, UPD 1–6)

| UPD | Что исправлено (факт) | Доказательство |
|---|---|---|
| **UPD 1** — layout/fullscreen | Единый источник высоты **`--shell-h`**: базовое `100vh` + апгрейд `min(100dvh, var(--tg-viewport-stable-height))` **только внутри** `@supports`; два явных режима **normal** (`min-height/height:auto/overflow:visible`) и **fullscreen** (`height:max-height:var(--shell-h); min-height:0; overflow:hidden`) без конкурирующих высот; зафиксирован z-index/stacking; **виджет «Сердцебиение» гарантированно виден в fullscreen** (`.hb-wrap`/`.hb-canvas` не схлопываются, min-height 56 px). | §59.1; матрица: `appShell.h == innerH` (вне Telegram) / `= stable` (mobile), `hbVisible=true` во всех режимах; `f2ShellH`-эмуляция старого WebView |
| **UPD 2** — heartbeat premium | «Линия + плавающая точка» **удалена** (`pulseX` устранён): реалистичный кардиокомплекс **P/Q/R/S/T** (сумма гауссан) + **sweep-wipe**; цвет/интенсивность от **реальных метрик** и статус-токенов (HEALTHY `--ok` green, WARNING `--warn` amber, CRITICAL `--err` red-pink, UNKNOWN muted без свечения); **glow-лестница** `.45/.60/.85/0` и `shadowBlur ×0.9/1.1/1.5/0`; стек переиспользован — **Canvas 2D + rAF** (без WebGL, без нового поллера); reduced-motion — статичный корректный кадр; семантика `_heartbeatTransition`/`heartbeatSample`/EMA/гистерезис/dwell/«без выдуманного BPM» не менялась. | §59.2; `evidence.md` (Round 2, F-3/F-4); `review.md`; `round1025_hotfix7_scanner_audit.md` §7 |
| **UPD 3** — glass shell отдельным слоем | Введены отдельные **серо-графитовые `--shell-*`** (`--shell-bg rgba(33,37,45,.62)`, `--shell-bg-strong rgba(24,28,35,.90)` для header), **отличные от карточных** `--glass-*`; shell-панели (sidebar/drawer/header/bottom-nav/more-sheet) выглядят единым слоем и отделены от карточек по тону и глубине. | §59.3; computed `--shell-bg ≠ --glass-bg`, shell-панели ≠ карточкам (матрица) |
| **UPD 4** — liquid glass качество | 6-составной рецепт (полупрозрачный серо-графитовый base + `backdrop-filter: blur(...)` (**не** `url`) + две мягкие inset-подсветки + тонкая светлая обводка + слабый specular + аккуратная faux-noise текстура); **«грязь» снята** (`--glass-shadow` α `.75→.55`; `body::before` opacity `.42→.30`, reduced-motion `.35→.26`); карточкам — отдельная `--card-shadow`; **AA ≥ 4.5:1** подтверждён (6.46 / 4.73 / 15.26 / 11.29); палитра §8 и механика фона §10 **не менялись**. | §59.4; `round1025_hotfix7_contrast.md`; независимый recompute @Scanner |
| **UPD 5** — shell-выравнивание | Header без наезда на контент/нативные кнопки; `--header-h` (ResizeObserver) — единственный источник резерва (`scroll-padding-top`); переполнение — `ellipsis`/перенос без горизонтального скролла; sidebar/topbar — цельные shell-элементы; mobile: `env(safe-area-inset-*)` + `--tg-*`, `viewport-fit=cover`, `computeBottomOffset()` = **max** трёх инсетов (ADR-1025-12 D3 сохранён), fullscreen-sync ADR-1024-24 сохранён. | §59.4; матрица (`rect.bottom ≤ innerHeight`) |
| **UPD 6** — обязательная проверка | Playwright-матрица **5 логических режимов × 10 вьюпортов × normal/fullscreen**: desktop normal, desktop fullscreen, tablet, mobile regular, mobile fullscreen — **failures: 0**. Проверено: heartbeat виден везде; header не ломается; glass качественный (`backdrop-filter ≠ none`); sidebar/topbar серые и отделены; ничего не съезжает; `backdrop-filter: url(` = 0. | `round1025_hotfix7_ui_report.md`, §59.5 |

**Дополнительно (сопутствующее):** `APP_VERSION` **2.58.7 → 2.58.8** (+cache-bust `?v=`); три **env-only** флага soft-отката (`UI_SHELL_GLASS_V2` / `UI_HEARTBEAT_PREMIUM` / `UI_SHELL_LAYOUT_V2`, default ON, Δ каталога = 0); инварианты соблюдены — **Δ DDL = 0**, **Δ каталога = 0** (459/98/96/21/418), CSP/zero-build, запрет WebGL; регресс — pytest **8207/0**, JS **27/27**; @Reviewer **Approved** (итер.2), @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 3** («к деплою ДА»).

**Осталось по HOTFIX7:** только **deploy (T-2690, Шаг 9 @DevOps)** и **live-гейт владельца T-2682** (реальный Telegram WebView + FPS). Техдолг — §59.8 (L-H7-1/-2/-3 + Info), не блокеры.

### 9.2. Какие пункты `current_task.md` ещё оставались

- **Эпик 1:** **F4** ⏸ PAUSED (ближайшая), **F5, F6, F7, F9, F11** — заготовки Step 1; **F8** (обязательный аудит §1–§3 + карта виджетов §117) — **не завершён**; **F10** — финальный гейт приёмки Эпика 1.
- **Эпик 2 «Summary Hybrid Pipeline» (§80–§115):** **S1–S10 — не начат** (старт только после приёмки Эпика 1, §0/§79).
- **Эпик 3 «Agentic Intelligence»:** **A0–A10 — не начат** (старт только после Эпиков 1 и 2).
- **Внеплановый бэклог** (вне Эпиков): `post-deploy-admin-minors` (F-1), `config-read-path-audit` (F-5), `frontend-admin-bugfixes` (F-4), `scam-incident-security-followup` (F-3), `admin-debug-webview` (F-2); техдолг @Scanner (HIGH-001…008, MED-*) — кандидат на отдельный дефект-эпик.
- **§15 «живое сердцебиение»** больше **не остаётся**: реализовано в hotfix6 и доработано в HOTFIX7 (UPD 2).
- **Живые гейты владельца (не код, требуют человека):** **T-2682** (HOTFIX7) + T-2617 (hotfix6), T-2561 (F2), live-приёмка F3, live-проверка hotfix5, T-2409 (F1), T-2463/T-2472/T-2479 (hotfix-media), T-2505 (hotfix3), T-2527 (hotfix4).

### 9.3. Что взято следующим в работу

1. **Немедленно — deploy HOTFIX7 (Шаг 9 @DevOps, T-2690):** коммит/push origin/master → прод `/var/www/admin_bot` → `systemctl restart admin_bot` → `/api/health`=200, `database is locked`=0, `APP_VERSION`=2.58.8; заполнить `deployment.md` (VERIFIED) в архиве; live-гейт **T-2682** остаётся за владельцем.
2. **Следом — возобновление F4** `module-catalog-quickpanel-store-round1025` (Step 2 @Architect: `spec.md` + **ADR-1025-14** → build → ревью → аудит) — следующий P0-блок Эпика 1, от него зависят F5/F6/F7/F9.
3. **Далее — единый порядок Эпика 1:** `F4 → F5 → F6 → F7 → F11 → F9 → F10` → **СТОП-ГЕЙТ Эпика 1** (приёмка владельцем) → **Эпик 2 (S1–S10)** → **Эпик 3 (A0–A10)**. Живые гейты владельца закрываются параллельно и старт F4 не блокируют (UPD 7 п.7 — «без human gate»).

> **✂️ Цитата для финального отчёта (кратко):** «Пакет HOTFIX7 (`hotfix7-shell-glass-heartbeat-round1025`, T-2658…T-2694) **завершён, смёржен (§59) и заархивирован**: исправлены все шесть UI-пунктов UPD — стабильная геометрия shell и видимость сердцебиения в fullscreen, премиальный ECG-виджет на реальных метриках вместо «линии с точкой», отдельный серо-графитовый glass-shell, полноценное liquid glass без „грязи“ при AA ≥ 4.5:1, выравнивание header/mobile; автоматическая приёмка (Playwright, 5 режимов × 10 вьюпортов) — **0 FAIL**, ревью Approved, аудит **Critical 0 / High 0 / Medium 0**, pytest **8207/0**, JS **27/27**, Δ DDL = Δ каталога = 0. Осталось: **deploy (Шаг 9 @DevOps)** и **живой гейт владельца T-2682**. По остатку ТЗ следующим возвращается **F4** (`module-catalog-quickpanel-store-round1025`, Step 2 @Architect → build), затем F5–F11, Эпик 2 и Эпик 3.»
