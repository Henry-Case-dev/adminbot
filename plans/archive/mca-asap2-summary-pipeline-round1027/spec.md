# mca-asap2-summary-pipeline — spec.md (спецификация @Architect)

- **Feature-ID:** `mca-asap2-summary-pipeline` (opaque, round1027)
- **Режим:** design (pre-Build); после сверки PM выдаёт `PLANNING_CONSISTENT`.
- **Нормативный источник (immutable):** `plans/current_task.md:1884–2768`
  (`# ASAP 2 / P0`, §0–§21). Ссылки — «§N:строка».
- **План PM:** `plans/features/mca-asap2-summary-pipeline/tasks.md` (T-3935…T-3963, Q1–Q8).
- **Предшественник (verified, НЕ переоткрывается):** `mca-asap-summary-hotfix`
  (прод 2.58.32, коммит `270c277`, review Approved, deployment VERIFIED). Его
  trim-костыль (`paragraphs[:cap]` + `SUMMARY_L2_TRIM_ENABLED`) **удаляется** (§16:2536–2548).
- **Risk-Level: R1** — фича перестраивает живую цепочку публикации саммари
  (T-3950/T-3951 — delivery, T-3963 — прод-деплой); ядро генерации — R2; механика/тесты — R3.
  Повышение риска: правка `web/api/routes.py` (freeze-пин `test_routes_file_unchanged`)
  или PG-DDL (сейчас Δ DDL=0) — только через эскалацию к Orchestrator.
- **Browser-Verification: REQUIRED** — miniapp меняет user-visible UI (§13:2400–2455,
  DoD-11, §17 тесты 14–16). Сценарии — раздел 5; инструмент — Playwright MCP
  (структурные behavior-checks), скриншот-инспекция — только факт визуального
  разделения секций (S1/S3).
- **Deploy:** DEPLOY REQUIRED (prod), единый релиз ≥2.58.33 (Q8).
- **ADR:** `adr-1027-10-summary-dual-circuit-recovery.md` (в этой папке) — AMEND
  ADR-1026-5 D5, ADR-1026-6 D1/D2/D5, ADR-1026-7 D2/D4/D5, ADR-1026-11 D5,
  ADR-1026-12 D2. Архивные оригиналы: `plans/archive/summary-*-round1026/`.

---

## 1. Scope / Excluded scope

**В скоупе:** двухконтурная архитектура Summary (§0:1909–1925):
(A) HYBRID — L1 semantic graph → deterministic repair → FactPackage v2 → L2
storyteller с soft-targets → article formatting → cover → sendRichMessage → plain
delivery fallback → Legacy fallback; (B) LEGACY — существующий OFF-пайплайн
(XML+RAG → System2 two-call/single → rich/plain → sendMessage chunks по
MAX_SUMMARY_PARTS), он же LEVEL-3 emergency fallback и kill-switch. Демонтаж
trim-костыля 2.58.32; переработка uncommitted same-prompt retry в correction retry;
раздельные бюджеты/настройки/секции miniapp; observability §18; verification-only
граф-память (§19).

**ВНЕ скоупа (запрещено):** переписывание GraphRAG (§19:2697–2700, §21:2761);
удаление Legacy (§0:1899, §21:2759); отключение Rich Article (§21:2760);
незакоммиченная MCA-волна round1027 (~94 файла — не трогать, кроме файлов этой фичи);
`web/api/routes.py` (вне диффа); PG-DDL (Δ DDL=0); `services/telegram_send.py` (вне диффа).

**Инварианты (§0:1929, §21:2765–2768):** настройки/лимиты Hybrid и Legacy НЕ
смешиваются ни в backend-резолве, ни в miniapp; HYBRID = качественная Article
summary, LEGACY = надёжный fallback с Telegram PARTS.

---

## 2. Ответы на Q1–Q8

### Q1 — Форма §95-контракта v2: **threads-v2 (relaxed membership), `schema_version: 2`. НЕ двухсущностная схема.**

Обоснование:
- Связующее требование §4:2097–2102 — `message_id → 0..N topics`, many-to-many,
  «это НЕ validation error». Форма `threads[]` с пересекающимися `message_ids`
  выражает это напрямую: сообщение в N темах = присутствует в N тредах; в 0 темах =
  только в `unassigned_message_ids`.
- Двухсущностная схема §4:2107–2123 («архитектурно предпочтительно») потребовала бы
  от LLM ре-эмиссии `author/timestamp/text/reply_to` — эти данные УЖЕ
  детерминированно несёт §92-payload (`services/summary_context_restore.py::build_l1_payload`,
  строки 365–391: message_id, chat_id, timestamp, author_id, display_name, text,
  reply_to_id, message_type). Ре-эмиссия = дублирование источника истины, рост
  токенов и НОВАЯ поверхность галлюцинаций (§5:2143 «нет полностью синтетических
  сообщений» — модель, переписывающая text, способна его исказить). Сущность
  **Message материализуется кодом** из payload (fragments v2, контракт (h)); LLM
  отвечает только за семантический слой (topics/facts/membership). Это и есть
  semantic graph: сторона Message — детерминированная, сторона Topic — модельная.
- Минимальный дифф: парсер/IdSpace/канонизатор/`build_l1_user_content` форму
  входа-выхода не меняют; меняются валидатор (снятие partition-инвариантов),
  промпт-канон (Q7) и FactPackage (снятие `message_in_multiple_threads`, fragments v2).
- **`unassigned_message_ids` остаётся обязательным полем** (список, может быть
  пустым): наблюдаемость §7:2216–2218 («не включать малоинформативные сообщения
  никуда») через `auto_unassigned_count`. Конфликт «id и в треде, и в unassigned»
  больше НЕ fatal (`REASON_UNASSIGNED_CONFLICT` уходит из валидатора) —
  детерминированно разрешается repair'ом: membership побеждает, id из unassigned
  удаляется (счётчик `unassigned_conflicts_resolved`).
- `schema_version: 2` — строго (валидатор принимает ровно 2; `bad_schema_version` —
  retryable-класс). Персистенции L1-выхода нет, двойная совместимость не нужна.

Точная схема и список проверок валидатора — контракт (a), раздел 3.

### Q2 — ADR-amendment «ровно 2 LLM-вызова / нет legacy-фолбэка»: **принят (ADR-1027-10 D3), новая формулировка + матрица «стадия отказа → действие».**

Текущий контракт (ADR-1026-7 D5, `plans/archive/summary-l2-writer-formatter-round1026/adr-1026-7-l2-writer-article-formatter.md`, строки 35–40; код —
`services/summary_l2_writer.py:29–30` «legacy-фолбэка НЕТ (это был бы третий вызов)»,
`services/summary_generator.py:741`) **прямо противоречит** §8:2222–2267, §9:2269–2298,
DoD-9/10/16. Владелец меняет приоритеты явно (§3:2038–2044: качество/полнота/
связность/устойчивость > стоимость). Новая формулировка:

> **Happy path — ровно 2 физических LLM-вызова (L1+L2); в успешном прогоне третий
> невозможен. Recovery-бюджет конечен и включается ТОЛЬКО когда основной контур не
> довёл результат до публикации:** ≤1 correction retry L1 (строго после deterministic
> repair, §15:2504–2520) + ≤1 L2-вызов на deterministic fallback-пакете (LEVEL-2,
> §8:2260 «и всё равно вызвать L2») + ≤2 вызова Legacy-генерации (LEVEL-3 —
> существующий System2 two-call при `SYSTEM2_SUMMARY_ENABLED=ON` либо single-call).
> **Worst case ≤5 генераций** (+ существующие транспортные retry-once внутри
> `llm_client`/`_llm_generate` — не новые сущности). «Ничего не отправить» достижимо
> только при полном отказе обоих контуров генерации И доставки (§9:2298).

Точки вызова Legacy (T-3951, §9:2295–2296 «где дешевле»): (1) hybrid выключен
kill-switch → Legacy сразу, 0 hybrid-вызовов (существующий OFF-путь байт-в-байт);
(2) L2 мёртв после LEVEL-2 → Legacy; повторный L2-retry НЕ вводится — владелец
требует correction retry только для L1 (§15), а деградировавший провайдер одинаково
ненадёжен для обоих слотов: Legacy-вызов не дороже и переключает КОНТУР (другой
промпт-канон, другой формат входа, main-модель вместо L2-слота); (3) rich И plain
доставка hybrid-текста провалились → Legacy (контент-специфичный отказ доставки);
если мёртв сам Telegram — Legacy тоже провалится, это и есть «крайне редкое
состояние» §9:2298. Полная матрица — контракт (i), раздел 3.

### Q3 — Порог «L1 практически бесполезен после repair»: **формула ниже; repair — отдельный чистый модуль `services/summary_l1_repair.py` между parse и validate.**

Формула бесполезности (величины — ПОСЛЕ repair; `ids_referenced_before` = число
различных message_id в `threads[].message_ids ∪ facts[].evidence_message_ids` ДО repair):

```
useless ⟺ topics_after == 0
        ∨ facts_total_after == 0
        ∨ unknown_ids_removed / max(ids_referenced_before, 1) > 0.5
```

Обоснование: пример владельца §6:2160–2172 (1 выдуманный id из 4 = 25%) → продолжаем;
2 из 3 (67%) → модель системно выдумывает id-пространство → output не доверяем →
correction retry → снова useless → LEVEL-2 fallback-пакет (саммари будет в любом
случае). `facts_total_after == 0` — структура без семантики: хронологический
fallback-пакет (§8:2249–2260) строго лучше. Граница «>0.5» = «практически полностью
бесполезна» (§6:2188–2189): половина evidence уцелела — структура наполовину полезна,
продолжаем (§3: качество и полнота выше перфекционизма). `topics_after == 0` —
рассказывать нечего.

Размещение: **отдельный модуль** (0 LLM, без БД/сети/часов — по образцу
`summary_l1_contract.py`), НЕ внутри валидатора: (1) repair — явный наблюдаемый шаг
(§18 `L1_REPAIR`); валидатор остаётся строгим fail-closed checker'ом уже
отремонтированной структуры; (2) порядок §15:2508–2520 (output → parse → normalize →
repair → validate → [correction retry]) читается в `run_l1` напрямую; (3) юнит-тесты
repair изолированы от контракта. Новый код причины:
`REASON_L1_USELESS_AFTER_REPAIR = "l1_useless_after_repair"` (retryable-класс,
контракт (c)).

### Q4 — Пресеты Hybrid-длины: **4000/6500/11000 (target_chars), 5/8/14 (target_paragraphs); `summary_hybrid_max_chars = 24000` — WARN-порог аномалии, НЕ ножницы.**

Реальные технические пределы (сверено с кодом `services/summary_l2_writer.py:59–66`,
`services/summary_article_formatter.py:42–46`): rich ≤ **32000** симв.
(`RICH_MAX_CHARS`, fail-closed `too_long`), ≤ **498** блоков (`MAX_PARAGRAPHS_HARD`
= 500 Bot API − 2 на H1/обложку), абзац ≤ **900**, title ≤ **200**. Оценка PM
«498×≤900» теоретически даёт 448k, но связующий предел — 32000 симв. Превышение
rich-вместимости — НЕ потеря данных: `rich_document_limits` → plain-фолбэк с ПОЛНЫМ
текстом (`_publish_rich_document`, строки 1065–1082).

| Пресет | target_chars | target_paragraphs | Запас до 32000 |
|---|---|---|---|
| casual | 4000 | 5 | 8× |
| serious (**default**) | 6500 | 8 | 4.9× |
| deep_research | 11000 | 14 | 2.9× |

Значения — середины диапазонов владельца §2:2011–2018 (3–5k/5–8k/8–14k); serious=6500
и «6–10 абзацев» дословно подтверждены примером §10:2316–2318. Все пресеты влезают в
rich-канал с ≥2.9× запасом — цифры проверены, не слепые (§2:2020–2021).

`limits.summary_hybrid_max_chars` (default **24000** = 0.75×`RICH_MAX_CHARS`; ≥2.1×
над deep_research-целью — легитимное превышение цели флагом не считается):
- `chars ≤ 24000` → ok всегда (превышение target — НЕ ошибка, §3:2069; §17 тесты 8–9);
- `24000 < chars ≤ 32000` → **публикуем** + WARN `L2_OVER_SOFT_CEILING | chars= |
  max_chars=` (никогда не обрезка);
- `chars > 32000` → существующий технический fail-closed `too_long` (§3:2063–2067:
  Telegram/API hard limit) → LEVEL-3 Legacy. Это и есть «защита от явно аномального
  ответа модели» (runaway-генерация пробивает 32000 и не публикуется как статья);
  граница аномального ответа для T-3939 = `RICH_MAX_CHARS`, не max_chars.

### Q5 — Бюджет-формула §11: **отдельные hybrid-ключи; учёт по реальному serialized prompt; margin = существующий `TOKEN_SAFETY_MULTIPLIER` (~1.15), НЕ 50%.**

Новые ключи каталога (Δ каталога, F8-переиздание): `limits.summary_hybrid_context_tokens`
(env-слой `SUMMARY_HYBRID_CONTEXT_TOKENS`, default None→30000) и
`limits.summary_hybrid_context_chars` (default 120000). Масштаб — как у текущих общих
(`_SUMMARY_CONTEXT_TOKEN_DEFAULT=30000`, `SUMMARY_MAX_CONTEXT_CHARS=120000`), но
ключи независимы: Legacy читает ТОЛЬКО `limits.summary_max_context_*`
(`summary_generator.py:525–535`), Hybrid — ТОЛЬКО новые (§11:2356; «не обрезать
данные из-за маленького legacy limit», §11:2353–2354).

Формула (tokens-режим; chars-режим симметрично, резервы в символах ×4):

```
L1:  available = safe_budget(hybrid_context_tokens)
                − count_tokens(L1 system prompt)
                − marker_overhead (§93 chunk-маркеры, существующий учёт)
                − SUMMARY_L1_OUTPUT_RESERVE_TOKENS   (env ClassVar, default 4000)
L2:  package_budget = safe_budget(hybrid_context_tokens)
                − count_tokens(L2 system prompt)
                − SUMMARY_L2_OUTPUT_RESERVE_TOKENS   (env ClassVar, default 6000)
```

`safe_budget` = деление на `models.token_safety_multiplier` (~1.15, расхождение
токенизаторов) — это и есть «разумный margin» (§11:2367–2368); 50% запаса нет.
Output reserve: L1-выход — JSON до 100 тем × 30 фактов (4000 токенов покрывает
реалистичный ответ); L2-выход — статья: типичный serious ≈ 6500 симв. ≈ 2k токенов,
deep_research ≈ 11000 ≈ 3.5k, 6000 — с запасом. Резервы — env-only ClassVar
(Δ каталога=0): инфраструктурная защита, не пользовательская настройка.

**Коррекция учёта (ключевая):** сейчас `pack_l1_input._unit`
(`summary_l1_clusterizer.py:176–178`) считает токены ТОЛЬКО текста сообщения,
игнорируя сериализованные имена полей §92-элемента (~+15–20 токенов/сообщение).
По §11:2358–2365 оценка переходит на `count_tokens(json.dumps(item,
separators=(",",":")))` — реальный сериализованный элемент; system-промпт и маркеры
вычитаются явно (формула). Это же делает `serialized_chars/serialized_tokens` в логе
FILTER (контракт (k)) честными.

**Democratic policy (§11:2344–2351):** очевидный шум снимает S1-префильтр ДО бюджета
(существующее). Вытеснение по бюджету в `pack_l1_input` меняется с «самые старые
первыми» на ключ ASC `(reply_protected, −weight, timestamp)`: `reply_protected=1`,
если сообщение — участник reply-цепочки (его `reply_to_id` указывает на сохраняемое
сообщение ИЛИ сохраняемое указывает на него); `weight` — вес S1-фильтра
(переиспользовать скоринг `summary_filter`, второй не изобретать). Последнее
сообщение сохраняется всегда (существующий инвариант §93). Итог: сначала старый
малозначимый контекст без reply-связей; reply chains и ключевые события — до
последнего. Любое вытеснение → `truncated=True` + `skipped_ids` + WARN (без
молчаливого среза, §93).

Дополнительно: `_apply_filter` (`summary_generator.py:1189–1198`) резолвит бюджет
фильтрации/восстановления ПО РЕЖИМУ (hybrid → `summary_hybrid_context_*`, off →
`summary_max_context_*`) — режим известен до фильтра (`_run:407` раньше `:451`).

### Q6 — Слой Recovery-тумблеров: **hot-ключи каталога (user-facing по §13) с env ClassVar как дефолтным слоем; Δ каталога > 0 → F8-переиздание (T-3962).**

§13:2430–2433 требует Recovery-строки в miniapp → env-only не подходит (ClassVar в UI
невидим). Каждый тумблер — PG-ключ каталога + env ClassVar-дефолт, резолв hot-first
(существующие паттерны: `_hybrid_l2_enabled:652–669`, `resolve_l1_slot`):

| Hot-ключ каталога | env ClassVar (default) | Секция miniapp |
|---|---|---|
| `flags.summary_hybrid_l2_enabled` (существующий; в каталог впервые) | `SUMMARY_HYBRID_L2_ENABLED` (True) | HYBRID — «[✓] Hybrid Summary enabled» |
| `flags.summary_hybrid_l1_repair_enabled` (новый) | `SUMMARY_L1_REPAIR_ENABLED` (True) | HYBRID → Recovery |
| `flags.summary_hybrid_l1_retry_enabled` (новый; uncommitted `SUMMARY_L1_RETRY_ENABLED` остаётся env-слоем) | `SUMMARY_L1_RETRY_ENABLED` (True) | HYBRID → Recovery |
| `flags.summary_legacy_fallback_enabled` (новый) | `SUMMARY_LEGACY_FALLBACK_ENABLED` (True) | LEGACY — «[✓] Legacy fallback enabled» |

`flags.summary_legacy_fallback_enabled` — ЕДИНСТВЕННЫЙ ключ «Fallback to Legacy»
(строка Recovery §13:2433 и чекбокс §13:2439 — одна сущность, дубль в двух секциях
запрещён §13:2451–2452; в Recovery-подсекции HYBRID рендерятся repair+retry, а
описание retry-флага даёт ссылку «полный отказ Hybrid → Legacy: см. секцию LEGACY
SUMMARY FALLBACK»). Скетч §13:2409 — «пример» (композиция, не побайтовая раскладка).
OFF fallback-флага → LEVEL-3 не выполняется, hybrid-провал терминален (существующие
§106-коды) — осознанный аварийный режим. `SUMMARY_L2_TRIM_ENABLED` — УДАЛЯЕТСЯ
(контракт (e)), не мигрирует. AMEND ADR-1026-12 D2: запрет «UI-селектора Legacy↔Hybrid»
сужается до запрета штатного переключателя режимов; видимый чекбокс «Hybrid Summary
enabled» — аварийный kill-switch, выставленный в UI по прямому требованию §13;
резолв per-chat → hot → env сохраняется байт-в-байт (`_chat_limit`).

### Q7 — Канон L1/L2-промптов: **новые каноны ниже; PREV_*/ROLLBACK-механика ADR-1013-3 сохраняется (снимки `PREV_*_R1027`).**

Точные тексты — контракт (l), раздел 3. Совместимость hard-контракта §95-v2 с «не
заставлять выбирать одну тему» (§4:2125): правила «ТОЛЬКО существующие message_id»,
«evidence из своей темы», лимиты 100/30/1000, ≤200/≤500 — сохраняются; правило «один
id ровно в одной теме» — удаляется и заменяется явным разрешением many-to-many +
разрешением не покрывать всё. Длина передаётся ТОЛЬКО в L2 (§3:2046–2047) —
детерминированным блоком в user-контенте (не интерполяцией канона): hot-правки
PG-канона не могут сломать подстановку чисел.

### Q8 — Релиз: **единый релиз 2.58.33 (не ниже), одним feat-коммитом после Reviewer Approved + отдельный docs-коммит (конвенция проекта); partial отдельно НЕ коммитится.**

Локальный uncommitted пин `APP_VERSION = "2.58.33"` (дифф `config/settings.py`)
никогда не деплоился (прод = 2.58.32) — номер валиден для единого ASAP-2-релиза
(§ «не ниже 2.58.33»). Промежуточный релиз partial-retry запрещён §16:2550–2554
(same-prompt retry вне correction-семантики — не фикс). Порядок: Build → Reviewer
Approved (binding к дереву) → один feat-коммит (код+тесты+версия-пины) → docs-коммит
(планы/ADR) → reconcile → Orchestrator `delivery → reconcile → archive` → DevOps
(`git pull --ff-only`, рестарт `admin_bot`). Финальный номер подтверждает Orchestrator.

---

## 3. Контракты

### (a) L1 v2 — semantic graph, many-to-many (§4, §5)

JSON-контракт выхода L1 (`schema_version: 2`):

```json
{
  "schema_version": 2,
  "threads": [
    {"thread_id": "thread_001", "topic": "≤200, одна строка",
     "message_ids": [101, 102],
     "facts": [{"text": "≤500, атомарный", "evidence_message_ids": [101, 102]}]}
  ],
  "unassigned_message_ids": [103],
  "response_mode": "serious",
  "cover_prompt": "english visual prompt ≤300"
}
```

- Top-level ровно 5 ключей (лишние → `unknown_field`); thread — 4; fact — 2.
- `message_ids` одного треда и разных тредов МОГУТ пересекаться (many-to-many);
  дубли внутри треда детерминированно дедуплицируются. Пересечение — НЕ ошибка;
  `REASON_MESSAGE_IN_MULTIPLE_THREADS` **удаляется** из `summary_l1_contract.py`
  (строки 85, 377–384) и `summary_fact_package.py` (строки 88, 504–510).
- `unassigned_message_ids` обязателен (возможен пустой); auto-unassigned для
  неупомянутых payload-id сохраняется (`auto_unassigned_count`).
- Служебные `response_mode`/`cover_prompt` — тот же JSON, нормализаторы
  `service_fields` без изменений; `response_mode` L1 больше НЕ управляет длиной
  статьи (только observability) — длина из конфига (контракт (f)).

Валидатор (`validate_l1_response`) проверяет ИСЧЕРПЫВАЮЩИЙ список (§5:2138–2143):
1. JSON-структура/типы/field-sets (parse-слой: `invalid_json`/`empty_response`/`bad_type`/`unknown_field`);
2. `schema_version == 2` (`bad_schema_version`);
3. каждый `message_id` (threads/unassigned) существует в IdSpace payload — `unknown_message_id`
   (defense-in-depth: после repair недостижим);
4. `thread_id`-паттерн, `topic`/`fact.text` — длина/однострочность/без системных
   тегов/markdown-заголовков (`invalid_thread_id`/`invalid_topic`/`invalid_fact`);
5. facts имеют ≥1 evidence после repair (`evidence_message_ids` непустой; fact без
   evidence удаляет repair, валидатор видит уже чистые данные);
6. жёсткие лимиты контракта: ≤100 тем, ≤30 фактов/тема, ≤1000 фактов всего
   (`too_many_threads`/`too_many_facts`/`too_many_facts_total`) — fail-closed, НЕ retryable;
7. детерминированная канонизация: дедуп, ASC `(timestamp, message_id)`,
   перенумерация `thread_001…`, дедуп фактов с объединением evidence,
   байт-идентичность двойного прогона.

НЕ являются ошибками (§5:2145–2148): реплика в 0..N темах; один участник в
нескольких темах; overlapping chronology; сообщение в теме и отсутствие покрытия
всех сообщений. Дедупликация пересказов — СЕМАНТИЧЕСКИ в L2 (контракт (l)), не
запретом связей.

### (b) Deterministic repair pipeline (§6, §15)

Модуль `services/summary_l1_repair.py` (новый, чистый: 0 LLM/БД/сети/часов).
Вход: `(data: dict, id_space: IdSpace)` — результат `parse_l1_response` при
`data is not None`. Выход: `(repaired: dict, report: RepairReport)`. Шаги
(детерминированный порядок):

1. `threads[].message_ids`: удалить id, отсутствующие в IdSpace → `unknown_ids_removed += 1` (за вхождение);
2. `facts[].evidence_message_ids`: удалить неизвестные id (в `unknown_ids_removed`);
   evidence-id, существующий в IdSpace, но НЕ входящий в `message_ids` своего треда →
   ДОБАВИТЬ в `message_ids` (membership expansion: evidence implies relation) →
   `evidence_membership_added += 1` (не ошибка, `REASON_EVIDENCE_NOT_IN_THREAD` уходит
   из валидатора в repair);
3. fact с пустым `evidence_message_ids` после шагов 1–2 → удалить fact → `facts_removed += 1` (§6:2178);
4. thread с пустыми `message_ids` И пустыми `facts` → удалить thread → `topics_removed += 1` (§6:2179);
   thread с сообщениями, но без фактов — СОХРАНЯЕТСЯ (хронология — материал для L2);
5. `unassigned_message_ids`: удалить неизвестные id (`unknown_ids_removed`); удалить
   id, присутствующие в любом треде → `unassigned_conflicts_resolved += 1`
   (`REASON_UNASSIGNED_CONFLICT` больше не fatal);
6. посчитать `overlapping_topic_memberships` = число различных id, встречающихся в ≥2
   тредах (информационно, §18);
7. verdict `useless` по формуле Q3; `useless_reason` ∈ {`no_topics`, `no_facts`, `mass_unknown_ids`}.

RepairReport-поля (все int/bool, R17-safe): `unknown_ids_removed`, `facts_removed`,
`topics_removed`, `evidence_membership_added`, `unassigned_conflicts_resolved`,
`overlapping_topic_memberships`, `topics_before/after`, `facts_before/after`,
`useless`, `useless_reason`. Ремонт НЕ мутирует вход (копия).

Размещение в потоке (`run_l1`, §15:2508–2520): `call → parse → [repair → validate] →
(correction retry при retryable-причине, ≤1) → итог`. Kill-switch
`flags.summary_hybrid_l1_repair_enabled` (Q6): OFF → repair пропускается, валидатор
v2 работает как есть (unknown id → fatal `unknown_message_id` — прежняя строгость
 minus partition-правила). `useless` → статус `invalid`, reason
`l1_useless_after_repair`. Лог — контракт (k) `L1_REPAIR`.

### (c) Correction retry (§15, §16-2.58.33) — ТОЛЬКО после repair

Порядок строго §15: LLM output → parse → normalize → **deterministic repair** →
validate → «всё ещё действительно сломано» → **ровно одна** вторая попытка с
текстом причины в user-контенте. Retryable-набор (reason ПОСЛЕ repair+validate):
`invalid_json`, `empty_response`, `bad_type`, `unknown_field`, `bad_schema_version`,
`invalid_thread_id`, `invalid_topic`, `invalid_fact`, `l1_useless_after_repair`,
`unknown_message_id` (defense: repair должен был спасти — retry как последний шанс).
НЕ retryable: `LLMError`/`LLMTimeoutError` (транспорт, error_result как в partial),
`too_many_threads`/`too_many_facts`/`too_many_facts_total` (переполнение контракта —
в LEVEL-2), `id_space_mismatch`/`internal_error` (наши баги). 
`message_in_multiple_threads` — НЕ retry reason и вообще больше не существует (§15:2501–2502).

Correction-блок второй попытки — append к исходному user-контенту (system-канон не
дублируется):

```
ПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: <reason_code>.
<детализация по классу:>
- unknown ids: неизвестные message_id [id1, id2, … до 20 шт]. Используй ТОЛЬКО
  message_id из входных данных. Не выдумывай идентификаторы.
- useless after repair: после ремонта не осталось пригодных тем/фактов (причина:
  <useless_reason>). Верни структуру, опирающуюся только на реальные message_id.
- invalid json / bad schema: верни СТРОГО валидный JSON-объект по схеме
  (schema_version: 2), без текста вокруг.
Верни исправленный JSON.
```

Логи: WARN `L1_CORRECTION_RETRY | run_id | chat_id | attempt=1/2 | reason=<код>`
(только код и числа, НЕ списки id — R17); `L1_COMPLETE` получает `attempts=1|2`
(переиспользование partial-кода). Kill-switch `flags.summary_hybrid_l1_retry_enabled`
(hot-first, env `SUMMARY_L1_RETRY_ENABLED` default ON): OFF → single-shot.

**Переиспользование uncommitted partial** (`git diff services/summary_l1_clusterizer.py`):
- СОХРАНИТЬ: структуру цикла `for attempt in range(1, max_attempts+1)`; plumbing
  `attempts` в `_log_complete`/`L1_COMPLETE`; отсутствие retry на
  LLMError/LLMTimeoutError и too_many_*; паттерн kill-switch-чтения; overall-докстринг
  (обновить формулировки).
- ПЕРЕПИСАТЬ: `_RETRYABLE_REASONS` (убрать `message_in_multiple_threads`,
  `unknown_message_id`-как-триггер-до-repair → перенести в post-repair набор Q(c);
  добавить `empty_response`, `bad_schema_version`, `invalid_thread_id`,
  `invalid_topic`, `l1_useless_after_repair`); вставить repair-шаг между parse и
  validate; same-prompt `continue` заменить на сборку correction-сообщения (новые
  messages второй попытки = system + исходный user + correction-блок); WARN-строку
  `L1 retry` → `L1_CORRECTION_RETRY`; `SUMMARY_L1_RETRY_ENABLED`-резолв →
  hot-first (`flags.summary_hybrid_l1_retry_enabled`).
- Тесты `tests/test_summary_asap2_l1_retry_round1027.py` (12): переработать под
  correction-семантику (тест `message_in_multiple_threads → retry` инвертировать:
  такой ответ теперь VALID без retry; unknown-id тесты → через repair; добавить
  assertion'ы на текст correction-блока и repair-первенство).

### (d) MAX_SUMMARY_PARTS — строго Legacy (§1)

Семантика (единственная): «максимальное число Telegram sendMessage частей, на которые
можно разбить длинный legacy summary»; `max_symbols = parts × 4000 − 200` — бюджет
legacy-промпта (`summary_generator.py:547–548`, backward-compatible, не меняется).
НЕ: число абзацев/тем, длина Hybrid Article, лимит L1/L2/sendRichMessage (§1:1956–1962).

**Полное удаление из Hybrid** (§1:1964–1976): `resolve_l2_max_paragraphs()`
(`summary_l2_writer.py:236–250`) — удалить; `cap`/`max_paragraphs` в `run_l2`
(строки 771–806, 868–881) — удалить (параметр `max_paragraphs` из сигнатуры уходит;
`summary_test_run.py` его не передаёт — проверка grep'ом); комментарий
«Совместимость с limits.max_summary_parts» (строка 64) и `MAX_PARAGRAPHS_DEFAULT` —
удалить; hybrid validation по параметру — отсутствует после удаления cap-ветки
(остаётся только `MAX_PARAGRAPHS_HARD=498`); hybrid prompt logic на параметре —
заменяется length-блоком контракта (f) из НОВЫХ hybrid-ключей.
rg-инвариант после Build: `max_summary_parts`/`MAX_SUMMARY_PARTS` встречается только
в legacy-контурах `summary_generator.py` (промпт-бюджет + send-кап ниже),
`config/settings.py:938`, `services/param_catalog.py` (legacy-группа) и тестах legacy-семантики.

**Send-time кап legacy-доставки** (§1:1947–1954 «parts=1 → одно Telegram сообщение»;
§17 тест 2): legacy plain-доставка (`_send_chunked`/`_publish_plain_document` при
вызове ИЗ legacy-контура, `_send_streaming`-остаток) отправляет не более
`MAX_SUMMARY_PARTS` чанков (чанки — существующие, по границам абзацев ≤4096).
Избыток НЕ теряется молча: WARN `LEGACY_CHUNKS_CAPPED | run_id | chat_id |
chunks_total= | chunks_sent=`. Реализация — явный параметр `max_chunks: int | None`
по цепочке доставки: legacy-вызывающий передаёт резолв parts (hot
`limits.max_summary_parts` → env), hybrid-вызывающий передаёт `None` (без капа —
hybrid-plain §105 доставляет ПОЛНЫЙ текст чанками, `chunk_plain_blocks`). Rich-путь
Legacy (article) капом не ограничен (sendRichMessage — не sendMessage, §1:1935–1937).
Prompt-бюджет + send-кап вместе = «старая семантика» из §1: модель просят уложиться
в ~parts×4000, а доставка гарантирует ≤ parts сообщений.

Backward-compat hot-ключа (§14:2482–2484): env-имя `MAX_SUMMARY_PARTS` и pg-ключ
`limits.max_summary_parts` НЕ переименовываются; в каталоге/UI — явная пометка
Legacy (контракт (j)). Прод-значение **6** (выставлено ASAP-1-деплоем под trim)
после удаления trim получает чистую legacy-семантику: legacy-саммари до ~23800
симв. ≈ до 6 Telegram-сообщений — значение разумное, **рекомендация: оставить 6**
(обсуждение значения: 1 — коротко, 3 — средне, 6 — полно; §21 запрещает повышать
его РАДИ Hybrid — здесь оно на Hybrid не влияет вовсе).

### (e) Удаление trim-костыля 2.58.32 (§16)

Удалить (полностью, не «оставить выключенным» — §16:2536–2545):
- `services/summary_l2_writer.py`: `_trim_document_for_publication` (строки 566–613),
  trim-ветку в `run_l2` (строки 869–881), `REASON_TRIMMED_FOR_PUBLICATION`
  (строки 97–99), метрики `trimmed_for_publication`/`paragraphs_before`/
  `paragraphs_dropped_count`, `trimmed=` в `L2_COMPLETE` + WARN-строку
  `L2 trimmed_for_publication` (строки 724–749);
- `config/settings.py`: ClassVar `SUMMARY_L2_TRIM_ENABLED` (строки ~1092–1101);
- NOTE-аннотацию hotfix в `tests/test_tool_coordinator_round1026.py` (строка 663).

Жёсткие тех-лимиты §99 (title≤200, абзац≤900, ≤498 блоков, rich≤32000) СОХРАНЯЮТСЯ
fail-closed — это не trim (§3:2063–2067). Тесты, защищавшие trim, переписать
(§16:2547–2548): `tests/test_summary_asap_hotfix_round1027.py` trim-сценарии (а)/(в)
→ инвертировать в инварианты «превышение мягкой цели не режет и не отбраковывает»
(§17 тесты 8–9); `tests/test_summary_l2_writer.py::test_too_many_paragraphs*`
(trim ON/OFF, `max_paragraphs=3`) → удалить/заменить на hard-498-сценарий;
`tests/test_summary_publish_integration_round1026.py:1123` (assertion
max_summary_parts×4000 в hybrid-контексте) → перевести на legacy-семантику
(legacy-контур) и hybrid-инвариант «полная статья при parts=1». Байт-в-байт история
тестов не сохраняется — владелец прямо требует переписать. Граф-сценарии того же
файла (ASAP-1 §3-г) переносятся/сохраняются для T-3957.

### (f) Hybrid-настройки длины (§2, §10)

Точные имена каталога (§2:1992–2001, §14:2476–2480) и env-слои:

| Hot-ключ | env ClassVar | Default | Семантика |
|---|---|---|---|
| `limits.summary_hybrid_response_mode` | `SUMMARY_HYBRID_RESPONSE_MODE` | `serious` | пресет casual/serious/deep_research |
| `limits.summary_hybrid_target_chars` | `SUMMARY_HYBRID_TARGET_CHARS` | `0` (= по пресету) | мягкий ориентир длины статьи в L2-промпт |
| `limits.summary_hybrid_target_paragraphs` | `SUMMARY_HYBRID_TARGET_PARAGRAPHS` | `0` (= по пресету) | мягкий ориентир числа абзацев, НЕ hard cap, НЕ validator condition (§10:2330–2332) |
| `limits.summary_hybrid_max_chars` | `SUMMARY_HYBRID_MAX_CHARS` | `24000` | широкий safety ceiling = WARN-порог аномалии (Q4); никогда не механическая обрезка |

Пресеты (модуль-константы, например `summary_l2_writer.PRESETS`): casual →
(target_chars 4000, target_paragraphs 5); serious → (6500, 8); deep_research →
(11000, 14). Резолв: явное значение ключа >0 побеждает пресет; иначе пресет по
`response_mode`. Резолв режима: per-chat → hot → env → default `serious`
(существующий `_chat_limit`-паттерн).

**Конфликт с L1 `response_mode` решён:** конфигурационный режим ПОЛЬЗОВАТЕЛЯ
побеждает; `response_mode` из L1-JSON остаётся в контракте (observability +
обложка-стиль не затрагиваются), но длину больше не определяет — существующий
`_DETAIL_PARAGRAPH_HINT`/`detail` в `build_l2_input` заменяется length-блоком
(контракт (l)). Обоснование: §13 отдаёт выбор режима пользователю (miniapp
«Mode: Casual / Serious / Deep research»); авто-детект модели не может переопределить
явную настройку владельца чата.

`max_chars` в промпт НЕ передаётся (это post-hoc guard, не цель); в промпте — только
target (§3:2046–2047: все требования к длине — в последнюю LLM-фазу как soft target).
Валидатор НИКОГДА не сравнивает результат с target_chars/target_paragraphs
(§3:2071–2076 «ожидалось 6, получено 7 → НЕ invalid»); единственные hard-проверки
длины — технические §99 (200/900/498/32000) + WARN-полоса 24000–32000 (Q4).

### (g) Бюджеты Legacy/Hybrid (§11) — см. Q5

Разделение полное: Hybrid (L1-упаковка `pack_l1_input`, FactPackage
`resolve_fact_package_budget`, S1/S2-фильтр в hybrid-режиме) читает ТОЛЬКО
`limits.summary_hybrid_context_tokens/_chars`; Legacy (OFF-ветка `_run:525–535`,
S1/S2 в off-режиме) — ТОЛЬКО `limits.summary_max_context_tokens/_chars`. Формула,
margin, output reserve, serialized-учёт и democratic eviction — Q5. Ключи
`resolve_fact_package_budget`/`resolve_l1_budget` переходят на новый резолвер
`resolve_hybrid_context_budget()` (единая точка, hot-first + per-chat).

### (h) FactPackage v2 → L2 payload (§12)

`services/summary_fact_package.py`: `SCHEMA_VERSION = 2`; фрагмент и хронология
несут полный авторский контекст из §92-payload (источник — `build_l1_payload`,
поля уже доступны; сейчас `_select_fragments:233–257` берёт только message_id+text —
исправить):

```json
"fragments": [{"message_id": 101, "author_id": 777, "display_name": "Имя",
               "timestamp": 1727000000, "reply_to_id": 100, "text": "…"}],
"chronology": [{"message_id": 101, "timestamp": 1727000000, "topic_ids": ["thread_001","thread_003"]}]
```

- `topic_ids` — many-to-many карта (все треды, содержащие сообщение; детерминированно
  из payload L1); `reply_to_id` — null/отсутствует, если ответа нет.
- НЕ тащим (§12:2397 «всю внутреннюю техническую metadata не нужно»): `chat_id`
  (неявен), DB `id` (пространство §93 — только TG message_id), `message_type`,
  `mentions`, `skipped_ids`, `budget`, `service` (изолированы и сейчас), веса фильтра.
- `build_l2_input` (`summary_l2_writer.py:283–336`) пробрасывает новые поля fragments
  и chronology verbatim; дедупликация фрагментов между тредами НЕ выполняется
  (локальность контекста важнее экономии — §3:2038–2044; пределы — существующие
  `MAX_FRAGMENTS_PER_THREAD=30`/`MAX_FRAGMENTS_TOTAL=500` + бюджет (g));
  семантическая дедупликация повторяющихся событий — задача L2-промпта (контракт (l)).
- Пересечение membership больше не рвёт сборку: удалить fail-closed ветку
  `REASON_MESSAGE_IN_MULTIPLE_THREADS` (`summary_fact_package.py:504–510`);
  `unassigned_conflict` — только defense-in-depth (repair чинит раньше).
- Бюджетное усечение пакета (fragments → description → целые темы) сохраняется;
  порядок «старые первыми» остаётся (это не democratic eviction входа L1 — здесь
  уже тематизированный материал).

### (i) Fail-soft: LEVEL-1/2/3 + цепочка доставки (§8, §9)

Availability invariant (§8:2233–2237): «если в исходном чате есть пригодный
материал, одна неидеальная стадия LLM не должна приводить к отсутствию саммари».

**LEVEL-1** = repair + correction retry (контракты (b)/(c)) внутри `run_l1`.

**LEVEL-2** — deterministic fallback FactPackage (0 LLM): новый билдер
`build_fallback_package(payload_items, *, budget, correlation_id)` в
`services/summary_fact_package.py`. Собирается из filtered source messages (§92,
после S1/S2) когда L1 unusable (любая причина: invalid после retry, error/timeout,
useless, too_many_*, empty): один thread `thread_001` c `name="Общий ход обсуждения"`
(§8:2252), `description=""`, `facts=[]`, `chronology` = ВСЕ source messages ASC с
`topic_ids=["thread_001"]`, `fragments` = все сообщения (author+text+reply links,
контракт (h)) c существующими капами/бюджетом → статус `ok`/`truncated`
(обязан проходить deliverability-гейт `run_l2:792–797`). Пустой payload (0 сообщений
после фильтра) → пакет не строится → не failure, а существующая empty-семантика.
Затем **L2 вызывается в любом случае** (§8:2260). Обложка для fallback-пути —
детерминированная: существующий `_derive_fallback_cover_prompt` (0 LLM, гейт
`SUMMARY_COVER_FALLBACK_ENABLED`) из заголовка/первой фразы документа — DoD-14
сохраняется и на деградированном пути.

**LEVEL-3** — Legacy Summary (§8:2262–2266, §9): полный существующий legacy-пайплайн
(OFF-ветка `_run:484–618`: XML+RAG+System2 two-call/single+cover+rich/plain+chunks
по MAX_SUMMARY_PARTS). Реализация — извлечь тело OFF-ветки в
`_run_legacy_pipeline(chat_id, rows, xml_rows, focus, trigger_message_id,
correlation_id, ctx, *, max_parts, skip_memorize)`; OFF-режим вызывает его как
раньше (байт-в-байт поведение), LEVEL-3 — тот же метод с уже готовыми
`rows`/`xml_rows` (окно НЕ перечитывается, фильтр НЕ перезапускается,
`memorize_facts` НЕ дублируется — `skip_memorize=True`, fire-and-forget уже сделан
в hybrid-ветке `_run:475–480`). Legacy-функции `_llm_generate`/`_generate_two_call`
НЕ удаляются и НЕ ломаются (DoD-10). Гейт: `flags.summary_legacy_fallback_enabled`
(Q6); OFF → терминальный SUMMARY_FAILED (аварийный режим).

**Матрица «стадия отказа → действие»** (единый источник для T-3950/T-3951/T-3952;
копируется в evidence T-3951):

| # | Отказ | Действие | Доп. LLM-вызовы |
|---|---|---|---|
| 1 | Hybrid kill-switch OFF | Legacy-пайплайн сразу (существующий OFF-путь) | ≤2 (legacy) |
| 2 | Окно пустое (0 rows) | `_UX_EMPTY`, SUMMARY_COMPLETE empty (существующее) — НЕ failure | 0 |
| 3 | L1 invalid после repair (+ retry если включён) / error / timeout / empty / useless / too_many_* | LEVEL-2: fallback-пакет → L2 | ≤1 (L1 retry) +1 (L2) |
| 4 | L1 slot не резолвится (L1SlotError) | то же, что 3 (LEVEL-2) | +1 (L2) |
| 5 | FactPackage not deliverable при usable L1 (defensive, не ожидается после (h)) | LEVEL-2: пересборка fallback-пакета → L2 | +1 (L2) |
| 6 | L2 unusable (invalid/error/empty: invalid_json, quote_attribution, too_long, transport…) — и для обычного, и для fallback-пакета | LEVEL-3 Legacy (L2-retry НЕ вводится — Q2) | ≤2 (legacy) |
| 7 | Cover-генерация упала/недоступна | plain-публикация hybrid-текста (существующее `_plain_fallback reason=cover_*`) — НЕ legacy | 0 |
| 8 | sendRichMessage fail / rich-лимиты не влезают | plain sendMessage полного текста (существующее, `_publish_plain_document`) | 0 |
| 9 | plain-доставка hybrid-текста fail (HTML и text-даунгрейд) | LEVEL-3 Legacy (§9:2289–2291) | ≤2 (legacy) |
| 10 | Непредвиденное исключение в hybrid-ветке, ничего не опубликовано | LEVEL-3 Legacy (best-effort, own try) | ≤2 (legacy) |
| 11 | Legacy тоже провалился | SUMMARY_FAILED + UX-сообщение (существующие `_send_ux`), code=`SUMMARY_GENERATION_FAILED` | — |

Guard двойной публикации: флаг `published` в `_run_hybrid_l2` — LEVEL-3 входим
ТОЛЬКО если ничего не отправлено (rich-успех + позднее исключение → НЕ fallback).

**Цепочка доставки (§9:2281–2293):** Hybrid semantic pipeline → Hybrid article →
sendRichMessage → fail → Hybrid plain sendMessage → fail/unavailable → Legacy →
sendMessage chunks по MAX_SUMMARY_PARTS (send-кап контракта (d)).

**§106-коды/UX (T-3952):** `SUMMARY_GENERATION_FAILED` — ТОЛЬКО когда и Legacy
провалился (строка 11); `RICH_MESSAGE_SEND_FAILED`/`TEXT_FALLBACK_FAILED` — коды
соответствующих пролётов цепочки (TEXT_FALLBACK_FAILED в hybrid больше не
терминален — за ним LEVEL-3); `L2_SKIPPED reason=l1_not_usable` — больше не
терминальное «не публикуем»: заменяется переходом в LEVEL-2 (новое событие
`L1_FALLBACK_PACKAGE`). Промежуточные коды не должны порождать `_send_ux`-сообщения
об ошибке, пока цепочка продолжает работать (UX — только строка 11 либо существующие
исключения транспорта). Тесты §106-кодов (`test_summary_publish_integration_round1026.py`,
`test_summary_deploy_round1026.py` scenario_07 и подобные fail-closed-сценарии)
обновить под новую семантику.

### (j) Miniapp / param catalog (§13, §14)

**Секции.** Модуль «Саммаризация» (`web/app.js` TABS `mod_summary`, строки 85–93)
получает две НОВЫЕ workspace-вкладки (прецедент — вкладка 'prep', маппинг по id
групп в `workspaceGroupTab:6282–6289` независимо от категории):
- **'hybrid' — «HYBRID SUMMARY»**: группы `flags_summary_hybrid`,
  `models_summary_hybrid`, `limits_summary_hybrid`;
- **'legacy' — «LEGACY SUMMARY FALLBACK»**: группы `flags_summary_legacy`,
  `limits_summary_legacy`.

Существующие общие группы (`limits_summary` — throttle/timezone/chunk_delay/
compress/retry-pause/stream-интервалы/max_message_chars; `limits_summary_filter` →
'prep'; `flags_module_summary`/`flags_summary`) остаются вне двух секций — это
общая инфраструктура саммари, не hybrid- и не legacy-специфика (правило
§13:2451–2452 не нарушается: ни ОДИН hybrid-ключ не в legacy-блоке и наоборот).

**Состав секций (точный):**

HYBRID SUMMARY:
- `[✓] Hybrid Summary enabled` — `flags.summary_hybrid_l2_enabled` («Основной
  пайплайн саммари: статья с обложкой. Выключение — аварийный переход на Legacy.»);
- Model/Provider: `models.summary_l1_base_url`, `models.summary_l1_model_name`,
  `keys.summary_l1_api_key` (secret), `models.summary_l2_base_url`,
  `models.summary_l2_model_name`, `keys.summary_l2_api_key` (secret) — hot-ключи
  УЖЕ читаются `resolve_l1_slot`/`resolve_l2_slot` (forward-compatible), теперь
  каталогизированы; описания: «Пусто — наследуется основная модель»;
- Context: `limits.summary_hybrid_context_tokens` («Сколько слов-кусочков контекста
  видит Hybrid-пайплайн»), `limits.summary_hybrid_context_chars`;
- Article length: `limits.summary_hybrid_response_mode` (селектор casual/serious/
  deep_research), `limits.summary_hybrid_target_chars` («Мягкий ориентир длины
  статьи; 0 — по режиму»), `limits.summary_hybrid_target_paragraphs` («Мягкий
  ориентир числа абзацев; не жёсткий лимит»), `limits.summary_hybrid_max_chars`
  («Широкий аварийный потолок наблюдения; статья не обрезается по нему»);
- Recovery: `flags.summary_hybrid_l1_repair_enabled` («Локальный ремонт ответа L1
  вместо отбраковки»), `flags.summary_hybrid_l1_retry_enabled` («Одна исправляющая
  повторная попытка L1 с указанием ошибки; полный отказ Hybrid → Legacy: см. секцию
  LEGACY SUMMARY FALLBACK»).

LEGACY SUMMARY FALLBACK:
- `[✓] Legacy fallback enabled` — `flags.summary_legacy_fallback_enabled` («Если
  Hybrid не смог, пользователь всё равно получит обычное текстовое саммари»);
- Legacy max context: `limits.summary_max_context_tokens` (SUMMARY_MAX_CONTEXT_TOKENS),
  `limits.summary_max_context_chars` (SUMMARY_MAX_CONTEXT_CHARS) — перенос группы
  `limits_summary` → `limits_summary_legacy`, ретитл с пометкой «Legacy»;
- `limits.max_summary_parts` (MAX_SUMMARY_PARTS) — перенос группы; **точная подпись
  (§13:2445–2449):** «Максимальное число обычных Telegram-сообщений, на которые
  может быть разбит Legacy Summary. Не влияет на Hybrid Article.»

Legacy model/provider отдельного слота в коде НЕТ (Legacy работает на основной
модели `models.llm_*`) — новый слот НЕ создаётся (scope creep, §14 не требует);
в legacy-секции этот факт закрывается описанием группы («Legacy использует основную
модель — вкладка LLM Провайдеры»).

**Имена (§14:2470–2484):** legacy — `limits.max_summary_parts` (старое имя
сохранено, backward-compat, явная Legacy-пометка в title/описании); hybrid —
`limits.summary_hybrid_*` (все 6 новых), `flags.summary_hybrid_*`,
`models/keys.summary_l1_*`/`summary_l2_*`. Hot-резолв (`hot.get`/`resolve_chat_limit`/
`_chat_limit`) не перетекает между контурами (контракт (g)); результат инвентаризации
ВСЕХ summary-ключей — таблица в `evidence.md` (T-3955).

**Δ каталога (для T-3962/F8):** REGISTRY 473 → **489** (+16: 4 flags + 6 models/keys
+ 6 limits); GROUPS 102 → **107** (+5: `flags_summary_hybrid`,
`models_summary_hybrid`, `limits_summary_hybrid`, `flags_summary_legacy`,
`limits_summary_legacy`); `_TAB_BY_GROUP` 100 → **105**; TAB_RULES **21** (без
изменений — правило mod_summary правится in-place); 3 существующих ключа меняют
группу (перенос, не дельта). F8-переиздание: `plans/docs/param-registry-round1025.meta.md`
(счётчики + APP_VERSION), `param-registry-round1025.tsv`,
`plans/reports/round1025_f8_config_diff.md`, `test_round1025_f8_registry`. CSP/
zero-build механика miniapp сохраняется; `web/api/routes.py` вне диффа.

### (k) Observability (§18) — точные события и поля

Принцип: существующие имена событий S7/S8 НЕ переименовываются (их пинят
`test_summary_logging_runid.py`, JS-харнесс log viewer, S8-адаптер); §18-скелет
обеспечивается аддитивными полями + тремя новыми событиями + документированным
маппингом. Все поля — числа/коды/id (R17); **raw messages, тексты модели, секреты,
API-ключи в логи не попадают НИКОГДА** (§18:2684); списки unknown-id — только в
correction-промпт, в логах — счётчики.

| §18-имя | Фактическое событие | Поля (жирным — новые) |
|---|---|---|
| SUMMARY_START | `SUMMARY_START` (существ.) | run_id, chat_id, mode, manual, source_count, has_trigger |
| FILTER | `FILTER_START`/`FILTER_COMPLETE` (существ.) | + **messages_before**, **messages_after**, **serialized_chars**, **serialized_tokens** (по serialized §92-оценке Q5); существующие source_count/saved_count/restored_count/drop_percent/status/duration_ms сохраняются |
| L1_START | `L1_START` (существ.) | без изменений |
| L1_PARSE | **НОВОЕ** `L1_PARSE` | run_id, chat_id, attempt, parse_status (ok/empty_response/invalid_json), **raw_chars** |
| L1_REPAIR | **НОВОЕ** `L1_REPAIR` | run_id, chat_id, attempt, **overlapping_topic_memberships**, **unknown_ids_removed**, **facts_removed**, **topics_removed**, evidence_membership_added, unassigned_conflicts_resolved, topics_before/after, facts_before/after, **useless** (0/1), useless_reason |
| (retry) | **НОВОЕ** `L1_CORRECTION_RETRY` (WARN) | run_id, chat_id, attempt=1/2, reason=<код> |
| (L1 итог) | `L1_COMPLETE` (существ.) | + attempts (из partial); threads/facts/auto_unassigned/skipped/truncated/status/invalid_reason/duration_ms |
| FACT_PACKAGE | `FACT_PACKAGE_START`/`FACT_PACKAGE_COMPLETE` (существ.) | + **topics=** (дубль threads= на переходный период), **messages=** (уникальные id в тредах); **НОВОЕ** `L1_FALLBACK_PACKAGE` (WARN): run_id, chat_id, reason=<код L1-отказа>, fragments=, chronology= |
| L2_START | `L2_START` (существ.) | + **response_mode**, **target_chars**, **target_paragraphs**; paragraphs_hint сохраняется |
| L2_RESULT | `L2_COMPLETE` (существ.; §18-алиас документируется) | + **chars**; существующие tokens_in/out, paragraphs, title_len, quote_unverified, ids_stripped, emphasis_dropped, status, invalid_reason, duration_ms; `trimmed=` — УДАЛЯЕТСЯ (контракт (e)); WARN `L2_OVER_SOFT_CEILING` (chars, max_chars) при 24000<chars≤32000 |
| ARTICLE_FORMAT | `FORMAT_START`/`FORMAT_COMPLETE`/`FORMAT_ERROR` (существ.) | без изменений |
| COVER | `COVER_START`/`COVER_COMPLETE`/`COVER_ERROR` (существ.) | без изменений |
| RICH_PUBLISH | `PUBLISH_RICH_START`/`_COMPLETE`/`_ERROR` (существ.) | без изменений |
| PLAIN_FALLBACK | `PUBLISH_TEXT_START`/`_COMPLETE`/`_ERROR` reason=… (существ.) | + при legacy-капе: WARN `LEGACY_CHUNKS_CAPPED` (chunks_total, chunks_sent) |
| LEGACY_FALLBACK | **НОВОЕ** `LEGACY_FALLBACK` (WARN) | run_id, chat_id, **reason** ∈ {l1_unusable, l2_unusable, package_unusable, delivery_failed, hybrid_exception:<Class>}, **calls_so_far** |
| SUMMARY_DONE | `SUMMARY_COMPLETE`/`SUMMARY_FAILED` (существ.) | SUMMARY_COMPLETE + **fallback=none/legacy**, publication_status; code — по контракту (i) |

Лог одного прогона читается как pipeline сверху вниз (§18:2637). JS-харнесс log
viewer и `test_summary_logging_runid.py` обновляются под новые поля/события (T-3956);
фильтр «Саммари» (§110) подхватывает новые события по существующему префикс-правилу
(проверить, что `L1_PARSE`/`L1_REPAIR`/`LEGACY_FALLBACK`/`L1_FALLBACK_PACKAGE`
попадают в фильтр — при необходимости правка JS-списка префиксов, Δ каталога=0).

### (l) Промпт-каноны L1/L2 (§7, §10) + PREV_*/ROLLBACK

Механика (ADR-1013-3, прецедент `PREV_*_R1026`): в `services/summary_prompts.py`
текущие `_SUMMARY_L1_CLUSTERIZER_R1026_BASE`/`_SUMMARY_L2_WRITER_R1026_BASE`
получают снимки `PREV_SUMMARY_L1_CLUSTERIZER_R1027`/`PREV_SUMMARY_L2_WRITER_R1027`
(байт-в-байт текущие), новые базы — `_..._R1027_BASE`; идемпотентная канон-миграция
PG-ключей `prompts.summary_l1_clusterizer_system_prompt`/`prompts.summary_l2_writer_system_prompt`
+ документированный ROLLBACK (обратная миграция на PREV-снимки). TARGET_INSTRUCTION_BLOCK
сохраняется в обоих.

**L1 v2 — изменения канона** (структура: СИСТЕМНАЯ РОЛЬ / ЗАДАЧА / ЖЁСТКИЕ ПРАВИЛА /
ФОРМАТ ОТВЕТА / служебные поля):
- РОЛЬ: «Ты — кластеризатор саммари (Conversation Disentanglement). Твоя задача —
  понять, **что происходило в этом чате**, и разложить это на темы и проверяемые
  факты» (§7:2197–2203). ТЫ НЕ ПИШЕШЬ САММАРИ — сохраняется.
- ЗАДАЧА (расширение §7:2205–2212): основные темы; подпроцессы разговора; события;
  позиции участников; шутки/конфликты/ответы, если они важны; результат обсуждения;
  развитие темы во времени.
- ЯВНО РАЗРЕШИТЬ (§7:2216–2219): «Не обязаны включать каждое сообщение:
  малоинформативные сообщения можно не включать ни в одну тему (перечисли их в
  unassigned_message_ids). Одно сообщение МОЖЕТ входить в несколько тем, если оно
  реально относится к нескольким разговорам (ответ, закрывающий старую тему и
  начинающий новую; шутка-реакция на человека и на тему). Десятки мелких ответов
  можно объединить в один факт с несколькими evidence_message_ids. Не заставляй себя
  выбирать одну-единственную тему для сообщения.»
- УДАЛИТЬ правило «Один message_id — ровно в одной теме»; заменить: «Один message_id
  может встречаться в нескольких темах — это нормально».
- ЖЁСТКИЕ ПРАВИЛА (сохраняются): только существующие message_id; evidence из своей
  темы; не выдумывать факты/участников/метаданные; без системных тегов и сырых ID;
  факт ≤500 атомарный; topic ≤200 однострочный; ≤100 тем, ≤30 фактов/тему.
- ФОРМАТ ОТВЕТА: `"schema_version": 2` (пример JSON обновить).

**L2 v2 — изменения канона:**
- Базовые правила §97/§98 сохраняются (стиль, цитаты, атрибуция, JSON §99).
- Добавить блок ДЛИНА/ДЕДУПЛИКАЦИЯ (числа — НЕ в каноне, а в детерминированном
  length-блоке user-контента, см. ниже): «Требования к длине приходят в задании
  вместе с пакетом фактов. Target — мягкий ориентир, а не жёсткий лимит: если
  материала много, сначала объединяй похожие эпизоды и сокращай второстепенные
  подробности; не обрывай статью посередине и не удаляй последнюю тему ради
  попадания в лимит (§10:2320–2328). Одно и то же событие может встречаться в
  пакете несколько раз через разные темы (общие сообщения) — расскажи его ОДИН раз,
  дедупликация семантическая (§5:2150–2154, §10:2327–2328).»
- **Length-блок** — детерминированный append к user-контенту `build_l2_input`
  (после JSON пакета): «ЗАДАНИЕ ПО ДЛИНЕ И ДЕТАЛИЗАЦИИ: response_mode=<mode>;
  цель ≈ <target_chars> символов (мягкий ориентир); абзацев ≈ <target_paragraphs>
  (рекомендация). Это ориентиры, а не лимиты: не обрывай события и не выбрасывай
  важные темы ради точного числа.» Формат §99-документа не меняется; length-блок —
  не JSON-поле (валидатор документа его не видит).
- Author-контекст: fragments v2 несут `author_id`/`display_name`/`reply_to_id` —
  канон L2 дополнить: «В пакете указаны авторы и связи ответов: используй их, чтобы
  понимать, кто что сказал и кто кому отвечал; не приписывай реплики другим (§12).»
  (правило «не выдумывать авторство» уже есть — усилить ссылку на поля пакета.)

### (m) Graph memory (§19) — verification-only

Контракт: GraphRAG НЕ переписывается (§19:2697–2700, §21:2761). Задача T-3957 —
подтвердить (тестами и чтением кода), что: (1) `GraphExtractionError` при
`LLMTimeoutError` остаётся пойманным в `_compress_purge_extract_only` («batch kept,
pipeline continues» — verified ASAP-1 evidence §1); (2) новая fail-soft цепочка
саммари не интерпретирует граф-ошибки как причину SUMMARY failure (граф-ветка
`_run:428`/`memorize_facts` fire-and-forget — вне цепочки публикации); (3) граф-
сценарии `tests/test_summary_asap_hotfix_round1027.py` сохраняются/переносятся при
переписывании trim-тестов (контракт (e)). Никаких изменений граф-кода.

### (n) Релиз (Q8)

Единый релиз **2.58.33** (APP_VERSION + README + `param-registry-round1025.meta.md`
+ версия-пины 23+ py-тестов и 4 JS-харнессов — механика `270c277`; финальный номер
подтверждает Orchestrator, не ниже 2.58.33). Uncommitted partial НЕ коммитится
отдельно и НЕ деплоится — перерабатывается в Build (T-3947) и входит в единый
feat-коммит после Reviewer Approved; затем docs-коммит (планы/ADR/артефакты) —
конвенция проекта (git log: feat → docs). Δ DDL=0; Δ каталога=+16/+5 (F8-переиздание);
0 новых внешних зависимостей (всё stdlib + существующие модули — обоснование:
задача — реструктуризация существующего пайплайна, новых capability-доменов нет).

---

## 4. Failure cases и наблюдаемое поведение (сводка для Builder/Reviewer)

1. L1 выдал один неизвестный id → repair удалил id, факт/тема уцелели → pipeline
   продолжается, `L1_REPAIR unknown_ids_removed=1` (§17 тест 5).
2. L1 выдал >50% неизвестных id → useless → correction retry (1) → снова useless →
   `L1_FALLBACK_PACKAGE` → L2 на хронологии → статья «Общий ход обсуждения» (§17 тест 10).
3. Сообщение в двух темах → VALID, `overlapping_topic_memberships=1`, FactPackage
   строится (§17 тесты 3, 4, 6); L2 рассказывает событие один раз (§17 тест 7 —
   промпт-инструкция; формально assert по отсутствию дубля в mock-статье).
4. L2 вернул 8 абзацев при `limits.max_summary_parts=1` → статья публикуется ПОЛНОЙ
   (§17 тест 1) — параметр hybrid-кодом не читается.
5. L2 превысил target умеренно → не режем, не бракуем (§17 тест 8); L2 меньше target
   → не ошибка (§17 тест 9); L2 вернул 30000 симв. → WARN + публикация; 33000 →
   too_long → Legacy (§17 тест 11 через mock).
6. sendRichMessage упал → plain полный текст (§17 тест 12); plain упал → Legacy
   chunks (§17 тест 13); Legacy тоже упал → SUMMARY_FAILED + UX (§17 тест 11-анти-лавина).
7. Legacy при parts=1 сгенерировал >4000 → ровно 1 sendMessage-часть + WARN
   `LEGACY_CHUNKS_CAPPED` (§17 тест 2).
8. Miniapp: секции разделены (§17 тесты 14–15), подпись MAX_SUMMARY_PARTS точная
   (§17 тест 16).

## 5. Browser-сценарии (Playwright MCP, REQUIRED)

Окружение: локальный webapp (uvicorn) на тестовой БД/сиде каталога с существующей
test-админ-сессией (механизм авторизации проекта из webapp-тестов; prod-credentials,
Telegram-авторизация и реальный Bot API НЕ используются и НЕ изобретаются).
Entry point: `#/modules/summary` (модуль «Саммаризация»). Viewports: 1440×900
(desktop) и 390×844 (Telegram WebView mobile).

- **S1 (визуальный, скриншот):** на `#/modules/summary` видны две отдельные
  workspace-вкладки/секции «HYBRID SUMMARY» и «LEGACY SUMMARY FALLBACK»; они не
  слиты в одну карточку; общие параметры — вне обеих секций.
- **S2 (структурный):** вкладка HYBRID содержит: чекбокс «Hybrid Summary enabled»;
  поля L1 model/base_url (+secret key), L2 model/base_url (+secret key);
  context tokens/chars; селектор режима с ровно тремя опциями casual/serious/
  deep_research; target chars; target paragraphs; max chars; тумблеры «L1 repair»
  и «L1 retry» — каждый с человеческим русским описанием (не пустым).
- **S3 (визуальный, скриншот + структурный):** вкладка LEGACY содержит: чекбокс
  «Legacy fallback enabled»; legacy max context tokens/chars; MAX_SUMMARY_PARTS с
  описанием, ДОСЛОВНО включающим «Не влияет на Hybrid Article».
- **S4 (структурный, cross-isolation):** DOM-assert: ни один элемент с hybrid-ключом
  (`summary_hybrid_*`, `summary_l1_*`, `summary_l2_*`) не находится внутри контейнера
  legacy-секции, и наоборот (`max_summary_parts`, `summary_max_context_*`,
  `summary_legacy_fallback_enabled` — вне hybrid-секции).
- **S5 (интеракционный):** переключить «L1 repair» → сохранить → ровно 1 POST
  `/api/config` (network-наблюдение) → reload страницы → значение сохранено;
  смена режима serious→deep_research → save → GET отражает новое значение.
- **S6 (mobile 390×844):** обе секции рендерятся без горизонтального overflow;
  тач-цели ≥44px; описания читаемы (скриншот).
- **S7 (гигиена):** console без ошибок на всех шагах; секретные поля (api_key)
  рендерятся masked-виджетом (существующая механика adr-1025-22).

Критерий приёмки: S1–S7 зелёные в отчёте Reviewer; S1/S3 — со скриншотами в
`evidence.md`/`review.md`.

## 6. Traceability (требование → контракт/задачи)

R1 §1 → (d) T-3935/38; R2 §16 → (e) T-3936/37; R3 §2 → (f) T-3940; R4 §3 → (f)/(Q4)
T-3939; R5 §4/§5 → (a) T-3944/46; R6 §6 → (b) T-3945; R7 §8/§9 → (i) T-3949…52;
R8 §10 → (l) T-3942; R9 §11 → (g)/Q5 T-3941; R10 §12 → (h) T-3943; R11 §13 → (j)
T-3953/54; R12 §14 → (j) T-3955/38; R13 §15/§16 → (c) T-3947/48; R14 §18 → (k)
T-3956; R15 §19 → (m) T-3957; R16 §17/§20 → T-3958…61 (+ раздел 4/5); R17 §20/deploy →
(n) T-3962/63. Орфанов нет; каждый контракт имеет ≥1 задачу PM и ≥1 приёмочный тест.

## 7. Риски по группам задач

- **R1 (живая доставка/прод):** T-3950, T-3951, T-3963 — цепочка публикации и
  LEVEL-3 врезка в `_run_hybrid_l2`; причина: отказ = «саммари не публикуется»
  (P0-инцидент повторно). Митигация: guard `published`, kill-switch
  `summary_legacy_fallback_enabled`, harness T-3961 (§114-подобный, 0 отправок в
  основной чат), откат env `SUMMARY_HYBRID_L2_ENABLED=false` → весь трафик Legacy.
- **R2 (живой пайплайн генерации/UI):** Groups A/B/C (T-3935/36/39…T-3949), T-3953;
  причина: контракты L1/L2/FactPackage и бюджет — ядро продукта. Митигация:
  fail-closed валидаторы не ослабляются (список проверок (a) исчерпывающий),
  repair/retry за kill-switch'ами, PREV_*-снимки канонов + ROLLBACK.
- **R3 (механика/тесты/observability):** T-3937/38/48/54…57, T-3958…T-3962;
  причина: не меняют runtime-семантику доставки.

## 8. Стратегия тестирования / деплой / откат

- **Тесты:** §17 тесты 1–16 (маппинг — раздел 4/5 + tasks T-3958…T-3960); полный
  pytest baseline 9851 (после переписанных trim/retry-тестов — новый baseline
  фиксирует T-3961); JS vm-харнесс 48+ файлов exit 0 (новые/обновлённые харнесс-пины
  F8); `git diff --check`; R17-скан диффа. Интеграция fail-soft — mock-транспорт
  (QueueLLM-паттерн partial-тестов), 0 реальных LLM/Telegram.
- **Деплой (T-3963):** штатный `git pull --ff-only` + рестарт `admin_bot`; Δ DDL=0;
  env-правок не требуется (все новые дефолты в коде ON/середины пресетов); после
  деплоя — проверка hot-ключей `limits.summary_hybrid_*` и legacy
  `limits.max_summary_parts=6`; прод-верификация DoD-13…16 по §18-логам реального
  саммари `-1002661910336`.
- **Откат:** soft — env `SUMMARY_HYBRID_L2_ENABLED=false` (весь трафик Legacy,
  байт-в-байт OFF-путь) либо точечные `SUMMARY_L1_REPAIR_ENABLED=false`/
  `SUMMARY_L1_RETRY_ENABLED=false`/`SUMMARY_LEGACY_FALLBACK_ENABLED=false` + рестарт;
  cold — revert единого feat-коммита (прод-базис 2.58.32/`270c277`).
- **Промпт-откат:** ROLLBACK-миграция канонов на `PREV_*_R1027` (механика ADR-1013-3).

## 9. Расхождения для PM (consistency-check tasks.md ↔ spec)

1. **T-3935/T-3938:** rg-инвариант «`max_summary_parts` остаётся только в
   summary_generator.py:547 и каталоге» устарел — контракт (d) добавляет ВТОРОЙ
   legacy-потребитель (send-time кап числа чанков, §17 тест 2 требует «≤1 часть при
   parts=1», что prompt-бюджетом alone не гарантируется). PM: переформулировать
   инвариант как «только legacy-контуры summary_generator (промпт-бюджет + send-кап)
   + каталог + тесты» и добавить send-кап в объём T-3938 (или новой подзадачей).
2. **T-3939:** граница «аномального ответа» — `RICH_MAX_CHARS=32000` (fail-closed
   too_long), а `summary_hybrid_max_chars=24000` — WARN-полоса без отбраковки (Q4).
3. **T-3940:** значения пресетов зафиксированы (4000/5, 6500/8, 11000/14;
   max_chars 24000) — снять пометку «значения проверить».
4. **T-3941:** добавить в объём: (а) serialized-учёт `_unit` по json.dumps (§92-элемент),
   (б) mode-зависимый резолв бюджета `_apply_filter`, (в) democratic eviction ключ
   `(reply_protected, −weight, timestamp)` с reuse S1-веса.
5. **T-3944:** форма контракта — threads-v2 relaxed membership, `schema_version: 2`;
   `unassigned_message_ids` обязателен; `REASON_UNASSIGNED_CONFLICT` и
   `REASON_EVIDENCE_NOT_IN_THREAD` мигрируют из валидатора в repair (не остаются fatal).
6. **T-3945:** порог useless — формула Q3 (topics_after==0 ∨ facts_after==0 ∨
   unknown_ratio>0.5); модуль `services/summary_l1_repair.py`.
7. **T-3947:** retryable-набор отличается от partial (список Q(c)); correction-блок —
   текст контракта (c); `SUMMARY_L1_RETRY_ENABLED` становится env-слоем hot-ключа
   `flags.summary_hybrid_l1_retry_enabled`.
8. **T-3948:** слой Recovery-тумблеров — hot-ключи каталога (Q6) → Δ каталога +16/+5
   групп; `SUMMARY_L1_REPAIR_ENABLED`/`SUMMARY_LEGACY_FALLBACK_ENABLED` — новые
   env ClassVar.
9. **T-3949:** fallback-пакет обязан нести fragments v2 (author/reply — контракт (h))
   и строится с обложечным fallback `_derive_fallback_cover_prompt` (DoD-14 на
   деградированном пути).
10. **T-3950/51:** legacy fallback = полный legacy-пайплайн (System2 two-call по
    флагу), извлечённый в `_run_legacy_pipeline` (общий для OFF и LEVEL-3);
    worst-case бюджет ≤5 генераций (Q2 amendment); матрица из 11 строк (контракт (i))
    копируется в evidence T-3951.
11. **T-3953:** имена групп/вкладок зафиксированы (j); 3 существующих ключа меняют
    группу (перенос); общие ключи остаются в нейтральных группах; legacy-модель —
    БЕЗ нового слота (основная модель, описание в секции).
12. **T-3956:** переименований событий НЕТ — аддитивные поля + 4 новых события
    (`L1_PARSE`, `L1_REPAIR`, `L1_CORRECTION_RETRY`, `L1_FALLBACK_PACKAGE`,
    `LEGACY_FALLBACK`, `LEGACY_CHUNKS_CAPPED`, `L2_OVER_SOFT_CEILING`) + маппинг-таблица (k).
13. **T-3962:** F8-счётчики: REGISTRY 473→489, GROUPS 102→107, _TAB_BY_GROUP
    100→105, TAB_RULES 21 (in-place); релиз единый 2.58.33, feat+docs два коммита
    после Reviewer Approved (Q8).
14. **Browser-Verification REQUIRED** (ранее в tasks.md не зафиксирован): сценарии
    S1–S7 раздела 5 входят в приёмку T-3960/T-3963 (Reviewer — Playwright-отчёт).

## 10. Зависимости и совместимость

- Внешние зависимости: 0 новых (stdlib + существующие `services/*`; aiogram ≥3.31
  для rich — существующее требование, не меняется). Обоснование отсутствия: задача —
  реструктуризация собственного пайплайна; capability-доменов, где библиотека
  улучшила бы корректность/безопасность, не появляется.
- Backward compatibility: pg-ключи `limits.max_summary_parts`,
  `limits.summary_max_context_*`, `flags.summary_hybrid_l2_enabled` (per-chat
  overrides продолжают работать); env-имена не переименовываются; §99-документ и
  rich/plain-доставка байт-совместимы; FactPackage/L1 — внутренние контракты без
  персистенции (schema_version bump безопасен).
- Миграции данных: нет (Δ DDL=0); канон-миграция промптов — идемпотентная PG-запись
  существующим механизмом (ADR-1013-3).
- Security/privacy: R17 — секреты (api_key L1/L2) masked в UI и никогда в логах;
  display_name/тексты — только в LLM-payload (как сегодня), не в логах; correction-блок
  содержит только числовые id; egress — существующий `sanitize_outgoing`.

