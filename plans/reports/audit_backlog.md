# Audit Backlog

## Эпик 3 / A0 `agentic-audit-round1026` (T-3498, единый Reviewer gate — линза 1 requirements/completeness + линза 2 focused change audit), 24.09.2026 — **APPROVED: к архивации/handoff ДА (C0/H0/блокирующих Medium 0; read-only подтверждён по факту; первопричина честно разделена; live-пробы A3/A4 — unavailable)**
База — HEAD `e8065e9` == `origin/master`; annotated-тег `pre-round1026-a0` (obj `afe14278` → `e8065e9`); **A0-коммитов нет**; правки — только `plans/features/agentic-audit-round1026/**` + `plans/docs/agentic-audit-round1026.md` (untracked) + `plans/MEMORY.md`/`plans/backlog.md`/`plans/workflow_state.md` (ролевые, не A0). Product-diff (`git diff e8065e9 -- . ":(exclude)plans"`) — **пусто**; untracked-кода — **нет**. Отчёт и биndинг: `plans/features/agentic-audit-round1026/review.md`. Воспроизведено @Reviewer независимо: `git diff --check`=0 (только CRLF-warning для не-A0 файлов); импорт каталога — **REGISTRY 469 / Settings(fields) 426 / categorized 444 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21**; `TOOL_CALLING_TOOLS` = **10** (имена/порядок канона); `factcheck_tools` = 3; `active_tools()` default = 9 (image OFF по дефолту); `get_user_context` в `*.py` — **0**; `APP_VERSION` = **2.58.29** (без bump); **Δ DDL=0** (SQLite v12, `db/**` вне diff); **Δ каталога=0** (`param_catalog.py` вне diff); R18 — тег `pre-round1026-a0`→`e8065e9`, бэкап `var/backups/a0-round1026-20260924-114354/`, `stash@{0}` целы.
- **Линза 1 (requirements/completeness):** §12 — **15/15** разделов в `§10.2`; §54 п.1 — **1/1**; карта инструментов — **ровно 10 × 8/8 полей**, каждый с `file:line` (распарсено: 10 строк × 9 колонок, пустых ячеек нет); **22** различных `.py`-ссылок — все существуют, **0** ссылок вне диапазона строк; **38** явных анкоров (0 дублей), **89** внутренних `#`-ссылок → **0** неразрешённых; трассировка без orphan'ов (REQ **19/19**, SC **23/23**, §12 **15/15**, §54 п.1 **1/1**); handoff §8.3 содержит все обязательные точки (2-вызовный пайплайн без 3-го LLM-вызова; `action`/`style` ADR-1023-3; REUSE ExecutionGraph §65/§79; §104; канон ADR-1013-3; §85-UI отдельная санкция; существующие досье/RAG/фактчек/`image_calls`; `get_user_context` отсутствует). Разметка: **34 EVIDENCE / 6 HYPOTHESIS**; каждая HY-01…HY-06 — с планом проверки и волной A3/A4; вывод «только промпт» отсутствует и опровергнут (§6.3, места №1/№2/№9). ADR-1026-13 — **Proposed** ✅.
- **Линза 2 (focused change audit):** read-only подтверждён фактическим деревом; скрытых побочных эффектов нет; first-cause «9 мест + 5 кандидатов» проверен по коду (tool_loop, tool_router, image_generation, direct_chat_service, tool_schemas); EVIDENCE-выборка `file:line` сверена с кодом `e8065e9` и совпала.
- **Unavailable:** живой прогон провайдера / tool-probe и разбор прод-логов (кандидаты г/д + фактическое состояние рубильников) — вне A0 (read-only); пробы A3/A4 по HY-01…HY-06.
- **Новых Critical/High/блокирующих Medium — нет.** Отдельного Scanner-approval не существует (Scanner удалён намеренно, 24.09.2026).
- **Handoff:** @Orchestrator → **APPROVED (единый gate: обе линзы пройдены)**; далее T-3499 @PM — архивация COMPLETE-фичи (durable-артефакт `plans/docs/agentic-audit-round1026.md` **остаётся на месте**; ADR-1026-13 → Accepted по merge/архивации) → handoff к **A1 `tool-coordinator`**.

## Эпик 2 / S10 `summary-deploy-round1026` (T-3474/T-3475, единый Reviewer gate — линза 1 requirements/correctness + линза 2 focused change audit), 24.09.2026 — **APPROVED: к деплою ДА (C0/H0/блокирующих Medium 0; отклонения D-a/D-b/D-c — допустимы, non-blocking; live §115/§117 — PENDING OWNER VERIFICATION)**

Baseline — HEAD `76abf91` == `origin/master` (closing-docs S6) == annotated-тег `pre-round1026-s10` (tag-obj `be7760295` → `76abf91`); правки S10 **НЕ закоммичены** (`git status`: 39 M + 2 ??-записи; untracked-манифест Working-Tree-Hash — 8 файлов, кроме `review.md`). Отчёт и актуальные биндинги (Reviewed-Commit `76abf91` / Working-Tree-Hash / Spec-Hash `41ee0c6e…`): `plans/features/summary-deploy-round1026/review.md`. Воспроизведено @Reviewer независимо: pytest `.venv` **9026/0** (154.97 s), JS **47/47**, `git diff --check`=0; каталог **469/426/444/100/98/21** (`gen_param_registry --check` OK), `APP_VERSION` **2.58.29**, `SUMMARY_HYBRID_L2_ENABLED` default **True**, `SUMMARY_FILTER_ENABLED` default True; **Δ DDL=0** (`db/**` вне diff, 0 DDL-хитов в изменённых модулях); **Δ каталога=0** (`param_catalog.py` вне diff, F8 не переиздаётся); границы diff подтверждены (пусто: `image_generation.py`/`telegram_send.py`/`summary_prompts.py`/`prompt_migrations.py`/`summary_filter.py`/`summary_context_restore.py`/`summary_l1_clusterizer.py`/`summary_fact_package.py`/`summary_article_formatter.py`/`summary_test_run.py`/`routes.py`/`web/**`/`db/**`/`param_catalog.py`/`bot.py`); AST-идентичность `_run`/`_run_hybrid_l2`/`_hybrid_l2_enabled` (и всего `services/summary_l2_writer.py`) baseline без docstrings; **0 новых внешних зависимостей** (манифесты вне diff); 2-вызовность (`await_count==2`); R17/R18 (тег `pre-round1026-s10`/`var/backups/s10-round1026-20260924-100654/`/`.env.bak.round1026-s10`/`stash@{0}` целы); все 20 заявленных Builder SHA-256 совпали.
- **Линза 1 (requirements/correctness):** §107 — активация = code-default ON без ручного действия (`_env_bool("SUMMARY_HYBRID_L2_ENABLED", True)`, рантайм-проба: default True / env `false` → False), kill-switch (env/hot/per-chat `false`) и сохранённая цепочка `per-chat → hot → env/default` работают; теневой режим/rollout/Legacy-селектор **не введены**; фильтр ON; роутинг L1/L2 активен; фича **не остаётся выключенной**. §114 — 11/11 сценариев покрыты (`TestSec114Scenarios`), **0 реальных отправок** (шпионы + guard, бросающий при обходе `telegram_send.*`/`image_generation.generate_image_verbose`). §115 — процедура 7 проверок + rich/plain-артефакты (`procedure-115.md`); живой прогон — ⏳. §116 — 15 критериев не нарушены (модули S1–S9 вне diff). §117 — `results.md`, 14 пунктов с трассировкой. §85-UI (каталог/F8/UI-тумблер/селектор) — не тронут.
- **Линза 2 (focused change audit):** Δ DDL=0; Δ каталога=0 (F8 N/A); CSP/zero-build (`web/**` вне diff); 0 зависимостей; 2-вызовность; границы diff по факту; version-pins 2.58.28→2.58.29 корректны; перепрофилирование OFF-default-тестов — только добавление **явного** OFF/переименование, assertions не ослаблены.
- **[D-a] `plans/docs/param-registry-round1025.meta.md` — допустимо (non-blocking):** обновлён только провенанс-штамп `APP_VERSION` 2.58.28→2.58.29; **необходим** для зелёного `tests/test_round1025_f8_registry.py::test_meta_provenance` (assert `APP_VERSION in meta`); прецедент S5–S9; каталог/TSV/F8 не переиздаются (`--check` OK).
- **[D-b] явный OFF в legacy-тестах шире точного списка D1 — допустимо (non-blocking):** все правки в `tests/**` (разрешено D1); OFF-путь фиксируется явным `false`, ON-путь покрыт §114-harness/S5–S6; assertions не ослаблены.
- **[D-c] флак `test_summary_memory.py` (teardown-таймаут Windows asyncio) — инфраструктурный шум, не регресс:** изолированный прогон `test_summary_memory.py` **79 passed**; полный прогон **9026/0** без таймаутов.
- Unavailable: live §115 (7 проверок на проде) и live-составляющая §117 пп.7/8/11/12/13/14 — **PENDING OWNER VERIFICATION** (вне этого gate); §116 — не machine-verified единым тестом (чек-лист + неизменность модулей S1–S9).
- **Новых Critical/High — нет.** Отдельного Scanner-approval не существует (Scanner удалён намеренно, 24.09.2026).
- **Handoff:** @Orchestrator → **APPROVED (единый gate: обе линзы пройдены)**; далее commit/push (без force) → T-3476 merge (§81, ADR-1026-12 Accepted) → T-3477 archive → T-3478 deploy/активация (2.58.29, §115) → T-3479/T-3480 handoff; live — PENDING OWNER VERIFICATION.

## Эпик 2 / S6 `summary-publish-integration-round1026` (T-3454/T-3455, повторный единый Reviewer gate — линза 1 requirements/correctness + линза 2 focused change audit, после rework T-3456), 24.09.2026 — **APPROVED: к деплою ДА (C0/H0/блокирующих 0; B-R1026S6-1/-2 CLOSED; non-blocking Low/Info; live — PENDING OWNER VERIFICATION)**

Baseline — HEAD `197891f` == `origin/master` (closing-docs S8) == annotated-тег `pre-round1026-s6` (tag-obj `6fd4a9d6` → `197891f`); правки S6 **НЕ закоммичены** (`git status`: 49 M + 3 ??-записи = 7 untracked-файлов; манифест Working-Tree-Hash — 6, кроме `review.md`). Rework T-3456 затронул ровно 4 файла (mtime после ревью 08:44: formatter 08:50, generator 08:50, formatter-тест 08:51, S6-тест 08:53; прочие файлы фичи ≤ 08:24) — подтверждено. Отчёт и актуальные биндинги (Reviewed-Commit / Working-Tree-Hash / Spec-Hash): `plans/features/summary-publish-integration-round1026/review.md`. Воспроизведено @Reviewer независимо: pytest `.venv` **9000/0** (153.86 s; S6-файл 69/69, форматтер 16/16), JS **47/47**, `git diff --check`=0; каталог **469/426/444/100/98/21** (Δ=0), `APP_VERSION` **2.58.28** (README v2.58.28); **Δ DDL=0** (`db/**` вне diff, 0 DDL-хитов в изменённых модулях); границы diff подтверждены (пусто: `telegram_send.py`/`image_generation.py`/`summary_prompts.py`/`summary_test_run.py`/`routes.py`/`db/**`/`param_catalog.py`/`bot.py`; `web/api/analytics.py` — только docstring, независимое AST-сравнение без docstring идентично); **0 новых внешних зависимостей** (манифесты вне diff); 2-вызовность (`await_count==2`, 3 passed); `_send_streaming`/`_send_chunked`/`_send_one_chunk`/`_chunk_by_whitespace`/`_llm_generate`/`_ensure_shiz_postfix`/`_resolve_cover_prompt`/`_compose_user_content`/`_apply_filter` AST-идентичны baseline; R17/R18 (тег `pre-round1026-s6`/`var/backups/s6-round1026-20260924-070835/`/`.env.bak.round1026-s6`/`stash@{0}` целы); GATED-тесты S7/S8 перепрофилированы без удаления/ослабления; 39/39 независимых проб @Reviewer зелёные.
- [x] **[B-R1026S6-1] [medium, requirement gap §105/SC-20] — CLOSED (rework T-3456; перепроверено @Reviewer независимо, пробы a–c):** ни один путь не теряет текст молча: (a) plain 600 абзацев через `_deliver_plain` → missing=0, 11 чанков, `PUBLISH_TEXT_COMPLETE message_id=101` (первый чанк); (b) rich >32000 симв. (45×~810) → rich **не отправлялся** (`send_rich_message` await_count=0), WARN `reason=rich_char_limit` (числа, R17-safe), `FORMAT_ERROR channel=rich`, plain-фолбэк с **полным** текстом (`PUBLISH_TEXT_COMPLETE reason=rich_overflow`, message_id первого чанка), `PUBLISH_RICH_START` отсутствует; (c) rich >498 абзацев (600) → `reason=rich_paragraph_limit`, тот же полный plain-фолбэк; (d) `format_rich_html` отдаёт полный HTML (45/45 `<p>`, len 40375 > 32000) — тихое усечение снято; лимиты rich-канала проверяет `rich_document_limits` (границы: 498 абзацев fits / 499 overflow; ровно 32000 fits / 32001 overflow). Файлы: `services/summary_article_formatter.py:81-98,137-190,335-379`; `services/summary_generator.py:1056-1078`.
- [x] **[B-R1026S6-2] [medium, requirement gap §105/SC-06] — CLOSED (rework T-3456; перепроверено @Reviewer независимо, проба d):** единый канон `_plain_html_blocks` (`services/summary_article_formatter.py:195-224`): `chunk_plain_blocks(doc) == [format_plain_html(doc)]` байт-в-байт, абзацный `<b>` рендерится в фактической доставке (`_deliver_l2_plain`/`_publish_plain_document`), ≤1 `<b>` на абзац, экранирование сохранено (проба: emphasis `<b>&</b>` → `&lt;b&gt;&amp;&lt;/b&gt;`, 1 `<b>`); тесты уровня доставки `test_plain_delivery_renders_paragraph_emphasis`, `test_chunk_plain_blocks_renders_emphasis_single_source`, `test_chunk_plain_blocks_emphasis_escaped`.
- **Семантика `format_rich_html` (без усечения) — корректная реализация no-loss, не дефект:** rich-лимиты (≤32000 < Bot API 32768; ≤498 абзацев + h1/img = ≤500 блоков) по-прежнему соблюдаются — проверкой `rich_document_limits` до отправки; переполнение уходит в plain-фолбэк с полным текстом; отказ Telegram (если счётчик разойдётся) → `RICH_MESSAGE_SEND_FAILED` → plain (без потери). Doc-drift spec §7 («`format_rich_html` — без изменений контракта») и ARCHITECTURE §76.1/S5-spec (лимиты форматтера) — **non-blocking**: зафиксировать перенос проверки лимитов из форматтера в доставку на merge T-3457 (§80, @Architect).
- Non-blocking: **Q1** (стриминг `SUMMARY_STREAMING_ENABLED=true` вне §105/`PUBLISH_*`-контура — допустимо, spec §5.4; `_send_streaming`/`_send_chunked` AST-идентичны baseline; default OFF) и **Q2** (DB-сбои без §106-кода — допустимо, `SUMMARY_FAILED stage=db/reason=db_error/error_type=DatabaseError`) — **актуальны, rework не затронул**.
- **Новых Critical/High/блокирующих — нет.** Отдельного Scanner-approval не существует (Scanner удалён намеренно, 24.09.2026).
- **Handoff:** @Orchestrator → **APPROVED (единый gate: обе линзы пройдены)**; далее T-3457 merge (§80, ADR-1026-11 Accepted; зафиксировать перенос проверки rich-лимитов из форматтера в доставку) → T-3458 archive → T-3459 deploy (2.58.28) → T-3460 handoff; live — PENDING OWNER VERIFICATION.

## Эпик 2 / S6 `summary-publish-integration-round1026` (T-3454/T-3455, единый Reviewer gate — линза 1 requirements/correctness + линза 2 focused change audit), 24.09.2026 — **NEEDS FIXES: 2 блокирующих Medium (§105/SC-20 — тихая потеря текста; §105/SC-06 — совместимые `<b>`-акценты не рендерятся в plain-доставке); Critical/High = 0; остальные инварианты подтверждены; live — PENDING OWNER VERIFICATION**

Baseline — HEAD `197891f` == `origin/master` (closing-docs S8) == annotated-тег `pre-round1026-s6` (tag-obj `6fd4a9d6` → `197891f`); правки S6 **НЕ закоммичены** (47 M + 6 ??). Отчёт и актуальные биндинги (Reviewed-Commit / Working-Tree-Hash / Spec-Hash): `plans/features/summary-publish-integration-round1026/review.md`. Воспроизведено @Reviewer: pytest `.venv` **8989/0** (121.61 s; S6-файл 58/58), JS **47/47**, `git diff --check`=0; каталог **469/426/444/100/98/21** (Δ=0), `APP_VERSION` **2.58.28**; **Δ DDL=0** (`db/**` вне diff); границы diff подтверждены (пусто: `telegram_send.py`/`image_generation.py`/`summary_prompts.py`/`summary_test_run.py`/`routes.py`/`db/**`/`param_catalog.py`/`bot.py`; `web/api/analytics.py` — только docstring, AST-сравнение без docstring идентично); **0 новых внешних зависимостей** (манифесты вне diff); 2-вызовность; `_send_streaming`/`_send_chunked` байт-идентичны baseline; R17/R18 (тег `pre-round1026-s6`/`var/backups/s6-round1026-20260924-070835/`/`.env.bak.round1026-s6`/`stash@{0}` целы); GATED-тесты S7/S8 перепрофилированы без удаления/ослабления (S8-файл: `['llm','publish']`, реальные статусы вместо `gated`).
- [ ] **[B-R1026S6-1] [medium, requirement gap §105/SC-20, blocking]** — OPEN: тихая потеря текста в живой публикации. (a) plain-путь (`_publish_plain_document` → `chunk_plain_blocks`/`format_plain_text`) ограничивает абзацы `_iter_paragraphs` (cap **498**) — воспроизведено end-to-end: 600 абзацев → доставлено 499 (первый абзац ушёл заголовком), потеряны 101, без WARN; (b) rich-путь `format_rich_html` (`RICH_MAX_CHARS=32000`) молча срезает хвостовые абзацы (45 абзацев × ~810 симв. → 39, потеряно ~4.9k символов) — **регресс** относительно baseline OFF-rich (раньше переполнение → ошибка Telegram → plain-фолбэк с полным текстом). Файлы: `services/summary_article_formatter.py:75-85,144-156,182-190,322-342`; `services/summary_generator.py:877,915-918,1056`. Fix @Builder: plain — не применять rich-блок-кап; rich — при переполнении не срезать молча (фолбэк в plain и/или явный WARN); регресс-тесты на >498 абзацев и >32000 символов.
- [ ] **[B-R1026S6-2] [medium, requirement gap §105/SC-06, blocking]** — OPEN: plain-доставка не рендерит абзацные `<b>`-акценты — `chunk_plain_blocks` игнорирует `emphasis` (акцент умеет только `format_plain_html`, который используется лишь в dry-run S9-предпросмотре). Воспроизведено: `format_plain_html` → `<b>акцентом</b>` есть; `chunk_plain_blocks` → нет. Файлы: `services/summary_article_formatter.py:322-342` (+ spec §5.2/SC-06). Impact: ON-plain-фолбэк теряет акценты (ON gated; OFF-источник акцентов не содержит). Fix @Builder: рендерить `emphasis` (sanitize→clean→escape) в plain-чанкере либо вести доставку через accent-aware рендер; тест уровня доставки; при несогласии — spec amend @Architect.
- Non-blocking (оценка 2 трактовок @Builder): **Q1** — стриминг `SUMMARY_STREAMING_ENABLED=true` вне §105/`PUBLISH_*`-контура: **допустимо** (spec §5.4/D9; default OFF; документировано в docstring `_deliver_plain` и evidence §7.4; точка роста — возврат `message_id` из `_send_streaming`); **Q2** — DB-сбои без §106-кода: **допустимо** (не входят в 4 класса §106/D5; `SUMMARY_FAILED` с `stage=db`/`reason=db_error`/`error_type=DatabaseError` наблюдаем, evidence §7.1).
- Info: **[L-R1026S6-1]** cap 498 и **[L-R1026S6-2]** rich-trim без лога — pre-existing S5 (S6 расширил экспозицию на OFF-путь); обе снимаются фиксами B-R1026S6-1.
- **Handoff:** @Orchestrator → **NEEDS FIXES (не одобрять до rework T-3456)**; findings переданы @Builder (2 Medium блокирующих). Отдельного Scanner-approval не существует (Scanner удалён намеренно, 24.09.2026).

## Эпик 2 / S8 `summary-analytics-adapter-round1026` (T-3428/T-3429, единый Reviewer gate — линза 1 requirements/correctness + линза 2 focused change audit), 24.09.2026 — **APPROVED: к деплою ДА (C0/H0/блокирующих Medium 0; non-blocking Low/Info; live — PENDING OWNER VERIFICATION)**

Baseline — HEAD `2ffeb6a` == `origin/master` (closing-docs S7) == annotated-тег `pre-round1026-s8` (tag-obj `eeb960b4` → `2ffeb6a`); правки S8 **НЕ закоммичены** (34 M + 7 ??). Отчёт и актуальные биндинги (Reviewed-Commit / Working-Tree-Hash / Spec-Hash): `plans/features/summary-analytics-adapter-round1026/review.md`. Воспроизведено @Reviewer: pytest `.venv` **8926/0** (115.08 s; S8-файл 31/31), JS **46/46**, `git diff --check`=0; каталог **469/426/444/100/98/21** (Δ=0; `gen_param_registry --check` OK), `APP_VERSION` **2.58.27** (README v2.58.27); **Δ DDL=0** (`db/**` вне diff, untracked в `db/` нет); **Δ каталога=0** (`param_catalog.py` вне diff, `Settings`=426); publish-срез GATED (нет `kind="publish"`-узлов; `PUBLISH_*` в коде S8 = 0; `telegram_send.py`/`summary_xml.py`/`image_generation.py`/`routes.py`/`param_catalog.py`/`db/**`/`summary_test_run.py` вне diff); **0 новых внешних зависимостей** (манифесты вне diff); 2-вызовность (`await_count==2`, 3 passed); R17 (узлы/снапшот — числа/коды/id; неизвестные ключи отбрасываются; новые `RunContext`-поля в лог §108 не выводятся); R18 (тег `pre-round1026-s8`/`var/backups/s8-round1026-20260924-053821/`/`.env.bak.round1026-s8`/`stash@{0}` целы); release readiness (bump 2.58.27 + README + cache-bust `?v=__APP_VERSION__`; откат `pre-round1026-s8`/`git revert`).
- Verdicts (3 спорные трактовки @Builder): **Q1** — аддитивный снапшот `summary_generator.py`/`summary_run_log.py` **в scope** (D2 + spec §19 «аддитивный снапшот прогона (in-memory)»), не незаявленный drift; **Q2** — линейные связи узлов по каноническому порядку пайплайна одного `run_id` **санкционированы** D6/§3 («подтверждённая линейная последовательность одного `run_id`»), не выдуманные (ветвление не достраивается, `hasBranch=false`); **Q3** — `_context_limit_info` в endpoint **не нарушение** D3 (чистый модуль `execution_graph_source.py` остаётся чистым; §25 запрещает преобразование внутри SVG/Vue, а не в роутере).
- [ ] **[L-R1026S8-1] [low, honesty/§3 edge]** — OPEN (non-blocking): `algorithm`-узел эмитится по одному `source_count` без filter-метрик (пустое окно / фильтр OFF) → `services/execution_graph_source.py:323-325`; spec D2 явно допускает `source_count` как вход узла, но рекомендация — требовать filter-derived поле либо явно задокументировать.
- [ ] **[L-R1026S8-2] [low, unused/§112]** — OPEN (non-blocking): `metrics.context` (`_context_limit_info`, `web/api/analytics.py:165-183,186`) вычисляется в endpoint, но UI `execMetricsRows` его не рендерит → «Без лимита» пользователю не видно (в перечне REQ-S8-09 контекст-лимита нет).
- [ ] **[L-R1026S8-3] [info, docs]** — OPEN: комментарий `tests/test_round1025_f8_registry.py:125` после bump читается как «S7 … 2.58.25 → 2.58.27» (фактически S7→2.58.26, S8→2.58.27).
- Info: mobile §29 (S8-специфичные CSS-маркеры) не покрыты отдельным тестом — существующий F6 §29-тест + вертикальный `.token-flow` (flex-column) сохраняются.
- **Новых Critical/High — нет.** Отдельного Scanner-approval не существует (Scanner удалён намеренно, 24.09.2026).
- **Handoff:** @Orchestrator → **APPROVED (единый gate: линза 1 + линза 2 пройдены)**; далее T-3430 (rework — не требуется, блокеров нет) → T-3431 merge (§79, ADR-1026-10 Accepted) → T-3432 archive → T-3433 deploy (2.58.27) → T-3434 handoff; live — PENDING OWNER VERIFICATION.

## Эпик 2 / S7 `summary-logging-runid-round1026` (T-3404, единый Reviewer gate — линза 2 focused change audit + миграция управляющих документов), 24.09.2026 — **APPROVED: к деплою ДА (C0/H0/блокирующих 0; миграция корректна; live — PENDING OWNER VERIFICATION)**

Baseline — HEAD `f774ecc` == annotated-тег `pre-round1026-s7` (tag-obj `bd7c822` → `f774ecc`); правки **НЕ закоммичены** (36 M + 4 ??; состав = итер.3 (35 M) + `plans/project.md` миграции). Отчёт и актуальные биндинги (Reviewed-Commit / Working-Tree-Hash / Spec-Hash): `plans/features/summary-logging-runid-round1026/review.md`, раздел «Единый gate T-3404 (линза 2 + миграция)». Воспроизведено @Reviewer: pytest `.venv` **8890/0** (114.40 s); S7-файл **35/35**; JS **45/45**; `git diff --check`=0; каталог импортом **469/426/444/100/98/21** (Δ=0), `APP_VERSION` **2.58.26**; **Δ DDL=0** (`db/**` вне diff, untracked в `db/` нет); `PUBLISH_*` в коде = **0** (grep + `test_publish_events_absent_gated`); `routes.py`/`param_catalog.py`/`image_generation.py`/`telegram_send.py`/`summary_xml.py`/`summary_article_formatter.py` вне diff; **0 новых внешних зависимостей** (манифесты вне diff); 2-вызовность (`await_count==2`), dry-run 0/0/0; R17-пины (сырой текст/URL/ключ не текут); R18 (тег/бэкап `var/backups/s7-round1026-20260924-003537/`/`.env.bak.round1026-s7`/`stash@{0}` целы); release readiness (bump 2.58.26 в `config/settings.py` + `README.md` + cache-bust `?v=__APP_VERSION__`; откат `pre-round1026-s7`/`git revert`).
- [x] **[B-R1026S7-1] [medium, requirement gap §109]** — **CLOSED, перепроверено по коду/тестам/прогону:** `summary_generator._run` заполняет `ctx.model`/`ctx.provider` (host) на OFF-пути best-effort; пин `test_llm_failure_summary_failed_http`.
- [x] **[B-R1026S7-2] [medium, requirement gap §109 / SC-07]** — **CLOSED, перепроверено:** `summary_run_log.attempts_of()` — текст (`after N attempts`) → атрибут → `None`, в лог только число; пины на реальные тексты `llm_client` (`test_attempts_of_real_llm_texts`, L1/L2).
- [x] **[L-R1026S7-3] [low, R17]** — **CLOSED:** `SUMMARY_TEST_FORMAT_ERROR` без `exc_info` (+`error_type`), пин `test_dry_run_format_error_test_code`.
- [ ] **[L-R1026S7-1] [low, R17, pre-existing S1, вне diff]** — OPEN (non-blocking): `FILTER_ERROR` с `exc_info=True` → S8/хотфикс.
- Info: **[I-R1026S7-1]** (устаревший машинный чекпоинт) — **CLOSED** (@Orchestrator, миграция; revision 4).
- **Миграция управляющих документов (@Orchestrator, 24.09.2026) — проверена:** исполняемых/будущих назначений и handoff на Scanner нет (T-3404 → @Reviewer-линза 2; S7/S8/S10 в `backlog.md` — без Scanner; `project.md` — «миграции проверяет @Reviewer»); исторические упоминания сохранены (`plans/reports/**`, `plans/archive/**`, `metrics.md`, исторические разделы); обязанности Scanner включены в единый gate и фактически исполнены (прогоны/инварианты выше); отдельного артефакта Scanner нет (`round1026_s7_scanner_audit.md` отсутствует); `plans/current_task.md` не изменялся (mtime 2026-09-23, gitignored); `plans/archive/**` не тронут; product code миграцией не менялся (untracked-код байт-в-байт == итер.3: `summary_run_log.py` `B2B98024…`, JS-тест `2DF92F44…`, pytest-файл `A13DC956…`; все code-файлы mtime ≤ 02:04, правки планов 02:16–02:31).
- **Новых Critical/High — нет.** Отдельного Scanner-approval не существует (Scanner удалён намеренно, 24.09.2026).
- **Handoff:** @Orchestrator → **APPROVED (единый gate: линза 1 итер.3 + линза 2 пройдены)**; далее T-3406 merge → T-3407 archive → T-3408 deploy (2.58.26) → T-3409 handoff; live — PENDING OWNER VERIFICATION.

## Эпик 2 / S9 `summary-testing-ui-round1026` (T-3374, Step 6 @Scanner, ИТЕРАЦИЯ 2 — rework T-3375), 24.09.2026 — **SCANNED: к деплою ДА (C0/H0/блокирующих Medium 0; Low 5 + 1 новый Low doc-drift); live — PENDING OWNER VERIFICATION**

Baseline — HEAD `cc6105c` == annotated-тег `pre-round1026-s9` (`for-each-ref` tag `9f4305a` → `git rev-list -n 1` = `cc6105c`); правки **НЕ закоммичены**. Отчёт: `plans/reports/round1026_s9_scanner_audit.md` (итерация 2). Воспроизведено @Scanner: pytest `.venv` **8854/0** (120.75 s), JS **44/44** + `node --check` OK, каталог импортом **469/426/444/100/98/21**, `APP_VERSION` 2.58.25, `git diff --check`=0, `summary_generator.py` **55+/0−**, **Δ DDL=0**, R18 OK; свой шпион-прогон → 0 публикаций/памяти/`generate_image`, `await_count==2`, флаг до==после.
- [x] **[S-R1026S9-1] [medium, ui-render] — RESOLVED** (== `B-R1026S9-2` High): 4 пробы payload (`no-generator`/`error_result`/`running`/`window-read-error`) → полные `metrics`/`artifacts`/`display` + диагностика; guards не скрывают успех (JS-блок g).
- [x] **[S-R1026S9-2] [low, robustness] — RESOLVED** (== `L-R1026S9-3`): `_purge`/эвикция исключают `running`; пробы — KEPT после TTL, сохранён при переполнении.
- [x] **[S-R1026S9-3] [low, contract/docs] — RESOLVED** (== `L-R1026S9-4`) для spec §5.2 + README; **остаточный doc-drift → [S-R1026S9-5] ниже.**
- [x] **[S-R1026S9-4] [low, metrics] — RESOLVED** (== `L-R1026S9-5`): reset `_filter_metrics` в `build_test_rows`; проба fail-open → `{}`/0.
- [ ] **[S-R1026S9-5] [low, contract/docs] — NEW, OPEN (non-blocking):** `services/summary_test_run.py:489` docstring и `adr-1026-8` D4 всё ещё указывают `503 (TEST_NO_GENERATOR)`; реализация + spec §5.2 — `202`/`200`+`status="error"`. Fix: docstring + ADR.
- [ ] **[L-R1026S9-2] [low, env/evidence]** — OPEN (non-blocking): 5 пред-существующих падений rich-media на глобальном `py -3` (aiogram 3.29.1), воспроизведены на base `cc6105c`; `.venv` (3.31.0) — 0.
- [ ] **[L-R1026S9-6] [low, shared state]** — OPEN (non-blocking): dry-run пишет `SummaryGenerator._filter_metrics[chat_id]`.
- [ ] **[L-R1026S9-7] [low, API]** — OPEN (non-blocking): `window_hours` клампится вместо 422.
- [ ] **[L-R1026S9-8] [low, R17]** — OPEN (non-blocking): catch-all `exc_info=True` в `_execute`/чтении окна.
- Info: **[I-R1026S9-1]** `present_result.has_more` — эвристика; **[I-R1026S9-2]** == `L-R1026S9-8`.
- **Новых Critical/High — нет.** Low-фиксы без регрессий (retention/fail-open + pytest 8854/0). Живой ON-путь (S6/S10) — GATED.
- **Handoff @Scanner:** @Orchestrator → **SCANNED — к деплою ДА**; Low/Info — owned follow-up; далее @DevOps T-3378; live — PENDING OWNER VERIFICATION.

## Эпик 2 / S9 `summary-testing-ui-round1026` (T-3373, Step 5 @Reviewer, ИТЕРАЦИЯ 2), 23.09.2026 — **APPROVED: прежние блокеры закрыты (B-R1026S9-2 High UI-краш + B-R1026S9-1 Medium «Процент отсева»); остаток Low/Info — non-blocking; live — PENDING OWNER VERIFICATION**

Baseline — HEAD `cc6105c` == annotated-тег `pre-round1026-s9` (`git cat-file -p` → `cc6105c`); правки **НЕ закоммичены** (33 M + 5 ??). Отчёт: `plans/features/summary-testing-ui-round1026/review.md`. @Reviewer итерация 2: pytest `.venv` **8854/0**, JS **44/44**, каталог **469/426/444/100/98/21**, `git diff --check`=0, `summary_generator.py` **55+/0−**, **Δ DDL=0**, `APP_VERSION` 2.58.25, R18 OK.
- [x] **[B-R1026S9-2] [high, ui-render]** — **RESOLVED** (подтверждено кодом/тестами/прогоном): полные `metrics/artifacts/display` на всех путях (`_base_result`/`present_result`/`error_result`/`empty_payload`/`_result_payload`/`_execute`) + guard `v-if` в `index.html` и computed-guard в `app.js`; диагностика видна; тесты `test_no_generator_error_payload_contract`, `test_error_result_has_diagnostics_and_full_structures`, `test_empty_payload_running_contract`, `test_execute_exception_payload_contract`, JS (g).
- [x] **[B-R1026S9-1] [medium, requirement gap]** — **RESOLVED**: `data-summary-test-drop` «Процент отсева» + computed `summaryTestDropPercent` (null → «Нет данных»); JS (h).
- [x] **[L-R1026S9-1] [low, docs/R18]** — **RESOLVED**: `evidence.md`/`tasks.md` → `cc6105c` (проверено `git cat-file -p`).
- [x] **[L-R1026S9-3] [low, robustness]** — **RESOLVED**: `_purge`/эвикция исключают `status=="running"`; `test_store_ttl_keeps_running`, `test_store_eviction_keeps_running`.
- [x] **[L-R1026S9-4] [low, contract/docs]** — **RESOLVED**: spec §5.2 (503 убран), §7 `TEST_RUN_FAILED`, README-оговорка об обложке.
- [x] **[L-R1026S9-5] [low, metrics]** — **RESOLVED**: reset `_filter_metrics` в `build_test_rows` + тест.
- [ ] **[L-R1026S9-2] [low, env/evidence]** — OPEN (non-blocking): 5 пред-существующих падений rich-media на глобальном `py -3` (aiogram 3.29.1), воспроизведены на base `cc6105c`; `.venv` (3.31.0) — 0.
- [ ] **[L-R1026S9-6] [low, shared state]** — OPEN (non-blocking): dry-run пишет `SummaryGenerator._filter_metrics[chat_id]`.
- [ ] **[L-R1026S9-7] [low, API]** — OPEN (non-blocking): `window_hours` клампится вместо 422.
- [ ] **[L-R1026S9-8] [low, R17]** — OPEN (non-blocking): catch-all `exc_info=True` в `_execute`/чтении окна.
- Info: **[I-R1026S9-1]** `present_result.has_more` — эвристика.
- **Handoff @Reviewer:** @Orchestrator → **APPROVED**; далее @Scanner T-3374 + @DevOps T-3378; live — PENDING OWNER VERIFICATION.

## Эпик 2 / S9 `summary-testing-ui-round1026` (T-3373, Step 5 @Reviewer, ИТЕРАЦИЯ 1), 23.09.2026 — **CHANGES REQUESTED: 2 блокирующих (High UI-краш error-результатов + Medium §112 «Процент отсева»); Low non-blocking; live — PENDING OWNER VERIFICATION**

Baseline — HEAD `cc6105c` == annotated-тег `pre-round1026-s9` (`git rev-parse pre-round1026-s9^{commit}` = `cc6105c`); правки **НЕ закоммичены** (33 M + 5 ??). Отчёт: `plans/features/summary-testing-ui-round1026/review.md`. @Reviewer: pytest `.venv` **8847/0**, JS **44/44**, каталог **469/426/444/100/98/21**, `git diff --check`=0, `summary_generator.py` 51+/0−, **Δ DDL=0**, `APP_VERSION` 2.58.25, R18 OK.
- [ ] **[B-R1026S9-2] [high, ui-render, BLOCKING]** — **OPEN; подтверждён @Reviewer независимо (== [M-R1026S9-1] @Scanner).** `web/index.html:490/:511` — error-результаты (`TEST_NO_GENERATOR`, ошибка чтения окна, исключение в `_execute`) не содержат `metrics`/`artifacts` → TypeError в render Vue, диагностика §5.3/§7 не видна. Проба: `present_result(_base_result(status="error"))` → `metrics={}`, `artifacts={}`. **Fix:** guard в HTML и/или пустые `metrics`/`artifacts`/`display` в `_result_payload`. **Verify:** JS-маркер + re-review.
- [ ] **[B-R1026S9-1] [medium, requirement gap, BLOCKING]** — **OPEN.** `web/index.html` L484–497 не рендерит `metrics.drop_percent` (§112 «Процент отсева»; tasks инвариант 8; REQ-S9-09). **Fix:** строка «Процент отсева: …» (null → «Нет данных»).
- [ ] **[L-R1026S9-1] [low, docs/R18]** — тег фактически `cc6105c`, в `evidence.md`/`tasks.md` T-3345 указан `ae5a147`. OPEN.
- [ ] **[L-R1026S9-2] [low, env/evidence]** — 5 пред-существующих падений rich-media на глобальном `py -3` (aiogram 3.29.1), воспроизведены на base `cc6105c`; `.venv` (3.31.0) — 0. OPEN.
- [ ] **[L-R1026S9-3] [low, robustness]** — `_RunStore._purge`/эвикция не исключают running (== L-R1026S9-1 @Scanner). OPEN.
- [ ] **[L-R1026S9-4] [low, contract/docs]** — spec §5.2 обещает 503; реализация 202+`status="error"` (== L-R1026S9-2 @Scanner). OPEN.
- [ ] **[L-R1026S9-5] [low, metrics]** — fail-open `_apply_filter` не пишет `_filter_metrics` (== L-R1026S9-3 @Scanner). OPEN.
- [ ] **[L-R1026S9-6] [low, shared state]** — dry-run пишет `SummaryGenerator._filter_metrics[chat_id]`. OPEN.
- [ ] **[L-R1026S9-7] [low, API]** — `window_hours` клампится вместо 422 (spec §5.2 vs §4.2). OPEN.
- [ ] **[L-R1026S9-8] [low, R17]** — catch-all `exc_info=True` в `_execute`/чтении окна (== I-R1026S9-2 @Scanner). OPEN.
- **Инварианты OK:** 0 публикаций/0 памяти/0 `generate_image` (шпионы); ON per-run ровно 2 вызова, флаг не читается/не пишется; `_run`/`_run_hybrid_l2` байт-в-байт; async 202+polling + in-memory TTL/≤20; global admin; флаг default ON + hot-OFF false → 404+скрытие; fail-closed-коды `TEST_*`; S6 GATED; Δ DDL=0; Δ каталога=0; CSP/zero-build; R17/R18; bump 2.58.25.
- **Handoff @Reviewer:** @Orchestrator → **CHANGES REQUESTED**; @Builder — [B-R1026S9-2] + [B-R1026S9-1] → повторный прогон → re-review.

## Эпик 2 / S9 `summary-testing-ui-round1026` (T-3374, Step 6 @Scanner) — 23.09.2026 — **NOT READY: C0/H0; 2 блокирующих (B-R1026S9-1 Medium + UI-render S-R1026S9-1 Medium, эскалирован @Reviewer в B-R1026S9-2 High); Low/Info non-blocking**

Baseline — HEAD `cc6105c`; правки **НЕ закоммичены** (33 M + 5 ?? кода/тестов + каталог фичи). Отчёт: `plans/reports/round1026_s9_scanner_audit.md`. **ID @Scanner — `S-R1026S9-*`** (переименовано из `M-R1026S9-1`/`L-R1026S9-1..4`; карта: `S-R1026S9-1`==`M-R1026S9-1`==эскалация @Reviewer `B-R1026S9-2 High`; `S-R1026S9-2`==`L-R1026S9-1 @Scanner`==`L-R1026S9-3 @Reviewer`; `S-R1026S9-3`==`L-R1026S9-2 @Scanner`==`L-R1026S9-4 @Reviewer`; `S-R1026S9-4`==`L-R1026S9-3 @Scanner`==`L-R1026S9-5 @Reviewer`). Воспроизведено @Scanner: pytest **8847/0**, JS **44/44** + `node --check` OK, каталог **469/426/444/100/98/21**, `APP_VERSION` 2.58.25, `git diff --check`=0, R18 (тег `pre-round1026-s9`→`cc6105c`, `stash@{0}`); шпион-проба `run_summary_test` → 0 публикаций/памяти/`generate_image`, `await_count==2`.
- [ ] **[B-R1026S9-1] [medium, requirement-gap, BLOCKING] — @Reviewer Step 5, подтверждён @Scanner (OPEN).** §112 «Процент отсева» не рендерится: `Select-String "отсев|drop_percent" web/index.html web/app.js` → **0**, при том что `_metrics` возвращает `drop_percent`. **Fix:** строка «Процент отсева: …» (`null` → «Нет данных»).
- [ ] **[S-R1026S9-1] [medium, ui-render, BLOCKING] — == [M-R1026S9-1] @Scanner, эскалирован @Reviewer в [B-R1026S9-2] High.** `web/index.html:490/:511` — без guard читаются `metrics.tokens.l1`/`artifacts.source.length`; error-результаты (`TEST_NO_GENERATOR`, ошибка чтения окна, исключение в `_execute`) не содержат `metrics`/`artifacts` → TypeError в render Vue, диагностика §5.3/§7 не видна. **Fix:** `v-if="summaryTest.result.metrics && summaryTest.result.metrics.tokens"` (+ `artifacts`) и/или всегда отдавать пустые `metrics`/`artifacts` из `_base_result` в `_result_payload`.
- [ ] **[S-R1026S9-2] [low, robustness] — == L-R1026S9-1 @Scanner == L-R1026S9-3 @Reviewer.** `web/api/summary_test.py:84-102` — `_purge`/эвикция не исключают running: прогон >15 мин вычищается (poll 404 + возможен повторный параллельный запуск). **Fix:** исключать `status=="running"` из purge/эвикции.
- [ ] **[S-R1026S9-3] [low, contract/docs] — == L-R1026S9-2 @Scanner == L-R1026S9-4 @Reviewer.** spec §5.2 обещает `503 (TEST_NO_GENERATOR)` — реализация 202 + 200/`status="error"`; README/ADR «0 `generate_image`» без оговорки про подтверждение обложки. **Fix:** 503-маппинг либо правка формулировок.
- [ ] **[S-R1026S9-4] [low, metrics] — == L-R1026S9-3 @Scanner == L-R1026S9-5 @Reviewer.** `services/summary_generator.py:808-813` fail-open `_apply_filter` не пишет `_filter_metrics` → `build_test_rows:625` вернёт устаревшие `status`/`restored_count` предыдущего прогона.
- Info: **I-R1026S9-1** (`present_result` `has_more` — сумма по всем list-артефактам, эвристика); **I-R1026S9-2** (== `L-R1026S9-8 @Reviewer`: `SUMMARY_TEST_*_FAILED` с `exc_info=True`; секретов/сырых текстов не найдено).
- **Инварианты OK:** Δ DDL=0; Δ каталога=0; `routes.py`/`image_generation.py`/`telegram_send.py`/`database.py`/`pg_db.py`/`param_catalog.py` вне diff; `summary_generator.py` аддитивно (51+/0−); ON живого пайплайна не активируется; CSP/zero-build; флаг default ON, OFF→404+скрытие вкладки; §112 «Нет данных»/«Без лимита»; маркер-тесты не ослаблены.
- **Handoff @Scanner:** @Orchestrator → **NOT READY** (блокируют B-R1026S9-1 + S-R1026S9-1/B-R1026S9-2; возврат в @Builder → @Reviewer + @Scanner). Low/Info — owned follow-up.

## Эпик 2 / S5 `summary-l2-writer-formatter-round1026` (T-3338, Step 6 @Scanner) — re-audit итерация 2 (rework T-3339), 23.09.2026 — **SCANNED: C0/H0; блокирующих Medium 0; Low/Info non-blocking — к деплою ДА по коду (OFF-безопасное; ON — GATED; live — PENDING OWNER VERIFICATION)**

Baseline — HEAD `e3ea608` == annotated-тег `pre-round1026-s5` (`a6be444`→`e3ea608`); правки **НЕ закоммичены** (59 M + 6 ??). Отчёт: `plans/reports/round1026_s5_scanner_audit.md` (итерация 2). Воспроизведено @Scanner: pytest **8807/0**, JS **30/0** + `node --check` **43/43**, целевые L1/L2/F8/IA **222 passed**, каталог **469/426/444/100/98/21**, F8 `--check` **OK**, **Δ DDL=0**, `APP_VERSION` 2.58.24, `git diff --check`=0, R18 OK.
- [x] **[B-R1026S5-1] [medium, data-integrity, BLOCKING]** → **RESOLVED, подтверждено @Scanner независимо (итерация 2).** Без BOM (`7B 0D 0A`), 0 mojibake (U+2550–256C=0/U+2591–2593=0/байт `E2 95 A8`=0), `nav_titles` «Модули»/«ИИ»/«Память» байт-точно; `git diff HEAD --numstat`=**3+/2−** (только `_provenance.note`, `counts.REGISTRY 468→469`, +ключ `prompts.summary_l2_writer_system_prompt`); отступ 1; LF↔CRLF нормализуется git.
- [x] **[S-R1026S5-1] [medium, architecture-drift, ON-gated]** → **RESOLVED, подтверждено @Scanner независимо (итерация 2).** ON-guard после S1/S2 (`_apply_filter`=`filter_window`+`restore_context` → `xml_rows`); `_run_hybrid_l2(chat_id, xml_rows, focus, correlation_id)`; `trigger_message_id`→S1, `focus`→`focus_block` в `run_l1`; ON = ровно 2 вызова (`run_l1`+`run_l2`, по одному `await call`); OFF-тело `_run` не изменено.
- [x] **[S-R1026S5-2] [low]** → **RESOLVED** (проба: `'…'`/`‚…‘`/`「…」`/`『…』` снимаются). **[S-R1026S5-3] [low]** → **RESOLVED** (`TestCanon::test_canon_doc_byte_identical`, 7/7 `-k canon`). **[S-R1026S5-4] [low]** → **RESOLVED** (проба limit=20: 0 висячих `&`, осколки ≤ limit). **[S-R1026S5-6] [info]** → **RESOLVED**.
- [x] **L-R1026S5-1** (мёртвый импорт) → **RESOLVED**; **L-R1026S5-2** (прямой OFF-тест) → **RESOLVED**.
- [ ] **OPEN (non-blocking):** L-R1026S5-3 (+1 `_chat_limit` на OFF), L-R1026S5-4 (§106-классы → **S6**), L-R1026S5-5 (sanitize после escape), **L-R1026S5-6** (`'[^']*'` снимает апострофы `It's John's`→`Its Johns`, `Don't`→`Dont`; содержимое сохраняется; подтверждён @Scanner, побочный от S-R1026S5-2; русскоязычный продукт + ON gated → не блокер), S-R1026S5-5 [info, env] (pytest зелёный только на `.venv`/aiogram 3.31.0).
- [ ] **S-R1026S5-7 [info, new, ON-gated, S6-note]** `services/summary_generator.py:378-380` — ON-return до `:405-409` → ON пропускает `fire_and_forget(memory.memorize_facts(..., "chat_history"))` (единственный вызов в summary-пути `:407`). Соответствует ADR-1026-7 D5/spec §7.1 (не дефект кода); при активации ON память перестанет получать `chat_history`-факты саммари. **Fix (S6):** вызывать `memorize_facts` и в ON либо зафиксировать изменение в ADR. (Не блокирует.)
- **Инварианты OK:** Δ DDL=0; Δ каталога=+1 (469/426/444/100/98/21); `pg_db.py`/`routes.py`/`database.py` вне diff (`routes.py`=`4b652cb1…` == `ROUTES_SHA256_F11`, fixture-хэш исторический by design L-F9S-4); `APP_VERSION` 2.58.24; F8 `--check` OK; R17/R18; `git diff --check`=0; ON = 2 вызова; OFF байт-в-байт.
- **Unavailable:** ON-путь в проде — GATED (default OFF, моки); live-приёмка Эпика 1 — PENDING OWNER VERIFICATION.
- **Handoff @Scanner:** @Orchestrator → **SCANNED — к деплою ДА по коду** (OFF-безопасное состояние; ON — только после live-приёмки Эпика 1). S6-items: L-R1026S5-4, S-R1026S5-7.

## Эпик 2 / S5 `summary-l2-writer-formatter-round1026` (T-3337, Step 5 @Reviewer) — re-review итерация 2 (rework T-3339), 23.09.2026 — **APPROVED: C0/H0; блокирующих Medium 0; Low/Info non-blocking; ON — GATED; live — PENDING OWNER VERIFICATION**

Baseline — HEAD `e3ea608` == annotated-тег `pre-round1026-s5`; правки **НЕ закоммичены** (59 M + 6 ??). Отчёт: `plans/features/summary-l2-writer-formatter-round1026/review.md`. Воспроизведено @Reviewer: pytest **8807/0**, JS **30/0** (43 файла), 3 L2-тест-файла **70 passed**, F8/IA/JS-набор **66 passed**, `git diff --check`=0, каталог **469/426/444/100/98/21**, F8 `--check` **OK**, **Δ DDL=0**, `APP_VERSION` 2.58.24, R18 OK.
- [x] **[B-R1026S5-1] [medium, data-integrity, BLOCKING]** → **RESOLVED 23.09.2026 (T-3339 @Builder; подтверждено @Reviewer).** Фикстура восстановлена из `e3ea608`; `git diff HEAD --numstat` = **3+/2−**; UTF-8 без BOM, отступ 1, **0** mojibake; JSON-дифф = только нота/`REGISTRY 468→469`/+1 ключ; `test_round1025_f8_registry`/`test_ia_inventory_round1025` + F8 `--check` зелёные.
- [x] **[S-R1026S5-1] [medium, architecture-drift, ON-gated]** → **RESOLVED 23.09.2026 (T-3339; подтверждено @Reviewer).** ON-ветка после S1/S2 (`_apply_filter` = фильтр+restore → `xml_rows` → ON); `focus`→`focus_block` в L1; `trigger_message_id` учтён S1; тест `TestOnPathAppliesS1S2` (нетривиальный: спай `filter_window`/`restore_context`).
- [x] **[S-R1026S5-2] [low, hardening]** → **RESOLVED** (`_QUOTE_RE`/`_strip_quotes`: `'…'`, `‚…‘`, `「…」`, `『…』`).
- [x] **[S-R1026S5-3] [low, evidence/test-gap]** → **RESOLVED** (`TestCanon::test_canon_doc_byte_identical` для L2).
- [x] **[S-R1026S5-4] [low, edge]** → **RESOLVED** (`_split_safe` не рвёт HTML-сущность; `test_chunk_does_not_split_html_entity`).
- [x] **S-R1026S5-6 [info, noise]** → **RESOLVED** (переформатирование фикстуры устранено фиксом [B-R1026S5-1]).
- [ ] **S-R1026S5-5 [info, env]** — ACTIVE (нужен `.venv`/aiogram 3.31.0 для полного pytest; фиксируется для воспроизводимости CI).
- [x] **L-R1026S5-1** (мёртвый импорт `format_plain_html`) → **RESOLVED**; **[L-R1026S5-2]** (нет прямого OFF-теста `_run`) → **RESOLVED** (`TestOffPathDirect`).
- [ ] **OPEN (non-blocking):** L-R1026S5-3 (доп. `get_chat_param` на OFF), L-R1026S5-4 (§106-классы → **S6**, закреплено в `tasks.md`/`evidence.md`), L-R1026S5-5 (sanitize после escape), **L-R1026S5-6 [low, new]** (`'[^']*'` может склеить апострофы `don't, it's` → `dont, its`; побочный от S-R1026S5-2; продукт русскоязычный, ON gated → не блокер).
- **Unavailable:** ON-путь в проде — GATED (default OFF, гейт S6/S10+D4, моки); live-приёмка Эпика 1 — PENDING OWNER VERIFICATION.
- **Handoff @Reviewer:** @Orchestrator → **APPROVED** (OFF-безопасное состояние к merge/деплою); ON — только после live-приёмки Эпика 1.

## Эпик 2 / S5 `summary-l2-writer-formatter-round1026` (T-3338, Step 6 @Scanner) — 23.09.2026 — **SCANNED: C0/H0; 1 блокирующий Medium (data-integrity, подтверждён); 1 Medium ON-gated (S6); Low 3 (+5 @Reviewer подтверждены); Info 2 — НЕ к деплою**

Baseline — HEAD `e3ea608` == annotated-тег `pre-round1026-s5`; правки **НЕ закоммичены** (59 M + 6 ??). Отчёт: `plans/reports/round1026_s5_scanner_audit.md`. Bump `APP_VERSION` 2.58.24; **Δ DDL=0**; **Δ каталога=+1** (469/426/444/100/98/21; F8 `--check` OK). Воспроизведено: pytest **8801/0** (только `.venv`, aiogram 3.31.0), JS **30/0** (43 файла), 64 теста, `git diff --check`=0, sha256 repin OK, R18 OK.
- [ ] **[B-R1026S5-1] [medium, data-integrity, BLOCKING, @Builder, confirmed-by-Scanner]** `tests/fixtures/round1025/catalog_baseline.json` — 302 mojibake-символа (U+2550–256C/U+2591–2593) в `L4` (`_provenance.note`) и `L224–226` (`nav_titles.{modules,ai,memory}`); hex `E2 95 A8 D0 AC…` = двойная перекодировка `"Модули"`; в `e3ea608` — 0. Нарушает ADR-1026-2/tasks S5 инв. №12. Тесты/F8 `--check` эти поля не читают → ложно-зелёный. **Fix:** восстановить из `e3ea608` + только 2 санкц. правки (`registry_keys += prompts.summary_l2_writer_system_prompt`, counts 468→469), UTF-8 без BOM, исходный отступ. **Verify:** JSON-дифф = только +1 ключ/счётчики/нота; 0 mojibake; `test_round1025_f8_registry`/`test_ia_inventory_round1025` зелёные. → **RESOLVED (re-review итерация 2, T-3337).**
- [ ] **[S-R1026S5-1] [medium, architecture-drift, ON-gated, S6-owned, @Builder/@Architect]** `services/summary_generator.py:349-354` (guard до S1/S2) + `:522-597` (`_run_hybrid_l2`) — ON-ветка берёт сырые `rows` → `build_l1_payload` → `run_l1`, **не применяя** S1 `_apply_filter`/S2 `restore_context` (вызов только в OFF `:377`; `_restore` `:772/:799`); `focus`/`trigger_message_id` не используются (grep=0). Расходится с ADR-1026-7 D5 («врезка … после S1/S2») и §80 («фильтр → восстановление → L1»); spec §7.1 противоречит D5. Прод не затронут (флаг OFF), но при включении ON — тихая регрессия S1/S2/`focus`. **Fix (S6):** `_apply_filter` до `build_l1_payload` + прокинуть `focus`/`trigger_message_id`; либо AMEND D5/§80 с обоснованием. → **RESOLVED (re-review итерация 2, T-3337).**
- [ ] **[S-R1026S5-2] [low, hardening]** `services/summary_l2_writer.py:101` — `_QUOTE_RE` не покрывает одиночные кавычки `'…'`; проба `Он 'придумал такое' на ходу.` → `ok` с сохранённой выдуманной цитатой (для `"…"`/`«…»` кавычки снимаются). **Fix:** расширить regex (одиночные/парные кавычки). → **RESOLVED (re-review итерация 2, T-3337).**
- [ ] **[S-R1026S5-3] [low, evidence/test-gap]** `tests/test_summary_l2_writer.py::TestCanon` не содержит byte-identity проверки канона L2 в `plans/docs/canon/architecture.md` (у L1 — `test_canon_doc_byte_identical`). Док фактически байт-идентичен коду (проверено @Scanner), но `evidence.md`/`review.md` заявляют покрытие неверно. **Fix:** добавить тест по образцу L1; поправить evidence. → **RESOLVED (re-review итерация 2, T-3337).**
- [ ] **[S-R1026S5-4] [low, edge]** `services/summary_article_formatter.py:207-211` — при вынужденной нарезке блока (`len(block)>limit`) HTML-сущность может быть разрезана (`&am`+`p;`). В проде недостижимо (абзац ≤900 < 4096). **Fix:** резать по границам сущностей/слов. → **RESOLVED (re-review итерация 2, T-3337).**
- [ ] **S-R1026S5-5 [info, env]** Полный pytest зелёный только на `.venv` (aiogram 3.31.0); глобальный `py -3` (aiogram 3.29.1) → 5 ложных `ImportError: InputRichMessageMedia`. Не дефект кода; для воспроизводимости CI.
- [ ] **S-R1026S5-6 [info, noise]** `tests/fixtures/round1025/catalog_baseline.json` переформатирован (отступ 1→2, 721+/720−) — устраняется фиксом [B-R1026S5-1]. → **RESOLVED (re-review итерация 2, T-3337).**
- **@Reviewer Low подтверждены @Scanner (OPEN, owned):** L-R1026S5-1 (мёртвый импорт `format_plain_html`), L-R1026S5-2 (нет прямого OFF-baseline-теста `_run`), L-R1026S5-3 (доп. `get_chat_param` в OFF), L-R1026S5-4 (§106-классы ошибок → S6), L-R1026S5-5 (sanitize после escape).
- **Инварианты OK:** OFF-тело `_generate_two_call` не изменено + ленивые импорты L2; ON = ровно 2 вызова (моки); `content_format="auto"` default байт-в-байт; `web/**`/`summary_xml.py`/`summary_filter.py`/`summary_context_restore.py`/`image_generation.py`/`pg_db.py`/`database.py`/`current_task.md` вне diff; нет CDN/inline/eval; форматтер экранирует HTML; fail-closed §106; канон `PREV_*`/миграция/ROLLBACK идемпотентны; Рассказчик/Редактор/`digest` REUSE; Δ DDL=0; Δ каталога=+1; маркер-тесты заменены, не отключены; R17/R18; гигиена индекса.
- **Unavailable:** ON-путь в проде — GATED (S6/S10+D4, моки); live-приёмка Эпика 1 — PENDING OWNER VERIFICATION.
- **Handoff @Scanner:** @Orchestrator → **SCANNED — НЕ к деплою** (блокер [B-R1026S5-1]); @Builder — фикс фикстуры → re-review; [S-R1026S5-1] — обязательный S6-item.

## Эпик 2 / S5 `summary-l2-writer-formatter-round1026` (T-3337, Step 5 @Reviewer) — 23.09.2026 — **CHANGES REQUESTED: C0/H0; 1 блокирующий Medium (data-integrity); Low 5**

Baseline — HEAD `e3ea608` == annotated-тег `pre-round1026-s5`; правки **НЕ закоммичены** (59 M + 6 ??). Отчёт: `plans/features/summary-l2-writer-formatter-round1026/review.md`. Bump `APP_VERSION` 2.58.24; **Δ DDL=0**; **Δ каталога=+1** (469/426/444/100/98/21; F8 `--check` OK). Воспроизведено: pytest **8801/0**, JS **30/0** (43 файла), 64 новых теста, `git diff --check`=0, sha256 repin OK.
- [ ] **[B-R1026S5-1] [medium, new, data-integrity, BLOCKING, @Builder]** `tests/fixtures/round1025/catalog_baseline.json` — файл перезаписан (721+/720−, отступ 1→2) с двойной перекодировкой русского текста: `nav_titles.{modules,ai,memory}` (`"Модули"`→`"╨М╨╛╨┤╤Г╨╗╨╕"`) и `_provenance.note` (302 mojibake-символа; в `e3ea608` — 0). Нарушает ADR-1026-2 (обновление фикстуры, не порча) и tasks.md S5 инв. №12. Тесты/F8 `--check` эти поля не читают → ложно-зелёный. **Fix:** восстановить из `e3ea608` + только 2 санкц. правки (новый ключ `prompts.summary_l2_writer_system_prompt`, counts 468→469), UTF-8 без BOM, исходный отступ. **Verify:** JSON-дифф к `e3ea608` = только +1 ключ/счётчики/нота; `tests/test_round1025_f8_registry.py`, `tests/test_ia_inventory_round1025.py` зелёные. → **RESOLVED (re-review итерация 2, T-3337).**
- [ ] **[L-R1026S5-1] [low, new, cleanup]** `services/summary_generator.py::_deliver_l2_plain` — мёртвый импорт `format_plain_html` (не используется). **Fix:** убрать из импорта. → **RESOLVED (re-review итерация 2, T-3337).**
- [ ] **[L-R1026S5-2] [low, new, evidence]** OFF-идентичность `_run` доказана только тестом `_generate_two_call` + инспекцией исходника; нет теста прямого сравнения вывода `_run` в OFF с baseline. Тело OFF-ветки в diff не менялось → не блокер. **Fix:** добавить прямой byte/behavior-тест OFF-цепочки `_run`. → **RESOLVED (re-review итерация 2, T-3337).**
- [ ] **[L-R1026S5-3] [low, new, perf]** `_run` добавляет один `get_chat_param("flags.summary_hybrid_l2_enabled")` до OFF-ветки (fail-safe → False). Поведение идентично; «строго байт-в-байт» верно по телам кода. (Info-level; фикс не обязателен.)
- [ ] **[L-R1026S5-4] [low, new, traceability, S6]** §106-классы `SUMMARY_GENERATION_FAILED`/`COVER_GENERATION_FAILED`/`RICH_MESSAGE_SEND_FAILED`/`TEXT_FALLBACK_FAILED` не реализованы (0 вхождений в коде), хотя T-3325 `[x]` и SC-09 требуют «4 класса различимы». Backlog S6 («коды ошибок §106») — дефер приемлем; согласовать отметку T-3325/SC-09 (закрываются в S6). ON gated — не блокер.
- [ ] **[L-R1026S5-5] [low, new, order]** Rich-путь: `send_rich_message` применяет `_maybe_sanitize` ПОСЛЕ `html.escape` (spec §5.2 — «sanitize ДО escape»); функционально безопасно (sanitize не трогает сущности). То же у `chunk_plain_blocks` (sanitize в `send_text`).
- **Вне diff (подтверждено):** `web/**`, `summary_xml.py`, `summary_filter.py`, `summary_context_restore.py`, `image_generation.py`, `pg_db.py`, `database.py`, `current_task.md`. R17 (логи L2_*/FORMAT_* без секретов/текстов) / R18 (тег→`e3ea608`, `stash@{0}`) — OK.
- **Unavailable:** ON-путь в проде — GATED (S6/S10+D4, моки); live-приёмка Эпика 1 — PENDING OWNER VERIFICATION.
- **Handoff @Reviewer:** @Builder — закрыть [B-R1026S5-1] → повторный прогон → @Orchestrator re-review.

## Эпик 2 / S4 `summary-fact-package-round1026` (Шаг 6, T-3301) — Step 6 @Scanner, 23.09.2026 — **SCANNED: код-блокеров нет; C0/H0; Medium 1 (процесс/gate); Low 2 (owned follow-up); Info 2 — к деплою ДА по коду**

Baseline — HEAD `59f5921` (annotated-тег `pre-round1026-s4` → `59f5921`); правки **НЕ закоммичены** (24 M + 6 ??). Отчёт: `plans/reports/round1026_s4_scanner_audit.md`. Bump `APP_VERSION` 2.58.23; **Δ DDL=0**; **Δ каталога=0** (468/426/443/100/98/21; F8 не переиздавался — N/A).
- [x] **[M-R1026S4-1] [medium, new, process/gate, не код-дефект]** `plans/features/summary-fact-package-round1026/review.md` отсутствует (T-3300 @Reviewer не закрыт; T-3301 формально зависит от T-3300). **Fix:** выполнить T-3300 → `review.md`; при findings — rework + повторные проверки; либо явное решение @Orchestrator. Независимые проверки @Scanner — зелёные (не код-блокер). (Аналог M-R1026S3-1.) → **RESOLVED 23.09.2026 (T-3300 @Reviewer): `review.md` создан, Status: Approved (C0/H0, блокирующих Medium нет); process gate снят.**
- [ ] **[L-R1026S4-1] [low, new, observability, owned → S5]** `services/summary_fact_package.py:251-253` — обрезка фрагмента >`FRAGMENT_MAX_CHARS=1000` инкрементирует только `metrics.fragment_char_truncated_count`, но не помечает пакет `truncated` и не даёт WARN (проба: текст 1500 симв. → `status=ok`, `truncated_count=0`, `fragment_char_truncated_count=1`). Спек §4.5 санкционирует сам лимит, но это расходится с политикой модуля «любое вытеснение → truncated/WARN» (§93 «не резать молча»). **Fix:** учитывать char-обрезку в `truncated`/WARN либо явно задокументировать. (Не блокирует; модуль не в живом пути.)
- [ ] **[L-R1026S4-2] [low, new, perf, owned → S5]** `services/summary_fact_package.py:382-412` — `_enforce_budget` на каждом вытеснении заново сериализует JSON и считает `count_tokens` по всему остатку (O(n²)); проба 17 тем × 30 фрагментов × 1000 симв. при limit=199000 → 341 вытеснение, **0.29 s** CPU. **Fix:** инкрементальная оценка/батч-вытеснение. (Не блокирует.)
- [ ] **[L-R1026S4-3] [low, new, contract, owned → S5, @Reviewer]** `services/summary_fact_package.py` (L1-passthrough) — §9/ADR-1026-6 D5 «проброс `skipped_ids`/`skipped_tg_ids`» выполнен как **счётчики** (`metrics.l1_skipped_count`/`l1_chunk_count`); сами id-списки и `skipped_tg_ids` в `FactPackageResult` не переносятся (`grep` — `skipped_tg_ids` в модуле отсутствует). §10 трактует `skipped_ids` «счётно», данные остаются на `L1Result` (S5 получает его напрямую) → функциональной потери нет. **Fix:** уточнить формулировку §9/*ADR* либо донести ids в S5. (Не блокирует — не код-дефект целостности.)
- [ ] **I-R1026S4-1 [info, new]** `services/summary_fact_package.py:382-412` — `unassigned_message_ids` не усекаются бюджетом; возвращаемый `cut` не используется → при превышении одними unassigned пакет `status=empty`/`fits=False` (reason `empty`, не `budget_empty`).
- [ ] **I-R1026S4-2 [info, new]** `services/summary_fact_package.py:639-645`/`_fail_result` — `invalid`/`error` без `invalid_reason` → `FactPackageResult.reason=None`, тогда как `metrics.reason` и запись `FACT_PACKAGE_COMPLETE` показывают `ok`.
- **Инварианты OK:** 0 LLM-вызовов (`llm_client` в модуле отсутствует); §96 — сырой лог повторно не дублируется, доказательства не генерируются, `description`/`chronology` детерминированы; fail-closed `ok/truncated/empty/invalid/error/not_built`; ID — TG `message_id` (DB `id` → `invalid`; `evidence_ids ⊆ message_ids`); Δ DDL=0 (`database.py`/`pg_db.py` вне diff); Δ каталога=0 импортом (468/426/443/100/98/21; `param_catalog.py` вне diff); `APP_VERSION` 2.58.23 синхронен; живой путь/публикация/обложка/`web/**` вне diff; CSP/zero-build; R17 (логи — числа/коды/id; секрет-тест)/R18 (тег `pre-round1026-s4`→`59f5921`, `var/backups/s4-round1026-20260923-202326/`, `.env.bak.round1026-s4`, `stash@{0}`); `git diff --check`=0; гигиена индекса OK; маркер-тесты не ослаблены (только version-пины).
- **Прогоны @Scanner:** `tests/test_summary_fact_package.py` **52 passed / 0 failed**; импорт каталога **468/426/443/100/98/21**; `git diff --check`=0; `git rev-list -n1 pre-round1026-s4` = `59f5921`. Полный pytest/JS — данные Builder (8737/0, 43/43), повторно не гонялись.
- **Handoff @Scanner:** @Orchestrator → **SCANNED** (к деплою ДА по коду; процессный gate — T-3300 @Reviewer; L-R1026S4-1/-2 — owned follow-up к S5).
- **@Reviewer (T-3300, 23.09.2026) — Status: Approved:** оба ленза (требования/корректность + focused change-audit) пройдены; C0/H0/блокирующих Medium 0. Независимо воспроизведено: pytest **8737/0** (8685+52), JS **43/43**, `git diff --check`=0, каталог **468/426/443/100/98/21**, F8 `--check` OK, Δ DDL=0, 0 LLM (AST-импорты), живой путь/публикация/обложка/`web/**` вне diff, R17/R18, `APP_VERSION` 2.58.23. **L-R1026S4-1/-2 подтверждены лично**; добавлен **L-R1026S4-3** (Low, contract §9). **M-R1026S4-1 — RESOLVED.** Отчёт: `plans/features/summary-fact-package-round1026/review.md`. Live — PENDING OWNER VERIFICATION.

## Эпик 2 / S3 `summary-l1-clusterizer-round1026` (Шаг 6, T-3276) — Step 6 @Scanner, 23.09.2026 — **SCANNED: дефектов кода-блокеров нет; C0/H0; Medium 1 (процесс); Low 3 (owned follow-up)**
Baseline — HEAD `4007081` (annotated-тег `pre-round1026-s3` → `4007081`); правки **НЕ закоммичены** (57 M + 4 ??). Отчёт: `plans/reports/round1026_s3_scanner_audit.md`. Bump `APP_VERSION` 2.58.22; Δ DDL=0; Δ каталога = ровно +1 (468/426/443/100/98/21; prompts 22); F8 delta 56→57, `--check` OK.
- [x] **[M-R1026S3-1] [medium, new, process/gate, blocking deploy]** `plans/features/summary-l1-clusterizer-round1026/review.md` отсутствует (T-3275 @Reviewer не закрыт; workflow_state/backlog/MEMORY не отражают и Step 4 @Builder). **Fix:** прогнать T-3275 → review.md; при findings — rework + повторные проверки; либо явное решение @Orchestrator о порядке шагов. (Не код-дефект; независимые проверки Scanner — зелёные.) → **RESOLVED 23.09.2026 (T-3275 @Reviewer): `review.md` создан, Status: Approved (C0/H0, блокирующих Medium нет); gated-часть снята.**
- [ ] **[L-R1026S3-1] [low, new, hardening]** `services/summary_l1_clusterizer.py:469-475` — `resolve_l1_slot()` вызывается вне try/fail-closed: исключение резолва слота пробрасывается наружу (воспроизведено подменой → `RuntimeError`), вопреки docstring «любое исключение → error/invalid». **Fix:** перенести резолв в try до врезки S5. (Не блокирует; S3 не в живом пути.)
- [ ] **[L-R1026S3-2] [low, new, contract]** `services/summary_l1_contract.py:399-413` — `evidence_message_ids: []` принимается как валидный факт (проверено: `ok`, `facts=1`). **Fix:** требовать ≥1 evidence (`invalid_fact`) либо документировать политику. (Не блокирует.)
- [ ] **[L-R1026S3-3] [low, new, edge]** `services/summary_l1_clusterizer.py:193-215` — строка без `tg_message_id`: single-chunk ветка молча даёт `message_id: null` (вне id-space/auto-unassigned), fragmented ветка → `IdSpaceMismatch` (воспроизведено). **Fix:** унифицировать fail-closed. (Прод-инвариант S1/S2 гарантирует поле.)
- [ ] **I-R1026S3-1 [info, new]** `tests/js/round1025_hotfix{7,8,9,10}_*.js` — regex обновлён на `2.58.22`, метка assert осталась `'D: APP_VERSION 2.58.21'` (косметика; тесты зелёные).
- [ ] **I-R1026S3-2 [info, new]** `services/summary_l1_contract.py:50-51,360` — `THREAD_ID_RE` (`$`) принимает trailing `\n`; значение перенумеровывается (`thread_%03d`) → влияния нет.
- [ ] **I-R1026S3-3 [info, new]** `services/summary_prompts.py:246-252` — канон L1 содержит `TARGET_INSTRUCTION_BLOCK`, но `build_l1_user_content` не ставит маркер текущей команды: блок инертен; решить при врезке S5.
- [ ] **I-R1026S3-4 [info, new, S5-note]** `services/llm_client.py:559-570` — `_post(api_key=…)` подменяет общий chat-клиент при смене ключа (pre-existing паттерн `generate_worker`); на S5 при параллельных вызовах — per-key кэш клиентов.
- [ ] **I-R1026S3-5 [info, new, docs]** `plans/workflow_state.md`/`backlog.md`/`MEMORY.md` не отражают Step 4 @Builder (синк ожидается на Step 8–10 @PM/@Memory).
- [ ] **R-R1026S3-1 [info, new, S5-note, @Reviewer]** `services/summary_l1_clusterizer.py:357-404` — dedicated-путь (`llm._post`) не пишет analytics (`_record_analytics` module/step/correlation_id) и не учитывает global usage / per-chat BYOK, в отличие от `generate` (в S3 нет потребителя). **Fix:** публичный метод клиента на S5. (Не блокирует.)
- [ ] **R-R1026S3-2 [info, new, S5-note, @Reviewer]** `services/summary_l1_clusterizer.py:181-244` — оценка бюджета L1 (`estimate_and_split`) считает только токены текста (+маркеры), без system-промпта и JSON-обёртки §92 → фактический ввод больше оценки (спека предписывает существующий эстиматор). **Fix:** учесть overhead/наблюдать на S5. (Не блокирует.)
- **Вердикт @Reviewer (T-3275, 23.09.2026):** **Approved** — C0/H0, блокирующих Medium нет; L-R1026S3-1/-2/-3 подтверждены независимо (owned follow-up к S5); I-R1026S3-1/-2 и docs-lag — косметика/процесс. Отчёт: `plans/features/summary-l1-clusterizer-round1026/review.md`; запись — `plans/reports/full_audit_results.md` (Step 5 @Reviewer). Live — PENDING OWNER VERIFICATION.
- **Инварианты OK:** D4-гейт (live-путь/публикация/обложка/XML/web вне diff; врезки нет; 2-вызовность; третьего вызова нет); Δ DDL=0 (`sha256(pg_db.py)` == фикстура); Δ каталога = +1 (468/426/443/100/98/21; prompts 21→22; `settings_field=None`); F8 repin (delta 57, `--check` OK, `ROUTES_SHA256_F11` цел, байтфризы целы); `APP_VERSION` 2.58.22; R17 (логи — числа/коды/id; канон/эталон без секретов)/R18 (тег `pre-round1026-s3` → `4007081`, `var/backups/s3-round1026-20260923-183119/`, `.env.bak.round1026-s3`, `stash@{0}`); CSP/zero-build; канон-эталон байт-в-байт; миграция идемпотентна; `git diff --check`=0; гигиена индекса OK; маркер-тесты не ослаблены.
- **Прогоны @Scanner:** `.venv` pytest **8685/0** (113.18 s; +116); новый файл **116 passed**; JS **43/43**; `node --check` OK; F8 `--check` exit 0; импорт-проверки каталога/версии/хешей OK.
- **Handoff @Scanner:** @Orchestrator → **SCANNED** (код чистый; деплой — после закрытия T-3275 @Reviewer; Low — owned follow-up).

## Эпик 2 / S2 `summary-context-restore-round1026` (Шаг 6, T-3246) — Step 6 @Scanner, 23.09.2026 — **SCANNED: блокеров нет; Critical/High/Medium — 0; Low 2 (owned follow-up)**
Baseline — HEAD `7895e77` (тег `pre-round1026-s2`); правки **НЕ закоммичены**. Отчёт: `plans/reports/round1026_s2_scanner_audit.md`. Bump `APP_VERSION` 2.58.21; Δ DDL=0; Δ каталога=0 (467/426/442/100/98/21).
- [ ] **[L-R1026S2-1] [low, new, doc]** `services/summary_context_restore.py:4-6` — docstring «без системных часов», но `duration_ms` считается через `time.perf_counter()` (недетерминирован лишь метрический таймер; `kept`/`restored` детерминированы). **Fix:** уточнить формулировку либо вынести таймер в адаптер. (Не блокирует)
- [ ] **[L-R1026S2-2] [low, new, perf]** `services/summary_generator.py::_collect_extra_parents` — до 50 последовательных `collect_thread_chain` (глубина 10) + повторное чтение строк цепочки из БД; ограниченный рост латентности на «звонких» чатах. **Fix:** наблюдать в проде; при необходимости batch-чтение/кэш. (Не блокирует)
- **Инварианты OK:** D4-гейт (XML/промпты/публикация вне diff; 2 LLM; нет новых зависимостей/CDN); Δ DDL=0; Δ каталога=0 (`param_catalog.py` не тронут; 467/426/442/100/98/21); `APP_VERSION` 2.58.21; R17 (логи — числа/коды/id)/R18 (тег `pre-round1026-s2`, бэкапы, `stash@{0}`); `git diff --check`=0; гигиена индекса (нет `.env`/`current_task.md`/zip/`tools/_ui_*`/`var/backups`).
- **Handoff @Scanner:** @Orchestrator → **SCANNED** (к деплою ДА; live-приёмка — PENDING OWNER).

## Правка владельца v2.58.20 «мерцание свечения фона ×2» в `polygonal-luminescence-round1026` (T-3220…T-3223) — Step 6 @Scanner, 23.09.2026 — **SCANNED: блокеров нет; новых Low/Medium — 0**
Baseline — HEAD `1ad98ca` (прод-деплой 2.58.19); правки **НЕ закоммичены** (25 M / 0 ??). Отчёт: `plans/reports/round1026_visual_scanner_audit.md` (Addendum). Bump `APP_VERSION` 2.58.20.
- [ ] **I-POLY1026-5 [info, new]** Docstring `tests/test_webapp_round1026_polygon.py:7` / `evidence.md` упоминают `SQLite user_version=12`, тогда как схема версионируется в `services/database.py` (`_SCHEMA_VERSION*`), `db/**/*.sql` отсутствует → `test_zero_ddl` вакуумный. Δ DDL=0 доказан diff-скоупом. **Fix:** уточнить формулировку. (не блокирует; pre-existing)
- **Проверено (инварианты/гигиена):** Δ DDL=0; Δ каталога=0 (467/426/442/100/98/21; `param_catalog.py` не тронут); CSP/zero-build (`eval`/`innerHTML`=0; только `/static/**`; `script-src 'self'` + pre-existing `'unsafe-eval'`); один активный рендерер; `Math.random`=0; DPR-кап/NODES/`TOPO_HZ=4`/reduced-motion/hidden/context-loss без изменений; `APP_VERSION` 2.58.20 синхронен; R17 (`current_task.md` не тронут)/R18 (tag `pre-round1026-visual`→`9d046e5`, `stash@{0}`, бэкап); `git diff --check`=0; маркер-тесты не ослаблены (только version re-pin).
- **Severity 10.26 owner-edit v2.58.20:** Critical 0 / High 0 / Medium 0 / Low 0 (новых) / Info 1 (pre-existing). **Вердикт: К ДЕПЛОЮ — ДА (блокеров нет).** Live-гейты (перф/стекло/WebView) — PENDING OWNER.
- **Прогоны @Scanner:** `test_webapp_round1026_polygon.py` **23 passed**; re-pin pytest **295 passed**; JS `POLYGON-LUMINESCENCE-OK` + hotfix7/8/9/10 OK (всего 43); `git diff --check`=0.
- **Handoff @Scanner:** @Orchestrator → **SCANNED**.

## EXTRA-визуальный эпик `polygonal-luminescence-round1026` (Polygon Canvas2D + Delaunator 5.0.0; env-only `UI_POLYGON_BG_ENABLED`; glass-прототип) — Step 6 @Scanner (T-3214), 23.09.2026 — **SCANNED: блокеров нет; Low(3) — owned follow-up**
Baseline — HEAD `9d046e5` (annotated-тег `pre-round1026-visual` → `9d046e5`); правки **НЕ закоммичены** (34 M + 10 ??). Отчёт: `plans/reports/round1026_visual_scanner_audit.md`. Bump `APP_VERSION` 2.58.19; deploy — T-3217.
- [ ] **[L-POLY1026-1] [low, new, perf/gc]** `web/static/polygon-background.js:425-534` (`drawFacets`/`drawNodes`) — на каждый кадр аллоцируются массивы `ca/cb/mix` (по грани) и `rgba()`-строки (~500–1000+ объектов/кадр). SC-33 не нарушен (точки не аллоцируют), но GC-давление на mobile. **Fix:** скретч-массивы/кэш `rgba` по PAL. (не блокирует; live-перф — PENDING OWNER)
- [ ] **[L-POLY1026-2] [low, new, gate-coverage]** `tools/ui_round1025_matrix.py:133-142` — §71 зафиксирована на `UI_POLYGON_BG_ENABLED=False`; активный default-ON путь покрыт только `tools/ui_round1026_polygon.py`. **Fix:** второй режим ON в матрице/общий CI-гейт. (не блокирует)
- [ ] **[L-POLY1026-3] [low, new, evidence]** `round1026_polygon_background_ui_report.md:7,80`/`spec.md:272` пишут CSP `script-src 'self'`, фактически `web/app.py:50-61` — `'self' 'unsafe-eval'` (pre-existing; `app.py` не менялся). Инвариант нового кода (no CDN/inline/eval) соблюдён. **Fix:** уточнить формулировку. (не блокирует)
- [ ] **I-POLY1026-1 [info]** `web/static/glass.js:127-139` (`detectMode` webgl→refraction) без отдельного регресс-теста; влияние — только `data-lg-mode`. Не блокер.
- [ ] **I-POLY1026-2 [info]** `web/static/polygon-background.js:640-651` (`fallbackNone`) без `contextrestored` → фон off до след. `_syncBgLayer`/reload (CSS-wash остаётся, «честный фолбэк» по ADR). Не блокер.
- [ ] **I-POLY1026-3 [info]** `web/app.js:4154-4160` (`uiFlag`) default `true` до `/api/me` (pre-existing) → soft-OFF не применится при auth-фейле; общая семантика env-only флагов. Не блокер.
- [ ] **I-POLY1026-4 [info]** `polygon-background.js:757-774` (`sample()`) читает `getImageData` полного DPR-буфера (~2880×1800) — только диагностика, не в rAF. Не блокер.
- **Проверено (инварианты/гигиена):** Δ DDL=0 (`services/**`/миграции/`db/**` пусты; `sha256(pg_db.py)` == фикстура); Δ каталога=0 (467/426/442/100/98/21; флаг ∉ `pc.REGISTRY`; `sha256(param_catalog.py)` == фикстура); CSP/zero-build (only `/static/**`; `eval`/`innerHTML` нет; SHA delaunator `7707D7FE…C1BE`); ровно один активный рендерер (`_syncBgLayer` + `html.polygon-bg`, JS-тест C); `Math.random` в рендере нет (SEED+mulberry32); нет утечек rAF/RO/буферов; a11y `pointer-events:none`/`aria-hidden`; `APP_VERSION` 2.58.19; R17 (0 секретов; логов нет)/R18 (`pre-round1026-visual`, `var/backups/visual-round1026-20260923-142355/`, `stash@{0}`); D4-гейт (публикация/`summary_*`/S6/S10/IA/сердцебиение не тронуты); стекло default OFF, J заблокирован §13.2; `git diff --check`=0; маркер-тесты не ослаблены (bump + re-pin `ROUTES_SHA256_F11`).
- **Прогоны @Scanner:** `node tests/js/round1026_polygon_background_test.js` → `POLYGON-LUMINESCENCE-OK`; hotfix7/8/9/10 JS OK; `test_webapp_round1026_polygon.py` **18 passed**; `test_webapp_js_unit.py`+`test_round1025_f8_registry.py` **59 passed**; каталог 467/426/442/100/98/21; `git diff --check`=0.
- **Severity 10.26 visual:** Critical 0 / High 0 / Medium 0 / Low 3 / Info 4. **Вердикт: К ДЕПЛОЮ — ДА (блокеров нет).** Live-гейты (стекло п.1/5/7, перф/видео, реальный Telegram WebView) — **PENDING OWNER VERIFICATION**; блок J — заблокирован §13.2.
- **Handoff @Scanner:** @Orchestrator → **SCANNED**.

## Эпик 2 / S1 `summary-filter-round1026` (алгоритмический префильтр Саммари §87–§89/§93) — Step 6 @Scanner (T-3153), 23.09.2026 — **SCANNED (итер.2, финал): блокеров нет; Low(1) — owned follow-up**
Baseline — HEAD `01f3c57` (annotated-тег `pre-round1026-s1` → `01f3c57`); правки **НЕ закоммичены** (57 M + 6 ??). Отчёт: `plans/reports/round1026_s1_scanner_audit.md`. Bump `APP_VERSION` 2.58.18; deploy — T-3157.
- [x] **[M-R1026S1-1] [medium, RESOLVED итер.2, per-chat/SC-05]** `services/summary_generator.py:343-348` — тумблер `flags.summary_filter_enabled` теперь `bool(await _chat_limit(...))` (per-chat, симметрично `reply_context_enabled`); spec §6.1. Верификация: `tests/test_summary_filter_integration.py::TestPerChatToggle` (A/C ON, B OFF → `applied == [A, C]`; OFF → тот же объект `rows`, метрики пусты). Воспроизведено (38 passed).
- [x] **[L-R1026S1-1] [low, RESOLVED итер.2, budget-edge]** `services/summary_generator.py:512-521` — `resolve_context_tokens(await _chat_limit(...), _SUMMARY_CONTEXT_TOKEN_DEFAULT)` перед бюджетом. Верификация: `TestTokenCeilingNormalised` (`0 → дефолт`, `-1 → безлимит`, `fits is True`).
- [x] **[L-R1026S1-2] [low, RESOLVED итер.2, test-coverage]** Добавлен `tests/test_summary_filter_integration.py` (7 тестов): OFF байт-в-байт, RAG/graph на исходном окне, fail-open, ровно 2 LLM-вызова, sentinel.
- [ ] **[L-R1026S1-3] [low, new, non-blocking, consistency]** После нормализации `token_limit` всегда не-`None` → `estimate_and_split` всегда tokens-ветка; `char_limit` в `_run` фактически не используется, а при env-конфиге с chars-fallback (`SUMMARY_MAX_CONTEXT_CHARS` задан, `SUMMARY_MAX_CONTEXT_TOKENS` нет) `budget.kind` разойдётся с `_run` (`resolve_chat_limit`). Влияние — только информационный `budget`/S8 (S1 на него не действует). **Fix:** `resolve_chat_limit` (единый kind) либо убрать мёртвый `char_limit`.
- [x] **B-1 [@Reviewer high, governance, RESOLVED]** **ADR-1026-2** (Accepted, Step 2b @Architect) — AMEND ADR-1025-21 D6 (переиздание frozen F8 при санкционированном Δ каталога); `plans/ARCHITECTURE.md §67.6` + `adr-1026-1` AMEND обновлены.
- **Инварианты OK:** D4-гейт публикации (diff пуст по `image_generation.py`/`telegram_send.py`/`summary_prompts.py`/`summary_xml.py`/`routes.py`; `_deliver_*` не тронуты), 2-вызовность, Δ DDL=0 (`database.py`/`pg_db.py`/`summary_memory.py` пуст), Δ каталога ровно 467/426/442/100/98/21, R17 (логи — только id/числа), R18 (`pre-round1026-s1`, `var/backups/`, `stash@{0}`), CSP/zero-build, `git diff --check`=0, F0/F4/F5/F6/F7/F9/F11 зелёные.
- **Суперсессия F8:** санкционирована (ADR-1026-2); байтфризы не ослаблены (`sha256(param_catalog.py)` совпал, `ROUTES_SHA256_F11` цел, `app_version` исторический 2.58.15); TSV/screen-map/meta консистентны (467, delta 56).
- **Прогоны @Scanner (итер.2):** `.venv` pytest **8501/0**; JS **42/42**; `node --check` OK; фильтр-блок **38 passed**; каталог 467/426/442/100/98/21; hash совпал; `git diff --check`=0. `py -3` — 8495/5env/1 (5 pre-existing env).
- **Handoff @Scanner:** @Orchestrator → **SCANNED** (блокеров нет).

## Round 10.25 F10 `epic1-verification-round1025` (верификационный стоп-гейт Эпика 1) — Step 6 @Scanner (T-3122), 23.09.2026 — **SCANNED (блокеров нет; Low/Info — owned follow-up)**
Baseline — HEAD `57b325c` (annotated-тег `pre-round1025-f10` → `57b325c`); правки **НЕ закоммичены** (5 M + 18 ??, verification-only). Отчёт: `plans/reports/round1025_f10_scanner_audit.md`. Deploy **NOT_APPLICABLE**, `APP_VERSION` 2.58.17 без bump.
- [ ] **[L-F10S-1] [low, new, gate-robustness]** `tools/ui_round1025_e2e.py:320,346-350` — §73 фиксирует `deferred_captured`/`a_server_value`, но не assert'ит их → при неотправленной мутации проверка вакуумна (B неизменен тривиально). Текущий прогон валиден (`deferred_captured=true`, `a_server_value=true`). **Fix:** assert `deferred_captured is True` + `a_server_value == target`. (не блокирует; §72 отдельно ловит 0-write)
- [ ] **[L-F10S-2] [low, new, evidence-honesty]** `tools/ui_round1025_matrix.py:1451-1481,2610-2690` + `round1025_f10_playwright.md:36-37` — low-TG `1280×400` на desktop-ширине не имеет `.bottom-nav`/`minTouch`, поэтому клаузы «нижние панели в `stableHeight` / touch ≥44» в `_low_tg_failures` инертны; фактическое покрытие = h-scroll + bounds sidebar. **Fix:** уточнить формулировку или добавить mobile-ширину при низкой высоте. (не блокирует)
- [ ] **I-F10S-1 [info]** `round1025_f10_epic2_gate.md:29-32` — evidence `sendRichMessage` = grep-присутствие; поведенческий тест `tests/test_outgoing_guard_round1022.py` (проходит в `.venv`) в 300-test subset не включён. Не блокер (рантайм не изменялся).
- [ ] **I-F10S-2 [info]** `round1025_f10_acceptance.md:142`/`evidence.md:48`/`round1025_f10_map_monitoring.md:22` — «pytest 8463 passed» воспроизводится в `.venv` (aiogram 3.31.0); system `py -3` (aiogram 3.29.1) → 8457/5env/1. Указывать интерпретатор рядом с числом.
- [ ] **I-F10S-3 [info]** `tools/ui_round1025_secrets_ui.py:35` — синтетический `NEW_KEY="sk-ui-round1025-f10-probe"` (не реальный секрет; может триггерить секрет-сканеры).
- [ ] **I-F10S-4 [info]** `round1025_f10_epic2_gate.md:9`/`evidence.md:31` — nit: формулировка «изменены `tools/**`, `plans/**`, `tests/**`», хотя `tests/**` в F10 не менялись.
- **Проверено (инварианты/гигиена):** read-only ✔ (`git diff HEAD -- services web handlers config migrations param_catalog.py web/api` пуст, untracked в рантайме нет); Δ DDL=0; Δ каталога=0 (459/98/96/21; `REGISTRY=459`,`GROUPS=98`,`_TAB_BY_GROUP=96`,`TAB_RULES/TAB_NAV/CONFIG_TAB_TITLES=21`); CSP/zero-build; R17 (regex-скан 0); R18 (`pre-round1025-f10`→`57b325c` (origin), бэкап `f10-round1025-20260923-091131`, `.env.bak.round1025-f10`, `stash@{0}`); §117 п.1–12 полны (12/12, артефакты существуют); маркер-тесты не ослаблены (`tests/**` не менялись); гигиена (`git diff --check`=0; `tools/_ui_*`/shots/`.env`/zip/`var/` вне индекса); `deploy_commands.txt`/`current_task.md` не тронуты — проверено.
- **Прогоны @Scanner (независимо):** `node --check web/app.js` OK; `tests/js/*.js` **42/42 OK**; `py -3 -m pytest -q` **8457 passed / 5 failed / 1 skipped** (5 env pre-existing `rich`/`InputRichMessageMedia`); `.venv` → **8463 passed**; `git diff --check`=0.
- **Severity 10.25 F10:** Critical 0 / High 0 / Medium 0 / Low 2 / Info 4. **Вердикт: приёмка Эпика 1 (авто) — ДА, блокеров нет.** Live-гейт Telegram WebView — **PENDING OWNER VERIFICATION**; Эпик 1 не объявляется завершённым.
- **Handoff @Scanner:** @Orchestrator → **SCANNED**.

## Round 10.25 F11 `status-showcase-dashboard-round1025` (витрина «Статус» §11–§21 + kill-switch `UI_STATUS_GRID_V2`) — Step 6 @Scanner (T-3092), 23.09.2026 — **итерация 2 (финал): SCANNED, все findings RESOLVED**
Baseline — HEAD `25cc19c` (тег `pre-round1025-f11`); правки **НЕ закоммичены** (31 M + 10 ??). Отчёт: `plans/reports/round1025_f11_scanner_audit.md`.
- [x] **[H-F11S-1] [high, RESOLVED]** аддитивный `counts` в `/api/status/logs` (`routes.py:1675-1685`) + read-only `LogRingHandler.level_counts()` (`services/log_ring.py:185-199`); `loadLogCounts` (`web/app.js:9308-9318`) — 1 запрос `level=ALL&limit=1`, читает `counts.ERROR`/`counts.WARNING` (реальные числа, раздельная семантика); нет `counts`/ошибка → «—». `count`/`logs` без изменений (`loadLogs` не тронут). Гейты: `test_level_counts_exact` (7→7/3→3), `test_level_counts_not_capped_by_limit`, API `test_logs_counts_not_capped_by_limit` (`count=1`, `counts.ERROR=5>1`), JS `F11-LOG-COUNTS-OK` — PASSED.
- [x] **[M-F11S-1] [medium, RESOLVED]** формулировки приведены к факту: OFF = «одноколоночный безопасный режим» (`.status-grid--legacy`), НЕ byte-identical legacy-DOM (`spec.md:70/149`, `adr:48/52/73`, `.env.example`).
- [x] **[L-F11S-1] [low, RESOLVED]** строгий byte-freeze `web/api/routes.py` восстановлен `ROUTES_SHA256_F11` (SHA совпал, тест PASSED).
- [x] **[L-F11S-2] [low, RESOLVED]** `UI_STATUS_GRID_V2` задокументирован в `.env.example`.
- [x] **[L-F11S-3] [low, RESOLVED]** initial focus (`ref="graphFullPanel" tabindex="-1"` + `_focusGraphFull`) + Esc-close (`escClose`→`closeGraphFull`). Остаток (Info, не блокер): нет полного focus-trap; тач-цели <44px.
- [x] **I-F11S-1 [info, RESOLVED]** мёртвая ветка `$refs.statusLogs` удалена. Info: I-F11S-2 (1 запрос вместо 2, без новых таймеров); I-F11S-3 live Telegram WebView/TMA — PENDING OWNER (T-3097).
- **Прогоны @Scanner (итер.2):** `node --check` OK; `tests/js/*.js` **42/42 PASS**; `py -3 -m pytest -q` **8457 passed / 5 failed / 1 skipped** (5 env pre-existing: `outgoing_guard_round1022` ×2 + `summary_cover_round1023` ×3, `ImportError` aiogram rich); `tests/test_webapp_f11_round1025.py` **33 passed**; каталог 459/98/96/21; Δ DDL=0; `git diff --check`=0; R17 0; R18 (тег/`stash@{0}`/`.env.bak`).
- **Handoff @Scanner:** @Orchestrator → **SCANNED** (к деплою ДА, блокеров нет).

## Round 10.25 F9 `secrets-and-save-states-round1025` (UI секретов §50 + состояния §51 + визуальный добор SaveBar §69/§78) — Step 6 @Scanner (T-3055), 23.09.2026 — **итерация 2: SCANNED, все findings RESOLVED**
Baseline — HEAD `93432c0` (тег `pre-round1025-f9`); правки **НЕ закоммичены** (focused diff-based; 32 M + 9 ??). Отчёт: `plans/reports/round1025_f9_scanner_audit.md`. Итер.1 (High 1 + Low 4) закрыта фиксами @Builder, воспроизведена @Scanner.
- [x] R17 — сырых секретов в DOM/POST/логах/тестах/артефактах нет (regex-скан 0); поле ввода секрета всегда пусто (`_seedSecretMasks` только чистит; `blockFieldValue` секрет → `''`); guard'ы `hasSecretMask` целы (`dirtyKeyItems:2822`, `saveKeyItem:7951`, `saveBlock:6039`, `testBlock:5973`, `testField:6005`); маска в API не уходит (JS-тест, 0 запросов) — проверено.
- [x] Инварианты — Δ DDL=0 (`services/**`/`web/api/**`/миграции не тронуты; новый endpoint не создан); Δ каталога=0 (459/98/96/21/418; `param_catalog.py` не тронут); CSP/zero-build (x-template); `APP_VERSION` 2.58.16 синхронен; F0-движок не переписан (`persistItems`×1, `notify`×1); §52–§67/F1/F4/F5/F6/F7/F8/BYOK не сломаны; XSS-safe; safe-area один раз — проверено.
- [x] Логика — не трогали→не перезаписывается; заменили→новая маска; вставка маски→отказ; удаление — отдельное действие + `window.confirm`, не при пустом поле — проверено (JS).
- [x] Гигиена — `git diff --check`=0; в индексе нет `.env`/`current_task.md`/zip/скриншотов/`tools/_ui_*`/`var/backups`; R18: тег `pre-round1025-f9`, `.env.bak.round1025-f9`, `stash@{0}` — проверено.
- **Severity 10.25 F9 (итер.2, финал): Critical 0 / High 0 / Medium 0 / Low 0 / Info 2. Вердикт: К ДЕПЛОЮ — ДА (блокеров нет).**
  - [x] **[H-F9S-1] [high, new, functional-scope, БЛОКЕР] RESOLVED** — `web/app.js:7978-7986`: image-ветка `DELETE /api/config/keys/own/{key}` теперь `{method:'DELETE', global:true}` (при выбранном чате `api()` не подставляет `X-Chat-Id` → глобальная ветка `routes.py:814-833`, chat-ветка/422 не задействуется); паритет с `saveProviderSecret`; регресс-гейт `round1025_f9_secret_field_test.js:236-239` (`opts.global===true`). `web/app.js:7997-7999` (`deleteKeyItem`) — `DELETE /api/config/keys/own/{key}` без `global:true`; `api()` (`:3295`) добавляет `X-Chat-Id` при выбранном чате → сервер chat-ветка (`routes.py:834-847`) → `chat_keys.delete_chat_key` (`services/chat_keys.py:137-138`, whitelist `{keys.llm_api_key}`) → **422**; «Удалить» image-секрета не работает в контексте чата, глобальный секрет не удалён. Паритет с `saveProviderSecret` (`:3864`, `global:true`); ADR-1025-22 D2 требует глобальную ветку. **Fix:** `{ method:'DELETE', global:true }` + JS-кейс на `opts.global` для image-ветки. **Возврат @Builder → @Reviewer → @Scanner.**
  - [x] **[L-F9S-1] [low, new, dead-code/duplication] RESOLVED** — `secret-field.maskText` (`:11464-11468`) делегирует в `secretDisplayOf`; мёртвый `blockSecretText` удалён (ссылок в `web/`/`tests/` нет), 2 теста переведены на `secretDisplay` (assert неизменён). `web/app.js:36-51/5937-5940/7922-7944` — `secretDisplayOf`/`secretDisplay`/`blockSecretText` не используются в разметке (шаблон берёт `configured`/`last4` props); логика маски продублирована в компоненте `maskText`. **Fix:** использовать единый хелпер или удалить мёртвое. (не блокирует)
  - [x] **[L-F9S-2] [low, new, honesty] RESOLVED** — ветка `stateLabel['saved']` убрана (`:11398-11404`); тест `round1025_f9_savebar_visual_test.js:184-185` ждёт `''`; «Сохранено» — тост F0 после сервера. `web/app.js:11397-11407` — ветка `stateLabel['saved']` недостижима (`root.saveState` после успеха → `clean`); «Сохранено» доставляется тостом F0. Тест `round1025_f9_savebar_visual_test.js:180` проверяет мёртвую ветку. (не блокирует)
  - [x] **[L-F9S-3] [low, new, marker-weakening] RESOLVED** — `tests/test_round1025_f8_registry.py:106-107`: `FIXTURE["app_version"] == "2.58.15"` и `APP_VERSION == "2.58.16"` (строго, без `>=`); 2.58.15 в `tests/` — только исторический fixture. `tests/test_round1025_f8_registry.py:102-112` — `test_app_version_recorded` ослаблен со строгого `APP_VERSION == FIXTURE == "2.58.15"` до `_v(APP_VERSION) >= _v("2.58.15")`. Версия всё ещё пинится точным `2.58.16` в ~10 других тестах → не блокирует; желательно сохранить строгий контракт (fixture vs current). (не блокирует)
  - [x] **[L-F9S-4] [low, new, doc] RESOLVED** — `evidence.md:25/53`: `f8_baseline.json` убран из списка bump, помечен историческим baseline 2.58.15. `plans/features/secrets-and-save-states-round1025/evidence.md:25` называет `tests/fixtures/round1025/f8_baseline.json` среди bump-версий, `:37` — «не бампнут сознательно» (файл не менялся). **Fix:** убрать из списка bump. (не блокирует)
  - Info (итер.1, не блокируют): I-F9S-1 (empty-write не-image ключей в чате корректен: `per_chat=false` → global, проверено); I-F9S-2 (`_syncKeyboardOffset` на `visualViewport` scroll может часто звать `scrollIntoView` — live-гейт); I-F9S-3 (live TMA/WebView keyboard/safe-area — PENDING OWNER).
  - Info (не блокируют): I-F9S-1 (осиротевший комментарий от удалённого `blockSecretText`, `web/app.js:5935-5936`); I-F9S-2 (live TMA/WebView keyboard/safe-area — PENDING OWNER VERIFICATION).
  - **Прогоны @Scanner (итер.2):** `node --check` OK; `tests/js/*.js` **40/40 OK**; `py -3 -m pytest -q` **8421 passed / 0 failed / 1 skipped** (5 env-failed `rich`-fallback, `services/**` вне диффа); каталог 459/98/96/21/418; `git diff --check`=0; R17-regex 0.
  - **Handoff @Scanner:** @Orchestrator → `SCANNED`.

## Round 10.25 F8 `parameter-registry-widget-map-round1025` (реестр параметров §2 + сохранность конфигурации §3 + §117 п.1–4) — Step 6 @Scanner (T-3016), 23.09.2026 — all scanned, PENDING=0
Baseline — HEAD `a40f244` (== `origin/master`, тег `pre-round1025-f8`); правки **НЕ закоммичены** (focused diff-based, рабочие артефакты `plans/docs/**` + `tools/**` + тесты). Отчёт: `plans/reports/round1025_f8_scanner_audit.md`. Тип — read-only enabler (Δ DDL=0, Δ каталога=0, deploy NOT_APPLICABLE).
- [x] Реестр/полнота — 459 строк × 23 кол. × 0 пустых; `set(internal_key)` == `{s.pg_key}` == 459 (биекция); каталог 459/98/96/21/418 — проверено.
- [x] Дельта 411→459 = **48**; набор `status=new` == `pg_keys − inventory(411)`; список в `.meta.md` совпал (проверено программно) — проверено.
- [x] Карта экранов 459 ⊇ каталог, «без места»=0, `registry-only`=0; карта виджетов — маркер + `api-only`-секция (`≠ сохранено`) — проверено.
- [x] R17 — секретов 28, все `current_value`/`default_value` = `{configured,last4}`; ручной скан bot-token/`sk-`/hex32/DSN по всем артефактам и отчётам чист (совпадения — синтетические тест-токены и SHA256 freeze-хэши) — проверено.
- [x] Инструменты — `gen --check` exit 0 + детект искусственного расхождения; `config_snapshot_diff --selftest` OK; F8-`tools/*` рантаймом не импортируются; маркер-тесты **29 passed** — проверено.
- [x] Инварианты — `git diff a40f244 -- migrations alembic services/pg_db.py services/param_catalog.py` = 0 файлов; `services/web/handlers/config/settings.py/web/api/routes.py` без изменений; роуты 31; `APP_VERSION` 2.58.15; `plans/docs/canon/` не тронут; CSP/zero-build; `git diff --check`=0 — проверено.
- [x] R18 — тег `pre-round1025-f8`@`a40f244`; бэкапы `f8-round1025-20260923-044606` + `f8-round1025-config`; `.env.bak.round1025-f8`; `stash@{0}` на месте; `var/` не в индексе; гигиена (`.env`/zip/скриншоты/`tools/_ui_*`/`var/backups`) чистая; `plans/current_task.md` не изменён (gitignored, `.gitignore:70`) — проверено.
- **Severity 10.25 F8 (итер.1): Critical 0 / High 0 / Medium 0 / Low 3 / Info 4. Вердикт: к приёмке — ДА, блокеров нет.**
  - [ ] **[L-F8S-1] [low, new, honesty]** `plans/reports/round1025_f8_config_diff.md:12–14` — пустые срезы `chats`/`dm`/`permsoc` показаны как `OK (без изменений)` при `unchanged=0` (offline-baseline, живой снимок не снимался; T-2998/T-3000 @DevOps) → «0 из 0» вакуумно, не доказательство сохранности. **Fix:** помечать `н/д (нет живых данных)` и уточнить в `results.md` §5. (не блокирует)
  - [ ] **[L-F8S-2] [low, new, regression-gate]** `tools/config_snapshot_diff.py:299–302` — `--diff` всегда `return 0`, даже при реальных added/removed/changed (в отличие от `gen --check`); метод заявлен как гейт для **F10** → риск ложного «зелёного». **Fix:** `--fail-on-changes` (exit≠0). (не блокирует)
  - [ ] **[L-F8S-3] [low, new, R17-coverage]** `tools/gen_param_registry_round1025.py:505–513` сканирует 4 артефакта; `tests/test_round1025_f8_registry.py:156–158` — `ARTIFACTS` без `round1025_f8_results.md`; `run_check` не читает `config_diff.md`. **Fix:** расширить список. Ручной скан @Scanner чист. (не блокирует)
  - Info (не блокируют): I-F8S-1 (`tools/` не полностью изолирован — pre-existing `tools.video_downloader`; F8-инструменты чисты), I-F8S-2 (мёртвый `scan_for_secret_patterns`), I-F8S-3 (spec §3.2 «== ключи REGISTRY» неточен — фактически `{s.pg_key}`; сверка корректна), I-F8S-4 (живой PG-diff отложен, раскрыто).
  - **Handoff @Scanner:** @Orchestrator → `SCANNED`. Deploy — NOT_APPLICABLE.

## Round 10.25 F7 `permsoc-local-space-round1025` (PERMsoc — локальное пространство чата §60–§67 + per-chat блок-гейты) — аудит рабочего дерева (Step 6 @Scanner, 23.09.2026, T-2957; **итерации 2–3, финал: +H-F7-7/L-F7-8/L-F7-9**) — all scanned, PENDING=0
База — HEAD `551847d` (тег `pre-round1025-f7`; правки НЕ закоммичены). Отчёт: `plans/reports/round1025_f7_scanner_audit.md`. @Reviewer итер.3 — **Approved**. **Итерация 3 (финал): Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 — к деплою ДА.**
- [x] A — scope «Только этот чат»/`.scope-tech`, guard `PERMSOC_LOCAL_KEYS` в `persistItems`/`saveConfigItem` (явный `failed{reason:'permsoc-global'}` + toast, не молча) — чисто; **guard цел**
- [x] B — 6 owner-блоков, key-level partition (60 body + 5 toggle = 65 ключей вкладки, «ключ ровно в одном блоке»), «Общее/Мастер» выведено в отдельный уровень §61 — чисто
- [x] C — OFF блока пишет только `toggleKey`/`gate`, дочерние byte-identical (JS-тест) — чисто
- [x] D — `permsoc_reactions`/`permsoc_schedule` в `feature_gates` (память `chat_params["gates"]`, Δ DDL=0, Δ каталога=0); `PermsocBlockGate` в war/common/vasya/slavik/alan/alan_greeting; goodmorning `_tick` no-send; RBAC `permsoc*` → global admin (`who_can_toggle`/PUT 403) — чисто; **серверные гейты не менялись с итер.1**
- [x] E — §62–§67 presentation-level; **H-F7-1 CLOSED**: `PERMSOC_BLOCK_SUBGROUPS`+`permsocRenderItems` — 24 подгруппы реально в DOM (матрица), deprecated `slavic_photo_path` сохранён, round-trip % Костика; **M-F7-2 CLOSED**: `PERMSOC_LIST_WIDGET_KEYS`+`_normalizeConfigItems`+`listEditorProps variant='ids'` (списки ID Оли — list, матрица `hasTextarea:False`); **H-F7-7 CLOSED**: `list-editor._numericList()/toStoredValue()` — ID Оли числами (round-trip `includes(-100123)===true`), фразы Костика строками; pytest-эмуляция `OlyaVideoFilter` int→True/str→False; **L-F7-8 CLOSED** («Лимит N ID/фраз»)
- [x] F — kill-switch env-only `PERMSOC_BLOCK_GATES_ENABLED` (default ON → baseline True; OFF → блок-тумблеры read-only), `ui_flags` bool-only, bump 2.58.15 синхронен — чисто
- [x] `config/settings.py` + `README.md` + пины тестов/hotfix7–10/F6/scope/design-tokens — версия 2.58.15 атомарно; маркеры не ослаблены — чисто
- [x] `tests/*`/`tests/js/*` — `round1025_f7_permsoc_local_test.js` (+регистрация; +подгруппы/список-ID +H-F7-7 round-trip типа), `test_permsoc_f7_round1025.py` (+`test_olya_saveasbot_list_type_comparison` int/str), `test_webapp_f7_round1025.py` (+`TestBlockSubgroupsRendered`/`TestOlyaIdLists`); **L-F7-5 CLOSED** `test_all_six_owner_blocks_always_render`; AMEND `round109_ui` под D1/D2 — чисто
- [x] `tools/ui_round1025_matrix.py` — `#/permsoc` chat/global + **L-F7-3 CLOSED** отдельный no-chat контекст (`_route_nochat`/`_permsoc_nochat_failures`); harness-stub `key=spec.pg_key` — чисто
- [x] инварианты — Δ DDL=0, Δ каталога=0 (459/98/96/21/418; `param_catalog.py` не тронут), CSP `script-src 'self'`/zero-build, R17/R18, `git diff --check`=0, гигиена индекса — чисто
- **СВОДКА 10.25 F7 (итер.3, финал): Critical 0 / High 0 / Medium 0 / Low 3 / Info 3. Вердикт: к деплою — ДА, обязательных возвратов @Builder нет.**
  Independent (@Scanner, итер.3): `node --check` OK; **JS 38/38 OK**; `py -3 -m pytest -q` → **8374 passed / 0 failed**; matrix **failures: 0** (24 подгруппы, no-chat owners=0+banner, Оля-list); `git diff --check`=0; серверный дифф D3/guard неизменен; тег `pre-round1025-f7`, `.env.bak.round1025-f7`, `stash@{0}` целы; `.env`/zip/скриншотов нет. Живой WebView/TMA — PENDING OWNER (T-2961).
  Follow-up (ноты, не блокеры): **L-F7S-1** (D1-guard «PERMsoc не в global» — клиентский; серверный `POST /api/config` global-путь не дублирует; не эскалация, только global admin), **L-F7-4** (`flags.dead_page_post_on_join` без рантайм-гейта; T-2939/2940), **L-F7-6** (DM-мастер pre-existing).
  Follow-up (не блокеры): **L-F7S-1** (D1-guard «PERMsoc не в global» — клиентский; серверный `POST /api/config` global-путь не дублирует; не эскалация, только global admin; hardening — серверный denylist), **L-F7S-2** (`flags.dead_page_post_on_join` в блоке «Общие реакции» без рантайм-гейта; follow-up T-2939/2940).

## Round 10.25 F6 `memory-analytics-reorg-round1025` (Аналитика §21–§30 + adapter ExecutionGraph + «Память» §52–§59) — аудит рабочего дерева (Step 6 @Scanner, 23.09.2026, T-2912; **итерация 2 после ремедиации H2/M-F6S-1/L-F6S-3..5 + AMEND-1 H1**) — all scanned, PENDING=0
База — HEAD `f103992` (тег `pre-round1025-f6` → `f103992`; правки НЕ закоммичены). Отчёт: `plans/reports/round1025_f6_scanner_audit.md`. **Итерация 2: Critical 0 / High 0 / Medium 0 / Low 2 / Info 4 — к деплою ДА.**
- [x] `web/app.js` — adapter-backed `tokenFlowTree`, 2 несмешиваемых режима (`execMode`/`setExecMode` + `resetExecFilters` при смене режима), фильтры §27 (модуль/модель/этап/статус + `execFilterQuery`-поиск), `execStatusOptions`, `execAggregate` применяет только `{module}`, `execDetail`/`selectExecNode`/`closeExecDetail`, превью (`execPreview`/`loadExecPreview`), honest `fmtCost(v,known)` + `execCostLabel`/`fmtTokensCell`/`execStatusLabel`, `openHubCard` сбрасывает `memorySubgroup`, 5 подгрупп «Памяти» (`MEMORY_SUBGROUPS`/`_memoryGroups`/`_memorySubgroupOf`), `HUBS_V2['#/memory']` 3 раздела — чисто; **M-F6S-1 CLOSED**, L-F6S-3 CLOSED, L-F6S-5 CLOSED
- [x] `web/index.html` — 4 режима, взаимоисключающие ветки trace/aggregate, фильтры (+ `input type="search"`, статус-селект, кнопка «Сбросить» в обеих ветках), detail-overlay на `#app` (`aria-modal="true"` + `.exec-detail-backdrop` + Esc), превью «Последний вызов» на Статусе, подгруппы «Памяти», `<script src="/static/execution_graph.js?v=...">` до `app.js` — чисто; **L-F6S-4 CLOSED**, L-F6S-2 остаётся (Low-техдолг)
- [x] `web/static/execution_graph.js` — adapter `window.ExecutionGraph` (`fromTrace/fromSummary/filter/detail` + `searchHaystack` для поиска); `cost=null` при `price_known!==true`, `status='unknown'`, `parentIds` только линейная последовательность (`tool`→`[]`), `algorithm/format/publish` в enum, но не эмитятся; без DOM/внешних ресурсов — чисто
- [x] `web/static/app.css` — аддитивные `.token-flow__node--llm/--algorithm/--format/--publish/--other`, `.exec-detail` (side-panel/bottom-sheet), `.exec-preview` — чисто
- [x] `config/settings.py` + `README.md` — `APP_VERSION` 2.58.14 синхронен (`?v=__APP_VERSION__`) — чисто
- [x] `tests/*` + `tests/js/*` — 2 новых JS-раннера (`F6-EXECGRAPH-OK`/`F6-ANALYTICS-MEMORY-OK`) + `test_webapp_f6_round1025.py` (**19**) + регистрация; версии-пины и AMEND `round1024_nodeflow` атомарны (не ослаблены) — чисто; H2/M-F6S-1/L-F6S-3/4/5 покрыты новыми проверками (поиск/статус/сброс/aria-modal/backdrop/escClose)
- [x] инварианты — Δ DDL=0 (`services/handlers/migrations/web/api` пусто), Δ каталога=0 (459/98/96/21/418), CSP/zero-build, R17/R18 — чисто
- **СВОДКА 10.25 F6 (итер.2): Critical 0 / High 0 / Medium 0 / Low 2 / Info 4. Вердикт: к деплою — ДА, обязательных возвратов @Builder нет.**
  Independent (@Scanner, итер.2): `node --check` OK; JS **37/37 PASS**; F6 pytest **19 passed**; полный `pytest -q` **8334 passed / 1 skipped / 5 env-failed** (outgoing_guard/summary_cover, вне F6); `git diff --check`=0; тег `pre-round1025-f6`→`f103992`, `.env.bak.round1025-f6`, `stash@{0}` целы; `.env`/zip/скриншотов нет.
  Follow-up (не блокеры): L-F6S-1 (honest-цена агрегата: summary без `price_known`), L-F6S-2 (OFF-«Итого» не byte-identical); H2/M-F6S-1/L-F6S-3/4/5 **CLOSED**, H1 закрыт AMEND-1 (`adr-1025-19a`). Live-гейт T-2917 (реальный Telegram WebView) — открыт за владельцем.

## Round 10.25 F5 `module-workspace-tabs-round1025` (§46–§49/§84/§85 workspace/промпты/модели) — аудит рабочего дерева (Step 6 @Scanner, 22.09.2026; повторный после правки M-F5S-1 + T-2714/T-2703/T-2733) — all scanned, PENDING=0
База — HEAD `12a55bb` (`pre-round1025-f5`; правки НЕ закоммичены). Отчёт: `plans/reports/round1025_f5_scanner_audit.md`; AI-карта — `plans/reports/round1025_f5_ai_map.md`.
- [x] **[M-F5S-1] RESOLVED (итер.2)** `web/app.js` — `parsePromptLibraryRoute` читает `promptKey`; `workspace()` прокидывает `promptKey` для `door='library'`; `openWorkspacePrompt` для библиотеки строит `#/ai/prompts/<slug>[/<stage>]/<key>`; probe PROBE-ALL-PASS (summary/sleep/factcheck — редактор открыт, модульная дверь цела); покрыто блоком (g) + pytest
- [x] `web/app.js` — маршрут `#/modules/<slug>[/<wt>[/<stage>/<key>]]` + `#/ai/prompts/<slug>[/<stage>[/<key>]]`, `routeToTab`=m.tab (RBAC/kill-switch целы), `routeParent`/`routeDepth`, шов `openModuleWorkspace`=навигация + fallback `openModuleWindow`, store F4-тумблер, `providerGrouped` 6 групп, single-write-path, `buildConnectionCard`/`workspaceModelCards`/`connectionCard`/`toggleConnectionSettings`/`testConnection` (§49) — чисто
- [x] `web/index.html` — workspace-шапка/табы/overview, §85 placeholder, §84 L1/L2, §48 master-detail + «две двери», §49-карточка `data-connection-card` (название/назначение/основная/резервная/статус + «Проверить»/«Настроить») — чисто; L-F5S-2 (ARIA) закрыт (`role="group" aria-label`, без `listitem`)
- [x] `web/static/app.css` — `.workspace-prompt-lib` 3→2→1, mobile list→editor, `.conn-*`, тач-цели ≥44px (`.prompt-tree-item`, `[data-workspace-tabs] button`, `[data-conn-*]`) — чисто; L-F5S-1 закрыт
- [x] `config/settings.py` + `README.md` — `APP_VERSION` 2.58.10 синхронен — чисто
- [x] `tests/*` + `tests/js/*` + `tools/ui_round1025_matrix.py` — 3 новых JS-раннера + `test_webapp_f5_round1025.py` (19) + регистрация; версии-пины и `providerGrouped`-маркеры обновлены атомарно (не ослаблены); новые тесты M-F5S-1/L-F5S-1..3/§49-карточка; T-2703 матрица (`F5_PROBE_JS`, 4 F5-маршрута) — чисто
- [x] инварианты — Δ DDL=0, Δ каталога=0 (459/98/96/21/418), CSP/zero-build, без новых API/библиотек/WebGL, R17/R18 — чисто
- **СВОДКА 10.25 F5: Critical 0 / High 0 / Medium 0 / Low 0 / Info 2. Вердикт: к деплою — ДА, обязательных возвратов @Builder нет.**
  Independent (итер.2): `node --check` OK, JS `MODULE-WORKSPACE-OK`/`PROMPTS-SINGLE-SOURCE-OK`/`MODELS-GROUPS-OK`/`JS-UNIT-OK` + `IMAGE-MODULE-OK` + hotfix7 OK, целевые pytest **19 passed**, регресс-пины **202 passed**, `git diff --check`=0; тег/бэкап/`.env.bak`/`stash@{0}` целы; `.env`/zip/скриншотов нет.
  Follow-up: Low закрыты. Live-гейт T-2742 (реальный Telegram WebView) — открыт за владельцем; Playwright T-2703 (`failures: 0`) @Scanner не воспроизводился (Info).

## Round 10.25 F4 `module-catalog-quickpanel-store-round1025` (§31–§45 каталог/панель/store) — аудит рабочего дерева (Step 6 @Scanner, 22.09.2026) — all scanned, PENDING=0
База — HEAD `b5f8348` (`pre-round1025-f4`; правки НЕ закоммичены, включая rework iter2 F4-M1). Отчёт: `plans/reports/round1025_f4_scanner_audit.md`.
- [x] `web/app.js` — `MODULES` (`keywords`/`runtimeGate`/`parentGate`, витринные имена), `ModuleConfigurationStore` (`storeScope/storeKey/getModuleState/_moduleRuntimeState/moduleRuntimeNotice/moduleStateText/setModuleState/refreshModuleState/subscribeModuleState`), overlay `moduleOptimistic/Pending/SaveError`, избранное `localStorage`, шов `openModuleWorkspace` — чисто; Low L-F4S-1 (`stickyFailedKeys` между чатами), L-F4S-2 (parent-gate по эффективному `value`); F4-M1 fix подтверждён
- [x] `web/index.html` — страница «Модули» §32 (счётчики → панель → поиск/фильтры → каталог), карточка §33, головной тумблер модалки — чисто
- [x] `web/static/app.css` — `.module-catalog`/`.module-list` тиры ≤3/2/1, `.module-quick` ≤4/2/1, `.module-toggle` 44×44, счётчики/поиск/фильтры/empty-state — чисто
- [x] `config/settings.py` + `README.md` — `APP_VERSION` 2.58.9 синхронен — чисто
- [x] `tests/*` + `tests/js/*` — новые F4-раннеры/структурные тесты + регистрация; версии-пины; `nav_disclosure` усилен (L-F4-4) — чисто
- [x] инварианты — Δ DDL=0, Δ каталога=0 (459/98/96/21/418), CSP/zero-build, без новых API/библиотек/эндпоинтов — чисто
- **СВОДКА 10.25 F4: Critical 0 / High 0 / Medium 0 / Low 2 / Info 3. Вердикт: к деплою — ДА, обязательных возвратов @Builder нет.**
  Independent: `node --check` OK, JS `MODULE-STORE-OK`/`MODULE-CATALOG-OK`/`JS-UNIT-OK`, целевые pytest **165 passed**, полный pytest **8229/0**, `git diff --check`=0; тег/бэкап/`stash@{0}` целы; `.env`/zip/скриншотов нет.
  Follow-up (Low, не блокеры): L-F4S-1 (сброс `stickyFailedKeys` при смене области), L-F4S-2 (parent-gate по `global_value`). Live-гейт T-2656 (реальный Telegram WebView) — открыт за владельцем.

## Round 10.25 hotfix7 `hotfix7-shell-glass-heartbeat-round1025` (UPD «Срочный фикс фронта») — аудит рабочего дерева (Step 6 @Scanner, 22.09.2026) — all scanned, PENDING=0
База/голова аудита — `5a5465c` (`pre-round1025-hotfix7`; правки НЕ закоммичены). Отчёт: `plans/reports/round1025_hotfix7_scanner_audit.md`; AA — `plans/reports/round1025_hotfix7_contrast.md`; матрица — `plans/reports/round1025_hotfix7_ui_report.md`.
- [x] `web/static/app.css` — `--shell-h` (base `100vh` + dvh/min() строго в `@supports`), два режима normal/fullscreen, `--shell-*`/`--card-shadow`, shell-панели (sidebar/drawer/header/bottom-nav/more-sheet), specular/texture, `@supports`-фолбэк, `.shell-*-legacy`, виньетка .42→.30 — чисто; Low L-H7-1 (мёртвый @supports-фолбэк из-за порядка каскада), L-H7-2 (OFF-путь header: рамка+тень), L-H7-3 (specular∩texture 4.44:1)
- [x] `web/app.js` — computeds `shellGlassV2`/`shellLayoutV2`/`heartbeatPremium`,ECG sweep-wipe (`_hbEcg`/`_hbPalette`/`_hbDrawGrid`/`_hbDrawPremium`) + canvas-legacy (`_hbDrawLegacy`), DPR-cap 2, без WebGL/`pulseX`; семантика `_heartbeatTransition`/`heartbeatSample` не тронута — чисто
- [x] `web/index.html` — привязка классов `.app-shell` (`shell-layout-v2/legacy`, `shell-glass-v2/legacy`) — чисто
- [x] `config/settings.py` + `web/api/routes.py` + `.env.example` — env-only `ClassVar` (`UI_SHELL_GLASS_V2`/`UI_HEARTBEAT_PREMIUM`/`UI_SHELL_LAYOUT_V2`, default ON), аддитивный `ui_flags` (только bool), `APP_VERSION` 2.58.8 — чисто
- [x] `tests/*` + `tests/js/*` — новый `round1025_hotfix7_shell_glass_heartbeat_test.js` + `test_webapp_hotfix7_round1025.py` + регистрация + пин версии/wash; маркеры атомарны и усилены (не ослаблены) — чисто
- [x] `tools/ui_round1025_matrix.py` — 5 режимов, `F7_PROBE_JS`, `_hotfix7_failures`, `f2ShellH`/`__f2_broken`; воспроизведена @Builder (`failures: 0`), в среде @Scanner не перезапускалась — Info
- **СВОДКА 10.25 hotfix7: Critical 0 / High 0 / Medium 0 / Low 3 / Info 3. Вердикт: к деплою — ДА, обязательных возвратов @Builder нет.**
  Independent: `node --check` OK, JS hotfix7 + все `tests/js/*.js` PASS, pytest **8207/0**, целевые **156 passed** + nav **28 passed**, `git diff --check`=0; Δ DDL=0, Δ каталога=0 (459/98/96/21/418), `backdrop-filter: url(`=0, WebGL=0, `APP_VERSION` 2.58.8 синхронен, `stash@{0}`/теги/бэкапы целы, `.env`/zip/скриншотов нет.
  Follow-up (Low, не блокеры): L-H7-1/L-H7-2/L-H7-3. Live-гейт T-2682 (реальный Telegram WebView + FPS) — открыт за владельцем.

## Round 10.25 hotfix6 `hotfix6-webview-shell-heartbeat-round1025` (пакет «Волна 1.5») — аудит рабочего дерева (Step 6 @Scanner, 22.09.2026) — all scanned, PENDING=0
База/голова аудита — `441e8f7` (правки НЕ закоммичены на момент скана); диапазон правок пакета `441e8f7` → `055525c` (код+тесты) + docs `ba75751`. Отчёт: `plans/reports/round1025_hotfix6_scanner_audit.md`; AA — `plans/reports/round1025_hotfix6_contrast.md`.
- [x] `web/static/app.css` — foreground-линза `[data-glass="a"]::before` (`filter:var(--glass-displace)`), radial-mask, стекло `.app-sidebar`/`.app-drawer`/`header.header-sticky`/`.bottom-nav`/`.more-sheet`, шапка с blur — чисто; Low L-H6-2 (линза на скролл-контейнерах)
- [x] `web/index.html` — inline `#lg-lens` (единственный SVG-фильтр, CSP-safe), две строки шапки под `UI_HEADER_COMPACT_V2`, ⛶ (`:aria-pressed`, тач ≥44×44), canvas — чисто; Low L-H6-1 (`role="img"` у canvas, `aria-describedby` v-if)
- [x] `web/app.js` — `reconcileLiquidGlass`/tier/кап `UI_LENS_MAX_NODES`, `_liquidGlassSupported` по feature-detect (UA-gate снят), heartbeat Canvas 2D+rAF + `heartbeatLegacy`, fullscreen D5, teardown rAF/ResizeObserver — чисто; Low L-H6-3 (stale-порог-комментарий)
- [x] `web/static/telegram-init.js` — `computeBottomOffset()=max(...)`, пересчёт на `viewportChanged`/`safeAreaChanged`/`contentSafeAreaChanged`/`resize`, guard `stableH>0` — чисто
- [x] `config/settings.py` + `web/api/routes.py` — env-only `ClassVar`-флаги (`UI_GLASS_TIER_OVERRIDE`/`UI_HEARTBEAT_CANVAS_ENABLED`/`UI_HEADER_COMPACT_V2`/`UI_LENS_MAX_NODES`), аддитивный `ui_flags` (383-392), `APP_VERSION` 2.58.7 — чисто
- [x] `tests/*` + `tests/js/*` — маркер-тесты F2/F3/hotfix4 переведены на новую семантику и усилены (не ослаблены), `round1025_hotfix6_lens_heartbeat_shell_test.js` — чисто; Info Playwright (`tools/ui_round1025_matrix.py` не воспроизведён — нет `playwright`)
- **СВОДКА 10.25 hotfix6: Critical 0 / High 0 / Medium 1 / Low 3 / Info 3. Вердикт: к деплою — ДА, обязательных возвратов @Builder нет.**
  Целевые pytest **119 passed**, JS `HOTFIX6-LENS-HEARTBEAT-SHELL-OK`/`JS-UNIT-OK`, `node --check` OK, `git diff --check`=0; Δ DDL=0, Δ каталога=0, `backdrop-filter: url(` = 0, `stash@{0}`/теги целы, секретов/zip нет.
  Итоговые прогоны пакета (после Scanner, @Builder/@DevOps): pytest **8185 passed / 0 failed**, JS **26/26**, matrix **0**; прод `ba75751`, `APP_VERSION` **2.58.7**, health **200**, `database is locked`=0.

## Round 10.25 ПАКЕТ F2+hotfix5+F3 — повторный аудит финальных коммитов (Step 6 @Scanner, 22.09.2026) — all scanned, PENDING=0
Диапазон `f2328fb..HEAD` (`3caddeb`). Финалы: F2 `d2df8ca`, hotfix5 `412f844`, F3 `4f31197` (ревью-фиксы покрыты).
- [x] `web/app.js` (reconcileLiquidGlass обратимо через `data-glass-downgraded`, `_lgSchedule` троттлинг+observer,
      WebKit UA-gate, `hasUnsavedEdits`+blockDrafts/persona/dossier, `resetChatOverride` паритет local_admin) —
      **M10.25F2-1 ЗАКРЫТ**, **M-F3-1 ЗАКРЫТ**; M10.25F2-2 частично (iOS Edge `EdgiOS` — Low)
- [x] `web/static/app.css` (downgraded-правило, контраст Tailwind-утилит `--text-3/--err-text`, `.btn-reset-global`) —
      контраст пересчитан (5.25:1/6.07:1); L10.25F2-1 (sticky-header) открыт
- [x] `web/index.html` (кнопки возврата ×8, `btn-reset-global`, поиск scope всегда) — Critical mobile-overflow закрыт (CSS)
- [x] `services/image_generation.py` (retry=False→max_retries=0, `is_transient_reason`, `wait_for`-дедлайн, global+per-chat budget) —
      **M10.25H5-1 ЗАКРЫТ**
- [x] `config/settings.py` + `.env.example` (клампы окно≤600/attempts≤5/backoff≤30; worst-case 362 c документирован) — чисто
- [x] `tests/*` + `tools/ui_round1025_matrix.py` — целевые 152 passed, JS 25/25; matrix НЕ воспроизведён (нет playwright) — I-1
- **СВОДКА ПАКЕТА: Critical 0 / High 0 / Medium 1 / Low 5 / Info 4. Вердикт: к деплою — ДА, возвратов @Builder нет.**
  pytest **8146 passed / 5 failed / 1 skipped** (5 — env aiogram `InputRichMessageMedia`, вне пакета); Δ DDL=0, Δ каталога=0,
  `stash@{0}` цел, zip/секретов нет. Отчёт: `plans/reports/round1025_package_scanner_audit.md`.

## Round 10.25 hotfix5 `summary-cover-window-round1025` scan (Step 6 @Scanner, 21.09.2026) — all scanned (diff `0e43c37..b3fb6a5`, `b3fb6a5`) — ⚠️ SUPERSEDED повторным аудитом финальных коммитов выше (правки `cbaec05`,`412f844`)
- [x] services/image_generation.py (окно 180 c + bounded-retry 2/backoff, `reason_class`/`provider_label`, timeout-класс, temp-хелпер) — чисто; **M10.25H5-1** (ретрай ×2 умножается на внутренний 429/503 → до 4 вызовов/~4×окна)
- [x] services/worker_budget.py (env-only ветка `image_calls`, sentinel, изоляция от `llm_calls`/`llm_tokens`) — чисто
- [x] services/summary_scheduler.py (`int(chat_id)` до DM-фильтра, мусор/NULL → skip без падения тика) — чисто
- [x] services/summary_generator.py (WARNING с `reason_class`/provider, R17-safe; одно списание бюджета) — чисто
- [x] config/settings.py + .env.example (env-only ClassVar, Δ каталога = 0) — чисто
- [x] tests/* (новый hotfix5-файл + правки 1023/webapp_dm_ui; не тавтологичны, падают на старом коде) — чисто; L10.25H5-3 (grep-тест планировщика)
- **СВОДКА 10.25 hotfix5: Critical 0 / High 0 / Medium 1 / Low 3 / Info 1.** pytest **8124/0** (113.19 s), JS **24/24**;
  Δ DDL=0, Δ каталога=0, `stash@{0}` цел, zip/секретов нет. Вердикт: **к деплою — ДА**, обязательных возвратов @Builder нет.
  Отчёт: `plans/reports/round1025_hotfix5_scanner_audit.md`.

## Round 10.25 F2 `design-tokens-liquidglass-v2-round1025` scan (Step 6 @Scanner, 21.09.2026) — all scanned (diff `f2328fb..HEAD`, `e895726`) — ⚠️ SUPERSEDED повторным аудитом финальных коммитов выше (правки `0f227a5`,`d2df8ca`)
- [x] web/static/app.css (токены §8 + Liquid Glass A/B/C + фон §10 + `@supports`-фолбэки) — чисто; Low L10.25F2-1 (sticky-header alpha 0.96→0.85)
- [x] web/index.html (inline SVG `#lg-displace`; `data-glass="a"|"c"`) — чисто (CSP-safe, один фильтр, без layout shift)
- [x] web/app.js (палитра графика §8, `reconcileLiquidGlass`/`_liquidGlassSupported`, `setBgPaused`) — чисто; **M10.25F2-1/-2/-3**
- [x] web/static/telegram-init.js (фолбэки темы §8) — чисто
- [x] tools/ui_round1025_matrix.py (F2-пробы: токены/диапазоны/glass/reduced-motion/hidden) — чисто; Low L10.25F2-3 (точные 75s/105s)
- [x] tools/ui_audit_round1021.py (`--grad-speed-slow` в пробе) — чисто
- [x] config/settings.py (`APP_VERSION 2.58.5`) + README.md — чисто; Low L10.25F2-4 (счётчик тестов устарел)
- [x] tests/test_webapp_design_tokens_round1025.py + tests/js/round1025_design_tokens_test.js + правки старых UI-тестов — inventory на множествах, маркеры не ослаблены; Low L10.25F2-2 (тавтологичный `"240" in APP_JS`)
- **СВОДКА 10.25 F2: Critical 0 / High 0 / Medium 3 / Low 4.** pytest **8096/0** (106.03 s), JS **24/24**;
  Δ DDL=0, Δ каталога=0, `stash@{0}` цел, zip/секретов нет, `git diff --check`=0. Вердикт: **к деплою — ДА**,
  обязательных возвратов @Builder нет. Отчёт: `plans/reports/round1025_f2_scanner_audit.md`.

## Round 10.24 scan (Step 6 @Scanner, 20.09.2026) — all scanned (diff-based, HEAD 379cfdd, 132 файла) — files processed
- [x] web/api/routes.py (F20 critical: разведены `perm_overrides`/`overrides`; merge не стирает
      остальные per-chat значения; `set_chat_params` пишет только overrides+meta; F11 scope
      `auto|global|chat` с `is_global_admin`; F12 `POST /api/images/test` global-admin + rate-limit;
      F8 `_persona_traits_meta` fail-open) — чисто
- [x] services/chat_keys.py (_sign global secrets `keys.image_api_key`, kill-switch
      `BYOK_IMAGE_KEY_ENABLED`, `record_global_secret_audit` только `***`, Δ DDL=0) — чисто
- [x] services/budget_gate.py + chat_usage.py + worker_budget.py + direct_chat_service.py
      (F21 master: chat→global→default ON, fail-open; enforcement direct/фон/контекст; учёт при OFF) — чисто
- [x] manage.py (F9 `disk audit|cleanup` dry-run + verify fail-closed; F22 `apply-chat-overrides`
      merge + `audit-chat-overrides` READ-ONLY/fail-loud/--strict; F10 `diag aliases` READ-ONLY) — чисто
- [x] services/disk_retention.py + memory_backup.py + memory_rebuild.py + memory_maintenance.py
      (F9: 1 DB-бэкап, immutable-история deny-list+sniff fail-closed+re-classify, facts 1) — чисто
- [x] services/media_marker.py + native_media.py + chat_context.py + thread_chain.py
      (F13/F14/F19: диалект маркера, единый резолвер, media-строки без потери окна/бюджета) — чисто
- [x] services/tool_router.py + tool_schemas.py (F14/F19: native-first, `transcribe_video` 10-й,
      первые 9 байт-в-байт, kill-switch'и OFF-тесты) — чисто; Low L10.24-2 (2 ГБ лимит)
- [x] handlers/youtube.py + voice_transcription.py + video_download.py (F16 download→multimodal→subtitle,
      F19 форс-повтор STT, idempotency `_row_has_transcript`, reason age_restricted) — чисто;
      Low L10.24-1 (тристейт тихий пропуск), Info I10.24-5 (send_message вне обёрток, allowlisted)
- [x] services/youtube_summarizer_service.py + youtube_transcript_engine.py (F16: L3-only cascade,
      `reason` на исключении, credentialed kill-switch) — чисто
- [x] services/smart_cache.py (F17 PRAGMA + bounded retry на locked, fail-open, счётчик) — чисто
- [x] services/external_log.py + image_generation.py + summary_generator.py (F2 R17-safe хелперы,
      F12 универсальный payload/b64/probe, красный ключ в body_excerpt) — чисто; Low L10.24-3 (body без `_redact_secret`)
- [x] services/llm_client.py + dream_worker.py + summary_memory.py (F1 `generate_background`/чанки/батч-кап,
      F8 traits перед paradigm-ветками, per-chat счётчик фейлов) — чисто; Info I10.24-2 (текст исключения)
- [x] services/param_catalog.py + web/app.js + web/index.html + web/api/oversight.py + memory_agi.py
      (F5/F21/F24/F3/F4/F10/F6: GROUPS 98, `mod_images`, `flags_module_budgets`, `limits_anticliche`,
      `ui_flags`, dossier-feed user_id, XSS-санитизация) — чисто; Info I10.24-3 (N+1), I10.24-1 (cap)
- [x] config/settings.py + bot.py + .env.example (env-only ClassVar-рубильники, DI `transcriber`, порядок
      роутеров не сдвинут, Δ DDL=0) — чисто
- [x] tests/* (полный pytest **7911 passed / 0 failed**, 103.71 s; JS round1024-тесты; grep секретов —
      только тестовые плейсхолдеры) + `.env.example` без реальных значений; `git diff --check` exit 0
- **СВОДКА 10.24: Critical 0 / High 0 / Medium 0 / Low 3 (open) / Info 5.**
  Валидатор: SQLite v12 (Δ=0), PG DDL (Δ=0), канон инструментов 10, GROUPS 98.
  Вердикт: **Merge/деплой разрешён**; обязательных возвратов @Builder нет.
  Отчёт: `plans/reports/round1024_scanner_audit.md`.

<!-- Format: one item per line, `- [ ]` = pending, `- [x]` = done -->
<!-- High-priority (git-changed) files go on top; no code-change files this run. -->

## Round 10.23 scan (Step 6 @Scanner, 19.09.2026) — all scanned (diff-based, HEAD 2e056e7, 22 коммита) — files processed
- [x] services/target_marking.py + summary_xml.py + canonical_context.py + chat_context.py + outgoing_guard.py (F1: единый маркер,
      оба рендера, анти-эхо, ровно один раз; smoke байт-путь) — чисто
- [x] services/thread_chain.py + database.get_messages_around + handlers/factcheck._fetch_chat_context (F2: окно/граф/fail-open,
      keep-end бюджет, `_trusted_text` без chat_context) — чисто; Low L4 (шум миграции)
- [x] services/system2_handoff.py + prompt_style_blocks.py + negative_constraints.py (F3: роутер в Stage-1, канальные блоки,
      `detect_plain_tables`) — чисто; **M2** (`response_mode` в Stage-2 JSON direct/factcheck)
- [x] services/anticliche_cache.py + anticliche_worker.py + web/api/anticliche.py + pg_db DDL (F4: PG-кэш, re.escape, guard пустого,
      S10.22-4b, RBAC global admin) — чисто
- [x] services/image_generation.py + tool_schemas.py + tool_router.py + worker_budget.py + telegram_send.send_photo (F5: tool 9-й,
      POST/GET, бюджет, секрет env/PG, anti-double) — чисто; **M1** (корреляция пре-гейта), Low L1 (image_calls), L3 (SSRF/size)
- [x] services/summary_generator.py + telegram_send.build_cover*/send_rich_message (F6: cover_prompt, Article, тихий фолбэк,
      даунгрейд по содержимому, egress-реестр) — чисто; Low L2 (`_strip_safe_html` на rich)
- [x] services/usage_events.py + llm_pricing.py + llm_client.py + tool_loop.py + web/api/analytics.py + pg_db DDL (F7: correlation-id
      Stage1/tool/Stage2, cost/price_known, retention, RBAC) — чисто; **M1** (image-нода без родительской корреляции)
- [x] services/param_catalog.py + prompt_migrations.py + chat_prompts.py + summary_prompts.py + factcheck_prompts.py + web/app.js +
      web/index.html (F8/F9: +18 каталога, PG-промпты, UI-табы, справка v5 + guide v2, backup/reset RBAC) — чисто; Info I2 (stale doc)
- [x] bot.py + config/settings.py + config_cache.py + config_migrations.py + web/app.py + .env.example (DI воркера, env-рубильники,
      идемпотентные миграции, порядок роутеров не сдвинут, PG-DDL идемпотентен, SQLite v12) — чисто
- [x] tests/* (полный pytest 7418 passed / 0 failed; node --check OK) + grep секретов (sk_/gsk_/ghp_/Bearer/ssh-rsa/PRIVATE KEY —
      только фейковые фикстуры)
- **СВОДКА 10.23: Critical 0 / High 0 / Medium 2 (M1 correlation картинок, M2 response_mode в Stage-2; не блокеры) /
  Low 4 / Info 4.** Валидатор: каталог 457/96/94 (Settings 416), SQLite v12 (Δ=0), PG +3 таблицы, aiogram 3.31.0.
  Вердикт: **обязательных возвратов @Builder нет; раунд передаётся на Merge/деплой** (Medium — к решению владельца/tech-debt).
  Отчёт: `plans/reports/round1023_scanner_audit.md`.

## Round 10.22 scan + re-audit (Step 6 @Scanner, 19.09.2026) — all scanned/closed (diff-based, HEAD acd9311 + worktree)
- [x] services/memory_rebuild.py (F1: fail-closed `_belief_source_set` — S10.22-1 CLOSED; `:787-847` + тест
      `test_belief_read_error_skips_chat_fail_closed`; rebuild_empty/exit — S10.21-инвариант цел)
- [x] services/dossier_rebuild_jobs.py (F8: `cleaned>0 & rebuilt==0` → `failed`/`rebuild_empty` — S10.22-2 CLOSED;
      `interrupted` вне `_ACTIVE_STATUSES` + prune — S10.22-5 CLOSED; `restore_user_snapshot` whitelist по
      `PRAGMA table_info` — S10.22-9 CLOSED)
- [x] services/negative_constraints.py (F6: `as_ai` сужен до 1-го лица — S10.22-4 CLOSED; остаток S10.22-4b Info —
      ложное срабатывание при запятой «Он, как искусственный интеллект, …»)
- [x] services/telegram_send.py + handlers/voice_transcription.py (F6: обоснование allowlist отделяет ASR-транскрипт
      от Stage-2 LLM + escape-инвариант — S10.22-3 CLOSED, достаточно)
- [x] services/summary_generator.py (R17: лог только len/latency, без сырого текста — S10.22-8 CLOSED)
- [x] web/api/chat_lore.py + web/app.js + web/index.html (F8: `latest` 404 при kill-switch → UI прячет карточку
      `dossierRebuildEnabled=false` — S10.22-6 CLOSED; новый старт после `interrupted` — S10.22-5 UI CLOSED)
- [x] .env.example (новые env-рубильники `SYSTEM2_*`/`TELEGRAM_SEND_GUARD_ENABLED`/`DOSSIER_REBUILD_*` — S10.22-7 CLOSED)
- [x] tests/* (целевые 187+339+70+88 passed / 0 failed; JS-гейты `JS-UNIT-OK`/`DOSSIER-REBUILD-UNIT-OK`/help OK)
- **СВОДКА RE-AUDIT: Critical 0 / High 0 / Medium 0 (open). Low 0, Info 1 (S10.22-4b, не блокер).**
  Валидатор: catalogue 439/92/20 (Δ=0), v12, канон v4 байт-в-байт, `git diff --check` exit 0.
  Вердикт: **раунд передаётся на Merge/деплой**; обязательных возвратов @Builder нет.
  Отчёт: `round1022_scanner_audit.md` §«Re-audit после пост-скан фиксов».

## Round 10.21 scan + re-audit (Step 6 @Scanner, 18.09.2026) — all scanned/closed (diff-based, HEAD 21cd54c + worktree)
- [x] services/grounding_validator.py (F2: anchors только из доверенных источников — S10.21-5 CLOSED; дата-теги без
      `fact:ID` проверяются — S10.21-4 CLOSED; fail-open, no ReDoS)
- [x] services/factcheck_service.py + services/tool_loop.py (F2: `tool_context` до cleanup; `trusted_parts` =
      rag/results/chat_context/tool_context, `<claim>`/`<user_hint>` исключены — S10.21-5 CLOSED)
- [x] services/dossier_prompts.py + services/lore_worker.py (F1: слои A/B, фильтр, дедуп, бюджет; пустой `memes` Слоя Б
      больше не перетирается мемами А — S10.21-7 CLOSED)
- [x] services/database.py (`get/upsert_generated_dossier`; `initialize_readonly` (`mode=ro`, без DDL/WAL/создания файла) —
      S10.21-6 CLOSED; схема v12, Info S10.21-11 открыт)
- [x] services/memory_rebuild.py (F5: allowlist+`RAW_HISTORY_TABLES`+`_guarded_delete`; бэкап→JSONL→сверка→DELETE;
      `_chat_roster` union nodes+portraits+overrides + `roster_incomplete`/`roster_size` — S10.21-2 CLOSED;
      `belief_source` исключает опоры убеждений — S10.21-3 CLOSED; Info S10.21-13 открыт)
- [x] manage.py (F4/F5 CLI `memory`; guard целевого чата; `audit` через `initialize_readonly` — S10.21-6 CLOSED)
- [x] services/memory_maintenance.py (F4 consolidate fail-closed; per-chat кап `deep_sleep_max_paradigms_per_run` +
      `deep_sleep_top_k` — S10.21-1 CLOSED; Low S10.21-8 парадигмы без vec — ОТКРЫТО, вне скоупа фиксов)
- [x] services/config_migrations.py + services/prompt_migrations.py + `*_prompts.py` (F3/F4: PREV_*_R1021 + ROLLBACK,
      идемпотентные миграции порогов, docs-канон синхронен — чисто)
- [x] services/prompt_style_blocks.py (F3: блоки A/B, R46-4 без «уже проверял» — чисто)
- [x] config/settings.py + bot.py + .env.example (env-only ClassVar, порядок роутеров не тронут, Δ каталога = 0 — чисто)
- [x] web/app.js + web/index.html + web/api/chat_lore.py + tests/js/round1021_ui_audit_test.js (F6: `_syntheticGroup` в
      methods, `positionScopePanel`; регресс зелёный — чисто)
- [x] tools/ui_audit_round1021.py + UI_AUDIT_REPORT.md + tools/_ui_audit_raw.json (F6: реальный Playwright-рендер;
      S10.21-9 CLOSED — `tools/_ui_audit_shots/` и `tools/_ui_audit_raw.json` в `.gitignore`, `git check-ignore -v` OK)
- [x] tests/test_*_round1021.py + тесты канонов/промптов — 217 целевых passed; фиксы S10.21-2/-3/-6/-7 подтверждены
      7 ad-hoc пробами @Scanner (своих регресс-тестов у этих 4 веток нет — новый Low N10.21-1)
- **СВОДКА RE-AUDIT: Critical 0 / High 0 / Medium 0 (open).** Low: S10.21-8 (вне скоупа) + N10.21-1 (тест-покрытие) +
  N10.21-2 (бинарный `roster_incomplete`). Info 4. Вердикт: **раунд передаётся на Merge/деплой**; обязательных
  возвратов @Builder нет. Отчёт: `round1021_scanner_audit.md` §«Re-audit после пост-скан фиксов».

## Round 10.20 scan + re-audit (T-1915, 2026-09-16) — all scanned/closed (diff-based, HEAD 2f3e1f0 + worktree)
- [x] web/index.html + web/app.js (S10.20-1 High CLOSED: `<sticky-save>` в ветке `currentTabIsConfig`
      (:704) + модалка «Модулей» (:967) + «Доступы» (:1549) + футер досье (:2694); S10.20-6 CLOSED:
      `saveModalEdits` не снапшотит при ошибках, `stickyFailed`; S10.20-10 CLOSED: длинная история → plain)
- [x] services/tool_router.py (S10.20-2 `resolve_lore_compiler_flag`; S10.20-3 `_dig_json_payload`
      с валидным JSON; S10.20-4 `lore_verbatim_instruction`/`strip_lore_html`)
- [x] services/factcheck_service.py (S10.20-2 per-chat флаг; S10.20-4 без «ДОСЛОВНО» + strip HTML)
- [x] services/smartmodule_utils.py (S10.20-4/10/11: `strip_lore_html`, комментарий sanitize)
- [x] services/lore_compiler_service.py (S10.20-5 `last_ts` по включённым диалогам; S10.20-8/M1
      header-safe `_trim_pairs`; S10.20-14 tz `_date`; S10.20-15 `_empty_dense`)
- [x] services/status_service.py (S10.20-7 per-chat cap приоритетнее acct + `context.source`)
- [x] services/database.py (M2 докстринг `_LORE_NODE_SCAN_LIMIT`; M3 `dossier_feed` пул `limit*20`;
      S10.20-13 `initialize_existing` валидация; S10.20-16 докстринг)
- [x] services/canonical_context.py (S10.20-9 паттерны 6-кортежа `direct_rag`/`legacy_rag`)
- [x] tests/test_scanner_fixes_round1020.py + tests/test_webapp_round1020_ui.py +
      tests/js/round1020_ui_test.js (панель в каждой ветке, S10.20-6)
- **Принято обоснованно (не закрываем):** S10.20-12 (Time Injection/prompt-cache — ADR-1020-3),
  S10.20-17 (RBAC-паритет `persona_dossier_overrides` — вне скоупа).
- **СВОДКА: Critical 0 / High 0 / Medium 0 / Low 0 (open) / Info 5.** Новых находок нет.
  Валидатор: pytest **6546 passed / 0 failed** (87.49 s); `node --check web/app.js` OK;
  `routing_test.js`/`round1020_ui_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` exit 0. **ВЕРДИКТ: «нет Critical/High»** → @Orchestrator, шаг 7.

## Round 10.18 БАТЧ 4 (финал эпика) scan (2026-09-15) — all scanned (diff-based: F5 `metafact-penalty-extractor-prompt` + F6 `role-matrix-settings-actualization`, HEAD 118a03c + worktree)
- [x] services/graph_stoplist.py (F5: `METAFACT_PENALTY_IMPORTANCE=1`, `is_metafact_stopword`; списки centers≠penalty — чисто)
- [x] services/database.py (F5: `insert_graph_fact` += `subject/object` + централизованный срез `imp=min(imp,1)`;
      `f.importance` в SELECT `search_graph_facts_fts`/`get_graph_fact_records`. Находка: S10.18-35)
- [x] services/summary_memory.py (F5: `PREV_FACT_EXTRACT_PROMPT` байт-в-байт + аддитивный канон (AST-проба);
      `_importance_factor` в FTS+KNN ветках `_search_graph_facts` (взаимоисключающие → нет двойного применения); S10.18-37)
- [x] services/param_catalog.py (F6: `NAV_*`/`NAV_TITLES`/`NAV_ORDER`/`TAB_NAV`/`tab_nav`, `CONFIG_TAB_TITLES[PERMsoc]`=«PERMsoc»; Δ=0)
- [x] web/api/access.py (`param_permissions_list` += `nav/nav_title/nav_order`, R16; 403/форма прав не изменены)
- [x] web/app.js + web/index.html (F6: `matrixSections` по nav, `NAV_GROUP_ORDER/TITLES` — parity-тест, вложенный шаблон, «Прочее»; S10.18-36)
- [x] tests/test_metafact_penalty_round1018.py (новый: канон-байты, стоп-листы, срез (обе стороны/нормализация/явный importance),
      memorise-путь, поведенческий гейт Сна, RAG FTS/KNN/золотые, границы множителя) + test_frontend_tab_mapping/test_webapp_api
- **Открыто (Батч 4):**
  - [ ] **S10.18-35 [low, new]** F5-срез покрывает только memorise-путь; эпи-мерж (`memory_maintenance.py:250-258`)
        ре-вычисляет importance от origin → слитый мета-факт теряет пенальти (imp 1→4) → прокинуть пенальти в merge.
  - Info: S10.18-36 (spec §3.1 «3 nav» vs фактические 4 группы с «Прочее» — синхронизировать с ADR D4),
    S10.18-37 (F5-множитель меняет RAG-порядок всех чатов — живая проверка), S10.18-38 (сводка остатков эпика).
- **СВОДКА ЭПИКА 10.18 (F1–F7, батчи 1–4): Critical 0 / High 0 / Medium 1 (S10.18-30) / Low 2 (S10.18-29, -35) / Info 11.**
  **Вердикт: эпик готов к @Reviewer/@PM (T-1749/T-1757) → Merge/архивация → деплой @DevOps**; до деплоя желательно
  закрыть S10.18-30 (перф ×2-фазы `graph_snapshot`).
- Валидатор @Scanner (независимо): pytest **6137 passed / 0 failed** (67.8 c); `node --check web/app.js` OK;
  `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19;
  SQLite v10; nav-интроспекция 161/180/65/5 = 411.

## Round 10.18 БАТЧ 3 scan (2026-09-15) — all scanned (diff-based: F3 `graph-density-scoring-stoplist` + F4 `graph-physics-stabilization`, HEAD 118a03c + worktree)
- [x] services/database.py (F3: миграция v10 `_migrate_edges_fact_id_v10` (guard/индекс вне `_SCHEMA_SQL`/user_version=10),
      `graph_snapshot` (score=Σ importance, bound-pool, STOP_LIST центров, ×2, cap 800/2400, сироты/truncated),
      `_belief_participation_blob`, `upsert_edge(fact_id, commit)`, `insert_graph_fact(commit)`. Находки: S10.18-30/-32/-33)
- [x] services/graph_stoplist.py (новый: centers/penalty списки, normalize_token/predicates — чисто; S10.18-31)
- [x] services/summary_memory.py (атомарность fact+edge: commit=False ×2 + единый commit + rollback; cron-путь NULL)
- [x] web/api/memory_agi.py (лимиты 800/2400/150; `limits` аддитивно; manual-маркеры/`_badge_active_until`; S10.18-29)
- [x] web/app.js (F4: physics 150 + `once`-авто-отключение, guard по тождеству, reducedMotion; S10.18-22/-26 закрыты)
- [x] tests/test_graph_scoring_round1018.py (новый: миграция/fresh/legacy/FTS, скоринг/degree, STOP_LIST, ×2/substring/multiword,
      fact_id-путь/COALESCE/атомарность, плотность 500–800, константы) + 11 обновлённых тестов (user_version 9→10)
- **Закрыто в Батче 3:** S10.18-21 [medium] (предгейт `_deep_tick` + `has_any_override` удалены), S10.18-22 [medium]
  (restore-polling только на «Статусе» + `closeModule`), S10.18-23 [low] (manual-маркеры воркера), S10.18-24 [low]
  (`_FALLBACK_MIN_IMPORTANCE_SUM=6`), S10.18-25 [low] (`0` = «без лимита»), S10.18-26 [info] (ретраи снимаются).
- **Открыто (Батч 3):**
  - [ ] **S10.18-30 [medium, new]** перф ×2-фазы `graph_snapshot` (`database.py:3796-3833`): замер — полный ≈238 мс
        (15k рёбер/200 beliefs), SQL ≈59 мс, ×2-цикл ≈176 мс; линейно растёт с belief-блобом (≈2.3 с при 4000, ≈6.5 с при 10 000);
        выполняется в event loop на каждый `/api/memory/graph` (15с / 5с при manual) → заменить на O(1)-множество токенов/кэш.
  - [ ] **S10.18-29 [low, new]** `run_once(deep=False)` не ставит `_manual_deep_until` → `deep_sleep.manual=False` и
        `active_until=None` во время deep-фазы manual-каскада вне окна; TTL 900с не связан с локами.
  - Info (open): S10.18-31 (варианты STOP_LIST с дефисом/пробелом), S10.18-32 (self-loop ×2 в degree/score),
    S10.18-33 (`upsert_edge` при отсутствии узла → факт без ребра), S10.18-34 (S10.18-18/-19/-20 из Батча 1),
    плюс S10.18-12 (nostalgia backlog T-1764), S10.18-13 (SSH-фрагмент, вне батча).
  - **ВЕРДИКТ: БАТЧ 4 (F5 экстрактор + F6 матрица ролей) РАЗРЕШЁН** (0 Critical / 0 High).
- Валидатор @Scanner (независимо): pytest **6104 passed / 0 failed** (75.4 c); `node --check web/app.js` OK;
  `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19;
  SQLite v10 (миграция проверена пробой fresh/legacy/idempotent).

## Round 10.18 БАТЧ 2 scan (2026-09-15) — all scanned (diff-based: F2 `sleep-manual-cascade-badges`, HEAD 118a03c + worktree)
- [x] services/dream_worker.py (F2: manual-обход gate (`gate_override`)/бюджетов (`budget_override`)/near-limit/window;
      `_dream_budget_ok`/`_deep_budget_ok(manual=True)` — 4 независимых `consume`, verdict игнорируется; каскад
      `_maybe_deep_after_sleep(manual, only_chat)` + `_MANUAL_DEEP_CASCADE_MAX=1`; `_deep_result`; `_deep_fixed_possible`;
      `_run_persona_traits_once` reason-коды. Находки: S10.18-21/-23/-24/-25/-27)
- [x] services/config_migrations.py (новый; `migrate_dream_thresholds`: идемпотентность/кастом/PG down — чисто)
- [x] config/settings.py (пороги 2/8/2/10/60/300000/10; DREAM/DEEP_ENABLED оставлены False — S10.18-28)
- [x] bot.py (вызов `migrate_dream_thresholds` после `migrate_prompt_canons`; маркер BetterStack без `last4`)
- [x] web/api/memory_agi.py (`_badge_active_until`; `dream/deep_sleep.manual`; `effective`/`source` — S10.18-23)
- [x] web/app.js (S10.17-2 закрыт; оптимистичная `active`; `_retryCognition`; `restartCognitionPolling`/restore — S10.18-22/-26)
- [x] services/param_catalog.py (тексты порогов/DREAM_ENABLED; Δ=0) + services/feature_gates.py (`_master_fallback_default` — S10.18-15 closed)
- [x] services/chat_params.py (`has_any_override`/`note_overrides`/`_override_keys_seen` — S10.18-21)
- [x] tests/* (новый `test_sleep_manual_cascade_round1018.py` + deep_sleep/dream_worker/webapp1015/smoke1016/fallback1015/persona_traits/chat_params/js-routing)
- **Закрыто в Батче 2:** S10.18-15 [medium] (`settings.DREAM_ENABLED`-дефолт), S10.18-16 [low] (мёртвые sync-хелперы), S10.18-17 [low] (`_deep_fixed_possible`).
- **Открыто (Батч 2):**
  - [ ] **S10.18-21 [medium, new]** предгейт `_deep_tick` (`dream_worker.py:1282-1333`, `chat_params.py:150-183`) видит
        только прогретый кэш → per-chat `trigger='fixed'` молча пропускается на cold-start/после NOTIFY (откат R10.18-2).
  - [ ] **S10.18-22 [medium, new]** `_restoreCognitionPolling` (`app.js:5440-5463`, `closeModule:2371-2373`) стартует 15с
        без гейта `activeTab` и не снимается при закрытии модалки → polling вне «Статуса» бессрочно (JS-тест фиксирует).
  - [ ] **S10.18-23 [low, new]** `manual = running && !in_window` (`memory_agi.py:590-601`) — авто-тик вне окна помечается
        «ручным»; `active_until` 900с для него.
  - [ ] **S10.18-24 [low, new]** дефолты 2/8 == fallback-константы (`dream_worker.py:168-170`) → F3-fallback no-op.
  - [ ] **S10.18-25 [low, new]** `0` как per-chat лимит противоречив (`dream_worker.py:723-733`).
  - Info: S10.18-26 (`_retryCognition` без очистки), S10.18-27 (manual deep без кап/cooldown — принято),
    S10.18-28 (`DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` False; T-1713/T-1724/T-1725/T-1726/T-1772 открыты);
    плюс из Батча 1: S10.18-12 (nostalgia backlog T-1764), S10.18-13 (SSH-фрагмент R10.18-12, вне батча),
    S10.18-18…-20.
  - **ВЕРДИКТ: БАТЧ 3 (F3 граф + миграция v10) РАЗРЕШЁН** (0 Critical / 0 High).
- Валидатор @Scanner (независимо): pytest **6083 passed / 0 failed** (69.6 c); `node --check web/app.js` OK;
  `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19.

## Round 10.18 scan (2026-09-15, БАТЧ 1/3) — all scanned (diff-based: F7 settings-worker-sync + F1 betterstack-us-region-401, HEAD 118a03c + worktree)
- [x] services/worker_settings.py (F7: `resolve_setting`/`_with_source`/`_cached`/`setting_source`; сентинел `hot.get(key,_SENTINEL)`
      проходит `_coerce` без изменений — интроспекция `_cast_to_type`; каст == `chat_params._resolve_from_root`; fail-open)
- [x] services/dream_worker.py (F7: `_key_for`/`_window_open_for`/`_daily_limit_for`/`_budget_reason_for`; `start()` регистрирует
      джобы ВСЕГДА; `_maybe_deep_after_sleep(…, manual)`; gate-fallback per-chat. Находки: S10.18-1…-5)
- [x] services/feature_gates.py (F7: `_explicit_flag_value` + `fallback`; без fallback поведение прежних вызовов не изменилось — grep 5 callers)
- [x] services/chat_params.py (`invalidate_chat_from_notify` — fail-open) + services/chat_params_notify.py (LISTEN на отдельном
      `asyncpg.connect` + backoff + закрытие conn; `stop()` не вызывается — S10.18-7; untracked tasks — S10.18-11)
- [x] services/betterstack_handler.py (F1: host обязателен, `DEFAULT_HOST=""`, `extract_sentry_public_key`,
      `token_equals_sentry_public_key`, `_HINT_401`; S10.18-8 доки)
- [x] bot.py (F1 attach/skip-маркеры + last4; F7 `_start_chat_params_listener` + cancel на shutdown; stale-коммент :565)
- [x] services/param_catalog.py (`BETTERSTACK_HOST` в `_INFRA_ENV_ONLY`, REGISTRY 436)
- [x] web/api/memory_agi.py (chat_id-резолв + аддитивный `source`; S10.18-3 kill-switch не учитывается)
- [x] web/index.html (hint-ссылка на `#/ai/memory` — маршрут существует, TAB_RULES не расширен)
- [x] scripts/betterstack_host_token_probe.py + tests/test_betterstack_probe.py (матrix host×token, dry-run, R17-маскирование)
- [x] tests/* (settings_worker_sync_round1018, dream_worker, betterstack_handler, monitoring_smoke, param_catalog, 12 пин-тестов каталога)
- [x] plans/* (spec/adr/tasks F1+F7, backlog 10.18, ARCHITECTURE/README — drift S10.18-8/-9)
- **ЗАКРЫТО @Builder (10.18, Батч 1):**
  - [x] **S10.18-1 [high]** per-chat суточные лимиты Сна vs глобальные счётчики — `count_dream_log`/`sum_dream_log_tokens`
        получили `chat_id`; `_process_chat` считает расход по чату; регресс-тест `TestPerChatBudget`.
  - [x] **S10.18-2 [medium]** per-chat `deep_sleep_trigger`/`hour` в `_deep_tick` (+`_deep_candidate_chat_ids`); тесты.
  - [x] **S10.18-3 [medium]** статусы используют тот же fallback, что воркер (`feature_gates.master_fallback`); `cognition`
        отдаёт `dream.effective`, `active` по нему; тесты `TestStatusMatchesWorkerBehavior`.
  - [x] **S10.18-4 [medium]** decay гейтится глобальным master Сна (`TestDecayGatedByDreamMaster`).
  - [x] **S10.18-5 [medium]** manual-каскад по целевому чату + кап (`TestManualDeepCascade`).
  - [x] **S10.18-6 [medium]** нет `BETTERSTACK_HOST` → ERROR «логи НЕ отправляются»; тесты обновлены.
  - [x] S10.18-7…-11 [low] — `stop()` вызывается в `on_shutdown`; сильные ссылки на `create_task` в `_on_notify`; stale-доки
        (bot.py/ARCHITECTURE/README) синхронизированы; спека F1 §9 Q4 ↔ T-1706 и docstring `mask`; изоляция reload
        `config.settings` в тесте (restore `settings_mod.settings` + pop `bot` в `finally`).
  - [x] Гигиена: `test_tool_download_quality_round1017` ищет ADR в `plans/archive/`.
  - Info: S10.18-12 (Nostalgia backlog + задача есть), S10.18-13 (SSH-фрагмент, R10.18-12 — вне батча), S10.18-14 (инварианты целы).
- **⏱ Итерация 2 @Scanner (повторный аудит, 15.09.2026) — CLOSED S10.18-1…-11, -14 (11 закрыто); OPEN:**
  - [x] **S10.18-15 [medium, new]** `services/feature_gates.py:55-72` — `master_fallback` default `False` ≠
        `settings.DREAM_ENABLED`: env `DREAM_ENABLED=true` + нет DB-ключа `memory.dream_enabled` → воркер ON, статус
        гейтов/`cognition.effective` OFF (воспроизведено скриптом). Фикс — default из `settings`.
        **CLOSED (fix @Builder, итерация 3):** `_master_fallback_default("dream")=settings.DREAM_ENABLED`; тесты
        `test_master_fallback_default_matches_worker_env_on/_off`.
  - [x] **S10.18-16 [low, new]** `services/dream_worker.py:753,766,784-793` — мёртвые sync-хелперы
        `_window_open`/`_daily_limit`/`_budget_reason` (0 вызовов в проде и тестах) → удалить/deprecate.
        **CLOSED (fix @Builder, итерация 3):** удалены; `_key()` сохранён.
  - [x] **S10.18-17 [low, new]** `services/dream_worker.py:1205-1230` — `_deep_tick` делает `get_dream_candidate_chats`
        + N per-chat resolve каждый тик (60 мин) даже без `fixed`-чатов (раньше ранний return без I/O) → дешёвый предгейт.
        **CLOSED (fix @Builder, итерация 3):** `_deep_fixed_possible()` + `ChatParamsCache.has_any_override`; тесты
        `test_deep_tick_skips_candidate_sql_when_disabled` / `test_deep_tick_proceeds_when_per_chat_override`.
  - Info (open): S10.18-12 (Nostalgia/backlog T-1764), S10.18-13 (SSH-фрагмент, R10.18-12, вне батча),
    S10.18-18 (`?deep=1` без капа — осознанно), S10.18-19 (`tokens_per_day` без фильтра `kind` — pre-existing),
    S10.18-20 (`previous` kill-switch = effective — семантика поля).
  - **ВЕРДИКТ итерации 2: БАТЧ 2 (F2) РАЗРЕШЁН** (0 Critical / 0 High).
- Валидатор @Builder (итерация 3): pytest **6057 passed / 0 failed**; `node --check web/app.js` clean; `JS-UNIT-OK`;
  `VUE-MOUNT-OK`; `git diff --check` clean; каталог-интроспекция 436/406/411/90/88/19; SQLite v9.
- Валидатор @Builder (итерация 1): pytest **6052 passed / 0 failed**; `node --check web/app.js` clean; `JS-UNIT-OK`; `VUE-MOUNT-OK`;
  `git diff --check` clean; каталог-интроспекция 436/406/411/90/88/19; SQLite v9; `logtail`-импортов нет.
- Валидатор @Scanner (независимо): pytest **6052 passed / 0 failed** (75.6 c); целевые 10.18 — 121 passed;
  `git ls-files` подтверждает трекинг архивного `spec.md` с фрагментом пароля (S10.18-13).

## Round 10.17 scan (2026-09-14) — all scanned (diff-based, 5 фич F1–F5, HEAD 772f192 + worktree)
- [x] services/tool_router.py (F2: `_download_media` probe→меню→`needs_quality`; `_download_now` direct/явное
      качество/bounded fallback; `store/peek/pop_tool_download_pending` TTL 600; `_quality_arg`; R17-логи без URL)
- [x] handlers/video_download.py (F2: callback `tdq:` c валидацией высоты до consume, busy без потери pending,
      chat_action; Fast-Track-меню делегировано в `services/media_send`; F1 host-only лог в `handlers/menu.py`)
- [x] services/media_send.py (F2: единый `QUALITY_ROW_SIZE`/`build_quality_keyboard`/`quality_menu_text`/`send_quality_menu`)
- [x] services/tool_schemas.py (F2: опциональный `quality` enum `QUALITY_ENUM`)
- [x] tools/video_downloader.py (F2: `QUALITY_ENUM` = `("max",)+_ALLOWED_HEIGHTS`)
- [x] web/app.py (F1: `_startup_diag` host-only; HEAD `/web/`,`/index.html`; GET/HEAD `/healthz`)
- [x] web/app.js (F3: `fmtCountdown`; `dreamPhaseBadge`/`deepPhaseBadge` — остаток/до, ветка «выключен» удалена)
- [x] web/api/avatars.py (F5: `_log_bot_api_failure` + 6 сайтов — ожидаемое DEBUG, транзиент WARNING без кэша,
      generic WARNING с трейсом)
- [x] tests/* (F1 `test_webapp_dns_round1017`, F2 `test_tool_download_quality_round1017`,
      F3 `test_webapp_round1017_sleep` + JS, F5 `test_avatars_round1017`; обновлены регресс-маркеры 1015/1016)
- [x] plans/README/ARCHITECTURE/MEMORY/backlog/archive (F4 CANCELLED, brotli-WONTFIX, SUPERSEDE ADR-1016-1)
- **Открыто (не блокеры шага 7; 0 Critical / 0 High / 1 Medium / 2 Low / 3 Info):**
  - [ ] **S10.17-1 [medium]** `plans/archive/security-rotation-finalize-round1016/spec.md:3,72,79-83` —
        архивная спека без CANCELLED-баннера, §8 «ротация обязательна в любом случае» (docs-only).
  - [ ] **S10.17-2 [low]** `web/app.js:1216-1247` — `cognition==null` → «Сон через —» vs spec §3.4 «—».
  - [ ] **S10.17-3 [low]** доки-счётчики: `tool-download-quality/spec.md:245`, `sleep-badge-countdown/spec.md:125` (5951/5985).
  - Info: S10.17-4 (tool env-preflight), S10.17-5 (callback без hot-гейта), S10.17-6 (`/healthz` version — принято).
- Валидатор: pytest **6007 passed**/0 fail (79.62 c); `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`;
  `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0. Инварианты: R17/R16, роутеры `bot.py`,
  `media/`/`.env`, каталог 435/406/411/90/88/19, tool-set 7, лимиты 4/2, PREV/`PROMPT_MIGRATIONS`, SQLite v9 — целы.

## Round 10.16 scan (2026-09-14) — all scanned (diff-based, 5 фич F1–F5)
- [x] tools/video_downloader.py (F1: `DownloadError.reason`+`default_reason` подклассов,
      `download(url, quality=None)`, `_normalize_quality` None/auto/best/max/direct→`max`+диапазон 144…4320,
      `download_env_summary`/`log_download_env_once`, R17-лог-сайты без URL)
- [x] config/settings.py (F1: `get_ytdlp_pot_provider` — единый POT-источник, env-only, каталог-Δ=0)
- [x] handlers/video_download.py (F1: горячий гейт `flags.download_enabled`, `download_available`,
      `_download_without_menu` bounded fallback, `_probe_error_phrase`/`_fallback_phrases`, reason-логи)
- [x] services/tool_router.py (F1: `download(url)` без `"direct"`, DownloadError→`status:"error"` R17)
- [x] bot.py (F1/F3: только снятие startup-гейта вокруг 4e — порядок роутеров не изменён)
- [x] handlers/direct_chat.py (F3: `_functional_module_active` + `download_available`)
- [x] services/info_service.py + services/config_cache.py + handlers/info.py + web/api/routes.py + web/app.js
      (F2: canon_version/normalize_canon/KNOWN_INFO_SNAPSHOTS, force-reset+prev_html, PG-only save_text,
      drift-preserve, UI resetInfoCanon)
- [x] services/database.py + dream_worker.py + summary_memory.py + command_prefix.py
      (F3 FIX: S10.13-6b archived_beliefs-фильтр, S10.13-13 единый `parse_belief_meta`,
      R10.15-10 `split_prefix_anywhere(url_before)`)
- [x] handlers/youtube.py + handlers/web.py (F3: `_has_video_target`/link-first; residual R17-лог YouTube)
- [x] web/index.html + web/static/app.css + telegram-init.js + vendor/* + tailwind.config.js + web/app.py
      (F4: self-host, CSP `unsafe-eval`, `/static/app.css` с `?v=`)
- [x] plans/features/*-round1016/ + plans/reports/round10.16_*.md + ssh-rotation-checklist.md (F5: docs/scan)
- [x] tests/* (new: test_download_round1016, test_guide_delivery_round1016, test_smoke_round1016_* ×7,
      tests/js/vue_mount_test.js; обновлены маркерные/каталог/JS)
- **Итерация 2 (после фиксов @Builder) — закрыто:**
  - [x] **S10.16-1 [high→closed]** R17: youtube-лог-сайты — только `error=<Class> reason=<reason>`
        (`handlers/youtube.py:697-699,705-707`); caplog-тест `test_download_round1016.py:711-748` покрывает путь.
  - [x] **S10.16-2 [medium→closed]** бэкап канона: `config_cache.py:292,317-323` + `info_service.py:285-291`.
  - [x] **S10.16-3 [low→closed]** `download_available()` задокументирован (`handlers/video_download.py:126-136`).
  - [x] **S10.16-4 [low→closed]** touch после успешного старта (`video_download.py:462-468`).
  - [x] **S10.16-5 [low→closed]** мёртвый `probe_unavailable` удалён (`video_download.py:415-426`).
  - [x] **S10.16-6 [low→closed]** `is_platform_url` публичный (`tools/video_downloader.py:235`).
  - [x] **S10.16-7 [low→closed]** native media — только класс (`video_download.py:698-701`).
  - [x] **S10.16-8 [low→closed]** аватар same-origin прокси (`web/app.js:1564-1590`), CSP OK.
  - [ ] **S10.16-9 [low, latent]** 4 raise-сайта ещё интерполируют `{exc}` (`video_downloader.py:767,772,899,904`),
        `:835` — тело cobalt до 500 символов; лог-пути их не печатают (утечки нет) — hardening.
- Валидатор итерации 2: pytest **5936 passed**/0 fail (69.4 c), `node --check web/app.js` OK, `routing_test.js`
  JS-UNIT-OK, `vue_mount_test.js` VUE-MOUNT-OK, `git diff --check` OK. Инварианты: R17/R16, роутеры `bot.py`,
  `media/`/`.env`, каталог 435/406/411/90/88/19, tool-set 7, PREV/`PROMPT_MIGRATIONS`, SQLite v9 — целы.
  **Открыто: 0 Critical / 0 High / 0 Medium / 1 Low (latent).**

## Round 10.15 scan (2026-09-14) — all scanned (diff-based, 9 фич F1–F9)
- [x] services/command_registry.py (NEW: канон 17 + `чекап`/`фактчек` bare, `_HEAD`/`_TAIL` word-boundaries,
      `matches`/`group_of`/`matches_group`/`has_trigger_word`)
- [x] services/command_prefix.py (NEW: `active_name`/`command_prefix_tokens`/`split_prefix`/`name_mentioned`/
      `functional_group`/`is_functional_command`; префикс якорён к `^`)
- [x] services/media_send.py (NEW: общий `send_media`, фолбэк video→document, R17-лог)
- [x] handlers/search.py / youtube.py / web.py / checkup.py / video_download.py (F6: снятие префикса,
      триггеры из реестра, консьюм без цели `COMMAND_NO_TARGET_PHRASES`)
- [x] handlers/direct_chat.py (F6: `name_mentioned`, отключение ботвордов при имени, `_FUNCTIONAL_FLAGS`/
      `_functional_module_active`, yield UNHANDLED, имя в `_parse_memory_command`)
- [x] bot.py (F8 DI: `youtube_service`/`checkup_service`/`_shared_video_downloader` → `ToolDeps(video/downloader/
      db/health)`; порядок роутеров не тронут)
- [x] services/tool_schemas.py (F8/F9: +`summarize_video`/`download_media`/`get_bot_health`/`get_recent_history`, итого 7)
- [x] services/tool_router.py (F8: `_summarize_video`/`_download_media` (успех только после `send_media`)/
      `_get_bot_health`; F9: `_get_recent_history` depth/query + `_history_lines`; `ToolHealthDeps`)
- [x] services/direct_chat_service.py (F8: `ToolContext(bot/reply_to_message_id/user_id)`)
- [x] services/database.py (F1: `graph_snapshot` CTE Degree Centrality + 1-hop + сироты + оба конца рёбер)
- [x] web/api/memory_agi.py (F1 `GRAPH_SEED_NODES=50`; F5 `_in_hour_window`/`_local_hour` + `active`/`active_until`,
      H1-гейт `enabled`)
- [x] web/app.js / web/index.html (F2 barnesHut + поиск по графу; F5 релокация метрик, `intel-header`, бейджи
      «через/до»/«выключен», удалён `loadCognitionStats`)
- [x] services/dream_worker.py (F3 `_sleep_fallback_active` 2/8, детект раз на тик, `[Sleep]` WARNING/INFO)
- [x] services/nostalgia_prompts.py / nostalgia_worker.py / config/settings.py / param_catalog.py (F4: окно 10,
      лор/мемы капы 600/10/120, PREV-слепок, промпт-ревамп)
- [x] services/info_service.py / config_cache.py / info_text.md / plans/docs/intelligence_user_guide.md (F7 канон +
      идемпотентная миграция по `PREV_DEFAULT_INFO_TEXT`)
- [x] tests/* (8 новых файлов + обновления), tests/conftest.py (сброс persona-name кэша)
- [x] plans/features/*-round1015/ (9 спек + ADR-1015-1/-2/-3 + tasks), plans/reports/round10.15_scanner_audit.md
### Round 10.15 — повторный аудит (итерация 2, 2026-09-14)
- [x] **R10.15-1 [medium] closed** — `command_prefix.split_prefix_anywhere():61-77`; link-first в
      `youtube.py:206-215`/`web.py:97-106` (URL строго до обращения + `matches_group` остатка); тесты
      `test_command_registry_round1015.py:153-161,225-242`.
- [x] **R10.15-2 [medium] closed** — `tool_router.py:623` гейт `flags.checkup_enabled` до `fetch()`/`checkup()`
      (тест `test_tool_calling_round1015.py:438-455`).
- [x] **R10.15-3 [medium] closed** — обычная речь без URL → `UNHANDLED` (`youtube.py:200-205`, `web.py:91-96`;
      тесты `:249-279`); residual R10.15-11.
- [x] **R10.15-5 [low] closed** — `memory_agi.py:497-501` независимый `deep_active_until`.
- [x] **R10.15-6 [low] closed** — `tool_router.py:657-661` fallback `ctx.query` (тест
      `test_recent_history_tool_round1015.py:134-148`).
- [x] **R10.15-7 [low] closed** — мёртвые `is_functional_command`/`command_registry.matches` удалены (grep 0).
- [x] **R10.15-8 [low] closed** — `database.py:3651-3652` seed join `nodes`+`nwhere` (тест
      `test_webapp_round1015_graph.py:105-118`).
- [x] **R10.15-9 [low] closed** — `tool_router.py:576-591` общий кулдаун 4e через `get_download_cooldown`
      (`handlers/video_download.py:116-122`); тесты `test_tool_calling_round1015.py:289-335`.
- **Открыто (не блокеры шага 7; 0 Critical / 0 High / 0 Medium / 3 Low / 3 Info):**
  - [ ] **R10.15-4 [low]** F6 M2-остаток: yield по hot-флагу vs startup-регистрация 4e (`direct_chat.py:461-463`,
        `bot.py:747-753`) — осознанный follow-up.
  - [ ] **R10.15-10 [low]** link-first привязан к первому вхождению имени (`command_prefix.py:71-77`;
        `youtube.py:206-215`; `web.py:97-106`) — узкий false-negative.
  - [ ] **R10.15-11 [low]** «триггер anywhere + любой http-URL» консьюмит обычную речь с не-media ссылкой
        (`youtube.py:203`; `web.py:94`) — residual R10.15-3.
  - Info: R17-долг `plans/current_task.md:62-65` (вне диффа).
- Валидатор итерации 2: pytest **5774 passed**/0 fail, `node --check web/app.js` clean, `routing_test.js`
  JS-UNIT-OK, `git diff --check` OK. Инварианты: R17/R16, роутеры `bot.py`, `media/`/`.env`, каталог
  435/406/411/90/88/19, tool-set 7, PREV байт-идентичен, `PROMPT_MIGRATIONS` не тронут — целы.

## Round 10.14 scan (2026-09-13) — all scanned (diff-based, 8 фич F1–F8)
- [x] services/database.py (F1 SQLite v8→v9: `_migrate_self_origin_v9` rebuild 16 колонок/id 1:1,
      guard + безусловный `user_version=9`, 5 индексов, origin-исключения self в list_new_confirmed/
      golden/live/dup/graph_stats, `include_self` в `search_graph_facts_fts`; `rule_importance` self=2)
- [x] services/bot_persona.py (NEW: scope-резолв per-chat→global→empty, prompt-блок + `_NO_AI_DISCLOSURE_BLOCK`,
      UPSERT/optimistic `updated_at`/`PersonaConflict`, traits cap/дедуп/FIFO, persona_state-метрики, name-cache)
- [x] services/self_reflection.py (NEW: LLM-экстрактор сути, роль `reflection`→фоллбэк main, fail-safe '', метрики)
- [x] services/summary_memory.py (`_origin_weight(bot_weight=…)`, `memorize_self_reply`, `include_self`
      через `_search/_knn/_vec*`+`_filter_vec_rows`, метка `[Источник: Я сам (Бот)]`, `_SELF_ECHO_INSTRUCTION`)
- [x] services/direct_chat_service.py (persona-хвост system prompt per-chat; self-aware ветка
      `_memorize_in_background` (query=bot_direct_reply + essence=bot_self_reply); анти-эхо ДО cap;
      `_reassign_fact_owners` изолирует self по origin; `include_self=True` только direct-RAG)
- [x] services/dream_worker.py / dream_prompts.py (F2 `_run_persona_traits_once` + `PERSONA_EVOLUTION_PROMPT`/
      `build_persona_user`/`parse_persona_traits`; гейт per-chat `flags.persona_enabled`, fail-open)
- [x] services/pg_db.py (F1 `persona_state` DDL+сид; F2 `personas`/`persona_traits` DDL, partial-unique,
      FK CASCADE, ALTER persona_state; идемпотентность)
- [x] services/permissions.py (`edit_persona` в ACTIONS_TREE/ACTION_IDS) — H2 закрыт
- [x] services/info_service.py + config_cache.py (F6 `content.intelligence_guide`, `GUIDE_SEED_FILE` абсолютный,
      идемпотентный сид) ; services/param_catalog.py (Δ +1 content, +1 limit, +2 flag, +3 models, +1 key)
- [x] services/status_service.py (R10.9-4 `invalidate_health_cache` по `models.*`/`keys.*`)
- [x] config/settings.py (+INTEL_REFLECTION_*×4, +GRAPH_FACT_WEIGHT_BOT/BOT_SELF_AWARENESS_ENABLED,
      +PERSONA_ENABLED, ClassVar SELF_ESSENCE_MAX_CHARS/PERSONA_TRAITS_MAX/PERSONA_TRAIT_MAX_CHARS)
- [x] web/api/routes.py (`GET/PUT/DELETE /api/persona`, `GET /api/persona/health`, `GET/POST /api/info/guide`,
      health-инвалидация в config/BYOK); web/api/memory_agi.py (fallback `bot_self_replies`)
- [x] web/app.js (F3 special-screen persona + ROUTE_*/canViewTab; F4 3-я лента + метрики + `fmtDayMonth`;
      F6 Markdown-гайд + fail-closed sanitize; F8 provider-блок `intel_reflection`; F5 scope-reset черновиков)
- [x] web/index.html (F3 карточка persona; F4 3-я лента + панель «Личность»; F6 гайд-блок; F7 порядок карточек;
      CSS `.guide-markdown`/`.cognition-ribbons 3`)
- [x] bot.py (только `await load_global_cache()` после `set_config_cache` — DI-порядок не тронут)
- [x] .env.example (+INTEL_REFLECTION_* плейсхолдеры, +GRAPH_FACT_WEIGHT_BOT/BOT_SELF_AWARENESS_ENABLED/PERSONA_ENABLED)
- [x] tests/* (new: test_graph_facts_origin_v9, test_bot_persona, test_persona_api, test_persona_prompt,
      test_self_reflection, test_self_reflection_provider_round1014, test_dream_persona_traits,
      test_help_guide_round1014, test_settings_persistence_round1014, test_webapp_round1014_ui; обновлены
      маркерные/каталог/JS) — pytest 5582/0, node --check OK, JS-UNIT-OK, git diff --check clean
- [x] plans/features/*-round1014/ (8 спек + ADR-1014-1/-2 + tasks), plans/reports/round10.14_scanner_audit.md
- **Открыто (Low, не блокеры, после итерации 2; 0 Critical / 0 High / 0 Medium / 2 Low / 2 Info):**
  **R10.14-4 [low]** `dynamic_traits` не фильтруются по chat_id (`routes.py:1461-1462`) — осознанно
  (traits = общий характер бота, F4). **R10.14-7 [low]** 12 leaked aiosqlite-соединений (pre-existing).
  **I10.14-1/2 [info]**: v7→v9-каскад без прямой фикстуры (safe по guard-анализу); FIFO-ротация трейтов глобальная.
- **Сквозной паттерн 10.14:** dedicated-API с собственным scope/RBAC сверять парой view↔edit;
  новые LLM-вызовы воркеров — всегда через worker_budget.

### Round 10.14 — повторный аудит (итерация 2, 2026-09-13)
- [x] Ре-верификация фиксов @Builder: **R10.14-1 (Medium) closed** — `routes.py:1365-1372`
      `_persona_has_edit_action`, `:1388-1399` `_persona_can_view` согласован с `_persona_can_edit`;
      `app.js:2820-2825` `canViewTab('persona')` → global-экран при `edit_persona`; тесты
      `test_persona_api.py:197-222` (view global/chat + GET/PUT consistency), `routing_test.js:190-195`;
      moderator/без прав по-прежнему 403 (`:193-195`, `:256-261`). **R10.14-2 (Medium) closed** —
      `dream_worker.py:1460` `_deep_budget_ok` до traits-LLM, `:1355-1368` кап учитывает `deep_traits`,
      `:1406-1415`/`:1475-1479` логирование токенов; тесты `test_dream_persona_traits.py:182-238`.
- [x] Low закрыты: R10.14-3 (`routes.py:1452-1460`, тест `:224-238`), R10.14-5 (док. `summary_memory.py:1771`),
      R10.14-6 (docstring 8→9 в 4 файлах).
- [x] Валидатор: pytest **5589 passed**/0 fail (60.58 s), `node --check web/app.js` OK,
      `routing_test.js` JS-UNIT-OK, `git diff --check` OK. Инварианты: R17/R16, роутеры `bot.py`,
      `media/`/`.env` не тронуты, REGISTRY 435/GROUPS 90/mapped 88/TAB_RULES 19, DOMPurify self-host,
      SQLite v9/PG DDL целы.
- Итог итерации 2: **0 Critical / 0 High / 0 Medium / 2 Low** открытых; вердикт — открытых
  Critical/High/Medium НЕТ.

## Round 10.13 scan (2026-09-13) — all scanned (diff-based, 8 фич F1–F8)
- [x] services/summary_memory.py (F1 `_fact_prefix`/`_stale_suffix`/4-кортежи RAG; F2 `_knn_graph_facts`
      архив+penalty+`_resurrect_resonant`, `graph_activation_facts`)
- [x] services/dream_worker.py (F2 decay/`_reinforce`/`_try_reanimate`; F3 packet/bridge/`_run_deep_*`/
      `_deep_tick`/`_deep_budget_ok`/`_write_paradigm`; роутер `_worker_llm`)
- [x] services/dream_prompts.py (PREV-слепок, правило 5, `order_dream_rows`, `build_bridge_user`,
      `parse_bridge_answer`, DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT)
- [x] services/database.py (F2 belief-хелперы + `list_recent_beliefs` status/kind; F3 deep-маркеры/
      `count_paradigms`; F8 `meme_exists`/`list_chat_memes`; F5 `graph_snapshot`/`graph_stats`;
      `search_graph_facts_fts(include_archived)`; `sum_dream_log_tokens(kind)`)
- [x] services/direct_chat_service.py (F5 `_PROCESS_ACCOUNTING`/`record_*`; F2 graph-activation hook;
      F8 persona-блоки [Факты]/[Мемы])
- [x] services/lore_worker.py (F8 `_classify_dossier*`/`_window_names`/`_canon`; F3 `_worker_llm` history)
- [x] services/dossier_prompts.py (NEW; канон + keyword fail-safe + parser + `format_dossier_block`)
- [x] services/lore_prompts.py / dream_prompts.py (PREV-слепки, ироническая заметка)
- [x] services/llm_client.py (`generate_worker`/`_worker_profile` — history/background, фоллбэк)
- [x] services/llm_probe.py (`_LLM_BLOCKS`/`_BLOCK_SAVED_KEY` intel_*, `_saved_api_key` фоллбэк)
- [x] services/memory_health.py (счётчики убеждений/парадигм)
- [x] services/nostalgia_worker.py (`_worker_llm` background)
- [x] services/log_ring.py (`ERROR+WARNING`)
- [x] services/status_service.py (`server.cpu_count`, `context`)
- [x] services/tool_router.py (dig: `include_archived`, единый RAG-рендер)
- [x] services/worker_budget.py (`WORKER_DEEP_SLEEP`, `allowed_workers` позиция -1)
- [x] config/settings.py (+INTEL_*×8, +RAG_STALE_AFTER_DAYS, BELIEF_*×6, DEEP_SLEEP_*×6, IRONY_FILTER_ENABLED;
      APP_VERSION 2.57.0)
- [x] services/param_catalog.py (Δ +22: F1/F2/F3/F4/F8; `_PG_ID_OVERRIDES`; select-widget DEEP_SLEEP_TRIGGER)
- [x] web/api/memory_agi.py (`cognition/status`, `graph`, `stats`, `timeline`, `deep-sleep`, `health`,
      `?deep=1`, beliefs status/kind)
- [x] web/api/routes.py (logs 422/=, docstring)
- [x] web/app.js (F4 2 provider-блока; F5 cognition-polling/graph/ленты/виджет; F6 EKG + logLevel watch)
- [x] web/index.html (F5 дашборд/виджет, F6 EKG + селектор логов; CSS)
- [x] web/static/vendor/vis-network/vis-network.min.js (NEW, self-host v9.1.9)
- [x] bot.py (DI `aliases=AliasResolver` в LoreWorker; router order не тронут)
- [x] .env.example (+INTEL_*, RAG_STALE_AFTER_DAYS, DEEP_SLEEP_*) — **нет** BELIEF_*/IRONY_FILTER (S10.13-12)
- [x] tests/* (new: test_belief_decay, test_deep_sleep, test_dossier_*, test_webapp_round1013[_f5]_ui;
      обновлены маркерные/каталог/JS) — pytest 5383/0, JS-UNIT-OK, node --check clean
- [x] plans/features/cognition-*-round1013/ (8 спек + ADR-1013-1/2/3), plans/docs/intelligence_user_guide.md,
      README.md, plans/MEMORY.md, plans/backlog.md (doc-only)
- [x] plans/reports/round10.13_scanner_audit.md — итог: **0 critical / 1 high / 4 medium / 9 low**
- **Открыто (follow-up, не блокеры после фикса high):** S10.13-1 [high] неэкранированный `target_user`
  в `_fact_prefix` (RAG-промпт); S10.13-2 deep-sleep cooldown/суточный кап обходятся на неуспешных
  прогонах (`deep_run` пишется только при written>0; кап суммирует только `deep_run`);
  S10.13-3 F2-decay архивирует F3-парадигмы (`list_confirmed_beliefs` без фильтра `type='paradigm'`);
  S10.13-4 реаниматор (`kind='skipped'/status='resurrected'`) не виден в `resurrections_total`/health/
  Timeline; S10.13-5 F5-ленты beliefs/paradigms без `chat_id`; S10.13-6 `graph_stats` facts без
  `status` и beliefs с парадигмами; S10.13-7 `or <default>` блокирует 0-значения; S10.13-8 deep-sleep TZ
  = SUMMARY_TIMEZONE (спека: WORKER_BUDGET_TZ); S10.13-9 Timeline lore = in-memory inject (спека:
  chat_lore_history); S10.13-10 probe не зеркалит runtime base/model-фолбэк; S10.13-11 LIKE-маркер
  парадигм хрупок; S10.13-12 `.env.example`/описание irony-флага; S10.13-13 три дубля парсера
  `belief_meta`; S10.13-14 граф может отдавать «висячие» рёбра.
  Из прошлых раундов: R10.12-1/-5, R10.12-2/-3/-4, R10.11-1…-6, R10.10-*, R10.9-*.

### Round 10.13 — повторный аудит (итерация 2, 2026-09-13)
- [x] Ре-верификация фиксов @Builder: S10.13-1 (High) closed — `summary_memory.py:723-728`
      `escape_xml_text`+схлопывание `\n\t`, рантайм `&lt;/RAG_Memory&gt;`, тест
      `tests/test_webapp_round1013_ui.py:63-84`; S10.13-2 closed (`dream_worker.py:1153-1156`,
      `_log_deep_skip:1373-1381`, `_deep_budget_ok:1329-1348`, `database.py:2088-2117`);
      S10.13-3 closed (`database.py:1932-1954`, тест `test_belief_decay.py:215-228`);
      S10.13-4 closed (`dream_worker.py:1019-1026`, `memory_health.py:80-82`,
      `memory_agi.py:313,548-553`); S10.13-5 closed (`web/app.js:4830-4835`).
- [x] Low: закрыты S10.13-7 (`_hot_number`), -8 (`_deep_tz_name`=WORKER_BUDGET_TZ),
      -10 (`llm_probe._intel_probe_fallback`), -12 (`.env.example` + описание флага).
- [x] Валидатор: pytest **5392 passed**/0 fail (60.75 s), `node --check web/app.js` clean,
      `routing_test.js` JS-UNIT-OK, `git diff --check` OK. Инварианты: 0 PG-DDL, SQLite v8,
      роутеры bot.py, REGISTRY 427/GROUPS 90/mapped 88/TAB_RULES 19, vis-network self-host.
- **Открыто (Low, не блокеры, итерация 2):** S10.13-9 Timeline-лор = in-memory inject
  (`memory_agi.py:596-604`); S10.13-11 хрупкий LIKE-маркер парадигм (`database.py:1941-1942`
  и др.); S10.13-13 три дубля парсера `belief_meta` (`database.py:1919-1930`,
  `dream_worker.py:857-869`, `summary_memory.py:70`); S10.13-14 «висячие» рёбра графа
  (`database.py:3538-3541`); **новый S10.13-6b** `archived_beliefs` без фильтра парадигм
  (`database.py:3590-3592`).
- Итог итерации 2: **0 Critical / 0 High / 0 Medium / 5 Low** открытых; вердикт — High
  открытых НЕТ.

## Round 10.12 scan (2026-09-13) — all scanned
- [x] config/settings.py (`LLM_BASE_URL` default → nano-gpt; +`EMBEDDING_BASE_URL`, +`EMBEDDING_API_KEY`,
      +`OPENROUTER_TRANSCRIBE_DISPLAY_NAME`; +`DEFAULT_KOSTIK_REPLIES`/`KOSTIK_REPLIES`/`KOSTIK_ENABLED`;
      Settings 372→377)
- [x] services/llm_client.py (`embed_base_url`/`embed_api_key` DI, `_embed_base_url`/`_embed_api_key`,
      `_current_embed_api_key`, `_post(base_url=…, channel='embed')`, отдельный `_embed_client`-кэш;
      chat-путь/ретраи/`EMBEDDING_FALLBACK_*` целы)
- [x] services/status_service.py (`emb_base`/`emb_key` из embed-ключей; `emb_main` без алиасинга `main_base`;
      `stt_openrouter` → `models.openrouter_transcribe_display_name`)
- [x] services/llm_probe.py (`_BLOCK_SAVED_KEY` primary-embed → `keys.embedding_api_key`; `_saved_api_key`
      фолбэк на `keys.llm_api_key`; Google-фоллбэки не затронуты) — инфо-нит по docstring (R10.12-2)
- [x] services/param_catalog.py (Δ +5: `models.embedding_base_url`, `models.openrouter_transcribe_display_name`,
      `keys.embedding_api_key`, `flags.kostik_enabled`, `reactions.kostik_replies` widget=list;
      `_REACTIONS` 6-элементные строки)
- [x] services/permsoc.py (`PermsocModule('kostik').sub_flag_key='flags.kostik_enabled'`;
      `DEFAULT_SUB_FLAGS['flags.kostik_enabled']=True`)
- [x] handlers/kostik.py (литерал удалён; thin-alias; `hot.get('reactions.kostik_replies', default)` +
      `_resolve_replies`; пустой список → молчание)
- [x] bot.py (только 4 пары DI `embed_base_url`/`embed_api_key`; router order/media не тронуты)
- [x] web/app.js (`api()` global-опция без утечки в fetch; `saveBlock`/`saveConfigItem` global-save;
      merged `PROVIDER_BLOCKS` + `blockDisplayName`; owner-блок Костика; `list-editor`)
- [x] web/index.html (merged-заголовки + `{{ blockDisplayName }}`; ветка `widget==='list'` в обоих
      generic-шаблонах; `#list-editor-tpl`)
- [x] .env.example (nano-gpt/apinet defaults; `EMBEDDING_API_KEY` комментарий; плейсхолдеры)
- [x] tests/js/routing_test.js (merged-блоки, global-save, `saveConfigItem`, `blockDisplayName`,
      `list-editor`, owner-блок), tests/test_webapp_round1012_ui.py (NEW), test_llm_client.py,
      test_kostik.py, test_permsoc.py, test_param_catalog.py, test_status_service.py, test_webapp_api.py,
      test_migrate_env_to_pg.py, test_round106_ia_smoke.py, test_frontend_tab_mapping.py,
      test_webapp_parity_smoke.py, test_webapp_round10{9,10,11}_ui.py
- [x] plans/features/providers-kostik-round1012/ (spec + ADR-1012-1 + tasks), plans/backlog.md (doc-only)
- [x] plans/reports/round10.12_scanner_audit.md (итог: 0 blocker/0 high/0 medium; 2 low R10.12-1/-5,
      3 info R10.12-2…-4)
- Открыто (follow-up, не блокеры): **R10.12-1** `web/app.js:3092-3112` `saveKeyItem` не переведён на
  global-save → 422 для `keys.*` вне provider-блоков (`CHECKUP_BETTERSTACK_SQL_*`, `YOUTUBE_COOKIES_FILE`,
  `YOUTUBE_TRANSCRIPT_PROXY_*`) при активном чате; **R10.12-5** `web/app.js:362,380,400` parent
  `modules==title` → `blockDisplayName` дублирует заголовок (косметика); R10.12-2 stale docstring
  `llm_probe.py:14`; R10.12-3 `KOSTIK_ENABLED` вне `.env.example`; R10.12-4 index-key в `list-editor`
  (`index.html:3181`). Из прошлых раундов: R10.11-1/-2/-3 (low), R10.11-4/-5/-6 (info), R10.10-1/-2/-4/-5,
  R10.9-1/-2/-3/-4, R10.7-1/-2, R10.6-1/-2/-3.

## Round 10.11 scan (2026-09-12) — all scanned
- [x] services/param_catalog.py (ADR-1011-2: 4 embed-фоллбэк-записи переведены из `_INFRA`
      в first-class каталог; REGISTRY 400/GROUPS 90/Settings 372/mapped 88 без изменений;
      categorized 372→376, infra 28→24; models 42 / keys 15)
- [x] services/llm_probe.py (`_BLOCK_SAVED_KEY` + `_saved_api_key` — R17-резолв сохранённого
      ключа при пустом `api_key`; `video_fallback`/`embeddings_main`/`_fallback1/2` в
      `KNOWN_BLOCKS`/`_EMBEDDING_BLOCKS`; kind=embeddings)
- [x] services/llm_client.py (embed-фоллбэк через `hot.get` с прежними кwarg-дефолтами)
- [x] services/status_service.py (embed-фоллбэк base/model/key1/key2 через `hot.get`)
- [x] web/app.js (`providerConnectionBlocks`/`providerAdvancedBlocks` — computed; `video_fallback`;
      embeddings 3 подблока; `zone:'advanced'` для guard/search/media_share; рекурсивный
      `providerCoveredKeys`; `blockFieldConfigured`/`last4ByKey`; `keyHistoryChartModel` —
      точки `{x,y}` + `spanGaps:true`; X linear + HH:MM callback + `parsing:false`)
- [x] web/index.html (две зоны, `<component :is=details/div>`, subBlocks-рендер, key-hint,
      nav/hub CSS 2.1, `:value`+`@input` без префилла секретов)
- [x] .gitignore (+plans/current_task.md), plans/backlog.md (doc-only)
- [x] tests/js/routing_test.js (chart-точки/ось; R17-draft; computed-зоны; video/embeddings),
      tests/test_webapp_round1011_ui.py (NEW), test_round106_ia_smoke.py, test_webapp_api.py
      (376; blank api_key → saved), test_param_catalog.py (42/15), test_migrate_env_to_pg.py (15)
- [x] plans/features/llm-providers-refactor-round1011/ (spec + ADR-1011-1/-2/-3 + tasks),
      plans/docs/memory_sleep_nostalgia_lore_report.md (п.4, docs-only)
- [x] plans/reports/round10.11_scanner_audit.md (итог: 0 blocker/0 high/0 medium; 3 low
      R10.11-1…-3, 3 info R10.11-4…-6)
- Открыто (follow-up, не блокеры): R10.11-1 (nested details делят localStorage-ключ),
  R10.11-2 (`embedding_fallback_model`: status vs runtime при явной очистке), R10.11-3
  (устаревшие «правьте в .env» для embed-ключей), R10.11-4 (probe + caller base_url —
  hardening), R10.11-5 (мёртвый `destroy`), R10.11-6 (нет headless Chart.js-теста).
  Из прошлых раундов: R10.10-1/-2 (скрипт DM), R10.10-4/-5 (фронт), R10.9-1/-2/-3/-4,
  R10.7-1/-2, R10.6-1/-2/-3.
- Обязательный деплой-шаг (ADR-1011-2): `python scripts/migrate_env_to_pg.py
  --only-category models,keys` (БЕЗ `--force`) до UI-проверки сохранённых embed-ключей.

## Round 10.10 scan (2026-09-12) — all scanned
- [x] web/index.html (fullscreen `.fullscreen-mode header.header-sticky` padding `max(env,--tg-*)`;
      10.7 width/10.9 scroll целы; «Провайдеры» `:value`+`@input`; «Роли» аватар/ник/ID `text-[10px]`
      `text-gray-500 font-mono`, `w-24`, `flex-1 min-w-0`, `shrink-0`; `.keys-chart` wrapper)
- [x] web/app.js (`keyHistoryChartModel` + `SAMPLE_BUCKET`/`MIN_BUCKETS`/окно от конца; `maintainAspectRatio:false`
      + `keyHistoryChartHeight` + `$nextTick`; `blockFieldValue` `''`-очистка; сброс `blockDrafts`/`blockResults`
      в `loadConfig`/`setActiveChat`; `loadAdmins` blob-аватары; `adminInitial`)
- [x] services/chat_params.py (`_DM_DISABLED_GATES`/`_DM_DISABLED_OVERRIDES`; `ensure_scope_profile(dm=True)`
      дефолты OFF; групповой путь и `bot.py` не тронуты)
- [x] scripts/disable_dm_heavy_modules.py (NEW: dry-run/`--apply`/`--chat-id`/`--snapshot-out`/`--restore`;
      snapshot до записи + abort; idempotent; merged namespaces; partial-failure → exit 1; 0 DDL)
- [x] web/api/avatars.py (`global_user_display_info`, `_user_name_cache`, транзиентные НЕ кэшируются)
- [x] web/api/routes.py (`GET /api/admins` enrichment копий, `gather`+`Semaphore(5)`, fail-open, RBAC не ослаблен)
- [x] tests/test_webapp_round1010_ui.py (NEW), tests/test_scripts_round1010_dm_off.py (NEW),
      tests/js/routing_test.js (chart/`blockFieldValue`/`adminInitial` юниты), tests/test_chat_params.py,
      tests/test_webapp_api.py, tests/test_webapp_avatars_ui.py
- [x] plans/features/admin-ui-round1010/ (spec/tasks + ADR-1010-1/-2/-3), plans/backlog.md
- [x] plans/reports/round10.10_scanner_audit.md (итог: 0 blocker/0 high/0 medium; 3 low R10.10-1…-3, 2 info R10.10-4/-5)
- Открыто (follow-up, не блокеры): R10.10-1 staged-отчёт `noop/total`; R10.10-2 `meta.note` вне snapshot;
  R10.10-3 chart-return без destroy; R10.10-4 аватары админов без skip; R10.10-5 дубль `adminInitial`.
  Из прошлых раундов: R10.9-1/-2/-3 (status_service), R10.9-4 (health cache-key), R10.7-1/-2,
  R10.6-1 (дубль generic-рендера), R10.6-2/-3 (SSRF/422-эхо `api_key`).

## Round 10.9 scan (2026-09-12) — all scanned
- [x] config/settings.py (+SLAVIK_ENABLED default True; +7 LLM/GROQ/OPENROUTER/EMBEDDING*_DISPLAY_NAME; Settings 372)
- [x] services/permsoc.py (slavik sub_flag_key=`flags.slavik_enabled`; DEFAULT_SUB_FLAGS True)
- [x] services/param_catalog.py (GROUPS 90/REGISTRY 400/mapped 88; −reactions_persons; SLAVIK_USER_ID→reactions_slavik;
      OLYA_USER_ID→reactions_olya; +7 display-name ParamSpec; переписаны title/description без жаргона/AI-шаблона; TAB_PERMSOC без persons)
- [x] services/status_service.py (llm_registry: group_id/group_title/display_name/provider=host/kind; probe_openai-интеграция;
      `_check_health` кэш по module_id 2xx 60с/ошибки 10с; emb main+2fb; `_display`/`_model_from`; healthLabel-контракт)
- [x] services/llm_probe.py (probe_openai chat/embeddings/stt; `_post_multipart`+`_silent_wav`; timeout/unreachable/error/not_configured; sanitize R17)
- [x] web/app.js (PERMSOC_OWNER_BLOCKS/TOGGLE_KEYS; `_permsocOwnerGroups`/`permsocOwnerOn`/`canToggleOwner`/`toggleOwner`;
      `llmGroups`; `healthBadge`/`healthLabel`; `_preserveScroll` (document+`.scroll-area`); −whoCanToggle/−optInCount;
      PROVIDER_BLOCKS display-name первым + человеческие label'ы; loadModules без бюджета; loadOversight→loadBudgetInfo)
- [x] web/index.html (owner-блоки `<component is=details/div>` + один `<summary>`-тумблер; −мастер-карта permsoc;
      −«Тяжёлые фичи»; «Бюджет фона (день)» в «Сводке»; блок «Доступность ключей» 4 группы; «История доступности ключей»;
      `configLoading && !configItems.length`; `max-w-3xl`; --grad-speed 14s/grad-drift 18s)
- [x] tests/test_webapp_round109_ui.py (NEW 18 тестов), tests/test_status_service.py (probe_openai/кэш-ошибок/группы), test_key_availability.py,
      test_param_catalog.py, test_frontend_tab_mapping.py, test_round106_ia_smoke.py, test_webapp_parity_smoke.py, test_webapp_api.py,
      test_permsoc.py, test_webapp_dm_ui.py, test_webapp_key_availability_ui.py, test_webapp_status_control.py,
      test_webapp_nav_disclosure_ui.py, test_webapp_avatars_ui.py, test_webapp_round108_ui.py, test_104_backend_additions.py
- [x] tests/js/routing_test.js (`_preserveScroll` два-скроллера юнит; спиннер-условие)
- [x] plans/features/admin-ui-round109/ (spec.md, tasks.md, ADR-109.md)
- [x] plans/backlog.md, plans/reports/round10.9_scanner_audit.md (0 blocker/0 major/0 medium; 3 low R10.9-1…3, 3 info R10.9-4…6)
- Открыто (follow-up, не блокеры): R10.9-1 (`model_source`); R10.9-2 (emb-fallback display/read);
  R10.9-3 (stale docstring status_service); R10.9-4 (health cache-key по module_id).
  Из прошлых раундов вне UI-скоупа: R10.7-1/-2 (`status_service` gap-fill), R10.6-1 (дубль generic-рендера),
  R10.6-2/-3 (SSRF/422-эхо `api_key`).

## Round 10.8 scan (2026-09-11) — all scanned
- [x] web/app.js (labels TABS/NAV/HUBS; ICONS 20→37 (17 new, 6 dead из 10.7 не вернулись);
      applyRoute accessOpen-нормализация; openAccessWindow/closeAccessWindow (−setAccess);
      setTab cleanup copiedTimer/copiedIndex; fmtLogTime DD.MM HH:MM:SS)
- [x] web/index.html (заголовки разделов; emoji→Material (§2.2); логи: div.log-code/.log-row/
      .log-head/.log-msg без жёстких ширин и break-all, toggle chevron/spacer; «Доступы»:
      3 modal-backdrop + плитки, `sec-*` целы; удалён внешний GLOBAL-бейдж)
- [x] scripts/build_font_subset.py (ICON_NAMES 37; `_marker_key` sha(src|names);
      `_write_icon_codepoints` → build/icon_codepoints.json)
- [x] web/static/fonts/material-symbols-rounded.woff2 (субсет 18 388 B, cmap 37/37)
- [x] README.md (структура: «самое важное», управление+деплой, changelog под `<details>`,
      шапка v2.52.0/5073)
- [x] tests/test_webapp_round108_ui.py (NEW: renames/emoji/badge/logs/access-windows)
- [x] tests/test_font_subset.py (паритет ICONS↔ICON_NAMES + cmap через fontTools; Test C/D)
- [x] tests/test_webapp_tma_fixes_ui.py, test_webapp_round107_ui.py (логи: блок-раскладка,
      toggle-иконка, отсутствие жёстких ширин)
- [x] tests/test_frontend_tab_mapping.py, test_round106_ia_smoke.py (access windows)
- [x] tests/test_webapp_hubs_matrix_ui.py, test_webapp_parity_smoke.py (новые лейблы)
- [x] tests/test_webapp_key_availability_ui.py (sec-roles/sec-matrix вместо слайсинга)
- [x] tests/test_webapp_back_button.py (openAccessWindow/closeAccessWindow/ROUTE_PARENT)
- [x] tests/test_webapp_nav_disclosure_ui.py (⚙️→iconGlyph('settings')), test_webapp_avatars_ui.py (✕==4)
- [x] tests/js/routing_test.js (applyRoute #/access/roles→'roles', #/ai→null; fmtLogTime дата)
- [x] plans/features/admin-ui-round108/ (spec.md, tasks.md, ADR-001, ADR-002)
- [x] plans/backlog.md, plans/reports/round10.8_scanner_audit.md (итог: 0 блокеров/0 major,
      2 minor R10.8-1 Esc / R10.8-5 APP_VERSION=2.51.0 vs README v2.52.0 + кэш старого
      субсета `.woff2` (max-age 86400, URL не версионирован) → tofu; 3 info; R10.7-3/R10.7-4 закрыты)
- Открыто (НЕ 10.8, кандидаты 10.9): R10.7-1/-2 (`services/status_service.py`),
  R10.6-1 (дубль generic-рендера `llm_providers`), R10.6-2/-3 (SSRF/422-эхо `api_key`).

## Round 10.7 scan (2026-09-11) — all scanned
- [x] web/app.js (scope* → computed 6 шт; ICONS −6 мёртвых; fmtLogTime; copyText
      finally-remove + preventScroll + boolean execCommand; copyLogRow + copiedIndex;
      copyAllLogs self.logText)
- [x] web/index.html (1b `header.header-sticky`+env safe-area; 1c компактный user block;
      1d nav-label keep-all/2-line clamp/0.625rem; 2a scoped `.keys-avail` fixed+ellipsis;
      3a `.clipboard-ghost` opacity/contain strict без visibility:hidden; 3b log-колонки;
      3c `log-copied`/`copyLogRow`)
- [x] services/status_service.py (2b `_bucketize` gap-fill 'down' до now_slot;
      `last_heartbeat` = последний 'up'/None)
- [x] tests/test_webapp_round107_ui.py (NEW: маркеры 1b/1c/1d/2a/3a/3b/3c)
- [x] tests/js/routing_test.js (стаб document/navigator/execCommand; 3a ghost-removed,
      DEF-2 false-execCommand, 3c copyLogRow, 1a computed)
- [x] tests/test_status_service.py (gap-fill up/down/down/up, trailing downtime,
      last_heartbeat None/truthy)
- [x] tests/test_font_subset.py (R106-5: `\ue887` help вместо `\ue850`)
- [x] tests/test_webapp_avatars_ui.py (`_Static.body` — regex определения функции)
- [x] tests/test_webapp_back_button.py (1a: 6 scope* в computed, не methods)
- [x] tests/test_webapp_tma_fixes_ui.py (3c: `copyLogRow(log,i)` + `log-copied`)
- [x] plans/backlog.md, plans/features/admin-ui-bugfixes-round107/ (spec/tasks)
- [x] plans/reports/round10.7_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major,
      1 minor + 3 info + 1 nit; R10.6-5 закрыт)

## Round 10.6 scan (2026-09-11) — all scanned
- [x] config/settings.py (5 master-флагов FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP_ENABLED, default True)
- [x] services/param_catalog.py (GROUPS 91/REGISTRY 392/Settings 364/mapped 89; расщепления
      limits_media→4, limits_persons→2, limits_youtube_web→2, limits_cooldowns→0,
      flags_modules→7, flags_chat_behavior→7, reactions_kostik NEW, limits_rag NEW;
      _FLAGS +TAB_RULES/CONFIG_TAB_TITLES 19;_TAB_BY_GROUP 89, DDL-free)
- [x] services/llm_probe.py (NEW: _safe_base SSRF-минимум, sanitize_error R17,
      KNOWN_BLOCKS, probe_block/_probe_search, per-field search_keys:tavily/exa)
- [x] web/api/routes.py (POST /api/llm/test: requires_global_admin, rate-limit 5с/ttl-прунинг,
      LlmTestRequest; reset_llm_test_rate_limit — тест-точка)
- [x] handlers/factcheck.py, search.py, web.py, checkup.py, youtube.py
      (5 master-гейтов hot.get→UNHANDLED; youtube — только mode=="summary")
- [x] web/app.js (MODULES 11, PROVIDER_BLOCKS 9, accessOpen-аккордеон, scope/route-алиасы,
      activeModule-модалка, Esc/back-закрытие, canEditConfig DM per_chat R10.5-2,
      initBackButton ready R10.5-1, TAB_SECTION_ORDER 19, emoji→Material)
- [x] web/index.html (sidebar/☰/MENU_ORDER удалены, nav-label, scroll-модель,
      модуль-карточки+модалка, prov-блоки+test-кнопка, аккордеон, iconGlyph help/matrix)
- [x] tests/test_round106_gates.py (NEW: OFF→UNHANDLED ×5 + default ON)
- [x] tests/test_round106_ia_smoke.py (NEW: каталог-инвариант, nav, IA, llm_probe, SSRF)
- [x] tests/test_frontend_tab_mapping.py, test_param_catalog.py, test_webapp_api.py
      (POST /api/llm/test 403/200/429/R17), test_webapp_nav_disclosure_ui.py,
      test_webapp_hubs_matrix_ui.py, test_webapp_parity_smoke.py, test_webapp_dm_ui.py,
      test_webapp_agi_ui.py, test_webapp_back_button.py, test_webapp_lore_ui.py,
      test_webapp_avatars_ui.py, tests/js/routing_test.js (маркеры новой IA)
- [x] plans/features/tma-ia-modules-rework/ (spec v2, design-project v2, tasks)
- [x] plans/backlog.md (doc-only)
- [x] plans/reports/round10.6_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major,
      3 minor + 3 info)

## Round 10.5 scan (2026-09-10) — all scanned
- [x] .gitignore (relumesite_example/, MaterialSymbolsRounded*.woff2, var/, build/)
- [x] services/key_history.py (NEW: allowlist, атомарный снимок, ring, fail-open)
- [x] services/param_catalog.py (_MODELS_PG_ONLY: +4 PG-only → REGISTRY 387/74/359)
- [x] services/config_cache.py (rename_role/role_usage/_scrub_param_permissions — DML-only)
- [x] services/status_service.py (_resolve/llm_registry module_id|module_title|model_source;
      _build_llm_card → key_history.record; maybe_save)
- [x] services/video_cascade_client.py (base_url hot + инвалидация клиента)
- [x] SmartModule/transcriber/groq_transcriber.py (hot base_url/model)
- [x] SmartModule/transcriber/openrouter_transcriber.py (hot base_url/model)
- [x] web/api/routes.py (roles DELETE + /rename; GET /status/key-history; get_roles role_type)
- [x] web/api/access.py (param_permissions_list: tab/tab_title/group*/title/secret метаданные)
- [x] web/app.py (mount /static — self-host fonts/vendor)
- [x] web/app.js (hash-роутер, navbar/hub, scope-dropdown+a11y, матрица, key-avail,
      role rename/delete, sanitize fail-closed, scopeEpoch-гварды, иконки PUA)
- [x] web/index.html (токены+градиенты, @font-face, navbar/hub, scope-dropdown,
      матрица, key-avail, self-host dompurify, адаптив)
- [x] scripts/build_font_subset.py + scripts/requirements-font.txt (NEW, build-time only)
- [x] web/static/fonts/* (субсет 13 КБ + LICENSE Apache-2.0)
- [x] web/static/vendor/dompurify-3.4.15.min.js (self-host, pinned)
- [x] conftest.py (M6: STATUS_KEY_HISTORY_FILE → temp)
- [x] tests/test_key_availability.py, test_roles_admin.py, test_font_subset.py,
      test_webapp_back_button.py, test_webapp_hubs_matrix_ui.py, test_webapp_js_unit.py,
      test_webapp_key_availability_ui.py, test_webapp_parity_smoke.py, tests/js/routing_test.js (NEW)
- [x] tests/test_menu.py, test_param_catalog.py, test_video_cascade.py, test_webapp_api.py,
      test_webapp_avatars_ui.py, test_webapp_deps.py, test_webapp_dm_ui.py,
      test_webapp_nav_disclosure_ui.py, test_webapp_rbac_ui.py (маркеры обновлены)
- [x] plans/features/tma-relume-redesign/ (spec v3, design-project v5, tasks, reference-analysis)
- [x] plans/MEMORY.md, plans/backlog.md (doc-only)
- [x] plans/reports/round10.5_scanner_audit.md (итоговый отчёт — 0 блокеров/0 major)

## Round 10.4 scan (2026-09-10) — all scanned
- [x] plans/features/* (8 спек: A reorg, B limits-temp-budgets, C memory-sleep-nostalgia,
      D advanced-collapse, E llm-providers-layout, F relations-participants,
      G chat-1002661910336-scaling, H relations-nickname)
- [x] services/param_catalog.py (TAB_RULES/CONFIG_TAB_TITLES/_TAB_BY_GROUP,
      select_options/labels, _MEMORY progressive_level, _ADVANCED_GROUPS)
- [x] services/chat_params.py (_resolve_from_root G-2: _cast_type_ok + isfinite)
- [x] services/direct_chat_service.py (_cp_g-точки, _budget_gate B-2,
      _apply_context_budget(enabled, tokens), _thread_limit, window[-max(1,..)],
      _active_participants, level2 cap, thread depth)
- [x] services/summary_aliases.py (+build_alias_resolver)
- [x] services/summary_generator.py (_chat_limit: rag_l2/max_context_tokens/chars)
- [x] services/summary_memory.py (window/rag/retention/compress/edge_weight per-chat)
- [x] services/user_relations.py (_display_name B-13-limitation, документирование)
- [x] web/api/routes.py (GET select_options/labels; POST валидация — обе ветки)
- [x] web/api/chat_lore.py (list_relations: Semaphore(5) username-всем, photo-топ-50,
      per-chat alias_resolver B-13)
- [x] web/app.js (TABS-зеркало, flatGroupRank, sectionTitle, chatLoreTab/relationsTab,
      setTab-сброс, relChat-гвард, relations-автозагрузка, карточки модулей)
- [x] web/index.html (select-виджет basic+advanced, `:open="expandOpen"`, relations-
      шаблон (участники+конфиг-блок+аккордеон), lore-конфиг-блок, удаление блока
      участников из лора, карточки модулей)
- [x] scripts/backfill_104_chat_flags.py (идемпотентность/безопасность)
- [x] scripts/backfill_104_overrides.py (множители, caps, skip-логика None-дефолтов)
- [x] tests/test_104_backend_additions.py, test_progressive_tab_basic_coverage.py,
      test_frontend_tab_mapping.py + обновлённые маркер-тесты (4860 passed)
- [x] plans/reports/round10.4_review_fixes.md (соответствие реальности: 3 пункта —
      R10.4-3/4/7 расхождения зафиксированы)

## Round 10.3 scan (2026-09-10) — all scanned
- [x] plans/features/tma-chat-selector-fixes/ (spec)
- [x] plans/features/dm-user-settings/ (spec)
- [x] plans/features/direct-sandbox-budget-investigation/ (spec)
- [x] services/access.py (DM-ветки can_access_chat/eligible_type/can_edit_param)
- [x] services/roles.py (is_dm_owner/DM_OWNER_PRESET/access_for DM-ветка)
- [x] services/chat_params.py (is_dm_scope/ensure_scope_profile/get_chat_param_defaulted/chat_summary_enabled)
- [x] services/llm_client.py (NoApiKeyForChat.details, BYOK-фоллбэк, usage-учёт)
- [x] services/direct_chat_service.py (S2-гейт, sandbox WARNING details)
- [x] services/summary_memory.py (S1-гейт, _mask_llm_raw, fallback-парсер, ретрай)
- [x] services/summary_scheduler.py (S3: skip chat_id>0)
- [x] services/chat_lore_store.py (П.2: chat_id<0)
- [x] services/oversight.py (П.4: chat_id<0)
- [x] web/api/routes.py (DM-гейты GET/POST/keys/delete/status)
- [x] web/api/access.py (DM-строка, фильтр <0)
- [x] web/api/gates.py (DM read/403 write)
- [x] web/api/chat_lore.py (DM→404)
- [x] web/app.js (canViewTab/canEditConfig/isDmCtx/configError/setActiveChat/closeApp)
- [x] web/index.html (селектор, template v-for/v-if, бейдж, z-index 45, баннер)
- [x] tests/test_dm_access.py, test_webapp_dm_ui.py + обновлённые тест-файлы (4831 passed)

## High priority (git working tree)
- [x] plans/MEMORY.md (untracked, doc-only)

## Root files
- [x] bot.py
- [x] manage.py
- [x] conftest.py
- [x] deploy_v2.9.2.py
- [x] check_remote_bot.py
- [x] debug_remote.py
- [x] docker-compose.yml
- [x] requirements.txt
- [x] pytest.ini
- [x] .gitignore
- [x] .env.example
- [x] info_text.md

## config/
- [x] config/settings.py
- [x] config/__init__.py

## handlers/
- [x] handlers/__init__.py
- [x] handlers/common.py
- [x] handlers/menu.py
- [x] handlers/media_common.py
- [x] handlers/info.py
- [x] handlers/search.py
- [x] handlers/admin_commands.py
- [x] handlers/alan.py
- [x] handlers/alan_greeting.py
- [x] handlers/kostik.py
- [x] handlers/slavik.py
- [x] handlers/slava_presence.py
- [x] handlers/olya.py
- [x] handlers/vasya.py
- [x] handlers/dead_page_trigger.py
- [x] handlers/dead_page_delete.py
- [x] handlers/war_alert.py
- [x] handlers/chat_lifecycle.py
- [x] handlers/direct_chat.py
- [x] handlers/factcheck.py
- [x] handlers/summary.py
- [x] handlers/video_download.py
- [x] handlers/voice_transcription.py
- [x] handlers/web.py
- [x] handlers/youtube.py
- [x] handlers/checkup.py
- [x] handlers/debug_config.py

## filters/
- [x] filters/__init__.py
- [x] filters/admin_word.py
- [x] filters/danger_word.py
- [x] filters/kucha_word.py
- [x] filters/olya_video.py
- [x] filters/otboy_word.py
- [x] filters/selfdev_word.py
- [x] filters/target_channel.py
- [x] filters/user_id.py
- [x] filters/vasya_name.py
- [x] filters/word_lists.py
- [x] filters/work_word.py

## services/
- [x] services/__init__.py
- [x] services/access.py
- [x] services/betterstack_handler.py
- [x] services/bot_commands.py
- [x] services/chat_access.py
- [x] services/chat_context.py
- [x] services/chat_keys.py
- [x] services/chat_lore.py
- [x] services/chat_lore_store.py
- [x] services/chat_params.py
- [x] services/chat_prompts.py
- [x] services/chat_usage.py
- [x] services/checkup_prompts.py
- [x] services/checkup_service.py
- [x] services/common_relay.py
- [x] services/config_cache.py
- [x] services/control_service.py
- [x] services/database.py
- [x] services/dead_page_relay.py
- [x] services/debug_config.py
- [x] services/direct_chat_service.py
- [x] services/dream_prompts.py
- [x] services/dream_worker.py
- [x] services/feature_gates.py
- [x] services/goodmorning_captions.py
- [x] services/goodmorning_relay.py
- [x] services/goodmorning_scheduler.py
- [x] services/hot_config.py
- [x] services/info_service.py
- [x] services/llm_circuit_breaker.py
- [x] services/llm_client.py
- [x] services/log_ring.py
- [x] services/lore_cache.py
- [x] services/lore_notify.py
- [x] services/lore_prompts.py
- [x] services/lore_runtime.py
- [x] services/lore_worker.py
- [x] services/media_download.py
- [x] services/media_group_buffer.py
- [x] services/media_picker.py
- [x] services/media_share.py
- [x] services/memory_backup.py
- [x] services/memory_health.py
- [x] services/memory_maintenance.py
- [x] services/message_counter.py
- [x] services/mimic_relay.py
- [x] services/mimic_transform.py
- [x] services/nostalgia_prompts.py
- [x] services/nostalgia_worker.py
- [x] services/olya_relay.py
- [x] services/oversight.py
- [x] services/param_catalog.py
- [x] services/payload_builder.py
- [x] services/permissions.py
- [x] services/permsoc.py
- [x] services/persistent_throttling.py
- [x] services/pg_db.py
- [x] services/progress_reporter.py
- [x] services/prompt_migrations.py
- [x] services/roles.py
- [x] services/sandbox_reply.py
- [x] services/scheduler.py
- [x] services/search_aggregator.py
- [x] services/search_prompts.py
- [x] services/search_service.py
- [x] services/smart_cache.py
- [x] services/smartmodule_concurrency.py
- [x] services/smartmodule_phrases.py
- [x] services/smartmodule_throttling.py
- [x] services/smartmodule_urls.py
- [x] services/smartmodule_utils.py
- [x] services/status_service.py
- [x] services/summary_aliases.py
- [x] services/summary_cleanup.py
- [x] services/summary_generator.py
- [x] services/summary_memory.py
- [x] services/summary_prompts.py
- [x] services/summary_scheduler.py
- [x] services/summary_throttling.py
- [x] services/summary_xml.py
- [x] services/system_logs_fetcher.py
- [x] services/token_counter.py
- [x] services/tool_loop.py
- [x] services/tool_router.py
- [x] services/tool_schemas.py
- [x] services/typing_manager.py
- [x] services/uptime_heartbeat.py
- [x] services/user_relations.py
- [x] services/video_cascade_client.py
- [x] services/web_content_extractor.py
- [x] services/web_prompts.py
- [x] services/web_runtime.py
- [x] services/web_summarizer_service.py
- [x] services/worker_budget.py
- [x] services/youtube_prompts.py
- [x] services/youtube_summarizer_service.py
- [x] services/youtube_transcript_engine.py

## scripts/
- [x] scripts/__init__.py
- [x] scripts/backfill_feature_gates.py
- [x] scripts/backfill_permsoc_gates.py
- [x] scripts/migrate_direct_chat_v2.py
- [x] scripts/migrate_env_to_pg.py
- [x] scripts/migrate_epic60_v3.py
- [x] scripts/migrate_graphrag_v2.py
- [x] scripts/run_golden_questions.py
- [x] scripts/seed_chat_lore.py

## tools/
- [x] tools/__init__.py
- [x] tools/cookies_export.py
- [x] tools/video_downloader.py
- [x] tools/video_download_phrases.py
- [x] tools/history_import/__init__.py

## web/
- [x] web/__init__.py
- [x] web/app.py
- [x] web/app.js
- [x] web/index.html
- [x] web/api/__init__.py
- [x] web/api/access.py
- [x] web/api/admins.py
- [x] web/api/avatars.py
- [x] web/api/chat_lore.py
- [x] web/api/config.py
- [x] web/api/direct_chat.py
- [x] web/api/keys.py
- [x] web/api/logs.py
- [x] web/api/oversight.py
- [x] web/api/params.py
- [x] web/api/permissions.py
- [x] web/api/relations.py
- [x] web/api/roles.py
- [x] web/api/status.py
- [x] web/api/system.py
- [x] web/api/usage.py
- [x] web/api/workers.py

## SmartModule/
- [x] SmartModule/__init__.py
- [x] SmartModule/service.py

## tests/
- [x] tests/__init__.py
- [x] tests/conftest.py
- [x] tests/test_*.py (all test files)
## Round 10.20 (T-1915) scan (2026-09-16) — diff-based: БЛОКИ 0–8 эпика `round1020`, HEAD 2f3e1f0 + worktree
- [x] services/canonical_context.py (14 точек, representation/pattern, `strip_context_header`/`format_context_item`/
      `format_chat_time`; pattern `legacy_rag` рассинхронизирован с рантаймом — S10.20-9)
- [x] services/context_middleware.py (header-safe `truncate_keep_header`, `limit<=0` → заголовок; чисто)
- [x] services/lore_compiler_service.py (`_trim` режет header — S10.20-8; `last_ts` обгоняет материал — S10.20-5;
      `_EMPTY_DENSE` shared list — S10.20-15; `_date` UTC — S10.20-14)
- [x] services/reply_postprocess.py (`strip_reasoning_tags`: no-op/парные/незакрытые/лишние — верно; чисто)
- [x] services/tool_loop.py (graceful degradation BLOCK 7.1; NoApiKeyForChat-проброс; PartialText; чисто)
- [x] services/llm_client.py (`reasoning` аддитивно; reasoning-only без LLMBadResponseError; чисто)
- [x] services/direct_chat_service.py (точки 2/3 канона, `_line_markers` header-strip, Time Injection,
      `_send_direct_answer` HTML+фолбэк; per-chat флаг vs роутер — S10.20-2; чанк-дубль — S10.20-10)
- [x] services/database.py (v11→v12 `graph_facts` provenance — идемпотентно/PG no-op; `lore_stories`,
      `persona_dossier_overrides` без бампа; `lore_graph_slice`/`lore_dense_dialogs`; 17/17 `memorize_facts`;
      `dossier_feed` RANDOM — reviewer M3 + S10.20-16)
- [x] services/tool_schemas.py (8 тулов EN, `active_tools`/`factcheck_tools` — новые списки, dict-схемы общие — ок)
- [x] services/tool_router.py (JSON-контракт dig ломается капом — S10.20-3; per-chat флаг — S10.20-2;
      `_LORE_RETURN_INSTRUCTION` в фактчеке — S10.20-4)
- [x] services/factcheck_service.py / services/factcheck_prompts.py (Full Tool Access, DI-kwarg; канон +функц. блоки)
- [x] services/summary_memory.py / summary_generator.py / summary_cleanup.py (6-кортежи R16, ASC после дедупа,
      header-strip токенов, archive-маркер; чисто)
- [x] services/oversight.py (`key_status` 1× вместо 2× — контракт сохранён; чисто)
- [x] services/memory_maintenance.py / manage.py (fsync каталога no-op win32; retention-снапшот;
      `initialize_existing` без проверки схемы — S10.20-13)
- [x] services/status_service.py (per-chat context budget; acct затирает cap — S10.20-7)
- [x] services/param_catalog.py / config/settings.py (каталог 439/92/20, +1 tz-ключ, +1 флаг; Δ санкционирован)
- [x] web/index.html + web/app.js + web/static/app.css + web/api/* (`openModuleWindow`/тумблер/досье/тикер/
      sticky-save; МЕНЮ не изменено; **S10.20-1 [High] — конфиг-вкладки без сохранения**; S10.20-6)
- **Открыто (Round 10.20):**
  - [ ] **S10.20-1 [high, new] BLOCKER** — `web/index.html:170-700`: добавить `<sticky-save>` в ветку
        `currentTabIsConfig` (перед :700) + тест «панель есть в каждой ветке без авто-сейва».
  - [ ] S10.20-2 [medium, new] — per-chat `flags.lore_compiler_enabled` в `tool_router._compile_lore_story`
        и `factcheck_service` (сегодня только глобальный `hot.get`).
  - [ ] S10.20-3 [medium, new] — `dig_into_lore`: усечение секций ДО `json.dumps` (или `truncated: true`).
  - [ ] S10.20-4 [medium, new] — `_LORE_RETURN_INSTRUCTION` не подмешивать вне DirectChat / срезать HTML в фактчеке.
  - [ ] S10.20-5 [medium, new] — `last_ts` считать по фактически включённым в промпт строкам.
  - [ ] S10.20-6 [medium, new] — `saveModalEdits`: не снимать baseline при ошибках сохранения.
  - [ ] S10.20-7 [medium, new] — «Бюджет контекста»: приоритет per-chat cap над `acct.context_limit`.
  - [ ] S10.20-8 [medium, подтверждение reviewer M1–M3] — `_trim` (header), кап скана узлов, `ORDER BY RANDOM()`.
  - [ ] Low: S10.20-9 (pattern `legacy_rag`), -10 (чанк-дубль HTML), -11 (`javascript:` href), -12 (cache),
        -13 (`initialize_existing`), -14 (`_date` UTC), -15 (`_EMPTY_DENSE`), -16 (докстринг fail-open),
        -17 (запись досье moderator'ом).
- **СВОДКА ЭПИКА 10.20: Critical 0 / High 1 / Medium 7 / Low 9 / Info 5.**
  **ВЕРДИКТ: есть Critical/High → возврат к @Builder (S10.20-1), затем повторный ревью UI-фазы (T-1904).**
- Валидатор @Scanner: pytest **6523 passed / 0 failed** (89.52 c); `node --check web/app.js` OK;
  `routing_test.js` + `round1020_ui_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` exit 0; каталог 439/92/20; SQLite v12.

## Round 10.22 (UPD3, 19.09.2026) — diff-based scan (HEAD `acd9311` + worktree); открытых пунктов нет
- [x] services/memory_rebuild.py (F1 confirmed-cleanup: `cleanup_confirmed_dossier_facts`, `_belief_source_set` fail-open — S10.22-1; keyset/JSONL/сверка/guard — ок)
- [x] manage.py (F1 `--target-chat`, `_memory_scope`, CLI per-chat lock, `_memory_exit_code` rebuild_empty — ок)
- [x] services/system2_handoff.py (новый: parse/validate JSON, `contains_system_ids`, `redact_secrets` — ок)
- [x] services/negative_constraints.py (новый: детектор клише + validator-loop ≤2; FP `as_ai` — S10.22-4)
- [x] services/outgoing_guard.py (новый: `sanitize_outgoing`, fail-closed; ReDoS нет — ок)
- [x] services/telegram_send.py (обёртки + SEND_POINTS/SEND_ALLOWLIST; allowlist обоснование voice_transcription — S10.22-3)
- [x] services/dossier_rebuild_jobs.py (новый F8: job-store/lock/снапшот/rollback/раннер; done-empty — S10.22-2; interrupted retention — S10.22-5)
- [x] web/api/chat_lore.py (F8 start/status/latest/cancel; RBAC/R17 — ок)
- [x] web/api/routes.py (`_ensure_keyvalue_object` — ок)
- [x] web/app.js + web/index.html + web/static/app.css (F2 KV, F8 UI, F7 info-стили; flag-OFF кнопка — S10.22-6)
- [x] services/lore_worker.py (F8 user-scoped чанковый rebuild; соседние контуры не тронуты — ок)
- [x] services/direct_chat_service.py / summary_generator.py / factcheck_service.py (two-call + fallback — ок)
- [x] services/info_service.py + config/settings.py + .env.example (канон v4 байт-тест; .env.example — S10.22-7)
- **Открыто (Round 10.22):** нет Critical/High. Non-blocking: S10.22-1/-2 (Medium), S10.22-3/-4/-5/-6 (Low), S10.22-7/-8/-9 (Info).
  Все — `plans/reports/round1022_scanner_audit.md`.


## Round 10.25 F3 `global-scope-selector-round1025` (`76a6c40`), Step 6 @Scanner (21.09.2026) — ⚠️ SUPERSEDED повторным аудитом финальных коммитов (правки `fb49f29`,`4f31197`)

- **Diff `5dcc6bd..76a6c40`.** Отчёт: `plans/reports/round1025_f3_scanner_audit.md`.
- **Итог: Critical 0 / High 0 / Medium 1 / Low 4 / Info 3 — к деплою да.**
- Связи: `web/index.html` (`.scope-wrap`/`.scope-trigger`/`.scope-panel`, `.scope-tech`) → `web/app.js` (`scopeKind`, `configSourceLabel`/`configSourceTitle`/`configItemNotice`, `hasUnsavedEdits`) → `scopeEpoch`/`_scopeGuard` (`loadConfig`, `persistItems`) → `resetChatOverride` → `DELETE /api/config/chat/{key}` (`web/api/routes.py:852`) → `chat_params.set_chat_params` (merge overrides/meta). `web/static/app.css` §70 mobile. `config.settings.APP_VERSION=2.58.6`.
- M-F3-1 (`web/app.js:2472-2482` + `2538`): guard не покрывает `blockDrafts` (llm_providers) — вероятна тихая потеря черновика при смене scope.
- Инварианты: Δ DDL=0, Δ каталога=0 (459), `stash@{0}` цел, zip не в git, `git diff --check`=0. pytest 8142/5/1 (5 — env aiogram InputRichMessageMedia), JS SCOPE-SELECTOR-OK, matrix не воспроизведён (нет playwright).

## Round 10.25 hotfix8 `hotfix8-shell-glass-aurora-round1025` (22.09.2026, Step 6 @Scanner): Critical/High/Medium = 0 → SCANNED
- [ ] **L-H8S-1** [low, new, perf] -- aurora-слой: 5 `.aurora-blob` 52vmax `filter: blur(64px)` + `will-change: transform` анимируют `transform`/`border-radius`; `body::before/after` анимируют `background-position`. Митигации: `lg-bg-paused` (hidden) + `prefers-reduced-motion`. Действие: FPS/батарея на low-end Telegram WebView -- live-гейт **T-2776** (владелец); при провале -- статичный/урезанный blob-слой.
- [ ] **L-H8S-2** [low, new, test-coverage] -- `tools/ui_round1025_matrix.py`: `shellBg` читает root-токен (mobile `.78` не ассертится, только computed панелей); `_hotfix8_failures` `glass=None` = pass; `test_webapp_hotfix6_round1025.py:73` -- drawer-подстрока «где угодно». Действие: позитивный ассерт mobile `.78` + `data-glass="shell"` у существующей панели.
- [ ] **L-H8S-3** [low, new, a11y-margin] -- AA-отчёт `round1025_hotfix8_contrast.md` считает worst-case по одному blob; перекрытие blob/`body::after` (opacity .9) теоретически светлее. Запас 7.33:1 при пороге 4.5:1. Действие: пере-проверка AA в live-гейте **T-2776**.
- Info: I-H8S-1 (APP_VERSION 2.58.10 → bump 2.58.11 в Block G/T-2786); I-H8S-2 (F2-чекер ослаблен намеренно, static-инвариант сохранён `test_f2_checker_rejects_static_background`); I-H8S-3 (`header border-top:0` сбрасывает цвет рамки в currentColor, width 0 -- без действий).

## Round 10.25 hotfix9 `hotfix9-shell-liquidglass-darkaurora-round1025` (22.09.2026, Step 6 @Scanner, UPD3) — NOT READY (High)

- **Diff:** дерево относительно HEAD `b374c0f` (не закоммичено). Отчёт: `plans/reports/round1025_hotfix9_scanner_audit.md`.
- **Итог: Critical 0 / High 1 / Medium 0 / Low 3 / Info 2.**
- [ ] **[H-H9S-1] [high, new, structure, blocking]** `web/index.html:1919–1924` — пропущен `</div>` закрытия `.modal-body` модульной модалки: `footer.modal-actions` внутри `.modal-body`, `.modal-backdrop` неявно закрывается на `</template>` (`:1930`). SaveBar (`position:static`) скроллится с полями (в HEAD была pinned). Проверка: HTML-парсер (ancestor-chain + IMPLICIT-CLOSE) vs HEAD (clean). Фикс: вернуть `</div>` после `:1919`; покрыть модульную модалку в `H9_MODAL_PROBE_JS`.
- [ ] **[L-H9S-1] [low, new, rollback]** `web/static/aurora-flow.js:217–221` — `stop()` не убирает `#aurora-flow-canvas` (застывший кадр при `UI_AURORA_FLOW_V2=OFF`; при OFF+OFF перекрывает `bg-wash-legacy`). Фикс: hide/remove canvas в `stop()`.
- [ ] **[L-H9S-2] [low, new, drift]** `UI_SHELL_V3` без потребителя: `shellV3` (`web/app.js:2450`) не читается шаблоном; флаг всё ещё в `config/settings.py:742`/`/api/me`/`.env.example`. Фикс: deprecated/alias на `UI_SHELL_GRAPHITE_V3`.
- [ ] **[L-H9S-3] [low, new, interaction]** `.status-block` двойная обработка стекла: `data-glass="a"` legacy-lens + цель `glass.js`. Фикс: снять `data-glass` у library-managed целей.
- Info: I-H9S-1 (текст MIT/Unlicense не поставлен — паттерн pre-existing); I-H9S-2 (`glass_prototype_probe.py` — локальный `127.0.0.1`, dev-only).
- **Инварианты OK:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418); `APP_VERSION` 2.58.12; `--shell-texture`=0; CSP same-origin/без CDN+inline+eval; SHA-256 vendored 3/3; нет root package.json; R17/R18; `git diff --check`=0; pytest hotfix9 17/0 + группа 183/0.

## Round 10.25 hotfix9 `hotfix9-shell-liquidglass-darkaurora-round1025` — ПОВТОРНЫЙ аудит (22.09.2026, Step 6 @Scanner, UPD3): H-H9S-1/M-H9R-1/L-H9S-1..3 CLOSED → SCANNED
- [x] **[H-H9S-1] RESOLVED** — `web/index.html:1920` восстановлен `</div>`; парсер: `footer.modal-actions` сиблинг `.modal-body` (0 вложенных, стек пуст); парсер-тест red-on-regression; матрица модульной модалки `modalBody.bottom <= modalActions.y+1` + `stickyInActions=true`.
- [x] **[M-H9R-1] RESOLVED** — `aurora-flow.js:101–122/153–167`: свежий canvas + реальный 2D-контекст при `webglcontextlost`; матрица `mode!=webgl`, `sampleCount>0`, `brightness>=3`.
- [x] **[L-H9S-1] RESOLVED** — `stop()` → `detachCanvas()` (removeChild + renderer.destroy + сброс mode).
- [x] **[L-H9S-2] RESOLVED** — `web/app.js:2462–2468` `shellGraphiteV3 && UI_SHELL_V3` (legacy-алиас, задокументирован).
- [x] **[L-H9S-3] RESOLVED** — `.status-block` без `data-glass="a"` (нет двойной обработки стекла).
- Info (не блокирует): I-H9S-1 текст лицензий vendored; I-H9S-2 `glass_prototype_probe.py` dev-only localhost; I-H9S-3 `scrollActiveModalField` на visualViewport scroll — низкий риск джанка, live-наблюдение.
- **Прогоны @Scanner:** `node --check` OK; JS hotfix7/8/9 OK; `py -3 -m pytest -q` **8291 passed / 0 failed**; `git diff --check`=0; Δ DDL=0; Δ каталога=0 (459/98/96/21/418); `APP_VERSION` 2.58.12; CSP/`--shell-texture`/`backdrop-filter:url(` инварианты OK; R17/R18 OK.

## Round 10.25 hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` (22.09.2026, Step 6 @Scanner, UPD4) — SCANNED (блокеров нет)
- [ ] **[L-H10-1] [low, new, visual]** `web/index.html:3271-3272` — статичный `<div class="glass-surface" data-glass-surface>` (`web/static/app.css .glass-surface { height:44px }`) остаётся в сетке «Статус» и при `UI_LIQUID_GLASS_LIB=OFF` (прод-default): `mountedCount=0`, `surfaceCount=1` → ~44 px + grid-gap пустого места над карточкой. Фикс: `.glass-surface:not([data-lg-mounted="1"]){display:none}` либо `v-if` на флаг. Не блокирует (визуальный follow-up).
- Info: I-H10-1 OFF-проба матрицы (`_h10_glass_off_failures`) не ассертит скрытие placeholder (`surfaceCount` не проверяется) → L-H10-1 не ловится; I-H10-2 Playwright-матрица @Scanner не перезапускалась (опора на @Builder `failures:0`).
- **Прод-дефект белых прямоугольников УСТРАНЁН:** `glass.js` единственная цель `[data-glass-surface]`; флаг default OFF; функциональные цели (`.scope-trigger/.header-fs-btn/.status-block`) стекла не получают; `--glass-paper` тёмный только на `.glass-surface`; `backdrop-filter:url(`=0; vendored same-origin/CSP.
- **Инварианты OK:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418; `param_catalog.py` не тронут); флаги env-only ∉ REGISTRY; `APP_VERSION` 2.58.13 синхронен; `--shell-texture`=0; маркер-тесты не ослаблены; R17/R18 (тег `pre-round1025-hotfix10`, `stash@{0}`); `git diff --check`=0; индекс без `.env`/zip/скриншотов/`tools/_ui_*`.
- **Совместимость:** IA F1/роуты, F4 §60, F5 §61, F0, F9, F3, ADR-1024-24, flex/графит §63, сердцебиение — не тронуты; второй safe-area снят; `.more-sheet` один offset; Main без полосы; `__AuroraFlow.resize` вызывается на resize/fullscreen/viewport; режим честный `frosted`; unmount идемпотентен.
- **Прогоны @Scanner:** `node --check` OK; JS `HOTFIX10-GLASS-GEOMETRY-BG-OK`; целевые pytest **166 passed**; полный `pytest -q` **8314 passed / 0 failed**.

## Round 10.25 hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` — ПОВТОРНЫЙ аудит (22.09.2026, Step 6 @Scanner, UPD4): H-1/L-H10-1/L-1/L-2 CLOSED → SCANNED
- [x] **[H-1] RESOLVED** (High @Reviewer) — `web/static/app.css` `main.scroll-area { grid-auto-rows: max-content; }`; матрица @Scanner `failures:0`, `.status-block` `scrollH==clientH` (320:567/567, 360:532/532, 390:508/508, 430:508/508 + 768–2560) и fullscreen; `elementFromPoint` `.hb-canvas`/`.status-block__bot`/`.status-block__server` — `self=true`; дизайн сердцебиения не тронут; гейт `_h10_status_card_failures` не вакуумный.
- [x] **[L-H10-1] RESOLVED** (Low @Scanner) — `web/index.html` `v-if="liquidGlassLib"` на `[data-glass-surface]`; OFF-проба `surfaceCount==0` (320/360/390/430/1280); `test_lh101_placeholder_hidden_when_off`.
- [x] **[L-1] RESOLVED** — `glass.js::clearAttrs` снимает `data-glass`/`data-uid`/`data-render`/`data-glass-motion`/`data-ps-loupe` + inline `--g-*` (`removeProperty`); node-юнит fake-DOM → dispose → атрибуты/пропы пусты (`test_l1_clear_library_attrs_and_inline_props`).
- [x] **[L-2] RESOLVED** — `.env.example`: `UI_LIQUID_GLASS_LIB (default OFF)` + `[data-glass-surface]`, устаревший текст убран (`test_l2_env_example_actual`).
- Info (не блокирует): I-H10-2 закрыт перезапуском матрицы @Scanner (`failures:0`); live Telegram WebView — PENDING OWNER VERIFICATION.
- **Инварианты OK:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418); `APP_VERSION` 2.58.13; CSP same-origin/0 внешних; `--shell-texture`=0; `backdrop-filter:url(`=0; маркер-тесты не ослаблены; R17/R18 (тег `pre-round1025-hotfix10`, `stash@{0}`); `git diff --check`=0.
- **Прогоны @Scanner (повтор):** `node --check` OK; JS `HOTFIX10-GLASS-GEOMETRY-BG-OK`; полный `pytest -q` **8319 passed / 0 failed**; матрица **failures: 0**.
