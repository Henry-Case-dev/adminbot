# spec.md — F5 `system2-direct-chat-two-call-round1022`

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 2b @Architect · Тип: backend/LLM (tool-loop) + канон промптов
> **ADR:** `ADR-1022-5.md` (**Accepted — UPD3: validator-loop**). **Задачи:** `tasks.md` (T-2053…T-2061 + T-2096).
> **ТЗ:** `plans/current_task.md`, «ЧАСТЬ 1 → 3. Direct Chat (Прямые ответы) (2 шага)» (210–213); UPD3 §3 (259–262).
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Вызов tool-цикла в прямом чате | `services/direct_chat_service.py:714-764` |
| `ToolLoopResult` (str + телеметрия) | `services/tool_loop.py:48-73` |
| «Каша логов» инструментов | `services/tool_loop.py:104` (`tool_context_parts`), `:169-171` (`tool_context`, `tool_trace`) |
| Bounded-раунды | `services/tool_loop.py:38` (`TOOL_MAX_ROUNDS=4`), `:39` |
| Degraded-путь | `services/tool_loop.py:76-86`, `:174-179`; обработка `direct_chat_service.py:750-755` |
| `lore_compiled` HTML-доставка | `services/direct_chat_service.py:756-773` |
| Пост-обработка | `services/reply_postprocess.py:39-74` |
| Канон direct-чата | `services/chat_prompts.py` (`CHAT_SYSTEM_PROMPT`, `PREV_*`/`LEGACY_*`) |

### 0.1. Расхождения/инварианты

- ТЗ: «Синтезатор тулов: вход — сообщение юзера + каша из логов (Exa, RAG, API) → чистая
  информационная справка в JSON; Вербализатор пишет финальный ответ, опираясь только на справку».
- Инвариант: **не сломать** degraded-путь, `round_limit`, `lore_compiled`-доставку, порядок
  роутеров `bot.py` (только DI-kwargs).
- Инвариант R17: `tool_context` может содержать токены/секреты → санитизация входа Синтезатора
  и запрет логирования.

---

## 1. Цель

Убрать перегрузку прямого ответа логами инструментов: Синтезатор тулов превращает «кашу логов»
в чистую **JSON-справку**, а отдельный Вербализатор пишет финальный ответ, видя **только** справку.

## 2. Архитектура

### 2.1. Поток

```
сообщение юзера + payload (chat system)
        │
        ▼  [tool-loop — исполнение инструментов, без изменений]
   ToolLoopResult: text (финал модели), tool_trace[], tool_context (сырые выводы тулов)
        │
        ├─ ctx.lore_compiled?  →  ДЕТЕРМИНИРОВАННАЯ HTML-история (существующий путь, без LLM-2)
        │
        ├─ тулы НЕ вызывались (tool_trace пуст)  →  одиночный путь (финал tool-loop)
        │
        └─ тулы вызывались:
              ▼  [Stage 1 — СИНТЕЗАТОР ТУЛОВ]
                 system = DIRECT_SYNTHESIZER_*  (роль «аналитик», БЕЗ стиля)
                 user   = сообщение юзера + sanitized(tool_context) + сводка tool_trace
                 → raw_synth (СТРОГО JSON; CoVe-черновик срезается)
                 → strict parse/validate
                    │
                     ▼  [Stage 2 — ВЕРБАЛИЗАТОР]
                  system = DIRECT_VERBALIZER_*  (стиль STYLE_BLOCKS_SUFFIX)
                  user   = "СПРАВКА (JSON): {validated json}"   ← ЕДИНСТВЕННЫЙ вход
                  → финальный ответ (plain)
                     │
                  → **Validator Loop (F6, §2.5):** детектор клише → брак → возврат Вербализатору (≤2)
                     │
                  → strip_reasoning_tags → send (chokepoint F6)
```

### 2.2. JSON-контракт Синтезатора (Chain Handoff Spec)

```json
{
  "user_question": "краткая суть запроса",
  "facts": [
    {
      "topic": "тема",
      "finding": "чистая выжимка без логов/токенов",
      "source": "exa|rag|lore|api|unknown",
      "confidence": "high|medium|low"
    }
  ],
  "answer_outline": "план ответа / ключевой вывод",
  "limitations": ["чего не удалось выяснить"]
}
```

Запрещено в JSON: сырые логи инструментов, URL с токенами, `fact:\d+`, `msg:\d+`, `<thought>`.

### 2.3. Парсинг / fallback / degraded

1. Невалидный JSON/таймаут Синтезатора → использовать финал tool-loop (`ToolLoopResult.text`)
   как есть (одиночный путь) — пользователь всегда получает ответ.
2. `degraded=True` (`round_limit`/`llm_error`) → существующее поведение сохраняется; System-2
   включается только для успешного tool-финала.
3. `lore_compiled` → **не** запускать Stage 1/2 (детерминированная история в коде).
4. Kill-switch `SYSTEM2_DIRECT_ENABLED=false` → одиночный путь 10.21.

### 2.4. R17-санитизация перед Синтезатором

- Собирать «кашу» из `tool_context`/`tool_trace` (`tool_loop.py:169-171`).
- Прогнать через маскирование секретов/токенов (regex по ключам `sk-`, `Bearer`, длинным
  токен-подобным строкам; прецедент R17) **до** подачи в промпт.
- Не логировать содержимое `tool_context` (только длины/имена тулов).

### 2.5. Validator Loop на выходе Вербализатора (UPD3 §3, F6)

- Stage-2 вызывается через `services/negative_constraints.verbalize_validated(...)`
  (`max_retries=2`): детектор ИИ-клише → при находке ответ **бракуется** и Вербализатор
  вызывается заново с `CLICHE_RETRY_SYSTEM_PROMPT` (тот же вход = JSON-справка). ≤3 вызова Stage-2.
- **При исчерпании** — вернуть лучший вариант (fail-open); если пусто/ошибка → финал tool-loop.
- Scrubber (F6) — последняя сеть (режет только теги, не клише). OFF
  `SYSTEM2_VALIDATOR_LOOP_ENABLED` → Stage-2 напрямую.

## 3. Контракты

- Stage-2 получает только валидированный JSON; ни `tool_context`, ни `tool_trace`, ни истории.
- Новые константы `DIRECT_SYNTHESIZER_SYSTEM_PROMPT` / `DIRECT_VERBALIZER_SYSTEM_PROMPT` +
  `PREV_*`; канон-миграция ADR-1013-3 (сериализация F6→F3→F4→F5).
- Порядок роутеров `bot.py` не меняется (только DI-kwargs).

## 4. Feature Flags / Progressive Delivery

- `SYSTEM2_DIRECT_ENABLED` — env-only `ClassVar`, **default ON**, Δ каталога = **0**.
- `SYSTEM2_VALIDATOR_LOOP_ENABLED` (F6) — env-only, **default ON**, Δ каталога = **0**.
- OFF → одиночный путь 10.21.

## 5. Kill-switch / fallback / откат

- Kill-switch: флаг OFF.
- Fallback: невалидный JSON/таймаут → финал tool-loop; degraded/`lore_compiled` — без изменений;
  клише после 2 ретраев → лучший вариант (fail-open), пусто/ошибка → финал tool-loop (§2.5).
- Откат: флаг OFF / `git revert` + обратная канон-миграция.

## 6. Стоимость / латентность (×2)

- Стоимость: tool-loop (≤4) + Синтезатор (1) + Вербализатор (1) при использовании тулов;
  validator-loop — `+0…+2` к Stage-2 только при срабатывании. Максимум ≈ 6 вызовов (было ≤4).
  Требует bounded-таймаутов и опции «не синтезировать при тривиальном tool-результате» (Д-6).
- Латентность: +2 round-trip в tool-сценарии. Решение о приемлемости — Д-6 (закрыт UPD3).

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Сломать degraded/`lore_compiled` | Явные ветки §2.3; регресс-тесты |
| R2 | High | Утечка токенов/секретов из логов тулов в промпт | R17-санитизация (§2.4) + запрет логирования |
| R3 | Medium | Невалидная JSON-справка | Строгий парсер + fallback на финал tool-loop |
| R4 | Medium | Двойная стоимость/латентность | Лимиты/таймауты; Д-6 |
| R5 | Medium | Канон-атомарность; сдвиг порядка роутеров `bot.py` | Только DI-kwargs; один коммит |
| R6 | R17/R18 | Логи инструментов с чувствительными значениями | Маскировать, не логировать |
| R7 | Medium | Validator-loop: лишние вызовы/не зацикливаться | `max_retries=2` + fail-open (лучший вариант → tool-loop) |

## 8. Открытые вопросы

- Д-6/Д-7/Д-9 **закрыты** UPD3: ×2 стоимость принята; fallback — да; `lore_compiled` — вне System 2.
  См. `round1022-human-gate-map.md`.

## 9. Задачи

См. `tasks.md` (T-2053…T-2061 + **T-2096** интеграция `verbalize_validated` в Вербализатор).



## 10. Реализация (Шаг 4 @Builder, 18.09.2026)

`DIRECT_SYNTHESIZER_SYSTEM_PROMPT` (сообщение + санитизированная «каша» логов →
JSON-справка) и `DIRECT_VERBALIZER_SYSTEM_PROMPT` (только справка, стиль A/B) в
`chat_prompts.py`; `DirectChatService._synthesize_direct_answer` — System 2
включается только при непустом `tool_trace`, успешном финале и НЕ `lore_compiled`;
`degraded` и `lore_compiled` — существующие ветки; R17-маскировка `tool_context`
(`redact_secrets`); любой сбой → финал tool-loop; Вербализатор через
`verbalize_validated`. Флаг `SYSTEM2_DIRECT_ENABLED` (env-only ON). Тесты:
`test_direct_two_call_round1022.py`. Порядок роутеров `bot.py` не менялся.
Полный pytest 6876/0.
