# spec.md — F3 `system2-factcheck-two-call-round1022`

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 2b @Architect · Тип: backend/LLM + канон промптов
> **ADR:** `ADR-1022-3.md` (**Accepted — UPD3: validator-loop**). **Задачи:** `tasks.md` (T-2035…T-2043 + T-2094).
> **ТЗ:** `plans/current_task.md`, «ЧАСТЬ 1 → 1. Фактчекер (2 шага)» (200–204); UPD3 §3 (259–262).
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Текущий один вызов `check_claim` | `services/factcheck_service.py:55-157` |
| CoVe в одном промпте (`<reasoning>`) | `services/factcheck_prompts.py:123-130`; сборка канона `:138-144` |
| Grounding-якоря (доверенные) | `services/factcheck_service.py:135-140`; `services/grounding_validator.py` (`collect_allowed_anchors`/`strip_phantom_tags`) |
| cleanup/strip тегов | `services/factcheck_service.py:128`; `services/reply_postprocess.py:39-74` |
| Инструменты фактчека (Full Tool Access) | `services/factcheck_service.py:98-118` (`factcheck_tools`, `chat_with_tools`) |
| Слепок 10.21 | `PREV_FACTCHECK_R1021_SYSTEM_PROMPT` (`factcheck_prompts.py:134-136`) |
| Канон-миграции промптов | `services/prompt_migrations.py` (+ PREV-слепки, `ROLLBACK_MIGRATIONS`) |

### 0.1. Расхождения/уточнения ТЗ

- «Вербализатор физически отрезан от базы и тегов» — реализуемо строго: Stage-2 не получает
  ни `rag`, ни `results`, ни `tool_context`, ни якоря. Это главное архитектурное решение.
- Grounding **не удаляется**: он переносится на выход Stage-1 (Аналитик) и дублируется
  regex-предохранителем F6 на выходе Stage-2 (последняя сетка).
- ТЗ-костыль `<thought>` внутри одного промпта **AMENDS** подход 10.21: слепки `PREV_*_R1021`
  сохраняются, канон-миграция обязательна (ADR-1013-3).

---

## 1. Цель

Заменить одиночный `<reasoning>`-вызов на **физический конвейер из двух независимых вызовов**:
Слой 1 — Аналитик (текст юзера + сырые факты RAG → строгий JSON, перевод `fact:ID`/дат в
человеческое время); Слой 2 — Вербализатор (вход только JSON; без БД/инструментов/тегов).

## 2. Архитектура

### 2.1. Поток

```
target_text (reply-цель) + user_hint + forward_source + chat_context
        │
        ▼  [Stage 1 — АНАЛИТИК]
   system = FACTCHECK_ANALYST_*        (доступ к RAG/поиску/тулам — как сейчас)
   user   = <claim> + <context> + <rag> + выдача поиска + tool_context
   → raw_analyst  (СТРОГО JSON; допускается CoVe-черновик в <reasoning>, срезается)
        │
   strip_reasoning_tags → strip_phantom_tags(anchors) → strict JSON parse/validate
        │
        ▼  [Stage 2 — ВЕРБАЛИЗАТОР]
   system = FACTCHECK_VERBALIZER_*     (style из prompt_style_blocks; БЕЗ доступа к сырью)
   user   = "АНАЛИЗ (JSON): {validated json}"      ← ЕДИНСТВЕННЫЙ вход
   → финальный дерзкий текст (plain, без маркдауна, как канон фактчека)
        │
   → **Validator Loop (F6, §2.5):** детектор клише → брак → возврат Вербализатору (≤2 ретрая)
         │
   cleanup_llm_text + strip_phantom_tags (belt-and-suspenders)  → send (chokepoint F6)
```

### 2.2. JSON-контракт Аналитика (Chain Handoff Spec)

Валидатор требует **строго** эти поля (лишние игнорируются, отсутствующие → ошибка):

```json
{
  "claim": "краткая суть проверяемого тезиса",
  "findings": [
    {
      "assertion": "проверяемое утверждение",
      "status": "true|false|misleading|unverifiable",
      "human_time": "человеческое время (напр. 'в августе' / 'без даты')",
      "author": "имя автора или null",
      "evidence": "краткий довод из RAG/поиска БЕЗ системных тегов и fact:ID"
    }
  ],
  "verdict": "сухой итог, БЕЗ fact:ID/msg:ID/фантомных дат",
  "tone_hint": "необязательная подсказка стиля"
}
```

**Правило изоляции:** `human_time` обязан быть человеческим описанием; перевод `fact:ID` и
`ММ.ГГГГ`/ISO-дат выполняет Аналитик. Валидатор отвергает JSON, если в любом строковом поле
остался `fact:\d+`/`msg:\d+` или `[ММ.ГГГГ | …]` вне `human_time` (см. §3).

### 2.3. Парсинг / fallback

1. Строгий парсер: срезать ```` ```json ```` fences, взять первый `{…}`, `json.loads`, проверить схему.
2. Ошибка/усечение/пусто → **fallback на одиночный путь 10.21** (существующий
   `FACTCHECK_SYSTEM_PROMPT` с CoVe + grounding) — пользователь **всегда** получает ответ.
3. Kill-switch `SYSTEM2_FACTCHECK_ENABLED=false` → сразу одиночный путь (байт-в-байт 10.21).
4. Никогда не «догадываться» о содержимом невалидного JSON.

### 2.4. Grounding-интеграция

- Trusted-якоря как сейчас: `rag` + `results` + `chat_context` + `tool_context`
  (`factcheck_service.py:129-140`); `<claim>`/`<user_hint>` — **исключены** (S10.21-5).
- `strip_phantom_tags` применяется к выходу Аналитика (до парсинга JSON) и к финалу Вербализатора.
- S10.21-4 (дата-только без `fact:ID`) сохраняется.

### 2.5. Validator Loop на выходе Вербализатора (UPD3 §3, F6)

- Stage-2 вызывается через общий `services/negative_constraints.verbalize_validated(...)`
  (`max_retries=2`): Python-детектор запрещённых ИИ-клише → при находке **весь ответ бракуется**
  и Вербализатор вызывается заново с `CLICHE_RETRY_SYSTEM_PROMPT` (тот же вход = валидированный
  JSON). ≤3 вызовов Stage-2 суммарно.
- **При исчерпании ретраев** — **fallback на одиночный путь 10.21** (существующий
  `FACTCHECK_SYSTEM_PROMPT` с CoVe + grounding): пользователь всегда получает корректный ответ.
- Regex Scrubber (F6) — последняя сеть: тихо режет `<thought>`/`fact:\d+`/`msg:\d+` (клише —
  **не** вырезаются; см. F6 §2).
- OFF `SYSTEM2_VALIDATOR_LOOP_ENABLED` → Stage-2 напрямую (scrubber остаётся).

## 3. Контракты

- Stage-2 получает **только** валидированный JSON в labelled-блоке, без system headers,
  без черновиков, без якорей.
- Выход Stage-2: plain-text, без markdown/списков/эмодзи (канон фактчека), стиль —
  `STYLE_BLOCKS_SUFFIX` из `services/prompt_style_blocks.py`.
- Канон-константы: `FACTCHECK_ANALYST_SYSTEM_PROMPT`, `FACTCHECK_VERBALIZER_SYSTEM_PROMPT`,
  новые `PREV_*`-слепки; единый `PROMPT_MIGRATIONS`-контур (ADR-1013-3).

## 4. Feature Flags / Progressive Delivery

- `SYSTEM2_FACTCHECK_ENABLED` — env-only `ClassVar`, **default ON**, Δ каталога = **0**.
- `SYSTEM2_VALIDATOR_LOOP_ENABLED` (F6) — env-only, **default ON**, Δ каталога = **0**.
- OFF → одиночный путь 10.21 (kill-switch). Поэтапная раскатка % не требуется (прецедент 10.21).

## 5. Kill-switch / fallback / откат

- Kill-switch: флаг OFF → 10.21.
- Fallback: невалидный JSON/таймаут Stage-1 → 10.21; таймаут Stage-2 → вернуть валидированный
  Stage-1 JSON → одиночный путь при провале; клише после 2 ретраев → **10.21** (§2.5).
- Откат: флаг OFF / `git revert` + обратная канон-миграция (`rollback_prompt_canons`).

## 6. Стоимость / латентность (×2)

- Базово 2 LLM-вызова вместо 1 (в tool-пути Stage-1 = существующий tool-loop ≤4 раундов,
  Stage-2 = +1). Validator-loop — `+0…+2` вызова Stage-2 **только при срабатывании клише** (bounded).
  Итого обычно ≈ **+1 вызов** на фактчек.
- Лимит: `limits.factcheck_max_symbols`; таймауты per-stage; при `SYSTEM2_*` бюджете —
  bounded. Логи — только числа/латентность (R17).

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Двойная стоимость/латентность | Лимиты/таймауты; fallback; kill-switch |
| R2 | High | Невалидный/усечённый JSON Аналитика | Строгий парсер + fallback на 10.21 |
| R3 | High | Утечка `fact:\d+`/`msg:\d+` через Вербализатор | Изоляция входа + `strip_phantom_tags` + chokepoint F6 |
| R4 | Medium | Канон-атомарность (ADR-1013-3) | `PREV_*_R1021` не терять; один коммит |
| R5 | Medium | «Человеческое время» искажает дату | Тест перевода `fact:ID`/дат; Аналитик без домыслов |
| R6 | R17/R18 | Сырые логи/факты с секретами | R17-safe логи (только числа) |
| R7 | Medium | Validator-loop: лишние вызовы/не зацикливаться | `max_retries=2` (≤3 Stage-2) + fail-open + fallback 10.21 при исчерпании |

## 8. Открытые вопросы

- Д-5/Д-6/Д-7 **закрыты** UPD3: отдельные env-флаги (default ON), ×2 стоимость принята,
  fallback на 10.21 — да. См. `round1022-human-gate-map.md`. Открытых нет.

## 9. Задачи

См. `tasks.md` (T-2035…T-2043 + **T-2094** интеграция `verbalize_validated` в Stage-2 фактчека).



## 10. Реализация (Шаг 4 @Builder, 18.09.2026)

`FACTCHECK_ANALYST_SYSTEM_PROMPT` (строгий JSON, человеческое время) и
`FACTCHECK_VERBALIZER_SYSTEM_PROMPT` (вход только JSON, стиль A/B) в
`factcheck_prompts.py`; `FactCheckService` — 2 вызова + строгий парсер
`system2_handoff.parse_factcheck_analysis`, grounding на обоих слоях,
fallback на одиночный путь 10.21; Stage-2 через `verbalize_validated`.
Флаг `SYSTEM2_FACTCHECK_ENABLED` (env-only ON). Тесты:
`test_factcheck_two_call_round1022.py`. Полный pytest 6876/0.
