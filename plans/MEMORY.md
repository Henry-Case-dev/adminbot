# AdminBot — Memory Index (plans/MEMORY.md)

Индекс долговременной памяти. Архитектура — `plans/ARCHITECTURE.md` (§1–§73);
бэклог — `plans/backlog.md`. Полная семантическая карта — knowledge graph
(Memory MCP, entity `AdminBot` + модули `adminbot-*` + entity `feature-*`
раунда 10).

> **✅ S7 ЭПИКА 2 (Шаг 10 @Memory, 24.09.2026; Merge §78; deploy VERIFIED): `summary-logging-runid-round1026` (§108–§110) — COMPLETED + MERGED (§78, T-3406 @Architect) + ARCHIVED (T-3407 @PM, Шаг 8, 24.09.2026) + DEPLOYED (T-3408 @DevOps, **2.58.26 VERIFIED**; `5cba5df` код+тесты / `aa42a04` планы/миграция + `1684da9`/`4c22e2c` deploy-doc; прод ff `59e5b12..aa42a04`, active MainPID **522392**, health 200, `database is locked`=0; откат annotated-тег `pre-round1026-s7` → `f774ecc` + `git revert`; `deployment.md` VERIFIED); Approved **единым Reviewer gate** (Scanner удалён намеренно 24.09.2026 — обязанности в Reviewer; отдельного Scanner-approval нет); архив — `plans/archive/summary-logging-runid-round1026/` (T-3407 @PM — ✅ выполнен 24.09.2026; 6 файлов, SHA-256 до/после идентичны); live — ⏳ PENDING OWNER VERIFICATION; следующий — **S8 `summary-analytics-adapter`** (§111/§112; зависит от S7 ✅ и S6 ⛔ BLOCKED/D4).** Историческая запись (Step 1 @PM + Step 2 @Architect + Step 3 @Memory, 24.09.2026): `tasks.md` (T-3380…T-3409) + `spec.md` (REQ-S7-01…-13, SC-01…SC-16) + **ADR-1026-9** (`adr-1026-9-summary-runid-logging-logviewer.md`, D1–D8, Accepted) + KG-узел `ADR-1026-9-summary-runid-logging-logviewer`. Baseline HEAD `59e5b12`, `APP_VERSION` 2.58.25, pytest `.venv` 8854/0, JS 44/44, каталог 469/426/444/100/98/21, Δ DDL=0.** Суть: сквозной `run_id` = существующий `correlation_id` (D1; одна точка на прогон — `summary_generator.py:348`/dry-run `summary_test_run.py:495`; проброс параметром S1→S2→L1→пакет→L2→форматтер→обложка; второй id не вводится); каталог §108/§109 — аддитивные `SUMMARY_START/COMPLETE/FAILED`, `FORMAT_START/COMPLETE` (+`run_id/reason` в `FORMAT_ERROR`), `COVER_START/COMPLETE/ERROR` + reuse `FILTER_*`/`RESTORE_*`/`L1_*`/`L2_*`/`TEST_*`; **`PUBLISH_RICH_*`/`PUBLISH_TEXT_*` — GATED (S6/D4), не реализуются** (D2). **Δ DDL=0** — ring-buffer+файлы, токены/стоимость из `llm_usage_events` по `run_id`, контекст in-memory (D3). §110 — клиентский фильтр-чип «Саммари» в существующем log viewer (`web/app.js:9457–9607`), без нового endpoint и без diff `routes.py`, раскрытие/копирование сохранены (D4). Dry-run S9 — 0/0/0 + тот же `run_id`, `TEST_*` без `SUMMARY_*`/`PUBLISH_*` (D5). Fail-closed `*_ERROR`+`SUMMARY_FAILED`, helper-поля §109, лог-стор best-effort, R17 (D6). **Δ каталога=0** (F8 не переиздаётся — ADR-1026-2 не запускается), CSP/zero-build, 2-вызовность, §104/обложка/XML не тронуты; «OFF байт-в-байт» = неизменны поведение/артефакты, аддитивные лог-строки разрешены (§108) (D7). **Deploy=ДА, bump 2.58.25→2.58.26**, hot-OFF не нужен, откат annotated-тег `pre-round1026-s7` → `f774ecc` (D8). KG: `S7 summary-logging-runid` → ADR-1026-9 (`specified-by`); ADR-1026-9 → ADR-1026-5/-6/-7/-8/-1/-4 (`reuses`), → ADR-1025-24 (`governed-by`), → ADR-1026-2 (`does-not-trigger`). Код НЕ менялся (только `plans/**` + KG). **Итог (24.09.2026): build B–F + rework ×2 ✅ → Reviewer (единый gate): линза 1 T-3403 — итер.1 Changes requested (**B-R1026S7-1**) → итер.2 Changes requested (**B-R1026S7-2** Medium, §109/SC-07) → итер.3 **Approved** (C0/H0/M0); линза 2 T-3404 (focused change audit + миграция) — **Approved** (C0/H0, блокирующих 0); binding: Reviewed-Commit `f774ecc`, Working-Tree-Hash `6c7c9061…`, Spec-Hash `d9d11797…` → Merge **§78** (T-3406) → deploy **2.58.26 VERIFIED** (T-3408). Числа: pytest `.venv` **8890/0** (+36; S7-файл **35/35**), JS **45/45**; `git diff --check`=0; **Δ DDL=0**; **Δ каталога=0** (469/426/444/100/98/21; F8 не переиздаётся); 2-вызовность (`await_count==2`), dry-run 0/0/0, R17-пины; `PUBLISH_*` GATED (S6/D4) — в коде отсутствуют. Техдолг — **§78.7** (L-R1026S7-1 Low — pre-existing, вне diff → S8/хотфикс; L-R1026S7-2/-3 закрыты; follow-up S9 → S7/S8: L-R1026S9-8 устранён в S7, остальное — S8). Гейты: **S6/S10 GATED** до live-приёмки Эпика 1 (ADR-1025-24 D4); live S1–S5/S9/S7 и Эпика 1 — ⏳ PENDING OWNER VERIFICATION.**

> **✅ S9 ЭПИКА 2 (Шаг 10 @Memory, 24.09.2026; Merge §77; deploy VERIFIED): `summary-testing-ui-round1026` (§113 + §112) — COMPLETED + MERGED (§77) + ARCHIVED + DEPLOYED (`ac3f8fc` код+тесты / `59e5b12` планы/архив, `APP_VERSION` 2.58.24 → **2.58.25**, health 200 `version 2.58.25`, `database is locked`=0, `TEST_*`/`L2_*`/`FORMAT_*`=0, каталог 469; откат annotated-тег `pre-round1026-s9` → `cc6105c`; hot-OFF `SUMMARY_TEST_UI_ENABLED=false`); live — ⏳ PENDING OWNER VERIFICATION; следующий — **S7 `summary-logging-runid`** (§108–§110; **S6 — ⛔ BLOCKED/D4**).** Автономный контур: @Reviewer итер.1 **Changes requested** (2 блокера: **B-R1026S9-2** High — краш вкладки на error-путях; **B-R1026S9-1** Medium — §112 «Процент отсева») → итер.2 **Approved** C0/H0; @Scanner итер.2 **C0/H0/блокирующих 0/L5/I2 → «к деплою ДА»** (`plans/reports/round1026_s9_scanner_audit.md`); rework **1**. Числа: pytest `.venv` **8854/0** (**+47**), JS **44/44**; **Δ DDL=0**; **Δ каталога=0** (F8 не переиздаётся — ADR-1026-2 «не требуется»). Архив — `plans/archive/summary-testing-ui-round1026/` (`spec.md` + **ADR-1026-8** (D1–D8, Accepted фактом §77) + `tasks.md` + `evidence.md` + `review.md` + `README.md`). Техдолг — **§77.6** (L-R1026S9-2/-6/-7/-8 + S-R1026S9-5 + I-R1026S9-1/-2 → S7/S8). Историческая запись (Step 1/2/3, IN PROGRESS): `summary-testing-ui-round1026` (§113 + §112) — `tasks.md` (T-3345…T-3379, 35; блоки 0/A–H) + `spec.md` (REQ-S9-01…-15, SC-01…SC-15) + **ADR-1026-8** (`adr-1026-8-summary-test-run-dry-run-ui.md`, D1–D8, **Accepted**; формально — фактом мержа §77 / T-3376) + сверка @PM T-3347 ✅; KG-узел `ADR-1026-8-summary-test-run-dry-run-ui`. Baseline HEAD `cc6105c` == `origin/master`, `APP_VERSION` **2.58.24**, pytest `.venv` 8807/0, JS 43/43, каталог 469/426/444/100/98/21, Δ DDL=0.** Суть: первый **dry-run** потребитель S1–S5 — новый `services/summary_test_run.py` (**0 публикаций / 0 памяти / 0 `generate_image`**; ON-путь `L1→пакет→L2` включается **per-run** прямыми `run_l1`/`run_l2`, ровно **2 LLM-вызова**, глобальный `SUMMARY_HYBRID_L2_ENABLED`/per-chat override не читаются и не меняются; окно — read-only `db.get_smart_window`; доказательство — шпионы + `await_count==2`) + additive `SummaryGenerator.build_test_rows` + новый роутер `web/api/summary_test.py` (async job + polling, in-memory store TTL 15 мин/≤20, **без DDL**, `requires_global_admin`, rate-limit; `routes.py` вне diff) + UI-вкладка «Тестирование» `#/modules/summary/testing` (tab-id уже есть → **Δ каталога=0**; команда не вводится). Предпросмотр §113 (исходные→фильтр→L1→пакет→L2→Rich+plain) + метрики §112 («Нет данных» вместо $0, «Без лимита», публикация «не публиковалось»); двухшаговая обложка (существующий `generate_image_verbose`, 0 LLM, §104 не тронут); fail-closed §106 коды `TEST_*`; границы S6 — **GATED** (не вызывается), `run_id`→S7, ExecutionGraph→S8, §85 вне S9; **Δ DDL=0**; **Δ каталога=0** (F8 не переиздаётся — ADR-1026-2 «не требуется»); CSP/zero-build; R17/R18. **Deploy=ДА, bump 2.58.24 → 2.58.25**; hot-OFF `SUMMARY_TEST_UI_ENABLED=false`; откат annotated-тег `pre-round1026-s9` → `cc6105c`. **▶️ Следующий — baseline @DevOps (T-3345) → Step 4 @Builder (блоки B–F) → H; метрики S9 — Шаг 10.** **S6 `summary-publish-integration` — ⛔ BLOCKED (гейт D4/ADR-1025-24).**
>
> **✅ S5 ЭПИКА 2 (Шаг 10 @Memory, 23.09.2026; Merge §76; deploy VERIFIED): `summary-l2-writer-formatter-round1026` (§97–§103) — COMPLETED + MERGED (§76) + ARCHIVED + DEPLOYED (`03a4d55` код+тесты+канон / `ae5a147` планы/архив, `APP_VERSION` 2.58.23 → **2.58.24**, health 200, `database is locked`=0, `L2_*`=0 / `FORMAT_*`=0 — флаг OFF, ON-врезка GATED, каталог 469; откат annotated-тег `pre-round1026-s5` → `e3ea608`); live — ⏳ PENDING OWNER VERIFICATION (D4); следующий — **S9 `summary-testing-ui`** (§113; **S6 — ⛔ BLOCKED/D4**).** Автономный контур: @Reviewer итер.1 **Changes requested** (блокер **B-R1026S5-1** — порча тестовой фикстуры F8) → итер.2 **Approved** (C0/H0; 4 Low `L-R1026S5-3..-6` неблокирующие); @Scanner итер.2 **C0/H0/блокирующих Medium 0/L4/I2 → «к деплою ДА»** (`plans/reports/round1026_s5_scanner_audit.md`); rework **1**. Числа: pytest `.venv` **8807/0** (**+70** = 64 + 6 rework; L2/форматтер 70), JS **43/43**; **Δ DDL=0**; **Δ каталога=+1** — санкция ADR-1026-7 D3 (промпт-ключ L2; REGISTRY **469**/Settings 426/categorized **444**; F8 переиздан, delta **58**). Архив — `plans/archive/summary-l2-writer-formatter-round1026/` (`spec.md` + **ADR-1026-7** (D1–D7, Accepted фактом §76) + `tasks.md` + `evidence.md` + `review.md` + `README.md`). Техдолг — **§76.6**; ON-путь — GATED (включение — после live-приёмки Эпика 1). Суть: L2 «Писатель» `services/summary_l2_writer.py` (**1 вызов** `step="l2_writer"`; вход — контент `FactPackage` §96, выход — документ §99) + серверный форматтер `services/summary_article_formatter.py` (**0 LLM**; rich `<h1>`+`<p>`/≤1 `<b>`, plain `<b>`-заголовок; лимиты 200/`max_summary_parts`/32 000); kill-switch `SUMMARY_HYBRID_L2_ENABLED` (default OFF) + `_chat_limit`: OFF байт-в-байт, ON = `L1→пакет→L2` ровно 2 вызова.
>
> **🗂️ S5 ЭПИКА 2 (исторический Step 1 @PM + Step 2 @Architect + Step 3 @Memory, 23.09.2026 — итог см. баннер выше): `summary-l2-writer-formatter-round1026` (§97–§103) — `tasks.md` (T-3308…T-3344, 37) + `spec.md` (REQ-S5-01…-18, SC-01…SC-09) + **ADR-1026-7** (`adr-1026-7-l2-writer-article-formatter.md`, D1–D7, **Accepted**); KG-узел `ADR-1026-7-l2-writer-article-formatter`. Baseline HEAD `7722d66` == `origin/master`, `APP_VERSION` **2.58.23**, pytest `.venv` 8737/0, JS 43/43, каталог 468/426/443/100/98/21, Δ DDL=0.** Суть: L2 «Писатель» — новый `services/summary_l2_writer.py` (вход — контент-секция `FactPackage` §96 без `service`/сырого лога; выход — структурированный документ §99 `{schema_version,title,paragraphs[{text,emphasis}]}`; **ровно 1 вызов** `step="l2_writer"`; анти-цитаты: промпт + пост-валидация, именованная атрибуция → `quote_attribution` fail-closed) + детерминированный серверный форматтер `services/summary_article_formatter.py` (**0 LLM**: rich `<h1>`+`<p>`+≤1 `<b>`, plain `<b>`-заголовок; §98/§101/§102/§105; `content_format="html"`; лимиты title ≤200 / абзацев ≤ `limits.max_summary_parts` / rich ≤32 000). Врезка за kill-switch `SUMMARY_HYBRID_L2_ENABLED` (env-only, **default OFF**) + `_chat_limit`: OFF = прежний `_generate_two_call` **байт-в-байт**, ON = `L1→пакет→L2` **ровно 2 вызова** (в S5 — на моках, `await_count==2`; реальный ON — гейт S6/S10+D4, не раньше live-приёмки Эпика 1). Слот §82: модель/провайдер/ключ — env-only `SUMMARY_L2_*` (**Δ каталога=0**); промпт — **каталог +1 (санкция)** `prompts.summary_l2_writer_system_prompt` (F8 переиздаётся по ADR-1026-2; REGISTRY 468→469, categorized 443→444; Settings/GROUPS/`_TAB_BY_GROUP`/TAB_RULES без изменений); канон L2 `PREV_SUMMARY_L2_WRITER_R1026`+`PROMPT_MIGRATIONS`/ROLLBACK+эталон атомарно (ADR-1013-3); `SUMMARY_NARRATOR_SYSTEM_PROMPT`/Редактор/`digest`/`system2_handoff` — REUSE (не удалять, OFF/откат). AMEND **ADR-1022-4** (состав Stage-2), **ADR-1023-3/-6** (семантика/формат L2-пути) — effective S5; REUSE ADR-1026-5/-6/ADR-1026-1/-2/-4; governed-by ADR-1025-24 D4. **Δ DDL=0**; §104/`generate_image`/обложка/XML/`web/**` не тронуты; **deploy=ДА, bump 2.58.23→2.58.24**; откат annotated-тег `pre-round1026-s5` → `7722d66` (hot-OFF `flags.summary_hybrid_l2_enabled=false`). Follow-up S3/S4 (`L-R1026S3-1/-2/-3`, `R-R1026S3-1/-2`, `L-R1026S4-1/-2/-3`, `I-R1026S4-1/-2`) закрываются в S5. **▶️ Следующий шаг — baseline @DevOps (T-3308) → Step 4 @Builder**; порядок: S1→S2→S3→S4 (все DEPLOYED) → **S5** → [S6 ∥ S9] → S7 → S8 → S10. Метрики S5 — Шаг 10 (в `plans/metrics.md` строки S5 ещё нет — не инвентаризировать). Live S1–S4 и Эпик 1 — ⏳ PENDING OWNER VERIFICATION.
>
> **✅ S4 ЭПИКА 2 (Шаг 10 @Memory, 23.09.2026; Merge §75; deploy VERIFIED): `summary-fact-package-round1026` (§96) — COMPLETED + MERGED (§75) + ARCHIVED + DEPLOYED (`08219ab` код+тесты / `7722d66` планы/архив, `APP_VERSION` 2.58.22 → **2.58.23**, health 200, `database is locked`=0, `FACT_PACKAGE_*`=0 — модуль не врезан; откат annotated-тег `pre-round1026-s4` → `59f5921`); live — ⏳ PENDING OWNER VERIFICATION (D4); врезка L1→пакет→L2 — **GATED (S5/S6)**; следующий — **S5 `summary-l2-writer-formatter`** (§97–§103).** Merge — `plans/ARCHITECTURE.md` **§75** (@Architect, T-3303); архив — **`plans/archive/summary-fact-package-round1026/`** (`spec.md` + **ADR-1026-6** (D1–D6, Accepted фактом мержа §75) + `tasks.md` (T-3283…T-3307) + `evidence.md` + `review.md` + `README.md`; содержимое/чекбоксы сохранены, UTF-8). Суть: детерминированный «пакет фактов» §96 между L1 (§95/S3) и L2 (§97–§99/S5) — `services/summary_fact_package.py` (694 стр., **0 LLM-вызовов**, чистый: без БД/сети/часов), `description` = агрегация `facts[].text`, `chronology` = ASC `(timestamp,message_id)` из §92, `service{response_mode,cover_prompt}` транзитом, бюджет через существующие `limits.summary_max_context_*` (**Δ каталога=0**, F8 не переиздавался), fail-closed `ok/truncated/empty/invalid/error/not_built`, TG `message_id` без фабрикации, логи `FACT_PACKAGE_*`. @Reviewer **Approved** (1 итер., C0/H0; 3 Low `L-R1026S4-1..3`), @Scanner **C0/H0/M1(процесс, закрыт `review.md`)/L2/I2 → «к деплою ДА»** (`plans/reports/round1026_s4_scanner_audit.md`). Числа: pytest `.venv` **8737/0** (+52; S4 52), JS **43/43**; **Δ DDL=0**, **Δ каталога=0** (468/426/443/100/98/21), 0 LLM-вызовов, живой путь вне diff. Техдолг — **§75.7** (L-R1026S4-1/-2/-3, I-R1026S4-1/-2 → S5). Deploy — ✅ **VERIFIED** (Шаг 9 @DevOps, T-3305: прод ff `3ccb1bb..7722d66`, active MainPID 425178, health 200, served `?v=2.58.23`, locked=0, `FACT_PACKAGE_*`=0). KG: `S4 summary-fact-package` → **DEPLOYED** (`release-round1026-s4`, 2.58.23, `7722d66`); `ADR-1026-6` → **Accepted** (MERGED §75); созданы `release-round1026-s4` + `metric-snapshot-round1026-s4-final` + `tech-debt-round10.26-s4`.
>
> **🗂️ S4 ЭПИКА 2 (исторический Step 1 @PM + Step 2 @Architect + Step 3 @Memory, 23.09.2026 — итог см. баннер выше): `summary-fact-package-round1026` (§96) — Step 0–3 ✅; ADR-1026-6 Accepted; врезка GATED (S5/S6); deploy = ДА (bump 2.58.22 → 2.58.23).** Артефакты — `plans/features/summary-fact-package-round1026/` (`tasks.md` + `spec.md` + **`adr-1026-6-fact-package-contract-deterministic-s5.md`**). Суть: детерминированный «пакет фактов» §96 между L1 (§95/S3) и L2 (§97–§99/S5) — новый чистый модуль `services/summary_fact_package.py`, топ-уровень `{schema_version, status, threads[], unassigned_message_ids[], service{response_mode, cover_prompt}, budget{kind,limit,estimated,fits}}`, тема `{thread_id, name, description, chronology[], facts[], evidence_ids[], fragments[]}`; `name` = `topic` verbatim, **`description` = детерминированная агрегация `facts[].text`** (дедуп/кап; без LLM/прозы), **`chronology` = ASC `(timestamp,message_id)`** из §92-payload, **третий LLM-вызов исключён**. Бюджет L2-входа — переиспользование существующих `limits.summary_max_context_tokens`/`_chars` (`resolve_chat_limit`, default 30000) → **Δ каталога = 0**, новых env нет; усечение: фрагменты (старые первыми) → `description` → целые темы (факты/evidence не режутся частично), `truncated`+`skipped_ids`+WARN, ноль тем → `empty` → L2 не вызывается. `cover_prompt`/`response_mode` — транзит в секцию `service` (вне L2-контента; §104/обложка не меняются). Fail-closed: `ok→ok`; `truncated→truncated`+проброс; `empty/invalid/error → threads=[]` и **в L2 не передаётся** (§95/§106); нет usable → `not_built`; ID — TG `message_id` (DB `id` только в логах), висячие/фабрикованные → `invalid`, `evidence_ids ⊆ message_ids`, двойной прогон байт-идентичен. **0 LLM-вызовов; Δ DDL = 0; Δ каталога = 0** (F8 не переиздаётся); CSP/zero-build; R17/R18; врезка — GATED (S5/S6; гейт S6/S10 + D4/ADR-1025-24). Интерфейс для S5 — `build_fact_package(l1_result, payload_items, *, budget=None) -> FactPackageResult`; `run_id` → S7, ExecutionGraph → S8, §113 → S9. KG: `ADR-1026-6-fact-package-contract-deterministic-s5` (Accepted) + связи (`specified-by` от S4; `reuses` ADR-1026-5/ADR-1022-4/ADR-1023-3/-6/ADR-1013-3; `governed-by` ADR-1025-24; `decides` SpecDecision — RESOLVED; `mitigates` 4 Risk). Код НЕ менялся (только `plans/**` + KG). **▶️ Следующий шаг — baseline @DevOps (annotated-тег `pre-round1026-s4` → `59f5921`) → Step 4 @Builder (S4)** → S5. Гейты: S6/S10 — 🔒 закрыт (ADR-1025-24 D4); live-гейты (Эпик 1, S1/S2/S3) — ⏳ PENDING OWNER VERIFICATION.
>
> **✅ S3 ЭПИКА 2 (Шаг 10 @Memory, 23.09.2026; Merge §74; deploy VERIFIED): `summary-l1-clusterizer-round1026` — COMPLETED + MERGED (§74) + ARCHIVED + DEPLOYED (`b31c2a6`/`3ccb1bb`, `APP_VERSION` 2.58.21 → **2.58.22**, health 200, `database is locked`=0, `L1_*`=0 — модуль не врезан); live — ⏳ PENDING OWNER VERIFICATION (D4); следующий — **S4 `summary-fact-package`** (§96).** Merge — `plans/ARCHITECTURE.md` **§74** (@Architect, T-3278); архив — **`plans/archive/summary-l1-clusterizer-round1026/`** (`spec.md` + **ADR-1026-5** (D1–D6, Accepted фактом мержа §74) + `tasks.md` + `evidence.md` + `review.md` + `README.md`; содержимое/чекбоксы сохранены, UTF-8; **T-3253…T-3282, 30**; закрыты T-3253…T-3282, в т.ч. **T-3280** deploy ✅ VERIFIED и **T-3281** метрики ✅ Шаг 10; T-3273 — **DEFERRED** (врезка → S5/S6), T-3274 → S9). Суть: L1 «Кластеризатор» (§81/§94–§95, этап между S2-восстановлением и пакетом фактов §96) — контракт `services/summary_l1_contract.py` (строгая JSON-схема §95, лимиты 100/30/1000/200/500, канонизация/дедуп/ASC, ID-пространства DB `id`↔TG `message_id`, fail-closed `L1Result{ok|empty|invalid|truncated|error}`; невалидный JSON не идёт в L2) + ядро `services/summary_l1_clusterizer.py` (**ровно 1 вызов**, `generate(step="l1_clusterizer")`/dedicated `_post`, §93-фрагменты — один вход, chunk-merge BLOCKED, `truncated`+`skipped_ids`+WARN) + канон `SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT` (+`PREV_*`/миграция/ROLLBACK/эталон) + env-only слот `SUMMARY_L1_*` (§82) + логи `L1_*`; **врезка L1 — DEFERRED** (не раньше S5/S6; гейт S6/S10+D4); `cover_prompt`/`response_mode` — служебные поля того же JSON (AMEND ADR-1023-3/-6, effective S5); AMEND ADR-1022-4. @Reviewer **Approved** (T-3275, 1 итер., C0/H0; 3 Low `L-R1026S3-1..3`), @Scanner **C0/H0/M1(процесс, закрыт ревью)/L3/I5 → «к деплою ДА»** (T-3276; `plans/reports/round1026_s3_scanner_audit.md`). Числа: pytest `.venv` **8685/0** (+116; S3 116), JS **43/43**; **Δ DDL=0**, **Δ каталога=+1** — санкция ADR-1026-5 D4 (**468**/426/**443**/100/98/21; F8 переиздан, delta **57**); `SUMMARY_L1_*` env-only; публикация/XML/`summary_generator.py` вне diff; ровно 2 LLM-вызова; CSP/zero-build. Deploy — ✅ **VERIFIED** (Шаг 9 @DevOps, T-3280: прод ff `989ff8d..3ccb1bb`, active MainPID 413635, `/api/health` **200**, served `?v=2.58.22`, `L1_*`=0, каталог рантайм 468; deploy-doc — секция T-3280 в `evidence.md`, вне коммита). Техдолг — **§74.6** (L-R1026S3-1/-2/-3 + R-R1026S3-1/-2 → S5 + Info 1–5). Откат — тег `pre-round1026-s3` → `4007081`; канон-откат — ROLLBACK; `stash@{0}` (R18). KG: `release-round1026-s3` + `metric-snapshot-round1026-s3-final` + `tech-debt-round10.26-s3`. R17/R18: `plans/current_task.md` не изменялся; Шаг 10 — только `plans/**` + KG (не коммичено).
>
> **✅ S2 ЭПИКА 2 (Шаг 10 @Memory, 23.09.2026; Merge §73; deploy VERIFIED): `summary-context-restore-round1026` — COMPLETED + MERGED (§73) + ARCHIVED; deploy — ✅ VERIFIED (Шаг 9 @DevOps, T-3250; `eda7325`/`6fa456c`/`989ff8d`, `APP_VERSION` 2.58.20 → **2.58.21**, health 200, `database is locked`=0); live — ⏳ PENDING OWNER VERIFICATION (D4); следующий — **S3 `summary-l1-clusterizer`** (§94–§95).** Merge — `plans/ARCHITECTURE.md` **§73** (@Architect, T-3248); архив — **`plans/archive/summary-context-restore-round1026/`** (`spec.md` + **ADR-1026-4** (D1–D7, Accepted фактом мержа §73) + `tasks.md` + `evidence.md` + `review.md`; содержимое/чекбоксы сохранены, UTF-8; **T-3224…T-3252, 29**; закрыты T-3224…T-3252 (в т.ч. **T-3250** deploy ✅ VERIFIED и **T-3251** метрики ✅ Шаг 10); блок H/T-3244 — **NOT_APPLICABLE**). Суть: детерминированное восстановление контекста входа L1 (этап «Восстановление контекста» §80, между S1-фильтром и XML) — чистое ядро `services/summary_context_restore.py` (`restore_context`→`RestoreResult`, `build_l1_payload` §92, `RESTORE_CHAIN_DEPTH=10`; 0 LLM-вызовов) + async-адаптер в `services/summary_generator._apply_filter` (`_restore`/`_collect_extra_parents`, reuse `services/thread_chain.collect_thread_chain`): транзитивные reply-родители (пример §90 `100→101→102`, сквозь бот-ответы), ограниченные соседи (`context_neighbors`=1), cap `context_max_messages`=50, единая ASC-хронология `(timestamp,id)`/дедуп, сохранение исходных `id`/`tg_message_id`/`reply_to_id`, бюджет через `resolve_context_tokens`/`resolve_chat_limit` (без новых ключей), «не резать молча» (`status=truncated`+`skipped_ids`), fail-open, OFF (`flags.summary_filter_reply_context_enabled=false`) → S1 байт-в-байт; логи `RESTORE_START/COMPLETE/ERROR` + `FILTER_COMPLETE.restored_count`. @Reviewer **Approved** (T-3245, блокеров нет); @Scanner **C0/H0/M0/L2/I2 → «к деплою ДА»** (T-3246; `plans/reports/round1026_s2_scanner_audit.md`). Числа: pytest `.venv` **8569/0**, JS **43/43**; **Δ DDL=0**, **Δ каталога=0** (467/426/442/100/98/21); публикация/промпты/XML вне diff (D4); ровно 2 LLM-вызова. Техдолг — **§73.5** (L-R1026S2-1 docstring-таймер / L-R1026S2-2 perf-watch `_collect_extra_parents` / L-R1026S2-3 открытый якорь вне `smart_messages` + Info 1–2). `APP_VERSION` 2.58.20 → **2.58.21** (bump @Builder; **код НЕ закоммичен** — Шаг 9). **Гейт S6/S10** (публикация/hybrid) остаётся закрыт (ADR-1025-24 D4; S2 его не открывает). Откат — annotated-тег **`pre-round1026-s2`** → `7895e77` + `var/backups/s2-round1026-*` + `.env.bak.round1026-s2`; soft — `flags.summary_filter_reply_context_enabled=false` (байт-в-байт S1) / `flags.summary_filter_enabled=false`; R18 (теги/бэкапы/`stash@{0}` не удалять). **▶️ Следующая actionable — S3 `summary-l1-clusterizer`** (§94–§95; зависимости S1 ✅/S2 ✅ закрыты).
>
> **✅ EXTRA-ВИЗУАЛЬНЫЙ ЭПИК (round 10.26; Шаг 8 @PM, 23.09.2026; Merge §72): `polygonal-luminescence-round1026` — COMPLETED + MERGED (§72) + ARCHIVED + DEPLOYED (6 коммитов: `76fc5e1`/`bf46360`/`1ad98ca` — базовый, 2.58.19; `306778a`/`a50b014`/`54c6445` — правка владельца v2.58.20 «мерцание свечения ×2 медленнее»).** Merge — `plans/ARCHITECTURE.md` **§72** (@Architect, T-3215); архив — **`plans/archive/polygonal-luminescence-round1026/`** (`spec.md` + **ADR-1026-3** (D1–D9, Accepted фактом мержа §72) + `tasks.md` + `evidence.md` + `review.md` + `deployment.md`; содержимое/чекбоксы сохранены, UTF-8; **T-3162…T-3219, 58**). @Reviewer **Approved** (T-3213); @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 4 → «к деплою ДА»** (T-3214; `plans/reports/round1026_visual_scanner_audit.md`). Суть: замена **Dark Aurora Flow** на полигональный фон — `web/static/polygon-background.js` (Canvas 2D + **Delaunator 5.0.0** vendored same-origin ISC, контракт `window.__PolygonBackground{start,stop,pause,resume,resize,getDiagnostics,mode}` + адаптер `window.__AuroraFlow`, детерминированный `SEED=20260923`/mulberry32, **ровно один активный рендерер** `_syncBgLayer`, env-only `UI_POLYGON_BG_ENABLED` default **ON**); **блок J / Liquid Glass — BLOCKED гейтом §13.2 (PENDING OWNER)** → `mountGlass` со `source` в основной UI не подключён, `UI_LIQUID_GLASS_LIB` default **OFF** (hotfix10 не повторяем). Числа: pytest **8525/0**, JS **43/43**, polygon-Playwright + матрица §71 **0 failures** (правка — новые Scanner **0/0/0**, Info `I-POLY1026-5` pre-existing); **Δ DDL=0**, **Δ каталога=0** (467/426/442/100/98/21); `APP_VERSION` **2.58.18 → 2.58.19 → 2.58.20**. Техдолг — **§72.5** (L-POLY1026-1 GC-аллокации / L-POLY1026-2 покрытие матрицы §71 / L-POLY1026-3 CSP-формулировка + Info 1–4). Откат — annotated-тег `pre-round1026-visual` → `9d046e5` + `var/backups/visual-round1026-*` + `.env.bak.round1026-visual`; soft — env-only `UI_POLYGON_BG_ENABLED=false` → Aurora → CSS-aurora; R18 (бэкапы/теги/`stash@{0}` не удалять). **Live-гейты — `[ ]` PENDING OWNER VERIFICATION** (реальный Telegram WebView/WebKit; стекло п.1/5/7; §17). **▶️ Следующее — возобновление Эпика 2 / S2 `summary-context-restore` (§90–§92, Step 1 @PM); live — PENDING OWNER VERIFICATION; на декоре не зацикливаться.**
>
> **✅ S1 ЭПИКА 2 (Шаг 10 @Memory, 23.09.2026; Merge §71; deploy VERIFIED): `summary-filter-round1026` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`4cd4ae6`/`89bda3d`/`31763ab`, `APP_VERSION` 2.58.18); live — ⏳ PENDING OWNER VERIFICATION (D4).** Merge — `plans/ARCHITECTURE.md` **§71** (@Architect, T-3155); архив — **`plans/archive/summary-filter-round1026/`** (`spec.md` + **ADR-1026-1** + **ADR-1026-2** + `tasks.md` + `evidence.md` + `review.md` + `deployment.md`; содержимое/чекбоксы сохранены, UTF-8; **T-3129…T-3161**; закрыты T-3129…T-3156, T-3159/T-3160/T-3161; закрыты **T-3157** deploy ✅ VERIFIED и **T-3158** метрики ✅). Суть: детерминированный алгоритмический префильтр входа L1 — `services/summary_filter.py` (балл 0..4: reply/`@`-упоминание, «на сообщение ответили», всплеск по плотности 120 с/≥4, слова >5; бот → 0; `kept = score ≥ clamp(min_weight,0,4)`; `==` порога → keep; fail-open; forced-keep), каталог **+8 полей/+2 группы** на вкладке `mod_summary` (санкция ADR-1026-1 D1), UI «Подготовка сообщений», чанки/лимит §93, аддитивные логи `FILTER_*`/`run_id`; врезка `summary_generator._apply_filter` между `get_window_messages` и `xml.build` (фильтруется **только XML-история L1**; RAG/граф/память — на исходных строках; **0 новых LLM-вызовов**). @Reviewer **Approved** (итер.2, T-3152; B-1/M-1 + L-1/L-R1026S1-1/-2 закрыты), @Scanner **C0/H0/M0/L1 → «к деплою ДА»** (T-3153; `plans/reports/round1026_s1_scanner_audit.md`). Числа: pytest **8501/0**, JS **42/42**, **Δ DDL=0**, Δ каталога = санкция ADR-1026-1 D1 (**467**/426/442/**100**/98/21), 2-вызовность (ADR-1022-3/4), CSP/zero-build, R17/R18; **`APP_VERSION` 2.58.18**. Deploy — ✅ **VERIFIED** (Шаг 9 @DevOps, T-3157: прод ff `e7170b7..89bda3d`, active, `/api/health` **200**, served `?v=2.58.18`, `database is locked`=0, `services.summary_filter` импортируется, планировщик Саммари стартует; `deployment.md` **VERIFIED**); **метрики/KG — ✅ Шаг 10 @Memory (T-3158)**. Техдолг — **§71.5** (L-R1026S1-3, L-2/-3/-4, T-3151 браузерный UI/E2E). Гейт: **S6/S10 не открыты** (публикация/промпты вне diff; live-приёмка Эпика 1 — ⏳ PENDING OWNER VERIFICATION, ADR-1025-24 D4). Точка отката — annotated-тег **`pre-round1026-s1`** → `01f3c57`; soft — `flags.summary_filter_enabled=false`; `stash@{0}` цел; код закоммичен (`4cd4ae6`/`89bda3d`/`31763ab`). **▶️ Следующая — S2 `summary-context-restore` (§90–§92, Step 0).** R17/R18: `plans/current_task.md` не изменялся; Шаг 10 @Memory — только `plans/**` + KG (не коммичено).
>
> **✅ F10 ЭПИКА 10.25 (Шаги 8–10 @PM/@DevOps/@Memory, 23.09.2026; Merge §70): `epic1-verification-round1025` — COMPLETED + MERGED + ARCHIVED; deploy — NOT_APPLICABLE (обосновано); авто-приёмка Эпика 1 ✅; live — ⏳ PENDING OWNER VERIFICATION (Telegram WebView).** Архив — **`plans/archive/epic1-verification-round1025/`** (`spec.md` + **ADR-1025-24** + `tasks.md` + `evidence.md` + `review.md` + `deployment.md`; **T-3100…T-3128, 29**; закрыты **T-3100…T-3128** (T-3127 — метрики/KG, Шаг 10 @Memory ✅)). @Reviewer **Approved** (T-3121, 0 блокеров; L-F10R-1…-4/Info); @Scanner **C0/H0/M0/L2/I4 → SCANNED** (T-3122; `plans/reports/round1025_f10_scanner_audit.md`). Числа: `.venv` pytest **8463/0** (system `py -3` = 8457/5env/1), JS **42/42**, матрица §71 + E2E §72–§74 + §78 UI — **failures: 0**; §79-стоп-гейт пройден (300 passed, пайплайны не изменены); **Δ DDL=0**, **Δ каталога=0** (459/418/434/98/96/21); CSP/zero-build; **`APP_VERSION` 2.58.17 (без bump)**. Deploy — **NOT_APPLICABLE** (read-only verification-гейт: нет Δ рантайма/ассетов/каталога/DDL; `tools/**`/`tests/**` рантаймом не импортируются; `deployment.md`; прецедент F8 §67.3; ADR-1025-24 D1). Точка отката §117 п.12 — annotated-тег **`pre-round1025-f10` → `57b325c`**. Live-гейт Telegram WebView **PENDING OWNER VERIFICATION** — Эпик 1 по live не объявляется завершённым; независимые задачи Эпика 2 разрешены (ADR-1025-24 D4). R17/R18: `plans/current_task.md` не изменялся; не коммичено. Техдолг — **§70.5** (L-F10S-1/-2, L-F10R-1…-4 + Info 4). **▶️ Следующая работа — Эпик 2 «Summary Hybrid Pipeline» (10.26), S1 `summary-filter`** (старт по ADR-1025-24 D4: авто-часть Эпика 1 закрыта ✅, live-гейт владельца PENDING и независимые задачи не блокирует; смена существующего публикационного пайплайна — только после live-приёмки).
>
> **✅ F11 ЭПИКА 10.25 (Шаги 8–10 @PM/@DevOps/@Memory, 23.09.2026): `status-showcase-dashboard-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`f3e9195`/`e7170b7`/`5c8fa88`, `APP_VERSION` 2.58.17; Merge §69; `deployment.md` VERIFIED); live — ⏳ PENDING OWNER VERIFICATION (T-3097).** Merge — `plans/ARCHITECTURE.md` **§69** (@Architect, T-3094); архив — **`plans/archive/status-showcase-dashboard-round1025/`** (`spec.md` + **ADR-1025-23** + `tasks.md` + `evidence.md` + `review.md`; содержимое/чекбоксы сохранены, UTF-8; **T-3063…T-3099, 37**; закрыты T-3063…T-3096 и T-3098/T-3099, открыт **T-3097** live). Суть: витрина «Статус» §11–§21 — 12-кол. сетка §12 (адаптив 12/6/1, флаг `UI_STATUS_GRID_V2`, OFF = одноколоночный безопасный режим), Hero §13 / метрики+heartbeat §14 (`null ≠ 0`), граф §16 + hash-маршрут `#/status/graph`, виджет сна §17 (единый источник времени), «Новые факты»/бюджеты §19, счётчики §20 (аддитивное `counts`, corrective H-F11S-1), превью §21 (данные/компонент — F6); §15 не переделывался (hotfix6). @Reviewer **Approved** (T-3091, итер.2; H-F11S-1 + M/L/I закрыты); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 2 → «к деплою ДА»** (T-3092; `plans/reports/round1025_f11_scanner_audit.md`). Числа: JS **42/42**, pytest **8457/5/1** (5 — предсуществующие env `rich`-ImportError), матрица §70 **failures: 0**; **Δ DDL=0**, **Δ каталога=0** (459/418/434/98/96/21); CSP/zero-build; **`APP_VERSION` 2.58.16 → 2.58.17** (задеплоено — health 200, `/healthz` 2.58.17, served `?v=2.58.17`, `database is locked`=0). Техдолг — **§69.6** (`F11-FU-DOSSIER-TS`, `F11-FU-GRAPH-ALIAS`, I-F11S-3 + Info). Откат — тег `pre-round1025-f11` → `25cc19c`; `.env.bak.round1025-f11` / `var/backups/f11-round1025-*` / `stash@{0}` (R18). **▶️ Следующая — F10 `epic1-verification-round1025`** (Step 0; стоп-гейт Эпика 1). R17/R18: `plans/current_task.md` не изменялся; Шаг 10 @Memory — только `plans/**` + KG (не закоммичено).
>
> **✅ F9 ЭПИКА 10.25 (Шаги 8–10 @PM/@DevOps/@Memory, 23.09.2026): `secrets-and-save-states-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`f5fbd5f`/`c610c5f`/`49c1ae1`, `APP_VERSION` 2.58.15 → **2.58.16**; Merge §68); live — ⏳ PENDING OWNER VERIFICATION (T-3059).** Merge — `plans/ARCHITECTURE.md` **§68** (@Architect); архив — **`plans/archive/secrets-and-save-states-round1025/`** (`spec.md` + **ADR-1025-22** + `tasks.md` + `evidence.md` + `review.md` + `deployment.md` **VERIFIED**; содержимое/чекбоксы сохранены, UTF-8; **T-3024…T-3062, 39**; закрыты **T-3058** deploy ✅ VERIFIED, **T-3060** метрики/KG ✅ Шаг 10; открыт **T-3059** live). Суть: UI-слой секретов §50 (`{configured,last4}`, «Ключ установлен», маска = display-индикатор ≠ значение `input`, отдельные «Заменить»/«Удалить» без нового endpoint) + визуальная часть SaveBar §69/§78 (safe area, клавиатура/`visualViewport`, последнее поле, одно уведомление, «Подробнее»); persistence/409/412/state-machine — в F0 (§52), не дублируется. @Reviewer **Approved** (итер.2; H-F9S-1 + L-F9S-1..4 закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 2 → «к деплою ДА»** (`plans/reports/round1025_f9_scanner_audit.md`; I-F9S-1 косметика, I-F9S-2 live PENDING OWNER). Числа: JS **40/40**, полный pytest **8421 passed / 0 failed / 1 skipped** (5 env-падений `rich` — предсуществующие, вне F9), матрица **failures: 0**; **Δ DDL=0**, **Δ каталога=0** (459/418/434/98/96/21; секреты 28 = 20 UI + 8 env-only); CSP/zero-build; **`APP_VERSION` 2.58.16** (bump — менялись `web/**`-ассеты, cache-bust). Техдолг — **§68.8** (I-F9S-1, I-F9S-2 + док-ниты). Откат — тег `pre-round1025-f9` (база `93432c0`); `stash@{0}` (R18; `.env.bak.round1025-f9` на проде отсутствует — UI-only, Δ DDL=0). KG: `release-round1025-f9` + `metric-snapshot-round1025-f9-final` + `tech-debt-round10.25-f9`. **▶️ Следующая — F11 `status-showcase-dashboard-round1025`** (Step 0), затем **F10** `epic1-verification-round1025` (приёмка Эпика 1). R17/R18: `plans/current_task.md` не изменялся; код/планы закоммичены и задеплоены (Шаги 8–9); Шаг 10 @Memory — только `plans/**` + KG (не коммичено).
>
> **✅ F8 ЭПИКА 10.25 (Wave 0 enabler, Шаг 8 @PM + Шаг 9 deploy NOT_APPLICABLE + Шаг 10 @Memory, 23.09.2026): `parameter-registry-widget-map-round1025` — COMPLETED + MERGED + ARCHIVED; deploy — NOT_APPLICABLE (обосновано).** Merge — `plans/ARCHITECTURE.md` **§67** (@Architect); архив — **`plans/archive/parameter-registry-widget-map-round1025/`** (`spec.md` + **ADR-1025-21** + `tasks.md` + `evidence.md` + `review.md` + `deployment.md`; содержимое/чекбоксы сохранены, UTF-8; **T-2964…T-3023, 60**). Read-only enabler (ADD-only, без AMEND): реестр **459** (23 колонки, 0 пустых; дельта 411→459 = **48**), карта экранов «без места»=0, карта виджетов (`api-only` отдельно), read-only `tools/*` (рантаймом не импортируются), diff 8 срезов (offline-baseline). @Reviewer **Approved** (`review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 4** (`plans/reports/round1025_f8_scanner_audit.md`) → «к приёмке ДА»; pytest **8403/0** (baseline 8374 + 29 F8); **Δ DDL=0**, **Δ каталога=0** (459/98/96/21/418); CSP/zero-build; **`APP_VERSION` 2.58.15 (без bump)**. **deploy — NOT_APPLICABLE** (нет Δ рантайма/БД/ассетов/каталога; `tools/` рантаймом не импортируется; рестарт/cache-bust не требуются) — `deployment.md`. Открыто: только **T-3021** (живой PG-снимок «до/после» — ⏳ PENDING OWNER VERIFICATION) + Low L-F8S-1/-2/-3 (owned follow-up); **T-3020 (метрики/KG — Шаг 10 @Memory) — ✅ выполнен** (`plans/metrics.md` **10.25-F8** + KG `metric-snapshot-round1025-f8-final`/`tech-debt-round10.25-f8`). **▶️ Следующая — F9 `secrets-and-save-states-round1025`** (§50 + визуальный SaveBar §69/§78). R17/R18: `plans/current_task.md` не изменялся; тег `pre-round1025-f8`, бэкапы `f8-round1025-*`, `.env.bak.round1025-f8`, `stash@{0}` — не удалять; не коммичено.
>
> **🗂️ F8 ЭПИКА 10.25 (Wave 0 enabler, исторический Step 0 @Memory 23.09.2026 — итог см. баннер выше): `parameter-registry-widget-map-round1025` — обязательный аудит §1–§3 + §117 п.1–4 (реестр параметров, карта «экран→параметр→новый экран→API», карта виджетов, бэкап+diff до/после).** Baseline HEAD `a40f244` (== `origin/master`, после F7), `APP_VERSION` **2.58.15**, каталог **459/98/96/21/418** (подтверждён импортом), pytest 8374/0 (последний верифицированный прогон F7), JS 38/38. Код НЕ менялся (только `plans/**` + KG). Источники-артефакты: `plans/archive/settings-persistence-audit-round1014/` (`inventory.tsv` 411 строк / `report.md` / `spec.md` / `tasks.md`), `plans/docs/prod-params-audit-2026-09.md` (341 ключ `bot_settings`), `plans/reports/global_map.md`, `plans/reports/full_audit_results.md`; заготовка `plans/features/parameter-registry-widget-map-round1025/tasks.md` (без T-ID). KG: `F8-parameter-registry-widget-map-round1025` + `constraint-parameter-inventory-no-loss-round1025` + 5 Risk (потеря параметра Critical / скрытая миграция High / секрет в отчёте Critical-R17 / API-only параметр High / дублирование артефактов Medium-High); связи — part-of Epic round1025, mapped-in `round1025-architecture`, enabler-for F1/F4/F5/F6/F7, governed-by constraint, raises×5. Живой гейт — ⏳ PENDING OWNER VERIFICATION (T-2961 F7, T-2917 F6). **Следующий шаг — Step 1 @PM** (декомпозиция `tasks.md` с T-ID; Step 2 @Architect — `spec.md`/ADR).
>
> **✅ F7 ЭПИКА 10.25 (Волна 3, Шаги 7–10 @Architect/@PM/@DevOps/@Memory, 23.09.2026): `permsoc-local-space-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`6bf00e7`/`908f471`/`e2b452c`/`3bab70f`, `APP_VERSION` 2.58.14 → 2.58.15; live — ⏳ PENDING OWNER VERIFICATION).** Merge — `plans/ARCHITECTURE.md` **§66** (Step 7 @Architect); **архив — `plans/archive/permsoc-local-space-round1025/`** (`spec.md` + **ADR-1025-20-permsoc-local-space-and-server-gates** + `tasks.md` + `evidence.md` + `review.md`; содержимое/чекбоксы сохранены, UTF-8; **T-2921…T-2963, 43**; закрыты T-2921…T-2959, **T-2960** (deploy — ✅ VERIFIED, `6bf00e7`/`908f471`/`e2b452c`/`3bab70f`, 2.58.15, health 200, `database is locked`=0), **T-2962** (метрики/KG — ✅ Шаг 10 @Memory); открыты **T-2961** (живой Telegram WebView/TMA + реальные фоновые задачи — **PENDING OWNER VERIFICATION**), **T-2963** (продолжение → F8)). @Reviewer **Approved** (итер.3; H-F7-1/-7, M-F7-2, L-F7-3/-5/-8/-9 закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → «к деплою ДА»** (`plans/reports/round1025_f7_scanner_audit.md`). Числа: JS **38/38**, полный pytest **8374 passed / 0 failed**; матрица `tools/ui_round1025_matrix.py` **failures: 0**; `node --check` OK; **Δ DDL = 0**; **Δ каталога = 0** (459/98/96/21/418); CSP/zero-build; **`APP_VERSION` 2.58.14 → 2.58.15**. Техдолг — **§66.8** (L-F7S-1 серверный denylist PERMsoc в global-пути, L-F7-4 `dead_page_post_on_join`, L-F7-6 DM-мастер pre-existing; не блокеры). Откат — тег `pre-round1025-f7` → `551847d`; `.env.bak.round1025-f7`; `stash@{0}` (R18). **✅ Шаг 9 @DevOps (deploy F7 — VERIFIED, `3bab70f`, 2.58.15, health 200, `database is locked`=0, `deployment.md` VERIFIED) + Шаг 10 @Memory (T-2962, метрики/KG) выполнены; следующий — F8** `parameter-registry-widget-map-round1025` (обязательный аудит §1–§3/§117). R17/R18: `plans/current_task.md` не изменялся; не коммичено.

> **✅ F6 ЭПИКА 10.25 (Волна 3, Шаги 8–10 @PM/@DevOps/@Memory, 23.09.2026): `memory-analytics-reorg-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`02b99e9`/`cddacda`/`947191e`, `APP_VERSION` 2.58.13 → 2.58.14; live — ⏳ PENDING OWNER VERIFICATION).** Merge — `plans/ARCHITECTURE.md` **§65** (Step 7 @Architect, 23.09.2026); архив — **`plans/archive/memory-analytics-reorg-round1025/`** (`spec.md` + **ADR-1025-19** + **ADR-1025-19a** (AMEND-1) + `tasks.md` + `evidence.md` + `review.md`; содержимое/чекбоксы сохранены, UTF-8; **T-2870…T-2920, 51**; **48 [x] / 3 [ ]** — ✅ закрыты **T-2916** (deploy, VERIFIED) и **T-2918** (метрики, Шаг 10); открыты **T-2917** (живой WebView + реальный PG-пайплайн `/analytics/*`, **PENDING OWNER VERIFICATION**), **T-2919/T-2920** (продолжение F7 / финальная сверка)). @Reviewer **Approved** (итер.2; H1 §52 закрыт AMEND-1 `adr-1025-19a`, H2 §27/M-F6S-1/L-F6S-3/4/5 закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 2 / Info 4 → «к деплою ДА»** (`plans/reports/round1025_f6_scanner_audit.md`). Числа: JS **37/37**, F6 pytest **19 passed**, полный pytest **8334 passed / 1 skipped / 5 env-failed** (env `rich`-fallback, `services/**` вне диффа → не регресс); Playwright F6-проба и матрица **failures 0**; `node --check` OK; `APP_VERSION` **2.58.13 → 2.58.14**; **Δ DDL=0**, **Δ каталога=0** (459/98/96/21/418); CSP/zero-build (adapter `web/static/execution_graph.js` — same-origin, без inline/CDN/eval). Техдолг **§65.10** (L-F6S-1 `priceKnown` в агрегате / L-F6S-2 OFF-ветка не byte-identical + Info, не блокеры). Откат — тег `pre-round1025-f6` → `f103992` + `.env.bak.round1025-f6` + `stash@{0}` (R18). **✅ Шаг 9 @DevOps (deploy F6 — VERIFIED, `947191e`, 2.58.14) + Шаг 10 @Memory выполнены; следующий — F7 `permsoc-local-space-round1025` (T-2919, Step 0).** R17/R18: секреты не цитировались; `plans/current_task.md` не изменялся.

> **✅ ПАКЕТ ЗАКРЫТ И ЗАДЕПЛОЕН (Шаги 8–10: @PM/@DevOps/@Memory, 23.09.2026): UPD4 `hotfix10-liquidglass-rollback-shell-geometry-round1025` (Волна 1.9, приоритетный P0 поверх HOTFIX9 2.58.12) — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`bf086d4`/`24dc7e3`/`8964f07`, `APP_VERSION` **2.58.13**).** Merge — `plans/ARCHITECTURE.md` **§64** (@Architect, Step 7); **архив — `plans/archive/hotfix10-liquidglass-rollback-shell-geometry-round1025/`** (`spec.md` + **ADR-1025-18** + `tasks.md` + `evidence.md` + `review.md`; содержимое/чекбоксы сохранены, UTF-8; **T-2840…T-2869, 30**; **28 [x] / 2 [ ]** — закрыт **T-2867** (deploy — ✅ @DevOps, `deployment.md` VERIFIED, 2.58.13); открыты **T-2862** (live WebView, **PENDING OWNER VERIFICATION**) и **T-2869** (продолжение F6); T-2868 архивация ✅). @Reviewer **Approved** (T-2865, итер.2; блокер **H-1** + Low **L-H10-1**/**L-1**/**L-2** закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 1 → «к деплою ГОТОВО»** (T-2866; `plans/reports/round1025_hotfix10_scanner_audit.md`). Источник — `plans/current_task.md` строки **7267–7482** («P0 HOTFIX — исправление интеграции Liquid Glass и геометрии AppShell»), дословно; файл **не изменялся** (R17/R18). **Суть:** §1 — `UI_LIQUID_GLASS_LIB` default **OFF** + снят `mountGlass()` с `.scope-trigger`/`.header-fs-btn`/`.status-block` (белые непрозрачные прямоугольники = белый frost-fallback без `refract`/`source`; **не** лечение opacity); §2 — реинтеграция только через 1 изолированный декоративный `GlassSurface` (честный `detectMode` = frosted ≠ преломление); §3 — единая рабочая поверхность Main (`--work-surface-bg`, полосы нет, лимит 1100px без отрицательных отступов); §4 — единая модель высоты (второй safe-area снят, legacy `.more-sheet`/`.bottom-nav` выведены); §5 — восстановлен `.status-block` (фикс **H-1**: `main.scroll-area{grid-auto-rows:max-content}`); §6/Доп.P0 — фон не переделан, но `__AuroraFlow.resize` экспортирован/вызывается (resize/fullscreen/visualViewport/ResizeObserver), `gl.viewport`/`uRes` из drawing buffer, композиция без полосы слева, без новых CSS-градиентов. Baseline: HEAD **`5184584`** (= tag `pre-round1025-hotfix10`), `APP_VERSION` **2.58.12 → 2.58.13** (✅ задеплоено, Шаг 9 @DevOps). Прогоны: pytest **8319 passed / 0 failed** (baseline 8291), JS **35/35**, матрица `tools/ui_round1025_matrix.py` **failures: 0** (10 вьюпортов, normal+fullscreen, OFF на 5 ширинах); **Δ DDL=0**, **Δ каталога=0** (459/98/96/21/418), CSP same-origin; кадры фона 0/5/10/20 с — движение; гейт §5 не вакуумный (red при откате `grid-auto-rows`). **✅ Шаг 9 @DevOps (deploy, T-2867; `deployment.md` VERIFIED):** коммиты **`bf086d4`** (код+тесты) + **`24dc7e3`** (планы) + **`8964f07`** (deploy-doc); прод `/var/www/admin_bot` fast-forward `8d61926..24dc7e3`, active (Main PID 181526), `/api/health` **200**, `/healthz` **200** (`version 2.58.13`), served `?v=2.58.13`, `data-glass-surface`=1, `database is locked`=0. Техдолг — **§64.9** (Info I-H10-3 + не блокеры; финализация — Шаг 10 @Memory ✅). **▶️ Следующий шаг — НЕМЕДЛЕННО F6 `memory-analytics-reorg-round1025`** (T-2869, UPD4 §8, без human gate; Step 0 ✅, возобновление Step 1 @PM). Живой WebView — **PENDING OWNER VERIFICATION** (не объявлять дефект устранённым по сборке/Reviewer; Chromium ≠ WebView). KG: `HOTFIX10-…` + `SpecDecision-glass-rollback-temporarily-off-round1025` + 4 Risk (связи `follows-up` HOTFIX9, `amends` ADR-1025-17).

> **✅ ПАКЕТ ЗАКРЫТ И ЗАДЕПЛОЕН (Шаги 8–10: @PM/@DevOps/@Memory, 22.09.2026): UPD3 `hotfix9-shell-liquidglass-darkaurora-round1025` (Волна 1.8, приоритетный поверх HOTFIX8) — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`470b63a`/`8d61926`/`dba76e8`, `APP_VERSION` 2.58.12).** Merge — `plans/ARCHITECTURE.md` **§63** (Шаг 7 @Architect, 22.09.2026); **архив — `plans/archive/hotfix9-shell-liquidglass-darkaurora-round1025/`** (`spec.md` + **ADR-1025-17-shell-flex-aurora-glass-csp** + `tasks.md` + `evidence.md` + `review.md`; содержимое/чекбоксы сохранены, UTF-8; `deployment.md` **VERIFIED**). **T-2790…T-2839 (50)** — в `tasks.md` открыты **T-2830** (live-гейт владельца, **PENDING OWNER VERIFICATION**), **T-2837** (deploy — ✅ выполнен, @DevOps `deployment.md` VERIFIED), **T-2839** (продолжение F6). @Reviewer **Approved** (T-2835, итер.2; блокер **H-H9S-1** и **M-H9R-1** закрыты, L-H9S-1..3 закрыты — `review.md`); @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 3 → «к деплою ГОТОВО»** (T-2836; `plans/reports/round1025_hotfix9_scanner_audit.md`). **Суть:** flex-колонка `shell-mobile` + единый `--app-usable-height` (safe-area один раз, старый fixed/bottom-offset удалён), нижняя nav внутри потока, header/fullscreen через flex (`scrollTop=0`), modal footer `.modal-actions` + SaveBar вне `.modal-body`, **полное удаление диагональной текстуры `--shell-texture`** со всех shell-поверхностей, графитовые shell-токены §8, **настоящее преломление §9** (vendored same-origin под CSP `script-src 'self'`: `liquidglass.core.0.5.3` + `ogl.1.0.11`, SHA-256 3/3, прототип-гейт `displacementScale=14.56`/`diffGlass=15.97`, без `backdrop-filter:url()`), фон **Dark Aurora Flow** §10 (без CDN/inline/eval), автопроверки §12 (**матрица 10 вьюпортов × 5 режимов — failures 0**), сердцебиение §11 (только исчезновение в fullscreen, дизайн не менялся). Числа: pytest **8291 passed / 0 failed** (baseline 8272); hotfix9 pytest **17/0**; `node --check` OK; `git diff --check` = 0; **Δ DDL=0**, **Δ каталога=0** (459/98/96/21/418; 4 env-only `ClassVar`). Baseline HEAD **`b374c0f`** (= tag `pre-round1025-hotfix9`). **Деплой (Шаг 9 @DevOps, `deployment.md` VERIFIED):** коммиты **`470b63a`** (код+тесты+vendor, 36 файлов) + **`8d61926`** (планы: Merge §63 + архивация + Scanner-аудит) + **`dba76e8`** (deploy-doc); прод `/var/www/admin_bot` fast-forward `1a8ed18..8d61926`, `systemctl restart` active (Main PID 154704), `/api/health` **200**, `/healthz` **200** (`version 2.58.12`), `APP_VERSION` **2.58.11 → 2.58.12**, served `?v=2.58.12`, новые ассеты same-origin 200, `database is locked`=**0**, Traceback/ERROR=0. Откат — тег `pre-round1025-hotfix9` → `b374c0f` + `git revert`; soft — env-only kill-switch (default ON). **⏳ live — T-2830 PENDING OWNER VERIFICATION. Шаг 10 @Memory — метрики `10.25-HOTFIX9` + KG + техдолг §63.11 ✅. Следующая — F6 `memory-analytics-reorg-round1025` (T-2839, немедленно, без human gate).** R17/R18: секреты не цитировались; `plans/current_task.md` не изменялся; теги/бэкапы `pre-round1025*` и `stash@{0}` **НЕ удалять**.

> **✅ ПАКЕТ ЗАКРЫТ И ЗАДЕПЛОЕН (Шаги 8–10 @PM/@DevOps/@Memory, 22.09.2026): UPD2 `hotfix8-shell-glass-aurora-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`98551b2`/`5124522`/`1a8ed18`/`d3179c1`, `APP_VERSION` **2.58.11**); Merge `plans/ARCHITECTURE.md` §62.** Архив — **`plans/archive/hotfix8-shell-glass-aurora-round1025/`** (`spec.md` + **ADR-1025-16** + `tasks.md` + `evidence.md` + `review.md`; `deployment.md` **VERIFIED** (Шаг 9 @DevOps); **T-2745…T-2789, 45**; **44 [x] / 1 [ ]** — открыт только **T-2776** (live-гейт владельца)). @Reviewer **Approved** (T-2783); @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → «к деплою ДА»** (`plans/reports/round1025_hotfix8_scanner_audit.md`); AA — `plans/reports/round1025_hotfix8_contrast.md`; матрица 5 режимов — `plans/reports/round1025_hotfix8_ui_report.md` (**failures: 0**). **Суть:** shell v3 по §4 (тёмно-серый glass-слой, снята цветная линза/ореол, панели → `data-glass="shell"`), CSS-aurora/mesh (5 blob + grain, пауза hidden, reduced-motion) вместо мёртвого conic-фона, выравнивание shell/mobile/fullscreen/SaveBar; **ограничение** «Framer Motion/React подключить нельзя» (Vue 3 zero-build + CSP) + выбран эквивалент (CSS/WAAPI/SVG). Baseline HEAD **`a1e6db3`** (= tag `pre-round1025-hotfix8`), `APP_VERSION` **2.58.10** (bump 2.58.11 — T-2786). **Δ DDL=0, Δ каталога=0** (459/98/96/21/418), CSP/zero-build, без WebGL/новых библиотек. Техдолг — **§62.7** (L-H8R-1…5 / L-H8S-1…3, не блокеры). Откат — тег `pre-round1025-hotfix8` → `a1e6db3` + `git revert`; soft — env-only `UI_SHELL_V3`/`UI_AURORA_BG_ENABLED` (default ON). **Шаг 9 @DevOps ✅ (деплой VERIFIED) → Шаг 10 @Memory ✅ (метрики `plans/metrics.md` 10.25-HOTFIX8 + KG, T-2789) → следующий — F6** `memory-analytics-reorg-round1025` (Step 0). Код/тесты/планы закоммичены и задеплоены (`98551b2`/`5124522`/`1a8ed18`/`d3179c1`, 2.58.11); R17/R18 (теги/бэкапы/`stash@{0}` не удалять).

> **✅ F5 ЭПИКА 10.25 (Волна 3, Шаг 10 @Memory, 22.09.2026): `module-workspace-tabs-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (`63dddd3`/`0d3ea40`/`af137cd`, `APP_VERSION` 2.58.10).** Архитектура — `plans/ARCHITECTURE.md` **§61** (Merge @Architect: §61.1 A — workspace §46 маршрут/вкладки/тумблер из store F4, §61.2 B — раздел ИИ §47 (5 страниц), §61.3 C — гибридная библиотека промптов §48 «один промпт — один источник», §61.4 D — §49 (6 групп + карточка), §61.5 E/F — §84/§85 только UI-каркас, §61.6 тесты/маркеры/bump, §61.7 SUPERSEDE/AMEND, §61.8 техдолг, §61.9 ссылки). Архив — **`plans/archive/module-workspace-tabs-round1025/`** (`spec.md` + **ADR-1025-15** + `tasks.md` + `evidence.md` + `review.md`; **T-2695…T-2744, 50**; `deployment.md` **VERIFIED**). @Reviewer **Approved** (итер.2; FIX-1…FIX-4 + блокер M-F5S-1 закрыты) — `review.md`; @Scanner **Critical 0 / High 0 / Medium 0 / Low 0 / Info 2 → «к деплою ДА»** (`plans/reports/round1025_f5_scanner_audit.md`). Числа: pytest **8245 passed / 1 skipped / 5 failed** (5 — пред-существующий env `InputRichMessageMedia`, вне F5), F5 pytest **19 passed**, JS `MODULE-WORKSPACE-OK`/`PROMPTS-SINGLE-SOURCE-OK`/`MODELS-GROUPS-OK`, Playwright §71 **failures: 0**, `APP_VERSION` **2.58.10**; **Δ DDL=0**, **Δ каталога=0** (459/98/96/21/418), новых API/библиотек нет (reuse `/api/llm/test`,`/api/images/test`). Техдолг **§61.8**. Откат — тег `pre-round1025-f5` → `940ba40` (R18, целы) + `git revert`; мягкий — `openModuleWindow` + `git revert`. **✅ Деплой (Шаг 9 @DevOps):** коммиты **`63dddd3`** (код+тесты, 18 файлов, `APP_VERSION` 2.58.9→2.58.10) + **`0d3ea40`** (docs/plans: Merge §61 + архивация + Scanner-аудит) + **`af137cd`** (deploy-doc); push origin/master без force (`12a55bb..0d3ea40`); прод `/var/www/admin_bot` fast-forward `28eb02d..0d3ea40`; `systemctl restart admin_bot` active (Main PID 96796); `/api/health` **200**; `/healthz` **200** (`version 2.58.10`); served `?v=2.58.10`; `database is locked` **0**. **Следующая — F6** `memory-analytics-reorg-round1025`. ⏳ Live-гейт владельца **T-2742** открыт.
>
> **✅ АКТИВНЫЙ ПАКЕТ ЗАКРЫТ (Шаги 7–10: @Architect/@PM/@DevOps/@Memory, 22.09.2026): UPD-фикс `hotfix7-shell-glass-heartbeat-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 9 @DevOps, 22.09.2026); ⏳ live-гейт владельца T-2682 открыт.** Архитектура — **`plans/ARCHITECTURE.md` §59** (Merge @Architect: §59.1 A — единый `--shell-h` + режимы normal/fullscreen, §59.2 B — premium ECG-сердцебиение §15 (AMEND ADR-1025-12 D4), §59.3 C — серо-графитовый `--shell-*` (AMEND ADR-1025-12 D2 / уточнение ADR-1025-9 D2), §59.4 D/E — рецепт glass + снятие «грязи» + AA + выравнивание, §59.5 F — матрица 5 режимов, §59.6 флаги, §59.7 SUPERSEDE/AMEND, §59.8 техдолг, §59.9 live-гейты, §59.10 ссылки). Архив — **`plans/archive/hotfix7-shell-glass-heartbeat-round1025/`** (`spec.md` + **ADR-1025-13** + `tasks.md` + `evidence.md` + `review.md`; `deployment.md` **VERIFIED**; **T-2658…T-2694, 37**; остался открытым только **T-2682 (live)**, T-2690 (deploy) закрыт фактом). @Reviewer **Approved** (итер.2, F-1…F-4); @Scanner **Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → «к деплою ДА»** (`plans/reports/round1025_hotfix7_scanner_audit.md`); AA — `plans/reports/round1025_hotfix7_contrast.md`; матрица — `plans/reports/round1025_hotfix7_ui_report.md`; UPD 7 — `plans/reports/round1025_tz_remaining_audit.md` (+§9 итоговый отчёт). Числа: pytest **8207/0**, JS **27/27**, `APP_VERSION` **2.58.8** (задеплоено); **Δ DDL=0**, **Δ каталога=0** (459/98/96/21/418). Техдолг **§59.8** (L-H7-1/-2/-3, Info I-H7-1/-2/-3). Откат — тег `pre-round1025-hotfix7`→`5a5465c` (запушен) + `git revert`; soft — env-флаги `UI_SHELL_GLASS_V2`/`UI_HEARTBEAT_PREMIUM`/`UI_SHELL_LAYOUT_V2` (+hotfix6-флаги), default ON. **✅ Деплой (Шаг 9 @DevOps):** коммиты **`7073e34`** (код+тесты) + **`a9cec67`** (планы) + **`2a67829`** (deploy-doc); прод `/var/www/admin_bot` fast-forward `5a5465c..a9cec67`; `systemctl restart` active; `/api/health` **200**; `APP_VERSION` **2.58.8**; served `?v=2.58.8`; `database is locked` **0**. **✅ F4 `module-catalog-quickpanel-store-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 9 @DevOps, 22.09.2026; Merge §60; `APP_VERSION` 2.58.9; см. баннер ниже). Следующий шаг — F5 `module-workspace-tabs-round1025`; `metrics.md` разделы 10.25-HOTFIX7 и 10.25-F4 — Шаг 10 @Memory ✅.**
>
> **✅ F4 (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026): `module-catalog-quickpanel-store-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED** (Эпик 1, Волна 2; ТЗ §31–§45/§72/§73/§79/§116). **Merge — `plans/ARCHITECTURE.md` §60** (@Architect, T-2652; §60.1–§60.13). **Архив — `plans/archive/module-catalog-quickpanel-store-round1025/`** (`spec.md` + **ADR-1025-14** + `tasks.md` + `evidence.md` + `review.md`; **T-2619…T-2657, 39**; закрыты **T-2619…T-2655** и **T-2657** (@Memory — KG-синк + `metrics.md`, Шаг 10); **⏳ остался открытым только T-2656 (live-гейт владельца, реальный Telegram WebView)**). @Reviewer **Approved** (итер.2, блокер F4-M1 закрыт); @Scanner **Critical 0 / High 0 / Medium 0 / Low 2 / Info 3 → «к деплою ДА»** (`plans/reports/round1025_f4_scanner_audit.md`). Числа: pytest **8229/0**, JS-маркеры `MODULE-STORE-OK`/`MODULE-CATALOG-OK`, `APP_VERSION` **2.58.9**; **Δ DDL=0**, **Δ каталога=0** (459/98/96/21/418). **Суть:** каталог модулей §31–§45 + панель избранного §34–§36 + канонический `ModuleConfigurationStore` §37–§39 (одна мутация → все представления §40, ключ `scope_type+scope_id+module_id`, scoped keys/stale §42/§73, **откат при ошибке §41**), переиспользование F3 (`scopeEpoch`/`_scopeGuard`, `chat_source`/`global_value`, §43-хелперы) и F0-write-path (`persistItems`); §43 «Ожидает применения» = **N/A** (read-through); «Настроить» → шов `openModuleWorkspace` (без фиктивного маршрута — собственность F5). **Техдолг §60.10:** L-F4-1 (defensive re-read 409), L-F4-6 (§73-гонка без обратной связи), L-F4S-1 (`stickyFailedKeys`), L-F4S-2 (`runtimeGate`/parent-gate follow-up) + Info. **✅ Деплой (Шаг 9 @DevOps):** коммиты **`7f9fed1`** (код+тесты, APP_VERSION 2.58.8→2.58.9) + **`28eb02d`** (планы: Merge §60 + архивация + Scanner-аудит) + **`f0db773`** (deploy-doc); push origin/master без force; прод `/var/www/admin_bot` fast-forward `2a67829..28eb02d`; `systemctl restart admin_bot` active; `/api/health` **200**; `APP_VERSION` **2.58.9**; served `?v=2.58.9`; `database is locked` **0**; `deployment.md` **VERIFIED**. Метрики — Шаг 10 @Memory (раздел `10.25-F4`) ✅. **⏳ Открыт только live-гейт владельца T-2656 (реальный Telegram WebView).** **Следующая фича — F5** `module-workspace-tabs-round1025`. R17/R18: секреты не цитировались; `current_task.md` не трогался; теги/бэкапы `pre-round1025*` **НЕ удалять**.

> **✅ ХОТФИКС-6 (пакет «Волна 1.5») ЭПИКА 10.25 (Шаг 8 @PM, 22.09.2026): `hotfix6-webview-shell-heartbeat-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 9 @DevOps, 22.09.2026).** Архитектура — `plans/ARCHITECTURE.md` **§58** (Merge @Architect: §58.1 A — преломление/стекло, §58.2 B — нижняя панель, §58.3 C — Canvas-2D §15, §58.4 D — шапка/⛶, §58.5 флаги, §58.6 SUPERSEDE/AMEND, §58.7 техдолг, §58.8 live-гейты). Архив — `plans/archive/hotfix6-webview-shell-heartbeat-round1025/` (`spec.md` + **ADR-1025-12** + `tasks.md`, **T-2581…T-2618, 38 задач**; T-2615 ревью/аудит ✅, **T-2616 deploy ✅**, T-2618 архивация ✅; **T-2617 live — открыт**). Аудит — `plans/reports/round1025_hotfix6_scanner_audit.md` (**Critical 0 / High 0** / M1 / L3 / I3 → деплой разрешён) + AA-доказательство `plans/reports/round1025_hotfix6_contrast.md`. @Reviewer **Approved** (итер.2, 12/12); @Scanner — Critical 0 / High 0. `APP_VERSION` **2.58.6 → 2.58.7** (задеплоено). **Суть:** **A** — foreground-линза `[data-glass="a"]::before` + `filter:url(#lg-lens)` (edge-weighted radial-mask), `backdrop-filter:url()` удалён, UA-gate снят, перф-кап `UI_LENS_MAX_NODES=6`, стекло на sidebar/drawer/header/bottom-nav/more-sheet; **B** — `computeBottomOffset()=max(innerHeight−stableHeight, contentSafeAreaInset.bottom, safeAreaInset.bottom)`; **C** — Canvas 2D + rAF heartbeat §15 (HEALTHY/WARNING/CRITICAL/UNKNOWN + гистерезис/EMA/dwell, `missing≠bad`, телеметрия из `/api/status`, legacy-OFF `heartbeatLegacy`); **D** — двухстрочная шапка + ⛶ по safe-area + резерв `--header-h`; **§15 SUPERSEDE/вынесено из F11**. Флаги env-only (`UI_GLASS_TIER_OVERRIDE`/`UI_HEARTBEAT_CANVAS_ENABLED`/`UI_HEADER_COMPACT_V2`/`UI_LENS_MAX_NODES`, default ON, Δ каталога = 0). **Инварианты:** Δ DDL = 0, Δ каталога = 0, CSP/zero-build, запрет WebGL (Canvas 2D), нативные кнопки Telegram CSS не двигаются. **✅ Деплой (Шаг 9 @DevOps):** коммиты **`055525c`** (код+тесты) + **`ba75751`** (docs), push origin/master, прод `/var/www/admin_bot` fast-forward `4cde1bc..ba75751`, `systemctl restart admin_bot` → **active**, `/api/health` = **200**, `APP_VERSION` **2.58.7**, served `?v=2.58.7`, `database is locked` = **0** → `deployment.md` **VERIFIED** (точка отката `pre-round1025-hotfix6`; бэкап `var/backups/hotfix6-round1025-20260922-013551/`). **Прогоны:** pytest **8185 passed / 0 failed**, JS **26/26**, matrix **0**. **⏳ Открыт live-гейт владельца T-2617** (реальный Telegram WebView: преломление/стекло, панель в экране, heartbeat/тултип/перф, ⛶/fullscreen, консоль TMA) + ранее открытые T-2409/T-2505/T-2527. **Pending sync закрыт** на Шаге 10 (@Memory: `plans/reports/full_audit_results.md`/`audit_backlog.md` обновлены); метрики — `plans/metrics.md` раздел **10.25-HOTFIX6**. **Следующий шаг — F4 `module-catalog-quickpanel-store-round1025`.** R17/R18: секреты не цитировались; теги `pre-round1025-hotfix6`/бэкапы/`stash@{0}` **НЕ удалять**.

> **✅ ВОЛНА 1 ЭПИКА 10.25 (Шаг 8 @PM, 22.09.2026): `F2 design-tokens-liquidglass-v2-round1025` + hotfix5 `summary-cover-window-round1025` + `F3 global-scope-selector-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED (Шаг 8 @PM + Шаг 9 @DevOps, 22.09.2026).** Архитектура — `plans/ARCHITECTURE.md` **§57** (Merge @Architect): §57.1 (F2), §57.2 (hotfix5), §57.3 (F3), §57.4 (SUPERSEDE/AMEND-карта). Архивы — `plans/archive/design-tokens-liquidglass-v2-round1025/` (`spec.md` + **ADR-1025-9** + `tasks.md`, T-2529…T-2562), `plans/archive/hotfix5-summary-cover-window-round1025/` (ретро: `spec.md` + **ADR-1025-11** + `tasks.md`, T-2563…T-2573), `plans/archive/global-scope-selector-round1025/` (ретро: `spec.md` + **ADR-1025-10** + `tasks.md`, T-2574…T-2580). Аудит — `plans/reports/round1025_package_scanner_audit.md` (пакетный, **C0/H0**) + базовые `round1025_f2/hotfix5/f3_scanner_audit.md`.
> **Числа пакета:** итоговый `APP_VERSION` **2.58.6**; полный pytest **8146 passed / 5 failed / 1 skipped** (5 падений — env `aiogram` без `InputRichMessageMedia`, файлы **вне** пакета → не регрессия); целевые тесты пакета **152 passed**; JS **25/25**; **Δ DDL = 0**, **Δ каталога = 0** (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418); CSP/zero-build сохранены. Финальные коммиты кода: F2 **`d2df8ca`**, hotfix5 **`412f844`**, F3 **`4f31197`**.
> **Суть:** **F2** — палитра §8 (SUPERSEDE OD4 / glass 10.20 / `--grad-d #FF8A3D` / `--grad-speed:6s`; AMEND ADR-1020-9), Liquid Glass A/B/C §9 (`feDisplacementMap`, deny-list), фон 60–90/90–120 с §10, контраст AA. **hotfix5** — ≤2 попытки обложки, `retry=False`+`max_retries=0`, селективный ретрай (`is_transient_reason`), `wait_for`-дедлайн (**362 c**), отдельный env-only `image_calls`-бюджет (ровно одно списание), R17-safe логи, `int(chat_id)` в планировщике. **F3** — постоянный селектор области §5, «Вернуть глобальное» = **DELETE override** (не factory-reset), guard несохранённых (`blockDrafts`/API-ключ/persona/dossier), stale-эпоха (`scopeEpoch`/`_scopeGuard`), §43 N/A (read-through).
> **✅ Шаг 9 @DevOps выполнен (деплой пакетом):** коммит **`4cde1bc`** (push origin/master, прод `/var/www/admin_bot` fast-forward), `systemctl restart admin_bot` → **active**, `/api/health` = **200**, `APP_VERSION` **2.58.6**, `database is locked` = **0**. **⏳ Открыто:** только **live-гейты владельца** (F2 **T-2561**, F3 live-приёмка, hotfix5 live-проверка) — **НЕ выполнены**. Ранее открытые live-гейты F1 (T-2409), hotfix-медиа (T-2463/T-2472/T-2479), P0-fix, hotfix3 (T-2505), hotfix4 (T-2527) — остаются за владельцем.
> **Waiver/техдолг:** для F3 и hotfix5 Шаг 2 @Architect формально **не оформлялся** → артефакты восстановлены **ретро** (Шаг 8 @PM); процессный техдолг зафиксирован в ADR-1025-10/-11. Остаточный техдолг Волны 1 — §57.5 (F2 M-3, L-1/-2/-4, NEW-L1/-L2; hotfix5 L10.25H5-1/-3; F3 L-F3-1/-2/-4; Playwright-матрица не воспроизведена — нет `playwright`). **Следующий шаг — F4 `module-catalog-quickpanel-store-round1025`** (Волна 2, зависит от F2/F3) → F5–F11 → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. **R17/R18:** секреты не цитировались; `current_task.md` не трогался; теги/бэкапы `pre-round1025*` и `stash@{0}` **НЕ удалять**.
>
> **✅ ФИЧА (Wave 0) ЭПИКА 10.25 (Step 10 @Memory, 20.09.2026): `F0 f0-config-bugfixes-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED.** Раунд **10.25 (Эпик 1 «Liquid Glass Control Center»), Wave 0** (P0, выполнялся ДО F1 «не переносить неисправный механизм сохранения в новые компоненты»); ниже — блок завершённого эпика 10.24. Архитектура — `plans/ARCHITECTURE.md` **§52** (Merge @Architect) + **§52.8** (техдолг F0); архив — `plans/archive/f0-config-bugfixes-round1025/` (`spec.md` + **4 ADR** `adr-1025-2-save-state-machine`/`adr-1025-3-anticliche-semantics`/`adr-1025-4-toasts-savebar`/`adr-1025-5-db-lock-resilience` + `tasks.md`, **T-2410…T-2455, 46 задач**).
>
> **📌 5 блоков:** **F0.1** единый `persistItems()` + честный **409** (первопричина: одно действие = **две** мутации `prompts.verbilizer_default_mode` с одним optimistic-токеном — `savePromptFallbackMode` без `await` + sticky-SaveBar `dirtyItems` → 0 строк `UPDATE` → `ChatParamsConflict` → 409 при 3 противоречивых сообщениях; решение: client state-machine `loading|clean|dirty|saving|saved|error|conflict`, idempotent short-circuit 409→200 `revalidated`, сериализация (`asyncio.Lock` per `chat_id` + PG `pg_advisory_xact_lock`), **без авто-retry**); **F0.2** аудит **14** механизмов сохранения `load→edit→save→re-read→compare` (**HTTP 200 ≠ подтверждение**); **F0.3** анти-клише — разведение **capacity (БД, `limits.anticliche_max_patterns`=200)** vs **per-run (env-only `ANTICLICHE_MAX_PATTERNS_PER_RUN`=40)**, дедуп против БД/партии, «0 новых» ≠ «ошибка модели», 8 событий `ANTI_CLICHE_*`; **F0.4** одно итоговое уведомление на операцию (`notify(operationId, result)`, `err>warn>ok`, очередь ≤3, safe-area) + SaveBar/`saveState`; **🆕 F0.5** устойчивость к `database is locked` (**AMEND ADR-1024-18**): bounded retry (`_LOCK_RETRIES=3`, backoff 0.1/0.2/0.4с, **только** `locked`) + single-writer (`write_transaction`), PRAGMA-паритет, `event=*_lock_exhausted` + счётчик (fail-open — **последний** рубеж), kill-switch env-only `DB_LOCK_RESILIENCE_ENABLED` (**default ON**); `smart_cache` не дублируется/не трогается.
>
> **Процесс:** @Reviewer — **3 итерации** (Changes Requested → Changes Requested → **Approved**); @Builder — **3 rework-цикла** (Reviewer iter1, Reviewer iter2, Scanner `H-1`); @Scanner — **2 прохода** (итер.1: **0 Critical / 1 High** `H-1` `saveBlock` ложный «Сохранено» / 3 Medium / 8 Low; итер.2: **0 Critical / 0 High**). Отчёты: `plans/reports/round1025_f0_scanner_audit.md`, `plans/reports/f0-round1025-report.md`, `plans/reports/f0-save-audit-round1025.md`, `plans/reports/f0-5-db-lock-round1025.md`.
>
> **Финальные числа:** pytest **7911/0 → 7946 passed / 0 failed** (**+35**); JS **19/19**; **Δ DDL = 0** (SQLite `user_version=12`); **Δ каталога = 0** (REGISTRY **459** / Settings **418** / GROUPS **98** / `_TAB_BY_GROUP` **96** / TAB_RULES **21**); `smart_cache` не тронут; промпты не менялись.
>
> **Деплой (Step 9 @DevOps):** commit **`3a91c84`** (push origin/master), прод `/var/www/admin_bot` fast-forward **`da561bc..3a91c84`**, `systemctl restart admin_bot` → **active**, `/api/health` = **200**. **Live:** **T-2454** ✅ **подтверждён** (до деплоя за 24ч — **633** записи `database is locked` от `summary_memory`; после рестарта — **0**, `*_lock_exhausted` не срабатывал); **T-2433** ⏸ (воркер `AntiClicheWorker` зарегистрирован, кэш fresh `count=20/200`, форс-пополнение до 200 **не запускалось** — ждёт владельца); **T-2419** ⏸ (ручная проверка владельцем в TMA, Fallback/409). **Техдолг:** `tech-debt-round10.25` (**M-2** global per-key optimistic не прокинут в UI; **I-2, I-4, L-2, L-7, L-8**; §52.8). **Релиз/метрика:** `release-round1025-f0`, `metric-snapshot-round1025-f0`. **KG:** ⚠️ граф смешанный (содержит устаревший/сторонний подграф `AdminBot` v2.x + `voxy-*`), но узлы раундов 10.24/10.25 присутствуют и рабочие — сущности F0/ADR/релиза записаны, чистка чужих узлов не выполнялась. **R17/R18:** секреты не цитировались/не коммитились, `current_task.md` не трогался; бэкапы `var/backups/web-round1025-f0-*` и теги `pre-round1025*` **НЕ удалять** до утверждения владельца.
>
> **🔥 ASAP-ХОТФИКС (внеплановый, между F0 и F1) — Step 10 @Memory, 21.09.2026: `hotfix-media-tma-round1025` — COMPLETED + MERGED + DEPLOYED + ARCHIVED.** Архив — `plans/archive/hotfix-media-tma-round1025/` (`spec.md` + `adr-1025-6-bot-api-local-mode.md` + `tasks.md`, **T-2456…T-2481, 26 задач**); интеграция — `plans/ARCHITECTURE.md` **§53**; аудит — `plans/reports/round1025_hotfix_scanner_audit.md`. KG: `HOTFIX hotfix-media-tma-round1025`, `ADR-1025-6`, `bot-api-local-mode`, `release-round1025-hotfix`, `metric-snapshot-round1025-hotfix`, `tech-debt-round10.25-hotfix`, `provider-nano-gpt`.
> **Причины (4, диагностика — данность):** (1) контейнер `telegram-bot-api` **без** `--local` → облачный `getFile` = **20 МБ** (медиа/транскрибация; **НЕ связано с F0**); (2) LLM `ReadTimeout` — внешний провайдер **`nano-gpt.com`** (primary + резерв одновременно; хроническое с 15.09.2026, 167 случаев/сутки) — **НЕ связано с F0**; (3) cache-bust `?v=2.58.0` не менялся при F0-деплое → stale `app.js` в TMA (`ReferenceError` в config-разделах ИИ/Модули/Память, Статус/Справка живы); (4) логи без текста причины (только класс исключения).
> **Фиксы:** единый рубильник **`TELEGRAM_LOCAL`** (непустое → `--local`, getFile до **2000 МБ**; контейнер + хостовый процесс читают один `.env`; `0` ≠ «выключено») + **эффективный гейт размера** (`handlers/youtube.py:160-197`: `LOCAL_GETFILE_LIMIT_MB=2000` / `CLOUD_GETFILE_LIMIT_MB=20`, `min(configured, ceiling)`, ранний гейт до `fetch`, фраза с фактическим лимитом `video_too_big_phrase(limit_mb)` + пул `VIDEO_MEDIA_PROVIDER_TIMEOUT_PHRASES`); `local_file_path` — traversal-guard (`_is_within_root`, fail-closed); **R17-логи причин** (`_safe_exc_text`, `_provider_host` = hostname; логика ретраев не менялась); cache-bust `APP_VERSION` **2.58.0 → 2.58.1** (+`README.md`, `?v=` у tailwind/app.css/app.js + `telegram-init.js`; нужен рестарт `admin_bot`).
> **Процесс:** @Reviewer **2 итерации** (Changes Requested → **Approved**); @Builder **1 rework** (ревью-итерация `ee23e47`); @Scanner **1 проход** — **Critical 0 / High 0**, **2 Medium** (`M-1` R17-лог медиа со `<bot_id>:<token>` — маскируется глобальным `SecretMaskFilter`; `M-2` двойной рубильник `TELEGRAM_LOCAL` ↔ `DOWNLOAD_ENABLED`) + **4 Low** (`L-1` win32-тавтологичные тесты, `L-2` `?v=` для 3 vendor-скриптов, `L-3` нет пост-скачивающей проверки `_downloaded_too_big`, `L-4` бланкетный `*.zip`) + Info 4.
> **Числа:** pytest **7946 → 7976 passed / 0 failed** (**+30**), JS **19/19**; **Δ DDL = 0** (SQLite `user_version=12`), **Δ каталога = 0** (в `config/settings.py` менялся только `APP_VERSION`); F0 не тронут; Эпик 2 не тронут; `git diff --check` exit 0.
> **Деплой (Step 9 @DevOps):** commits **`8b16c4a`** (ядро) + **`ee23e47`** (ревью-итерация) + docs **`65e39fb`** (origin/master); прод `/var/www/admin_bot` → **`65e39fb`**; `TELEGRAM_LOCAL=1` + рестарт `telegram-bot-api` и `admin_bot`; `APP_VERSION` **2.58.1**; `/api/health` = **200**; `database is locked` = **0**; WAL **159 МБ → 0**. Откат: тег `pre-round1025-hotfix` + `git revert` (медиа — вернуть `TELEGRAM_LOCAL` в облако; cache-bust — вернуть версию + повторный bump).
> **Live-гейт владельца (⏳ post-deploy, НЕ выполнено):** **T-2463** ⏸ (тестовое видео **> 20 МБ** — нужен файл от владельца), **T-2472** ⏸ (ручная проверка консоли TMA — нет `ReferenceError`, грузится новая версия ассетов), **T-2479** ⏸/✅ (частично: логи/health/WAL/версия подтверждены, сквозной live-тест — за владельцем). ✅ **T-2462** (локальный режим включён), ✅ **T-2480** (регрессий F0 нет).
> **Изоляция F1-WIP:** `git stash@{0}` (`wip(f1)`, **25 файлов**) + untracked F1 в `var/backups/f1-wip-20260921-015653/`; теги/бэкапы `pre-round1025*` **НЕ удалять** до утверждения владельца (R18). **Возврат — T-2481** (`git stash pop` + вернуть untracked поверх `65e39fb`; ожидаемые конфликты — `?v=`/`APP_VERSION` и `IA_V2_ENABLED`). **F1-WIP НЕ трогать до явной задачи.**
> **Техдолг:** `tech-debt-round10.25-hotfix` — **M-1**, **M-2**, LLM-таймауты/провайдер (T-2473/T-2474 открыты), RAM/swap/graceful-stop (`TimeoutStopSec`), `?v=` для 3 vendor-скриптов, точечный `.gitignore` (§53). **Следующий шаг — возврат к F1 (T-2481)** → F2–F11 → приёмка Эпика 1 (F10) → **Эпик 2** «Summary Hybrid Pipeline» (раунд 10.26) → **Эпик 3** «Agentic Intelligence». _(Актуально до завершения F1 — ниже.)_
>
> **✅ F1 ЭПИКА 10.25 (Wave 1) + P0-ФИКС (Step 10 @Memory, 21.09.2026): `F1-ia-shell-navigation-round1025` и `p0-fix-render-media-paths-round1025` — COMPLETED + MERGED + DEPLOYED + ARCHIVED.** Архитектура — `plans/ARCHITECTURE.md` **§54** (F1) + **§54.1** (P0-фикс); архивы — `plans/archive/ia-shell-navigation-round1025/` (`spec.md` + `adr-1025-1-ia-v2.md` D1–D8 + `tasks.md`) и `plans/archive/p0-fix-render-media-paths-round1025/tasks.md` (**FIX 1–4**; отдельного ADR нет).
> **F1 (IA v2 + app-shell):** новая IA §4 — «Память» (`#/memory`) вынесен из «ИИ» (`memory_rag`/`chat_lore`/`relations`; `TAB_NAV` 3 переноса; `NAV_ORDER = (modules, ai, memory, permsoc)`), «Сводка»→«Аналитика» (label; hash `#/oversight` без дублирующей главной), hash-роуты `#/memory/{rag,lore,relations}` + legacy-алиасы `#/ai/{...}`; shell: sidebar ≥1200 / drawer 768–1199 / bottom-nav <768 («Ещё»); kill-switch **`IA_V2_ENABLED`** (env-only `ClassVar`, default ON, вне `param_catalog` → Δ каталога = 0) через `GET /api/me.ui_flags` (ADR-1024-13), OFF → legacy-navbar байт-в-байт (**граница OFF — только nav-scope**). Атомарная миграция 13 маркер-тестов. @Reviewer **2** (Changes Requested → Approved); @Builder **2** rework (ревью-правки + Scanner H-1); @Scanner **2** прохода (итер.1: **0C / 1H** `H-1` «Ещё» недостижимо для не-админ ролей на mobile + **2M** + **4L**; итер.2: **0C / 0H**). pytest **7976 → 7996/0** (+20); JS **19 → 21/21**; Playwright §71 (10 вьюпортов × маршруты) — **0 нарушений**. **Δ DDL = 0**, **Δ каталога = 0** (459/418/434/98/96/21), F0/Эпик 2 не тронуты. Деплой **`fe0f7bb`** (код `ff34115`+`b1c87b0`+`78e612a`), `APP_VERSION` **2.58.2**, health 200.
> **P0-фикс после F1 (hotfix2):** (1) **render** — `stickyFieldFailed` **computed → methods** (регрессия F0 `d5750fc` → `TypeError` → пустые config-разделы ИИ llm/names/smart-cache/memory); (2) **container → host путь Bot API** — `normalize_api_file_path`/`read_host_file_bytes` (+`web/api/avatars.py`; traversal-guard `_is_within_root` **fail-closed сохранён**) → чинит видео/ГС/аватары; (3) `APP_VERSION` **2.58.2**; (4) усилена `tools/ui_round1025_matrix.py` (непустой config + AI-маршруты + FAIL на console/pageerror). @Reviewer **1** (Approved); @Scanner **1** проход — **0C / 0H** (**2M** → техдолг, **3L**). pytest **7996 → 8003/0** (+7); JS **21/21**; матрица **0** (впервые с непустым config). Деплой **`fea2daa`**; live: файл **28.7 МБ** (>20) на диске, нормализация → существующий host-файл, fail-closed сохранён, `database is locked` = **0**.
> **Техдолг:** `tech-debt-round10.25-f1-p0` — **M-1** (сырой `file_path` в логе медиа → `name`/`sanitize`), **M-2** (avatars `exc_info` — трейсбек не маскируется), **TOCTOU-guard**, vendor-скрипты без `?v=`, matrix `_config_stub` → ложно-зелёная, **T-2409** (очистка бэкапа — после утверждения владельца). **⏳ live-гейт владельца (post-deploy):** реальные видео/ГС/аватары + открытие разделов TMA. **Релиз/метрика:** `release-round1025-f1`/`metric-snapshot-round1025-f1`, `release-round1025-p0`/`metric-snapshot-round1025-p0`, KG `incident-2026-09-21-f1-render-media`. **Следующий шаг — F2 `design-tokens-liquidglass-v2` ∥ F3 `global-scope-selector`** → F4–F11 → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. **R17/R18:** секреты не цитировались; `current_task.md` не трогался; теги/бэкапы `pre-round1025*` **НЕ удалять**.
>
> **🔥 ASAP-ХОТФИКС-3 (внеплановый, после F1/hotfix2, перед F2) — Step 10 @Memory, 21.09.2026: `hotfix3-summary-stt-anticliche-round1025` — COMPLETED + MERGED + DEPLOYED + ARCHIVED.** Архив — `plans/archive/hotfix3-summary-stt-anticliche-round1025/` (`spec.md` + `adr-1025-7-summary-fallback-stt-anticliche.md` D1–D5 + `tasks.md`, **T-2482…T-2506, 25 задач**); интеграция — `plans/ARCHITECTURE.md` **§55**; аудит — `plans/reports/round1025_hotfix3_scanner_audit.md`. KG: `HOTFIX hotfix3-summary-stt-anticliche-round1025`, `ADR-1025-7`, `incident-2026-09-21-summary-stt-anticliche`, `release-round1025-hotfix3`, `metric-snapshot-round1025-hotfix3`, `tech-debt-round10.25-hotfix3`, `stt-audio-prep-compression`, `summary-cover-fallback-path`.
> **Причины (4, диагностика — данность):** **A** саммари уходило plain без обложки — Stage-1 «Редактор» (`parse_summary_handoff`, `services/summary_generator.py:480`) невалиден из-за таймаутов **`nano-gpt.com`** → «невалидная выжимка редактора — fallback» → одиночный путь → `cover_prompt=""` → `_deliver_rich` не вызывается (успешный rich-путь цел: логи 01:03/05:13/07:03); **C** анти-клише молча дропало ручные фразы (`build_patterns` `services/anticliche_worker.py:226-258`: длина <2/>120, хардкод-клише `find_forbidden_cliches`, дубли, cap), API отдавал 200 + уменьшенный `count`, UI всегда «Сохранено»; **B** STT: сырой файл **28 МБ** > лимитов провайдеров (Groq 25 / OpenRouter 20), извлечения/сжатия аудио не было; **D** хронические LLM-таймауты провайдера (24ч: `ReadTimeout=189`, `LLMTimeoutError=28`).
> **Фиксы (ADR-1025-7):** **A** — `services/system2_handoff.py::parse_summary_handoff_ex(raw) -> (dict|None, reason)` (`empty|invalid_json|invalid_digest|ok`); таймаут Stage-1 **не роняет** саммари; на fallback — **детерминированная** обложка (без доп. LLM-вызова) → **rich** через существующие `build_cover_media`/`send_rich_message`; plain — только с залогированной причиной; kill-switch **`SUMMARY_COVER_FALLBACK_ENABLED`** (env-only, default **ON**; OFF → plain байт-в-байт) — `config/settings.py:591-592`. **C** — канон длины **2…120** (`DYNAMIC_PHRASE_MIN/MAX`; UI `maxlength`/`limitClicheDraft` + подсказка), «лимит длины фразы» ≠ «число паттернов»; ручные фразы **не** фильтруются хардкод-правилами (помечаются `hardcoded`, сохраняются — «подводя итог» сохраняется); честный контракт API `{saved, dropped:{invalid,hardcoded,duplicate,over_limit}, count}` (200 ≠ «всё сохранено»); UI — warn «Сохранено N из M» + причины (единственная правка `web/app.js`). **B** — новый `SmartModule/transcriber/audio_prep.py`: ffmpeg **opus mono 16 kHz ~24 kbps** + **чанкинг-fallback** + очистка `tmp_dirs` (`shutil.rmtree`, fail-open); врезка в **`VoiceTranscriber.transcribe_voice`** (prep **до** семафора; покрывает видео и ГС/кружки), частичный результат при сбое чанка (`reason=partial`); лог `reason=compressed|chunked|no_ffmpeg|partial`; kill-switch **`STT_AUDIO_COMPRESS_ENABLED`** (env-only, default **ON**) — `config/settings.py:1392-1393`; сжатие только при `size_mb > max(limits)`. **D** — **`LLM_FALLBACK_TIMEOUT_SECONDS` 120 → 60** (таймаут **одной попытки**, не бюджет цепочки; логика/число ретраев не менялись) + `llm_stats` (`requests/timeouts/fallbacks` + доля) аддитивно в **`GET /api/status`** (`services/status_service.py:505-509,595`); второй резервный провайдер — **не внедряем** (корень провайдерский, эскалация владельцу).
> **Процесс:** @Reviewer **2 итерации** (Changes Requested → **Approved**; R-1…R-8 закрыты в `fb65965`); @Builder **1 rework-цикл**; @Scanner **1 проход** — **Critical 0 / High 0** (**2 Medium**: temp-каталог чанкинга → закрыт R-1 (`rmtree`); prep внутри семафора STT → закрыт R-5; семантика/именование `LLM_FALLBACK_TIMEOUT_SECONDS` (per-attempt vs бюджет цепочки) → R-8; **4 Low** + **1 Info** >999 частей).
> **Числа:** pytest **8003 → 8041 passed / 0 failed** (**+38**), JS **21 → 22/22**; **Δ DDL = 0** (SQLite `user_version=12`); **Δ каталога = 0** (флаги — env-only `ClassVar` вне `param_catalog`); F0/hotfix2/F1/P0-fix/Эпик 2/каноны промптов не тронуты; `git diff --check` exit 0. ⚠️ 5 средовых падений pytest в чужой среде (aiogram без rich-типов) — **не регрессия** (падают и на `fe0f7bb`).
> **Деплой (Step 9 @DevOps):** commits **`090d2e7`** (ядро) + **`fb65965`** (ревью R-1…R-8) + **`cfe7342`** (bump) → origin/master; прод `/var/www/admin_bot`; `APP_VERSION` **2.58.3**; `/api/health` = **200**; `database is locked` = **0**. **⚠️ docs-коммит hotfix3** (`ARCHITECTURE.md` §55 + `backlog.md` + перенос `plans/features/hotfix3-…` → `plans/archive/hotfix3-…`) на момент Step 10 — **в рабочем дереве, НЕ закоммичен** (HEAD `5f624cd` = docs F1/P0) → требуется docs-коммит (@DevOps/оркестратор). Откат: тег `pre-round1025-hotfix3` + `git revert` + флаги OFF (байт-в-байт прежнее поведение) + возврат `APP_VERSION`.
> **Live-гейт владельца (⏳ T-2505, post-deploy, НЕ выполнено):** (1) саммари с обложкой `article sent` (в т.ч. на fallback); (2) видео 28 МБ `reason=compressed` + расшифровка; (3) анти-клише «Сохранено N из M» (на уровне функций подтверждено: «подводя итог» сохраняется); (4) `llm_stats` в TMA; (5) `database is locked`=0; (6) консоль TMA без `ReferenceError`.
> **Техдолг:** `tech-debt-round10.25-hotfix3` — grep-JS-тест анти-клише (статический); реальный ffmpeg-прогон `-c copy` на 28 МБ (live); Info >999 частей; второй LLM-провайдер (не внедряем); семантика `LLM_FALLBACK_TIMEOUT_SECONDS`; **M-1** (сырой `file_path` в логе медиа → `name`), avatars `exc_info`, vendor `?v=`, TOCTOU-guard. **Следующий шаг — возврат к F2 `design-tokens-liquidglass-v2` ∥ F3 `global-scope-selector`** → F4–F11 → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. **R17/R18:** секреты не цитировались; `current_task.md` не трогался; теги/бэкапы `pre-round1025*` и `stash@{0}` **НЕ удалять**.
>
> **🔥 ASAP-ХОТФИКС-4 (внеплановый, после hotfix3, перед F2) — Step 10 @Memory, 21.09.2026: `hotfix4-cover-nav-shell-round1025` — COMPLETED + MERGED + DEPLOYED + ARCHIVED.** Архив — `plans/archive/hotfix4-cover-nav-shell-round1025/` (`spec.md` + `adr-1025-8-cover-style-viewport-shell.md` D1–D4 + `tasks.md`, **T-2507…T-2528, 22 задачи**); интеграция — `plans/ARCHITECTURE.md` **§56**; аудит — `plans/reports/round1025_hotfix4_scanner_audit.md`. KG: `HOTFIX hotfix4-cover-nav-shell-round1025`, `ADR-1025-8`, `incident-2026-09-21-cover-nav-shell`, `release-round1025-hotfix4`, `metric-snapshot-round1025-hotfix4`, `tech-debt-round10.25-hotfix4`, `cover-style-resolution`, `viewport-bottom-offset`.
> **Причины (3):** **A** `prompts.summary_cover_style` — **per-chat**-ключ, а саммари читало только глобальный `hot.get` → применялся дефолт `photorealistic, cinematic light` (31 симв); плюс конфликт «без надписей» в блоке Редактора; плюс пустой `draft.cover_prompt` глушил резервную обложку hotfix3. **B** нижняя панель/шторка уезжала (`.bottom-nav{bottom:0}` = layout-вьюпорт, `.app-shell` уже без бара; safe-area=0). **C** у админа «Справка» была не второй (в «Ещё»).
> **Фиксы (ADR-1025-8):** **A** — `_resolve_cover_style_text(chat_id)` (**chat override → global → default**, fail-open) по паттерну алиасов; self-contained канон Редактора (`PREV_SUMMARY_EDITOR_R1025_HOTFIX4`); фолбэк при пустом `cover_prompt`; маркеры `has_comic`/`has_heading`/`style_is_default` (R17, без текста). **B** — `--tg-viewport-bottom-offset` (`web/static/telegram-init.js`) + CSS-фолбэк + `viewport-fit=cover` + вертикальная проверка матрицы (`rect.bottom <= innerHeight`). **C** — `bottomNavItems` = `status`+`how` **первыми для всех**, ≤4; `mobileMoreItems` без дубля.
> **Процесс:** @Reviewer **2 итерации** (Changes Requested: корень не доказан — мок; → **Approved** после PG-backed теста); @Builder **1 rework**; @Scanner **1 проход** — **Critical 0 / High 0** (**Medium**: JS-тест дублировал формулу; **Low**: guard `stableH>0`, CSS-фолбэк, `has_heading`, `viewport-fit` OFF-скоуп L10.25H4-4).
> **Числа:** pytest **8041 → 8071 passed / 0 failed** (**+30**); JS **22 → 23/23**; матрица **0**; **Δ DDL = 0**, **Δ каталога = 0** (правки только метаданных существующего ключа); F0/F1/P0-fix/hotfix-медиа/hotfix3/Эпик 2 не тронуты.
> **Деплой (Step 9 @DevOps):** **`55f286f`** + **`072800a`** + **`f458b8c`** + **`acd538c`**, docs **`f2328fb`**; `APP_VERSION` **2.58.4**; `/api/health` = **200**; `database is locked` = **0**. Live-факт: у чата есть per-chat override стиля (len=62, `has_comic`/`has_heading`) — подтверждает корень A. Откат: тег `pre-round1025-hotfix4` + `git revert` (+ возврат `APP_VERSION`).
> **Live-гейт владельца (⏳ T-2527, post-deploy, НЕ выполнено):** обложка с авторским стилем (`article sent`, маркеры не-дефолт); панель/шторка в экране; «Статус»+«Справка» первыми.
> **Техдолг:** `tech-debt-round10.25-hotfix4` — fake-pool в `test_pg_backed`; доп. async `get_chat_param` на путь обложки (TTL 120с); реальный ffmpeg-прогон 28 МБ; grep-JS-тест анти-клише; второй LLM-провайдер; **M-1** лог `file_path`; avatars `exc_info`; vendor `?v=`; TOCTOU. **Следующий шаг — возврат к F2 `design-tokens-liquidglass-v2` ∥ F3 `global-scope-selector`** → F4–F11 → приёмка Эпика 1 (F10) → **Эпик 2** (10.26) → **Эпик 3**. **R17/R18:** секреты не цитировались; `current_task.md` не трогался; теги/бэкапы `pre-round1025*` и `stash@{0}` **НЕ удалять**.
>
> **✅ ЗАВЕРШЁННЫЙ ЭПИК (Step 10 @Memory, 20.09.2026): `Epic round1024 (Disaster Recovery: UI & Backend Bloat)` — COMPLETED + DEPLOYED + ARCHIVED.** Архитектура — `plans/ARCHITECTURE.md` **§51** (итог/ADR-карта/SUPERSEDE-AMEND-карта, Merge @Architect) + **§50** (F16, YouTube-пайплайн); спеки/ADR — `plans/archive/*-round1024/` (**24 папки**; 23 с `ADR-1024-N`, F23 без ADR; `ADR-1024-13` — сквозной без файла). **Деплой:** feature-HEAD **`cf98b99`** + docs-коммит **`da561bc`** (Merge §51, архивация 24 фич, Scanner-аудит, техдолг, метрики); push **`00eab85..da561bc`**; прод `/var/www/admin_bot` → **`da561bc`**; `systemctl` **active**; `/api/health` + `/healthz` = **200** (**`version=2.58.0`**); aiogram **3.31.0**; PG **19 таблиц**; SQLite **`user_version=12`** (Δ DDL=0). **Финальные числа:** pytest **7911 passed / 0 failed** (baseline 7424 → **+487**; 1 сторонний `StarletteDeprecationWarning`); каталог **REGISTRY 459** (Δ+2 к 10.23), Settings **418**, GROUPS **98**, `_TAB_BY_GROUP` **96**, `TAB_RULES` = `TAB_NAV` = `CONFIG_TAB_TITLES` **21** (F5 `mod_images`), JS MODULES **13**, TABS **26**; **SQLite v12 (Δ DDL=0)**; PG **Δ DDL=0**; `DDL_STATEMENTS` **45**; **APP_VERSION 2.57.0 → 2.58.0**; **канон инструментов R9 9 → 10** (`transcribe_video`, 10-й; первые 9 байт-в-байт). **200 задач T-2188…T-2387 / ADR-1024-1…-24** (отменены владельцем T-2191/T-2192 — embeddings, UPD3 №7). **Ремонт бюджетов целевого чата `-1002661910336` (F20–F22):** `manage.py audit-chat-overrides` → **`ok=8 / absent=0 / different=0`** (seed применён при старте из `config/chat_settings_seed.json`; JSONL-аудиты в `var/audit/`); F20 (Critical) подтверждён live — одиночный save **не стирает** остальные per-chat значения. **Диск (F9):** до `used 17G / avail 5.8G`, `backups` **3.0 GiB**; `cleanup --apply` удалил **3 старых `memory_rebuild_*.db` = 2.2 GiB** (история/`media/**`/SQLite/`.env` **не тронуты** — immutable); после `used 15G / avail 8.0G`, `backups` **788.6 MiB**. **Ключевые фиксы:** F20 (Critical merge-фикс per-chat), F21 (master-тумблер `flags.budgets_enabled`, OFF = не ограничивать, учёт вёдётся), F22 (ремонт seed-overrides + fail-loud CLI), F9 (retention «история неприкосновенна»: 1 бэкап БД, логи 7 дней), F16 (YouTube download→мультимодалка→субтитры), F19 (инструмент транскрибации, канон 10), F13/F14 (медиа-маркер/native-first), F24 (fullscreen-sync/реактивный аккордеон). **Процесс:** @Reviewer — Approved по фичам, **~45 прогонов** (2 у большинства; 3 — F5/F11/F19; 1 — F13/F17/F18/F20; F23 — iter1 `Changes Requested` → fix `cf98b99`, подтверждено); @Builder — **~22 цикла доработок**; @Scanner — **0 Critical / 0 High / 0 Medium**, открыто **3 Low (L10.24-1/-2/-3) + 5 Info (I10.24-1…-5) + 2 деплой-пункта** (`--strict` семантика исторических вайпов F22; `var/` требует root F9). **Техдолг:** `tech-debt-round10.24`. **Metric:** `metric-snapshot-round1024-final`. **Release:** `release-round1024`. **Закрыто раундом:** техдолг 10.23 **I2**, **S10.19-24** (Won't Fix — история неприкосновенна), ложное закрытие 10.22 F2 (алиасы — RE-OPEN + live-доказательство). **Архив (Step 8 @PM):** `plans/archive/<feature>-round1024/` — **24 папки** + сквозные доки `round1024-architecture.md` / `round1024-web-architecture.md` / `round1024-upd4-architecture.md` → `plans/archive/`; `plans/features/` — только 6 backlog-папок; R18-скан чист. **⏸ Ручные приёмки владельца (живые, не блокеры): F4/F5/F6/F10/F11/F16/F19/F24** (Telegram/TMA). **R17/R18:** SSH/креды и значения секретов **не цитировались и не коммитились**; `plans/current_task.md` (untracked, `.gitignore`) не трогался; R17 — **Risk Accepted** (ротация SSH не делалась); R18 в силе. Предыдущий раунд — **10.23** (COMPLETED + DEPLOYED + ARCHIVED, `4314ea4`).
>
> **✅ ЗАВЕРШЁННЫЙ ЭПИК (Step 10 @Memory, 19.09.2026): `Epic round1023 (Adaptive System 2, Token Analytics, Anti-Cliche Cache & Image Generation)` — COMPLETED + DEPLOYED + ARCHIVED.** Архитектура — `plans/ARCHITECTURE.md` **§49** (итог/ADR-карта/SUPERSEDE-AMEND-карта, Merge @Architect); спеки/ADR — `plans/archive/*-round1023/`. **Деплой:** commit **`8dadbe3`** (feat/фиксы) + **`4314ea4`** (docs/plans: архивация 9 фич + Merge §49 + Scanner-аудит); push **`731a845..4314ea4`**; HEAD **`4314ea4`**; прод `/var/www/admin_bot` → **`4314ea4`** (`git pull --ff-only`); venv aiogram обновлён (**≥3.31.0**); `.env` += `IMAGE_API_KEY` (значение не фиксируется, R18) + `IMAGE_BASE_URL=https://gen.pollinations.ai/v1`; `systemctl restart admin_bot` → **active**; `/api/health` + `/healthz` = **200**; `canon=5 delivered=5`, `guide=2 delivered=2`; воркер `AntiClicheWorker` зарегистрирован (`interval_days=7`); SQLite **`user_version=12`** (Δ DDL=0; PG +3 таблицы: `anticliche_cache`/`llm_usage_events`/`llm_model_prices`). **Финальные числа:** pytest **7424 passed / 0 failed** (baseline 6962 → **+462**; 1 сторонний `StarletteDeprecationWarning`); каталог **REGISTRY 457** (Δ+18: F2 +2/F5 +5/F6 +1/F8 +10), Settings **416**, categorized **432**, GROUPS **96**, `_TAB_BY_GROUP` **94**, TAB_RULES **20**; `INFO_CANON_VERSION=5`; `GUIDE_CANON_VERSION=2`; aiogram **`>=3.31.0`**; APP_VERSION **2.57.0** (без бампа). **90 задач T-2097…T-2186 / ADR-1023-1…9 (Accepted/реализованы).** Предыдущий раунд — **10.22** (COMPLETED + DEPLOYED + ARCHIVED, `a8a6437`).
>
> **9 фич F1–F9:** **F1** `target-message-marking` (P0, маркировка целевого сообщения-триггера в обоих рендерерах + правило в 3 Stage-1 Синтезаторах); **F2** `factcheck-deep-context` (P0, двунаправленное окно before/after + граф реплаев + обязательный веб-поиск; Δ каталога +2); **F3** `verbalizer-response-modes` (P0, `response_mode` casual/serious/deep_research строго в Stage-1 + канальные блоки); **F4** `dynamic-anticliche-cache` (P1, недельный воркер → PG-кэш → ДЕТЕКТОР клише; фикс S10.22-4b); **F5** `image-generation-tool` (P1, `generate_image` + Pollinations.ai/flux + UI); **F6** `summary-cover-rich-article` (P1, `cover_prompt` + «Стиль обложки» + Article `sendRichMessage` + тихий фолбэк); **F7** `token-analytics-dashboard` (P1, PG `llm_usage_events`/`llm_model_prices` + correlation-id + дашборд); **F8** `ui-verbilizer-tabs` (P1, Синтезатор/Вербализатор + Tabs режимов + мониторинг клише; Δ каталога +1 группа/+10 ключей); **F9** `help-ui-v5` (P2, Справка v4→v5 + версионирование гайда). **Порядок:** `F1 → F2 → [F3 ∥ F5] → F4 → F6 → F7 → F8 → F9`.
>
> **ADR-1023-1…9 (Accepted):** -1 маркировка (`services/target_marking.py`, сопоставление по `tg_message_id`, байт-в-байт legacy, антиэхо); -2 окно/граф фактчека (депрекейт legacy-ключа → миграция в `before`, общий `services/thread_chain.py`, глубина без нового ключа); -3 `response_mode` в Stage-1 = ровно 2 LLM-вызова (fail-safe `serious`, `parse_summary_handoff`); -4 динамический список питает детектор, не промпт/scrubber (PG `anticliche_cache`, литеральные фразы `re.escape`, коды `dyn_<sha1[:8]>`); -5 image-тул (Bearer, `flux`, `response_format=url`, секрет только env/PG, байты вместо keyed-URL, `SEND_ALLOWLIST`); -6 Article `InputRichMessage(html + media)`, egress `send_rich_message`, тихий фолбэк; -7 **DDL аналитики в PostgreSQL** (AMEND Part 1: Δ SQLite=0, остаётся v12; correlation-id stage1/tool/stage2/image); -8 UI-табы + PG-редактируемые Stage-1/2 промпты (freeze меню, TAB_RULES Δ=0); -9 Справка v5 + `GUIDE_CANON_VERSION=2` + версионирование гайда.
>
> **Процесс:** @Reviewer — **Approved 9/9**, всего **21 прогон** (F1=2, F2=3, F3=3, F4=2, F5=2, F6=2, F7=2, F8=2, F9=3); @Builder — **12 циклов доработок + 1 scanner follow-up**; @Scanner — **0 Critical / 0 High** (2 Medium: M1 correlation-id изображений + M2 изоляция `response_mode` в Stage-2 — закрыты follow-up `8dadbe3`, +6 регресс-тестов); открыто **4 Low (L1–L4) + 4 Info (I1–I4)**. Отчёты: `plans/reports/round1023_scanner_audit.md`, `plans/reports/round1023_f1…f9_reviewer.md`, `plans/reports/global_map.md` (Round 10.23), `plans/reports/audit_backlog.md`. **Constraints:** `response-mode-router-stage1-only-round1023`, `anticliche-feeds-detector-not-prompt-round1023`, `analytics-ddl-in-pg-round1023`, `channel-markup-rules-round1023`, `aiogram-min-3-31-round1023`, `target-message-marking-rule-round1023`, `shared-file-staging-round1023`. **Risks:** `risk-image-key-leak-round1023` (Critical), `risk-plain-tables-parseerror-round1023` + `risk-aiogram-version-rich-media-round1023` (High), 4×Medium + 1×Low (`risk-token-analytics-failopen-round1023`) — все mitigated. **ExternalDependency:** `pollinations-ai`, `telegram-sendRichMessage-api`. **Техдолг:** `tech-debt-round10.23` (L1–L4, I1–I4; закрыт S10.22-4b). **Metric:** `metric-snapshot-round1023-final`. **Release:** `release-round1023`. **Архив (Step 8 @PM):** `plans/archive/<feature>-round1023/` — **9 папок** (`spec.md` + `tasks.md` + `ADR-1023-N`) + `plans/archive/round1023-architecture.md`; `plans/features/` — только 6 backlog-папок; R18-скан чист. **⏸ Ручные приёмки владельца (живые, не блокеры):** **T-2135** (F4 — воркер/UI клише), **T-2146** (F5 — генерация), **T-2156** (F6 — Article+обложка), **T-2175** (F8 — UI-табы/монитор), **T-2182** (F9 — Справка v5). **R17/R18:** SSH-креды и значение `IMAGE_API_KEY` не цитировались; `current_task.md` untracked не коммитился; R17 — **Risk Accepted** (ротация SSH не делалась); R18 в силе.
>
> **✅ ЗАВЕРШЁННЫЙ ЭПИК (Step 10 @Memory, 19.09.2026): `Epic round1022 (True System 2 Pipeline & UI Help)` — COMPLETED + DEPLOYED + ARCHIVED.** Архитектура — `plans/ARCHITECTURE.md` **§48** (итог/ADR-карта/SUPERSEDE-AMEND-карта). **Деплой:** commit **`2d153b5`** (feat: True System 2 Pipeline) + **`a8a6437`** (docs/plans: архивация 8 фич + Merge §48 + Scanner re-audit); push **`acd9311..a8a6437`**; HEAD **`a8a6437`**; сервер `/var/www/admin_bot` → **`a8a6437`**; `systemctl` **active**; `/api/health` + `/healthz` = **200**; SQLite **`user_version=12`** (Δ DDL=0); `INFO_CANON_VERSION=4`; env-флаги default ON (`SYSTEM2_*`, `TELEGRAM_SEND_GUARD_ENABLED`, `DOSSIER_REBUILD_UI_ENABLED`). **Финальные числа:** pytest **6962 passed / 0 failed** (baseline 6779 → **+183**); каталог **439/409/414/92/90/20** (**Δ=0**); **SQLite v12 (Δ DDL=0)**; APP_VERSION **2.57.0** (без бампа). **78 задач T-2019…T-2096 / ADR-1022-1…8 (Accepted/реализованы).**
>
> **Боевой прогон пересборки досье (чат `-1002661910336`, окно 4320ч):** CLI-отчёт `scanned=451 cleaned_facts=441 protected_belief_sources=10 rebuilt=2 window_hours_used=4320 backup=yes`; confirmed target-факты **451 → 10** (cleaned=441), `dossier_portrait` **0 → 12**, `chat_meme` **0 → 2**; beliefs **71/41** и nodes/edges/overrides — без изменений; `smart_messages` **не удалялись** (+живой трафик). JSONL-архив `memory_generated_confirmed_20260918_144249_877827.jsonl` (441 строка) + авто-бэкап 802 МБ; старый мусор в portraits/memes = **0**.
>
> **Процесс:** @Reviewer — **2 итерации `Needs fixes` → Approved (3-я)**; @Scanner первично **0 Critical/0 High** (2 Medium `S10.22-1/-2` + 4 Low + 3 Info) → re-audit **0 Critical / 0 High / 0 Medium / 0 Low открыто** (1 Info **S10.22-4b**); @Builder — **3 фикс-раунда** (2 по @Reviewer + 1 пост-скан). Отчёты: `plans/reports/round1022_scanner_audit.md`, `plans/reports/audit_backlog.md`, `plans/reports/global_map.md`.
>
> **Архив:** `plans/archive/<slug>-round1022/` — **8 папок** (`spec.md` + `tasks.md` + `ADR-1022-N`) + `plans/archive/round1022-human-gate-map.md`; `plans/features/` — 6 backlog-папок (round1022 отсутствует). **⚠️ Follow-up техдолг:** **S10.22-4b** (Info: `as_ai` при запятой), **CLI `memory` берёт LLM-ключ из `.env`, а не из PG** (root cause 401 первого прогона — нужна синхронизация `.env`/ConfigCache в CLI), **vec-слой F8 не восстанавливается** (best-effort, embeddings не в снапшоте), **stale-lock TTL** 6ч; ⏸ живые приёмки **T-2069** (F6: ответ без тегов) и **T-2089** (F8: TMA прогресс/reopen/cancel+rollback) — за владельцем.
>
> **🗂 ИСТОРИЧЕСКИЙ СНИМОК (Step 3 @Memory, 18.09.2026) — УСТАРЕЛ (актуальный статус — в блоке «✅ ЗАВЕРШЁННЫЙ ЭПИК» выше): раунд `10.22 (True System 2 Pipeline & UI Help)` — UPD3 Human Gate пройден, spec/ADR/граф синхронизированы; код и tasks НЕ начаты.** ТЗ — `plans/current_task.md` **§UPD3 (строки 245–271)** (untracked, `.gitignore:70`; содержит plaintext SSH-креды — в git **НЕ коммитить**, значения **НЕ цитировать**, R17/R18). **Baseline:** HEAD **`acd9311`** (= origin/master, дерево чистое); pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION **2.57.0**; прод 10.21 (**`a923310`**, PID **3023258**). **8 фич / ADR-1022-1…8 (Accepted) / задачи T-2019…T-2096 / Δ каталога = 0 / DDL = 0 (SQLite остаётся v12).** Порядок: **[F1 ∥ F2 ∥ F6] → [F3 → F4 → F5] → F7**; **F8 зависит от F1/F2**. Карта гейта — `plans/features/round1022-human-gate-map.md` (Д-1…Д-11 закрыты).
>
> **Фичи:** F1 `urgent-rebuild-dossiers-target-chat` (боевой rebuild целевого чата `-1002661910336`, вариант (а), окно **180 дней**, **confirmed-cleanup** `graph_facts` `kind='fact' AND status='confirmed' AND target_user != ''` + JSONL-архив + защита `source_ids` живых beliefs); F2 `urgent-summary-aliases-ui` (фикс рендера JSON-объекта алиасов на фронте, restore запрещён); F3/F4/F5 `system2-*-two-call` (фактчек/саммари/direct chat → **2 физических LLM-вызова**, fallback на 10.21 + Validator Loop); F6 `telegram-send-regex-guard` (единый egress `services/outgoing_guard.py`: тихо режет только `<thought>`/`fact:\d+`/`msg:\d+`; клише → детектор `services/negative_constraints.py` + **браковка → повтор Вербализатору, max 2 ретрая**, флаг `SYSTEM2_VALIDATOR_LOOP_ENABLED` ON); F7 `help-ui-system2` (полная переписка Справки, `INFO_CANON_VERSION 3→4`); **F8 `dossier-rebuild-async-ui`** (кнопка «Пересобрать досье» 30/90/180/всё, async job-store `services/dossier_rebuild_jobs.py` без DDL, прогресс «X/Y чанков», persistence при reopen, отмена = rollback из стартового снапшота, `interrupted` при рестарте, конкурентность per (chat,user), флаг `DOSSIER_REBUILD_UI_ENABLED` ON).
>
> **Constraints:** `physical-two-call-pipeline`, `regex-strip-before-send`, `raw-history-immutable` (не снят), `validator-loop-cliche`, `confirmed-cleanup-jsonl`, `dossier-job-persistence`. **SpecDecision UPD3:** вариант (а)/180 дней; вето на `string.replace` для клише (Validator Loop вместо хардкода); async job + progress + rollback; confirmed-cleanup. **Risks:** `risk-confirmed-cleanup-overdelete` (Critical, mitigated), `risk-dossier-job-interrupt` (High, accepted), `risk-validator-loop-false-positive` + Step-0 `risk-target-chat-rebuild-guard` (понижен до operational), `risk-summary-aliases-overwrite`, `risk-two-call-cost-latency`, `risk-help-canon-migration`, `risk-strip-regex-false-positive`. **Техдолг:** `tech-debt-round10.22` (авто-resume jobs, orphan-edge GC). Полная семантическая карта — KG (`Epic round1022` + `round-1022` + `feature-*`/`ADR-1022-*`); архитектура — `plans/ARCHITECTURE.md` (мержится на Step 7).
>
> **🗂 ИСТОРИЧЕСКИЙ СНИМОК (Step 0 @Memory, 18.09.2026) — УСТАРЕЛ (актуальный статус — в блоке «✅ ЗАВЕРШЁННЫЙ ЭПИК» выше): `round1022 (True System 2 Pipeline & UI Help)` — RECON / HISTORICAL CONFLICT CHECK выполнен, spec/tasks/код НЕ начаты.** ТЗ — `plans/current_task.md` §UPD2 (стр. **170-241**; untracked, `.gitignore:70`; содержит plaintext SSH-креды — в git **НЕ коммитить**, значения **НЕ цитировать**, R17/R18). **Baseline:** HEAD **`acd9311`** (= origin/master, дерево чистое); pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION **2.57.0**; прод 10.21 (**`a923310`**, PID **3023258**). **2 срочные проблемы + эпик:** (P1) боевой чат **`-1002661910336`** не пересобран — Досье Никиты со старым мусором; (P2) в UI пусто `limits.summary_aliases`; (Часть 1) физический конвейер из **двух независимых LLM-вызовов** для **фактчекера** (Аналитик→Вербализатор), **саммари** (Редактор→Рассказчик), **direct chat** (Синтезатор тулов→Вербализатор) + Negative Constraints + **Python-middleware** перед отправкой Telegram (вырезать `<thought>`, `fact:\d+`, `msg:\d+`); (Часть 2) переписать «Справку» (blockquote/h1-h2, убрать п.11 «безлимиты», транскрипт vs выжимка, блок «Как бот думает (System 2)»). **⚠️ HISTORICAL CONFLICT CHECK (факты по коду):** (1) P1-блокер — guard `_memory_scope` (`manage.py:848-869`): целевой чат требует `--chat <id> + --allow-target-chat`, иначе `SystemExit`; вторично — окно `--window-hours=168`/`--limit=500` (`manage.py:682-683`, `lore_worker.py:704-710`); инвариант сырой истории **сохраняется** (`RAW_HISTORY_TABLES`, `memory_rebuild.py:55-82`); (2) P2 — миграции 10.19-10.21 `summary_aliases` **не трогают** (grep 0 совпадений); API отдаёт `widget` всегда (`routes.py:365`), фронт-binding цел (`app.js:3544-3551/6334-6344`); вероятнее значение в PG пусто/`{}` или per-chat override `{}` целевого чата перекрыл global; (3) «Справка» — **не React/Vue**, а **код-канон** `DEFAULT_INFO_TEXT` + `INFO_CANON_VERSION=3` (`services/info_service.py:145-225`), PG-key `content.info_how_it_works`, рендер `web/index.html:2564-2608`; правка требует бампа версии + `KNOWN_INFO_SNAPSHOTS` + байт-тест `info_text.md`; (4) `strip_reasoning_tags`/`cleanup_llm_text` **уже есть** (`reply_postprocess.py`/`summary_cleanup.py`), но **вырезания `fact:\d+`/`msg:\d+` в отправке Telegram НЕТ**, единого chokepoint отправки нет; (5) 10.21 F2 grounding+CoVe — в **ОДНОМ** вызове, 10.22 заменяет на **два физических** (AMENDS). **Предварительные feature-папки:** `urgent-rebuild-dossiers-target-chat-round1022`, `urgent-summary-aliases-ui-round1022`, `system2-factcheck-two-call-round1022`, `system2-summary-two-call-round1022`, `system2-direct-chat-two-call-round1022`, `telegram-send-regex-guard-round1022`, `help-ui-system2-round1022`. **KG:** Epic + 7 Feature + 3 ArchitecturalConstraint (`physical-two-call-pipeline`, `regex-strip-before-send`, `raw-history-immutable`) + 5 Risk + SpecDecision `round1022-p1-rebuild-target-chat` + `tech-debt-round10.22` + `metric-snapshot-round1022-baseline`; связи `FOLLOWS` → `Epic round1021`.

> **✅ ЗАВЕРШЁННЫЙ ЭПИК (Step 10 @Memory, 18.09.2026): `Epic round1021 (System 2 Reasoning & Memory Rebuild)` — COMPLETED + DEPLOYED + ARCHIVED.** Архитектура — `plans/ARCHITECTURE.md` **§47** (итог/ADR-карта/SUPERSEDE-AMEND-карта). **Деплой:** commit **`29fc638`** (feat: System 2 Reasoning) + **`a923310`** (docs/plans: архивация + Merge §47 + отчёты); push **`21cd54c..a923310`** в origin/master; сервер `/var/www/admin_bot` fast-forward **`ec93c3d..a923310`**; `systemctl` **active** (PID **3023258**); бэкап `.env.bak.round1021…`; включены `DREAM_ENABLED=true` / `DEEP_SLEEP_ENABLED=true` / `BELIEF_DECAY_ENABLED=true`; `/api/health` + `/healthz` = **200**; SQLite **`user_version=12`**; канон-миграция промптов применилась идемпотентно (8 ключей). **Финальные числа:** pytest **6779 passed / 0 failed** (baseline 6574 → **+205**); каталог **439/409/414/92/90/20** (**Δ=0**); **SQLite v12 (Δ DDL=0)**; APP_VERSION **2.57.0** (без бампа). **76 задач T-1943…T-2018 / ADR-1021-1…-6 (Accepted/реализованы).**
>
> **6 фич (canonical):** **F1** `multilayer-memory-extraction-round1021` (T-1943…1952 + T-2001…2005/2012/2013) — двухслойный пайплайн `LoreWorker._classify_dossier` (Слой А Thinker → Слой Б Synthesizer), производный `graph_facts.status='dossier_portrait'`, env-only `MULTILAYER_EXTRACTION_ENABLED` (**ON**); **F2** `factchecker-grounding-cove-round1021` (T-1953…1961 + T-2014/2015/2016) — `services/grounding_validator.py` + CoVe; **F3** `de-robotization-negative-constraints-round1021` (T-1962…1970) — `services/prompt_style_blocks.py` + атомарная канон-миграция ADR-1013-3; **F4** `paradigm-thresholds-consolidation-round1021` (T-1971…1979 + T-2009/2010/2011/2017) — READ-ONLY аудит + `memory_maintenance.consolidate` CLI-only, env-only `DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED` (**OFF**); **F5** `memory-rebuild-sanitation-round1021` (T-1980…1989 + T-2006/2007/2008/2018) — `manage.py memory`; **F6** `ui-audit-puppeteer-round1021` (T-1990…2000) — реальный браузерный UI-аудит (Playwright fallback) + фиксы.
>
> **Инварианты:** `imported-history-immutable`, `manual-overrides-immutable`, env-only рубильники, **Δ каталога=0**, `user_version=12`, канон-миграция ADR-1013-3 с обратным `rollback_prompt_canons`. **`memory consolidate --all`** — no-op (`candidates=0`; все 52 confirmed-belief принадлежат целевому чату `-1002661910336`, исключённому из `--all`); таргет и сырая история (`smart_messages` +4 = живой трафик) не тронуты.
>
> **Процесс:** @Reviewer — **2 итерации `Needs fixes` → Approved (3-я)**; @Scanner первично **0 Critical/High** (2 Medium + 7 Low + 4 Info) → re-audit **0 Critical / 0 High / 0 Medium**; @Builder — **2 фикс-раунда (по @Reviewer) + 1 пост-скан фикс-раунд**. Отчёты: `plans/reports/round1021_scanner_audit.md`, `plans/reports/round1021_paradigm_audit.md`, `UI_AUDIT_REPORT.md`, `plans/reports/global_map.md`. **Human Gate** пройден владельцем (UPD).
>
> **Архив:** `plans/archive/<feature>-round1021/` — **6 папок** (`spec.md` + `tasks.md` + `ADR-1021-N`; у F3 — `ROLLBACK.md`, у F4 — `audit.md`); `plans/features/` — 6 backlog-папок (round1021 отсутствует). **Техдолг:** Low `S10.21-8` (vec-эмбеддинги парадигм CLI), `N10.21-1` (тест-покрытие), `N10.21-2` (бинарный `roster_incomplete`) + Info `S10.21-10…-13`; ⏸ Telegram **WebView не воспроизводился** (headless ≠ WebView); **Puppeteer MCP недоступен** → честный fallback Playwright; **R17/R18** — SSH-пароль в истории git (**Risk Accepted**, ротация не делалась).
>
> **📦 ИСТОРИЧЕСКИЙ СНИМОК ПЛАНИРОВАНИЯ (Step 0/Step 3 @Memory, 18.09.2026) — УСТАРЕЛ, сохранён для истории (финал — в блоке «✅ ЗАВЕРШЁННЫЙ ЭПИК» выше):** эпик был SPEC_READY / PLANNED (Step 2 @Architect + UPD владельца, Human Gate пройден; код и tasks НЕ начаты). ТЗ — `plans/current_task.md` (untracked, `.gitignore:70`; **содержит plaintext SSH-креды — в git НЕ коммитить, значение не цитировать**, R17/R18). **Baseline:** HEAD **`21cd54c`**; pytest **6574 passed / 0 failed**; каталог **439/409/414/92/90/20**; SQLite **`user_version=12`**; APP_VERSION **2.57.0**; прод — **`ec93c3d`** (`racknerd-f4e3456`, systemctl active, MainPID 2738993). **6 фич / 58 задач T-1943…T-2000 / ADR-1021-1…-6 (Accepted) / Δ каталога = 0 / схема БД не меняется (v12).** Порядок: **F6 (параллельно) ∥ [F1 → {F2→F3} → {F4→F5}]**.
>
> **Канонические фичи (папки `plans/features/*-round1021/` при планировании; после Step 8 архивированы в `plans/archive/*-round1021/`):** **F1** `multilayer-memory-extraction-round1021` (P0) — Слой А Thinker + Слой Б Synthesizer внутри `LoreWorker._classify_dossier`; **F2** `factchecker-grounding-cove-round1021` (P0) — строгий grounding-валидатор + CoVe; **F3** `de-robotization-negative-constraints-round1021` (P0) — Negative Constraints/асимметрия + канон-миграция; **F4** `paradigm-thresholds-consolidation-round1021` (P1) — READ-ONLY аудит Deep Sleep + консолидация (CLI-only); **F5** `memory-rebuild-sanitation-round1021` (P0) — `manage.py memory` rebuild-dossiers/sanitize-beliefs; **F6** `ui-audit-puppeteer-round1021` (P0) — реальный браузерный UI-аудит + `UI_AUDIT_REPORT.md`. **(KG Step 0-имена F5/F6 `memory-data-migration-rebuild-dossiers-round1021`/`puppeteer-ui-audit-round1021` переименованы/удалены.)**
>
> **⚠️ HISTORICAL CONFLICT CHECK (факты по коду):** (1) класс **`PersonalityExtractor` НЕ существует** — досье строит `LoreWorker._classify_dossier` (`lore_worker.py:526`) single-pass + 1 retry; DreamWorker — single-pass (`dream_worker.py:948-970`); (2) таблицы **`user_dossier` нет** — досье = `graph_facts` (`get_persona_card`) + `persona_dossier_overrides`; (3) **`manage.py memory` отсутствует** (есть `import_history`/`apply-chat-overrides`/`retention`); (4) **валидатора убеждений нет**; (5) шаг 2 частично закрыт 10.20 — Full Tool Access фактчекера (ADR-1020-5, `factcheck_tools()`); CoVe/grounding — новое; (6) шаг 4 пересекается с 10.18 (ADR-1018-2 пороги Сна + manual-каскад, verify-only) — Deep Sleep имеет свои пороги `_DEEP_SLEEP_*`; (7) **negative constraints конфликтуют** с действующим каноном «ты уже проверял эту инфу ранее» (16 совпадений в 5 файлах) — нужна канон-миграция; (8) шаг 1 опирается на 10.20 БЛОК 7 (`LLMChatResult.reasoning` + `strip_reasoning_tags`, 4 пути).
>
> **✅ БЛОКЕР СНЯТ (UPD владельца):** Puppeteer MCP пофиксирован владельцем → порядок **Puppeteer MCP (первым) → Playwright ≥1.40 + Chromium → честный отказ**; выдумывать результаты аудита запрещено (ADR-1021-6, Д17). **KG синхронизирован (Step 3):** Epic + **6 Feature** + **6 ADR-1021-1…-6 (Accepted, GOVERNED_BY/DECIDES)** + **6 ArchitecturalConstraint** (`imported-history-immutable`, `manual-overrides-immutable`, `kill-switch-env-only`, `no-staged-rollout-round1021`, `ui-audit-honest-tools`, `phantom-citations-hard-cut`) + **4 SpecDecision** (activation-default-on, no-mandatory-dry-run, forbidden-phrases-final, tool-order) + **8+1 Risk** (F1-cost ×2, F5-деструктив, F2/F3-канон-асинхрон, F6-галлюцинация отчёта — все **MITIGATED**, блокер Puppeteer снят) + `tech-debt-round10.21` + `metric-snapshot-round1021-spec-ready`. Отчётов о готовности нет. **(УСТАРЕЛО: раунд COMPLETED + DEPLOYED + ARCHIVED — см. блок «✅ ЗАВЕРШЁННЫЙ ЭПИК» в начале файла; KG-узлы понижены/дополнены Step 10.)**

> **✅ ЗАВЕРШЁННЫЙ ЭПИК (16.09.2026; Merge Step 7 @Architect → Step 10 @Memory): `Epic round1020 (Lore Compiler & RAG Refactor)` — COMPLETED + DEPLOYED + ARCHIVED (фазы A–H) + @Reviewer **Approved** + @Scanner **0 Critical/High/Medium/Low** (re-audit §10, `plans/reports/round1020_scanner_audit.md`; 5 Info).** Статус: **COMPLETED + DEPLOYED + ARCHIVED** — деплой commit **`995cf83`** (фича) + **`741b77c`** (R18-вычистка кредов из архива 10.16), запушено в origin/master; сервер **`racknerd-f4e3456`** — `systemctl` **active**, MainPID **2668878**, **NRestarts=0**, SQLite **`user_version=12`**. Живая приёмка владельцем остаётся ⏸ **T-1904** (UI/мини-апп) и ⏸ **T-1931** (Справка). Спека/ADR — **`plans/archive/round1020-lore-compiler-rag-refactor/`** (перенесена `git mv` из `plans/features/`; 11 файлов) (`spec.md` FINAL + `tasks.md` T-1866…T-1931 + **8 ADR ADR-1020-1…-8**, все приняты). **9 фич-блоков 0–8.** **Финальные числа:** pytest **6546 passed / 0 failed** (baseline 6326 → +220; фикс-проход S10.20-*), каталог **439/409/414/92/90/20** (REGISTRY/Settings-fields/categorized/GROUPS/mapped/TAB_RULES; Δ+2 — `flags.lore_compiler_enabled` default **ON**, `limits.chat_timezone`), **SQLite v11 → v12** (`graph_facts.tg_message_id`/`forward_from`; `lore_stories`/`persona_dossier_overrides` — без бампа `user_version`), 8-й инструмент `compile_lore_story`, `INFO_CANON_VERSION` **2 → 3**, APP_VERSION 2.57.0 (без бампа). Ключевое: канонические метаданные (`services/canonical_context.py` + `context_middleware.truncate_keep_header`), «Летописец» (граф+хронология+UPD), RAG ASC у всех потребителей + Time Injection первым user-блоком, Agentic AI (fail-safe `ToolLoopResult`/reasoning/EN-схемы), Full Tool Access фактчекера, мини-апп UX + досье. Merge @Architect: `plans/ARCHITECTURE.md` — **§45** (итог/ADR-карта/инварианты) + точечные синки §1/§3/§4/§5/§6/§9/§11/§25; `plans/reports/global_map.md` — Round 10.20. Открыто: **T-1932** (follow-up — fallback точки 7 реестра `CONTEXT_POINTS`); **S10.20-12** (Time Injection/prompt-cache — принятый трейд-офф ADR-1020-3) и **S10.20-17** (RBAC `persona_dossier_overrides` — вне скоупа) приняты обоснованно; ⚠️ **открытый R18-риск** — исходное значение пароля осталось в истории git (коммиты `eb3fd4a…995cf83`), рабочее дерево и HEAD чисты; требуется решение владельца (rotation и/или rewrite history) — KG `risk-secret-in-git-history`; каноны промптов синхронны (`docs/canon/architecture.md` + `backlog.md`).
>
> **⚠️ ВОЗВРАТ НА ДОРАБОТКУ / REOPENED (UI rework) — Шаг 0 @Memory, 17.09.2026 (по UPD3 владельца, 16.09.2026): `Epic round1020 (Lore Compiler & RAG Refactor)`.** Фронтенд-блок **БЛОК 3** (`miniapp-ux-refactor-round1020`) **провален**: отчёт Оркестратора о готовности — галлюцинация; бэкенд работает, но UI по визуальной инспекции (снимки экранов) не соответствует ТЗ. Владелец вернул эпик на доработку; **@Reviewer — выговор** за пропуск неработающего UI (ревью фазы D было ошибочно code-passed; @Scanner позже нашёл **High `S10.20-1`** — конфиг-вкладки мини-аппа потеряли сохранение). **Обновлённый статус:** бэкенд — фактически COMPLETED+DEPLOYED (`995cf83` + `741b77c`; прод `racknerd-f4e3456`, SQLite v12), **UI-часть — REOPENED** до устранения 5 дефектов. KG: Feature **`round1020-ui-rework`** (AMENDS `miniapp-ux-refactor-round1020`).
>
> **✅ UI-REWORK ИСПРАВЛЕН + ЗАДЕПЛОЕН + ЗААРХИВИРОВАН (Merge Step 7 @Architect + Step 9 @DevOps + Step 10 @Memory, 17.09.2026) — REOPENED → COMPLETED + DEPLOYED + ARCHIVED:** все **5 дефектов закрыты** — (1) **Liquid Glass** (`--glass-bg rgba(20,25,30,.5)` + `blur(16px)`, стекло на `.card`/`.modal-card`, снят `card-solid` с 5 модалок, `@supports`-фолбэк); (2) **CSS Grid** (`minmax(320px,1fr)` у `.prov-grid`/`.module-list`/`.hub-grid`; 4/3/3 трека @1440px, 1 трек @400px); (3) **маска секретов** (`SECRET_MASK`+`isSecretMask`+**`hasSecretMask`**, no-op guard → **0 POST** при чистой маске и композите `маска+ввод`; `_seedSecretMasks`); (4) **градиент** (`--grad-d #FF8A3D` + `--grad-speed:6s`, conic-wash, reduced-motion/contrast); (5) **sticky** внутрь скроллера + **`.sticky-spacer`** (зазор 0). **Процесс:** итерация 1 — Critical (композит маски уходил в `POST /api/config` + отсутствие `@focus select()` на provider-инпутах) → фиксы **T-1936-fix**; **@Reviewer — APPROVED** (Re-review итерация 2, `round1020_ui_rework_reviewer.md`); **@Scanner — 0 Critical / 0 High** (`round1020_ui_rework_scanner_audit.md`; 1 Medium `M-1` + 3 Low), закрыты финальным фиксом **T-1936-fix2** (M-1 `.sticky-spacer`, L-1 условный `@focus f.secret`, L-2 `SECRET_MASK_HINT`). pytest **6574 passed / 0 failed**; JS-гейты (`node --check`/`JS-UNIT-OK`×2/`VUE-MOUNT-OK`/routing) чистые; **red→green** подтверждён (19 failed/7 passed → 26 passed). **Инварианты:** меню-freeze (25 вкладок + 6 nav + 12 модулей), **каталог-Δ=0**, `services/**`/`web/api/**`/`web/app.py`/`bot.py` не тронуты, `APP_VERSION` без бампа. Архитектура — `plans/ARCHITECTURE.md` **§46** + шапка §1; спека/`ui-contract`/**ADR-1020-9** — `plans/archive/round1020-ui-rework/` (перенесена `git mv` из `plans/features/`; 4 файла: `spec.md`/`ui-contract.md`/`tasks.md`/`adr/ui-rework-1020.md`). **✅ ДЕПЛОЙ ВЫПОЛНЕН — `ec93c3d` (@DevOps, T-1942):** прод-`/web/static/app.css` подтверждён (`blur(16px)`, `rgba(20, 25, 30, 0.5)`, `#FF8A3D`, `6s`, `sticky-spacer`, `Cache-Control: no-store`); сервер **`racknerd-f4e3456`** — `systemctl` **active**, MainPID **2738993**, **NRestarts=0**; SQLite `user_version=12`; каталог/меню-инварианты не тронуты. **⏸ Остаточная живая приёмка (не блокер):** живые WebView (Telegram Android, Nekogram) и **скриншот-приёмка §7.5**. Деплой/скедаун 10.20 (`995cf83`+`741b77c`) не затронуты.
>
> **✅ 5 обязательных дефектов UI — ВСЕ ЗАКРЫТЫ (17.09.2026; история для контекста, @PM/@Builder):**
> 1. **Нет Liquid Glass** — сплошные тёмные фоны модалок/карточек, сломанная верстка → `.modal/.card`/панели: `background-color: rgba(20,25,30,0.5)` + `backdrop-filter: blur(16px)` (+`-webkit-`) + светлая граница. Constraint **`glassmorphism-contract`** (Risk `risk-ui-liquid-glass-missing-round1020`).
> 2. **CSS Grid проигнорирован** — «Модули»/«ИИ» в одну колонку на десктопе → `display:grid; grid-template-columns: repeat(auto-fit, minmax(320px,1fr)); gap:1rem;`. Constraint **`css-grid-320`** (Risk `risk-ui-grid-single-column-round1020`).
> 3. **КРИТИЧНО: пустые поля ввода** — в «Диагностике» `Пароль Betterstack SQL` и `Пользователь Betterstack SQL` пусты, two-way binding не прокидывает данные из БД в state. Секреты при наличии значения показывать как `••••••••••••`; пусто — только при реальном `null`; **проверить ВО ВСЕХ модулях**. Constraint **`secret-field-mask`** (Risk `risk-ui-empty-secret-fields-round1020`; R18 — значения не цитировать).
> 4. **НОВОЕ требование: фоновый градиент** — ускорить CSS-анимацию до **5–8s** и добавить **оранжевый** цвет в палитру (к сиреневому и циан/бирюзовому), отрегулировать углы. Constraint **`gradient-motion-orange`** (Risk `risk-ui-gradient-slow-no-orange-round1020`).
> 5. **Кривая sticky-панель `Отмена/Сохранить`** — сломала отступы (padding/margin), перекрывает контент → переверстать, гармонично прилипает к низу без перекрытия. (Risk `risk-ui-sticky-panel-layout-round1020`).
>
> **✅ Закрытие доработки (17.09.2026):** все 5 дефектов исправлены и задеплоены (`ec93c3d`); @Reviewer Approved (итерация 2, реальный Chromium), @Scanner 0 Critical/0 High (M-1/L-1/L-2 закрыты T-1936-fix2); pytest **6574 passed / 0 failed**; прод-CSS подтверждён; меню-freeze и каталог-Δ=0 сохранены. Детали — `plans/metrics.md` (раздел «Детали раунда 10.20-UPD3»), `plans/ARCHITECTURE.md` §46, `plans/reports/global_map.md` (Round 10.20 UPD3), KG `round1020-ui-rework`.
>
> **Указание владельца:** до отчётов о готовности — **только реальный фикс** (CSS + стейт-менеджмент фронтенда). Область: `web/index.html`, `web/app.js`, `web/static/app.css`; меню/навигацию **НЕ менять** (`tma-menu-freeze`). SpecDecision — KG `owner-ui-rework-directive-round1020`.
>
> **✅ R17-ИНЦИДЕНТ ЗАКРЫТ — Risk Accepted (владелец, 16.09.2026, UPD3 п.2):** старая частичная утечка в `plans/archive/security-rotation-finalize-round1016/spec.md`; **ротация НЕ делается** (отказ от варианта А), **история git НЕ переписывается** (отказ от варианта B). **R18 (Secret Scrubbing) остаётся глобальным правилом** для всех текущих и будущих эпиков — достаточно. Секреты из текста удалены (коммит `741b77c` → `[REDACTED]`); **старый файл добавлен в ignore-лист сканера R18** — **`plans/docs/r18_scanner_ignore.md`** (правило «risk-accepted»: реальные секреты всё равно вычищаются, игнор — только для исторических неподтверждённых упоминаний). KG: `risk-secret-in-git-history` → **ACCEPTED**; SpecDecision `r17-risk-accepted-no-rotation`. Значение секрета нигде не цитируется (R18).
>
> **🗂 ИСТОРИЧЕСКИЙ СНИМОК ПЛАНИРОВАНИЯ (Step 3 @Memory, 16.09.2026): `Epic round1020 (Lore Compiler & RAG Refactor)` — был APPROVED (Human Gate пройден, решения О1–О7; скоуп расширен блоками 7–8; на момент снимка код не был тронут, впереди был Step 4 @Builder).** Аудит Фазы A + `spec.md` + ADR-1020-1…6 закрыты @Architect (spec — PROVISIONAL). ТЗ — `plans/current_task.md` (untracked, `.gitignore:70`; содержит plaintext SSH-пароль — в git/KG/MEMORY.md **НЕ вносить**, R17; О6 подтверждён). Baseline: pytest **6326 passed**; каталог **437/407/412/92/90/20** (REGISTRY/Settings/categorized/GROUPS/mapped/TAB_RULES); SQLite **v11**; APP_VERSION **2.57.0**; прод `release-round1019` (`2416d3e`, MainPID 2476027).
>
> **9 фич-блоков 0–8 (граф):** `metadata-injection-round1020` (BLOCK 0 — метаданные `[Дата Время | Автор | ID | Переслано: откуда]`), `lore-compiler-round1020` (BLOCK 1 — Летописец `compile_lore_story(topic)` + storytelling + UPD-диффы), `rag-chronology-tool-routing-round1020` (BLOCK 2 — роутинг/хронология ASC/`/summary`/`dig_into_lore`), `miniapp-ux-refactor-round1020` (BLOCK 3 — UX/UI TMA), `llm-engine-audit-round1020` (BLOCK 4 — READ-ONLY аудит), `time-awareness-hallucination-fixes-round1020` (BLOCK 5 — Time Injection/анти-галлюцинации/безлимит), `persona-worker-ui-factcheck-round1020` (BLOCK 6 — manual DeepDream/Full Tool Access фактчекера/техдолг), **`agentic-ai-refactor-round1020`** (BLOCK 7 — Tool Recursion Fail-Safe / Reasoning / Context Middleware / EN-schemas), **`help-ui-update-round1020`** (BLOCK 8 — актуализация «Справки»). Плюс **12 SpecDecision** (в т.ч. **О1–О7**), **8 ArchitecturalConstraint** (`prompt-cache-immutable`, `tma-menu-freeze`, `metadata-update-priority-over-budget`, `graph-facts-schema-extension`, `english-tool-schemas` + 3 исходных), **12 Risk** (в т.ч. `reasoning-parsing-compat`, `budget-cap-metadata-regression`, `graph-facts-migration`, `english-schema-regression`, `help-text-tone-drift`), `tech-debt-round1020`, `metric-snapshot-round1020-baseline`; эпик `FOLLOWS` `Epic round1019`.
>
> **⚠️ HISTORICAL CONFLICT CHECK (пересечения с прошлым):** (1) **BLOCK 6.1 «ручной DeepDream» и BLOCK 5.5 (пустые «Парадигмы»/«Эволюция характера») уже закрыты раундом 10.18 F2/F5** (`sleep-manual-cascade-badges`, ADR-1018-2, коммит `16a8c0b`, `tests/test_sleep_manual_cascade_round1018.py`) — риск дублирования, нужен дельта-объём; (2) имя тула в ТЗ `dig_into_lor` неверно → в коде **`dig_into_lore`**; (3) хроно-сортировка ASC (`sort_by_timestamp=True`, канон D206) **уже есть, но только DirectChat** — BLOCK 2.6 расширяет скоуп аддитивно; (4) **аккордеон Advanced уже существует** (`progressive_level` + `<details class="advanced">`, свёрнут+персист) — BLOCK 3.8 = рестайлинг Glassmorphism; (5) **tool recursion уже реализована** (`services/tool_loop.py`, `TOOL_MAX_ROUNDS=4`); (6) `compile_lore_story` **не существует** (новый, 8-й к канону 7 инструментов R9); (7) `factcheck_service.py` тулов не имеет (посылка ТЗ верна); (8) **техдолг БЛОКА 6 подтверждён:** `S10.19-15` (двойной `chat_usage.key_status` в «Сводке»), `S10.19-23` (fsync **каталога** архива; файл уже fsync'ится), CLI `python manage.py retention` при живом боте (dry-run по умолчанию).
>
> **✅ РЕШЕНИЯ Human Gate (О1–О7, 16.09.2026):** О1 — BLOCK 5.5/6.1 **verify-only** (ADR-1018-2 не переоткрывать, привязать к кнопке нового UI); О2 — Time Injection **первым USER-блоком**, system-промпт статичен (Prompt Caching не ломать); О3 — `compile_lore_story` разрешён, **простой флаг ВКЛ/ВЫКЛ, дефолт ON** глобально (без поэтапности); О4 — **новый ключ `limits.chat_timezone`** (не смешивать с `limits.summary_timezone`); О5 — UI-объём полный, **меню не менять**, глобальный `parse_mode=None`, для историй Летописца локально **HTML**; О6 — `current_task.md` **untracked**, пароль не коммитить (R17); О7 — таблица `lore_stories` **аддитивно, без бампа `user_version`**.
>
> **АКТУАЛЬНЫЙ СТАТУС (16.09.2026):** раунд **10.19 «UPD2+UPD3+UPD4 bugfixes»**
> — **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН**: **8 фич F1–F8**, **8 ADR (ADR-1019-1…-8)**,
> **задачи T-1778…T-1865** (88). Спеки + ADR — **`plans/archive/<feature>/`** (8 папок):
> `betterstack-ingest-bearer-contract`, `direct-chat-budget-unlimited`, `budget-settings-section`
> (ADR-1019-3 + **ADR-1019-8** `per-chat-limits-and-seed` → **Accepted/Implemented**),
> `direct-context-limit-expansion`, `status-section-ui-merge`, `media-files-avatars-sync`,
> `memory-retention-health`, `graphrag-memorize-robustness`. `plans/archive/` — **84 папки**;
> `plans/features/` — 6 backlog-папок.
>
> **Финальные числа:** pytest **6326 passed / 0 failed** (база 6139 → **+187**; траектория
> 6164(A) → 6195(B) → 6232(C) → 6262(D) → 6323(E) → 6326 hotfix); каталог
> **437/407/412/92/90/20** (REGISTRY/Settings/categorized/GROUPS/mapped/TAB_RULES; было
> 436/406/411/90/88/19); **SQLite v10 → v11** (`UNIQUE(chat_id, import_key)` + `import_checkpoints`
> PK `(path, chat_id)`), на проде `user_version=11`; **новых каталоговых флагов НЕТ**; env-only
> `IMPORT_RETENTION_ENABLED`/`_DRY_RUN`/`_BACKUP_CONFIRMED` (**авто-purge OFF**) и
> `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000`. Деплой: **`c1502b6`** + **`2416d3e`** (hotfix сида),
> push `fd6acc7..2416d3e`, прод **active (MainPID 2476027)**, `/api/health` **200**; релиз-узел
> **`release-round1019`** (alias `release-2416d3e`).
>
> **✅ BetterStack 401 ПОБЕЖДЁН:** ingest-контракт `POST https://{host}` + `Authorization: Bearer`
> — probe **US × Bearer = 202** (path-token/EU = 401); после деплоя `status=401` = **0**;
> `[betterstack] attached | host=…us-west-2a…`. WARNING `token == SENTRY_DSN pubkey` снят → `debug`
> (норма unified US). **`_STATUS_HINTS = {401, 402, 403, 406}`** — **202 = успех**, в подсказках его
> нет (в ТЗ-брифе UPD2 значился 202 — неверно; **код — источник истины**).
>
> **🔴→✅ Post-Deploy Gate (UPD4 п.4):** первый деплой **`c1502b6`** → **ABORT** — сид не применялся
> (`changed_by='chat_settings_seed'` (str) → `chat_lore_history.changed_by BIGINT` → `asyncpg.DataError`,
> глотался fail-open; тесты не поймали — мок `set_chat_params`). **Hotfix `2416d3e`**: `changed_by=None`
> + интеграционный тест **без мока** (`_StrictPgConn` валидирует BIGINT) → повторный гейт **PASS**:
> 8 ключей целевого чата `-1002661910336` = `[0, -1, -1, -1, -1, -1, -1, -1]` (retention 0 = вечно;
> бюджеты/фон/контекст −1 = безлимит); идемпотентность 2-го рестарта (chat_lore_history 39→39),
> чужие overrides (`limits.chat_burst_limit=10`) и `meta` сохранены. **UPD4:** концепция «VIP» удалена
> из КОДА → универсальный сид `services/chat_settings_seed.py` + `config/chat_settings_seed.json`
> (id чата — только данные + тесты). retention dry-run (снапшот БД): целевой чат НЕ кандидат.
>
> **Процесс:** @Reviewer **Approved** по батчам A(F1+F8)/B(F2)/C(F3)/D(F4+F5)/E(F6+F7, после UPD4);
> **отклонений 6** (A-1, B-1, C-1, D-1, E-2); @Scanner **0 Critical / 0 High / 0 Medium** по всему эпику;
> открыто **2 Low** (`S10.19-15` двойной `key_status`; `S10.19-23` fsync каталога архива) + Low
> `S10.18-29` + **16 Info**; @Builder **~6 rework**. Merge @Architect: `plans/ARCHITECTURE.md`
> **818 строк** — **§40** (F2), **§41** (F3/F6/F7), **§42** (F1/F8), **§43** (F4/F5),
> **§44** (итог/SUPERSEDE-карта + Feature Flags/Progressive Delivery). Archive @PM: `plans/backlog.md` —
> 10.19 COMPLETED + ИТОГ + техдолг + таблица @DevOps-гейтов; **UPD2-3 (SSH-фрагмент) закрыт/отменён**
> (историю git не трогаем). Граф: **`Epic round1019`** COMPLETED + `release-round1019` + F1–F8
> (DEPLOYED_IN) + ADR-1019-1…-8 (Accepted) + risks **RESOLVED** + новый
> `risk-seed-changed-by-type-round1019` (ABORT → hotfix → PASS) + `metric-snapshot-round1019-final`.
> Предыдущий раунд — **10.18** (COMPLETED + DEPLOYED + ARCHIVED, `16a8c0b`).
>
> ⤵️ **Ниже — исторический снимок планирования (Step 2/3, 15.09.2026) раунда 10.19.**
>
> ---
>
> **ИСТОРИЧЕСКИЙ СНИМОК (Step 2/3, 15.09.2026):** раунд **10.19 «UPD2 bugfixes»** (UPD2 + итерация 2 **UPD3**)
> — **PLANNED / SPEC_READY, Builder не начат**: **8 фич F1–F8**, **8 ADR (ADR-1019-1…-8)**,
> **88 задач T-1778…T-1865** (исходно T-1778…T-1852 + итерация 2 UPD3 T-1853…T-1865).
> Спеки/ADR — `plans/features/` (**8 папок**). ТЗ — `plans/current_task.md` §UPD2 (стр.130-175)
> + **§UPD3 (стр.178-216)**; ответ владельца — «Принято, реализуем per-chat архитектуру».
> **Каталог-Δ (санкц. UPD3 п.5):** **437/407/412/92/90/20** (REGISTRY/Settings/categorized/
> GROUPS/mapped/TAB_RULES); было 436/406/411/90/88/19. **DDL:** SQLite v10 → **v11 (в планах)** —
> `idx_smart_messages_chat_import_key UNIQUE(chat_id, import_key)` + `import_checkpoints.chat_id`.
> **Дефолты (UPD3):** direct **100** вызовов / **500 000** токенов; фон per-chat **60** / **300 000**;
> контекст **5000/3000/16000** (+ потолок `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000`, env-only);
> retention импорта **180**. Baseline: HEAD **`fd6acc7`**, прод **`16a8c0b`** (`release-round1018`,
> PID 2319614), pytest **6139**, SQLite **v10**, APP_VERSION **2.57.0**. Детали — KG-узлы
> `Epic round1019 (UPD2 bugfixes)` / `round10.19-epic` + блок **«Step 2/3»** ниже; метрики —
> `plans/metrics.md`. Предыдущий раунд — **10.18** (COMPLETED + DEPLOYED + ARCHIVED, `16a8c0b`).
>
> **Step 2/3 (Step 2 @Architect + итерация 2 после UPD3 — синк Step 3 @Memory)
> 15.09.2026 (раунд 10.19 «UPD2 bugfixes»):** эпик `Epic round1019 (UPD2 bugfixes)` —
> **PLANNED / SPEC_READY**. **8 фич / 8 ADR / 88 задач T-1778…T-1865** (итерация 2:
> ADR-1019-8 + T-1853…T-1865).
> **F1** `betterstack-ingest-bearer-contract round1019` (T-1778…T-1788, **P0**, **ADR-1019-1**):
> ingest — `POST https://{host}` **без токена в пути** + `Authorization: Bearer {SOURCE_TOKEN}`
> (202/402/403/406; 4xx не ретраить); `_HINT_401` → `_STATUS_HINTS`; **снят ложный WARNING**
> `token == SENTRY_DSN pubkey` (на unified US — **норма**, → `debug`); **`logtail-python` в проекте
> НЕТ** (посылка ТЗ ложна) — прод-точка `services/betterstack_handler.py`; curl-матрикс **{path-token,
> Bearer}×{US,EU}** до правки (**T-1779**, @DevOps, только HTTP-коды); `.env` + рестарт — вне репо; Δ=+1
> (`BETTERSTACK_HOST`, сохранён из 10.18).
> **F2** `direct-chat-budget-unlimited round1019` (T-1789…T-1798 + T-1854/T-1855, **P0**, **ADR-1019-2**):
> sentinel **`0 = запрет`, `−1 = безлимит`**; причина «рассинхрона» — `chat_usage` читал лимиты
> **только** `hot.get` → per-chat override не работал; фикс — per-chat резолв
> (`chat_params.overrides → hot.get → env`, ADR-1018-7 `resolve_setting_cached`);
> `budget_snapshot`/`exceeded_metric`; `exceeded` без метрики → ERROR + **fail-open** (ложный sandbox
> невозможен); дефолты **100/500 000**; **ревью-фиксы Батча B (D-1…D-5):** `worker_budget` (фон) —
> тот же sentinel (`-1`=безлимит, `0`=запрет) + per-chat резолв (дефолты **60/300 000**, `_metric_limit`
> async); `llm_client` — единый снимок (без двойного PG-раундтрипа); fail-open `budget_snapshot`
> пробрасывает `forbidden`/`source` (не хардкод); **SUPERSEDE F-15** (10.3); см. ARCHITECTURE §40.
> **F3** `budget-settings-section round1019` (T-1799…T-1808 + T-1856…T-1860, **P0/P1**,
> **ADR-1019-3** + **ADR-1019-8**): вкладка **`mod_budgets` «Бюджеты»** в nav «Модули»; группы
> **`limits_chat_key`**/**`limits_chat_context`**; 3 per-chat поля («Хранение импорта (дней)» 0=вечно,
> «Лимит токенов/вызовов» −1=безлимит, «Лимит контекста»); тумблер безлимита пишет **существующие**
> per-chat ключи (новых REGISTRY-записей нет); **сид настроек чатов** `services/chat_settings_seed.py` +
> `config/chat_settings_seed.json` (chat_id **−1002661910336**: retention 0, бюджеты −1, контекст max) + guard
> `retention==0 → purge запрещён`; «Сводка» — аддитивный `limits {key_budget, worker_budget, context,
> storage}` (R16) с бейджем «Безлимит (∞)» / «Импорт: Вечно».
> **F4** `direct-context-limit-expansion round1019` (T-1809…T-1817 + T-1861/T-1862, **P1**,
> **ADR-1019-4**): развязка `_build_global_context` (per-block caps) ↔ `_apply_context_budget` (общий
> бюджет); root cause 869 = `resolve_chat_limit(token_default=1000)` → `safe_budget(1000)=1000/1.15`;
> дефолты **5000/3000/16000**; per-chat `−1` → ceiling **`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000`**
> (**env-only**, Δ каталога=0); chars-fallback — только аварийный.
> **F5** `status-section-ui-merge round1019` (T-1818…T-1825, **P2**, **без ADR** — UI-вёрстка):
> «Сердцебиение»+«Бот»+«Сервер» → один визуальный блок; удалить строку «Режим … · версия …»
> (`index.html:2141`; API-поля `bot.mode`/`bot.version` остаются, R16); компактное поле поиска по графу
> (мобила/десктоп); конфликт файлов с F3 → вливать ступенями **F3 → F5**.
> **F6** `media-files-avatars-sync round1019` (T-1826…T-1834, **P1**, **ADR-1019-5**): локальный
> fallback аватаров/медиа — общий хелпер `read_local_file_bytes`/`local_file_path` в
> `services/media_download.py`; новый `services/media_integrity.py` (audit/restore ФС↔БД); аддитивный
> `GET /api/status/media-health` (R16, только числа/хвосты `photos/file_*.jpg`); R17 (без `<bot_id>:<token>`
> и абсолютных путей).
> **F7** `memory-retention-health round1019` (T-1835…T-1844 + T-1863/T-1864, **P1**, **ADR-1019-6**):
> retention per-chat `limits.import_history_retention_days=180` (**0=вечно**, иной sentinel, чем бюджеты);
> `purge_imported_history(*, chat_cutoffs: dict[int,int])` — keyword-only allow-list; архив перед purge
> (сбой → не удалять); guard целевого чата; **аудит изоляции I-1…I-9**: **I-2** (`import_key` без `chat_id` +
> глобально UNIQUE → кросс-чат подавление) и **I-6** (`import_checkpoints` только `path`) → **SQLite v11**
> (`UNIQUE(chat_id, import_key)`, ключ `(path, chat_id)`); включение Сна/декая **данными** per-chat
> (ADR-1018-7) + честные метрики памяти (overdue/unconfirmed/размеры).
> **F8** `graphrag-memorize-robustness round1019` (T-1845…T-1852, **P1**, **ADR-1019-7**, **AMEND F-15 §4**):
> `parse_fact_list_ex` → `ok/empty_valid/invalid` (валидный `[]` ≠ невалидный); `LLMError` первичной
> экстракции перехватывается внутри `_memorize_facts_inner` → fallback + **1 bounded retry**; единый
> rate-limited WARNING (60с) вместо спама; канон `FACT_EXTRACT_PROMPT` байт-в-байт, Δ=0.
>
> **Порядок:** **{F1 ∥ F2} → F3 → {F4 ∥ F5} → {F6 ∥ F8} → F7**. **Пересечения файлов:** F2/F3/F4/F7 —
> `param_catalog.py`/`settings.py` (сводить Δ); F3/F5 — `web/index.html`/`app.js`/`app.css`; F7/F8 —
> `summary_memory.py`; F2/F3 — `chat_usage.py`.
>
> **Решения владельца (UPD3):** хардкод безлимитов глобально **ЗАПРЕЩЁН** → безлимит только per-chat
> override (данные), глобальные дефолты — предохранитель; целевой чат `−1002661910336` (retention 0, бюджеты −1,
> контекст max) — **сидом**; санкционированы Δ каталога и **DDL SQLite v11**; дефолты умеренные.
> **UPD2-3 (SSH-фрагмент) — ОТМЕНЁН:** вариант (а) — оставить как есть, `filter-repo` **НЕ трогаем**,
> риск принят (публичный репо, неполный обрывок); S10.18-13 закрыт; значение не цитировать.
>
> **Снятие противоречий (KG, явно):** «logtail-python используется» — **ОПРОВЕРГНУТО** (библиотеки
> в прод-пути нет с раундов 4/5); «`token == SENTRY_DSN pubkey` = ошибка» — **ОПРОВЕРГНУТО**
> (на unified US — норма, WARNING снят).
>
> **Остаётся в силе:** R16, R17, порядок роутеров `bot.py`, `media/`/`.env` не трогать, каталог-Δ
> только санкционированно, русские conventional commits; `plans/current_task.md` — untracked
> (`.gitignore:70`), **секреты в KG/MEMORY.md не вносились**.
> **Граф синхронизирован (Step 3):** Epic + **8 Feature** + **8 ADR** (ADR-1019-1…-8) + **7 Risk**
> (`risk-betterstack-bearer-vs-path`, `risk-cross-chat-import-collision`, `risk-catalog-delta`,
> `risk-import-purge-eternal` + `risk-direct-key-budget-ui`, `risk-context-cap-869`,
> `risk-ssh-fragment-tracked`) + **3 ArchitecturalConstraint** (`per-chat-limits-no-global-hardcode`,
> `chat-seed-data-only`, `memory-isolation-by-chat`) + **4 SpecDecision** (owner-UPD3,
> logtail-python-refuted, token==pubkey-normal, ssh-fragment-cancelled) + `tech-debt-round10.19`
> (I-4 vec-KNN global k=3) + `metric-snapshot-round1019-spec-ready`; связи HAS_FEATURE/PART_OF/HAS_ADR/
> DECIDES/GOVERNED_BY/**AMENDS** (ADR-1019-1 → ADR-1018-1; ADR-1019-3/-8 → ADR-1018-6; ADR-1019-8 →
> ADR-1018-7; ADR-1019-8 → ADR-1019-2/-3/-4/-6) / **SUPERSEDES** (ADR-1019-2 → F-15
> `direct-sandbox-budget-investigation`; ADR-1019-7 **AMEND F-15 §4**) / DEPENDS_ON /
> RESOLVED_BY / HAS_TECH_DEBT / HAS_METRIC.
>
> **UPD (Step 10, 16.09.2026): блок «Step 2/3» выше — исторический снимок планирования.**
> Факт финала: раунд **10.19 COMPLETED + DEPLOYED + ARCHIVED**, спеки+ADR в `plans/archive/<feature>/`
> (8), pytest **6326**, каталог **437/407/412/92/90/20**, SQLite **v11** (на проде `user_version=11`),
> коммиты **`c1502b6`** + **`2416d3e`** (hotfix сида после ABORT Post-Deploy Gate), релиз
> **`release-round1019`**; BetterStack 401 снят (US × Bearer = 202); `_STATUS_HINTS={401,402,403,406}`.
> «PLANNED/SPEC_READY, Builder не начат» — устарело. Актуальные числа — в блоке «АКТУАЛЬНЫЙ СТАТУС»
> выше и в `plans/metrics.md`.

> **Архив (раунд 10.18): «Memory-Graph-Sleep-BetterStack bugfixes»**
> — **COMPLETED + DEPLOYED + ЗААРХИВИРОВАН**: **7 фич F1–F7**, **75 задач T-1703…T-1777**,
> **7 ADR (ADR-1018-1…-7)**; спеки+ADR — `plans/archive/<feature>/` (7 папок:
> `betterstack-us-region-401`, `settings-worker-sync`, `sleep-manual-cascade-badges`,
> `graph-density-scoring-stoplist`, `graph-physics-stabilization`,
> `metafact-penalty-extractor-prompt`, `role-matrix-settings-actualization`).
> **Каталог-факт: REGISTRY 435→436 / Settings 406** (Δ=+1 — только F1 `BETTERSTACK_HOST`;
> **новых фича-флагов НЕТ** — плановый 437/407 с F5-флагом **отменён**, флаг
> `flags.metafact_penalty_enabled` не вводился; `categorized 411 / GROUPS 90 / mapped 88 /
> TAB_RULES 19` — без изменений). **DDL SQLite v9→v10** (`edges.fact_id` + индекс, F3;
> применена на проде, `PRAGMA user_version=10`). Прогоны: pytest **6007 → 6139 passed / 0 failed**
> (+132), JS-гейты OK. Деплой: commit **`16a8c0b`**, push `118a03c..16a8c0b`, прод
> fast-forward `b6c153f..16a8c0b`, `admin_bot` active PID **2319614**, `/api/health` **200**
> (+ публичный healthz 200). Baseline HEAD **`118a03c`**, прод release-round1017 (**`b6c153f`**),
> APP_VERSION **2.57.0** (без бампа). Детали — KG-узлы `release-round1018` /
> `Epic round1018 (Memory-Graph-Sleep-BetterStack bugfixes)` + блок **«Step 10 (финал)»** ниже;
> метрики — `plans/metrics.md`. ⚠️ Остаточный блокер: BetterStack 401 — версия 10.18 «неверный токен»
> **опровергнута раундом 10.19: причина — ingest-контракт (path-token → Bearer), токен корректен**
> (см. блок 10.19 выше и KG `SpecDecision token-equals-pubkey-normal round1019`).
> Предыдущий раунд — 10.17 (COMPLETED + DEPLOYED, `b6c153f`).

> **Step 2/3 (Step 2 @Architect + итерация 2 после human-gate — синк Step 3 @Memory)
> 15.09.2026 (раунд 10.18 «Memory-Graph-Sleep-BetterStack bugfixes»):** эпик
> `Epic round1018 (Memory-Graph-Sleep-BetterStack bugfixes)` — **ARCHITECTED / SPEC_READY,
> Builder не начат**. ТЗ — `plans/current_task.md` §1–§5 + **UPD владельца (строки 109-128)**.
> **7 фич F1–F7 / 75 задач T-1703…T-1777** (итерация 2: F2 T-1767…T-1772, F3 T-1773…T-1777,
> F7 T-1758…T-1766) + **7 ADR (ADR-1018-1…-7)**. Каталог-Δ (санкц.): **REGISTRY 437 /
> Settings 407** (F1 +1, F5 +1); **GROUPS 90 / mapped 88 / TAB_RULES 19 — без изменений**;
> F2/F3/F4/F6/F7 Δ=0. **DDL: SQLite v9→v10** — nullable `edges.fact_id` + индекс (F3).
> **Порядок:** **F7 → F2 → F3 → {F4 ∥ F5} → F6** (F1 — параллельная инфра-плоскость
> @DevOps: `.env` + `systemctl restart`). **Рекомендация @PM** была `{F1 ∥ F2} → F3 →
> {F4 ∥ F5} → F6`; ADR-1018-2 D8 / ADR-1018-7 ставят F7 перед F2.
>
> **F1** `betterstack-us-region-401 round1018` (T-1703…T-1711, **P0**, **ADR-1018-1**):
> посылка ТЗ неверна — библиотечный `LogtailHandler` НЕ в прод-пути с раунда 4/5; реальная
> точка `bot.py:141-145` (`BetterStackHandler`), host не передавался → EU-дефолт
> `in.logs.betterstack.com` → 401 на US-токене. Решение: `BETTERSTACK_HOST` обязателен
> (env-only, **REGISTRY 435→436**; пусто → хендлер не создаётся + WARNING fail-safe);
> `token_equals_sentry_public_key()` → WARNING (не блок); Sentry/BetterStack разведены;
> startup-лог (R17); `.env` — только рестарт. **T-1704 — обязательный curl-матрикс
> {US,EU}×{Source Token, public key} ДО правки кода.** Артефакт `test_monitoring_smoke.py`
> (библиотечный `LogtailHandler` без host) — на ревизию. `CHECKUP_BETTERSTACK_SQL_HOST` —
> другой контур, вне скоупа.
> **F2** `sleep-manual-cascade-badges round1018` (T-1712…T-1726 + T-1767…T-1772, **P0**,
> **ADR-1018-2**): `manual=True` — **безусловный приоритет БЕЗ фича-флагов** (UPD п.2);
> обходит window_skip/kill-switch/near-limit/суточные бюджеты/тайминги каскада
> (аудит `gate_override`/`budget_override`; Worker Budget как **учёт** сохраняется);
> **НЕ обходит** локи/`protected_facts`/≥2 `source_ids`/R17/`persona_enabled`/целостность;
> каскад Сон→Глубокий→Личность (+`stats['cascade']`); пороги ослаблены 2/8/2/10/60/300000/10
> + идемпотентная **DML**-миграция PG; реактивные бейджи без WebSocket
> (`active_until=now+900с`, оптимистичный фронт + ретраи); **S10.17-2 закрывается**
> (`cognition==null` → `—`/`badge-muted`, T-1721); диагностика Личности (7 R17-safe исходов).
> **Жёстко зависит от F7** (D8).
> **F3** `graph-density-scoring-stoplist round1018` (T-1727…T-1735 + T-1773…T-1777, **P1**,
> **ADR-1018-3**, **SUPERSEDE ADR-1015-2**): `score = Σ edge_importance` (COALESCE
> `f.importance`/`e.weight`) ×2 за Убеждение/Парадигму; STOP_LIST центров (6 слов) только к
> seed-выборке; **seeds 150 / cap 800-2400** → 500–800 узлов; **DDL v9→v10**: `edges.fact_id`
> nullable + индекс, reorder `insert_graph_fact` ДО `upsert_edge(..., fact_id=…)`,
> legacy NULL (без backfill); единый `services/graph_stoplist.py`; флаг
> `flags.graph_scoring_v2_enabled` OFF (⚠️ см. дрейф Δ).
> **F4** `graph-physics-stabilization round1018` (T-1736…T-1741, **P1**, **ADR-1018-4**,
> **AMEND F2 10.15**): `iterations=150` + `net.once('stabilizationIterationsDone'/'stabilized')`
> → `physics.enabled=false`; `destroy` пересоздаёт с options; `reducedMotion`/поиск/подсветка
> без изменений; Δ=0.
> **F5** `metafact-penalty-extractor-prompt round1018` (T-1742…T-1749, **P1**, **ADR-1018-5**,
> **AMEND ADR-1013-3**): `FACT_EXTRACT_PROMPT` — модульная константа → `PREV_…` + байт-тесты,
> `PROMPT_MIGRATIONS` **не трогается** (крон-промпт `EXTRACT_PROMPT` — другой, вне скоупа);
> `importance` считает `rule_importance()`, НЕ LLM; хард-лимит **`min(imp, 1)`** в
> `insert_graph_fact` по penalty-стоп-листу (6 слов, отдельный frozenset); флаг
> `flags.metafact_penalty_enabled` OFF (**+1 REGISTRY/+1 Settings**).
> **F6** `role-matrix-settings-actualization round1018` (T-1750…T-1757, **P2**, **ADR-1018-6**):
> «Матрица ролей» = фактическая карта мини-аппа (3 nav: Модули 11 / ИИ 7 / PERMsoc);
> `NAV_TITLES`/`NAV_ORDER`/`TAB_NAV` — Python-метаданные (счётчики не растут); подпись
> `CONFIG_TAB_TITLES[permsoc]` → «PERMsoc» + инвариант-тест; аддитивные `nav/nav_title/nav_order`;
> сводит Δ каталога (**437/407** vs 436/406). Последняя.
> **F7** `settings-worker-sync round1018` (T-1758…T-1766, **P0 — новый пункт итерации 2**,
> **ADR-1018-7**): **критичный рассинхрон UI↔воркеры** — тумблеры Dream/DeepSleep ON в UI,
> бэкенд видит OFF. Корень: воркеры/статус-API читают только глобальный `hot.get`, а UI пишет
> в `chat_params.overrides`; планировщик регистрирует джоб один раз на старте; `pg_notify`
> без `LISTEN`; тумблер `deep_sleep` вне окна «Сон». Решение: единый accessor
> (**per-chat DB → глобальный DB → env-дефолт**), реактивный планировщик, `LISTEN`, `source=`
> в статус-API/логах, UI-хинт (Δ=0). **F7 — первая** (без неё F2 не проверяема).
>
> **Решения владельца (UPD, итерация 2):** DDL `edges.fact_id` v9→v10 — **ДА**; manual обходит
> гейты **без фича-флагов** (новый стандарт базовой логики); включать
> `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` + **починить рассинхрон** (F7); BetterStack host через
> env; лимиты графа (seeds 150 / cap 800-2400), STOP_LIST, **importance мета-узлов = 1** — «как есть».
>
> **Противоречие памяти о BetterStack 401 — RESOLVED WITH ADR-1018-1:** в KG две
> взаимоисключающие записи (раунд 5 / T-746: «токен == public key `SENTRY_DSN` → 401» vs
> раунд 6: «ошибочная эвристика, Errors и Logs делят один токен, Sentry-сравнения удалены»).
> Итог: первопричина — **EU-хост при US-регионе**; диагностика **curl-матриксом ДО правки**
> (T-1704); хост US через `BETTERSTACK_HOST`; сравнение возвращается **только** как WARNING-диагностик
> (KG `risk-betterstack-401-token-vs-region-round1018`).
>
> **⚠️ Дрейф — СУЖЕН (F3-часть снята, Step 3→реализация):** F3 объявляла «каталог Δ=0»,
> но ADR-1018-3 D7 вводил флаг `flags.graph_scoring_v2_enabled` — **флаг НЕ вводится**
> (D7 финально: поведение безусловно, дед-кода OFF нет, откат = `git revert`), поэтому
> конфликт «Δ=0 ↔ флаг» снят. Остаётся: spec F6 §6 всё ещё пинит `REGISTRY == 436`
> против §5 `437`; backlog (Step 1) устарел (6 фич / 5 ADR / нумерация
> `1018-4=metafact, -5=role-matrix`). На Merge — единый свод и обновление пин-тестов
> (KG `risk-catalog-delta-drift-round1018`).
>
> **Остаётся в силе:** R16, R17, порядок роутеров `bot.py`, `media/`/`.env` не трогать,
> каталог-Δ только санкционированно, русские conventional commits; `plans/current_task.md` —
> untracked (`.gitignore:70`), **секреты ТЗ в KG/MEMORY.md не вносились**.
> **Граф синхронизирован (Step 3):** Epic + 7 Feature + 7 ADR + 7 Risk + 3 ArchitecturalConstraint
> + ExternalDependency BetterStack + SpecDecision owner UPD + `tech-debt-round10.18` +
> `metric-snapshot-round1018-baseline`; 85 связей (HAS_FEATURE/PART_OF/GOVERNED_BY/DECIDES/
> **SUPERSEDES** (ADR-1018-3 → ADR-1015-2; ADR-1018-2 → F-10), **AMENDS** (ADR-1018-1 → раунды
> 4/5; ADR-1018-4 → F2 10.15; ADR-1018-2 → ADR-1017-3; ADR-1018-5 → ADR-1013-3),
> DEPENDS_ON (ADR-1018-2 → ADR-1018-7), RESOLVED_BY и др.).
>
> **UPD (Step 10, 15.09.2026): блок «Step 2/3» выше — исторический снимок планирования.**
> Факт финала: раунд **COMPLETED + DEPLOYED**, спеки в `plans/archive/<feature>/` (7),
> каталог **436/406** (F5-флаг не вводился; plan **437/407 отменён**), pytest **6139**,
> SQLite **v10**, commit **`16a8c0b`**; «Builder не начат» — устарело (все 75 задач закрыты).
> Актуальные цифры — в блоке «Step 10 (финал)» ниже и в `plans/metrics.md`.

> **Step 10 (финал @Memory) раунда 10.18 «Memory-Graph-Sleep-BetterStack bugfixes»
> (15.09.2026):** эпик `Epic round1018 (Memory-Graph-Sleep-BetterStack bugfixes)`
> → **COMPLETED + DEPLOYED + ARCHIVED**; создан релиз-узел **`release-round1018`**
> (alias **`release-16a8c0b`**, commit **`16a8c0b`**), фичи F1–F7 связаны
> (`DEPLOYED_IN release-round1018`), обновлены 7 ADR-1018-1…-7 (Accepted/реализовано),
> Risk-узлы (betterstack-401 → **RESOLVED** с остаточным блокером; catalog-delta-drift →
> **RESOLVED/NARROWED**; 5 проектных рисков **CLOSED**), `tech-debt-round10.18` (финал),
> `metric-snapshot-round1018-final`. Связи: `ADR-1018-6 AMENDS OD11-OD15`;
> дублирующие ADR-узлы итерации 2 консолидированы в канонические `ADR-1018-1…-7`.
>
> **Деплой-верификация:** commit **`16a8c0b`** (`fix(services,web,plans): раунд 10.18 —
> BetterStack US-хост и единый источник настроек воркеров, manual-приоритет Сна и каскад,
> скоринг графа Σ importance (SQLite v10), плотность и физика, пенализация мета-фактов,
> матрица ролей (тесты 6139)`); push `118a03c..16a8c0b`, прод fast-forward
> `b6c153f..16a8c0b`; `.env` += `BETTERSTACK_HOST=s2736363.us-west-2a.betterstackdata.com`,
> бэкап `.env` + SQLite (`local_database.db.bak.2026-09-15-0744`); `admin_bot` active
> PID **2319614**; `/api/health`=**200** (+ публичный healthz 200); миграция v10 применена
> (`PRAGMA user_version=10`); DML-миграция порогов Сна применена.
>
> **Метрики:** pytest 6007 → **6139 passed / 0 failed** (+132; scan-итерации 6042→6052→
> 6083→6104→6137→6139); JS-гейты OK; `git diff --check` clean; каталог **436/406/411/90/88/19**
> (Δ=+1); SQLite **v10**; APP_VERSION 2.57.0 без бампа. **@Reviewer:** Approved по всем
> батчам (4 раунда ревью + фиксы; отклонений Б1=1/B2=2/B3=1/B4=1). **@Scanner:** финал
> **0 Critical / 0 High** открыто; закрыто **1 High** (`S10.18-1`) + 6 Medium
> (`S10.18-15/-21/-22/-30/-35/-36`) + множество Low (закрыт `S10.17-2`); открыто
> **1 Low `S10.18-29`** + Info. **@Builder — ~7 rework-циклов.**
>
> **Ключевое:** BetterStack — US-хост через env (401 остаётся из-за неверного токена, не хоста);
> единый источник настроек воркеров (per-chat DB → global DB → env) + реактивный планировщик;
> manual-приоритет Сна с безусловным каскадом Сон→Глубокий→Личность (без флагов) и реактивными
> бейджами; граф — скоринг Σ importance + STOP_LIST + плотность 500–800 + физика off по
> стабилизации; пенализация мета-фактов (importance=1) + RAG-множитель; Матрица ролей под
> фактическую структуру мини-аппа. **SQLite v10**, каталог Δ=+1. §39 ARCHITECTURE.md.
>
> **Техдолг (открыт):** **Low `S10.18-29`** (deep-manual маркер при каскаде) + **Info**
> (`S10.18-12` NostalgiaWorker global-only → backlog **T-1764**; `S10.18-13` фрагмент
> SSH-пароля в tracked `plans/archive/security-rotation-finalize-round1016/spec.md:35` —
> вычистить + скан истории, значение НЕ цитировать; `S10.18-18/-19/-20`, `-31/-32/-33`,
> `-37` живая RAG-проверка). **Остаточный блокер владельцу:** реальный Source Token
> BetterStack в `.env` + рестарт (401). Живые проверки RAG/графа/бейджей/manual-каскада —
> за владельцем. Архив: `plans/archive/<feature>/` (**7 папок**; всего **76**), §39
> ARCHITECTURE.md.

> **АКТУАЛЬНЫЙ СТАТУС (14.09.2026):** раунд **10.17 «Mobile-Download-Badges»**
> — **COMPLETED + DEPLOYED** (функциональный HEAD == origin/master == **`b6c153f`**;
> ТЗ — `plans/current_task.md` секция «UPD3:», строки 155-160): 5 фич F1–F5
> (F1 `miniapp-mobile-dns`, F2 `tool-download-quality`, F3 `sleep-badge-countdown`,
> F4 `ssh-rotation-cancelled`, F5 `warnings-hygiene`), **37 задач T-1666…T-1702**,
> релиз **`release-round1017`** (alias `release-b6c153f`), 3 ADR (ADR-1017-1/2/3;
> ADR-1017-2 **SUPERSEDE** ADR-1016-1 §2 п.3/§3). ARCHITECTURE.md **§38**. Прод
> `admin_bot` active PID **2016726**, `/api/health` **200**, `/healthz` + `HEAD /web/`
> **200**, pytest **6007 passed / 0 failed** (+71), каталог **435/406/411/90/88/19**
> (Δ=0), миграций нет, APP_VERSION **2.57.0**. Спеки+ADR — `plans/archive/*-round1017/`
> (**5 папок**; всего **69**). Детали — KG-узел `Epic: Mobile-Download-Badges round1017`
> + блоки «Step 0», «Step 2/3» и **«Step 10 (финал)»** ниже; метрики — `plans/metrics.md`.
> Предыдущий раунд — **10.16 «Download-Guide-MobileAudit»**
> — **COMPLETED + DEPLOYED** (функциональный HEAD == origin/master == `eb3fd4a`): 5 фич F1–F5,
> 41 задача T-1625…T-1665, релиз **`release-round1016`**, 3 ADR (ADR-1016-1/2/3),
> заархивирован (`plans/archive/` — **64 папки**; `plans/features/` — 6 активных
> F-1…F-6). APP_VERSION **2.57.0** (без бампа), pytest **5936 passed / 0 failed**
> (+162), каталог **435/406/411/90/88/19** (Δ=0), БД без новых миграций
> (F2 — DML канона), прод `admin_bot` active PID **1976836**, `/api/health` **200**.
> Предыдущий раунд — **10.15** (COMPLETED + DEPLOYED, HEAD `d01a539`, гибридный
> Tool Calling; далее 10.14 — PG `personas`/`persona_traits`/`persona_state`;
> флаги `persona_enabled`/`bot_self_awareness_enabled` = **ON**).
> Метрики — `plans/metrics.md`. Блоки раунда 10.16 — ниже.

> **Step 0 (recon @Memory) раунда 10.17 «Mobile-Download-Badges» (14.09.2026):**
> ТЗ — `plans/current_task.md` секция «UPD3:» (строки 155-160). KG-узел
> `Epic: Mobile-Download-Badges round1017` + 5 Feature (§1–§5) + 5 Risk +
> `tech-debt-round10.17` + `metric-snapshot-round1017-baseline` +
> `ArchitecturalConstraint miniapp self-host, no external CDN` + SpecDecision
> `ssh-rotation-cancelled round1017`. Статус — **RECON, Builder не начат**.
> Baseline: HEAD `772f192`, прод release-round1016 (`eb3fd4a`), APP_VERSION 2.57.0,
> pytest 5936/0, SQLite v9, каталог 435/406/411/90/88/19 (Δ=0).
>
> **§1 (P0, миниапп Android):** `net::ERR_NAME_NOT_RESOLVED` сохраняется после F4
> 10.16 (self-host CDN + CSP). Git-находка: `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL`
> (`config/settings.py:171-173,988-989` → `https://admin-bot.duckdns.org/web/`),
> кнопка (`handlers/menu.py:48-66`) и домен/scheme/path **в 10.13–10.16 НЕ
> менялись**; единственное крупное изменение рядом — F4 10.16 (`web/index.html`
> self-host, `web/app.py:_CSP_HTML`, `/static/app.css`). В `web/` внешних
> http(s)-URL больше нет (grep пусто) → **ERR_NAME_NOT_RESOLVED = сбой резолва
> топ-домена, не CSP/subresource**; причина инфраструктурная (блокировка
> duckdns мобильными операторами / Private DNS / протухшая запись / кэш после
> смены A 10.16). Проверка — @DevOps (`dig A/AAAA`, `curl -I`, Android).
>
> **§2 (P0, tool-download):** tool `download_media` не работает и НЕ спрашивает
> качество; прямой «Бот, скачай» работает с выбором качества. ⚠️ **КОНФЛИКТ** с
> F1 10.16 / ADR-1016-1, где прямо записано «quality в JSON-Schema НЕ
> добавляется» (авто=`max`) → требуется SUPERSEDE пункта ADR. Точки:
> `services/tool_router.py` (~592-599), `tools/video_downloader.py`,
> `handlers/video_download.py` (~284-343), `services/media_send.py`.
>
> **§3 (P1, бейджи Сна):** UI показывает целевой час, не остаток —
> `web/app.js:1210-1245` (`dreamPhaseBadge`/`deepPhaseBadge`) + `fmtClock`
> (`web/app.js:5112-5119`); данные — `web/api/memory_agi.py:430-545`
> (`_next_hour_epoch` :75-88, `_in_hour_window` :104-116). Нужен duration-
> countdown; «Глубокий сон выключен» = `flags.deep_sleep_enabled` false;
> `deep.next_run_at` for `after_sleep` = next_wake (начало обычного сна) — вероятная
> логическая ошибка. Эмодзи не трогать, каталог-Δ=0.
>
> **§4 (CANCEL):** владелец отменил ротацию SSH — секреты в `plans/current_task.md`
> норма, файл не в репо (`.gitignore:70`); узел `security-rotation-finalize-round1016`
> → CANCELLED.
>
> **§5 (гигиена):** 3 WARNING в `web/api/avatars.py` (старый код, `d082800`/10.10;
> generic `except Exception`+`exc_info`) — понизить/убрать traceback (R17);
> «brotli» = только build-time (`scripts/requirements-font.txt`), Caddy-бротли
> требует плагина `http.encoders.brotli` (`xcaddy`) — @DevOps вне репо.
> Техдолг — `tech-debt-round10.17`.

> **Step 2/3 (Step 2 @Architect — синк Step 3 @Memory) 14.09.2026 (раунд 10.17
> «Mobile-Download-Badges»):** эпик `Epic: Mobile-Download-Badges round1017` —
> **ARCHITECTED / SPEC_READY, Builder не начат**. **5 фич F1–F5 / 37 задач
> T-1666…T-1702** (во всех 5 `plans/features/*-round1017/` — `spec.md` + `tasks.md`,
> 🟣 SPEC_READY) + **3 ADR** (ADR-1017-1/2/3; F4 docs-only и F5 brotli-WONTFIX — без ADR).
> Каталог-Δ = **0** (REGISTRY **435** / Settings **406** / categorized **411** /
> GROUPS **90** / mapped **88** / `TAB_RULES` **19**); **DDL нет** (SQLite v9).
> Baseline: HEAD `772f192`, pytest **5936/0**, APP_VERSION **2.57.0**, прод
> release-round1016 (`eb3fd4a`, PID **1976836**).
>
> **F1** `miniapp-mobile-dns` (T-1666…T-1674, **P0**, **ADR-1017-1**): причина —
> сбой резолва **топ-домена** `admin-bot.duckdns.org` (не subresource/CSP);
> hostname/схему/путь **в репо не меняем** (`WEBAPP_URL` env-driven → смена домена
> = правка `.env` + restart, процедура в ADR §4). Repo-меры: явные **HEAD `/web/`**
> и `/web/index.html`, unauth **`/healthz`** (GET+HEAD, `no-store`), startup-лог
> host/scheme/path (host-only, R17), регресс-гейт «нет внешних CDN + консистентные
> absolute-URL». Реальный DNS-фикс — **@DevOps** вне репо (DuckDNS A/AAAA/TTL,
> Private DNS/DoH, live Android-смоук). CDN не возвращать (ADR-1016-2 в силе).
> **F2** `tool-download-quality` (T-1675…T-1684, **P0**, **ADR-1017-2**,
> **⚠️ SUPERSEDE ADR-1016-1** §2 п.3/§3): меню качества инициирует **бэкенд** —
> `probe` → инлайн-клавиатура **`tdq:<height>`** → `tool_response`
> `{status:"needs_quality"}`; callback `tdq:` в роутере **4e** доводит download+send
> (как Fast-Track `cb_pick_quality`). `quality` в JSON-Schema — **опционально**
> (`QUALITY_ENUM` ↔ `_ALLOWED_HEIGHTS`) при явном запросе; прямой медиа-URL — без
> меню; bounded fallback `download(url,None)`; кулдаун **D279** (touch только после
> успеха, callback не трогает); pending in-memory **TTL 600с** без PG/DDL; лимиты
> tool-loop **4/2** и tool-сет **7** не меняются. **Конфликт с F1 10.16 снят.**
> **F3** `sleep-badge-countdown` (T-1685…T-1691, **P1**, **ADR-1017-3**, независима):
> `now` = серверный `cognition.generated_at`; новый `fmtCountdown` (**Xч Yм** / Yм /
> 0м, округление вниз, кламп ≥0); вне фазы — «Сон через {остаток}» / «Глубокий сон
> через {остаток}» (при `enabled=false` — остаток `badge-muted` **без свечения**, не
> «выключен»); в фазе — `.glow` + «Сон до HH:MM» / «Глубокий сон до HH:MM»; **эмодзи
> ☀️/🌙/🌅/🌌 не трогать**; `limit_exhausted` сохраняется; API и оконная семантика
> 10.15 не меняются; без tick-таймера.
> **F4** `ssh-rotation-cancelled` (T-1692…T-1695, **P0 doc**, docs-only, без ADR,
> последняя): **ОТМЕНА** ротации SSH (10.16 F5) — CANCELLED-пометка в
> `plans/backlog.md` + архиве 10.16, снятие README-overclaim (строки 74/387),
> подтверждение untracked `plans/current_task.md`; **кода — ноль**.
> `security-rotation-finalize-round1016` → **CANCELLED**.
> **F5** `warnings-hygiene` (T-1696…T-1702, **P2/P3**, без ADR, независима): политика
> уровней логов в `web/api/avatars.py` (TelegramBadRequest → `debug` без `exc_info`;
> транзиент → `warning` без трейса, не кэшируется; прочее → `warning` с `exc_info`,
> R17-safe; негатив-кэш сохранить) + **brotli WONTFIX** (Caddy `zstd+gzip` уже
> включено; brotli в репо — только build-time); тесты `caplog`.
>
> **Порядок:** F1 ∥ F2 ∥ F3 ∥ F5 → F4 (docs, последняя); **все фичи независимы**
> (DEPENDS_ON внутри раунда нет; F4 связана с 10.16 F5). **В силе:** R16, R17,
> порядок роутеров `bot.py`, `media/`/`.env` не трогать, каталог-Δ только
> санкционированно, русские conventional commits. **Граф синхронизирован (Step 3):**
> 5 Feature + 3 ADR (`ADR-1017-1/2/3`) + компоненты `HEAD /web/ + /healthz routes`,
> `tool quality-menu flow (tdq:)`, `sleep badge countdown (fmtCountdown)`,
> `avatars log hygiene`, `F5 brotli WONTFIX`, `ADR-1016-1 Download contract`;
> обновлены Risk/SpecDecision/`tech-debt-round10.17`/`DuckDNS + Caddy + Let's Encrypt`/
> `miniapp self-host, no external CDN`/`tool_router download_media`; связи
> PART_OF/IMPLEMENTS/DECIDES/**SUPERSEDES** (`ADR-1017-2` → `ADR-1016-1`; F2 →
> `download contract quality fix`) + `metric-snapshot-round1017-spec-ready`.

> **Step 10 (финал @Memory) раунда 10.17 «Mobile-Download-Badges» (14.09.2026):**
> эпик `Epic: Mobile-Download-Badges round1017` → **COMPLETED + DEPLOYED**;
> создан релиз-узел **`release-round1017`** (alias **`release-b6c153f`**, commit
> **`b6c153f`**), фичи F1–F5 связаны (COMPLETED_IN/DEPLOYED_IN), обновлены
> ADR-1017-1/2/3, компоненты (`HEAD /web/ + /healthz routes`,
> `tool quality-menu flow (tdq:)`, `sleep badge countdown (fmtCountdown)`,
> `avatars log hygiene (web/api/avatars.py)`, `F5 brotli WONTFIX`),
> Risk-узлы (закрыты), `tech-debt-round10.17`, SpecDecision
> `ssh-rotation-cancelled round1017` (**CANCELLED**) и `metric-snapshot-round1017-final`;
> связь **SUPERSEDES** `ADR-1017-2` → `ADR-1016-1 Download contract` применена.
>
> **Деплой-верификация:** commit **`b6c153f`** (`fix(services,handlers,web,docs,plans):
> раунд 10.17 — ... (тесты 6007)`), push `772f192..b6c153f`, прод fast-forward
> `eb3fd4a..b6c153f`, `admin_bot` active PID **2016726**, лог без traceback.
> `/api/health` = **200**; `/healthz` GET+HEAD = **200** (no-store); `HEAD /web/` = **200**;
> `/api/memory/graph` = **401**; `/api/persona/health` = **401**. **DNS** A→198.46.175.136
> (AAAA пусто, TTL 50); **LE** notAfter 2026-11-28; Caddy `encode zstd gzip`
> (gzip подтверждён). **Миграций БД нет, `.env` не правился.**
>
> **Метрики:** pytest 5936 → **6007 passed / 0 failed** (**+71**); `node --check
> web/app.js` clean; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` clean;
> каталог **Δ=0** (435/406/411/90/88/19); БД без новых миграций (SQLite v9);
> APP_VERSION **2.57.0** без бампа. **@Reviewer:** итер.1 **Rejected** (3 Medium —
> overclaim ротации в ARCHITECTURE, транзиенты аватаров на 2 из 6 сайтов,
> дублирование меню качества) → итер.2 **APPROVED**. **@Scanner:** итер.1
> **0 C / 0 H / 1 Medium / 2 Low / 3 Info** (Medium `S10.17-1` docs — закрыт
> @Architect на Merge) → контракт по C/H пройден. **@Builder — 2 реворка.**
>
> **Ключевое:** tool-скачивание предлагает выбор качества (`probe → меню tdq: →
> callback`), падение исправлено, ADR-1016-1 помечен SUPERSEDE; бейджи Сна —
> «через {остаток}» / «до HH:MM» (эмодзи не тронуты); `HEAD /web/` + `/healthz`
> (диагностика DNS, no-store) + startup host-лог; политика логов аватаров (6 сайтов,
> транзиенты без трейса/кэша); brotli — WONTFIX; **ротация SSH — CANCELLED**.
>
> **Техдолг (открыт):** **Low `S10.17-2`** (бейдж «Сон через —»/«Глубокий сон через —»
> при `cognition==null` вместо «—»; функц. вреда нет) + **Info 3** (`S10.17-4`
> `log_download_env_once` parity, `S10.17-5` hot-флаг в callback `tdq:`, `S10.17-6`
> `/healthz` version) + **WONTFIX** brotli; ротация SSH — **CANCELLED**. Ручной
> Android-смоук — у владельца (инструкция в отчёте @DevOps). Архив:
> `plans/archive/*-round1017/` (**5 папок**), §38 ARCHITECTURE.md.

> **Step 10 (финал @Memory) раунда 10.16 «Download-Guide-MobileAudit» (14.09.2026):**
> эпик `Epic: Download-Guide-MobileAudit round1016` → **COMPLETED + DEPLOYED**;
> создан релиз-узел **`release-round1016`** (commit **`eb3fd4a`**), фичи/ADR связаны
> (COMPLETED_IN/DEPLOYED_IN/IMPLEMENTED_IN), обновлены `tech-debt-round10.16`,
> SpecDecision-компоненты (download contract, canon versioning/force-delivery,
> miniapp self-host/CSP, smoke suite, SSH rotation), `security scan round1016`,
> `help guide canon`, `tool_router download_media`, `DuckDNS + Caddy + Let's Encrypt`,
> 4 Risk-узла (закрыты) и `metric-snapshot-round1016-baseline` (финал).
>
> **Деплой-верификация:** commit **`eb3fd4a`** (`fix(services,handlers,web,docs,plans):
> раунд 10.16 — ... (тесты 5936)`), push `18a9aa1..eb3fd4a`, прод fast-forward
> `d01a539..eb3fd4a`, `admin_bot` active PID **1976836**. **Гайд доставлен в PG:**
> `canon_version=2`, `canon_delivered_version=2`, `canon_drift=False`, `prev_html`
> сохранён, `html_len==seed_len==4592`. `/api/health`=200, `/api/memory/graph`=401,
> `/api/persona/health`=401. **DNS** A→198.46.175.136 (AAAA нет), LE notAfter
> 2026-11-28; `/web/` GET 200 + CSP(`'unsafe-eval'`); Caddy: включено
> `encode zstd gzip` (backup) — сжатие появилось. SSH-ключ работает (парольный вход
> сохранён намеренно); live-скачивание видео — ручной шаг владельцу.
>
> **Метрики:** pytest 5774 → **5936 passed / 0 failed** (**+162**); `node --check`
> clean; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` clean; каталог **Δ=0**
> (435/406/411/90/88/19); БД без новых миграций (F2 — DML канона `canon_version`);
> APP_VERSION **2.57.0** без бампа. **@Reviewer:** итер.1 **Rejected** (Critical CSP
> `script-src 'self'` ломал Vue full build; High R17-логи URL, доставка гайда,
> README-overclaim) → итер.2 **APPROVED**. **@Scanner:** итер.1 0C/1H/1M/6L →
> итер.2 **0 C / 0 H / 0 M** (Low 1 — `S10.16-9`). **@Builder — 2 реворка.**
>
> **Техдолг (открыт):** **Low `S10.16-9`** (latent hardening — 4 raise-сайта
> `tools/video_downloader.py:767,772,899,904`; доступного лог-пути нет — утечки нет) +
> **WONTFIX** `S10.13-9`/`S10.13-11`/`R10.14-4` + **R17-долг** `current_task.md`
> (untracked; ротация — по желанию владельца). **@DevOps-заметки:** HEAD `/web/` 404
> (pre-existing FastAPI/StaticFiles), brotli-плагин Caddy, live-smoke скачивания.
> Архив: `plans/archive/*-round1016/` (**5 папок**), §37 ARCHITECTURE.md.

> **Step 0 (recon @Memory) раунда 10.16 «Download-Guide-MobileAudit» (14.09.2026):**
> ТЗ — `plans/current_task.md` секция «UPD2:» (строки 148-153). KG-узел
> `Epic: Download-Guide-MobileAudit round1016` + 4 Risk-узла. Статус —
> **RECON, Builder не начат**. Проверка репозитория: `plans/current_task.md` —
> **НЕ в git** (`git ls-files` пусто, `git log --all` пусто, `git rev-list --all
> --objects | grep current_task` = 0, `.gitignore:70`) → **пароль в истории git
> ОТСУТСТВУЕТ**; но он есть в рабочем файле (строки 63-65) → сменить/отозвать.
> **§1 (download):** два независимых дефекта — (a) tool-путь:
> `services/tool_router.py:592-594` всегда шлёт quality `"direct"` →
> `_normalize_quality('direct')` (`tools/video_downloader.py:695-705`) →
> `DownloadError("invalid quality")` для YouTube/платформ (проверено рантаймом;
> работает только для прямых `.mp4`); (b) ручной путь: `probe()` в
> `handlers/video_download.py:326-331` падает по окружению (cookies/proxy/POT/
> SABR-403) → «битая ссылка». **§2 (гайд):** `_migrate_info_how_it_works_v1015`
> (`services/config_cache.py:235-266`) осознанно **пропускает** перезапись, если
> прод-PG `content.info_how_it_works` != `PREV_DEFAULT_INFO_TEXT` (ручная правка);
> косвенно подтверждено дрейфом `info_text.md` при деплое 10.15 (tracked-файл
> как write-path `/edit_info`). **§4 (миниапп):** DuckDNS+Caddy+LE
> (`admin-bot.duckdns.org`), Android `ERR_NAME_NOT_RESOLVED` = DNS-резолв
> (duckdns-блокировка/протухшая запись/IPv6); ~1 мин — тяжёлый несобранный
> фронт (`index.html` ~235 КБ + `app.js` ~285 КБ) + CDN-Tailwind/telegram-web-app.
> **В силе:** R16, R17, порядок роутеров `bot.py`, `media/`/`.env` не трогать,
> русские conventional commits. Открытый техдолг 10.13-10.15 (см. ниже) — в
> скоупе §3 (полный аудит). Детали — KG + `plans/reports/*`.

> **Step 2/3 (Step 2 @Architect — синк Step 3 @Memory) 14.09.2026 (раунд 10.16
> «Download-Guide-MobileAudit»):** эпик `Epic: Download-Guide-MobileAudit round1016`
> — **ARCHITECTED / SPEC_READY, Builder не начат**. **5 фич F1–F5 / 41 задача
> T-1625…T-1665** (во всех 5 `plans/features/*-round1016/` — `spec.md` + `tasks.md`,
> 🟣 SPEC_READY) + **3 ADR**. Каталог-Δ = **0** (REGISTRY **435** / GROUPS **90** /
> Settings **406** / categorized **411** / mapped **88** / `TAB_RULES` **19**);
> **DDL нет** (единственная миграция — DML `info_how_it_works` в F2). Baseline:
> HEAD `18a9aa1`, pytest **5774/0**, APP_VERSION **2.57.0**, SQLite **v9**.
>
> **F1** `download-fix` (T-1625…1633, **P0**, **ADR-1016-1**): контракт
> `download(url, quality=None)` — `None`/`""`/`auto`/`best`/`max` → `max`,
> `"1080p"`/`1080` → `"1080"`, мусор → `invalid_quality` без сети; **`"direct"`
> больше не quality** (legacy-алиас → `max`); ветвление direct/платформа только по
> `is_direct_media_url` (без Content-Type/пробы); **R17-safe reason-коды**
> (`probe_timeout`/`probe_bot_check`/`cobalt_*`/…; в лог только `error=<Class>
> reason=<code>`, без URL); **env-preflight** `download_env_summary()` (presence
> cookies/proxy/pot/cobalt); **bounded probe-fallback** `_download_without_menu`
> (probe-fail не жжёт кулдаун).
> **F2** `guide-delivery` (T-1634…1641, **P1**, **ADR-1016-3**): **владелец
> РАЗРЕШИЛ ПРИНУДИТЕЛЬНО перезаписать** текущий текст гайда в PG
> (`content.info_how_it_works`) новым каноном из ТЗ (ценных ручных правок нет);
> вводится **`canon_version`** + `KNOWN_INFO_SNAPSHOTS` + `normalize_canon`
> (нормализованное сравнение, unknown-текст не затирается молча → `canon_drift`);
> **force-reset** `POST /api/info/reset-canon` (RBAC `edit_info`, бэкап
> `prev_html`, аудит `updated_by` = id); **`save_text` PG-only**, `info_text.md` —
> read-only сид/байт-канон → pull не блокируется; кнопка/команда `reset-canon`.
> **F3** `audit-recent-epics` (T-1642…1650, **P1**, →F1/F2): **in-process
> смоук-тесты** (pytest + моки PG/yt-dlp/cobalt/LLM, без сети/секретов) по 7
> подсистемам (download/probe, tool-loop, guide, graph, sleep, nostalgia, persona);
> **FIX** S10.13-6b/-13, R10.15-4/-10/-11; **WONTFIX+док** S10.13-9/-11, R10.14-4;
> отчёт `plans/reports/round10.16_audit.md`.
> **F4** `miniapp-mobile` (T-1651…1659, **P1**, **ADR-1016-2**, независима,
> параллельно F3): **владелец утвердил self-host ВСЕХ зависимостей** (Vue 3,
> Chart.js 4, Telegram WebApp SDK, **Tailwind → предсобранный CSS** build-time CLI +
> safelist), строгий **CSP** (`script-src 'self'`, без inline), убрать внешние CDN;
> `<style>` → `app.css`, сжатие Caddy (вне репо); DNS/Caddy — **@DevOps**.
> **F5** `security-rotation-finalize` (T-1660…1665, **P0**, →F1–F4, последняя):
> ротация/отзыв SSH-пароля (`plans/current_task.md` — **НЕ в git**, подтверждено),
> переход на SSH-ключи, README/R17; ротация может идти параллельно.
>
> **Порядок:** F1 → F2 → F3 → {F4 ∥ F3} → F5; **F1 и F2 независимы** (зависимости
> `F1→F2` **НЕТ**). **В силе:** R16, R17, порядок роутеров `bot.py`, `media/`/`.env`
> не трогать, каталог-Δ только санкционированно, русские conventional commits.
> **Граф синхронизирован (Step 3):** созданы 5 Feature + 5 SpecDecision
> (`download contract quality fix`, `guide canon versioning + force overwrite`,
> `miniapp self-host (Vue/Chart.js/Tailwind/Telegram SDK)`, `in-process smoke suite`,
> `SSH password rotation`) + `CSP script-src 'self' (round1016)` +
> `DuckDNS + Caddy + Let's Encrypt` + `tech-debt-round10.16` +
> `metric-snapshot-round1016-baseline` + `tool_router download_media`; обновлены
> 4 Risk-узла (статусы), 3 ADR, `tech-debt-round10.15`, `help guide canon`;
> связи CONTAINS/PART_OF/DEPENDS_ON (F3→F1/F2; F5→F1–F4), IMPLEMENTS, HAS_ADR,
> ADDRESSES, REQUIRES, CONSTRAINED_BY, SUPERSEDES.

> **Step 2/3 (Step 2 @Architect, итерация 2 — синк Step 3 @Memory) 14.09.2026
> (раунд 10.15 «Багфиксы Графа памяти, Воркера Сна и Ностальгии»):**
> ТЗ — `plans/current_task.md` §1–§7 + UPD владельца; эпик
> `Epic: Memory-Graph-Sleep-Nostalgia bugfixes round1015` — **ARCHITECTED /
> SPEC_READY, Builder не начат**. Владелец **отменил рубильник
> `flags.command_prefix_enabled`** (UPD §1) — **каталог-Δ = 0** (REGISTRY **435** /
> Settings **406** / categorized **411** / GROUPS **90** / mapped **88** /
> TAB_RULES **19**; прежний черновик итерации 1 с +1 ключом и 436/407/412
> **отменён**). Триггер системы = **непустое `active_persona.name`**: имя задано →
> префикс «<Имя>, » (+ эвристические склонения при len≥3), дефолтные ботворды
> `бот`/`ботик`/`ботяра` **отключаются**; имя пусто → «Бот, » и дефолты активны.
> Также **утверждена оконная семантика бейджей Сна** (UPD §3):
> `active = in_window OR running`, `active_until` = конец окна, вне окна — начало
> следующего; свечение `.glow` только в активной фазе.
>
> **9 фич / 76 задач T-1549…T-1624 (во всех 9 `plans/features/*-round1015/` —
> `spec.md` + `tasks.md`, 🟣 SPEC_READY):**
> **F1** `graph-sampling-centrality` (T-1549…1557, ADR-1015-2) — degree centrality,
> сиды топ-50 + окрестность + очистка сирот, финальный cap 120/240, закрывает
> S10.13-14; **F2** `graph-frontend-physics-search` (T-1558…1565, →F1) — barnesHut +
> «Поиск по графу»; **F3** `sleep-unblock-diagnostics` (T-1566…1574) — fallback
> порогов 2/8 за 3 дня без `distilled` (self-healing) + пре-гейт-лог `[Sleep]` на
> WARNING; **F4** `nostalgia-prompt-revamp` (T-1575…1583) — окно ±10, инжект
> Лора/мемов, перепись канона (ADR-1013-3); **F5** `status-graph-ui-relocation`
> (T-1584…1592, →F2/F3) — релокация статистики графа в Сводку + бейджи; **F6**
> `command-prefix-persona-routing` (T-1593…1602, ADR-1015-1) — реестр **17
> триггеров** (search 3 / youtube 4 / web 4 / checkup 3 / download 3) +
> bare-исключения `чекап`/`фактчек`; новые модули `services/command_registry.py`,
> `services/command_prefix.py`; порядок роутеров `bot.py` **НЕ меняется**
> (direct_chat yield → download 4e); сняты legacy-алиасы (F6-U1); **F7**
> `guide-rewrite-persona` (T-1603…1609, →F6) — перепись гайда под реестр/имя +
> идемпотентная DML-миграция `PREV_DEFAULT_INFO_TEXT`; **F8** `hybrid-tool-calling`
> (T-1610…1618, ADR-1015-3, →F6/F9) — JSON-Schema tools для основной LLM, tool-сет
> **7** (`query_chat_memory`/`dig_into_lore`/`execute_web_search`/`summarize_video`/
> `download_media`/`get_bot_health`/`get_recent_history`), Fast-Track приоритетен;
> корнер-кейс скачивания = фиктивный `tool_response {status:success}` при реальной
> отправке MP4 (сбой → честный `error`); **F9** `recent-history-tool`
> (T-1619…1624, →F8) — `get_recent_history` (depth≤150 ИЛИ query, стенограмма
> «Имя: текст», переиспользует `database.get_recent_messages`, DDL не нужен).
>
> **Порядок внедрения:** F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F9 (F8∥F9).
> **DDL не требуется** по всему раунду (read-only/UI/код-константы); единственная
> миграция — DML `info_how_it_works` (F7). **Остаётся в силе:** R16, R17, порядок
> роутеров `bot.py` (только DI-kwargs), `media/` и `.env` не трогать, каталог-Δ
> только санкционированно, русские conventional commits. **Граф синхронизирован
> (Step 3):** эпик + 9 Feature-узлов; 3 ADR (`round1015-command-prefix-policy`
> ADR-1015-1, `ADR-1015-2 graph sampling`, `round1015-hybrid-tool-calling-ADR-1015-3`);
> модули `services/command_registry.py`/`services/command_prefix.py`; механизмы
> `hybrid-tool-calling`/`graph centrality top-50`/`sleep threshold fallback`/
> `nostalgia lore/memes inject`/`status layout relocation`/`guide rewrite`; tool
> `get_recent_history`; связи PART_OF/DEPENDS_ON (F2→F1; F5→F2/F3; F8→F6/F9;
> F9→F8; F7→F6/F8/F9).

> **Синк STEP 10 (финал) раунда 10.15 «Багфиксы Графа памяти, Воркера Сна и
> Ностальгии + Гибридный Tool Calling» (14.09.2026):** эпик
> `Epic: Memory-Graph-Sleep-Nostalgia bugfixes round1015` — **COMPLETED +
> DEPLOYED**, 9 фич F1–F9, **76 задач T-1549…T-1624** — все закрыты;
> спеки+ADR заархивированы в `plans/archive/*-round1015/` (**9 папок**;
> `plans/archive/` — **59 папок**; `plans/features/` — 6 активных F-1…F-6).
> **Коммит:** `d01a539` (`feat(services,web,api,docs,plans): раунд 10.15 — умная
> выборка графа, диагностика Сна, ревамп ностальгии, префиксы команд и Persona,
> гибридный tool calling (тесты 5774)`); push origin/master `798e044..d01a539`.
> **APP_VERSION остался 2.57.0** (без бампа; README и код согласованы, тесты 5774).
> **Деплой-верификация:** прод `nik@198.46.175.136:/var/www/admin_bot`,
> fast-forward `eb2a232..d01a539`; ⚠️ инцидент серверного дрейфа `info_text.md`
> (fast-forward заблокирован) — разрешён вручную: backup + `git stash` → pull →
> `systemd admin_bot` **active (running) PID 1860445**; `/api/health` = **200**,
> `/api/memory/graph` = **401**, `/api/memory/stats` = **401** (не 500).
> **Миграций БД НЕТ** (SQLite остаётся **v9**; PG без изменений); `.env` не
> редактировался. **Метрики:** pytest **5589 → 5774 passed / 0 failed** (Δ **+185**;
> итер.1 @Scanner — 5761); `node --check web/app.js` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
> Каталог **Δ=0**: **REGISTRY 435 / Settings 406 / categorized 411** (GROUPS 90 /
> mapped 88 / `TAB_RULES` 19).
> **Ревью/аудит:** @Reviewer итерация 1 = **Rejected** (H1 F5 — `enabled=false`
> не гасил бейдж Сна; M1 F6 — нет правой границы слова у триггеров; M2 F6 —
> безусловный yield терял сообщение при выключенном модуле); итерация 2 =
> **APPROVED**. @Scanner итерация 1 = **0 C / 0 H / 3 M / 6 L**; итерация 2 =
> **0 C / 0 H / 0 M** (Low 3, Info 3). Закрыты R10.15-1/-2/-3/-5/-6/-7/-8/-9;
> остались R10.15-4 (deferred), R10.15-10, R10.15-11. @Builder — **2 цикла
> реворков**.
> **Архитектура:** `plans/ARCHITECTURE.md` **§36** «Карта раунда 10.15» +
> **ADR-1015-1** (command prefix policy), **ADR-1015-2** (graph sampling),
> **ADR-1015-3** (tool calling).
> **Ключевые решения:** команды требуют обращения; префикс = непустое имя
> персоны («из коробки», БЕЗ флага), иначе «Бот, »; реестр 17 команд + bare
> `чекап`/`фактчек`; гибридный tool-calling (7 JSON-Schema инструментов,
> корнер-кейс скачивания через `services/media_send.py`); `get_recent_history`
> (depth≤150/query); граф — Degree Centrality топ-50 + соседи + сироты (закрыт
> **S10.13-14**); сон — fallback 2/8 + лог `[Sleep]` WARNING; ностальгия ±10 +
> лор/мемы; бейджи оконной семантики. **Граф обновлён (Step 10):** эпик/милстоун
> → **COMPLETED+DEPLOYED**, созданы `release-round1015`, `tech-debt-round10.15`,
> `metric-snapshot-round1015-final`, `services/media_send.py`,
> `help guide canon (info_how_it_works)`; 9 фич → `DEPLOYED_IN release-round1015`
> + `ARCHIVED_IN plans-structure`; релиз `release-round1015 FOLLOWS release-round1014`.

> **Step 0 recon 13.09.2026 (раунд 10.14 — «Самосознание и Личность бота»,
> plans/current_task.md пп.1–7):** HEAD == origin/master == `2edc65b` (docs-финал
> 10.13), дерево ЧИСТОЕ, APP_VERSION 2.57.0, pytest **5392/0**, каталог
> **427/90/399/403** (TAB_RULES 19), SQLite v8. Эпик записан в KG —
> `Epic: Self-Awareness-Persona Refactor round1014` + милстоун
> `round1014-epic-self-awareness` (+ `round1014-persona-storage-ddl-free`,
> `risk-bot-self-echo-round1014`, `metric-snapshot-round1014-baseline`).
> §1 anti-echo: свои ответы УЖЕ хранятся как `graph_facts.origin='bot_direct_reply'`
> (query+answer) с весом 0.7 и идут в RAG+сон (`_DREAM_SOURCE_ORIGINS`); новый
> origin запрещён CHECK'ом SQLite (DDL-free маркировка — `status`/`belief_meta`).
> §2 Persona — greenfield (таблицы/полей `is_global`/`is_aware_ai`/`dynamic_traits`
> нет); «Досье» 10.13 = карточка ПОЛЬЗОВАТЕЛЯ, не бот. §3/§3.1/§7 — точки изменения
> найдены (hub «ИИ» 7 карточек, `_ribbonLoop` 2 ленты, порядок Статуса). §4 —
> global-save уже в 10.12 (R10.12-1 закрыт), нужен end-to-end аудит (связан с
> активной F-5 `config-read-path-audit`). §5/§6 — гайд и «Справка» существуют,
> нужен доп. редактируемый блок. ⚠️ Главный конфликт — **новая схема Persona vs
> инвариант «ноль новых PG-DDL»**: PG-таблицы живут в `services/pg_db.py`
> (идемпотентный DDL при старте); DDL-free путь — `bot_settings`/
> `chat_params.overrides`/каталог. Открытый техдолг: 5 Low `S10.13-*` +
> R10.11-4/R10.12-2..4/R10.3-1..2/R10.9-4. Дальше — Step 1 @PM (5–7 фич),
> Step 2 @Architect (решение Persona storage).
>
> ⚠️ **ЧАСТЬ ЭТОГО РЕКОНА УСТАРЕЛА (UPD 13.09.2026, см. блок «Step 2/3 (итерация 2)» ниже):**
> DDL-free-путь Persona (`bot_settings`/`chat_params.overrides`) и тезис «новый origin запрещён
> CHECK'ом SQLite» — **ОТМЕНЕНЫ ВЛАДЕЛЬЦЕМ**; инвариант «ноль PG-DDL» и «SQLite v8 / origin CHECK
> заморожен» **СНЯТЫ**. Актуальные цифры — 8 фич, T-1477…T-1548, каталог 435/406/411, SQLite v9.

> **Step 2/3 (итерация 2) 13.09.2026 (раунд 10.14 — ПЕРЕРАБОТКА под UPD владельца):**
> Владелец **РАЗРЕШИЛ** менять структуру БД и писать миграции (PG + SQLite) — прежние инварианты
> «ноль новых PG-DDL» (10.4–10.13) и «SQLite остаётся v8 / `graph_facts.origin` CHECK заморожен»
> **СНЯТЫ**; DDL-free-решения Шага 2 (Persona в `bot_settings`/`chat_params.overrides`, self-маркер
> через `status='self_reply'`, rule-based экстрактор) **ОТМЕНЕНЫ** владельцем («не лепим заплатки»;
> «делай базу логичной»; «вырезание сути регулярками убьёт контекст»). Политика —
> `plans/project.md` §«Политика DDL (обновлено раундом 10.14)»; KG-узел `DDL allowed (10.14)`
> (прежний узел `round1014-persona-storage-ddl-free` удалён).
>
> **Итог Шага 2: 8 фич F1–F8, задачи T-1477…T-1548 (72), 8 `spec.md` + 2 ADR, все SPEC_READY/ACCEPTED**
> (Step 1 @PM дал 7 фич/64 задачи — добавлена **F8** по UPD п.3); статус эпика — **ARCHITECTED**
> (Builder не начат). Каталог-Δ (санкционирован): **REGISTRY 427→435, Settings 399→406,
> categorized 403→411; GROUPS 90 / mapped 88 / TAB_RULES 19 — без изменений** (прежний черновик
> 436/92/20 отменён — вкладка «Личность» = special-screen, не `TABS`).
>
> **F1 `anti-echo-self-reply` (T-1477…1486):** origin `bot_self_reply` (11-й) + rebuild `graph_facts` +
> **SQLite v8→v9** (`_migrate_self_origin_v9`; копируются все 16 колонок, `id` 1:1 ⇒ FTS/vec валидны;
> обратимость — обратный `UPDATE origin` перед revert); вес `limits.graph_fact_weight_bot`=0.2,
> важность 2; экстрактор — **только LLM** (`services/self_reflection.py`, prompt-константа, fail-open);
> анти-эхо-инструкция `_SELF_ECHO_INSTRUCTION`; карантин self из Сна/золотых/компакции/
> `graph_stats.facts`; `persona_state` (PG singleton); флаг `flags.bot_self_awareness_enabled`=**True**.
> ADR-1014-2.
> **F2 `persona-storage-core` (T-1487…1497):** **PG `personas`** (id, chat_id NULL, is_global, name,
> biography, system_prompt_overrides, is_aware_ai, created_at, updated_at; CHECK скоупа, 2 partial
> UNIQUE, FK `chat_id`→`chat_profiles` ON DELETE CASCADE) + **`persona_traits`** (id, chat_id, trait,
> source, created_at); `services/bot_persona.py` (scope per-chat→global→empty, промпт-блок `<Persona>`,
> `_NO_AI_DISCLOSURE_BLOCK`); traits пишет DeepSleepWorker; API `GET/PUT/DELETE /api/persona` +
> `GET /api/persona/health`; флаг `flags.persona_enabled`=**True**. ADR-1014-1.
> **F3 `persona-ui-tab` (T-1498…1504):** special-screen `#/ai/persona` (карточка «Личность» в Hub «ИИ»),
> форма 3 поля + чекбокс «Осознаёт себя ИИ», scope-сброс; Δ каталога = 0.
> **F4 `persona-traits-ribbon` (T-1505…1510):** 3-я лента «Эволюция характера» (`_ribbonLoop`, сетка
> 3→1) + панель **метрик Личности в «Сводке»** (`#/oversight`: кол-во `dynamic_traits`, время
> последнего пересмотра, статус экстрактора; источник `GET /api/persona/health`).
> **F5 `settings-persistence-audit` (T-1511…1525):** write-path/scope/restart-аудит ВСЕХ параметров +
> dedicated-API раунда; закрывает R10.9-4 (health-кэш); границы с активной F-5
> `config-read-path-audit` (read-path — у неё, не дублировать).
> **F6 `help-guide-integration` (T-1526…1534):** гайд в БД (**PG `content.intelligence_guide`**, json) +
> второй редактируемый блок в «Справке» (Markdown-редактор + DOMPurify 3.4.15 self-host, preview,
> save); идемпотентный сид из `plans/docs/intelligence_user_guide.md` (ручные правки не
> перезатираются); API `GET/POST /api/info/guide`.
> **F7 `status-layout-reorder` (T-1535…1540):** порядок Статуса Сводка → **Сердцебиение** → Бот →
> Сервер → **Мониторинг Интеллекта** → Доступность ключей → История; Δ=0, правок `app.js` нет.
> **F8 `self-reflection-llm-provider` (T-1541…1548):** роль `reflection` → slug **`intel_reflection`**
> (`generate_worker`), 4 PG-ключа (models/keys), probe `intel_reflection_main`, третий parent-блок
> «LLM для саморефлексии (Экстрактор сути)»; пусто/ошибка → основная модель (fail-open). Паттерн
> ADR-1013-1.
>
> **Порядок внедрения:** F1 → F2 → {F3, F4} → {F5 ∥} → F6 → F7 (F8 самодостаточна, потребляется F1).
> **Остаются в силе:** R17, R16, порядок роутеров `bot.py` (DI-kwargs), `media/` и `.env` не трогать,
> каталог-Δ только санкционированно + пин-тесты, русские conventional commits. Риски:
> `risk-round1014-v9-migration-rebuild`, `risk-round1014-index-html-merge-conflicts`, self-эхо.
> **Граф синхронизирован (Step 3):** 8 Feature + 14 компонентов + ADR-1014-1/2 + `UPD owner decisions`
> + `DDL allowed (10.14)` + риски/техдолг/внешняя-зависимость/снимок метрик; узел
> `round1014-persona-storage-ddl-free` удалён.

> **Синк STEP 10 (финал) раунда 10.14 «Самосознание и Личность бота» (13.09.2026):**
> эпик **COMPLETED + DEPLOYED**, 8 фич F1–F8, **72 задачи T-1477…T-1548** — все `[x]`.
> **Коммит:** `eb2a232` (`feat(services,web,api,docs,plans): раунд 10.14 — самосознание и
> личность бота, PG Persona и SQLite v9, LLM-экстрактор, метрики Сводки, редактор Справки
> (тесты 5589)`); push origin/master `2edc65b..eb2a232`. HEAD == origin/master == `eb2a232`,
> дерево ЧИСТОЕ. **APP_VERSION НЕ бампился** (остался **2.57.0**; отдельный релиз v2.58.0 не
> выставлялся — см. KG `release-round1014`).
> **Миграции реализованы** (инварианты «ноль PG-DDL»/«SQLite v8» сняты владельцем):
> SQLite **v8→v9** (rebuild `graph_facts`, новый origin `bot_self_reply`), PG
> **`personas`/`persona_traits`/`persona_state`** (идемпотентный DDL). На проде после
> рестарта: `PRAGMA user_version=9`, PG-таблицы на месте.
> **Деплой-верификация:** прод `nik@198.46.175.136:/var/www/admin_bot`, fast-forward
> `8800bba..eb2a232`; `systemd admin_bot` **active (running) PID 1774527**; `/api/health` =
> **200**, `/api/persona/health` = **401** (не 500); `.env` не редактировался (дефолты
> безопасны, флаги ON в коде); пул `flags.persona_enabled`/`flags.bot_self_awareness_enabled`
> = **ON** по умолчанию (требование владельца).
> **Метрики:** pytest **5392 → 5589 passed / 0 failed** (Δ **+197**); `node --check web/app.js`
> clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean. Каталог
> **427/399/403 → 435/406/411** (REGISTRY/Settings/categorized); **GROUPS 90 / mapped 88 /
> TAB_RULES 19** — без изменений.
> **Ревью/аудит:** @Reviewer итерация 1 = **Rejected** (H1 persona optimistic-409 недостижим
> — `updated_at` не отдавался; H2 RBAC `edit_persona` не выдаётся; H3 per-chat флаги читались
> только глобально `hot.get`), итерация 2 = **APPROVED**. @Scanner итерация 1 =
> **0 C / 0 H / 2 M / 5 L**, итерация 2 = **0 C / 0 H / 0 M** (Low 2, Info 2); закрыты
> R10.14-1 (RBAC view/edit `edit_persona`) и R10.14-2 (traits-LLM вне `worker_budget`).
> @Builder — **2 цикла реворков**.
> **Архитектура:** `plans/ARCHITECTURE.md` **§35** «Карта раунда 10.14» + **ADR-1014-1**
> (PG Persona: `personas`/`persona_traits`/`persona_state`) + **ADR-1014-2** (origin
> `bot_self_reply` + SQLite v9 + LLM-экстрактор). Спеки+ADR заархивированы в
> `plans/archive/*-round1014/` (**8 папок**; `plans/archive/` — **50 папок**;
> `plans/features/` — снова 6 активных F-1…F-6).
> **Техдолг (открыт, не блокеры):** Low `R10.14-4` (traits без `chat_id` — осознанно по F4),
> `R10.14-7` (aiosqlite-leak, pre-existing), `L5` (@Reviewer: hot-path — 2 доп. PG-запроса +
> запись `persona_state` на каждый direct-ответ, кэша нет); Info `I10.14-1` (каскад v7→v9 не
> покрыт юнит-тестами), `I10.14-2` (FIFO-ротация traits глобальная). KG — `tech-debt-round10.14`.
> **Примечание:** `betterstack_handler WARNING 401` (внешний `LOGTAIL_SOURCE_TOKEN`) —
> pre-existing, вне раунда. Граф обновлён (Step 10): эпик/милстоун → **COMPLETED+DEPLOYED**,
> созданы `release-round1014` и `metric-snapshot-round1014-final`, 8 фич →
> `COMPLETED_IN`/`DEPLOYED_IN`/`ARCHIVED_IN plans-structure`, `DDL allowed (10.14)` →
> РЕАЛИЗОВАНО.

> Создан заново 07.09.2026 (pre-планирование эпоса «Multi-chat scaling +
> Granular RBAC + BYOK + PERMsoc-плагин + TMA-навигация»). Прежние plans/
> файлы удалены 03.09.2026. Синк STEP 3 выполнен 07.09.2026 (HEAD fac1b9f):
> раунд 10 распланирован — 6 фич F-7…F-12, T-843…T-924, spec.md @Architect,
> tasks.md @PM, статус «запланирован»; граф обновлён (entity feature-*).
> **Синк STEP 9 (финал) выполнен 08.09.2026 (HEAD fac1b9f): раунд 10
> ЗАВЕРШЁН и заархивирован** — 4717 passed / 0 failed (подтверждён прогоном,
> 54.46s), аппрув @Reviewer, архив 15 папок, ARCHITECTURE.md §22, DevOps
> runbook готов; БЕЗ коммита (worktree dirty); граф обновлён
> (feature-* → archived + round10-epic + ARCHIVED_IN).
> **Синк STEP 9 (финал, post-commit) 08.09.2026: раунд 10 закоммичен и
> задеплоен** — HEAD == origin/master == `533bf13` (69be94e + 533bf13),
> прод обновлён (PID 133710, DDL ok, бэкфилы done); граф обновлён
> (round10-epic → completed+deployed, AdminBot → DEPLOYED).
> **Step 0 recon 08.09.2026 (post-deploy баг-репорт TMA):** 4 группы
> багов найдены в коде, подробные координаты — KG-сущность
> `recon: tma-round10-postdeploy-bugs` + `bug: tma-*` (4 шт). Кратко:
> (1) конфиг-вкладки Промпты/Лимиты/LLM Провайдеры/Память и RAG/Реакции
> и Триггеры пустые — `web/index.html:436,538,542` вызывают НЕСУЩЕСТВУЮЩИЕ
> `basicItems(grp)`/`advancedItems(grp)` (в `web/app.js` только
> неиспользуемый `itemAdvanced` :1168) → TypeError при рендере;
> (2) логи — сервер отдаёт newest-first (`services/log_ring.py:153`), но
> `loadLogs` автоскроллит ВНИЗ (`app.js:1700-1704`) → старые видны внизу;
> per-line «Скопировать» (index.html:1586), невидимое поле = textarea-
> фолбек `copyText` (app.js:1742-1748); (3) relations — обогащение
> username/photo_file_id только топ-30 (`web/api/chat_lore.py:562-568`),
> имена каскадом names-map(30д/200)→aliases(флаг summary_enabled)→uid
> (user_relations.py:346-349, bot.py:570-571), панель ограничена только lg
> (index.html:1122-1123); (4) modules_feats — placeholder «Выберите чат в
> шапке» при `activeChatId==null` (index.html:748-750), карточки в v-else
> (751-869), `loadGateInfo` early-return (app.js:780-784). Тесты — только
> маркерные, баги не ловят. Отдано @Builder (RESEARCH ONLY, без правок).
> **Синк STEP 9 (финал, хотфикс 10.1) 08.09.2026:** раунд 10.1 ЗАВЕРШЁН и
> ЗАДЕПЛОЕН — HEAD == origin/master == `8eae899` (поверх 533bf13), 4 группы
> багов рекона закрыты (review PASS), тесты 4726, README «Хотфикс 10.1 —
> бот взял себя в руки»; прод 198.46.175.136: PID 159455 (active, since
> 2026-09-07 16:27:04 UTC), journal чист; граф обновлён (милстоун
> `round10.1-hotfix` → COMPLETED+DEPLOYED, FIXES tma-frontend,
> RESOLVES recon, AdminBot → COMPLETED). Новых follow-up нет.
> **Step 0 recon 09.09.2026 (пост-10.1 баг-репорт TMA, 7 багов):** RESEARCH
> ONLY, 7 багов из ультиматума юзера (bug 8 — место на диске сервера,
> DevOps, вне кода). Подробные координаты — KG `recon: tma-bugs-7-post-10.1`
> + `bug: tma-*` (7 шт). Кратко: (1) селектор чата скрыт — `index.html:389`
> `accessChats.length > 1` для global admin (+вторично PG-down → пустой
> `/api/access/chats`); (2) сайдбар без `overflow-y` (index.html:347/328-340);
> (3) нет вкладки «Функции PERMsoc» — параметры разбросаны по
> reactions_persons/reactions_mimic/reactions_word_reactions/limits_mimic/
> flags_media, TAB_RULES (param_catalog.py:1359) «группа → ровно 1 вкладка»;
> (4) аватары только инициалы (топ-50 + негатив-кэш 1ч, chat_lore.py:574-580,
> avatars.py:113-136, app.js:536-550), имена = грязный author_name БЕЗ
> санитизации (_participant_names chat_lore.py:602-616); (5) аккордеон
> `(0)` — details.advanced рендерится всегда (index.html:559-567);
> (6) модалка прав — 2 select min-ролей + checkbox (index.html:1914-1952,
> access.py:129-143 дефолт view=user); (7) «невидимое поле» — off-screen
> textarea-фолбек copyText (app.js:1792-1816), CSS-класса нет (инлайн-стили).
> Тесты: маркерные test_webapp_* (nav_disclosure/rbac/avatars/tma_fixes),
> test_frontend_tab_mapping, test_access.py, test_relations_service.py —
> баги НЕ ловят, часть фиксирует текущее поведение и потребует обновления.
> Отдано @Builder (без правок).
> **Синк STEP 9 (финал) 09.09.2026 (раунд 10.2):** фиксы рекона
> `recon: tma-bugs-7-post-10.1` РЕАЛИЗОВАНЫ и УТВЕРЖДЕНЫ (@Reviewer PASS,
> минор B-1 TABS-зеркало закрыт), 4759 passed / 0 failed (прогон в .venv,
> 64.00s), НО НЕ ЗАКОММИЧЕНЫ — 26 файлов modified + untracked plans/MEMORY.md,
> HEAD == 8eae899; коммит/деплой ожидают решения юзера. Граф обновлён:
> милстоун `round10.2-fixes` (IMPLEMENTED + PENDING_COMMIT, RESOLVES recon,
> FIXES 7 bug: tma-*). Диск сервера уже исправлен DevOps (см. раздел ниже).
> **Синк STEP 9 (финал, post-commit) 09.09.2026: раунд 10.2 ЗАКОММИЧЕН и
> ЗАДЕПЛОЕН** — HEAD == origin/master == `d30b203` (поверх 8eae899,
> 28 файлов, +1576/−314), тесты 4760 passed / 0 failed, @Reviewer APPROVED
> (имена as-is: ID никогда не имя; каскад alias→nickname raw→username(без @)→'';
> avatarInitial графема); прод 198.46.175.136: PID 454654, DDL ok, polling,
> webapp 200 «Функции PERMsoc», без Traceback, .env без изменений; README
> обновлён; граф обновлён (милстоун `round10.2-fixes` → COMPLETED+DEPLOYED,
> AdminBot → DEPLOYED, создан `server-hardening-102` → DEPLOYED).
> **Безопасность сервера (DevOps, 09.09.2026) — fail2ban/ufw/SSH-харденинг
> АКТИВНЫ** (см. раздел «Безопасность сервера» ниже); follow-up: миграция
> на SSH-ключи (решение владельца), ignoreip для статического IP, CrowdSec
> альтернатива, migrate_history 1.1G перенос.
> **Step 0 recon 09.09.2026 (раунд 10.3, 7 задач ТЗ юзера):** HEAD ==
> origin/master == `d30b203` (10.2 закоммичен+задеплоен, PID 454654),
> ветка master, дерево ЧИСТОЕ (untracked: plans/MEMORY.md + plans/reports/
> только). 7 задач ТЗ → раунд 10.3: F-13 `tma-chat-selector-fixes`
> (задачи 1,2,3,6 = AC-1/AC-2/AC-3/AC-5) + F-14 `dm-user-settings`
> (задача 4 = AC-4), милстоун `round10.3-epic` — статус **ARCHITECTED**
> (T-925…T-964, PM+Arch done, Builder не начат). ⚠️ (коррекция ниже —
> файлы уже НЕ пустые). Задачи 5 (sandbox reason=budget) и 7
> (graphrag JSON list) — НОВЫЕ бэкенд-реконы (KG: `recon:
> direct-chat-sandbox-budget` + `recon: graphrag-memorize-json-list`);
> на Step 0 были «вне планирования», но далее включены в F-15 (см. ниже).
> **Синк STEP 3 (планирование 10.3) 09.09.2026:** раунд 10.3 перепланирован —
> **3 фичи**: F-13 `tma-chat-selector-fixes` (T-925…T-944; tasks.md пересоздан по
> KG-канону, файл был утрачен), F-14 `dm-user-settings` (T-945…T-964; tasks.md
> пересоздан по KG-канону), **F-15 НОВАЯ** `direct-sandbox-budget-investigation`
> (T-965…T-973; задачи 5 и 7 ТЗ — sandbox reason=budget + graphrag JSON list;
> прод-диагностика T-965/T-966 ДО фикса). spec.md для всех трёх фич — @Architect
> (F-13/F-14 — пересоздание по KG-наблюдениям, F-15 — создание). Статус милстоуна
> `round10.3-epic` → ARCHITECTED (F-13/F-14/F-15, всё spec.md+tasks.md на диске:
> пересозданы/созданы 09.09.2026 — наблюдение Step 0 «файлы отсутствуют»
> УСТАРЕЛО; F-15: прод-диагностика T-965/T-966 (TODO) ДО фикса, Builder не начат);
> конфликт-матрица с F-1/F-3/F-4/F-5 зарегистрирована в plans/backlog.md
> (раунд 10.3); аудит Scanner (plans/reports/full_audit_results.md) учтён
> (HIGH-004/MED-015/017/019/021/022 → задачи фич; остальное — кандидат в отдельный
> техдолг-эпик). Граф обновлён (Step 3): AdminBot HAS_PLAN → F-13/F-14/F-15,
> F-14 DEPENDS_ON F-13 (+F-1 post-deploy-admin-minors, RELATED_TO F-3 scam-followup),
> F-13 CONFLICTS_WITH F-4 frontend-admin-bugfixes (Баг-4, общий рендер :551-552),
> F-15 RELATED_TO DirectChatService/summary-subsystem, PART_OF round10.3-epic.
>
> **Merge Phase 10.3 (10.09.2026, @Architect)** — F-13/F-14/F-15 IMPLEMENTED в рабочем
> дереве (HEAD d30b203 + 10.3, 27 файлов), @Reviewer APPROVED, Scanner-аудит 10.3:
> **0 blocker/major** (minor/info R10.3-1…R10.3-6 → ARCHITECTURE.md §24), pytest
> **4831 passed / 0 failed**, `node --check web/app.js` clean. ARCHITECTURE.md обновлён:
> §23 (раунд 10.3: DM-скоуп и настройки ЛС /F-14, единый селектор чатов + z-index /F-13,
> sandbox-budget + memorize-JSON /F-15) + §24 «Известные ограничения и техдолг»
> (R10.3-1…R10.3-6 + ссылка на остаток полного аудита); кросс-указатели §3/§4/§5/§9/§16.
> Локальные спеки F-13/F-14/F-15 НЕ тронуты (архивная фаза — @PM); коммит/деплой
> (T-972/T-973) — финальный шаг раунда. **Финальный синк KG/графа, статусов милстоуна
> `round10.3-epic` и архивирование — шаг 10 @Memory.**
> **Синк STEP 10 (финал) 10.09.2026: раунд 10.3 ПОЛНОСТЬЮ ЗАВЕРШЁН** — HEAD ==
> origin/master == `1410a68` (коммит 09.09.2026 12:33 UTC, автор Henry), тесты
> **4831 passed / 0 failed**, @Reviewer APPROVED, Scanner 0 blocker/major
> (R10.3-1…R10.3-6 → ARCH §24); деплой 09.09.2026 (рестарт 12:37 UTC, active);
> прод-диагностика задачи 5 проведена (чат -1002661910336 без своего ключа,
> глобальный ключ 25/25 → sandbox R16, сброс бакета 00:00 Екб — детали в KG
> `recon: direct-chat-sandbox-budget`); F-13/F-14/F-15 заархивированы
> (plans/archive/ — **18 папок**, plans/features/ — снова 6 активных F-1…F-6);
> MEMORY.md ВПЕРВЫЕ вошёл в коммит; граф обновлён (милстоун `round10.3-epic` →
> COMPLETED+DEPLOYED, фичи → ARCHIVED_IN/WAS_PART_OF). Цикл раунда полностью закрыт.
> **Step 0 recon 10.09.2026 (раунд 10.4, 9 пунктов ТЗ реструктуризации TMA):**
> RESEARCH ONLY — дерево чистое (только plans/MEMORY.md modified, остаток шага 10),
> HEAD == origin/master == `1410a68`. Изучены структура миниаппа (TABS/MENU_ORDER/
> generic-рендер, web/app.js + web/index.html), каталог параметров (REGISTRY 383 /
> 71 групп / Settings 359, TAB_RULES param_catalog.py:1374-1406, паттерн добавления
> раздела), локализованы все 9 пунктов ТЗ по группам/ключам. Всё зафиксировано —
> KG-сущность **`recon: tma-structure-10.4`** (полные координаты, реестры ключей
> реакций/лимитов/памяти/провайдеров/отношений, тест-риски, конфликты с F-1…F-6).
> Планирование — @PM (конфликт-матрица не строилась).
> **Синк STEP 3 (планирование 10.4) 10.09.2026:** раунд 10.4 распланирован и
> **ЗААРХИТЕКТИРОВАН** — **8 фич** (plans/features/, spec.md @Architect + tasks.md
> @PM для каждой, стадия ARCHITECTED, Builder не начат): **D**
> `frontend-advanced-collapse-default` (T-1018…T-1023), **C**
> `frontend-memory-sleep-nostalgia` (T-1006…T-1017), **E**
> `frontend-llm-providers-layout` (T-1024…T-1032), **A**
> `frontend-reorg-modules-reactions` (T-974…T-989), **B**
> `frontend-limits-temperature-budgets` (T-990…T-1005), **F**
> `frontend-relations-participants` (T-1033…T-1044), **H**
> `backend-relations-nickname` (T-1057…T-1065), **G**
> `backend-chat-1002661910336-scaling` (T-1045…T-1056) — итого T-974…T-1065
> (92 задачи). Порядок исполнения: **D → C → E → A → B → F → H → G** (обоснование:
> D — аккордеоны первыми; C/E/A — реструктуризация вкладок после D; B — per-chat
> алиасы/виджет ДО F и H; H — фикс каскада после B; G — деплой-бэкфил последним).
> Ключевое: REGISTRY **383/71/359 ЗАМОРОЖЕН** по всем 8 фичам (MED-017 — только
> переносы/разметка/поля виджета select); SQLite v8, порядок роутеров bot.py,
> каноны промптов, known_sections() — без дифов; R16/R17 сохранены; **девиансия
> D-A1** (фича A: war/common/goodmorning/word_reactions ТАКЖЕ переезжают в
> «Функции PERMsoc» — канон спеки §2, шире tasks.md T-975); общий новый тест
> `test_progressive_tab_basic_coverage` (≥1 basic-группа на каждую config-вкладку;
> пишется в D, зелёный после C/E/A; MED-022-маркеры обновляются в каждой
> фронт-фиче). Конфликт-матрица с F-1…F-6 зарегистрирована в backlog.md:
> **F-1 ДО B/G** (атомарный POST, касты T-651/652, NaN T-654), **F-3 T-663 ПОСЛЕ
> раунда** (DM-перепроверка), **F-4 Баг-4 ПОСЛЕ раунда** (сверка по новой карте
> вкладок), **F-5 ПОСЛЕ G/B** (реестры новых read-путей), **F-6 SUPERSEDED_BY
> round10.4** (аудит каскада → H T-1058/1059/1063, live-эффект → B T-1005,
> верификация → владельцу). Граф обновлён (Step 3): AdminBot HAS_PLAN → 8 фич,
> милстоун `round10.4-epic` → ARCHITECTED (PLANNED_IN/ARCHITECTED_IN plans-structure),
> цепочка DEPENDS_ON D→C→E→A→B→F→H→G; наблюдения добавлены в param-catalog
> (TAB_RULES-реструктуризация), DirectChatService (бюджеты B + overrides G),
> chat-lore (каскад имён H + перенос F), plans/features/user-aliases-admin
> (SUPERSEDED_BY).
> **Merge Phase 10.4 (10.09.2026, @Architect)** — 8 фич раунда (D/C/E/A/B/F/H/G,
> T-974…T-1065) IMPLEMENTED в рабочем дереве (HEAD 1410a68 + 10.4: 24 модифицированных
> файла, 8 новых фич-папок, 2 backfill-скрипта `scripts/backfill_104_{chat_flags,overrides}.py`,
> 2 новых тест-файла), @Reviewer APPROVED, Scanner-аудит 10.4: **0 blocker/major**
> (minor/info R10.4-1…R10.4-7 → ARCHITECTURE.md §25; R10.4-1/-2/-3 закрыты
> follow-up @Builder и сверены), pytest **4860 passed / 0 failed** (4831 → +29),
> `node --check web/app.js` clean, `git diff --check` чист. ARCHITECTURE.md обновлён:
> **§24** (раунд 10.4: карта вкладок — PERMsoc 17 групп/Модули/Память+Сон+Ностальгия/
> секции LLM Провайдеров/Имена людей/Участники и отношения/Лор-расширенные; select-виджет
> (widget='select' + select_options/select_labels, 422); бюджет-флаг per-chat
> `chat_context_budgets_enabled` + backfill_104_chat_flags (-1002661910336 off);
> `build_alias_resolver(chat_id)` per-chat/ЛС алиасы; аккордеоны «Расширенные» свёрнуты
> по умолчанию (expandOpen+персист); каскад имён username-всем строкам (Semaphore 5,
> кэш 1ч, фото топ-50, R16); per-chat скейлинг -1002661910336 — 15 ключей ×1.5–×2,
> backfill_104_overrides, `_resolve_from_root` _cast_type_ok+isfinite, граница G-4,
> KPI 25 req → флаг бюджетов off) + **§25** «Известные ограничения и техдолг»
> (R10.4-1…R10.4-7 со статусами + обновлённые R10.3-*); кросс-указатели §3/§4/§9/§16
> (+ исправлен счётчик групп каталога **71→74** — ре-дизайн 10.2 BUG-3 +3 группы;
> сверка: GROUPS=74 на HEAD и в 10.4). Локальные спеки 8 фич НЕ тронуты (архивная
> фаза — @PM); коммит/деплой + прогон обоих бэкфилов (@DevOps) — финальный шаг раунда.
> **Финальный синк KG/графа, статусов милстоуна `round10.4-epic` и архивирование —
> шаг 10 @Memory.**
> **Синк STEP 10 (финал, post-commit+деплой) 10.09.2026: раунд 10.4 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `0bdf272` (feat(admin,web,chat,api):
> раунд 10.4 — реструктуризация админки (Модули/PERMsoc/Память/Сон/Ностальгия/
> Провайдеры/Отношения), бюджеты per-чат и температура-select, имена людей
> per-чат/ЛС, каскад имён, лимиты ×1.5-×2 для -1002661910336); тесты **4860 passed /
> 0 failed** (4831 → +29), @Reviewer APPROVED, Scanner 10.4 **0 blocker/major**
> (minor/info R10.4-1…R10.4-7 → ARCHITECTURE.md §25; R10.4-1/-2/-3 закрыты follow-up
> и сверены); деплой 10.09.2026 (198.46.175.136): git pull, **.env +=
> CHAT_THREAD_MAX_CHARS=2000**, **бэкфилы применены** — backfill_104_chat_flags.py
> (флаг бюджетов OFF для -1002661910336) + backfill_104_overrides.py
> (15 ключей ×1.5–×2), рестарт, bot active; ARCHITECTURE.md §24 (карта вкладок/
> бюджеты/каскад имён) + §25 (техдолг R10.4-*, B-13 points 2-4, HIGH-004-остаток);
> 8 фич заархивированы (@PM) — plans/archive/ **26 папок**, plans/features/ снова
> 6 активных F-1…F-6; README тесты 4860; граф обновлён (round10.4-epic →
> **COMPLETED+DEPLOYED**, 8 фич → ARCHIVED_IN/WAS_PART_OF, HAS_PLAN/PLANNED_IN/
> ARCHITECTED_IN удалены, создан `tech-debt-round10.4`). Цикл раунда полностью закрыт.
> **Синк STEP 3 (планирование 10.5) 10.09.2026:** раунд 10.5 «Редизайн TMA по
> референсу Relume + гигиена репозитория» распланирован и **ЗААРХИТЕКТИРОВАН** —
> фича **`tma-relume-redesign`** (`plans/features/tma-relume-redesign/`):
> `tasks.md` @PM (T-1066…T-1089, продолжает T-1065), `reference-analysis.md` @PM
> (recon-разбор референса, стадия ANALYSIS), `spec.md` @Architect (686 строк,
> §0–§11). Референс `relumesite_example/` — статический Relume-экспорт (15 страниц,
> 0 input/form/table) ⇒ редизайн визуальный + IA, не функциональный порт; ~90%
> функциональности уже есть (18 вкладок в 5 секциях MENU_ORDER). T-1066 (гигиена)
> **ВЫПОЛНЕНО** — `.gitignore += relumesite_example/` (отдельный раздел),
> `media/` НЕ тронут (политика project.md). ⏸ Решения **D1–D8** требуют владельца
> (рекомендации @Architect: C hybrid / поэтапно / остаться на Vue3 global / палитра
> P3 teal `#14CBB6` на dark `#161616` / emoji now + Material Symbols follow-up /
> Чат-Профиль на усмотрение / B1-B2 отложить / hash-роутинг при C); секция E
> (реализация) заблокирована до апрува D1 (T-1076). Конфликт-матрица с F-1…F-6:
> **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ редизайна 10.5**, F-1/F-2/F-3/F-5
> независимы, F-6 SUPERSEDED_BY round10.4. Граф обновлён (Step 3): entity
> `tma-relume-redesign` обогащена (+5 наблюдений: артефакты, инварианты/фазы/AC,
> `.gitignore`-гигиена, D1–D8, конфликт-матрица; дублей нет — добавлено в
> существующую сущность @Architect), создано 7 связей: `AdminBot HAS_PLAN
> tma-relume-redesign`, `CONFLICTS_WITH plans/features/frontend-admin-bugfixes`,
> `RELATED_TO` ×5 (post-deploy-admin-minors, admin-debug-webview,
> scam-incident-security-followup, config-read-path-audit, user-aliases-admin).
> Следующий шаг — решение владельца D1–D8 → @Builder секция E.
> **Синк STEP 3 (design-project) 10.09.2026 (вечер):** главный deliverable раунда
> 10.5 ГОТОВ и находится на **GATE** — `plans/features/tma-relume-redesign/design-project.md`
> (835 строк, RU, §0–§14; статус 🟡 DESIGN/GATE). `spec.md` → **v2** (согласован с
> решениями владельца **OD1–OD6**, которые отменяют/заменяют рекомендации spec v1 и
> прежние D1–D8); `tasks.md` секция **E (T-1090…T-1097) ✅ ВЫПОЛНЕНО**; секции
> **F/G (T-1098…T-1118) ⛔ заблокированы до явного апрува владельцем**. **OD1–OD6
> (LOCKED):** OD1 навигация = **вариант B, ПОЛНЫЙ ребейлд** по модели эталона
> (navbar 6 пунктов + hub-карточки + отдельные экраны); OD2 **big-bang всё сразу**
> (внутренний порядок токены→shell/navbar→hubs→15 экранов→QA); OD3 **та же
> технология** (Vue3 global / zero-build, единый `index.html`+`app.js`); OD4 палитра
> эталона как база + **АНИМИРОВАННЫЕ плавные градиенты** (reduced-motion + WCAG AA);
> OD5 **Material Symbols Rounded** primary + карта emoji-fallback; OD6 **структура
> эталона = ЭТАЛОН** композиции (15 страниц). **КРИТИЧНО:** hash-роутинг обязателен
> (следствие OD1+OD3); Telegram кладёт `initData` в `window.location.hash`
> (`#tgWebAppData=...`) — читать/кэшировать **ДО** первой записи `location.hash`,
> парсить только роуты с префиксом `#/`, **vue-router НЕ использовать** (ломает
> кодирование `tgWebAppData`, vuejs/router#2155). **Верифицированная коррекция:**
> в приложении **17 вкладок** `TABS` (`web/app.js:18-145`), а НЕ 18 (off-by-one в
> `tasks.md`/`spec.md`); паритет — «0 бездомных» из 17. **Предложения (§10):**
> **ADD A1–A10** (initData-guard, Telegram BackButton+deep-link, единые
> empty/error/retry, hub-карточки+drill-down, self-host subset Material Symbols,
> prefers-contrast:more, тема-переключатель 4 схемы, quick-search, скелетоны
> relations, breadcrumb); **REMOVE R1–R7** (sidebar как primary nav, хардкод
> `#8b5cf6/#3b82f6/#2b2b40`+Tailwind-токены, дубль локальных админов в `chat_lore`,
> emoji как основные иконки, отдельная navbar-секция «Чат-Профиль», Tailwind CDN
> runtime, 409 no-op reload); **OPTIMIZE O1–O7** (`@property inherits:false` → до
> 848% быстрее recalc, ограничение площади анимации + `contain:paint`, ленивые
> аватары R10.4-4, кэш params-meta/chats, namespace-модульность без разбиения файла,
> DM models read-only, единый fetch-слой); **NOT DO N1–N5** (bundler/vue-router,
> backend B1/B2, текст на движущемся градиенте, анимация за таблицами/формами/логами,
> изменения param_catalog/settings/SQLite v8/PG-DDL/порядок `bot.py`). Открыты
> **D6** (реком. свернуть «Чат-Профиль» в AI-hub), **D7** (реком. отложить B1/B2,
> B3 опц.), **D8** (реком. включить BackButton/deep-link). Exa-research успешен
> (6 тем: docs.telegram-mini-apps.com, core.telegram.org, W3C WCAG 2.3.3, web.dev
> @property, MDN, Google Fonts Material Symbols, admin IA). Граф обновлён:
> `tma-relume-redesign` +4 наблюдения (deliverable/status+GATE, OD1–OD6, proposals
> A/R/O/N, gotcha initData/17-vs-18); relation `HAS_DESIGN_PROJECT →
> tma-relume-redesign-design-project`; дублей нет (Voxy-сущности не затронуты,
> ничего не удалено). **Следующий шаг — владелец: D6/D7/D8 + GO → @Builder T-1098.**
> **Синк STEP 3 (догон, T-1119/T-1120) 10.09.2026 (вечер, @Memory):** доуточнения
> проекта по обратной связи владельца **ВЫПОЛНЕНЫ** — `tasks.md` секция **E2**:
> **T-1119 ✅** (Exa-research back-навигации) и **T-1120 ✅** (plain-language
> разъяснения D6 + B1/B2/B3); `design-project.md` (1105 строк) обновлён: **§0 TL;DR**
> (+п.9 «back без своей кнопки»), **§6.4 переписан** (нативный `Telegram.WebApp.BackButton`:
> `show()` на глубине >0 заменяет ✕ на ←, `hide()` на корне возвращает ✕ — один header-слот,
> конфликта нет; мы владеем history/stack, Telegram — header+OS-back; Android hardware-back
> эмитит `back_button_pressed` только при `is_visible=true`, иначе закрывает WebView;
> `onClick` регистрируется ОДИН раз → `goBack()` = детерминированный parent-route, НЕ
> `history.back()`, без popstate; единственный applier = `hashchange`; Bot API 6.1+),
> **§11** (+ **§11.1 D6**, + **§11.2 D7**), **§12** (Exa расширен **6→7 тем** + источники
> **§12.7**), **§13** (AC-5 routing переформулирован под нативный BackButton, AC-9 —
> Scanner re-check), **§14 GATE**. Новый маркер-тест `test_webapp_back_button` (§9.4).
> Тумблеры: `__TMA_BACK__=true` (решено), `__TMA_DEEPLINK__` (ждёт владельца, default false).
> **Статусы решений:** **D8 — RESOLVED-in-intent** (back-навигация подтверждена владельцем,
> паттерн определён); **D6/D7 — OPEN** (ждут решения владельца; рекомендации: свернуть
> «Чат-Профиль» в «Настройки AI» — 6 navbar-пунктов как в эталоне; B1/B2 отложить, B3
> опционально). **GATE остаётся ЗАКРЫТ** — 0 кода, реализация (F/G) не стартует до явного
> GO владельца + решения deep-link. Репо: HEAD `0bdf272`, worktree dirty (`.gitignore`,
> `plans/MEMORY.md`, `plans/backlog.md` modified; `plans/features/tma-relume-redesign/`
> untracked). Граф: обновлены `tma-relume-redesign`, `tma-relume-redesign-design-project`,
> `TMA BackButton navigation pattern`, `D6 D7 plain-language clarifications` (только
> добавление наблюдений; дублей нет; Voxy-сущности не затронуты).
> **Синк STEP 3 (v3, секция E3 — OD7–OD10) 10.09.2026 (поздний вечер, @Memory):** главный
> deliverable раунда 10.5 обновлён до **v3** — `design-project.md` **1105 → 1817 строк**,
> добавлен **§15** (15.1 scope-switcher/OD7, 15.2 key-availability/OD8, 15.3
> role-matrix/OD10, 15.4 font-delivery/D11, 15.5 deep-link/D9, 15.6 Q-NEW-1..5, 15.7
> трассировка E3); обновлены §0/§2/§3/§5/§7/§10/§11/§12/§13/§14. `tasks.md`
> **T-1121…T-1126 ✅ done (E3)**; `spec.md` согласован (v3-указатель, v2 частично
> SUPERSEDED). **OD7–OD10:** OD7 «Чат-Профиль» = глобальный scope-switcher GLOBAL/ЧАТ/ЛС
> (не 7-й nav-пункт); OD8 B1 key-availability В СКОУПЕ (in-memory ring, без PG-DDL/
> SQLite v8); OD9 B2 custom-modules CRUD OUT (read-only); OD10 B3 role-matrix В СКОУПЕ и
> расширена (per-param read/write + role CRUD). **Q-NEW-1..5** (каталог 383→385?;
> key-history in-memory vs persisted; deep-link; файл шрифта; delete/rename ролей?) и
> **D9/D11** открыты владельцу; font-delivery spec готова (§15.4: self-host woff2 subset
> `web/static/fonts/`, `@font-face`, CSP `font-src 'self'`, ~2–15 КБ, emoji-fallback).
> **GATE ЗАКРЫТ: 0 кода**, T-1127+ (F4) и F/G не стартуют без GO владельца. Граф обновлён:
> добавлены наблюдения в `tma-relume-redesign` (+5), `tma-relume-redesign-design-project`
> (+1), `tma-relume-redesign v3 design-project` (+7: §15-карта, Q-NEW, трассировка, gate);
> связи — `v3 SUPERSEDES design-project`, `tma-relume-redesign HAS_DESIGN_PROJECT v3`,
> `OD7-OD10 owner decisions DECIDES tma-relume-redesign`. Дублей нет; Voxy-сущности не
> затронуты; удалений нет.
> **Синк STEP 3 (v4, секция E4 — OD11–OD15, T-1136…T-1138) 10.09.2026 (@Memory):**
> главный deliverable раунда 10.5 ревизован **v3 → v4** — `design-project.md`
> **1817 → 2119 строк**, добавлен **§16** (16.1 hardcode-аудит H1–H22; 16.2 замеры
> шрифта; 16.3 персистентность истории; 16.4 роли; 16.5 **Q1–Q4**; 16.6 Scanner);
> обновлены шапка/§0 (пп.12–17)/§5.2/§6.4.5/§10.4 N5/§11/§13 (**AC-14…AC-18**)/
> §14/§15.2/§15.3/§15.4/§15.5/§15.8. `tasks.md` секция **E4 (T-1136/T-1137/T-1138)
> ✅ ВЫПОЛНЕНО**; **T-1139…T-1142 (F5, реализация OD11–OD15) ⛔ заблокированы до GATE**.
> `spec.md` согласован (v4). **0 кода.** **Итоги:** (OD11) исчерпывающий аудит —
> **9 активных P0-хардкодов / 4 уникальных значения** (Groq/OpenRouter base_url +
> STT-модели whisper-large-v3 / openrouter/free) в `services/status_service.py`,
> `SmartModule/transcriber/{groq,openrouter}_transcriber.py`, `services/video_cascade_client.py`;
> миграция **аддитивная** `hot.get(key, literal)` (дефолт = текущая константа ⇒ вывод
> идентичен, существующие значения не меняются); санкционированное исключение
> **param_catalog +2 PG-only записи STT → REGISTRY 385 / GROUPS 74 / Settings 359**
> (было 383/74/359), сид `code_source` + `ON CONFLICT DO NOTHING`; P1 — дефолт-фолбэки
> (не трогать), P2 — фикс-endpoint'ы, T — tooling. (OD12) история доступности ключей
> **персистится**: in-memory ring + **атомарный JSON-снимок `var/status_key_history.json`**
> (gitignored, 288 точек/провайдер, R17-safe) — **0 PG-DDL, SQLite остаётся v8** ⇒
> **исключение у владельца НЕ требуется**. (OD13) **deep-link OFF** — D9 CLOSED,
> `__TMA_DEEPLINK__=false`, задач реализации нет. (OD14) шрифт
> `MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2` **инспектирован T-1137**:
> валидный WOFF2, Material Symbols Rounded v2.967, 6607 глифов / 4277 лигатур,
> оси `FILL 0..1 / GRAD -50..200 / opsz 20..48 / wght 100..700`, **26/26 иконок**,
> Apache-2.0, но **5.36 МБ (5.11 МиБ) = не shippable** ⇒ обязателен субсет
> (`pyftsubset`): all-axes 36.3 КБ, **FILL-only 5.5 КБ**, **FILL+wght 13.2 КБ
> (рекомендован)**, static 3.7 КБ; **КРИТИЧНО:** `--unicodes-file` **теряет лигатуры**
> (`rlig/rclt→0`) ⇒ иконки рендерятся **PUA-кодпоинтом** (`&#xE850;`), а не текстом-именем;
> `--text` сохраняет лигатуры, но 4.03 МиБ (отвергнут); источник 5.11 МиБ **не
> коммитить** (`.gitignore`), коммитим субсет ~13.2 КБ + Apache-2.0 LICENSE; build-time
> зависимости `fonttools`+`brotli` (не рантайм). (OD15) **rename/delete ролей разрешены,
> КРОМЕ superuser** (жёсткая защита 403/409 + UI disabled; встроенные/занятые — нельзя).
> Открыты владельцу только **4 не-блокирующих выбора Q1–Q4** (base-url UI +2 записи
> → 387?; `fonttools`+`brotli` как build-dep?; 5.11 МиБ источник вне git?; файл
> `var/status_key_history.json`?). **GATE по-прежнему ЗАКРЫТ: 0 кода**, старт
> реализации (F/F4/F5/G) — только после общего GO владельца на v4. Граф обновлён:
> создана сущность **`tma-relume-redesign v4 design-project`** (+11 наблюдений) и
> **`OD11-OD15 owner decisions`** (+7); добавлены наблюдения в `tma-relume-redesign`
> (+2) и `tma-relume-redesign v3 design-project` (+1, SUPERSEDED); связи —
> `v4 SUPERSEDES v3`, `tma-relume-redesign HAS_DESIGN_PROJECT v4`,
> `v4 implements OD11-OD15`, `OD11-OD15 DECIDES tma-relume-redesign`.
> Дублей нет; Voxy-сущности не затронуты; удалений нет.
> **Синк STEP 3 (v5, секция E5 — OD16–OD19, T-1144) 10.09.2026 (@Memory):**
> главный deliverable раунда 10.5 ревизован **v4 → v5** — `design-project.md`
> **2119 → 2312 строк**, добавлена трассировка **§16.7 (E5)**; обновлены
> шапка/§0/§3/§9/§10/§11/§13/**AC-19/AC-20**/§14/§15.2/§15.3/§15.4/§16.1–§16.7.
> `tasks.md` секция **E5 (T-1144) ✅ ВЫПОЛНЕНО** (pre-gate, 0 кода, landing notes);
> **T-1145…T-1148 (F6, реализация OD16–OD19) ⛔ заблокированы до GATE**.
> `spec.md` согласован (v5). **Итоги:** **(OD16)** адреса провайдеров
> (`base_url` Groq/OpenRouter) **ОБЯЗАТЕЛЬНЫ в UI** — провайдер, модель и адрес
> редактируемы из мини-аппа, владелец **переключает провайдера И модель**; отменяет
> прежнее «base_url hot-only» (§15.2.2/§16.5 Q1); **+2 PG-only записи каталога**
> `models.groq_base_url` = `https://api.groq.com/openai/v1`,
> `models.openrouter_base_url` = `https://openrouter.ai/api/v1` ⟹ каталог-финал
> **REGISTRY 387 / GROUPS 74 / Settings 359** (383 → +2 STT OD11 → 385 → +2 адреса
> OD16 → **387**; миграция аддитивная, значения не меняются, `GET /api/status.llm[]`
> байт-идентичен, R17 — адрес НЕ секрет). **(OD17)** `fonttools`+`brotli` —
> **build-time only** (в runtime `requirements.txt` не входят). **(OD18)** тяжёлый
> источник шрифта **5.11 МиБ** → **`.gitignore`** (в git только субсет ~13.2 КБ +
> `LICENSE` Apache-2.0; на 10.09.2026 файл **untracked и ещё НЕ ignored** ⟹ T-1147
> добавит паттерн). **(OD19)** `var/status_key_history.json` **утверждён** с
> **обязательной leak-safety-верификацией**: allowlist-схема (module id, provider,
> model, key-configured bool, HTTP-код, timestamp, version, generated_at); запрет
> сырых ключей/токенов/`Authorization`/`Bearer`/`sk-`/`gsk_`/cookies/`initData`/
> credentials-in-`base_url`/тел LLM; права 0600 (каталог 0700); gitignored; **не
> отдаётся `GET /api/config`** и **не пишется в логи/`log_ring`/BetterStack**;
> атомарная запись (tmp + `os.replace`); corrupt/missing → пустая история + WARNING
> (fail-open). AC: grep-маркер (нет паттернов ключей) + unit-сериализатор +
> проверка прав + `git check-ignore` + выживание рестарта; **R17 доказан**.
> Scanner E5: `plans/reports/` — новых отчётов по 10.5 нет (последний — Round 10.4,
> 0 blocker/0 major); учтены MED-017/MED-021/LOW-012/R10.4-2/-4/-5, MED-003
> подтверждает OD16. **ВСЕ решения закрыты (D6–D12 = OD7–OD15; Q1–Q4 = OD16–OD19)** —
> открытых вопросов/выборов НЕ осталось. **GATE по-прежнему ЗАКРЫТ: 0 кода**;
> реализация (F/F5/F6/G, T-1098…T-1148) стартует только после **явного общего GO
> владельца на v5**. Граф обновлён: созданы сущности
> **`tma-relume-redesign v5 design-project`** (+10 наблюдений) и
> **`OD16-OD19 owner decisions`** (+6); добавлены наблюдения в `tma-relume-redesign`
> (+1) и `tma-relume-redesign v4 design-project` (+1, SUPERSEDED); связи —
> `v5 SUPERSEDES v4`, `tma-relume-redesign HAS_DESIGN_PROJECT v5`,
> `v5 implements OD16-OD19`, `OD16-OD19 DECIDES tma-relume-redesign`.
> Цепочка SUPERSEDES: **v5 → v4 → v3**. Дублей нет; Voxy-сущности не затронуты;
> удалений нет.
> **Синк STEP 10 (финал, post-commit+деплой) 10.09.2026: раунд 10.5 ПОЛНОСТЬЮ
> ЗАВЕРШЁН — HEAD == origin/master == `c01ed72`** (`918f675` — фича, 49 файлов;
> `c01ed72` — docs деплой-верификация; поверх `0bdf272`). Единственная фича
> `tma-relume-redesign` (T-1066…T-1148) реализована целиком (Builder Pass 1–6:
> токены/градиенты, hash-router + нативный BackButton, scope-switcher GLOBAL/ЧАТ/ЛС,
> hubs + 15 экранов, key-availability + persisted chart, матрица ролей + role CRUD
> кроме superuser, hardcode H1–H22 → безопасная аддитивная миграция, каталог
> 387/74/359, font-subset ~13.2 КБ + self-host DOMPurify 3.4.15 fail-closed).
> @Reviewer: REJECTED → fixes D1–D4 → APPROVED WITH MINOR → R1–R4 закрыты.
> @Scanner: **CLEAN — 0 blocker / 0 major**; R10.5-1/-2/-4 закрыты, R10.5-3/-5/-6/-7
> — техдолг (ARCH §25); отчёт `plans/reports/round10.5_scanner_audit.md`.
> @Architect: merge в `plans/ARCHITECTURE.md` (§9 обновлён, §25 «по состоянию на 10.5»
> + блок R10.5, новый **§26 «Раунд 10.5»** — последняя секция). **Тесты: 4962 passed /
> 0 failed** (baseline 10.4 = 4860, +102); `node --check web/app.js` clean;
> `git diff --check` чист. @PM: фича заархивирована — `plans/archive/tma-relume-redesign/`
> (**plans/archive/ — 27 папок**, plans/features/ — снова 6 активных F-1…F-6), backlog
> epic 10.5 закрыт. @DevOps: README обновлён (ироничный тон); push origin/master;
> **деплой 198.46.175.136:/var/www/admin_bot** — git pull fast-forward, `.env` без
> изменений, `systemctl restart admin_bot` → active (running), `/api/health` = 200,
> **0 startup-ошибок**. Граф обновлён: милстоун `round10.5-epic` → COMPLETED + DEPLOYED,
> фича → WAS_PART_OF + ARCHIVED_IN plans-structure + COMPLETED_IN/DEPLOYED_IN, создан
> `tech-debt-round10.5` (R10.5-3/5/6/7). **Осталось вручную:** live Telegram
> smoke-тест (T-1153), опциональный betterstack-401 fix, вердикт владельца.

## Активные фичи (plans/features/)

| Фича | Скоуп |
|---|---|
| `admin-debug-webview` (F-2) | `/debug_config` в HTML WebView поверх HTTPS |
| `scam-incident-security-followup` (F-3) | Секьюрити-фоллоу-ап после скам-инцидента 30.08 |
| `frontend-admin-bugfixes` (F-4) | Багфиксы админ-минги и `<Красивые ссылки>` |
| `config-read-path-audit` (F-5) | Аудит read-путей: settings.X vs hot.get |
| `user-aliases-admin` (F-6) | Алиасы юзеров в разделе «Лор чатов» (частично в master; SUPERSEDED_BY round10.4) |
| `post-deploy-admin-minors` (F-1) | Пост-деплойные миноры Epic 85 (T-648:T-655) |

> **Свежие завершённые раунды (архив):** **10.25 (Эпик 1, в работе — Волна 1 закрыта)** — **F0** `f0-config-bugfixes-round1025`
> (`plans/archive/f0-config-bugfixes-round1025/`, деплой `3a91c84`, pytest 7946/0, §52) +
> **ASAP-хотфикс** `hotfix-media-tma-round1025` (`plans/archive/hotfix-media-tma-round1025/`,
> commits `8b16c4a`+`ee23e47`+docs `65e39fb`, pytest 7976/0, §53; ⏳ live-гейт владельца T-2463/T-2472/T-2479) +
> **F1** `ia-shell-navigation-round1025` (`plans/archive/ia-shell-navigation-round1025/`, `adr-1025-1-ia-v2.md`,
> деплой `fe0f7bb`, pytest 7996/0, §54; kill-switch `IA_V2_ENABLED`) +
> **P0-фикс** `p0-fix-render-media-paths-round1025` (`plans/archive/p0-fix-render-media-paths-round1025/`, FIX 1–4,
> деплой `fea2daa`, pytest 8003/0, §54.1) +
> **Волна 1 (пакет, деплой `4cde1bc`, `APP_VERSION` 2.58.6, §57):** **F2** `design-tokens-liquidglass-v2-round1025`
> (`plans/archive/design-tokens-liquidglass-v2-round1025/`, `adr-1025-9`, pytest 8096/0 → полный пакет 8146/5/1) +
> **hotfix5** `summary-cover-window-round1025` (`plans/archive/hotfix5-…/`, ретро `adr-1025-11`, pytest 8124/0) +
> **F3** `global-scope-selector-round1025` (`plans/archive/global-scope-selector-round1025/`, ретро `adr-1025-10`,
> локально 8142/5/1); ⏳ live-гейты владельца F2 **T-2561** / F3 / hotfix5;
> **10.24** «Disaster Recovery: UI & Backend Bloat» —
> **24 папки** `plans/archive/*-round1024/` (+3 сквозных дока), деплой **`da561bc`**,
> pytest 7911/0 (§51); **10.23** «Adaptive System 2 …» — **9 папок**
> `plans/archive/*-round1023/` (+`round1023-architecture.md`), деплой **`4314ea4`**,
> pytest 7424/0 (§49). `plans/features/` — **14 папок**: 6 backlog (сверху) + 8 фич раунда 10.25 (в т.ч. `epic1-verification-round1025`); следующий шаг — **F4 `module-catalog-quickpanel-store-round1025`**.
> Также закрыты: **hotfix3** `hotfix3-summary-stt-anticliche-round1025` (§55, `APP_VERSION` 2.58.3,
> pytest 8041/0) и **hotfix4** `hotfix4-cover-nav-shell-round1025` (`adr-1025-8-…`, §56, `APP_VERSION` 2.58.4,
> pytest 8071/0, JS 23/23); у обоих ⏳ live-гейт владельца (T-2505 / T-2527).

> **✅ ВОЛНА 1 ЗАКРЫТА (Step 10 @Memory, 22.09.2026): F2 `design-tokens-liquidglass-v2-round1025` + hotfix5
> `summary-cover-window-round1025` + F3 `global-scope-selector-round1025` — COMPLETED + MERGED + ARCHIVED + DEPLOYED
> (пакет, коммит `4cde1bc`, `APP_VERSION` 2.58.6, Merge `plans/ARCHITECTURE.md` §57).** Архивы —
> `plans/archive/design-tokens-liquidglass-v2-round1025/` (F2, `spec.md` + **ADR-1025-9** + `tasks.md`),
> `plans/archive/hotfix5-summary-cover-window-round1025/` (hotfix5, ретро `spec.md` + **ADR-1025-11** + `tasks.md`),
> `plans/archive/global-scope-selector-round1025/` (F3, ретро `spec.md` + **ADR-1025-10** + `tasks.md`).
> Аудит — `plans/reports/round1025_package_scanner_audit.md` (**C0/H0**) + базовые `round1025_f2/hotfix5/f3_scanner_audit.md`.
> KG: `F2-design-tokens-liquidglass-v2-round1025`, `F3-global-scope-selector-round1025`,
> `HOTFIX hotfix5-summary-cover-window-round1025`, `ADR-1025-9`/`-10`/`-11`, `round1025-package-scanner-audit`,
> `release-round1025-wave1`, `metric-snapshot-round1025-f2`/`-hotfix5`/`-f3`, `tech-debt-round10.25-f2`/`-f3`/`-hotfix5`.
> **⏳ live-гейты владельца (F2 T-2561, F3, hotfix5) — открыты.**
> **Следующая — F4 `module-catalog-quickpanel-store-round1025`** (Волна 2, зависит от F2/F3) → F5–F11 → приёмка Эпика 1 (F10).

> **📌 Step 0 @Memory (22.09.2026): открыт внеплановый пакет по итогам ЖИВОЙ ПРИЁМКИ владельца после Волны 1 —
> KG `HOTFIX6-webview-shell-heartbeat-round1025` (RECON; код не менялся).** Baseline: HEAD **`441e8f7`** (== origin/master,
> worktree чистый), **`APP_VERSION` 2.58.6**, база pytest **8146/5/1** (5 — env aiogram, вне диффа), SQLite `v12`,
> Δ каталога = 0. **Блоки:** **A** Liquid Glass фактически без преломления (уровень A `feDisplacementMap`, вероятно не
> работает в реальном WebView; корень — опора на `backdrop-filter: url()` + UA-gate Blink-only + A opt-in лишь на 3 узлах
> + карта-приближение) + стекло на **sidebar/header** (сейчас `--surface-1` / `--glass-bg-strong` без blur);
> **B** `.bottom-nav` уползает за край на мобильном (недодел hotfix4/ADR-1025-8 D2; гипотеза — не учтён
> `contentSafeAreaInset.bottom`); **C** heartbeats overflow на мобильном + переделать в реальный Canvas 2D + rAF по §15
> (телеметрия отдельно, polling 10–30 с, HEALTHY/WARNING/CRITICAL/UNKNOWN, гистерезис, тултип, reduced-motion);
> **D** кнопка ⛶ ниже нативных кнопок TG + header-перекомпоновка (селектор/бейдж/аватар/роль — отдельной строкой;
> нативные кнопки CSS не двигать; D5 — фуллскрин должен работать).
> **Пересечение:** **F11 `status-showcase-dashboard-round1025`** (§11–§21) — блок **§15 исключить из F11** (SUPERSEDE/AMEND);
> KG-узел F11 создан (ранее отсутствовал). **AMEND задеплоенного:** F2/ADR-1025-9, F3/ADR-1025-10, hotfix4/ADR-1025-8, F1.
> **Приёмка:** Playwright-матрица §71 + ОТДЕЛЬНО реальный Telegram WebView. KG: `status-showcase-dashboard-round1025`,
> `SpecDecision-owner-acceptance-directive-round1025-hotfix6`, `ArchitecturalConstraint-{liquidglass-a-…,heartbeat-canvas2d-…,native-controls-…}`,
> `Risk-hotfix6-{liquidglass-a-no-render,bottomnav-viewport-regress,heartbeat-overflow-mobile,header-native-controls-collision}`,
> `ExternalDependency-telegram-webview-backdrop-filter`, `tech-debt-round10.25-hotfix6`, `metric-snapshot-round1025-hotfix6-step0`.
> **Статус на 22.09.2026:** ✅ пройдены Step 1–8 (декомпозиция @PM, `spec.md` + ADR-1025-12 @Architect, реализация A–D @Builder, ревью @Reviewer **Approved**, аудит @Scanner **C0/H0**, Merge @Architect §58, архивация — Шаг 8 @PM; см. блок «✅ ХОТФИКС-6» выше). **✅ deploy — Шаг 9 @DevOps (T-2616) выполнен: коммиты `055525c`+`ba75751`, `APP_VERSION` **2.58.6 → 2.58.7**, health 200, `database is locked`=0, `deployment.md` VERIFIED; ⏳ live-гейт владельца T-2617 — открыт; далее F4.**

> **Раунд 10.14 — 8 фич ЗАВЕРШЁН, ЗАДЕПЛОЕН и ЗААРХИВИРОВАН (13.09.2026)** — F1
> `anti-echo-self-reply`, F2 `persona-storage-core`, F3 `persona-ui-tab`, F4
> `persona-traits-ribbon`, F5 `settings-persistence-audit`, F6 `help-guide-integration`,
> F7 `status-layout-reorder`, F8 `self-reflection-llm-provider` (72 задачи T-1477…T-1548,
> все COMPLETED+DEPLOYED). Спеки+ADR — в `plans/archive/*-round1014/` (8 папок);
> `plans/archive/` — **50 папок**; `plans/features/` — 6 активных (F-1…F-6). См. блок
> «Синк STEP 10 (финал) раунда 10.14» выше.

> **Раунд 10.13 — 8 фич ЗАВЕРШЁН и ЗААРХИВИРОВАН (13.09.2026)** — F1 4D-память,
> F2 belief decay+resurrection, F3 глубокий сон+роутер, F4 UI провайдеров,
> F5 дашборд Cognition+виджет, F6 EKG+фикс логов, F7 справка+README, F8 ирония/досье
> (60 задач T-1417…T-1476, все COMPLETED). Спеки — в
> `plans/archive/cognition-*-round1013/` (spec.md + tasks.md + ADR-1013-1/2/3);
> см. блок «Синк STEP 10 (финал) 13.09.2026» выше и «Свежие архивы» ниже.

> **Раунд 10.4 — 8 фич ЗАВЕРШЁН и ЗААРХИВИРОВАН (10.09.2026)** — см. раздел
> «Раунд 10.4 — финал» ниже; их спеки — в `plans/archive/`
> (frontend-advanced-collapse-default, frontend-memory-sleep-nostalgia,
> frontend-llm-providers-layout, frontend-reorg-modules-reactions,
> frontend-limits-temperature-budgets, frontend-relations-participants,
> backend-relations-nickname, backend-chat-1002661910336-scaling);
> конфликт-матрица backlog.md «Раунд 10.4»: F-1 PRECEDES B/G — учтён; F-3 T-663 +
> F-4 Баг-4 + F-5 — остаются ПОСЛЕ раунда (фичи активны); F-6 — SUPERSEDED_BY
> round10.4-epic (подтверждена; папка F-6 остаётся в plans/features/).

> **Раунд 10.5 — DESIGN-PROJECT v3 ГОТОВ, на GATE (10.09.2026, поздний вечер)** — активная
> фича `tma-relume-redesign` в `plans/features/`: решения владельца **OD1–OD6 LOCKED**
> (полный ребейлд по эталону / big-bang всё сразу / Vue3 global zero-build /
> анимированные градиенты + reduced-motion + WCAG AA / Material Symbols Rounded +
> emoji-fallback / структура эталона = эталон) + **OD7–OD10 LOCKED** (OD7 «Чат-Профиль» =
> глобальный scope-switcher GLOBAL/ЧАТ/ЛС, НЕ 7-й nav-пункт; OD8 B1 key-availability
> В СКОУПЕ (in-memory ring, без PG-DDL/SQLite v8); OD9 B2 custom-modules CRUD OUT;
> OD10 B3 role-matrix В СКОУПЕ и расширена). Главный deliverable —
> **`design-project.md` v3 (1817 строк, RU, §0–§15, статус 🟡 DESIGN/GATE)**; `spec.md`
> согласован (v3-указатель, v2 частично SUPERSEDED); `tasks.md` секция
> **E/E2/E3 (T-1090…T-1126) ✅ ВЫПОЛНЕНО**; **T-1127…T-1133 (F4) + F/G ⛔ заблокированы
> до явного апрува владельцем**. **§15 (E3):** 15.1 scope-switcher/OD7, 15.2
> key-availability/OD8, 15.3 role-matrix/OD10, 15.4 font-delivery/D11, 15.5 deep-link/D9,
> 15.6 **Q-NEW-1..5**, 15.7 трассировка. **Открыто владельцу:** Q-NEW-1 (+2 строки каталога
> 383→385?), Q-NEW-2 (key-history in-memory vs persisted), Q-NEW-3 (deep-link, реком. OFF),
> Q-NEW-4 (файл шрифта, emoji до поставки), Q-NEW-5 (delete/rename ролей?), **D9**
> (`__TMA_DEEPLINK__`=false), **D11** (шрифт поставляет владелец) + **GO на реализацию**.
> **RESOLVED:** D6/D7 → OD7–OD10; D8 — back через нативный `BackButton` (`__TMA_BACK__`=true).
> `.gitignore += relumesite_example/` (T-1066); `media/` НЕ тронут. **Коррекция:** 17 вкладок
> `TABS` (`web/app.js:18-145`), не 18. Конфликт-матрица: **F-4 frontend-admin-bugfixes
> (Баг-4) — ПОСЛЕ 10.5** (редизайн меняет карту вкладок); F-1/F-2/F-3/F-5
> независимы; F-6 SUPERSEDED_BY round10.4. Спека референса — `relumesite_example/`
> (gitignored). Детали — KG `tma-relume-redesign` + `tma-relume-redesign v3 design-project`.
> (Блок выше — исторический снимок v3; актуальный статус — ниже.)

> **Раунд 10.5 — DESIGN-PROJECT v4 ГОТОВ, на GATE (10.09.2026, E4/OD11–OD15)** — активная
> фича `tma-relume-redesign` в `plans/features/`: **OD1–OD10 LOCKED** (см. блок v3 выше)
> + **OD11–OD15 LOCKED** (ответы владельца на §15.6 Q-NEW-1..5): **OD11** — ноль
> захардкоженных моделей (аудит T-1136: 9 P0-хардкодов, аддитивная миграция без смены
> значений, `REGISTRY 385 / 74 / 359`); **OD12** — история ключей персистится
> (`var/status_key_history.json`, 0 PG-DDL, SQLite v8, исключение не нужно); **OD13** —
> deep-link **OFF** (`__TMA_DEEPLINK__=false`); **OD14** — шрифт инспектирован (валиден
> как источник; 5.11 МиБ не shippable → субсет ~13.2 КБ + рендер по PUA-коду); **OD15** —
> rename/delete ролей, **кроме superuser**. Главный deliverable —
> **`design-project.md` v4 (2119 строк, RU, §0–§16, статус 🟡 DESIGN/GATE)**; `spec.md`
> согласован (v4); `tasks.md` секции **E/E2/E3/E4 (T-1090…T-1138) ✅ ВЫПОЛНЕНО**;
> **T-1127+ и F/F4/F5/G (T-1098…T-1143) ⛔ заблокированы до явного GO владельца на v4**.
> **D6–D12 — все RESOLVED** (OD7–OD15). `.gitignore += relumesite_example/` (T-1066) +
> 5.11 МиБ источник шрифта (OD14); `media/` НЕ тронут. **Коррекция:** 17 вкладок `TABS`
> (`web/app.js:18-145`), не 18. Открыты только **4 не-блокирующих выбора Q1–Q4** (§16.5).
> Конфликт-матрица: **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ 10.5**; F-1/F-2/F-3/F-5
> независимы; F-6 SUPERSEDED_BY round10.4. Детали — KG `tma-relume-redesign` +
> `tma-relume-redesign v4 design-project` + `OD11-OD15 owner decisions`.
> (Блок выше — исторический снимок v4; актуальный статус — ниже.)

> **Раунд 10.5 — DESIGN-PROJECT v5 ГОТОВ, на GATE (10.09.2026, E5/OD16–OD19) — исторический снимок v5, см. финал ниже** —
> активная фича `tma-relume-redesign` в `plans/features/`: **OD1–OD15 LOCKED** (см. блоки v3/v4
> выше) + **OD16–OD19 LOCKED** (ответы владельца на §16.5 Q1–Q4): **OD16** — адреса
> провайдеров (`base_url`) **обязательны в UI**, провайдер/модель/адрес редактируемы из
> мини-аппа ⟹ каталог **REGISTRY 387 / GROUPS 74 / Settings 359** (383→385→387);
> **OD17** — `fonttools`+`brotli` **build-time only**; **OD18** — источник шрифта **5.11 МиБ**
> → **`.gitignore`** (в git субсет ~13.2 КБ + Apache-2.0 LICENSE); **OD19** —
> `var/status_key_history.json` утверждён при **обязательной leak-safety** (allowlist-схема,
> права 0600/0700, gitignored, не в `GET /api/config`/логах, атомарная запись, R17 доказан).
> Главный deliverable — **`design-project.md` v5 (2312 строк, RU, §0–§16.7, статус
> 🟡 DESIGN v5 / GATE)**; `spec.md` согласован (v5); `tasks.md` секции
> **E/E2/E3/E4/E5 (T-1090…T-1144) ✅ ВЫПОЛНЕНО**; **F/F4/F5/F6/G (T-1098…T-1148)
> ⛔ заблокированы до явного GO владельца на v5**. Новые **AC-19** (UI-редактируемость
> провайдера/модели/адреса) и **AC-20** (leak-safety файла истории). Коррекции: 17 вкладок
> `TABS` (`web/app.js:18-145`), не 18; `.gitignore += relumesite_example/` + источник шрифта;
> `media/` НЕ тронут. **ВСЕ решения закрыты (D6–D12 = OD7–OD15; Q1–Q4 = OD16–OD19)** — открытых
> вопросов нет. Конфликт-матрица: **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ 10.5**;
> F-1/F-2/F-3/F-5 независимы; F-6 SUPERSEDED_BY round10.4. Детали — KG `tma-relume-redesign`
> + `tma-relume-redesign v5 design-project` + `OD16-OD19 owner decisions`.

> **Раунд 10.5 — ФИНАЛ: ЗАВЕРШЁН, ЗАКОММИЧЕН И ЗАДЕПЛОЕН (10.09.2026, HEAD
> `c01ed72`) — АКТУАЛЬНО** — милстоун **`round10.5-epic`** (COMPLETED + DEPLOYED).
> Коммиты `918f675` (фича, 49 файлов) + `c01ed72` (docs memory-sync), push
> origin/master. Тесты **4962 passed / 0 failed**; `node --check web/app.js` clean;
> @Reviewer APPROVED; @Scanner CLEAN (0 blocker/0 major; R10.5-3/-5/-6/-7 → техдолг
> ARCH §25); ARCHITECTURE.md §9/§25/§26. Деплой: 198.46.175.136:/var/www/admin_bot —
> git pull fast-forward, `.env` без изменений, restart active (running),
> `/api/health`=200, 0 ошибок. Фича заархивирована — `plans/archive/tma-relume-redesign/`
> (**plans/archive/ — 27 папок**; features/ — 6 активных F-1…F-6); README обновлён;
> backlog epic 10.5 закрыт. **Осталось вручную:** live Telegram smoke-тест (T-1153),
> опц. betterstack-401 fix, вердикт владельца. Детали — KG `round10.5-epic` +
> `tma-relume-redesign` + `tech-debt-round10.5`. (Снимки v3/v4/v5 выше — историчны.)

> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.6 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `4055434` (`6f91e8b` — фича, 37 файлов;
> `4055434` — docs деплой-верификация; поверх `be7b85b` = задеплоенный 10.5).
> Единственная фича **`tma-ia-modules-rework`** (T-1155…T-1223) реализована
> целиком: sidebar удалён (только top navbar 6 пунктов, иконка + подпись),
> «Модули» = 11 `mod_*` с реальными тумблерами + модалка параметров,
> «Настройки AI» = 7 подразделов (RAG → «Память»), PERMsoc очищен (10 параметров →
> модули 5/6/7), Леха/Костик раздельно, LLM Провайдеры — 9 блоков по модулям +
> `POST /api/llm/test`, proxy/cookies → M6, diagnostics → M9, emoji→Material,
> эксклюзивный аккордеон «Доступы и роли». 5 master-флагов default ON
> (FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP) с реальными гейтами OFF→UNHANDLED.
> **Каталог 392 / 91 / 364 / mapped 89 / TAB_RULES 19**; ноль PG-DDL, SQLite v8,
> `bot.py` и `media/` не тронуты. @Reviewer: REJECTED → fixes → APPROVED WITH MINOR
> → миноры закрыты. @Scanner: **CLEAN — 0 blocker / 0 major** (R10.6-1/-3 закрыты;
> R10.6-2/-4/-5/-6 — техдолг; отчёт `plans/reports/round10.6_scanner_audit.md`).
> @Architect: merge в `plans/ARCHITECTURE.md` (§27 + §25/§9/§6/§2). **Тесты:
> 5027 passed / 0 failed** (baseline 10.5 = 4962; +65); `node --check web/app.js`
> clean; `tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
> @PM: фича заархивирована — `plans/archive/tma-ia-modules-rework/`
> (**plans/archive/ — 28 папок**; plans/features/ — 6 активных F-1…F-6). @DevOps:
> README обновлён (ироничный тон); push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward до `4055434`, `.env`
> без изменений, restart → `is-active=running`, `/api/health`=200, **0 tracebacks**.
> Граф обновлён: милстоун `round10.6-epic` → COMPLETED + DEPLOYED, фича →
> WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.6` (R10.6-2/-4/-5/-6). **Осталось вручную:** live Telegram
> smoke-тест (desktop/Android WebView), опциональный betterstack-401 fix.
> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.7 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `bb59476` (`7f3b790` — fix, 19 файлов;
> `bb59476` — docs деплой-верификация; поверх `2ccf558` — docs 10.6; прод до
> деплоя `4055434`).
> Единственная фича **`admin-ui-bugfixes-round107`** (spec @Architect T-1224)
> реализована целиком: 1a `scope*` → computed (фикс `function () { [native code] }`),
> 1b header safe-area padding, 1c компактный user block, 1d nav labels меньше/без
> per-letter wrap, 2a ellipsis таблицы ключей, 2b uptime gap-fill (непрерывная
> 5-мин сетка, `down` для пустых слотов, `last_heartbeat` = last up else None),
> 3a clipboard-ghost focusable (без visibility:hidden) + удалён, 3b фикс. ширины
> лог-колонок + flex последней, 3c copy-on-row-click с feedback, R106-5 dead ICONS
> удалены (26→20). @Reviewer: REJECTED (visibility:hidden сломал execCommand-фолбэк)
> → fix → APPROVED WITH MINOR ISSUES → doc nit закрыт. @Scanner: **CLEAN — 0 blocker /
> 0 major** (R10.7-1 (minor) + R10.7-2..5 (info/nit) — техдолг; R10.6-5 ЗАКРЫТ; отчёт
> `plans/reports/round10.7_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§28 «Раунд 10.7»** (+§9/§25). **Тесты: 5042 passed /
> 0 failed** (baseline 10.6 = 5027; +15); каталог 392/91/364. @PM: фича
> заархивирована — `plans/archive/admin-ui-bugfixes-round107/`
> (**plans/archive/ — 29 папок**; plans/features/ — 6 активных F-1…F-6). @DevOps:
> README обновлён (ироничный тон); push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward до `7f3b790`, `.env`
> без изменений, restart → active, `/api/health` = 200, **0 errors**. Граф обновлён:
> милстоун `round10.7-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.7` (R10.7-1…R10.7-5). **Осталось вручную:** live Telegram
> smoke-тест исправленного UI, опциональный betterstack-401 fix.
> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.8 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `976e335`** (`31d2ce7` — фича,
> 30 файлов, тесты 5076; `976e335` — docs деплой-верификация; поверх `636a75d` —
> docs-финал 10.7; прод до деплоя `7f3b790` = задеплоенный 10.7).
> Единственная фича **`admin-ui-round108`** (spec @Architect + tasks @PM; T-1243…)
> реализована целиком: (1) переименование разделов — «Доступы»/«PERMsoc»/«ИИ»/
> «Справка»/«Сводка» (route-ключи `#/how|ai|permsoc|access|oversight` не менялись);
> (2) emoji→Material-иконки, субсет шрифта **20→37** (13 428→**18 388 B**),
> идемпотентность build-script по `sha256(source_sha+ICON_NAMES)`,
> `build/icon_codepoints.json`, R10.7-4 cmap-тест; (3) фикс логов на Android —
> Material-шеврон только при `exc_text` (без невидимого глифа), дата
> **DD.MM HH:MM:SS**, блочная раскладка (без `<pre><span>`, без жёстких ширин),
> `.log-msg` full-width, R10.7-3 closed; (4) «Доступы» — подразделы отдельными
> **route-driven модалками** (`#/access/roles|local|admins`), «Администраторы»→
> «Роли», аккордеон удалён, «Мой доступ»/«Telegram ID админа» вне окон,
> BackButton/deep-link/Esc; (5) удалён внешний GLOBAL-бейдж; README переструктурирован
> (users-first, гайд «Управление и деплой», changelog под `<details>`), счётчик 5076;
> `APP_VERSION` 2.51.0→**2.52.0**, шрифт cache-busted `?v=__APP_VERSION__`.
> @Reviewer: APPROVED WITH MINOR ISSUES (doc-nit исправлен). @Scanner: **0 blocker /
> 0 major** (R10.8-1 Esc и R10.8-5 APP_VERSION/кэш субсета закрыты follow-up;
> R10.8-2/-3/-4 — info/техдолг; **R10.7-3 и R10.7-4 ЗАКРЫТЫ**; отчёт
> `plans/reports/round10.8_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§29 «Раунд 10.8»** (+§1/§9/§25). @PM: фича заархивирована —
> `plans/archive/admin-ui-round108/` (spec.md, tasks.md, **ADR-001-access-windows-modal**,
> **ADR-002-icon-subset-parity**); **plans/archive/ — 30 папок**; plans/features/ —
> 6 активных F-1…F-6. @DevOps: README счётчик 5073→5076; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward `7f3b790..31d2ce7`,
> `.env` без изменений, restart active, `/api/health`=200, шрифт `?v=2.52.0` → 200
> (wOF2, 18 388 B), 0 ошибок. Граф обновлён: милстоун `round10.8-epic` → COMPLETED +
> DEPLOYED, фича → WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure,
> создан `tech-debt-round10.8` (R10.8-2/-3/-4 + закрытые R10.8-1/-5). **Осталось
> вручную:** live Android smoke **T-1254** (логи) и **T-1258** (окна «Доступов»);
> опциональный betterstack-401 fix.

> **Синк STEP 10 (финал, post-commit+деплой) 12.09.2026: раунд 10.9 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `f928225`** (`d2d1215` — фича,
> 34 файла, тесты 5105; `f928225` — docs деплой-верификация; поверх `51f308b` —
> docs-финал 10.8; прод до деплоя `31d2ce7` = задеплоенный 10.8).
> Единственная фича **`admin-ui-round109`** (spec @Architect + tasks @PM + ADR-109;
> T-1270…T-1314) реализована целиком: (1) PERMsoc — 4 сворачиваемых owner-блока
> (Славик/Оля/Мимикрия/Общее), в каждом ровно один рабочий тумблер; новый
> `flags.slavik_enabled` (default True), `reactions_persons` удалена,
> `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`;
> (3) `_preserveScroll` для `document.scrollingElement` И `.scroll-area` —
> сохранение не прыгает вверх, вкл. fullscreen; (4) все описания и титулы
> параметров/групп переписаны (plain ironic language, без жаргона/AI-паттернов);
> (5) карточка «Тяжёлые фичи» удалена; (6) «Бюджет фона» перенесён в «Сводку»
> (backend/endpoint не тронуты); (7.1) dashboard «Доступность ключей» из 4
> функциональных групп + реальный health `probe_openai` (ok/error/timeout/
> unreachable/not_configured; STT groq POST `/audio/transcriptions` multipart WAV;
> кэш per `module_id`: 2xx 60с, ошибки 10с; stale-200 не отдаётся); (7.2) 7
> `models.*_display_name` первым полем каждого провайдер-блока, форма `max-w-3xl`;
> (8) градиент быстрее (`--grad-speed:14s`, `grad-drift 18s`). **Каталог 400 / 90 /
> 372 / mapped 88 / TAB_RULES 19**; ноль PG-DDL, SQLite v8, `bot.py`/`media/` не
> тронуты. @Reviewer: REJECTED → фиксы → APPROVED WITH MINOR ISSUES → follow-ups
> закрыты. @Scanner: **0 blocker / 0 major / 0 medium** (3 low R10.9-1/-2/-3 +
> 3 info R10.9-4/-5/-6; R10.9-6 закрыт архивацией; отчёт
> `plans/reports/round10.9_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` §30 (+§1/§9/§25). **Тесты: 5105 passed / 0 failed**
> (baseline 10.8 = 5076; +29); `node --check web/app.js` clean; `tests/js/routing_test.js`
> → `JS-UNIT-OK`; `git diff --check` чист. @PM: фича заархивирована —
> `plans/archive/admin-ui-round109/` (spec.md + tasks.md + ADR-109.md);
> **plans/archive/ — 31 папка**; plans/features/ — 6 активных F-1…F-6. @DevOps:
> README 5105 + APP_VERSION **2.53.0**; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward `31d2ce7..d2d1215`,
> `.env` без изменений, restart active, `/api/health` 200, 0 ошибок. Граф обновлён:
> милстоун `round10.9-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.9` (R10.9-1/-2/-3 low + R10.9-4/-5 info; R10.9-6 закрыт).
> **Осталось вручную:** live Android smoke — T-1277/1290/1292/1294/1302/1305;
> опциональный betterstack-401 fix. ⚠️ Пункт 2 исходного ТЗ (инфраструктура
> локального IDE владельца) — **вне скоупа проекта**, в репозитории/графе
> не фиксируется.

> **Синк STEP 10 (финал, post-commit+деплой) 12.09.2026: раунд 10.10 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `772db08`** (`d082800` — фича,
> тесты 5144; `a477747` — fix scripts standalone sys.path bootstrap + CLI-тест,
> тесты 5145; `772db08` — docs деплой-верификация; поверх `da85b60` — docs
> memory-sync 10.9; прод до деплоя — `d2d1215` = задеплоенный 10.9).
> Единственная фича **`admin-ui-round1010`** (spec @Architect + tasks @PM +
> ADR-1010-1/2/3; T-1315…T-1328) реализована целиком: (1) header fullscreen
> padding — `max(env(safe-area-inset-*), --tg-content-safe-area-inset-*,
> --tg-safe-area-inset-*)`, профиль-блок не перекрывается нативными кнопками;
> (2) мобильный график доступности ключей — окно строится ОТ КОНЦА, новейшие
> сэмплы не отбрасываются, дорожки на провайдера + временная сетка 300с (min 12
> бакетов), адаптивная высота, `api_payload` не изменён; (3) «Провайдеры» —
> реальные значения полей через `blockFieldValue` (`:value`+`@input`), секреты
> замаскированы; (4) ЛС heavy-modules OFF — `scripts/disable_dm_heavy_modules.py`
> (идемпотентный; dry-run/`--apply`/`--restore`/`--chat-id`/snapshot) + new-DM
> defaults OFF (сон/ностальгия/саммаризация; F-14 gate не тронут); (5) «Роли» —
> аватар+ник+мелкий серый ID, backend `global_user_display_info` (RAM-TTL 1ч,
> fail-open, транзиентные ошибки не кэшируются), ширины w-24/flex-1 min-w-0/
> shrink-0. **Каталог 400 / 90 / 372 / mapped 88 / TAB_RULES 19**; ноль PG-DDL,
> SQLite v8, `bot.py`/`media/`/`.env` не тронуты. @Reviewer: REJECTED (график
> отбрасывал новейшие данные) → fix → APPROVED WITH MINOR ISSUES → restore
> exit-code Low закрыт. @Scanner: **0 blocker / 0 major / 0 medium** (low
> R10.10-1/-2/-3 + info R10.10-4/-5; большинство закрыто;
> `plans/reports/round10.10_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§31** (+§3/§9/§25). **Тесты: 5145 passed / 1 skipped /
> 0 failed** (baseline 10.9 = 5105; Scanner 5140 + 1 skipped на момент аудита);
> `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
> `git diff --check` чист. @PM: фича заархивирована —
> `plans/archive/admin-ui-round1010/` (spec.md + tasks.md + ADR-1010-1/2/3.md);
> **plans/archive/ — 32 папки**; plans/features/ — 6 активных F-1…F-6.
> @DevOps: README 5145 + `APP_VERSION` **2.54.0**; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward, `.env` без
> изменений, restart active, `/api/health` 200, 0 ошибок; **DM data-run применён**
> (1 активный ЛС; snapshot `var/dm_modules_off_snapshot_20260911T201219Z.json`;
> повторный dry-run 0). Граф обновлён: милстоун `round10.10-epic` → COMPLETED +
> DEPLOYED, фича → WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN
> plans-structure, создан `tech-debt-round10.10` (R10.10-1..-5). **Осталось
> вручную:** live Android QA — T-1317/1320/1323/1332; UI spot-check DM-тумблеров
> OFF (T-1328). ⚠️ П.6 Headroom (saved-tokens stats, внешняя IDE-инфраструктура) —
> **вне скоупа проекта**, в репозитории/графе не фиксируется.

> **Синк STEP 10 (финал, post-commit+деплой) 12.09.2026: раунд 10.11 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `cbe6ea5`** (`3624789` — фича,
> 28 файлов, тесты 5172; `cbe6ea5` — docs деплой-верификация; поверх `ec5dd1f` —
> docs memory-sync 10.10; прод до деплоя — `772db08` = задеплоенный 10.10).
> Единственная фича **`llm-providers-refactor-round1011`** (spec @Architect + tasks
> @PM + ADR-1011-1/2/3; T-1340…T-1381) реализована целиком: (п.1) `POST /api/llm/test`
> резолвит SAVED-ключ блока server-side при пустом `api_key` (R17-safe: `_BLOCK_SAVED_KEY`,
> `_saved_api_key` = `hot.get(pg_key, settings_default)`, явный draft приоритетнее, ключ
> не в `_result`/логах; UI mask+hint `{configured,last4}`) — работает без повторного ввода;
> (п.2) рефакторинг «LLM Провайдеры» — nav-icons 22px/gap .15rem/min-width 60px + pinned
> профиль; две зоны «Подключения»/«Расширенные настройки» (**computed**, не methods);
> embeddings — один блок с 3 подблоками (main/f1/f2) с полными полями base/model/key/
> «Проверить»; video fallback поднят сразу после `video_summary_openrouter`; media-share/
> search_keys/llm_guard → advanced внизу с human-subtext; теххаос внизу; (п.3) dashboard
> key-history — непрерывный график (`spanGaps:true` + `stepped:true`, линейная ось X в ms,
> `parsing:false`, ticks HH:MM; `type:'time'` НЕ используется), серверный контракт
> `api_payload`/`key_history.py` НЕ изменён; (п.4) docs-only отчёт
> `plans/docs/memory_sleep_nostalgia_lore_report.md` (память, сон/синтез снов, ностальгия,
> лор чатов, тайминги/лимиты, сборка контекста — plain language, каждая цифра `file:line`).
> **Каталог-дельта (ADR-1011-2, sanctioned):** 4 infra embed-fallback записи перенесены
> в каталог (`models.embedding_fallback_base_url/_model` → models/`models_embeddings`;
> `keys.embedding_fallback_api_key/_2` → keys/`keys_llm`, `secret=True`), `llm_client`/
> `status_service` читают `hot.get`; счётчики БЕЗ роста — REGISTRY **400** / GROUPS **90** /
> Settings **372** / mapped **88** / `TAB_RULES` 19 / `CONFIG_TAB_TITLES` 19; `categorized`
> 372→**376** (models 40→42, keys 13→15), `infra` 28→**24**. Ноль PG-DDL; SQLite v8;
> `bot.py`/`media/`/`.env` не тронуты. @Reviewer: REJECTED (CRITICAL: zone helpers в methods,
> не computed → блоки провайдеров исчезали) → фикс (computed) → APPROVED WITH MINOR ISSUES.
> @Scanner: **CLEAN — 0 blocker / 0 major / 0 medium** (3 low R10.11-1/-2/-3 закрыты
> follow-up; 3 info R10.11-4/-5/-6 → техдолг; `plans/reports/round10.11_scanner_audit.md`).
> @Architect: merge в `plans/ARCHITECTURE.md` **§32** (+§5/§9/§25). **Тесты: 5172 passed /
> 0 failed** (baseline 10.10 = 5145; Scanner 5168 на момент аудита — до follow-up
> R10.11-1/-2/-3); `node --check web/app.js` clean; `node tests/js/routing_test.js` →
> `JS-UNIT-OK`; `git diff --check` чист; R17-скан чист. @PM: фича заархивирована —
> `plans/archive/llm-providers-refactor-round1011/` (spec.md + tasks.md + ADR-1011-1/2/3.md);
> **plans/archive/ — 33 папки**; plans/features/ — 6 активных F-1…F-6. @DevOps: README +
> `APP_VERSION` 2.54.0→**2.55.0**; коммиты `3624789` (feat, 28 файлов) + `cbe6ea5` (docs
> deploy-verification); push origin/master; **деплой 198.46.175.136:/var/www/admin_bot** —
> git pull fast-forward `772db08..3624789`, миграция `migrate_env_to_pg --only-category
> models,keys` **created=5 / skipped=48**, restart active, `/api/health` 200, 0 ошибок.
> Граф обновлён: милстоун `round10.11-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан `tech-debt-round10.11`
> (R10.11-4/-5/-6; R10.11-1/-2/-3 закрыты). **Осталось вручную:** live Android/Telegram QA
> (**T-1377** — поле ключа + «Проверить» без повторного ввода, навигация/профиль/сетка,
> две зоны, эмбеддинги, video-фоллбэк, media-share, график; статически покрыто
> `tests/test_webapp_round1011_ui.py` + JS-юниты). ⚠️ Наблюдение: pre-restart PID имел
> 401 к `apinet.cloud` (возможно невалидный primary token) — стоит проверить.
> ⚠️ Headroom — вне репозитория, как сущность НЕ фиксируется.

> **Синк STEP 10 (финал, post-commit+деплой) 13.09.2026: раунд 10.12 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `bad2b0d`** (`708f7df` — фича,
> 39 файлов, тесты 5211; `bad2b0d` — docs деплой-верификация; поверх `32d1aa9` —
> docs memory-sync 10.11; прод до деплоя — `cbe6ea5` = задеплоенный 10.11).
> Единственная фича **`providers-kostik-round1012`** (spec @Architect + tasks @PM +
> ADR-1012-1): (п.1) эмбеддинги развязаны от прямых ответов — новый
> `models.embedding_base_url` (PG-значение `https://apinet.cloud/v1`) +
> `keys.embedding_api_key` (OD-1; пусто → рантайм-фолбэк на llm-ключ);
> `models.llm_base_url` = `https://nano-gpt.com/api/v1`; отдельный read-path +
> отдельный кэш httpx-клиента (`_embed_client`); `.env` обновлён на проде
> (`LLM_BASE_URL=nano-gpt/api/v1`, `EMBEDDING_BASE_URL=apinet.cloud/v1`); (п.2) фикс
> 422 — глобальные (`per_chat=false`) ключи сохраняются в global-скоуп (без
> chat-скоупа) в `saveConfigItem`/`saveBlock`/`saveKeyItem`; серверный гейт + DM
> read-only не ослаблены; (п.3) блоки подключений объединены/переименованы с
> display-name подписями в шапке, OpenRouter display-name разделён (STT vs видео),
> свопа транскрибация/саммаризация нет (проверено); (п.4) Костик — JSON-параметр
> `reactions.kostik_replies` (14 фраз: 4 владельца + 10) + плотный list-editor +
> `flags.kostik_enabled` (default true) + новый PERMsoc-блок Костика; handler
> безопасен при пустом списке; `limits.kostik_reply_probability` (0.1) сохранён.
> **Каталог (sanctioned Δ +5, ADR-1012-1):** REGISTRY **405** / GROUPS **90** /
> Settings **377** / mapped **88** / `categorized` **381** (models 42→44, keys 15→16,
> flags 58→59, reactions 38→39); TAB_RULES 19. Ноль новых PG-DDL; SQLite v8;
> `bot.py` router order не тронут (только DI-kwargs `embed_base_url`/`embed_api_key`
> в 4 точках); `media/`/`.env` (git) не тронуты. @Reviewer APPROVED WITH MINOR ISSUES
> (дефекты 1–4 закрыты); @Scanner **CLEAN — 0 blocker / 0 major / 0 medium**
> (2 low R10.12-1/-5 закрыты follow-up; 3 info R10.12-2/-3/-4 → техдолг;
> `plans/reports/round10.12_scanner_audit.md`); @Architect merge в `plans/ARCHITECTURE.md`
> **§33** (+§5/§9/§12/§25). **Тесты: 5211 passed / 0 failed** (baseline 10.11 = 5172);
> `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
> `git diff --check` чист. @PM: фича заархивирована —
> `plans/archive/providers-kostik-round1012/` (spec.md + tasks.md + ADR-1012-1.md);
> **plans/archive/ — 34 папки**; plans/features/ — 6 активных F-1…F-6. @DevOps: README +
> `APP_VERSION` 2.55.0→**2.56.0**; коммиты `708f7df` (feat, 39 файлов) + `bad2b0d` (docs
> deploy-verification); push origin/master; **деплой 198.46.175.136:/var/www/admin_bot** —
> git pull fast-forward `3624789..708f7df`, миграция `migrate_env_to_pg`
> **created=5 / skipped=149**, restart active, `/api/health` 200, 0 ошибок. Граф обновлён:
> милстоун `round10.12-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан `tech-debt-round10.12`
> (R10.12-2/-3/-4; R10.12-1/-5 закрыты), `round10.12-epic FOLLOWS round10.11-epic`.
> **Осталось вручную:** live Android/Telegram QA; опционально задать выделенный
> embedding api key. ⚠️ Headroom — вне репозитория, как сущность НЕ фиксируется.

> **Step 0 recon 13.09.2026 (раунд 10.13 — «Рефакторинг Памяти, Сна и Дашборда
> Интеллекта»):** HEAD == origin/master == `ce25dc7`, дерево ЧИСТОЕ, APP_VERSION
> 2.56.0, pytest **5210/0**, каталог **405/90/377/88** (TAB_RULES 19). Новый эпик
> `plans/current_task.md` (пп.1–10) пересёк memory/RAG/сон/ностальгию/лор/провайдеров/
> TMA. **Ни один пункт 1–10 не реализован**; есть фундамент (см. ниже).
> **Уже есть (не переделывать):** (1) `build_rag_context`/`_format_origin_labeled_line`
> (`services/summary_memory.py:676,681-710`) — факты уже с метками origin и датой
> `[ГГГГ-ММ-ДД]` (нет автора и пометки устаревания); (2) GraphRAG v2 + vec/int8-KNN +
> MMR + `dig_into_lore`; (3) `DreamWorker` (окно 4–6 local, тик 60м, бюджеты,
> beliefs `derived_belief`/kind=belief, weight 0.6, вечные) + `NostalgiaWorker`
> (слои A/B) + `LoreWorker` + `CheckupService`/`memory_health.py`/`worker_budget.py`;
> (4) provider-модель `PROVIDER_BLOCKS` parent+`subBlocks` (10.11/10.12),
> `providerCoveredKeys`, `_BLOCK_SAVED_KEY`/`KNOWN_BLOCKS` (`services/llm_probe.py`);
> (5) вкладки «Память»/«Сон»/«Ностальгия» (10.4-фича C), мини-блоки dream/nostalgia
> в TMA, «Бюджет фона (день)» в «Сводке» (10.9), `web/api/memory_agi.py`;
> (6) старый линейный график аптайма (`web/index.html:2713-2718` +
> `services/uptime_heartbeat.py`) — его заменяет п.8; key-history график (10.11) —
> ДРУГОЙ, не путать; (7) технический отчёт `plans/docs/memory_sleep_nostalgia_lore_report.md`
> (10.11) — сырьё для п.10, но новый `intelligence_user_guide.md` пишется с нуля.
> **Исторические конфликты/запреты:** комбинированного тега `ERROR+WARNING` и
> `chat_memes`/`archived_belief`/`paradigm`/`deep sleep`/force-directed graph в коде
> НЕТ (greenfield); `logLevel:'INFO'` (`web/app.js:860`) + один `level` в
> `/api/status/logs` — п.9 меняет контракт фильтра (нужен учёт тестов);
> beliefs сейчас вечные и подаются как обычные факты — п.4 меняет read-path
> контекста (регресс-риск); инварианты 10.11/10.12 в силе: **ноль новых PG-DDL,
> SQLite v8, `bot.py` router order не трогать** (только DI-kwargs), `media/`/`.env`
> не трогать, **R17** (секреты только `{configured,last4}`), каталог-счётчики
> обновлять осознанно с тестами, новые provider-блоки — в формате parent+subBlocks
> (+`providerCoveredKeys`/`_BLOCK_SAVED_KEY`, иначе generic-дубли/непроверяемые
> ключи). **Открытые Critical/High из Scanner — НЕТ:** 10.10/10.11/10.12 =
> 0 blocker/0 high/0 medium; открыт low R10.12-1 (`saveKeyItem` не на global-save →
> 422 для `keys.*` вне provider-блоков) — релевантен п.3, если новые ключи пойдут
> отдельными блоками; техдолг info R10.11-4 (probe base_url hardening), R10.12-2/-3/-4.
> **Рекомендация @PM:** 6–7 фич — F1 backend 4D-память+сон-группировка (п.1);
> F2 backend «Сон v2»: Belief Decay + Resurrection (п.4+4.1); F3 backend
> «Глубокий сон»: мета-синтез/якоря/парадигмы (п.6) + LLM-роутер фоновых воркеров
> (п.3, backend); F4 frontend «Провайдеры»: 2 новых блока (п.3, UI); F5 frontend
> «Cognition»: дашборд+граф+виджет Сводки (п.5+п.7); F6 frontend: EKG + логи (п.8+п.9);
> F7 docs: user guide + README (п.10). Дробить п.4.1 на 3 подзадачи (резонанс/
> Реаниматор/граф-активация). Зависимости: F1→F2→F3; F4∥F3; F5 зависит от API
> F2/F3/F6. Граф обновлён: `Epic: Cognition-Sleep-Memory Refactor round1013`.
>
> **Синк STEP 2 (Architecture, @Architect) 13.09.2026 (раунд 10.13):** эпик
> ЗААРХИТЕКТИРОВАН — 8 фич, во всех папках `plans/features/cognition-*-round1013/`
> созданы `spec.md` (🟣 SPEC_READY) + `tasks.md` (T-1417…T-1476) + 3 ADR:
> `adr-1013-1-provider-keys.md` (F4/F3 — единые ключи `models.intel_<role>_*` /
> `keys.intel_<role>_api_key`), `adr-1013-2-graph-library.md` (F5 — vis-network
> standalone UMD, self-host, lazy-load), `adr-1013-3-prompt-canon-policy.md`
> (F1 — модульные каноны dream/lore/dossier: PREV-snapshot + байт-тесты,
> `PROMPT_MIGRATIONS` НЕ трогаем). Список спек: **F1** `cognition-4d-memory-round1013`,
> **F2** `cognition-belief-decay-round1013`, **F3** `cognition-deep-sleep-round1013`,
> **F4** `cognition-llm-providers-round1013`, **F5** `cognition-dashboard-round1013`,
> **F6** `cognition-ekg-logs-bugfix-round1013`, **F7** `cognition-user-guide-round1013`,
> **F8** `cognition-irony-dossier-round1013`. Граф: милстоун `round1013-epic-cognition`
> → ARCHITECTED; epic `Epic: Cognition-Sleep-Memory Refactor round1013` обновлён.
>
> **Синк STEP 3 (Intent, @Memory) 13.09.2026 (раунд 10.13):** Human Gate пройден,
> решения подтверждены пользователем. **Подтверждённые решения:** F5 — vis-network
> (standalone UMD, self-host, lazy-load); F3/F4 — роли выделенных LLM
> `intel_history` (Историческая память/Лор) и `intel_bg` (Фоновые проверки/важность),
> при пустых значениях фоллбэк на `models.llm_*`/`keys.llm_api_key`; F8 — Досье через
> существующий `LoreWorker` + `build_persona_card` (новый воркер НЕ создаём),
> мемы = `graph_facts.status='chat_meme'`; архив убеждений =
> `graph_facts.status='archived_belief'`; парадигмы =
> `origin='derived_belief' + belief_meta.type='paradigm'`, weight 0.55.
> **Ключевые DDL-free решения:** `graph_facts.kind` имеет CHECK (`fact`/`belief`) →
> третий kind запрещён (был бы PG-DDL); `graph_facts.status` БЕЗ CHECK → архив/мемы/
> парадигмы кодируются колонкой `status` + JSON `belief_meta`; ноль новых PG-DDL,
> SQLite остаётся v8. **Каталог-Δ:** 405→427 (Settings 377→399), categorized
> 381→403, GROUPS 90, mapped 88, TAB_RULES 19 неизменны. **Флаги (default OFF):**
> `flags.belief_decay_enabled`, `flags.deep_sleep_enabled`,
> `flags.irony_filter_enabled`.
> **Порядок:** F1→F2→F3→F5 (цепочка данных/API); F4 ∥ F3 (RELATED_TO, общий роутер
> `LLMClient.generate_worker` и ключи `intel_*`); F6 и F8 — параллельны основной
> цепочке; F7 — последняя. **Узлы графа:** 8 фич (PART_OF `round1013-epic-cognition`,
> `AdminBot HAS_PLAN`) + 7 компонентов (`DeepSleepWorker`, `LLMClient.generate_worker`,
> `BeliefDecayService`, `CognitionDashboard`, `EKGHeartbeat`, `IronyPromptFilter`,
> `plans/docs/intelligence_user_guide.md`). Статус милстоуна →
> ARCHITECTED + INTENT_SYNCED. Следующий шаг — @Builder (Step 4) по `spec.md`;
> инварианты: ноль PG-DDL, SQLite v8, порядок роутеров `bot.py` (только DI-kwargs),
> R17 (секреты `{configured,last4}`), R16 (id-не-имя).
>
> **Синк STEP 10 (финал, post-commit+деплой) 13.09.2026: раунд 10.13 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `8800bba`** (`8800bba` — feat
> раунда, 8 фич F1–F8, 60 задач T-1417…T-1476, тесты 5392; поверх `ce25dc7` —
> docs memory-sync 10.12; прод до деплоя — `708f7df` = задеплоенный 10.12).
> **8 фич** (все COMPLETED): **F1** `cognition-4d-memory-round1013` — префикс
> `[ММ.ГГГГ \| Автор: ]` + метка `(Внимание: возможно устарело)` >6 мес + временная
> группировка фактов в Сне; **F2** `cognition-belief-decay-round1013` — decay −0.1/мес,
> архив `graph_facts.status='archived_belief'`, Resurrection (векторный резонанс
> 0.78/−0.3, Сон-Реаниматор, граф-активация); **F3** `cognition-deep-sleep-round1013` —
> «Глубокий сон» (якоря → «Мост времени» → парадигмы `origin='derived_belief'`
> weight 0.55) + роутер `LLMClient.generate_worker`; **F4**
> `cognition-llm-providers-round1013` — 2 provider-блока `intel_history`/`intel_bg`
> (parent+subBlocks, фоллбэк на llm-ключ); **F5** `cognition-dashboard-round1013` —
> дашборд «Осмысление» + виджет «Интеллект и Память» + граф vis-network
> (nodes/edges 120/240, polling 15с); **F6** `cognition-ekg-logs-bugfix-round1013` —
> SVG-EKG (Load/CPU/RAM) + багфикс «Логи» (серверный тег ERROR+WARNING, дефолт
> фильтра); **F7** `cognition-user-guide-round1013` — `plans/docs/intelligence_user_guide.md`
> (без жаргона) + README; **F8** `cognition-irony-dossier-round1013` — ироничный промпт
> Досье + мемы `graph_facts.status='chat_meme'` + блоки [Факты]/[Локальные мемы/Ярлыки].
> **Ревью/аудит:** @Reviewer итерация 1 — **Rejected** (BLOCKER-1 [Critical] T-1439 —
> роутер воркеров не подключён; BLOCKER-2 [High] — ностальгия F5) → итерация 2 —
> **APPROVED**; @Scanner итерация 1 — 0 Critical / 1 High / 4 Medium / 9 Low → итерация 2 —
> **CLEAN 0/0/0** (закрыты High S10.13-1 и Medium S10.13-2/-3/-4/-5), остаются **5 Low**
> (техдолг); @Builder — **2 цикла реворков** (после Reviewer Rejected и после Scanner High).
> Источники — `plans/reports/round10.13_reviewer.md` + `plans/reports/round10.13_scanner_audit.md`.
> **Архитектура:** `plans/ARCHITECTURE.md` **§34** + `ADR-1013-1` (provider keys
> `models.intel_<role>_*`/`keys.intel_<role>_api_key`), `ADR-1013-2` (vis-network
> standalone UMD self-host lazy-load), `ADR-1013-3` (prompt canon policy — модульные
> каноны dream/lore/dossier, `PROMPT_MIGRATIONS` не трогаем). @PM: 8 фич заархивированы —
> `plans/archive/cognition-*-round1013/` (spec.md + tasks.md + 3 ADR); **plans/archive/ —
> 42 папки**; plans/features/ — 6 активных F-1…F-6. **Тесты: 5392 passed / 0 failed**
> (база 10.12 = 5211 → **+181**); `node --check web/app.js` clean; `node tests/js/routing_test.js`
> → `JS-UNIT-OK`; `git diff --check` чист. **Каталог:** REGISTRY **427** / Settings **399** /
> `categorized` **403** / GROUPS 90 / mapped 88 / TAB_RULES 19 (санкционированный Δ
> ADR-1013-1 + флаг F8). **Инварианты:** ноль новых PG-DDL, SQLite **v8**, порядок
> роутеров `bot.py` не тронут (только DI-kwargs), R17-скан чист, F7-гайд без запрещённого
> жаргона (grep 0), новых `v-html`/CDN нет. **Флаги default OFF:** `flags.belief_decay_enabled`,
> `flags.deep_sleep_enabled`, `flags.irony_filter_enabled`. **Деплой @DevOps:** README +
> `APP_VERSION` 2.56.0→**2.57.0**; коммит `8800bba`; push origin/master `ce25dc7..8800bba`;
> **деплой 198.46.175.136:/var/www/admin_bot** — git pull fast-forward `708f7df..8800bba`,
> restart active (running) PID 1629874, `/api/health` = 200 `{"status":"ok"}`, рабочее дерево
> чистое; `.env` на проде не редактировался (новые ключи — безопасные дефолты, флаги OFF).
> **Техдолг Low (открыт, не блокеры):** `S10.13-9` / `-11` / `-13` / `-14` / `-6b` — KG
> `tech-debt-round10.13`; `plans/reports/round10.13_scanner_audit.md` §5. Граф обновлён:
> милстоун `round1013-epic-cognition` → COMPLETED + DEPLOYED, 8 фич → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure (PART_OF/ARCHITECTED удалены),
> создан `release-v2.57.0-round1013`, `round1013-epic-cognition FOLLOWS round10.12-epic`,
> `plans/metrics.md` создан. **Остаточно (не блокеры):** betterstack_handler WARNING 401
> (внешний LOGTAIL_SOURCE_TOKEN, вне раунда); ручной live Android/Telegram QA.
>
> **Раунд 10.3 (F-13/F-14/F-15) завершён и заархивирован** — см. раздел
> «Раунд 10.3 — финал (09–10.09.2026)» ниже; их спеки — в `plans/archive/`
> (`tma-chat-selector-fixes`, `dm-user-settings`, `direct-sandbox-budget-investigation`).

## Раунд 10 — ЗАВЕРШЁН, закоммичен и ЗАДЕПЛОЕН (07.09–08.09.2026, HEAD 533bf13; статус: done+deployed)

«Multi-chat scaling (Variant A)» по `plans/docs/multi-chat-scaling-research.md`: 6 фич,
82 задачи T-843…T-924 (нумерация продолжает T-842). spec.md @Architect (закрывает
Q-протоколы раздела A tasks.md), tasks.md @PM. **Итог (08.09.2026): полный pytest
4717 passed / 0 failed (+155; подтверждён прогоном — 54.46s, 1 StarletteDeprecationWarning),
аппрув @Reviewer PASS, `git diff --check` чист; все 6 фич заархивированы
(@PM Archive Phase), архитектура — `ARCHITECTURE.md` §22, backlog.md — «✅ Выполнен
и заархивирован (08.09.2026 @PM, HEAD fac1b9f, tests 4717)».** После финала —
**коммит `69be94e` (фича, 89 файлов, +8932/−216) + фикс `533bf13` (DSN, 2 файла),
push origin/master, прод-деплой — см. «Раунд 10 — закоммичен и задеплоен» ниже.**

| Фича | Задачи | Скоуп |
|---|---|---|
| `multi-chat-rbac-byok` (F-7) | T-843…T-869 (27) | Часть 1 — фундамент раунда: роли Global/Local/Moderator/User/Custom (`bot_roles.role_type`, `services/roles.py` ROLE_RANK), `services/access.py::access_for`, таблица `param_permissions` (view/edit_min_role+hidden_from_local, DEFAULT_MATRIX в коде), `chat_profiles.chat_params` JSONB {v:1, overrides, gates, keys:{allow_global}, perm_overrides, meta} + резолв `hot_chat` chat_params→bot_settings→дефолт (409 по updated_at, NOTIFY, кэш 120с), BYOK `chat_keys` + бюджет `chat_usage` + `limits.chat_global_key_budget_*` + sandbox `content.no_key_reply`, `resolve_api_key(chat_id)` в llm_client, API `/api/access/*` + X-Chat-Id в /api/config |
| `tma-ui-fixes` (F-8) | T-870…T-877 (8) | Часть 3.2 — 8 UI/UX-фиксов TMA: flex-шапка 380px (T-870), логи `<pre><code>` 0.75rem (T-871), relations Alias→nickname→username→id + аватар-фолбэк (T-872), title чатов вместо -100… (T-873), чип «авто» (T-874), компактные стадии+note (T-875), Telegram ID админа → «Доступы» (T-876), регресс-аудит (T-877). Только web/*, без API/БД-изменений |
| `permsoc-module-isolation` (F-9) | T-878…T-889 (12) | Часть 2.1 — `services/permsoc.py` (реестр 5 модулей: slavik/kostik/alan/olya/mimic) + `PermsocGateFilter` (гейт на уровне фильтра, порядок роутеров bot.py НЕ меняется); master `flags.permsoc_enabled` default false + `chat_params.gates.permsoc`; под-флаги olya/mimic/alan через hot_chat; новые чаты OFF, живые — бэкфил `scripts/backfill_permsoc_gates.py` (ON для -1002661910336/custom-профилей) |
| `feature-gates-worker-budget` (F-10) | T-890…T-902 (13) | Части 2.3+2.4 — жёсткий Opt-In: `gates_opt_in` колонка + gates в `chat_params.gates` (dream/nostalgia/lore_auto/permsoc), `services/feature_gates.py::set_feature_gate` единый write-path; бюджет-ледежер `worker_budget` в PG (day/scope/metric/used; WORKER_BUDGET_TZ=Asia/Yekaterinburg), `services/worker_budget.py::consume`, лимиты `limits.worker_daily_*`, деградация nostalgia→lore→dream, jitter ≤ interval/3, fail-open; API GET/PUT gates + GET /api/workers/budget |
| `tma-ia-progressive-disclosure` (F-11) | T-903…T-913 (11) | Части 2.2+3.1 — MENU_ORDER (Главная/Чат-Профиль/Модули и Фичи/Настройки AI/Доступы и Роли), новая вкладка `modules_feats`, вход Oversight (F-12); селектор чатов `GET /api/access/chats` + X-Chat-Id + localStorage active_chat_id; `progressive_level` (RAG/k/vector/timeout/context/budget → advanced) + нативный `<details>` аккордеон + adminbot.expand; user → read-only (только Статус/Как это работает) |
| `global-oversight-dashboard` (F-12) | T-914…T-924 (11) | Часть 3.1 — `services/oversight.py::build_summary` → `ChatSummary` (гейты/opt_in/key_status/admins_count/last_active_ts/budget; кэши 60-120с, без новых таблиц), kill-switch через `set_feature_gate`, запрет глобального ключа `chat_params.keys.allow_global=false`, API GET /api/oversight/summary|chat/{id} + POST killswitch/global_key, `requires_global_admin` (deps.py), зверю-таблица + модалка в TMA |

Взаимозависимости: F-7 — фундамент (chat_params/RBAC/chat_keys/X-Chat-Id/params-meta);
F-9 и F-10 пишут в `chat_params.gates` через единый патч-метод F-7 `set_chat_params`;
F-11 и F-12 построены поверх F-7/F-10; F-8 — независимый UI-фикс-слой.
**Все 6 фич раунда 10 (F-7…F-12) — archived** (`plans/archive/<feature>/{spec.md,tasks.md}`);
plans/features/ — снова 6 старых активных (F-1…F-6).

### Финал раунда — ключевые факты

- **Фиксы по ревью:** R1 (chat-scope EDIT требует chat-грант local_admin|moderator
  этого чата или global-ранг — `access.py::can_edit_param`), R6 (per-call BYOK-резолв
  `_resolve_api_key_and_source(chat_id)` без `_byok_chat_id`-инстансного стейта),
  S1–S3 (config-глобальный путь по ролям; `_mask_key_for_role` — `{configured,last4}`
  глобального только global-admin; модератор/юзер без chat-гранта — read-only);
  R17 — raw-ключи никогда не логируются/не отдаются.
- **Девиансия M-F-9 (08.09.2026, вариант (а)):** alan — master-only; `reactions.alan_mimic_enabled`
  остаётся легаси-выключателем common-мимикрии на Леху (нужны ОБА флага), в реестр модуля не входит
  (обоснование: прод-сид False выключил бы живое приветствие Лехи после бэкфила master ON).
- **RUNTIME WARNING соблюдён:** SQLite остаётся v8 (новых миграций нет — только идемпотентные
  PG-DDL: `bot_roles.role_type`, `param_permissions`, `chat_keys`, `chat_usage`, `worker_budget`,
  ALTER `chat_admins`/`chat_profiles`/`chat_lore_history`-CHECK); порядок роутеров bot.py,
  `hot.get`/ConfigCache, LEGACY/PREV-каноны — без дифов.
- **Каталог:** REGISTRY 372→**383** (limits +9 в т.ч. `limits_worker` 7 + chat_global_key_budget_*,
  flags +1 `permsoc_enabled`, content +1 `no_key_reply`); группы 70→**71**; Settings 349→**359**.
- **DevOps runbook ВЫПОЛНЕН (08.09.2026):** PG-DDL прогнан (`[pg_db] DDL ok`, 8 таблиц),
  роли засеяны (admin/moderator/user/local_admin), `scripts/backfill_permsoc_gates.py` success
  (gates.permsoc=True), `scripts/backfill_feature_gates.py` success (chat=-1002661910336:
  dream=False, lore_auto=True, nostalgia=False, opt_in=True); live-верификация — post-deploy
  journal чист (без Traceback/ERROR/CRITICAL, только пре-существующий betterstack/Logtail 401).
- **Известные follow-up (вне раунда):** тест-гап `backfill_permsoc_gates.py` (нет прямых
  unit-тестов бэкфила — только детерминированное правило), проверка имени CHECK-ограничения
  `chat_lore_history` на проде (field='gates'/'chat_keys' — DDL-имя под live-верификацию),
  предложение расширения `deploy_v2.9.2.py` (шаблон деплоя: DDL + бэкфилы + live-гистограммы).

### Раунд 10 — закоммичен и задеплоен (08.09.2026)

- **Коммиты (master):** `69be94e` feat(admin,web,chat): Multi-Chat раунд 10 — RBAC и BYOK
  (chat_params-слой, param_permissions), PERMsoc-изоляция, фичи-гейты и бюджет воркеров, TMA
  (5 секций, прогрессивное раскрытие, Oversight), UI-фиксы + docs(readme) (тесты 4717)
  — 89 файлов, +8932/−216; `533bf13` fix(scripts): бэкфиллы раунда 10 — DSN из
  os.getenv(POSTGRES_DSN) вместо несуществующего settings.POSTGRES_DSN (деплой: AttributeError,
  pg_db-резолв) — 2 файла.
- **Пуш:** origin/master; local master HEAD == origin/master ==
  `533bf13f421025dc3c9c900bd0fc798d0236521a`.
- **Деплой (198.46.175.136:/var/www/admin_bot):** `git pull` fast-forward до 533bf13; .env без
  изменений (только API_TOKEN — новых переменных не требуется); `systemctl restart admin_bot` OK
  (старый процесс — SIGKILL по таймауту, пре-существующее поведение; новый инстанс чист);
  status active (running), PID 133710.
- **Прод-состояние:** `[pg_db] DDL ok` (8 таблиц); роли засеяны (admin/moderator/user/local_admin);
  `backfill_feature_gates.py` done (chat=-1002661910336: dream=False, lore_auto=True,
  nostalgia=False, opt_in=True); `backfill_permsoc_gates.py` done (gates.permsoc=True);
  post-deploy journal чист (без Traceback/ERROR/CRITICAL).
- **README.md:** строка версии — тесты 4717, бейдж «Раунд 10», новый раздел «Multi-Chat, RBAC
  и BYOK (раунд 10)», TMA-таблица перестроена (5 секций меню), +3 пункта «Известные нюансы».
- **Follow-up (известные):** betterstack/Logtail 401 в journal — LOGTAIL_SOURCE_TOKEN невалиден
  в .env (пре-раунд-10, не регрессия); graceful-stop SIGKILL по таймауту (пре-существующее
  поведение); plans/MEMORY.md untracked намеренно (в коммиты раунда не входит).

### Хотфикс 10.1 — закоммичен и задеплоен (08.09.2026)

Post-deploy багфиксы TMA по рекону `recon: tma-round10-postdeploy-bugs` (БГ1–БГ4).
- **Коммит (master):** `8eae899` fix(admin,web): TMA хотфикс 10.1 — пустые вкладки
  (basicItems/advancedItems), логи (сверху свежие, клик-копия, шрифт 0.7rem), лор (ленивые
  аватары, каскад имён, скролл/фулскрин), Модули и Фичи (бюджет всегда) + docs(readme)
  (тесты 4726) — 8 файлов, +436/−151, поверх `533bf13`; local HEAD == origin/master ==
  `8eae8992a55a9a09255c345018d909759121a04b` (подтверждено git rev-parse).
- **Фиксы (review PASS, миноры закрыты):** (1) пустые конфиг-вкладки — реализованы
  `basicItems`/`advancedItems`, прогрессивное раскрытие Basic/Advanced работает (БГ1);
  (2) логи — `scrollTop=0` (сверху свежие), клик по строке = копирование, off-screen
  textarea-фолбек, шрифт `.log-code` 0.70rem (БГ2); (3) лор — обогащение топ-50 (было топ-30),
  ленивые аватары 300ms stagger, каскад имён alias→nickname→username→id (порядок — минор
  ревью), высоты панелей + fullscreen-mode (БГ3); (4) Модули и Фичи — бюджет виден всегда
  (без выбранного чата), плейсхолдеры + optInCount, master-тумблер disabled без чата (БГ4);
  миноры ревью: template filter → methods, lazy-фильтр исключает топ-50.
- **Тесты:** 4726 passed / 0 failed (4717 + 9 новых в 4 test_webapp-файлах).
- **README.md:** «Тестов: 4726 | Раунд: 10 (хотфикс 10.1 — TMA снова открывается)»,
  абзац «Хотфикс 10.1 — бот взял себя в руки», счётчик раундов +9.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 8eae899; .env БЕЗ изменений
  (API_TOKEN присутствует; PERMSOC_ENABLED/WORKER_* не нужны — работают дефолты);
  restart OK; active (running) PID **159455**, since 2026-09-07 16:27:04 UTC; journal чист
  (DDL ok, polling, webapp lifespan, без Traceback/CRITICAL).
- **Follow-up: НОВЫХ НЕТ.** Пре-существующие (не регрессия): betterstack/Logtail 401
  (LOGTAIL_SOURCE_TOKEN невалиден), graceful-stop SIGKILL-after-timeout.

### Раунд 10.2 — фиксы (09.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d30b203)

По рекону `recon: tma-bugs-7-post-10.1` (7 багов TMA от юзера; bug 8 — диск
сервера, DevOps вне кода). HEAD == origin/master == `d30b203` (был 8eae899).

- **Статус: COMPLETED + DEPLOYED.** Коммит + пуш + деплой выполнены 09.09.2026
  (см. «Раунд 10.2 — финал» ниже). планы-док plans/MEMORY.md остаётся
  untracked намеренно.
- **Фиксы (все 7 закрыты):**
  (1) селектор чата всегда виден для админов + кнопка/дропдаун «Выбрать чат»
  в шапке и empty states (`bug: tma-chat-selector-hidden`);
  (2) сайдбар скроллится — md:sticky md:h-screen md:overflow-y-auto + mobile
  overflow-y:auto (`bug: tma-sidebar-noscroll`);
  (3) НОВАЯ вкладка «Функции PERMsoc» — группы каталога
  `flags_permsoc`/`reactions_admin`/`reactions_permsoc`, TAB_PERMSOC,
  TABS-зеркало с except-списками, master-карточка + бейджи модулей + сводка
  modules_feats; runtime `services/permsoc.py` не тронут (`bug: tma-nopermsoc-tab`);
  (4) аватары — транзиентные Bot API ошибки НЕ в негатив-кэш; каскад имён
  alias→nickname(очищенный)→username(без @)→id (`bug: tma-relations-names-avatars`);
  (5) пустые «(0)» секции скрыты — v-if advancedItems>0, группа v-if
  basic||advanced (`bug: tma-empty-advanced-accordion`);
  (6) права → FLAGS-модель {view_roles, edit_roles}: DEFAULT_MATRIX —
  keys `[]`/`[]`, prompts `[local_admin]`/`[local_admin]`, прочие
  `[moderator,local_admin]`/`[local_admin]`; legacy-нормализация;
  DELETE `/api/access/param_permissions/{key}` = сброс; модалка с
  чекбокс-строками + «Сбросить на дефолт»; глобальный админ имплицитно
  (`bug: tma-perm-flags-ui`);
  (7) clipboard-ghost — одно переиспользуемое скрытое textarea
  (`bug: tma-invisible-copy-field`);
  (8) код-часть фикса диска: MEMORY_BACKUP_KEEP дефолт 7→1 + hot-лимит
  `limits.memory_backup_keep`.
- **Файлы (26):** web/app.js, web/index.html, services/access.py,
  services/param_catalog.py, web/api/access.py, web/api/routes.py,
  web/api/chat_lore.py, web/api/avatars.py, services/memory_backup.py,
  config/settings.py; 12 тест-файлов (test_access, test_webapp_api,
  test_webapp_rbac_ui, test_chat_params, test_frontend_tab_mapping,
  test_param_catalog, test_webapp_nav_disclosure_ui, test_webapp_avatars_ui,
  test_webapp_tma_fixes_ui, test_relations_service, test_memory_backup,
  test_settings_helpers); 4 plans-дока (backlog.md «Ре-дизайн 10.2» +
  archive spec-ы multi-chat-rbac-byok / permsoc-module-isolation /
  tma-ia-progressive-disclosure).
- **Тесты: 4759 → 4760 passed / 0 failed** (финал подтверждён прогоном;
  +1 тест «ID никогда не отображается как имя»; ранее 4759 в .venv — 64.00s,
  1 StarletteDeprecationWarning пре-существующий). Только .venv: системный
  python/py не имеет `ijson` → collection error в test_history_loader/parser.
- **Замечание ревью (APPROVED):** имена отношений as-is — ID никогда не
  отображается как имя (никогда не показывать идентификатор); каскад имён
  alias→nickname raw→username(без @)→''; avatarInitial — графема.
- **Диск сервера (DevOps, уже исправлено на проде 09.09.2026):** освобождено
  ~5.8G (16G→10G used); бэкапы ротированы до 1 через `/root/bak/rotate_bak.sh`
  + root cron 03:10 daily; journal SystemMaxUse=200M; очищены /home/nik/.cache,
  /tmp, apt cache, btmp; главные подозреваемые — /var/www/admin_bot/backups
  (2.8G) + /home/nik/backups_adminbot (2.0G); migrate_history 1.1G — данные,
  не кэш (сохраняется); рекомендация fail2ban; `limits.memory_backup_keep=1`
  теперь применим через hot config. Виновник бэкапов — ежедневный VACUUM INTO
  после импорта истории.

### Раунд 10.2 — финал (09.09.2026)

- **Коммит (master):** `d30b203` fix(admin,web,api): раунд 10.2 — раздел
  «Функции PERMsoc», права-флаги (view/edit_roles), фиксы TMA (селектор чата,
  скролл сайдбара, пустые секции, копи-поле), имена отношений as-is (ID не
  имя), лимит бэкапов 1 + docs(readme) (тесты 4760) — **28 файлов, +1576/−314**,
  поверх `8eae899`; local HEAD == origin/master == `d30b203` (подтверждено
  git rev-parse); `git diff --check` чист.
- **Тесты:** 4760 passed / 0 failed (было 4759; +1 тест «ID никогда не имя»).
- **Ревью:** APPROVED (@Reviewer) — имена отношений as-is: ID никогда не
  отображается как имя; каскад alias→nickname raw→username(без @)→'';
  avatarInitial — графема.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до d30b203; бот
  active (running), PID **454654**; [pg_db] DDL ok; polling активен; webapp 200
  с разделом «Функции PERMsoc»; БЕЗ Traceback после рестарта; .env без
  изменений.
- **README.md:** тесты 4760, бейдж «Раунд 10.2», раздел «Функции PERMsoc»
  (абзац), security-буллет в «Мониторинг», нюанс про имя (ID не отображается).
- **Следующие шаги (10.2):** закрыты; новые follow-up — только security-слой
  (см. «Безопасность сервера» ниже).

### Раунд 10.3 — финал (09–10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (1410a68)

По ультиматуму юзера (7 пунктов ТЗ; задачи 1–4, 6 → F-13/F-14, задачи 5 и 7 →
F-15). HEAD == origin/master == `1410a68` (был d30b203). **Статус: COMPLETED +
DEPLOYED.** Все 3 фичи заархивированы, цикл раунда полностью закрыт (Step 10).

- **Коммит (master):** `1410a68` feat(admin,web,chat,api): раунд 10.3 — единый
  селектор чата в TMA, отдельные настройки ЛС (саммари default-off), диагностика
  sandbox budget и graphrag memorize (тесты 4831) — автор Henry, 09.09.2026
  12:33 UTC; push origin/master; `git diff --check` чист. **plans/MEMORY.md ВПЕРВЫЕ
  вошёл в коммит** (в раундах 10–10.2 был untracked намеренно).
- **Тесты:** 4831 passed / 0 failed (4760 baseline + ~71 новых). @Reviewer
  APPROVED; Scanner 0 blocker/major (миноры R10.3-1…R10.3-6 → ARCHITECTURE.md §24);
  `node --check web/app.js` clean.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 1410a68; рестарт
  09.09.2026 12:37 UTC; `systemctl status admin_bot` → active (running); .env без
  изменений. Прод-диагностика задачи 5 проведена (см. ниже).
- **Фичи (все ARCHIVED, plans/archive/ — 18 папок):**
  - `tma-chat-selector-fixes` (F-13, T-925…T-944): единый нативный <select> +
    бейдж #id/«ЛС #id», удалены openChatPicker/✕ closeApp, фикс v-if/v-for
    precedence (<template v-for> + v-if на дочернем div; configError-баннер),
    .sidebar z-index:45 + safe-area. ARCH §23.
  - `dm-user-settings` (F-14, T-945…T-964): DM-скоуп is_dm_scope=chat_id>0 на
    chat_profiles/chat_params (ноль DDL), is_dm_owner (rank=local_admin,
    DM_OWNER_PRESET без chat_lore), ensure_scope_profile, саммари в ЛС default-off
    (S1–S5), изоляция WHERE chat_id<0 (6 точек), синтез DM-строки в
    /api/access/chats|me, TMA «Личные сообщения» в селекторе. ARCH §23.
  - `direct-sandbox-budget-investigation` (F-15, T-965…T-973): прод-диагностика
    T-965/T-966 ДО фикса; NoApiKeyForChat.details (снапшот resolve_path/day/
    used|limit calls|tokens/allow_global) + WARNING с details; BYOK-фоллбэк
    свой→глобал-бюджет→свой-фоллбэк→sandbox; parse_fact_list: _mask_llm_raw +
    _fallback_parse_facts + 1 ретрай (только fire-and-forget memorize, крон без
    ретрая). ARCH §23/§24.
- **Прод-диагностика задачи 5 (ВЫВОД):** у чата -1002661910336 НЕТ собственного
  ключа (chat_keys пуст) → работает глобальный ключ с суточным лимитом 25
  запросов; 09.09.2026 счётчик дошёл 25/25 в 09:55 UTC, WARNING reason=budget в
  09:57 — исчерпание суточного лимита; sandbox-фраза = штатный дизайн R16 (не
  баг); восстановление автоматическое после сброса бакета chat_usage в 00:00
  Екб. Рекомендации: BYOK-ключ для чата (chat_keys /api/config/keys/own) ИЛИ
  поднять limits.chat_global_key_budget_requests (25 → 50/100) через hot config.
  Детали — KG `recon: direct-chat-sandbox-budget` (+ фикс-слой F-15 уже в проде).
- **README.md:** тесты 4831, раздел раунда 10.3 (ироничный тон сохранён).

### Раунд 10.4 — финал (10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (0bdf272)

По 9 пунктам ТЗ реструктуризации TMA. HEAD == origin/master == `0bdf272`
(был 1410a68). **Статус: COMPLETED + DEPLOYED.** Все 8 фич заархивированы,
цикл раунда полностью закрыт (Step 10).

- **Коммит (master):** `0bdf272` feat(admin,web,chat,api): раунд 10.4 —
  реструктуризация админки (Модули/PERMsoc/Память/Сон/Ностальгия/Провайдеры/
  Отношения), бюджеты per-чат и температура-select, имена людей per-чат/ЛС,
  каскад имён, лимиты ×1.5-×2 для -1002661910336 (тесты 4860); push origin/master;
  `git diff --check` чист.
- **Тесты:** 4860 passed / 0 failed (4831 baseline + 29: test_104_backend_additions 11,
  test_progressive_tab_basic_coverage 3, маркеры webapp_*/frontend_tab_mapping).
  @Reviewer APPROVED; Scanner 10.4 — 0 blocker/major (minor R10.4-1…R10.4-4,
  info R10.4-5…R10.4-7 → ARCH §25; R10.4-1/-2/-3 закрыты follow-up @Builder и сверены);
  `node --check web/app.js` clean.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 0bdf272; **.env —
  добавлена `CHAT_THREAD_MAX_CHARS=2000`**; **бэкфилы применены:**
  `scripts/backfill_104_chat_flags.py` (flags.chat_context_budgets_enabled=false
  для -1002661910336) + `scripts/backfill_104_overrides.py` (15 ключей ×1.5–×2:
  thread_max_chars ×2, global_context_max_chars/limit ×1.5, level2 ×2,
  map_participants_cap ×2, summary_*/ретенция/graph_rag_* ×2;
  graph_edge_weight_increment НЕ менялся); рестарт — `systemctl status admin_bot`
  → active (running).
- **Фичи (все ARCHIVED, plans/archive/ — 26 папок):**
  - `frontend-advanced-collapse-default` (D, T-1018…T-1023): «Расширенные» свёрнуты
    по умолчанию (:open="expandOpen(activeTab)"); 0-basic группы — свёрнуты с видимым
    summary; BUG-5-семантика сохранена; новый тест test_progressive_tab_basic_coverage. §24.
  - `frontend-memory-sleep-nostalgia` (C, T-1006…T-1017): «Память» (memory_rag) +
    отдельные «Сон»/«Ностальгия»; _ADVANCED_GROUPS минус dream/nostalgia; явная
    progressive-разметка; мини-блоки перенесены. §24.
  - `frontend-llm-providers-layout` (E, T-1024…T-1032): 4 секции
    (модели→ключи→фолбэк→расширенные), sections-зеркало TABS; маскировка/BYOK
    без изменений. §24.
  - `frontend-reorg-modules-reactions` (A, T-974…T-989): девиансия D-A1 —
    «Функции PERMsoc» 17 групп (+war/common/goodmorning/word_reactions);
    «Реакции и Триггеры» 4 группы; «Модули» (modules_switches); лор-настройки
    в «Лор чатов». §24.
  - `frontend-limits-temperature-budgets` (B, T-990…T-1005): бюджет-гейт per-chat
    (limits_chat_budgets, override false для -1002661910336); select-температура
    (widget='select' + select_options/select_labels, 422); «Имена людей» (people_names)
    + build_alias_resolver(chat_id); реестр read-путей T-993 для F-5. §24.
  - `frontend-relations-participants` (F, T-1033…T-1044): вкладка «Участники и
    отношения» (type 'relations'); перенос блока участников + «Настройки отношений»;
    DM-заглушка; серверные API без изменений. §24.
  - `backend-relations-nickname` (H, T-1057…T-1065): username для ВСЕХ строк
    (Semaphore(5), кэш 1ч; фото топ-50); каскад alias→nickname→username→''; R16. §24.
  - `backend-chat-1002661910336-scaling` (G, T-1045…T-1056): per-chat лимиты ×1.5–×2
    (12 точек чтения → get_chat_param; ревью-фикс №5: _thread_limit/_cp_g/budget_tokens),
    _resolve_from_root +_cast_type_ok+isfinite; граница G-4 задокументирована. §24/§25.
- **Диагнозы раунда:** per-chat бюджеты — флаг переведён в limits_chat_budgets,
  для -1002661910336 OFF (KPI-риск F-15: глобальный ключ 25 req/сутки; восстановление —
  1 клик); лимиты ×1.5–×2 — thread ×2 через chat_thread_max_chars (R10.4-3-фикс),
  global ×1.5 через max_chars; каскад имён — username всем строкам, R16 сохранён,
  per-chat алиасы (точка 1) через build_alias_resolver.
- **Техдолг (кандидаты следующего раунда, KG `tech-debt-round10.4`):** R10.4-4
  (фото-обогащение всех 100 строк), R10.4-5 (409-модалка relations «Перезагрузить»),
  R10.4-6 (бэкфилы без optimistic-метки), R10.4-7 (граница G-4: direct RAG-cap/
  get_rag_facts глобальные — кандидат F-5), B-13 points 2-4 (per-chat алиасы не
  доходят до инжекта <user_relations>), HIGH-004 (полный LLM request/response-лог).
- **README.md:** тесты 4860, раздел раунда 10.4.

### Раунд 10.5 — финал (10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (918f675)

«Редизайн TMA по референсу Relume + гигиена репозитория». Единственная фича —
`tma-relume-redesign` (T-1066…T-1148, продолжает T-1065). HEAD == origin/master
== `c01ed72` (`918f675` + `c01ed72`, поверх `0bdf272`). **Статус: COMPLETED +
DEPLOYED.** Цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `918f675` feat(admin,web,chat,api): раунд 10.5 — редизайн
  TMA по референсу Relume: navbar, hubs, hash-роутинг, scope-switcher, key-history,
  матрица ролей, градиенты, Material Symbols (тесты 4962) — 49 файлов; `c01ed72`
  docs(plans): деплой-верификация раунда 10.5; push origin/master.
- **Тесты:** 4962 passed / 0 failed (baseline 10.4 = 4860, +102); `node --check
  web/app.js` clean; `git diff --check` чист; HTML tag-balance 0.
- **Реализация (Builder Pass 1–6):** токены/анимированные градиенты (T-1098);
  hash-router + нативный `Telegram.WebApp.BackButton` (Bot API 6.1+, single
  onClick, `goBack`=routeParent, deep-link OFF) (T-1099); scope-switcher
  GLOBAL/ЧАТ/ЛС + scopeEpoch (T-1127); 6-item navbar + 3 hubs + 15 экранов
  (T-1100…T-1112); key-availability + chart + `services/key_history.py` (ring 288
  + атомарный `var/status_key_history.json`, allowlist, 0 DDL, SQLite v8)
  (T-1128/1129/1132/1139/1140/1145/1148); матрица ролей + создание/rename/delete
  кроме superuser (T-1130/1131/1133/1141/1142); hardcode H1–H22 → безопасная
  аддитивная миграция `hot.get(key, literal)`; каталог **387/74/359**; font-subset
  ~13.2 КБ + self-host DOMPurify 3.4.15 fail-closed (T-1146/1147).
- **Ревью/Scanner:** @Reviewer REJECTED → fixes D1–D4 → APPROVED WITH MINOR →
  R1–R4 закрыты. @Scanner **CLEAN — 0 blocker / 0 major**; R10.5-1/-2/-4 закрыты;
  R10.5-3/-5/-6/-7 — техдолг (ARCH §25). Отчёт
  `plans/reports/round10.5_scanner_audit.md`.
- **Архитектура:** @Architect — §9 обновлён, §25 «по состоянию на раунд 10.5» +
  блок R10.5, новый §26 «Раунд 10.5» (последняя секция, ARCHITECTURE.md 320 строк).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward; `.env`
  без изменений; `systemctl restart admin_bot` → active (running);
  `/api/health` = 200; 0 startup-ошибок.
- **Архивация:** `tma-relume-redesign` → `plans/archive/tma-relume-redesign/`
  (**plans/archive/ — 27 папок**; plans/features/ — 6 активных F-1…F-6); backlog
  epic 10.5 закрыт. README обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест (T-1153), опциональный
  betterstack-401 fix, вердикт владельца.
- **Техдолг раунда (KG `tech-debt-round10.5`):** R10.5-3 (GET
  /api/status/key-history открыт любому авторизованному TMA-юзеру),
  R10.5-5 (rename_role race → 500 вместо 409), R10.5-6 (мёртвый setMenu,
  пре-существующий), R10.5-7 (sync `key_history.maybe_save()` I/O в async path).

### Раунд 10.6 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (6f91e8b + 4055434)

«Переработка IA TMA — единый navbar, 11 Модулей с реальными тумблерами, Настройки AI
из 7 подразделов, чистка PERMsoc». Единственная фича — `tma-ia-modules-rework`
(T-1155…T-1223; follow-up после round10.5-epic). HEAD == origin/master == `4055434`
(`6f91e8b` + `4055434`, поверх `be7b85b`). **Статус: COMPLETED + DEPLOYED.** HARD GATE
T-1156 пройден владельцем 11.09.2026 (GO на IA). Цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `6f91e8b` feat(admin,web,api,plans): раунд 10.6 — редизайн IA
  TMA: одна навигация, 11 модулей-тумблеров, RAG в память, тест провайдеров, чистка
  PERMsoc (тесты 5027) — **37 файлов**; `4055434` docs(plans): раунд 10.6 — деплой-
  верификация; push origin/master.
- **Тесты:** 5027 passed / 0 failed (baseline 10.5 = 4962; +65; Scanner зафиксировал
  5023 на момент аудита — до follow-up R10.6-1/-3). `node --check web/app.js` clean;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- **Реализация (@Builder, T-1157…T-1223):** sidebar/`MENU_ORDER`/`sidebarOpen`/
  `setMenu` удалены — только top navbar (6 пунктов: Статус/Как это работает/Модули/
  Настройки AI/Функции PERMsoc/Доступы и Роли), иконка + подпись под ней; модель
  скролла `.app-shell` flex-col + `.scroll-area` (desktop fullscreen ⛶ скроллится);
  «Модули» = 11 `mod_*` (Саммаризация, Прямые ответы, Фактчек, Поиск, Транскрипт
  голосовых и видео, Выжимка видео, Скачивание медиа, Веб-страницы, Диагностика, Сон,
  Ностальгия) с реальными toggle + модалка параметров; «Настройки AI» = 7 подразделов
  (LLM Провайдеры, Промпты, Память+RAG, Умный кэш, Имена, Отношения, Лор чата;
  «Лимиты» растворены); 5 master-флагов default ON
  (FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP) с реальными гейтами OFF→UNHANDLED
  (youtube — только summary-ветка); PERMsoc очищен — 10 миселённых параметров
  разнесены по модулям 5/6/7; Леха/Костик раздельно (`limits_alan`/`limits_kostik`,
  `reactions_kostik`); LLM Провайдеры — 9 блоков по модулям + `POST /api/llm/test`
  (global admin, rate-limit 5с, R17); `keys_youtube` → M6, `models_checkup`/
  `keys_betterstack` → M9; emoji→Material icons; эксклюзивный аккордеон «Доступы и роли».
- **Каталог (locked):** REGISTRY **392** / GROUPS **91** / Settings **364** /
  mapped **89** / `TAB_RULES` **19**. Расщепления: `limits_media`→4, `limits_persons`→2,
  `limits_youtube_web`→2, `limits_cooldowns`→растворена, `flags_modules`→7, `flags_chat_behavior`→3,
  `reactions_persons`→+`reactions_kostik`, `limits_chat_budgets`→+`limits_rag` (RAG→«Память»).
  **Ноль новых PG-DDL**; SQLite **v8**; порядок роутеров `bot.py` и `media/` не тронуты.
- **Ревью/Scanner:** @Reviewer REJECTED → fixes (BLOCKER nav-gating модулей, test-buttons,
  Sleep/Nostalgia-панели в модалке) → APPROVED WITH MINOR ISSUES → миноры закрыты
  (SSRF-префикс, search per-key, clear field). @Scanner **CLEAN — 0 blocker / 0 major**;
  R10.6-1 (дубль LLM-редакторов) и R10.6-3 (422-эхо `api_key`) закрыты; R10.6-2/-4/-5/-6 —
  техдолг (ARCH §25/§27). Отчёт `plans/reports/round10.6_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§27 «Раунд 10.6»** + обновлены
  §25 (техдолг R10.6-*), §9 (фронт/каталог/provider-блоки), §6 (таблица master-гейтов),
  §2 (гейты внутри существующих роутеров).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward до `4055434`;
  `.env` без изменений; `systemctl restart admin_bot` → `is-active=running`;
  `/api/health` = 200; 0 tracebacks.
- **Архивация:** `tma-ia-modules-rework` → `plans/archive/tma-ia-modules-rework/`
  (**plans/archive/ — 28 папок**; plans/features/ — 6 активных F-1…F-6). README
  обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест (desktop/Android WebView),
  опциональный betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.6`):** R10.6-2 (SSRF-периметр
  `POST /api/llm/test`: https для любого хоста без private-range-проверки),
  R10.6-4 (info — `media_share` вне списка блоков спеки), R10.6-5 (info — мёртвые
  записи `ICONS` после удаления вкладок), R10.6-6 (info — rate-limit расходуется
  до валидации блока).

### Раунд 10.7 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (7f3b790 + bb59476)

«UI/UX-багфиксы админ-минги». Единственная фича — `admin-ui-bugfixes-round107`
(spec @Architect T-1224). HEAD == origin/master == `bb59476` (`7f3b790` + `bb59476`,
поверх `2ccf558` — docs 10.6; прод до деплоя — `4055434`).
**Статус: COMPLETED + DEPLOYED.** FOLLOWS
round10.6-epic; цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `7f3b790` fix(admin,web): раунд 10.7 — UI/UX-багфиксы
  (scope*-computed, safe-area шапки, компактный юзер-блок, ellipsis ключей,
  gap-fill uptime, clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20)
  — **19 файлов**; `bb59476` docs(plans): деплой-верификация раунда 10.7;
  push origin/master.
- **Тесты:** 5042 passed / 0 failed (baseline 10.6 = 5027; +15). Каталог
  **392 / 91 / 364** (без изменений).
- **Реализация:** 1a `scope*` → computed (фикс `function () { [native code] }`);
  1b header safe-area padding; 1c компактный user block; 1d nav labels меньше/без
  per-letter wrap; 2a ellipsis таблицы ключей; 2b uptime gap-fill (непрерывная
  5-мин сетка, `down` для пустых слотов, `last_heartbeat` = last up else None);
  3a clipboard-ghost focusable (без `visibility:hidden`) + удалён; 3b фиксированные
  ширины лог-колонок + flex последней; 3c copy-on-row-click с feedback; R106-5
  dead ICONS удалены (26→20).
- **Ревью/Scanner:** @Reviewer REJECTED (`visibility:hidden` сломал
  `execCommand`-фолбэк) → fix → APPROVED WITH MINOR ISSUES → doc nit закрыт.
  @Scanner **CLEAN — 0 blocker / 0 major**; R10.7-1 (minor) + R10.7-2..5
  (info/nit) — техдолг; R10.6-5 ЗАКРЫТ. Отчёт
  `plans/reports/round10.7_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§28 «Раунд 10.7»** + обновлены
  §9/§25.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward до
  `7f3b790`; `.env` без изменений; `systemctl restart` → active; `/api/health` =
  200; 0 errors.
- **Архивация:** `admin-ui-bugfixes-round107` →
  `plans/archive/admin-ui-bugfixes-round107/` (**plans/archive/ — 29 папок**;
  plans/features/ — 6 активных F-1…F-6). README обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест исправленного UI, опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.7`):** R10.7-1 (minor — gap-fill
  помечает текущий незавершённый 5-мин слот `down` до ~60 с; §2b trade-off),
  R10.7-2 (info — `[-288:]` может отсечь единственный ранний `up`-бакет),
  R10.7-3 (info — `copiedTimer` не чистится при смене вкладки),
  R10.7-4 (info — `test_font_subset` проверяет JS, не cmap WOFF2),
  R10.7-5 (info/nit — неточная формулировка «context-loss» в `copyAllLogs`).

### Раунд 10.8 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (31d2ce7 + 976e335)

«Точечные UI-правки админ-минги». Единственная фича — `admin-ui-round108`
(spec @Architect + tasks @PM, T-1243…; продолжает 10.7). HEAD == origin/master ==
`976e335` (`31d2ce7` + `976e335`, поверх `636a75d` — docs-финал 10.7; прод до
деплоя — `7f3b790`). **Статус: COMPLETED + DEPLOYED.** FOLLOWS round10.7-epic;
цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `31d2ce7` feat(admin,web,plans): раунд 10.8 — переименование
  разделов, emoji→иконки, фикс логов на Android, окна «Доступов» (тесты 5076) —
  **30 файлов**; `976e335` docs(plans): раунд 10.8 — деплой-верификация; push origin/master.
- **Тесты:** 5076 passed / 0 failed (baseline 10.7 = 5042; +34; Scanner зафиксировал
  5073 на момент аудита — до follow-up R10.8-1/-5). Каталог **392 / 91 / 364**
  (mapped 89, `TAB_RULES` 19); `node --check web/app.js` clean;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- **Реализация:** (1) переименования разделов «Доступы»/«PERMsoc»/«ИИ»/«Справка»/«Сводка»;
  (2) emoji→Material-иконки, субсет шрифта 20→37 глифов (18 388 B), идемпотентность
  build-script по sha256(source_sha+ICON_NAMES), `build/icon_codepoints.json`,
  R10.7-4 cmap-тест; (3) Android-логи — шеврон только при `exc_text`, дата
  DD.MM HH:MM:SS, блочная раскладка без `<pre><span>` и жёстких ширин, `.log-msg`
  full-width, `copiedTimer` cleanup (R10.7-3); (4) три route-driven модалки
  `#/access/roles|local|admins`, «Администраторы»→«Роли», аккордеон удалён, «Мой доступ»/
  «Telegram ID админа» без изменений, BackButton/deep-link/Esc; (5) удалён внешний
  GLOBAL-бейдж; README-реструктуризация.
- **Ревью/Scanner:** @Reviewer APPROVED WITH MINOR ISSUES → doc-nit закрыт.
  @Scanner **CLEAN — 0 blocker / 0 major**; R10.8-1 (Esc) и R10.8-5 (APP_VERSION
  2.51.0 vs README 2.52.0 + кэш старого субсета без `?v=`) закрыты точечно follow-up;
  R10.8-2 (stale-комментарий `section`/ветка `openHubCard`), R10.8-3 (мёртвый
  `TABS.icon`/`visibleTabs`/`tabMat`), R10.8-4 (doc-drift backlog — закрыт архивацией)
  — техдолг; **R10.7-3 и R10.7-4 ЗАКРЫТЫ**. Отчёт `plans/reports/round10.8_scanner_audit.md`.
- **Архитектура/ADR:** @Architect — ARCHITECTURE.md **§29 «Раунд 10.8»** (+§1/§9/§25).
  ADR-001 — «Доступы» как route-driven модалки (hash — источник истины, `git revert`
  как откат); ADR-002 — паритет `ICONS`==`ICON_NAMES`↔cmap WOFF2 (PUA из GSUB,
  идемпотентность учитывает `ICON_NAMES`, fontTools/brotli build-time only).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward
  `7f3b790..31d2ce7`; `.env` без изменений; restart → active; `/api/health` = 200;
  шрифт `?v=2.52.0` → 200 (wOF2, 18 388 B); 0 ошибок.
- **Архивация:** `admin-ui-round108` → `plans/archive/admin-ui-round108/`
  (**plans/archive/ — 30 папок**; plans/features/ — 6 активных F-1…F-6). README
  счётчик 5073→5076; `APP_VERSION` 2.52.0.
- **Осталось вручную:** live Android smoke-тест **T-1254** (логи: ширина/дата/текст/
  отсутствие невидимого поля) и **T-1258** (три отдельных окна «Доступов»); опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.8`):** R10.8-2 (info — stale-комментарий/
  осиротевшая ветка `openHubCard`), R10.8-3 (info — мёртвый `TABS.icon`/`visibleTabs`/
  `tabMat`, pre-existing), R10.8-4 (info — doc-drift backlog, закрыт @PM); закрытые
  R10.8-1/-5; закрытые из 10.7 — R10.7-3/-4.

### Раунд 10.9 — финал (12.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d2d1215 + f928225)

«UI/UX-правки админ-минги — PERMsoc owner-блоки и под-флаг Славика, сохранение
скролла, переписанные описания, удаление «Тяжёлых фич»/перенос «Бюджета»,
dashboard-health, display-name, градиент». Единственная фича — `admin-ui-round109`
(spec @Architect + tasks @PM + ADR-109; T-1270…T-1314, продолжает T-1269).
HEAD == origin/master == `f928225` (`d2d1215` + `f928225`, поверх `51f308b` —
docs-финал 10.8; прод до деплоя — `31d2ce7`). **Статус: COMPLETED + DEPLOYED.**
FOLLOWS round10.8-epic; цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `d2d1215` feat(admin,web,plans): раунд 10.9 — PERMsoc-блоки,
  сохранение скролла, описания, доступность ключей по функциям, display-name,
  градиент (тесты 5105) — **34 файла**; `f928225` docs(plans): раунд 10.9 —
  деплой-верификация; push origin/master.
- **Тесты:** 5105 passed / 0 failed (baseline 10.8 = 5076; +29; 1 pre-existing
  warning + «closed 12 leaked aiosqlite connection(s)» — ресурс-предупреждение).
  Каталог **400 / 90 / 372 / mapped 88** (`TAB_RULES` 19, `CONFIG_TAB_TITLES` 19);
  `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` чист.
- **Реализация:** (п.1) PERMsoc — 4 сворачиваемых `<details class="owner-block">`
  (Славик/Оля/Мимикрия/Общее), в каждом ровно один рабочий тумблер
  (`PERMSOC_OWNER_BLOCKS`/`_permsocOwnerGroups`/`PERMSOC_TOGGLE_KEYS`; generic-bool
  дубли и master-карта удалены); backend — новый `flags.slavik_enabled`
  (`SLAVIK_ENABLED` default True), `reactions_persons` удалена,
  `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`,
  `TAB_PERMSOC` без persons; (п.3) `_preserveScroll` для `document.scrollingElement`
  И `.scroll-area` (restore в `$nextTick`) — скролл не прыгает при сохранении,
  вкл. fullscreen; (п.4) ВСЕ описания/титулы переписаны (plain ironic language,
  тест на 28 запрещённых жаргон-подстрок + AI-шаблон); (п.5) карточка «Тяжёлые
  фичи» удалена (per-chat dream/nostalgia/lore_auto остаются в «Сводке»);
  (п.6) «Бюджет фона» перенесён в «Сводку» (`loadBudgetInfo` из `loadOversight`;
  backend/endpoint не тронуты); (п.7.1) dashboard «Доступность ключей» — 4
  функциональные группы (main+fallback / транскрибация / саммаризация видео /
  эмбеддинги) + реальный health `probe_openai` (ok/error/timeout/unreachable/
  not_configured; `stt_groq` → `POST /audio/transcriptions` multipart WAV, таймаут
  5с; кэш per `module_id`: 2xx 60с, ошибки 10с, stale-200 не отдаётся), старый
  блок → «История доступности ключей»; (п.7.2) 7 `models.*_display_name` первым
  полем каждого провайдер-блока, ширина формы `max-w-3xl`; (п.8) градиент быстрее
  (`--grad-speed:14s`, `grad-drift 18s`).
- **ADR-109 (Accepted @Architect 12.09.2026):** ADR-109-1 — display-name как 7
  новых `ParamSpec` (`models.*_display_name`, Settings, глобальные); ADR-109-3 —
  health реальным POST вместо `GET /models` (`probe_openai` chat/embeddings/stt,
  кэш per `module_id`); ADR-109-4 — `SLAVIK_ENABLED` для независимого тумблера
  Славика; ADR-109-5 — «Бюджет фона» → «Сводка».
- **Ревью/Scanner:** @Reviewer REJECTED (1 Critical + 1 High + 2 Medium + 3 Low) →
  фиксы (STT probe, AI-описания, титулы, fullscreen-скролл, dead code, owner-блоки,
  JS-единицы) → APPROVED WITH MINOR ISSUES → follow-ups закрыты. @Scanner
  **CLEAN — 0 blocker / 0 major / 0 medium**; 3 low R10.9-1/-2/-3 + 3 info
  R10.9-4/-5/-6; R10.9-6 закрыт архивацией. Отчёт
  `plans/reports/round10.9_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§30 «Раунд 10.9»** (+§1/§9/§25).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward
  `31d2ce7..d2d1215`; `.env` без изменений; restart → active; `/api/health` = 200;
  0 ошибок.
- **Архивация:** `admin-ui-round109` → `plans/archive/admin-ui-round109/`
  (spec.md + tasks.md + ADR-109.md) (**plans/archive/ — 31 папка**;
  plans/features/ — 6 активных F-1…F-6). README счётчик 5105; `APP_VERSION` 2.53.0.
- **Осталось вручную:** live Android smoke — **T-1277** (owner-блоки/тумблеры
  PERMsoc), **T-1290** (скролл при сохранении), **T-1292/T-1294**
  (dashboard-health/«Доступность ключей»), **T-1302** (форма провайдеров/
  display-name), **T-1305** (градиент); реальное Android-устройство недоступно
  @Builder, статически покрыто `tests/test_webapp_round109_ui.py` + JS-юниты;
  опциональный betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.9`):** R10.9-1 (low — `model_source`
  запасных/эмбеддинг-записей снова `"code"` при конфиге, metadata-only),
  R10.9-2 (low — эмбеддинг-фоллбэки читаются из `settings`, не через
  `hot`/`_resolve`; `emb_fallback*` исчезают без env-ключа), R10.9-3 (low —
  устаревший docstring `status_service.py`), R10.9-4 (info — кэш health по
  `module_id` не инвалидируется при смене base_url/key/model ≤60с), R10.9-5
  (info — docstring `_LLM_BLOCKS` без `transcribe_groq`; `ConnectTimeout` →
  «timeout»); R10.9-6 закрыт архивацией; R10.8-2/-3 остаются открытыми.
- **⚠️ Вне скоупа:** пункт 2 исходного ТЗ — инфраструктура локального IDE
  владельца (не часть бота); в репозитории и в графе не фиксируется.

### Раунд 10.10 — финал (12.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d082800 + a477747 + 772db08)

«UI/UX-правки админ-минги — шапка в fullscreen, мобильный график доступности
ключей, реальные значения «Провайдеров», ЛС heavy-modules OFF, «Роли» с
аватарами». Единственная фича — `admin-ui-round1010` (spec @Architect + tasks @PM +
ADR-1010-1/2/3; T-1315…T-1328, продолжает 10.9). HEAD == origin/master == `772db08`
(`d082800` + `a477747` + `772db08`, поверх `da85b60` — docs memory-sync 10.9; прод
до деплоя — `d2d1215`). **Статус: COMPLETED + DEPLOYED.** FOLLOWS round10.9-epic;
цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `d082800` fix(admin,web,api,scripts,plans): раунд 10.10 —
  fullscreen safe-area, mobile key-chart, реальные значения провайдеров, ЛС
  heavy-modules OFF, роли с аватарами (тесты 5144); `a477747` fix(scripts): раунд
  10.10 — standalone-запуск `disable_dm_heavy_modules` (sys.path bootstrap) +
  регресс-тест CLI (тесты 5145); `772db08` docs(plans): раунд 10.10 —
  деплой-верификация; push origin/master.
- **Тесты:** 5145 passed / 1 skipped / 0 failed (baseline 10.9 = 5105; Scanner
  зафиксировал 5140 + 1 skipped на момент аудита — до CLI-регресс-теста).
  `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` чист. Каталог **400 / 90 / 372 / mapped 88** (`TAB_RULES` 19,
  `CONFIG_TAB_TITLES` 19) — без изменений; ноль новых PG-DDL; SQLite v8;
  `bot.py` router order, `media/` и `.env` не тронуты.
- **Реализация:** (п.1) fullscreen-паддинг шапки — `.fullscreen-mode
  header.header-sticky` padding `calc(base + max(env(safe-area-inset-*),
  var(--tg-content-safe-area-inset-*), var(--tg-safe-area-inset-*)))` —
  профиль-блок не перекрывается нативными кнопками Telegram; 10.7 (ширина) и 10.9
  (`.scroll-area`) не тронуты; (п.2) мобильный график key-availability —
  RENDER-фикс: окно строится ОТ КОНЦА (`minStart`, cap ≤ `MAX_HISTORY_POINTS`,
  без `break`/`slice`) — новейшие сэмплы больше не отбрасываются; дорожки на
  провайдера + временная сетка `SAMPLE_BUCKET=300` (min 12 бакетов), динамическая
  высота, `pointRadius:3` при 1 сэмпле, пропуск = `null` + `spanGaps:false`;
  контракт `/api/status/key-history` (`api_payload`) НЕ изменён; (п.3)
  «Провайдеры» показывают реальные значения — `:value="blockFieldValue(f)"` +
  `@input` вместо `v-model`; `blockFieldValue` возвращает `''` для пустого
  черновика и значение `configItems` при отсутствии черновика, секреты
  (`type==='object'`) → `''` (placeholder-маска); `blockDrafts`/`blockResults`
  сброшены в `loadConfig` и `setActiveChat`; `saveBlock`/MINOR-3 (`null`=не
  трогать, `''`=очистить) не менялись; (п.4) ЛС heavy-modules OFF; (п.5) «Роли» —
  аватар + ник + мелкий серый ID, backend `global_user_display_info` (RAM-TTL 1ч,
  `get_chat(user_id)`→first/last→username, фото через `getUserProfilePhotos`;
  транзиентные `TelegramRetryAfter`/`TelegramNetworkError` НЕ в негатив-кэш,
  fail-open), `/api/admins` обогащает КОПИИ под `requires_permission("access")`,
  `Semaphore(5)`+`gather`; фронт `admin.avatarUrl` (blob через прокси, `@error`),
  `adminInitial`, `display_name||username`, ID `text-[10px] text-gray-500
  font-mono`; ширины `w-36→w-24`, ID-инпут `flex-1 min-w-0`, кнопка `shrink-0`.
- **ADR-1010:** ADR-1010-1 — ЛС heavy-modules OFF (`gates.dream/nostalgia=false` +
  4 override=false; `ensure_scope_profile(dm=True)` DM-дефолты;
  `scripts/disable_dm_heavy_modules.py` dry-run/`--apply`/`--restore`/`--chat-id`/
  snapshot, без DDL); ADR-1010-2 — key-chart render-only, дорожки + временная
  сетка 300с, контракт `api_payload` не меняется; ADR-1010-3 —
  `global_user_display_info(user_id)`, RAM-TTL 1ч, fail-open, обогащение
  `/api/admins`, фронт аватар/инициалы + мелкий серый ID.
- **Ревью/Scanner:** @Reviewer REJECTED (график отбрасывал новейшие данные) →
  фикс → APPROVED WITH MINOR ISSUES → restore exit-code Low закрыт. @Scanner
  **0 blocker / 0 major / 0 medium**; low R10.10-1/-2/-3 + info R10.10-4/-5
  (большинство точечно исправлено); отчёт
  `plans/reports/round10.10_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§31 «Раунд 10.10»** (+§3/§9/§25).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward; `.env` без
  изменений; `systemctl restart` → active (running); `/api/health` = 200; 0 ошибок.
- **DM data-run (прод, 12.09.2026):** `scripts/disable_dm_heavy_modules.py`
  применён — **1 активный ЛС изменён** (сон/ностальгия/саммаризация OFF),
  снапшот `var/dm_modules_off_snapshot_20260911T201219Z.json`; повторный dry-run —
  **0 изменений** (идемпотентно). F-14 gate (`bot.py flags.summary_enabled`) не
  тронут.
- **Архивация:** `admin-ui-round1010` → `plans/archive/admin-ui-round1010/`
  (spec.md + tasks.md + ADR-1010-1/2/3.md) (**plans/archive/ — 32 папки**;
  plans/features/ — 6 активных F-1…F-6). README счётчик 5145; `APP_VERSION` 2.54.0.
- **Осталось вручную:** live Android QA — **T-1317** (шапка fullscreen),
  **T-1320/T-1323/T-1332** (мобильный график/провайдеры/роли), UI spot-check
  DM-тумблеров OFF (**T-1328**); реальное Android-устройство недоступно @Builder,
  статически покрыто `tests/test_webapp_round1010_ui.py` +
  `tests/test_scripts_round1010_dm_off.py` + JS-юниты; опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.10`):** R10.10-1 (low — скрипт DM:
  `total`/`noop`/dry-run-count игнорируют `--chat-id`; операторский вывод),
  R10.10-2 (low — `meta.note` перезаписывается и не откатывается snapshot'ом),
  R10.10-3 (low — `renderKeyHistoryChart` ранний return без `destroy()` старого
  Chart.js), R10.10-4 (info — `loadAdmins` без `avatarSkipped`/`.catch`, повторные
  blob-запросы), R10.10-5 (info — `adminInitial` дублирует `avatarInitial`,
  ветка `admin.username` недостижима).
- **⚠️ Вне скоупа:** П.6 ТЗ — Headroom saved-tokens stats (внешняя
  IDE-инфраструктура владельца, не часть бота); в репозитории и в графе НЕ
  фиксируется как сущность.

### Раунд 10.11 — финал (12.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (3624789 + cbe6ea5)

«Рефакторинг раздела LLM Провайдеры + проверка сохранённого ключа +
непрерывный график доступности + plain-language отчёт о памяти/сне/ностальгии/
лоре». Единственная фича — `llm-providers-refactor-round1011` (spec @Architect +
tasks @PM + ADR-1011-1/2/3; T-1340…T-1381, продолжает T-1339 — финал 10.10).
HEAD == origin/master == `cbe6ea5` (`3624789` + `cbe6ea5`, поверх `ec5dd1f` —
docs memory-sync 10.10; прод до деплоя — `772db08` = задеплоенный 10.10).
**Статус: COMPLETED + DEPLOYED.** FOLLOWS round10.10-epic; цикл раунда
полностью закрыт (Step 10).

- **Коммиты (master):** `3624789` feat(admin,web,api,scripts,plans): раунд 10.11 —
  рефакторинг «LLM Провайдеры», проверка сохранённого ключа, график доступности,
  отчёт по памяти (тесты 5172) — **28 файлов**; `cbe6ea5` docs(plans): раунд 10.11 —
  деплой-верификация; push origin/master.
- **Тесты:** 5172 passed / 0 failed (baseline 10.10 = 5145; Scanner зафиксировал
  5168 на момент аудита — до follow-up R10.11-1/-2/-3). `node --check web/app.js`
  clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист;
  R17-скан чист.
- **Пункт 1 (ADR-1011-1):** `POST /api/llm/test` при пустом/пробельном `api_key`
  резолвит СОХРАНЁННЫЙ ключ блока server-side — `_BLOCK_SAVED_KEY` (все сетевые
  блоки + media_share), `_saved_api_key` (`hot.get(pg_key, settings_default)`,
  ошибка → `""`); явный draft из UI приоритетнее (UI шлёт `api_key` только если
  truthy); резолв внутренний — ключ не попадает в `_result` (ok/status/latency/
  model/error) и не логируется, тело ошибки чистится `sanitize_error`; UI — поле
  остаётся пустым, hint «Ключ сохранён (••••last4)» через маску `{configured,last4}`.
  Работает без повторного ввода ключа.
- **Пункт 2.1–2.5:** nav-icons крупнее/плотнее (`nav-icon 22px`, `gap .15rem`,
  `min-width 60px`) + pinned профиль (`shrink-0` + `whitespace-nowrap`);
  `.hub-head`/`.hub-grid` `max-width:64rem` + `justify-self:center`; две зоны
  «Подключения»/«Расширенные настройки» — `providerConnectionBlocks`/
  `providerAdvancedBlocks` **computed** (НЕ methods; фикс ревьюера), зона advanced
  через `<component :is>` + `<summary>`, на прочих вкладках `div`; embeddings —
  один блок с 3 подблоками (`embeddings.subBlocks = [main, f1, f2]`, у каждого
  Base URL+Модель+Ключ+«Проверить»; `providerCoveredKeys` рекурсивно покрывает
  subBlocks — нет дублей в generic); video fallback строго после
  `video_summary_openrouter` (kind=chat); media_share → advanced + note,
  `search_keys`/`llm_guard` тоже advanced внизу; технический хаос ниже зоны
  «Подключения».
- **Пункт 2.3 — каталог-дельта (ADR-1011-2, sanctioned):** 4 infra
  embed-fallback записи перенесены в каталог — `models.embedding_fallback_base_url`/
  `_model` → category `models`/group `models_embeddings`;
  `keys.embedding_fallback_api_key`/`_2` → category `keys`/group `keys_llm`,
  `secret=True`; `llm_client`/`status_service` читают через `hot.get` (прежние
  дефолты — паритет). Счётчики БЕЗ роста: REGISTRY **400** / GROUPS **90** /
  Settings **372** / mapped **88** / `TAB_RULES` 19 / `CONFIG_TAB_TITLES` 19;
  `categorized` 372→**376** (models 40→42, keys 13→15), `infra` 28→**24**.
- **Пункт 3 (ADR-1011-3):** dashboard key-history — непрерывный график:
  точки `{x: ts*1000, y: lane|null}`, `spanGaps:true`, `stepped:true`,
  ось X `type:'linear'` + `min/max` (`xMin`/`xMax`) + `ticks.callback` HH:MM,
  `parsing:false`; `type:'time'` отсутствует (без date-adapter); серверный
  контракт `GET /api/status/key-history` (`api_payload`, `services/key_history.py`)
  НЕ изменён. R10.10-3 (ранний return без destroy) не регрессирован.
- **Пункт 4 (docs-only, без кода):** `plans/docs/memory_sleep_nostalgia_lore_report.md`
  — подробный plain-language отчёт: память (L1/L2/L3/GraphRAG), сон/синтез снов,
  ностальгия, чат-лор, тайминги/лимиты, сборка контекста; 6 тем, каждая цифра с
  `file:line`; принят @PM (T-1342).
- **Ревью/Scanner:** @Reviewer REJECTED (CRITICAL: zone helpers в methods, не
  computed → блоки провайдеров исчезали) → фикс (computed) + жёсткий тест →
  APPROVED WITH MINOR ISSUES. @Scanner **CLEAN — 0 blocker / 0 major / 0 medium**;
  3 low R10.11-1/-2/-3 закрыты follow-up; 3 info R10.11-4/-5/-6 → техдолг; отчёт
  `plans/reports/round10.11_scanner_audit.md`.
- **Архитектура/ADR:** @Architect — ARCHITECTURE.md **§32 «Раунд 10.11»**
  (+§5/§9/§25). ADR-1011-1 — saved-key probe (R17-safe); ADR-1011-2 — embeddings
  one block + sanctioned Δ каталога без роста счётчиков; ADR-1011-3 — key-history
  chart на линейной оси (без `type:'time'`), контракт `api_payload` неизменен.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward
  `772db08..3624789`; миграция `python scripts/migrate_env_to_pg.py
  --only-category models,keys` → **created=5 / skipped=48** (4 embed-фоллбэка
  резолвятся); `systemctl restart` → active; `/api/health` = 200; 0 ошибок.
- **Архивация:** `llm-providers-refactor-round1011` →
  `plans/archive/llm-providers-refactor-round1011/` (spec.md + tasks.md +
  ADR-1011-1/2/3.md) (**plans/archive/ — 33 папки**; plans/features/ — 6 активных
  F-1…F-6). README счётчик 5172; `APP_VERSION` 2.55.0.
- **Осталось вручную:** live Android/Telegram QA — **T-1377** (поле ключа +
  «Проверить» без повторного ввода; навигация/профиль/сетка; две зоны
  «Провайдеры»; эмбеддинги (3 подблока); видео-фоллбэк; media-share внизу; график
  доступности ключей). Статически покрыто `tests/test_webapp_round1011_ui.py` +
  JS-юнитами; опциональный betterstack-401 fix. Не блокирует закрытие цикла.
- **⚠️ Наблюдение:** pre-restart PID имел 401 к `apinet.cloud` (возможно невалидный
  primary token) — стоит проверить.
- **Техдолг раунда (KG `tech-debt-round10.11`):** R10.11-1 (low, закрыта — вложенные
  `<details>` делят один localStorage-ключ `adminbot.expand:llm_providers`),
  R10.11-2 (low, закрыта — расхождение `embedding_fallback_model` рантайм vs
  карточка статуса при явной очистке), R10.11-3 (low, закрыта — устаревшие
  подсказки «править в .env» для embed-фоллбэк-ключей), R10.11-4 (info, открыта —
  probe прикрепляет сохранённый секрет к caller-supplied `base_url`; hardening:
  резолвить `base_url` из конфига блока/allowlist), R10.11-5 (info, открыта —
  мёртвая ветка `destroy()` в `renderKeyHistoryChart`), R10.11-6 (info, открыта —
  нет headless-теста фактического рендера `spanGaps:true`/`parsing:false`).
- **⚠️ Вне скоупа:** Headroom — внешняя IDE-инфраструктура владельца, не часть
  бота; в репозитории и в графе как сущность НЕ фиксируется.

## Безопасность сервера (fail2ban / ufw / SSH-харденинг, 09.09.2026)

Применено DevOps на 198.46.175.136 (Ubuntu 24.04.4, OpenSSH 9.6p1),
research-based (референсы: fail2ban issues #3785/#3812 для OpenSSH 9.8 —
неактуально на 9.6p1, работает; ufw порядок правил). **Активно.**

- **fail2ban 1.0.2** (`/etc/fail2ban/jail.local`): backend=systemd,
  banaction=nftables, bantime 1h + increment до 1w; jail `sshd`: maxretry=3,
  bantime=24h, findtime=10m, journalmatch=_SYSTEMD_UNIT=ssh.service +
  _COMM=sshd + _SYSTEMD_UNIT=ssh.socket; jail `recidive`: 1w/1d/3.
  Живой бан подтверждён: **176.53.159.197** (nft f2b-table); фильтр — ~65k
  матчей; btmp сокращён (было 44M/3д).
- **ufw:** default deny incoming; 22/tcp LIMIT IN; 80/443 ALLOW. Снаружи
  открыты только 22/80/443; закрыты: 4416 (bgutil POT), 8000, 8081, 9000,
  5432, 2019, 10808 (проверено извне — timeout).
- **SSH `/etc/ssh/sshd_config.d/00-hardening.conf`:** PermitRootLogin no,
  MaxAuthTries 3, LoginGraceTime 20, MaxStartups 10:30:60, MaxSessions 3,
  ClientAliveInterval 300/2, X11Forwarding no, LogLevel VERBOSE, DebianBanner no;
  `sshd -t` + reload OK. **Password auth сохранена** (требование владельца),
  порт 22 не менялся. Lockout не произошёл.
- **Follow-up (решения владельца):** миграция на SSH-ключи (key migration
  proposal); добавить IP владельца в `ignoreip`, если он статический;
  CrowdSec как альтернатива fail2ban; перенос `migrate_history` (1.1G) вне
  диска.

## Свежие архивы (plans/archive/ — 137 папок)

> **Раунд 10.25 (20–21.09.2026):** `f0-config-bugfixes-round1025` (F0, Wave 0, `spec.md` + 4 ADR
> `adr-1025-2…-5` + `tasks.md` T-2410…T-2455, деплой `3a91c84`, §52), `hotfix-media-tma-round1025`
> (внеплановый ASAP-хотфикс, `spec.md` + `adr-1025-6-bot-api-local-mode.md` + `tasks.md` T-2456…T-2481,
> commits `8b16c4a`+`ee23e47`+docs `65e39fb`, §53; ⏳ live-гейт владельца T-2463/T-2472/T-2479),
> `ia-shell-navigation-round1025` (F1, Wave 1, `spec.md` + `adr-1025-1-ia-v2.md` + `tasks.md`,
> деплой `fe0f7bb`, pytest 7996/0, §54) и `p0-fix-render-media-paths-round1025`
> (P0-фикс после F1, `tasks.md` FIX 1–4, деплой `fea2daa`, pytest 8003/0, §54.1;
> ⏳ live-гейт владельца: видео/ГС/аватары + разделы TMA).
> `plans/features/` — 16 папок (6 backlog + 10 фич раунда 10.25, F2–F11).

> **Раунд 10.18 (15.09.2026, HEAD `16a8c0b`, §39)** — 7 фич заархивированы:
> `betterstack-us-region-401` (F1, ADR-1018-1), `settings-worker-sync` (F7, ADR-1018-7),
> `sleep-manual-cascade-badges` (F2, ADR-1018-2), `graph-density-scoring-stoplist` (F3, ADR-1018-3, SQLite v10),
> `graph-physics-stabilization` (F4, ADR-1018-4), `metafact-penalty-extractor-prompt` (F5, ADR-1018-5),
> `role-matrix-settings-actualization` (F6, ADR-1018-6). Каждый — `spec.md` + `tasks.md` + ADR.
> `plans/features/` — 6 активных (F-1…F-6); новых фича-флагов нет; каталог 436/406/411/90/88/19.

- `anti-echo-self-reply-round1014` — **Раунд 10.14, 13.09.2026** (F1, T-1477…T-1486 + ADR-1014-2): origin `bot_self_reply` (11-й, честный карантин) + rebuild `graph_facts` + **SQLite v9**; вес `limits.graph_fact_weight_bot`=0.2 (importance=2), LLM-экстрактор `services/self_reflection.py` (роль `reflection`, fail-open), `_SELF_ECHO_INSTRUCTION`, карантин self из Сна/золотых/компакции/`graph_stats`; флаг `flags.bot_self_awareness_enabled` **ON**)
- `persona-storage-core-round1014` — **Раунд 10.14, 13.09.2026** (F2, T-1487…T-1497 + ADR-1014-1): **PG `personas`/`persona_traits`** (+`persona_state`), `services/bot_persona.py` (scope per-chat→global→empty, `<Persona>`-блок, `_NO_AI_DISCLOSURE_BLOCK`), traits пишет DeepSleepWorker, API `GET/PUT/DELETE /api/persona` + `/api/persona/health`; флаг `flags.persona_enabled` **ON**)
- `persona-ui-tab-round1014` — **Раунд 10.14, 13.09.2026** (F3, T-1498…T-1504): special-screen `#/ai/persona` (карточка «Личность» в Hub «ИИ»), форма 3 поля + чекбокс «Осознаёт себя ИИ», scope-сброс, RBAC `edit_persona`; Δ каталога = 0)
- `persona-traits-ribbon-round1014` — **Раунд 10.14, 13.09.2026** (F4, T-1505…T-1510): 3-я лента «Эволюция характера» в «Мониторинге Интеллекта» (`_ribbonLoop`, сетка 3→1) + панель метрик Личности в «Сводке» `#/oversight` (`/api/persona/health`))
- `settings-persistence-audit-round1014` — **Раунд 10.14, 13.09.2026** (F5, T-1511…T-1525): инвентаризация всех изменяемых параметров + аудит write-path/scope/restart, закрыт R10.9-4 (health-кэш); `report.md` + `inventory.tsv` в архиве)
- `help-guide-integration-round1014` — **Раунд 10.14, 13.09.2026** (F6, T-1526…T-1534): гайд в PG `content.intelligence_guide` + второй редактируемый блок «Гайд по возможностям» в «Справке» (Markdown-редактор + DOMPurify 3.4.15 self-host), идемпотентный сид; API `GET/POST /api/info/guide`)
- `status-layout-reorder-round1014` — **Раунд 10.14, 13.09.2026** (F7, T-1535…T-1540): порядок «Статуса» Сводка → Сердцебиение → Бот → Сервер → Мониторинг Интеллекта → Доступность ключей → История; Δ=0)
- `self-reflection-llm-provider-round1014` — **Раунд 10.14, 13.09.2026** (F8, T-1541…T-1548): роль `reflection` → slug `intel_reflection` (`generate_worker`), 4 PG-ключа (models/keys), probe `intel_reflection_main`, третий parent-блок «LLM для саморефлексии (Экстрактор сути)», фоллбэк на основную модель)
- `cognition-4d-memory-round1013` — **Раунд 10.13, 13.09.2026** (F1, T-1417…T-1423 + ADR-1013-3): 4D-память — префикс `[ММ.ГГГГ | Автор: ]` (автор=target_user), метка `(Внимание: возможно устарело)` для фактов >6 мес (`limits.rag_stale_after_days`), временная группировка фактов в DreamWorker; канон dream/lore — PREV-снапшот + байт-тесты, `PROMPT_MIGRATIONS` не трогаем)
- `cognition-belief-decay-round1013` — **Раунд 10.13, 13.09.2026** (F2, T-1424…T-1433): Belief Decay (−0.1/мес без подкрепления >6 мес) + архив `graph_facts.status='archived_belief'`; Resurrection — векторный резонанс (пенальти −0.3, порог 0.78), Сон-Реаниматор, граф-активация (связки 2–3 узлов в L1); DDL-free, флаг `flags.belief_decay_enabled` OFF)
- `cognition-deep-sleep-round1013` — **Раунд 10.13, 13.09.2026** (F3, T-1434…T-1442 + ADR-1013-1): «Глубокий сон» — после обычного сна, «Поиск по якорям» (свежие beliefs + 12ч-выжимка → RAG) → синтез «Мост времени» → парадигмы (`origin='derived_belief'`, `belief_meta.type='paradigm'`, weight 0.55); роутер `LLMClient.generate_worker` (роли intel_history/intel_bg); флаг `flags.deep_sleep_enabled` OFF)
- `cognition-llm-providers-round1013` — **Раунд 10.13, 13.09.2026** (F4, T-1443…T-1447 + ADR-1013-1): 2 provider-блока `intel_history` / `intel_bg` (parent+subBlocks, `providerCoveredKeys`, `_BLOCK_SAVED_KEY`), ключи `models.intel_<role>_*` + `keys.intel_<role>_api_key`, фоллбэк на `models.llm_*`/`keys.llm_api_key`; R17 `{configured,last4}`)
- `cognition-dashboard-round1013` — **Раунд 10.13, 13.09.2026** (F5, T-1448…T-1458 + ADR-1013-2): дашборд «Осмысление» на «Статусе» (2 бегущие строки, бейджи фаз) + виджет «Интеллект и Память» в «Сводке» (пульс, прогресс-бары, метрики БД, Timeline); граф vis-network standalone UMD self-host lazy-load (nodes/edges 120/240, polling 15с); аддитивные read-API)
- `cognition-ekg-logs-bugfix-round1013` — **Раунд 10.13, 13.09.2026** (F6, T-1459…T-1464): SVG-EKG Heartbeat (Load/CPU/RAM, спокойный зелёный ↔ оранжево-красный), старый линейный аптайм-график удалён; багфикс «Логи» — серверный комбинированный тег ERROR+WARNING + дефолт фильтра при открытии)
- `cognition-user-guide-round1013` — **Раунд 10.13, 13.09.2026** (F7, T-1465…T-1467): `plans/docs/intelligence_user_guide.md` — простыми словами, без аббревиатур, ироничный тон; задел под раздел «Справка» + ссылка из README; APP_VERSION 2.57.0)
- `cognition-irony-dossier-round1013` — **Раунд 10.13, 13.09.2026** (F8, T-1468…T-1476 + ADR-1013-3): иронический фильтр в промпте Досье (LoreWorker + `build_persona_card`), мемы `graph_facts.status='chat_meme'`, `real_facts`=confirmed+target_user, блоки [Факты]/[Локальные мемы/Ярлыки]; флаг `flags.irony_filter_enabled` OFF)
- `providers-kostik-round1012` — **Раунд 10.12, 13.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-1012-1, FOLLOWS round10.11-epic): развязка эмбеддингов (`models.embedding_base_url`=apinet.cloud/v1, `keys.embedding_api_key`, отдельный httpx-кэш `_embed_client`) от прямых ответов (`models.llm_base_url`=nano-gpt.com/api/v1), фикс 422 сохранения глобальных ключей (`saveConfigItem`/`saveBlock`/`saveKeyItem`), объединённые блоки подключений с display-name, JSON-список фраз Костика (`reactions.kostik_replies`, 14 фраз) + `flags.kostik_enabled` + owner-блок PERMsoc; каталог 405/90/377/mapped 88/categorized 381; тесты 5211 passed / 0 failed; §33)
- `llm-providers-refactor-round1011` — **Раунд 10.11, 12.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-1011-1/2/3, T-1340…T-1381): saved-key probe `/api/llm/test` без повторного ввода (R17-safe, `{configured,last4}`), рефакторинг «LLM Провайдеры» (nav-icons 22px + pinned профиль, две зоны «Подключения»/«Расширенные» computed, embeddings 3 подблока, video-fallback выше, media-share/теххаос внизу), непрерывный key-history chart (`spanGaps`+`stepped`, linear-ось, `parsing:false`), docs-отчёт `plans/docs/memory_sleep_nostalgia_lore_report.md`; каталог 400/90/372/mapped 88, `categorized` 376 (sanctioned Δ, infra 28→24); тесты 5172 passed / 0 failed; §32)
- `admin-ui-round1010` — **Раунд 10.10, 12.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-1010-1/2/3, T-1315…T-1328: fullscreen safe-area паддинг шапки, мобильный график доступности ключей (окно от конца, дорожки + 300с сетка), реальные значения полей «Провайдеров» (`blockFieldValue`), ЛС heavy-modules OFF (`disable_dm_heavy_modules.py`, прод data-run 1 ЛС), «Роли» с аватаром+ником+мелким серым ID; каталог 400/90/372/mapped 88; тесты 5145 passed / 1 skipped; §31)
- `admin-ui-round109` — **Раунд 10.9, 12.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-109; T-1270…T-1314: PERMsoc owner-блоки + `flags.slavik_enabled`, сохранение скролла (`_preserveScroll`), переписанные описания/титулы, удаление «Тяжёлых фич», «Бюджет фона»→«Сводка», dashboard «Доступность ключей» (4 группы) + реальный health `probe_openai`, 7 `models.*_display_name`, `max-w-3xl`, градиент 14s/18s; каталог 400/90/372/mapped 88; тесты 5105; §30)
- `admin-ui-round108` — **Раунд 10.8, 11.09.2026** (единственная фича, spec @Architect + tasks @PM, T-1243…: переименование разделов, emoji→Material-иконки (субсет 20→37, 18 388 B), фикс логов на Android, route-driven окна «Доступов», README; тесты 5076; §29; ADR-001-access-windows-modal + ADR-002-icon-subset-parity)
- `admin-ui-bugfixes-round107` — **Раунд 10.7, 11.09.2026** (единственная фича, spec T-1224: UI/UX-багфиксы админ-минги — scope*-computed, safe-area шапки, компактный юзер-блок, ellipsis ключей, uptime gap-fill, clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20; тесты 5042; §28)
- `tma-ia-modules-rework` — **Раунд 10.6, 11.09.2026** (единственная фича, T-1155…T-1223: IA-ребейлд TMA — единый navbar, 11 Модулей-тумблеров, Настройки AI (7) + RAG→Память, чистый PERMsoc, Леха/Костик раздельно, provider-блоки + `POST /api/llm/test`; каталог 392/91/364/mapped 89; тесты 5027; §27)
- `tma-relume-redesign` — **Раунд 10.5, 10.09.2026** (единственная фича, T-1066…T-1148: полный редизайн TMA по Relume — navbar/hubs/hash-роутинг/scope-switcher/key-history/матрица ролей/градиенты/Material Symbols; тесты 4962; §26)
- `frontend-advanced-collapse-default` — **Раунд 10.4, 10.09.2026** (D, T-1018…T-1023: аккордеоны «Расширенные» свёрнуты по умолчанию, AC-B1-тест; §24)
- `frontend-memory-sleep-nostalgia` — **Раунд 10.4, 10.09.2026** (C, T-1006…T-1017: «Память» + вкладки «Сон»/«Ностальгия», progressive-разметка; §24)
- `frontend-llm-providers-layout` — **Раунд 10.4, 10.09.2026** (E, T-1024…T-1032: LLM Провайдеры — 4 секции: модели→ключи→фолбэк→расширенные; §24)
- `frontend-reorg-modules-reactions` — **Раунд 10.4, 10.09.2026** (A, T-974…T-989: «Функции PERMsoc» 17 групп (девиансия D-A1), «Модули», лор-настройки; §24)
- `frontend-limits-temperature-budgets` — **Раунд 10.4, 10.09.2026** (B, T-990…T-1005: бюджеты per-чат (флаг + бэкфил), select-температура, «Имена людей» + build_alias_resolver; §24)
- `frontend-relations-participants` — **Раунд 10.4, 10.09.2026** (F, T-1033…T-1044: вкладка «Участники и отношения», перенос блока участников; §24)
- `backend-relations-nickname` — **Раунд 10.4, 10.09.2026** (H, T-1057…T-1065: username для всех строк каскада имён, Semaphore(5), фото топ-50, R16; §24)
- `backend-chat-1002661910336-scaling` — **Раунд 10.4, 10.09.2026** (G, T-1045…T-1056: per-chat лимиты ×1.5–×2 (15 override, бэкфил), _resolve_from_root-харденинг, граница G-4; §24/§25)
- `tma-chat-selector-fixes` — **Раунд 10.3, 09–10.09.2026** (F-13, T-925…T-944: единый селектор чата, удаление ✕/пикера, фикс пустых вкладок, z-index 45; §23)
- `dm-user-settings` — **Раунд 10.3, 09–10.09.2026** (F-14, T-945…T-964: ЛС-настройки вариант A, саммари default-off; §23)
- `direct-sandbox-budget-investigation` — **Раунд 10.3, 09–10.09.2026** (F-15, T-965…T-973: прод-диагностика sandbox budget + graphrag JSON, фиксы; §23/§24)
- `multi-chat-rbac-byok` — **Раунд 10, 08.09.2026** (F-7, T-843…T-869: RBAC-роли + chat_params-слой + BYOK + бюджеты; §22)
- `tma-ui-fixes` — **Раунд 10, 08.09.2026** (F-8, T-870…T-877: 8 UI/UX-фиксов TMA; §22)
- `permsoc-module-isolation` — **Раунд 10, 08.09.2026** (F-9, T-878…T-889: плагин PERMsoc + девиансия M-F-9 (а); §22)
- `feature-gates-worker-budget` — **Раунд 10, 08.09.2026** (F-10, T-890…T-902: Opt-In-гейты + worker-бюджет; §22)
- `tma-ia-progressive-disclosure` — **Раунд 10, 08.09.2026** (F-11, T-903…T-913: IA/меню 5-секций + прогрессивное раскрытие; §22)
- `global-oversight-dashboard` — **Раунд 10, 08.09.2026** (F-12, T-914…T-924: Oversight + kill-switch; §22)
- `agi-memory-implementation` — Раунд 9, 06.09.2026 (relations A-Life, сон, ностальгия, dig_into_lore, канон R9; ARCHITECTURE §21)
- `context-layer-x-features` — Раунд 8 (24 пункта CONTEXT_RESEARCH; §20)
- `chat-lore-management-v2` — Раунд 7 (PG chat_profiles, TMA «Лор чатов»; §19)
- `history-import-hybrid-memory` — Раунд 6 (FTS5 + GraphRAG, миграция v7; §18)
- `betterstack-lore-prompts-round5` — Раунд 5 (§17)
- `betterstack-own-handler-video-memory-cmds` — Раунд 4 (§16)
- `multimodal-summarization-tools-reactions-ui` — Эпик 04.09 (§13)
- `tg-video-tool-calling-fixes` — Bugfix 04.09 (§14)
- `video-multimodal-pipeline-and-incidents` — Раунд 3 (§15)

## Research (plans/docs/)

`multi-chat-scaling-research.md` (07.09.2026 — ИСХОДНИК раунда 10, вариант A),
`prod-params-audit-2026-09.md`, `memory-project-overview.md`,
`CONTEXT_RESEARCH.md`, `agi-memory-research.md`, `chat-lore-management-research.md`,
`sqlite-to-pg-research.md`, `factcheck-audit.md`, `memory-import-research.md`,
`research-directchat-digest.md`, `memory_sleep_nostalgia_lore_report.md`
(12.09.2026 — plain-language отчёт раунда 10.11: память/сон/ностальгия/лор,
тайминги, сборка контекста; каждая цифра с `file:line`), `canon/` (architecture.md, backlog.md).

## Граф: краткий обзор (узел AdminBot + feature-*)

> **Актуализация 20.09.2026 (после 10.24):** каталог **REGISTRY 459** / Settings **418** /
> categorized **434** / GROUPS **98** / mapped **96** / `TAB_RULES` **21**; **SQLite v12** (Δ DDL=0);
> релиз **`release-round1024`** (commit **`da561bc`**, прод `version=2.58.0`); канон инструментов R9 = **10**.
>
> **Исторический снимок (15.09.2026, после 10.18):** каталог REGISTRY 436 / Settings 406 /
> categorized 411 / GROUPS 90 / mapped 88 / `TAB_RULES` 19; **SQLite v10** (`edges.fact_id`,
> nullable + индекс); релиз **`release-round1018`** (commit **`16a8c0b`**, прод PID 2319614);
> новых фича-флагов нет. Линии ниже — исторические снимки раундов 10–10.13.

- **adminbot-backend** — aiogram 3.31 (polling) + FastAPI (`web/app.py`) + asyncpg + aiosqlite; APP_VERSION=2.57.0 (раунд 10.13); порядок роутеров bot.py: slava_presence → alan_greeting → kostik → alan → dead_page → war_alert → common → olya → slavik → vasya (без изменений). F-12 добавил oversight-API (web/api/oversight.py), F-7/F-10 — access/gates/budget-роуты.
- **adminbot-pg-schema** — `bot_settings` (key/value JSONB/category), `bot_roles` (permissions JSONB; F-7 добавил `role_type`), `bot_admins`, `chat_profiles` (manual/auto лор + `relations` JSONB; **F-7 добавил `chat_params` JSONB**, **F-10 добавил `gates_opt_in`**), `chat_lore_history` (F-7 расширил CHECK поля: chat_params/chat_keys/gates), `chat_links`, `chat_admins` (F-7 добавил `role_name`), `uptime_events`. **Новые таблицы раунда 10: `param_permissions`, `chat_keys`, `chat_usage`, `worker_budget`** (итог — DDL-код в `services/pg_db.py`, прод-DDL @DevOps).
- **adminbot-sqlite-schema** — `users_meta` (стадии отношений), `smart_messages` (FTS5), `nodes/edges`, `graph_facts` (v1–v8), `dream_state`, `memory_dream_log` (бюджет суток), `nostalgia_log` и др. Миграция памяти sqlite→PG ЗАМОРОЖЕНА (04.09.2026). Вне скоупа раунда 10.
- **hot-config-layer** — `services/hot_config.py::hot.get(pg_key, default)`; ConfigCache (`services/config_cache.py`) — in-memory над PG, R6 fail-open. Цепочка глобальная; **F-7 добавил per-chat слой `hot_chat` (chat_params → bot_settings → дефолт) параллельно — hot.get/ConfigCache не менялись**.
- **llm-client-key-resolution** — `services/llm_client.py`; ключ: `hot.get("keys.llm_api_key", settings.LLM_API_KEY)`; фоллбэки `keys.llm_fallback_api_key` + embed-каскад (Google AI Studio, 2 ключа). **F-7 добавил BYOK: `_resolve_api_key_and_source(chat_id)` — свой ключ чата → allow_global=false → бюджет → глобальный; sandbox `content.no_key_reply` (фикс R6: per-call, без инстанс-стейта).**
- **param-catalog** — `services/param_catalog.py` REGISTRY ParamSpec; F-7 добавил поле `per_chat` (whitelist), F-11 — `progressive_level`, F-9/F-10 — новые ключи (`flags.permsoc_enabled`, `limits.worker_daily_*`, `limits.chat_global_key_budget_*`, `content.no_key_reply`); раунды 10.9–10.13 — итеративный прирост. Итог раунда 10.13: REGISTRY **427** / GROUPS **90** / Settings **399** / mapped **88** / categorized **403**, TAB_RULES 19 (санкционированный Δ ADR-1013-1 + флаг F8).
- **rbac-v2** — `services/permissions.py` + неймспейсы `section./param./key./action.`; GET /api/config маскирует секреты {configured,last4}; POST — per-key права. **F-7 расширил: role_type-иерархия (services/roles.py), access_for, param_permissions, локальные чат-роли (chat_admins.role_name)**; `permissions.py` остаётся чистым матчером.
- **tma-frontend** — Vue 3 global (без сборки): `web/index.html` + `web/app.js` + FastAPI `/api/*`. Вкладки: LLM Провайдеры, Промпты, Лимиты, Память и RAG, Реакции и Триггеры, Доступы, Лор чатов, Статус, Как это работает. **Раунд 10 реализован: F-8 (UI-фиксы) + F-11 (навигация 5 меню + селектор чатов + прогрессивное раскрытие + вкладка modules_feats) + F-12 (oversight) поверх F-7 (X-Chat-Id, роль-пикер, BYOK-поля).** **Хотфикс 10.1 (8eae899):** закрыты БГ1–БГ4 рекона — `basicItems`/`advancedItems` (+ прогрессивное раскрытие на всех конфиг-вкладках), логи (scrollTop=0, клик-копия, 0.70rem), лор (топ-50, ленивые аватары 300ms, каскад имён alias→nickname→username→id, фулскрин), modules_feats (бюджет всегда).
- **legacy-triggers-permsoc** — Славик (479167456), Костя (350803143), Леха/Алан (138811255), Оля (834424825, единственный с флагом `flags.olya_enabled`), передразнивания (`flags.mimic_enabled`); ID в группе `reactions_persons`. **F-9 изолировал в плагин services/permsoc.py с master-гейтом flags.permsoc_enabled + PermsocGateFilter (девиансия M-F-9 (а): alan — master-only).**
- **background-workers** — LoreWorker, DreamWorker, NostalgiaWorker, Summary/Goodmorning/валер-подобные; бюджет сна — `memory_dream_log.tokens` за local-сутки. **F-10 перевёл тяжёлые фичи под жёсткий Opt-In (gates + gates_opt_in) + суточный ledger `worker_budget` (global/per-chat лимиты LLM-вызовов/токенов, деградация nostalgia→lore→dream).**
- **plans-structure** — см. разделы выше; раунд 10 ЗАВЕРШЁН: 6 фич F-7…F-12 (entity `feature-*` в графе, статус **archived**, ARCHIVED_IN plans-structure), 82 задачи T-843…T-924; plans/archive/ — **15 папок**; раунд закоммичен (69be94e + 533bf13,
HEAD == origin/master == 533bf13); **милстоун `round10.1-hotfix`** (AdminBot → COMPLETED,
FIXES tma-frontend, RESOLVES recon: tma-round10-postdeploy-bugs) — хотфикс 10.1 закоммичен
и задеплоен (8eae899, PID 159455), HEAD == origin/master == 8eae899;
**милстоун `round10.2-fixes`** (AdminBot → COMPLETED + DEPLOYED; RESOLVES
recon: tma-bugs-7-post-10.1; FIXES 7 bug: tma-*) — раунд 10.2 ЗАКОММИЧЕН и
ЗАДЕПЛОЕН (d30b203, 28 файлов, тесты 4760, PID 454654),
HEAD == origin/master == d30b203; **новый милстоун `server-hardening-102`**
(AdminBot → DEPLOYED) — fail2ban/ufw/SSH-харденинг 09.09.2026 (см. раздел
«Безопасность сервера» выше); **милстоун `round10.3-epic` (AdminBot → COMPLETED +
DEPLOYED, конвенция round10.2-fixes)** — раунд 10.3 ЗАВЕРШЁН, ЗАКОММИЧЕН и
ЗАДЕПЛОЕН (коммит 1410a68, 09.09.2026 12:33 UTC; рестарт 12:37 UTC, active;
тесты 4831; прод-диагностика задачи 5 — recon: direct-chat-sandbox-budget);
3 фичи F-13 tma-chat-selector-fixes + F-14 dm-user-settings + F-15
direct-sandbox-budget-investigation (T-925…T-973) → **ARCHIVED_IN plans-structure
+ WAS_PART_OF round10.3-epic** (HAS_PLAN/PLANNED_IN/PART_OF/ARCHITECTED удалены,
конвенция F-7…F-12); ARCHITECTURE.md §23/§24;
**милстоун `round10.4-epic` (AdminBot → COMPLETED + DEPLOYED, 10.09.2026)** —
раунд 10.4 «Реструктуризация TMA-миниаппа + точечные фиксы» (9 пунктов ТЗ):
8 фич feature-frontend-advanced-collapse-default (D), feature-frontend-memory-sleep-nostalgia
(C), feature-frontend-llm-providers-layout (E), feature-frontend-reorg-modules-reactions
(A), feature-frontend-limits-temperature-budgets (B), feature-frontend-relations-participants
(F), feature-backend-relations-nickname (H), feature-backend-chat-1002661910336-scaling
(G) — **все COMPLETED + ARCHIVED** (WAS_PART_OF round10.4-epic + ARCHIVED_IN
plans-structure; HAS_PLAN/PLANNED_IN/ARCHITECTED_IN удалены — конвенция F-7…F-12;
HAS_SPEC/HAS_TASKS и цепочка DEPENDS_ON D←C←E←A←B←F←H←G сохранены как исторический
факт); архитектурная фаза зафиксирована @Architect (KG: round10.4-specs +
round10.4-dependencies; Step 0 — recon: tma-structure-10.4); конфликт-матрица:
F-1 PRECEDES B/G — учтён (фича активна), F-3/F-4 AFTER round10.4-epic (активны),
F-5 AFTER B/G (активна, R10.4-7 — её кандидат), F-6 (plans/features/user-aliases-admin)
SUPERSEDED_BY round10.4-epic — подтверждена; REGISTRY 383/**74**/359 (коррекция
71→74 — ре-дизайн 10.2 BUG-3; MED-017); техдолг-кандидаты следующего раунда —
KG `tech-debt-round10.4` (R10.4-4…R10.4-7, B-13 points 2-4, HIGH-004-остаток);
plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **26 папок**;
HEAD == origin/master == `0bdf272` (коммит раунда 10.4: бэкфилы применены,
CHAT_THREAD_MAX_CHARS=2000, тесты 4860, прод active);
**милстоун `round10.5-epic`** (AdminBot → COMPLETED + DEPLOYED, 10.09.2026) —
раунд 10.5 «Редизайн TMA по референсу Relume + гигиена репозитория»: единственная
фича `tma-relume-redesign` (T-1066…T-1148) → COMPLETED + DEPLOYED + WAS_PART_OF
round10.5-epic + ARCHIVED_IN plans-structure (HAS_PLAN/HAS_FEATURE/RELATED_TO/
HAS_DESIGN_PROJECT — сохранены как исторический факт; HAS_PLAN не удалялся);
ARCHITECTURE.md §9/§25/§26; R10.5-1/-2/-4 закрыты, техдолг-кандидаты — KG
`tech-debt-round10.5` (R10.5-3/-5/-6/-7, ARCH §25); plans/features/ — **6 активных**
(F-1…F-6); plans/archive/ — **27 папок**; HEAD == origin/master == `c01ed72`
(коммиты 918f675 + c01ed72, тесты 4962, деплой 198.46.175.136 active/health 200,
0 ошибок); остаётся ручной live-smoke T-1153 + опц. betterstack 401.
**милстоун `round10.6-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.6 «Переработка IA TMA»: единственная фича `tma-ia-modules-rework` (T-1155…T-1223)
→ COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.6-epic +
ARCHIVED_IN plans-structure; sidebar удалён, «Модули» (11) + «Настройки AI» (7) + чистый
PERMsoc + provider-блоки + `POST /api/llm/test`; каталог 392/91/364/mapped 89/TAB_RULES 19;
5 master-флагов default ON с реальными гейтами; ARCHITECTURE.md §27 (+§25/§9/§6/§2);
Scanner 0 blocker/0 major (R10.6-1/-3 закрыты; техдолг-кандидаты — KG `tech-debt-round10.6`:
R10.6-2/-4/-5/-6); plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **28 папок**;
HEAD == origin/master == `4055434` (коммиты 6f91e8b + 4055434, тесты 5027, деплой
198.46.175.136 active/health 200, 0 tracebacks); остаётся ручной live-smoke (desktop/Android
WebView) + опц. betterstack 401.
**милстоун `round10.7-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.7 «UI/UX-багфиксы админ-минги»: единственная фича `admin-ui-bugfixes-round107`
(spec T-1224) → COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.7-epic
+ ARCHIVED_IN plans-structure; scope*-computed, safe-area шапки, компактный юзер-блок,
nav labels без per-letter wrap, ellipsis ключей, uptime gap-fill (5-мин сетка/down),
clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20; ARCHITECTURE.md §28 (+§9/§25);
Scanner 0 blocker/0 major (R10.6-5 закрыт; техдолг-кандидаты — KG `tech-debt-round10.7`:
R10.7-1…R10.7-5); plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **29 папок**;
HEAD == origin/master == `bb59476` (коммиты 7f3b790 + bb59476, тесты 5042, деплой
198.46.175.136 active/health 200, 0 errors); остаётся ручной live-smoke исправленного UI
+ опц. betterstack 401.
**милстоун `round10.8-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.8 «Точечные UI-правки админ-минги»: единственная фича `admin-ui-round108`
(T-1243…) → COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.8-epic
+ ARCHIVED_IN plans-structure; переименование разделов, emoji→Material (субсет 20→37,
18 388 B), Android-логи, route-driven окна «Доступов», README, APP_VERSION 2.52.0;
ARCHITECTURE.md §29 (+§1/§9/§25); Scanner 0 blocker/0 major (R10.8-1/-5 закрыты;
техдолг — KG `tech-debt-round10.8`: R10.8-2/-3/-4; R10.7-3/-4 закрыты);
plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **30 папок**;
HEAD == origin/master == `976e335` (коммиты 31d2ce7 + 976e335, тесты 5076, деплой
198.46.175.136 active/health 200, 0 errors, шрифт wOF2 18 388 B); остаётся ручной
Android smoke T-1254 (логи)/T-1258 (окна «Доступов») + опц. betterstack 401.
**милстоун `round10.9-epic`** (AdminBot → COMPLETED + DEPLOYED, 12.09.2026) —
раунд 10.9 «UI/UX-правки админ-минги»: единственная фича `admin-ui-round109`
(T-1270…T-1314, spec @Architect + tasks @PM + ADR-109) → COMPLETED + DEPLOYED +
WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.9-epic + ARCHIVED_IN plans-structure;
PERMsoc owner-блоки (4) + `flags.slavik_enabled`, `_preserveScroll` для
`document.scrollingElement`/`.scroll-area`, переписанные описания/титулы,
«Тяжёлые фичи» удалены, «Бюджет фона»→«Сводка», dashboard «Доступность ключей»
(4 группы) + реальный health `probe_openai` (TTL 2xx 60с/ошибки 10с), 7
`models.*_display_name`, форма `max-w-3xl`, градиент 14s/18s; каталог
400/90/372/mapped 88; ARCHITECTURE.md §30 (+§1/§9/§25); Scanner 0 blocker/0 major/
0 medium (3 low R10.9-1/-2/-3 + 3 info R10.9-4/-5/-6; R10.9-6 закрыт; техдолг —
KG `tech-debt-round10.9`); plans/features/ — **6 активных** (F-1…F-6);
plans/archive/ — **31 папка**; HEAD == origin/master == `f928225` (коммиты
d2d1215 + f928225, тесты 5105, деплой 198.46.175.136 active/health 200, 0 ошибок,
APP_VERSION 2.53.0); остаётся ручной live Android smoke T-1277/1290/1292/1294/
1302/1305 + опц. betterstack 401. ⚠️ Пункт 2 ТЗ (инфраструктура локального IDE
владельца) — вне скоупа проекта.
**милстоун `round10.10-epic`** (AdminBot → COMPLETED + DEPLOYED, 12.09.2026) —
раунд 10.10 «UI/UX-правки админ-минги»: единственная фича `admin-ui-round1010`
(spec @Architect + tasks @PM + ADR-1010-1/2/3; T-1315…T-1328) → COMPLETED + DEPLOYED
+ WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.10-epic + ARCHIVED_IN plans-structure;
fullscreen safe-area padding шапки, мобильный график доступности ключей (окно от
конца), реальные значения полей Провайдеров (`blockFieldValue`), ЛС heavy-modules
OFF (`disable_dm_heavy_modules.py` + data-run 1 ЛС), «Роли» с аватаром+ником+мелким
ID; каталог 400/90/372/mapped 88; ARCHITECTURE.md §31 (+§3/§9/§25); Scanner
0 blocker/0 major/0 medium (low R10.10-1/-2/-3 + info R10.10-4/-5; техдолг —
KG `tech-debt-round10.10`); plans/features/ — **6 активных** (F-1…F-6);
plans/archive/ — **32 папки**; HEAD == origin/master == `772db08` (коммиты
d082800 + a477747 + 772db08; тесты 5145 passed / 1 skipped / 0 failed; деплой
198.46.175.136 active/health 200, 0 ошибок, APP_VERSION 2.54.0); остаётся ручной
live Android QA T-1317/1320/1323/1332 + UI spot-check DM-тумблеров OFF T-1328.
**милстоун `round10.11-epic`** (AdminBot → COMPLETED + DEPLOYED, 12.09.2026) —
раунд 10.11 «Рефакторинг LLM Провайдеры + проверка сохранённого ключа + key-history
chart + отчёт по памяти»: единственная фича `llm-providers-refactor-round1011`
(spec @Architect + tasks @PM + ADR-1011-1/2/3; T-1340…T-1381) → COMPLETED + DEPLOYED
+ WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.11-epic + ARCHIVED_IN plans-structure;
saved-key probe `/api/llm/test` (R17-safe), nav-icons 22px + pinned профиль, две зоны
«Подключения»/«Расширенные» (computed), embeddings 3 подблока + 4 записи в каталог
(sanctioned Δ: categorized 376, infra 28→24), video-fallback выше, media-share/теххаос
внизу, key-history chart `spanGaps`+`stepped` (linear-ось, `parsing:false`), docs-отчёт
`memory_sleep_nostalgia_lore_report.md`; каталог 400/90/372/mapped 88; ARCHITECTURE.md
§32 (+§5/§9/§25); Scanner CLEAN 0 blocker/0 major/0 medium (R10.11-1/-2/-3 закрыты;
техдолг — KG `tech-debt-round10.11`: R10.11-4/-5/-6); plans/features/ — **6 активных**
(F-1…F-6); plans/archive/ — **33 папки**; HEAD == origin/master == `cbe6ea5` (коммиты
3624789 + cbe6ea5; тесты 5172 passed / 0 failed; деплой 198.46.175.136 active/health 200,
0 ошибок, миграция created=5/skipped=48, APP_VERSION 2.55.0); остаётся ручной live
Android/Telegram QA **T-1377**; наблюдение — pre-restart PID 401 к apinet.cloud (проверить).
**милстоун `round10.12-epic`** (AdminBot → COMPLETED + DEPLOYED, 13.09.2026) —
раунд 10.12 «Развязка эмбеддингов от прямых ответов + 422 глобальных ключей +
объединённые блоки подключений + фразы Костика»: единственная фича
`providers-kostik-round1012` (spec @Architect + tasks @PM + ADR-1012-1) → COMPLETED +
DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.12-epic + ARCHIVED_IN
plans-structure; `round10.12-epic FOLLOWS round10.11-epic`; models.embedding_base_url
=apinet.cloud/v1 + keys.embedding_api_key (OD-1, фолбэк на llm-ключ) /
models.llm_base_url=nano-gpt.com/api/v1 (отдельный read-path + httpx-кэш
`_embed_client`); global-save для per_chat=false во всех трёх путях; merged-блоки с
display-name (STT/video display-name разделены, свопа нет); reactions.kostik_replies
(14 фраз) + flags.kostik_enabled + owner-блок; каталог 405/90/377/mapped 88/
categorized 381; ARCHITECTURE.md §33 (+§5/§9/§12/§25); Scanner clean 0 blocker/0 major/
0 medium (R10.12-1/-5 закрыты; техдолг — KG `tech-debt-round10.12`: R10.12-2/-3/-4);
plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **34 папки**;
HEAD == origin/master == `bad2b0d` (коммиты 708f7df + bad2b0d; тесты 5211 passed /
0 failed; деплой 198.46.175.136 active/health 200, 0 ошибок, миграция
created=5/skipped=149, APP_VERSION 2.56.0); остаётся ручной live Android/Telegram QA
+ опц. выделенный embedding api key.
**милстоун `round1013-epic-cognition`** (AdminBot → COMPLETED + DEPLOYED, 13.09.2026) —
раунд 10.13 «Cognition / Sleep / Memory Refactor»: **8 фич** (F1 `cognition-4d-memory-round1013`,
F2 `cognition-belief-decay-round1013`, F3 `cognition-deep-sleep-round1013`,
F4 `cognition-llm-providers-round1013`, F5 `cognition-dashboard-round1013`,
F6 `cognition-ekg-logs-bugfix-round1013`, F7 `cognition-user-guide-round1013`,
F8 `cognition-irony-dossier-round1013`; 60 задач T-1417…T-1476) → COMPLETED + DEPLOYED +
WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure (PART_OF/ARCHITECTED
удалены — конвенция round10.12); `round1013-epic-cognition FOLLOWS round10.12-epic`;
созданы `release-v2.57.0-round1013` (AdminBot PRODUCED) и `tech-debt-round10.13` (5 Low).
4D-память + belief decay/Resurrection + «Глубокий сон»/парадигмы + UI-провайдеры
`intel_history`/`intel_bg` + дашборд «Осмысление»/граф vis-network + EKG/фикс логов +
user guide + ирония/досье (`status='chat_meme'`). ARCHITECTURE.md §34 + ADR-1013-1/2/3;
каталог **427**/90/**399**/mapped 88/categorized **403** (TAB_RULES 19); флаги default OFF
(`belief_decay_enabled`/`deep_sleep_enabled`/`irony_filter_enabled`); тесты
**5392 passed / 0 failed** (база 10.12 = 5211, +181); деплой `8800bba`, прод
198.46.175.136 active (PID 1629874)/health 200, APP_VERSION **2.57.0**;
plans/archive/ — **42 папки**; plans/features/ — 6 активных (F-1…F-6);
@Reviewer iter1 Rejected → iter2 APPROVED; @Scanner iter1 0C/1H/4M/9L → iter2 0C/0H/0M/5L;
@Builder — 2 цикла реворков. `plans/metrics.md` — метрики по раундам.

## Факты для планирования (проект)

- HEAD промпт-каноны живут в `plans/docs/canon/`; миграции промптов — `services/prompt_migrations.py`.
- Отношения: manual-стадии в PG `chat_profiles.relations`, авто — SQLite `users_meta.relationship_stage`.
- Тумблеры персоналий по умолчанию выключены только для kucha/mimic/olya; сон/ностальгия/авто-лор — включены по умолчанию (раунд 10 перевёл на жёсткий Opt-In — F-10: `gates_opt_in` + `chat_params.gates`).
- Раунд 10, F-7 (Q5, РЕАЛИЗОВАНО): `per_chat=True` = категории {prompts, limits, flags, reactions, content, memory} и secret=False; `models.*`/`keys.*` — строго глобальные.
- Раунд 10, F-7 (R17/инвариант 2, РЕАЛИЗОВАНО): локальный админ НЕ видит глобальный ключ ни в каком виде; raw-ключи никогда не логируются/не отдаются (S1/S2/S3, R17-аудит).
- Раунд 10, F-9 (Q3, РЕАЛИЗОВАНО): дефолт новых чатов — permsoc OFF; живые чаты включаются бэкфилом `scripts/backfill_permsoc_gates.py` по правилу (-1002661910336 / relations_enabled / manual|auto_lore / chat_admins).
- Раунд 10, F-12 (Q2, РЕАЛИЗОВАНО): приоритет гейтов — явный chat-гейт → `hot.get('flags.<feature>_enabled')` → False; kill-switch = явный `gates[feature]=false`.
- **Follow-up раунда 10 (вне цикла):** unit-тест-гап `backfill_permsoc_gates.py` (прямых тестов бэкфила нет); live-проверка имени CHECK-ограничения `chat_lore_history` на проде (field='gates'/'chat_keys'); предложение расширения `deploy_v2.9.2.py` (DDL + бэкфилы + live-гистограммы при деплое).
- **Follow-up безопасности сервера (ожидают решения владельца):** миграция на SSH-ключи (key migration proposal — password auth пока оставлена по требованию); добавить IP владельца в fail2ban `ignoreip`, если он статический; CrowdSec как альтернатива fail2ban; перенос `migrate_history` (1.1G) на другой диск/раздел.
- **Раунд 10.4 (ЗАВЕРШЁН + DEPLOYED, 10.09.2026, коммит 0bdf272):** порядок фич
  D→C→E→A→B→F→H→G выполнен; REGISTRY 383/**74**/359 без изменений (коррекция счётчика
  групп 71→74 — ре-дизайн 10.2 BUG-3; MED-017; новые ключи/группы ЗАПРЕЩЕНЫ);
  SQLite v8, роутеры bot.py, каноны промптов, known_sections() — без дифов;
  девиансия D-A1 реализована (фича A: war/common/goodmorning/word_reactions →
  «Функции PERMsoc», 17 групп); бэкфилы backfill_104_chat_flags.py +
  backfill_104_overrides.py применены; техдолг-кандидаты следующего раунда:
  R10.4-4…R10.4-7, B-13 points 2-4, HIGH-004 (KG `tech-debt-round10.4`);
  конфликт-матрица исходно: F-1 (T-648 атомарный POST) — учтён ДО B/G.
