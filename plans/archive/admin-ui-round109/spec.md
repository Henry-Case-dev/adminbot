# spec.md — Раунд 10.9 `admin-ui-round109`

> **Статус:** 🟢 Design (Step 2, @Architect) — передано @Builder.
> **Преемник:** 10.8 `admin-ui-round108` (pytest 5076/0, health 200).
> **Шапка каталога (baseline):** REGISTRY **392** / GROUPS **91** / Settings **364** / mapped **89** / TAB_RULES 19 / CONFIG_TAB_TITLES 19.
> **HEAD рекогносцировки:** `51f308b` (tasks.md @PM, 12.09.2026).
> **Источники:** `plans/features/admin-ui-round109/tasks.md`; `plans/reports/round10.8_scanner_audit.md` (учтён, см. §0.3).

---

## 0. Скоуп, инварианты, учёт аудита

### 0.1 Скоуп

| Трек | Пункты | Деплой |
|---|---|---|
| **UI/UX + статус** | 1, 3, 4, 5, 6, 7.1, 7.2, 8 | один релиз (git) |

**[OUT OF SCOPE] Пункт 2 — вне проекта.** Пункт 2 — инфраструктурный инструмент локального IDE владельца (OpenCode), **не часть бота**. Ни бот, ни backend о нём не знают; в коде/конфиге/тестах проекта ссылок нет и быть не должно. Пункт 2 исходного ТЗ в скоуп проекта **не входит** — это отдельный инфраструктурный deliverable @DevOps (см. §2).

### 0.2 Инварианты (не ломать)

- **Ноль новых PG-DDL**; SQLite `user_version` = **v8** не трогать.
- **`bot.py` router order — не трогать** (гейты — только через существующие `PermsocGateFilter`).
- **`media/` — не трогать**; `.env` — не трогать.
- **Baseline `pytest` 5076 passed / 0 failed**; цель — регрессий 0, +новые.
- `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- Секреты не коммитить (R17). Каталог-пины обновить **синхронно** (см. §9).

### 0.3 Учёт последнего аудита @Scanner (R10.8)

Согласно мандату, прочитан `plans/reports/round10.8_scanner_audit.md` (HEAD `636a75d`; pytest 5073/0; 0 blocker / 0 major; 2 minor, 3 info):

- **R10.8-5** (APP_VERSION 2.51.0 vs README v2.52.0 + кэш субсета шрифта) → **учтено п. плюс-финал**: T-1307 поднимает `APP_VERSION` → **2.53.0**; `?v=__APP_VERSION__` у `@font-face` уже есть (`index.html:72`). Версию считать/обработать в финале.
- **R10.7-1/-2** (`status_service` health/gap-fill) → **учтено п.7.1** (health bugfix).
- **R10.6-1** (дубль generic-рендера `llm_providers`) → **учтено п.7.2** (`providerCoveredKeys` уже есть, сохранить; новые display-name-поля тоже исключает).
- **R10.8-1** (Esc не закрывает окна «Доступов») — `escClose` уже реализован (`app.js:1916-1919`); **в скоуп 10.9 не входит** (подтверждено, закрыто ранее).
- **R10.8-2/-3** (stale-комментарий `section`, мёртвый `TABS[].icon/visibleTabs/tabMat`) — **вне скоупа**, кандидаты follow-up.
- Инварианты R10.8 (392/91/364, 0 PG-DDL, v8) соблюдены; 10.9 их осознанно меняет по каталогу (см. §9).

---

## 1. п.1 — PERMsoc: персоны, owner-блоки, рабочие тумблеры

### 1.1 Root cause

1. Группа `reactions_persons` (`param_catalog.py:300`, title «Персоны (ID): Славик и Оля») смешивает владельцев: `SLAVIK_USER_ID` (`:1104`) и `OLYA_USER_ID` (`:1156`).
2. Параметры одного владельца размазаны по 5–7 группам (`reactions_*`, `flags_media`, `limits_media_permsoc`, `limits_mimic`, `limits_deadpage`), визуально не связаны.
3. **Дубль тумблера:** `PERMSOC_ENABLED` (`param_catalog.py:662`, группа `flags_permsoc`) рендерится generic-bool-карточкой (`index.html:926-944`) НИЖЕ мастер-карты с тем же смыслом (`index.html:818-826`). То же для `OLYA_ENABLED` (`:668`) и `MIMIC_ENABLED` (`:680`).
4. Модули `slavik/kostik/alan` **не имеют** под-флага (`permsoc.py:51-72`, `sub_flag_key=None`) — сознательное решение T-878/P1; «выключить только Славика» сейчас невозможно.

### 1.2 Решение (Architect)

**Owner-блоки** — это UI-концепт поверх каталога. Рендер для `activeTab === 'permsoc'` переходит с generic-цикла на 4 collapsible `<details class="owner-block">`, каждый со **строго одним** тумблером в `<summary>`:

| Блок | Тумблер (`pg_key`) | Путь записи | Состав |
|---|---|---|---|
| **Славик** | `flags.slavik_enabled` **(НОВЫЙ)** | `saveConfigItem` (config bool) | `reactions_slavik`, `reactions_deadpage`, `limits_deadpage`; ключи `reactions.slavik_user_id`, `limits.slavik_mimic_min_words`, `limits.slavik_mimic_cooldown`, `limits.gif_interval`, `limits.slavic_photo_interval` |
| **Оля** | `flags.olya_enabled` (существующий) | `saveConfigItem` | `reactions_olya`; `reactions.olya_user_id`, `flags.olya_caption_enabled`, `flags.olya_repost_enabled`, `flags.olya_always_send`, `flags.olya_caption_mention_enabled`, `limits.olya_cooldown` |
| **Мимикрия** | `flags.mimic_enabled` (существующий) | `saveConfigItem` | `reactions.mimic_victim_user_ids`, `limits.mimic_min_words`, `limits.mimic_cooldown`, `flags.mimic_forwards_enabled`, `reactions.alan_mimic_enabled`, `reactions.kucha_enabled` |
| **Общее / Мастер** | `flags.permsoc_enabled` (мастер) | при `isChatContext()` — `PUT /api/chat/{id}/gates` (`togglePermsoc`); иначе — `saveConfigItem` (глобальный дефолт) | `reactions_admin`, `reactions_alan`, `reactions_kostik`, `reactions_war`, `reactions_common`, `reactions_goodmorning`, `reactions_permsoc`, `reactions_word_reactions`, `limits_alan`, `limits_kostik`, `limits_media_permsoc` (общие: `COMMON_COOLDOWN`, `DANGER_COOLDOWN`, `SELFDEV_COOLDOWN`, `WORK_COOLDOWN`), `flags_media` (общие: `COMMON_MEDIA_ENABLED`, `COMMON_WORK_MEDIA_ENABLED`), `flags_permsoc_behavior`. Плюс read-only сводка 5 модулей. |

Правило принадлежности (детерминированное, реализуется константой `PERMSOC_OWNER_BLOCKS` в `web/app.js`):
`item ∈ owner`, если `key ∈ owner.keys` **или** (`group ∈ owner.groups` **и** `key ∉ ∪otherOwner.keys`).
«Общее» получает всё, что не попало ни в один персональный блок.
**Из тела блока исключаются** ключи-тумблеры (`flags.permsoc_enabled`, `flags.slavik_enabled`, `flags.olya_enabled`, `flags.mimic_enabled`) — они рендерятся только в `<summary>`.

**Ключевая правка бэкенда (п.1):** новый флаг `SLAVIK_ENABLED` (Settings + `_FLAGS`, группа `flags_permsoc`, default **True**) и в `services/permsoc.py` у модуля `"slavik"` `sub_flag_key="flags.slavik_enabled"`; в `DEFAULT_SUB_FLAGS` добавить `"flags.slavik_enabled": True`. Untouched → `True` → поведение байт-в-байт; OFF → Славик независимо замолкает. `PermsocGateFilter` уже стоит в хендлерах — router order `bot.py` не меняется.

### 1.3 Точные правки (file:line)

| Файл | Правка |
|---|---|
| `services/param_catalog.py:300-301` | **Удалить** `GroupSpec("reactions_persons", …)`. |
| `services/param_catalog.py:1104` | `SLAVIK_USER_ID` → `group="reactions_slavik"`. |
| `services/param_catalog.py:1156` | `OLYA_USER_ID` → `group="reactions_olya"`. |
| `services/param_catalog.py:662-665` | `PERMSOC_ENABLED` остаётся (становится тумблером «Общее»). Добавить `("SLAVIK_ENABLED", "Славик включён", "flags_permsoc", …)` в `_FLAGS`. |
| `config/settings.py` (блок PERMsoc-флагов, ~`:376-394`) | `SLAVIK_ENABLED: bool = _env_bool("SLAVIK_ENABLED", True)`. |
| `services/permsoc.py:51-72` | `PermsocModule("slavik", …, "flags.slavik_enabled", …)`; `DEFAULT_SUB_FLAGS["flags.slavik_enabled"]=True`. |
| `services/param_catalog.py:1668-1680` (`TAB_PERMSOC`) | Убрать `"reactions_persons"` из `CATEGORY_REACTIONS` frozenset. |
| `web/index.html:812-854` | Удалить отдельную мастер-карту (её тумблер уезжает в блок «Общее»; сводка 5 модулей — внутрь «Общего»). |
| `web/index.html:887-1106` | Для `activeTab === 'permsoc'` рендерить owner-блоки вместо generic-цикла; generic-bool тумблеры исключены. |
| `web/app.js:326-430` | Добавить `PERMSOC_OWNER_BLOCKS`; `permsocModuleBadge` (app.js:1671-1683) — slavik теперь по под-флагу, не `derived (master)`. |
| `web/app.js` (новое) | `toggleOwner(owner)` → `saveConfigItem` либо `toggleGate('permsoc', …)`. |

### 1.4 Acceptance

- На вкладке «Функции PERMsoc»: 4 сворачиваемых блока; в каждом ровно один тумблер, вне тела; дублей generic-bool нет.
- Тумблер «Славик» реально включает/выключает только славиковы триггеры (не трогая Олю/мимикрию); Оля/Мимикрия — свои; мастер — все.
- Поведение нетронутых флагов идентично (SLAVIK_ENABLED default True).
- `reactions_persons` отсутствует; ID персон в блоках владельцев.

### 1.5 Тесты

- Python: `tests/test_param_catalog.py` (GROUPS 90, наличие `SLAVIK_ENABLED`, `reactions_persons` отсутствует; `TAB_PERMSOC` без persons), `tests/test_frontend_tab_mapping.py` (91→90; REGISTRY 400), `tests/test_round106_ia_smoke.py`, `tests/test_webapp_parity_smoke.py`, `tests/test_permsoc*` (slavik sub-flag: default True; OFF гейтит).
- UI-маркеры: новый `tests/test_webapp_round109_ui.py` — `PERMSOC_OWNER_BLOCKS`, `owner-block`, `SLAVIK_ENABLED`, отсутствие `flags_permsoc`-generic-карточки на permsoc.
- Live Android (QA): сворачивание, один тумблер, реальное изменение поведения per chat.

### 1.6 Parity

Один источник истины — `permsoc.master_enabled/module_enabled`; тумблеры пишут в **один** слой (`flags.*` config) или в `gates.permsoc` (мастер) — не оба одновременно. `TAB_RULES` = 19; скрытых/декоративных флагов нет.

---

## 2. п.2 — инфраструктура IDE — ⛔ ВНЕ СКОУПА проекта

**Пункт 2 — это инфраструктурный инструмент локального IDE владельца (OpenCode), а не часть бота.** Бот и его backend о нём ничего не знают: ссылок на него в коде, конфигах и тестах проекта нет и быть не должно.

Серверное развёртывание инструмента — **отдельный инфраструктурный deliverable @DevOps** (вне репозитория и вне данного эпика; на 12.09.2026 выполнено). Готовый `opencode.jsonc` передаётся владельцу **в чате** и в репозиторий проекта не кладётся.

Команды установки, systemd-юнит, правила firewall и JSON-конфиг OpenCode в плане проекта **не хранятся** (при необходимости — в git-истории отдельного серверного infra-трека).

---

## 3. п.3 — Скролл не сбрасывается при сохранении параметра

### 3.1 Root cause

`web/index.html:755`: `<div v-if="configLoading" class="card p-8"><div class="spinner"></div></div>`.
`loadConfig` (`web/app.js:2459`) ставит `configLoading=true`, и во время повторного запроса **вся ветка конфига заменяется коротким спиннером** → высота документа падает → браузер клампит `document.scrollingElement.scrollTop` к 0. После рендера позиция остаётся 0. `saveConfigItem` (`app.js:2706`), `saveKeyItem` (`:2749`), `saveBlock` (`:2081`), `toggleModule` (`:1972`) и 409-ветки (`:2710`) вызывают `loadConfig()`.

`setTab` (`app.js:2234-2238`) намеренно сбрасывает скролл — **не трогать**.

### 3.2 Exact fix

1. `web/index.html:755` → `v-if="configLoading && !configItems.length"` (большой спиннер только на первой загрузке; при ре-фетче контент остаётся).
2. Общий helper в `web/app.js`: `_preserveScroll(fn)` — снимает `document.scrollingElement.scrollTop` до вызова, восстанавливает в `$nextTick` после.
3. Обернуть `await this.loadConfig()` в `saveConfigItem`, `saveKeyItem`, `saveBlock`, `toggleModule`, `toggleOwner` и в 409-ветках.
4. (Доп.) Пока `configLoading && configItems.length` — тонкий оверлей/полупрозрачность, а не подмена карточек.

### 3.3 Acceptance / тесты / parity

- После сохранения bool/int/float/str/json/select и ключей на прокрученной странице позиция сохраняется (±50 px).
- `setTab` по-прежнему скроллит вверх.
- JS-юнит: `tests/js/` маркер `_preserveScroll`/условие `configItems.length`; `node --check`.

---

## 4. п.4 — Переписать описания (стиль + скоуп)

### 4.1 Скоуп

- `services/param_catalog.py`: **все** `GroupSpec.description` (90 после п.1) и **все** `ParamSpec.description` (400 после п.7.2) в списках `_PROMPTS`, `_KEYS`, `_MODELS`, `_MODELS_PG_ONLY`, `_FLAGS`, `_LIMITS`, `_REACTIONS`, `_CONTENT_SETTINGS`, `_CONTENT`, `_CONTENT_STR`, `_MEMORY`.
- UI-строки: `web/index.html` — hint-тексты PERMsoc (`:829-833`, `:849-853`), заголовки/подсказки секций, пустые состояния (`:874-878`, `:1204`, `:1207`, `:1247-1249`, `:2569-2571`, `:2583-2585`), `:1214-1221` при удалении (п.5).
- `web/app.js:364-430` — человеческие label'ы provider-полей (`base_url`→«Адрес сервера», `model`→«Модель», `api key`→«Ключ»).

### 4.2 Правила стиля (обязательны)

1. **Одно-два простых предложения**, ≤ ~120 символов на предложение.
2. **Никаких аббревиатур/жаргона.** Запрещены: RAG, LLM, STT, TTS, API, JSON, токен(в тех. смысле), TTL, backoff, jitter, MMR, WAL, CB, HMAC, SSRF, DDL, regex, cron, semaphore, URL, cookies, webhook, prompt, embedding, id8, vector, GraphRAG, дайджест. Замены: «нейросеть», «поиск по памяти», «отпечаток текста», «пересказ», «ключ», «адрес», «текст-инструкция».
3. **Никаких AI-паттернов**: «данный параметр», «осуществляет», «является», «в рамках», «представляет собой», «позволяет», шаблонные «Включает… Выключено — …» подряд на каждой карточке, длинные тире-перечисления.
4. **Лёгкая ирония**, дружелюбно, «ты»/«бот». Например: «Сколько слов должно быть в сообщении, чтобы бот решил его передразнить. Хочешь тишины — задирай число.»
5. **Обратная связь с последствием**: короткий ответ «что будет, если увеличить/выключить».
6. Ключи (`item.key`) и тех. имена **не переводить и не менять**.

### 4.3 Acceptance / тесты / parity

- Пустых `description` нет ни у одной группы/параметра.
- Тест-маркер: нет запрещённых подстрок (список из §4.2.2) в `title_ru`/`description`; длина в пределах.
- Выборочное чтение «глазами новичка» (QA) ключевых групп: PERMsoc, Модули, Ключи, Лимиты.
- Parity: меняется только текст; `key`/`type`/`group`/значения — без изменений.

---

## 5. п.5 — «Тяжёлые фичи» (дубль) → удалить

### 5.1 Root cause

`web/index.html:1213-1250` — карточка с тумблерами `gateInfo.gates` (`dream`, `nostalgia`, `lore_auto`). `HEAVY_FEATURES = {dream, nostalgia, lore_auto}` (`services/feature_gates.py:27`).
- `dream` и `nostalgia` **дублируют** per-module тумблеры «Сон» (`memory.dream_enabled`) и «Ностальгия» (`memory.nostalgia_enabled`) в списке 11 модулей (`index.html:1153-1172`).
- `lore_auto` **уже управляется** в «Сводке»: модалка чата (`index.html:2872-2880`, `toggleKillswitch`) шлёт `POST /api/oversight/chat/{id}/killswitch` для всех `heavy`-фич.

### 5.2 Exact fix

- **Удалить** карточку `index.html:1213-1250` целиком.
- Удалить осиротевшие `whoCanToggle` (`app.js:1659`), `optInCount` (`:1706`) и их использование.
- Оставить `loadGateInfo`/`gatesBusy`/`toggleGate` — используются мастер-тумблером PERMsoc (`togglePermsoc`).
- `lore_auto` сохраняется: killswitch в «Сводке» (не дублируется).
- Удалить неиспользуемые ветки в `loadModules` только если после правок `gateInfo` больше не нужен для «Модулей» (permsoc использует — **оставить**).

### 5.3 Acceptance / тесты / parity

- На «Модулях» нет карточки «Тяжёлые фичи»; нет мёртвых ссылок/вызовов.
- `dream`/`nostalgia` управляются через модули; `lore_auto` — через «Сводку» (модалка чата). Функционал не потерян.
- `tests/test_round106_gates.py` / UI-маркеры обновить (нет `optInCount`/`whoCanToggle`).

---

## 6. п.6 — «Бюджет фона» (нули): диагностика + перенос в «Сводку»

### 6.1 Root cause (диагноз, не баг расчёта)

- Источник: `GET /api/workers/budget` (`web/api/gates.py:148-157`) → `worker_budget.get_day_summary` (`services/worker_budget.py:237-267`).
- `used=0` возвращается, когда **нет строк** `worker_budget` за `today()` (`WORKER_BUDGET_TZ="Asia/Yekaterinburg"`). Строки пишут только `consume()` из `dream_worker`/`lore_worker`/`nostalgia_worker`. Если воркеры выключены/не тикнули (начало суток, jitter) — день пуст, это **корректный ноль**, а не поломка.
- UI-дефект: `index.html:1194-1205` во втором столбце перебирает **все** `budgetInfo.chats` (не фильтруя по `activeChatId`) → на «этом чате» показывает чужие/никакие; при отсутствии строк пишет «День не начат — счёт пуст».
- **Дубль:** `oversight.build_summary` (`services/oversight.py:141,223`) возвращает `global_budget` из того же `get_day_summary`, а per-chat `budget` (`:190-199`) уже рендерится в «Сводке» колонкой «Бюджет» (`index.html:1564-1568`).

### 6.2 Решение

**Перенести** «Бюджет фона» на вкладку «Сводка» и **убрать** с «Модулей».
- `index.html:1176-1211` — удалить карточку.
- В `index.html` в секции `#/oversight` добавить компактную полосу «Бюджет фона (день)» сверху таблицы: день/TZ, глобальные вызовы и токены с прогрессбарами (`budgetRatio`). Источник — `oversightData.global_budget` (уже приходит) **или** `loadBudgetInfo()`; выбрать одно. **Решение:** вызывать `loadBudgetInfo()` из `loadOversight` (единый клиентский путь, прогрессбары) и рендерить `budgetInfo`; `global_budget` не дублировать.
- Убрать `loadBudgetInfo()` из `loadModules` (`app.js:1623`) — «Модули» больше бюджет не грузит.
- Убрать per-chat секцию из карточки (она уходит); per-chat остаётся колонкой в таблице «Сводки».
- Пустое состояние: `used==0` → человеческое «Сегодня расхода ещё не было», без красных прогрессов.
- Endpoint `GET /api/workers/budget` **сохранить** (контракт/тесты); backend `worker_budget.py` **не менять** (нулей-баг отсутствует).

### 6.3 Acceptance / тесты / parity

- «Бюджет фона» есть только в «Сводке»; на «Модулях» его нет; дубля нет.
- Цифры совпадают с колонкой «Бюджет» для того же чата.
- `tests/test_round106_gates.py`, `test_webapp_*` — обновить маркеры переноса.

---

## 7. п.7 — Dashboard/статус + форма провайдеров

### 7.1 Dashboard: один блок «Доступность ключей» + реальный health

#### 7.1.1 Root cause

- `index.html:2547-2564` — `v-for="card in statusData.llm"` рендерит карточки по одной; заголовок — хардкод `card.provider` (`:2548`); нет группировки.
- `services/status_service.py:139-183` `llm_registry()` хардкодит `provider` = `"deepseek"/"groq"/"openrouter"/"deepseek_fallback"`; **эмбеддинг-провайдеров нет** (открытый Q2).
- Health **баг:** `_check_health` (`:187-201`) кэширует 60 с (`_HEALTH_CACHE_SECONDS`) → отдаёт **stale-200** после падения провайдера; `_ping_models` (`:203-224`) пингует `GET {base}/models` — может быть 200, тогда как `/chat/completions` отдаёт `502/503`; исключение → `http_status=None`, `status="unreachable"`, код/таймаут не различаются.

#### 7.1.2 Решение

**a) Один блок, 4 группы функций** (рендер `index.html`):
- `<div class="card" v-for="g in llmGroups">` → «Доступность ключей» (переименовать существующую `keys-avail`-карту `:2577` в «История доступности ключей», чтобы не путать).
- Группы: **Основные функции ИИ** (main + fallback), **Транскрибация** (groq), **Саммаризация видео** (openrouter), **Эмбеддинги** (main + 2 fallback).
- Строка: `display_name` (кастомное имя, п.7.2) → реальный провайдер (`host` из base_url) и модель → маска ключа (`configured ••••last4` / «не настроен») → задержка мс → Health (статус + HTTP-код).
- Убрать хардкод-имена; `:key` и заголовок — по `card.module_id` / `card.display_name`.

**b) Контракт `status_service`** (без хардкода имён):
- В записи реестра: `module_id`, `group_id`, `group_title`, `display_name` (из п.7.2), `provider` = host(`base_url`) через `urlsplit(...).hostname`, `model`, `key` (маска по роли), `latency_key` (внутренний: `deepseek`/`groq`/`openrouter` для `_llm_latency`), `last_latency_ms`, `health`.
- `module_id`: `llm_main`, `llm_fallback`, `stt_groq`, `stt_openrouter`, `video_openrouter`, `emb_main`, `emb_fallback`, `emb_fallback2`.
- **Эмбеддинги (Q2):** main = `models.llm_base_url` + `keys.llm_api_key` + `models.embedding_model_name`; fallback1 = `EMBEDDING_FALLBACK_BASE_URL` + `EMBEDDING_FALLBACK_API_KEY` + `EMBEDDING_FALLBACK_MODEL|EMBEDDING_MODEL_NAME`; fallback2 = тот же base + `EMBEDDING_FALLBACK_API_KEY_2` + та же модель. Читать через `hot.get(<pg_key>, settings.<FIELD>)`; маска — `_mask_key_for_role`.

**c) Health bugfix (Q3):** реальный минимальный POST к используемому эндпоинту:
- Расширить `services/llm_probe.py` функцией `probe_openai(base_url, key, model, kind)` (`kind ∈ {"chat","stt","embeddings"}`), возвращающей `{ok,status,http_status,latency_ms,error}`; `probe_block` использовать её.
- `status_service._ping_provider(...)` (через ленивый импорт `llm_probe` — без циклов) вызывает `probe_openai`: `chat` → `POST /chat/completions` `max_tokens=1`, `embeddings` → `POST /embeddings`, `stt` → `POST /audio/transcriptions` (multipart, минимальный WAV). **CRITICAL-1:** `stt_groq` — Whisper-модель, chat-запрос к ней всегда падал; для неё используется `kind="stt"`. `stt_openrouter` остаётся `kind="chat"`: расшифровка OpenRouter идёт через `chat.completions` с `input_audio` (см. `openrouter_transcriber`), отдельного `/audio/transcriptions` у него нет.
- Таймаут **5 с**; различать: `status="timeout"` (`httpx.TimeoutException`), `status="unreachable"` (транспорт, `http_status=None`), `status="error"` (`http_status` 4xx/5xx), `status="ok"` (2xx), `status="not_configured"`.
- Кэш: ключ — `module_id`; **2xx кэшируем 60 с, ошибки — 10 с** (никакого stale-200). При ошибке не отдавать старый ok.
- `_build_llm_card` (`:386-412`) прокидывает `display_name`/`group_*`; `key_history.record` — без изменений (allowlist).
- Фронт: `healthBadge` (`app.js:3161`) — `ok`→ok; `timeout`/`unreachable`/`error`→err/warn; рендер `HTTP <code>` и «Timeout». `index.html` внутри нового блока.

#### 7.1.3 Acceptance / тесты / parity

- Один блок, ровно 4 группы; строки в заданном формате; нет «deepseek/groq/openrouter» в выводе/шаблоне.
- При лежащем apinet.cloud показывается реальный код (`502/503`) или «Timeout», **не** 200; при живом — 200 + latency.
- Тесты: `tests/test_status_service.py` (обновить: ключевание по `module_id`, эмбеддинг-записи, `probe_openai`, различение timeout/502, инвалидация кэша), `tests/test_webapp_key_availability_ui.py`, `tests/test_webapp_api.py`.
- Parity: `key_history` allowlist и маскирование по ролям не ослаблены.

### 7.2 Форма провайдеров: «Название модели» первым полем (Q1)

#### 7.2.1 Root cause

`web/index.html:762-804` (`providerBlocks`), `PROVIDER_BLOCKS` `app.js:364-430`: первое поле — `base_url`/`model`; кастомного имени нет; форма растянута на всю ширину.

#### 7.2.2 Решение — хранение

**Новые `ParamSpec`** (не map): 7 полей `models.*_display_name`, тип `str`, группа по функции, `category="models"` → **глобальные** (не per-chat, не BYOK — `models.*` вне `_PER_CHAT_CATEGORIES`), пустой дефолт. Это даёт единый источник для UI и `/api/status`, сид через существующую миграцию Settings→bot_settings (без новой механики).

| ParamSpec (pg_key) | Settings поле | Группа | Питает |
|---|---|---|---|
| `models.llm_display_name` | `LLM_DISPLAY_NAME` | `models_main` | Основные функции ИИ (main) |
| `models.llm_fallback_display_name` | `LLM_FALLBACK_DISPLAY_NAME` | `models_fallback` | Основные функции ИИ (fallback) |
| `models.groq_display_name` | `GROQ_DISPLAY_NAME` | `models_extra_providers` | Транскрибация |
| `models.openrouter_display_name` | `OPENROUTER_DISPLAY_NAME` | `models_video_summary` | Саммаризация видео |
| `models.embedding_display_name` | `EMBEDDING_DISPLAY_NAME` | `models_embeddings` | Эмбеддинги (main) |
| `models.embedding_fallback_display_name` | `EMBEDDING_FALLBACK_DISPLAY_NAME` | `models_embeddings` | Эмбеддинги (fb1) |
| `models.embedding_fallback2_display_name` | `EMBEDDING_FALLBACK2_DISPLAY_NAME` | `models_embeddings` | Эмбеддинги (fb2) |

**UI:** `PROVIDER_BLOCKS` — добавить `{ key: 'models.<...>_display_name', label: 'Название модели', role: '' }` **первым** элементом `fields` в `direct_main`, `direct_fallback`, `transcribe_groq`, `video_summary_openrouter`, `embeddings`; отдельный блок для transcribe_openrouter (тот же `models.openrouter_display_name`). `saveBlock` сохранит его как обычную str (без секрета). `providerCoveredKeys` (app.js:2555-2561) автоматически исключит его из generic-дубля.
**Источник dashboard:** `/api/status` карточка `display_name = models.<...>_display_name || <fallback: «Основная модель»/host>`.

**Layout:** `section.prov-block` → `max-w-3xl mx-auto w-full` (+ `col-span-full`), label фиксированной ширины, поля выровнены влево; в fullscreen форма по центру.

#### 7.2.3 Acceptance / тесты / parity

- «Название модели» — **первое** поле каждого provider-блока; сохранение не ломает `base_url/model/api_key`.
- Имя появляется в блоке «Доступность ключей».
- Форма ограничена (`max-w-3xl`), выровнена; мобильная раскладка не разъезжается.
- Тесты: `test_webapp_round109_ui.py` (маркер первого поля/`max-w-3xl`), `test_webapp_api.py` (7 новых ключей в `/api/config`).
- Parity: `per_chat=False` для `models.*`; BYOK-логика не затронута.

---

## 8. п.8 — Ускорить градиент (слегка)

### 8.1 Root cause / фикс

`web/index.html:39` `--grad-speed:18s` → **`14s`**; `:119` `grad-drift 24s` → **`18s`** (linear/alternate сохранить). `prefers-reduced-motion` (`:122-126`) и `prefers-contrast` (`:127-132`) — **не трогать**; читаемость (offset/opacity .16, плотные подложки) сохранить.

### 8.2 Acceptance / тесты / parity

- Анимация заметно, но не резко быстрее; reduced-motion/contrast уважаются; WCAG AA не нарушен.
- Тест-маркер на новые значения (`test_webapp_round109_ui.py` или существующий `test_font_subset`-стиль).

---

## 9. Каталог: точная дельта (392/91/364/mapped)

| Пункт | REGISTRY | GROUPS | Settings | mapped(_TAB_BY_GROUP) |
|---|---|---|---|---|
| Baseline 10.8 | 392 | 91 | 364 | 89 |
| п.1 `SLAVIK_ENABLED` (+1) | 393 | 91 | 365 | 89 |
| п.1 удаление `reactions_persons` (−1) | 393 | **90** | 365 | **88** |
| п.7.2 7×`*_display_name` (+7) | **400** | 90 | **372** | 88 |
| **Итог 10.9** | **400** | **90** | **372** | **88** |

- `TAB_RULES` = **19**, `CONFIG_TAB_TITLES` = **19** (без изменений).
- `TAB_PERMSOC`: из `CATEGORY_REACTIONS` убрать `reactions_persons` (см. §1.3).
- Синхронно обновить пины: `tests/test_frontend_tab_mapping.py:48,76-77`, `tests/test_param_catalog.py:52,237`, `tests/test_round106_ia_smoke.py:20-24`, `tests/test_webapp_parity_smoke.py:48-52`, `tests/test_webapp_api.py:1181`.
- **Ноль PG-DDL**; Settings растёт только декларативно (новые поля dataclass), SQLite v8 не трогается.

---

## 10. Разрешение 5 открытых вопросов (tasks.md §7)

> Вопросы по пункту 2 (входящая auth, backend/URL apinet, rollout порта) **сняты вместе с пунктом** — инфраструктура IDE вне скоупа проекта (см. §2).

| # | Вопрос | Решение |
|---|---|---|
| 1 | Хранение «Название модели» | **7 новых `ParamSpec`** (`models.*_display_name`), Settings-поля, глобальные (per-chat/BYOK не затронуты). Дельта — §9. |
| 2 | Эмбеддинги main + 2 fallback | main = `llm_base_url`+`llm_api_key`+`embedding_model_name`; fb1 = `EMBEDDING_FALLBACK_BASE_URL`+`..._API_KEY`; fb2 = тот же base + `..._API_KEY_2`. Маска — `_mask_key_for_role`. module_id `emb_main/emb_fallback/emb_fallback2`. |
| 3 | «Реальный» health-тест | Минимальный POST: `/chat/completions` (LLM), `/embeddings` (эмбо) и `/audio/transcriptions` (STT/Groq); **да**, отдельная индикация `timeout` vs `502/503` vs `unreachable`. `/models` больше не единственный проб. |
| 4 | Куда общие параметры | Отдельный блок **«Общее / Мастер»**; тумблер = мастер `flags.permsoc_enabled`. |
| 5 | «Тяжёлые фичи» / «Бюджет фона» | Тяжёлые — **удалить** (§5); Бюджет — **перенести в «Сводку»** (§6). |

---

## 11. Feature Flags / Progressive Delivery

- **UI (1, 3–8):** отдельных декоративных фича-флагов не вводим; откат = `git revert`. Гейты модулей персон используются по назначению (реальные, не декоративные).
- **Пункт 2 (инфраструктура IDE):** вне проекта — feature flags не применяются (см. §2).

---

## 12. QA / тест-план (сводно)

- Python: `py -m pytest tests/ -v` — baseline 5076, 0 failed, +новые (round109).
- JS: `node --check web/app.js`; `node tests/js/routing_test.js` → `JS-UNIT-OK`.
- Маркеры/парность: `test_param_catalog.py`, `test_frontend_tab_mapping.py`, `test_round106_ia_smoke.py`, `test_webapp_parity_smoke.py`, `test_status_service.py`, `test_webapp_key_availability_ui.py`, `test_webapp_api.py`, `test_round106_gates.py`, новый `test_webapp_round109_ui.py`.
- Секреты: grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` — пусто.
- Live Android: п.1 (блоки/тумблеры), п.3 (скролл), п.7 (dashboard/health/форма).
- Совместимость: `git diff --check`; `media/`/`bot.py` не тронуты; PG-DDL = 0; SQLite v8.

---

## 13. Handoff

План детерминирован: у каждого пункта root cause, точные `file:line`, AC, тесты и parity. Открытые вопросы закрыты (§10); спорных развилок нет. Реализация — @Builder. После реализации — @Scanner (аудит) и @Architect (Step 7 merge в `plans/ARCHITECTURE.md`).

`@Orchestrator Architecture phase complete, passing the baton.`
