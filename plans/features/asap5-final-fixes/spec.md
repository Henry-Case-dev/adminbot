# `asap5-final-fixes` — spec.md (Step 2 @Architect, design-freeze 07.10.2026)

Feature: **ASAP 5** — Summary Reliability + Cover Prompt Transparency + GraphRAG Recovery (+ Embeddings migration/identity, Random config-clarity, Парадигмы, Граф, Visual QA). Источник требований: `plans/current_task.md:27151–29600` (USER-OWNED, READ-ONLY). Входы: `requirements-map.md` (ASAP5-R1…R30, Q1–Q13), `tasks.md` (T-5238…T-5275), RCA-отчёты: `rca_summary.md` (**9/9 confirmed**), `rca_cover.md` (4 CONFIRMED / 2 REFUTED / 1 ADJUSTED + прозрачность REFUTED), `rca_graphrag_random.md` (G1 ADJUSTED→**STUCK**, G2–G6/13A/13B confirmed). Базлайн: прод **2.58.67** (feat `6f062fa`), SQLite **v33**, каталог **523**, KS **85**, reason **280**, тулы **14**, реестр **47**. ADR: **adr-1028-25** (Proposed; «1028-25» свободен, −24 занят mca-release). **Статус: PLANNING_READY** — на сверку @PM (T-5240).

Правило дизайна: каждый fix = подтверждённый RCA root cause; AMEND точечными правками, никаких rewrite (§18); simplest design с проверяемым поведением и понятными failure-режимами.

---

## §1. RCA-вердикты — основа design-freeze (T-5241/T-5242/T-5243)

| # | Симптом/аудит (раздел) | RCA-вердикт | Root cause (механика) | Fix |
|---|---|---|---|---|
| S1 | §1.1 L1 валит Summary (витрина «не выполнено») | **confirmed** (`rca_summary` п.1/п.6) | durable L1-статус бинарный (`summary_generator.py:1971–1974`), ось «продолжение пайплайна» в витрину не проецируется; трёхуровневой семантики нет нигде | **D1/D6** |
| S2 | §1.2A `unusable` доверяет модели | **confirmed** (п.2) | `summary_l2_review.py:1022–1031` — raw status=unusable → немедленно `l2_unusable` → Legacy; прод: **8/8** последних fallbacks = `l2_unusable` | **D3** |
| S3 | §1.2B unknown severity → blocking | **confirmed+усиление** (п.3) | `:326–328` — неизвестный severity → `SEVERITY_BLOCKING`; в anchor-mode **все** findings принудительно blocking (`:353–367`); таксономии код→класс нет | **D2** |
| S4 | §1.2C progress по count | **confirmed** (п.4) | `:1045–1057` — `blocking_now >= prev_blocking → break`; fingerprint не вычисляется | **D4** |
| S5 | §1.2D soft топит Hybrid | **confirmed** (п.5) | все 15 FINDING_CODES равноправны; needs_fixes с оставшимся «blocking» → `l2_review_rejected` → Legacy; механика degraded-publish есть (`_degraded_or_legacy`), к semantic-rejection не применяется | **D5** |
| S6 | Live: «Writer не выполнено — Проверка отклонила» | **confirmed** (п.7) | stage-статус пишется на всю L2 (`:2258–2262`); Writer реально выполнился; RU-текст `l2_review_unusable` описывает другой механизм | **D5/D6** |
| S7 | Live: не видно, какой finding blocking / почему не прогресс | **confirmed** (п.8) | данные per-attempt уже durable (`stage_events`: verdict/finding_codes/blocking_count/paragraph_ids/revision-результаты, ≤24, R17-safe), UI не рендерит | **D6** |
| S8 | Live: Hybrid систематически в Legacy | **confirmed** (п.9) | цепочка S2–S5; Legacy = штатный исход ежедневных прогонов, `pipeline_health=degraded` | **D3/D4/D5** |
| C1 | Cover: стиль/профиль/номер/инварианты/refs-картинки доходят | **CONFIRMED** (`rca_cover` §2) | — | сохраняется (D7 фиксирует в манифесте) |
| C2 | Cover: сюжет слабый/теряется | **REFUTED** как «доходит» (§2#2) | 4 ступени squeeze; cover_prompt ≤300 — единственный смысловой источник; `brief_from_text` double-squeeze; unknown-limit retry `minimal=True` выбрасывает brief целиком (прод 911→708, 2/2 повторяемо) | **D8/D9** |
| C3 | Cover: Summary-context | **REFUTED** (§2#3) | `summary_text=cover_prompt` (`:3007`); в пайплайн не вводится вообще (`context: 0` честен) | **D8** |
| C4 | Cover: прозрачность («что реально ушло») | **REFUTED** (§2) | полный prompt не персистится нигде; только длины/hash; восстановить после отправки нельзя даже админом; `limit_source=unknown` | **D7/D9** |
| G1 | GraphRAG building/gen_fp==new_fp | **ADJUSTED → STUCK** (`rca_gr` §2.3) | квот-paused job (`paused_rate_limit`, 576 пауз/7.5 сут, checkpoint 40% заморожен >20 ч); это не config-mismatch и не «нормальный rebuild» | **D10** |
| G2 | §13 stale building → recovery | **CONFIRMED дефект** (§2.3 п.2) | resume-gap: `_ensure_job` при неистёкшем `next_allowed_at` не планирует future-resume (`graphrag_rebuild.py:1667–1673`); in-process auto-resume умирает с процессом; рестарты ~1.3 ч → job спит вечно | **D10** |
| G3 | Warning «not serviceable» | **ADJUSTED** (§2.4) | коалисинг 300 с работает (55/72 ч), но память in-process; warning честен — **не глушить**; устраняется resume-фиксом | **D10** |
| G4–G6 | Random `provider_unconfigured` | **CONFIRMED** config/degraded (§3) | selected=quantum при `key_fingerprint=NULL`; fallback честен; transition ×1 на state-key; путь исправления из UI физически отсутствует — **bootstrap paradox 14A.0**: `routes.py:489` items только из `cache.get_all()`, `pg_db.py:722` не сидит секреты | **D13** |
| P1 | 13A: виден только cooldown | **CONFIRMED** (`rca_gr` §4) | `memory_agi.py:635–644` — gate_reason приоритетнее last-attempt; cooldown считает **любые** попытки (`dream_worker.py:1821–1841`); прод: 16 подряд `no_anchors` | **D14** |
| GR1 | 13B: стена текста | **CONFIRMED** (`rca_gr` §5) | `app.js:14946–15001` — labels у всех узлов, фикс. шрифт, без scaling/drawThreshold; данные presentation не режет | **D15** |

---

## §2. Архитектурные решения (frozen, D1–D19)

**D1 — L1-семантика OK / DEGRADED_MAP_FALLBACK / FAILED_TERMINAL.** Трёхуровневый статус в durable stage result и узле витрины; при DEGRADED_MAP_FALLBACK — причина деградации карты + явная пометка «Writer продолжил от полного окна (fallback package)». FAILED_TERMINAL — только когда L2 Writer не стартовал из-за отсутствия и semantic map, и Full SourceWindow/fallback package (редкий инфраструктурный случай). Обоснование: RCA S1 — L1-fail не валит Summary (writer-source ON by default), витрина обязана это показывать.

**D2 — Server-owned severity-таксономия.** Новый код-константник `FINDING_CODE_TAXONOMY` (в `summary_l2_review.py`): **все 15 существующих FINDING_CODES** получают ровно один класс `hard|soft`, условия promote/demote и `can_force_legacy`. Hard (factual/safety, can_force_legacy=yes): wrong_person_attribution; quote speaker/text mismatch; invented_name; unsupported_number; contradiction_with_package; forward/reply attribution; material factual_overstatement; material timeline inconsistency. Soft (quality/completeness, can_force_legacy=no): duplicate_event; major_topic_omitted; стилистические/полнотные. Promote soft→hard — только при server-side детерминированном подтверждении механизма (deterministic validator); demote hard→soft запрещён (integrity fail-closed). Unknown/не из словаря код от модели → существующий путь dropped_invalid (в трейсе виден), никогда не blocking. Severity-поле модели решение не принимает. Код без класса на ревью = дефект (STOP-условие).

**D3 — `unusable` server-gate (Q1).** Raw `status=unusable` принимается как terminal **только если**: (а) ≥ **2 независимых валидных HARD findings** (независимость = разные finding-коды И разные paragraph targets), **или** (б) deterministic validator сам доказал непригодность (тот же механизм, что даёт hard proof). Иначе unusable даунгрейдится до needs_fixes с сохранением findings как blocking-набора (идёт в bounded repair); даунгрейд фиксируется в трейсе (отдельное событие, reason `l2_unusable_gate` — см. D17). Обоснование: §4.3 делегирует threshold Architect; прод-факт 8/8 `l2_unusable` требует evidence-квоты, а не доверия статусу.

**D4 — Stagnation по fingerprint (Q3).** Идентичность hard-finding = `code + paragraph_id + sorted(evidence_refs) + target` (нормализация: paragraph_id канонический, refs — sorted set, target — paragraph/span id). Progress = prev_fps − curr_fps ≠ ∅ (старый исправлен) — даже при новых findings. Stagnation (разрешён break): тот же fingerprint-набор после repair, ИЛИ документ/target не изменился (hash), ИЛИ deterministic validation вернула тот же hard mechanism. Count — только вторичный сигнал в трейсе. `MAX_REVISIONS` ≤2 и бюджет **не увеличиваются** (§4.5: без роста LLM-циклов). Обоснование: RCA S4, прод-пример «исправлен old + найден new = ноль прогресса».

**D5 — Final policy + честные стадии.** Исход run'а = `HYBRID_PUBLISHED | HYBRID_DEGRADED_PUBLISHED | LEGACY_FALLBACK` + **одна точная причина**. Soft-only needs_fixes после исчерпания bounded-цикла → `HYBRID_DEGRADED_PUBLISHED` (переиспользовать существующий механический путь `_degraded_or_legacy`), не Legacy. Hard unresolved / server-подтверждённый unusable / transport-провал / структурная невалидность после bounded repair → `LEGACY_FALLBACK` (4 случая §4.1 — исчерпывающий список). Витрина: Writer и Reviewer — раздельные stage-исходы; «не выполнено» резервируется за transport/структурным провалом; RU-текст `l2_review_unusable` исправляется на честный («Reviewer вернул semantic unusable…»). Reviewer-outage fail-soft (degraded publish) сохраняется как есть.

**D6 — Hybrid Decision Trace без новых LLM-вызовов.** Источник трассы — **существующие** durable stage_events (`_stage_event`: attempt/verdict/finding_codes/blocking_count/paragraph_ids/revision_target/revision_result/revision_failure_reason/deterministic_validation_codes) + финальная policy-запись. Хранение final policy — **строка `stage='final_policy'` в существующей `summary_run_stages`** (status=policy-исход, reason_code=точная причина) — Δ DDL = 0 (проверено: у таблицы есть stage/status/reason_code, `database.py:927–941`). UI-карточка в Run Inspector рендерит 5 секций §3.1 (L1 / L2 Writer / Reviewer-итерации / Revision-итерации / Final policy). Телеметрия mca_events не расширяется (drill-down по trace_id из БД — вне скоупа, RCA п.10.3 учтён). Обоснование: RCA S7 — данных хватает, отсутствует только витрина + финальный статус.

**D7 — `CoverPromptManifest` (Q4, имя зафиксировано).** Единая server-side структура для Base и Style Edit, одна компиляция для всех трёх UI (§10A.1). Схема: 6 компонент (`BASE_STYLE, STORY_SCENE, SUMMARY_CONTEXT, STYLE_PROFILE, RUNTIME_INVARIANTS, REFERENCES`), для каждой `source/priority/original_text/original_chars/sent_text/sent_chars/status kept|compacted|omitted/reason`; плюс `provider/model/route/operation/resolved_limit/limit_unit/limit_source/final_prompt/final_chars/prompt_hash(sha256[:16], существующая конвенция)` и **массив attempts** (attempt 1 / retry — обе фактические строки). Персист полного sent prompt — JSON в **существующем** job/run evidence (Style Edit — payload `task_jobs`, где уже живут `prompt_diagnostics`; Base — evidence Summary run'а); retention bounded вместе с этим evidence; чтение — только admin-authorized существующие API (расширение ответов, не новые роуты — D17); в generic server log полный prompt не попадает (SAFE_LOG_FIELDS не меняются); без API key/secret.

**D8 — Base Cover contract.** Base получает `STORY_SCENE` (главный предмет/действие/обстановка, явный minimum budget — стиль не вытесняет сюжет) + `SUMMARY_CONTEXT` (bounded representation финального approved Summary: title + главные события/участники; переиспользовать CoverBrief-builder, но от FINAL SUMMARY, не от 300-char seed) + `BASE_STYLE`. Без нового дорогого LLM-call. Технически: сборка cover-prompt выносится из `summary_generator.py` в новый модуль `services/cover_prompt_assembly.py` (B2-владение), `compose_cover_image_prompt` сохраняется как импортируемый shim (join-инвариант для `summary_test.py`/тестов). Обоснование: RCA C2/C3 — сюжет P2-по-факту и единственная жертва.

**D9 — Style Edit contract + bounded semantic squeeze (Q5).** Edit-not-recompose; mandatory minimums при **любом** retry: P0 runtime (issue/logo/no-duplicate) полностью + minimum story + minimum profile identity + mandatory reference roles; затем optional context/details. Числа: story-minimum = **160 chars или 100% оригинала, если короче**; profile identity ≥ **50%** текущей instruction; ссылки-картинки (reference_paths) при retry не меняются (уже так). `minimal=True` (P0+style, потеря сюжета) — **запрещён**. Один retry максимум (как сейчас). `resolved_limit`: unit=chars; `limit_source ∈ {capability_registry, last_success, unknown}` — при unknown **честно unknown**, без выдуманного числового лимита (§18 запрещает hardcoded arbitrary limit); squeeze при unknown выполняется до mandatory-ядра с story-minimum, эмпирически соответствующего прошедшему провайдеру (~708). Все сокращения — в Manifest (D7). Обоснование: RCA C2/C4 — root cause `limit_source=unknown → minimal=True → prompt без сюжета`.

**D10 — GraphRAG recovery (future-resume, переживает рестарты).** Дефект G2 закрывается **без in-process sleep**: существующий `maybe_schedule_rebuilds(include_failed=False)` вызывается из периодического scheduler-тика (период ≤ 15 мин, константа в коде) — тогда `_ensure_job` с неистёкшим `next_allowed_at` даёт no-op, а после истечения cooldown следующий тик возобновляет job; рестарты (~1.3 ч) больше не убивают восстановление. Healthy vs stale: при живом прогрессе (last_progress_at свежий, lease жив) — «Vector rebuild in progress N/M» в Analytics, warning не повторяется (per-process dedupe достаточен — устраняется сам resume-фиксом); при stale building (нет active job / lease умер / progress stale / job terminal) — один bounded resume/rebuild, без бесконечных duplicate jobs; при невозможности — visible durable blocker. Warning **не глушится** (§13, §18). Смарт-архив: `knn_source_empty` при пустом источнике — stable terminal с видимой причиной, без переоткрытия по schedule (RCA §2.4, тот же файл/лейн). Диагностика §13 (13 полей) + подключение написанного `rebuild_status()` к **существующему** embeddings/status read-API (без нового роута, D17).

**D11 — Embeddings: три честных профиля + identity (Q6).** Primary/Fallback1/Fallback2 — независимые provider/base_url/model/key/quota_group/params; Fallback2 не наследует от Fallback1 без явного режима «наследовать»; отдельные config keys/runtime bindings/status/probe; миграция существующих credentials без потерь (текущие значения `models.embedding_fallback_*` становятся значениями Fallback1; ключи уже раздельные). Identity fingerprint (Q6): sha256[:16] над каноническим JSON из {provider family/protocol, resolved endpoint, resolved model + revision (если отдаётся), effective dimension (+override), task/type/mode, normalization, материальные параметры}; key/quota/timeout/route сами по себе identity не меняют. Canary для floating alias: **3 фиксированные non-sensitive строки-пробы**, их вектора кэшируются в существующем `embedding_cache` под identity_fingerprint (5 identity-колонок уже есть, `database.py:472–479`); сверка — **косинусная близость** (порог: mean < 0.98 или min < 0.95 → drift), не byte-hash float-векторов. Не доказано → `COMPATIBILITY_UNKNOWN` (fail-safe: без writes в active generation, FTS fail-soft, видимый blocker, не «наверное совместимо»). Классы INSTANT_COMPATIBLE / REINDEX_REQUIRED / INCOMPATIBLE_DIMENSION / COMPATIBILITY_UNKNOWN — одна server-side классификация для backend и MiniApp; одинаковая размерность сама по себе не даёт INSTANT_COMPATIBLE.

**D12 — Generations state machine + storage (Q7).** Реестр `mca_embedding_index_generations` переиспользуется (AMEND поверх, `database.py:5385–5597`): словарь статусов расширяется значениями state machine (ACTIVE_OLD→BUILDING_TARGET→CATCHING_UP→READY→atomic PROMOTE + FAILED/SUPERSEDED/CANCELLED/BLOCKED) — status TEXT без CHECK, новых миграций не требует; инвариант «chat → одна ACTIVE» моделируется index-namespace-конвенцией (`index_name` per chat/namespace) + partial UNIQUE active-индекс (уже существует). Migration job'ы — в существующем `task_jobs` (kind=`embedding_migration`), checkpoint/cursor/lease — по прецеденту graphrag-rebuild (payload). Storage (Q7): **generation-isolated физические vec-таблицы** через существующий shadow/swap-механизм `_activate` (build в shadow-таблицу → атомарный swap-activate в одной транзакции, `graphrag_rebuild.py:897–948`); старые таблицы не удаляются до истечения rollback-retention; GC только по retention-политике; destructive ALTER/resize активного хранилища запрещён. Entry-check Builder'а (единственный санкционированный unknown): если текущее создание vec-таблиц — runtime-CREATE, Δ DDL остаётся 0; если окажется, что изоляция требует versioned-миграции — единственный предсанкционированный путь: одна аддитивная миграция v34 по механизму mca-14 (nullable/additive, PG no-op, повторный прогон no-op), с обязательной эскалацией @Architect до merge. Snapshot+delta catch-up, no new-message loss, promotion только после coverage+delta+consistency, rollback при падении post-promotion health — по §13E без отклонений.

**D13 — Random bootstrap-фикс (14A.0).** Подход **минимально-системный**: `/api/config` дополняет items **синтетическими catalog-only items** для незаданных секретов санкционированных secret-групп (`keys_random`; другие secret-группы — той же механикой, только по списку в коде): `configured=false`, без plaintext, без пустой строки-«секрета», **без фиктивных строк в БД** (синтетика деривационная — переживает рестарт by construction). Сборка config-items выносится из `routes.py` в helper `web/api/config_payload.py` (B3-владение); в `routes.py` — тонкий вызов (region-фикс, см. D17 про F11). Карточка «Случайность: подключение ANU» видна до первой настройки и после reload/restart; entry point «Сон → Случайность» (кнопка «Настроить подключение ANU →»); один protected secret store, второй storage/field не создаётся. Owner-supplied ключ (14A.2) — через существующий protected path, клиенту только `configured/last4`, plaintext нигде; `/api/random/test`; `provider_unconfigured` исчезает; ротацию не рекомендовать, ключ повторно не запрашивать.

**D14 — Парадигмы: gate ≠ last-attempt (Q11).** `deep_sleep_status` отдаёт независимо: `scheduler_gate` (cooldown|schedule|budget|...) и `last_attempt_result` (`no_context|no_anchors|insufficient_evidence|unchanged|duplicate|budget_skip|llm_error|parse_error|paradigm_write|ok`) + счётчики anchors/candidates/validated/written/причины отсева + последний успешный прогон (§13A.1 полный набор). Cooldown объясняет только почему новый запуск не начался. Retry-классы: **A** контент-пустые (no_context/no_anchors/insufficient_evidence/unchanged/all_duplicates) — обычный интервал, причина видна; **B** техошибки (llm_error/parse_error/write_error) — короткий bounded backoff (старт 1 ч, ×2, максимум 2 ускоренных повтора/сутки, дальше обычный интервал — не busy-loop); **C** bootstrap (`paradigms_total==0`) — попытки раз в 2 ч, максимум 6/сутки, до первой записи. Manual deep run — обходит scheduler cooldown в рамках существующего контракта, результат в той же диагностике. Защита от бесконечных LLM-вызовов сохраняется. Обоснование: RCA P1 — 16×no_anchors за cooldown при намеренном «считать любые попытки».

**D15 — Граф: semantic zoom (presentation-only).** **В скоупе** минимального фикса (без него невыполним acceptance 13B.4): vis-network `scaling.label.drawThreshold/maxVisible` + zoom-обработчик — far (точки/рёбра все, подписи почти скрыты, несколько центральных), medium (подписи заметных), close (шире, с визуальным ограничением длины); selected neighborhood — labels выбранного+соседей, edge labels только neighborhood; search находит/приближает/включает label + полный текст в detail panel; длинные labels — краткое canvas-представление, canonical `node.label` в backend не менять, полный текст в detail/tooltip; **все nodes/edges остаются в DataSet** (не резать, не удалять ради скриншотов). Обоснование: RCA GR1 confirmed, §13B.

**D16 — Write-scope/сериализация (Q9/Q13).** См. §4: 3 лейна строго непересекающиеся по доменам; hotspots (`web/app.js`, `web/index.html`, `services/summary_generator.py`, `services/mca_events.py`, `web/api/routes.py`, `config/settings.py`) — SERIALIZE через parent Builder с фиксированным порядком и секционной принадлежностью.

**D17 — Δ-инварианты и пороги СТОП (Q8).** См. §5.

**D18 — Deploy (Q10).** Risk **R2** ратифицирован (см. §9). Один deploy-окон после интеграции B1+B2+B3 и зелёного T-5270: CA-11 bump **2.58.67→2.58.68** (код-дельта есть во всех трёх лейнах; «пустой» бамп запрещён); при Δ DDL = 0 миграционный smoke не требуется (frontier v33/0 pending + census); при Δ DDL ≠ 0 (только по предсанкционированному пути D12) — миграционный smoke + frontier 0 pending обязателен. Откат: soft (config/KS, каноны не затронуты) + cold (git revert; при v34 — аддитивная миграция совместима в обе стороны). SSH/fail2ban-дисциплина AGENTS.md: один recon ~15 с + один основной прогон, пауза ≥ 22 мин при закрытом SSH, статус по HTTP `/healthz` (443), креденшелы — только в `deploy_commands.txt`.

**D19 — Тесты (Q12).** Финальный реестр: §16 #1–25, #34–36 (33 focused) + **13N×28** (embeddings) = 61 позиция; гэп нумерации #26–33 — **зарезервирован разделом, не перенумеровывать** (якоря PM/requirements ссылаются на номера), недостающие кейсы покрыты 13N ( embedding-домен) — зафиксировать в test-реестре комментарием «#26–33 = 13N#1–28». Живые приёмки (T-5274) — no-false-acceptance, имитация запрещена.

---

## §3. Контракты/инварианты (frozen для всех лейн)

- **INV-1 (integrity fail-closed):** hard factual finding никогда не demote, не soft, не игнорируется; bounded repair — да, «просто публиковать» — нет.
- **INV-2 (без роста LLM-циклов):** MAX_REVISIONS ≤2, retry Cover ≤1, новых обязательных LLM-вызовов не появляется (Decision Trace — из существующих событий; Summary-context — без LLM).
- **INV-3 (прозрачность):** каждое фактическое сокращение/даунгрейд/шлюз виден владельцу в UI (трейс/манифест/диагностика) с точной причиной; «не выполнено» — только про реально не выполненное.
- **INV-4 (секреты/prompts, R17):** plaintext ANU — никогда в код/логи/evidence/API; full prompts — admin-only, не в generic logs, retention bounded; `/api/config` не отдаёт значения секретов (только configured/mask).
- **INV-5 (память не уничтожается):** raw source memory авторитетна и переживает любые смены embedding-модели; смешивание vector spaces запрещено; promotion атомарен; rollback возможен.
- **INV-6 (GraphRAG честность):** warning не глушится, не дублируется; healthy rebuild ≠ авария; FTS остаётся fail-soft во время rebuild.
- **INV-7 (UI):** каждое визуальное изменение — Playwright + Browser Use (§15A–15F), neighborhood sweep, fix → re-review; недоступность инструмента ≠ PASS.

---

## §4. Санкции — write-scope трёх лейн (Q9/Q13; правило `:27411`)

### B1 — Summary reliability + inspector (PARALLEL_SAFE внутри домена)
`services/summary_l2_review.py`, `summary_l2_writer.py`, `summary_l1_semantic_map.py`, `summary_prompts.py`, `summary_run_store.py`, `summary_run_log.py`, `services/execution_graph_source.py`, `services/pipeline_analytics.py` (только summary-узлы/REASONS_RU), `services/summary_generator.py` (**после** B2-extraction, см. SERIALIZE-1; только функции L1-статуса/legacy-матрицы), `web/app.js` (секция Run Inspector), `web/index.html` (блок Inspector), tests Summary (T-5267).

### B2 — Cover Prompt Transparency (PARALLEL_SAFE внутри домена)
`services/cover_prompt_assembly.py` (**новый**, extraction из summary_generator — SERIALIZE-1), `services/cover_style_jobs.py`, `services/image_prompt_compiler.py`, `services/cover_style_edit.py`, `services/cover_style_registry.py`, `services/system2_handoff.py` (COVER_PROMPT-константы), `web/api/cover_styles.py`, `web/api/summary_test.py`, `web/app.js` (секции Cover Constructor/Style Editor/Cover Analytics), `web/index.html` (соответствующие блоки), tests Cover (T-5268). Все UI-правки — под Visual QA §15A–15F.

### B3 — GraphRAG + Embeddings + Random + Memory-UI (PARALLEL_SAFE внутри домена)
`services/graphrag_rebuild.py`, `dossier_rebuild_jobs.py`, `summary_memory.py` (guard/коалисинг), `embedding_control_plane.py`, `llm_client.py`, `llm_probe.py`, `status_service.py`, `services/database.py` (registry/job-хелперы; DDL только по D12-пути), `mca_random_source.py`, `mca_intents.py`/`mca_exploration.py` (если touch), `web/api/memory_agi.py`, `dream_worker.py`, `mca_gates.py`, `web/api/config_payload.py` (**новый**), `param_catalog.py` (только санкционированные embedding-ключи §5), `web/api/routes.py` (**ровно одна region**: вызов config-payload helper — SERIALIZE-3), `web/app.js` (секции embeddings/random/paradigms/graph), `web/index.html` (соотв. блоки), tests B3 (T-5269).

### SERIALIZE (hotspots, parent Builder)
- **SERIALIZE-1 `services/summary_generator.py`:** первый merge-коммит пакета B2 — extraction cover-сборки в `cover_prompt_assembly.py` + import-shim (`compose_cover_image_prompt` сохранён); **до** этого ленда B1 не трогает файл; после — B1 владеет своими функциями, B2 файл больше не трогает.
- **SERIALIZE-2 `web/app.js` / `web/index.html`:** секционная принадлежность (B1: Run Inspector; B2: Cover×3; B3: embeddings/random/paradigms/graph); коммиты строго последовательные, порядок применения **B1→B2→B3**; конфликт внутри чужой секции → escalate, тихо не править.
- **SERIALIZE-3 `web/api/routes.py`:** единственная санкционированная правка — region config-items (B3, D13); F11 re-pin **ровно один** на пакете (T-5270).
- **SERIALIZE-4 `services/mca_events.py`:** ожидается Δ=0; при необходимости reason-кода из списка §5 — через parent, одна правка.
- **SERIALIZE-5 `config/settings.py`:** только parent на интеграции — APP_VERSION 2.58.67→2.58.68 (release-owned, прецедент §1.2.13).

### BLOCKED_BY
- B1 (T-5245+) BLOCKED_BY: SERIALIZE-1 ленд B2-extraction.
- Все лейны BLOCKED_BY: T-5240 (PLANNING_CONSISTENT).
- T-5266/T-5270 BLOCKED_BY: T-5248, T-5254, T-5260–T-5265, T-5266–T-5269.

Принадлежность §13A/§13B лейну **B3 — подтверждена** (единый домен «Модули→Сон»/memory-observability, общие файлы `memory_agi.py`/`app.js`; пересечений с B1/B2 нет).

---

## §5. Δ-инварианты и пороги СТОП (Q8, D17)

| Инвариант | Базлайн | Ожидаемое Δ | Граница / СТОП |
|---|---|---|---|
| **DDL (schema version)** | v33 | **0** — v33 не растёт; final policy = stage-row `summary_run_stages`; состояния = словарь статусов; migration jobs = `task_jobs`; canary = `embedding_cache`; синтетика `/api/config` = деривация | v34 / любая миграция без отдельного решения @Architect → **СТОП**; предсанкционированный путь один (D12, аддитивная v34 + эскалация) |
| **Каталог (F8)** | 523 | **+4…+8**: только `models.embedding_fallback{1,2}_{base_url,model,quota_group}` (ожидаемо +6) | ключ вне списка, KS-ключи, Δ > +8 → **СТОП**; F8-переиздание meta-pin обязателен при Δ≠0 |
| **Kill-switches** | 85 | **0** | новый KS → **СТОП**/эскалация |
| **reason_code** | 280 | **0**; допустимо ровно 2 именованных: `l2_unusable_gate` (D3), `l2_stagnation_fingerprint` (D4) | любой другой новый/удалённый код → **СТОП**; Δ > +2 → **СТОП** |
| **Тулы (METERED_TOOLS)** | 14 | **0** (14 = 14) | Δ ≠ 0 → **СТОП** |
| **Реестр процессов / widget-ID** | 47 | **0** (47 = 47; новые карточки — settings-виджеты, не process registry) | Δ ≠ 0 → **СТОП** |
| **Routes (эндпоинты)** | без Δ | **0 новых эндпоинтов** (манифест/трейс/rebuild-status/paradigms — расширения существующих API); `routes.py` трогает только B3-config-region | новый эндпоинт, правка routes.py вне region → **СТОП**; `ROUTES_SHA256_F11` re-pin ровно ×1 на пакете (T-5270) |
| **JS-базлайн** | 62/62 | ≥62 зелёных (новый базлайн фиксируется при добавлении) | падения без разбора до Review → **СТОП** |
| **py-suite** | 12359/5 (4 pre-existing identity + dream_worker-флейк) | 0 новых red | новый red → **СТОП** до Review |

Любое расхождение факт↔санкция без решения @Architect, секрет в артефакте, имитация живой проверки, fail2ban-нарушение → **СТОП + возврат Step 2**.

---

## §6. Верификация — REQ→SC (прогрессивное доказательство)

| REQ | SC (приёмка) |
|---|---|
| R1 | любой failed run объясняется из Inspector без server log: 5 секций трассы + final policy + одна причина (D6); §16#11; visual 15E#1 |
| R2 | L1 degraded ≠ красный крест; Writer от полного окна виден; §16#1–2 |
| R3 | таксономия D2 в коде (все 15 кодов классифицированы); unknown ≠ blocking; §16#3–6 |
| R4 | progress по fingerprint; §16#7–9; число ревизионных LLM-циклов не выросло |
| R5 | 4 случая Legacy §4.1 исчерпывают LEGACY_FALLBACK; soft-only → degraded publish; §16#4/#10 |
| R6 | T-5248: 5 controlled real-provider прогонов со стабильным policy и 0 необъяснимых `l2_unusable`; затем 1 live (T-5274) |
| R7 | факты RCA C1–C4 устранены; манифест показывает реальность dataflow; §16#12–16 |
| R8 | один CoverPromptManifest для 3 UI; персист sent prompt admin-only; §16#17–18, #20 |
| R9 | Base = STORY+CONTEXT+STYLE со story-minimum; §16#12 |
| R10 | Style Edit: minimums при retry, без minimal=True; §16#13–16 |
| R11 | §10A.2 (6 пунктов) + Prompt Assembly-таблица; draft-честность; visual 15E#2/#3 |
| R12 | Analytics: Base и Style раздельно, attempts 1/2, обе строки admin; §16#17–20; visual 15E#4 |
| R13 | §12 чек-листы Base/Styled + visual live canary (T-5274) |
| R14 | §16#21–25; `graph_facts_vec` → active ИЛИ точный durable blocker виден; «N/M» в Analytics |
| R15 | 13N#1–2; credentials не потеряны при миграции |
| R16 | 13N#3–6; same dim + diff model → REINDEX_REQUIRED; UNKNOWN fail-safe |
| R17лок | 13N#7–16, #25–28; atomic promote/rollback; snapshot+delta |
| R18 | 13N#7–9, #15–17, #24; safe default pinned; impact до сохранения |
| R19 | 13N#19–22; запрет cross-space одним embedding |
| R20 | 13N#23–24; ✅/🟡/🔴/⚪; quota человеческим языком; visual 15E#9–13 |
| R21 | 13N 28/28 + 13O (17 чекбоксов) |
| R22 | §16#34–36; config-state ≠ runtime failure; без fake provider/key |
| R23 | 14A.4 п.1–8: карточка видна до настройки и после рестарта; visual 15E#7/#8 |
| R24 | 14A.4 п.9–11 + Scanner T-5272 (plaintext 0 hits) |
| R25 | 13A.4 (8 чекбоксов); controlled manual deep run; visual 15E#6 |
| R26 | 13B.4: nodes/edges до=после; нет стены текста; visual 15E#5 |
| R27 | 15F все чекбоксы; T-5266 свод; evidence §15D |
| R28 | реестр D19 (61 позиция) зелёный; T-5267–T-5270 |
| R29 | §19: 17 пунктов human language first; финал = observable production behavior |
| R30 | §4/§5 соблюдены; сериализация; RCA-first (выполнено — §1) |

---

## §7. Failure/fallback семантика (сводка)

- **Summary:** L1 degraded → Writer от полного окна (не терминально); unusable без evidence → needs_fixes; soft-only → HYBRID_DEGRADED_PUBLISHED; hard unresolved → LEGACY_FALLBACK с точной причиной; reviewer outage → degraded publish (как сейчас).
- **Cover:** unknown limit → semantic squeeze с story-minimum (обе attempts в манифесте); provider fail → существующая error-семантика job'а, без новых ретраев (>1 запрещено).
- **GraphRAG:** healthy building → FTS-only + «N/M» + warning ×1; stale → один bounded resume; провайдер недоступен → visible `paused_rate_limit` + next_allowed_at, future-resume тиком; FTS остаётся.
- **Random:** quantum без ключа → честный `provider_unconfigured` + карточка подключения; явный pseudorandom → без WARN; transition ×1 на state-key.
- **Embeddings:** UNKNOWN/несовместимость → не писать в active, FTS/compatible fallback, blocker виден; old provider умер во время rebuild → raw memory сохраняется, target догоняет delta.

## §8. Совместимость/миграция/откат

Δ DDL = 0 (база); при активации пути D12 — одна аддитивная v34 (nullable, PG no-op, повторный no-op, старый код колонки не читает). Credentials embedding-профилей мигрируют in-place без потери. Rollback: soft (config/KS; reason-коды аддитивны) / cold (git revert; БД совместима в обе стороны при v33 и при аддитивной v34). Каноны гайдов/MCA-каналы не затрагиваются.

## §9. Риски

- **Risk R2 (ратифицирован, Q10):** multi-domain corrective фича: 3 параллельных лейна, publish-path (Summary) и memory-path (embeddings) меняются одновременно; schema-дельта ожидаемо 0, config/catalog-дельта > 0; ошибки политики Summary видны на живых публикациях → компенсация: D19 live-приёмки + §5 пороги + INV-1 fail-closed.
- R-наблюдение (не гейт): рестарты прода ~1.3 ч — операционный фон; D10 спроектирован рестарто-устойчивым (durable tick, не in-process sleep).

## §10. Ответы на открытые вопросы Q1–Q13 (requirements-map §5)

- **Q1 unusable-threshold:** D3 — ≥2 независимых валидных HARD (разные коды И разные targets) ИЛИ deterministic proof; иначе даунгрейд до needs_fixes с трейсом. База: прод 8/8 `l2_unusable`, §4.3 делегирование.
- **Q2 hard/soft-таксономия:** D2 — FINDING_CODE_TAXONOMY, все 15 кодов, promote только через deterministic proof, demote запрещён, can_force_legacy только у hard; unknown-код → dropped_invalid.
- **Q3 fingerprint-формат:** D4 — `code+paragraph_id+sorted(evidence_refs)+target`; прогресс = prev−curr ≠ ∅; stagnation = набор сохранился/doc не изменился/тот же deterministic mechanism.
- **Q4 CoverPromptManifest:** D7 — имя `CoverPromptManifest`; персист JSON в существующем job/run evidence; retention = evidence retention; hash sha256[:16]; attempts[]; admin-only чтение существующими API.
- **Q5 semantic squeeze:** D9 — порядок §9, story ≥160 chars (или 100%), profile ≥50%, refs mandatory; limit_source ∈ {capability_registry, last_success, unknown}; при unknown честный unknown без числового лимита; retry ≤1.
- **Q6 embedding identity + canary:** D11 — canonical JSON → sha256[:16]; canary = 3 фиксированные строки, вектора в существующем `embedding_cache`, сверка косинусом (mean<0.98/min<0.95 → drift); UNKNOWN → fail-safe без writes.
- **Q7 storage при смене размерности:** D12 — generation-isolated vec-таблицы через существующий shadow/swap `_activate`; registry = pointer; retention/GC; destructive ALTER запрещён; единственный unknown (механизм создания vec-таблиц) — entry-check с предсанкционированной аддитивной v34 + эскалацией.
- **Q8 Δ-инварианты и пороги:** §5 — DDL 0 (v33), каталог +4…+8 (список фиксирован), KS 0, reason 0..+2 (именованные), тулы/widget 0, routes 0 (F11 re-pin ×1), js/py без новых red.
- **Q9 parent Builder / shared-файлы:** §4 SERIALIZE-1…5 — `summary_generator.py` (B2-extraction первой), `app.js`/`index.html` (секции, порядок B1→B2→B3), `routes.py` (одна region), `mca_events.py`, `settings.py` (parent: bump).
- **Q10 Risk/деплой:** R2 ратифицирован (§9); деплой одним окном после T-5270, bump 2.58.67→2.58.68, smoke при Δ DDL≠0, rollback soft/cold (§8).
- **Q11 парадигмы retry:** D14 — классы A/B/C с bounded caps (B: 1 ч ×2, ≤2/сутки; C: 2 ч, ≤6/сутки), manual run обходит cooldown, защита от LLM-спама сохранена.
- **Q12 гэп нумерации §16:** D19 — #26–33 зарезервированы, покрыты 13N#1–28; финальный реестр 33+28=61 позиция; не перенумеровывать.
- **Q13 принадлежность §13A/§13B:** B3 — подтверждено (§4); финальные write-scope трёх лейн — §4.

## §11. Non-goals (вне скоупа ASAP 5)

- Coverage=0 на legacy-путях витрины (RCA п.10.1) — отдельный backlog-пункт для Orchestrator/PM, не в лейне B1 (bounded slice).
- Drill-down Decision Trace из БД по trace_id (RCA п.10.3) — телеметрия не расширяется.
- Cross-chat semantic search UI (13I — только инварианты/запреты, самого продукта нет).
- Vision/deep-sleep RED-строки owner-gate — вне кодового скоупа (кроме D14-диагностики).
- Перезапись Summary/Cover/GraphRAG целиком, «just disable Reviewer», «just increase retries», все-findings-soft (§18 — поимённо для Reviewer T-5271).
