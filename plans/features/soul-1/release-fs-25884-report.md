# RELEASE-FS-25884 — изолированный релиз FS-HOTFIX (2.58.84): отчёт

Дата: 2026-10-17, сессия 18:44–18:47 UTC (деплой) + пост-проверки сразу после (серверное UTC; реальные коннекты — два: recon 18:44:30, основной прогон 18:44:5x–18:47).
Лейн: RELEASE-FS (release engineer). Режим: release-ветка + штатный деплой.
Источник семантики: `6094a2cf` (fs-слой W7+FS на master; fs-часть отревьюена: review-fs Needs Fixes→FS2→
RECHECK Approved→BINDING Approved `a891b721`). PET_PROJECT: релиз готового+проверенного исправления выполнен
штатно, без канареечных согласований; тесты/изоляция/откат сохранены.

## Вердикт (одной строкой)

**Кандидат `0b7a0aca` (2.58.84) задеплоен на прод и здоров: healthz `{"status":"ok","version":"2.58.84"}`
(loopback+443+извне), кнопка ⛶ рабочая (tdesktop снова обычный клиент — политика без платформенных запретов),
заглушек нет, §8 admin-инструмент на месте (off by default), логотип скрыт на мобильных; стопы грациозные
(`stop-sigterm`=0, `runtime sqlite closed`→`bye`), ERROR/CRITICAL/Traceback после деплоя = 0; SOUL-1
в релизе нет (изоляция доказана: дельта только fs+N-пины; SOUL-1 byte-diff пуст; маркеры отсутствуют).**

## Deploy binding

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | локальный репо `C:\Code\Python\adminbot`, worktree `OPENCODE_WORKFLOW_SCRATCH/fs-release-25884`, ветка `release/fs-2.58.84`, релизный коммит **`0b7a0aca416a418e099e157eca77d0a3137b3405`** |
| База ветки | **`448cc81a`** (задеплоенный 2.58.83, ветка `release/incident-2.58.83`) |
| Состав | `448cc81a` + **`a4fb04a9`** (семантический порт fs-семантики на прод-версии web-файлов: 9 файлов, +1773/−469) + **`0b7a0aca`** (bump 2.58.84, 31 файл, 33 ins/33 del) |
| Push | `git push -u origin release/fs-2.58.84` (обычный, без force) |
| Сервер | fetch + `git checkout -B release/fs-2.58.84 origin/...`; HEAD `0b7a0aca`, TRACKED_MOD_AFTER=0, COMMITS_ON_BRANCH=**2**, DELTA_FILES=**40** |
| MUTABLE_WORKTREE_REQUIRED | **no** — деплой из immutable закоммиченного дерева; main worktree (master/WIP) не тронут; write scope релиза = только release-ветка/worktree |
| DDL / миграции | ΔDDL = 0, миграций нет |
| Версии | 2.58.83 → **2.58.84** (31 файл: settings + README + F8-meta (HEAD `a4fb04a9`) + 24 py-пина + 4 JS-пина) |
| Rollback | **`448cc81a`** = `release/incident-2.58.83` (2.58.83); резерв — `git checkout --detach 448cc81a9eab…`; DDL-откат не нужен |

## Перенос fs-семантики (что именно приехало)

Прод fs-контур == master-pre-fix (`9d8da1d7`): policy-блоб `18ee7ed72f` совпадает; fs-строки
`app.css`/`app.js`/`index.html` идентичны ⇒ перенос точный:

1. `web/static/fullscreen-policy.js` — **байт-в-байт** из `6094a2cf` (sha256 `96db0642…`): скрытие кнопки только
   при реальном отсутствии API (tdesktop — обычный клиент; `tdesktop_disabled_until_e2e` удалён), авто-`exitFullscreen()`
   на старте launch-fullscreen удалён, сохранены ack-модель/pending-guard/ALREADY_FULLSCREEN без второго request,
   dev-API `explain()/diagnostics()` с F1-фиксом launchParams (sessionStorage `__telegram__initParams` + allowlist).
2. `web/static/app.css` — fs-дифф `9d8da1d7..6094a2cf` применён `git apply` **чисто**: sum-формула нативной зоны
   (`max(env,--tg-safe)+--tg-content`, фикс `d9b7f389` сохранён при нулевом content-inset), сняты float-резерв/fixed-слот,
   `.app-shell.shell-mobile .mobile-brand{display:none}`, компактный ландшафт (.15rem/32px), кнопка «как у нативных»
   (без `::before`/backdrop-filter/круга, ≥44×44), стили §8-панели и оверлея границ.
3. `web/app.js` — fs-дифф применён чисто (7 ханков): зеркала заглушек удалены (`fsReasonText`→0), §8 admin-диагностика
   геометрии (off by default, admin-гейт `isGlobalAdminEffective`, копирование одним действием), `data-fs-scheme`/стекло удалены.
4. `web/index.html` — только fs-ханки (гейт `fsSlot!=='hidden'`, мёртвый `fs-slot-*` удалён, §8 вход в «Ещё»+панель+оверлей);
   **W7-ханки embeddings-primary/`cr.key_source` СОЗНАТЕЛЬНО не взяты**.
5. Тесты/инструменты (были идентичны prod↔pre-fix; диффы полностью fs): `tests/js/asap8_w2_fullscreen_policy_test.js`
   (sha `7614df40…`), `tests/js/asap8_w2_shell_mobile_nav_test.js` (`7ff4d1f6…`), `tests/test_webapp_avatars_ui.py`
   (`b3221746…`), `tools/ui_asap8_w2_fullscreen_e2e.py` (`0fd689fc…`, S1–S13), `tools/ui_asap8_w2_shell_e2e.py` (`0b67e8d6…`).

## Изоляция (доказательства)

1. **Дельта vs `448cc81a` = ровно 40 файлов: 9 fs + 31 версионный пин, 0 неклассифицированных**
   (`isolation-classification.txt`; `delta-files-with-stats.txt`). `services/` в дельте отсутствует целиком.
2. **SOUL-1-набор — byte-diff ПУСТ**: `git diff 448cc81a..HEAD -- services/prompt_registry.py prompt_factory.py
   prompt_composer.py style_policy.py chat_prompts.py response_extent.py direct_l1.py capability_registry.py
   direct_capabilities.py direct_chat_service.py image_generation.py initiative_diagnostics.py initiative_observer.py
   mca_authorial_speech.py mca_humor_craft.py mca_humor_feedback.py mca_sample_library.py prompt_migrations.py
   prompt_style_blocks.py embedding_control_plane.py web/api/speech.py web/api/initiative_vitality.py`
   → `soul1-diff-empty.txt` = **0 байт** (`soul1-diff-empty-len.txt`).
3. **SOUL-1-маркеры в дереве релиза отсутствуют** (`soul1-markers-release-tree.txt`, все hits=0):
   `speechLessonAction`, `#/ai/speech`, `ai/speech`, `initiative-vitality`, `initiativeVitality`,
   `data-embeddings-primary[-warn]`, `cr.key_source`, `@app.get("/api/speech`; плюс fs-отрицания:
   `data-fs-diagnostics`, `fsReasonText`, `fsNextStep`, `fsDiag`, `tdesktop_disabled_until_e2e`, `_softExitTimer`,
   `launchExitIgnored`, `fs-slot-float` — отсутствуют. (`mood`-токены встречаются только в файлах, не входящих в
   дельту — они byte-идентичны проду; master их не менял.)
4. **SOUL-1-only файлы отсутствуют и untracked** (`soul1-absent.txt`): `web/api/speech.py`, `web/api/initiative_vitality.py`,
   `services/prompt_registry.py`, `prompt_factory.py`, `style_policy.py`, `capability_registry.py`,
   `initiative_diagnostics.py`, `mca_authorial_speech.py`, `mca_humor_craft.py`, `mca_humor_feedback.py`, `mca_sample_library.py`.
5. Замечание: ревью-именованные упоминания «SOUL-1» в комментариях `app.css`/`app.js` (HOTFIX-TIERA) — предсуществующие
   на проде и дельтой не затронуты; «SOUL-12.x»-упоминания — только в dev-API-комментариях портированной политики (входят
   в согласованный объём). Файл `tools/ui_soul1_w7_fullscreen_explain_e2e.py` **не портирован** (см. §Девиации).

## Тесты на точном релиз-кандидате (verbatim; все — на дереве ветки)

| Прогон | Результат | Артефакт |
|---|---|---|
| `node tests/js/asap8_w2_fullscreen_policy_test.js` (движок+§8+dev-API) | **FS-POLICY-OK** | `node-guards.txt` |
| Все node-сторожа (`tests/js/*.js`, 84 шт.) | **83/84 OK**, 1 предсуществующий RED | `node-guards.txt` |
| fs-матрица S1–S13 (`tools/ui_asap8_w2_fullscreen_e2e.py`) | **12/12 PASS, 166 проверок** | `e2e-w2/_results.json` + 18 PNG |
| shell-e2e U01 (`tools/ui_asap8_w2_shell_e2e.py`) | `W2-SHELL-E2E-OK`, `failed_checks: {}`, header **116.2px** @320/360/390 | `shell-e2e-run.txt`, `shell-e2e/` |
| pytest focused fs/UI (10 файлов) | **319 passed** | `pytest-fs-focused.txt` |
| pytest summary-family (62 сьюта) | **1442 passed**, 2 warnings | `pytest-summary-family.txt` |
| Source-пины bot.py (76 файлов, glob-конвенция релиза) | **1866 passed / 1 failed** | `pytest-source-pins.txt` |
| 24 py-пина (после bump) | **868 passed** | `pytest-24py-pins.txt` |
| 4 JS-пина (после bump) | `HOTFIX7/8/9/10 … OK` (**4/4**) | — |
| `tools/gen_param_registry_round1025.py --check` (после bump) | `CHECK OK: реестр 572 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны` | `gen-registry-check.txt` |

RED-классификация (оба — **предсуществующие на задеплоенном `448cc81a`**, воспроизведены на чистом worktree
`inc83-tests` (detached HEAD `448cc81a`), файлы дельтой релиза не тронуты):
- node `round1025_design_tokens_test.js` — `TypeError: this._lgGlassSelector is not a function` (мок-тест prod-линии
  отстал от HOTFIX-TIERA обоих master-линков; на master тест обновлён вне fs-слоя);
- pytest `tests/test_webapp_ui_rework_round1020.py::TestLiquidGlass::test_modal_backdrop_blur_token` — тот же RED,
  что документировали 25882/25883 (файл+ассеты не в дельте).

## Прод-верификация (всё с сервера; полный лог `evidence/release-fs-25884/ev_deploy_run.txt`)

### Артефакты (Фаза C) — 7/7 raw-хешей == релизному коммиту
`web/static/fullscreen-policy.js` `96db0642…`, `web/static/app.css` `a54f3856…`, `web/index.html` `4a40a78a…`,
`web/app.js` `c9772329…`, `config/settings.py` `577ded06…`, `README.md` `5749f09a…`,
`plans/docs/param-registry-round1025.meta.md` `808715d0…` (полные sha256 — `hashes.txt`).

### C2 (диск): SOUL-1 отсутствует, fs-маркеры на месте
`SPEECH_ABSENT=1 INITV_ABSENT=1 W1_REGISTRY_ABSENT=1 W1_FACTORY_ABSENT=1 W3_STYLE_ABSENT=1 W10_CAPREG_ABSENT=1`;
`POLICY_TDESKTOP_BAN=0 POLICY_SOFTEXIT=0 POLICY_LAUNCHPARAMS=3 IDX_ADMINTOOL=1 IDX_STUB=0 CSS_LOGO_HIDDEN=1 CSS_FLOAT=0 APPJS_STUB=0 APPJS_BUILD=4`.

### Стопы/рестарты (грациозность; контракт «стоп-строки»)
- **Рестарт №1** (стоп старый 2.58.83, старт 2.58.84): `STOPSIGTERM=0`, `LEFTOVER=0`, `ERR=0`, `CRIT=0`, `TB=0`;
  порядок строк: `stopped accepting new work` → `polling stop | graceful=True | elapsed_ms=278` →
  `SUMMARY_SHUTDOWN_DRAIN` → `runtime sqlite closed` → `[shutdown] bye | elapsed_ms=3787`; процесс вышел сам.
- **Рестарт №2** (стоп новый 2.58.84): `STOPSIGTERM=0`, `LEFTOVER=0`, `ERR=0`, `CRIT=0`, `TB=0`;
  `polling stop` (255 мс) → `runtime sqlite closed` → `bye | elapsed_ms=636`. MainPID после — 3204968,
  `NRestarts=0`, `ExecMainStatus=0`, active/running.
- healthz после рестартов: `{"status":"ok","version":"2.58.84"}` (3-я и 2-я проба, старт ~20–40 с — штатно).

### 443 (Фаза E; caddy, --resolve на loopback)
- HZ443=2.58.84; `/web/` 200, sha served `c174838c…` == расчётной (модель подстановки валидирована на 2.58.83
  значением `c1987340…` из 25883), 14×`2.58.84`, 0×`2.58.83`, admin-инструмент=1, заглушки=0, BotFather=0;
- `/static/app.css` 200, sha `95f24eca…` == расчётной (модель валидирована: 2.58.83-значение `d14a7818…`),
  logo-правило=1, float=0; `/web/static/app.css` raw `a54f3856…`; `/web/app.js` raw `c9772329…`;
  `/web/static/fullscreen-policy.js` raw `96db0642…`;
- SOUL-1-пробы: `/api/speech/overview` **404**, `/api/memory/initiative-vitality` **404**, `/web/api/speech.py` **404**,
  teststand 6 путей 404; живые пути 200.

### Runtime-проба (Фаза F)
`version=2.58.84`; все SOUL-1 отсутствия True; `policy_tdesktop_ban=0 policy_soft_exit=0 policy_launch_storage=3
policy_diag=1`; `idx_admin_tool=1 idx_stub=0 idx_botfather=0`; `css_logo_hidden=1 css_float_slot=0`;
`appjs_admin_build=4 appjs_stub_mirror=0 appjs_scheme=0`.

### БД (Фаза H, read-only)
`nonterminal_count=0`; последние раны: `…13:00 DONE/published`, `…07:00 DEGRADED/published`,
`…01:00 DEGRADED/published` (профиль деградации предсуществующий, публикации есть). Патологий нет.

### Пост-деплой (агентские проверки, вне серверного коннекта)
- `healthz` из интернета: 200 `{"status":"ok","version":"2.58.84"}`; `/web/` 200 (14×2.58.84, 0×2.58.83, §8-вход есть,
  заглушек нет); policy по публичному URL — без ban/soft-exit, diagnostics+launchParams на месте.
- Headless Playwright (390×844, без initData): страница открывается (`AdminBot — Админка`, `.app-shell.shell-mobile`),
  `window.__FullscreenPolicy` работает (`state()/explain()/diagnostics()`), кнопка ⛶ **не показывается** (нет `me` —
  не вводит в заблуждение), §8-панель закрыта (off by default), заглушек/BotFather/«недоступен» в DOM нет,
  ошибок приложения в консоли нет (1 favicon-404 + SDK-варнинги 6.0 — предсуществующий шум).
  Артефакты: `postdeploy_headless_probe.txt`, `postdeploy_headless_390.png`.
- `deployed_commit` для ре-анкора: **`0b7a0aca416a418e099e157eca77d0a3137b3405`** (релиз-линия).
  Мапа soul-1 — legacy (`openworkflow-coverage-v1`, без `strict_evidence`), `deployed_commit` не менял
  (ре-анкор — за parent/PM).

## Девиации (честно)

1. **`tools/ui_soul1_w7_fullscreen_explain_e2e.py` не портирован** (не входил в список обязательных файлов релиза;
   dev-API-покрытие достигнуто JS-тестом (разделы 4.1–4.6, `FS-POLICY-OK`) и S12/S13 браузерной матрицей;
   имя файла привязано к W7-линку и в релиз-дереве нежелательно). Влияние: ноль на прод-поведение; инструмент
   остаётся на master-линии.
2. Node-сторожа на релиз-дереве — **83/84** (а не 86/86 как на master-линии): 84 = все `tests/js/*.js`
   prod-линии; разница с master — счёт самих файлов линка; единственный RED предсуществующий (§Тесты).
3. pytest regression-«674-класс» заменён расширенным summary-family (1442 passed, те же 62 сьюта семейства) +
   source-пинами (1866/1) — по духу конвенции 25882/25883, объём больше; все цифры verbatim.
4. Побочный эффект прогона shell-e2e в worktree: пересозданные артефакты `w2-evidence-shell/**` восстановлены
   (`git checkout --`), релиз-ветка чистая; копии свежих артефактов — в `evidence/release-fs-25884/shell-e2e/`.
5. На сервере 13–15 untracked-файлов (пост-инцидентные логи/патчи предыдущих лин); конфликтов с целевым деревом
   нет (`CONFLICTS=0`), ничего не перемещалось (TAR_SKIP).

## Rollback (готовность; не потребовался)

```bash
ssh nik@198.46.175.136
cd /var/www/admin_bot
git checkout release/incident-2.58.83        # 448cc81a = 2.58.83 (задеплоенный предшественник)
sudo systemctl restart admin_bot
curl -s http://127.0.0.1:8000/healthz        # ожидаем {"status":"ok","version":"2.58.83"}
```
Резерв: `git checkout --detach 448cc81a9eab590ea6de599f478220dd00abd3d1`. DDL-откат не нужен (DDL=0).

## SSH-коннекты (дисциплина AGENTS.md)

**2 логина**, оба одиночные, успешные: (1) recon ~15 c, закрыт (18:44:30 UTC); (2) основной прогон с фазами
A→B→C→D1→G1→D2→G2→E→F→H (18:44:5x–18:47 UTC). Ретраев нет; пароли не печатались (скрабятся в раннере).
Fail2ban-паттерн соблюдён: один recon + один основной коннект.

## Evidence

`plans/features/soul-1/evidence/release-fs-25884/`: `branch-log.txt`, `ancestry.txt`, `delta-files-with-stats.txt`,
`isolation-classification.txt`, `soul1-diff-empty.txt` (0 байт) + `soul1-diff-empty-len.txt`, `soul1-absent.txt`,
`soul1-markers-release-tree.txt`, `hashes.txt`, `bump_run.txt`, `node-guards.txt`, `e2e-w2-run.txt` + `e2e-w2/**`
(18 PNG + `_results.json`), `shell-e2e-run.txt` + `shell-e2e/**`, `pytest-fs-focused.txt`,
`pytest-summary-family.txt`, `pytest-source-pins.txt`, `pytest-24py-pins.txt`, `gen-registry-check.txt`,
`ev_recon.txt`, `ev_deploy_run.txt`, `postdeploy_headless_probe.txt`, `postdeploy_headless_390.png`.
Скрипты: `OPENCODE_WORKFLOW_SCRATCH/release25884/` (`bump_25884.py`, `deploy_25884.py`, `gen_evidence.py`,
`filter_index_diff.py`, `bump_run.txt`). Worktree: `OPENCODE_WORKFLOW_SCRATCH/fs-release-25884`.
Серверные логи: `/tmp/deploy25884_boot1.log` (стоп 2.58.83), `/tmp/deploy25884_boot2.log` (стоп 2.58.84),
`/tmp/deploy25884_since.txt` (окно с 2.58.83), `/tmp/deploy25884_backup/` (untracked-конфликты, 0 шт.).
Пины ветки: `release/fs-2.58.84` → origin (pushed); локально — `0b7a0aca`.
