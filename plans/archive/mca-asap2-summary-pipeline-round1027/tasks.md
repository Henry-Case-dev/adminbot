# mca-asap2-summary-pipeline — tasks.md

- **Feature-ID:** `mca-asap2-summary-pipeline` (стабильный opaque ID; порядок НЕ кодируется префиксом)
- **Родительская задача:** `memory-context-autonomy` (MCA, round1027)
- **Источник требований (immutable):** `plans/current_task.md`, блок `# ASAP 2 / P0`,
  **строки 1884–2768** (разделы §0–§21; 16 приёмочных тестов §17 строки 2557–2631;
  DoD §20 строки 2703–2742; анти-паттерны §21 строки 2745–2762). Файл не редактируется;
  ссылки ниже — «ASAP-2 §N (current_task.md:строка)».
- **Статус плана:** PLANNING_CONSISTENT — сверка tasks.md ↔ spec.md выполнена
  (2026-09-28): все 14 расхождений spec §9 устранены в тексте задач, Q1–Q8 закрыты
  (spec §2), ADR-1027-10 принят как AMEND-карта.
  **Binding:** `spec.md` SHA256 `C30AABC49CC3E996C7CBF072A154FCD7EA7E8C0963974F9ACEE34B30F67C12DC`;
  `adr-1027-10-summary-dual-circuit-recovery.md` SHA256 `5542CCBE8A809FBF6B32E88C5CC5FE235FA38CA74EAAF2D72040E7A6EFD60DD3`
  (Get-FileHash, 2026-09-28). При входе в Build хэши перепроверяются; изменение
  spec/ADR откатывает статус в PROVISIONAL.
- **Роль в цепочке:** завершает начатое ASAP-1. Родительский hotfix
  `mca-asap-summary-hotfix` T-3918…T-3927 (L2-trim, прод **2.58.32**, коммит `270c277`,
  review Approved, deployment VERIFIED) — **не повторяется и не переоткрывается**.
  Его trim-костыль **удаляется** в рамках этой фичи (ASAP-2 §16).

## Связь с partial-реализацией (uncommitted, рабочее дерево)

В дереве лежит **нелокальная неревьюенная partial** предшественника: `run_l1`
same-prompt retry (бывшие T-3928…T-3934, аннотированы как
`PARTIAL · UNREVIEWED · SUPERSEDED` в `plans/features/mca-asap-summary-hotfix/tasks.md`):
`services/summary_l1_clusterizer.py` (diff), `config/settings.py`
(`SUMMARY_L1_RETRY_ENABLED`, локальный пин APP_VERSION 2.58.33), untracked
`tests/test_summary_asap2_l1_retry_round1027.py`. По ASAP-2 §15/§16 он
**перерабатывается, а не оставляется как есть** — это задача T-3947.

## Scope OUT (границы, запрещены §-ами владельца)

- **Graph memory / GraphRAG не переписывать** (ASAP-2 §19:2687) — только
  проверка fail-soft (T-3957), отдельной задачи на переписывание НЕТ.
- **Legacy Summary не удалять** (§0:1899, §21:2759) — он остаётся рабочим
  emergency fallback и kill-switch.
- `web/api/routes.py` и `services/telegram_send.py` — вне диффа; PG-DDL Δ=0;
  R17: raw messages/секреты в логах запрещены (spec §1/§10).
- Не трогать незакоммиченную MCA-волну round1027 (~94 файла в `git status`) —
  вне scope этой фичи.

## Пометки задач

- `[ARCH]` — пометка ВРЕМЕННОГО блокирующего статуса до появления `spec.md`;
  spec создан и сверён (2026-09-28) — **все `[ARCH]`-пункты закрыты, задачи
  перемаркированы в `[MECH]`/`[MIXED]`**;
  `[MECH]` — механическая при наличии spec (не требует новых решений);
  `[MIXED]` — механическая часть выполнима, параметр зафиксирован spec.
- `[PARTIAL→]` — задача удаляет/перерабатывает код partial-реализации или
  hotfix-костыль 2.58.32.
- Риск: R1 — задевает живую доставку/публикацию (цепочку отправки);
  R2 — задевает живой пайплайн генерации; R3 — механика/тесты/наблюдаемость.

## Traceability-матрица (требование → источник → задачи → приёмка)

| # | Требование (ID) | Источник (ASAP-2 §, строка current_task.md) | Задачи | Приёмочный тест §17 | Состояние |
|---|---|---|---|---|---|
| R1 | MAX_SUMMARY_PARTS — только Legacy | §1 (1932–1978), DoD-1/2 | T-3935, T-3938 | 1, 2 | planned |
| R2 | Удалить алгоритмическую обрезку 2.58.32 | §16 (2533–2554), §3 | T-3936, T-3937 | 8 | planned |
| R3 | Собственные Hybrid-настройки длины | §2 (1981–2024) | T-3940 | 1, 8 | planned (spec ✓) |
| R4 | Hard-limit'ы только технические | §3 (2027–2076) | T-3939 | 8, 9 | planned |
| R5 | L1 semantic graph many-to-many | §4 (2078–2126), §5 (2128–2155) | T-3944, T-3946 | 3, 4, 6 | planned (spec ✓) |
| R6 | Deterministic local repair | §6 (2157–2190) | T-3945 | 5 | planned (spec ✓) |
| R7 | Fail-soft три уровня + цепочка доставки | §8 (2222–2267), §9 (2269–2298) | T-3949…T-3952 | 10–13 | planned (spec ✓) |
| R8 | L2 управляет длиной (targets в prompt) | §10 (2301–2332), §3 | T-3942 | 8, 9 | planned (spec ✓) |
| R9 | Бюджеты democratic, раздельные | §11 (2335–2369) | T-3941 | — (входит в 6, 13) | planned (spec ✓) |
| R10 | Author/reply context не терять | §12 (2371–2398) | T-3943 | 7 (косвенно) | planned |
| R11 | Miniapp: секции Hybrid/Legacy | §13 (2400–2455), DoD-11 | T-3953, T-3954 | 14, 15, 16 | planned |
| R12 | Param catalog / имена | §14 (2457–2485) | T-3955, T-3938 | 16 | planned |
| R13 | Retry только correction-repair→retry | §15 (2487–2531), §16-2.58.33 | T-3947, T-3948 | 5 (через repair) | planned (spec ✓) |
| R14 | Observability pipeline-читаемость | §18 (2634–2684) | T-3956 | — (сопровождает 1–13) | planned |
| R15 | Graph memory не трогать, проверка | §19 (2687–2700) | T-3957 | — | planned |
| R16 | 16 приёмочных тестов + DoD | §17 (2557–2631), §20 (2703–2742) | T-3958…T-3961 | 1–16 | planned |
| R17 | Прод-деплой после ревью | §20, приказ владельца | T-3962, T-3963 | DoD 13–16 на проде | planned |

Орфанов нет: каждый §0–§21 покрыт; каждая задача имеет ≥1 требование.
Запретов-противоречий в скоупе нет (§19 vs §8 — согласованы: граф только
verification-only, T-3957). Матрица сверена с spec §6 (2026-09-28).

---

## Group A — Вывод MAX_SUMMARY_PARTS из Hybrid и демонтаж trim-костыля

- [x] **T-3935** `[MECH]` Удалить связь `limits.max_summary_parts` ↔ L2/Hybrid
  (spec контракт (d); расхождение §9-1 закрыто).
  - Удалить из `services/summary_l2_writer.py`: `resolve_l2_max_paragraphs()`
    (стр. 236–250), кап/параметр `max_paragraphs` в `run_l2` (стр. 771–806,
    868–881; параметр уходит из сигнатуры — `summary_test_run.py` его не передаёт,
    grep-проверка), комментарий «Совместимость с limits.max_summary_parts»
    (стр. 64) и `MAX_PARAGRAPHS_DEFAULT`. Гибрид-validation по параметру
    отсутствует вместе с cap-веткой (остаётся только `MAX_PARAGRAPHS_HARD=498`);
    prompt-логика длины Hybrid заменяется length-блоком из НОВЫХ hybrid-ключей
    (контракт (f), T-3940/T-3942).
  - Файлы: `services/summary_l2_writer.py`, тесты `tests/test_summary_l2_writer.py`
    (юниты `resolve_l2_max_paragraphs`).
  - Acceptance: ASAP-2 §1 (1964–1976): `resolve_l2_max_paragraphs` отсутствует;
    MAX_SUMMARY_PARTS=1 → Hybrid L2 с 8 абзацами публикует ПОЛНУЮ статью
    (§17 тест 1 — реализуется в T-3958).
  - rg-инвариант после Build (ОБНОВЛЁН по spec §9-1): `max_summary_parts` /
    `MAX_SUMMARY_PARTS` встречается ТОЛЬКО в legacy-контурах
    `services/summary_generator.py` (промпт-бюджет :547–548 + send-кап чанков —
    T-3938), `config/settings.py:938`, `services/param_catalog.py` (legacy-группа)
    и тестах legacy-семантики. Прежняя формулировка «только :547 и каталог»
    устарела: тест §17-2 без send-капа не green.
  - Риск R2. Не трогать legacy-потребители (summary_generator).

- [x] **T-3936** `[PARTIAL→2.58.32]` `[MIXED]` Удалить алгоритмическую обрезку
  статьи из hotfix 2.58.32.
  - Удалить в `services/summary_l2_writer.py`: `_trim_document_for_publication`,
    ветку trim в `run_l2` (стр. 869–881), маркер `REASON_TRIMMED_FOR_PUBLICATION`
    (стр. 97–99), метрики `trimmed_for_publication`/`paragraphs_before/kept/dropped`,
    WARN-строку и `trimmed=` в `L2_COMPLETE`; в `config/settings.py` — ClassVar
    `SUMMARY_L2_TRIM_ENABLED` (стр. 1092–1101). **Владелец §16 (2536–2545) требует
    именно удалить `paragraphs[:cap]`, а не «оставить выключенным».** Жёсткие
    тех-лимиты §99 (498/32000/900/200) остаются (это не trim).
  - Снять NOTE-аннотацию hotfix в `tests/test_tool_coordinator_round1026.py` (стр. 663).
  - Acceptance: §16; rg `SUMMARY_L2_TRIM_ENABLED|_trim_document_for_publication` = 0
    входов в `services/`/`config/`.
  - Риск R2. Зависит от T-3935 (кап больше не резолвится).

- [x] **T-3937** `[PARTIAL→]` `[MECH]` Переписать тесты, утверждающие правильность trim.
  - `tests/test_summary_asap_hotfix_round1027.py` (trim-сценарии а/в) —
    инвертировать в инварианты «не режем, не отбраковываем по мягкому капу»;
    `tests/test_summary_l2_writer.py::test_too_many_paragraphs*` (trim ON/OFF) —
    удалить/заменить; `tests/test_summary_publish_integration_round1026.py:1123`
    (assertion про max_summary_parts×4000 в hybrid-контексте) — перевести на
    legacy-семантику. Байт-в-байт история не сохраняется — тесты переписываются
    (§16: «тесты, утверждающие, что такой trim правильный, тоже переписать»).
  - Acceptance: §16 (2547–2548), §17 тесты 1, 8, 9 зелёные после T-3958.
  - Риск R3.

- [x] **T-3938** `[MECH]` Вернуть `MAX_SUMMARY_PARTS` в строго Legacy-семантику
  с backward-compat: промпт-бюджет + НОВЫЙ send-кап чанков
  (spec контракт (d); расхождение §9-1 закрыто).
  - `config/settings.py:938` — комментарий: «макс. число Telegram sendMessage
    частей legacy-саммари (~4000 симв./часть)»; НЕ переименовывать env-ключ и
    каталожный `limits.max_summary_parts` (обратная совместимость, §14:2482–2484).
    Потребители — ТОЛЬКО legacy-контур: промпт-бюджет
    `summary_generator.py:547–548` (`max_symbols = parts×4000−200`, не меняется)
    И send-time кап (ниже).
  - **Send-time кап legacy-доставки (ADDING, без него §17 тест 2 невыполним):**
    legacy plain-доставка (`_send_chunked`/`_publish_plain_document` при вызове
    ИЗ legacy-контура, `_send_streaming`-остаток) отправляет ≤ `MAX_SUMMARY_PARTS`
    существующих чанков (по границам абзацев ≤4096). Реализация — явный параметр
    `max_chunks: int | None` по цепочке доставки: legacy-вызывающий передаёт резолв
    parts (hot `limits.max_summary_parts` → env), hybrid-вызывающий — `None`
    (hybrid-plain §105 доставляет ПОЛНЫЙ текст). Избыток НЕ теряется молча:
    WARN `LEGACY_CHUNKS_CAPPED | run_id | chat_id | chunks_total= | chunks_sent=`.
    Rich-путь Legacy капом НЕ ограничен (sendRichMessage ≠ sendMessage, §1:1935–1937).
  - Исправить docstring `services/summary_article_formatter.py:30–31`
    (убрать «абзацев ≤ limits.max_summary_parts»; кап статьи — только §99-hard 498).
  - Прод-значение hot-ключа 6 (поставлено ASAP-1 под trim): оставить — после
    удаления trim это чистая legacy-семантика «до 6 сообщений» (рекомендация spec (d)).
  - Acceptance: §1 (1935–1954) + DoD-1/2; §17 тест 2 (Legacy >4000 симв. при
    parts=1 → ровно одна часть + WARN `LEGACY_CHUNKS_CAPPED` — закрепляется
    тестом T-3958).
  - Риск R3 (legacy-доставка; поведение OFF-пути с parts сохранено).

- [x] **T-3939** `[MECH]` Ревизия валидаторов: hard-limit'ы только технические
  (spec Q4/контракт (f); расхождение §9-2 закрыто).
  - `validate_l2_document`/форматтер: остаются §99 fail-closed константы
    (title ≤200, абзац ≤900, ≤498 блоков, rich ≤32000) — это Telegram/API/blocks/
    payload, §3 (2063–2067). Превышение target_chars/target_paragraphs — НЕ ошибка;
    удалить любые условия валидации, сравнивающие результат с мягкими целями.
  - **Граница «аномального ответа» ФИКСИРОВАНА (не ножницы и не 24000):**
    `chars > RICH_MAX_CHARS = 32000` → существующий технический fail-closed
    `too_long` → LEVEL-3 Legacy (защита от runaway-генерации);
    `24000 < chars ≤ 32000` → **публикуем** + WARN `L2_OVER_SOFT_CEILING | chars= |
    max_chars=` (никогда не обрезка); `chars ≤ 24000` → ok всегда.
    `limits.summary_hybrid_max_chars = 24000` — только WARN-порог наблюдения
    (0.75×RICH_MAX_CHARS, ≥2.1× над deep_research-целью), в промпт НЕ передаётся
    (post-hoc guard), валидатор по нему не бракует.
  - Acceptance: §3 (2069–2076), DoD-4; §17 тесты 8–9; failure-case 5 spec §4
    (30000 симв. → WARN+публикация; 33000 → too_long → Legacy).
  - Риск R2.

## Group B — Hybrid-настройки длины, бюджеты, L2-цели, author-контекст

- [x] **T-3940** `[MECH]` Собственные Hybrid-настройки длины (targets, не ножницы)
  — значения зафиксированы spec (Q4/контракт (f); расхождение §9-3 закрыто,
  пометка «значения проверить» СНЯТА).
  - Ключи каталога/env-слои (точные имена spec (f)):
    `limits.summary_hybrid_response_mode` (`SUMMARY_HYBRID_RESPONSE_MODE`, default
    `serious`), `limits.summary_hybrid_target_chars` (default 0 = по пресету),
    `limits.summary_hybrid_target_paragraphs` (default 0; НЕ hard cap, НЕ validator
    condition §10:2330–2332), `limits.summary_hybrid_max_chars` (default **24000** —
    WARN-порог аномалии, T-3939).
  - **Пресеты (модуль-константы, напр. `summary_l2_writer.PRESETS`) — ПРОВЕРЕНЫ
    spec относительно Rich-бюджета (RICH_MAX_CHARS=32000, ≤498 блоков × ≤900):**
    casual → 4000/5 (запас 8×), serious (default) → 6500/8 (4.9×, подтверждён
    примером §10:2316–2318), deep_research → 11000/14 (2.9×). Середины диапазонов
    владельца §2:2011–2018.
  - Резолв: явное значение ключа >0 побеждает пресет; режим per-chat → hot → env →
    `serious`. Конфиг-режим ПОЛЬЗОВАТЕЛЯ побеждает L1-`response_mode` (тот остаётся
    только observability + стиль обложки, spec (f)).
  - Файлы: `config/settings.py`, `services/param_catalog.py` (**Δ каталога > 0 →
    переиздание F8-реестра + версия-пины — см. T-3962, счётчики (j)**),
    `services/summary_l2_writer.py` (резолв, PRESETS), miniapp-референсы (T-3953).
  - Acceptance: §2 (главное: «это TARGETS, а не механическая обрезка»), DoD-3.
  - Риск R2.

- [x] **T-3941** `[MECH]` Раздельные democratic-бюджеты Legacy vs Hybrid
  (spec Q5/контракт (g); расхождение §9-4 закрыто — все три пункта добавлены).
  - Сейчас Hybrid-вход (L1 payload, FactPackage `resolve_fact_package_budget`
    стр. 176) переиспользует общие `limits.summary_max_context_tokens/_chars`
    вместе с Legacy (`summary_generator.py:525–535`). Разделить полностью
    (§11:2356): Hybrid (L1-упаковка, FactPackage, S1/S2 в hybrid-режиме) читает
    ТОЛЬКО новые `limits.summary_hybrid_context_tokens` (default None→30000) /
    `_chars` (default 120000); Legacy — только старые. Единая точка резолва
    `resolve_hybrid_context_budget()` (hot-first + per-chat); ключи
    `resolve_fact_package_budget`/`resolve_l1_budget` переходят на неё.
  - **Бюджет по реальному serialized prompt:** формула spec Q5 —
    `safe_budget(tokens) − tokens(system prompt) − marker_overhead −
    output_reserve`; margin = существующий `TOKEN_SAFETY_MULTIPLIER` (~1.15),
    НЕ 50 % окна (§11:2367). Output reserve — env-only ClassVar (Δ каталога=0):
    `SUMMARY_L1_OUTPUT_RESERVE_TOKENS` (4000), `SUMMARY_L2_OUTPUT_RESERVE_TOKENS`
    (6000). Если данные помещаются в окно модели — не резать из-за маленького
    legacy-лимита (§11:2353–2354).
  - **(а) Serialized-учёт в `pack_l1_input._unit`** (`summary_l1_clusterizer.py:176–178`):
    оценка элемента — `count_tokens(json.dumps(item, separators=(",",":")))` по
    §92-JSON (имена полей ~+15–20 токенов/сообщение), а не только text; делает
    `serialized_chars/serialized_tokens` в логе FILTER честными (контракт (k)).
  - **(б) Mode-резолв `_apply_filter`** (`summary_generator.py:1189–1198`):
    бюджет фильтрации/восстановления резолвится ПО РЕЖИМУ (hybrid →
    `summary_hybrid_context_*`, off → `summary_max_context_*`); режим известен до
    фильтра (`_run:407` раньше `:451`).
  - **(в) Democratic eviction в `pack_l1_input`** — порядок «самые старые первыми»
    заменить на ключ ASC `(reply_protected, −weight_S1, timestamp)`:
    reply-участники цепочек (своё `reply_to_id` на сохраняемое или наоборот) и
    высокий вес S1-фильтра (ПЕРЕИСПОЛЬЗОВАТЬ скоринг `summary_filter`, второй не
    изобретать) вытесняются последними; последнее сообщение — всегда (§93);
    шум снимает S1-префильтр ДО бюджета. Любое вытеснение → `truncated=True` +
    `skipped_ids` + WARN (без молчаливого среза).
  - Acceptance: §11 (2344–2368). Риск R2.

- [x] **T-3942** `[MECH]` L2-prompt: цели длины + дедуп-инструкция (spec контракт
  (l)/Q7 — формулировки зафиксированы).
  - В канон `SUMMARY_L2_WRITER_SYSTEM_PROMPT` (`services/summary_prompts.py`) —
    блок ДЛИНА/ДЕДУПЛИКАЦИЯ формулировками контракта (l): «target — мягкий
    ориентир, не лимит; при избытке материала сначала объединять похожие эпизоды;
    не обрывать статью посередине и не удалять последнюю тему ради лимита
    (§10:2320–2328); одно событие, встреченное через разные темы, рассказать
    ОДИН раз — дедупликация семантическая (§5:2150–2154)» + авторский контекст
    («в пакете указаны авторы и связи ответов — кто что сказал и кто кому
    отвечал», §12).
  - **Числа — НЕ в каноне:** детерминированный length-блок append к user-контенту
    `build_l2_input` (response_mode/target_chars/target_paragraphs, «ориентиры,
    а не лимиты») — hot-правки PG-канона не могут сломать подстановку; `max_chars`
    в промпт НЕ передаётся. Paragraph target — НЕ validator condition
    (§10:2330–2332). Механика PREV_*/ROLLBACK: снимки `PREV_*_R1027` (контракт (l)).
  - Acceptance: DoD-5; §17 тест 7 (дедуп на уровне статьи) — тест в T-3958.
  - Риск R2.

- [x] **T-3943** `[MECH]` FactPackage v2 → L2 сохраняет author/reply-контекст
  (spec контракт (h)/D10 — форма фрагмента зафиксирована).
  - §92-payload уже несёт `author_id`, `display_name`, `timestamp`,
    `reply_to_id`, `text` (`services/summary_context_restore.py:365–391`), но
    Fragments в `services/summary_fact_package.py` (стр. 233–257: только
    `message_id`+`text`) и `build_l2_input` (`summary_l2_writer.py:283–336`)
    их теряют.
  - **Точная форма (контракт (h)):** `SCHEMA_VERSION = 2`; fragments:
    `{message_id, author_id, display_name, timestamp, reply_to_id, text}`
    (`reply_to_id` = null/отсутствует без ответа); chronology:
    `{message_id, timestamp, topic_ids[]}` — many-to-many карта всех тредов,
    содержащих сообщение (детерминированно из L1-выхода, связка с T-3944).
  - НЕ тащить (§12:2397): `chat_id`, DB `id`, `message_type`, `mentions`,
    `skipped_ids`, `budget`, `service`, веса фильтра. `build_l2_input` пробрасывает
    новые поля verbatim; дедуп fragments между тредами НЕ выполняется (капы 30/500 +
    бюджет (g); семантическая дедупликация — L2-промпт, T-3942).
  - Acceptance: §12 (2374–2395); рассказчик видит «кто что сказал / кто кому
    отвечал».
  - Риск R2.

## Group C — L1: semantic graph, repair, prompt, correction retry

- [x] **T-3944** `[MECH]` §95-v2 контракт L1: threads-v2, relaxed membership
  (semantic graph many-to-many) — форма зафиксирована spec (Q1/контракт (a);
  расхождение §9-5 закрыто).
  - **Форма (НЕ двухсущностная схема):** сохраняется `threads[]`
    `{thread_id, topic, message_ids[], facts[{text, evidence_message_ids[]}]}`;
    many-to-many = ПЕРЕСЕЧЕНИЯ `threads[].message_ids` (реплика в N темах = в N
    тредах; в 0 темах = только в `unassigned_message_ids`); дубли внутри треда
    детерминированно дедуплицируются; `schema_version: 2` строго (валидатор
    принимает ровно 2; `bad_schema_version` — retryable). **`unassigned_message_ids`
    ОСТАЁТСЯ ОБЯЗАТЕЛЬНЫМ полем** (список, может быть пустым). Top-level ровно
    5 ключей (лишние → `unknown_field`).
  - `services/summary_l1_contract.py`: убрать partition-инвариант (стр. 377–384,
    `REASON_MESSAGE_IN_MULTIPLE_THREADS` стр. 85) — также из
    `services/summary_fact_package.py` (стр. 88, 504–510). **Миграция fatality
    (spec §9-5):** `REASON_UNASSIGNED_CONFLICT` и `REASON_EVIDENCE_NOT_IN_THREAD`
    уходят ИЗ валидатора В repair (T-3945) — больше не fatal.
  - Валидатор проверяет ИСЧЕРПЫВАЮЩИЙ список (контракт (a)): структура/типы JSON;
    `schema_version==2`; существование message_id в IdSpace; thread_id-паттерн,
    topic ≤200 однострочный / fact ≤500 без тегов; fact с ≥1 evidence (после
    repair); лимиты ≤100/≤30/≤1000 (fail-closed, НЕ retryable); детерминированная
    канонизация (дедуп, ASC, перенумерация thread_001…, байт-идентичность).
    Не ошибка (§5:2145–2148): 0..N тем у реплики, overlapping chronology,
    непокрытые сообщения.
  - Acceptance: DoD-6/7; §17 тесты 3, 4, 6 (реализуются в T-3958).
  - Риск R2 (меняет живой контракт; парные правки prompt-канона T-3946).

- [x] **T-3945** `[MECH]` Deterministic local repair ответа L1 — ОТДЕЛЬНЫЙ модуль
  `services/summary_l1_repair.py` МЕЖДУ parse и validate (spec Q3/контракт (b)/D2;
  расхождение §9-6 закрыто, «открытый вопрос Q3» снят).
  - Чистый модуль (0 LLM/БД/сети/часов): вход `(data, id_space)`, выход
    `(repaired, RepairReport)`, вход НЕ мутируется (копия). Шаги строгого порядка
    (контракт (b)): 1) unknown id в `threads[].message_ids` → удалить
    (`unknown_ids_removed`); 2) unknown id в `facts[].evidence_message_ids` →
    удалить; evidence-id, существующий, но НЕ в membership своего треда → ДОБАВИТЬ
    в `message_ids` (`evidence_membership_added`; `REASON_EVIDENCE_NOT_IN_THREAD`
    живёт здесь, не в валидаторе); 3) fact с пустым evidence → удалить
    (`facts_removed`, §6:2178); 4) тред с пустыми message_ids И фактами → удалить
    (`topics_removed`, §6:2179); тред с сообщениями без фактов — СОХРАНЯЕТСЯ;
    5) unassigned: unknown → удалить; id, присутствующий в треде → убрать из
    unassigned (`unassigned_conflicts_resolved`; `REASON_UNASSIGNED_CONFLICT`
    больше не fatal); 6) посчитать `overlapping_topic_memberships` (информационно).
  - **Формула «практически полностью бесполезен» (ФИКСИРОВАНА, §6:2188):**
    `useless ⟺ topics_after == 0 ∨ facts_after == 0 ∨
    unknown_ids_removed / max(ids_referenced_before, 1) > 0.5`
    (`useless_reason` ∈ {no_topics, no_facts, mass_unknown_ids}); новый код
    `REASON_L1_USELESS_AFTER_REPAIR = "l1_useless_after_repair"` (retryable-класс).
  - Логи/метрики: все поля RepairReport (int/bool, R17-safe) → событие `L1_REPAIR`
    (T-3956, §18/§6:2182–2186). Kill-switch `flags.summary_hybrid_l1_repair_enabled`
    (T-3948): OFF → repair пропускается, валидатор v2 строгий как есть.
  - Файлы: `services/summary_l1_repair.py` (новый), `services/summary_l1_contract.py`
    (снятие мигрированных правил — T-3944), `services/summary_l1_clusterizer.py`
    (врезка `parse → repair → validate` в цикл попыток — T-3947).
  - Acceptance: §6; DoD-8; §17 тест 5; failure-case 1 spec §4. Риск R2.

- [x] **T-3946** `[MECH]` Пересмотр L1 prompt: извлечение смысла (текст канона
  зафиксирован spec контракт (l)/Q7).
  - Канон `SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT` (`services/summary_prompts.py:214–240`)
    по контракту (l): РОЛЬ «кластеризатор саммари (Conversation Disentanglement) —
    понять, что происходило в этом чате»; ЗАДАЧА расширенная (темы, подпроцессы,
    события, позиции, шутки/конфликты, результат, развитие во времени, §7:2205–2212);
    ЯВНО РАЗРЕШИТЬ (§7:2216–2219): не включать малоинформативные (в
    `unassigned_message_ids`), одно сообщение в несколько тем, десятки мелких
    ответов — один факт с несколькими evidence («не заставляй себя выбирать
    одну-единственную тему»); ПРАВИЛО «один id ровно в одной теме» → «может
    встречаться в нескольких темах — это нормально»; жёсткие правила сохраняются
    (только существующие id, evidence из своей темы, ≤200/≤500, 100/30); пример
    JSON — `"schema_version": 2`.
  - Механика PREV_*/ROLLBACK: снимок `PREV_SUMMARY_L1_CLUSTERIZER_R1027` + база
    `_..._R1027_BASE` + идемпотентная канон-миграция PG-ключа (ADR-1013-3).
  - Acceptance: §7. Риск R2. Парная к T-3944 (контракт↔prompt согласованы spec).

- [x] **T-3947** `[PARTIAL→T-3928…T-3934]` `[MECH]` Same-prompt retry → correction
  retry после repair (spec контракт (c)/D9; расхождение §9-7 закрыто).
  - Переработать частичную реализацию в `services/summary_l1_clusterizer.py`.
    Порядок строго §15 (2508–2520): output → parse → normalize → **deterministic
    repair (T-3945)** → validate → «всё ещё реально сломано» → **ровно одна**
    вторая попытка; messages второй попытки = system + исходный user +
    correction-блок (текст контракта (c): «ПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: <reason_code>…
    unknown ids: [≤20 id]… Используй ТОЛЬКО message_id из входных данных… Верни
    исправленный JSON», §15:2496–2499).
  - **Retryable-набор (ПОСЛЕ repair+validate, фиксирован spec §9-7/c):**
    `invalid_json`, `empty_response`, `bad_type`, `unknown_field`,
    `bad_schema_version`, `invalid_thread_id`, `invalid_topic`, `invalid_fact`,
    `l1_useless_after_repair`, `unknown_message_id` (defense: retry — последний
    шанс, repair должен был спасти). НЕ retryable: `LLMError`/`LLMTimeoutError`
    (транспорт), `too_many_threads/_facts/_facts_total` (→ LEVEL-2),
    `id_space_mismatch`/`internal_error`. **`message_in_multiple_threads` — не
    retry-причина и больше вообще не существует (T-3944).**
  - **Флаг:** `SUMMARY_L1_RETRY_ENABLED` становится env-слоем hot-ключа каталога
    `flags.summary_hybrid_l1_retry_enabled` (hot-first резолв, T-3948).
    WARN `L1 retry` → `L1_CORRECTION_RETRY | attempt=1/2 | reason=<код>` (id-списки
    в лог НЕ пишутся — R17). Из partial СОХРАНИТЬ: цикл `attempts`, plumbing
    `attempts` в `L1_COMPLETE`, kill-switch-паттерн; ПЕРЕПИСАТЬ:
    `_RETRYABLE_REASONS`, same-prompt `continue` → correction-сообщение.
  - Переделать `tests/test_summary_asap2_l1_retry_round1027.py` (12 тестов) под
    correction-семантику: `message_in_multiple_threads → retry` инвертировать
    (теперь VALID без retry), unknown-id → через repair, assertion'ы на текст
    correction-блока и первенство repair.
  - Acceptance: §15, §16-2.58.33 (2550–2554: «сохранить только если превращён в
    correction retry после deterministic repair»). Риск R2.

- [x] **T-3948** `[MECH]` Флаги/kill-switch нового L1-потока — HOT-ключи каталога
  (spec Q6/контракт (j); расхождение §9-8 закрыто, «открытый вопрос Q6» снят).
  - **Слой ФИКСИРОВАН: Recovery-тумблеры — hot-ключи PG-каталога + env ClassVar
    как дефолтный слой, резолв hot-first** (паттерн `_hybrid_l2_enabled:652–669`):
    `flags.summary_hybrid_l1_repair_enabled` (env `SUMMARY_L1_REPAIR_ENABLED`,
    default True — НОВЫЙ ClassVar), `flags.summary_hybrid_l1_retry_enabled`
    (env `SUMMARY_L1_RETRY_ENABLED` — uncommitted остаётся env-слоем),
    `flags.summary_legacy_fallback_enabled` (env `SUMMARY_LEGACY_FALLBACK_ENABLED`,
    default True — НОВЫЙ ClassVar), `flags.summary_hybrid_l2_enabled` (существующий
    hot-ключ — впервые каталогизирован).
  - Удалить `SUMMARY_L2_TRIM_ENABLED` (T-3936; не мигрирует).
  - «Fallback to Legacy» — ЕДИНСТВЕННЫЙ ключ `flags.summary_legacy_fallback_enabled`
    (строка Recovery §13:2433 и чекбокс §13:2439 — одна сущность, дубль в двух
    секциях запрещён §13:2451–2452). OFF → LEVEL-3 не выполняется, hybrid-провал
    терминален (осознанный аварийный режим).
  - **Δ каталога > 0 (+16 REGISTRY / +5 GROUPS — счётчики (j)) → F8-переиздание
    через T-3962.** AMEND ADR-1026-12 D2: чекбокс «Hybrid Summary enabled» —
    аварийный kill-switch по §13, резолв per-chat → hot → env сохранён.
  - Acceptance: §13 (Recovery-строки), §14 (имена объясняют принадлежность).
  - Риск R3.

## Group D — Fail-soft: три уровня + цепочка доставки

- [x] **T-3949** `[MECH]` LEVEL-2: deterministic fallback FactPackage
  (spec контракт (i)/D4; расхождение §9-9 закрыто).
  - Если L1 непригоден даже после repair+correction (ЛЮБАЯ причина: invalid после
    retry, error/timeout, useless, too_many_*, empty): новый билдер
    `build_fallback_package(payload_items, *, budget, correlation_id)` в
    `services/summary_fact_package.py` собирает ДЕТЕРМИНИРОВАННО (0 LLM) пакет из
    filtered source messages §92 (после S1/S2): один `thread_001` с
    `name="Общий ход обсуждения"` (§8:2252), `description=""`, `facts=[]`,
    chronology = ВСЕ source messages ASC (`topic_ids=["thread_001"]`),
    **fragments — поля v2 контракта (h): author + text + reply links (T-3943)**.
  - Пакет обязан проходить deliverability-гейт `run_l2`
    (`status in ("ok","truncated")`, `summary_l2_writer.py:792–797`) → **L2
    вызывается в любом случае** (§8:2260). Пустой payload (0 сообщений после
    фильтра) → пакет не строится → НЕ failure, существующая empty-семантика.
  - **Обложка деградированного пути (DoD-14):** детерминированная
    `_derive_fallback_cover_prompt` (0 LLM, гейт `SUMMARY_COVER_FALLBACK_ENABLED`).
  - Файлы: `services/summary_fact_package.py`, `services/summary_generator.py::_run_hybrid_l2`
    (стр. 671+). Лог: WARN `L1_FALLBACK_PACKAGE` (T-3956).
  - Acceptance: DoD-9; §17 тест 10; failure-case 2 spec §4. Риск R2.

- [x] **T-3950** `[MECH]` LEVEL-3 + цепочка доставки до Legacy (spec контракт (i)/
  D8/Q2; расхождение §9-10 закрыто; ADR-1027-10 D3 принята).
  - **Legacy fallback = ПОЛНЫЙ legacy-пайплайн, извлечённый в общий метод**
    `_run_legacy_pipeline(chat_id, rows, xml_rows, focus, trigger_message_id,
    correlation_id, ctx, *, max_parts, skip_memorize)` (тело текущей OFF-ветки
    `summary_generator.py:484–618`): OFF-режим вызывает как раньше (байт-в-байт),
    LEVEL-3 — с уже готовыми `rows`/`xml_rows` (окно НЕ перечитывается, фильтр НЕ
    перезапускается, `skip_memorize=True` — без дубля memorize). System2 two-call/
    single по существующему `SYSTEM2_SUMMARY_ENABLED`. `_llm_generate`/
    `_generate_two_call` НЕ удаляются и НЕ ломаются (DoD-10).
  - Цепочка: Hybrid article → sendRichMessage → fail → plain sendMessage (§105) →
    fail/unavailable → **LEVEL-3 Legacy** (гейт `flags.summary_legacy_fallback_enabled`,
    T-3948) → chunks по MAX_SUMMARY_PARTS с send-капом (T-3938, §9:2281–2293).
    Снять ограничение «L2-провал → без legacy-фолбэка» (`_run_hybrid_l2:741`,
    ADR-1026-7 D5) — amendment ADR-1027-10 D3 принят.
  - **Recovery-бюджет конечен (Q2):** happy path — ровно 2 LLM-вызова; worst case
    ≤5 генераций (≤1 correction retry L1 + ≤1 L2 на fallback-пакете + ≤2 Legacy);
    L2 correction retry НЕ вводится. «Ничего не отправить» — только при полном
    отказе обоих контуров.
  - **Guard двойной публикации:** LEVEL-3 входим ТОЛЬКО если ничего не отправлено
    (флаг `published` в `_run_hybrid_l2`; rich-успех + позднее исключение → НЕ
    fallback).
  - Acceptance: §8 (2233–2237 availability invariant), §9; DoD-9/10/15/16;
    §17 тесты 11–13. Риск **R1** (цепочка доставки в проде).

- [x] **T-3951** `[MECH]` Оптимальная точка вызова Legacy — матрица «стадия-отказ →
  действие» (spec контракт (i)/Q2; расхождение §9-10 закрыто, вопрос Q2 снят).
  - §9:2295–2296 («где именно выгоднее вызывать Legacy, чтобы не делать лишний
    LLM-вызов») РЕШён spec: **матрица из 11 строк контракта (i) — копировать её
    в `evidence.md` этой задачи как единый источник для T-3950/T-3951/T-3952**:
    hybrid OFF → Legacy сразу (0 hybrid-вызовов); пустое окно → не failure;
    L1 invalid/error/timeout/useless/too_many_* / L1SlotError → LEVEL-2;
    L2 unusable (для обычного и fallback-пакета) → LEVEL-3 Legacy (L2-retry нет —
    деградировавший провайдер одинаково ненадёжен, Legacy переключает КОНТУР и не
    дороже); cover-отказ → plain Hybrid (не Legacy); rich-отказ → plain;
    plain-отказ → LEVEL-3; непредвиденное исключение при неопубликованном →
    LEVEL-3 best-effort; Legacy мёртв → SUMMARY_GENERATION_FAILED.
  - Acceptance: §9. Риск R1 (матрица описывает живую цепочку).

- [x] **T-3952** `[MIXED]` §106-коды и UX деградированной цепочки (spec контракт
  (i); AMEND ADR-1026-11 D5 принят ADR-1027-10).
  - Адаптировать коды/UX по матрице T-3951: `SUMMARY_GENERATION_FAILED` — только
    когда и Legacy провалился (строка 11 матрицы); `RICH_MESSAGE_SEND_FAILED`/
    `TEXT_FALLBACK_FAILED` — соответствующие пролёты цепочки (TEXT_FALLBACK_FAILED
    в hybrid больше НЕ терминален — за ним LEVEL-3); `L2_SKIPPED reason=l1_not_usable`
    — больше не терминальный «не публикуем», переход на LEVEL-2 (T-3949, новое
    событие `L1_FALLBACK_PACKAGE`). Промежуточные коды НЕ порождают `_send_ux`
    сообщений об ошибке, пока цепочка работает. Обновить тесты §106-кодов
    (`tests/test_summary_publish_integration_round1026.py`,
    `test_summary_deploy_round1026.py` scenario_07 и подобные fail-closed-сценарии).
  - Acceptance: §8/§9; §17 тесты 10–13. Риск R2.

## Group E — Настройки, каталог, miniapp

- [x] **T-3953** `[MECH]` Miniapp: две workspace-вкладки с ФИКСИРОВАННЫМИ именами
  (spec контракт (j)/D11; расхождение §9-11 закрыто, имён-вариантов больше нет).
  - `web/app.js`/`web/index.html`/`services/param_catalog.py` (GroupSpec): в модуле
    «Саммаризация» (TABS `mod_summary`, строки 85–93) — две НОВЫЕ workspace-вкладки
    (маппинг по id групп в `workspaceGroupTab:6282–6289`, прецедент 'prep'):
    **'hybrid' — «HYBRID SUMMARY»** (группы `flags_summary_hybrid`,
    `models_summary_hybrid`, `limits_summary_hybrid`) и **'legacy' —
    «LEGACY SUMMARY FALLBACK»** (группы `flags_summary_legacy`,
    `limits_summary_legacy`).
  - Состав — побитово по контракту (j): HYBRID — enabled-чекбокс, L1/L2
    model/base_url + api_key (secret; hot-ключи уже читаются слот-резолверами,
    впервые каталогизированы), context tokens/chars, mode-селектор
    (casual/serious/deep_research), target chars/paragraphs, max_chars, Recovery
    (repair + retry; описание retry — «полный отказ Hybrid → Legacy: см. секцию
    LEGACY SUMMARY FALLBACK»); LEGACY — fallback enabled, `summary_max_context_*`,
    `max_summary_parts`. Human-readable описания у всех.
  - **Перенос (не Δ) 3 существующих ключей:** `limits.max_summary_parts`,
    `limits.summary_max_context_tokens/_chars` из `limits_summary` →
    `limits_summary_legacy` с ретитлом «Legacy». Общие ключи (throttle/timezone/
    chunk_delay/compress/retry-pause/stream/max_message_chars, фильтр) остаются в
    нейтральных группах ВНЕ двух секций.
  - **Legacy-модель: НОВЫЙ СЛОТ НЕ СОЗДАЁТСЯ** — Legacy на основной модели
    `models.llm_*`; факт закрывается описанием группы («вкладка LLM Провайдеры»).
  - Ни одного Hybrid-параметра в блоке Legacy и наоборот (spec S4 DOM-assert).
  - Acceptance: DoD-11; §21-запрет «смешать в miniapp»; §17 тесты 14–15 +
    браузерные сценарии S1–S3/S4/S6 (T-3960, REQUIRED).
  - Риск R2 (UI), механика CSP/zero-build сохранена; `web/api/routes.py` вне диффа.

- [x] **T-3954** `[MECH]` Подпись MAX_SUMMARY_PARTS в UI (точная формулировка spec
  (j) / §13:2445–2449).
  - Каталог-описание (стр. 1079): «Максимальное число обычных Telegram-сообщений,
    на которые может быть разбит Legacy Summary. Не влияет на Hybrid Article»
    — verbatim; браузерный S3 проверяет дословное вхождение «Не влияет на Hybrid
    Article» в DOM.
  - Acceptance: §17 тест 16. Риск R3.

- [x] **T-3955** `[MECH]` Аудит param_catalog / settings / hot-config.
  - Инвентаризация всех summary-ключей: имена объясняют принадлежность
    (`summary_hybrid_*` vs legacy); hot-резолв (`resolve_chat_limit`,
    `hot.get`) не перетекает между пайплайнами; MAX_SUMMARY_PARTS — старое имя
    сохранено (backward-compat) с явной Legacy-пометкой (§14:2482–2484);
    результаты — таблица в `evidence.md` фичи.
  - Acceptance: §14 (2460–2480). Риск R3.

## Group F — Observability и graph-memory

- [x] **T-3956** `[MIXED]` Логи-скелет пайплайна §18 — АДДИТИВНО, без переименований
  (spec контракт (k)/D12; расхождение §9-12 закрыто: ветка «переименованием» снята).
  - Существующие имена событий S7/S8 НЕ переименовываются (пинят
    `test_summary_logging_runid.py`, JS log viewer, S8-адаптер). §18-скелет =
    аддитивные поля (FILTER_COMPLETE += messages_before/after,
    serialized_chars/serialized_tokens (serialized-оценка Q5/T-3941); L2_START +=
    response_mode/target_chars/target_paragraphs; L2_COMPLETE += chars, `trimmed=`
    УДАЛЯЕТСЯ (T-3936); FACT_PACKAGE_COMPLETE += topics/messages) + документируемый
    маппинг SUMMARY_DONE≡SUMMARY_COMPLETE/FAILED и т.д. (таблица (k)).
  - **Новые события (7):** `L1_PARSE` (attempt, parse_status, raw_chars),
    `L1_REPAIR` (поля RepairReport), `L1_CORRECTION_RETRY` (WARN, attempt,
    reason — коды, НЕ id-списки), `L1_FALLBACK_PACKAGE` (WARN, reason,
    fragments, chronology), `LEGACY_FALLBACK` (WARN, reason ∈ {l1_unusable,
    l2_unusable, package_unusable, delivery_failed, hybrid_exception:<Class>},
    calls_so_far), `LEGACY_CHUNKS_CAPPED` (T-3938), `L2_OVER_SOFT_CEILING`
    (T-3939); L1_COMPLETE += attempts; SUMMARY_COMPLETE += fallback=none/legacy.
  - R17-safe: только числа/коды/id; raw messages/тексты модели/секреты — НИКОГДА
    (§18:2684). Обновить `tests/test_summary_logging_runid.py` + JS-харнесс;
    проверить попадание новых событий в §110-фильтр «Саммари» (при необходимости —
    правка JS-списка префиксов, Δ каталога=0).
  - Acceptance: §18; «лог одного прогона читается как pipeline» (§18:2637).
  - Риск R3.

- [x] **T-3957** `[MECH]` Graph-memory: verification-only (НЕ трогать).
  - Подтвердить (не переписывать): GraphExtractionError при LLMTimeoutError
    остаётся fail-soft и не влияет на новую цепочку саммари — re-run
    graph-сценариев `tests/test_summary_asap_hotfix_round1027.py` (граф-часть,
    будет перенесена в T-3937) + проверка региона `summary_generator._run`
    (compress_and_purge защищён). Никаких задач на переписывание GraphRAG (§19:
    2697–2700; §21: «исправлять GraphRAG вместо Summary» — запрещено).
  - Acceptance: §19. Риск R3.

## Group G — Приёмочные тесты §17 и полные прогоны

- [x] **T-3958** `[MECH]` Regression: §17 тесты 1–9 (backend).
  - 1 parts=1 → hybrid 8 абзацев — полная статья; 2 parts=1 → legacy >4000
    симв. → **≤1 sendMessage-часть через send-кап (T-3938) + WARN
    `LEGACY_CHUNKS_CAPPED`** (prompt-бюджета alone недостаточно — spec §9-1/D5);
    3 message_id в topics A+B → VALID (`schema_version: 2`,
    `overlapping_topic_memberships=1`); 4 reply-в-одной-теме + смыслово-в-другой →
    VALID; 5 один unknown id → repair (`L1_REPAIR unknown_ids_removed=1`) →
    продолжение; 6 overlapping topics → FactPackage строится; 7 одна evidence через
    разные topics → без двойного пересказа в статье; 8 L2 > target умеренно → не
    режем; 9 L2 < target → не ошибка. Плюс failure-case 5 spec §4: 30000 симв. →
    WARN `L2_OVER_SOFT_CEILING` + публикация; 33000 → too_long → Legacy.
  - Файлы: новый(е) `tests/test_summary_asap2_*` + переписанные из T-3937.
  - Acceptance: §17.1–9. Риск R3.

- [x] **T-3959** `[MECH]` Integration: §17 тесты 10–13 (fail-soft/доставка).
  - 10 L1 полностью непригоден → fallback FactPackage (ok/truncated, проходит
    гейт `run_l2`; coverage — `_derive_fallback_cover_prompt`, DoD-14 на
    деградированном пути) → L2 вызван; 11 Hybrid failed → Legacy
    (`_run_legacy_pipeline`, WARN `LEGACY_FALLBACK reason=…`); 12 sendRichMessage
    fail → plain ПОЛНОГО текста (`max_chunks=None`); 13 plain fail/unavailable →
    Legacy chunks с send-капом. Плюс анти-лавина: «ничего не отправить»
    недостижимо при пригодном материале (кроме полного отказа обоих контуров),
    guard `published` — нет двойной публикации; mock-транспорт (QueueLLM-паттерн
    partial-тестов), 0 реальных LLM/Telegram (spec §8).
  - Acceptance: §17.10–13, DoD-9/10/15/16. Риск R3 (проверяет R1-цепочки).

- [x] **T-3960** `[MECH]` Miniapp-тесты: §17 тесты 14–16 + Browser Verification
  S1–S7 (**REQUIRED** — spec §5; расхождение §9-14 закрыто).
  - Python UI-тесты структуры секций + JS-харнесс (`tests/js/`): Hybrid-вкладка
    отдельно; Legacy-вкладка отдельно; описание MAX_SUMMARY_PARTS — «только
    Legacy Telegram chunks» + verbatim «Не влияет на Hybrid Article».
    Кросс-проверка: ни один гибрид-ключ не рендерится в legacy-блоке (по
    каталог-группам).
  - **Браузерные сценарии (Playwright MCP, `#/modules/summary`, вьюпорты
    1440×900 и 390×844; тестовый webapp на test-БД/сиде каталога, без prod-
    credentials):** S1/S3 — визуально две отдельные вкладки «HYBRID SUMMARY» /
    «LEGACY SUMMARY FALLBACK», общие параметры вне обеих (скриншоты);
    S2 — полнота полей HYBRID (enabled, L1/L2 model/base_url/secret key, context,
    mode-селектор ровно 3 опции, target/max chars, paragraphs, repair/retry с
    человеческими описаниями); S4 — DOM cross-isolation в обе стороны;
    S5 — сохранение (ровно 1 POST `/api/config` на тумблер, reload → значение
    сохранено; смена режима serious→deep_research → GET); S6 — mobile без
    горизонтального overflow, тач-цели ≥44px; S7 — console без ошибок, api_key
    masked-виджет.
  - Acceptance: §17.14–16, DoD-11; **S1–S7 зелёные в Playwright-отчёте Reviewer
    (скриншоты S1/S3 в `evidence.md`/`review.md`) — гейт прохода в деплой T-3963.**
  - Риск R3.

- [x] **T-3961** `[MECH]` Предполётный harness + полные прогоны.
  - Обновить §114-подобный harness (`tests/test_summary_deploy_round1026.py`):
    реалистичный групповой чат с переплетёнными темами → полная связная статья
    (DoD-13), cover+sendRichMessage (DoD-14), plain и Legacy-пролёты (DoD-15/16)
    — без отправки в основной чат. Полный pytest (baseline 9851 до правок;
    после переписанных trim/retry-тестов **новый baseline фиксируется здесь**,
    spec §8) + JS vm-харнесс 48+ файлов exit 0 (обновлённые харнесс-пины F8) +
    `git diff --check` + R17-скан диффа.
  - Acceptance: §20 (все пункты, верифицируемые локально). Риск R3.

## Group H — Релиз и деплой

- [x] **T-3962** `[MECH]` Релизная механика версии и каталога (spec контракт (n)/
  Q8; расхождение §9-13 закрыто — счётчики фиксированы).
  - APP_VERSION: **единый релиз 2.58.33** (не ниже; финальный номер подтверждает
    Orchestrator при релизе). Uncommitted partial (локальный пин 2.58.33) НЕ
    коммитится/НЕ деплоится отдельно (§16:2550–2554) — входит в единый
    feat-коммит (код+тесты+версия-пины) после Reviewer Approved, затем отдельный
    docs-коммит (планы/ADR) — конвенция проекта (Q8). README «Версия»,
    `plans/docs/param-registry-round1025.meta.md`, версия-пины (механика
    коммита `270c277`: 23+ py-пинна + 4 JS-харнесса).
  - **F8-счётчики после переиздания (spec (j)):** REGISTRY 473 → **489** (+16:
    4 flags + 6 models/keys + 6 limits); GROUPS 102 → **107** (+5:
    `flags_summary_hybrid`, `models_summary_hybrid`, `limits_summary_hybrid`,
    `flags_summary_legacy`, `limits_summary_legacy`); `_TAB_BY_GROUP` 100 → **105**;
    TAB_RULES **21** (без изменений — правило mod_summary правится in-place);
    3 ключа меняют группу (перенос, не дельта).
  - Переиздание: `param-registry-round1025.meta.md` (счётчики + APP_VERSION),
    `param-registry-round1025.tsv`, `plans/reports/round1025_f8_config_diff.md`,
    `test_round1025_f8_registry`. routes.py не меняется → пин
    `test_routes_file_unchanged` не трогать. Баунд-гейты: новые summary-файлы —
    санкционированные NOTE в `test_tool_coordinator_round1026.py` /
    `test_summary_deploy_round1026.py`.
  - Acceptance: Δ DDL=0; Δ каталога = +16/+5 задокументирован (в отличие от
    hotfix-философии «Δ=0», здесь каталог РАСШИРЯЕТСЯ намеренно — §2/§13).
  - Риск R3.

- [ ] **T-3963** `[MECH]` Review → reconcile → DevOps-деплой 2.58.33 и прод-DoD
  (spec §8: деплой/откат; расхождение §9-14 — браузерная часть гейта).
  - Порядок: @Reviewer Approved (оба линза + **Playwright-отчёт S1–S7 зелёные**,
    binding к текущему коммиту/дереву/spec) → @Architect reconciliation (merge
    ADR-1027-10 в `plans/ARCHITECTURE.md`: AMEND ADR-1026-5 D1/D5, -6 D1/D2/D5,
    -7 D2/D4/D5, -11 D5, -12 D2) → Orchestrator `delivery → reconcile → archive`
    → @DevOps: штатный прод-деплой (`git pull --ff-only`, рестарт `admin_bot`;
    env-правок не требуется — дефолты в коде ON).
  - Post-deploy: проверка hot-ключей `limits.summary_hybrid_*`,
    `flags.summary_hybrid_*`/`flags.summary_legacy_fallback_enabled`, legacy
    `limits.max_summary_parts` = 6 (оставить, spec (d)). Прод-верификация
    DoD-13…16 на реальном саммари `-1002661910336` по §18-логам (цепочка читается
    как pipeline, поля `fallback=none/legacy`).
  - Откат: soft — env `SUMMARY_HYBRID_L2_ENABLED=false` (весь трафик Legacy,
    байт-в-байт OFF-путь) либо точечно `SUMMARY_L1_REPAIR_ENABLED` /
    `SUMMARY_L1_RETRY_ENABLED` / `SUMMARY_LEGACY_FALLBACK_ENABLED=false`;
    промпты — ROLLBACK-миграция на `PREV_*_R1027`; cold — revert feat-коммита
    (прод-базис 2.58.32/`270c277`). Деплой **применим**: DEPLOY REQUIRED (prod).
  - Acceptance: §20 полностью (пункты 13–16 — только на проде). Риск R1.

---

## Открытые вопросы Q1–Q8 — ЗАКРЫТЫ (ответы в spec.md §2; зафиксированы в задачах)

1. **Q1 — CLOSED (spec Q1/ADR D1):** threads-v2 relaxed membership,
   `schema_version: 2`; `unassigned_message_ids` обязателен; Message-сторона
   материализуется кодом (fragments v2), НЕ двухсущностная wire-схема. → T-3944.
2. **Q2 — CLOSED (spec Q2/ADR D3):** amendment принят ADR-1027-10: happy path
   ровно 2 вызова, recovery ≤5; матрица 11 строк контракта (i). → T-3950/T-3951.
3. **Q3 — CLOSED (spec Q3/ADR D2):** формула `topics_after==0 ∨ facts_after==0 ∨
   unknown_ratio>0.5`; отдельный модуль `services/summary_l1_repair.py`. → T-3945.
4. **Q4 — CLOSED (spec Q4/ADR D6):** пресеты 4000/5, 6500/8, 11000/14;
   max_chars=24000 — WARN-порог; граница аномалии = RICH_MAX_CHARS=32000. → T-3939/T-3940.
5. **Q5 — CLOSED (spec Q5/ADR D7):** ключи `summary_hybrid_context_*` (30000/120000);
   serialized-учёт; margin = `TOKEN_SAFETY_MULTIPLIER` (~1.15); output reserve
   4000/6000; eviction `(reply_protected, −weight_S1, timestamp)`. → T-3941.
6. **Q6 — CLOSED (spec Q6/ADR D11):** Recovery-тумблеры — hot-ключи каталога
   (Δ +16/+5); имена по таблице Q6/контракту (j). → T-3948/T-3953/T-3962.
7. **Q7 — CLOSED (spec Q7/контракт (l)):** новые тексты L1/L2-канонов;
   PREV_*/ROLLBACK-снимки `*_R1027`; length-блок — детерминированный user-контент.
   → T-3942/T-3946.
8. **Q8 — CLOSED (spec Q8/контракт (n)):** единый релиз 2.58.33, feat+docs два
   коммита; partial отдельно не коммитится. → T-3962/T-3963.

## Глобальные запреты (анти-паттерны §21:2748–2762) — проверять в каждой задаче

НЕ делать: увеличивать MAX_SUMMARY_PARTS ради Hybrid; использовать его как
paragraphs; `paragraphs[:N]`/`text[:N]` как контроль длины; запрет membership
в нескольких topics; считать overlap invalid; увеличивать retry 1→3 «ради
robustness»; увеличивать timeout вместо root cause; ослаблять всю validation
подряд (hard-контракты Telegram/структуры остаются); удалять Legacy fallback;
отключать Rich Article; править GraphRAG вместо Summary; смешивать настройки
в miniapp. Финальная рамка: **HYBRID = качественная Article summary,
LEGACY = надёжный fallback с Telegram PARTS** (§21:2765–2768).

## Handoff

- **PLANNING_CONSISTENT ВЫДАН (2026-09-28).** Устранены все 14 расхождений
  tasks↔spec (spec §9-1…§9-14); Q1–Q8 закрыты ответами spec §2; матрица
  трассировки R1–R17 сверена со spec §6 (орфанов нет, противоречий нет); все 16
  приёмочных тестов §17 (current_task.md:2560–2632) отражены в Group G
  (1–9 → T-3958, 10–13 → T-3959, 14–16 → T-3960 + Browser S1–S7); антипаттерны
  §21 задачам не противоречат; scope-out соблюдён (graph memory §19 — только
  verification в T-3957; Legacy жив; Rich Article не отключается).
- **Binding:** `spec.md` SHA256 `C30AABC49CC3E996C7CBF072A154FCD7EA7E8C0963974F9ACEE34B30F67C12DC`,
  `adr-1027-10-...md` SHA256 `5542CCBE8A809FBF6B32E88C5CC5FE235FA38CA74EAAF2D72040E7A6EFD60DD3`
  (перепроверены Get-FileHash 2026-09-28 — совпали). Любая правка spec/ADR ⇒
  перепроверка хэшей Orchestr'ом и откат статуса до повторной сверки PM.
- Все задачи допущены в Build (незакрытых `[ARCH]` нет). Порядок входа
  (зависимости): A (T-3935→T-3936→T-3937; T-3938; T-3939) → C (T-3944→T-3945→T-3946→T-3947→T-3948)
  → B (T-3940→T-3941→T-3942→T-3943) → D (T-3949→T-3950→T-3951→T-3952) → E → F → G → H.
- Артефакты evidence: матрица 11 строк (T-3951), инвентарная таблица ключей
  (T-3955), скриншоты S1/S3 (T-3960), F8-переиздание (T-3962).
- Следующий шаг по цепочке: **@Builder по T-3935** (Group A); Orchestrator
  чекпоинт `select_next → plan/plan_ok` с этим PLANNING_CONSISTENT-хендоффом.
