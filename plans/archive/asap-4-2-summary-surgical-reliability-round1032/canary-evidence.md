# REAL provider canary — ASAP 4.2 Step 4 (T-4830 / T-4831)

**Статус: VERIFIED — 2/2 canary PASS. Mock не использовался.**

- **Дата прогона:** 2026-10-03 16:14–16:19 UTC
- **Среда:** прод-хост `198.46.175.136` (SSH `nik@...`; sudoers-allowlist systemctl/journalctl admin_bot был в наличии, но НЕ использовался — service-действия запрещены и не выполнялись).
- **Код:** незакоммиченное рабочее дерево ASAP 4.2 (HEAD `373c387` + wt) — `config/` + `services/` отзеркалированы в `/tmp/asap42_canary`, прод-venv использован для зависимостей. После прогона парковка удалена.
- **Прод-сервис: НЕ тронут.** Status-проверка `systemctl status admin_bot`: PID 3294197, active since 2026-10-03 10:27:54 UTC (read-only, без рестартов). Рестартов нет, DDL нет, деплой нет. Canary — только исходящие HTTP-вызовы к провайдеру.

### Биндинг кода (sha256-первые-12 байт скопий в canary-парковке)

| файл | sha256[:12] |
|---|---|
| services/llm_client.py | `79382e83e2cc` |
| services/cover_style_edit.py | `1e02a514cfe6` |
| services/media_execution.py | `5ab8096d6f81` |
| services/image_capabilities.py | `42e6c27382fa` |
| services/image_prompt_compiler.py | `858733af1d4f` |
| services/model_capacity.py | `13fefe26d35e` |

---

## Прод-конфигурация (read-only PG `bot_settings`; секреты в памяти, не печатались)

| слот | base_url | модель | ключ |
|---|---|---|---|
| image (фактический edit-слот) | `https://nano-gpt.com/api/v1` | `qwen-image-3-pro` | `keys.image_api_key` — присутствует (len 44) |
| чат (TEXT) | `https://nano-gpt.com/api/v1` | `deepseek-v4-flash` (env `LLM_MODEL_NAME`) | `keys.llm_api_key` — присутствует (len 44) |
| спе-слот `models.image_style_*` | пусто | пусто | отсутствует |
| `cover_style_connections` | — | — | пусто |

Фактический edit-слот резолвится лестницей наследования §35 в шаг **3c** (`resolve_source = global_image`) — `models.image_*` + `keys.image_api_key`.

**Наблюдение по ключам (важно для supervisor-потока):** RAW-ключ из `.env` (`LLM_API_KEY`) на реальном маршруте даёт **HTTP 401** (первый контрольный прогон, 16:14 UTC). Прод-ключ живёт в PG через ConfigCache (`hot.get('keys.llm_api_key', …)`) — только он аутентифенфицируется (canary v2, 200). Рекомендация в финальный отчёт: всегда резолвить ключ через ConfigCache-лестницу, не через сырое `.env`-значение.

---

## (a) T-4830 — TEXT canary, реальный адаптер `stream=true` → **PASS**

| Метрика | Значение |
|---|---|
| Route | `POST https://nano-gpt.com/api/v1/chat/completions` (`stream: true`) |
| HTTP status | **200**, `content-type: text/event-stream` |
| Модель | `deepseek-v4-flash` (прод-модель чата) |
| SSE data-события | **8** + финальный `[DONE]` получен |
| `on_activity` | 15 вызовов (SSE-активность, последний также после последнего события) |
| `assembled_len` | **55 (> 0)**; текст не публикуется — R17 |
| usage в чанках | не вернулся провайдером (пусто) |
| Latency | 3.1 s |
| Код | `LLMClient.stream_chat_completion` (T-4810) |

Canary упражняет РЕАЛЬНУЮ реализацию SSE-потока (новый код T-4810): submit stream → приём чанков → `on_activity()` → сборка финального контента. Mock-транспорт НЕ использовался; маршрут — production-конфиг (PG + venv).

## (b) T-4831 — NanoGPT Style Edit canary → **PASS**; PO-1: route подтверждён

| Метрика | Значение |
|---|---|
| Слот | `resolve_source = global_image`: `nano-gpt.com/api/v1` + `qwen-image-3-pro` |
| Endpoint discovery | `GET /api/v1/images/models/qwen-image-3-pro/endpoints` → **200**; root-keys: `endpoints`, `id`; содержит `input_reference*`, НЕ содержит `/images/edit(s)`/`imageDataUrl`/multipart |
| Resolved route | **`image_api`** (`POST {base}/images` + `input_references`; без mixing legacy-алиасов) |
| Capability | `image_edit = yes` (подтверждён через live catalog+endpoints; source=`provider_or_registry`) |
| Reference | `extra_images/medved_press.png`: **475 189 B, sha256[:12] `be0a700ba8d3`** (байты локального репо-объекта эквивалентны) |
| HTTP status | **200** (`POST /api/v1/images`) |
| Результат | **реальный image**: len = 1 471 019 B, sha256[:12] `da92902d9ecd` (сохранён в `/tmp/asap42_canary/edit_result.png`, удалён вместе с парковкой; тело не логировалось) |
| Latency | 55.2 s (внутри clamp-окна edit-политики [30, 900]) |
| Ретраи | 0 (успех с первой попытки; provider-error parsing T-4813 не задействован) |

### Примечание по истории контракта (R8-I)
Прод-код до 4.2 обращался к Image API (`{base_url}/images` + `input_references` data-URL) — это совпадает с фактическим маршрутом модели: задокументированный в BL-4 «HTTP 400» на реальном ключе/модели не воспроизведён. Новый код с discovery-driven выбором ветки резолвит тот же контракт (`image_api`). Ветка `route_unverified` неприменима: endpoint-метадата подтверждена реальным 200.

### Гигиена прогона

- Ключи, промпты, байты изображений НЕ печатались и НЕ попали в репо; результаты — санигированные поля (status/route/model/счётчики/sha-префиксы).
- stderr-лог: 0 байт (без ошибок и следов секретов).
- Парковка `/tmp/asap42_canary` и `/tmp/asap42_canary.tar` удалены. Сторонние остатки прошлых сессий (`asap32_watch.log`, `asap32_watch.sh`, `asap4_prod_tests.txt`) — вне задачи, не тронуты.

---

## Вердикт

**PASS (a) и PASS (b).** Оба REAL canary зелёные; provider contract НЕ требует фикса; сценарий `route_unverified` не актуален (route подтверждён). Step 4 закрыт — full suite (T-4832) может запускаться.
