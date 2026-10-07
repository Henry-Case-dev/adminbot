# `asap5-final-fixes` — requirements-map.md (Step 1 @PM 07.10.2026)

Feature: `asap5-final-fixes` (ASAP 5). Источник требований: `plans/current_task.md:27151–29600` — раздел **«ASAP 5 — Summary Reliability + Cover Prompt Transparency + GraphRAG Recovery»** (прочитан полностью 07.10.2026, включая owner report §19 `:29578–29600` и 15E surfaces `:28927–29548`). Директива владельца 07.10.2026: строго после всех MCA (закрыты, прод **2.58.67**, feat `6f062fa`/docs `fbdc95c`/PM-close `e9d71c8`); read-only planning заранее; реализация — ≤3 Builder-lane при непересекающихся скоупах; **сначала root causes на текущем коде и production evidence**, НЕ переписывать Summary/Cover/GraphRAG целиком; без human gate. Tasks: `tasks.md` (этой папки), T-5238…T-5275.

---

## 1. Реестр требований ASAP5-R1…R30

Локальная нумерация ASAP5-R*; **не путать с глобальным инвариантом GEN-R17 (секреты)** — он сквозной для всех задач и отдельно перечислен в §4/§6.

| REQ | Суть | Якорь (current_task.md) | Задачи | Приёмка |
|---|---|---|---|---|
| **ASAP5-R1** | Hybrid Decision Trace в Run Inspector: L1 / L2 Writer / Reviewer-итерации / Revision-итерации / Final policy (`HYBRID_PUBLISHED\|HYBRID_DEGRADED_PUBLISHED\|LEGACY_FALLBACK`) + одна точная причина; failed run диагностируется без server log | §3 `:27415–27486`; symptoms `:27175–27180` | T-5244, T-5266 | §17 `:29491–29496`; §15E#1 |
| **ASAP5-R2** | L1-семантика OK / DEGRADED_MAP_FALLBACK / FAILED_TERMINAL; degraded map ≠ terminal, Writer продолжается от Full SourceWindow | §1.1 `:27243–27268` | T-5241 (ревизия), T-5245 | §16#1–2 `:29447–29448` |
| **ASAP5-R3** | Server-owned severity: policy/taxonomy (code → hard\|soft, promote/demote, can_force_legacy); `unusable` terminal только при server-условиях; unknown severity ≠ blocking | §4.2 `:27507–27520`, §4.3 `:27522–27533`, §1.2A/B `:27292–27306` | T-5241, T-5246 | §16#3–6 `:29449–29452` |
| **ASAP5-R4** | Stagnation по fingerprint hard-findings (code+paragraph+evidence/target), не по count; retry budget — без роста LLM-циклов | §4.4 `:27535–27544`, §4.5 `:27546–27554`, §1.2C `:27308–27329` | T-5247 | §16#7–9 `:29453–29455` |
| **ASAP5-R5** | Legacy — аварийный контур (4 случая §4.1), не обычный исход Reviewer; soft-only → `hybrid_degraded`, не Legacy; hard integrity fail-closed; reviewer-outage fail-soft сохранить | §4.1 `:27490–27505`, §1.2D `:27331–27357` | T-5246, T-5247 | §17 `:29494–29495` |
| **ASAP5-R6** | Summary live acceptance: 5 controlled real-provider прогонов (3+2) с Decision Trace + затем 1 live `/summary` | §5 `:27557–27585` | T-5248; live — T-5274 | §17 `:29498–29499` |
| **ASAP5-R7** | Cover dataflow честность: подтвердить/устранить — story seed ≤300 chars как единственный смысл; Style Edit от `cover_prompt`, а не финального Summary; `minimal=True` retry теряет refs/brief | §6 `:27588–27621` | T-5242 (ревизия), T-5250–T-5251 | §16#12–16 `:29461–29465` |
| **ASAP5-R8** | `CoverPromptManifest` — единый источник истины: 6 компонент (BASE_STYLE/STORY_SCENE/SUMMARY_CONTEXT/STYLE_PROFILE/RUNTIME_INVARIANTS/REFERENCES) с source/priority/original/sent/status/reason + provider/model/route/limit/hash; один manifest для всех трёх UI; полный prompt — не в generic logs | §7 `:27623–27670`, §10A.1 `:29422–29429` | T-5249 | §17 `:29507` |
| **ASAP5-R9** | Base Cover contract: STORY_SCENE + SUMMARY_CONTEXT (bounded representation финального Summary) + BASE_STYLE; minimum budget для STORY; без лишнего LLM-call | §8 `:27672–27693` | T-5250 | §12 Base `:27820–27824` |
| **ASAP5-R10** | Style Edit contract: edit-not-recompose; mandatory minimums при любом retry; bounded semantic squeeze вместо `P0+style`; required role-ref не выбрасывается; retry ≤1; сокращения — в Manifest | §9 `:27695–27742` | T-5251 | §12 Styled `:27826–27832` |
| **ASAP5-R11** | Settings UI «Что реально уйдёт модели»: Prompt Assembly-таблица + FINAL PROMPT + limit source; draft-честность (placeholder ≠ production); Constructor на «Саммаризация → Стили обложки», Style Editor — компактный переход (§10A) | §10 `:27744–27775`, §10A `:29338–29440` | T-5252 | §10A.2 `:29431–29440`; §15E#2/#3 |
| **ASAP5-R12** | Analytics: фактический prompt каждого run (Base и Style отдельно, attempts 1/2, chars/limit/model, hash); admin-only, retention bounded, chat data учтён | §11 `:27777–27812` | T-5253 | §16#17–20 `:29466–29469`; §15E#4 |
| **ASAP5-R13** | Cover live acceptance: Base — manifest и визуальное соответствие сюжету; Styled — профиль/номер/logo/refs/сохранённый сюжет/no-duplicate; retry не теряет story | §12 `:27814–27833` | T-5254; live — T-5274 | §17 `:29501–29508` |
| **ASAP5-R14** | GraphRAG `building` same fingerprint: диагностика durable rebuild job (13 полей §13); healthy rebuild ≠ авария (прогресс N/M, warning не повторяется); stale building → bounded recovery без duplicate jobs, visible blocker; после success — active; warning не глушить | §13 `:27836–27895` | T-5243 (ревизия), T-5255 | §16#21–25 `:29472–29477`; §17 `:29519–29521` |
| **ASAP5-R15** | Embeddings: Primary/Fallback1/Fallback2 — три независимых connection profile (provider/base_url/model/key/quota_group/params); Fallback2 не наследует от Fallback1 без явного режима; миграция без потери credentials | 13C.1 `:27899–27955` | T-5256 | 13N#1–2 `:28589–28590`; §17 `:29510` |
| **ASAP5-R16** | Embedding identity/fingerprint (не только dimension) + canary для floating alias + классы INSTANT_COMPATIBLE/REINDEX_REQUIRED/INCOMPATIBLE_DIMENSION/COMPATIBILITY_UNKNOWN (fail-safe), одна server-side классификация | 13C.2–13C.4 `:27957–28054` | T-5257 | 13N#3–6 `:28591–28594` |
| **ASAP5-R17лок** | Vector generations: chat_id → одна ACTIVE generation; immutable metadata; смена key/quota → без reindex; смена model → новая generation (не in-place); state machine миграции (BUILDING→CATCHING_UP→READY→atomic PROMOTE; FAILED/SUPERSEDED/CANCELLED/BLOCKED); snapshot+delta; atomic promotion + rollback; generation-isolated storage | 13D `:28057–28150`, 13E `:28154–28262`, 13H `:28374–28395` | T-5258 | 13N#7–16, #25–28 `:28595–28616` |
| **ASAP5-R18** | Global default vs per-chat override: safe default — pinned до миграции; impact до сохранения; per-chat — отдельное permission, moderator без global mutation; повторные изменения → SUPERSEDED/stale-promote защита; A→B→A; alias drift → stop silent writes | 13F `:28265–28314`, 13G `:28317–28371` | T-5259 | 13N#7–9, #15–17, #24 `:28595–28604`, `:28612` |
| **ASAP5-R19** | Multi-chat retrieval по active identity; запрет cross-space сравнения одним query-embedding; same-space fallback request-level, different-space — нет; observability per chat/migration без вечного `building` | 13I `:28398–28421`, 13L `:28526–28552`, 13M `:28555–28584` | T-5259 | 13N#19–22 `:28607–28610` |
| **ASAP5-R20** | MiniApp embeddings UX: identity/dimension/compatibility-индикаторы (✅/🟡/🔴/⚪); impact-диалог до apply; кнопки по смыслу; quota groups человеческим языком, raw syntax — Advanced; unknown ≠ rotation | 13J `:28425–28477`, 13K `:28480–28523` | T-5260 | 13N#23 `:28611`; §15E#9–13 |
| **ASAP5-R21** | Embeddings edge-tests 13N (28 кейсов) + Definition of Done 13O (17 чекбоксов) | 13N `:28587–28617`, 13O `:28620–28640` | T-5269 | 13O `:28622–28640` |
| **ASAP5-R22** | Random: config-state ≠ runtime failure; selected/effective/блокер/действие; explicit pseudorandom без WARN; notable transition ×1; без fake provider/key | §14 `:28643–28684`; symptoms `:27220–27235` | T-5261 | §16#34–36 `:29482–29484` |
| **ASAP5-R23** | ANU bootstrap-фикс: незаданный secret присутствует в config metadata как `configured=false` (без plaintext, без фиктивного секрета в БД); карточка «Случайность: подключение ANU» видна до настройки; entry point из «Сон → Случайность» | 14A.0 `:29179–29237`, 14A.1 `:29238–29288` | T-5262 | 14A.4 `:29320–29333`; §15E#7/#8 |
| **ASAP5-R24** | Owner-supplied ANU key применить сразу (не PENDING OWNER): protected secret path, без hardcode, `configured/last4` клиенту, `/api/random/test`, `provider_unconfigured` исчезает; значение — никуда не копировать; ротацию не рекомендовать; ключ повторно не запрашивать | 14A.2 `:29290–29318` | T-5263 (Scanner — T-5272) | 14A.4 `:29330–29333`; §17 `:29518` |
| **ASAP5-R25** | Парадигмы: last-attempt reason отдельно от cooldown (поля §13A.1); controlled manual deep run; retry-политика по классам причин (bounded, не busy-loop) | §13A `:28986–29085` | T-5264 | 13A.4 `:29073–29084`; §15E#6 |
| **ASAP5-R26** | Граф знаний: semantic zoom (far/medium/close), selected neighborhood, long labels; все nodes/edges сохраняются; canonical `node.label` не менять; не резать данные | §13B `:29088–29154` | T-5265 | 13B.4 `:29145–29153`; §15E#5 |
| **ASAP5-R27** | Visual QA regime: каждое UI-изменение — Playwright + Browser Use; neighborhood sweep (§15B, граница §15B.1, дефекты = findings §15B.2); fix → re-review цикл (§15C); evidence §15D; 13 surfaces §15E; Visual DoD §15F; недоступность инструмента ≠ PASS | §15A `:28686–28806`, §15B `:28808–28880`, §15C `:28882–28897`, §15D `:28900–28924`, §15E `:28927–28948`, §15F `:28951–28965` | все UI-задачи + T-5266 | §15F `:28953–28964` |
| **ASAP5-R28** | Focused tests §16 (Summary #1–11, Cover #12–20, GraphRAG #21–25, Random #34–36 + 13N×28) + DoD §17 + Дополнение DoD + запрет §18 | §16 `:29443–29486`, §17 `:29488–29540`, §18 `:29543–29574` | T-5267–T-5270, T-5271 | §17 `:29490–29525`, `:29532–29540` |
| **ASAP5-R29** | Final owner report §19: 17 пунктов human language first; финал — observable production behavior, не «tests green» | §19 `:29578–29600` | T-5275 | `:29600` |
| **ASAP5-R30** | Процесс: root-causes-first (§1 ревизия на HEAD до изменений); ≤3 writer-лейны, shared-файлы сериализовать; doc discipline (bounded артефакты, workflow_state ≤ ~40 строк, evidence bounded); read-only PREP параллельно | `:27153–27164`, §2 `:27361–27412`, `:28969–28980` | T-5241–T-5243 (до кода), T-5238–T-5240 | `:27163`, `:27241` |

## 2. Live symptoms → REQ (§0 `:27167–27237`)

- **Summary** `:27169–27187` (Hybrid нестабилен; L1/L2 падения → Legacy; Run Inspector не показывает причины; live run: coverage 874/874, L1 failed, «Writer не выполнено» → Legacy при успешном cover `medved_press`) → R1–R6.
- **Cover** `:27189–27204` (Style Edit работает, но базовый сюжет слабый; до image-provider должны доходить 7 компонент `:27195–27202`; владелец видит В ТОЧНОСТИ отправленное) → R7–R13.
- **GraphRAG** `:27206–27218` (`embedding generation not serviceable | index=graph_facts_vec | status=building | gen_fp=new_fp — FTS-only (A06)`; определить rebuild vs застревание; не лечить скрытием warning) → R14–R21.
- **Random** `:27220–27235` (`random_fallback blocker=provider_unconfigured`; effective config; configuration/degraded state, не загадочная ошибка; pseudorandom допустим; один notable transition, спам — нет) → R22–R24.

## 3. Preliminary code audit §1 → ревизионные задачи

Раздел требует: «Builder/Architect должны подтвердить их на фактическом HEAD перед изменением» (`:27241`). Ревизия — T-5241/T-5242/T-5243, ДО design-freeze и ДО кода:

- §1.1 `:27243–27268` (L1 не обязан валить Summary; семантика OK/DEGRADED_MAP_FALLBACK/FAILED_TERMINAL) → T-5241.
- §1.2A `:27292–27298` (unusable слишком доверяет модели) / B `:27300–27306` (unknown severity → blocking) / C `:27308–27329` (count-based progress) / D `:27331–27357` (hard vs soft) → T-5241.
- §6.1 `:27594–27621` (story seed / Style Edit без Summary / minimal retry) → T-5242 (HEAD-якоря: `web/api/summary_test.py:349–370` — `compose_cover_image_prompt(style, cover_prompt)`; `services/cover_style_jobs.py:1086/:1206`).
- §13 `:27836+` (building: healthy vs stale), §14 `:28643+` (Random config-state), 14A.0 `:29179+` (bootstrap paradox `/api/config`), §13A.2 `:29038–29052` (цепочка пустого пула парадигм) → T-5243.

Подтверждение предварительного аудита на HEAD (grep 07.10.2026, детали — в RCA-артефактах): оба embedding-fallback делят `models.embedding_fallback_base_url`/`model` (`services/llm_client.py:364–376`, `embedding_control_plane.py:282–284`, `status_service.py:277–301`) — тезис 13C.1 подтверждён; `provider_unconfigured`/`random_fallback` уже в словаре reason-кодов (`mca_events.py:67`) — Δ reason ожидаемо 0 (подтвердить Step 2); registry поколений существует (`database.py:5385–5597`: `activate/get_active/get_latest/ensure_embedding_generation`) — 13D строится поверх существующего механизма (AMEND).

## 4. Conflict-audit — границы AMEND (не rewrite)

| Область | Файлы (HEAD) | Режим | Граница |
|---|---|---|---|
| Summary pipeline | `services/summary_generator.py`, `summary_l2_review.py`, `summary_prompts.py`, `summary_l2_writer.py`, `summary_l1_semantic_map.py`, `summary_run_store.py`, `summary_run_log.py` | **AMEND (B1)** | Policy/taxonomy/fingerprint/трасса — точечные правки; полный rewrite pipeline запрещён до понимания failure trace (§18 `:29552`); «just disable Reviewer» / «just increase retries» / «все findings soft» — запрещены (`:29553–29555`) |
| Run Inspector UI | `web/app.js` (секция summary run view), API рунов | **AMEND (B1)** | Добавить Decision Trace-карточку, не ломая существующие поля; секция app.js за B1 |
| Cover pipeline | `services/cover_style_jobs.py` (`run_style_job:1206`, CoverBrief `:1086`), `web/api/cover_styles.py`, `web/api/summary_test.py`, image provider route | **AMEND (B2)** | Manifest-слой поверх существующей сборки; компиляцию не дублировать (§10A.1); запрет hardcoded universal prompt limit / скрытой обрезки (`:29557–29558`) |
| Cover UI | `web/app.js`/`web/index.html` (Стили обложки, Style Editor, Analytics-виджеты) | **AMEND (B2)** | Секция app.js за B2; все изменения под Visual QA §15A–15F |
| GraphRAG/rebuild | `services/database.py` (registry `:5385–5597`), `dossier_rebuild_jobs.py` (`:1442–1448`), `embedding_control_plane.py` | **AMEND (B3)** | Диагностика/recovery поверх существующего registry; отключение GraphRAG ради чистых логов запрещено (`:29561–29562`); vec-таблицы не модифицировать деструктивно (13H) |
| Embeddings config | `services/llm_client.py`, `status_service.py`, `llm_probe.py`, `embedding_control_plane.py`, `config/settings.py`, `param_catalog.py` | **AMEND (B3)** | Независимые профили; миграция credential-ключей без потерь (13C.1 `:27953–27955`); «no shared hidden fallback model key behind two supposedly independent profiles» (`:29566`) |
| Random | `services/mca_random_source.py` (`:120`), `mca_events.py` (`:67`), `web/api/routes.py:1998–2012`, `param_catalog` (группа `keys_random`), `mca_intents.py`, `mca_exploration.py`, `mca_process_registry.py` | **AMEND (B3)** | UX/состояния/transition-коалесинг; fake provider/key запрещён (`:29563`); второй storage для ключа не создавать (14A.1 `:29286–29288`) |
| Парадигмы | `web/api/memory_agi.py` (`deep_sleep_status:558`), deep-sleep worker | **AMEND (B3)** | Разнос полей диагностики; scheduler-контракт не ломать; защиту от бесконечных LLM-вызовов сохранить (13A.3 `:29058`) |
| Граф | `web/app.js` (vis-network), graph API | **AMEND (B3, presentation-only)** | Backend `node.label` не менять (13B.1 `:29117–29119`); узлы/рёбра не удалять (`:29549`) |
| Shared UI-файлы | `web/app.js`, `web/index.html` | **SERIALIZE** | Правило `:27411` «Shared files/config/DB schema changes сериализовать через parent Builder»: секционная принадлежность (B1: inspector; B2: cover; B3: embeddings/random/paradigms/graph), последовательные коммиты, порядок — санкция T-5239 |
| Чужие артефакты | `plans/current_task.md` (READ-ONLY `:27157`/`:28971`), arch-frames.md (Step 2), ARCHITECTURE/metrics/backlog/workflow_state (PM-close T-5275), MEMORY.md (параллельный memory-лейн), чужие фичи-папки, git-индекс | **DO_NOT_TOUCH** | — |

## 5. Открытые вопросы Step 2 (Q1–Q13; ответы — spec §10 / ADR-1028-25)

- **Q1 `unusable`-threshold** — точные server-side условия (§4.3 `:27531` «Точный threshold — решение Architect по реальным failed runs»); вход — вердикты T-5241.
- **Q2 hard/soft-таксономия** — полный список finding codes + условия promote/demote + `can_force_legacy` (§4.2); граница «доказанный factual corruption» (§4.1).
- **Q3 fingerprint-формат** — нормализация `code+paragraph+evidence refs/target`; правило «старый исправлен + новый найден» (§4.4).
- **Q4 CoverPromptManifest** — имя/схема, persistence (job evidence/таблица), retention «bounded вместе с run/job evidence» (§11 `:27809`), prompt_hash.
- **Q5 semantic squeeze** — minimums story/profile/refs, resolved_limit unit/source, «один retry максимум» (§9 `:27739–27741`); источник лимита при unknown provider limit.
- **Q6 embedding identity** — состав fingerprint, устойчивый canary-механизм при numerical drift (13C.3 `:28018–28019`), политика COMPATIBILITY_UNKNOWN.
- **Q7 storage-стратегия** — generation-isolated storage при фиксированной размерности vec0-таблиц (13H `:28385`); следствия для DDL.
- **Q8 Δ-инварианты** — ожидаемые дельты: DDL (v33→v34 при новых таблицах миграций/профилей?), каталог (523→X — новые embedding keys 13C.1), reason (280→0/+N; `provider_unconfigured`/`random_fallback` уже есть — `mca_events.py:67`), KS (85→X), routes-пин (admin-API полных промптов §11); пороги эскалации → СТОП.
- **Q9 сериализация shared-файлов** — parent Builder для `web/app.js`/`web/index.html`, порядок коммитов секций B1/B2/B3 (правило `:27411`).
- **Q10 Risk + деплой** — ратификация (PM-предложение R2: multi-domain corrective, schema/config-дельты вероятны); правило код-дельты/bump; миграционный smoke при Δ DDL ≠ 0.
- **Q11 парадигмы retry** — классы причин и bounded backoff (13A.3 `:29060–29068`); контракт manual deep run.
- **Q12 состав тестов** — гэп нумерации §16 (после #21–25 сразу #34–36): подтвердить, что недостающие #26–33 покрываются 13N/13O, финальный тест-реестр.
- **Q13 лейн-границы** — принадлежность §13A/§13B лейне B3 (PM-предложение, tasks.md) — подтвердить/скорректировать; финальные write-scope трёх лейн.

## 6. Сквозные инварианты

- **R17 (глобальный GEN-R17):** секреты/живые чаты/персональные данные — не упоминать и не переносить. Особо: owner-supplied ANU credential (14A.2) — только из user-owned источника, не в spec/пакет/evidence/тесты/логи/env; plaintext никогда клиенту/в логи; владельцу ключ повторно не запрашивать, ротацию не рекомендовать (`:29313–29314`, `:29564–29565`). Full prompts — admin-only, не в generic logs, retention bounded, Summary context может содержать chat data (§11).
- **No-false-acceptance:** live-проверки (§5/§12/§17) не имитировать; visual QA — недоступность Playwright/Browser Use ≠ PASS (§15A `:28712–28716`).
- **Forbidden shortcuts §18** `:29543–29574` — поимённый чек-лист Reviewer (T-5271).
- **fail2ban (AGENTS.md):** прод-коннекты — один recon ~15 с + один прогон, пауза ≥ 22 мин при закрытом SSH, статус по HTTP `/healthz` (443), без поллеров/переборов; креденшелы — в `deploy_commands.txt`, не печатать.
- **Document discipline** `:28969–28980`: артефакты bounded, без append-only дневника; workflow_state snapshot ≤ ~40 строк; evidence: один полезный pre-fix repro + current PASS + verdict.
