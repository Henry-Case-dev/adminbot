# Runtime Task — ASAP 8 v6 (финальное состояние)

Status: **код запуска завершён** — все волны (A/B/C/P1/UI/D14) реализованы,
отревьюены и закоммичены; кандидат D14 (help-каноны v9/v6 + f10) в дереве,
ожидает коммита/деплоя Orchestrator'ом. Финальная reconciliation:
`plans/features/asap8-v6-remediation/f10-report.md`.

- Бaseline запуска: `1e98027` (2.58.77). Финальный HEAD: `217c965`
  (2.58.77, волны v6) + D14-кандидат. **Deployed SHA: pending** (ожидается
  2.58.78; до деплоя live-вердикты не заявлять).
- Фича: `plans/features/asap8-v6-remediation/` — ledger-c/ledger-d,
  requirements-map, forensic, волновые отчёты (wa1/wa2/wa3, wc-direct,
  c03a, c06a, d05, d06, d07, p1-d091011, d1213, d14), rca-c03a/rca-c06a,
  f10-report.

## Что закрыто кодом (кратко)

C03A (styled recovery), C06A (initiative hot-toggle + funnel UI),
C10 (этот f10), D01–D14. Таблицы с пер-ID вердиктами и живыми гейтами —
f10-report §2/§3. Help синхронизирован: INFO v9 (§10 стиль сохраняет сюжет),
GUIDE v6 (§5/§10/§12/§13/§14/§18), слепки `PREV_ASAP8V6_*`, миграции через
существующий generic-механизм config_cache (ΔDDL=0, Δroutes=0).

## Гейты до полного закрытия запуска

1. Коммит D14-кандидата + деплой 2.58.78 (deployed SHA зафиксировать в f10).
2. Prod-пробы по строкам f10 §2/§3 (по одной целевой пробе на ID; список —
   в колонке «что закрывает VERIFIED_LIVE»).
3. OWNER_VISUAL_PENDING (f10 §5): вкус Save-чипа, прод-данные run-карточек,
   живые стиль/инициатива.

## Осознанные остатки (backlog, не P0)

search_result producer; GraphRAG `_vec_candidates` scope; partition key DDL;
7 виджетов D12; demote_reason; diction style_job_failed; Stories
recall-эмиттер. Обоснования и пути закрытия — f10-report §4.

## Не трогать

`plans/workflow_state.md` (Orchestrator), `plans/current_task.md`
(user-owned), чужой шум дерева (services/disk_retention.py,
tests/test_disk_retention_deploy_backups.py, plans/MEMORY.md, backlog.md,
archive/, reports/mca20_wth, tools/_ui_mca12*, node_modules, AGENTS.md,
package*.json).

Финал невозможен без production proof для P0 и при stale plans-state —
поэтому deployed SHA и прод-пробы остаются обязательными гейтами.
