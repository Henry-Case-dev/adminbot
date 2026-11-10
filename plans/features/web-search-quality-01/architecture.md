# WEB-SEARCH-QUALITY-01 — целевая архитектура

**Вердикт:** `ARCHITECT_ADJUSTMENT_REQUIRED`, риск **R3**. ТЗ v1.1 совместимо с системой, но нужны четыре узкие поправки: весь runtime-аудит `WQ-S0` остаётся `BLOCKED_BY:fc-trust-01 production`; параллель `WQ-S1 || WQ-S2` разрешена только после заморозки `SearchHit/SearchBatch`; в write scope интеграции входят фактические потребители FactCheck; Parallel использует актуальный keyless endpoint `https://mcp.parallel.ai/mcp` (старый `search.parallel.ai` — только совместимый override).
**Опора:** production `77a63bc5` (2.58.184), а не рабочий checkout: `search_aggregator.py:693-998`, `tool_router.py:1596-1637,2745-3008`, `direct_execution.py:402-454,1645-2017,2250-2530,2746-2897`, `search_service.py:51-175`, `source_reuse.py:47-56,275-323,410-448`, `auto_budget.py:360-540`, `bot.py:515-622`.
**Внешние контракты, проверенные 11.11.2026:** DDGS 9.16.1 ([PyPI](https://pypi.org/project/ddgs/)); Diffbot Web Search OpenAPI v1.0.0 ([docs](https://www.diffbot.com/docs/web-search/get)); LangSearch Free Plan ([pricing](https://langsearch.com/pricing)); Firecrawl Keyless + Free pricing ([launch](https://www.firecrawl.dev/blog/firecrawl-keyless-launch), [pricing](https://www.firecrawl.dev/pricing)); Parallel MCP ([official page](https://parallel.ai/mcp)); официальный MCP Python SDK ([source/docs](https://github.com/modelcontextprotocol/python-sdk), Streamable HTTP client, Python 3.11+). Числа квот не становятся кодовыми истинами: Firecrawl keyless сообщает daily/IP, аккаунтный Free — 1000 credits/month; UI показывает только фактический режим и ответ провайдера.

## 1. Граница и единый поток

- Один `SearchAggregator`, один `ToolRouter`, один `WebContentExtractor/SafeFetcher`, один L1 → tool phase → L2. Новых агентов, второго Router/aggregator, фоновых worker, GraphRAG/embedding rebuild нет.
- Канонический вызов: `SearchRequest → SearchAggregator.search_batch() → SearchBatch → ToolRouter.run_web_research() → fetch_article для выбранных URL → EvidencePack → существующий Writer`. `SearchAggregator.search()` остаётся временным text-wrapper через `_format_hits()` для обратной совместимости, но production-потребители переводятся на typed API.
- `ToolRouter.run_web_research()` — внутренний метод того же Router, не новый pipeline: выбирает discovery/read, вызывает существующие `_execute_web_search` и `_fetch_article`, возвращает `WebResearchResult`. `dispatch()` продолжает работать.
- Direct и Initiative остаются в `direct_execution.run_tool_phase`; убирается только удаление `execute_web_search` из continuation allowlist (`direct_execution.py:2413-2454`). SmartSearch получает тот же Router в `SearchService`; FactCheck после gate потребляет тот же `WebResearchResult`, но его `EvidenceMap/verdict/renderer` остаются каноном FC-TRUST-01.
- `bot.py`: сохранить один `_search_aggregator`; создать extractor и Router, затем внедрить тот же Router в `SearchService` и `FactCheckService`. Меняется порядок DI до polling, не число экземпляров.
- Адресный URL: сначала существующий `fetch_article`/SafeFetch; общий поиск включается только при неуспехе чтения, запросе независимого подтверждения, новой версии/контрдоказательстве. Cloud-reader никогда не обходит blocked destination/redirect/SSRF.
- `auto_budget` ограничивает доставку в L2 после добычи, а не истинность/число найденных документов; `source_reuse` даёт 0 network calls только для свежего прочитанного источника и не превращает его в verdict.

## 2. Замороженные типы и инварианты

- `SearchRequest`: `query, route, intent_class, language, region, freshness, site, claim_ids, direct_urls, user_forbidden, deadline, evidence_capacity`.
- `SearchHit`: поля ТЗ + `hit_id`, `seen_via[]`, `index_identity`, `independence_known`, `document_cluster_id`, `syndication_state`, `epistemic_state`.
- `ProviderOutcome`: `provider, index_identity, status, latency_ms, result_count, retry_after, quota/usage (если сообщены), error_code`; ключи/сырой запрос не сериализуются.
- `SearchBatch`: исходные outcomes, все hits, merged/ranked hits, query variants, rounds, `stop_reason`, coverage/novelty, real usage. Неполный успех не выбрасывает удачные результаты.
- `WebResearchResult`: batch + прочитанные `EvidenceSource` + failures/limitations; единственный вход `build_evidence_pack` для Direct/Initiative/SmartSearch и совместимый вход FC EvidenceMap.
- Rerank возвращает только `{hit_id, score}`; оригинальные URL/title/snippet/date неизменны. `SearchService._rerank_results` с переписыванием текста и критерием длины удаляется.
- Dedupe: до чтения hard-merge только точный canonical URL (scheme/host/default port/fragment/tracking); разные документы не сливать по title/snippet. После чтения похожие зеркала — soft syndication cluster с сохранением членов/provenance. Один cluster даёт не более одного голоса подтверждения.
- `provider != independent source`: число посредников повышает recall, но не confidence. Независимость утверждается только для известного upstream index и разных document/publication clusters; `unknown` не считается независимым подтверждением.

## 3. Провайдеры и продолжение

- Внутренние adapters — `services/search_providers/**`; Tavily/Exa сохраняются. DDGS: `from ddgs import DDGS`, экземпляр на вызов в `asyncio.to_thread`, явный backend/region/news когда выбран; `auto` помечает upstream unknown.
- Keyless baseline полноценен без секретов: DDGS + You free MCP; Parallel MCP и Firecrawl keyless — P2 после benchmark. LangSearch/Diffbot дают преимущество только при настроенном free key. Никакой OAuth/card/billed endpoint и автоматического перехода на paid/advanced.
- MCP — plain официальный `mcp` SDK, Streamable HTTP, без CLI extra; адаптер владеет lazy session/reconnect и закрывается из `SearchAggregator.close()`. Один reconnect допустим только при invalid transport session; 429 следует `Retry-After`, не ретраится как transport.
- Ключ резолвится per call из persisted hot-config → env fallback; raw secret не кэшируется в status. Поэтому замена из UI действует без restart. `not_configured` относится только к keyed adapter; capability готова при любом healthy keyless adapter.
- Вместо first-hit cascade: начальная волна 1 provider для простого discovery или максимум 2 разных retrieval groups для required/fresh/fact-check; результаты объединяются RRF + измеренными quality/freshness/coverage signals. Не запускать все adapters всегда.
- После начальной волны — **не более двух refinement rounds**. Каждый обязан дать новый canonical query и ожидаемый gap: новый claim, freshness/site/locale или новый index group; до двух provider calls в волне, в рамках существующего `ChainBudget/deadline`.
- Stop=`sufficient` только когда обязательные claims покрыты релевантным evidence и существенный источник прочитан; иначе stop по `no_new_hits/no_coverage_gain`, `all_candidates_read`, `deadline/capacity`, `quota/retry_after`, `all_unavailable`, `user_forbidden`. Resource/no-gain stop = честный `partial|technical_not_checked`, не «доказано».

## 4. Эпистемика и память

- Три независимых слоя: `snippet_found` (discovered/snippet), `page_read` (fetched/parsed/selected), `claim_established` (роль EvidenceMap + итоговый truth verdict). Статус провайдера/поиска не поднимает слой.
- Минимально расширить существующие `direct_execution.SourceRecord`, `EvidenceSource`, `ToolEvidence.trace_fields` полями `canonical_url, provider/index_identity, read_level, evidence_role, cluster_id`; `build_evidence_pack` печатает «сниппет найден»/«страница прочитана»/роль, но слово «доказано» берёт только из canonical verdict.
- `source_reuse.SourceRecord` уже хранит read level/date/pointer/TTL/contested; сохранить. `verified_reuse` оставить compatibility alias, но новый смысл/имя — `reusable_read`: доставка прочитанной выдержки, не доказательство claim.
- Удалить raw hooks `SearchService.research:108-110` и `FactCheckService:2168-2170`: выдача не идёт в `memorize_facts(..., "search_fact")`. Сейчас этот путь может создать `status='confirmed'` (`summary_memory.py:4713-4715`) — это корень contamination.
- Новые snippet/page blobs в GraphRAG не писать. Legacy `origin='search_fact'` не удалять и не пересобирать: read-side помечает «прошлый поиск, не перепроверено» и исключает его из proof/персональных фактов. Запись принятого внешнего claim откладывается до финального FC admission-контракта; без него источник живёт только в `source_reuse`/trace.

## 5. «Модули → Поиск» и Visual Preservation Map

Фактический render 2.58.184 проверен Browser Use и Playwright на exact `77a63bc5`: desktop/mobile без page overflow, но Overview почти пуст; текущие вкладки показывают duplicate prompt editor, модель Direct, generic 8000/300/6 и тесты только LLM. Live production без TMA недоступен; exact-code стенд использовал masked synthetic config, без записи настроек.

| BLOCK / route | CURRENT PURPOSE | USER VALUE | ACTION | MUST PRESERVE | ALLOWED CHANGE | DATA / STATE | INTERACTION | RESPONSIVE | WHY |
|---|---|---|---|---|---|---|---|---|---|
| общий shell/sidebar/topbar/glass/polygon | навигация/scope | узнаваемость | KEEP | drawer, роль, scope, refraction/background | a11y/spacing only | общий shell | прежние Back/focus | текущие breakpoints | ASAP-UI-02/MOD M3 |
| workspace header + tabs | module identity/effective master link | ориентация | REFINE | single master owner в каталоге, badges, tab pattern | 5 предметных tabs, без дублей | effective state/provenance | deep-links/back | desktop row, mobile wrap | текущая структура рабочая |
| Overview | generic state/history | почти нет | REDESIGN | real state + catalog link | компактные runtime/provider/last-run blocks | search trace/health | drill-down/test | 2 колонки→1 | доказана огромная пустота |
| Основные настройки | master status + rerank | частичная | MOVE | read-only master, saved OFF/ON | rerank IDs в «Стратегию» | config/effective | save с 409 | stack | смысловая группировка |
| Промпты | второй редактор | доступ к prompt | MOVE | тот же key/text/history/scope | только кнопка в Library + redirect | Prompt Registry | focused route/back | без нового editor | один canonical editor |
| Модели | копия Direct model | понять Writer | MOVE | ссылка на реальную модель | read-only explanation/redirect | actual Direct slot | click-through | compact row | это не search model |
| Лимиты | 8000/300/6 как общие | управление SmartSearch | REDESIGN | values/provenance/overrides | Auto/manual/none + scopes/capacity | resolver + actual result | save/reset Auto | cards stack | подписи сейчас ложны |
| Тестирование | LLM connection probes | диагностика | REDESIGN | explicit user-run, no writes | query→providers→dedupe→read→evidence→L2 trace | same adapters/events | cancel/drill-down | timeline, no table mobile | сейчас поиск не тестируется |
| AI/LLM `search_keys` | Tavily/Exa secrets | подключение | MOVE | `keys.*`, mask/history/RBAC | Connections в Search, без копии | secret API/probe | test/replace/delete confirm | compact provider list | ownership владельцем задан |

Итоговые tabs: **Обзор → Поисковики / подключения → Стратегия и качество → Контекст и ограничения → Тестирование / диагностика**. Advanced provider details и техническая ёмкость свернуты; ordered trace не превращать в generic KPI-card. Overview: desktop 2 columns, mobile 1; p50/p95 явно «24 ч» (переключатель 24 ч/7 д), quota unknown ≠ unlimited; loading/empty/error/partial/disabled раздельны.
Промпт: `#/ai/prompts/search/verbalizer/prompts.search_system_prompt` через действующий route builder; legacy `/modules/search/prompts` — адресный redirect. Legacy `/modules/search/models` → реальный owner Direct model (`#/modules/direct/models`), `/limits` → «Контекст и ограничения». Search keys остаются под прежними `keys.*`; физической миграции секретов нет.
Режимы: новые `limits.search_response_mode=auto|manual`, `limits.search_context_mode=auto|manual`, `limits.search_cooldown_mode=auto|none|manual`; factory `auto/auto/none`. На существующей БД отсутствие mode + наличие legacy numeric сохраняется как `legacy_manual`; one-time additive config migration пишет mode/history, но не меняет 8000/300/6. Fresh install получает factory modes.

## 6. Gate FC-TRUST-01, доставка и доказательства

- После FC deploy перечитать его accepted contract/code: `factcheck_planner.py`, `factcheck_service.py`, `evidence_policy.py`, `relation_evidence.py`, renderer и `plans/features/fc-trust-01/{contract,acceptance,reports,requirements-map.json}`. Заморозить ClaimUnit↔SearchRequest, Candidate/Evidence/Verdict basis, coverage vs execution_status и truth statuses; не создавать FactCheck 2.
- `UR-SRC-DATE` уже VERIFIED/deployed 2.58.184: переиспользовать per-hit `published_at`, но сверить финальный FC `EvidenceRef`. Для inspector перечитать итог UR-F/UR-20.4…20.8 и `turn_trace/pipeline_analytics/routes/app.js`; текущую работу inspector сейчас не трогать.
- Исполнение: `WQ-S0 BLOCKED_BY:fc-trust-01`; затем freeze `search_hits.py` → `WQ-S1 || WQ-S2 PARALLEL_SAFE`; `WQ-S3 SERIALIZE` (добавить FactCheck call sites); `WQ-S4 || WQ-S6 PARALLEL_SAFE`; `WQ-S5 BLOCKED_BY:S4` и может идти с S6; `WQ-S7 SERIALIZE`; `WQ-S8 → S9 SERIALIZE`; `WQ-S10 || WQ-S11 PARALLEL_SAFE`; S12.
- Acceptance по срезам: adapters contract/error tests; dedupe mutation (same URL/index/syndication); Direct+Initiative+SmartSearch+FactCheck parity на одном typed result; fetch/SafeFetch negatives; raw `search_fact` write count=0; hot key update без restart; old/new benchmark; live free/keyless + сохранённые Tavily/Exa; Playwright + Browser Use + Visual Neighborhood Sweep (Modules catalog, Prompt Library, Direct model, FactCheck/Web links; desktop/mobile/GLOBAL/CHAT/RBAC/409).
- Observability в существующих mca-events/Inspector: `SEARCH_PLAN`, `SEARCH_PROVIDER_ATTEMPT`, `SEARCH_MERGE`, `SEARCH_READ`, `SEARCH_STOP` + join к `reply_search_evidence`; только enum/id/count/latency/usage, без secret/raw private query/page text. No second DB/DDL.
- Failure: partial batch survives; exact 401/403/429/timeout/empty/bad-payload statuses; all failed → unavailable; read failed → snippet_only, никогда proof; paid fallback запрещён. Rollback — предыдущий release SHA; additive mode/provider rows инертны, старые numeric/key/prompt values целы, schema/embeddings не меняются.
- Риски: latency R2 (waves≤2 providers, p95/deadline); free quotas R2 (reported state/Retry-After, no overage); dedupe false-positive R2 (hard exact URL, soft content cluster); memory contamination R3 (no raw writes + legacy downgrade); secrets/SSRF R3; UI regression R2 (preservation map + two-browser sweep).
- Non-goals: платные tiers/card/top-up, новые ключи сейчас, второй FactCheck/aggregator/router/Writer, новые агенты/workers/microservice, arbitrary user quota, embedding rebuild, prompt text/history reset, дублирование MOD-ACL/ASAP shell.

DESIGN READY
FC-TRUST gate: re-verify deployed SHA + accepted ClaimUnit/EvidenceMap/verdict/coverage/execution-status, FactCheck retrieval budgets, UR-SRC-DATE mapping, UR-20.x inspector trace, MOD-ACL/ASAP-UI accepted shell and current official MCP/free-quota contracts.
