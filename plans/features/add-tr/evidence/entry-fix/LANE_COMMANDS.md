# ADTR-ENTRY — точные команды зелёных прогонов (закрытие minor-gap ревью)

**Источник gap:** `review-entry-fix.md` (строка про «две точные команды») —
в evidence лейна ADTR-ENTRY были только логи (`green-core.txt` = 489 passed,
`green-direct-cluster.txt` = 669 passed), а сами команды не записаны; из-за
этого числа были «не сверимы» (10+ наборов дают 669).
**Лейн восстановления:** RE-PIN-25891 (2026-10-19).

## Базовая ревизия и окружение

- **База лейна:** `76b156e0` (рабочее дерево базы + дельта лейна; та же
  дельта теперь закоммичена как `5bc0243c`, на ней и воспроизведено ниже).
- **Окружение логов:** системный Python (`py -3`), не `.venv`: в логах
  видны предупреждения `Unknown config option: timeout/timeout_method`
  (в `.venv` эти опции известны) — учтено при воспроизведении.

## Восстановленные команды (воспроизведены 1:1 на `5bc0243c`, `py -3`)

PowerShell-обёртка этого окружения **не раскрывает** wildcard для `py -3`
(pytest получает литерал `tests/test_direct*.py` → «file or directory not
found»), поэтому файлы записаны явным списком; ядро команды — те же 13
`test_direct*.py` (алфавитно).

```powershell
# green-core.txt → «489 passed, 2 warnings»
py -3 -m pytest tests/test_direct_chat.py tests/test_direct_chat_concurrency.py tests/test_direct_chat_handlers.py tests/test_direct_chat_lore_inject.py tests/test_direct_chat_prompts.py tests/test_direct_chat_relations_inject.py tests/test_direct_context_capacity_asap3.py tests/test_direct_context_composer_asap3.py tests/test_direct_context_scenarios_asap3.py tests/test_direct_decision_matrix_asap3.py tests/test_direct_fallback_recompose_asap32.py tests/test_direct_llm_decision_asap32.py tests/test_direct_two_call_round1022.py tests/test_mca07_retrieval_context_round1027.py

# green-direct-cluster.txt → «669 passed, 2 warnings»
py -3 -m pytest tests/test_direct_chat.py tests/test_direct_chat_concurrency.py tests/test_direct_chat_handlers.py tests/test_direct_chat_lore_inject.py tests/test_direct_chat_prompts.py tests/test_direct_chat_relations_inject.py tests/test_direct_context_capacity_asap3.py tests/test_direct_context_composer_asap3.py tests/test_direct_context_scenarios_asap3.py tests/test_direct_decision_matrix_asap3.py tests/test_direct_fallback_recompose_asap32.py tests/test_direct_llm_decision_asap32.py tests/test_direct_two_call_round1022.py tests/test_asap7_direct_l1.py tests/test_asap8_v6_wc_direct_d03.py tests/test_asap8_v6_wc_direct_d04.py tests/test_asap8_v6_wc_direct_matrix.py tests/test_tool_chains_round1026.py tests/test_tool_coordinator_round1026.py tests/test_budget_global_toggle_round1024.py
```

Проверка на дереве кандидата (`5bc0243c`, окно RE-PIN-25891):

| Набор | Прогон | Строка лога |
|---|---|---|
| core (13 `test_direct*.py` = 446 + `test_mca07_retrieval_context_round1027.py` = 43) | `py -3 -m pytest …` | **489 passed, 2 warnings** (= записанной 1:1) |
| direct-cluster (+ `asap7_direct_l1` 37 + `wc_direct_d03/04/matrix` 9/34/15 + `tool_chains` 45 + `tool_coordinator` 56 + `budget_global_toggle` 27) | `py -3 -m pytest …` | **669 passed, 2 warnings** (= записанной 1:1) |

Дополнительно (карточка ревьюера «suites 44/446/585» — тоже воспроизводимо):

```powershell
py -3 -m pytest tests/test_addtr_entry_caption.py                        # 44 passed
py -3 -m pytest tests/test_direct_*.py  → явный список 13 файлов выше      # 446 passed
py -3 -m pytest <13 direct выше> tests/test_addtr_entry_caption.py tests/test_asap7_direct_l1.py tests/test_asap8_v6_wc_direct_d03.py tests/test_asap8_v6_wc_direct_d04.py tests/test_asap8_v6_wc_direct_matrix.py   # 585 passed
```

## Границы восстановления (честно)

- Исходные командные строки **нигде не записаны** (логи поймали только
  вывод; в `green-direct-cluster.txt` PowerShell-эхо сохранило лишь префикс
  `py -3 -m pytest tests/test_asap7_direct_l1.py tests/test_asap8_v6_wc_...`).
- Приведённые команды воспроизводят **числа/предупреждения логов 1:1** на
  ревизии кандидата; полная однозначность файлового набора недоказуема
  (несколько наборов дают 669 — напр. замены `tool_chains`↔`tool_router`
  внутри 128-хвоста). Прочие ограничения, проверенные при восстановлении:
  набор 446+44 (direct+caption) даёт 490, а не 489; `asap7_direct_settings.py`
  исключён (2 пред-существующих падения: `test_migration_v35_idempotent_twice`,
  `test_backup_guard_fires_before_pending_step` — те же, что в `matrix.md`,
  §«Прогоны-регрессии»).
- Отпечаток `closed 22 leaked aiosqlite connection(s)` из 669-лога
  воспроизвести не удалось ни для одного набора, дающего ровно 669
  (утечки состав-зависимы: одиночные файлы не текут, комбинации — текут
  разным числом) → **точный файловый состав 669-лога недоказуем**; при
  этом числа и предупреждения у приведённой реконструкции совпадают 1:1.
  На зелёный исход это не влияет (warning — хозбыт conftest, не провал).
