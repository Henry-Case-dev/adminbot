# ADR-1020-4 — Новый 8-й инструмент `compile_lore_story` и UPD-хранилище (БЛОК 1)

- **Статус:** 🟢 **Принято** (Step 2 @Architect, 16.09.2026; **AMEND ред. 2** — решения О3/О7 FINAL)
- **Раунд:** 10.20, фаза C (`lore-compiler-round1020`), задачи T-1886…T-1893
- **Спека:** [`spec.md`](spec.md) §3
- **Аудит-основание:** `round1020_llm_engine_audit.md` §Q1/Q2/Q4
- **Связанные ADR:** [ADR-1020-6](adr-1020-6-story-delivery-format.md) (формат доставки), ADR-1015-3 (tool calling)

## Контекст

Тул-сет DirectChat — **7 инструментов** (`services/tool_schemas.py:190-201`), канон R9 (память → лор → веб).
`compile_lore_story` не существует. ТЗ БЛОК 1 требует изолированный инструмент для запросов
«расскажи историю про…/поясни за…»: граф (узел + связи 1–2 уровня + привязанные Убеждения) + хронология
(earliest/latest + 2–3 диалога максимальной плотности, ASC) + storytelling-промпт + механизм диффов/UPD.

Ограничения из аудита:
- результат тула уходит модели как **строка** (`tool_loop.py:87-88`), а финальный ответ — под каноном DirectChat,
  который **запрещает маркдаун и режет ответ до 1–2 предложений** (`chat_prompts.py:160`, `:171-172`);
- доставка — plain-text (`send_chunked_reply(..., parse_mode=None)`, `smartmodule_utils.py:113-120`);
- `smart_cache` **непригоден** для UPD-кэша: `created_at = time.monotonic()` (`smart_cache.py:137,151`) — TTL
  не переживает рестарт, плюс LRU по `limits.smart_cache_max_rows`;
- у `graph_facts` нет forward-полей (`database.py:286-296`) — метаданные БЛОК 0 формируются по правилам ADR-1020-1.

## Решение

1. **8-й инструмент** `compile_lore_story(topic: string)` (единственный параметр — как в ТЗ).
   Регистрация: `tool_schemas.TOOL_CALLING_TOOLS` (в конец, канон R9 не тронут) + реестр `tool_router.dispatch:302-310`
   + `ToolRouter._compile_lore_story`. Доступ: DirectChat + фактчекер (фаза E).
2. **Пайплайн:** Шаг А — граф: узел `nodes` (`database.py:247-256`) → связи 1–2 уровня `edges` (`:258-278`, включая
   `fact_id`-provenance, ADR-1018-3 D1) → привязанные Убеждения `graph_facts`; новый read-метод
   `db.lore_graph_slice(chat_id, topic, depth=2)`. Шаг Б — хронология: `search_messages_fts_count`
   (`:1859-1878`) даёт `first_seen/last_seen`; новый `db.lore_dense_dialogs(chat_id, keywords, max_dialogs=3,
   window_minutes=30)` — бакетирование FTS-выборки и топ-3 бакета, текст окна **строго ASC**.
   Рендер — единый `format_context_item` (ADR-1020-1).
3. **Синтез делает сам инструмент.** Изолированный `services/lore_compiler_service.py::LoreCompilerService`
   вызывает LLM со своим каноном `LORE_STORY_SYSTEM_PROMPT` (`services/lore_prompts.py`) и возвращает
   `{"status":"ok","is_update":bool,"story":"<готовый рассказ>"}` + инструкцию «верни `story` дословно».
   Обоснование: изоляция стиля от канона DirectChat (иначе история будет обрезана до 1–2 предложений и лишена
   разметки). **AMEND ред. 2 (О5):** разметка — **HTML** (`<b>`, `<i>`) вместо Markdown; при `ctx.lore_compiled`
   DirectChat доставляет **готовый текст истории** с `parse_mode="HTML"` (фолбэк на `None` при `TelegramBadRequest`).
   Факт вызова фиксируется в `ToolContext.lore_compiled` → DirectChat применяет режим доставки летописца (ADR-1020-6).
4. **UPD-хранилище — аддитивная таблица `lore_stories`** (`CREATE TABLE IF NOT EXISTS`, **без подъёма `user_version`**,
   прецедент `smart_cache` `database.py:304-311`, `bot_reply_parents` `:328-334`):
   `(id, chat_id, topic_key, topic, story, last_ts, created_at, updated_at, UNIQUE(chat_id, topic_key))`,
   `topic_key = normalize_text(topic)` (`services/smart_cache.py:61`).
   Hit → `is_update=true`, `previous_story_at`, в промпт идёт «известная база» + только новые сообщения
   (`timestamp > last_ts`) и ветка **UPD (Свежак)**.
5. **Флаг `flags.lore_compiler_enabled` — FINAL (О3):** простой тумблер ВКЛ/ВЫКЛ, **дефолт ВКЛ глобально**
   для всех чатов (код-дефолт `True` + сид `bot_settings`); **поэтапная раскатка 10/50/100 % ОТМЕНЕНА** решением
   владельца. Откат — тумблер OFF без редеплоя (тул недоступен, остальные 7 работают); полное снятие — `git revert`.
   Тест «флаг OFF → `compile_lore_story` недоступен» обязателен.
6. **Опечатка ТЗ** `dig_into_lor` не переносится; роутинг разводится EN-описаниями (ADR-1020-2 п.4).

## Альтернативы и отклонения

- **(B) Отдать JSON + prompt диспетчеру, синтез в основном LLM:** отклонено — размывает изоляцию стиля, дублирует
  промпт-канон, ломает детерминизм; fallback-вариант, если владелец запретит отдельный LLM-вызов.
- **Backend сам отправляет историю (как `download_media` шлёт файл):** отклонено — разрывает диалог, лишает модель ремарки.
- **Хранить UPD-состояние в `smart_cache`:** отклонено — `time.monotonic()`-TTL не переживает рестарт, LRU вытесняет.
- **Хранить историю в `smart_archive_facts` (без DDL):** резервный вариант (О7,б) — риск загрязнения L3/RAG-выборок;
  допустим только при запрете DDL, с исключением неймспейс-маркера из RAG/L3.
- **Расширить `graph_facts` forward-полями (DDL):** отклонено в этом эпике.
- **Поэтапная раскатка 10/50/100 %:** **ОТКЛОНЕНА ВЛАДЕЛЬЦЕМ (О3)** — фича включается глобально по дефолту;
  откат — простой OFF-тумблер (без редеплоя) либо `git revert`.

## Каталог-Δ

**Δ = +1** (`flags.lore_compiler_enabled`, группа `flags_module_direct`).

## Последствия

- Рост tool-сета 7 → 8 меняет выбор модели → обязательны роутинг-тесты и снапшот описаний.
- Появляется **второй LLM-вызов** на запрос летописца (стоимость/латентность) — метрика и наблюдение на живой
  проверке обязательны; раскатка — глобальная (О3), откат — OFF-тумблер.
- Новое хранилище `lore_stories` — идемпотентное, откат = `DROP TABLE` без миграционных следов.
- Новая фича обслуживается каноном `plans/docs/canon/` (первая ступень миграции, прод-значения ещё нет).

## Инварианты

Канон R9 и существующие 7 схем не менять; `TOOL_MAX_ROUNDS`/`_TOOL_CALLS_PER_ROUND_MAX` не менять;
R16/R17; `user_version` SQLite не поднимать; порядок роутеров `bot.py` не менять; меню мини-аппа не менять.
