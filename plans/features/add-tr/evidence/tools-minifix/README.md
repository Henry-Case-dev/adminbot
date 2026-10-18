# ADTR-TOOLS-MINIFIX — свидетельства лейна (19.10.2026, worktree, БЕЗ коммита)

Лейн: `ADTR-TOOLS-MINIFIX` (writer). Задача: минимальный фикс §ADD-TR.3 п.4
(health/checkup-capability в живом L1-контуре) + фиксация свободной формы
генерации + bounded-аудит инвентаря. Файлы активных лейнов (ENTRY, GRID)
не трогались; правок в `handlers/direct_chat.py`,
`services/direct_chat_service.py`, `web/static/app.css` и их тестах нет.

## Изменённые файлы (sha256-12 на момент сдачи, git diff = +63 строки в 3 файлах)

| файл | sha256-12 | суть |
|---|---|---|
| `services/direct_capabilities.py` | `bbdaddc6901a` | `CAPABILITY_TOOLS["health"] = ("get_bot_health",)` (:46) — capability в resolved-наборе L1 |
| `services/capability_registry.py` | `f560b21793e1` | `CHECKUP_KEY` (+_TOKEN_KEYS) :85/:91; билдер `_build_health` :571-606; диспетчер :700 |
| `services/direct_execution.py` | `8785f554f4a0` | дет. шаг `health_N → get_bot_health {}` в `derive_simple_steps` :295-306 |
| `tests/test_addtr_tools_minifix.py` | `dadbedc29653` | новый файл, 15 тестов, `TEST-LIFECYCLE: CONTRACT owner=ADTR-TOOLS` |

Дифф целиком: `candidate-diff.patch`.

## RED → GREEN

- RED: `red.txt` — до правок (13-тестовая редакция файла) 10 failed /
  3 passed (падали: capability не резолвится/не анонсируется, реестр не
  знает `health`, нет дет. шага, нет данных в Writer). 3 passed —
  REUSE-пины (канон «чекап», свободная форма «надо нарисовать» через
  смысловую дверь).
- GREEN: `green-minifix.txt` (финальная редакция файла, 15/15) и
  `green-cluster.txt` (478 passed: затронутые сьюты L1/capability/direct/
  checkup/ENTRY в финальной редакции).
- Дополнительно после фикса добавлены два INTEGRATION-теста (реальный
  `ToolRouter` + полный `handle` → L2): оба зелёные; в RED-снимке их нет —
  они создавались как интеграционная проверка уже исправленного контура
  (честная граница RED-доказательства).

Команды:

```
py -3 -m pytest tests/test_addtr_tools_minifix.py -q
py -3 -m pytest tests/test_addtr_tools_minifix.py tests/test_asap7_direct_l1.py \
  tests/test_soul1_capability_registry.py tests/test_soul1_capability_intent.py \
  tests/test_soul1_capability_fallbacks.py tests/test_tool_calling_round1015.py \
  tests/test_checkup_handlers.py tests/test_asap8_v6_wc_direct_d04.py \
  tests/test_asap8_v6_wc_direct_d03.py tests/test_asap8_v6_wc_direct_matrix.py \
  tests/test_direct_chat_handlers.py tests/test_addtr_entry_caption.py -q
```

Дополнительные прогоны финальной редакции: `tests/test_asap5_cover_manifest_web.py`
+ `tests/test_asap7_cover_preview.py` — 25 passed; `tests/test_soul1_w6_speech_ui.py`
+ `tests/test_unified_image_request_round1026.py` +
`tests/test_image_generation_round1023.py` — 109 passed; суммарно по всем
прогонам этого лейна 0 падений в затронутых зонах.

## Привязка к требованиям карты (для PM/Reviewer)

| требование | что даёт лейн | статус |
|---|---|---|
| `M-ADTR-TOOLS-E2E` (get_bot_health-часть) | код-цепочка L1→tool→handler→данные→Writer (15 тестов) | unit/интеграция ✅; **live — postdeploy** |
| `M-ADTR-TOOLS-FIVEFACTS` | `checkup-five-facts.md` — стадии разведены, смешения нет | ✅ (diagnostics-часть) |
| `M-ADTR-TOOLS-REUSE-SOUL5` | новый реестр/пайплайн НЕ создан: переиспользованы `capability_registry`/существующий `get_bot_health`; дифф +63 строки | ✅ |
| `M-ADTR-VERIFY-S6` (свободная форма gen) | `test_free_form_draw_reaches_single_image_workflow` | unit ✅; live — postdeploy |
| `M-ADTR-VERIFY-S12` («чекап» + свободная форма) | канон 0g не задет (2 теста) + новый маршрут здоровья | unit ✅; live — postdeploy |
| `ADTR-REG-AUDIT` (п.5 инвентарь) | `audit-inventory.md` | ✅ документально |

## Цепочка (п.2 брифа) — что подтверждено по коду

`available_capabilities` («ДОСТУПНЫЕ ВОЗМОЖНОСТИ» L1) → план
`capabilities_needed:["health"]` → `_l1_tool_subset` анонсирует схему
`get_bot_health` → `simple_tools` шаг `{}` → `ToolRouter._get_bot_health`
(тот же путь, что 0g: `CheckupLogsFetcher.fetch → CheckupService.checkup`)
→ evidence/`tool_context` → L2 Writer. См. `checkup-five-facts.md`
(стадии названы раздельно) и `announce-vocabulary.txt`.

## Свободная форма генерации (п.4 брифа) — факт без правок ENTRY

«Бот, надо нарисовать X» уже доходит до image-контура существующими
путями: регекс-быстрый путь его не ловит (`ig.is_image_keyword` = False),
но смысловая дверь `detect_action_intent` (`need`+`нарисовать` → actionable)
и §5.10-дверь `_l1_capability_consistency` (routing fix в том же ходу →
`_image_pre_gate_block(intent_confirms=True)` → `maybe_handle_keyword`)
ведут к ровно одной генерации. Зафиксировано тестом
`test_free_form_draw_reaches_single_image_workflow` (gen_calls == 1,
l1_planner == 1). **Правка ENTRY-файлов не потребовалась** — дожим не нужен.

## Аудит инвентаря (п.5) — `audit-inventory.md`

14 тулов × (schema → capability → деривация → гейты → прод-статус).
Исправлен один доказанный дефект (`get_bot_health` — 0 вызовов и
недостижимость из L1). Зафиксированы наблюдения: дет. деривация
`image_understanding` целится в текущее сообщение (владелец —
VISION-FIX-CORE/ADTR-VERIFY S2); `health` не в UI-витрине; `get_bot_health`
вне `METERED_TOOLS` (ADR-1026-15 D3) — смоук-контроль стоимости у Reviewer.

## Осталось на postdeploy (живые вызовы)

1. «бот, как состояние сервера?» / «проверь логи» в рабочем чате →
   ожидаемо: план L1 (`plan_meta.capabilities` содержит `health`) →
   `TOOL_CALL get_bot_health` → `TOOL_CALL_COMPLETE status=ok` →
   ответ Writer'а с реальными данными (не «всё нормально» из памяти).
2. «чекап» — канон 0g не изменился (контроль отсутствия регресса).
3. «бот, надо нарисовать X» — одна генерация, одно списание.
4. Telegram-доставка отчёта: отдельного `delivery`-лога у чекапа нет —
   смотреть ответ в чате (живой контур).
