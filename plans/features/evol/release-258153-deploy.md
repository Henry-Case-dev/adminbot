# REL-258153 — деплой 2.58.153 на production (новый VPS)

Дата: 03.11.2026, 10:30–10:38 UTC. Сервер: `192.255.209.205`, каталог `/var/www/admin_bot`, unit `admin_bot`.
Итог: **VERIFIED** (откат не требуется).

## DEPLOY_SOURCE

- Кандидат: **`e52a06b2b8cdcb6c01c83bda46d7a406596f2088`**, ветка `release/2.58.153` (запушена, remote ref совпал с локальным).
- Версия: `2.58.153` (bump `09aaf121` → `e52a06b2`, 31 файл).
- База: развёрнутый `ab662a7529891c7f97f6c81d46e86b635b029dbb` (2.58.152), ветка `release/2.58.152`. Кандидат — прямой потомок базы.
- `MUTABLE_WORKTREE_REQUIRED: no` — деплой шёл с точного коммита на сервере; локальная рабочая копия не использовалась.
- Write scope деплоя: только серверный checkout `/var/www/admin_bot` (ветка `release/2.58.153`) + рестарт unit. Файлы релиза/версии на сервере не менялись вручную.

## Привязка к одобренному кандидату (проверено независимо)

| Проверка | Результат |
|---|---|
| Дерево pre-bump `09aaf121` vs одобренный `01cc9693` | `ecf58c1479cdcdf77bc74d79b91475352b4db7ef` = **YES** |
| `git diff ab662a75 e52a06b2 -- services handlers web/api/routes.py` | пусто (EXIT 0) |
| Дельта вне тестов | `README.md`, `config/settings.py`, `web/api/initiative_publications.py` (A), `web/app.js`, `web/app.py`, `web/index.html`, `web/static/app.css` — ничего лишнего («other» = 0) |
| `web/api/initiative_publications.py` | только чтение: 4 × SELECT, 0 × INSERT/UPDATE/DELETE/DDL; RBAC как у `GET /api/initiative/meme-settings` (`get_tma_user` → `_chat_id_or_none` → `_require_chat_access`) |
| `ROUTES_SHA256_F11` | `cfd1a41c489665f8fc8dce6d74bc6d64b8eaac4d848b7c882dd7c7d06a470b4f` — совпал в обоих пинах тестов, для `ab662a75` и `e52a06b2` (216 929 байт, байт-в-байт) |
| Коммит-дерево кандидата | `24de8c0a7f9e20e2a7b54bd3f5c1fcc128ec169f` |

## Содержимое runtime-дерева на сервере (content-addressed)

Digest = sha256 по строкам `<blob-sha> <path>` из `git ls-tree -r` (LC_ALL=C sort), независимо посчитан локально от кандидата.

| Каталог | файлов | digest | git-tree | статус |
|---|---|---|---|---|
| `web` | 51 | `f6476b61cfee0132…` | `5c948296c9a4…` | MATCH |
| `services` | 265 | `ea920c974da3c52e…` | `213364e07ec2…` | MATCH |
| `handlers` | 28 | `8d01b0f992274e3c…` | `584ac33f3751…` | MATCH |
| `config` | 3 | `554e21e95d5bac0e…` | `92c5d5cb468d…` | MATCH |

Плюс `git status` (tracked) = 0 изменённых файлов, единственный untracked — известный `.cache/`.

## Преддеплойный снапшот БД

- `/root/deploy-258153/local_database_pre_258153.db` (вне репозитория), 1 679 773 696 байт.
- Сделан через sqlite backup API при работающем приложении.
- `PRAGMA quick_check = ok`, `user_version = 41`.

## Рестарт и состояние после выката

- Один `systemctl restart admin_bot`, 10:34:26 UTC → `ExecMainStartTimestamp = 10:34:32 UTC`, **MainPID 1618119**, **NRestarts 0**, ровно **1** процесс.
- `/healthz` loopback: **200** `{"status":"ok","version":"2.58.153"}`; публично `https://admin-bot.duckdns.org/healthz`: **200**, `2.58.153`.
- `user_version` 41 → 41 (DDL не было, миграций нет), книга миграций не менялась.
- Медиа: 66 файлов до и после.
- Память процесса ~424 МБ.

## Журнал

- После старта (≥10:34): `Traceback` 0, `CRITICAL` 0, `publication_stale` 0, `[ini-pub]` ошибок 0.
- Единственная строка уровня ERROR — `services.prompt_release_policy … activation_drift | block=initiative.meme.joke … активации нет, рестарт остаётся no-op`. Код `services/` в релизе не менялся; поведение объяснено ниже (находка 1).
- В окне предыдущего билда (08:47:44–10:34:26, до выката) — 3 Traceback: Wikipedia 403 (внешний robot policy), 2 × `sqlite3.OperationalError: database is locked` в `meme_initiative.record_attempt`, `VisionError: timeout` (openrouter). После рестарта повторов нет (нагрузки на этих путях ещё не было).

## Smoke (без записи в чаты, только чтение)

Ассеты (отданы сервером):

| Файл | код | маркеры |
|---|---|---|
| `/web/index.html` | 200, 1 214 794 б | `?v=2.58.153`, `data-workspace-tabs`, `data-initiative-publications`, `data-initiative-diagnostics`, `data-ini-pub-rows`, `data-ini-pub-filters` — все найдены |
| `/web/app.js` | 200, 1 812 567 б | `mod_initiative: ['overview','text','memes','publications','diagnostics']`, `publications: 'Публикации'`, `diagnostics: 'Диагностика'`, `/api/initiative/publications(/detail)`, `loadInitiativePublications` — все найдены |

API (initData собран на сервере штатным HMAC, админ-контекст, GET-only):

| Запрос | Ожидание | Факт |
|---|---|---|
| `GET /api/initiative/publications` без initData | 401 | 401 `missing init data` |
| то же + `X-Chat-Id`, без initData | 401 | 401 |
| с initData, без `X-Chat-Id` | 422 | 422 `нужен X-Chat-Id` |
| `GET …/publications/detail` без initData | 401 | 401 |
| `…/detail` с initData, без `X-Chat-Id` | 422 | 422 |
| `…/publications?days=90` (ЛС админа) | 200 | 200, честное пусто: `total=0`, `notes=[]` |
| `…/publications?days=90` chat `-1002661910336` | 200 с данными | 200: `total=721` (text 181, meme 540), `published=82`, `not_delivered=634`, `deferred=5`, страница 40 строк |
| `…/publications?days=90` chat `-1004482340693` | 200 с данными | 200: `total=667` (text 110, meme 557), `published=78`, `deferred=0`, страница 40 строк |
| фильтры `kind=text/meme`, `outcome=published`, `limit/offset`, `days=90` | 200 | все 200 |
| `…/publications/detail?attempt_id=<row0>` | 200 | 200, `available=True` |
| `GET /api/initiative/meme-settings` (ЛС админа) | P0.5 auto | `mode='auto'`, `known=false`, `joke_budget=null` |
| `GET /api/initiative/meme-settings` (группы) | действующий потолок | `mode='fixed'`, `known=true`, `joke_budget=368` / `771` |
| `GET /api/initiative/mechanism-diagnostics`, `/api/status` | без регресса | 200 (3 135 б / 20 624 б) |

Ни одного сообщения в живые чаты не отправлялось; мем не форсировался.

## Находки (не блокируют выкат, вне зоны релиза)

1. **`activation_drift` в лог на уровне ERROR (низкая/средняя, наблюдаемость).** Единственное вхождение за 7 дней — на этом старте, для блока `initiative.meme.joke` (чат `-1004482340693`). Код `services/prompt_release_policy.py` в релизе не менялся (диф `services/` пуст). Механика: в предыдущем старте (08:52) прошёл `legacy_cutover/legacy_snapshot applied`; при следующем старте журнальная метка не новее применённой → пишется дрейф, активации нет (`no-op`, источник истины — значение PG). Функционального эффекта не наблюдалось; предложение — понизить уровень до WARNING/INFO либо не логировать no-op как ERROR. Для Builder/Reviewer как отдельный пункт.
2. **`sqlite3.OperationalError: database is locked` в `meme_initiative.record_attempt` (до релиза, средняя).** 2 случая 08:52:53/58 UTC на 2.58.152: часть строк журнала попыток может теряться при конкуренции за SQLite — это тот самый журнал, который читает новая витрина. Код не менялся этим релизом; после рестарта повторов нет. В бэклог (устойчивость записи журнала).
3. **Мелочь UX (низкая).** `detail` для строк без `job_id` (`attempt_id = meme:row:<id>`) отдаёт 200 с пустой цепочкой и `notes=[]` — трасса по такой попытке пустая, хотя строка в списке есть. Данные не повреждены, ошибки нет; на усмотрение Reviewer/Builder.

## Откат

```
cd /var/www/admin_bot && git switch release/2.58.152 && systemctl restart admin_bot
```

Цель отката: `ab662a75` (2.58.152, последняя проверенная версия), снапшот БД `/root/deploy-258153/local_database_pre_258153.db` (не требовался: DDL и записи в БД не было).

## Доказательства

- Логи прогонов: `<GLOBAL_CONFIG>/WorkspaceData/runs/c742e4de9e92c489/release-258153-1d2280204d47/temp-a673767138/` (`deploy_run.log`, `verify_run.log`, `journal_run.log`, `anomaly_run.log`, `positive_run.log`).
- Скрипты проверки (read-only, воспроизводимы): там же `verify_candidate.py`, `local_digest3.py`, `deploy_258153.sh`, `verify_258153.sh`, `positive_258153.sh`.
