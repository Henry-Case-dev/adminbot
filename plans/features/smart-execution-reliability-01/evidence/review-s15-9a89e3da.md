# Reviewer S15-FC-EVIDENCE

Решение: Approved для controlled deployment; SFC-7-06 READY_FOR_LIVE, parent не DONE.

Кандидат: 9a89e3da; evidence head 52514203; база 80c83d24. Проверены factcheck_service.py, factcheck_attribution.py, factcheck_orchestrator.py, capacity/evidence callers и 12 CONTRACT-тестов. git diff --check 80c83d24 9a89e3da -- services tests пуст.

Implementation: retrieval -> evidence delivery/packing -> analyst -> validator -> diagnostics -> durable record. Единый resolver использует фактические model/endpoint primary и fallback; unknown default 1000000, output reserve отделён. Нет универсального 16384 и delivery cap 20/1200; overflow сохраняет remainder IDs/URLs, provenance и budget/deadline caveat доходят analyst и validator.

Test validity: прочитаны assertions всех 12 тестов: delivery, capacity, fallback recompose, remainder/durable parity, provenance, budget negative case, attribution >400, diagnostics. Focused suite 12 passed. Factcheck seams 98 passed, 1 warning. Binding comparison: candidate 839 passed/6 failed, base 737 passed/7 failed, master имеет те же 6 pre-existing failures (MCA20 escaping, fallback stubs без sent=, DDG network flake).

Independent challenge: reviewer-independent-probe-9a89e3da.json. Primary window 3000: 2/60 delivered, remainder 58, durable 2. Fallback window 1000: 1/8, remainder 7. Budget-stop caveat наблюдается analyst и validator; search_text не утёк. Facebook fixture: 1 row, support 209, opened yes, budget caveat.

## Ledger

SFC-7-01 VERIFIED: 12x2000 проходит analyst и validator без искусственной обрезки.
SFC-7-02 VERIFIED: overflow/tiny-share сохраняют remainder и durable parity.
SFC-7-03 VERIFIED: actual-route resolver, unknown 1M, no 16384.
SFC-7-04 VERIFIED: route-specific fallback recompose.
SFC-7-05 VERIFIED: meaningful selection, full fit, provenance, overflow accounting.
SFC-7-06 READY_FOR_LIVE: code/probe audit done, real postdeploy factcheck pending.
SFC-8-01 VERIFIED: Facebook root cause reconstructed; S13/S14/S15 fixes bound.
SFC-8-02 VERIFIED: snippet/opened distinction and budget caveat.
SFC-8-03 VERIFIED: no domain rule or alternate trust model.
SFC-10-03 VERIFIED: EvidenceMap/trust contract unchanged.

Итого: 9 VERIFIED, 1 READY_FOR_LIVE, 0 FAILED, 0 predeploy UNVERIFIED.

## Facebook

Record tfr-d4f381867a884cbd: subject был исходным материалом, не вопросом пользователя; сохранён один Facebook snippet длиной 209, opened page не зафиксирована; старый trace показывал temporal search success, verdict uncertainty называла time-limit stop. Provider responses и точные причины discard не были сохранены и не выдумываются. Подтверждённые причины: subject loss, artificial budgets, deadline observability gap, support truncation, missing remainder accounting, DB/payload cap divergence.

## Residual

После deployment DevOps должен выполнить один реальный factcheck: проверить diagnostics route, delivered_rows, stop_reason; delivered plus remainder equals total; DB rows equal delivered. Это не owner QA. Parent не DONE до этой записи.

BACKLOG_ONLY: stale MCA20 escaping assertion; fallback stubs reject sent=; DDG relevance test network-sensitive.

Executed: focused suite, factcheck seams, independent deterministic probe, diff check. Reused binding raw audit, base/master comparison, mutation results, production DB reconstruction. Web sources не нужны. Durable probe: plans/features/smart-execution-reliability-01/evidence/fc-evidence/raw/reviewer-independent-probe-9a89e3da.json.

Next action: controlled deploy exact candidate 9a89e3da; DevOps updates SFC-7-06 with actual deployed SHA and live evidence.
