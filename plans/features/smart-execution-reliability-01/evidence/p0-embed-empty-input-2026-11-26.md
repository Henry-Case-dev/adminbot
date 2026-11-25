# P0-EMBED-EMPTY — `LLM HTTP 400 … embeddings` (R247-DEP-N1), 2026-11-26

Bounded triage of the post-deploy signal from release 2.58.247 and the minimal
fix. Production was **not** touched (no deploy, no merge, no map/queue edits).

| | |
|---|---|
| Base | `f2cb38c8412506261504b4000f7a7a53be143851` (2.58.247, branch `release/p0-2.58.247`) |
| Candidate | **`7686d6fcd`** — branch `fix/p0-embed-empty-input` (parent `f2cb38c84`) |
| Evidence commit | this file (branch `fix/p0-embed-empty-input`) |
| Signal source | `plans/features/unified-reply/evidence/release-2.58.247/deploy-2.58.247.md` §7, `open_signal.R247-DEP-N1` |
| Classification | **(b) pre-existing path that got more traffic** — not introduced by 2.58.247 |

## 1. The production signal (as measured by the deploy run)

* 11 × `LLM HTTP 400 | url=…/embeddings` in three clusters (12:20:59–12:21:02,
  12:26:05–12:26:09, 12:37:24–12:37:27Z), body
  `EmbedContentRequest.content contains an empty Part` /
  `Invalid input: input cannot be empty`.
* All three embedding legs (primary nano-gpt, fallback_1/2 Google) went into a
  60 s cooldown → `EmbeddingNoUsableCredential` → `graphrag memorize … facts
  saved text-only` + one `EMBED_API_DEFERRED` per batch.
* 7 days before the deploy the same 400 occurred **1** time (general embed
  transport failures in the same window: 1516, `EMBED_API_DEFERRED`: 53), i.e.
  the degradation class is pre-existing.
* Correlates with media-only messages (audio 5, photo 2, empty text).
* No data loss; saved facts non-empty; user answers unaffected.

## 2. Cause in code (path, `f2cb38c84` line numbers)

Media-only message → direct answer path:

1. `services/direct_chat_service.py:18056`
   `query = getattr(message, "text", None) or ""` — for a photo/audio message
   without caption/text, Telegram's `message.text` is `None`, so the RAG query
   becomes `""` (no empty-query guard on this path).
2. `_build_rag_block` → `_rag_unified_rows` (`direct_chat_service.py:17137`) →
   `_rag_retrieve` → `mca_retrieval_context.retrieve`
   (`services/mca_retrieval_context.py:2760`). `request_reason_code`
   (`:1469`) validates purpose/limit only — an empty `query` is accepted.
3. Vector channel (`mca_retrieval_context.py:3192`, call at `:3263`) →
   `MemoryManager.retrieve_fact_candidates`
   (`services/summary_memory.py:6086`) → `_search_graph_facts`.
4. `services/summary_memory.py:6380`
   `vectors = await self._embed([query], priority=_PRIO_QUERY)` — **no
   empty-query guard**, while the FTS branch two lines below is guarded
   (`if not match_query: return []`, `:6410`) and `fetch_golden_facts` already
   guards (`:6335`). So `_embed([""])` is issued.
5. `MemoryManager._embed` (`:3401`) has only `if not texts: return []` — a
   non-empty list containing `""` passes through
   `_embed_api` → control plane `execute_embed`
   (`services/embedding_control_plane.py:2114`) → `EmbeddingExecutor.embed`
   (`:1520`, only `if not texts`) → `EmbeddingProviderAdapter.embed_batch`
   (`:1318`) → `llm_client.embed_once` (`services/llm_client.py:3059`) →
   `POST {base}/embeddings` with `input: [""]`.
6. Provider rejects the whole request (Gemini: empty Part) with HTTP 400.
   `EmbeddingExecutor._on_error` (`embedding_control_plane.py:1963`) classifies
   429/auth/programming errors explicitly; a 400 falls through to the
   **transport** branch (`:2059`), so the leg is parked with
   `_PROVIDER_UNAVAILABLE_COOLDOWN_S = 60.0` (`:1435`, `_park_transport_credential`
   `:1891`). Three legs → 60 s of `EmbeddingNoUsableCredential` → the facts
   written in that window stay text-only. This matches the observed log order
   exactly (400s first, then `facts saved text-only`).

Same class at other boundaries (all pre-existing):

* `summary_memory.py:7144` `period_fill_candidates` → `_embed([str(query or "")])`.
* `summary_memory.py:5763` `_save_graph_fact_embedding` → `_embed([fact])`
  (a whitespace-only triplet sentence would be embedded and stored).
* `summary_memory.py:7978` `_save_archive_embedding` → `_embed([fact])`.
* `summary_memory.py:3825/3911` backfill batches → `_embed([row["fact"] …])`
  (a legacy blank row would poison the whole batch).

Attribution check against the release diff (`78abc866c..f2cb38c84`):
`summary_memory.py`, `embedding_control_plane.py` and `llm_client.py` are
**absent** from the delta; `_embed([query])`, the `query = … or ""` line and the
empty-list-only guards are identical at 2.58.246 (verified with
`git show 78abc866c:…`). 2.58.247 added media traffic (slice C) and the
lane-B retrieval wiring, which is why a rare pre-existing path appeared
11 times in 25 minutes. It is not a release regression.

## 3. Chosen minimal behaviour

Blank text is not an embed request; the item degrades on the existing path:

* all-blank input to `MemoryManager._embed` → **no network call**, empty result
  (same convention as the existing `if not texts: return []`);
* blank query → no semantic leg: `_search_graph_facts` returns `[]` (identical
  final result to today's FTS fallback, which also returns `[]` for empty
  keywords), `period_fill_candidates` returns `[]` with
  `vector_leg="empty_query"` (not reported as `vector_unavailable` — no query is
  not an outage);
* blank fact → text-only (existing `batch.text_only` accounting for graph facts,
  silent FTS/source retention for archive facts);
* blank DB rows are excluded from backfill batches (zip stays aligned).

No new breaker, flag, retry loop, store, model or reason-code enum. Existing
credential-health/cooldown semantics untouched.

## 4. Blast radius

* Embedding model, endpoint, dims, identity/MSI, stored vectors and indexes:
  untouched (no writes to `graph_facts_vec`/`smart_archive`, no rebuild).
* `llm_client` / control plane untouched — the 400-classification is unchanged
  (a real invalid request still parks a leg; only blank input is prevented).
* Non-empty text takes the previous path byte-for-byte.
* Lane approvals (finalization/lore A, memory relevance B, canon P0GM C) are
  not touched: no prompt, contract or retrieval-selection change. The only
  retrieval-visible addition is `vector_leg="empty_query"` for a blank query,
  which `_vector_unavailable_reason` treats as benign.
* Flags: 0. DDL/migrations: 0.

## 5. Tests

New discriminating test: `tests/test_p0_embed_empty_input.py` (8 cases) —
records the actual texts that would reach the provider.

RED on `f2cb38c84` (`raw-red-base-f2cb38c84.txt`): **6 failed, 2 passed**

```
embed_calls == [['']]            # _search_graph_facts("")
embed_calls == [['   \n\t ']]    # whitespace query
embed_calls == [['']]            # retrieve(query="")  ← production chain
embed_calls == [['']]            # period_fill_candidates("")
_save_graph_fact_embedding("   ") -> written True  (vector stored for blank)
_save_archive_embedding(" \t ")   -> embed_calls == [[' \t ']]
```

GREEN on `7686d6fcd` (`raw-green-candidate-7686d6fcd.txt`): **8 passed**
(blank query/fact → provider not called, item still handled; non-empty query
and non-empty fact → exactly one call with the original text, vector written).

Affected suites (candidate vs base, same commands, `-p no:cacheprovider`):

| Batch | Candidate `7686d6fcd` | Base `f2cb38c84` |
|---|---|---|
| 20 memory/graphrag/summary files | 576 passed, 5 failed | 576 passed, 5 failed — **same 5 IDs** |
| 12 retrieval/direct-chat/p0-relevance files | 363 passed, 1 failed | same failure reproduced on base |
| 10 vmq/embed/turn-trace files | 213 passed, 1 failed | same failure reproduced on base |
| 6 graphrag/embed core files | 299 passed, 0 failed | — |

Pre-existing failures (identical on base, unrelated to this change):
`test_memory_quality_contract_07.py::test_cron_path_creates_fact_and_links_edge`,
`::test_subject_ref_resolves_for_world_knowledge` (`'third_party' ==
'world_knowledge'`), `test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced`,
`test_asap5_graphrag_recovery.py::test_resume_ticker_starts_once_and_reports`
(order-dependent in the 20-file batch, passes isolated on both),
`::test_warning_coalesced_not_repeated`,
`test_speech_p0_a2_memory.py::TestSelfEchoNotFactual::test_style_anchors_not_broken`
(`RuntimeError: coroutine raised StopIteration` in the test harness),
`test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year`
(`assert 4 <= 2`). Raw logs: `raw-affected-batch20-{candidate,base-f2cb38c84}.txt`,
`raw-pre-existing-2-{candidate,base-f2cb38c84}.txt`.

`py_compile` of both changed modules + the test: OK. `git diff --check`: clean.

## 6. Residuals (honest, not blockers)

1. **A real 400 is still classified as a transport failure** and parks a leg for
   60 s (`embedding_control_plane._on_error`, no 4xx-invalid branch). This fix
   removes the blank-input trigger only. A genuinely malformed request from a
   future caller would still park legs; changing the classification is a
   separate policy decision (auth/429/5xx contracts) and was not taken here.
2. Mixed batches: only the backfill path can carry a blank element; it now
   filters blank rows, so no consumer can receive an unaligned vector list.
3. The `400`-body evidence comes from the deploy run (production journal); the
   provider was not called during this triage — no synthetic request was sent to
   nano-gpt/Google.
4. Not verified in production: the fix is code-only on a branch. Live
   confirmation (media-only message → no `LLM HTTP 400 … embeddings`, no leg
   cooldown) requires a deploy of this candidate, which is outside this
   assignment.
