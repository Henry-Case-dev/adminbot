# Раунд 10.10 — admin-ui-round1010 (admin UI bugfix + DM-модули OFF + Headroom stats)

> **✅ СТАТУС: ЗАВЕРШЕНО И ЗААРХИВИРОВАНО (12.09.2026, @PM Step 8 Archive Phase).**
> Фича перенесена из `plans/features/admin-ui-round1010/` в
> **`plans/archive/admin-ui-round1010/`** (плоский kebab-case, как существующие архивы).
> **Итог:** полный pytest — **5144 passed / 1 skipped / 0 failed** (база 10.9 = 5105 → **+39**);
> @Reviewer — **APPROVED WITH MINOR ISSUES** (follow-ups закрыты); @Scanner — **CLEAN: low/info**
> (большинство находок устранено) (`plans/reports/round10.10_scanner_audit.md`); @Architect —
> архитектура влита в `plans/ARCHITECTURE.md` (**§31** + связанные разделы).
> **Каталог-инвариант:** REGISTRY **400** / GROUPS **90** / Settings **372** (mapped 88).
> Артефакты сохранены: `spec.md`, `ADR-1010-1.md`, `ADR-1010-2.md`, `ADR-1010-3.md`, `tasks.md`.
> **⚠️ ОТКРЫТО (PROD data-run, за @DevOps):** **T-1327** — применить DM-скрипт на сервере
> (`python scripts/disable_dm_heavy_modules.py --dry-run` → `--apply` → повторный `--dry-run` = 0
> изменений; снапшот до apply), затем **T-1328** (верификация: ни одна активная ЛС не имеет
> модулей ON); **T-1333** (Headroom stats через серверный прокси) и пост-архивные
> **T-1337/T-1338** (русский commit / push / deploy, health 200).
> **⚠️ ОТКРЫТО (live Android/Telegram QA, за владельцем/QA):** **T-1317** (fullscreen header),
> **T-1320** (mobile key-availability chart), **T-1323** (провайдеры: реальные значения полей),
> **T-1332** (роли: аватар+ник, ширины) — реальное устройство/Telegram в среде @Builder недоступно,
> статически покрыто (`tests/test_webapp_round1010_ui.py`, JS-юниты).
> **ВНИМАНИЕ:** статусы `[ ]` ниже — снимок на момент архивации; пост-архивная фаза @DevOps
> (T-1327/T-1328/T-1333/T-1337/T-1338) выполняется ПОСЛЕ архивации.

> **Фича:** `plans/archive/admin-ui-round1010/` (kebab: `admin-ui-round1010`; создана @PM 12.09.2026, Step 1; перенесена @PM Step 8 12.09.2026).
> **Нумерация:** **T-1315…T-1360** (продолжает **T-1314** — финал раунда 10.9).
> **Преемник:** 10.9 `admin-ui-round109` (архив; commit `d2d1215`, прод-деплой 12.09.2026, health 200).
> **Дата планирования:** 12.09.2026 (@PM, Step 1). **Дата архивации:** 12.09.2026 (@PM Step 8). **Статус:** ✅ РЕАЛИЗАЦИЯ ЗАВЕРШЕНА; фича заархивирована 12.09.2026.
> **Дословный запрос владельца (пункты 1–6 + финал)** — §1.
> **@PM не пишет код.** Передача: @Architect (контракты п.1/п.2/п.4/п.5) → @Builder (реализация п.1–п.5) →
> @DevOps (п.4 data-run на проде, п.6 stats-fetch, commit/push/deploy) → @QA (live Android).

---

## 0. Базовая линия и инварианты (не ломать)

- **pytest baseline: 5105 passed / 0 failed** (10.9). Регрессий быть не должно; цель 10.10 — **≥ 5105 + новые**.
- `node --check web/app.js` — clean.
- `node tests/js/routing_test.js` — `JS-UNIT-OK`.
- `git diff --check` — чист (только LF/CRLF-предупреждения допустимы).
- Каталог-инвариант: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88**, `TAB_RULES` 19, `CONFIG_TAB_TITLES` 19.
  Пункты 1–6 **не требуют новых ParamSpec/GroupSpec**; если по итогам @Architect всё же потребуется — числа меняются синхронно с тестами-пинами и осознанно.
- **Ноль новых PG-DDL** (`CREATE/ALTER/ADD COLUMN`) — п.4 (data-change) обязан уложиться в существующую таблицу `chat_profiles`.
- `bot.py` router order — **не трогать**. `media/` — **не трогать**. `.env` — **не трогать**.
- Секреты не коммитить (R17); реальные ключи — только на сервере. `chat_params.overrides`/`gates` — не секреты, но вывод статистики Headroom (п.6) не должен печатать сырые ключи.
- UI-only + data-change + read-only stats. Существующие гейты (`feature_gates`) и RBAC не ослаблять.

---

## 1. Дословный запрос владельца (capture exactly)

1. **Header padding в FULLSCREEN:** блок профиля (аватар + ник + роль + кнопка fullscreen) не должен перекрываться нативными кнопками Telegram.
2. **Mobile:** график доступности ключей рендерится некорректно (одна плоская полоса) — починить.
3. **Подраздел «Провайдеры»:** поля **Название** (display name), **Адрес** (base_url), **Модель** (model), **Ключ** (api key) должны показывать свои РЕАЛЬНЫЕ текущие значения; сейчас выглядят пустыми. **Поле «Ключ» уже показывает текущий ключ — оставить как есть.**
4. **ЛС (личные сообщения):** модули **сон, ностальгия, саммаризация** должны быть **ВЫКЛЮЧЕНЫ по умолчанию**; выключить их для **ВСЕХ текущих активных ЛС** (изменение данных существующих чатов).
5. **Подраздел «Роли»:** список ролей должен показывать **аватар + ник** вместо голого ID (ID — рядом, мелким серым шрифтом); **уменьшить ширину селектора ролей**; **расширить поле ввода ID**.
6. **Headroom stats:** получить и вывести текущую статистику сэкономленных токенов (MCP-инструмент `headroom_stats`; забрать через серверный прокси).
- **Плюс:** README (ироничный тон), русский коммит, push, деплой, plain-language отчёт.

**Подтверждение раунда:** **раунд 10.10** — подтверждён (предыдущий задеплоенный — 10.9, commit `d2d1215`).

---

## 2. Рекогносцировка (@PM, HEAD `da85b60`, дерево чистое)

### 2.1 п.1 — Header/fullscreen + блок профиля
- Шапка: `web/index.html:628-722` (`<header class="main-header header-sticky … px-4 py-3 flex items-center gap-2 flex-wrap">`).
- Блок профиля (avatar+nick+role+⛶): `web/index.html:694-709` (`<div class="ml-auto flex items-center gap-1.5 text-xs">`; аватар `:698`, ник `:701`, бейдж роли `:702`, кнопка ⛶ `:706-708`).
- CSS-модель fullscreen: `web/index.html:594-612` (`.app-shell`, `.scroll-area`, `.fullscreen-mode { height:100dvh; overflow:hidden }`).
- Текущий safe-area только по ширине: `web/index.html:588-591` (`padding-right/left: calc(1rem + env(safe-area-inset-*))`); по верху — лишь `@media (max-width:768px) header.header-sticky { padding-top: calc(0.75rem + env(safe-area-inset-top)) }` `web/index.html:616-620`.
- JS-тоггл: `web/app.js:717` (`isFullscreen:false`), `:2344-2358` (`toggleFullscreen`, оптимистичный локальный флаг, `Telegram.WebApp.requestFullscreen/exitFullscreen`).
- **Гипотеза root cause (для @Architect):** в режиме fullscreen Telegram нативные кнопки (Свернуть/Ещё/Закрыть) лежат поверх верхней полосы webview; `env(safe-area-inset-top)` внутри TMA-fullscreen часто = 0, поэтому профильный `ml-auto`-блок уходит под нативные кнопки. Нужен верхний отступ именно в `.fullscreen-mode` (не только `max-width:768px`), согласованный с `Telegram.WebApp.viewportStableHeight`/`isFullscreen`.

### 2.2 п.2 — Mobile-график доступности ключей («одна плоская полоса»)
- Рендер: `web/app.js:3425-3481` (`renderKeyHistoryChart`; union `ts` всех провайдеров `:3431-3437`; datasets `stepped:true, tension:0, pointRadius:0, spanGaps:false` `:3445-3461`; `legend bottom` `:3473-3475`).
- Вызов: `loadKeyHistory` `web/app.js:3400-3407`; данные `GET /api/status/key-history` `web/api/routes.py:1090-1102` → `services/status_service.py key_history.api_payload()`.
- Данные: `services/key_history.py` — ring по 5-мин слотам (`SAMPLE_BUCKET_SECONDS`, `record` `:126-149`), allowlist `ts/ok/http_status` (`:38`, `:55-68`), payload `_file_payload` `:179-194`, `api_payload` `:196-203`; `MAX_HISTORY_POINTS=288` (`web/app.js:194`).
- Разметка/высота: `web/index.html:2552-2588` (карточка `.keys-avail`; `<canvas ref="keyHistoryCanvas" height="80">` `:2585`).
- **Гипотезы root cause (для @Architect):** (а) данные — на мобильном в ring мало слотов / все провайдеры в одном слоте → одна ступенька `y=1` сливается в полосу; (б) рендер — фикс `height="80"` + `responsive:true` + много overlapping stepped-линий + легенда внизу дают «плоскую полосу»; (в) union-ось `ts` + `spanGaps:false` ломает разделение строк. Нужно разделить: **данные vs отрисовка**.

### 2.3 п.3 — «Провайдеры»: поля выглядят пустыми (ROOT CAUSE найден)
- Форма: `web/index.html:776-818` (блоки `providerBlocks`; `v-model="blockDrafts[f.key]"` `:788`).
- Определение блоков/полей: `web/app.js:366-438` (`PROVIDER_BLOCKS`: `models.*_display_name`, `models.*_base_url`, `models.*_model_name`/`*_transcribe_model`/`video_primary_model`, `keys.*_api_key`).
- **Root cause:** `blockDrafts` инициализируется пустым `{}` (`web/app.js:643`) и **нигде не наполняется** из `configItems` — `blockDrafts` встречается только в `:643` (data), `:2037` (`blockFieldValue`, только для test/save), `:2115` (`saveBlock`). При этом `v-model` привязан именно к `blockDrafts[f.key]`, а не к `blockFieldValue(f)` → инпуты пустые.
- `blockFieldValue` `web/app.js:2036-2043` (уже умеет падать на `configItems`), `blockFieldPlaceholder` `:2044-2050` (для секретов отдаёт `configured ••••last4`). Поэтому **поле «Ключ» и так показывает текущее (placeholder/маска)** — его не менять (п.3).
- **Фикс (для @Builder):** наполнять `blockDrafts[f.key]` реальными значениями из `configItems` при загрузке конфига (`loadConfig`) и при смене scope, для не-секретных полей (display_name/base_url/model); секретные (`keys.*`) оставить пустыми (маска как сейчас). Не ломать логику «`draft == null` = не трогать» в `saveBlock` `:2119-2122`.

### 2.4 п.4 — DM-модули (сон/ностальгия/саммаризация): хранилище и безопасный флип
- **Хранилище (PG, без DDL):** `chat_profiles.chat_params` JSONB (v-1-лейаут) — `services/chat_params.py:1-9`, типы/колонки `:41-43`, SQL `:60-85`; схема `services/pg_db.py:76-83` (`chat_id`, `auto_enabled`, `is_active`, `chat_params`, `gates_opt_in`).
- **Ключи per-chat overrides:** `chat_params.overrides` (резолв `web/api/routes.py:296-306`; запись `POST /api/config` → `set_chat_params` `routes.py:366-460`).
- **Ключи гейтов:** `chat_params.gates` (`dream`/`nostalgia`/`lore_auto`/`permsoc`) — `services/feature_gates.py:1-48,92-116`; единственная точка записи `set_feature_gate`.
- **Идентификация ЛС:** `services/chat_params.py:31-35 is_dm_scope(chat_id)` = `chat_id > 0` (группы — отрицательные). Активные: `chat_profiles WHERE chat_id > 0 AND is_active = TRUE`.
- **Модуль→ключ (UI `MODULES` `web/app.js:326-360`):**
  - **Сон** → `memory.dream_enabled` (`app.js:356`); гейт `dream` (`feature_gates.py:37`); глобальный рубильник воркера `memory.dream_enabled` (`services/dream_worker.py:6,211`), per-chat гейт проверяется в тике (`dream_worker.py:401-402`).
  - **Ностальгия** → `memory.nostalgia_enabled` (`app.js:359`); гейт `nostalgia` (`feature_gates.py:38`); воркер работает только по группам `chat_id<0` (`services/nostalgia_worker.py:14,269`) + per-chat гейт (`:285-286`).
  - **Саммаризация** → `flags.summary_enabled` (`param_catalog.py:593`, `settings.SUMMARY_ENABLED=True` `config/settings.py:388`); «бегущий конспект» — отдельный `flags.chat_running_summary_enabled`, уже DM-default OFF через `chat_summary_enabled` (`chat_params.py:397-412`). **@Architect обязан подтвердить, какой именно ключ считать «модулем саммаризации» для ЛС.**
- **Безопасный флип (для @Architect/@Builder/@DevOps):** идемпотентный скрипт `scripts/*.py` (прецеденты `scripts/backfill_feature_gates.py`, `backfill_permsoc_gates.py`) с `--dry-run` (по умолчанию) и `--apply`; писать через `chat_params.set_chat_params` (транзакция + `chat_lore_history` + NOTIFY, `pg_db.py`/`chat_params.py:60-85`) либо документированный SQL-JSONB-апдейт; **без новой схемы**. Перед apply — снапшот затронутых строк (SELECT→JSON) для rollback. Идемпотентность: повторный прогон = no-op.
- **Верификация:** после apply — `SELECT` по `chat_id>0 AND is_active`, проверить, что `overrides[key]=false` и `gates.dream=false`/`gates.nostalgia=false`; повторный прогон `--dry-run` показывает 0 изменений.

### 2.5 п.5 — «Роли»: список, аватары, ширины
- Окно «Роли» `#/access/admins`: `web/index.html:1579-1621`; список `admins` `:1598-1605` (сейчас `<b class="font-mono">{{ admin.telegram_id }}</b>` `:1601` + бейдж роли `:1602`).
- Форма добавления: `web/index.html:1608-1614` — поля `input.field.flex-1` (ID) `:1609`, `select.field.w-36` (роль) `:1610`, кнопка `:1613`. **Здесь:** уменьшить ширину селектора (`w-36` → уже), расширить ID-инпут.
- Данные: `loadAdmins` `web/app.js:2940-2946` → `GET /api/admins` `web/api/routes.py:705-712` (`cache.admins_full()`), модель админа `services/config_cache.py:256-330` (сейчас **нет** имени/аватара — только `telegram_id/role_name/added_by/created_at`).
- Обогащение именем/фото (есть прецедент): `user_display_info(chat_id, uid)` + паттерн из `web/api/chat_lore.py:44,60,577-630`; фронт-аватар через `avatarUrl('user', id)` `web/app.js:1232,1266-1298`, инициал `avatarInitial` `:3999`.
- **Открытый вопрос @Architect:** источник ника для глобальных админов (Bot API `user_display_info` вне чата vs кэш отношений vs `first_name/username` из initData). API `/api/admins` не должен утечь секреты (R17).
- Окно «Матрица ролей» `#/access/roles` `:1623-1673` — **не трогать** (п.5 про список назначений «Роли»).

### 2.6 п.6 — Headroom saved-tokens stats
- Внешний MCP-инструмент `headroom_stats` (у владельца); нужен вызов через серверный прокси. В проектном коде ссылок нет (проверить grep по `headroom`).
- **Deliverable:** вывод текущей статистики сэкономленных токенов (read-only) + безопасное хранение/вывод без сырых ключей (R17). Кода в боте по возможности не менять.

---

## 3. План задач

### 3.1 п.1 — Header/fullscreen (T-1315…T-1317)

- [x] **T-1315 (@Architect):** Контракт верхнего паддинга в fullscreen: где именно добавлять отступ (`.fullscreen-mode header` / профильный блок), какие величины (`env(safe-area-inset-top)` + высота нативных кнопок TG), как учитывать `Telegram.WebApp.isFullscreen`/`viewportStableHeight`. Не ломать sticky-модель и мобильные `@media`. 0 кода.
- [x] **T-1316 (@Builder):** Реализовать фикс по контракту T-1315: блок профиля (аватар+ник+роль+⛶) не перекрывается нативными кнопками Telegram в fullscreen. Маркер-тест в `tests/test_webapp_round1010_ui.py`.
- [ ] **T-1317 (@QA):** Live Android/Telegram: включить fullscreen, убедиться, что профильный блок доступен и не перекрыт; выход из fullscreen не сдвигает layout.

### 3.2 п.2 — Mobile key-availability chart (T-1318…T-1320)

- [x] **T-1318 (@Architect):** Диагностика «одной плоской полосы»: разделить data-слой (`key_history` ring/слоты, union `ts`) и render-слой (`canvas height="80"`, `stepped`, `spanGaps:false`, легенда). Вердикт: что чинить и как (при необходимости — контракт `api_payload`). 0 кода.
- [x] **T-1319 (@Builder):** Реализовать фикс (данные и/или рендер) — график на мобильном читается как временной ряд, а не одна полоса. Маркер/JS-юнит-тест.
- [ ] **T-1320 (@QA):** Live mobile (Android): график с реальными слотами рисуется корректно; легенда не перекрывает полотно; пустое состояние сохранено.

### 3.3 п.3 — «Провайдеры»: реальные значения полей (T-1321…T-1323)

- [x] **T-1321 (@Builder):** Наполнять `blockDrafts[f.key]` реальными значениями из `configItems` в `loadConfig`/при смене scope для **не-секретных** полей (display name, base_url, model). Поле «Ключ» (`keys.*`, `secret:true`) **оставить как есть** (маска/placeholder). Сохранить семантику `draft==null` = «не трогать» в `saveBlock`.
  > Реализовано иначе, но точнее (spec §3.2): контролируемый `:value="blockFieldValue(f)"` + `@input` → `blockDrafts`, `blockDrafts`/`blockResults` сбрасываются в `loadConfig`/`setActiveChat`; `blockFieldValue` теперь возвращает `''` для пустого черновика.
- [x] **T-1322 (@Builder):** Маркер-тест: после загрузки конфига `blockDrafts` содержит display_name/base_url/model; секретные поля не префиллятся.
- [ ] **T-1323 (@QA):** Live: в каждом блоке «Провайдеры» видны реальные Название/Адрес/Сервер/Модель; «Ключ» — как раньше; сохранение не затирает значения.

### 3.4 п.4 — ЛС: сон/ностальгия/саммаризация OFF (T-1324…T-1328)  ⚠️ DATA-CHANGE

- [x] **T-1324 (@Architect):** Зафиксировать: (а) точный набор ключей для трёх модулей в DM-скоупе (`overrides` vs `gates`); (б) «OFF по умолчанию» для **новых** ЛС (код-дефолт, без DDL); (в) влияние на воркеры (`dream_worker.py:401-402`, `nostalgia_worker.py:285-286`, `chat_summary_enabled`). 0 кода.
- [x] **T-1325 (@Builder):** Реализовать «OFF по умолчанию» для DM-скоупа (там, где требуется) — минимально, без новых PG-DDL; синхронно с T-1324.
- [x] **T-1326 (@Builder):** Идемпотентный скрипт `scripts/…` (`--dry-run` по умолчанию, `--apply`) — выключить три модуля для всех активных ЛС (`chat_profiles WHERE chat_id>0 AND is_active`), через `set_chat_params`/документированный JSONB-апдейт; снапшот до apply; повторный прогон = 0 изменений. Прецеденты: `scripts/backfill_feature_gates.py`, `backfill_permsoc_gates.py`.
- [ ] **T-1327 (@DevOps):** На проде: снапшот затронутых строк → `--dry-run` (отчёт) → `--apply` → повторный `--dry-run` (0 изменений). Без рестарта, если не требуется; при необходимости — `systemctl restart admin_bot` и health 200.
- [ ] **T-1328 (@QA/@DevOps):** Верификация: ни одна активная ЛС не имеет модулей ON (SELECT/проверка через UI DM-скоупа); новые ЛС получают OFF.

### 3.5 п.5 — «Роли»: аватар+ник, ширины (T-1329…T-1332)

- [x] **T-1329 (@Architect):** Контракт обогащения списка `admins` именем/аватаром (источник, кэш, R17, поведение при недоступности Bot API → фолбэк «ID»). 0 кода.
- [x] **T-1330 (@Builder):** `/api/admins` (или клиентский слой) отдаёт display name/аватар; рендер в `web/index.html:1598-1605`: **аватар + ник**, голый **ID рядом мелким серым** (`text-[10px] text-gray-500`), бейдж роли сохранить. Фолбэк — инициал/ID.
- [x] **T-1331 (@Builder):** Уменьшить ширину селектора ролей и расширить ID-инпут (`web/index.html:1609-1610`): ID — `flex-1` больше, селектор — уже (`w-36`↓); проверить, что кнопка «Назначить» не уезжает на мобильном.
- [ ] **T-1332 (@QA):** Live mobile: список читается (аватар+ник+мелкий ID), ширины полей адекватны, назначение роли работает.

### 3.6 п.6 — Headroom saved-tokens stats (T-1333)

- [ ] **T-1333 (@DevOps):** Получить через серверный прокси текущую статистику `headroom_stats` (MCP-инструмент) и **вывести** её владельцу (plain-language). Read-only, без сырых секретов (R17). Если статистика требует серверного шага — зафиксировать команду/путь в отчёте.

### 3.7 Финал: Scanner follow-ups, README/commit/push/deploy/report (T-1334…T-1341)

- [ ] **T-1334 (@Builder, P2-опционально):** Закрыть low-находки Scanner 10.9 (точечно, 2–10 строк каждая): **R10.9-1** (`model_source` у fallback/эмбеддинг-записей, `services/status_service.py:192-277`), **R10.9-3** (устаревший docstring `status_service.py:10-15`). Если риск > польза — задокументировать решение не брать.
  > В этом проходе не брал (фокус — пункты 1–5 владельца; P2-опционально). Решение: не трогать `status_service.py` сейчас, чтобы не раздувать диф и не рисковать контрактом.
- [ ] **T-1335 (@Builder):** README (ироничный тон): обновить счётчик тестов и changelog раунда 10.10; синхронно поднять `APP_VERSION` (`config/settings.py`) + cache-bust `?v=` (закрыть риск R10.8-5), не ломая `test_app_version_matches_readme`.
  > В этом проходе не делал: явный запрет владельца/задания на README и `.env`; версия/cache-bust не тронуты.
- [x] **T-1336 (@Builder):** Полный прогон: `pytest` (baseline **5105** + новые), `node --check web/app.js`, `node tests/js/routing_test.js`, `git diff --check`.
- [ ] **T-1337 (@DevOps):** Русский conventional-commit, `git push` (origin/master).
- [ ] **T-1338 (@DevOps):** Деплой: `git pull --ff-only`, при необходимости `systemctl restart admin_bot`; `/api/health` = 200, 0 ERROR/Traceback.
- [ ] **T-1339 (@PM):** Plain-language отчёт владельцу (что изменилось, что стало лучше, что осталось), включая вывод Headroom stats (T-1333).

---

## 4. Acceptance criteria (по пунктам)

| # | AC |
|---|---|
| 1 | В FULLSCREEN блок профиля (аватар+ник+роль+⛶) не перекрыт нативными кнопками Telegram на Android; sticky-модель и выход из fullscreen корректны. |
| 2 | На мобильном график доступности ключей отображается как временной ряд (не одна плоская полоса); пустое состояние и легенда сохранены. |
| 3 | В «Провайдеры» поля Название/Адрес/Модель показывают реальные текущие значения; поле «Ключ» — как раньше (маска); сохранение работает и не затирает. |
| 4 | Сон/Ностальгия/Саммаризация — OFF по умолчанию для новых ЛС и OFF для всех текущих активных ЛС; повторный data-прогон идемпотентен (0 изменений); новых PG-DDL нет. |
| 5 | В «Роли» список показывает аватар+ник, ID — мелким серым рядом; селектор ролей уже, ID-инпут шире; назначение роли работает. |
| 6 | Текущая статистика `headroom_stats` получена и выведена владельцу; без утечки секретов. |
| + | README (ирония, счётчик, версия) обновлён; русский commit; push; деплой; health 200; plain-language отчёт. |

---

## 5. QA / test plan

- **Python:** `py -m pytest tests/ -q` — baseline **5105 passed / 0 failed**, цель 0 failed и +новые.
- **Синтаксис JS:** `node --check web/app.js`.
- **JS-юниты:** `node tests/js/routing_test.js` → `JS-UNIT-OK`.
- **Новые/обновлённые маркер-тесты:** `tests/test_webapp_round1010_ui.py` (NEW: п.1/п.3/п.5 маркеры),
  `tests/test_webapp_key_availability_ui.py` + `tests/test_key_availability.py` (п.2),
  `tests/test_webapp_dm_ui.py`/`tests/test_dm_access.py` (п.4 default OFF),
  `tests/test_webapp_avatars_ui.py`/`tests/test_roles_admin.py` (п.5),
  `tests/test_webapp_api.py`/`tests/test_status_service.py` (п.2/п.3, если меняется контракт).
- **Скрипт п.4:** отдельный тест идемпотентности/`--dry-run` (без реального PG — на in-memory/mock, прецедент backfill-тестов).
- **Каталог-пины:** `REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88 / TAB_RULES 19` — держать; менять только при обоснованном добавлении ParamSpec.
- **Секреты:** grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` — пусто; вывод Headroom — без сырых ключей.
- **Live Android (обязательно, за владельцем/QA):** п.1 (fullscreen), п.2 (график), п.3 (поля), п.5 (список/ширины); п.4 — проверка DM-скоупа в UI.
- **PC/git:** `git diff --check`; `media/`/`bot.py` не тронуты; 0 новых PG-DDL.

---

## 6. Feature flags & progressive delivery

- **П.1/п.2/п.3/п.5/п.6 (UI + read-only stats):** отдельный фича-флаг не нужен; rollback = `git revert`.
- **П.4 (data-change, самый рискованный):** обязательный поэтапный прогон:
  1. **snapshot** затронутых DM-строк (SELECT→JSON) — rollback-точка;
  2. `--dry-run` — список изменений (кол-во/ключи), без записи;
  3. `--apply` на проде;
  4. повторный `--dry-run` → **0 изменений** (идемпотентность);
  5. выборочная проверка 2–3 ЛС в UI + SELECT-ассерт.
  - Опционально staged-охват: сначала «внутренние» ЛС (по списку telegram_id владельца), затем все — если @Architect сочтёт нужным.
- **Каталог/env:** новые env-ключи не требуются; `.env` не менять.

---

## 7. Открытые вопросы (в @Architect до реализации)

1. **п.1:** точная величина/селектор верхнего отступа в fullscreen (только `.fullscreen-mode`? учитывать ли `viewportStableHeight`?).
2. **п.2:** «плоская полоса» — это данные (мало слотов / общий `ts`) или отрисовка (фикс `height=80`, overlapping stepped-lines)? Меняется ли контракт `api_payload`?
3. **п.4:** «саммаризация» для ЛС — это `flags.summary_enabled` (модуль) или `flags.chat_running_summary_enabled` (бегущий конспект, уже OFF для ЛС)? Куда писать `gates` vs `overrides`?
4. **п.5:** источник имени/аватара глобальных админов (Bot API `user_display_info` вне чата / кэш отношений / initData) и поведение при недоступности.
5. **п.6:** как именно забирать `headroom_stats` через серверный прокси (команда/эндпоинт) и в каком виде выводить.

---

## 8. Учёт аудита @Scanner (R10.9)

- Прочитан `plans/reports/round10.9_scanner_audit.md` (**0 blocker / 0 major / 0 medium**; 3 low + 3 info)
  и `plans/reports/audit_backlog.md` (раунд 10.9 просканирован полностью).
- **Учтено (P2, точечно):** **R10.9-1** (`model_source` fallback/embedding-записей → T-1334),
  **R10.9-3** (stale docstring `status_service.py` → T-1334).
- **Известный техдолг (вне скоупа 10.10, кандидаты follow-up):** R10.9-2 (emb-fallback display/omit),
  R10.9-4 (health cache-key `module_id`), R10.9-5 (docstring `llm_probe`/`ConnectTimeout`),
  R10.7-1/-2 (`status_service` gap-fill), R10.6-1 (дубль generic-рендера), R10.6-2/-3 (SSRF/422-эхо `api_key`).
- **Инварианты 10.9 соблюдены** (400/90/372/mapped 88, 0 PG-DDL, SQLite v8, `bot.py`/`media/` не тронуты) — 10.10 их сохраняет.

---

*План создан @PM 12.09.2026 (Step 1). Код не писался. Передача @Architect (T-1315/T-1318/T-1324/T-1329) и @Builder (реализация), @DevOps (data-run T-1327, stats T-1333, commit/push/deploy T-1337/T-1338).*

---

## 9. Статус @Builder (реализация п.1–п.5, 12.09.2026)

**Сделано (код + тесты):**
- **п.1 (T-1316):** CSS `.fullscreen-mode header.header-sticky` c `max(env(...), var(--tg-content-safe-area-inset-*), var(--tg-safe-area-inset-*))` (`web/index.html`); 10.7/10.9 сохранены.
- **п.2 (T-1319):** чистая `keyHistoryChartModel` (дорожки `i+0.75/i+0.25`, временная сетка 300с/мин. 12 бакетов, `null` на пропуске, `pointRadius:3` при ≤1 сэмпле), `maintainAspectRatio:false`, реактивная `keyHistoryChartHeight`, обёртка `.keys-chart`; контракт `/api/status/key-history` не тронут.
- **п.3 (T-1321/T-1322):** контролируемый `:value="blockFieldValue(f)"` + `@input`; `blockFieldValue` возвращает `''` для пустого черновика; сброс `blockDrafts`/`blockResults` в `loadConfig`/`setActiveChat`; `saveBlock`/MINOR-3 не тронуты.
- **п.4 (T-1325/T-1326):** `services/chat_params.py` — `_DM_DISABLED_GATES`/`_DM_DISABLED_OVERRIDES` + DM-дефолты в `ensure_scope_profile(dm=True)`; `scripts/disable_dm_heavy_modules.py` (dry-run/`--apply`/`--chat-id`/`--snapshot-out`/`--restore`, идемпотентность, snapshot до записи, abort при сбое snapshot, запись только через `set_chat_params`, 0 DDL). Групповой путь и `bot.py` (F-14) не тронуты.
- **п.5 (T-1330/T-1331):** `global_user_display_info(user_id)` (`web/api/avatars.py`, RAM-TTL 1ч, fail-open) + обогащение копий в `GET /api/admins` (`asyncio.gather`+`Semaphore(5)`); фронт — аватар/инициал + ник, ID `text-[10px] text-gray-500 font-mono`, селектор `w-24`, ID-инпут `flex-1 min-w-0`, кнопка `shrink-0`; `loadAdmins` грузит blob-аватары.

**Прогоны:**
- `pytest -q`: **5133 passed / 1 skipped / 0 failed** (baseline 5105; добавлено 28 тестов).
- `node --check web/app.js` — clean; `node tests/js/routing_test.js` — `JS-UNIT-OK`.
- `git diff --check` — чисто (только LF/CRLF-предупреждения).
- Новые тесты: `tests/test_webapp_round1010_ui.py`, `tests/test_scripts_round1010_dm_off.py`, JS-юниты в `tests/js/routing_test.js`, дополнения в `tests/test_chat_params.py`, `tests/test_webapp_api.py`, `tests/test_webapp_avatars_ui.py`.

**Осталось (не Builder):** T-1317/T-1320/T-1323/T-1332 — Live Android (QA); T-1327/T-1328 — прод data-run (DevOps); T-1333 — Headroom stats вне репо (DevOps); T-1337/T-1338 — commit/push/deploy (DevOps); T-1339 — отчёт (PM). T-1334/T-1335 — осознанно не брались в этом проходе (P2/README-запрет).

**Blockers:** нет. `media/`, `.env`, `bot.py`, SQLite v8, каталог-пины (400/90/372/mapped 88, TAB_RULES 19) — не тронуты; новых PG-DDL нет.

---

## 10. Фикс после ревью (High-1 + Medium-2 + Low-3/4/5, 12.09.2026)

@Reviewer REJECTED (1 High + 1 Medium + 3 Low) — все закрыты:

- **HIGH-1 (`web/app.js`, `keyHistoryChartModel`):** окно графика строится ОТ КОНЦА: `minStart = endBucket - (MAX_HISTORY_POINTS - 1)*SAMPLE_BUCKET`, `startBucket = max(firstBucket, minStart)`, затем `min(... MIN_BUCKETS ...)` и `max(0, ...)`. Убраны `break` после 576 бакетов и `grid.slice(-MAX_HISTORY_POINTS)`; `endBucket` — последний элемент, длина ≤ `MAX_HISTORY_POINTS`. Новейшие сэмплы больше не теряются. JS-юнит на разброс > 576 бакетов (см. ниже) + статический маркер `test_window_built_from_end_high1`.
- **MEDIUM-2 (`scripts/disable_dm_heavy_modules.py`, `restore_from_snapshot`):** `--restore` больше НЕ передаёт `meta` — `set_chat_params` заменяет namespace только при наличии ключа, значит прежний `meta` не затирается. Тест `test_restore_does_not_wipe_meta`.
- **LOW-3 (`run()`):** при непустом `res['errors']` возвращается код 1; в финальном отчёте печатается `errors=<k>`. Тест `test_apply_partial_failure_nonzero_exit`.
- **LOW-4 (`web/api/avatars.py`, `global_user_display_info`):** транзиентные ошибки (`TelegramRetryAfter`/`TelegramNetworkError`) обрабатываются отдельной веткой и НЕ пишутся в негатив-кэш (паттерн BUG-4); кэшируются только дефинитивные негативы. Функциональные тесты `TestGlobalUserDisplayInfoFunctional1010` + маркеры.
- **LOW-5 (`tests/js/routing_test.js`):** добавлен кейс span > `MAX_HISTORY_POINTS` бакетов: сэмпл в `endBucket` присутствует ПОСЛЕДНИМ, длина окна ровно `MAX_HISTORY_POINTS`, древний сэмпл вне окна.

**Повторные прогоны после фикса:**
- `pytest -q`: **5138 passed / 1 skipped / 0 failed** (было 5133; +5 тестов).
- `node --check web/app.js` — clean; `node tests/js/routing_test.js` — `JS-UNIT-OK`.
- `git diff --check` — чисто. Секретов/Headroom в диффе нет. `bot.py`/`media/`/`.env`/PG-DDL не тронуты.

**Blockers после фикса:** нет.

---

## 11. Фикс остаточного Low (restore exit-code, 12.09.2026)

@Reviewer: `--restore` всегда возвращал 0 при частичном сбое (per-chat
исключения только логировались) — закрыто.

- **`scripts/disable_dm_heavy_modules.py`:**
  - `restore_from_snapshot` возвращает `{restored, total, errors}` (список
    chat_id, которые не удалось восстановить), а не голый счётчик;
  - `run()` в ветке `--restore` печатает `restored=<n>/<total>` и
    `errors=<k>`, возвращает **1** при `errors` непустом ИЛИ
    `restored < total`; полный успех → 0.
- **Тесты:** `test_restore_partial_failure_nonzero_exit` (1 из 2 чатов
  падает → exit 1, `restored=1/2 errors=1`, успешный чат восстановлен) и
  `test_restore_all_success_exit_zero` (`restored=1/1 errors=0` → exit 0).

**Повторные прогоны:**
- `pytest -q`: **5140 passed / 1 skipped / 0 failed** (+2 теста к 5138).
- `node --check web/app.js` — clean; `node tests/js/routing_test.js` —
  `JS-UNIT-OK`; `git diff --check` — чисто.

**Blockers:** нет.

---

## 12. Фикс Scanner-low (12.09.2026)

@Scanner/`@Reviewer`: 3 дешёвых Low + 1 info — закрыты.

- **1. Stale Chart.js (`web/app.js` `renderKeyHistoryChart`):** teardown
  (`destroy()` + обнуление ссылки) выполняется ДО раннего `return`, в т.ч.
  при `keyHistory == null`; высота сбрасывается в 120. JS-тест на stale
  instance при пустой истории.
- **2. Snapshot/restore `meta` (`scripts/disable_dm_heavy_modules.py`):**
  `build_snapshot` хранит `meta`; `--restore` возвращает его faithfully
  (прежний `meta.note` не теряется). Legacy-снапшоты без ключа `meta`
  namespace не трогают. Тесты: `test_apply_snapshot_preserves_meta`,
  `test_restore_returns_meta_faithfully`,
  `test_restore_legacy_snapshot_without_meta_not_wiped`.
- **3. Scope-отчёт (`--chat-id`):** добавлен `select_scope`; `noop/total`
  в dry-run и apply считаются по выбранному scope, а не по всем ЛС.
  Тесты: `test_dry_run_scope_respects_chat_id`,
  `test_apply_report_scope_respects_chat_id`.
- **4. info (`web/app.js` `loadAdmins`):** негатив blob-аватара помечается
  `avatarSkipped` (повторная `loadAdmins` не долбит прокси); дублирующий
  `adminInitial` переписан на делегирование общему `avatarInitial` (без
  дубля графем-логики), удалена недостижимая ветка `admin.username`
  (template + helper). JS-юниты + маркеры обновлены.

**Повторные прогоны:**
- `pytest -q`: **5144 passed / 1 skipped / 0 failed** (+4 к 5140).
- `node --check web/app.js` — clean; `node tests/js/routing_test.js` —
  `JS-UNIT-OK`; `git diff --check` — чисто.
- Секретов/Headroom в диффе нет; `bot.py`/`media/`/`.env`/PG-DDL не тронуты.

**Blockers:** нет.
