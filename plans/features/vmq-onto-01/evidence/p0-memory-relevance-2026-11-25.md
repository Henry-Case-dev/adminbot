# P0 memory-relevance — lane B (owner 2026-11-25)

Scope: relevance, attribution, roles and temporal scope **in the existing
retrieval/package path** (owner input §3; §1/§6 constraints). No new memory
store, no new retrieval engine, no embedding-model change, no mass rebuild,
no mandatory LLM call per memory access, no trigger dictionaries, no queue/
map/gate changes. Acceptance framing follows
`plans/owner_inputs/2026-11-25-p0-acceptance-boundaries-amendment.md`
(concrete contract checks, not product-quality scoring).

- Base: `e3467ccb787709650af3f493a88861e60ac51684` (no DEPLOY OK evidence
  exists for 2.58.246 at start of work, per lane instruction).
- Branch: `fix/p0-memory-relevance` in
  `WorkspaceData/worktrees/…/p0-memory-relevance-6c8c01aa20ee-2d10622e`.
- Diagnostic probe: `plans/features/vmq-onto-01/evidence/p0-memory-relevance/probe_abcd.py`
  (local in-memory SQLite fixture, no production writes, no network, no
  embedding calls).

## 1. Established causes (file:line on base e3467ccb)

### RC1 — author / subject / addressee roles conflated end-to-end

| Where | What it does | Effect |
|---|---|---|
| `services/mca_retrieval_context.py:1903` | `build_memory_request` writes `addressee_uid` into `speaker_entity_id` | the recipient of the new text is declared the *speaker* of the material |
| `services/mca_retrieval_context.py:1901-1902` | addressee + reply-parent become `participants` | those people silently become the author allowlist (next row) |
| `services/mca_retrieval_context.py:2088-2090` (`_apply_filters`, same in `_split_range:1954`) | `participants` used as hard **author** filter | «поздравь Никиту» dropped every message written by other people *about* Никита |
| `services/mca_retrieval_context.py:3370` (`_fact_candidate`) | `author_id = speaker if speaker is not None else target_uid` | a fact *about* a person, spoken by someone else, is attributed to that person |
| `services/mca_retrieval_context.py:1789-1797`, `1800-1808` (`assess_relevance`) | subject match looks only at `subject_entity_id`/`subject_node_id`; verbatim messages carry none | a package made of the subject's own messages was reported `use_memory=False / subject_mismatch` |
| `services/mca_retrieval_context.py:1026-1029` | request contract has `subject_entity_ids`, `participants`, `reply_target_entity_id` — **no author axis** | «сообщения, написанные X» was not expressible at all |

### RC2 — the requested period was not applied to the material it constrains

| Where | What it does | Effect |
|---|---|---|
| `services/mca_retrieval_context.py:2833-2837` | message FTS gets a `since_ts/until_ts` window **only** when the caller sets `lexical_time_window` | original messages are read over the whole history while facts get the year |
| `services/mca_retrieval_context.py:2656-2659` | `period_intent` is computed only for `period_fill` and used for the facts pool | the year never reaches the messages leg of the package |
| `services/direct_chat_service.py:13134-13142` | live memory leg calls `build_memory_request(topic=query, addressee…)` — no period, no author | a year in the request never reaches retrieval |
| `services/direct_execution.py:662` | deterministic `query_chat_memory` step passes `{"query": …}` only | `year_from/year_to/author` supported by the tool are never filled → count over all time (the «40 475 за четыре года» shape) |

### RC3 — prefix-OR volume acted as the relevance verdict

| Where | What it does | Effect |
|---|---|---|
| `services/mca_retrieval_context.py:2625-2628` | `match = build_fts_query(keywords, mode="prefix_or")` over **all** tokens, including 1–2-char service words | `"в"*`, `"с"*`, `"за"*` expand the pool to the corpus; measured: a message «Видел.» matched the query «днюха в стиле» |
| `services/mca_retrieval_context.py:3100-3104`, `3250-3251` (`_sort_key`) | order = channel weight − position + recency bonus; no content-coverage signal | the freshest service-prefix match outranks the message that matched the subject term (reproduced, see §2) |
| `services/tool_router.py:2822-2840` (base) | first line of the tool result is prose «Широкий поиск (префиксы, не морфология): 9377 сообщений …» | retrieval diagnostics become the opening of the generative context → narrated instead of the requested work |

## 2. Compact A/B/C/D replay (local fixture, real code paths)

Fixture: one chat, Никита = 777 (his own congratulation texts 2023/2024/2025),
888/999 = other participants (congratulations *to* Никита, plus unrelated
messages). Writer is not invoked (no network): D is the material control.
Numbers are counts of candidates by role/period, not answer-quality scores.

| Variant | Items | Author-originals (777) | Other people / irrelevant | Period violations | Verdict |
|---|---|---|---|---|---|
| **A** base direct memory leg (`build_memory_request`, addressee=Никита) | 2 | 2 | 0 (others **dropped** by participants-as-author) | 1 (2024 included for «за прошедший год») | `use_memory=False / subject_mismatch` |
| **A** after fix, same call | 6 | 2 | 4 (2 about the subject, 2 unrelated) | 0 (no horizon invented) | `relevant` |
| **A2** after fix, explicit `author_uid` + 2025 | 1 | 1 | 0 | 0 | `relevant` |
| **B** existing FTS with author + year (`search_messages_fts(author_ids, since/until)`) | 1 | 1 | 0 | 0 | — |
| **C** hybrid retrieval without constraints (facts/vector/lexical, `memory=None`) | 6 | 2 | 4 | not applied | — |
| **D** Writer control set (known-good originals) | 1 | 1 | 0 | 0 | — |

Reading: A ≈ C — the package is dominated by material that matched service
prefixes (67 % not the author's speech), and the one structural constraint the
user gave (period) was not applied. B (the "simple search" the owner asked to
compare against) is already exactly right — the advanced pipeline simply did
not use its filters (RC2), and it replaced the author with the addressee
(RC1). After the fix the same package path produces B/D-shaped material
(A2: 1 author-original, 0 foreign, in period).

Locations of quality loss (explicit): **candidate acquisition** (no author/
period constraint, prefix-OR over service words) and **role mapping**
(addressee→speaker→author allowlist). Not intent interpretation, not vector/
graph quality, not packing.

## 3. Fix (smallest common mechanism)

`services/mca_retrieval_context.py`
- `RetrievalRequest.author_entity_ids` — explicit author axis, separate from
  subject (about whom), participants (prior only) and reply target.
- `_apply_filters` / `_split_range`: author constraint comes from
  `author_entity_ids`; `participants` no longer acts as an author allowlist
  (kept only for the accepted `scope="participants"` speech slice).
- `_fact_candidate`: `author_id` = real `speaker_author_id` only; unknown
  author stays `None` (subject stays in `subject_entity_id`).
- `build_memory_request(author_uid=…, author_uids=…)`: addressee is no longer
  declared "speaker"; author(s) fill the author axis.
- `retrieve`:
  - author pushdown into the existing message FTS (`author_ids=…` in SQL
    before LIMIT, only when the constraint is present);
  - the period of an explicit year is applied to **original messages** too
    (same `since_ts/until_ts` + `order="time"` plan already used for year
    windows), not only to the facts pool;
  - new bounded `author_window` channel: `get_chat_history_messages` (existing
    read) filtered by the explicit author inside the period — thin result is
    expanded *within* the user's constraints instead of by random memories.
    Active only when both author and period are known → zero new reads
    elsewhere;
  - prefix-only matches (matched solely by service/short prefixes, same §2
    morphology the module already uses) are ranked **after** content matches
    by a stable partition — they are not dropped, so differently-worded
    material stays reachable;
  - `_candidate_matches_subject` counts a person's own verbatim message as
    subject material (removes the false `subject_mismatch` verdict).
- `services/direct_execution.py`: the deterministic `query_chat_memory` step
  passes `year_from/year_to` when the query names an explicit year
  (`resolve_period_intent`, existing deterministic parser — no new word list).
- `services/tool_router.py`: memory tool result is rendered as
  material (verbatim messages) → derived facts (labelled) → a separate
  trailing service block (`<поиск_служебное>`: method, count, shown, period,
  range). Numbers are preserved for count questions and diagnostics; they are
  no longer the opening line of the generative context.

## 4. Tests

New `tests/test_p0_memory_relevance.py` (11 tests, real SQLite, real reads,
`memory=None` so no provider dependency):

| Contract check | Test | base | fixed |
|---|---|---|---|
| addressee ≠ author filter | `test_addressee_is_not_an_author_filter` | RED | GREEN |
| explicit author selects only that author | `test_explicit_author_constraint_selects_only_that_author` | RED | GREEN |
| fact about person not attributed to person (speaker present) | `test_fact_about_person_is_not_attributed_to_that_person` | GREEN (guard) | GREEN |
| fact without speaker has no invented author | `test_fact_without_speaker_has_no_invented_author` | RED | GREEN |
| source author ≠ new recipient (request contract) | `test_request_keeps_source_author_and_recipient_apart` | RED | GREEN |
| material authored by source, not recipient | `test_material_is_authored_by_source_not_recipient` | RED | GREEN |
| period applied to the author's own messages | `test_year_window_applies_to_author_messages` | RED | GREEN |
| no invented horizon without a period | `test_without_period_no_year_window_is_invented` | RED | GREEN |
| thin result not filled with other material | `test_thin_result_is_not_filled_with_other_material` | RED | GREEN |
| service-prefix match does not outrank content match | `test_service_prefix_match_ranks_below_content_match` | RED | GREEN |
| service metadata not opening the narration surface | `test_counts_do_not_open_the_result` | RED | GREEN |

Ran on base (`e3467ccb`, same test file copied into a detached worktree):
**10 failed, 1 passed**. On the candidate: **11 passed**.

Updated to the new structural contract (same intent, new rendering):
`tests/test_tool_router.py` (4 assertions), 
`tests/test_mca15_chat_statistics_round1028.py` (2 assertions) — they asserted
the old prose header «Широкий поиск (префиксы …): N сообщений …» that is the
defect itself.

Regression runs (candidate tree, `-p no:cacheprovider`):
- memory/retrieval/mca07/mca22/tool_router group: 3 failures, all pre-existing
  on base (`test_memory_quality_contract_07` ×2, `test_speech_p0_a2_memory`).
- direct group (`test_direct_context_scenarios_asap3`,
  `test_direct_fallback_recompose_asap32`, `test_direct_l1_corrective_r1`):
  7 failed / 26 passed — the same 7 fail identically on base.
- targeted suites: `test_memory_unified_retrieval`, `…_06`,
  `test_memory_period_vector_leg`, `test_mem_time_policy`,
  `test_vmq_mem_*`, `test_ur_13_memory_types_scale`, `test_memory_identity`,
  `test_mca07_retrieval_context_round1027`, `test_history_isolation`,
  `test_ur_c_3_real_fts`, `test_ur_context_selection`,
  `test_tool_router`, `test_mca15_chat_statistics` — green, **кроме**
  `test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::
  test_quota_is_bounded_by_slots_and_never_adds_current_year`, который падает
  идентично на базе (пре-существующее; см. §6/N1).
- `py_compile` on changed modules/tests: OK; `git diff --check`: clean.

Pre-existing failures reproduced unchanged on base (not caused here):
`test_direct_context_scenarios_asap3::test_lag400_middle_topk_under_pressure`,
`test_direct_fallback_recompose_asap32` (5),
`test_direct_l1_corrective_r1::test_build_l1_context_bot_replies_caps_and_limit`,
`test_memory_quality_contract_07` (2),
`test_speech_p0_a2_memory::test_style_anchors_not_broken`.

## 5. Residuals (factual)

1. **Originals are still lexical-only.** Messages have no embeddings
   (`smart_archive`/`graph_facts_vec` index facts, not messages), and
   `text_morphology.stem_word` is a light suffix stripper, so
   «поздравление»* does not reach «поздравляю». The `author_window` channel
   bridges this only when author **and** period are explicit; without them a
   differently-worded original can still be missed. Fixing that needs a new
   message index/embedding rebuild — explicitly out of this P0.
2. **Автор материала доезжает до retrieval только при структурном сигнале
   плана.** `author_entity_ids` заполняется (а) явным `author_uid`/`author_uids`
   у вызывающего и (б) plan-driven пересборкой RAG-блока: `target_user_id`
   плана считается автором материала ТОЛЬКО когда `capabilities_needed`
   содержит read-only capability существующего материала
   (`chat_memory`/`historical_search`). Без такого сигнала названный человек
   остаётся получателем (смешивать роли запрещено). До плана (live-selection
   нога) автор по построению неизвестен — там доезжает только период; это
   честная граница, а не «honoured end-to-end» (прежняя формулировка
   остатков была неверной, см. §6/F2).
3. **«За прошедший год» without a calendar year** is not converted into a
   rolling window server-side; the step passes a year only when the user named
   one (existing deterministic parser). Relative-period interpretation stays
   with L1.
4. **`author_window` — bounded выборка по автору и годам** (после review r1:
   существующее чтение `get_author_message_periods` с аддитивным `years`,
   берутся СВЕЖИЕ строки каждого года, а не первые строки окна). Годовая
   квота = `limit//5`, поэтому за один год приходит ограниченное число
   последних реплик автора, а не весь год: ресурсная граница, не полный
   экспорт.
5. **Prefix-only demotion is order-only.** Such material stays in the package
   (it may be the lexically different correct sample); with thin material it
   will still reach the Writer.
6. **Service block is separated and labelled, not hidden.** Whether the model
   narrates it remains model judgement; the count stays available because count
   questions need it.
7. During the ad-hoc fixture probe `search_graph_facts_fts` returned no rows
   for a directly inserted fact; not investigated further (facts attribution
   is covered by unit-level tests, and the fact channel was not the cause
   under repair). Flagged as observation only.
