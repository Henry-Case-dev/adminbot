# Фича F1 — `betterstack-ingest-bearer-contract` (BetterStack: ingest-контракт `POST https://{host}` + `Authorization: Bearer`, снятие ложного WARNING token==SENTRY_DSN public key)

> **Статус: ⏳ PLANNED** (Step 1 @PM, 15.09.2026). Реализация — @Builder (T-1780…T-1787); гейты T-1778 (@Architect) / T-1779 (@DevOps, curl-матрикс) / T-1788 (@Reviewer/@PM).
> **Spec/ADR:** создаёт @Architect — `spec.md` + **ADR-1019-1** (**AMEND ADR-1018-1 D2/D4/D8**).
> **Раунд:** 10.19 (UPD2, `plans/current_task.md:130-175`). **Нумерация:** T-1778…T-1788 (продолжает T-1777).
> **Тип:** backend/infra (`services/betterstack_handler.py`, `bot.py`, `tests/`, `.env.example`, docs). **Приоритет:** **P0** (телеметрия уходит в никуда, >1000 неотправленных логов).
> **Зависимости:** — (инфра-плоскость, может идти параллельно всем). **Конфликт файлов:** `config/settings.py` (только если Δ каталога — не ожидается), `tests/test_betterstack_handler.py`, `tests/test_monitoring_smoke.py`.
> **ТЗ:** UPD2 **п.2** (`plans/current_task.md:133-149`) + контекст чекапа (строка 156).
> **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; прод `release-round1018` (`16a8c0b`, PID 2319614); каталог **436/406/411/90/88/19**; SQLite **v10**; APP_VERSION 2.57.0.

## 0. Цель

Заменить неверный ingest-контракт собственного `BetterStackHandler` (токен в **пути** `https://{host}/{token}`, без авторизации) на актуальный контракт BetterStack: `POST https://{ingesting_host}` + заголовок `Authorization: Bearer {source_token}`. Снять/переформулировать ложный стартовый WARNING «token == public key SENTRY_DSN» (на унифицированных US-кластерах Source Token для Telemetry побайтово совпадает с Public Key — это **норма**, владелец подтвердил скриншотами). Обновить `_HINT_401`, тесты, docs и ADR.

**Требуется (UPD2 п.2, `plans/current_task.md:133-149`):**
- Логи уходят POST-запросом строго на US-ingesting-host (значение — только в `.env`; в репо не вносить).
- Токен — **абсолютно верный** (владелец подтвердил), причина 401 — не токен, а контракт запроса/роутинг.
- Посылка ТЗ о `logtail-python` — **фактически неверна**: библиотека в проекте отсутствует (`requirements.txt`, импорты), прод-путь — собственный `services/betterstack_handler.py` (см. §1, §7).
- Прекратить ссылаться на «неверный токен»; исправить контракт, задеплоить, проверить логи рестарта.

## 1. Доказательства / карта кода (HEAD `fd6acc7`)

- `services/betterstack_handler.py:157` — `self._url = f"https://{host}/{self.source_token}"` (токен в **пути**).
- `services/betterstack_handler.py:232-241` — `urllib.request.Request(..., headers={"Content-Type", "User-Agent"})` — **нет `Authorization`**.
- `services/betterstack_handler.py:60-62` — `_HINT_401` содержит указание «токен — Source Token, а не public key из SENTRY_DSN».
- `services/betterstack_handler.py:82-93` — `token_equals_sentry_public_key` (constant-time сравнение token с userinfo `SENTRY_DSN`).
- `services/betterstack_handler.py:22-24` — докстринг «это должен быть Source Token, а НЕ public key».
- `bot.py:190-195` — стартовый `WARNING` при `token == SENTRY_DSN public key`.
- `bot.py:141-145,151-159` — создание `BetterStackHandler(host=...)` (раунд 10.18: host обязателен из env).
- `services/betterstack_handler.py:51` — `DEFAULT_HOST = ""` (ADR-1018-1 D2).
- **Отсутствие библиотеки:** `logtail-python` в `requirements.txt` **нет**, импортов нет → правки «конструктора LogtailHandler/`endpoint=`» неприменимы (артефакт-тест `tests/test_monitoring_smoke.py:17,57` — проверить, что он не библиотечный, или убрать).
- **Официальный контракт US:** `POST https://{ingesting_host}` + `Authorization: Bearer {source_token}`; ответы: **202** ok / **402** quota / **403** invalid token / **406** bad body.

## 2. Требования

- [x] URL запроса — **без токена в пути**: `https://{host}` (хост из `BETTERSTACK_HOST`, значение не хардкодить).
- [x] Заголовок `Authorization: Bearer {source_token}` в каждом POST.
- [x] Обработка кодов ответа: 202 — успех; 402 — квота; 403 — неверный токен; 406 — битое тело; все 4xx (включая 429) — не ретраить; 5xx/транспорт — политика повтора (≤1) сохранена.
- [x] `_HINT_401` переформулирован → удалён, заменён словарём `_STATUS_HINTS` (без утверждения «token == public key = ошибка»); R17-safe (без значений токена/URL).
- [x] `token_equals_sentry_public_key`: **не** выдавать WARNING «это не Source Token» (на unified US совпадение — норма) — понижено до DEBUG; старт не блокируется.
- [x] `bot.py` стартовая диагностика согласована (attached/skipped, token_len — R17; без last4).
- [ ] Обязательный **curl-матрикс ДО правки** (T-1779): `{token-in-path, Bearer} × {US, EU}`; вывод — **только HTTP-код** (маскированный, R17); фиксирует, какая комбинация даёт 202. **= @DevOps (прод-кредам; @Builder обновил скрипт, живых запросов не слал).**
- [x] `.env.example` и docs обновлены (плейсхолдеры, без реального хоста/токена); README/ARCHITECTURE — без overclaim.
- [x] Тесты: отсутствие токена в URL, наличие `Authorization: Bearer`, матрица статусов, «token==pubkey не WARNING», R17 (нет токена в логах/подсказке).

## 3. Constraints (инварианты раунда)

- **R17:** токены/URL с токеном **не** логировать, не коммитить, не вносить в спеки/ADR/отчёты/KG. Вывод диагностики — только HTTP-коды.
- **R16** (id — ключ) — если добавляются поля статуса, только аддитивно.
- **Каталог:** ожидается **Δ=0** (ключ `BETTERSTACK_HOST` уже введён в 10.18, F1). Любой Δ — только через human-gate (санкция владельца).
- **Порядок роутеров `bot.py` не менять** (только DI-строки хендлера); `media/`/`.env` **не трогать** (в git — только `.env.example`).
- **Ревью-гейты:** полный `pytest` 0 регрессий; `node --check web/app.js`; `git diff --check`; русские conventional commits.
- **Библиотеку `logtail-python` не добавлять/не трогать** — прод-путь иной.

## 4. Зависимости / порядок

- **Вверх:** T-1778 (@Architect, ADR), T-1779 (@DevOps, live curl-матрикс) — обязательны **до** правки кода.
- **Вниз:** релиз 10.19; F3/F4 (каталог-Δ) — свести Δ.
- **Порядок:** может идти параллельно F2/F5/F6/F7/F8 (разные файлы). Деплой — @DevOps (`.env` + рестарт).

## 5. Definition of Done

- [x] POST уходит на `https://{host}` **без** токена в пути и с `Authorization: Bearer`.
- [x] Ответы 202/402/403/406 обрабатываются; ретраи/rate-gate сохранены; буфер не теряет логи при 401.
- [x] Ложный WARNING «token == public key» снят/переформулирован (DEBUG); `_STATUS_HINTS` актуален и R17-safe.
- [ ] curl-матрикс зафиксирован (маскированно) и объясняет причину 401 до правки. **= T-1779 (@DevOps, прод).**
- [x] Полный `pytest` **0 failed** (6155 passed; **6164** после ревью-фиксов D-01…D-05); каталог **Δ=0**; R17-скан чист; `git diff --check` clean.
- [x] ADR-1018-1 D2/D4/D6/D8 помечены **AMEND**; противоречие раунда 10.18 снято.

## 6. Чек-лист задач

- [x] **T-1778 (@Architect, гейт):** `spec.md` + **ADR-1019-1** — AMEND ADR-1018-1 D2 (host/URL), D4 (token==pubkey — не ошибка), D8 (curl-матрикс: `{path-token, Bearer}×{US,EU}`); контракт `POST https://{host}` + `Bearer`; семантика 202/402/403/406; судьба `token_equals_sentry_public_key`; обновление `_HINT_401`/docs; список тестов.
- [ ] **T-1779 (@DevOps, гейт):** живой curl-матрикс на прод-кредах — 4 комбинации `{token-in-path, Bearer} × {US, EU}`; в отчёт — **только HTTP-коды** (R17); ожидание: 202 лишь на (US × Bearer). Артефакт — evidence для ADR. **@Builder подготовил скрипт `scripts/betterstack_host_token_probe.py` (Bearer-контракт, маска, `--dry-run`); реальные запросы — за @DevOps.**
- [x] **T-1780 (@Builder):** `services/betterstack_handler.py` — `_url = f"https://{host}"` (без токена) + заголовок `Authorization: Bearer {source_token}` в `_post`.
- [x] **T-1781 (@Builder):** обработка статусов 202/402/403/406 → reason-коды + rate-limited WARNING (R17); все 4xx (включая 429) не ретраить; 5xx/транспорт — политика (≤1 повтор) сохранена.
- [x] **T-1782 (@Builder):** `token_equals_sentry_public_key` — снять WARNING → DEBUG (решение ADR D4); диагностируемость сохранена; значения не логируются.
- [x] **T-1783 (@Builder):** `_HINT_401` удалён → словарь `_STATUS_HINTS` (контракт Bearer/регион/валидность токена/квота/тело); неверное утверждение про public key убрано.
- [x] **T-1784 (@Builder):** `bot.py:135-205` — стартовая диагностика/комментарии согласованы с новым контрактом; маркер `attached`/`skipped` без секретов; token==pubkey → DEBUG.
- [x] **T-1785 (@Builder):** тесты — URL без токена; наличие `Authorization: Bearer`; матрица 202/402/403/406; регресс буфера/ретраев; «token==pubkey не WARNING»; R17 (токен не в логах/тексте подсказки).
- [x] **T-1786 (@Builder):** `.env.example` + docs/README/ARCHITECTURE-ссылки; `logtail-python` в `requirements.txt` отсутствует (не добавлялся); `tests/test_monitoring_smoke.py` актуализирован.
- [x] **T-1787 (@Builder):** гейты — полный `pytest` **6155 passed / 0 failed**; каталог Δ=0; `node --check`/`routing_test`/`vue_mount_test` OK; `git diff --check` clean. Коммит — отдельным шагом @Orchestrator/@DevOps.
- [x] **T-1789 (@Builder, ревью Бата A — D-01…D-05):** D-01 — запросы через opener с `_NoRedirectHandler` (3xx не фоллоуится: токен не форвардится на `Location`, POST-тело не теряется, ложного `sent` нет; 302/307 → `_mark_failed`, без ретрая) + регресс-тесты (включая end-to-end локальный 302); D-02 — синхронизирована формулировка ретраев («5xx/транспорт — ≤1; все 4xx, включая 429 — не ретраить») в ADR-1019-1 D3 / spec §3.3/§4.3 / tasks; D-03 — ADR-1018-1 D6/D8 остаточные строки зачёркнуты/переформулированы (`last4` убран, `_HINT_401`→`_STATUS_HINTS`, ожидание 202 на US×Bearer); D-04 — inline-пометка AMEND в §39/10.18 + @DevOps-гейт; D-05 — ARCHITECTURE §18 (строка о F-15 §4) `reason=invalid_json`→`not_json` (синхронизация с кодом/ADR-1019-7 D4). Гейты: pytest **6164 passed / 0 failed**; `node --check`/routing/vue_mount OK; `git diff --check` clean.
- [ ] **T-1788 (@Reviewer + @PM, гейт):** сверка DoD; согласованность кода ↔ ADR-1019-1; R17-аудит (никаких значений токена/URL); проверка снятия противоречия 10.18; повторное ревью фиксов D-01…D-05.

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | **ADR-1018-1 D4** прямо требует WARNING при `token==pubkey` | **AMEND** (ADR-1019-1): на unified US совпадение — норма; UPD2 п.2 + скриншоты владельца |
| R2 | **ADR-1018-1 D8** фиксировал матрикс `{US,EU}×{Source Token, public key}` | **AMEND**: матрикс `{path-token, Bearer}×{US,EU}` (проверяет контракт, а не «верность» токена) |
| R3 | **ADR-1018-1 D2** (host обязателен) остаётся в силе | Не меняется; AMEND только URL-форма |
| R4 | ТЗ ссылается на `logtail-python`/`endpoint=` — библиотеки нет | Задокументировать в ADR/spec; правку делать в собственном хендлере |
| R5 | Возможен регресс доставки логов при смене контракта | T-1779 evidence до правки + T-1765 тесты + @DevOps live-проверка рестарта |
| R6 | Утечка значения токена/хоста в отчёты/логи | R17: только HTTP-коды/`token_len`; скан `git diff` на секреты |
| R7 | `_HINT_401` может снова ввести в заблуждение | Формулировка без категоричных утверждений; T-1788 аудит |

**ADR:** требуется новый **ADR-1019-1** (AMEND ADR-1018-1 D2/D4/D8).

## 8. Feature flag / progressive delivery

- **Feature flag НЕ вводится** (инфра-контракт логирования; OFF-ветка = повторный 401). Переключение — деплой + рестарт.
- **Rollback:** `git revert` + возврат `.env` (при необходимости) + рестарт; прежний контракт (path-token) снова даст 401 — мониторинг временно деградирует, что видно по ERROR `[betterstack] disabled`/счётчикам.
- **Progressive delivery:** неприменимо. Live-проверка @DevOps: `attached`-маркер + отсутствие `send failed status=401` в логах рестарта.

## 9. Handoff / деплой

`@Orchestrator` — план F1 готов. Spec/ADR — T-1778 (@Architect). Evidence — T-1779 (@DevOps. Реализация — T-1780…T-1787 (@Builder). **Деплой (SSH `git pull --ff-only` + `.env` (значение хоста/токена — только на сервере) + `systemctl restart admin_bot` + проверка журнала рестарта) — отдельный шаг @DevOps. Секреты в репозиторий НЕ вносить.**
