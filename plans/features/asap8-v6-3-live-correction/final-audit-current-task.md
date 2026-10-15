# FINAL-AUDIT — независимый аудит исходного `plans/current_task.md` (MCA-01…21, ASAP 1–8, v6)

LANE_ID: FINAL-AUDIT (перезапуск после сбоя квоты). Дата: 2026-10-16.
HEAD аудита: `c2775a54` (2.58.79). Источник: `plans/current_task.md` — SHA256
`91f754e3993477e888e874cd88dcfaf3234d54a92e3409f4d6744150a4ca5c05`, 1 577 802 B,
37 873 строки (37 872 LF + хвост) — **байт-в-байт равен замороженному снапшоту**
`plans/features/asap8-v6-3-live-correction/current_task.snapshot_2026-10-15.md`
(манифест `SNAPSHOT_MANIFEST.md`). Дрейфа исходника с момента freeze нет.

Read-only по репо. Прод-факты НЕ проверялись: деплой v6.3 идёт параллельно другим
лейном; раздел live во всех строках отчёта = «в процессе Wave 4 / см. live-canary.md».

---

## 1. Карта разделов с вердиктами

Порядок строк в файле **не хронологический** (документ user-owned, дописывался
владельцем в разных фазах) — хронология эпох зафиксирована в §6 «Ограничения».

| Строки | Раздел / программа | Что требует текст | Доказательство на HEAD | Backlog-хвосты | Вердикт |
|---|---|---|---|---|---|
| 1–1061 | §1–21 — миссия, архитектура, **MCA-01…21** (26 фич в 6 волнах) | вся программа «Память, контекст, автономия» | архивы 20 фич в `plans/archive/*-roundNNNN/` + `mca-release-round1048` (RELEASED+VERIFIED 2.58.67) | да (owner-гейты, watch-items) | **HISTORICAL-CLOSED** |
| 1062–1093 | §22–23 — ориентиры в коде, исследовательская основа | контекст/границы утверждений | — | — | HISTORICAL-CLOSED (context) |
| 1094–1172 | **MCA-15** — достоверная статистика | MetricResult, разделение поиск/замер | `mca-15-chat-statistics-round1036` 2.58.56 VERIFIED | T-4940 owner-live; F-1/F-2 | HISTORICAL-WITH-OPEN-TAILS |
| 1173–1282 | **MCA-16** — обучение на опыте без правки весов | детектор→урок→применение | `mca-16-experience-lessons-round1039` 2.58.59 VERIFIED; `services/mca_experience.py` | T-5015 owner-live; handoff'ы | HISTORICAL-WITH-OPEN-TAILS |
| 1283–1322 | §26 — воспроизводимый probe статистики | probe без выдумывания | поглощён mca-15 | — | HISTORICAL-CLOSED |
| 1323–1485 | **MCA-17** — прозрачность памяти/контекста/самообучения | покрытие инструментированием процесса | `mca-17a-observability-core-round1027`, `mca-17c-analytics-matrix-round1047` 2.58.66 | T-5199 owner-live; L-A/L-B Scanner | HISTORICAL-WITH-OPEN-TAILS |
| 1486–1607 | **MCA-18** — личность, модель себя | traits→поведение | `mca-18-self-model-round1042` 2.58.62; `services/mca_self_model.py` | T-5095 owner-live; S-2/S-3 | HISTORICAL-WITH-OPEN-TAILS |
| 1608–1746 | **MCA-19** — понимание изображений | vision в исходном сообщении | `archive/features/mca-19-image-understanding`; `services/mca_vision.py` | T-5127 owner-live (RED-20: провайдер не настроен) | HISTORICAL-WITH-OPEN-TAILS |
| 1747–1813 | **MCA-20** — фактчек с датой оригинала | repost/original, as-of | `archive/features/mca-20-temporal-factcheck` | T-5151 owner-live; L-A/L-B | HISTORICAL-WITH-OPEN-TAILS |
| 1814–1868 | **MCA-21** — итоговая актуализация справки | help = shipped runtime | `archive/features/mca-21-guides` + D14 help-sync; `tests/test_asap8_v6_d14_help_sync.py` | T-5217 owner-live | HISTORICAL-WITH-OPEN-TAILS |
| 1869–1883 | **ASAP 1** — «не работает саммари» | инцидент-симптом | поглощён ASAP-2 (hotfix 2.58.32) | — | HISTORICAL-CLOSED |
| 1884–2771 | **ASAP 2 / P0** — Summary pipeline, Legacy/Hybrid | двухконтурный Summary | `mca-asap2-summary-pipeline-round1027` 2.58.33; `services/summary_memory.py` (47 комм.) | `param-catalog-pg-only-seed-config-exposure` (🟦 К ПЛАНИРОВАНИЮ) | HISTORICAL-WITH-OPEN-TAILS |
| 2772–4061 | **ASAP-2.1 / P0** — Summary до production-состояния | удалить prefilter, Prompt Library, tests §27–46 | `mca-asap21-summary-quality-ui-cleanup-round1028` 2.58.34 | 3 doc-долга (не блокёры) | HISTORICAL-WITH-OPEN-TAILS |
| 4062–6066 | **ASAP-3 / P0** — Direct Context Reliability | -1=Unlimited, P0–P3, verbatim episode | `mca-asap3-direct-context-reply-reliability-round1028` 2.58.35; `services/direct_context_composer.py` | env `CHAT_MODEL_CONTEXT_WINDOW`; F8-hash/eol-рецепт | HISTORICAL-WITH-OPEN-TAILS |
| 6067–12024 | **ASAP-3.1** — Auto Budgets, Capacity, LLM REACT | model-aware бюджет, REACT | `mca-asap31-auto-budgets-capacity-react-round1028` 2.58.37/38; `services/model_capacity.py`, `services/auto_budget.py`, `services/direct_llm_react.py` | L-ASAP31-1…6 + `FACT_PACKAGE_TRUNCATED` (владелец) + watch cron | HISTORICAL-WITH-OPEN-TAILS |
| 12025–15304 | **ASAP-3.2** — Runtime Reliability, Provider Discovery, GraphRAG | D1–D14 | `asap-32-runtime-reliability-round1029` 2.58.40 VERIFIED | GraphRAG resume (failed 2500/15013), smart_archive KNN-smoke, owner live T-4234/T-4227, L/N-долги | HISTORICAL-WITH-OPEN-TAILS |
| 15305–16483 | **MCA-22 / FINAL INTEGRATION** — сквозная атрибуция | D1–D10 | `mca-22-attribution-memory-coherence-round1029` 2.58.44; `services/bot_output_ledger.py`, `services/thread_chain.py` | T-4319/T-4317 live-smoк; диск 4.6G watch | HISTORICAL-WITH-OPEN-TAILS |
| 16484–20832 | **ASAP-4** — Embedding CP, GraphRAG Activation, Cover Style | D1–D8 | `asap-4-embedding-graphrag-cover-runtime-round1030` 2.58.45; `services/embedding_control_plane.py`, `services/cover_style_registry.py` | T-4447/4448/4449 owner-live; EMBED_ASYNC_BATCH OFF; L-ASAP4-2…9 | HISTORICAL-WITH-OPEN-TAILS |
| 20833–22344 | **MCA-23** — Unified Response Orchestrator (§33–52) | план→DAG→ResponseDocument→Delivery | `8b446694` (phase 2, 2.58.71) + `services/response_extent.py`, `tests/test_mca23_response_plan.py`, `tests/test_mca23_planned_vs_actual.py` | §52 production-acceptance — owner live-gate (см. §4 BLOCKER-AUDIT) | HISTORICAL-WITH-OPEN-TAILS |
| 21650–21682 | §30 «Интеграция с оставшимися MCA» (MCA-08/09/10/15/16/18/19/20/21) | не ломать смежные фичи | покрыто соответствующими раундами | — | HISTORICAL-CLOSED |
| 22345–23846 | **ASAP 4.1** — Durable Whole-Window Summary | snapshot, supervised, runs | `asap-4-1-durable-whole-window-summary-round1031` 2.58.47 | PO-1…PO-5 owner; L-ASAP41-1…6 | HISTORICAL-WITH-OPEN-TAILS |
| 23847–25458 | **ASAP 4.2** — Surgical Summary Reliability | anchors, real provider E2E | `asap-4-2-summary-surgical-reliability-round1032` 2.58.48 | PO-2…PO-5 owner; L-ASAP42-2…6 | HISTORICAL-WITH-OPEN-TAILS |
| 25459–26364 | **ASAP 4.3** — Cover Style surgical + Test Style | честный Test Style, mobile UI | `asap-4-3-cover-style-surgical-round1034` 2.58.50/51 | L-ASAP43-1/2 (в силе) | HISTORICAL-WITH-OPEN-TAILS |
| 26365–27150 | **ASAP 4.4** — FINAL production closure | Cover Style + Hybrid + GraphRAG | `asap-4-4-final-live-closure-round1034` 2.58.52/53/54 | 7 хвостов (контентные причины Legacy, Inspector retro, promote-race, route-TTL, `LIMIT 1`, `[I-1]`, ASAP 4.3 carry-over) | HISTORICAL-WITH-OPEN-TAILS |
| 27151–29603 | **ASAP 5** — Summary Reliability + Cover Prompt + GraphRAG | 15E, controlled acceptance | `asap5-final-fixes-round1049` 2.58.69 VERIFIED | T-5274 owner; T-5248/5254/5263/5266 owner-гейты; N-1…N-7; scanner L-A/L-B | HISTORICAL-WITH-OPEN-TAILS |
| 29604–31768 | **ASAP 6 / P0** — Current Task Closure Audit | 15-строчная аудит-матрица | `archive/features/asap6-current-task-closure/{current-task-audit,review-final-w2w3}.md`; все 15 пунктов закрыты волнами asap6/asap7 | см. §4: MCA-23 §52 live — неявный owner-гейт | HISTORICAL-WITH-OPEN-TAILS |
| 31769–33791 | **ASAP 7** — Cognitive Direct Pipeline, Module Contract, Cover Truth, Multi-chat | L1/L2, initiative, corrective audit | `archive/features/asap7-cognitive-direct-pipeline` (20 файлов) | входило в asap5-final-fixes / owner live-гейты | HISTORICAL-CLOSED |
| 33792–37279 | **ASAP 8** (исходный v5) | 26 ID F1–F10 | `archive/features/asap8-reliability-truthfulness` (13 файлов) + `plans/features/asap8-v6-remediation/ledger-c.md`, `ledger-d.md` | 7 осознанных остатков (см. §3) + OWNER_VISUAL_PENDING | HISTORICAL-WITH-OPEN-TAILS |
| 37280–37422 | **ASAP 8 v6 — corrective delta после F1–F9** (A/B/C/C03A/C06A/D01–D14) | RECONCILE→REUSE→REMEDIATE, 26 ID | `plans/features/asap8-v6-remediation/` (wa1-3, wc-direct, c03a, c06a, d05–d07, d1213, d14, p1-d091011, **f10-report.md**) | 7 осознанных остатков (backlog «ASAP 8 v6»); OWNER_VISUAL_PENDING | HISTORICAL-WITH-OPEN-TAILS |
| 37423–37873 | **ASAP 8 v6.3** — Live Behavior, fullscreen, Liquid Glass | 148 inventory / 139 required | карта + ревью (см. §5) | REV-W1/W2 non-blocking; Wave 4 live-чеклист | ACTIVE (покрыто картой — не дублируется) |

Каждый архивный каталог существует на HEAD (32 проверенных пути, файлов 5–20 в
каждом) — см. §6.

---

## 2. Открытые хвосты (сверка с `plans/backlog.md` без дублей)

Все хвосты уже зарегистрированы в `plans/backlog.md`; ниже — только те, которые
не покрыты v6.3-картой и остаются открытыми на HEAD, сгруппированные по классу.
Полные формулировки — в `backlog.md` (строки 31–315); здесь без копирования.

**A. Owner live-гейты (только владелец, no-false-acceptance):**
T-5236 единый live-sweep. Пункты 1–12 (mca-15/16/09/10b/18/19/20/12/17c/21 +
скриншоты §21.5 + 3 RED-решения: deep-sleep PG-flag, ANU-ключ, vision-провайдер).
ASAP 5: T-5274, T-5248, T-5254, T-5263, T-5266. ASAP-4/4.1/4.2: T-4447/4448/4449,
PO-1…PO-5. ASAP-3.2/3.1: T-4234, T-4227. mca-04b/mca-05: платные LLM-пересборки.
V6: OWNER_VISUAL_PENDING (Save-чип D13, run-карточки, styled-cover live, Initiative live).

**B. Инженерные долги (non-blocking, все имеют owner-зону):**
`param-catalog-pg-only-seed-config-exposure` (ASAP-2); L-R1028-3 Cache-Control;
`CHAT_MODEL_CONTEXT_WINDOW` env/map (ASAP-3); M-ASAP31-2 fallback_payload_adapter в
tool-путь; `FACT_PACKAGE_TRUNCATED` семантика кап (ASAP-3.1/3.2/mca-22, владелец
считает отдельной проблемой); GraphRAG rebuild resume + smart_archive KNN-smoke;
L-EXTRA-3 `update_reference` 200-vs-404; L-HOTFIX-1/2; L-ASAP4-E2/E3/7/8/9;
L-ASAP41-1…6; L-ASAP42-2…6; L-ASAP43-1/2; ASAP-4.4 пункты 1–7; N-1…N-7 (ASAP 5);
N1–N7 (mca-17c); S-2/S-3 (mca-18); L-A/L-B (mca-15/17c/20); F-1…F-6 (mca-08);
F-1…F-6 (mca-11); F-1…F-6 (mca-10a); F-1…F-4 + census + [I-1]/[I-2]/[P-1] (mca-09);
F-1/F-2/N-1 (mca-10b); N-1…N-6 (mca-12); L-A/L-B + I-1…I-3 (mca-12 scanner);
N1–N5 + Wave-4 checklist (REV-W1/W2 v6.3).

**C. Операционные/процессные:** диск прод-сервера (≥2.7G guard на DDL);
`deploy_commands.txt` с кредами в корне репо (untracked, вне git) — перенести в
секрет-хранилище; рецепт агрегатного sha256 WTH-манифеста не документирован;
frozen-hash пины — eol-фактор; 6 предсуществующих свипт-failed (2× aiogram 3.29.1
InputRichMessageMedia — влияет на B04.5 prod-доставку, mca02 network, mca16,
2× summary-publish); флайки (mca09_intents_block_e, nostalgia year_back,
dream cluster_distilled, betterstack real_302).

**Вывод по разделу:** дублей backlog в аудите нет; ни один хвост не является
блокером релиза v6.3 (все non-blocking / owner-gate).

---

## 3. Покрытие осознанных остатков v6 волной v6.3

Источник остатков: `plans/features/asap8-v6-remediation/f10-report.md` §4
(7 строк) + backlog-таблица «ASAP 8 v6».

| Остаток v6 | Закрыт v6.3? | Доказательство |
|---|---|---|
| **D06** `_vec_candidates` chat-scope до top-K | **ДА — закрыт** | `services/summary_memory.py:4550` `_vec_candidates` → `_staged_knn_scope` (overfetch ×4 до cap, фильтр own-chat, telemetry `_log_knn_scope`). Тесты `tests/test_asap8_v63_b03_memory.py` (11 тестов, 5 классов: `TestGraphKnnChatScope`, `TestExpiredRetrievalEligibility`, `TestArchiveTopUpAndVersions`, `TestExpiredOverview`, `TestInfiniteRetentionNoDelete`) — **прогон 35 passed вместе с b08**. Карта: B03.4 + B10-R13. |
| **Partition key DDL** (v6.3 предложил staged overfetch как доказанную альтернативу) | **ДА — супerseeded техникой** | та же реализация `_staged_knn_scope`; апгрейд vec-хранилища не требуется. Остаётся только как дальнейшая оптимизация (не требований закрытия). |
| **7 виджетов D12** (memory-flow, Sankey, waterfall, heatmap, dependency map, timeline, overrides) | **ДА — закрыт** | `da58e24b`: все 7 на durable-данных + `/api/analytics/viz/activity`; REV-W3 §6 VERIFIED. Карта: U05.3 + B10-R17. E2E ANALYTICS 74/74. |
| **Diction `style_job_failed`** | **ДА — закрыт ранее в v6** | `02b38cb6` (F4): `cover_prompts_status {base,style}` с `style_job_failed` + человекочитаемая RU-причина построчно (§28.8). |
| **`demote_reason` детализация** (D04) | **НЕТ — остаётся** | backlog-строка «demote_reason детализация»; в v6.3-карте нет отдельного ID (B10-R11 принимает D03/D04 функционально, без расширения словаря). |
| **Stories recall-эмиттер** (C07/F7) | **ЧАСТИЧНО** | `4b64b38e`/`ccdd0a76`/`df1aac42`/`f8f9d9a` дали детерминированную сборку Stories + честные display-правила (`_stories_display`, `stories_rows`, +2 регресс-теста, 24 passed) и honest proxy `excluded_from_retrieval`; настоящего эмиттера «кто дёрнул историю» на retrieval-call-sites по-прежнему нет → backlog-строка в силе. |
| **`search_result` producer** (C06/C06A) | **НЕТ — остаётся (осознанно)** | v6 §C06A запрещает включать событие «ради счётчика»; в v6.3-карте ID нет. Требуется решение владельца. |
| **direct_concurrency** (backlog Direct-лейна, `test_third_handle_waits_for_slot_at_n2`) | **ДА — закрыт** | REV-W1: B10-фикс APPROVED (`test_direct_chat_concurrency.py` +19 строк, ассерты не тронуты; пин L1 OFF по канону F1). |
| **dossierSaving shared / D01 concurrent UI** | **ДА — принят повторно** | B10-R09 (concurrent UI edit/refresh/409 на dossier/настройках); `dossierSaving` — остаток отмечен в карте как «см. B11». |
| **Experience K2-OFF** | **ДА — принят повторно** | B10-R12 + REQ-B02/K2-OFF; в карте помечен как «см. B11»; `mca_experience.py` + `tests/test_asap8_v63_b02_semantic_experience.py`. |
| **OWNER_VISUAL_PENDING (v6)** | в процессе | Wave 4 live-чеклист (`waves.md` §W4) — см. live-canary.md. |

Итог: из 7 осознанных остатков v6 — **4 закрыты** (D06 vec-scope, partition-DDL
техникой, 7 виджетов D12, diction `style_job_failed`), **1 частично** (stories
recall), **2 остаются осознанно открытыми** (`search_result` producer — требует
решения владельца; `demote_reason` детализация — диагностическое уточнение).

---

## 4. BLOCKER-AUDIT — действующие требования вне v6.3

**Блокеров нет.** Ни одно требование строк 1–37422 не является одновременно
(a) действующим и (b) непокрытым ни v6.3-картой, ни `plans/backlog.md`.

Единственная строка, которую следует держать на радаре владельца (не блокер
кода, а пробел учёта):

- `current_task.md:22341` — «MCA-23 production acceptance complete; unified
  response orchestration is the canonical Direct/Autonomous execution path».
  §52 (21650–22344) требует production-acceptance MCA-23; код фазы 2 закоммичен
  (`8b446694`, 2.58.71) и подтверждён аудитом ASAP-7
  (`archive/features/asap7-cognitive-direct-pipeline/audit-modules-chat-claims.md:185`
  — «MCA-23 phase 2 complete»), отдельного backlog-пункта для live-приёмки нет:
  она поглощена консолидированным owner live-sweep T-5236 и ASAP-5 «owner-гейты
  программы MCA — консолидация БЕЗ изменений». Рекомендация: при закрытии Wave 4
  добавить строку live-приёмки MCA-23 в live-canary.md, чтобы гейт был явным.

Остальные «действующие» требования либо закрыты кодом+тестами (MCA-01…22, ASAP
2–8/v6), либо перенесены в backlog с обоснованием, либо являются owner-гейтами
(нет доступа у агентов).

---

## 5. v6.3-часть (37423–EOF) — только сверка факта (без дублирования)

- **Карта:** `plans/features/asap8-v6-3-live-correction/requirements-map.json`
  существует, schema `openworkflow-coverage-v1`, `source_sha256` =
  `91f754e3…` (= текущий `current_task.md`); **148 inventory-позиций**
  (139 required / 8 duplicate / 1 context), 15 слайсов
  (FE-FULLSCREEN 25, FE-GLASS 24, REL-GATE 18, FE-STATUS 13, FE-SHELL 10,
  FE-EDITOR 8, BE-MODULES 8, BE-COVER 7, BE-INITIATIVE 6, BE-EXPERIENCE 6,
  BE-MEMORY 6, BE-STORIES 5, BE-MIGRATION 1, BE-INT-REPORT 1, смешанный 1).
- **Гейт plan:** `requirements_gate.py check --stage plan` → **exit 0**
  (`inventory=148 manual=74 scoped=0 errors=0`).
- **Ревью:** `review-w1.md` (fix-note исправлен, recheck 39 passed, B09
  IMPLEMENTED+TESTED, B10-фикс APPROVED), `review-w2.md` — **Approved** (объём
  Wave 2, блокеров нет), `review-w3.md` — **Approved** (объём Wave 3;
  live/прод = Wave 4), плюс `review-w3-stories-mech.md`, `review-coverage.md`.
- **Статус релиза:** `candidate_commit` и `deployed_commit` в карте **пусты**,
  все 148 статусов = `PENDING` → `check --stage release` даёт **exit 1**
  (202 errors). Это соответствует параллельному деплою (прод ещё 2.58.78 /
  `f58a644` по `plans/workflow_state.md`), а не дефекту реализации. После
  заполнения SHAs и live-статусов Wave 4 повторный release-gate обязателен.
- **Вердикт аудита по v6.3:** требования покрыты картой, ревью Approved на
  уровне кода и тестов; live-секция — Wave 4 (см. live-canary.md).

---

## 6. Spot-check результаты (артефакт существует на HEAD)

| # | Программа | Заявленный артефакт | Проверка | Результат |
|---|---|---|---|---|
| 1 | MCA-01 | tx/task supervisor | архив `mca-01-…-round1027` (8 файлов) + 171 commit-site census (`1db6931`) | OK |
| 2 | ASAP-2 / 2.1 | `services/summary_memory.py` | 47 коммитов, последний `1e24eca4` | OK |
| 3 | ASAP-3 | `services/direct_context_composer.py`, `model_capacity.py` | файлы + 5 коммитов `model_capacity` | OK |
| 4 | ASAP-4 | `services/embedding_control_plane.py`, `cover_style_registry.py` | 6 и 7 коммитов, последние `781e9b3b`, `92de1e37` | OK |
| 5 | MCA-22 | `services/bot_output_ledger.py` | 1 коммит `9c78760` (2.58.44) + интеграции в 9 модулей | OK |
| 6 | MCA-12 | `web/api/stories.py` | 2 коммита, последний `df1aac42` (2.58.76) + `MCA_STORIES_VITRINA_ENABLED` в catalog/settings | OK |
| 7 | MCA-17c | `web/api/memory_overview.py` | 1 коммит `2d95689e` (v6.3 W3a) + `web/api/analytics_viz.py` | OK |
| 8 | ASAP-7 | `services/direct_l1.py`, `tests/test_mca23_planned_vs_actual.py` | 3 коммита, последний `2ef61892` | OK |
| 9 | ASAP-8 v6 C03A | styled-cover recovery | `87006280` + `services/cover_style_jobs.py`, 36 recovery-тестов | OK |
| 10 | **v6.3 B03/B08** | staged KNN scope + Stories cards | **собственный прогон:** `pytest tests/test_asap8_v63_b03_memory.py tests/test_asap8_v63_b08_stories.py` → **35 passed** | OK |

Дополнительно проверено: `services/response_extent.py` (планировщик MCA-23 фазы 2,
16 вхождений `ResponsePlan`), `services/mca_game_stub.py` (§14.12 — намеренно
неактивная заглушка, `23cb2a1c`), `APP_VERSION = 2.58.79` и README `v2.58.79`.

---

## 7. Ограничения аудита

1. **Прод не проверялся** (иная лейн): все live/acceptance-строки = Wave 4 /
   live-canary.md; `plans/workflow_state.md` фиксирует прод на 2.58.78.
2. **Бюджет:** ~30 файловых чтений + grep'ы. Глубокое перечитывание всех 37 873
   строк не выполнялось — статусы определены по границам разделов, финальным
   отчётам/архивам и точечным грепам, а не построчным проходом.
3. **Границы разделов** определены по заголовкам `^#{1,2} `; отдельные
   нумерованные подпункты (особенно в ASAP-3 §1–62 и ASAP-4 §50.x) не
   инвентаризовались поштучно — их покрытие подтверждается архивными
   requirements-map/review соответствующих раундов.
4. **Исторические и заменённые требования** (ASAP-1, §22–23, §26, §30, ASAP-8 v5
   после v6-delta,MCA-23 до фазы 2) помечены HISTORICAL-CLOSED / частично
   HISTORICAL-WITH-OPEN-TAILS **без перезапуска** — переоткрытие только по
   конкретной регрессии.
5. **Хронология ≠ порядок строк** в `current_task.md`; эпохи сопоставлены по
   содержимому и архивным раундам (10.27–10.48, 10.49, 10.13–10.14, 10.14, 10.15–16).
6. `requirements_gate.py` вызван как read-only проверка; гейт release НЕ
   проводился как «сданный» — зафиксирован его фактический exit 1 на текущем
   состоянии (deploy в процессе).

---

## Итог для владельца

Исходный `plans/current_task.md` (37 873 строки, байт-в-байт = замороженный
снапшот) **полностью покрыт**: 28 программ/эпиков — все закрыты с архивными
доказательствами и версиями (MCA-01…22 + ASAP 2–8/v6, релизы 2.58.31→2.58.78);
открыты только owner live-гейты и non-blocking долги, все зарегистрированы в
`backlog.md` без дублей. **Активных непокрытых требований нет — BLOCKER-AUDIT
чист.** Из 7 осознанных остатков v6 волна v6.3 закрыла 4 (D06 vec-scope,
partition-DDL техникой staged overfetch, 7 виджетов D12, diction
`style_job_failed`), 1 частично (stories recall), 2 остаются осознанно
(`search_result` producer, `demote_reason`). v6.3-часть: карта 148 позиций
(139 required), gate `--stage plan` exit 0, ревью W1/W2/W3 **Approved** на
уровне кода и тестов; release-gate сейчас exit 1 штатно — SHAs и live-статусы
заполняет идущий деплой (прод 2.58.78 → Wave 4 / live-canary.md). Spot-check
10 программ — все артефакты на HEAD, включая собственный зелёный прогон
35 тестов v6.3 (B03+B08).
