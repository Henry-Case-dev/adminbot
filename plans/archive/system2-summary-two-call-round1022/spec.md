# spec.md — F4 `system2-summary-two-call-round1022`

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 2b @Architect · Тип: backend/LLM + канон промптов
> **ADR:** `ADR-1022-4.md` (**Accepted — UPD3: validator-loop**). **Задачи:** `tasks.md` (T-2044…T-2052 + T-2095).
> **ТЗ:** `plans/current_task.md`, «ЧАСТЬ 1 → 2. Саммари (2 шага)» (205–208); UPD3 §3 (259–262).
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Один вызов генерации саммари | `services/summary_generator.py:204-241` |
| RAG-инжект (только сюда) | `services/summary_generator.py:164-168` |
| Сборка user-content (архив/свежее) | `services/summary_generator.py:341-376` (`_compose_user_content`) |
| Канон «Архивная справка» | `services/summary_prompts.py:38-39`; сборка `_SUMMARY_R1021_BASE` → `SYSTEM_PROMPT` (`:57-62`) |
| Слепки | `PREV_R1021_SUMMARY_SYSTEM_PROMPT` (`:53-55`), `PREV_SUMMARY_SYSTEM_PROMPT` (`:65+`) |
| cleanup | `services/summary_generator.py:241`; `services/summary_cleanup.py:20-30` |
| Стриминг / чанки | `services/summary_generator.py:380-441`, `:443-475` |
| Постфикс «шиз» | `services/summary_generator.py:249` (`_ensure_shiz_postfix`) |
| Флаг стриминга | `limits`/`settings.SUMMARY_STREAMING_ENABLED` (`:250-254`) |

### 0.1. Расхождения/инварианты

- «Уничтожать исторические факты, если не относятся к сегодняшней теме» → делает **Редактор**
  (Stage 1); Рассказчик историю не видит вообще.
- Инвариант R11: итоговый текст — **plain**, без markdown/списков/эмодзи; `{username}`-постфикс
  и `_ensure_shiz_postfix` сохраняются (их добавляет **код**, не LLM).
- Стриминг/HTML-доставка не ломаются: генерация остаётся в `summary_generator`, меняется только
  число LLM-вызовов до `text`.

---

## 1. Цель

Разделить генерацию саммари на **Редактор** (сырая история + RAG → чистая Markdown-выжимка,
отсев нерелевантной истории, без системных тегов) → **Рассказчик** (только выжимка → связный
текст). Устранить «пришивание» нерелевантной архивной справки.

## 2. Архитектура

### 2.1. Поток

```
xml_context + l2_quotes + l3_facts + graph_facts + rag_context
        │
        ▼  [Stage 1 — РЕДАКТОР]
   system = SUMMARY_EDITOR_*     (правила R11: архив ≠ свежее; фильтр мусора)
   user   = _compose_user_content(...)   ← сюда ЕДИНСТВЕННО подаётся rag_context
   → "digest": чистая Markdown-выжимка (события, факты), БЕЗ системных тегов/fact:ID
        │
         ▼  [Stage 2 — РАССКАЗЧИК]
   system = SUMMARY_NARRATOR_*   (стиль R11: токсичный, plain-text, без markdown)
   user   = "ВЫЖИМКА (Markdown):\n{digest}"     ← ЕДИНСТВЕННЫЙ вход
   → связный текст (plain)
         │
   → **Validator Loop (F6, §2.5):** детектор клише → брак → возврат Рассказчику (≤2 ретрая)
         │
   → cleanup_llm_text → _ensure_shiz_postfix → streaming/chunked
```

### 2.2. Контракт Редактора (Chain Handoff Spec)

- Формат: **Markdown** (заголовки/абзацы/маркированные пункты — внутренний формат, не для пользователя).
- Обязательное содержимое: хронологичный список событий «кто с кем / что обсуждалось / итог».
- **Отсев:** исторические факты (`<historical_graph_facts>`, `<memory>`, `<facts>`) включаются
  только если прямо релевантны сегодняшней теме; иначе — **выбрасываются** (ТЗ).
- Запрещено: `fact:\d+`, `msg:\d+`, любые служебные теги, сырые ID, «Архивная справка» как текст.
- Пустой/невалидный digest → fallback на одиночный путь 10.21.

### 2.3. Контракт Рассказчика

- Вход: **только** digest. Ни истории, ни RAG, ни архива.
- Выход: связный **plain-text** без markdown/списков/эмодзи (R11), стиль — `STYLE_BLOCKS_SUFFIX`.
- Не «пришивает» факты сбоку; не выдумывает события, которых нет в digest.
- Не добавляет финальный постфикс шиза — его добавляет код.

### 2.4. Интеграция с доставкой

- Меняется только участок до `text` (`summary_generator.py:241-249`); `_send_streaming`/
  `_send_chunked`/`_send_one_chunk` (`:380-475`) — **без изменений**.
- `focus` («/summary про X») продолжает применяться к user-content **Редактора**.
- `cleanup_llm_text` вызывается на выходе Рассказчика.

### 2.5. Validator Loop на выходе Рассказчика (UPD3 §3, F6)

- Stage-2 вызывается через `services/negative_constraints.verbalize_validated(...)`
  (`max_retries=2`): детектор ИИ-клише → при находке ответ **бракуется** и Рассказчик
  вызывается заново с `CLICHE_RETRY_SYSTEM_PROMPT` (тот же вход = digest). ≤3 вызова Stage-2.
- **При исчерпании** — вернуть лучший вариант (минимум клише), очищенный scrubber'ом (fail-open,
  пользователь получает саммари); если текст пуст → fallback одиночный путь 10.21.
- **Д-8:** лёгкий code-strip markdown из выхода Рассказчика допускается **только как последняя
  сеть** (защита R11); клише кодом **не** вырезаются.
- OFF `SYSTEM2_VALIDATOR_LOOP_ENABLED` → Stage-2 напрямую.

## 3. Контракты

- Stage-2 получает только digest в labelled-блоке; никаких system headers/черновиков.
- Новые константы `SUMMARY_EDITOR_SYSTEM_PROMPT` / `SUMMARY_NARRATOR_SYSTEM_PROMPT` +
  `PREV_*`-слепки; канон-миграция ADR-1013-3 (один коммит с F6→F3→F4→F5).

## 4. Feature Flags / Progressive Delivery

- `SYSTEM2_SUMMARY_ENABLED` — env-only `ClassVar`, **default ON**, Δ каталога = **0**.
- `SYSTEM2_VALIDATOR_LOOP_ENABLED` (F6) — env-only, **default ON**, Δ каталога = **0**.
- OFF → одиночный путь 10.21.

## 5. Kill-switch / fallback / откат

- Kill-switch: флаг OFF.
- Fallback: невалидный digest/таймаут Stage-1 → одиночный путь; таймаут Stage-2 → 10.21;
  клише после 2 ретраев → лучший вариант (fail-open), пусто → 10.21 (§2.5).
- Откат: флаг OFF / `git revert` + обратная канон-миграция.

## 6. Стоимость / латентность (×2)

- +1 LLM-вызов на саммари. Validator-loop — `+0…+2` к Stage-2 **только при срабатывании** (bounded).
  Бюджет — `limits.summary_max_context_tokens` (Редактор) и короткий лимит digest (Рассказчик).
  Латентность: +1 round-trip; стриминг скрывает частично.

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Стриминг/HTML-доставка ломается | Интеграция только до `text`; регресс `_send_streaming`/`_send_chunked` |
| R2 | High | Редактор вырежет полезные свежие факты | Тест «отсекается только нерелевантная история, свежее сохраняется» |
| R3 | Medium | Рассказчик снова «пришивает» архив | Контракт «только digest»; изоляция входа |
| R4 | Medium | Канон-атомарность | `PREV_*` + один коммит |
| R5 | Medium | Рассказчик эхо-ит markdown в финал (нарушение R11) | Промпт + тест на отсутствие markdown; при необходимости — лёгкий code-strip |
| R6 | R17/R18 | Сырая история утекает в логи/отчёт | R17-safe логи (числа) |
| R7 | Medium | Validator-loop: лишние вызовы/не зацикливаться | `max_retries=2` + fail-open (лучший вариант) |

## 8. Открытые вопросы

- Д-6/Д-7/Д-8 **закрыты** UPD3: ×2 стоимость принята; fallback — да; клише кодом не вырезаются,
  regex-стрип — только теги (последняя сеть). См. `round1022-human-gate-map.md`.

## 9. Задачи

См. `tasks.md` (T-2044…T-2052 + **T-2095** интеграция `verbalize_validated` в Рассказчик).



## 10. Реализация (Шаг 4 @Builder, 18.09.2026)

`SUMMARY_EDITOR_SYSTEM_PROMPT` (Markdown-выжимка, отсев нерелевантного архива)
и `SUMMARY_NARRATOR_SYSTEM_PROMPT` (вход только выжимка, R11 plain) в
`summary_prompts.py`; `SummaryGenerator._generate_two_call` +
`validate_summary_digest`; Рассказчик через `verbalize_validated` (лучший
вариант при исчерпании, пусто → 10.21); стриминг/чанки и `_ensure_shiz_postfix`
не тронуты; `rag_context` — только Редактору. Флаг `SYSTEM2_SUMMARY_ENABLED`
(env-only ON). Тесты: `test_summary_two_call_round1022.py`. Полный pytest 6876/0.
