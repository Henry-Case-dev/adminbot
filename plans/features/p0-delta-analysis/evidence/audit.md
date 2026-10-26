# P0 Delta — аудит существующих механизмов (READ-ONLY)

- Дата: 26.10.2026. Worktree: `C:\Code\Python\adminbot-wt-delta-audit` @ `534ac7dd` (2.58.130).
- Источник: `plans/owner_inputs/2026-10-26-p0-delta-analysis.md`. Только факты, без изменений кода.
- Метод: чтение кода прод-коммита; все пути относительно корня репо; `:N` — строка в файле на `534ac7dd`.

---

## 1. L1 / Decision Making

### 1.1. Поля L1Plan (`services/direct_l1.py:134-169`)

`action, reaction, response_act, extent, tone, emotional_mirroring, structure,
delivery_hint, tool_policy (none|auto), capabilities_needed (≤8 строк),
needs_clarification, clarification_target, confidence, source, form_override,
future_intent, execution_mode, comic_strategy, delivery (chat|reply|""),
target_message_id, target_user_id`.

- **Поля «субъект анализа» и «период» ОТСУТСТВУЮТ.** `target_user_id` —
  смысловой АДРЕСАТ reply-формы (direct_l1.py:161-169, chat_prompts.py:674-675),
  не субъект анализа. Никакого `time_range`/`year`/`subject` в плане нет.
- `capabilities_needed` — ТОЛЬКО имена без аргументов (direct_l1.py:327-338,
  40 символов на имя). Аргументы инструментов (query/person/year/time_range/
  stats) генерирует tool-calling модель в `tool_loop` из JSON-схем
  (`services/tool_loop.py:174-209 normalize_tool_plan`), не L1.
- Схема, видимая планером: `services/chat_prompts.py:647-666`
  (`_DIRECT_L1_PLANNER_BASE_L1D`); `response_act` — открытый словарь
  (chat_prompts.py:595-596 «можно уточнять своими короткими понятиями»).

### 1.2. task_kind — производная от response_act (`direct_l1.py:184-218`)

`to_response_plan()` маппит ТОЛЬКО: `explanation→explanation, research→research,
comparison→comparison, summarization→summarization, creative→creative_writing,
historical_recall→historical_recall` (direct_l1.py:201-206). **Любое другое
значение (включая кастомные «analysis», «person_analysis», разрешённые промптом)
→ `social_chat`.**

### 1.3. Fallback-планы (`direct_l1.py:1024-1050, 1053-1092`)

`fallback_plan()` = `classify_request` + `infer_fallback_capabilities`
(только URL→fetch_url, search-маркеры→web_search; direct_l1.py:1029-1050).
Память/лор в fallback-инференсе НЕ участвуют: при сбое L1 запросы про прошлое
теряют `chat_memory`/`historical_search` (остаётся только explicit-лексика).

### 1.4. Возможности L1 (`services/direct_capabilities.py:28-49`)

`CAPABILITY_TOOLS`: web_search→execute_web_search; fetch_url→fetch_article;
chat_history→get_recent_history; chat_memory→query_chat_memory;
user_memory→get_user_context; historical_search→(dig_into_lore,
compile_lore_story); fact_check; image_understanding; media_download;
transcription; video_summary; image_generation; health; **statistics→() —
тула НЕТ, честная пометка L2** (direct_capabilities.py:47-48).

### 1.5. Способность текущего плана выразить 8 интентов

| Интент | Вердикт | Чем выражается сегодня |
|---|---|---|
| Свободное рассуждение | **YES** | tool_policy=none, caps=∅; L2 пишет из контекста (direct_l1.py:147-148) |
| Поиск факта | **YES** | `web_search`/`fact_check` capability (direct_capabilities.py:29,35) |
| Анализ сообщений человека | **PARTIAL** | capability-имени «анализ человека» нет; L1 может попросить `chat_memory`/`historical_search`, но ни план, ни схема не выражают «сообщения именно этого человека» (см. §3/§4) |
| Изменения за период (многолетнее) | **NO** (первоклассно) | поля периода нет; `time_range` enum без годов (tool_schemas.py:107-112), `year` dig — один календарный год (tool_router.py:3272-3279); многолетний диапазон невыразим |
| История/мем | **YES** | `historical_search` → dig_into_lore + compile_lore_story (direct_capabilities.py:34) |
| Анализ отношений | **PARTIAL** | только `user_memory` purpose=relationships (досье ≤10 фактов; tool_router.py:1916) + dig facts; рёбра графа direct-чату не доступны никак |
| Точная статистика | **YES** (при K1 ON) | `stats`-объект query_chat_memory (tool_schemas.py:116-170) → measure() + MetricResult + numeric-гард; дет. классификатор intent (chat_statistics.py:655-697). Оговорка: автор — только имя/алиас, не user_id |
| Творческий запрос | **YES** | `response_act=creative` → creative_writing; structure=story (chat_prompts.py:584-588) |

Дополнительно: кастомный `response_act` (например «analysis») **тихо
деградирует** в `social_chat` в downstream (§1.2) — источник «бот не отличает
анализ от болтовни» на уровне L2-настроек (response_mode):
`plan_response_mode` смотрит только extent/structure/delivery_hint
(direct_l1.py:221-240) — «research»-акт без longform-extent/structure даёт
`casual`.

---

## 2. query_chat_memory (`services/tool_router.py:750-831` обычный; 870-936 stats)

### 2.1. Схема (`services/tool_schemas.py:91-176`)

- Параметры: `query` (required), `time_range` ∈ {last_day, last_week,
  last_month, **all**} (tool_schemas.py:107-112), `stats` (аддитивный объект).
- **Параметра автора/uid в обычном режиме НЕТ вообще.** Автор есть только внутри
  `stats`: `author` — «Author name/alias; the server resolves it»
  (tool_schemas.py:151-154). Прямого `user_id` нет нигде.
- Произвольный временной диапазон (год/интервал) **невозможен** — только 4
  значения enum (`_TIME_RANGE_SECONDS`, tool_router.py:185-190).

### 2.2. Обычный режим (tool_router.py:750-831)

- FTS по `search_long_term` (limit `_MEMORY_FTS_LIMIT=40`, tool_router.py:89)
  → **пост-фильтр окна ПОСЛЕ LIMIT** (tool_router.py:766-780): для узкого окна
  top-40 по rank может целиком состоять из старых сообщений → строки отфильтруются
  при count>0.
- Счётчик: `count_mentions` → SQL COUNT по всему корпусу с since
  (database.py:8255-8288) — счётчик корпус-полный, в отличие от сниппетов.
- При пустом FTS и широком окне → `vector_search` (KNN по graph_facts,
  tool_router.py:794-798) → затем `get_rag_context` (tool_router.py:800-806).
  **Результаты L3/RAG — производные факты (пересказы/выводы LLM), вставляются
  как обычные строки без маркировки происхождения** (см. §8).
- Результат: строки `[Имя [дата]]: текст` + заголовок «Широкий поиск (префиксы,
  не морфология): N сообщений…» при K1 ON (tool_router.py:819-829) — счётчик
  НЕ выдаётся за точную статистику (MCA-15 T-4926).
- Формат результата — текст с id/датами НЕ возвращает: только `[имя [ts]]: текст`
  (tool_router.py:776-780); message id/uid в обычном режиме не отдаются.

### 2.3. Stats-режим (tool_router.py:870-936)

- Разделение поиска и точной статистики РЕАЛЬНОЕ: `stats` → `chat_statistics.measure()`
  → типизированный JSON + `MetricResult` в `ctx.metric_results` (источник
  NumericClaim; финальный numeric-гард direct_chat_service.py:3744-3759).
- metric ∈ {messages, occurrences, distinct_authors}; match_mode ∈ {exact_phrase,
  token, prefix, all_terms, any_terms}; quote_forward; sender (tool_schemas.py:124-167).
- Автор: `_resolve_author_id` (tool_router.py:835-853) — casefold-точное
  совпадение значения алиаса; неоднозначность/не найдено → честный
  `unsupported/ambiguous_identity|author_unresolved`, без угадывания.
- Уточняющие запросы: инструмент stateless; уточнение = повторный вызов с другими
  аргументами (модель сама); `max_id` watermark существует на уровне SQL
  (database.py:8267-8270), в схему инструмента НЕ проброшен.

---

## 3. dig_into_lore (`services/tool_router.py:940-1282`)

### 3.1. Параметры и поток

- `query` (required), `year` (int 2000..текущий; tool_router.py:3194-3205),
  `mode` ∈ {messages, facts, both}, `person` ≤100 симв. (3342-3347).
- «N лет назад» в query → год = текущий − N (3207-3229). Диапазон лет/интервал
  **невозможен** — `bounds` только одного календарного года (3272-3279).

### 3.2. Расширение токенов графа (976-987, 3231-3269)

- `_dig_graph_names`: BFS по nodes/edges глубиной `limits.dig_graph_hop_depth`
  (макс `_DIG_GRAPH_MAX_HOP_DEPTH`), фолбэк target_user-имена; seeds — токены
  ≥4 симв.
- K1 ON: expansion НЕ входит в условие измерения (`measurement_tokens`,
  985-987) и добавляет кандидатов только через mca-07 `retrieve()`
  (1059-1091); K1 OFF: имена графа добавляются OR-токенами в FTS (979-984).
  Косвенные связи прямые высказывания не вытесняют при K1 ON; при K1 OFF
  «о человеке» и «от человека» смешиваются в одном OR-запросе.

### 3.3. «О человеке» vs «человеком» — разделение есть, хрупкое

- `person` → `(person_uid, person_terms)` (`_dig_person_terms`, 3349-3368):
  ТОЧНОЕ casefold-совпадение значения алиаса → uid; **первое совпадение
  побеждает (break)** — в отличие от stats-режима, дубликаты имён не
  обнаруживаются (сравни 835-853: там честный `ambiguous_identity`).
- messages-режим: фильтр `user_id == person_uid` (1029-1031) — «от человека».
  **Если алиас-мэтча нет → person_uid=None → фильтра автора НЕТ, имя
  превращается в OR-токены запроса (966-967) → «о человеке/упоминания».**
  Т.е. строгость фильтра зависит от полноты алиас-мапы, тихо.
- facts-режим: фильтр substring по `target_user` имени (1117-1122) — факты
  «о человеке», по ИМЕНИ без uid (похожие имена дают ложные попадания).
- Счётчик: `search_messages_fts_count_by_author` (1154-1202); K1 ON применяет
  `author_ids=(person_uid,)` к счётчику (1163-1164); K1 OFF — счёт по всем
  авторам (упоминания).
- Медиа-сообщения в сниппеты не попадают (текст пуст → skip, 1032-1034).

### 3.4. Выборка/покрытие

- Сниппеты: `search_long_term(..., limit=40)` по rank → пост-фильтр года/person
  ПОСЛЕ LIMIT (1022-1031). Для старого года top-40-rank по всему корпусу может
  не содержать ни одного сообщения этого года → секция пустая при непустом счётчике.
- Счётчик и first/last_seen — SQL по всему корпусу (8290-8342) — корпус-полные.
- JSON-контракт результата: status/ok/partial, stats{status,value,unit,method,
  method_label,scope{since_ts,until_ts,person_user_id},coverage="known_complete"},
  authors[{user_id,label,count}], snippets (с `[дата | автор | tg:/msg:]`),
  facts (`[ММ.ГГГГ | target_user | fact:ID] (+ устарело)`) (1203-1282).
- **coverage="known_complete" относится к счётчику, не к сниппетам** — доля
  сниппетов от total нигде не сообщается.

### 3.5. Провенанс результата

- Рендер `format_context_item` (10.20 канон): дата, автор (R16-каскад алиасов),
  ID (tg:/msg:/fact:), переслано, stale-суффикс (1037-1047, 1127-1138).
- facts-режим включает архивные beliefs (include_archived=True, 1104-1111) —
  происхождение «прямой пересказ vs вывод L2» в рендере НЕ различается
  (kind="fact" для всего; см. §8).

---

## 4. Субъект: Telegram user ID → запрос → L1 → анализ → память → Writer

- **Говорящий**: `target_name = self._resolve_name(user)` (direct_chat_service.py:2215)
  → L1-контекст `speaker=target_name` (4214). UID говорящего в ToolContext есть:
  `ToolContext.user_id` (tool_router.py:588,609), **но ни один инструмент памяти
  его не читает** — «мои сообщения» резолвятся только через имя/алиас, которое
  модель должна написать сама в аргументе `author`/`person`.
- **Адресат**: `bundle.addressee` → `addressee=` L1 (4215); `target_user_id`
  плана — только для формы доставки (direct_l1.py:161-169).
- **Reply vs цитата**: reply-цель выделена отдельным блоком L1 «ОТВЕТ НА
  (reply/цитата)» с автором first_name (`_l1_reply_block`, 4067-4082); в окне
  разметка `(ответ на msg:N)` (direct_l1.py:878-883). Различение «автор reply-
  сообщения vs автор цитаты внутри текста» — только текстовое; **в путь анализа
  (person/author инструмента) reply-автор автоматически НЕ попадает.**
- **Алиасы (uid)**: применяются на чтении (`_resolve_name` R7-каскад алиас→имя→
  ник→uid, tool_router.py:3386-3398; рендер окна с `alias_resolver`,
  direct_l1.py:855-860) и в фильтрах (stats author→uid 835-853; dig person→uid
  3349-3368 — с семантическим расхождением, §3.3). По Telegram ID искать НЕЛЬЗЯ:
  ни одна схема не принимает user_id.
- «Указанный человек = он»: резолв только по имени из аргумента модели; «частые
  упоминания делают человека субъектом» — такого автоматизма нет (правильно),
  но и связи «о ком речь» из запроса в аргумент person нет — всё на усмотрение
  tool-calling модели.

---

## 5. Lore bypass (`services/direct_chat_service.py:3734-3739` @ 534ac7dd)

```python
lore_story = str(getattr(tool_ctx, "lore_story", "") or "").strip()
if getattr(tool_ctx, "lore_compiled", False) and lore_story:
    answer = strip_reasoning_tags(lore_story)
```

- Условие подмены: ТОЛЬКО «compile_lore_story выполнился и вернул ok»
  (tool_router.py:3004-3005 ставит оба поля). **Проверок субъекта, интента,
  релевантности текущего запроса НЕТ.** L2 Writer в L1-пути выполняется ДО
  этого (3655-3709) и его ответ отбрасывается.
- Речевые настройки: канон «Летописца» при композере ON получает Core + жанр
  «Лор» + Style Policy + Expression (lore_compiler_service.py:198-206,
  mca_authorial_speech.py:96-157, ADD-EXP wiring) — композер ON частично
  компенсирует «обход речи»; при композере OFF — голый LORE_STORY-канон.
  Но драматургические требования канона остаются в обоих режимах (§6).
- Delivery: L2-пайплайн (numeric-гард 3744-3759 применяется к story тоже);
  freshness-guard дубликатов lore-ветку исключает (3788-3790). HTML-доставка
  без Markdown (lore_prompts.py:109).
- Провенанс ВМЕСТЕ с story НЕ путешествует: в `lore_stories` хранится только
  текст (lore_compiler_service.py:218-219); снапшоты/цитаты внутри story —
  на совести канона («цитаты вставляй дословно» — lore_prompts.py:108).
- Кэш: повторный запрос того же topic_key может вернуть СТАРУЮ историю веткой
  `unchanged` со статусом ok → тоже подменяет ответ (lore_compiler_service.py:
  158-170); числа помечаются `stats_recheck` и снимаются numeric-гардом
  (tool_router.py:3006-3023).
- Выбор «story vs анализ» де-факто делает tool-calling модель через EN-описание
  схемы: «Use this ONLY when the user asks to explain a meme, tell a story, or
  give a comprehensive historical overview of a topic» (tool_schemas.py:368-370)
  — «comprehensive historical overview» легитимно приглашает вызов и на
  аналитические запросы.

---

## 6. LORE_STORY_SYSTEM_PROMPT (`services/lore_prompts.py:101-116`)

- Определение: lore_prompts.py:101; канон-дубль plans/docs/canon/architecture.md:403.
- Использование: `lore_compiler_service.py:190` (`.replace("{topic}", clean)`)
  → system для синтеза story (209-212, temperature 0.85).
- Драматургические требования: «эпичная/абсурдная завязка → развитие → вывод/
  статус-кво», «3-6 абзацев», «Если фактов мало, сымпровизируй вокруг них,
  раздуй из мухи слона» (lore_prompts.py:106-112). Ограничитель вымысла:
  «имена, поступки и их порядок — только из предоставленных данных» (112).
- **Может ли дойти до анализа**: ДА — через §5: любой вызов compile_lore_story
  подменяет финальный ответ канон-текстом независимо от того, просили историю
  или анализ человека/периода. Отдельного «аналитического» канона у Летописца нет.
- Для художественного рассказа требования легитимны (владелец §8: творческие
  возможности не подавлять); проблема — не в тексте канона, а в отсутствии
  маршрутизации.

---

## 7. Покрытие/свежесть выборки

- L1-окно: 20 последних сообщений + честная пометка «ГРАНИЦА ИСТОРИИ» по ФАКТУ
  усечения (`_history_partial` по БД, direct_chat_service.py:5514-5533;
  direct_l1.py:644-659, 703-707). L2-канон велит назвать ограничение один раз
  обычными словами (chat_prompts.py:551-555).
- Инструментальные сниппеты: top-40 по FTS-rank, пост-фильтры после LIMIT
  (§2.2/§3.4) — **старые периоды могут выпадать из показа при живом счётчике**;
  рекент-первого смещения в SQL нет (rank), но lore_dense_dialogs сканирует
  `max_scan=300` СТРОГО ASC (database.py:8587-8588) — плотностные окна
  «Летописца» строятся по ПЕРВЫМ 300 совпадениям корпуса: у темы с тысячами
  упоминаний поздние периоды в окна не попадают вовсе (агрегаты earliest/
  latest/total при этом точные, 8562-8576). UPD-режим (since_ts) частично
  компенсирует только для повторных запросов той же темы.
- Per-year квот нет; «одному эпизоду доминировать» — да, может: топ-3 окна по
  плотности (lore_compiler_service.py:53-54, database.py:8609-8610) — это по
  построению самые плотные всплески.
- Сообщение покрытия модели: у dig — `coverage="known_complete"` только для
  счётчика; доли сниппетов от total нет; в query_chat_memory покрытия нет вовсе
  (только счётчик + first/last_seen, tool_router.py:810-829). Прямой формулировки
  «история доступна с 2022» ни один инструмент не выдаёт.

---

## 8. Провенанс / self-echo в фактическом пути

- Контракт MCA-04a (`services/provenance.py`) — write-side/attribution:
  запись provenance за факты direct-ответов (direct_chat_service.py:7298-7407),
  `read_policy_rank` для персонализации с фильтром BOT_ORIGINS
  (graphrag_provenance.py:187-208), self-echo-леджер (bot_output_ledger.py).
- **В пути query_chat_memory/dig_into_lore read-side-фильтрация происхождения
  НЕ применяется**: обычный режим вставляет graph_facts/векторные факты как
  строки без origin (tool_router.py:794-806); dig facts рендерит beliefs и
  прямые факты одним kind="fact", различая только stale (1092-1140).
  Т.е. **L2-пересказы/выводы могут выступать как независимые свидетельства** —
  статус `origin`/`kind` существует в БД, но до модели в этих путях не доезжает.
- Само-эхо direct-ответов исключено из RAG по умолчанию: `include_direct_reply=False`
  (summary_memory.py:3971-3990), `include_self=False` (4016-4030) — точечная
  защита есть; но ЛЕГАСИ-факты, выведенные ботом ранее и записанные как
  graph_facts, фильтром не отделяются.
- Служебные ID в речь: канон запрещает публиковать служебные метки
  (chat_prompts.py:551-555, direct_capabilities.py:157-177 — capability-имена
  только в человеческой формулировке); при этом сниппеты отдают модели
  `tg:/msg:/fact:` ID как данные — выдавать их пользователю может сама модель.

---

## 9. Подтверждённые дефекты (top-5)

1. **Lore bypass без проверки интента/субъекта** — direct_chat_service.py:3737-3739.
   Готовая драматичная история подменяет ответ на ЛЮБОЙ запрос, где tool-модель
   вызвала compile_lore_story (её EN-описание активно приглашает вызов на
   «comprehensive historical overview», tool_schemas.py:368-370). Числа
   защищены numeric-гардом; композиция/подача — нет.
2. **Многолетний период невыразим** — plan без периода (§1.1); time_range enum
   без годов (tool_schemas.py:107-112); dig `year` = один календарный год
   (tool_router.py:3272-3279); «N лет назад» тоже одиночный год (3207-3229).
3. **Сниппеты теряют старые периоды** — top-40 по rank с пост-фильтром после
   LIMIT (tool_router.py:766-780, 1022-1031) + lore_dense_dialogs max_scan=300
   ASC (database.py:8587-8588). Счётчик корпус-полный, показ — нет; доля
   покрытия не сообщается.
4. **«Сообщения человека» без алиаса → тихий отказ фильтра** — `_dig_person_terms`
   берёт первое совпадение алиаса (дубликаты не видит, tool_router.py:3349-3368),
   при отсутствии мэтча фильтр автора исчезает, имя становится OR-токеном
   (966-967) — «о человеке» выдаётся за «от человека». stats-режим при этом
   честно возвращает ambiguous_identity (835-853) — два разных контракта
   идентичности в одном файле.
5. **L2-пересказы как свидетельства** — read-side провенанс не применяется в
   памяти-тулах (§8): производные факты вставляются неотличимо от прямых.

Дополнительно (не топ, но факт): fallback L1 теряет память/лор
(direct_l1.py:1029-1050); кастомный response_act деградирует в social_chat
(direct_l1.py:201-206); ordinary query_chat_memory не принимает автора
(tool_schemas.py:103-113); ToolContext.user_id не используется инструментами
памяти (tool_router.py:609).

---

## 10. Минимальные варианты закрытия (2-3 на разрыв; без нового тулa)

**G1 = bypass (дефект 1).** Варианты:
- a) Сузить условие 3738: подменять ответ только при story-интенте хода
  (например, L1 `response_act` ∈ {creative, historical_recall} / structure=story
  / явный lore-запрос детектором существующих маркеров); иначе story идёт в
  evidence L2 как источник. Cost: точечная правка условия + флаг; Risk:
  ложноположительное сужение — нужен fail-open на текущее поведение при
  неопределённости, тесты 10 сценариев §12 владельца.
- b) Поменять EN-описание схемы compile_lore_story (убрать «or give a
  comprehensive historical overview» → «topic/meme lore only»). Cost: одна
  строка схемы + байт-тест канона схем; Risk: минимальный, но сам по себе не
  чинит подмену (a — корневой).
- c) (не рекомендуется) отдельный аналитический канон «Летописца» — новый слой
  речи, против директивы владельца §6/§11.

**G2 = периоды (дефекты 2-3).** Варианты:
- a) Расширить СУЩЕСТВУЮЩИЕ схемы аддитивно: `query_chat_memory.stats` + `year`/
  `year_from/year_to` (SQL уже принимает since_ts/until_ts — database.py:8233-8241),
  `dig_into_lore` + опциональный `year_to` (bounds-пара). Cost: схема+нормализация+
  снапшот-тесты; Risk: низкий (аддитивно, defaults = прежнее поведение).
- b) Прокинуть author_ids/since/until фасада `search_long_term` в SQL-слой
  (сигнатуры уже готовы, summary_memory.py:2949-2959 → database.py:8223-8227) и
  поднять/задать per-window лимит сниппетов. Cost: маленький; Risk: низкий.
- c) Только промпт-фикс (пусть модель вызывает инструмент дважды на каждый год):
  без правки кода; Risk: недетерминированно, не решает rank-40 усечение.

**G3 = идентичность (дефект 4).** Варианты:
- a) `_dig_person_terms` → та же семантика, что `_resolve_author_id`
  (множество совпадений → честный ambiguous, дубликаты не сливаются). Cost:
  ~10 строк + тест; Risk: низкий.
- b) Принять в схемах `author`/`person` значение `[user:UID]`/число — резолв по
  ctx.user_id при «me/self»; Cost: аддитивная ветка в 2 местах + описание схем;
  Risk: низкий. Закрывает «искать по Telegram ID» из §6 владельца.

**G4 = провенанс чтения (дефект 5).** Варианты:
- a) Маркировка рендера: в dig facts/query fallback различать «прямая цитата vs
  пересказ/вывод» суффиксом reusing существующих `origin`/`classify_fact_provenance`
  (graphrag_provenance.py:187-208) — данные для модели, не приказ. Cost: рендер+
  тесты; Risk: низкий.
- b) Фильтр origin ∈ BOT_ORIGINS из фактических путей (аналог read_policy_rank).
  Cost: маленький; Risk: потеря полезного контекста при агрессивном фильтре.

**Новый инструмент: НЕ рекомендуется.** Существующие механизмы покрывают
потребности при исправлении маршрутизации/аргументов: SQL-слой уже умеет
author_ids/since/until (database.py:8223-8241), stats-контур уже умеет точные
измерения с честными refusal (§2.3), рёбра графа уже читаются
`lore_graph_slice` (database.py:8424-8533) — недостающее это фильтры/маркировка/
условие доставки, а не новый retrieval.

---

## 11. Что сохраняется (факты против «сломать»)

- `compile_lore_story`, `dig_into_lore`, fallback и legacy-ветки: сохраняются по
  директиве владельца §7 — аудит не находит причин удалять.
- Честные счётчики (method_label, coverage, unknown_count), numeric-гард,
  Метрика MetricResult, ГРАНИЦА ИСТОРИИ, honest-пометки capabilities — работающие
  механизмы, обязательные к сохранению.
- Канон «Летописца» — легитимен для story-интенции (владелец §8); правка текста
  канона не требуется для G1.
