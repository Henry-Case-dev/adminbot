# mca-asap21-summary-quality-ui-cleanup — tasks.md

- **Feature-ID:** `mca-asap21-summary-quality-ui-cleanup` (стабильный opaque ID; порядок НЕ кодируется префиксом)
- **Родительская задача:** `memory-context-autonomy` (MCA, round1027), ASAP-трек: ASAP-2 ✅ (прод **2.58.33**, ADR-1027-10, архив `plans/archive/mca-asap2-summary-pipeline-round1027/`) → **ASAP-2.1 (эта фича, P0 владельца)** → прод-деплой → production acceptance → ASAP-3 (`mca-asap3-direct-context-reply-reliability`). Между фичами к обычным MCA-волнам НЕ возвращаться (ASAP-2.1 §47:4030–4056).
- **Источник требований (immutable):** `plans/current_task.md`, блок `# ASAP-2.1 / P0`, **строки 2772–4061** (разделы §1–§47: проблемы §1–§6, PL-структура §7–§14, стиль/typography §15–§17, formatting §18–§20, «главный шиз» §21–§26, тесты §27–§33, границы §34–§38, вопросы Architect Q1–Q10 §39:3787–3833, invariants Reviewer §40:3837–3860, DoD §41:3864–3889, прод-деплой §42:3893–3910, live acceptance §43–§45, acceptance gate §46:3998–4026, ASAP-3 §47). Файл не редактируется; ссылки ниже — «ASAP-2.1 §N (current_task.md:строка)».
- **Статус плана:** **PLANNING_CONSISTENT (Step 3 @PM, 28.09.2026).** `spec.md` @Architect существует (ответы Q1–Q10 по фактическому коду + контракты (a)–(i); SHA-256 `7B7461D0A3648B0D696D9C5813A924D691D505B04F26C091C54C5C901341B0CD`) + `adr-1028-1-summary-quality-cleanup-core-decisions.md` (SHA-256 `0F7CE3DE205081E443AEFEAE8BD25B23FD8CB245CCD479F0CCACAB4B3116E458`). Все 12 расхождений раздела 10 spec устранены в этом tasks.md — см. таблицу «Сверка tasks ↔ spec (раздел 10 spec)» в конце файла. Блокирующих вопросов к Architect нет. `[ARCH Qn]`-задачи разблокированы решениями spec; фактические результаты `[MECH]`-аудитов блока A остаются фактическим входом прод-верификации T-3965 и миграций T-3980.
- **ID-диапазон:** **T-3964…T-3998 (35 задач)**. Преемственность: T-3935…T-3963 заняты ASAP-2 (архив); дублей нет.
- **Baseline:** прод **2.58.33** (HEAD `c0f299c`, docs `8663214`), dual-circuit Summary (Hybrid L1/L2 + Legacy fallback) уже на проде; `APP_VERSION` в коде `config/settings.py` = 2.58.33; архивы контрактов: `plans/archive/mca-asap2-summary-pipeline-round1027/` (spec/ADR-1027-10/review/deployment), `plans/archive/summary-*-round1026/` (S1 prefilter, S2 context_restore, S5 l2_writer/formatter).

## Scope OUT (границы владельца — НЕ включать в скоуп)

- **§37:3748–3762** — не делать в ASAP-2.1: Direct Context redesign, Unlimited context, verbatim old dialogue retrieval, FORCE/REPLY/REACT/SILENT, 🗿, новая memory architecture, paradigms, OpenViking, новый GraphRAG (всё это — ASAP-3 и далее).
- **§34:3667–3684** — backend cover generation работает; не превращать задачу Cover Style в переработку image pipeline (чинить только доказанный mismatch key→runtime key).
- **Legacy Summary не удалять** (§0:2790) — остаётся рабочим fallback-контуром; обновляется только инструкция Narrator/Single (§25).
- **Незакоммиченный WIP MCA-волны §93–§100 (~150 файлов в `git status`) — НЕ включать в скоуп и НЕ ТРОГАТЬ.**
- Канон-дисциплина: правки промптов = константа в коде + эталон `plans/docs/canon/` + тесты атомарно; R17 (сырые сообщения/приватные промпты целиком не логировать, §11:3170, §36:3744).

## Пометки задач

- `[ARCH Qn]` — форма/параметры задачи определяются ответом Architect на вопрос Qn (§39) в `spec.md` раздел 2. После Step 3 все `[ARCH Qn]`-задачи разблокированы; пометка сохраняется как ссылка на управляющее решение spec (Q1–Q10 + контракты (a)–(i)).
- `[MECH]` — механическая задача: не требует новых архитектурных решений (после spec для зависимых по данным задач).
- Риски: **R1** — задевает живую доставку/публикацию/прод-деплой; **R2** — задевает живой пайплайн генерации/данные PG; **R3** — механика/тесты/наблюдаемость/UI-вёрстка.

## Порядок и зависимости

1. **Блок A (T-3964…T-3968)** — независимо, сразу; результат → @Architect как факты для Q1/Q2/Q4/Q9/Q10 (§39: «сначала подтвердить фактическое состояние кода», без speculative design). **Выполнен; факты вошли в spec раздел 2.**
2. ✅ @Architect: `spec.md` + ответы Q1–Q10 + контракты (a)–(i) + ADR-1028-1 — выполнено 28.09.2026, включая санкцию отрицательного Δ каталога (T-3973) и решение по T-3978.
3. **Блоки B∥C∥D∥E∥F** — после spec (внутри блоков порядок по нумерации); F (T-3986) зависит от фактических полей B/C.
4. **Блок G** — тесты пишутся вместе с реализацией, зелёные до H.
5. **Блок H** — только после Reviewer Approved (§42:3895–3909).

---

## Блок A — Аудит ДО изменений (факты для Q1/Q2/Q4/Q9/Q10)

### T-3964 — Карта 6 prompt-ключей (deliverable для Q9/Q10)
- **Метка:** [MECH]. **Риск:** R3.
- **Суть:** составить точную карту «prompt key → runtime stage → Hybrid/Legacy → primary/fallback → откуда берётся effective value → где редактируется в UI» для `prompts.summary_l1_clusterizer_system_prompt`, `prompts.summary_l2_writer_system_prompt`, `prompts.summary_system_prompt`, `prompts.summary_editor_system_prompt`, `prompts.summary_narrator_system_prompt`, `prompts.summary_cover_style` — по actual execution path, НЕ по названиям UI (§7:2997–3027). Явно показать: какой prompt пишет текущую Hybrid статью; какой только Legacy; какой структурирует L1; какой задаёт стиль обложки.
- **Acceptance:** deliverable-документ `plans/features/mca-asap21-summary-quality-ui-cleanup/prompt-map-audit.md`; все 6 ключей покрыты; каждое утверждение подтверждено ссылкой на код (файл/функция/стадия вызова); отдельно отмечены UI-пункты «Писатель саммари» / «Вербализатор саммари (Рассказчик)» / «Системный промпт саммари» — реальные стадии, legacy или accidental duplicates (факты для Q9:3827).

### T-3965 — Effective PG-значения на проде + аудит per-chat mismatch (deliverable для Q10)
- **Метка:** [MECH] (выполняется в начале Build; read-only к прод-БД; R17). **Риск:** R3.
- **Суть:** процедура прод-верификации по spec Q10 для каждого из 6 ключей и целевого прод-чата (PERMsoc): (1) снять значение глобального слоя (`bot_settings` hot PG), значение `chat_params.overrides` чата, код-канон (`services/summary_prompts.py`, база `_..._R1027_BASE`) и `PREV_*`-слепки; (2) зафиксировать таблицей в `prompt-map-audit.md`: key / effective source (`chat_override` / `global` / `code_default`) / sha256-префикс 12 hex effective-значения / класс содержимого (`canonical_current` / `canonical_prev` / `custom`) / runtime stage. **Полные тексты промптов в лог/документ не попадают** (§11:3170, R17). Особо `prompts.summary_l2_writer_system_prompt`: подтвердить/опровергнуть гипотезу «code default уже R1027, но prod-global = старая канон-версия или custom» (§11:3150–3160). **Отдельный пункт проверки (факт spec Q10, расхождение 11):** все 6 ключей каталога помечены `per_chat=True`, Mini App сохраняет правки в `chat_params.overrides`, но runtime читает per-chat только для cover style — зафиксировать факт наличия/отсутствия per-chat-значений stage-ключей на проде (кандидат в «пользователь правит — поведение не меняется»); при подтверждении значений — условный фикс (h) spec (хелпер `_resolve_summary_prompt(chat_id, key, default)`, Δ каталога = 0), при отсутствии — только документирование цепочки без правки кода.
- **Acceptance:** таблица в `prompt-map-audit.md` с полями выше на каждый из 6 ключей; расхождения code default ↔ PG override явно отмечены; ответ «какой effective runtime prompt реально управляет Hybrid L2 production output» сформулирован как факт; по per-chat mismatch — явный вывод «per-chat-значения есть/нет» и решение по (h), зафиксированные в evidence.

### T-3966 — Dependency audit `summary_l1_clusterizer` → `summary_filter` (для Q1)
- **Метка:** [MECH]. **Риск:** R2.
- **Суть:** перечислить все импорты/вызовы/символы `summary_l1_clusterizer` (и прочих live-стадий) из старого S1 `summary_filter` (§3:2908) **по фиксированному контракту (a) spec**: нейтральный technical budget-модуль = **СУЩЕСТВУЮЩИЙ `services/summary_hybrid_budget.py`** — новый модуль НЕ создаётся (расхождение 1 spec §10); переносу с сохранением имён/сигнатур подлежат ТОЛЬКО `estimate_and_split`, `Fragment`, `DEFAULT_FRAGMENT_OVERLAP`; строковые хелперы `_row_*` не дублируются (`services.database.row_get` + локальные обёртки потребителей); eviction-ключ `pack_l1_input` переопределяется технически `(reply_protected, timestamp, db_id)` — без S1-веса. Явный список НЕ переносимого: `score_message()`, `filter_window`, `FilterParams`, `FilterResult`, burst/mention-эвристики (§3:2919, §38:3773).
- **Acceptance:** инвентарь полон (grep по коду и тестам); по каждому символу судьба по контракту (a): перенос в `summary_hybrid_budget` / удаление / техническое переопределение; `score_message` помечен «удалить, не переносить под новым именем»; подтверждено: других live-потребителей S1 нет (grep: только `summary_generator`, `summary_l1_clusterizer`, тесты); результат — факты для Q1 (§39:3793).

### T-3967 — Dead-logic аудит `summary_context_restore` (для Q2)
- **Метка:** [MECH]. **Риск:** R2.
- **Суть:** классификация по контракту spec Q2: единственный genuinely-used символ — `build_l1_payload(rows, chat_id)` (кодировщик §92; потребители: `summary_l1_clusterizer`, `summary_generator`, `summary_test_run`, `summary_fact_package`), судьба — перенос в `services/summary_l1_clusterizer.py` без изменения сигнатуры; всё остальное ядро S2 (`restore_context`, `_walk_parents`, `_collect_neighbors`, `_index_by_tg`, `RestoreParams`, `RestoreResult`, `RESTORE_CHAIN_DEPTH` и пр.) — dead code, модуль `summary_context_restore.py` удаляется ЦЕЛИКОМ (фиктивная стадия `restore` не сохраняется — §4:2936). Отдельно зафиксировать: единственное использование `thread_chain.collect_thread_chain` в summary удаляется вместе с адаптером генератора; сам `services/thread_chain.py` НЕ трогается (memory-контур).
- **Acceptance:** классификация покрывает каждую функцию модуля (нет непокрытых); проверочный grep-критерий аудита из spec Q2: `rg "summary_context_restore|restore_context|RestoreParams|RestoreResult|RESTORE_START|RESTORE_COMPLETE|_collect_extra_parents"` по `services/` + `tests/` → 0 совпадений (кроме `plans/archive/`); `rg "build_l1_payload"` → ровно одно определение (`summary_l1_clusterizer.py`); факты для Q2 (§39:3797).

### T-3968 — Проверка `_ensure_shiz_postfix` / `_most_active_author` (для Q4)
- **Метка:** [MECH]. **Риск:** R3.
- **Суть:** найти в коде цепочку `_ensure_shiz_postfix()` → `_most_active_author()` (выбор по количеству сообщений → hardcode финальной строки «Главным шизом объявляется …»), все call-sites, включая тесты/логи, завязанные на строку (§21:3392–3402, §22:3404–3419).
- **Acceptance:** перечислены все точки определения и вызова; подтверждено отсутствие других легитимных потребителей; факты для ответа Q4 (§39:3805).

---

## Блок B — Удаление алгоритмического prefilter (§1–§5, §35)

### T-3969 — Live-путь Hybrid И Legacy без score-фильтра
- **Метка:** [ARCH Q1]. **Риск:** R2.
- **Суть:** новый путь `source messages (get_window_messages) → SOURCE_WINDOW → run_l1(rows) → pack_l1_input`: всё влезло — L1 получает ВСЁ; физическое переполнение — technical packing (`estimate_and_split` + serialized-учёт + eviction без веса) + WARN → L1 (§2:2841–2890). Удаление затрагивает ОБА контура (расхождение 3 spec §10): блок `if flags.summary_filter_enabled` в `_run` удаляется целиком, отдельная сущность `xml_rows` исчезает — **и Hybrid, и Legacy получают исходное `rows`**; Legacy получает полное окно, его prompt-бюджет/`truncate_to_tokens` и `max_summary_parts` — без изменений (контракт ADR-1027-10 (d)); вместе с префильтром удаляются `_apply_filter`/`_restore`/`_collect_extra_parents`/`_is_open_anchor`, слот `_filter_metrics` и S1-поля RunContext/SUMMARY_COMPLETE (`saved_count/restored_count/drop_percent/filter_status/filter_duration_ms`). Prefilter **удалить полностью**, не выключать по умолчанию (§2:2866, §38:3770–3771: «просто оставить выключенным» / «default true→false» не считается fix).
- **Acceptance:** в live-пути нет вызова heuristic prefilter ни для Hybrid, ни для Legacy; короткое сообщение не может быть удалено только за короткость (примеры §2:2880–2890); technical overflow protection осталась (§40:3843); `record_run_from_context(ctx, None)` толерантен, узел `algorithm` исчезает из карты вызовов (замещается событиями §36); тесты §27 (T-3987). Запрет §38: не увеличивать thresholds как «фикс».

### T-3970 — Нейтральный technical budget: переезд в существующий `summary_hybrid_budget.py`
- **Метка:** [ARCH Q1]. **Риск:** R2.
- **Суть:** нейтральный модуль = **СУЩЕСТВУЮЩИЙ `services/summary_hybrid_budget.py`** (единая точка бюджета Hybrid из ADR-1027-10 D7) — создавать третий модуль НЕ нужно (расхождение 1 spec §10, контракт (a)). Из `summary_filter.py` переезжают ТОЛЬКО технические примитивы с сохранением имён/сигнатур: `estimate_and_split(kept, *, token_limit=None, char_limit=None)`, `Fragment(index, message_ids, overlap_message_ids, reason)`, `DEFAULT_FRAGMENT_OVERLAP = 1`; строковые хелперы `_row_get/_row_id/_row_tg/_row_text/_row_ts` НЕ дублировать (`services.database.row_get` покрывает `_row_get`, однострочные обёртки остаются локальными в потребителях). `summary_l1_clusterizer` переподключает импорты на `summary_hybrid_budget`; импорты `score_message`/`_EVICTION_PARAMS` удаляются. Eviction в `pack_l1_input` становится **чисто техническим** — ключ `(reply_protected, timestamp, db_id)`: reply-защита (физическая связность reply-цепочек внутри пакета, не «важность») остаётся, весовой член `−weight_S1` удаляется; «последнее сообщение неприкосновенно» и `truncated/skipped_ids/WARN` сохраняются (ADR-1027-10 D7). Модуль решает только «как физически вместить payload», не «какие сообщения кажутся важными» (§3:2894–2906). **Не переносить `score_message()` под новым именем** (§3:2919, §38:3773, §40:3841–3842).
- **Acceptance:** `summary_hybrid_budget` не содержит score/burst/mention-эвристик ни в каком виде — только длина/токены/нарезка/бюджет (grep-инварианты (a): `rg "score_message"` по `services/` → 0; `rg "summary_filter"` по `services/` → 0); `summary_l1_clusterizer` больше не зависит от `summary_filter`; юнит-тесты на estimation/splitting/budget + порядок eviction без весового члена.

### T-3971 — Роспуск `summary_context_restore`: перенос `build_l1_payload`, удаление модуля
- **Метка:** [ARCH Q2]. **Риск:** R2.
- **Суть:** по контракту spec Q2 / ADR-1028-1 D2: `build_l1_payload(rows, chat_id)` переносится в `services/summary_l1_clusterizer.py` (реальная ответственность — §92-вход L1; там уже есть `_payload_item`, построенный на нём) с сохранением сигнатуры; все импортеры (`summary_l1_clusterizer`, `summary_generator`, `summary_test_run`, `summary_fact_package`) переподключаются. Остальное содержимое — dead code; модуль `summary_context_restore.py` **удаляется ЦЕЛИКОМ** (не «оставить с честной ответственностью» — расхождение 2 spec §10); фиктивная стадия `restore` не сохраняется (§4:2923–2936). Вместе с генератором удаляются адаптер `_collect_extra_parents`/`_is_open_anchor`, константы `RESTORE_CHAIN_DEPTH`/`RESTORE_CHAIN_CALLS_MAX` и единственное использование `thread_chain.collect_thread_chain` в summary; `services/thread_chain.py` сам НЕ трогается. Принятое поведение фиксируется в evidence: reply-родитель вне 6-часового окна больше не добирается из БД (внутри окна он присутствует — L1 получает всё; `reply_to_id` в §92-payload сохраняется) — осознанный сдвиг к «L1 понимает сам» (§2:2864).
- **Acceptance:** grep-критерий spec Q2: `rg "summary_context_restore|restore_context|RestoreParams|RestoreResult|RESTORE_START|RESTORE_COMPLETE|_collect_extra_parents"` по `services/` + `tests/` → 0 совпадений (кроме `plans/archive/`); `rg "build_l1_payload"` → ровно одно определение (`summary_l1_clusterizer.py`); full regression зелёный.

### T-3972 — Dry-run паритет (§35)
- **Метка:** [MECH] (после T-3969). **Риск:** R3.
- **Суть:** Dry-run/Test Summary использует тот же semantic input path, что production; test path не продолжает тайно запускать старую S1 filtering logic (§35:3688–3700). По контракту (j): в `build_test_rows` `_apply_filter` удаляется, возвращаемый shape сохранён для UI (`filtered = source`, `dropped = []`, `restored = []`, `filter_metrics = {}` + `source_count/filtered_count/restored_count/limit`); в `summary_test_run` L1 получает полный source (`run_l1(rows=filtered)` — packing идентичен продy); stage «filter» в отчёте переименовывается по смыслу в «window/packing» **без изменения API-ключа** `result.stages["filter"]` (UI-совместимость — API-форма dry-run сохраняется); поля `saved_count/restored_count/drop_percent` отдаются как `None`/нули; отображаются packing-счётчики L1 (`truncated/skipped`) — dry-run отражает отсутствие фильтрации (короткие сообщения присутствуют). Side effects в dry-run отключены как сегодня (0 отправок/0 image/0 памяти — публикацию, image generation, Telegram send).
- **Acceptance:** тест/инспекция подтверждают: dry-run input→L1→L2 идентичен production; grep не находит вызовов S1 в test path; API-форма ответа dry-run не изменилась (UI не ломается); результат dry-run отражает отсутствие фильтрации (короткие сообщения присутствуют).

### T-3973 — Удаление 8 настроек prefilter из Miniapp + каталога; вкладка «prep»; F8-переиздание
- **Метка:** [MECH]; **санкция отрицательного Δ каталога — УТВЕРЖДЕНА Architect (spec раздел 9, контракт (i))**.
- **Риск:** R1 (каталог/UI), R3 (миграция).
- **Суть:** удалить 8 ключей (§5:2940–2959): `flags.summary_filter_enabled`, `flags.summary_filter_reply_context_enabled`, `limits.summary_filter_min_weight`, `limits.summary_filter_min_words_for_bonus`, `limits.summary_filter_burst_window_seconds`, `limits.summary_filter_min_burst_density`, `limits.summary_filter_context_neighbors`, `limits.summary_filter_context_max_messages` (registrations `param_catalog.py:1206–1216` + два флага группы `flags_summary_filter`) и 2 группы `flags_summary_filter` (`:368`)/`limits_summary_filter` (`:303`); из `TAB_RULES` (TAB_MOD_SUMMARY, `param_catalog.py:2289–2292`) frozenset-члены `flags_summary_filter`/`limits_summary_filter` убираются **in-place** (счётчик TAB_RULES не меняется). **Frontend-часть в объёме этой задачи (расхождение 4 spec §10):** вкладка **«Подготовка сообщений» удаляется** — `WORKSPACE_TABS.mod_summary` теряет `'prep'` (`app.js:584`), `workspaceGroupTab` (`app.js:6312–6313`) теряет маппинг filter-групп, label `'prep'` удаляется (`app.js:613`); после удаления групп вкладка неприменима (`_workspaceTabApplicable`) — мёртвых тумблеров нет (§5:2963); вкладки `clusterizer`/`writer` остаются вне этого решения. **F8-счётчики (контракт (i)):** REGISTRY **489 → 481** (−8 keys `summary_filter_*`), GROUPS **107 → 105** (−2 группы), `_TAB_BY_GROUP` **105 → 103**, TAB_RULES **21** (in-place). **Контент-дифф, не количество (расхождение 12 spec §10):** `title_ru` 6 промпт-ключей → §9-формулировки («Кластеризатор (L1)», «Писатель статьи (L2)», «Стиль обложки», «Legacy Single-call», «Legacy Editor», «Legacy Narrator/Рассказчик») + описания «Legacy fallback, не основной Hybrid writer» для №3–5; Δ количества от этого = 0, фиксируется в F8-диффе. Старые значения в БД миграции НЕ подлежат: строки `summary_filter_*` в `bot_settings` и `chat_params.overrides` остаются и безопасно игнорируются (`hot_config._coerce` возвращает raw-значение без spec), startup не валидирует каталог против БД — не ломается (§5:2965). F8-переиздание одним атомарным коммитом (код+каталог+тесты): `plans/docs/param-registry-round1025.meta.md` (счётчики + APP_VERSION 2.58.34), `param-registry-round1025.tsv`, `plans/reports/round1025_f8_config_diff.md`, маркер-тесты (`tests/fixtures/round1025/catalog_baseline.json`, `test_round1025_f8_registry`).
- **Acceptance:** ни один из 8 ключей не виден/не действует в UI; вкладки `'prep'` нет в workspace mod_summary; тест startup + полный прогон с «грязной» БД (pre-seeded старые `summary_filter_*`) зелёный; счётчики каталога = 481/105/103/21, Δ отрицательный и контент-дифф 6 титулов задокументированы в F8-evidence. Запрет §38: «только спрятать UI toggle» не считается fix — удаление полное.

---

## Блок C — Rich cut + emphasis formatting (§1, §18–§20)

### T-3974 — Детерминированный Rich cut (`<details>` в format_rich_html)
- **Метка:** [ARCH Q5]. **Риск:** R1 (живая доставка).
- **Суть:** механизм зафиксирован spec Q5 / ADR-1028-1 D4: **`<details><summary>Читать дальше</summary>` в `format_rich_html`** (единственная точка сборки rich-HTML; native `blocks`-эквивалент отклонён — минимальный дифф; aiogram 3.31.0 поддерживает, `sanitize_outgoing` тег не трогает — прецедент `<h1>/<p>/<b>`). Порядок: `[img cover]` → `<h1>title</h1>` → `<p>` абзац 1 → при **len(абзацев) > 1**: ОДИН закрытый `<details>` (атрибут `open` НЕ ставится) с `<p>2..N</p>` + finale-блоком внутри; summary-текст константен (`Читать дальше`), детерминирован, экранируется; **1 абзац (или 0) → ката нет, `details` не эмитится**, finale — видимый концевой блок (Q4). Cut — presentation layer: документ не меняется, L2 не видит cut; plain-каналы (`format_plain_html`, `chunk_plain_blocks`, `format_plain_text`) отдают **ПОЛНЫЙ** текст без ката; `rich_document_limits` без структурных правок (~50–60 симв. обёртки внутри headroom 32000; семантика fail-closed `too_long`/overflow→plain сохранена). Не полагаться на эвристику Telegram-клиента (§1:2824, §38:3776).
- **Acceptance:** cut — только presentation layer: не обрезает статью, не удаляет последние абзацы, не влияет на L2 и на plain fallback (§1:2828–2835); при падении RichMessage обычный `sendMessage` получает **ПОЛНЫЙ** текст (§1:2837); тесты §28 (T-3988); Reviewer: >1 paragraph всегда получает deterministic cut, cut не теряет body, plain fallback содержит полный текст (§40:3845–3847).

### T-3975 — §99 v1.1: `emphasis_spans` в structured L2 document
- **Метка:** [ARCH Q3]. **Риск:** R2.
- **Суть:** stable formatting контрактом, а не случайным Markdown от модели (§18:3317–3331). Имя поля зафиксировано spec Q3 / ADR-1028-1 D3: **`emphasis_spans`** — опциональный массив объектов `{text: str, kind: str}`, `kind ∈ {"person","event"}`; `PARAGRAPH_FIELDS := {"text", "emphasis", "emphasis_spans"}`; `schema_version` остаётся **1** — аддитивно, backward-compatible (расхождение 5 spec §10). Детерминированная канонизация в `_validate`: (1) текст абзаца проходит `cleanup_llm_text` (T-3978) ДО substring-проверки; спаны чистятся той же картой замен; (2) span валиден ⟺ `text` — непустая точная подстрока финального текста абзаца, len ≤ `PARAGRAPH_MAX`, без тегоподобных конструкций (`</?[A-Za-z]`); (3) invalid span **молча игнорируется** (счётчик `emphasis_dropped_count`, документ валиден); (4) overlap детерминирован: позиции = первое вхождение; сортировка `(start ASC, length DESC, порядок_в_JSON ASC)`; жадный приём без пересечений; дедуп по `text`; (5) **кап ≤4 принятых span'ов на абзац** (анти «жирная каша», §18:3330) — излишек отбрасывается со счётчиком; (6) legacy `emphasis` (строка) = кандидат-span «первым в очереди» — документы прежнего канона рендерятся как сегодня; (7) канонический вывод абзаца: `{"text", "emphasis": <первый принятый span | null>, "emphasis_spans": [..]}` — **derived-поле `emphasis` сохраняется** для совместимости читателей/legacy-документов; рендер — по `emphasis_spans`, при пустом списке — по `emphasis`. Прочие `kind` не бракуют документ (рендер одинаковый — bold), но пишутся в счётчик. Raw HTML от L2 не проходит как разметка структурно (sanitize → escape; тегоподобные спаны отбрасываются п.2). Документы без новых полей валидны (старые записи/`document_from_plain_text` не меняются).
- **Acceptance:** backward-совместимость: документы без новых полей валидны; юнит-тесты: множественные spans, invalid→ignored со счётчиком, overlap→детерминированный результат, кап 4 (5-й отброшен, счётчик), derived-`emphasis` = первый принятый span, HTML от L2 не проходит; форматирование детерминировано (DoD-10, §41:3877).

### T-3976 — Formatter → RichMessage bold (по `emphasis_spans`) + plain fallback
- **Метка:** [ARCH Q3] → механическая после утверждения схемы. **Риск:** R1.
- **Суть:** formatter переходит от `partition`-одиночки (единственный `emphasis`) к **секвенциальному рендеру принятых span'ов** — walk по тексту, `<b>` вокруг каждого принятого span'а, всё экранируется (`sanitize_outgoing → html.escape`), один и тот же код для rich (`<p>`) и plain-HTML (`<b>title</b>`-блоки) (§19:3371): имена участников и ключевые события/повороты — bold, без «жирной каши» (§18:3326–3330). При пустом списке span'ов рендер идёт по legacy `emphasis` (совместимость). Последний raw-text fallback (`format_plain_text`) рендерит текст без markup — span'ы не теряются как текст, весь текст сохраняется (§20:3375–3388).
- **Acceptance:** тест §29: все три span («Никита»/«новую схему»/«Лёха») bold в Rich; invalid span не ломает публикацию; fallback-тесты: HTML fallback сохраняет bold, raw fallback сохраняет полный текст без markup; нет случайных `**` артефактов (§43:3937–3941).

---

## Блок D — L2-стиль, structured finale, prompt migration (§15–§17, §21–§26)

### T-3977 — Prompt-обновления Hybrid L2: грамматика + двачерский голос + typography
- **Метка:** [ARCH Q10] (целевой prompt и его effective source определяются T-3964/T-3965; правка — через migration contract T-3980). **Риск:** R2 (риск stale PG override — §11:3150, §17:3309).
- **Суть:** в effective Hybrid L2 prompt: нормальная русская грамматика, предложения с заглавной, нормальная пунктуация/структура абзацев/оформление имён, никаких случайных lowercase starts (§15:3239–3262) — при этом Direct Chat стиль НЕ меняется и его random lowercase НЕ переносится в Summary (§15:3249, §38:3780); двачерский характер сохранён: сарказм, иронию, сленг, двачерские обороты, естественный мат — целевая смысловая инструкция §16:3288; typography policy (без ёлочек/длинного тире — §17:3292–3311). Обязательно: аудит shared style blocks — Direct Chat instructions случайно не попадают в L2 (§15:3262). Если в effective prompt есть запрет «никакого сленга» — исправить (§16:3280–3284).
- **Acceptance:** effective (после миграции) L2 prompt содержит требуемые инструкции — проверяется через `L2_START effective_prompt_key` (T-3986) и T-3965; тест §30 (T-3989); Reviewer: грамматика нормальная, голос/сленг/мат сохранены, Direct Chat style не изменён (§40:3854–3856). Запреты §38: не запрещать весь сленг и мат; не переносить random lowercase в Summary.

### T-3978 — Deterministic typography normalizer: переиспользование `cleanup_llm_text` на Hybrid L2-канонизации
- **Метка:** [ARCH Q10] → **РЕШЕНО Architect** (spec контракт (d), санкция раздела 9): normalizer **НУЖЕН**, prompt-only признан недостаточным; статус «опциональный» снят (расхождение 6 spec §10). **Риск:** R2.
- **Суть:** применяется **существующий** `cleanup_llm_text` (`services/summary_cleanup.py`; ровно 6 замен символов оформления: `«»„“ → "`, `—– → -`, + strip reasoning-тегов; идемпотентен, содержание не трогает; сегодня применяется к Legacy `summary_generator.py:716` и factcheck/checkup R33-7, а Hybrid-путь его НЕ применяет вовсе — это и есть нестабильность §17:3303) к `title`/`paragraphs[].text`/`finale` в детерминированной канонизации `_validate` (`summary_l2_writer.py`) ДО substring-проверки спанов; спаны чистятся той же картой замен (Q3 п.1). **Kill-switch/env НЕ вводится** (Δ каталога = 0; конвенция R33-7 — безусловно на этом контуре). Prompt-инструкции (без ёлочек/длинного тире) остаются первой линией в каноне L2 — normalizer даёт гарантию (§17:3311).
- **Acceptance:** идемпотентность; тест-инвариант «содержание не изменено» (посимвольное сравнение вне разрешённых замен); substring-проверка `emphasis_spans` выполняется после cleanup; объём: 1 точка вызова + тесты-инварианты.

### T-3979 — «Главный шиз» выбирает LLM; structured `finale`; удаление алгоритмического выбора
- **Метка:** [ARCH Q4]. **Риск:** R2.
- **Суть:** удалить из responsibility кода `_ensure_shiz_postfix` (`:1870–1880`), `_most_active_author` (`:1882–1896`), **`_SHIZ_AT_RE`** и вызов `:729` (§22:3404–3419; запрет §38:3778 «сохранить _most_active_author»; деталь контракта (e), расхождение 7 spec §10). **`_SHIZ_MARKER`-strip в `_derive_fallback_cover_prompt` (`:2033`) СОХРАНЯЕТСЯ** — защита: модель может написать шутку в тексте, в visual-промпт обложки она попасть не должна. Шутка остаётся как **творческое решение LLM** (§21:3392–3402, §23:3421–3436: semantic/tone decision, не статистика message count). Structured finale: top-level опциональное поле L2-документа `finale: str` (§24:3440–3452; `TOP_LEVEL_FIELDS += {"finale"}`); валидация в `_validate` детерминирована: строка, одна строка, после `cleanup_llm_text`+strip 1..200 симв.; невалидное/отсутствующее → canonical без `finale`, `metrics["finale_present"]=0`; code валидирует/экранирует/отображает, **НЕ выбирает winner**, без `_most_active_author()` fallback (§24:3454–3466). Отображение: formatter выводит `finale` последним блоком — в rich **внутри cut**, если cut применён (всё после 1-го абзаца под одним cat'ом, §1:2813); при 0–1 абзацах — видимой концевой строкой; в plain-HTML/plain-text — последним блоком (полный текст сохраняется, §20). Грамматика строки — за LLM.
- **Acceptance:** тест §31 (T-3989): User A=30 сообщений, User B=5, абсурдный эпизод у B → code не подставляет A, winner из LLM output; grep: `_most_active_author`/`_ensure_shiz_postfix`/`_SHIZ_AT_RE` отсутствуют в live/fallback-путях, `_SHIZ_MARKER` остался только как strip-константа в `_derive_fallback_cover_prompt`; тесты shiz-блока `test_summary_generator.py` и маркер `test_summary_deploy_round1026.py:619` переписаны на инвариант «code не выбирает winner»; Reviewer: code больше не выбирает «главного шиза» (§40:3859); Legacy-путь отдаёт выбор модели — код не дописывает поверх (§25:3470–3478, инструкция входит в миграцию T-3980).

### T-3980 — Prompt migration contract (§26): L2 + Narrator + Legacy Single
- **Метка:** [ARCH Q10]. **Риск:** R2 (данные PG).
- **Суть:** изменяемые каноны зафиксированы контрактом (g), расхождение 8 spec §10: **L2 writer** (грамматика §15 + двачерский голос §16 + typography §17 + инструкция `emphasis_spans`/`finale` §18–19 + запрет HTML/`**`), **Legacy Narrator** И **Legacy Single** (инструкция §21/§25 — «шиза» выбирает модель, строка опциональна; §25 говорит «Narrator / Single-call» — входят ОБА, не только Narrator). **L1-канон НЕ меняется** (L1 не пишет текст, §7:3062–3066); `summary_cover_style` — без миграций (только UI, §26:3495). Шаги по механике ADR-1013-3 (`services/prompt_migrations.py`): текущие базы → байт-в-байт слепки **`PREV_SUMMARY_L2_WRITER_R1028` / `PREV_SUMMARY_NARRATOR_R1028` / `PREV_SUMMARY_SYSTEM_R1028`**; новые базы `_..._R1028_BASE`; `PROMPT_MIGRATIONS` += ступени (canonical-old → canonical-new); `PROMPT_ROLLBACK` += обратные; **genuinely-custom пользовательские prompts не перезаписывать молча** — миграция матчит только точные канон-тексты (существующая семантика `prompt_migrations.py:102–182`, §26:3482–3488). Канон-эталон `plans/docs/canon/` обновляется атомарно с кодом и тестами.
- **Acceptance:** миграционные тесты: (а) canonical-old → canonical-new; (б) genuinely-custom → не тронут; (в) ключ отсутствует → code default; ROLLBACK-миграция на `PREV_*_R1028` возвращает прежний текст без рестарта кода (проверка); канон-эталон в `plans/docs/canon/` обновлён атомарно с кодом и тестами.

---

## Блок E — Prompt Library frontend (§6, §9–§14, §34)

### T-3981 — Desktop Prompt Library: все 6 открываются и редактируются
- **Метка:** [ARCH Q6]. **Риск:** R1 (редактирование конфига из UI).
- **Суть:** фикс-план (f) spec, расхождение 9 (правки только в app.js/index.html/app.css; backend конфиг-API и `web/api/routes.py` НЕ трогаются — расхождение 9): в `app.js openWorkspacePrompt` (`:6245–6268`) цепочка построения URL становится `seg = stage || item.stage || ''` — залипший `ws.stage` убирается (сегодня он имеет приоритет над stage item'а и создаёт битые URL `…/verbalizer/<чужой-ключ>`); в `workspacePromptFocus` (`:2146–2159`) — фолбэк на полный список модуля при ненайденном ключе в непустом stage-списке; ключ не найден нигде → `null` + stale-guard T-3982. Каждый пункт списка открывает соответствующий editor: Hybrid L1, Hybrid L2, Cover Style, Legacy Single, Legacy Editor, Legacy Narrator (§12:3175–3192). Никакого пустого editor; никаких «выглядит кликабельно, но ничего не происходит».
- **Acceptance:** тест §32 (T-3990) + сценарии B2/B3 spec раздела 5 (регресс Q6: Narrator → клик «Кластеризатор (L1)» переключается корректно; на save — ровно 1 POST /api/config): для каждого из 6 — open → edit → save → reload → value persisted; Reviewer: desktop prompts все открываются (§40:3850).

### T-3982 — Mobile Prompt Library: flow + stale promptKey guard + явный back
- **Метка:** [ARCH Q7]. **Риск:** R1.
- **Суть:** нормальный flow «список prompts → выбрать → editor → save → назад к списку» (§13:3196–3204); нет состояния «prompts не открываются / список исчез / виден только Анти-клише». Механика по Q7/(f): сегодня `is-editing` навешивается по факту существования строки `promptKey` (`index.html:742`), а CSS ≤767px (`app.css:2568–2575`) при этом скрывает дерево — **stale-guard**: `is-editing` и скрытие дерева привязать к `workspacePromptFocus` (валидно найденный item), не к сырому `promptKey`; invalid/stale ключ → режим списка + redirect на канонический `#/ai/prompts/<slug>` (§13:3212–3219); **явная кнопка «← К списку»** в editor-состоянии (navigate `#/ai/prompts/<slug>`) — flow §13:3199 без браузерного back. Mobile CSS: без `display:none` дерева при invalid ключе; тач-цели ≥44px сохраняются. Backend конфиг-API и `web/api/routes.py` НЕ трогаются (расхождение 9).
- **Acceptance:** тест §33 (T-3991, browser verification **обязателен**) + сценарии B4/B5 spec раздела 5: список виден, L1/L2/Cover/Legacy открываются, Save работает, Back («← К списку») работает, invalid/stale route не создаёт пустой editor, анти-клише не блокирует; Reviewer: mobile prompts все открываются (§40:3851).

### T-3983 — Анти-клише отдельной секцией
- **Метка:** [MECH]. **Риск:** R3.
- **Суть:** существующий anti-cliche feature остаётся, но не занимает место prompt editor, не скрывает prompt list, не является единственным видимым блоком на mobile; prompt editor — основная часть страницы, анти-клише — отдельная вспомогательная section (§14:3223–3235). Механика по (f) п.5 / Q7 п.3: блок монитора переносится **ниже** промпт-контента и сворачивается в `<details>` по умолчанию; V2-раскладка не меняется по механике сохранения; editor доступен при открытом/свёрнутом блоке; на mobile блок перестаёт быть первым экраном.
- **Acceptance:** layout desktop+mobile: editor доступен при открытом/свёрнутом блоке анти-клише; тест §33 покрывает «anti-cliche не блокирует editor» (сценарии B4/B6: скриншоты обязательны как layout-факт).

### T-3984 — Ре-структура PL по §9 + metadata-панель §10 + подписи ролей
- **Метка:** [ARCH Q9] (по факту аудита T-3964 и Q9-карте spec; **ключевых дублей нет** — все шесть ключей ведут к разным runtime-стадиям, объединять запрещено §8:3046; реальная проблема — ложная лексика стадий). **Риск:** R1.
- **Суть:** группировка и бейджи — **presentation-слой**: статическая карта `SUMMARY_PROMPT_META` в app.js по 6 ключам → {pipeline, stage_label, runtime, group} (прецедент MEMORY_SUBGROUPS — витрина без Δ каталога; один config key = один source of truth сохраняется). Группы: **Hybrid Summary** — «Кластеризатор (L1)» (описание: структурирует сообщения в темы и факты, не пишет пользовательский текст) и «Писатель статьи (L2)» с бейджем **«АКТИВНЫЙ HYBRID OUTPUT»**; **Обложка** — «Стиль обложки» (advanced-аккордеон для этой карточки в списке §9 НЕ применяется — ключ виден сразу, §9:3093–3104); **Legacy Summary Fallback** — Legacy Single / Legacy Editor / Legacy Narrator с явной пометкой «Legacy fallback, не основной Hybrid writer» (§9:3122); каталоговые `stage='synthesizer'/'verbalizer'` на Hybrid L1/L2 не переименовываются — ложная лексика снимается подписью витрины. Metadata-панель в editor: `Pipeline / Stage / Runtime / Key / Source` (§10:3126–3138); **честный Source (chat override / global / code default) появляется только после решения (h) по T-3965** — до этого Source из существующего `configSourceLabel` (расхождение 9 spec §10). Backend конфиг-API и `web/api/routes.py` НЕ трогаются.
- **Acceptance:** структура соответствует §9 с поправкой на факты T-3964 (Q9); каждая карточка/editor показывает metadata §10; Reviewer: PL правильно показывает runtime roles (§40:3849), L2 Writer действительно помечен как текущий Hybrid output prompt (§40:3848).

### T-3985 — Cover Style: open/edit/save/reload (frontend-only)
- **Метка:** [ARCH Q8]. **Риск:** R1.
- **Суть:** причина зафиксирована Q8: `summary_cover_style` имеет `stage=None` (`param_catalog.py:460–463`), при залипшем `ws.stage` URL `…/verbalizer/prompts.summary_cover_style` не резолвится в фокус → пустое состояние; чинится теми же правками (f), что Q6 (перестают строиться битые URL + фолбэк поиска). Поле `Стиль обложки` (`prompts.summary_cover_style`) реально открывается, текущее значение видно, изменяется, Save работает, reload сохраняет значение (§6:2983–2985, §9:3088–3104, §34:3673–3682); в структуре §9 у карточки явная группа «Обложка» и description; advanced-аккордеон не применяется (§9:3093–3104). Проверяемый mismatch key→runtime отсутствует: runtime-ключ совпадает с UI-ключом, per-chat резолв уже реализован (`_resolve_cover_style_text`, `:2069–2090`). Backend image generation и `web/api/routes.py` **не трогать** — он работает (§34:3684, расхождение 9).
- **Acceptance:** тест §32 (desktop) + §33 (mobile) строки Cover Style + live §44; Reviewer: Cover Style editor открывается, save/reload работает (§40:3852–3853); cover backend продолжает работать без регрессии (DoD-20). Запреты §38: не считать Cover Style исправленным без mobile проверки; не превращать в переработку image pipeline.

---

## Блок F — Observability (§36)

### T-3986 — События успешного Hybrid run
- **Метка:** [MECH] (после T-3969/T-3970/T-3974/T-3975 — фиксирует фактические поля нового пути). **Риск:** R3.
- **Суть:** читаемая последовательность §36:3704–3744, состав полей — раздел 4 spec (расхождение 10): `SUMMARY_START` → **`SOURCE_WINDOW`** (НОВОЕ, INFO, в `_run` после чтения окна; поля: run_id, chat_id, messages=source_count — первое событие после `SUMMARY_START`) → `L1_CONTEXT_PACK` (НОВОЕ, INFO, в `run_l1` после `pack_l1_input`; поля: run_id, chat_id, source_messages, packed_messages, serialized_tokens, physical_budget, overflow (0/1=truncated), skipped, kind(tokens/chars)) → `L1_START` → `FACT_PACKAGE` → `L2_START` (`effective_prompt_key=` + **`prompt_source=` (chat/global/default)**; response_mode/target_* сохраняются) → `L2_COMPLETE` (`paragraphs=`, **`emphasis_spans=` (принято шт.)**, **`emphasis_dropped=`**, **`finale_present=`**; chars сохраняются) → `FORMAT` (FORMAT_COMPLETE channel=rich: `rich_cut=`, `visible_paragraphs=`, `collapsed_paragraphs=`; channel=plain: `rich_cut=0`, visible=all) → `COVER` → `PUBLISH_RICH` → `SUMMARY_DONE`. Старые события `FILTER_START/FILTER_COMPLETE/FILTER_EMPTY_FALLBACK/FILTER_ERROR/RESTORE_*` **удаляются вместе с S1/S2** (замещаются `SOURCE_WINDOW`/`L1_CONTEXT_PACK`); `SUMMARY_COMPLETE` теряет S1-поля `saved_count/restored_count/drop_percent` (fallback=/publication_status= сохраняются). События аддитивны, имена зафиксированных событий не переименовываются; R17: только числа/коды/id, **raw messages/тексты/приватные промпты — никогда** (§36:3744). Сопутствующие правки наблюдаемости: JS log-viewer фильтр «Саммари» — префикс-правило покрывает `SOURCE_WINDOW`/`L1_CONTEXT_PACK` (Δ каталога = 0); JS-харнесс `tests/js/round1026_s7_log_summary_filter_test.js` переписывается под новые события; `test_summary_logging_runid.py` обновляется (новые поля, отсутствие FILTER_*).
- **Acceptance:** интеграционный тест успешного прогона фиксирует полную последовательность и поля (включая новые `SOURCE_WINDOW`/`L1_CONTEXT_PACK` и отсутствие FILTER_*/RESTORE_*); в событиях нет текста сообщений; `effective_prompt_key`/`prompt_source` позволяют проверить T-3977 в проде (DoD-21); JS-харнесс и log-viewer-тесты зелёные.

---

## Блок G — Тесты (§27–§33) + регресс

### T-3987 — Тесты удаления prefilter (§27)
- **Метка:** [MECH]. **Риск:** R3. **Покрывает:** DoD-1/3/4.
- **Acceptance (4 сценария §27:3499–3537):** (1) «у кота рак» (короткое, no reply/mention/burst) доходит до L1; (2) «Леха уехал» доходит до L1; (3) 500 сообщений, помещаются в budget → все доступны L1; (4) physical overflow → technical packing + явный лог + никакого старого heuristic `score_message`.

### T-3988 — Тесты Rich cut (§28)
- **Метка:** [MECH]. **Риск:** R3. **Покрывает:** DoD-5/6/7.
- **Acceptance (§28:3541–3570):** (1) один body paragraph → title + paragraph, без искусственного ката; (2) два абзаца → p1 виден, p2 внутри закрытого cut; (3) много абзацев → p1 виден, paragraphs 2..N внутри ОДНОГО закрытого cut, ничего не потеряно; (4) rich failure → plain fallback содержит ВСЮ статью.

### T-3989 — Тесты emphasis + style + finale (§29–§31)
- **Метка:** [MECH]. **Риск:** R3. **Покрывает:** DoD-8/9/10/11/12/13/14/15.
- **Acceptance:** §29:3592–3590 — абзац «Никита предложил новую схему, после чего Лёха её разъебал.»: все три span'а bold в Rich, invalid span не ломает публикацию. §30:3594–3608 — Hybrid L2 output: нормальные заглавные/грамматика/пунктуация, нет random lowercase, сленг/мат/сарказм допустимы, нет корпоративного sterile tone, typography policy соблюдена. §31:3612–3624 — fixture A=30/B=5 сообщений, абсурд у B: code НЕ выбирает A, winner приходит из LLM output.

### T-3990 — Тесты Prompt Library desktop (§32)
- **Метка:** [MECH]. **Риск:** R3. **Покрывает:** DoD-16/17/19.
- **Acceptance (§32:3628–3645 + сценарии B1–B3 spec раздела 5):** для каждого из 6 (Hybrid L1, Hybrid L2, Cover Style, Legacy Single, Legacy Editor, Legacy Narrator): open → edit → save → reload → value persisted; клик по каждому → editor с непустым textarea, корректным Key и metadata-панелью; регресс Narrator → L1 (B2); на save ровно 1 POST /api/config.

### T-3991 — Тесты Prompt Library mobile (§33) — browser REQUIRED
- **Метка:** [MECH]. **Риск:** R3. **Покрывает:** DoD-18/19.
- **Acceptance (§33:3649–3663 + сценарии B4–B7 spec раздела 5, browser verification обязателен):** на mobile viewport 390×844: список prompt'ов виден; L1/L2/Cover Style/Legacy открываются; Save работает; Back («← К списку») работает; stale-комбинация `#/ai/prompts/summary/verbalizer/prompts.summary_cover_style` не создаёт пустой editor (B5); анти-клише разворачивается/сворачивается без перекрытия (B6); console чистый на всех шагах (B7); скриншоты B4/B6 обязательны как layout-факт.

### T-3992 — Полный регресс
- **Метка:** [MECH]. **Риск:** R3. **Покрывает:** DoD-22.
- **Acceptance:** полный pytest 0 failed + JS-тесты (правило проекта: полный прогон перед каждым коммитом); обновлённые маркер-тесты каталога после F8 (T-3973); тесты T-3987–T-3991 входят в общий прогон; фактический Δ DDL зафиксирован (ожидание: 0 schema-DDL; изменения только в данных/настройках — если появятся, требуют санкции spec и идемпотентной миграции по политике DDL project.md).

---

## Блок H — Релиз: bump, прод-деплой, live acceptance, gate, архив

### T-3993 — APP_VERSION bump 2.58.33 → 2.58.34
- **Метка:** [MECH]. **Риск:** R3.
- **Суть:** bump по конвенции проекта (сверка git log: каждая фича раунда = один patch-бамп; текущий прод 2.58.33 = ASAP-2). Финальный аудит перед деплоем: Δ каталога отрицательный и переиздан (T-3973: счётчики 481/105/103/21 + контент-дифф 6 титулов промптов по §9 — расхождение 12), миграция настроек идемпотентна (данные не удаляются), R17-проверка диффа на секреты.
- **Acceptance:** `APP_VERSION = "2.58.34"`; ChangeLog-комментарий по домову стилю; предрелизный чек-лист пройден.

### T-3994 — Прод-деплой (§42) — после Reviewer Approved
- **Метка:** [MECH]. **Риск:** R1 (прод).
- **Суть:** ASAP-2.1 НЕ считается завершённым после merge/commit (§42:3895). Шаги §42:3897–3908: (1) preflight; (2) checkpoint (тег/бэкап по конвенции, прежние бэкапы/теги не удалять — R18); (3) version bump; (4) deploy в production; (5) health; (6) logs; (7–9) live acceptance (T-3995/T-3996); (10) deployment evidence. До успешного deploy фича остаётся ACTIVE (§42:3910).
- **Acceptance:** `/api/health` 200; на проде 2.58.34; systemd active; evidence сохранён в deployment-документе фичи.
- **Откат (spec раздел 7):** это фича-удаление БЕЗ hot-ключа — hot-отката нет, «оставить выключенным» запрещено владельцем (§38:3770–3771). **Откат = cold git-revert feat-коммита до 2.58.33**: сирота-значения `summary_filter_*` в БД снова подхватываются старым кодом — обратимо, т.к. **БД-данные не удаляются**; промпты — ROLLBACK-миграция на `PREV_*_R1028` без рестарта кода; Rich cut/emphasis/finale — revert (персистенции нет, plain fallback инвариантен); каталог — revert + повторное F8-переиздание (процедура документирована); UI PL — revert frontend-коммита (CSP/zero-build сохраняются). Промежуточная защита без отката: аварийные режимы `flags.summary_legacy_fallback_enabled`/`flags.summary_hybrid_l2_enabled` (ADR-1027-10) остаются.

### T-3995 — Live acceptance Summary (§43)
- **Метка:** [MECH]. **Риск:** R1. **Gate-компонент:** `LIVE SUMMARY SUCCESS`.
- **Acceptance (§43:3914–3946) — реальный Summary в прод-чате PERMsoc:** содержимое: реальные имена присутствуют; статья не обрывок; нет потерянных коротких фактов; нормальная грамматика/начала предложений; двачерский голос сохранился; сленг/мат не запрещены искусственно. RichMessage: обложка работает; title работает; первый paragraph виден; остальные под **одним** cut; cut раскрывается; полный body сохранён. Formatting: имена bold; ключевые события bold; нет случайных `**` артефактов. Finale: «главный шиз» выбран моделью; code не подставил самого активного участника.

### T-3996 — Live acceptance Prompt Library (§44)
- **Метка:** [MECH]. **Риск:** R1. **Gate-компоненты:** `DESKTOP PROMPT UI SUCCESS` + `MOBILE PROMPT UI SUCCESS`.
- **Acceptance (§44:3950–3979):** desktop — открыть все 6 editor'ов; каждый реально отображается; test value → save → reload → saved value остаётся; после теста вернуть production value. Mobile — тот же список; состояние «виден только Anti-cliche, prompts открыть нельзя» недопустимо.

### T-3997 — Post-deploy log check (§45)
- **Метка:** [MECH]. **Риск:** R3. **Gate-компонент:** `POST-DEPLOY LOG CHECK SUCCESS`.
- **Acceptance (§45:3983–3994):** нет filter-induced empty Summary; нет нового L1/L2 error spike; rich details не вызывают массовый fallback; full article не теряется; cover продолжает генерироваться; Prompt Library не создаёт JS errors; prompt saves не падают; mobile routing работает.

### T-3998 — Acceptance gate §46 → reconcile → архивация → metrics → ASAP-3
- **Метка:** [MECH]. **Риск:** R3.
- **Суть:** фича становится `DONE` только при всех шести компонентах §46:3998–4026: `REVIEWER APPROVED` + `PROD DEPLOY SUCCESS` + `LIVE SUMMARY SUCCESS` + `DESKTOP PROMPT UI SUCCESS` + `MOBILE PROMPT UI SUCCESS` + `POST-DEPLOY LOG CHECK SUCCESS`; любой непройденный пункт → фича остаётся ACTIVE. Затем: reconcile @Architect → архивация COMPLETE-папки фичи в `plans/archive/` (стабильные ID, ссылки разрешены) → metrics-данные для @Orchestrator/@Memory (фактические timestamps старта/финиша, число Reviewer-раундов, findings обеих линз, evidence-ссылки) → запись `ASAP-2.1 production acceptance complete` → следующий `active_feature = ASAP-3` (§47:4030–4044; к обычным MCA-волнам не возвращаться).
- **Acceptance:** gate-чеклист из 6 компонентов с evidence-ссылками; архив+metrics выполнены только после VERIFIED (не по чекбоксам Builder).

---

## Traceability-матрица: DoD §41 (1–22) → задачи/тесты

| DoD | Требование (§41:3868–3889) | Источник (ASAP-2.1 §) | Задачи | Тесты | Состояние |
|---|---|---|---|---|---|
| 1 | Prefilter удалён из live Summary pipeline | §2, §38 | T-3969, T-3970 | T-3987 | planned `[ARCH Q1]` |
| 2 | Filter controls удалены из Miniapp | §5 | T-3973 | T-3987 (startup-тест в рамках), T-3992; B-сценарии (нет prep-вкладки) | planned |
| 3 | Technical L1 packing независим от heuristic scoring | §3 | T-3970 (T-3966) | T-3987 (сценарий 4) | planned `[ARCH Q1]` |
| 4 | Короткие важные сообщения не отбрасываются до L1 | §2 | T-3969 | T-3987 (сцен. 1–2) | planned `[ARCH Q1]` |
| 5 | >1 абзац → cut после первого | §1 | T-3974 | T-3988 (сцен. 2–3) | planned `[ARCH Q5]` |
| 6 | Collapsed body никогда не теряется | §1 | T-3974 | T-3988 (сцен. 3–4) | planned `[ARCH Q5]` |
| 7 | Plain fallback сохраняет полный текст | §1, §20 | T-3974, T-3976 | T-3988 (сцен. 4) | planned |
| 8 | Имена могут выделяться bold | §18–§19 | T-3975, T-3976 | T-3989 (§29) | planned `[ARCH Q3]` |
| 9 | Ключевые события могут выделяться bold | §18–§19 | T-3975, T-3976 | T-3989 (§29) | planned `[ARCH Q3]` |
| 10 | Formatting deterministic, не случайный Markdown | §19, §38 | T-3975, T-3976 | T-3989 | planned `[ARCH Q3]` |
| 11 | Нормальная грамматика/capitalization | §15 | T-3977 | T-3989 (§30) | planned `[ARCH Q10]` |
| 12 | Двачерский голос, сленг и мат сохранены | §16 | T-3977 | T-3989 (§30) | planned `[ARCH Q10]` |
| 13 | Не наследует random lowercase Direct style | §15 | T-3977 | T-3989 (§30) | planned `[ARCH Q10]` |
| 14 | «Главного шиза» выбирает LLM | §21–§24 | T-3979 | T-3989 (§31) | planned `[ARCH Q4]` |
| 15 | Code не выбирает winner по message count | §22, §24 | T-3979 | T-3989 (§31) | planned `[ARCH Q4]` |
| 16 | PL ясно разделяет реальные runtime-роли | §7–§10 | T-3984 (вход T-3964/T-3965) | T-3990, T-3991 | planned `[ARCH Q9]` |
| 17 | Все Summary prompts открываются на desktop | §12 | T-3981 | T-3990 | planned `[ARCH Q6]` |
| 18 | Все Summary prompts открываются на mobile | §13 | T-3982 | T-3991 | planned `[ARCH Q7]` |
| 19 | «Стиль обложки» открывается и редактируется | §6, §9, §34 | T-3985 | T-3990, T-3991, live T-3996 | planned `[ARCH Q8]` |
| 20 | Cover backend работает без регрессии | §34 | T-3985 (ограничение), T-3992 | live T-3995 (обложка), T-3997 | planned |
| 21 | Effective runtime Hybrid L2 prompt установлен и проверен | §11, §16, §26 | T-3965, T-3977, T-3980, T-3986 (+ условный (h) по факту per-chat mismatch) | prompt-map-audit.md + live T-3995 + лог `effective_prompt_key`/`prompt_source` | planned `[ARCH Q10]` |
| 22 | Unit/integration/browser tests green | §27–§33 | T-3987–T-3992 | — (сами тесты) | planned |

**Дополнительно (не DoD, но binding):** §42 прод-деплой обязателен (T-3994, откат — cold git-revert, см. T-3994); §46 gate из 6 компонентов (T-3998); §35 dry-run паритет (T-3972, контракт (j)); §36 observability (T-3986, состав полей — раздел 4 spec); §43–§45 live acceptance (T-3995–T-3997).

## Карта инвариантов §40 Reviewer (20 пунктов) → чек-лист Reviewer-задач

Каждый инвариант обязан быть подтверждён Reviewer отдельно (§40:3839); покрытие задачами/тестами/evidence:

| # | Инвариант §40 | Задачи | Тесты/evidence |
|---|---|---|---|
| 1 | Prefilter отсутствует в live Hybrid path | T-3969 | T-3987; grep-инварианты (a) |
| 2 | Old heuristic scoring не переехал под другим названием | T-3970 | grep `score_message\|burst\|mention` в `summary_hybrid_budget`/`summary_l1_clusterizer` = 0 |
| 3 | Technical overflow protection осталась | T-3970 | T-3987 (сцен. 4); L1_CONTEXT_PACK overflow |
| 4 | Короткие важные сообщения доходят до L1 | T-3969 | T-3987 (сцен. 1–2) |
| 5 | >1 paragraph → deterministic cut | T-3974 | T-3988 (сцен. 2–3) |
| 6 | Cut не теряет body | T-3974 | T-3988 (сцен. 3) |
| 7 | Plain fallback содержит полный текст | T-3974/T-3976 | T-3988 (сцен. 4) |
| 8 | L2 Writer — текущий Hybrid output prompt | T-3984 (+T-3964) | Q9-карта spec; B1 |
| 9 | PL правильно показывает runtime roles | T-3984 | B1–B2; metadata-панель §10 |
| 10 | Desktop prompts все открываются | T-3981 | T-3990 |
| 11 | Mobile prompts все открываются | T-3982 | T-3991 (browser) |
| 12 | Cover Style editor открывается | T-3985 | T-3990/T-3991 |
| 13 | Cover Style save/reload работает | T-3985 | T-3990/T-3991 + live T-3996 |
| 14 | Summary использует нормальную грамматику | T-3977 (+T-3978) | T-3989 (§30); live T-3995 |
| 15 | Двачерский голос/сленг/мат сохраняются | T-3977 | T-3989 (§30) |
| 16 | Direct Chat style не изменён | T-3977 (аудит shared style blocks) | T-3989 (§30); дифф-проверка Direct-канона |
| 17 | Names/key events получают deterministic bold | T-3975/T-3976 | T-3989 (§29) |
| 18 | LLM не обязана генерировать Markdown | T-3975 (контракт), T-3980 (канон) | запрет `**`/HTML в каноне L2; тест §29 |
| 19 | Code не выбирает «главного шиза» | T-3979 | T-3989 (§31); grep `_most_active_author`/`_ensure_shiz_postfix`/`_SHIZ_AT_RE` = 0 |
| 20 | Effective production prompt source проверен | T-3965 | prompt-map-audit.md (таблица effective source + per-chat mismatch) |

## Чек-лист запретов §38 (вшит в критерии задач; повторено здесь для Reviewer)

Не считать fix'ом: prefilter «просто выключенным» / default `true→false`; спрятанный UI toggle; `score_message` под новым именем; увеличенные thresholds; алгоритмическую обрезку статьи; надежду на automatic Telegram collapse; просьбу к L2 писать `**Markdown**`; сохранённый `_most_active_author`; полный запрет сленга/мата; перенос random lowercase Direct style в Summary; fix только desktop PL; fix только одного открывающегося prompt; Cover Style «исправлен» без mobile проверки (§38:3766–3783).

## Санкции/решения Architect (Step 2) — ЗАКРЫТО

1. Ответы Q1–Q10 — даны в `spec.md` раздел 2 по фактическому коду (без speculative design); факты блока A вошли в spec.
2. Санкция **отрицательного Δ каталога** — УТВЕРЖДЕНА: −8 ключей `summary_filter_*`, −2 группы; счётчики 481/105/103/21, F8-переиздание — контракт (i), задача T-3973 (+ контент-дифф 6 титулов — T-3973/T-3993).
3. **Typography (T-3978)** — решено: deterministic normalizer НУЖЕН, переиспользование существующего `cleanup_llm_text` на Hybrid L2-канонизации (контракт (d)); prompt-only признан недостаточным; без kill-switch/env.
4. **F8-переиздание** — обязательно в релизе 2.58.34 (T-3973/T-3993), артефакты и маркер-тесты атомарно.

## Сверка tasks ↔ spec (раздел 10 spec) — расхождения устранены @PM, 28.09.2026

| # | Расхождение (spec §10) | Правка в tasks.md |
|---|---|---|
| 1 | Нейтральный модуль = существующий `summary_hybrid_budget.py`, перечень переносов — (a) | T-3966, T-3970 переписаны (переезд `estimate_and_split`/`Fragment`/`DEFAULT_FRAGMENT_OVERLAP`, без нового модуля) |
| 2 | `build_l1_payload` → `summary_l1_clusterizer.py`; модуль удаляется целиком | T-3967, T-3971 переписаны + grep-критерий аудита Q2 |
| 3 | Удаление prefilter затрагивает И Legacy-вход (`xml_rows` исчезает) | T-3969 переименован и переписан (оба контура; `truncate_to_tokens`/`max_summary_parts` без изменений) |
| 4 | T-3973: Δ-счётчики и TAB_RULES — (i) + удаление вкладки `'prep'` (frontend) | T-3973 дополнен: 481/105/103/21, in-place TAB_RULES, `WORKSPACE_TABS`/`workspaceGroupTab`/label `'prep'` |
| 5 | Имя поля `emphasis_spans` (schema_version 1, опционально); кап 4/абзац; derived-`emphasis` | T-3975 переписан (канонизация п.1–7), T-3976 (секвенциальный рендер, рендер по списку/по `emphasis`) |
| 6 | T-3978 решён: normalizer НУЖЕН на базе `cleanup_llm_text`, без kill-switch | T-3978 переписан (статус «опциональный» снят, объём = 1 точка вызова + тесты) |
| 7 | T-3979: удаление `_SHIZ_AT_RE`; сохранение `_SHIZ_MARKER`-strip в `_derive_fallback_cover_prompt` | T-3979 дополнен (детали контракта (e), переписывание shiz-тестов) |
| 8 | Миграции: L2 + Narrator + **Legacy Single**; L1-канон не меняется; `PREV_*_R1028` | T-3980 переписан по контракту (g) (3 слепка, ROLLBACK-тест) |
| 9 | Фикс-план (f): 4 точки app.js/index.html/app.css + presentation-карта; честный Source после (h) | T-3981, T-3982, T-3984, T-3985 дополнены (конкретные правки, backend/routes.py не трогаются, связка с T-3965) |
| 10 | T-3986: `SOURCE_WINDOW` первый после `SUMMARY_START`; состав полей — раздел 4 | T-3986 выровнен по разделу 4 (поля L1_CONTEXT_PACK/L2_*/FORMAT_*, −FILTER_*/−RESTORE_*, −S1-поля SUMMARY_COMPLETE, JS-харнесс/log-viewer) |
| 11 | T-3965: факт `per_chat=True` у 6 ключей + mismatch-аудит; условный фикс (h) | T-3965 переписан (процедура Q10: hot PG/chat overrides/код-канон/PREV-слепки; отдельный пункт проверки per-chat) |
| 12 | Каталог-титулы 6 промптов → §9-формулировки (контент, не количество) | T-3973 + T-3993 (контент-дифф в F8, Δ количества = 0) |

**Вердикт: PLANNING_CONSISTENT.** Binding-хэши на момент сверки: `spec.md` SHA-256 `7B7461D0A3648B0D696D9C5813A924D691D505B04F26C091C54C5C901341B0CD`; `adr-1028-1-summary-quality-cleanup-core-decisions.md` SHA-256 `0F7CE3DE205081E443AEFEAE8BD25B23FD8CB245CCD479F0CCACAB4B3116E458`. Трассировка перепроверена: DoD §41 1–22 (таблица выше), запреты §38 (13 пунктов — чек-лист ниже), инварианты §40 (20 пунктов — карта выше), observability §36 (T-3986 = раздел 4 spec). Блокирующих вопросов к Architect нет; условные решения (h) по per-chat и границы эскалации (`routes.py`/PG-DDL) зафиксированы в spec разделах 6/Q10 и не блокируют Build.


---

## Builder execution status (round1028, implementation-side; 28.09.2026)

Реализация завершена в рабочем дереве (БЕЗ коммита, ревью до коммита). Полные
доказательства — `evidence.md`; карта/прод-аудит — `prompt-map-audit.md`.

- **Выполнено Builder'ом:** T-3964, T-3965 (прод-верификация, read-only; (h) не применён —
  per-chat stage-значений на проде нет), T-3966–T-3972, T-3973 (каталог 481/105/103/21 +
  вкладка prep удалена), T-3974–T-3976 (Rich cut + emphasis_spans + formatter),
  T-3977–T-3980 (каноны R1028 + миграции PREV_*_R1028/ROLLBACK + canon-эталоны атомарно),
  T-3981–T-3985 (Prompt Library desktop/mobile/структура/Cover Style), T-3986 (observability),
  T-3987–T-3992 (тесты + полный регресс), T-3993 (2.58.34 + README + F8 атомарно +
  откат-заметка).
- **Прогоны:** pytest 9876 passed / 2 failed (ОБА pre-existing от чужой WIP-волны:
  hotfix8/9 tokens `saturate(103%)` — на HEAD зелёные, падают с WIP-тестами независимо
  от ASAP-2.1); JS 49/49; F8 `--check` OK; Δ DDL=0.
- **Browser verification (implementation-side):** B1–B7 PASS (Playwright MCP, standalone
  uvicorn + одноразовый docker-PG; скриншоты B4/B6 в `tools/asap21_*.png`). Reviewer
  повторяет независимо.
- **НЕ выполнялось (вне Builder):** T-3994 (прод-деплой), T-3995/T-3996 (live acceptance),
  T-3997 (post-deploy log check), T-3998 (gate §46). До успешного деплоя фича ACTIVE (§42).
