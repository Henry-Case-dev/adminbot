# Review — A3 `unified-image-request-round1026` (повторный единый Reviewer gate T-3580/T-3581; линза 1 requirements/correctness + линза 2 focused change audit; Scanner удалён намеренно)

- **Feature-ID:** `unified-image-request-round1026` (Эпик 3 «Agentic Intelligence», Wave 2, Раунд 10.26; §18 «Генерация изображений» / §19 «Прямой вызов и tool calling» / §20 «Единый image request» / §21 «Tool calling генерации изображений»; P0)
- **Risk-Level:** **R3** (не понижен: меняется рантайм-семантика **разделяемых** модулей живого direct-чата `services/image_generation.py` / `services/tool_router.py` / `services/direct_chat_service.py` при двух Critical KG-рисках — `Risk-a3-unproven-root-cause`, `Risk-a3-direct-path-regression`; причина §21 остаётся недоказанной).
- **Status: Approved** — обе линзы пройдены независимо; **release-блокеры `[B-1]` (High) и `[B-2]` (Medium) закрыты** документальным rework T-3580 (spec/ADR amend @Architect + `threat-failure-analysis.md` @Builder); правок product-кода не потребовалось. Critical = 0, High = 0, блокирующих Medium = 0. Вердикт — **feature gate**: одобряет включение A3 в pending epic-release Эпика 3; **деплой не авторизует** (`DEFERRED_TO_EPIC`, `EPIC_ONLY`).
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f` (HEAD == `origin/master`; annotated-тег `pre-round1026-a2` tag-obj `a3ea44d` → `e8646af`; **A3-коммитов/тега нет**; рабочее дерево — pending epic-release candidate: незакоммиченный A2 + A3)
- **Working-Tree-Hash:** `29e8da0a7a7e404bc9dfc3c6f414bd0f620379fdb6d3bd4c16ca90a14781bd46`
  - Рецепт (детерминированный, как S6–S10/A0–A2): SHA-256 манифеста (UTF-8; строки соединены LF + завершающий LF) =
    - строка `git-diff e8646af sha256=4c58755083de114c9033f640ddf7d5c17af0a6857de08ceecfb1c14fb7d9954d` (SHA-256 **сырых байт** stdout `git diff e8646af -- . ":(exclude)plans/MEMORY.md" ":(exclude)plans/workflow_state.md"`; ролевые `plans/MEMORY.md`/`plans/workflow_state.md` — Orchestrator/Memory — **исключены**; запись этого gate в `plans/reports/audit_backlog.md` **включена**)
    - + по строке `<путь> sha256=<hash>` для каждого untracked-файла (**14 шт.**, сортировка, POSIX-пути), **кроме** `plans/features/unified-image-request-round1026/review.md` (сам отчёт)
  - Per-file (SHA-256, lowercase): `spec.md` `a98d20d15a382c172eb07a762cb8eea3273eb757f7f6fc125615d137f057e9e2`, `adr-1026-16-…md` `53fe38c266e3513fa1465c2cb220ceaa945170ceb8850032dfa8e77c18d68f0c`, `tasks.md` `7268f22f3fa80ed807794d3753462ab317d0d6ba753279d9ed21be0ef6cf99a7`, `evidence.md` `659e9a238998cffeb383856f24cee3d293e043e213e09a9fc2a99ac30f585e27`, `image-diagnostics.md` `edb0e282d6a33df3e8a697907dc40417cdad90ffb9d734eba2ef40977440614b`, `threat-failure-analysis.md` `e4ffbc0c936546685f317f3c8fae57f8bcdcb4fd9af0411af26efa8095faf7de`, `tests/test_unified_image_request_round1026.py` `35878a72b9d5fb44b24d3e2a32a347209cdb78153e66b2fd624cd7e334b6a120`.
- **Spec-Hash:** `a98d20d15a382c172eb07a762cb8eea3273eb757f7f6fc125615d137f057e9e2` (полный SHA-256 `spec.md`; совпал с заявленным @Architect). ADR-1026-16 — `53fe38c2…` (совпал).
- **Binding связан с текущим состоянием worktree:** любая последующая правка product code / relevant untracked-файлов / `spec.md` делает вердикт устаревшим и требует пересчёта. A3-коммитов и пер-фича тега нет (`EPIC_ONLY`).

## 1. Git base и фактический объём изменений (линза 2)

- **База:** `e8646af` == `origin/master`; annotated-тег `pre-round1026-a2` → `e8646af`. Коммитов A3 нет, HEAD не двигался. R18: теги `pre-round1026-a0/a1/a2` + `s1…s10` + `visual` целы; `stash@{0}` (round1025) на месте; пер-фича тега A3 нет.
- **Product-код НЕ изменился с прошлого gate (ключевое подтверждение):** SHA-256 сырых байт `git diff e8646af` (без ролевых `MEMORY`/`workflow_state`) на момент начала этого gate = `6df003c3b3e4cb2a2d35e78314aca9ad1ed8d13b0876072dd8b8b655f51f27ef` — **байт-идентичен** значению предыдущего gate. Diff-stat product-путей совпал: `image_generation.py` +106, `tool_router.py` +168, `tool_schemas.py` +117, `tool_loop.py` +280, `direct_chat_service.py` +19, `smartmodule_urls.py` +21, `config/settings.py` +22, `bot.py` +6 (A2+A3, без изменений).
- **Rework T-3580 затронул только документы** (untracked-файлы фичи): `spec.md` (SC-A3-05/§3/§7/§10), `adr-1026-16-…md` (D1 AMEND/D11/D9-note), новый `threat-failure-analysis.md`. `tasks.md`/`evidence.md`/`image-diagnostics.md` — **без изменений** (хеши совпали с прошлым gate).
- **Untracked (15, в манифест вошли 14 — кроме `review.md`):** архив A2 `plans/archive/tool-chains-round1026/**` (6), `plans/features/unified-image-request-round1026/**` (7, из них review.md исключён), `tests/test_tool_chains_round1026.py`, `tests/test_unified_image_request_round1026.py`.
- **Зависимости:** манифесты/локи вне diff — **0 новых зависимостей**.

## 2. Выполненные проверки (независимо воспроизведено @Reviewer)

| Проверка | Команда/метод | Результат |
|---|---|---|
| Полный регресс | `.venv\Scripts\python.exe -m pytest tests/ -q` | **9156 passed, 0 failed** (155.53 с) — заявленное 9156/0 подтверждено |
| JS (47 файлов) | цикл `node tests/js/*.js` | **OK=47, FAIL=0** |
| `git diff --check` | — | **exit 0** (только CRLF-предупреждения) |
| Каталог / версия / канон | импорт `config.settings`/`tool_schemas`/`param_catalog` | `APP_VERSION` **2.58.30**; `TOOL_CALLING_TOOLS` = **11**, `generate_image` — 9-й; REGISTRY **469**; `UNIFIED_IMAGE_REQUEST_ENABLED` ∉ REGISTRY; ∉ `dataclasses.fields(Settings)` (426 полей) |
| Product-код без Δ | SHA-256 сырого `git diff e8646af` | `6df003c3…` — **идентичен** прошлому gate |
| Тест-набор A3 | `Select-String 'def test_'` | **31 тест**, имена/строки совпали с заявленными |
| Анкоры `file:line` | выборочная сверка `image_generation.py`/`tool_router.py`/`direct_chat_service.py`/`tool_schemas.py`/`settings.py` | совпали (`:202/227/246/256/890/993/1047/1063`, `tool_router:425/446/1559/1579–1590/1597`, `direct_chat:938–939/967–968`, `tool_schemas:329/350/390–393/427`, `settings:899–904`) |
| R18/теги | `git tag -l`, `git stash list`, `git log e8646af..HEAD` | теги/`stash@{0}` целы; A3-коммитов нет |

## 3. Линза 1 — требования/correctness (факт)

- **REQ-A3-01 / SC-A3-01 (§18/§20, единый механизм) — OK.** Оба входа строят `ImageRequest` и сходятся в единственный раннер `run_image_request` → **существующий** `generate_and_send`; второго pipeline/генератора нет.
- **REQ-A3-02 / SC-A3-02 (§18/§19, без регрессий) — OK.** `build_final_prompt` = `extract_prompt`; ON≡OFF по вызову генератора; OFF — legacy без `ImageRequest`.
- **REQ-A3-03/-04 / SC-A3-03/-04 (§19, контекст условен) — OK.** `context_required=False`, `context_sources=[]`, `resolved_subjects=[]`; RAG/досье/память не читаются.
- **REQ-A3-05 / SC-A3-05 (§21, диагностика) — OK (B-1 CLOSED).** `spec.md:233` (SC-A3-05) требует **документированный** вердикт по каждой HY-01…HY-06 (`подтверждено`/`опровергнуто`/`INCONCLUSIVE` с блокером и планом проб); ветка `INCONCLUSIVE` из-за недоступности билд-окружения описана в `spec.md:73–74/208–213`; **фикс на недоказанной причине по-прежнему запрещён** (`spec.md:72/213/225/233`); owner-гейт прод-проб зарегистрирован `PENDING OWNER VERIFICATION` (`spec.md:215–223`, `adr:40–46/98`). ADR D1 AMEND фиксирует вердикты (HY-06 подтверждена; HY-03 env-слой опровергнут; HY-01/02/04/05 — `INCONCLUSIVE`), согласованные с фактами `evidence.md` §1 / `image-diagnostics.md` §2.
- **REQ-A3-06/-07/-08 / SC-A3-06/-07/-08 (§21) — OK.** Структурированные аргументы; fail-closed `_require_str`; вызов существующего генератора; возврат через reuse A2-envelope; реальный `reason` доводится, «отказ модели» не подставляется.
- **REQ-A3-09 / SC-A3-09 (§20, нет двойной генерации) — OK.** forced `image_enabled=False` + авторитетный маркер `ToolContext.image_request_handled`, проверяется первым делом → `{"status":"skipped","reason":"already_handled"}` без генерации/бюджета; `<image_result>`-guard сохранён.
- **REQ-A3-10 / SC-A3-10…-14 (границы/инварианты) — OK.** §104 без изменений (AST-гейт); Δ DDL=0; Δ каталога=0; env-only киль-свитч; 2-вызовность; REUSE ExecutionGraph; deploy = DEFERRED.
- **Ложных закрытий не обнаружено.**

## 4. Линза 2 — focused change audit (факт)

- **Δ DDL=0** (`db/**` вне diff); **Δ каталога=0** (REGISTRY 469; `UNIFIED_IMAGE_REQUEST_ENABLED` — env-only `ClassVar`, ∉ REGISTRY и ∉ `dataclasses.fields(Settings)`).
- **Версия не бампалась:** `APP_VERSION` **2.58.30** (bump 2.58.31 — в агрегатном релизе Эпика 3).
- **0 новых зависимостей; CSP/zero-build** (манифесты/локи/`web/**` вне diff).
- **2-вызовность** `await_count==2` сохранена (полный прогон).
- **R17:** логи только `reason`/`reason_class`/`mode`/`model`/`attempt`/`chat`/`source`/длины; тест `test_failure_logs_are_codes_only`.
- **B-2 CLOSED — `threat-failure-analysis.md`:** присутствует, **11 угроз** (≥8) в формате «угроза → механизм → код (file:line) → тест/доказательство»; покрыты **все 8 обязательных** угроз spec §10 п.1 (двойная генерация T1; регресс прямого T2; второй pipeline T3; подмена ошибки T4; недоказанный фикс T5; R17-утечка T6; дубль контрактов T7; регресс 2-вызовности T9) + T8 (исключение в цикле), T10 (bound-гейты), T11 (недоступность проб). Выборочная сверка `file:line` и ссылок на 31 тест — **совпала**; доказательства воспроизводимы (тесты проходят в полном прогоне).

## 5. Counterexamples / adversarial (проверено, не гипотезы)

| # | Сценарий | Проверка | Результат |
|---|---|---|---|
| 1 | Двойная генерация (ключевик + tool) | `test_loop_double_trigger_is_one_generation` (полный `chat_with_tools`) | OK — ровно одна генерация, tool-роль `skipped`, бюджет не списан |
| 2 | Маркер при OFF-киль-свитче | `test_marker_off_legacy` | OK — legacy-поведение |
| 3 | Битые/пустые аргументы | `test_missing_prompt_fail_closed` | OK — `status:error`, генерации нет, цикл жив |
| 4 | Модуль OFF | `test_module_off_error_and_no_generation` | OK |
| 5 | Ошибка генератора в середине | `test_error_enters_loop_as_tool_role` | OK — реальный `reason`, envelope reuse |
| 6 | Подмена ошибки «отказом модели» | `test_generator_reason_is_surfaced` | OK — реальный `reason`, текст без «модель» |
| 7 | Утечка промпта/ключа/URL (R17) | `test_failure_logs_are_codes_only` | OK |
| 8 | OFF ≠ baseline | `test_direct_on_same_prompt_as_legacy`, `test_direct_off_no_image_request` | OK |
| 9 | §104 drift | `test_104_generator_functions_ast_identical` + полный прогон | OK |
| 10 | Δ DDL/каталога/версия ≠ 0 | независимые прогоны | OK — 0/0/2.58.30 |
| 11 | SC-A3-05 без вердиктов HY | spec/ADR/evidence сверка | OK — вердикты документированы, `INCONCLUSIVE` с блокером/планом, owner-гейт |
| 12 | Ремонт затронул product-код | SHA-256 `git diff e8646af` | OK — идентичен прошлому gate |

## 6. Блокирующие findings

**Нет.** `[B-1]` (High) и `[B-2]` (Medium) — **CLOSED** (rework T-3580):

- **[B-1] [High] — CLOSED.** @Architect внёс AMEND D1 + ветку `INCONCLUSIVE` (недоступность билд-окружения) в `spec.md` SC-A3-05/§3/§7 и ADR-1026-16 D1/D11; **фикс на недоказанной причине по-прежнему запрещён**; owner-гейт прод-проб (HY-01/02/04/05, per-chat) зарегистрирован `PENDING OWNER VERIFICATION`. Вердикты согласованы с `evidence.md`/`image-diagnostics.md`. Правок product-кода не требовалось.
- **[B-2] [Medium] — CLOSED.** @Builder создал `plans/features/unified-image-request-round1026/threat-failure-analysis.md` (11 угроз; полнота, соответствие `file:line`, воспроизводимость — подтверждены).

## 7. Non-blocking debt (прозрачно зарегистрировано)

- **[L-R1026A3-1…-5] (Low/Info, прежние):** AST-docstring упоминает `reason_class` вне набора гейта; `maybe_handle_keyword`/`<image_result>` не AST-гейтится; `test_kill_switch_off_restores_legacy_via_env` хардкодит `C:\Code\Python\adminbot`; tool-путь нормализует prompt через `extract_prompt`; `_classify_output` трактует `skipped` как envelope `ok`+`metered`.
- **[L-R1026A3-6] (Low, doc-only, новый):** `tasks.md` инвариант 5 (стр. 64) сохранил формулировку «диагностика HY-01…HY-06 **доказательна**» до amend; рекомендуется @PM реконсилировать с переформулированным SC-A3-05 при merge/архивации. Не блокирует: авторитетный приёмочный критерий — `spec.md` SC-A3-05, он допускает документированный `INCONCLUSIVE`.
- **[L-R1026A3-7] (Low, doc-only, новый):** `image-diagnostics.md` §1.3 (и ADR/spec) содержат устаревшие `file:line` логов генератора; фактически `services/image_generation.py:890`/`:993`.
- **[L-R1026A3-8] (Low, doc-only, новый):** `evidence.md` §1 использует метку «НЕПОДТВЕРЖДЕНО / НЕ ОПРОВЕРГНУТО» вместо `INCONCLUSIVE`; ADR AMEND формально мапит термины — несоответствия по существу нет.

## 8. Вердикт по remediation (ключевой вопрос)

**Оба блокера сняты документально; product-код не менялся; новых блокеров нет.**

1. **B-1:** `spec.md`/ADR теперь содержат легитимную ветку `INCONCLUSIVE` (блокер + план проб), owner-гейт зарегистрирован, и — критично — **фикс на недоказанной причине остаётся запрещён**; реализованная часть (унификация §18/§20 + страховки) от нераскрытой причины не зависит. Это ровно то корректирующее действие, которое требовал предыдущий gate.
2. **B-2:** обязательный R3-артефакт создан, полнее минимума (11 ≥ 8), с проверяемыми `file:line` и тестами; воспроизводимость подтверждена полным прогоном.
3. **Risk-Level остаётся R3** (причина §21 не доказана; меняется разделяемый контур живого direct-чата) — понижение до R2 не выполнялось и не требуется.

## 9. Unavailable checks

- **Живые прод-пробы HY-01/HY-02/HY-04/HY-05** (реальный `chat/completions` с активным прод-набором `tools`; journald `[image] generation failed`/`attempt failed │ reason_class=`; grep `[provider rejected tools]`; живая A/B описания) — **владелец/оператор**, owner-гейт **`PENDING OWNER VERIFICATION`** (билд-окружение неэквивалентно проду).
- **Per-chat `flags.image_generation_module_enabled`** (PG-каталог) — недоступен с билд-машины; владелец.
- **Live-прогон §18–§21 на проде** — вне этого gate; **DEFERRED_TO_EPIC** (агрегатный Reviewer gate на границе Эпика 3).
- **Деплой** — не выполнялся и не должен (EPIC_ONLY, `DEFERRED_TO_EPIC`); @DevOps не вызывался.

## 10. Handoff

- **@Orchestrator → `Approved` (feature gate; линзы 1/2 пройдены независимо; B-1/B-2 CLOSED; Critical = 0; блокирующих Medium = 0).**
- Далее: **reconcile/архивация** — @Architect merge `plans/ARCHITECTURE.md` §85 + ADR-1026-16 → Accepted → @PM архивация с `deployment: DEFERRED_TO_EPIC` → handoff к следующей фиче Эпика 3 (A4–A5).
- **Deploy/DevOps не вызывать** до границы Эпика 3 (`EPIC_ONLY`). Отдельный Scanner-отчёт **не создаётся** (Scanner удалён намеренно; его обязанности — линза 2 этого gate).
- Binding: Reviewed-Commit `e8646af`, Working-Tree-Hash `29e8da0a…`, Spec-Hash `a98d20d1…`; любая последующая правка product code / relevant untracked-файлов / `spec.md` делает вердикт устаревшим.
