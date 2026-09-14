# ADR-1016-2 — Мини-апп: self-host ресурсов, строгий CSP, предсобранный Tailwind

> **Статус:** Accepted (Step 2 @Architect, 14.09.2026). **Раунд:** 10.16. **Фича:** F4 `miniapp-mobile-round1016`.
> **Связано:** ADR-1013-2 (self-host DOMPurify/vis-network), §9/§26 `ARCHITECTURE.md` (zero-build фирменный стек), UPD2 строка 153.

## 1. Контекст

Android WebView даёт `net::ERR_NAME_NOT_RESOLVED`, десктоп работает; часть пользователей ждала «~1 минуту». `web/index.html` подключает 4 внешних ресурса синхронно: `telegram.org` (:11), `cdn.tailwindcss.com` (:12), `unpkg.com/vue` (:3633), `cdn.jsdelivr.net/chart.js` (:3638); есть 2 inline-скрипта; CSS/JS не сжаты. История эпиков: self-host DOMPurify/vis-network/шрифта уже принят как паттерн.

## 2. Решение

1. **Self-host всех внешних ресурсов** в `web/static/vendor/` (Telegram SDK, Vue 3 prod, Chart.js UMD), пин-версии.
2. **Tailwind:** не self-host Play/JIT-CDN, а **предсобранный CSS** (`vendor/tailwind.css`) через Tailwind CLI на этапе разработки; `tailwind.config.js` переносится из inline; рантайм — zero-build.
3. **Инлайн-скрипты вынести** в external (`/static/telegram-init.js`); tailwind-config-инлайн удаляется.
4. **CSP:** `script-src 'self' 'unsafe-eval'` — ВАРИАНТ A ревью-итерации 1 (см. §4a): self-host использует FULL-сборку Vue, чей рантайм-компилятор исполняет `Function()` при компиляции in-DOM шаблонов; без `'unsafe-eval'` приложение не монтируется (`EvalError`). Внешние скрипты запрещены (`'self'`), `'unsafe-inline'` отсутствует. `style-src 'self' 'unsafe-inline'` (Vue `:style`/`<style>`), `frame-ancestors` для Telegram, `connect-src 'self'`.
5. **Скорость:** сжатие gzip/brotli на Caddy (вне репо) + вынос CSS + preload; service worker и JS-минификация — вне скоупа.

## 3. Альтернативы

| Вариант | Вердикт |
|---|---|
| Self-host Tailwind Play CDN | Отклонён: это рантайм-JIT-движок (~сотни КБ, исполняется в браузере), не предназначен для прода; выгоды нет |
| Оставить CDN + fallback-копия | Отклонён: возвращает исходный сбой (`ERR_NAME_NOT_RESOLVED` на subresource); fallback-логика усложняет |
| CSP с `'unsafe-inline'` для script | Отклонён: обесценивает CSP; правильнее вынести inline-скрипты (их всего 2) |
| CSP `script-src 'self'` + runtime-only Vue + предкомпиляция render-функций (**вариант B**, ревью-итер. 1) | Отклонён как минимально-рискованный путь: требует перевода in-DOM шаблона `#app` (~2900 строк `index.html`) и `template: '#kv-editor-tpl'`/`'#list-editor-tpl'` в `h(...)` — большой объём правок горячего фронта при нулевой прод-выгоде против A |
| `script-src 'self' 'unsafe-eval'` (**вариант A**, ревью-итер. 1) | **Принят:** минимальная правка одной константы; внешние скрипты остаются запрещены (`'self'`), `'unsafe-inline'`/nonce/hash-послаблений нет; компенсируется поведенческим JS-гейтом `tests/js/vue_mount_test.js` |
| CSP с nonce/hash | Отклонён: hash хрупок (правка inline), nonce требует серверной подстановки в статику — дороже, чем вынести скрипты |
| Service worker для офлайна/кеша | Отклонён в этом раунде: риск stale-cache и релизной сложности; достаточно сжатия/кеша/self-host |
| Бандлинг/минификация JS тулчейном | Отклонён: нет гарантии Node-тулчейна в проде, а Caddy-сжатие даёт основной эффект; upstream-бандлы уже `.min.js` |
| Исключить Telegram SDK из self-host | Отклонён: это один из трёх хостов, падающих в регионе; self-host безопасен и широко практикуется |

## 4. Последствия

- (+) Приложение не зависит от внешних CDN → устраняется subresource-часть `ERR_NAME_NOT_RESOLVED` и «~1 минута» (нет DNS-таймаутов).
- (+) Инлайн-скриптов нет; внешние источники скриптов запрещены (`script-src 'self'`).
- (−) `'unsafe-eval'` ослабляет CSP до исполнения `Function()`/`eval`: это **обязательная** плата за FULL-сборку Vue (рантайм-компилятор in-DOM шаблонов). Внешние скрипты всё равно запрещены — вектор инъекции чужого кода не открывается; компенсация — поведенческий гейт `tests/js/vue_mount_test.js` (реальная компиляция шаблона загруженным бандлом + симуляция CSP-запрета `Function`).

## 4a. Ревью-итерация 1: выбор CSP-варианта (Critical: CSP ломал Vue)

Первый вариант `script-src 'self'` отклонён @Reviewer: self-host — full-сборка
`vue.global.prod.min.js` (в ней `Function(l)()` внутри `compileToFunction`),
поэтому под строгим CSP монтирование падало с `EvalError`. Выбран **вариант A**
(`'unsafe-eval'`) как минимально-рискованный: вариант B (runtime-only сборка +
`h(...)`) потребовал бы переписать весь in-DOM канон (`#app` ~2900 строк) и оба
`template:`-селектора. Поведенческий smoke (T-1659) компилирует реальный шаблон
загруженным бандлом и проверяет, что компиляция опирается на `Function`
(симуляция CSP-запрета → `EvalError`), а также отсутствие inline-скриптов и
внешних ресурсов.

- (−) Появляется build-step для Tailwind CSS (offline, результат коммитится) и обязанность обновлять пин-версии vendor-бандлов.
- (−) Риск пропуска динамических Tailwind-классов → компенсируется `safelist` + мобильный smoke.
- Не решает top-level DNS-резолв домена — это серверная зона (@DevOps, чек-лист в спеке §7).
- Инварианты: `media/`/`.env` не тронуты, порядок роутеров `bot.py` не тронут, каталог-Δ=0, `WEBAPP_URL` не меняется.
