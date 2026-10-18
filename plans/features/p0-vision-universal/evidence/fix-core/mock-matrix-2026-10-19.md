# P0-Vision (VISION-FIX-CORE) — матрица контрактных моков пробы, 2026-10-19

- Кандидат: рабочее дерево поверх `4ecd2595` (без коммита — на ревью).
- SUT: `services/mca_vision.py::probe_connection` (ступени конфигурация → image → текст).
- Все ответы провайдера — **контрактные моки transport** (`tests/test_p0_vision_fix_core.py`),
  сеть не использовалась: живой внешней пробы в этом срезе НЕТ (честно;
  postdeploy-проба — задача релиза).
- Формат detail: `класс[/http_N]` (R17-safe: без ключей/тела; тело читается
  только через `image_capabilities.extract_provider_error` + sanitize).

## 1. HTTP-статусы (image-ступень, тело без семантики)

| Вход (мок) | capability | reason (словарь 269) | detail | visible_reason (UI) | вызовов |
|---|---|---|---|---|---|
| 2xx + `choices[]` | ok | '' | '' | «Распознавание работает» | 1 |
| 2xx без choices | unavailable | vision_unavailable | empty_completion/http_200 | «Провайдер вернул пустой ответ» | 1 |
| 2xx + `error` c модальным текстом | no_vision | main_model_no_vision / vision_unsupported | image_modality_unsupported/http_200 | «Модель не принимает изображения» | 1 |
| 401 | access_error | vision_unavailable | http_401 | «Неверный ключ: провайдер отклонил авторизацию» | 1 |
| 403 | access_error | vision_unavailable | http_403 | то же | 1 |
| 429 | rate_limited | vision_rate_limited | http_429 | «Превышен лимит запросов провайдера» | 1 |
| 500/503 | unavailable | vision_unavailable | http_500 / http_503 | «Провайдер временно недоступен (ошибка сервера)» | 1 |
| TimeoutError | unavailable | vision_unavailable | timeout | «Провайдер не ответил вовремя (таймаут)» | 1 |
| httpx.HTTPError | unavailable | vision_unavailable | transport_error | «Нет соединения с сервером распознавания» | 1 |

TTL: `access_error/rate_limited/unavailable/pending` — transient
(`MCA_VISION_TRANSIENT_TTL_SECONDS`, default 90 с); `ok/no_vision` — длинный
(`MCA_VISION_CAPABILITY_TTL_HOURS`, default 6 ч).

## 2. Семантика тела 4xx (D4/D5) — «400 сам по себе ≠ нет vision»

| Вход (мок) | capability | detail | вызовов | Комментарий |
|---|---|---|---|---|
| 400 `"Bad request"` (без семантики), текст-контроль 2xx | unavailable (НЕ no_vision) | image_rejected/http_400_text_ok | 2 | модель доступна, изображение отклонено без пояснения |
| 400 `"This model does not support image input"` | no_vision | image_modality_unsupported/http_400 | 1 | явный модальный отказ — доказательство |
| 404 `"No endpoints found that support image input"` (OpenRouter-кейс) | no_vision | image_modality_unsupported/http_404 | 1 | модальный отказ на 404 — тоже доказательство |
| 404 `"The model `x` does not exist"` (+ текст 404) | unavailable | model_not_found/http_404 | 2 | «модель не существует» ≠ «нет vision» |
| 400 `"image too small"` → второй образ 2xx | ok | '' | 2 | повтор другим валидным изображением (D4) |
| 400 `"invalid image data"` ×2 | unavailable | image_rejected/http_400 | 2 | «некорректное изображение» — transient, не постоянное |
| 400 оба этапа без семантики (image + текст) | unavailable | http_400/http_400 | 2 | конфигурация/формат запроса |
| 401 (image) | access_error | http_401 | 1 | авторизация |

## 3. Конфигурационные отказы (локально, без сети; вызовов = 0)

| Вход | detail | visible_reason |
|---|---|---|
| Нет base_url/model | not_configured | «Не настроены адрес или модель распознавания» |
| Отдельный endpoint без своего ключа | vision_key_missing | «Для отдельного адреса укажите отдельный ключ распознавания» |
| api_type ≠ openai_compatible | api_type_unsupported | «Тип подключения не поддерживается (доступен OpenAI-совместимый)» |
| main_model без ключа основного профиля | not_configured | «Не настроены адрес или модель распознавания» |

## 4. Сборка URL (D14) — матрица форм (regression)

| Ввод base_url | chat_completions_url |
|---|---|
| `https://h` | `https://h/chat/completions` |
| `https://h/` | `https://h/chat/completions` |
| `https://h/v1` | `https://h/v1/chat/completions` |
| `https://h/v1/` | `https://h/v1/chat/completions` |
| `https://h/api/v1` | `https://h/api/v1/chat/completions` |
| `https://h/v1/chat/completions` | `https://h/v1/chat/completions` (без удвоения) |
| `https://h/v1/chat/completions/` | `https://h/v1/chat/completions` |

## 5. Кеш/инвалидация (D6/D7)

| Сценарий | Наблюдаемое |
|---|---|
| transient-вердикт старше 120 с (TTL 90 с) | `capability_check_pending` (пере-проверка), НЕ постоянный отказ |
| `no_vision` старше 120 с | вердикт ещё живёт (длинный TTL) |
| success после transient | ok, `effective_enabled=True` |
| ротация значения ключа (dedicated endpoint) | `config_revision` меняется → старый вердикт не действует (pending) |
| ротация основного ключа (main-маршрут) | `config_revision` меняется |
| смена endpoint/модели/типа | `config_revision` меняется |
| в `config_revision` | 16 hex-символов, значение ключа отсутствует (hash значения, R17) |

## 6. Авто-проба (D8)

| Сценарий | Наблюдаемое |
|---|---|
| задание + capability неизвестна, провайдер ok | проба выполнена автоматически (1 вызов), анализ выполнен (ready) |
| задание + проба 401 | задание failed `vision_unavailable` (не `capability_check_pending`) |
| две параллельные `ensure_capability` | ровно 1 проба (singleflight) |
| tool-путь `recognize_target` при pending | проба автоматически, manual-джоба поставлена |

## 7. Воркер (D9)

| Сценарий | Наблюдаемое |
|---|---|
| обработка блокируется 2 с | `_tick_body()` возвращается < 1.5 с (тик не занят), джоба `running` |
| второй тик при работающей джобе | дубля нет (claim CAS, вызовов 1) |
| 3 джобы, concurrency 2 | running=2, queued=1 (не потеряна), затем обрабатывается |
| долгая обработка | heartbeat пишется (call-count ≥ 1), `heartbeat_at` не откатывается |
