# Nostalgia Seam — Frozen Contract
**Feature:** smart-module-semantic-routing / NOST-PROACTIVE  
**Date:** 2026-11-10  **Status:** NOSTALGIA SEAM RECONCILED

## 1. In-conversation seam

**Call site:** `InitiativeObserverRunner._act_on_memory_recall`, immediately after the
opportunity evaluator returns `kind=memory_recall`; it does not wait for
`nostalgia_tick`.

```python
result = await nostalgia_worker.recall_in_conversation(
    chat_id: int,
    memory_refs=(),       # refs to real retrieved records: story:/episode:/lore:
    context_rows=None,    # current conversation window
)
# result: {"status": str, "reason_code": str | absent}
```

`now` is an optional keyword accepted by the implementation for deterministic
clocking: `now: int | None = None`. `context_rows` may be omitted; the worker
then obtains its recent context. The worker resolves only real records by
`memory_refs`, reconstructs the episode from factual source messages, and uses
the existing Writer/Decision/SendRecheck/publication transport. It does not
make the evaluator's publication decision and does not create a second send
path.

Statuses are `sent`, `skipped`, `silent`, `disabled`, or `error`; silence is a
normal non-exceptional outcome. Skips/errors carry a stable `reason_code` when
available. Invalid, missing, repeated, unavailable, or non-relevant records
must not be invented or published.

## 2. Evaluator memory context

When `random.uses.memory_recall` is enabled (factory default ON), the existing
GraphRAG retrieval, episode channel, supplies at most three real records in
`<Related_Memory>`, numbered 1..3. The evaluator may return optional
`memory_slot` (integer 1..3), but must choose `memory_recall` only when a record
is genuinely related to the current conversation and the conversation has
actually approached that subject. Records merely being present are not proof;
no suitable relation means `silent`/non-recall. The existing evaluator,
Writer, Decision and transport remain the authorities for relevance, text and
publication. Empty retrieval produces no memory block.

## 3. Candidate ranking and direction

Autonomous candidate ordering uses:
`0.65 * relevance + 0.2 * coverage + 0.1 * usage`, where relevance is the
retrieval signal (FTS topicality is only a weak fallback), coverage rewards an
unrecently used period, and usage rewards stale usage. Ties are resolved by
period freshness and episode start; repeats are excluded by stable
`story:/episode:/lore:` references. `last_used_in_chat_at` changes only after a
confirmed send.

```python
async def _direction_pick(
    self, chat_id: int, ordered: list[int], info: dict
) -> int | None
```

`_direction_pick` is the sole `RandomSourceService` integration. It can select
only an index within the equal-weight tie band; it returns `None` when there is
no tie band or the source is unavailable/deferred, preserving deterministic
order. It cannot establish memory truth, alter relevance/thresholds, turn a
non-memory into a memory, or oblige the evaluator/Writer to publish. All
selected material still comes from real records and the common publication
path.

## 4. Invariants, compatibility and safety

- Silence is valid and logged; no exception or forced fallback publication.
- One transport path: existing `_delegate_initiative` → `handle_initiative`.
- No user prompt, Personality Core or instruction text is rewritten.
- No new OFF/SHADOW default is introduced; the ready feature remains ON by
  default while explicit existing user/chat overrides are preserved.
- `RandomSource` is not persisted in the database or included in LLM payload.
- Retrieval failure degrades to no related-memory block; it must not fabricate
  records or force `memory_recall`.

**NOSTALGIA SEAM RECONCILED**
