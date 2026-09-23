# S10 `summary-deploy-round1026` — §114 предполётный harness (чек-лист)

- **Фича:** S10 (Эпик 2, §107/§114/§115/§117), **ADR-1026-12 D3** (REQ-S10-06/-07/-08; SC-06…SC-08).
- **Модуль:** `tests/test_summary_deploy_round1026.py` (класс `TestSec114Scenarios`, 11 тестов).
- **Дата:** 24.09.2026. **Автор:** @Builder (Step 4).
- **База:** reuse S9/Harness-паттернов S6: реальные `run_l1` → `build_fact_package` → `run_l2` → форматтер на детерминированных L1/L2-JSON; шпионы `telegram_send.send_text`/`send_rich_message` и `image_generation.generate_image_verbose`.
- **Жёсткий инвариант:** **0 реальных отправок** Telegram/обложек. Обеспечен шпионами + guard-функциями, которые бросают `AssertionError` при любом обходе (`services.telegram_send.*`, `services.image_generation.generate_image_verbose`).
- **Порядок «проверка → деплой» (§114):** harness выполняется локально, **до** деплоя; тестовые результаты **не публикуются** в основной чат (0 sends). Деплой — за @DevOps (T-3478) после этой проверки.

## Таблица «сценарий → тест → результат»

| # | §114 сценарий | Тест (`tests/test_summary_deploy_round1026.py`) | Результат |
|---|---|---|---|
| 1 | Несколько параллельных разговоров | `TestSec114Scenarios::test_scenario_01_parallel_conversations` (:201) | **PASS** — 3 чата параллельно, по 2 вызова, по 1 публикации |
| 2 | Короткие важные ответы | `::test_scenario_02_short_important_answers` (:214) | **PASS** — «да»/«нет» доходят до статьи |
| 3 | Длинные сообщения | `::test_scenario_03_long_messages` (:223) | **PASS** — cap входа не ломает пайплайн |
| 4 | `reply_to` | `::test_scenario_04_reply_to` (:232) | **PASS** — цепочка ответа обрабатывается |
| 5 | Упоминания | `::test_scenario_05_mentions` (:241) | **PASS** — `@user` штатно |
| 6 | Почти пустой лог | `::test_scenario_06_almost_empty_log` (:250) | **PASS** — 1 сообщение → статья, без падения |
| 7 | Невалидный JSON L1 | `::test_scenario_07_invalid_json_l1_fail_closed` (:259) | **PASS** — fail-closed §106, L2 не вызывается, 0 публикаций |
| 8 | Ошибка LLM | `::test_scenario_08_llm_error_no_publication` (:272) | **PASS** — публикации нет, `SUMMARY_FAILED`/degraded |
| 9 | Ошибка генерации обложки | `::test_scenario_09_cover_error_plain_fallback` (:282) | **PASS** — rich не отправлялся, текст публикуется (plain §105) |
| 10 | Rich Message с H1 | `::test_scenario_10_rich_message_h1` (:301) | **PASS** — `<img>` → `<h1>` → `<p>`; `content_format="html"` |
| 11 | Обычный текстовый fallback | `::test_scenario_11_plain_text_fallback` (:326) | **PASS** — `<b>title</b>` + абзацы, без `<h1>` |

**Итог §114: 11/11 сценариев покрыто и зелёное; 0 публикаций тестовых результатов в основной чат.**

## Прогон

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120 tests/test_summary_deploy_round1026.py
→ 25 passed   (11 §114 + активация/роутинг/границы, см. evidence.md §3)
```

## Связанные инварианты, проверяемые в том же модуле

- **2-вызовность** (`await_count == 2`) — каждый успешный сценарий.
- **R17** — `TestBounds::test_r17_no_raw_text_in_logs` (секрет в доставке, но не в логах).
- **SC-01/SC-03** — `TestActivation::test_code_default_is_on` / `test_run_reaches_hybrid_without_manual_action` / `test_explicit_false_is_kill_switch`.
- **SC-04/SC-05** — `TestFilterAndRouting`.
- **D1/AST** — `TestBounds::test_run_logic_ast_identical_to_baseline` (логика `_run`/`_run_hybrid_l2`/резолва не менялась).
