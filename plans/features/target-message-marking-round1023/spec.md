# spec.md — F1 `target-message-marking-round1023`

> **Раунд 10.23** · Приоритет **P0** · Шаг 2 @Architect · Тип: backend/LLM-контекст + канон промптов
> **ADR:** `ADR-1023-1.md` (**Accepted**). **Задачи:** `tasks.md` (T-2097…T-2106).
> **ТЗ:** `plans/current_task.md`, «Контекст и Баг-фиксы ядра → Маркировка целевого запроса (Изоляция контекста)». Файл untracked, секреты не цитировать/не коммитить (R17/R18).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION 2.57.0.
> **Сквозной слой:** `plans/features/round1023-architecture.md` §3.2, §4.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| XML-рендер истории | `services/summary_xml.py:53` (`XmlGroundingBuilder.build`), элементы `:99-102` |
| Плоский рендер строки контекста | `services/canonical_context.py:242` (`format_context_item`) |
| Реестр точек подачи контекста | `services/canonical_context.py:103` (`CONTEXT_POINTS`, 14 точек; инвентарный тест `tests/test_memory_core_round1020.py:92`) |
| Фактчек-окно рендерится через `format_chat_context` | `services/chat_context.py:42` → `format_context_item` |
| Вызов XML-бинаря | `services/summary_generator.py:144` (`self.xml.build(rows, self.aliases)`) |
| Промпты Синтезаторов | `services/summary_prompts.py` (`SUMMARY_EDITOR_SYSTEM_PROMPT`), `services/factcheck_prompts.py` (`FACTCHECK_ANALYST_SYSTEM_PROMPT`), `services/chat_prompts.py` (`CHAT_SYSTEM_PROMPT`) |
| Канон-контур | `services/prompt_migrations.py` + `plans/docs/canon/**` + `PREV_*` (ADR-1013-3) |

### 0.1. Уточнения ТЗ / инварианты

- **Физически вырезать сообщение-команду из истории запрещено** (таймлайн/причинно-следственные связи). Разрешена только визуальная маркировка.
- Сопоставление — по **Telegram `message_id`** (`smart_messages.tg_message_id`), не по внутреннему `id` (коллизии).
- **Обратная совместимость:** нет `trigger_message_id` (или нет совпадения) → оба рендерера дают **байт-в-байт** прежний вывод.
- `<` в XML экранируется (`saxutils`); токен маркера содержит `<<<` → в XML он станет `&lt;&lt;&lt;`. Escape-стабильное ядро `[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` идентично в обоих рендерерах.

---

## 1. Цель

Дать LLM-Синтезатору однозначный указатель на сообщение-триггер, чтобы он **не пересказывал собственную команду как событие чата**, сохранив сообщение в истории.

## 2. Требуемое поведение

1. При рендере истории сообщение с `tg_message_id == trigger_message_id` получает визуальный тег `<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]`.
2. Маркер ставится **ровно на одном** сообщении; порядок/состав истории не меняется.
3. Промпты трёх Stage-1 Синтезаторов получают жёсткое правило: помеченное сообщение — инструкция, а не событие; запрещено пересказывать/анализировать/упоминать его в выжимке.
4. Маркер **не протекает** в финальный пользовательский текст (антиэхо).
5. Нет триггера/совпадения → прежний вывод без маркера.

## 3. Архитектура и контракты

### 3.1. Новый модуль `services/target_marking.py`

- `TARGET_MARKER = "<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]"` — единый токен для plain-рендера.
- `TARGET_MARKER_CORE = "[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]"` — escape-стабильное ядро (якорь промпт-правила и паритет-теста).
- `is_target_row(row, trigger_message_id) -> bool` — сравнение `row_get(row, "tg_message_id")` с триггером; `None`/пусто → `False`.
- `append_marker(body: str) -> str` — аккуратная склейка (один пробел-разделитель, без дублей).

### 3.2. `services/summary_xml.py`

- `XmlGroundingBuilder.build(messages, aliases=None, trigger_message_id=None)`.
- В `_build_element(row, aliases, trigger_message_id)`: `body = self._build_body(...)`; если `is_target_row(row, trigger_message_id)` → `body = f"{body} {TARGET_MARKER}"` **до** `_escape(body)`.
- `trigger_message_id is None` → вызов `_build_element` без изменений семантики (legacy).

### 3.3. `services/canonical_context.py`

- `format_context_item(..., is_target: bool = False)`; при `True` — `body = f"{body} {TARGET_MARKER}"` (plain, без экранирования).
- Дефолт `False` → все существующие вызывающие байт-в-байт неизменны (RAG/lore/tool_router/search/chat_context).
- `format_fact_line` не меняется (маркер — только для `kind="msg"`).

### 3.4. Проброс `trigger_message_id` из точек сборки (T-2100)

| Точка | Источник триггера |
|---|---|
| `summary_generator._run` → `self.xml.build(...)` | message_id команды `/summary` из handler'а (через новый параметр `trigger_message_id` в `_run`/публичный API); авто-крон → `None` |
| `chat_context.format_chat_context(rows, ..., trigger_message_id=None)` | message_id команды фактчека (handler) |
| `direct_chat_service` (рендер истории через `format_context_item`) | `message.message_id` текущего пользовательского хода |

`None` в любой точке → legacy-путь (без маркера). Никаких догадок, если сообщение не найдено в окне.

### 3.5. Промпт-правило (канон)

Единый блок `TARGET_INSTRUCTION_BLOCK` — фактически размещён в новом F1-модуле `services/target_marking.py` (импортируется в 3 Stage-1 промпта; вариант «общий блок в `prompt_style_blocks.py`» не выбран, чтобы не пересекаться со ступенью вливания `F3 → F4`). Смысл:

> «В истории чата будет сообщение с пометкой `[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` (перед ней может стоять `<<<`). Это инструкция от пользователя. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО пересказывать этот запрос как событие чата, упоминать его в выжимке или анализировать как часть обычного диалога. Просто выполни написанное.»

- Вставляется в `SUMMARY_EDITOR_SYSTEM_PROMPT`, `FACTCHECK_ANALYST_SYSTEM_PROMPT`, `CHAT_SYSTEM_PROMPT` (Stage-1; Вербализаторы историю не видят).
- Формулировка не цитирует запретные клише дословно (grep-тест отсутствия тропов не должен ловить сам запрет).

### 3.6. Канон-миграция (ADR-1013-3, атомарно, T-2102)

- Слепки `PREV_SUMMARY_EDITOR_R1023`, `PREV_FACTCHECK_ANALYST_R1023`, `PREV_CHAT_R1023` (прежние константы байт-в-байт).
- `services/prompt_migrations.py`: запись в `PROMPT_MIGRATIONS` (migrate) + `ROLLBACK_MIGRATIONS` (`rollback_prompt_canons`).
- `plans/docs/canon/**` синхронизируются.
- Один коммит: код + слепки + docs + тесты.

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| **NEW** `services/target_marking.py` | токен + matcher + append |
| `services/summary_xml.py` | `build(..., trigger_message_id=None)`; маркер в `_build_element` |
| `services/canonical_context.py` | `format_context_item(..., is_target=False)` |
| `services/chat_context.py` | проброс `trigger_message_id` |
| `services/summary_generator.py` | проброс `trigger_message_id` в `xml.build` |
| `services/direct_chat_service.py` | проброс триггера в рендеры строк |
| `handlers/summary.py`, `handlers/factcheck.py` | проброс `message.message_id` (у direct_chat id берётся внутри `DirectChatService._build_user_content` — `handlers/direct_chat.py` НЕ меняется) |
| `services/summary_prompts.py`, `services/factcheck_prompts.py`, `services/chat_prompts.py` | правило маркировки |
| `services/prompt_style_blocks.py` | константа блока (если выбран общий блок) |
| `services/prompt_migrations.py`, `plans/docs/canon/**` | канон-миграция + слепки |
| **не меняются:** `services/system2_handoff.py`, `services/negative_constraints.py`, каталог, DDL | — |

## 5. План тестирования (T-2104/T-2105)

1. `test_target_marking_round1023.py` (новый):
   - маркер ровно на одном сообщении (совпал `tg_message_id`);
   - `trigger_message_id=None` → вывод байт-в-байт прежний;
   - таймлайн/порядок/число сообщений не изменены; триггер присутствует (не вырезан);
   - паритет двух рендереров: `TARGET_MARKER_CORE` присутствует и в XML (`&lt;&lt;&lt; …`), и в plain (`<<< …`);
   - дубль `tg_message_id` → маркируется один (первый) / ровно один элемент;
   - антиэхо: симуляция финального текста без маркера; правило промпта присутствует в 3 константах.
2. Обновление эталонов: `tests/test_summary_xml.py`, инвентарные сэмплы `tests/test_memory_core_round1020.py` (T-2103).
3. Регресс: `test_summary_two_call_round1022.py`, `test_factcheck_two_call_round1022.py`, `test_direct_two_call_round1022.py`, `test_summary_xml.py`, `test_memory_core_round1020.py`, `test_prompt_migrations`. Полный pytest — 0 failed.

## 6. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Маркер ломает байт-эталоны обоих рендереров | Обновление эталонов в T-2103 тем же коммитом; legacy-путь при `None` |
| R2 | Medium | Маркер просачивается в финальный текст | Промпт-правило + антиэхо-тест; Вербализатор истории не видит |
| R3 | Medium | Неоднозначность при нескольких совпадениях | Строго по `tg_message_id`; тест на дубль |
| R4 | Medium | Канон-атомарность (ADR-1013-3) | Один коммит (T-2102) |
| R5 | R17/R18 | Сырая история/секреты в логах/отчётах | Только коды/числа |

## 7. Критерии приёмки

- Помеченное сообщение идентифицируется однозначно по `tg_message_id`; при отсутствии — байт-в-байт прежнее поведение.
- Промпт-правило присутствует в трёх Stage-1 Синтезаторах; канон-миграция атомарна и обратима.
- Таймлайн не изменён; маркер не протекает в финал.
- Полный pytest — 0 failed.

## 8. Feature flag / раскатка / откат

- Отдельного флага нет (поведение контекста). **Δ каталога = 0; DDL = 0.**
- Откат — `git revert` + обратная канон-миграция (`rollback_prompt_canons`).

## 9. Открытые вопросы (Human Gate)

- **ЗАКРЫТО (R1023F1-04):** для `/summary` маркер **недостижим** — observer (`summary_observer`, B9) принципиально не сохраняет команды в `smart_messages`, поэтому `trigger_message_id` команды никогда не совпадёт. Это известное ограничение F1 (саммари идёт legacy-путём); отдельный носитель триггера саммари — вне объёма F1. `trigger_message_id` в контракте сохранён для симметрии API.
- Способ проброса триггера в `summary_generator` — параметр публичного API `trigger_message_id` (T-2100).

## 10. Задачи

См. `tasks.md` (T-2097…T-2106). **T-2097** — этот spec + ADR-1023-1 (выполнен).
