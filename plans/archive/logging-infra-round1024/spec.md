# spec.md — F2 `logging-infra-round1024` (R17-safe логирование внешних API и фоновых пайплайнов)

> Раунд 10.24, Часть 1 (backend-core) · Приоритет **P1 (enabler)** · ADR: **ADR-1024-1**
> ТЗ: `plans/current_task.md` UPD2 п.11 (стр. 231–235), UPD3 п.7. Секреты/креды не цитировать (R17/R18).
> Baseline: HEAD `00eab85`; pytest 7424/0; SQLite v12; каталог 457/96/94.

## 1. Цель

Ввести единое правило: **«тихий откат для конечного пользователя ≠ тишина в серверных логах»**. Каждый сбой внешнего API/фонового пайплайна обязан оставить в логе причину (статус, усечённое тело ответа стороннего API, фаза падения, `exc_info`), но без утечки секретов. Без этого F1/F7/F8/F12 дебажатся вслепую.

## 2. Что уже есть (координаты)

- R17-маскировка: `services/log_ring.py::sanitize` (`:65-84`), `SecretMaskFilter` (`:94-112`), фильтр на консольном хендлере — `bot.py` (при подключении `console_handler`).
- Image-провайдер: `services/image_generation.py:176-186` (`_reason_from_status` — только код), POST `:246-289`, GET `:306-331`, download `:291-303`; итог `generate()` `:357-398` (WARNING без тела).
- Анти-клише: `services/anticliche_worker.py:217-227` (`tick` — только статус), `refresh` `:231-314` (WARNING без причины фазы), `_call_llm` `:316-324`.
- Экстрактор/Сон: `services/dream_worker.py` — точечные `logger.warning` (`:1593`, `:1607`, `:1629`, `:1828`, `:1856`, `:1871`, `:1885`), сквозной трассировки нет.
- Embed 4xx (образец формата): `services/llm_client.py:720-735` (`body_4xx` уже усечён, `_BODY_MAX_CHARS`).
- Egress-сканер секретов: `tests/` (паттерны R17/R18); консольный `SecretMaskFilter`.
- Потребители результата: F1 (graph-extract причина), F7 (крон клише), F8 (этапы Сна), F12 (тело ошибки image-провайдера).

## 3. Требуемое поведение

1. Все внешние/фоновые сбои пишутся через **один helper** `services/external_log.py`.
2. Тело ответа стороннего API логируется усечённо (≤ `EXTERNAL_API_LOG_BODY_CHARS`, default 1024) и обезврежено (`log_ring.sanitize`).
3. URL логируется без query/userinfo (по умолчанию), либо с маскировкой секрето-подобных параметров.
4. Уровни: нормальный 2xx → `INFO`; ожидаемый fallback → `WARNING`; реальный сбой/потеря → `ERROR`.
5. Крон анти-клише пишет фазу падения (`fetch|llm|parse|empty|write`) и `next_run_time`; исключения — с `exc_info`.
6. Экстрактор Сна пишет этапы (`gate/candidates/parse/dedup/write/status`) с `chat_id` и причиной skip/empty/error — без сырых текстов.
7. Один вызов = одна строка с `event=...` (греп/алерт).
8. Помощник никогда не бросает; логирование не делает сетевых вызовов и не тормозит горячий путь (работает на уже полученном `response`).

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `services/external_log.py` | **новый**: `log_external_api`, `trace_step`, `log_dropped`, `redact_url`, `safe_text`, `REDACTED` |
| `config/settings.py` | env-only `ClassVar`: `EXTERNAL_API_LOGGING_ENABLED` (True), `EXTERNAL_API_LOG_BODY_CHARS` (1024), `EXTERNAL_API_LOG_URL_QUERY` (False) |
| `services/image_generation.py` | В `generate()` при ошибке — `log_external_api(...)` с телом; в POST/GET/download — статус/тело; ERROR для реального сбоя, WARNING для штатного фолбэка |
| `services/anticliche_worker.py` | `refresh`: фаза+статус+`exc_info`; `tick`: `next_run_time` и итог; `fetch_source` ошибка со статусом/телом |
| `services/dream_worker.py` | `_run_deep_once`/`_run_persona_traits_once`/`_write_paradigm`: `trace_step(...)` на каждом этапе/раннем return с причиной |
| `services/summary_memory.py` | `_extract_and_save_graph`: `trace_step`/`log_dropped` (потребляет F1) |
| `services/llm_client.py` | (только формат) embed 4xx через helper; **логика embeddings не меняется** (UPD3 п.7) |

## 5. Контракты

### 5.1. Публичный API helper (стабильный, для F1/F7/F8/F12)

```python
REDACTED = "***"
def redact_url(url, *, keep_query=False) -> str
def safe_text(text, *, limit=None) -> str
def log_external_api(logger, *, provider, method=None, url=None, status=None,
                     reason=None, body=None, duration_ms=None, attempt=None,
                     level=logging.INFO) -> None
def trace_step(logger, *, component, step, status, reason=None, chat_id=None,
               extra=None, level=None) -> None
def log_dropped(logger, *, component, reason, count=1, chat_id=None,
                extra=None) -> None
```

- Ни один аргумент не несёт auth-материал; `body` — уже полученный текст ответа.
- `safe_text` идемпотентен (повторный вызов не портит), никогда не бросает.
- `level=None` в `trace_step` → правило: `status in {"ok","skip"}` → `INFO`, `{"empty","duplicate"}` → `INFO`, `{"error","dropped"}` → `ERROR`, иначе `WARNING`.

### 5.2. Формат строк (пример)

```
[ext] event=ext_api provider=pollinations method=POST status=400 reason=bad_request url=https://host/v1/images/generations body='{"error": ...}' dur_ms=812
[pipeline] event=pipeline_step component=dream step=traits status=empty reason=no_self_facts chat_id=-100...
```

### 5.3. Kill-switch

`EXTERNAL_API_LOGGING_ENABLED=False` → `log_external_api` не печатает `url`/`body`, только `provider/status/reason`; `trace_step`/`log_dropped` продолжают работать (они R17-safe по построению).

## 6. Тесты

- (a) Helper маскирует секреты: `Bearer abc`, `sk-...`, `gsk_...`, `or-...`, URI-креды, литеральный секрет каталога → `***`.
- (b) Helper режет длину тела до лимита; `EXTERNAL_API_LOG_URL_QUERY=False` → query отсутствует.
- (c) Egress-сканер логов не находит запрещённых токенов после прогона сценариев сбоя.
- (d) При сбое каждой подсистемы (image/cron/extractor/graph) появляется запись с причиной (не только имя класса).
- (e) Уровни: штатный фоллбэк → WARNING/INFO, реальный сбой → ERROR.
- (f) Helper не делает сетевых вызовов и не бросает на `None`/битом входе.
- (g) `EXTERNAL_API_LOGGING_ENABLED=False` → нет тела/URL в записи.

## 7. Риски

- **R1 (High):** утечка секрета через `body`/URL → маскирование + тест egress (T-2197/T-2202).
- **R2 (Medium):** раздувание journald → лимит тела/уровни, согласовано с F9 (логи 7 дней).
- **R3 (Medium):** логирование сырых текстов сообщений нарушает приватность → не писать тела пользовательских сообщений (только метаданные/длины).
- **R4 (Low):** шум на ожидаемых фоллбэках → уровни WARNING/INFO.

## 8. Критерии приёмки

- Для каждого класса сбоя из п.0/п.5/п.6/п.10 в логе есть запись с причиной (а не только имя класса).
- Тело ответа внешнего API усечено и без секретов; egress-тест зелёный.
- Штатный фоллбэк — WARNING/INFO, реальный сбой — ERROR.
- pytest зелёный; логирование не добавляет сетевых вызовов и не тормозит горячий путь.

## 9. Флаг и откат

- Флаги: `EXTERNAL_API_LOGGING_ENABLED` (env-only `ClassVar`, default **ON**), `EXTERNAL_API_LOG_BODY_CHARS` (1024), `EXTERNAL_API_LOG_URL_QUERY` (False).
- Откат: флаг OFF (тело/URL выключаются) / `git revert`; Δ DDL = 0, Δ каталога = 0, канон-миграций нет.

## 10. Артефакты-ссылки

- ADR: `ADR-1024-1.md`.
- Карта: `plans/features/round1024-architecture.md` §3.1, §3.4, §5.
