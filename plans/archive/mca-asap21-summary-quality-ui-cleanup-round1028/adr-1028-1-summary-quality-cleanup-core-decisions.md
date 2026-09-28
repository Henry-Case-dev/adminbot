# ADR-1028-1 — Quality cleanup: удаление S1/S2, §99 v1.1 (emphasis_spans/finale), deterministic Rich cut, typography normalizer

- **Статус:** Accepted (Step 2 @Architect, 28.09.2026; прод-валидация reconcile @Architect, 29.09.2026: деплой 2.58.34 VERIFIED — прод HEAD `8a0fa6c`, feat `219a55c`; live acceptance §43 подтверждена владельцем → gate §46 DONE)
- **История статуса:** Proposed → Accepted (Step 2, 28.09.2026 — именно эта редакция прошла ревью и деплой, sha256 `0F7CE3DE…164E458`) → подтверждён reconcile (29.09.2026; решения D1–D6 не менялись — прод-факты: prefilter-удаление в live, deterministic cut `rich_cut=1`, `emphasis_spans=33` на live-публикации, finale опционален `finale_present=0`, PL §44 desktop/mobile PASS)
- **Фича:** `mca-asap21-summary-quality-ui-cleanup` (эпик memory-context-autonomy, ASAP-трек)
- **Тип:** backend-архитектура + форматный контракт + presentation-layer frontend
- **Baseline:** прод 2.58.33 (`config/settings.py:2184`); каталог F8: 489/107/105/21
- **Связанные ADR:** **SUPERSEDE** ADR-1026-1 (S1 prefilter — удаляется из live), **SUPERSEDE** ADR-1026-4 (S2 context restore — роспуск; `build_l1_payload` переживает в `summary_l1_clusterizer`); **AMEND** ADR-1026-7 D2 (§99-документ: аддитивные `emphasis_spans`/`finale`, `schema_version` остаётся 1), **AMEND** ADR-1027-10 D7 (eviction без S1-веса), D8/контракт (k) (observability: +SOURCE_WINDOW, +L1_CONTEXT_PACK, −FILTER_*/RESTORE_*); ADR-1013-3 (промпт-миграции PREV_*/ROLLBACK) — действует; ADR-1026-11 (доставка rich/plain) — действует, дополняется details-блоком.

## Контекст

ASAP-2 (2.58.33) восстановил двухконтурный Hybrid Summary, но prod-проверка выявила: (1) heuristic prefilter S1 (`score_message`: reply/mention/burst/длина) повреждает вход L1 — теряются короткие центральные факты; S2 был его компенсацией; (2) RichMessage сворачивается непредсказуемо — collapsible-механизм в форматтере отсутствовал; (3) выделения нестабильны — единственный `emphasis`-string без контракта множественных span'ов; (4) «главный шиз» выбирался кодом по счёту сообщений (`_most_active_author`); (5) typography-инструкции соблюдались нестабильно — Hybrid-путь вообще не прогонял существующий нормализатор `cleanup_llm_text` (Legacy прогонял). Владелец требует удаления сущностей, а не выключателей (ASAP-2.1 §2:2866, §38).

## Решения

**D1. S1 удаляется из live полностью; технические примитивы переезжают в `summary_hybrid_budget.py`.**
Путь: `source messages → packing (только при физическом переполнении) → L1`. Переносятся с сохранением сигнатур: `estimate_and_split`, `Fragment`, `DEFAULT_FRAGMENT_OVERLAP`. `score_message`/`FilterParams`/`FilterResult`/`filter_window`/burst/mention-эвристики — удалены без реинкарнации под новым именем (запрет §38:3773). Eviction в `pack_l1_input` становится чисто техническим: `(reply_protected, timestamp, db_id)` — reply-цепочки (физическая связность пакета) вытесняются последними, вес «важности» исключён; последнее сообщение неприкосновенно, `truncated/skipped_ids/WARN` сохраняются. Альтернатива «флаг OFF» отклонена владельцем явно.

**D2. S2 роспущен; фиктивная стадия `restore` не сохраняется.**
`restore_context`/`RestoreParams`/`RestoreResult`/parent/neighbor-ядро — dead code (существовал только для возврата S1-удалённого). Единственный живой символ `build_l1_payload` (кодировщик §92) переносится в `summary_l1_clusterizer.py` — по реальной ответственности. Принятое поведение: reply-родитель вне 6-часового окна больше не добирается из БД (внутри окна он присутствует, `reply_to_id` в payload сохраняется; L1 семантически понимает контекст сам — §2:2864). `thread_chain.py` не трогается.

**D3. §99 v1.1 — аддитивный форматный контракт, `schema_version: 1` сохранён.**
`paragraphs[].emphasis_spans: [{text, kind: person|event}]` (опционально; точная подстрока финального clean-текста; invalid → игнор со счётчиком; overlap — детерминированная резолюция `(start, length desc, order)` с жадным приёмом; кап 4/абзац — анти «жирная каша»; тегоподобные спаны отбрасываются); derived-`emphasis` сохраняется для совместимости. Top-level опциональный `finale` (1..200, одна строка; невалидный → отброшен, `finale_present=0`; **никакого fallback на `_most_active_author`**). Альтернативы: `schema_version: 2` (отклонено — нет персистенции, ломает совместимость без пользы) и Markdown-генерация `**` от LLM (запрещена §38:3777 — formatting детерминирован кодом).

**D4. Rich cut — `<details><summary>` в html-режиме RichMessage.**
Проверено: aiogram 3.31.0 `InputRichMessage(html=…)` (Bot API 10.x) поддерживает collapsible block `<details>`/`<summary>` (native-эквивалент `InputRichBlockDetails{summary, blocks, is_open}`); `sanitize_outgoing` эти теги не трогает. Механика в `format_rich_html` (единственная точка сборки): img → `<h1>` → `<p>1</p>` → при >1 абзацах ОДИН закрытый `<details><summary>Читать дальше</summary>[p2..pN][finale]</details>`; 0–1 абзац — без ката. Cut — presentation layer: документ/L2/plain-фолбэк не затронуты (plain отдаёт полный текст — инвариант §1:2837). Альтернатива native `blocks`-массиву отклонена: минимальный дифф (структура `html`-конвейера, `rich_document_limits`, доставка — без изменений). Альтернатива «надеяться на клиентский auto-collapse» запрещена §38:3776.

**D5. Typography — детерминированный normalizer на базе существующего `cleanup_llm_text`, применяется к Hybrid L2-канонизации (title/paragraphs/finale) до substring-проверки спанов.**
Карта замен ровно 6 символов оформления («»„“→", —–→-), идемпотентна, содержание не трогает. Выбор против prompt-only: нормализатор уже существует и применяется на Legacy/factcheck/checkup (R33-7) — Hybrid был единственным контуром без него, что и давало нестабильность §17. Prompt-инструкции остаются первой линией; kill-switch/env не вводится (Δ каталога=0, конвенция контура безусловна).

**D6. «Главный шиз» — семантическое решение LLM.**
`_ensure_shiz_postfix`/`_most_active_author`/`_SHIZ_AT_RE` удалены из responsibility кода (§22); шутка живёт в канонах L2/Narrator/Single как опциональное творческое решение с полем `finale` (Hybrid) или свободной строкой (Legacy); `_SHIZ_MARKER` сохранён только как strip-константа в `_derive_fallback_cover_prompt` (шутка не должна попадать в visual-промпт обложки).

## Последствия

- L1 получает весь вход → устранён класс «потерянных коротких фактов»; окно физически большое — packing по serialized-оценке остаётся страховкой (инвариант §40 «technical overflow protection осталась»).
- Один форматный контракт (§99 v1.1) обслуживает rich-cut, bold-выделения и finale на всех трёх каналах доставки; documents без новых полей валидны — миграций нет.
- FILTER_*/RESTORE_* события и S1-поля SUMMARY_COMPLETE исчезают; §36-скелет закрывается аддитивно (SOURCE_WINDOW, L1_CONTEXT_PACK, поля L2_*/FORMAT_*).
- Откат: cold git-revert (фича-удаление, hot-флага нет и не должно быть); промпты — ROLLBACK на PREV_*_R1028; данные БД не удалялись — обратимо.
- Ограничения: reply-родители вне окна не восстанавливаются; per-chat-чтение stage-промптов зависит от аудита T-3965 (см. spec Q10/(h)).

## Альтернативы (сводно)

- Оставить S1 выключенным по умолчанию — отклонено владельцем (§38:3770–3771).
- Перенести `score_message` в budget-модуль — отклонено (§3:2919).
- `schema_version: 2` для emphasis_spans/finale — отклонено (см. D3).
- Native `blocks`-массив для cut — отклонено (D4, минимальный дифф).
- Prompt-only typography — отклонено (D5; гарантия §17 требует детерминизма).
- Сохранить S2 «на будущее» — отклонено (§4:2936: фиктивную стадию не оставлять; git-история и архив ADR-1026-4 сохраняют контракт).

## Затронутые контракты/требования

- Требования ASAP-2.1: §1–§5, §15–§25, §35–§36, §38–§41 (полная трассировка — spec.md раздел 8).
- Супергейды: ADR-1026-1 (D1–D7) и ADR-1026-4 (D1–D7) не применяются к live-коду начиная с 2.58.34; исторические документы сохранены в архиве как evidence.
- ADR-1026-7 (§99), ADR-1027-10 (D7/D8/контракт (k)) — действуют в редакции настоящего ADR.
