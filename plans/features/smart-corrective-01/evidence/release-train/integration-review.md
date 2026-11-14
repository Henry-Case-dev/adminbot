# SMART-CORRECTIVE-01 - Deploy-stage approval appendix

- Candidate: `409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9` (`409f4e8a`).
- Review type: independent predeploy deploy-stage disposition. No row is marked `VERIFIED`.
- S0: `investigation/production-runs-and-incidents.md` and `evidence/binding-production-investigation.md` reconstruct two read-only production runs and separate facts, source conclusions, hypotheses and unrecoverable data. `SC-WD-W12` records six detections, one confirmed false takeover; not six crashes.
- S5: `evidence/s5a-d/{implementation.md,review-r1.md}` covers lifecycle/history, severity/degraded separation, delivery_unknown guards, fencing, duplicate prevention, per-job events and non-recursive failure observability. Review evidence only.
- S8 process rows are `REVIEW`; production prompt/release and AC rows are `READY_FOR_LIVE`.

## Machine-readable dispositions

```json
{
  "schema": "smart-corrective-01-deploy-appendix-v1",
  "candidate_commit": "409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9",
  "rows": [
    {
      "req_id": "SC-REP-INC-01",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-INC-02",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-INC-03",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-INC-04",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-INC-05",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-01",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-02",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-03",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-04",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-05",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-06",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-07",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-08",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-09",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-10",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-11",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-12",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-13",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-14",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-15",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-16",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-17",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-EVSEP",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-TRACE-GAP",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-INV-OBSDEF",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-BASE",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-FAIL",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-STOP",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-GH-UNCONF",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-FOLLOWUP",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-FOLLOW-READ",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-CONSIST",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-ESSENCE",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-CAUSE",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-REP-NOFOLLOWUP",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-WD-W12",
      "disposition": "REVIEW",
      "evidence": [
        "investigation/production-runs-and-incidents.md",
        "evidence/binding-production-investigation.md"
      ]
    },
    {
      "req_id": "SC-WD-SEPARATE",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-WD-NOREPLACE",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-WD-NO-01",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-WD-NO-02",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-WD-NO-03",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-WD-NO-04",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-WD-NO-05",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-WD-NO-06",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-WD-NO-07",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/s5a/implementation.md",
        "evidence/s5a/review-r1.md",
        "evidence/s5b/implementation.md",
        "evidence/s5b/review-r1.md",
        "evidence/s5c/implementation.md",
        "evidence/s5c/review-r1.md",
        "evidence/s5d/implementation.md",
        "evidence/s5d/review-r1.md"
      ]
    },
    {
      "req_id": "SC-ART-01",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-02",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-03",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-04",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-05",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-06",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-07",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-08",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-11",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-COR-DELIVERY",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-COR-NOTVERIFIED",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-NOTDONE",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-OVL-FC-SEM",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-OVL-FC-CONTEXT",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-OVL-FC-NOCLARIFY",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ACC-METHOD",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ACC-REG-01",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ACC-REG-02",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ACC-REG-SCOPE",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-SEQUENCE",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-REVIEW-SCOPE",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-NOSTUB",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-PRESERVE",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-ACTIVE",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-USER-OFF",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-DEPLOY",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-NODEMO",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-IMPL-OBSFAIL",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ACC-MAIN",
      "disposition": "REVIEW",
      "evidence": [
        "evidence/release-train/merge-log-corrective.md",
        "evidence/release-train/integration-review.md"
      ]
    },
    {
      "req_id": "SC-ART-09",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "SC-ART-09"
      }
    },
    {
      "req_id": "SC-ART-10",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "SC-ART-10"
      }
    },
    {
      "req_id": "AC-01",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-01"
      }
    },
    {
      "req_id": "AC-02",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-02"
      }
    },
    {
      "req_id": "AC-03",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-03"
      }
    },
    {
      "req_id": "AC-04",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-04"
      }
    },
    {
      "req_id": "AC-05",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-05"
      }
    },
    {
      "req_id": "AC-06",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-06"
      }
    },
    {
      "req_id": "AC-07",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-07"
      }
    },
    {
      "req_id": "AC-08",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-08"
      }
    },
    {
      "req_id": "AC-09",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-09"
      }
    },
    {
      "req_id": "AC-10",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-10"
      }
    },
    {
      "req_id": "AC-11",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-11"
      }
    },
    {
      "req_id": "AC-12",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-12"
      }
    },
    {
      "req_id": "AC-13",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-13"
      }
    },
    {
      "req_id": "AC-14",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-14"
      }
    },
    {
      "req_id": "AC-15",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-15"
      }
    },
    {
      "req_id": "AC-16",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-16"
      }
    },
    {
      "req_id": "AC-17",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-17"
      }
    },
    {
      "req_id": "AC-18",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-18"
      }
    },
    {
      "req_id": "AC-19",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-19"
      }
    },
    {
      "req_id": "AC-20",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-20"
      }
    },
    {
      "req_id": "AC-21",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-21"
      }
    },
    {
      "req_id": "AC-22",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-22"
      }
    },
    {
      "req_id": "AC-23",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-23"
      }
    },
    {
      "req_id": "AC-24",
      "disposition": "READY_FOR_LIVE",
      "postrelease_wait": {
        "nonblocking": true,
        "reason": "Required production observation cannot exist before deployment of this exact candidate.",
        "trigger": "First successful controlled deployment and the named live scenario for this row.",
        "next_check": "DevOps records deployed SHA, health and effective config; Builder/Reviewer records the scenario result, logs, state and rollback outcome.",
        "owner": "DevOps/Builder/Reviewer",
        "contract_ref": "AC-24"
      }
    }
  ]
}
```

Specific live triggers: AC-15/AC-19 saved-edition checkup with prompt provenance; AC-20..AC-24 watchdog per-job events, recovery, lifecycle and observability; SC-ART-10 SFC-12-09, S1/S2/S3/S4/S6, S5A-D and L1-L8 recanary. These waits are not owner QA.

## Conditional verdict

Train `409f4e8a` may proceed to controlled deployment only after PM binds this appendix and candidate-bound evidence to the exact combined candidate and the deploy gate returns `errors=0`. Current master gate evidence reports `119` errors; this appendix is not approval of the current checkout, not production acceptance, and not parent `DONE`.

## Three proof lines

- **Implementation:** inspected S0 evidence and S5A-D lifecycle, recovery, fencing, event and failure-observability paths.
- **Test validity:** inspected S5A-D assertions and mutation outcomes; they exercise SQLite state/events/fencing and durable failure paths, not tautologies. Slice evidence is not yet directly bound to combined `409f4e8a`.
- **Independent challenge:** adversarial delivery_unknown marker, duplicate emission, empty batch, fingerprint and recursive-write mutations were reviewed; no production canary was run predeploy.

## Blocking handoff

PM/Orchestrator must bind rows/evidence, reconcile 119 gate errors, rerun deploy-stage gate and only then authorize controlled deployment. Do not mark rows `VERIFIED`.
