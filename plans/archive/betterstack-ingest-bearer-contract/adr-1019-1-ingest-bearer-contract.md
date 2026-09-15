# ADR-1019-1 — BetterStack ingest-контракт: `POST https://{host}` + `Authorization: Bearer`; снятие ложного WARNING token==SENTRY_DSN public key

- **Статус:** Proposed (Step 2 @Architect, раунд 10.19)
- **Дата:** 2026-09-15
- **Раунд:** 10.19, фича F1 `betterstack-ingest-bearer-contract` (T-1778)
- **База:** HEAD `fd6acc7`. **Связано:** ADR-1018-1 (host/token политика 10.18), ADR-1013-1 (env-only), §10/§16/§17.
- **AMEND:** **ADR-1018-1 D2** (URL-форма: из «`https://{host}/{token}`, token в path» → «`https://{host}` + `Authorization: Bearer`»), **D4** (совпадение token с Sentry public key перестаёт быть ошибкой — на unified US это норма), **D8** (matrix проверяет **контракт запроса**, а не «верность» токена), **D6** (из стартовой диагностики убирается ложный WARNING; `_HINT_401` переформулирован).
- **SUPERSEDE:** не supersede — D2/D3/D5/D7 сохраняются полностью (host обязателен из env, `.env`-рестарт-зависимость, разведение Sentry↔BetterStack, Δ каталога +1 остаётся).

## Context

1. Прод-симптом: `[betterstack] send failed | reason=status=401`, >1000 недоставленных логов; мониторинг «не мониторит».
2. Владелец (UPD2 п.2, `current_task.md:133-149`) предоставил скриншоты BetterStack: на **унифицированных US-кластерах** Source Token для Telemetry **побайтово совпадает** с Public Key из `SENTRY_DSN`. Токен верный; причина 401 — не токен.
3. Код: `services/betterstack_handler.py:157` формирует `https://{host}/{source_token}` (token в **path**), `_post:232-241` **не** ставит `Authorization`. Официальный контракт BetterStack — `POST https://{ingesting_host}` + `Authorization: Bearer {source_token}`, `Content-Type: application/json`.
4. Прежняя диагностика (`bot.py:190-194` WARNING, `_HINT_401:60-62`) построена на неверной посылке «token == pubkey = ошибка» → ложная тревога и увод диагноза.
5. `logtail-python` в прод-пути **не используется** (нет в `requirements.txt`, нет импортов) — ТЗ-инструкция про `LogtailHandler(endpoint=…)` неприменима.
6. Инварианты: R17 (токен/URL с токеном — никогда в логи/планы/отчёты), fail-safe 10.18 (без host хендлер не создаётся), Δ каталога 0.

## Decision

### D1. URL без токена в пути; авторизация — заголовком Bearer
`self._url = f"https://{host}"`; `_post` добавляет `Authorization: Bearer {source_token}`. `Content-Type: application/json` и `User-Agent: adminbot/own-v1` сохранены. Значение `_auth_header` в логи не попадает (R17).

### D2. Единый Bearer-путь — без авто-выбора формата и без флага
Авто-детект «`betterstackdata.com` → Bearer, иначе path-token» **отклонён**: Bearer валиден и на legacy EU `in.logs.betterstack.com`, path-token — не документированный контракт, а наша ошибка раунда 4. Один путь = предсказуемость и отсутствие мёртвой ветки. Feature flag не вводится (OFF-ветка = гарантированный 401). Формально это **AMEND ADR-1018-1 D2**: обязательность host и запрет EU-дефолта сохраняются, меняется только форма URL.

### D3. Семантика ответов ingest
`202` — успех; `402` — квота; `403` — невалидный source token; `406` — битое тело; **все 4xx, включая `429`, — не ретраить**; `5xx`/транспорт — прежняя политика (≤1 повтор). Подсказки — словарь `_STATUS_HINTS` (только код + слова, R17).

### D4. `token == SENTRY_DSN public key` — НЕ ошибка (**AMEND ADR-1018-1 D4**)
На unified US совпадение — норма (подтверждено скриншотами владельца). Стартовый `WARNING` `bot.py:190-194` **удаляется**, заменяется `logger.debug(... normal on unified US clusters)`. Функции `extract_sentry_public_key`/`token_equals_sentry_public_key` сохраняются как дешёвая диагностика.

### D5. `_HINT_401` снят; подсказки привязаны к коду
Константа `_HINT_401` удаляется; вводится `_STATUS_HINTS` (`401: невалидный source token или не тот хост региона`, `403: невалидный source token (Logs → Sources)`, `402: квота`, `406: битое тело`). Категоричные утверждения о public key убраны.

### D6. Матрикс до правки — проверка КОНТРАКТА, а не токена (**AMEND ADR-1018-1 D8**)
Обязательный curl-матрикс (@DevOps, T-1779, до правки): `{токен-в-пути, Bearer} × {US, EU}`; вывод — **только HTTP-код**. Ожидание: 202 только на (`US` × `Bearer`). Артефакт — evidence для этого ADR; значения токена/URL не фиксируются.

### D7. Что из ADR-1018-1 сохраняется без изменений
D2 (host обязателен, нет EU-дефолта, `DEFAULT_HOST=""`, нет host → ERROR «логи НЕ отправляются»), D3 (Δ каталога +1 `BETTERSTACK_HOST`, env-only), D5 (Sentry↔BetterStack разведены), D7 (правка `.env` = рестарт, шаг @DevOps).

## Consequences

**Positive**
- Логи доставляются на US-ingest; 401 устранён; потеря телеметрии прекращается.
- Убрана ложная тревога «не тот токен» — диагноз больше не уводится в сторону.
- Контракт соответствует официальной документации BetterStack; мёртвая path-token-ветка не поддерживается.
- Диагностика стала точнее (distinct 401/402/403/406), оставаясь R17-safe.

**Negative**
- При неверном host/токене теперь виден 401/403 — ожидаемо; оператор должен различать «не тот регион» и «не тот токен» по коду (401 vs 403).
- Если у BetterStack изменится контракт, path-token-совместимости нет (осознанно; откат — `git revert`).
- Требуется live-шаг @DevOps (`.env` + рестарт) — иначе фикс не проявится.

## Alternatives

- **A1. Авто-детект формата по `betterstackdata.com`.** Отклонено: мёртвая ветка, неопределённость, нет выгоды (Bearer работает и на EU).
- **A2. Добавить `logtail-python` и «починить» вызов `endpoint=`.** Отклонено: библиотека не в прод-пути (ТЗ-посылка неверна), лишняя зависимость.
- **A3. Хардкод US-хоста в коде.** Отклонено ADR-1018-1/A1 (привязка к региону, ломает мультипроектность).
- **A4. Оставить WARNING `token==pubkey` как «предупреждение».** Отклонено: владелец подтвердил норму; это шум и ложный диагноз.
- **A5. Блокировать старт при `token==pubkey`.** Отклонено: роняем прод из-за штатной конфигурации.
- **A6. Fan-out в оба региона.** Отклонено: дубли в панели, двойные расходы, маскирует проблему.

## References

- `services/betterstack_handler.py:22-24,51,60-62,82-93,157,232-241,250-281`
- `bot.py:140-205`
- `plans/current_task.md:133-149,156`; `plans/features/betterstack-ingest-bearer-contract/tasks.md`
- `plans/features/betterstack-ingest-bearer-contract/spec.md` §4.1/§4.5
- ADR-1018-1 (`plans/archive/betterstack-us-region-401/adr-1018-1-betterstack-host-token.md`) — **AMEND D2/D4/D6/D8**
- Задачи: T-1778 (ADR), T-1779 (curl-матрикс @DevOps), T-1780…T-1787 (@Builder), T-1788 (@Reviewer/@PM)
