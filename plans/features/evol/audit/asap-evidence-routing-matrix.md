# ASAP-EVIDENCE-ROUTING-01 v3 — матрица соответствия 46 сценариев и preflight-аудит

**Источник требований:** `plans/current_task.md`, строки 2008–2439 (v3; читано полностью 01.11.2026).
**Аудит выполнен по коду, не по отчётам.** Ветка `evol/impl`, HEAD `57081925`; production 2.58.145 @ `4bf3604a`.
**Режим полосы:** read-only по коду (`web/**` занят соседней UI-полосой). Изменены только артефакты аудита:
`plans/features/evol/audit/asap-evidence-routing-matrix.md` (этот файл) и `plans/features/evol/audit/limits-audit.md`.
**Примечание:** в рабочем worktree отсутствует `plans/current_task.md` (user-owned файл не в ветке) — требования читались из канонического корня `C:\Code\Python\adminbot`; код проверялся в worktree.

## 0. Легенда и честные границы аудита

| Состояние | Значение |
|---|---|
| `DONE_AND_VERIFIED` | поведение существует в коде и имеет проверяемое доказательство (код-путь + тест/route/структурный инвариант) |
| `PARTIAL` | механизм есть частично (примитив/один из путей), полного контракта сценария нет |
| `MISSING` | требуемого механизма нет |
| `CONFLICTS_WITH_NEW_CONTRACT` | действующее осознанное поведение прямо противоречит v3 и должно быть изменено, а не «дополнено» |
| `NOT_APPLICABLE` | сценарий закрыт другой полосой и в этой задаче не даёт delta |

Метод: чтение реальных путей `direct_l1 → _l1_tool_subset → _l1_tool_phase → tool_loop/tool_router → EvidencePack → Writer`,
`initiative_observer → Decision → Direct`, `factcheck_*`, `summary_*`, `dream_worker`, `mca_vision/media_readiness`,
`prompt_registry.factory_text` (реально активные тексты, 111 блоков), плюс AST-скан числовых лимитов (см. `limits-audit.md`).

Честные ограничения:
- Семантического судьи утверждений в коде нет — это признано самим ТЗ (§4.6). Сценарии, требующие «определить, есть ли у бота собственный внешний claim», нельзя закрыть `DONE` без нового минимального runtime-механизма; ниже они помечены как `MISSING`, а не «работает за счёт промпта».
- Для `NOT_OBSERVED` в этой матрице ничего не заявляется: живых проверок в боевых чатах не выполнялось (запрет ТЗ §11.5).
- 46 «контрактных тестов» (§10) сейчас отсутствуют как класс: в `tests/` нет ни одного теста на `runtime_required/evidence_policy/low-confidence+tool`, а формат «0 необоснованных skip» нечем измерить (нет счётчиков §10.46). Поэтому многие поведенческе корректные строки помечены `PARTIAL`: поведение держится конструкцией, а не контрактом.

## 1. Что уже поставлено соседними полосами (не переделывать)

| Полоса | Факт в коде на HEAD | Что из v3 закрывает |
|---|---|---|
| `ASAP-FC-ADMISSION-01` | `services/factcheck_suitability.evaluate_suitability` (предикат/литерал/адресат), reply/media-target через `factcheck_attribution.py`, `claim_envelope.py` (атрибуция/цитаты) | A2 (admission), C21/C27 (атрибуция при извлечении) |
| `ASAP-FC-EVIDENCE-STYLE-02` | `factcheck_planner`: claim units с `claim_id` (`factcheck_planner.py:193-260,720,797,1419`), per-claim queries `queries_for(claim_id)` (`:317`), `_MAX_PRIMARY_FETCHES=2` (`:150`), source→claim link (`:1363,1393`), `search_aggregator.claim_relevance` + роли `supports/contradicts/qualifies/background_only` (`search_aggregator.py:214-226,356`) | A2, A10 (внутри FactCheck), C25 (частично) |
| `ASAP-VISION-SYNC-01` + watchdog | `services/media_readiness.py` (единый barrier), `mca_vision` readiness/pending/lease, `MCA_VISION_READINESS_WAIT_SECONDS=20`, `pending_intent_ttl`, `job_max_recoveries` | D34 (ожидание только нужного медиа) |
| `EVOL-SRC-*` | **не поставлено**: в `tool_schemas.py` нет ни одного source-code reader (список из 15 инструментов), `grep read_source_code/source_reader` — 0 совпадений | A3, D35 — остаются за EVOL-SRC (queued) |
| `EVOL-016`–`018` | реестр промптов: 111 блоков, `FACTORY_REVISION_SEALS`, `registry_view()`; `effective_prompt()` (`prompt_registry.py:2814`) с потребителями `prompt_factory.py:1081`, `capability_registry.py:1023` | F42/F43 — каркас есть (EVOL-042 resolver = DONE на уровне API) |
| `EVOL-042` | effective-prompt resolver есть; UI Inspector в этой полосе не проверялся | F42 требует снапшота effective payload |
| `EVOL-031` | replay готовых ответов снят: `services/smart_cache.py:1-25` (ответы не хранятся/не воспроизводятся) | снят конфликт с §4.5; сам claim-bound reuse **не** создан |
| `EVOL-034/040` | один canonical setting/write path для модулей/бюджетов (проверено по `param_catalog.py`, `hot_config`) | не создавать второй toggle поиска |
| `EVOL-006` (memory) | `memory.fact_extract` промпт: классы `durable_fact/world_news/quote/hypothetical_character`, `source_message_ids` (`prompt_registry.factory_text('memory.fact_extract')` строки 15–29), seal `fact-extract-evol006` | C21, C22, C27 (семантика атрибуции в памяти) |

## 2. Матрица A–F (46 сценариев)

### A. Обязательность Search/Fetch/Source Reader и честный статус (1–10)

| № | Требование (v3) | Состояние | Доказательство (факт кода) | Минимальная дельта | Владелец |
|---|---|---|---|---|---|
| 1 | «погугли» + `confidence=low` → Search реально вызван, отказ L1 не причина skip | **MISSING** | Нет `runtime_required`. Детерминированный детектор поручения есть (`direct_capabilities.py:535` `_SEARCH_MARKERS → INTENT_WEB_SEARCH`), но единственный runtime-потребитель — image-прегейт (`direct_chat_service.py:8629-8632`); при `confidence=low` L1-способности выкидываются (`direct_chat_service.py:5073-5090`), инструменты не анонсируются | доказать `runtime_required = policy(task, query_intent, plan)` и `effective_readonly = allowed(L1_requested ∪ runtime_required)` до `_l1_tool_subset` | Builder (Direct evidence) + Architect (freeze контракта) |
| 2 | «проверь тезис» + reply → FactCheck получает правильный claim/target, не заменяется snippet | **DONE_AND_VERIFIED** (полоса FC) | `factcheck_suitability`, `factcheck_attribution`, `factcheck_planner` claim units/`claim_id`, per-claim queries | нет в этой задаче; только не ломать (§5.3 запрещает второй preflight внутри FC) | FC lane (владелец), PM — контроль регресса |
| 3 | «найди файл/реализацию» без URL → Source Reader открывает файл или честный ограничитель | **MISSING** | Инструментов чтения кода нет (`tool_schemas.py`: 15 инструментов, среди них нет source-code reader); EVOL-SRC queued | не реализовывать здесь; связать evidence policy с будущим `EVOL-SRC` (только вызов существующего контракта) | EVOL-SRC lane, PM — dependency edge |
| 4 | Технический вопрос без «погугли», `capabilities_needed=[]`, `tool_policy=none`, `confidence=high` → обязательный runtime-readonly evidence | **CONFLICTS_WITH_NEW_CONTRACT** | Инструменты выдаются только по L1 (`direct_chat_service.py:3867-3885` → `_l1_tool_subset` по `plan.capabilities_needed`); legacy-путь дополнительно гейтит детерминированный план по `response_plan.tool_policy != "none"` (`:3911-3913`); `build_tool_plan` требует ≥2 URL + маркер (`response_extent.py:657-720`) | policy должна переопределять `tool_policy=none` для read-only evidence; side-effect tools остаются под L1/RBAC | Builder + Architect |
| 5 | L1 запросил web, low-confidence skip убирает capability → runtime восстанавливает required capability | **CONFLICTS_WITH_NEW_CONTRACT** | `_l1_tool_subset`: `skip = tuple(plan.capabilities_needed)` при `low` (`direct_chat_service.py:5073-5080`) → `resolve_capabilities(..., skip_capabilities=skip)` → reason `low_confidence` (`direct_capabilities.py:58,94`); намеренно (SOUL-1 §1.3) | не поднимать confidence: разделить skip на `side_effect` (оставить) и `read_only` (не скипать) | Builder |
| 6 | `execution_mode=none` не скрывает обязательную внешнюю проверку; Initiative `SILENT` не становится reply | **PARTIAL** (две половины: SILENT — DONE, `none` — CONFLICTS) | SILENT-короткое замыкание до инструментов: `direct_chat_service.py:3497-3527`; но `_l1_tool_phase` возвращает `None` при пустых схемах (`:5137-5141`) | шаг обязательной проверки не должен зависеть от `execution_mode`, вычисленного из L1-схем | Builder |
| 7 | Категорическое «модель X не существует» → нужен проверенный источник либо нельзя публиковать | **MISSING** | Исходящего claim-guard нет; есть только грубый детектор «проверил весь интернет» (`public_speech_guard.py:245-253`, потребители `:459,506,616`) | bounded egress guard (§4.6) + запрет категорического несуществования из `no_results` (`tool_router.py:1148-1149` даёт «поиск недоступен (empty result)») | Builder (egress) |
| 8 | Только snippets, страница не прочитана → статус не `source_fetched/claim_verified`, Writer не говорит «прочитал документацию» | **PARTIAL** | Агрегатор отдаёт `title/snippet/url` (`search_aggregator.py:708-751`), отдельный `fetch_article` возвращает `status/url/source_id/chars/truncated` (`tool_router.py:2204-2279`) — но нет `source_read_level` и нет проверки публичного текста на «прочитал» | ввести `source_read_level` в trace/envelope и один адресный возврат при ложном «прочитал» | Builder |
| 9 | 403/404/429/timeout/пустая выдача → честная деградация, без «не существует» | **PARTIAL** | Структурные ошибки есть: `timeout`, `extract_failed`, `empty`, `no_url`, `destination blocked` (`tool_router.py:2236-2269`), `SafeFetchError(code,stage,reason,retryable)` (`safe_fetch.py:89-106`); `Retry-After`/backoff отсутствуют; запрета на вывод «не существует» нет | маппинг `reason_code`→честная формулировка в egress; `Retry-After` для retryable | Builder (retrieval) + DevOps (provider) |
| 10 | Два источника расходятся → сохранить оба, различить `conflicting/event_date/publication_date` | **PARTIAL** | Роли `supports/contradicts/qualifies` и `claim_relevance` существуют (`search_aggregator.py:214-226,356`) — используются FC-путём; в Direct-path к Writer идут только `title/snippet/url` блоками (`:749-751`), дат публикации/события нет | не терять роли/даты при передаче в Writer; добавить их в EvidencePack источник-поля | Builder (evidence contract) |

### B. Социальное общение без переусердствования (11–18)

| № | Требование | Состояние | Доказательство | Минимальная дельта | Владелец |
|---|---|---|---|---|---|
| 11 | «лол»/приветствие → 0 внешних вызовов и 0 доп. LLM-check | **PARTIAL** (поведение держится конструкцией, теста нет) | Автопоиска нет: единственные вызовы — по L1-capabilities (`direct_chat_service.py:3867+`) или по ≥2 URL (`response_extent.py:657-720`); L1-промпт прямо исключает болтовню (`factory_text('direct.base.l1_planner')` правило 4) | фикстура «0 network calls на 4 social fixtures» | Builder (тесты) |
| 12 | Разговор о GPU, ответ только сарказмом → веб не запускается, хотя тема техническая | **MISSING** | Нет понятия `NO_NEW_EXTERNAL_CLAIM`; тематическая эвристика не запрещена, L1 вправе запросить web по «технической теме» (правило 4) | reason-code `NO_NEW_EXTERNAL_CLAIM` из планируемого содержания, не из темы входа | Builder |
| 13 | «На каком железе запускал?» — вопрос без внешнего утверждения | **MISSING** | Того же механизма нет; `self_status` не выделен в policy | классификация `self_status` → `SUFFICIENT_RUNTIME_SOURCE` | Builder |
| 14 | «Лёха говорил, что у X 5 ГБ» — атрибутированный пересказ, Search не принуждать | **PARTIAL** | Атрибуция есть: `claim_envelope.classify_speech_act/_reported_speech` (`claim_envelope.py:337-380`), `direct_capabilities._reported_speech` (`:368`), FC-attribution; в evidence policy не подключено | подключить существующую атрибуцию как основание `ATTRIBUTED_HISTORY_OR_SUMMARY` | Builder |
| 15 | «У X официально 5 ГБ» как новый claim → проверка обязательна (даже с шуткой) | **MISSING** | То же, что №4/№12: при `capabilities_needed=[]` инструментов нет | runtime policy из планируемых claims L1 (поле уже есть в плане — `response_act/capabilities_needed`), без нового классификатора | Builder + Architect |
| 16 | Writer добавил новый claim в шутку → один адресный fetch/rewrite либо удаление добавки, шутка остаётся | **MISSING** | Egress ограничен формой/метатекстом (`public_speech_guard.guard_public_text`), claim-сверки нет | один bounded возврат к tool path + безопасное удаление именно claim | Builder |
| 17 | Яркая метафора без проверяемого факта → egress не запускает веб и не затирает стиль | **MISSING** (нет guard → свойство нечего проверять) | — | фикстура «guard не срабатывает на метафору/мат» вместе с №16 | Builder |
| 18 | Просьба «одно слово» + внешний факт → проверка выполняется, публичный ответ остаётся кратким | **PARTIAL** | Краткость управляема (`response_extent`: `ONE_WORD_MAX=1`, `MICRO_REPORT_MAX_WORDS=16`), evidence отделён от публичного текста (`EvidencePack` → Writer) — но проверки не будет без №4 | №4 + тест «extent=one_word, evidence present» | Builder |

### C. Summary/Sleep/Memory не заражены поиском (19–27)

| № | Требование | Состояние | Доказательство | Минимальная дельта | Владелец |
|---|---|---|---|---|---|
| 19 | Плановая Summary по 500 сообщениям → 0 внешних поисковых вызовов | **DONE_AND_VERIFIED** (структурно) | В `services/summary_*` нет импортов `SearchService/SearchAggregator/WebContentExtractor` (grep 21 совпадение — все в factcheck/tool_router/web_*, ни одного в summary/dream/memory). Источник — `summary_source_window`, `summary_execution_input` | зафиксировать инвариант тестом-«запрет импорта» (чтобы будущая правка не протащила web) | Builder (тест) |
| 20 | Sleep/Deep Sleep → 0 web calls; расписание/модельные вызовы не изменились | **DONE_AND_VERIFIED** | `dream_worker.py` без web-импортов; промпты `internal.dream.distill/deep_sleep_bridge` без директив о поиске (`factory_text`) | тот же тест-инвариант | Builder (тест) |
| 21 | Memory Extraction сохраняет «участник утверждал X», не как внешнюю истину | **DONE_AND_VERIFIED** | `memory.fact_extract` (seal `fact-extract-evol006`): классы `world_news/quote/hypothetical_character`, «Публичный факт не становится личным фактом участника», обязательные `source_message_ids` (строки 15–29 factory_text) + `claim_envelope` валидаторы | нет | EVOL-006 владелец |
| 22 | Досье/GraphRAG — внутренняя атрибуция, без автофактчека, исходное сообщение не удаляется | **PARTIAL** | Промпты `internal.dossier.*`, `graphrag_provenance.py`, `graphrag_stoplist` существуют и не содержат web-директив; но нет теста «0 web + исходник сохранён» | тест-инвариант на dossier/graphrag | Builder (тест) |
| 23 | Публичный пересказ Summary «участники спорили о X» — без веба и без «X подтверждено» | **PARTIAL** | `summary.base.l2_writer`: «Внешнюю реальность не «допроверяй» сама: …«в чате обсуждали новость о...», а не «событие действительно произошло»» (строка 30) — сильно выровнено; публичный пересказ идёт тем же Direct-путём, где веб может включиться по L1 | не добавлять web в summary; публичная ветка подчиняется №4/№12 | Builder |
| 24 | Публичный пересказ + своя новая цена/версия → проверяется только добавка | **MISSING** | Механизма «diff нового claim» нет | часть bounded egress guard (§4.6) | Builder |
| 25 | «Саммари и проверь, кто прав» → две различимые фазы, история неизменна | **PARTIAL** | Раздельные сервисы есть (`summary_generator` vs `fact_check` tool / `factcheck_*`); явного разбиения поручения нет — решает L1 | правило разделения фаз в L1/ResponsePlan + тест «summary не переписан FC» | Builder |
| 26 | Трансформация/перевод текста не правит «истину» | **DONE_AND_VERIFIED** (структурно) | Нет пути, где transform-стадия вызывает web; тексты задач не содержат «проверь факты» | тест-инвариант (0 calls) | Builder (тест) |
| 27 | Чужой репост/новость/персонаж не становятся личным фактом и не подтверждаются вебом в extraction | **DONE_AND_VERIFIED** | `memory.fact_extract` строки 19–26 + `summary.base.l2_writer` строка 48 («Пересланное сообщение: содержание принадлежит источнику пересылки») | нет | EVOL-006 владелец |

### D. Initiative, память разговора, alternate source (28–35)

| № | Требование | Состояние | Доказательство | Минимальная дельта | Владелец |
|---|---|---|---|---|---|
| 28 | Initiative `SILENT` → 0 поисковых запросов, 0 сообщений, антифлуд не изменён | **DONE_AND_VERIFIED** | `initiative_observer.py:1727-1733` (silent-вердикт, counters), `:1825-1833`; web-импортов в модуле нет; квоты `INITIATIVE_MAX_REPLIES_PER_DAY=6`, `MIN_GAP=7200`, `PER_TOPIC=1` | нет | Initiative владелец |
| 29 | Initiative делает внешний claim → тот же evidence/status, что Direct | **MISSING** | Инициативная публичная реплика проходит через Direct-пайплайн (наблюдаемый `l1_silent` в `initiative_observer.py:891,1784`), значит наследует отсутствие policy (№4) | после №4 — проверить, что policy применяется и на initiative-ветке | Builder |
| 30 | Повтор о том же проверенном claim, источник свежий → `verified_reuse`, 0 нового поиска, Writer получает выдержку/URL | **MISSING** | Claim-bound кеша источников нет. `smart_cache` после EVOL-031 хранит только технические маркеры (`smart_cache.py:1-25`); примитивы для reuse есть (`claim_relevance`, `source_id` в `fetch_article`, `claim_key` в `claim_envelope.py:177`) | кеш «прочитанных источников с claim-key/freshness», не кеш ответов | Builder + Architect |
| 31 | Версия/дата/параметр изменились или контрдоказательство → reuse не засчитывается, адресный новый fetch | **MISSING** | Инвалидации нет (её негде применить) | freshness/инвалидация внутри той же row 30 | Builder |
| 32 | «Что ты писал вчера?» → история/ID, 0 web, без выдуманных цитат | **DONE_AND_VERIFIED** | Инструменты `query_chat_memory` (`tool_router.py:1154+`, FTS/vec лимиты), `get_recent_history` с keyset-пагинацией и `cursor` (`:3529-3546`), attribution в промптах памяти | нет | Direct/memory владельцы |
| 33 | «На какой модели работаешь?» → effective route/fallback фактического вызова, 0 web | **MISSING** | Фактическая модель известна клиенту (`llm_client.py:1417,1495,1534` `used_model`), но в payload Direct/Writer не попадает; отдельного route-инструмента нет (`get_bot_health` — про checkup, `tool_router.py:3503-3527`) | добавить effective-route факт в машинный контекст Writer + тест «не угадывает» | Builder |
| 34 | Скриншот — источник запроса → ждать только относящийся OCR, одна проверка, без повторного Vision и вечного ожидания | **PARTIAL** (ready-часть — DONE полосой Vision) | `media_readiness` единый barrier, `MCA_VISION_READINESS_WAIT_SECONDS=20` (settings), `MCA_VISION_REOCR_BUDGET=2`, `job_max_recoveries`, `PENDING_INTENT_TTL` | «одна связанная проверка» — из evidence policy (№4) | Vision владелец + Builder |
| 35 | Код из файла пользователя — локально; внешняя зависимость читается только при внешнем claim | **PARTIAL** | Локальный текст доступен как контекст; внешнее чтение кода невозможно (нет reader, см. №3) | ждать EVOL-SRC; не подменять выдуманным «прочитал» (№8) | EVOL-SRC + Builder |

### E. Dynamic capacity / bounded recovery / безопасность (36–41)

| № | Требование | Состояние | Доказательство | Минимальная дельта | Владелец |
|---|---|---|---|---|---|
| 36 | Релевантный URL за пределами 4k-среза → находится и доступен для fetch; простая замена на 16k не засчитывается | **MISSING** | `_SEARCH_MAX_SYMBOLS = 4000` (`tool_router.py:91`), применение: `search(..., max_symbols=4000)` (`:1136`) и повторный срез `_truncate(text, 4000)` (`:1150`); `_truncate` — слепой срез + «…» (`:715-720`). Также `SEARCH_MAX_SYMBOLS=4000` в `settings.py:2125` / hot `limits.search_max_symbols` (`search_service.py:78-84`) | убрать 4000 как «потолок качества»: индексировать кандидатов и не терять URL; связать с dynamic window | Builder (P0) |
| 37 | Нужная часть документа после 8k → section-aware fetch/chunking с provenance и указателем на полный источник | **MISSING** | `WebContentExtractor.extract(url, max_symbols)` → `text[:max_symbols]` (`web_content_extractor.py:83-114,243-246`), `include_links=False` (`:185`); `fetch_article` даёт только `chars/truncated` (`tool_router.py:2270-2273`), без section/offset/remainder | `offset/section/line_range` + `full_source_pointer` в существующем `fetch_article` (не новый reader) | Builder (P0) |
| 38 | Большое окно → реальная ёмкость используется по необходимости, без потери Core/reply/OCR, без принудительного заполнения | **PARTIAL** | Динамика уже есть: `l2_evidence_budget_chars(input_budget_tokens, other_chars, output_reserve)` — `min(40% бюджета, бюджет − прочее − reserve)` с floor ( `direct_execution.py:911-931`), применяется в `direct_chat_service.py:4223-4244`; discovery окна реальный (`model_capacity` адаптеры openrouter/nanogpt/llama.cpp/ollama/vllm, TTL, `source`) | evidence cap применяется **после** жёстких 4k/8k: окно не спасает уже потерянное; нет per-claim распределения | Builder (P1) |
| 39 | Маленькое/unknown окно — `claim→source` не теряется, URL/JSON не режется, overflow через retrieval, причины наблюдаемы | **CONFLICTS_WITH_NEW_CONTRACT** | Слепой срез режет URL/JSON/пары (`tool_router._truncate:715-720`, `web_content_extractor._truncate:243-246`); маркер только «…»; `retrievable_remainder` нет. Контраст: в том же файле уже есть правильный образец — пагинация истории с `cursor/remaining/has_next` (`tool_router.py:3529-3546`) | ввести структурный truncation-конверт (`effective_limit/source/used/truncated/why/remainder`) и не резать внутри URL/JSON/citation | Builder (P0) |
| 40 | Медленный/зависший Search + restart → bounded retries/timeout, одна завершённая операция или честный terminal status | **PARTIAL** | Конечные таймауты: `_SEARCH_TOOL_TIMEOUT=25`, `_ARTICLE_TOOL_TIMEOUT=45` (`tool_router.py:96,130`), tool-loop `TOOL_CHAIN_TIMEOUT_SECONDS=360` (`tool_loop.py:47`), оркестратор с ER-08 резолвит ТОТ ЖЕ дедлайн (`direct_execution.orchestrator_max_time_seconds` → `MCA_TOOL_CHAIN_TIMEOUT_SECONDS`, дефолт 360; прежняя отдельная ось 90 с снята как преждевременный обрыв), rounds/calls caps (`tool_loop.py:44-53`); `retryable` в `SafeFetchError` | `Retry-After`/backoff и durable continuation для поиска отсутствуют; нет проверки «одно сообщение» при рестарте | Builder + DevOps |
| 41 | Запрет сети/RBAC/приватный текст/prompt-injection → 0 запрещённых действий, без утечек, hard guards целы | **DONE_AND_VERIFIED** | SSRF/схемы/credentials/redirect: `safe_fetch.py:37-42,89-106`, `aguarded_target`; capability-готовность/квоты per-chat: `capability_registry.py:44-52,478-508`; нет network-opt-out ключа, но выключение модуля = 0 вызовов; инструкция «считать документы данными» в Writer (`direct.base.l2_writer` строка 13) | добавить reason-code `USER_FORBIDS_EXTERNAL`/`RBAC_OR_PRIVACY_BLOCKED` в trace (не менять сами guards) | Builder (trace) |

### F. Effective prompts / регрессии / измерение охвата (42–46)

| № | Требование | Состояние | Доказательство | Минимальная дельта | Владелец |
|---|---|---|---|---|---|
| 42 | Полный effective-prompt trace L1/Writer/FactCheck/Initiative + fallback: нет «гугли всегда» / «не пользуйся tools»; машинные промпты без Core-сарказма, публичные — с характером | **MISSING** (аудита нет; конфликт найден — см. §6) | `factory_text` реально активных блоков: L1 `l1-planner-tech-reasoning`, Writer `l2-writer-tech-reasoning`, tool_phase `toolphase-search-decision`, FC `factcheck-r1022`/`factcheck-analyst-r1023-f3`, summary `summary-l2-writer-p0-factual`, memory `fact-extract-evol006`, core `asap-core-full-v4`. Прямых «гугли всегда» нет; конфликтующие формулировки перечислены в §6 | провести аудит по §6 и зафиксировать снапшот payload (секреты редактируются) | Builder + Reviewer |
| 43 | Summary/Sleep/Memory не получили глобальную директиву «обязательно веб-проверять»; Registry/precedence без потери ручных редакций | **PARTIAL** | В промптах summary/memory/dream таких директив нет (`factory_text` проверены); реестр с печатями `FACTORY_REVISION_SEALS` и `effective_prompt` работает | тест-«запрет директивы» + снапшот активных ревизий до/после | Builder |
| 44 | FactCheck/Source Reader/Vision/SearchAggregator переиспользованы; прежние PASS сохранены; стекло/UI/эмбеддинги не тронуты | **PARTIAL** | Переиспользование реально: `tool_router` берёт общий `extractor` (`:967-970`), FC берёт общий `SearchAggregator` (`factcheck_service.py:63`), Vision — `media_readiness`; Source Reader отсутствует (EVOL-SRC) | ничего не переписывать; добавить регресс-тест «один контур» | Builder |
| 45 | Размеченный корпус (`externally_factual/attributed/background/social/transformation/runtime/historical`) через реальные routing+egress: 0 необоснованных skip, 0 лишних вызовов | **MISSING** | Ни корпуса, ни harness: в `tests/` нет упоминаний `runtime_required/evidence_policy/must_retrieve` (grep 0) | создать offline-корпус + harness (мок-провайдеры, реальные route/tool/serializer/effective prompt) | Builder + Reviewer |
| 46 | Счётчики `eligible_factual/verified_fresh/verified_reuse/appropriate_alternate_source/attempted_but_failed/valid_skip/invalid_skip/unnecessary_search/unsupported_claim_blocked` + latency/calls до-после | **MISSING** | Событий/метрик с такими именами нет (grep `evidence_delivered` = 0); существующие `pipeline_events`/`agentic_events` не покрывают evidence-политику | добавить поля в существующие события (§4.7), без нового экрана | Builder + DevOps (аналитика) |

## 3. Сводка состояний

| Состояние | Кол-во | Номера |
|---|---|---|
| `DONE_AND_VERIFIED` | 9 | 2, 19, 20, 21, 26, 27, 28, 32, 41 |
| `PARTIAL` | 16 | 6, 8, 9, 10, 11, 14, 18, 22, 23, 25, 34, 35, 38, 40, 43, 44 |
| `MISSING` | 18 | 1, 3, 7, 12, 13, 15, 16, 17, 24, 29, 30, 31, 33, 36, 37, 42, 45, 46 |
| `CONFLICTS_WITH_NEW_CONTRACT` | 3 | 4, 5, 39 |
| `NOT_APPLICABLE` | 0 | — |

Итого 9 + 16 + 18 + 3 = **46**. Дополнительно: в №6 «SILENT»-половина — `DONE` (короткое замыкание работает), а «`execution_mode=none` скрывает проверку» — конфликтующее поведение, зафиксированное в §4.1 (строка целиком учтена как `PARTIAL`, чтобы не двойной счёт).

## 4. Ключевые дельты (по приоритету P0)

### 4.1. `runtime_required` preflight отсутствует, а действующий контракт его исключает

- Нет ни одного вхождения `runtime_required|must_retrieve|evidence_policy` (grep по репозиторию — 0).
- Точка, где L1 получает последнее слово: `direct_chat_service.py:3867-3885` → `_l1_tool_subset` (`:5055-5105`) → схемы только из `plan.capabilities_needed`.
- Два явных запрета:
  1. `confidence_bucket == "low"` → `skip = capabilities_needed` (`:5073-5080`), причина `low_confidence` (`direct_capabilities.py:58`).
  2. legacy-путь: детерминированный план режется по `response_plan.tool_policy != "none"` (`direct_chat_service.py:3911-3913`).
- Что уже готово к переиспользованию: детектор поручения (`detect_action_intent`, `direct_capabilities.py:419-535`, включая `_SEARCH_MARKERS`/`_FACTCHECK_MARKERS`/`_MEMORY_MARKERS`), allowlist (`resolve_capabilities`), capability-готовность/квоты (`capability_registry`), `active_tools`.
- Минимальная дельта: одна функция политики до `_l1_tool_subset` (`effective_readonly = allowed(L1_requested ∪ runtime_required)`), где `runtime_required` выводится из (а) детектированного явного поручения, (б) планируемых claim-полей L1-плана, (в) статуса «нет локального авторитетного источника»; `allowed()` сохраняет RBAC/сеть/квоты/безопасность; `confidence` не меняется.
- Владелец: Architect фиксирует контракт функции и поля trace; Builder реализует в `direct_chat_service`/`direct_capabilities` без второго классификатора.

### 4.2. Жёсткие срезы 4000/8000 и слепая обрезка (P0)

- `_SEARCH_MAX_SYMBOLS=4000` (`tool_router.py:91`) применяется дважды: как `max_symbols` для агрегатора (`:1136`) и как повторный `_truncate` (`:1150`).
- `_ARTICLE_MAX_SYMBOLS=8000` (`:131`) уходит прямо в `WebContentExtractor.extract` (`:2234`) → `text[:max_symbols]` (`web_content_extractor.py:114,243-246`).
- `_truncate` (`tool_router.py:715-720`) режет по символу и добавляет «…» → рвёт URL/JSON/пары `claim→source`, remainder недоступен.
- Динамический бюджет существует, но применяется ниже по потоку (`direct_execution.l2_evidence_budget_chars`, `direct_chat_service.py:4223-4244`) — то есть окно модели не может вернуть уже отрезанное.
- Минимальная дельта: (1) поиск отдаёт индекс кандидатов (title/url/сниппет) без потери URL; (2) `fetch_article` получает `offset/section/line_range` + `remainder` и не режет внутри токенов; (3) cap evidence берётся из существующего resolver; (4) события `effective_limit/source/used/truncated/why/remainder`.
- Владелец: Builder (P0), Architect — только форма конверта и совместимость с `EvidencePack`.

### 4.3. Qualified claim-bound reuse отсутствует (P0 для повторного диалога)

- Кеш ответов снят (EVOL-031, `smart_cache.py:1-25`) — это правильно, но замены нет.
- Примитивы: `claim_key`/`normalize_proposition` (`claim_envelope.py:177`), `claim_relevance`/роли (`search_aggregator.py:214-226,356`), `source_id` (`tool_router.py:2225`), `retrieved_at` в provenance-слое.
- Минимальная дельта: краткоживущий кеш **прочитанных источников** с ключом (сущность+предмет+версия+дата+метрика), freshness по типу claim, инвалидация на контрдоказательство/новый анонс, scope per-chat.
- Владелец: Architect (схема ключа/политика freshness), Builder (реализация), DevOps (наблюдаемость).

### 4.4. Исходящий claim-guard (P0 для «не заявлять проверенное»)

- Есть только «не заявляй, что проверил весь интернет» (`public_speech_guard.py:245-253`).
- Минимальная дельта: в существующем egress сравнить планируемые/фактические существенные внешние claims, при новом неподтверждённом — один адресный возврат к tool-пути или безопасное удаление именно claim; без второго Writer и без цикла.
- Владелец: Builder; Reviewer — тесты false-positive (метафора/мат/атрибуция) и false-negative (категоричное «не существует»).

### 4.5. Фоновая независимость — сохранена, но не закреплена контрактом

- Структурно верно: в `services/summary_*`, `dream_worker`, `summary_memory`, `dossier_*` нет web-импортов.
- Риск: любая будущая правка может протащить web; нужен тест-инвариант (AST/импорт-запрет) + запрет добавлять `must_retrieve` в фоновые стадии.

### 4.6. Наблюдаемость и измерение отсутствуют

- Нет счётчиков §10.46 и нет `evidence_delivered_to_writer` (grep 0). Без них §10.45/46 и DoD не проверяемы.
- Минимальная дельта: поля в существующих событиях (`pipeline_events`/`agentic_events`), без нового экрана (согласуется с §9 EVOL-022/033/ASAP-UI-02).

## 5. Зависимости и волны (для Orchestrator)

| Волна | Содержимое | Зависит от | Параллельность |
|---|---|---|---|
| W0 (read-only, сделано) | эта матрица + лимиты + prompt pre-map | — | — |
| W1 | §4.1 policy (`runtime_required`) + trace reason-codes | freeze контракта Architect | с W2 (разные файлы), не с W3 |
| W2 | §4.2 dynamic evidence window / source fetch paging / анти-слепой срез | — | параллельно W1 (tool_router vs direct_chat_service) — но `tool_router.py` один владелец |
| W3 | §4.3 claim-bound reuse + §4.4 egress guard | W1 (нужны planned claims) | serial после W1 |
| W4 | промпты (§6: только реально конфликтующие) | W1 (иначе директива повиснет) | serial с W1 по prompt-registry файлам |
| W5 | корпус §10.45 + счётчики §10.46 + 46 тестов | W1–W4 | serial (тесты поверх всего) |

Занятые полосы (не трогать): `web/**` (UI lane), `services/factcheck_*` (FC lane), `services/mca_vision.py`/`media_readiness.py` (Vision lane).

## 6. Prompt Conflict Pre-Map (§7) — обязателен ДО изменения текстов

Источник ревизий: `services/prompt_registry.registry_view()` + `factory_text()` (реально активные заводские тексты). Живые PG-редакции (manual/chat/custom) в этой полосе недоступны — их обязан снять effective-prompt Inspector (EVOL-042) перед правкой; ниже — заводские ревизии, на которых проверялись формулировки.

### 6.1. Карта активных путей, которые затрагиваются

| Стадия / `prompt_id` | Заводская ревизия (seal) | Scope / речь | PG ключ | Потребитель |
|---|---|---|---|---|
| L1 план — `direct.base.l1_planner` | `l1-planner-tech-reasoning` | global / machine | `prompts.direct_l1_planner_system_prompt` | `direct_l1` |
| Tool-phase (SP) — `direct.base.tool_phase` | `toolphase-search-decision` | global_chat / speech | `prompts.direct_chat_system_prompt` | legacy direct + tool loop |
| Writer — `direct.base.l2_writer` | `l2-writer-tech-reasoning` | global / speech | `prompts.direct_chat_verbalizer_system_prompt` | `_l2_write_answer` |
| Синтезатор — `direct.base.synthesizer` | `synthesizer-r1023` | global / machine | `prompts.direct_chat_synthesizer_system_prompt` | evidence→facts JSON |
| Сегмент истории — `direct.history_segment` | `history-segment-w2b` | code / machine | — | `collect_history_segments` |
| Режимы вербализатора — `verbilizer.mode.{default,casual,serious,deep_research}` | `mode-r1024`, `mode-r1023`, `mode-r1023`, `mode-no-meta-lexical` | global / speech | `prompts.verbilizer_*` | рендер |
| FactCheck single — `factcheck.base.single` | `factcheck-r1022` | global / speech | `prompts.factcheck_system_prompt` | `factcheck_service.py:181` |
| FC аналитик — `factcheck.base.analyst` | `factcheck-analyst-r1023-f3` | global / machine | `prompts.factcheck_analyst_system_prompt` | FC verdict |
| FC вербализатор — `factcheck.base.verbalizer` | `factcheck-verbalizer-w1` | global / speech | `prompts.factcheck_verbalizer_system_prompt` | публичная речь FC |
| FC критика — `factcheck.critique.directive` | `factcheck-critique-w5` | code / speech | `prompts.factcheck_critique_directive` | разнос |
| Temporal — `temporal.analyst`/`temporal.validator`/`temporal.fallback` | `temporal-*-fc08` | code / machine | — | temporal FC |
| Initiative — `internal.initiative_observer`, `internal.observer_digest` | `initiative-observer`, `observer-digest-w2a` | code / machine | — | `initiative_observer` |
| Summary — `summary.base.{single,l2_writer,narrator,editor,l1_clusterizer}`, `summary.l1.anchors`, `summary.l2.{reviewer,reviser}` | `summary-cfg07a`, `summary-l2-writer-p0-factual`, `summary-narrator-legfix`, `summary-editor-r1025-hotfix4`, `summary-l1-clusterizer-asap41`, `*-w2a` | global/code | `prompts.summary_*` (часть) | summary pipeline |
| Memory — `memory.{extract,compress,fact_extract,fact_retry,memorize_compress,chat_rag_rerank}` | `extract-etl`, `compress-canon`, `fact-extract-evol006`, `fact-retry-evol006`, `memorize-compress-w2b`, `chat-rag-rerank-w2b` | global/code / machine | `prompts.extract_system_prompt`, `prompts.compress_system_prompt` | memory/GraphRAG |
| Core / Expression / Style — `core.personality` (+compact), `style.policy.hint`, `style.bot_knowledge`, `style.format.*`, `retry.*` | `asap-core-full-v4`, `asap-core-compact-v4`, `style-hint-soul16-w3`, `bot-knowledge-r1021`, `format-*-*`, `retry-*-*` | global_chat / speech | `character.core` и др. | сборка payload |
| Поиск — `search.base.system`, `search.rerank` | `search-cfg07a`, `search-rerank-w2b` | global/code / speech | `prompts.search_system_prompt` | `SearchService.research` |

### 6.2. Найденные конфликтующие инструкции

| № | Стадия / prompt_id | Цитата (минимальная) | Конфликтующий контракт | Решение / владелец | Тест |
|---|---|---|---|---|---|
| P1 | `direct.base.l1_planner` (правило 4) | «Запрашивай поиск (web_search), когда достоверность ответа существенно зависит от внешних сведений… **если хватает разговора — оставь пустым**» | §4.2.2/4/6, §8.1: L1 предлагает, но не имеет последнего слова; `confidence`/`tool_policy=none` не отменяют compulsory read-only | L1 сохраняет право молчания/реакции и право *предлагать* поиск; добавить §8.1-абзац про планируемые claims и явно сказать, что обязательность исполняет runtime. Правка — только через registry (bump seal), владелец: эта задача (Builder) после W1 | фикстуры 1,4,5,6,12 + снапшот payload |
| P2 | `direct.base.tool_phase` | «Конкретные характеристики… проверяй через `execute_web_search`, **когда он доступен**» | §4.2.4/6: отсутствие инструмента не основание пропуска, но и не разрешение на необъявленный вызов | добавить только честную формулировку «если проверка не состоялась — не утверждай проверенное»; машинную policy в SP-промпт не вставлять (§7.2) | 1,7,9 |
| P3 | `direct.base.l2_writer` | «Это этап написания текста, **а не поиска, проверки фактов** или выбора действия» | §4.6: guard должен жить **после** Writer, не внутри | оставить; guard реализуется как отдельная стадия; добавить в Writer «не заявляй, что проверил, если evidence не передан» | 8,16,17 |
| P4 | `direct.base.synthesizer` | «Выбрось весь технический мусор: … **ссылки с токенами, служебные теги и ID**» + схема `facts[].source = exa/rag/lore/api` | §4.4/§3.5: `url/source_id/claim_id/source_read_level/full_source_pointer` обязаны доходить до Writer | сохранить вычистку токенов, но добавить структурные поля provenance (аддитивно к JSON). Владелец: Architect (форма) + Builder | снапшот payload: URL/claim_id доходят |
| P5 | `factcheck.base.single` | «Используй поисковую выдачу **только как вспомогательный инструмент** … **Твоя собственная логика и кругозор важнее**» | §4.4 + `ASAP-FC-EVIDENCE-STYLE-02`: per-claim mandatory retrieval, evidence≠memory | НЕ править в этой задаче (второй preflight внутри FC запрещён §5.3). Передать владельцу FC как отдельный пункт регресса | FC-фикстуры (частичное подтверждение) |
| P6 | `factcheck.base.single` (строка 19, для контраста) | «Мировые факты… **проверяй веб-поиском. Не верь своей памяти**» | согласуется с v3 | не менять; сохранить при правке P5 | FC-фикстуры |
| P7 | `summary.base.l2_writer` | «Внешнюю реальность не «допроверяй» сама: … «в чате обсуждали новость о…», а не «событие действительно произошло»» | согласуется с §5.4 | не менять; закрепить тестом «0 web в summary» | 19–23 |
| P8 | `memory.fact_extract` | классы `world_news/quote/hypothetical_character` + «Публичный факт не становится личным фактом участника» + `source_message_ids` | согласуется с §5.4 | не менять | 21,27 |
| P9 | `prompt_style_blocks.LEGACY_BOT_KNOWLEDGE_INSTRUCTION` (+ копии в `factcheck_prompts.py:64,93`, `search_prompts.py:54`, `summary_prompts.py:1039,1070`) | «Дай понять, что ты **уже проверял эту инфу ранее** … и тебе **не нужно повторять дважды**» | §4.4/§6: запрещено заявлять несостоявшуюся проверку и блокировать перепроверку новых данных | **в активных канонах этой фразы нет** (проверено: `factory_text('factcheck.base.single')` строка 50 = только hostility-вариант; активный `BOT_KNOWLEDGE_INSTRUCTION`/`_NEUTRAL` без неё). Требование: никогда не реактивировать LEGACY/PREV-слепки; тест «активные payload не содержат подстроку» | grep-тест по effective payload |
| P10 | `verbilizer.mode.*`, `style.policy.hint`, `internal.dossier.*`, `internal.dream.*`, `internal.initiative_observer` | директив о поиске/проверке нет | — | конфликта нет (доказано чтением активных текстов) | — |

### 6.3. Обязательные проверки перед изменением промпта (§7.8)

1. Снять `effective_prompt()` для P1–P4 в текущем окружении: активный `prompt_id`, revision label, origin (factory/manual), итоговый payload (секреты редактировать).
2. Зафиксировать, что машинные стадии (L1, synthesizer, history_segment, temporal, memory) не получают публичных стилевых/характерных блоков, а публичные (Writer, FC verbalizer, summary narrator) — получают действующий Core/Expression/Style.
3. После правки: bump `FACTORY_REVISION_SEALS` + новая ревизия через существующий путь (`EVOL-016`–`018`); ручные редакции владельца остаются в истории; рестарт без релиза их не сбрасывает.
4. Регресс: social/шутка не получает отчёт со ссылками; summary не получает web-директиву; FC-структура вердикта не меняется.

## 7. Что не должно быть сделано в этой задаче

- Не переписывать FactCheck/Vision/EVOL-SRC «заодно» (§5.3, §5.5, §11.4).
- Не добавлять второй toggle поиска, второй классификатор, второй Writer, новый crawler, новый экран (`EVOL-034/040`, `ASAP-UI-02`).
- Не вводить «всегда гуглить» и не поднимать confidence искусственно.
- Не деплоить и не постить тестовые сообщения в боевые чаты (§11.5).
