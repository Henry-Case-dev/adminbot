# QRNG P2 — LfDR-адаптер (implementation)

**Дата:** 2026-11-17
**Стадия:** P2 из arch-decision `plans/features/vmq-onto-01/evidence/qrng-recovery/arch-decision-2026-11-17.md` (§3 D9, §6 P2).
**Требования:** `QAN-REC-LFDR-01` (AC-06); регрессия `QAN-REC-PROV-02`, `QAN-REC-EXC-01…05`.
**База:** P1 approved tip `2e4c11cf` (ветка `fix/qrng-p1`), не master/deployed.
**Ветка:** `fix/qrng-p2`; кандидат: `27591ede` (код+тесты) + этот evidence-коммит.
**Статус:** REVIEW (не VERIFIED, не деплой, версия не bumped). P3/P4/P5 не начаты.

## 1. Что сделано (ровно P2)

Один аддитивный блок внутри существующего `services/mca_random_source.py`; второй
сервис/store/очередь/API/планировщик не создаются.

| Элемент | Назначение |
|---|---|
| `LFDR_HOST/PATH/ENDPOINT/FORMAT` | документированный контракт `GET https://lfdr.de/qrng_api/qrng`, `format=HEX` |
| `LFDR_MIN_LENGTH=1`, `LFDR_MAX_LENGTH=MAX_LENGTH=1024` | границы запроса: безопасный предел = действующий контракт партии; документированный серверный максимум 2147483647 сознательно не используется |
| `LfdrError(AnuError)` | те же коды/поля (`code/reason/retryable/sent/retry_after`), существующая обработка `except AnuError` продолжает работать; второй контракт ошибок не создаётся |
| `validate_lfdr_endpoint(url)` | origin-guard до запроса: scheme `https`, host ровно `lfdr.de`, порт только None/443, путь ровно `/qrng_api/qrng`, без userinfo/query/fragment |
| `LfdrClient` | async fetch/check; инъекция `http_get` (та же сигнатура), таймаут, min-interval, circuit breaker (3 fails → open 60 c → half-open один probe) с **независимым** состоянием от ANU |
| `lfdr_fetch` / `lfdr_check` | реестровые точки входа; принимают общий клиент владельца (breaker/min-interval сохраняются) либо создают одноразовый клиент с инъекцией `http_get` |
| `PROVIDERS[lfdr]` | `entropy_class=hardware_quantum`, `requires_key=False`, `key_setting=None`, `fetch/check` подключены; `docs_url` уточнён до `https://lfdr.de/QRNG/` |

Контракт запроса (единственный возможный): метод GET, URL `https://lfdr.de/qrng_api/qrng`,
`params={"length": N, "format": "HEX"}`, заголовков авторизации нет (`headers={}`),
таймаут — параметр клиента. Произвольный endpoint/query/заголовки через публичный
API адаптера не передаются.

Контракт ответа: `{"length": N, "qrn": "<2N hex>"}`. Проверки по порядку: объект →
отсутствие `error` → `length` целое/dec-строка и равен запрошенному → `qrn` строка →
`len(qrn) == 2N` (чётность и точная длина) → только `[0-9a-fA-F]` → пары → uint8.
Партия — существующий носитель `AnuBatch(values, data_type="uint8", length=N,
provider="lfdr", latency_ms)`, поэтому `RandomStore.insert_batch`/`reserve_chunk`/
`reserve_draw` расходуют её без нового механизма (см. тест
`test_lfdr_batch_consumed_by_existing_atomic_store`).

## 2. Коды ошибок (честные, без зелёного)

| Условие | Код | retryable | sent |
|---|---|---|---|
| пустой/битый URL, чужой host/path/port, userinfo, query | `invalid_url` | False | False |
| не https | `scheme_not_allowed` | False | False |
| length вне 1..1024 / не целое / bool | `validation_failed` | False | False |
| breaker открыт | `provider_unavailable` (`circuit_open`) | True | False |
| backoff/min-interval | `rate_limit` | True | False |
| `asyncio.TimeoutError` | `timeout` | True | True |
| Connect/Pool timeout (транспорт) | `timeout` | True | False |
| 3xx | `redirect_blocked` | False | True |
| 401/403 | `auth_failed` | False | True |
| 429 (+Retry-After) | `rate_limit` | True | True |
| 4xx | `client_error` (очищенный `error`) | False | True |
| 5xx | `provider_unavailable` (очищенный `error`) | True | True |
| битый JSON / схема / length / hex / `error` при 200 | `validation_failed` | False | True |

Отличие от ANU намеренное: 429 у LfDR — это rate limit публичного сервиса, а не
исчерпание квоты аккаунта, поэтому код `rate_limit`, не `quota_exhausted`.
Ключа нет и не создаётся: новое setting-поле отсутствует, `PROVIDER_KEY_SETTINGS`
не менялся (9 ключей ANU), заголовок `x-api-key` не отправляется.

## 3. Что НЕ изменено

- ANU-клиент, `validate_endpoint`, ANU-коды/квоты — без изменений (доказано тестом
  `test_anu_client_contract_still_intact` и разделением guard'ов).
- IBM: адаптера по-прежнему нет (`fetch/check is None`) — P5.
- Селектор/fallback, `memory.random_source`, refill-путь, UI (`web/`), routes,
  параметры каталога, ключи/панели, LLM — не тронуты; новых env-флагов/настроек/
  таблиц/эндпоинтов нет.
- `status_snapshot` DTO не менялся: `providers[lfdr]` остаётся в P1-схеме
  (`configured=false`, `state=provider_unconfigured`), потому что runtime LfDR пока
  не использует; per-provider runtime-состояние — P3. Фейкового «готов» нет.

## 4. Тесты и доказательства

Артефакты в этом каталоге:

- `tests-p2.json` — все прогоны (P2 62, P1 29, random/QND 196, mandatory 386,
  webapp 1455/33 идентично базе, JS 117/4), RED и мутации.
- `red-tests-2e4c11cf.txt` — RED на базе `2e4c11cf`: 60 failed / 2 passed
  (проходят только «отсутствие ключа» и «ANU не изменён»).
- `red-probe-base-2e4c11cf.json` / `green-probe-p2.json` — поведенческий пробник:
  на базе нет `LfdrClient`/`validate_lfdr_endpoint`, `PROVIDERS[lfdr].fetch is None`;
  на кандидате — запрос ровно один, params `{"length":2,"format":"HEX"}`, заголовки
  пустые, значения `[94,241]`, guard-коды на недопустимые URL.
- `mutations.json` — 7 мутаций (http-scheme, произвольный path, отсутствие проверки
  hex, отсутствие сверки `length`, снятые границы, `requires_key=True`, ключевой
  заголовок) — все убиты целевыми тестами; модуль восстановлен (sha256 совпал).
- `live-probe-2026-11-17.json` — один реальный GET `length=2` из dev-harness:
  200, `length=2`, `qrn` 4 hex-символа, 2 uint8-значения, 1078 мс, без ключа.
- `mutation_probe.py`, `red_probe.py`, `live_probe.py` — воспроизводимые скрипты.

## 5. Ограничения и передача в P3

1. LfDR **не включён** в runtime-путь: `resolve_effective`/`refill_if_needed`/
   `_fetch_batch` остаются ANU-only — это P3 (селектор/fallback). P2 даёт адаптер,
   реестровую точку входа и совместимый носитель партии.
2. Circuit breaker LfDR повторяет семантику `AnuClient`, но не вынесен в общий
   класс: постановка P2 прямо запрещает менять ANU-клиент; унификация уместна в P3,
   когда оба адаптера окажутся в одном dispatch-пути. Состояние breaker'ов уже
   независимое (падение LfDR не должно открывать ANU-цепь).
3. `/api/status` не заявляет LfDR как подключённый к runtime; честные per-provider
   состояния/остатки — P3/P4.
4. Публичный сервис без SLA: доступность проверена одним запросом; latency не
   нормируется, при недоступности — `provider_unavailable`/`timeout` и breaker.
5. P1-плейсхолдер-утверждение «`PROVIDERS[lfdr].fetch is None`» заменено на
   `is not None` (D9 подключает адаптер); остальные P1-инварианты не изменены,
   P1-набор 29/29 проходит.

## 6. Rollback

`git revert` коммита P2: адаптер/реестровая привязка исчезают, P1-код остаётся
работоспособным; данные и схема не затрагиваются (новых колонок/таблиц нет).
