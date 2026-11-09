# REL-258158 — выкат 2.58.158 (CMV: «Сбросить вид» больше не стирает фильтры)

Дата: 04.11.2026, 18:33–18:35 UTC. Сервер `192.255.209.205`, каталог `/var/www/admin_bot`, unit `admin_bot`.
Результат: **VERIFIED** — прод на точном проверенном кандидате, обязательные постпроверки пройдены, откат не потребовался.

## 1. DEPLOY_SOURCE

- Кандидат ревью: `652b69b9e0daa75073195aa037247cd4002cf346` (ветка `cmv/reset-view-fix`, база `6fd3dcf3` = 2.58.157).
- Артефакт релиза: **`40a622484bab8ff14feda232b928271fcf57f76c`**, ветка `release/2.58.158` (в origin; побайтно тот же объект).
  - `7080fda6` — cherry-pick `652b69b9` без конфликтов (только `web/app.js`, `web/index.html`, `tests/js/evol_cmv_d_fullscreen_test.js`, 90+/10−);
  - `40a62248` — bump 2.58.157 → 2.58.158 (31 файл / 33 вхождения: `APP_VERSION`, README-блок, 1 meta-файл каталога, 4 JS-пина, 24 Python-пина; 32+/32−).
- Предыдущий прод: `6fd3dcf391482836af6907bb4654291a97018076` (2.58.157) — **точка отката** (`release/2.58.157`).
- `MUTABLE_WORKTREE_REQUIRED: no` — выкат из immutable-коммита; локальный worktree кандидата не использовался прод-процессом.
- Write scope прода: checkout `/var/www/admin_bot` (ветка `release/2.58.158`) + один рестарт unit. `reset --hard` / `clean -fd` / `checkout -f` не применялись.
- Дельта `6fd3dcf3 → 40a62248`: `web/app.js`, `web/index.html`, тесты, `config/settings.py` (строка `APP_VERSION` + комментарий), README, пины. `services/` — пусто, DDL/миграций нет, промпты и каталог не меняются.

## 2. Проверки до выката (18:32 UTC)

- Фронт: `node tests/js/evol_cmv_d_fullscreen_test.js` → **`EVOL-CMV-D-OK checks=84`**.
- Backend: `py -3 -m pytest tests/test_evol_cog_map_widget.py tests/test_webapp_f11_round1025.py -q` → **73 passed**, 0 failed (9.95 c; известные «3 pin-падения» в этом прогоне не воспроизвелись).
- Прод до выката: `PRE_HEAD=6fd3dcf3`, ветка `release/2.58.157`, tracked-dirty **0**; `/healthz` публично 200 `2.58.157`; `NRestarts` 0.
- Serve-базис старого ассета: `GET /web/app.js` → 1976096 байт, sha256 `49523d3c89d61e669e006f29ff222dd79a64c8d0198a63e6ea95d7797f746797`.

## 3. Выкат (18:33:59 UTC)

- Fail2ban-бюджет: **1 recon-коннект + 1 основной прогон**, одиночный логин, без поллеров.
- `git fetch --prune origin release/2.58.158` → ветка в origin; `git cat-file -e 40a62248^{commit}` OK.
- `git checkout -B release/2.58.158 40a62248` → `HEAD=40a62248…`, tracked-dirty после checkout **0**.
- Один `systemctl restart admin_bot`.

## 4. Health и процесс

| Проверка | Значение |
| --- | --- |
| `/healthz` loopback | 200 `{"status":"ok","version":"2.58.158"}` |
| `/healthz` публично | 200 `2.58.158` |
| `ActiveState` / `SubState` | active / running |
| `NRestarts` | **0** (`ExecMainStartTimestamp 18:33:59 UTC`) |
| `Traceback` в журнале после рестарта | **0** |
| DDL | нет (`Δ DDL = 0`, миграции не запускались) |

## 5. Отдаваемые ассеты (локально = диск = HTTP)

| Файл | Локально (кандидат) | Диск сервера | HTTP |
| --- | --- | --- | --- |
| `web/app.js` | `932a94f9158593326b57d8f5eadfca818149df887875b26350b842c928d4a9e1` (1976574 б) | тот же | тот же (200, 1976574 б) |
| `web/index.html` | `c41268a624e6c650ef9e8aeff2d2d956bec10f67f2dcdd87989926b9a7da7870` | тот же | sha отличается **законно**: сервер подставляет `__APP_VERSION__` при рендере |

- Старый прод-ассет `49523d3c…f746797` (2.58.157) **заменён** на `932a94f9…b842c928`; отдаётся `graphResetFilters` в теле `app.js`.
- `index.html`: `?v=2.58.158` — **17** вхождений, `?v=2.58.157` — **0**; в разметке есть обе привязки: `graphResetView(` — 2, `graphResetFilters(` — 2 (обычный и полноэкранный режим).

## 6. Живой смоук

- Playwright, публичная страница: title `AdminBot — Админка`, Vue смонтирован (`#app`), версия `2.58.158` в разметке, **0 ошибок приложения в консоли**; единственная запись error — `404 /favicon.ico` (косметика, было и раньше).
- `#/memory` без Telegram-контекста честно показывает «Миниапп открыт без Telegram-контекста…» — интерактивная проверка кнопок карты требует Telegram-клиента и остаётся у владельца (необязательная, не блокирует); поведение кнопок подтверждено тестом против того же бандла (sha совпадает).

## 7. Release-гейт

Карта требований CMV (`plans/features/epic-cm-visual-01/...`) в этой линии отсутствует (`requirements-map.json` нет), `requirements_gate.py --stage release` для слайса не применим; статус bookkeeping — как в REL-258156 (PM/Orchestrator), прод-артефакт и постпроверки при этом корректны. `VERIFIED` из отсутствующего доказательства не выставлялся.

## 8. Откат (не потребовался)

`git checkout -B release/2.58.157 6fd3dcf391482836af6907bb4654291a97018076` + `systemctl restart admin_bot`.
DDL нет, `services/` в дельте пусто, статические ассеты возвращаются вместе с коммитом, промпты/данные не затрагивались.

## 9. Независимая перепроверка (05.11.2026, 06:35 локального / 18:35 UTC)

Отдельный прогон DevOps после выката — те же факты, полученные заново с сервера, не из этой записи:

- кандидат/прод идентичны: ветка `release/2.58.158`, `HEAD=40a622484bab8ff14feda232b928271fcf57f76c` = `origin/release/2.58.158`; `7080fda6` — предок HEAD (фикс присутствует); `APP_VERSION = "2.58.158"`;
- прод-дерево: tracked-dirty **0** (только рантайм-каталог `?? .cache/`);
- `systemctl`: active/running, `NRestarts=0`, `ExecMainStartTimestamp 04.11 18:33:59 UTC`; в журнале после рестарта `Traceback|CRITICAL` — **0**, `-p err` — пусто; миграции `user_version=41`, `pending=[]`;
- `/healthz` loopback и публично 200 `{"status":"ok","version":"2.58.158"}`; `/api/health` 200;
- `web/app.js`: локально = диск сервера = HTTP = `932a94f9158593326b57d8f5eadfca818149df887875b26350b842c928d4a9e1` (прежний `49523d3c…f746797`);
- `index.html` отдаёт `app.js?v=2.58.158`; в разметке `graphResetView(` 2 и `graphResetFilters(` 2; в отдаваемом `app.js` присутствуют оба идентификатора;
- повтор тестов на том же коммите: `EVOL-CMV-D-OK checks=84`; `pytest` → **73 passed**, 0 failed;
- Playwright по публичной странице: 23 запроса, все 200, 0 ошибок приложения в консоли, ассеты с `?v=2.58.158`; `#/memory` без Telegram-контекста даёт штатный экран «Миниапп открыт без Telegram-контекста» — интерактив кнопок требует Telegram-клиента (необязательная проверка владельца, релиз не блокирует).

Откат не потребовался, состояние отката без изменений (см. §8).

## 10. Артефакты

- Worktree релиза: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\release-258158-9d6d7eef1d53-d147dcf3` (`release/2.58.158` @ `40a62248`, чистый, зарегистрирован).
- Скрипты прогона: `WorkspaceData/runs/rel258158-{scan,bump}.py`, `rel258158-{probe,post}.ps1`.
