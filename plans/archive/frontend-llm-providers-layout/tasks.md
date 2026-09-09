# Задачи: frontend-llm-providers-layout (ТЗ 6 раунда 10.4)

Раунд 10.4, фича E (T-1024…T-1032). Стадия старта — PLANNED; spec.md @Architect.
ТЗ владельца (п.6): «LLM Провайдеры» разбить логически:
**основные модели → ключи → фолбэк → расширенные** (порядок рендера групп).

Отправная точка (рекон tma-structure-10.4, HEAD 1410a68):
- TAB_LLM_PROVIDERS sources: (MODELS, None) + (KEYS, None) — категории целиком;
  категории/модели и ключи — строго глобальные (per_chat=False).
- Группы models (8): models_main(1) «Основная модель», models_fallback(2),
  models_embeddings(3) «Эмбеддинги и токены», models_llm_timeouts(4),
  models_llm_guard(5) «Бюджет и защита», models_extra_providers(6),
  models_checkup(7), models_video_summary(8).
- Группы keys (7): keys_llm(1), keys_groq(2), keys_openrouter(3), keys_search(4),
  keys_betterstack(5), keys_youtube(6), keys_media(7).
- Прогрессивные маркеры (param_catalog.py:64-67): timeout/budget/context/summary
  и т.п. — таймауты/бюджеты уже advanced (models_llm_timeouts/models_llm_guard).
- **ПРОБЛЕМА сортировки:** groupedForTab (app.js:1433-1485) сортирует группы по
  рангu КАТЕГОРИИ (первое вхождение категории в sources) → категория models
  целиком рендерится раньше keys ЦЕЛИКОМ. Чтобы «модели → ключи → фолбэк →
  расширенные» — нужен плоский порядок по (категория, группа) или секции.
- Эталон REGISTRY 383/71/359 (без изменений — только переносы/порядки).

ЦЕЛЕВОЙ ПОРЯДОК (дефолт; уточнения @Architect):
1. **Основные модели**: models_main.
2. **Ключи**: keys_llm, keys_groq, keys_openrouter (LLM-ключи).
3. **Фолбэк**: models_fallback.
4. **Расширенные**: models_embeddings, models_llm_timeouts, models_llm_guard,
   models_extra_providers, models_video_summary, models_checkup +
   keys_search, keys_betterstack, keys_youtube, keys_media.
(Допустимо: keys_search и медиа-ключи в отдельную подсекцию «Расширенные: ключи».)

## A. Каталог/порядок [@Architect/@Builder]

- [ ] T-1024 — TAB_RULES: TAB_LLM_PROVIDERS sources → секционированный список:
  (MODELS, {models_main}) / (KEYS, {keys_llm, keys_groq, keys_openrouter}) /
  (MODELS, {models_fallback}) / (MODELS, {остальные}) / (KEYS, {остальные}).
  **AC-E1:** покрытие категорий моделей/ключей целиком (каждая группа ровно
  на одной вкладке — _TAB_BY_GROUP); конфиг-контракт сохранён
  (test_frontend_tab_mapping test_providers_tab_covers_all_models_and_keys).
- [ ] T-1025 — РАЗМЕТКА источника: источники повторяют категорию (models дважды)
  — принятый формат rule это допускает (frozenset); НО сортировка в
  groupedForTab должна следовать ПОРЯДКУ источников (плоская очередь
  (категория, группа) в порядке вхождений) — иначе фолбэк встанет в начало.
  **AC-E2:** порядок витрины для llm_providers = ровно целевой; сорт в
  groupedForTab обобщён (rank по паре category+group; «Прочее» — в конец);
  регресс: прочие вкладки без изменения порядка.
- [ ] T-1026 — прогрессивная разметка: «Расширенные» секция = группы 4-й
  позиции; внутри них таймауты/бюджеты сохраняют advanced (аккордеон);
  остальные (эмбеддинги, чек-ап, видео-выжимка, доп.провайдеры) — basic
  (иначе секция выглядит пустой после ТЗ 5 — фичи D).
  **AC-E3:** у секции «Расширенные» ≥1 basic-группы; маркеры progressive
  обновлены.

## B. Фронт [@Builder]

- [ ] T-1027 — groupedForTab-сортировка (секции) — реализация плоского порядка
  (см. T-1025); тест-маркер на порядок (напр. список groupTitle в ожидаемом
  порядке для llm_providers — добавить юнит-тест чистой функции сортировки,
  без браузера). **AC-B1:** функция чистая/тестируемая; node --check clean.
- [ ] T-1028 — визуальная иерархия: заголовки секций (h3/подзаголовки)
  «Основные модели», «Ключи», «Фолбэк», «Расширенные» — в шаблоне
  generic-рендера (опционально — только для llm_providers; решение @Architect:
  свой шаблон ИЛИ обобщённый подзаголовок по первой группе секции).
  **AC-B2:** секции видимы (маркеры в HTML); рендер секций не ломает
  остальные конфиг-вкладки (регресс-маркеры).
- [ ] T-1029 — keys-поле: секрет-виджет (input password + маска {configured,
  last4}) — сохранить для всех ключевых групп при переносе; ограничение
  редактирования ключей (глобальные — только global admin) не менять (поле на
  вкладке остаётся для global; local — BYOK-блок на вкладке).
  **AC-B3:** маска/статус {configured, last4} ключей — без изменений; тесты
  webapp_rbac (ключи маскируются) — зелёные.

## C. Маркеры и регресс [@Builder]

- [ ] T-1030 — test_frontend_tab_mapping.py: composition llm_providers — наборы
  групп (секции в TAB_RULES); зеркало TABS-маркеры (разделённые sources).
- [ ] T-1031 — test_webapp_nav_disclosure_ui.py / test_webapp_*: маркеры секций,
  отсутствие старых строк (models эталонный порядок); обновление по
  MED-022-прецеденту.
- [ ] T-1032 — регресс: полный pytest 0 failed; node --check; git diff --check;
  live: вкладка «LLM Провайдеры» рендерится в целевом порядке; ключи маскируются;
  BYOK-блок для local admin на месте (index.html:750-769, маркер).

**Критерии приёмки ТЗ 6 (сводные):**
- Порядок: основные модели → ключи → фолбэк → расширенные (визуально видно);
- Категории models/keys покрыты полностью (без дублей и потерь);
- Маскировка/права ключей (S1-S3/R17) — без изменений;
- REGISTRY 383 / 71 / 359 — без изменений; SQLite v8 — без дифов.
