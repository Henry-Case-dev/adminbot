# Spec — S9 `summary-testing-ui-round1026` (Эпик 2, шаг «Тестирование из Mini App», §113)

- **Автор:** Step 2 @Architect (23.09.2026). Файл ТЗ (`plans/current_task.md`) — только чтение (R17/R18).
- **Тип:** UI (Mini App, Vue-global/zero-build) + backend API (dry-run предпросмотр). **P0**.
- **ADR:** `adr-1026-8-summary-test-run-dry-run-ui.md` (D1–D8).
- **Врезка:** ON-путь (`L1 → пакет → L2`) выполняется **только внутри тест-прогона**; глобальный kill-switch `SUMMARY_HYBRID_L2_ENABLED` **не включается**, живой `_run`/OFF-путь **байт-в-байт**. Реальная публикация — гейт **S6/S10 + D4** (ADR-1025-24).
- **Baseline (заявлено; подтверждает @DevOps T-3345):** HEAD `ae5a147`, `APP_VERSION` **2.58.24**, pytest `.venv` 8807/0, JS 43/43, каталог 469/426/444/100/98/21, Δ DDL=0 (SQLite v12).

## 1. Цель и контекст

§113 задаёт маршрут «Модули → Сводки чатов → Тестирование»: администратор выбирает **чат** и **временное окно**, нажимает «Проверить пайплайн» и видит прогон пайплайна Эпика 2 (`фильтр S1 → восстановление S2 → L1 §95 → пакет §96 → L2 §98/§99 → форматтер §105` + предпросмотр Rich Message + токены/стоимость/ошибки). Прогон **не публикует** сообщение, **не изменяет память**, **не вызывает `generate_image`** без отдельного подтверждения.

S9 — первый потребитель уже поставленных модулей S1–S5 (врезка ON в живой путь GATED). Тест-контур даёт владельцу наблюдаемый dry-run без открытия публикационного гейта.

## 2. Границы

**В scope S9:**
- Новый dry-run сервис `services/summary_test_run.py` (оркестрация S1–S5, 0 побочных эффектов, ровно 2 LLM-вызова L1+L2).
- Аддитивный публичный метод `SummaryGenerator.build_test_rows(...)` (read-only окно + S1/S2), без правок тела `_run`/`_run_hybrid_l2`.
- Runtime-доступ к генератору: `services/web_runtime.py` (+`set_summary_generator`/`get_summary_generator`), вызов из `bot.py`.
- Новый API-роутер `web/api/summary_test.py` (включается в `web/app.py`); `web/api/routes.py` — **вне diff**.
- UI: вкладка **«Тестирование»** модуля «Сводки чатов» (`#/modules/summary/testing`) в `web/index.html` + `web/app.js` (витрина, Δ каталога=0).
- env-only флаг `SUMMARY_TEST_UI_ENABLED` (default **ON**), ClassVar, Δ каталога=0.
- Логи `SUMMARY_TEST_*` (аддитивные, R17-safe), тесты, evidence.

**Вне scope (не трогать):** `generate_image`/`compose_cover_image_prompt`/`_resolve_cover_prompt`/обложка/порядок публикации (§104, только переиспользование существующего пути при подтверждении); `summary_filter.py`/`summary_context_restore.py`/`summary_l1_*`/`summary_fact_package.py`/`summary_l2_writer.py`/`summary_article_formatter.py` (S1–S5 — только вызов); `summary_xml.py`; `system2_handoff.py`; `summary_memory.py` (кроме read-only методов); S6 (публикационный адаптер — GATED), S7 (`run_id`/log viewer §110), S8 (ExecutionGraph §111), S10 (§115); `web/api/routes.py`; `param_catalog.py`; DDL.

## 3. Трассируемость (REQ → verbatim §ТЗ → раздел → задачи)

| REQ | Источник (verbatim) | Раздел | Задачи |
|---|---|---|---|
| REQ-S9-01 | §113 «Модули → Сводки чатов → Тестирование.» | §5.1, §6 | T-3358 |
| REQ-S9-02 | §113 «Администратор выбирает: Чат. Временное окно.» | §5.2 | T-3359 |
| REQ-S9-03 | §113 «Кнопка: "Проверить пайплайн".» | §5.2 | T-3359 |
| REQ-S9-04 | §113 «Тестовый запуск не должен публиковать сообщение в чат.» | §4.1, §7 | T-3349, T-3368 |
| REQ-S9-05 | §113 «Показывать: Исходные сообщения… Предпросмотр Rich Message.» | §4.3, §5.3 | T-3353, T-3360 |
| REQ-S9-06 | §113 «Токены. Стоимость. Ошибки.» | §4.4, §5.3 | T-3354, T-3355, T-3361 |
| REQ-S9-07 | §113 «Не запускать generate_image… без отдельного подтверждения.» | §4.5, §5.4 | T-3351, T-3362 |
| REQ-S9-08 | §113 «Не изменять память.» | §4.2 | T-3350, T-3368 |
| REQ-S9-09 | §112 + «Если стоимость неизвестна: "Нет данных". Не показывать выдуманный $0.» | §4.4 | T-3354, T-3357, T-3361 |
| REQ-S9-10 | §114 (сценарии) | §9 | T-3370 |
| REQ-S9-11 | §106 «не публиковать пустое или выдуманное… без бесконечных повторов» | §7 | T-3365, T-3369 |
| REQ-S9-12 | ADR-1025-24 D4 + R17 + Δ DDL=0 | §8, §10 | T-3345, T-3372, T-3373, T-3374 |
| REQ-S9-13 | §46 «Показывать только применимые вкладки»; §7; §33 | §5.1, §5.5 | T-3358, T-3364 |
| REQ-S9-14 | §107/§114/§115 (deploy/bump — Step 2) | §10 | T-3346, T-3378 |
| REQ-S9-15 | §111 (S8), §110 (S7), §85 (S6) — вне S9 | §8 | T-3372 |

## 4. Наблюдаемое поведение и контракты

### 4.1. Dry-run семантика (D2) — «0 публикаций / 0 памяти / 0 `generate_image`»
Тест-прогон идёт **отдельным путём** `services/summary_test_run.py` и **не вызывает** ни одного публикующего/пишущего/генерирующего пути:
- **Публикация (0):** запрещены `services.telegram_send.send_text`/`send_rich_message`/`build_cover_media` и любые `SummaryGenerator._deliver_*`/`_send_*`/`_plain_fallback`/`_send_streaming`/`_send_chunked`/`_send_ux`. «Предпросмотр Rich Message» — **локальный рендер** через `summary_article_formatter.format_rich_html(document)` (без `tg://`-медиа) и `format_plain_html`; не отправляется.
- **Память (0):** запрещены `summary_memory.compress_and_purge`, `memorize_facts`, `remember_user_fact`, `memorize_self_reply`, `get_window_messages` (триггерит fire-and-forget бегущего конспекта → запись в `chat_running_summary`), `_build_running_summary`, досье/граф-записи, `INSERT/UPDATE/DELETE` в `smart_memory`/`graph_facts`/архив. Окно читается **read-only** через `db.get_smart_window(chat_id, since, limit)`; S1/S2 — чистые функции (`filter_window`, `restore_context`), обход цепочек (`collect_thread_chain`/`get_smart_message_by_tg_id`) — только чтение.
- **`generate_image` (0 по умолчанию):** вызов возможен **только** отдельным эндпоинтом подтверждения (D3/§5.4) через **существующий** `generate_image_verbose`; модель/провайдер/ключи/промпт/обработка ошибок/прикрепление — **не меняются** (§104).
- **Включение ON-пути:** per-run — тест-сервис напрямую вызывает `run_l1`/`run_l2` (S3/S5), которые **не зависят** от `SUMMARY_HYBRID_L2_ENABLED`; глобальный флаг и per-chat override **не читаются и не пишутся**. Ровно **2** физических LLM-вызова (L1+L2).
- **Доказательство:** тесты-шпионы (MagicMock/AsyncMock) на каждую запрещённую точку + проверка `llm.await_count == 2` + проверка неизменности `SUMMARY_HYBRID_L2_ENABLED`/`chat_params` до/после.

**Оговорка (фиксируется явно):** LLM-вызовы через `llm.generate` пишут **операционную телеметрию** (`llm_usage_events`, PG) — это не «память/досье»; она нужна §112 (токены/стоимость). Тест даёт ≤2 usage-события (module=`summary`), R17-safe (числа/модель/цены). При `dedicated`-слоте (`SUMMARY_L1_*`/`SUMMARY_L2_*` env) учёт usage не ведётся → метрики «Нет данных» (известное ограничение, follow-up S7).

### 4.2. Интерфейс `services/summary_test_run.py` (D1/D3)
```python
@dataclass
class TestRunResult:
    schema_version: int          # 1
    test_id: str                 # opaque, R17-safe
    status: str                  # ok|empty|invalid|error|skipped
    chat_id: int
    window: dict                 # {hours, from_ts, to_ts, messages}
    dry_run: bool                # True
    publication: dict            # {status:"not_published", reason:"dry_run"}  §112
    stages: dict                 # filter/l1/package/l2/format — статусы/метрики/причины
    artifacts: dict              # source/filtered/restored/clusters/package/article/rich_preview/plain_preview
    metrics: dict                # §112
    diagnostics: list[dict]      # {stage, code, reason, model, provider_host, http_status, attempts}
    display: dict                # {truncated_display, has_more, totals}

async def run_summary_test(chat_id, window, *, allow_cover=False,
                           correlation_id=None, generator=None) -> TestRunResult
```
- `window` — `{"hours": int}` (валидация 1..720; дефолт — `limits.summary_window_hours`); `since = now - hours*3600`; лимит строк — `limits.summary_max_window_messages` (переиспользование, Δ каталога=0).
- Оркестрация: `generator.build_test_rows(...)` → `run_l1(llm, rows, chat_id, correlation_id, focus_block=None)` → `build_fact_package(l1_result, build_l1_payload(rows, chat_id))` → `run_l2(llm, package, service=..., chat_id, correlation_id)` → `format_rich_html`/`format_plain_html`.
- `generator=None` → `web_runtime.get_summary_generator()`; нет генератора → `status="error"`, код `TEST_NO_GENERATOR` (API: `200` + `status="error"` при polling, **не** `503`; см. §5.2).
- `correlation_id` — существующий (формальный `run_id` — S7, не дублируется).

### 4.3. Состав предпросмотра (§113, D3)
Секции (порядок §113): **исходные сообщения → результат фильтра → кластеры L1 → пакет фактов → статья L2 → предпросмотр Rich Message (+ plain §105)**. Артефакты — **реальные** объекты S1–S5, без фиктивных данных. Rich-предпросмотр — `format_rich_html(document)` (H1/`<p>`/≤1 `<b>`, без обложки); plain — `format_plain_html(document)`. Если обложка сгенерирована подтверждением — показывается отдельным `<img>` (превью), тело статьи не меняется.
- **R17/объём:** секции отдаются **усечёнными срезами** с явными `totals`/`has_more` (per-message cap текста — 2000 символов с пометкой «обрезано»); пагинация — `?offset=`/`?limit=`. Полные тексты доступны только уполномоченному администратору выбранного чата; в логи не пишутся.

### 4.4. Метрики §112 и диагностика (D3/D5)
- §112: исходных / после фильтра / восстановленных, процент отсева, тем, токены L1/L2, стоимость L1/L2, общая, время, статус обложки, **статус публикации = «не публиковалось (dry-run)»**.
- **Источник токенов/стоимости:** учёт `llm_usage_events` (PG) по `correlation_id` прогона (`module="summary"`, `step ∈ {l1_clusterizer,l2_writer}`); стоимость — `llm_pricing`/`cost_usd`+`price_known`. Неизвестно (нет цены/PG/analytics OFF/dedicated-слот) → **«Нет данных»**, не `$0`. Безлимитный бюджет (`-1`-sentinel `resolve_chat_limit`) → **«Без лимита»**.
- Диагностика — только числа/коды/id/host (R17): этап, код, причина, модель, host провайдера, HTTP-статус, попытки. «Ошибка Саммари» без деталей **запрещена** (§109).

### 4.5. Форма «отдельного подтверждения» обложки (§113, D3)
Двухшаговая модель: прогон по умолчанию **не генерирует** обложку (в ответе `cover.status="not_generated"`). Явное подтверждение — отдельный эндпоинт `POST /api/summary/test/{test_id}/cover` c телом `{"confirm": true}`: переиспользует **сохранённый** `service.cover_prompt` прогона, вызывает существующий `generate_image_verbose(...)` (0 новых LLM-вызовов), возвращает `{cover_status, preview_url|error_class}`. Отказ/ошибка → понятный статус (`COVER_GENERATION_FAILED`), статья-предпросмотр остаётся (§106: текст готов, обложки нет → публикуется текст). Превью — `GET /api/summary/test/{test_id}/cover-image` (no-store, только зафиксированный сервером temp-файл задания; клиент путь не задаёт).

## 5. API / UI контракт (D1/D4)

### 5.1. Маршрут и вход
- UI: вкладка **«Тестирование»** модуля «Сводки чатов» — `#/modules/summary/testing`. Вкладка уже объявлена (`WORKSPACE_TABS.mod_summary` включает `testing`, label «Тестирование»); **новый tab-id не вводится** → Δ каталога=0. Секция рендерится при `workspaceModule.id==='mod_summary' && workspaceTab==='testing'` и флаге UI.
- Backend: **новый роутер** `web/api/summary_test.py` (прецедент: chat_lore/memory_agi/analytics). Telegram-команда **не вводится** (§113 — маршрут Mini App).
- Флаг `SUMMARY_TEST_UI_ENABLED` (env-only ClassVar, default ON): OFF → 404 на API + секция UI скрыта.

### 5.2. Эндпоинты
| Метод | Путь | Назначение | Права |
|---|---|---|---|
| POST | `/api/summary/test/run` | старт dry-run `{chat_id, window_hours}` → 202 `{test_id,status:"running"}` | global admin |
| GET | `/api/summary/test/{test_id}` | статус/результат (polling) | global admin |
| GET | `/api/summary/test/latest?chat_id=` | последний прогон для (user,chat) | global admin |
| POST | `/api/summary/test/{test_id}/cover` | подтверждение обложки `{confirm:true}` | global admin |
| GET | `/api/summary/test/{test_id}/cover-image` | превью обложки (no-store) | global admin |

- **Асинхронная модель:** `POST /run` создаёт задачу (`asyncio.create_task`), сразу 202; клиент опрашивает `GET /{id}` (прецедент ADR-1022-8; LLM-латентность + mobile). Store — **in-memory** (TTL 15 мин, ≤20 заданий), **без persistence/DDL**; рестарт процесса → результат теряется (осознанно, предпросмотр).
- **Rate-limit/стоимость:** ≥10 с на `(user, chat_id)`; повтор/параллельный прогон того же `(user,chat)` → 409. Потолок одновременных прогонов (≤2) → 429.
- **Безопасность (R17):** `chat_id` валидируется против доступных областей (reuse `GET /api/access/chats` / RBAC); без секретов/сырых ключей/промптов/сырых LLM-ответов в ответе и логах; тексты сообщений — только уполномоченному админу выбранного чата, не логируются.
- **Схема ответа:** `TestRunResult` (см. §4.2). Ошибки: 401/403 (права), 404 (флаг OFF/задание истекло), 409 (параллельный прогон), 422 (невалидный `chat_id`/окно), 429 (rate-limit). **503 не используется:** async-модель D4 (`POST /run` всегда `202`, `GET /{id}` — `200`), поэтому отсутствие генератора приходит как `200` + `status="error"` с кодом `TEST_NO_GENERATOR` (не 503). **Контракт-валидность:** ответ на всех путях (включая `error`/`running`) содержит полные `metrics`/`artifacts`/`display` (B-R1026S9-2).

### 5.3. UI-секции (D3)
Форма: селектор **чата** (reuse `accessChats`), селектор **временного окна** (пресеты 6/12/24/72/168 ч, дефолт — настроенное), кнопка **«Проверить пайплайн»**, состояния загрузки/ошибки/пустого окна, защита от повторного запуска. Результат: секции артефактов §4.3, блок метрик §4.4 («Нет данных»/«Без лимита»), диагностика, статус публикации «не публиковалось». Явная пометка dry-run («не публикуется», «память не изменяется») + предупреждение о расходах тест-прогона (2 LLM-вызова). Кнопка обложки — с подтверждением и предупреждением о расходе.

### 5.4. Mobile (§7/§33, REQ-S9-13)
Одна колонка; тач-область ≥44×44; без горизонтального скролла; длинные предпросмотры (исходные сообщения/статья/Rich) — отдельные экраны/шторки; существующие `.card`/`.btn-*`/design-tokens (без новых библиотек).

### 5.5. Применимость вкладки (§46)
Вкладка видна только когда у модуля есть тестируемое содержимое (существующее `_workspaceTabApplicable`/`workspaceTabHasContent` для `testing`); для `mod_summary` добавляется секция пайплайна. Существующие вкладки/маршруты не ломаются.

## 6. Данные и совместимость

- **Δ DDL=0** (SQLite v12; `database.py`/`pg_db.py`/SQL вне diff). Новых таблиц/полей нет.
- **Δ каталога=0:** новые параметры/промпты/слоты не вводятся; `SUMMARY_TEST_UI_ENABLED` — env-only ClassVar; tab/labels — JS-витрина. F8 **не переиздаётся**.
- **Backward compatibility:** live `_run`/`_run_hybrid_l2`/OFF-путь — байт-в-байт; новые модули вызываются только тест-сервисом; `routes.py` вне diff; S1–S5 не переписываются.
- **Миграции:** не требуются.

## 7. Fail-closed §106 и коды ошибок (D5)

| Условие | Результат | Публикация |
|---|---|---|
| окно пусто | `status=empty`, код `TEST_WINDOW_EMPTY` | нет |
| `L1Result` не usable (`empty/invalid/error`) | `skipped`/`invalid`, код `TEST_L1_*`, диагностика | нет |
| пакет не deliverable | `skipped`, код `TEST_PACKAGE_NOT_DELIVERABLE` | нет |
| L2 `empty/invalid/error` | `invalid`/`error`, код `TEST_L2_*` | нет |
| LLM недоступен (таймаут/ошибка) | `error`, код `TEST_LLM_UNAVAILABLE` + класс §106 | нет |
| ошибка форматтера | `error`, код `TEST_FORMAT_ERROR` (plain-даунгрейд в предпросмотре) | нет |
| непредвиденное исключение оркестрации | `error`, код `TEST_RUN_FAILED` + диагностика | нет |
| нет генератора/флаг OFF | `error`, `TEST_NO_GENERATOR` / 404 | нет |

Без бесконечных повторов (одна попытка; retry-политика — существующая у LLM-клиента). Классы §106 (`SUMMARY_GENERATION_FAILED`/`COVER_GENERATION_FAILED`/`RICH_MESSAGE_SEND_FAILED`/`TEXT_FALLBACK_FAILED`) — различимы в диагностике; фактическая публикация — S6.

## 8. Границы с S6/S7/S8 (D6)

- **S6 (публикационный адаптер, §100–§106):** **GATED** — S9 не вызывает публикующий адаптер; предпросмотр строится напрямую из форматтера S5. Если в будущем понадобится тест-API из S6 — соответствующий фрагмент помечается **GATED** и вне S9.
- **S7 (`run_id`, log viewer §110):** S9 использует существующий `correlation_id`; формальный `run_id` и фильтр логов — S7, **не дублируются**.
- **S8 (ExecutionGraph §111):** S9 не создаёт узлов графа; только аддитивные метрики/логи `SUMMARY_TEST_*`.
- **§85 (UI «Писатель», S6):** вне S9.

## 9. Приёмочные сценарии (§114, SC)

- **SC-01…SC-05:** несколько параллельных разговоров; короткие важные ответы; длинные сообщения; `reply_to`; упоминания — артефакты S1–S5 реальны, 0 публикаций/0 памяти.
- **SC-06:** почти пустой лог → `empty`, LLM не вызывается, понятное сообщение.
- **SC-07:** невалидный JSON L1 → fail-closed, диагностика этапа, нет публикации.
- **SC-08:** ошибка LLM → `TEST_LLM_UNAVAILABLE`, нет публикации, без повторов.
- **SC-09:** ошибка генерации обложки (подтверждение) → `COVER_GENERATION_FAILED`, статья-предпросмотр сохранена.
- **SC-10:** Rich Message с H1 → rich-предпросмотр содержит настоящий H1.
- **SC-11:** обычный текстовый fallback → plain-предпросмотр (`<b>`-заголовок, абзацы).
- **SC-12:** инварианты dry-run: шпионы 0 публикаций/0 памяти/0 `generate_image`; `await_count==2`; глобальный флаг не тронут; OFF-путь байт-в-байт.
- **SC-13:** метрики §112 + «Нет данных»/«Без лимита»; статус публикации «не публиковалось».
- **SC-14:** права/scope: не-админ → 403; чужой `chat_id` → 422/403; R17 (нет ключей/сырых ответов/текстов в логах).
- **SC-15:** UI-маркеры: маршрут `#/modules/summary/testing`, форма, dry-run-пометки, mobile-вёрстка; JS-тесты зелёные.

## 10. Зависимости, deploy, rollback (D7/D8)

- **Зависимости:** S1–S5 ✅ (модули); baseline @DevOps T-3345; S6 — **не** зависимость (GATED).
- **Deploy = ДА (T-3378 применим):** меняются рантайм (новый сервис + новый роутер + additive-метод генератора + `web_runtime`/`bot.py`/`app.py`/`app.js`/`index.html`/`settings.py`) → **bump `APP_VERSION` 2.58.24 → 2.58.25** + `README.md` + cache-bust; перед деплоем — минимальные §114-тесты; подтвердить, что `SUMMARY_HYBRID_L2_ENABLED` **не** включён глобально.
- **Откат:** annotated-тег `pre-round1026-s9` → baseline; hard — `git revert`; hot-OFF — `SUMMARY_TEST_UI_ENABLED=false`.
- **Тест-стратегия:** unit (сервис/API/guard-шпионы/метрики/fail-closed) + JS-маркеры + регресс живого пути (`await_count==2`, OFF байт-в-байт, §104/`generate_image`/публикация/XML вне diff); §114-сценарии как тест-кейсы (тестовые результаты **не** публикуются).

## 11. Открытые вопросы → закрыты (D1–D8)
(a) форма входа — §5.1; (b) состав/объём — §4.3/§5.3; (c) ON-путь в dry-run — §4.1; (d) «0 публикаций» технически — §4.1; (e) `generate_image` — §4.5; (f) deploy/bump — §10; (g) граница S6 — §8; (h) хранение/лимиты — §5.2 (in-memory TTL, Δ DDL=0); (i) Δ каталога — §6 (=0).

## 12. Риски и ограничения
- **High:** случайная публикация/запись из тест-пути → митигируется отдельным сервисом без публикующих вызовов + шпионы; fail-closed guard.
- **Medium:** стоимость тест-прогона (2 LLM-вызова × чат) → rate-limit ≥10 с, ≤2 параллельных, предупреждение в UI, флаг OFF.
- **Medium:** реальные usage-события пишутся в PG-телеметрию → задокументировано (§4.1), не «память/досье».
- **Low:** `dedicated`-слот → токены/стоимость «Нет данных» (follow-up S7); in-memory store теряется при рестарте (осознанно); R17-тексты в ответе доступны только админу, не логируются.
- **Ограничения:** §110/§111/§115 — S7/S8/S10; формальный `run_id` — S7.
