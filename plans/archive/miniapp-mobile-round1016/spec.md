# Спека F4 — `miniapp-mobile-round1016` (Мини-апп: мобильный запуск, self-host CDN, CSP, скорость)

> **Статус:** ✅ COMPLETED (14.09.2026; @Reviewer APPROVED, итерация 2). T-1651 закрыт.
> **Раунд:** 10.16. **Тип:** frontend + infra. **Приоритет:** P1. **T-ID:** T-1651…T-1659.
> **ТЗ:** `plans/current_task.md` UPD2 (строка 153: `ERR_NAME_NOT_RESOLVED` на Android, «~1 минута»).
> **ADR:** [`adr-1016-2-selfhost-csp.md`](adr-1016-2-selfhost-csp.md).
> **Baseline:** HEAD `18a9aa1`; pytest 5774/0; каталог 435/90/406/411/88/19 (Δ=0).
> **Зависимости:** нет. **Вниз:** F5. Параллельно с F3. Серверная часть (Caddy/DNS) — @DevOps, вне репо.

## 0. Цель и диагноз

Симптомы: Android WebView → `net::ERR_NAME_NOT_RESOLVED` (десктоп ок); часть пользователей ждала «~1 минуту».

**Оценка причин (гипотезы, проверяются чек-листом §7):**
1. **Top-level домен** `admin-bot.duckdns.org` не резолвится у части Android: оператор/DNS-репутация DuckDNS, **приватный DNS (DoH)** не резолвит зону, либо у A-записи есть нерабочий **AAAA** (IPv6 без маршрута). `ERR_NAME_NOT_RESOLVED` на уровне навигации указывает именно на хост документа.
2. **Subresource-CDN** `telegram.org` / `cdn.tailwindcss.com` / `unpkg.com` / `cdn.jsdelivr.net` блокируются/не резолвятся в регионе → падает JS, и в консоли тот же `ERR_NAME_NOT_RESOLVED`.
3. **«~1 минута»** — блокирующие внешние `<script>` (синхронные, до рендера) с длинными DNS-таймаутами/ретраями + несжатые `index.html` (~235 КБ) и `app.js` (~285 КБ).

Цель: убрать все внешние блокирующие ресурсы (self-host), включить строгий CSP, вынести CSS/инлайн-скрипты, включить сжатие/кеш (Caddy, вне репо) — приложение грузится без внешних CDN; причина DNS установлена и устранена/задокументирована @DevOps.

## 1. Точки изменения (`file:line` на HEAD `18a9aa1`)

| Файл | Строки | Что |
|---|---|---|
| `web/index.html` | 11 | `telegram.org/js/telegram-web-app.js` (блокирующий) → self-host |
| `web/index.html` | 12 | `cdn.tailwindcss.com` (блокирующий Play CDN) → предсобранный CSS |
| `web/index.html` | 13-19 | inline `tailwind.config` → удалить (при prebuilt CSS) |
| `web/index.html` | 20-… | большой `<style>` → вынести в `web/static/app.css?v=…` |
| `web/index.html` | 3633 | `unpkg.com/vue@3` → self-host |
| `web/index.html` | 3637 | DOMPurify уже self-host (прецедент) |
| `web/index.html` | 3638 | `cdn.jsdelivr.net/npm/chart.js@4` → self-host |
| `web/index.html` | 3640-3656 | inline Telegram-init → вынести в `/static/telegram-init.js` |
| `web/app.py` | 151-157, 216-221 | CSP-заголовок для `/web/`, `/web/index.html`; статика без изменений |
| `web/static/vendor/*` | — | новые self-host бандлы (Vue/Chart.js/Tailwind CSS/telegram) |
| конфиг Caddy | **вне репо** | compression/brotli, CSP duplicate, кеш — инструкция @DevOps |
| `handlers/menu.py` | 53-64 | без изменений (при необходимости — только если меняется URL) |

## 2. Self-host политика (нормативно)

Все внешние ресурсы → `web/static/vendor/` (паттерн ADR-1013-2 DOMPurify/vis-network). **Никаких новых CDN.**

| Ресурс | Источник | Локальная цель | Версия/лицензия |
|---|---|---|---|
| Telegram WebApp SDK | telegram.org | `vendor/telegram-web-app.js` | пин-версия (зафиксировать комментарием) |
| Vue 3 | unpkg `vue@3/dist/vue.global.prod.js` | `vendor/vue.global.prod.min.js` | 3.x prod, MIT |
| Chart.js 4 | jsdelivr `chart.js@4` | `vendor/chart.umd.min.js` | 4.x UMD, MIT |
| Tailwind | `cdn.tailwindcss.com` (Play/JIT) | **не self-host**; предсобранный `vendor/tailwind.css` | build-time CLI, MIT |

**Tailwind — решение (ADR-1016-2 §3):** Play CDN — рантайм-JIT, тяжёлый и не предназначен для прода; self-host его бессмыслен. Генерируем **предсобранный CSS** (Tailwind CLI, standalone/npx) из `content: ['./web/index.html', './web/app.js']` + `tailwind.config.js` (перенос текущего inline-конфига), коммитим `vendor/tailwind.css`. Рантайм — только локальный CSS, zero-build на сервере.
- **Риск динамических классов:** классы, собираемые в JS-строках, могут не попасть в скан. Мера: `safelist` для вычисляемых классов + визуальная проверка ключевых экранов (см. §6 тест 4). Если найдены пропуски — добавить в `safelist` и пересобрать (не возвращать CDN).
- Команда регенерации документируется рядом с файлом/в README фронта.

**Инлайн-скрипты:** оба (tailwind.config и Telegram-init) удаляются/выносятся; `tailwind.config` нужен только на этапе сборки, Telegram-init → `/static/telegram-init.js`. Итог: в `index.html` **нет inline-скриптов** → CSP `script-src 'self'` без `'unsafe-inline'`/nonce/hash.

## 3. CSP-политика (нормативно)

Заголовок `Content-Security-Policy` для HTML (`/web/`, `/web/index.html`) — в `web/app.py` (`_html_response`), дублируется/усиливается в Caddy (инструкция @DevOps):
```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:;
font-src 'self';
connect-src 'self';
frame-ancestors https://web.telegram.org https://*.telegram.org;
base-uri 'self';
object-src 'none';
form-action 'self'
```
- `style-src 'unsafe-inline'` **необходим**: Vue биндит `:style` (inline style-атрибуты) и в приложении есть `<style>`; полный отказ потребует переписывания стилей — вне скоупа. Скрипты при этом строгие (`script-src 'self'`) — основной выигрыш.
- `frame-ancestors` — чтобы Telegram Web/WebView мог встроить приложение. Если в проде Telegram-клиент встраивает с другого origin (напр. `https://web.telegram.org`), расширить список; проверка — §6 тест 5.
- `connect-src 'self'` — API same-origin. Если Telegram SDK потребует сетевой origin — расширить точечно (документируется в отчёте), но по умолчанию оставить `'self'`.
- CSP применяется только к HTML-ответам, не к `/api` (не ломать API/`initData`).

## 4. Скорость / «~1 минута»

Приоритет мер (без тяжёлого JS-тулчейна):
1. **Убрать блокирующие внешние скрипты** (главный источник таймаутов) → локальные same-origin.
2. **Сжатие на Caddy** (gzip/brotli) для `text/html`, `application/javascript`, `text/css` — вне репо, самый крупный выигрыш по байтам; инструкция @DevOps.
3. **Вынести `<style>`** в `app.css` (кэшируется, парсится параллельно).
4. **`<link rel="preload">`** для локальных критичных ассетов; локальные скрипты — `defer` там, где позволяет порядок (Vue/Chart — до `app.js`; сохранить порядок исполнения).
5. **Кеш-версионирование** `?v=__APP_VERSION__` — сохранить (как сейчас).
6. **Service worker — OUT** (риск stale-cache и усложнение; при необходимости — отдельный раунд с явной политикой инвалидации).
7. **Временное дублирование CDN как fallback — OUT:** возвращает исходный сбой; источник истины — self-host. Аварийный откат = `git revert`.
8. Минификация JS/HTML — **не обязательна**: сжатие Caddy даёт основной эффект; коммитить минифицированные исходники не нужно (читаемость). `vendor/*.min.js` — уже минифицированные upstream-бандлы.

## 5. Диагностика DNS (вне репо, @DevOps)

Артефакт-чек-лист (см. §7) + отчёт. Ключевые проверки: `dig A/AAAA admin-bot.duckdns.org @8.8.8.8` и `@1.1.1.1`, наличие/корректность AAAA, резолв из мобильных сетей, `curl -I https://admin-bot.duckdns.org/web/`, сертификат LE, Caddy 2.11.4, сжатие, MTU. Если AAAA виноват — удалить AAAA у DuckDNS (тогда IPv4-only для несовместимых клиентов).

## 6. Конфиг / флаги

- **Новых параметров/флагов нет** (каталог-Δ=0); `WEBAPP_URL` не меняется (`config/settings.py:171-173`).
- Опциональный kill-switch раздачи нового бандла — **вне репо** (Caddy/файл-переключатель @DevOps), не обязателен.
- Progressive delivery — канареечно на уровне Caddy/DNS (отдельный host/sub-path) — вне репо; мониторинг: время загрузки, 4xx/5xx, ошибки резолва.
- Rollback = `git revert` + `systemctl restart` (или Caddy-переключатель).

## 7. DevOps-чек-лист (артефакт T-1656/T-1657, вне репо)

```
[ ] dig A  admin-bot.duckdns.org @8.8.8.8 @1.1.1.1  → совпадает с сервером
[ ] dig AAAA admin-bot.duckdns.org                  → есть/нет; при наличии — доступен ли IPv6 у клиента
[ ] Проверка с мобильного оператора / Private DNS (Android): curl -I https://admin-bot.duckdns.org/web/
[ ] Caddy 2.11.4: сертификат LE валиден, авто-renew
[ ] Caddy: gzip/brotli включены для html/js/css; Cache-Control для /static/vendor/*
[ ] Caddy/приложение: CSP-заголовок присутствует, не блокирует Telegram WebApp
[ ] MTU/фрагментация на пути; отсутствие блокировки CDN-хостов (не нужны после self-host)
[ ] Отчёт без секретов (R17)
```

## 8. Тест-план (T-1658/T-1659)

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | Grep `web/index.html` | нет `https://` внешних `<script>`/`<link>` (кроме self-host) |
| 2 | `node --check web/app.js` | clean |
| 3 | `node tests/js/routing_test.js` | `JS-UNIT-OK` (hash-router/шаблоны не сломаны) |
| 4 | Мобильный smoke (DevTools device emulation + блокировка внешних хостов в hosts/req-interceptor) | приложение грузится; ключевые экраны рендерятся (проверка safelist Tailwind) |
| 5 | CSP-прогон с тестовым Telegram-оригином | нет CSP-нарушений `script-src`; WebApp/`initData` работают |
| 6 | Замер времени до интерактива (локальный CSS/JS) vs baseline | измеримое сокращение |
| 7 | `pytest` | 0 failed; каталог Δ=0 |

## 9. Риски и меры

| Риск | Мера |
|---|---|
| Prebuilt Tailwind теряет динамические классы | `safelist` + визуальная проверка (тест 4); при пропуске — добавить класс и пересобрать |
| Self-host `telegram-web-app.js` устаревает | пин-версии + комментарий/дока об обновлении; SDK стабилен |
| CSP ломает Telegram WebApp/`initData` | `frame-ancestors`/`connect-src` подобраны; тест 5; точечное расширение при необходимости |
| Android всё ещё не резолвит домен | DNS-диагностика @DevOps (§7); self-host CDN устраняет subresource-часть, top-level — серверная зона |
| `defer`/порядок ломает инициализацию | сохранять порядок (Vue→app.js), менять только атрибуты, JS-гейты |
| CSP «забыт» в Caddy | дублирование в `web/app.py` + чек-лист @DevOps |

## 10. Критерии приёмки (DoD)

- [ ] Внешние блокирующие `<script>` (telegram/tailwind/vue/chart) устранены; всё self-host в `web/static/vendor/`.
- [ ] Tailwind — предсобранный `vendor/tailwind.css`; inline-скрипты вынесены; `script-src 'self'`.
- [ ] CSP-заголовок активен (приложение + Caddy-инструкция); WebApp/`initData` не сломан.
- [ ] `<style>` вынесен в `app.css`; `?v=` сохранён; сжатие на Caddy включено (@DevOps).
- [ ] Причина `ERR_NAME_NOT_RESOLVED` установлена и устранена/задокументирована; артефакт-чек-лист @DevOps готов.
- [ ] `node --check`/`JS-UNIT-OK`; мобильный smoke без внешних CDN; полный `pytest` 0 failed; каталог Δ=0.
- [ ] Инварианты: новых CDN/`v-html` без санитайза нет; `media/`/`.env` не тронуты; порядок роутеров `bot.py` не тронут.

## 11. Handoff

Реализация — @Builder: T-1652…T-1656, T-1658; @DevOps: T-1657; гейт — T-1659.
`@Orchestrator` — спецификация F4 готова.
