# Prod health — HTTP-only verification (evol audit)

- **Дата/время проверок:** 2026-10-29 23:56:28 +12:00 (UTC 2026-10-29 11:56:28)
- **Base URL:** `https://admin-bot.duckdns.org` (443, Caddy → uvicorn; новый VPS, service `admin_bot`)
- **Ограничения:** только HTTPS-запросы; без SSH/логинов (fail2ban), без аутентификации, без изменений кода.
- **Сырые артефакты проб:** `WorkspaceData/runs/c742e4de9e92c489/evol-audit-ff24d3ac81be/temp-9be75a274f/` (заголовки+тела ответов).

## Результаты

| Endpoint | Метод | Статус | Наблюдение |
|---|---|---|---|
| `/healthz` | GET | **200** | `{"status":"ok","version":"2.58.141"}`, `Cache-Control: no-store` |
| `/api/health` | GET | **200** | `{"status":"ok"}` — record-only |
| `/` | GET | **307** | `Location: /web/` (ожидаемо по роуту `web/app.py:313`) |
| `/web/` | GET | **200** | 930 269 байт, `text/html; charset=utf-8`, no-store; в HTML — заголовок AdminBot + подключение Telegram MiniApp SDK (входная точка админ-UI/MiniApp) |
| `/web/index.html` | GET | **200** | тот же ответ (алиас-роут) |

## Версия

- `/healthz` отдаёт **2.58.141** — совпадает с ожидаемой релизной версией.
- Commit-строку health-эндпоинт не раскрывает (по коду `web/app.py:324-334` — только `status`+`version`). Привязка версии к коммиту — из репо-артефактов миграции: 2.58.141 @ `5346ee76` (commit `37aaebbb`).
- Примечание (не расхождение прода): локальный чекаут HEAD `3193b657` (behind 143 vs origin), его `config/settings.py` ещё на 2.58.111 — рабочая копия отстаёт от origin, прод новее.

## Диагностика подсистем без авторизации

- `/healthz`: только `status`+`version`; **embeddings/memory/vision не раскрываются**.
- `/api/health`: только `{"status":"ok"}` (по коду `web/api/routes.py:330-333`, «без auth (ngrok/мониторинг)»); подсистемы не раскрываются.
- Все прочие `/api/*` — за TMA-initData (`web/api/routes.py:3`). Глубже не зондировалось (по условию задачи).

## Вердикт

**Production alive and matching expected release** (2.58.141; healthz/UI/MiniApp отвечают 200, расхождений нет).
