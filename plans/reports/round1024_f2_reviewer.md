# Отчёт @Reviewer — раунд 10.24, Фича F2 `logging-infra-round1024`

> **Ревьюер:** @Reviewer (Senior Principal Engineer — качество / безопасность / архитектура / прод-готовность).
> **Дата:** 19.09.2026. **Шаг:** 5 (строгий аудит). **Итерации:** 1 (`9b802eb`) → **2 (`27296bb`, FINAL)**.
> **Метод:** полный diff; адресные чтения call-site; **собственные инструментальные пробы утечки** через реальный `image_generation._generate_get`/`_request_with_retry`; чистые worktree коммитов (полный pytest); целевой и связанные прогоны.

---

# ИТЕРАЦИЯ 2 (commit `27296bb`) — FINAL

> **Коммит:** `27296bb` — `fix(services,tests): раунд 10.24 F2 — не логировать промпт в path GET, сквозные тесты (review iter1)`.
> **Родитель:** `2a5c694` (F1 уже влит поверх F2 — F1-изменения F2 не приписываю). **Диапазон ревью:** `git diff 27296bb^ 27296bb` — 4 файла, +235/−20: `services/image_generation.py`, `services/external_log.py`, `services/anticliche_worker.py`, `tests/test_external_log_round1024.py`.

## Status: **Approved**

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.

## Итог итерации 2: 0 Critical / 0 High / 0 Medium / 2 Low (не блокирующие).

Все блокеры итерации 1 закрыты по существу и подтверждены мной независимо на чистом коммите `27296bb`.

### Проверка Critical R1024F2-01 (утечка промпта на GET-ретрае) — **Закрыт**

- `_request_with_retry` получил параметр `log_url` (`services/image_generation.py:239-262`); `safe_url = log_url or url`.
- `_generate_get` передаёт `log_url=f"{host}/image"` без промпта (`:383`), `_download_bytes` — только host (`:346`).
- **Моя независимая проба** (реальный production-путь, `_http_request` подменён, 429→200):
  ```
  [ext] event=ext_api provider=image.pollinations.ai method=GET status=429 reason=retry
        url=https://image.pollinations.ai/image attempt=1 body='rl'
  ```
  Ни промпта, ни его percent-encoded формы в логе нет; запрос при этом завершился успешно (`b'img'`).
- Тест `test_get_retry_does_not_leak_prompt` нетривиален: гоняет реальные `_generate_get`+`_request_with_retry`, проверяет и `prompt`, и `quote(prompt, safe="")`, и наличие безопасного `url=.../image`, и `provider=` (R1024F2-05).

### Проверка Medium

- **R1024F2-02 — Закрыт.** `TestEgressEndToEnd.test_scan_failure_scenarios` реально прогоняет image POST 400 (секрет в теле), image GET 429-ретрай, cron fetch 500, Dream traits-empty, graph no-captions и сканирует объединённые записи единым R17/R18-regex; ассертит отсутствие секретов и наличие `reason=retry`/`event=pipeline_step` (т.е. сценарии действительно исполнились). Не тавтологично.
- **R1024F2-03 — Закрыт.** `TestLiteralCatalogSecret` маскирует литеральный секрет каталога: `IMAGE_API_KEY` действительно `secret:true`/`settings_field=IMAGE_API_KEY` в `param_catalog.py:608-609`, кэш `log_ring._SECRETS` сбрасывается фикстурой, значение синтетическое (R18). Проверяет и `safe_text`, и `log_external_api(body=...)`.
- **R1024F2-04 — Закрыт (поставкой F1).** `log_dropped` вызывается в проде: `services/summary_memory.py:3441` (коммит `2a5c694`) на «отравленном» батче. На `27296bb` сигнатура F2 совместима (позднее рабочее дерево добавляет `event=`, но это уже вне ревьюируемого коммита).

### Проверка Low

- **R1024F2-05 — Закрыт.** `_provider_from_url` понимает scheme-less host (`urlsplit("//"+raw.lstrip("/"))`); тест `test_provider_from_scheme_less_host`. В логе `provider=image.pollinations.ai`.
- **R1024F2-06 — Закрыт.** IPv6 возвращает квадратные скобки (`redact_url("https://[::1]:8443/path?x=1") == "https://[::1]:8443/path"`); relative keep_query работал и ранее (поправлен только комментарий).
- **R1024F2-07 — Закрыт.** `fetch_source` логирует ERROR только при `status>=400`; 2xx≠200 → WARNING `fetch_unexpected`; тест `test_fetch_source_2xx_not_error` (204 → ни ERROR, ни `ext_api`).
- **R1024F2-08 — Закрыт.** Полный pytest в основном дереве: **7466 passed / 0 failed**. В чистом worktree `27296bb` — 7465 passed / 1 failed (`test_history_cli` — платформенно-кодировочный флейк, воспроизводится и на baseline, к F2 не относится).

### Тесты итерации 2

- Целевой `tests/test_external_log_round1024.py` — **28 passed** (было 21; +7: retry-leak, egress-e2e, literal-secret ×2, ipv6, provider, 2xx-not-error).
- Связанные (anticliche/dream/image/summary/log_ring) — **272 passed**.
- Полный — **7466 passed / 0 failed** (main tree).

### Инварианты итерации 2

| Инвариант | Статус |
|---|---|
| R17/R18 (без промптов/секретов; синтетические значения в тестах) | ✅ |
| Δ каталога = 0 (`REGISTRY 457 / GROUPS 96 / _TAB_BY_GROUP 94`) | ✅ |
| Δ DDL = 0 (4 файла, ни `database.py`, ни миграций) | ✅ |
| `embeddings` не тронуты (`llm_client.py` в коммите отсутствует) | ✅ |
| `physical-two-call-pipeline` (F2-фикс LLM-вызовов не добавляет) | ✅ |

**Остаточные Low (не блокирующие, не требуют правок для приёмки):**
1. `fetch_source` при 3xx логирует WARNING `fetch_unexpected`, но `raise_for_status()` для 3xx не бросает и поток продолжается — косметика.
2. `_download_bytes` в лог отдаёт только host (без path) — осознанный privacy-first компромисс, диагностируемость чуть ниже.

> **Примечание о рабочем дереве.** В ходе ревью в основном дереве параллельно появлялись незакоммиченные правки других фич (`services/database.py`, `services/external_log.py`, `services/summary_memory.py`, `tests/test_graphrag_memory.py`). Аудит и цифры pytest относятся строго к коммиту `27296bb` (проверено в чистом worktree). Перед деплоем F2 рабочее дерево должно быть стабилизировано/закоммичено.

---

# ИТЕРАЦИЯ 1 (commit `9b802eb`, историческая)

## Status: **Changes Requested**

---

## Сводка итерации 1 (почему было не готово)

Фича сделана аккуратно: единый helper, переиспользование `log_ring.sanitize` (без дублирования R17), URL без query/userinfo, тело ≤1024, kill-switch, сквозная трассировка крона/Сна/графа, `llm_client`/embeddings не тронуты, Δ каталога/DDL = 0. Но есть **один блокирующий дефект приватности**: на пути ретрая image-провайдера в лог уходит **пользовательский промпт целиком** (в path GET-URL). То есть ровно то, от чего эта фича обязана защищать — «тихий откат ≠ утечка», превращается в «тихий откат ≠ утечка секретов, но пользовательский текст утёк». Это ломает R17/R3, spec §3.7, §6(c) и ADR-1024-1 A3. Плюс тест-покрытие обходит этот сценарий, поэтому дефект не поймано.

Плюс к этому заявленное «pytest 7445 passed» на живом рабочем дереве **не воспроизводится как есть** (в ТЗ — 8 падений из-за незакоммиченной параллельной F1; в чистом worktree F2 — 7444 passed и 1 платформенный флейк `test_history_cli`). Сам F2-коммит зелёный, но формулировка заявки неточна.

**Итог итерации 1: 1 Critical / 0 High / 3 Medium / 4 Low.**

---

## Findings

### [Severity: Critical] R1024F2-01 — Промпт пользователя утекает в лог на ретрае image GET-режима
**File:** `services/image_generation.py:242-246` (в `_request_with_retry`), вызывается из `_generate_get` (`services/image_generation.py:361`).
**Location:** `log_external_api(logger, provider=_provider_from_url(url), method=method, url=url, ... reason="retry" ...)`.
**Problem:** `_generate_get` кодирует промпт прямо в path URL (`url = f"{host}/image/{quote(prompt, safe='')}?{urlencode(params)}"`, `:360`). При `status in {429, 503}` `_request_with_retry` логирует **полный `url`**, а `redact_url` по умолчанию срезает только query, **path сохраняет** — и вместе с ним закодированный промпт.
**Доказательство (мой прогон против F2-кода):**
```
WARNING:services.image_generation:[ext] event=ext_api provider=image.pollinations.ai
  method=GET status=429 reason=retry
  url=https://image.pollinations.ai/image/%D0%BA%D0%BE%D1%82-%D1%81%D0%B5%D0%BA%D1%80%D0%B5%D1%82 attempt=1 body='rate limited'
```
(`%D0%BA%D0%BE%D1%82...` — это пользовательский промпт.)
**Why it matters:** R17/R3 и spec §3.7/ADR-1024-1 A3 прямо запрещают писать сырые пользовательские тексты; код в `_generate_get:364` сам комментирует «в лог уходит ТОЛЬКО эндпоинт без промпта», а на ретрае этот же инвариант нарушен. GET-режим — анонимный и как раз наиболее часто упирается в 429/503, значит утечка не экзотика, а регулярный сценарий. Журнал (journald/BetterStack) становится каналом утечки приватных промптов.
**Required fix:** Убрать логирование сырого `url` для GET-ретрая. Минимум — добавить в `_request_with_retry` параметр `log_url: str | None = None` (или `redact_prompt: bool`), и в `_generate_get` вызывать его с безопасным эндпоинтом `f"{host}/image"`; `provider` брать из `base_url`, а не из обрезанного host. Обязательный регресс-тест: 429 в GET-режиме → в логе нет ни `quote(prompt)`, ни распознаваемого фрагмента промпта.

---

### [Severity: Medium] R1024F2-02 — Спец-тест egress (spec §6c) не реализован по существу
**File:** `tests/test_external_log_round1024.py:167-177` (`TestEgressMasking`).
**Problem:** Тест подаёт секрет напрямую в `log_external_api` и проверяет его отсутствие. Но spec §6(c) требует «egress-сканер логов не находит запрещённых токенов **после прогона сценариев сбоя** подсистем» — сквозного сканирования собранных записей image/cron/dream/graph. Этого нет.
**Why it matters:** Именно сквозной скан поймал бы R1024F2-01 (утечка path). Локальная проверка helper'а даёт ложную уверенность.
**Required fix:** Добавить параметризованный тест: прогнать сбои image (POST 400 + GET 429), cron fetch 500, dream error, graph fail с caplog; затем единым regex R17/R18-паттернов (Bearer/`sk-`/`gsk_`/`or-`/literal catalog secret) просканировать все сообщения и assert `0` совпадений.

---

### [Severity: Medium] R1024F2-03 — Не покрыт ключевой случай spec §6(a): литеральный секрет каталога
**File:** `tests/test_external_log_round1024.py:52-89`.
**Problem:** Тестируются `Bearer`, `sk-`, `gsk_`, `or-`, URI-креды, но не проверяется маскирование **литерального значения секрета из каталога** (`log_ring._collect_secrets`), которое spec §6(a) перечисляет явно.
**Why it matters:** Helper делегирует маскировку `sanitize`, но без теста можно случайно сломать именно этот путь (например, кэш `_SECRETS` или отсутствие `settings`-значения) и не заметить.
**Required fix:** Добавить тест с monkeypatch значения секретного `settings`-поля каталога (без цитирования реального ключа) → в `safe_text`/`log_external_api` оно отсутствует.

---

### [Severity: Medium] R1024F2-04 — `log_dropped` в проде не вызывается ни разу (spec §4)
**File:** `services/external_log.py:227-240`; потребление — только `tests/`.
**Problem:** Spec §4 (таблица) и ADR-1024-1 D1/D5 заявляют `log_dropped` как часть поставки F2 для `summary_memory._extract_and_save_graph`. В коммите F2 в `summary_memory` подключён только `trace_step`; `log_dropped` — мёртвый публичный API (потребителя в проде нет).
**Why it matters:** Метрика «потеря данных видима и считается» (`event=dropped_metric`) фактически не эмитится. Часть заявленного контракта enabler'а не выполнена; фактически отложена на F1.
**Required fix:** Либо явно зафиксировать в spec/ADR, что `log_dropped`-эмиссия — поставка F1 (и тогда убрать из «поставлено F2»), либо добавить минимальный вызов в ветку «батч сохранён, но экстракция упала» (`summary_memory.py:3188`) с `count=len(ids)`.

---

### [Severity: Low] R1024F2-05 — Provider-метка GET-режима деградирует до `image`
**File:** `services/image_generation.py:190-196`, вызов `:367` (`_provider_from_url(host)`), где `host = _host_from_base(base_url)` уже без схемы.
**Problem:** `urlsplit("image.pollinations.ai").hostname is None` → `_provider_from_url` возвращает `"image"`. В логах провайдер неотличим от заглушки.
**Why it matters:** Диагностика (грепы/алерты по провайдеру) теряет идентификатор.
**Required fix:** Передавать в `_provider_from_url` исходный `base_url` (со схемой) или `hostname` напрямую.

### [Severity: Low] R1024F2-06 — `redact_url(keep_query=True)` молча теряет query для относительных/безсхемных URL
**File:** `services/external_log.py:87-93`.
**Problem:** В ветке «относительный/некорректный URL» `base = raw.split("?", 1)[0]` — `keep_query=True` игнорируется, query отбрасывается целиком (включая несекретные параметры). Также IPv6-host теряет квадратные скобки при реконструкции netloc (`:82-86`).
**Why it matters:** Неверное ожидание при включённом `EXTERNAL_API_LOG_URL_QUERY`; не критично, но контракт «keep_query сохраняет query» ложный.
**Required fix:** Разобрать query и в ветке без scheme; для IPv6 оборачивать host в `[]`.

### [Severity: Low] R1024F2-07 — `fetch_source` пишет ERROR на любой status ≠ 200, включая успешные 2xx
**File:** `services/anticliche_worker.py:169-177`.
**Problem:** Для `status ∈ {201, 204, ...}` логируется `reason=fetch_http` с `level=ERROR`, затем `raise_for_status()` не бросает, и выполнение продолжается успешно. Получается ERROR-строка при фактическом успехе.
**Why it matters:** Ложные ERROR зашумят алерты (цель F2 — достоверная наблюдаемость).
**Required fix:** Логировать ERROR только при `status >= 400` (или `not 200 <= status < 300`), иначе INFO/DEBUG.

### [Severity: Low] R1024F2-08 — Заявка «7445 passed» на живом дереве не воспроизводится
**File:** процесс/отчётность (не код F2).
**Problem:** Полный прогон в основном рабочем дереве дал `8 failed, 7437 passed` — все 8 падали на счётчиках каталога/полей Settings из-за **незакоммиченных параллельных правок F1** (`config/settings.py`, `services/llm_client.py`, `services/summary_memory.py`). В чистом worktree коммита `9b802eb`: `7444 passed, 1 failed` — `tests/test_history_cli.py::TestCliFts::test_scope_is_required` (платформенная кодировка stdout на Windows в worktree; на baseline `00eab85` падает так же → к F2 не относится).
**Why it matters:** «Зелёный полный pytest» как критерий приёмки на грязном дереве недостоверен.
**Required fix:** Ревью/приёмку фиксировать на чистом коммите; Builder'у — не мешать коммитам независимых фич в одном дереве.

---

## Контракт: чекбоксы и покрытие

| Требование spec §3/§4 | Статус |
|---|---|
| Helper `log_external_api`/`trace_step`/`log_dropped`/`redact_url`/`safe_text`/`REDACTED` | ✅ (`services/external_log.py`) |
| Тело усечено ≤ `EXTERNAL_API_LOG_BODY_CHARS` (1024) и обезврежено `sanitize` | ✅ |
| URL без query/userinfo (default); маскировка секрет-параметров при `keep_query` | ✅ (кроме R1024F2-06) |
| Уровни INFO/WARNING/ERROR по правилу | ✅ (`_level_for_status`, `_refresh_level`) |
| Крон клише: фаза + `next_run_time` + `exc_info` | ✅ (`anticliche_worker:264-277, 290-385`) |
| Экстрактор/Сон: этапы с `chat_id`, без сырых текстов | ✅ (`dream_worker._trace_deep`) |
| Image: статус + тело + reason + ретраи | ✅ / ⚠️ утечка промпта на GET-ретрае (R1024F2-01) |
| Embeddings/`llm_client` НЕ тронут | ✅ (`git diff` по `services/llm_client.py` в коммите пуст) |
| `bot.py`/`log_ring`/`SecretMaskFilter` не дублируются | ✅ |
| Kill-switch OFF → без url/body, но с status/reason | ✅ (тест `TestKillSwitch`) |
| `log_dropped` поставлен в прод | ⚠️ нет вызовов (R1024F2-04) |

## Инварианты

| Инвариант | Статус |
|---|---|
| `physical-two-call-pipeline` | ✅ F2 не добавляет LLM-вызовов |
| egress-реестр `SEND_POINTS`/`SEND_ALLOWLIST` | ✅ не тронут |
| `parse_mode=None` (plain-каналы) | ✅ `handlers/**`,`web/**` не менялись |
| Δ каталога = 0 | ✅ `param_catalog`/REGISTRY не менялись (457/96/94) |
| Δ DDL = 0 | ✅ миграций/схемы нет |
| логика фич не изменена (только логирование) | ✅ по diff — только лог-точки (нюанс R1024F2-07) |
| R18 — секреты не в коде/логах/отчёте | ✅ в отчёте секреты не цитируются |

## Тесты

- Целевой `tests/test_external_log_round1024.py` — **21 passed** (маскировка, усечение, уровни, kill-switch, image/cron/dream/graph — не тавтологичны, изолированы, без сети).
- Связанные (`test_anticliche_round1023`, `test_dream_worker`, `test_dream_persona_traits`, `test_image_generation_round1023`, `test_summary_memory`, `test_log_ring`) — **272 passed**.
- Чистый worktree `9b802eb`: **7444 passed / 1 failed** (`test_history_cli`, платформенный флейк, воспроизводится и на baseline).
- Живое дерево в момент первого прогона: **7437 passed / 8 failed** — из-за незакоммиченной параллельной F1; после её пересохранения 8 тестов вновь зелёные (подтверждено точечным прогоном: 18 passed).
- Пробел покрытия: ретрай image GET (R1024F2-01/02), литеральный секрет каталога (R1024F2-03).

---

## Точный список для @Builder (blocking)

1. **[Critical] R1024F2-01.** `services/image_generation.py`: исключить попадание промпта из path в лог ретрая. В `_request_with_retry` добавить `log_url`/безопасный URL-параметр; в `_generate_get` (`:361`) передавать `f"{host}/image"` (без `{quote(prompt)}`). Регресс-тест: GET 429 → `assert` отсутствия промпта (и его percent-encoded формы) в `caplog`.
2. **[Medium] R1024F2-04.** Определиться с `log_dropped`: либо вызов в `summary_memory.py:3188` (`component="graph", reason="extract_failed", count=len(ids)`), либо зафиксировать отложенность в spec/ADR и снять из объёма F2.
3. **[Medium] R1024F2-02/R1024F2-03.** Добавить сквозной egress-тест по подсистемам и тест на литеральный секрет каталога.
4. **[Low] R1024F2-05/06/07.** Поправить metку провайдера, `keep_query` для относительных URL/IPv6 и уровень лога `fetch_source` для не-4xx/5xx.

Верни исправленную версию. Текущий код отклонён.
