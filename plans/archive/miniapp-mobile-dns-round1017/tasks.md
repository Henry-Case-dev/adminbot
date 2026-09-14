# Фича F1 — `miniapp-mobile-dns-round1017` (Мобильный мини-апп: `ERR_NAME_NOT_RESOLVED` на Android)

> **Статус: ✅ COMPLETED** (14.09.2026; @Reviewer **APPROVED**, итерация 2; @Scanner **0 C/H/M**). Код-часть реализована, архивировано (Step 8 @PM). Открыты только инфра-гейты @DevOps (T-1667/T-1668/T-1671/T-1673 — DNS/оператор/Private DNS/живой Android-смоук; вне репо), см. §6/§9.
> **Spec:** [`spec.md`](spec.md) — ✅ создан @Architect (Step 2); **ADR:** [`adr-1017-1-miniapp-hostname-dns.md`](adr-1017-1-miniapp-hostname-dns.md) — ✅ создан (hostname/DNS, граница «репо vs инфра», env-only смена домена).
> **Раунд:** 10.17. **Нумерация:** T-1666…T-1674 (продолжает 10.16 → T-1665).
> **Тип:** frontend + infra (диагностика/DNS — @DevOps, вне репо). **Приоритет:** **P0** (прод-блокер: мини-апп не открывается на Android).
> **Зависимости:** нет. **Конфликт файлов:** `config/settings.py`, `handlers/menu.py`, `web/*` (только если найден регресс); конфиг DNS/Caddy — **вне репо**.
> **Эпик:** `Epic: UPD3 багфиксы round1017` (@Memory, Step 0).
> **ТЗ:** `plans/current_task.md`, **UPD3** (строки 155–157): «на десктопе админка запускается, а на мобильном устройстве та же ошибка `net::ERR_NAME_NOT_RESOLVED`. Эти проблемы начались после последних изменений… Найди что могло повлиять» + **UPD2 §4** (строка 153, «~1 минута»).
> **Baseline:** HEAD `772f192`; pytest **5936 passed / 0 failed**; каталог **435/406/411/90/88/19** (Δ=0); SQLite **v9**; прод `eb3fd4a` / PID **1976836**; APP_VERSION 2.57.0.

## 0. Цель

Мини-апп на **десктопе** открывается, на **Android** — `net::ERR_NAME_NOT_RESOLVED`; проблемы начались после ТЗ 10.13–10.16.

**Установлено (@Memory Step 0 / recon):**
- `WEBAPP_URL` (`config/settings.py:171-173`, дефолт `https://admin-bot.duckdns.org/web/`) и `MEDIA_PUBLIC_BASE_URL` (`config/settings.py:987-989`, `https://admin-bot.duckdns.org`), кнопка `/menu` (`handlers/menu.py:48-66`), а также домен/схема/путь **не менялись** в 10.13–10.16 (git-история).
- В `web/` внешних CDN больше нет (self-host 10.16, ADR-1016-2) → субресурсы не могут быть причиной `ERR_NAME_NOT_RESOLVED`.
- `ERR_NAME_NOT_RESOLVED` — сбой резолва **топ-домена `admin-bot.duckdns.org`** у Android-клиента (не субресурс).

**Гипотезы:** блокировка домена `duckdns.org` мобильными операторами; протухшая/пустая запись DuckDNS (A→`198.46.175.136`, AAAA отсутствует); Android Private DNS/DoH; стухший кэш DNS.

**Цель:** диагностика (чек-лист @DevOps + живой Android-смоук) и устранение причины; кодовые правки — только если подтверждён регресс в репо. **Внешние CDN не возвращать.**

## 1. Доказательства (`file:line` на HEAD `772f192`)

- `config/settings.py:170-173` — `WEBAPP_URL` дефолт `https://admin-bot.duckdns.org/web/` (не менялся в 10.13–10.16).
- `config/settings.py:987-989` — `MEDIA_PUBLIC_BASE_URL` дефолт `https://admin-bot.duckdns.org`.
- `handlers/menu.py:48-66` — `/menu` → `WebAppInfo(url=url)`; пустой URL → предупреждение без кнопки.
- `plans/ARCHITECTURE.md:150` — 10.16: все внешние ресурсы → self-host `web/static/vendor/`, внешних CDN — **0**.
- `web/app.py` — CSP `_html_response` (`frame-ancestors` Telegram, `connect-src 'self'`) — менять не предполагается.
- Прод: домен `admin-bot.duckdns.org` (DuckDNS + Caddy 2.11.4 + Let's Encrypt), uvicorn `127.0.0.1:8000`; A→`198.46.175.136`, AAAA нет.

## 2. Требования (UPD3 §1–§2, строки 155–157)

- [ ] Подтверждён факт: `ERR_NAME_NOT_RESOLVED` = сбой резолва **топ-домена** у Android-клиента (не субресурс, не CSP, не initData). *(диагноз @Architect/ADR-1017-1; подтверждение в мобильной сети — @DevOps, T-1668)*
- [ ] Проведена диагностика DNS (@DevOps): публичные резолверы, мобильная сеть/операторы, A/AAAA/CNAME, Private DNS/DoH, кэш.
- [x] Исключён регресс в репо: домен/схема/путь `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL`/`menu.py` и внешние ссылки `web/*` не менялись в 10.13–10.16 (evidence: `git diff 708f7df..HEAD -- config/settings.py handlers/menu.py` — 0 строк по WEBAPP_URL/MEDIA_PUBLIC_BASE_URL/duckdns/WebAppInfo; web/index.html/app.js — только self-host 10.16).
- [ ] Если причина в hostname/DNS — предложен и применён фоллбэк (устранение stale AAAA / альтернативный hostname / второй DNS-провайдер) **вне репо** (@DevOps) с ADR.
- [ ] Живой Android-смоук: мини-апп открывается полностью (initData/authLocked проходит), загрузка без «~1 минуты».
- [x] Регресс-гейт: статическая проверка отсутствия внешних CDN и консистентности absolute URL (`tests/test_webapp_dns_round1017.py`, T-1672).

## 3. Constraints (инварианты раунда)

- **Не возвращать внешние CDN** (self-host 10.16 сохраняется; ADR-1016-2 в силе).
- `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL` менять только при подтверждённом решении о смене hostname (ADR); путь `/web/` и схема `https` — сохранить.
- **Caddy/DNS — вне репозитория** → изменения на сервере выполняет **@DevOps**; в репо — только диагностический артефакт/инструкция.
- Каталог-инварианты **435/406/411/90/88/19** — **Δ=0**; **SQL/DDL не требуется**.
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**; **R17** (секреты `{configured,last4}`, без URL/секретов в логах); **R16** (id — ключ).
- Сохранять `node --check web/app.js` clean и `node tests/js/routing_test.js` → `JS-UNIT-OK`.
- **Ревью-гейты:** полный `pytest` 0 регрессий, JS-гейты, `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** нет. **Вниз:** F4 (отмена ротации — док), релиз 10.17.
- **Порядок:** можно параллельно с F2/F3 (разные плоскости: infra vs backend vs frontend), но диагностический гейт — первым.

## 5. Definition of Done

- [ ] Android-резолв `admin-bot.duckdns.org` стабилен (несколько операторов/сетей); `dig`/`curl` из мобильной сети — OK.
- [ ] Нерабочие/пустые DNS-записи (AAAA/stale A) устранены; Private DFS/DoH-совместимость подтверждена.
- [x] Регресс в репо исключён (или исправлен) с доказательствами diff/grep; внешних CDN нет.
- [ ] Живой Android-смоук пройден (скриншот/лог); мини-апп грузится без `ERR_NAME_NOT_RESOLVED`.
- [x] Полный `pytest` **0 failed** (6007 passed); каталог **Δ=0** (435/406/411/90/88/19); JS-гейты чистые (`JS-UNIT-OK`); R17-скан чист.

## 6. Чек-лист задач

- [ ] **T-1666 (@Architect, гейт):** spec.md + ADR-1017-1 — диагностический план DNS (резолверы/операторы/Private DNS), граница «репо vs инфра», критерий подтверждения регресса, вариант фоллбэка hostname.
- [ ] **T-1667 (@DevOps):** DNS-чек-лист: `dig A/AAAA/CNAME admin-bot.duckdns.org` (@8.8.8.8/@1.1.1.1/@9.9.9.9), запись DuckDNS (A→сервер, stale/пустой AAAA), LE-сертификат/срок, доступность Caddy; отчёт (вне репо).
- [ ] **T-1668 (@DevOps):** Android-диагностика в мобильной сети: Private DNS off/auto, сброс кэша/авиарежим, ≥2 оператора, `curl -I https://admin-bot.duckdns.org/web/`; фиксация класса ошибки (блокировка/пусто/DoH).
- [x] **T-1669 (@Builder):** регресс-аудит репо: git-история и текущее состояние `config/settings.py:170-173,987-989`, `handlers/menu.py:48-66`, `web/*` (внешние ссылки); доказательство «не менялось» или найденный регресс.
- [x] **T-1670 (@Builder):** если регресс найден — минимальный фикс (домен/схема/путь/ссылка) без возврата CDN; иначе — задокументированный no-op с evidence.
- [ ] **T-1671 (@DevOps):** фоллбэк hostname/DNS (второй DNS-провайдер / альтернативное имя / устранение блокируемого `duckdns.org`) — вне репо, при подтверждении гипотезы блокировки; ADR + инструкция.
- [x] **T-1672 (@Builder):** регресс-гейт: статический тест (нет внешних CDN в `web/index.html`/`app.js`; консистентность absolute URL `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL`) — новый или расширение существующего.
- [ ] **T-1673 (@Builder + @DevOps):** живой Android-смоук на реальном устройстве: /menu → WebApp открывается, проходит auth, грузится без «~1 минуты»; скриншот/лог.
- [ ] **T-1674 (@Reviewer + @PM, гейт):** сверка DoD, подтверждение отсутствия регресса/внешних CDN, закрытие или эскалация инфра-гипотезы.

## 7. Открытые вопросы (@Architect → владелец)

- Мигрировать ли с `duckdns.org` на собственный домен (устойчивость к блокировкам) или достаточно починить DNS-запись?
- Нужен ли второй DNS-провайдер/альтернативный hostname как постоянный фоллбэк (или только как диагноз)?
- Требуется ли диагностический эндпоинт/лог в репо для отслеживания резолва, или достаточно чек-листа @DevOps?
- Кто выполняет живой Android-смоук (владелец/@DevOps) и какой оператор/устройство эталонны?

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (инфра-фикс, вне репо); rollback — DNS/Caddy откат (@DevOps).
- **Progressive delivery:** возможен канареечный hostname/sub-path на уровне Caddy/DNS (вне репо, @DevOps). Мониторинг: ошибки резолва у пользователей, время до интерактива.

## 9. Отчёт @Builder (Step 4, 14.09.2026)

**Изменённые файлы:**
- `web/app.py` — `_startup_diag()` (host/scheme/path, R17) + вызов в `create_app`; явные
  `HEAD /web/`, `HEAD /web/index.html`; unauth `GET /healthz` (JSON + `no-store`) и `HEAD /healthz`.
  Порядок роутов сохранён (до `app.mount("/web")`); `bot.py` НЕ тронут.
- `handlers/menu.py` — в `[menu] sent` добавлен `host=<hostname>` (host-only, R17).
- `tests/test_webapp_dns_round1017.py` — новый регресс-гейт: HEAD/CSP/no-store,
  `/healthz` GET+HEAD unauth, статический скан `web/**` (нет внешних CDN),
  консистентность absolute-URL, startup-лог host-only.
  **Ревью-итер.1:** `HEAD /healthz` повторяет `content-type` GET (L4); скан
  расширен на `web/static/vendor/**` (6 бандлов, L2); `version` в `/healthz`
  — осознанное info-disclosure по спеке (L8, без секретов/PII).

**Инварианты:** каталог 435/406/411/90/88/19 (Δ=0); SQL не менялся; `media/`, `.env` не тронуты;
порядок роутеров `bot.py` не менялся; внешние CDN не возвращались; R17/R16 соблюдены.

**Прогоны:** `node --check web/app.js` → OK; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
`.venv/Scripts/python.exe -m pytest -q` → **6007 passed / 0 failed**; `git diff --check` → OK.

**Δ-обоснование T-1669/T-1670 (no-op):** `git diff 708f7df..HEAD -- config/settings.py handlers/menu.py`
не содержит изменений строк `WEBAPP_URL`/`MEDIA_PUBLIC_BASE_URL`/`duckdns`/`WebAppInfo` — домен/схема/путь
и привязка кнопки не менялись в 10.13–10.16; в `web/**` внешних CDN нет (ADR-1016-2 в силе). Регресс в репо
не подтверждён → фикс не требуется, добавлены только диагностические артефакты (T-1672).

**Чек-лист @DevOps (вне репо, открыт; spec §5):**
1. `dig A/AAAA/CNAME admin-bot.duckdns.org @8.8.8.8 @1.1.1.1 @9.9.9.9` — A→`198.46.175.136`, AAAA пусто.
2. DuckDNS: актуальная A, отсутствие/устранение stale AAAA, TTL 300–600.
3. Android ≥2 оператора: `curl -I https://admin-bot.duckdns.org/healthz` (DNS vs TLS).
4. Private DNS/DoH: off/auto, класс ошибки (`blocked`/`empty`/`DoH`).
5. Caddy/LE: `curl -I /web/` (200, CSP), `notAfter`, `encode zstd gzip`; разрешить `/healthz`.
6. При подтверждении блокировки `duckdns.org` — фоллбэк hostname (ADR-1017-1 §4, env-only).
7. Живой Android-смоук (T-1673): `/menu` → WebApp, initData/auth, без «~1 минуты».
