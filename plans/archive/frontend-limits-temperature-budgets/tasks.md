# Задачи: frontend-limits-temperature-budgets (ТЗ 3 раунда 10.4)

Раунд 10.4, фича B (T-990…T-1005). Стадия старта — PLANNED; spec.md @Architect.
ТЗ владельца (п.3, три под-пункта):
1. Бюджеты «Прямой чат» (limits_chat_budgets + гейт CHAT_CONTEXT_BUDGETS_ENABLED)
   → флаг ВКЛ/ВЫКЛ **per-чат**; для чата -1002661910336 — **ВЫКЛ**.
   Связь с F-15 (recon: direct-chat-sandbox-budget): у -1002661910336 НЕТ
   BYOK-ключа, глобальный ключ лимитирован 25 req/сутки → экономия токенов
   через выключение бюджетов/управление контекстом важна; флаг решает проблему budget.
2. Температура (limits_temperature: CHAT_TEMPERATURE_PRECISE/BALANCED/CHATTY +
   CHAT_TEMPERATURE_PRESET_DEFAULT) → **выпадающий список** (новый виджет).
3. «Имена людей» (limits_user_aliases / SUMMARY_ALIASES, KV-editor) → отдельный
   раздел + настраиваемость **per-чат/ЛС**.
   ПЕРЕСЕЧЕНИЕ с F-6 `user-aliases-admin` (см. конфликт-матрицу в backlog:
   остаточные задачи F-6 → аудит каскада уходит в фичу H, живой эффект +
   регресс — сюда; сама F-6 в основном в master (5d011d2), статус — см. backlog).

Отправная точка (рекон tma-structure-10.4, HEAD 1410a68):
- Гейт читается как `settings.CHAT_CONTEXT_BUDGETS_ENABLED` в
  direct_chat_service.py:1011 (НЕ hot.get!) — перенести на per-chat-aware
  резолв; остальные ключи бюджета: :996-1014 (доли), :1498-1522 (карта),
  :1622 (RAG-контекст), :1684-1880 (контекст/тред), :1726 (L2).
- Per-chat резолв существует: `get_chat_param_defaulted(chat_id, key, fallback)`
  (chat_params.py:349-372); hot_chat-кэш (chat_params):200+. Режим «группа →
  только при override», «ЛС → свой дефолт» — прецедент `chat_summary_enabled`
  (chat_params.py:388-403, F-14).
- Каталог: виджеты только ""|"keyvalue" (`ParamSpec.widget` :88; проверка
  test_widget_keyvalue_on_summary_aliases — «others_with_widget == []» — СЛОМАЕТСЯ,
  обновить). `progressive_level` :89-92.
- SUMMARY_ALIASES: `ParamSpec` строка :884 (json, widget='keyvalue',
  limits_user_aliases); AliasResolver (services/summary_aliases.py) — глобальный
  кэш: hot.get('limits.summary_aliases') (web/api/chat_lore.py:555-556).
- Режим per-чат override: POST /api/config с X-Chat-Id → chat_params.overrides
  (F-7); KV-редактор (widget keyvalue) в generic-рендере — уже есть.

## A. Бюджеты: per-чат флаг [@Architect/@Builder]

- [ ] T-990 — указать в каталоге гейт-ключ: `flags.chat_context_budgets_enabled`
  (группа flags_chat_behavior) — карточка «Бюджеты контекста direct_chat»:
  перевести из группы «Поведение в чате» в «Прямой чат: бюджеты токенов»
  (limits_chat_budgets) — ТОЛЬКО перенос рендер-группы (pg-ключ/семантика без
  изменений; REGISTRY 383 — без изменений). **AC-B1:** по каталогу группа ключа
  == limits_chat_budgets; тест catalog-сверки (локация pg-ключа) обновлён.
- [ ] T-991 — резолв гейта per-чат: замена `settings.CHAT_CONTEXT_BUDGETS_ENABLED`
  на per-chat-aware чтение (hot_chat-раскрытие: async `chat_param(chat_id, key,
  default)` в chat_params; для групп — override → значение; нет override → текущий
  hot.get-путь; сохранить байт-в-байт поведение для чатов без override).
  **AC-B2:** юнит-тесты: (1) без override — поведение как сейчас (hot.get);
  (2) override true/false — взятие из overrides; (3) DM-скоуп — свой дефолт
  (по образцу chat_summary_enabled; дефолт для ЛС = глобальное значение;
  переопределением юзер правит свой ЛС).
- [ ] T-992 — пер-чат override для -1002661910336 = ВЫКЛ: значение
  `chat_params.overrides["flags.chat_context_budgets_enabled"] = false`
  (через ensure_scope_profile + set_chat_params паттерн; бэкфил-скрипт
  `scripts/backfill_104_chat_flags.py` или сид — решение @Architect).
  **AC-B3:** скрипт идемпотентен (повторный прогон не меняет остальные override);
  глобальные дефолты/другие чаты не тронуты; запись в chat_lore_history/аудит
  опционально (по паттерну F-7).
- [ ] T-993 — READ-путь аудит: пометить новые read-пути (chat_param / hot_chat)
  для F-5 config-read-path-audit (список точек в AC-комментарии).
  **AC-B4:** в tasks.md F-5 или отчёте фичи — реестр новых read-путей
  (key/файл/строка) для последующего аудита.

## B. Температура: виджет select [@Builder]

- [ ] T-994 — каталог: `ParamSpec.widget` расширить до "select" + новое поле
  `select_options: tuple[str,...] | None` (например ("precise","balanced",
  "chatty")); для CHAT_TEMPERATURE_PRESET_DEFAULT — widget="select", options=
  пресеты. Остальные поля температуры (float-значения) остаются обычными
  (в расширенных при желании). **AC-B5:** spec.select_options None по умолчанию;
  старые записи без widget — как раньше; REGISTRY 383 (без роста — поле/виджет
  не добавляет ключей); test_widget_keyvalue_on_summary_aliases обновлён
  (разрешённые значения widget: "", "keyvalue", "select").
- [ ] T-995 — API /api/config: отдавать `select_options`/widget-select в items
  (web/api/params.py или config.py — точка, где формируются item-поля;
  решение @Architect); валидация POST: значение пресета в допустимых (отклонение
  422 иначе, без изменения типа поля). **AC-B6:** GET config отдаёт
  select_options; POST с неизвестным значением → 422; POST с валидным — 200 и
  персист.
- [ ] T-996 — рендер: в generic-шаблоне (index.html basic/advanced ветки)
  для `widget === 'select'` — `<select v-model="item.value">` c опциями из
  select_options (ключ-значение: value = опция, label — человекочитаемый:
  «Точный / Сбалансированный / Болтливый» — заголовки пресетов из каталога);
  счёт сохранения — как у существующих полей (кнопка Сохранить/авто).
  **AC-B7:** на вкладке «Лимиты» (группа «Температура ответов») — выпадающий
  список вместо текстового поля; float-поля пресетов по-прежнему поля;
  `node --check` clean; маркер select в index.html (позитив) + отсутствие
  старого input для этого ключа (негатив) — тест-маркеры обновлены.
- [ ] T-997 — сохранение select: submit-путь `saveConfigItem` — для widget
  "select" значение = строка (без парсинга JSON/числовых кастов — str).
  **AC-B8:** изменение пресета → POST /api/config → toast «Сохранено»; reload
  отдаёт выбранное значение.

## C. Имена людей: отдельный раздел + per-чат/ЛС [@Builder]

- [ ] T-998 — вынос группы limits_user_aliases с «Лимитов»: НОВАЯ config-вкладка
  TAB_PEOPLE_NAMES ("people_names", «Имена людей», menu 'chat_profile',
  sources: limits {limits_user_aliases}); from TAB_LIMITS except +=
  {limits_user_aliases}. **AC-C1:** `tab_group_ids("people_names")` ==
  {limits_user_aliases}; зеркало TABS + меню; на «Лимитах» ключа больше нет;
  эталон REGISTRY 383/71/359 без изменений.
- [ ] T-999 — per-чат/ЛС алиасы (резолв): AliasResolver-точки перевести на
  per-chat-aware чтение: web/api/chat_lore.py:555-556 (список участников),
  services/user_relations.py (каскад name), bot.py:570-571 (инжект
  `<user_relations>`, RelationsService.aliases — гейт summary_enabled не трогать!)
  — через единый хелпер (`chat_param(chat_id,'limits.summary_aliases', hot.get…)
  / AsyncAliasResolver). **AC-C2:** (1) группа: алиасы — override чата →
  иначе глобальные (поведение других чатов не меняется); (2) ЛС: свой резолв
  (юзер задал → свои; не задал → глобальные); (3) `flags.summary_enabled`
  гейт-семантика (F-14) не регрессирует: каскад имён в списке участников
  НЕ зависит от summary_enabled (прецедент Hotfix-R10 :551-554).
- [ ] T-1000 — KV-редактор алиасов в per-chat override-режиме: карточка
  «Имена людей» на вкладке people_names — отображать текущие (global+chat)
  значения; для активного чата — per-chat override (кнопка «↪ глобальное» +
  сохранить в чат — паттерн generic-переопределений; widget keyvalue уже
  поддерживает). **AC-C3:** для -1002661910336/ЛС: сохранение алиаса уходит в
  `chat_params.overrides` (X-Chat-Id); кнопка сброса возвращает глобальный;
  видимость правок по canEditConfig (DM — is_dm_owner → можно).
- [ ] T-1001 — каскад-тест (F-6-аудит переноса): тесты каскада
  `alias → nickname → username → id` для AliasResolver + резолв имени
  участника в web/api/chat_lore.py (уже частично test_relations_service;
  расширить: alias-приоритет, «id никогда имя» (R16), username-без-«@».
  **AC-C4:** набор тестов — как в реконе ТЗ 9 (не ломать relations/R16).

## D. Регресс и маркеры [@Builder]

- [ ] T-1002 — test_frontend_tab_mapping.py: composition people_names,
  обновлённые исключения «Лимитов»; зеркало TABS (except/groups) — маркеры.
- [ ] T-1003 — test_webapp_nav_disclosure_ui.py / test_webapp_*_ui.py: маркеры
  новой вкладки, select-рендера, отсутствие старых строк (limits_user_aliases
  на Лимитах); обновление по MED-022-прецеденту.
- [ ] T-1004 — регресс-прогоны: полный pytest (baseline 4831 + новые) — 0 failed;
  `node --check web/app.js` clean; `git diff --check` чист.
- [ ] T-1005 — live-акт (после деплоя): алиас из админки → каскад имени
  участника/саммари/граф использовать новое имя (проверка через /debug_config
  + живой чат; НЕ историо-график — только новые записи); отметить в отчёте
  фичи (перенос с F-6 «Реальный эффект»). **AC:** подтверждение — в отчёте
  @Builder + пункт «ждёт человека» → владельцу.

**Критерии приёмки ТЗ 3 (сводные):**
- Флаг бюджетов: per-чат тумблер, у -1002661910336 — ВЫКЛ (до деплоя — сид),
  другие чаты — без изменений; дефолты не тронуты; связь с F-15-диагностикой
  (25 req/сутки) описана в spec.
- Температура: выпадающий список на «Лимитах» (базовый рендер: пресет-дефолт)
  + float-пресеты в расширенных; невалидное значение → 422.
- Имена людей: отдельный раздел; редактирование per-чат и ЛС; каскад имени
  не ломает R16 (id никогда) и summary_enabled-гейтинг поверхностей.
- ЭТАЛОН КАТАЛОГА: REGISTRY 383 / 71 / Settings 359 — без изменений; MED-017
  (тест-сверка Settings↔REGISTRY) — как есть (не добавлен, вне скоупа).
- SQLite v8, порядок роутеров bot.py, каноны промптов — без дифов.
