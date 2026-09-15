# Spec F1 — `betterstack-ingest-bearer-contract` (Ingest: `POST https://{host}` без токена в пути + `Authorization: Bearer`; снятие ложного WARNING token==SENTRY_DSN pubkey)

> **Раунд:** 10.19 (Step 2 @Architect, 15.09.2026). **Тип:** backend/infra (`services/betterstack_handler.py`, `bot.py`, `tests/`, `.env.example`, docs). **Приоритет:** **P0** (телеметрия уходит в никуда, >1000 неотправленных логов).
> **ADR:** `adr-1019-1-ingest-bearer-contract.md` (**AMEND ADR-1018-1 D2/D4/D8**).
> **Задачи:** T-1778…T-1788. **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог 436/90/406/411/88/19; SQLite v10; APP_VERSION 2.57.0.
> **Источник:** `plans/current_task.md` UPD2 п.2 (строки 133-149) + чекап (строка 156).
> **Конфликт файлов:** только если Δ каталога — не ожидается (Δ=0 у F1).

## 1. Контекст и цель

Прод-симптом: `[betterstack] send failed | reason=status=401` спамит, >1000 логов не доставлены. Владелец подтвердил скриншотами: **Source Token для Telemetry на унифицированном US-кластере побайтово совпадает с Sentry public key** — это норма, токен верный. Причина 401 — **контракт запроса**, а не токен.

Прод-путь — **наш** `BetterStackHandler`, библиотеки `logtail-python` в проекте нет (см. §2): посылка ТЗ про `LogtailHandler(endpoint=…)` фактически неприменима. Текущий контракт хендлера — **токен в пути** `https://{host}/{source_token}` без авторизации (`_url:157`), что на unified US даёт 401.

**Цель:** перейти на официальный контракт `POST https://{ingesting_host}` + `Authorization: Bearer {source_token}`, Content-Type `application/json`; снять/переформулировать ложные предупреждения; обновить подсказки/тесты/docs. Значения хоста/токена — **только в `.env`** на сервере (R17).

## 2. Текущее поведение (сверено с кодом HEAD `fd6acc7`)

- `services/betterstack_handler.py:157` — `self._url = f"https://{host}/{self.source_token}"` — **токен в пути**.
- `services/betterstack_handler.py:232-241` — `urllib.request.Request(self._url, data=body, method="POST", headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT})` — **нет `Authorization`**.
- `services/betterstack_handler.py:250-264` — ретрай ≤1 только на 5xx/транспорт; 4xx — `_mark_failed("status=…")`.
- `services/betterstack_handler.py:272-281` — `_mark_failed`: при `status=401` добавляет `_HINT_401`.
- `services/betterstack_handler.py:60-62` — `_HINT_401` утверждает «токен — Source Token, а не public key из SENTRY_DSN» — **вводит в заблуждение**.
- `services/betterstack_handler.py:82-93` — `token_equals_sentry_public_key(token, dsn)` — точное `hmac.compare_digest`.
- `bot.py:190-194` — стартовый `WARNING` при совпадении token с pubkey (**ложная тревога** на unified US).
- `bot.py:151-157,182-205` — host обязателен из env `BETTERSTACK_HOST` (10.18/F1), при пустом — `ERROR «логи НЕ отправляются»` (fail-safe сохраняем).
- `services/betterstack_handler.py:51` — `DEFAULT_HOST = ""` (ADR-1018-1 D2 сохраняется).
- `logtail-python` в `requirements.txt` **отсутствует**, импортов нет; `tests/test_monitoring_smoke.py` переведён на `BetterStackHandler` — **библиотеку не добавлять/не трогать**.

## 3. Требуемое поведение

1. URL запроса — **без токена в пути**: `https://{host}` (host из `BETTERSTACK_HOST`; значение не хардкодить).
2. Каждый POST несёт заголовок `Authorization: Bearer {source_token}`; `Content-Type: application/json` сохранён.
3. Коды ответа: **202** — успех; **402** — квота исчерпана; **403** — невалидный source token; **406** — битое тело; **все 4xx, включая 429, — не ретраить**; **5xx/транспорт** — прежняя политика повтора (≤1).
4. `token_equals_sentry_public_key` **не порождает WARNING** (на unified US совпадение — норма); старт не блокируется, диагностируемость сохраняется (DEBUG/INFO, R17).
5. `_HINT_401` переформулирован без ложного тезиса «pubkey — ошибка»; при 403 — подсказка «невалидный source token».
6. Диагностика/ответы — **R17-safe**: в логи не попадают ни токен, ни URL с токеном.
7. Все ветки — автоматическое решение о формате (без флага): Bearer **всегда** (см. §4.1).

## 4. Технический дизайн

### 4.1. Решение по обратной совместимости форматов (D2-adr)

**Принято: единый Bearer-путь, без авто-выбора формата.**

Обоснование (документируется в ADR-1019-1):
- официальный контракт BetterStack (и unified US, и legacy EU `in.logs.betterstack.com`) — `POST https://{host}` + `Authorization: Bearer {source_token}`; path-token не является документированным контрактом, он был нашей ошибкой раунда 4;
- при `host`, содержащем `betterstackdata.com` (unified US), Bearer — точно;
- при legacy EU `in.logs.betterstack.com` Bearer тоже валиден по докам → **один путь проще, предсказуемее, без risk «тихо не туда»**;
- авто-выбор `if 'betterstackdata.com' in host: Bearer else path-token` **отклонён**: сохраняет мёртвый код и неопределённость; path-token оставлен только как диагностическая ветка T-1779 (curl-матрикс), не как рантайм.

### 4.2. Правки `services/betterstack_handler.py`

```python
# :157
self._url = f"https://{host}"                       # токен в пути УБРАН
self._auth_header = f"Bearer {self.source_token}"   # для _post (в логи не попадает)

# :232-241 (_post)
request = urllib.request.Request(
    self._url, data=body, method="POST",
    headers={"Content-Type": "application/json",
             "Authorization": self._auth_header,
             "User-Agent": _USER_AGENT})
```

- Импорт `hmac`/`extract_sentry_public_key`/`token_equals_sentry_public_key` **сохранить** (вызов из `bot.py`), но убрать из докстринга модуля (`:22-24`) утверждение «это должен быть Source Token, а НЕ public key» → заменить на «на unified US Source Token Telemetry совпадает с Sentry public key — норма».

### 4.3. Обработка статусов (`_mark_failed` / `_reason` / `_HINT_401`)

Новый словарь reason-текстов (R17-safe, только слова):
```python
_STATUS_HINTS = {
    401: "невалидный source token или не тот хост региона",
    402: "квота ingest исчерпана (проверьте план/объём)",
    403: "невалидный source token (Logs → Sources)",
    406: "битое тело батча (внутренняя ошибка, повторите после рестарта)",
}
```
- `_mark_failed`: `hint = _STATUS_HINTS.get(code)` → `reason = f"status={code} | {hint}"`.
- `_HINT_401` из константы **удаляется** (заменяется словарём); тезис про pubkey снят.
- **Все 4xx, включая 429, не ретраить** (сохраняется); 5xx/транспорт — без изменений (≤1 повтор).
- Никаких значений токена/URL в reason — только коды и слова (R17).

### 4.4. `token_equals_sentry_public_key` (D4-adr): снять ложный WARNING

- Функции `extract_sentry_public_key`/`token_equals_sentry_public_key` **остаются** (нужны для диагностики).
- В `bot.py:190-194` WARNING **удаляется**. Вместо него — `logger.debug("[betterstack] token matches SENTRY_DSN public key (normal on unified US clusters)")` — только при совпадении, без значений.
- `bot.py` стартовый маркер `:186-189` (`attached | host=… | token_len=… | from=LOGTAIL_SOURCE_TOKEN`) **сохраняется**.

### 4.5. curl-матрикс ДО правки (T-1779, @DevOps; evidence для ADR)

Обязательный наблюдательный шаг **до** изменения кода (на прод-кредах, вывод — **только HTTP-код**, R17):

| # | Формат | Хост | Ожидание |
|---|---|---|---|
| 1 | токен в пути (`POST https://{host}/{token}`) | US (`*betterstackdata.com`) | 401 |
| 2 | `Authorization: Bearer {token}` | US | **202** |
| 3 | токен в пути | EU (`in.logs.betterstack.com`) | 401/не найден |
| 4 | `Authorization: Bearer {token}` | EU | (справочно; для unified US не требуется) |

В отчёт — только HTTP-коды и факт «какая комбинация дала 202». Запрещено печатать значение токена/полный URL.

## 5. Изменения схемы / каталога / env

- **Схема БД:** нет.
- **Каталог:** **Δ=0** (`BETTERSTACK_HOST` уже введён в 10.18/F1, ADR-1018-1 D3). Новых ключей нет; `_HINT_401` — код-константа.
- **env:** `.env.example` — **только плейсхолдеры** (`BETTERSTACK_HOST=...`); реальные значения на сервер вносит @DevOps. `LOGTAIL_SOURCE_TOKEN` — единственное имя токена.
- **docs/README/ARCHITECTURE:** §10/§16/§17 — заменить `_url = https://{host}/{token}` на Bearer-контракт; markdown-пометки, что `logtail-python` не используется, сохранить.

## 6. Влияние на тесты

- `tests/test_betterstack_handler.py`:
  - assert `handler._url == "https://{host}"` (токена в URL нет);
  - assert `Authorization` присутствует в перехваченном `Request` (monkeypatch `urllib.request.urlopen`/`Request`);
  - матрица 202/402/403/406 → reason-коды + `get_stats()["failed"]`;
  - R17: сериализованное представление `Request.headers`/`_url` не содержит токена при логировании (проверка текста `_HINT`-констант);
  - **D-01 (ревью Батча A):** 302 → ровно один запрос, `Authorization` только к исходному хосту (на `Location` не уходит), `sent==0`, `failed==1`, без ретрая; end-to-end через production-opener (`_NoRedirectHandler`) с локальным сервером;
  - регресс: буфер/ретраи/`close()`/дропы — без изменений.
- `tests/test_monitoring_smoke.py`: подтвердить, что используется `BetterStackHandler` (не библиотечный).
- Новый маркер-тест: **отсутствие** строки `SENTRY_DSN public key` в WARNING-канале на старте (caplog `bot`).
- `tests/test_param_catalog.py` — Δ=0 (не менять).
- Полный `pytest` 0 failed; `git diff --check` clean.

## 7. Rollout / feature-flag / откат

- **Feature flag НЕ вводится** (инфра-контракт логирования; OFF-ветка = гарантированный 401). Переключение — деплой + рестарт (`systemctl restart admin_bot`).
- **Progressive delivery:** неприменимо. Live-проверка @DevOps: маркер `attached` + отсутствие `status=401` в логе рестарта + счётчик `sent` растёт.
- **Rollback:** `git revert` (+ при необходимости возврат `.env`); прежний контракт снова даст 401 — деградация видна по `[betterstack] send failed`.

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | ADR-1018-1 D4 прямо требовал WARNING при `token==pubkey` | **AMEND** ADR-1019-1 D4: на unified US совпадение — норма |
| R2 | ADR-1018-1 D8 фиксировал матрикс `{US,EU}×{SourceToken,pubkey}` | **AMEND** D8: матрикс `{path-token,Bearer}×{US,EU}` |
| R3 | ТЗ ссылается на `logtail-python`/`endpoint=` — библиотеки нет | Зафиксировать в ADR/spec; править наш хендлер |
| R4 | Регресс доставки при смене контракта | T-1779 evidence до правки + матрица-тесты + live-проверка |
| R5 | Утечка токена в отчёты/логи | R17: только HTTP-коды/`token_len`; скан `git diff` |
| R6 | `_HINT_401` снова введёт в заблуждение | Словарь без категоричных утверждений о pubkey; T-1788 аудит |

## 9. Открытые вопросы (рекомендации)

0. **UPD2 §3 / UPD3 п.1 (SSH-фрагмент) — ВНЕ scope F1 и ЗАКРЫТО:** задача очистки/переписывания истории `git` **отменена** владельцем (вариант (а): оставить как есть, `filter-repo`/историю НЕ трогаем). Пометка — в `plans/backlog.md` (раунд 10.19, «Пункт отчёта/backlog»). Значение секрета нигде не цитируется (R17). F1 занимается **только** ingest-контрактом (§1-§8).
1. **Поддерживать ли path-token legacy EU автоматически?** Рекомендация — **нет**, единый Bearer (§4.1). Санкция не требуется (внутренний контракт).
2. **Удалять ли `token_equals_sentry_public_key` совсем?** Рекомендация — **оставить** (дешёвая диагностика), понизив до DEBUG.
3. **Расширять ли матрикс на EU-Bearer?** Рекомендация — только справочно у @DevOps, в DoD не требовать (проект в US).
4. **Нужен ли `BETTERSTACK_HOST` в каталоге как Settings-поле?** Рекомендация — **нет** (env-only, прецедент `POSTGRES_DSN`; ADR-1018-1 D3 сохраняется).
