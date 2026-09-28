# ADR-1027-10 — `mca-asap2-summary-pipeline`: двухконтурная архитектура Summary (Hybrid + Legacy fallback), §95-v2 semantic graph c many-to-many, deterministic repair + correction retry, bounded recovery-бюджет LLM, раздельные Hybrid/Legacy настройки — Δ DDL = 0, Δ каталога = +16/+5 групп, R1

- **Статус:** **Proposed** (Accepted — по Merge в `plans/ARCHITECTURE.md` в фазе
  reconcile, T-3963).
- **Фича:** `mca-asap2-summary-pipeline` (round 10.27, P0 владельца). **Deploy:** REQUIRED (prod, ≥2.58.33).
- **ТЗ-основание:** `plans/current_task.md:1884–2768` (`# ASAP 2 / P0`, §0–§21);
  спецификация — `plans/features/mca-asap2-summary-pipeline/spec.md` (контракты (a)–(n), Q1–Q8).
- **Baseline:** прод `270c277` (APP_VERSION 2.58.32, ASAP-1 trim-hotfix VERIFIED);
  рабочее дерево = 2.58.32 + незакоммиченная MCA-волна round1027 + uncommitted
  partial L1-retry (локальный пин 2.58.33, SUPERSEDED, перерабатывается);
  каталог `REGISTRY 473 / GROUPS 102 / _TAB_BY_GROUP 100 / TAB_RULES 21`;
  pytest 9851/0 (partial-срез), JS 48/48.
- **Связано:** AMEND ADR-1026-5 D5 (§95-контракт L1), ADR-1026-6 D1/D2/D5 (§96
  FactPackage + бюджет), ADR-1026-7 D2/D4/D5 (L2/форматтер: кап абзацев, «ровно 2
  вызова», «без legacy-фолбэка»), ADR-1026-11 D5 (§106-коды/цепочка публикации),
  ADR-1026-12 D2 (§107 kill-switch/UI). REUSE: `summary_filter`/`summary_context_restore`
  (S1/S2), `hot_config`/`_chat_limit`/`resolve_chat_limit`/`safe_budget`,
  `send_rich_message`/`_publish_*_document` (S6), PREV_*/ROLLBACK-механика ADR-1013-3,
  F8-реестр ADR-1025-21. SUPERSEDE: ASAP-1 trim-костыль 2.58.32 (удаление по §16) и
  partial same-prompt retry T-3928…T-3934 (переработка по §15).

## Контекст

После внедрения Hybrid-пайплайна (round1026 S3–S10) саммари стало нестабильным:
16/17 прогонов за 30 дней — degraded. Прод-инцидент 27.09 (отбраковка валидной статьи
по мягкому капу `limits.max_summary_parts`) закрыт ASAP-1 trim-костылём (2.58.32), но
костыль владелец требует удалить (§16); пост-деплойные провалы сместились на L1
(`invalid_json`, `message_in_multiple_threads` → `L2_SKIPPED l1_not_usable` →
публикации нет). Корневые причины (§ «Контекст» current_task.md:1886–1897):
строгий partition-контракт §95 (один id — ровно один тред) неверен для живого
группового чата; любая мелкая неконсистентность L1 фатальна; fail-closed §106 без
фолбэка оставляет пользователя без саммари; legacy-ключ MAX_SUMMARY_PARTS ошибочно
управляет длиной Hybrid-статьи; настройки Legacy/Hybrid смешаны в backend и miniapp.
Владелец требует восстановить ДВУХКОНТУРНУЮ архитектуру (§0): HYBRID = качественная
Article summary; LEGACY = надёжный fallback с Telegram PARTS; «не очередной локальный
hotfix по reason=...» (:1902–1903).

Фактическое состояние baseline (сверено с кодом):
- `services/summary_l1_contract.py:377–384` — `REASON_MESSAGE_IN_MULTIPLE_THREADS`
  fail-closed; `:420–431` — `unassigned_conflict` fail-closed; `:399–409` —
  `evidence_not_in_thread` fail-closed.
- `services/summary_l1_clusterizer.py` (uncommitted diff) — same-prompt retry c
  `_RETRYABLE_REASONS` (включая `message_in_multiple_threads`/`unknown_message_id`);
  `pack_l1_input._unit:176–178` оценивает ТОЛЬКО текст (serialized-поля не учтены);
  вытеснение по бюджету — «самые старые первыми».
- `services/summary_fact_package.py:504–510` — повторный fail-closed на пересечении
  membership; `_select_fragments:233–257` — fragments несут только message_id+text
  (author/reply теряются, §12 нарушается); бюджет — общие
  `limits.summary_max_context_*` (`resolve_fact_package_budget:176–193`).
- `services/summary_l2_writer.py:236–250` — `resolve_l2_max_paragraphs` из
  `limits.max_summary_parts`; `:566–613, 869–881` — trim-костыль 2.58.32; `:29–30` —
  «legacy-фолбэка НЕТ (третий вызов)»; длина в промпте — только `_DETAIL_PARAGRAPH_HINT`
  по L1-`response_mode` (soft targets нет).
- `services/summary_generator.py:741` — L2-провал → «не публикуем», return; `:710–720`
  — L1 unusable → `L2_SKIPPED` → degraded; LEVEL-2/LEVEL-3 отсутствуют; legacy-ветка
  `:484–618` (OFF-путь) — рабочая, но не подключена как fallback.
- `services/param_catalog.py:219–220, 1079–1080` — группа `limits_summary` смешивает
  legacy- и общие ключи; hybrid-ключей/секций нет; `flags.summary_hybrid_l2_enabled`,
  слоты L1/L2 — вне каталога (env-only).

## Решения

**D1. §95-v2: threads c relaxed membership (semantic graph many-to-many), `schema_version: 2`; НЕ двухсущностная схема.**
- **Выбрано:** форма выхода L1 сохраняется (`threads[{thread_id, topic, message_ids[],
  facts[{text, evidence_message_ids[]}]}]` + `unassigned_message_ids` + служебные
  `response_mode`/`cover_prompt`); `message_id ∈ 0..N topics` — пересечения
  `message_ids` между тредами допустимы; `REASON_MESSAGE_IN_MULTIPLE_THREADS` удаляется
  из валидатора И из FactPackage; сторона Message графа (author/timestamp/text/reply_to)
  материализуется КОДОМ из §92-payload (fragments v2), LLM её не ре-эмитит.
  Валидатор проверяет только: структуру/типы JSON, существование id, ссылочность,
  наличие evidence у фактов, отсутствие синтетики, жёсткие лимиты (100/30/1000) —
  исчерпывающий список §5:2138–2143. `unassigned_message_ids` обязателен; конфликт
  с membership разрешается repair'ом (membership побеждает).
- **Обоснование:** §4:2078–2126, §5:2128–2154, §7:2214–2219; ре-эмиссия сообщений
  моделью = дублирование детерминированного источника + поверхность галлюцинаций
  («нет полностью синтетических сообщений» §5:2143); минимальный дифф парсера/IdSpace/канонизатора.
- **Альтернатива:** двухсущностный граф `Topic{evidence_message_ids[]}/Message{topic_ids[]}`
  в ВЫХОДЕ LLM (§4:2107–2123 «архитектурно предпочтительно») — отклонено как wire-форма:
  полная смена схемы/канона/пакета/тестов ради той же many-to-many семантики, которую
  threads-v2 выражают пересечениями; `topic_ids[]` сохраняется как ПРОИЗВОДНАЯ
  many-to-many карта в chronology FactPackage v2 (контракт (h)) — понятие графа
  реализовано без передачи стороне LLM чужих данных.

**D2. Deterministic repair как отдельный чистый шаг + порог «практически бесполезно».**
- **Выбрано:** новый модуль `services/summary_l1_repair.py` (0 LLM/БД/сети/часов);
  порядок §15:2508–2520: parse → repair → validate; шаги: unknown id → удалить;
  evidence вне membership → расширить membership; fact без evidence → удалить;
  пустой topic → удалить; unassigned-конфликт → разрешить; логи/счётчики
  `unknown_ids_removed`/`facts_removed`/`topics_removed`/`overlapping_topic_memberships`
  (§6:2182–2186, §18:2647–2650). Fail всего L1 — только при
  `topics_after==0 ∨ facts_after==0 ∨ unknown_ids_removed/ids_referenced_before > 0.5`
  (`l1_useless_after_repair`). Kill-switch `flags.summary_hybrid_l1_repair_enabled`.
- **Обоснование:** §6:2157–2190 («не выбрасывать весь L1 result из-за одного
  выдуманного id»); отдельный модуль — наблюдаемый шаг (§18 L1_REPAIR) + изолированные тесты.
- **Альтернатива:** repair внутри валидатора — отклонено (смешение ролей: валидатор
  должен оставаться строгим fail-closed checker'ом; счетчики/verdict чище как явный
  результат repair-модуля).

**D3. Bounded recovery-бюджет LLM (AMEND ADR-1026-5 D1/ADR-1026-7 D5): happy path — ровно 2 вызова; восстановление — ≤5.**
- **Выбрано:** «ровно 2 физических LLM-вызова (L1+L2), 3-й — блокер» и «L2-провал →
  без legacy-фолбэка» ЗАМЕНЯЮТСЯ: happy path — по-прежнему ровно 2; recovery-бюджет
  (только когда результат не дошёл до публикации): ≤1 correction retry L1 (после
  repair) + ≤1 L2 на deterministic fallback-пакете (LEVEL-2) + ≤2 Legacy-генерации
  (LEVEL-3, существующий System2 two-call/single по `SYSTEM2_SUMMARY_ENABLED`).
  Worst case ≤5 генераций; «ничего не отправить» — только при полном отказе обоих
  контуров генерации И доставки. L2 correction retry НЕ вводится.
- **Обоснование:** §8:2222–2267 (availability invariant), §9:2269–2298 (цепочка
  fallback, «где дешевле вызывать Legacy»), §3:2038–2044 (приоритет
  качество/полнота/устойчивость > стоимость), DoD-9/10/16; прод-статистика 16/17
  degraded — цена fail-closed-без-фолбэка выше цены recovery-вызовов.
- **Альтернатива:** (а) сохранить «ровно 2, фолбэка нет» — отклонено (прямо
  противоречит §8/§9/DoD); (б) unlimited retry-циклы — отклонено (§21:2756 «увеличить
  retry и назвать это robustness» запрещено; бюджет конечен и перечислим);
  (в) L2 correction retry — отклонено (владелец требует correction retry только для
  L1 (§15); при деградации провайдера Legacy-контур надёжнее второго L2).

**D4. LEVEL-2 deterministic fallback FactPackage (0 LLM).**
- **Выбрано:** при L1 unusable (любая причина, включая useless-after-repair и
  too_many_*) — `build_fallback_package` из filtered §92-сообщений: один topic
  «Общий ход обсуждения», chronology = все сообщения ASC, fragments = author+text+
  reply links (v2-поля), status ok/truncated (проходит гейт `run_l2`), и L2
  вызывается в любом случае; обложка — детерминированная
  (`_derive_fallback_cover_prompt`, 0 LLM).
- **Обоснование:** §8:2243–2260 verbatim; DoD-9; §17 тест 10.
- **Альтернатива:** сразу LEVEL-3 Legacy при смерти L1 — отклонено (§8 явно требует
  «и всё равно вызвать L2»: hybrid-статья по хронологии качественнее legacy-текста;
  Legacy остаётся на случай смерти самого L2).

**D5. MAX_SUMMARY_PARTS — только Legacy: prompt-бюджет + send-кап чанков; полный вывод из Hybrid; trim-костыль 2.58.32 удалён.**
- **Выбрано:** `resolve_l2_max_paragraphs`, cap-ветка `run_l2`,
  `_trim_document_for_publication`, `REASON_TRIMMED_FOR_PUBLICATION`,
  `SUMMARY_L2_TRIM_ENABLED` — УДАЛИТЬ (§16:2536–2548 — «удалить, а не оставить
  выключенным»; тесты trim переписать). Legacy сохраняет `max_symbols = parts×4000−200`
  (§1:1940–1945) И получает send-time кап: legacy plain-доставка отправляет ≤ parts
  чанков (избыток — WARN `LEGACY_CHUNKS_CAPPED`, не молча); hybrid-доставка
  `max_chunks=None` (полный текст). Прод-значение hot-ключа 6 (поставлено ASAP-1) —
  оставить: оно больше не влияет на Hybrid, а legacy-семантика «до 6 сообщений» разумна.
- **Обоснование:** §1:1932–1978, §16, §17 тесты 1–2, DoD-1/2; send-кап — единственная
  трактовка, при которой тест 2 («>4000 chars при parts=1 → максимум одна часть»)
  выполним детерминированно; §3/§21 запрещают обрезку Hybrid-статьи — на Legacy
  «максимальное число частей, на которые МОЖНО разбить» (§1:1936–1938) — это и есть
  объявленная семантика.
- **Альтернатива:** только prompt-бюджет без send-капа — отклонено (модель может
  превысить бюджет → parts=1 даст 2+ сообщения, §17 тест 2 красный); переименовать
  ключ — отклонено (§14:2482–2484 backward-compat, старое имя + Legacy-пометка).

**D6. Hybrid-настройки длины: soft targets в L2-промпт, `max_chars` = WARN-порог аномалии.**
- **Выбрано:** ключи `limits.summary_hybrid_target_chars/_max_chars/_target_paragraphs/
  _response_mode`; пресеты casual 4000/5, serious 6500/8, deep_research 11000/14
  (серединные значения §2:2011–2018, serious подтверждён §10:2316–2318; запас до
  rich-потолка 32000 ≥ 2.9×). Target — мягкий ориентир в детерминированном
  length-блоке user-контента L2; paragraph target — рекомендация, НЕ validator
  condition (§10:2330–2332). `max_chars=24000`: ≤24000 — ok; 24000–32000 — публикуем
  + WARN `L2_OVER_SOFT_CEILING`; >32000 — существующий технический fail-closed
  `too_long` → LEVEL-3. Валидатор никогда не сравнивает результат с target.
  Конфиг-режим пользователя побеждает L1-`response_mode` (тот остаётся в
  observability).
- **Обоснование:** §2:1981–2024, §3:2027–2076, §10:2301–2332, §17 тесты 8–9;
  «значения проверить относительно реального sendRichMessage Article» (§2:2020) —
  проверено (RICH_MAX_CHARS/498/900/200, rich→plain фолбэк полного текста).
- **Альтернатива:** max_chars как жёсткий validator/обрезка — отклонено (§2:1996–1997
  «не должен использоваться как обычные ножницы»; §3:2069 «немного превысила — не ошибка»).

**D7. Раздельные democratic-бюджеты Legacy/Hybrid по реальному serialized prompt.**
- **Выбрано:** `limits.summary_hybrid_context_tokens/_chars` (30000/120000 default) —
  единственные ключи входа Hybrid (L1-упаковка, FactPackage, S1/S2 в hybrid-режиме);
  Legacy — только `limits.summary_max_context_*`. Формула: `safe_budget(tokens) −
  tokens(system) − markers − output_reserve` (L1 4000, L2 6000 — env ClassVar);
  оценка сообщения — по сериализованному §92-JSON-элементу (не по голому text).
  Вытеснение: ASC `(reply_protected, −weight_S1, timestamp)` — сначала старый
  малозначимый контекст, reply-цепочки и ключевые события защищены; последнее
  сообщение всегда; вытеснение → truncated+WARN.
- **Обоснование:** §11:2335–2368 (широкий бюджет; «не 50% окна» — margin =
  существующий TOKEN_SAFETY_MULTIPLIER ~1.15; порядок «шум → старый контекст,
  reply chains сохранять»; «полное разделение лимитов»).
- **Альтернатива:** общий бюджетный ключ с режимным множителем — отклонено
  (§11:2356 «полностью разделить»; смешанный ключ — корень инцидента 27.09).

**D8. Fail-soft LEVEL-3: Legacy — настоящий fallback; матрица «стадия отказа → действие».**
- **Выбрано:** OFF-ветка legacy извлекается в `_run_legacy_pipeline` (общая для
  OFF-режима и LEVEL-3; без перечитывания окна/рефильтрации/дубля memorize);
  вход в LEVEL-3 — по матрице spec-контракта (i) (11 строк): L2 unusable (вкл.
  fallback-пакет), plain-доставка hybrid-текста провалилась, непредвиденное
  исключение при неопубликованном результате; guard `published` исключает двойную
  публикацию; гейт `flags.summary_legacy_fallback_enabled`; `SUMMARY_GENERATION_FAILED`
  — только когда И Legacy провалился; `L2_SKIPPED l1_not_usable` больше не терминален.
- **Обоснование:** §8:2262–2266, §9:2269–2298, §17 тесты 11–13, DoD-9/10/15/16.
- **Альтернатива:** (а) legacy = single-call always — отклонено (DoD-10 «Legacy
  остаётся РАБОЧИМ fallback» = существующий полноценный пайплайн, backward-compat
  §1:1978); (б) вызывать Legacy до L2-fallback — отклонено (§8 LEVEL-2 обязателен,
  hybrid-статья качественнее).

**D9. Correction retry (переработка uncommitted partial) — только после repair, с текстом причины.**
- **Выбрано:** ≤1 вторая попытка; user-контент = исходный + correction-блок
  (reason-код + «unknown message ids: [≤20 id] … Do not invent message ids» по
  §15:2496–2499); retryable-набор — post-repair классы (invalid_json, empty_response,
  bad_type, unknown_field, bad_schema_version, invalid_thread_id, invalid_topic,
  invalid_fact, l1_useless_after_repair, unknown_message_id-defense); НЕ retryable —
  транспорт (LLMError/LLMTimeout) и too_many_*; `message_in_multiple_threads` не
  существует как причина. Из partial сохраняются: цикл attempts, plumbing `attempts`
  в L1_COMPLETE, kill-switch-паттерн; переписываются: `_RETRYABLE_REASONS`, same-prompt
  `continue` → correction-сообщение, hot-first резолв флага.
- **Обоснование:** §15:2487–2531, §16:2550–2554 («сохранить только если превращён в
  correction retry после deterministic repair»).
- **Альтернатива:** оставить same-prompt retry — отклонено (§15:2512–2516 прямо
  запрещает «повторить тот же запрос»); удалить partial целиком — отклонено (цикл/
  attempts-механика годна, §16 разрешает сохранение после переработки).

**D10. FactPackage v2 → L2: полный авторский контекст, topic-связи, без технической metadata.**
- **Выбрано:** `SCHEMA_VERSION=2`; fragments несут `message_id, author_id,
  display_name, timestamp, reply_to_id, text`; chronology — `topic_ids[]`
  (many-to-many карта); НЕ передаются chat_id/DB-id/message_type/mentions/budget/
  service/skipped; дедуп fragments между тредами не выполняется (пределы —
  существующие капы 30/500 + бюджет); семантическая дедупликация повторов —
  инструкция L2-канона.
- **Обоснование:** §12:2371–2398 (рассказчик понимает «кто что сказал, кто кому
  отвечал»; «всю внутреннюю техническую metadata тащить не нужно»), §5:2150–2154.
- **Альтернатива:** глобальный дедуп fragments (одно сообщение — один раз на пакет) —
  отклонено (теряется локальность темы для рассказчика; экономия токенов — последний
  приоритет §3:2038–2044).

**D11. Miniapp: две визуальные секции; Recovery-тумблеры — hot-ключи каталога (Δ +16 REGISTRY / +5 GROUPS / +5 _TAB_BY_GROUP, TAB_RULES 21 in-place); F8-переиздание.**
- **Выбрано:** workspace-вкладки модуля «Саммаризация» 'hybrid' («HYBRID SUMMARY») и
  'legacy' («LEGACY SUMMARY FALLBACK») — маппинг по id групп в `workspaceGroupTab`
  (прецедент 'prep'); группы: `flags_summary_hybrid` (enabled/repair/retry),
  `models_summary_hybrid` (L1/L2 base_url/model/api_key — hot-ключи уже читаются
  слот-резолверами), `limits_summary_hybrid` (context ×2 + длина ×4),
  `flags_summary_legacy` (legacy fallback enabled), `limits_summary_legacy`
  (max_summary_parts + summary_max_context_* — перенос с ретитлом «Legacy»).
  Общие ключи (throttle/timezone/chunk_delay/окно/фильтр) — вне секций. Подпись
  MAX_SUMMARY_PARTS — verbatim §13:2445–2449. Отдельный legacy-модельный слот НЕ
  создаётся (Legacy на основной модели; описание в секции). AMEND ADR-1026-12 D2:
  чекбокс «Hybrid Summary enabled» в UI — аварийный kill-switch по §13, не «ручная
  активация»; резолв per-chat → hot → env сохранён.
- **Обоснование:** §13:2400–2455 (обязательная часть задачи), §14:2457–2485, DoD-11,
  §17 тесты 14–16; §21:2762 (смешивание запрещено).
- **Альтернатива:** env-only тумблеры (Δ каталога=0) — отклонено (§13 требует
  user-facing Recovery-строк в miniapp; env-only в UI невидим).

**D12. Observability: §18-скелет аддитивно, без переименования существующих событий.**
- **Выбрано:** существующие SUMMARY_*/FILTER_*/L1_*/FACT_PACKAGE_*/L2_*/FORMAT_*/
  COVER_*/PUBLISH_* сохраняют имена (пинят S7/S8-тесты и JS-харнесс); §18-соответствие —
  аддитивные поля (FILTER_COMPLETE += messages_before/after, serialized_chars/tokens;
  L2_START += response_mode/target_chars/target_paragraphs; L2_COMPLETE += chars;
  FACT_PACKAGE_COMPLETE += topics/messages) + новые события L1_PARSE, L1_REPAIR,
  L1_CORRECTION_RETRY, L1_FALLBACK_PACKAGE, LEGACY_FALLBACK, LEGACY_CHUNKS_CAPPED,
  L2_OVER_SOFT_CEILING; маппинг SUMMARY_DONE≡SUMMARY_COMPLETE/FAILED,
  ARTICLE_FORMAT≡FORMAT_*, COVER≡COVER_*, RICH_PUBLISH≡PUBLISH_RICH_*,
  PLAIN_FALLBACK≡PUBLISH_TEXT_* — таблица spec (k). R17: только числа/коды/id;
  raw messages/секреты запрещены (§18:2684).
- **Обоснование:** §18:2634–2684 («логи одного run читаются как pipeline»);
  аддитивность дешевле переименований (bound-тесты/харнесс S7/S8).
- **Альтернатива:** переименовать события под §18 verbatim — отклонено (ломает
  §110-фильтр/тесты/S8-адаптер ради косметики; §18 задаёт порядок и состав полей,
  что обеспечено маппингом).

## Последствия

- **Положительные:** доступность саммари восстановлена (availability invariant §8); качество
  L1 на переплетённых темах (many-to-many); длина статьи управляется рассказчиком,
  а не ножницами; настройки разделены и объясняют принадлежность; наблюдаемость
  одного прогона читается как pipeline; Legacy — проверенный аварийный контур.
- **Отрицательные/риски:** worst-case стоимость прогона растёт до ≤5 генераций
  (только на отказах; happy path — прежние 2); L2-вход растёт на author-поля
  fragments (~+10–15% токенов пакета); Δ каталога +16 → F8-переиздание и
  версия-пины; R1-риск врезки в цепочку доставки (митигация: guard published,
  kill-switch'и, §114-harness, откат `SUMMARY_HYBRID_L2_ENABLED=false` → весь
  трафик Legacy байт-в-байт).
- **Откат:** soft — env-kill-switch'и (hybrid/repair/retry/fallback) + ROLLBACK
  канон-миграция `PREV_*_R1027`; cold — revert feat-коммита (прод-базис `270c277`).
- **AMEND-карта:** ADR-1026-5 D1/D5 (2-вызовность → bounded recovery; §95 → v2);
  ADR-1026-6 D1/D2/D5 (пакет v1 → v2, бюджет hybrid-ключи, fail-closed membership
  снят); ADR-1026-7 D2/D4/D5 (кап абзацев из max_summary_parts → удалён; trim →
  удалён; «без legacy-фолбэка» → LEVEL-3); ADR-1026-11 D5 (§106-коды: терминальность
  сужена до «оба контура мертвы»); ADR-1026-12 D2 (UI-видимость kill-switch).
  SUPERSEDE: ASAP-1 trim (2.58.32), partial same-prompt retry (T-3928…T-3934).
