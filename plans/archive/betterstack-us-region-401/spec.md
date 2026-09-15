# Spec F1 — `betterstack-us-region-401` (BetterStack: US-хост, разделение host/token, аудит Sentry)

> **Раунд:** 10.18 (Step 2 @Architect, 15.09.2026). **Тип:** backend/infra. **Приоритет:** P0.
> **ADR:** `adr-1018-1-betterstack-host-token.md` (обязателен).
> **Задачи:** T-1703…T-1711. **Baseline:** HEAD `118a03c`; pytest 6007 passed / 0 failed; каталог 435/406/411/90/88/19; SQLite v9.
> **Источник:** `plans/current_task.md` §1 (строки 3–25) + **UPD п.4** (строка 124). **R17:** в этом документе **нет** токенов/паролей/хостов-значений из `.env` — только имена env-переменных.
> **Решение владельца (UPD п.4):** BetterStack env-host подтверждён **«как есть»** — открытые вопросы §9 Q1/Q2/Q3/Q4 закрыты в пользу рекомендаций (env, а не хардкод; WARNING, а не блокировка; `CHECKUP_BETTERSTACK_SQL_HOST` вне скоупа; `logtail-python` — **удалён из `requirements.txt`/smoke**, T-1706, `S10.18-9`).

## 1. Контекст и цель

Прод спамит `[betterstack] send failed | reason=status=401`: логи не доходят. Проект живёт в US-кластере (`us-west-2a`), а наш `BetterStackHandler` конструируется **без `host=`**, поэтому берёт EU-дефолт `in.logs.betterstack.com` (`services/betterstack_handler.py:39,99,109`). US Source Token на EU-ingest → 401.

**Посылка ТЗ про `LogtailHandler` неточна и должна быть снята:** библиотека `logtail-python` в прод-пути **не используется** с раунда 4 (`bot.py` импортирует свой `BetterStackHandler`, `bot.py:14,136-147`); `logtail-python==0.4.0` остался только в `requirements.txt:14` и используется одним smoke-скриптом `tests/test_monitoring_smoke.py:17,57`.

**Цель:** логи доставляются на US-ingest; хост и токен разведены; Sentry и BetterStack не конфликтуют; зафиксирована рестарт-зависимость `.env`.

## 2. Текущее поведение (сверено с кодом)

| Точка | Факт | Файл/строка |
|---|---|---|
| Инициализация хендлера | `BetterStackHandler(source_token=os.getenv("LOGTAIL_SOURCE_TOKEN"), level=INFO)` — **`host` не передан** | `bot.py:141-145` |
| Дефолт хоста | `DEFAULT_HOST = "in.logs.betterstack.com"` (EU) | `services/betterstack_handler.py:39` |
| URL отправки | `self._url = f"https://{host}/{token}"` (token в path, без Bearer) | `services/betterstack_handler.py:109` |
| Подсказка 401 | `_HINT_401` предлагает «проверьте `LOGTAIL_SOURCE_TOKEN`» | `services/betterstack_handler.py:48-49,224-233` |
| Sentry | отдельный `sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))`, `SENTRY_DSN` больше нигде не используется | `bot.py:26-31` |
| `CHECKUP_BETTERSTACK_SQL_HOST` | code-default тоже EU (`https://eu-fsn-3-connect…`) — та же семья рисков, **отдельный** контур (ClickHouse SQL API) | `config/settings.py:618-620` |
| Санитайз | `sanitize()` применяется к сообщению; фильтр `logtail*` в ring | `services/betterstack_handler.py:134`, `services/log_ring.py:87-90` |
| Противоречащие артефакты | комментарий «совпадение токена с `SENTRY_DSN` — НОРМА» (`bot.py:138-140`, `services/betterstack_handler.py:22-23`); smoke на библиотечном `LogtailHandler` | `bot.py:140`, `tests/test_monitoring_smoke.py:17,57` |
| Тест EU-дефолта | `assert req.full_url == f"https://in.logs.betterstack.com/{'t'*32}"` | `tests/test_betterstack_handler.py:129` |

## 3. Требуемое поведение

1. **Хендлер создаётся только с явным US-хостом.** Хост резолвится из env-ключа `BETTERSTACK_HOST`; при пустом значении хендлер **не создаётся** (fail-safe «лучше без логов, чем логи не в тот регион») + **ERROR** (S10.18-6: явная деградация мониторинга — «логи НЕ отправляются»; было WARNING). Никакого неявного EU-дефолта в проде.
2. **Source Token ≠ public key.** В `LOGTAIL_SOURCE_TOKEN` должен лежать BetterStack **Source Token** (Logs → Sources). Public key из `SENTRY_DSN` в Source Token недопустим. Код даёт детерминированную (не эвристическую) стартовую диагностику при точном совпадении, но **не** блокирует старт.
3. **Sentry и BetterStack разведены:** `SENTRY_DSN` → только Sentry; `LOGTAIL_SOURCE_TOKEN` → только BetterStack. Двойного/конфликтующего хендлера нет.
4. **Startup-диагностика (R17-safe):** в лог — `host`, `token_len`/`last4`, `from=<env-name>`; сами значения токена не печатаются.
5. **Рестарт-зависимость `.env`** задокументирована (`.env.example` + README/док).
6. Диагностика 401 не печатает секрет и содержит корректную подсказку (**Source Token**, а не Sentry DSN).

## 4. Технический дизайн

### 4.1. `services/betterstack_handler.py`

- `DEFAULT_HOST: str = ""` — **убрать EU-дефолт** (константа остаётся как пустой невозможный дефолт, чтобы любой явный вызов с `host=` был обязателен).
- `BetterStackHandler.__init__(self, source_token: str, host: str, ...)` — `host` становится **обязательным** (или при пустом → `ValueError("BetterStackHandler: host is required")`). `self._url` строится только из непустого `host`.
- Новый чистый хелпер (для тестов, без секретов):
  ```python
  def extract_sentry_public_key(dsn: str | None) -> str | None: ...
  def token_equals_sentry_public_key(token: str | None, dsn: str | None) -> bool: ...
  ```
  Реализация: вырезать userinfo из `SENTRY_DSN` вида `https://<pubkey>@<host>/<project>`; сравнить с `token` (`hmac.compare_digest`). Это **точное сравнение**, а не эвристика «токен похож».
- `_HINT_401` переформулировать: «хост и токен должны соответствовать одному региону/проекту; токен — Source Token из Logs → Sources, не public key из `SENTRY_DSN`».
- Стартовый маркер (в `bot.py`, не в хендлере) — см. 4.2.

### 4.2. `bot.py` (только DI-строки логирования; порядок роутеров не трогать)

```python
betterstack_token = os.getenv("LOGTAIL_SOURCE_TOKEN")
betterstack_host = (os.getenv("BETTERSTACK_HOST") or "").strip()
handlers = [console_handler]
if betterstack_token and betterstack_host:
    handlers.append(BetterStackHandler(
        source_token=betterstack_token, host=betterstack_host,
        level=logging.INFO))
elif betterstack_token and not betterstack_host:
    # не создаём хендлер: нет хоста → не отправляем в неизвестный регион
    logging.getLogger(__name__).warning(
        "[betterstack] skipped (no BETTERSTACK_HOST — set the US ingest host)")
```
Стартовый маркер после подключения `log_ring`:
```python
if betterstack_token and betterstack_host:
    logger.info("[betterstack] attached | host=%s | token_len=%d | last4=%s | from=LOGTAIL_SOURCE_TOKEN",
                betterstack_host, len(betterstack_token), betterstack_token[-4:][:4])
    if token_equals_sentry_public_key(betterstack_token, os.getenv("SENTRY_DSN")):
        logger.warning("[betterstack] token == SENTRY_DSN public key — "
                       "this is NOT a Source Token (Logs → Sources)")
else:
    logger.warning("[betterstack] skipped (no token/host)")
```
- `host` — не секрет, логировать можно (R17).
- Никаких правок порядка инклудов/роутеров; меняются только строки логирования (DI).

### 4.3. `tests/test_monitoring_smoke.py` (ревизия противоречащего артефакта)

- Убрать `from logtail import LogtailHandler` и создание хендлера библиотеки. Smoke должен использовать `BetterStackHandler` с `host=os.getenv("BETTERSTACK_HOST")` (или быть помечен `@pytest.mark.skipif` без env и запускаться только вручную). Это устраняет единственный оставшийся путь отправки на EU-дефолт.

### 4.4. Диагностика ДО правки (T-1704) — curl-матрикс

Обязательный **шаг наблюдения** (не коммитится как скрипт с секретом; процедура прикладывается к отчёту с маскированным выводом):

| # | host | token | Ожидание |
|---|---|---|---|
| 1 | US ingest | Source Token | **200** |
| 2 | US ingest | public key из DSN | 401 |
| 3 | EU ingest (`in.logs.betterstack.com`) | Source Token | 401 |
| 4 | EU ingest | public key | 401 |

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Content-Type: application/json" \
  -d '[{"dt":"2026-09-15T00:00:00+00:00","level":"info","severity":2,"message":"probe"}]' \
  "https://$HOST/$TOKEN"
```
Вывод — только HTTP-код; значения `$HOST`/`$TOKEN` в отчёт не попадают (R17). Матрикс разводит две переменные (host × token) и подтверждает root-cause **до** правки.

## 5. Изменения схемы / каталога / env

- **DDL:** нет.
- **Каталог (санкционированный Δ):** новый env-only infra-ключ `BETTERSTACK_HOST` в `services/param_catalog.py::_INFRA_ENV_ONLY` (category `None`, `settings_field=None`, `secret=False`) → **REGISTRY 435 → 436**, `Settings` **406 → 406** (env-only, не Settings-поле), GROUPS 90 / mapped 88 / TAB_RULES 19 — без изменений. Свод с F6/F2 — единый Δ каталога раунда.
- **`.env.example`:** добавить (рядом с `LOGTAIL_SOURCE_TOKEN`, строки 57-60):
  ```
  # US ingest host проекта (из BetterStack → Logs → Sources). Пусто = хендлер не создаётся.
  BETTERSTACK_HOST=your-region-ingest.betterstackdata.com
  ```
- **`config/settings.py`:** НЕ добавлять поле (env-only, читается `os.getenv` напрямую, прецедент `POSTGRES_DSN`).
- `CHECKUP_BETTERSTACK_SQL_HOST` — вне скоупа F1 (отдельный контур), но зафиксировать в отчёте как «проверить регион отдельно» (см. §9 Q3).
- **Секреты:** `.env`/`media/` не трогать; значения токенов/хостов из ТЗ в спеки/ADR/коммит не вносить.

## 6. Влияние на тесты

- `tests/test_betterstack_handler.py`:
  - `:129` — заменить ожидаемый EU-URL на хост, переданный в конструктор (обновить fixture хендлера на явный `host="test.invalid"` или аналог).
  - Добавить: конструктор без `host` → `ValueError`; `_url` = `https://{host}/{token}`; отказ создать хендлер при пустом host (bot.py-импорт-тест).
  - `:339`/`:390` — текст подсказки обновить (Source Token + хост/регион), без значений токена.
  - Новые: `token_equals_sentry_public_key` (совпадение/несовпадение/None/кривой DSN), `caplog`: старт-маркер содержит host и `last4`, не содержит полного токена.
- `tests/test_monitoring_smoke.py` — убрать `LogtailHandler`.
- `tests/test_param_catalog.py` — `INFRA_FIELDS` += `BETTERSTACK_HOST`; `test_env_only_infra_present` — добавить ключ.
- Пин-тесты каталога `REGISTRY == 435` (`tests/test_frontend_tab_mapping.py:84`, `test_round106_ia_smoke.py:32`, `test_webapp_parity_smoke.py:52`, `test_help_guide_round1014.py:196`, `test_settings_persistence_round1014.py:41`, `test_self_reflection_provider_round1014.py:68`, `test_webapp_round1010_ui.py:182`) → **436**.
- Полный `pytest` — 0 failed; `node --check web/app.js` не требуется (фронт не трогаем), но общий раунд-гейт держит.

## 7. Rollout / feature-flag / откат

- **Feature flag:** не требуется (инфра-фикс). Rollback = `git revert BetterStackHandler/host-строк` + рестарт.
- **Порядок (обязателен):** T-1704 curl-матрикс (наблюдение) → T-1705 host-фикс (код) → T-1707 каталог/`.env.example` → T-1706 аудит Sentry → T-1708 startup-лог/док → T-1709 тесты → **@DevOps (T-1710): SSH pull + правка `.env` (`BETTERSTACK_HOST`, `LOGTAIL_SOURCE_TOKEN`=Source Token) + `systemctl restart admin_bot` + live-наблюдение 24ч**.
- `.env` подтягивается **только при рестарте** (`load_dotenv` на импорте, хендлер на уровне модуля) — «рантайм-подтягивание» невозможно; рестарт — часть деплоя.
- Progressive delivery неприменим единым флагом; безопасный порядок выше.

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Правка «не там» из-за посылки про `LogtailHandler` | Раздел 1/2 фиксирует реальную точку; библиотека не трогается |
| R2 | 401 вызван не хостом, а токеном | curl-матрикс разводит host × token **до** правки |
| R3 | При пустом `BETTERSTACK_HOST` логи пропадут | Осознанный fail-safe + **ERROR** (S10.18-6, «логи НЕ отправляются»); `.env.example` и @DevOps-шаг закрывают |
| R4 | Утечка секрета в логи/спеки/ADR | R17-гейт: только `host`, `token_len`, `last4`, `from`; T-1711 скан |
| R5 | Δ каталога (+1) конфликтует с F6/F2 | Единый свод Δ раунда; обновление всех пин-тестов |
| R6 | `CHECKUP_BETTERSTACK_SQL_HOST` остался EU | Вне скоупа F1; зафиксировать в отчёте/backlog |

## 9. Открытые вопросы для human-gate

1. **Хардкодить ли US-хост или брать из env?** → **Рекомендация:** брать из `BETTERSTACK_HOST` (env), code-default — пусто/fail-safe. Хардкод проекта в код не закладываем (мультипроектность/ротация регионов). Санкционированный Δ каталога +1 — **да**.
2. **Считать ли `LOGTAIL_SOURCE_TOKEN == public key SENTRY_DSN` ошибкой на старте?** → **Рекомендация:** да, WARNING (точное сравнение), но **не** блокировать старт (прод не роняем). Полная блокировка — если владелец хочет жёстко.
3. **Обновлять ли `CHECKUP_BETTERSTACK_SQL_HOST` на US-контур в этом раунде?** → **Рекомендация:** нет (отдельный контур, отдельный запрос), зафиксировать в отчёте/backlog; владелец может задать значение в `.env` без правки кода.
4. **Оставлять ли `logtail-python` в `requirements.txt`?** → **Решение (S10.18-9, синхронизировано с T-1706):** **удалён** — smoke переведён на `BetterStackHandler` (T-1709), прод-путь библиотеку не использовал; пин `logtail-python` из `requirements.txt` убран.
