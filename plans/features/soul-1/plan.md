# SOUL-1 — Plan (requirement coverage, dependency graph, waves)

| Field | Value |
|---|---|
| Feature | `soul-1` (epic SOUL-01 … SOUL-19 + §0/§1/§21) |
| Authoritative source | `plans/features/soul-1/source-current-task.md`, SHA256 `8C42DDFABCE635FE4E1F24F9522FF8642F3BD3049FAC05C77CA162687051196B` (306 lines, read in full) |
| Amendment source | `plans/features/soul-1/source-architectural-clarification.md`, SHA256 `338FD9C6BD323A7EA8AD80577C2E9D8B45A714D30BDD4FC9147AF75931A4A35C` (= строки 761–899 `plans/current_task.md`, 139 строк); **приоритет над противоречащими старыми формулировками, включая SOUL-03/SOUL-04 о сохранении legacy-речевых кастомов** |
| Map | `plans/features/soul-1/requirements-map.json` — 101 inventory items (96 required / 5 `context` / 4 `user_excluded` по уточнению) + 97 manual = **193 req_ids**, 9 slices (W1–W9) |
| Amendment map | `plans/features/soul-1/requirements-map-amendment.json` — 66 inventory items (51 required / 15 `context` подзаголовков) + 28 manual = **79 req_ids** (W1 9, W2 24, W3 7, W4 1, W6 8, W8 3, W9 1, W10 26); **ко-гейтится с основной картой на review/release** |
| Plan gate | `requirements_gate.py check --map … --stage plan` → `errors=0` для обеих карт (must be re-run per slice at review with `--slice`, and at release with candidate/deployed SHA) |
| Owner of this lane | PM-1, writer, write scope limited to `plans/features/soul-1/{requirements-map.json,requirements-map-amendment.json,plan.md}` |
| Rule | No slice may drop its req_ids to backlog; parent epic closes only when every req_id in **both** maps is `VERIFIED` (see «Never auto-closable»); уточнение владельца отменяет противоречащие старые формулировки |

## 1. Slices (stable ids) and owners

| Slice | Requirement scope | Owner role | Entry criteria | Exit criteria | Risk |
|---|---|---|---|---|---|
| **W1** | SOUL-EXEC.1–8, EXEC.13, SOUL-01.0–01.5 (audit + matrix + conflicts + runtime-assembly test), SOUL-15.0–15.4 (single source schema, two-phase migration + dry-run, rights model); **уточнение**: SOUL-AMD.0.1 (приоритет уточнения), 1.4 (данные не обнулены), 2.1 (классификация стадий по назначению), 3.1 (инвентаризация §3), 3.3 (что законно остаётся в коде), 4.6 (старый canon только в backup), 7.1–7.2 (backup + идемпотентная обратимая миграция), 8.5 (аудит runtime-сборки) | Architect (design) → Builder (read-only audit, migration tooling) | snapshot SHA verified, map plan-gate green | Prompt/Writer Matrix + conflict list + runtime-assembly test evidence; source schema of all legacy keys/overrides; dry-run report with predicted diff; migration plan with backup/abort | R1 (read-only); migration **write pass** is R3 and is gated by JB-3 |
| **W2** | SOUL-BOUND.0–7, SOUL-02.0–02.8 (owner Personality Core + compact runtime edition + inheritance), SOUL-03.0–03.6 (module/SelfModel preservation, levels 1–7, GLOBAL/CHAT scope, no double render), SOUL-04.0–04.6 (one Composer, layer split, normalization, idempotent migration, no second LLM writer), SOUL-15.5 (hot apply), SOUL-15.7 (no silent degradation); **уточнение**: SOUL-AMD.0.2, 1.1–1.3, 1.5 (Factory Default = полный авторский SOUL-02, удаление старых канонов, сохранение характера, dynamic traits не переписывают Core), 2.2–2.3, 2.8, 2.10–2.13 (один Core через Composer; граница публичной речи и внутренних стадий; запрет скрытых личностей), 3.2, 3.4, 3.6 (Prompt Registry, управляемые шаблоны/отговорки, диагностируемая причина), 4.1–4.5 (версионные Factory Defaults, diff/reset/inheritance, hot apply), 7.3 (hidden fallbacks), 8.1–8.2, 8.4 (один effective Core во всех путях, сравнение полной/компактной редакций, factory-операции, отсутствие старых PG-речевых overrides в effective prompt) | Architect (precedence contract) → Builder (implementation) | W1 audit baseline merged (JB-1) | Core stored versioned + compact runtime edition measured; hierarchy contract tests; single Composer with `effective layers` API; legacy ↔ Core mapping without double render; hot apply on next reply without restart; degradation reasons logged; старые каноны вне runtime и вне legacy-редактора | **R3** (PG migration + affects every Writer) |
| **W3** | SOUL-16.0, 16.P1, 16.1.1–.5, 16.2.1–.4, 16.3.1–.4, 16.4.1–.5 (Speech Style Policy: data model, quotes, trailing period, execution order/precedence, protected spans, bounded repair), SOUL-16.5.3 (hard-rule acceptance on Direct/Initiative/tool-backed), SOUL-05.0–05.7 (one_word vs micro end-to-end, validator, payload chain, behaviour matrix), SOUL-09.0–09.3 (anti-stickiness); **уточнение (расширение покрытия Core)**: SOUL-AMD.1.6–1.7 (`one_word` vs `micro` — два режима; дешёвая проверка без полной регенерации; ссылки/код/цитаты не ломаются), 2.4–2.5, 2.7, 2.9 (публичные Factcheck и Summary, ответы на инструменты и сообщения о неудаче — через Core + зарегистрированный жанровый слой; без сухой ассистентской речи, истинность неприкосновенна), 3.5 (Speech Style Policy — самостоятельный управляемый слой, включая fallback) | Architect (policy/priority contract) → Builder | W2 Composer seam frozen (JB-2) | `effective_style_policy` before Writer; single normalization pass owner; hard/soft rules typed with pass/repaired/exempted/conflict; one_word gives exactly one lexical word up to Telegram payload; micro 2–8 words; 10+ heterogeneous inputs evidence; публичные Factcheck/Summary и tool-ответы подтверждены на реальных прогонах | **R3** (mutates final user text on the delivery path) |
| **W4** | SOUL-06.0–06.7 (Humor Craft techniques + toggle + 0 extra LLM by default), SOUL-07.0–07.3 (few-shot library 15–30, owner CRUD, selection 1–3, A/B, leakage protection), SOUL-08.0–08.12 (feedback loop inside `mca_experience`, bounded metadata, signal classes, conservative updates, measured effect, mandatory real scenarios); **уточнение**: SOUL-AMD.2.6 (сны, глубокий сон, ностальгия, лор, истории, воспоминания — авторские тексты через Core и жанровые правила) | Architect (learning/anti-gaming design) → Builder | JB-2 (Composer slots for humor/examples/lessons) | Techniques selectable and testable; library CRUD + selection with reasons; feedback signals with provenance/confidence/timeout; no auto Core rewrite; bounded storage + rollback/decay; measured next-reply effect | R2 (additive, but writes Experience/PG and influences choice) |
| **W5** | SOUL-05.8 (initiative autonomy, same Core/Composer/Writer, SILENT, snapshot identity), SOUL-18.0–18.7 (funnel diagnostics, real counters, gates/cooldown audit, owner frequency prefs, health≠outcome, MiniApp funnel, live acceptance) | Builder → Reviewer | JB-2 (Writer/Core reuse) | Real 24–48h counters as evidence; documented causes of every silence; no spam; diagnostics button with trace to mock send; health vs outcome warning; live acceptance or `LIVE_UNVERIFIED` + 24–48h plan | **R3** (may send messages into a real group) |
| **W6** | SOUL-10.0–10.6, 10.P1–P5 (single «Речь и характер» entry, six sections, Prompt Inspector, exact visual/responsive rules, screenshot/interaction matrix, real WebView), SOUL-11.0–11.4 (prompt accessibility on mobile, one backend config object, real-API E2E), SOUL-16.5.0–.2 (style editor UI/UX), SOUL-17.0, 17.P1, 17.1–17.6 (targeted liquid glass), SOUL-EXEC.14 (polygon background untouched); **уточнение**: SOUL-AMD.0.3 (владельческий контроль речевых инструкций), 6.1–6.6 (разделы Характер / Стиль письма / Выражение / Юмор / Примеры / Попробовать / Обучение; Prompt Registry UI; мобильная доступность редакторов; Effective Prompt Inspector с фактически отправленным payload; «Возможности бота»; hot apply), 8.3 (правки через MiniApp меняют следующую генерацию, fallback не возвращает старого персонажа) | Architect (Visual Preservation Map) → Builder (UI) | JB-3 (backend registries + APIs frozen) + JB-A (ко-гейт карт) | Entry point + sections usable at 320–1440; Prompt Inspector admin-only и показывает preview отдельно от отправленного payload; both prompt entry points work on mobile with real API responses; style editor separate from Core with preview/history; capability list «Возможности бота» читаемый и без дублей тумблеров; before/after glass frames on identical polygon position; zero diff on background | R2 (UI only, but shared `web/static`, `web/api`) |
| **W7** | SOUL-12.0–12.5 (fullscreen: three separated operations, client matrix, real acceptance, no mock-DONE, safe-area/no jump), SOUL-13.0–13.6 (ASAP8 v6.3 baseline, glass-teststand exposure, 14 pending live gates, embedding quota, git-evidence gaps incl. `225c3c2b`, 6 failed pytest) | Builder → DevOps/Reviewer (external evidence) | JB-4 (`web/static` writer handover from W6) | tdesktop path either works with visual proof or has honest explanation + supported launch workflow; teststand unreachable anonymously (401/403/404); legacy gate registry visible; quota/commit evidence sourced, not invented | R2 (security exposure + platform behaviour) |
| **W8** | SOUL-14.0–14.4 (layer influence diagram, telemetry metrics, 30–50 reply A/B, feature flag + rollback), SOUL-15.6 (flags/canary), SOUL-15.8 (size/latency/cost), SOUL-15.9 (SOUL-15 acceptance scenarios), SOUL-19.0–19.6 (unit/integration/UI/feedback/deploy test plan, waves keep epic in force), SOUL-EXEC.9–12 (release evidence discipline, rollback gating) | Builder (telemetry/flags) → Reviewer (gate) | JB-5 (all feature slices in REVIEW/VERIFIED) | Metrics with honest stale/zero states; A/B report with method, cost, regressions, rollback; flags separate and non-duplicating; p50/p95 latency + prompt growth measured; release gate with exact deployed SHA; `LIVE_UNVERIFIED` used instead of false DONE | R2–R3 (flags and canary touch production behaviour) |
| **W9** | SOUL-21.0–21.11 (ten final-report obligations + main success criterion); **уточнение**: SOUL-AMD.8.14 (итоговый отчёт по уточнению: архитектура простыми словами, карта изменений/удалённых legacy путей, Factory Defaults, реальные effective prompts и tool traces без секретов, честный список оставшихся live-проверок) | Reviewer + PM (evidence assembly) | JB-6 (release gate green or deviations explicitly listed) | Report contains matrices, source maps, real examples with delivered payload, screenshots at 320/390/1440, A/B, observed→lesson→outcome, fullscreen + initiative diagnosis, legacy gate ledger, version/SHA/test/reviewer status, human-readable summary | R1 |
| **W10** | SOUL-AMD.0.4, 5.1–5.18 (§5: semantic intent → capability, runtime capability registry со статусами, truthful self-knowledge, удаление `IMAGE_GENERATION_FALLBACK_PHRASE`, единая цепочка исполнения, idempotency и delivery confirmation), SOUL-AMD.7.5 (ложные утверждения о способностях), SOUL-AMD.8.6–8.11 (живые сценарии image / search / factcheck / video; delivery-confirmation кейс — postdeploy) | Architect (capability contract + reuse map) → Builder | JB-A (ко-гейт карт) + JB-2 (registry API для управляемых fallback-шаблонов) | Capability resolver + статусы из реальных schemas/config/overrides/ключей/квот; однозначное поручение → ровно один вызов tool; разные правдивые объяснения отказа в голосе Core; нет дублей/двойных списаний; delivery confirmation; один реальный trace на каждый сценарий (не мок) | **R3** (платные вызовы, публичные сообщения, ошибки доставки) |

**Baseline deviations (justified):** §0 governance split between W1 (process/audit), W6 (background freeze), W8 (release evidence/deploy gating), W9 (report) instead of one owner — otherwise W1 blocks all later slices; SOUL-16.5.x sits in W6 (UI) while SOUL-16.0–16.4.x sits in W3 (engine) — one editor, one engine, no competing owners; SOUL-15.5/15.7 moved to W2 (Composer/config semantics) while 15.6/15.8/15.9 sit in W8 (measurement/flags/gate); SOUL-BOUND.* grouped in W2 because boundaries are enforced by Core+Composer; уточнение владельца разведено по существующим W1/W2/W3/W4/W6/W8/W9 с новым блоком W10 (Capability Awareness & Tool Grounding, §5); UI-часть «Возможности бота» (SOUL-AMD.6.5) остаётся в W6, W10 поставляет ей capability-данные и trace.

## 2. Dependency graph and waves (max 3 concurrent writer lanes)

```
W1 audit + source schema (R1)                         [wave 0, alone]
   | JB-1 audit baseline + schema frozen
   | JB-A (barrier): amendment map + main map co-gated at plan -> W3/W4/W6 dispatch allowed
   +--> W2 Core + Composer + migration domain (R3)     [wave 1, lane 1 writer]
   |      | JB-2 Composer seam frozen
   |      +--> W10 Capability Awareness & Tool Grounding (R3)                   [wave 2, lane 1]
   |      +--> W3 Speech Style Policy + one_word/micro + Core coverage (R3)     [wave 2, lane 2]
   |      +--> W4 Humor Craft + Few-shot + Feedback loop (R2)                   [wave 2, lane 3]
   |      | JB-3 W1 migration write pass after W2+W3 registries frozen          [wave 3, lane 1]
   |      +--> W6 MiniApp «Речь и характер» + prompts + capability UI + glass (R2) [wave 3, lane 2]
   |      +--> W5 Initiative diagnostics/vitality (R3)                          [wave 3, lane 3]
   |             | JB-4 web/static handover (W6 -> W7)
   |             +--> W7 Fullscreen + legacy v6.3 tails (R2)                    [wave 4, lane 1]
   +--> W8 Observability / A-B / flags / release gate (R2)                      [wave 5, after JB-5]
          | JB-6 release gate result
          +--> W9 §21 final report + coverage reconciliation (R1)                [wave 6]
```

Waves 2 and 3 are the only places with three lanes; every other wave is serialized. Read-only look-ahead is allowed in any wave (e.g. W6 may read W2/W3/W10 contracts while W2 writes). The W10 capability UI surface is delivered in W6 from W10's registry data (single writer per file stays as in §3).

## 3. Serialization of shared mutable resources (single writer per file per wave)

| Resource | Single writer | Rule for other slices |
|---|---|---|
| `services/direct_chat_service.py` | W2 | W3/W4/W5 integrate **only** through the Composer/policy API; no concurrent edits; hook points must be reviewed in one diff series |
| `services/chat_prompts.py`, `prompt_style_blocks.py` | W2 (registry + Composer) | W3 adds style-policy accessors after W2 seam merges; append-only, no parallel rewriting |
| `services/prompt_migrations.py`, PG prompt registry + migrations | W1 | W2/W3 hand definitions to W1 lane; W1 executes the single transactional write pass (JB-3) with backup + abort |
| `services/direct_l1.py`, `response_extent.py` | W3 | W1 reads only (audit); W5 consumes L1 contract, does not edit; W10 supplies capability truth as data/contract only — правки L1 идут через W3-lane после JB-2 |
| `services/direct_capabilities.py`, `tool_schemas.py`, `tool_router.py`, capability resolver (новый модуль) | W10 | Никто больше не редактирует; W6 читает capability-данные через API, W10 не трогает UI-файлы; единый `generate_image` и delivery-механизм не дублируются |
| `mca_experience*`, lessons/extractor modules | W4 | W2/W3 read lessons; no parallel writers; no second learning loop |
| `initiative_observer.py`, initiative services | W5 | W2 provides Core accessor only |
| `web/api/**` (routers) | W6 | W5 (initiative funnel endpoints) and W8 (telemetry/flags) add separate router modules after W6 merge |
| `web/static/**` (except frozen background assets) | W6 | W7 owns `fullscreen-policy.js` and `glass-teststand.html` only after JB-4; nothing else touches static JS/CSS |
| polygon background (DOM/canvas/CSS geometry) | **frozen** | No slice may modify; W6 verified by byte diff + before/after frames (SOUL-EXEC.14, SOUL-17.P1, SOUL-17.6) |
| `tests/**` | owning slice | New tests live in slice-owned files; W8 aggregates the test plan, does not rewrite others' tests |

## 4. Acceptance ledger (PENDING = all rows; evidence column = expected evidence at review)

Notation: `static` = code/config/report artifact, `unit`, `integration`, `ui` (Playwright/browser or real device capture), `live` (real Telegram client/chat/provider/human). `gate=l` marks `live_required` rows; `gate=L~` marks `live_when=postdeploy` (review allows `READY_FOR_LIVE`, release requires `live`/`production` evidence bound to the candidate).

| req_id | slice | status | expected evidence | live gate |
|---|---|---|---|---|
| SOUL-EXEC.1–8, EXEC.13 | W1 | PENDING | static (snapshot SHA, map, gate logs, audit artifacts, plan) | – |
| SOUL-EXEC.9–12 | W8 | PENDING | static + live (release discipline, per-ID SHA/test ledger, rollback plan, backup/abort evidence) | EXEC.12 = L~ |
| SOUL-EXEC.14 | W6 | PENDING | static (byte diff of background assets) + ui frames | – |
| SOUL-01.0–01.5 | W1 | PENDING | static matrix/report + unit/integration (runtime-assembly test) | – |
| SOUL-BOUND.0–7 | W2 | PENDING | static contract review + unit/integration (fabrication, permissions, machine-stage neutrality) + live for BOUND.3 (same speech recognizable across real Direct/Initiative/tool-backed runs: real chat logs / real run samples, not fixtures alone) | BOUND.3 = l |
| SOUL-02.0–02.8 | W2 | PENDING | unit (versioned core, compact edition 150–250 words, token measurement, inheritance, no silent global change) + ui (editor preview) | – |
| SOUL-03.0–03.6 | W2 | PENDING | integration (level hierarchy, conflict outcome, two chats) + static provenance; SOUL-03.5 `user_excluded` уточнением: legacy custom уходит в аварийную копию, не в runtime и не в legacy-редактор (совместимые части — через SOUL-02.8/03.1 и SOUL-AMD.1.2/1.4) | – |
| SOUL-04.0–04.6 | W2 | PENDING | unit/integration (typed plan, `effective layers`, no double render, no second LLM writer); SOUL-04.3/04.4/04.6 `user_excluded` уточнением (совместимые части — через SOUL-AMD.1.2/2.4/2.7/2.11/7.2 и SOUL-15.3) | – |
| SOUL-05.0–05.7 | W3 | PENDING | unit/integration (one_word exactly one word, micro separate, validator, protected content, behaviour matrix) + live for payload chain | 05.2,05.3,05.5,05.6,05.7 = l |
| SOUL-05.8 | W5 | PENDING | integration + live (initiative reuse of Core/Composer/Writer, SILENT, snapshot identity) | L~ |
| SOUL-06.0–06.7 | W4 | PENDING | unit (technique selection, toggle, 0 extra calls by default) + live scenario samples | – |
| SOUL-07.0–07.3 | W4 | PENDING | unit/integration (CRUD, selection 1–3, diversity/recency, leakage guards, A/B of versions) + ui (cards, badges) | – |
| SOUL-08.0–08.11 | W4 | PENDING | integration (metadata fields, signal classes, conservative update, decay, telemetry) + unit (unknown=failure guard) | 08.10 = l |
| SOUL-08.12 | W4 | PENDING | live (seven real scenarios with attribution and effect on next selection) | L~ |
| SOUL-09.0–09.3 | W3 | PENDING | unit/integration (sliding window, capped ban-list with TTL, local replacement, /style cannot disable core) | – |
| SOUL-10.0–10.6, 10.P1–P4 | W6 | PENDING | ui (entry point, six sections, Inspector, responsive/touch/a11y, draft/selection stability) | l |
| SOUL-10.P5 | W6 | PENDING | ui at 320/360/390/430/768/1024/1440 + landscape and live on real Telegram WebView | L~ |
| SOUL-11.0–11.3 | W6 | PENDING | ui/integration (both entry chains, one config object, visible reason instead of empty, 320–430 px) | l |
| SOUL-11.4 | W6 | PENDING | live (real-API E2E on real Telegram client, save + restore) | L~ |
| SOUL-12.0–12.5 | W7 | PENDING | live (platform/client matrix, SDK events, actual fullscreen, safe area, no layout jump) | L~ |
| SOUL-13.0, 13.1, 13.5, 13.6 | W7 | PENDING | static (baseline record, legacy registry, artifact locations, pytest log analysis) | – |
| SOUL-13.2 | W7 | PENDING | integration + live (anonymous probe 401/403/404 against the deployed production host; stand reachable only in the permitted test environment) | L~ |
| SOUL-13.3 | W7 | PENDING | live (real Windows/Android gates, initiative SEND, 24/48h observability) | L~ |
| SOUL-13.4 | W7 | PENDING | provider (rotation/proxy documented from provider evidence, no secrets) | l |
| SOUL-14.0–14.2, 14.4 | W8 | PENDING | ui (influence diagram) + integration (metrics, flag rollback without data loss) | l |
| SOUL-14.3 | W8 | PENDING | live (human A/B judgement on 30–50 anonymized replies) | L~ |
| SOUL-15.0–15.4 | W1 | PENDING | static schema + dry-run report + integration (transaction, conflict, rights) | – |
| SOUL-15.5, 15.7 | W2 | PENDING | integration (hot apply on two chats, immutable snapshot, degradation reasons, PG outage) | – |
| SOUL-15.6, 15.8, 15.9 | W8 | PENDING | integration (flags/canary) + measurements (prompt growth, p50/p95, cost) + static scenario ledger | – |
| SOUL-16.0, 16.P1, 16.1.1–.5, 16.2.1–.4, 16.3.1–.4, 16.4.1–.5 | W3 | PENDING | unit (typed rules, pass/repaired/exempted/conflict, Unicode classes, protected spans, single normalization pass) + integration | – |
| SOUL-16.5.0–.2 | W6 | PENDING | ui (one editor separate from core, examples before/after, mobile 320–430, Save not covered by keyboard) | l |
| SOUL-16.5.3 | W3 | PENDING | integration + live (10+ heterogeneous inputs through Direct/Initiative/tool-backed on test delivery contour; real chat only with owner permission) | l |
| SOUL-17.0, 17.P1, 17.1–17.4 | W6 | PENDING | ui (surface inventory, real refraction evidence, tokens, perf/reduced-motion/fallback) | l |
| SOUL-17.5 | W6 | PENDING | ui + live (identical before/after frames 390/1440 on frozen polygon, contrast pattern proof, Reviewer sees images) | l |
| SOUL-17.6 | W6 | PENDING | static diff + Reviewer (forbidden changes absent) | – |
| SOUL-18.0–18.7 | W5 | PENDING | integration (funnel, diagnostics, prefs, health≠outcome) + live (24–48h counters, real group acceptance) | 18.4,18.5 = l; 18.0,18.2,18.3,18.6,18.7 = L~ |
| SOUL-19.0–19.6 | W8 | PENDING | unit/integration/ui/live per subsection + release gate record with deployed SHA | 19.0,19.3,19.5 = L~ |
| SOUL-21.0–21.11 | W9 | PENDING | static report artifacts + ui screenshots + live evidence for A/B/fullscreen/initiative/learning | 21.3,21.4 = l; 21.5,21.6,21.7 = L~ |
| SOUL-AMD.0.1, 1.4, 2.1, 3.1, 3.3, 4.6, 7.1–7.2, 8.5 | W1 | PENDING | static (инвентарная карта §3, backup до удаления canon, source→registry mapping, аудит runtime-сборки) | – |
| SOUL-AMD.0.2, 1.1–1.3, 1.5, 2.2–2.3, 2.8, 2.10–2.13, 3.2, 3.4, 3.6, 4.1–4.5, 7.3, 8.1–8.2, 8.4 | W2 | PENDING | unit/integration (Factory Default = полный SOUL-02, Prompt Registry, factory revisions/diff/reset/inheritance, hot apply, один effective Core) + live для 8.1–8.2 (реальные обезличенные сцены) | 8.1, 8.2 = l |
| SOUL-AMD.1.6–1.7, 2.4–2.5, 2.7, 2.9, 3.5 | W3 | PENDING | unit/integration (два режима, protected spans, дешёвая проверка) + live (публичные Factcheck/Summary и tool-ответы через Core + жанровый слой) | 1.6, 1.7, 2.9 = l |
| SOUL-AMD.2.6 | W4 | PENDING | integration + live samples (сны/глубокий сон/ностальгия/лор/истории/воспоминания через Core и жанровые правила) | – |
| SOUL-AMD.0.3, 6.1–6.6, 8.3 | W6 | PENDING | ui (разделы, Prompt Registry UI по правам, Effective Prompt Inspector, «Возможности бота») + live (правки MiniApp меняют следующую генерацию, мобильная доступность) | все = l |
| SOUL-AMD.7.4, 8.12–8.13 | W8 | PENDING | static + review evidence (реальная сборка/доставка в ревью, unit/integration/e2e/реальный trace, блокирующие условия релиза) | – |
| SOUL-AMD.8.14 | W9 | PENDING | static report artifacts (архитектура простыми словами, change map, Factory Defaults, реальные effective prompts/traces без секретов, честный live-чеклист) | – |
| SOUL-AMD.0.4, 5.1–5.18, 7.5, 8.6–8.11 | W10 | PENDING | unit/integration (capability resolver + статусы, ровно один вызов tool, idempotency, delivery confirmation) + live (реальные сценарии image/search/factcheck/video; не моки) | 5.17, 8.6–8.8, 8.10–8.11 = l; 8.9 = L~ |

## 5. Never auto-closable (require a real human, real client or live observation)

1. **SOUL-12.0, 12.1, 12.3, 12.4, 12.5** — real Telegram Desktop Windows / Android / Telegram Web: actual `requestFullscreen`, `isFullscreen`, launch-mode matrix, visual fullscreen. Mocks are regression-only.
2. **SOUL-18.2, 18.3, 18.6, 18.7 and SOUL-05.8** — real group without addressing the bot, actual SEND delivery, 24–48h observation; `LIVE_UNVERIFIED` is the expected state until then.
3. **SOUL-08.12** and **SOUL-21.6** — real conversations (metaphor picked up, request to stop, brigading protection) with `observed → lesson → application → outcome`.
4. **SOUL-11.4** and **SOUL-10.P5**, **SOUL-19.3** — real TMA on Android/Telegram Desktop and real WebView screenshots at 320/390/1440; Playwright Desktop is not sufficient alone.
5. **SOUL-14.3** and **SOUL-21.5** — owner/human A/B judgement on 30–50 anonymized real replies (blind order, quality/cost/regressions).
6. **SOUL-16.5.3** — sending hard-rule outputs into a working Telegram chat only with explicit owner permission; otherwise the test delivery contour is the ceiling.
7. **SOUL-17.5** — Reviewer must look at real before/after images on a frozen polygon position; CSS diff alone is not acceptance.
8. **SOUL-13.3, 13.4, 21.7, 21.8** — external/history evidence: legacy v6.3 live gates, provider quota behaviour, `225c3c2b` SHA reconciliation; cannot be closed from local code alone.
9. **SOUL-EXEC.12** — production deploy with rollback plan, backup and integrity control.
10. **SOUL-AMD.5.17, 8.1–8.3, 8.6–8.11 и 6.1–6.6** — реальные прогоны уточнения: живые сцены чата, реальный tool trace провайдера, фактическая доставка Telegram (включая ошибку доставки), MiniApp/WebView; моки и собранный шаблон не являются доказательством (SOUL-AMD.8.12, 8.13).

## 6. Backlog decision

Nothing from the current source is demoted to backlog: all 101 inventory items are classified (96 required, 5 documented `context` for subsection headings whose items are mapped separately), and 97 prose/visual obligations are added manually. Legacy ASAP8 v6.3 items are **not** re-executed; they live in a visible registry inside SOUL-13 and the §21 report (SOUL-13.3), never silently marked closed.

Уточнение владельца (amendment, приоритетный источник): 66 inventory items классифицированы (51 required + 15 `context` подзаголовков) и 28 прозаических обязательств добавлены вручную = **79 req_ids**; ничего не отправлено в backlog. Четыре строки основной карты переклассифицированы в `user_excluded` решением владельца (см. amendment-pass ниже): SOUL-03.5, SOUL-04.3, SOUL-04.4, SOUL-04.6 — это единственные `user_excluded`; совместимые части каждой строки перекрыты новыми req_id уточнения. Обе карты ко-гейтятся: ни одна карта не может закрыть эпик в одиночку.

## 7. Next Orchestrator action

1. **JB-A (join barrier уточнения):** обе карты прогнаны `check --stage plan` → `errors=0` (логи в amendment-pass ниже). W3/W4/W6 **и** W10 не диспатчить до фиксации JB-A; барьер выполняется повторно, если меняется любая из карт.
2. Открыть wave 2 в пределах 3 writer-лан: **W10** (Capability Awareness & Tool Grounding, §5; lane 1), **W3** (Style Policy + расширение Core-покрытия публичных Factcheck/Summary/tool-ответов; lane 2), **W4** (Humor Craft + сны/ностальгия/лор; lane 3). W5 переносится в wave 3 (к W6) — иначе превышается лимит 3 writer-лан.
3. Для каждого слайса требовать `requirements_gate.py check --stage review --slice <Wn> --candidate <sha>` по **обеим** картам для его req_id (у W10 — все SOUL-AMD.5.x/8.x с живыми trace); W6 дополнительно требует JB-3 (backend API frozen) и capability-контракт W10 для «Возможности бота».
4. Релиз (W8): `check --stage release --candidate <sha> --deployed-commit <sha>` по обеим картам; в §21-отчёте четыре `user_excluded` строки перечисляются как «исключено уточнением владельца» с `user_approval_ref`, а не как потерянные требования.

## Amendment pass (владельческое уточнение, 2026-10-16)

Источник: `source-architectural-clarification.md` (SHA256 `338FD9C6BD323A7EA8AD80577C2E9D8B45A714D30BDD4FC9147AF75931A4A35C`), приоритет над противоречащими старыми формулировками. Карта: `requirements-map-amendment.json` — 66 inventory (51 required + 15 `context`) + 28 manual = **79 req_ids**: W1 9, W2 24, W3 7, W4 1, W6 8, W8 3, W9 1, W10 26.

Реконсиляция основной карты (единственные изменения — 4 строки, текст/req_id/acceptance не переписаны; добавлены `disposition`, `reason`, `user_approval_ref`):

| Строка | Почему подавлена | Ссылка на решение владельца | Перекрытие совместимых частей |
|---|---|---|---|
| SOUL-03.5 | Ветка «legacy custom с сохранённым эффектом до решения владельца» отменена: legacy custom-промпты не активный слой, специальная UI-миграция не добавляется, старые каноны — только в аварийной копии | §1 п.2 (стр. 10), §4 п.6 (стр. 58) | SOUL-02.8, SOUL-03.1, SOUL-AMD.1.2/1.4 |
| SOUL-04.3 | «Владельческие кастомы сохранены» как речевой слой отменено; удаление «токсичный/циничный» и защита фактчека/антиигаллюцинаций остаются | §1 п.2 (стр. 10), §4 п.6 (стр. 58) | SOUL-AMD.1.2, 2.11, 3.3 |
| SOUL-04.4 | Модель миграции заменена: Migration Preview/специальная UI-миграция для legacy custom не добавляется; идемпотентность и безопасность повтора сохраняются | §1 п.2 (стр. 10), §4 п.6 (стр. 58), §7 п.2 (стр. 113) | SOUL-15.3, SOUL-AMD.7.2 |
| SOUL-04.6 | Публичный Factcheck больше не «machine-only»: публикация обязана идти через Core + жанровый слой; без Core — только анализ доказательств и внутренние стадии Summary | §2.1 (стр. 24), §2.2 (стр. 34), §2.3 (стр. 38) | SOUL-BOUND.4, SOUL-AMD.2.4/2.7/2.11 |

Строки, **сознательно не тронутые** (совместимы, противоречащих формулировок нет): SOUL-EXEC.8 (сохранность данных/rollback — backup удовлетворяет), SOUL-03.1 (модуль не удаляется), SOUL-03.6 (no double render), SOUL-04.5 (no second LLM writer), SOUL-15.2/15.3/15.9 (миграционные механики, custom_legacy = data-safety), SOUL-16.4.3 (legacy участвует «по явно описанному precedence» — при конфликте применяется приоритет уточнения: legacy-каноны удаляются из runtime), SOUL-19.1 (тестовая строка «legacy PG custom preservation» остаётся в Data-safety смысле), SOUL-BOUND.5 и SOUL-16.4.4 (явная редакционная eligibility теперь конкретизирована уточнением §2.1/§2.3, исключений не требуется), SOUL-10.P1/P2 (IA по аудиту, разделы §6.1 уточнения встраиваются в витрину).

Gate-логи (plan stage, обе карты): см. зафиксированный вывод в конце этого файла/в отчёте PM; `requirements-map-amendment.json` → `inventory=66 manual=28 scoped=0 errors=0`; `requirements-map.json` → `inventory=101 manual=97 scoped=0 errors=0`.

## Fix pass (review F1–F7)

Applied 2026-10-16 after the independent source↔map review (`review-map.md`, Needs Fixes). Targeted edits only: req_ids, dispositions, slices and `source_text_sha256` untouched; item count unchanged (101 inventory = 96 required + 5 context; 97 manual; 193 req_ids).

| # | Finding | Changed field | New value |
|---|---|---|---|
| F1 | SOUL-01.1 / SOUL-21.1 omitted the mandated speech-path inventory (`YouTube`, `Checkup`, `Search`, ручные тесты absent from the map) | `requirements-map.json` → `items[3].acceptance` (SOUL-01.1) and `items[91].acceptance` (SOUL-21.1) | both now end with: «…; matrix обязательно включает пути Direct L1/L2, legacy/direct fallback, System2, Initiative, Factcheck, Summary human-facing, Search, Web, YouTube, Checkup, возможные сны/истории, ручные тесты и шаблоны» (SOUL-01.1 also keeps the per-path PG key/default/priority/effective source/assembly method/delivery channel clause) |
| F2 | SOUL-14.1 dropped the source boundary «это не новая панель всех внутренних событий» | `additional_requirements[78].acceptance` (SOUL-14.1) | «…какие данные были подтверждены, и это не новая панель всех внутренних событий (второй аналитической стены нет)» |
| F3 | SOUL-13.2 dropped «доступность только в разрешённой test-среде» | `items[37].acceptance` (SOUL-13.2) | «…либо закрыт серверной авторизацией; стенд доступен только в разрешённой test-среде (положительная проверка); боевой polygon background и liquid glass не изменены» |
| F4 | SOUL-13.2 `live_when=preprod` — production static-asset exposure closable without the deployed path | `items[37].live_when` (SOUL-13.2) + plan row 91 | map: `postdeploy`; plan row 91 gate `l` → `L~`, evidence now «anonymous probe 401/403/404 against the deployed production host; stand reachable only in the permitted test environment» |
| F5 | (a) SOUL-16.5.3 gated postdeploy although its evidence is the test delivery contour; (b) SOUL-BOUND.3 `live_required=false` while comparable quality claims are live | (a) `additional_requirements[87].live_when` (SOUL-16.5.3), (b) `additional_requirements[15].live_required` (SOUL-BOUND.3); plan rows 101 / 74 | (a) `preprod` (plan row 101 gate `L~` → `l`; owner-permission real send stays optional); (b) `true`, plan row 74 evidence now names real-path samples «real Direct/Initiative/tool-backed runs: real chat logs / real run samples, not fixtures alone» and gate becomes `BOUND.3 = l` |
| F6 | (a) SOUL-14.3 turned a permission into an obligation (added MiniApp scope); (b) SOUL-21.5 added owner judgement not present in L299 | (a) `additional_requirements[80].acceptance` (SOUL-14.3), (b) `items[95].acceptance` (SOUL-21.5) | (a) «человеческие оценки **могут** собираться в MiniApp»; (b) «включая оценку владельца (производное от L289)» |
| F7 | plan.md stated "10 slices" while W1–W9 = 9 | `plan.md` L7 (map row) | «= **193 req_ids**, 9 slices (W1–W9)» |

Recheck performed (own run): `requirements_gate.py check --map plans/features/soul-1/requirements-map.json --stage plan` → `inventory=101 manual=97 scoped=0 errors=0` (exit 0). Only the fields listed above were modified; no renumbering, no disposition/slice changes, source binding `8C42DDFABCE635FE4E1F24F9522FF8642F3BD3049FAC05C77CA162687051196B` unchanged. W1 remains blocked until this fix pass is re-checked by the Reviewer lane.

## W2 binding (4116c48a)

**Кандидат:** `4116c48a74e08c8be8c4cc1f3ed37bf62ed3e8e4` (= master `50a7e689` + fix-pass W2, «Approved за F1–F3 + Core-budget» в `review-w2.md`). В обеих картах `candidate_commit` = этот SHA, `deployed_commit` пуст (деплоя нет). Совпадение с ревью-кандидатом подтверждено хешами: `prompt_composer.py=426D93014FC9`, `direct_chat_service.py=D603E00DB241`, `mca_gates.py=2DA5986D8CCD`, `prompt_style_blocks.py=A62AB337A2D6`; тесты `parity_off=33C0D128B3A4`, `layers=296BE6D5F300`, `legacy_custom=13801A5FCB88` — 1:1 с review-w2. W2-строк: main 33 (29 required + 4 `user_excluded`), amendment 24.

**Переведены в VERIFIED (main, 5):** `SOUL-03.2` (иерархия уровней 1–7 как канонический порядок слоёв; SelfModel-контракты сохранены, черты folded), `SOUL-03.6` (одна инструкция не рендерится дважды: conflict `duplicate_owner_character`/`keep_stronger` с провенансом), `SOUL-04.2` (слои разделены по назначению, характер несёт только `core`), `SOUL-04.5` (0 доп. LLM-вызовов, бюджет не вытесняет вопрос/evidence/Core, лишние слои `skip_reason`), `SOUL-BOUND.4` (machine_json = только канал-контракт; L1/Stage-1 на реальных методах без Core/юмора). У каждой строки evidence привязано к `4116c48a…` (tests + манифест `evidence/w2/manifest-direct-l2.txt` + review-ledger).

**Amendment: 0 строк переведено в VERIFIED** — правдоподобных по этой поставке нет (все требуют реестра/фабричных редакций/UI/живых прогонов либо блокированы hard rule).

**Оставлено открытым с причиной в поле `reason`:**

1. **Заблокировано уточнением владельца (hard rule — не VERIFIED в этом проходе):** `SOUL-AMD.1.2`, `SOUL-AMD.8.4` (при ON base_prompt = слой `channel_contract`, т.е. legacy-каноны/PG-речевые overrides остаются в effective-слое; backup+удаление — слайс W1 после JB-3). Зависящие main-строки: `SOUL-BOUND.0`, `SOUL-BOUND.1`, `SOUL-BOUND.2`, `SOUL-03.1`.
2. **Вне поставки W2 — реестр/фабричные редакции/UI (§3/§4 уточнения):** `SOUL-AMD.1.1`, `SOUL-AMD.3.2`, `SOUL-AMD.3.4`, `SOUL-AMD.3.6`, `SOUL-AMD.4.1–4.5`, `SOUL-AMD.0.2`, `SOUL-AMD.2.12`; main: `SOUL-02.0`, `SOUL-02.1–02.8` (Core-документ не заведён — `core_absent`), `SOUL-03.0`.
3. **Частично / нужен отдельный шов или слайс:** `SOUL-04.1` (копии `STYLE_BLOCKS_SUFFIX` остаются в search/web/youtube/checkup/factcheck/summary — пять семейств не переведены; review-w2 §4.2), `SOUL-15.5` (snapshot/rollback + шов `mca_self_model`), `SOUL-15.7` (PG outage/stale/restart-клаузы не проверялись; hard-запрет `styled=true` — W3), `SOUL-03.3`/`SOUL-03.4` (конфликт Core↔derived-правил и негативные кейсы сверх Core-оверрайда), `SOUL-04.0`, `SOUL-AMD.1.5`, `SOUL-AMD.2.2`, `SOUL-AMD.2.8`, `SOUL-AMD.2.11`, `SOUL-AMD.2.13`, `SOUL-AMD.7.3`.
4. **Живые/реальные прогоны:** `SOUL-BOUND.3` (live_required), `SOUL-AMD.8.1`, `SOUL-AMD.8.2`.
5. **Совместимость уточнения:** `SOUL-AMD.2.10` — истинность/evidence для подключённых путей не нарушаются, но публичные Factcheck/Summary ещё не подключены.

**Флаг/релиз:** `UNIFIED_COMPOSER_ENABLED` (env + `flags.unified_composer_enabled`) и регистрация `flags.*` остаются OFF; маркер `composer_flag_release_gate` подтверждён ревью в трёх местах (отчёт :220, `prompt_composer.py:524–538`, шапка `test_soul1_legacy_custom_preserved.py`). Включение — только после слайса-amendment и повторной проверки F1.

**Обратная проверка текста уточнения (item 4):** ни одна открытая строка не противоречит уточнению; недостижимых буквально строк нет — у каждой назван недостающий артефакт. Единственная строка с внешней неоднозначностью: `SOUL-AMD.2.3` в части «реакции с текстом» — отдельного словесно-реакционного writer-пути в поставке и в контуре композера нет (`reactions_word_reactions` — legacy-группа); трактовку («путь не существует» = строка закрывается иначе) должен подтвердить Orchestrator/владелец, а не PM молча.

**Гейты (review, обе карты, кандидат `4116c48a74e08c8be8c4cc1f3ed37bf62ed3e8e4`) — verbatim, exit 1 каждая (ожидаемо: открытые строки, не форсировались):**

```
FAIL: SOUL-BOUND.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-03.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-04.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-15.5: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-15.7: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-BOUND.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-BOUND.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-BOUND.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-BOUND.5: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-BOUND.6: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-BOUND.7: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.5: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.6: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.7: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-02.8: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-03.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-03.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-03.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-04.1: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=101 manual=97 scoped=29 errors=24
```

```
FAIL: SOUL-AMD.1.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.1.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.1.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.8: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.3.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.3.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.3.6: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.4.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.4.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.4.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.4.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.4.5: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.7.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.8.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.8.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.8.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.0.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.1.5: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.10: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.11: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.12: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.13: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=66 manual=28 scoped=24 errors=24
```

**Следующее действие (для Orchestrator):** W2 не объявляется Approved-по-гейту и не закрывает эпик; решения требуются по (а) re-slice/расширению для пяти писательских семейств и Factcheck/Summary (SOUL-04.1, SOUL-AMD.2.2/2.8/8.1), (б) мини-слайсу шва `mca_self_model` (SOUL-15.5), (в) слайсу реестра/фабричных редакций (§3/§4 уточнения), (г) слайсу удаления legacy-канонов (AMD.1.2/8.4) с backup — только после него включать флаг и повторять F1.

## W6 binding (a5902b15)

**Кандидат:** `a5902b15e7bf943dc454dbf59ee9b9fe1152a87e` (= master `c8cf77a5` + W6, «Approved» в `review-w6.md`, третий вердикт RECHECK-W6-2; цепочка REVIEW-W6 Needs Fixes → FIX-W6 → RECHECK-W6 Needs Fixes (EOL) → FIX-W6-EOL → FIX-W6-LESSON → RECHECK-W6-2 Approved). В обеих картах `candidate_commit` = этот SHA, `deployed_commit` пуст (деплоя нет). W6-строк: main 29 (16 inventory + 13 additional), amendment 8 (7 inventory + 1 additional). LF-инвариант коммита проверен после `git commit`: `git show HEAD:web/app.js` = `401a40a5…` (CRLF=0), `git show HEAD:web/index.html` = `8d86cd1a…` (CRLF=0), сторож `tests/js/app_methods_dup_keys_guard_test.js` = `68243a47…` (LF).

**Переведены в VERIFIED (main, 19):** `SOUL-10.0` (единая точка входа + 6 разделов: live Chrome, ui-report.json failures=0/94 кадра, тест состава экрана), `SOUL-10.1` (Характер: round-trip ревьюера global→chat→factory→rollback + тесты core/compact + harness POST block/core.personality), `SOUL-10.2` (Стиль письма: F2 закрыт live Browser Use — галки/пресеты/счётчик/привычки/черновик + тесты save/preview/draft), `SOUL-10.3` (Выражение: 4 контрола + рендер слоя, честный `runtime_wired=false`), `SOUL-10.5` (Попробовать: current vs candidate без отправок, `telegram_send=false`/`lessons_created=0`), `SOUL-16.5.0` (карточка «Стиль письма» → один редактор, отдельный от Core), `SOUL-10.P1–P4` (не «приборка»: хаб 5 карточек и пин f5; витрина карточек/один экран за раз; один Inspector с preview≠sent и маскировкой; pageOverflow=0/minTap=44/padding 12/сплит 1↔2 колонки на 320–1440+landscape), `SOUL-17.0–17.6`, `SOUL-17.P1`, `SOUL-EXEC.14` (стекло: `review-tiera.md` + `review-tiera-strengthened.md` (Approved, независимые замеры) связаны с кандидатом байтовым инвариантом W6-ревьюера — polygon blob `c2ad97d4…`, `#lg-lens` `5367ec45…`, `--lg-*` `89cda50a…` == HEAD; на кандидате зелёные glass_probe/design_tokens/shell/fullscreen; H2 политика «diff фона пуст»). Amendment VERIFIED (7): `SOUL-AMD.6.1` (витрина 7+3, live), `6.2` (F3 закрыт на реальном `/reset`: changed=True 2882→2835, diff{−2/+0}; фикстура снята настоящим эндпоинтом), `6.3` (320–430 + live 390/320/430, навигация не переделана), `6.4` (F1 закрыт: рантайм-форма uuid-run_id достижима; preview≠sent; маскировка), `6.5` (/capabilities + trace, «доступное действие не выбрано»), `6.6` (hot-контур без рестарта), `0.3` (владельческий контроль: единственный путь записи + RBAC).

**READY_FOR_LIVE (main 2, amendment 1):** `SOUL-10.P5` и `SOUL-11.4` — postdeploy (скриншот/interaction-матрица выполнена, реальный Telegram WebView и сохранение/восстановление на настоящем клиенте — только после деплоя); `SOUL-AMD.8.3` — вердикт ревьюера «за канарейкой, flag ON»: живая генерация на этом слайсе не проверяема, запись — единым путём.

**Оставлено PENDING с причиной в поле `reason` (main 8):**

1. `SOUL-10.4` — humor-библиотека («Примеры») поставляется слайсом W4; UI честно отдаёт `not_implemented_w4` (ревьюер: N/A_WITH_REASON (W4)).
2. `SOUL-10.6` — полная формулировка требует humor-контур и `reset-learning` (W4); подтверждены только уроки Experience с pause/approve через существующий `/api/memory/lessons/action`.
3. `SOUL-11.0` — подтверждена одна цепочка («Все инструкции» 320–430), вторая точка входа — не этот слайс (review-w6); E2E с реальными ответами API по обеим точкам нет.
4. `SOUL-11.1`, `SOUL-11.2`, `SOUL-11.3` — цепочки `#/ai/prompts` → catalog → Direct/Синтезатор/Вербализатор и «Модули → Ответы в чате → Промпты», индекс «Ответы в чате» и инвентаризация PG-ключей на этом слайсе не проверялись.
5. `SOUL-16.5.1` — первый экран и действия подтверждены (F2 live + тесты + харнесс), но «История изменений» для политики стиля в слайсе не поставлена (`style_policy_view` не отдаёт `history`; блок index.html:7613 пуст) и advanced-состав поимённо не проверялся.
6. `SOUL-16.5.2` — подтверждены preview≠sent, черновик при навигации, 320–430 без overflow и minTap=44; не подтверждены «Save не накрыт клавиатурой» и «одна раскрытая настройка» на 320–430.

**Гейты (review, обе карты, кандидат `a5902b15e7bf943dc454dbf59ee9b9fe1152a87e`) — verbatim, exit 1 каждая (честно: открытые строки, не форсировались; main-ошибки — только PENDING-строки, amendment — только канареечная 8.3):**

```
FAIL: SOUL-10.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-10.6: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-11.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-11.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-11.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-11.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-16.5.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-16.5.2: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=101 manual=97 scoped=29 errors=8
```

```
FAIL: SOUL-AMD.8.3: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
stage=review inventory=66 manual=28 scoped=8 errors=1
```

**Следующее действие (для Orchestrator):** W6 готов к коммиту/канарейке с открытыми пунктами выше: (а) humor-контур W4 закрывает 10.4/10.6; (б) mobile-prompts цепочки 11.0–11.3 требуют отдельной проверки на реальном route entry; (в) 16.5.1/16.5.2 — мини-дополнение по «Истории изменений» политики стиля и мобильной клавиатуре; (г) 10.P5/11.4/8.3 закрываются после деплоя/канарейки (postdeploy).

**Corrections (REVIEW-W6-BINDING):**

1. `SOUL-17.4` (main): `VERIFIED` → `READY_FOR_LIVE`, `live_when` = `postdeploy`; `reason` заполнен: токены/reduced-motion/overdraw/fallback и перф на Windows/desktop-Chrome (вкл. 390-эмуляцию) подтверждены (review-tiera, review-tiera-strengthened, byte-invariant review-w6); реальный Android/TMA GPU-замер — device-only, ждёт postdeploy live-проверки (по образцу 10.P5). Evidence-список не менялся; перечень READY_FOR_LIVE выше («main 2») — состояние до этой правки, после неё main = 3: `SOUL-10.P5`, `SOUL-11.4`, `SOUL-17.4`.
2. `SOUL-AMD.8.3`: `live_when` = `preprod` → `postdeploy`; статус `READY_FOR_LIVE` сохранён (канарейка/postdeploy по review-w6).
3. Счёт W6-строк уточнён: main 29 (16 inventory + 13 additional) — сумма прежняя (29), исправлена разбивка inventory/additional.

**Гейты после правок (review, обе карты, кандидат `a5902b15e7bf943dc454dbf59ee9b9fe1152a87e`) — verbatim, `errors=8` exit 1 / `errors=0` exit 0:**

```
FAIL: SOUL-10.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-10.6: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-11.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-11.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-11.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-11.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-16.5.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-16.5.2: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=101 manual=97 scoped=29 errors=8
```

```
stage=review inventory=66 manual=28 scoped=8 errors=0
```

## W1/W3/W10 binding (post-factum)

**Кандидаты слайсов:** W1 `3cc0b9c0541aa9c5a81c2caa995644bb1af61f11` («Prompt Registry, Factory Defaults, legacy removal»; review-w1 Needs Fixes → Approved после recheck), W3 `4c8405e783ac005ac0044974c5fbd7e518d12e2a` (Speech Style Policy + one_word/micro; review-w3 NF → Approved), W10 `c8cf77a5065f4cbc0a77616da6bbd7e1154ba5c8` (Capability Awareness & Tool Grounding; review-w10 NF → Approved после recheck). Привязка выполнена post-factum по образцу W6-binding: для каждой строки слайса в обеих картах выставлены `status`/`reason`/`evidence` (evidence привязано к SHA слайса); W2/W6-строки и их evidence не трогались. Формат карт сохранён (JSON `indent=2`, `ensure_ascii=False`, CRLF); построчный дифф: изменены только поля status/reason/evidence строк W1/W3/W10 (main 53 из 198, amendment 42 из 94), прочие строки — байт-идентичны. **Top-level `candidate_commit` обеих карт остаётся W6-кандидатом `a5902b15e7bf943dc454dbf59ee9b9fe1152a87e`** (single-candidate семантика инструмента; временные подмены на SHA слайсов при прогонах откатаны, контроль W6 — зелёный по амендменту, см. ниже). **Финальный release-re-anchor на задеплоенный SHA — отдельным проходом родителя** (W8/W9).

**Итог по строкам (обе карты, 95 строк W1/W3/W10 = 29+40+26; состояние после решения родителя, follow-up):**

| Слайс | Строк | VERIFIED | PENDING | READY_FOR_LIVE (postdeploy) |
|---|---|---|---|---|
| W1 (main 20 / amend 9) | 29 | 18 (11+7) | 11 (9+2) | 0 |
| W3 (main 33 / amend 7) | 40 | 25 (24+1) | 10 (5+5) | 5 (`SOUL-05.2/05.3/05.5/05.6` + `SOUL-AMD.1.7`) |
| W10 (amend 26 / main 0) | 26 | 19 | 0 | 7 (`SOUL-AMD.8.6–8.11` + `SOUL-AMD.5.17`) |

**Решение родителя (follow-up):** live-класс «движок/мок подтверждён, живая половина ждёт канарейку» переведён в `READY_FOR_LIVE` + `live_when=postdeploy` (образец SOUL-AMD.8.3 / SOUL-17.4 / SOUL-10.P5 / SOUL-11.4) с точными причинами: W3 — `SOUL-05.2/05.3/05.5/05.6`, `SOUL-AMD.1.7`; W10 — `SOUL-AMD.8.6/8.7/8.8/8.10/8.11`, `SOUL-AMD.5.17` (у 5.17 ранее приложенное evidence не менялось). Для переведённых строк добавлено минимальное candidate-bound evidence (ссылки на разделы ревью/артефакты; ранее приложенное evidence не переписывалось). НЕ переведены — у строки есть и не-live пробел, оставлены PENDING с точной причиной: `SOUL-05.7` (SILENT/REACT и tool-result — W5-покрытие), `SOUL-16.5.3` (tool-backed-путь и часть списка классов — поимённо ревью не подтверждены), `SOUL-AMD.1.6` (UI-часть — ledger «+ W6 UI»; W6-кандидат one_word/micro-UI поимённо не подтверждает).

**Открытые строки — что именно не закрыто и чем закрывается:**

1. **W1 — процессные клаузы release/report (4):** `SOUL-EXEC.1`, `SOUL-EXEC.4` — gate-стадия «release» ещё не прогонялась (деплоя нет); `SOUL-EXEC.2`, `SOUL-EXEC.7` — «видно явно в отчёте» / «равный статус в отчёте» появятся в §21-отчёте (W9). Snapshot с SHA256, полнота карты (review-map.md Approved), назначение исполнителей и plan/review-логи подтверждены артефактами.
2. **W1 — зависят от других слайсов/живого снимка (7):** `SOUL-01.0`+`SOUL-01.5` (клауза «ровно один путь к общему Core» — Core ещё не заведён, W2 core_absent), `SOUL-15.0` (подстроки 15.5/15.7 — W2, 15.6/15.8/15.9 — W8), `SOUL-15.2` (Core/Sample Library к versioned-конфигу — W2/W4), `SOUL-15.4` (права VERIFIED по факту в W6/AMD.0.3, но не на W1-кандидате — кандидат на переанкор), `SOUL-AMD.4.6` и `SOUL-AMD.7.2` (4 неудерживаемых summary-кастома, JB-3 write-pass и обратимость деплоя — живой снимок + решение JB-3 + канарейка; ср. AMD.1.2/8.4 — W2).
3. **W3 — live-класс (переведён решением родителя, follow-up, см. блок выше):** `SOUL-05.2/05.3/05.5/05.6` и `SOUL-AMD.1.7` → `READY_FOR_LIVE`+postdeploy (движок и тест-контур подтверждены ревью: w3-style-report §4.5 `LIVE_UNVERIFIED` была живая половина; review-w3: «live-часть — вне этого вердикта»). Остались PENDING только строки с не-live пробелом: `SOUL-05.7`, `SOUL-16.5.3`, `SOUL-AMD.1.6`.
4. **W3 — не поставлено / перескоп F5 (7):** `SOUL-16.4.4` (eligibility финального Factcheck/редакционной Summary), `SOUL-09.3` (связка с Experience — W4/W5), `SOUL-AMD.2.4/2.5/2.7/2.9` (публичные Factcheck/Summary/tool-ответы через Core — ждут Core; перескоп — решение PM/Architect), `SOUL-05.0` (контейнер — закрывается вместе с 05.7).
5. **W10 — live-класс (переведён решением родителя, follow-up, см. блок выше):** `SOUL-AMD.8.6/8.7/8.8/8.10/8.11` и `SOUL-AMD.5.17` → `READY_FOR_LIVE`+postdeploy (мок-часть подтверждена review-w10/recheck, включая мутации; живая половина — канарейка: 1 реальный семантический запрос + 1 кейс отказа + trace, review-w10). PENDING в слайсе W10 нет; review-гейт слайса — зелёный (`errors=0`).

**Спорные/особые классификации (явно):**
- `SOUL-AMD.5.17` — по решению родителя (follow-up) переведена из `VERIFIED` в `READY_FOR_LIVE` + `live_when=postdeploy` с точной причиной (мок/движок-часть: review-w10 ledger 5.17 + recheck — цепочка/idempotency/send-failed/replay; живая половина: реальный провайдер/Telegram и фактическая ошибка доставки — канарейка); ранее приложенное evidence не менялось. Ранее честный красный гейт (`live requirement lacks evidence`) закрыт классификацией.
- `SOUL-16.P1` закрыт по совокупности (отдельная первосущность и слои — review-w3 §4/16.0/16.4.1 + композер style_policy_hint — W2/W6); ревью не судило строку отдельно — зафиксировано в evidence.
- `SOUL-09.3`, `SOUL-16.5.3` ревью отдельно не судило; 09.3 оставлена PENDING (связка с Experience не проверялась), 16.5.3 на follow-up родителя специально НЕ переведена в postdeploy (есть не-live пробелы: tool-backed-путь и часть списка классов поимённо не подтверждены ревью) — осталась PENDING с точной причиной.
- W4 (незакоммиченный в дереве) не затронут; его файлы в этой привязке не изменялись.

**Гейты (review, verbatim; для каждого слайса top-level candidate временно = SHA слайса на обеих картах, затем восстановлен на `a5902b15…`):**

W1 — main:
```
FAIL: SOUL-EXEC.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-01.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-01.5: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-15.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-15.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-15.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-EXEC.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-EXEC.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-EXEC.7: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=101 manual=97 scoped=20 errors=9
EXITCODE=1
```
W1 — amendment:
```
FAIL: SOUL-AMD.4.6: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.7.2: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=66 manual=28 scoped=9 errors=2
EXITCODE=1
```

W3 — main (**решение родителя, follow-up**: live-класс переведён; остались только не-live открытые строки):
```
FAIL: SOUL-05.0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-16.4.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-05.7: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-09.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-16.5.3: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=101 manual=97 scoped=33 errors=5
EXITCODE=1
```
W3 — amendment (**решение родителя, follow-up**):
```
FAIL: SOUL-AMD.1.6: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.4: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.5: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.7: mandatory not ['VERIFIED'] (got PENDING)
FAIL: SOUL-AMD.2.9: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=66 manual=28 scoped=7 errors=5
EXITCODE=1
```

W10 — main (строк W10 в основной карте нет — ожидаемый честный результат, без изменений на follow-up):
```
FAIL: review scope has no requirements: W10
stage=review inventory=101 manual=97 scoped=0 errors=1
EXITCODE=1
```
W10 — amendment (**решение родителя, follow-up**: live-класс переведён — слайс зелёный):
```
stage=review inventory=66 manual=28 scoped=26 errors=0
EXITCODE=0
```

**Контроль после восстановления candidate на `a5902b15e7bf943dc454dbf59ee9b9fe1152a87e` (W6-состояние не изменилось):** main — те же 8 PENDING-строк W6 (`SOUL-10.4, 10.6, 11.0–11.3, 16.5.1, 16.5.2`), `stage=review inventory=101 manual=97 scoped=29 errors=8, EXITCODE=1`; amendment — `stage=review inventory=66 manual=28 scoped=8 errors=0, EXITCODE=0` (совпадает с §W6 binding и его Corrections).

**Следующее действие (для Orchestrator; после решения родителя — follow-up):** (а) канарейка/postdeploy: живой прогон для READY_FOR_LIVE-строк W3 (5: 05.2/05.3/05.5/05.6, AMD.1.7) и W10 (7: AMD.8.6–8.11, AMD.5.17) + release-стадия гейта (live/production evidence); (б) `SOUL-15.4` — переанкор на W6-кандидат либо адресная проверка прав; (в) `SOUL-EXEC.1/2/4/7` — закрываются финальным release-проходом и §21-отчётом (W9); (г) не-live пробелы `SOUL-05.7` (W5), `SOUL-16.5.3` (tool-backed/классы), `SOUL-AMD.1.6` (UI) и перескопы F5 (`AMD.2.4/2.5/2.7/2.9`, `16.4.4`) — решения PM/Architect/родителя.

## W4 binding (c1cb6475)

**Кандидат:** `c1cb64753ae82940843709ab2dcca9603850a1a8` (= master `c5900874` + W4, «Approved» в `review-w4.md` после RECHECK-W4; цепочка REVIEW-W4 Needs Fixes → FIX-W4 (F1/F2/F3, RED→GREEN) → RECHECK-W4 Approved). В обеих картах top-level `candidate_commit` = этот SHA (single-candidate семантика инструмента; прежний указатель — W6 `a5902b15e7bf`); `deployed_commit` пуст (деплоя нет). W4-строк: main 25 (13 inventory + 12 additional), amendment 1 (`SOUL-AMD.2.6`). Финальные отпечатки файлов слайса (sha256_12, final, commit-time) — `w4-humor-feedback-report.md` §3/§10. LF-инвариант коммита проверен после `git commit`: `git show HEAD:web/app.js` = `11215e3a4d10…` (CRLF=0), `git show HEAD:web/index.html` = `9e0b761104ff…` (CRLF=0), сторож `speechLessonAction` на месте, новые исходники слайса LF-only.

**C1 (RECHECK-W4) — закрыт на коммите:** в dirty-вызов теста bounded-метаданных добавлены секрето-подобные kwargs `api_key`/`secret_prompt`/`raw_text` с безопасным значением (иначе утечку маскировал бы `_SAFE_TOKEN`), пин `SEND_FIELDS` сохранён; исходная выжившая мутация M11 ревьюера и форма «все переданные kwargs» — **KILLED**, мутационный свидетель расширен до 14 мутаций (**14/14**, `evidence/w4/mutation-witness.json`). Прогоны commit-time: W4-файлы **83 passed**; периметр **3869/0** (два прогона на одних байтах; промежуточная флейк-аномалия `3867/2` в `tests/test_nostalgia_worker.py` не воспроизвелась — файл изолированно 26 passed; зафиксировано в отчёте §4).

**Переведены в VERIFIED (main, 24):** `SOUL-06.0–06.7` (пять приёмов = закрытый набор L1 `COMIC_STRATEGIES` + заводские редакции; рамка «связность/уместность, а не частота мата»; toggle OFF → `humor_disabled` при живом Core; «Проверить приём» без LLM; 0 доп. LLM-вызовов; паритет OFF), `SOUL-07.0–07.3` (таблица `humor_samples` v36, 18 сидов-черновиков `bot_suggested` без owner_approved; отбор 1–3/ноль с diversity/recency + двойная PII-защита; изоляция chat-скоупа — F1: approve/archive чужого чата 403 по пробам ревьюера; A/B и «почему выбраны»), `SOUL-08.0–08.11` (контур внутри Experience, второй контур не создан; bounded-метаданные закрытого набора + C1; связи observed→…→outcome; семантическая классификация с fail-open; тишина = unknown; консерватизм с защитами малого N/бригандинга, Core не переписывается; расход Experience → следующий промпт (детерминированный эффект + затухание, мутации KILLED) + живая витрина телеметрии (F2: счётчик отправок исправлен)).

**READY_FOR_LIVE (main, 1):** `SOUL-08.12` — 7 сценариев закрыты детерминированными симуляциями + live-маркеры в UI; живого прогона с реальными собеседниками не было → канарейка **postdeploy**, до неё строка не закрывается.

**Amendment:** 0 строк переведено в VERIFIED — `SOUL-AMD.2.6` остаётся **PENDING** с точной причиной: частичная поставка (4 жанровые редакции + хелпер `authorial_system` + путь «Ностальгии», OFF = канон байт-в-байт), проводка снов/глубокого сна/лора/историй — следующий слайс (review-w4 §5, отчёт §1.4/§8.4).

**Гейты (review, обе карты, кандидат `c1cb64753ae82940843709ab2dcca9603850a1a8`) — verbatim; amendment-FAIL ожидаемый и честный (AMD.2.6 — частичная поставка), не форсировался:**

```
stage=review inventory=101 manual=97 scoped=25 errors=0
EXITCODE=0
```

```
FAIL: SOUL-AMD.2.6: mandatory not ['VERIFIED'] (got PENDING)
stage=review inventory=66 manual=28 scoped=1 errors=1
EXITCODE=1
```

**Следующее действие (для Orchestrator):** (а) канарейка postdeploy: живые сценарии `SOUL-08.12` (7) + release-стадия гейта; (б) ~~следующий слайс: проводка снов/глубокого сна/лора/историй через `authorial_system` (закрытие `SOUL-AMD.2.6`)~~ — **выполнено tail-слайсом AMD.2.6**: лор/истории проведены через `authorial_system`, сны/глубокий сон — подтверждённая граница «публикующего пути нет»; привязка ниже (§AMD.2.6 binding); (в) включение осей (`HUMOR_CRAFT_ENABLED`/`HUMOR_LIBRARY_ENABLED`/`HUMOR_FEEDBACK_ENABLED`) на одном чате под наблюдением.

## W5 binding (bc277a3d)

**Кандидат:** `bc277a3dc8bd54e721f5855fc6920f2ea401b25f` (= master `006fcfaa` + срез W5, коммит A; цепочка REVIEW-W5 **Needs Fixes** (overclaim D1) → FIX-W5 (только текст/докстринги, AST-идентичность) → **RECHECK: Approved (for controlled deployment; parent not DONE)**). Отпечаток 23-файлового набора W5 пересчитан по **коммитным** блобам — `20219378654acb9eeb77184b`, совпадает с отпечатком на ревью. В обеих картах top-level `candidate_commit` = этот SHA (single-candidate семантика; прежний указатель — W4 `c1cb6475`); `deployed_commit` пуст (пуша и деплоя нет). Коммит A: **91 файл** = 10 новых + 9 runtime/web + 3 артефакта каталога (`param-registry-round1025.{tsv,meta.md}`, `screen-map-round1025.md`) + 2 фикстуры + 55 ре-пинов чужих тестов + 12 документов слайса (`w5-initiative-report.md`, `review-w5.md`, `evidence/w5/**`).

**Строк W5:** main **9** (7 inventory: `SOUL-18.0`, `SOUL-18.2`–`SOUL-18.7` + 2 additional: `SOUL-05.8`, `SOUL-18.1`); **amendment — 0**: слайс W5 в amendment не представлен, гейт amendment на слайс W5 даёт честный `FAIL: review scope has no requirements: W5` (не форсировался).

| req | Статус | live_when | Основание / что осталось |
|---|---|---|---|
| SOUL-18.0 | READY_FOR_LIVE | postdeploy | движок/API/UI закрыты (33 passed слайса; периметр 3902/0, база 3869/0); живые числа 24–48ч — канарейка |
| SOUL-18.2 | READY_FOR_LIVE | postdeploy | оконные счётчики 24/48ч из durable-источников (репро ревьюера 600/1600, coverage=full), нули — нулями; живая конфа — postdeploy |
| SOUL-18.3 | READY_FOR_LIVE | postdeploy | D2 (свежее окно, маркер false→true) и D3 (причины 10/10) подтверждены, негативы сохранены; D1 — контрактная защита состояния окна, не причина тишины; живая конфа — postdeploy |
| SOUL-18.4 | READY_FOR_LIVE | postdeploy | мягкие цели с полами (600с/4/1800с), per-chat и visible, trace до mock send, ось OFF+confirm (`publish_axis_off`/`confirm_required`); реальная отправка — только решением владельца |
| SOUL-18.5 | VERIFIED | preprod | health≠outcome: вердикты, warning «возможности есть, сообщений нет», note «тики и прогоны ≠ отправка» + рендер панели (evidence type `ui`) |
| SOUL-18.6 | READY_FOR_LIVE | postdeploy | одна панель Статуса (якорь ровно 1; полигонных токенов нет), доставка ↔ манифест (`message_id` + Core/Style), node-сторожа 4/4; реальные доставки — postdeploy |
| SOUL-18.7 | READY_FOR_LIVE | postdeploy | план наблюдения 24–48ч конкретен; искусственных отправок в рабочую группу нет (§19 п.6) |
| SOUL-05.8 | VERIFIED | postdeploy | равенство ревизий Core/Style/identity Direct↔Initiative и SILENT без Writer (мутация M4 KILLED), пин хода = ревизия Core |
| SOUL-18.1 | VERIFIED | preprod | факт владельца = основание runtime-диагностики; «25 заданий/сутки» — прогоны очереди, не сообщения; overclaim снят (RECHECK §1) |

**Помета про SOUL-05.8 (уточнение к REVIEW-W5 §5):** строка **существует** в карте — `M00091` в `additional_requirements`, исходная строка 91 (§6: «Initiative полностью самостоятельна в выборе повода…»), acceptance выведен из текста клаузы. Дубль НЕ заводился (конфликт manual `source_id` + дубль `req_id`); строка привязана к кандидату и переведена в VERIFIED по фактам ревью. Замечание ревью «в карте строки нет» верно только для массива `items` — там её действительно нет, она в additional.

**Помета про SOUL-18.1 (собственная классификация Builder'а; нужно принятие или корректировка родителем/Reviewer'ом):** строки нет в таблице REVIEW-W5 §5 (ревьюер её отдельно не судил). Её acceptance — докладная (факт владельца как основание диагностики; 25 заданий/сутки ≠ сообщения), `live_required=false`; выполнена отчётом §2 и проверена RECHECK §1 (проверка всей атрибуции). Поэтому VERIFIED. Если Reviewer считает, что строку нужно вести по live-слоту — она переводится в `READY_FOR_LIVE`/postdeploy одной строкой без изменения кода.

**Помета про top-level candidate (single-candidate семантика):** указатель отдан W5-кандидату, поэтому повторный прогон гейта по **другим** слайсам на этом кандидате даст FAIL по evidence-binding (их evidence привязано к собственным SHA: W4 `c1cb6475`, W6 `a5902b15`, W1 `3cc0b9c0`, W3 `4c8405e7`, W10 `c8cf77a5`). Для контрольных повторов чужих слайсов указатель временно восстанавливается (прецедент §W1/W3/W10 → «Контроль после восстановления candidate»); механика не менялась.

**Гейты (review, verbatim; кандидат `bc277a3dc8bd54e721f5855fc6920f2ea401b25f`):**

main, `--slice W5`:
```
stage=review inventory=101 manual=97 scoped=9 errors=0
EXITCODE=0
```

amendment, `--slice W5` (**слайс W5 в amendment не представлен — честный FAIL, не форсировался**):
```
FAIL: review scope has no requirements: W5
stage=review inventory=66 manual=28 scoped=0 errors=1
EXITCODE=1
```

**Структурный контроль карт** (`--stage plan`, обе карты): `stage=plan inventory=101 manual=97 scoped=0 errors=0` / `stage=plan inventory=66 manual=28 scoped=0 errors=0`, EXITCODE=0 (и до, и после привязки).

**LF-санити коммита A (после `git commit`):** `git show bc277a3d:web/app.js` — CRLF=0 (22483 LF), `git show bc277a3d:web/index.html` — CRLF=0 (10935 LF), `web/app.py` — CRLF=0; новые исходники/тесты/инструменты W5 — LF-only; `services/mca_gates.py` — смешанный EOL сохранён как в HEAD (CRLF 582, LF 2483).

**Девиация A (честно):** в коммит A включён новый инструмент-стенд `tools/_soul1_w5_visual_server.py` (LF) — им лейн поднимал панель, стенд засветился в REVIEW-W5 §2; в 23-файловый отпечаток отчёта/ревью он не входил (там 9 новых файлов). Он принадлежит слайсу; других файлов вне W5-набора в коммите A нет.

**Открытые W5-строки и что осталось:** (1) канарейка postdeploy по 6 live-строкам (`18.0`, `18.2`, `18.3`, `18.4`, `18.6`, `18.7`): живые числа 24–48ч, реальные сценарии и реальная отправка по явному решению владельца — `evidence/w5/live-acceptance-plan.md`; (2) не-блокирующий бэклог REVIEW-W5 §4 и RECHECK «Хвосты» (подпись `w5CheckNote` при сорванной реальной отправке, неиспользуемый `initiative_check_no_publish`, склейка строки `loadIntelFunnels`, тест пола `min_gap` при целях >24/сутки, юнит-тест оси ON, косметический дубль в `live-acceptance-plan.md`) — в эту привязку не входит и статусы не меняет; (3) `SOUL-05.7` (SILENT/REACT и tool-result) остаётся PENDING в W3 — W5 покрывает SILENT/REACT-часть через `SOUL-05.8`, закрывающая строка этим коммитом не переносится.

**Следующее действие (для Orchestrator):** (а) независимое ревью привязки — статусы, evidence, честность классификаций `SOUL-18.1` и `SOUL-18.5`; (б) решение владельца по канарейке (push/deploy — вне этого лейна); (в) postdeploy: заполнение 6 live-строк + release-стадия гейта.

## AMD.2.6 binding (d4c33c2126af)

**Кандидат:** `d4c33c2126afa8e214063e4d8ef9bb2d997502e5` (= `434b7ac5` (verify-W5) + tail-слайс AMD.2.6, коммит A). Независимое ревью `plans/features/soul-1/review-amd26.md` — **Approved**: своя OFF/ON-проба на реальном компиляторе, независимо воспроизведённый RED, свои 8/8 мутаций KILLED, адверсариальный скан «пути снов», периметр 3908/0, реестр 575/64→64, тесты не ослаблены. Коммит A — **16 файлов** = 2 runtime (`lore_compiler_service.py`, `prompt_registry.py`) + 2 теста + 2 инструмента-свидетеля + 8 evidence + отчёт + ревью.

**Разведение кандидатов карт (сознательное, single-candidate семантика):** top-level `candidate_commit` в **amendment-карте** := `d4c33c21…` (эта привязка); **main-карта не менялась** — её кандидат остаётся `bc277a3dc8bd54e721f5855fc6920f2ea401b25f` (W5): у AMD.2.6 **нет main-строк** (клауза L00026 живёт только в amendment; сверено — в main `SOUL-AMD.2.6` отсутствует). `deployed_commit` пуст (пуша/деплоя нет). Отпечатки шести ключевых файлов сверены с коммитными блобами: `6255c2b97d69` / `4b0ef89007ef` / `b530706409dc` / `f6e3961c4372` / `c6248fd6a022` / `f009e96f4c47`.

**Строка amendment:** `SOUL-AMD.2.6` → **VERIFIED** (slice W4). Основание: лор/истории («Летописец», единственный реальный публикующий путь остатка клаузы) проведены через `authorial_system(writer="lore_writer", genre="lore")` — OFF = канон байт-в-байт, ON = жанровая рамка `genre.lore.rules` + Core + Style-hint, единственный писатель (`llm.calls==1`); «Ностальгия» — W4; сны/глубокий сон/«рассказы о них» — честная граница: публикующего пути в продукте нет, внутренние машинные стадии §2.2 не тронуты, рамка `genre.dream.rules` готова (контракт покрыт тестом). Историческая evidence-запись W4 (`c1cb6475`) сохранена; добавлены две записи, привязанные к `d4c33c21`.

**Гейты (review, verbatim; кандидат `d4c33c2126afa8e214063e4d8ef9bb2d997502e5`):**

amendment, `--stage review --slice W4`:
```
stage=review inventory=66 manual=28 scoped=1 errors=0
EXITCODE=0
```

**Структурный контроль карт** (`--stage plan`, обе карты): `stage=plan inventory=101 manual=97 scoped=0 errors=0` / `stage=plan inventory=66 manual=28 scoped=0 errors=0`, EXITCODE=0.

**W4-evidence:** перезаписанный прогоном слайса `plans/features/soul-1/evidence/w4/frozen-assets.txt` восстановлен из HEAD (дифф пуст); содержимое сохранено как `plans/features/soul-1/evidence/amd26/frozen-assets.txt` (артефакт того же прогона; сверено после нормализации BOM/CRLF). Четыре evidence-`*.txt` слайса — CRLF (захват PowerShell-редиректом); байты сохранены как есть, чтобы не рвать привязанные ревью отпечатки, на будущее — LF.

**Что осталось:** (1) ось `UNIFIED_COMPOSER_ENABLED` остаётся OFF — включение ON/OFF решение владельца (OFF-паритет подтверждён; у строки `live_required=false`, `live_when=preprod`); (2) чужие карты/слайсы этим коммитом не привязывались.

## W7 binding (6094a2cfa166)

**Кандидат:** `6094a2cfa1660d1b949dcfe5ec085bc08f080de4` (коммит A поверх `9d8da1d7` (docs-only) = объединённый слой W7 (реконсиляция наследия v6.3: SOUL-12 fullscreen, SOUL-13 хвосты) + FS-HOTFIX/FS2 (директива владельца 18.10 + FOLLOW-UP `current-task.md` L903–1229)). Ревью-цепочка: **REVIEW-W7 Needs Fixes** (единственный блокер F1: launchParams не читались из hash) → F1 починен в этом дереве → **REVIEW-FS Needs Fixes** (не хватало FOLLOW-UP-дельты) → **FS2-дельта** (логотип скрыт, матрица №8/№12, admin-диагностика §8) → **RECHECK: Approved** (tech; свои прогоны ревьюера: 12/12·166, 5/5·88, node 86/86, периметр 3915/0, frozen OK, 10/10 отпечатков). Коммит A — **95 файлов, +7530/−489**: web 4, tests 5 (1 новый), tools 3 (1 новый), services 1, docs 5 (вкл. `fullscreen-archaeology.md`), evidence 77 (`evidence/w7/**` 34 + `evidence/fs-hotfix/**` 43, вкл. browseruse PNG). В обеих картах top-level `candidate_commit` := W7-кандидат (single-candidate семантика; прежние указатели — W5 `bc277a3d` / AMD.2.6 `d4c33c21`); `deployed_commit` пуст (пуша и деплоя нет).

**Строк W7:** main **13** (7 inventory: `SOUL-12.0`, `SOUL-13.0`, `SOUL-13.2`–`SOUL-13.6`; 6 additional: `SOUL-12.1`–`SOUL-12.5`, `SOUL-13.1`); **amendment — 0**: слайс W7 в amendment не представлен, гейт amendment на слайс W7 даёт честный `FAIL: review scope has no requirements: W7` (не форсировался).

| req | Статус | live_when | Основание / что осталось |
|---|---|---|---|
| SOUL-12.0 | READY_FOR_LIVE | postdeploy | строка закрытым не объявляется: живое подтверждение (Windows/Android) — postdeploy; чек-лист владельца отменён 18.10, живые наблюдения — агенты после выката (`PENDING_OWNER_E2E` информационный) |
| SOUL-12.1 | READY_FOR_LIVE | postdeploy | кодовый факт устранён (tdesktop — обычный клиент, заглушки удалены директивой); живая половина — Launch Mode на клиенте владельца (postdeploy) |
| SOUL-12.2 | READY_FOR_LIVE | postdeploy | три операции разделены (негативы 5.3b/5.3c, запрет moveTo/resizeTo/expand-фолбэка); визуальная сущность fullscreen — postdeploy |
| SOUL-12.3 | READY_FOR_LIVE | postdeploy | диагностика собирает факты воспроизведения (F1 починен: sessionStorage+hash, allowlist); живая матрица клиентов — postdeploy |
| SOUL-12.4 | READY_FOR_LIVE | postdeploy | политика соблюдена на mock-канале (реальная кнопка там, где есть API; без ложного успеха); «визуально подтверждённый fullscreen» — postdeploy |
| SOUL-12.5 | READY_FOR_LIVE | postdeploy | моки — только регресс; safe area/без перекрытий; полигон не тронут (`frozen-check` OK); живое подтверждение — postdeploy |
| SOUL-13.0 | VERIFIED | preprod | baseline v6.3 зафиксирован (`v63-baseline-record.json`); ни одна строка не «closed» |
| SOUL-13.1 | VERIFIED | preprod | видимый реестр 65 строк (42/18/5) 1:1 сверен ревьюером, без «закрытий» |
| SOUL-13.2 | READY_FOR_LIVE | postdeploy | локально 7 путей стенда → 401/403/404, боевые 200, test-среда рендерится; прод-проба 404 — на предыдущем кандидате, повтор на задеплоенном — postdeploy |
| SOUL-13.3 | VERIFIED | postdeploy | реестр без переименований; «14» = историческое состояние, обязательства не спрятаны |
| SOUL-13.4 | VERIFIED | preprod | код различает absent/hot/env + WARN без секретов; UI-состояние подтверждено реальным рендером (мок-канал); провайдерский reset horizon честно OPEN |
| SOUL-13.5 | VERIFIED | preprod | реальные расположения артефактов и deployed SHA (без выдуманных путей); `225c3c2b` — ancestor `origin/master` |
| SOUL-13.6 | VERIFIED | preprod | 6/6 PASS на `.venv`; падения под `py -3` воспроизведены как интерпретаторные; runtime-бага нет |

**Гейты (verbatim; кандидат `6094a2cfa1660d1b949dcfe5ec085bc08f080de4`):**

main, `--stage review --slice W7`:
```
stage=review inventory=101 manual=97 scoped=13 errors=0
EXITCODE=0
```

amendment, `--stage review --slice W7` (**слайс W7 в amendment не представлен — честный FAIL, не форсировался**):
```
FAIL: review scope has no requirements: W7
stage=review inventory=66 manual=28 scoped=0 errors=1
EXITCODE=1
```

**Структурный контроль карт** (`--stage plan`, обе карты): `stage=plan inventory=101 manual=97 scoped=0 errors=0` / `stage=plan inventory=66 manual=28 scoped=0 errors=0`, EXITCODE=0 (после привязки).

**LF/CRLF-санити коммита A (после `git commit`, сверка блобов с родителем):** `web/index.html`, `web/app.js`, `web/static/fullscreen-policy.js`, тесты, инструменты, `services/embedding_control_plane.py` — CRLF=0 (не добавлено); `web/static/app.css` — CRLF=6, ровно как в родителе (унаследовано, новых нет); карты при привязке перезаписаны с сохранением их CRLF-конвенции (дифф — только W7-строки и указатель).

**Пометы:**
1. **U07.1a — исключена ранее (не этим коммитом):** в соседней карте v6.3-коррекции (`plans/features/asap8-v6-3-live-correction/requirements-map.json`, `items/L00200`) строка `U07.1a` переведена в `user_excluded` («SUPERSEDED директивой владельца 18.10»); эта привязка её не трогает, директива подтверждена кодовой частью FS-хотфикса (заглушка → рабочая кнопка).
2. **FOLLOW-UP-критерии (логотип / §7 №8–№12 / §8-диагностика) живут в карте v6.3-коррекции** — это соседняя карта; её файлы в коммит A сознательно не включены (чужие незакоммиченные правки, включая PNG `w2-evidence*`). Ре-анкор — после выката.
3. **Замечания review-w7:** N1 (stale-артефакт `pytest-embedding-suites.txt` «1 failed, 96 passed») — **исправлено в A**: артефакт перегенерирован (`97 passed`); N2 (тест-гэп: приоритет hot-над-env не защищён assert'ом) — **открытая не-блокирующая заметка** (код ведёт себя верно, дефекта нет); N3 (binding) — этот коммит; N4 (аддитивное расширение области `index.html`/`app.js`) — задекларировано в отчёте §4.1, регрессий нет; N5–N8 — pre-existing/шум.
4. **Девиация коммита A (честно):** добавлены новые доказательства SOUL-13.4-UI (`evidence/w7/embed_primary_ui_render.json` + 2 PNG + `_probe_embed_primary_ui.py`; browser-use, реальный Chrome, мок SDK/API стенда — доказывают UI-wiring, не состояние прода) и ранее untracked `fullscreen-archaeology.md` (read-only разведка FS-лейна).
5. **Живые границы (не закрыты):** реальные Windows/Android после выката (SOUL-12.x), прод-404 стенда на новом кандидате (SOUL-13.2), reset horizon провайдера эмбеддингов (SOUL-13.4, внешний факт); `SOUL-12.0` закрытым не объявляется.

**Следующее действие (для Orchestrator):** (а) независимое ревью привязки (статусы/evidence/честность классификаций); (б) push+изолированный релиз и деплой — отдельный лейн; (в) postdeploy — живые наблюдения по SOUL-12.x/13.2 и release-стадия гейта.
