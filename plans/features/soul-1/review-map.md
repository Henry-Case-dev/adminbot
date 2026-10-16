# SOUL-1 — Independent source↔map coverage review (REVIEW-MAP lane, read-only)

**Verdict: Needs Fixes** (all fixes are acceptance-string edits in `requirements-map.json`; no implementation impact).

## Binding
- Source: `plans/features/soul-1/source-current-task.md`, 306 lines, SHA256 `8C42DDFABCE635FE4E1F24F9522FF8642F3BD3049FAC05C77CA162687051196B` (recomputed, matches required value; file read in full, not only headings).
- Map: `plans/features/soul-1/requirements-map.json` (101 items = 96 `required` + 5 `context`; 97 `additional_requirements` = 193 unique req_ids).
- Plan: `plans/features/soul-1/plan.md`.
- Gate (own run, 2026-10-16): `py -3 %USERPROFILE%\.config\opencode\tools\requirements_gate.py check --map plans/features/soul-1/requirements-map.json --stage plan` → `stage=plan inventory=101 manual=97 scoped=0 errors=0` (exit 0). PM claim reproduced. Gate checks metadata only.

## Method (all own, not PM-reported)
Line-level coverage reconstruction (element index ⇒ 4 non-mapped non-empty lines, all lead-ins); SHA256+substring verification of all 198 entries against the source line (0 mismatches, `source_sha256` matches file); clause-density scan (lines with ≥3 sentences and 1 item, reviewed by hand); enumeration/keyword audit against the source (`System2`, `YouTube`, `Checkup`, `Search`, `Web`, `ручные тесты`); slice/prefix reachability; live-flag cross-check against acceptance text; plan wave/ownership cross-check.

## Result of the required checks
1. Coverage: **1 hole** (F1). Zero silently-unmapped obligations otherwise; all 306 lines accounted for.
2. Invented obligations: **0** (all 97 manual entries trace to real source text, hashes verified). Minor tightenings noted in F6.
3. Softened acceptances: **3** (F1, F2, F3) out of the 31 sampled req_ids across W1–W9 (risky ones included: §7 one_word/micro, §16 hard rules, §5 precedence, §15 migration/rights, §18 initiative, §12/§19 UI, §21 report). No acceptance was found weaker than the source for one_word/micro (05.2/05.3/05.5/05.6), hard-rule acceptance (16.5.3), precedence (16.4.2), migration/rights (15.2/15.3/15.4/15.9), fullscreen (12.4), initiative (18.5), test plan (19.1/19.2/19.3/19.5) — these are faithful and observable.
4. `live_required`/`live_when`: **2 mis-set** (F4, F5). No requirement tied to real-client/real-chat/real-provider behavior was left `live_required=false` except the borderline SOUL-BOUND.3 (F5). W6 (29 items, 25 live) and W7/W5 live weighting are justified by the source text.
5. Slices/ownership: all `SOUL-01…SOUL-19` reachable (plus `SOUL-21`, `SOUL-BOUND`, `SOUL-EXEC`); 193 unique ids, no duplicates; no item without slice; nothing demoted to backlog (`dispositions` = 193 `required` + 5 `context`; no `user_excluded`/`duplicate`). Slice↔prefix mapping matches plan.md; shared-file collisions (`services/*`, PG registry/migrations, `web/api`, `web/static`) are explicitly assigned single writers.
6. Waves: W1 wave 0 is genuinely non-behavioural (read-only audit + source-schema design); the only W1-owned write (`prompt_migrations.py` / PG prompt registry) is isolated at JB-3 with backup/abort. W2→W3/W4/W5 seam barriers (JB-2) and W6→W7 handover (JB-4) are consistent with §0 "no competing parallel agents on the same files".

## Findings
| # | Sev | Source line | req_id | Observation | Minimal correction |
|---|---|---|---|---|---|
| F1 | blocking (coverage) | L31 | SOUL-01.1 | Acceptance requires only the generic chain + per-path PG key/default/priority/effective source/channel. The source separately mandates the **path inventory** "Direct L1/L2, legacy/direct fallback, System2, Initiative, Factcheck, Summary human-facing, Search, Web, YouTube, Checkup, сны/истории, ручные тесты и шаблоны". Verified: `YouTube`, `Checkup`, `Search`, `ручные тесты` occur **0 times** anywhere in the map; a matrix omitting those paths would still pass. Also affects L295 (`SOUL-21.1`, same omission). | Append the explicit path list to SOUL-01.1 acceptance (and echo it in SOUL-21.1): "…обязательно включает Direct L1/L2, legacy/direct fallback, System2, Initiative, Factcheck, Summary human-facing, Search, Web, YouTube, Checkup, сны/истории, ручные тесты и шаблоны". |
| F2 | blocking (narrow) | L193 | SOUL-14.1 | Acceptance keeps the positive diagram/understandability requirement but drops the explicit boundary "это не новая панель всех внутренних событий" (§19.5 mirrors it: "не делать вторую аналитическую стену"). | Add "…и это не новая панель всех внутренних событий (второй аналитической стены нет)". |
| F3 | low (narrow) | L185 | SOUL-13.2 | Acceptance covers anonymous 401/403/404 + server auth but drops "доступность только в разрешённой test-среде" (the stand must still work where intended). | Add "…и стенд доступен только в разрешённой test-среде (положительная проверка), боевой фон и liquid glass не изменены". |
| F4 | medium (live gate) | L185 | SOUL-13.2 | `live_when=preprod`, but closure of a *production* static-asset exposure can only be proven on the deployed environment (plan row 91: "anonymous probe 401/403/404", gate `l`). Risk: item closed before the real path is fixed. | Set `live_when=postdeploy` (probe the deployed host) or state the probe environment explicitly as deployed production in plan row 91. |
| F5 | low (live gate) | L255 / L25 | SOUL-16.5.3, SOUL-BOUND.3 | (a) 16.5.3 is gated `L~` (postdeploy) while its own evidence is "10+ heterogeneous inputs … on the **test delivery contour**" — provable preprod; the real-chat send is optional/owner-gated. (b) BOUND.3 ("одна и та же речь узнаваема в Direct/Initiative/tool-result") is `live_required=false` while comparable quality claims (14.3, 21.3) are live; a fixture-only sample would pass, which is the mock-DONE pattern the source forbids (L15). | 16.5.3 → gate `l` (preprod, test contour), owner-permission real send stays optional. BOUND.3 → `live_required=true` with real-path samples (chat logs/real runs) named in the evidence column. |
| F6 | low (precision) | L197 / L299 | SOUL-14.3, SOUL-21.5 | (a) 14.3 states "человеческие оценки собираются в MiniApp", while the source says "**Можно** собирать человеческие оценки в MiniApp" (permission, not obligation) — adds UI scope. (b) 21.5 adds "включая оценку владельца" not present in L299 (defensible from L289/plan §5, but not stated in the source line). | (a) reword to "человеческие оценки **могут** собираться в MiniApp". (b) keep, but label owner judgement as derived from L289, or drop the clause. |
| F7 | low (doc) | – | plan.md L7 | plan.md says "193 req_ids, **10 slices**"; the map and plan §1 define **9** slices (W1–W9). Documentation defect only. | Fix "10 slices" → "9 slices (W1–W9)". |

## The five `context` items (L41, L219, L227, L234, L241) — all legitimate, 0 holes
- L41 `### Речь, юмор и мышление` — pure label; every body obligation is mapped (SOUL-02.1 L43 … SOUL-02.6 L53).
- L219 `### 16.1…` → L221–225 = SOUL-16.1.1–.5. L227 `### 16.2…` → L229–232 = SOUL-16.2.1–.4. L234 `### 16.3…` → L236–239 = SOUL-16.3.1–.4. L241 `### 16.4…` → L243–247 = SOUL-16.4.1–.5.
- No unbulleted obligation is lost behind these headings; the only non-mapped non-empty lines in the whole document are lead-ins L1, L39, L95, L120, whose obligations are carried by the neighbouring mapped items.

## Recheck after fix (minimum)
Re-run the plan gate (must stay `errors=0`) and re-inspect only: SOUL-01.1/SOUL-21.1 acceptance text, SOUL-14.1, SOUL-13.2 (text + `live_when`), SOUL-16.5.3/BOUND.3 live flags, plan.md slice count. Then W1 dispatch may proceed.

---

## Verdict — round 2 recheck (REVIEW-MAP-2, 2026-10-16) → **Approved** (bounded recheck of F1–F7 + doc fix only; whole-map not re-reviewed)

**Candidate binding:** `requirements-map.json` + `plan.md` (untracked working tree; whole `plans/features/soul-1/` dir is git-untracked). Source `source-current-task.md` SHA256 recomputed = `8C42DDFABCE635FE4E1F24F9522FF8642F3BD3049FAC05C77CA162687051196B`; map `source_sha256` matches.

**Gate (own independent run, verbatim):**
```
py -3 ...\requirements_gate.py check --map plans/features/soul-1/requirements-map.json --stage plan
stage=plan inventory=101 manual=97 scoped=0 errors=0
EXITCODE=0
```

**Per-finding:**
- F1 SOUL-01.1 / SOUL-21.1 — RESOLVED. Both acceptances now enumerate the full path set (Direct L1/L2, legacy/direct fallback, System2, Initiative, Factcheck, Summary human-facing, Search, Web, YouTube, Checkup, сны/истории, ручные тесты и шаблоны), matching source L31; the previously-absent YouTube/Checkup/Search/ручные тесты are present.
- F2 SOUL-14.1 — RESOLVED. Boundary "…это не новая панель всех внутренних событий (второй аналитической стены нет)" restored; faithful to L193.
- F3 SOUL-13.2 — RESOLVED. Positive check "стенд доступен только в разрешённой test-среде (положительная проверка)" restored; faithful to L185.
- F4 SOUL-13.2 live gate — RESOLVED. `live_when=postdeploy`; plan row 91 gate `L~`, evidence now "anonymous probe … against the deployed production host".
- F5a SOUL-16.5.3 — RESOLVED. `live_when=preprod`; plan row 101 gate `l`; test-contour evidence is preprod, real send stays owner-gated (matches L255).
- F5b SOUL-BOUND.3 — RESOLVED. `live_required=true`; plan row 74 names "real Direct/Initiative/tool-backed runs … not fixtures alone"; gate `BOUND.3 = l`.
- F6a SOUL-14.3 — RESOLVED. Now "человеческие оценки **могут** собираться в MiniApp" (permission, matches L197 "Можно").
- F6b SOUL-21.5 — RESOLVED. Owner judgement now labelled "(производное от L289)"; verified L289 supports real-client/owner-quality judgement; not mis-attributed to L299.
- F7 plan slice count — RESOLVED. L7 now "9 slices (W1–W9)".
- «способ сборки» restoration (SOUL-01.1) — FAITHFUL to L31 ("…effective source, способ сборки и канал доставки"); all six per-path attributes preserved, nothing dropped.

**No unrelated changes found.** Structural parse of the map: 101 items + 97 additional = 198 entries; dispositions = 193 `required` + 5 `context` (no `user_excluded`/`duplicate`); 193 unique real req_ids (the only shared id is the empty `req_id` of the 5 context headings) all sliced W1–W9. All 8 touched rows' `source_text_sha256` still equal SHA256(raw source line) — no rebinding. PM's claimed indices all resolve to exactly the stated req_ids (addl[15/78/80/87]=BOUND.3/14.1/14.3/16.5.3; items[3/37/91/95]=01.1/13.2/21.1/21.5). No req_id/disposition/slice churn.

**Residual (non-blocking, flag before W1/W2):** no committed git baseline exists for map/plan, so "no other acceptance/live string edited" was proven via partition integrity + live-flag read + source-binding + index checks rather than a block diff. Recommend PM commits the map/plan/snapshot to git before W1 dispatch so slice reviews have a diffable baseline and the W1 entry criterion "snapshot SHA verified" is git-checkable. SOUL-13.2/14.3/21.5 remain postdeploy (expected L~) — need a committed canary/rollback plan before those reach VERIFIED, not before W1 starts.

**Recheck method (own, not PM-reported):** direct line reads of all 8 rows + source lines L31/L193/L197/L185/L255/L289/L299; independent gate run; JSON structural parse; 8× source_text_sha256 recompute; PM index resolution.