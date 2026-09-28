# mca-asap21-summary-quality-ui-cleanup — spec.md (спецификация @Architect)

- **Feature-ID:** `mca-asap21-summary-quality-ui-cleanup` (opaque, round1028)
- **Режим:** design (pre-Build); ответы Q1–Q10 даны ПО ФАКТИЧЕСКОМУ КОДУ (без speculative design — §39:3789–3791).
- **Нормативный источник (immutable):** `plans/current_task.md:2772–4061` (`# ASAP-2.1 / P0`, §1–§47). Ссылки — «§N:строка».
- **План PM:** `plans/features/mca-asap21-summary-quality-ui-cleanup/tasks.md` (T-3964…T-3998, блоки A–H).
- **Контрактные предки (НЕ ломать без явной санкции):**
  `plans/archive/mca-asap2-summary-pipeline-round1027/spec.md` + **ADR-1027-10** (двухконтурность, LEVEL-1/2/3, budgets, §99);
  `plans/archive/summary-filter-round1026/adr-1026-1` (S1 — **SUPERSEDED настоящим спеком**, см. D1 ADR-1028-1);
  `plans/archive/summary-context-restore-round1026/adr-1026-4` (S2 — **SUPERSEDED**, D2);
  `plans/archive/summary-l2-writer-formatter-round1026/adr-1026-7` (§99-контракт — **расширяется аддитивно**, D3).
- **Baseline:** прод **2.58.33** (`APP_VERSION` `config/settings.py:2184`), каталог F8: REGISTRY 489 / GROUPS 107 / `_TAB_BY_GROUP` 105 / TAB_RULES 21.
- **Risk-Level: R1** (общий) — фича трогает живую доставку статьи (Rich cut, emphasis, plain fallback) и требует обязательного прод-деплоя (§42). Разбивка по группам — раздел 6.
- **Browser-Verification: REQUIRED** — Prompt Library (desktop+mobile) и Cover Style — user-visible UI (§6, §12–§14, §44). Сценарии — раздел 5; инструмент — Playwright MCP (структурные behavior-checks), скриншоты — для layout-фактов мобильной секции анти-клише.
- **Deploy:** DEPLOY REQUIRED — единый релиз **2.58.34** после Reviewer Approved (§42, T-3993/T-3994). До успешного деплоя + live acceptance фича ACTIVE (§42:3910, §46).
- **ADR:** `adr-1028-1-summary-quality-cleanup-core-decisions.md` (в этой папке) — SUPERSEDE ADR-1026-1 (S1-удаление), ADR-1026-4 (S2-роспуск); AMEND ADR-1026-7 (§99 v1.1), ADR-1027-10 (D7 eviction, D8 observability).

---

## 1. Scope / Excluded scope

**В скоупе:** (1) полное удаление heuristic prefilter из live Summary (Hybrid И Legacy) с сохранением technical context packing; (2) роспуск dead-code `summary_context_restore`; (3) §99 v1.1: `emphasis_spans` + `finale` (backward-compatible); (4) детерминированный Rich cut (`details`); (5) typography: детерминированный normalizer (переиспользование `cleanup_llm_text`) + канон L2; (6) «главный шиз» — выбор LLM, удаление `_ensure_shiz_postfix`/`_most_active_author`; (7) Prompt Library desktop/mobile/cover-style фиксы + структура §9 + metadata-панель §10 + stale-guard; (8) удаление 8 ключей `summary_filter_*` из каталога/UI (отрицательный Δ, F8-переиздание); (9) observability §36; (10) dry-run паритет §35.

**ВНЕ скоупа (§37:3748–3762, §34:3667–3684):** Direct Context redesign, Unlimited context, verbatim retrieval, FORCE/REPLY/REACT/SILENT, 🗿, новая memory architecture, paradigms, OpenViking, новый GraphRAG; переработка backend image pipeline обложки; удаление Legacy Summary (§0:2790); незакоммиченная MCA-волна §93–§100 (~150 файлов — не трогать); `web/api/routes.py` (вне диффа); PG-DDL (Δ DDL=0); Direct Chat стиль/промпты (§15:3249 — не менять).

---

## 2. Ответы на Q1–Q10 (по фактическому коду)

### Q1 — Удаление heuristic prefilter с сохранением technical packing

**Факты.** Сегоднешний live-путь: `_run` (`summary_generator.py:473–498`) при `flags.summary_filter_enabled` вызывает `_apply_filter` (`:1392–1550`) → S1 `filter_window` (`services/summary_filter.py:299–382`, `score_message` `:200–225`: reply/mention + answered + burst + длина) → S2 `restore_context` (`summary_generator.py:1552–1618`). Hybrid получает `xml_rows` (отфильтрованные) в `_run_hybrid_l2` (`:515–517`), Legacy — тоже (`:522–524`). Зависимость L1 от S1: `summary_l1_clusterizer.py:42` (import `score_message`), `:332–356` (`_EVICTION_PARAMS`, `_eviction_key` — eviction-вес = `score_message`), `:382–471` (`pack_l1_input` использует `estimate_and_split` из `summary_filter.py:230–282`). Второй потребитель технической части — только `pack_l1_input`; legacy-обрезка контента независима (`truncate_to_tokens`, `summary_generator.py:657–678`).

**Решение.**
1. **`_run`:** блок `if flags.summary_filter_enabled` (`:477–498`) удаляется целиком; `xml_rows` более не существует как отдельная сущность — и Hybrid, и Legacy получают исходное `rows`. `ctx.saved_count/restored_count/drop_percent/filter_status/filter_duration_ms` перестают заполняться (поля удаляются из `RunContext`; `SUMMARY_COMPLETE` теряет filter-поля — см. раздел 4). Слот `self._filter_metrics` (`:404–406, 489–498, 1037, 1045, 1055, 552–554`) удаляется; `record_run_from_context(ctx, None)` уже толерантен к `None` (`execution_graph_source.py:304–316`) — узел `algorithm` исчезает из карты вызовов (замещается событиями §36).
2. **Удаляемые функции** (целиком, не «выключить»): `summary_generator.py`: `_apply_filter` (1392–1550), `_restore` (1552–1618), `_collect_extra_parents` (1620–1675), `_is_open_anchor` (1677–1693), `RESTORE_CHAIN_CALLS_MAX`, импорты `FilterParams/filter_window` (`:53`), `restore_context` (`:51`), `collect_thread_chain`; `services/summary_filter.py` — **модуль удаляется целиком**: `FilterParams`, `FilterResult`, `Fragment`, `filter_window`, `score_message`, `_burst_ids`, `_build_children_by_tg`, `_has_mention`, `_word_count`, `_is_trigger`, `_MENTION_RE`. **`score_message` не переносится ни под каким именем** (§3:2919, §38:3773).
3. **Нейтральный technical budget-модуль = существующий `services/summary_hybrid_budget.py`** (создавать третий модуль не нужно: он уже единая точка бюджета Hybrid из ADR-1027-10 D7). Туда переносятся из `summary_filter.py` ТОЛЬКО технические примитивы, с сохранением имён/сигнатур:
   - `estimate_and_split(kept, *, token_limit=None, char_limit=None) -> (fragments | None, budget)` (`summary_filter.py:230–282`);
   - `Fragment(index, message_ids, overlap_message_ids, reason)` (`:55–62`);
   - `DEFAULT_FRAGMENT_OVERLAP = 1` (`:38`);
   - строковые хелперы `_row_get/_row_id/_row_tg/_row_text/_row_ts` — НЕ дублировать: существующий `services.database.row_get` покрывает `_row_get`; однострочные обёртки остаются локальными в потребителях (как сейчас).
   `summary_l1_clusterizer` импортирует их из `summary_hybrid_budget`; импорт `score_message` и `_EVICTION_PARAMS` удаляются; `_eviction_key` (`:339–356`) переопределяется технически: **`(reply_protected, timestamp, db_id)`** — reply-защита (целостность reply-цепочек внутри пакета — физическая связность, не «важность») остаётся, весовой член `−weight_S1` удаляется. «Последнее сообщение неприкосновенно» и `truncated/skipped_ids/WARN` сохраняются (ADR-1027-10 D7).
4. **Новый путь:** `source messages` (`get_window_messages`) → `SOURCE_WINDOW` → `run_l1(rows)` → `pack_l1_input`: всё влезло → L1 получает ВСЁ; физическое переполнение → technical packing (`estimate_and_split` + serialized-учёт + eviction без веса) + WARN → L1. Проверка зависимостей (T-3966) подтверждает: других live-потребителей S1 нет (grep: только `summary_generator`, `summary_l1_clusterizer`, тесты).
5. **Legacy-контур** получает полное окно; его существующий prompt-бюджет/`truncate_to_tokens` (`:656–678`) и `max_summary_parts` — без изменений (ADR-1027-10 контракт (d)).
6. **Запреты §38** вшиты: не «default true→false», не спрятанный toggle, не увеличенные thresholds, `score_message` не реинкарнируется.

### Q2 — Dead code `summary_context_restore`

**Факты.** Модуль (`services/summary_context_restore.py`, 391 строк): `restore_context` (`:245–360`) + ядро `_walk_parents/_collect_neighbors/_index_by_tg/_key/_unit/_int_or/RestoreParams/RestoreResult/RESTORE_CHAIN_DEPTH` — существуют ТОЛЬКО для возврата сообщений, искусственно удалённых S1 (ADR-1026-4 прямо называет S2 «компенсацией»). Единственный genuinely-used символ — **`build_l1_payload(rows, chat_id)` (`:365–391`)**: канонический кодировщик §92, потребители: `summary_l1_clusterizer.py:38,313,466`, `summary_generator.py:786,1496`, `summary_test_run.py:39,584`, `summary_fact_package` (docstring-ссылка). S2-ключи (`context_neighbors/context_max_messages/reply_context_enabled`) — умирают вместе с S1 (§5).

**Решение.**
- `build_l1_payload` **переносится в `services/summary_l1_clusterizer.py`** (реальная ответственность: §92-вход L1; там уже есть `_payload_item`, построенный на нём). Сигнатура без изменений. Все 4 импортера переподключаются. Остальное содержимое модуля — **dead code, удаляется**; модуль `summary_context_restore.py` **удаляется целиком** (фиктивная стадия `restore` не сохраняется — §4:2936).
- Удаляемые вместе с генератором: адаптер `_collect_extra_parents`/`_is_open_anchor` + `RESTORE_CHAIN_DEPTH/RESTORE_CHAIN_CALLS_MAX` + единственное использование `thread_chain.collect_thread_chain` в summary. `services/thread_chain.py` сам НЕ трогается (принадлежит memory-контуру).
- Принятое поведение (задокументировать в ADR): reply-родитель **вне 6-часового окна** больше не добирается из БД; внутри окна родитель и так присутствует (L1 получает всё); `reply_to_id` в §92-payload сохраняется — L1 видит связь. Это осознанный семантический сдвиг к «L1 понимает сам» (§2:2864).
- **Audit-критерий (Reviewable, grep):** `rg "summary_context_restore|restore_context|RestoreParams|RestoreResult|RESTORE_START|RESTORE_COMPLETE|_collect_extra_parents"` по `services/` + `tests/` → 0 совпадений (кроме `plans/archive/`); `rg "build_l1_payload"` → ровно одно определение (`summary_l1_clusterizer.py`).

### Q3 — Минимальный backward-compatible контракт `emphasis_spans`

**Факты.** §99-документ v1 (`summary_l2_writer.py:57–88`): `{schema_version:1, title, paragraphs:[{text, emphasis|null}]}`; `TOP_LEVEL_FIELDS`/`PARAGRAPH_FIELDS` строгие — лишнее поле = `unknown_field` → reject (`:569,596`). Форматтер рендерит ≤1 `<b>` на абзац из одиночного `emphasis` (`summary_article_formatter.py:114–134`), span обязан быть дословной подстрокой clean-текста. Персистенции L2-документов нет (генерация → публикация); старые документы встречаются из `document_from_plain_text` (emphasis=None) и из LLM с прежним каноном.

**Решение — §99 v1.1, аддитивно, `schema_version` остаётся 1:**
- `PARAGRAPH_FIELDS := {"text", "emphasis", "emphasis_spans"}`; `TOP_LEVEL_FIELDS += {"finale"}` (Q4). Отсутствие новых полей валидно (старые документы/канон LLM не ломаются — это и есть backward-compat).
- `emphasis_spans`: массив объектов `{text: str, kind: str}`, `kind ∈ {"person","event"}`; прочие `kind` не бракуют документ (рендер одинаковый — bold), но пишутся в счётчик. Требования §19:3363–3369 реализуются детерминированной канонизацией в `_validate`:
  1. текст абзаца проходит `cleanup_llm_text` (см. Q-typography) → **финальный текст**; спаны чистятся той же картой замен до substring-проверки;
  2. span валиден ⟺ `text` — непустая точная подстрока финального текста абзаца, len ≤ `PARAGRAPH_MAX`, не содержит тегоподобных конструкций (`</?[A-Za-z]`);
  3. invalid span **молча игнорируется** (счётчик `emphasis_dropped_count`, документ валиден);
  4. overlap детерминирован: позиции = первое вхождение; сортировка `(start ASC, length DESC, порядок_в_JSON ASC)`; жадный приём без пересечений; дедуп по `text`;
  5. **кап ≤4 принятых span'ов на абзац** (анти «жирная каша», §18:3330); излишек отбрасывается со счётчиком;
  6. legacy `emphasis` (строка) = кандидат-span с приоритетом «первым в очереди» — документы прежнего канона рендерятся как сегодня;
  7. канонический вывод абзаца: `{"text", "emphasis": <первый принятый span | null>, "emphasis_spans": [..]}` — `emphasis` сохраняется как derived-поле для совместимости читателей/legacy-документов; рендер идёт по `emphasis_spans`, при пустом списке — по `emphasis`.
- **Raw HTML от L2 не проходит как разметка** структурно: весь текст/спаны проходят `sanitize_outgoing → html.escape` (`summary_article_formatter.py:127–134,152`), тегоподобные спаны отбрасываются п.2. L2-канон прямо запрещает HTML/`**Markdown**` (§38:3777).
- Formatter: `_render_*` переходит от `partition`-одиночки к секвенциальному рендеру принятых span'ов (walk по тексту, `<b>` вокруг каждого, всё экранируется) — один и тот же код для rich (`<p>`) и plain-HTML (`<b>title</b>`-блоки); raw-text fallback (`format_plain_text`) рендерит текст без markup, span'ы не теряются как текст (§20).

### Q4 — Представление LLM-`finale`

**Факты.** Сегодня «главный шиз» дописывается кодом в Legacy: `_ensure_shiz_postfix` (`summary_generator.py:1870–1880`) → `_most_active_author` (`:1882–1896`, максимум по счёту сообщений) → hardcode-строка `самым главным шизом объявляется {name}` (`_SHIZ_MARKER` `:376`). Hybrid этой строки не получает вовсе. Точки вызова: `:729` (legacy pipeline), тесты `test_summary_generator.py:252–277, 839–858`, маркер-строковый тест `test_summary_deploy_round1026.py:619`; защитный strip маркера в `_derive_fallback_cover_prompt` (`:2033`).

**Решение.**
- L2-документ получает **опциональное top-level поле `finale: str`** (минимальный вариант §24:3446–3450). Валидация (детерминированная, в `_validate`): строка, одна строка, после `cleanup_llm_text`+strip 1..200 симв.; невалидное/отсутствующее → canonical без `finale`, `metrics["finale_present"]=0`. **Code НЕ выбирает winner и НЕ имеет fallback на `_most_active_author()`** (§24:3466).
- Отображение: formatter выводит `finale` как последний блок статьи — в rich **внутри cut**, если cut применён (finale идёт после 1-го абзаца, а §1:2813 требует всё после 1-го абзаца под одним cat'ом), при 0–1 абзацах — видимой концевой строкой; в plain-HTML/plain-text — последним блоком (полный текст сохраняется, §20). Экранирование — общее (sanitize → escape).
- `_ensure_shiz_postfix`, `_most_active_author`, `_SHIZ_AT_RE` **удаляются**; вызов `:729` удаляется. `_SHIZ_MARKER`-strip в `_derive_fallback_cover_prompt` (`:2033`) **сохраняется** (защита: модель может написать шутку в тексте — в visual-промпт обложки она попасть не должна).
- Legacy (§25): инструкция «оцени сам и заверши строкой "Главным шизом объявляется …" или без неё — твоё творческое решение» входит в канон Narrator/Single (миграция T-3980); код поверх выбора модели больше ничего не дописывает.
- Грамматика строки — за LLM (канон требует заглавную букву/нормальную пунктуацию).

### Q5 — Детерминированный Rich cut в текущем formatter

**Факты.** Rich HTML собирается в `format_rich_html` (`summary_article_formatter.py:139–161`) и отправляется через `rich_document_limits` → `_publish_rich_document` (`summary_generator.py:1305–1331`) → `send_rich_message(content_format="html")` (`telegram_send.py:190–221`) → `InputRichMessage(html=...)`. Никакого collapsible-механизма сегодня нет — отображение зависит от клиента. **Возможности API проверены:** aiogram **3.31.0** (`InputRichMessage`: html/markdown/blocks/media) соответствует Bot API 10.x; HTML-режим RichMessage поддерживает блок `<details><summary>…</summary>…</details>` («collapsible block; `open` expands by default»; native-эквивалент `InputRichBlockDetails{summary, blocks, is_open}`) — источник: Bot API `InputRichMessage`/`InputRichBlockDetails` (aiogram 3.31.0 types) и сводка поддерживаемых тегов Rich message formatting options (`<details>/<summary>` среди block-тегов). `sanitize_outgoing` (`outgoing_guard.py`) режет только reasoning-теги/ID-маркеры — `<details>` не трогает (прецедент: `<h1>/<p>/<b>` проходят сегодня).

**Решение.** Cut строится в `format_rich_html` (единственная точка сборки rich-HTML):
- порядок: `[img cover]` → `<h1>title</h1>` → `<p>` абзац 1 → при **len(абзацев) > 1**: ОДИН закрытый `<details><summary>Читать дальше</summary>[<p>2</p>…<p>N</p>][finale]</details>`; атрибут `open` НЕ ставится (закрыт по умолчанию);
- **1 абзац (или 0) → ката нет** (`details` не эмитится); finale при этом — видимый концевой блок (Q4);
- cut — presentation layer: документ не меняется, L2 не видит cut, `plain`-каналы (`format_plain_html`, `chunk_plain_blocks`, `format_plain_text`) отдают ПОЛНЫЙ текст без ката — при падении RichMessage обычный `sendMessage` получает всю статью (§1:2837);
- `rich_document_limits` считает лимиты по полному HTML (обёртка details добавляет ~50–60 символов — в пределах существующего headroom 32000; блок-учёт не меняется, абзацы считаются по документу) — семантика fail-closed `too_long`/overflow→plain не меняется;
- зависимость от эвристики Telegram-клиента убирается: свёрнутость гарантирует `<details>`, а не угадывание.

### Q6 — Desktop: почему открывается только один prompt

**Факты (web/app.js).** Библиотека — workspace master-detail `#/ai/prompts/<slug>[/<stage>[/<promptKey>]]` (`parsePromptLibraryRoute:1167–1182`; для модулей без stage ключ `prompts.*` занимает слот stage по префиксу `prompts.` `:1178`). Фокус: `workspacePromptFocus` (`:2146–2159`) ищет `ws.promptKey` **только внутри `workspacePromptItems(ws.module, ws.stage)`**; фолбэк на полный список срабатывает лишь когда stage-список ПУСТ (`:2149–2150`), а при «ключ не найден» возвращается `null` (`:2157`) → секция-заглушка «Выберите промпт в списке» (`index.html:769–771`). Клик по дереву: `openWorkspacePrompt` (`:6245–6268`) строит URL с `seg = stage || ws.stage || item.stage || ''` — **залипший `ws.stage` имеет приоритет над stage самого item'а**. mod_summary не объявляет вкладки prompts/synthesizer/verbalizer (`WORKSPACE_TABS.mod_summary:584–585`), `_workspacePromptTabOf` даёт `prompts`; вход через библиотечную карточку «Вербализатор» даёт `ws.stage='verbalizer'` → дефолтный фокус = items[0] стадии verbalizer = «Вербализатор саммари (Рассказчик)» — он и открывается. Клик по любому другому item'у строит `…/verbalizer/<чужой-ключ>` → ключа в verbalizer-списке нет → фокус `null` → «ничего не происходит». Это в точности симптом владельца (§6:2972–2978).

**Фикс-план (минимальный):**
1. `openWorkspacePrompt`: `seg = stage || item.stage || ''` — убрать `ws.stage` из цепочки (URL всегда соответствует кликнутому item'у; для шести summary-промптов, у которых stage ∈ {synthesizer, verbalizer, None}, ссылки станут однозначными).
2. `workspacePromptFocus`: при непустом stage-списке, но ненайденном ключе — фолбэк на полный список модуля; ключ, не найденный нигде → `null` (и см. Q7 stale-guard).
3. Никаких пустых editor-состояний: если `promptKey` задан, но item не найден — UI возвращает список (Q7), а не глухую заглушку.
Acceptance: §12/§32 — все 6 открываются/редактируются/сохраняются.

### Q7 — Mobile: почему блокируется

**Факты.** CSS `web/static/app.css:2568–2575`: на ≤767px `.workspace-prompt-lib .prompt-editor{display:none}` (editor скрыт, пока список), а класс `is-editing` навешивается **по факту существования строки `promptKey`**, не валидного item'а (`index.html:742`), и даёт `.is-editing .prompt-tree{display:none}` + `.is-editing .prompt-editor{display:block}`. Итог при stale/invalid ключе (та же причина, что Q6): **список скрыт, editor — заглушка** → «список исчез, виден только …». Обратной кнопки «к списку» нет (дерево скрыто; дверь ведёт на страницу модуля, не в список). На глобальной странице `#/ai/prompts` (activeTab='prompts', `index.html:1011–1114`) блок «Анти-клише: динамический список» рендерится `col-span-full` **до** карточек групп промптов, с развёрнутым списком паттернов (до 200×2 колонки) — на mobile занимает экраны и вытесняет промпты (§14:3229–3231).

**Фикс-план (минимальный):**
1. **Stale promptKey guard:** `is-editing` и скрытие дерева привязать к `workspacePromptFocus` (валидно найденный item), не к сырому `promptKey` (`index.html:742`); invalid/stale ключ → режим списка + redirect на канонический `#/ai/prompts/<slug>` (§13:3212–3219).
2. **Явный back:** кнопка «← К списку» в editor-состоянии (navigate `#/ai/prompts/<slug>`) — flow §13:3199 «список → editor → save → назад к списку» без браузерного back.
3. **Анти-клише отдельной секцией (T-3983):** блок монитора переносится **ниже** промпт-контента и сворачивается в `<details>` по умолчанию (V2-раскладка не меняется по механике сохранения); editor доступен при открытом/свёрнутом блоке; на mobile он перестаёт быть первым экраном.
Acceptance: §13/§33 (browser REQUIRED), включая «invalid route не создаёт пустой editor».

### Q8 — Cover Style: почему editor не появляется

**Факт.** Генерация обложки читает `prompts.summary_cover_style` по цепочке **chat override → global hot → default** (`_resolve_cover_style_text`, `summary_generator.py:2069–2090`) — backend работает. Editor не появляется по той же причине, что Q6: у `summary_cover_style` `stage=None` (каталог `param_catalog.py:460–463`), при залипшем `ws.stage` URL `…/verbalizer/prompts.summary_cover_style` не резолвится в фокус → пустое состояние. Дополнительный фактор видимости: ключ помечен `progressive_level='advanced'` — при OFF `PROMPTS_UI_V2_ENABLED` он сидит под `<details>`-аккордеоном на глобальной странице (`promptVisibleItems:7424–7429`, `promptsShowAccordion:7406–7410`); в дереве workspace он есть всегда.

**Фикс-план:** те же два пункта, что Q6 (перестают строиться битые URL + фолбэк поиска); в структуре §9 у карточки «Обложка → Стиль обложки» явная группа и description; advanced-аккордеон для этой карточки в списке §9-структуры не применяется (ключ должен быть виден сразу — §9:3093–3104). Backend image generation НЕ трогается (§34). Допустимый проверяемый mismatch key→runtime отсутствует: runtime-ключ совпадает с UI-ключом; per-chat резолв уже реализован.

### Q9 — Карта 6 prompt-ключей (runtime vs UI-дубли)

| # | Key | Runtime-стадия | Контур | Читается (файл:строка) | Цепочка effective | UI сегодня | Решение UI |
|---|---|---|---|---|---|---|---|
| 1 | `prompts.summary_l1_clusterizer_system_prompt` | Hybrid L1 «Кластеризатор» | Hybrid, primary | `summary_l1_clusterizer.py:719–720` | `resolve_prompt`: hot(global PG) → код-канон | «Кластеризатор саммари (L1)», stage=synthesizer | Группа **Hybrid Summary → Кластеризатор (L1)**; описание §9 |
| 2 | `prompts.summary_l2_writer_system_prompt` | Hybrid L2 «Писатель» — **АКТИВНЫЙ HYBRID OUTPUT** | Hybrid, primary | `summary_l2_writer.py:57,897–898` | `resolve_prompt`: hot → код-канон | «Писатель саммари (L2)», stage=synthesizer | Группа **Hybrid Summary → Писатель статьи (L2)** + бейдж «АКТИВНЫЙ HYBRID OUTPUT» |
| 3 | `prompts.summary_system_prompt` | Legacy single-call | Legacy (OFF-путь и LEVEL-3) | `summary_generator.py:685–686` (`{max_symbols}` replace, без strip-guard) | hot → код-канон | «Системный промпт саммари», без stage | Группа **Legacy Summary Fallback → Legacy Single-call** |
| 4 | `prompts.summary_editor_system_prompt` | Legacy Stage-1 «Редактор» | Legacy two-call | `summary_generator.py:1754–1757` | `resolve_prompt` | «Синтезатор саммари (Редактор)», stage=synthesizer | Группа **Legacy → Legacy Editor** |
| 5 | `prompts.summary_narrator_system_prompt` | Legacy Stage-2 «Рассказчик» | Legacy two-call (kill-switch `SMART_VERBALIZER_MODES_ENABLED` → `PREV_SUMMARY_NARRATOR_R1023`) | `summary_generator.py:1794–1797` | `resolve_prompt` | «Вербализатор саммари (Рассказчик)», stage=verbalizer | Группа **Legacy → Legacy Narrator/Рассказчик** |
| 6 | `prompts.summary_cover_style` | Стиль обложки (оба контура) | Cover | `summary_generator.py:2083–2090` (`chat_params` → hot → `resolve_cover_style`) | **per-chat capable** | «Стиль обложки», advanced, без stage | Группа **Обложка → Стиль обложки** |

**Дубли:** все шесть ключей ведут к **разным runtime-стадиям** — ключевых дублей «два UI-пункта → один runtime key» НЕТ; объединять запрещено (§8:3046). Реальная проблема — **ложная лексика стадий**: каталоговые `stage='synthesizer'/'verbalizer'` (двухзвенное наследие 10.23) навешаны и на Hybrid L1/L2 (`param_catalog.py:509–518`), из-за чего UI подаёт L2-писателя как «синтезатор», а descriptions не говорят, кто Legacy. Решение: **один config key = один источник правды сохраняется**; catalog `title_ru` шести ключей приводится к §9-формулировкам («Кластеризатор (L1)», «Писатель статьи (L2)», «Стиль обложки», «Legacy Single-call», «Legacy Editor», «Legacy Narrator/Рассказчик») — Δ количества = 0 (F8-дифф фиксирует); группировка §9 (Hybrid / Обложка / Legacy) и бейджи — **presentation-слой app.js** (статическая карта `SUMMARY_PROMPT_META` по ключу → {pipeline, stage_label, runtime, group}; прецедент MEMORY_SUBGROUPS — витрина без Δ каталога). Дескрипшены каталога дополняются пометкой «Legacy fallback, не основной Hybrid writer» для №3–5.

### Q10 — Effective runtime prompt Hybrid L2 и процедура верификации на проде

**Цепочка резолва (код):** `run_l2` → `resolve_prompt("prompts.summary_l2_writer_system_prompt", SUMMARY_L2_WRITER_SYSTEM_PROMPT)` (`summary_l2_writer.py:897–898`) → `hot.get` (глобальный PG `bot_settings`) → код-канон `services/summary_prompts.py` (текущая база `_..._R1027_BASE`; снапшоты `PREV_*_R1026/R1027` участвуют в миграции `prompt_migrations.py:180–182`). **Per-chat override этим путём НЕ читается**, хотя каталог помечает все 6 ключей `per_chat=True` и Mini App в контексте чата сохраняет правки в `chat_params.overrides` — чтение per-chat сегодня реализовано только для cover style. Это кандидат в «пользователь правит — поведение не меняется» и входит в аудит T-3965.

**Процедура Builder (T-3965, начало Build, read-only, R17):** для каждого из 6 ключей и целевого прод-чата (PERMsoc):
1. снять значение глобального слоя (`bot_settings`), значение `chat_params.overrides` чата, код-канон и `PREV_*`-слепки;
2. зафиксировать: key / effective source (`chat_override` / `global` / `code_default`) / sha256-префикс 12 hex effective-значения / класс содержимого (`canonical_current` / `canonical_prev` / `custom`) / runtime stage — таблицей в `prompt-map-audit.md`; **полные тексты промптов в лог/документ не попадают** (§11:3170);
3. отдельно ответить: какой effective prompt реально управляет Hybrid L2 prod-output (ожидаемая гипотеза §11:3150–3160: code default уже R1027, но prod-global = старая канон-версия или custom — подтвердить/опровергнуть фактом).
**Следствие (фикс mismatch, если аудит подтвердит per-chat-значения):** генератор резолвит промпты чата-осознанно через единый хелпер `_resolve_summary_prompt(chat_id, key, default)` (`chat_params.get_chat_param` → hot → default, по образцу `_resolve_cover_style_text`) и передаёт в `run_l1/run_l2`/legacy-payload через существующие параметры `system_prompt`; Δ каталога = 0, один key = один source of truth. Если per-chat-значений на проде нет — цепочка документируется без правки кода (в(sp)ec-решение фиксируется в evidence).

---

## 3. Контракты

### (a) Технический packing (итог Q1.3) — точные переносы

| Символ | Откуда | Куда | Изменение |
|---|---|---|---|
| `estimate_and_split(kept, *, token_limit, char_limit)` | `summary_filter.py:230` | `summary_hybrid_budget.py` | без изменений |
| `Fragment(index, message_ids, overlap_message_ids, reason)` | `summary_filter.py:55` | `summary_hybrid_budget.py` | без изменений |
| `DEFAULT_FRAGMENT_OVERLAP=1` | `summary_filter.py:38` | `summary_hybrid_budget.py` | без изменений |
| `_eviction_key(row, *, kept_tg, children_by_tg)` | `summary_l1_clusterizer.py:339` | там же | ключ `(reply_protected, timestamp, db_id)`; `score_message`/`_EVICTION_PARAMS` удалены |
| `score_message`, `filter_window`, `FilterParams`, `FilterResult`, `_burst_ids`, `_build_children_by_tg`, `_has_mention`, `_word_count`, `_is_trigger`, `_MENTION_RE` | `summary_filter.py` | — | УДАЛЕНЫ (не переносятся) |
| `build_l1_payload(rows, chat_id)` | `summary_context_restore.py:365` | `summary_l1_clusterizer.py` | без изменений; модуль-источник удалён |

Инвариант Reviewer: `rg "score_message"` по `services/` → 0; `rg "summary_filter"` по `services/` → 0; `summary_hybrid_budget` не содержит весовых/бurst/mention-эвристик (только длина/токены/нарезка/бюджет).

### (b) Rich cut (итог Q5) — механика

`format_rich_html(document, *, cover_id, sanitize)`: `body = _iter_paragraphs(document)`; `cut = len(body) > 1`; вывод: `(img)` + `(h1)` + `<p>body[0]</p>` + `cut ? <details><summary>Читать дальше</summary> + p[1..N] + (finale-блок) + </details> : (finale-блок при наличии)`. Summary-текст константен (`Читать дальше`), детерминирован, экранируется. Plain-каналы без изменений (полный текст). `rich_document_limits` без структурных правок (доп. ~60 симв. внутри headroom; длина считается по фактическому HTML). Формат события — раздел 4 (`FORMAT rich_cut/visible_paragraphs/collapsed_paragraphs`).

### (c) §99 v1.1 (итог Q3/Q4) — сводка полей

```json
{
  "schema_version": 1,
  "title": "≤200, одна строка",
  "finale": "опционально; 1..200 симв., одна строка; иначе отброшено (finale_present=0)",
  "paragraphs": [
    {"text": "≤900 после cleanup",
     "emphasis": "первый принятый span | null (compat)",
     "emphasis_spans": [{"text": "точная подстрока text", "kind": "person|event"}]}
  ]
}
```
Валидация/детерминизм — Q3 (п.1–7); канонический вывод всегда содержит `emphasis` и `emphasis_spans` (список, возможно пустой) и `finale` только при валидности. Документы без новых полей валидны (старые записи/legacy-адаптер `document_from_plain_text` не меняются). Рендер-канал: rich `<b>`-сегменты; plain-HTML `<b>`; raw-text — без markup, полный текст.

### (d) Typography — решение (открытый пункт PM №3)

**Выбрано: deterministic normalizer, переиспользованием существующего `cleanup_llm_text` (`services/summary_cleanup.py`)** — НЕ prompt-only. Обоснование по §17 и коду: normalizer уже существует и применяется к Legacy (`summary_generator.py:716`) и factcheck/checkup (R33-7), заменяет ровно 6 символов оформления (`«»„“ → "`, `—– → -`) + strip reasoning-тегов, идемпотентен, содержание не трогает. **Hybrid-путь сегодня его не применяет вовсе** — это и есть нестабильность §17:3303. Решение: применить `cleanup_llm_text` к `title`/`paragraphs[].text`/`finale` в детерминированной канонизации `_validate` (`summary_l2_writer.py`) ДО substring-проверки спанов; спаны чистятся той же картой (Q3 п.1). Kill-switch/env не вводится (Δ каталога=0; конвенция R33-7 — безусловно на этом контуре). Prompt-инструкции (нет ёлочек/длинного тире) остаются первой линией в каноне L2 — normalizer даёт гарантию. T-3978 закрывается как «нужен», объём: 1 точка вызова + тесты-инварианты («содержание не изменено» посимвольно вне разрешённых замен; идемпотентность).

### (e) «Главный шиз»/finale — удаление из code responsibility (итог Q4)

Удаляются `_ensure_shiz_postfix` (`:1870–1880`), `_most_active_author` (`:1882–1896`), `_SHIZ_AT_RE`, вызов `:729`; тесты `test_summary_generator.py` (shiz-блок) и маркер `test_summary_deploy_round1026.py:619` переписываются на инвариант «code не выбирает winner» (grep-тест: `_most_active_author` отсутствует). `_SHIZ_MARKER` остаётся только как strip-константа в `_derive_fallback_cover_prompt`. Legacy Narrator/Single канон получают инструкцию §25 (миграция (g)).

### (f) Prompt Library frontend (итог Q6–Q9) — минимальный набор правок

1. `app.js openWorkspacePrompt`: `seg = stage || item.stage || ''` (убрать `ws.stage`).
2. `app.js workspacePromptFocus`: фолбэк на полный список модуля при ненайденном ключе в stage-списке; ключ не найден нигде → `null`.
3. `index.html:742` + `app.css`: `is-editing` от `workspacePromptFocus` (валидный item), а не от строки `promptKey`; invalid/stale `promptKey` → список + redirect `#/ai/prompts/<slug>`; кнопка «← К списку» в editor-состоянии.
4. Витрина §9: `SUMMARY_PROMPT_META` (presentation-карта по 6 ключам: pipeline/stage/runtime/group/бейдж «АКТИВНЫЙ HYBRID OUTPUT»/«Legacy fallback»); группы «Hybrid Summary», «Обложка», «Legacy Summary Fallback»; metadata-панель в editor: `Pipeline / Stage / Runtime / Key / Source` — Source из существующего `configSourceLabel` + (после (h)) реальная цепочка chat/global/default.
5. Анти-клише: блок монитора ниже промпт-контента, свёрнут по умолчанию (`<details>`), не перекрывает editor (desktop+mobile).
6. Mobile CSS: без `display:none` дерева при invalid ключе; тач-цели ≥44px сохраняются.
`web/api/routes.py` и backend конфиг-API не меняются (save уже работает через POST /api/config).

### (g) Prompt migration contract (§26, T-3980)

Механика ADR-1013-3 сохраняется. Изменяемые каноны: **L2 writer** (грамматика §15 + двачерский голос §16 + typography §17 + инструкция `emphasis_spans`/`finale` §18–19 + запрет HTML/`**`), **Legacy Narrator** и **Legacy Single** (инструкция §21/§25 — «шиза» выбирает модель, строка опциональна). Шаги: текущие базы → слепки `PREV_SUMMARY_L2_WRITER_R1028` / `PREV_SUMMARY_NARRATOR_R1028` / `PREV_SUMMARY_SYSTEM_R1028` (байт-в-байт), новые базы `_..._R1028_BASE`; `PROMPT_MIGRATIONS` += ступени (canonical-old → canonical-new); `PROMPT_ROLLBACK` += обратные; **genuinely-custom не трогается** (миграция матчит только точные канон-тексты — существующая семантика `prompt_migrations.py:102–182`). L1-канон НЕ меняется (L1 не пишет текст; §7:3062–3066). `summary_cover_style` — без миграций (только UI, §26:3495). Канон-эталон `plans/docs/canon/` обновляется атомарно с кодом и тестами.

### (h) Per-chat резолв промптов (условный, по Q10)

Если T-3965 найдёт per-chat-значения для stage-ключей: хелпер `_resolve_summary_prompt(chat_id, key, default)` в генераторе (chat_params → hot → default; fail-open на глобальный путь), прокидка в `run_l1(system_prompt=…)`/`run_l2(system_prompt=…)`/legacy payload (параметры уже существуют: `summary_l1_clusterizer.py:719`, `summary_l2_writer.py:897`). Источник для metadata-панели — тот же хелпер (Source: chat override/global/code default — честно). Иначе — только документирование цепочки. Решение фиксируется в `prompt-map-audit.md` + evidence.

### (i) Каталог / секция «Подготовка сообщений» / F8 (T-3973)

- Удаляются 8 ключей: `flags.summary_filter_enabled`, `flags.summary_filter_reply_context_enabled`, `limits.summary_filter_min_weight`, `limits.summary_filter_min_words_for_bonus`, `limits.summary_filter_burst_window_seconds`, `limits.summary_filter_min_burst_density`, `limits.summary_filter_context_neighbors`, `limits.summary_filter_context_max_messages` (registrations `param_catalog.py:1206–1216` + два флага группы `flags_summary_filter`) и 2 группы `flags_summary_filter` (`:368`), `limits_summary_filter` (`:303`); from `TAB_RULES` (TAB_MOD_SUMMARY, `:2289–2292`) frozenset-члены `flags_summary_filter`/`limits_summary_filter` убираются **in-place**.
- **Санкция отрицательного Δ каталога — ДАЮ (Architect), это прямое следствие Q1/§5:** REGISTRY **489 → 481** (−8), GROUPS **107 → 105** (−2), `_TAB_BY_GROUP` **105 → 103**, TAB_RULES **21** (без изменения счётчика; in-place правка). F8-переиздание обязательно: `plans/docs/param-registry-round1025.meta.md` (счётчики + APP_VERSION 2.58.34), `param-registry-round1025.tsv`, `plans/reports/round1025_f8_config_diff.md`, маркер-тесты каталога (`tests/fixtures/round1025/catalog_baseline.json`, `test_round1025_f8_registry`) — одним коммитом код+каталог+тесты.
- UI: вкладка **«Подготовка сообщений» удаляется** — `WORKSPACE_TABS.mod_summary` теряет `'prep'` (`app.js:584`); `workspaceGroupTab` (`:6312–6313`) теряет маппинг filter-групп; label `'prep'` (`:613`) удаляется. После удаления групп вкладка неприменима (`_workspaceTabApplicable`) — мёртвых тумблеров нет (§5:2963). Вкладки `clusterizer`/`writer` (стадийные витрины §84/§85) остаются вне этого решения.
- **Безопасность старых значений (§5:2965):** миграции данных НЕТ; строки `summary_filter_*` в `bot_settings` и в `chat_params.overrides` остаются и игнорируются: `hot_config._coerce` возвращает raw-значение при отсутствии spec (`hot_config.py:55–61`), читателей ключей после Q1 нет; startup не валидирует каталог против БД. Тест: startup + полный прогон с «грязной» БД (pre-seeded старые ключи) — зелёный. Это же делает откат безопасным (см. раздел 7).

### (j) Dry-run паритет (§35, T-3972)

`build_test_rows` (`summary_generator.py:1003–1061`): `_apply_filter` удаляется; возвращаемый shape сохраняется для UI: `filtered = source`, `dropped = []`, `restored = []`, `filter_metrics = {}` (+ `source_count/filtered_count/restored_count/limit`). `summary_test_run.py` (`:520–585`): L1 получает полный source (`run_l1(rows=filtered)` — packing внутри `run_l1` идентичен продy); stage «filter» в отчёте переименовывается по смыслу в «window/packing» без изменения API-ключа `result.stages["filter"]` (UI-совместимость), поля `saved_count/restored_count/drop_percent` отдаются как `None`/нули; отображаются packing-счётчики L1 (`truncated/skipped`) — dry-run отражает отсутствие фильтрации (короткие сообщения присутствуют). Side effects в dry-run отключены как сегодня (0 отправок/0 image/0 памяти — `summary_test_run.py` неизменен в этой части).

---

## 4. Observability §36 — схема событий (аддитивная)

Принцип как в ASAP-2 (k): имена зафиксированных событий НЕ переименовываются; новые события/поля аддитивны; R17 — только числа/коды/id; **raw messages, тексты, приватные промпты — никогда** (§36:3744).

| §36 | Фактическое событие | Поля |
|---|---|---|
| SUMMARY_START | `SUMMARY_START` (сущ.) | без изменений |
| SOURCE_WINDOW | **НОВОЕ** `SOURCE_WINDOW` (INFO, в `_run` после чтения окна) | run_id, chat_id, messages (=source_count) |
| — | ~~`FILTER_START`/`FILTER_COMPLETE`/`FILTER_EMPTY_FALLBACK`/`FILTER_ERROR`/`RESTORE_*`~~ | **УДАЛЕНЫ вместе с S1/S2** (замещены SOURCE_WINDOW/L1_CONTEXT_PACK) |
| L1_CONTEXT_PACK | **НОВОЕ** `L1_CONTEXT_PACK` (INFO, в `run_l1` после `pack_l1_input`) | run_id, chat_id, source_messages, packed_messages, serialized_tokens, physical_budget, overflow (0/1=truncated), skipped, kind(tokens/chars) |
| L1_START / L1_PARSE / L1_REPAIR / L1_CORRECTION_RETRY / L1_COMPLETE | сущ. (ASAP-2) | без изменений |
| FACT_PACKAGE | `FACT_PACKAGE_START/_COMPLETE`, `L1_FALLBACK_PACKAGE` (сущ.) | без изменений |
| L2_START | `L2_START` (сущ.) | + **effective_prompt_key** (`prompts.summary_l2_writer_system_prompt`), **prompt_source** (`chat/global/default`); response_mode/target_* сохраняются |
| L2_COMPLETE | `L2_COMPLETE` (сущ.) | + **emphasis_spans** (принято шт.), **emphasis_dropped** (сущ. счётчик переиспользуется), **finale_present** (0/1); chars/paragraphs сохраняются |
| FORMAT | `FORMAT_START/_COMPLETE/_ERROR` (сущ.) | FORMAT_COMPLETE (channel=rich): + **rich_cut** (0/1), **visible_paragraphs**, **collapsed_paragraphs**; (channel=plain): rich_cut=0, visible=all |
| COVER | `COVER_*` (сущ.) | без изменений |
| PUBLISH_RICH | `PUBLISH_RICH_*` (сущ.) | без изменений |
| SUMMARY_DONE | `SUMMARY_COMPLETE`/`SUMMARY_FAILED` (сущ.) | **минус** saved_count/restored_count/drop_percent (S1-поля); fallback=/publication_status= сохраняются |

JS log-viewer фильтр «Саммари» (§110): проверить, что префикс-правило покрывает `SOURCE_WINDOW`/`L1_CONTEXT_PACK` (правка JS-списка при необходимости, Δ каталога=0); JS-харнесс `tests/js/round1026_s7_log_summary_filter_test.js` переписывается под новые события; `test_summary_logging_runid.py` обновляется (новые поля, отсутствие FILTER_*).

---

## 5. Browser-сценарии (Playwright MCP, REQUIRED)

Окружение: локальный webapp (uvicorn) на тестовой БД; существующий test-админ-сессии механизм; prod-credentials и Telegram не используются. Entry: `#/ai/prompts` (глобальная) и `#/ai/prompts/summary` (дверь библиотеки). Viewports: 1440×900 и 390×844.

- **B1 (desktop, структурный):** из библиотечной карточки «Саммаризация» (без stage) видны 6 промптов в группах §9; клик по КАЖДОМУ → editor с непустым textarea, корректным Key и metadata-панелью (Pipeline/Stage/Runtime/Key/Source).
- **B2 (desktop, регресс Q6):** открыть «Legacy Narrator» (стадия verbalizer), затем кликнуть «Кластеризатор (L1)» → editor переключается на L1 (сегодня — баг), URL `…/summary/synthesizer/prompts.summary_l1_clusterizer_system_prompt`.
- **B3 (desktop, интеракция):** для каждого из 6: edit → save → ровно 1 POST /api/config → reload → значение persisted; после теста вернуть исходное значение.
- **B4 (mobile 390×844, структурный):** `#/ai/prompts`: список групп промптов достижим БЕЗ прокрутки сквозь развёрнутый анти-клише (блок свёрнут/ниже); открыть `#/ai/prompts/summary`: дерево видно; клик по prompt → editor видим, дерево скрывается только при валидном фокусе; «← К списку» возвращает список.
- **B5 (mobile, stale-guard):** открыть `#/ai/prompts/summary/verbalizer/prompts.summary_cover_style` (stale-комбинация) → НЕТ пустого editor; UI в режиме списка (или redirect на `#/ai/prompts/summary`); console без ошибок.
- **B6 (mobile, анти-клише):** развернуть блок анти-клише → editor/список остаются доступны (не перекрыты); свернуть → без изменений; console чистый на всех шагах.
- **B7 (гигиена):** на всех шагах console без ошибок; сеть — только ожидаемые GET/POST конфига.

Скриншоты обязательны для B4/B6 (layout-факт мобильной секции); остальное — структурные DOM/network-проверки.

---

## 6. Риски по группам

- **R1 (живая доставка/прод-деплой):** T-3974 (Rich cut — меняет rich-HTML каждой статьи), T-3976, T-3981/3982/3984/3985 (конфиг-UI), T-3993–3997. Причина: отказ = сломанная публикация/потеря текста. Митигации: cut не меняет документ (plain-фолбэк полный — тест T-3988.4); rich_document_limits fail-closed сохранён; PL-правки — presentation-слой, backend конфиг-API не тронут; деплой-гейт §46 из 6 компонентов.
- **R2 (живой пайплайн генерации/данные PG):** T-3969–3971 (путь до L1), T-3973 (каталог, F8), T-3975, T-3977–3980 (§99 v1.1 + каноны + миграции), T-3986. Причина: L1/L2-контракты, eviction, промпты. Митигации: packing-механика сохранена (только без весового члена), последнее сообщение неприкосновенно, PREV-слепки + ROLLBACK (g), migration-тесты (a/b/c) T-3980, каталог атомарно с маркер-тестами, старые PG-значения игнорируются безопасно (i).
- **R3 (механика/тесты/observability/UI-вёрстка):** T-3964–3968 (аудиты), T-3972 (dry-run), T-3983, T-3986–3992, T-3998. Причина: не меняют runtime-семантику доставки.

## Риски-замечания (что может повысить уровень)

- Правка `web/api/routes.py` или PG-DDL — только через эскалацию к Orchestrator (ожидание: 0).
- Если (h) потребует изменений контракта `run_l1/run_l2` глубже параметра `system_prompt` — вернуть на согласование (не делать молча).

---

## 7. Тестирование / деплой / откат

- **Тесты:** T-3987 (§27: «у кота рак», «Леха уехал» доходят до L1; 500 сообщений в бюджете — все доступны; overflow → technical packing + WARN + отсутствие score_message), T-3988 (§28: 1 абзац — без ката; 2/N абзацев — p1 виден, rest под ОДНИМ закрытым details, ничего не потеряно; rich failure → plain полный), T-3989 (§29: 3 span'а bold в rich, invalid не ломает; §30 стиль/typography; §31: A=30/B=5 — winner из LLM, code не подставляет A), T-3990/T-3991 (§32/§33 PL desktop/mobile, browser REQUIRED), T-3992 (полный pytest + JS-харнессы + обновлённые каталог-маркеры). Интеграционные: тесты S1/S2 (`test_summary_filter*.py`, `test_summary_context_restore*.py`) удаляются; `test_summary_l2_integration`, `test_summary_logging_runid`, `test_summary_test_api/test_summary_test_run`, `test_summary_deploy_round1026`, `test_summary_asap2_miniapp_round1027`, `test_frontend_tab_mapping`, `test_summary_publish_integration_round1026` — переписываются под новую семантику.
- **Deployd-применимость:** единый релиз 2.58.34 (T-3993), feat-коммит + docs-коммит после Reviewer Approved; прод-деплой T-3994 (§42), live acceptance T-3995/3996, log-check T-3997, gate §46 (T-3998).
- **Откат:**
  - **Prefilter-удаление — фича-удаление, НЕ флаг:** hot-отката нет (владелец прямо запрещает «оставить выключенным», §38:3770). **Откат = cold git-revert feat-коммита** → возврат к 2.58.33 (сирота-значения `summary_filter_*` в БД снова подхватываются старым кодом — обратимо, т.к. данные не удалялись). Промежуточная защита без отката: существующий `flags.summary_legacy_fallback_enabled`/`flags.summary_hybrid_l2_enabled` (аварийные режимы ADR-1027-10) остаются.
  - Каноны: ROLLBACK-миграция на `PREV_*_R1028` (механика (g)) — без рестарта кода.
  - Rich cut / emphasis / finale: revert (персистенции нет); plain fallback инвариантен.
  - Каталог: revert + повторное F8-переиздание (процедура документирована); удалённые строки БД не тронуты — откат без потерь.
  - UI PL: revert frontend-коммита; CSP/zero-build сохраняются.

---

## 8. DoD §41 (1–22) → контракты/задачи/тесты

| DoD | Контракт/решение | Задачи | Тесты/доказательство |
|---|---|---|---|
| 1 Prefilter удалён из live | Q1 (модуль/вырезание) | T-3969 | T-3987; grep-инварианты (a) |
| 2 Filter controls удалены из Miniapp | (i) | T-3973 | каталог-маркеры F8; B1–B7 (нет prep-вкладки) |
| 3 Packing независим от scoring | Q1.3/(a) | T-3970 | T-3987.4; grep score_message=0 |
| 4 Короткие доходят до L1 | Q1 путь | T-3969 | T-3987.1–2 |
| 5 Cut после первого абзаца | (b) | T-3974 | T-3988.2–3; B-канал rich |
| 6 Collapsed body не теряется | (b) | T-3974 | T-3988.3 |
| 7 Plain fallback полный | (b) | T-3974/3976 | T-3988.4 |
| 8/9 Имена/события bold | (c) | T-3975/3976 | T-3989 (§29) |
| 10 Deterministic formatting | (c) | T-3975/3976 | T-3989; overlap-тесты |
| 11–13 Грамматика/голос/без lowercase | (g)+Q-typography | T-3977 | T-3989 (§30); live T-3995 |
| 14/15 Шиз — LLM; code не считает | (e)+Q4 | T-3979 | T-3989 (§31); grep `_most_active_author`=0 |
| 16 PL разделяет роли | Q9/(f) | T-3984 | B1–B2; Reviewer §40 |
| 17 Desktop все открываются | Q6/(f) | T-3981 | T-3990 |
| 18 Mobile все открываются | Q7/(f) | T-3982 | T-3991 (browser) |
| 19 Cover Style open/edit/save/reload | Q8/(f) | T-3985 | T-3990/3991 + live T-3996 |
| 20 Cover backend без регрессии | Q8 (не трогаем) | T-3985 | T-3992; live T-3995/3997 |
| 21 Effective L2 prompt установлен и проверен | Q10/(g)/(h) | T-3965/3977/3980/3986 | prompt-map-audit.md + `L2_START effective_prompt_key` |
| 22 Tests green | все | T-3987–3992 | полный pytest + JS |

**Reviewer-чеклист §40 (20 инвариантов)** — каждый покрывается строками таблицы выше + grep-инвариантами (a), (e), разделом 4; особые: «old heuristic scoring не переехал» — grep `score_message|burst|mention` в `summary_hybrid_budget`/`summary_l1_clusterizer` = 0; «L2 Writer действительно текущий Hybrid output» — Q9-карта + B1; «effective production prompt source проверен» — T-3965 evidence.

---

## 9. Санкции Architect (открытые пункты PM)

1. **Отрицательный Δ каталога — УТВЕРЖДЁН:** −8 ключей, −2 группы; счётчики и F8-переиздание — (i). Отдельного design-решения не требует (следствие Q1).
2. **Typography (T-3978) — deterministic normalizer, переиспользование `cleanup_llm_text` на Hybrid L2-канонизации** — контракт (d). Prompt-only признан недостаточным: нормализатор уже существует и уже применяется к Legacy — симметрия и гарантия §17:3311 достигаются одной точкой вызова.
3. **F8-переиздание** — обязательно в релизе 2.58.34 (счётчики раздела 8/(i)); артефакты и маркер-тесты — атомарно.

## 10. Расхождения для PM (consistency-check tasks.md ↔ spec)

1. **T-3966/T-3970:** нейтральный модуль = существующий `summary_hybrid_budget.py` (PM-формулировка «technical context/budget module» допускала новый модуль; создавать третий не нужно). Список переносов фиксирован — (a).
2. **T-3967/T-3971:** `build_l1_payload` переезжает в `summary_l1_clusterizer.py`, модуль `summary_context_restore.py` удаляется целиком (не «оставить с честной ответственностью»). Audit-критерий — Q2.
3. **T-3969:** удаление затрагивает и Legacy-вход (`xml_rows` исчезает) — формулировка задачи «live Hybrid-путь» должна покрывать оба контура (§2:2866 «из live Summary pipeline полностью»).
4. **T-3973:** Δ-счётчики и перечень правок TAB_RULES — (i); плюс удаление `'prep'` из `WORKSPACE_TABS.mod_summary` и JS-мэппинга (это frontend-правка в объёме T-3973, не только каталог).
5. **T-3975/T-3976:** имя поля зафиксировано: `emphasis_spans` (совместимо: `schema_version` остаётся 1, поле опционально); кап 4 span/абзац и сохранение derived-`emphasis` — дополнить критерии.
6. **T-3978:** решён — normalizer НУЖЕН, на базе `cleanup_llm_text`, без нового env/kill-switch (контракт (d)); задача снимается с статуса «опциональный».
7. **T-3979:** в объём входит удаление `_SHIZ_AT_RE` и сохранение `_SHIZ_MARKER`-strip в `_derive_fallback_cover_prompt` (деталь (e)).
8. **T-3980:** миграции затрагивают L2 + Narrator + **Legacy Single** (§25 говорит «Narrator / Single-call»); L1-канон не меняется.
9. **T-3981/3982/3984/3985:** фикс-план (f) — правки в 4 точках app.js/index.html/app.css + presentation-карта; backend конфиг-API и `routes.py` не трогаются. Метаданные Source станут честными только после решения (h) — связка с Q10/T-3965.
10. **T-3986:** событие `SOURCE_WINDOW` добавляется к списку §36-имён (в tasks.md перечислен скелет без него — фактически он первый после SUMMARY_START); FILTER_* удаляются (в tasks.md это отмечено, состав полей — раздел 4).
11. **T-3965:** добавлен факт `per_chat=True` у всех 6 ключей и потенциальный mismatch «UI пишет per-chat, runtime читает global» — критерий аудита дополнен; условный фикс (h).
12. **Каталог-титулы 6 промптов** меняются на §9-формулировки (контент, не количество) — учесть в F8-диффе T-3973/T-3993.

## 11. Зависимости и совместимость

- Внешние зависимости: **0 новых** (aiogram ≥3.31 RichMessage details — уже установленная версия; stdlib + существующие модули). Обоснование: задача — удаление сущности + презентационные фиксы; новых capability-доменов нет.
- Backward compatibility: §99 v1.1 аддитивен (старые документы валидны; `emphasis` сохранён); pg/env-именаLegacy не переименовываются; удалённые `summary_filter_*` значения в БД игнорируются и обратимо; dry-run API-форма сохранена.
- Миграции данных: нет (Δ DDL=0); промпт-миграции — идемпотентные PG-записи существующим механизмом.
- Security/privacy: R17 — события только с числами/кодами; sha256-префиксы промптов только в audit-документе (не в runtime-логах); egress-санитизация не ослабляется (`<details>` проходит существующий sanitize как и `<h1>`).
