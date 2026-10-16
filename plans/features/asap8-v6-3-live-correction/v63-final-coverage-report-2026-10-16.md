# v63-final-coverage-report — ASAP 8 v6.3 live correction (2026-10-16)

Финальный отчёт эпика, требуемый строками `source-lines-37423-EOF.md:409`
(B12.1: «в финальном отчёте нет открытых pending-заглушек без красного статуса и
блока завершения») и `:439` (FINAL.1: таблица coverage «проблема → доказанный RCA →
изменённые исходники → RED-тест → GREEN/Review → deployed SHA → настоящий
outcome → статус»).

Кандидат и deployed commit: **`c2775a54258512a3e20c97341d3e8a6738b1a33b`**
(2.58.79). Независимая live-привязка выполнена этой lane:
`healthz` 200 `2.58.79`, `/web/` и `/web/static/fullscreen-policy.js` побайтово
равны блобам кандидата (`evidence/v63-close/prod-probes-2026-10-16.md`).

Фронтенд- Lane V63-FE-2 завершён и его вердикт учтён здесь
(`v63-frontend-verification-2026-10-16.md`): 6/6 e2e-сьютов зеленые
(384 проверки, 0 console errors), 49 PNG `evidence/v63-frontend/` — настоящие
непустые кадры (IHDR + pixel-variance), покрыты все 8 классов viewport.
**Ограничение привязки:** V63-FE-2 сама объявилаfingerprint прогонов как
`a854ad95 + незакоммиченная дельта web/` (не коммит и не `c2775a54`), поэтому
её числа относятся к рабочему дереву, а не к задеплоенному бандлу; для FINAL.3
и B10-R17 это должен быть отдельный шаг (коммит дерева либо перепрогон на
`c2775a54`).

**Заявление о полноте не делается.** Эпик не закрыт: 18 owner-гейтов,
37 rows READY_FOR_LIVE, 3 required PENDING, 3 незакрытых RED. Полный список
открытого — §4.

## 1. Бухгалтерия

| | карта (рабочее дерево, post-reconciliation) | предложение этой lane |
|---|---|---|
| VERIFIED | 129 | 129 → **135** (6 сейчас) → **143** (8 после коммита артефактов/снятия RED) |
| READY_FOR_LIVE | 44 | 44 → **38** |
| PENDING (required) | 9 | 9 → **3** (FINAL.3, B12.6, REQ-0-1) |
| BLOCKED_REAL_HUMAN_GATE | 18 | 18 (без изменений) |
| Итого | 222 | 222 |

Карта требований (`requirements-map.json`) этой lane **не редактировалась** —
все изменения статусов предложены в `v63-agent-close-2026-10-16.md` и подлежат
применению отдельным письмом (PM/Orchestrator) с последующим коммитом.

## 2. Coverage-таблица (FINAL.1)

Статусы: **V** = VERIFIED, **L** = READY_FOR_LIVE (ждёт live/владельца),
**B** = BLOCKED_REAL_HUMAN_GATE, **P** = PENDING (открыт, причина в §4),
**C** = закрывается после коммита артефактов этой lane.
Все строки привязаны к deployed SHA `c2775a54`; «RED→GREEN» даётся по факту
ревью/теста, а не по заявлению лейна.

### B01–B12

| ID | Проблема | Доказанный RCA | Изменённые исходники | RED→GREEN/Review | Outcome | Ст. |
|---|---|---|---|---|---|---|
| B01 (+DOD) | проактивная инициатива в обычном чате | observer не был проводкой в джобу; «включено = выполнено» не доказуемо | `services/memory_maintenance.py` (initiative observer), `services/initiative_writer.py` | RED на отсутствии воронки → GREEN `test_asap8_v63_b01_initiative_observer.py` 13/13; REV-W1 APPROVED | код+тесты: opportunity→SAY/REACT/SILENT, бюджеты, dedup, «24ч ноль» → диагностика; прод: 25 job/24h, `opportunities=0` | V/B |
| B02 (+DOD) | семантическое извлечение Experience | regex-детектор ≠ семантика; курсоры двигались без durable-записи | `services/mca_experience_jobs.py` | GREEN `test_asap8_v6_d05_experience.py` 18/18; REV-W1 APPROVED | e2e коррекция→применённый урок (не только счётчики); прод: последняя попытка `failure` 2026-10-10 | V/B |
| B03 (+B03.4, DOD) | expired-память и вытеснение | GraphRAG KNN фильтровал scope ПОСЛЕ top-K (анти-паттерн D06) | `services/summary_memory.py` (`_staged_knn_scope`, `_vec_candidates`) | RED displacement (400 чужих фактов) → GREEN 11/11 + `d06_isolation` 9/9; REV-W1 APPROVED | fresh-first + архивный top-up с as-of, никогда не delete; прод-вектор деградирован (квота parked) | V/L |
| B04 (+DOD, B04.5) | style-EDIT без потери сцены | EDIT повторно пересылал сцену; prompt overflow | `services/cover_style_jobs.py`, `web/api/cover_styles.py` | GREEN b04_edit 60, scene; REV-W1 APPROVED (live честно LIVE_UNVERIFIED) | compact EDIT 528 vs 1133, preview=production; rich-media публикация — owner | V/B |
| B05 | редактор обложек «прыгает» | RCA: реальный канал — `loadMeta` в draft, а не polling-off | `web/app.js`, `index.html`, `app.css` | GREEN EDITOR e2e 40/40; REV-W3 VERIFIED | выделение 13 с при живом polling, copy==exact | V |
| B06 (+DOD) | per-chat Summary | Summary гейт был глобальным | `services/summary_scheduler.py` (`summary_effective_enabled`) | GREEN 17/17 матрица на реальной генерации; REV-W1 APPROVED | единый резолвер emergency→chat→global во всех путях; прод-матрица — owner | V/L |
| B07 (+BODY) | Temporal не карточка, а функция Фактчека | `SEED_CATEGORIES` без `CATEGORY_TEMPORAL` → настройка не сидилась | `services/pg_db.py`, `services/param_catalog.py` | GREEN 12/12; REV-W1 APPROVED + REV-W3 UI | сид идемпотентен, гейт через hot, в витрине карточки нет | **V** (закрыто этой lane) |
| B08 (+B08.4) | «Эпизод 1780…» вместо истории | пустой summary + legacy-заглушка проходили в ленту | `services/mca_episodes.py`, `services/web_stories.py` | RED (REV-W3PRE N1) → GREEN `f8f9d9a0`, 24/24; REV-W3 VERIFIED | content_status, три даты, участники ≤5,+ещё N; 10 «настоящих» эпизодов — owner | **V** / L |
| B09 (+BODY) | перенос supergroup ≠ потеря | backup с `LIMIT 200_000` + WARNING при cap → перенос продолжался | `services/chat_migration.py`, `handlers/chat_lifecycle.py` | RED (REV-W1 F1) → GREEN `72cab8fc`, 39 passed | chunked backup + hard-cap abort, 0 DELETE; live-перенос — owner | P/B |
| B10 (R01–R19, PYTEST) | «26/26» без функциональной приёмки | заявления вне зоны вместо классификации | тесты/код по legacy-пунктам | 616 passed на кандидате (эта lane); `baseline-pytest-b10.md` | 1 реальный RCA + 2 исторических flaky зелёные; live-пункты открыты | L (1 V) |
| B11 (SCOPE/CHAIN/E2E) | скрытые механизмы «включены, но не запускались» | нечем отличить no_input/producer_off/cursor_stalled/worker_crashed/ttl/never_run | `tools/v63_b11_mechanisms_report.py`, `services/mca_episodes.py` | GREEN 17/17; REV-W3PRE VERIFIED | прод: 8 ok / 2 never_run (graph_memory, embeddings — parked-квота); E2E для векторного контура невозможен | L (**SCOPE=V**) |
| B12 (B12.1–6) | фиктивный DONE | пакет без validator'а и без per-ID статусов | `requirements-map.json` + validator | RED 110 errors (exit 1) — честно; plan stage 0 errors | validator работает, статусы по 222 ID, deploy-протокол и reconciliation есть; 3 артефакта созданы, но ещё не в git | **C** |

### U01–U08

| ID | Проблема | RCA | Источники | RED→GREEN/Review | Outcome | Ст. |
|---|---|---|---|---|---|---|
| U01 | мобильная шапка 225.6 px и горизонтальная лента | navScrollW 455 > 288 | `web/app.js`, `index.html`, `app.css` | GREEN SHELL 129/129; REV-W2 VERIFIED | header 116.2 @320–430, 93.8 landscape, `scrollWidth==innerWidth` | V |
| U02 | 8 вкладок Аналитики incl. «Логи» на мобиле | `oversightTabs` без фильтра | `web/app.js` | GREEN e2e u02_*; REV-V2 VERIFIED | 7 вкладок, ARIA, deep-link, desktop ≥768 без изменений | V |
| U03 | два блока Сна, «1970» | дубль-бейджи + отсутствие нормализации TS | `web/app.js`, `web/api/memory_overview.py` | GREEN STATUS 26/26; REV-W3 VERIFIED | один блок, 1970→«ещё не выполнялся», смысловые/технические строки раздельно | V |
| U04 | логи в трёх местах | `#status-logs` продублирован | `index.html`, `web/app.js` | GREEN; REV-W3 VERIFIED | один экземпляр в конце Статуса, легаси-редирект нормализован | V |
| U05 (+7viz) | 7 отложенных визуализаций на пустых данных | durable-счётчики не были подключены | `web/api/analytics_viz.py`, `web/api/memory_overview.py` | GREEN ANALYTICS 74/74; REV-W3 VERIFIED | honest empty-состояния, 0 новых поллеров/CDN; прод-рендер — owner | V |
| U06 | style editor: порядок и честный лимит | — | `web/app.js`, `index.html` | GREEN; REV-W3 VERIFIED | одна строка сборки, copy==exact, «неизвестно» вместо псевдо-успеха | V |
| U07 (+HARD, U07.0–3) | fullscreen-ловушка | policy отсутствовал; legacy-инверсия isFullscreen | `web/static/fullscreen-policy.js`, `web/app.js` | GREEN FULLSCREEN 7/7 (70 проверок); REV-V2 VERIFIED | mock-матрица incl. tdesktop/launch-mode/safe-area; реальные клиенты — owner. **Открытый дефект U07.2:** горизонтальные `safeAreaInset` игнорируются, hit-box заезжает в native-правую зону в landscape-cutout (`v63-frontend-verification-2026-10-16.md §4`) | V/B |
| U08 (0–5) | стекло декларировалось, но не рефрагировало | `css.supports` ≠ рендер; feImage без карты | `web/app.css`, `index.html`, `web/static/glass-probe.js` | GREEN сканлайн-корреляция Tier A + ui-acceptance; REV-V2 VERIFIED | кромка dx −5…−8, центр 0, контроль corr 1.0; контраст 13.1:1; WebKit честно Tier B | V |

### V01–V07

| ID | Сценарий | Итог | Ст. |
|---|---|---|---|
| V01 | живой SEND при opportunity | механизм жив (25 job/24h), `opportunities=0` — нужен естественный повод + canary 24–48 ч | **B** |
| V02 | семантическое извлечение в бою | B11: experience ok, последняя попытка failure 2026-10-10 — нужен естественный поток | **B** |
| V03 | исторический RAG по expired-фактам | код доказан (`test_expired_found_by_historical_query_only`, confirm/refute без delete, чужие факты не вытесняют); прод-проверка требует админ-сессии, вектор деградирован | L |
| V04 | styled-обложка в чат | зависит от `InputRichMessageMedia` в прод-aiogram (2 предсуществующих фейла) | **B** |
| V05 | UI/operational (2 чата+Summary, temporal в Фактчеке, 320/390/landscape, 3 tabs+Ещё, 1 сон, logs только Статус, аналитика, Stories narrative, коды/источники, без 1970, unknown не зелёный) | STATUS 26/26 + MODULES 42/42 + ANALYTICS 74/74 + js 11/11 (эта lane на кандидате) + `w2_shell_e2e.json` hOverflow=false; V63-FE-2 §4 — V05 VERIFIED-BY-AGENT; прод-бандл = кандидат | **V** (закрыто этой lane) |
| V06 | fullscreen на реальных клиентах | 8 строк U07.* требуют Windows/Android/BotFather | **B** |
| V07 | оптическое стекло + CSP на проде | Tier A/Tier B приняты (`ui-acceptance.md`), CSP data: разрешён (прод-проба); физический FPS/визуал — owner | L |

### Legacy v6 (B10-R01…R19)

| ID | Что | Итог на кандидате | Ст. |
|---|---|---|---|
| R01 (C01/C02) | два реальных Summary L2 | механизм GREEN (39+20 тестов); двух реальных опубликованных Summary и diff источников в пакете нет | L |
| R02 (C03/C03A/C04) | styled-публикация и восстановление | b04 тесты зелёные; live-публикация — owner | L |
| R03 (C05) | live негативный тест Summary OFF | реальная генерация: `tick_skips_chat_off`, 0 LLM-вызовов (17/17); прод-прогон с OFF — owner | L |
| R04 (C06/C06A) | автономная Initiative | тесты зелёные; естественный чат — owner | L |
| R05 (C07) | stories с реальными источниками | 24/24 b08 + 9/9 f7 (display-имена, refs, без выдумок) | **V** |
| R06 (C08) | embeddings quota/backfill | f8 тесты зелёные; live backfill невозможен (parked-квота) | L |
| R07 (C09) | YouTube 407 + proxy | 41/41 (классификация 407, каскад, health, auth-probe); реальный provider-проход — owner | L |
| R08 (C10/D14) | tracked docs/help/sync release | 24/24 `d14_help_sync` (канон, версии, реестры, миграции, запрет лживых обещаний); пакет в git | **V** |
| R09 (D01) | dossier/settings race | поведенческого теста concurrent edit/refresh/409 не найдено | L |
| R10 (D02) | supergroup incl. память | b09 тесты + `wa3` зелёные; live-перенос — owner | L |
| R11 (D03/D04) | Direct L1 auth/budget/modes/tools | 9+34 тестов (запрет без ключа, бюджет, режимы, evidence-pack) | L |
| R12 (D05) | genuine lesson applied | 18/18 e2e до счётчиков | L |
| R13 (D06) | displacement + prod timing | 9/9 изоляция; прод-timing — owner | L |
| R14 (D07/D08) | overrides map + Random | 11/11 (RBAC, изоляция, fail-closed) | L |
| R15 (D09) | Dream/Deep Sleep/paradigms | 5+5 dream/deep + B11 (prod dream/deep_sleep ok) | L |
| R16 (D10/D11) | даты источников + реестр | 23/23 даты + 16/16 machine key inventory; live-примеров датирования Фактчека в пакете нет | L |
| R17 (D12/D13) | 7 визуализаций + mobile | 74/74 e2e на фикстурах реальной структуры; прод-рендер LIVE_UNVERIFIED, «всех размеров» нет (cover_editor/fullscreen) | L |
| R18 (U07) | fullscreen policy | mock-матрица 7/7 | L |
| R19 (U08) | стекло + видео изгиба | Tier A/B приняты; видео изгиба линии в пакете отсутствует | L |

## 3. Закрыто этой lane (6 строк, evidence — `evidence/v63-close/`)

1. **REQ-B07** — 12/12 `test_asap8_v63_b07_temporal_factcheck.py` на `c2775a54`
   (сид `CATEGORY_TEMPORAL`, отсутствие карточки в выдаче, гейт/hot/RBAC/env) +
   REV-W1/REV-W3 вердикты + прод-бандл = кандидат.
2. **REQ-B08** — 24/24 `test_asap8_v63_b08_stories.py` (детерминизм, content_status,
   три даты, 1970, участники, backfill, честная лента) + REV-W3PRE/REV-W3.
3. **REQ-B11-SCOPE** — отчёт по всем 10 механизмам без пропусков: прод-прогон
   (`w4-live-probes.md §1`: 8 ok / 2 never_run) и артефакт запуска на дереве
   кандидата (`evidence/v63-close/b11-mechanisms-report-history-db.json`,
   10 секций полной цепочки, `not_green_rule` соблюдён).
4. **V05** — STATUS 26/26, MODULES 42/42, ANALYTICS 74/74, js 11/11 на кандидате,
   `w2_shell_e2e.json` (hOverflow=false 320/360/390/430/667/zoom200),
   прод-бандл = кандидат.
5. **B12.4** — протокол/deploy/rollback/smoke/поверхность (`live-canary.md`,
   `prod-probes-2026-10-16.md`) + аудит источников «нет фальшивых SEND/lesson»
   (`evidence/v63-close/preserve-and-workflow-audit.md §3`).
6. **B10-R05 (C07)** — по делегации acceptance к REQ-B08 (закрыт): 24/24 b08 +
   9/9 f7 (display-имена, refs по правам, `test_deterministic_card_no_invention`,
   `test_ui_no_numeric_id_dump_in_main_ui`). Отличается от B08.4: у R05 нет
   отдельной live-клаузы про «10 настоящих эпизодов».

## 4. Что осталось открытым (полный список)

### 4.1. Owner-гейты (18) — BLOCKED_REAL_HUMAN_GATE

`U07-SYM-DESKTOP`, `U07-LAUNCHMODE`, `REQ-B01`, `REQ-B02`, `B02.3`, `B04.5`,
`REQ-U07`, `U07.1a`, `U07.1e`, `REQ-U07-3`, `U07.3b`, `U07.3c`, `REQ-B09`,
`FINAL.2`, `V01`, `V02`, `V04`, `V06`.
Причины по каждой строке — `map-reconciliation-2026-10-16.md §3`; кратко:
реальные Telegram-клиенты (8 строк U07), естественный групповой чат и окно
canary 24–48 ч (B01/B02/B02.3/V01/V02), реальная supergroup-миграция
(B09), styled-публикация (B04.5/V04), 24/48h наблюдаемость Initiative/Experience
(FINAL.2).

### 4.2. READY_FOR_LIVE (38 после закрытий)

`REQ-B03, B03.4, REQ-B04, REQ-B06, REQ-B01-DOD, REQ-B02-DOD, REQ-B03-DOD,
REQ-B04-DOD, REQ-U07-HARD, REQ-B06-DOD, REQ-B09-BODY, B10-R01, R02, R03, R04,
R06, R07, R09, R10, R11, R12, R13, R14, R15, R16, R17, R18, R19, REQ-B11, REQ-B11-E2E,
B08.4, REQ-B10, FINAL.4, V03, V07`.
Группы причин: (i) пункты legacy v6, чей Proof требует реального
прод-прогона/провайдера/UI-сессии; (ii) B03/B04/B06/B09-DOD — прод-метрики и
live-доставка; (iii) `REQ-B11-E2E` — контролируемый E2E для векторного контура
невозможен при parked-квоте эмбеддингов.

### 4.3. PENDING required (3)

* **FINAL.3** — вердикт lane V63-FE-2 (`v63-frontend-verification-2026-10-16.md`)
  получен и учтён: 49 PNG подлинные (IHDR + pixel-variance, ни одного пустого),
  все 8 классов viewport покрыты. Остаётся три конкретных пробела:
  (1) у `status` нет одиночного-viewport кадра на 768/1024/1440
  (`status_768x1024.png` = full-page 768×4780, 1024×3991, 1440×3939);
  (2) `cover_editor` и `fullscreen` не имеют 360/430/768, а
  `fullscreen_tdesktop_1440x900.png` — не fullscreen-режим, а policy-кадр
  (полноэкранного захвата на desktop-размере нет вовсе);
  (3) прогоны V63-FE-2 привязаны к рабочему дереву `a854ad95 + delta web/`,
  а не к `c2775a54`, и папка `evidence/` не в git.
* **B12.6** — side effects не измерены; нет негативных тестов на «GraphRAG
  hallucinated stats» и на ошибочного адресата (`preserve-and-workflow-audit.md §4`).
* **REQ-0-1** — 24/48h датасет §0.1 не собран (`baseline-inventory.md:82` —
  перечень «для сбора на S0»); сбор только на сервере.

### 4.4. Незакрытый RED (4)

1. `tests/js/round1025_hotfix{7,8,9,10}_*_test.js` — RED на кандидате: пин
   `APP_VERSION "2.58.78"` сломан релизным bump. Механическая причина,
   функциональной регрессии нет, правка тестов вне зоны lane.
2. `tests/test_direct_chat_concurrency.py::…n2` — RED, RCA в
   `baseline-pytest-b10.md` item 1.
3. Release coverage gate — exit 1, scoped=200, errors=110.
4. **U07.2 — дефект, найденный lane V63-FE-2 и воспроизводимый агентом:**
   горизонтальные `safeAreaInset`/`contentSafeAreaInset` для fullscreen-контрола
   игнорируются — при правом inset 44 hit-box уходит на 28 px в native-правую
   зону (`_v63fe2_rowa_safearea.json`, случай `667_safearea_cutout`). Не
   перекрашивается: U07.2-строки карты требуют исправления до приёмки.

### 4.5. Требует одного прод-подключения (DevOps)

1. Перезапустить `tools/v63_b11_mechanisms_report.py` **с `--pg-dsn`** — снять
   расхождение `w4-live-probes.md:17` («с PG DSN») vs `live-canary.md:52`
   (`pg_dsn_not_provided`).
2. Снять §0.1-датасет (24/48h: API/trace/job state/counters/ingest cursor/LLM
   errors/UI) для REQ-0-1 и мировые факты для FINAL.2.

## 5. Итог

Релиз 2.58.79 задеплоен и привязан к кандидату воспроизводимо. Ядро волн
B01–B09/U01–U08 имеет реальные тесты, e2e и ревью; три обязательных документа
пакета созданы этой lane; фронтенд- Lane V63-FE-2 завершён вердиктом
(6/6 сьютов, 384 проверки, подлинные 49 PNG) с одним найденным дефектом U07.2
и 9 owner-only пунктами. Эпик **не** завершён: открыты 18 owner-гейтов,
38 READY_FOR_LIVE, 3 required PENDING и 4 RED. «ASAP выполнен полностью» не
заявляется.
