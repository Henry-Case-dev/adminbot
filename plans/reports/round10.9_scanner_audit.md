# Round 10.9 Scanner Audit (admin-ui-round109: PERMsoc owner-blocks, scroll, описания, «Тяжёлые»/«Бюджет», dashboard/health, display-name, градиент)

> Аудит 2026-09-12. HEAD `51f308b` (10.8 docs) + рабочее дерево 10.9.
> `git status -s`: **23 modified + 2 untracked** (`tests/test_webapp_round109_ui.py`,
> `plans/features/admin-ui-round109/`). `git diff --stat`: **+1326/−605** по 25 путям.
> Изменённые исходники: `config/settings.py`, `services/{param_catalog,permsoc,status_service,llm_probe}.py`,
> `web/{app.js,index.html}` + 18 тест-файлов + `plans/backlog.md`.
>
> **pytest: 5105 passed, 1 warning** (60.68s; база 10.8 = 5076 → **+29**).
> **`node --check web/app.js` — clean.** **`node tests/js/routing_test.js` — `JS-UNIT-OK`.**
> **`git diff --check` — чист (только LF/CRLF-warnings).**
> Проверены диффы всех изменённых файлов, независимый расчёт инвариантов каталога,
> реальные сетевые прогоны `probe_openai`, сверка owner-ключей/групп с каталогом,
> ревизия RBAC/маршрутов скролла, поиск секретов/DDL.

## 1. Инварианты — независимая проверка

| Инвариант | Проверка | Вердикт |
|---|---|---|
| Каталог **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88 / TAB_RULES 19 / CONFIG_TAB_TITLES 19** | Независимо: `len(REGISTRY)==400`; `len(GROUPS)==90`; `len(dataclasses.fields(Settings))==372`; `len(_TAB_BY_GROUP)==88`; `len(TAB_RULES)==19`; `len(CONFIG_TAB_TITLES)==19` | ✅ |
| **Ноль новых PG-DDL** | `git diff` не содержит `services/database.py`/`services/pg_db.py`; `git diff -G "CREATE TABLE\|ALTER TABLE\|ADD COLUMN\|user_version\|schema_version"` — пусто | ✅ |
| **SQLite v8** | `_SCHEMA_VERSION_AGI_MEMORY == 8`; `services/database.py` не менялся | ✅ |
| **`bot.py` router order не тронут** | нет в `git diff`/`git status` | ✅ |
| **`media/` не тронут** | `git status -s media/` пусто | ✅ |
| **`.env` не тронут** | нет в диффе | ✅ |
| **Нет секретов** | grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` — пусто | ✅ |
| **Нет ссылок на инфраструктуру IDE в коде** | repo-wide grep (кроме `.git/.venv/node_modules`): только plans-доки (spec/tasks/ADR/backlog) + **gitignored** `local_database_2026-09-04_history.db` (755 МБ, данные истории 06.09, не код). В коде/конфиге/тестах ссылок нет | ✅ |
| **Каталог-пины синхронны, не ослаблены** | `test_param_catalog`/`test_frontend_tab_mapping`/`test_round106_ia_smoke`/`test_webapp_parity_smoke`/`test_webapp_api` — 400/90/372/88/19 | ✅ |
| **Settings покрыты REGISTRY** | `covered == fields` (`test_param_catalog` зелёный) | ✅ |

## 2. Верификация пунктов раунда

| # | Пункт | Проверка | Вердикт |
|---|---|---|---|
| 1a | Owner-блоки PERMsoc | `PERMSOC_OWNER_BLOCKS` (4 шт., `slavik/olya/mimic/common`); `_permsocOwnerGroups` распределяет по `keys`→`groups`→common; `PERMSOC_TOGGLE_KEYS` исключает 4 тумблера из тела; **все 21 owner-ключ существуют в `_BY_PG_KEY`**, все 4 owner-группы существуют в `GROUPS`; «common» — остаток | ✅ |
| 1b | Ровно один тумблер в `<summary>` | `<summary v-if="grp.owner">` + `<label @click.stop>` + `@change.stop="toggleOwner(...)"`; generic-bool тумблеры не рендерятся (ключи исключены) | ✅ |
| 1c | Один путь записи | `toggleOwner`: common+чат → `togglePermsoc` (`gates.permsoc`); иначе `saveConfigItem` (config) — не оба одновременно (spec §1.6); `canToggleOwner` common+чат = только `isGlobalAdmin` | ✅ |
| 1d | Backend Славик | `SLAVIK_ENABLED` в `_FLAGS` (`flags_permsoc`, default **True**); `PermsocModule("slavik", …, "flags.slavik_enabled")`; `DEFAULT_SUB_FLAGS["flags.slavik_enabled"]=True`; `reactions_persons` удалена; `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`; `TAB_PERMSOC` без persons | ✅ |
| 1e | Нет потери поведения | Untouched `SLAVIK_ENABLED=True` = прежний `sub_flag_key=None` (module_enabled True); master-логика `PermsocFilter` не менялась; `permsoc_telemetry`/`permsocModuleBadge` учитывают slavik-под-флаг | ✅ |
| 3a | Спиннер только первая загрузка | `v-if="configLoading && !configItems.length"`; `setActiveChat` очищает `configItems` → спиннер на смене scope; `setTab` сброс скролла сохранён | ✅ |
| 3b | `_preserveScroll` | снимает/восстанавливает `document.scrollingElement` **и** `querySelector('.scroll-area')` в `$nextTick`; обёрнуты `saveConfigItem`/`saveKeyItem`/`saveBlock`/409-ветки/`resetChatOverride`/`resetPermPicker`/kv-editor; `fn.call(ctx || this)` корректен для root/child | ✅ |
| 4 | Переписаны описания | тест ругается на 28 запрещённых жаргон-подстрок в `title_ru`**и**`description` (группы+параметры) + AI-шаблон `включ…выключ` — зелёный; пустых нет; keys/type/group не тронуты | ✅ |
| 5 | «Тяжёлые фичи» удалены | карточка удалена; `whoCanToggle`/`optInCount` отсутствуют; per-chat `dream/nostalgia/lore_auto` остаются доступны в «Сводке» (`oversightDetail.heavy` + `toggleKillswitch` → `set_feature_gate`); master-карта permsoc удалена | ✅ |
| 6 | «Бюджет фона» → «Сводка» | полоса «Бюджет фона (день)» внутри `activeTab === 'oversight'`, источник `loadBudgetInfo()` из `loadOversight`; `loadModules` больше не грузит бюджет; пустое состояние «Сегодня расхода ещё не было»; endpoint/бэкенд не тронуты | ✅ |
| 7.1a | Один блок «Доступность ключей», 4 группы | `llmGroups` computed группирует `/api/status.llm`; старый блок переименован в «История доступности ключей»; хардкода `deepseek/groq/openrouter` в `web/` нет | ✅ |
| 7.1b | Реальный health | `status_service._check_health(module_id, base,key,model,kind)` → `_ping_provider` → `llm_probe.probe_openai` (lazy import); кэш **по `module_id`**: 2xx 60с, ошибки 10с (stale-200 не отдаётся); `stt_groq` → `kind="stt"` (`POST /audio/transcriptions`, multipart WAV), `stt_openrouter` → chat (input_audio), embeddings → `/embeddings`; таймаут 5с; различаются `ok/error/timeout/unreachable/not_configured` | ✅ |
| 7.1c | Проб реально сетевой | Независимый прогон `probe_openai`: пустой base/ ключ → `not_configured`; недостижимый хост → `timeout` (реальный httpx-таймаут); `_silent_wav()` = `RIFF` 9644 B; тесты покрывают 200/502/timeout/unreachable/URL STT/embeddings | ✅ |
| 7.2 | «Название модели» первым | у всех 6 provider-блоков первое поле — `models.*_display_name`; `providerCoveredKeys` исключает generic-дубль; `max-w-3xl mx-auto w-full`; 7 новых `ParamSpec` (глобальные, `models.*`); `_display` fallback при пустом | ✅ |
| 8 | Градиент быстрее | `--grad-speed:14s`, `grad-drift 18s`; `prefers-reduced-motion`/`prefers-contrast` не тронуты | ✅ |

## 3. Новые находки раунда 10.9

### [R10.9-1] severity: low — `model_source` запасных/эмбеддинг-записей реестра снова «code» при конфиге
**Файл**: `services/status_service.py:192-207` (`_entry` default `model_source="code"`),
`:217-226` (`llm_fallback` не передаёт source), `:244-256` (`video_openrouter`), `:251-277` (`emb_*`).
**Суть**: до 10.9 у `llm_fallback` было явное `"model_source": "config"`; теперь источник не
передаётся и `_build_llm_card` отдаёт `"code"` даже когда `models.llm_fallback_model` взят из
ConfigCache. Аналогично `video_openrouter`/`emb_main`/`emb_fallback*`. UI это поле не рендерит
(проверено: `model_source` в `web/` не используется), но `/api/status.llm[].model_source` —
часть контракта. Ремендация (2 строки): пробросить `fallback_model_src` из `_resolve`/`_model_from`.
**Impact**: metadata-only, на функциональность не влияет.

### [R10.9-2] severity: low — эмбеддинг-фоллбэки читаются из `settings`, не через `hot`/`_resolve`; display-name не виден без env-ключа
**Файл**: `services/status_service.py:257-277`.
**Суть**: spec §7.1.2b предписывал `hot.get(<pg_key>, settings.<FIELD>)`; фактические
`EMBEDDING_FALLBACK_BASE_URL/_API_KEY/_API_KEY_2/_MODEL` — `_INFRA_ENV_ONLY` (category `None`,
в REGISTRY их нет), поэтому прямой `settings`-доступ сегодня безвреден. Но (а) при будущей
миграции этих полей в PG реестр разойдётся с рантаймом; (б) `emb_fallback`/`emb_fallback2`
**полностью отсутствуют** в реестре, если env-ключ не задан, — заданное кастомное
`models.embedding_fallback*_display_name` тогда не отображается (карточки нет). Ожидаемое
поведение dashboard — показывать «не настроен»; сейчас запись просто исчезает. Ремендация:
добавлять запись при заданном base даже без ключа (`status="not_configured"`), либо
документировать omit-семантику.

### [R10.9-3] severity: low — устаревший docstring `status_service.py`
**Файл**: `services/status_service.py:10-15`.
**Суть**: шапка модуля по-прежнему описывает «health — лёгкий GET {base}/models (таймаут 5с,
кэш 60с)» и перечисляет хардкод-провайдеров (`deepseek/groq/openrouter`), что противоречит
ADR-109-3 (реальный POST-probe, кэш ошибок 10с, провайдер = host). Код корректен, документ
вводит в заблуждение. Ремендация: обновить docstring.

### [R10.9-4] severity: info — кэш health по `module_id`: смена base_url/key/model не инвалидирует ok ≤60с
**Файл**: `services/status_service.py:283-305`.
**Суть**: раньше кэш ключевался по `base_url` — смена адреса инвалидировала ок-результат
мгновенно; теперь ключ `module_id`, поэтому вылеченный ключ/адрес до 60с может показывать
старый `ok` (ошибки — только 10с). Смягчено тем, что ошибки переспрашиваются быстро.
Точечно: инвалидировать `_health_cache[module_id]` при `saveBlock`/`saveConfigItem` или
добавить config-версию в ключ.

### [R10.9-5] severity: info — `_LLM_BLOCKS` содержит `transcribe_groq`, хотя contract-заголовок перечисляет только chat-блоки; `ConnectTimeout` → «timeout»
**Файл**: `services/llm_probe.py:9-13,28-32,238-254`; `:163-164`.
**Суть**: `_LLM_BLOCKS` обязан содержать `transcribe_groq` (для `KNOWN_BLOCKS`), но
docstring-контракт в шапке его исключает — мелкая рассогласованность. Также
`httpx.ConnectTimeout` — подкласс `TimeoutException`, поэтому сетевой «connection timed out»
показывается как «timeout», а не «unreachable». Спека прямо относит `TimeoutException` к
`timeout` — поведение допустимо; фиксирую для трассируемости.

### [R10.9-6] severity: info — `plans/backlog.md` показывает «🟡 ПЛАНИРОВАНИЕ» при завершённой реализации
**Файл**: `plans/backlog.md:5`.
**Суть**: `tasks.md` §9 фиксирует выполненную реализацию (pytest 5105/0), а backlog-запись
осталась в статусе планирования. Doc-drift; закрывается @PM Step 8 (архив + статус ✅).

## 4. Проверенные области — вердикты (логических дыр не найдено)

1. **Owner-блоки (п.1)**: детерминированный `ownerOf` = `key∈keys` → `group∈groups && !claimed`
   → common; `claimed` строится из ключей **всех** персональных владельцев (условие
   `key ∉ ∪otherOwner.keys` реализовано верно, порядок блоков не ломает принадлежность).
   Все 4 блока рендерятся всегда (LOW-6), даже с пустым телом; `common` несёт read-only сводку
   5 модулей. Дублей generic-bool нет.
2. **Скролл (п.3)**: `_preserveScroll` не подавляет исключения (`try/finally`, результат `fn`
   возвращается), `$nextTick`-restore для двух скроллеров; `setTab`-сброс вверх не затронут;
   на смене scope `configItems=[]` → корректный большой спиннер; `setTab` не рефетчит —
   стейл-контента между вкладками нет.
3. **«Тяжёлые»/«Бюджет» (п.5/6)**: функциональной потери нет — per-chat `dream/nostalgia/
   lore_auto` доступны в «Сводке» (модалка деталей → `toggleKillswitch` → `set_feature_gate`),
   `toggleGate` жив (используется `togglePermsoc`); «Бюджет фона» — только в «Сводке»,
   `loadModules` бюджет не грузит, endpoint/`worker_budget.py` не тронуты. Смена прав:
   тяжёлые гейты теперь только global admin (в удалённой карточке local admin при
   `whoCanToggle==='global'` мог их менять) — ужесточение, не дыра.
4. **Health (п.7.1)**: `probe_openai` возвращает санитизированный `error` (ключ заменяется
   `***`, тело обрезается); `_ping_provider` не прокидывает `error` в `/api/status` (R17);
   маска `_mask_key_for_role` и `key_history`-allowlist не ослаблены; probe безопасен
   (SSRF-минимум `_safe_base`: https либо точный loopback; timeout 5с; тихий WAV 0.3с).
5. **RBAC/DM**: `canToggleOwner`/`permsocOwnerOn` дублируют серверные гейты; common+чат —
   только `isGlobalAdmin`; `canEditConfig`-ветки не менялись; DM-пути `_preserveScroll`
   (`this.root.…`) и kv-editor корректны; XSS-периметр (`{{ }}`, `sanitizeHtml`) не затронут.
6. **Шаблон**: разметка `web/index.html` сбалансирована (`<component>`→`details/div`,
   `<summary>`→`v-else div`, вложенные `<details class="advanced">` закрыты); теги owner-блоков
   парны. Иконки owner-блоков (`smart_toy/play_circle/psychology/admin_panel_settings`) есть
   в `ICONS` (37) и в субсете шрифта — tofu нет.
7. **Backend-флаги**: `SLAVIK_ENABLED` глобальный дефолт True, per-chat override через
   `get_chat_param`; `permsoc_telemetry` no-chat ветка читает `DEFAULT_SUB_FLAGS` (True);
   `master_flag_default()=False` не менялся — «байт-в-байт» для нетронутых чатов соблюдён.
8. **`APP_VERSION`**: оставлен `2.52.0` сознательно (tasks.md §9: T-1307 не делался по
   указанию «no README», чтобы не ломать `test_app_version_matches_readme`) — не находка.

## 5. Итог 10.9

- **Блокеров: 0. Major (High): 0. Medium: 0.** Low: **3** (R10.9-1 metadata `model_source`;
  R10.9-2 эмбеддинг-фоллбэки/display-name; R10.9-3 stale docstring). Info: **3**
  (R10.9-4 cache-key; R10.9-5 doc/`ConnectTimeout`; R10.9-6 backlog-статус).
- Для мержа **не обязательны** (ни blocker, ни major, ни medium). R10.9-1/-2/-3 —
  точечные (2-10 строк) ремедиации, рекомендуются в follow-up.
- Инварианты соблюдены: каталог **400 / 90 / 372 / mapped 88**, `TAB_RULES` 19;
  **ноль PG-DDL**; SQLite **v8**; `bot.py` не тронут; `media/` не тронут; секреты не коммитятся;
  **Ссылок на инфраструктуру IDE в коде/конфиге/тестах нет**.
- pytest **5105 passed / 0 failed** (60.68s; 1 pre-existing Starlette-deprecation warning +
  «closed 12 leaked aiosqlite connection(s)» — ресурс-предупреждение, не регресс).
- `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean.

*Round 10.9 report generated by Scanner on 2026-09-12*
