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
