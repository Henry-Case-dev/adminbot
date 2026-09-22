# Deployment — `epic1-verification-round1025` / F10 (Шаг 9 @DevOps, T-3126)

## Вердикт: **NOT_APPLICABLE**

**Тип:** read-only verification-гейт Эпика 1 (стоп-гейт; доказательство, а не реализация).

**Обоснование.** F10 не поставляет рантайм: изменяются только `tools/**` (аддитивное расширение
Playwright-харнесса и E2E-скриптов), `tests/**` и `plans/**` (спека/ADR/отчёты). Рантайм
`services/**`, `web/**`, `web/api/**`, `config/**`, миграции и каталог `param_catalog`
**не менялись** (`git diff` пуст — подтверждено @Reviewer T-3121 и @Scanner T-3122). `tools/**`
и `tests/**` рантаймом **не импортируются** (не входят в поставку приложения), ассеты не менялись →
cache-bust не нужен. Поэтому деплой/рестарт/health-gate/миграции **неприменимы**; `APP_VERSION`
**2.58.17** остаётся без bump (bump без поставки был бы ложным сигналом новой сборки). Прецедент —
F8 (`plans/ARCHITECTURE.md` §67.3). Решения: **ADR-1025-24 D1**, `spec.md` §3.

- Среда деплоя: — (деплой не выполняется)
- Commit/версия: HEAD `57b325c`, `APP_VERSION` **2.58.17** (без изменений)
- Релизные команды: нет; рестарт/миграции не требуются
- Health/smoke: N/A
- Инварианты: **Δ DDL=0**, **Δ каталога=0** (459/418/434/98/96/21), CSP/zero-build, R17/R18
- Откат F10: не требуется (рантайм не поставлен)
- Точка отката Эпика 1 (§117 п.12): annotated-тег **`pre-round1025-f10` → `57b325c`**
  (`git fetch --tags origin && git reset --hard pre-round1025-f10`; см. `evidence.md`)
- Live-гейт: Telegram WebView/TMA — **[ ] PENDING OWNER VERIFICATION** (Chromium ≠ WebView; вне deploy-gate)

Статус: **NOT_APPLICABLE** (обосновано).
