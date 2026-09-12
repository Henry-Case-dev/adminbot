# Раунд 10.12 — `providers-kostik-round1012` (tasks.md)

> **✅ СТАТУС: ЗАВЕРШЕНО И ЗААРХИВИРОВАНО (13.09.2026, @PM Step 8 Archive Phase).**
> Фича перенесена из `plans/features/providers-kostik-round1012/` в
> **`plans/archive/providers-kostik-round1012/`** (плоский kebab-case, как существующие архивы).
> **Финальные метрики:** полный pytest — **5211 passed / 0 failed** (база 10.11 = 5172; **+39**);
> `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
> каталог: **REGISTRY 405 / GROUPS 90 / Settings 377** (санкционированный прирост — новые параметры
> `base_url` embed/direct и редактируемый список фраз Костика, ADR-1012-1); R17-скан чист.
> @Reviewer — **APPROVED WITH MINOR ISSUES** (дефекты 1–4 закрыты @Builder); @Scanner — **CLEAN**
> (low закрыты follow-up; `plans/reports/round10.12_scanner_audit.md`); @Architect — архитектура влита
> в `plans/ARCHITECTURE.md` (**§33**).
> Артефакты сохранены: `spec.md`, `ADR-1012-1.md`, `tasks.md` (этот файл).
> **⚠️ ОТКРЫТО (PROD-деплой, за @DevOps, пост-архив):** README (ироничный тон) / `APP_VERSION` /
> cache-bust; **русский** commit; push; `git pull` → `systemctl restart admin_bot` → `status`;
> `/api/health` **200**; 0 ERROR/Traceback; маркеры 10.12 в `/web/` и `/web/app.js`.
> **⚠️ ОТКРЫТО (live Android/Telegram QA, за владельцем/QA):** правка base_url обоих провайдеров
> (embed ≠ direct, без взаимного алиасинга); маленькая надпись «Название модели» у всех подключений;
> merged-блоки (основная+запасная, транскрибация, саммаризация видео); список фраз Костика
> (add/delete/save) и реальный ответ Костику.
> **ВНИМАНИЕ:** статусы `[ ]` ниже — снимок на момент архивации; пост-архивная фаза @DevOps/QA
> (PROD-деплой + live Android) выполняется ПОСЛЕ архивации.
>
> **Статус на момент реализации (историческое):** 🟢 ITEMS 1–3 РЕАЛИЗОВАНЫ (@Builder); проверены
> @Reviewer (**APPROVED WITH MINOR ISSUES**, дефекты 1–4 закрыты), @Scanner (**CLEAN**, low закрыты).
> **Раунд подтверждён:** **10.12** (HEAD `32d1aa9`, 10.11 завершён и заархивирован).
> **Нумерация:** **T-1382…** (продолжает T-1381 — финал 10.11).
> **Преемник:** 10.11 `llm-providers-refactor-round1011` (архив; commit `3624789`, прод health 200, pytest 5172).
> **Базовая линия:** pytest **5172 passed / 0 failed**; `node --check web/app.js` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; каталог-инвариант **REGISTRY 400 / GROUPS 90 /
> Settings 372 / mapped 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19.
> **Источник:** `plans/current_task.md` (дословно, §1). Секреты/креды деплоя — только из
> `plans/current_task.md`, **в этот файл и коммит не попадают** (R17).
> **@PM код не пишет.** Архитектурные решения (новая параметр-модель base_url, схема merged-блоков,
> тип виджета списка фраз) — за @Architect; реализация — @Builder; деплой — @DevOps.

---

## §0. Инварианты раунда (не нарушать)

- **Ноль новых PG-DDL**: `services/database.py`/`services/pg_db.py` — без DDL; SQLite остаётся **v8**.
- **`bot.py` router order** критичен и не меняется (искл.: DI-аргументы новых hot-значений в точках
  создания `LLMClient` — `bot.py:316,486,515,542`); `filters/`/`media/` — не трогать.
- **R17**: секреты не логируются/не эхо; в git — только `.env.example` (плейсхолдеры). Новые
  параметры item 1/3 — **не секреты**.
- **R16 (id, не имя)**: ID (Костик, провайдеры) остаются ключами.
- **«Без хардкода»**: адреса/модели/фразы — через `settings` (code-default) + `hot.get(pg_key, default)`,
  редактируемо в мини-аппе; литералы в хендлерах/UI недопустимы.
- **UI + аддитивный серверный read-path** ⟹ feature-flag/kill-switch **не требуется** (спец. preцедент
  10.9–10.11); откат — атомарный `git revert` (+ возврат значений в PG, если менялись). Feature-flag/
  progressive-rollout неприменим: инструмент внутренний, один владелец (см. §6).
- **Деплой-команды** (ssh/пароль/`git pull`/`systemctl restart`/`status`) — по `plans/current_task.md`;
  пароль в документацию не переносится.

---

## §1. Дословный запрос владельца (`plans/current_task.md`)

1. **BUG (base_url провайдеров).** При изменении base_url основного провайдера (`models.llm_base_url`,
   сейчас `https://nano-gpt.com/api/v1`) — ошибка сохранения
   «models.llm_base_url: ключ нельзя переносить на уровень чата», и url основного эмбеддинга тоже
   меняется на этот же url. Модели эмбеддингов и основная — разные, могут быть на разных провайдерах,
   не должны зависеть друг от друга. Требуется: **embeddings base_url = `https://apinet.cloud/v1`**,
   **direct-answers base_url = `https://nano-gpt.com/api/v1`**. **Без хардкода.**
2. **Блоки подключения (UI).**
   - Рядом с заголовком «Основная модель» маленькая надпись; в неё должно транслироваться содержимое
     поля **«Название модели»**; так же — **для всех подключений**.
   - **«Фолбэк-модель» → «Запасная модель»**; объединить эти две настройки в **один блок**.
   - **«Groq (расшифровка)» → «Модель транскрибации»**; **«OpenRouter (запасной)» → «Запасная модель
     транскрибации»**; объединить в **один блок**.
   - **«Видео-модель (OpenRouter)» → «Саммаризация видео»**; **«Запасная видео-модель» → «Запасная
     модель саммаризации видео»**; объединить в **один блок**.
   - **Проверить семантику**: модели транскрибации должны отвечать за транскрибацию (команда
     транскрибации видео/ГС/кружка — просто расшифровка слов), модели саммаризации — за выжимку видео;
     ощущение владельца, что модели перепутаны по смыслу.
3. **PERMsoc: функция Костика.** Сейчас на его сообщения уходят захардкоженные фразы.
   - Вынести **все фразы** в настройки PERMsoc в **блок Костика**: редактируемый список, каждая фраза —
     отдельное редактируемое поле, возможность удалять/добавлять, **поля плотно друг к другу**.
   - Заменить фразы на 4 данных + придумать **ещё 10** в том же духе:
     «Папочка, только не в попочку»; «Папа Костя, только не там»;
     «Папа Костя, можно хотя бы сегодня без конфетки?»; «Daddy, i'm scared, убери это пожалуйста».
   - Проверить, есть ли в мини-аппе параметр, регулирующий **частоту** этих фраз.
4. **Финал:** README (ироничный тон), **русский коммит** в основную ветку по правилам, **push**,
   **деплой** (ssh → `cd /var/www/admin_bot` → `git pull`; при изменениях env — `nano .env`;
   `sudo systemctl restart admin_bot`; `sudo systemctl status admin_bot`),
   **человекочитаемый отчёт простыми словами** (что сделано, как работает, какие баги исправлены,
   какие блокеры).

---

## §2. Рекогносцировка (@PM, `file:line`)

### 2.1. Item 1 — почему 422 и почему embedding-URL «алиасит» main

**Root cause A — per-chat 422 (сохранение в контексте выбранного чата):**
- `web/app.js:2181-2225` `saveBlock()` постит `POST /api/config`.
- `web/app.js:1240-1254` `api()` **автоматически** добавляет `X-Chat-Id`, если `activeChatId != null`
  (`:1253-1254`).
- Сервер: `web/api/routes.py:414-417` — при `X-Chat-Id` и `spec.per_chat == False` → **422**
  `"{key}: ключ нельзя переносить на уровень чата"`.
- `services/param_catalog.py:110-119` — `per_chat = category ∈ {prompts,limits,flags,reactions,content,memory}`
  и не secret ⟹ **`models.*` (в т.ч. `models.llm_base_url`) — всегда `per_chat=False`**.
  ⟹ Любое сохранение provider-поля `models.*` при выбранном чате падает 422.
  (Прецедент/класс: R10.5-2, `ARCHITECTURE.md:353`.)

**Root cause B — embedding base_url == main base_url (UI):**
- `web/app.js:362` `direct_main` поле `models.llm_base_url`.
- `web/app.js:417` `embeddings.subBlocks.embeddings_main` **то же поле `models.llm_base_url`** ⟹
  один и тот же pg-ключ на оба блока → правка main меняет значения обоих.
- `web/app.js:408-436` `embeddings` = subBlocks `[main, fallback1, fallback2]`.

**Root cause B′ — embedding base_url == main base_url (рантайм):**
- `services/llm_client.py:231-256` `LLMClient.__init__(base_url, ...)` — **единственный** `self._base_url`.
- `services/llm_client.py:534-544` `_post()` всегда использует `self._base_url`.
- `services/llm_client.py:926-942` `embed()` вызывает `self._post("/embeddings", …)` ⟹ primary-эмбеддинги
  идут на chat-base_url. **Отдельного `EMBEDDING_BASE_URL` в `config/settings.py` НЕТ.**
- Точки создания: `bot.py:316-321`, `bot.py:486-491`, `bot.py:515-520`, `bot.py:542-547` — везде
  `hot.get("models.llm_base_url", settings.LLM_BASE_URL)` в один конструктор.
- `config/settings.py:317-320` — `LLM_BASE_URL` (default `https://apinet.cloud/v1`), `EMBEDDING_MODEL_NAME`;
  `EMBEDDING_DIM` `:337`; embed-fallback `:346-362`.
- `services/status_service.py:163-164` `main_base` из `models.llm_base_url`; `:251-256` `emb_main`
  использует **тот же `main_base`** ⟹ карточка «Основная модель памяти» тоже алиасит main.
- `services/param_catalog.py:496-511` — `LLM_BASE_URL` (`models_main`), `EMBEDDING_MODEL_NAME`/
  `EMBEDDING_DIM`/`EMBEDDING_FALLBACK_*` (`models_embeddings`). Отдельного embed-base-url нет.
- `services/llm_probe.py:35-38,58-61` — `_EMBEDDING_BLOCKS`/`_BLOCK_SAVED_KEY`: `embeddings_main` →
  `keys.llm_api_key` (ключ шарится с main — by design R17/BYOK; base_url — нет).
- UI-кандидаты на правку: `web/app.js:411-436` (3 subBlocks), `web/index.html:800-899` (рендер),
  `providerCoveredKeys` (generic-дубли) — `web/app.js` ~`:2729-2740` (10.11).
- Тесты-маркеры: `tests/js/routing_test.js:399-500,700-722,836`; `tests/test_webapp_round1011_ui.py:115,124,147,162`;
  `tests/test_status_service.py:472,491`; `tests/test_param_catalog.py:189`; `tests/test_round106_ia_smoke.py:215,439`.
- Деплой-нюанс: `.env.example:147-149` (`LLM_BASE_URL=https://apinet.cloud/v1`), `config/settings.py:318`.
  Требуемые значения владельца (embeddings=`apinet.cloud/v1`, direct=`nano-gpt.com/api/v1`) — задать
  code-default + PG/hot без хардкода в хендлерах. ⚠️ Разрешение конфликта дефолтов — **OPEN-Q1**.

### 2.2. Item 2 — блоки подключения, display-name, семантика STT vs summary

**Данные блоков (`web/app.js`):**
- `PROVIDER_BLOCKS` `:358-466`:
  - `direct_main` `:359-365` (`models.llm_display_name`/`models.llm_base_url`/`models.llm_model_name`/`keys.llm_api_key`);
  - `direct_fallback` `:366-373` («Фолбэк-модель», `models.llm_fallback_*`);
  - `transcribe_groq` `:374-380` («Groq (расшифровка)», `models.groq_*`);
  - `transcribe_openrouter` `:381-388` («OpenRouter (запасной)», `models.openrouter_*` + `models.openrouter_transcribe_model`);
  - `video_summary_openrouter` `:389-396` («Видео-модель (OpenRouter)», `models.video_primary_model`);
  - `video_fallback` `:397-407` («Запасная видео-модель», `models.video_fallback_model`);
  - `embeddings` `:408-436` (3 subBlocks);
  - advanced: `llm_guard` `:438-447`, `search_keys` `:448-457`, `media_share` `:458-465`.
- **Общий `models.openrouter_display_name` / `models.openrouter_base_url` / `keys.openrouter_api_key`**
  у `transcribe_openrouter` И `video_summary_openrouter`/`video_fallback` (`:384,392,403`) ⟹ при merge
  в «один блок» transcribe и video остаются РАЗНЫМИ блоками, но делят display-name — **OPEN-Q2**.
- Рендер: `web/index.html:806-811` (header: `.prov-title` + `.prov-modules {{ b.modules }}`),
  `:815-850` (subBlocks), `:851-898` (поля/кнопки), `:946-994` (advanced-блоки). Маленькая надпись
  владельца = **`{{ b.modules }}`** (`:810`, `:950`) — сейчас статичный текст; нужна трансляция
  «Название модели».
- Display-name ключи: `models.llm_display_name` (`:361,369`), `models.groq_display_name` (`:376`),
  `models.openrouter_display_name` (`:384,392,403`), `models.embedding_display_name`/`_fallback_`/`_fallback2_`
  (`:416,423,431`); каталог `services/param_catalog.py:562-577`; settings `config/settings.py:325-333`.
- `blockFieldValue` `web/app.js:2094-2101`, `blockFieldConfigured`/`last4ByKey` `:2109-2122`,
  `saveBlock` `:2181-2225`, `testBlock` `:2123-2151`, `testField` `:2153-2178`.
- `providerConnectionBlocks`/`providerAdvancedBlocks` — computed, `web/app.js:957-966` (10.11);
  шаблон — bare-ref `web/index.html:807,947`. При merge структуры `computed`/`providerCoveredKeys`
  придётся обновить (иначе generic-дубли/пропажа полей).
- Ремайндер аудита: **R10.11-1** (nested `<details>` делят `localStorage`-ключ `adminbot.expand:...`);
  `expandOpen/toggleExpand` `web/app.js:2510-2519` — при изменении блоков не воспроизводить баг.

**Семантика STT vs summary (проверка — вероятной путаницы в коде НЕТ):**
- Транскрибация: `handlers/voice_transcription.py:184` → `SmartModule/service.py:78-116`
  `VoiceTranscriber.transcribe_voice` → стратегии `(GroqTranscriber, OpenRouterTranscriber)` `:69-73`.
  - Groq: `SmartModule/transcriber/groq_transcriber.py:20-21` (`GROQ_BASE_URL`/`whisper-large-v3`),
    hot `models.groq_base_url`/`models.groq_transcribe_model` `:52,127-128`.
  - OpenRouter: `SmartModule/transcriber/openrouter_transcriber.py:33-36`, hot `models.openrouter_base_url`/
    `models.openrouter_transcribe_model` `:73-74,160-161`; транскрибация через `chat.completions` + `input_audio` (`:143-164`).
  - Видео/кружок STT — тот же контроллер (`handlers/youtube.py:376`, `transcribe_voice`).
- Саммаризация видео: `handlers/youtube.py:974` `summarize_cascade` и `:590,697` `summarize_media_url`
  → `services/youtube_summarizer_service.py:101-147,254-303` — `models.video_primary_model` / `models.video_fallback_model`
  через `services/video_cascade_client.py` (`video_url`, OpenRouter).
- `services/status_service.py:154-243` — карточки: `stt_groq`/`stt_openrouter` kind=`stt`/`chat`,
  `video_openrouter` — `models.video_primary_model`.
- **Вывод рекогносцировки:** модели транскрибации → транскрибация, видео-модели → саммаризация;
  семантического свопа в коде не видно. Причина ощущения владельца — вероятно **общий
  `models.openrouter_*`/display-name** у STT-фолбэка и видео-блока + старые подписи. Задача Builder —
  подтвердить/опровергнуть на живом коде и **документировать** вывод (при реальном свопе — исправить).

### 2.3. Item 3 — фразы Костика и частота

- **Захардкоженные фразы:** `handlers/kostik.py:30-39` `KOSTIK_REPLIES` (8 шт.), выбор
  `:54` `random.choice(KOSTIK_REPLIES)`.
- Гейт PERMsoc: `:42` `PermsocGateFilter("kostik")` + `UserIdFilter` `:43`.
- Модуль: `services/permsoc.py:55-57` `PermsocModule("kostik", "Костя (персона-реплики)",
  "reactions.kostik_user_id", None, (350803143,), ("handlers/kostik.py",))`; master-флаг
  `flags.permsoc_enabled` (`:34`); под-флага у Костика нет (`sub_flag_key=None`) ⟹ только master.
- **Группы каталога:** `reactions_kostik` (`services/param_catalog.py:311-312`, только
  `KOSTIK_USER_ID` `:1139-1140`; вкладка PERMsoc `:1701`); `limits_kostik` (`:194-195`) с
  `KOSTIK_REPLY_PROBABILITY` `:750-751`.
- **Частота — ЕСТЬ:** `settings.KOSTIK_REPLY_PROBABILITY` (`config/settings.py:165`), `.env.example:22`,
  pg `limits.kostik_reply_probability`, чтение `handlers/kostik.py:47-48`. В мини-аппе живёт в группе
  **«Костик: лимиты»**, не в блоке Костика. Ответ владельцу: параметр частоты существует (вероятность);
  при желании продублировать/перенести в блок Костика — **OPEN-Q3**.
- **UI PERMsoc:** `PERMSOC_OWNER_BLOCKS` `web/app.js:473-494` — блоки `slavik`/`olya`/`mimic`/`common`;
  **отдельного блока `kostik` НЕТ** — `reactions_kostik` попадает в «Общее» через `ownerOf()`
  (`:2800-2838`). Владелец просит «блок Костика» ⟹ нужен новый owner-блок или явная секция — **OPEN-Q4**.
- Виджеты: `keyvalue` (KV-редактор пар) `web/index.html:1107-1111,1385-1389`, template `:3124-3143`,
  `web/app.js:4713-4825`; **списка строк (add/delete по фразе) нет** — нужен новый виджет/компонент
  (напр. `widget="list"` + `list-editor`) — **OPEN-Q5**; JSON-редактор как тип — `type="json"`
  (`param_catalog.py:1473`, `pg_db.py:280`).
- Тесты: `tests/test_kostik.py` (импорт `KOSTIK_REPLIES`, pool ≥3, ответ ∈ pool `:13,36,64-74,95`);
  `tests/test_direct_chat_handlers.py:458`; `tests/test_param_catalog.py:383`.

---

## §3. Задачи для @Builder (granular checklist)

### A. Item 1 — развязать base_url провайдеров + починить 422 (сначала, блокирующее)

> ✅ Реализовано @Builder (раунд 10.12): base_url/ключ эмбеддингов развязаны,
> 422 закрыт клиентским global-save. OD-1 ПРИНЯТ владельцем → добавлен
> `keys.embedding_api_key` (итоговые счётчики: REGISTRY 405 / Settings 377 /
> categorized 381).

- [x] **T-1382 (@Architect, гейт):** spec/ADR: отдельный параметр base_url основного эмбеддинга
  (имя, category/group, type/default, `hot.get`-точки, семантика «пусто → ?»), как хранить два URL,
  влияние на `providerCoveredKeys`, счётчики каталога, миграция значений PG/`.env`, поведение при
  merge-блоках item 2. Разрешить OPEN-Q1.
- [x] **T-1383 (@Builder):** добавить параметр embeddings base_url (Settings + ParamSpec в
  `models_embeddings`), code-default = требуемый владельцем адрес; без хардкода в хендлерах/UI.
  Обновить `.env.example` (комментарий, плейсхолдер), `services/param_catalog.py`, `config/settings.py`.
- [x] **T-1384 (@Builder):** `services/llm_client.py`: развязать embed-путь от chat-base —
  `_embed_base_url` из `hot.get(<embed_pg_key>, settings.<EMBED_...>)`; `embed()` использует его
  (аккуратно с `_post`/ретраями/`_get_client`, не ломая chat-путь).
- [x] **T-1385 (@Builder):** `bot.py:316,486,515,542` — прокинуть embed base_url в `LLMClient`
  (DI-аргумент), порядок роутеров не трогать.
- [x] **T-1386 (@Builder):** `services/status_service.py:163-164,251-256` — карточка `emb_main`
  берёт **embed**-base, а не `main_base`; provider/host не хардкодить.
- [x] **T-1387 (@Builder):** `web/app.js` embed-subBlocks (`:411-436`) — заменить `models.llm_base_url`
  в `embeddings_main` на новый ключ; `providerCoveredKeys` покрывает новый ключ (нет generic-дубля).
- [x] **T-1388 (@Builder):** починить 422: provider-поля `models.*` (`per_chat=False`) сохранять
  **глобальным путём** (без `X-Chat-Id`) либо иным согласованным способом — и в `saveBlock`, и в generic
  save; DM read-only (`R10.5-2`) и серверный гейт `routes.py:414-417` не ослаблять.
- [x] **T-1389 (@Builder):** тесты item 1: embed/chat base независимы (`llm_client`), новый каталог-ключ,
  `status_service.emb_main` использует embed-base, сохранение provider-поля при активном чате → **не 422**,
  `providerCoveredKeys`. Обновить счётчики каталога осознанно.

### B. Item 2 — блок подключения (после T-1382 для merge-схемы)

> ✅ Реализовано: 3 merged parent-блока + embeddings; динамическая подпись display-name у всех
> подключений; семантика STT/summary подтверждена (§2.1 — свопа нет).

- [x] **T-1390 (@Builder):** merge `direct_main`+`direct_fallback` в **один блок**; «Фолбэк-модель» →
  **«Запасная модель»**; подблоки «Основная модель»/«Запасная модель» с полным набором полей и
  отдельными «Сохранить»/«Проверить».
- [x] **T-1391 (@Builder):** merge `transcribe_groq`+`transcribe_openrouter` в **один блок**;
  заголовки **«Модель транскрибации»** / **«Запасная модель транскрибации»**.
- [x] **T-1392 (@Builder):** merge `video_summary_openrouter`+`video_fallback` в **один блок**;
  заголовки **«Саммаризация видео»** / **«Запасная модель саммаризации видео»**.
- [x] **T-1393 (@Builder):** маленькая надпись у header каждого подключения транслирует значение поля
  **«Название модели»** (первое поле блока/подблока), динамически; для всех блоков (main/fallback,
  STT, video, embeddings, advanced). Фолбэк при пустом display-name — прежний текст (не пусто/не хардкод).
- [x] **T-1394 (@Builder):** обновить `providerConnectionBlocks`/`providerAdvancedBlocks`,
  `providerCoveredKeys`, шаблон `web/index.html:806-811,946-994` под merged-структуру; проверить, что
  **все** поля остаются редактируемыми и не дублируются в generic-группах; не воспроизвести R10.11-1.
- [x] **T-1395 (@Builder):** **семантика STT vs summary** — подтвердить по коду (`file:line`), что
  `models.groq_*`/`models.openrouter_transcribe_model` → транскрибация, `models.video_primary_model`/
  `models.video_fallback_model` → выжимка видео; зафиксировать вывод в spec/ADR/отчёте. При обнаружении
  свопа — исправить и покрыть тестом. **(Свопа нет — «не чинил» не-проблему.)**
- [x] **T-1396 (@Builder):** тесты item 2: заголовки/переименования, merged-блоки, динамическая надпись
  display-name (в т.ч. live-обновление), отсутствие generic-дублей, R10.5-2 DM read-only, per-block
  test/save.

### C. Item 3 — фразы Костика в PERMsoc

> ✅ Реализовано: `reactions.kostik_replies` (json/widget=list, 14 фраз), owner-блок «Костик»,
> под-флаг `flags.kostik_enabled` (default ON), вероятность перенесена в блок.

- [x] **T-1397 (@Architect):** spec/ADR: формат хранения списка фраз (новый параметр, тип, виджет),
  новый owner-блок Костика (или место в существующей структуре), дефолт из 14 фраз, чтение/валидация,
  пустой список. Разрешить OPEN-Q3/Q4/Q5.
- [x] **T-1398 (@Builder):** параметр списка фраз Костика (в группе `reactions_kostik` или новом блоке),
  editable list, дефолт = 4 фразы владельца + 10 новых в том же духе (все — отдельными элементами);
  `handlers/kostik.py` читает через `hot.get(pg_key, default)`; литералы `KOSTIK_REPLIES` удалить
  (оставить как code-default параметра). Пустой список → безопасное поведение (не падать).
- [x] **T-1399 (@Builder):** UI-виджет списка строк: каждое поле — отдельная плотная строка, add/delete,
  save; `web/index.html` + `web/app.js` (по образцу KV-редактора, без секретов).
- [x] **T-1400 (@Builder):** блок Костика в PERMsoc (owner-блок/секция): ID + фразы (+ при согласовании —
  вероятность/частота); согласовать с `PERMSOC_OWNER_BLOCKS`/`_permsocOwnerGroups`/`_ownerDescription`.
- [x] **T-1401 (@Builder):** тесты item 3: дефолт содержит 4 фразы владельца + ≥10 новых, все непусты/
  уникальны; правка/добавление/удаление сохраняется; handler использует hot-значение; пустой список
  безопасен; `tests/test_kostik.py` обновлён без ложных падений.

### D. README / версия (ироничный тон)

- [ ] **T-1402 (@Builder/@DevOps):** README: шапка (новый счётчик тестов, версия), changelog 10.12,
  таблицы env — **иронично, простыми словами**; описать развязку base_url, merged-блоки, фразы Костика.
- [ ] **T-1403 (@Builder/@DevOps):** синхронно поднять `APP_VERSION` (`config/settings.py`) + cache-bust
  `?v=__APP_VERSION__`; не ломать `test_app_version_matches_readme`/`test_index_version_query_param`.

### E. Проверки перед коммитом

- [x] **T-1404 (@Builder):** `node --check web/app.js` — clean; `node tests/js/routing_test.js` —
  `JS-UNIT-OK` (дописать юниты под merged-блоки/display-name/список фраз).
- [x] **T-1405 (@Builder):** полный `pytest` — **0 failed** (база 5172; фиксировать дельту);
  `git diff --check` — clean; независимый пересчёт инвариантов каталога.
  **(5206 passed / 0 failed; +34 теста; `git diff --check` EXIT=0.)**
- [ ] **T-1406 (@DevOps):** русский conventional-commit, `git add` только нужного, `push` в `origin/master`.

### F. Деплой и отчёт

- [ ] **T-1407 (@DevOps):** деплой по `plans/current_task.md`: ssh → `cd /var/www/admin_bot` → `git pull`;
  если env менялся — `.env` (nano); `sudo systemctl restart admin_bot`; `sudo systemctl status admin_bot`;
  `git pull --ff-only`, health `200`, стартовые логи — 0 ERROR/Traceback. Проверить
  `/web/` и `/web/app.js` на маркеры 10.12 и `?v=<APP_VERSION>`.
- [ ] **T-1408 (@DevOps/@PM):** **человекочитаемый отчёт** простыми словами: что сделано, как работает
  (item 1/2/3), какие баги исправлены, блокеры. Живая проверка в TMA/Android — за владельцем/QA.

### G. Ревью follow-up (@Reviewer APPROVED WITH MINOR ISSUES → @Builder)

- [x] **T-1409 (@Builder, DEFECT 1 Medium):** `bot.py` `lore_llm` (`:491`) получил 4-ю пару DI
  `embed_base_url=`/`embed_api_key=` (итого 4/4 точки). Тест-инвариант в
  `tests/test_webapp_round1012_ui.py::test_bot_di_all_four_call_sites`.
- [x] **T-1410 (@Builder, DEFECT 2 Low):** `services/llm_probe._saved_api_key` — для primary embed
  (`keys.embedding_api_key`) фолбэк на `keys.llm_api_key` (зеркало рантайма, R17). Google-фоллбэки
  НЕ затронуты. Тесты `test_embeddings_main_falls_back_to_llm_key` /
  `test_embeddings_fallback_does_not_use_llm_key`.
- [x] **T-1411 (@Builder, DEFECT 3 Low):** `services/llm_client.py` — отдельный кэш embed-клиента
  (`_embed_client`/`_embed_client_key`, `_get_embed_client`, `channel="embed"` в `_post`, закрытие в
  `close()`). Тест `test_chat_and_embed_use_separate_clients`.
- [x] **T-1412 (@Builder, DEFECT 4 Info):** spec §3.3 + ADR-1012-1 D4 синхронизированы с shipped-списком
  фраз (#5/#12 — adult-to-adult, rationale записан).

### H. Scanner LOW follow-up (@Builder, раунд 10.12)

- [x] **T-1413 (@Builder, LOW):** `web/app.js` `saveKeyItem` переведён на global-save
  (per_chat=false → без `X-Chat-Id`; `updated_at` только для chat-ветки). Закрывает 422 для
  `keys.*` вне provider-блоков (Betterstack/YouTube cookies/proxy). Тест-юнит `saveKeyItem`
  в `tests/js/routing_test.js` + статик-маркер.
- [x] **T-1414 (@Builder, LOW cosmetic):** `blockDisplayName` подавляет подпись, если она равна
  заголовку блока (parent direct/transcription/video_summary); `v-if` на span в `index.html`.
  Тест-юнит + статик-маркер.
- [x] **T-1415 (@Builder, INFO):** актуализирован docstring `services/llm_probe.py` (embeddings
  теперь с UI-кнопкой теста + OD-1 фолбэк primary embed).
- [x] **T-1416 (@Builder, INFO):** `KOSTIK_ENABLED` добавлен в `.env.example`; list-editor `:key`
  стал стабильным (`rowIds` вместо индекса). Тесты: `.env`-маркер, `rowIds`-юнит.

---

## §4. Acceptance Criteria

| # | Критерий | Проверка |
|---|---|---|
| AC-1.1 | Правка base_url основного провайдера сохраняется без 422 при выбранном чате | unit/API + live |
| AC-1.2 | Embeddings base_url — независимый параметр; правка main его не меняет (UI, runtime, status) | тест + live |
| AC-1.3 | embeddings base_url = `https://apinet.cloud/v1`; direct answers base_url = `https://nano-gpt.com/api/v1`; без хардкода в хендлерах/UI | grep + тесты дефолтов |
| AC-1.4 | `LLMClient.embed()` ходит на embed-base, chat — на chat-base; регрессии chat нет | `test_llm_client`/новый тест |
| AC-1.5 | Новый ключ — first-class каталог; `providerCoveredKeys` включает его; счётчики задокументированы; ноль PG-DDL | `test_param_catalog`/`test_webapp_round1012_ui` |
| AC-2.1 | Маленькая надпись у header каждого подключения показывает «Название модели» (динамически) | JS-юнит + статик-маркер |
| AC-2.2 | main+fallback — один блок; «Запасная модель» | UI-тест |
| AC-2.3 | STT groq+openrouter — один блок; «Модель транскрибации»/«Запасная модель транскрибации» | UI-тест |
| AC-2.4 | video primary+fallback — один блок; «Саммаризация видео»/«Запасная модель саммаризации видео» | UI-тест |
| AC-2.5 | Семантика STT/summary подтверждена `file:line`; своп — отсутствует (или исправлен) | документ/тест |
| AC-2.6 | Все поля/кнопки сохранены, generic-дублей нет, DM read-only (R10.5-2) цел | тесты |
| AC-3.1 | Все фразы Костика — в настройках (нет хардкода); дефолт = 4 владельца + 10 новых | тест |
| AC-3.2 | Каждая фраза — отдельное плотное поле; add/delete/save работают | UI-тест/юнит + live |
| AC-3.3 | Handler читает фразы через `hot.get`; пустой список безопасен | `test_kostik` |
| AC-3.4 | Параметр частоты частоты присутствует (вероятность); место — согласовано | тест/документ |
| AC-4 | README + `APP_VERSION` + cache-bust синхронны; русский коммит; push; деплой; health 200; отчёт | чек-лист деплоя |
| AC-5 | Инварианты: ноль PG-DDL, SQLite v8, `bot.py`-порядок и `media/` нетронуты, R17 | `git diff`/grep |

---

## §5. QA / Test Plan

- **Статика:** `node --check web/app.js`; `node tests/js/routing_test.js` → `JS-UNIT-OK`.
- **Юниты JS:** merged-структура блоков; `blockDisplayName`/трансляция display-name (пусто/live);
  список фраз (add/delete/save); независимость base_url-полей.
- **Python:** `pytest` полный — база **5172 passed / 0 failed**, фиксировать дельту;
  ключевые `test_llm_client`, `test_status_service`, `test_param_catalog`, `test_kostik`,
  `test_webapp_api`, `test_webapp_dm_ui`, `test_webapp_round1012_ui` (новый), `tests/js/routing_test.js`.
- **Каталог-инвариант:** пересчитать REGISTRY/GROUPS/Settings/mapped/TAB_RULES; задокументировать Δ.
- **API:** сохранение `models.*` (provider) при `X-Chat-Id` больше не 422; embed/chat base независимы.
- **Live Android/Telegram (за владельцем/QA):** правка base_url обоих провайдеров; маленькие надписи у
  всех подключений; merged-блоки; список фраз Костика (add/delete/сохранение), реальный ответ Костику.
- **Деплой:** `git pull --ff-only`, `systemctl restart/status`, `/api/health` 200, 0 ERROR/Traceback,
  маркеры 10.12 в `/web/` и `/web/app.js`.

---

## §6. Feature flags / Progressive delivery

- **Feature flag не требуется.** Изменения — админ-UI + аддитивный серверный read-path (новый параметр
  base_url) + вынос строк в каталог; перцедент 10.9–10.11 (UI/config-only ⟹ flag не вводится).
- **Rollback:** атомарный `git revert`; при изменённых значениях в PG — вернуть их в админке/скриптом
  (идемпотентно, без DDL). Деплой-откат — `git revert` + `systemctl restart admin_bot`.
- **Progressive rollout неприменим** (внутренний инструмент для одного владельца; нет долей пользователей).
  При желании @Architect может ввести kill-switch для раздельного embed-base — отметить в spec.

---

## §7. Open Questions (@Architect → владелец)

- **OPEN-Q1 (item 1):** где «живут» требуемые адреса — code-default `settings` (какие значения
  `LLM_BASE_URL`/нового `EMBEDDING_BASE_URL`?) + переопределение в PG/`.env`; как мигрировать прод-значения
  (`models.llm_base_url` уже `nano-gpt`?) без перезаписи осознанного выбора.
- **OPEN-Q2 (item 2):** общий `models.openrouter_display_name`/`base_url`/`keys.openrouter_api_key` у STT-фолбэка
  и видео-блока — разделять ли (новые ключи/имена) или оставить (комментарий в UI).
- **OPEN-Q3 (item 3):** дублировать/перенести ли вероятность (`limits.kostik_reply_probability`) в блок
  Костика или оставить в «Костик: лимиты».
- **OPEN-Q4 (item 3):** создавать ли отдельный owner-блок `kostik` в `PERMSOC_OWNER_BLOCKS` (сейчас его нет,
  группа попадает в «Общее»).
- **OPEN-Q5 (item 3):** тип виджета списка (новый `list` + компонент vs переиспользование `keyvalue`/JSON).
- **OPEN-Q6 (item 1):** нужен ли hardening R10.11-4 (probe не шлёт сохранённый ключ на caller-`base_url`) —
  включить в скоуп или оставить техдолгом.

---

## §8. Учёт свежих аудитов @Scanner (обязательно)

Прочитан **`plans/reports/round10.11_scanner_audit.md`** (0 blocker / 0 high / 0 medium; 3 low
R10.11-1…-3 закрыты follow-up; 3 info R10.11-4…-6 — техдолг) и **`plans/reports/audit_backlog.md`**.

- **R10.11-1 (low, nested `<details>` делят `localStorage`-ключ)** → учесть при merge-блоках item 2:
  не воспроизводить общий ключ `adminbot.expand:*` (T-1394).
- **R10.11-2 (low, `embedding_fallback_model`: status vs runtime) и R10.9-2 (embed-fallback читались
  из settings)** → item 1 трогает embed-цепочку: держать симметрию `status_service`/`llm_client`, читать
  через `hot.get` (T-1384/T-1386).
- **R10.11-3 (low, устаревшие подсказки «правьте в .env» для embed-ключей)** → обновить тексты/комментарии
  при добавлении нового embed-base-url (T-1383/T-1386).
- **R10.11-4 (info, probe + caller `base_url`)** → OPEN-Q6; при касании base_url можно закрыть как hardening.
- **R10.11-5 (info, мёртвый `destroy`)** — вне скоупа.
- **R10.11-6 (info, нет headless-теста рендера)** — учесть при UI-тестах item 2 (статик-маркеры + юниты).
- **R10.6-1 (был дубль generic-рендера)** → при новых/merged блоках обязательно проверить
  `providerCoveredKeys` (T-1387/T-1394), регресс-тест `provider_blocks_single_home`.

---

## §9. Передача

Планирование завершено. Следующий шаг: **@Architect** — spec.md + ADR (T-1382/T-1397), ответы на OPEN-Q1…Q6.
Затем **@Builder** — задачи §3; **@DevOps** — T-1406…T-1408. **@PM код не пишет.**
