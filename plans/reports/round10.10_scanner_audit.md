# Round 10.10 Scanner Audit (admin-ui-round1010: fullscreen-padding, mobile key-chart, provider values, DM heavy-modules OFF, Roles avatar/nick/widths)

> Аудит 2026-09-12 (Step 6). HEAD `da85b60` (10.9 docs) + рабочее дерево 10.10.
> `git status -s`: **10 modified + 4 untracked** (`scripts/disable_dm_heavy_modules.py`,
> `tests/test_scripts_round1010_dm_off.py`, `tests/test_webapp_round1010_ui.py`,
> `plans/features/admin-ui-round1010/`).
> `git diff --stat`: **+555/−55** по 10 путям.
> Изменённые исходники: `services/chat_params.py`, `web/{app.js,index.html}`,
> `web/api/{avatars,routes}.py` + 5 тест-файлов + `plans/backlog.md`.
>
> **pytest: 5140 passed, 1 skipped, 0 failed** (59.59s; база 10.9 = 5105).
> **`node --check web/app.js` — clean.** **`node tests/js/routing_test.js` — `JS-UNIT-OK`.**
> **`git diff --check` — чист (только LF/CRLF-warnings).**
> Проверены диффы всех изменённых файлов, независимый расчёт инвариантов,
> ревизия DM-скрипта (идемпотентность/под-набор/snapshot), enrichment `/api/admins`
> (fail-open/XSS), окно графика, RBAC/DM, поиск секретов/PG-DDL/Headroom.
> П.6 (Headroom) — OUT OF SCOPE репозитория, отсутствие изменений находкой не считается.

## 1. Инварианты — независимая проверка

| Инвариант | Проверка | Вердикт |
|---|---|---|
| Каталог **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88 / TAB_RULES 19 / CONFIG_TAB_TITLES 19** | Независимо: `len(REGISTRY)==400`, `len(GROUPS)==90`; `_TAB_BY_GROUP==88`, `TAB_RULES==19`, `fields(Settings)==372` (тест `test_webapp_round1010_ui.py:166-175` зелёный) | ✅ |
| **Ноль новых PG-DDL** | `git diff` не содержит `services/database.py`/`services/pg_db.py`; `git diff -G "CREATE TABLE\|ALTER TABLE\|ADD COLUMN\|DROP TABLE\|CREATE INDEX"` — пусто; п.4 — только DML JSONB | ✅ |
| **SQLite v8** | `_SCHEMA_VERSION_AGI_MEMORY == 8`; `services/database.py` не менялся | ✅ |
| **`bot.py` router order не тронут** | нет в `git diff`/`git status`; тест `test_bot_router_gate_not_touched` зелёный | ✅ |
| **`media/` не тронут** | нет в диффе/`git status` | ✅ |
| **`.env` не тронут** | нет в диффе | ✅ |
| **Нет секретов** | grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` — пусто; Snapshot DM-скрипта пишет только `overrides/gates` | ✅ |
| **Нет Headroom-ссылок в коде** | repo-wide grep (кроме `.venv`/`plans`): нет; в `web/`/`services/`/`scripts/`/тестах — 0 | ✅ |
| **Существующие пин-тесты не ослаблены** | полный pytest 5140/0 + маркеры 10.7/10.8/10.9 зелёные | ✅ |

## 2. Верификация пунктов раунда

| # | Пункт | Проверка | Вердикт |
|---|---|---|---|
| 1 | Fullscreen header padding | `.fullscreen-mode header.header-sticky` (специфичность `(0,2,1)` > базовой `(0,1,1)`/Tailwind `px-4 py-3`); `padding-{top,right,left}: calc(base + max(env(safe-area-inset-*,0px), var(--tg-content-safe-area-inset-*), var(--tg-safe-area-inset-*)))`; `max()` с `var(...,0px)`-фолбэком — при отсутствии TG-переменных/старом WebView поведение не хуже базового; 10.7 (ширина) и 10.9 (`.fullscreen-mode .scroll-area`) не тронуты; `padding-bottom` не задаётся — `.py-3` сохраняется | ✅ |
| 2 | Mobile key-history chart | Чистая `keyHistoryChartModel`; дорожки `lane+0.75/0.25`, `y.max = laneCount+0.2` — слияние исключено; временная сетка `SAMPLE_BUCKET=300` == `key_history.SAMPLE_BUCKET_SECONDS`, минимум `MIN_BUCKETS=12`; окно строится ОТ КОНЦА (`minStart`, cap ≤ `MAX_HISTORY_POINTS`, никаких `break`/`slice`), новейший сэмпл всегда последний; пропуск = `null` + `spanGaps:false`; `pointRadius:3` при ≤1 сэмпле; `height=max(120,44+lanes*22)` + `maintainAspectRatio:false` + `$nextTick`; контракт `/api/status/key-history` (`api_payload`) не изменён; пустое состояние (`providers==[]`) сохранено | ✅ |
| 3 | «Провайдеры»: реальные значения | `:value="blockFieldValue(f)"` + `@input` вместо `v-model`; `blockFieldValue` возвращает `''` для пустого черновика (не откат) и значение `configItems` при отсутствии черновика; секреты (`type==='object'`) → `''` (placeholder-маска); `blockDrafts`/`blockResults` сброшены в `loadConfig` (success) и `setActiveChat`; `saveBlock`/MINOR-3 (`null`=не трогать, `''`=очистить) не менялись | ✅ |
| 4 | DM heavy modules OFF | Новые ЛС: `ensure_scope_profile(dm=True)` кладёт `gates.dream/nostalgia=false` + 4 override=false (единые `_DM_DISABLED_*`); существующие: скрипт dry-run/`--apply`/`--chat-id`/`--snapshot-out`/`--restore`, запись только через `set_chat_params` (merged namespaces), snapshot ДО записи с abort, пустой патч = no-op (идемпотентность), `--restore` не трогает `meta` (MEDIUM-2), частичный сбой/META/LOW → exit 1; групповой путь и `bot.py` не тронуты | ✅ |
| 5 | «Роли»: аватар+ник+ID, ширины | Backend `global_user_display_info` (RAM-TTL 1ч, `get_chat(user_id)`→first/last→username, фото через `_user_photo_cache`+`getUserProfilePhotos`), транзиентные `TelegramRetryAfter/TelegramNetworkError` НЕ негатив-кэшируются; `/api/admins` обогащает **копии** (`dict(a)`) под `requires_permission("access")`, `Semaphore(5)`+`gather`, fail-open; фронт — `admin.avatarUrl` (blob через прокси, `@error`), `adminInitial`, `display_name||username`, ID `text-[10px] text-gray-500 font-mono`; `w-36→w-24`, ID-инпут `flex-1 min-w-0`, кнопка `shrink-0`; `>✕</button>` == 4 | ✅ |

## 3. Находки раунда 10.10

Critical/High/Medium — **нет**. Ниже Low/Info (не блокируют мерж).

### [R10.10-1] severity: low — скрипт DM: отчёт `noop/total` и dry-run-count игнорируют `--chat-id`
**Файл**: `scripts/disable_dm_heavy_modules.py:217-238` (`total = len(rows)`,
`noop = total - len(plan)`; dry-run `:225` `планируется N изменений из {total} ЛС`).
**Суть**: `total` — все активные ЛС, а `plan` уже отфильтрован `--chat-id`.
При staged-прогоне `--chat-id 5` строки «из 100 ЛС» и `noop=99` вводят в заблуждение:
99 чатов не рассматривались, а не «уже выключены». На данные не влияет, только
операторский вывод/риск неверного прочтения staged-охвата.
**Ремендация**: считать `total = len(rows)` только при пустом `chat_ids`, иначе
`total = len([r for r in rows if id in wanted])`.

### [R10.10-2] severity: low — скрипт DM: `meta.note` перезаписывается и не откатывается snapshot'ом
**Файл**: `scripts/disable_dm_heavy_modules.py:139-140` (apply пишет
`meta.note = "dm heavy modules off"`), `build_snapshot:87-101` (снапшот только
`overrides`/`gates`), `restore_from_snapshot:156-182` (по MEDIUM-2 `meta` не передаёт).
**Суть**: предыдущее значение `meta.note` безвозвратно теряется при `--apply`, а
`--restore` его не восстанавливает (снапшот его не содержит). Изменение метаданных,
не влияющее на поведение; но rollback «как было» неточен.
**Ремендация**: добавить `meta` в snapshot (или записывать note отдельным ключом,
не затирая прежний). Осознанно допустимо, если @DevOps согласен.

### [R10.10-3] severity: low — `renderKeyHistoryChart`: ранний return при `keyHistory==null` не уничтожает старый Chart
**Файл**: `web/app.js:3541-3548`.
**Суть**: при неудачном `loadKeyHistory` (`keyHistory=null`, `:3442`) вызов
`renderKeyHistoryChart` выходит по `if (!this.keyHistory) return;`, НЕ вызывая
`this.keyHistoryChart.destroy()`. Остаётся Chart.js-инстанс со ссылкой на
отсоединённый canvas; очищается лишь при следующем успешном рендере (`:3545-3547`).
Кратковременная утечка/стейл-инстанс при сетевых сбоях. Функционального сбоя нет
(пустое состояние рендерится по `v-if`).
**Ремендация**: перед `return` уничтожать существующий чарт.

### [R10.10-4] severity: info — `loadAdmins`: аватары без `avatarSkipped`/`.catch`, повторные blob-запросы
**Файл**: `web/app.js:2965-2974`.
**Суть**: в отличие от `loadRelationAvatarsLazy` (`avatarSkipped` на негатив),
`loadAdmins` на каждый вызов заново шлёт `loadAvatar` для всех `photo_file_id != null`
без флага «больше не пробовать»; `loadAvatar` не обёрнут `.catch` (паттерн
промисов без обработки reject — как в существующем коде). При редком 404/сбое blob
повторные открытия окна «Роли» повторяют запросы.
**Impact**: минимальный (админов мало; серверный негатив-кэш 1ч). Инфо для трассируемости.

### [R10.10-5] severity: info — `adminInitial` дублирует `avatarInitial`; ветка `admin.username` недостижима
**Файл**: `web/app.js:2977+` (`adminInitial`), `:4098` (`avatarInitial`).
**Суть**: новая функция повторяет логику `Array.from(name)[0].toUpperCase()`;
`admin.username` в API-модели не приходит (`global_user_display_info` сворачивает
username в `display_name`), поэтому `admin.display_name || admin.username` —
фактически только `display_name` (фолбэк-ID остаётся рабочим). Стилевой дубль, не баг.

## 4. Проверенные области — вердикты (логических дыр не найдено)

1. **XSS «Роли»**: `display_name`/`username` рендерятся через `{{ }}` (Vue-экранирование),
   `adminInitial` — текст/`?`, `:src="admin.avatarUrl"` — blob-URL из прокси
   (`avatarUrl()` c `X-Telegram-Init-Data`, вне Telegram → `null`), не сырой `<img src>`
   по внешнему URL. Инъекция невозможна.
2. **Fail-open enrichment**: `global_user_display_info` ловит `get_chat`/photos:
   транзиентные ветки (`TelegramRetryAfter`/`TelegramNetworkError`) логируют и НЕ
   кэшируют негатив; прочие `Exception` → негатив-кэш; `bot is None` → `{None,None}`;
   `web_runtime.get_web_bot()` — простая функция без исключений. `/api/admins`
   сохраняет `requires_permission("access")` и не отдаёт секретов.
3. **Идемпотентность DM-скрипта**: `build_dm_patch` патчит только `is not False`;
   повторный dry-run после apply = 0; snapshot пишется до записи, ошибка → exit 1 без
   записи; `--restore` возвращает только `overrides`/`gates`, `set_chat_params`
   сохраняет прочие namespace (`keys`/`perm_overrides`) и `meta` (проверено по
   `services/chat_params.py:279-291`); exit-коды при частичном сбое (apply/restore) = 1.
4. **DM-дефолты новых ЛС**: `_DM_DISABLED_*` == spec §4.3 (dream/nostalgia + 4 override);
   `INSERT_SCOPE_PROFILE_SQL` c `ON CONFLICT DO NOTHING` — ноль DDL, повтор = no-op;
   групповой `INSERT_DEFAULT_PROFILE` не изменён.
5. **Окно графика (edge-cases)**: окно никогда не длиннее `MAX_HISTORY_POINTS` (287 шагов
   от `minStart`), `MIN_BUCKETS` расширяет окно только влево и не выходит за `minStart`;
   при 1–2 сэмплах — точка `r=3`; при пустом входе/без сэмплов → `null`; `y.max` покрывает
   верхнюю дорожку; бакеты данных и сетки используют один `floor(ts/300)*300`.
6. **RBAC/DM не ослаблены**: `/api/admins` — тот же `requires_permission("access")`;
   DM-скоуп затрагивает только `chat_id>0`; `bot.py` direct-chat гейт не тронут;
   `chat_summary_enabled` для ЛС по-прежнему `get_chat_param_defaulted(...)`.
7. **Отсутствие функциональной потери**: `saveBlock`/`testBlock`/`testField` продолжают
   использовать `blockFieldValue` (реальные значения); MINOR-3-семантика `null`/`''`
   сохранена; серверные контракты `/api/config`, `/api/status/key-history`, `/api/admins`
   (старые поля `role_name/added_by/created_at` на месте) не сломаны.
8. **Тест-качество**: функциональные тесты `TestGlobalUserDisplayInfoFunctional1010`
   реально проверяют кэш/транзиентность; `test_scripts_round1010_dm_off.py` покрывает
   dry-run/apply/snapshot/idempotency/restore/partial-failure; JS-юниты — дорожки,
   окно > `MAX_HISTORY_POINTS`, `blockFieldValue`, `adminInitial`. Маркеры — статические
   grep (как в 10.9), но подкреплены функциональными.

## 5. Итог 10.10

- **Блокеров: 0. Critical: 0. High: 0. Medium: 0.** Low: **3** (R10.10-1/-2 скрипт,
  R10.10-3 chart-return), Info: **2** (R10.10-4/-5 фронт).
- Для мержа **не обязательны**; R10.10-1 (операторский вывод staged) и R10.10-2
  (rollback `meta`) — точечные ремедиации перед прод-`--apply` (T-1327), рекомендуются.
- Инварианты соблюдены: **400 / 90 / 372 / mapped 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19;
  **ноль PG-DDL**; SQLite **v8**; `bot.py` не тронут; `media/`/`.env` не тронуты;
  секреты не коммитятся; **Headroom-ссылок в коде нет** (п.6 out of scope).
- pytest **5140 passed / 1 skipped / 0 failed** (59.59s);
  `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean.

*Round 10.10 report generated by Scanner on 2026-09-12*
