# P0-FORENSIC-PROD — production facts (read-only)

- **Lane:** `P0-FORENSIC-PROD`
- **Source task:** `plans/features/p0-corrective-factcheck-speech/source-2026-10-24.md`
- **Authoritative clock:** prod server **UTC**, checked live `date -u` → `2026-10-23 17:55:01 UTC`
  (= local `2026-10-24 05:59 +12:00`; same instant, no clock conflict).
- **Prod version:** `APP_VERSION = 2.58.118`, `HEAD = 9ed68ee8`, service `active/running`,
  `NRestarts=0`, `MainPID=858447`, started `2026-10-23 17:51:39 UTC`, `/healthz` → 200 `{"status":"ok","version":"2.58.118"}`.
  > Lane brief assumed `2.58.117`; the box is already on **2.58.118**. The reported bad run happened on
  > the **previous** process `PID 847992` (see F-02), i.e. before that restart.
- **Read-only:** only `GET` APIs and `journalctl`/`systemctl show`/`git rev-parse` reads. No writes, no restarts, no chat messages.
- **SSH:** 2 connections total (1 short recon + 1 main session, one login each, 75 s apart). No retries.
- **Method:** MiniApp API with locally signed WebApp `initData` (owner admin ID) + one SSH session.
  Scripts kept in `OPENCODE_WORKFLOW_SCRATCH/p0-forensic/`; raw payloads in `evidence/raw/`.

Legend: **FACT** = directly observed in prod; **WARN** = real signal, scope limited; **HYPOTHESIS** = plausible, not proven.

---

## 1. Prompt registry: withheld values (full list, not two)

**FACT.** `GET /api/speech/blocks?speech_only=true` (global scope) reports `stale_values = 9`.
All nine rows below are held back (`withheld=true`), effective source = **`default` (factory)**.
`stored_sha12` = sha of the stored PG value; `effective_sha12` = sha of the layer actually resolved.

| # | block | pg_key | reason | stored_sha12 | effective_sha12 | eff chars |
|---|-------|--------|--------|--------------|-----------------|-----------|
| 1 | factcheck.base.single | prompts.factcheck_system_prompt | provenance_missing | `76c4beb11c63` | `c96d5817cf1a` | 4472 |
| 2 | search.base.system | prompts.search_system_prompt | provenance_missing | `ba43fb679db6` | `a1d2e653c449` | 2403 |
| 3 | summary.base.single | prompts.summary_system_prompt | provenance_missing | `d697b0745b29` | `5f096fc613a3` | 3374 |
| 4 | checkup.base.system | prompts.checkup_system_prompt | provenance_missing | `1e8a3c69cf7b` | `38d63d86b54d` | 2077 |
| 5 | youtube.base.system | prompts.youtube_system_prompt | provenance_missing | `e0a1ffaf18a1` | `65ec52f176c0` | 2073 |
| 6 | youtube.base.video | prompts.youtube_video_system_prompt | provenance_missing | `c8bba06ec6a8` | `a4794cd1d74e` | 2069 |
| 7 | web.base.system | prompts.webpage_system_prompt | provenance_missing | `7801085b6ef5` | `dccad8eafdfb` | 1895 |
| 8 | factcheck.base.verbalizer | prompts.factcheck_verbalizer_system_prompt | provenance_missing | `5fbf61cea310` | `83b4fb75500f` | 1599 |
| 9 | direct.base.l2_writer | prompts.direct_chat_verbalizer_system_prompt | **provenance_mismatch** | `83ff62bbee40` | `83ff62bbee40` | 3081 |

Facts and nuances:

- **FACT.** Rows 1–8 store content that **differs from the factory** (`stored_differs_from_factory=true`) and is
  discarded in favour of factory text. Row 9 holds a value **byte-identical to the factory**
  (`stored_differs_from_factory=false`) yet is still withheld because provenance metadata is missing/mismatched —
  so for `direct.base.l2_writer` the effective text is not harmed, only the owner's save is not "attested".
- **FACT.** `stored_chars` is only partially observable through the API. Confirmed from logs/migrations:
  `factcheck_system_prompt` = **4666** chars (`[prompt_migration] кастом юзера — НЕ трогаем`,
  2026-10-23 17:00:26 and 17:51:54 UTC), `factcheck_verbalizer_system_prompt` = **1712**,
  `checkup_system_prompt` = **2312** (`[prompt_registry] ... stored_sha=1e8a3c69cf7b`).
  For rows 2, 3, 5, 6, 7, 9 the exact `stored_chars` is **NOT_FOUND** in the read-only surfaces used
  (API returns only effective chars; journal printed no line in the sampled window).
- **FACT.** Journal since 2026-10-01 shows **409** `persisted speech value withheld` lines across **11** keys —
  i.e. the conflict is continuous, not a single-startup artefact:
  `direct_chat_system_prompt` 210 (missing), `direct_chat_verbalizer` 132 (missing) + 14 (mismatch),
  `summary_system` 17, `summary_narrator` 13, `factcheck_verbalizer` 6, `factcheck_system` 5,
  `search_system` 3, `checkup_system` 3, `youtube_video` 2, `youtube` 2, `webpage` 2.
- **FACT.** Blocks that are *not* withheld despite a stored global value (attested): `direct.base.tool_phase`,
  `summary.base.narrator`, `summary.base.l2_writer`, `summary.cover.style`, 4 × `verbilizer.mode.*`,
  `core.personality` (+compact). So provenance protection itself works; the problem is the 9 unattested edits.
- **WARN.** `direct_chat_system_prompt` is the most frequent offender (210 lines) — larger blast radius than the
  two blocks cited in the task.

Evidence: `evidence/raw/distilled_speech_expression.json`, `evidence/raw/ssh_forensic.log` (section D).

---

## 2. Factcheck run 23.10 — found, with the exact loss point

**FACT.** The run exists and matches the reported publication:
`run_id=tfr-6e0ab2dbcc784b57`, created **2026-10-23 17:19:24 UTC**, chat `-1004482340693`,
trigger msg `4591`, `pipeline_version=tf2`, `cache_hit=false`, `fallback_used=false`,
`factual_verdict=insufficient_evidence`, `temporal_status=unknown`, claim 487 chars, sha12 `eda4aec4f80c`.
Claim text opens with «⚡️ В Telegram добавят ИИ-агентов — Claude, ChatGPT…» and ends «Дуров убил Claude Code».

Stage trace (durable, 8 entries): `target_resolve` success → `origin_date_resolve` success →
`claim_decompose` success → `temporal_search` success (`reason=unified_retrieval`) →
`evidence_validate` success → `verdict` success → `verdict` **corrected** → `verbalize` success.
**No stage failed.**

Journal for the same second (`short-iso`, prod UTC):

```
17:19:04 [factcheck] triggered | chat=-1004482340693 user=1313107079
17:19:04 [factcheck_v2] retrieval plan | chat=-1004482340693 | queries=1 | intents=entity_check | privacy_dropped=0
17:19:05 SearchAggregator: level ok | provider=tavily | latency_ms=1274 | chars=7778
17:19:05 [factcheck_v2] retrieval | ... | attempted=1 | used=1 | refs=4 | fetch_errors=0 |
         budget_exhausted=False | version=fp2
17:19:13 [prompt_registry] persisted speech value withheld |
         key=prompts.factcheck_verbalizer_system_prompt | block=factcheck.base.verbalizer |
         reason=provenance_missing | stored_sha=5fbf...
```

**Where it actually broke — `FACT`, evidence-backed:**

1. **Query construction produced a single query** (`queries=1`, `intents=entity_check`). The composite post
   (function claim + provider/API-key claim + multi-agent claim + subjective verdict) was not turned into
   per-claim retrieval intents. This is the first divergence from §3.4/§3.5 of the task.
2. **Tavily returned 7778 chars, accepted as relevant, `refs=4`, `fetch_errors=0`, budget not exhausted.**
   So this run is **not** a provider outage, **not** a fetch failure, **not** a budget exhaustion, and
   **not** the lexical overlap filter rejecting results (see §3).
3. **The four evidence rows are off-topic and structurally empty** (`FACT`, durable `mca_factcheck_evidence`):
   all four are `source_kind=secondary` with `url=null`, `source_ref=null`, `claim_part=null`,
   `published_at=null`; their snippets are about *«Claude Code source code leak»* (Boris Cherny / IT Pro /
   newsletter boilerplate). The token «Claude» matched; the actual subject (Telegram Agent) did not.
4. **Claim decomposition never reached the evidence layer:** `claim_part=null` for every row → the requirement
   of independent verdicts per claim (§3.5) is not represented in durable evidence at all.
5. **The `verdict` stage corrected itself to a global `insufficient_evidence`.** The delivered text is honest
   about the failure («Ни одного источника про ИИ-агентов в Telegram…»), i.e. the **renderer did not hide
   results behind a generic header** — the defect is upstream (query + evidence relevance), not the renderer.
6. **Version/build absent from what was analyzed** (`FACT`): the analyzed claim contains `telegram`,
   `claude`, `chatgpt` — but **no `283365`, no `13.1.0`, no `macos`**. `source_type=text`, and the stage trace
   contains **no OCR/image stage**. So the macOS 13.1.0 (283365) details the owner saw were not part of the
   analysed text.
   **HYPOTHESIS** (not proven): those details were in the attached image / outside the captured caption, and
   the run used text only (no vision/OCR path in `tf2`).

**What is NOT_FOUND here:** no per-query provider-by-provider log for this run beyond the single Tavily line;
no stored query strings, no lexical-filter decisions (the filter is only logged when it rejects). The
`retrieval plan` log line does not carry query text (R17-safe by design).

Evidence: `evidence/raw/http_fc_run_tfr-6e0ab2dbcc784b57.json`, `evidence/raw/fc_trace.txt`,
`evidence/raw/ssh_forensic.log` (section B).

---

## 3. Search providers and the lexical filter (window 22–24.10)

- **FACT.** In the whole `SearchAggregator` window since 2026-10-22 there is **exactly one** call and it
  succeeded (`level ok | provider=tavily`). **Zero** `level failed` lines, therefore **zero**
  `irrelevant results (low query overlap)` rejections in this window.
- **FACT.** No Tavily/Exa/DDG/SafeFetcher error lines for the 23.10 factcheck window; `fetch_errors=0` in the run.
- **WARN.** Absence of lexical rejections here does not clear the filter in general — it simply did not fire in
  this window (one call total). The filter is only observable when it rejects
  (`SearchAggregator: level failed → fallback | provider=… | error=irrelevant results (low query overlap)`);
  its accept/reject outcomes for other runs are not logged, so a broad "how often does it drop relevant hits"
  question is **NOT_FOUND** from logs alone.
- Cascade order is Tavily → Exa → DDG; only Tavily was exercised on 23.10, so Exa/DDG behaviour on that run is
  unobservable.

---

## 4. Expression / FREQUENT: effective config and layer delivery

**FACT — effective configuration (global doc `character.expression`):**
`enabled=true`, `sharpness=sharp` (source `global`), `profanity=**frequent**` (source `global`),
`wit=inherit`, `verbosity=inherit` (both `factory_default`), rendered text **812 chars**.

**FACT — per-chat composer preview (3 chats):**

| chat | expression layer rendered | chars | revision | source | marker `<Expression_Settings>` in preview system |
|------|---------------------------|-------|----------|--------|--------------------------------------------------|
| -1004482340693 | yes | 812 | `f90f1be5ac11` | global | 1 |
| -1002661910336 | yes | 913 | `cdb6afe75b24` | **chat override** | 1 |
| 5885953495 | yes | 812 | `f90f1be5ac11` | global | 1 |

- **FACT.** The layer is **not skipped and not budget-excluded** in any of the three previews:
  no `expression_*`/`budget_excluded` code among the skip reasons; 13 layers compose; layer weight 203/229 tokens.
- **FACT.** The rendered layer contains the frequent-mode instruction verbatim:
  «- Мат: Пиши на живом разговорном языке с выраженным использованием мата…» (present in all three chats).
- **FACT.** Separate layer `expression_examples` is **absent** (`expression_examples_absent`) in all three
  chats — no approved few-shot samples, only the instruction layer.
- **FACT.** `last_run_present = false` in all three chats: the Inspector holds **no real provider-call snapshot**
  (`exact.status=no_actual_request`, `is_actual=false`). Reason: the process restarted at 17:51:39 UTC and the
  provider trace buffer is in-memory.
  → **"Was `Expression_Settings` in the literal system message of the 23.10 answers?" is NOT_FOUND** for past
  messages. Only the assembled payload is proven (marker + frequent line), not historical wire delivery.
- **FACT.** No `[expression]` and no `[composer]` warnings in journal since 2026-10-22 (both counts = 0) —
  the layer never failed to build at runtime.
- **HYPOTHESIS (for the Expression lane, not proven here):** since delivery is present and unskipped, a weak
  real-world effect of FREQUENT must be sought in model compliance / competing genre instructions / output
  post-processing, not in "the layer never reached the prompt". Existing runtime logs cannot separate
  "instructed" from "obeyed" — that needs the offline/probe contour with the real provider.

Evidence: `evidence/raw/http_expression_global.json`, `evidence/raw/distilled_speech_expression.json`.

---

## 5. Checkup: lowercase rule, Betterstack 401, Vision sweep

- **FACT — lowercase rule is LIVE.** Effective `checkup.base.system` (factory `38d63d86b54d`, 2077 chars)
  contains: «1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Пиши небрежно.»
  Because the owner's stored checkup text (`1e8a3c69cf7b`) is **withheld**, this factory wording is what the
  model gets. So §4.3 of the task ("убрать требование строчной буквы") is **not yet satisfied in production**.
- **FACT — the same lowercase instruction exists in 6 other effective prompts**: `factcheck.base.single`,
  `search.base.system`, `summary.base.single`, `youtube.base.system`, `youtube.base.video`, `web.base.system`
  (all factory, all withheld). `summary.base.l2_writer` and `verbilizer.mode.casual` instead contain
  *negative*/casual variants. So removing it from Checkup alone will not remove it from other routes.
- **FACT — Betterstack:** `[checkup fetcher] sql api failed → journalctl fallback | error=Client er…` (401) at
  **2026-10-23 17:22:04** — exactly **1** occurrence since 20.10, immediately followed by
  `[checkup fetcher] journalctl ok | lines=11`. The fallback **worked**; no repeated 401 storm.
- **FACT — Vision `claim sweep slow` since 20.10:** n=**1355**, min **5.01 s**, p50 **7.49 s**,
  p90 **11.51 s**, max **37.69 s**; `claim sweep timeout` = **13**. Slow events recur roughly every 5 minutes
  (tail: 17:35:46 7.34 s, 17:40:42 13.41 s, 17:40:51 7.55 s, 17:45:39 5.71 s, 17:50:43 25.18 s, 17:50:53 5.06 s).
  **Phase breakdown is NOT_FOUND:** the log line carries only total `dur`, no per-phase timings and no SQLite
  contention data. 13 timeouts are the concrete error signal; the rest is latency.
- **WARN.** The 17:22 Betterstack failure and the 17:19 factcheck failure are **independent events**
  (factcheck search used Tavily successfully); nothing links the 401 to the factcheck outcome.

---

## 6. Health snapshot (prod, 2026-10-23 17:55 UTC)

| item | value |
|------|-------|
| version / HEAD | 2.58.118 / `9ed68ee8` |
| service | `active (running)`, `MainPID=858447`, `NRestarts=0`, up since 17:51:39 UTC |
| `/healthz` | 200 `{"status":"ok","version":"2.58.118"}` |
| ERROR lines 23.10 | **5** |
| CRITICAL lines 23.10 | **0** |
| `[expression]` / `[composer]` warnings since 22.10 | 0 / 0 |

---

## 7. What this proves / what remains unproven

**Proven (FACT):**
1. Nine prompt blocks are withheld in production; only two were previously known. Eight hold text that differs
   from the factory and is discarded; one (`direct.base.l2_writer`) is byte-identical but still unattested.
2. The 23.10 Telegram-Agent factcheck run is identified (`tfr-6e0ab2dbcc784b57`) with a durable trace; no stage
   failed; `cache_hit=false`; the loss is **1 query / `entity_check` intent → off-topic Tavily result accepted →
   4 evidence rows with no URL/claim part → `verdict` corrected to `insufficient_evidence`**.
3. Version/build (283365, 13.1.0, macOS) never entered the analyzed text; no image/OCR stage in the trace.
4. No search-provider error and no lexical rejection occurred in that run or in the 22–24.10 window.
5. Expression layer is composed and delivered in the payload for all three chats, with the `frequent`
   instruction verbatim, and is not budget-excluded.
6. Checkup's effective prompt **does contain** the small-letter instruction (factory), and so do six other routes.
7. Betterstack 401 occurred once and the journalctl fallback succeeded; Vision sweep is chronically slow
   (p50 7.49 s, 13 timeouts) but phase breakdown is unavailable.

**Not found / unproven:**
- Historical wire payload of the 23.10 answers (provider trace is in-memory; restarted) → expression *delivery*
  proven only at composition level.
- Query strings and per-provider relevance verdicts for that run (logs carry counts, not text, by design).
- Whether 283365/13.1.0 came from the image or the caption (no OCR stage, claim text lacks them).
- Exact `stored_chars` for 6 of the 9 withheld blocks.
- Whether the 23.10 run executed on 2.58.117 (inference from `PID 847992` being replaced at 17:51:39 UTC by
  `9ed68ee8`/2.58.118; the version string at run time is not logged).

## 8. Reproduction / re-check

```text
API:  GET /healthz
      GET /api/speech/blocks?speech_only=true          (X-Telegram-Init-Data: owner-signed initData)
      GET /api/speech/expression
      GET /api/speech/inspector                        (+ X-Chat-Id)
      GET /api/factcheck/temporal/runs?limit=100
      GET /api/factcheck/temporal/runs/{run_id}
SSH:  systemctl show admin_bot -p ActiveState -p NRestarts -p MainPID
      journalctl -u admin_bot --since '2026-10-23 16:30' --until '2026-10-23 19:00' -o short-iso
Scripts: OPENCODE_WORKFLOW_SCRATCH/p0-forensic/{http_probe,fc_trace,expr_inspector,ssh_forensic}.py
```
