# ADR-1026-8 — S9 «Тестирование из Mini App»: dry-run контур (0 публикаций / 0 памяти / 0 `generate_image`), асинхронный API + UI-вкладка, Δ DDL=0 / Δ каталога=0

- **Статус:** Proposed (Step 2 @Architect, 23.09.2026; Accepted — фактом мержа §77 / T-3376)
- **Фича:** S9 `summary-testing-ui-round1026` (Эпик 2, шаг «Тестирование из Mini App», §113 + §112)
- **Тип:** UI (Mini App, zero-build) + backend API (dry-run предпросмотр, ровно 2 LLM-вызова L1+L2)
- **Связано:** **ADR-1026-5/-6/-7** (S3/S4/S5 — контракты/модули, REUSE); **ADR-1022-3/4/5** (2-вызовность — REUSE); **ADR-1025-24 D4** (публикационный гейт S6/S10 — governed-by); **ADR-1026-2** (frozen F8 — не запускается); **ADR-1022-8** (async job + polling — REUSE паттерна); ADR-1025-15 (workspace-маршрут `#/modules/<slug>:` — REUSE); §104 (`generate_image` не трогать) — REUSE; §106 (fail-closed) — REUSE
- **Baseline (заявлено; подтверждает @DevOps T-3345):** HEAD `ae5a147` == `origin/master`, `APP_VERSION` 2.58.24, pytest `.venv` 8807/0, JS 43/43, каталог 469/426/444/100/98/21, Δ DDL=0 (SQLite v12)

## Контекст

§113 требует маршрут «Модули → Сводки чатов → Тестирование»: администратор выбирает **чат** и **временное окно**, жмёт «Проверить пайплайн» и видит реальный прогон пайплайна Эпика 2 (`S1 → S2 → L1 §95 → пакет §96 → L2 §98/§99 → форматтер §105`) с предпросмотром Rich Message и метриками §112, **не публикуя**, **не меняя память**, **не вызывая `generate_image`** без отдельного подтверждения (§104, гейт D4/ADR-1025-24). S1–S5 поставлены, но ON-врезка в живой путь GATED — тест-контур нужен как наблюдаемая проверка без открытия публикационного гейта.

Открытые вопросы Step 1 (`tasks.md` «Открытые вопросы @Architect», (a)–(i)): форма входа; состав/объём предпросмотра; ON-путь per-run; техническая гарантия «0/0/0»; форма подтверждения обложки; хранение/retention; границы S6/S7/S8; Δ каталога; deploy/bump.

Ключевые факты кода: `SummaryGenerator._run` (OFF) и `_run_hybrid_l2` (ON, за `SUMMARY_HYBRID_L2_ENABLED`, default OFF) — `services/summary_generator.py`; `run_l1`/`run_l2` принимают `llm_call`-инъекцию и **не зависят** от глобального флага; `memory.get_window_messages` триггерит fire-and-forget запись бегущего конспекта (нельзя использовать в dry-run); `db.get_smart_window` — read-only; вкладка `testing` у `mod_summary` уже объявлена в JS-витрине (`WORKSPACE_TABS`); отдельные API-роутеры (chat_lore/memory_agi/analytics) — установленный паттерн; runtime-доступ к `Bot` — `services/web_runtime.py`.

## Решения

**D1. Форма входа: UI-вкладка «Тестирование» (`#/modules/summary/testing`) + новый backend-роутер; команда не вводится.**
- Переиспользуется **уже объявленная** вкладка `testing` модуля «Сводки чатов» (label «Тестирование»; `WORKSPACE_TABS.mod_summary`), новый tab-id не вводится → **Δ каталога=0**. Секция пайплайна рендерится при `id==='mod_summary' && workspaceTab==='testing'`.
- Backend — **новый файл** `web/api/summary_test.py` (прецедент chat_lore/memory_agi/analytics), включается в `web/app.py`; `web/api/routes.py` — **вне diff**. Telegram-команда не вводится: §113 определяет маршрут Mini App.
- Runtime-доступ к генератору: `services/web_runtime.py` (+`set_summary_generator`/`get_summary_generator`, зеркало `set_web_bot`/`get_web_bot`); вызов из `bot.py` после создания `SummaryGenerator`.
- Флаг `SUMMARY_TEST_UI_ENABLED` (env-only ClassVar, default **ON**): OFF → 404 + секция UI скрыта (прецедент ADR-1022-8 D8; Δ каталога=0). **Уточнение (Step 5 @Architect, 23.09.2026):** флаг — это **тумблер доступности** UI/API, а **не** гейт ON-пути/публикации (гейт — D4/S6/S10). Dry-run 0/0/0, только global admin, rate-limit, предупреждение о расходе → default ON безопасен; OFF-инструкция Step 4 была ошибочной (противоречила D1/§5.1/tasks-инварианту 2). Hot-OFF `=false` имеет смысл только при default ON.
- Альтернатива «отдельная карточка/новый tab-id» отклонена: дубль существующей вкладки и лишний Δ каталога без выигрыша. Альтернатива «добавить в routes.py» отклонена: нарушает изоляцию и byte-диффы `routes.py`.

**D2. Dry-run: отдельный путь без публикации/памяти/`generate_image`; ON-путь — per-run, глобальный флаг не трогается.**
- Новый `services/summary_test_run.py` оркестрирует `build_test_rows → run_l1 → build_fact_package → run_l2 → formatter`. **Не вызывает**: `telegram_send.send_text`/`send_rich_message`/`build_cover_media`, `SummaryGenerator._deliver_*`/`_send_*`, `summary_memory.compress_and_purge`/`memorize_facts`/`remember_user_fact`/`memorize_self_reply`/`get_window_messages`/`_build_running_summary`, досье/граф-записи.
- Окно читается **read-only** через `db.get_smart_window(chat_id, since, limit)`; S1/S2 — чистые функции (`filter_window`/`restore_context`); обход цепочек (`collect_thread_chain`) — только чтение. Аддитивный публичный метод `SummaryGenerator.build_test_rows(...)` переиспользует существующие `_apply_filter`/`_restore` (без дублирования резолва параметров), тело `_run`/`_run_hybrid_l2` **не меняется**.
- **ON per-run:** тест напрямую вызывает `run_l1`/`run_l2` (не зависят от `SUMMARY_HYBRID_L2_ENABLED`); флаг/override не читаются и не пишутся; ровно **2** LLM-вызова. Доказательство — шпионы на запрещённые точки + `await_count==2` + снимок флага/`chat_params` до/после.
- Оговорка: `llm.generate` пишет операционную телеметрию `llm_usage_events` (PG) — **не** «память/досье»; нужна §112. При `dedicated`-слоте usage не ведётся → «Нет данных» (follow-up S7).
- Альтернатива «переиспользовать `_run_hybrid_l2` с флагом» отклонена: включила бы глобальный флаг/риск публикации. Альтернатива «мок-доставка через DI» отклонена: сложнее доказать 0 вызовов, чем отдельный путь + шпионы.

**D3. Предпросмотр §113: полный набор реальных артефактов + Rich/plain + метрики §112; усечение срезами.**
- Секции: исходные → фильтр → кластеры L1 → пакет §96 → статья L2 → Rich-предпросмотр (`format_rich_html`, без `tg://`-медиа) → plain §105 (`format_plain_html`). Артефакты — реальные объекты S1–S5.
- §112: исходных/после фильтра/восстановленных, отсев, тем, токены L1/L2, стоимость L1/L2/общая, время, статус обложки, **статус публикации «не публиковалось (dry-run)»**. Источник токенов/стоимости — `llm_usage_events` (PG) по `correlation_id` + `llm_pricing`; неизвестно → **«Нет данных»** (не `$0`); безлимит (`-1`-sentinel) → **«Без лимита»**.
- Объём: срезы с `totals`/`has_more`, per-message cap 2000 символов с пометкой «обрезано», пагинация `offset/limit`; полные тексты — только уполномоченному админу, в логи не пишутся (R17).
- **Обложка:** двухшаговая — прогон по умолчанию не генерирует; отдельное подтверждение `POST /{test_id}/cover {confirm:true}` переиспользует сохранённый `service.cover_prompt`, вызывает **существующий** `generate_image_verbose` (0 LLM-вызовов), превью — `GET /{test_id}/cover-image` (no-store, только серверный temp-файл задания). §104 не трогается.
- Альтернатива «показывать всё целиком без срезов» отклонена: риск раздувания ответа/утечек. Альтернатива «генерировать обложку в основном прогоне» отклонена: §113 требует отдельного подтверждения.

**D4. API/UI контракт: асинхронный job + in-memory store; RBAC global admin; rate-limit.**
- `POST /api/summary/test/run` → 202 `{test_id,status:"running"}` (`asyncio.create_task`); `GET /{test_id}` polling; `GET /latest?chat_id=`; `POST /{test_id}/cover`; `GET /{test_id}/cover-image`. Права — `requires_global_admin()`; `chat_id` валидируется против доступных областей (reuse `GET /api/access/chats`).
- **Store — in-memory** (TTL 15 мин, ≤20 заданий), **без persistence/DDL**; рестарт → результат теряется (осознанно). Rate-limit ≥10 с на `(user,chat)`; параллельный тот же `(user,chat)` → 409; ≤2 одновременных → 429.
- Коды: 401/403/404 (флаг OFF/истёк)/409/422/429. Отсутствие генератора — **не** `503`: async-модель (`POST /run` всегда `202`, `GET /{id}` — `200`) отдаёт `200` + `status="error"` с кодом `TEST_NO_GENERATOR` (паритет spec §5.2; правка Step 7 @Architect, 24.09.2026 — устранение `S-R1026S9-5`). R17: без секретов/сырых ключей/промптов/сырых ответов.
- Альтернатива «синхронный POST» отклонена: LLM-латентность + mobile-таймауты (прецедент ADR-1022-8 — polling). Альтернатива «файловый store» отклонена: persistence не нужен, а лишние записи на диск противоречат принципу «тест ничего не меняет».

**D5. Fail-closed §106 и диагностика.**
- `L1Result`/пакет не usable/deliverable → тест-статус `skipped`/`invalid`, L2 не вызывается; L2 `empty/invalid/error` → `invalid`/`error`; LLM-сбой → `TEST_LLM_UNAVAILABLE`; ошибка форматтера → `TEST_FORMAT_ERROR` (plain-даунгрейд в предпросмотре); нет генератора/флаг OFF → `TEST_NO_GENERATOR`/404. Публикации/записи нет, без бесконечных повторов.
- Коды `TEST_*` + классы §106 (`SUMMARY_GENERATION_FAILED`/`COVER_GENERATION_FAILED`/`RICH_MESSAGE_SEND_FAILED`/`TEXT_FALLBACK_FAILED`) различимы. «Ошибка Саммари» без деталей запрещена (§109). Диагностика R17-safe (числа/коды/id/host/HTTP-статус/попытки).

**D6. Границы S6/S7/S8.**
- **S6** (публикационный адаптер) — **GATED**: S9 не вызывает публикующий путь; предпросмотр — напрямую из форматтера S5. Потребность в тест-API из S6 — помечается GATED и вне S9.
- **S7** (`run_id`, log viewer §110) — S9 использует существующий `correlation_id`, не дублирует. **S8** (ExecutionGraph §111) — узлы не создаются, только аддитивные метрики/логи. **§85/S10** — вне S9.

**D7. Инварианты.**
- **Δ DDL=0** (SQLite v12; `database.py`/`pg_db.py`/SQL вне diff). **Δ каталога=0** (`param_catalog.py` вне diff; tab/labels — JS-витрина; `SUMMARY_TEST_UI_ENABLED` — ClassVar; F8 не переиздаётся). **CSP/zero-build** (Vue-global + fetch, без новых либ). **R17/R18**. **2-вызовность** сохранена (тест = ровно 2 LLM-вызова; подтверждение обложки — 0 LLM). **OFF-путь/`_run`/`_run_hybrid_l2`/`routes.py`/§104/`generate_image`/обложка/XML — вне diff.**

**D8. Deploy = ДА; bump 2.58.24 → 2.58.25.**
- Меняются рантайм (новый сервис `summary_test_run.py`, новый роутер `summary_test.py`, additive-метод `SummaryGenerator`, `web_runtime.py`, `bot.py`, `web/app.py`, `web/app.js`, `web/index.html`, `config/settings.py`) и наблюдаемое UI/API → version-tracking/откат требуют маркера: **bump `APP_VERSION` 2.58.24 → 2.58.25** + `README.md` + cache-bust; перед деплоем — минимальные §114-тесты; подтвердить, что `SUMMARY_HYBRID_L2_ENABLED` не включён глобально.
- Альтернатива **NOT_APPLICABLE** отклонена: рантайм/API/UI реально меняются, «bump без поставки» оставил бы прод/master рассинхронизированными.
- Откат: annotated-тег `pre-round1026-s9` → baseline (T-3345); hard — `git revert`; hot-OFF — `SUMMARY_TEST_UI_ENABLED=false`.

## AMEND / REUSE-карта

| Ранее | Действие | Что именно |
|---|---|---|
| **ADR-1026-5 / -6 / -7** (S3/S4/S5) | **REUSE** | Контракты `L1Result`/`FactPackage`/`L2Result`/форматтер не меняются; S9 — их первый **dry-run** потребитель |
| **ADR-1022-3/4/5** (2-вызовность) | **REUSE** | Тест сохраняет ровно 2 физических LLM-вызова; 3-й невозможен |
| **ADR-1025-24 D4** (публикационный гейт) | **governed-by** | S9 не публикует/не включает ON в проде; гейт S6/S10 закрыт |
| **ADR-1026-2** (frozen-артефакты F8) | **не запускается** | Δ каталога = 0 |
| **ADR-1022-8** (async job + polling, in-memory/file store) | **REUSE паттерна** | Async + polling; store in-memory (не файловый — persistence не нужен) |
| **ADR-1025-15** (workspace `#/modules/<slug>:`) | **REUSE** | Маршрут `#/modules/summary/testing`; tab/labels — JS-витрина |
| **§104 / `image_generation.py`** | **REUSE (read-only)** | `generate_image_verbose` только по подтверждению; модель/провайдер/ключи/промпт/порядок публикации не меняются |
| **§106** | **REUSE** | Fail-closed; без бесконечных повторов |
| **ADR-1026-8** | **НОВЫЙ** | Step 2 @Architect |

## Последствия

- Владелец получает наблюдаемый dry-run всего пайплайна Эпика 2 без открытия публикационного гейта D4; публикация остаётся за S6/S10.
- Разделение «тест-путь vs живой путь» делает инвариант 0/0/0 доказуемым шпионами и сохраняет OFF-путь байт-в-байт.
- Метрики §112 честные: токены/стоимость из учёта, неизвестное — «Нет данных» (никогда выдуманный `$0`); безлимит — «Без лимита».
- Ограничения (документируются): in-memory store не переживает рестарт; `dedicated`-слот → токены/стоимость «Нет данных» (follow-up S7); реальные usage-события пишутся в PG-телеметрию (не память/досье); превью-тексты доступны только уполномоченному админу и не логируются; формальный `run_id` — S7; ExecutionGraph-узлы — S8; §115 — S10.

## Ссылки

- `plans/features/summary-testing-ui-round1026/{spec.md, tasks.md}`; `plans/ARCHITECTURE.md` §74–§76 (§ S9 — T-3376).
- Код: `services/summary_generator.py` (`_run`/`_run_hybrid_l2`/`_apply_filter`/`_restore`/`_collect_extra_parents`), `services/summary_l1_clusterizer.py` (`run_l1`, `llm_call`), `services/summary_fact_package.py` (`build_fact_package`), `services/summary_l2_writer.py` (`run_l2`, `llm_call`), `services/summary_article_formatter.py` (`format_rich_html`/`format_plain_html`), `services/summary_context_restore.py` (`build_l1_payload`/`restore_context`), `services/summary_filter.py` (`filter_window`), `services/summary_memory.py` (`get_window_messages` — не использовать), `services/database.py` (`get_smart_window`), `services/web_runtime.py`, `services/llm_pricing.py`, `services/usage_events.py`, `web/api/deps.py` (`requires_global_admin`), `web/api/analytics.py` (паттерн `cache.pg.pool`), `web/app.py`, `web/app.js`, `web/index.html`, `bot.py`.
- Архивы: ADR-1026-5, ADR-1026-6, ADR-1026-7, ADR-1022-3/4/5, ADR-1022-8, ADR-1025-15, ADR-1025-24, ADR-1026-2.
