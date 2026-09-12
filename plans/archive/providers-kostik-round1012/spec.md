# Раунд 10.12 — `providers-kostik-round1012` — spec.md (items 1–3)

> **Автор:** @Architect (Step 2, Design). **Статус:** ✅ SANCTIONED — готова к @Builder.
> **Раунд:** 10.12 (HEAD `32d1aa9`; 10.11 завершён и заархивирован, pytest 5172/0).
> **Источник требований:** `plans/current_task.md` §1–§3 (дословно) + `tasks.md` (@PM) + `plans/reports/round10.11_scanner_audit.md`.
> **Скоуп этого файла:** items **1–3**. Финальные items 4 (README/версия/commit/push/деплой/отчёт) — за @Builder/@DevOps (T-1402…T-1408), здесь только parity-заметки.
> **Сопроводительное решение:** `ADR-1012-1.md` (развязка base_url, список фраз, owner-блок).
> **@Architect код не пишет.** Ниже — только спецификация, интерфейсы, `file:line`-адреса и критерии.

---

## §0. Инварианты и внешние рамки

| Инвариант | Требование | Как контролируется |
|---|---|---|
| **Ноль новых PG-DDL** | `services/database.py`/`services/pg_db.py` — без DDL | `git diff -G "CREATE TABLE\|ALTER TABLE\|ADD COLUMN"` пуст; новый параметр — только строка `bot_settings` (DML) |
| **SQLite v8** | `_SCHEMA_VERSION_AGI_MEMORY == 8` | `services/database.py` вне диффа |
| **`bot.py` router order** | не меняется; допускаются ТОЛЬКО DI-аргументы в 4 точках создания `LLMClient` (`bot.py:316,486,515,542`) | дифф бота — только kwargs |
| **`media/`, `filters/`** | не трогать | вне диффа |
| **R17 (секреты)** | новые параметры item 1/3 — **не секреты**; ключи не логируются/не эхо; `.env` не коммитится | grep-секретов + review |
| **R16 (id, не имя)** | `reactions.kostik_user_id`, `reactions.*_user_id` остаются ключами | `test_frontend_tab_mapping` |
| **R10.5-2** | DM read-only для `per_chat=False` не ослабляется | `tests/test_webapp_dm_ui.py`; `web/app.js:2557-2573` сохраняется |
| **Серверный гейт 422** | `routes.py:414-417` **не ослабляется** (по T-1388); фикс 422 — на клиенте | `tests/test_dm_access.py` + новый UI-тест |
| **«Без хардкода»** | адреса/модели/фразы — код-дефолт в `settings` + `hot.get(pg_key, default)` | tests дефолтов + grep |
| **Откат** | feature-flag **не требуется** (UI + аддитивный read-path; прецедент 10.9–10.11); откат — атомарный `git revert` (+ возврат значений в PG через админку) | §6 |

**R10.11-находки, учтённые в design:**

- **R10.11-1** (nested `<details>` делят `localStorage`-ключ) → item 2 **не добавляет** вложенных `<details>` (merged-блоки остаются `<section class="prov-block">`; generic wrapper не трогаем). Регресс не воспроизводится.
- **R10.11-2** (`embedding_fallback_model`: status vs runtime) → item 1 меняет embed-цепочку; держим симметрию `llm_client`/`status_service`, читаем через `hot.get` (см. §1.3).
- **R10.11-3** (устаревшие подсказки «править в .env») → в item 1 обновляем `humanize_embed_error` (`services/llm_client.py:170-172`) и комментарий `config/settings.py:338-345` на «правьте в админке».
- **R10.11-4** (probe + caller `base_url`) → **вне скоупа** (OPEN-Q6 → техдолг, см. §4).
- **R10.11-5** (мёртвый `destroy`) → вне скоупа.
- **R10.11-6** (нет headless-render) → покрываем item 2/3 JS-юнитами + статик-маркерами.
- **R10.6-1** (generic-дубли) → `providerCoveredKeys` обязан покрыть новые ключи (`models.embedding_base_url`, `models.openrouter_transcribe_display_name`); регресс-тест `provider_blocks_single_home`.

---

## §1. Item 1 — развязка base_url провайдеров + фикс 422

### 1.1 Root cause (evidence)

**A. 422 «ключ нельзя переносить на уровень чата».**
- `web/app.js:1242-1255` (`api()`): если `activeChatId != null` — **автоматически** ставит `X-Chat-Id` на КАЖДЫЙ запрос (`:1253-1254`).
- `web/app.js:2181-2225` (`saveBlock()`) и `web/app.js:2928-2987` (`saveConfigItem()`) постят `/api/config` **без опции глобальности**.
- `web/api/routes.py:366-417`: при `X-Chat-Id` и `spec.per_chat == False` → **422** `"{key}: ключ нельзя переносить на уровень чата"` (`:414-417`).
- `services/param_catalog.py:110-119`: `per_chat = category ∈ {prompts,limits,flags,reactions,content,memory} and not secret` ⟹ **все `models.*` и `keys.*` — `per_chat=False`**.
- ⟹ Any provider-поле при выбранном чате (группа/ЛС) падает 422. Класс известен (R10.5-2, `ARCHITECTURE.md:353`).

**B. embedding base_url == main base_url (UI).**
- `web/app.js:362` — `direct_main` → `models.llm_base_url`.
- `web/app.js:417` — `embeddings.subBlocks.embeddings_main` → **тот же** `models.llm_base_url`.
- ⟹ правка main меняет оба значения (один PG-ключ на два блока).

**B′. embedding base_url == main base_url (runtime).**
- `services/llm_client.py:231-256` — единственный `self._base_url`.
- `services/llm_client.py:534-544` (`_post()`) всегда `f"{self._base_url}{path}"`.
- `services/llm_client.py:926-942` (`embed()`) → `self._post("/embeddings", …)` ⟹ primary-эмбеддинги идут на chat-base.
- `bot.py:316-321,486-491,515-520,542-547` — везде `hot.get("models.llm_base_url", settings.LLM_BASE_URL)`.
- `config/settings.py:318` — `LLM_BASE_URL` default `https://apinet.cloud/v1`; **отдельного `EMBEDDING_BASE_URL` нет**.
- `services/status_service.py:163-164` (`main_base`) и `:251-256` (`emb_main` берёт тот же `main_base`) ⟹ карточка «Основная модель памяти» тоже алиасит main.
- `services/param_catalog.py:496-511` — `LLM_BASE_URL` (`models_main`), `EMBEDDING_MODEL_NAME`/`DIM`/`FALLBACK_*` (`models_embeddings`); отдельного embed-base-url нет.

### 1.2 Каталожная дельта item 1 (sanctioned)

| Settings field | PG key | category | group | type | widget | code-default | per_chat | secret |
|---|---|---|---|---|---|---|---|---|
| `EMBEDDING_BASE_URL` **(new)** | `models.embedding_base_url` | models | `models_embeddings` | str | `""` | `https://apinet.cloud/v1` | false | false |
| `OPENROUTER_TRANSCRIBE_DISPLAY_NAME` **(new)** | `models.openrouter_transcribe_display_name` | models | `models_extra_providers` | str | `""` | `""` | false | false |

- `LLM_BASE_URL` **code-default меняется** `https://apinet.cloud/v1` → `https://nano-gpt.com/api/v1` (item 1, «direct answers default»). Значение в PG/`.env` не перезаписывается (см. 1.5).
- `EMBEDDING_BASE_URL` **новый** код-дефолт `https://apinet.cloud/v1`.
- `embeddings_main` в UI привязывается к `models.embedding_base_url` (`web/app.js:417`).
- `status_service.stt_openrouter` переключается на новый display-ключ (см. §2.4); `video_openrouter` остаётся на `models.openrouter_display_name`.
- **Ноль хардкода в хендлерах/UI**: адреса — только `hot.get(pg_key, settings.*_DEFAULT)`.

### 1.3 Read-path (runtime + диагностика)

1. **`config/settings.py`**
   - `:318` `LLM_BASE_URL` default → `https://nano-gpt.com/api/v1`.
   - рядом (`:320`) добавить `EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "https://apinet.cloud/v1")`.
   - комментарий `:338-345` переформулировать: embed-ключи/адреса правятся в админке («LLM Провайдеры → Эмбеддинги»), `.env` — только code-default (R10.11-3).

2. **`services/llm_client.py`**
   - `:231-256` `__init__`: добавить keyword-параметр `embed_base_url: str | None = None`; вычислить `self._embed_base_url`:
     - `hot.get("models.embedding_base_url", embed_base_url if embed_base_url is not None else self._base_url)`,
     - пустое → `self._base_url` (полная обратная совместимость существующих вызовов/test'ов),
     - `.rstrip("/")`.
   - `:534-544` `_post()`: добавить keyword `base_url: str | None = None`; `base = (base_url or self._base_url).rstrip("/")`; `url = f"{base}{path}"`. Логика ретраев/таймаутов/`_get_client` НЕ меняется.
   - `:926-942` `embed()`: primary-вызов → `self._post("/embeddings", {…}, base_url=self._embed_base_url)`. Fallback-каскад (`_post_embed_fallback`) не меняется.
   - `:170-172` `humanize_embed_error`: текст 401 → «проверьте ключ в админке (LLM Провайдеры → Эмбеддинги)» (R10.11-3).
   - **Seam для OD-1 (см. §4):** отдельной функции embed-ключа НЕ вводим; primary embed по-прежнему использует `_current_api_key()` (`keys.llm_api_key`). Если live-проба даст 401 — точечно добавить `_current_embed_api_key()` и `keys.embedding_api_key` (аддитивно).

3. **`bot.py`** (`:316-321, :486-491, :515-520, :542-547`): в каждый `LLMClient(...)` добавить
   ```text
   embed_base_url=hot.get("models.embedding_base_url", settings.EMBEDDING_BASE_URL),
   ```
   Порядок роутеров/остальной код не трогать. Значение читается на момент создания клиента (паттерн ADR-109).

4. **`services/status_service.py`**
   - `:163-164`: оставить `main_base` (chat/base для `llm_main`).
   - добавить `emb_base = StatusService._resolve("models.embedding_base_url", settings.EMBEDDING_BASE_URL)`.
   - `:251-256` `emb_main`: передавать `emb_base` вместо `main_base` (провайдер/хост — из base_url, `_host` без хардкода).
   - `:238-243` `stt_openrouter`: `_display("models.openrouter_transcribe_display_name", "OPENROUTER_TRANSCRIBE_DISPLAY_NAME", "Транскрибация (резерв)")` (см. §2.4).

5. **`web/app.js`**
   - `:417` `embeddings_main` base-field: `models.llm_base_url` → `models.embedding_base_url`.
   - `providerCoveredKeys` (`:2730-2742`) рекурсивно покрывает новый ключ автоматически (проверить тестом).

### 1.4 Фикс 422 (UI, без ослабления сервера)

**Решение:** глобальные (`per_chat === false`) ключи сохраняются ГЛОБАЛЬНЫМ путём — UI **не отправляет `X-Chat-Id`** для них. Серверный гейт `routes.py:414-417` и DM read-only (`app.js:2557-2573`) остаются без изменений.

1. `web/app.js:1242-1255` `api(path, options)`: поддержать `options.global === true` → **не добавлять** `X-Chat-Id`. В `fetch` опция-флаг не должна утекать (собрать headers/инициализатор аккуратно).
2. `web/app.js:2181-2225` `saveBlock(b)`: после сборки `items` определить, все ли ключи глобальные (lookup `configItems` по `key`, `it.per_chat === false`; отсутствие `per_chat` трактуем как per-chat — совместимость со старыми данными). Если все глобальные → `api('/api/config', {method, body, global:true})`. Если смешанные (в merged provider-блоках не встречается) → разделить на два последовательных запроса: global (без `X-Chat-Id`) и chat (текущее поведение). `updated_at` для chat-ветки — `configChatUpdatedAt`; для global — не нужен.
3. `web/app.js:2928-2987` `saveConfigItem(item)`: если `item.per_chat === false` → тот же `global:true`.
4. DM: `canEditConfig` (`:2557-2573`) уже отключает `per_chat=false` в DM → редактирование невозможно → 422 не возникает; **не менять**.
5. `kv-editor`/новый `list-editor`: постят через `saveConfigItem` (per-chat `reactions.*`), 422-специфика не затрагивает.

> Почему не серверная делегация: T-1388 прямо требует «серверный гейт не ослаблять»; строка чата не должна молча писать в глобал от имени local-админа чата. Клиентский путь прозрачен и проверяем.

### 1.5 Миграция / `.env` (OPEN-Q1)

- **PG авторитетен**: `hot.get(pg_key, settings_default)`. Существующее значение `models.llm_base_url` в PG **не перезаписывается** (`migrate_env_to_pg` — `ON CONFLICT DO NOTHING`; DML, без DDL).
- **Новая строка** `models.embedding_base_url` сидится существующим DML-механизмом (`iter_migratable`/ConfigCache) со значением `https://apinet.cloud/v1`; при отсутствии кэша — DI-дефолт из `bot.py` (тот же адрес). ⟹ после деплоя эмбеддинги уходят на `apinet.cloud/v1`, direct — на текущее PG-значение (nano-gpt).
- **`.env.example:146-151`**: `LLM_BASE_URL=https://nano-gpt.com/api/v1`, добавить `EMBEDDING_BASE_URL=https://apinet.cloud/v1` + комментарий «адреса/ключи правятся в админке; env — дефолт для пустой БД». Продовый `.env` не трогать в git (R17).
- ⚠️ **Ключ не развязывается** в этом раунде: primary-эмбеддинги ходят с `keys.llm_api_key`. Если ключ, действующий на nano-gpt, не действует на apinet.cloud — primary-эмбеддинг получит 401 и уйдёт в существующий `EMBEDDING_FALLBACK_*` (Google). Проверка — live-проба «Эмбеддинги → Основная модель»; при 401 — эскалация OD-1 (§4).

### 1.6 Acceptance criteria (item 1)

| # | Критерий | Проверка |
|---|---|---|
| AC-1.1 | Правка `models.llm_base_url` при активном чате (группа) сохраняется без 422; запись уходит в global-слой | JS-юнит `saveBlock` (global-опция) + API-тест |
| AC-1.2 | `models.embedding_base_url` — независимый параметр; правка main (`models.llm_base_url`) **не меняет** embed-base (UI, runtime, status) | unit `llm_client`/`status_service` + JS-маркер |
| AC-1.3 | Код-дефолты: embed = `https://apinet.cloud/v1`, direct = `https://nano-gpt.com/api/v1`; в хендлерах/UI — ноль литералов | test дефолтов + grep |
| AC-1.4 | `LLMClient.embed()` POST'ит на `_embed_base_url`, chat — на `_base_url`; регрессий chat нет | `test_llm_client` + новый тест |
| AC-1.5 | Новый ключ — first-class каталог; `providerCoveredKeys` его покрывает (нет generic-дубля); счётчики задокументированы (Δ) | `test_param_catalog` + `test_webapp_round1012_ui` |
| AC-1.6 | Серверный гейт 422 и DM read-only не ослаблены; существующие `test_dm_access`/`test_webapp_dm_ui` зелёные | pytest |
| AC-1.7 | Ноль PG-DDL; SQLite v8; `bot.py`-порядок роутеров не тронут | diff/grep |

### 1.7 Tests (item 1)

- `tests/test_llm_client.py` (или новый `tests/test_llm_embed_base_1012.py`): embed идёт на embed-base, chat — на chat-base; пустой embed-base → старое поведение; `hot.get`-приоритет; `_post(base_url=…)` не ломает ретраи/фоллбэк-каскад.
- `tests/test_status_service.py:225` — `llm_main.provider == "nano-gpt.com"` (код-дефолт direct изменился); новый кейс `emb_main.base_url == "https://apinet.cloud/v1"` / `provider == "apinet.cloud"` при пустом кэше.
- `tests/test_param_catalog.py:54` — Settings 372 → **376**; группа `models.embedding_base_url` == `models_embeddings`, `per_chat is False`.
- `tests/test_webapp_api.py:1198` — categorized 376 → **380**; `:1053` (явное значение apinet round-trip) не трогать.
- `tests/test_webapp_round1011_ui.py:138-142` — REGISTRY 400 → **404**, Settings 372 → **376**.
- Новый `tests/test_webapp_round1012_ui.py`: `embeddings_main` использует `models.embedding_base_url`; `api()` поддерживает global-опцию; `saveBlock`/`saveConfigItem` шлют global без `X-Chat-Id`; `providerCoveredKeys` содержит новый ключ.
- `tests/js/routing_test.js`: расширить кейс saveBlock — при `activeChatId != null` и `per_chat === false` `api` вызывается с `{global:true}`.

### 1.8 Parity note

- Старые 4-аргументные вызовы `LLMClient(base_url,key,model,embed_model)` сохраняют прежнее поведение (embed на `base_url`) ⟹ существующие тесты не ломаются.
- `status_service.llm_main` меняет провайдера только при пустом кэше (код-дефолт); в проде значение PG авторитетно.
- `.env` прод не меняется; меняется только `.env.example`.

---

## §2. Item 2 — блоки подключения, display-name, верификация STT vs summary

### 2.1 Результат верификации «модели перепутаны?» — **СВОПА НЕТ** (подтверждено `file:line`)

**Транскрибация** (расшифровка слов: голосовые / видео / кружок):
- Точка входа STT голосовых: `handlers/voice_transcription.py:184` → `SmartModule/service.py:78-116` `VoiceTranscriber.transcribe_voice`.
- Стратегии: `SmartModule/service.py:69-73` → `(GroqTranscriber, OpenRouterTranscriber)`.
- Groq: `SmartModule/transcriber/groq_transcriber.py:20-21` (`whisper-large-v3`), hot `models.groq_base_url`/`models.groq_transcribe_model` (`:52,127-128`), ключ `keys.groq_api_key` (`:47`).
- OpenRouter-фолбэк: `SmartModule/transcriber/openrouter_transcriber.py:33-36`, hot `models.openrouter_base_url`/`models.openrouter_transcribe_model` (`:73-74,160-161`), ключ `keys.openrouter_api_key` (`:68`); идёт через `chat.completions` + `input_audio` (`:143-164`).
- Видео/кружок STT: `handlers/youtube.py:371-377` `_transcribe_video_file`→`transcribe_voice`; ветка `mode == "transcript"` (`:867-894`) и STT-фолбэк summary-ветки (`:910-924`).

**Саммаризация видео** (выжимка по видео):
- `handlers/youtube.py:974` `summarize_cascade` (YouTube-URL) и `:898` `_publish_and_cascade` → `services/youtube_summarizer_service.py:101-147,254-303`; медиа-URL: `summarize_media_url` (`:590,697`).
- Уровни L1/L2: `services/youtube_summarizer_service.py:102-103,255-256` — `models.video_primary_model` / `models.video_fallback_model`; транспорт — `services/video_cascade_client.py` (`content: video_url`, `models.openrouter_base_url`, `keys.openrouter_api_key`).

**Вывод:** `models.groq_*` + `models.openrouter_transcribe_model` → транскрибация; `models.video_primary_model` + `models.video_fallback_model` → саммаризация. **Функционального свопа в коде нет.** Причина ощущения владельца — общий `models.openrouter_display_name`/`models.openrouter_base_url`/`keys.openrouter_api_key` у STT-фолбэка и видео-блока + старые подписи. **Фикс «свопа» не требуется**; устраняем UI-путаницу (§2.2–2.4).

Семантика соединяется ВЕРНО, в т.ч. для кружка: `mode=="transcript"` → STT-модели; `mode=="summary"` → видео-модели.

### 2.2 Новая структура `PROVIDER_BLOCKS` (`web/app.js:358-466`)

Переходим на формат parent-блок + `subBlocks` (как у `embeddings`). Существующий шаблон `b.subBlocks` (`web/index.html:815-850`) уже даёт per-sub-block поля, «Сохранить» и «Проверить» — переиспользуем.

| parent id | parent title | sub-block id | sub-block title | поля (display / base / model / key) |
|---|---|---|---|---|
| `direct` | **Прямые ответы** | `direct_main` | **Основная модель** | `models.llm_display_name` / `models.llm_base_url` / `models.llm_model_name` / `keys.llm_api_key` |
| | | `direct_fallback` | **Запасная модель** | `models.llm_fallback_display_name` / `models.llm_fallback_base_url` / `models.llm_fallback_model` / `keys.llm_fallback_api_key` |
| `transcription` | **Транскрибация** | `transcribe_groq` | **Модель транскрибации** | `models.groq_display_name` / `models.groq_base_url` / `models.groq_transcribe_model` / `keys.groq_api_key` |
| | | `transcribe_openrouter` | **Запасная модель транскрибации** | `models.openrouter_transcribe_display_name` **(new)** / `models.openrouter_base_url` / `models.openrouter_transcribe_model` / `keys.openrouter_api_key` |
| `video_summary` | **Саммаризация видео** | `video_summary_openrouter` | **Саммаризация видео** | `models.openrouter_display_name` / `models.openrouter_base_url` / `models.video_primary_model` / `keys.openrouter_api_key` |
| | | `video_fallback` | **Запасная модель саммаризации видео** | `models.openrouter_display_name` / `models.openrouter_base_url` / `models.video_fallback_model` / `keys.openrouter_api_key` |
| `embeddings` | **Эмбеддинги** | `embeddings_main` | Основная модель | `models.embedding_display_name` / **`models.embedding_base_url`** / `models.embedding_model_name` / `keys.llm_api_key` |
| | | `embeddings_fallback1` | Фоллбэк 1 | (без изменений) |
| | | `embeddings_fallback2` | Фоллбэк 2 | (без изменений) |

Advanced-блоки (`llm_guard`, `search_keys`, `media_share`, `web/index.html:946-994`) — **без изменений** (display-полей нет → подпись = статичный `b.modules`).

**Порядок/id:** `direct_main` идёт до `direct_fallback`; `transcribe_groq` до `transcribe_openrouter`; `video_summary_openrouter` до `video_fallback` — старые маркеры `tests/test_webapp_round1011_ui.py:111-115` продолжают находиться (id сохранены).

### 2.3 Динамическая маленькая надпись «Название модели»

- Взять за правило: **подпись рядом с заголовком = значение первого поля блока/подблока с `role === ''`** (поле «Название модели»).
- Новый резолвер уровня `methods` (reading reactive deps): `blockDisplayName(x)` →
  1. найти в `x.fields` поле с `role === ''` (или `x.displayKey`) — первое;
  2. `blockFieldValue(f)`; если непустая строка → вернуть её;
  3. иначе — `x.modules` (сохранённый прежний текст, **не пусто и не хардкод**).
- `web/index.html:808-811` (connection parent) и `:948-951` (advanced parent), а также заголовок подблока `:818`:
  - parent: `{{ b.title }}` + `<span class="prov-modules">{{ blockDisplayName(b) }}</span>`;
  - sub-block: `{{ sb.title }}` + `<span class="prov-modules">{{ blockDisplayName(sb) }}</span>`;
  - для parent-блоков без display-поля (`direct`/`transcription`/`video`/`embeddings`) — fallback `b.modules` (роль-подпись).
- «Трансляция» = живая: метод пере-вычисляется при изменении `blockDrafts`/`configItems` (Vue tracking). Fallback при пустом display-name — прежний текст.

### 2.4 Общие поля OpenRouter — решение (OPEN-Q2)

- `models.openrouter_base_url` и `keys.openrouter_api_key` у STT-фолбэка и видео — **физически один аккаунт OpenRouter** ⟹ **оставляем общими**; добавляем `sb.note` в обоих блоках: «Адрес и ключ общие с блоком „…“ — один аккаунт OpenRouter».
- `models.openrouter_display_name` — **оставляем у видео-блока** (каталог `models_video_summary`, `param_catalog.py:570-571`).
- **Новый** `models.openrouter_transcribe_display_name` — для STT-фолбэка (каталог `models_extra_providers`). Устраняет скрытую связь display-name двух разных ролей.
- `status_service.stt_openrouter` (`:238-243`) переключается на новый ключ; `video_openrouter` (`:244-250`) — без изменений.

### 2.5 Acceptance criteria (item 2)

| # | Критерий | Проверка |
|---|---|---|
| AC-2.1 | Рядом с header каждого подключения (parent/sub-block) — «Название модели» (динамически, live), пусто → прежний текст | JS-юнит + статик-маркер |
| AC-2.2 | main+fallback — один блок «Прямые ответы»; «Запасная модель» | UI-маркер/юнит |
| AC-2.3 | Groq+OpenRouter STT — один блок «Транскрибация»; «Модель транскрибации»/«Запасная модель транскрибации» | UI-маркер |
| AC-2.4 | video primary+fallback — один блок «Саммаризация видео»; «Саммаризация видео»/«Запасная модель саммаризации видео» | UI-маркер |
| AC-2.5 | Семантика STT/summary подтверждена `file:line`; своп отсутствует | §2.1 + тест wiring |
| AC-2.6 | Все поля/кнопки сохранены; generic-дублей нет (`providerCoveredKeys` рекурсивно); DM read-only цел; R10.11-1 не воспроизведён | `test_webapp_round1012_ui`, `test_dm_access`, `test_webapp_round1011_ui` (адаптирован) |

### 2.6 Tests (item 2)

- Новый `tests/test_webapp_round1012_ui.py`: merged parent-блоки; заголовки; `blockDisplayName` динамичен (пусто → fallback); `models.openrouter_transcribe_display_name` в транскрипции; `embeddings_main` base = `models.embedding_base_url`.
- `tests/js/routing_test.js`: юниты — `providerConnectionBlocks` содержит 4 parent-блока (direct/transcription/video/embeddings) + advanced; `blockDisplayName` (draft/пусто); `providerCoveredKeys` покрывает все поля subBlocks.
- `tests/test_webapp_round1011_ui.py:111-114` — сохранить (id `video_summary_openrouter` до `video_fallback`).
- Wiring-тест (например, расширение `tests/test_youtube_summary_*` / `tests/test_transcribe_*`): `mode=="transcript"` зовёт `voice_transcriber`, `mode=="summary"` — видео-каскад; `models.groq_transcribe_model`/`models.openrouter_transcribe_model` не используются видео-каскадом, а `models.video_*` — транскрибацией.

### 2.7 Parity note

- Net-эффект: 6 provider-блоков схлопываются в 3 parent (direct/transcription/video) + embeddings (был) + 3 advanced; количество полей не уменьшается, все ключи остаются редактируемыми.
- `providerConnectionBlocks`/`providerAdvancedBlocks` (`:964-973`) — computed, фильтр по `zone`; шаблон — bare-ref. Сохранить.
- Существующие статик-тесты, ищущие `id: 'direct_main'`/`transcribe_groq`/`video_fallback`, остаются зелёными (id переехали в subBlocks, строки в JS присутствуют).

---

## §3. Item 3 — фразы Костика в PERMsoc (редактируемый список)

### 3.1 Root cause (evidence)

- `handlers/kostik.py:30-39` — литерал `KOSTIK_REPLIES` (8 захардкоженных фраз), `:54` `random.choice(KOSTIK_REPLIES)`.
- Гейт: `:42` `PermsocGateFilter("kostik")` + `:43` `UserIdFilter(hot.get("reactions.kostik_user_id", settings.KOSTIK_USER_ID))`.
- Модуль: `services/permsoc.py:55-57` `PermsocModule("kostik", …, sub_flag_key=None, …)` ⟹ только master `flags.permsoc_enabled`.
- Группы: `reactions_kostik` (`param_catalog.py:311-312`; `KOSTIK_USER_ID` `:1139-1140`); `limits_kostik` (`:194-195`) с `KOSTIK_REPLY_PROBABILITY` (`:750-751`).
- **Частота ЕСТЬ:** `settings.KOSTIK_REPLY_PROBABILITY` (`config/settings.py:165`), `.env.example:22`, pg `limits.kostik_reply_probability`, чтение `handlers/kostik.py:47-48`. В мини-аппе — группа «Костик: лимиты».
- UI PERMsoc: `PERMSOC_OWNER_BLOCKS` (`web/app.js:473-494`) — блоков `kostik` НЕТ (группа попадает в «Общее»). Виджета списка строк нет; KV-редактор `keyvalue` (`index.html:1107-1112,1385-1389`, tpl `:3124-3155`, `app.js:4713-4826`).

### 3.2 Storage (OPEN-Q5) — JSON-список в одном параметре

**Решение:** один параметр `type="json"` + **новый виджет `list`** (массив строк). Индексированные ключи (`..._1..N`) отвергаем (ломают каталог, добавляют N параметров); CSV-строку отвергаем (нет отдельных полей/удаления).

| Settings field | PG key | category | group | type | widget | per_chat | secret |
|---|---|---|---|---|---|---|---|
| `KOSTIK_REPLIES` **(new)** | `reactions.kostik_replies` | reactions | `reactions_kostik` | json | `list` | true | false |

- Значение: JSON-массив непустых строк. `param_catalog._cast_to_type` (json) и `pg_db.coerce_catalog_value` уже корректно принимают список (tuple→list).
- Код-дефолт — `config/settings.py` константа `DEFAULT_KOSTIK_REPLIES: tuple[str, ...]` + поле `KOSTIK_REPLIES: tuple[str, ...] = DEFAULT_KOSTIK_REPLIES` (без нового `.env`-ключа).
- Порядок фраз сохраняется (JSON-массив); пустой массив → **безопасное молчание** (не падать; `random.choice` не вызывается).

### 3.3 Дефолтный пул фраз (sanctioned, 18+, 14 шт.)

4 фразы владельца (дословно) + 10 новых в том же духе:

1. «Папочка, только не в попочку»
2. «Папа Костя, только не там»
3. «Папа Костя, можно хотя бы сегодня без конфетки?»
4. «Daddy, i'm scared, убери это пожалуйста»
5. «Папа Костя, ты хоть смазку купил или опять по-сухому?»
6. «Папочка, а можно не в рот, я подавлюсь»
7. «Папа Костя, мама узнает — нам обоим влетит»
8. «Daddy, please, не по бутылке, я же просил»
9. «Папа Костя, ты обещал без наручников в этот раз»
10. «Папочка, я всё сделаю, только не при друзьях»
11. «Папа Костя, а презерватив ты тоже „забыл“?»
12. «Daddy, not the belt, я же взрослый мужик»
13. «Папа Костя, у меня после прошлого раза сесть больно»
14. «Папочка, ты сказал „последний раз“, а вон опять»

Все — непустые, уникальные, 18+ (внутренний инструмент). Хранятся как code-default параметра; в UI — редактируемые поля.

> **Ревью-правка (раунд 10.12, follow-up):** фразы #5 и #12 первоначальной
> редакции («я ещё маленький для такого» / «i'll be a good boy») были
> заменены на adult-to-adult формулировки, чтобы исключить minor-coded
> фрейминг (требование владельца/ревьюера). Остальные 12 фраз —
> дословно. Shipped-дефолт = `config.settings.DEFAULT_KOSTIK_REPLIES`.

### 3.4 Read-path (`handlers/kostik.py`)

- Убрать литерал `KOSTIK_REPLIES`; handler на каждом вызове читает `raw = hot.get("reactions.kostik_replies", settings.KOSTIK_REPLIES)` и нормализует: принимать list/tuple/JSON-строку; оставлять только непустые `str`; `strip`.
- Логика частоты — без изменений: `prob = hot.get("limits.kostik_reply_probability", settings.KOSTIK_REPLY_PROBABILITY)`; `prob <= 0` → return; `phrases` пуст → return (тихое молчание); иначе `random.choice(phrases)`.
- Backward-compat: сохранить `KOSTIK_REPLIES = tuple(settings.KOSTIK_REPLIES)` как thin-alias для существующих импортов (`tests/test_kostik.py:13`, `tests/test_direct_chat_handlers.py:458`); **канон** — `config.settings.DEFAULT_KOSTIK_REPLIES`.
- `logger.debug` — без изменения (текст фразы не секрет, но и не обязателен).

### 3.5 Owner-блок, тумблер, частота (OPEN-Q3/Q4)

1. **Owner-блок `kostik`** в `PERMSOC_OWNER_BLOCKS` (`web/app.js:473-494`), вставляем после `slavik`:
   - `id: 'kostik'`, `title: 'Костик'`, `icon` — существующий набор глифов;
   - `keys: ['reactions.kostik_user_id', 'reactions.kostik_replies', 'limits.kostik_reply_probability']`;
   - `groups: ['reactions_kostik', 'limits_kostik']`;
   - `_ownerDescription` (`:2839-2847`) + `kostik: 'ID, фразы-реплики и вероятность ответа.'`.
2. **Тумблер блока — новый под-флаг** `flags.kostik_enabled` (OPEN-Q4): иначе `<summary>`-тумблер owner-блока не к чему привязать (шаблон `index.html:1027-1036` всегда рисует переключатель).
   - `services/permsoc.py:55-57`: `PermsocModule("kostik", …, sub_flag_key="flags.kostik_enabled", …)`.
   - **Обязательно** `DEFAULT_SUB_FLAGS["flags.kostik_enabled"] = True` (`permsoc.py:79-83`) — иначе `module_enabled` даст default `False` и Костик замолчит (регресс).
   - `PERMSOC_TOGGLE_KEYS` (`app.js:496-499`) += `'flags.kostik_enabled'`; `permsocModuleBadge` (`:1791-1795`) `subFlags.kostik = 'flags.kostik_enabled'`.
   - Каталог: `KOSTIK_ENABLED` (`flags`, group `flags_permsoc`, bool, default `True`, per_chat true).
3. **Частота (OPEN-Q3):** отдельный cooldown **не нужен** — частота уже регулируется вероятностью `limits.kostik_reply_probability` (0.0…1.0); она переезжает в блок Костика через claim группы `limits_kostik`. Кулдаун добавим только по явному запросу владельца (вне раунда).

### 3.6 UI: виджет `list` + `list-editor` (плотно)

- `web/app.js` (рядом с `kv-editor`, `:4709-4826`): новый компонент `list-editor`:
  - `inject root`, props `item`, `canEdit`; data `rows: []`, `maxRows` (напр. 100);
  - `sync()` из `item.value` (если массив; JSON-строка → распарсить; иначе `[]`);
  - `addRow()` (в конец, пустая строка), `removeRow(i)`, `save()` → `item.value = rows` (обрезка/отброс пустых) и вызов `root.saveConfigItem(item)` (учёт per-chat/global routing, 409-конфликты);
  - шаблон `#list-editor-tpl`: строки `<input class="field">` + кнопка удаления, **плотно** (`mb-1`/`mb-0.5`), кнопка «+ Добавить фразу», «Сохранить»; пустой список — без ошибки (блок «список пуст — Костик молчит»).
- `web/index.html`: ветка `v-else-if="item.widget === 'list'"` в **обоих** generic-шаблонах — desktop (`~:1107`) и mobile/compact (`~:1385`), по образцу `item.widget === 'keyvalue'`; плюс `<script type="text/x-template" id="list-editor-tpl">` рядом с `kv-editor-tpl` (`:3124`).
- `web/app.js` `loadConfig` (`:2647-2650`): не строкифаймить json при `widget` непустом — для `list` массив сохраняется как есть (условие `!item.widget` уже это обеспечивает; проверить тестом).
- `saveConfigItem` (`:2928-2987`): json-массив проходит без парсинга, уходит как есть.

### 3.7 Acceptance criteria (item 3)

| # | Критерий | Проверка |
|---|---|---|
| AC-3.1 | Все фразы — в настройках; литерала в хендлере нет; дефолт = 4 владельца + 10 новых | `test_kostik` (обновлён) + grep |
| AC-3.2 | Каждая фраза — отдельное плотное поле; add/delete/save работают | JS-юнит `list-editor` + live |
| AC-3.3 | Handler читает через `hot.get`; пустой список безопасен (молчание) | `test_kostik` (пустой list) |
| AC-3.4 | Параметр частоты присутствует (вероятность) и доступен в блоке Костика | `test_param_catalog`/UI-маркер |
| AC-3.5 | Блок Костика в PERMsoc; под-флаг `flags.kostik_enabled` default ON (поведение сохранено) | `test_permsoc` + `test_webapp_round1012_ui` |
| AC-3.6 | R16/R17: `reactions.kostik_user_id` — id-ключ; секретов нет | тесты |

### 3.8 Tests (item 3)

- `tests/test_kostik.py`: пул = 14 (4 фразы владельца присутствуют дословно, ≥10 новых), все непустые/уникальные; правка через hot (`reactions.kostik_replies`) меняет пул; пустой список → `reply` не вызван; существующие prob-кейсы зелёные.
- `tests/test_permsoc.py:37-39`: `sub_flag_key is None` count 2 → **1** (только `alan`); `_MODULE_BY_ID['kostik'].sub_flag_key == 'flags.kostik_enabled'`; `DEFAULT_SUB_FLAGS['flags.kostik_enabled'] is True`; master ON + sub-flag OFF → kostik молчит.
- `tests/test_param_catalog.py`: новые записи (category/group/type/widget/per_chat); Settings count 376.
- `tests/test_frontend_tab_mapping.py:165-166` — не ломать (группы те же).
- Новый `tests/test_webapp_round1012_ui.py`: owner-блок `kostik`; `item.widget === 'list'` в обоих шаблонах; `#list-editor-tpl`; `PERMSOC_TOGGLE_KEYS['flags.kostik_enabled']`.
- `tests/js/routing_test.js`: `list-editor` add/remove/save (через `saveConfigItem`), `_permsocOwnerGroups` кладёт фразы/вероятность в `kostik`.

### 3.9 Parity note

- Дефолт `flags.kostik_enabled=True` + `DEFAULT_SUB_FLAGS` ⟹ поведение Костика по умолчанию идентично прежнему (отвечает при master ON).
- `KOSTIK_REPLIES`-alias сохраняет импорты; при monkeypatch `handlers.kostik.settings` alias остаётся статичным, но handler читает hot/settings заново.
- Прод-фразы в PG не существуют до первого сохранения ⟹ действует код-дефолт из 14 фраз.

---

## §4. Open Questions — решения @Architect

| ID | Решение |
|---|---|
| **OPEN-Q1** (дефолты/миграция) | `LLM_BASE_URL` (direct) code-default → `https://nano-gpt.com/api/v1`; новый `EMBEDDING_BASE_URL` → `https://apinet.cloud/v1`. PG/hot авторитетны; существующее значение `models.llm_base_url` не перезаписывается (DML `DO NOTHING`); новая строка сидится дефолтом. `.env.example` обновляется, продовый `.env` — нет. |
| **OPEN-Q2** (общий OpenRouter) | base_url + ключ — **общие** (один аккаунт), с UI-note; **display-name разделяем**: новый `models.openrouter_transcribe_display_name` (STT) и `models.openrouter_display_name` (видео). |
| **OPEN-Q3** (частота Костика) | Оставляем `limits.kostik_reply_probability` как единый регулятор; claim группы `limits_kostik` в блок Костика. Новый cooldown не вводим. |
| **OPEN-Q4** (owner-блок `kostik`) | Создаём owner-блок `kostik`; тумблер — новый под-флаг `flags.kostik_enabled` (default True), иначе `<summary>`-тумблер не привязать. |
| **OPEN-Q5** (виджет списка) | Новый `widget="list"` + компонент `list-editor`; хранение — один `type="json"` параметр `reactions.kostik_replies` (массив строк). Индексированные ключи/CSV отвергнуты. |
| **OPEN-Q6** (probe caller base_url, R10.11-4) | **Вне скоупа 10.12**, остаётся info-техдолгом (global-admin-only; R17-эхо не задет). |
| **OD-1 (владелец)** | Развязка **только base_url** (в рамках item 1). Ключ эмбеддингов остаётся общим `keys.llm_api_key`. Если live-проба «Эмбеддинги → Основная модель» после деплоя даст 401 (ключ не действует на apinet.cloud) — аддитивно ввести `keys.embedding_api_key` (secret, `keys_llm`) + `_current_embed_api_key()` с fallback на `keys.llm_api_key`. Требуется подтверждение владельца / результат live-пробы. |

---

## §5. Sanctioned catalog delta (item 1–3)

**Базовая линия (HEAD `32d1aa9`):** REGISTRY **400**, GROUPS **90**, Settings **372**, mapped (`_TAB_BY_GROUP`) **88**, TAB_RULES 19, categorized **376**.

| # | Параметр | Δ REGISTRY | Δ Settings | GROUPS | mapped |
|---|---|---|---|---|---|
| 1 | `models.embedding_base_url` (`EMBEDDING_BASE_URL`, models/`models_embeddings`, str) | +1 | +1 | 0 | 0 |
| 2 | `models.openrouter_transcribe_display_name` (`OPENROUTER_TRANSCRIBE_DISPLAY_NAME`, models/`models_extra_providers`, str) | +1 | +1 | 0 | 0 |
| 3 | `reactions.kostik_replies` (`KOSTIK_REPLIES`, reactions/`reactions_kostik`, json, widget=list) | +1 | +1 | 0 | 0 |
| 4 | `flags.kostik_enabled` (`KOSTIK_ENABLED`, flags/`flags_permsoc`, bool, default True) | +1 | +1 | 0 | 0 |
| | **Итого (sanctioned)** | **400 → 404** | **372 → 376** | **90 → 90** | **88 → 88** |
| | categorized | | | | 376 → **380** |
| OD-1 (если подтверждён) | `keys.embedding_api_key` (keys/`keys_llm`, str, secret) | +1 (405) | +1 (377) | 0 | 0 |

- Групп **не добавляем** — все новые параметры ложатся в уже существующие и уже смапленные группы (TAB_LLM_PROVIDERS / TAB_PERMSOC), поэтому `mapped` не растёт.
- Групповые описания/заголовки групп не меняются (кроме, при желании, уточнения описания `reactions_kostik`).
- **Ноль PG-DDL**: новые ключи — строки `bot_settings` (jsonb/bool) через существующий `ConfigCache.set`.
- `LLM_BASE_URL` default-смена — **не** меняет счётчики.

---

## §6. Feature flags / progressive delivery

- **Feature-flag не требуется.** Изменения: админ-UI (item 2/3), аддитивный серверный read-path (новый base_url), вынос строк в каталог. Прецедент 10.9–10.11: UI/config-only ⟹ flag не вводится.
- **Kill-switch:** `flags.kostik_enabled` (new) даёт точечное отключение реплик Костика; отдельного flag для embed-base не вводим (откат значения в PG достаточен).
- **Progressive rollout неприменим** (внутренний инструмент одного владельца).
- **Rollback:** атомарный `git revert`; при изменённых значениях в PG — вернуть через админку (идемпотентно, без DDL); деплой-откат — `git revert` + `systemctl restart admin_bot`.

---

## §7. Scope boundaries

**В скоупе:** items 1–3 (§1–§3), каталожная дельта (§5), тесты §1.7/§2.6/§3.8, обновление `.env.example` и текстов-подсказок (R10.11-3).

**Вне скоупа (не делать в 10.12):**
- Развязка embed-API-ключа (OD-1) — только по подтверждению.
- OPEN-Q6 / R10.11-4 (probe hardening), R10.11-5 (мёртвый `destroy`).
- Изменение серверного гейта 422 / DM-политики.
- Разделение `models.openrouter_base_url`/`keys.openrouter_api_key` (остаются общими).
- Любые PG-DDL, изменения `media/`, порядка роутеров, системных промптов.

**Items 4 (README/версия/commit/push/деплой/отчёт)** — по `tasks.md` T-1402…T-1408 за @Builder/@DevOps. Обязательная синхронизация:
- `APP_VERSION` (`config/settings.py:1088`, `2.55.0`) + cache-bust `?v=__APP_VERSION__`; не ломать `test_app_version_matches_readme` / `test_index_version_query_param`.
- README шапка (ироничный тон), таблица env (новый `EMBEDDING_BASE_URL`, смена `LLM_BASE_URL`), changelog 10.12.

---

## §8. Handoff

**@Builder** — задачи `tasks.md` §3.A/B/C (T-1383…T-1401) по этому spec + `ADR-1012-1.md`.
**@DevOps** — T-1406…T-1408 (коммит/пуш/деплой/отчёт); пароль деплоя — только из `plans/current_task.md`, в документацию не переносится (R17).

`@Orchestrator Architecture phase complete, passing the baton.`
