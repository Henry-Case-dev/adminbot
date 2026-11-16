# MOD-ACL-UX-01 — M3 design freeze

**Статус:** FROZEN. Источники: owner input §§2, 3, 5, 6, 8, 10–12; `m0-baseline.md`; M2 candidate `3b1ba3b2`; `lesson-strategy-contract.md`. Продуктовый код не изменён.

## 1. Workspace модуля

* Маршрут: `Каталог → Модуль → вкладка`; scope-selector (`Весь бот`/чат) общий для всех вкладок. Последняя вкладка запоминается только для этого модуля и scope.
* Реальные базовые табы: **Обзор / Настройки / История**. Дополнительные (`Промпты`, `Модели и провайдеры`, `Лимиты`, `Расширенные`) показываются только если соответствующая группа есть в `ModuleSpec.settings_groups`/каталоге и есть право read.
* **Обзор** не является прокладкой: компактные state-поля, последние события и адресные ссылки на настройки. Если у модуля нет живых данных, обзор всё равно показывает доступные параметры и честный `нет данных` с моментом проверки; при отсутствии даже этого открывается первая содержательная вкладка.
* **Настройки:** живые поля `param_catalog` по группам, сохранение через существующий config/chat_params путь; источник effective и область изменения рядом с контролом.
* **История:** события/изменения с `created_at`, причиной, источником, `run_id` если есть; данные из существующих history/events API, не новый журнал.
* Обязательные поля Обзора: `Состояние`, `Последняя попытка`, `Последнее сообщение`, `Пропуски с причинами`.
  * `Состояние` = capability snapshot M2: `desired`, `effective_runtime`, `ready`, `observed_at`, `last_activity_at`, `reason_code`, `source`, `chat_state`, `can_read/can_edit`.
  * `Последняя попытка` = существующий `status_service.intent_snapshot`/`experience_snapshot` и их `last_action`/job `status`, timestamp, reason; для конкретного модуля — его `status_source` из `ModuleSpec`.
  * `Последнее сообщение` = последнее реально зарегистрированное событие/ledger выбранного scope (не heartbeat); источник модуля и `created_at` обязательны, неизвестное не заменяется нулём.
  * `Пропуски` = `intent_snapshot.last_skip` и счётчики/причины событий выбранного окна; показывать code и русский label, raw detail — по раскрытию.

## 2. Каталог 21 карточки

* Канонический список и подписи приходят только из `module_registry.registry_for_frontend()`/`GET /api/config.modules`; новый JS-реестр запрещён. Группа карточек: **диалог и интеллект** (Ответы, Диалог, Фактчек, Поиск, Анализ, Генерация изображений/Vision, Транскрипция, Выжимка видео, Скачивание медиа); **память и опыт** (Память/Истории и эпизоды, Опыт и уроки, Векторная память, Характер/SelfModel, Случайность, Сводки); **проактивность** (Инициатива, Мем-ветка, Сон/глубокий сон, Ностальгия); **политики и контекст** (Бюджеты, Время). Ровно 21 видимая карточка подтверждается live-каталогом перед рендером; скрытые подмодули не становятся карточками.
* `classification=product_module/submodule`: пользовательская возможность. Её карточка показывает управление по capability и scope; submodule ведёт в рабочую поверхность родителя, не создаёт дублирующей навигации.
* `classification=infrastructure/maintenance`: shared-инфраструктура (DB, scheduler core, Embeddings API/index, транспорт, защита секретов) не получает фиктивный master-toggle. Карточка показывает `Инфраструктура`, `Общий сервис`, readiness/health и ссылку на использование; per-chat capability (например, `Использовать поиск памяти в этом чате`) управляется отдельно. Выключение чата не останавливает shared worker/index для других чатов.
* Карточка без master параметра не рисует disabled/fake switch и не говорит «выключено»: явный текст `Общий сервис. Отдельного переключателя нет`; если существует законный chat-use capability — показывает его tri-state.

## 3. Tri-state

* В CHAT точный сегментированный control: **Наследовать / Включить / Выключить**. GLOBAL остаётся ON/OFF. Рядом всегда раздельные бейджи `Желаемое`, `Готовность`, `Фактическая работа`.
* `Наследовать` удаляет только `chat_params.overrides[key]` (или соответствующий gate через адаптер), запись `INHERIT`; `Включить`/`Выключить` пишут explicit bool. Используются существующие `chat_params.set_chat_params` и `PUT /api/chat/{chat_id}/gates` (`feature`, `enabled: true|false|"inherit"`), с `expected_updated_at`/версией.
* При stale token/`409 conflict`: не показывать «Сохранено»; заблокировать только группу, перечитать серверный snapshot, показать `Настройка изменилась в другом окне`, diff `ваше/на сервере`, кнопки `Применить снова` и `Оставить серверное`. Никакого молчаливого overwrite и двойного POST.
* `desired=ON` + `ready=true`, но нет свежего `observed_at`/события: **«Включён · работа ещё не подтверждена»** (жёлтый/нейтральный, не зелёный). `desired=OFF`: **«Выключен»** независимо от readiness. `ready=false`: **«Включён · сейчас не работает»** + точная причина (`permission_denied`, `consent_required`, `emergency_block`, `gate_conflict:<name>`, `<group>_missing:<name>`). «Нет права» никогда не стилизуется как OFF.

## 4. Status freeze

* Порядок: health (`/api/status`: bot/server/version/errors/uptime) → пять живых лент **Факты / Убеждения / Парадигмы / Эволюция характера / Досье** → компактная память → Observer → сон/последний вызов/бюджеты → аналитика и опыт.
* Все пять используют один `v-sfeed`-подобный компонент: pause on focus/drag, wheel/swipe, reduced-motion, detail с датой события, provenance, scope и source link. Досье переносится из нижнего блока; источник только `/api/oversight/dossier_feed`, дубль запрещён.
* Память: `status_service` memory snapshot + `/api/memory/overview` (`expired_total`, `needs_recheck`, `superseded_total`, `now_ts`) и доступные 24h/7d данные; `0` не подменяет 403/503/unknown.
* Observer: `/api/memory/initiative-vitality?chat_id&hours` и `/api/memory/intel-funnels`. KPI подписывать `24 ч`/`7 д`/`всего`/`сейчас` и timestamp. Визуальный funnel разрешён только при общей когорте/окне/ID; иначе независимые счётчики без процентов и стрелок. Развести `mca_intents` от ledger публикаций; причины молчания — максимум 3–5 реальных причин, остальное раскрытие.
* Последний вызов: использовать только достоверную telemetry (`/api/status` LLM cards/`llm_stats`, analytics `llm_call_span` если доступен). Есть данные: время, модуль, модель, latency, tokens, стоимость только при известной цене, error и trace. Нет данных: контентная компактная строка `Последний вызов: нет зарегистрированных данных` + checked-at/reason; image event не называть LLM-вызовом.
* Опыт: существующий `status_service.experience_snapshot` и `/api/memory/intel-funnels` (`semantic_lag`, `last_application`, events); компактная лента **под своими индикаторами**, опыт и уроки различаются, статус/доказательства/provenance видны. Причина нуля: `нет подходящих доказательств`/`backlog`/`модель недоступна`/`ожидает решения`, не fake success.

## 5. «Роли и права»

* Самостоятельный route/deep-link `Доступы → Роли и права`, Back; не модальное дерево. Слева роли, справа searchable tree `Раздел → Модуль → Группа → Параметр`; поиск по русскому label и `pg_key`, фильтр «Только изменённые», effective Actor+Scope.
* Наследование показывает `роль по умолчанию → чатовый грант/override → effective право`, кто/когда изменил. Read/write/run/delete/rebuild/restart/test/export/history разделены. Preview `Проверить доступ` read-only и показывает путь до backend guard; preview не выдаёт секреты и не меняет actual grant.
* Запись использует текущие `bot_roles`, `bot_admins`, `chat_admins`, `param_permissions`, `services/roles.py`, `services/access.py`, `/api/access/*`; **второй ACL/roles storage не создаётся**. Legacy keys не удаляются автоматически.
* `409`: сохранить dirty draft локально, перечитать сервер, показать конфликтующие ключи и выбрать merge/сервер/повтор; не перетирать чужое изменение. Перед публикацией любого изменения и перед выдачей результата долгого защищённого запроса повторно проверить ACL и scope; при отзыве скрыть уже загруженные защищённые данные.

## 6. Русская редактура (плохо → хорошо)

* «Master toggle» → «Переключатель для чата».
* «Global OFF» → «Общий режим: выключен (новые чаты наследуют)».
* «Override» → «Отдельная настройка этого чата».
* «Enabled» → «Включён»; «enabled but not verified» → «Включён · работа ещё не подтверждена».
* «Provider missing» → «Не настроен провайдер речи».
* «No data» → «Нет зарегистрированных данных за выбранный период».
* «0 intentions = broken» → «Намерений нет; публикации считаются отдельно».
* «Нет доступа» для 503 → «Сервис временно недоступен; последняя успешная проверка: …».
* «Embeddings toggle» → «Векторная память — общий сервис; здесь настраивается использование в чате».
* «Сохранено» до ответа API → «Сохраняем…», после ответа → «Настройка сохранена».

## 7. Серилизация M4 и приёмка

* Файлы и порядок: **M4A** `web/app.js`/маршрутизация и каталог + workspace/tri-state (сначала зафиксировать DTO и loading/error/409); **M4B** Status/feeds/observer/last-call/experience (использовать существующие endpoints); **M4C** route матрицы ролей и ACL interactions. Shared `module_registry`/ACL contracts и `web/app.js` — SERIALIZE; тесты и редактура могут быть READ_ONLY_PARALLEL. M4B/M4C BLOCKED_BY M4A DTO/shell; не смешивать крупные UI-правки.
* Reviewer обязан проверить реальные экраны Playwright **и** реальный браузер: desktop 1440/1280, tablet 768, mobile 390/320; GLOBAL/CHAT, INHERIT/ON/OFF, `GLOBAL OFF + CHAT ON`, stale 409, ready=false, observed отсутствует, 403/503, пустой/деградировавший Status, длинные названия и reduced-motion. Для каждого: screenshot + network/API snapshot, отсутствие горизонтального overflow/пустых прокладок, рабочие tab/deep-links, поздний ответ не смешивает чаты. Тесты без визуального прохода недостаточны.

M3 DESIGN FROZEN — риски: (1) честное разделение desired/effective/ready/observed без ложного OFF; (2) observer funnel без псевдоконверсий при разных окнах; (3) полноценная ACL-страница без второго реестра и с безопасным 409/revocation flow.

---

## 8. Дополнение 2026-11-16 — design revision 2 (актуальная)

Разделы §1–§7 выше сохранены как история первой редакции. Действующая design specification —
`design-m3-2026-11-16.md`; полный copy inventory — `copy-inventory.md`. Что изменено и почему:

1. **§2 (состав 21 карточки) заменён.** Список названий первой редакции не совпадал с фактическим
   каталогом 2.58.205 (`m0-baseline.md` §8, `evidence/m0/mac-m0-01.md` §2.4). Канон — 16 static
   `mod_*` + 5 registry-only (`stories`, `character`, `experience`, `random`, `embeddings`);
   «Диалог», «Анализ», «Мем-ветка» отдельными карточками не создаются. Карточки сгруппированы:
   Общение / Память / Автономность / Медиа / Системные.
2. **Каталог — серверный.** `MODULES` в `app.js` удаляется; 21 видимый `ModuleSpec` (+ hidden
   `factcheck_temporal`) становятся единственным источником. `WORKSPACE_TABS` остаётся
   presentation-map вкладок, не реестром модулей.
3. **Scope исправлен по фактическому runtime:** `per_chat` без master-AND у summary, sleep,
   nostalgia, budgets, images, vision, experience (7); ещё **12** модулей требуют per-chat adapters
   (M2.1), включая initiative (master-AND с `flags.initiative_enabled`) и random (shared QRNG).
   Это блокирующая зависимость, а не UI-деталь.
4. **Добавлены wireframes** каталога, малого/сложного/инфраструктурного модуля и страницы «Время»,
   пять осей состояния, responsive, token mapping, Visual Preservation Map и точные UI/API-поля.
5. **Copy inventory** полный, с сохранением «чекапа», пользовательских промптов и owner-описаний
   Историй/Векторной памяти/Опыта/Случайности.
6. **§4 (Статус) и §5 (права) не переписаны:** их концепция остаётся frozen; revision 2 добавляет
   только карту экранов/навигацию и границы данных. M4B/M4C реализуют их как раньше.
7. **Новые конфликты/риски:** дубли `experience/stories/character/random` на родительских
   страницах (один write-point), `keys_llm` на странице embeddings (фильтр embedding-ключей),
   `nostalgia` master precedence, live-флаг `IMAGE_MODULE_CARD_ENABLED`, MEMORY-08/VMQ/SELF-DIAG
   границы. Product-код не менялся; статусы карты не менялись.

---

## 9. Дополнение 2026-11-16 (rev2.1) — уточнения после независимого ревью

Раздел §8 сохранён как история rev2. Действующая спецификация — `design-m3-2026-11-16.md`
(revision 2.1). Ниже — только то, что уточняет/заменяет формулировки §1–§8; продукт и карта
статусов не менялись.

1. **Порядок каталога нормативен через `catalog_order`:** §2 (группы) и порядок регистрации
   больше не конкурируют. `catalog_order` — целое 1…21, уникальное; DOM обязан совпадать с ним.
   Порядок регистрации в коде на рендер не влияет (design §3.2).
2. **«Расширенные» (MAC-S5-TAB-07) — не отдельная вкладка.** В `bca18c1e` это раскрываемая зона
   `advancedItems(grp)` внутри существующей вкладки; отдельная вкладка создала бы второй дом для
   технических параметров. Зона обязательна там, где фактический `advancedItems(grp) > 0`
   (`resolve_progressive_level(spec) == "advanced"` хотя бы у одного видимого параметра группы);
   таких карточек **15/21** (`sleep`, `nostalgia`, `initiative`, `character`, `experience`, `random`
   плюс `summary`, `direct`, `factcheck`, `search`, `transcribe`, `video_summary`, `vision`, `checkup`,
   `budgets`), у остальных 6 зона не рисуется. Существующие зоны сохраняются (design §2.4).
3. **«История/События» (MAC-S5-TAB-06) — вкладка `history` только при реальном источнике.**
   Источник именованный, при 403/503/`available:false`/пустоте вкладки нет; где уже есть
   собственный событийный таб (`inspector`, `publications`/`diagnostics`, инфраструктурные
   `События`), второй не создаётся. Перечень источников — design §2.4.
4. **Пять осей + `source`.** `source` — атрибут `desired`, не шестая ось (design §5.1).
5. **Имена DTO — по одному на ось:** `runtime_gate` (одно имя в `ModuleSpec` и DTO; `scope` —
   только контекст global/chat),
   `permissions{can_read,can_edit}` — единственное место прав, `state` — единственное имя осей
   (`usage_state` не вводится; для инфраструктуры — `service_state`). Design §6.2.
6. **M2.1 — отдельный backend-срез, обязательный предшественник M4A** (решение Оркестратора):
   12 модулей (`initiative`, `direct`, `factcheck`, `search`, `web`, `transcribe`,
   `video_summary`, `media_download`, `checkup`, `stories`, `character`, `random`); до его закрытия
   M4A не рисует их CHAT-контролы, interim disabled-контрол не нужен. 8 существующих
   `ModuleSpec.runtime_gate` (`initiative`, `stories`, `character`, `random`, `factcheck`,
   `vision`, `nostalgia`, `sleep`) исправляются на `per_chat` в M4A после M2.1. Design §12.2/§12.5.
7. **Оболочка:** sidebar 190–220; контентная колонка = viewport − sidebar − 48 (на 1440 при
   sidebar 220 это 1172, не 1440); сетка `minmax(280px,1fr)` с потолком 4 → 4/3/2/1; state-чипы
   несут иконку и текст, цвет вторичен (design §4.1/§8/§9). Дубль заголовка «Модули» устранён:
   заголовок один, в topbar (design §3.3).
8. **Copy:** шапка каталога/фильтры/счётчик — `copy-inventory.md` §10; «Статус»/«Права» — границы
   в `copy-inventory.md` §11 (frozen §4/§5 + редактура §6, без второго инвентаря).
9. `VERIFIED` не заявляется; ревизия 2.1 закрывает замечания ревью, но требует повторного
   независимого ревью.
