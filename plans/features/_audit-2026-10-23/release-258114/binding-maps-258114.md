# Привязка карт к релизному кандидату 2.58.114

- Дата: 23.10.2026 (PM-SYNC-BIND-258114)
- Кандидат: `bd1cdc3d73a03199b02206dd5594ec2573717618` (ветка `release/2.58.114`, 2.58.114)
- Worktree: `C:\Code\Python\adminbot-wt258114`
- deployed_commit в картах: пусто — кандидат ещё не задеплоен; предыдущий деплой 2.58.113 (`e4ee54f3`) остаётся в истории карт через `produced_on`.

## 1. Что синхронизировано (docs-only)

- `plans/features/asap3-corrective/**` (source, requirements-map, slice-graph, plan, arch-design, migration, evidence, review-*).
- `plans/features/asap2-direct-chat/`: requirements-map, binding-*, evidence/boundary-t20.md, evidence/semantic-closure.md, evidence/review-telemetry.md, evidence/telemetry-clar.md, evidence/probe-r2/**, evidence/prod-snapshot/**.
- `plans/features/asap-speech-arch/`: requirements-map, evidence/r2/**, evidence/r3/**, evidence/r3b/**, evidence/remainder-2026-10-23.md, evidence/reconciliation-2026-10-23.md, evidence/w4/binding-258113.md.
- `plans/features/_audit-2026-10-23/**`, `plans/progress_scope.json`.
- `plans/current_task.md` не копировался и не менялся.

Замечание по релизной линии: в `release/2.58.114` работа ASAP3 присутствует под другими SHA (rebase): style `673d142c` (был `f30feb30`), identity `d8af77c3` (был `bfc12366`), ui `81cdaa28` (был `6c479ad2`), accept `0d57ec24` (был `804b68b1`). Эти SHA не являются предками `bd1cdc3d`, поэтому карты привязаны к кандидату, а evidence-записи перенесены с сохранением `produced_on`.

## 2. Нормализация evidence

- Короткие SHA (7–39 hex) в `evidence[].candidate_commit` заменены на полный `bd1cdc3d…`; исходное значение сохранено в `produced_on`.
- Полные SHA других коммитов (`fbf9013d…`, `ec359bb3…`) **не** перезаписывались: это историческая provenance, а не привязка к кандидату.
- 52 (asap2) и 67 (speech) `artifact_sha256` пересчитаны по текущим файлам; прежние значения сохранены в `artifact_sha256_at_produced_on`. Это bookkeeping, а не доказательство поведения: Reviewer обязан сверить содержимое.

## 3. Закрытие строк

| Карта | required | VERIFIED | READY_FOR_LIVE | PENDING |
|---|---:|---:|---:|---:|
| ASAP3 (`asap3-corrective`) | 234 | 146 | 3 | 85 |
| ASAP2 (`asap2-direct-chat`) | 110 | 98 | 0 | 12 |
| SPEECH (`asap-speech-arch`) | 115 | 87 | 0 | 28 |

ASAP3 закрыто по evidence: `STYLE-LIMITS` 20, `UI` 21, `IDENTITY` 70, `ACCEPT` 38 строк.
Источники: `evidence/style-phase1.md`, `evidence/ui-phase.md` + `review-ui-r2.md` (блокеры 1–3 закрыты),
`evidence/identity-phase.md` + `review-identity-r2.md` (APPROVED), `evidence/acceptance.md` (S1–S10, A1–A15, §10.1–§10.8, §10.10).
Оставлены как postdeploy: `ACC-03` (§10.3, живая отправка без «—»), `ACC-09` (§10.9, прод-конфигурация), `A16` — все `READY_FOR_LIVE` с `next_check`. Строки `REPORT-*`/`GOV-*`/`AUD-*` намеренно **не** закрывались.

ASAP2 закрыто: 8 семантических строк (`CLAR-L1-DIST2/DIST3/DIST5`, `CLAR-L1-PRINCIPLE`, `CLAR-L1-PRIOR`, `CLAR-PLAN-ONETARGET`, `CLAR-L2-NOMENU`, `CLAR-L2-ROLE`) по `evidence/semantic-closure.md` §1; `T24` (§3, структурный тест :513-546); `TESTS-METHOD-SCREENSHOT` (§1, процедура UNCONFIRMED); `T20` по `evidence/boundary-t20.md` §4 (`not_reproduced as PASS`, дефект поведения модели).
`T10-BOUNDARY` **не закрыт**: собственное evidence лейна (§3 и §6 semantic-closure) фиксирует, что маркер доставлен и покрыт 8 тестами, но контрольный L2-вызов оговорку не дал. Строка оставлена `PENDING` с `next_check` (одна узкая строка канона L2 + 1 живой вызов). `CLAR-CTX-HONEST` — тот же корень.

SPEECH закрыто: `INIT-I01`…`INIT-I07` по `evidence/r3/report.md` §4 и `evidence/r3b/report.md` (I-01, I-02, I-04, I-05, I-07 — PASS; I-03 — safety PASS + durable; I-06 — чужой target отклонён durable-тестом).
`EVAL-MODES` оставлен `PENDING` (различие occasional/frequent не достигнуто: 0/3 vs 0/3 в r3, 0/2 в r2) с `next_check` на выборку §9.2. `INIT-48H` — `PENDING`, earliest useful check 25.10.2026 13:14 UTC (01:14 +12).

## 4. Гейты (`check --stage review`)

| Карта | Слайс | scoped | errors | EXIT |
|---|---|---:|---:|---:|
| ASAP3 | STYLE-LIMITS | 20 | 0 | 0 |
| ASAP3 | UI | 21 | 0 | 0 |
| ASAP3 | IDENTITY | 70 | 0 | 0 |
| ASAP3 | ACCEPT | 46 | 8 | 1 |
| ASAP2 | CLAR-PLAN | 5 | 0 | 0 |
| ASAP2 | CLAR-L2 | 4 | 0 | 0 |
| ASAP2 | TESTS | 45 | 2 | 1 |
| ASAP2 | CLAR-L1 | 13 | 2 | 1 |
| ASAP2 | MIGR | 9 | 2 | 1 |
| ASAP2 | DONE-CRITERIA | 11 | 5 | 1 |
| SPEECH | INIT-LIVE | 21 | 18 | 1 |

ASAP3 ACCEPT: 8 ошибок — только `REPORT-*` строки (обязательства отчёта, не приёмка §8/§10).
ASAP2 TESTS: `TESTS-METHOD-REAL`, `T10-BOUNDARY`. CLAR-L1: `CLAR-L1-DIST4`, `CLAR-L1-CONTINUATION`. MIGR: `MIGR-PAYLOAD`, `MIGR-HOTAPPLY`. DONE-CRITERIA: `DONE-D1/D5/D6/D8/REPORT`.
SPEECH INIT-LIVE: 18 ошибок — `PENDING` (`T-I-COVERAGE`, `T-UI-*`, `T-GLASS-PERF`, `P0D-QUOTED`, `INIT-48H`, `EVAL-MODES`) и 4 исторически `VERIFIED` строки без привязки к кандидату (`INIT-I08`, `INIT-I09`, `INIT-TESTS`, `EVAL-EGRESS` — evidence на `fbf9013d…`/`ec359bb3…`).

## 5. Остаток и следующий шаг

1. ASAP3: 85 PENDING — `HIDDEN-LIMIT`, `DASH`, `MIGRATION`, `GOV`, `REPORT-*`; это отдельные слайсы, а не «хвост UI».
2. ASAP2: 12 PENDING — `T10-BOUNDARY`/`CLAR-CTX-HONEST` (канон L2 + 1 вызов), `CLAR-L1-DIST4`, `CLAR-L1-CONTINUATION`, `TESTS-METHOD-REAL`, `MIGR-PAYLOAD`/`MIGR-HOTAPPLY`, `DONE-D1/D5/D6/D8/REPORT` (телеметрия и завершение — после деплоя).
3. SPEECH: 28 PENDING — `EVAL-MODES`, `INIT-48H`, UI-матрица/GLASS, Inspector, MIGR/TRACE. Плюс перепривязка 4 исторических VERIFIED к кандидату либо честное понижение статуса решением Reviewer.
4. Release-gate по всем трём картам не пройден и не может быть пройден до деплоя и postdeploy-проверок.
