# Workflow State

Task: ASAP 8 v6.3 — live correction (B01–B12, U01–U08, V01–V07) + plans cleanup + final audit
Task source: root prompt; канонический снапшот ТЗ plans/features/asap8-v6-3-live-correction/source-lines-37423-EOF.md
Status: in_progress (код+деплой закрыты; финальная приёмка упирается в 14 owner-гейтов)
Primary phase: delivery
Active feature: asap8-v6-3-live-correction

Active lanes:
- (none) — сабагенты недоступны (rate limit провайдера); прод-пробы и гейты выполнены напрямую

Join barriers:
- Финальный DONE заблокирован 14 BLOCKED_REAL_HUMAN_GATE: реальные клиенты fullscreen (8, U07.*), натуральный canary инициативы (REQ-B01), естественная нагрузка/измерение Опыта (REQ-B02, B02.3), real supergroup migration (REQ-B09), styled-image delivery (B04.5), окно наблюдаемости 24/48 ч (FINAL.2)
- Дополнительно к решению владельца: суточная квота эмбеддингов parked est=utc_day_end → семантика памяти деградирована (FTS-only)

Last verified:
- Deploy: прод 2.58.79 @ c2775a54 (server-verified: healthz/api/web 200, journal чист, rollback b9ea4907)
- Gate: --stage review зелёный по 12/14 слайсов; красные только 14 объявленных гейтов; --stage release красный (14 гейтов + 87 «нет live-evidence») — честный сигнал, финал не объявляется
- Карта: 139 required → 112 VERIFIED / 13 READY_FOR_LIVE / 14 BLOCKED_REAL_HUMAN_GATE, evidence привязан к candidate SHA
- Live: CSP `img-src 'self' data: blob:` (линза разрешена), инициатива жива (25 job/24ч, вход 3516), B11 с PG: 8 ok / 2 never_run
- Финальный аудит всего current_task.md: 28 программ HISTORICAL-CLOSED/WITH-OPEN-TAILS, BLOCKER-AUDIT чист (final-audit-current-task.md)
- Ревью: REV-W1 Approved (после fix B09), REV-W2 Approved (CORR-1 «background unchanged, glass changed»), REV-W3 Approved

Next unlocks:
- Владелец: (1) прогнать owner-проверки real-клиентов/canary и отметить в карте; (2) решить по квоте эмбеддингов у apinet.cloud; (3) опционально — диагностика пустого primary-слота эмбеддингов
- После закрытия гейтов: повторный gate --stage review/--stage release → DONE

Review: approved (W1/W2/W3)
Deployment: verified (2.58.79 = c2775a54)
Human gate: 14 owner-проверок (real clients / natural canary / styled delivery / supergroup migration / 24-48h observability) + решение по квоте эмбеддингов
Updated: 2026-10-16