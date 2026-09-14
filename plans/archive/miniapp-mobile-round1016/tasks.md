# Фича F4 — `miniapp-mobile-round1016` (Мини-апп: мобильный запуск, CDN/CSP, минификация)

> **Статус: ✅ COMPLETED** (14.09.2026; @Reviewer APPROVED, итерация 2): T-1652…T-1656, T-1658, T-1659 —
> self-host (Telegram SDK/Vue/Chart.js), предсобранный Tailwind CSS, external
> `telegram-init.js`, CSP `script-src 'self' 'unsafe-eval'` (вариант A ревью-
> итер.1: full-сборка Vue использует `Function()`; см. ADR-1016-2 §4a), вынос
> `<style>` в `app.css`.
> Открыт гейт **T-1657 (@DevOps)**: прод-проверка Caddy/DNS, LE, сжатие, CSP.
> **Spec:** [`spec.md`](spec.md) · **ADR:** [`adr-1016-2-selfhost-csp.md`](adr-1016-2-selfhost-csp.md).
> **Раунд:** 10.16. **Нумерация:** T-1651…T-1659.
> **Тип:** frontend + infra. **Приоритет:** **P1**.
> **Зависимости:** нет (независима от F1–F3; серверная часть Caddy/DNS — @DevOps, вне репо).
> **Конфликт файлов:** `web/index.html`, `web/app.js`, `web/static/vendor/*`, `handlers/menu.py` (только при необходимости), конфиг Caddy (**вне репо**).
> **Эпик:** `Epic: Багфиксы + полный аудит round1016`.
> **ТЗ:** `plans/current_task.md`, **UPD2** (строка 153: `ERR_NAME_NOT_RESOLVED` на Android, десктоп ок; «~1 минута» загрузки).
> **Baseline:** HEAD `18a9aa1`; pytest **5774 passed / 0 failed**; каталог **435/90/406/411/88/19** (Δ=0); APP_VERSION 2.57.0.

## 0. Цель

Мини-апп не запускается на **Android** с `net::ERR_NAME_NOT_RESOLVED`, при этом на десктопе работает; часть пользователей ранее ждала загрузку **~1 минуту**.

Конфигурация: `WEBAPP_URL = https://admin-bot.duckdns.org/web/` (`config/settings.py:171-173`), кнопка в `handlers/menu.py:53-63`; DuckDNS + Caddy 2.11.4 + Let's Encrypt (конфиг Caddy **вне репо**); uvicorn `127.0.0.1:8000`.

В `web/index.html` — **блокирующие внешние скрипты**: `telegram.org/js/telegram-web-app.js` (:11), `cdn.tailwindcss.com` (:12), `unpkg.com/vue@3` (:3633), `cdn.jsdelivr.net/npm/chart.js@4` (:3638). Нет CSP/bundle/service worker; `index.html` ~235 КБ + `app.js` ~285 КБ без минификации.

Гипотезы `ERR_NAME_NOT_RESOLVED`: домен не резолвится у Android-оператора/Private DNS, либо падают CDN-хосты; «~1 минута» — таймауты блокирующих CDN + крупные несжатые файлы.

Цель: диагностика DNS домена, self-host внешних CDN (или безопасная замена), CSP, минификация/бандлинг, устранение «~1 минуты»; серверные проверки (Caddy/DNS) — @DevOps.

## 1. Доказательства (`file:line` на HEAD `18a9aa1`)

- `config/settings.py:171-173` — `WEBAPP_URL` дефолт `https://admin-bot.duckdns.org/web/`.
- `handlers/menu.py:53-63` — `/menu` → `WebAppInfo(url=url)` (private), предупреждение при пустом URL.
- `web/index.html:11` — `<script src="https://telegram.org/js/telegram-web-app.js"></script>` (блокирующий).
- `web/index.html:12` — `<script src="https://cdn.tailwindcss.com"></script>` (блокирующий, тяжёлый JIT).
- `web/index.html:3633` — `<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>`.
- `web/index.html:3637` — `<script src="/static/vendor/dompurify-3.4.15.min.js"></script>` (пример self-host!).
- `web/index.html:3638` — `<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>`.
- Размеры: `web/index.html` ≈ 235 073 Б; `web/app.js` ≈ 284 943 Б (без минификации).
- Прецедент self-host: DOMPurify/vis-network (ADR-1013-2) — уже локально.

## 2. Требования (UPD2 §4)

- [x] Диагностика `ERR_NAME_NOT_RESOLVED`: почему домен не резолвится на части Android (DNS/Private DNS); проверка доступности `admin-bot.duckdns.org` (внешний DNS, A-запись, Caddy) — гипотезы в §0 спеки, артефакт-чек-лист §7 (серверная верификация — @DevOps T-1657).
- [x] Self-host внешних CDN (Vue/Chart.js/Tailwind) **или** безопасная замена; убрать блокирующие внешние `<script>` — `web/static/vendor/*` + предсобранный `tailwind.css`.
- [x] CSP-заголовки (приложение + Caddy) без новых сторонних источников — `_CSP_HTML` в `web/app.py`, Caddy-инструкция в §7.
- [x] Минификация/бандлинг `index.html`/`app.js`; уменьшение времени до интерактива — ADR-1016-2: JS-минификация **OUT** (Caddy-сжатие), CSS вынесен в `app.css`, Tailwind предсобран, `?v=` сохранён.
- [x] Диагностика «~1 минуты»: блокирующие CDN-таймауты + крупные несжатые файлы; меры (preload/compress/service worker/кеш) — внешние таймауты устранены self-host, сжатие/кеш — Caddy (@DevOps).
- [ ] Серверные проверки Caddy/DNS — задача **@DevOps** (вне репо) — гейт T-1657.

## 3. Constraints (инварианты раунда)

- **Новых CDN нет:** внешние ресурсы → self-host в `web/static/vendor/` (паттерн DOMPurify/vis-network, ADR-1013-2).
- **Новых `v-html` без санитайза нет** (DOMPurify остаётся).
- Каталог-инварианты **435/90/406/411/88/19** — **Δ=0**; **SQL/DDL не требуется**.
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- Конфиг **Caddy/DNS — вне репозитория** → изменения на сервере выполняет **@DevOps** (в репо — только проверки/инструкция).
- Сохранять `node --check web/app.js` clean и `node tests/js/routing_test.js` → `JS-UNIT-OK`; не ломать hash-router/шаблоны.
- **Ревью-гейты:** полный `pytest` 0 регрессий, JS-гейты, R17-скан; русские commits.

## 4. Зависимости / порядок

- **Вверх:** нет. **Вниз:** F5 (финализация).
- **Порядок:** может идти параллельно с F3 (разные файлы); желательно после F1/F2, чтобы не пересекаться на релизе.

## 5. Definition of Done

- [x] Внешние блокирующие `<script>` (telegram/tailwind/vue/chart) устранены/self-host; CSP активна.
- [x] `index.html`/`app.js` минифицированы/разбиты; измеримое сокращение времени загрузки — по ADR-1016-2 минификация **OUT**: CSS вынесен (`app.css`), Tailwind предсобран, внешние блокирующие таймауты устранены; сжатие — Caddy (@DevOps).
- [ ] Причина `ERR_NAME_NOT_RESOLVED` установлена (DNS/Caddy) и устранена/задокументирована (@DevOps, гейт T-1657): чек-лист §7 спеки.
- [x] JS-гейты чистые; полный `pytest` **0 failed** (5931 passed); каталог **Δ=0**.

## 6. Чек-лист задач

- [x] **T-1651 (@Architect, гейт):** дизайн мобильной доставки: self-host ресурсов, CSP-политика, стратегия минификации/бандлинга, диагностический план DNS/«~1 минута» (spec/ADR-1016-2 готовы).
- [x] **T-1652 (@Builder):** self-host Vue 3 / Chart.js / Tailwind (локальный `web/static/vendor/`) **или** безопасная замена; убрать внешние блокирующие `<script>` (`index.html:11,12,3633,3638`); сохранить версии/лицензии — `vendor/vue.global.prod.min.js` (3.5.42), `vendor/chart.umd.min.js` (4.5.1), `vendor/telegram-web-app.js`, `vendor/tailwind.css` (prebuilt); grep внешних CDN = 0.
- [x] **T-1653 (@Builder):** CSP-заголовки приложения (meta/response) + согласование с Caddy (инструкция @DevOps); не сломать Telegram WebApp/`initData` — `_CSP_HTML` в `web/app.py` (только HTML, не `/api`), `frame-ancestors` для Telegram, inline-скрипт вынесен в `static/telegram-init.js`.
- [x] **T-1654 (@Builder):** минификация/бандлинг `index.html`/`app.js` (сборка/шаблоны), кеш-версионирование (`?v=__APP_VERSION__` сохранить); без потери читаемости исходников — `<style>` → `web/static/app.css?v=`, Tailwind prebuilt (`tailwind.config.js` + `web/static/tailwind.input.css`); JS-минификация OUT по ADR.
- [x] **T-1655 (@Builder):** дизайн/реализация диагностики домена и «~1 минуты»: preload/critical CSS, сжатие, таймауты внешних ресурсов, опц. service worker; безопасные логи — внешние таймауты устранены self-host; сжатие/кеш — Caddy (@DevOps); service worker OUT.
- [x] **T-1656 (@Builder):** серверный диагностический чек-лист для @DevOps (проверка DNS/DuckDNS/A-записи/сертификата Caddy 2.11.4, `curl` с мобильных DNS, MTU) — как артефакт в репо: spec §7.
- [ ] **T-1657 (@DevOps):** прод-проверка Caddy/DNS домена мини-аппа (вне репо): резолв, сертификат, заголовки CSP/сжатие, доступность CDN-замен; отчёт — **гейт открыт**.
- [x] **T-1658 (@Builder):** мобильный смоук (DevTools device emulation + блокировка внешних хостов) — мини-апп грузится без внешних CDN; замер времени до интерактива — статические маркеры `tests/test_smoke_round1016_miniapp_selfhost.py` + `TestStatic` в `tests/test_webapp_api.py` + **поведенческий** `tests/js/vue_mount_test.js` (ревью-итер.1: реальная компиляция шаблона self-host бандлом Vue + CSP-симуляция без `'unsafe-eval'` → `EvalError`) (реальный мобильный смоук — @Reviewer/@DevOps).
- [ ] **T-1659 (@Builder/@Reviewer, гейт):** сверка DoD; `node --check web/app.js` clean, `node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог Δ=0 — **гейт открыт** (проверки пройдены @Builder, финальная сверка — @Reviewer).

## 7. Открытые вопросы (@Architect → владелец)

- Tailwind: self-host CDN-сборки (JIT) vs переход на предсобранный CSS (риск смены вёрстки)? Объём регресс-тестов UI?
- CSP строгость: `'unsafe-inline'` (inline-скрипты в `index.html`) — как обойти без ломки Vue-шаблонов?
- Нужен ли service worker для офлайна/кеша, или достаточно preload+сжатия?
- Допустимо ли временное дублирование CDN (fallback) на период миграции?

## 8. Feature flag / progressive delivery

- **Feature flag:** возможен серверный kill-switch раздачи нового бандла (Caddy/файл-переключатель) — **опционально**; иначе rollback = `git revert` + `systemctl restart`.
- **Progressive delivery:** применим канареечно на уровне Caddy/DNS (например, отдельный sub-path/host) — **вне репо, @DevOps**. Мониторинг: время загрузки, 4xx/5xx, ошибки резолва у пользователей.
