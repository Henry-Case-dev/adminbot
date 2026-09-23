# deployment.md — `polygonal-luminescence-round1026`

> **Feature:** `polygonal-luminescence-round1026` (EXTRA-визуальный эпик, маркер `POLYGON-LUMINESCENCE-OK`)
> **Роль:** @DevOps · **Статус (T-3217, Блок P):** **VERIFIED** ✅
> **Окружение:** прод `/var/www/admin_bot` (`nik@198.46.175.136`), systemd-юнит `admin_bot` (`ExecStart=…/venv/bin/python bot.py`, `User=root`).
> **Live-гейт владельца:** живой Telegram WebView / стекло — **PENDING OWNER VERIFICATION** (см. ниже).

---

## 1. Блок 0 — T-3162 (точка отката + бэкап + baseline): **NOT_APPLICABLE**

На этом шаге **поставка рантайма не выполнялась** — это подготовка до правок (Block 0), а не выпуск фичи.
Причина NOT_APPLICABLE: изменения кода/ассетов ещё не созданы; прод не затрагивался; `APP_VERSION` не менялся; миграции не запускались.

**Что фактически сделано (evidence):**
- Annotated-тег **`pre-round1026-visual`** → `9d046e5` (tag-object `4b78e82`; в origin ✅).
- Бэкап из HEAD: `var/backups/visual-round1026-20260923-142355/` (+ `BASELINE.md`, SHA-256 всех файлов).
- `.env.bak.round1026-visual` (размер/хеш совпали с `.env`; gitignored; содержимое не раскрывалось).
- Baseline: HEAD `9d046e5`, `APP_VERSION` `2.58.18`, pytest `.venv` **8501/0**, JS **42/42**, `database is locked`=0, каталог **467/426/442/100/98/21**, `user_version`=12, **Δ DDL = 0**.
- Vendor: `delaunator` ещё не добавлен (ожидаемо до T-3166/T-3167); `node_modules` gitignored; `web/static/vendor/delaunator.5.0.0.min.js` отсутствует.
- R18: `stash@{0}`, ранее созданные теги/бэкапы не тронуты. В git не коммитилось.

Подробности: `var/backups/visual-round1026-20260923-142355/BASELINE.md`.

---

## 2. Шаг 9 / T-3217 — поставка рантайма: **VERIFIED** ✅

### 2.1 Коммиты и рассылка

| Роль | Commit | Содержимое |
|---|---|---|
| код + тесты + vendor | **`76fc5e1`** | `web/static/polygon-background.js`, `web/static/vendor/delaunator.5.0.0.min.js` (+README), `web/index.html`, `web/app.js`, `web/static/app.css`, `web/static/glass.js`, `config/settings.py`, `web/api/routes.py`, `.env.example`, `.gitignore`, `README.md`, `tools/vendor/*`, тесты (новые + правки версий), `tools/{ui_round1026_polygon.py,polygon_glass_probe.py,ui_round1025_matrix.py}` (38 файлов) |
| планы / Merge §72 / архивация / Scanner-аудит | **`bf46360`** | `plans/**` (ARCHITECTURE §72, MEMORY, backlog, workflow_state, reports/*, `archive/polygonal-luminescence-round1026/**`) — 17 файлов |
| deploy-doc (этот файл) | см. коммит, добавивший `deployment.md` в `VERIFIED` | `plans/archive/polygonal-luminescence-round1026/deployment.md` |

- **Push:** `origin/master`, без force — **`9d046e5..bf46360`**.
- **Прод fast-forward:** `89bda3d..bf46360` (`git pull --ff-only`, **2026-09-23T03:07:10Z**).
- `APP_VERSION`: **2.58.18 → 2.58.19** (bump в `config/settings.py`, cache-bust ассетов эпика).

### 2.2 Релизные команды (фактические)

```
# локально
git commit -F c1.txt   # -> 76fc5e1 (код+тесты+vendor)
git commit -F c2.txt   # -> bf46360 (планы: §72 + архивация + Scanner-аудит)
git push origin master                 # 9d046e5..bf46360 (без force)

# прод /var/www/admin_bot
git pull --ff-only                     # 89bda3d..bf46360
sudo systemctl restart admin_bot       # активен, MainPID 353131, NRestarts 0 (старт 2026-09-23T03:08:41Z)
```

### 2.3 Health и версии

- `/api/health` → **HTTP 200** `{"status":"ok"}`.
- `/healthz` → **HTTP 200** `{"status":"ok","version":"2.58.19"}`.
- Фактический `APP_VERSION` в проде (`venv/bin/python -c "import config.settings"`): **`2.58.19`**.
- Отдаваемый `index`: `?v=2.58.19` — **12** вхождений; плейсхолдер `__APP_VERSION__` = **0**.
- Флаг доставки фонового рендерера: `UI_POLYGON_BG_ENABLED=**True**` (env-only, default ON; правка `.env` не требовалась).

### 2.4 Новые ассеты (same-origin, CSP `script-src 'self'`)

| Ассет | HTTP | Примечание |
|---|---|---|
| `/web/static/polygon-background.js` | **200** | 33 893 Б; маркер `__PolygonBackground` присутствует |
| `/web/static/vendor/delaunator.5.0.0.min.js` | **200** | 8 454 Б; vendored IIFE (ISC), без CDN |
| `/web/static/app.css` | **200** | — |
| `/web/static/aurora-flow.js` | **200** | сохранён как soft-откат |
| `/web/static/glass.js` | **200** | — |
| `/web/app.js` | **200** | отдаётся как `/web/app.js?v=2.58.19` |

- Off-origin (`src="http(s)://…"`) ссылок в отдаваемом `index` — **0** (CDN не используется).
- Подключение Delaunator — **до** `polygon-background.js`; «ровно один фоновый рендерер» выбирается матрицей `_syncBgLayer` (ON → Polygon; OFF → legacy Aurora `__AuroraFlowLegacy`); в DOM не более одного активного rAF-фонового канваса.

### 2.5 Стабильность и логи

- Текущий запуск (MainPID **353131**, ~166 строк journald): `database is locked` = **0**, `Traceback` = **0**, `ERROR/CRITICAL` = **0**.
- Последнее историческое `database is locked` — **Sep 20 10:06** (до этого деплоя, не связано); последний исторический `Traceback` — **Sep 23 01:01** (до рестарта 03:08).
- Старт бота/планировщика — OK: `Scheduler started`, `Goodmorning scheduler started`, `Start polling` / `Run polling for bot @PERMsoc_bot`, `UptimeHeartbeatService._heartbeat` выполняется по расписанию; бот обслуживает живой трафик (direct reply / саммари / изображения) без ошибок.
- **Миграции:** не выполнялись; **Δ DDL = 0**; `services/param_catalog.py` не изменён (**Δ каталога = 0**).

### 2.6 Откат (готовность)

- **Точка отката (hard):** annotated-тег **`pre-round1026-visual`** → `9d046e5` (в origin) + `git revert` коммитов `76fc5e1`/`bf46360`; бэкапы `var/backups/visual-round1026-20260923-142355/` и `.env.bak.round1026-visual` целы.
- **Мягкий откат (без редеплоя):** `UI_POLYGON_BG_ENABLED=false` в `.env` + рестарт → возврат к Dark Aurora Flow (OGL); `aurora-flow.js` остаётся в поставке.
- R18: теги/бэкапы/`stash@{0}` **не удалялись**; force-push не выполнялся; `deploy_commands.txt` не трогался.

### 2.7 Честные ограничения

- **HTTP 200 ≠ качество фона.** Все проверки выше подтверждают доставку, отсутствие регрессий и целостность рантайма — но **не** визуальное качество полигональной сети/света/bloom.
- Живой **Telegram WebView / стекло** (реальный WebKit/WebView, а не headless Chromium) — **PENDING OWNER VERIFICATION** (открытый live-гейт; шаги J/1/5/7 в архиве помечены `[ ]`).

---

## 3. Handoff

**RESULT: VERIFIED (Шаг 9 / T-3217) @Orchestrator** — коммиты `76fc5e1` (код+тесты+vendor) + `bf46360` (планы: §72 + архивация + Scanner-аудит) + deploy-doc (этот файл); push `origin/master` `9d046e5..bf46360` без force; прод `/var/www/admin_bot` fast-forward `89bda3d..bf46360`; `systemctl restart admin_bot` → **active** (MainPID 353131, NRestarts 0); `/api/health` **200**, `/healthz` **200** (`version 2.58.19`); `APP_VERSION` **2.58.19**; served `?v=2.58.19` (×12, placeholder 0); `polygon-background.js` и `vendor/delaunator.5.0.0.min.js` — **200** same-origin (off-origin 0); `database is locked`=**0**; бот/планировщик стартуют. Откат: тег `pre-round1026-visual` → `9d046e5` + `git revert`; soft — `UI_POLYGON_BG_ENABLED=false`. **HTTP 200 ≠ качество фона; живой WebView/стекло — PENDING OWNER VERIFICATION.** Далее: Шаг 10 @Memory (`plans/metrics.md` ещё не затронут).
