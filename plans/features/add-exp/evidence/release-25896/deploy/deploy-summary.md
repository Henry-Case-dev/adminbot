# DEPLOY-25896 — evidence: выкат 2.58.96 (ADD-EXP)

Релиз: **2.58.96** — состав поезда: **ADD-EXP** (режимы экспрессии
off/occasional/frequent, врезанные в живую генерацию: per-control effective,
allowed→occasional, diag-классы, few-shot register-сиды + approve, UI
live-check; ревью `981e9902` Needs Fixes → RECHECK `d0afd2cc` Approved,
BLOCK-1 закрыт) + bump 2.58.96. §4-приёмка (живые ответы: 20–30 проб,
Direct/Initiative/жанры, per-chat, preview vs production trace) — отдельный
лейн; здесь только выкат.

- Утверждённый кандидат: `95d11472b9e533b554554918e3efa6b42125260b`
  (= `origin/master` tip на момент выката; review-коммит `95d11472`; pkg
  `3ff9b319`; bump `14535c59`; fix `f06f376f`; runtime-дельта к базе 2.58.95
  (`113f3a62`) = ровно 10 whitelist-файлов).
- Прод ДО: `113f3a629cab54f7fcc261349a7c9af3b90f56d7` (2.58.95, healthz
  2.58.95) → ПОСЛЕ: **`95d11472` (2.58.96)**.
- **Server-reported HEAD после выката = `95d11472…`** — совпадает с
  кандидатом (три независимых среза: C-checkout, J-стадия, HTTPS-проба).
- DEPLOY_SOURCE: `origin/master` (иммутабельный коммит; fetch
  `113f3a62..95d11472`, B3-ancestor пройден). Mutable worktree **не требуется**;
  прод-репо: `git checkout -B master origin/master` + `/tmp`-логи; репо-файлы
  DevOps-машины — только scratch + этот evidence-каталог.
- T0 (рестарт, UTC): **2026-10-19 14:51:18**; MainPID 3716545 → **3739015**
  (NRestarts=0, active/running, ExecMainStartTimestamp 14:51:31Z,
  ExecMainStatus=0). PID до выката (3716545) — процесс 2.58.95 от
  13:07:57Z (цепочка 25895 → 25896 непрерывна).
- Инструменты (scratch `release-25896`): `deploy_25896.py` sha256_12
  **`b8179a3cdb3f`** (T0-hardened клон; apre-фикс + `_rb` detach-fallback;
  использован **как есть**); `rel96_final.sh` sha256_12 **`26548559ad7b`**
  (read-only; использован как есть, загружен в `/tmp/rel96_final.sh`).
  Offline-чек скриптов до выката: EXIT 0 (см. scratch
  `logs/deploy-offline-check-final.txt`, маркеры selfcheck 41/41).

## Режимы и rc

| режим | rc | результат |
|---|---|---|
| recon (read-only) | 0 | SSH ok; прод 2.58.95 @ `113f3a62` (master); healthz 2.58.95; server UTC 14:49:20Z |
| main | 0 | checkout `95d11472`; дельта 10/10 == whitelist; артефакты 14/14; restart; healthz 2.58.96; журнал чист; J-стадия OK; WARNINGS=0; без abort/rollback |

## Ключевые проверки (main, 14:51–14:52Z)

- healthz loopback **и** HTTPS = `2.58.96`; HTTPS-маршруты `/healthz` 200,
  `/web/` 200, `/static/app.css` 200.
- Изоляция дельты: `DELTA_RUNTIME` **10/10** == whitelist (set-eq):
  `config/settings.py`, `services/mca_expression.py` (новый),
  `services/mca_gates.py`, `services/prompt_composer.py`,
  `services/mca_sample_library.py`, `services/direct_chat_service.py`,
  `services/mca_authorial_speech.py`, `web/api/speech.py`, `web/app.js`,
  `web/index.html`; `TRACKED_MOD_AFTER`=0; `DELTA_TOTAL`=106 (остальное —
  /plans + tests/evidence, не runtime).
- `EXPECT12`-хэши **14/14** (вкл. новый `services/mca_expression.py`
  `2b0d09888243`, `services/mca_gates.py` `1f6c28841d8a`,
  `services/prompt_composer.py` `721773eada65`,
  `services/mca_sample_library.py` `a7f81b4f62c0`,
  `services/direct_chat_service.py` `0faaa6034f71`,
  `services/mca_authorial_speech.py` `55e8fd72ccff`,
  `web/api/speech.py` `85741bcacdbf`, `web/app.js` `1d68fede513e`,
  `web/index.html` `b80dad12a482`, `config/settings.py` `1f39e0269056`,
  README `9af3db32f047`, F8-meta `5e804bb16316`, sanity
  fullscreen-policy.js `96db06425079` / telegram_send.py `e23bced2fdb8`);
  `APP_VER=2.58.96`; F8-meta HEAD `f1463f10`.
- Маркеры ADD-EXP 16/16 (deployed bytes): EXP_MODULE=1,
  EXP_RESOLVE_EFFECTIVE=1, EXP_EXAMPLES_REFS=2, EXP_LAYER=1,
  EXP_COMPOSER_SETTINGS=6, EXP_RESOLVE_SETTINGS=1, EXP_GATE_FLAG=2,
  EXP_STARTERS=2, EXP_RESOLVE_EX=1, EXP_SEED_FN=1, EXP_AUTHORIAL_POLICY=1,
  EXP_SEED_API=2, EXP_LIVECHECK=2, EXP_DCS_LINES=45, EXP_UI_JS_LINES=31,
  EXP_UI_HTML_LINES=23.
- Регрессионные маркеры: DL-FIX 8/8, CFG-02C 13/13, 2.58.92 (TRFIX 7/7 +
  VFIX 6/6), волна 2.58.91 16/16 — все на месте. Spot-маркеры поезда 2.58.95:
  CFG03_HONEST_DESC=5, CFG03_TSV_ROWS=580, PGD_NORMALIZE_MODULE=1,
  VA_ADAPT_EVENT=1. Сравнение с `final-verification.txt` 2.58.95: 95 общих
  маркеров, отличия только ожидаемые (HEAD, версия, PID, `SERVED_APP_JS`;
  ERR 2→0 и ERR_402 1→0 — в этом окне чище); полные наборы PGD_*/VA_*
  из 95-скрипта в 96-скрипт не входят (spot-политика), но их файлы
  не в whitelist-дельте → байт-идентичны 2.58.95 (следствие set-eq дельты).
- Served: `SERVED_EQ_APP_JS=SAME` (`1d68fede513e`), `SERVED_EQ_APP_CSS=SAME`
  (`6d3ae1112d50`), `SERVED_INDEX_HTML`=`c00e345f40db`, `PAGE_VER`=**15**,
  `SUBST_CSS`=**2**, `SCOPE_LABEL_SERVED`=1.
- Дрифт=0: `PROD_RUNTIME_DRIFT`=0 (до), `TRACKED_MOD`=0 (до и после),
  HEAD == origin/master == кандидат (на момент выката).
- Миграции: `pending=[]`; sqlite `user_version` **36→36 (ΔDDL=0)**;
  `migrations: complete`.
- Воркеры: SKIPS=**0** («maximum number of running instances»),
  CLAIM_SLOW=0, MAINT_TIMEOUT=0, VISION_TICK=1, RUNTIMEWARN=0,
  VISION_PROBE_FAIL=0, GRACEFUL=2, POLLER=1.
- Журнал since T0: ERR/CRITICAL/Traceback=**0**, 402=**0** (грep-проверка),
  `[local-bot-api] файлы:`=1, warn=0; построчный разбор не требуется.

## Откат

- Abort до рестарта: `_tree_restore` → `release/fix-2.58.95` (`113f3a62`;
  ветки в прод-репо может не быть → fallback detach `113f3a62`). Не
  потребовался.
- Abort после рестарта: `_rb` → `release/fix-2.58.94` (2.58.94; fallback
  detach `9072347b` — объект в прод-репо есть: HEAD до выката 2.58.95).
  Не потребовался.
- Обе ветки на origin (ls-remote 19.10, до выката): `release/fix-2.58.95` =
  `113f3a62`, `release/fix-2.58.94` = `9072347b`. Киль-свитч ADD-EXP:
  `EXPRESSION_EXAMPLES_ENABLED=0` (env-only, default ON).

## Девиации (честно)

1. API-пробы `/api/vision/state`, `/api/workers/budget` без TMA-заголовка
   вернули `{"detail":"missing init data"}` — ожидаемая auth-заглушка
   (как в 2.58.95).
2. Live-маркеры ADD-EXP (`expression_diag`, `direct: expression resolve
   failed`) и vision-adapt/postgen в окне выката = 0 — появятся при первой
   живой генерации / тяжёлом кадре; §4-скоуп.
3. `UNTRACKED=13` на проде — pre-existing (как в 2.58.95).
4. `EXPRESSION_EXAMPLES_ENABLED` отсутствует в `.env` — env-only
   kill-switch, default **ON** (`services/mca_gates.py:2433`,
   `_env_flag(..., True)`); few-shot черновики всё равно требуют
   owner-approve (`owner_approved=0` — дизайн BLOCK-1).
5. `mca_media_analyses`: failed=32 / ready=19 / running=1 — состояние
   данных, pre-existing (running=1 наблюдался и в 2.58.95).
6. Release-гейт read-only (`gate-release-readonly.txt`): exit 1 — карта
   ещё не ре-биндится этим лейном (`candidate_commit`=4a09e29a…,
   `deployed_commit` пуст), 5 строк READY_FOR_LIVE. Закрытие RFL +
   ре-биндинг карты — §4/родительская линия. Карта этим лейном
   **не редактировалась**.
7. SSH-коннекты лейна: **2** (recon + main), пауза ≥90 с между ними,
   один логин `nik`, без ретрай-спама; fail2ban не задет.

## Остаток

- §4-приёмка (живые ответы: набор 20–30 проб, Direct/Initiative/жанры,
  per-chat override/GLOBAL, переключение без рестарта, reread после
  сохранения, preview vs production trace, реальный complete LLM payload)
  — отдельный лейн.
- Ре-биндинг карты (`candidate_commit`/`deployed_commit` := `95d11472`) и
  закрытие 5 RFL production-typed evidence — §4/родительская линия.

## Файлы (sha256_12)

- `deploy-run.txt` **`368129cbcb01`** (scrub применён скриптом);
- `final-verification.txt` **`d4cd807be10e`** (J-стадия, read-only);
- `recon96.txt` **`e0435b8b91c6`**;
- `gate-release-readonly.txt` **`4ec588f967c5`** (exit 1, read-only);
- `deploy-summary.md` (этот файл).
- Времена: recon 14:49:16–14:49:20Z; main 14:51:04Z–~14:52:05Z (J NOW
  14:52:01Z); внешние HTTPS-пробы DevOps-машины ≈14:53Z и 14:57:38Z
  → `2.58.96`.
