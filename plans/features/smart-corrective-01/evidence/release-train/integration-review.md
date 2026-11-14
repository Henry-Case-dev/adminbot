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

## Delta integration review 2.58.202

- **Candidate/base:** `release/smart-corrective-01` tip `0beed63df8037002ccfaacef019b8ea948d957f6` (`2.58.202`), base `409f4e8a` (`2.58.201`). Train worktree was retained for DevOps.
- **Verdict:** **Needs Fixes** for the exact combined artifact. The approved guard semantics themselves remain intact, but the requested diff-scope invariant is not satisfied by the candidate as reviewed.

### Diff audit

`git diff 409f4e8a..0beed63d` contains 38 paths. The guard paths are present and the 30-file version-bump set is present, but the diff also includes the following versioned test files outside the explicitly named guard files: `tests/test_decision_making_round1026.py`, `tests/test_image_context_memory_round1026.py`, `tests/test_mca17c_invariants_round1047.py`, `tests/test_round1025_f8_registry.py`, `tests/test_scope_selector_round1025.py`, `tests/test_summary_deploy_round1026.py`, `tests/test_summary_fact_package.py`, `tests/test_summary_logging_runid.py`, `tests/test_summary_publish_integration_round1026.py`, `tests/test_summary_test_run.py`, `tests/test_telegram_reactions_round1026.py`, `tests/test_tool_coordinator_round1026.py`, `tests/test_unified_image_request_round1026.py`, `tests/test_webapp_design_tokens_round1025.py`, `tests/test_webapp_f11_round1025.py`, `tests/test_webapp_f6_round1025.py`, `tests/test_webapp_f7_round1025.py`, `tests/test_webapp_f9_round1025.py`, `tests/test_webapp_hotfix10_round1025.py`, `tests/test_webapp_hotfix6_round1025.py`, `tests/test_webapp_hotfix7_round1025.py`, `tests/test_webapp_hotfix8_round1025.py`, `tests/test_webapp_hotfix9_round1025.py`, `tests/test_webapp_round1026_polygon.py` and four JS test files. These must be explicitly justified as the intended version-bump set or removed from this release train.

No changes were observed in `services/database.py` or `migrate_history`; the inspected metadata retains schema v47, DDL=0, REGISTRY=645 and GROUPS=121. No factory prompt text/label change was observed in the guard diff.

### Guard merge semantics

`services/prompt_release_policy.py` in the merged tip retains the approved ordering: explicit pinned/baseline handling precedes the manual-revision guard. The guard queries live `origin='manual' AND retired=false` state, preserves the chat bytes/override, records `factory_superseded_manual`, and writes the factory revision to history. The baseline test keeps the old behavior when no saved manual revision exists. This matches the approved guard branch evidence (`s6-prompt-guard/review-r1.md`, approved code `a8b6197f`) and no new semantic drift was found.

### Version bump and manifest

`APP_VERSION` and the registry metadata are `2.58.202`; the metadata reports REGISTRY 645 / GROUPS 121. The train manifest evidence reports version `2.58.202`, `deployed_sha=0beed63d` and `dirty=false`. The version bump itself is consistent with the prior release format, subject to resolving the diff-scope finding above.

### Checks executed/reused

- Executed on the train: `pytest tests/test_smart_corrective_prompt_delivery.py tests/test_prompt_baseline.py tests/test_evol016_prompt_activation.py -q` → **69 passed, 1 skipped**.
- Executed pin-related subset: `tests/test_tool_coordinator_round1026.py tests/test_unified_image_request_round1026.py tests/test_round1025_f8_registry.py` → **104 passed, 4 failed**. The failures are the existing forbidden-diff/canon checks against the broad historical baseline, not the guard tests; they nevertheless prevent claiming the requested pin guard as green on this exact train.
- Reused from candidate-bound guard review: guard/S6 **320 passed, 2 skipped**; checkup/prompt **331 passed**; regression **264 passed, 1 pre-existing failure**; baseline **274 passed, 2 skipped, 1 pre-existing failure**; sanity **328**; JS **4**. The full pin **856/4** claim was not independently rerun in this delta review.
- The guard review's pre-existing `prompt_field_audit` and `soul1_registry_completeness` observations remain separate and were not treated as new delta failures.

### Independent falsification

The focused guard tests on the merged train passed. The approved guard review's disposable mutation evidence remains candidate-lineage evidence: disabling only the guard caused exactly the three guard tests to fail while two unrelated cases stayed green. A fresh mutation copy was not retained/run after the diff-scope blocker was observed; this claim is therefore reused, not newly executed for the combined tip.

### Deploy/postdeploy obligations

Even after the scope correction, deployment must retain these unresolved obligations: DevOps data-only reactivation of `rev:d31300ef35a0`; a checkup in the affected chat confirming `prompt_source=chat`, 12,469 chars and hash prefix `31d17506`; clean SFC-12-09; watchdog events; and the remaining parent live rows. No requirement is marked `VERIFIED` and no production access was used.

### Blocking handoff

**Owner: PM/Orchestrator + DevOps.** First reconcile the 38-path delta against the declared guard plus version-bump allowlist and remove or explicitly bind every unexpected path. Then rerun the full train pin guard and the candidate-bound deploy gate. Minimum recheck: exact diff allowlist passes, pin suite has no new failure, and deploy gate remains `errors=0`. Do not deploy or mark requirements `VERIFIED` before that recheck.

## Delta integration review 2.58.202 - scope blocker resolved

- Exact candidate: `0beed63df8037002ccfaacef019b8ea948d957f6` (`2.58.202`).
- Base: `409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9` (`2.58.201`).
- Verdict: **Approved for controlled deployment** of this exact combined artifact. Predeploy approval only; no requirement is marked `VERIFIED`.

### Diff audit
`git diff --name-only 409f4e8a..0beed63d` returned exactly 38 paths. All belong to the declared union: 7 guard paths, 30 version-bump paths, and 1 train merge-log path. `outliers=[]`; `missing_expected_bump=[]`.

The 30 bump paths are exactly the file set reported by both `git show --stat a476818d` and `git show --stat 051ab76a` (30 files, 31 insertions, 31 deletions). Every bump path at `0beed63d` has the same Git blob as at `a476818d` (`bump_blob_mismatches=[]`). Every non-evidence guard path matches approved guard head `703b2877` (`guard_blob_mismatches=[]`). `review-r1.md` remains master binding evidence and is intentionally absent from the train.

### Pin and guard checks
The four pin failures are known base failures: canon 17 versus 18, canonical tool description/order with extra `inspect_runtime`, forbidden-diff allowlist, and web-diff allowlist. They reproduce on/reported for base `409f4e8a` and are not introduced by this merge or bump. Train subset: 104 passed, 4 failed. Focused merged guard tests: 69 passed, 1 skipped. Reused guard evidence: 320 passed/2 skipped; checkup/prompt 331 passed; regression 264 passed/1 pre-existing failure; baseline 274 passed/2 skipped/1 pre-existing failure; sanity 328; JS 4.

### Semantics and evidence
Merged `prompt_release_policy.py` preserves pinned/baseline precedence, live manual revision filtering (`origin=manual`, `retired=false`), chat bytes/override preservation, factory history insertion and `factory_superseded_manual`. No factory prompt text/label changed; schema v47, DDL=0, catalog 645/121.

- Implementation: exact 38-path union and per-file blob equality checked against `703b2877`, `a476818d` and `051ab76a`.
- Test validity: assertions cover journal state, bytes, history, diagnostics, isolation and restart no-op; known baseline reds were not relabeled as passes.
- Independent challenge: merged guard suite passed; prior disposable mutation disabled only the guard and failed exactly three guard tests; pin reds reproduced as base-class failures.

### Controlled deployment and postdeploy
Approved only for controlled deployment of exact tip `0beed63d`. Postdeploy obligations remain: DevOps data-only reactivation of `rev:d31300ef35a0`; checkup in the affected chat with `prompt_source=chat`, 12,469 chars and hash prefix `31d17506...`; clean SFC-12-09; watchdog events; remaining parent live rows. These are not owner QA assignments. No production access was used. No requirements are marked `VERIFIED`; final release acceptance remains pending.
