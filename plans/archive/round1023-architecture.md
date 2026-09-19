# Round 10.23 — сквозной архитектурный слой (Step 2 @Architect, часть 1/3)

> **Эпик:** Adaptive System 2, Token Analytics, Dynamic Anti-Cliche Cache & Image Generation (9 фич F1–F9).
> **Источники:** `plans/current_task.md` (untracked, секреты не цитируем — R17/R18), `plans/backlog.md` §«Раунд 10.23», `tasks.md` F1–F3, Scanner-отчёты 10.22/10.21.
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION **2.57.0**; прод `a8a6437`.
> **Статус:** часть 1 из 3 — F1–F3 (ядро + канон). F4–F9 — части 2/3.
> **ADR этой части:** ADR-1023-1 (маркировка), ADR-1023-2 (двунаправленный фактчек), ADR-1023-3 (роутер режимов).
> **UPD владельца (19.09.2026):** `aiogram >= 3.31` — **обязательное** условие; жёсткие правила разметки по каналам — см. §3.6 (Сценарий А: plain, таблицы запрещены, жирный+буллиты; Сценарий Б: rich Article, полный Markdown/таблицы).

---

## 0. Что уже есть и что меняется (не переизобретаем)

System 2 в проекте — **физический двухвызовный конвейер** (10.22):

| Слой | Роль | Вход | Выход | Точка |
|---|---|---|---|---|
| Stage-1 | Аналитик / Синтезатор / Редактор | сырьё + тулы + БД | строгий JSON или чистая выжимка | `factcheck_service._check_claim_two_call`, `direct_chat_service._synthesize_direct_answer`, `summary_generator._generate_two_call` |
| Stage-2 | Вербализатор / Рассказчик | **только** валидированный объект Stage-1 | финальный текст | `verbalize_validated` (детектор клише, ≤2 ретрая) |

Общий контракт handoff: `services/system2_handoff.py` (строгая JSON-валидация, `contains_system_ids`, `redact_secrets`). Egress: `services/outgoing_guard.py::sanitize_outgoing` + реестры `SEND_POINTS`/`SEND_ALLOWLIST` в `services/telegram_send.py`.

Round 10.23 **не переписывает** этот каркас — он его расширяет тремя ядровыми фичами (F1–F3) и шестью надстроечными (F4–F9).

---

## 1. Обзор эпика: 9 фич и их место

| # | Фича | Ядро / слой | Δ каталога | DDL | Канон | Флаг |
|---|---|---|---|---|---|---|
| **F1** | `target-message-marking` | контекст: маркировка триггера в 2 рендерерах + правило в 3 Синтезатора | 0 | 0 | да (3 промпта) | нет |
| **F2** | `factcheck-deep-context` | фактчек: двунаправленное окно + граф реплаев + правило веб-поиска | **+2** (`factcheck_context_before/after`) | 0 | да (1 промпт) | нет |
| **F3** | `verbalizer-response-modes` | System 2: `response_mode` в Stage-1 + 3 промпта Вербализатора + типографика | 0 | 0 | да (narrator ×3 модуля) | `SMART_VERBALIZER_MODES_ENABLED` |
| **F4** | `dynamic-anticliche-cache` | анти-клише: недельный воркер → динамический список → детектор (не scrubber/промпт) + фикс S10.22-4b | 0 (env-only флаг) | 0 (PG-таблица `anticliche_cache`) | нет (канон no-op, ADR-1023-4 D4) | `DYNAMIC_ANTICLICHE_ENABLED` |
| **F5** | `image-generation-tool` | изображения: `generate_image` + провайдер Pollinations (GET-режим) + UI | **+группа/ключи image** | 0 (PG-сид) | да | `IMAGE_GENERATION_ENABLED` + тумблер |
| **F6** | `summary-cover-rich-article` | изображения: visual prompt + «Стиль обложки» + `sendRichMessage` + тихий фолбэк | +1 (стиль) | 0 | да | `SUMMARY_COVER_ARTICLE_ENABLED` |
| **F7** | `token-analytics-dashboard` | аналитика: DDL `llm_usage_events` + correlation-id + Flow-node/графики | +0 | **PG (+2 табл.; SQLite v12 — AMEND ADR-1023-7)** | нет | `TOKEN_ANALYTICS_ENABLED` |
| **F8** | `ui-verbilizer-tabs` | UI: разделение Синтезатор/Вербализатор + Tabs режимов + мониторинг клише | **+ключи stage-1/2/режимы** | 0 | нет | нет |
| **F9** | `help-ui-v5` | Справка v4→v5 | 0 | 0 (PG-миграция v4→v5) | код-канон | нет |

> Точные Δ/DDL F4–F9 фиксируются в Part 2/3. Здесь — стратегия и границы.

**Порядок исполнения (из backlog):** `F1 → F2 → [F3 ∥ F5] → F4 → F6 → F7 → F8 → F9`, при этом общий канон-контур строго `F1 → F2 → F3 → F4 → F6`.

---

## 2. Схема потока System 2 с новыми элементами

```
пользовательское сообщение (trigger_message_id)
        │
        │  F1: маркировка «[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]» в истории
        ▼
┌─────────────────────── CONTEXT BUILD ───────────────────────┐
│  summary_xml.XmlGroundingBuilder   (XML, <message …>)        │  F1
│  canonical_context.format_context_item (plain, [..]: …)      │  F1
│  chat_context.format_chat_context  (фактчек)                 │  F1/F2
│  thread_chain (граф реплаев, общий util)                     │  F2
└──────────────────────────────────────────────────────────────┘
        │
        ▼  [Stage-1 — СИНТЕЗАТОР/АНАЛИТИК/РЕДАКТОР]   (LLM-вызов №1; tool-loop внутри)
   system: <модульный Stage-1 промпт> (+ правило маркировки F1)
   user  : контекст + RAG/тулы
   → СТРОГИЙ JSON: {…, "response_mode": "casual|serious|deep_research"}   F3
        │
   system2_handoff: parse + validate + normalize_response_mode (fail-safe serious)
        │
        ▼  [Stage-2 — ВЕРБАЛИЗАТОР/РАССКАЗЧИК]        (LLM-вызов №2; БД/тулы НЕ видит)
   system: <модульный базовый narrator> + TYPOGRAPHY_BLOCK + MODE_*_BLOCK(response_mode) + FORMAT_*_BLOCK(канал)   F3
   user  : только валидированный объект Stage-1
   → текст
        │
   validator-loop (клише: брак + ≤2 ретрая; динамический список F4)
        │
        ▼
┌─────────────────────── EGRESS ───────────────────────────────┐
│  sanitize_outgoing → telegram_send.send_text / send_rich_message (F6) │
│  sanitize_outgoing реализуется через реестры SEND_POINTS/SEND_ALLOWLIST │
└──────────────────────────────────────────────────────────────┘
```

Новые элементы раунда помечены F1/F2/F3 (эта часть) и F4/F6 (надстройки). **Число физических LLM-вызовов не растёт: ровно 2** (+ tool-loop внутри Stage-1 + bounded validator-ретраи Stage-2).

---

## 3. Общие контракты

### 3.1. Расширение `system2_handoff.py` под `response_mode`

- **Enum:** `RESPONSE_MODES = ("casual", "serious", "deep_research")`.
- **Нормализатор:** `normalize_response_mode(value) -> str` — неизвестное/пустое/`None` → `"serious"` (fail-safe default). Никогда не бросает.
- **Поля Stage-1 JSON:** ко всем трём контрактам добавляется `"response_mode"` (строка).
  - `parse_factcheck_analysis` — читает `data["response_mode"]`, нормализует, кладёт в результат.
  - `parse_direct_synthesis` — аналогично.
  - `parse_summary_handoff(raw)` — **новый**: строгий JSON `{"response_mode": ..., "digest": "..."}`.
- **Обратная совместимость:** `validate_summary_digest(raw) -> str | None` остаётся (обёртка над `parse_summary_handoff`, возвращает только `digest`) для существующих тестов/вызовов; при raw-не-JSON, но валидной Markdown-выжимке — `digest = raw`, `response_mode = "serious"`. Так же `parse_factcheck_analysis`/`parse_direct_synthesis` при отсутствии поля возвращают `response_mode="serious"` — старые Stage-1 промпты продолжают работать (graceful).
- **Изоляция:** `response_mode` — служебное поле, НЕ попадает в user-content Stage-2 и НЕ логируется как содержимое (R17).
- **Порядок полей:** `response_mode` добавляется последним; F7 (correlation-id) добавляется ПОСЛЕ F3 и только аддитивно (см. §3.4).

### 3.2. Маркировка целевого сообщения в обоих рендерерах (F1)

- **Единый токен:** константа `TARGET_MARKER = "<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]"` и escape-стабильное ядро `TARGET_MARKER_CORE = "[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]"` в новом модуле `services/target_marking.py`.
- **Правило встраивания:**
  - `XmlGroundingBuilder.build(messages, aliases=None, trigger_message_id=None)`: маркер добавляется к body сообщения с совпавшим `tg_message_id` ДО `_escape` → в XML он выглядит как `&lt;&lt;&lt; [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` (well-formed XML сохраняется). `trigger_message_id=None` или нет совпадения → рендер **байт-в-байт** прежний.
  - `format_context_item(..., is_target: bool = False)`: при `True` маркер приписывается после текста. Дефолт `False` → все прочие вызывающие (RAG, lore, tool_router, search) не затронуты.
- **Ключ сопоставления:** Telegram `message_id` (`smart_messages.tg_message_id`); при отсутствии совпадения маркер не ставится (никаких догадок).
- **Промпт-правило** (единый блок) в трёх Stage-1 Синтезаторах: помеченное сообщение — инструкция пользователя, а не событие чата; запрещено пересказывать/анализировать его как диалог.
- **Байт-эталоны:** `tests/test_summary_xml.py`, инвентарные сэмплы `tests/test_memory_core_round1020.py` обновляются в T-2103; отдельный тест антиэхо — маркер не протекает в финальный текст.
- Детали → **ADR-1023-1**.

### 3.3. Двунаправленное окно фактчека + граф реплаев (F2)

- **Ключи:** `limits.factcheck_context_before` и `limits.factcheck_context_after` (group `limits_factcheck`). Дефолты: **6/6** (суммарный потолок `FACTCHECK_CONTEXT_TOTAL_CAP = 40`, жёсткий код-кап). Δ каталога F2 = **+2**.
- **Судьба legacy `FACTCHECK_CONTEXT_MESSAGES`:** **депрекейт** — используется только как источник для одноразовой миграции значения в `before`; активный код-путь читает только `before`/`after`. Ключ остаётся в реестре (не ломаем пин-тесты), но уходит из UI-раздела фактчека (внутренний/скрытый). Итоговое число Settings-полей = +2 (не +3).
- **Запрос:** новый `DatabaseService.get_messages_around(chat_id, target_tg_message_id, before, after)` — anchor = целевое (обсуждаемое) сообщение; возвращает `before` старше + сам anchor + `after` новее, хронологически ASC. Fail-open → legacy `get_recent_messages(before+after)`.
- **Граф реплаев:** `_collect_thread_chain` выносится из `DirectChatService` в общий util (напр. `services/thread_chain.py`), инжектируется в контекст фактчека для **anchor-сообщения**; глубина = существующий `limits.chat_thread_max_depth` (паритет с direct, новый ключ НЕ вводим). Fail-open: нет цепочки → блок опускается.
- **Порядок:** <chat_context> идёт рядом с `<claim>`; цепочки — отдельный под-блок, помеченный как НЕ-доказательства.
- **Промпт-правило:** обязательный веб-поиск для тейков о реальном мире/новостях/датах/политике.
- Детали → **ADR-1023-2**.

### 3.4. Стратегия Δ каталога (F2 → F5 → F8) и DDL/миграций

**Каталог (`services/param_catalog.py`) — ступени: F2 → F5 → F8.**

| Ступень | Что добавляется | Категория | Итог регистра (от базы 439) |
|---|---|---|---|
| F2 | `FACTCHECK_CONTEXT_BEFORE`, `FACTCHECK_CONTEXT_AFTER` | limits/`limits_factcheck` | +2 |
| F5 | группа «Генерация изображений» (URL/модель/key/GET-режим) + тумблер модуля | models/flags | +N (Part 2) |
| F8 | ключи Stage-1/Stage-2 редакторов + режимы + блок `dynamic_cliche_list` (hidden) | content/flags | +N (Part 3) |

Правила: один ключ — один владелец-группа; осиротевших ключей нет; пин-тесты `test_param_catalog`/`test_frontend_tab_mapping` обновляются **в том же коммите**, что и ступень; `tma-menu-freeze` (структура меню) не меняется.

**DDL/SQLite (AMEND ADR-1023-7 §Amend):** ~~F7 `v12 → v13`~~ — **F7 DDL идёт в PostgreSQL** (`services/pg_db.py`: `llm_usage_events` + `llm_model_prices` + индексы/correlation + идемпотентный сид цен), **SQLite остаётся v12, Δ SQLite = 0**. Причина: web-API читает только PG (`cache.pg`), а запись usage идёт через `chat_usage`/`worker_budget` (PG) — телеметрия должна лежать рядом. F4 (кэш клише) и F5 (провайдер изображений) — **PG-ключи** (`bot_settings`/`prompts.*`). F6/F9 — без SQLite DDL. Part 1 сам оговаривал «точные Δ/DDL F4–F9 фиксируются в Part 2/3».

**PG-миграции:** значение `before` из legacy-ключа — идемпотентная миграция в стиле `config_migrations.migrate_*`; сид провайдера изображений (F5) — seed-миграция; Справка v4→v5 (F9) — идемпотентная `config_cache`-миграция с `KNOWN_INFO_SNAPSHOTS` (v4 → снимок).

**Канон-миграции промптов (ADR-1013-3):** атомарно на фичу, ступень `F1 → F2 → F3 → F4 → F6`. Каждая ступень = правка константы + `PREV_*_R1023`-слепки + `PROMPT_MIGRATIONS` (migrate) + `ROLLBACK_MIGRATIONS` (`rollback_prompt_canons`) + `plans/docs/canon/**` + тесты — **одним коммитом**. `bot.py` вызывает `migrate_prompt_canons` (порядок существующих миграций не сдвигается).

### 3.5. Egress и `sendRichMessage` (общие требования; детали F6)

- **Любая новая точка отправки** обязана попасть в `SEND_POINTS` (если идёт через обёртку) **или** в `SEND_ALLOWLIST` (если осознанно минует guard, с обоснованием). Тест покрытия (`test_outgoing_guard_round1022.py`) сверяет реестр со сканом кода.
- **F6** добавляет точку `send_rich_message` в `telegram_send.py`; текст rich-сообщения (markdown/HTML) — модель-сгенерированный → обязан проходить `sanitize_outgoing` (либо осознанный allowlist с обоснованием). Rich-канал **не отменяет** `parse_mode=None`-инвариант plain-каналов; `sendRichMessage` — отдельный метод без `parse_mode`.
- **Тихий фолбэк F6:** сбой генерации обложки/`sendRichMessage` → обычное текстовое саммари без сообщений об ошибке (fail-silent), но с R17-safe логом (только класс/код).
- **Веб-ресёрч (факты):** см. §6.

### 3.6. Правила разметки по каналам (UPD владельца 19.09.2026; синхрон ADR-1023-3 §Decision 10 / ADR-1023-6 п.11–12)

Разметка привязана к **каналу доставки**, а не только к режиму. Причина — защита от `ParseError`: Telegram Bot API не поддерживает таблицы ни в одном text-`parse_mode`; сырая табличная разметка → `BadRequest: can't parse entities`, и ответ не уходит.

| `response_mode` | Сценарий А — plain (обычное сообщение) | Сценарий Б — rich Article (`sendRichMessage`) |
|---|---|---|
| `casual` | без Markdown | не применяется |
| `serious` | без Markdown | не применяется |
| `deep_research` | жирный (`<b>`) + буллиты `- `; таблицы **ЗАПРЕЩЕНЫ** | **РАЗРЕШЕНО ВСЁ:** полный Markdown/HTML, таблицы, сетки |

- Промпт-блоки: `FORMAT_PLAIN_BLOCK` / `FORMAT_RICH_BLOCK` в `services/prompt_style_blocks.py`; `MODE_DEEP_RESEARCH_BLOCK` дополняется **ровно одним** канальным блоком (выбор детерминирован каналом).
- Guard: `detect_plain_tables` + правило `plain_no_tables` (bounded-регенерация, fail-open) — **только на plain-канале**; на rich не активно.
- Сценарий А `deep_research` прямого чата доставляется safe-HTML-паттерном «Летописца» (`escape_lore_html` whitelist + `parse_mode="HTML"` + `TelegramBadRequest`→plain).
- **aiogram `>= 3.31.0` обязателен** для rich-канала/обложек (`requirements.txt` уже пинит); версия ниже на деплое — блокер, а не «допустимый режим» (guard — только defense-in-depth).
- Детали: ADR-1023-3 §Decision 10, ADR-1023-6 п.11–12; задачи F3 T-2183…T-2186.

---

## 4. Инварианты раунда (нарушать нельзя)

1. **physical-two-call-pipeline** — ровно 2 физических LLM-вызова (Stage-1 + Stage-2); tool-loop внутри Stage-1; роутер `response_mode` — только в Stage-1. Три-вызовные схемы запрещены.
2. **validator-loop без regex-реза клише** — клише только бракуются и регенерируются (≤2 ретрая, fail-open). Regex режет исключительно технические теги (`<thought>`, `fact:\d+`, `msg:\d+`).
3. **egress-реестр** — новые send-точки регистрируются; нет «серых» отправок модель-текста.
4. **imported-history-immutable** — сырая история `smart_messages` не удаляется (только READ для новых фич).
5. **manual-overrides-immutable** — `persona_dossier_overrides` не перезаписываются.
6. **R16** — API расширяется аддитивно; **R17** — логи/отчёты только коды/числа, секретов нет; **R18** — секреты из `current_task.md` не коммитить/не цитировать (ключ изображений — «ключ из ТЗ»).
7. **`parse_mode=None`** — plain-каналы сохраняют его; rich-доставка — только через новый явный `sendRichMessage`-путь (F6). Исключение — ограниченный под-путь `deep_research` прямого чата: safe-HTML-паттерн «Летописца» (`escape_lore_html` whitelist), как уже существует для историй. Таблицы на plain-каналах запрещены (guard `plain_no_tables`, §3.6).
8. **Байт-эталоны** — оба рендерера истории (F1) и `info_text.md` (F9) обновляются осознанно, с фиксацией нового эталона.
9. **Δ каталога фиксирована** — любое отклонение фиксируется в spec соответствующей фичи; произвольный рост запрещён.
10. **Порядок роутеров `bot.py`** не сдвигается (только DI-kwargs/вызовы миграций).
11. **Канальные правила разметки (UPD владельца)** — таблицы только в rich-канале; plain — жирный+буллиты, без таблиц (§3.6).
12. **aiogram `>= 3.31.0`** — жёсткое условие rich-канала F6/деплоя (не опция).

---

## 5. Разграничение ответственности фич и ступени общих файлов

**Эксклюзивы (один владелец):**

| Файл | Владелец |
|---|---|
| `services/summary_xml.py`, `services/canonical_context.py`, новый `services/target_marking.py` | **F1** |
| `handlers/factcheck.py`, `services/factcheck_prompts.py`, новый общий `services/thread_chain.py` | **F2** |
| `services/negative_constraints.py`, новый `services/anticliche_worker.py` | **F4** |
| `services/tool_schemas.py`, новый `services/image_generation.py` | **F5** |
| `services/summary_generator.py`, `services/summary_prompts.py`, `services/telegram_send.py` | **F6** |
| `services/info_service.py`, `info_text.md` | **F9** |

**Общие файлы — ступени вливания:**

| Файл | Ступень |
|---|---|
| `services/prompt_migrations.py` + `plans/docs/canon/**` | **F1 → F2 → F3 → F4 → F6** (атомарно на фичу; F4 — **no-op**, ADR-1023-4 D4) |
| `services/param_catalog.py` | **F2 → F5 → F8** |
| `services/system2_handoff.py` | **F3 → F6 → F7** (F3 добавляет `response_mode`; F6 — `cover_prompt`/`normalize_cover_prompt`; F7 — correlation-id аддитивно) |
| `web/index.html` / `web/app.js` | **F5 → F7 → F8 → F9** |
| `services/prompt_style_blocks.py` | **F3** (F3 добавляет `TYPOGRAPHY_BLOCK` + `MODE_*_BLOCK`; F4 канон **не трогает** — ADR-1023-4 D1/D4) |

Правило: **общие файлы вливаются строго по ступеням**; фича из более поздней ступени читает результат предыдущей, но не переписывает её блоки.

---

## 6. Веб-ресёрч: `sendRichMessage` / aiogram (факты для F6/F9)

Собрано по официальным источникам (правило владельца «не гадай — гугли»):

| Факт | Источник |
|---|---|
| `sendRichMessage` появился в **Bot API 10.1** (11.06.2026); сигнатура: `chat_id` (required), `rich_message: InputRichMessage` (required) + опциональные `reply_parameters`, `reply_markup`, `message_thread_id`, `disable_notification`, `protect_content`, `allow_paid_broadcast`, `message_effect_id`, `business_connection_id` и др. | https://core.telegram.org/bots/api/ · https://tg-bot-sdk.website/api/methods/send-rich-message/ |
| `InputRichMessage`: ровно одно из `html` / `markdown` / `blocks`; `media: list[InputRichMessageMedia]` — вложения, на которые ссылаются `tg://photo?id=`, `tg://video?id=`, `tg://document?id=`, `tg://audio?id=`; `is_rtl`, `skip_entity_detection`. | https://docs.aiogram.dev/en/v3.31.0/api/types/input_rich_message.html · https://raw.githubusercontent.com/aiogram/aiogram/v3.31.0/aiogram/types/input_rich_message.py |
| Поля `blocks` и `media` добавлены в **Bot API 10.2**; `sendRichMessageDraft` — стриминг частичного rich-сообщения (ephemeral 30 c, только private-чаты, требует финальный `sendRichMessage`). | https://github.com/aiogram/aiogram/releases/tag/v3.30.0 |
| Лимиты rich-сообщения (серверные, читать из `help.getAppConfig`): `rich_message_length_limit` 32768, `max_blocks` 500, `max_media` 50, `max_depth` 16, `max_table_cols` 20. | https://trip2g.com/dev/telegram_rich |
| `Message.text` у rich-сообщения пуст; rich-контент — в `Message.rich_message` (`Message` получил поле `rich_message`). | https://core.telegram.org/bots/api/ |
| **aiogram:** поддержка Bot API 10.1 добавлена в **3.29.0** (14.06.2026) — `SendRichMessage`, `SendRichMessageDraft`, `InputRichMessage`; Bot API 10.2 — в **3.30.0** (17.07.2026, `InputRichMessageMedia`/`media`); Bot API 10.3 — в **3.31.0** (26.08.2026). | https://docs.aiogram.dev/en/v3.31.0/changelog.html · https://github.com/aiogram/aiogram/releases/tag/v3.29.0 · https://github.com/aiogram/aiogram/releases/tag/v3.30.0 |
| **Проект:** `requirements.txt` → `aiogram>=3.31.0,<4.0.0` (media/blocks доступны). **Но установленный локально в dev-окружении — 3.29.1** (без `media`) → для F6 требуется `pip install -r requirements.txt` до ≥3.31.0. | `requirements.txt:1`, `pip show aiogram` |

**Вывод для F6:** обложка-медиа возможна только через `InputRichMessage.media` (`tg://photo?id=…`) или `blocks` с медиа-блоком → минимальная версия aiogram **3.31.0** (по `requirements.txt`). На 3.29.1 доступен только markdown/html без media.
**UPD владельца (19.09.2026):** апгрейд aiogram до `>=3.31.0` — **ОБЯЗАТЕЛЬНОЕ условие F6/деплоя** (без него лонгриды с обложками не работают), а не «желательный апгрейд». Guard `_rich_media_supported` — только защитный фолбэк. План F6 обязан: (1) обеспечить aiogram `>=3.31.0` на деплое (блокер при меньшей версии); (2) регистрировать egress-точку; (3) иметь тихий фолбэк → plain.

---

## 7. Открытые вопросы → Human Gate

1. **F2, дефолты окна:** `before=6`/`after=6`, суммарный кап 40 — подтвердить (влияет на стоимость). См. ADR-1023-2 §Human Gate.
2. ~~**F3, `deep_research` в plain-саммари:**~~ — **ЗАКРЫТО владельцем (UPD 19.09.2026):** Сценарий А (прямой чат) — таблицы запрещены, обязательны жирный + `- `-буллиты; Сценарий Б (статья) — полный Markdown/HTML с таблицами (§3.6).
3. ~~**F6, богатый API-флаг:**~~ — **ЗАКРЫТО:** апгрейд aiogram до `>=3.31.0` **ОБЯЗАТЕЛЕН** (без него лонгриды с обложками не работают). Жёсткое условие деплоя.
4. **F1, носитель триггера:** для `/summary` сообщение-команда может отсутствовать в окне `smart_messages` — предложено «нет в окне → без маркера (legacy байт-путь)». Подтвердить.

---

## 8. Что передаётся частям 2/3

- **Part 2 (F4–F6):** детальный дизайн Dynamic Anti-Cliche Cache (кэш PG vs DDL, фикс S10.22-4b без regex-реза), image-generation tool (Pollinations, GET-режим, `response_format=url`, секрет только env/PG + тест «нет plaintext»), `sendRichMessage`-доставка + визуальный промпт (EN ≤300) + «Стиль обложки» + тихий фолбэк.
- **Part 3 (F7–F9):** DDL `llm_usage_events` + сквозной correlation-id (Stage-1/2/tool-loop), Flow-node/графики, UI-табы Синтезатор/Вербализатор + мониторинг `dynamic_cliche_list`, Справка v4→v5 (blockquote/h1/h2, команды изображений).
- **Ступени, которые обязаны соблюсти Part 2/3:** каталог F5→F8; web F5→F7→F8→F9; `system2_handoff` F3→F6→F7; канон F4→F6.

---

## 9. Ссылки

- ADR-1023-1 `plans/features/target-message-marking-round1023/ADR-1023-1.md`
- ADR-1023-2 `plans/features/factcheck-deep-context-round1023/ADR-1023-2.md`
- ADR-1023-3 `plans/features/verbalizer-response-modes-round1023/ADR-1023-3.md`
- Спеки: `target-message-marking-round1023/spec.md`, `factcheck-deep-context-round1023/spec.md`, `verbalizer-response-modes-round1023/spec.md`
- Архив-образцы: `plans/archive/system2-factcheck-two-call-round1022/spec.md`, `plans/archive/system2-summary-two-call-round1022/{spec.md,ADR-1022-4.md}`
- Scanner: `plans/reports/round1022_scanner_audit.md` (S10.22-4b — ложный `as_ai` при запятой), `plans/reports/round1021_scanner_audit.md`, `plans/reports/global_map.md`, `plans/reports/audit_backlog.md`
