# Задачи: multimodal-summarization-tools-reactions-ui

## Контекст и статус

Активный эпик 04.09.2026 (OpenSpec шаги 0–9; шаг 0 Memory-sync выполнен, живой план — `plans/docs/memory-project-overview.md:38-45`, KG-сущность `epic: multimodal-summarization-tools-reactions-ui`, запись добавлена в `plans/backlog.md`). Эпик в 4 частях: (1) каскадная мультимодальная видео-выжимка через OpenRouter `video_url` — primary `minimax/minimax-m3:free`, fallback `google/gemma-4-31b-it:free`, затем старая логика субтитров (graceful degradation, без ошибок юзеру); (2) Tool Calling — `execute_web_search`, `query_chat_memory`, цикл обработки `tool_calls`; (3) фиксы реакций — новые тумблеры (default `false`), строгий гейт `slavic_chlen.mp4` по `reactions.slavik_user_id`, переименование Alan → Леха в UI/параметрах; (4) UX/UI админки — группировка вкладок, KV-редактор `limits.summary_aliases`, нейминг Леха.

Новые параметры — только через param_catalog REGISTRY (`services/param_catalog.py`: `_MODELS` :321, `_FLAGS` :378, `_REACTIONS` :710) + сид `services/pg_db.py _seed_settings` (INSERT … ON CONFLICT DO NOTHING); чтение — `hot.get(key, settings_default)` (`services/hot_config.py`). Правила: полный pytest перед коммитом (0 failed), conventional commits на русском, идентификаторы кода (ALAN_USER_ID и т.п.) не переименовываются.

**Статус:** archived (выполнено 2026-09-04, 3447 passed, 0 failed). Задачи T33/T34 (деплой и живая проверка) остаются открытыми — исполняет @DevOps отдельным шагом вне архива. Задачи `⏸` ждут человека и не закрываются без вердикта.

## A. Планирование и дизайн

- [x] T1: Создать spec.md фичи (роль @Architect, шаг 2 OpenSpec) и сверить границы/критерии готовности 4 частей с декомпозицией ниже (spec.md). **Выполнено:** спецификация одобрена @Reviewer 04.09.2026.
- [x] T2: Держать «живой план» в синхроне: проставлять статусы частей по мере выполнения (plans/docs/memory-project-overview.md:38-45). **Выполнено:** статусы велись весь эпик; финальный memory-sync — отдельный шаг @Memory (вне архива).

## B. Часть 1 — Видео-выжимка (каскад video_url)

- [x] T3: Добавить поля настроек `VIDEO_PRIMARY_MODEL = 'minimax/minimax-m3:free'` и `VIDEO_FALLBACK_MODEL = 'google/gemma-4-31b-it:free'` (config/settings.py, блок LLM-моделей).
- [x] T4: Зарегистрировать ключи `models.video_primary_model` и `models.video_fallback_model` (type `str`, env_name VIDEO_PRIMARY_MODEL/VIDEO_FALLBACK_MODEL, title_ru, группа, description, code_source) в REGISTRY (services/param_catalog.py `_MODELS`:321-374; при необходимости новый GroupSpec группы моделей).
- [x] T5: Добавить сид-строки новых ключей в `_seed_settings` (INSERT … ON CONFLICT DO NOTHING) (services/pg_db.py).
- [x] T6: Реализовать сервис каскадной видео-выжимки: мультимодальный вызов OpenRouter с `video_url` в payload — primary → fallback (образец клиента: AsyncOpenAI, base_url `openrouter.ai/api/v1` — SmartModule/transcriber/openrouter_transcriber.py; интеграция с пайплайном выжимки — services/youtube_summarizer_service.py).
- [x] T7: Graceful degradation: оба мультимодальных вызова недоступны → существующая логика субтитров, юзеру ошибку не показывать (services/youtube_summarizer_service.py:41-63, services/youtube_transcript_engine.py).
- [x] T8: Встроить каскад в обработчик видео, кэш — только успешный результат, логи по R41-5 (handlers/youtube.py:110-170).
- [x] T9: Обработка ошибок каскада: сбой → WARNING/ERROR-лог и молчание по прецедентам D190/R41-5 (handlers/youtube.py:160-170).
- [x] T10: Тесты Части 1: primary OK / primary fail→fallback OK / оба fail→субтитры / пустой ответ→молчание; чтение новых ключей через hot.get (tests/, прецедент tests/test_message_counter.py).

## C. Часть 2 — Tool Calling

- [x] T11: Описать JSON Schema инструментов `execute_web_search` (запрос, число результатов) и `query_chat_memory` (запрос, окно/источник) (новый модуль описаний инструментов; размещение — по решению spec.md).
- [x] T12: Расширить LLMClient.generate: прокидывать `tools`/`tool_choice` в payload при вызове, не меняя {model, messages, temperature} (services/llm_client.py:453-455).
- [x] T13: Реализовать `execute_web_search` поверх каскада SearchAggregator Tavily→Exa→DDG; `AllSearchEnginesFailedException` → структурированный результат инструмента (services/search_aggregator.py).
- [x] T14: Реализовать `query_chat_memory` поверх MemoryManager: `get_rag_context`/`search_long_term`/`get_window_messages` (services/summary_memory.py:956,1025,1413).
- [x] T15: Цикл обработки `tool_calls` в aiogram-хендлере: есть tool_calls → исполнить инструменты, вернуть результат сообщением `role:"tool"`, повторить генерацию; жёсткий лимит итераций против бесконечного цикла (интеграция: SmartModule/service.py + целевой хендлер — по spec.md).
- [x] T16: Сохранить ручной триггер поиска/исследования без изменений — только регресс-проверка (handlers/search.py, handlers/web.py).
- [x] T17: Тесты Части 2: мок-ответы с tool_calls — round-trip, порядок сообщений, `role:"tool"`, лимит итераций, сбой инструмента (tests/).

## D. Часть 3 — Реакции (тумблеры + Alan → Леха)

- [x] T18: Вынести «Вася → АДМИН / админ → ВАСЯ» под флаг `reactions.vasya_enabled` (default `false`): регистрация в REGISTRY `_REACTIONS` + сид, гейт через hot.get в хендлере/фильтре (handlers/vasya.py:8-17, filters/vasya_name.py).
- [x] T19: Вынести «куча → ДАЛБАЕБ» под флаг `reactions.kucha_enabled` (default `false`), гейт до отправки, data-флаг миддлвари сохранить (handlers/slavik.py:149-156, filters/kucha_word.py).
- [x] T20: mimic в common.py под флаг `flags.mimic_enabled` (default `false`) — НЕ ломая механизм `reactions.mimic_victim_user_ids` (common.py:204) и mimic-механизм Славика внутри handlers/slavik.py (handlers/common.py mimic_handler:228-269).
- [x] T21: Тумблер `reactions.alan_mimic_enabled` (default `false`) для mimic-реакции на Леху/Алана (id: reactions.alan_user_id, settings.ALAN_USER_ID=138811255, services/param_catalog.py:715) — семантику подтвердить в spec.md.
- [x] T22: Media-реакция slavic_chlen.mp4 — слать строго по `reactions.slavik_user_id` (settings.SLAVIK_USER_ID): гейт в MessageCounterMiddleware до отправки, файл media/slavik/slavic_chlen.mp4 (services/message_counter.py:43-74, config/settings.py:185 GIF_PATH, scheduler.py:29) + тесты (tests/test_message_counter.py).
- [x] T23: Переименовать Alan → Леха в UI-параметрах: title_ru и описания/группы «Алан», «Персонажи: Алан и Костик», «Telegram ID Алана» → Леха (services/param_catalog.py:136,188-195,715,727); код-идентификаторы не трогать.
- [x] T24: Тесты Части 3: дефолт `false` у всех новых тумблеров, включение через админку/hot.get меняет поведение, регресс старых реакций (tests/).

## E. Часть 4 — UX/UI админки

- [x] T25: Перегруппировать вкладки: «LLM Провайдеры», «Промпты», «Лимиты», «Память и RAG», «Реакции и Триггеры», «Доступы», «Статус» — маппинг категорий/групп param_catalog (prompts|models|keys|limits|flags|reactions|content + GroupSpec) на вкладки в бэке и фронте (web/api/routes.py, web/app.js, web/index.html). **Бэк готов** (04.09): TAB_RULES/TAB_*_TITLES + group_tab()/tab_group_ids() в services/param_catalog.py (контракт 3.5.1) + тест-аудит test_frontend_tab_mapping.py; **фронт готов** (04.09, шаг 4b): декларативный TABS с sources (зеркало TAB_RULES/CONFIG_TAB_TITLES) + ОДИН generic config-шаблон вместо 5 категорийных (web/app.js groupedForTab, web/index.html).
- [x] T26: Свести разрозненные настройки памяти в «Память и RAG»: группы limits_memory/limits_graph/flags_memory (services/param_catalog.py:164-167,181-182) + связанные лимиты окон/RAG (limits_summary:146-147, limits_search:148-149); чужие группы не переносить.
- [x] T27: Аудит дублирования параметров по вкладкам (один ключ виден в двух местах) и убрать дубли (web/api/routes.py, группы/категории в services/param_catalog.py). **Бэк готов:** TAB_RULES-аудит (каждая группа — ровно одна вкладка) в test_frontend_tab_mapping.py; дублей по конфиг-вкладкам нет.
- [x] T28: Vue Key-Value редактор для `limits.summary_aliases`: v-for по парам alias→имя, input-поля, кнопка «Добавить имя», иконка корзины на строке, сборка JSON при сохранении; заменить текстовое JSON-поле (web/app.js:341-344, web/index.html, POST /api/config). **Бэк готов** (widget='keyvalue' в REGISTRY + GET /api/config, POST принимает json-dict — тесты test_webapp_api); **фронт готов** (04.09, шаг 4b): компонент kv-editor (app.js provide/inject, шаблон #kv-editor-tpl) — для ЛЮБОГО item.widget='keyvalue'; json без widget — textarea JSON с парсингом при сохранении.
- [x] T29: «Леха» вместо остаточных «Alan»/«Алан» в интерфейсе после перегруппировки вкладок (web/app.js, web/index.html; строки с бэка правятся через param_catalog по T23). **Бэк готов (T23):** в каталоге «Алан» не осталось (тест test_reaction_flags::test_no_alan_in_display_texts); **фронт готов** (04.09, шаг 4b): grep-аудит «Alan|Алан» по web/ пуст; все названия параметров/групп приходят с сервера.
- [ ] T30: Проверка фронта: все вкладки грузятся, KV-редактор сохраняет summary_aliases в PG (updated_by), тумблеры/select на новых группах работают (ручная проверка + тесты /api/config). **Бэк готов:** test_webapp_api — widget в GET /api/config, POST json-dict summary_aliases (updated_by штатно в ConfigCache.set). **Фронт готов** (04.09, шаг 4b): вкладки/KV-компонент реализованы (node --check + статические проверки структуры шаблонов); остаётся живая ручная проверка (в связке с T34).

## F. Тестирование, документация и деплой

- [~] T31: Обновить README и .env.example: новые настройки (models.video_*, reactions.vasya_enabled/kucha_enabled/alan_mimic_enabled, flags.mimic_enabled), новые вкладки и KV-редактор (README.md, .env.example). **Частично (фикс-раунд 05.09.2026):** .env.example готов (7 переменных: VIDEO_PRIMARY_MODEL/VIDEO_FALLBACK_MODEL/VIDEO_TIMEOUT_SECONDS/VASYA_ENABLED/KUCHA_ENABLED/MIMIC_ENABLED/ALAN_MIMIC_ENABLED, комментарии на русском); README.md — за @DevOps.
- [x] T32: Полный pytest перед коммитом — 0 failed, git diff --check чист (правило plans/project.md). **Выполнено (фикс-раунд 05.09.2026):** 3447 passed, 0 failed (B1/W1/W2/env-правки).
- [ ] T33: Деплой на прод: git pull --ff-only + systemd `admin_bot` restart на 198.46.175.136 (/var/www/admin_bot) — исполнитель DevOps (вне этого плана; выполняется отдельным шагом после архивации фичи).
- [ ] T34: Живая верификация (⏸ ждёт человека): видео-каскад и молчание при сбоях, тумблеры реакций, mimic-Леха, KV-редактор и вкладки в мини-аппе (после деплоя T33; в связке с T30).
