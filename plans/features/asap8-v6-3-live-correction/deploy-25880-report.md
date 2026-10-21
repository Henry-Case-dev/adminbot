# DEPLOY-25880 — релиз 2.58.80 (v6.3 UI-коррекция) на прод: отчёт

Дата: 2026-10-16. Лейн: DEPLOY-25880 (release engineer). Владелец деплой одобрил.

## Deploy binding

| Поле | Значение |
| --- | --- |
| DEPLOY_SOURCE | локальный репо `C:\Code\Python\adminbot`, branch `master`, release commit `31c165556dbe8c289606bd6bee1af49bb72d5794` (`31c16555`); parent — reviewed кандидат `d9b7f389` |
| Push | `c2775a54..31c16555 master -> master`; `origin/master` = `31c16555` (сервер тянет из GitHub origin) |
| Server HEAD после pull | `31c165556dbe8c289606bd6bee1af49bb72d5794` (проверено в фазе B прогона) |
| Предыдущий прод (rollback target) | `c2775a54258512a3e20c97341d3e8a6738b1a33b` (`c2775a54`, 2.58.79) |
| MUTABLE_WORKTREE_REQUIRED | **no** — деплой из закоммиченного immutable commit; незакоммиченная работа соседних лейнов (SOUL-1: `services/prompt_migrations.py`, `services/prompt_registry.py`, `plans/features/soul-1/**`, `web/static/glass-teststand.*` → `tests/glass-teststand/` и др.) в релизный коммит и на сервер **не попала** |
| Записная зона (сервер) | `/var/www/admin_bot`; `git pull --ff-only` обновил только tracked-файлы, 13 предсуществующих untracked dirty-путей не тронуты (DIRTY_BEFORE=13 → DIRTY_AFTER=13) |
| DDL / миграции | **ΔDDL = 0**: в дельте `c2775a54..31c16555` нет `migrations/*`, `services/database.py`, `services/pg_db.py`, `services/mca_schema_registry.py`; prompt-миграции DML-only (подключены уже с ASAP-7) |
| Версии | 2.58.79 → **2.58.80** |

## Что в релизе (дельта с прода)

- `d9b7f389` (reviewed candidate, Approved): U07.2 — safe-area шапка
  (`web/static/app.css`: padding `max(env(safe-area-inset-*), --tg-content-safe-area-inset-*, --tg-safe-area-inset-*)`);
  каталог `+1`: `prompts.direct_l1_planner_system_prompt` (L1 Planner виден/редактируем в MiniApp,
  реестр round1025 572/547/25); честные пустые состояния (`web/app.js`, `web/index.html`).
- `4116c48a` (SOUL-1 W2, review-w2 Approved): prompt_composer — **все гейты OFF** (байт-паритет);
  `UNIFIED_COMPOSER_ENABLED` и другие флаги **не включались** (требование лейна соблюдено).
- Документационные коммиты (`50a7e689`, `225c3c2b`, `a854ad95`, `8c960df6`, `736a8834`, `4ca40730`, `00eb362b`) — без кода.
- `31c16555` (этот лейн): bump-коммит **31 файл**: `config/settings.py` + `README.md` + F8-meta
  (`plans/docs/param-registry-round1025.meta.md`: APP_VERSION 2.58.80, HEAD d9b7f389) + 24 py-пина
  + **re-pin 4 JS-харнесс-пинов `2.58.78 → 2.58.80`** (они были RED при 2.58.79; ре-пин — задокументированное
  лечение клаузы; после ре-пина `node hotfix7-10` = 4/4 OK).
- Стейджинг релизного коммита — хирургический (blob из HEAD + только версионная строка), поэтому
  конкурентные незакоммиченные правки соседних лейнов в двух пинах-файлах
  (`tests/test_tool_coordinator_round1026.py`, `tests/test_unified_image_request_round1026.py`)
  в коммит **не попали** (см. `git diff --cached` — только строки версии).

## Верификация (всё с сервера; локальный DNS домена не работает)

Полные команды и вывод — `evidence/deploy-25880/ev01-deploy-run.txt`, сводка — `ev03-verification-summary.md`.

- Сервис: `ActiveState=active SubState=running MainPID=2815638 NRestarts=0 ExecMainStatus=0`.
- `healthz` (loopback и **443** через caddy): `{"status":"ok","version":"2.58.80"}`.
- Главная `/web/`: `200`, `728255` байт; `2.58.80` ×14 (все `__APP_VERSION__` подставлены), `2.58.79` ×0.
- Отданный `/web/static/app.css`: sha256 = `70975eb2…87be2` — побайтово равен файлу релизного коммита
  (и отпечатку ревью); новая формула `max(env(safe-area-inset-…), --tg-content-safe-area-inset-…, --tg-safe-area-inset-…)`
  присутствует (3 вхождения, включая `header.header-sticky`, стр. 1017).
- Файлы сервера побайтово = релизному коммиту: `app.css / app.js / index.html / param_catalog.py / settings.py`
  (sha сошлись; `param_catalog.py` = пин `f8_baseline.json`).
- `/api/config` без TMA-initData → `401` (auth-контур жив, витрина секретов не отдаёт). «Видимость ключа
  L1 planner через реальный config API» подтверждена на прод-рантайме (интерпретатор сервиса) через тот же
  путь, что использует `/api/config`: `ConfigCache._synthetic_group_items()` → `synthetic_present=True,
  value_len=2423, group=prompts_direct_chat, per_chat=True`.
- Журнал после рестарта (224 строки): `ERROR=0 CRITICAL=0 Traceback=0 database-locked=0`.
- Отправок в чаты не было; всё взаимодействие — read-only HTTP/SSH.

## Отклонения и наблюдения

1. **SSH-коннекты: 3** (дисциплина AGENTS.md, без ретраев после неудачных auth, все логины успешные):
   (a) recon ~5.3 c; (b) абортированная попытка основного прогона ~6.5 c — **мой** скрипт сравнивал
   7-символьный `--short` HEAD сервера (`c2775a5`) с 8-символьным (`c2775a54`) и прервался на pre-state
   **до любых изменений**; (c) основной прогон ~115 c (фазы A–G). Возврат версии/кода во (b) не производился.
2. **requirements_gate `--stage release` → FAIL (exit 1)**: `candidate mismatch` (карта привязана к `c2775a54`)
   + позиции без evidence к кандидату. **Карта не редактировалась** (DO_NOT_TOUCH; «зеленить» запрещено) —
   финальный re-capture FINAL.3 на `31c16555` с привязкой этих evidence остаётся за parent/PM/Reviewer.
   Вывод гейта: `evidence/deploy-25880/ev02-gate-release-check.txt`.
3. В стартовом журнале ровно 1 INFO-строка упоминает `direct_l1_planner` (семантика `prompt_migrations`:
   «ключ отсутствует — сид сделает своё» / «уже новый канон» / «кастом юзера — НЕ трогаем»); агрегированный
   счётчик, не ERROR. Сырой boot-лог оставлен на сервере: `/tmp/deploy25880_boot.log` (224 строки).
4. F8-meta: `HEAD (short)` зафиксирован как `d9b7f389` — родитель релизного коммита (та же конвенция, что
   у c2775a54 → d5794ddd). После коммита это ожидаемо «отстаёт» от HEAD.
5. 4 JS-харнесс-пина изменены (тесты) — это часть документированного bump-флоу; поведенческих изменений нет.

## Rollback (не потребовался; готовность)

Показания к откату: `healthz` не `2.58.80` после рестарта; сервис не `active`; ERROR/CRITICAL/Traceback
при старте; регресс конфиг-витрины (L1 Planner пропал) или шапки (safe-area снова перекрыт).

```bash
ssh nik@198.46.175.136
cd /var/www/admin_bot
git diff > /tmp/pre_rollback_local.patch      # подстраховка для локальных (tracked) правок сервера
git reset --hard c2775a54258512a3e20c97341d3e8a6738b1a33b   # = c2775a54 (2.58.79), ancestor → сеть не нужна
sudo systemctl restart admin_bot
curl -s http://127.0.0.1:8000/healthz          # ожидаем {"status":"ok","version":"2.58.79"}
curl -s --resolve admin-bot.duckdns.org:443:127.0.0.1 https://admin-bot.duckdns.org/healthz
```

- Откат DDL не нужен (DDL=0); БД/SQLite-схема не менялась.
- Мягкие откаты для содержимого релиза: CSS/каталог — только cold revert (флагов нет);
  SOUL-1 composer и так OFF (не включать).
- `git reset --hard` затронет и локальные tracked-правки сервера (если появятся) — при необходимости
  сначала `/tmp/pre_rollback_local.patch`.

## Evidence

- `evidence/deploy-25880/ev01-deploy-run.txt` — транскрипт прогона A–G (санитизирован, 0 секретов).
- `evidence/deploy-25880/ev02-gate-release-check.txt` — release-гейт (read-only).
- `evidence/deploy-25880/ev03-verification-summary.md` — сводка хешей/проверок.
- Скрипты и сырые логи лейна: `OPENCODE_WORKFLOW_SCRATCH/deploy25880/`
  (`bump_25880.py`, `stage_release.py`, `deploy_25880.py`, `recon-1.log`, `deploy-run2.log`).
- На сервере (в /tmp): `deploy25880_probe.py`, `deploy25880_web.html`, `deploy25880_app.css`, `deploy25880_boot.log`.

## Итог

2.58.80 @ `31c16555` задеплоен и подтверждён live-проверками с сервера; rollback-ready.
Продуктовых находок при деплое нет. Coverage-гейт красный из-за несвязанной карты (не правилась) —
финальная приёмка (FINAL.3 re-capture на deployed SHA) остаётся за parent.
