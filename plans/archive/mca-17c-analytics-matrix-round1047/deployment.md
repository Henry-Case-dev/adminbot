# Deployment — mca-17c-analytics-matrix (T-5198)

**Статус:** ✅ **VERIFIED** (07.10.2026) · **Версия:** 2.58.65 → **2.58.66** · **Δ DDL = 0 — МИГРАЦИЙ НЕТ ВООБЩЕ**

## Биндинг и кандидат

- Ревью **Approved (итер.2)**, Scanner **«к деплою ДА»** (все классы 0).
- WTH-манифест `plans/reports/mca17c_wth_manifest_review.txt`: `MANIFEST_SHA256 5e35f97f…22fb7bb`, FILE_COUNT 23.
- Preflight DevOps: **23/23 файлов байт-в-байт**, манифест-хеш пересчитан — совпадение 1-в-1.
- Единственная пост-ревью девиация кандидата — **1 assert-строка** `tests/test_mca17c_invariants_round1047.py:107` (пин APP_VERSION 2.58.65→2.58.66); санкционировано самим тестом («bump — домен @DevOps, T-5198»), докстринг/замеры биндинга не тронуты. Остальные 22/23 — без изменений.

## DEPLOY_SOURCE

- `DEPLOY_SOURCE`: git-коммит **`e16be7e`** (feat, 56 файлов, +3789/−40) на `origin/master` (push ff `844ad15..e16be7e`, без force).
- Прод: `git pull --ff-only` **`3dfc892 → e16be7e`**, один SSH-коннект (AGENTS.md-дисциплина: единственный логин, без ретраев).
- `MUTABLE_WORKTREE_REQUIRED: no` — деплой из immutable-коммита; прод-дерево чистое. Следующая фича (mca-21, контент-фаза) может готовиться параллельно без сериализации с деплоем.
- Репо-файлы, созданные деплоем: `plans/features/mca-17c-analytics-matrix/deployment.md` (этот) + `startup_prod_t5198.log` (boot-лог 441 строка, в пакете фичи); `tools/_d2_t5198_deploy.py` — untracked-раннер по прецеденту `_d2_*`, не коммитится.

## Release-свип (вне манифеста, прецедент mca-12 `3dfc892`)

APP_VERSION (`config/settings.py`), README header, F8 meta-pin (`plans/docs/param-registry-round1025.meta.md`), 24 py-пина (23 файла ×1 + polygon ×2), 4 js-харнесса (regex-пины hotfix7/8/9/10). Санкционные числа НЕ тронуты: каталог 523 (F8 NA), KS 85, тулы 14 — финальны по ревью.

## Прогоны (деплой-окно)

| Прогон | Результат |
|---|---|
| Focused mca-17c (API 15 + инварианты 8) | **23 passed** |
| JS `tests/js` полный набор | **62/62** (58 сразу + 4 после regex-пин-свипа) |
| Полный pytest foreground | **12338 passed / 4 failed** — ровно 4 документированных pre-existing (tool_loop / nav_disclosure / status_control / mca09-registry); сходится с Builder-замером 12338/4 1-в-1 |
| F8 реестр | 29 passed |

Примечание: первая попытка полного набора 12336/6 — хвост свипа (meta-pin, исправлен) + средозависимый флейк `test_betterstack_handler::test_real_302_not_followed_by_opener` (сетевой real-302; изолированно 1 passed и в финальном полном прогоне зелёный — не воспроизвёлся). Флейк-класса 2 прогона подряд не образует; в backlog не добавлял.

## Прод-верификация (оба рестарта `systemctl restart admin_bot`)

- Identity-хеши на проде **9/9** байт-в-байт: `web/api/oversight_router.py`, `services/mca_events.py`, `services/task_supervisor.py`, `web/api/__init__.py`, `config/settings.py`, `web/app.js`, `web/app.py`, `web/index.html`, `web/api/routes.py` (byte-freeze пин `8153b8bd…c7b45` цел).
- **БЕЗ МИГРАЦИЙ — доказано продом**: `user_version=33`, `tables=120` до=после обоих рестартов; каталога миграций нет, вызовов не было (Δ DDL=0).
- Kill-switches: **0 env-оверрайдов** (`grep '^MCA_' .env` = 0) — все 85 default ON.
- Health: `/healthz` **200 @2.58.66** ×3 (после рестарта #1 и ×2 после #2), `/api/health` **200**.
- Overside-смоуки (маршруты mca-17c смонтированы, RBAC жив), unauth → **401 ×3** после каждого рестарта: `GET /api/oversight/runs`, `GET /api/oversight/experience/funnel`, `POST /api/oversight/jobs/{id}/action`.
- Журнал окна деплоя (441 строка): ERROR/CRITICAL/Traceback/NameError/`database is locked` = **0**; `[vision] media worker started` ×2 (воркер жив после обоих рестартов); oversight-упоминания в логе живы; `MainPID` стабилен, **NRestarts=0**, ExecMainStatus=0.
- R17: **SECRET_HITS = 0** — 6 паттернов (sk-keys/bearer/password-assign/token-assign/private-key/initData-hash) по полному boot-логу `startup_prod_t5198.log`.

## Откат

- **Soft:** read-side фича — витрина/лейблы нейтральны; единственный write — `POST /api/oversight/jobs/{id}/action` через существующие операции TaskSupervisor (гейт RBAC global-admin); отдельных KS для 17c нет (Δ KS=0 по санкции) — soft-рубильника фича не имеет и не требует.
- **Cold:** `git revert e16be7e` (локально) → на проде `git reset --hard 3dfc892` + рестарт. DDL/каталог/KS не менялись — БД совместима в обе стороны (v33 идемпотентна для 2.58.65↔2.58.66). Автороллбэк при срыве healthz встроен в драйвер (прецедент T-5174), не потребовался.

## Инцидентальные наблюдения (не блокеры)

- 502 на первой пробе healthz после каждого рестарта (TRY1), 200 на второй (~15 с) — нормальный systemd-интервал перезапуска, воспроизводимо и в mca-12; не дефект.
- Параллельные сессии: PM пишет `plans/features/mca-21-guides/` (контент-фаза) — в деплой не входило, дерево прод-фичи не пересекается.

## Итог

**VERIFIED.** Кандидат `e16be7e` задеплоен на прод (2.58.66), health/smoke зелёные, откат-состояние известно (cold revert, DDL-совместимость в обе стороны), блокеров деплоя нет. Baseline-абсолют для следующих раундов: **прод = `e16be7e`, 2.58.66, v33, каталог 523, KS 85, reason 280, тулы 14, routes-py pin `8153b8bd…c7b45`**.
