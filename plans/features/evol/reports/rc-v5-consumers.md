# RC v5 — волна потребителей речевой проекции (B/E/F)

- Кандидат: ветка `rc/consumers` @ `47567a6d`, база `b8ea1d8c`.
- Worktree: `WorkspaceData\worktrees\c742e4de9e92c489\evol-reply-context-integrity-0-84aebcb8b554-dd8d1edb`.
- Контракт: `plans/features/evol/arch/reply-context-integrity-v5-contract.md` §4.1 (P1–P7), §4.2 (п.2–п.5), §4.4, §4.5, §7.1 R2, §7.2.
- Источник владельца: `plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md` §5.4, §9.2–§9.5.
- Шов: `services/canonical_context.py` (`format_speech_item`, `SpeechProjection`, `SpeechQuote`, `SpeechRelation`, `emit_speech_projection_event`), `media_marker(projection=…)`, `thread_chain.render_speech_line/render_reply_chains(projection=…)`.
- Внешние источники: не использовались (контракт — внутренний; поведение проверено тестами и рантайм-пробами).

## Что теперь верно по потребителям

### 1. Direct (обычный ответ, ответ на Reply, тред/ветка/окно)

- Одна проекция на весь payload хода (`DirectChatService` создаёт её до сборки блоков):
  `<Global_Context>`, `<Conversation_Thread>`, `<Conversation_Branch>`, эпизоды,
  `<RAG_Memory>`, `<Target_User>`, `<Current_Question>` и медиа-маркеры используют
  **её же**, поэтому одно сообщение адресуется одной меткой во всех блоках.
- Абсолютные даты, «Переслано:», маркер цели `<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]`,
  роль бота `(бот)`, автор цитаты человеком — сохранены; `tg:/msg:/fact:` и `[uid]`
  в речевых строках отсутствуют.
- L1 (машинная стадия) сознательно остаётся на сыром каноне: у него `[user:10]`,
  `(ответ на msg:10000)`, `[msg:N]` — по §5.4 специализированным стадиям нужны
  настоящие refs.
- Дедуп middle↔tail переведён с `re.findall(r"tg:(\d+)")` на структурный ключ
  (`_context_line_dedup_key`: типизированный ref в заголовке ИЛИ метка прогона).
  Слово «M1» в чужих словах ключом не становится — текст участника не читается.
- Образец:

      [30.04.2024 16:04 | Марина (U2) | M2]: разбор волокон цитата (автор: Вася (U1)): «там волокна разные» — выделенный фрагмент оригинала, ПРИОРИТЕТНЫЙ ПРЕДМЕТ ответа; полное исходное сообщение — контекст ↳ Reply M1

### 2. Текстовая инициатива

- Окно Writer'а (`direct_l1.render_window_lines(projection=…)`) и форма доставки
  (`build_l2_plan_block(projection=…, label_of=…)`) адресуют сообщения метками
  **той же** проекции, что и остальной payload инициативного Writer'а.
  Цель вне показанного окна называется честно («нет в показанном окне»), id не
  выдумывается. Personality Core / Expression / Humor / план L1 не тронуты.
- Образец:

      [M1] Вася (U1): первая реплика
      [M2] Марина (U2): ответ ↳ Reply M1

### 3. Результаты инструментов

- `get_recent_history` (все страницы), `dig_into_lore` (сообщения и факты графа),
  строки статистики истории — речевые строки с метками; факт адресуется `F<n>`,
  дата/автор/`Переслано:`/тип медиа сохранены.
- `fact_check`: модель больше **не получает** `run_id` (это метаданные §9.2;
  корреляция осталась в машинном слое — `tf.stage_event(..., pipeline_run_id=…)`
  и запись прогона в БД), зато получает `claim_author`, `as_of`,
  `original_published_at`, `evaluated_period` и **структурный список проверенных
  ссылок** `evidence[] = {url, published_at, source_kind, excerpt}`. Раньше ссылки
  были доступны только внутри текста вердикта.
- Образец:

      [30.04.2024 16:00 | Вася (U1) | M1 | Переслано: Канал X]: первая реплика

### 4. Память / RAG (и архивные строки)

- `build_rag_context(projection=…)` (оба режима: origin-метки и legacy
  `<context>/<user_gossip>/<bot_knowledge>`): `fact:<id>` → `F<n>`, `tg:<id>` → `M<n>`,
  метка происхождения (`[чат]`, `[dream]`) и пометка устаревания сохранены;
  дата остаётся датой (`[04.2024 …]`) — не заменяется порядком в массиве.
- Саммари-генератор (`summary_generator`) проверен отдельно: он строит
  `<historical_graph_facts>/<memory>/<facts>` из `author: text` и 4-кортежей RAG
  (без `item_id`), `summary_xml` использует `id=`/`reply_to_id=` как атрибуты —
  служебных refs в его речи нет, править не потребовалось.
- Образец:

      [чат] [04.2024 | Вася | M1]: обсуждали релиз 2.58.153
      [dream] [04.2024 | Марина | F1]: факт из графа о волокнах

### 5. Летописец (lore)

- Факты графа и окна диалогов идут через общую проекцию прогона: `fact:`/`tg:`/uid
  заменены метками, дата/автор/`Переслано:`/тип медиа сохранены; обратная карта
  уходит в защищённое событие `speech_projection`.
- Образец:

      [04.2024 | Вася | F1]: факт о чате

### 6. Мем (текст/подпись)

- В выжимке (`_default_summarize`) поле `id` сообщения = метка прогона (`M1`), а не
  внутренний номер строки БД: выжимка становится словами мема и надписью картинки.
  Порядок сообщений и их тексты не тронуты.
- **Тексты промптов не изменены.** sha256 фрагментов `services/meme_initiative.py`
  совпадает с базой `b8ea1d8c`:
  `MEME_JOKE_PROMPT 999976f3c08993af`, `MEME_IMAGE_PROMPT 4a9a4936c89fbd54`,
  `JOKE_PROMPT_BLOCK_ID c2df24960ec76e31`, `IMAGE_PROMPT_BLOCK_ID 351d828a2d5c34bb`
  (candidate == base). Плейсхолдеры `{joke}`/`{max_symbols}`, логика этапов A/B/C,
  бюджеты и лимиты не менялись.
- Образец payload модели:

      {"messages":[{"id":"M1","text":"привет"},{"id":"M2","text":"пока"}]}

### 7. prompt_composer (наблюдаемость §4.5)

- `compose_speech_system(..., context_representation=…, speech_projection=…)` →
  аддитивные поля `PromptManifest.context_representation` (`internal` | `writer`) и
  `PromptManifest.speech_projection`. `render_effective_layers` и
  `manifest_for_events` отдают `context_representation` + сводку проекции
  (`representation`, `counts`, `suppressed_field_types`) **без пар «метка → ID» и
  без текстов**; пары остаются в защищённой трассе (`speech_projection`).
- Поле заполняется фактом: `writer`, если user-часть реально собрана речевой
  проекцией, иначе `internal`.

### 8. Соседние речевые поверхности (вне списка волны, но в тех же модулях)

- Узкое окно FactCheck (`handlers/factcheck._fetch_chat_context`) и ответы поиска
  (`handlers/search._fetch_chat_context`) переведены на тот же шов; окно и
  `<reply_chains>` узкого маршрута получают **одну** проекцию.
- `chat_context.format_chat_context`: вытеснение строк окна бюджетом больше не
  молчит — печатается `…часть окна не показана (N)` с фактическим счётчиком
  (контракт §5.4 п.153, §8 п.5). Это единственное изменение сверх «чистой речи»:
  без него речевая строка (+2…5 % длины) вытесняла на 2–3 старых реплики больше
  и теряла их без объявления.

## Инварианты, которые проверены

- Обратная карта: каждая метка в речевом payload разрешается (`raw_of`) в реальный
  `tg:`/`msg:`/`fact:` или user id; меток-сирот нет.
- Один прогон: сообщение, показанное в окне и в цепочке, адресуется одной меткой.
- Рубильник `flags.context_speech_projection` OFF → прежний сырой канон во всех
  потребителях; Composer ON/OFF одинаков по составу отношений (различие — только
  представление, не связи).
- Никакой чистки готового текста regex'ом, новых LLM-вызовов, бюджетов и схем БД.
  Единственный новый разбор собственного маркера — `MEDIA_MARKER_RE` (контрактный
  regex самого маркера, а не текста участника).

## Мутации (файлы приложения не правились — рантайм-подмена)

| Мутация | Что ломаем | Поймано |
| --- | --- | --- |
| `hide_reply_edge` | убрать подтверждённый reply-край | 1 тест (`test_forward_and_bot_role_are_kept_in_thread`) |
| `drop_date` | выкинуть абсолютную дату из речевой строки | 5 тестов (Direct/фактчек/инструменты/RAG/поиск) |
| `collapse_same_name` | слить одноимённых по нику | 3 теста (`test_same_name_participants_are_not_collapsed` и др.) |
| `label_inside_quote` | вклеить метку внутрь «…» | 1 тест (`test_quote_text_never_contains_run_labels`) |
| `leak_tg_ref` | вернуть сырой `tg:` в речевой слот | 14 тестов |

Скрипт мутаций: `WorkspaceData/runs/rc_v5_mut_plugin.py` (вне репозитория).

## Прогоны

- `tests/test_evol_reply_context_consumers.py` — 37 passed (новый файл).
- Профильный набор (consumers, direct_chat, factcheck_context_cfg06, evol014_meme,
  seam, summary_memory, memory_core, tool_router, tool_chains, recent_history,
  initiative_coordination, asap8_f6_initiative, initiative_speech_layers,
  initiative_delivery_telemetry, soul1_w5_initiative_vitality,
  factcheck_deep_context, native_reply_media_context, evol015_quote_pipeline,
  target_marking) — **801 passed, 3 failed**; все три — `test_initiative_coordination`,
  падают и на базе `b8ea1d8c` (pre-existing).
- Широкий прогон `tests/ -k "factcheck or direct or summary or memory or tool or
  initiative or evol or soul1 or mca or native_reply_media or target_marking or
  addtr"`: база `b8ea1d8c` — 43 падения, кандидат `47567a6d` — 44; единственное
  различие — сетевой `test_factcheck_post_release_w1` флейк, который падает и на
  базе при изолированном прогоне (разные сообщения: `DID NOT RAISE` против
  `assert 'empty_results' == 'timeout'`). Регрессий нет.
- Отдельно проверенные и осознанно обновлённые пины старого формата:
  `test_factcheck_context_cfg06` (паритет узкого пути — теперь по содержанию через
  обратную карту + проверка объявленной неполноты), `test_factcheck_tool_route_cfg06`,
  `test_cfg07_guard_tail`, `test_factcheck_attribution_cfg06`,
  `test_mca20_integration_round1045`, `test_mca20_rework1_f1_f2`,
  `test_tr_fix2_reply_ref` (`run_id` ушёл в машинный слой),
  `test_addtr_entry_caption` (медиа-маркер меткой),
  `test_factcheck_orchestrator_cfg06` (`author_uid` в `ContextMessage`),
  `test_evol014_meme_initiative` (метка вместо внутреннего номера).
  Основание правок — §5.4 (CONTEXT-FIDELITY: меняется только форма адресации) и
  §9.2 (служебные ID не озвучиваются).

## Что осознанно не сделано / риски

1. `goal`/`rationale` инициативы — свободный текст Наблюдателя; он может содержать
   числа, которые Наблюдатель видел в машинном виде (`[msg:N]`). Чистить готовый
   текст запрещено (§9.3 п.6), а менять промпт машинной стадии — отдельная волна.
   Окно и форма доставки Writer'а при этом уже метками, поэтому адресация не
   зависит от этого текста.
2. Блок медиа-свидетельства (`media_readiness.evidence_block`) сохраняет
   `изображение msg:<id>` — это провенанс конкретной ревизии Vision, а не строка
   диалога; в перечне P1 его нет, и он используется общим для FactCheck путём.
3. `<UserResolutionMap>` (карта «имя ↔ user_id») остаётся: это объявленная
   адресная карта для сопоставления имён, её инструкция — заводской
   версионированный промпт (изменение требует бампа ревизии, запрещено другим
   пакетом). Речевой контекст вокруг неё — без номеров.
4. Оценка R7 «дельта размера ≤ 0» не выполняется и здесь: `U`-метки дают +2…5 %
   на строку (это уже отмечено в ревью шва). Взамен окно теперь **объявляет**
   вытеснение, а не теряет строки молча.
5. Широкий фид FactCheck и узкое окно строят каждая свою проекцию (у них разные
   прогоны/точки входа); внутри одного payload представление всегда одно.
6. В рабочем дереве уже были изменены 42 файла
   `plans/features/evol/audit/evidence/*` (PNG/JSON скриншоты UI-волны) — не мои,
   не коммитил и не откатывал.
