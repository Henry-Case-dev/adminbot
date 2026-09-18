# spec.md — F3 `verbalizer-response-modes-round1023`

> **Раунд 10.23** · Приоритет **P0** · Шаг 2 @Architect · Тип: backend/LLM + канон промптов
> **ADR:** `ADR-1023-3.md` (**Accepted**, UPD владельца 19.09.2026 — канальные правила). **Задачи:** `tasks.md` (T-2116…T-2125, +T-2183…T-2186).
> **ТЗ:** «Умный Вербализатор (3 режима общения)». Untracked, секреты не цитировать/не коммитить (R17/R18).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**.
> **Зависит от:** F1, F2 (канон-контур). **Сквозной слой:** `round1023-architecture.md` §3.1, §3.4, §4.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Общий контракт handoff | `services/system2_handoff.py` (`parse_factcheck_analysis:75`, `validate_summary_digest:128`, `parse_direct_synthesis:140`) |
| Двухвызовный фактчек | `services/factcheck_service.py::_check_claim_two_call` |
| Двухвызовное саммари | `services/summary_generator.py::_generate_two_call` (`:298`) |
| Direct System 2 | `services/direct_chat_service.py` (при непустом `tool_trace`) |
| Стилевые блоки | `services/prompt_style_blocks.py` (`STYLE_BLOCKS_SUFFIX`, `CLICHE_RETRY_SYSTEM_PROMPT`) |
| Детектор клише/loop | `services/negative_constraints.py::verbalize_validated` (`:132`, ≤2 ретрая) |
| Narrator-промпты | `services/summary_prompts.py:88` (`SUMMARY_NARRATOR_SYSTEM_PROMPT`), аналоги в `chat_prompts.py`/`factcheck_prompts.py` |
| Канон-контур | `services/prompt_migrations.py` + `plans/docs/canon/**` |

### 0.1. Ключевой конфликт (решён в ADR-1023-3)

`response_mode` нельзя получить третьим LLM-вызовом — это нарушило бы **physical-two-call-pipeline**. Роутер живёт **внутри Stage-1** (поле JSON). Второй конфликт: `deep_research` (Markdown/таблицы) vs R11 (plain-саммари) — решается разделением «контент (режим)» и «канал (plain/rich)».

## 1. Цель

Синтезатор Stage-1 определяет `casual` / `serious` / `deep_research` и передаёт его Вербализатору Stage-2; Вербализатор по режиму формирует ответ, убирая «высокомерного профессора» и жалобы на «ленивого юзера», сохраняя саркастичный двачерский характер и типографику (`-`/`""`).

## 2. Требуемое поведение

1. `response_mode` присутствует в JSON Stage-1 и валидируется/нормализуется.
2. Роутер — только в Stage-1; число физических LLM-вызовов **не растёт**.
3. Три режима дают различимый стиль (casual: торопливое письмо без Markdown; serious: грамотно, минимальное форматирование, лёгкая циничная ирония; deep_research: полный структурированный отчёт, если он передан).
4. Типографика: только короткий дефис `-` и двойные кавычки `""`; запрещены `—` и `«»`; разрешён мат/сленг; нет понтов «я сделал за тебя работу».
5. Fallback при отсутствии/невалидном режиме → `serious` (fail-safe).
6. `deep_research` не ломает R11/plain-контракт саммари (см. ADR §Decision 5).
7. **Правила разметки по каналам (UPD владельца, обязательны):** прямой чат — таблицы запрещены в любом виде, для `deep_research` обязательны жирные акценты + буллиты `- `; статья (`sendRichMessage`) — полный Markdown/HTML с таблицами. Жёсткий маппинг — §3.6.

## 3. Архитектура и контракты

### 3.1. `services/system2_handoff.py` (T-2117)

- `RESPONSE_MODES = ("casual", "serious", "deep_research")`.
- `normalize_response_mode(value) -> str` — неизвестное/пустое/`None` → `"serious"`; никогда не бросает.
- `parse_factcheck_analysis`, `parse_direct_synthesis` — читают `data["response_mode"]`, нормализуют, кладут в результат.
- **Новый** `parse_summary_handoff(raw) -> dict | None` — строгий JSON `{"response_mode": ..., "digest": "..."}`; `digest` валидируется существующими правилами (`strip_reasoning_tags`, `contains_system_ids`, запрет «Архивная справка»).
- `validate_summary_digest(raw) -> str | None` **сохраняется** как backward-compatible обёртка (возвращает `digest`); если raw — не JSON, но валидная Markdown-выжимка → `digest=raw`, mode=`serious`.
- `response_mode` не попадает в user-content Stage-2 и не логируется как содержимое (R17).
- Порядок полей: `response_mode` добавляется последним; F7 (correlation-id) — **после** F3, аддитивно.

### 3.2. Stage-1 промпты возвращают `response_mode` (T-2118)

- `SUMMARY_EDITOR_SYSTEM_PROMPT` → JSON `{"response_mode": …, "digest": …}` (выжимка — в `digest`).
- `FACTCHECK_ANALYST_SYSTEM_PROMPT` → добавляется поле `response_mode` в существующий JSON.
- `CHAT_SYNTHESIZER` (direct) → добавляется поле `response_mode`.
- Инструкция режима: casual — бытовой треп/споры/короткие вопросы; serious — средняя сложность; deep_research — глубокий анализ/структура/масштабный поиск.

### 3.3. Типографика и режимные блоки (T-2119/T-2120)

- `TYPOGRAPHY_BLOCK` в `services/prompt_style_blocks.py` (общий для всех режимов): только `-`/`""`; запрет `—`/`«»`; разрешён мат/сленг; без «я сделал за тебя работу».
- `MODE_CASUAL_BLOCK` / `MODE_SERIOUS_BLOCK` / `MODE_DEEP_RESEARCH_BLOCK` — общие режимные блоки (переиспользуются всеми модулями, а не 9 отдельных констант).
- Narrator system = базовый narrator-промпт модуля + `STYLE_BLOCKS_SUFFIX` + `TYPOGRAPHY_BLOCK` + выбранный `MODE_*_BLOCK`.

### 3.4. Выбор промпта по режиму (T-2121)

- `summary_generator`, `factcheck_service`, `direct_chat_service` в Stage-2 выбирают `MODE_*_BLOCK` по `response_mode` из валидированного объекта Stage-1 **и канальный `FORMAT_*_BLOCK`** по каналу доставки (см. §3.6.2).
- Интеграция с `verbalize_validated` сохраняется; `enabled_rules` для plain-каналов: `DEFAULT_ENABLED_RULES | {"bullet_list", "plain_no_tables"}` (см. §3.6.3, ADR §Decision 5/10); на rich-канале — без `plain_no_tables`.

### 3.5. Канон-миграция (T-2122, ADR-1013-3)

- Слепки `PREV_SUMMARY_NARRATOR_R1023`, `PREV_FACTCHECK_VERBALIZER_R1023`, `PREV_CHAT_VERBALIZER_R1023`; `PROMPT_MIGRATIONS` + `ROLLBACK_MIGRATIONS`; `plans/docs/canon/**`; тесты — один коммит (ступень F1→F2→F3).

### 3.6. Правила разметки по каналам (UPD владельца, обязательны) — T-2183…T-2186

**Причина (защита от ParseError):** Telegram Bot API не поддерживает таблицы ни в одном текстовом `parse_mode`. Сырая табличная разметка от модели даёт битые entities → `BadRequest: can't parse entities` (ParseError) и ответ **не уходит вовсе**. Поэтому разметка жёстко привязана к **каналу доставки**, а не только к режиму: «режим определяет тон/полноту; канал определяет разрешённую разметку; таблицы — только rich-канал».

#### 3.6.1. Итоговый контракт «канал → формат»

| `response_mode` | Сценарий А — Прямой чат (обычное сообщение) | Сценарий Б — Статья (`sendRichMessage`) |
|---|---|---|
| `casual` | plain-текст, Markdown **запрещён** (как было, `parse_mode=None`) | не применяется (статья — только саммари) |
| `serious` | plain-текст, Markdown **запрещён** (как было) | не применяется |
| `deep_research` | **safe-формат:** жирный `<b>…</b>` для акцентов + буллиты `- `; **таблицы ЗАПРЕЩЕНЫ** во всех видах (Markdown `| … |`, HTML `<table>`, ASCII-сетки) | **РАЗРЕШЕНО ВСЁ:** полный Markdown/HTML, сложные таблицы, сетки, глубокая разметка |

#### 3.6.2. Промпт-блоки (T-2183)

- В `services/prompt_style_blocks.py` добавляются **канальные форматные блоки** (разделение форматной логики, не монолит):
  - `FORMAT_PLAIN_BLOCK` — Сценарий А: обязательные жирные акценты (`<b>…</b>`) + `- `-буллиты; **категорический запрет таблиц** любых видов; без `#`-заголовков и тяжёлой разметки. Запрет таблиц **не означает** нечитаемый монолит: перечисления — только буллитами, акценты — жирным.
  - `FORMAT_RICH_BLOCK` — Сценарий Б: полный Markdown/HTML разрешён, включая таблицы, сетки и глубокую структуру.
- `MODE_CASUAL_BLOCK` / `MODE_SERIOUS_BLOCK` — без изменений (Markdown запрещён; `- `-буллиты допустимы как plain).
- `MODE_DEEP_RESEARCH_BLOCK` больше не самодостаточен: итоговый narrator-промпт `deep_research` = базовый narrator + `STYLE_BLOCKS_SUFFIX` + `TYPOGRAPHY_BLOCK` + `MODE_DEEP_RESEARCH_BLOCK` + **ровно один** канальный блок (`FORMAT_PLAIN_BLOCK` | `FORMAT_RICH_BLOCK`).
- Выбор канального блока детерминирован каналом доставки: direct/factcheck/plain-саммари → `FORMAT_PLAIN_BLOCK`; rich-саммари Article (F6) → `FORMAT_RICH_BLOCK`.

#### 3.6.3. Валидация и guard (T-2184)

- Новый детектор `detect_plain_tables(text) -> bool` (Markdown `| … |`-строки, `<table`, ASCII-сетки `+---+`, разделители `---|`).
- В `services/negative_constraints.py` добавляется правило `"plain_no_tables"` (по умолчанию выключено; включается **только на plain-канале**): при срабатывании ответ **бракуется и регенерируется** тем же контуром, что клише (bounded ≤2 ретрая, fail-open). Regex-рез запрещён (инвариант №2).
- `enabled_rules` plain-каналов: `DEFAULT_ENABLED_RULES | {"bullet_list", "plain_no_tables"}`; на rich-канале `plain_no_tables` **не** включается (таблицы легальны).

#### 3.6.4. Доставка Сценария А (safe-HTML, переиспользуемый паттерн)

- Чтобы жирный реально отрендерился (не как literal `**`), под-путь `deep_research` прямого чата использует **уже существующий безопасный HTML-паттерн «Летописца»**: `escape_lore_html` (whitelist `<b>/<i>/<u>/<s>/<code>/<blockquote>/…`), `parse_mode="HTML"`, одиночное сообщение ≤4096, при `TelegramBadRequest` → plain-фолбэк (`services/direct_chat_service._send_direct_answer`, `services/smartmodule_utils.py`).
- Guard таблиц срабатывает **до** отправки; `<table>` в HTML-поток не просачивается.
- `casual`/`serious` доставляются **байт-в-байт** прежним путём (`parse_mode=None`).
- **Поправка к инварианту №7 сквозного слоя:** `parse_mode=None` сохраняется для plain-каналов; исключение — ограниченный под-путь `deep_research` прямого чата (safe-HTML), аналогично уже существующему исключению «Летописца».

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `services/system2_handoff.py` | enum + нормализатор + поле в 3 парсерах + `parse_summary_handoff` |
| `services/summary_prompts.py` | editor → JSON; narrator базы + режимы |
| `services/factcheck_prompts.py` | analyst → поле `response_mode`; verbalizer + режимы |
| `services/chat_prompts.py` | synthesizer → поле; verbalizer + режимы |
| `services/prompt_style_blocks.py` | `TYPOGRAPHY_BLOCK` + `MODE_*_BLOCK` + канальные `FORMAT_PLAIN_BLOCK`/`FORMAT_RICH_BLOCK` |
| `services/negative_constraints.py` | правило `plain_no_tables` (guard от таблиц на plain-канале) |
| `services/summary_generator.py`, `services/factcheck_service.py`, `services/direct_chat_service.py` | выбор режима Stage-2 |
| `services/prompt_migrations.py`, `plans/docs/canon/**` | канон-миграция + слепки |
| `config/settings.py` | `SMART_VERBALIZER_MODES_ENABLED` (env-only ClassVar, default ON) |

## 5. План тестирования (T-2123/T-2124)

1. Определение режима по сэмплам Stage-1; выбор `MODE_*_BLOCK`; fallback при отсутствии/невалидном режиме → `serious`.
2. Типографика: нет `—`/`«»`; запрет Markdown в casual; полный структурированный вывод в deep_research.
3. **Число LLM-вызовов:** существующие two-call-тесты подтверждают Stage-1+Stage-2 = 2 (роутер не добавляет вызов).
4. Backward-compat: `validate_summary_digest` (старый контракт) возвращает digest; `parse_*` без поля → `serious`.
5. Канон-миграция migrate/rollback.
6. Регресс: `test_summary_two_call_round1022.py`, `test_factcheck_two_call_round1022.py`, `test_direct_two_call_round1022.py`, `test_negative_constraints_round1022.py`, `test_prompt_migrations`. Полный pytest — 0 failed.
7. **Каналы, Сценарий А:** ответ direct/plain-саммари с табличной разметкой (`|…|`, `<table>`, ASCII-сетки) бракуется правилом `plain_no_tables` и регенерируется; в финале нет таблиц; жирный `<b>…</b>` и буллиты `- ` присутствуют; `casual`/`serious` остаются без Markdown.
8. **Каналы, Сценарий Б:** на rich-канале `plain_no_tables` не активен, подключён `FORMAT_RICH_BLOCK`; таблицы/сетки сохраняются в Article.

## 6. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Третий LLM-вызов ломает physical-two-call-pipeline | роутер только в Stage-1 + тест числа вызовов |
| R2 | High | `deep_research` ломает R11/plain | разделение контент/канал (ADR §Decision 5) + регресс |
| R3 | Medium | Невалидный/отсутствующий режим роняет ответ | fail-safe `serious` |
| R4 | Medium | Канон-атомарность | один коммит |
| R5 | R17/R18 | Секреты/сырьё в логах | только коды/числа |
| R6 | High | Таблицы/тяжёлая разметка в plain-канале → `BadRequest: can't parse entities` (ParseError), ответ не уходит | канальные блоки (T-2183) + guard `plain_no_tables` (T-2184) + тесты (T-2185/T-2186) |

## 7. Критерии приёмки

- `response_mode` в JSON Stage-1, валидируется; роутер только в Stage-1 (число вызовов не выросло).
- Три режима различимы; `deep_research` выводит переданный отчёт полностью.
- **Каналы:** в plain-канале таблиц нет (guard `plain_no_tables`), жирный + `- `-буллиты есть; в rich-канале полный Markdown/таблицы разрешены и не бракуются.
- Типографика: нет `—`/`«»`; канон-миграция атомарна; полный pytest — 0 failed.

## 8. Feature flag / раскатка / откат

- `SMART_VERBALIZER_MODES_ENABLED` — env-only `ClassVar` (**вне `param_catalog`, default ON, Δ каталога = 0**); OFF → единый прежний Вербализатор.
- Раскатка internal→10%→50%→100% не требуется; откат — kill-switch OFF / `git revert` + обратная канон-миграция.

## 9. Открытые вопросы (Human Gate)

- ~~`deep_research` в plain-саммари~~ — **РЕШЕНО владельцем (UPD 19.09.2026):** прямой чат (Сценарий А) — таблицы запрещены, обязательны жирный + `- `-буллиты; статья (Сценарий Б) — полный Markdown/HTML с таблицами. См. §3.6 и ADR-1023-3 §Decision 10.

## 10. Задачи

См. `tasks.md` (T-2116…T-2125, +T-2183…T-2186 — канальные правила). **T-2116** — этот spec + ADR-1023-3 (выполнен).

## 11. UPD review iter1 (@Builder, 19.09.2026) — уточнения приёмки

Ревью F3 (Step 5, `plans/reports/round1023_f3_reviewer.md`) зафиксировало противоречие и пробелы; ниже — уточнённая трактовка, синхронная коду.

1. **H1 — снятие конфликта буллитов в `deep_research`.** В общих блоках (`ANTI_BOT_BLOCK` п.4, R11-правило 2 Рассказчика) буллиты безусловно запрещены, а канальный plain-блок для `deep_research` их требует. При сборке промпта `deep_research` точечные запреты буллитов заменяются разрешающей формулировкой (`_DEEP_RESEARCH_OVERRIDES` в `services/prompt_style_blocks.py`); базовые каноны и их PREV-слепки не трогаются. Для `casual`/`serious` запрет сохраняется.
2. **H2 — доставка `<b>`.** «Жирный» рендерится только там, где есть safe-HTML-доставка (`parse_mode="HTML"` + `escape_lore_html`). Такая доставка есть у direct `deep_research` (§3.6.4). У саммари и фактчека её нет, поэтому они получают **text-only** канальный блок `FORMAT_PLAIN_TEXT_BLOCK` (без HTML-тегов вовсе); требование `<b>` там снимается до появления HTML-доставки (F6/F8), а финальный текст гарантированно очищается от whitelist-тегов (`strip_lore_html`). `FORMAT_PLAIN_BLOCK` (с `<b>`) применяется к direct `deep_research` (`html_safe=True`).
3. **M1 — область действия флага.** `SMART_VERBALIZER_MODES_ENABLED` гейтит **Stage-2** (выбор режимного/канального блока) и **маршрут доставки** (`deep_research` → safe-HTML). Stage-1-поле `response_mode` флагом не гейтится: оно остаётся в JSON, но при OFF игнорируется (fail-safe `serious`).
4. **M2/M5 — guard таблиц.** Прод-путь `plain_no_tables` идёт через публичный `detect_plain_tables` (единый источник). Детекция **контекстно-чувствительная**: одиночный `|` таблицей не считается. Таблица фиксируется по одному из признаков: HTML `<table`; ASCII-сетка `+---+`; separator-строка Markdown (`---|`, `|---|---|`, `|:--|:--|`); **две и более подряд** идущих pipe-строк (шапка + строки/разделитель). Тем самым легитимный шелл-пайп (`cat file | grep error`), `a|b`, `5|10`, `сигнал|шум` и одиночная `a | b` не бракуются, а реальная Markdown-таблица — бракуется (review iter2).
5. **M3 — rich-канал.** Интеграция `sendRichMessage`/`InputRichMessage` — зона **F6**; F3 поставляет только контракт-хелперы (`FORMAT_RICH_BLOCK`, `channel_enabled_rules("rich", …)`). T-2186 — **контрактный**, не сквозной.
6. **L4 — narrator-слепки.** `PREV_SUMMARY_NARRATOR_R1023`, `PREV_FACTCHECK_VERBALIZER_R1023`, `PREV_CHAT_VERBALIZER_R1023` — **code-snapshots** для отката/документации: у narrator-промптов нет PG-ключей, поэтому в `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` входят только Stage-1-ключи Редактора/Аналитика (ступень F3).

