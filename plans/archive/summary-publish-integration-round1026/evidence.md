# S6 `summary-publish-integration-round1026` — evidence (Step 4 @Builder, блоки B–G)

- **Фича:** S6 (Эпик 2, §100–§106), P0/R2. **ADR-1026-11** (D1–D10), `spec.md` (REQ-S6-01…-10 / SC-01…SC-20).
- **Дата:** 24.09.2026. **Автор:** @Builder.
- **Baseline:** HEAD **`197891f`** == `origin/master` == annotated-тег **`pre-round1026-s6`** (tag-object `6fd4a9d6`, подтверждён фактически: `git rev-parse pre-round1026-s6^{commit}` → `197891fdb6…`); `APP_VERSION` **2.58.27**; pytest `.venv` **8926/0**; JS **46/46**; каталог **469/426/444/100/98/21**; Δ DDL=0.
- **Итог Step 4:** блоки **B–G** реализованы и проверены. `APP_VERSION` **2.58.28**; pytest `.venv` **8989/0** (+63); JS **47/47** (+1); `git diff --check`=0. Коммит **не делался**. `plans/current_task.md` / машинный блок / `tasks.md` / `spec.md` / ADR / `backlog.md` / `metrics.md` / `ARCHITECTURE.md` — **не изменялись** (чекбоксы `tasks.md` не проставлялись по указанию).
- **Rework T-3456 (24.09.2026):** блокеры единого Reviewer gate **B-R1026S6-1** (тихая потеря текста: plain >498 абзацев, rich >32000) и **B-R1026S6-2** (plain-доставка без абзацных `<b>`-акцентов) **закрыты** — см. §Rework. pytest `.venv` **9000/0** (+11); JS **47/47**; `git diff --check`=0; коммит не делался.
- **Рабочее дерево:** 47 modified + 3 untracked. **Не Builder** (были modified до старта, не трогались): `plans/MEMORY.md`, `plans/workflow_state.md`, `plans/round1025-architecture.md`. **Untracked:** `plans/features/summary-publish-integration-round1026/` (spec/ADR/tasks + этот файл), `tests/test_summary_publish_integration_round1026.py`, `tests/js/round1026_s6_publish_test.js`.

## 1. Что реализовано по блокам

### Блок B — §100/§101/§102: reuse rich-пути, H1-порядок, форматтер (T-3438…T-3441)
- **T-3438 (reuse `sendRichMessage`/§100):** `services/summary_generator.py` — единое ядро `_publish_rich_document` (`:969`) отправляет через **существующий** `send_rich_message` (`services/telegram_send.py` — **вне diff**), явный `content_format="html"`; `_send_rich_with_retry` (`:1803`) возвращает `Message` для `message_id`. `web/app.js` — только маркеры/подписи. Новый rich-механизм не создавался; `build_cover_article_html` саммари-путём не вызывается (статик-тест; остаётся в `telegram_send.py` для auto/legacy).
- **T-3439 (настоящий H1/§101):** OFF-текст → детерминированный адаптер `document_from_plain_text` (`services/summary_article_formatter.py:236`) → `format_rich_html` (существующий форматтер S5: `<img>` → `<h1>` → `<p>`); порядок и «H1 не жирный» закреплены тестами (`TestRichFormatter`/`TestOffDelivery`). Заголовок: `SummaryDraft.title` (`summary_generator.py:158`) из digest Stage-1 (`extract_title_from_markdown`, `:195`), fallback §5.3 (первая короткая строка → первое предложение → нет заголовка; тело не обрезается). AMEND ADR-1026-7 D5 / ADR-1026-9 D7 зафиксирован комментарием в `_run` (`:601-607`) — OFF-доставка меняется, «байт-в-байт» сужается до генерации.
- **T-3440 (§102 + L-R1026S5-5/-6):**
  - `chunk_plain_blocks(..., sanitize=None)` (`:322`) — порядок **sanitize → clean → escape**; байт-тест «egress-guard — no-op на выводе `format_rich_html`» (`TestRichFormatter.test_egress_guard_noop_on_rich_output`).
  - `services/summary_l2_writer.py` — `_QUOTE_RE` (`:104-110`): ASCII-апостроф кавычка только по границам слова `(?<!\w)'[^']*'(?!\w)`; `_strip_quotes` (`:375`) больше не снимает одиночный `'` fallback-strip'ом. Тесты `don't/it's` — в новом S6-файле (`TestTitleAdapter`/`TestQuotes` существующие + новые).
  - Экранирование `& < > " '`, Unicode/эмодзи/ссылки — тесты `TestRichFormatter` (только теги `img/h1/p/b`, ≤1 `<b>` на абзац).
- **T-3441 (S-R1026S5-7):** `_run` (`:466-479`) — на ON перед `_run_hybrid_l2` тот же `fire_and_forget(memory.memorize_facts(chat_id, _build_batch_text(rows, skip_empty=True), "chat_history"))` под `flags.graph_rag_enabled`; второй контур не создан; OFF не изменён (тест: ровно 1 вызов с теми же строками, OFF — тоже 1).

### Блок C — §105 fallback: абзацная нарезка, no-loss (T-3442/T-3443)
- Единое ядро `_publish_plain_document` (`summary_generator.py:849`): `<b>title</b>` + абзацы, `send_text(..., parse_mode="HTML")`, чанки `chunk_plain_blocks` ≤4096 **по границам абзацев**; финальный даунгрейд — `format_plain_text` + `chunk_plain_text` (`formatter.py:345`); `message_id` первого чанка → `PUBLISH_TEXT_COMPLETE`; тексты не теряются (no-loss тесты, SC-20).
- `_send_text_with_retry` (`:1790`) — чанк ≤2 попытки (1 retry на `TelegramRetryAfter`); **`_send_chunked` не удалена** и осталась только в стриминговой деградации; `_send_streaming` и её ветки **не изменялись** (diff-проверено); стриминг-ветка `_deliver_plain` (`:1720`) — существующий механизм без изменений (§5.4).

### Блок D — §106-коды + `PUBLISH_*` + publish-узел (T-3444…T-3446)
- `services/summary_run_log.py`: коды `:56-59`; `RunContext.code` + публикационные поля (`:154-158`); `fail/fail_from_exc(code=)`; `code=` в `SUMMARY_COMPLETE` (`:223`), `SUMMARY_FAILED` (`:238`), `FORMAT_ERROR` (`:294`), `COVER_COMPLETE` (`:314`), `COVER_ERROR` (`:325`); `PUBLISH_RICH_START/COMPLETE/ERROR` (`:352/:365/:377`) и `PUBLISH_TEXT_START/COMPLETE/ERROR` (`:392/:405/:417`) — поля `run_id/stage=publish/method/chat_id/message_id/reason/error_type/http_status/attempts/duration_ms` (R17-safe, best-effort).
- `summary_generator.py`: `SUMMARY_GENERATION_FAILED` — L1/пакет/L2/OFF LLM/пустой текст (`_generation_code :333`, call-sites `_run`/`_run_hybrid_l2`); `COVER_GENERATION_FAILED` — обложка недоступна/исключение; `RICH_MESSAGE_SEND_FAILED` — rich-отправка → plain; `TEXT_FALLBACK_FAILED` — финал текста упал → `SUMMARY_FAILED` (`ctx.fail(stage="publish")`).
- `services/execution_graph_source.py`: `STAGE_PUBLISH="publication"` (`:57`), `STAGE_ORDER` после `formatting`; `publish_node` (`:377`) — только реальные поля снапшота; `publication_status_of` (`:405`) — `published_rich/published_text/failed/skipped`, нет данных → `None`; `record_run_from_context` (`:205`) переносит publish-поля; `metrics_block` (`:576`) — реальный статус.
- `web/static/execution_graph.js`: publish-узлы **рендерятся** (отбрасывание снято), `publicationStatus` без `'gated'` (нет данных → `null`); `web/app.js`: маркер `'PUBLISH_'` (`:9639`), подписи ошибок (`:9658`), `execPublicationLabel` (`:2620`) — реальные статусы; `web/index.html`/`GraphViewer` не переписаны.
- **Перепрофилирование GATED-тестов S7/S8** (без удаления/ослабления): S7 — `test_publish_events_only_on_real_publication`, серия `PUBLISH_TEXT_*` в ON-тесте; S8 — `test_publish_row_not_llm_node`, `TestPublishNode` (+4), статусы вместо `gated`; JS S8 — publish-узел рендерится, `publicationStatus` реален. Dry-run S9 — без `PUBLISH_*` (S7 + новый тест).

### Блок E — §103-сверка (T-3447/T-3448)
- Памятка spec §8 (Bot API 10.3, aiogram 3.31.0; лимиты 32 768/500/16/50/20; `<h1>/<p>/<b>/<img>`; `sendMessage` 1–4096) применена **кодом**; значения закреплены константами/тестами (`TestSpec103Statements`: rich-кап 32 000 ≤ 32 768, абзацев ≤498, plain-чанк 4096). Промпты/каноны **не менялись**; копии документации в промпте нет (статик-тест `summary_prompts.py`).

### Блок F — тесты/R17/регресс (T-3449…T-3451)
- **NEW `tests/test_summary_publish_integration_round1026.py` — 58 тестов:** адаптеры/детерминизм/мутация входа (`document_from_plain_text` double-run байт-идентичен), rich-порядок/H1/экранирование/whitelist тегов, egress-guard no-op, OFF/ON rich+plain, H1-отсутствие в plain, no-loss/чанки/message_id первого чанка, §106-коды (вкл. `COVER_ERROR`/`TEXT_FALLBACK_FAILED`), bounded retry («вечно RetryAfter»: rich=2, plain HTML=2 + финал=2), `memorize_facts` ON=1/OFF=1, publish-узел/статусы/skipped/None, R17 (сырой текст не в логах), dry-run без `PUBLISH_*`, границы (Δ DDL=0/Δ каталога=0/forbidden diff/`analytics.py` — только docstring через AST).
- **NEW `tests/js/round1026_s6_publish_test.js`** (+ регистрация в `tests/test_webapp_js_unit.py`): маркеры `PUBLISH_*` в §110-фильтре, подписи ошибок, `execPublicationLabel`, `fromExecution.publicationStatus`.
- Обновлены (аддитивно): `test_summary_logging_runid.py`, `test_summary_execution_graph_round1026.py`, `test_webapp_analytics_api.py`, `summary_cover_helpers.py`, `test_summary_cover_round1023.py`, `test_hotfix5_*`, `test_summary_generator.py`, `test_summary_two_call_round1022.py`, `test_summary_l1_clusterizer.py`, `test_verbilizer_response_modes_round1023.py`, `test_summary_l2_integration.py`, `test_token_analytics_round1023.py`, JS S8; version-pin 2.58.27→2.58.28 (15 pytest + 4 JS + README/meta).

### Блок G — интеграция и границы (T-3452/T-3453)
- Оба режима идут через одни ядра/форматтер; `_run`/`_run_hybrid_l2` врезаны; publish-узел и `PUBLISH_*` через существующие контракты S7/S8; §104-контур, §110-viewer, S9, S10-остаток — не тронуты (проверено diff-аудитом, см. §5).

## 2. Команды и фактические результаты

| Проверка | Команда | Результат |
|---|---|---|
| Полный регресс | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **8989 passed, 0 failed**, 1 warning (113.84 с); baseline 8926 → **+63** |
| Новый S6-файл | `pytest tests/test_summary_publish_integration_round1026.py -q` | **58 passed** |
| 2-вызовность | `pytest tests/test_summary_l1_clusterizer.py tests/test_summary_test_run.py -k two_calls` | **3 passed** (`await_count==2`; ON/OFF интеграционные тесты S6 тоже это проверяют) |
| OFF-генерация (канон/байт) | `tests/test_summary_l1_clusterizer.py::…::test_off_chain_byte_identical_single_call` + `test_run_off_two_calls_and_no_loss` | passed (полный прогон) |
| JS (все файлы) | цикл `node tests/js/*.js` (47 файлов) | **OK=47 FAIL=0** (baseline 46 → +1) |
| `git diff --check` | `git diff --check` | exit **0** |
| Каталог/версия | импорт `param_catalog`/`settings` | **2.58.28**; **469/426/444/100/98/21** |
| Каталог `--check` | `tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны` |
| Δ DDL=0 | `db/**`, миграции — вне diff; DDL-поиск по изменённым модулям пуст | подтверждено (тест `test_no_ddl_in_touched_sources`) |
| Границы diff | `git diff --name-only pre-round1026-s6 -- services/telegram_send.py services/image_generation.py services/summary_prompts.py services/summary_test_run.py web/api/routes.py db services/param_catalog.py bot.py` | **пусто** |
| `analytics.py` — только docstring | AST-сравнение со `git show pre-round1026-s6:web/api/analytics.py` (без docstring'ов) | идентично (`test_analytics_docstring_only_changed`) |
| 0 зависимостей | манифесты/локи вне diff | подтверждено |

## 3. Покрытие SC (сжато)

- **SC-01** — reuse `send_rich_message` (+`content_format="html"`), `telegram_send.py` вне diff; статик-тест «второго rich-механизма нет».
- **SC-02/SC-08/SC-09** — `<img>`→`<h1>`→`<p>` OFF/ON; в plain H1 нет; 2-вызовность; OFF-генерация не тронута; ON не активируется.
- **SC-03/SC-18** — `<p>`/`<b>`, whitelist тегов, экранирование; L-R1026S5-5/-6 закрыты; S-R1026S5-7 (memorize и на ON) закрыт.
- **SC-04** — spec §8-утверждения/лимиты, промпты без копии документации.
- **SC-05** — §104-контур пуст в diff; обложка — часть статьи (`media`), отдельного image-сообщения нет (`send_photo` не вызывается).
- **SC-06/SC-20** — `<b>title</b>`+абзацы, чанки по абзацам, финальный даунгрейд, no-loss, `message_id` первого чанка.
- **SC-07/SC-10** — 4 кода различимы, fail-closed (L1/L2 → публикации нет), retry ≤2, `PUBLISH_*` с `run_id/method/chat_id/message_id/reason`.
- **SC-11** — publish-узел только из реальных данных; `publication_status` реален, нет данных → `None`.
- **SC-12/SC-13** — dry-run S9 без публикаций/`PUBLISH_*`; viewer не переписан, `routes.py` вне diff.
- **SC-14/SC-15/SC-16** — R17 (см. §4); Δ DDL=0/Δ каталога=0; bump 2.58.28 + README + cache-bust (механизм `?v=__APP_VERSION__`); нового kill-switch нет.
- **SC-17** — `summary_test_run.py`/`bot.py`/`param_catalog.py`/`db/**` вне diff; S10-остаток не реализован.
- **SC-19** — двойной прогон адаптера/`format_*` байт-идентичен; вход не мутируется.

## 4. R17 / R18

- **R17:** логи/события `PUBLISH_*`/`CODE_*` — только числа/коды/id/host/типы/причины/попытки/длительности; `_mid`-хелпер обрезает не-int `message_id`; секреты/промпты/сырые тексты не логируются (тест `test_publish_events_r17_no_raw_text`; `SUMMARY_*`-R17 — прежние S7-тесты). Снапшот S8 фиксирует только известные поля.
- **R18:** теги/бэкапы (`pre-round1026-s6`, `var/backups/s6-round1026-*`, `.env.bak.round1026-s6`) не удалялись; baseline-тег резолвится в `197891f`.

## 5. Границы diff (факт)

- **Изменено кодом:** `services/summary_generator.py`, `services/summary_article_formatter.py`, `services/summary_run_log.py`, `services/summary_l2_writer.py`, `services/execution_graph_source.py`, `web/app.js`, `web/static/execution_graph.js`, `web/api/analytics.py` (только docstring), `config/settings.py` (APP_VERSION), `README.md`, `plans/docs/param-registry-round1025.meta.md` (провенанс-штамп APP_VERSION), тесты.
- **Вне diff (подтверждено пустым `git diff --name-only pre-round1026-s6`):** `services/telegram_send.py`, §104-контур (`services/image_generation.py`, `compose_cover_image_prompt`, `_resolve_cover_style_text`, `build_cover_media`, порядок), `services/summary_prompts.py`/каноны/миграции, `services/summary_test_run.py`, `web/api/routes.py`, `web/index.html`, `db/**`, `services/param_catalog.py`, `bot.py`, манифесты зависимостей.

## 6. Хэши (SHA-256, для манифеста Reviewer; на момент прогонов)

| Файл | SHA-256 |
|---|---|
| `services/summary_generator.py` | `B21AA3CB031F1BD9D96FD0269704EC9FF45C1D30DED72A93F8789C25E37C4E54` |
| `services/summary_article_formatter.py` | `408FA9D2B9C71DAAFEBC83519A1936DDD469E4FDFF38BEC4662078547DAFD942` |
| `services/summary_run_log.py` | `8BF240DB8139C62FE296DC8381B1A770C933F2BD85BD7C81AE08840D563723E7` |
| `services/summary_l2_writer.py` | `F1FF24A1AB1F4B2EF37E71B300E595CC17B70E9AFFFA78BF3D2D7E49766B11B0` |
| `services/execution_graph_source.py` | `2737BB2C245D80AF5835F5CFEC4A9FC1C080631AA1ECE4791B8CFCE6E8A157EC` |
| `web/app.js` | `BF45F231202427ED0E5A3FBB6420CD40403B10753753E705294AC92847A70111` |
| `web/static/execution_graph.js` | `DE7293DFE5E7357AF7BB8684EFD77DC208E3E50363A6A749FA4FC5080812DEB8` |
| `web/api/analytics.py` | `B302EB34B1E6BA38312D359D9A38D669C62522F41EC93151F2D620018F4F3489` |
| `config/settings.py` | `67872C1DFE0A16D42BA6626CF9304D5E5C478243CD8669F30E50221C0F1A3764` |
| `README.md` | `26D6AD8319D113584482C58DA622BDE1C2D95DA8FE85A8764FBE9A809C513306` |
| `tests/test_summary_publish_integration_round1026.py` | `3808E324D3D18CC7F777F685B70309249163B6D257418027171B4C5823E80A1F` |
| `tests/test_summary_article_formatter.py` | `E1ACCD62688BAA1F97252DB7FC24F11E92C4769C5B207833F860FF52CD4F9C6C` |
| `tests/js/round1026_s6_publish_test.js` | `9E8C3B51C4A0DC25C07D8E8783D8763D18D5D0968A611971B3E2BD9F9127CFF3` |
| `tests/js/round1026_s8_execution_graph_test.js` | `1718E0D1097D3D5F32AF20054CC9DAD68C31F96E3D1820BFAA8AC050CE707AC1` |
| `tests/test_summary_logging_runid.py` | `D7CFB00B8E9F355DE3F1B508F44E29831B870BB2285CA4694E47DAB256E41E55` |
| `tests/test_summary_execution_graph_round1026.py` | `CA43A2A563DB640D84A3693CE219F189CC8EA521851ABA709AC7E9F651F32BD1` |

> Хэши сняты после финальных прогонов (§2) и **обновлены после rework T-3456** (§Rework); правка `evidence.md` после — документная. Изменения `plans/MEMORY.md`/`plans/workflow_state.md`/`plans/round1025-architecture.md` — **до старта** Step 4 (не Builder).

## 7. Решения/интерпретации (для Reviewer; спека не молчит прямо)

1. **`SUMMARY_GENERATION_FAILED`** ставится на L1/пакет/L2 (ON), OFF LLM-ошибку, пустой текст после cleanup и неожиданные исключения OFF-генерации; **DB-ошибки** и `deliver`-исключения кода не получают (не входят в 4 класса §106/D5). `SUMMARY_COMPLETE status=empty` + `code=` не считается «успехом».
2. **`FORMAT_ERROR` при plain-даунгрейде** идёт с `code=-` (даунгрейд — не §106-провал; публикация состоялась текстом, §6-таблица).
3. **`publication_status="skipped"`** — снапшот есть и прогон завершился `empty/degraded/failed` без попытки публикации; нет снапшота/полей → `None` («Нет данных»), `gated` устранён.
4. **Стриминг (`SUMMARY_STREAMING_ENABLED`, default OFF) — вне §105/PUBLISH-контура** (§5.4: существующий механизм не менялся). Следствие: при включённом стриминге `PUBLISH_*` не эмитятся, `publication_status` не заполняется. Зафиксировано в docstring `_deliver_plain`; при необходимости — отдельное решение Architect (кодовая точка роста — возврат `message_id` из `_send_streaming`).
5. **`_plain_fallback`** теперь принимает §99-документ (или legacy-текст) и ведёт в единое plain-ядро; прежние тесты-хуки (`_deliver_plain`/`_send_chunked`) перепрофилированы аддитивно на `sg.send_text`/`_plain_fallback` (assertions не ослаблены).
6. **`plans/docs/param-registry-round1025.meta.md`** — обновлён только провенанс-штамп `APP_VERSION` (прецедент S7/S8: иначе `test_meta_provenance` краснеет при bump); каталог/TSV не переиздавались.
7. **L-R1026S8-3 (Info, комментарий `tests/test_round1025_f8_registry.py:125`)** — уточнён попутно (перечисление bump'ов S7→2.58.26, S8→2.58.27, S6→2.58.28).

## 8. Незакрытое / вне Step 4

- **Коммит, merge, архивация, deploy (T-3457/T-3458/T-3459), handoff (T-3460)** — не выполнялись (вне Step 4); bump/README/готовность к deploy — да, фактический deploy — за @DevOps.
- **Live-приёмка** (владелец) — PENDING; `tasks.md`-чекбоксы не проставлялись (по указанию).
- **S10 (§107/§114/§115/§117, §85-UI)** — не реализовано и не дублировано (SC-17).
- **Evidence Review:** `plans/current_task.md`, машинный блок, spec/ADR, `tasks.md`, `backlog.md`, `metrics.md`, `ARCHITECTURE.md` — не изменялись; Scanner не создавался; коммитов нет.

## Rework (T-3456) — закрытие B-R1026S6-1 / B-R1026S6-2 (24.09.2026)

**Вход:** единый Reviewer gate вернул Needs Fixes (`review.md` §6): **B-R1026S6-1** (тихая потеря текста: plain >498 абзацев — потеря 101; rich >32000 символов — молча срезано ~4.9k; регресс к baseline) и **B-R1026S6-2** (plain-доставка не рендерит абзацные `<b>`-акценты). Правки — только S6-контур (ADR-1026-11 D1); spec/ADR **не менялись** (не требуются: фикс реализует §105/SC-06/SC-20, вариант «не молча + plain-фолбэк» из review §6).

### Что изменено (файлы:строки)

1. **`services/summary_article_formatter.py`:**
   - `_iter_paragraphs` (`:81`) — срез `[:MAX_PARAGRAPHS_HARD]` снят: форматтер не теряет абзацы (>498) ни на одном пути; кап 498 остаётся лимитом rich-канала;
   - `format_rich_html` (`:137`) — «тихий» trim по `RICH_MAX_CHARS` удалён: возвращает **полный** HTML (без молчаливого среза хвоста);
   - **новый** `rich_document_limits` (`:162`) — чистая проверка вместимости rich по полному тексту: `{"html","paragraphs","html_len","max_paragraphs","max_chars","fits","reason"}`, `reason ∈ {"", "rich_paragraph_limit", "rich_char_limit"}`;
   - `_plain_html_blocks` (`:195`) — **единый канон** plain-блоков (`<b>title</b>` + абзацы с ≤1 `<b>`), общий для `format_plain_html` (`:217`) и `chunk_plain_blocks` (`:367`): акценты в доставке = предпросмотр S9, порядок sanitize → clean → escape сохранён (B-R1026S6-2).
2. **`services/summary_generator.py`** (`_publish_rich_document`, `:1056-1078`): перед rich-отправкой — `rich_document_limits`; при `fits=False` — явный WARN с числами (`reason/paragraphs/html_len/max_paragraphs/max_chars`, R17-safe), `FORMAT_ERROR` (channel=rich), затем plain-фолбэк с **полным** текстом (`reason=rich_overflow`); `PUBLISH_RICH_START` не эмитится (rich-отправки не было); `publish_started=None` — None-safe (`_elapsed_since`).
3. **Тесты:**
   - `tests/test_summary_publish_integration_round1026.py` — **+11 тестов**: `TestChunking` (+`test_chunk_plain_blocks_renders_emphasis_single_source` `:294`, `+test_chunk_plain_blocks_emphasis_escaped` `:310`, `+test_chunk_plain_blocks_600_no_loss` `:322`); новый `TestRichLimitsNoSilentTrim` (`:385-418`: полный текст без trim, `rich_char_limit`, `rich_paragraph_limit`, `fits` для малого документа); `TestNoLossPublication` (+`test_plain_600_paragraphs_delivered_no_loss` `:931`, `+test_rich_char_overflow_plain_fallback_full_text` `:953`, `+test_rich_paragraph_overflow_plain_fallback_full_text` `:993`, `+test_plain_delivery_renders_paragraph_emphasis` `:1028`);
   - `tests/test_summary_article_formatter.py:85` — S5-пин старого lossy-поведения (`test_rich_cap_drops_tail_paragraphs`) **перепрофилирован** в `test_rich_full_text_no_silent_trim`: проверка не ослаблена, а заменена более сильной (все 45 абзацев на месте; переполнение — сигнал вызывающему).

### Воспроизводимые пробы (реплика проб Reviewer'а)

| Проба | Метод | Результат после rework | Было (review §6) |
|---|---|---|---|
| **a** plain 600 абз. | `_deliver_plain` — тест `test_plain_600_paragraphs_delivered_no_loss`; скрипт-проба PROBE-A | chunks=11, **missing=0**, `PUBLISH_TEXT_COMPLETE message_id=101` (первый чанк) | доставлено 499, missing=101 |
| **b** rich 45×810 | `_deliver_rich`/`_publish_rich_document` — тест `test_rich_char_overflow_plain_fallback_full_text`; PROBE-B | rich_sent=0, plain 9 чанков, **paras 45/45**; WARN `reason=rich_char_limit html_len=36822`; `PUBLISH_TEXT_COMPLETE reason=rich_overflow message_id=101` | HTML 39 абз., ~4.9k срезано молча |
| **c** formatter 600 | `chunk_plain_blocks` — тест `test_chunk_plain_blocks_600_no_loss`; PROBE-C | missing=0; `rich_document_limits`: `fits=False reason=rich_char_limit html_len=40375 paragraphs=45` | абзацы 499–599 терялись |
| **d** emphasis | `chunk_plain_blocks` vs `format_plain_html` — тесты `test_chunk_plain_blocks_renders_emphasis_single_source`/`test_plain_delivery_renders_paragraph_emphasis`; PROBE-D | `<b>дождь</b>` есть, `chunks == [format_plain_html(doc)]`, ≤1 `<b>`/абзац, экранирование сохранено | акцентов в доставке не было |

Пробы запускались скриптом вне репозитория (`.venv\Scripts\python.exe <temp>\probe_s6_rework.py`): `PROBE-A missing=0`, `PROBE-B rich_sent=0 paras_present=45/45`, `PROBE-C missing=0 fits=False reason=rich_char_limit`, `PROBE-D bold_present=True single_source=True b_tags=2` — 24.09.2026.

### Регресс после rework

| Проверка | Команда/метод | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **9000 passed, 0 failed** (154.92 с); до rework 8989 → **+11** |
| S6-файл | `pytest tests/test_summary_publish_integration_round1026.py -q` | **69 passed** (58 + 11) |
| Форматтер | `pytest tests/test_summary_article_formatter.py -q` | **16 passed** (1 перепрофилирован) |
| JS | цикл `node tests/js/*.js` (47 файлов) | **OK=47 FAIL=0** |
| `git diff --check` | — | exit **0** |
| Каталог/версия | импорт `param_catalog`/`settings` + `gen_param_registry_round1025.py --check` | **469/426/444/100/98/21**; `APP_VERSION` **2.58.28**; CHECK OK |
| Δ DDL=0 | `db/**` вне diff (пусто); DDL-поиск по изменённым модулям (тест `test_no_ddl_in_touched_sources`) | подтверждено |
| 2-вызовность | `pytest ... -k two_calls` + S6 ON/OFF-интеграции | **3 passed**; `await_count==2` |
| Границы diff | `git diff --name-only pre-round1026-s6 -- <запрещённые пути>` | **пусто** (`telegram_send.py`/`image_generation.py`/`summary_prompts.py`/`summary_test_run.py`/`routes.py`/`db/**`/`param_catalog.py`/`bot.py`) |

### Хэши после rework (SHA-256)

| Файл | SHA-256 |
|---|---|
| `services/summary_article_formatter.py` | `408FA9D2B9C71DAAFEBC83519A1936DDD469E4FDFF38BEC4662078547DAFD942` |
| `services/summary_generator.py` | `B21AA3CB031F1BD9D96FD0269704EC9FF45C1D30DED72A93F8789C25E37C4E54` |
| `tests/test_summary_publish_integration_round1026.py` | `3808E324D3D18CC7F777F685B70309249163B6D257418027171B4C5823E80A1F` |
| `tests/test_summary_article_formatter.py` | `E1ACCD62688BAA1F97252DB7FC24F11E92C4769C5B207833F860FF52CD4F9C6C` |

- `git diff 197891f` (SHA-256 сырых байт stdout; рецепт `review.md` §Working-Tree-Hash): `7117ED8AEB2AC133BB129FE7E5F811413C1D2C52EC9B42FF690184E9956FCD3B`.
- Полный Working-Tree-Hash (diff + untracked, кроме `review.md`) — пересчитывает @Reviewer: binding текущего вердикта устарел (см. §9 review).

### Статус блокеров

- **B-R1026S6-1 — закрыт:** ни один путь не теряет текст молча — plain доставляет все абзацы чанками ≤4096 (кап 498 снят); rich при переполнении (блоки/символы) не срезает, а явно (WARN + `FORMAT_ERROR` с числами) уходит в plain с полным текстом; SC-20: каждый абзац ровно один раз, `message_id` первого чанка — в `PUBLISH_TEXT_COMPLETE`.
- **B-R1026S6-2 — закрыт:** plain-доставка рендерит абзацные `<b>` единым каноном с предпросмотром (`_plain_html_blocks`); ≤1 `<b>` на абзац, экранирование (sanitize → clean → escape) сохранено.
- **Spec/ADR:** правки **не требуются**. Если @Reviewer сочтёт снятие trim у `format_rich_html` (чистая функция теперь без усечения) изменением контракта §7, требующим amend — это решение @Architect; @Builder его не принимал.
- **Не тронуто (подтверждено Reviewer'ом):** Q1/Q2, Δ DDL=0, Δ каталога=0, CSP/zero-build, 2-вызовность, границы diff, R17/R18; `plans/current_task.md`, машинный блок, `tasks.md`, spec/ADR, `backlog.md`, `metrics.md`, `ARCHITECTURE.md` — без изменений; Scanner не создавался; коммитов нет.
