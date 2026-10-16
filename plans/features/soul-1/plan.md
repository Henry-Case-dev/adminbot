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
