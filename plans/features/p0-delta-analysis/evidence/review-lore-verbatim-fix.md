# Review: LORE-VERBATIM-GATE fix (eaabb66f) — ограниченное ревью

**Кандидат:** merge `2d4eaad6be2196bd9e0cf304d2b3ed15e4b321b5` (worktree adminbot-wt-rel-p0, tree чистый).
Фикс-коммит `eaabb66f`; 3 файла фикса байт-в-байт совпадают с merge-деревом (diff пуст; merge добавляет только релизный бамп 2.58.132/пины/доки с release-ветки).

**Вердикт: Approved for release.**

## 1. Дифф-аудит `git show eaabb66f` (services/direct_chat_service.py)
- `lore_verbatim_allowed` = kill-switch `LORE_STORY_INTENT_GATE_ENABLED` (OFF → True, легаси) + прямая делегация `_l1.lore_story_delivery_allowed(l1_plan, response_plan)` — семантика идентична гейту подмены `lore_story_override` (та же функция, 0 дрейфа). Никогда не бросает (getattr с default; внутри гейта try/except → True). Композиционных/длинновых требований не добавлено.
- Единственная прод-точка прокидки — construction `ToolContext` в `_handle_turn` (~строка 3328).

## 2. Прогоны (независимые, на кандидате 2d4eaad6)
- `pytest tests/test_p0_delta_routing.py -q` → **66 passed**, 0 failed.
- `pytest tests -k "delta or lore or tool_router" -q --ignore=tests/test_p0_vision_ui_e2e.py` → **539 passed**, 0 failed (дельта +12 новых против базы 527 — совпадает с impl.md Builder'а).

## 3. Story-доставка не сужена (S04/S09)
- `test_s04_creative_story_keeps_verbatim` (creative/story) и `test_s09_historical_recall_keeps_verbatim` (historical_recall): реальный dispatch `compile_lore_story` (in-memory БД + фейк-LLM) → `"ДОСЛОВНО" in out`, `ctx.lore_verbatim_instruction is True`.

## 4. Точки вызова ToolContext
- `_handle_turn` — гейт прокинут (единственное изменение; source-пин `test_call_site_wires_gate_into_tool_context`).
- dig-pregate (dispatch `dig_into_lore`, ~7018) и image-pregate (~7334) — инструкцию не потребляют: `_LORE_RETURN_INSTRUCTION` используется ТОЛЬКО в `compile_lore_story` (tool_router.py:3344/3345), `dig_into_lore` не тронут.
- Фактчек: `factcheck_service.py:1058` по-прежнему `lore_verbatim_instruction=False` — не изменён.

## 5. Квоты/шаблоны/NO_META
- Diff не трогает `tool_router.py`, `prompt_style_blocks.py`, `prompt_registry.py`: текст `_LORE_RETURN_INSTRUCTION` и `NO_META_STRUCTURE_TEXT`/`NO_META_CLOSING_TEXT` без изменений. Новых квот/шаблонов нет.

## Маппинг живых сценариев → фикс
- S03 (research/report) → payload без инструкции, story сохранён как provenance (`"story"` в JSON) — test_s03_period_research_no_verbatim.
- S05 (summarization/summary + легаси task_kind) → без инструкции — test_s05_meta_essay_summarization_no_verbatim, test_s05_legacy_response_plan_kind_no_verbatim.
- S07 (comparison) → без инструкции — test_s07_two_person_comparison_no_verbatim.
- S10 (research/explanation) → без инструкции — test_s10_out_of_range_period_no_verbatim.
- Контролы доставки: S04/S09 — инструкция на месте (см. §3).

Kill-switch OFF → легаси (инструкция везде): test_kill_switch_off_restores_legacy.

**Замечание (non-blocking):** payload-тесты воспроизводят call-site вручную (`lore_verbatim_allowed(plan, rp)` при construction ctx) — wiring в реальный `_handle_turn` защищён source-пином, а не исполнением. Для micro-fix с уже подтверждённым живым дефектом (2.58.132 probe) этого достаточно; финальное подтверждение — пост-деплой live-проба S03/S05/S07/S10 владельцем/DevOps.

**Binding:** ревью действительно только для tree `2d4eaad6`; любое изменение `direct_chat_service.py`/`tool_router.py` инвалидирует.
