# deployment.md — mca-12-miniapp-stories (T-5174)

**Результат: VERIFIED.** Дата: 07.10.2026. Прод: 198.46.175.136 (`/var/www/admin_bot`, systemd `admin_bot`).

## 1. Биндинг и источник

- Кандидат: review Approved (итер.1) + Scanner «к деплою ДА» (все классы 0).
- Манифест: `plans/reports/mca12_wth_manifest_review.txt`, `MANIFEST_SHA256 a0bdb9cf…0952`, FILE_COUNT 25, HEAD-линия `e12a94d1`.
- Preflight DevOps: **25/25 файлов байт-в-байт** (per-file SHA256).
- `DEPLOY_SOURCE`: коммит **`3dfc892`** (feat mca-12, 56 файлов; push ff `e12a94d..3dfc892`).
- Прод: `git pull --ff-only` `0db30a2 → 3dfc892`; identity-хеши 10 ключевых файлов (web/api/stories.py, services/web_stories.py, services/mca_gates.py, services/mca_episodes.py, config/settings.py, web/app.js, web/app.py, web/index.html, web/static/app.css, web/api/__init__.py) — совпали байт-в-байт с локальным деревом.
- `MUTABLE_WORKTREE_REQUIRED: no` — деплой из immutable-коммита; рабочий tree локально не задействован. Параллельная подготовка следующей фичи (mca-17c/mca-21) не конфликтует.

## 2. Релизный bump (release-owned, вне манифеста)

- `APP_VERSION 2.58.64 → 2.58.65` (config/settings.py:3209).
- README header `v2.58.65`; F8 meta-pin `plans/docs/param-registry-round1025.meta.md`.
- Release-pin sweep: 24 py-пина (23 файла: `assert APP_VERSION == "2.58.65"` / SETTINGS-needle) + 4 js-харнесса (`APP_VERSION = "2\.58\.65"`). Исторические markdown-упоминания (инцидент 2.58.64, фингерпринты ревью) не тронуты.

## 3. Миграции и kill-switch

- **МИГРАЦИЙ НЕТ (Δ DDL = 0)** — миграции не вызывались. Доказано продом: `user_version=33`, `tables=120` **до и после** обоих рестартов.
- KS: `.env` — 0 оверрайдов (`^MCA_` count=0), в т.ч. `MCA_STORIES_*` не переопределены; оба гейта `MCA_STORIES_VITRINA_ENABLED` / `MCA_STORIES_MANAGE_ENABLED` default **ON** в коде (settings.py + mca_gates.py) → эффективны ON.
- Счётчики (финальны от Builder, не менялись): каталог 523 (F8 NA), KS 85, reason 279, тулы 14; `ROUTES_SHA256_F11` пин `8153b8bd…` не изменился (routes.py byte-freeze, проверен тестом).

## 4. Прогоны до деплоя (две независимые верификации, 0 новых фейлов в обеих)

- Focused mca-12: **22 passed**. js: **61/61**.
- **Полный pytest foreground (DevOps):** попытка 1 сорвалась на средозависимом hang `test_summary_memory` (aiosqlite lock-wait, 74%; изолированно файл зелёный — 79 passed); попытка 2 чистая: **12315 passed / 4 failed** — все 4 документированные pre-existing (tool_loop / nav_disclosure / status_control / mca09-pollution).
- **Сегментная верификация (оркестратор, прецедент mca-19/20):** g1 4291 passed / 0; g2 3748 / 1 (mca09 `test_registry_process_intent_initiative`, pre-existing); g3 4274 / 3 (`tool_loop`, `webapp_nav_disclosure`, `webapp_status_control` — pre-existing). Итого **12313 passed / 4 pre-existing, 0 новых**; identity 4 фейлов совпадают с полным прогоном. Счётчики сбора полного (12319) и сегментного (12317) прогона различаются на 2 — методика разбиения, не продукт (критерий «0 новых» выполнен в обеих методиках).
- **Изолированные перепрогоны:** `test_summary_memory.py` — 79 passed (файл зависания фонового прогона сам зелёный → класс среды/порядка, backlog #121); `nostalgia_worker::test_year_back_candidate_sent` — 1 passed изолированно, в сегменте падал → **order-pollution флейк, новый член документированной pollution-семьи** (mca09↔17a↔nostalgia; кандидат в backlog-запись, к mca-12 отношения не имеет).

## 5. Прод-верификация (хронология сжата)

- Рестарт ×2; healthz опрос: 502→200 в обоих окнах (штатный бут).
- `/healthz` 200 `{"status":"ok","version":"2.58.65"}` ×3 (после рестарта #1 и ×2 после #2).
- `/api/health` 200. Смоук критичного пути: `GET /api/stories/summary` без TMA-auth → **401** ×2 (маршрут смонтирован, RBAC работает; 404/500 отсутствуют).
- Окно журнала (буты B–C, 441 строка, полный лог сохранён: `startup_prod_t5174.log` в этой папке; на проде `/tmp/t5174_boot.log`): ERROR=0, CRITICAL=0, Traceback=0, NameError=0, `database is locked`=0; `[vision] media worker started` присутствует (×2 по рестартам); MainPID=65899, NRestarts=0, ExecMainStatus=0.
- R17: SECRET_HITS=0 (sk-/ghp_/Bearer/password/token/secret — 6 паттернов по полному логу).
- Drivers: `tools/_d2_t5174_deploy.py` (untracked, DevOps-механика, один SSH-коннект, без ретраев — fail2ban-safe).
- Прод остаётся на runtime-коммите `3dfc892` (feat): последующие docs-коммиты (deployment.md, лог) runtime не меняют — прод-pull не требуется (минимизация SSH-коннектов; прецедент mca-20: прод 0db30a2 при origin e12a94d).

## 6. Rollback

- **Soft (первая линия):** `MCA_STORIES_VITRINA_ENABLED=false` (скрывает витрину и read-API — честный disabled) и/или `MCA_STORIES_MANAGE_ENABLED=false` (POST → 409) в `.env` + рестарт. Гейты независимы по осям; фасад mca-05 не выключается.
- **Cold:** `git reset --hard 0db30a2` + `systemctl restart admin_bot`. Δ DDL=0 → БД (v33) совместима в обе стороны, данных-артефактов фича не создаёт.

## 7. Incidental (не блокеры, вне скоупа релиза)

- На проде 13 untracked-записей `git status` (prod-local артефакты: логи/прочее) — pre-existing, деплой не затронул.
- `test_summary_memory` env-hang (aiosqlite lock-wait) — флакующий класс полного набора, backlog #121, к mca-12 отношения не имеет.
