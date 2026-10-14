# DEPLOY-W2 — asap7 wave2 (71b3b69, 2.58.73) — 09.10.2026

**Результат: VERIFIED** (прод 2.58.72 → **2.58.73**, один основной SSH-прогон + один короткий recon (~15 с) по fail2ban-дисциплине AGENTS.md; ssh-ключ, пароли только через stdin/askpass, не печатались).

## Параметры
- **DEPLOY_SOURCE:** immutable commit `71b3b69` (origin/master, REV-2 Approved после речека B11). **MUTABLE_WORKTREE_REQUIRED: no** (локальный незакоммиченный шум не тронут, прод забрал только origin/master).
- Прод pre-state: HEAD `e6670b0` (2.58.72), healthz 200 @2.58.72 (внешне), DIRTY=13 (untracked-хвост, ff не мешает).
- Rollback: cold `git reset --hard 71b3b69~1` (= e6670b0) + restart; soft `DIRECT_L1_ENABLED=false`, `SUMMARY_COVER_PROMPT_ORDER=style_first` (оба default в коде, .env не трогали). ΔDDL=0 обе стороны. БД-бэкап не требовался (миграций нет).

## Ход
1. `git pull --ff-only`: `e6670b0 → 71b3b69` (fast-forward, creds из кэша гита; askpass-фолбэк не понадобился), полный hash подтверждён `git rev-parse HEAD`.
2. Identity sha256 5/5: `bot.py`, `config/settings.py`, `services/direct_l1.py`, `services/direct_capabilities.py`, `services/cover_style_jobs.py` — прод = локальный 71b3b69 байт-в-байт.
3. Defaults в коде на проде: `DIRECT_L1_ENABLED` → True (emergency kill-switch), `SUMMARY_COVER_PROMPT_ORDER` → "story_first", `APP_VERSION = "2.58.73"`; .env не менялся.
4. Restart `sudo systemctl restart admin_bot` (MARK 2026-10-09 00:25:28 UTC): healthz 200 с 8-й попытки (~24 c, нормальный стартовый интервал); тело сразу **2.58.73**.
5. Статус: active/running, PID **723867**, NRestarts=0, ExecMainStatus=0, ExecMainStartTimestamp 00:26:29 UTC.
6. Boot-батарея (journalctl с MARK, 219 строк, артефакт `startup_prod_w2_71b3b69.log`): **ERR=0, CRIT=0, NRestarts=0**, «Bot started, listening for messages» присутствует.
7. Смоуки (с прода 127.0.0.1:8000 + внешне https://admin-bot.duckdns.org): `/healthz` **200 @2.58.73** обе стороны; `/web/` **200** (index перерендерен, 606882 байт); unauth `/api/config` **401**, `/api/access/chats` **401** — RBAC жив.

## Отклонение от гейта «Traceback=0» (задокументировано)
Ровно 1 traceback на буте: `EmbeddingGroupCoolingDown: embedding quota group cooling down: unknown until 1791590700` внутри `embedding_canary_check` (embedding_control_plane.py:2010 → scheduler.acquire, 00:26:50 UTC). Классификация: **incidental, pre-existing/environmental, low** — идентичен W1-кейсу (см. deploy-w1-evidence.md §«Отклонение»): квотный cooldown внешнего embedding-провайдера при старте, fail-safe → retrieval fail-soft, бот продолжает старт. ERR/CRIT=0 — другого ущерба нет. Код Wave 2 не затронут; наблюдение остаётся за embedding-доменом.

## Owner/acceptance-шаги (не блокируют деплой)
- Авторизованный live-чек L1 Planner в действии (пре-тул планирование, capability-resolve в тул-фазе, L2 Writer) и Direct Golden D-сценарии в живом чате — owner-гейт.
- Cover: GENERATE с сюжетом → порядок промпта STORY_SCENE→SUMMARY_CONTEXT→BASE_STYLE (content-loss fix) — проверяется владельцем на живой генерации.

## Отчёт
pull fast-forward: **y** (e6670b0→71b3b69, cached creds) · restart ok (SUDO_RC=0, PID→723867, NRestarts=0) · healthz **200 @2.58.73** (внутрь+внешне) · boot: ERR/CRIT=0, Traceback=1 (embedding-canary quota, pre-existing, см. выше) · смоуки: healthz/web/401-RBAC зелёные (обе стороны) · блокеров нет.
