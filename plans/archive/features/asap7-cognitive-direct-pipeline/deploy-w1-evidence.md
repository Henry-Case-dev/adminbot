# DEPLOY-W1 — asap7 wave1 (e6670b0, 2.58.72) — 09.10.2026

**Результат: VERIFIED** (прод 2.58.71 → **2.58.72**, один основной SSH-прогон по fail2ban-дисциплине AGENTS.md; первый короткий прогон был abort-фильтром pre-state до pull — прод не тронут).

## Параметры
- **DEPLOY_SOURCE:** immutable commit `e6670b0` (origin/master, review Approved REV-1). **MUTABLE_WORKTREE_REQUIRED: no** (локальные правки Wave 2 не затронуты, на прод не переносились; прод забрал только origin/master).
- Прод pre-state: HEAD `9f803aa` (2.58.71 без двух docs-коммитов — 08a8849/e6670b0), healthz 200 @2.58.71, DIRTY=13 (untracked-хвост, не мешает ff).
- Rollback source: `git reset --hard e6670b0~1` (9f803aa) + restart; ΔDDL=0 обе стороны. Бэкап: `/tmp/pre_w1_20261008_225407.db` (VACUUM INTO, integrity ok, UV=34, tables=120, 1.33 GB) — не потребовался.

## Ход
1. `git pull --ff-only`: `9f803aa → e6670b0` (fast-forward, полный hash подтверждён `git rev-parse HEAD`).
2. Identity sha256 5/5: `bot.py`, `config/settings.py`, `handlers/chat_lifecycle.py`, `services/module_registry.py`, `services/cover_style_jobs.py` — прод = локальный e6670b0 байт-в-байт.
3. `CHAT_PROFILE_FALLBACK_ENABLED` default ON в коде (settings.py:592, `_env_bool(..., True)`) — в .env писать нечего (как и заявлено в лейне). `APP_VERSION = "2.58.72"`.
4. Restart #1 `sudo systemctl restart admin_bot`: HZ1_TRY1=502 → TRY2=200 (нормальный systemd-интервал); PID 363294 → 706380; тело healthz сразу **2.58.72** (второй рестарт не понадобился).
5. Смоуки (с прода + внешне): `/healthz` 200 @2.58.72; `/web/` 200, DOCTYPE+app.js (index перерендерен при старте, len 549548); `/api/config` и `/api/access/chats` unauth **401** — RBAC жив.
6. Boot-батарея (journalctl с 22:56:23 UTC, 226 строк, артефакт `startup_prod_w1_e6670b0.log`): **ERR=0, CRIT=0, LOCKED=0, NameError=0, NRestarts=0, ExecMainStatus=0, active**; «Bot started, listening for messages» присутствует; tma-auth в хвосте отклоняет неавторизованные.
7. Финально (внешне, ~23:05 UTC): `/healthz` 200 @2.58.72, `/web/` 200.

## Отклонение от гейта «Traceback=0» (задокументировано)
Ровно 1 traceback на буте: `EmbeddingGroupCoolingDown: embedding quota group cooling down: unknown until 1791504300` внутри `embedding_canary_check` (embedding_control_plane.py:2010→scheduler.acquire). Классификация: **incidental, pre-existing/environmental, low** — квотный cooldown внешнего embedding-провайдера (временнОе состояние до рестарта, не код Wave 1); путь задокументирован как fail-safe → «unknown», бот продолжает старт, retrieval fail-soft FTS-only (A06). ERR/CRIT=0 подтверждает отсутствие другого ущерба. Чинить в этом деплое нечего (не дефект e6670b0); наблюдение оставить воркеру embedding-домена.

## Owner/acceptance-шаги (не блокируют деплой)
- Авторизованный `/api/config`: наличие ключа `registry/modules` (нет TMA-админ-сессии у DevOps).
- `/api/access/chats` авторизованный; live-чат: карточка Initiative (#/modules/initiative), badge «неактивен» после добавления бота в новый чат (F5-жизненный цикл), Run Inspector «Фактический промпт» (F8).

## Отчёт
pull fast-forward: **y** (9f803aa→e6670b0) · restart ok (PID 363294→706380, NRestarts=0) · healthz **200 @2.58.72** · boot: ERR/CRIT/LOCKED=0, Traceback=1 (embedding-canary quota, см. выше) · смоуки: healthz/web/401-RBAC зелёные · блокеров нет.
