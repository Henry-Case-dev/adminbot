# W1 — EVOL-015: Telegram quote (выделенный фрагмент reply) полный конвейер

Lane: Builder EVOL-015, worktree `evol/impl` (shared checkout), 30.10.2026.
Requirement source: `plans/current_task.md` §4 (EVOL-015, 5 acceptance criteria).
Audit basis: `backend-defects-audit.md` + production-base corrections in
`base-revalidation.md` (DROP POINT #1 ingest `handlers/summary.py:388-403`;
DROP POINT #2 context SELECTs `database.py:7785+`; ChainItem `thread_chain.py:30-42`;
`claim_envelope.py:850`; dead-in-prod renderer `canonical_messages.py:232`).

## 1. Schema delta (v38, additive only)

`services/database.py`:

* `_SCHEMA_VERSION_QUOTE_METADATA = 38` (next free step; 37 = humor_samples, untouched).
* `_QUOTE_METADATA_COLUMNS` — 3 nullable-колонки `smart_messages`:
  * `quote_position INTEGER` — Telegram `TextQuote.position` **verbatim**
    (UTF-16 code units). Хранится как есть, никогда не пересчитывается поиском
    по тексту (повторяющиеся подстроки/эмодзи/переносы безопасны по построению).
  * `quote_is_manual INTEGER` — 0/1 (bool из TextQuote); NULL = неизвестно.
  * `quote_entities TEXT` — safe JSON (≤32 entities, ≤2000 chars; только
    скалярные поля type/offset/length/url/language/custom_emoji_id,
    `user` → `user_id`); NULL = отсутствуют/не влезли.
* `MigrationStep(38, "quote_metadata_v38")` → `_migrate_quote_metadata_v38()`:
  `ALTER ADD COLUMN` под guard `PRAGMA table_info` (паттерн v16), self-guard,
  повтор — no-op, строка в книге `schema_migrations` (PK version=38).
  Backfill НЕ требуется: старые строки = честный NULL, цитаты задним числом
  не дорисовываются (требование «история без quote-меты не подтверждается
  ретроспективно»). **PG — no-op**: `smart_messages` не существует в pg_db
  (memory-контур SQLite-only, прецедент v16/v28/v30/v36) — проверено `rg smart_messages services/pg_db.py` (0 hits).
* `quote_text`/`quote_author_id` существовали с v16 — заполняются как раньше.

Backward compatible: строки/вызовы без quote-данных ведут себя байт-в-байт
как сегодня (все новые параметры — keyword-only с default None).

## 2. Data flow (ingest → storage → context → prompt)

```
Telegram update (aiogram ≥3.31, Message.quote: TextQuote)
  └─ handlers/summary.py observer
       ├─ _extract_quote_fields(message)          [text/author/position/is_manual/entities]
       │    ├─ author = reply_to_message.from_user.id (Telegram не отдаёт автора в TextQuote)
       │    └─ _serialize_quote_entities(entities) → safe JSON | None
       ├─ _emit_quote_event: "quote_present" | "quote_missing_in_transport"  (component=ingestion)
       └─ message_identity.save_live_message(..., quote_position, quote_is_manual, quote_entities)
            ├─ identity ON  → db.save_smart_message_identity(rec)   [INSERT: 31+10 колонок]
            └─ identity OFF → db.save_smart_message(..., quote_*)   [legacy-путь тоже несёт цитату]

storage: smart_messages (одна строка на сообщение: chat_id + tg_message_id +
reply_to_id → связь с оригиналом; quote_author_id → автор; всё chat-scoped)

context assembly:
  ├─ db.get_smart_window / get_smart_raw / get_recent_messages
  │     SELECT +5 quote-колонок (DROP POINT #2 устранён на уровне чтения)
  ├─ db.get_smart_message_by_tg_id (+3 колонки) → thread_chain.collect_thread_chain
  │     ChainItem += quote_text/quote_author_id/quote_position/quote_is_manual
  │     + quote_original_available (True/False/None — честный статус доставки
  │       оригинала в ЭТУ цепочку; событие quote_unavailable при False)
  └─ thread_chain.format_chain_line (единый рендер direct + фактчек)
        ├─ без цитаты → байт-в-байт прежняя каноническая строка
        └─ с цитатой → inline-аннотация (одна строка — «нет голого текста»
              per-point pattern сохранён):
              trigger:  «цитата (автор: <uid>): «...» — выделенный фрагмент
                         оригинала, ПРИОРИТЕТНЫЙ ПРЕДМЕТ ответа; полное
                         исходное сообщение — контекст»
              history:  «цитата (автор: <uid>): «...» (выделенный фрагмент
                         оригинала выше по цепочке)»
              unavailable: «... — выделенный фрагмент, оригинал недоступен
                         (контекст ограничен)»
              + событие quote_delivered_to_context (component=context)

prompt (rendering seams, W1 scope = rendering only):
  ├─ claim_envelope.SpeechUnderstanding.quote_text (new, default "")
  │   build_speech_understanding(..., quote_text=...) →
  │   render_speech_block: первой строкой «Предмет вопроса — выделенная
  │   цитата (её автор — не ты): «...». Полное исходное сообщение —
  │   контекст, отвечай по выделенному фрагменту.»
  └─ canonical_messages.CanonicalMessage v2 (+position/is_manual/entities;
      CANONICAL_ENVELOPE_VERSION="mca22/canonical/v2");
      format_canonical_envelope: «> <текст> (автор цитаты: <uid>;
      фрагмент UTF-16 offset <N>) — выделенный фрагмент оригинала»
```

Три требуемых режима различимы: (1) обычный reply — без цитаты, поведение
прежнее; (2) reply с цитатой — фрагмент = предмет, оригинал = контекст;
(3) цитата при недоступном оригинале — честная пометка «контекст ограничен».

## 3. Diagnostics taxonomy (mca_events, R17: только id/коды, ноль текстов)

| stage | component | outcome | когда |
|---|---|---|---|
| `quote_present` | ingestion | success | Telegram доставил quote с непустым text |
| `quote_missing_in_transport` | ingestion | skipped | reply есть, quote не доставлен (нормальный обычный reply; агрегат делает доставку наблюдаемой — регресс SDK виден ростом доли) |
| `quote_delivered_to_context` | context | success | цитата реально отрендерена в LLM-контекст (thread/reply_chains) |
| `quote_unavailable` | context | skipped | ход с цитатой, а оригинал в цепочку не доставлен (нет строки/без текста/бюджет) |

Код таксономии — в `stage` (свободное code-поле контракта §17.1); `outcome`
ограничен закрытым словарём mca_events. `services/mca_events.py` НЕ менялся
(чужой/общий файл) — расширение REASON_CODES не потребовалось.

## 4. Tests (`tests/test_evol015_quote_pipeline.py`, 18 PASSED, offline)

Run: `C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest tests/test_evol015_quote_pipeline.py -q` → **18 passed** (worktree cwd).

| AC (current_task §4) | Тест |
|---|---|
| 1: «если S Pen» + «Че это такое» → вопрос про S Pen, без хардкода | `test_a_spen_quote_marks_subject_in_context` (структурный ассерт рендера: «ПРИОРИТЕТНЫЙ ПРЕДМЕТ», автор, оригинал-контекст; механика универсальна — test_b на другом тексте) |
| 2: середина сообщения / повтор подстроки / переносы+эмодзи / UTF-16 | `test_b_mid_message_repeated_substring`, `test_c_newline_emoji_utf16_offset_verbatim` (позиция 8 при py-индексе 4 — вербатим, не пересчитан) |
| 3: обычный reply без регресса; цитата с недоступным оригиналом | `test_d_plain_reply_byte_parity` (байт-в-байт = format_context_item), `test_e_quote_unavailable_original` («оригинал недоступен», без обещания предмета) |
| 4: структурно видно сохранение и доставку; видно, какое выделение получено | round-trip `test_f` + ассерты рендера (текст цитаты в строке/блоке) + `quote_position` в БД и рендере (canonical envelope: UTF-16 offset) |
| 5: оба чата, реконструкция сохранённой истории, fallback | `test_g_two_chats_isolation`, `test_f_persist_roundtrip_restart` (переоткрытие БД), `test_legacy_off_path_persists_quote` (identity OFF), `test_v38_restart_idempotent_and_old_row_intact` (старые строки = NULL, задним числом не дорисовываются) |

Плюс: миграция v38 (колонки/книга/идемпотентность), full-metadata ingest
(`_extract_quote_fields`: биты типов → None, quote без reply → автор None),
bounded-сериализация entities, окно/SELECT'ы несут quote-поля, телеметрия
(4 стадии, R17-ассерты), рендеры (`<Speech_Understanding>` предмет + байт-
паритет прежнего блока; canonical envelope суффикс/легаси-форма).

Combined focused suite (затронутые швы): test_memory_core_round1020 (реестр
«нет голого текста» — цитата inline, паттерн точки не нарушен),
test_mca03_message_identity_round1027, test_mca08_character_speech,
test_mca22_core/truthset_round1027, test_factcheck_deep_context_round1023,
test_history_w4_fixes, test_native_reply_media_context_round1024,
test_target_marking_round1023 + новый файл → **376 passed, 0 failed**.
`python -m compileall services handlers -q` → exit 0.

## 5. Coordination notes (shared worktree / чужие скоупы)

1. **direct_chat_service.py — вне моего write scope, не менялся.** Рендер-шов
   готов, но два потребителя нуждаются в одно-двухстрочной проводке владельцем
   dcs-полосы: (a) `_build_speech_understanding` — передать
   `quote_text=quote.text` живого сообщения в `build_speech_understanding`
   (сейчас Speech_Understanding получает только флаги; рендер предмета уже в
   claim_envelope и покрыт тестом); (b) `_context_row_line`/`_render_current_question`
   — опционально добавить аннотацию цитаты в Global_Context/Current_Question
   (колонки в SELECT'ах уже есть). Базовая доставка Writer'у в этой волне —
   `<Conversation_Thread>/<Conversation_Branch>` + `<reply_chains>` фактчека
   через `thread_chain.format_chain_line`.
2. **Race note (пре-существующий):** ход-триггер персистится observer'ом;
   если reply-путь выиграет гонку, строка триггера (и его цитата в треде)
   появится с задержкой — то же поведение, что у текста триггера в треде;
   Current_Question всегда несёт живой текст (dcs). Фиксится проводкой (1a)
   — live quote идёт в Speech_Understanding напрямую из aiogram-сообщения.
3. **mca_events.py не расширялся** (общий файл): таксономия в `stage`,
   outcome из закрытого словаря. Если владелец mca-13 захочет выделить
   quote-стадии в REASON_CODES — отдельная правка его полосы.
4. **Чужие падения в общем чекауте (не EVOL-015):** при параллельном прогоне
   смежных файлов падают `test_mca07_retrieval_context_round1027.py::test_answer_cache_policy_helper`
   (убран `_legacy_text_replay_enabled` — правка полосы EVOL-031 в dcs,
   старый тест ещё не обновлён) и `test_budget_global_toggle_round1024.py::TestCatalog::test_counts`
   (581 vs 587 — дрейф param_catalog другой полосы; падает и без моего диффа —
   проверено прогоном на чистом дереве). Мой дифф на них не влияет.
5. Write scope: только `handlers/summary.py`, `services/database.py`,
   `services/message_identity.py` (модуль нормализации ингест-пути — ضمن
   скоупа «any message-normalization module on the ingest path»),
   `services/thread_chain.py`, `services/canonical_messages.py`,
   `services/claim_envelope.py`, `tests/test_evol015_*.py`, этот отчёт.
   Git-коммиты не создавались (по брифу).

## 6. Incidental findings

* `related-nonblocking`: `save_smart_message` до v38 молча терял
  quote_text/quote_author_id на OFF-пути (identity OFF) — закрыто этой
  волной (kw-only quote-блок + проводка в OFF-ветке save_live_message).
* `unrelated/pre-existing`: падения из п.4 (полосы EVOL-031/param_catalog).
* `uncertain`: точная частота `quote_missing_in_transport` на проде станет
  видна только после выката (счётчик нормальных обычных reply).

---

## 7. Follow-up (тот же worktree, 30.10.2026): SQL-регрессия + dcs-проводка

### 7.1 SQL failure `message_identity.py:268` — root cause и статус

**Root cause (подтверждён воспроизведением, а не предположением):** в
промежуточном состоянии моей же правки литерал VALUES канонического INSERT
(`save_smart_message_identity`, database.py ~:8237) потерял хвостовую запятую
перед `",".join("?" * len(_SMART_MESSAGES_ORIGIN_COLUMNS))`: строки
`"...,?,"` + `"?,?,?"` склеивались в `...,?,??,?...` (два `?` без запятой) →
`sqlite3.OperationalError: near "?"` на ЛЮБОМ identity-INSERT (41 колонка /
29 плейсхолдеров с адъянсенцией). Параллельная полоса поймала именно это
окно на disk-состоянии (shared worktree): 5 падений в
test_mca22_core_round1027, все через `save_live_message → save_smart_message_identity`.

**Resolution:** исправлено в этой же волне ДО получения отчёта — литерал
приведён к `"?,?,?,?,"` (проверено исполнением точного выражения из файла:
41 колонка / 41 плейсхолдер / без адъянсенции; одноразовый probe в
WorkspaceData/runs, см. probe_sql.py). Обе ветки персистентности сходятся:

* identity ON: INSERT 31 фикс.+10 origin колонок = 41 плейсхолдер = 41 параметр;
* identity OFF: `save_smart_message` INSERT 25 колонок = 25 плейсхолдеров.

**Evidence (текущее дерево):** `pytest tests/test_mca22_core_round1027.py -x -q`
→ **58 passed** (точная команда репродукции из брифа); общий прогон
mca22 core+truthset, evol013 (dcs-телеметрия), mca08, mca03, memory core,
factcheck context, native reply media, target marking + evol015 →
**301 passed / 143 passed**, compileall exit 0. На момент проверки ни одного
падения SQL в дереве не осталось; если у параллельной полосы остался
зафиксированный лог с ДРУГИМ SQL (не `...media_group_id) VALUES` с `??`),
нужен точный statement — в текущем дереве таких путей нет.

### 7.2 dcs-проводка (минимальная, аддитивная)

`services/direct_chat_service.py::_build_speech_understanding`:

* из живого сообщения читается `message.quote.text` (Telegram-native
  `TextQuote`); не-str/пустой → None (честный unknown);
* сам факт quote в транспорте служит структурным маркером присутствия
  (`quote_text_present=True`) — родной эквивалент ручной `>`-цитаты, которую
  `build_speech_understanding` уже детектит в тексте; фрагмент передаётся
  в `_ce.build_speech_understanding(..., quote_text=...)`;
* `<Speech_Understanding>` рендерит предмет вопроса первой строкой
  («Предмет вопроса — выделенная цитата (её автор — не ты): «…». Полное
  исходное сообщение — контекст, отвечай по выделенному фрагменту.»);
* атрибуция автора по-прежнему только из mca-22-контура (`bundle`), новых
  вызовов резолвера нет; чужие правки полосы EVOL-013 (`_exc_brief`,
  cause_class) не затронуты; Global_Context/Current_Question НЕ менялись —
  в дизайн-доке (§5 этого файла) их аннотация помечена опциональной.

Test: `test_dcs_wiring_live_quote_reaches_speech_block` — (a) живой quote
доходит до блока-предмета, (b) обычный reply — прежнее поведение,
(c) битый текст цитаты → unknown, (d) mca-22-атрибуция сохранена.
Полный набор полосы: **19 passed**; общая проверка швов → **301 passed**.
