# Spec — S6 `summary-publish-integration-round1026` (Эпик 2, §100–§106)

- **Статус:** Step 2 @Architect (24.09.2026, T-3436). Код — не в этом шаге. Сверка `tasks.md` ↔ spec/ADR — @PM (T-3437); `tasks.md` (T-3435…T-3460) не переписывался.
- **Тип:** backend/публикация (живой публикационный путь Саммари; reuse существующих rich/plain-каналов). **P0.**
- **Risk-Level:** **R2** — S6 меняет форматирование/доставку живой публикации Саммари во всех чатах (blast radius: каждый прогон), при этом: 0 новых LLM-вызовов (2-вызовность), Δ DDL=0, Δ каталога=0, retry ограничены, фолбэк без потери текста, откат `git revert`. **Повышает до R3:** любое касание `generate_image`/механизма прикрепления обложки, изменение OFF-генерации (промпты/вызовы/XML/память), DDL/каталог/новые зависимости, изменение обращения с секретами.
- **ADR:** `adr-1026-11-summary-publication-integration.md` (D1–D10; Proposed → Accepted по T-3457, merge §80).
- **Гейт D4 (ADR-1025-24) — ✅ закрыт владельцем 24.09.2026** (live-приёмка Эпика 1 подтверждена) — S6 разблокирована.
- **Baseline:** HEAD `197891f` == `origin/master`; `APP_VERSION` **2.58.27** (прод активен, MainPID 540872); pytest `.venv` **8926/0**; JS **46/46**; каталог **469/426/444/100/98/21**; **Δ DDL=0** (SQLite v12). Подтверждается baseline @DevOps (T-3435).

## 1. Цель и контекст

§100: бот **уже** публикует Саммари через `sendRichMessage`; новый механизм Rich Message не внедрять, улучшить форматирование в существующем; проверить фактический формат `InputRichMessage` (html/markdown/blocks) и использовать существующий. §101: в основном rich-пути — **настоящий H1** (`<h1>` / Heading block size 1), обложка сверху, H1 после изображения, не подменять H1 жирным. §102: абзацы `<p>`, акцент `<b>`, без неподдерживаемых тегов, без смешивания HTML и MarkdownV2, экранирование пользовательского текста (`& < >`, кавычки, Unicode, эмодзи, ссылки). §103: сверить актуальную официальную документацию Telegram; короткая памятка вместо копии документации в промпте; экранирование/разметка — **код**. §104: `generate_image` и механизм прикрепления обложки **не трогать**; обложка — часть статьи. §105: fallback на существующий `sendMessage`; H1 → жирный; абзацы и совместимые `<b>`-акценты; превышение лимита — разбиение **по границам абзацев**; текст не теряется. §106: различать `SUMMARY_GENERATION_FAILED` / `COVER_GENERATION_FAILED` / `RICH_MESSAGE_SEND_FAILED` / `TEXT_FALLBACK_FAILED`; текст готов, обложки нет → публиковать текст; L1/L2 без корректного результата → не публиковать; без бесконечных повторов.

**Факты кода (Step 0 @Memory + Step 2 @Architect):**

1. **OFF-путь (default):** `_run` → `_generate_two_call` (Stage-1 Редактор → Stage-2 Рассказчик) → `_deliver_rich` при обложке (`generate_image_verbose` → `_send_rich_with_retry` → `send_rich_message` c `content_format="auto"`: `build_cover_article_html` = `<img>` + `<p>`-абзацы **без H1**; markdown-ветка при `_looks_rich`), иначе `_deliver_plain` (`_send_streaming` или `_send_chunked` **по пробелам**, `parse_mode=None`).
2. **ON-путь (за `SUMMARY_HYBRID_L2_ENABLED`, default OFF):** `_run_hybrid_l2` → `format_rich_html` (обложка + **`<h1>`** + `<p>`; `content_format="html"`) или `_deliver_l2_plain` (`chunk_plain_blocks`, `<b>title</b>`, абзацы). `await_count==2` (L1+L2); fail-closed без legacy-фолбэка.
3. **S7:** сквозной `run_id`=`correlation_id`; события `SUMMARY_*`/`FORMAT_*`/`COVER_*` + этапные `FILTER_*`/`RESTORE_*`/`L1_*`/`L2_*`; **`PUBLISH_*` отсутствуют (GATED)**. §110-фильтр «Саммари» — в существующем viewer.
4. **S8:** `KIND_PUBLISH`/`STEP_KIND["publication"]` **зарезервированы и GATED**; `publication_status="gated"`; publish-узлы отбрасываются в `web/static/execution_graph.js`; `web/app.js` отображает «недоступна (гейт S6)».
5. **S9:** dry-run — **0 публикаций / 0 памяти / 0 `generate_image`**; предпросмотр через `format_rich_html`/`format_plain_html` (не отправка).
6. **§104-контур:** `services/image_generation.py::generate_image_verbose`, `compose_cover_image_prompt`, `_resolve_cover_style_text`, `build_cover_media`, `SUMMARY_COVER_MEDIA_ID`, порядок «обложка → отправка» — S6 **не меняет**.

## 2. Границы

**В scope S6:** живая доставка Саммари (§100–§105) в обоих режимах генерации; §106-коды; `PUBLISH_*`-события (§108/§109) и публикационный узел S8 (§111/§112); §103-сверка (документируемые утверждения + памятка); follow-up S5 (L-R1026S5-3/-4/-5/-6, S-R1026S5-7); тесты/деплой/откат.

**Вне scope (не трогать):** `generate_image`/обложка-контур (§104 — модель/провайдер/ключи/промпт/параметры/обработка ошибок/порядок/прикрепление); генерация OFF (Stage-1/Stage-2, промпты/каноны, число и состав LLM-вызовов, XML, память, RAG); L1/пакет/L2-контракты и каноны (`summary_l1_clusterizer.py`, `summary_fact_package.py`, `summary_l2_writer.py` — кроме анти-цитатного регекса L-R1026S5-6); `summary_filter.py`/`summary_context_restore.py`/`summary_xml.py`; `summary_test_run.py` (S9 — dry-run не публикует); §110-viewer (не переписывать; только маркеры/подписи, см. D6); `web/api/routes.py`; `db/**`; `param_catalog.py`; UI §85 (вкладки/слоты) — S10; `bot.py`/порядок роутеров; §107/§114/§115/§117 — S10.

## 3. Трассируемость REQ → SC → ADR

| REQ (tasks.md) | §ТЗ (verbatim-источник) | SC спеки | Решение ADR |
|---|---|---|---|
| REQ-S6-01 | §100 «Не нужно внедрять новый механизм Rich Message… Использовать существующий формат, если он подходит. Не менять механизм публикации без необходимости.» | SC-01 | D1, D2, D4 |
| REQ-S6-02 | §101 «В основном пути sendRichMessage использовать настоящий H1… Не заменять H1 жирным… Обложка остаётся сверху. H1 располагается после изображения.» | SC-02, SC-08, SC-09 | D2, D3 |
| REQ-S6-03 | §102 «`<p>`… `<b>`… Не использовать неподдерживаемые теги. Не смешивать HTML и MarkdownV2… экранирования… `&` `<` `>` Кавычки. Unicode. Эмодзи. Ссылки.» | SC-03 | D2, D4, D7 |
| REQ-S6-04 | §103 «Перед реализацией проверить актуальную официальную документацию… Не вставлять в системный промпт L2 огромную копию документации… Само экранирование и формирование разметки должен выполнять код.» | SC-04 | D4 |
| REQ-S6-05 | §104 «Существующий generate_image и механизм прикрепления обложки категорически не менять… Не создавать отдельное сообщение с изображением…» | SC-05 | D1, D9 |
| REQ-S6-06 | §105 «Использовать существующий fallback на обычный sendMessage… Заголовок преобразовать в жирный текст… разделять по границам абзацев. Не обрезать статью молча.» | SC-06, SC-20 | D2, D7 |
| REQ-S6-07 | §106 «Различать: SUMMARY_GENERATION_FAILED. COVER_GENERATION_FAILED. RICH_MESSAGE_SEND_FAILED. TEXT_FALLBACK_FAILED… не публиковать пустое или выдуманное Саммари. Не запускать бесконечные повторные отправки.» | SC-07 | D5 |
| REQ-S6-08 | R17/R18 + Δ DDL=0 + Δ каталога (санкция) + CSP/zero-build + 2-вызовность | SC-14, SC-15, SC-16 | D8, D9 |
| REQ-S6-09 | §110 (не переписывать) + §113/S9 (не публикует) + §111/S8 (publish GATED → решение Step 2) + §107/§114/§115 — S10 | SC-10, SC-11, SC-12, SC-13, SC-17 | D6, D10 |
| REQ-S6-10 | Follow-up S5: L-R1026S5-3/-4/-5/-6, S-R1026S5-7; AMEND-кандидаты «OFF байт-в-байт» и чанки по пробелам | SC-06, SC-08, SC-09, SC-18, SC-19 | D3, D5, D7 |

## 4. Решения (D1–D10; полно — в ADR)

### D1. Границы diff (ответ (a))

**Меняется (diff S6):** `services/summary_generator.py` — доставка OFF (`_deliver_rich`, `_deliver_plain`, `_plain_fallback`, `_send_rich_with_retry`), доставка ON (`_deliver_l2_rich`/`_deliver_l2_plain` — события/единое ядро), `_run` (проброс `title`/`ctx`, parity `memorize_facts` на ON, `ctx.code`), `_generate_two_call` (аддитивный `SummaryDraft.title` из digest), общие ядра `_publish_rich_document`/`_publish_plain_document`; `services/summary_article_formatter.py` (аддитивно: `document_from_plain_text`, `extract_title_from_markdown`, `chunk_plain_text`, параметр `sanitize` у `chunk_plain_blocks`); `services/summary_l2_writer.py` (L-R1026S5-6: апострофы в `_QUOTE_RE`/`_strip_quotes`); `services/summary_run_log.py` (`PUBLISH_*`-хелперы, поле `code`); `services/execution_graph_source.py` (publish-этап/узел, реальный `publication_status`); `web/static/execution_graph.js` (активация publish-узлов, `publicationStatus` без `gated`); `web/app.js` (маркеры `PUBLISH_*` в §110-фильтре, подписи ошибок публикации, `execPublicationLabel`); `web/api/analytics.py` (только docstring: снять S8-формулировки «publish GATED» — актуализация AMEND ADR-1026-10 D1/D4/D8; код эндпоинта не меняется); `config/settings.py` (`APP_VERSION`); `README.md`; тесты.

**Остаётся вне diff:** §104-контур (`image_generation.py`, `compose_cover_image_prompt`, `_resolve_cover_style_text`, `build_cover_media`, `SUMMARY_COVER_MEDIA_ID`, порядок и механизм прикрепления); `services/telegram_send.py` (**reuse без изменений**: `send_rich_message`/`build_cover_article_html`/`build_cover_media`); `summary_prompts.py`/`prompt_migrations.py` (каноны не меняются); `summary_filter.py`/`summary_context_restore.py`/`summary_xml.py`/`summary_l1_*`/`summary_fact_package.py`; `summary_test_run.py`; `web/api/routes.py`; `web/index.html` (разметка viewer не меняется); `db/**`; `param_catalog.py`; `bot.py`.

**«Не ломать существующий рабочий rich-путь»:** механизм отправки (`sendRichMessage` через существующую обёртку), генерация обложки, `media`-вложение и порядок публикации — не меняются; меняется **только сборка текста** rich-сообщения (настоящий H1 + `<p>`) и plain-доставка (§105). Авто-детектор `_looks_rich` для саммари-пути больше не используется: rich всегда передаётся с явным `content_format="html"` (уже существует с S5).

### D2. Reuse `sendRichMessage` + H1-порядок + единый форматтер (ответы (a), (f))

- **Формат:** Rich HTML (не blocks, не markdown). §101 разрешает `<h1>` для Rich HTML; Heading block size 1 — эквивалент, но смена формата = «менять механизм без необходимости» (§100). Заголовок — **настоящий `<h1>`**, не жирный.
- **Порядок:** `<img src="tg://photo?id=summary_cover">` → `<h1>title</h1>` → `<p>`-абзацы. Обложка остаётся частью статьи (`media` + `tg://photo`-ссылка), отдельного сообщения с изображением нет (§104).
- **Единый канон форматирования:** серверный форматтер S5 (`format_rich_html`/`chunk_plain_blocks`) — единственный путь для саммари **в обоих режимах**:
  - ON: документ §99 из L2 (как в S5);
  - OFF: документ строится детерминированным адаптером `document_from_plain_text(text, title=…)` (новый, чистый, 0 LLM): абзацы — по `\n\n`, markdown-разметка снимается существующим `_clean_text`; заголовок — по приоритету (см. §5.3).
- **`build_cover_article_html`:** остаётся в `telegram_send.py` без изменений (auto-ветка/legacy-вызовы/тесты); саммари-путь его больше не использует. Не удалять.
- **`downgrade_rich_to_plain`:** сохраняется как пред-шаг, если текст содержит rich-разметку (`looks_rich`) — поведение review iter1 (Medium-2) не регрессирует; таблицы Markdown деградируют в текст (` - `-склейка ячеек), без потери слов. Это осознанный trade-off (альтернатива «оставить markdown-ветку» отклонена: ломает единый §101/§102-канон и гарантии экранирования).
- **Plain (§105):** `<b>title</b>` + абзацы + совместимые `<b>`-акценты, отправка существующим `sendMessage` (`send_text`, `parse_mode="HTML"`, экранирование кодом); чанки — по границам абзацев (`chunk_plain_blocks`, ≤4096). Настоящий H1 в plain **не используется**.

### D3. OFF-доставка меняется → AMEND (ответ (b))

**S6 меняет OFF-доставку** — это и есть требование §100–§105 («улучшить форматирование текста в существующем механизме»): OFF-rich получает H1, OFF-plain — жирный заголовок и абзацную нарезку. Поэтому:

- **AMEND ADR-1026-7 D5:** гарантия «OFF байт-в-байт» сужается до **слоя генерации** (промпты, число/состав LLM-вызовов, XML, память/RAG, обложка-контур) и смысла OFF-ветки; **формат доставки** OFF намеренно меняется S6 (§100–§105) — effective S6.
- **AMEND ADR-1026-9 D7:** уточнение «OFF/legacy байт-в-байт» (поведение/артефакты) дополняется исключением S6-sanctioned доставки; аддитивные логи сохраняются.
- **Семантика kill-switch сохраняется:** `SUMMARY_HYBRID_L2_ENABLED` (env-only, default **OFF**) — переключатель **режима генерации** (OFF → Stage-1/Stage-2; ON → L1+L2), не формата. S6 **не активирует** ON (активация — §107/S10); per-chat/hot резолв (`_chat_limit`) не меняется.
- Откат формата — только `git revert` (тег `pre-round1026-s6`); частичные рычаги — `SUMMARY_COVER_ARTICLE_ENABLED=false` (plain-only), `SUMMARY_HYBRID_L2_ENABLED` (режим генерации).

### D4. §103 — проверенная памятка (ответ (c))

Сверка выполнена 24.09.2026 по официальной документации `https://core.telegram.org/bots/api` (снимок содержит Bot API 10.3 от 24.08.2026) и установленному aiogram **3.31.0**. Проверяемые утверждения — §8. **Короткая памятка** о разрешённых смысловых элементах уже содержится в L2-каноне (структура §98, лимиты, запрет markdown/буллитов/ID; экранирование и разметка — код); **промпт L2 S6 не меняет** (канон-байт-тест остаётся зелёным). Документация Telegram в промпт не копируется.

### D5. §106-коды: маппинг и fail-closed (ответ (d))

| Код | Триггер | Где эмитится | Событие |
|---|---|---|---|
| `SUMMARY_GENERATION_FAILED` | L1 не usable / пакет не deliverable / L2 не usable / LLM-ошибка генерации / пустой текст после cleanup | `_run_hybrid_l2`, `_run` (OFF) | `SUMMARY_FAILED` (или `SUMMARY_COMPLETE status=degraded`) + `code=` |
| `COVER_GENERATION_FAILED` | `generate_image_verbose` → нет пути или исключение | `_publish_rich_document` (оба режима) | `COVER_ERROR` / `COVER_COMPLETE status=unavailable` + `code=`; текст публикуется |
| `RICH_MESSAGE_SEND_FAILED` | rich-отправка упала (после ≤1 retry на RetryAfter) | `_publish_rich_document` | `PUBLISH_RICH_ERROR` + `code=`; → plain-фолбэк |
| `TEXT_FALLBACK_FAILED` | финальная текстовая доставка (после падения HTML-чанков) упала | `_publish_plain_document` | `PUBLISH_TEXT_ERROR` + `code=`; прогон `SUMMARY_FAILED` |

- «Текст готов, обложка не создана → публиковать текст» — сохраняется в обоих режимах.
- L1/L2 без корректного результата → **публикации нет** (fail-closed, без legacy-фолбэка — 3-й вызов запрещён).
- «Без бесконечных повторов»: rich ≤2 попытки (1 retry на `TelegramRetryAfter`), чанк ≤2, финальный текст ≤2; циклов нет. Поведение пинуется тестом с «вечно RetryAfter» ботом.
- **Закрывается L-R1026S5-4.**
- Взаимодействие с S7: `run_id` во всех `PUBLISH_*`; `code=` — аддитивное R17-safe поле существующих строк `SUMMARY_*`/`COVER_*`/`FORMAT_*`; новые `PUBLISH_*` используют тот же helper-стиль §109 (`run_id/stage/method/chat_id/message_id/reason/error_type/http_status/attempts/duration_ms`).

### D6. Publish-срез S8 и `PUBLISH_*` — делаем в S6 (ответ (e))

`PUBLISH_*` (§108) и публикационный узел (§111/§112) **реализуются в S6** — это публикационный слой, которым владеет S6; S10 — deploy/ops (§107/§114/§115/§117) и активация, не место для новых узлов/событий. Реализация — через существующие контракты:

- `PUBLISH_RICH_START/COMPLETE/ERROR`, `PUBLISH_TEXT_START/COMPLETE/ERROR` (§108/§109: method, chat_id, message_id, причина fallback; ошибки — §109-поля).
- S8: `STAGE_PUBLISH="publication"` включается в канонический порядок после `formatting`; узел `kind="publish"` строится **только из реальных данных** снапшота (channel/status/duration/message_id; без LLM-токенов/стоимости); нет данных — нет узла. `publication_status` — реальный: `published_rich` | `published_text` | `failed` | `skipped`; нет снапшота → `None` («Нет данных»), не `gated` и не выдуманное «опубликовано».
- `web/static/execution_graph.js`: отбрасывание publish-узлов снимается (узел рендерится существующим `GraphViewer`, стиль `.token-flow__node--publish` уже есть); `publicationStatus` без дефолта `'gated'`.
- `web/app.js`: `execPublicationLabel` — подписи реальных статусов; §110-маркеры + подписи ошибок публикации (viewer не переписывается).
- **AMEND ADR-1026-10 D1/D4/D8** (publish GATED → активирован в S6), **AMEND ADR-1026-9 D2** (`PUBLISH_*` GATED → реализованы в S6).
- GATED-тесты S7/S8 **перепрофилируются** (не удаляются): «publish-узел — только при реальных данных»; dry-run S9 — по-прежнему без `PUBLISH_*`.

### D7. Follow-up S5 (REQ-S6-10) — решения

| Finding | Решение S6 |
|---|---|
| **L-R1026S5-3** (+1 `get_chat_param` до OFF-ветки) | **Подтверждено, без изменения кода:** чтение флага — само решение ветки (per-chat override), fail-safe `False`; «байт-в-байт» относится к генерации/артефактам, не к числу config-read. Документируется в ADR. |
| **L-R1026S5-4** (§106-классы) | **Закрывается** — D5. |
| **L-R1026S5-5** (sanitize после escape) | **Закрывается с evidence:** в `chunk_plain_blocks` добавляется `sanitize` (порядок sanitize → clean → escape — реальная инверсия); для rich-пути фиксируется байт-тест «egress-guard — no-op на выводе `format_rich_html`»; `telegram_send.py` остаётся вне diff. |
| **L-R1026S5-6** (апострофы `It's`→`Its`) | **Исправляется:** `_QUOTE_RE`/`_strip_quotes` не трактуют `'` внутри слова как кавычки (границы слова); тесты `don't/it's` + существующие кавычковые — зелёные. |
| **S-R1026S5-7** (ON пропускает `memorize_facts(chat_history)`) | **Исправляется:** на ON-пути перед `_run_hybrid_l2` вызывается тот же `fire_and_forget(memory.memorize_facts(chat_id, _build_batch_text(rows, skip_empty=True), "chat_history"))` под тем же `flags.graph_rag_enabled`; **один контур памяти**, второй не создаётся; OFF не меняется. Тест: ON → `memorize_facts` вызван ровно 1 раз с теми же строками. |

### D8. Санкции и инварианты

- **Δ DDL = 0** (SQLite v12; новых таблиц/колонок/индексов нет).
- **Δ каталога = 0** — **санкции нет**: `param_catalog.py` вне diff, F8 **не переиздаётся**, новых ключей/env нет. UI-слоты §85 (модели/провайдеры/ключи L1/L2, видимость флага) — **вне S6**; активация/видимость — S10 или отдельная санкционированная фича (явно документируется как остаток, не «тихо потерян»).
- **2-вызовность:** 0 новых LLM-вызовов; форматтер/адаптер/заголовок — детерминированный код; `await_count==2` на обоих путях.
- **CSP/zero-build**; **0 новых внешних зависимостей**.
- **R17/R18:** логи/события/ошибки — числа/коды/id/host/HTTP-статус/тип/причина/попытки; без ключей, промптов, сырых текстов и сырых ответов; теги/бэкапы не удаляются.
- §110-viewer, S9-контур, §104-контур, генерация/каноны — не переписываются.

### D9. Deploy/bump/hot-OFF (ответ (g))

- **Deploy = ДА:** меняются рантайм-модули и наблюдаемое поведение публикации → **bump `APP_VERSION` 2.58.27 → 2.58.28** + `README.md` + cache-bust; перед деплоем — минимальные §114-тесты; подтвердить, что §104-контур не изменён. **NOT_APPLICABLE отклонён** (прод/master разошлись бы).
- **Новый kill-switch не вводится** (не оставлять скрытых состояний; §107 против «фичи, ждущей ручной активации»); существующие рычаги: `SUMMARY_HYBRID_L2_ENABLED` (режим генерации, default OFF), `SUMMARY_COVER_ARTICLE_ENABLED=false` (plain-only), `SUMMARY_STREAMING_ENABLED` (ортогонально).
- **Откат:** annotated-тег **`pre-round1026-s6`** → `197891f` + `git revert` (границы отката: формат доставки + события/узел; генерация/каноны/§104 не затрагиваются).

### D10. Остаток S10 (ответ (h)) — не реализуется в S6

**S10 `summary-deploy`:** §107 (прямой деплой/активация: Hybrid — основным, фильтр включён по умолчанию, раздельный роутинг, без теневого режима/rollout), §114 (чек-лист минимальных проверок, включая «Rich Message с H1», «обычный текстовый fallback», «не публиковать тестовые результаты в основной чат»), §115 (первый рабочий запуск: Hybrid активен, фильтр, модели L1/L2, промпты, штатный запуск, логи этапов, публикация — статья с обложкой/H1 либо текст с жирным заголовком), §117 (результаты Эпика 2: схема, новые параметры, промпты, роутинг, JSON Schema, пакет фактов, пример статьи, проверки Rich/fallback, сохранность `generate_image`, пример логов полного запуска). Также в S10/следом: UI-слоты §85 (L1/L2-модели/ключи, видимость флага) — **при отдельной санкции** (Δ каталога ≠ 0), если потребуется. S6 не дублирует и не реализует ничего из этого.

## 5. Наблюдаемое поведение (контракт доставки)

### 5.1. Rich-путь (основной, оба режима)
`<img src="tg://photo?id=summary_cover">` (если обложка создана) → `<h1>title</h1>` → `<p>…</p>…`; ≤1 `<b>` на абзац (дословная подстрока своего абзаца, иначе снимается); только теги `img/h1/p/b`; `content_format="html"` (явный маршрут, без авто-детектора); `media=[build_cover_media(tmp_path)]` — существующий механизм. Отправка — существующий `send_rich_message`; `message_id` возвращается для §109.

### 5.2. Plain-путь (§105, fallback)
`<b>title</b>` → абзацы (экранированные) + совместимые `<b>`-акценты; `sendMessage` (`parse_mode="HTML"`); чанки ≤4096 **по границам абзацев** (`chunk_plain_blocks`); ни один абзац не теряется/не дублируется; финальный даунгрейд (если HTML отклонён) — `format_plain_text` + `chunk_plain_text` (без разметки, тоже по абзацам); молчаливой обрезки нет. Настоящий `<h1>` в plain не отправляется.

### 5.3. Источник заголовка (детерминированно, 0 LLM)
1. **Основной:** первая Markdown-заголовочная строка digest Stage-1 (`extract_title_from_markdown`; чистка/≤200/одна строка) — `SummaryDraft.title` (аддитивное поле).
2. **Fallback (нет заголовка/нет draft):** первая строка текста, если это отдельный короткий абзац ≤200 и далее есть текст.
3. **Иначе:** первое предложение первого абзаца ≤200 символов с непустым остатком.
4. **Иначе:** заголовка нет (H1 опускается; тело не меняется). Тело никогда не обрезается ради заголовка; выдуманный заголовок запрещён.

### 5.4. Неизменное
- OFF-генерация: Stage-1 → Stage-2, каноны, ровно 2 вызова, XML/память/RAG, `_ensure_shiz_postfix`, `_resolve_cover_prompt`.
- ON-генерация: L1 → пакет → L2, ровно 2 вызова, fail-closed.
- §104: модель/провайдер/ключи/промпт обложки/параметры/обработка ошибок/порядок/механизм прикрепления.
- S9 dry-run: 0 публикаций/0 памяти/0 `generate_image`.
- Стриминг (`SUMMARY_STREAMING_ENABLED=true`): существующий механизм без изменений (ортогонален §105; §105 применяется к fallback-доставке).

## 6. Поведение при отказах (§105/§106)

| Ситуация | Поведение | Код/событие |
|---|---|---|
| L1/пакет/L2 не дали корректный результат | L2 не вызывается либо результат не публикуется; legacy-фолбэка нет | `SUMMARY_GENERATION_FAILED`; `SUMMARY_FAILED`/`degraded`; публикации нет |
| LLM-ошибка генерации / пустой текст | Публикации нет (OFF: молчание/UX-фраза — как сейчас) | `SUMMARY_GENERATION_FAILED` |
| Обложка не создана (нет пути/исключение) | Публикуется текст (plain) | `COVER_GENERATION_FAILED` → `PUBLISH_TEXT_*` |
| Rich-отправка упала | ≤1 retry (RetryAfter) → plain-фолбэк | `RICH_MESSAGE_SEND_FAILED` |
| Plain HTML-чанки упали | Финальный текст без разметки, по абзацам | `FORMAT_ERROR` (downgrade) |
| Финальная текстовая доставка упала | Прогон `failed`, UX-фраза; текст не «потерян молча» — зафиксировано | `TEXT_FALLBACK_FAILED` |
| Повторы | Строго ограничены (≤1 retry на отправку), без циклов | — |

## 7. Интерфейсы и данные

```
# services/summary_article_formatter.py (чистые, аддитивные)
def extract_title_from_markdown(markdown: str) -> str
def document_from_plain_text(text: str, *, title: str = "") -> dict   # §99-shape
def chunk_plain_text(text: str, limit: int = 4096) -> list[str]      # по абзацам
def chunk_plain_blocks(document, limit=4096, sanitize=None)          # +sanitize (L-R1026S5-5)

# services/summary_generator.py
SummaryDraft(title: str = "")                       # аддитивное поле
_publish_rich_document(chat_id, document, cover_prompt, *, correlation_id, ctx)   # ядро rich (OFF+ON)
_publish_plain_document(chat_id, document, *, correlation_id, ctx, reason)        # ядро plain (OFF+ON)
_deliver_rich(...), _deliver_l2_rich(...)           # обёртки (имена сохранены)
_deliver_plain(...), _plain_fallback(...), _deliver_l2_plain(...)  # обёртки
```

- **`RunContext` (аддитивно):** `code` (§106), `publish_channel` (`rich|text`), `publish_status` (`ok|failed`), `publish_duration_ms`, `publish_message_id`.
- **Снапшот S8:** те же поля переносятся `record_run_from_context` (R17-safe).
- **Граф:** `STAGE_PUBLISH="publication"` в `STAGE_ORDER` (после `formatting`); узел `kind="publish"` из реальных полей; `publication_status ∈ {published_rich, published_text, failed, skipped}`; нет снапшота → `None`.
- **События (§108/§109):** `PUBLISH_RICH_START/COMPLETE/ERROR`, `PUBLISH_TEXT_START/COMPLETE/ERROR`; поля — method (`sendRichMessage`/`sendMessage`), chat_id, message_id (первый чанк для text), reason (fallback), duration_ms; ошибки — §109-набор. `code=` добавляется в `SUMMARY_COMPLETE/FAILED`, `COVER_COMPLETE/ERROR`, `FORMAT_ERROR`.
- **Совместимость:** `send_rich_message`/`build_cover_article_html`/`build_cover_media`/`format_rich_html`/`format_plain_html`/`format_plain_text` — без изменений контракта; новые параметры аддитивны с дефолтами.

## 8. §103 — проверенные утверждения (снимок 24.09.2026)

Источник: `https://core.telegram.org/bots/api` (страница Bot API 10.3, 24.08.2026) + установленный aiogram 3.31.0.

| Утверждение | Значение |
|---|---|
| `sendRichMessage` | `chat_id` + `rich_message` обязательны; возвращает `Message` |
| `InputRichMessage` | ровно **одно** из `html`/`markdown`/`blocks`; `media[]` для `tg://photo?id=…`; `is_rtl`, `skip_entity_detection` |
| Rich HTML-теги | `<h1>`–`<h6>`, `<p>`, `<b>`/`<strong>`, `<img src=…/>` и др.; только перечисленные; медиа — отдельными блоками; `tg://photo?id=`-ссылки разрешены при передаче `media` |
| Экранирование | ответственность отправителя (`<`, `>`, `&`); поддержаны все числовые сущности + именованные `&lt; &gt; &amp; &quot; &apos; &nbsp; &hellip; &mdash; &ndash; &lsquo; &rsquo; &ldquo; &rdquo;` |
| Лимиты Rich Message | 32 768 UTF-8 символов; 500 блоков; 16 уровней вложенности; 50 медиа; 20 колонок |
| `InputRichBlockSectionHeading` | `size` 1–6, 1 — наибольший (blocks-эквивалент `<h1>`; не используется) |
| `sendMessage` | 1–4096 символов после разбора сущностей; классический HTML-набор (`b/i/u/s/a/code/pre/tg-spoiler/tg-emoji/tg-time`); `<h1>`/`<p>`/`<img>` **не поддерживаются** |
| aiogram 3.31.0 | `InputRichMessage{html,markdown,is_rtl,skip_entity_detection,blocks,media}`; `SendRichMessage(chat_id, rich_message)`; `InputRichBlockSectionHeading{text,size}` |
| Текущий код | `<img src="tg://photo?id=summary_cover">` + `InputRichMessageMedia(id=…)` — соответствует «media field specifies media used in html/markdown» |

**Памятка:** в L2-канон не добавляется копия документации; допустимые смысловые элементы (H1/абзацы/≤1 `<b>`) уже зафиксированы в каноне S5; разметку и экранирование выполняет код.

## 9. Приёмочные сценарии

- **SC-01** §100/D1/D2: `sendRichMessage` — reuse существующего `send_rich_message`; summary rich = `html` (ровно одно поле); второго rich-механизма нет; `telegram_send.py` вне diff.
- **SC-02** §101/D2: в rich-пути `<img>` → `<h1>title</h1>` → `<p>`; H1 не подменён жирным; ON и OFF; в plain настоящего H1 нет.
- **SC-03** §102/D2/D7: `<p>`-абзацы, ≤1 `<b>`; только `img/h1/p/b`; нет MarkdownV2; экранирование `& < > " '`, Unicode, эмодзи, ссылок; L-R1026S5-5/-6 закрыты.
- **SC-04** §103/D4: утверждения §8 зафиксированы; L2-канон байт-идентичен (нет копии документации); экранирование/разметка — код.
- **SC-05** §104/D1/D9: diff `image_generation.py`/`compose_cover_image_prompt`/`_resolve_cover_style_text`/`build_cover_media`/порядок/прикрепление пуст; обложка — часть статьи; отдельного image-сообщения нет.
- **SC-06** §105/D2/D7: plain — `<b>title</b>`, абзацы, совместимые `<b>`; Rich-теги/H1 не отправляются; чанки по абзацам ≤4096; no-loss.
- **SC-07** §106/D5: 4 кода различимы и эмитятся на своих этапах; «текст без обложки публикуется»; L1/L2-провал → публикации нет; retry ограничены.
- **SC-08** OFF/D1/D3: OFF-генерация байт-в-байт (промпты/2 вызова/XML/память/обложка); доставка — по §101/§102/§105 (AMEND зафиксирован); `await_count==2`.
- **SC-09** ON/D3/D7: ON — 2 вызова, fail-closed без legacy-фолбэка; единая доставка; S-R1026S5-7 закрыт (`memorize_facts` на ON, один контур).
- **SC-10** §108/§109/D5/D6: `PUBLISH_RICH_*`/`PUBLISH_TEXT_*` с `run_id/method/chat_id/message_id/reason`; R17-safe.
- **SC-11** §111/§112/D6: publish-узел при реальной публикации (после `formatting`, линейная связь); без данных узла нет; `publication_status` реален; UI рендерит publish; вторая визуализация не создана.
- **SC-12** §113/S9/D8: dry-run — 0 публикаций/0 `PUBLISH_*`/0 памяти/0 `generate_image`; предпросмотр не сломан.
- **SC-13** §110/S7/D8: viewer не переписан; второй контур логов не создан; новые события ловятся фильтром «Саммари»; `routes.py` вне diff.
- **SC-14** R17/R18: в логах/событиях/ошибках нет ключей/промптов/сырых текстов/ответов; теги/бэкапы не удаляются.
- **SC-15** Δ: Δ DDL=0; Δ каталога=0 (F8 не переиздаётся); 0 новых зависимостей; CSP/zero-build.
- **SC-16** deploy/D9: bump 2.58.28 + `README.md` + cache-bust; откат `pre-round1026-s6` + `git revert`; §104-контур после деплоя не изменён.
- **SC-17** границы: §85 UI/каталог вне diff; `summary_test_run.py` вне diff; S10-остаток не реализован; `bot.py`/роутеры вне diff.
- **SC-18** follow-up/D7: L-R1026S5-3 подтверждён и документирован; L-R1026S5-4 закрыт; L-R1026S5-5/-6 исправлены; S-R1026S5-7 исправлен с тестом.
- **SC-19** детерминизм: двойной прогон `document_from_plain_text`/`format_*` байт-идентичен; вход не мутируется.
- **SC-20** no-loss публикации: сумма доставленных абзацев == исходный текст (ровно один раз каждый); `message_id` первого чанка в `PUBLISH_TEXT_COMPLETE`.

## 10. Тесты / деплой / откат

- **Тесты (@Builder):** T-3449 (rich-reuse/H1-порядок/§102-экранирование/no-loss), T-3450 (OFF/ON, 2-вызовность, S9-границы, §104/§110 вне diff, `PUBLISH_*`/publish-узел, GATED-тесты перепрофилированы), T-3451 (полный регресс ≥ 8926/0, JS ≥ 46/46, `git diff --check`=0, R17, Δ DDL=0, CSP/zero-build, 0 зависимостей). Каждый REQ — ≥1 тест. Существующие тесты `_deliver_*`/`_send_chunked`/`_send_streaming`/S7/S8 обновляются **аддитивно** (никогда не ослабляются).
- **§114-минимум перед деплоем:** несколько параллельных разговоров; короткие важные ответы; длинные сообщения; reply_to; упоминания; почти пустой лог; невалидный JSON L1; ошибка LLM; ошибка обложки; Rich Message с H1; обычный текстовый fallback; тестовые результаты не публикуются в основной чат.
- **Deploy (@DevOps T-3459):** bump 2.58.27 → **2.58.28**, `README.md`, cache-bust; push без force; прод ff; `/api/health` 200; `database is locked`=0; подтвердить §104-контур; `deployment.md` VERIFIED.
- **Откат:** annotated-тег **`pre-round1026-s6`** → `197891f`; hard — `git revert`; рычаги — `SUMMARY_HYBRID_L2_ENABLED`/`SUMMARY_COVER_ARTICLE_ENABLED`; теги/бэкапы не удалять (R18).

## 11. Зависимости

S1–S5 ✅, S7 ✅ (2.58.26), S8 ✅ (2.58.27), S9 ✅ (2.58.25); `services/telegram_send.py` (`send_rich_message`/`build_cover_media`/`SUMMARY_COVER_MEDIA_ID`); `services/summary_article_formatter.py`; `services/summary_run_log.py`; `services/execution_graph_source.py`; `services/summary_l2_writer.py`; aiogram **3.31.0**; Bot API Rich Messages (см. §8). Гейт D4 закрыт.

## 12. Риски и follow-up

- **High:** регресс живой публикации (митигации: SC-02/SC-06/SC-08, полный регресс, единый форматтер, откат); потеря текста в fallback (SC-06/SC-20); случайное касание §104 (diff-аудит T-3452 + линза 2 T-3455).
- **Medium:** подмена H1 жирным/обложка не сверху (SC-02); незакрытые §106-коды (SC-07); расхождение OFF-доставки с AMEND (D3 фиксируется в ADR); «зелёная сборка» как ложное закрытие (приёмка по живым артефактам/evidence).
- **Follow-up → S10/после:** UI-слоты §85 (L1/L2-модели/ключи, видимость флага) — при отдельной санкции; live-приёмка (владелец); стриминг-режим — вне §105-контура.
- **Миграционное примечание:** @Scanner удалён намеренно; его содержательные обязанности — в едином Reviewer gate (линза 2, T-3455); отдельный Scanner-отчёт не создаётся.

## 13. Ссылки

`plans/features/summary-publish-integration-round1026/{tasks.md, adr-1026-11-summary-publication-integration.md}`; `plans/current_task.md` §100–§106 (только чтение); архивы: `plans/archive/summary-l2-writer-formatter-round1026/adr-1026-7-*.md`, `plans/archive/summary-logging-runid-round1026/adr-1026-9-*.md`, `plans/archive/summary-analytics-adapter-round1026/adr-1026-10-*.md`, `plans/archive/epic1-verification-round1025/adr-1025-24-*.md`; код: `services/{summary_generator.py, telegram_send.py, summary_article_formatter.py, summary_l2_writer.py, summary_run_log.py, execution_graph_source.py}`, `web/static/execution_graph.js`, `web/app.js`; внешние: `https://core.telegram.org/bots/api` (Rich Messages), aiogram 3.31.0.
