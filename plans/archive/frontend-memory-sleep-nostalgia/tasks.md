# Задачи: frontend-memory-sleep-nostalgia (ТЗ 4 раунда 10.4)

Раунд 10.4, фича C (T-1006…T-1017). Стадия старта — PLANNED; spec.md @Architect.
ТЗ владельца (п.4): «Память и RAG» → «Память»; «Сон» и «Ностальгия» — в
ОТДЕЛЬНЫЕ разделы (не в «Памяти»).

Отправная точка (рекон tma-structure-10.4, HEAD 1410a68):
- TAB_MEMORY_RAG (id 'memory_rag', label «Память и RAG», menu 'ai') — sources:
  limits {limits_memory, limits_graph} + flags {flags_memory} + memory **все**;
  группы памяти: memory_infinite, memory_dream (Синтез (сон)), memory_nostalgia.
- CONFIG_TAB_TITLES :1362-1369 (сервер) + TABS label (app.js:34-40).
- `_ADVANCED_GROUPS` (param_catalog.py:58-61) = {limits_memory, limits_graph,
  flags_memory, memory_infinite, memory_dream, memory_nostalgia} → ВСЕ записи
  групп advanced (заметка: DREAM_ENABLED/NOSTALGIA_ENABLED сейчас advanced —
  после реструктуризации вкладки с полностью advanced-группой выглядят пустыми
  (см. фичу D — свёрнутый по умолчанию аккордеон!) → нужна переразметка
  базовых выключателей).
- Гейты пер-чат: `chat_params.gates.{dream,nostalgia}` (F-10) — для сон/ностальгия
  ОСТАЮТСЯ; карточки «Тяжёлые фичи» в modules_feats — переходы (setTab) на
  новые вкладки при необходимости.
- Эталон: REGISTRY 383 / 71 группа / Settings 359 (правки — ТОЛЬКО переносы
  вкладок/разметка; новых ключей/групп НЕТ).

ЦЕЛЕВОЕ СОСТОЯНИЕ (дефолт, уточнение у @Architect):
- Вкладка «Память» (id остаётся `memory_rag` — переименовать label-поля/титулы,
  id менять НЕ обязательно; если меняем id — синхронно: TABS app.js + маркеры):
  sources limits {limits_memory, limits_graph} + flags {flags_memory} +
  memory {memory_infinite}.
- Новая config-вкладка «Сон» (id `memory_dream`, menu 'ai'): memory {memory_dream}.
- Новая config-вкладка «Ностальгия» (id `memory_nostalgia`, menu 'ai'):
  memory {memory_nostalgia}.
- Разметка: базовые = рубильники (DREAM_ENABLED, NOSTALGIA_ENABLED,
  NOSTALGIA_LAYER_A_ENABLED); advanced = пороги/окна/бюджеты/анти-спам — явной
  разметкой (вручную), _ADVANCED_GROUPS для memory_dream/memory_nostalgia
  снимается (иначе вся вкладка уходит в аккордеон и пустеет после фичи D).

## A. Каталог: вкладки и разметка [@Architect/@Builder]

- [ ] T-1006 — TAB_RULES: TAB_MEMORY_RAG-источники → (LIMITS, {limits_memory,
  limits_graph}) + (FLAGS, {flags_memory}) + (MEMORY, {memory_infinite});
  новые записи TAB_MEMORY_DREAM ("memory_dream") и TAB_MEMORY_NOSTALGIA
  ("memory_nostalgia") с (MEMORY, {memory_dream}) / (MEMORY, {memory_nostalgia}).
  **AC-C1:** `_TAB_BY_GROUP`-конструктор без ValueError; `tab_group_ids` для
  трёх вкладок — ровно по целевым наборам; категория memory покрыта целиком
  (infinite+dream+nostalgia), без дублей.
- [ ] T-1007 — переименования: CONFIG_TAB_TITLES[TAB_MEMORY_RAG] → «Память»;
  добавлены «Сон»/«Ностальгия»; label зеркала app.js; MENU-теги — 'ai'.
  **AC-C2:** титулы в каталоге/фронте синхронны; тест-маркеры обновлены
  (test_frontend_tab_mapping + test_webapp_nav_disclosure_ui).
- [ ] T-1008 — `_ADVANCED_GROUPS`: убрать {memory_dream, memory_nostalgia};
  группам задать явную разметку в `resolve_progressive_level` и/или
  ParamSpec.progressive_level: basic — гейт-флаги (DREAM_ENABLED,
  NOSTALGIA_ENABLED, NOSTALGIA_LAYER_A_ENABLED); advanced — всё остальное
  (окна/пороги/бюджеты/анти-спам). **AC-C3:** у каждой записи memory_dream/
  memory_nostalgia basic-группа ≥1 (вкладка не пуста без раскрытия);
  verify: для группы «Синтез (сон)» basicItems ≥ 1; то же для «Ностальгии».
- [ ] T-1009 — настройки-«Тяжёлые фичи» (modules_feats): переходы на новые
  вкладки «Сон»/«Ностальгия» (setTab) — если есть setTab-переходы на
  memory_rag — актуализировать; гейты gates (opt_in/dream/nostalgia) —
  без изменений. **AC-C4:** маркеры setTab('memory_dream'|'memory_nostalgia').

## B. Фронт [@Builder]

- [ ] T-1010 — TABS-зеркало (app.js:18-72): три config-вкладки с новыми
  sources/except-источниками; старый порядок (memory_rag → 'ai') сохраняется;
  иконки: 🗄️ → 🌙 / 📼 и т.п. (по вкусу @Architect). **AC-B1:** зеркало
  синхронно TAB_RULES (тест-маркеры); `node --check` clean.
- [ ] T-1011 — generic-шаблон: вкладки «Сон»/«Ностальгия» рендерятся общим
  шаблоном (без отдельного HTML) — проверка currentTabGroups/групп;
  аккордеон-«Расширенные» работает по фиче D (свёрнут по умолчанию).
  **AC-B2:** вкладки открываются, группы «Расширенные» в аккордеоне; no
  TypeError; карточки (0) не рендерятся.
- [ ] T-1012 — canViewTab/категории: tabCategories для новых вкладок = [memory]
  (RBAC-проверка секции memory — существующая; новый гейт не вводить).
  **AC-B3:** категория для видимости — memory; роли по секции memory —
  как раньше (глобальный админ/права параметров).

## C. Маркер-тесты и регресс [@Builder]

- [ ] T-1013 — test_frontend_tab_mapping.py: composition memory_rag → новый
  набор; добавлены memory_dream/memory_nostalgia; ALL_TABS + импорты.
- [ ] T-1014 — test_webapp_nav_disclosure_ui.py: label «Память», маркеры
  вкладок, «Сон»/«Ностальгия», набор _ADVANCED-маркеров (test_registry/
  test_details) — актуализация.
- [ ] T-1015 — test_param_catalog.py: эталон 383/71/359 (без изменений каталога)
  — остаётся; тест на разметку basic/advanced для dream/nostalgia (новый,
  если в рестрое нет аналогичного).
- [ ] T-1016 — python-регресс: полный pytest 0 failed (baseline 4831 + новые);
  node --check; git diff --check.
- [ ] T-1017 — live-маркер (после деплоя): вкладки «Память» (только infinite +
  limits/flags), «Сон», «Ностальгия» — открываются; «Сон»/«Ностальгия» — с
  базовым рубильником (не пустые); гейты chat (гейты gate-карточки) видят
  статус (напр. «Сон выключен для чата»).

**Критерии приёмки ТЗ 4 (сводные):**
- «Память и RAG» → «Память»; «Сон» и «Ностальгия» — отдельные разделы/вкладки в
  «Настройки AI»; гейты/бюджеты сон/ностальгия на своих вкладках; поведение
  воркеров (DreamWorker/NostalgiaWorker) НЕ меняется — только UI/каталог.
- Реструктуризация совместима с ТЗ 5 (фича D): базовые рубильники остаются
  базовыми (вкладки не пустые после сворачивания advanced).
- REGISTRY 383 / 71 / 359 — без изменений; SQLite v8; промпты/каноны —
  без дифов; R9-маркеры/разметка — сохранены.
