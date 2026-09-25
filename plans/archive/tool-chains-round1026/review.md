# Review — A2 `tool-chains-round1026` (единый Reviewer gate T-3545/T-3546; линза 1 requirements/correctness + линза 2 focused change audit; Scanner удалён намеренно)

- **Feature-ID:** `tool-chains-round1026` (Эпик 3 «Agentic Intelligence», Wave 2, Раунд 10.26; §15 «Последовательные tool calls» / §16 «Контракты инструментов» / §17 «Ограничение цепочек»; P0)
- **Risk-Level:** **R3** (подтверждён фактическим diff: меняется рантайм-семантика **разделяемого** `services/tool_loop.py` живого direct-чата, вводится out-of-band envelope-контракт результата, контроль потока цепочки (cap/тайм-аут/дедуп/расходы) и **+1 инструмент канона** 10→11; обратимо env-OFF kill-switch'ами + annotated-тег. Понижение до R2 не выполнено — понижение требовало бы доказанной полной аддитивности без изменения базового control-flow, а изменения вносятся в общий механизм.)
- **Status: Approved** — Critical/High/блокирующих Medium = **0**; обе линзы пройдены независимо; R3-усиленные доказательства достаточны. `Approved` здесь — **feature gate**: разрешает включение A2 в pending epic-release candidate Эпика 3; **deploy НЕ авторизует** (release policy **EPIC_ONLY**, `deploy = DEFERRED_TO_EPIC`).
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f` (HEAD == `origin/master`; annotated-тег `pre-round1026-a2`, tag-obj `a3ea44d41cd497956928e5adf8545b1549cc7b9c` → `e8646af`; правки A2 **НЕ закоммичены**)
- **Working-Tree-Hash:** `f1f1d54464a15f37f0514264e16ebf842a20b8619f3157df125c98555bb158f5`
  - Рецепт (детерминированный, как S6–S10/A0/A1): SHA-256 манифеста (UTF-8; строки соединены LF + завершающий LF) =
    - строка `git-diff e8646af sha256=07126e3351c68f6667cd328b00f94433ca55b60068f0925450ea855319c68e7e` (SHA-256 **сырых байт** stdout `git diff e8646af -- . ":(exclude)plans/MEMORY.md" ":(exclude)plans/workflow_state.md"`; ролевые `plans/MEMORY.md`/`plans/workflow_state.md` — Orchestrator/Memory — **исключены из A2-манифеста**, см. D-c; запись этого gate в `plans/reports/audit_backlog.md` **включена**)
    - + по строке `<путь> sha256=<hash>` для каждого untracked-файла (сортировка, POSIX-пути), **кроме** `plans/features/tool-chains-round1026/review.md` (сам отчёт)
  - Per-file (SHA-256, lowercase): `spec.md` `e87e530f2e367d4524f059f32ada1c15ece681950a23054bb1b0b5940fd7cefe`, `adr-1026-15-…md` `0bd5b3ceda5b2774065a80186d069c31e698ffea21353dd2a20402b91e6f9c56`, `tasks.md` `eaadb1be61b2656062e9063ad16a9da2376e657c79f8ea363f66c9f42c9690b6`, `evidence.md` `73b80c38044372b6a7c98cc90b30722505cf187bc385a95e347b2b7b72f9572e`, `threat-failure-analysis.md` `8564c3ccf1dfda037657da15853ba19ce23b1c0d5a78bb9baa9b10b12ffdecd9`, `tests/test_tool_chains_round1026.py` `deb7ee77e0c559082fcf03787065f55da0cebd04f91f043b392fc4086bc1eb61`.
- **Spec-Hash:** `e87e530f2e367d4524f059f32ada1c15ece681950a23054bb1b0b5940fd7cefe` (полный SHA-256 `spec.md`; совпал с ожиданием после micro-amend `E87E530F…`). Правок `spec.md`/ADR/`tasks.md` этим gate **не было**.
- **Binding связан с текущим состоянием worktree:** любая правка product code / relevant untracked-файлов / `spec.md` после этой фиксации делает approval устаревшим и требует пересчёта.

## 1. Git base и фактический объём изменений (линза 2)

- **База:** `e8646af` == `origin/master`; annotated-тег `pre-round1026-a2` (obj `a3ea44d` → `e8646af`) — проверено `git rev-parse`/`git cat-file`. Коммитов A2 нет.
- **Трекинг-дифф (20 файлов, `git diff --stat e8646af`):** `bot.py` (5+/1− — только аддитивная DI-строка `extractor=_web_extractor`), `config/settings.py` (+2 env-only `ClassVar`), `services/{direct_chat_service,smartmodule_urls,tool_loop,tool_router,tool_schemas}.py`, 11 `tests/*.py` (re-pin канона 10→11), ролевые `plans/MEMORY.md`/`plans/workflow_state.md` (Orchestrator/Memory, **не A2**). Всего +595/−86.
- **Untracked:** `tests/test_tool_chains_round1026.py`, `plans/features/tool-chains-round1026/**` (spec/ADR/tasks/evidence/threat-analysis).
- **Вне diff (независимо проверено пустым `git diff --name-only e8646af -- …`):** `services/image_generation.py` (§104), `services/summary_prompts.py`, `services/prompt_migrations.py`, `services/param_catalog.py` (Δ каталога), `db/**`, `web/**`, `web/api/routes.py`, `plans/current_task.md`, манифесты/локи зависимостей.
- **Зависимости:** diff манифестов/локов — **пусто** (0 новых).
- **R18 цел:** annotated-тег `pre-round1026-a2` → `e8646af`; бэкап `var/backups/a2-round1026-20260924-173812/` (BASELINE.md, pytest.log, config/services-снапшоты); `.env.bak.round1026-a2`; `stash@{0}` (round1025) — на месте.

## 2. Выполненные проверки (независимо воспроизведено @Reviewer)

| Проверка | Команда/метод | Результат |
|---|---|---|
| Полный регресс | `.venv\Scripts\python.exe -m pytest -q` | **9125 passed, 0 failed**, 1 warning (154.13 с) — заявленное 9125/0 (+43) подтверждено |
| A2-набор | `pytest tests/test_tool_chains_round1026.py -q` | **43 passed** (2.64 с) |
| Канон/2-вызовность/границы прошлых фич | `pytest tests/test_tool_schemas.py tests/test_direct_two_call_round1022.py tests/test_summary_deploy_round1026.py tests/test_summary_publish_integration_round1026.py tests/test_tool_calling_round1015.py tests/test_agentic_ai_round1020.py -q` | **202 passed** (48.95 с) |
| JS (47 файлов) | цикл `node tests/js/*.js` | **OK=47, FAIL=0** |
| `git diff --check` | — | **exit 0** (только CRLF-предупреждения) |
| Канон / гейты / каталог / версия | импорт модулей | `TOOL_CALLING_TOOLS` = **11** (fetch_article в хвосте), `factcheck_tools` = **3**, `active_tools()` default = **10** (image OFF), каталог **469/100/98/21**, `APP_VERSION` **2.58.30** (без bump) |
| Δ DDL | grep `CREATE/ALTER/DROP TABLE|CREATE INDEX` в `git diff services/` | **0** |
| Запрещённые пути | `git diff --name-only e8646af -- …` | **пусто** (§104/промпты/`param_catalog.py`/`db`/`web`/`routes.py`/`current_task.md`/манифесты) |
| Дедупликация сервиса | `git grep "WebContentExtractor("` | product code — **только** `bot.py:419` (тот же инстанс, что web-модуль); второй extractor не создан |
| `asyncio.gather` | `git grep` в `tool_loop.py`/`tool_router.py` | **0** (последовательность санкционирована D4) |
| **OFF vs baseline (R3 rollback)** | собственная проба @Reviewer: `git show e8646af:services/tool_loop.py` vs текущий при `TOOL_CHAIN_LIMITS_ENABLED=False`, 4 сценария | **ALL EQUAL** — `str`/`tool_context`/`tool_trace`/`reason`/`degraded`/модельно-видимые сообщения/вызовы роутера идентичны |

## 3. Линза 1 — требования/correctness

- **REQ-A2-01/-02 (SC-A2-01/-02) — OK:** зависимые A→B исполняются **существующим** последовательным многораундовым `tool_loop` (`services/tool_loop.py:240…`; модельный выбор инструментов, `tool_choice='auto'`); результат A возвращается моделью ролью `tool` и доступен B; программный handoff — общий `ctx.result_for(name)` (`services/tool_router.py:456–468`). Зависимые — всегда последовательно; `asyncio.gather` отсутствует. Тест `test_dependent_chain_a_then_b_sequential` (B читает envelope A).
- **REQ-A2-03/-09 (SC-A2-03/-09) — OK:** per-phrase/per-combination обработчиков нет; механизм инструмент-агностичный (`test_no_per_phrase_handler` — 2 разные пары без хардкода). Контекстный резолв ссылки — общий `smartmodule_urls.resolve_context_url(*texts)` (`:44–62`; текущее сообщение → reply; 0 URL → `None`; ровно 1 уникальный → он; ≥2 разных → `None`/честный `no_url`, без угадывания). `direct_chat_service` передаёт `resolved_url` в `ToolContext` (`:946–959`).
- **REQ-A2-04/-05 (SC-A2-04/-05) — OK:** §16-контракт каждого из **11** инструментов — `spec.md` §6 + `TOOL_FETCH_ARTICLE` (§16-поля); envelope (гибрид D1) строится на **каждый** вызов во **всех** ветке (`parse-error`/`dedup`/`skip`/`dispatch`) и пишется в `ToolLoopResult.tool_results` + `ctx.tool_results`; модельно-видимый канал (`role:"tool"`-content, `tool_context`) и ключи `tool_trace` **не изменены** (`test_envelope_recorded_on_every_call`, `test_model_visible_channel_unchanged`, `test_tool_loop_result_reuse_additive`).
- **REQ-A2-06 (SC-A2-06) — OK:** ошибки структурированы (`status:error` + `error_code`/`error_type`, в т.ч. из JSON `status:error` и «ОШИБКА …»); ошибка одной инструмента **не** превращается в общий отказ LLM — цикл продолжается (`test_structured_error_does_not_kill_llm`, `test_structured_error_from_json_status`, `test_adversarial_mixed_errors`).
- **REQ-A2-07 (SC-A2-07) — OK:** cap **6** / мягкий тайм-аут **360 c** (in-flight не отменяется) / дедуп **≤2** / платные **≤4** / частичный результат с `chain_timeout`/`chain_call_limit`/`chain_cost_limit` (`TestLimits` — 12 тестов, включая шторм дубликатов и soft-timeout). Внешний `TOOL_MAX_ROUNDS=4` × ≤2/раунд — цикл гарантированно завершается.
- **REQ-A2-08 (SC-A2-08) — OK:** параллельность не введена; последовательность **санкционирована** ADR D4 и обоснована (архитектура не concurrency-safe); `test_no_asyncio_gather_in_chain_sources`.
- **REQ-A2-10 (SC-A2-10/-11/-12/-13) — OK:** reuse существующей архитектуры (`tool_loop`/`ToolRouter`), 0 новых LLM-вызовов, канон расширен атомарно (схема+регистрация в хвост+метод роутера+`active_tools`+DI+тесты), Δ DDL=0/Δ каталога=0, §104/§85-UI вне diff, REUSE ExecutionGraph (вторая аналитика не создана), OFF/legacy-эквивалентность, 2-вызовность `await_count==2`.
- **Ложных закрытий не обнаружено:** каждое заявление @Builder подтверждено кодом/тестом/независимым прогоном (см. §2/§5).

## 4. Линза 2 — focused change audit

- **Δ DDL=0:** 0 DDL-хитов в A2-источниках; `db/**` вне diff.
- **Δ каталога=0:** `param_catalog.py` вне diff; счётчики **469/100/98/21**; kill-switch'и `TOOL_CHAIN_LIMITS_ENABLED`/`ARTICLE_TOOL_ENABLED` — env-only `ClassVar`, не в `REGISTRY`/не поля `Settings` (`test_kill_switches_not_in_catalog`).
- **Версия не бампалась:** `APP_VERSION` **2.58.30** (EPIC_ONLY → bump 2.58.31 в агрегатном релизе Эпика 3).
- **0 новых зависимостей:** манифесты/локи вне diff.
- **CSP/zero-build:** `web/**` вне diff.
- **2-вызовность:** `tests/test_direct_two_call_round1022.py` passed (`await_count==2`).
- **R17:** A2-логи — только `source`/`chars`/`truncated`/`reason`/имена/числа; envelope (`data` с сырым URL/Markdown) **нигде не логируется и не сериализуется** (grep: `tool_results` встречается только в `tool_loop.py`/`tool_router.py`); `test_fetch_article_url_not_logged`, `test_no_payload_in_logs`, `test_degraded_log_r17_safe`.
- **R18:** тег/бэкап/`.env.bak`/`stash@{0}` целы.
- **Целостность assertions:** 11 тест-файлов канона — только обновления счётчика/имени/порядка; assertions не ослаблены, кроме **двух** historical boundary-тестов (см. D-a).

## 5. Counterexamples / adversarial (проверено, не гипотезы)

| # | Сценарий | Проверка | Результат |
|---|---|---|---|
| 1 | Костыль под фразу/пару | `test_no_per_phrase_handler` (2 разные пары) | OK |
| 2 | Зависимые параллелятся | grep `asyncio.gather` = 0 | OK |
| 3 | Неструктурированный handoff | envelope на каждый вызов; B читает A через `ctx.result_for` | OK |
| 4 | Ошибка инструмента = общий отказ LLM | `test_structured_error_does_not_kill_llm`, `test_adversarial_mixed_errors` | OK |
| 5 | Бесконечный цикл / шторм дубликатов | `test_total_call_cap_six`, `test_adversarial_duplicate_storm` | OK |
| 6 | Тайм-аут режет in-flight | `test_soft_timeout_does_not_cancel_inflight` (результат сохранён) | OK |
| 7 | Битый URL / недоступный источник | `TestFetchArticle::test_extraction_failure_structured`, `test_no_url_is_honest_error`, `test_fetch_article_timeout` | OK |
| 8 | Неоднозначная ссылка | `test_resolve_context_url_ambiguous_returns_none` | OK |
| 9 | Гигантский вывод + усечение | `test_adversarial_huge_output_truncation_flag`, `test_truncated_flag_when_capped` | OK |
| 10 | OFF ≠ baseline | **независимая проба vs baseline-код** (4 сценария) | OK |
| 11 | 3-й LLM-вызов / регресс 2-вызовности | `await_count==2` | OK |
| 12 | Δ DDL/каталога скрытно ≠ 0 | подтверждён 0 | OK |
| 13 | Утечка URL/аргументов в логи (R17) | `test_fetch_article_url_not_logged`, grep `tool_results` | OK |

## 6. Вердикты по отклонениям @Builder

- **[D-a] `bot.py` (аддитивная DI-строка) + ослабление 2 boundary-тестов прошлых фич — ДОПУСТИМО, non-blocking, документировано.**
  - Факт: @Builder убрал `bot.py` из `tests/test_summary_deploy_round1026.py::TestBounds::test_forbidden_paths_unchanged` и `tests/test_summary_publish_integration_round1026.py::TestBoundaries::test_forbidden_paths_outside_diff` (они запрещали любые правки `bot.py` относительно тегов `pre-round1026-s10`/`pre-round1026-s6`). Причина: A2 санкционированно (ADR-1026-15 D5) добавляет в `bot.py` **одну** DI-строку `extractor=_web_extractor` (reuse `WebContentExtractor` — тот же инстанс, что у web-модуля, без дубля сервиса).
  - Независимая проверка @Reviewer: `git diff e8646af -- bot.py` = **ровно** 5 вставок/1 удаление (DI + комментарий); других изменений нет; запрещённые пути не затронуты.
  - Классификация: **не fix, не spec amend** (изменение тестов чужих фич — следствие санкционированного cross-feature изменения; факт подтверждён). Рекомендация (Low, non-blocking): при merge добавить компенсирующий ассерт «diff `bot.py` ограничен санкционированной DI-строкой» либо явно зафиксировать исключение в §84/ADR.
- **[D-b] `_ARTICLE_MAX_SYMBOLS = 8000` — реализационная деталь, НЕ drift, non-blocking.** `spec.md` §6 и ADR D5 фиксируют «усечение max_symbols» и per-tool `_ARTICLE_TOOL_TIMEOUT=45.0`, но не число; 8000 — bounded-выбор @Builder (между `_SEARCH_MAX_SYMBOLS=4000` и `_SUMMARIZE_TRANSCRIPT_CAP=20000`), усечение честно отражается в `truncated`/`chars`. Классификация: **не fix, не spec amend**; рекомендация — @Architect зафиксировать число при merge (§84).
- **[D-c] `plans/MEMORY.md`/`plans/workflow_state.md` — не A2, исключены из A2-манифеста.** Diff — ролевые баннеры Memory и машинный блок Orchestrator (rev 66→72, phase=review); этот gate их не создавал и не менял (машинный блок — только через `workflow_checkpoint`). Подтверждено по содержимому diff.

## 7. Достаточность R3-доказательств — **достаточно**

1. **Threat/failure-анализ** (`threat-failure-analysis.md`): **14 угроз** → механизм (код) → тест; adversarial-таблица (12 сценариев) — все PASS. Покрывает Critical-KG-риски `Risk-a2-infinite-call-loop`/`Risk-a2-live-chat-regression` и High `Risk-a2-phrase-hack-per-combination`/`Risk-a2-unstructured-handoff`.
2. **Rollback-доказательство** — **усилено @Reviewer**: помимо ON≡OFF внутри одного кода (заявление @Builder), независимо воспроизведена **эквивалентность baseline-коду** (`git show e8646af:services/tool_loop.py` vs текущий при `TOOL_CHAIN_LIMITS_ENABLED=False`) в 4 сценариях — побайтовое совпадение `str`/`tool_context`/`tool_trace`/`reason`/`degraded`/модельно-видимых сообщений/вызовов роутера. Эффективный канон при `ARTICLE_TOOL_ENABLED=false` = **10** (тест `test_off_legacy_effective_canon_ten`). Hot/cold-процедуры и тег зафиксированы.
3. **Расширенная adversarial-приёмка + diff-аудит:** `TestLimits`/`TestFetchArticle`/`TestR17AndBoundaries` + независимые пробы §2 — зелёные; Δ DDL/каталог/§104/§85-UI/ExecutionGraph/канон подтверждены.

## 8. Блокирующие findings — **нет**

Critical = 0; High = 0; requirement-/architecture-blocking Medium = 0. Отклонения D-a/D-b/D-c — non-blocking (§6).

## 9. Non-blocking debt

- **[L-R1026A2-1] [low, coverage/tests, non-blocking] — OPEN:** два historical boundary-теста (`test_summary_deploy_round1026.py`, `test_summary_publish_integration_round1026.py`) удалили `bot.py` из списка запрещённых путей; отдельного ассерта «diff `bot.py` ограничен санкционированной DI-строкой» нет. Фактический diff проверен @Reviewer вручную. **Fix:** @Architect при merge (T-3547) добавить компенсирующий ассерт либо зафиксировать исключение в §84/ADR (doc-only).
- **[L-R1026A2-2] [info, docs, non-blocking] — OPEN:** число `_ARTICLE_MAX_SYMBOLS=8000` не зафиксировано в spec/ADR (D-b). **Fix:** @Architect при merge зафиксировать значение в §84/ADR (doc-only).
- **[L-R1026A2-3] [low, robustness, non-blocking] — OPEN:** в ветке ошибки парсинга аргументов (`tool_loop.py` path (а)) `total_calls`/`metered_calls` инкрементируются без проверки cap; поведение ограничено внешними `TOOL_MAX_ROUNDS=4` × ≤2/раунд (инфинити-луп невозможен), но метрика «суммарных вызовов» учитывает и неуспешный парсинг. **Fix:** по желанию — вынести счётчик фактических диспетчей отдельно (при следующем касании).

## 10. Unavailable checks

- **Live-прогон §15–§17 на проде** (реальный трафик/цепочки инструментов, фактическая доставка direct-чата) — вне этого gate; **DEFERRED_TO_EPIC** (проверяется агрегатным Reviewer gate на границе Эпика 3, в составе агрегатного релиза).
- **Прод-`.env`/фактическое состояние kill-switch'ов** — намеренно не читалось; hot-OFF-проверка — часть эпик-деплоя (@DevOps).
- **R-1 (300 c vs 360 c)** — закрыт авторитетным значением **360.0 c** (ADR-1026-15 D3 + `spec.md` §7 согласованы; реализовано 360.0). Не является unavailable-риском.

## 11. Handoff

- **@Orchestrator → APPROVED (feature gate; единый Reviewer gate: линза 1 + линза 2 пройдены; Critical/High/блокирующих = 0).**
- Далее: reconcile/архивация — **T-3547** @Architect merge (`plans/ARCHITECTURE.md` §84 + ADR-1026-15 Accepted; учесть L-R1026A2-1/-2 как doc-only рекомендации) → **T-3548** @PM архивация в `plans/archive/` с `deployment: DEFERRED_TO_EPIC`.
- **Deploy — DEFERRED_TO_EPIC** (release policy EPIC_ONLY): T-3549 исполняется на границе Эпика 3 под **агрегатным** Reviewer gate (bump 2.58.30 → 2.58.31, §114-проверки, манифест/порядок/откат эпика). Затем — следующая фича Эпика 3 (A3/A4 §18–§25), handoff T-3550.
- Отдельный Scanner-отчёт/approval **не создаётся** (Scanner удалён намеренно; его обязанности — в линзе 2 этого gate).
- Binding: Reviewed-Commit `e8646af`, Working-Tree-Hash `f1f1d544…`, Spec-Hash `e87e530f…`; любая последующая правка product code / relevant untracked-файлов / `spec.md` делает approval устаревшим.
