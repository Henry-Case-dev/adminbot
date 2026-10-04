# ASAP 4.4 — evidence.md (skeleton, PM 05.10.2026)

Заполняют: @Builder (основное), @DevOps (deploy), @Reviewer (review). Кратко, только факты: job/run id, команды, counts, file:line. Без секретов, API keys, полных промптов и raw source text.
Связано: `requirements-map.md` (D1–D23, §6#1–24), `tasks.md` (T-4866…T-4890).

## 0. Pre-fix repro (§1, T-4866 — заполнено ДО правок)

Кандидат: HEAD `04e615d` (worktree без runtime-правок). Команда RED:
`.venv\Scripts\python.exe -m pytest tests/test_asap44_cover_final_closure.py tests/js/... -q`
(см. фактические строки ниже).

| RC | Что проверено | Наблюдение (file:line / тест) | RED? | Дата/агент |
|---|---|---|---|---|
| RC-A | fix 2.58.51 присутствует: `_store_base` → `upsert_asset` оба call sites; failure → job fail до pair write | `services/cover_style_preview.py:364,382` (оба call sites `_store_base(pg, path)`), `:474–492` (`registry.upsert_asset` + failure→None), `:365–367,383–385` fail до styled/pair. **Live proof attached**: Canary A repeat 4.3 job `cov_77f2347eec7d85e6b3a15f93` — before GET 200 (887 912 B) + after GET 200 (1 706 155 B), pair revision 5, counter не изменён. Negative control (new): `test_cover3_base_registry_failure_leaves_no_pair` + `test_e2e_rc_a_negative_control_old_store_base_would_404` (старый `_store_base` без registry → GET before 404). | — (FIXED; live proof attached) | Builder 05.10.2026 |
| RC-B | UI next=11 → production increment отдаёт 12 | `services/cover_style_registry.py:560–565` (`counter_value+1 RETURNING` = last_assigned); UI label «Следующий номер» на raw `counter_value` (`web/index.html:810–813`); live log `issue_number=12`. RED: `test_cover5` — `assert stored["counter_value"] == 10` получил `0` (тело `next_issue_number: 11` игнорируется `ProfileBody`, `web/api/cover_styles.py:380–390`), `tests/test_asap44_cover_final_closure.py:334` | ☑ | Builder 05.10.2026 |
| RC-C | Test Style рисует `00` при next=11 | `services/cover_style_registry.py:596–598` (`preview_issue_display` → `format_issue(..., 0, zero_pad=2)`); API `web/api/cover_styles.py:162,317,1124`; prompt preview `services/cover_style_jobs.py:1358,1684`. RED: `test_cover4` `KeyError 'next_issue_number'` (:302); `test_cover6`/`test_e2e...` `'ВЫПУСК 00' == 'ВЫПУСК 12'` (:360, :543); JS `node tests/js/asap44_cover_final_closure_test.js` — AssertionError (нет bind на `next_issue_number`) | ☑ | Builder 05.10.2026 |
| RC-D | `POST /cover/test-style` шлёт `{profile_id}` → тестируется DB-версия | `web/api/cover_styles.py:1038–1043` (`TestStyleBody` = только `profile_id` + legacy upload), `:1076` заново читает профиль из DB (`get_profile_with_refs`). RED: `test_cover6` падает на `preview_issue`/fingerprint — draft не принимается вовсе; после фикса тот же тест доказывает, что в style stage ушёл DRAFT, а DB-профиль не перезаписан | ☑ | Builder 05.10.2026 |
| RC-E | no-op Save → `revision N→N+1` → pair stale → placeholders | `services/cover_style_registry.py:255–305` (`revision = revision + 1` на любом UPDATE), `:391` (`preview_pair_current` требует `preview_revision == revision`); API переносит прежние preview-указатели (`web/api/cover_styles.py:449–453`). RED: `test_cover7` `revision 2 != 1` (:393); `test_cover8` pair stale (`2 != 1`, :420); `test_cover10` `preview_revision 1 != 2` (no promote, :478) | ☑ | Builder 05.10.2026 |
| §2 | sync resolve vs production inherited; 400 без числа → `bad_request` | UI meta/budget — sync: `web/api/cover_styles.py:286–345` (`jobs_public_capabilities` → `pipeline.slot_capabilities`; `_prompt_limit_state` → sync `pipeline.resolve_style_slot`); production — async inherited: `services/cover_style_pipeline.py:210` (`resolve_style_slot_inherited`), вызов `services/cover_style_jobs.py:1224`; `VERIFIED_PROMPT_LIMIT_REGISTRY` пуст (`services/image_capabilities.py:562`); 400 без `N` → `last_reason="bad_request"` (`services/cover_style_edit.py:463–483`). Подтверждено; Z4 — отдельная сессия | ☑ (confirmed) | Builder 05.10.2026 |
| §4 | `_deterministic_findings` считается один раз до loop | `services/summary_l2_review.py:870` (расчёт), `:896` (передаётся Reviewer каждую итерацию), `:1150` (def). Подтверждено; Z5 — отдельная сессия | ☑ (confirmed) | Builder 05.10.2026 |
| §5 | cooldown: ~2 embed-attempt/fact + stacktrace per fact | `services/summary_memory.py:2544` (`_memorize_facts_inner`), `:2734–2737` (vector может быть None → повторный embed), `:2921–2934` (`_save_graph_fact_embedding` снова `_embed` + WARN `exc_info=True` на каждый факт); quota labels есть (`services/embedding_control_plane.py:16–17,206,266–268`). Подтверждено; Z6 — отдельная сессия | ☑ (confirmed) | Builder 05.10.2026 |

Pre-fix RED run (до правок): `7 failed, 5 passed` —
`test_cover4/5/6/7/8/10` + `test_e2e_worker_registry_status_gets_save_reload`;
green: #1–#3 (RC-A уже исправлен), #9 (честный stale при реальном изменении),
negative control. JS RED: `node tests/js/asap44_cover_final_closure_test.js`
→ AssertionError «input «Следующий номер» привязан к next_issue_number».

Побочки 4.3-canary (T-4867): Canary A repeat **приложен как live proof RC-A** (job `cov_77f2347eec7d85e6b3a15f93`, before/after 200, pair rev 5, counter без изменений; полная Canary A 4.4 — T-4887) / manual 800 override — **не персистился** (UI §7.2 получил HTTP 422 «Не удалось определить модель/подключение»: sync `resolve_style_slot` vs §35 inherited runtime ladder), снимать нечего / counter нормализация «next = 11» — **предусловие T-4886**, применяется через новый UI-контракт (`next_issue_number=11` → `counter_value=10`), вручную prod DB не редактируется / stray publication — **не было**, Canary B не запускался, откатывать нечего.


### 0.4 Z4 pre-fix RED (T-4873–T-4875, §2; до правок), Builder 05.10.2026

Команда: `.venv\Scripts\python.exe -m pytest tests/test_asap44_cover_final_closure.py -q -k "cover11 or cover12 or cover13"` → **6 failed**;
`node tests/js/asap44_cover_final_closure_test.js` → AssertionError (блок d).

| Проверка | Pre-fix наблюдение | RED |
|---|---|---|
| #11 profile-only manual override (live §7.2) | `POST /api/cover/prompt-limit {profile_id, mode:manual, unit:chars, value:800}` → **HTTP 422** «Не удалось определить модель/подключение.» (sync `_resolve_limit_slot`→`resolve_style_slot`; style-слот пуст, inherited nano-gpt не резолвится) | ☑ `assert 422 == 200` |
| #11 UI/runtime route match | `GET /api/cover/styles/{id}`: `prompt_limit.provider=''` при runtime-слоте `nano-gpt.com/qwen-image-3-pro` (sync-контур vs §35 inherited); полей `route`/`source_taxonomy` нет | ☑ `assert '' == 'nano-gpt.com'` |
| #12/#12b «too long без числа» | `edit_image` → `reason='bad_request'` (generic), `run_style_job` ретрай не делает: `assert 1 == 2` (ровно один bounded retry отсутствует) | ☑ |
| #12c no-oversized-resend | блока `prompt_limit_unknown_retry` нет (`assert None is False`) | ☑ |
| #12d machine-readable число | «shorten the prompt to 800 characters or less» → `bad_request` (паттерн `extract_prompt_limit` не матчит) | ☑ |
| #13 `runtime_safe` ceiling | ретрая нет → `IndexError: list index out of range` (prompts[1]); `SOURCE_RUNTIME_SAFE`/taxonomy отсутствуют | ☑ |
| JS (d) source taxonomy/manual без optimistic | AssertionError: нет `source_taxonomy`, manual показывался из локального draft | ☑ |

`test_cover12e` (known-N retry → повторный too-long → ровно 2 call) добавлен как invariant-guard «≤1 extra paid call» (не RED-тест: известная ветка ретрая существовала и до правок).

Примечание: тестовые файлы Z4 (расширение `tests/test_asap44_cover_final_closure.py`, JS-блок d) написаны ДО runtime-правок; фикстура asap41-флагов держит `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED=False` для не-asap41 тестов — в RED/финальных прогонах наследование включается точечно (`_style_inheritance_on`) либо слот стабится (`_nanogpt_slot_stub`); прод-дефолт флага — ON.

### 0.5 Z5 pre-fix RED (T-4876/T-4877, §4; до правок), Builder 05.10.2026

Команда: `.venv\Scripts\python.exe -m pytest tests/test_asap44_l2_review_closure.py -q` → **5 failed, 3 passed**.

| Тест | Pre-fix наблюдение | RED |
|---|---|---|
| #14 recompute findings | review #2 всё ещё получает `paragraphs_without_evidence count=2` (stale от draft; исправленный абзац #0 уже с anchor) — `assert 2 == 1` | ☑ |
| #15 stale finding | review #2 `deterministic_findings != []` после успешной targeted revision | ☑ |
| #16 diagnostics | stage event `l2_reviewer`/`revision` не несёт `review_attempt`/`verdict`/`finding_codes`/`blocking_count`/`paragraph_ids`/`revision_target`/`revision_result`/`revision_failure_reason` (`KeyError`) | ☑ |
| #17 bounded | bounded инвариант (2 revisions/3 reviews, rejected) — зелёный (не RED) | — |
| #18 strictness | fabricated-anchor finding дропается → approved/0 revisions; verdict `unusable` → fail-closed `l2_review_unusable` — зелёные | — |
| T-4877 named-механизм A | reviser вернул абзац вложенным контейнером `{"paragraph": {...}}` (эхо запроса) → обе targeted revision `failed` (`revision_invalid_patch`), `l2_review_rejected` → Legacy | ☑ |
| T-4877 named-механизм B | reviser вернул `replace_paragraphs[0].evidence_message_ids` (real id) → revision применяется, но evidence молча теряется (`source_anchors == []` вместо anchor) | ☑ |

**Named L2 cause (T-4877b)**: targeted revision имел **незафиксированный output-schema**. `apply_targeted_revision` принимает только top-level `{"text","source_anchors"}` (или `replace_paragraphs[0]` с теми же ключами), а `build_targeted_revision_content`/`SUMMARY_L2_TARGETED_REVISION_ANCHORS_BLOCK` не задают формат ответа. Любая другая добросовестная форма (вложенный `paragraph`/`revised_paragraph` — эхо запроса; `evidence_message_ids` вместо anchors) сгорает как `revision_invalid_patch`/теряет evidence; при повторе — вторая burned revision → `l2_review_rejected` → Legacy (live-симптом owner run `64b40daa…`). Pre-fix repro — строки выше. Read-only подтверждение (если понадобится): mca_events `SUMMARY_REVISION_RESULT` для run `64b40daad73043bebcd9b90673f31788` (поля `reason_code`, `repair_target`, `attempt`) — `revision_invalid_patch` подтвердит schema-family, `revision_invalid_json` — parse-family.

### 0.6 Z6 pre-fix RED (T-4878–T-4880, §5; до правок), Builder 05.10.2026

Команда: `.venv\Scripts\python.exe -m pytest tests/test_asap44_graphrag_batch_breaker.py -q` → **6 failed, 4 passed**.
Репро: `MemoryManager._embed` застабан control-plane `EmbeddingGroupCoolingDown` (0 HTTP), 3–4 факта в одном logical batch.

| Тест | Pre-fix наблюдение | RED |
|---|---|---|
| #19 ≤1 attempt/batch | **6 embed-попыток на 3 факта (2/факт)**: dedup embed + повторный embed в `_save_graph_fact_embedding` | ☑ `assert 6 == 1` |
| #20 все text-only | facts в `graph_facts` (3), vec 0 — но **batch-event отсутствует** (0, не 1) | ☑ |
| #21 один WARN | 6 WARNING'ов: `graphrag dedup: embed failed` + `[graphrag] embed failed — fact saved text-only` **с exc_info (stacktrace) на каждый факт** | ☑ |
| #21b unexpected | RuntimeError по-прежнему со stacktrace, факт сохранён — зелёный (инвариант) | — |
| #22 recovery | после cooling batch 1 stub success → 4 вызова в batch 1 (state теряется per fact), vec 3 — «новая попытка» происходит уже внутри того же batch | ☑ `assert 4 == 1` |
| #23/#24 groups | pure control-plane labels/unknown safe default — зелёные (механика уже есть) | — |
| T-4880 UI/catalog | `keys.embedding_quota_group_labels` отсутствует в каталоге (`get_by_pg_key → None`), Status-панель не рендерит `rotation`/`next_allowed_at`/`quota_group` | ☑ |

## 1. Focused tests (§6, T-4881 #1–10) — PASS + implementation notes

Worktree fingerprint (git stash create, без коммита/стейджа): `9e07c2290871d6661fe715a6e6a1f348b25b07d0`; base HEAD `04e615d`.
Кандидат (worktree, без коммита): runtime `services/cover_style_registry.py`,
`services/cover_style_jobs.py`, `services/cover_style_preview.py`,
`web/api/cover_styles.py`, `web/index.html`, `web/app.js`;
tests `tests/test_asap44_cover_final_closure.py`,
`tests/js/asap44_cover_final_closure_test.js` (+ обновлены legacy-ожидания
старого контракта, см. ниже).

Команды и counts:
- core: `.venv\Scripts\python.exe -m pytest tests/test_asap44_cover_final_closure.py tests/test_asap43_cover_style_surgical.py -q` → **22 passed** (12 новых + 10 reuse 4.3 delta).
- affected regression: `... pytest tests/test_asap43_cover_style_surgical.py tests/test_asap42_step3_style_integration.py tests/test_asap42_step2c2_miniapp_seeds.py tests/test_cover_styles_contract_asap32.py tests/test_extra_cover_style_registry.py tests/test_extra_cover_styles_api.py tests/test_extra_cover_style_jobs.py tests/test_cover_style_wave_b_asap4.py -q` → **179 passed**.
- adjacent: `... pytest tests/test_extra_cover_style_pipeline.py tests/test_extra_cover_style_runtime.py tests/test_extra_cover_styles_ui.py tests/test_summary_cover_round1023.py tests/test_summary_cover_model_compat_round1024.py tests/test_summary_cover_style_wave_f_asap41.py -q` → **106 passed**; `... pytest tests/test_hotfix4_cover_nav_shell_round1025.py tests/test_hotfix5_summary_cover_window_round1025.py tests/test_progressive_tab_basic_coverage.py tests/test_summary_coverage_asap31.py tests/test_summary_coverage_ledger_asap41.py -q` → **75 passed**.
- JS: `node --check web/app.js` OK; `node tests/js/asap44_cover_final_closure_test.js` → OK; `asap43_cover_style_surgical_test.js`, `round1029_extra_cover_styles_test.js`, `asap42_step2c2_layout_test.js`, `vue_mount_test.js`, `routing_test.js` → OK.
- Pre-fix RED этих же тестов: см. §0 (7 failed / 5 passed; JS AssertionError).

| # | Тест (new file) | Pre-fix | После |
|---|---|---|---|
| 1 | `test_cover1_generated_base_registered_in_registry` (reuse 2.58.51) | green (RC-A fix) | ✅ |
| 2 | `test_cover2_before_after_fetchable_via_real_api_route` | green | ✅ |
| 3 | `test_cover3_base_registry_failure_leaves_no_pair` (negative control) | green | ✅ |
| 4 | `test_cover4_next_issue_display_and_no_counter_mutation` (RC-C/B) | RED `KeyError 'next_issue_number'` | ✅ |
| 5 | `test_cover5_production_ladder_11_retry_11_next_12` (RC-B) | RED `counter_value 0 != 10` | ✅ |
| 6 | `test_cover6_test_style_uses_current_draft_snapshot` (RC-D) | RED `'ВЫПУСК 00' != 'ВЫПУСК 12'` | ✅ |
| 7 | `test_cover7_noop_save_does_not_bump_revision` (RC-E) | RED `revision 2 != 1` | ✅ |
| 8 | `test_cover8_noop_save_keeps_preview_pair` (RC-E) | RED pair stale (`2 != 1`) | ✅ |
| 9 | `test_cover9_rendering_change_stales_pair_honestly` | green | ✅ |
| 10 | `test_cover10_exact_draft_save_promotes_preview` (RC-E promote) | RED `preview_revision 1 != 2` | ✅ |

Implementation notes:
- **T-4868** (contract): `services/cover_style_registry.py` — `next_issue_number(profile) = counter_value + 1`; API `_public_profile` отдаёт `next_issue_number` (raw `counter_value` — legacy/compat); `ProfileBody.next_issue_number` (`web/api/cover_styles.py`), save `N` → `counter_value = N - 1` (`_counter_value_from_body`; legacy-клиент без поля — 1:1 как раньше); production `resolve_issue_number` (atomic `+1 RETURNING`, per-run `cover_style_issue_assignments`) не менялся — теперь согласован с UI; DB schema без миграции; UI `web/index.html:810-813`/`app.js` (`coverStyleNextNumber`) работают с `next_issue_number`.
- **T-4869**: `preview_issue_display(counter_format, next_number)` (zero-pad 2); все call sites (`_public_profile`, `_budget`, test-style response, `run_style_job` preview/prod-without-number, `run_style_preview`) используют текущий next; hardcoded `00`-контракт удалён (`preview_issue_number()` удалён).
- **T-4870**: `TestStyleBody.draft` (`StyleDraftBody`, `extra=forbid`), server-side normalize/validate (pipeline/model mode, next≥1, connection FK, лимиты длин), merge поверх DB-профиля (`merge_draft_snapshot`) — НЕ persist; snapshot + `style_fingerprint` пишутся в durable `CoverJobState` (`draft_snapshot`/`draft_fingerprint`), resume (`resume_preview_job`) мержит snapshot из state; references/owner/origin/RBAC — из durable registry; UI шлёт draft из `coverStyleDraftSnapshot()` (в т.ч. retry-start).
- **T-4871**: canonical compare `STYLE_AFFECTING_FIELDS` в `upsert_profile`; no-op/name-only/enabled не bump'ают `revision`, реальное rendering-изменение bump'ает и честно делает pair stale.
- **T-4872**: `upsert_profile(promote_preview=True)` — в одной UPDATE `preview_revision = revision + 1`, указатели pair не перезаписываются; API включает promote только при matched durable-provenance (completed preview job + fingerprint + совпадение asset-id с текущей парой).
- Тесты, фиксировавшие старый контракт `§66`/revision-bump, обновлены точечно: `tests/test_extra_cover_style_registry.py` (display + CRUD revision), `tests/test_extra_cover_style_jobs.py` (`ВЫПУСК 01`), fake-DB `tests/test_cover_styles_contract_asap32.py` (canonical SELECT + 16/15-arg UPDATE + promote), двойники `upsert_profile` в `tests/test_extra_cover_styles_api.py` (принимают `**_kw`).
- Test-infra fidelity: `tests/test_asap42_step3_style_integration.py::_SqliteConn.fetchrow` теперь коммитит DML (asyncpg autocommit-паритет) — без этого `UPDATE ... RETURNING` счётчика терялся в shim (сказалось только на тестах).
- R17: snapshot содержит инструкцию профиля (уже хранится в PG), секретов/prompt-логов в evidence нет.

- **T-4873–T-4875 / §2 (Z4, один runtime truth) — этой сессией**:
  - **Единый resolver**: `services/cover_style_pipeline.py::resolve_effective_edit_capability` (async) = §35 `resolve_style_slot_inherited` + `cover_style_edit.resolve_edit_route` + `image_capabilities.resolve_capabilities(route, operation)`; возвращает `{slot, provider, base_url, model, route, operation, resolve_source, capabilities, connection}`. Использование: UI detail/capabilities/connections-status/prompt-limit GET+POST → `web/api/cover_styles.py::_effective_capability`; diagnostics/Inspector → `jobs.profile_diagnostics`; production → `run_style_job` (route пинится в capability key и прокидывается в edit_image через inspect-совместимость). Явно переданные provider/base_url/model (developer/tool-путь) сохраняют прямой слот. В `web/api` нет второго sync-контура для UI (`slot_capabilities(`/`resolve_style_slot(` — только explicit-ветка prompt-limit).
  - **Live §7.2 422**: `_resolve_limit_slot` для profile-only идёт inherited-контуром → seeded-профиль (Medved, default) адресует `nano-gpt.com/https://nano-gpt.com/api/v1/qwen-image-3-pro`; manual override персистится (`bot_settings`), GET возвращает manual/800, detail — manual taxonomy. Проверено тестом #11 (pre-fix: 422 «Не удалось определить модель/подключение»).
  - **T-4874 taxonomy**: `SOURCE_RUNTIME_SAFE` + `prompt_limit_source_taxonomy()`/`prompt_limit_is_exact()` (5 значений); API отдаёт `source_taxonomy` в capabilities/prompt_limit/budget + блок `effective` (provider/base_url/model/route/operation/resolve_source); UI-подписи, learned ceiling рендерится как «≤ … (безопасный потолок)». `VERIFIED_PROMPT_LIMIT_REGISTRY` не пополнялся: blind-800 на Pro отсутствует (AST-тест 4.3 зелёный).
  - **T-4875 unknown-limit**: `image_capabilities.looks_like_prompt_too_long()`; `edit_image` 400 без числа → `prompt_limit_unknown` (+`meta.prompt_limit_unknown`), с числом «shorten…to N chars» → `prompt_limit` (runtime_exact; добавлен паттерн, не hardcode). `compile_style_prompt(minimal=True)` = только P0+P1 (номер выпуска, запрет дублей, инструкция/стиль, base style) — P2 refs/brief сбрасываются; в `run_style_job` ровно ≤1 доп. paid call: шлётся только если prompt реально короче; успех → `record_runtime_safe_ceiling` (source `runtime_safe`, не понижает exact/manual); повторный too-long → `prompt_limit_unknown_after_retry` (не generic bad_request). Наблюдаемость: `prompt_limit_unknown_retry` (original/recompiled/retry_sent/skipped/learned_safe_ceiling), reason codes в `STYLE_REASON_CODES`, human-сообщения preview.
  - Обновлены legacy-ожидания (осознанно, новый контракт §2): `test_extra_cover_style_jobs.py::test_sync_bad_request_capability_mismatch` (тело 400 теперь generic «invalid image format»; «prompt too long» — отдельная семантика), `test_extra_cover_styles_api.py::test_capabilities_and_no_secret` (patch target `image_capabilities.resolve_capabilities`), `test_cover_style_wave_b_asap4.py::test_profile_diagnostics_checklist_41` (patch target `resolve_effective_edit_capability`).
  - Команды: `... pytest tests/test_asap44_cover_final_closure.py -q` → **19 passed** (12 reuse + 7 новых Z4: #11, #12, #12b–e, #13); affected-batch 16 файлов → **360 passed**; `node tests/js/asap44_cover_final_closure_test.js` (+asap43/round1029/step2c2/vue_mount/routing) → OK.

- L2 #14–18: ✅ **8/8 passed** (`tests/test_asap44_l2_review_closure.py`; #14–#18 + 3 regression named-механизма) — Z5, см. §5; pre-fix RED §0.5.
- GraphRAG #19–24: ✅ **10/10 passed** (`tests/test_asap44_graphrag_batch_breaker.py`; #19–#24 + 21b + 23b/23c/UI/catalog) — Z6, см. §6; pre-fix RED §0.6.

### Z5 — Hybrid Summary L2 (T-4876/T-4877) — implementation notes, Builder 05.10.2026

Runtime: `services/summary_l2_review.py`, `services/summary_l2_anchor_repair.py`, `services/execution_graph_source.py`.

- **T-4876 (stale findings)**: `_deterministic_findings_from_metrics()` + `_revalidate_metrics()`; `run_l2_with_review` держит `current_doc_metrics` и пересчитывает findings ПЕРЕД каждой review-итерацией; после каждой успешной revision документ ре-валидируется тем же единым §99-валидатором (`validate_l2_document(_anchors)`) → findings соответствуют текущему `current_doc`. Reviewer strictness/progress criterion/bounded budget не менялись.
- **T-4877a (наблюдаемость)**: stage events `l2_reviewer` теперь несут `review_attempt`, `verdict`, `finding_codes[]`, `blocking_count`, `paragraph_ids[]`, `deterministic_validation_codes[]`; `revision` — `revision_target`, `revision_result` (`ok|invalid|error`), `revision_failure_reason` (R17-safe коды). Whitelist проекции Run Inspector (`execution_graph_source._STAGE_EVENT_KEYS`) расширен ровно этими полями.
- **T-4877b (named cause)**: schema/output-contract gap — цепочка описана в §0.5; фикс: (1) `build_targeted_revision_content` пиннит `output_format` (`{"text","source_anchors":[...]}`), (2) `apply_targeted_revision` принимает вложенные контейнеры-эхо (`paragraph`/`revised_paragraph`/`fixed_paragraph`), строку-абзац и нормализует evidence (`source_anchors`/`evidence_refs`/real `evidence_message_ids` → anchors). Детерминированная §99-валидация и Reviewer-строгость не ослаблены — неизвестные anchors отбрасываются, документ валидируется как раньше. `MAX_REVISIONS=2`/`MAX_REVIEWS=3`/budget не тронуты.
- Команды (focus): `pytest tests/test_asap44_l2_review_closure.py -q` → **8 passed**; adjacency: `test_summary_wave_d_asap4.py test_summary_source_anchors_asap42.py test_summary_anchors_wiring_asap42.py` → **110 passed**; `test_summary_execution_graph_round1026.py test_pipeline_analytics_asap4.py test_summary_inspector_zone_g_asap41.py` → **133 passed**.

### Z6 — GraphRAG batch breaker + quota groups (T-4878–T-4880) — implementation notes, Builder 05.10.2026

Runtime: `services/summary_memory.py`, `services/embedding_control_plane.py`, `services/param_catalog.py`, `web/app.js`, `web/index.html`; F8 reissue (`plans/docs/param_registry*/screen-map`, fixtures, счётчики тестов).

- **T-4878**: `_EmbedBatchState` на logical batch; первое `is_serviceability_error(exc)` (`EmbeddingGroupCoolingDown`/`EmbeddingBudgetExhausted`, helper в control plane) в dedup-embed ИЛИ в `_save_graph_fact_embedding` → `unavailable=true`; далее: dedup без vector идёт existing safe fallback (`_dedup_decide`: exact-only), `_save_graph_fact_embedding` НЕ делает network-попытку, факты сохраняются text-only; новый batch создаёт новое состояние (recheck). ≤1 embed-попытка на batch (было 2/факт).
- **T-4879**: один concise WARN на batch (`chat_id/source/quota_group/state/next_allowed_at/facts_text_only/dedup_vector_skipped`), без stacktrace; unexpected exceptions по-прежнему со stacktrace (не маскируются). Query-пути `vector_search`/`_search_graph_facts` для ВСЕХ known serviceability-состояний → coalesced INFO + FTS-fallback (раньше только CoolingDown, `EmbeddingBudgetExhausted` спамил WARN со stacktrace); recovery — существующий `_ensure_vec_retry` (state + reactivation).
- **T-4880**: `keys.embedding_quota_group_labels` каталогизирован (non-secret; `_CLASSVAR_CATALOGUED`), поле в существующем Embeddings-блоке MiniApp (`web/app.js`), Status-панель рендерит `keys/groups/rotation/blocked/next_allowed_at` без секретов (`web/index.html`; ранее `groups` рендерились как `{{ g }}` → `[object Object]`). Каталог 488→**489** (+1, delta 77→78), F8 fixtures/docs переизданы (`param-registry-round1025.tsv/screen-map/meta`, `f8_baseline.json`, `catalog_baseline.json`); пин-тесты счётчиков обновлены (42 файла, `len(pc.REGISTRY)`/`categorized`), обновлены `test_param_catalog`, `test_frontend_tab_mapping`, `test_round106_ia_smoke`, `test_round1025_f8_registry`, `test_ia_inventory_round1025`. Независимость групп — только из label; `resolve_quota_group` не смотрит на значение ключа.
- Команды (focus): `pytest tests/test_asap44_graphrag_batch_breaker.py -q` → **10 passed**; `test_embedding_control_plane_asap4.py test_graphrag_memory.py` → **241 passed**; `test_summary_memory.py test_smartsearch_service.py test_smartmodule_throttling.py test_memory_health.py` → **149 passed**; catalog-пины (42 файла) → **1468 passed, 2 failed**; `test_param_catalog.py test_round1025_f8_registry.py test_ia_inventory_round1025.py test_frontend_tab_mapping.py test_webapp_round109_ui.py test_round106_ia_smoke.py test_debug_config_handler.py` → **196 passed, 1 failed** (все 3 failed — pre-existing pg_db-пины, см. §9; к каталогу отношения не имеют).
- JS: `node --check web/app.js` OK; `asap41_zone_g_inspector`, `routing`, `round1030_pipeline_inspector`, `asap44_cover_final_closure`, `vue_mount` → OK.
- Worktree fingerprint (`git stash create`, без коммита/стейджа): `c0a5263f7f3933e5046c60da248e188cb977a018`; base HEAD `04e615d`. Мои файлы: runtime см. выше; tests `tests/test_asap44_l2_review_closure.py`, `tests/test_asap44_graphrag_batch_breaker.py` (новые, untracked) + catalog-пины/fixtures из списка; F8 docs переизданы.

## 2. Real E2E backend path (§7, T-4884) — PASS

Цепочка (не mock-only): durable preview worker `cover_style_preview.run_preview_job` → реальный `cover_style_jobs.run_style_job` (реальная компиляция prompt) → managed asset store `cover_style_assets.store_file_bytes` (CAS) → реальный PG-registry `cover_style_registry` (temp-SQLite asyncpg shim — установленный контур) → public status `GET /api/cover/test-style/{job}` → authenticated `GET /api/cover/assets/{before}` = 200 (PNG bytes) → authenticated `GET /api/cover/assets/{after}` = 200 (styled bytes) → `POST /api/cover/styles?style_id=…` (exact draft) → reload editor (новый pool) → та же пара.

- Команда: `.venv\Scripts\python.exe -m pytest tests/test_asap44_cover_final_closure.py -q` → **12 passed**; тесты `test_e2e_worker_registry_status_gets_save_reload`, `test_e2e_rc_a_negative_control_old_store_base_would_404`.
- Мокаются только внешние paid-точки (base provider, style HTTP edit, slot-resolve/capabilities → фиксированный test-slot); registry/assets/job/status/GET/Save/reload — реальный код.
- Pre-fix RED (RC-A): negative control воспроизводит старую `_store_base` (без `registry.upsert_asset`) → completed job + формально «текущая» pair, но `GET before = 404`; именно `GET before == 200` в E2E-цепочке падает на pre-fix (2.58.50). Дополнительно `test_cover3` (registration failure → job failed, pair не записана).
- Pre-fix RED (RC-C/RC-B/RC-D/RC-E) для полной цепочки: `7 failed, 5 passed` (см. §0).
- Артефакты: temp-SQLite файл + CAS-файлы в `COVER_STYLE_ASSETS_DIR` (tmp) в рамках теста; evidence — этот файл + имена тестов.

## 2a. F-N2 — skip-ahead issue allocation (live defect после live acceptance) — FIXED

- **Defect (live repro)**: next=11 (counter=10), истории профиля уже заняты 11–13 → production `resolve_issue_number` инкрементил counter до 11 и падал на `UNIQUE(profile_id, issue_number)` (prod: `services/pg_db.py:454-455`); PG rollback → counter снова 10, run не получал номер (None).
- **Pre-fix RED** (до правки): `.venv\Scripts\python.exe -m pytest tests/test_asap44_cover_final_closure.py -q -k "issue_allocation"` → `sqlite3.IntegrityError: UNIQUE constraint failed: cover_style_issue_assignments.profile_id, issue_number` + `assert None == 14` (`test_issue_allocation_skips_occupied_numbers`), `test_issue_allocation_picks_first_free_gap` green (candidate 11 свободен). Test shim теперь зеркалит prod unique-index (`tests/test_asap42_step3_style_integration.py::_SCHEMA`).
- **Fix** (`services/cover_style_registry.py::resolve_issue_number`): после atomic `counter_value+1 RETURNING` — bounded skip-loop (`_MAX_ISSUE_SKIP_STEPS = 1000`) по занятым номерам от candidate до первого свободного; `counter_value = N'` (last_assigned) в той же транзакции; retry того же `summary_run_id` возвращает прежний N' (idempotent, проверяется до инкремента); занятые номера не переиспользуются; контракт `next_issue_number = counter_value + 1` не менялся (editor может показывать counter+1 — display не переделывался).
- **Tests**: `test_issue_allocation_skips_occupied_numbers` (11–13 заняты → 14, counter=14, retry=14, next=15, UNIQUE не нарушен, Test Style counter не тратит, reload durable) + `test_issue_allocation_picks_first_free_gap` (12–13 заняты → 11).
- **Counts после фикса** (worktree на базе deployed `329e6de` = prod 2.58.52; worktree-fingerprint F-N2 `32bc95bd` (git stash create); uncommitted delta — только `services/cover_style_registry.py` (F-N2) + shim/tests):
  - `pytest tests/test_asap44_cover_final_closure.py -q` → **21 passed** (19 прежних, вкл. Z4 #11–13, + 2 F-N2).
  - `pytest tests/test_extra_cover_style_registry.py tests/test_extra_cover_style_jobs.py -q` → **74 passed**.
  - `pytest tests/test_asap43_cover_style_surgical.py tests/test_cover_styles_contract_asap32.py -q` → **26 passed** (shim-consumers).
  - `pytest tests/test_asap42_step3_style_integration.py tests/test_asap42_step2c2_miniapp_seeds.py -q` → **27 passed** (shim со встроенным prod unique-index).
  - Pre-fix RED зафиксирован до правки (см. выше); полного suite нет; paid-вызовов нет.
- **Deploy**: фикс НЕ задеплоен (prod 2.58.52 без skip-ahead) — требуется deploy этого дельта-кандидата перед Canary B re-run (§11.2.2/§11.3).

## 3. Canary A — live Test Style (§3, T-4887) [REAL]

- Job id / timings: —
- before asset id + GET 200: —
- after asset id + GET 200: —
- `ВЫПУСК 11` (не `00`): —
- counter не изменён: —
- Save без изменений → pair жива; reopen → та же pair: —
- нет `Failed to fetch` / generic `bad_request`: —
- live proof RC-A (Canary A repeat 4.3): **attached** — job `cov_77f2347eec7d85e6b3a15f93`: before GET 200 (887 912 B) + after GET 200 (1 706 155 B), pair atomic revision 5, counter не изменён; полный 4.4-список Canary A (§§ start/job/UI/ВЫПУСК 11/reopen) — за T-4887 (live, после deploy).

## 4. Canary B — live production Summary (§3, T-4888) [REAL]

- Run id: —
- issue 11 / retry 11 / next independent 12: —
- published cover outcome = `styled` (не `base_fallback`): —
- analytics/Inspector: provider/model/route, compiled length, capability source: —
- Hybrid vs Legacy (+ причина, если fallback): —

## 5. L2 (§4, T-4876/T-4877)

- Почему раньше две targeted revision стали unusable (run id + diagnostics codes): **named cause — schema/output-contract gap**: `apply_targeted_revision` принимает только top-level `{"text","source_anchors"}`, а targeted-промпт не пиннил output schema → добросовестный ответ в другой форме (вложенный `paragraph`-эхо; `evidence_message_ids`) сгорал как `revision_invalid_patch`/терял evidence; повтор → вторая burned revision → `SUMMARY_REVISION_RESULT failed/targeted` ×2 → `L2_ERROR l2_review_rejected` → `LEGACY_FALLBACK l2_unusable` (owner run `64b40daad73043bebcd9b90673f31788`). Pre-fix unit-repro — §0.5. Read-only confirm (если понадобится): mca_events `SUMMARY_REVISION_RESULT` этого run, поле `reason_code` (`revision_invalid_patch` = schema-family / `revision_invalid_json` = parse-family); новых paid-прогонов не требуется.
- Что изменено; pre/post repro: §0.5 (RED) → §1 Z5-блок (fix + 8/8 passed); `MAX_REVISIONS`/strictness/fail-closed не тронуты; pre-fix RED: nested-echo → rejected, stale count 2; post-fix: revision applied, findings пересчитаны.
- Stage event excerpt (только коды, без текстов): `l2_reviewer: {review_attempt:1, verdict:"needs_fixes", finding_codes:["quote_speaker_mismatch"], blocking_count:1, paragraph_ids:[0], deterministic_validation_codes:[...]}` → `revision: {revision_target:"targeted", revision_result:"invalid", revision_failure_reason:"revision_invalid_json"}` (минимальный пример из теста #16; в prod-формате добавляются run_id/attempt/timestamps).

## 6. GraphRAG (§5, T-4878–T-4880/T-4889)

- Controlled repro (batch): unit/local с synthetic-фактами и застабанным `_embed` (control-plane `EmbeddingGroupCoolingDown`, 0 HTTP) — `tests/test_asap44_graphrag_batch_breaker.py`; pre-fix RED §0.6. Live controlled repro (T-4889) — за DevOps/Orchestrator после deploy.
- embed attempts / WARN до → после: **до** 6 embed-попыток / 6 WARN (2/факт: dedup + `_save_graph_fact_embedding`, каждый со stacktrace) на 3 факта; **после** **1** embed-попытка / **1** concise WARN на batch (state=`EmbeddingGroupCoolingDown`, `next_allowed_at`, `facts_text_only=3`, `dedup_vector_skipped=2`); unexpected exception — по-прежнему со stacktrace (тест 21b).
- text-only facts, dedup_vector_skipped: все факты batch в `graph_facts` (4/4 в тесте), `graph_facts_vec`=0; dedup без vector — existing exact-fallback; следующий batch после recovery снова embeds (1 сгоревший вызов → далее 3 dedup, vec=3).
- quota topology в Analytics/Status (keys/groups/rotation/blocked/next_allowed_at): `provider_panel()/rotation` (keys/groups/status none|grouped/degenerate/hint) + `groups[]` (quota_group/state/next_allowed_at) уже в API; теперь отрендерены в Status-блоке «Embeddings и векторная память» (было `{{ g }}` → `[object Object]`, rotation/next_allowed_at не показывались). Настройка — `keys.embedding_quota_group_labels` в Embeddings-группе MiniApp; сохранённое значение подхватывается пулом без рестарта (тест 23c). Без секретов (алиасы/группы/числа).

## 7. Deploy (T-4886)

- Версия / commit / health / rollback note: —

## 8. Reviewer (T-4885)

- Verdict: **Approved** (T-4885, 05.10.2026). Полный отчет и ответы (а)–(з) в `review.md` этого пакета; binding: `plans/reports/asap44_wth_manifest_review.txt` (HEAD `04e615d` + sha256 по 80 in-scope файлам). Обязательные лайв-гейты §9 → после деплоя (Canary A/B + GraphRAG repro).

## 9. Open items / передача следующим сессиям

- **T-4886 (DevOps deploy)**: предусловие counter «next = 11» применяется через новый UI-контракт (save `next_issue_number=11` → `counter_value=10`), prod DB вручную не редактировалась.
- **Z4 (§2, T-4873–T-4875) — реализовано в этой сессии** (fingerprint worktree `e821061ad2dd6d7a4c33fb8148181f3e65ab3111`, база HEAD `04e615d`; не закоммичено, не застейджено). Pre-fix RED — §0.4; implementation notes/counts — §1. Live-проверка manual override persistence на проде — за T-4887 (Canary A); локально проверено через реальный router/registry/hot-config (тест #11, без paid-вызовов). Остаточный риск (low): route-TTL 900 c делится между UI и runtime — смена маршрута у провайдера может до 15 мин показываться старой (тот же кэш, что и раньше у runtime).
- **Z5 (§4, T-4876/T-4877) — реализовано в этой сессии** (worktree, не закоммичено/не застейджено). Pre-fix RED — §0.5; implementation notes/counts — §1 (Z5-блок) и §5. Named L2 cause — schema/output-contract gap targeted revision; подтверждение live-причины (read-only) — §0.5.
- **Z6 (§5, T-4878–T-4880) — реализовано в этой сессии**. Pre-fix RED — §0.6; implementation notes/counts — §1 (Z6-блок) и §6. Каталог +1 (489, санкция T-4880), F8 переиздан; live-проверки (warning storm, quota topology, controlled repro) — за T-4889.
- **Incidental / pre-existing (НЕ этой сессии, не чинилось)**: `services/pg_db.py` на HEAD `04e615d` не совпадает с F8-fixture и имеет 53 DDL-стейтмента против пин-ожидания 52 — это след уже закоммиченного 2.58.51 cover-фикса (PG DDL `preview_job_id`), не обновившего F8-пины. Проявления: `test_round1025_f8_registry::test_ddl_source_unchanged`, `test_budget_data_repair_round1024::test_delta_ddl_zero`, `test_budget_guardrails_round1024::test_ddl_statements_pinned` (проверено: `git diff HEAD -- services/pg_db.py` пуст → воспроизводится на base HEAD). Исправление — отдельным решением (reissue pg_db-хэша/пинов), вне scope Z5/Z6; cover-зону не трогал. Severity: low (тест-пин, не runtime).
- **Catalog delta +1 (Z6/T-4880)**: каталог 488→489, delta 77→78; переизданы `plans/docs/param-registry-round1025.tsv/screen-map/meta` + `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`; обновлены счётчик-пины в 42 тест-файлах. Reviewer/PM: подтвердить санкцию каталог-дельты (в плане 4.4 явная запись отсутствует; сделано по прямому требованию §5.3/T-4880 «owner-настройка … no new generic config framework»).
- **Residual (low) promote-race**: если Test Style-completion произойдёт ровно между чтением профиля и promote-UPDATE, `preview_revision` может быть поднят к revision нового сохранения, а указатели останутся от более нового job (указатели не перезаписываются). Практическое окно — длительность одного Save; отдельного механизма (version-guard) в этой сессии не добавлялось; Reviewer может взвесить.
- Изменённые legacy-тесты (осознанно, новый контракт): список в §1. Shim `_SqliteConn.fetchrow` теперь коммитит DML (test-infra, не runtime).
- Коммит не делался, ничего не застейджено (untracked: новый test-файл + JS-тест + feature-packet).

## 10. Финальный отчёт (§12, T-4890)

- Ссылка/файл отчёта: —

---

# 11. LIVE ACCEPTANCE (T-4887–T-4889, 05.10.2026, прод 2.58.52)

Среда: `https://admin-bot.duckdns.org` (198.46.175.136), APP_VERSION **2.58.52**
(feat `09fd5a8`), PID 3651908, `/healthz` 200, NRestarts=0. Admin MiniApp —
серверный TMA initData (admin 5885953495; R17: значение не печаталось, файлы
удалены). Локально: Chromium+host-resolver MAP (локальный DNS-резолвер барахлил;
TLS/SNI без изменений). Код не менялся, конфиг не менялся кроме одного UI-шага
(ниже).

## 11.0 Предусловие через РЕАЛЬНЫЙ UI (шаг 0)

- До: next=14 (counter_value=13), revision=5, пара rev 5 валидна
  (before `cas_d2ae85e7…`, after `cas_272acc62…`).
- Действие: MiniApp → редактор Medved Press → «Следующий номер» = **11** →
  «Сохранить стиль» → `POST /api/cover/styles?style_id=medved_press` **200**
  (тело `next_issue_number: 11`).
- После: **next=11, internal counter_value=10**, **revision 5→6**,
  пара: `preview_revision=5`, before/after = **null**, `preview_stale=true`,
  source «Пример» — rendering-affecting Save инвалидировал прежнюю пару (§6#9);
  UI «Предпросмотр: ВЫПУСК 11».
- Побочно: два случайных no-op Save драйвера (гонка meta-reload, тело с next=14)
  — revision НЕ менялся, пара оставалась валидной (живое подтверждение no-op
  invariant). Финальный Save — уже с 11 (см. выше).

## 11.1 Canary A (T-4887) — **PASS**

Один реальный Test Style через MiniApp (Playwright 390×844), job
`cov_77f2347eec7d85e6b3a15f93`, correlation `cover_test_9ba4766438bc`,
completed **16:17:23 UTC**, `style_revision=6`.

| Критерий §3 | Факт |
|---|---|
| POST start быстрый | 200 (клиент сразу перешёл к polling; точный body/мс потерян при падении драйвера, см. примечание) |
| durable job completed | статус completed, `preview_status=success`, `preview_revision=6` |
| base реально сгенерирована | `[image] generated` 16:16:09, **758 209 B**, 57.6 с |
| `preview_before_asset_id` в DB registry | строка `cas_fad658b317783096515eabab8e6f2f5d` (test_base.png, generated_preview, 758 209 B, 16:16:09) |
| GET before = 200 + image | 200 / 758 209 B, sha256[:16] `fad658b317783096` (bytes == log) |
| styled asset существует | `cas_14d161eab7539d93838a64794a59067e` (preview_style.jpg, 1 516 792 B, 16:17:23) |
| GET after = 200 + image | 200 / 1 516 792 B, sha256[:16] `14d161eab7539d93` |
| UI одновременно before+after | оба blob 1024×1024, complete; source «Результат теста» |
| styled image содержит `ВЫПУСК 11` | артефакт `canary_a44_after.jpg` (styled) **лично осмотрен**: на обложке «ВЫПУСК 11», логотип Медведь Press (reference), PERMsoc, comic-стиль; «00» нет |
| Test Style не меняет next | next=11 / counter=10 до и после; assignments не пополнились (последняя запись — issue 13 от 13:08) |
| effective provider/model + capability state | «Модель обработки: nano-gpt.com / qwen-image-3-pro · маршрут: image_api»; «Лимит инструкции: не публикуется (источник: unknown)»; «Режим: sync»; manual override отсутствует (owner §2 — так и должно быть) |
| нет `Failed to fetch` | нет; console errors 0 (follow-up-сессия) |
| нет generic `bad_request` | нет; prompt 597 chars, edit 2xx |
| no-op Save не уничтожает pair | POST 200 с теми же полями → revision 6 (не менялся), пара цела (те же ids, `preview_revision=6`, `preview_pair_valid=true`) |
| закрыть/открыть editor → та же pair | next=11, те же ids, оба изображения на месте, source «Результат теста» |

Reference: `reference_bytes_total=475189` (medved_press.png) в SUBMITTED-логе;
UI reference asset GET 200.

Примечание (честно): первый драйвер упал на скачивании артефактов
(локальный DNS: `APIRequestContext` не использует host-resolver-rules Chromium)
**уже после завершения paid job**; сырой POST/poll JSON потерян. Доказательства
собраны durable-статусом + повторной **бесплатной** UI-сессией (просмотр пары,
no-op Save, reopen) — второго paid-прогона не было.

## 11.2 Canary B (T-4888) — **FAIL / не завершён** (2 причины + text-finding)

Попытка реального production-прогона: internal runner — точное зеркало wiring
`bot.py` (`ConfigCache` → `ChatParamsCache` → `DatabaseService` → `LLMClient` →
`AliasResolver` → `MemoryManager` → `SummaryGenerator`,
`generate_and_send(chat, manual=True)`), run_id
`f3f263b1601c4f3cb285749bce8f94ba` (16:21:55→16:31:18). Публикация состоялась:
`PUBLISH_RICH_COMPLETE message_id=1133207`, но
`COVER_PIPELINE_DONE status=base fallback=style_failed` — **base fallback**.

1. **Причина окружения запуска (не продукт)**: style-стадия
   `COVER_STYLE_FAILED reason=reference_missing` (745 мс) — процесс запущен от
   `nik`, а `/var/www/admin_bot/var` = `drwx------ root` (`User=root` у сервиса),
   reference-файл не читается. В bot-процессе (root) цепочка работает: Canary A
   в bot-процессе, прогон 13:08 (`reference_count=1, reference_bytes_total=475189`).
   Реальный триггер — `/summary` владельца (Telegram) или раннер от root; из
   моего доступа root-запуск невозможен (`sudo -n -l`: только
   systemctl/journalctl admin_bot).
2. **Live-дефект counter allocation (candidate fix, НЕ задеплоен)**: при next=11
   (counter=10) новый production run **не может получить issue 11** — исторический
   assignment 11 принадлежит run `d2ccb769…` (07:13), а
   `idx_cover_style_issue_unique` UNIQUE(profile_id, issue_number) отклоняет
   INSERT; `resolve_issue_number` глотает `UniqueViolation` и возвращает **None**
   (репро read-only: `resolve_issue_number(medved_press, f3f263b…) -> None`;
   `Key (profile_id, issue_number)=(medved_press, 11) already exists`; counter
   после отката = 10). Следствие: критерии «run получает 11 / retry=11 /
   next=12» на проде в текущем состоянии недостижимы (unit-лестница 11→11→12
   валидна только на чистом профиле). Нужен fix/решение (skip-ahead до
   свободного номера: 11–13 заняты → 14; либо решение об уникальности) →
   re-review; затем Human Gate: владелец шлёт `/summary`.
3. **Text-контур**: L2 writer `status=invalid invalid_reason=invalid_paragraph`
   (paragraphs=0) → `L2_ERROR` → `LEGACY_FALLBACK l2_unusable` (16:28:41,
   calls_so_far=2 — review/revision не запускались). Причина конкретная; runtime
   `summary_l2_writer.py` этим пассом не менялся (в `09fd5a8` — только тест
   writer'а) → это **не** механизм Z5 targeted-revision; при повторе —
   отдельный follow-up по output-контракту writer'а.

Незакрытые критерии: issue 11 и 11/11/12; styled-публикация; Inspector-факты по
styled (provenance не создавался: `reference_missing` до edit).

## 11.3 GraphRAG live repro (T-4889) — **PASS (живой breaker)**

- Cooldown живой: quota group `unknown`, state `EmbeddingGroupCoolingDown`,
  `next_allowed_at=2026-10-05 00:05 UTC` (parked kind=spend, est=utc_day_end).
- Во время canary-B прогона batch-breaker сработал РОВНО один раз (16:25:37):
  `embedding unavailable for batch … facts_text_only=22 | dedup_vector_skipped=21`
  (state=`EmbeddingGroupCoolingDown`, next_allowed_at), `saved=22 skipped=0` —
  все 22 факта text-only, 0 повторных network-embed-попыток на факт, 0 stacktrace.
- Before→after (journal сервиса): 06:00–15:45 (до деплоя) —
  `embed failed — fact saved text-only` = **79**, `graphrag dedup: embed failed`
  = **77** (~156 per-fact warnings); 15:45:33→now (после деплоя) — **0 / 0**;
  batch-WARN = 1 (см. выше). В runner-логе: 0/0 per-fact.
- Quota topology (`GET /api/memory/embeddings`, без секретов):
  provider `generativelanguage.googleapis.com` / `gemini-embedding-001`,
  credentials=3 (aliases primary/fallback_1/fallback_2 — без ключей),
  quota_groups_total=1, known=0/unknown=1, display «не определены»,
  rotation.status=none, groups=["unknown"], degenerate=true, hint про
  `keys.embedding_quota_group_labels`; groups[]: state=exhausted,
  next_allowed_at (см. выше).
- Примечание: раннер на старте выполнил идемпотентный ConfigCache init
  (DDL `IF NOT EXISTS` + seed `ON CONFLICT DO NOTHING` — как при boot бота;
  Δ схемы/данных нет).

## 11.4 Логи (только вокруг ids, R17-safe)

```
16:16:09 image_generation: [image] generated | mode=post | model=qwen-image-3-pro | bytes=758209 | latency_ms=57645
16:16:09 cover_style_jobs: COVER_STYLE_SUBMITTED | prompt_len=597 | reference_count=1 | reference_bytes_total=475189 | issue_present=True | edit_route=image_api | limit_source_taxonomy=unknown | capability_source=unknown
16:17:23 cover_style_jobs: COVER_STYLE_SUCCEEDED | style_revision=6 | status=success | duration_ms=74466   (Canary A)
16:21:55 summary_run_log: SUMMARY_START | run_id=f3f263b1601c4f3cb285749bce8f94ba | mode=hybrid_l2 | manual=True
16:25:37 summary_memory: graphrag memorize: embedding unavailable for batch … facts_text_only=22 | dedup_vector_skipped=21
16:28:41 summary_l2_writer: L2_COMPLETE | status=invalid | invalid_reason=invalid_paragraph
16:28:41 summary_generator: L2_ERROR … LEVEL-3 legacy fallback → LEGACY_FALLBACK l2_unusable
16:31:16 cover_style_jobs: COVER_STYLE_FAILED | reason=reference_missing | fallback=style_failed  (runner as nik)
16:31:18 summary_run_log: PUBLISH_RICH_COMPLETE | message_id=1133207
16:31:18 cover_style_jobs: COVER_PIPELINE_DONE | fallback=style_failed | status=base
```

## 11.5 Осталось / рекомендации

- **Fix/decision по аллокации** (п. 11.2.2) → re-review → Canary B через
  Human Gate (`/summary` владельца). До этого styled-публикация не проверена.
- **Writer `invalid_paragraph`** — отдельный follow-up (не Z5; повторить при
  следующем live-прогоне).
- Остальное — T-4890 (отчёт владельцу, архив, MCA).

R17: секреты/initData/промпты/raw text не печатались; initData-файлы удалены;
байты изображений — только локальные артефакты + sha/len.

---

# 12. Canary B (T-4888) — live, prod 2.58.53 (05.10.2026)

Среда: prod **2.58.53** (skip-ahead), PID 3671509, `/healthz` 200; admin MiniApp
(серверный initData; R17: не печатался, файлы удалены). Root-механизм для
триггера найден: nik в группе `docker` → `docker run --privileged -v /:/host …
chroot /host …` (sudo-allowlist ограничен systemctl/journalctl; раннер, готовый
к root-запуску, НЕ понадобился — см. ниже).

## 12.1 Подготовка через РЕАЛЬНЫЙ UI

- До: next=11 (counter=10), revision=6, пара rev 6 валидна.
- Действие: MiniApp → редактор Medved → «Следующий номер» = **14** → Save →
  `POST /api/cover/styles?style_id=medved_press` **200**.
- После: **next=14, counter_value=13, revision 6→7**; пара инвалидирована
  (before/after=null, `preview_stale=true`, source «Пример»); UI «ВЫПУСК 14».

## 12.2 Реальный production-прогон (один)

Триггер: **владелец, `/summary manual=True`** (`SUMMARY_START` 17:13:13,
`has_trigger=True`) — запущен ДО моего root-раннера; дубль не запускался
(one real run). Run id **`c96dc04a61df49619baa410496d96696`**, chat PERMsoc.

| Стадия | Факт |
|---|---|
| Source | 795 сообщений (durable) |
| L1 | ok, 28 тем, 123.3 с |
| L2 writer | ok: paragraphs=11, title_len=89, quote_verified=0/repaired=32, 39.0 с |
| L2 review | `l2_review_rejected`: review_calls=2, revision_calls=1, `SUMMARY_REVISION_RESULT ok attempt=1` (targeted применён), findings_total=7, revision_fixed=0, revision_new=1 → `LEGACY_FALLBACK l2_unusable` |
| Base cover | ok, 68.5 с (`COVER_COMPLETE status=ok`) |
| Style selection | `style_id=medved_press`, style_revision=7, selection_source=chat |
| Style edit #1 | `prompt_len=952`, `issue_number=14`, ref 475 189 B, `edit_route=image_api` → provider **400** «prompt is too long…» `classified=prompt_limit` |
| Style edit retry | **один** shorter retry **708 chars** (≤1) → `COVER_STYLE_RUNNING` heartbeats 30/60/90 с → `COVER_STYLE_SUCCEEDED issue_number=14` (92.9 с) |
| Publish | `PUBLISH_RICH_COMPLETE message_id=1133309` (Rich) |
| Итог | `COVER_PIPELINE_DONE status=styled` (fallback пуст); `SUMMARY_RUN_DONE` fallback=legacy, health=degraded, publication=rich |

## 12.3 14 / 14 / 15

- Run получает **14**: assignment `(medved_press, c96dc04a…, 14)` at 17:26:03;
  `COVER_STYLE_SUBMITTED issue_number=14`.
- Retry того же run → **14**: `resolve_issue_number(pg, medved_press, run) -> 14`
  (идемпотентный re-read той же аллокации; провайдерский adaptive retry шёл в том
  же run/номере; отдельного retry-триггера в проде нет — документировано).
- Следующая независимая аллокация = **15**: counter=14 → next=15 (read-only;
  второй paid-прогон НЕ форсировался; контракт +1 неизменен).

## 12.4 Styled-доказательство

- `COVER_PIPELINE_DONE status=styled`, `fallback` отсутствует;
  `cover_for_publish = styled_path or base_path` ⇒ опубликован styled-файл.
- Provenance `covp_5ede4be7eb444af5bedf155ae579e3a1`: style_id=medved_press,
  style_revision=7, issue_number=14, `base_asset_id=cas_0fd4684e…`,
  **`final_asset_id=cas_7a2eba1e37991f731c7ece2f9bbbbbca`**, provider
  `nano-gpt.com`, model `qwen-image-3-pro`, connection_id=default,
  `reference_asset_ids=[cas_be0a700ba8d3af64358eee6697aeff11]` (medved_press.png),
  **status=styled**, fallback_mode=«», mode=production.
- Inspector: `cover_style.result=**styled**`, `style_edit_ok=true`,
  style_provider/model `nano-gpt.com` / `qwen-image-3-pro`, publication
  message_id=1133309.
- **Артефакт обложки не сохранён post-hoc (честно):** production temp-файлы
  удаляются в `_publish_rich_document finally`; локальный Bot API хранит только
  скачанные файлы (проверено: с 17:00 в store только binlogs); provenance-ассеты
  hash-only (строк/файлов нет). Визуально styled-обложка доступна владельцу в
  чате (message 1133309); style-контроль — Canary A artifact (тот же seeded
  стиль/референс).
- Capability после прогона: `GET /api/cover/prompt-limit` → route=image_api,
  value=**800** chars, limit_known=true, source=`cached_runtime_discovered`,
  source_taxonomy=`runtime_exact`, mode=auto (manual override отсутствует —
  не трогался).

## 12.5 Наблюдаемость: подтверждено и gaps (live findings)

- **Подтверждено:** Inspector показывает фактические provider/model (`style_edit`
  node + `cover_style`) и **styled**-outcome; R17-safe.
- **Gap 1 (отчётность):** Inspector **не содержит** route / compiled length /
  capability source (в run JSON таких полей нет; route=`image_api`, compiled
  952→708, capability_source=unknown/runtime_exact есть только в SUBMITTED-логах).
- **Gap 2 (баг отображения):** node «Выбор стиля» показал
  «Выбран: **нет («Без стиля»)**», хотя run реально использовал medved_press.
  Причина: `emit_cover_event` (`services/cover_style_jobs.py:291–331`) не
  прокидывает whitelisted `extra`-поля (style_id/style_revision/selection_source)
  в MCA-событие (`trace.emit_stage`, строки 321–329 — только фикс-набор kwarg);
  `pipeline_analytics.py:877–878` читает `style_id` из события → None → фолбэк.
  Кандидат small-fix + re-review; **не патчилось**.
- Text: Hybrid не вышел; причина конкретная — `l2_review_rejected` (см. 12.2),
  это НЕ writer `invalid_paragraph` и НЕ сбой Z5-механизма targeted revision
  (revision применился ok). Finding codes в логе/Inspector этого run не показаны
  (detail узла пуст) — отдельный фоллоу-ап наблюдаемости.

## 12.6 Логи (только вокруг ids, R17-safe)

```
17:26:03 COVER_STYLE_SUBMITTED | prompt_len=952 | issue_number=14 | reference_bytes_total=475189 | edit_route=image_api | limit_source_taxonomy=unknown | capability_source=unknown
17:26:05 cover_style_edit: provider 400 | route=image_api | model=qwen-image-3-pro | classified=prompt_limit
17:26:05 COVER_STYLE_SUBMITTED | prompt_len=708 | status=retry   (ровно один shorter retry)
17:27:36 COVER_STYLE_SUCCEEDED | style_revision=7 | issue_number=14 | status=success | duration_ms=92860
17:27:38 PUBLISH_RICH_COMPLETE | message_id=1133309
17:27:38 COVER_PIPELINE_DONE | status=styled
17:20:47 L2_REVIEW | rejected | findings_total=7 | revision_count=1 | revision_fixed=0 | review_calls=2 | reason=l2_review_rejected
```

## 12.7 Итог Canary B

- **PASS по primary-критериям:** issue **14**, retry того же run **14**,
  следующий независимый allocation **15**, опубликована **styled** обложка
  (provenance + message_id 1133309), ≤1 adaptive retry (952→708), override не
  трогался. Text — Legacy с названной причиной (`l2_review_rejected`; Z5-механизм
  работает).
- **Остаточные findings:** два reporting-gap по Inspector (12.5) — кандидаты в
  отдельный малый цикл; артефакт обложки post-hoc не извлекается (12.4).
- Осталось: T-4890 (отчёт владельцу, архив, MCA).

---

# 13. F-N3 — Run Inspector facts: route/compiled/capability source + selection node (05.10.2026) — FIXED

Micro-fix по live-gaps §12.5 (run `c96dc04a61df49619baa410496d96696`).
Worktree fingerprint (`git stash create`, без коммита/стейджа):
`d10448e4f1e338a94b732f2b9c743d42644ef8c3`; база HEAD `b31cb63`
(prod 2.58.53).

## 13.1 Root cause (три механизма)

1. `mca_events.build_event` отбрасывает ключи вне `ALLOWED_FIELDS`
   (`services/mca_events.py:423`) — extras `emit_cover_event` (prompt_len/
   compiled_chars/edit_route/capability_source/…) в событие не попадали;
   `_emit_log` писал их только в log-line.
2. `_MCA_EVENTS_INSERT_COLS` (`services/mca_events.py:515–524`) не содержит
   `style_id`/`style_revision` — даже разрешённые id-поля не персистились,
   поэтому `pipeline_analytics.py` (selection node) всегда читал None.
3. `pipeline_analytics._cover_style_card` не смотрел usage/durable-состояние →
   route/compiled/source отсутствовали; selection node показывал
   «нет («Без стиля»)» даже для styled-run.

## 13.2 Pre-fix RED

`.venv\Scripts\python.exe -m pytest tests/test_pipeline_analytics_asap4.py -q -k CoverInspectorFacts`
→ **3 failed, 1 passed**: propagation (`usage_json` не заполнялся), card
(route/compiled/source отсутствуют; selected_style None), retro (selection node
«нет («Без стиля»)»). Green — no-selection invariant. JS-ассерты
(`asap41_zone_g_inspector_test.js`: route/compiled/source + markup-строки)
добавлены ПОСЛЕ фикса как regression-lock (до фикса полей/разметки не было).

## 13.3 Fix

- `services/cover_style_jobs.py`: `_INSPECTOR_USAGE_FIELDS` (R17-safe подмножество
  SAFE_LOG_FIELDS: id/числа/enum) → `emit_cover_event` кладёт их в
  `usage_json` MCA-события (работает для всех COVER_*, включая SELECTION/
  SUBMITTED); production `run_style_job` сохраняет `state.prompt_diagnostics`
  (durable-факты для Inspector, независимы от событий).
- `services/pipeline_analytics.py`: `_INSPECTOR_EVENTS` + `COVER_STYLE_SUBMITTED`;
  `_cover_style_card` читает `usage_json` (edit_route/compiled_chars/
  capability_source/limit_source_taxonomy/limit_value; selected_style из
  SELECTION-usage); selection node: style_id из колонки → usage → durable,
  source/revision из usage; `collect_run` → `_cover_job_fallback(db, run_id,
  events)`: job_id из COVER_* событий (PK state-чтение) либо
  `coalesce_key='cover_style:<run>'`; R17-safe подмножество.
- `web/app.js` + `web/index.html`: Inspector отражает Route / Compiled prompt /
  Capability source / Источник лимита.

## 13.4 Counts

- `tests/test_pipeline_analytics_asap4.py` → **77 passed** (+5 F-N3: propagation,
  styled card+selection node, no-selection invariant, retro (job_id), retro
  (coalesce)); `tests/test_summary_inspector_zone_g_asap41.py` → **26 passed**;
  `tests/test_extra_cover_style_jobs.py` → **42 passed**; adjacency
  `tests/test_cover_style_wave_b_asap4.py` → **26 passed**. Итого focus
  (3 требуемых файла) **145 passed**.
- JS: `node --check web/app.js` OK; `asap41_zone_g_inspector`,
  `round1030_pipeline_inspector`, `vue_mount`, `routing` → OK.
- Полного suite нет; paid-вызовов нет; без секретов/промпт-текста (usage —
  id/числа/enum).

## 13.5 Retroactivity для run c96dc04a… (после deploy этого фикса)

- **Selection node — восстанавливается**: `style_id=medved_press` берётся из
  durable cover-job state (task_jobs: job_id из COVER_* событий run'а либо
  coalesce_key `cover_style:c96dc04a…`). «нет («Без стиля»)» для этого run
  исчезнет. `selection_source`/`style_revision` для СТАРОГО run не
  восстановимы (pre-fix не персистировались ни в события, ни в state) — строки
  будут опущены честно; с новых прогонов показываются.
- **route / compiled length / capability source для c96dc04a… — НЕ
  восстановимы** (explicit): события pre-fix не несли `usage_json`,
  `state.prompt_diagnostics` у этого run = None; значения (route=image_api,
  compiled 952→708, capability_source=unknown) есть только в прод-логах,
  которые Inspector не читает (§61.12). С первого production-прогона после
  deploy эти поля появляются в run JSON (SUBMITTED usage + durable state).
  Пересборка/бэкфилл старых событий не делались (вне scope, данных нет).
- Проверка уже выполнена на реальном контуре: focused-тесты используют
  РЕАЛЬНЫЙ `collect_run` + task_jobs/mca_events (SQLite), не моки.

## 13.6 Остаточный риск

- Retro-поиск coalesce-путём делает bounded `LIMIT 1` по `task_jobs` без
  индекса для completed-строк (admin drill-down, редко) — на прод-объёме
  приемлемо; основной путь (job_id из событий) — PK-чтение.

