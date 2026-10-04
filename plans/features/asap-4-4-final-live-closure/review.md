# ASAP 4.4 — review.md (Independent Reviewer, gate T-4885)

## 1. Вердикт

**Approved** для кандидата: uncommitted working tree на HEAD `04e615d`; привязка — WTH-манифест Reviewer: `plans/reports/asap44_wth_manifest_review.txt` (файлов 80; рецепт в §6, HEAD `04e615da9b9e03d056658ca7f02cc334089b4fec`). Любая правка файла из манифеста (кроме review.md) инвалидирует это ревью.

Одно не блокирующее, но обязательное следствие — **F-N1 (F8/pg_db-пины, Medium)**: выполняется отдельным bounded micro-round Builder'а (ровно 3 файла, §5 Special Q1), не задерживает деплой T-4886: дрифт появился из уже закоммиченного 2.58.51, кандидат его не ухудшает.

Пост-ревью: **live Canary A / Canary B / GraphRAG controlled repro НЕ запускались Reviewer'ом — они обязательны после деплоя по §9 (T-4887 / T-4888 / T-4889 `[REAL]`, DevOps/Orchestrator) и являются обязательным условием закрытия 4.4 (§0.8, §10 DoD)**. Моки вместо 4.4 live-acceptance недопустимы (§11).

## 2. Что запущено Reviewer'ом самостоятельно (exact counts)

| Проверка | Команда (repo root, `.venv\Scripts\python.exe`) | Результат |
|---|---|---|
| Cover focused (§6 #1–#13 + E2E T-4884) | pytest tests/test_asap44_cover_final_closure.py -q | **19 passed / 0 failed** |
| Hybrid Summary L2 (§6 #14–#18 + 3 named-механизма) | pytest tests/test_asap44_l2_review_closure.py -q | **8 passed** |
| GraphRAG batch breaker + quota groups (§6 #19–#24 + 21b + catalog/UI) | pytest tests/test_asap44_graphrag_batch_breaker.py -q | **11 passed** |
| Affected legacy batch (реальный Z1–Z3-периметр) | pytest tests/test_asap43_cover_style_surgical.py tests/test_extra_cover_style_registry.py tests/test_extra_cover_style_jobs.py tests/test_extra_cover_styles_api.py tests/test_cover_styles_contract_asap32.py tests/test_cover_style_wave_b_asap4.py tests/test_asap42_step3_style_integration.py -q | **162 passed / 0 failed** |
| F8/pg_db pin-набор | pytest tests/test_round1025_f8_registry.py tests/test_budget_data_repair_round1024.py tests/test_budget_guardrails_round1024.py -q | **3 failed / 82 passed** — ровно 3 pg_db/DDL-пина (см. Special Q1); каталог-пины на 489 зелёные (test_delta_catalog_zero: 489/105/103/21) |
| JS | node --check web/app.js; node tests/js/asap44_cover_final_closure_test.js | OK / OK (exit 0) |
| RED-spot (§8-б) | `git worktree add --detach %TEMP%\opencode\wt44red 04e615d` + копия 3 новых test-файлов → pytest (cover/l2/graphrag) | cover **13 failed / 6 passed** (RED: cover4/5/6/7/8/10 + e2e + все Z4 #11–#13); L2 **5 failed / 3 passed**; GraphRAG **6 failed / 5 passed**; worktree удалён, `git worktree prune` |
| Гейты L2 (инварианты) | чтение файла: MAX_REVISIONS=2 / MAX_REVIEWS=3 / CALL_BUDGET_L2_STAGE=6 | не тронуты |
| Диффы | full read of service/web diff + 3 обновлённых legacy-теста + новые тест-файлы | см. §3/§4 |

Полный suite НЕ запускался (§11); heavy 4.3 mobile-geometry не перезапускалась (файлы не затронуты).

## 3. Обязательные ответы §8 (а)–(з)

- **(а) Почему 4.3-тесты не поймали RC-A/RC-E.** RC-A: у 4.3 не было real-GET-проверки через registry/API (unit-моки стора вместо реального маршрута), а live Canary A остался `PENDING OWNER` — поэтому 404 на before-asset проявился только на проде (Canary A repeat 4.3: GET before 404). В 4.4 закрыто E2E real backend-path + negative control + live-пруф (2.58.51; job `cov_77f2347eec7d85e6b3a15f93`). RC-E: suite 4.3 сам кодифицировал сломанный контракт — `test_extra_cover_style_registry.py` декларировал `revision+1` на каждый UPDATE и display «ВЫПУСК 00» (старый §66), т.е. assert'ы предписывали дефект; плюс не было цепочки save→reload. Тесты не могли «поймать» то, что сами предписывали. В 4.4 добавлены честные тесты #4–#10 + UI/JS-тест.
- **(б) Новые тесты реально RED на pre-fix или эквивалентно доказаны.** Да, метод: temp `git worktree add --detach <tmp> 04e615d` + копия новых test-файлов, без runtime-правок → cover 13 failed / 6 passed; L2 5 failed / 3 passed; GraphRAG 6 failed / 5 passed. Совпадает с декларациями Builder (7 failed/5 passed core + 6 Z4; 5; 6). Green на overwritten-части (cover1–3, cover9, negative control, #12e, #18, #21b, #23–#24) — это инварианты/уже-починенное (RC-A fix в проде 2.58.51).
- **(в) Counter-семантика едина (ONE contract UI/API/DB/production).** `registry.next_issue_number() = counter_value+1` (DB internal = last_assigned) → API `_public_profile` отдаёт `next_issue_number` (compat `counter_value` = 1:1, совместим); editor подписывает «Следующий номер» на `next_issue_number`; POST сохранить N → `_counter_value_from_body` пишет `counter_value = N−1`; production `resolve_issue_number` — атомарный `+1 RETURNING` (=N) + per-run assignment (`cover_style_issue_assignments`), retry того же run получает прежний N (функция НЕ тронута и теперь согласована с UI). `-1` НЕ размазан: единственные точки — `_counter_value_from_body` и `next_issue_number` (grep). Лестница 11→11→retry 11→next 12 — test_cover5 (мой ран, PASS).
- **(г) Test Style НЕ расходует номер.** Preview-джоба вызывает run_style_job без `summary_run_id`; allocation требует run-id → не вызывается; в preview-диагностике `issue_number=None`; counter после Test Style не меняется (test_cover4 — PASS в моём run). `preview_issue_display` теперь показывает current next_issue_number (zero-pad 2), не hardcoded `00`.
- **(д) Prompt-limit fallback не есть скрытый paid-loop.** `run_style_job`: ровно ≤1 bounded retry и ТОЛЬКО если recompiled реально короче (`len(...) < len(...)`; иначе skip="not_shorter" без пересылки); minimal-компиляция сбрасывает P2/P3 (refs/brief), сохраняет P0/P1 (номер выпуска, запрет дублей, style-instruction, base-style) — test_cover12 assert'ы это проверяют; success → `record_runtime_safe_ceiling` (source `runtime_safe`, НЕ понижает known exact/manual); повторный too-long → honest `prompt_limit_unknown_after_retry` (не generic bad_request); test_cover12e закрывает known-N→unknown-ветку (ровно 2 paid call, третьего нет). Manual override сохраняет высший приоритет (`_apply_manual` не понижается `SOURCE_RUNTIME_SAFE`), test_cover11 проверяет persistence. Классификация 400 без числа → `prompt_limit_unknown` (`looks_like_prompt_too_long`, cover_style_edit.py), с числом («shorten … to N chars») → `prompt_limit` (runtime_exact; добавленный regex — не hardcode).
- **(е) L2 Reviewer не ослаблен.** Verdict-flow/строгость/budget не тронуты; MAX_R/MAX_REV/CALL_BUDGET = 2/3/6 (grep in-file). Толерантный targeted-парсер (`_normalized_target_anchors`) не меняет verdict: anchors валидируются той же anchor-картой, неизвестные отбрасываются (fail-closed через §99-валидацию документа), pinned `output_format` в targeted-prompt; `needs_fixes` НЕ превращён в auto-approve (test #18 зелёный). Deterministic findings пересчитываются от current validated doc перед каждой review-итерацией (`_deterministic_findings_from_metrics(current_doc_metrics)` + `_revalidate_metrics` тем же единым валидатором) — test #14/#15 зелёные. Stage events: whitelist `_STAGE_EVENT_KEYS` расширен ровно диагностическими полями (R17: коды/числа/id, без текстов/промптов) — test #16.
- **(ж) GraphRAG cooldown не маскирует unexpected.** `_is_serviceability_error` ловит ТОЛЬКО `EmbeddingGroupCoolingDown` + `EmbeddingBudgetExhausted` (control-plane serviceability). Batch breaker: первое доказанное state → `embedding_unavailable_for_batch`; далее факты text-only без повторных embed-попыток; batch завершается ОДНИМ concise WARN (chat/source/quota_group/state/next_allowed_at/facts_text_only/dedup_vector_skipped) — test #19–#21. Unexpected exception (RuntimeError и пр.) по-прежнему per-fact warning **со stacktrace** (test #21b, зелёный в моём run). Query-пути: известные serviceability-состояния → coalesced INFO + FTS-fallback; прочие классы → WARNING+со stacktrace, не глушились. `EmbeddingConcurrencyBusy` НЕ включён (transient, повторный attempt осмысленный).
- **(з) Нет unrelated MCA changes.** Дифф соответствует зонам Z1–Z6 + тестам + F8-переизданию + новым test-файлам. `plans/metrics.md` / `plans/docs/mca-round1027-arch-frames.md` — незакоммиченный backfill старых раундов 10.27–10.31 (в diff нет ни asap-4-4, ни T-48xx; grep-подтверждение; разведено pre-existing, не 4.4). `plans/features/asap-4-3-cover-style-surgical/canary-evidence.md` — файл активного 4.3-canary-агента (писался не 4.4-сессией), 4.4-Builder его не трогал; в review-манифест не включён (read-only). `plans/workflow_state.md` — Orchestrator-область (NOTE 15). Семантика cover-зоны вне задач 4.4 не менялась (диффы затрагивают только Z-контракты): диффы затрагивают только описанные контракты (display/save/preview/resolve/revision), старые geometry-файлы не правлены.

## 4. Findings

| # | Sev | Место | Проблема | Evidence | Blocking |
|---|---|---|---|---|---|
| F-N1 | **Medium** | tests/fixtures/round1025/f8_baseline.json:59 (+ tests/test_budget_guardrails_round1024.py:419; tests/test_budget_data_repair_round1024.py::test_delta_ddl_zero) | 3 red pg_db/DDL-пина: fixture sha256 `4cb889fa…` vs текущий pg_db.py `86fc88af15ab7c50e0b544718d8afe76155d9ffefcf215d0890c27f70c9f9f8c`; DDL 53 vs pin 52 | мой запуск §2 (3 failed/82 passed); sha256-вычисление; `git diff HEAD -- services/pg_db.py` пуст → reproduced on base HEAD; last-change commit `1c47b5e` (2.58.51) | **No** (pre-existing от закоммичённого 2.58.51; runtime не затрагивает; на другие пины не влияет) |
| F-N2 | Low | services/summary_l2_review.py `_revalidate_metrics` | Validator-исключение → findings = `{}` (fail-open на hint-уровне); вердикт/budget/§99-валидация не затронуты | code read | No |
| F-N3 | Low | web/api/cover_styles.py `_promote_preview_requested` + upsert promote-path | Микро-окно между promote-check и promote-UPDATE при параллельном Test Style completion (self-heal на следующем Save/Test Style; fingerprint/asset-match гейты препятствуют недопустимому pair) | декларация Builder (evidence §9 residual); мой code-read | No |
| F-N4 | Low | services/image_capabilities cache TTL 900 s | UI и runtime делят route-кэш — смена маршрута у провайдера до ~15 мин видна как старая (у runtime этот TTL был и раньше) | code read | No |
| F-N5 | Info | untracked debris (`node_modules/`, `package*.json`, `.playwright-mcp/`, `tools/_ui_asap43_*.png|json`, `plans/verification_cache.json`) | Вне ревью-манифеста; при коммите НЕ стейджить (commit-hygiene tasks.md T-4866) | git status | No |

Current-блокеров нет.

## 5. Special questions — решение

### Special Q1 — 3 red F8/DDL pin tests (pg_db.py HEAD ↔ fixture; DDL 53 vs pin 52)
Классификация: **(b) real drift от санкционированного закоммиченного триггера (2.58.51 `1c47b5e`/`acbbe1f` — PG additive `preview_job_id`), НЕ known-noise CRLF-класс** (drift не composition; подтверждено sha256 + git-trace). Диспозиция: **обязательный bounded micro-round (re-issue)** — санкция CI-гигиены, НЕ блокер для T-4885/деплоя (пины тест-гигиена; runtime не затронут; каталог-часть F8 перепроверена и зелёная). Пины desynced ещё с 2.58.51 — исторический прецедент «pre-existing red, толерировано до re-issue» есть в раундах (напр. «2 failed known» базовых якоря).
**Один bounded rework — ровно 3 файла:**
1. `tests/fixtures/round1025/f8_baseline.json` — поле `"sha256"["services/pg_db.py"]` → `86fc88af15ab7c50e0b544718d8afe76155d9ffefcf215d0890c27f70c9f9f8c` (+ counts-блок не трогается).
2. `tests/test_budget_guardrails_round1024.py` (≈:419) — pin 52 → **53** + комментарий-санкция (прецедент A5: 45→46; ASAP-3.2: 51→52 уже виден в файле).
3. `tests/test_budget_data_repair_round1024.py` (`test_delta_ddl_zero`) — 52 → **53**.
Recheck после микрораунда: rerun этих 3 файлов → 0 failed; затем обновить WTH-манифест (пины входят в него).

### Special Q2 — catalog delta +1
**Sanction подтверждена.** Ровно +1 ключ: `keys.embedding_quota_group_labels` (REGISTRY 488→489; test_delta_catalog_zero == 489/105/103/21, пройден в моём pin-run; delta 411→78). Non-secret: в param_catalog tuple secret-флаг = False; значение — только `alias:group` labels; UI идёт через тот же masked keys-API путь (tsv/screen-map), никакого самого ключа; независимость групп считается только из label, не из значений ключей (`resolve_quota_group` не читает key bytes). Санкция владельца — прямая из SoT §5.3 (26929–26948) + T-4880 (owner-настройка в существующей Embeddings-группе MiniApp, без нового generic-config фреймворка). F8 re-issue (489/delta 78) оформлен корректно (tsv/meta/screen-map/fixtures/42 файла update) и подтверждён прогоночно (82 passed pin-suite, включая каталог-пин на 489).

### Special Q3 — residual Builder-риски
- **promote-race window** (Test Style completion параллельно Save): **acceptable-with-note** (F-N3, Low). Окно — длительность одного Save; content-consistency защищена fingerprint/asset-match гейтами; worst-case self-heal (следующий Save/Test Style явно перезапишет). Отдельный version-guard в этом bounded pass не требую.
- **route-TTL 900 s (общий cache UI/runtime):** **acceptable-with-note** (F-N4, Low). Это тот же кэш, что был у runtime раньше; UI теперь показывает те же данные, что исполняет runtime — единая модель, а не два независимых контура.

### Special Q4 — deploy/live preconditions (T-4886/T-4887), что DevOps должен подтвердить
1. **manual 800 override ABSENT:** Builder-пруф — live §7.2 попытка manual-override НЕ персистилась (HTTP 422 на старом sync-слоте), снимать нечего. Проверка после деплоя: UI «Ограничение промпта» = auto; bot_settings/manual-limit записи для nano-gpt.com/qwen-image-3-pro отсутствуют (§11 запрещает blind-800 на Pro).
2. **«next = 11» достижим новым UI-контрактом:** в редакторе установить «Следующий номер» = 11 → API пишет `counter_value = 10`, читает `next_issue_number = 11`; prod DB напрямую не править. Проверка в Canary A: Test Style рисует «ВЫПУСК 11», после теста next остаётся 11.
3. Нынешний deploy: PG-DDL НОВЫХ в 4.4 нет (preview_job_id уже в проде 2.58.51); SQLite ΔDDL = 0; после рестарта — health + version/commit в `deployment.md`; R17-мониторинг; Inspector/логи — только run/job id без текстов/секретов.
4. График live: Canary A (T-4887) → Save/reopen → Canary B (T-4888, issue 11 / retry 11 / next 12 / [`styled`, не `base_fallback`]) → GraphRAG controlled repro (T-4889): отсутствие warning storm + quota topology (keys/groups/rotation/next_allowed_at) видна без секретов.

## 6. Binding

WTH recipe (Reviewer-generated, 1:1 конвенция 4.3): заголовок `WTH-MANIFEST asap-4-4-final-live-closure (Reviewer T-4885) | HEAD=04e615da9b9e03d056658ca7f02cc334089b4fec | files=80 | generated=<UTC>Z` + CRLF-строки `path|size_bytes|SHA256` (sha256 от содержимого файла, UTF-8, пути отсортированы). Файлы манифеста: **12 services** (cover_style_edit/jobs/pipeline/preview/registry, embedding_control_plane, execution_graph_source, image_capabilities, param_catalog, summary_l2_anchor_repair, summary_l2_review, summary_memory) + **3 web** (web/api/cover_styles.py, web/app.js, web/index.html) + **59 tests** (все git-modified тесты + 4 новых asap44 py/js + 2 fixtures/round1025) + **6 plans-docs** (4.4 packet: evidence/requirements/tasks + F8: param-registry-round1025.tsv, param-registry-round1025.meta.md, screen-map-round1025.md). review.md в манифест не включён (self-reference). Не часть binding'а (вне change-blast-radius или вне 4.4): `workflow_state.md` (Orchestrator), `metrics.md`/`mca-round1027-arch-frames.md` (pre-existing backlog backfill), 4.3-пакет (read-only active canary), node_modules/, .playwright-mcp/, package*.json, tools/_ui_asap43_*.

## 7. Residual notes / передача Orchestrator

- Обязательное post-deploy §9: **Canary A (T-4887), Canary B (T-4888), GraphRAG controlled repro (T-4889) — `[REAL]`, их НЕ выполнил Reviewer и НЕ может заменять моками; закрытие 4.4 (DoD §10) недопустимо до их успешного исхода и записи job/run id в evidence.md §3/§4/§6.**
- F-N1 follow-up: первый rework micro-round (3 файла, §5 Q1) → rerun 3 pin-файлов → пересоздать WTH.
- После релиза: legacy/compat `counter_value` поле остаётся 1:1 (одна внутренняя точка контракта, а не «Следующий номер»); без миграции.
- Архивирование 4.4 и возврат к MCA — только после live acceptance по планам Z10/Z11 (T-4890).
- R17: в ревью НЕТ секретов/ключей/полных URL/raw-text/промптов — только коды, числа и file:line.

## 8. Дополнение — F-N1 закрыт (recheck bounded rework, 05.10.2026)

Микрораунд Builder: ровно 3 файла по назначению T-4885/F-N1:
1. `tests/fixtures/round1025/f8_baseline.json` — `sha256["services/pg_db.py"]`: `4cb889fa…` → **`86fc88af15ab7c50e0b544718d8afe76155d9ffefcf215d0890c27f70c9f9f8c`** (полный sha256 независимо пересчитан Reviewer по bytes — совпадает). Counts 488→489/77→78 в этом файле — часть основного reviewed-state (Z6 F8 reissue), не микрораунд; файл перезаписан целиком (63/63) — допущенный CRLF-rewrite-шум (класс-прецедент 10.27-REL `c5cb5a9`), значения семантически верные.
2. `tests/test_budget_guardrails_round1024.py` — DDL-pin 52 → **53** + комментарий-санкция (прецедент уже в файле: A5 45→46, ASAP-3.2 51→52).
3. `tests/test_budget_data_repair_round1024.py` — DDL-pin 52 → **53** + комментарий.
Прим.: оба test-файла дополнительно лишились BOM в первой строке (byte-level, безвредно; тот же rewrite-класс).

Проверка Reviewer (самостоятельно):
- diff против reviewed-manifest-state: изменены ТОЛЬКО эти 3 файла (+ `evidence.md` — собственное заполнение §8 Reviewer; вне Builder-контроля). Все остальные 80 позиций манифеста по sha256 без изменений, missing=0.
- rerun 3 pin-файлов: `pytest tests/test_round1025_f8_registry.py tests/test_budget_data_repair_round1024.py tests/test_budget_guardrails_round1024.py -q` → **85 passed / 0 failed** (было 82 passed / 3 failed).
- `git diff HEAD -- services/pg_db.py` остаётся пустым: пины догнали закоммиченный 2.58.51-drift; runtime не менялся.

Обновлённый биндинг: `plans/reports/asap44_wth_manifest_review.txt` — HEAD `04e615da9b9e03d056658ca7f02cc334089b4fec` | files=80 | generated=20261005T032942Z | sha256(manifest)=75E9AEAD96F64B9D0F8BA67DA67ECA3F64C63CE00409BECC608418F773F7C0F1. Аддендум пере-привязывает кандидата: предыдущий манифест устарел.

**Вердикт не меняется: Approved.** Live-канарейки §9 остаются обязательными (T-4886…T-4889).

## 9. Дополнение — F-N2 закрыт (recheck skip-ahead, 05.10.2026)

Дельта на базе deployed `329e6de` (prod 2.58.52; вся 80-файловая reviewed-state 4.4 зафиксирована коммитами `09fd5a8`/`1a6b5ba` и задеплоена). Builder изменил ровно 4 файла (проверено по diff HEAD + манифест-сверке):
1. `services/cover_style_registry.py::resolve_issue_number` — skip-ahead: atomic `counter_value+1 RETURNING` (row-lock PG сериализует параллельные allocations) → bounded loop (`_MAX_ISSUE_SKIP_STEPS=1000`) по занятым номерам до первого свободного N′ → `counter_value = N′` (last_assigned) той же транзакцией; retry того же `summary_run_id` — прежний N′ (проверка до инкремента); cap исчерпан → откат increment (counter не расходуется) + WARN, None; занятые номера (и ниже counter) не переиспользуются. Логика минимальна; контракт `next_issue_number = counter_value+1` и save-N/Test-Style-no-spend не менялись. PG-concurrency: сериализация на row-lock делает окно между чтением occupied и INSERT безопасным; revert-cap-percansummed безопасен по той же блокировке.
2. `tests/test_asap42_step3_style_integration.py` — shim-DDL + `UNIQUE INDEX (profile_id, issue_number)` = зеркало prod (fidelity; не construction-new).
3. `tests/test_asap44_cover_final_closure.py` — +2 теста F-N2 (helpers `_assign_issue`/`_fetch_assigned_numbers`): фикс (Test Style counter не тратит, reload durable).
4. `plans/features/asap-4-4-final-live-closure/evidence.md` — §2a (pre-fix RED, counts) + §11 live-acceptance лог (docs-only).
Вне дельты (пре-existing backlog churn, вне биндинга): `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/workflow_state.md` (Orchestrator).

Проверка Reviewer (самостоятельно):
- asap44 cover-файл: **21 passed** (19 прежних + 2 F-N2).
- registry+jobs: **74 passed**; 4.3 delta + contract: **26 passed**; shim-consumers (step3 + step2c2): **27 passed**; общий прогон всех 6 файлов единой командой → **127 passed** (= 74+26+27, совпадает с Builder).
- RED spot-check: worktree на чистом `329e6de` + копия нового тест-файла → `test_issue_allocation_skips_occupied_numbers` **FAILED (:381 — allocation вернул занято-вперёд 11, механизм live-дефекта)**; `test_issue_allocation_picks_first_free_gap` passed (candidate 11 свободен; green допустимо pre-fix). RED подтверждён вне Builder-прогона. worktree удалён.

Обновлённый биндинг: `plans/reports/asap44_wth_manifest_review.txt` — HEAD `329e6deae31345b6cb6f8fb5943277547e6ed0ad` | files=6 | generated=20261005T045310Z | sha256(manifest)=EB02F3E9E9492B869270D0D64045F5463E4466629F5840275F3405B7CB24B897. Формат/рецепт прежние (header + CRLF `path|size_bytes|SHA256`); файлы: registry + 2 теста + 3 пакачечных док (всегда bound); остальная reviewed-state — в коммитах/деплое `09fd5a8`/`1a6b5ba`. Аддендум пере-привязывает кандидата.

Вердикт остаётся: **Approved**. ПРИМЕЧАНИЕ ДЛЯ ОРКЕСТРАТОРА/DEVOPS: фикс F-N2 НЕ задеплоен (prod 2.58.52 без skip-ahead) — deploy этой дельты перед Canary B re-run (per evidence §2a); live Canary A/B/GraphRAG отчёты §11 теперь в evidence — их полная сверка остаётся за Z10-gate.
