# Evidence — S5 `summary-l2-writer-formatter-round1026` (Эпик 2, блоки B–G)

- **Автор:** @Builder (Step 3), 23.09.2026.
- **База:** HEAD `e3ea608` (closing-docs S4; номинальный baseline `7722d66`), `APP_VERSION` 2.58.23 → **2.58.24** (D7).
- **Статус:** реализовано + локально верифицировано; ON-путь L2 **не активирован** (kill-switch OFF, гейт S6/S10+D4). Ревью/аудит/деплой — блок H (другие агенты).

## Что реализовано (по блокам B–G)

### B — L2 «Писатель» (T-3311…T-3315)
- Новый модуль `services/summary_l2_writer.py`: `build_l2_input(package, *, detail)`,
  `run_l2(llm, package, *, service, correlation_id, slot, max_paragraphs, chat_id)`,
  `parse_l2_document(raw)`, `validate_l2_document(document, package)`,
  `resolve_l2_slot()`/`resolve_l2_slot_safe()`/`resolve_l2_max_paragraphs()`,
  `L2Result{status,document,invalid_reason,usage,metrics,duration_ms}`, `L2Slot`, `L2SlotError`.
  Вход — контент-секция `FactPackage` (§96; без `service`/`budget`/`unassigned`/сырого лога);
  выход — `{schema_version:1, title, paragraphs:[{text, emphasis|null}]}` (§99);
  **ровно 1** LLM-вызов (`module="summary", step="l2_writer"`).
- Пост-валидация §97: выдуманная цитата (нет нормализованного совпадения с
  `facts∪fragments` пакета) → снятие кавычек + WARN-счётчик; именованная атрибуция
  (`Имя: «…»`, `«…», — сказал Имя`) → fail-closed `invalid`/`quote_attribution`;
  вырезание `fact:`/`msg:`/метка-даты; `emphasis` — дословная подстрока, иначе снят.
- Канон `SUMMARY_L2_WRITER_SYSTEM_PROMPT` + `PREV_SUMMARY_L2_WRITER_R1026` +
  `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` + эталон `plans/docs/canon/architecture.md`
  (байт-идентичен) — атомарно (ADR-1013-3). `SUMMARY_NARRATOR`/Редактор/`digest`/
  `system2_handoff` — REUSE без изменений.
- Слот §82 env-only: `SUMMARY_L2_BASE_URL`/`SUMMARY_L2_MODEL_NAME`/`SUMMARY_L2_API_KEY`
  (ClassVar, Δ каталога=0), hot-first, «не выбрано» → глобальная.
- F8 переиздание (ADR-1026-2, T-3312): REGISTRY **468→469**, categorized **443→444**,
  delta **57→58**; Settings **426** / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21 — без изменений.

### C — Форматтер (T-3316…T-3320)
- Новый модуль `services/summary_article_formatter.py` (**0 LLM**, чистый stdlib):
  `format_rich_html` (обложка → **настоящий `<h1>`** → `<p>` + ≤1 `<b>`),
  `format_plain_html` (`<b>title</b>` + абзацы/акценты), `format_plain_text`,
  `chunk_plain_blocks(document, limit=4096)` по границам абзацев.
  Экранирование `sanitize_outgoing` → `html.escape(quote=True)`; теги только
  `img/h1/p/b`. Лимиты: `title` ≤200/одна строка, абзацев ≤ `limits.max_summary_parts`
  и ≤498, rich ≤32000, абзац ≤900.
- `services/telegram_send.send_rich_message(..., content_format="auto")` — новый
  параметр; `"html"` (ON-путь) шлёт готовый HTML форматтера без авто-детектора;
  `"auto"` (default) — прежнее поведение байт-в-байт.

### D — Вход/режимы/лимиты (T-3321…T-3324)
- `build_l2_input` — компактный детерминированный JSON контент-секции; `service` не утекает.
- `response_mode` на ON — уровень детализации (casual/serious/deep_research);
  `cover_prompt` — транзит; `digest` — только OFF; §104 (`generate_image`/обложка/XML) не тронут.

### E — Fail-closed + логи (T-3325…T-3327)
- `L1Result`/пакет не usable/deliverable → L2 **не вызывается** (`L2_SKIPPED` + reason);
  L2 `empty`/`invalid`/`error` → `L2_ERROR`, **без legacy-фолбэка**, публикации нет;
  обложка-провал → публикуется текст (§105). Логи `L2_START/COMPLETE/ERROR/SKIPPED` и
  `FORMAT_ERROR` — аддитивные, R17-safe (числа/коды/host/модель/токены/абзацы/длительность).

### F — Тесты (T-3328…T-3331)
- `tests/test_summary_l2_writer.py` (38), `tests/test_summary_article_formatter.py` (15),
  `tests/test_summary_l2_integration.py` (11). Плюс обновлены F8-фикстуры и pinned-ассерты
  (REGISTRY 469 / categorized 444 / delta 58).

### G — Интеграция / kill-switch (T-3332…T-3336)
- `summary_generator._run`: ON-ветка за `_hybrid_l2_enabled(chat_id)` (env-only
  `SUMMARY_HYBRID_L2_ENABLED`, default **False**, hot-first `flags.summary_hybrid_l2_enabled`,
  per-chat `_chat_limit`); OFF-путь `_generate_two_call` **байт-в-байт**.
  ON: `run_l1 (1) → build_fact_package (0) → run_l2 (1) → formatter (0) → доставка`,
  ровно 2 вызова. Ленивые импорты L1/L2/пакета (OFF не тянет модули).
- Follow-up закрыты/переданы (T-3335): **[L-R1026S3-1]** — `resolve_l2_slot_safe()`
  fail-closed-обёртка (L2-аналог, до врезки); **[I-R1026S4-2]** — `reason` в `metrics`
  fail-closed-веток; **[L-R1026S3-2]** `evidence_message_ids: []` — документируется
  (L2 не цитирует); **[L-R1026S3-3]/[L-R1026S4-1]/[L-R1026S4-3]/[R-R1026S3-1/-2]** —
  note/не блокер (S6/S7).

## Изменённые/новые файлы
- **Новые:** `services/summary_l2_writer.py`, `services/summary_article_formatter.py`,
  `tests/test_summary_l2_writer.py`, `tests/test_summary_article_formatter.py`,
  `tests/test_summary_l2_integration.py`.
- **Правки кода:** `services/summary_prompts.py`, `services/prompt_migrations.py`,
  `services/param_catalog.py`, `services/telegram_send.py`, `services/summary_generator.py`,
  `config/settings.py` (`APP_VERSION` 2.58.24 + env-only `SUMMARY_L2_*`/`SUMMARY_HYBRID_L2_ENABLED`),
  `README.md` (v2.58.24 + описание раунда).
- **F8/эталон:** `plans/docs/canon/architecture.md` (канон L2), `plans/docs/param-registry-round1025.{tsv,meta.md}`,
  `plans/docs/screen-map-round1025.md`, `tests/fixtures/round1025/{f8_baseline.json,catalog_baseline.json}`.
- **Pinned-ассерты:** 31 test-файл (REGISTRY 468→469 / categorized 443→444), 13 — `APP_VERSION` 2.58.23→2.58.24,
  4 JS-теста (версия в `config/settings.py`), `tests/test_{param_catalog,prompt_migrations,outgoing_guard_round1022,ui_verbilizer_tabs_round1023,round1025_f8_registry,summary_l1_clusterizer,summary_fact_package}.py`.

## Прогоны (факт)
- `py -3 -m pytest -q` (`.venv`): **8801 passed, 0 failed** (~109s; baseline S4 — 8737); 1 warning — pre-existing starlette/httpx deprecation.
  - **Rework T-3339 (повторный прогон):** **8807 passed, 0 failed** (~109s; +6 новых тестов rework); 1 warning тот же.
- JS-юнит: `tests/test_webapp_js_unit.py` — **30 passed**; файлов `tests/js/*.js` — **43**.
- `node --check`: `web/app.js`, `web/static/{glass,aurora-flow,polygon-background}.js` — exit 0.
- `git diff --check` — exit 0 (только CRLF-warnings Git).
- Каталог импортом: REGISTRY **469** / Settings **426** / categorized **444** / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21**.
- F8: `python tools/gen_param_registry_round1025.py` (emit) + `--check` — **CHECK OK** (реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны).
- Канон L2 в `plans/docs/canon/architecture.md` — байт-идентичен коду (проверено `tests/test_summary_l2_writer.py::TestCanon::test_canon_doc_byte_identical`; S-R1026S5-3 — тест добавлен в rework T-3339).
- **Δ DDL=0:** `services/pg_db.py` не изменён; новых миграций/DDL нет.

## Rework S5 (T-3339, 23.09.2026) — findings @Reviewer/@Scanner

- **[B-R1026S5-1] ✅ исправлено (фикстура F8).** `tests/fixtures/round1025/catalog_baseline.json`
  восстановлен из blob `e3ea608` (UTF-8 без BOM, исходный отступ 1, LF→рабочий CRLF),
  наложены **только** санкционированные правки: ключ `prompts.summary_l2_writer_system_prompt`,
  `counts.REGISTRY 468→469`, дописана provenance-нота S5. `git diff --stat` = **3 insertions / 2 deletions**
  (только эти строки); mojibake-символов **0** (было 302). `test_round1025_f8_registry.py` +
  `test_ia_inventory_round1025.py` — зелёные.
- **[S-R1026S5-1] ✅ исправлено (архитектурный drift D5/§80).** ON-ветка перенесена из начала `_run`
  врезкой **после S1/S2**: `rows → (S1 `_apply_filter` + S2 `restore_context`) → xml_rows → ON`.
  `_run_hybrid_l2(chat_id, rows, focus, correlation_id)` теперь принимает уже отфильтрованный/
  восстановленный вход; `focus` прокинут в L1 (`run_l1(..., focus_block=_apply_filter`-совместимый
  блок `_apply_focus`)`); `trigger_message_id` учтён S1-фильтром. OFF-путь по телам кода не изменён
  (проверен прямым OFF-тестом, см. L-R1026S5-2). Новый тест `TestOnPathAppliesS1S2` доказывает:
  `_apply_filter` вызван, `restore_context` вызван, L1 получил filtered-вход + focus.
- **[L-R1026S5-1] ✅** удалён мёртвый импорт `format_plain_html` в `_deliver_l2_plain`.
- **[S-R1026S5-3] ✅** добавлен byte-тест канона L2 `TestCanon::test_canon_doc_byte_identical`
  (эталон `plans/docs/canon/architecture.md` == код промпта, как у L1).
- **[S-R1026S5-2] ✅** анти-цитатный валидатор расширен: одиночные `'…'`/`‚…‘` и восточные
  `「…」`/`『…』` (defense-in-depth); `_strip_quotes` знает эти пары. Тесты `test_single_quoted_*`,
  `test_corner_quoted_*`.
- **[S-R1026S5-4] ✅** `chunk_plain_blocks` при вынужденной нарезке режет по безопасной границе
  (`_split_safe`) — HTML-сущность не разрывается. Тест `test_chunk_does_not_split_html_entity`.
- **[L-R1026S5-2] ✅** добавлен прямой OFF-тест `TestOffPathDirect` (сравнение вывода `_run` OFF-пути
  с эталоном: legacy `_generate_two_call` + ожидаемый текст доставки).
- **[L-R1026S5-4] — передано в S6 (не S5):** §106-классы `SUMMARY_GENERATION_FAILED`/
  `COVER_GENERATION_FAILED`/`RICH_MESSAGE_SEND_FAILED`/`TEXT_FALLBACK_FAILED` в S5 не реализуются;
  владелец — S6 (закреплено в backlog-строке S6). Пометка внесена в `tasks.md` (T-3325/T-3339).

**Проверки rework (факт):** pytest `.venv` **8807/0**; JS `tests/test_webapp_js_unit.py` **30/0**,
файлов `tests/js/*.js` **43**; `git diff --check` exit 0 (только CRLF-warnings);
`pg_db.py`/`database.py` вне diff → **Δ DDL=0**; каталог импортом **469/426/444/100/98/21**;
F8 `--check` **CHECK OK**; fixture-diff **3+/2−** (0 mojibake).


## Не проверено / ограничения
- **ON-путь L2 в проде не прогонялся** — по гейту D4 (kill-switch OFF); проверен на моках (`tests/test_summary_l2_integration.py`).
- **Live-приёмка Эпика 1** — PENDING OWNER VERIFICATION (вне S5).
- **F8 config-diff артефакт** (`plans/reports/round1025_f8_config_diff.md`) — исторический baseline (2.58.15), не переиздавался (в него дельта не входит; pinned-тесты зелёные).
- Слот модели/флаг без UI — S6; реальный ON — гейт S6/S10+D4.
- **Ревью/аудит/merge/deploy** — блок H (T-3337…T-3344), не выполнены @Builder.
