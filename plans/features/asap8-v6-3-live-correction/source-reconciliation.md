# source-reconciliation — ASAP 8 v6.3 Live Correction ↔ legacy v6/v6.1/v6.2

- Дата: 15.10.2026. Автор: PM-1.
- Канонический источник: `source-lines-37423-EOF.md` (451 строка, sha256 `d0b4f611…`).
- Проверенная точка: HEAD/master = `f58a644` = deployed **2.58.78** (коммит f58a644: «v6 deployed 2.58.78»). Первоисточник статусов: `plans/features/asap8-v6-remediation/f10-report.md` (26 ID) + волновые отчёты той же фичи.
- Правило приоритета (строка 11 снапшота): при конфликте v6.3 **старше** v6.1/v6.2; ниже в колонке «v6.3» указано, что именно уточнено/заменено.
- **Числа F\* старого плана NOT ID**: F1–F9 были номерами задач запуска v6 и не совпадают с C/D-требованиями; в этой карте не используются.
- Внимание: параллельный лен CLEAN-1 перемещает старые каталоги `plans/` в `plans/archive/`; статусы ниже привязаны к f10-report.md (содержание, а не путь).

## 1. Легенда статуса на HEAD (f58a644 / 2.58.78)

- **сделано** — код в master + тесты + ревью волны пройдены (f10); live/owner-проба могла остаться pending (см. остаток).
- **частично** — основная поверхность закрыта, но есть явный остаток (f10 §4 или live-проба).
- **нет** — на HEAD не реализовано.
- VERIFIED_LIVE на HEAD не заявлен ни для одного ID (f10: деплой 2.58.78 завершился уже после отчёта; prod-пробы — предмет B10/волн v6.3).

## 2. Таблица перекрытия

| v6.3 ID | Legacy v6/v6.1/v6.2 | Статус на HEAD | Что осталось для v6.3 | Slice |
|---|---|---|---|---|
| REQ-B01 | C06/C06A (v6), C4 v6.1 — уточнение владельца **заменяет** C4 | частично (код producer→intent→decision→send, 23 теста; live-цикл не подтверждён) | автономный observer из обычного чата, opportunity/intent/Direct-разделение, SAY/REACT/SILENT, per-chat частота, отвязка от Direct-gate; funnel 24–48h canary, ≥1 SEND | BE-INITIATIVE |
| REQ-B02 | D05, C06A-хвост | частично (hybrid-детектор + usefulness f2192b6; genuine lesson applied live — нет) | семантический extractor вместо regex-хардкода, типизированные кандидаты, cursor/pокрытие, влияние на retrieval/decision, ≥10 сценариев E2E | BE-EXPERIENCE |
| REQ-B03 | C6 (v6.1), D06-часть | частично (purge noop, TTL-фильтры retrieval живы; 3584 expired) | retention/temporal-truth/retrieval-eligibility, as-of поиск, revalidation-блок, бессрочный per-chat override | BE-MEMORY |
| REQ-B03.4 | **D06 (остаток GraphRAG `_vec_candidates`)** | частично (D06 закрыл archive vector path `cadd432`; GraphRAG-поверхность и partition DDL — осознанные остатки f10 §4) | scope до effective top-K в `_vec_candidates` (L4206/4423) + GraphRAG path; displacement-тест; опц. partition DDL по решению владельца | BE-MEMORY |
| REQ-B04 | C03/C03A/C04 (частично) | частично (preservation P0/story P1, recovery-каталог `8700628`, preview-compile v2; live styled + owner visual pending) | EDIT≠GENERATE контракт, нормализатор+preflight лимита, preview=production route, late-recovery замена изображения (recover **не вызывает Telegram** — проверено на HEAD), vision-проверка | BE-COVER |
| REQ-B05 | — (новый симптом v6.3; связан с C04 UX) | нет (editor polling трогает `coverStyles.current` — L1830/1871) | неподвижный фон, несбрасываемое выделение/caret/scroll, 100dvh-модалка, guard черновика | FE-EDITOR |
| REQ-U01 | D13-часть (mobile shell `217c965`) | частично (верхняя mobile-nav сделана; «Ещё»-шторка отсутствует, mobileTopnavItems отдаёт весь navItems — L2530) | row A/row B контракт, «Ещё»-popover, chat-selector ellipsis, тесты 320–430+landscape | FE-SHELL |
| REQ-U02 | — (новое) | нет (oversight pills) | dropdown субвкладок <768, полный список без «Логи» | FE-SHELL |
| REQ-U03 | D12-часть | частично (Unified Run Card; дубли сна/1970-баг) | один блок сна, фикс 22.01.1970, здоровье памяти, честные воронки Опыт/Инициатива | FE-STATUS |
| REQ-U04 | — (новое) | нет (#status-logs в Analytics, L5682) | перенос единственного log-viewer в Статус, redirects | FE-STATUS |
| REQ-U05 | **D12 (7 отложенных виджетов)** | частично (durable-данные готовы; виджеты не отрисованы — f10 §4) | 7 визуализаций на подтверждённых данных + прогрессивный UI процессов/запусков | FE-STATUS |
| REQ-U06 | — (новое; смежен C04) | нет | порядок панелей editor, «Фактическая сборка» одной строкой, pre+copy | FE-EDITOR |
| REQ-U07 | — (новое; симптомы v6.3) | нет (toggleFullscreen L12802, legacy-угадывание isFullscreen) | FullscreenPolicy, tdesktop-запрет, safe-area позиционирование, BotFather launch-mode, Windows e2e | FE-FULLSCREEN |
| REQ-U08 | — (новое; U07-смежное) | нет (vendored lib 0.5.3 OFF; filter:url на псевдоэлементе ≠ рефракция) | аудит → слои .lg-panel → Tier A/B/C → стенд-приёмка | FE-GLASS |
| REQ-B06 | D07/D08-смежное | частично (overrides map сделан; Summary per-chat runtime не доказан) | Summary per-chat-operable, матрица карточек global-only/per-chat, DoD на реальной генерации | BE-MODULES |
| REQ-B07 | D10/D11-смежное | частично (temporal evidence есть; CATEGORY_TEMPORAL в pg_db.SEED_CATEGORIES отсутствует — подтверждено grep, param_catalog L41 знает категорию) | убрать карточку, сид/настройки в Фактчеке, gate temporal.tool_enabled | BE-MODULES |
| REQ-B08 | C07 (v6), stories recall-emitter остаток | частично (display names/карточки; «неизвестно»/пустые эпизоды, `[:50]` cap L1390, recall-emitter нет) | содержательная Story, backfill, 1970-даты, приёмка на 10 эпизодах | BE-STORIES |
| REQ-B09 | **D02 (остаток: Summary/Memory вне сквозного переноса — wa3)** | частично (миграция профилей/ролей `bfbc3df`; resolve_canonical_chat_id L7735 есть) | доказать end-to-end memory/FTS/GraphRAG/episodes/summary/override или идемпотентный alias; link≠proof | BE-MIGRATION |
| REQ-B10 | **весь список C01–C10/C03A/C06A/D01–D14 (26 ID)** | см. §3 | функциональная повторная приёмка 19 строк таблицы + 3 failed pytest | REL-GATE |
| REQ-B11 | D09/D12-смежное (честная телеметрия) | частично (durable run-cards; сквозные цепочки не сведены) | отчёт-цепочка по 10 механизмам + контролируемый E2E каждому | BE-INT-REPORT |
| REQ-B12 | C10/D14 (f10: Deployed SHA `__PENDING__` при workflow_state=done) | частично (расхождение зафиксировано самим ТЗ) | validator, статусы по каждому ID, release-reconciliation, deploy-протокол | REL-GATE |
| V01 | C06/C06A E2E | частично | release-blocker: живой цикл Initiative | E2E-VERIFY |
| V02 | D05 E2E | частично | release-blocker: semantic lesson | E2E-VERIFY |
| V03 | D06 E2E | частично | release-blocker: expired-fact retrieval + displacement | E2E-VERIFY |
| V04 | C03/C03A/C04 E2E | частично | release-blocker: styled применён + доставка + стабильный selection | E2E-VERIFY |
| V05 | D12/D13 E2E | частично | release-blocker: сводной UI-сценарий | E2E-VERIFY |
| V06 | — (новое) | нет | release-blocker: fullscreen/platform на реальных клиентах | E2E-VERIFY |
| V07 | — (новое) | нет | release-blocker: optical glass стенд | E2E-VERIFY |

## 3. B10 — регрессионная пере-приёмка 26 legacy ID (таблица B10 снапшота, строки 377–395)

Маппинг строк таблицы на требования карты: B10-R01 (C01/C02), B10-R02 (C03/C03A/C04), B10-R03 (C05), B10-R04 (C06/C06A), B10-R05 (C07), B10-R06 (C08), B10-R07 (C09), B10-R08 (C10/D14), B10-R09 (D01), B10-R10 (D02), B10-R11 (D03/D04), B10-R12 (D05), B10-R13 (D06), B10-R14 (D07/D08), B10-R15 (D09), B10-R16 (D10/D11), B10-R17 (D12/D13), B10-R18 (U07-нов), B10-R19 (U08-нов) + REQ-B10-PYTEST (3 failed pytest).

Статус каждого на HEAD — см. f10 §2/§3: все 26 = код+тесты+REV; **live/owner-пробы — ни по одному не закрыты** (это и есть содержание B10: «функциональная регрессия, не 26/26»).

## 4. Волны v6 → v6.3 (для истории)

| Волна v6 | Коммиты (f10 §1) | Поглощено в v6.3 |
|---|---|---|
| Wave A | bfbc3df (D02), e606ec8 (D08+D09), 6230fde (D01+D09) | B09/B10-R09/R14/R15 |
| Wave B | cadd432 (D06), 5c521fd (C06A), 8700628 (C03A) | B03.4/B01/B04.5/B10-R02/R04/R13 |
| Wave C | 2ef6189 (D03+D04+D07) | B10-R11/R14 |
| P1 | f2192b6 (D05), 2e40615 (D09+D10+D11) | B02/B10-R12/R15/R16 |
| UI | 217c965 (D12+D13) | U01/U03/U05/B10-R17 |
| D14 | кандидат→f58a644 (help v9/v6) | B10-R08/B12.5 |

## 5. Осознанные остатки v6 (f10 §4) → куда попали в v6.3

| Остаток v6 | v6.3 требование |
|---|---|
| search_result producer (C06/C06A) | B01 (наблюдатель opportunities; решение владельца о источнике — внутри B01.2 reason codes) |
| GraphRAG `_vec_candidates` scope | **B03.4** |
| Partition key DDL (sqlite-vec 0.1.9) | B03.4 (опциональная схема по возможностям; решение владельца при DDL) |
| 7 виджетов D12 | **U05.3** |
| demote_reason детализация (wc-direct) | B11.CHAIN (reason codes/skip reasons) — не-P0 уточнение диагностики |
| Diction `style_job_failed` | B04.4/U06.2 (честные причины в Inspector/UI) |
| Stories recall-emitter | B08.1 (retrieval-эмиттеры истории) |
| (из workflow_state, по lane-input) Direct concurrency тест | B10-R09 (D01 live) |
| (из workflow_state) dossierSaving shared | B10-R09 (concurrent UI edit) |
| (из workflow_state) Experience K2-OFF ре-обработка | B02.3 (cursor lag/backfill) |

Примечание: `plans/workflow_state.md` при подготовке карты не перечитывался напрямую (параллельный CLEAN-1 перемещает plans/); остатки взяты из lane-input и f10 §4. Расхождение f10 (`Deployed SHA: __PENDING__`) vs факт деплоя 2.58.78 — обязателен к снятию в release-reconciliation (REQ-B12.5).
