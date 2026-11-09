# REL-258156 — выкат 2.58.156 (визуальный релиз когнитивной карты)

Дата: 04.11.2026, 18:05–18:09 UTC. Сервер `192.255.209.205`, каталог `/var/www/admin_bot`, unit `admin_bot`.
Результат выката: **VERIFIED** (прод на точном кандидате, постпроверки пройдены, откат не нужен).
Статус release-гейта: **не закрыт** — блокирует только bookkeeping карты требований (см. §7), не прод.

## 1. DEPLOY_SOURCE

- Артефакт: **`30fac6ce503714e0100fbac2f5b020bfa1c3ca71`**, ветка `release/2.58.156` (в origin, побайтно совпадает с локальным объектом).
- Предыдущий прод: `f4a44167fa42fc0f23d681a76554246754172830` (2.58.155) — **точка отката**.
- `MUTABLE_WORKTREE_REQUIRED: no` — выкат из immutable-коммита; локальное рабочее дерево не использовалось.
- Write scope прода: checkout `/var/www/admin_bot` (ветка `release/2.58.156`) + один рестарт unit; следы `/root/deploy-258156/`.
- Дельта `f4a44167 → 30fac6ce` вне `plans/`: только `web/app.js`, `web/index.html`, `web/static/app.css`, `web/static/cog-visual.js`, `web/static/cognitive-map.js`, `config/settings.py` (только строка `APP_VERSION`), тесты и tools. `services/` — **пусто**, миграций/DDL нет.

## 2. Проверки до выката (18:05:55 UTC)

- `PRE_HEAD=f4a44167`, ветка `release/2.58.155`, tracked-dirty **0**, untracked только `.cache/` (гейт по грязи пройден, `DIRT_GATED=0`).
- `/healthz` локально 200 `2.58.155`; публично 200 `2.58.155`; `NRestarts` 0; MainPID 1867207; медиа 66.

## 3. Выкат

- `git fetch --prune origin` → новая ветка `origin/release/2.58.156`; `git cat-file -e 30fac6ce^{commit}` OK.
- `git checkout -B release/2.58.156 30fac6ce` → `HEAD=30fac6ce…`, `APP_VERSION = "2.58.156"`, дерево чистое (`TREE_DIRTY=0`).
- Один рестарт в 18:05:57 UTC. `reset --hard`, `clean -fd`, `checkout -f` не применялись.

## 4. Health и процесс

| Проверка | Значение |
| --- | --- |
| `/healthz` loopback | 200 `{"status":"ok","version":"2.58.156"}` (18:06:08 UTC, 3-я попытка поллинга) |
| `/healthz` SNI на loopback | 200, `2.58.156` |
| `/healthz` публично | 200, `2.58.156` |
| `ActiveState` / `SubState` | active / running |
| `NRestarts` / MainPID | **0** / **2005585** (`ExecMainStartTimestamp 18:06:03 UTC`) |
| Процессов в cgroup | **1** (подтверждено повторно в 18:09:11 UTC, тот же PID, uptime 188 с) |
| `PRAGMA user_version` | **41** (без изменений), `integrity_check` = ok |
| Медиа | **66** файлов (как до выката) |

## 5. Отдаваемые ассеты (диск и HTTP)

| Файл | Ожидаемо | Диск | HTTP |
| --- | --- | --- | --- |
| `web/app.js` | `49523d3c…f746797` | `49523d3c…f746797` | `49523d3c…f746797` |
| `web/static/app.css` | `e08eeee9…a198f7b6` | `e08eeee9…a198f7b6` | `e08eeee9…a198f7b6` |
| `web/static/cog-visual.js` | присутствует | `1076d633fb6d124cf24829ab530996e976dbc1a7b3604cb731b3e1e75404557f` | тот же (200) |
| `web/static/cognitive-map.js` | — | `e47ad249071c36634ef17d4aae69e67c66ff1b1e41b4a28fe96e4a691c0a4eed` | — |

- Коды: `/web/app.js` 200, `/static/app.css?v=2.58.156` 200, `/web/static/cog-visual.js` 200.
- `index.html` (1231349 байт): `?v=2.58.156` — **17** вхождений, `?v=2.58.155` — **0**.
- Порядок подключения: `cognitive-map.js` (стр. 16433) → `cog-visual.js` (16439) → `/web/app.js` (16444).

## 6. Журнал

- С 18:05:57 UTC: 288 строк, `Traceback` **0**, `CRITICAL` **0**, `database is locked` **0**, `Unhandled` **0**, `Task exception` **0**.
- Один `ERROR` — запись самого сервиса: `services.mca_events - ERROR - mca_event=INCIDENT | event_name=INCIDENT | stage=takeover | reason_code=incident_opened | pipeline_type=vision.media` (18:07:06). Класс повторяющийся: **5** за 24 ч, **9** за 7 дней; бэкенд-код в дельте идентичен прошлому проду (`services/` пусто) → не следствие релиза. Наблюдение, не блокер.

## 7. Smoke и карта памяти (read-only, GET-only)

- `GET /api/memory/cognitive-map` без initData → **401** (гейт авторизации работает).
- С админским initData (сгенерирован на сервере, токен не покидал сервер) → **200**, 1447969 байт.
  `state=partial`, `scope=global`, `degraded.active=false`, `not_loaded=none`.
  Счётчики: `api_nodes=688 api_edges=2400`, `db_nodes=55888 db_edges=58061`, `truncated nodes=true edges=true`.
  Типы узлов: fact 150 (потолок класса), entity 205, belief 150, evolution_event 150, paradigm 33 → 688.
  `state=partial` — честное состояние при потолках (`caps`), не деградация.
- Публичная страница (Playwright, 1280×800 и 390×844): title `AdminBot — Админка`, Vue смонтирован, **0 ошибок консоли**, 0 упавших запросов, ровно **1** запрос к `cognitive-map`, все три скрипта с `?v=2.58.156`. Без Telegram-контекста показано честное «Миниапп открыт без Telegram-контекста — откройте админку через кнопку меню в боте».

## 8. Release-гейт (не закрыт — bookkeeping)

`requirements_gate.py check --stage release --candidate 30fac6ce --deployed-commit 30fac6ce --repo <worktree 30fac6ce>`:
`stage=release inventory=226 manual=27 scoped=183 errors=486`, exit 1.

Причины (не связаны с продом):

1. `source not present: plans/owner_inputs/2026-11-03-epic-cm-visual-01.md` — файл-источник есть в коммите `7fd65891` (ветки `cmv/*`), но **не входит** в линию `release/2.58.156` (карта внесена коммитом `343bf37d`, источник — нет). Из-за этого 485 ошибок «inventoried source item gone or edited» по всем 226 строкам.
2. `candidate_commit` и `deployed_commit` в карте — `null`; `deployed_commit` не проставлен после выката.
3. Статусы: **188 PENDING** (без evidence), **38 VERIFIED**; по слайсам VERIFIED только `CMV-A-INTEGRATION` (15) и `CMV-B-SCENE-PHYSICS` (23), слайсы `CMV-C/D/E` — PENDING.
4. `live_required=0`, `live_when=preprod` у всех 226 строк — обязательных постдеплой-live пунктов карта не содержит.

Это работа PM/Orchestrator (связать источник в ветке/карте, проставить candidate+deployed, добить PENDING по C/D/E). Прод-код и артефакты при этом корректны; `VERIFIED` из отсутствующего доказательства не выставлялся.

## 9. Откат (не потребовался)

`git checkout -B release/2.58.155 f4a44167fa42fc0f23d681a76554246754172830` + `systemctl restart admin_bot`.
DDL нет (`user_version` 41), `services/` в дельте пусто, статические ассеты возвращаются вместе с коммитом, промпты/данные не затрагивались.

## 10. Артефакты

- Сервер: `/root/deploy-258156/` — `journal_after_258156.log`, `journal_final_258156.log`, `probe_map.py`, `probe_map2.py`.
- Локально (scratch): `WorkspaceData/runs/c742e4de9e92c489/release-258156-6165e4aa53c4/temp-e49eae543b/` — `deploy_258156.py`, `post_258156.py`, `public_smoke.py`, `public_smoke_258156.json`, `public_desktop_1280x800.png`, `public_mobile_390x844.png`.
- Worktree кандидата для гейта: `WorkspaceData/worktrees/c742e4de9e92c489/release-258156-6165e4aa53c4-90f9b4d1` (detached `30fac6ce`, чистый, зарегистрирован).
