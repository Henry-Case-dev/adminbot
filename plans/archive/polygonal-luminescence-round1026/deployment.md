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

---

## 4. Addendum — v2.58.20 «мерцание свечения фона ×2 медленнее»: **VERIFIED** ✅

> **Контекст:** правка владельца поверх эпика round1026. Мерцание свечения (импульсы свечения узлов §8.3 + «дыхание» радиуса фонового излучения §7.1) замедлено **ровно ×2** (частота ÷2 → период ×2). Дизайн/позиция/оттенок не менялись. Ветка/маркер: `polygonal-luminescence-round1026`.

### 4.1 Коммиты и рассылка

| Роль | Commit | Содержимое |
|---|---|---|
| код + тесты + версия | **`306778a`** | `fix(round1026): … мерцание свечения фона ×2 медленнее (PULSE_SPEED_*/GLOW_SHIMMER_SPEED), APP_VERSION 2.58.20` — `web/static/polygon-background.js`, `config/settings.py`, `README.md`, тесты JS+py (новый гейт `TestGlowFlickerSlowdown` + re-pin версий) — 21 файл |
| планы / Scanner | **`a50b014`** | `docs(plans): round1026 — evidence/review/spec §8.3 уточнение (мерцание ×2), scanner-аудит, метарегистр` — 8 файлов |
| deploy-doc (этот раздел) | см. docs-коммит ниже | `plans/archive/polygonal-luminescence-round1026/deployment.md` |

- **Push** `origin/master`, без force: **`1ad98ca..a50b014`**.
- **Прод fast-forward** `bf46360..a50b014` (`git pull --ff-only`, **2026-09-23T04:07:48Z**).
- `APP_VERSION`: **2.58.19 → 2.58.20** (cache-bust `polygon-background.js`).

### 4.2 Diff-scope (инспекция перед коммитом)

- Изменения ровно в ожидаемых зонах: `web/static/polygon-background.js` (§7.1/§8.3 — введены `PULSE_SPEED_MIN/MAX`, `GLOW_SHIMMER_SPEED`), `config/settings.py` (`APP_VERSION`), `README.md` (версия), тесты, `plans/**`.
- Вне scope — **пусто**: `services/**`, схема БД, `services/param_catalog.py`, `web/static/glass.js`, публикация — не тронуты.
- Секретов/`.env*`/`current_task.md`/zip/`deploy_commands.txt`/`var/backups`/`tools/_ui_*` в наборе коммита **нет** (перечисленные — gitignored, в diff не попадали). Скан diff по паттернам секретов — чисто.
- Тесты локально перед пушем: JS `POLYGON-LUMINESCENCE-OK`; pytest `test_webapp_round1026_polygon.py` **23 passed** (в т.ч. гейт ×2).

### 4.3 Релизные команды (фактические)

```
# локально
git commit -m "fix(round1026): … ×2 медленнее …, APP_VERSION 2.58.20"   # -> 306778a
git commit -m "docs(plans): round1026 — evidence/review/spec §8.3 …"     # -> a50b014
git push origin master                        # 1ad98ca..a50b014 (без force)

# прод /var/www/admin_bot
git fetch origin && git pull --ff-only        # bf46360..a50b014 (2026-09-23T04:07:48Z)
sudo systemctl restart admin_bot              # active, MainPID 366068, NRestarts 0 (2026-09-23T04:09:00Z)
```

### 4.4 Health и версии

- `/api/health` (`127.0.0.1:8000`) → **HTTP 200** `{"status":"ok"}`.
- Фактический `APP_VERSION` в проде (`venv/bin/python -c "import config.settings"`): **`2.58.20`**.
- Отдаваемый `index` (`/web/`): `?v=2.58.20` — **12** вхождений; плейсхолдер `__APP_VERSION__` = **0**.
- `static/polygon-background.js?v=2.58.20` → **HTTP 200**, **35 296** Б; в теле присутствуют новые константы: `PULSE_SPEED_MIN = 0.025`, `PULSE_SPEED_MAX = 0.075`, `GLOW_SHIMMER_SPEED = 0.03` (ровно прежние/2).

### 4.5 Стабильность и логи

- Окно рестарта (~6 мин, MainPID **366068**): `database is locked` = **0**, `Traceback` = **0**, `ERROR/CRITICAL` = **0**.
- Старт бота/планировщика — OK: `Scheduler started`, `Goodmorning scheduler started`, `Start polling` / `Run polling for bot @PERMsoc_bot`.
- **Миграции:** не выполнялись; **Δ DDL = 0**; `services/param_catalog.py` не изменён (**Δ каталога = 0**).

### 4.6 Откат (готовность)

- **Hard:** аннотированный тег **`pre-round1026-visual`** → `9d046e5` (в origin) + `git revert 306778a` (и `a50b014` — только доки); бэкапы `var/backups/visual-round1026-20260923-142355/` и `.env.bak.round1026-visual` целы.
- **Soft (без редеплоя):** `UI_POLYGON_BG_ENABLED=false` + рестарт → Dark Aurora Flow (кэш-баст версии не требуется).
- R18: теги/бэкапы/`stash@{0}` **не удалялись**; force-push не выполнялся; `deploy_commands.txt` не трогался.

### 4.7 Честные ограничения

- Подтверждена **доставка/целостность/отсутствие регрессий** и факт замедления (константы/тесты), но **не** субъективное визуальное впечатление от темпа мерцания — живой **Telegram WebView/стекло** остаётся **PENDING OWNER VERIFICATION**.
- Кэш браузера: ассет отдаётся с `?v=2.58.20`; у клиента с активной старой сессией возможен старый канвас до перезагрузки страницы (не дефект сервера).

### 4.8 Handoff

**RESULT: VERIFIED (Addendum v2.58.20) @Orchestrator** — коммиты `306778a` (код+тесты+версия) + `a50b014` (планы/Scanner); push `origin/master` `1ad98ca..a50b014` без force; прод `/var/www/admin_bot` fast-forward `bf46360..a50b014` (04:07:48Z, `--ff-only`); `systemctl restart admin_bot` → **active** (MainPID 366068, NRestarts 0, 04:09:00Z); `/api/health` **200**; `APP_VERSION` **2.58.20**; served `?v=2.58.20` (×12, placeholder 0); `static/polygon-background.js` **200** (35 296 Б) с `PULSE_SPEED_MIN/MAX=0.025/0.075`, `GLOW_SHIMMER_SPEED=0.03`; `database is locked`=**0**; бот/планировщик стартуют. Откат: тег `pre-round1026-visual` → `9d046e5` + `git revert 306778a`; soft — `UI_POLYGON_BG_ENABLED=false`. **HTTP 200 ≠ субъективный темп мерцания; живой WebView/стекло — PENDING OWNER VERIFICATION.** Далее по процессу: @Architect (reconciliation), @PM (архив), @Memory (sync), запись метрик, следующий F.
