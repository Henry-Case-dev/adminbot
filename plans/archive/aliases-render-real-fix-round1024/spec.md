# Spec: aliases-render-real-fix-round1024 (F10)

> Раунд 10.24 (UPD2 п.8) · P1 · UI/web (data-binding) + обязательная live-диагностика · Владелец: F10
> Ступень `web/**`: **6-я, последняя** (F3 → F5 → F6 → F11 → F4 → → **F10**)
> **ADR:** ADR-1024-11 (**RE-OPEN/AMEND** 10.22 F2 — прошлый отчёт «починили» признан **ложным**)
> **Сквозной слой:** `plans/features/round1024-web-architecture.md`

## 1. Цель

Реально починить рендер поля **«Словарь алиасов имён»** (`limits.summary_aliases`,
вкладка «ИИ» → «Имена»). При наличии данных в БД поле обязано отрисовать текущий
JSON-объект при загрузке страницы. **Обязательна живая диагностика в БД** (global vs
per-chat override) с доказательством — закрытие возможно только с фактическим
подтверждением (не «тест прошёл»).

## 2. Что уже есть (координаты)

| Что | Где |
|---|---|
| Каталог: `SUMMARY_ALIASES`, type `json`, group `limits_user_aliases`, **widget `keyvalue`** | `services/param_catalog.py:1262-1266` |
| Backend: `_ensure_keyvalue_object` (снятие двойного кодирования), сборка items, `global_value` | `web/api/routes.py:219-239, 380-383` |
| Frontend: KV-редактор `kv-editor`: `created(){sync()}`, `watch:{'item.value':…}`, `sync()` | `web/app.js:6812-6938` (`sync` `:6863-6886`) |
| Шаблон `#kv-editor-tpl` | `web/index.html:3304-3338`; вызов `<kv-editor :item :can-edit>` `:707-712` |
| `loadConfig` (заменяет `configItems`, snapshot, seed масок) | `web/app.js:4042-4100` |
| `summaryAliasesMap()` (резолв имён из того же item) | `web/app.js:5807-5813` |
| Прошлые «фиксы» 10.22 | `tests/js/round1022_aliases_test.js`, `tests/test_aliases_render_round1022.py` |

**Почему прошлый отчёт ложный (гипотеза с доказательствами):**
`tests/js/round1022_aliases_test.js` вызывал `kv.methods.sync.call(ctx)` **вручную**,
никогда не проверяя реальный **reactive mount**. В Vue 3 `props` — `shallowReactive`
(а не `reactive`); `watch: { 'item.value': … }` на prop-объекте **не является deep** и
может не срабатывать при замене `configItems`/вложенном обновлении. Плюс компонент
не перемонтируется (нет `:key`), поэтому `created`-`sync()` выполняется один раз со
значением, которое могло ещё не приехать. Это официально задокументированное
поведение (см. ADR-1024-11, ссылки: Vue docs «Watchers», vuejs/core#9965).

## 3. Требуемое поведение

### 3.1. Шаг 1 (обязателен ДО фикса): live-диагностика (read-only)

- Собрать факты (без записи, без restore из бэкапа — **запрещён**):
  1. **Global:** фактическое значение `limits.summary_aliases` в `bot_settings`
     (источник PG): форма (`dict`/`str`/`list`/`null`), число ключей, наличие двойного
     кодирования. Значения **обезличиваются** (R17) — только форма/количество.
  2. **Per-chat override:** есть ли override в `chat_params` для целевого чата,
     его форма/число ключей.
  3. **API-эффект:** что реально отдаёт `GET /api/config` для роли владельца для
     этого ключа: `value` (форма), `global_value`, `widget`, `chat_source`.
- Реализация: одноразовый read-only скрипт/CLI (`manage.py diag aliases …`) ИЛИ
  защищённый debug-вывод; НЕ мутация. Вывод включается в отчёт (обезличенно).
- **Ветвление:**
  - данные **есть** → переходим к §3.2 (это баг binding/рендера);
  - данные **пусты** (`{}`/`null`) → фикс = честный Empty State + (опционально) сид;
    «binding-баг» фиксируется как **отсутствие данных**, с доказательством.
- Предыдущий вывод 10.22 «данные есть» считается **неподтверждённым** до этого шага.

### 3.2. Шаг 2: реальный data-binding fix

- **Реактивность:** заменить хрупкий `watch: { 'item.value': … }` на надёжный:
  `watch: { item: { handler(){ this.sync(); }, deep: true, immediate: true } }`
  (или геттер `() => props.item && props.item.value` c `deep: true, immediate: true`).
  `created()` — оставить как «первый проход».
- **Перемонтирование:** на вызове компонента добавить `:key`, зависящий от версии
  значения, чтобы reload гарантированно пере-инициализировал пары:
  `:key="item.key + ':' + configVersion"` (где `configVersion` инкрементится в
  `loadConfig`) либо `:key="item.key + ':' + _serializeValue(item.value)"`.
- **Нормализация:** `sync()` уже умеет object/JSON-строку (до 2 уровней)/плохие формы.
  Добавить обработку массива пар `[[k,v],…]` (если backend когда-либо отдаст) и
  сохранить безопасный fallback (0 пар → понятный Empty State, не «сломанный» вид).
- **Источник/эффективное значение:** показывать **эффективное** значение (chat
  override, если есть, иначе global) и индикатор источника: «значение чата» /
  «глобально» (через `item.chat_source` и `item.global_value`).
- **Кеш:** cache-bust остаётся (`?v=APP_VERSION`, `no-store`) — stale JS больше не
  может маскировать фикс (проверено 10.22, сохраняем инвариант).

### 3.3. Шаг 3: доказательство приёмки

- **Render-тест** (обязателен, в отличие от 10.22): реально смонтировать/отрендерить
  `kv-editor` с `item.value = {"138811255":"Леха"}` и убедиться, что в DOM появились
  input-ы со значениями (а не «Пар пока нет»).
- **Живая приёмка в TMA** (cache-bust) на данных прод-БД: поле показывает текущий
  JSON сразу при загрузке. Скриншот/факт в отчёте (обезличенно).
- Закрытие F10 допускается **только** при наличии §3.1-фактов **и** §3.3-доказательства.

## 4. Изменения по файлам

| Файл | Что |
|---|---|
| `web/app.js` | KV-редактор: `watch` через `item` (deep+immediate); `sync` — массив пар; `loadConfig` — `configVersion`; `:key` на вызове; индикатор источника; `uiFlag`. |
| `web/index.html` | `#kv-editor-tpl`: явный Empty State; бейдж источника («значение чата»/«глобально»); `:key` на `<kv-editor>`. |
| `web/api/routes.py` | (если диагностика в API) read-only поля формы значения; НЕ менять контракт значений. |
| `manage.py` (опц.) | read-only команда диагностики алиасов. |
| `tests/**` | §6. |
| `config/settings.py` + `routes.me` | `ALIASES_KEYSVALUE_RENDER_ENABLED` (enabler). |

## 5. Контракты

- Значение `limits.summary_aliases` наружу — **объект** (`_ensure_keyvalue_object`),
  `widget='keyvalue'`, `chat_source`, `global_value` — как есть.
- KV-редактор инициализируется **и** при монтировании, **и** при любом изменении
  `item`/`item.value` (deep+immediate).
- При наличии данных поле **никогда** не пустует.
- Диагностика — read-only; restore из бэкапа **запрещён** (перезапишет свежие данные).
- R17: в отчёт — только форма/количество, без значений имён/ID; в логи — без значений.

## 6. Тесты

- **JS render-тест (главный, `tests/js/round1024_aliases_render_test.js`):**
  - компонент с `item.value = {"1":"Иван"}` → в отрисованном состоянии `pairs.length===1`
    и `id/name` заполнены;
  - смена `item.value` после монтирования → повторный sync (эмуляция reload);
  - замена `item` (новый объект) → sync срабатывает (регресс shallowReactive-бага);
  - не-объект/пусто → Empty State, без исключений;
  - массив пар `[[k,v]]` → пары (если поддержан);
  - `node --check web/app.js`.
- **Python (расширить `tests/test_aliases_render_round1022.py`):**
  - `_ensure_keyvalue_object`: object/JSON/double-encoded/list/none (как есть);
  - `GET /api/config` для владельца отдаёт `widget='keyvalue'` и `value`-объект
    (фикстура PG/SQLite);
  - формат `global_value` — объект;
  - `manage.py diag` (если реализован) — read-only, без UPDATE/DELETE (SQL-трасса).
- **Cache-bust (сохранить):** `?v=APP_VERSION`, `no-store`.
- **Гейт:** `tests/js/vue_mount_test.js` зелёный.

## 7. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | Повторный ложный отчёт | High | §3.1 факты + §3.3 live-доказательство = критерий закрытия; render-тест |
| R2 | per-chat override маскирует global | Medium | §3.2 эффективное значение + индикатор источника |
| R3 | stale JS-кэш TMA | Medium | cache-bust сохраняется (10.22-инвариант) |
| R4 | Значения имён/ID утекут в отчёт | Medium | R17: только форма/количество, обезличенно |
| R5 | `watcher` deep на большом объекте дорогой | Low | объект алиасов мал (`maxPairs 200`), приемлемо |
| R6 | Restore из бэкапа «на всякий случай» | High | запрещён явно (spec §5, ADR) |

## 8. Критерии приёмки

- §3.1-диагностика выполнена, факты (global + override + API-форма) приложены.
- При наличии данных поле рендерит текущий JSON **сразу** при загрузке (render-тест +
  живая TMA-приёмка).
- Если данных нет — это доказано фактически, и поле показывает понятный Empty State
  (не «сломано»).
- Данные не перезаписываются/не восстанавливаются из бэкапа.
- Δ DDL = 0, Δ каталога = 0; JS-гейт зелёный.

## 9. Флаг и откат

- `ALIASES_KEYSVALUE_RENDER_ENABLED` (env-only `ClassVar`, **default ON**) через
  `ui_flags`; OFF → прежний (сломанный) watcher (только для аварийного сопоставления).
- Откат: флаг OFF / `git revert`. Миграций нет.
