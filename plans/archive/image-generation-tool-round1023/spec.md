# spec.md — F5 `image-generation-tool-round1023`

> **Раунд 10.23** · Приоритет **P1** · Шаг 2 @Architect (часть 2/3) · Тип: backend (tool/service) + UI (`web/**`) + PG-сид
> **ADR:** `ADR-1023-5.md` (Accepted). **Задачи:** `tasks.md` (T-2136…T-2146).
> **ТЗ:** `plans/current_task.md`, «Генерация изображений и Rich Text Саммари → 1. Генерация изображений (Direct Chat)» (untracked; секреты не цитируем — R17/R18; ключ изображений = «ключ из ТЗ current_task.md»).
> **Сквозной архитектурный документ:** `plans/features/round1023-architecture.md` (§1 F5, §3.4 каталог, §5 ступени, §8).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a8a6437`.
> **Зависит от:** F2 (ступень `param_catalog`). Может идти параллельно канон-цепочке F3/F4 (другие файлы). F6 читает провайдера F5.

---

## 0. Контекст и факты аудита кода + веб-ресёрч

| Факт | Точка в коде / источник |
|---|---|
| Tool calling: канон R9, 8 инструментов, EN-descriptions, `additionalProperties:false` | `services/tool_schemas.py:245` `TOOL_CALLING_TOOLS`, `active_tools()`:260 |
| Гейт инструмента по флагу (прецедент «Летописец») | `services/tool_schemas.py:260` (`LORE_COMPILER_TOOL_NAME`) |
| Цикл tool_calls, `TOOL_MAX_ROUNDS=4`, непрямое падение инструмента (модель видит текст) | `services/tool_loop.py:38,89` |
| Реестр исполнения инструментов | `services/tool_router.py:397` `dispatch()` |
| Вызов `active_tools(...)` и `chat_with_tools(...)` в прямом чате | `services/direct_chat_service.py:726` |
| Пре-гейт до генерации (образец для ключевиков) | `services/direct_chat_service.py:670` `_dig_pre_gate_block` |
| Платный бюджет фона | `services/worker_budget.py:196` `consume(pg, scope, metric, amount)` |
| Каталог: группы `models_*`/`keys_*`/`flags_module_*` | `services/param_catalog.py:139` `GROUPS`, `:478` `REGISTRY`, `:1909` `TAB_RULES` |
| Egress-реестр | `services/telegram_send.py:26` `SEND_POINTS`, `:35` `SEND_ALLOWLIST` |
| Идемпотентный PG-DDL/сиды | `services/pg_db.py:33` `DDL_STATEMENTS`, `_seed_settings` |
| Генерации изображений в коде **нет** | — |

### 0.1. Веб-ресёрч (обязательное правило «не гадай — гугли», URL в ADR §References)

**Pollinations.ai (актуальная документация):**
- Base URL: `https://gen.pollinations.ai` (OpenAI-compatible — `https://gen.pollinations.ai/v1`).
- Авторизация: `Authorization: Bearer <sk_...>` (для GET-эндпоинтов допускается `?key=<key>`).
- `POST /v1/images/generations`: поля `prompt` (1…32000), `model` (в OpenAI-схеме default `flux`; в свежих доках GET-эндпоинта упоминается `zimage` как default — поэтому модель **пиннуем явно** `flux` по ТЗ), `n` (сейчас max 1), `size` (`WIDTHxHEIGHT`, default `1024x1024`), `quality` (`standard|hd|low|medium|high`, default `medium`), **`response_format`** (`"url"` → URL на pollinations.ai; `"b64_json"` — default).
- GET-режим: `GET https://gen.pollinations.ai/image/{prompt}?model=flux&width=&height=&seed=` → JPEG/PNG; параметры `seed` (диапазон `-1…2147483647`), `nologo`, `enhance`, `private`, `safe`.
- Ошибки: `400` невалидные параметры, `401` нет/невалидный ключ, `402` исчерпан баланс/бюджет ключа, `403` нет прав, `429`/`503` — с заголовком `Retry-After`, `502` — upstream, `500` — сервер. Повтор того же запроса с тем же `seed` переиспользует генерацию/кэш.
- `response_format:"url"` **не поддерживается community-моделями** — для `flux` (owned) поддерживается.
- Дефолтный таймаут SDK для изображений — 10 мин; проект задаёт свой меньший таймаут.

**Telegram Bot API `sendPhoto`:**
- `photo` — максимум **10 MB**; сумма ширины и высоты ≤ **10000**; соотношение сторон ≤ **20**; `caption` 0…1024.
- Принимает HTTP URL (Telegram сам скачивает) **или** загрузку файла (multipart). Мы используем загрузку байтами (см. §2.4 — чтобы не отдавать Telegram keyed-URL).

**Вывод:** интеграция — `POST /v1/images/generations` с жёстким `response_format:"url"`, модель `flux`, скачивание байтов сервером и отправка `sendPhoto` из памяти.

---

## 1. Цель

Инструмент `generate_image` для Синтезатора прямого чата: срабатывает на явные ключевики («Бот, нарисуй …», «Бот, создай изображение …», «Бот, создай мем …») и на свободные просьбы через tool-calling. Результат — изображение, отправленное в чат. Провайдер по умолчанию — Pollinations.ai (`flux`), настраивается в UI. При падении API бот не падает, Вербализатор выдаёт циничную отмазку. Секрет — только `.env`/PG, никогда в git.

---

## 2. Требуемое поведение

### 2.1. Инструмент и гейтинг

- Новая схема `TOOL_GENERATE_IMAGE` (EN-description, `parameters: {prompt: string}`, `required:[prompt]`, `additionalProperties:false`), добавляется **в конец** `TOOL_CALLING_TOOLS` → 9-й инструмент (порядок первых 8 — канон R9, байт-в-байт).
- `active_tools(lore_compiler_enabled=True, image_generation_enabled=False)` — новый опциональный kwarg. `False` → инструмент исключён (список 8 имён байт-в-байт как сейчас). Снапшот не мутируется.
- Гейт: env-флаг `IMAGE_GENERATION_ENABLED` **И** каталоговый тумблер модуля `flags.image_generation_module_enabled` (per-chat резолв, прецедент `lore_enabled` в `direct_chat_service.py:718`).
- Фактчек-набор (`factcheck_tools`) **не меняется** — изображения в фактчеке не нужны.

### 2.2. Триггер ключевиков (пре-гейт, без форса `tool_choice`)

- Канон: `tool_choice` **не** форсируется (backlog §16 п.2). Поэтому явные ключевики обрабатываются **пре-гейтом** до генерации (образец `_dig_pre_gate_block`):
  - `IMAGE_KEYWORD_RE` в `services/image_generation.py`: сообщение начинается с `бот|bot` и содержит `нарисуй …`, `создай (изображение|картинку|мем|арт)`, `сгенерируй …` (регистронезависимо).
  - При совпадении и включённом модуле: `image_generation.maybe_handle_keyword(ctx, query)` генерирует и отправляет изображение, возвращает блок `<image_result status="ok|error">…</image_result>` для инъекции в user-content Stage-1 (как `<dig_result>`); если генерации нет — блок не инжектится.
- Свободные просьбы («сделай мне картинку кота, который…») ловятся обычным tool-calling: модель сама вызывает `generate_image`.
- Оба пути используют одну и ту же `generate_and_send()`.

### 2.3. Вызов провайдера

`services/image_generation.py::generate(prompt: str) -> GenerationResult`:

- **POST-режим (default):** `POST {IMAGE_BASE_URL}/images/generations` с `Authorization: Bearer <key>`, JSON `{prompt, model, n:1, size:"1024x1024", response_format:"url"}`. Из ответа берётся `data[0].url`, скачивается байтами.
- **GET-режим** (чекбокс «Режим GET-запроса»): `GET {IMAGE_HOST}/image/{urllib.parse.quote(prompt)}?model=<model>&width=1024&height=1024&seed=<random>`; **строго анонимный** — ключ в query НЕ добавляется (review iter1, Finding 1: httpx логирует полный URL на INFO; в UI поле ключа в GET-режиме блокируется). Байты берутся из тела ответа. Defense-in-depth: глушение INFO httpx + `SecretMaskFilter` на `console_handler`.
- **`b64_json`-фолбэк:** если шлюз игнорирует `response_format:"url"` и отдаёт base64, он принимается как сознательный defensive-fallback (основной контракт — `data[0].url`; review iter1, Finding 5).
- **Жёстко:** `response_format:"url"` в POST-режиме (требование ТЗ).
- Таймауты/ретраи: общий таймаут `IMAGE_REQUEST_TIMEOUT_SECONDS` (env-only `ClassVar`, default 90 c, Δ каталога 0); один bounded-ретрай на `429`/`503` с учётом `Retry-After` (не более 1), прочие ошибки — без ретрая. Максимум скачиваемых байтов `IMAGE_MAX_BYTES` (env-only, default 9 MB — ниже лимита Telegram 10 MB).
- **Секрет:** ключ резолвится `hot.get("keys.image_api_key", settings.IMAGE_API_KEY)`; в URL/логах не печатается (R17). В GET-режиме keyed-URL **никогда** не передаётся в Telegram.

### 2.4. Отправка в чат (egress)

- Байты отправляются из памяти: `telegram_send.send_photo(bot, chat_id, BufferedInputFile(bytes, filename="image.jpg"), reply_to_message_id=...)` (новый тонкий wrapper; подпись отсутствует/статична — модель-текста в подписи нет).
- Точка отправки регистрируется в `SEND_ALLOWLIST` (`services/image_generation.py` → «сгенерированное изображение, байты без LLM-текста»), потому что `sendPhoto` не несёт модель-сгенерированного текста.
- `response_format:"url"`-URL не логируется и не отдаётся наружу (может содержать `?key=` в GET-режиме).

### 2.5. Фолбэк

- Ошибка провайдера/таймаут/превышение размера → `GenerationResult(ok=False, reason=<код>)`; R17-safe лог (модель/статус/латентность/класс ошибки — без URL/промпта/ключа).
- В прямом чате: инструмент возвращает модели короткий статус → Синтезатор/Вербализатор формулирует **циничную отмазку**; на пре-гейт-пути при невозможности отправить — код-константа `IMAGE_GENERATION_FALLBACK_PHRASE` (саркастичная фраза, Δ каталога 0).
- Бот **не** падает; существующая деградация tool-loop (`ToolLoopResult`) сохраняется.

### 2.6. Бюджет

- Перед платным вызовом: `ok = await worker_budget.consume(pg, scope=f"chat:{chat_id}", metric=METRIC_IMAGE_CALLS, amount=1)` (новая метрика `"image_calls"` в `worker_budget`). `False` (лимит/`0`-запрет) → генерация не запускается, деградация/отмазка. PG down → fail-open `True` (прецедент).
- Резолв лимита метрики `image_calls`: **переиспользуется** существующий per-chat лимит стоимости (`limits.worker_daily_llm_calls_per_chat`) — **новых каталоговых ключей лимита не вводим** (Δ каталога ограничен image-группами). `worker_budget._metric_limit` расширяется аддитивно веткой для `image_calls`.
- Отдельного `image_tokens` нет (изображение не токены) — стоимость индексируется вызовами.

### 2.7. Каталог (Δ фиксирован)

Новые группы (категории `models`/`keys`/`flags`; **новых вкладок нет**):

| Группа | Категория | Заголовок | Ключи (ParamSpec) |
|---|---|---|---|
| `models_images` | `models` | «Генерация изображений» | `IMAGE_BASE_URL` (default `https://gen.pollinations.ai/v1`), `IMAGE_MODEL` (default `flux`), `IMAGE_GET_MODE` (bool, default false) |
| `keys_images` | `keys` | «Генерация изображений: ключ» | `IMAGE_API_KEY` (secret, **без дефолта**) |
| `flags_module_images` | `flags` | «Модуль: Генерация изображений» | `IMAGE_GENERATION_MODULE_ENABLED` (bool, default ON) |

- pg_key (конвенция `{category}.{snake}`, тест каталога требует префикс категории): `models.image_base_url`, `models.image_model`, `models.image_get_mode`, `keys.image_api_key`, `flags.image_generation_module_enabled` (точные имена финализируются в реализации, но префикс категории обязателен).
- Δ: **REGISTRY +5**, **Settings +5**, **GROUPS +3**, **categorized/mapped +3**, **TAB_RULES +0**, **TAB_NAV +0**. Пин-тесты `test_param_catalog`/`test_frontend_tab_mapping` обновляются **в том же коммите**.
- `models_images`/`keys_images` → вкладка «Провайдеры» (`TAB_LLM_PROVIDERS`); `flags_module_images` → «Модули» (`TAB_MOD_*`-раздел). Структура меню (`tma-menu-freeze`) не меняется.

### 2.8. Секрет и сид

- Ключ **не** коммитится: `IMAGE_API_KEY` default пуст; сид-миграция `config_migrations.migrate_image_provider_defaults(cache)` (идемпотентно) записывает only URL/model/GET-дефолты; ключ — из `.env` (`IMAGE_API_KEY`) или PG (UI), резолв `hot` → `settings`.
- Тест «нет plaintext в репозитории»: скан трекаемых файлов на `sk_`-литерал длиной >20 → fail.
- Отчёт/логи — без значения ключа (R18/R17).

---

## 3. Изменения по файлам

| Файл | Тип изменения |
|---|---|
| `services/tool_schemas.py` | **эксклюзив F5**: `TOOL_GENERATE_IMAGE`, `TOOL_CALLING_TOOLS` +1 (в конец), `active_tools(..., image_generation_enabled)` |
| `services/image_generation.py` | **новый** (эксклюзив F5): провайдер (POST/GET), скачивание байтов, `generate_and_send`, `maybe_handle_keyword`, `IMAGE_KEYWORD_RE`, fallback-фраза, R17-safe логи |
| `services/tool_router.py` | аддитивно: ветка `generate_image` в `dispatch()` (F5 — единственный, кто её трогает) |
| `services/direct_chat_service.py` | аддитивно: резолв тумблера модуля + пре-гейт ключевиков + передача `image_generation_enabled` в `active_tools` |
| `services/worker_budget.py` | аддитивно: `METRIC_IMAGE_CALLS`, ветка `image_calls` в `_metric_limit` |
| `services/param_catalog.py` | ступень F2→**F5**→F8: +3 группы, +5 ключей, tab-маппинг |
| `services/pg_db.py` | аддитивно: автосид новых ключей через существующий `_seed_settings` (defaults из REGISTRY) |
| `services/config_migrations.py` | идемпотентная `migrate_image_provider_defaults(cache)` + вызов в `bot.py main()` |
| `services/telegram_send.py` | аддитивно: `send_photo(...)` + `SEND_ALLOWLIST["services/image_generation.py"]` (F6 позже расширяет файл) |
| `config/settings.py` | `IMAGE_GENERATION_ENABLED` (env ClassVar ON), `IMAGE_API_KEY` (secret), `IMAGE_REQUEST_TIMEOUT_SECONDS`, `IMAGE_MAX_BYTES` |
| `web/index.html` / `web/app.js` | ступень **F5**→F7→F8: блок image-генерации в «Провайдеры» + тумблер в «Модули» (generic-рендер; меню не меняется) |

---

## 4. Контракты/схемы БД, Δ DDL

- Только **PG** `bot_settings` (сид дефолтов image-провайдера). Δ **SQLite DDL = 0**.
- **Нет** plaintext-секрета ни в DDL, ни в сид-миграции, ни в каталоге.
- Идемпотентность: `ON CONFLICT DO NOTHING`; повторный рестарт — no-op.
- Откат: удаление дефолтного провайдера/групп без потери пользовательских настроек; `git revert` / флаг OFF.

---

## 5. Канон / промпты

- **F5 не меняет канон-промпты** Stage-1/Stage-2. Промпт-правила ключевиков не нужны (работает tool-calling + пре-гейт). Δ канона = 0; позиция F5 вне канон-контура (F1→F2→F3→F4→F6).
- EN-description инструмента — единственная новая «инструкция» для модели; она не цитирует клише и не нарушает grep-тест тропов.

---

## 6. План тестирования

1. **Схема/регистрация:** `generate_image` присутствует 9-м; порядок первых 8 байт-в-байт; при `image_generation_enabled=False` список = 8.
2. **Гейт тумблера:** env OFF **или** каталоговый тумблер OFF → инструмент недоступен.
3. **Ключевики:** `IMAGE_KEYWORD_RE` ловит заданные формулировки и не ловит нейтральные фразы.
4. **GET-режим:** формируется GET-URL, ключ не логируется/не уходит в Telegram (байты скачиваются сервером).
5. **worker_budget:** `consume(metric="image_calls")` вызывается; исчерпание/`0`-запрет → деградация без вызова API; PG down → fail-open.
6. **Таймаут/ошибки:** `429`/`503` с `Retry-After` → ≤1 ретрай; `4xx`/таймаут → отмазка, бот жив.
7. **Размер:** превышение `IMAGE_MAX_BYTES`/Telegram-лимитов → отмазка.
8. **Идемпотентность сида:** повторный `migrate_image_provider_defaults` — no-op; ключ не записывается.
9. **Секрет:** нет plaintext-ключа в трекаемых файлах.
10. **Egress:** `services/image_generation.py` зарегистрирован в `SEND_ALLOWLIST`; подпись не несёт LLM-текста.
11. **Регресс:** существующие инструменты/каталог не сломаны; `test_param_catalog` обновлён осознанно; полный pytest **0 failed**; `node --check web/app.js`.

---

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | Critical | Утечка секрета в git/логи/Telegram | Только env/PG; байты вместо keyed-URL; тест «нет plaintext»; отчёт без значения |
| R2 | High | Неверная/устаревшая интеграция Pollinations | Веб-ресёрч зафиксирован (§0.1, ADR §References); жёсткий `response_format:"url"`; GET/POST разведены |
| R3 | High | Платный вызов вне бюджета | `worker_budget.consume(image_calls)` + деградация (T-2140) |
| R4 | Medium | Тулы ломают порядок/канон R9 | Новый инструмент в конец; тесты состава |
| R5 | Medium | UI меняет структуру меню | tma-menu-freeze; generic-рендер; TAB_RULES +0 |
| R6 | Medium | Telegram-лимиты фото (10 MB/w+h/ratio) | Серверная проверка размера до `sendPhoto`; отмазка |

---

## 8. Feature flag / раскатка / откат

- `IMAGE_GENERATION_ENABLED` — env-only `ClassVar` (**default ON**) + каталоговый тумблер модуля `flags.image_generation_module_enabled`.
- `OFF` (любой из двух) → инструмент не объявляется, пре-гейт не срабатывает (байт-в-байт прежний прямой чат).
- Поэтапная раскатка % не требуется; откат — kill-switch OFF / `git revert` (сид обратим, пользовательские настройки не теряются).

---

## 9. Критерии приёмки

- Инструмент вызывается по ключевикам и через tool-calling; результат — изображение в чате.
- Провайдер/модель/ключ/GET-режим настраиваются в UI; тумблер модуля работает.
- Дефолтный провайдер Pollinations записан сид-миграцией; **секрет нигде в git не хранится plaintext**.
- При падении API — циничная отмазка, бот не падает. Платный вызов проходит через `worker_budget`. Полный pytest — **0 failed**.

---

## 10. Зависимости / ступени / handoff

- **Зависит от F2** (порядок правок `param_catalog`). Идёт параллельно канон-цепочке.
- Ступени: каталог **F2 → F5 → F8**; web **F5 → F7 → F8 → F9**.
- Эксклюзивы: `services/tool_schemas.py`, `services/image_generation.py`; аддитивно — `tool_router.py`, `worker_budget.py`, `worker_budget._metric_limit`, `telegram_send.py` (F6 позже добавляет `send_rich_message`).
- **F6 читает**: `services/image_generation.py` (генерация обложки), провайдер-конфиг, `send_photo`, бюджет-метрику.

## 11. Открытые вопросы → Human Gate

1. **Метрика бюджета `image_calls` и переиспользование лимита** (без нового каталогового ключа) — подтвердить/уточнить лимит.
2. **GET-режим с ключом:** допустим ли `?key=` (риск утечки в логи прокси) или GET-режим строго анонимный (ключ заблокирован) — подтвердить.
3. **Размер/качество по умолчанию:** `1024x1024`, `quality=medium` — подтвердить (стоимость/латентность).
