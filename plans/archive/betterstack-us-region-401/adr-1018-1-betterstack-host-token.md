# ADR-1018-1 — BetterStack: политика host/token, разделение с Sentry, рестарт-зависимость `.env`

> **⚠️ AMENDED BY ADR-1019-1** (раунд 10.19, F1 `betterstack-ingest-bearer-contract`):
> **D2** — форма URL меняется с `https://{host}/{token}` (token в path) на
> `https://{host}` + `Authorization: Bearer {token}`; **D4** — совпадение
> token с Sentry public key на unified US перестаёт быть ошибкой (стартовый
> WARNING → DEBUG); **D6** — из диагностики убирается ложный WARNING,
> `_HINT_401` заменён словарём `_STATUS_HINTS`; **D8** — curl-матрикс проверяет
> `{path-token, Bearer} × {US, EU}` (контракт, а не «верность» токена).
> D3/D5/D7 сохраняются полностью (host обязателен из env, Sentry↔BetterStack
> разведены, правка `.env` = рестарт). Полный текст — `plans/features/
> betterstack-ingest-bearer-contract/adr-1019-1-ingest-bearer-contract.md`.

- **Статус:** Proposed → **AMENDED (ADR-1019-1, 15.09.2026, раунд 10.19)**: D2/D4/D6/D8 пересмотрены; D1/D3/D5/D7 в силе. (**подтверждён владельцем, UPD п.4:** «BetterStack (env host) … принимается „как есть“» — решения D2/D3/D4/D5/D6/D7/D8 без изменений; итерация 2, 15.09.2026)
- **Дата:** 2026-09-15
- **Раунд:** 10.18, фича F1 `betterstack-us-region-401` (T-1703)
- **База:** HEAD `118a03c`. **Связано:** T-746 / раунд 5 (`betterstack-lore-prompts-round5`), раунд 4 (`betterstack-own-handler-video-memory-cmds`), ADR-1013-1 (паттерн env-only vs каталог).
- **SUPERSEDE/AMEND:** **AMEND** неявный контракт раунда 4/5 (`DEFAULT_HOST` = EU; «сравнение с `SENTRY_DSN` не делаем»). Не supersede целиком — заменяется только host-политика и стартовая диагностика. **AMEND BY ADR-1019-1:** D2/D4/D6/D8 (см. блок выше).

## Context

1. **Посылка ТЗ неверна.** `LogtailHandler` из `logtail-python` **не используется** в прод-пути с раунда 4. Реальная точка — `bot.py:141-145` → `BetterStackHandler(source_token=os.getenv("LOGTAIL_SOURCE_TOKEN"))`; у хендлера уже есть параметр `host` (`services/betterstack_handler.py:39,99,109`), просто он **не передаётся** → EU-дефолт `in.logs.betterstack.com`.
2. **Регион проекта — US (`us-west-2a`).** US Source Token на EU-ingest даёт `401`, что и наблюдаем (`[betterstack] send failed | reason=status=401`).
3. **Двойная причина 401.** (а) неверный хост (EU вместо US); (б) в раунде 5 уже фиксировался случай, когда в `LOGTAIL_SOURCE_TOKEN` попадал **public key из `SENTRY_DSN`**, а не Source Token. Текущий код сознательно **не** сравнивает (`bot.py:138-140`, `services/betterstack_handler.py:22-23`, `tests/test_betterstack_handler.py:11-14`).
4. **Рестарт-зависимость.** `load_dotenv()` выполняется на импорте, хендлер создаётся на уровне модуля → изменение `.env` **не** подтягивается без `systemctl restart admin_bot`.
5. **Артефакт-противоречие.** `tests/test_monitoring_smoke.py:17,57` до сих пор конструирует библиотечный `LogtailHandler` (без host) — единственный оставшийся код, способный уйти в EU-дефолт.

## Decision

### D1. Точка фикса — только `services/betterstack_handler.py` + DI-строки `bot.py`
Библиотека `logtail-python` в прод-пути не используется и **не трогается**. Единственная точка — наш `BetterStackHandler`.

### D2. Хост — обязательный явный параметр (env), неявный EU-дефолт запрещён
> **AMENDED BY ADR-1019-1:** форма URL — `https://{host}` (токен в path УБРАН)
> + заголовок `Authorization: Bearer {source_token}`. Обязательность host и
> запрет EU-дефолта сохранены.
- `DEFAULT_HOST = ""`; конструктор при пустом `host` → `ValueError`.
- `bot.py` резолвит `host = os.getenv("BETTERSTACK_HOST")`; при пустом — **хендлер не создаётся** + WARNING (fail-safe: не отправлять в неизвестный регион).
- `CHECKUP_BETTERSTACK_SQL_HOST` — **другой контур** (ClickHouse SQL API), вне скоупа ADR.

### D3. Санкционированный Δ каталога: `BETTERSTACK_HOST` (env-only)
Новый ключ в `services/param_catalog.py::_INFRA_ENV_ONLY` (category `None`, `settings_field=None`, `secret=False`): **REGISTRY 435 → 436**; Settings/GROUPS/mapped/TAB_RULES без изменений. Обоснование env-only: прецедент `POSTGRES_DSN`; значение — инфраструктура, не рантайм-тюнинг; нет необходимости в Settings-поле. `.env.example` получает плейсхолдер.

### D4. Source Token vs public key — детерминированная проверка, НЕ эвристика
> **AMENDED BY ADR-1019-1:** на **унифицированных US-кластерах** Source Token
> (Telemetry) побайтово совпадает с public key `SENTRY_DSN` — это **НОРМА**,
> а не ошибка (владелец подтвердил скриншотами). Стартовый WARNING
> понижается до **DEBUG**; функция `token_equals_sentry_public_key` остаётся
> как дешёвая диагностика, старт не блокируется.
В отличие от снятого в раунде 5 запрета на любые сравнения, вводится **точное** сравнение: `token_equals_sentry_public_key(token, dsn)` (извлечь userinfo из `SENTRY_DSN` → `hmac.compare_digest`). При совпадении — ~~**WARNING на старте**~~ **DEBUG** (не блокирует старт). Это устраняет главный источник 401 без риска ложных срабатываний.

### D5. Sentry ↔ BetterStack разведены по переменным
`SENTRY_DSN` → только `sentry_sdk.init` (`bot.py:26-31`); `LOGTAIL_SOURCE_TOKEN` → только BetterStack. Двойной инициализации/конфликта хендлеров нет; изменения Sentry-кода **не требуются**, требуется лишь стартовая диагностика (configured/not) и ревизия комментариев.

### D6. Startup-диагностика (R17-safe)
> **AMENDED BY ADR-1019-1:** ложный WARNING при `token==pubkey` убран
> (DEBUG); `_HINT_401` УДАЛЁН → словарь `_STATUS_HINTS`
> (`401/402/403/406`). Маркер `attached | host=… | token_len=… | from=…`
> сохранён.
Маркер `[betterstack] attached | host=<host> | token_len=N | ~~last4=XXXX~~ | from=LOGTAIL_SOURCE_TOKEN` (**last4 убран — R17**; см. AMEND выше); хост не секрет, токен — нет. При пустом host/token — `skipped` с причиной. ~~`_HINT_401` дополняется указанием «host/токен одного проекта/региона»~~ → **`_HINT_401` УДАЛЁН, подсказки — словарь `_STATUS_HINTS` (401/402/403/406)** (AMEND ADR-1019-1 D5).

### D7. Рестарт-зависимость `.env` — часть деплоя, не «фикс кода»
Рантайм-подтягивание `.env` **невозможно** без рестарта (порядок импорта). Документируется в `.env.example`/README; `git pull` + правка `.env` + `systemctl restart admin_bot` — шаг @DevOps.

### D8. Диагностика до правки — curl-матрикс (host × token)
> **AMENDED BY ADR-1019-1:** матрикс проверяет **контракт запроса**, а не
> «верность» токена: `{path-token, Bearer} × {US, EU}`; ожидание — **202**
> только на (`US` × `Bearer`). Скрипт — `scripts/betterstack_host_token_probe.py`
> (маскированный вывод, `--dry-run`). Вывод — только HTTP-код (R17).
~~Обязательный наблюдательный шаг (T-1704): 4 комбинации {US, EU} × {Source Token, public key}; ожидаемый 200 только на (US × Source Token).~~ **AMEND ADR-1019-1 D6/D8:** матрикс проверяет **контракт запроса**, а не «верность» токена — `{path-token, Bearer} × {US, EU}`; ожидаемый статус — **202 только на (US × Bearer)** (не 200 на «Source Token»). Вывод — только HTTP-код (R17).

## Consequences

**Positive**
- Логи доставляются в US; 401 исчезает; потеря логов прекращается.
- Fail-safe при ненастроенном хосте (не шлём «в никуда»/в чужой регион).
- Устранено противоречие «public key == Source Token — норма»; проверка детерминирована.
- Sentry и BetterStack явно разведены; smoke-артефакт с библиотечным `LogtailHandler` удалён.

**Negative**
- При пустом `BETTERSTACK_HOST` в проде логи **не** отправляются (требует внимания @DevOps) — принято как осознанный fail-safe.
- Санкционированный Δ каталога +1 и правка 7+ пин-тестов.
- Изменение контракта `BetterStackHandler` (host обязателен) — правка тестов/вызовов.
- `.env`-правка невозможна без рестарта — операционный шаг, не автоматизирован.

## Alternatives

- **A1. Захардкодить US-хост константой в коде.** Отклонено: привязка проекта к региону в коде; хуже для мультипроектности/ротации. Оставлено как допустимый вариант владельца (см. Открытые вопросы спеки).
- **A2. Оставить EU-дефолт и просто «научить» брать из `.env` при наличии.** Отклонено: оставляет ловушку «тихо не туда» при забытом ключе; 401 вернётся.
- **A3. Отправлять в оба региона (fan-out).** Отклонено: двойные расходы/дубли в панели, маскирует проблему.
- **A4. Доверять библиотеке `logtail` и «починить» её вызовом.** Отклонено: библиотека не в прод-пути; ТЗ ошибочно указывает на неё.
- **A5. Блокировать старт при `token == public key`.** Отклонено как дефолт (риск уронить прод из-за одной env-опечатки); WARNING достаточно. Жёсткий вариант — на усмотрение владельца.
- **A6. Settings-поле вместо env-only.** Отклонено: нет рантайм-тюнинга, лишний Settings-Δ и сид.

## References

- `services/betterstack_handler.py:22-23,39,48-49,99-109,224-233`
- `bot.py:14,26-31,136-147,165-174,904`
- `config/settings.py:618-620` (`CHECKUP_BETTERSTACK_SQL_HOST`, отдельный контур)
- `.env.example:57-60,355`; `requirements.txt:14`; `services/log_ring.py:87-90`
- `tests/test_betterstack_handler.py:11-14,129,339,390,401-462`
- `tests/test_monitoring_smoke.py:17,57`; `services/param_catalog.py:440-456`
- Задачи: T-1703 (ADR), T-1704 (curl-матрикс), T-1705 (host), T-1706 (Sentry-аудит), T-1707 (каталог/.env.example), T-1708 (старт-лог/док), T-1709 (тесты), T-1710 (@DevOps), T-1711 (@Reviewer/@PM).
