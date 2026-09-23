# ADR-1026-11 — S6 «Публикационная интеграция Саммари»: reuse `sendRichMessage`, единый Rich HTML (обложка → H1 → абзацы), §105 plain по абзацам, §106-коды, `PUBLISH_*`/publish-узел, Δ DDL=0/Δ каталога=0

- **Статус:** **Proposed** (Step 2 @Architect, T-3436, 24.09.2026) → **Accepted по T-3457** (Merge `plans/ARCHITECTURE.md` **§80**, ожидаемый номер). Сверка @PM — T-3437.
- **Фича:** S6 `summary-publish-integration-round1026` (Эпик 2, §100–§106; P0).
- **Тип:** backend/публикация (живой публикационный путь Саммари; reuse существующих rich/plain-каналов) + аддитивный UI-срез §112 (publish-статус).
- **Связано:** **ADR-1026-7** (S5 L2/форматтер; **AMEND D5** — OFF байт-в-байт сужается до генерации), **ADR-1026-9** (S7 `run_id`/события; **AMEND D2/D7** — `PUBLISH_*` реализуются в S6), **ADR-1026-10** (S8 adapter; **AMEND D1/D4/D8** — publish-срез активируется в S6), **ADR-1022-4** (2-вызовность — REUSE), **ADR-1022-6** (egress-guard — REUSE), **ADR-1023-6** (rich/plain-каналы, обложка — REUSE), **ADR-1013-3** (каноны — не запускается), **ADR-1026-2** (F8 — не запускается), **ADR-1025-24 D4** (публикационный гейт — **закрыт владельцем 24.09.2026**).
- **Baseline:** HEAD `197891f` == `origin/master`; `APP_VERSION` **2.58.27**; pytest `.venv` **8926/0**; JS **46/46**; каталог **469/426/444/100/98/21**; Δ DDL=0 (SQLite v12).
- **Номер ADR:** `ADR-1026-11` — следующий свободный (S8 = ADR-1026-10).

---

## Контекст

§100–§106 требуют привести **существующий** механизм публикации Саммари (`sendRichMessage`) к целевому формату: настоящий H1 в основном rich-пути (§101), `<p>`/`<b>` и экранирование (§102), сверка с документацией Telegram и короткая памятка (§103), обложка и `generate_image` неприкосновенны (§104), plain-fallback без потери текста и с нарезкой по границам абзацев (§105), четыре различимых класса ошибок (§106). Новый механизм Rich Message не внедряется (§100).

**Проверенные факты кода (Step 0 @Memory + Step 2 @Architect):**

1. **OFF-путь (default):** `_generate_two_call` → `_deliver_rich` (`build_cover_article_html` — `<img>` + `<p>`, **без H1**; markdown-ветка при `_looks_rich`) либо `_deliver_plain` (`_send_chunked` **по пробелам** / streaming). OFF-доставка сегодня не соответствует §101/§105.
2. **ON-путь** (за `SUMMARY_HYBRID_L2_ENABLED`, default OFF): `format_rich_html` уже даёт `<img>`+`<h1>`+`<p>` (`content_format="html"`); `_deliver_l2_plain` — `<b>title</b>` + абзацные чанки. Формат ON — целевой; публикационных событий/узла нет.
3. **S7:** `run_id`=`correlation_id`; `SUMMARY_*`/`FORMAT_*`/`COVER_*` есть, **`PUBLISH_*` GATED**.
4. **S8:** `KIND_PUBLISH`/`publication` зарезервированы и GATED; `publication_status="gated"`; publish-узлы отбрасываются в `execution_graph.js`.
5. **S9:** dry-run не публикует (0/0/0); предпросмотр — через форматтер.
6. **§104-контур** (`image_generation.py`, `compose_cover_image_prompt`, `_resolve_cover_style_text`, `build_cover_media`, порядок/прикрепление) — неприкосновенен.
7. **Follow-up S5:** L-R1026S5-3/-4/-5/-6 + S-R1026S5-7 переданы в S6 (Low/Info, не блокеры).
8. **Гейт D4** (ADR-1025-24) закрыт владельцем 24.09.2026 — смена существующего публикационного пайплайна разрешена.

**Открытые вопросы Step 1 (a)–(h)** — закрыты решениями D1–D10 ниже.

---

## Решения

### D1. Границы diff живого пайплайна (ответ (a))

**Решение.** Diff S6 — только **публикационная доставка** и её наблюдаемость: `services/summary_generator.py` (`_run`, `_generate_two_call` — аддитивный `title`, `_deliver_rich`/`_deliver_plain`/`_plain_fallback`/`_send_rich_with_retry`, `_deliver_l2_rich`/`_deliver_l2_plain`, общие ядра `_publish_rich_document`/`_publish_plain_document`), `services/summary_article_formatter.py` (аддитивные адаптеры/чанкер + `sanitize` у `chunk_plain_blocks`), `services/summary_l2_writer.py` (только L-R1026S5-6), `services/summary_run_log.py` (`PUBLISH_*`, `code`), `services/execution_graph_source.py` + `web/static/execution_graph.js` + `web/app.js` (publish-узел/статус/маркеры), **`web/api/analytics.py` — только docstring** (модульный + `execution_latest`: снять S8-формулировки «Publish-срез GATED»/«Публикация — `gated`»), `config/settings.py` (`APP_VERSION`), `README.md`, тесты.

**Почему `web/api/analytics.py` в diff (выравнивание T-3437).** После активации publish-среза (D6) его docstring — единственное место в product code, где утверждение «GATED» осталось бы ложным (прочие носители — `execution_graph_source.py`, `execution_graph.js`, `web/app.js`, комментарий `APP_VERSION` — уже в diff S6); меняется **только docstring**, код эндпоинта (pass-through `build_graph`) не трогается, новых задач не вводится (состав T-3435…T-3460 не меняется).

**Вне diff:** §104-контур; `services/telegram_send.py` (reuse **без изменений**); каноны/промпты и их миграции; `summary_filter.py`/`summary_context_restore.py`/`summary_xml.py`/`summary_l1_*`/`summary_fact_package.py`; `summary_test_run.py`; `web/api/routes.py`; `db/**`; `param_catalog.py`; `bot.py`.

**«Не ломать рабочий rich-путь».** Механизм (`sendRichMessage` через существующую обёртку), генерация обложки, `media`-вложение, порядок публикации — не меняются. Меняется только сборка текста (H1 + `<p>`) и plain-доставка (§105); rich всегда идёт явным `content_format="html"` (параметр существует с S5). `build_cover_article_html` сохраняется для auto/legacy-вызовов и не удаляется.

**Альтернатива «тронуть `telegram_send.py`»** (скипать egress-guard для html) отклонена: guard — defense-in-depth (ADR-1022-6), для валидного HTML — no-op (пинуется байт-тестом); минимальный diff важнее косметики порядка.

### D2. Reuse rich-механизма, H1-порядок и единый форматтер (ответы (a), (f))

**Решение.** Rich = **Rich HTML** (не blocks, не markdown): `<img src="tg://photo?id=summary_cover">` → **`<h1>title</h1>`** → `<p>`-абзацы, ≤1 `<b>` на абзац. Форматтер S5 — единственный канон для **обоих** режимов: ON получает документ §99 из L2; OFF — детерминированный адаптер `document_from_plain_text(text, title=…)` (0 LLM). Plain (§105): `<b>title</b>` + абзацы через `sendMessage parse_mode="HTML"`, чанки по абзацам (`chunk_plain_blocks` ≤4096); настоящий H1 в plain не используется. Заголовок — по приоритету (digest → короткая первая строка → первое предложение → нет заголовка); тело никогда не обрезается ради заголовка; выдуманный заголовок запрещён.

**Альтернативы.**
- **(a) Heading blocks (`InputRichBlockSectionHeading.size=1`).** Отклонено: смена формата = «менять механизм без необходимости» (§100); HTML-путь уже реализован и проверен в S5.
- **(b) Сохранить markdown-ветку OFF при `_looks_rich`.** Отклонено: смешение форматов ломает единый §101/§102-канон и гарантии экранирования; таблицы Markdown деградируют в текст (слова не теряются) — задокументированный trade-off.
- **(c) Новый слой legacy-text→HTML с собственной разметкой.** Отклонено: дублирование канона S5; адаптер отдаёт §99-документ и переиспользует `format_*`.

### D3. OFF-доставка меняется; AMEND ADR-1026-7 D5 и ADR-1026-9 D7; kill-switch сохраняется (ответ (b))

**Решение.** §100–§105 — это и есть смена форматирования **существующего** механизма, поэтому OFF-доставка (rich H1, plain жирный заголовок + абзацная нарезка) меняется вместе с ON. Гарантия «OFF байт-в-байт» **сужается** до слоя генерации (промпты, число/состав вызовов, XML, память/RAG, обложка-контур) и смысла OFF-ветки. `SUMMARY_HYBRID_L2_ENABLED` остаётся переключателем **режима генерации** (OFF → Stage-1/Stage-2; ON → L1+L2), не формата; S6 ON не активирует (это §107/S10). Откат формата — `git revert` (тег `pre-round1026-s6`); частичные рычаги — `SUMMARY_COVER_ARTICLE_ENABLED`, `SUMMARY_HYBRID_L2_ENABLED`.

**Альтернатива «не менять OFF до S10»** отклонена: §101/§105 адресованы живому основному пути, который до S10 — OFF; оставить его без H1 и с чанками по пробелам = не выполнить ТЗ и приёмку S6.

### D4. §103: проверяемые утверждения и памятка (ответ (c))

**Решение.** Сверка по `https://core.telegram.org/bots/api` (снимок 24.09.2026; Bot API 10.3) и aiogram 3.31.0: `sendRichMessage` (chat_id+rich_message → Message); `InputRichMessage` — ровно одно из `html`/`markdown`/`blocks`, `media[]` для `tg://photo?id=`; Rich HTML `<h1>`–`<h6>`/`<p>`/`<b>`/`<img>`, только перечисленные теги, экранирование `< > &` — ответственность отправителя, числовые + ограниченный набор именованных сущностей; лимиты 32 768 символов / 500 блоков / 16 уровней / 50 медиа / 20 колонок; `sendMessage` 1–4096, `<h1>`/`<p>`/`<img>` не поддержаны. Памятка о разрешённых смысловых элементах уже в L2-каноне; **промпт L2 не меняется** (канон-байт-тест зелёный), документация в промпт не копируется; разметку/экранирование делает код. Утверждения фиксируются в spec §8 и здесь.

### D5. §106-коды: маппинг на этапы/события, fail-closed, bounded retry (ответ (d))

**Решение.** `SUMMARY_GENERATION_FAILED` (L1/пакет/L2/LLM/пустой текст → публикации нет; `SUMMARY_FAILED`/`degraded` + `code=`), `COVER_GENERATION_FAILED` (`COVER_ERROR`/`COVER_COMPLETE status=unavailable` + `code=`; текст публикуется), `RICH_MESSAGE_SEND_FAILED` (`PUBLISH_RICH_ERROR` + `code=`; → plain-фолбэк), `TEXT_FALLBACK_FAILED` (`PUBLISH_TEXT_ERROR` + `code=`; прогон failed). «Текст готов, обложки нет → публиковать текст» — сохраняется; L1/L2-провал → без legacy-фолбэка (3-й вызов запрещён); повторы строго ограничены (≤1 retry на отправку, без циклов). **Закрывает L-R1026S5-4.** `run_id` — во всех событиях; `code` — аддитивное R17-safe поле.

### D6. Publish-срез S8 и `PUBLISH_*` — реализуются в S6 (ответ (e))

**Решение.** `PUBLISH_RICH_START/COMPLETE/ERROR` и `PUBLISH_TEXT_START/COMPLETE/ERROR` (§108/§109: method/chat_id/message_id/reason) + узел `kind="publish"` в существующем `ExecutionNode`-контракте: `STAGE_PUBLISH="publication"` после `formatting`; узел — только из реальных данных снапшота (channel/status/duration/message_id; без LLM-токенов/стоимости); нет данных — нет узла. `publication_status` — реальный (`published_rich`/`published_text`/`failed`/`skipped`; нет снапшота → `None`). `execution_graph.js` — снять отбрасывание publish-узлов; `web/app.js` — подписи статусов и маркеры/подписи ошибок публикации в §110-фильтре (viewer не переписывается). GATED-тесты S7/S8 перепрофилируются: «узел/события — только при реальных данных», dry-run S9 — без `PUBLISH_*`.

**Альтернатива «follow-up/S10»** отклонена: §108/§111 требуют эти события/узел, а S10 — deploy/ops (§107/§114/§115/§117); иной владелец отсутствует, и публикационный слой принадлежит S6.

### D7. Follow-up S5 (REQ-S6-10) — решения

**Решение.**
- **L-R1026S5-3** — **подтверждено** (чтение флага = решение ветки, per-chat override, fail-safe `False`; «байт-в-байт» относится к генерации/артефактам, не к config-read); документируется.
- **L-R1026S5-4** — **закрывается** (D5).
- **L-R1026S5-5** — **закрывается**: `chunk_plain_blocks` получает `sanitize` (порядок sanitize → clean → escape); для rich-пути — байт-тест «egress-guard — no-op на выводе `format_rich_html`»; `telegram_send.py` вне diff.
- **L-R1026S5-6** — **исправляется**: `'` внутри слова не трактуется как кавычка (границы слова) в `_QUOTE_RE`/`_strip_quotes`.
- **S-R1026S5-7** — **исправляется**: на ON-пути перед `_run_hybrid_l2` вызывается тот же `fire_and_forget(memory.memorize_facts(chat_id, _build_batch_text(rows, skip_empty=True), "chat_history"))` под `flags.graph_rag_enabled`; **один контур памяти**, второй не создаётся; OFF не меняется.

### D8. Санкции и инварианты

**Решение.** **Δ DDL=0**; **Δ каталога=0 — санкции нет** (`param_catalog.py` вне diff; F8 не переиздаётся; новых ключей/env нет). UI-слоты §85 (L1/L2-модели/ключи, видимость флага) — вне S6; S10/отдельная санкция (явный остаток). **2-вызовность** (0 новых LLM-вызовов; заголовок/формат — код). **CSP/zero-build**; **0 новых зависимостей**; **R17/R18**; §110-viewer/S9/§104-контур/каноны не переписываются.

### D9. Deploy/bump/hot-OFF (ответ (g))

**Решение.** **Deploy = ДА**: bump `APP_VERSION` **2.58.27 → 2.58.28** + `README.md` + cache-bust; перед деплоем — §114-минимум; подтвердить неизменность §104-контура. **Новый kill-switch не вводится** (без скрытых состояний; §107 против «фичи, ждущей ручной активации»). Откат — annotated-тег **`pre-round1026-s6`** → `197891f` + `git revert`; мягкие рычаги — `SUMMARY_COVER_ARTICLE_ENABLED=false`, `SUMMARY_HYBRID_L2_ENABLED` (режим генерации, default OFF).

**Альтернатива NOT_APPLICABLE** отклонена: рантайм и наблюдаемое поведение меняются → прод/master разошлись бы.

### D10. Границы S10 (ответ (h))

**Решение.** S10 = §107 (прямой деплой/активация: Hybrid основным, фильтр default ON, раздельный роутинг), §114 (чек-лист), §115 (первый рабочий запуск: Hybrid активен, модели/промпты, публикация — статья с H1 либо текст с жирным заголовком), §117 (результаты Эпика 2) + остаток §85-UI (при отдельной санкции). S6 ничего из этого не реализует и не дублирует.

---

## AMEND / REUSE-карта

| Ранее | Действие | Что именно |
|---|---|---|
| **ADR-1026-7 D5** (S5: OFF байт-в-байт) | **AMEND (effective S6)** | Гарантия сужается до слоя генерации (промпты/2 вызова/XML/память/обложка); доставка OFF меняется по §100–§105 |
| **ADR-1026-9 D2/D7** (S7: `PUBLISH_*` GATED; «OFF байт-в-байт») | **AMEND** | `PUBLISH_*` реализуются в S6; уточнение «байт-в-байт» распространяется на S6-доставку |
| **ADR-1026-10 D1/D4/D8** (S8: publish GATED) | **AMEND** | Publish-узел и реальный `publication_status` активируются в S6; `ExecutionNode`-контракт/F6 REUSE |
| **ADR-1022-4** (2-вызовность) | **REUSE** | 0 новых LLM-вызовов; `await_count==2` на обоих путях |
| **ADR-1022-6** (egress-guard) | **REUSE** | Guard сохраняется; для HTML-вывода — no-op (байт-тест) |
| **ADR-1023-6** (rich/plain-каналы, обложка) | **REUSE** | Обложка — часть статьи; §104-контур не тронут |
| **ADR-1013-3 / ADR-1026-2** | **не запускаются** | Каноны не меняются; Δ каталога=0 → F8 не переиздаётся |
| **ADR-1025-24 D4** | **gate closed** | Владелец подтвердил live-приёмку Эпика 1 (24.09.2026) — публикационный пайплайн разблокирован |
| **ADR-1026-11** | **НОВЫЙ** | Step 2 @Architect (T-3436); Proposed → Accepted по T-3457 |

## Последствия

**Плюсы.** Живой Саммари-путь (OFF и ON) даёт статью с настоящим H1 после обложки (§101), абзацами/акцентами и корректным экранированием (§102), plain-fallback без потери текста и с абзацной нарезкой (§105), различимые §106-коды; публикация наблюдаема (`PUBLISH_*`, publish-узел, реальный `publication_status`); `sendRichMessage`/§104-контур/2-вызовность/DDL/каталог не затронуты; откат — revert.

**Минусы/цена.** Меняется вид живой публикации (единый HTML; markdown-таблицы деградируют в текст); OFF-доставка перестаёт быть байт-в-байт (AMEND зафиксирован); S8/S7-GATED-тесты перепрофилируются; `web/app.js` получает минимальные правки (§112-подписи, §110-маркеры).

**Ограничения (документируются).** Активация Hybrid — S10 (§107/§115); UI-слоты §85 — вне S6; стриминг-режим ортогонален §105 (вне diff); live-приёмка — за владельцем.

## Ссылки

- `plans/features/summary-publish-integration-round1026/{spec.md, tasks.md}`; Merge — `plans/ARCHITECTURE.md` **§80** (ожидаемо, T-3457); baseline-тег `pre-round1026-s6` → `197891f` (T-3435).
- Архивы: `plans/archive/summary-l2-writer-formatter-round1026/adr-1026-7-*.md`, `plans/archive/summary-logging-runid-round1026/adr-1026-9-*.md`, `plans/archive/summary-analytics-adapter-round1026/adr-1026-10-*.md`, `plans/archive/epic1-verification-round1025/adr-1025-24-*.md`.
- Код: `services/{summary_generator.py, telegram_send.py, summary_article_formatter.py, summary_l2_writer.py, summary_run_log.py, execution_graph_source.py, image_generation.py (read-only)}, web/static/execution_graph.js, web/app.js`.
- Внешние: `https://core.telegram.org/bots/api` (Rich Messages; снимок 24.09.2026), aiogram **3.31.0**.
