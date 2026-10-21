# DEPLOY-25880 — verification summary (compact evidence)

Релиз: **2.58.80**, release commit `31c165556dbe8c289606bd6bee1af49bb72d5794` (`31c16555`),
parent `d9b7f389` (reviewed: `plans/features/soul-1/review-ui-fixes.md` — Approved).
Прод: 198.46.175.136, сервис `admin_bot`, `/var/www/admin_bot`.
Метод: bump-коммит → `git push origin master` (`c2775a54..31c16555`) → на сервере
`git pull --ff-only` (штатный pull-канал, GitHub origin) → `systemctl restart admin_bot`
→ проверки с сервера (локальный DNS домена не работает; 443-путь эмулирован
`curl --resolve admin-bot.duckdns.org:443:127.0.0.1` через caddy).

## Артефактная привязка (sha256: файл в коммите == файл на сервере == отданный asset)

| Файл | sha256 | Источник совпадения |
| --- | --- | --- |
| `web/static/app.css` | `70975eb2eac08f01beaecc1bf5be6ff005de75efada145f96785c0973c887be2` | совпадает с отпечатком ревью (review-ui-fixes) и с sha отданного `/web/static/app.css` |
| `web/app.js` | `9774da6a4e932287123cc49f8c84337a77f2bdef63385b3e76a9d47d5f9cb8ac` | совпадает с отпечатком RECHECK-UI |
| `web/index.html` | `e209d5faf7e8e54a907a35c570aba9f574cbfa9fbae2ae1fc8c95e53be26b3e0` | совпадает с отпечатком ревью |
| `services/param_catalog.py` | `1981d3382e2ee81222107027ead5e7e61ef438cbdc91afcd1c13e668d0d15ba7` | совпадает с pinned sha в `tests/fixtures/round1025/f8_baseline.json` |
| `config/settings.py` | `5a31a2770ab27ba8b21f3f1fba499c50464b7798af15be8b79c09a31b9f722fd` | release blob (APP_VERSION=2.58.80) |

## Проверки на проде (наблюдённые результаты)

| Проверка | Команда/контекст (с сервера) | Результат |
| --- | --- | --- |
| server HEAD | `git rev-parse HEAD` (фаза B, программная проверка) | `31c165556dbe8c289606bd6bee1af49bb72d5794` |
| сервис | `systemctl show admin_bot -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStatus` | `ActiveState=active SubState=running MainPID=2815638 NRestarts=0 ExecMainStatus=0` |
| healthz (loopback) | `curl -s http://127.0.0.1:8000/healthz` | `{"status":"ok","version":"2.58.80"}` |
| healthz (443, caddy) | `curl -s --resolve admin-bot.duckdns.org:443:127.0.0.1 https://admin-bot.duckdns.org/healthz` | `{"status":"ok","version":"2.58.80"}` |
| главная web-страница | `/web/` (443-эмуляция) | `200`, `728255` байт; вхождений `2.58.80` = `14` (все `__APP_VERSION__` подставлены), вхождений `2.58.79` = `0` |
| отданный CSS | `/web/static/app.css` (443-эмуляция) | `200`; sha256 = `70975eb2…87be2` (= файл коммита); формула `max(env(safe-area-inset-right, 0px), var(--tg-content-safe-area-inset-right, 0px), var(--tg-safe-area-inset-right, 0px))` = 3 вхождения (в т.ч. `header.header-sticky` — строка 1017) |
| config API (auth-контур) | `GET /api/config` без TMA-initData | `401` — auth включён, без initData витрина недоступна (ожидаемо; секретов не отдаёт) |
| L1 planner в конфиг-пути | прод-рантайм `venv/bin/python` (интерпретатор сервиса): реальный путь `/api/config` — `ConfigCache._synthetic_group_items()` по deployed-каталогу | `PROBE version=2.58.80`, `catalog=True category=prompts group=prompts_direct_chat per_chat=True`, `synthetic_present=True value_len=2423` — ключ больше не выпадает из конфиг-витрины |
| api health | `GET /api/health` (443) | `200` |
| журнал после рестарта (`--since 09:43:54`) | `journalctl -u admin_bot` → 224 строки | `ERROR=0 CRITICAL=0 Traceback=0 database-locked=0`; 1 INFO-строка упоминает `direct_l1_planner` (штатная семантика prompt_migrations, см. отчёт) |
| healthz-подъём | poll после restart | `TRY1=000 TRY2=000 TRY3=200` (~30 c) |

Транскрипт прогона: `ev01-deploy-run.txt`. Release-гейт (read-only, карта не редактировалась):
`ev02-gate-release-check.txt` (FAIL: карта привязана к `c2775a54`, позиции без evidence —
бухгалтерия покрытия; деплой это не отменяет, финальный re-capture — за parent).
