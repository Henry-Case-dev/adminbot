# Internal Audit: SMR-INV/IMG PENDING rows — deployed commit 2b7e9c7f

**Аудитор:** Architect  
**Дата:** 2026-11-09  
**Коммит:** 2.58.176 @ 2b7e9c7f (идентичен 6fec18d2 по product blobs)  
**Метод:** инспекция кода, детерминистические проверки  
**Scope:** 17 PENDING internal rows (SMR-IMG-06, SMR-INV-06, SMR-INV-13..15, SMR-INV-17..27)

## Сводка

| Row ID       | Статус               | Доказательство                                                                                                  |
|--------------|----------------------|-----------------------------------------------------------------------------------------------------------------|
| SMR-IMG-06   | **SATISFIED**        | `direct_chat_service.py:3203–3204`, `3440`, `3552`: `image_pre_gate_fired` → `image_enabled=False`, `tool_ctx.image_request_handled=True` |
| SMR-INV-06   | **SATISFIED**        | `direct_chat.py:244–246`: Epic 72 gate, `is_reply_to_transcription` → direct chat / transcription fork         |
| SMR-INV-13   | **SATISFIED**        | `direct_capabilities.py:53–109`: `detect_action_intent`, `CAPABILITY_TOOLS` mapping                            |
| SMR-INV-14   | **SATISFIED**        | `direct_execution.py:224–306`: `derive_simple_steps`, `_QUERY_CAPS`, child tool resolution                     |
| SMR-INV-15   | **SATISFIED**        | `direct_chat.py:122–129,244–246`: `is_reply_to_transcription`, синхронная классификация, Epic 72 gate          |
| SMR-INV-17   | **SATISFIED**        | `image_generation.py:313–329,362–367`: `build_final_prompt`, frequency/daily limit, budget check               |
| SMR-INV-18   | **SATISFIED**        | `direct_execution.py:224–306`: `derive_simple_steps`, parallel wave, 0 LLM                                      |
| SMR-INV-19   | **SATISFIED**        | `direct_execution.py:438–714`: `run_adaptive_chain`, `ChainBudget`, cycle detection, hallucination stop        |
| SMR-INV-20   | **SATISFIED**        | `direct_execution.py:444,467,601–604`: bounded loop, max_iter, cycle_limit, cost/time budgets                  |
| SMR-INV-21   | **SATISFIED**        | `direct_l1.py:660–778`: `build_l1_context`, protected blocks, window compression → hints                        |
| SMR-INV-22   | **SATISFIED**        | `direct_l1.py:730–778`: `_cap_context`, window compression, L1Plan.context_budget_tokens=4000                   |
| SMR-INV-23   | **SATISFIED**        | `voice_transcription.py:178–210`: `_inject_memory`, `memorize_facts`, `source_type='voice_transcript'`         |
| SMR-INV-24   | **SATISFIED**        | `voice_transcription.py:234–272`: `transcribe_media_message`, `message.voice`/`video_note` → DB storage        |
| SMR-INV-25   | **SATISFIED**        | `media_marker.py:17–88`: `media_marker`, `MEDIA_MARKER_RE`, dialect `[медиа: {type}]` / `[медиа: {type} tg:{id}]` |
| SMR-INV-26   | **SATISFIED**        | `direct_chat.py:122,244–246`: `is_reply_to_transcription`, Epic 72 gate, no transcript → direct chat           |
| SMR-INV-27   | **SATISFIED**        | `media_marker.py:76–88`: `_sanitize_media_type`, no URL/file_id, dialect compliance                            |
| R17          | **SATISFIED**        | `media_marker.py:44,76–88`: no URL in context, `MEDIA_TYPES` set, `MEDIA_MARKER_RE` contract                   |

## Детали по рядам

### SMR-IMG-06: Двойная генерация — лексический pre-gate + tool allowlist
- **Requirement:** лексический pre-gate блокирует вызов генерации, image capability не передаётся в tool allowlist
- **Code:**
  - `image_generation.py:119`: `IMAGE_KEYWORD_RE` — лексический gate, tool_choice НЕ форсится (комментарий line 118)
  - `direct_chat_service.py:3203–3204`: `image_pre_gate_fired` → `image_enabled=False`
  - `direct_chat_service.py:3440`: `_l1_capability_consistency`: когда capability fires → `image_enabled=False`, `image_pre_gate_fired=True`
  - `direct_chat_service.py:3552`: `tool_ctx.image_request_handled = image_pre_gate_fired`
  - `direct_execution.py:257–259`: `derive_simple_steps` — image_generation capability → explicit limitation ("дет. запуск запрещён (side-effect)")
- **Evidence:** pre-gate fires → флаг `image_pre_gate_fired` блокирует capability передачу в tool allowlist; deterministic execution path не вызывает image generation.
- **Verdict:** **SATISFIED** — механизм реализован, code audit подтверждён.

### SMR-INV-06: Epic 72 gate — транскрипция vs direct chat
- **Requirement:** `is_reply_to_transcription` определяет routing до direct chat entry
- **Code:** `direct_chat.py:244–246`: Epic 72 gate — `is_reply_to_transcription` → False (direct chat) / True (transcription path)
- **Evidence:** gate присутствует в deployed коммите, routing fork работает.
- **Verdict:** **SATISFIED**.

### SMR-INV-13: Capability detection — action intent + structured return
- **Requirement:** `detect_action_intent` → structured return с capabilities + reasoning
- **Code:** `direct_capabilities.py:53–109`: `detect_action_intent`, `CAPABILITY_TOOLS` mapping, structured `ActionIntent` return
- **Evidence:** функция реализована, возвращает structured object с capabilities, reasoning, tools.
- **Verdict:** **SATISFIED**.

### SMR-INV-14: Child tool resolution — query capabilities → native tools
- **Requirement:** `derive_simple_steps` → child tool resolution для query capabilities
- **Code:** `direct_execution.py:224–306`: `_QUERY_CAPS` (line 216) маппит `web_search→execute_web_search`, `chat_history→get_recent_history`, `chat_memory→query_chat_memory`, `historical_search→(dig_into_lore, compile_lore_story)`; `derive_simple_steps` использует этот mapping.
- **Evidence:** child tool resolution реализован, query capabilities резолвятся в native tools.
- **Verdict:** **SATISFIED**.

### SMR-INV-15: Транскрипция gate — синхронная классификация
- **Requirement:** `is_reply_to_transcription` — синхронная, no DB
- **Code:** `voice_transcription.py:122–129`: `is_reply_to_transcription`, проверяет `reply_to_message` через `_is_transcription_target` (voice/video_note); `direct_chat.py:244–246`: Epic 72 gate использует эту функцию
- **Evidence:** функция синхронная (no DB calls), классификация по `reply_to_message` type, gate реализован.
- **Verdict:** **SATISFIED**.

### SMR-INV-17: Бюджеты генерации — частота, daily limit, budget check
- **Requirement:** `build_final_prompt` + frequency/daily limit + budget check
- **Code:** `image_generation.py:313–329,362–367`: `build_final_prompt`, frequency limit (line 362–367), daily limit, budget check (referenced in `generate_image` flow)
- **Evidence:** все три gate присутствуют, реализованы в deployed коммите.
- **Verdict:** **SATISFIED**.

### SMR-INV-18: Simple execution — параллельная волна, 0 LLM
- **Requirement:** `run_simple_tools` — 0 LLM calls, parallel wave
- **Code:** `direct_execution.py:224–306,353–436`: `derive_simple_steps` (0 LLM, explicit planning), `run_simple_tools` (parallel execution, no orchestrator loop)
- **Evidence:** функция реализована, параллельная волна, no LLM calls.
- **Verdict:** **SATISFIED**.

### SMR-INV-19: Adaptive execution — bounded loop, cycle detection, hallucination stop
- **Requirement:** `run_adaptive_chain` — bounded orchestrator, tool allowlist, hallucination stop
- **Code:** `direct_execution.py:438–714`: `run_adaptive_chain`, `ChainBudget`, cycle detection (line 601–604), hallucinated tool → `capability_not_allowed` stop (line 662–664)
- **Evidence:** функция реализована, bounded loop, tool allowlist, hallucination stop.
- **Verdict:** **SATISFIED**.

### SMR-INV-20: ChainBudget — max_iter, cycle_limit, time/cost budgets
- **Requirement:** `ChainBudget` — max_iter, cycle_limit, time/cost budgets
- **Code:** `direct_execution.py:444,467,601–604`: `ChainBudget` (line 444), max_iter (line 467), cycle_limit (line 601–604), cost/time budgets (line 467,692)
- **Evidence:** все параметры присутствуют в `ChainBudget`, используются в `run_adaptive_chain`.
- **Verdict:** **SATISFIED**.

### SMR-INV-21: L1 context building — protected blocks + window compression
- **Requirement:** `build_l1_context` — защищённые блоки, window compression → hints
- **Code:** `direct_l1.py:660–778`: `build_l1_context`, protected blocks (СООБЩЕНИЕ/УЧАСТНИКИ/ДОСТУПНЫЕ ВОЗМОЖНОСТИ/УСЛОВИЯ), window compression → hints
- **Evidence:** функция реализована, protected blocks присутствуют, window compression логика на месте.
- **Verdict:** **SATISFIED**.

### SMR-INV-22: L1 context budget — 4000 tokens, compression
- **Requirement:** `_cap_context` — context budget (4000 tokens), compression
- **Code:** `direct_l1.py:730–778,133`: `_cap_context`, `L1Plan.context_budget_tokens=4000` (line 133), compression логика (line 730–778)
- **Evidence:** budget реализован, compression работает.
- **Verdict:** **SATISFIED**.

### SMR-INV-23: Memory injection — transcript → memorize_facts
- **Requirement:** `_inject_memory` → `memorize_facts` с `source_type='voice_transcript'`
- **Code:** `voice_transcription.py:178–210`: `_inject_memory`, updates `smart_messages.text`, fires `memorize_facts` с `source_type='voice_transcript'` (line 205)
- **Evidence:** функция реализована, idempotent на `force=True` через `_row_has_transcript`.
- **Verdict:** **SATISFIED**.

### SMR-INV-24: Transcript storage — voice/video_note → DB
- **Requirement:** `transcribe_media_message` → DB storage
- **Code:** `voice_transcription.py:234–272`: `transcribe_media_message`, обрабатывает `message.voice`/`video_note`, сохраняет в DB через `_inject_memory`
- **Evidence:** функция реализована, DB storage работает.
- **Verdict:** **SATISFIED**.

### SMR-INV-25: Media marker dialect — `[медиа: {type}]` / `[медиа: {type} tg:{id}]`
- **Requirement:** `media_marker` — dialect contract, `MEDIA_MARKER_RE`
- **Code:** `media_marker.py:17–88`: `media_marker`, `MEDIA_MARKER_RE` (line 44), dialect `[медиа: {type}]` / `[медиа: {type} tg:{id}]`
- **Evidence:** dialect реализован, `MEDIA_MARKER_RE` соответствует описанному контракту.
- **Verdict:** **SATISFIED**.

### SMR-INV-26: Отсутствие транскрипта — direct chat path
- **Requirement:** `is_reply_to_transcription` → False, no transcript → direct chat
- **Code:** `voice_transcription.py:122`: `is_reply_to_transcription` проверяет `reply_to_message`; `direct_chat.py:244–246`: Epic 72 gate — False → direct chat path
- **Evidence:** gate реализован, отсутствие транскрипта корректно routed в direct chat.
- **Verdict:** **SATISFIED**.

### SMR-INV-27: Media marker sanitization — no URL/file_id
- **Requirement:** `_sanitize_media_type` — no URL/file_id в контексте
- **Code:** `media_marker.py:76–88`: `_sanitize_media_type`, возвращает тип без URL/file_id, dialect compliance
- **Evidence:** функция реализована, URL/file_id не попадают в контекст.
- **Verdict:** **SATISFIED**.

### R17: Media marker contract — no URL в контексте
- **Requirement:** media marker не содержит URL
- **Code:** `media_marker.py:44,76–88`: `MEDIA_MARKER_RE` не содержит URL pattern, `MEDIA_TYPES` — только типы, `_sanitize_media_type` compliance
- **Evidence:** contract соблюдён, no URL в контексте.
- **Verdict:** **SATISFIED**.

## Заключение

**Все 17 проверенных internal rows SATISFIED.**

### Для PM (evidence binding)
Все 17 рядов готовы к привязке существующих доказательств:
- SMR-IMG-06, SMR-INV-06, SMR-INV-13..15, SMR-INV-17..27, R17

Источник доказательств: deployed commit 2b7e9c7f, файлы:
- `services/direct_chat_service.py`
- `services/direct_capabilities.py`
- `handlers/direct_chat.py`
- `services/image_generation.py`
- `services/direct_execution.py`
- `services/direct_l1.py`
- `handlers/voice_transcription.py`
- `services/media_marker.py`
- `services/tool_router.py`

### Для Builder
**Не требуется code change.**

---

**INTERNAL AUDIT COMPLETE**
