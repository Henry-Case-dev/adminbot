# Round 10.12 Scanner Audit (providers-kostik-round1012: embed/direct base_url decoupling, 422 global-save fix, merged provider blocks, Kostik reply-list)

> Аудит 2026-09-13 (Step 6). HEAD `32d1aa9` (10.11) + рабочее дерево 10.12.
> `git status -s`: **24 modified + 2 untracked** (`plans/features/providers-kostik-round1012/`,
> `tests/test_webapp_round1012_ui.py`). `git diff --stat HEAD`: **+1030/−141** по 26 путям.
> Изменённые исходники: `config/settings.py`, `services/{llm_client,status_service,llm_probe,param_catalog,permsoc}.py`,
> `handlers/kostik.py`, `bot.py` (DI-kwargs only), `web/{app.js,index.html}`, `.env.example` + 15 тест-файлов
> + `plans/backlog.md` (doc-only).
>
> **pytest: 5210 passed, 0 failed, 1 warning** (59.85s; база 10.11 = 5172/0 → +38).
> **`node --check web/app.js` — clean.** **`node tests/js/routing_test.js` — `JS-UNIT-OK`.**
> **`git diff --check` — чист (EXIT=0, только LF/CRLF-warnings).**
> Проверены диффы всех изменённых файлов, полные тексты новых зон шаблона, независимый расчёт
> инвариантов каталога, embed-decoupling (UI + runtime + status + probe), 422-фикс (клиент + серверный
> гейт + DM), Kostik handler (пустой список/JSON/str/флаг), R16/R17, PG-DDL/секреты/Headroom.
> **Headroom — out of scope, ссылок в коде нет.**

## 1. Инварианты — независимая проверка

| Инвариант | Проверка | Вердикт |
|---|---|---|
| Каталог **REGISTRY 405 / GROUPS 90 / mapped 88 / Settings 377 / categorized 381** | Независимо: `len(REGISTRY)==405`, `len(GROUPS)==90`, `len(_TAB_BY_GROUP)==88`, `fields(Settings)==377`, categorized==381; `TAB_RULES==19` | ✅ |
| **Sanctioned Δ (ADR-1012-1 + OD-1)** | +5: `models.embedding_base_url` (models/`models_embeddings`, str, per_chat false), `models.openrouter_transcribe_display_name` (models/`models_extra_providers`, str), `keys.embedding_api_key` (keys/`keys_llm`, str, secret), `flags.kostik_enabled` (flags/`flags_permsoc`, bool), `reactions.kostik_replies` (reactions/`reactions_kostik`, json, widget=`list`, per_chat true). models 42→44 / keys 15→16 / flags 58→59 / reactions 38→39 | ✅ |
| **Ноль новых PG-DDL** | `services/database.py`/`services/pg_db.py` **не в диффе**; `git diff -G "CREATE TABLE\|ALTER TABLE\|ADD COLUMN"` — **пусто**; новые параметры — строки `bot_settings` (DML) | ✅ |
| **SQLite v8** | `services/database.py` вне диффа; `_SCHEMA_VERSION_AGI_MEMORY == 8` (`:53`) | ✅ |
| **`bot.py` router ORDER не тронут** | дифф бота — **только** 4 пары DI-kwargs `embed_base_url=`/`embed_api_key=` в 4 точках (`:316,491,525,557`); 4/4 `LLMClient(...)` покрыты; иных строк нет | ✅ |
| **`media/` не тронут** | нет в `git status`/диффе | ✅ |
| **`.env` не тронут** | в статусе только `.env.example`; прод `.env` вне git | ✅ |
| **Нет секретов** | grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` — пусто; `.env.example` — плейсхолдеры, `EMBEDDING_API_KEY` закомментирован | ✅ |
| **Нет Headroom-ссылок в коде** | repo-wide grep `*.py/*.js/*.html` — 0 (только архивные `plans/**` и `.venv`, вне кода) | ✅ |
| **R17 (секреты)** | новый `keys.embedding_api_key` → `secret=True`, маскируется; `_saved_api_key`/`_current_embed_api_key` значение не логируют; `sanitize_error` не затронут | ✅ |
| **R16 (id, не имя)** | `reactions.kostik_user_id`/`*_user_id` остаются pg-ключами; `test_frontend_tab_mapping` зелёный | ✅ |
| **Пин-тесты не ослаблены** | полный pytest 5210/0; счётчики обновлены **осознанно** и совпадают с независимым пересчётом; новых skip нет | ✅ |

## 2. Верификация пунктов раунда

### 2.1 Item 1 — развязка embed base_url/ключа (OD-1)
- **Settings** (`config/settings.py`): `LLM_BASE_URL` default → `https://nano-gpt.com/api/v1`;
  новый `EMBEDDING_BASE_URL` → `https://apinet.cloud/v1`; новый `EMBEDDING_API_KEY` → `""`.
- **Runtime** (`services/llm_client.py`): `__init__` принимает `embed_base_url`/`embed_api_key`;
  `self._embed_base_url = ((hot.get("models.embedding_base_url", embed_base_url if not None else _base_url) or _base_url) or "").rstrip("/")`;
  `_embed_api_key` из `keys.embedding_api_key`; `_current_embed_api_key()` = hot → `_embed_api_key` → `_current_api_key()` (fallback сохранён);
  `embed()` → `_post(..., base_url=self._embed_base_url, channel="embed")`; chat → `_base_url`. **Кросс-зависимости нет.**
  Для embed заведён **отдельный кэш** httpx-клиента (`_embed_client`/`_embed_client_key`/`_get_embed_client`,
  закрытие в `close()`) — churn при разных chat/embed-ключах исключён. Chat-путь/ретраи/`_post_with_key` не изменены.
- **DI** (`bot.py`): все 4 точки (`:316,491,525,557`) получают `embed_base_url`/`embed_api_key` из hot; порядок роутеров не тронут.
- **Status** (`services/status_service.py`): `emb_base` из `models.embedding_base_url`; `emb_key` из `keys.embedding_api_key or llm_key`;
  `emb_main` больше не алиасит `main_base`; `stt_openrouter` переключён на `models.openrouter_transcribe_display_name`
  (видео осталось на `models.openrouter_display_name`).
- **UI/probe** (`web/app.js`, `web/index.html`, `services/llm_probe.py`): `embeddings_main` → `models.embedding_base_url` +
  `keys.embedding_api_key`; `testBlock(sb)` подставляет именно embed-base (role `base_url`), т.е. проба идёт на embed-провайдера;
  `_saved_api_key` для primary embed зеркалит runtime-фолбэк на `keys.llm_api_key` (Google-фоллбэки НЕ затронуты).
- **Fallback-каскад** (`EMBEDDING_FALLBACK_*`) остался независимым (`_post_embed_fallback` не менялся).

### 2.2 Item 1 — фикс 422
- `api()` (`web/app.js:1268-1286`): `options.global === true` → **не** добавляет `X-Chat-Id`; флаг не утекает в `fetch`
  (`var init = Object.assign({}, options); delete init.global;`); `X-Telegram-Init-Data` сохранён.
- `saveBlock` (`:2261-2292`): per_chat=false → один global-POST (`updated_at:null`, `global:true`); смешанный блок → 2
  последовательных запроса (chat с `configChatUpdatedAt` + global без метки). `saveConfigItem` (`:3048-3060`): `item.per_chat === false`
  → `global:true` + `updated_at:null`.
- **Серверный гейт 422 не ослаблен:** `web/api/routes.py` **вне диффа**; `routes.py:414-417` и ранний 422 для
  `category == keys` (BYOK) сохранены. Global-путь `_post_config_global` проверяет права (`can_edit_param`/`can_view_key_value`) —
  локальный админ не может записать глобальный параметр ⇒ **эскалации нет**.
- **DM read-only не ослаблен:** `canEditConfig` (`:2637-2659`) по-прежнему отключает `per_chat=false` в DM (R10.5-2);
  `test_dm_access`/`test_webapp_dm_ui` зелёные.

### 2.3 Item 2 — merged-блоки + динамическая подпись
- `PROVIDER_BLOCKS`: 4 parent-блока `direct`/`transcription`/`video_summary`/`embeddings` + 3 advanced; id'ы
  `direct_main`/`direct_fallback`/`transcribe_groq`/`transcribe_openrouter`/`video_summary_openrouter`/`video_fallback` сохранены
  (тесты/`probe` их ждут). Шаблон рендерит `subBlocks` (save/test на подблок).
- `blockDisplayName(x)` (`:2137-2154`): первое поле с `role === ''` + `display_name` → значение, иначе `x.modules`
  (не пусто/не хардкод). Advanced-блоки (`llm_guard`/`search_keys`/`media_share`) → `modules` (поведение прежнее).
- `providerCoveredKeys` рекурсивно покрывает новые ключи (`models.embedding_base_url`, `keys.embedding_api_key`,
  `models.openrouter_transcribe_display_name`) ⇒ generic-дублей нет (R10.6-1).
- Семантика STT/summary: свопа нет (`models.groq_*`/`models.openrouter_transcribe_model` → транскрибация;
  `models.video_*` → саммаризация) — подтверждено тестом wiring.

### 2.4 Item 3 — Kostik handler safety
- `handlers/kostik.py`: литерал удалён; `KOSTIK_REPLIES = tuple(settings.KOSTIK_REPLIES)` thin-alias; handler читает
  `hot.get("reactions.kostik_replies", settings.KOSTIK_REPLIES)` и нормализует `_resolve_replies` (list/tuple/JSON-строка;
  только непустые `str` со strip; мусор/None/битый JSON → `[]`). Пустой список → **тихое молчание** (`random.choice` не вызывается).
- Гейт: `PermsocGateFilter("kostik")` → `master_enabled` + `module_enabled` (`flags.kostik_enabled`, `DEFAULT_SUB_FLAGS=True`).
  `PermsocModule('kostik').sub_flag_key == "flags.kostik_enabled"`; master ON + sub OFF → молчит (`test_permsoc`).
- Каталог: `reactions.kostik_replies` (json/widget=list/per_chat true); UI: owner-блок «Костик» (ID + фразы + вероятность),
  `PERMSOC_TOGGLE_KEYS['flags.kostik_enabled']`, `list-editor` (add/delete/save) в обоих generic-шаблонах.

## 3. Находки раунда 10.12

Critical/High/Medium — **нет**. Ниже Low/Info (не блокируют мерж).

### [R10.12-1] severity: low — путь `saveKeyItem` не переведён на global-save (тот же класс 422, что и item 1)
**Файл**: `web/app.js:3092-3112` (POST `/api/config` на `:3100`).
**Суть**: фикс ADR-1012-1 D2 переведён только на `saveBlock`/`saveConfigItem` (и `api()`-опцию `global`).
Метод `saveKeyItem` (редактор generic-секретов `item.category === 'keys' || item.secret`) по-прежнему пост**без** `global:true`,
поэтому при выбранном чате `api()` добавит `X-Chat-Id`, и сервер (`routes.py:409-417`) вернёт 422
(«ключ-секрет задаётся через /api/config/keys/own» / «ключ нельзя переносить на уровень чата») для `keys.*`, не покрытых
provider-блоками: `CHECKUP_BETTERSTACK_SQL_USER/PASSWORD`, `YOUTUBE_COOKIES_FILE`,
`YOUTUBE_TRANSCRIPT_PROXY_USERNAME/PASSWORD/URL`. Все они `per_chat=False` и должны сохраняться global-путём. Колонка
`keys.*`/секретов доступна wildcard-админу и при активном чате, поэтому путь воспроизводим.
**Регресс?** Нет — поведение pre-existing; spec §1.4 ограничил фикс `saveBlock`/`saveConfigItem`. Это **неполнота** того же
класса, а не новая поломка. KV-редактор (`web/app.js:4899`) не затронут и безопасен (единственный keyvalue-параметр
`SUMMARY_ALIASES` — `per_chat=True`).
**Рекомендация**: в `saveKeyItem` добавить `global: item.per_chat === false` (+ `updated_at:null` для global), по образцу
`saveConfigItem`.

### [R10.12-2] severity: info — устаревший docstring `llm_probe` про эмбеддинги
**Файл**: `services/llm_probe.py:14` («embeddings — требует base_url (UI не рендерит кнопку теста: base_url нет)»).
**Суть**: после ADR-1011/10.12 у `embeddings_main` есть собственный `base_url` и кнопка «Проверить» рендерится
(`web/index.html:843-846`, `testBlock(sb)`). Текст вводит в заблуждение. На поведение не влияет.

### [R10.12-3] severity: info — `KOSTIK_ENABLED` читает env, но не задокументирован в `.env.example`
**Файл**: `config/settings.py:195` (`_env_bool("KOSTIK_ENABLED", True)`), комментарий `:191` («env-ключа НЕТ»)
относится только к `KOSTIK_REPLIES`.
**Суть**: флаг имеет env-ключ (как прочие `*_ENABLED`), но в `.env.example` он не перечислен. Не поведенческий дефект;
источник значений — каталог/PG (hot). Информационно.

### [R10.12-4] severity: info — index-based `:key` в `list-editor`
**Файл**: `web/index.html:3181` (`:key="'le' + i"` + `v-model="rows[i]"`).
**Суть**: удаление/вставка строки в середине списка переиспользует DOM-инпуты по индексу (курсор/фокус-нюансы).
Данные не теряются (`rows` — источник истины, `save()` чистит пустые). Стилевой нит; при желании — ключ по контенту/uuid.

### [R10.12-5] severity: low — parent-заголовки merged-блоков дублируют title (маленькая надпись = тот же текст)
**Файл**: `web/app.js:362,380,400` (`direct`/`transcription`/`video_summary`: `title` == `modules`),
`web/index.html:810` (`{{ b.title }}` + `<span>{{ blockDisplayName(b) }}</span>`).
**Суть**: у parent-блоков нет display-поля, поэтому `blockDisplayName` падает в `x.modules` (spec §2.3),
а Builder выставил `modules` равным `title`. В итоге в шапке рендерится «Прямые ответы  Прямые ответы»,
«Транскрибация  Транскрибация», «Саммаризация видео  Саммаризация видео» — визуальный шум; у `embeddings`
(`title`='Эмбеддинги', `modules`='Поиск по памяти') дубля нет. Названия моделей на подблоках транслируются
корректно — дублируется только parent-подпись. Не функциональная потеря.
**Рекомендация**: задать parent `modules` роль-подписью, отличной от title (напр. «Основная и запасная модели»,
«Распознавание речи», «Выжимка видео»), либо скрывать надпись, если она совпадает с title.

## 4. Проверенные области — вердикты (логических дыр не найдено)

1. **Embed decoupling**: chat-base/ключ и embed-base/ключ полностью независимы; пустой embed-base → chat-base (паритет);
   пустой embed-ключ → `keys.llm_api_key`; fallback-каскад `EMBEDDING_FALLBACK_*` не тронут; отдельный httpx-кэш + закрытие;
   `hot.get`-приоритет на каждом вызове (актуальные значения админки). 4/4 DI-точки `bot.py`.
2. **422**: серверный гейт и DM read-only не изменены (routes.py вне диффа); global-ветка проверяет права на сервере →
   эскалации нет; `updated_at:null` корректно принимается (`ConfigUpdateRequest.updated_at: str | None`, global-путь его игнорирует).
3. **Kostik safety**: пустой список → `return` до `random.choice`; битый JSON/None/dict/не-str → `[]`; tuple-дефолт из settings
   принимается; флаг-гейт реально выключает модуль (master+sub), дефолт True сохраняет прежнее поведение.
4. **Каталог/UI**: `providerCoveredKeys` покрывает все новые ключи; `loadConfig` не строкифаймит `widget=list` (массив);
   `saveConfigItem` для json-массива не парсит повторно; серверный `_coerce_value`/`coerce_catalog_value` принимают list.
5. **Шаблон/index.html**: ветка `item.widget === 'list'` вставлена в **оба** generic-шаблона (desktop+compact) перед json-веткой;
   `#list-editor-tpl` рядом с kv-editor; `list-editor` зарегистрирован до `app.mount`.
6. **Отсутствие функциональной потери**: старый пул «кринжатура» удалён намеренно (запрос владельца п.3), alias сохранён
   для импортов (`test_direct_chat_handlers.py:458`, `tests/test_kostik.py`); display-name разделён (STT vs видео);
   merge-блоки не убирают ни одного поля (`test_round106_ia_smoke`: 42 поля/35 уникальных).
7. **R16/R17**: `reactions.kostik_user_id` — id-ключ; `keys.embedding_api_key` secret; сырые ключи не эхо/не логируются;
   probe-fallback ключа не попадает в результат (тест `test_embeddings_main_falls_back_to_llm_key`).
8. **Тест-качество**: полный pytest 5210/0 (+38 к базе 5172); новые `tests/test_webapp_round1012_ui.py`,
   `test_llm_client::TestEmbedBaseDecoupling1012`, JS-юниты (merged-блоки, global-save, `saveConfigItem`, `blockDisplayName`,
   `list-editor`, owner-блок Костика) — исполняются и зелёные; счётчики каталога совпадают с независимым пересчётом.

## 5. Итог 10.12

- **Блокеров: 0. Critical: 0. High: 0. Medium: 0.** Low: **2** (R10.12-1 `saveKeyItem` не переведён на global-save —
  pre-existing, вне ограниченного spec-scope; R10.12-5 дубль title/modules у parent-блоков), Info: **3**
  (R10.12-2 stale docstring probe, R10.12-3 `KOSTIK_ENABLED` вне `.env.example`, R10.12-4 index-key в `list-editor`).
  Для мержа не обязательны.
- Инварианты соблюдены: **REGISTRY 405 / GROUPS 90 / mapped 88 / Settings 377 / categorized 381**, TAB_RULES 19;
  **ноль PG-DDL**; SQLite **v8**; `bot.py` router order и `media/`/`.env` не тронуты; секретов нет;
  **Headroom-ссылок в коде нет** (out of scope).
- pytest **5210 passed / 0 failed** (59.85s); `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean.

*Round 10.12 report generated by Scanner on 2026-09-13*
