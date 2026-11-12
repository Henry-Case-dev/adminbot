# Деплой 2.58.198 — SELF-DIAG-01 (финальный поезд после блокирующего преддеплоя)

**Итог: ВЫКАЧЕНО И ПРОВЕРЕНО на проде.** Прод `2.58.198`, коммит
`234776589c934024ed0e8dceba189fb9d70d3215` (ветка `release/2.58.198`),
кандидат `dae6ffeae07cbf2b8d533bb99eaeaf267de335a2`. Эпик **НЕ закрыт**:
карту и release-гейт закрывает PM; 41 строка `READY_FOR_LIVE` остаётся
пострелизным наблюдением.

## 1. Привязка

| Поле | Значение |
|---|---|
| База (прод до выкатки) | `2587616759de31283585ffc105c91e7193c2e89e` = 2.58.197, ветка `release/2.58.197` |
| Кандидат (Reviewer, controlled deployment) | код `dae6ffeae07cbf2b8d533bb99eaeaf267de335a2`, docs `1fd0ceb675c7a39206c0cfb39c9772be630f84cb`, база `34754c9c` (интеграция `454727ed` + F1–F3/hard_rules) |
| Ревью | `evidence/final/review-final-fixes-dae6ffea.md` — Approved for controlled deployment; F3 visual/hard_rules отложен на deployed 2.58.198 с точным wait; 11/1541; F8 644 |
| Deploy-гейт | `stage=deploy inventory=183 manual=53 scoped=189 errors=0` (воспроизведён локально: `gate-deploy-258198.txt`) |
| Релизная ветка | `release/2.58.198` → **`234776589c934024ed0e8dceba189fb9d70d3215`** (пересобрана от `25876167`, force-with-lease; старый tip `78982058` не выкатывался и помечен тегом `release-2.58.198-pre-fixes`) |
| Кумулятивно `25876167..23477658` | **156 файлов (98 M, 50 A, 0 D), +23190/−293** = финальный поезд (148 файлов, +23159/−262) + 30 пинов (+31/−31) |
| Проверка состава | ровно 30 файлов бампа (только пины версии, 62 строки); DDL/миграций 0; новых LLM/БД/агентов/планировщиков 0; продуктовые файлы те же, что в одобренном кандидате (новых файлов фиксы не добавили) |
| DEPLOY_SOURCE | `release/2.58.198` @ `23477658` (immutable) |
| MUTABLE_WORKTREE_REQUIRED | no |
| Откат | `25876167` (2.58.197), не потребовался |

## 2. Обязательный преддеплойный поезд на `23477658`

| Набор | Факт | Ожидание | Вердикт |
|---|---|---|---|
| D6 `test_checkup_contract` | 41 passed | 41 | ok |
| D6 broad 22 файла | 946 passed | 946 | ok |
| D6 16 файлов | 661 passed / 1 failed (`mca10b` 643/644) | 661 + тот же 1 | ok (pre-existing) |
| D2 5 файлов | 145 passed | 145 | ok |
| D2 6 файлов | 216 passed | 216 | ok |
| D2 `debug_config+log_ring` | 42 passed | 42 | ok |
| D2 9 файлов | 244 passed / 1 failed (`cfg03`) | 244 + тот же 1 | ok (pre-existing) |
| D4 `deploy_identity_d4c` | 22 passed | 22 | ok |
| D4 9 файлов | 366 passed | 366 | ok |
| D4 итого | 388 | 388 | ok |
| D5 `prompt_readback` | 62 passed | 62 | ok |
| D5 `self_diag_golden` | 38 passed | 38 | ok |
| D5 8 файлов | 355 passed | 355 | ok |
| D5 prompt-контракты | 56 passed, 1 skipped | 56+1s | ok |
| D3 `bundle+probes` | 80 passed | 80 | ok |
| D3 focused 35 файлов | 1325 passed | 1325 | ok |
| web/api 2 контракта | 190 passed | 190 | ok |
| **JS unit** | **46 passed** | 45 + новый hard_rules тест | ok (F1 закрыт) |
| **web-wide `tests/test_web*.py`** | **11 failed / 1541 passed** | 11/1541 | ok (те же 11, новых 0) |
| e2e `ui_inspector_exact` | `checks=142, failures=0` | 0 | ok |
| e2e `ui_meme_ui_fields` | `failures=0` | 0 | ok |
| e2e `ui_initiative_rework` | `failures=2` (1536, 390) | те же 2 | ok (pre-existing) |

Прежний блок F1–F3 закрыт: `test_webapp_js_unit` стал зелёным (46), в web-wide
ровно 11 давних падений (включая известный флейк `dm_ui`), новых RED нет.
Отчёт прошлой (заблокированной) попытки сохранён как `deploy-blocked-pre-fixes.md`.

## 3. Выкатка

- прод до выкатки: `25876167` / `release/2.58.197`, tracked 0, unit active,
  `NRestarts=0`, `/healthz` 2.58.197 (21:24:04Z);
- снапшот: `backups/predeploy-258198-final-20261112T212408Z.db` —
  2 671 144 960 б, sha256 `97a8646e1e2fac2489ae5938092eb2c03f869d52f596bece74281cd46d201105`,
  read-back `integrity=ok`, `user_version=47`, 130 таблиц, 80.1 с;
- `git fetch --prune origin` → `origin/release/2.58.198 = 23477658`; `git cat-file -e`
  OK; `merge-base --is-ancestor HEAD 23477658` → `FF_OK`;
- `git checkout -B release/2.58.198 23477658`; HEAD совпал, tracked 0, `APP_VERSION=2.58.198`;
- `systemctl restart admin_bot` в **2026-11-12T21:25:37Z**; unit active, `NRestarts=0`,
  `ActiveEnterTimestamp=21:25:39Z`; `/healthz` 2.58.198 с первой попытки;
- пост-проверка 21:25:56Z: HEAD `23477658`, branch `release/2.58.198`, tracked 0,
  `user_version=47`, журнал 15 мин: `Traceback=0 ERROR=0 CRITICAL=0 WARN=9 attempt LOST=0`
  (843 строки) — рост traceback/`attempt LOST` нулевой;
- **идентичность отданных файлов**: `/web/app.js` sha256
  `3cf2c9168c350f49977127a1e6bb19363734e27923efeeeae4bce9fa9895f594` (2 311 044 б)
  совпал с диском и git-blob; `/web/` = `web/index.html` с подстановкой
  `__APP_VERSION__ → 2.58.198` (различие только в 17 cache-bust подстановках,
  119 б); `/web/static/app.css` sha256 `f468bd01…`. Оба sha совпали с
  ассетами, объявленными в F3-доказательстве кандидата.

## 4. Эффективная конфигурация (до/после)

`settings-parity-2.58.198.json` (baseline 21:12:36Z на 2.58.197, после 21:33:18Z):

| Поверхность | Итог |
|---|---|
| `/api/prompts/catalog` | sha256 идентичен |
| `/api/prompts/{key}/versions` × 4 | sha256 идентичны |
| `/api/config/overrides-map` | идентичен |
| `meme-settings`, сохранённые блоки × 2 чата | sha256 идентичны (сырой payload меняется только в живых `analytics.attempts/*`) |
| `chat_params` (per-item `updated_at`) | latest `2026-11-11T12:33:23Z` — не менялся, 530 записей |
| `/api/config` (глобально и оба чата) | **+1 запись ровно**: `flags.self_diag_repo_origin` (группа `flags_service`, тип `str`, заводское `""`), changed=0, removed=0 |
| env-оси релиза | `SELF_DIAG_*` и `ADMINBOT_DEPLOYED_SHA` не заданы ни в unit, ни в `.env` → заводские значения (local snapshot off → провайдер github; identity не выдумывает `verified`) |

Сохранённые промпты, модели и настройки не перезаписаны.

## 5. Живые проверки на 2.58.198 (без сообщений в чаты)

- **Самодиагностика**: `GET /api/status/self-diagnosis` — 200 в обоих чатах,
  `runtime.app_version=2.58.198`, `checkout_sha=23477658…`, `dirty=false`,
  `repo_origin=Henry-Case-dev/adminbot`, `code_check` github/enabled; 26 источников
  честно `not_checked/declaration`; `secret_value_disclosures=null` с причиной
  `no_deliveries_in_window`; аналитика счётчиков (все 0) присутствует, включая
  `prompt_readback_requested/allowed/denied`.
- **TTL 30 с**: два подряд вызова — байт-идентичный payload.
- **RBAC**: аноним → 401 `missing init data`; не-админ (проверенный участник)
  → самодиагностика 200 **по политике** (категория `bot_server_state` = `PUBLIC_TECH`,
  дефолт `view_roles=[user, local_admin]`, видно в живой матрице), при этом
  защищённые поверхности закрыты: `/api/prompts/catalog` → 403, `…/{key}/versions`
  → 403, `/api/access/diagnostic_policy` → 403, `/api/speech/inspector` → 403.
- **Секреты**: скан 20 779 симв. payload на `authorization/x-api-key/password/secret/cookie/Bearer/sk-/ghp_` — 0 совпадений.
- **UI «Статус»** (оба чата): блок «Самодиагностика» отрендерен, версия 2.58.198,
  PID 318147, checkout `23477658…`, CPU/RAM/диск, 26 строк источников;
  `deployed_sha`/`branch` — «—» (нет `.deploy/release.json`, env не задан;
  `local_source_verification=local_unverified` — по контракту не выдумывается).
  Скриншоты `live-selfdiag-A/B-2.58.198.png`, данные `live-ui-2.58.198.json`,
  `live-ui-B-2.58.198.json`.
- **F3 visual/hard_rules на проде** (`live-f3-matrix-2.58.198.json`):
  - Playwright, 390×844 и 1536×960, реальные API прода: 9 категорий, 48 чекбоксов,
    **нативных 0**, размеры `18x18`, accent `rgb(139,111,232)`, hScroll 0,
    обрезанного текста 0, console/pageerror 0; состояния checked/unchecked/disabled
    присутствуют; клик по unchecked (`prompts/view/Участник`) включает контрол
    (checked=true, disabled=false, только локально, без сохранения);
    строка «Жёсткие правила: Текст промптов доступен только администратору этого чата
    по явному запросу; участникам он не выдаётся.» — без `[object Object]` и без
    внутреннего кода правила. `failures: []`. 10 PNG.
  - **Browser Use** (независимо, реальный Chrome, 1707×932): 9 категорий, 48
    чекбоксов, нативных 0, `18x18`, accent совпал, hScroll 0, `[object Object]` нет,
    текст правила тот же; скриншот `live-f3-browseruse-2.58.198.png`.
- **Golden set на выкаченной сборке** (только тесты): `test_self_diag_golden.py`
  + `test_prompt_readback.py` → **100 passed** (`golden-2.58.198.log`).
- **Явный чекап и `inspect_runtime`**: живого HTTP-пути нет (только Telegram-команда
  и LLM-инструмент в чате) — сообщения в чаты не отправлялись, строка остаётся
  пострелизным `READY_FOR_LIVE` наблюдением. `prompt_readback` allowed/denied
  аналогично требует живого tool-вызова; политика (матрица) и счётчики проверены
  живьём, поведение allowed/denied покрыто тестами (100 passed).

## 6. Откат

Не потребовался. Готовность (данные не откатываются, схема 47, DDL=0):

```
cd /var/www/admin_bot && git checkout -B release/2.58.197 25876167 && systemctl restart admin_bot
```

Страховка — снапшот §3. Старый tip `78982058` сохранён тегом
`release-2.58.198-pre-fixes` (не выкатывался).

## 7. Честные границы

- Реальный Telegram WebView/getChatMember в клиенте владельца не проверялся —
  проверки шли на реальном HTTP/UI прода с подписанным TMA initData владельца.
- Журнал проверен в окне 15 мин после рестарта (0 traceback/ERROR/LOST); отдельный
  второй SSH-коннект для более позднего окна не открывался (бюджет fail2ban).
- `deployed_sha`/`branch` пусты: нет deploy-манифеста и `ADMINBOT_DEPLOYED_SHA`
  (по контракту D4 это `local_unverified`, `verified` не подделывается).
- Живые чекап/inspect_runtime/prompt_readback-allowed/denied и 41 строка
  `READY_FOR_LIVE` — пострелизные наблюдения, не `VERIFIED`.
- **Эпик НЕ закрыт**; release-гейт и карту закрывает PM.

## 8. Артефакты

`deploy-run.log`, `train-258198-final.txt`, `gate-deploy-258198.txt`,
`settings-parity-2.58.198.json` (+ baseline `settings-parity-before-2.58.197.json`),
`live-checks-2.58.198.json`, `live-rbac-2.58.198.json`, `live-ui-2.58.198.json`,
`live-ui-B-2.58.198.json`, `live-f3-matrix-2.58.198.json`, PNG (`live-f3-matrix-*`,
`live-f3-browseruse-*`, `live-selfdiag-A/B-*`), `golden-2.58.198.log`,
`postdeploy-read.txt`, `harness/` (скрипты бампа/поезда/деплоя/parity/visual),
`deploy-blocked-pre-fixes.md` + прежние логи блокирующего прогона.
