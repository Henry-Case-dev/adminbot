# Workflow State (operational checkpoint)

> Краткий оперативный чекпоинт оркестратора. Не транскрипт. Обновляется после каждого верифицированного шага.

- **task_id:** round1025-hotfix6 (пакет «Волна 1.5»)
- **Запрос (источник):** сообщение владельца в чате (баги после приёмки Волны 1) + `plans/current_task.md` (MASTER SPEC v6.0, действует как канон ТЗ). Запрос в `current_task.md` НЕ изменялся.
- **HEAD при старте:** `441e8f7` (== origin/master)
- **Активная фича:** `hotfix6-webview-shell-heartbeat-round1025`
- **Папка:** `plans/archive/hotfix6-webview-shell-heartbeat-round1025/` (spec.md + adr-1025-12 + tasks.md, 38 задач T-2581…T-2618; перенесена из `plans/features/` на Шаге 8 @PM)
- **APP_VERSION:** 2.58.7 (закоммичено `055525c`/`ba75751` и задеплоено на прод)

## Статус шагов (строгий воркфлоу)
| Шаг | Агент | Статус | Evidence |
|---|---|---|---|
| 0 context | @Memory | ✅ | карта кода A–D, KG, конфликт-чек |
| 1 plan | @PM | ✅ | tasks.md T-2581…T-2618; backlog (Волна 1.5, §15 вынесено из F11) |
| 2 design | @Architect | ✅ | spec.md + adr-1025-12-glass-lens-heartbeat-header-shell.md (D1–D5) |
| 3 graph | @Memory | ✅ | ADR-1025-12, relations (amends 9/8/10/1, supersedes §15 F11) |
| baseline | @DevOps | ✅ | тег `pre-round1025-hotfix6`; бэкап `var/backups/hotfix6-round1025-20260922-013551/` |
| 4 build | @Builder | ✅ | A/B/C/D; pytest 8185/0; JS 26/26; matrix 0; APP_VERSION 2.58.7 |
| 5 review | @Reviewer | ✅ | итер.1 Changes requested → итер.2 **Approved** (12/12 закрыто) |
| 6 audit | @Scanner | ✅ | `plans/reports/round1025_hotfix6_scanner_audit.md` — **Critical 0 / High 0** / M1 / L3 / I3 → деплой разрешён |
| 7 merge | @Architect | ✅ | `plans/ARCHITECTURE.md` **§58** (§58.1–§58.9) |
| 8 archive | @PM | ✅ | перенос → `plans/archive/hotfix6-webview-shell-heartbeat-round1025/`; tasks.md T-2615/T-2618 `[x]`; синк backlog (раздел «🌗 Хотфикс-6» + техдолг §58.7) / MEMORY (блок Волны 1.5, §58) |
| 9 deploy | @DevOps | ✅ | коммиты `055525c`/`ba75751` → push `441e8f7..ba75751`; прод fast-forward `4cde1bc..ba75751`; health 200; APP_VERSION 2.58.7; served `?v=2.58.7`; database is locked 0 → `VERIFIED` |
| 10 metrics | @Memory | ⏳ | `plans/metrics.md` + KG финал |

## Верифицированные результаты (evidence)
- `plans/reports/round1025_hotfix6_contrast.md` — AA-таблица панелей (все PASS ≥4.5:1).
- Отчёт Scanner: Critical 0 / High 0; Medium M-H6-1 (перф линзы на устройстве — не блокер, env `UI_LENS_MAX_NODES`).
- Реализовано: A1 foreground-линза `[data-glass="a"]::before` + `filter:url(#lg-lens)` (edge-weighted), `backdrop-filter:url()` удалён, UA-gate снят, кап 6; A2 стекло на sidebar/drawer/header/bottom-nav/more-sheet; B `computeBottomOffset()=max(...)`; C Canvas 2D+rAF heartbeat §15 (states+hysteresis+EMA+dwell, missing≠bad, telemetry `/api/status`, legacy-OFF `heartbeatLegacy`); D двухстрочная шапка + ⛶ по safe-area + резерв `--header-h`.

## Неразрешённое / открытое
- **Live-гейты владельца:** T-2617 (реальный Telegram WebView: преломление/стекло, низ панели в экране, ⛶ vs нативные кнопки, fullscreen, FPS) + ранее открытые T-2409/T-2505/T-2527.
- **Техдолг (не блокеры):** M-H6-1 (перф-замер линзы), L-H6-1 (`role="img"`→button, `hb-tip` через v-show), L-H6-2 (линза скроллится на scroll-контейнерах), L-H6-3 (комментарий stale-порога), I-H6-3 (README «5936»), + незапущенный playwright в CI.
- **Pending sync (Шаг 10 @Memory):** `plans/reports/full_audit_results.md` / `audit_backlog.md` не обновлены @Scanner (успел только `global_map.md`). PM их не правит (чужие отчёты) — зафиксировано в backlog §58.7 и MEMORY.
- **Не трогать на Шаге 10 (метрики):** `plans/metrics.md` (Шаг 10 @Memory). `stash@{0}` / теги `pre-round1025*` / бэкапы — НЕ удалять (R18).

## Деплой
- **ЗАДЕПЛОЕНО и `VERIFIED`** (Шаг 9 @DevOps). Прод HEAD `ba75751` (== origin/master), `APP_VERSION` **2.58.7**, health 200, `database is locked` 0. Evidence: `plans/archive/hotfix6-webview-shell-heartbeat-round1025/deployment.md`.
- Откат: тег `pre-round1025-hotfix6` + `git revert`; soft-откат — env-флаги `UI_HEARTBEAT_CANVAS_ENABLED`/`UI_HEADER_COMPACT_V2`/`UI_GLASS_TIER_OVERRIDE`. Бэкапы/теги/`stash@{0}` не удалять (R18).

## Last update
- 22.09.2026 — Шаг 9 @DevOps (Deploy Phase) выполнен: коммиты `055525c` (код+тесты) и `ba75751` (планы), push в origin/master, прод fast-forward `4cde1bc..ba75751`, рестарт, health 200, `APP_VERSION` 2.58.7, served `?v=2.58.7`, `database is locked` 0 → `VERIFIED`. Следующий — Шаг 10 @Memory (metrics + KG + pending sync).
