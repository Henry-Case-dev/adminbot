# Фича F5 — `warnings-hygiene-round1017` (WARNING в `avatars.py` + «brotli» / инфра-сжатие)

> **Статус: ✅ COMPLETED** (14.09.2026; @Reviewer **APPROVED**, итерация 2; pytest **6007 passed / 0 failed**; каталог Δ=0). Гейт T-1702 (@Reviewer/@PM) закрыт; открыт только @DevOps-гейт T-1699 (подтверждение `zstd+gzip` в Caddy); brotli — WONTFIX.
> **Spec:** [`spec.md`](spec.md) — ✅ создан @Architect (Step 2). **ADR:** не требуется (brotli — WONTFIX с обоснованием в спеке).
> **Раунд:** 10.17. **Нумерация:** T-1696…T-1702 (продолжает T-1695).
> **Тип:** backend (гигиена логов) + docs/infra. **Приоритет:** **P2/P3** (не блокер).
> **Зависимости:** — (независима; Caddy-часть — @DevOps, вне репо). **Конфликт файлов:** `web/api/avatars.py`, `tests/*` (аддитивно), docs/`scripts/requirements-font.txt` (только чтение).
> **Эпик:** `Epic: UPD3 багфиксы round1017` (@Memory, Step 0).
> **ТЗ:** `plans/current_task.md`, **UPD3** (строка 160): «3 перехваченных WARNING в аватарах (старый код); «brotli» требует плагина Caddy — обработать.»
> **Baseline:** HEAD `772f192`; pytest **5936 passed / 0 failed**; каталог **435/406/411/90/88/19** (Δ=0); SQLite **v9**.

## 0. Цель

1. **3 перехваченных WARNING в `web/api/avatars.py`** (старый код): генеральный `except Exception` + `exc_info=True` шумит ожидаемыми сбоями (нет аватара/нет прав/get_chat). Требуется классифицировать и приглушить/сузить, не теряя реальные ошибки.
2. **«brotli»:** в репозитории `brotli` присутствует **только build-time** (шрифтовый субсет, `scripts/requirements-font.txt`, OD17 — в runtime не входит). В Caddy brotli требует плагина (`xcaddy` / `http.encoders.brotli`), тогда как `zstd`+`gzip` уже включены @DevOps в 10.16. Требуется зафиксировать решение (оставить zstd+gzip как достаточное **или** добавить brotli через `xcaddy`) и снять неопределённость.

## 1. Доказательства (`file:line` на HEAD `772f192`)

- `web/api/avatars.py:146-148` — `except Exception: logger.warning("[avatar] fetch failed …", exc_info=True)` (ожидаемо: фото нет/бот без прав).
- `web/api/avatars.py:180-182` — `except Exception: logger.warning("[avatar] get_chat failed …", exc_info=True)`.
- `web/api/avatars.py:208-211`, `:220-223` — `logger.warning(..., exc_info=True)` в `user_display_info`/related.
- `web/api/avatars.py:139-145`, `:262-269`, `:283-290` — транзиентные ветки (`TelegramRetryAfter`/`TelegramNetworkError`) уже обрабатываются отдельно и **не** кэшируют негатив; `safe_exc_text` (:154-157) маскирует.
- **brotli:** `plans/ARCHITECTURE.md:465,499` — `fontTools`/`brotli` **build-time only** (`scripts/requirements-font.txt`), в runtime `requirements.txt` нет (grep по репо: brotli только в `plans/` + `.venv` aiohttp-декодер).
- **Caddy:** `plans/backlog.md:43-44` (10.16 гейт T-1657: «Caddy `encode zstd gzip` включено»); `plans/archive/miniapp-mobile-round1016/adr-1016-2-selfhost-csp.md:16` — сжатие gzip/brotli на Caddy (вне репо).
- `plans/archive/miniapp-mobile-round1016/tasks.md:81` — T-1657 (прод-проверка сжатия/CSP) — @DevOps.

## 2. Требования (UPD3 §5, строка 160)

- [x] 3 WARNING в `avatars.py` обработаны: ожидаемые сбои не логируются как WARNING с трейсом; реальные — остаются диагностируемыми (R17: без секретов).
- [x] Политика исключений зафиксирована (какие ошибки ожидаемы → debug/один раз; какие → WARNING).
- [x] «brotli»: явное решение — оставить build-time-only + Caddy `zstd gzip` (documented) **или** включить brotli через `xcaddy`/`http.encoders.brotli` (@DevOps, вне репо).
- [x] Отсутствие регрессов API-аватаров (кэш негатива, транзиентные ветки, same-origin прокси `/api/avatar`).
- [x] Документация не вводит в заблуждение (brotli не заявлен как runtime-зависимость/уже включённый в Caddy).

## 3. Constraints (инварианты раунда)

- **R17:** логи — без токенов/URL/трейсов с секретами; `safe_exc_text`/`{configured,last4}` сохранить.
- **SQL/DDL не требуется**; каталог-инварианты **435/406/411/90/88/19** — **Δ=0**.
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- **Caddy — вне репозитория** → изменения выполняет **@DevOps**; в репо — только доки/инструкция.
- Не ломать CSP/аватары self-host (10.16, ADR-1016-2); `node --check web/app.js` (если затронут фронт — нет).
- **Ревью-гейты:** полный `pytest` 0 регрессий, R17-скан, `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** нет. **Вниз:** релиз 10.17.
- **Порядок:** после F1/F2/F3 (гигиена, не блокер).

## 5. Definition of Done

- [x] 3 WARNING-сайта `avatars.py` приведены к политике; тесты (caplog) доказывают: ожидаемое — не WARNING с трейсом, неожиданное — логируется без секретов.
- [x] Поведение аватаров не изменилось (кэш/негатив/транзиент/прокси) — регресс-тесты зелёные.
- [x] По «brotli» зафиксировано решение: обновлён docs/`plans/` (build-time only) и, при выборе brotli, отчёт @DevOps о `xcaddy`.
- [x] Полный `pytest` **0 failed**; каталог **Δ=0**; R17-скан чист.

## 6. Чек-лист задач

- [ ] **T-1696 (@Architect, гейт):** spec.md — классификация 3 WARNING (ожидаемые/неожидаемые), политика уровня логов, решение по brotli (build-time only + zstd/gzip vs `xcaddy`), критерии R17.
- [x] **T-1697 (@Builder):** `web/api/avatars.py` — сузить/разметить генеральные `except` (фото нет/нет прав/`TelegramBadRequest` ожидаемые → без `exc_info`/debug; неожидаемые → WARNING с `exc_info`), сохранить `safe_exc_text` и кэш-семантику. **Ревью-итер.1 (M2):** транзиентные ветки `(TelegramRetryAfter, TelegramNetworkError)` добавлены и в `chat_display_info`, и в `user_display_info` (member+photos) — WARNING без трейса, негатив НЕ кэшируется; политика spec §3 теперь на всех 6 сайтах.
- [x] **T-1698 (@Builder):** тесты — caplog на 3 сайта (ожидаемый путь не пишет трейс; неожидаемый — пишет класс без секретов); не сломать существующие avatar-тесты. **Ревью-итер.1:** +2 теста транзиентов (`chat_display_info`, `user_display_info`) с проверкой «не кэшируется» и «WARNING без трейса».
- [ ] **T-1699 (@DevOps):** решение по Caddy brotli (вне репо): либо подтвердить `zstd+gzip` достаточным, либо собрать Caddy с `xcaddy` + `http.encoders.brotli`; отчёт.
- [x] **T-1700 (@Builder):** доки — зафиксировать build-time-only `brotli` (`scripts/requirements-font.txt`) и статус Caddy-сжатия; убрать возможные overclaim-упоминания.
- [ ] **T-1701 (@Builder):** гейты: полный `pytest` **0 failed**, каталог Δ=0, R17-скан, `git diff --check`; русский commit.
- [ ] **T-1702 (@Reviewer + @PM, гейт):** сверка DoD, R17, отсутствие регресса аватаров; подтверждение решения по brotli.

## 7. Открытые вопросы (@Architect → владелец)

- Какие из 3 WARNING считать ожидаемыми (допустимо `debug`), а какие оставить `WARNING`?
- Нужно ли логировать unhandled-ошибку аватара один раз (rate-limit) или каждый раз?
- Достаточно ли `zstd+gzip` в Caddy, или включать brotli ради экономии байт (стоимость: `xcaddy`-сборка, вне репо)?
- Нужен ли общий helper «expected Bot API failure» или точечные правки в `avatars.py`?

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (гигиена логов + инфра-решение). Rollback = `git revert` (код) / откат Caddy (@DevOps).
- **Progressive delivery:** неприменим; проверка — `pytest` (caplog) + прод-логи `[avatar]` после деплоя.
