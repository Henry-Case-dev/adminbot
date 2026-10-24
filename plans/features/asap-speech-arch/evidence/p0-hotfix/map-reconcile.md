# P0 hotfix — структурная сверка карты (PM, 25.10)

Кандидат для evidence: `7eca3cbccdf338a0f8180a6a1087ee262c805b5c` (код `51cee325` + offline-пробы), тот же SHA, который ревьюил Reviewer `d4b3c979`.

## Что исправлено (R3 из review.md)

| Было | Стало |
|---|---|
| `candidate_commit` пуст | `7eca3cbc…` + `candidate_note` о перепривязке после R1/R2 |
| `strict_evidence: true`, `slice_graph_path: ""` | `slice-graph-p0-hotfix.json` (9 слайсов, отдельный файл — большая карта продолжает использовать `slice-graph.json`) |
| 7 duplicate `req_id` на 17 строк | 100 required / 100 уникальных `req_id`; расщепления помечены `renamed_from` + `split_reason` |
| 0 evidence | 54 строки с candidate-bound evidence (`artifact_path` + `artifact_sha256`) |
| все 79/100 PENDING | 41 VERIFIED, 13 FAILED, 46 PENDING — строго по acceptance ledger Reviewer |

Счётчики не менялись: 100 required / 37 context / 23 duplicate.

## Гейты

- `--stage plan`: EXIT 0 (inventory=79, manual=81, errors=0), граф проверен.
- `--stage review` по слайсам на `7eca3cbc`: **TEXTS EXIT 0**. Остальные красные только из-за честных открытых пунктов (ни одного структурного дефекта):
  - ANALYSIS — 4 FAILED (R1: точные analysis-тексты не попадают в фактический deep/report payload) + `ANALYSIS-ROUTING-PRESERVED` FAILED + 14 PENDING;
  - PROBES — 5 FAILED (R2: пробы несопоставимы, сырой production-output не проверен) + 15 PENDING;
  - MEMORY — 5 PENDING (CHECK-SHOWN-ANSWERS, TRACE-ORIGIN, KEEP-EXTRACTION, FIX-RECORD-PATH, KEEP-CREATIVE-FICTION);
  - TRACE — 1 PENDING (`TRACE-CAUSE-FACTS`), 1 FAILED (`TRACE-PAYLOAD-CORRELATION`: сырой output не персистится);
  - CORE — 1 PENDING (`CORE-NO-JOKE-IS-NOT-LOSS`, нужна проба с бытовым вопросом на сопоставимом входе);
  - REVIEW — 2 FAILED (сырые ответы/payload provenance), 7 PENDING (условия отказа §7 перепроверяются на новом кандидате);
  - DEPLOY/REPORT — PENDING (деплоя и отчёта ещё нет).

## Что должен сделать PM/Orchestrator после R1/R2

1. Сменить `candidate_commit` на SHA, включающий R1+R2, и перепривязать evidence (поле `candidate_commit` внутри evidence обязано совпасть).
2. Перепроверить FAILED-строки и только затем ставить VERIFIED; DEPLOY/REPORT закрываются после выката.

## Границы

Код, `plans/current_task.md`, `plans/workflow_state.md`, прод и другие карты не менялись. Evidence принесён из `d4b3c979` (`review.md`, `probes/`, `traces.md`) без правок содержания.
