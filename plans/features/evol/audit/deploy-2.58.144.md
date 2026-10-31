# EVOL — выкат 2.58.144: Status order + warning tint (волна 2 ASAP-UI-02)

Дата: 31.10.2026, 14:39–14:41 UTC (новый VPS `192.255.209.205`). Роль: DevOps.
Итог: **успешный выкат, прод на 2.58.144 @ `ebec502b`.**

## 1. Привязка кандидата

| Параметр | Значение |
|---|---|
| `DEPLOY_SOURCE` | commit `ebec502b89d8d81dbcd9059f49c52db57fd66579` (ветка `release/2.58.144` = `evol/impl`) |
| Ревью-кандидат волны 2 | `0b198ad2` (+ `9e009671`), Reviewer PASS |
| Bump-коммит | `ebec502b` (2.58.143 → 2.58.144, 31 файл / 32 вхождения, набор пинов идентичен бампу 2.58.143) |
| Предыдущий прод (baseline) | `273be95c` — 2.58.143, SQLite `user_version=40` |
| FF-проверка | `git merge-base --is-ancestor 273be95c ebec502b` → yes |
| Push | `origin/release/2.58.144` = `origin/evol/impl` = `ebec502b` (проверено `ls-remote`) |
| `MUTABLE_WORKTREE_REQUIRED` | **no** — деплой по Git-коммиту из GitHub; локальный worktree не участвует |
| Write scope на проде | `git checkout -B release/2.58.144` + рестарт; продуктовые файлы сервера не правятся вручную |

Проверки кандидата до выката: `compileall` rc=0; node 5/5 OK (4 пина + `asap_ui02_status_ribbons`); pin-pytest
**867 passed**, 1 failed — `test_summary_publish_integration_round1026::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article`
(известный пре-существующий провал, воспроизводится до бампа, зафиксирован в `deploy-2.58.143.md` §2).

## 2. Ход выката (2 SSH-подключения: recon + основной прогон, fail2ban-режим)

- **recon** 14:31 UTC: `HEAD=273be95c`, ветка `release/2.58.143`, dirty=1 (`?? .cache/`), сервис `active`,
  `MainPID=754390`, `NRestarts=0`, `/healthz` 200 `2.58.143`, `/web/` 200, `/api/health` 200,
  media tracked=65, `srv_cookies.txt` не в Git, 1 процесс бота, 0 `Traceback/ERROR` за 60 мин, диск 21%.
- **основной прогон** 14:39:25 UTC: preflight (dirty=1, `?? .cache/`) → `git fetch --prune` →
  `git checkout -B release/2.58.144 origin/release/2.58.144` → `HEAD=ebec502b` (ровно кандидат) →
  `systemctl restart admin_bot` → готовность с первой итерации.

## 3. Проверки после выката

| Проверка | Результат |
|---|---|
| `/healthz` | **200** `{"status":"ok","version":"2.58.144"}` |
| `/web/` | **200**, 1 069 705 байт |
| `/api/health` (127.0.0.1:8000) | **200** |
| Сервис | `active`, `MainPID=781799`, **`NRestarts=0`** |
| Процессы бота | **1** |
| Журнал с момента рестарта | 219 строк, **0** `Traceback`, **0** `ERROR`/`IndeterminateDatatype` |
| `apply_release` | выполнен: `release=evol-016-cutover | blocks=109 | changed=0 | retired=0` (дрейфа конфигурации нет — волна чисто фронтовая) |
| SQLite | `user_version=40`, `quick_check=ok` (DDL не менялся) |
| Медиа | tracked=**65** (без изменений), `media/srv_cookies.txt` — **не** отслеживается |
| Стабильность (+30 с) | `/healthz` 200 `2.58.144`, `NRestarts=0`, 0 `Traceback`, 1 процесс |

## 4. Smoke волны 2 (read-only HTTP по задеплоенному билду)

Отдаваемые ассеты побайтно совпадают с кандидатом: `app.css` 329 867 = локальный, `app.js` 1 529 052 = локальный.

- index (`/web/`): `data-intel-switcher` = 1, `data-ribbon="` = 4 (ровно 4 секции), `intel-card` = 1,
  `data-health-inline="heartbeat"` присутствует, старый `card p-4 status-facts` = **0** (факты перенесены в виджет).
- CSS: `cognition-ribbons` = 8, `.hb-surface {` = 1 (собственная поверхность Heartbeat),
  `[data-health-state="warning"][data-health-material="bg"]` = 1 (отдельный warning-тон),
  `--control-h-touch, 44px` = 28 вхождений (переключатель 44 px).
- JS: `switchStatusRibbon` = 2, `statusRibbonTabs` = 2, `heartbeatHealthSource` = 2 (единый сигнал здоровья).

Telegram-отправок не выполнялось.

## 5. Откат

Не требовался. Готов: `git checkout --detach 273be95c` + `systemctl restart admin_bot` + проверка `/healthz` 200 `2.58.143`.
Последняя подтверждённо здоровая версия — `273be95c` (2.58.143); схема БД на обеих версиях `user_version=40`, откат безопасен.

## 6. Что осталось вне DevOps

1. **PM/evidence:** `plans/features/evol/requirements-map.json` — `deployed_commit` всё ещё `273be95c`;
   для закрытия волны 2 нужен перенос на `ebec502b` + привязка наблюдений. Карта исторически не `strict_evidence`,
   `source_path=plans/current_task.md` в worktree отсутствует (известное состояние, отмечено в `deploy-2.58.143.md` §7).
   Значения VERIFIED вручную не выставлялись.
2. **PM/backlog:** `test_summary_publish_integration_round1026::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article` — пре-существующий провал (не связан с волной).
3. **Orchestrator:** влить `release/2.58.144` в `master` (расхождение основной ветки и деплой-источника сохраняется с 2.58.143).
4. Необязательные наблюдения владельца (реальный Telegram-клиент) — по стоячему решению проекта не блокируют.
