# SMART-EXECUTION-RELIABILITY-01 — архитектурный контракт, часть 1

Основание: owner input `2026-11-14-smart-execution-reliability-01.md`, этапы A/B/C/G/K; runtime base `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199). Код не изменялся.

## 1. Карта ограничителей

| Runtime (base file:line) | Источник | OFF | Кат. | Решение / точное изменение |
|---|---|---:|---:|---|
| `services/tool_loop.py:44` `TOOL_MAX_ROUNDS=4` | константа | да | 1 | удалить enforcement/fixed `range`; завершение по progress/exhaustion/real limit/cancel/safety |
| `tool_loop.py:45` `_TOOL_CALLS_PER_ROUND_MAX=2` | константа | да | 1 | не slice tool_calls; dispatch все валидные calls, bounded concurrency только исполнительным queue |
| `tool_loop.py:50` `TOOL_MAX_TOTAL_CALLS=6` | константа + `MCA_*` env/settings | да | 1 | убрать cap; оставить счётчик telemetry и structured limit только при явном ON |
| `tool_loop.py:51` `TOOL_CHAIN_TIMEOUT_SECONDS=360` | константа + `MCA_*` | да | 2/1 | убрать общий product deadline; сохранить transport/provider timeout, cancel и доказательно обоснованный fuse, с partial evidence |
| `tool_loop.py:52` `_TOOL_MAX_SAME_CALL=2` | константа + setting | да | 3/1 | оставить dedup identity; retry только при изменившихся условиях/retryable, не arbitrary stop-2 |
| `tool_loop.py:53` `TOOL_CHAIN_MAX_METERED_CALLS=4` | константа + `MCA_*` | да | 1/2 | metering отделить от blocking; cost policy блокирует только явный budget ON/реальный paid operation |
| `tool_loop.py:81-82` `PLAN_MAX_STEPS=6`, replans=2 | константа | да | 1 | не обрезать нормализованный план; общий loop исполняет все разрешённые steps, без второго loop |
| `tool_loop.py:762-766` | константа 2 | да | 1 | удалить `tool_calls[:2]`; каждому call — result/denied/cancelled envelope с исходным `tool_call_id` |
| `tool_loop.py:692`, `806` | fixed loop `range(4)` | да | 1 | единый progress-driven loop для Direct/L1/checkup/inspect/retrieval/fetch/factcheck |
| `services/direct_execution.py:104-106` steps=4, tokens=6000, metered=4 | constants/env explicit ceilings | да | 1 | не применять при OFF; при ON только явная пользовательская policy; token ceiling не скрывать под evidence |
| `direct_execution.py:482`, `544` `max_fetch_steps=3`, `urls[:...]` | default/plan | да | 1 | не truncать нужные URLs; preserve semantic selection and continuation/provenance |
| `services/source_reader.py:160-162` files=6, depth=2, requests=16 | constants + `SOURCE_READ_*` | да | 1 | убрать unconditional ceilings; request lifetime per invocation, reset counters; retain provider rate/cancel |
| `source_reader.py:163-165` defaults files=3/depth=1/requests=8 | constants/env | да | 1 | не defaults-enforce; explicit ON policy only; no replacement cap |
| `source_reader.py:166`, `1023`, `1237` file bytes=2MB | env/default, SafeFetch/local read | нет | 2/3 | retain real memory/payload/binary safety; range/page reads for text, explicit continuation |
| `source_reader.py:170`, `172`, `174` ref=4/candidates=3/paths=3 | constants | да | 1 | remove arbitrary result/path truncation; preserve ranked relevance and expose continuation |
| `source_reader.py:176`, `1185` local tree=20,000 | constant | условно | 2/3 | retain only as filesystem traversal safety, mark `truncated` and continuation; not evidence quota |
| `source_reader.py:813`, `1110` search per-page 10/3 | provider/local adapter | нет/условно | 2 | provider API page limit stays; paginate until exhausted/relevant stop, never present first page as complete |
| `source_reader.py:1664`, `2187+` `_exhausted`, files/depth | request counter + caps | да | 1 | no previous-request leakage; stop only technical/provider denial or source exhaustion, with `not_checked` |
| `source_reader.py:1554-1588`, `2217`, `2302` evidence `budget_chars` | caller section budget | да | 1 | OFF does not impose section cap; real-window packing may page/split, retaining exact range and remainder |
| `services/direct_context_composer.py:159-181` middle=60, episode=40/count=2 | env defaults | да | 1 | remove artificial retrieval caps on Smart path; preserve relevance/order and actual model window |
| `direct_context_composer.py:389`, `509` max_messages=40 | function default | да | 1 | no fixed user-visible history cap when OFF; physical context window still governs packing |
| `direct_context_composer.py:226-308`, `1535+` token truncation/guard=12 | budget allocator | да | 1/2 | OFF: no artificial section budget; ON/physical window: only real capacity, lossless split where possible, provenance |
| `direct_context_composer.py:1917-1930` max_fragments=10 | function default | да | 1 | no hidden evidence fragment cap; semantic selection may stop only when no relevant candidates |
| `direct_context_composer.py:1998-2014` self output limit=50 | caller/DB query | да | 1 | remove Smart-path arbitrary top-K; pagination/continuation; retain storage/query safety |
| `services/evidence_bundle.py:316-378` traceback chars=2000/frames=120 | caller defaults | да/нет | 1/3 | OFF no evidence cap; retain structured paging cursor and redaction/safety, expose omitted frames |
| `evidence_bundle.py:578-684` page `max_chars` default 4k/6k, reserve 300..1500 | caller + serialization | да | 1/2 | do not silently drop facts; real LLM window packing only, page metadata/omitted IDs/next offset |
| `evidence_bundle.py:692-718` facts max_chars=3000 + `text[:max_chars]` | caller | да | 1 | remove user-visible hard slice; structured facts + continuation; no stub replacement |
| `services/response_extent.py:79-86` output=4096/ceiling=16384, plan steps=6/fetch=3 | env/constants | да | 1; output 2 | budgets OFF: no artificial max output/plan cap; provider `max_output` and real window remain; one loop |
| `services/llm_client.py:59`, `94`, `153` log/error snippets | constants | нет | 3 | retain secret-safe log redaction; not model/user evidence |
| `llm_client.py:521+`, `1098+` per POST timeout/retries | settings/provider transport | нет | 2/3 | retain actual request timeout/retry/cancel; not chain research deadline |
| `model_capacity` / `writer_max_output_tokens` | provider catalog/registry + real capacity | нет | 2 | retain actual context/max_output; unknown stays unknown, never invent 1M or local cap |
| `worker_budget.py:59-67`, `228+`, `363+` daily calls/tokens/image | hot registry, chat→global→env; `0` deny, `<0` unlimited | N/A for explicit business | 4 | do not alter monetization/background business quotas; Smart read-only evidence never routed through them |
| `budget_gate.py:27-46` `flags.budgets_enabled` | chat→global→factory setting | source OFF | 1 | fix OFF read contract/last-known-valid; no fallback True on read error |

Category 2 physical/external and 3 safety/integrity remain independent of budget OFF: provider context/output, HTTP payload, file/memory/binary safety, auth/RBAC/SSRF/path safety, concurrency, dedup, idempotency, cancellation and secret redaction. Category 4 paid image/user quota is out of scope.

## 2. Budgets OFF

Canonical predicate: `await budget_gate.budgets_enabled(chat_id)`; `False` means enforcement OFF. Resolution remains chat override → global → `settings.BUDGETS_ENABLED` factory. The resolver/cache must return the last-known-valid value on read error: a known OFF must never become ON; unknown/stale must be explicit/observable, not silently treated as ON. Every inner gate (`TOOL_CHAIN_LIMITS_ENABLED`, `MCA_*`, `DIRECT_ORCHESTRATOR_*`, legacy env, SourceReader caps, context/evidence/serialization caps) must consult the effective predicate before enforcement; OFF cannot be re-enabled by an env/default/inner fallback. Preserve stored chat overrides.

OFF removes only artificial volume/cost enforcement. Continue usage, token/cost, latency, retry, provider status, dedup and operational statistics. `worker_budget` remains for its explicit background/image business policy, not ordinary read-only Smart research.

## 3. One tool-loop policy

One existing `chat_with_tools`/`DirectExecution` path serves Direct, L1 plans, sequential rounds, checkup, inspect_runtime, SourceReader, web/fetch, factcheck, retrieval and memory. No second loop, checkup loop, progress-evaluator LLM or lexical heuristic. The model’s valid calls are all dispatched; queue controls real parallelism, not cardinality. Every requested call yields `ok/empty/error/timeout/cancelled/denied/delivery_unknown` (or structured legacy equivalent), preserves `tool_call_id`, ordering and valid provider `assistant(tool_calls) → tool(each id) → assistant` sequence. Metered/usage fields are observational; enforcement is separate.

Completion: sufficient model answer; no new relevant data; sources exhausted/unavailable; confirmed physical/provider limit; user cancel; or safety/integrity stop. Dedup suppresses only identical non-retryable conditions; retryable failures or changed cursor/source/state may retry. No universal 360s deadline. Any emergency fuse must have technical justification, retain evidence and produce a truthful stop reason.

## 4. Evidence delivery (C)

SourceReader counters are per request/execution, reset on new independent request; no prior request consumes the next request. File byte/binary and transport limits remain safety/physical; text uses line ranges/pages and continuation. Path: **tool execution → structured result → ToolResult/evidence envelope → tool-loop history → context composer → real-window packer/serializer → LLM payload → final answer**. At each edge preserve data, provenance, source/range, truncation/omission reason and continuation; success at edge N is not proof of delivery at N+1. OFF removes section token/char/evidence caps; only real provider window causes lossless splitting/priority packing and explicit incomplete coverage.

## 5. Finalization (G)

Existing execution has logical phases research/evidence collection and final answer, using existing LLM/Writer; skip final call if model already produced a valid final answer. If research stops first, finalize independently of exhausted research counters. Preserve request, original context, facts, successful/partial results, provenance, confirmed source errors, unchecked areas and stop reason. Final output is meaningful and evidence-grounded; degraded output separates confirmed facts/hypotheses, names failed sources, and never uses the sarcastic stub when publishable evidence exists. `retryable=false` is terminal for that route; do not repeat unchanged provider failure, use safe alternative if present, otherwise continue with available evidence. No new lexical error heuristics.

## 6. Scopes and acceptance

| Stage | Disjoint write scope | Required proof |
|---|---|---|
| A | `budget_gate.py`, settings resolution, inner gate predicates | OFF effective chat/global/factory; legacy/env cannot re-enable; ON and explicit overrides preserved; stats continue |
| B | `tool_loop.py`, `direct_execution.py`, shared result sequencing only | L1 scenario: >4 LLM rounds, >6 calls, >2 calls/round; no lost IDs; dedup/retry/concurrency and stop reasons |
| C | `source_reader.py`, evidence serialization/composer boundaries | L2 evidence past old caps, final-range fragment reaches payload, multiple linked results, physical overflow has honest continuation |
| G | finalization branch/result contract in existing loop/Writer | normal, post-stop-with-evidence, partial-source-error and terminal `retryable=false`; no stub, no false completeness |

Serialize writes to `tool_loop.py`, `direct_execution.py`, `tool_result`/provider message serializer, `budget_gate.py`/settings resolver and shared composer/evidence APIs. Do not parallelize overlapping runtime contracts; tests/evidence may run read-only after each slice. K invariants apply to every slice: policy/RBAC/publication guard/SafeFetcher/path safety/chat isolation/secrets/idempotency remain enabled; no new entity, loop, resolver, database or approval stage.

SMART_PART1_READY

Builder assignments: **A** repair effective OFF predicate and last-known-valid precedence across all inner gates; **B** remove fixed round/call/timeout/metered/plan enforcement while preserving one loop, concurrency, IDs, dedup/retry and telemetry; **C** remove SourceReader/evidence artificial caps, reset counters per request, and prove the seven-edge delivery path with real-window continuation; **G** add existing-loop research→final phase and meaningful degraded finalization with terminal retry semantics. 
