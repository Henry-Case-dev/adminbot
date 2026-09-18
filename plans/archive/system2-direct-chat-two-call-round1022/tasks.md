# Задачи: system2-direct-chat-two-call-round1022

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 1 @PM (+ Шаг 2b @Architect: T-2096) · Тип: backend/LLM (tool-loop) + канон промптов
> **ТЗ:** `plans/current_task.md`, «ЧАСТЬ 1 → 3. Direct Chat (Прямые ответы) (2 шага)» (строки 210–213); negative constraints — п.4 (строки 215–218). Файл untracked, SSH-креды — не цитировать, не коммитить (R17/R18).
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a923310`.

## Цель
Разделить прямой ответ на два независимых вызова:
**Слой 1 — Синтезатор тулов** (сообщение юзера + «каша» из логов сработавших инструментов: Exa-поиск, RAG, API → чистая информационная справка в JSON) → **Слой 2 — Вербализатор** (пишет финальный ответ, опираясь только на чистую справку).

## ТЗ (кратко)
Прямой чат перегружен логами инструментов; нужен синтез «каши логов» в чистую справку и отдельная вербализация.

## Решение (Шаг 0)
**Что уже есть:**
- Вызов tool-цикла: `services/direct_chat_service.py:714-764` (`chat_with_tools`, `ToolLoopResult`).
- Движок: `services/tool_loop.py` — `TOOL_MAX_ROUNDS=4`, `tool_trace` (`{"round","tool","ok","out_chars"}`), degraded-путь `services/tool_loop.py:76-86`.
- Сырые логи тулов: `services/tool_loop.py:104/129/169` (final round / truncation / exec failed).
- Канон direct-чата: `services/chat_prompts.py` (`CHAT_SYSTEM_PROMPT` + `PREV_*`/`LEGACY_*`), `plans/docs/canon/**`.
- Пост-обработка: `services/reply_postprocess.py:39-74`; HTML-доставка истории (`tool_ctx.lore_compiled`) — `services/direct_chat_service.py:757-762`.

**Что новое:**
- Два промпта: `DIRECT_SYNTHESIZER_*` (сообщение + `tool_trace`/логи → JSON-справка) и `DIRECT_VERBALIZER_*` (только справка → ответ).
- Оркестрация синтез→вербализация вокруг существующего tool-цикла.
- Fallback: нет тулов → одиночный путь; degraded → существующая логика.

**Конфликт / инварианты:**
- Не сломать degraded-путь (`services/tool_loop.py:76-86`, `services/direct_chat_service.py:751-762`) и `lore_compiled` HTML-доставку.
- Порядок роутеров `bot.py` не менять (инвариант).
- Канон-атомарность (ADR-1013-3).

## Задачи
- [x] **T-2053** [@Architect] ADR: Синтезатор→Вербализатор вокруг tool-цикла, JSON-справка, место в `handle`, fallback/degraded-совместимость, откат.
- [x] **T-2054** [@Builder] Промпт Синтезатора тулов (сообщение + `tool_trace`/логи → чистая JSON-справка).
- [x] **T-2055** [@Builder] Промпт Вербализатора (только справка → финальный ответ; стиль из `services/prompt_style_blocks.py`).
- [x] **T-2056** [@Builder] Оркестрация `services/direct_chat_service.py:714-764` (после tool-цикла: синтез → вербализация).
- [x] **T-2057** [@Builder] Сбор «каши логов» из `services/tool_loop.py` (`tool_trace`, rounds) без утечки секретов/токенов (R17).
- [x] **T-2058** [@Builder] Канон-миграция (`services/chat_prompts.py` + `PREV_*` + `services/prompt_migrations.py` + `plans/docs/canon/**`).
- [x] **T-2059** [@Builder] Fallback: нет тулов → одиночный путь; degraded/`round_limit` → существующая логика.
- [x] **T-2060** [@Builder] Тесты: 2 вызова, чистая справка без сырых логов, degraded/`lore_compiled` не сломаны.
- [x] **T-2061** [@Builder] Регресс + байт-тесты канона; порядок роутеров `bot.py` не изменён.
- [x] **T-2096** [@Builder] **UPD3:** интеграция `services/negative_constraints.verbalize_validated` в Вербализатор direct (≤2 ретрая → перегенерация; при исчерпании — лучший вариант/fail-open, пусто/ошибка → финал tool-loop); `SYSTEM2_VALIDATOR_LOOP_ENABLED` (env-only, default ON); клише кодом не вырезать; stats — коды/числа (R17).

## Риски
- **R1 (High):** сломать degraded/`lore_compiled` доставку → регресс-тесты (T-2060).
- **R2 (High):** утечка токенов/секретов из логов тулов в промпт → санитизация входа синтезатора (T-2057, R17).
- **R3 (Medium):** невалидная JSON-справка → строгий парсер + fallback (T-2059).
- **R4 (Medium):** двойная стоимость/латентность (tool-цикл + 2 вызова) → лимиты/таймауты.
- **R5 (Medium):** канон-атомарность (ADR-1013-3); риск сдвига порядка роутеров `bot.py` — только DI-kwargs.
- **R6 (R17/R18):** логи инструментов могут содержать чувствительные значения → маскировать.

## Зависимости / ступени вливания
- Зависит от **F6** (`telegram-send-regex-guard-round1022`): negative constraints + chokepoint.
- Общий канон-контур — **сериализовать: F6 → F3 → F4 → F5** (атомарно на фичу).
- Эксклюзив: `services/direct_chat_service.py`, `services/chat_prompts.py`.
- Read/переиспользование: `services/tool_loop.py` (структура `ToolLoopResult`/`tool_trace`).
- **Feature flag:** `SYSTEM2_DIRECT_ENABLED` (env-only `ClassVar`, **Δ каталога = 0**), **default ON**; раскатка internal→10%→50%→100% не требуется; откат — kill-switch OFF / `git revert`.
