# ASAP-EVIDENCE-ROUTING-01 v3 — замороженный контракт Evidence-first

Статус: `ARCHITECT_ADJUSTMENT_REQUIRED`
Фича: `asap-evidence-routing-01` (редакция **v3**; заменяет только v1/v2 этого же ID)
Ветка сверки: `evol/impl` @ `57081925` (2026-11-01), worktree `…/evol-71536a366a11-c63f6f44`
Источник требований: `plans/current_task.md:2008–2439` (v3 — полная самостоятельная редакция)
Внешние источники: **не использовались**. Все решения проверены по текущему коду worktree; внешних контрактов (провайдеры, лимиты API, версии SDK) это ТЗ не затрагивает.

Итог сверки: **дизайн владельца реализуем на текущей архитектуре без нового пайплайна**, но в коде найдены четыре конкретные несовместимости, которые надо снять узко и явно (§0.2). Ни одна из них не требует нового сервиса, новой LLM-стадии, нового Writer, нового классификатора или миграции БД.

---

## 0. Границы и четыре обязательные поправки

### 0.1. Scope

Входит:

- runtime-обязательность read-only evidence для **публичных** ветвей Direct и Initiative;
- детерминированные исключения (фон/социал/трансформация/атрибуция/runtime/история) без веб-вызова;
- qualified reuse уже прочитанного источника по claim-key (не Smart Cache ответов);
- единый контракт размера evidence (Dynamic Evidence Window) вместо независимых обрезок 4000/8000;
- bounded outbound guard по существенным внешним claim;
- минимальная правка только конфликтующих зарегистрированных промптов;
- 46 приёмочных сценариев на offline/staging fixtures.

Не входит (и это `NOT_APPLICABLE`, а не «забыли»):

- новый `AlwaysSearchService`, новый crawler, второй Writer, второй классификатор, второй FactCheck-пайплайн;
- переработка `ASAP-FC-ADMISSION-01`, `ASAP-FC-EVIDENCE-STYLE-02`, `ASAP-VISION-SYNC-01`, `EVOL-SRC-READER` (последний — `PENDING`, `plans/features/evol/status-snapshot.md:66`, параллельный reader не пишем);
- Smart Cache готовых ответов (`EVOL-031`, публичный API `SmartCache` после удаления — только маркерные методы, `services/smart_cache.py:170–173`);
- новые обязательные согласования/canary (PET_PROJECT, `AGENTS.md` §PET_PROJECT);
- DDL/миграция схемы (`PRAGMA user_version` = 40, `services/database.py:1753`);
- UI/стекло/эмбеддинги/личность/Core/Expression/Style.

### 0.2. Четыре несовместимости текущего кода с контрактом v3 (заморожено)

| # | Где | Что реально в коде | Минимальная поправка |
| --- | --- | --- | --- |
| C1 | `services/direct_execution.py:147–167` (`resolve_execution_mode`) | `plan.execution_mode == "none"` → `EXECUTION_NONE` **даже при наличии схем**; а `execution_mode` — allowlisted-поле L1-плана (`services/direct_l1.py:493–499`), т.е. L1 (или пустой `capabilities_needed`) может полностью выключить инструменты | mode `none` переопределяется, если есть `runtime_required` capabilities: `(simple_tools, "evidence_required_overrides_plan")`. Demotion adaptive-цепочки не меняется |
| C2 | `services/direct_chat_service.py:5073–5083` (`_l1_tool_subset`) | `confidence_bucket == "low"` → `skip = capabilities_needed`, т.е. низкая уверенность L1 **удаляет** запрошенные инструменты (`REASON_LOW_CONFIDENCE`) | skip применяется только к L1-запрошенным capability; `runtime_required` входит в отдельный `protected`-набор и не может быть снят уверенностью. Код `low_confidence` для них не эмитится |
| C3 | `services/tool_schemas.py:928–958` (`active_tools`) + `services/capability_registry.py:615–650` (`_build_web_search`) | глобальный рубильник «Модуль Поиск» (`flags.search_enabled`, `config/settings.py:487`) проверяется только в `handlers/search.py:122` и `handlers/direct_chat.py:117`; в Direct tool-пути `execute_web_search`/`fetch_article` работают мимо него; capability-реестр состояние флага также не читает | `allowed(web_search)` обязан читать `hot.get("flags.search_enabled", settings.SEARCH_ENABLED)` (и `flags.webpage_enabled` для `fetch_url`) **до** любого сетевого вызова. Это же закрывает `USER_FORBIDS_EXTERNAL` |
| C4 | `services/direct_execution.py:916–930` (`l2_evidence_budget_chars`) | вызывается с бюджетом **уже без** output reserve (`l2_input_budget` из композера, `direct_chat_service.py:7360`), но по умолчанию снова вычитает `output_reserve_tokens=512` → двойной резерв, evidence урезается дважды | дефолт `output_reserve_tokens=0`; резерв вывода остаётся один раз и только в композере. `others` считается одной функцией измерения (§4.2), а не ручной суммой подмножества блоков (`direct_chat_service.py:4227–4232` не включает базу Writer и plan-блок) |

Все четыре правки — часть этой же фичи; без них 46 сценариев не проходят честно (ложные skip'ы и двойные срезы).

---

## 1. Runtime evidence policy

### 1.1. Один новый чистый модуль, ноль новых стадий

`services/evidence_policy.py` — **чистые функции**: без I/O, без LLM, без БД, без сети. Один вход, один выход, полностью тестируемо.

```python
EvidenceClass = Literal[
    "externally_factual", "attributed", "background",
    "social", "transformation", "runtime", "historical",
]

@dataclass(frozen=True)
class ClaimKey:
    entity: str          # нормализованная сущность ("deepseek v4.1 flash")
    relation: str        # "exists" | "version" | "spec" | "price" | "date" | "event" | "comparison"
    version: str = ""    # "1017" / "2.58.145"
    date: str = ""       # ISO-дата или период claim, не «сегодня»
    metric: str = ""     # "vram_gb" / "usd" / "" — единица измерения claim
    def key(self) -> str: ...   # sha1[:16] от стабильного канона

@dataclass(frozen=True)
class EvidenceDecision:
    required: bool
    evidence_class: EvidenceClass
    claims: tuple[ClaimKey, ...] = ()
    source_kind: str = ""            # web|official_doc|source_code|chat_history|runtime|vision|supplied
    skip_reason: "EvidenceSkipReason | None" = None
    explicit_request: bool = False
    note: str = ""                   # машинный идентификатор, не текст для пользователя
```

Точка входа:

```python
def evaluate_evidence_need(
    *, plan,                        # существующий L1Plan
    task_kind: str,                 # response_extent.TASK_KINDS
    explicit: ExplicitRequest,      # см. 1.3 (детерминированные сигналы)
    supplied: SuppliedSources,      # reply-текст/медиа/URL/файл уже в контексте
    runtime_state: RuntimeState,    # effective route, настройки (для self-status)
) -> EvidenceDecision
```

`evidence_class` берётся из **планируемого содержания ответа**, не из темы входящего текста (§4.1 и §4.3 ТЗ). Разбор входа на классы — единственная семантика модуля.

### 1.2. Правила вывода (порядок — контракт, не рекомендация)

1. `plan.action in ("silent", "react")` → `evidence_class="social"`, `required=False`, `skip_reason=SILENT_OR_REACT_ONLY`. Никаких сетевых вызовов (ветка уже отсекается до tool-фазы, `direct_chat_service.py:3730–3831`; policy это подтверждает и тестируется).
2. `explicit.search or explicit.verify or explicit.read_source` → `required=True`, `source_kind` по типу поручения (`web`/`web`/`source_code`), **независимо** от `plan.confidence`, `tool_policy`, `execution_mode` (снимает C1/C2).
3. Реплика только трансформирует предоставленный текст (пересказ/перевод/правка) и план не содержит собственных новых внешних claim → `evidence_class="transformation"`, `skip_reason=TEXT_TRANSFORM_OR_TRANSLATION`.
4. План пересказывает чат/память/саммари с атрибуцией и не добавляет новых внешних claim → `attributed`, `skip_reason=ATTRIBUTED_HISTORY_OR_SUMMARY`; при вопросе «что было в чате» → `historical`, `skip_reason=SUFFICIENT_CHAT_HISTORY_SOURCE`.
5. Вопрос о собственной модели/настройках/состоянии → `runtime`, `skip_reason=SUFFICIENT_RUNTIME_SOURCE`; ответ обязан брать effective route из существующего источника, не из промпта (§5.6 ТЗ; текущий `SelfModel` — только характер).
6. `plan.external_claims` непусто **или** `plan.response_act ∈ FACTUAL_ACTS` (`answer|explanation|disagreement|research|comparison`, плюс категорическое опровержение) **или** `plan.structure ∈ (answer, explanation, report, comparison)` → `externally_factual`, `required=True`.
7. Социально-творческие акты без внешнего claim (`agreement|banter|tease|emotional_reply|support|creative`) → `social`, `skip_reason=PURE_SOCIAL_OR_CREATIVE` или `NO_NEW_EXTERNAL_CLAIM`.
8. Иначе (неизвестно) → **проверка требуется** (`externally_factual`, `required=True`), но с bounded-бюджетом «один адресный lookup» (§4.6). Это осознанная асимметрия: пропуск обязательной проверки опаснее лишнего запроса.
9. Если уже есть свежий claim-bound источник (§3) → `required=False`, `skip_reason=QUALIFIED_VERIFIED_REUSE`, но `claims` заполнены: Writer получает ту же выдержку.
10. Если `allowed(...)` не пропускает ни один нужный read-only tool → `required=True`, `required_unmet=True` с конкретным `EvidenceFailureCode` (§1.4). Это **не** исключение.

Правила 1–9 не вызывают LLM: используется уже существующий план L1 (`services/direct_l1.py:193–231`) и существующие детерминированные детекторы.

### 1.3. `explicit_request` — только существующие детекторы

- `services/direct_capabilities.py:419` `detect_action_intent(...)` уже даёт `INTENT_WEB_SEARCH` + `REASON_SEARCH="search_request"` (`:223`, `:535`) по `_SEARCH_MARKERS`;
- `services/direct_execution.py:217–219` `_SEARCH_RE` — тот же класс запроса для деградированного плана;
- `services/temporal_factcheck.py` `is_referential_claim(query)` — «проверь это» на reply;
- `services/smartmodule_urls.extract_urls` — явная ссылка/«прочитай вот это».

Новый словарь фраз **не заводится**. Расширение словарей под инцидентные формулировки запрещено (§4.3 ТЗ).

### 1.4. Два закрытых перечисления и их привязка к существующим кодам

`EvidenceSkipReason` (нормальное основание не делать **внешний** вызов):

| enum | `reason_code` в существующем словаре |
| --- | --- |
| `SILENT_OR_REACT_ONLY` | `stage_skipped` |
| `NO_NEW_EXTERNAL_CLAIM` | `stage_skipped` |
| `PURE_SOCIAL_OR_CREATIVE` | `stage_skipped` |
| `ATTRIBUTED_HISTORY_OR_SUMMARY` | `already_answered` |
| `TEXT_TRANSFORM_OR_TRANSLATION` | `stage_skipped` |
| `SUFFICIENT_RUNTIME_SOURCE` | `already_answered` |
| `SUFFICIENT_CHAT_HISTORY_SOURCE` | `no_relevant_memory` (не найдено) / `already_answered` (найдено) |
| `SUFFICIENT_SUPPLIED_SOURCE` | `stage_skipped` |
| `SOURCE_READER_ALREADY_FETCHED` | `provenance_linked` |
| `QUALIFIED_VERIFIED_REUSE` | `exact_match_used` (слаг кеша источников, не ответов) |
| `USER_FORBIDS_EXTERNAL` | `financial_limit_disabled`-класс → **новый** `external_tools_disabled` (см. ниже) |
| `RBAC_OR_PRIVACY_BLOCKED` | `job_not_allowed` |

`EvidenceFailureCode` (**обязательная, но не выполненная** проверка — не исключение):

| enum | `reason_code` |
| --- | --- |
| `SEARCH_PROVIDER_DOWN` | `provider_unavailable` |
| `SOURCE_FETCH_FAILED` | `source_missing` |
| `BUDGET_OR_DEADLINE` | `deadline_exceeded` |
| `QUOTA_EXHAUSTED` | `financial_limit_reached` |
| `NETWORK_UNAVAILABLE` | `provider_unavailable` |
| `MEDIUM_NOT_READY` | `stage_waiting_external` |
| `NO_RELEVANT_RESULTS` | `retrieval_empty` |
| `CAPABILITY_NOT_READY` | `capability_not_ready` (существующий `direct_capabilities.REASON_NOT_READY`) |

Словарь `mca_events.REASON_CODES` расширяемый (§17.2, `services/mca_events.py:59–60`). Аддитивно добавляются **ровно три** кода, без которых нет честной семантики:

- `evidence_skipped` (с подпричиной в отдельном поле события, не в `reason_code`);
- `evidence_reused`;
- `evidence_unverified_claim_removed`.

Никакого второго словаря: enum'ы живут в `evidence_policy.py` и в `reason_code` конвертируются **один раз**, на границе события.

### 1.5. Нормативный merge и `allowed()`

```text
effective_readonly = allowed(L1_requested ∪ runtime_required)
```

`allowed(capability, ctx)` — единственная точка разрешения, порядок проверок фиксирован:

1. RBAC/доступ чата (`services/permissions.py`, `services/chat_access.py`, существующие проверки хендлеров);
2. пользовательский/глобальный запрет сети: `hot.get("flags.search_enabled")` для `web_search`, `flags.webpage_enabled` для `fetch_url` (**C3**), плюс явный запрет в сообщении → `USER_FORBIDS_EXTERNAL`;
3. реальная доступность провайдера/ключа/состояния: `capability_registry.resolve(cap, chat_id)` → `available`, `reason_code` (`search_provider_unconfigured`, `provider_unavailable`, `tool_absent`); `EVOL-SRC` при `PENDING` → `CAPABILITY_NOT_READY`, а не «пропускаем»;
4. стоимость/квоты: `METERED_TOOLS` + действующие лимиты (`services/tool_loop.py:51–53`, `services/budget_gate.py`, `services/mca_money_limits.py`) — без новых квот;
5. SSRF/размер/тип контента: остаются в `services/safe_fetch.py` (класс A, не трогаем);
6. privacy/деперсонализация запроса (§7 ТЗ): сборка query — существующий путь, плюс запрет отправлять полный текст реплики/имена/ID в поисковик.

`allowed()` возвращает `(ok: bool, code: str)`; `runtime_required` **никогда** не понижается `confidence`, `tool_policy`, пустым `capabilities_needed` или `execution_mode`. Обратное (L1 запросил больше, чем разрешено) — штатно: capability отбрасывается с наблюдаемым кодом, как сейчас.

### 1.6. Optional-аннотация claim от L1 (без нового вызова)

Единственный LLM-вызов на ход в Direct остаётся прежним (`L1 + L2`; третий — только adaptive, `services/direct_execution.py:1–34`). Поэтому claim-аннотация добавляется **в тот же JSON L1** как allowlisted-поле, по прецеденту `future_intent` (`services/direct_l1.py:141–155`, парсинг `:519–526`):

```json
"external_claims": [{"entity": "...", "relation": "version|exists|spec|price|date|event|comparison",
                     "version": "...", "date": "...", "metric": "..."}]
```

Правила: невалидный элемент отбрасывается, пустой список → `[]`; отсутствие поля → деривация §1.2 п.6. Поле **уточняет** claim-key для reuse и coverage, но не даёт права отменить обязательную проверку, если §1.2 п.6 говорит `required=True`.

---

## 2. Точки интеграции (только существующие сервисы)

### 2.1. Direct / L1 / ExecutionGraph

| Шаг | Файл:строка (текущий HEAD) | Изменение |
| --- | --- | --- |
| participation decision | `direct_chat_service.py:3730–3831` | без изменений; именно это гарантирует «сначала публикация, потом проверка». Добавляется только событие с `evidence_class` |
| capability consistency | `direct_chat_service.py:3622–3641` → `_l1_capability_consistency` (`:8689`) | переиспользуется как есть для image-capability; evidence-политика не дублирует её |
| сбор policy | новое: `evidence_policy.evaluate_evidence_need(...)` | вызов **до** tool-фазы, после готового `l1_plan` и `response_plan` |
| merge capability | `direct_chat_service.py:5055–5098` (`_l1_tool_subset`) | `skip` (low-confidence) только для `l1_requested`; добавляется `required=decision.required_caps`; `allowed()` (§1.5) фильтрует итог; отказы — существующим `_caps.emit_capability_rejected` |
| выбор mode | `direct_execution.py:147–167` | правка C1 |
| исполнение | `direct_execution.py:232–403` (`derive_simple_steps`), `direct_chat_service.py:5100–5140` (`_l1_tool_phase`) | `derive_simple_steps` получает `required_caps` для деривации шагов, когда L1-план пуст (web/fetch/chat_history) |
| упаковка evidence | `direct_chat_service.py:4224–4245`, `direct_execution.py:933–1060` | capacity из §4.2; `EvidenceSource` получает `claim_keys`/`source_read_level`/`full_source_pointer` |
| Writer | `direct_chat_service.py:4281–4304` → `_l2_write_answer` (`:5843`) | один Writer, без изменений топологии; в план-блок добавляется машинная строка coverage (§4.5) |

Инвариант: **один** `EvidencePack` → **один** Writer. Никаких «догрузок» между L1 и L2 вне существующего tool-loop.

### 2.2. Initiative

`initiative_observer` уже идёт тем же путём: решение об участии → `handle_initiative` (`services/direct_chat_service.py:11469`) → тот же L1/L2. Поэтому:

- `SILENT`/`REACT` без фактов — tool-фаза не запускается вообще (существующая ветка), политика только фиксирует `SILENT_OR_REACT_ONLY`;
- выбранная публичная инициативная реплика с внешним claim — та же политика и тот же guard, что в Direct (вызов тот же, отдельного кода нет);
- антифлуд/cooldown/суточные квоты/выбор адресата не трогаются (`services/initiative_observer.py:1747–1760`, `1942+`);
- запрещено: проверка «всех кандидатов инициативы» или «всей истории 500 сообщений» — preflight только для фактически выбранной реплики.

### 2.3. Bounded outbound guard (egress)

Существующий chokepoint: `direct_chat_service.py:4331` (`answer = strip_reasoning_tags(...)`) → numeric guard (`:4345`) → duplicate guard (`:4371–4380`). Вставляется **после** L2 и **до** отправки, ровно один раз.

- Вход: `answer`, `decision` (планируемые claim), `evidence_index` (какие sources/claims реально доставлены Writer'у), `pack.limitations`.
- Проверка — **не** LLM-судья и **не** одна регулярка «всегда/не существует». Используются существующие семантические примитивы: `services/search_aggregator.py:356 claim_relevance(...)` (+`_opposite_direction`, `_numbers_in`, `_unit_classes`) для сверки чисел/единиц/направления, `claim_envelope.normalize_proposition` для канона, `public_speech_guard.claims_total_verification` (`services/public_speech_guard.py:249`) для «проверил/подтвердил» без доказательства.
- Класс риска: только существование/версия/цена/дата/число/характеристика/категорическое опровержение. Метафора, чужая атрибутированная речь, «ага» — вне проверки.
- Действие (`GuardAction`): `NONE` | `HINT_RETRY` | `ONE_LOOKUP_THEN_HINT_RETRY` | `DROP_UNSUPPORTED_HIGH_RISK_CLAIM`.
  - максимум **1** адресный lookup (существующий `tool_router`, тот же путь);
  - максимум **1** повторная генерация через существующий механизм hint-ретрая (`direct_chat_service.py:4371–4378` — сейчас там freshness-ретрай), и он **взаимно исключающий** с freshness-ретраем, чтобы на ход было не более одной регенерации;
  - `DROP_UNSUPPORTED_HIGH_RISK_CLAIM` — детерминированное удаление **только** предложения с высокорисковым категорическим claim и **только** если hint-ретрай исчерпан; остальной текст (шутка/ритм) сохраняется;
  - при недоступности проверки — не превращать ответ в «данных недостаточно»; максимум честное ограничение, либо (для Initiative) `SILENT`.

Kill-switch: `EVIDENCE_EGRESS_GUARD_ENABLED` (env + ClassVar по действующему паттерну `services/mca_gates.py`), OFF → прежнее поведение байт-в-байт.

### 2.4. FactCheck / Vision / SourceReader — только интеграция

- FactCheck: `derive_simple_steps` уже умеет `fact_check` (`direct_execution.py:333–362`), исполнение — `tool_router._fact_check` → `FactCheckService` (`tool_router.py:3161`). Второй search-preflight, вторая suitability-эвристика и второй verdict **не** добавляются. Глобальный контракт только гарантирует: публичный фактчек не обходит `FactcheckPlan → RetrievalOutcome/EvidenceMap → CheckedVerdict` и не объявляет «проверено» без evidence.
- Vision: готовность — существующий единый barrier (`services/media_readiness.py`, `services/mca_watchdog.py`). Политика ждёт только **относящийся** к тезису asset; повторный OCR не запускается. `image_understanding` деривация уже есть (`direct_execution.py:315–332`).
- SourceReader: `EVOL-SRC-READER` — `PENDING` (нет `read_source_code` в коде). Никакого параллельного reader'а не пишем: интеграционный шов — capability `source_read` в `allowed()` возвращает `CAPABILITY_NOT_READY`, а пользователь получает честную границу. Точка подключения появится после реализации `EVOL-SRC`.
- Web/Search: `SearchAggregator` (raw candidate list с URL) + `WebContentExtractor` (`services/web_content_extractor.py`) — существующие, второй контур не строится.

### 2.5. Background: Summary / Sleep / Deep Sleep / Memory / Dossier / GraphRAG

**Ноль изменений, ноль новых вызовов.** Доказательство структурное, а не «на слово»: ни один фоновый сервис не импортирует `search_aggregator`/`web_content_extractor` (проверено: импорты есть только в `factcheck_*`, `search_service`, `temporal_factcheck`, `tool_router`), а в промптах `summary_prompts.py`, `dream_prompts.py`, `dossier_prompts.py`, `memory_*` нет ни одной директивы про веб/интернет. Политика в эти ветви не вызывается вообще (нет точки вызова). Регрессия защищается тестом (§6, C19–C27).

---

## 3. Qualified source reuse (не Smart Cache)

### 3.1. Что переиспользуется

Только **прочитанный источник, привязанный к конкретному claim**: `http(s) URL | source_id`, фрагмент, `source_read_level` (`discovered|snippet|fetched|parsed|selected`), `retrieved_at`, `published_at`, `source_kind` (`services/search_aggregator.classify_source_kind`), `published_at_source`, поддерживаемая область. Ответы бота, пересказы и «текст прошлой реплики» не переиспользуются никогда.

### 3.2. `claim_key` — канон

`services/claim_key.py` (новый маленький модуль) или функции в `evidence_policy.py`:

```text
claim_key = sha1("|".join([entity, relation, version, date, metric]))[:16]
```

- `entity`/`relation` нормализуются `claim_envelope.normalize_proposition` (существующий канон whitespace/пунктуации, `services/claim_envelope.py:176`);
- `version`/`date`/`metric` — только из фактического claim (не «сегодня»); отсутствие → `""`;
- «тема та же» или совпадение названия продукта **недостаточно**: разные `version`/`date`/`metric` → разные ключи.

### 3.3. Хранилище и freshness

Хранилище — **in-memory bounded LRU в процессе**, новый `services/source_reuse.py` (прецедент структуры: `services/lore_cache.py:1–22`). Причины отказа от БД: `smart_cache` после `EVOL-031` имеет только маркерный API (`get_update_marker`/`set_update_marker`) — использовать его для источников значило бы вернуть удалённый ответный кеш; а новая таблица = DDL/миграция v41, которых фича не требует. Честное ограничение фиксируется явно: **после рестарта процесса reuse пуст, источник перечитывается один раз**; это не «verified reuse», а обычный fetch.

TTL по классу claim (hot-ключи `limits.evidence_reuse_ttl_<class>_seconds`, дефолты в коде):

| класс claim | TTL |
| --- | --- |
| `live_market` (курс/цена/наличие) | 900 с |
| `release_news` (выход версии/релиз/событие) | 6 ч |
| `spec_parameters` (характеристики/спеки) | 7 сут |
| `official_docs` (документация/API) | 14 сут |
| `historical_fact` (устойчивый факт) | 30 сут |

Инвалидация (обязательна, тестируется):

- новый `version`/`date`/`metric` в claim → ключ другой, reuse не засчитывается;
- контрдоказательство в том же диалоге (`claim_relevance` даёт `contradicts`) → запись помечается `contested` и **не** отдаётся как proof, разрешён адресный fetch;
- истёк TTL → miss, обычный fetch;
- явная просьба «обнови/проверь заново» → bypass;
- scope: приватный/чатовый контекст и query другого чата **не** переиспользуются и не смешиваются (`chat_id` в ключе для всего, что не публичный web/official URL); для публичного URL разрешено переиспользование самого источника, но не приватной формулировки запроса.

### 3.4. Что возвращается Writer'у при reuse

Тот же `EvidenceSource` с `delivered_chars > 0` и `source_read_level >= fetched`, плюс в пакете строка `reuse: <claim_key> | <source_id> | age=<...>`. `source_fetched` ≠ `verified_reuse`: reuse засчитывается только если выдержка реально доставлена в пакет (иначе — limitation, как сейчас в `build_evidence_pack`, `direct_execution.py:1043–1046`).

---

## 4. Dynamic Evidence Window

Расширяем существующие `model_capacity` / `auto_budget` / композер / `EvidencePack` / `tool_router`. Новый бюджетный движок не создаётся.

### 4.1. Discover

Реальное окно уже резолвится: `model_capacity.resolve_model_context_window` (`:205`), `resolve_effective_window` (`:235`, conservative min при fallback), `output_reserve_tokens` (`:256`), `compute_available_budget`/`apply_budget_policy` (`:277`, `:290`). Ничего не меняем, кроме одного: при `unknown` окно помечается как fallback (уже так, `services/model_capacity.py:173–204`) и используется консервативно — «16К выдаётся за реальную способность» запрещено.

### 4.2. Measure / Allocate (снимает C4)

Один измеритель вместо ручных сумм:

```python
def measure_nonevidence_chars(*, system_base: str, plan_block: str,
                              time_line: str, user_blocks, lessons: str,
                              speech: str, character: str) -> int
```

`l2_evidence_budget_chars(input_budget_tokens, other_chars, output_reserve_tokens=0)`:

```text
available   = input_budget_tokens * 4                     # chars
budget      = clamp(available - other_chars - SAFETY_MARGIN, floor=EVIDENCE_FLOOR_CHARS)
evidence    = min(budget, int(input_budget_tokens * 4 * EVIDENCE_MAX_SHARE))
```

`EVIDENCE_MAX_SHARE` (0.4) остаётся **страховкой сверху**, а не ceiling качества: при большом окне и малом остальном payload evidence получает реально больше (сценарий 38). `SAFETY_MARGIN` — фиксированные 200 chars.

### 4.3. Retrieve: tool-границы вместо 4000/8000

`services/tool_router.py`:

- `_SEARCH_MAX_SYMBOLS`/`_ARTICLE_MAX_SYMBOLS` перестают быть «потолком качества» и становятся **legacy-дефолтом** для вызовов без бюджета;
- фактический лимит приходит per-call: `ToolContext.evidence_budget_chars` (новое поле, дефолт `0`) → `cap = max(SEARCH_RESULT_SOFT_FLOOR, int(budget * 1.25))` для поиска и `int(budget * 1.25)` для статьи, но не выше `TOOL_RESULT_HARD_CEILING` (класс C, защита от лавины, настраиваемый; физические байтовые лимиты `safe_fetch` остаются классом A/B);
- `_execute_web_search` возвращает **кандидатов** (URL + заголовок + фрагмент), обрезка больше не режет список на 4000 до потери релевантного URL (сценарий 36); `truncated`/`remaining_chars` фиксируются в payload;
- `_fetch_article`: извлечение идёт с расширенным `ARTICLE_EXTRACT_CEILING` (класс C, дефолт 120 000 симв.) вместо `_ARTICLE_MAX_SYMBOLS`, затем **section selection** по терминам claim (`content_terms` + `claim_relevance`), с поддержкой `arguments.section|offset|terms` для догрузки. Payload сохраняет текущие ключи (`status,url,source_id,chars,truncated,markdown`) и добавляет `excerpt, excerpt_chars, sections, remainder_chars, budget_chars, budget_source, full_source_pointer` → существующие тесты/клиенты не ломаются, но нужная часть документа после 8k достижима (сценарий 37);
- таймауты остаются конечными и конфигурируемыми (`_SEARCH_TOOL_TIMEOUT=25`, `_ARTICLE_TOOL_TIMEOUT=45`), согласованы с `request_deadline` и `TOOL_CHAIN_TIMEOUT_SECONDS=360` (`services/tool_loop.py:51`); при нехватке — промежуточная реакция/durable continuation, а не бесконечный Writer.

### 4.4. Preserve

- P0-блоки защищены как сейчас: `build_evidence_pack` резервирует floor каждому источнику и возвращает излишек (`direct_execution.py:984–1010`); comparison-задачи сохраняют блок каждого источника;
- обрезка **никогда** не рвёт URL/JSON/citation ID: `source_id`, `full_source_pointer` и `line_range` — отдельные поля, не часть обрезаемого текста;
- пара `claim → source` сохраняется: `EvidenceSource.claim_keys` + `EvidencePack.coverage` (§4.5);
- если физически не влезает — поэтапное чтение (section/offset) с указателем на полный источник, а не потеря.

### 4.5. Observe

`EvidencePack` получает аддитивно:

```text
capacity_chars, capacity_source ("window"|"legacy"), budget_source,
coverage: {required_claim_keys, covered, missing}, truncation: [{tool, kept, total, stage, retrievable_remainder}]
```

События (существующая шина `agentic_events`, whitelist-поля обязательны):

- `EVIDENCE_POLICY_DECIDED` — `evidence_class`, `required`, `skip_reason`/`failure_code`, `claim_count`, `source_kind`, `network_calls=0`, `reason_code`;
- `EVIDENCE_DELIVERY` — `fetched`, `reused`, `delivered_to_writer`, `coverage_ratio`, `truncation_stage`, `capacity_source`, `latency_ms`, `cost`;
- `EVIDENCE_EGRESS_CHECK` — `guard_action`, `lookup_used`, `retry_used`, `dropped_claim`, `reason_code`.

`source_fetched ≠ evidence_delivered_to_writer ≠ verified`. В логи — только enum/числа/имена tools, без текстов, URL-секретов, промптов (`R17`).

### 4.6. Не двойные резервы и не «заполнить всё окно»

- output reserve вычитается **один раз** (композер), поэтому `output_reserve_tokens=0` в `l2_evidence_budget_chars` (C4);
- рост окна **не** обязывает заполнять его: объём evidence задаёт `claim_count`/число независимых источников, а не максимум окна; короткий factual-ответ берёт короткую выдержку (§3 ТЗ);
- частота веба не растёт от размера окна: один required-lookup на claim-группу.

---

## 5. Промпты: точный список и стратегия разрешения конфликтов

Аудит — по фактически активной сборке: `services/prompt_registry.py:782–815` (метаданные блоков), `services/prompt_migrations.py:243,507` (лестница канона), фактический текст `services/chat_prompts.py`.

| `prompt_id` | Что реально сейчас | Действие | Почему |
| --- | --- | --- | --- |
| `prompts.direct_l1_planner_system_prompt` | JSON-схема без `external_claims`; правило 4 (PA5W2) просит `web_search`, «когда достоверность существенно зависит…» (`chat_prompts.py:1053–1069`); про `execution_mode` в тексте нет ничего | **Изменить**: новая фабричная ревизия (новая ступень `_DIRECT_L1_PLANNER_BASE_EVR1`, прежняя — замороженный `PREV_*`), добавить optional `external_claims`, одну машинную фразу «решение об обязательности read-only проверки исполняет runtime независимо от твоего мнения» и явное «уверенность/tool_policy/пустой набор не отменяют обязательную проверку» | §8.1 ТЗ; сейчас L1 де-факто единственный судья (см. C1/C2) |
| `prompts.direct_chat_verbalizer_system_prompt` | «окончательный текст», без правила фактовой дисциплины | **Изменить**: 3–4 предложения фактовой дисциплины (§8.3 ТЗ): опираться на доставленные доказательства; не говорить «проверил», если проверки не было; `no_results` ≠ «не существует»; не превращать короткую шутку в отчёт со ссылками | Writer — единственный источник неподтверждённых добавок (§2.3) |
| `prompts.direct_chat_system_prompt` (tool phase) | секция «ПОИСК И НЕПОДТВЕРЖДЁННЫЕ ХАРАКТЕРИСТИКИ» (`chat_prompts.py:408–431`) уже покрывает семантику «когда искать» | **Изменить минимально**: одна фраза о том, что обязательность проверки решает runtime, а задача стадии — не выдавать неподтверждённое; секция W2 не переписывается | иначе «когда он доступен» читается как разрешение обойти policy |
| `prompts.search_system_prompt` | используется `SearchService.research` (правочный путь), не tool-путём | **Не менять** | tool-путь идёт через `SearchAggregator` напрямую (`tool_router.py:1136`) |
| `prompts.summary_system_prompt`, `summary_editor/narrator/l1_clusterizer/l2_writer`, `dream/dossier/memory` | ни одного упоминания веба/интернета (grep по `summary_prompts.py`, `dream_prompts.py`, `dossier_prompts.py`) | **Не менять**; добавить регресс-тест «нет директивы гуглить» | §5.4/§7.5 ТЗ: фоновая стадия не получает обязательный поиск |
| `prompts.factcheck_*` | предмет `ASAP-FC-EVIDENCE-STYLE-02` | **Не менять** | отдельная задача владельца |
| `prompts.verbilizer_mode_*` | длина/форма | **Не менять** | форма доставки не меняется (`response_extent`) |

Стратегия разрешения конфликтов (без «громкой» директивы сверху):

1. приоритет по смыслу: **runtime policy/источники > фактическая достоверность > стиль**; директива формулируется как задача стадии, не как приказ «всегда искать»;
2. конфликт устраняется **в источнике владения** (фабричный текст канона), не наложением повторов;
3. ни одна правка не добавляет persona, второй Writer, второй классификатор или JSON-инструкции в speech-канал;
4. каждая правка — через `prompt_release_policy`/`prompt_registry` по `EVOL-016–018`: новая заводская ревизия, `PREV_*`-слепок для отката, `prompt_migrations`-ступень; ручные редакции владельца не перезаписываются;
5. до merge/deploy — снимок effective payload для L1/Writer/Summary (машинная стадия без Core-сарказма, публичная — с активным характером), сохранённый как evidence.

**Обязательная таблица §7 ТЗ** (stage/prompt_id/revision | цитируемая конфликтующая инструкция | конфликтующий контракт | consumer/effective path | решение | тест) заполняется Builder'ом по факту до правки текстов и проверяется до релиза. Уже сейчас известные кандидаты конфликта: «когда он доступен» в W2-секции против обязательности при `allowed()=true`; отсутствие правила «не заявлять проверку» в вербализаторе против `public_speech_guard.claims_total_verification` (существующий guard ловит это на выходе, но промпт его не поддерживает).

---

## 6. Стратегия тестов на 46 сценариев

Правило: **сначала использовать существующие fixtures**, новые тесты — только для реально непокрытого. Никаких живых постингов в рабочие Telegram-чаты.

### 6.1. Что уже покрыто (переиспользовать, не дублировать)

| Группа | Существующие тесты |
| --- | --- |
| Direct tool-путь, mode-резолв, evidence pack | `tests/test_asap8_v6_wc_direct_d04.py`, `test_asap8_v6_wc_direct_matrix.py`, `test_asap8_v6_wc_direct_d03.py`, `test_tool_chain_round1026.py` |
| L1-контракт/парсинг плана | `test_asap7_direct_l1.py`, `test_direct_l1_l1d_contract.py`, `test_direct_l1_corrective_r1.py` |
| tool_loop/роутер/schemas | `test_tool_loop.py`, `test_tool_router.py`, `test_tool_schemas.py`, `test_tool_calling_round1015.py` |
| FactCheck (допуск/retrieval/вердикт/рендер) | `test_factcheck_planner_cfg06.py`, `test_factcheck_orchestrator_cfg06.py`, `test_factcheck_renderer_cfg06.py`, `test_evol_fc_evidence_style.py`, `test_factcheck_attribution_cfg06.py`, `test_asap8_v6_p1_d10_temporal.py` |
| Initiative/SILENT/антифлуд | `test_asap8_f6_initiative.py`, `test_asap8_v63_b01_initiative_observer.py`, `test_p0_initfix_initiative_observer.py`, `test_soul1_w5_initiative_vitality.py` |
| Summary/Memory независимость | `test_summary_prompts.py`, `test_p0_factual_memory_prompts.py`, `test_asap8_v63_b03_memory.py`, `test_asap8_v6_p1_d09_memory.py`, `test_asap8_v6_p1_d09_deep_stages.py` |
| Prompt registry/миграции/precedence | `test_evol016_prompt_activation.py`, `test_prompt_migrations.py`, `test_asap8_v6_p1_d11_registry.py`, `test_soul1_direct_prompt_reads.py`, `test_direct_chat_prompts.py` |
| Публичная речь/guard | `test_cfg07_guard_tail.py`, `test_outgoing_guard_round1022.py` |
| Media/Vision readiness | `test_factcheck_media_2026_10_25.py`, `test_native_media_tools_round1024.py`, `test_media_transcribe_tool_round1024.py` |
| Capacity/composer | `test_direct_context_composer_asap3.py`, `test_direct_context_capacity_asap3.py`, `test_direct_fallback_recompose_asap32.py` |

### 6.2. Новые тесты (минимально необходимое)

1. `tests/test_evidence_policy_rules.py` — таблица `plan/task_kind/explicit → evidence_class/required/skip_reason` по §1.2 (входы A1–A10, B11–B18, C19–C27 логики решения).
2. `tests/test_evidence_merge_allowed.py` — `effective_readonly = allowed(union)`; C1 (`execution_mode=none` + required → `simple_tools`), C2 (low confidence не снимает required), C3 (`flags.search_enabled=off` → `USER_FORBIDS_EXTERNAL`, ноль сетевых вызовов, мок-агрегатор assert not called), RBAC/квота/SSRF.
3. `tests/test_evidence_source_reuse.py` — claim-key канон, TTL по классам, инвалидация новой версией/контрдоказательством, scope-изоляция двух чатов, «source_fetched ≠ delivered».
4. `tests/test_evidence_window_dynamic.py` — C4 (нет двойного резерва), рост evidence при большом окне, unknown-окно, отсутствие 4000/8000 как потолка (сценарий 36), section-aware fetch (37), сохранение URL/JSON/claim→source.
5. `tests/test_evidence_egress_guard.py` — один lookup/одна регенерация, взаимное исключение с freshness-ретраем, сохранение шутки (16/17), честная деградация, отсутствие второго Writer.
6. `tests/test_evidence_background_isolation.py` — 0 сетевых вызовов в Summary/Sleep/Memory на fixtures с новыми моделями/ценами (19–27), отсутствие поисковой директивы в эффективных промптах фона.
7. `tests/test_evidence_corpus_45.py` — размеченный corpus `externally_factual|attributed|background|social|transformation|runtime|historical` через реальные route/egress; считает `eligible_factual`, `verified_fresh`, `verified_reuse`, `appropriate_alternate_source`, `attempted_but_failed`, `valid_skip`, `invalid_skip`, `unnecessary_search`, `unsupported_claim_blocked`; утверждает `invalid_skip == 0` и `unnecessary_search == 0` на исключённых классах (45/46).

### 6.3. Честная граница 100%

- 100% относится **к контрактным проверкам политики на размеченных fixtures**, не к семантической точности детектора и не к доступности провайдера (§10 ТЗ);
- сценарии, требующие реального внешнего провайдера: один **безопасный read-only smoke** (без Telegram-публикаций) при возможности; иначе `NOT_OBSERVED` с точной причиной — не подмена результата;
- запрещено «улучшать KPI» подменой разметки; тест 46 сравнивает метрики до/после на одном corpus;
- один известный пред-существующий красный тест (`test_summary_publish_integration_round1026::test_on_l1_not_usable_level2_l2_publishes_article`) не относится к фиче и не маскируется как её регресс.

---

## 7. Риски

| Риск | Оценка | Мера |
| --- | --- | --- |
| Latency при 2–5 тыс. сообщений/сутки | средний | политика вызывается только для выбранных к ответу реплик; 0 сетевых вызовов для `SILENT`/`REACT`/социала/фона; bounded deadline + один lookup; кеш источников снимает повтор |
| Рост числа внешних вызовов (false positives) | средний | консервативные исключения по плану (социал/трансформация/атрибуция), corpus-тест `unnecessary_search == 0` на исключённых классах, наблюдение `network_calls` |
| False negatives (пропуск обязательной проверки) | высокий по последствиям | асимметричный дефолт «неизвестно → проверяем», запрет понижения через confidence/tool_policy, регресс A1–A10 |
| Двойной резерв/недобор evidence | средний | правка C4 + один измеритель + тест dynamic window |
| Приватность двух чатов | высокий | reuse-ключ с `chat_id` для всего непубличного; в поисковик — минимальная неперсональная сущность; ноль текстов/ID в логах |
| Рост payload инструмента | средний | `TOOL_RESULT_HARD_CEILING` (класс C) + section selection; `safe_fetch` byte-лимиты (класс A/B) не тронуты |
| Нарушение инварианта «2 LLM-вызова» | средний | egress-регенерация взаимно исключающая с freshness-ретраем, максимум 1; задокументировано как осознанное изменение worst-case (≤3 при конфликте) с kill-switch |
| Prompt regression (личность/стиль/мат) | средний | правки только 3 зарегистрированных текстов, `PREV_*`-слепки, конфликт-таблица, snapshot effective payload |
| Тестовая зависимость от живого провайдера | низкий | мок-провайдеры + один optional smoke, `NOT_OBSERVED` честно |
| Рестарт процесса и reuse | низкий | явное ограничение: после рестарта — один обычный fetch, а не «verified reuse» |

---

## 8. Параллельность, откат, приёмка

### 8.1. Карта записи (не более одного писателя на файл)

| Lane | Файлы | Класс |
| --- | --- | --- |
| **A — policy** | `services/evidence_policy.py` (new), `services/claim_key.py` (new, при выносе), `services/direct_capabilities.py`, `services/direct_l1.py` (парсер `external_claims`) | `PARALLEL_SAFE` (A не пишет `direct_chat_service.py`) |
| **B — runtime/window** | `services/direct_execution.py`, `services/tool_router.py`, `services/source_reuse.py` (new), `services/direct_chat_service.py` | `SERIALIZE` внутри lane: `direct_chat_service.py` — один писатель (нужен и policy-wiring, и window-wiring) |
| **C — prompts** | `services/chat_prompts.py`, `services/prompt_registry.py`, `services/prompt_migrations.py`, `services/param_catalog.py` | `SERIALIZE` (общий реестр/каталог; правка до любых merge) |
| **D — evidence/QA (read-only)** | `plans/features/evol/…` артефакты, `tests/test_evidence_*` (новые файлы), corpus fixtures | `READ_ONLY_PARALLEL` до момента, когда тесты начинают зависеть от A/B интерфейсов |

Правила: A и B стартуют параллельно на замороженных интерфейсах (§1.1, §4.2, §4.3 подписи); C — до первого merged-а промпт-бампа; D пишет только свои новые файлы. `BLOCKED_BY`: любые правки `factcheck_*`, `mca_vision.py`, `media_readiness.py` — владельцы других задач, здесь только интеграция.

### 8.2. Откат

- DDL нет → откат данных не требуется;
- kill-switch: `EVIDENCE_ROUTING_POLICY_ENABLED`, `EVIDENCE_WINDOW_DYNAMIC_ENABLED`, `EVIDENCE_REUSE_ENABLED`, `EVIDENCE_EGRESS_GUARD_ENABLED` (env + ClassVar по существующему паттерну `mca_gates`); OFF → прежнее поведение байт-в-байт;
- промпты: фабричная ревизия + `PREV_*`-слепок, откат по действующему precedence `EVOL-016–018`;
- код: обычный revert коммита фичи; `EVOL-SRC`, FactCheck, Vision, UI, эмбеддинги не затрагиваются.

### 8.3. Приёмка (наблюдаемое доказательство)

1. `python -m pytest tests/test_evidence_*.py tests/test_asap8_v6_wc_direct_d04.py tests/test_asap8_v6_wc_direct_matrix.py -q` — зелёные;
2. таблица 46/46 с явной привязкой «сценарий → тест/ид» и честными `NOT_OBSERVED` там, где нужен живой провайдер;
3. снимок effective payload: L1 (machine, без Core), Writer (с активным характером), Summary (без поисковой директивы) — сохранён как evidence;
4. события `EVIDENCE_POLICY_DECIDED`/`EVIDENCE_DELIVERY`/`EVIDENCE_EGRESS_CHECK` на одном учебном прогоне: `network_calls`, `delivered_to_writer`, `coverage_ratio`, `reused`;
5. матрица действующих лимитов (классы A–E) с решениями: 4000/8000 → динамика; timeout/SSRF/RBAC/квоты → сохранены;
6. ноль изменений в `web/`, `services/mca_vision.py`, `services/media_readiness.py`, `services/factcheck_*`, векторной памяти.

### 8.4. Уровень риска

**R2** (средний): меняется поведение публичных ответов и tool-пути Direct, но без DDL, без смены моделей/провайдеров, с kill-switch, слепками промптов и полным откатом.

---

## 9. Итог (обязательные три строки)

Механизм выбран детерминированный: один чистый модуль `services/evidence_policy.py` вычисляет `runtime_required` из **планируемого содержания** ответа (поля L1-плана + optional `external_claims` в том же единственном вызове), объединяет с `L1_requested` как `allowed(union)` с RBAC/запретом сети/доступностью/стоимостью/SSRF, а фон/социал/трансформация/атрибуция исключаются закрытым enum'ом с привязкой к существующим `reason_code`.

Файлы к изменению: новые `services/evidence_policy.py` и `services/source_reuse.py`; правки `services/direct_capabilities.py`, `services/direct_l1.py`, `services/direct_execution.py` (C1, C4), `services/tool_router.py` (динамический лимит + section-aware `fetch_article`), `services/direct_chat_service.py` (merge capability, упаковка evidence, bounded egress guard), промпты через `services/chat_prompts.py` + `prompt_registry.py` + `prompt_migrations.py`, тесты `tests/test_evidence_*`.

Найденные конфликты с существующими промптами/кодом: `execution_mode="none"` и `confidence=low` сейчас реально отменяют инструменты (C1/C2), рубильник «Модуль Поиск» не действует в Direct tool-пути (C3), evidence-бюджет вычитает output reserve дважды (C4); из текстов править нужно только `prompts.direct_l1_planner_system_prompt`, `prompts.direct_chat_verbalizer_system_prompt` и одну фразу в `prompts.direct_chat_system_prompt`, а Summary/Memory/Dream/фактчек-промпты не меняются, потому что поисковой директивы в них нет вовсе.
