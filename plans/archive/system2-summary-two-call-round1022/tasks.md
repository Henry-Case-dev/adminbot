# Задачи: system2-summary-two-call-round1022

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 1 @PM (+ Шаг 2b @Architect: T-2095) · Тип: backend/LLM + канон промптов
> **ТЗ:** `plans/current_task.md`, «ЧАСТЬ 1 → 2. Саммари (2 шага)» (строки 205–208); negative constraints — п.4 (строки 215–218). Файл untracked, SSH-креды — не цитировать, не коммитить (R17/R18).
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a923310`.

## Цель
Разделить генерацию саммари на два независимых вызова:
**Слой 1 — Редактор** (сырая история + RAG-факты → чистая Markdown-выжимка; фильтр мусора; **уничтожение исторических фактов, не относящихся к сегодняшней теме**; без системных тегов) → **Слой 2 — Рассказчик** (только выжимка → связный текст; никакого «пришивания» фактов сбоку).

## ТЗ (кратко)
«Архивная справка» больше не должна приклеиваться нерелевантно; историческая справка отсеивается Редактором. Рассказчик физически не видит сырую историю/RAG.

## Решение (Шаг 0)
**Что уже есть:**
- Один вызов: `services/summary_generator.py:204-241` (system + user → `llm.generate`), RAG-инжект `services/summary_generator.py:164`, сборка user-контента `:342-378`.
- Канон «Архивная справка» (архив ≠ свежее): `services/summary_prompts.py:39`; слепки `PREV_R1021_SUMMARY_SYSTEM_PROMPT`.
- Пост-обработка: `services/summary_cleanup.py:20-30` (`cleanup_llm_text` → `strip_reasoning_tags`).
- Доставка: стриминг `services/summary_generator.py:380-401`, чанки `:443-473`.

**Что новое:**
- Два промпта: `SUMMARY_EDITOR_*` (Markdown-выжимка, отсев нерелевантного) и `SUMMARY_NARRATOR_*` (только выжимка).
- Оркестрация двух `llm.generate`; `rag_context` подаётся **только Редактору**.
- Fallback на одиночный путь 10.21; env-only kill-switch.

**Конфликт / инварианты:**
- Сохранить разделение «архив/свежее» (`services/summary_prompts.py:39`) и не сломать стриминг/HTML-доставку саммари.
- Канон-атомарность (ADR-1013-3): код + `plans/docs/canon/**` + `services/prompt_migrations.py` + тесты одним коммитом; `PREV_*` слепки сохраняются.

## Задачи
- [x] **T-2044** [@Architect] ADR: 2-вызовное саммари, Markdown-контракт Редактора, fallback/kill-switch, совместимость со стримингом, откат.
- [x] **T-2045** [@Builder] Промпт Редактора (`services/summary_prompts.py`): сырая история + RAG → чистая Markdown-выжимка; отсев нерелевантных исторических фактов; без системных тегов.
- [x] **T-2046** [@Builder] Промпт Рассказчика: вход только выжимка → связный текст; без «пришивания» фактов сбоку.
- [x] **T-2047** [@Builder] Оркестрация `services/summary_generator.py:204-241`; `rag_context` — только в слой Редактора (`:164`).
- [x] **T-2048** [@Builder] Совместимость со стримингом/чанками (`:380-473`), `services/summary_cleanup.py` и `_compose_user_content` (`:342-378`).
- [x] **T-2049** [@Builder] Канон-миграция (`services/summary_prompts.py` + `PREV_*` + `services/prompt_migrations.py` + `plans/docs/canon/**`).
- [x] **T-2050** [@Builder] Fallback на одиночный путь + env-only kill-switch.
- [x] **T-2051** [@Builder] Тесты: 2 вызова, чистая выжимка без тегов, отсев нерелевантного исторического факта, стриминг не сломан.
- [x] **T-2052** [@Builder] Регресс + байт-тесты канона.
- [x] **T-2095** [@Builder] **UPD3:** интеграция `services/negative_constraints.verbalize_validated` в Рассказчик (≤2 ретрая → перегенерация; при исчерпании — лучший вариант/fail-open, пусто → 10.21); `SYSTEM2_VALIDATOR_LOOP_ENABLED` (env-only, default ON); клише кодом не вырезать; stats — коды/числа (R17).

## Риски
- **R1 (High):** стриминг/HTML-доставка ломается при 2 вызовах → регресс `_send_streaming`/`_send_chunked` (`services/summary_generator.py:380-473`) (T-2048).
- **R2 (High):** Редактор вырежет полезные свежие факты → тест «отсекается только нерелевантная история, свежее сохраняется» (T-2051).
- **R3 (Medium):** историческая справка снова «приклеивается сбоку» → контракт Рассказчика «только выжимка» (T-2046).
- **R4 (Medium):** канон-атомарность (ADR-1013-3) → слепки `PREV_*` + один коммит (T-2049).
- **R5 (Medium):** двойная стоимость/латентность LLM → лимиты/таймауты/fallback (T-2050).
- **R6 (R17/R18):** сырые фрагменты истории не должны утечь в отчёт/логи.

## Зависимости / ступени вливания
- Зависит от **F6** (`telegram-send-regex-guard-round1022`): negative constraints + chokepoint.
- Общий канон-контур — **сериализовать: F6 → F3 → F4 → F5** (атомарно на фичу).
- Эксклюзив: `services/summary_generator.py`, `services/summary_prompts.py`.
- Read/переиспользование: `services/summary_cleanup.py`, `services/reply_postprocess.py`.
- **Feature flag:** `SYSTEM2_SUMMARY_ENABLED` (env-only `ClassVar`, **Δ каталога = 0**), **default ON**; раскатка internal→10%→50%→100% не требуется; откат — kill-switch OFF / `git revert`.
