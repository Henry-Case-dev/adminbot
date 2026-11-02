# EPIC-EXPERIENCE-LEARNING-ADMIN-PERFORMANCE-HELP — план работ (E, P, H)

Источник: `plans/owner_inputs/2026-11-02-experience-learning-performance-help.md` (дословный, 336 строк,
`current_task.md` 4030–4365), вход `OI-2026-11-02-EXPERIENCE-LEARNING-PERFORMANCE-HELP`.
Карта: `requirements-map.json` (169 строк инвентаря + 56 ручных строк, **119 обязательных требований**).
Граф: `slice-graph.json` (`openworkflow-slices-v1`), 15 слайсов.
Гейт: `requirements_gate.py check --stage plan` → `errors=0`.

Распределение обязательных строк: **E — 72**, **P — 45**, **H — 1**, **сквозной архитектурный guard — 1**
(`EP-GUARD-ARCH`, якорь L36, покрывает §0.2 как проверяемое требование). Контекстных строк — 106
(включая §0.2 дословно и §0.3 «разрешение конфликтов», чтобы запреты и разрешения не потерялись).

---

## 1. Пакеты работ (слайсы)

Size: S — один узкий механизм, M — связный механизм с миграцией/UI, L — сквозной контур.

| ID | Что даёт (наблюдаемо) | Владеет файлами | Зависит от | Доказательство приёмки | Size | Параллельность |
|---|---|---|---|---|---|---|
| **EP-E-EXTRACT** | существующий semantic batch отдаёт версионированный кандидат с refs/old_claim/revision, честно отклоняет несуществующие refs; сбой не двигает cursor | `services/mca_experience_jobs.py`, `services/database.py`, `tests/test_ep_e_extract.py` | — | тесты схемы/refs/cursor + прогон на длинной беседе через 2 окна | M | parallel-safe (сейчас) |
| **EP-E-GATE** | грубая содержательная поправка не теряется из-за агрессии/юмора; буквальное слово не внедряет урок; отбор — семантический на существующих retrieval-примитивах | `services/mca_experience_jobs.py`, `services/mca_experience.py`, `services/mca_retrieval_context.py` | EP-E-EXTRACT | тесты на грубой поправке / омониме / другой теме; отчёт «до/после» по отбору | M | serialized после EXTRACT и после FINAL v8 `MEM-CONTRACT` |
| **EP-E-LESSON** | смысловой урок без Python-каталога: principle/applies_when/do_not_apply_when/evidence/version, операции ADD/REVISE/MERGE/SUSPEND/SUPERSEDE/NOOP, история, manual suspend | `services/mca_experience.py`, `services/database.py`, `web/api/memory_agi.py`, `web/index.html`, `web/app.js` | EP-E-GATE | тесты операций и версий + инъекция отклоняется + карточка показывает версии/историю | L | serialized (DB + UI) |
| **EP-E-OUTCOME** | стадии selected/delivered/used/outcome_known, независимый outcome, витрина «событие→утверждение→поправка→ревизия→применения→исходы» | `web/api/oversight_router.py`, `web/api/memory_agi.py`, `web/index.html`, `web/app.js`, `services/mca_events.py`, `services/mca_experience.py` | EP-E-LESSON | тесты стадий/unknown≠success + UI-скриншоты + `mca_events` trail | M | serialized после LESSON |
| **EP-E-DIALOGUE** | на «кто такой X» после своего ввода имени — восстановление своего output, признание ошибки/сомнение в текущем ответе без лишнего LLM-вызова; поправка третьего лица не приписывается боту | `services/direct_chat_service.py`, `handlers/direct_chat.py`, `services/prompt_composer.py`, `services/bot_output_ledger.py` | — | тест «своё утверждение → вопрос → ответ» + счётчик вызовов модели + регресс смежных контуров | M | serialized после FINAL v8 `AC-P0` / `MEM-CONTRACT` |
| **EP-E-ACCEPT** | все 26 сценариев E-01..E-26 на независимых вариациях + DoD E | `tests/test_ep_e_accept.py`, `evidence/e-accept/` | все E | 26 строк VERIFIED с candidate-bound evidence | L | после E-слайсов |
| **EP-P-MEASURE** | воспроизводимый baseline/после на одном SHA: cold/warm/desktop, стадии, отклик, long tasks, байты, кеш, SQL | `tools/ui_ep_perf_baseline.py`, `evidence/perf/` | — | сырые прогоны + p50/p95 + разделение network/server/JS/render | M | parallel-safe (read-only; baseline — на SHA старта P) |
| **EP-P-CACHE** | версионированные JS/CSS/vendor реально переиспользуются; HTML/API не кешируются; версия соответствует байтам; сжатие подтверждено; CSP сохранён | `web/app.py`, `config/settings.py` | — | заголовки/304/сжатые байты на реальном proxy + P-03/P-04 | M | после COG-MAP S4 (тот же `web/app.py`) |
| **EP-P-SCRIPTS** | порядок/способ подключения vendor сохранён по зависимостям; обязательный bootstrap краток; необязательное отложено; отказ не ломает вход | `web/index.html` | EP-E-OUTCOME | тест загрузки без Chart/OGL + P-15 + отсутствие регрессии Telegram bridge | S | serialized (index.html) |
| **EP-P-BOOT** | первый экран «Статус» не монтирует скрытые вкладки; deep link напрямую; конечные стадии загрузки; нет stale overwrite при смене чата | `web/index.html`, `web/app.js`, `web/static/app.css` | EP-P-SCRIPTS | P-02/P-05/P-06/P-09/P-13 + профиль mount + эквивалентные скриншоты | L | serialized (монолит фронта) |
| **EP-P-ANIM** | нет невидимой работы на hidden/закрытых overlay; геометрия восстанавливается; чтения геометрии сгруппированы; внешний вид идентичен | `web/static/polygon-background.js`, `aurora-flow.js`, `glass.js`, `glass-probe.js`, `glass-refraction.js` | — | P-07/P-08/P-12 (скриншоты при включённом стекле) + числа CPU/кадров | M | parallel-safe по файлам; визуальная приёмка — после UI-волны |
| **EP-P-API** | `/config` и тяжёлые read-path ускорены на доказанных участках; keyset-списки; отзывчивый event loop; RBAC сохранён | `web/api/routes.py`, `web/api/oversight_router.py`, `services/database.py`, `services/status_service.py` | EP-E-OUTCOME, EP-E-LESSON | EXPLAIN+baseline до/после, P-10/P-11/P-14 | M | serialized (routes.py/oversight/database) |
| **EP-P-ACCEPT** | P-01..P-16 проверены независимо + DoD P | `tests/test_ep_p_accept.py`, `tests/js/ep_p_accept_test.js`, `evidence/p-accept/` | все P | 16 строк VERIFIED + real traces + regression | L | после P-слайсов |
| **EP-H-HELP** | оба гайда «Справки» пересмотрены по фактически deployed системе и доставлены в PG/UI | `services/info_service.py`, `info_text.md`, `plans/docs/intelligence_user_guide.md` | EP-E-ACCEPT, EP-P-ACCEPT, EP-GUARD | PG/UI доставка + версии/backup + negative-тесты обещаний | L | **только последним**, после PASS+deploy+live всей очереди |
| **EP-GUARD** | сквозной контроль §0.2 (нет второго мозга/хардкода/горячего LLM/бюджетов/эмбеддинг-пересчёта) | — (read-only) | — | Reviewer по диффу + тест переноса на других именах | S | постоянно |

## 2. Список сериализации (общие файлы → порядок единственного писателя)

| Файл | Кто пишет (в порядке) | Почему |
|---|---|---|
| `web/index.html`, `web/app.js` | COG-MAP S2–S4 → FINAL v8 `UI-BOOT`/`UI-SELECTOR`/`UI-MODULES`/`UI-MEME`/`UI-LOGS-FE`/`AC-UI`/`MEM-TRACE` → EP-E-LESSON → EP-E-OUTCOME → EP-P-SCRIPTS → EP-P-BOOT | монолит фронта, один писатель за раз |
| `web/static/app.css` | COG-MAP → FINAL v8 UI-* → EP-P-BOOT | визуальный контракт |
| `web/app.py` | COG-MAP (вне write_scope этого эпика, но держит файл) → EP-P-CACHE | кеш/CSP/статика |
| `web/api/routes.py` | FINAL v8 `UI-LOGS-BE`/`UI-MEME` → EP-P-API | `/config`, логи |
| `web/api/oversight_router.py` | EP-E-OUTCOME → EP-P-API | воронка/стадии, затем профилирование |
| `web/api/memory_agi.py` | EP-E-LESSON → EP-E-OUTCOME | lessons API |
| `services/mca_experience.py` | EP-E-GATE → EP-E-LESSON → EP-E-OUTCOME | ядро опыта, один писатель |
| `services/mca_experience_jobs.py` | EP-E-EXTRACT → EP-E-GATE | batch/детектор/cursor |
| `services/mca_retrieval_context.py` | FINAL v8 `MEM-CONTRACT` → EP-E-GATE | общий retrieval-контракт |
| `services/mca_events.py` | FINAL v8 `AC-PIPE` → EP-E-OUTCOME | журнал |
| `services/summary_memory.py` | FINAL v8 `MEM-CONTRACT`/EVOL-B-EMBED/EVOL-B-FACTS — **этот эпик не трогает** | запрет «второго мозга» и конфликт с очередью |
| `services/database.py` (DDL/индексы) | EP-E-EXTRACT → EP-E-LESSON → EP-P-API | одна миграционная линия за раз |
| `config/settings.py` (`APP_VERSION`) | EP-P-CACHE (+ обычный релизный bump) | ручная версия = риск stale mixed assets |
| `services/info_service.py`, `info_text.md`, `plans/docs/intelligence_user_guide.md` | EP-H-HELP — единственный писатель, до гейта не трогать | запрет публиковать справку заранее |

`services/self_reflection.py` — единственный писатель EP-E-EXTRACT (в других scope отсутствует).

## 3. Волны исполнения (честно про ранний старт)

Очередь до эпика: COG-MAP S2–S4 → §12 rerun → EVOL-RELEASE DoD → пакеты FINAL v8
(`asap-evol-anticliche-memory-admin-ux`, 573 обязательных строк).

**Волна 0 — можно начинать уже сейчас (файлы не пересекаются ни с COG-MAP, ни с FINAL v8):**
1. `EP-E-EXTRACT` — `mca_experience_jobs.py`/`database.py`/`tests/test_ep_e_extract.py`.
2. `EP-P-MEASURE` (recon + фиксация методики) — только чтение; авторитетный baseline снимается на SHA старта P.
3. `EP-P-ANIM` — `web/static/glass*.js`/`polygon-background.js`/`aurora-flow.js`; визуальный P-12 перепроверяется после UI-волны.

**Волна 1 — после merge COG-MAP S4 и закрытия EVOL-RELEASE:**
4. `EP-P-CACHE` (`web/app.py` освободился; FINAL v8 его не пишет) — параллельно с FINAL v8.
5. `EP-E-GATE` без retrieval-части (эвристики/ранжирование) — параллельно; retrieval-часть ждёт `MEM-CONTRACT`.

**Волна 2 — после FINAL v8 UI-стека и MEM-* (общие файлы):**
6. `EP-E-LESSON` → `EP-E-OUTCOME` → `EP-P-SCRIPTS` → `EP-P-BOOT` (строго последовательно в `index.html`/`app.js`).
7. `EP-E-DIALOGUE` (после `AC-P0`/`MEM-CONTRACT`), `EP-P-API` (после UI-LOGS-BE/UI-MEME).

**Волна 3 — приёмка:** `EP-E-ACCEPT`, `EP-P-ACCEPT`.

**Волна 4 — H:** `EP-H-HELP` только когда весь `current_task` выше H (включая E, P, AntiCliche/Memory/UI)
реализован, принят Reviewer, развёрнут и проверен live. Промежуточную справку не публиковать; черновики
в канонические файлы не класть.

Ограничение параллелизма: max 3 писателя одновременно, и только на непересекающихся файлах из §2.

## 4. Контракт измерения для P (до/после, без нового харнесса)

1. **Один SHA, одно окружение.** Baseline и «после» снимаются на зафиксированном SHA (записывается в
   каждый артефакт), локальный запуск существующим входом `bot.py` (`uvicorn.Server`, `create_app`) на
   одном и том же наборе данных PG; viewport 390×844 (TMA) и 1440×900 (desktop), стекло **включено**,
   сеть эмулируется CDP (`Network.emulateNetworkConditions`, «Slow 4G»). Cold = новый browser context
   без кеша; warm = повторный вход в том же профиле/релизе. Смешивать cold «до» и warm «после» запрещено.
2. **Клиентские метрики.** Playwright (уже используется в `tools/ui_*_e2e.py`): `Performance.getMetrics`,
   `PerformanceObserver` для LCP и longtask, `performance.now()` маркеры до «реально полезного статуса»
   (существующий DOM-селектор из ui-тестов, не skeleton), события ответов (`status`, `encodedBodySize`,
   `fromCache`), отклик кнопки/вкладки/чата, frame drops. ≥5 запусков на режим, значения p50/p95.
3. **Серверные метрики.** `curl -w` (TTFB/status/headers/размеры до и после сжатия) для HTML/JS/CSS и
   стартовых API; число и длительность SQL — `EXPLAIN (ANALYZE, BUFFERS)` на фактических запросах
   `/config`, `/status`, `/oversight`, уроков; app-side счётчики — существующие `mca_trace`/`mca_events`.
   Секреты/`initData` в артефакты не попадают (проверяется грепом артефактов).
4. **Разделение причин.** Каждое изменение сопровождается атрибуцией к слою: network (байты, кеш,
   сжатие), server (latency, SQL), JS (parse/compile/mount), render (layout/paint). «Оптимизация вообще»
   доказательством не считается; при пересечении доверительных интервалов p50/p95 выигрыш не заявляется.
5. **Приёмка и честность.** PASS только при улучшении медианы «время до полезного экрана» и задержки
   отклика с сохранением P-01..P-16, эквивалентных скриншотов при включённом стекле и без RBAC/утечек.
   Если реальный Android WebView недоступен — статус «мобильная проверка не подтверждена» с конкретным
   blocker (P-16), а не PASS. Инструментарий: `tools/ui_round1025_matrix.py` (статика/вьюпорты),
   `tools/ui_*_e2e.py` (Playwright-паттерн), `tools/mca18_paired_replay.py` (для E7-3/E-09),
   `tests/js/`; новый recorder `tools/ui_ep_perf_baseline.py` — тонкая обвязка, не харнесс.

### 4a. Гейт паритета по пакетам P (обязателен для каждого пакета)

Дополнение владельца `OI-2026-11-02-PERF-PARITY` (`b9ff8a7e`) и контракт
`docs/track-p-performance-parity.md` (`b0fce752`): оптимизация затрагивает только код, загрузку, рендеринг,
запросы, кеширование и внутреннюю архитектуру; визуальный и функциональный паритет обязателен, любое
отклонение — регрессия и блокер релиза даже при улучшенных метриках.

Каждый пакет P отдельно обязан предъявить три части на одном SHA кандидата: **(a)** метрику, **(b)** артефакт
паритета, **(c)** сравниваемые состояния и вьюпорты. Без артефакта паритета пакет не принимается независимо
от чисел; в карте требований это строки `P-GATE-00..P-GATE-05`, в `slice-graph.json` — та же формулировка
в `acceptance` соответствующего слайса.

| Пакет | (a) метрика | (b) артефакт паритета | (c) состояния и вьюпорты |
|---|---|---|---|
| `EP-P-MEASURE` (P0) | baseline B: cold/warm/desktop p50+p95 до полезного «Статуса», интерактивного экрана, отклика; long tasks, frame drops, запросы, байты, 304, SQL/EXPLAIN, JSON | UX Surface Manifest + матрица паритета для B тем же кодом, что снимет C, плюс калибровка детектора (один отключённый эффект обязан уронить счётчики) | V [320×700, 390×844, 768×1024, 1280×800] + свип [360/430/1024/1440/1920/2560]; cold-кадр, «Статус», вкладки, смена чата/scope, `.more-sheet`, fullscreen, tier-ы стекла, reduced-motion |
| `EP-P-CACHE` (P1) | доля 304 на warm-входе ↑, transfer bytes ↓, время до полезного «Статуса» ↓, загрузка после релиза без чистки кеша | распакованные JS/CSS/HTML байты идентичны, 0-px геометрия, инвентарь контролов/DOM, стекло/полигон/движение/данные равны, stale-mixed-assets (P-04) | V + свип; повторный вход в том же релизе, новый релиз, путь GET/HEAD/ETag/304 |
| `EP-P-SCRIPTS` (P2) | запросы до полезного экрана, убранные дубли GET, time-to-interactive, мутации при retry | loading/error/empty/retry, INV-DATA/INV-DOM, нет stale overwrite (P-06), конфликт ревизий (P-13), нет секретов в хранилище | V + свип; быстрая смена чата, медленная сеть, отказ API, offline→online |
| `EP-P-BOOT` (P3) | parse/compile/mount, long tasks, время до «Статуса», deep link, нет роста listeners/timers/heap | идентичный DOM на вкладках и deep link, нет новых заглушек, INV-DOM/GLASS/POLY/MOTION/ROUTE, клавиатура/landscape/fullscreen/dropdown | V + свип; каждая вкладка, deep link, landscape 844×390, fullscreen, reduced-motion |
| `EP-P-ANIM` (P4) | frame drops, long tasks, idle CPU/GPU при hidden, layout за кадр, отсутствие роста | 11 полей `getDiagnostics()` при фиксированном `?bgseed=`, nodeCount 90–140 / 45–75, bloom+morph, INV-MOTION/INV-GLASS, 0 пикселей | V + свип; `document.hidden` round trip, закрытая модалка, скрытый overlay, fullscreen |
| `EP-P-API` (P5) | p50/p95 эндпоинтов, число SQL, EXPLAIN дорогого SELECT, байты JSON, event-loop lag | равные строки/поля/значения на фиксированном датасете, единый `param_catalog`, RBAC/effective values, без нулей при таймауте | V + свип; вкладки с большим числом записей, два админа, граничные страницы |

Сквозные строки дополнения (`PAR-01..PAR-05`, `P-SPEC-PARITY`, `P-GENUINE`) принадлежат `EP-P-ACCEPT`;
`P-SPEC-PARITY` — спецификационная опора (§0.3 «быстрее админка vs сохранить дизайн»), `P-GENUINE` — запрет
выдать косметический skeleton за приложение или скрыть задержку за анимацией.

## 5. Существующее vs отсутствующее (текущее дерево, ветка `evol/impl`)

Вердикты: `DONE_AND_VERIFIED` / `PARTIAL` / `MISSING` / `CONFLICTS_WITH_NEW_CONTRACT` / `NOT_APPLICABLE`.

### E — обучение на опыте

| Предмет | Где сейчас | Вердикт |
|---|---|---|
| Канонический гейт рекомендаций | `services/mca_experience.py:1000-1015` (docstring «только из канона», `CANONICAL_RECOMMENDATIONS.get((type, rule_key))`, `None` → no-op, свободный текст → no-op), каталог `:103`, запрет неканонического текста для global `:306-307` | **CONFLICTS_WITH_NEW_CONTRACT** (E5.1/E5.2): смысловой урок обязан проходить; сохраняются safety/scope/права. Примечание: источник называет владельцем `ExperienceService.propose`, фактически это `LessonService.propose` (`:988`, `:994`) — дрейф зафиксирован |
| Схема batch-экстрактора | `services/mca_experience_jobs.py:385-405` (закрытый JSON-контракт), `:408-423` (окно: msg/chat/user), `:426-469` (whitelist полей), `:477-498` (rejection) | **PARTIAL**: нужны candidate_kind/source_message_refs/target_bot_output_ref/old_claim/proposed_revision/applicability/exceptions/evidence_refs + reply/time/bot-output refs |
| Skip-эвристики классификатора | `services/mca_experience_jobs.py:314-379`; коды `:169-179`; порядок «шутка/агрессия/третье лицо/спор до коррекции» `:341-351` | **CONFLICTS_WITH_NEW_CONTRACT** (E4.4): детектор должен ранжировать, не отсекать |
| Token/prefix `relevance_score` | `services/mca_experience.py:421-448` (токены + префикс 5 символов), используется в `select_for_context` `:1440-1456` | **CONFLICTS_WITH_NEW_CONTRACT** (E6.1/E6.2) |
| `self_reflection` | `services/self_reflection.py:24-29` (промпт), `:47-57` (cap), `:93-133` (суть + статусы) | **PARTIAL**: суть есть, связи «старая ошибка ↔ поздняя поправка» нет |
| Счётчики oversight | `web/api/oversight_router.py:383-487` (эпизоды/уроки по статусам/применения по outcome/feedback, `:479-482` «unknown ≠ провал») | **PARTIAL**: нет discovered/missed, merged/superseded-дельты, времени до durable, token/LLM usage, ошибок/ретраев |
| Модель уроков/применений (DDL) | `services/database.py:1200-1236` (`mca_lessons`, закрытый CHECK `type` `:1203-1205`, статусы `:1213-1214`), `mca_lesson_applications` `:1243-1266` (outcome success/failure/unknown `:1254-1255`) | **PARTIAL**: аддитивные колонки для principle/applies_when/… и стадий; расширение CHECK |
| Операции над уроками | `services/mca_experience.py:1145` activate, `:1186` suspend, `:1243` revise, `:1312` merge, supersede-поля `:189` | **PARTIAL**: ADD/NOOP/SUPERSEDE смыслового содержания нет |
| Собственные выводы бота (self-reference) | `services/bot_output_ledger.py:4-16` (durable `mca_bot_outputs`, append-only, kill-switch), `:69-71` (`SourceRef bot_output:<id>`), `:107` (запись) | **PARTIAL/REUSE**: фундамент есть, пути «вспомнить, что я утверждал» в диалоге нет |
| Витрина «Опыт» | `web/index.html:4129-4258` (таблица уроков, карточка, suspend/activate, след, полезность), цепочка D05 `:4148-4176`; API `web/api/memory_agi.py:1501`, `:1553` | **PARTIAL**: нет построчного раскрытия применения→исход→ревизия (E7.5/E-26) |
| Журнал `mca_events` | `services/mca_events.py`, вызовы `mca_experience.py:1057,1408,1863` | **DONE_AND_VERIFIED** (механизм переиспользуется) |

### P — производительность админки

| Предмет | Где сейчас | Вердикт |
|---|---|---|
| `CacheControlStaticFiles` no-store | `web/app.py:73-94` (`_NO_CACHE_SUFFIXES = (".html",".js",".css")` `:80`, заголовок `:90-93`), `app.css`-маршруты `:297-316`, HTML `:394-403` | **CONFLICTS_WITH_NEW_CONTRACT** (P3.1.1/2/3) |
| Порядок vendor-скриптов | `web/index.html:17` (telegram-web-app), `:14809` vue, `:14813` dompurify, `:14816` chart, `:14821` ogl, `:14822` liquidglass, `:14825` delaunator, `:14826` aurora-flow, `:14832` polygon-background, `:14837` glass-probe, `:14838` glass, `:14843` glass-refraction, `:14848` execution_graph, `:14854` cognitive-map, `:14858` fullscreen-policy, `:14859` app.js, `:14862` telegram-init — все синхронные, без defer/async | **CONFLICTS_WITH_NEW_CONTRACT** (P3.1.4) |
| Размеры ресурсов | `web/app.js` 1 681 966 Б (31 214 строк), `web/index.html` 1 126 126 Б (≥14 862 строк, все x-template модулей с `:14620`), `web/static/app.css` 421 508 Б; vendor: chart 208 522, vue 167 536, ogl 133 237, telegram-web-app 116 510, liquidglass 77 015, dompurify 29 369, delaunator 8 454 | **MISSING** (измерения): есть только сырые размеры; transfer/сжатых байт, traces, long tasks нет. Текущее дерево заметно больше публичного master из §P1 — зафиксировать как факт, не как «ухудшение» |
| Версия в URL | `config/settings.py:3472` `APP_VERSION = "2.58.144"` (ручная строка), подстановка `web/app.py:97-121,267-268` | **CONFLICTS_WITH_NEW_CONTRACT** (P3.1.2): версия не связана с байтами файлов |
| Сжатие | ни `GZipMiddleware`, ни `CompressionMiddleware` в `web/app.py`/`bot.py` (`uvicorn.Config` `bot.py:1480`); Caddyfile в репозитории нет | **MISSING**: подтверждение brotli/gzip/`Vary` — только на реальном proxy (DevOps-доказательство) |
| API/SQL горячие пути | `web/api/routes.py:456-560` `/config`: `db_override_map` `:476`, `access_for` `:480/488`, цикл по всем параметрам с `effective_matrix` `:489-523`; read-path `web/api/oversight_router.py:263,383` | **PARTIAL**: профилирования и keyset-пагинации нет |
| Тяжёлая клиентская поверхность | все модули одним `index.html` (x-template `:14620,14655,14725,14772,14809`), Chart.js грузится всегда `:14816` | **CONFLICTS_WITH_NEW_CONTRACT** (P3.2.6-7) |
| Инструментарий измерения | `tools/ui_round1025_matrix.py:45-105` (статика/вьюпорты/маршруты), `tools/ui_*_e2e.py` (Playwright), `tools/mca18_paired_replay.py` (paired replay), `tests/js/` | **REUSE** — новый харнесс не нужен |
| Hash-маршруты/deep link | `#/…` маршруты (`tools/ui_round1025_matrix.py:53-62`) | **PARTIAL**: есть, но должны выжить при разделении монолита |

`NOT_APPLICABLE` в текущем дереве: внешние архитектуры Reflexion/Mem0/A-MEM/Letta (идеи, не зависимости);
второй векторный индекс и «второй мозг» — запрещены источником.

## 6. Архитектурная классификация (до Builder)

- **ARCHITECT_REQUIRED** — `EP-E-EXTRACT` (версионированная схема кандидата: поля, валидация refs,
  совместимость/миграция, provenance), `EP-E-GATE` (где живёт семантический скоринг: переиспользование
  `mca_retrieval_context` против опыта; согласование с `MEM-CONTRACT`), `EP-E-LESSON` (миграция
  `mca_lessons`, расширение CHECK `type`, семантика ADD/REVISE/MERGE/SUSPEND/SUPERSEDE/NOOP),
  `EP-P-BOOT`/`EP-P-SCRIPTS` (границы модулей фронта, порядок загрузки, deep link, одновременно
  FINAL v8 UI-BOOT/SELECTOR/MODULES), `EP-P-API` (контракт keyset-пагинации между API и app.js).
- **ARCH_REUSE_CONFIRMED** — `EP-E-DIALOGUE` (существующие Observer/Planner-контекст и
  `bot_output_ledger` SourceRef, новых интерфейсов не требуется), `EP-E-OUTCOME` (существующие таблицы
  mca16 + funnel-эндпоинт, аддитивная миграция), `EP-P-CACHE` (существующий `StaticFiles`-сабкласс и CSP;
  правило immutable-vs-revalidation задано источником), `EP-P-ANIM` (локальные runtime-guard'ы),
  `EP-H-HELP` (существующий канон/доставка `info_service`), `EP-GUARD` (read-only контроль).

## 7. Риски и порядок доказательств

- R3: `EP-E-DIALOGUE` (меняет поведение ответа) и `EP-P-BOOT` (монолит фронта) — сначала минимальный
  слайс с наблюдаемым эффектом, затем расширение; любые правки после — только по evidence.
- R2: миграции (`database.py`) и витрина; обязательный rollback-путь и идемпотентность.
- R1: измерение/аудит — без изменения продакшн-поведения.
- Все `NOT_VERIFIED` и отсутствующие device-trace остаются `NOT_VERIFIED`: H и общий DONE не выставляются
  по зелёным тестам.
