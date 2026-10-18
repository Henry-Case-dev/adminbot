# P0 Vision Universal — recon: карта цепочки и карта дефектов

- Дата разведки: **19.10.2026** (Windows-локаль, UTC+5 на проде).
- Режим: **read-only**. Код не менялся; в репозиторий добавлены только этот док и `evidence/recon/**`; рабочие пробы лежали в managed scratch (`OPENCODE_WORKFLOW_SCRATCH/p0vision_recon/`).
- Локальный кандидат на момент разведки: `323ff265` (рабочее дерево, включая незакоммиченные изменения других срезов). Коммит этой разведки поставлен поверх `80d2257a`; между `323ff265` и `80d2257a` — только `plans/**` (доки), код-якоря перепроверены на текущем дереве (`services/mca_vision.py:80,175,902`).
- Прод: коммит `3b02366e`, 2026-10-19T01:30:51Z; **один** read-only SSH-коннект (fail2ban-дисциплина), без записи в БД и без ретраев.
- Внешние сервисы (OpenRouter и др.) **не вызывались** — среда не даёт оснований тратить чужие ключи; поведение воспроизведено на локальных пробах с подменённым транспортом (никаких сетевых вызовов).
- Источник требований: `plans/features/p0-vision-universal/source-p0-vision-2026-10-19.md` (§1–§5), карта `requirements-map.json` (req_id: P0V-ARCH-*, P0V-PROBE-*, P0V-PIPE-*, P0V-UI-*, P0V-ACCEPT).

## 0. Резюме: почему «`google/gemma-4-31b-it:free` через OpenRouter → `vision_unavailable`»

Корневая причина **воспроизведена** и подтверждена прод-данными:

1. Пользовательский адрес Vision сохраняется в ключ `models.vision_api_base_url` (каталог `services/param_catalog.py:1031`, UI `web/app.js:1065`).
2. Код маршрута читает **другой, несуществующий** ключ `models.vision_base_url` (`services/mca_vision.py:80`, использование `:175`). В каталоге такого ключа нет (локальная проверка: `'models.vision_base_url' registered: False`).
3. Поэтому «выделенный endpoint» фактически пуст → маршрут `dedicated` собирается как **base_url основного провайдера + Vision-модель + Vision-ключ**: локальная проба на прод-конфигурации даёт `base_url=https://nano-gpt.com/api/v1`, `model=google/gemma-4-31b-it:free`, а отправляемый ключ — именно Vision-ключ (прод: len=73, last4=e0ba) → запрос `POST https://nano-gpt.com/api/v1/chat/completions` с моделью OpenRouter и ключом OpenRouter.
4. Провайдер на чужую модель отвечает 404 → проба классифицирует как `vision_unavailable` (`detail=http_404/404`) — ровно то, что видно на проде и в UI.

Топ-дефекты по влиянию: **D1** (чужой endpoint), **D2** (смешивание ключей), **D3/D4/D5** (проба: 1×1 PNG, 400 → ложный `no_vision`, неразличаемые причины), **D6/D7** (кеш 6 ч для временных сбоев; нет инвалидации по смене ключа), **D8** (нет автоматической пробы → задания умирают `capability_check_pending`), **D9** (тики воркера пропускаются: последовательная обработка при интервале 5 с), **D10/D11/D12** (артефакт `function () { [native code] }`, сырой код `vision_unavailable` в тосте, провайдер/тип подключения не показываются).

## 1. Карта цепочки (файл:строка)

| Стадия | Где живёт | Точные якоря |
|---|---|---|
| Настройки (каталог) | `services/param_catalog.py` | `:1031-1039` ParamSpec `VISION_API_BASE_URL`/`VISION_API_TYPE`/`VISION_MODEL` (группа `models_vision`); `:832-836` секрет `VISION_API_KEY` (группа `keys_vision`); `:343-350` `limits_vision`; `:411` `flags_module_vision`; ключ bot_settings = `ParamSpec.pg_key` `:114-120` → `models.vision_api_base_url` |
| Настройки (UI) | `web/app.js` | `:1058-1070` блок подключения `id:'vision'` (`probeEndpoint:'/api/vision/test'`, поля base_url/тип/модель/ключ); `:675-680` карточка модуля (`toggleKey:'flags.vision_enabled'`); `:730,821-829` вкладки модуля и `MODULE_MODEL_BLOCKS.mod_vision=['vision']`; разметка блока — `web/index.html:2118-2260` (таб «LLM Провайдеры») и `:1753-1890` (карточка модуля, `workspaceModelCards`) |
| Сохранение | штатный контур config (`hot_config.set_config_cache`, `services/hot_config.py:32-36`); чтение — `hot.get(key, default)` `:71-76` (нет ключа → Settings-дефолт) | значения Vision в PG: `bot_settings` (`services/pg_db.py:36-42`) |
| Разрешение маршрута | `services/mca_vision.py` | `resolve_route` `:162-207`; `_main_route` `:154-159`; ключ — `_api_key_for` `:210-215`; константы ключей `:76-84`; revision `:202-204` |
| Capability probe | `services/mca_vision.py` | `_NEUTRAL_PNG` `:359-363`; `probe_connection` `:415-499`; классификация `_classify_probe` `:385-412`; кеш `:218-262`; событие `_emit_probe` `:502-516`; вход — только `web/api/routes.py:2246-2283` (`POST /api/vision/test`) |
| Постановка задания | `services/mca_vision.py`, `handlers/summary.py` | `enqueue_intake_jobs` `:1162-1217` (coalesce `vision:asset:{asset_id}`); вызов `handlers/summary.py:471-474`; backfill `backfill_sweep` `:1832-1897` |
| Worker | `services/mca_vision.py`, `bot.py` | `VisionMediaWorker` `:1665-1804` (start `:1685-1701`, `_tick` `:1716-1723`, `_tick_body` `:1725-1754`, `_run_one` `:1766-1782`, `_expire_deferred` `:1784-1804`); запуск `bot.py:841-852`, стоп `bot.py:1051-1053`; хранилище заданий `services/task_supervisor.py` (`enqueue` `:420-458`, `active` `:594`, `depth` `:608`, `recover_stale` `:547`) |
| Запрос провайдеру | `services/mca_vision.py` | `analyze_image_bytes` `:890-949` (URL `:902`, payload `:903-916`, ошибки `:919-932`); транспорт `_default_transport` `:372-382`; таймаут 60 с |
| Результат → сохранение | `services/mca_vision.py` | `process_asset_job` `:1315-1571` (гейт effective `:1394-1402`, кеш по content_hash `:1466-1486`, CAS-finish `:1543-1555`); парсер `parse_analysis_payload` `:852-887`; таблицы `mca_media_assets`/`mca_media_analyses` (`services/database.py:1572,1606`) |
| Контекст бота | `services/chat_context.py` → `services/mca_vision.py` | `collect_media_analysis_blocks` `:211-259` → `render_media_context_async` `:1924+` (read-only, без новых vision-вызовов) |
| Диагностика/снапшот | `services/mca_vision.py`, `web/api/routes.py` | `runtime_snapshot` `:2116-2164`; `GET /api/vision/state` `web/api/routes.py:2286-2303` |

## 2. Прод-факты (19.10.2026, read-only)

Полный вывод: `evidence/recon/prod_recon-2026-10-19.txt`.

**Эффективные настройки (bot_settings, секреты — только маска):**

| Ключ | Значение |
|---|---|
| `models.vision_api_base_url` | `https://openrouter.ai/api/v1` |
| `models.vision_api_type` | `openai_compatible` |
| `models.vision_model` | `google/gemma-4-31b-it:free` |
| `keys.vision_api_key` | present(len=73,last4=e0ba) |
| `flags.vision_enabled` (глобально) | **False** (per-chat `flags.*` — `per_chat=True`, возможны overrides в `chat_profiles.chat_params.overrides`) |
| `models.llm_base_url` / `models.llm_model_name` | `https://nano-gpt.com/api/v1` / `deepseek/deepseek-v4.1-flash` |
| `keys.llm_api_key` | present(len=44,last4=349c) |
| `limits.vision_*` | image_max_dimension=1600, queue_capacity=100, user_rate=10/10, chat_rate=60/30 |
| env `MCA_VISION_*`, `VISION_*` | не выставлены → дефолты (K1–K4 ON, capability TTL 6 ч, deferred TTL 24 ч) |

**События (`mca_events`):** `vision_capability_probe` — **4 записи, все `outcome=failed reason=vision_unavailable stage=dedicated model=google/gemma-4-31b-it:free`** (18.10.2026 14:12:21–14:13:25Z), успешных проб — ноль. За 24 ч: `vision_media skipped reason=capability_check_pending` ×14, `vision_media skipped reason=vision_unavailable` ×10. Эти же строки видит «Аналитика» (читатель `mca_events`: `services/pipeline_analytics.py:7,351,375,922`), источник записи — `mca_vision._emit_probe` (`services/mca_vision.py:502-516`; `outcome=failed` для любого не-`ok`, `skipped` для `pending`).

**Задания (`task_jobs`, kind `vision.*`):** `vision.media failed vision_unavailable` ×10; `vision.media failed capability_check_pending` ×4; `vision.media cancelled queue_coalesced` ×4; `vision.backfill failed capability_check_pending` ×10. Попытки у терминальных — `att=1/4`.

**Анализы:** `mca_media_analyses` — **0 строк** при 3183 активах `mca_media_assets` ⇒ сквозной результат ни разу не сохранился (P0V-PIPE-CONTEXT не выполнялся ни разу).

**Воркер/журнал:** `SKIPPED_INSTANCES=487` за 36 ч — записи вида
`apscheduler.scheduler - WARNING - Execution of job "VisionMediaWorker._tick (trigger: interval[0:00:05]...)" skipped: maximum number of running instances reached (1)`; пример 18.10.2026 15:04:49→15:05:01 UTC: тик занял ~7 с, следующий пропущен.

## 3. Локальное воспроизведение (read-only, без сети)

Скрипты и вывод: `evidence/recon/local_route_probe.py`, `evidence/recon/local_probe_matrix.py` (+ `.txt`).

- **Маршрут на прод-конфигурации:** `source=dedicated`, `base_url=https://nano-gpt.com/api/v1`, `model=google/gemma-4-31b-it:free`, `api_type=openai_compatible`, `key_present=True`, отправленный ключ = Vision-ключ. Т.е. Vision-ключ уходит на **основной** endpoint (OpenRouter-ключ → nano-gpt).
- **Проба при 404/404** (так отвечает endpoint на незнакомую модель): `capability=unavailable`, `reason=vision_unavailable`, `detail=http_404/404` — совпадает с прод-событиями.
- **Ключ при dedicated-endpoint без Vision-ключа:** `_api_key_for` отдаёт **основной** ключ; запрос уйдёт на сторонний endpoint с чужим ключом.
- **400 на изображении + текст 200** → `capability=no_vision`, `reason=vision_unsupported`, `image_input=False`, `detail=image_http_400_text_ok` — в том числе для ответа «image too small» (валидная, но 1×1 картинка).
- **401** → `access_error/vision_unavailable`; **429** → `rate_limited/vision_rate_limited`; **503** → `unavailable/vision_unavailable` и **кешируется** (`expired=False` при TTL 6 ч).
- **Ротация ключа** (значение другое, наличие то же) → `config_revision` **не меняется** (`fe861e8232b16d2e`) → старый вердикт продолжает действовать.
- **Тестовое изображение пробы:** `_NEUTRAL_PNG` = 70 байт, `image/png`, **1×1**, прозрачное.
- **URL при вводе полного пути:** `base_url=.../api/v1/chat/completions` → POST `.../api/v1/chat/completions/chat/completions` (двойной путь).

## 4. Карта дефектов (§ директивы → факт/якорь → предлагаемый фикс)

| ID | § / req | Факт и якорь | Предлагаемый фикс (кратко) |
|---|---|---|---|
| **D1** | §1 (L00011-L00013), P0V-ARCH-ENDPOINTS/BASEURL/SPLIT, P0V-SYMPTOMS | `VISION_BASE_URL_KEY="models.vision_base_url"` (`services/mca_vision.py:80`) не существует; каталог/UI пишут `models.vision_api_base_url` (`param_catalog.py:1031`, `web/app.js:1065`). `resolve_route:175` читает пусто → dedicated-маршрут = main base_url + чужая модель/ключ (локальная проба; прод: OpenRouter-адрес не применяется) | Читать канонический ключ (для совместимости — сначала `models.vision_api_base_url`, затем legacy-имя), регресс-тест «сохранённый адрес реально уходит в запрос» (матрица host / host/ / host/v1 / host/api/v1) |
| **D2** | §1 (L00014,L00016), P0V-ARCH-KEYS/NOFAULT | `_api_key_for` (`:210-215`): dedicated-маршрут без своего ключа получает **ключ основного провайдера** и отправляет его на чужой endpoint (проба: `fallback на MAIN ключ: True`); обратный случай — Vision-ключ уходит на main endpoint (D1). Дубль той же логики: `services/cover_style_jobs.py:1900-1910` | Ключ строго по профилю endpoint'а: dedicated endpoint без своего ключа → честная ошибка конфигурации (как уже описано в docstring D4), а не main-ключ; убрать дубль-резолв в `cover_style_jobs` (использовать общий `_api_key_for`) |
| **D3** | §2.1, P0V-PROBE-IMG | Проба шлёт прозрачный 1×1 PNG (`:359-363`; локально 70 байт, 1×1) | Валидное изображение подходящего размера (≥512 px, непрозрачное, с проверяемым содержимым); вердикт — по содержанию ответа, а не только по 2xx |
| **D4** | §2.4, P0V-PROBE-400 | 400/422 на image-пробе + текст 200 ⇒ постоянный `no_vision` (`:404-408`, `:470-495`); локально воспроизведено на «image too small». HTTP 400 не доказывает отсутствие мультимодальности | Не выводить `no_vision` из 400: разбирать тело ошибки (переиспользовать `services/image_capabilities.py:340-381` — `extract_provider_error`/`_sanitize_error_text`), повторять пробу с другим валидным изображением/моделью и различать «изображение не принято» vs «модальность не поддерживается» |
| **D5** | §2.2, §2.3, P0V-PROBE-SPLIT/CLASSIFY | Классы причин слиты: 401/403 → `access_error`+`vision_unavailable`; 404 (нет модели) → `unavailable http_404/404`; 5xx/таймаут → `unavailable`; доступность модели и мультимодальность проверяются одним вызовом (`:385-412`, `:415-499`) | Разделить ступени (модель доступна? / принимает изображение?), различать конфигурацию/авторизацию/нет модели/модальность/изображение/rate/таймаут/сбой провайдера; reason-словарь 269 не расширять — различия через `detail`+человекочитаемый `visible_reason` |
| **D6** | §2.5, P0V-PROBE-CACHE | Временные сбои кешируются как вердикт на `MCA_VISION_CAPABILITY_TTL_HOURS` = **6 ч** (`services/mca_gates.py:2211-2214`, кеш `mca_vision.py:218-262`); локально: 503 → `unavailable`, `expired=False` | Короткий TTL для transient (`access_error`/`rate_limited`/`unavailable`, ~60-120 с), длинный/постоянный — только для доказанного `no_vision`; успешная проба снимает transient (переиспользовать семантику `image_capabilities.invalidate`/TTL) |
| **D7** | §2.6, P0V-PROBE-INVALID | `config_revision` = hash(source/base_url/model/api_type/**наличие** ключа) `:202-204` → смена **значения** ключа не инвалидирует; по D1 смена endpoint'а вообще не видна маршруту. Локально: rev до/после ротации ключа одинаков, состояние осталось `vision_unavailable` | Включать в отпечаток hash значения ключа (без значения), сброс кеша при сохранении Vision-настроек и при `POST /api/vision/test`; тест «после смены модели/ключа/endpoint/типа старый вердикт не показывается» |
| **D8** | §3, P0V-PIPE-E2E/BEYOND, P0V-SYMPTOMS | `probe_connection` вызывается **только** из `POST /api/vision/test` (`web/api/routes.py:2271`); задания гейтятся по кешу `resolve_effective_state` (`mca_vision.py:1397-1402`) → без нажатия кнопки каждая джоба падает `capability_check_pending` (прод: 14+10 заданий) | Автоматическая bounded-проба: при сохранении Vision-настроек и/или первой джобе на маршруте (singleflight, антидребезг), с честной причиной при неуспехе; кеш не подменяет факт |
| **D9** | §3, P0V-PIPE-WORKER, P0V-SYMPTOMS | `_tick_body` обрабатывает до 6 джоб **последовательно** (`:1745-1746`), семафор `ANALYSIS_CONCURRENCY=2` бесполезен (`_run_one:1780`), таймаут вызова 60 с (`:921`) при интервале тика 5 с → APScheduler `max_instances=1` пишет skip (прод: 487 за 36 ч), `_tick_lock` (`:1717`) пропускает тихо | Ограниченный параллелизм (`asyncio.gather` под семафором 2), тик короче `VISION_TICK_SECONDS` (claim → фон), метрика/лог занятости вместо тихого skip; перекрытие не должно терять очередь |
| **D10** | §4, P0V-UI-NATIVE | `web/index.html:2127-2130`: `v-if="... && visionStateLine"` и `{{ visionStateLine }}` **без вызова**, при этом `visionStateLine` объявлен в `methods:` (`web/app.js:6025` начало methods; функция `:12622`) → Vue биндит метод и печатает `function () { [native code] }` (ср. собственный комментарий `web/app.js:5620-5622`) | Вызвать метод (или перенести в `computed`) и закрепить тестом, что отданная страница/рендер не содержат `[native code]` |
| **D11** | §4, P0V-UI-REASONS | `POST /api/vision/test` возвращает `reason` (код), но не `visible_reason` (`web/api/routes.py:2273-2283`); UI (`web/app.js:14447-14448`) печатает `Ошибка подключения: vision_unavailable` | Отдавать/использовать человекочитаемую причину (маппинг класса ошибки в текст: неверный ключ / лимит / модель не принимает изображения / провайдер недоступен), код оставлять в деталях |
| **D12** | §4, P0V-UI-DISPLAY | `runtime_snapshot` (`:2116-2164`) не отдаёт ни base_url, ни api_type, ни `detail` последней пробы; `visionStateLine` (`web/app.js:12622-12633`) показывает только «Работает/Не активно + причина + модель + очередь»; карточка модуля показывает «Основная модель» = поле `models.vision_model` и «Статус» = результат клиентского нажатия | Показывать фактического провайдера (host эффективного base_url), модель, тип подключения и результат последней проверки (класс + время) — в карточке Vision (и «Модули», и «LLM Провайдеры»), без секретов |
| **D13** | §1 (L00015), P0V-ARCH-ADAPTER | `api_type` читается (`:195`) и используется только в `config_revision`; адаптеров нет, payload всегда OpenAI-совместимый («неподдерживаемый протокол» не даёт конкретной причины) | Явный список поддерживаемых типов; для неизвестного типа — конкретная причина (`vision_unavailable` + `detail=api_type_unsupported` и человекочитаемый текст), несовместимый payload не отправляется |
| **D14** | §1 (L00011,L00016), P0V-ARCH-BASEURL/NOFAULT | `route.base_url.rstrip("/") + "/chat/completions"` в двух местах (`:432`, `:902`) + дубль `services/cover_style_jobs.py:1899`; ввод полного пути даёт двойной `/chat/completions` (локально воспроизведено); общей нормализации base_url нет | Единая функция сборки chat-URL (`normalize_base_url` + `chat_completions_url`), матрица форм (host, host/, host/v1, host/api/v1, полный путь), переиспользование в `cover_style_jobs`; при уже готовом пути — не дублировать (и не подсказывать пользователю руками) |
| **D15** (наблюдение, не блокер) | §3 (дубли/зависания) | Альбомная отсрочка пересоздаёт джобу (`:1366-1392`): прод показывает 4 `cancelled queue_coalesced` — это churn перевыпуска, а не дубль-обработка (уникальный partial-индекс `services/database.py:221-227`, singleflight `services/task_supervisor.py:168-283` защищают от дублей) | Оставить как есть; при правке воркера — не создавать новую джобу там, где достаточно `set_next_retry` |

## 5. Что уже работает (не переделывать)

- **Раздельные группы каталога** `models_vision` / `keys_vision` / `limits_vision` / `flags_module_vision` (Δ каталога проведена; тесты `tests/test_mca19_block_f_round1043.py:20-30`) и маска секрета (`secret-field`, `keys.vision_api_key` только configured/last4).
- **R17-безопасная диагностика**: события пробы не содержат endpoint/ключ/тело (`mca_vision.py:502-516`); в снапшоте нет секретов; `/api/vision/test` не эхо ключа.
- **Классификация 401/403/429 ≠ «нет vision»** (SC-R2a, `:398-403`) — уже правильно.
- **Дедуп/durable-очередь**: `coalesce_key` + уникальный partial-индекс (`services/database.py:221-227`), CAS-finish анализа (`:1543-1555`), TTL-deferred с честным `vision_skipped_expired` (`:1784-1804`).
- **Безопасная загрузка Telegram** (Bot API, без URL с токеном) и внешних ссылок (SafeFetcher) — `:629-662`.
- **Кеш по содержимому** (`content_hash` + scope) — `:1466-1486`; повторное наблюдение не тратит токены.
- **Шов контекста** `chat_context.collect_media_analysis_blocks` → `render_media_context_async` (`chat_context.py:211-259`) — read-only, без новых vision-вызовов.
- **Готовые переиспользуемые примитивы** для фикса: `services/image_capabilities.py` — `extract_provider_error`/`_sanitize_error_text` (`:340-381`), TTL-кеш с `invalidate(provider, base_url, model)` (`:560-600`); стиль хранилища джоб — `task_supervisor.py`.

## 6. UI и Android (переполнение)

Скриншот владельца в репозитории отсутствует (`plans/features/p0-vision-universal/` содержит только ТЗ и карту), поэтому «на глаз» причина не заявляется. Проверенные факты и кандидаты:

- Поля Vision-формы смонтированы в двух местах: таб «LLM Провайдеры» (`web/index.html:2118-2260`) и карточка модуля «Модули → Распознавание изображений → Модели» (`web/index.html:1753-1890`, данные `workspaceModelCards`, `web/app.js:3405-3415`).
- Классы `.prov-row` / `.prov-label` **не имеют CSS-правил** ни в `web/static/app.css`, ни в `web/index.html` — раскладка строки целиком опирается на Tailwind-утилиты (`flex items-start gap-2`, `w-36 shrink-0`, `flex-1 min-w-0`); наличие `.w-36/.min-w-0/.shrink-0/.flex-1` в `web/static/vendor/tailwind.css` подтверждено. Это хрупкость (пере-сборка Tailwind без этих классов молча ломает подписи), не переполнение.
- `web/static/app.css:1716-1730`: `.prov-grid { grid-template-columns: repeat(auto-fit, minmax(320px,1fr)); }` — минимальный трек 320 px; схлопывание в одну колонку задано **по viewport**: `@media (max-width:479px)` (`:1740-1742`) и `.app-shell.ia-v2 ... @media (max-width:767px)` (`:2612-2622`). Если контейнер уже 320 px при viewport ≥ 480 px (ландшафт/планшет/узкая рабочая колонка вне `ia-v2`), трек шире контейнера ⇒ горизонтальный скролл формы. Комментарии `app.css:2606-2611` фиксируют ровно этот класс дефекта для другого экрана (min-content пол трека выталкивал «Сохранить»).
- Прочие кандидаты: бейдж статуса карточки модуля с длинным текстом ошибки (`web/index.html:1766-1770`, `.badge` без `nowrap` — `app.css:704-710`, но в `header` с `flex items-center`), длинные значения модели/URL в инпутах (`flex-1 min-w-0` — должны ужиматься), `.conn-card/.conn-facts/.conn-fact` с `overflow-wrap: anywhere` (`app.css:2862-2865`) — контрольные точки для замера.

Вывод: переполнение нужно **измерить рендером** (Playwright при ширинах 320/360/390/430 portrait и 640×360 landscape, критерий `documentElement.scrollWidth <= clientWidth` и «все действия достижимы»), а правку — делать по факту замера, а не по догадке. Это уже требование карты (P0V-UI-OVERFLOW: Playwright-матрица + постдеплой-скриншоты).

## 7. Что требует уточнения/проверки перед реализацией

1. **Reason-словарь.** `mca_vision.py:1042-1045` и спека mca-19 фиксируют словарь причин как финальный (269). D5/D11 нужно закрыть существующими кодами + `detail`/`visible_reason`; если Architect решит, что требуется новый код, это санкция каталога/словаря — отдельный вопрос, а не самовольное расширение.
2. **Прод-тумблер.** Глобально `flags.vision_enabled=False`; `flags.*` per-chat, значит фактическое включение ищется в `chat_profiles.chat_params.overrides` (`services/chat_params.py:1-15`). Проверить в срезе P0V-PIPE/деплое, иначе живая приёмка «изображение распознано» упрётся в выключенный флаг (не в defect).
3. **Reduced-scope уточнение по D1:** необходимо решить, поддерживать ли чтение legacy-имени `models.vision_base_url` (совместимость, если оно где-то уже сохранено). Выборка прод-конфигурации (запрос по явному списку из 9 ключей `vision*`) показала только канонические ключи, строки с legacy-именем не встретилось; честная проверка «нет строки `models.vision_base_url`» — отдельный `SELECT` по этому ключу (одна read-only операция в срезе правки).
4. **D9-форма решения:** параллелизм внутри тика против claim+фон. Выбор влияет на наблюдаемость (`heartbeat_at`/`recover_stale`) — решение уровня Architect, в recon только фиксация факта и границ.
5. **D3 (изображение пробы):** нужен источник тестового изображения (сгенерировать в коде vs статический ресурс + лицензия/размер). Требуется решение, чтобы не тащить бинарь в репозиторий без нужды.

## 8. Артефакты и ограничения разведки

- `evidence/recon/prod_recon-2026-10-19.txt` — вывод одного read-only SSH-коннекта (маскированные ключи, без пароля и без секретов; проверено grep’ом на токены ≥24 симв.).
- `evidence/recon/prod_recon.py` — скрипт разведки (пароль читается из `deploy_commands.txt` и не печатается; запись на прод не выполняется).
- `evidence/recon/local_route_probe.py`, `evidence/recon/local_probe_matrix.py` (+ `.txt`) — локальные read-only пробы маршрута и классификации пробы (сеть не используется).
- Ограничения: (а) живые вызовы OpenRouter/провайдеров не делались — «провайдер отвечает 404 на чужую модель» воспроизведено контрактной моделью ответа, а факт `vision_unavailable` подтверждён прод-событиями; (б) рендер-проверка переполнения не выполнялась (нужен работающий web-стенд/`initData`) — вынесена в срез P0V-UI как обязательная; (в) per-chat значения `flags.vision_enabled` не читались (нужен ещё один доступ к PG — сознательно не открывался второй коннект).
- Ни строчки продуктового кода не изменено; изменения ограничены этим доком и `evidence/recon/**`.
