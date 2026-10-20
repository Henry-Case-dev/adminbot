# CFG-07CG-TAIL — egress-guard на outbound-швах фактчека v2 (07C.1–.6) + наблюдения ревью

- **Лейн:** CFG-07CG-TAIL, 21.10.2026. База: HEAD `7c3a1350` (волна словаря 07cg,
  review-07cg **Approved**). Коммитов НЕТ по брифу — биндинг оркестратора.
- **Дифф:** `services/public_speech_guard.py` (+115/−16 область), `services/factcheck_orchestrator.py`
  (+94), `services/tool_router.py` (+40), `tests/test_cfg07_egress_dictionary.py` (наблюдение 1),
  **новый** `tests/test_cfg07_guard_tail.py` (26 CONTRACT `owner=CFG-07CG-TAIL`).
- **W3-фриз цел:** `factcheck_prompts.py`/`prompt_migrations.py`/каноны — вне диффа.

## 1. Швы guard'а (каждый outbound-payload v2 проходит `public_speech_guard`)

| Шов | Где | Семантика |
|---|---|---|
| **presentation/delivery** (07C.1) | `factcheck_orchestrator._apply_delivery_guard` — после Writer/кеш-хита, ДО `render_factcheck` | FORBIDDEN/overclaim → срез (границы слов, висячая запятая/двоеточие заформулой убраны) + `logger.warning` + `stage_event("egress_guard","flagged")`; honesty-классы и чистые тексты — байт-в-байт; вырожденный остаток → **честный статус**: заголовок реального enum `CheckedVerdict` (renderer'у enum обнуляется — дубликата нет) или `LLMBadResponseError` → 🗿-молчание (fail-soft **не** выдаёт фиктивно уверенный вердикт, 07C.4). Кеш пишет сырой текст; guard идемпотентен, применяется при каждой доставке |
| **persona short_reply** (ambiguous) | `persona_short_reply` после `cleanup_llm_text` | LLM-реплика чистится; вырожденный остаток → пустая строка → прежний пул `FACTCHECK_CLARIFY_PHRASES` |
| **no_claim / attribution_miss / busy / search_error / llm_error / unexpected_error** | `run_factcheck`/`_run_inner` перед каждым `send_chunked_reply`/`_reply` | пулы — honesty-классы → байт-в-байт (18 фраз × 6 пулов pinned тестом); защита от случайного маркера в пуле |
| **tool_route v2** (`fact_check`, 07C.5 «где применимо») | `tool_router._guard_tool_verdict`, только `if v2:` после платного шага | NL-`verdict` tool-ответа (агент ретранслирует в чат) чистится; **машинный JSON-конверт не тронут** (claim/reason/статусы/даты — исключение 07C.5); вырожденный вердикт → структурный `failed` БЕЗ записи прогона и БЕЗ метаречи агенту; сбой → fail-soft passthrough |
| Fail-soft | все швы | двойной контур: `guard_public_text` ловит внутренние исключения → исходный текст; шов ловит сбой импорта/вызова → passthrough + WARNING (паттерн renderer'а). Доставку не рвёт |

**OFF-паритет:** весь guard живёт в v2-контуре — `run_factcheck` диспетчеризуется только за
`_pipeline_v2_enabled()` (pinned `test_pipeline_v2_default_off_and_hot_prio`, CFG-06), в tool_route
— только ветка `if v2:`. Тест `test_off_parity_guard_not_applied`: v2 OFF + spy на
`guard_public_text` → 0 вызовов, payload с маркером байт-в-байт прежний.

## 2. Наблюдения review-07cg

1. **attribution `agg.searches == []`** — **связан с реальным агрегатором**: `svc.aggregator = agg`
   инжектится в retrieval-шов `run_factcheck` (test_cfg07_egress_dictionary.py). Ассерт больше не
   пустышка: если код регрессирует и уйдёт в retrieval после miss, SpyAggregator это зафиксирует.
   Privacy-гарантия (no external search при miss) усилена, не ослаблена.
3. **`honest_failure_is_allowed` + honest_limitation** — расширен allow-путь: новый предикат
   `is_honest_limitation` (класс `HONEST_LIMITATION`: `_NO_LINKS_NOTICE`, insufficient-headline,
   PC-01/PC-09-примеры). Тесты: `test_honest_limitation_in_allow_path`, PC-01 байт-в-байт через
   guard и через delivery-шов (`test_honesty_class_verdict_byte_identical`).
2. **инверсный overclaim** («весь интернет я проверил») — **НЕ добавлен в словарь**: источника в
   корпусе 07a1 для инверсного порядка нет (корпус фиксирует только прямые формы; проверено
   runtime: `claims_total_verification('весь интернет я проверил') == False`). Осознанный остаток
   для владельческого корпуса — расширение только с источником (07A.7, не растущий black-list).
4. **админ-развязка** — runtime-guard принимает `admin_context` (`guard_public_text(...,
   admin_context=True)` → passthrough, тест `test_admin_context_passthrough_dirty_text`);
   механизм развязки готов для не-фактчек швов полного слайса CFG-07C.

## 3. Проверки (все зелёные, EXIT=0)

| Набор | Результат |
|---|---|
| `test_cfg07_guard_tail.py` (новый CONTRACT) | **26 passed** — guard-семантика 9, delivery-шов 6, short_reply/пулы 3, tool_route 4 (+OFF), OFF-паритет 1, в т.ч. honesty-классы байт-в-байт, fail-soft, enum-статус без фиктивного тела |
| `test_cfg07_egress_dictionary.py` | **67 passed** (без регресса; наблюдение 1 усилено) |
| Фактчек-семья CFG-06 (orchestrator/attribution/renderer/tool_route/w6/planner) | passed (в сводном прогоне) |
| `test_unified_core_route_coverage.py` | **18 passed** (шов speech_owner_block не тронут) |
| Samples-регресс (acceptance/factory/категории/fewshot) + smartmodule_phrases/concurrency | **135 passed** |
| tool_router + mca20 temporal | passed |
| **Сводный фокус** (tail+словарь+семья+route-coverage) | **214 passed / 0 failed, EXIT=0** |
| Сводный с samples | 311 passed / 0 failed |

**Сводный фокус (tail+словарь+семья+route-coverage): 214 passed / 0 failed, EXIT=0; c samples — 311/0.**

## 4. Маппинг на строки карты (статусы НЕ тронуты — полный слайс CFG-07C шире лейна; биндинг оркестратора)

| Строка | Что доставлено этим лейном | Остаток слайса |
|---|---|---|
| CFG-07C.1 | guard прямо перед delivery, после Writer, до сериализации (factcheck v2) — стоимость ограничена (детерминированный regex, 0 LLM), факты/ссылки/числа не меняет, analyst/verbalizer-изоляцию не заменяет | — (factcheck-часть) |
| CFG-07C.2 | FORBIDDEN-метаречь/overclaim проверяются; «лог/анализ/проверка» в содержательном контексте чисты (структурный скан словарной волны + тесты) | JSON/role/tag/reason_code-утечки и сырой HTML — в factcheck уже покрыты W3 egress-whitelist + renderer-экранированием; FA-*/MB-10/11/12-детекторы — 07D.5 |
| CFG-07C.3 | детерминированный sanitize с уборкой следов (без огрызков/логических дыр в пределах формулы); bounded retry для смысловой метаречи — НЕ в этом лейне | bounded retry — 07D.5 |
| CFG-07C.4 | честный fail-soft: enum-статус/🗿/пул, никогда не фиктивно уверенный вердикт — тестами | — (factcheck-часть) |
| CFG-07C.5 | factcheck v2 + tool-response (NL-верdict) покрыты; машинный JSON/клеймы/поисковые запросы исключены | Direct/fallback/error, summary/checkup/search/youtube send — другие швы полного слайса |
| CFG-07C.6 | postdeploy live_required — вне офлайн-лейна | postdeploy-проверка при релизе (агентская, техпроверки; live-глаз владельца опционален — standing rule) |

## 5. Сопутствующие находки (классификация)

- **unrelated/pre-existing (2):** `test_mca20_integration_round1045::test_reason_codes_279` и
  `test_mca20_rework1_f1_f2::test_validator_reason_codes_not_extended` — `assert 302 == 301`
  (каталог reason-кодов v6.3 «285→290 (+5 …)» из незакоммиченной asap8-v6-3-волны). Воспроизведено
  на дереве БЕЗ диффа лейна (git stash — тест падает так же). Бриф: «известные вне диффа не
  трогать». Владелец проблемы — asap8-волна/её ревью.
- **related-nonblocking (0):** новых не найдено; UI/визуала изменение не касается.

## 6. Честные остатки (за пределами лейна, зафиксированы)

- bounded retry для смысловой метаречи, FA-*/MB-10/11/12-детекторы — 07D.5;
- инверсный overclaim — остаток корпуса (см. §2.2);
- швы Direct/fallback/error, summary/checkup/search/youtube — полный слайс CFG-07C;
- 07C.6 postdeploy — при релизе.
