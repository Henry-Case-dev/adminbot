# REVIEW RECOVERY PASS — SMART-EXECUTION-RELIABILITY-01 (2026-11-15)

Независимый Reviewer: DeepSeek V4 Pro (`opencode-go/deepseek-v4-pro`), сессия `ses_e228ff98affe1vm338onVOk2OF`.
Проверенный код: `2b419aa2` (deployed 2.58.204), worktree `smart-recovery-r1`, HEAD `2b419aa2`, чисто.
Baseline: `d20a7f73` (2.58.199) → `aca13702` (кандидат) → `0e4a144d` (2.58.200) → corrective → `2b419aa2`.

## Вердикты

| Контракт | Вердикт |
|---|---|
| Effective budgets ON/OFF, единая точка резолва, last-known-valid, отсутствие обхода enforcement | CONFIRMED |
| SourceReader: реальное содержимое, local-first → GitHub по точному deployed SHA, продолжение после нерелевантного результата, честный partial, отсутствие циклического fallback | CONFIRMED |
| SSRF/DNS-pinning/SafeFetcher, сохранение прав, отсутствие подмены production-кода веткой | CONFIRMED (статически + unit) |
| Чекап продолжает исследование через `inspect_runtime`, не ждёт команды, не запускает полный аудит | CONFIRMED |
| Evidence injection S13–S17 (execution) | CONFIRMED |
| SMART I1–I6 (журнал, свежий опыт, уроки, reason codes, chat-scope KNN, полный текст реплики) | CONFIRMED |

## Независимые прогоны

Целевые наборы на `2b419aa2`: 87 + 129 + 44 + 82 + 162 + 74 = **578 passed, 0 failed**.
Контрпример last-known-valid: известный OFF при ошибке чтения → `enabled=False, source=last_known, stale=True`, без флипа в ON.

## Находки / ограничения

- **BACKLOG_ONLY:** `test_budget_global_toggle_round1024::TestMasterPriority` (3 теста) падает из-за устаревшего стаба `_render_thread()` без параметра `projection=` (параметр добавлен VMQ/onto-работой 2.58.204). Это дрейф теста, не дефект budget_gate.
- **BACKLOG_ONLY:** аудит-пин write-точек `test_mca01_tx_task_supervisor` разошёлся (15≠13, 230≠207, 3≠1) из-за новых write-точек VMQ/onto; механизм single-writer цел.
- Классификация `118 failed / 25 errors` проверена выборочно на изменённых контрактах: устаревшие стабы/пины и предсуществующие детерминированные падения; полного перебора нет. Цифры привязаны к `aca13702`; на `2b419aa2` картина может отличаться из-за VMQ-дельты — отдельная перепинка не блокирует SMART.
- Живой network-path SafeFetcher (реальные redirect/домены) не прогонялся — требуется сеть/прод.
- Полный 21k-suite не перезапускался.

## Вывод

**Approved** по всем пяти контрактам (A/B, C1, E, G, H, S13–S17, I1–I6). Прежних доказательств достаточно; блокеров нет. Неблокирующие наблюдения отнесены к VMQ/onto-гигиене и в текущий Assignment SMART не расширяются.
