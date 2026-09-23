# deployment.md — `polygonal-luminescence-round1026`

> **Feature:** `polygonal-luminescence-round1026` (EXTRA-визуальный эпик, маркер `POLYGON-LUMINESCENCE-OK`)
> **Роль:** @DevOps · **Статус:** Block 0 (baseline) выполнен; рантайм-деплой — **T-3217** (Блок P).

## Блок 0 — T-3162 (точка отката + бэкап + baseline): **NOT_APPLICABLE**

На этом шаге **поставка рантайма не выполнялась** — это подготовка до правок (Block 0), а не выпуск фичи.
Причина NOT_APPLICABLE: изменения кода/ассетов ещё не созданы; прод не затрагивался; `APP_VERSION` не менялся; миграции не запускались.

**Что фактически сделано (evidence):**
- Annotated-тег **`pre-round1026-visual`** → `9d046e5` (push в origin ✅; tag-object `4b78e82`).
- Бэкап из HEAD: `var/backups/visual-round1026-20260923-142355/` (+ `BASELINE.md`, SHA-256 всех файлов).
- `.env.bak.round1026-visual` (размер/хеш совпали с `.env`; gitignored; содержимое не раскрывалось).
- Baseline: HEAD `9d046e5`, `APP_VERSION` `2.58.18`, pytest `.venv` **8501/0**, JS **42/42**, `database is locked`=0, каталог **467/426/442/100/98/21**, `user_version`=12, **Δ DDL = 0**.
- Vendor: `delaunator` ещё не добавлен (ожидаемо до T-3166/T-3167); `node_modules` gitignored; `web/static/vendor/delaunator.5.0.0.min.js` отсутствует.
- R18: `stash@{0}`, ранее созданные теги/бэкапы не тронуты. В git не коммитилось.

Подробности: `var/backups/visual-round1026-20260923-142355/BASELINE.md`.

## Handoff
**RESULT: NOT_APPLICABLE (Block 0 / T-3162) — точка отката готова @Orchestrator** — тег `pre-round1026-visual`(→`9d046e5`) в origin, бэкап `var/backups/visual-round1026-20260923-142355/`, `.env.bak.round1026-visual` (hash-match), baseline 8501/0 · JS 42/42 · каталог 467/426/442/100/98/21 · Δ DDL=0, vendor без `delaunator`, R18 соблюдён, в git не коммитилось. Далее: Block 0 T-3163 @Architect.
