# Spec — admin-ui-round1010 (раунд 10.10)

> **Фича:** `plans/features/admin-ui-round1010/` · **Раунд 10.10** · создано @Architect 12.09.2026 (Step 2).
> **Вход:** `tasks.md` (@PM, Step 1), `plans/reports/round10.9_scanner_audit.md`, `audit_backlog.md`.
> **Область:** 5 пунктов владельца. **П.6 (Headroom) — OUT OF SCOPE этого репозитория.**
> **Задачи:** T-1315…T-1332 + T-1334…T-1339 (скрипт п.4 = T-1326).

---

## 0. Инварианты (проверять на Step 7)

- **Ноль новых PG-DDL** (`CREATE/ALTER/ADD COLUMN`) — п.4 только DML в существующей `chat_profiles.chat_params`.
- **SQLite v8** (`_SCHEMA_VERSION_AGI_MEMORY == 8`) не трогать; `services/database.py` не менять.
- **`bot.py` router order** не трогать; **`bot.py` вообще не менять** (F-14, тест `test_s5_bot_router_gate_not_touched`).
- **`media/`** и **`.env`** не трогать.
- **Каталог-пины:** REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88; `TAB_RULES` 19 / `CONFIG_TAB_TITLES` 19. Пункты 1–5 **не требуют** новых ParamSpec/GroupSpec.
- Секреты не коммитить (R17); реальные ключи — только на сервере. UI п.3 показывает ключ **как сейчас** (placeholder/маска), не сырое значение.
- Baseline: **5105 passed / 0 failed**; цель ≥ 5105 + новые. `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- Не ломать существующие маркеры-тесты (см. §7).

### 0.1 Учёт @Scanner (обязательно)

Прочитаны `plans/reports/round10.9_scanner_audit.md` (0 blocker / 0 major / 0 medium; 3 low + 3 info)
и `plans/reports/audit_backlog.md`. В план 10.10 инкорпорировано:

- **R10.9-1** (`model_source` fallback/embedding) и **R10.9-3** (stale docstring `status_service.py:10-15`) → **T-1334** (P2, точечно, 2–10 строк). Если риск > польза — Builder фиксирует решение не брать письменно.
- **R10.9-4** (health-кэш по `module_id`) — **вне скоупа** 10.10 (кандидат follow-up); п.2 его НЕ трогает (не менять кэш/проб).
- **R10.8-5** (APP_VERSION/README + cache-bust) уже закрыт в 10.9 (`APP_VERSION 2.53.0`, README v2.53.0); для 10.10 — **T-1335** (поднять синхронно README + `APP_VERSION` + `?v=`).
- Инфраструктурных ссылок на IDE/Headroom в коде нет — п.6 ничего в репо не добавляет.

---

## 1. Пункт 1 — Header в FULLSCREEN (T-1315/T-1316/T-1317)

### 1.1 Root cause (evidence)

- Шапка: `web/index.html:585-592` (`header.header-sticky`, sticky, z-index 40; safe-area только **по ширине**: `env(safe-area-inset-left/right)`), плюс `@media (max-width:768px) header.header-sticky { padding-top: calc(0.75rem + env(safe-area-inset-top)) }` — `web/index.html:616-620`.
- Профильный блок `ml-auto` (аватар+ник+роль+⛶): `web/index.html:694-709`.
- Fullscreen-модель: `.fullscreen-mode { height:100dvh; overflow:hidden }` + `.fullscreen-mode .scroll-area { overflow-y:auto }` — `web/index.html:603-612`; тоггл `isFullscreen` — `web/app.js:717`, `toggleFullscreen` — `web/app.js:2344-2358`.
- В TMA-fullscreen нативные кнопки (Свернуть/Ещё/Закрыть) лежат поверх верхней полосы webview. `env(safe-area-inset-*)` внутри Telegram WebView на Android **часто = 0**, поэтому `padding-top` не увеличивается и `ml-auto`-блок уходит под нативные кнопки. Telegram отдаёт точные значения в CSS-переменных `--tg-safe-area-inset-*` (device) и `--tg-content-safe-area-inset-*` (свободно от UI Telegram) — подтверждено официальной документацией Mini Apps (Bot API 8.0, поля `safeAreaInset`/`contentSafeAreaInset`, события `safeAreaChanged`/`contentSafeAreaChanged`).

### 1.2 Точный фикс (CSS-only, `web/index.html`, после строки 620)

Добавить **ровно одно** правило, специфичное для fullscreen+шапки (специфичность `(0,2,1)` выше базового `(0,1,1)`, поэтому перекрывает и `@media`, и базовое правило):

- Селектор: **`.fullscreen-mode header.header-sticky`**.
- `padding-top`: `calc(0.75rem + max(env(safe-area-inset-top,0px), var(--tg-content-safe-area-inset-top,0px), var(--tg-safe-area-inset-top,0px)))`.
- `padding-right` / `padding-left`: `calc(1rem + max(env(safe-area-inset-right|left,0px), var(--tg-content-safe-area-inset-right|left,0px), var(--tg-safe-area-inset-right|left,0px)))`.

Правила:
- `max(...)` с `var(--tg-*, 0px)` — безопасный фолбэк: если переменных нет (старый SDK/вне TG) или они = 0, остаётся `env()`, затем базовая `1rem`/`0.75rem`.
- **Не** трогать `.fullscreen-mode .scroll-area` (10.9 scroll), **не** трогать базовый `header.header-sticky` и `@media` (10.7 safe-area по ширине) — новые значения добавляются только в fullscreen-скоупе через `max`, т.е. не могут «уменьшить» текущие отступы.
- JS не менять: `toggleFullscreen` остаётся оптимистичным локальным флагом; класс `.fullscreen-mode` — существующий триггер. (Опционально Builder может добавить слушатель `fullscreenChanged`/`contentSafeAreaChanged` только если Live QA покажет лаг — не требуется по умолчанию.)

### 1.3 Acceptance criteria

- В fullscreen на Android профильный блок (аватар+ник+роль+⛶) виден и не перекрыт нативными кнопками при `env(safe-area-inset-top)==0`.
- Выход из fullscreen не сдвигает layout (правило действует только при `.fullscreen-mode`).
- Горизонтальные отступы 10.7 сохранены (в т.ч. на устройствах с вырезом).
- Вертикальный скролл 10.9 не изменился (шапка sticky, скролл в `.scroll-area`).

### 1.4 Тесты

- Маркер в `tests/test_webapp_round1010_ui.py`: наличие `.fullscreen-mode header.header-sticky`, `--tg-content-safe-area-inset-top`, `max(env(safe-area-inset-top`; сохранность `padding-right: calc(1rem + env(safe-area-inset-right` (10.7) и `.fullscreen-mode .scroll-area` (10.9).
- QA Live Android (T-1317).

### 1.5 Parity note

Чисто CSS, поведение вне fullscreen байт-в-байт прежнее. Rollback = `git revert`.

---

## 2. Пункт 2 — Mobile key-availability chart (T-1318/T-1319/T-1320)

### 2.1 Вердикт: это **RENDER**, не DATA. Контракт `/api/status/key-history` — НЕ менять.

Evidence:
- Данные в порядке: `services/key_history.py` ring 288×5мин, allowlist `ts/ok/http_status`; `api_payload()` (`services/key_history.py:196-203`), запись из `_build_llm_card` (`services/status_service.py:500-507`), роут `web/api/routes.py:1090-1102`. Payload одинаков для mobile/desktop.
- Root cause (render):
  1. Все провайдеры рисуются на одной числовой оси `y ∈ {0,1}` с `min=-0.2,max=1.2` (`web/app.js:3462-3478`); при `ok=true` у нескольких провайдеров линии **сливаются в одну горизонтальную полосу**.
  2. `height="80"` (`web/index.html:2585`) + `responsive:true` (default `maintainAspectRatio:true`) даёт маленькое полотно; x-подписи (`maxTicksLimit:10`) и легенда внизу съедают остаток.
  3. `labels` = union реальных `ts` (`web/app.js:3430-3442`), т.е. ось **неравномерная/категориальная**; при малом числе слотов (история пишется только при вызовах `/api/status`) получается 1–2 точки → сплошной отрезок.
  4. `pointRadius:0` при 1 сэмпле → точка не видна вовсе (`web/app.js:3458`).
- DATA-нюанс (не меняем контракт): история может быть разреженной; фикс обязан жить с 1–2 сэмплами.

### 2.2 Точный фикс (render-only, `web/app.js` + `web/index.html`)

Выделить **чистую** функцию `keyHistoryChartModel(providers)` (юнит-тестируемую) и переписать `renderKeyHistoryChart` на неё:
- Все провайдеры кладутся в **отдельные дорожки (lanes)**: провайдер `i` → значения `i+0.75` (ok) / `i+0.25` (err); `y: { min:-0.2, max: laneCount+0.2, ticks:{display:false} }`. Слияние полос исключено, цвета+легенда отображают дорожки.
- **Сетка времени:** шаг `SAMPLE_BUCKET=300с`, от `end = последний слот` назад минимум `MIN_BUCKETS=12` (1 час), затем все слоты до `end`; при > `MAX_HISTORY_POINTS` — последние `MAX_HISTORY_POINTS`. Отсутствующие слоты = `null` (разрыв, `spanGaps:false` сохраняется).
- **Одиночная точка:** `pointRadius: 3` если у провайдера ≤1 сэмпла, иначе `0`.
- **Высота:** `height = max(120, 44 + laneCount*22)`; `keyHistoryChartHeight` (data-поле) биндится на обёртку `:style="{height: keyHistoryChartHeight+'px'}"`, Chart `maintainAspectRatio:false`, `responsive:true`; chart строится в `$nextTick` после установки высоты.
- Сохранить маркеры существующего теста: строки `stepped: true` и `legend: { display: true` в `web/app.js` остаются.
- `web/index.html:2584-2586`: обернуть canvas в `<div class="keys-chart">` (`position:relative`) с `:style` высотой; атрибут `height="80"` можно оставить как fallback.
- Пустое состояние (`keyHistory.providers` пуст) — как сейчас (`web/index.html:2558-2560`); если провайдеры есть, но сэмплов нет — `keyHistoryChartModel` вернул `null` → чарт не создаётся, пустое состояние не ломается.

### 2.3 Acceptance criteria

- На мобильном график читается как временной ряд: дорожки провайдеров не сливаются; видны ok/err перепады; при 1 сэмпле видна точка; легенда не перекрывает полотно (переносится).
- Пустое состояние сохранено; `/api/status/key-history` контракт неизменен.

### 2.4 Тесты

- JS-юнит в `tests/js/routing_test.js` для `keyHistoryChartModel`: две дорожки не пересекаются; сетка ≥ `MIN_BUCKETS` при разбросе; `null` на пропущенном слоте; `pointRadius===3` при 1 сэмпле; пустой ввод → `null`.
- Маркер в `tests/test_webapp_round1010_ui.py`: `keyHistoryChartModel`, `maintainAspectRatio: false`, `keyHistoryChartHeight`, `:style`-обёртка.
- Существующий `tests/test_webapp_key_availability_ui.py::test_chart_and_legend` остаётся зелёным.

### 2.5 Parity note

`api_payload`/`KeyHistory` не меняются; desktop получает более читаемый график. Rollback = `git revert`.

---

## 3. Пункт 3 — «Провайдеры»: реальные значения (T-1321/T-1322/T-1323)

### 3.1 Root cause (evidence)

- Разметка: `web/index.html:783-788` — `v-model="blockDrafts[f.key]"`.
- `blockDrafts` инициализируется `{}` (`web/app.js:643`) и **нигде не наполняется**; `blockFieldValue` (`web/app.js:2036-2043`) умеет брать значение из `configItems`, но в шаблоне не используется. Отсюда пустые Название/Адрес/Модель; «Ключ» показывает маску через `blockFieldPlaceholder` (`web/app.js:2044-2050`) — его не менять.

### 3.2 Точный фикс (без изменения `saveBlock` и MINOR-3)

1. **Шаблон (`web/index.html:785-788`):** заменить `v-model="blockDrafts[f.key]"` на контролируемое значение + запись черновика:
   - `:value="blockFieldValue(f)"`, `@input="blockDrafts[f.key] = $event.target.value"`.
   - Это показывает реальное значение из `configItems` (fallback внутри `blockFieldValue`) и **не** наполняет `blockDrafts` без правки пользователя → `draft == null` остаётся «не трогать».
2. **`blockFieldValue` (`web/app.js:2036-2043`):** убрать отбрасывание пустой строки — `if (draft != null) return draft;` вместо `if (draft != null && draft !== '') return draft;`. Тогда `''` (явная очистка) показывается пустым, а не откатывается к старому значению. Fallback на `configItems` — прежний.
3. **Сброс черновиков:** в `loadConfig` при успешной загрузке и в `setActiveChat` (`web/app.js:1393-1449`) очищать `this.blockDrafts = {}` (и `this.blockResults = {}` при смене scope), чтобы черновик не «переживал» смену scope/reload и семантика `== null` сохранялась.
4. `saveBlock` (`web/app.js:2109-2153`) **не менять** — по-прежнему пишет только явно заданные черновики (`null` = не трогать, `''` = очистить); `testBlock`/`testField` продолжают использовать `blockFieldValue` (реальные значения для «Проверить»).
5. Секретные поля (`keys.*`) не префиллятся: `blockFieldValue` для них вернёт `''` (в `configItems` значение — объект маски), placeholder = маска `configured ••••last4` / «не настроен».

Альтернатива (наполнение `blockDrafts` в `loadConfig`, как предлагал @PM) отклонена: она делает `saveBlock` «всегда шлёт все не-секретные поля» и ломает отображение `''`-очистки; контролируемый `:value` решает задачу точнее при меньшем риске.

### 3.3 Acceptance criteria

- В «Провайдеры» Название/Адрес/Модель показывают реальные текущие значения (пусто → placeholder/label).
- «Ключ» — как раньше (маска/placeholder); сырой ключ не показывается и не коммитится.
- «Сохранить» пишет только изменённые поля; «очистить» сохраняет `''`; «Проверить» использует реальные значения.

### 3.4 Тесты

- JS-юнит в `tests/js/routing_test.js`: `blockFieldValue` при отсутствии черновика → значение `configItems`; при `''` → `''` (не откат); при заданном → черновик.
- Маркеры в `tests/test_webapp_round1010_ui.py`: нет `v-model="blockDrafts[f.key]"`; есть `:value="blockFieldValue(f)"` и `@input`.
- Существующие MINOR-3 кейсы `routing_test.js` (пустой draft очищает, отсутствующий не шлётся) остаются зелёными.

### 3.5 Parity note

Серверный контракт `/api/config` не меняется.

---

## 4. Пункт 4 — DMs: сон/ностальгия/саммаризация OFF (T-1324…T-1328) ⚠️ DATA-CHANGE

### 4.1 Решения по открытым вопросам (ADR-1010-1)

- **Хранилище:** `chat_profiles.chat_params` JSONB. DMs = `chat_id > 0` (`is_dm_scope`, `services/chat_params.py:31-35`). Активные = `chat_profiles WHERE chat_id > 0 AND is_active = TRUE`.
- **Ключи (точный набор):**
  - runtime-килсвитчи (единственный per-chat гейт воркеров): `gates.dream = false`, `gates.nostalgia = false` — `services/feature_gates.py:36-41`, проверка в `dream_worker.py:401-402`, `nostalgia_worker.py:285-286`.
  - модульный уровень / UI-тумблеры (per_chat категории `memory`/`flags`): `overrides["memory.dream_enabled"] = false`, `overrides["memory.nostalgia_enabled"] = false`, `overrides["flags.summary_enabled"] = false`.
  - «Саммаризация» для ЛС: **модуль = `flags.summary_enabled`** (UI `mod_summary`, `web/app.js:326-360`); фактический runtime-гейт бегущего конспекта в ЛС = `flags.chat_running_summary_enabled`, который уже `DEFAULT-OFF` через `chat_summary_enabled` (`services/chat_params.py:397-412`). Дополнительно пишем `overrides["flags.chat_running_summary_enabled"] = false`, чтобы погасить возможные ранее включённые явные `true` (гарантия «OFF для ВСЕХ активных ЛС»).
  - `bot.py` direct-chat гейт (`flags.summary_enabled`, строки 315/613…646) **НЕ трогаем** (F-14).
- **Значения (если вдруг включены):** `True` → принудительно `false`; отсутствие ключа → тоже пишем `false` (детерминизм и идемпотентность).
- **Инвариант:** писать только через `set_chat_params` (транзакция + `chat_lore_history` + NOTIFY), **без PG-DDL**.

### 4.2 Скрипт (T-1326): `scripts/disable_dm_heavy_modules.py`

Поведение:
- Аргументы: по умолчанию **dry-run**; `--apply` — запись; `--chat-id <id>` (повторяемый) — подмножество (staged); `--snapshot-out <path>`; `--restore <path>`.
- Источник строк: `SELECT chat_id, chat_params, gates_opt_in FROM chat_profiles WHERE chat_id > 0 AND is_active = TRUE ORDER BY chat_id` (raw SQL через `pg.pool`; `chat_lore_store.list_profiles` DMs исключает — не использовать).
- Чтение JSONB напрямую (`chat_params._load_chat_params` / `json.loads`), т.к. `get_all_chat_params` в standalone-скрипте вернёт `{}` (кэш не сконфигурирован).
- Патч на чат: `patch_o = {k: False}` для ключей, где `cur_o.get(k) is not False`; аналогично `patch_g`. Пустой патч = no-op (идемпотентность).
- `--dry-run` (default): печать `[dry-run] chat=<id> overrides=[…] gates=[…]`, без записи; в конце — «планируется N изменений из M ЛС».
- `--apply`:
  1. **Snapshot ДО записи** (SELECT→JSON, только `overrides`/`gates`, без секретов; файл `var/dm_modules_off_snapshot_<UTC>.json`, best-effort 0o600). Ошибка snapshot → abort (exit 1), записи нет.
  2. Для каждого чата: `set_chat_params(chat_id, {"overrides": {**cur_o, **patch_o}, "gates": {**cur_g, **patch_g}, "meta": {**cur_meta, "note": "dm heavy modules off"}}, changed_by=None, pg=pg, history_field="chat_params")` (полные merged-словари — `set_chat_params` заменяет namespace целиком).
  3. Финальный отчёт: `changed=<n> noop=<m> total=<M>`.
- Повторный `--dry-run` после `--apply` → **0 изменений**.
- `--restore <snapshot>`: вернуть `overrides`/`gates` из снапшота тем же путём (идемпотентно).
- Только stdout, без секретов; `PgDatabase(dsn=os.getenv("POSTGRES_DSN"))`.

### 4.3 Дефолт для НОВЫХ ЛС (чтобы не регрессировало)

`services/chat_params.py:325-355` (`ensure_scope_profile`, ветка `dm=True`): вместо `_root_with_meta({})` вставлять v-1-лейаут с явными дефолтами:
- `gates = {"dream": False, "nostalgia": False}`
- `overrides = {"memory.dream_enabled": False, "memory.nostalgia_enabled": False, "flags.summary_enabled": False, "flags.chat_running_summary_enabled": False}`

Выносится в модульные константы (`_DM_DISABLED_GATES`, `_DM_DISABLED_OVERRIDES`) и переиспользуется скриптом (единый источник значений). INSERT — существующий `INSERT_SCOPE_PROFILE_SQL` (`ON CONFLICT DO NOTHING`), без DDL. Групповые дефолты (`ensure_gates_defaults`, handlers/chat_lifecycle.py) **не менять**.

### 4.4 Влияние на воркеры

- `dream_worker._tick`/`_process_chat` — per-chat гейт `gates.dream` теперь false → skip (даже при глобальном `memory.dream_enabled=true`).
- `nostalgia_worker` уже skip'ает `chat_id >= 0` + гейт `gates.nostalgia=false` (defense-in-depth).
- Бегущий конспект ЛС — `chat_summary_enabled` → false (дефолт + явный override).
- `bot.py` direct-chat не затронут.

### 4.5 Acceptance criteria

- Ни одна активная ЛС не имеет модулей ON (`gates.dream/nostalgia is not True`, overrides `False`).
- Новые ЛС получают OFF автоматически.
- Повторный data-прогон идемпотентен (0 изменений); новых PG-DDL нет; секреты не печатаются.

### 4.6 Тесты

- `tests/test_scripts_round1010_dm_off.py` (mock-pg, прецедент `test_scripts_backfill_feature_gates.py`): dry-run без записи; apply пишет merged overrides/gates и snapshot; повторный прогон — 0 изменений; `--chat-id` фильтрует.
- `tests/test_chat_params.py`: `ensure_scope_profile(dm=True)` кладёт DM-дефолты (gates dream/nostalgia=false, 4 override=false); групповой insert не изменён.
- Обновить/добавить маркеры `tests/test_webapp_dm_ui.py` (дефолты для новых ЛС; `bot.py` не тронут).

### 4.7 Feature flags / progressive delivery (ADR-1010-1)

1. snapshot → 2. `--dry-run` → 3. `--apply` на проде (@DevOps) → 4. повторный `--dry-run` = 0 → 5. выборочная проверка 2–3 ЛС.
Опционально staged: сначала `--chat-id` внутренних ЛС, затем остальные. Rollback: `--restore <snapshot>` из шага 1.

---

## 5. Пункт 5 — «Роли»: аватар+ник, ширины (T-1329…T-1332)

### 5.1 Источник имени/аватара глобальных админов (ADR-1010-2)

- `cache.admins_full()` (`services/config_cache.py:259-263`) отдаёт только `telegram_id/role_name/added_by/created_at` — ничего не менять в модели.
- **Backend:** новый helper `global_user_display_info(user_id)` в `web/api/avatars.py`:
  - имя: best-effort `bot.get_chat(user_id)` → `first_name`/`last_name` → `username` (Full Name предпочтительно; `@` снимается);
  - фото: существующий `_user_photo_cache` + `get_user_profile_photos(user_id, limit=1)`;
  - RAM-TTL 1ч через `_cache_get/_cache_put` (новый dict `_user_name_cache`); fail-open `{display_name: None, photo_file_id: None}`. Bot API недоступен / юзер не «знаком» боту → `None` (фронт покажет фолбэк-ID).
  - **chat_id не нужен** — метод работает глобально (в отличие от `user_display_info(chat_id, uid)`).
- **Endpoint:** `GET /api/admins` (`web/api/routes.py:705-712`) обогащает **копии** строк (`dict(row)`) полями `display_name`/`photo_file_id` через `asyncio.gather` + `Semaphore(5)` (админов мало); fail-open. Существующие поля сохраняются. R17: endpoint под `requires_permission("access")`, секретов не добавляет.
- **Frontend (`web/app.js:2940-2947`):** после `loadAdmins` для строк с `photo_file_id != null` вызвать `loadAvatar('user', admin.telegram_id, admin)` (blob через `/api/avatar/user/{id}`, без прямых `<img src>`, 401-safe). Плюс опционально для себя: `admin.telegram_id === me.telegram_id` → `me.first_name` если сервер вернул пусто.

### 5.2 Рендер списка (`web/index.html:1598-1605`)

- Строка: аватар (`<img v-if="admin.avatarUrl" :src="admin.avatarUrl" @error="avatarError(admin)">`) либо инициал-фолбэк; ник = `admin.display_name || admin.username` (если пусто — не рисуем, остаётся ID); **ID всегда мелким серым** (`text-[10px] text-gray-500 font-mono`); бейдж роли сохранить; кнопка «Удалить» — как есть.
- Инициал: helper `adminInitial(admin)` = первая графема `display_name`/`username`, иначе первый символ `String(telegram_id)` (без новых зависимостей).
- Fallback: имя неизвестно → виден только мелкий ID (требование владельца).

### 5.3 Ширины (`web/index.html:1608-1614`)

- ID-инпут: `class="field flex-1 min-w-0"`.
- Селектор ролей: `w-36` → `w-24` (уже).
- Кнопка «Назначить»: добавить `shrink-0`; проверить, что на узком экране не уезжает (Live QA). «Матрица ролей» (`#/access/roles`, `web/index.html:1623-1673`) **не трогать**.

### 5.4 Acceptance criteria

- Список «Роли» показывает аватар+ник, ID мелким серым рядом; при неизвестном имени — только ID; назначение/удаление работают.
- Селектор уже, ID-инпут шире; на mobile кнопка не уезжает.
- Новых ParamSpec/каталога нет; секреты не утекают.

### 5.5 Тесты

- Бэкенд-маркеры `tests/test_webapp_avatars_ui.py` (или `test_roles_admin.py`): `global_user_display_info`, `bot.get_chat(user_id)`, `get_user_profile_photos`, обогащение `/api/admins` (`display_name`).
- API-тест: `/api/admins` возвращает `display_name` (None без бота), старые поля (`added_by`/`created_at`) на месте (`tests/test_webapp_api.py::test_get_admins_full_cards` не ломать).
- Ψ-маркеры `tests/test_webapp_round1010_ui.py`: нет `> {{ admin.telegram_id }}</b>`; есть `admin.avatarUrl`, `text-[10px] text-gray-500`, `w-24`, `flex-1 min-w-0`.
- Сохранить `test_close_and_fullscreen_buttons` (ровно 4 `>✕</button>` — новых ✕ не добавлять).

### 5.6 Parity note

`admins_full()` и `bot_admins` не меняются; enrichment читающий, кэш 1ч.

---

## 6. Пункт 6 — Headroom stats: OUT OF SCOPE (решение)

- В репозиторий **не добавлять** ничего Headroom-связанного (ни endpoint, ни proxy, ни env, ни тест), ссылок на IDE/`headroom` в коде нет.
- T-1333 остаётся задачей @DevOps вне репо: получить статистику существующим инструментом и вывести владельцу plain-language, без сырых ключей (R17). Это не влияет на код/каталог/дефолты.
- Scanner не должен считать отсутствие изменений по п.6 находкой.

---

## 7. Решения по открытым вопросам tasks.md §7

1. **п.1:** только CSS `.fullscreen-mode header.header-sticky`, `max(env(...), var(--tg-content-safe-area-inset-*), var(--tg-safe-area-inset-*))`; `viewportStableHeight` не требуется.
2. **п.2:** RENDER-фикс (дорожки + временная сетка + динамическая высота + точка при 1 сэмпле); контракт `api_payload` **не меняется**.
3. **п.4:** «саммаризация» = `flags.summary_enabled` (модуль) + `flags.chat_running_summary_enabled` (runtime ЛС, дефолт-OFF); `gates` — только `dream`/`nostalgia`, остальное — `overrides`.
4. **п.5:** имя — `bot.get_chat(user_id)` best-effort (кэш 1ч), фото — `getUserProfilePhotos`; недоступность → фолбэк на ID. `initData` — только опционально для себя.
5. **п.6:** out of scope репозитория; внешний вызов у владельца/@DevOps.

---

## 8. Маппинг задач

| Задача | Что |
|---|---|
| T-1315 | §1 (контракт), T-1316 — CSS, T-1317 — Live |
| T-1318 | §2 (вердикт render), T-1319 — код+JS-юнит, T-1320 — Live |
| T-1321 | §3 (шаблон+`blockFieldValue`+сброс), T-1322 — тесты, T-1323 — Live |
| T-1324 | §4.1/4.4 (контракт ключей/дефолты), T-1325 — `ensure_scope_profile`, T-1326 — скрипт, T-1327 — DevOps run, T-1328 — верификация |
| T-1329 | §5.1/5.2 (контракт), T-1330 — backend+frontend, T-1331 — ширины, T-1332 — Live |
| T-1333 | §6 out of scope |
| T-1334 | Scanner R10.9-1/-3 (P2) |
| T-1335 | README/APP_VERSION/cache-bust (R10.8-5) |
| T-1336–T-1339 | прогон/commit/push/deploy/отчёт |

---

## 9. Открытые вопросы к владельцу (owner decisions)

1. **Глубина правок ЛС:** подтвердить, что `flags.chat_running_summary_enabled=false` пишем явно (гасит ранее включённые `true`), а не полагаемся только на DM-дефолт. Рекомендация @Architect — **писать**.
2. **Источник ника админов:** согласиться, что для админов, никогда не запускавших бота, имя недоступно (Bot API отдаст ошибку) → показываем только ID. Альтернатива (ручной alias-список) — вне скоупа.
3. **Хранение snapshot ЛС:** оставляем ли файл `var/dm_modules_off_snapshot_*.json` на сервере (нужен для `--restore`) — да/нет; срок хранения.
4. **Staged-охват ЛС:** сначала внутренние `--chat-id`, затем все — или сразу все (по умолчанию @Architect: сразу все, staged опционально).

---

## 10. Handoff

@Orchestrator Architecture phase complete, passing the baton.
Вызовы: @Builder (T-1316/T-1319/T-1321/T-1322/T-1325/T-1326/T-1330/T-1334/T-1335/T-1336),
@DevOps (T-1327/T-1333/T-1337/T-1338), @QA (T-1317/T-1320/T-1323/T-1328/T-1332, Live Android).
