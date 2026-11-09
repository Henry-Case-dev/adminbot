# EPIC-ADMINBOT-CORRECTIVE-YM-NOST-20261108 — план и crosswalk

## Источник и границы

Канонический источник: `plans/owner_inputs/2026-11-08-epic-adminbot-corrective-ym-nost-20261108.md`.
Сохраненная planning-копия: `source-2026-11-08.md`; она является immutable snapshot для этой карты и не заменяет owner source.

Этот пакет не заменяет существующие эпики и не переоткрывает доказанную работу. Existing requirements связываются correction pointers/reuse; новые atomic obligations принадлежат этой карте. `current_task.md`, `plans/progress_scope.json` и `plans/workflow_state.md` не редактируются.

Machine dependencies: `slice-graph.json`. Map: `requirements-map.json`, `strict_evidence=true`.

## Crosswalk

| Контур | Классификация | Авторитетный existing owner | Решение |
|---|---|---|---|
| TIME-UX | CORRECTION/reuse | существующий `ChatClock`/`/api/config/time*`, EVOL/current UI contracts | `TIME-UX`; не добавлять timezone source of truth |
| REPLY-NATIVE | CORRECTION | `evol-reply-context-integrity-01`, `factcheck-clean-publication` | сначала `REPLY-RCA`, затем общий native fix; не создавать translator |
| VISION-MULTI | CORRECTION | `p0-vision-universal`, folded `asap-vision-sync-01`, `asap5-multimodal` | один media registry contract; `VISION-MULTI` serializes with OWN |
| VISION-OWN | CORRECTION | `p0-vision-universal`, `asap5-multimodal` | register returned Telegram `Message`, not request ID |
| RBAC | CORRECTION | `evol`, RBAC v2 in `plans/ARCHITECTURE.md` | scoped read projections plus server enforcement; no new RBAC epic |
| PAY-YM | NEW | no existing registered PAY implementation; reuse `image_reservation`/`worker_budget` only after architecture decision | `PAY-ARCH` first; engineering may finish with provider OFF |
| NOSTALGIA | CORRECTION | `p0-nostalgia-rework`; reuse `asap5` evidence | `NOST-P0` immediate, then evidence/quality; no second NostalgiaWorker |
| MEM-AUDIT | CORRECTION | `epic-memory-cognitive-02`, especially `MEMORY-00`, `INV-01`, `INV-08`, `MEM-04.6` | first urgent slice; read-only audit before any memory implementation |

## Ownership decisions

- `MEM-AUDIT` is owned by `epic-memory-cognitive-02`; it must not become a second memory epic. A class-C finding permits only a minimal protective change in the existing retention path.
- Reply corrective work remains with `evol-reply-context-integrity-01`/`factcheck-clean-publication`; `REPLY-RCA` is forensic preparation, not a new owner.
- Vision multi-object and outgoing-media work share the media registry. They are explicitly serialized in the graph; no parallel schema writers.
- RBAC changes share the active `evol` ownership of `services/roles.py`, `services/access.py`, analytics APIs and the Mini App. No parallel RBAC writer.
- Nostalgia changes remain with `p0-nostalgia-rework` and its Initiative/Personality seam. Existing NOST-15/16 evidence is reused where candidate/environment applicability holds.
- PAY is the only genuinely new product contour. It requires Architect approval because it changes financial persistence, external provider security, migration and recovery contracts.
- No product code is implemented by this planning artifact.

## Dependency waves

### Wave 0 — urgent bounded preparation

- `MEM-AUDIT` — first urgent slice; read-only quota/retention/SQL/restart classification.
- `XC-RECON` — source reverse audit and owner binding.
- `NOST-P0` — narrow truncation defect can proceed after ownership confirmation.

### Wave 1 — independent discovery/contract work

- `REPLY-RCA`
- `TIME-UX`
- `RBAC-PROJECTION`
- `VISION-MULTI`
- `PAY-ARCH`

Only disjoint read-only or contract preparation may run concurrently. Existing EVOL integration remains the writer authority for overlapping files.

### Wave 2 — dependent implementation

- `REPLY-FIX` is represented by the existing Reply owner after RCA; it is a correction pointer and is not duplicated as a new graph writer.
- `RBAC-ENFORCEMENT` after `RBAC-PROJECTION` and the `TIME-UX` web contract.
- `VISION-OWN` after `VISION-MULTI`.
- `NOST-EVIDENCE` after `NOST-P0` and the memory audit.
- `PAY-BALANCE` after `PAY-ARCH`, `MEM-AUDIT` and `VISION-OWN`; this serializes shared budget/image-generation writers. Then `PAY-ORDER` and `PAY-UX-EVENTS` follow their graph edges.

### Wave 3 — joins and verification

- `PAY-ADAPTER`, `PAY-ADMIN` (after `TIME-UX` and RBAC enforcement), then `PAY-VERIFY`.
- `NOST-QUALITY` after `NOST-EVIDENCE`.
- `PAY-LIVE-EXTERNAL` is a separate post-engineering dependency and does not block provider-OFF engineering delivery.

The full machine graph, including intentional serial joins, is in `slice-graph.json`.

### Writer-scope barrier

Plan-gate использует консервативную проверку glob-пересечений, поэтому граф намеренно перечисляет конкретные будущие файлы вместо широких масок. Реальные общие writer-файлы сериализованы явно: `MEM-AUDIT → PAY-BALANCE` для `services/worker_budget.py`, `VISION-OWN → PAY-BALANCE` для `services/image_generation.py`, `TIME-UX → RBAC-ENFORCEMENT` и `TIME-UX → PAY-ADMIN` для общих web-контрактов. Тестовые и evidence-файлы принадлежат ровно одному slice.

Проверка выполнена:

```text
py -3 C:\Users\main\.config\opencode\tools\requirements_gate.py check --map plans/features/epic-adminbot-corrective-ym-nost-20261108/requirements-map.json --stage plan --repo .
stage=plan inventory=419 manual=17 scoped=0 errors=0
```

## MEM-AUDIT acceptance

Trace quota/retention from workers and settings to SQLite/PG SQL and classify each observed behavior:

- A: omitted from prompt/retrieval/hot cache only;
- B: stale/expired marker with retained evidence;
- C: physical irreversible deletion solely for quota;
- D: authorized privacy/forget/retention deletion.

A/B are not physical deletion. C conflicts with `INV-01`/`INV-08`/`MEM-04.6` and requires a minimal stop-future-deletion fix without mass restoration, rebuild or embedding migration. D must remain functional. Evidence must include before/after/restart behavior and real code/SQL paths.

Relevant code/evidence pointers:

- `services/summary_memory.py`
- `services/database.py`
- `services/worker_budget.py`
- `services/pg_db.py`
- `plans/features/memory-cognitive-02/requirements-map.json`

## PAY external dependencies

The engineering contract is ЮMoney form/webhook/reconciliation with factory price 50 ₽ / 3 generations, but real collection remains OFF until external conditions are proven. External classifications are `OWNER_ACTION_REQUIRED`, `DONE_BY_AGENTS`, `NOT_APPLICABLE`, or `UNVERIFIED`; they are not Human Gates for independent engineering.

External evidence is required for receiver, notification secret, optional read-only OAuth, real test payment, provider/legal/platform permissibility, and payout/withdrawal behavior. Before giving owner instructions, verify current official documentation and existing project endpoint/config. Never ask for secrets in chat, files, Git or logs.

Engineering can complete bounded fake-provider/fake-Telegram tests, ledger, RBAC, admin settings and rollback with `billing.image_yoomoney_enabled=OFF`. A webhook fixture is not `LIVE_VERIFIED`.

## Evidence convention

Before implementation, map rows have `PENDING`. Builder/Reviewer/DevOps evidence must be candidate-bound and use real repo-relative artifacts. Expected artifact locations are under this feature directory or the owning existing feature directory. No placeholder evidence is declared as proof. For existing requirements, reuse existing candidate-bound evidence only after Reviewer confirms candidate/environment applicability.

## Plan gate status

The inventory and graph are prepared for:

```text
py -3 C:\Users\main\.config\opencode\tools\requirements_gate.py check --map plans/features/epic-adminbot-corrective-ym-nost-20261108/requirements-map.json --stage plan
```

Builder must not start until this check passes and Architect has frozen the PAY, shared media-registry, RBAC projection and Nostalgia machine-contract decisions. `MEM-AUDIT` remains the first urgent executable slice; it does not authorize implementation of unrelated memory work.
