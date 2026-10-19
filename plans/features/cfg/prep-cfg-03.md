# PREP-CFG-03 — бриф исполнения: полный аудит работоспособности ВСЕХ параметров MiniApp

**Лейн:** PM-PREP-CFG-03 (read-only; единственный артефакт — этот документ; код, карты, `current_task.md` и прод не менялись; SSH не использовался).
**Дата:** 19.10.2026, 12:25 (UTC+12) · HEAD master `20e4fa81` (движется: параллельные лейны коммитят доки) · прод **2.58.92** (ре-приёмка 92B идёт; 2.58.92 = 2.58.91 + vision-fix2 + ADD-TR fix2) · **CFG-02C: Approved `77e7dd5a` + леджер `26ebc0a8`, кандидат `1d9a7107` — в master, но НЕ выкачен** (ждёт следующий релиз-поезд после 2.58.92; `CFG-02C.5` — RFL live preprod на его приёмке) · f8-пара на HEAD **зелёная**: `tests/test_round1025_f8_registry.py` — 29 passed (прогон этого лейна, read-only).
**Источники:** `plans/features/cfg/{requirements-map.json (19 строк слайса CFG-03), slice-graph.json, plan.md, source-cfg-addendum.md L22/L119–L145}`, `prep-cfg-02b.md`/`prep-cfg-02c.md`, P0-карты (`p0-save-init-ux/requirements-map*.json`), `review-cfg-01/02a/02b/02c.md`, `plans/workflow_state.md`; код и артефакты (только чтение): `services/{param_catalog,chat_params,chat_settings_seed,hot_config,feature_gates,config_cache}.py`, `web/app.js`, `web/api/{routes,gates}.py`, `config/settings.py`, `tools/gen_param_registry_round1025.py`, `tools/_cfg02b_reissue_f8.py`, `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md`, `plans/archive/settings-persistence-audit-round1014/*`, `tests/*`.

---

## 1. Состав слайса (19 строк, все PENDING) — что доказывать

Рамка и метод (3 строки):

| # | req_id (источник) | Обязательство (сжато, дословные опоры) | Что именно доказывать |
|---|---|---|---|
| 1 | **ADD-1.T3** (L22, таблица v0.7) | «**Расширение до ВСЕХ параметров**, а не повтор B06/SOUL. Засчитывать уже подтверждённую трассу параметра, искать отсутствующий runtime consumer и `UI_missing`» | Каждая запись каталога (579) получила трассу в манифесте; ранее подтверждённые трассы (P0/B06/SOUL-1/CFG-01/02A/02B/02C) **переиспользованы без повторного прогона**; отдельно найдены и классифицированы: runtime-параметры без фактического потребителя и `UI_missing`. |
| 2 | **CFG-03.F** (L121) | «Не ограничиваться визуальным наличием полей, HTTP 200 или сохранённым значением в PostgreSQL. Сквозная инвентаризация всех реально представленных настроек и их потребителей. Это расширение покрытия B06 и SOUL-1, а не повтор» | Сквозная инвентаризация (настройка → потребитель) по всем 579 записям; для записей с доказанным E2E — проверка «не устарело» и переиспользование evidence. |
| 3 | **CFG-03.M** (L125) | Обязательная цепочка **на каждый параметр**: `UI-экран/контрол → Registry ID/тип/границы/Factory Default → scope/наследование → API read/write → DB → кэш/уведомления → effective resolver → фактический runtime consumer → observable behavior → тест/доказательство` | Манифест содержит все звенья цепочки для каждой записи; неприменимое звено — документированное «—», а не пропуск. |

Нормы 1–12 (L127–L138):

| # | req_id | Обязательство (сжато) | Что именно доказывать | Live |
|---|---|---|---|---|
| 4 | **CFG-03.1** (L127) | Проверить **каждый** параметр во всех разделах MiniApp, включая скрытые расширенные настройки, старые каталоги, модели/ключи, лимиты, промпты, модули, события, настройки чатов и глобальные, SOUL-1. **Обязательно обратное несоответствие**: runtime-параметры из реестра/конфигурации без положенного UI → `UI_missing` (как было с `limits.image_daily_limit`) | Полный охват разделов/категорий (знаменатель — §1.1); reverse-check: `REGISTRY − (UI-контролы ∪ документированные api-only/hidden) = ∅`. | — |
| 5 | **CFG-03.2** (L128) | Классифицировать по матрице: `working`, `save_only`, `runtime_not_consumed`, `wrong_scope`, `stale_cache`, `restart_required`, `invalid_default`, `UI_missing`, `UI_present_but_not_discoverable`, `effective_value_mismatch`, `inaccessible`, `duplicate_conflict`, `unknown`. Для отклонений — путь, воспроизведение, приоритет, исправление. Отдельно — параметры, перекрытые кодовым/ENV значением, cached constructor state или неверным scope | Классификация на каждую запись; карточка отклонения на каждый не-`working`; отдельный под-отчёт «перекрытий». | — |
| 6 | **CFG-03.3** (L129) | read/write/reload после перезапуска, F5, разных пользователей и состояний прав; отмена, optimistic concurrency, сетевые ошибки, 409, повторное сохранение, rollback, глобальное/локальное наследование, сброс в factory, снятие override | Покрытие классами сценариев по всем типам настроек; P0 real-DB цикл переиспользуется, остальные типы/эндпоинты доисполняются. | — |
| 7 | **CFG-03.4** (L130) | Для **горячих** параметров — изменение реального поведения без рестарта; для рестарт-зависимых — честно показать это в UI, проверить необходимость; фиктивный hot-reload запрещён | Список hot-параметров + проверка «изменил → поведение изменилось без рестарта» (тесты/спай + live preprod); честные метки для остальных. | ✔ preprod |
| 8 | **CFG-03.5** (L131) | Соответствие UI-описания реальной семантике, формату, валидаторам, диапазонам, единицам времени, `0`/`-1`/`null`, per-chat доступности. «Сохранилось, но игнорируется» — исключено | Сверка по каждому видимому параметру; закрытие carry-in находок CFG-01 R1 (min/max + единицы) и CFG-02A R5 (серверные диапазонные границы). | — |
| 9 | **CFG-03.6** (L132) | Временно отключённые/неиспользуемые параметры — честно отображаются (или выводятся из интерфейса после **отдельного согласования**), не изображают действующие | Список отключённых + честная витрина; вывод из UI — только через согласование (владельческое решение — реальный продуктовый выбор). | ✔ preprod |
| 10 | **CFG-03.7** (L133) | Runtime-пути: фоновые задачи, обработчики Telegram, Direct/Initiative, Summary/Factcheck/Images, память, fallback, доп. воркеры. Скрытые env-only потолки, перекрывающие UI-значение, **диагностируемы администратору без раскрытия секретов** | Матрица «маршрут → параметры-потребители»; список env-only потолков (напр. `WORKER_DAILY_IMAGE_CALLS_GLOBAL`) + способ диагностики. | — |
| 11 | **CFG-03.8** (L134) | Все проверки — в изолированной среде с безопасными фикстурами; боевые ключи/квоты не менять; массовых платных генераций на production нет | Метод проверок (sandbox-first; live — безопасные окна, малый объём); R17 (секреты не раскрываются). | — |
| 12 | **CFG-03.9** (L135) | Устойчивые автотесты: контракт каталога, реальные API/DB roundtrips, runtime consumer tests, перезапуск, многопроцессность, выбранные E2E на реальной MiniApp; одних моков недостаточно | Тестовый набор (см. Ф2) + честное разделение mock/live. | — |
| 13 | **CFG-03.10** (L136) | Независимый Reviewer-аудит и регрессионный прогон после исправлений; **100% не объявляется**, если часть параметров без фактической проверки | Review-гейт + честные счётчики «проверено/непроверено». | — |
| 14 | **CFG-03.11** (L137) | Для **каждого редактируемого параметра** — отрицательный тест: заведомо меняющее результат значение (лимит 1 вместо 10) → наблюдать реальный эффект → вернуть конфигурацию. «Прочитал в API то же, что записал» — не доказательство | Class-based параметризованные негативы + выбранные live; недоказуемое безопасно — в R4-список с точным сценарием. | ✔ preprod |
| 15 | **CFG-03.12** (L138) | Для каждой настройки-запрета: OFF/ON (0/ненулевое) реально отключает/включает поведение **по всем поддерживаемым маршрутам**; UI показывает effective state. Отдельно искать **параметры-сироты** (созданы в каталоге, но нигде не показываются/не читаются) | Проверка гейтов по маршрутам + список сирот (пустой либо классифицирован). | ✔ preprod |

Отчётность (L142–L145):

| # | req_id | Поставка | Что именно доказывать |
|---|---|---|---|
| 16 | **CFG-03.R1** (L142) | Машиночитаемый coverage manifest **на каждый параметр** с источниками и ссылками на тесты | Артефакт-манифест (формат — решение Ф1; кандидат — расширение схемы §3.4). |
| 17 | **CFG-03.R2** (L143) | Понятная владельцу сводка: проверено / работает / исправлено / непроверено | Сводка с честными числами (сверяется Reviewer'ом с манифестом). |
| 18 | **CFG-03.R3** (L144) | По каждому сбою: причина, затронутые пути, кодовая правка, автотест, live evidence, статус | Реестр сбоев в формате P0A-PERSIST-AUDIT (переиспользуется формат, не прогон). |
| 19 | **CFG-03.R4** (L145) | Отдельный список параметров, которые нельзя безопасно проверить без владельческого действия/живого события, **с точным сценарием ручной проверки** | Список + сценарии; PET-правило: device-чек-листы владельца не создаются, агентские проверки — агентам (см. §6 R9). |

### 1.1 Знаменатель аудита (счётные факты на HEAD; проверить в Ф1 повторно)

- **REGISTRY 579** (после CFG-02B; GROUPS 120, `_TAB_BY_GROUP` 118, TAB_RULES 23; F8-meta: `param-registry-round1025.meta.md`).
- Видимость: **visible 552 / api-only 25 / hidden 2** (screen-map; `api-only ≠ сохранено в UI` — REQ-F8-08).
- Scope: per_chat **441** / глобальные **138**; секретов **43**; категории: limits 226, flags 99, models 74, memory 47, reactions 39, keys 35, infra 25, prompts 25, content 5, temporal 4.
- Хранилище: chat-overrides 338, bot_settings 113, оба 102, env 25, спец (guide) 1.
- Разделы MiniApp: config-вкладки **23** (TAB_RULES = CONFIG_TAB_TITLES; TABS в `app.js` — 28 = 23 config + 5 не-config: modules/access/status/info/oversight), спец-экраны «Справка» (#/info; 2 группы `content_*` без вкладки — ожидаемо), «Речь и характер» (#/ai/speech), «Личность» (#/persona).
- Границы знаменателя: манифест — на **579 записей REGISTRY**; отдельным ограниченным проходом — «старые каталоги»/env-only потолки **вне** реестра (L127/L133): `config/settings.py` + поиск env-чтений; классифицируются как документированные env-only (не `UI_missing`), кроме реально требующих UI.

---

## 2. Что уже покрыто (алиасы — не дублировать) и что реально осталось

**Обновление против прежнего брифа** (prep-02b §5): P0-леджеры завершены — P0A **29/29 VERIFIED** (release-гейт `29/0` EXIT 0), FU-B 32/35 (SCEN-B честно `WAITING_EXTERNAL`). Поэтому **все пять P0-алиасов CFG-03 теперь VERIFIED на P0-стороне** (ранее «.3/.11/.F ждут леджер» — устарело). Сами строки CFG-03 остаются **PENDING**: их покрытие шире (все параметры), P0-эвиденс при биндинге **переиспользуется**, не перепрогоняется.

| Строка CFG-03 | Владелец-алиас (карта) | Статус алиаса | Что уже закрыто | Что остаётся CFG-03 |
|---|---|---|---|---|
| CFG-03.2 | P0A-PERSIST-CAUSE (`p0-save-init-ux`) | **V** | Первопричины сохранения классифицированы для «Речи и характера»; `write_error` не диагноз | Матрица 13 классов по **всем** 579 записям + «перекрытия» |
| CFG-03.3 | P0A-ACCEPT-PERSIST | **V** | Полный real-DB цикл по каждому типу настроек (прод 2.58.90, 17/17 + recheck `diff={}`) | Распространение на остальные параметры/эндпоинты; недостающие края (отмена/сеть/factory reset) |
| CFG-03.11 | P0A-ACCEPT-PERSIST-EDGE | **V** | 409 `document_invalid`/422/конфликт без потери текста (речевые настройки) | Отрицательный тест на **каждый** редактируемый параметр (классами + live) |
| CFG-03.F | P0A-PERSIST-TRUTH | **V** | Контракт «успех = read-after-write + runtime» (центральный механизм) | Сквозная инвентаризация всех настроек и потребителей + манифест |
| CFG-03.R3 | P0A-PERSIST-AUDIT + P0A-PERSIST-CENTRAL | **V** | Формат «причина/пути/правка/тест/evidence/статус» + централизованный фикс | Применение формата к сбоям самого CFG-03 |
| CFG-03.9 (принцип) | P0V-TEST-MOCKS (`p0-vision-universal`, алиас на CFG-03.9) | PENDING там | Принцип «моки не заменяют живые проверки» зафиксирован | Собственный набор устойчивых тестов CFG-03 |
| ADD-1.T3 (B06-часть) | ASAP8 v6.3 **B06.1–B06.3** (`asap8-v6-3-live-correction`) | V (Playwright 42/42, REV-W3 Approved) | per-chat Summary + переключатели реально управляют runtime | Трасса в манифесте; не переигрывать |
| ADD-1.T3 (SOUL-часть) | SOUL-1 (Prompt Registry/Style Policy/Factory Defaults; `review-w6/w10`, §5 18/18 V) | V | SOUL-параметры и контракты приняты | Не пересобирать; переиспользовать трассы |
| (carry-in) | CFG-01 R1 (`review-cfg-01 §R1`) | открыто | Рантайм клампит, но каталог не задаёт min/max; UI-тексты без единиц | Каталог/UI: границы и единицы — закрывается здесь |
| (carry-in) | CFG-02A R1/R5 (`evidence/cfg-02a`) | открыто | Клиентские границы есть; серверная валидация — только тип | Серверные диапазонные границы каталога |
| (прецедент) | CFG-02B леджер (`dea5f84a`) | V | Кат. дельта-процедура 575→579 + re-pin ~50 файлов | Процедура переиспользуется, работа не повторяется |
| (прецедент) | CFG-02C леджер (`26ebc0a8`) | V (`.5` RFL) | Типизация потребления, честные причины/TZ | Не повторять; честность effective-состояний — образец |

**Непереиспользованное ядро CFG-03 (то, что реально осталось):** машинный манифест 579 с трассой; классификация 13 классов; reverse-check `UI_missing`/сироты; hot-поведение без рестарта (.4); честность отключённых (.6); env-потолки (.7); negative per editable (.11); OFF/ON по маршрутам (.12); reviewer-аудит (.10); поставки R1/R2/R4. Действие PM из prep-02b §5 («синхронизировать статусы CFG-03 с P0-картами») **ещё не выполнено** — строки карты без P0-notes (сделать в Ф0, без ложных закрытий).

---

## 3. Кандидаты файлов/точек (read-only инвентарь; правок не вносилось)

### 3.1 Каталог и его артефакты (источник знаменателя)

| Что | Где | Роль для CFG-03 |
|---|---|---|
| Реестр | `services/param_catalog.py` (303 КБ): `ParamSpec` (:78) — `settings_field/env_name/category/title_ru/type/secret/group/description/code_source/pg_id/widget/progressive_level/select_options/hidden/stage`; `GroupSpec` (:140); `GROUPS` 120 (:151); `_build_registry` (:2745); `REGISTRY` 579 (:2899); `CONFIG_TAB_TITLES` (:3115); `TAB_RULES` 23 (:3197); хелперы `tab_group`/`tab_nav` (:3410–3422) | **Один писатель**. Любая правка файла = re-pin `PARAM_CATALOG_SHA256_FOLLOWUP` (§3.5). hidden-ключи: `limits.factcheck_context_messages`, `prompts.summary_cover_style_id` (ADR-1023-2) |
| Машинный реестр | `plans/docs/param-registry-round1025.tsv` (579 строк; 23 колонки: internal_key…ui_visibility…runtime_consumer…read_fn…status) + `.meta.md` (счётчики, R17, схема) | База манифеста R1. **Важно:** колонка `runtime_consumer` — грубая шаблонная (групповая), у 168 новых ключей — литеральный плейсхолдер `ConfigCache / hot.get\|get_chat_param`; это **не доказательство**, аудит обязан дать verified-потребителя |
| Карта экранов | `plans/docs/screen-map-round1025.md` (579 строк: old_screen→new_screen, read/write API, ui_visibility, secret, hidden, status; «без места = 0») | Статическая опора reverse-check; проверяется тестом `test_all_params_have_a_place` |
| Генератор | `tools/gen_param_registry_round1025.py` (`--check` идемпотентность; `_read_inventory` — 411-baseline; `_ui_visibility`, `_new_screen`) | Расширение схемы/генерация манифеста (Ф1); не импортируется рантаймом (`test_tools_not_imported_by_runtime`) |
| Прецедент аудита | `plans/archive/settings-persistence-audit-round1014/{inventory.tsv (411 строк, 12 колонок), report.md}` | Прямой предок машинного манифеста; схема расширяется (классификация, verified consumer, evidence) |

### 3.2 Витрина MiniApp (web)

| Что | Где | Роль |
|---|---|---|
| UI-каталог/рендер | `web/app.js` (~22.5 тыс. строк): `CONFIG_GROUP_DISPLAY` (:1366), зеркало `TAB_RULES` (комментарии :85–:349), рендер секций/групп/`basic/advanced` (:15683–:15855), save-пути (`saveBlock/saveConfigItem`, :2128/:5707/:12892), прецедент `IMAGE_QUOTA_KEY`/`data-image-quota-*` (:1309–:1388) | **Один писатель** на время слайса. UI-правки CFG-03 — только аудит-фиксы (подписи/единицы/честность/места для UI_missing); **не** формы/save/dirty (CFG-04) и не навигация/стекло |
| Оболочка/стили | `web/index.html`, `web/static/app.css` | Условно (только если аудит потребует UI-места); дизайн не переделывать |
| E2E-прецеденты | `tools/ui_cfg02a_image_quota_e2e.py`, `tools/ui_cfg02b_*`, `tools/ui_cfg02c_*` (+ Playwright/Browser Use) | Образец для `tools/ui_cfg03_*_e2e.py` |

### 3.3 API / резолв / хранилище (services)

| Что | Где | Роль |
|---|---|---|
| Config API | `web/api/routes.py`: `GET /config` (:456), `POST /config` (:609), `GET /config/params-meta` (:728 — источник title/type/group/per_chat/secret_mask для TMA; hidden не отдаёт), `GET/PUT/DELETE /config/keys/own` (:792–:891), `DELETE /config/chat/{key}` (:973 — снятие override), `GET /config/overrides-map` (:1042) | Чтение/запись/валидация; **файл byte-frozen** (`ROUTES_SHA256_F11`) — правки только осознанным re-pin |
| Effective resolver | `services/chat_params.py`: `_resolve_from_root` (:354, порядок override→hot→default), `get_chat_param` (:344), `get_chat_param_sourced` (:636, источник chat/global/default), `ChatParamsCache` (:234, TTL ~120 с + `invalidate_chat_from_notify`), `set_chat_params` (:407, 409/история/NOTIFY), `_chat_write_lock` | Ядро цепочки M (scope→resolver→consumer); прецедент CFG-01 (резолвер добавлен сюда же) |
| Кэш/горячее | `services/config_cache.py` (47 КБ; PG-first), `services/hot_config.py` (:71 `get(key, default)`; `_catalog_spec`/`_coerce`) | Звено «кэш/уведомления»; честность stale_cache |
| Дефолты | `config/settings.py` (458 полей; factory defaults; APP_VERSION) | «Factory Default» звена M; пин `FACTORY_SET_SHA256_12` |
| Сид | `services/chat_settings_seed.py` (seed `config/chat_settings_seed.json`; `enforce`-список) | per-chat предзаполнение; проверить в инвентаре |
| Гейты | `services/feature_gates.py` (HEAVY/ALL_GATED_FEATURES; резолв chat_params.gates→flags→False), `web/api/gates.py` (`GET/PUT /api/chat/{id}/gates`, `/api/workers/budget`); бюджеты: `services/worker_settings.py`, `services/budget_limits.py`, `services/worker_budget.py`; способности: `services/capability_registry.py` | «Настройки-запреты» (.12): OFF/ON по маршрутам; effective state |
| Права | `services/roles.py`, `web/api/access.py` | «разные пользователи и состояния разрешений» (.3); view/edit матрица |

### 3.4 Пины, тесты, re-pin-машинерия (обязательные точки синхронизации)

| Что | Где | Роль |
|---|---|---|
| F8-заморозка | `tests/test_round1025_f8_registry.py`: `PARAM_CATALOG_SHA256_FOLLOWUP` (:146), `FACTORY_SET_SHA256_12`, `ROUTES_SHA256_F11` (:102), `PG_DB_SHA256_B07`, `test_counts_frozen` (579/120/118/23), `test_delta_explicit` (168), screen-map проверки (:388–:417) | Любая правка `param_catalog.py` → re-pin; кат. дельта → счётчики+фикстуры |
| Фикстуры | `tests/fixtures/round1025/{catalog_baseline.json, f8_baseline.json}` | Baseline ключей/групп/вкладок |
| IA/витрина | `tests/test_ia_inventory_round1025.py` (множества ключей/групп/вкладок), `tests/test_frontend_tab_mapping.py` (`test_mapped_and_counts` и состав модулей), `tests/test_param_catalog.py` (`TestCompleteness` — покрытие всех Settings-полей; `TestGroups8424`; `test_dig_flags_registered_and_defaults`), `tests/test_budget_settings_round1019.py` | Регрессия контракта каталога/IA |
| Re-pin-процедура | `tools/_cfg02b_reissue_f8.py` (шаги 1–6: регенерация TSV/meta/screen-map → фикстуры → перенос счётчиков → `PARAM_CATALOG_SHA256` → `FACTORY_SET` → сверка `ROUTES`) + ~50 count-pin файлов (машинный список в scope-заметке CFG-02B) | Готовый чек-лист при кат. дельте; при Δ=0, но правке файла — минимум re-pin SHA |
| CFG-03-тесты | новые `tests/test_cfg03_*.py` (`TEST-LIFECYCLE: CONTRACT/REGRESSION owner=CFG-03`); `tests/test_chat_params.py` (текущий: resolver/409/cache/DM) — расширение | Ф2 |
| JS-пины | `tests/js/**` (счётчики/составы вкладок) | При витринных правках |

### 3.5 Источники переиспользования (не перепрогонять)

- **P0**: `plans/features/p0-save-init-ux/{persistence-audit.md, evidence/persist-fix/**, evidence/release-25890/acceptance/** (A/E/F, 17/17), review-persist-fix.md}` — контракт успеха, формат сбоев, real-DB цикл, payload-проверка.
- **B06**: `plans/features/asap8-v6-3-live-correction/requirements-map.json` (B06.1–B06.3, Playwright 42/42, REV-W3).
- **SOUL-1**: `plans/features/soul-1/**` (Prompt Registry/Style Policy/Factory Defaults; `review-w6-speech-ui.md`, `review-w10.md`, §5 18/18 V).
- **CFG-01/02A/02B/02C**: `plans/features/cfg/review-cfg-01.md` (§R1 — carry-in), `evidence/cfg-02a/README.md` (§R1/R5 — carry-in), `evidence/cfg-02b/**` (дельта-процедура), `review-cfg-02c.md` (честность/TZ-образец).

---

## 4. Зависимости и порядок

1. **Цепочка serial**: `CFG-02B → CFG-02C → CFG-03 → CFG-04 → …` (slice-graph; ADD-0.1). **CFG-02C в master, но не выкачен** — CFG-03 не стартует до его релиза+приёмки (включая закрытие `CFG-02C.5` RFL). Кандидат CFG-03 строится поверх master после этого поезда; CFG-03-дельту не подмешивать ни в один собираемый поезд.
2. **Что можно начать read-only сейчас** (до выката 02C): дизайн манифеста/метода (Ф1-draft), reuse-map (§2), carry-in список (§2), черновик R4-списка, прототип инвентарного скрипта (scratch), предложение по `write_scope` (§ниже). Правки repo-кода/карт — только после старта слайса (Ф0).
3. **Один писатель**: `services/param_catalog.py` + артефакты реестра + `web/app.js` — монополия CFG-03 в своём окне; CFG-04 (web/*) и CFG-07B (param_catalog + web/app.js) — строго после. Проверить чистоту дерева на старте (web/* и services/* сейчас чисты; параллельные лейны пишут только plans/доки).
4. **f8-пара / re-pin**: сегодня зелёная (29 passed); при старте — повторный прогон; кат. дельта — отдельным коммитом «catalog delta + re-pins» по процедуре §3.4 (прецедент `_cfg02b_reissue_f8.py`); Δ=0 не освобождает от re-pin SHA, если файл каталога правился.
5. **Прод-дисциплина**: live-проверки — безопасные фикстуры/малый объём (03.8), fail2ban; PET-режим — без новых обязательных согласований и device-чек-листов (AGENTS.md §PET).
6. **`write_scope` слайса — кандидаты на расширение** (финализирует PM одной правкой графа в Ф0, прецедент CFG-02C): добавить `config/settings.py`, `services/hot_config.py`, `services/config_cache.py`, `web/api/routes.py` (осознанный re-pin byte-freeze), `services/feature_gates.py`, `web/api/gates.py`, `plans/docs/param-registry-round1025.*`, `plans/docs/screen-map-round1025.md`, `tests/test_param_catalog.py`, `tests/test_round1025_f8_registry.py`, `tests/fixtures/round1025/{catalog_baseline,f8_baseline}.json`, `tests/test_ia_inventory_round1025.py`, `tests/test_frontend_tab_mapping.py`, `tests/test_budget_settings_round1019.py`, новые `tests/test_cfg03_*.py`, `tools/cfg03_*` (генератор манифеста) и `tools/ui_cfg03_*_e2e.py`; при кат. дельте — count-pin файлы по машинному списку процедуры. Уже в scope: `services/{param_catalog,chat_params,chat_settings_seed}.py`, `web/app.js`, `tests/test_chat_params.py`, `plans/features/cfg/evidence/cfg-03/**`.

---

## 5. Фазы (Ф0–Ф6)

**Ф0 — Возврат очереди.** Подтвердить выкат/приёмку CFG-02C (вкл. `CFG-02C.5` live preprod UI → V); синк master; f8-пара зелёная; PM: (а) обновить строки CFG-03 в карте — P0-алиасы в `reason`/`note` без ложных закрытий; (б) расширить `write_scope` (§4.6) и `--stage plan`; зафиксировать базу кандидата.

**Ф1 — Аудит-инвентарь (машинный).** Таблица 579 × [UI-экран/контрол; ui_visibility; группа/вкладка; ключ; тип; границы; Factory Default; scope/наследование; read/write API; storage; путь effective resolver; **declared vs VERIFIED** consumer; классификация (13 классов); гейт; тест/эвиденс; статус]. Статический проход: для каждого ключа — поиск фактических читателей (`hot.get("<key>"`, `get_chat_param(…, "<key>"`, `settings.<FIELD>`) по коду; метки: нет читателя / читается глобально при per_chat / перекрыт env / cached constructor state; отдельный ограниченный проход по env-only вне реестра (потолки, L133). Дизайн-фиксы — короткий раздел «Design» в `evidence/cfg-03/README.md`: формат манифеста (расширение схемы §3.4), эталон «verified consumer» (тест/спай/live; static grep — только кандидат), политика api-only/hidden (документированное отсутствие UI vs `UI_missing`), где задавать границы/единицы, честность `restart_required`, проверка restart/multiprocess в песочнице.

**Ф2 — RED.** Новые `tests/test_cfg03_*.py` (`TEST-LIFECYCLE: CONTRACT/REGRESSION owner=CFG-03`), кейсы-классы: (а) «UI_missing пуст/согласован» — каждая visible-запись рендерится (params-meta × группы × TABS × app.js; выбранные — Playwright e2e); reverse-check `REGISTRY − (rendered ∪ documented api-only/hidden) = ∅`; (б) консистентность ключ/группа/подпись/единицы/границы (carry-in CFG-01 R1 + CFG-02A R5); (в) effective-state/источник (`get_chat_param_sourced`); (г) negative-классы: лимиты (0/1/−1/мусор), флаги (OFF/ON по маршрутам), селекты (one-of), строки/промпты (доходят до payload-композиции); (д) честность отключённых/`restart_required`; (е) env-потолок диагностируем без секретов; (ж) пины: `PARAM_CATALOG_SHA256`, counts, `--check`, «без места=0». Прогон RED на базовом коммите (фиксация).

**Ф3 — IMPL.** Добить дырки: `UI_missing` → UI-место или документированный отказ; «сохраняется-но-игнорируется» → честность; отключённые/сироты → честная витрина/классификация; границы/единицы (carry-ins); `restart_required` честно. Кат. дельта — только по реальной нужде, **отдельным коммитом** «catalog delta + re-pins» (процедура §3.4); переименование ключей — не по умолчанию (ломающее; только с обоснованием и полным re-pin).

**Ф4 — GREEN + бласт-радиус.**
```
py -3 -m pytest tests/test_cfg03_*.py tests/test_chat_params.py tests/test_param_catalog.py -q
py -3 -m pytest tests/test_round1025_f8_registry.py tests/test_ia_inventory_round1025.py ^
  tests/test_frontend_tab_mapping.py tests/test_budget_settings_round1019.py -q
py -3 tools/gen_param_registry_round1025.py --check
node tests/js/<витринные JS-тесты>            # JS-sweep
.venv\Scripts\python.exe tools\ui_cfg03_*_e2e.py   # выбранные E2E на реальной MiniApp
```
При кат. дельте — перенос счётчиков/фикстур по процедуре + полный прогон пин-набора; при Δ=0 — минимум re-pin SHA.

**Ф5 — Evidence + Review.** `plans/features/cfg/evidence/cfg-03/{README.md (вкл. Design), manifest.* (R1), owner-summary.md (R2), failures.md (R3), manual-checks.md (R4), red-green.txt, e2e-log.json, ui/*.png}`; независимый Reviewer-аудит (03.10 — выборочная сверка манифеста с кодом/рантаймом, честность unverified) + регрессия; гейт `requirements_gate.py check --stage review --slice CFG-03 --candidate <sha>`.

**Ф6 — Release/live.** Поезд после CFG-02C; live preprod: hot-параметры без рестарта (.4), честность отключённых (.6), отрицательные тесты безопасного класса (.11), OFF/ON по маршрутам (.12); `--stage release --candidate <sha> --deployed-commit <sha>`; закрытие 19 строк только по фактам (непроверенное остаётся видимым — 03.10).

---

## 6. Риски

| ID | Риск | Митигация |
|---|---|---|
| R1 | **Кат. инкремент/re-pin**: правка `param_catalog.py` ломает SHA-пин; дельта — счётчики + фикстуры + ~50 файлов | Отдельный коммит «catalog delta + re-pins» по процедуре §3.4; Δ=0-путь: только re-pin SHA; переименования — не по умолчанию |
| R2 | **Объём/раздувание**: 579 × 13 классов × цепочка — не превратить в 579 ручных эссе и не выйти в редизайн | Машинный манифест + аннотации; class-based негативы + выбранные live; честный `unverified`; фиксы — только аудит-обусловленные (CFG-04/05/07 — владельцы остального) |
| R3 | **Пересечение с CFG-04 (web/app.js) и CFG-07B (param_catalog)** | Serial-очередь; один писатель; CFG-03 не трогает формы/save/nav/fullscreen/стекло; оставить каталог/витрину в стабильном состоянии |
| R4 | **«HTTP 200 = доказательство»** и грубая колонка `runtime_consumer` (плейсхолдер) как эвиденс | Запрещены источником (L121); эталон verified consumer — тест/спай/live; declared ≠ verified фиксируется в манифесте |
| R5 | **Стоимость live**: 03.8 запрещает массовые платные прогоны | Sandbox-first; live — безопасные фикстуры, малый объём; выбранные E2E; R17 |
| R6 | **f8-пара/релиз-дисциплина**: смешение с чужими лейнами/поездами | Пара сегодня зелёная; перепрогнать на старте; дельта — отдельным коммитом; не подмешивать в поезда |
| R7 | **Алиасы**: повторный прогон P0/B06/SOUL или ложное закрытие строк | §2: reuse-map; строки закрывать только по полному покрытию; 100% не объявлять (03.10) |
| R8 | **Restart/multiprocess** (прод = один процесс) | Проверки в песочнице (2 воркера/рестарт); что нельзя live — честно в манифесте/сводке |
| R9 | **R4-список**: владельческие/живые события | Список + точные сценарии; PET: device-чек-листы владельца не создаются, агентские проверки — агентам; не блокировать очередь |
| R10 | **Старые каталоги/env-потолки** вне реестра могут размыть знаменатель | Ограниченный отдельный проход (L127/L133); классификация «документированное env-only» vs `UI_missing`; без расширения знаменателя без нужды |

---

## 7. Guardrails («не делать»)

- Не переигрывать P0/B06/SOUL-1/CFG-01/02A/02B/02C: подтверждённые трассы переиспользуются, не перепрогоняются; не пересобирать Prompt Registry/Style Policy/Factory Defaults.
- Не выдавать HTTP 200 / значение в PG / статическую колонку `runtime_consumer` за доказательство работоспособности; не объявлять 100% при непроверенных (03.10).
- Не трогать формы/save/dirty/клавиатуру (CFG-04), навигацию/fullscreen/логотип/safe-area (U01/U07/HOTFIX), стекло/полигон (U08/SOUL-17/CFG-05).
- Не менять боевые ключи/квоты и не запускать массовые платные генерации (03.8); не раскрывать секреты (R17).
- Кат. дельта/переименования — только отдельным коммитом с полным re-pin-чеклистом; `routes.py` (byte-freeze) — только осознанным re-pin.
- Не открывать Human Gate: решения CFG-03 — технические; владельческое согласование — только если реально понадобится вывод параметра из UI (продуктовый выбор), точечно.

---

## 8. Точное действие Orchestrator

1. Дождаться выката/приёмки **CFG-02C** (закрытие `CFG-02C.5` RFL) — это шлагбаум старта CFG-03; параллельно допустим read-only Ф1-draft (§4.2).
2. При старте слайса: **PM-Ф0** — обновление строк CFG-03 по P0-алиасам (§2, без ложных закрытий), расширение `write_scope` (§4.6) + `--stage plan`; перепрогон f8-пары; фиксация базы кандидата.
3. Builder по фазам §5 (Ф1→Ф6) с монополией на `param_catalog.py`/артефакты реестра/`web/app.js`; без параллельных писателей.
4. После GREEN — evidence `cfg-03/**` (R1/R2/R3/R4), независимый Reviewer (03.10), review-гейт; затем релиз-поезд и live-проверки §5/Ф6; закрытие 19 строк только по фактам.

*Документ подготовительный; единственный источник истины — `plans/features/cfg/requirements-map.json` + гейт `requirements_gate.py`. В этом лейне карты, код, `current_task.md` и прод не изменялись; SSH не использовался. Единственные записи — этот документ и три одноразовых read-only пробника в managed scratch.*
