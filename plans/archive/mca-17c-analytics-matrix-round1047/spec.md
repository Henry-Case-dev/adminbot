# MCA-17 `mca-17c-analytics-matrix` — spec.md (Step 2 @Architect, design-freeze, 07.10.2026)

**Статус:** ✅ **DESIGN-FREEZE** (T-5177/T-5178 выполнены). Артефакты — 3 файла: `spec.md` (этот) + `adr-1028-23-analytics-matrix.md` (Proposed; 1028-21 занята mca-12, 1028-22 — mca-21, 1028-23 свободна — grep plans/** 07.10.2026) + `plans/docs/mca-round1027-arch-frames.md` **§1.2.12**. Ответы Q1–Q8 — §10. Threat-failure-analysis — **§8 внутри spec** (решение Q5: масштаб компактный — write-path = 1 endpoint под существующим RBAC; отдельный файл по прецеденту mca-12 не заведён; Scanner T-5197 якорится на §8). Head `b25558e`; прод 2.58.65 (mca-12 VERIFIED); SQLite v33; каталог 523; KS 85; reason 279; тулы 14; реестр — 47 `ProcessDefinition` (grep HEAD 07.10.2026).

**Ядро фичи:** mca-17c — **read-side потребитель + UI** поверх замороженных контрактов mca-17a/13/16/18/19/20. Второй store/аналитика/канал/контрольный контур запрещены (§100.4 `ARCHITECTURE.md:4146`, CA-17C-1). Все, что матрица показывает, уже в событиях/таблицах/реестре.

## 0. Scope / исключения

**В скоупе (REQ MCA17-R1-доля/R2/R6/R8/R9/R10):** представления «Обзор процессов»/«Запуски»/«Инциденты» внутри существующего `#/oversight` (лейбл «Аналитика» — переименование существующего «Диагностика», `web/app.js:399`; нового маршрута/дублирующей страницы analytics НЕТ); 5 уровней детализации; фильтры; deep links; матрица покрытия §27.1 + сверка реестра; A73-виджеты self.model/vision.media/temporal.factcheck; воронка самообучения §27.8; граф урока + «Эффект»; фуннель личности §28 `:1588` (три статуса); диагностические действия + экспорт §27.9; критерий завершения §27.10 + замер нагрузки телеметрии; carry-over UI-долги (T-5192, Q7).

**Вне скоупа (доставлено mca-17a ✅ §100; расхождение UI = дефект рендера, не второй контракт):** MCA17-R3/R4/R5/R7 — span-контракт mca_events, состояния/честный итог backend, heartbeat/watchdog/lease/fencing/recovery, хранение/ретенция/безопасность телеметрии. 17c их **отражает** (stalled/partial/degraded/gaps/telemetry_degraded как read-render контракта), не переопределяет. Также вне: второй store/агрегатор, второй event-канал, свой control-механизм мимо TaskSupervisor, новые widget-ID, вторые витрины mca-16/18/19/20, перенос витринных виджетов вглубь, fault injection в прод, произвольный код/SQL из UI, рассылки чат/DM/email, шкалы сознания/фиктивный IQ, платные внешние сервисы (GEN-R2).

**§27-покрытие:** §27.1→§1; §27.2→§2; §27.6→§3; §27.8+§28 `:1588`→§4; §27.9→§5; §27.10→§6; §27.3/27.4/27.5/27.7 — §0-отражение (read-render контракта mca-17a: статусы 9+partial/degraded/stalled, heartbeat≠progress, ретенция «детали удалены по сроку хранения»).

## 1. Реестр, карточки процессов, матрица покрытия (§27.1, `:1331–1364`; R1-доля; A48)

- **D1.** Карточки процессов — рендер существующего `GET /api/oversight/processes` (`oversight.py:198`, registry_snapshot): назначение простыми словами, enabled/effective state, «сейчас», последний успех/ошибка, pending/active, свежесть телеметрии, итог. 47 code-declared карточек видимы все; честные `not_run`/`disabled`/`unavailable`/`not_implemented` (`:1480`); K-OFF → disabled с причиной (не нули); игровая заготовка → not_implemented без имитации запусков.
- **D2.** Группировка связанных подфункций в одну карточку с вкладками — каждая подфункция сохраняет собственный фильтр/этап и drill-down (`:1362`). Матрица §27.1 (18 строк `:1341–1360`) + процессы MCA-18/19/20 (`:1364`) + фактические процессы вне таблицы — обязательный охват; строка матрицы = группа карточек/фильтр, не отдельная страница и не новая цифра.
- **D3.** Сверка реестра ↔ фактические handlers/workers/расписания/инструменты + mapping стадий на события — артефакт T-5191 (отчёт §21 п.5). «Число карточек не доказывает покрытие» (`:1337`). Незарегистрированный процесс/нужный новый widget-ID — эскалация @Architect (+mca-17a), не self-serve (CA-17C-7; прецедент `vision.analyze v0→v1`).
- **SC:** каждая из 47 карточек с честным состоянием; активные функции связаны со стадиями/виджетом (A48); матрица покрытия заполнена — нет строки без widget/drill-down/trace или честной причины; общесерверный scope явно отделён от чат-вида.

## 2. IA «Аналитики», уровни, фильтры, запуск (§27.2, `:1366–1384`; R2; A54)

- **D4.** Внутри `#/oversight` три представления («Обзор процессов»/«Запуски»/«Инциденты») + лейбл «Аналитика». Фильтры чат/время/process/статус/trigger/модель-версия — **серверная валидация/фильтрация** (client-side trust запрещён; deep link переживает обновление).
- **D5.** Уровни 1–5 (`:1374–1378`): карточка → виджет функции → запуск (граф + timeline) → этап («Источники»/«Результат»/«Логи», ожидаемый/фактический выход, ошибка + действие) → исходный объект в **существующей** карточке с текущими правами (без дублей карточек). Из ошибки — родительская операция и затронутые результаты; из виджетов витрин/«Памяти» — deep link на конкретный trace/этап (контракт ссылки 17c, рендер якоря — компакт-витрины mca-12, CA-17C-3).
- **D6.** ExecutionGraph — **AMEND-adapter** (`window.ExecutionGraph`, web/app.js:2863/2931, pipeline_analytics.py `build_run_view:829`), не замена. Граф только при ветвлениях/зависимостях; линейное — вертикальный stepper/timeline; summary-узел разворачивается; mobile — список стадий; цвет + текст/иконка; reduced motion/клавиатура. **Обновление не сбрасывает раскрытые узлы/прокрутку/выбранный trace** (A54).
- **D7.** Прогресс с известным denominator (N из M; stage completion и успешность отдельно); без объёма — стадия/счётчики/время, без выдуманных %; анимация = наблюдаемая активность, прекращается при stale/unknown («здоровье по локальному таймеру» запрещено, `:1384`/`:1422`). Run-карточка: статус по контракту pipeline version (succeeded/partial/degraded/failed/interrupted; stalled — диагностическое, не подмена outcome); «зелёный» = завершение необходимых этапов, не получение текста от LLM; очередь/провайдер отдельно от исполнения; нулевой результат/валидное молчание ≠ падение; ошибка SQL/парсинга ≠ «нет воспоминаний»; ошибка ветви не стирает успехи других (`:1402–1408`).
- **SC:** фильтры применяются на сервере; A54 — refresh/reconnect сохраняет UI-состояние, stale не выглядит healthy; граф только где ветвления; частичные/degraded/stalled различимы.

## 3. Инциденты (§27.6, `:1426–1436`; R6; A55-UI)

- **D8.** «Инциденты» — рендер `GET /api/oversight/incidents` + `/changes?since_ts` (`oversight.py:220/:244`): стадия, серьёзность, первое/последнее обнаружение, повторы, затронутые jobs/chats, влияние, восстановление, ссылка на trace. **acknowledged ≠ resolved**; recovered/resolved — после реальной проверки; история сохраняется; группировка по fingerprint (разные симптомы не сливаются по слову «timeout»); fallback понижает влияние, не скрывает сбой. Компактный индикатор на витрине + прямой переход. Доставка ≤10s — существующий polling-транспорт mca-17a; reconnect — cursor-догон; UI при потере backend — telemetry stale/unknown.
- **D9.** UI-порядок severity по числовому ключу — carry-over F14 (T-5192). Порядок отображаемых статусов = read-render контракта mca-17a, не новый словарь.
- **SC:** инцидент виден ≤10s в открытом миниаппе; ack не меняет resolved; reconnect догружает без дублей (A54/changes-calls); рассылки и публикация stack traces пользователям отсутствуют (`:1436`).

## 4. Самообучение, фуннель личности (§27.8, `:1452–1462`; §28 `:1588`; R8; A57)

- **D10.** Воронка за период: episodes → candidates → validated/active → rejected/suspended → applied → known success/failure/unknown; у каждого числа единица и scope; feedback ≠ уникальные lessons. Источник — существующие counters/API mca-16 (`experience_snapshot` `status_service.py:593`, `/api/memory/lessons*`) + агрегатный read-GET `GET /api/oversight/experience/funnel` (см. §7) — **без второго store/агрегатора**; unknown отображается как unknown.
- **D11.** Граф урока: эпизоды-основания, проверочные примеры, версия, scope, конкурирующий/замещённый урок, применения, feedback; клик перехода — причина. «Эффект»: доступные сравнения + объём наблюдений; нет данных — «эффект ещё не измерен»; unknown ≠ провал/успех; принятый candidate ≠ доказанный рост. Разделение представлений (`:1462`): лента «Опыт» на «Статусе» (mca-16) сохраняется; граф — в «Аналитике»; правка/отключение — в существующей «Памяти» переходом из карточки. Одни записи, разные представления, без собственного состояния.
- **D12.** Фуннель личности (handoff mca-18 D8, `ARCHITECTURE.md:4533`; реестр `:1063`/`:1083–1085`): в виджете «Что сейчас формирует характер» три различных статуса — **«передано модели»** (prompt_render) ≠ **«проявилось по оценке»** ≠ **«доказан сравнительный эффект»** (replay, вне процесса); per-rule included/excluded/conflict/stale + причина + frame version + trace (стадии observation_read→final_check, `:1064–1070`); причинность одному факту включения в prompt не приписывается (`:1588`).
- **SC (A57):** при unknown outcome улучшение не выдумывается, видны основания и недостаток измерений; три статуса фуннеля различимы на реальном прогоне; excluded/conflict/stale — с причинами.

## 5. Диагностические действия и проверка отказов (§27.9, `:1464–1474`; R9; A56)

- **D13 (Q2).** Write-API **санкционирован в узком объёме**: один endpoint `POST /api/oversight/jobs/{job_id}/action` (action: cancel/resume/retry в payload). Обоснование: A56 — приёмка mca-17c по §100.4 `:4146` («mca-17c реализует… A56»), вариант «только экспорт/просмотр» приёмку не закрывает. Действия идут **через существующий механизм задач** (TaskSupervisor/task_jobs — свой контрольный контур запрещён CA-17C-1): cancel/resume — через существующие операции supervisor (`task_supervisor.py:547` recover_stale, `:709` set_next_retry — AMEND-вызовы, не новый контур); retry = новый attempt по контракту mca-17a (прошлая ошибка не затирается). RBAC `requires_global_admin()` (прецедент killswitch `oversight.py:294`); actor/audit-событие `oversight_job_action` (+1 reason_code, §7); идемпотентность — state-машина supervisor (повтор cancel на cancelled = no-op) + idempotency-key. Запрещено: произвольный код/SQL; fault injection endpoints; повтор внешнего side effect без безопасной семантики; при delivery_unknown — доступная сверка, не слепой retry (`:1468`).
- **D14.** Просмотр/экспорт очищенного trace: сервер отдаёт уже маскированные данные (R17, sanitize до записи — mca-17a), экспорт — client-side download из полученного cleaned trace (отдельный route не создаёт). «Повторить отображение» — только чтение. Переход к настройке — ссылка в существующий каталог (без дублей).
- **D15.** 13 сценариев отказов `:1472` (timeout провайдера; невалидный JSON; ошибка записи после успешного LLM; отмена parent/child; гибель worker между checkpoint и terminal; рестарт; потеря heartbeat; живой heartbeat без прогресса; сбой log storage; reconnect миниаппа; ошибка одной ветви; неясный результат отправки; завершение shared task) — каждый проверяется через «владелец видит правильный статус/этап/причину/восстановление» по API/миниапп (T-5194), не только unit-исключение. Fixtures — без внешних платных операций; demo-данные — явная метка, отдельно от production (`:1474`).
- **SC (A56):** просмотр без действий — нет слепого дубля; доступ проверяется (global-admin; cross-chat отказ); действия идемпотентны с actor/audit; fault injection недоступен обычным и не включён в прод постоянно (`:1470`).

## 6. Критерий завершения наблюдаемости, prod-smoke (§27.10, `:1476–1484`; R10; Q6)

- **D16.** Для каждой строки матрицы/процесса: источник событий, рабочий widget, drill-down, success trace, пример ошибки/skip, права, тест актуальности; not_run/disabled/unavailable/not_implemented честно. Prod-smoke **двухступенчатый**: (а) live-приёмка на 17c-деплое — T-5199 владелец: A73-виджеты на реальных запусках, связность trace, видимость ошибки, актуальность timestamps, воронка из реальных counters; (б) финальный §27.10-smoke «после единого включения» волны + Live TMA/нагрузочный R3/e2e takeover — **mca-release** (handoff T-5200; чек-лист prod-smoke — артефакт T-5191/T-5194). Замер нагрузки телеметрии (число событий/рост хранилища, отсутствие блокировок writer path и неограниченных буферов, без обещания нулевого overhead) — dev-side на воспроизводимом прогоне (T-5194).
- **SC:** ни одна строка матрицы не закрыта фразой «логи добавлены»; замер зафиксирован в evidence; наблюдаемость идёт в одном выпуске с функциями.

## 7. Санкции (T-5178; = ADR-1028-23 D9–D16 = arch-frames §1.2.12, цифра-в-цифру)

| Санкция | Значение | Основание |
|---|---|---|
| Deploy (Q1) | **CA-11, пер-фичевый bump 2.58.65→2.58.66** на отдельном окне после mca-12; план `:213` DEFERRED_TO_RELEASE superseded Step 2 (прецедент mca-12 `:212`/§1.2.10); fallback — DEFERRED_TO_RELEASE, если окно недоступно до mca-release (SSH/fail2ban-гейт; решает @DevOps на окне) | read-side, Δ DDL=0 → тривиальный откат; ранняя owner-приёмка T-5199 до mca-release |
| Δ DDL | **0** (v33 не растёт; SQLite+PG без миграций; `pg_db.py` вне diff) | read поверх существующих v21/v33-таблиц, `mca_events`, `task_jobs` |
| Δ каталога | **0** (REGISTRY 523 = 523; F8 NOT_APPLICABLE; рендер существующих ParamSpec) | переход к настройке = ссылка, не новые настройки |
| Δ kill-switches | **0** (85 остаётся; защита write-API = RBAC+audit+идемпотентность; OFF-паритет из реестра — рендер) | прецедент killswitch `oversight.py:294` без отдельного KS |
| Δ reason_code | **+1**: `oversight_job_action` (actor/audit cancel/resume/retry) — 279→280 на пакете, 269→270 vs HEAD | словарь не содержит control-action кода (`mca_events.py:94–100` — только incident_*/telemetry/spool) |
| Δ тулов | **0** (14 = 14; METERED_TOOLS без изменений) | API/UI фича, инструменты бота не трогаются |
| Реестр/widget-ID | **47 = 47; новых widget-ID 0**; self.model/vision.media/temporal.factcheck — рендеры | CA-17C-7; нехватка → эскалация @Architect |
| Δ routes (Q3) | **+3** на существующем `oversight_router` (`web/api/oversight.py`, byte-freeze `routes.py` — прецедент mca-12): `GET /api/oversight/runs` (фильтрованный список runs, keyset-пагинация, серверные фильтры), `GET /api/oversight/experience/funnel` (периодные агрегаты из counters mca-16; read-only SELECT), `POST /api/oversight/jobs/{job_id}/action` (D13); RBAC read — существующий global-admin oversight-гейт, POST — `requires_global_admin()`; `ROUTES_SHA256_F11` — один финальный re-pin на пакете (L-F11S-1; mca-12 +5 уже в проде 2.58.65 — конфликтов нет) | runs-списка/воронки/действий на HEAD нет (grep `:430/:471`) |
| Carry-overs (Q7) | **В пакете** (T-5192): F14/F15/F16 UI-паритет, mca-06 M-2 (chain UI), L-3 (unchanged-метка), F12-display (расхождение runtime vs KS). **Не в пакете**: F12-backend (унификация резолва product-гейтов) — отдельный фикс-слайс после 17c (CA-17C-1: backend реестра/гейтов не трогается) | read-side долги закрываются рендером; backend-резолв — отдельная санкция |
| Baseline (Q8) | Двухуровневый: абсолют — пост-mca-12 **2.58.65** (фикс @DevOps на окне T-5198); дельты 17c от него: DDL 0 / каталог 0 / KS 0 / reason +1 / тулы 0 / routes +3 | прецедент mca-12 §1.2.10 |
| Risk (Q5) | **R2 confirmed** (не R3: DDL=0; write-path = 1 endpoint под существующим RBAC поверх supervisor; нет новых внешних поверхностей/провайдеров/секретов) | план `:213`; threat §8 |

## 8. Категория, Risk, threat-failure-analysis (Q5)

Категория: UI/read-API поверх замороженных контрактов; Risk **R2 confirmed**. Threat-поверхность и mitigation:

- **TH-1 Привилегия-эскалация через write-API.** Mitigation: `requires_global_admin()`; cross-chat отказ; actor-аудит в `oversight_job_action`; идемпотентность; отказ от произвольного кода/SQL/fault injection; действия только по существующим операциям supervisor. Проверка: T-5193 RBAC-тесты + T-5197 Scanner.
- **TH-2 Cross-chat утечка через фильтры/deep links.** Mitigation: серверная фильтрация и chat-scope валидация в обоих GET; client-side trust запрещён; access_scope из контракта mca-17a.
- **TH-3 Утечка секретов через trace/экспорт/логи.** Mitigation: R17 — sanitize до записи (mca-17a), экспорт из уже очищенных данных, error-cause очищен; секреты/cookies/initData не попадают в UI/экспорт (`:1450`); stack traces не публикуются пользователям (`:1436`).
- **TH-4 Инъекция/DoS через фильтры и funnel-агрегацию.** Mitigation: параметризованные запросы, лимиты периода/размера, keyset-пагинация, batch-read без writer-lock; funnel — ограниченный период по умолчанию.
- **TH-5 Двойной side effect при retry.** Mitigation: retry только для безопасных этапов по checkpoint-семантике mca-17a; delivery_unknown → сверка, не retry (`:1468`); идемпотентность state-машиной.
- **TH-6 UX-ложь (stale как healthy, выдуманный прогресс/эффект).** Mitigation: D7/D10/D11-ограничения + A54/A57-тесты + §27.10-проверка актуальности статуса.
- **TH-7 DOM-инъекция из payload событий.** Mitigation: существующие UI-практики экранирования/DOMPurify (прецедент mca-12), без raw-HTML рендера событий.
- **TH-8 Раздутый audit-след действий.** Mitigation: одно событие на действие с reason в detail; без дублирования в телеметрию-агрегаты.

Оценка: 0 Critical/High при mitigation; эскалация до R3 не требуется.

## 9. Риск-лист / AMEND / REUSE

**AMEND:** `web/app.js` (oversight-экран: представления/фильтры/уровни/граф/лейбл; ExecutionGraph-adapter), `web/index.html`, `web/static/app.css`, `web/api/oversight.py` (+3 routes, D13), `services/mca_events.py` (+1 reason_code), `services/pipeline_analytics.py` (read-хелперы списка runs — без смены контракта `build_run_view`), `services/task_supervisor.py` (только expose существующих операций для action-endpoint, без смены семантики), минимальные read-хелперы experience-агрегатов. **NEW:** не планируется (всё в существующих файлах; при необходимости Builder выносит funnel-запросы в отдельный модуль — согласуется с границей CA-17C-1). **Не трогаются:** `services/mca_process_registry.py`, `services/database.py`, `pg_db.py`, `param_catalog.py`, `routes.py` (byte-freeze), реестровые контракты mca-17a, папки mca-12/16/18/19/20.

**REUSE (grep-факты HEAD `b25558e`):** реестр 47 карточек + widget-ID (`mca_process_registry.py:933/:982/:1063/:1083–1085/:1115/:1154`); read-API oversight (`oversight.py:198/:220/:244`); runs по ID (`web/api/analytics.py:471`) + inspector (`:430`); `build_run_view` (`pipeline_analytics.py:829`); RBAC-прецедент POST (`oversight.py:294`); recovery/watchdog (`task_supervisor.py:547/:709`, `mca_watchdog.py:113`); experience-данные mca-16 (`status_service.py:593`, `/api/memory/lessons*`); ExecutionGraph-viewer (`web/app.js:2863/2931/5259`); polling-транспорт инцидентов mca-17a; компакт-витрины mca-12 как anchor-партнёр deep links (CA-17C-3). **Параллельность:** блоки A–F PARALLEL_SAFE по смыслу; SERIALIZE — `web/app.js`/`web/index.html`/`app.css`/re-pin (одна точка вставки, Dep-цепочка, старт после mca-12); routes/re-pin — один финальный пересчёт на пакете (L-F11S-1).

## 10. Ответы на 8 вопросов PM (requirements-map §5)

| Q | Ответ (кратко) | Где |
|---|---|---|
| **Q1 Deploy** | **CA-11, bump 2.58.65→2.58.66**, отдельное окно после mca-12; план `:213` DEFERRED_TO_RELEASE superseded Step 2 (прецедент mca-12 `:212`); fallback DEFERRED, если окно недоступно до mca-release (SSH-гейт, решает @DevOps). Причина: read-side, Δ DDL=0, ранняя owner-приёмка T-5199 | §7, ADR D9 |
| **Q2 Write-API** | **Да, узко**: один `POST /api/oversight/jobs/{job_id}/action` (cancel/resume/retry) через существующий supervisor-механизм; RBAC global-admin; actor/audit (+1 reason_code); идемпотентность; без fault injection/SQL/side-effect-retry. Вариант «только просмотр» отклонён — A56 прямо поручена 17c (§100.4 `:4146`) | §5 D13, §7, ADR D10 |
| **Q3 Δ routes** | **+3** (`GET /api/oversight/runs`, `GET /api/oversight/experience/funnel`, `POST /api/oversight/jobs/{job_id}/action`) на существующем `oversight_router`; byte-freeze `routes.py`; re-pin `ROUTES_SHA256_F11` — один финальный на пакете; конфликт с mca-12 (+5, в проде 2.58.65) отсутствует | §7, ADR D11 |
| **Q4 Δ каталог/KS** | **0/0 подтверждены**; F8 NOT_APPLICABLE; отдельный KS для мутаций не нужен (RBAC+audit+идемпотентность; прецедент killswitch). Δ reason_code **+1** — вне каталога/KS, аддитивен | §7, ADR D12/D13 |
| **Q5 Threat/R2** | **R2 confirmed**, эскалация к R3 не требуется; threat-раздел — **§8 внутри spec** (прецедент mca-21; отдельный файл не заведён — поверхность компактна: 1 write-endpoint + экспорт из очищенных данных) | §8, ADR D14 |
| **Q6 Prod-smoke** | Двухступенчато: (а) на 17c-окне — live-приёмка владельца T-5199 (реальные запуски, трассы, ≤10s-инциденты); (б) §27.10 «после единого включения» + Live TMA/нагрузка R3/e2e — **mca-release** (handoff T-5200, чек-лист — артефакт T-5191/T-5194) | §6 D16, ADR D15 |
| **Q7 Carry-overs** | В пакете (T-5192): F14/F15/F16 UI-паритет, mca-06 M-2/L-3, F12-display. Отдельным слайсом: F12-backend (унификация резолва product-гейтов) — 17c backend-резолв гейтов не трогает (CA-17C-1) | §7, ADR D16 |
| **Q8 Baseline** | Двухуровневый: абсолют 2.58.65 пост-mca-12 (фикс @DevOps на окне T-5198); дельты 17c: DDL 0 / каталог 0 / KS 0 / reason +1 / тулы 0 / routes +3 | §7, ADR D13-строка baseline |

## 11. Риски приёмки

- **R-a:** 47 карточек — число на HEAD; финальная сверка реестра при деплой-окне может дать иное (чужие фичи). Mitigation: D3-эскалация, T-5191-сверка, а не хардкод числа в UI.
- **R-b:** funnel-агрегация при больших периодах — нагрузка на SQLite. Mitigation: TH-4-лимиты; dev-замер T-5194.
- **R-c:** AMEND `task_supervisor.py` может расшириться — если существующие операции не покрывают action-семантику, останов и эскалация @Architect (не изобретать новый control-контур).
- **R-d:** SSH/fail2ban нестабилен → fallback DEFERRED (Q1); AGENTS.md-дисциплина: один recon + один деплой-прогон.
