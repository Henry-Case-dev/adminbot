# Release reconciliation — asap8-v6-3-live-correction (B12.5)

Дата: 2026-10-16. Кандидат/actual deploy: `c2775a54258512a3e20c97341d3e8a6738b1a33b`
(2.58.79), прод подтверждён с сервера (см. live-canary.md).

## 1. Снятие исторического расхождения (B12.5, пункт 5 ТЗ)

**Расхождение:** `plans/features/asap8-v6-remediation/f10-report.md` содержал
`Deployed SHA: __PENDING__` при `workflow_state.md: done` — документ фиксировал
«завершено» без фактического deployed SHA.

**Факт (установлен сейчас):** релиз v6 (2.58.78) был фактически задеплоен —
deployed SHA `b9ea4907ffa52e7b2974e9511113e03350820a6e` (подтверждено как
pre-deploy SHA сервера при деплое 2.58.79: `git rev-parse HEAD` на
`/var/www/admin_bot` до pull = b9ea4907), healthz отдавал
`{"status":"ok","version":"2.58.78"}` на всех проверках 2026-10-15/16. Т.е.
статус «deployed» был True, а поле в отчёте — не заполнено: чисто
бухгалтерский пробел, не ложный деплой.

**Санкция:** f10-report.md — исторический документ (новый релиз не
переписывает старые артефакты); расхождение фиксируется здесь и в
backlog-строке «v6.3: f10 Deployed SHA заполнен фактическим b9ea4907».

## 2. Механизм, исключающий повтор (B12.5)

1. **Deploy binding в requirements-map**: `candidate_commit` и
   `deployed_commit` map'ы этапа release обязаны совпадать с фактическим
   (gate: `--stage release` падает при несовпадении/пустоте — что и
   произошло при первой пробе после деплоя: gate штатно вернул exit 1 до
   биндинга — механизм работает).
2. **live-canary.md на каждый деплой**: фактические SHA/healthz/journal/B11,
   rollback-цель — до объявления любого статуса.
3. **workflow_state.md** — компактный снапшот с deployed SHA в каждой
   значимой строке; «done» без deployed SHA запрещён (проверка —
   release-reconciliation при релизе).
4. **requirements_gate** — исполняемый валидатор: statuses != VERIFIED у
   mandatory-элементов → release RED (B12.2). Инструкция «не лгать в
   отчётах» подкреплена машинной проверкой.
5. **Никаких авто-бэклогов**: находки без owner-решения обязаны иметь
   verdict в map, а не в «backlog на потом» (проверено двумя циклами
   полноты coverage).

## 3. Статус карты после деплоя 2.58.79

- candidate = deployed = `c2775a54…` (map bind выполняется на join
  live-probe'ов: preprod-пункты → VERIFIED с evidence; postdeploy →
  READY_FOR_LIVE/VERIFIED/BLOCKED_REAL_HUMAN_GATE по фактическим probe'ам).
- Приёмка release-гейта: только после биндинга; ожидаемо часть postdeploy
  (canary 24–48ч, реальные клиенты Telegram) — BLOCKED_REAL_HUMAN_GATE,
  релиз не объявляется финально DONE до их закрытия (B12.3).

## 4. Проверка post-deploy обязательств (B12.4)

- Reviewer + DevOps: REV-W1/W2/W3 Approved; DevOps-отчёт live-canary.md —
  rollback readiness (b9ea4907), smoke health (healthz/api/health/web),
  warnings (2 summary publish известных failsoft — предсуществующие),
  live input/output (journal ingestion_live/WATCHDOG_SWEEP/intiative
  тики), адресная поверхность и canary: V01 canary — monitoring-окно
  владельца (см. live-probes.md).
