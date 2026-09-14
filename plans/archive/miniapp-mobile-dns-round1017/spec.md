# Спека F1 — `miniapp-mobile-dns-round1017` (Мобильный мини-апп: `ERR_NAME_NOT_RESOLVED` на Android)

> **Статус:** ✅ COMPLETED (14.09.2026; @Reviewer **APPROVED**, итерация 2). Код-часть реализована; открыты только инфра-гейты DNS/Android-смоук (@DevOps, Step 9).
> **Раунд:** 10.17. **Тип:** infra + repo-diagnostics. **Приоритет:** P0 (прод-блокер).
> **T-ID:** T-1666…T-1674. **ADR:** [`adr-1017-1-miniapp-hostname-dns.md`](adr-1017-1-miniapp-hostname-dns.md).
> **Baseline:** HEAD `772f192`; pytest 5936/0; каталог 435/406/411/90/88/19 (Δ=0); SQLite v9.
> **ТЗ:** `plans/current_task.md` UPD3 (стр. 155–157) + UPD2 §4 (стр. 153).

## 0. Цель и диагноз

На **десктопе** мини-апп открывается, на **Android** — `net::ERR_NAME_NOT_RESOLVED`. В 10.13–10.16 `WEBAPP_URL` (`config/settings.py:170-173`), `MEDIA_PUBLIC_BASE_URL` (`:987-989`), `handlers/menu.py:48-66` и домен/схема/путь **не менялись**; в `web/` внешних CDN нет (self-host 10.16, ADR-1016-2). `ERR_NAME_NOT_RESOLVED` = сбой резолва **топ-домена** (не субресурс, не CSP): адрес набирается в адресной строке WebView, значит падает именно `admin-bot.duckdns.org`.

**Ключевой вывод:** причина — **вне репозитория** (DNS/DuckDNS/оператор/Private DNS). Проблема «началась после последних изменений» — **ложная корреляция**: 10.16 убрал внешние CDN (снял субресурсный резолв), но топ-домен `duckdns.org` блокируется мобильным оператором/резолвером. Смена hostname в репо **не требуется**: `WEBAPP_URL` уже env-driven → переключение домена = правка `.env` (@DevOps), без кода.

## 1. Scope

**In scope (репо, проверяемо):**
- Явные `HEAD`-обработчики `/web/`, `/web/index.html` (детерминированный ответ для внешних проверок; Starlette авто-HEAD уже есть — фиксируем контракт и тестом).
- Unauthenticated health-check `/healthz` (GET + HEAD) — дешёвая точка для `dig`/`curl -I` из мобильной сети @DevOps.
- Startup-диагностика: host/scheme/path `WEBAPP_URL` и host `MEDIA_PUBLIC_BASE_URL` (только host — R17).
- Регресс-гейт: отсутствие внешних CDN в `web/**`; консистентность absolute-URL (scheme https, непустой host).
- Документированная процедура смены hostname (env-only) — в ADR-1017-1.

**Out of scope:**
- DNS-записи DuckDNS, Caddy, Let's Encrypt, сеть оператора (@DevOps, вне репо).
- Смена hostname/провайдера (продуктовое решение владельца; env-only — код не нужен).
- **Возврат внешних CDN — запрещён** (ADR-1016-2 в силе).
- Изменение пути `/web/`, схемы `https`, CSP; `media/`, `.env`.

## 2. Точки изменения (`file:line` на `772f192`)

| Файл | Строки | Что |
|---|---|---|
| `web/app.py` | 195-221 | добавить `@app.head("/web/")`, `@app.head("/web/index.html")`; `@app.get/head("/healthz")` |
| `web/app.py` | 123-137 | startup-лог `[webapp] url | scheme=… host=… path=…` (host-only, R17) |
| `web/app.py` | 276-285 | `_html_response` — использовать для HEAD (тело пустое, заголовки те же) |
| `handlers/menu.py` | 64-66 | лог host (не полный URL) |
| `config/settings.py` | 170-173, 987-989 | **не менять** (env-driven; evidence «не менялось») |
| `web/index.html`, `web/app.js`, `web/static/*` | — | аудит отсутствия внешних CDN |
| `tests/test_webapp_dns_round1017.py` | новый | гейт HEAD/healthz/CSP/no-CDN |

## 3. Контракты

### 3.1. `/healthz` (новая точка, unauth)
```
GET  /healthz → 200 application/json {"status":"ok","version":"<APP_VERSION>"}
HEAD /healthz → 200 (тело пустое), те же заголовки
Cache-Control: no-store
```
Назначение: `curl -I https://<host>/healthz` из мобильной сети @DevOps отличает **DNS-сбой** (curl: `Could not resolve host`) от **TLS/Caddy** (код/заголовки). В Caddy разрешить `/healthz` (вне репо, @DevOps).

### 3.2. HEAD для HTML мини-аппа
```
HEAD /web/           → 200, Content-Security-Policy, Cache-Control: no-cache,no-store,must-revalidate
HEAD /web/index.html → 200, то же
```
Реализация — явные `@app.head(...)`, возвращающие `_html_response(rendered_index)`; Starlette для HEAD не отдаёт тело. Причина явных роутов: текущий контракт «HEAD не заявлен» → в прод-проверках невозможно отличить маршрутизацию от DNS; фиксируем его тестом.

### 3.3. Startup-диагностика (R17: host-only)
```
[webapp] WEBAPP_URL | scheme=https | host=admin-bot.duckdns.org | path=/web/
[webapp] MEDIA_PUBLIC_BASE_URL | scheme=https | host=admin-bot.duckdns.org
[menu] sent | chat=<id> | type=private | host=admin-bot.duckdns.org
```
Парсинг через `urllib.parse.urlsplit`; полный URL/секреты не логировать.

## 4. Алгоритм/псевдокод (`web/app.py`)

```python
from urllib.parse import urlsplit

def _startup_diag() -> None:
    for name in ("WEBAPP_URL", "MEDIA_PUBLIC_BASE_URL"):
        raw = str(getattr(settings, name, "") or "").strip()
        parts = urlsplit(raw)
        logger.info("[webapp] %s | scheme=%s | host=%s | path=%s",
                    name, parts.scheme, parts.hostname or "-", parts.path or "-")

# в create_app(): после include_router, ДО mount
@app.head("/web/", include_in_schema=False)
async def web_index_head():
    return _html_response(rendered_index)

@app.head("/web/index.html", include_in_schema=False)
async def web_index_html_head():
    return _html_response(rendered_index)

@app.get("/healthz", include_in_schema=False)
async def healthz():
    return JSONResponse({"status": "ok", "version": APP_VERSION},
                        headers={"Cache-Control": "no-store"})

@app.head("/healthz", include_in_schema=False)
async def healthz_head():
    return Response(status_code=200, headers={"Cache-Control": "no-store"})
```

`handlers/menu.py`: добавить `host=urlsplit(url).hostname or "-"` в существующий `logger.info("[menu] sent ...")`.

## 5. Диагностический чек-лист @DevOps (вне репо, T-1667/T-1668/T-1671)

1. **Резолв из разных сетей:** `dig +short A admin-bot.duckdns.org @8.8.8.8 @1.1.1.1 @9.9.9.9`; `dig +short AAAA …`; `dig +short CNAME …`. Ожидание: A→`198.46.175.136`, AAAA пусто.
2. **DuckDNS-запись:** A актуален, AAAA отсутствует/непустой-stale устранён, TTL разумный (300–600).
3. **Мобильная сеть (Android, ≥2 оператора):** `curl -I https://admin-bot.duckdns.org/healthz`; при `Could not resolve host` — оператор не резолвит/блокирует `duckdns.org`.
4. **Private DNS / DoH:** переключить off/auto, повторить; зафиксировать класс (`blocked`/`empty`/`DoH`).
5. **LE/Caddy:** `curl -I /web/` (200, CSP), сертификат `notAfter`; `encode zstd gzip`.
6. **Если подтверждена блокировка `duckdns.org`:** фоллбэк (T-1671, ADR-1017-1 §4) — альтернативный hostname/DNS-провайдер; смена = правка `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL` в `.env` + `systemctl restart admin_bot` (код не меняется).
7. **Живой Android-смоук (T-1673):** `/menu` → WebApp открывается, initData/auth, загрузка без «~1 минуты»; скриншот/лог.

## 6. Тест-план (`tests/test_webapp_dns_round1017.py`)

| # | Проверка | Ожидание |
|---|---|---|
| 1 | `TestClient(create_app(cache))` `HEAD /web/` | 200 + CSP + no-store |
| 2 | `HEAD /web/index.html` | 200 |
| 3 | `GET /healthz` | 200, JSON `status=ok`, `Cache-Control: no-store` |
| 4 | `HEAD /healthz` | 200 |
| 5 | static scan `web/index.html`/`app.js`/`static/app.css`/vendor | нет `http(s)://cdn.`/`unpkg`/`jsdelivr`/`tailwindcss.com`/внешних `telegram.org`-скриптов |
| 6 | defaults `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL` | scheme `https`, host непуст, path `/web/` сохранён |
| 7 | консистентность host двух URL | совпадают |
| 8 | startup-лог (caplog) | печатается host, НЕ полный URL/секреты (R17) |

## 7. Риски

| Риск | Мера |
|---|---|
| `/healthz` не проксируется Caddy | чек-лист @DevOps (п.1) до провозглашения фикса |
| Блокировка `duckdns.org` оператором | фоллбэк hostname (env-only, T-1671); ADR-1017-1 |
| Ложная уверенность «починили в репо» | DoD требует **живого** Android-смоука (T-1673), а не только in-process теста |
| Утечка URL в логи | host-only, R17-скан |
| Регресс self-host/CSP | тест no-CDN + существующие `test_smoke_round1016_miniapp_selfhost.py` |

## 8. Критерии приёмки (DoD)

- [ ] `HEAD /web/` и `/healthz` (GET+HEAD) → 200 in-process (тест).
- [ ] Startup-лог host/scheme/path без секретов/полного URL.
- [ ] Подтверждён факт: `ERR_NAME_NOT_RESOLVED` = сбой резолва топ-домена (devops-отчёт).
- [ ] Регресс в репо исключён (diff/grep: домен/схема/путь не менялись; внешних CDN нет).
- [ ] Живой Android-смоук пройден (скриншот/лог); «~1 минута» не воспроизводится.
- [ ] Полный pytest 0 failed; каталог Δ=0; R17-скан чист; `git diff --check`.

## 9. Feature flag / progressive delivery

- **Feature flag:** не требуется (infra-фикс + диагностические роуты). Rollback = `git revert` (роуты без состояния).
- **Progressive delivery:** канареечный hostname/sub-path на уровне Caddy/DNS @DevOps. Мониторинг: `/healthz` из мобильной сети, ошибки резолва, время до интерактива.

## 10. Handoff

`@Orchestrator` — спецификация F1 готова. Реализация: T-1669/T-1670/T-1672 (@Builder), T-1667/T-1668/T-1671/T-1673 (@DevOps), гейт T-1674 (@Reviewer/@PM).
