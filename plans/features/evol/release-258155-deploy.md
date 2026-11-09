# REL-258155 — выкат 2.58.155 (пакет версионирования промптов) на production

Дата: 04.11.2026, 06:50–06:58 UTC. Сервер: `192.255.209.205`, каталог `/var/www/admin_bot`, unit `admin_bot`.
Результат: **VERIFIED** (обязательные постпроверки пройдены, откат не нужен).

## DEPLOY_SOURCE

- Артефакт: **`f4a44167fa42fc0f23d681a76554246754172830`**, ветка `release/2.58.155` (в origin).
- Предыдущий прод: `2de11dc0c3a836b44e047484a80ddb0425891ad0` (2.58.154) — точка отката.
- `MUTABLE_WORKTREE_REQUIRED: no` — выкат из immutable-коммита; локальное дерево проекта не использовалось.
- Write scope прода: checkout `/var/www/admin_bot` (ветка `release/2.58.155`) + рестарт unit; следы в `/root/deploy-258155/`.
- DDL/миграций в дельте нет (`prompt_migrations` — только журнальные токены записи), `user_version` не двигался.

## Проверки до выката (06:50:27 UTC)

- Прод `2de11dc0`, branch `release/2.58.154`; tracked-dirty 0; untracked — только `.cache/`.
- `healthz` 200 `2.58.154` (loopback + SNI), MainPID 1794505, `NRestarts` 0, `user_version` 41, медиа 66.
- Порядок: `git status --porcelain` → СТОП при грязи → `git fetch --prune origin` → `git cat-file -e <sha>^{commit}` →
  `git checkout -B release/2.58.155 <sha>` → `git rev-parse HEAD` → один рестарт.
  `reset --hard`, `clean -fd`, `checkout -f`, stash не применялись.

## Выкат

- `checkout -B` в 06:50:22, `HEAD` = `f4a44167…`, `APP_VERSION = "2.58.155"`, дерево чистое.
- `ExecMainStartTimestamp = 2026-11-04 06:50:43 UTC`, MainPID **1867207**, `NRestarts` **0**, процессов в cgroup 1.

## Health

| Проверка | Значение |
| --- | --- |
| `/healthz` loopback | 200 `{"status":"ok","version":"2.58.155"}` (06:50:47 первый после старта; 06:50:50 подтверждение) |
| `/healthz` SNI на loopback | 200, `2.58.155` |
| `/healthz` публично (`https://admin-bot.duckdns.org`) | 200, `2.58.155` |
| `NRestarts` / процессов | 0 / 1 (пере-проверено ~06:58, тот же MainPID) |
| `PRAGMA user_version` | 41 (без изменений) |
| Медиа | 66 файлов (как до выката) |

## Промпты владельца: байтовое сравнение

Заводские/глобальные значения сняты пробником **до** рестарта и повторно после — sha256 совпадают.

| Значение | До | После |
| --- | --- | --- |
| `prompts.meme_joke` (global) | `2f30ca1f9a6b…` 51 симв. | `2f30ca1f9a6b…` 51 симв. |
| `prompts.meme_image` (global) | `f81fe7e4b505…` 28 симв. | `f81fe7e4b505…` 28 симв. |
| `prompts.meme_summary` (global) | отсутствует | отсутствует |

Пер-чат оверрайды (`chat_profiles.chat_params->overrides`) после выката:

| Чат | Ключ | sha12 / символов |
| --- | --- | --- |
| `-1002661910336` | joke | `539ceb6970ea` / 1357 |
| `-1002661910336` | image | `11cf82f45c3a` / 566 |
| `-1004482340693` | joke | `4bc3425f2f3d` / 261 |
| `-1004482340693` | image | `11388ab3a936` / 372 |
| оба чата | summary | не задан |

Неизменность пер-чат текстов доказана тремя фактами, а не отсутствием проверки:

1. `chat_profiles.updated_at` = 04:47:01 (чат 1) и 03.11 11:51:16 (чат 2) — **до** рестарта; `set_chat_params` всегда двигает `updated_at`.
2. В `chat_lore_history` последняя запись по чату 1 — id 283, 04:47:01, `changed_by` = владелец; записей позже 06:50 нет.
3. Журнальная копия, снятая самим релизом на старте (06:50:45), побайтно равна текущему значению:
   `rev:f501a080291c` = `539ceb6970ea` / 1357 симв. (историческая метка `pre_versioning_import`).

**Отличие от отчёта 2.58.154** (`71303ff62029` / 1363 симв. для joke чата 1) объясняется правкой владельца
**04:47:01 UTC**, то есть до этого выката: прежние байты сохранены в журнале как `rev:99b88b0b89d7`
(`71303ff62029`, 1363 симв., `reason=drift_recovery`). Наш рестарт ничего не менял.

## Живое доказательство версионирования (GET-only, админский initData)

- `GET /api/prompts/catalog` → 200, `count=112`; `initiative.meme.joke` → `fac:2f30ca1f9a6b(meme-joke-evol014)`,
  `initiative.meme.image` → `fac:f81fe7e4b505(meme-image-evol014)` — совпадает с заводскими байтами выше.
- `GET /api/prompts/initiative.meme.joke/versions` (global) → 200, `entries` 4 (2 ревизии + 2 активации),
  `page.has_more=false`, `next_cursor` пуст, `journal_available=true`; журнал даёт ровно те же 2 + 2.
- Курсорная пагинация: `page_size=2` → **2 страницы, 4 записи, 0 дублей**, `next_cursor` ведёт вглубь,
  последняя страница без курсора. `total`/`page.size` не отдаются — по контракту §3.4 `total_known=null`.
- Реальные объёмы журнала: 171 ревизия / 102 блока / **максимум 10 ревизий в блоке**, 166 активаций.
  Блока с >50 ревизий в проде нет → кейс «листание за 50» **NOT OBSERVED** (искусственные ревизии не создавались).
- `GET /api/prompts/initiative.meme.joke/baseline` → 200, `source="factory"`, `baseline=null`,
  `cleared_at=null`, `journal_available=true`, `capabilities={assign:true, clear:false, restore_baseline:false, restore_factory:true}`.
  В `prompt_activations` событий `baseline%` — **0**, то есть миграция никому baseline не назначила.
- Ожидаемые строки журнала от выката: 06:50:45 `legacy_import` — `initiative.meme.joke` чат 1
  (`rev:f501a080291c`, `539ceb6970ea`, 1357) и `summary.cover.style_id` чат 1 (`rev:ac2c44f1bd1f`,
  `cdd0c0d252d0`, 12), `outcome=recorded`, `detail=pre_versioning_import`. Плюс два INFO:
  `pre_versioning capture | values=2` и `релиз применён | release=evol-016-cutover | blocks=110 | changed=0 | retired=0`
  — ни один текст не перезаписан.
- Чат-скоуп истории: 200, `scope=chat`, `entries` 8/6, `active_sha12` = `2f30ca1f9a6b` (заводская),
  `can_activate=true`. Живой пер-чат текст отличается от этого указателя — это документированное состояние
  дрейфа (контракт §3.2: источник истины — PG-значение, заводской текст сам не включается); данные не тронуты,
  строк `activation_drift` на этом старте нет (на 2.58.154 их было 4).

## Интерфейс

- Публично `/web/index.html` 200: 18 вхождений `prompt-version-card`, шаблон `#prompt-version-card-tpl`, `pv-grid`.
- Публично `/web/app.js` 200: компонент `prompt-version-card` (4 вхождения) + обработка `next_cursor`.
- `sha256sum` на сервере: `index.html 4c648efb…`, `app.js 22267af7…` — **побайтно равны** блобам коммита `f4a44167`.
- Браузер (Playwright, публичная страница): заголовок `AdminBot — Админка`, Vue-приложение смонтировано,
  **0 ошибок консоли**, шаблон карточки в DOM; без Telegram-контекста показывается честное «откройте через бота».

## Журнал (с 06:50:22–06:50:43 UTC)

210 строк: `Traceback` 0, `CRITICAL` 0, `ERROR` 0, `database is locked` 0, `activation_drift` 0,
ошибок про журнал промптов 0. `prompt_release` — 2 строки, обе INFO (см. выше). Дальше только плановые
задачи (`VisionMediaWorker._tick`) и запросы проверки.

## Наблюдения

1. Пер-чат `active` в истории показывает заводской указатель, а не живой оверрайд владельца — известный класс
   `activation_drift`, описанный контрактом §3.2; релиз теперь сохраняет живой текст ревизией, но активирующего
   события не пишет. Не блокер, кандидат в backlog (UI-подпись «дрейф» вместо «активна заводская»).
2. Кейс «>50 ревизий в блоке» на реальных данных недостижим (максимум 10) — не проверялся намеренно.

## Откат (не потребовался)

`git checkout -B release/2.58.154 2de11dc0c3a836b44e047484a80ddb0425891ad0` + `systemctl restart admin_bot`.
Только код: DDL нет, `user_version` 41, строки журнала нового кода при откате инертны, промпты владельца
не менялись.

## Следы на сервере

`/root/deploy-258155/` — `probe.py` (pre/post), `probe2.py`, `probe3.py`, `post155.json`, `journal_after.log`.
