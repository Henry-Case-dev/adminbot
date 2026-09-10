# Round 10.6 Scanner Audit (tma-ia-modules-rework: единый navbar, 11 Модулей, Настройки AI (7), PERMsoc)

> Аудит 2026-09-11. HEAD `be7b85b` (10.5 docs) + рабочее дерево 10.6.
> `git status -s`: **24 modified + 4 untracked** (3 новых файла + feature-папка);
> `git diff --shortstat` = **1920 insertions / 1136 deletions** по отслеживаемым.
> Изменённые: `web/index.html`, `web/app.js`, `web/api/routes.py`,
> `services/param_catalog.py`, `config/settings.py`,
> `handlers/{factcheck,search,web,checkup,youtube}.py`,
> `plans/backlog.md`, + 16 тест-файлов.
> Новые: `services/llm_probe.py`, `tests/test_round106_gates.py`,
> `tests/test_round106_ia_smoke.py`, `plans/features/tma-ia-modules-rework/`.
>
> **pytest: 5023 passed, 1 warning** (55.99s; база 10.5 = 4962 → **+61**).
> **`node --check web/app.js` / `tests/js/routing_test.js` — clean.**
> **`node tests/js/routing_test.js` — `JS-UNIT-OK`.**
> **`git diff --check` — чист (только LF/CRLF-warnings).**
> Проверены диффы всех изменённых файлов, полный текст `services/llm_probe.py`,
> new-endpoint `POST /api/llm/test`, каталог-инварианты (независимым скриптом),
> маркеры фронта, новые/обновлённые тесты.

## 1. Инварианты — независимая проверка

| Инвариант | Проверка | Вердикт |
|---|---|---|
| Каталог **REGISTRY 392 / GROUPS 91 / Settings 364 / mapped 89** | Независимо: `len(REGISTRY)==392`; `len(GROUPS)==91`; **`len(dataclasses.fields(Settings))==364`** (не `dir()`); union групп из `TAB_RULES` = **89**; `_TAB_BY_GROUP` = 89 | ✅ |
| content `tab=None` = 2 / infra = 28 | Не смэплены только `content_info`, `content_media`; REGISTRY `category is None` = **28** | ✅ |
| **TABS ↔ TAB_RULES** | `TAB_RULES` = **19** вкладок; `CONFIG_TAB_TITLES` = 19; каждая группа ровно на **одной** вкладке (дублей `group→tab` нет); `test_frontend_tab_mapping` + `TestJsMirror` зелёные | ✅ |
| **Ноль новых PG-DDL** | `services/database.py`, `services/pg_db.py` **НЕ в диффе**; grep `CREATE/ALTER/ADD COLUMN/user_version` по tracked-диффу — пусто; `rename_role`-пути 10.5 не тронуты | ✅ |
| **SQLite v8** | `_SCHEMA_VERSION_AGI_MEMORY = 8` (`services/database.py:53`); файл не менялся | ✅ |
| **`bot.py` router order** | `bot.py` НЕ в git-диффе; новые гейты — внутри уже зарегистрированных handler-ов | ✅ |
| **`media/` не тронут** | `git status -s media/` пусто | ✅ |
| **Нет секретов staged/untracked** | `git diff --cached` пуст; скан новых/изменённых файлов (sk-/gsk_/AIza/bot-token/xox) — только комментарии-паттерны в `llm_client.py`; `.env` отсутствует в untracked | ✅ |
| **5 master-флагов default ON + реальные гейты** | `Settings()` — все 5 `True`; `pg_key` существуют и в правильных группах; гейты `hot.get(...)` в 5 handler-точках (см. §3) | ✅ |
| **Seed новых флагов** | `pg_db._seed_settings` (category `flags` ∈ SEED) → `coerce_catalog_value` → `true`; `ON CONFLICT DO NOTHING` → прод не «залочится» | ✅ |
| **R17 / R16 / DM** | см. §3 | ✅ (1 напряжённость — R10.6-2/6) |
| **Дубликаты каталога** | Нет дублей `GroupSpec.id`, `pg_key`, `settings_field`; `order` внутри категорий уникален | ✅ |
| **Pg-ключи не меняются** | У 10 перенесённых + RAG-ключей изменён только `group`; `pg_key`/`per_chat` (напр. `per_chat=True`) прежние | ✅ |

## 2. Верификация требований раунда (AC §13)

| # | Требование | Проверка | Вердикт |
|---|---|---|---|
| 1 | Sidebar удалён (`sidebar/☰/sidebarOpen/MENU_ORDER`) | grep по `web/` пусто; `MENU_LABELS`/`activeMenu`/`setMenu` удалены | ✅ |
| 2 | Navbar: 6 пунктов, иконка + подпись под ней | `NAV_ITEMS` = 6; `.nav-link` column + `.nav-label`; `aria-current`; правило `>span:not(.msr){display:none}` удалено | ✅ |
| 3 | Desktop fullscreen ⛶ скроллится | `.app-shell{flex-col;min-height:100vh}` + `.scroll-area{flex:1;min-height:0}` + `.fullscreen-mode .scroll-area{overflow-y:auto}`; вложенные `overscroll-behavior:contain` | ✅ |
| 4 | `#/modules` = ровно 11 модулей + toggle + «Параметры» | `MODULES` = 11 (порядок §5); `moduleEnabled/toggleModule/openModuleWindow`; «Кастомные модули» отсутствует | ✅ |
| 5 | 5 новых модулей реально гейтят (OFF→UNHANDLED) | Гейты: factcheck `:169`, search `:109`, web `:104`, youtube `:1019` (только `mode=="summary"`), checkup `:77`; `test_round106_gates` — 5/5 OFF→UNHANDLED | ✅ |
| 6 | `#/ai` = ровно 7 подразделов, без «Лимитов»/«Сна»/«Ностальгии»/«Диагностики» | `HUBS['#/ai'].cards` = 7 (LLM, Промпты, Память, Умный кэш, Имена, Отношения, Лор) | ✅ |
| 7 | LLM Провайдеры: 9 блоков по модулям, main→fallback, «Проверить» у каждого | `PROVIDER_BLOCKS` = 9; `testable:false` у `embeddings`/`llm_guard` (нет base_url/сети); `search_keys` — `perFieldTest` (`:tavily`/`:exa`); `media_share` — secret-presence | ⚠️ см. R10.6-1 (generic-рендер дублирует поля) |
| 8 | RAG → `memory_rag`; `limits_chat_budgets` 10 / `limits_chat` 25 | `limits_rag` = 2 ключа, `group_tab('limits_rag')==memory_rag`; budgets 10, chat 25 | ✅ |
| 9 | PERMsoc без 10 миселённых; Леха/Костик раздельно | 10 ключей в `limits_transcribe`(6)/`limits_video_summary`(3)/`limits_media_download`(1); `limits_media_permsoc`=7; `reactions_alan`=3 + `limits_alan`=3; `reactions_kostik`=1 + `limits_kostik`=1; `reactions_persons`=2 (Славик/Оля) | ✅ |
| 10 | Proxy/cookies → М6; diagnostics → М9; сервер/логи → Статус | `keys_youtube` в `mod_video_summary`; `models_checkup`/`keys_betterstack` в `mod_checkup`; оба отсутствуют в `llm_providers`; `#/` не менялся | ✅ |
| 11 | Нет emoji в `#/how` и матрице | `iconGlyph('help')` / `iconGlyph('admin_panel_settings')`, `restart_alt`, `manage_accounts`; emoji `ℹ️/🔐/⟳/⚙` в этих двух местах отсутствуют | ✅ |
| 12 | Эксклюзивный аккордеон «Доступы и роли» | `accessOpen ∈ {null,'roles','local','admins'}`, `setAccess`, `aria-expanded`, `v-show` — одна панель | ✅ |
| 13–14 | Каталог-инвариант / TABS↔TAB_RULES | §1 | ✅ |
| 15 | RBAC/DM/409/scope/key-availability/матрица | §3 | ✅ (2 info) |
| 16 | pytest 0 регрессий; node --check; git diff --check | §4 | ✅ |
| 17 | Ноль PG-DDL; SQLite v8; bot.py; media/ | §1 | ✅ |

### 2.1. Ремедиации прошлых раундов

- **R10.5-1 (BackButton re-init) — ✅ ЗАКРЫТО.** `initBackButton()` вызывается на `ready`
  (`web/app.js:995-999`) и на BOOT (`:953`) под guard `_boundBackApi` (`:2148-2150`);
  `goBack()` при открытой модалке закрывает окно (`:2130-2134`).
- **R10.5-2 (DM `models.*` редактируемы → 422) — ✅ ЗАКРЫТО.** DM-ветка `canEditConfig`
  (`web/app.js:2392-2399`) проверяет `dmItem.per_chat === false` → read-only + fallback
  `cat==='models'||cat==='keys'`; `GET /api/config` возвращает `per_chat` (`routes.py:331`).

## 3. Проверенные области — вердикты

1. **Каталог/расщепления**: `limits_media`→4, `limits_persons`→2, `limits_youtube_web`→2,
   `limits_cooldowns`→0, `flags_modules`→7 (+checkup в `flags_service`),
   `flags_chat_behavior`→7, `reactions_persons`/`alan`/`kostik`, `limits_chat_budgets`→10,
   `limits_chat`→25, +`limits_rag`. Все pg-ключи на месте, значения не мигрируют, DDL нет.
2. **Гейты (5 новых)**: статически и тестово `OFF → UNHANDLED`; `youtube` гейтит только
   `mode=="summary"` (transcript/«транскрипт» работает). 6 существующих тумблеров
   (`summary/direct_botword/voice_transcription/download/dream/nostalgia`) подтверждены
   как реальные гейт-точки.
3. **`POST /api/llm/test`**: `requires_global_admin()` (403; тест на `MODERATOR_ID`),
   rate-limit 5с `(user, block)` → 429, `probe_block` всегда 200 c `{ok,...}`,
   `sanitize_error` вырезает ключ, ключ не логируется и не возвращается штатно.
   `search_keys` не требует base_url; `llm_guard` намеренно не тестируется.
4. **Фронт навигации**: hash-роутер и алиасы legacy-роутов (`ROUTE_ALIAS` →
   `replaceState`); `#/modules` — не hub; back закрывает модалку раньше роута;
   глобальный Esc (`_onKeydown`) закрывает модалку; Сон/Ностальгия-панели перенесены
   в модалку (`_ensureModuleData`, не по `activeTab`).
5. **Матрица/роли/matrix**: `param_permissions_list` не менялся; `TAB_SECTION_ORDER`
   19 секций; матрица только global admin; emoji→Material.
6. **DM/RBAC**: `canEditConfig` DM-ветка с `per_chat`; `keys.*` — только BYOK;
   недоказуемо-ослабляющих фронтовых гейтов не найдено (сервер остаётся источником истины).
7. **Секреты/утечки**: новых секретов в диффе нет; `blockFieldPlaceholder` для секретов
   отдаёт только `{configured,last4}`; `blockFieldValue` для секрета = '' (сохранённый
   ключ НИКОГДА не уходит в тест/сохранение без повторного ввода).

## 4. Новые находки раунда 10.6

### [R10.6-1] severity: minor — LLM Провайдеры: дублирующиеся редакторы (prov-блоки + generic-группы)
**Файл**: `web/index.html:701-1053` (generic-рендер `currentTabGroups`) не подавлен при
`activeTab === 'llm_providers'`; при этом `web/index.html:709-751` уже рендерит
`providerBlocks`. `web/app.js:856-859` (`currentTabGroups`) и `:2517-2563`
(`groupedForTab`) возвращают группы `llm_providers` из `TABS.sources`.
**Суть**: из 37 параметров вкладки **21 присутствует дважды** — в prov-блоке и в
generic-группе: `models.llm_base_url`, `models.llm_model_name`, `keys.llm_api_key`,
`keys.llm_fallback_api_key`, `keys.tavily_api_key`, `keys.exa_api_key`,
`keys.groq_api_key`, `keys.openrouter_api_key`, `keys.media_share_secret`,
`models.llm_fallback_*`, `models.video_primary_model`, `models.groq_*`,
`models.openrouter_*`, `models.embedding_*`, `models.llm_timeout/retries/total_budget`.
Противоречит контракту §6.2 «ONE visual block = base_url + model + api key» и духу
«один дом» (§5.2). На данные не влияет (оба пишут тот же pg-ключ через `/api/config`),
поэтому minor, а не major. Часть 16 «generic-only» параметров (retry backoff, CB-пороги,
tokenizer, groq/video timeouts) действительно не представлена в prov-блоках — вероятно,
generic-рендер сохранён для parity, но 21 дубль — лишний.
**Ремедиация**: `v-if="activeTab !== 'llm_providers'"` вокруг generic-рендера (а 16
«только generic» перенести в соответствующие prov-блоки/отдельную «Дополнительно»-секцию),
либо сузить `TABS.llm_providers.sources` до 16 непокрытых групп.

### [R10.6-2] severity: minor — `POST /api/llm/test`: SSRF-периметр (https — любой хост, включая loopback/internal)
**Файл**: `services/llm_probe.py:58-80` (`_safe_base`), эндпоинт `web/api/routes.py:1225`.
**Суть**: `http` разрешён строго для точных `localhost/127.0.0.1/::1` (префиксный обход
`localhost.evil.com`, `user@host` — отклонены, покрыто тестами). Однако **`https`-схема
принимается для ЛЮБОГО хоста** без проверки на private/loopback/link-local: проходят
`https://127.0.0.1`, `https://localhost`, `https://[::1]`, внутренние DNS-имена и
DNS-rebind. Endpoint отправляет запрос и возвращает до 300 симв. тела ответа
(`sanitize_error`), т.е. даёт слепое/частичное SSRF-чтение. Ущерб ограничен: требуется
`requires_global_admin`, а глобальный админ и так управляет `models.*base_url` и может
инициировать LLM-вызовы; ключ — вызывающего, не сохранённый. Info/major-границы: minor.
**Ремедиация**: allowlist LLM-хостов либо denylist private-range (RFC1918/loopback/
link-local) и для `https`; явно задокументировать trust-boundary «global admin».

### [R10.6-3] severity: minor — `POST /api/llm/test`: R17-эхо `api_key` в 422-теле
**Файл**: `web/api/routes.py:126-132` (`LlmTestRequest`), `:1225` (эндпоинт).
**Суть**: при невалидном/неполном теле FastAPI/Pydantic 2 возвращает `422` с `input`,
содержащим всё присланное тело. Проверено на минимальном FastAPI-приложении:
`POST {"api_key":"sk-super-secret"}` (без `block`) → `422 {"detail":[{...,"input":
{"api_key":"sk-super-secret"}}]}`. Ключ эхо-возвращается тому же глобальному админу,
пользовательских утечек нет (кастомного error-хендлера/логирования тела в `web/app.py`
нет), но строгий R17 «ключ не возвращается» формально нарушается и может попасть в
client-логи/скриншоты при малформ-запросе.
**Ремедиация**: принять ключ не отражаемым полем (например, отдельная модель без
`api_key` и `Depends`/`Header`) или кастомный `RequestValidationError`-хендлер,
вычищающий `input.api_key`.

### [R10.6-4] severity: info — `/api/llm/test` вне спецификационного списка блоков
**Файл**: `services/llm_probe.py:35-38` (`KNOWN_BLOCKS`), `web/app.js:388-398`.
**Суть**: спека §6.3 перечисляет `embeddings`/`checkup_betterstack`, но не `media_share`
(в `KNOWN_BLOCKS` есть, UI-кнопка есть) и не `llm_guard` (в `KNOWN_BLOCKS` нет — верно);
`embeddings` в UI помечен `testable:false` (нет base_url) — кнопки нет. Отклонение
UI/контракта, не дефект.

### [R10.6-5] severity: info — мёртвые записи `ICONS` после удаления вкладок
**Файл**: `web/app.js:228-233` (`speed`, `theater_comedy`, `toggle_off`, `toggle_on`),
также неиспользуемые `stop_circle` (`:229`), `account_balance_wallet` (`:208`).
**Суть**: удалены вкладки `limits`/`reactions_triggers`/`modules_switches`, но их
Material-коды остались в карте. Безвредно (шрифт-субсет/PUA-канон 10.5 не пересобирался),
но мёртвый код. Удалять осторожно: сверить с `test_font_subset`.

### [R10.6-6] severity: info — rate-limit расходуется до валидации блока
**Файл**: `web/api/routes.py:1240-1242`.
**Суть**: `_LLM_TEST_LAST[rl_key] = now` до `probe_block`; для `block` из
`KNOWN_BLOCKS`-неизвестных probe вернёт «неизвестный блок», но слот 5с уже сожжён.
Admin-only, косметика.

## 5. Итог 10.6

- **Блокеров: 0. Major: 0.** Minor: **3** (R10.6-1 дубль LLM-редакторов; R10.6-2 SSRF
  https-периметр; R10.6-3 422-эхо ключа). Info: **3** (R10.6-4…R10.6-6).
- Для мержа **не обязательны**; R10.6-1 и R10.6-3 — точечные ремедиации (1 `v-if`
  / 1 validation-хендлер), рекомендуются в follow-up.
- Инварианты соблюдены: каталог **392 / 91 / 364 / mapped 89**; `TAB_RULES` **19**,
  каждая группа ровно на одной вкладке; **ноль PG-DDL**; SQLite **v8**; `bot.py` не
  тронут; `media/` не тронут; секреты не коммитятся; R16/R17 держатся штатно.
- Ремедиации **R10.5-1** и **R10.5-2** закрыты.
- pytest **5023 passed / 0 failed** (1 pre-existing Starlette-deprecation warning +
  «closed 12 leaked aiosqlite connection(s)» — ресурс-предупреждение, не регресс).
- `node --check` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean.

*Round 10.6 report generated by Scanner on 2026-09-11*
